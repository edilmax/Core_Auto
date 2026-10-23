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
from typing import Any, Callable, Dict, List, Optional

from fase85_pagamenti_stripe import _motivo_errore

logger = logging.getLogger("core_auto.stripe_connect")

STRIPE_URL = "https://api.stripe.com/v1/checkout/sessions"


def _intero_pos(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _importo_per_registro(minori: int, valuta: str) -> str:
    """r2 (23/10/2026, «autorizzato»): il registro scrive «87.00 EUR», non «8700 eur» -- chi
    legge le unita' minori come euro paga cento volte tanto. Con l'esponente vero della valuta
    (fase99: JPY 0, BHD 3). Una riga d'errore non solleva mai: valuta illeggibile -> le unita'
    minori, dette per nome."""
    try:
        from fase99_multicurrency import Denaro
        return Denaro(minori, str(valuta).upper()).formatta()
    except (TypeError, ValueError):
        return "%r unita' minori di %r" % (minori, valuta)


def _esito_sconosciuto(exc: BaseException) -> bool:
    """⛔ PILASTRO ZERO (19/10/2026). Una chiamata a Stripe finita in errore ha l'esito SCONOSCIUTO
    -- puo' essere stata ESEGUITA -- salvo un rifiuto certo: una risposta 4xx, tranne 409 (la
    stessa chiave e' ancora in lavorazione). Timeout, connessione caduta, 5xx e una risposta che
    non si legge restano sconosciuti (docs.stripe.com/error-low-level, letta il 19/10/2026:
    «Considera indeterminato l'esito di una richiesta che restituisce 500»). Il codice si legge
    da `code` come fa la diagnostica di `_post` (l'HTTPError vero e gli errori finti delle prove),
    dentro un `try`: nel dubbio e' sconosciuto, perche' un rifiuto inventato fa pagare due volte."""
    try:
        codice = getattr(exc, "code", None)
        return not (isinstance(codice, int) and not isinstance(codice, bool)
                    and 400 <= codice < 500 and codice != 409)
    except Exception:
        return True


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
# esito controversia). Account Express con la piattaforma responsabile (vedi crea_account)
# + Account Link per l'onboarding. Transfer IDEMPOTENTE (Idempotency-Key per riferimento: mai doppi
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
        # Una rete FINTA iniettata serve anche le letture (senza corpo e' un GET, come in fase85):
        # altrimenti una prova che inietta solo `fetch` leggerebbe dalla rete VERA.
        self._fetch_get = fetch_get or (self._fetch_get_reale if fetch is None
                                        else (lambda url, headers: fetch(url, None, headers)))

    def _post(self, url: str, params: Dict[str, str], idem_key: str = "",
              esito: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
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
            if esito is not None:                 # PILASTRO ZERO: rifiuto, o esito sconosciuto?
                esito["sconosciuto"] = _esito_sconosciuto(e)
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
        """Crea l'account connesso dell'host: Dashboard Express, piattaforma responsabile delle
        perdite, capacita' di ricevere i bonifici. -> acct_... o None.
        ⛔ Niente `type` (busta 1, 2026-10-04): con la piattaforma responsabile Stripe rifiuta
        `custom` ed `express` col campo `type`, e lo `standard` (dashboard completa, perdite a
        Stripe) non e' compatibile con gli addebiti indiretti. Costi: REGISTRO, appendice R5."""
        if not self._key:
            return None
        params = {"controller[stripe_dashboard][type]": "express",
                  "controller[fees][payer]": "application",
                  "controller[losses][payments]": "application",
                  "capabilities[transfers][requested]": "true"}
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
                    riferimento: str, source_transaction: str = "") -> Optional[str]:
        """Sposta il netto host sul suo conto. IDEMPOTENTE per riferimento (Stripe dedupa
        con la stessa Idempotency-Key: mai doppio bonifico).
        COMPITO 41: con l'ADDEBITO dell'ospite (`source_transaction`, ch_/py_) il bonifico non
        esce dal saldo DISPONIBILE (il 4/10 -0,27 EUR): Stripe lo accetta e lo esegue quando quei
        soldi sono disponibili. Col legame il gruppo lo crea Stripe (come nell'esempio ufficiale:
        mandarli insieme non e' documentato) e il riferimento resta nei metadata
        (docs.stripe.com/connect/separate-charges-and-transfers, letto l'11/10/2026).

        ⛔ PILASTRO ZERO (19/10/2026, «autorizzato»). Una risposta che non arriva (timeout,
        connessione caduta, 5xx) NON dice se il bonifico e' partito, e Stripe ricorda la chiave
        anti-doppio solo 24 ore (docs.stripe.com/error-low-level, letta il 19/10/2026): pagarlo a
        mano, o rifare il POST a chiave dimenticata, paga l'host DUE volte. Quindi, col
        riferimento, PRIMA si chiede a Stripe se il bonifico c'e' gia' (`bonifico_di`), e dopo un
        esito sconosciuto si rilegge SUBITO. Tre risposte, non due:
          'tr_...' = partito (adesso, o ritrovato su Stripe);
          None     = NON partito, con certezza (argomenti non validi, o un rifiuto 4xx): a mano;
          ""       = ESITO SCONOSCIUTO: niente bonifico nuovo e niente «a mano», il motivo e' nel
                     registro. Vuota e quindi falsa: chi sa solo «riuscito o no» non la scambia
                     mai per un bonifico partito."""
        if not (self._key and isinstance(account_id, str) and account_id.startswith("acct_")):
            return None
        if not (isinstance(amount_cents, int) and not isinstance(amount_cents, bool)
                and amount_cents > 0):
            return None
        rif = str(riferimento or "")
        params = {"amount": str(amount_cents),
                  "currency": (currency or "eur").lower(),
                  "destination": account_id,
                  "metadata[riferimento]": rif}
        if isinstance(source_transaction, str) and source_transaction.startswith(("ch_", "py_")):
            params["source_transaction"] = source_transaction
        else:
            params["transfer_group"] = rif
        if rif:
            gia = self._bonifico_esistente(account_id, rif, amount_cents, params["currency"])
            if gia is not None:                       # gia' partito ('tr_...'), o non si sa ("")
                return gia
        esito: Dict[str, Any] = {}
        r = self._post(self.TRANSFERS, params, idem_key="transfer_" + (rif or account_id),
                       esito=esito)
        tid = r.get("id") if r else None
        if isinstance(tid, str) and tid.startswith("tr_"):
            return tid
        if esito.get("sconosciuto") is False or (isinstance(r, dict)
                                                 and isinstance(r.get("error"), dict)):
            return None                               # rifiuto certo: non e' partito niente
        logger.error("Connect: bonifico con ESITO SCONOSCIUTO verso %s (riferimento %r, %s): "
                     "la risposta di Stripe non e' arrivata o non si legge, si rilegge Stripe",
                     account_id, rif, _importo_per_registro(amount_cents, params["currency"]))
        return (self._bonifico_esistente(account_id, rif, amount_cents, params["currency"])
                or "") if rif else ""

    def _bonifico_esistente(self, account_id: str, riferimento: str, amount_cents: int,
                            valuta: str) -> Optional[str]:
        """-> 'tr_...' il bonifico di questo riferimento c'e' gia' su Stripe ed e' quello giusto
        (stesso importo e valuta, non stornato) · None Stripe dice che non c'e' · "" non si sa, o
        c'e' ma non torna: lo dice il registro, e niente secondo bonifico."""
        letto = self.bonifico_di(account_id, riferimento)
        if not letto.get("ok"):
            logger.error("Connect: NON SO se il bonifico per %r verso %s e' gia' partito (%s): "
                         "non lo rifaccio alla cieca", riferimento, account_id,
                         letto.get("motivo"))
            return ""
        b = letto.get("bonifico")
        if b is None:
            return None
        if (_intero_pos(b["importo_cents"]) and b["importo_cents"] == amount_cents
                and b["valuta"] == valuta and not b["stornato"]):
            logger.warning("Connect: il bonifico %s per %r verso %s c'era gia' su Stripe: non se "
                           "ne fa un altro", b["id"], riferimento, account_id)
            return b["id"]
        logger.error("Connect: per %r verso %s Stripe ha GIA' il bonifico %s ma non torna (%r, "
                     "atteso %s): niente secondo bonifico, decide una persona",
                     riferimento, account_id, b["id"], b, _importo_per_registro(amount_cents, valuta))
        return ""

    # Pagine da 100 lette al massimo per ritrovare un bonifico: oltre, la risposta e' «non so».
    PAGINE_MASSIME = 10

    def bonifico_di(self, account_id: str, riferimento: str) -> Dict[str, Any]:
        """IL BONIFICO DI QUESTA PRENOTAZIONE C'E' GIA' SU STRIPE? Solo lettura: GET
        /v1/transfers filtrato sul conto dell'host (`destination`, 100 per pagina, `has_more` e
        `starting_after`: docs.stripe.com/api/transfers/list, letta il 19/10/2026), cercando
        `metadata[riferimento]`, che `trasferisci` mette sempre (il gruppo no: col legame
        all'addebito lo sceglie Stripe).
        -> {'ok': True, 'bonifico': None} nessuno · {'ok': True, 'bonifico': {'id',
        'importo_cents', 'valuta', 'stornato'}} uno · {'ok': False, 'motivo'} NON LO SO (rete,
        risposta che non e' una lista di bonifici, oltre PAGINE_MASSIME, piu' di un bonifico per
        lo stesso riferimento): chi chiama non paga. Mai solleva."""
        if not (self._key and isinstance(account_id, str) and account_id.startswith("acct_")
                and isinstance(riferimento, str) and riferimento):
            return {"ok": False, "motivo": "argomenti_non_validi"}
        trovati: List[Dict[str, Any]] = []
        dopo = ""
        try:
            for _ in range(self.PAGINE_MASSIME):
                q = {"destination": account_id, "limit": "100"}
                if dopo:
                    q["starting_after"] = dopo
                r = self._fetch_get(self.TRANSFERS + "?" + urllib.parse.urlencode(q),
                                    {"Authorization": "Bearer " + self._key})
                dati = r.get("data") if isinstance(r, dict) else None
                if not (isinstance(dati, list) and all(
                        isinstance(t, dict) and str(t.get("id") or "").startswith("tr_")
                        for t in dati)):
                    return {"ok": False, "motivo": "risposta_inattesa: %.200r" % (r,)}
                trovati += [t for t in dati if isinstance(t.get("metadata"), dict)
                            and t["metadata"].get("riferimento") == riferimento]
                if r.get("has_more") is not True:
                    break
                if not dati:
                    return {"ok": False, "motivo": "risposta_inattesa: has_more senza bonifici"}
                dopo = dati[-1]["id"]
            else:
                return {"ok": False, "motivo": "oltre %d pagine di bonifici" % self.PAGINE_MASSIME}
        except Exception as exc:
            return {"ok": False, "motivo": _motivo_errore(exc)}
        if len(trovati) > 1:
            return {"ok": False, "motivo": "%d bonifici per lo stesso riferimento: %s"
                    % (len(trovati), ", ".join(t["id"] for t in trovati))}
        if not trovati:
            return {"ok": True, "bonifico": None}
        t = trovati[0]
        stornato = not (t.get("reversed") is False and t.get("amount_reversed") == 0
                        and not isinstance(t.get("amount_reversed"), bool))
        return {"ok": True, "bonifico": {"id": t["id"], "importo_cents": t.get("amount"),
                                         "valuta": str(t.get("currency") or "").lower(),
                                         "stornato": stornato}}

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
