"""
CORE_AUTO - Fase 86: Provider Email (voucher all'ospite via SMTP).

Gemello di fase85 (Stripe): l'invio email era un'astrazione mai cablata. Questo modulo la
riempie con SMTP a ZERO dipendenze (smtplib + email.mime, stdlib - niente librerie di
terze parti). E' GATED dalla configurazione: senza host/credenziali SMTP il sistema non
invia nulla (come oggi); appena metti SMTP_HOST/SMTP_USER/SMTP_PASSWORD, ogni prenotazione
confermata manda all'ospite il voucher (con il link e la chiave di self check-in) - SENZA
toccare il codice.

L'invio e' ISOLATO: se l'SMTP e' giu', `invia` ritorna False e la prenotazione resta
valida (l'email e' best-effort, mai blocca l'incasso). Compone con fase83 (book) e il
voucher firmato (fase81/firma).

VINCITRICE DEL BENCHMARK (4 modi di mandare le email):
  V3 'provider iniettato gated da env + smtplib stdlib isolato'. Zero dipendenze,
  accensione senza modifiche, fail-safe. Le altre perdono: V1 'API email SaaS (SendGrid)'
  = dipendenza + costo per email; V2 'hardcode credenziali' = segreto nel codice; V4
  'invio sincrono bloccante senza isolamento' = un SMTP lento/giu' romperebbe il book.

SOPRAVVIVENZA TOTALE: `invia` non solleva MAI (eccezione -> False); destinatario non
valido -> False; `send` iniettabile (test deterministici senza SMTP reale); nessuna
config -> provider non creato. STARTTLS, login solo se le credenziali ci sono.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("core_auto.email")


class ProviderEmail:
    """Invia email via SMTP. `send(destinatario, oggetto, html) -> bool` e' iniettabile
    (default: smtplib reale) per testare senza un server SMTP."""

    def __init__(self, host: str, port: int, user: str, password: str, mittente: str, *,
                 send: Optional[Callable[[str, str, str], bool]] = None) -> None:
        self._host = host
        self._port = port if isinstance(port, int) and not isinstance(port, bool) else 587
        self._user = user
        self._password = password
        self._mittente = mittente or user
        self._send = send or self._send_smtp

    def invia(self, destinatario: Any, oggetto: str, corpo_html: str) -> bool:
        """Invia una email. Best-effort: ritorna True/False, non solleva MAI."""
        if not (isinstance(destinatario, str) and "@" in destinatario):
            return False
        try:
            return bool(self._send(destinatario, str(oggetto), str(corpo_html)))
        except Exception:
            logger.warning("Email: invio fallito (ISOLATO -> False)", exc_info=True)
            return False

    def _send_smtp(self, destinatario: str, oggetto: str,
                   html: str) -> bool:  # pragma: no cover
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(html, "html", "utf-8")
        msg["Subject"] = oggetto
        msg["From"] = self._mittente
        msg["To"] = destinatario
        # Porta 465 = SSL IMPLICITO (SMTPS) -> serve SMTP_SSL (con SMTP normale la connessione
        # appende fino al timeout). Porta 587/25 = SMTP + STARTTLS. Timeout corto: mai bloccare.
        if int(self._port) == 465:
            with smtplib.SMTP_SSL(self._host, self._port, timeout=10) as s:
                if self._user:
                    s.login(self._user, self._password)
                s.sendmail(self._mittente, [destinatario], msg.as_string())
        else:
            with smtplib.SMTP(self._host, self._port, timeout=10) as s:
                try:
                    s.starttls()
                except smtplib.SMTPException:
                    pass
                if self._user:
                    s.login(self._user, self._password)
                s.sendmail(self._mittente, [destinatario], msg.as_string())
        return True


def crea_provider_email(host: Optional[str], port: int = 587, user: str = "",
                        password: str = "", mittente: str = "", *,
                        send: Any = None) -> Optional[ProviderEmail]:
    """Factory GATED: provider solo se c'e' un host SMTP; altrimenti None (niente email)."""
    if not (isinstance(host, str) and host.strip()):
        return None
    return ProviderEmail(host.strip(), port, user, password, mittente or user, send=send)


def corpo_voucher_html(titolo_alloggio: str, riferimento: str, check_in: str,
                       check_out: str, voucher_url: str) -> str:
    """Corpo HTML dell'email di conferma (semplice, robusto). XSS-safe."""
    import html
    e = html.escape
    link = ('<p><a href="%s" style="background:#1e3c72;color:#fff;padding:.6rem 1.2rem;'
            'border-radius:8px;text-decoration:none">Apri il tuo voucher</a></p>'
            % e(voucher_url)) if voucher_url else ""
    return (
        "<div style=\"font-family:sans-serif;max-width:480px\">"
        "<h2 style=\"color:#1e3c72\">BookinVIP - Prenotazione confermata</h2>"
        "<p>%s</p><p>Riferimento: <strong>%s</strong><br>"
        "Dal %s al %s</p>%s"
        "<p style=\"color:#5e6f8d;font-size:.85rem\">Il voucher contiene il codice per il "
        "check-in autonomo.</p></div>"
    ) % (e(titolo_alloggio), e(riferimento), e(check_in), e(check_out), link)
