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

RETRY ANTI-SINGHIOZZO (collaudo 2026-07-15): in prod un invio e' fallito per un timeout
transitorio dell'SMTP Hostinger (SMTPServerDisconnected) e l'email era PERSA per sempre
— grave se era il link di pagamento di un su-richiesta approvato. Ora un errore di RETE
(eccezione) viene ritentato UNA volta con connessione fresca dopo una breve pausa; un
False "pulito" del provider NON viene ritentato (ha gia' risposto no). Attesa massima
comunque limitata (2 tentativi x timeout 10s + pausa), mai bloccante per sempre.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("core_auto.email")


class ProviderEmail:
    """Invia email via SMTP. `send(destinatario, oggetto, html) -> bool` e' iniettabile
    (default: smtplib reale) per testare senza un server SMTP. `sleep` iniettabile per
    testare il retry senza attese reali."""

    def __init__(self, host: str, port: int, user: str, password: str, mittente: str, *,
                 send: Optional[Callable[[str, str, str], bool]] = None,
                 tentativi: int = 2, pausa_s: float = 1.5,
                 sleep: Optional[Callable[[float], None]] = None) -> None:
        self._host = host
        self._port = port if isinstance(port, int) and not isinstance(port, bool) else 587
        self._user = user
        self._password = password
        self._mittente = mittente or user
        self._send = send or self._send_smtp
        ok_int = isinstance(tentativi, int) and not isinstance(tentativi, bool)
        self._tentativi = max(1, tentativi) if ok_int else 2
        self._pausa_s = pausa_s
        self._sleep = sleep or time.sleep

    def invia(self, destinatario: Any, oggetto: str, corpo_html: str) -> bool:
        """Invia una email. Best-effort: ritorna True/False, non solleva MAI.
        Errore di rete (eccezione) -> UN retry con connessione fresca; False pulito
        del provider -> nessun retry (il server ha gia' risposto)."""
        if not (isinstance(destinatario, str) and "@" in destinatario):
            return False
        # ANTI HEADER-INJECTION (choke-point unico, vale per OGNI provider): un a-capo
        # dentro destinatario/oggetto finirebbe negli header SMTP (es. "\r\nBcc: ...") ->
        # posta di massa dal nostro dominio -> blacklist. Il soggetto puo' contenere testo
        # scritto dall'host (titolo annuncio): qualunque whitespace collassa in spazio.
        destinatario = destinatario.strip()
        if "\r" in destinatario or "\n" in destinatario:
            logger.warning("Email: destinatario con a-capo RIFIUTATO (header injection)")
            return False
        oggetto = " ".join(str(oggetto).split())
        for tentativo in range(1, self._tentativi + 1):
            try:
                return bool(self._send(destinatario, oggetto, str(corpo_html)))
            except Exception:
                logger.warning("Email: invio fallito (tentativo %d/%d, ISOLATO)",
                               tentativo, self._tentativi, exc_info=True)
                if tentativo < self._tentativi:
                    try:
                        self._sleep(self._pausa_s)
                    except Exception:
                        pass  # perfino uno sleep rotto non deve far sollevare `invia`
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


def corpo_voucher_html(titolo_alloggio: str, codice: str, check_in: str,
                       check_out: str, voucher_url: str, pin: str = "",
                       payment_url: str = "") -> str:
    """Corpo HTML dell'email di conferma (semplice, robusto). XSS-safe. `codice` = codice
    prenotazione leggibile (BVIP-XXXX-XXXX); `pin` = PIN check-in (4 cifre), uguali all'host.
    `payment_url`: se presente, la prenotazione è RISERVATA ma da pagare -> bottone di
    pagamento in cima (per il su-richiesta approvato è l'unico canale del cliente)."""
    import html
    e = html.escape
    link = ('<p><a href="%s" style="background:#1e3c72;color:#fff;padding:.6rem 1.2rem;'
            'border-radius:8px;text-decoration:none">Apri il tuo voucher</a></p>'
            % e(voucher_url)) if voucher_url else ""
    blocco_pin = ('<br>PIN check-in: <strong style="font-size:1.1rem;color:#1e3c72">%s</strong>'
                  % e(str(pin))) if pin else ""
    if payment_url:
        titolo_email = "BookinVIP - Approvata! Completa il pagamento"
        blocco_pagamento = (
            '<p style="background:#fff4e5;border-radius:10px;padding:.7rem 1rem;color:#8a5200">'
            "La tua prenotazione &egrave; stata <strong>approvata e riservata</strong>: "
            "completa il pagamento per confermarla.</p>"
            '<p><a href="%s" style="background:#155724;color:#fff;padding:.7rem 1.4rem;'
            'border-radius:8px;text-decoration:none;font-weight:bold">'
            "&#128179; Completa il pagamento</a></p>" % e(payment_url))
    else:
        titolo_email = "BookinVIP - Prenotazione confermata"
        blocco_pagamento = ""
    return (
        "<div style=\"font-family:sans-serif;max-width:480px\">"
        "<h2 style=\"color:#1e3c72\">%s</h2>%s"
        "<p>%s</p><p>Codice prenotazione: <strong style=\"letter-spacing:.05em\">%s</strong>%s<br>"
        "Dal %s al %s</p>%s"
        "<p style=\"color:#5e6f8d;font-size:.85rem\">Conserva questa email: mostra il codice "
        "(e il PIN) all'arrivo. Dal voucher puoi vedere o annullare la prenotazione.</p></div>"
    ) % (e(titolo_email), blocco_pagamento, e(titolo_alloggio), e(codice), blocco_pin,
         e(check_in), e(check_out), link)


def corpo_preventivo_html(titolo_alloggio: str, check_in: str, check_out: str,
                          righe: Any, url_prenota: str, lingua: str = "it") -> str:
    """Email 'il tuo preventivo' (recupero ONESTO: parte solo se l'ospite la chiede
    col clic). `righe` = [(etichetta, importo_formattato), ...]. XSS-safe. Niente
    urgenza artificiale: solo il riepilogo e il link per completare quando vuole."""
    import html
    e = html.escape
    it = str(lingua or "it").lower().startswith("it")
    titolo_email = "Il tuo preventivo" if it else "Your quote"
    sotto = ("Ecco il riepilogo che hai richiesto per" if it
             else "Here is the summary you requested for")
    btn = "Completa la prenotazione" if it else "Complete your booking"
    nota = ("Nessun impegno e nessun addebito: le date restano libere finché "
            "qualcuno non prenota. Questa è l'unica email: niente promemoria."
            if it else
            "No commitment, no charge: the dates stay open until someone books. "
            "This is the only email: no reminders.")
    corpo_righe = "".join(
        "<tr><td style=\"padding:.2rem 0;color:#4a5b7a\">%s</td>"
        "<td style=\"padding:.2rem 0 .2rem 1.2rem;text-align:right\">"
        "<strong>%s</strong></td></tr>" % (e(str(k)), e(str(v)))
        for k, v in (righe or ()) if v)
    link = ('<p><a href="%s" style="background:#0f4c3a;color:#fff;padding:.7rem 1.4rem;'
            'border-radius:8px;text-decoration:none;font-weight:bold">%s</a></p>'
            % (e(url_prenota), e(btn))) if url_prenota else ""
    return (
        "<div style=\"font-family:sans-serif;max-width:480px\">"
        "<h2 style=\"color:#0f4c3a\">%s</h2>"
        "<p>%s <strong>%s</strong><br>%s → %s</p>"
        "<table style=\"width:100%%;border-collapse:collapse\">%s</table>%s"
        "<p style=\"color:#5e6f8d;font-size:.85rem\">%s</p></div>"
    ) % (e(titolo_email), e(sotto), e(titolo_alloggio), e(check_in), e(check_out),
         corpo_righe, link, e(nota))


def corpo_reset_password_html(link: str) -> str:
    """Email 'password dimenticata' (C2 2026-07-20): magic-link 30 minuti, single-use.
    Onesta: dice chiaro che se non l'hai chiesta tu, puoi ignorarla. XSS-safe."""
    import html
    e = html.escape
    return (
        "<div style=\"font-family:sans-serif;max-width:480px\">"
        "<h2 style=\"color:#0f4c3a\">BookinVIP - Reimposta la password</h2>"
        "<p>Hai chiesto di reimpostare la password del tuo account host.</p>"
        "<p><a href=\"%s\" style=\"background:#0f4c3a;color:#fff;padding:.7rem 1.4rem;"
        "border-radius:8px;text-decoration:none;font-weight:700\">Scegli la nuova password"
        "</a></p>"
        "<p style=\"color:#5e6f8d;font-size:.85rem\">Il link vale <strong>30 minuti</strong> "
        "e funziona <strong>una sola volta</strong>. Se non hai chiesto tu il cambio, "
        "ignora questa email: la tua password resta quella di sempre.</p></div>"
    ) % e(link)


def corpo_benvenuto_host_html(pannello_url: str) -> str:
    """Email di benvenuto all'host appena registrato: conferma che l'account esiste
    (e fa emergere SUBITO un refuso nell'email: se non ti arriva, l'indirizzo è
    sbagliato e puoi ri-registrarti prima di caricare annunci). XSS-safe."""
    import html
    e = html.escape
    return (
        "<div style=\"font-family:sans-serif;max-width:480px\">"
        "<h2 style=\"color:#0f4c3a\">Benvenuto su BookinVIP! 👑</h2>"
        "<p>Il tuo account host è pronto. In 3 passi sei online:</p>"
        "<ol><li>Pubblica il tuo alloggio (titolo, prezzo, foto).</li>"
        "<li>Apri le date libere sul calendario.</li>"
        "<li>Ricevi le prenotazioni e approva con un tocco.</li></ol>"
        "<p><a href=\"%s\" style=\"background:#0f4c3a;color:#fff;padding:.7rem 1.4rem;"
        "border-radius:8px;text-decoration:none;font-weight:700\">Apri il pannello host"
        "</a></p>"
        "<p style=\"color:#5e6f8d;font-size:.85rem\">0%% di commissioni all'ospite, 5%% sul "
        "tuo link diretto, 10%% dal marketplace. Nessun costo fisso.</p></div>"
    ) % e(pannello_url)


def corpo_promemoria_checkin_html(titolo_alloggio: str, voucher_url: str) -> str:
    """Email post-check-in: 'com'è andata?'. Se tutto ok, il cliente non deve fare nulla
    (l'host viene pagato). Se c'è un problema, lo segnala ENTRO 24h dal voucher. XSS-safe."""
    import html
    e = html.escape
    link = ('<p><a href="%s" style="background:#1e3c72;color:#fff;padding:.6rem 1.2rem;'
            'border-radius:8px;text-decoration:none">Apri il voucher</a></p>'
            % e(voucher_url)) if voucher_url else ""
    return (
        "<div style=\"font-family:sans-serif;max-width:480px\">"
        "<h2 style=\"color:#1e3c72\">BookinVIP - Com'è andata?</h2>"
        "<p>Ciao! Speriamo che il tuo soggiorno a <strong>%s</strong> stia andando bene.</p>"
        "<p style=\"background:#e7f6ec;border-radius:10px;padding:.7rem 1rem;color:#155724\">"
        "✅ <strong>Se è tutto come descritto, non devi fare nulla.</strong></p>"
        "<p style=\"background:#fff4e5;border-radius:10px;padding:.7rem 1rem;color:#8a5200\">"
        "⚠️ <strong>Se c'è un problema, segnalalo ENTRO 24 ore</strong> dall'arrivo, dal tuo "
        "voucher (pulsante \"Segnala un problema\"). Passate le 24h senza segnalazioni, il "
        "soggiorno è considerato regolare.</p>%s"
        "<p style=\"color:#5e6f8d;font-size:.82rem\">Grazie per aver scelto BookinVIP.</p></div>"
    ) % (e(titolo_alloggio), link)
