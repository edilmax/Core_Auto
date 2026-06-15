"""
CORE_AUTO / Tavola VIP - Fase 37: Notifiche (consegna voucher post-pagamento).

Dopo la conferma del pagamento il cliente riceve in automatico il voucher. La
consegna NON deve MAI rompere la conferma del pagamento (isolamento totale) e deve
essere RESILIENTE (un canale intermittente o giu' non perde il voucher).

Architettura = **Variante D** (isolato + retry + FALLBACK multi-canale), vincitrice
di un benchmark a 4 (inline / isolato-1-tentativo / isolato-retry / isolato-retry+
fallback): solo D consegna sia su guasto transitorio sia con il canale primario
giu', senza MAI propagare un'eccezione. Il fallback multi-canale e' gia' la porta
per l'innesto di WhatsApp (Increment #5): bastera' registrare un
`WhatsAppNotificatore` e metterlo nell'ordine di priorita'.

Compartimento stagno: un `Notificatore` astratto (StubNotificatore per i test,
EmailNotificatore reale via SMTP, futuro WhatsAppNotificatore). Email via smtplib
(stdlib): assente la config SMTP -> 'non_configurato' (degrada, non rompe).
"""
from __future__ import annotations

import logging
import os
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any, Dict, Mapping, Optional, Sequence

logger = logging.getLogger("core_auto.notifiche")


@dataclass(frozen=True)
class EsitoNotifica:
    ok: bool
    canale: str = ""
    motivo: str = ""   # "inviata"|"non_configurato"|"destinatario_mancante"|"errore"|"tutti_falliti"


@dataclass(frozen=True)
class Notifica:
    """Messaggio multi-canale: `recapiti` mappa canale->destinatario (es.
    {'email': 'x@y.it', 'whatsapp': '+39...'}) -> il router sceglie/ripiega."""
    oggetto: str
    corpo: str
    recapiti: Mapping[str, str] = field(default_factory=dict)


class Notificatore(ABC):
    """Un canale di consegna. `invia` NON deve sollevare: ritorna l'esito."""
    canale: str = ""

    @abstractmethod
    def invia(self, destinatario: str, oggetto: str, corpo: str) -> EsitoNotifica: ...


class StubNotificatore(Notificatore):
    """Deterministico per test: puo' fallire le prime `fallisci_volte` chiamate
    (guasto transitorio) o essere `sempre_giu`. Registra cio' che consegna."""

    def __init__(self, canale: str = "email", fallisci_volte: int = 0,
                 sempre_giu: bool = False) -> None:
        self.canale = canale
        self._fk = fallisci_volte
        self._giu = sempre_giu
        self.chiamate = 0
        self.inviate: list = []

    def invia(self, destinatario: str, oggetto: str, corpo: str) -> EsitoNotifica:
        self.chiamate += 1
        if not destinatario:
            return EsitoNotifica(False, self.canale, "destinatario_mancante")
        if self._giu or self.chiamate <= self._fk:
            return EsitoNotifica(False, self.canale, "errore")
        self.inviate.append((destinatario, oggetto, corpo))
        return EsitoNotifica(True, self.canale, "inviata")


class EmailNotificatore(Notificatore):
    """Invio email reale via SMTP (stdlib). Config da env SMTP_HOST/PORT/USER/PASS/
    FROM. Mai solleva: assente la config -> 'non_configurato'; errore SMTP ->
    'errore' (il router ritenta/ripiega)."""

    canale = "email"

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None,
                 user: Optional[str] = None, password: Optional[str] = None,
                 mittente: Optional[str] = None, timeout: float = 10.0) -> None:
        # `None` => prendi dall'env; stringa vuota => forza non-configurato (testabile).
        self._host = host if host is not None else os.environ.get("SMTP_HOST", "")
        self._port = int(port or os.environ.get("SMTP_PORT", "587") or 587)
        self._user = user if user is not None else os.environ.get("SMTP_USER", "")
        self._pass = password if password is not None else os.environ.get("SMTP_PASS", "")
        self._from = (mittente if mittente is not None
                      else (os.environ.get("SMTP_FROM", "") or self._user))
        self._timeout = timeout

    def _configurato(self) -> bool:
        return bool(self._host and self._from)

    def invia(self, destinatario: str, oggetto: str, corpo: str) -> EsitoNotifica:
        if not destinatario:
            return EsitoNotifica(False, self.canale, "destinatario_mancante")
        if not self._configurato():
            return EsitoNotifica(False, self.canale, "non_configurato")
        try:
            msg = EmailMessage()
            msg["From"] = self._from
            msg["To"] = destinatario
            msg["Subject"] = oggetto
            msg.set_content(corpo)
            with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as s:
                try:
                    s.starttls()
                except smtplib.SMTPException:
                    pass  # server senza TLS (es. sandbox): si procede
                if self._user:
                    s.login(self._user, self._pass)
                s.send_message(msg)
            return EsitoNotifica(True, self.canale, "inviata")
        except Exception:
            logger.warning("Email: invio fallito (-> il router ritenta/ripiega)",
                           exc_info=True)
            return EsitoNotifica(False, self.canale, "errore")


class RouterNotifiche:
    """Consegna RESILIENTE (Variante D): prova i canali nell'ordine di priorita',
    con RETRY su ciascuno; al primo successo si ferma. ISOLATA: non solleva MAI,
    anche se un notificatore difettoso lancia. Predisposta per WhatsApp: basta
    registrare un altro canale e includerlo nella priorita'."""

    def __init__(self, tentativi: int = 3) -> None:
        self._reg: Dict[str, Notificatore] = {}
        self._tentativi = max(1, tentativi)

    def registra(self, notificatore: Notificatore) -> "RouterNotifiche":
        self._reg[notificatore.canale] = notificatore
        return self

    def canali(self) -> Sequence[str]:
        return tuple(self._reg)

    def invia(self, notifica: Notifica,
              priorita: Optional[Sequence[str]] = None) -> EsitoNotifica:
        ordine = priorita if priorita is not None else tuple(self._reg)
        for canale in ordine:
            dest = notifica.recapiti.get(canale)
            n = self._reg.get(canale)
            if not dest or n is None:
                continue
            for _ in range(self._tentativi):
                try:
                    esito = n.invia(dest, notifica.oggetto, notifica.corpo)
                except Exception:
                    logger.error("Notificatore '%s' ha sollevato (isolato)",
                                 canale, exc_info=True)
                    esito = EsitoNotifica(False, canale, "errore")
                if esito.ok:
                    return esito
        return EsitoNotifica(False, "", "tutti_falliti")


def componi_voucher(*, codice_voucher: str, alloggio: str,
                    check_in: str, check_out: str) -> "tuple[str, str]":
    """Costruisce (oggetto, corpo) dell'email/messaggio di conferma col voucher."""
    oggetto = f"Voucher Tavola VIP - {alloggio}"
    corpo = ("Gentile ospite,\n"
             "la sua prenotazione e' CONFERMATA.\n\n"
             f"Codice voucher: {codice_voucher}\n"
             f"Tavolo/alloggio: {alloggio}\n"
             f"Dal {check_in} al {check_out}\n\n"
             "Conservi questo voucher: le servira' all'arrivo.\nGrazie.")
    return oggetto, corpo


class ServizioNotifiche:
    """Costruisce e consegna la notifica del voucher tramite il router resiliente."""

    def __init__(self, router: RouterNotifiche,
                 priorita: Sequence[str] = ("email",)) -> None:
        self._router = router
        self._priorita = tuple(priorita)

    def invia_voucher(self, *, recapiti: Mapping[str, str], codice_voucher: str,
                      alloggio: str, check_in: str, check_out: str) -> EsitoNotifica:
        oggetto, corpo = componi_voucher(
            codice_voucher=codice_voucher, alloggio=alloggio,
            check_in=check_in, check_out=check_out)
        return self._router.invia(Notifica(oggetto, corpo, dict(recapiti)),
                                  self._priorita)


def crea_servizio_notifiche(priorita: Sequence[str] = ("email",)) -> ServizioNotifiche:
    """Factory di default: router con EmailNotificatore (da env SMTP_*). Predisposto
    per aggiungere WhatsApp (#5) con un .registra() e l'ordine di priorita'."""
    router = RouterNotifiche().registra(EmailNotificatore())
    return ServizioNotifiche(router, priorita)
