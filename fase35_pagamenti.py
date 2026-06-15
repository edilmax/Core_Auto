"""
CORE_AUTO / Tavola VIP MVP - Fase 35: Pagamenti (PSP reale, link + webhook).

Genera un LINK DI PAGAMENTO HTTP: il cliente lo apre, paga la sua quota, il PSP
notifica via webhook (FIRMATO), il sistema conferma la prenotazione (split/escrow)
ed emette il voucher. Tutto in centesimi interi (fase17/Stripe parlano la stessa
lingua: importi in cents).

Compartimento stagno (come il Cervello LLM): un `PagamentoProvider` astratto con
- `StubPagamentoProvider`: deterministico, webhook firmato HMAC -> test al 100%
  senza rete ne' credenziali;
- `StripeProvider`: reale, import LAZY di `stripe`; assente la libreria o la chiave
  -> FALLISCE in modo chiaro (fail-closed), senza rompere l'import del modulo.

Il `ServizioPagamenti` cuce il provider al MotorePrenotazioni (fase34): alla
notifica 'pagato' chiama `conferma_pagamento` + `emetti_voucher` (idempotenti).
La firma del webhook e' VERIFICATA (compare_digest) prima di toccare lo stato:
un webhook non firmato NON conferma nulla.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("core_auto.pagamenti")


@dataclass(frozen=True)
class LinkPagamento:
    url: str
    riferimento: str          # id sessione PSP (correlazione)


@dataclass(frozen=True)
class EventoPagamento:
    tipo: str                 # "pagato" | "ignorato" | "non_valido"
    pagamento_id: Optional[int] = None


class PagamentoProvider(ABC):
    """Contratto di un PSP: crea un link di pagamento e verifica i suoi webhook."""

    @abstractmethod
    def crea_link(self, *, pagamento_id: int, importo_cents: int,
                  descrizione: str, email: str) -> LinkPagamento: ...

    @abstractmethod
    def verifica_webhook(self, payload: bytes, firma: str) -> EventoPagamento: ...


class StubPagamentoProvider(PagamentoProvider):
    """PSP finto deterministico per test/sviluppo. Webhook firmato HMAC-SHA256
    (stesso modello di Stripe): nessuna rete, riproducibile, ma la firma e' VERA."""

    def __init__(self, segreto: str = "stub-secret",
                 base_url: str = "https://pay.local/checkout") -> None:
        self._segreto = segreto.encode()
        self._base = base_url

    def crea_link(self, *, pagamento_id: int, importo_cents: int,
                  descrizione: str, email: str) -> LinkPagamento:
        ref = f"stub_{pagamento_id}_{importo_cents}"
        return LinkPagamento(f"{self._base}/{ref}", ref)

    def firma_evento(self, pagamento_id: int, pagato: bool = True) -> "tuple[bytes, str]":
        """Helper di test: produce (payload, firma) come farebbe il PSP."""
        payload = json.dumps({"pagamento_id": pagamento_id,
                              "pagato": bool(pagato)}).encode()
        firma = hmac.new(self._segreto, payload, hashlib.sha256).hexdigest()
        return payload, firma

    def verifica_webhook(self, payload: bytes, firma: str) -> EventoPagamento:
        attesa = hmac.new(self._segreto, payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(attesa, str(firma or "")):
            return EventoPagamento("non_valido")
        try:
            dati = json.loads(payload)
        except (ValueError, TypeError):
            return EventoPagamento("non_valido")
        if not dati.get("pagato"):
            return EventoPagamento("ignorato")
        try:
            return EventoPagamento("pagato", int(dati["pagamento_id"]))
        except (KeyError, ValueError, TypeError):
            return EventoPagamento("non_valido")


class StripeProvider(PagamentoProvider):
    """PSP reale (Stripe Checkout). Import LAZY: l'assenza di `stripe` o della
    chiave NON rompe il modulo, ma usarlo senza configurazione FALLISCE chiaro."""

    def __init__(self, api_key: Optional[str] = None,
                 webhook_secret: Optional[str] = None,
                 success_url: str = "https://tavolavip.example/ok",
                 cancel_url: str = "https://tavolavip.example/ko") -> None:
        self._api_key = api_key or os.environ.get("STRIPE_API_KEY", "")
        self._wh_secret = webhook_secret or os.environ.get("STRIPE_WEBHOOK_SECRET", "")
        self._success, self._cancel = success_url, cancel_url

    def _stripe(self):
        try:
            import stripe  # noqa: lazy, opzionale
        except ImportError as exc:
            raise RuntimeError("Stripe richiesto ma 'stripe' non e' installato "
                               "(pip install stripe).") from exc
        if not self._api_key:
            raise RuntimeError("STRIPE_API_KEY mancante (fail-closed).")
        stripe.api_key = self._api_key
        return stripe

    def crea_link(self, *, pagamento_id: int, importo_cents: int,
                  descrizione: str, email: str) -> LinkPagamento:
        stripe = self._stripe()
        sess = stripe.checkout.Session.create(
            mode="payment", success_url=self._success, cancel_url=self._cancel,
            customer_email=email or None,
            client_reference_id=str(pagamento_id),
            metadata={"pagamento_id": str(pagamento_id)},
            line_items=[{"quantity": 1, "price_data": {
                "currency": "eur", "unit_amount": importo_cents,
                "product_data": {"name": descrizione or "Prenotazione Tavola VIP"}}}])
        return LinkPagamento(sess.url, sess.id)

    def verifica_webhook(self, payload: bytes, firma: str) -> EventoPagamento:
        stripe = self._stripe()
        if not self._wh_secret:
            raise RuntimeError("STRIPE_WEBHOOK_SECRET mancante (fail-closed).")
        try:
            evento = stripe.Webhook.construct_event(payload, firma, self._wh_secret)
        except Exception:
            logger.warning("Stripe: firma webhook non valida (-> ignorato)")
            return EventoPagamento("non_valido")
        if evento["type"] != "checkout.session.completed":
            return EventoPagamento("ignorato")
        sess = evento["data"]["object"]
        if sess.get("payment_status") != "paid":
            return EventoPagamento("ignorato")
        ref = (sess.get("metadata") or {}).get("pagamento_id") \
            or sess.get("client_reference_id")
        try:
            return EventoPagamento("pagato", int(ref))
        except (TypeError, ValueError):
            return EventoPagamento("non_valido")


@dataclass(frozen=True)
class EsitoWebhook:
    esito: str                # "confermato"|"ignorato"|"non_valido"|"pagamento_sconosciuto"
    prenotazione_id: Optional[int] = None
    voucher: Optional[str] = None


class ServizioPagamenti:
    """Cuce il PSP al MotorePrenotazioni: crea il link e, al webhook 'pagato',
    conferma la prenotazione ed emette il voucher (entrambi idempotenti)."""

    def __init__(self, motore: Any, provider: PagamentoProvider) -> None:
        self._motore = motore
        self._provider = provider

    def crea_link_pagamento(self, *, pagamento_id: int, importo_cents: int,
                            email: str = "",
                            descrizione: str = "Prenotazione Tavola VIP") -> LinkPagamento:
        return self._provider.crea_link(
            pagamento_id=pagamento_id, importo_cents=importo_cents,
            descrizione=descrizione, email=email)

    def gestisci_webhook(self, payload: bytes, firma: str) -> EsitoWebhook:
        ev = self._provider.verifica_webhook(payload, firma)
        if ev.tipo != "pagato":
            return EsitoWebhook(ev.tipo)  # "non_valido" | "ignorato"
        pren_id = self._motore.conferma_pagamento(ev.pagamento_id)
        if pren_id is None:
            return EsitoWebhook("pagamento_sconosciuto")
        voucher = self._motore.emetti_voucher(pren_id)
        return EsitoWebhook("confermato", pren_id, voucher)


def crea_provider_pagamenti(*, success_url: Optional[str] = None,
                            cancel_url: Optional[str] = None) -> PagamentoProvider:
    """Factory env-driven (default-safe): se `STRIPE_API_KEY` e' presente usa il
    PSP REALE (StripeProvider), altrimenti lo StubPagamentoProvider (sviluppo).
    Nessuna chiamata di rete alla costruzione: la chiave si valida al primo uso."""
    if os.environ.get("STRIPE_API_KEY"):
        kw = {}
        if success_url:
            kw["success_url"] = success_url
        if cancel_url:
            kw["cancel_url"] = cancel_url
        return StripeProvider(**kw)
    logger.warning("STRIPE_API_KEY assente -> StubPagamentoProvider (solo sviluppo, "
                   "NON per produzione).")
    return StubPagamentoProvider(
        segreto=os.environ.get("STUB_PSP_SECRET", "stub-dev-secret"))
