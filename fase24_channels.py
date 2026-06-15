"""
CORE_AUTO - Fase 24 / BLOCCO 4: Tentacoli Social (Channel Adapters).

Astrazione unica per i canali social (WhatsApp, Instagram, Telegram, ...): ogni
canale e' un `ChannelAdapter` registrato in un `ChannelRegistry`. L'invio NON
avviene in linea: i messaggi passano per l'**Outbox** (Fase 16), che fornisce
gia' consegna at-least-once, retry+backoff, DLQ, idempotency-key in uscita e
dispatch concorrente. Cosi' "centinaia di chat" diventano N messaggi outbox
consegnati in parallelo, con fail-safe ereditato.

Compartimento stagno (North Star): se un canale cade (adapter solleva o
restituisce False) il messaggio finisce in retry/DLQ del SUO record, mentre il
core, la web app e gli altri canali continuano a girare. Modulo isolato:
l'aggancio all'Outbox e la pubblicazione usano import lazy.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("core_auto.channels")

# Topic Outbox unico per l'invio sui canali (il routing avviene per `channel`).
TOPIC_CHANNEL_SEND = "channel_send"


@dataclass
class ChannelMessage:
    """Messaggio normalizzato verso un canale social."""
    channel: str                       # "whatsapp" | "instagram" | "telegram" | ...
    recipient: str                     # numero / user-id / chat-id
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class ChannelAdapter(ABC):
    """Adapter di un singolo canale. `send` ritorna True se consegnato; in caso
    di fallimento ritorni False o sollevi: l'Outbox gestira' retry/DLQ."""

    name: str = ""

    @abstractmethod
    def send(self, msg: ChannelMessage) -> bool: ...


class ChannelRegistry:
    """Registro dei canali + handler Outbox che instrada al canale giusto."""

    def __init__(self) -> None:
        self._adapters: Dict[str, ChannelAdapter] = {}

    def register(self, adapter: ChannelAdapter) -> None:
        if not adapter.name:
            raise ValueError("ChannelAdapter.name obbligatorio")
        self._adapters[adapter.name] = adapter
        logger.info("Canale registrato: %s", adapter.name)

    def get(self, name: str) -> Optional[ChannelAdapter]:
        return self._adapters.get(name)

    def channels(self) -> List[str]:
        return list(self._adapters)

    def deliver(self, payload: Dict[str, Any]) -> bool:
        """Handler Outbox: instrada `payload` all'adapter del canale indicato.

        Fail-safe: canale ignoto o adapter che solleva -> log + False (il
        messaggio resta nel suo record e finisce in retry/DLQ, MAI perso in
        silenzio e MAI propaga l'errore al dispatcher/altri canali)."""
        channel = payload.get("channel")
        adapter = self._adapters.get(channel)
        if adapter is None:
            logger.error("Canale social non registrato: %r (msg scartato in DLQ)",
                         channel)
            return False
        # Propaga un delivery-id stabile (dall'Outbox) per la dedup lato canale.
        meta = dict(payload.get("metadata") or {})
        outbox = payload.get("_outbox") or {}
        if "message_id" in outbox:
            meta["delivery_id"] = f"outbox-{outbox['message_id']}"
        try:
            return bool(adapter.send(ChannelMessage(
                channel=channel,
                recipient=str(payload.get("recipient", "")),
                text=str(payload.get("text", "")),
                metadata=meta)))
        except Exception:
            logger.error("Adapter canale '%s' ha sollevato (-> retry/DLQ)",
                         channel, exc_info=True)
            return False


class StubChannelAdapter(ChannelAdapter):
    """Adapter in-memory per test/sviluppo: registra i messaggi, nessun I/O reale.
    `fail=True` simula un canale che non consegna (per testare retry/DLQ)."""

    def __init__(self, name: str = "stub", fail: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.sent: List[ChannelMessage] = []

    def send(self, msg: ChannelMessage) -> bool:
        if self.fail:
            return False
        self.sent.append(msg)
        return True


class TelegramAdapter(ChannelAdapter):
    """Adapter Telegram reale (best-effort) via Config.TELEGRAM_* + requests.
    Se non configurato, considera il messaggio consegnato (no-op) per non
    intasare la DLQ in sviluppo. `recipient` sovrascrive il chat-id di default."""

    name = "telegram"

    def __init__(self, timeout: int = 10) -> None:
        self._timeout = timeout

    def send(self, msg: ChannelMessage) -> bool:
        try:
            import requests  # lazy
            from fase13_protocollo_finale import Config
            if not Config.TELEGRAM_BOT_TOKEN:
                logger.warning("Telegram non configurato: messaggio considerato consegnato")
                return True
            chat_id = msg.recipient or Config.TELEGRAM_CHAT_ID
            if not chat_id:
                logger.warning("Telegram: nessun chat-id, messaggio considerato consegnato")
                return True
            r = requests.post(
                f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": msg.text, "parse_mode": "HTML"},
                timeout=self._timeout)
            return r.status_code == 200
        except Exception:
            logger.error("Telegram adapter fallito (-> retry/DLQ)", exc_info=True)
            return False


def collega_a_outbox(dispatcher: Any, registry: ChannelRegistry,
                     topic: str = TOPIC_CHANNEL_SEND) -> None:
    """Registra il routing dei canali come handler Outbox per `topic`."""
    dispatcher.register(topic, registry.deliver)


def pubblica_messaggio(publisher: Any, channel: str, recipient: str, text: str,
                       metadata: Optional[Dict[str, Any]] = None,
                       max_retries: int = 3) -> int:
    """Accoda un messaggio social sull'Outbox (consegna at-least-once).

    Ritorna l'id outbox. La consegna effettiva avviene dal dispatcher, con
    retry/DLQ/concorrenza gia' garantiti dall'Outbox."""
    from fase16_outbox import OutboxMessage  # import lazy (isolamento)
    return publisher.publish_standalone(OutboxMessage(
        topic=TOPIC_CHANNEL_SEND,
        payload={"channel": channel, "recipient": recipient, "text": text,
                 "metadata": metadata or {}},
        partition_key=channel,
        max_retries=max_retries))
