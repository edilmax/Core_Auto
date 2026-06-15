"""
CORE_AUTO / Tavola VIP - Fase 40: Agente IA reale agganciato al booking.

Il salto "avanguardia": il cliente CHATTA, l'agente COMPRENDE l'intento, propone il
Tavolo VIP, crea la prenotazione e manda il LINK Stripe. Costruito sul cervello
gia' esistente (ResilientBrain, FASE 25) con un `LLMProvider` REALE (Anthropic SDK).

Strategia chat->prenotazione = **Variante C** (estrazione STRUTTURATA + validazione),
vincitrice di un benchmark a 3 (regex-free-text / solo-intento / strutturata):
l'unica con ZERO prenotazioni sbagliate (la regex prenota su input incompleto
"indovinando" il check-out; il solo-intento non prenota mai). Sulle richieste
incomplete l'agente CHIEDE invece di indovinare.

PRINCIPIO FERREO (come fase17/27): il DENARO non si delega MAI all'IA. L'LLM fa
solo comprensione del linguaggio (intento + parametri); l'importo e la commissione
li calcola il SISTEMA. La chiave ANTHROPIC_API_KEY sta SOLO in env (mai nel codice);
l'SDK e' importato LAZY (assente -> errore chiaro, isolato dal ResilientBrain).
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

from fase25_brain import LLMProvider, ResilientBrain
from fase34_prenotazioni import RichiestaPrenotazione

logger = logging.getLogger("core_auto.agente_booking")

_BLOCCO_JSON = re.compile(r"\{.*\}", re.DOTALL)


# ─────────────────────────────────────────────────────────────────────────────
# Provider LLM REALE (Anthropic SDK) - lazy, fail-closed, iniettabile per i test
# ─────────────────────────────────────────────────────────────────────────────
class AnthropicLLMProvider(LLMProvider):
    """Implementazione reale di `LLMProvider.genera` via Anthropic SDK. Modello di
    default `claude-opus-4-8` (override con ANTHROPIC_MODEL). La chiave viene SOLO
    da ANTHROPIC_API_KEY (o iniettata). `client` iniettabile -> test senza rete."""

    def __init__(self, *, api_key: Optional[str] = None, model: Optional[str] = None,
                 max_tokens: int = 1024, system: Optional[str] = None,
                 client: Any = None) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model or os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")
        self._max_tokens = max_tokens
        self._system = system
        self._client = client

    def _ottieni_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import anthropic  # import LAZY: assente -> errore chiaro (isolato dal brain)
        except ImportError as exc:
            raise RuntimeError("Anthropic SDK non installato (pip install anthropic).") from exc
        if not self._api_key:
            raise RuntimeError("ANTHROPIC_API_KEY mancante (fail-closed).")
        return anthropic.Anthropic(api_key=self._api_key)

    def genera(self, prompt: str) -> str:
        client = self._ottieni_client()
        kwargs = {"model": self._model, "max_tokens": self._max_tokens,
                  "messages": [{"role": "user", "content": prompt}]}
        if self._system:
            kwargs["system"] = self._system
        resp = client.messages.create(**kwargs)
        return "".join(b.text for b in resp.content
                       if getattr(b, "type", None) == "text")


# ─────────────────────────────────────────────────────────────────────────────
# Agente conversazionale di prenotazione (Variante C)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RispostaBooking:
    testo: str
    azione: str                # "prenotata"|"chiarimento"|"non_disponibile"|"info"|"errore"
    intento: str = ""
    prenotazione_id: Optional[int] = None
    payment_url: Optional[str] = None


_PROMPT = (
    "Sei l'assistente prenotazioni di Tavola VIP. Estrai dal messaggio del cliente "
    "un JSON con: intento (uno tra: prenotazione, domanda, sconosciuto), alloggio "
    "(es. 'VIP-12'), check_in e check_out (formato YYYY-MM-DD), email, telefono. "
    "Includi solo i campi presenti. Rispondi ESCLUSIVAMENTE con il JSON, senza altro.\n"
    "Messaggio: {messaggio}"
)


class AgenteBooking:
    """Orchestratore chat->prenotazione. L'LLM (via ResilientBrain, isolato) estrae
    intento+parametri; il SISTEMA calcola il denaro, crea la prenotazione e genera
    il link Stripe. Prenota SOLO se la richiesta e' completa e valida."""

    def __init__(self, provider: LLMProvider, motore: Any, servizio: Any, *,
                 prezzo_notte_cents: int = 10000, commissione_bps: int = 1000,
                 **brain_kw: Any) -> None:
        self._brain = ResilientBrain(provider, **brain_kw)
        self._motore = motore
        self._servizio = servizio
        self._prezzo = prezzo_notte_cents
        self._comm_bps = commissione_bps

    def gestisci_chat(self, messaggio: str, *, email_default: str = "",
                      telefono_default: str = "") -> RispostaBooking:
        r = self._brain.genera(_PROMPT.format(messaggio=messaggio))
        if not r.ok:                       # IA giu'/lenta -> isolamento, niente prenotazione
            return RispostaBooking("Sistema momentaneamente occupato, riprova tra poco.",
                                   "errore")
        dati = self._estrai_json(r.testo)
        if dati is None:
            return RispostaBooking("Non ho capito bene, puoi riformulare la richiesta?",
                                   "info")
        intento = str(dati.get("intento", "")).strip()
        if intento != "prenotazione":
            return RispostaBooking("Sono qui per le prenotazioni dei Tavoli VIP: "
                                   "dimmi il tavolo e le date.", "info", intento)

        alloggio = str(dati.get("alloggio", "")).strip()
        check_in = str(dati.get("check_in", "")).strip()
        check_out = str(dati.get("check_out", "")).strip()
        email = (str(dati.get("email", "")).strip() or email_default)
        telefono = (str(dati.get("telefono", "")).strip() or telefono_default)
        notti = self._notti(check_in, check_out)
        if not alloggio or notti <= 0:
            return RispostaBooking("Per prenotare mi servono il tavolo e le date "
                                   "(check-in e check-out). Me li indichi?",
                                   "chiarimento", intento)

        # DENARO DAL SISTEMA (mai dall'IA): importo = notti * prezzo; commissione in bps.
        importo = self._prezzo * notti
        commissione = importo * self._comm_bps // 10000
        esito = self._motore.crea(RichiestaPrenotazione(
            alloggio_id=alloggio, ospite_nome="", ospite_email=email,
            check_in=check_in, check_out=check_out, importo_totale_cents=importo,
            commissione_cents=commissione, ospite_telefono=telefono))
        if not esito.ok:
            if esito.motivo == "non_disponibile":
                return RispostaBooking(f"Il tavolo {alloggio} non e' disponibile dal "
                                       f"{check_in} al {check_out}. Vuoi altre date?",
                                       "non_disponibile", intento)
            return RispostaBooking("Non riesco a completare: controlla i dati della "
                                   "richiesta.", "errore", intento)

        link = self._servizio.crea_link_pagamento(
            pagamento_id=esito.pagamento_id, importo_cents=importo, email=email)
        return RispostaBooking(
            f"Perfetto! Ho bloccato il tavolo {alloggio} dal {check_in} al "
            f"{check_out}. Completa il pagamento qui: {link.url}",
            "prenotata", intento, esito.prenotazione_id, link.url)

    def stop(self) -> None:
        self._brain.stop()

    # --- parsing/validazione (deterministici) ---
    @staticmethod
    def _estrai_json(testo: str) -> Optional[dict]:
        m = _BLOCCO_JSON.search(testo or "")
        if not m:
            return None
        try:
            d = json.loads(m.group(0))
            return d if isinstance(d, dict) else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _notti(check_in: str, check_out: str) -> int:
        try:
            ci = datetime.date.fromisoformat(check_in)
            co = datetime.date.fromisoformat(check_out)
        except (ValueError, TypeError):
            return 0
        return (co - ci).days
