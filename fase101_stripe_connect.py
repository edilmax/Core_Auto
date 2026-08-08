"""
CORE_AUTO - Fase 101: Stripe Connect split-all'origine (Modulo 3 - tutela forfettario).

Lo split avviene NEL gateway al checkout: il 90% (netto host) va DIRETTO al conto connesso
dell'host (destination charge), solo la nostra commissione (application_fee) resta a noi →
legalmente solo il 10% è nostro fatturato (intermediario puro, soglia 85k tutelata).
ZERO dipendenze (REST via urllib stdlib). GATED da STRIPE_SECRET_KEY + host_account.
`fetch` iniettabile → test senza rete. ISOLATO: errore → None, mai solleva.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("core_auto.stripe_connect")

STRIPE_URL = "https://api.stripe.com/v1/checkout/sessions"


def _intero_pos(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def costruisci_params(prezzo_guest_cents: int, application_fee_cents: int,
                      host_account: str, *, valuta: str = "eur",
                      riferimento: str = "", success_url: str = "",
                      cancel_url: str = "") -> Optional[Dict[str, str]]:
    """Params Checkout con destination charge: il lordo va al conto host, l'application_fee
    (nostra commissione) resta a noi. None se importi invalidi o fee >= lordo."""
    if not (_intero_pos(prezzo_guest_cents) and host_account):
        return None
    fee = application_fee_cents if isinstance(application_fee_cents, int) and \
        not isinstance(application_fee_cents, bool) else -1
    if fee < 0 or fee >= prezzo_guest_cents:
        return None
    return {
        "mode": "payment",
        "success_url": success_url or "https://bookinvip.com/grazie.html",
        "cancel_url": cancel_url or "https://bookinvip.com/annullato.html",
        "line_items[0][price_data][currency]": (valuta or "eur").lower(),
        "line_items[0][price_data][product_data][name]": "BookinVIP %s" % (riferimento or ""),
        "line_items[0][price_data][unit_amount]": str(prezzo_guest_cents),
        "line_items[0][quantity]": "1",
        "payment_intent_data[application_fee_amount]": str(fee),
        "payment_intent_data[transfer_data][destination]": str(host_account),
        "client_reference_id": str(riferimento or ""),
    }


class ProviderStripeConnect:
    """Crea una Checkout Session con split-all'origine verso il conto connesso dell'host."""

    def __init__(self, secret_key: str, *, success_url: str = "", cancel_url: str = "",
                 valuta: str = "eur",
                 fetch: Optional[Callable[[str, bytes, Dict[str, str]], Dict[str, Any]]]
                 = None) -> None:
        self._key = secret_key or ""
        self._ok = success_url
        self._ko = cancel_url
        self._valuta = (valuta or "eur").lower()
        self._fetch = fetch or self._fetch_reale

    def crea_link(self, dati: Dict[str, Any]) -> Optional[str]:
        """dati: prezzo_guest_cents, commissione_cents, host_account, riferimento, valuta."""
        try:
            if not self._key or not isinstance(dati, dict):
                return None
            params = costruisci_params(
                dati.get("prezzo_guest_cents"), dati.get("commissione_cents"),
                str(dati.get("host_account", "")),
                valuta=dati.get("valuta", self._valuta),
                riferimento=str(dati.get("riferimento", "")),
                success_url=self._ok, cancel_url=self._ko)
            if params is None:
                return None
            body = urllib.parse.urlencode(params).encode()
            headers = {"Authorization": "Bearer " + self._key,
                       "Content-Type": "application/x-www-form-urlencoded"}
            r = self._fetch(STRIPE_URL, body, headers)
            return r.get("url") if isinstance(r, dict) else None
        except Exception:
            logger.warning("StripeConnect.crea_link fallita (ISOLATA)", exc_info=True)
            return None

    def _fetch_reale(self, url: str, body: bytes,
                     headers: Dict[str, str]) -> Dict[str, Any]:  # pragma: no cover
        import urllib.request
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())


def crea_provider_stripe_connect(secret_key: Optional[str], *, success_url: str = "",
                                 cancel_url: str = "", valuta: str = "eur",
                                 fetch: Any = None) -> Optional[ProviderStripeConnect]:
    if not secret_key:
        return None
    return ProviderStripeConnect(secret_key, success_url=success_url,
                                 cancel_url=cancel_url, valuta=valuta, fetch=fetch)


# ─────────────────────────────────────────────────────────────────────────────
# ProviderConnect — modello ESCROW del fondatore (charge alla piattaforma come oggi,
# TRANSFER all'host SOLO allo sblocco della garanzia: ok cliente / 24h di silenzio /
# esito controversia). Account "standard" (GRATIS, zero canoni) + Account Link per
# l'onboarding. Transfer IDEMPOTENTE (Idempotency-Key per riferimento: mai doppi
# bonifici anche se il rilascio viene richiamato). GATED + fetch iniettabile + ISOLATO.
# ─────────────────────────────────────────────────────────────────────────────
class ProviderConnect:
    ACCOUNTS = "https://api.stripe.com/v1/accounts"
    LINKS = "https://api.stripe.com/v1/account_links"
    TRANSFERS = "https://api.stripe.com/v1/transfers"

    def __init__(self, secret_key: str, *,
                 fetch: Optional[Callable[[str, bytes, Dict[str, str]], Dict[str, Any]]]
                 = None, fetch_get: Optional[Callable[[str, Dict[str, str]],
                                                      Dict[str, Any]]] = None) -> None:
        self._key = secret_key or ""
        self._fetch = fetch or self._fetch_reale
        self._fetch_get = fetch_get or self._fetch_get_reale

    def _post(self, url: str, params: Dict[str, str],
              idem_key: str = "") -> Optional[Dict[str, Any]]:
        try:
            headers = {"Authorization": "Bearer " + self._key,
                       "Content-Type": "application/x-www-form-urlencoded"}
            if idem_key:
                headers["Idempotency-Key"] = idem_key
            body = urllib.parse.urlencode(params).encode()
            r = self._fetch(url, body, headers)
            return r if isinstance(r, dict) else None
        except Exception as e:
            # ⛔ IL MOTIVO STA NEL CORPO DELLA RISPOSTA, E LO BUTTAVAMO VIA (2026-08-08).
            #    Il fondatore premeva «Collega Stripe» e vedeva `stripe_non_disponibile`;
            #    nei registri restava solo «fallita». Stripe invece rispondeva:
            #    «You must complete your platform profile to use Connect...» -- cioe' ci
            #    diceva esattamente cosa fare. Costo del non leggerlo: 15 minuti per
            #    ritrovare una frase gia' scritta; per un host vero, che se ne va.
            #    REGOLA FERREA 9: di un servizio esterno si scrivono CODICE e MESSAGGIO.
            #    E il livello e' ERROR, non warning: `fase186:263` dichiara di leggere
            #    solo gli ERROR, quindi un warning qui e' un difetto invisibile.
            #    ⛔ E TUTTA LA LETTURA STA DENTRO UN `try`, COMPRESO IL `getattr`.
            #    Prima stava fuori, e il 2026-08-08 ha rotto l'isolamento: `getattr(e,
            #    "read", None)` NON protegge da un'eccezione sollevata dentro
            #    `__getattr__` (sopprime solo AttributeError), e su un HTTPError con
            #    `fp` chiuso e' uscito un `KeyError: 'file'`. Risultato: la diagnostica
            #    esplodeva MENTRE gestiva un'eccezione, e l'errore usciva da `_post`.
            #    L'ha preso `test_stripe_500_sul_transfer_non_solleva`, e a cascata la
            #    prova che il bonifico da fare a mano resti tracciato: un guasto di
            #    Stripe avrebbe potuto far perdere la traccia dei soldi dovuti a un host.
            #    UNA DIAGNOSTICA CHE PUO' SOLLEVARE E' PEGGIO DI NESSUNA DIAGNOSTICA.
            #    ⛔ DUE `try` SEPARATI, e nemmeno lo stato HTTP sta fuori. Alla prima
            #    correzione avevo protetto solo la lettura del corpo, e il
            #    `getattr(e, "code", "?")` dentro la riga di registro passava dallo
            #    STESSO `__getattr__` ostile: `KeyError: 'code'`, e l'errore usciva
            #    di nuovo. Qui NIENTE che tocchi l'oggetto dell'eccezione sta fuori
            #    da un `try`.
            tipo = codice = msg = ""
            stato = "?"
            try:
                stato = e.code
            except Exception:
                pass
            try:
                leggi = getattr(e, "read", None)
                if callable(leggi):
                    err = (json.loads(leggi().decode("utf-8", "replace") or "{}")
                           or {}).get("error", {})
                    tipo = str(err.get("type", ""))
                    codice = str(err.get("code", ""))
                    msg = str(err.get("message", ""))
            except Exception:
                pass                          # corpo illeggibile: resta il resto
            logger.error("Connect POST %s FALLITA: stato=%s tipo=%s codice=%s -- %s",
                         url, stato, tipo or "-", codice or "-",
                         msg or repr(e), exc_info=True)
            return None

    def crea_account(self, email: str = "") -> Optional[str]:
        """Crea l'account connesso dell'host (type=standard: GRATIS). -> acct_... o None."""
        if not self._key:
            return None
        params = {"type": "standard"}
        if isinstance(email, str) and "@" in email:
            params["email"] = email
        r = self._post(self.ACCOUNTS, params)
        acct = r.get("id") if r else None
        return acct if isinstance(acct, str) and acct.startswith("acct_") else None

    def link_onboarding(self, account_id: str, return_url: str,
                        refresh_url: str = "") -> Optional[str]:
        """Link (breve vita) dove l'host completa la registrazione Stripe."""
        if not (self._key and isinstance(account_id, str) and account_id):
            return None
        r = self._post(self.LINKS, {
            "account": account_id, "type": "account_onboarding",
            "return_url": return_url or "https://bookinvip.com/host.html",
            "refresh_url": refresh_url or return_url or "https://bookinvip.com/host.html"})
        url = r.get("url") if r else None
        return url if isinstance(url, str) and url.startswith("http") else None

    def stato_account(self, account_id: str) -> Dict[str, Any]:
        """{pronto: bool, ...}: pronto = puo' RICEVERE i bonifici (payouts_enabled)."""
        if not (self._key and isinstance(account_id, str) and account_id):
            return {"pronto": False}
        try:
            r = self._fetch_get(self.ACCOUNTS + "/" + urllib.parse.quote(account_id),
                                {"Authorization": "Bearer " + self._key})
            if not isinstance(r, dict):
                return {"pronto": False}
            return {"pronto": bool(r.get("payouts_enabled")),
                    "dettagli_inviati": bool(r.get("details_submitted"))}
        except Exception:
            logger.warning("Connect stato_account fallita (ISOLATA)", exc_info=True)
            return {"pronto": False}

    def _fetch_get_reale(self, url: str,
                         headers: Dict[str, str]) -> Dict[str, Any]:  # pragma: no cover
        import urllib.request
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    def trasferisci(self, account_id: str, amount_cents: Any, currency: str,
                    riferimento: str) -> Optional[str]:
        """Sposta il netto host sul suo conto. IDEMPOTENTE per riferimento (Stripe dedupa
        con la stessa Idempotency-Key: mai doppio bonifico). -> tr_... o None."""
        if not (self._key and isinstance(account_id, str) and account_id.startswith("acct_")):
            return None
        if not (isinstance(amount_cents, int) and not isinstance(amount_cents, bool)
                and amount_cents > 0):
            return None
        r = self._post(self.TRANSFERS, {
            "amount": str(amount_cents),
            "currency": (currency or "eur").lower(),
            "destination": account_id,
            "transfer_group": str(riferimento or ""),
            "metadata[riferimento]": str(riferimento or "")},
            idem_key="transfer_" + str(riferimento or account_id))
        tid = r.get("id") if r else None
        return tid if isinstance(tid, str) and tid.startswith("tr_") else None

    def _fetch_reale(self, url: str, body: bytes,
                     headers: Dict[str, str]) -> Dict[str, Any]:  # pragma: no cover
        import urllib.request
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())


def crea_provider_connect(secret_key: Optional[str], *,
                          fetch: Any = None) -> Optional[ProviderConnect]:
    """Factory GATED: senza chiave -> None (tutto resta manuale, come oggi)."""
    if not secret_key:
        return None
    return ProviderConnect(secret_key, fetch=fetch)
