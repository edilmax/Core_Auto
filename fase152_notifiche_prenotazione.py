"""
Fase 152 - Notifiche di prenotazione all'HOST (chiude il buco: oggi solo l'OSPITE riceve
l'email del voucher, l'host non sapeva nulla). Su ogni prenotazione confermata l'host viene
avvisato su PIU' canali (email sempre; WhatsApp se configurato + telefono host noto), con
testo LOCALIZZATO (fase61). La prenotazione e' instant-book: gia' confermata e a calendario
(fase58.blocca atomico) -> il messaggio dice 'confermata, nessuna azione richiesta'.

Vincitrice-del-benchmark: dispatcher multi-canale best-effort ISOLATO (un canale che fallisce
NON blocca gli altri ne' la transazione finanziaria), canali gated/iniettabili, contatto
scelto PER canale (email->email, whatsapp->telefono). Denaro: nessuno qui (solo avvisi).
"""
import json
import logging
import urllib.request
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v18.0"


def _solo_cifre(tel: Any) -> str:
    return "".join(c for c in str(tel or "") if c.isdigit())


def _fetch_post(url: str, headers: Dict[str, str], body: Dict[str, Any]):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:    # pragma: no cover (rete)
        return r.status, r.read().decode("utf-8", "replace")


class CanaleEmailHost:
    """Adatta il provider email (fase86) a canale-avviso host (testo -> HTML semplice)."""
    campo_contatto = "email"

    def __init__(self, email_provider: Any):
        self._ep = email_provider

    def invia(self, destinatario: str, oggetto: str, testo: str) -> bool:
        html = "<p>" + str(testo).replace("\n", "<br>") + "</p>"
        return bool(self._ep.invia(destinatario, oggetto, html))


class CanaleWhatsApp:
    """WhatsApp Cloud API (GATED): avvisa l'host sul suo numero. Richiede WHATSAPP_TOKEN +
    WHATSAPP_PHONE_ID. fetch iniettabile per i test (nessuna rete nei test)."""
    campo_contatto = "telefono"

    def __init__(self, token: str, phone_id: str, *, fetch: Optional[Callable] = None):
        self._token = token or ""
        self._phone_id = phone_id or ""
        self._fetch = fetch or _fetch_post

    def attivo(self) -> bool:
        return bool(self._token and self._phone_id)

    def invia(self, destinatario: str, oggetto: str, testo: str) -> bool:
        if not (self.attivo() and destinatario):
            return False
        url = "%s/%s/messages" % (GRAPH, self._phone_id)
        headers = {"Authorization": "Bearer " + self._token,
                   "Content-Type": "application/json"}
        body = {"messaging_product": "whatsapp", "to": _solo_cifre(destinatario),
                "type": "text", "text": {"body": (str(oggetto) + "\n" + str(testo))[:1024]}}
        try:
            st, _ = self._fetch(url, headers, body)
            return 200 <= int(st) < 300
        except Exception:
            logger.warning("whatsapp host alert fallito (ISOLATO)", exc_info=True)
            return False


def _fetch_form(url: str, headers: Dict[str, str], data: Dict[str, Any]):
    import urllib.parse
    body = urllib.parse.urlencode(data).encode("utf-8")
    h = dict(headers); h["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, method="POST", headers=h)
    with urllib.request.urlopen(req, timeout=10) as r:    # pragma: no cover (rete)
        return r.status, r.read().decode("utf-8", "replace")


class CanaleLine:
    """LINE Notify (Giappone/Thailandia/Taiwan/Indonesia): l'host genera un token personale e
    riceve gli avvisi su LINE. campo_contatto='line_token'."""
    campo_contatto = "line_token"
    API = "https://notify-api.line.me/api/notify"

    def __init__(self, *, fetch: Optional[Callable] = None):
        self._fetch = fetch or _fetch_form

    def invia(self, destinatario: str, oggetto: str, testo: str) -> bool:
        if not destinatario:
            return False
        try:
            st, _ = self._fetch(self.API, {"Authorization": "Bearer " + str(destinatario)},
                                {"message": "\n" + str(oggetto) + "\n" + str(testo)})
            return 200 <= int(st) < 300
        except Exception:
            logger.warning("line notify fallito (ISOLATO)", exc_info=True)
            return False


class CanaleWeChat:
    """WeChat Work robot webhook (Cina): avvisa l'host nel suo canale aziendale WeChat.
    campo_contatto='wechat_webhook' (l'URL del robot, fornito dall'host)."""
    campo_contatto = "wechat_webhook"

    def __init__(self, *, fetch: Optional[Callable] = None):
        self._fetch = fetch or _fetch_post

    def invia(self, destinatario: str, oggetto: str, testo: str) -> bool:
        if not (isinstance(destinatario, str) and destinatario.startswith("http")):
            return False
        try:
            st, _ = self._fetch(destinatario, {"Content-Type": "application/json"},
                                {"msgtype": "text",
                                 "text": {"content": str(oggetto) + "\n" + str(testo)}})
            return 200 <= int(st) < 300
        except Exception:
            logger.warning("wechat fallito (ISOLATO)", exc_info=True)
            return False


class NotificatorePrenotazione:
    """Dispatcher multi-canale. Ogni canale espone `.invia(dest, oggetto, testo)->bool` e
    `.campo_contatto` ('email' | 'telefono'). Best-effort isolato."""

    def __init__(self, canali: Optional[List[Any]] = None):
        self._canali = [c for c in (canali or []) if c is not None]

    def attivo(self) -> bool:
        return bool(self._canali)

    def avvisa(self, contatti: Dict[str, str], oggetto: str, testo: str) -> Dict[str, int]:
        inviati = falliti = 0
        for c in self._canali:
            dest = (contatti or {}).get(getattr(c, "campo_contatto", "email"), "")
            if not dest:
                continue
            try:
                if c.invia(dest, oggetto, testo):
                    inviati += 1
                else:
                    falliti += 1
            except Exception:
                falliti += 1
                logger.warning("canale notifica host fallito (ISOLATO)", exc_info=True)
        return {"inviati": inviati, "falliti": falliti}


def componi_avviso_host(localizzatore: Any, *, alloggio: str, ci: str, co: str,
                        origine: str = "", riferimento: str = "", pin: str = "",
                        link_pannello: str = "", lingua: str = "it"):
    """Testo LOCALIZZATO dell'avviso host (riusa fase61 'nuova_prenotazione'). `riferimento`
    = codice prenotazione leggibile (BVIP-XXXX-XXXX), `pin` = PIN check-in, uguali al cliente."""
    try:
        testo = localizzatore.notifica("nuova_prenotazione", lingua, alloggio=alloggio,
                                       ci=ci, co=co, origine=origine or "—")
    except Exception:
        testo = "Nuova prenotazione: %s dal %s al %s." % (alloggio, ci, co)
    oggetto = "BookinVIP - Nuova prenotazione"
    corpo = (testo +
             (("\n\nCodice prenotazione: %s" % riferimento) if riferimento else "") +
             (("\nPIN check-in: %s" % pin) if pin else "") +
             "\n\nLa prenotazione e' gia' CONFERMATA e segnata a calendario: "
             "nessuna azione richiesta. Al check-in verifica il codice (e il PIN) del cliente." +
             (("\nDettagli e calendario: %s" % link_pannello) if link_pannello else ""))
    return oggetto, corpo


def crea_notificatore_prenotazione(*, email_provider: Any = None,
                                   whatsapp_token: str = "",
                                   whatsapp_phone_id: str = "",
                                   fetch: Optional[Callable] = None,
                                   canali_extra: Optional[List[Any]] = None
                                   ) -> NotificatorePrenotazione:
    """Factory: canale email (se provider) + WhatsApp (se gated-config) + extra iniettabili."""
    canali: List[Any] = []
    if email_provider is not None:
        canali.append(CanaleEmailHost(email_provider))
    wa = CanaleWhatsApp(whatsapp_token, whatsapp_phone_id, fetch=fetch)
    if wa.attivo():
        canali.append(wa)
    # LINE/WeChat: sempre disponibili, scattano solo se l'host ha fornito il proprio contatto
    canali.append(CanaleLine(fetch=fetch))
    canali.append(CanaleWeChat(fetch=fetch))
    if canali_extra:
        canali.extend([c for c in canali_extra if c is not None])
    return NotificatorePrenotazione(canali)
