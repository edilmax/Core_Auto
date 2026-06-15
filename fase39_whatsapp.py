"""
CORE_AUTO / Tavola VIP - Fase 39: Canale WhatsApp (Meta Cloud API).

Innesta WhatsApp nella consegna resiliente della FASE 37 (Variante D: isolato +
retry + fallback). Niente nuovo metodo: `WhatsAppNotificatore` e' un `Notificatore`
che si registra nel `RouterNotifiche`; con la priorita' ('whatsapp','email') il
voucher parte su WhatsApp e ripiega su email se WhatsApp non e' configurato/giu'.

Via scelta (gia' deliberata): **Meta WhatsApp Cloud API DIRETTA** (REST), nessun
BSP, stesso pattern del TelegramAdapter. Invio PROATTIVO -> TEMPLATE approvato con
una variabile di corpo che ospita il voucher/link. `requests` e' importato LAZY:
assente la libreria o la config -> 'non_configurato'/'errore', MAI un'eccezione
propagata (il router ritenta/ripiega). Trasporto iniettabile per i test (no rete).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional, Tuple

from fase37_notifiche import EsitoNotifica, Notificatore

logger = logging.getLogger("core_auto.whatsapp")

# Trasporto: (url, headers, payload_json) -> (status_code, corpo). Per i test.
Trasporto = Callable[[str, dict, dict], Tuple[int, Any]]


class WhatsAppNotificatore(Notificatore):
    """Invia un messaggio TEMPLATE via WhatsApp Cloud API. Mai solleva."""

    canale = "whatsapp"

    def __init__(self, access_token: Optional[str] = None,
                 phone_number_id: Optional[str] = None,
                 template: Optional[str] = None, lang: Optional[str] = None,
                 api_version: Optional[str] = None, timeout: float = 10.0,
                 transport: Optional[Trasporto] = None) -> None:
        self._token = access_token if access_token is not None else os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
        self._phone_id = phone_number_id if phone_number_id is not None else os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
        self._template = template or os.environ.get("WHATSAPP_TEMPLATE_NAME", "link_pagamento")
        self._lang = lang or os.environ.get("WHATSAPP_TEMPLATE_LANG", "it")
        self._ver = api_version or os.environ.get("WHATSAPP_API_VERSION", "v21.0")
        self._timeout = timeout
        self._transport = transport

    def _configurato(self) -> bool:
        return bool(self._token and self._phone_id)

    def _payload(self, destinatario: str, corpo: str) -> dict:
        return {"messaging_product": "whatsapp", "to": destinatario,
                "type": "template",
                "template": {"name": self._template,
                             "language": {"code": self._lang},
                             "components": [{"type": "body", "parameters": [
                                 {"type": "text", "text": corpo}]}]}}

    def _post(self, url: str, headers: dict, payload: dict) -> Tuple[int, Any]:
        if self._transport is not None:          # iniettato dai test (no rete)
            return self._transport(url, headers, payload)
        import requests                          # lazy: assente -> eccezione gestita
        r = requests.post(url, headers=headers, json=payload, timeout=self._timeout)
        try:
            corpo = r.json()
        except ValueError:
            corpo = r.text
        return r.status_code, corpo

    def invia(self, destinatario: str, oggetto: str, corpo: str) -> EsitoNotifica:
        if not destinatario:
            return EsitoNotifica(False, self.canale, "destinatario_mancante")
        if not self._configurato():
            return EsitoNotifica(False, self.canale, "non_configurato")
        url = f"https://graph.facebook.com/{self._ver}/{self._phone_id}/messages"
        headers = {"Authorization": f"Bearer {self._token}",
                   "Content-Type": "application/json"}
        try:
            status, _ = self._post(url, headers, self._payload(destinatario, corpo))
        except Exception:
            logger.warning("WhatsApp: invio fallito (-> il router ripiega)",
                           exc_info=True)
            return EsitoNotifica(False, self.canale, "errore")
        if 200 <= status < 300:
            return EsitoNotifica(True, self.canale, "inviata")
        logger.warning("WhatsApp: Cloud API ha risposto %s", status)
        return EsitoNotifica(False, self.canale, "errore")


def crea_servizio_notifiche_completo(priorita: Optional[tuple] = None) -> Any:
    """Factory: router con Email SEMPRE + WhatsApp se WHATSAPP_ENABLED e' acceso.
    Default-off: WhatsApp spento -> identico al solo-email (FASE 37)."""
    from fase37_notifiche import (RouterNotifiche, EmailNotificatore,
                                  ServizioNotifiche)
    router = RouterNotifiche().registra(EmailNotificatore())
    abilitato = os.environ.get("WHATSAPP_ENABLED", "").strip().lower() in (
        "1", "true", "yes", "on")
    if abilitato:
        router.registra(WhatsAppNotificatore())
        ordine = priorita or ("whatsapp", "email")   # WhatsApp prima, email fallback
    else:
        ordine = priorita or ("email",)
    return ServizioNotifiche(router, ordine)
