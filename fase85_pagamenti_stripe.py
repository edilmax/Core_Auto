"""
CORE_AUTO - Fase 85: Provider Pagamento Stripe (l'ultimo pezzo del money-path).

Finora la prenotazione (concierge fase59) conferma e blocca l'inventario, ma NON incassa:
il `link_pagamento` era un'astrazione iniettabile mai cablata. Questo modulo la riempie
con Stripe Checkout, a ZERO dipendenze (chiamata REST via urllib stdlib - niente libreria
`stripe`). E' GATED dalla chiave: se la chiave non c'e', il sistema si comporta come ora
(nessun link); appena metti STRIPE_SECRET_KEY, ogni prenotazione produce un link di
pagamento reale - SENZA toccare il codice.

Il prezzo arriva GIA' firmato dal CORE (fase59, mai dall'IA) e qui viene solo passato a
Stripe in CENTESIMI interi (unit_amount). Riferimento e email viaggiano nei metadata per
la riconciliazione. La chiamata e' ISOLATA: se Stripe e' giu', `crea_link` ritorna None e
la prenotazione resta valida (il link si rigenera) - non si propaga mai un errore.

VINCITRICE DEL BENCHMARK (4 modi di cablare i pagamenti):
  V3 'provider iniettato gated da env + chiamata REST stdlib isolata'. Zero dipendenze,
  accensione senza modifiche, fail-safe. Le altre perdono: V1 'libreria stripe' = una
  dipendenza in piu' (contro "zero spese/dipendenze"); V2 'hardcode la chiave' = segreto
  nel codice; V4 'redirect lato client' = il prezzo passerebbe dal browser (manomettibile).

SOPRAVVIVENZA TOTALE: `crea_link` non solleva MAI (eccezione -> None); cents non validi ->
None; `fetch` iniettabile (test deterministici senza chiamare Stripe davvero); nessuna
chiave -> provider non creato. Denaro in centesimi interi.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("core_auto.pagamenti_stripe")

STRIPE_URL = "https://api.stripe.com/v1/checkout/sessions"
RIMBORSI_URL = "https://api.stripe.com/v1/refunds"


def _intero_pos(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


class ProviderStripe:
    """Crea una Checkout Session Stripe. `fetch(url, body_bytes, headers) -> dict` e'
    iniettabile (default: urllib reale) per testare senza chiamare Stripe."""

    def __init__(self, secret_key: str, success_url: str, cancel_url: str, *,
                 valuta: str = "eur",
                 fetch: Optional[Callable[[str, bytes, Dict[str, str]], Dict[str, Any]]]
                 = None) -> None:
        self._key = secret_key
        self._ok = success_url
        self._ko = cancel_url
        self._valuta = (valuta or "eur").lower()
        self._fetch = fetch or self._fetch_reale

    def crea_link(self, dati: Dict[str, Any]) -> Optional[str]:
        """Da un dict prenotazione (prezzo_guest_cents, riferimento, email) -> URL di
        pagamento Stripe, o None (chiave/cents invalidi o Stripe non raggiungibile)."""
        try:
            if not isinstance(dati, dict):
                return None
            # addebita il TOTALE (soggiorno + tassa di soggiorno); fallback al solo soggiorno
            cents = dati.get("totale_cents")
            if not _intero_pos(cents):
                cents = dati.get("prezzo_guest_cents")
            if not _intero_pos(cents):
                return None
            ref = str(dati.get("riferimento", ""))
            # VALUTA della PRENOTAZIONE (like-for-like): l'host prezza in X -> l'ospite paga X.
            # Senza questo si addebitava sempre nella valuta FISSA del provider (EUR) anche su
            # annunci JPY/USD/GBP -> valuta sbagliata e importo errato (bug provato). Fallback
            # alla valuta del provider se la prenotazione non la specifica.
            valuta = dati.get("valuta")
            valuta = valuta.lower() if isinstance(valuta, str) and valuta.strip() else self._valuta
            import time as _t
            # scadenza sessione: default 30 min (instant-book, minimo Stripe). Il chiamante può
            # chiedere di più via 'scade_secondi' (es. su-richiesta approvata: il cliente non è
            # online, gli si dà fino a ~24h — massimo Stripe). Clamp nei limiti Stripe.
            scade_sec = dati.get("scade_secondi")
            if not (isinstance(scade_sec, int) and not isinstance(scade_sec, bool)):
                scade_sec = 1800
            scade_sec = max(1800, min(86100, scade_sec))
            scade_at = int(_t.time()) + scade_sec
            params: List[Tuple[str, str]] = [
                ("mode", "payment"),
                ("expires_at", str(scade_at)),   # urgenza + auto-scadenza allineata all'hold stanza
                ("success_url", self._ok or "https://bookinvip.com/grazie.html"),
                ("cancel_url", self._ko or "https://bookinvip.com/annullato.html"),
                ("line_items[0][quantity]", "1"),
                ("line_items[0][price_data][currency]", valuta),
                ("line_items[0][price_data][unit_amount]", str(cents)),
                ("line_items[0][price_data][product_data][name]",
                 "BookinVIP " + (ref or "prenotazione")),
                ("client_reference_id", ref),
                ("metadata[riferimento]", ref),
            ]
            email = dati.get("email")
            if isinstance(email, str) and "@" in email:
                params.append(("customer_email", email))
            from urllib.parse import urlencode
            body = urlencode(params).encode("utf-8")
            headers = {"Authorization": "Bearer " + self._key,
                       "Content-Type": "application/x-www-form-urlencoded"}
            resp = self._fetch(STRIPE_URL, body, headers)
            url = resp.get("url") if isinstance(resp, dict) else None
            return url if isinstance(url, str) and url else None
        except Exception:
            logger.warning("Stripe: creazione link fallita (ISOLATA -> None)",
                           exc_info=True)
            return None

    def rimborsa(self, payment_intent: Any, importo_cents: Any,
                 chiave_idem: Any) -> Dict[str, Any]:
        """RESTITUISCE i soldi all'ospite. E' l'unica funzione del progetto che fa uscire
        denaro verso un cliente, e fino al 2026-08-16 non esisteva: il pannello admin faceva
        tutti i passi di sicurezza e poi diceva *«il rimborso va eseguito A MANO»*.

        ⛔ `chiave_idem` NON e' un dettaglio: senza `Idempotency-Key` un ritentativo di rete
        (o un doppio clic) restituisce i soldi DUE volte, ed e' il rovescio esatto del doppio
        pagamento -- con la differenza che questa volta a perderci siamo noi. La documentazione
        Stripe la indica come pratica obbligatoria proprio sui rimborsi. La chiave dev'essere
        **stabile per quel rimborso**: la sceglie il chiamante, che sa qual e' la prenotazione.

        ⚠️ NIENTE `reverse_transfer` qui, ed e' una scelta misurata, non una dimenticanza:
        l'ospite paga con `crea_link` (Checkout normale, incassa la PIATTAFORMA) e all'host si
        bonifica dopo, allo sblocco dell'escrow (fase101). Al momento del rimborso il
        trasferimento all'host non e' ancora partito -- e il chiamante deve averlo trattenuto
        PRIMA di chiamare qui. Se un giorno si passasse agli addebiti con destinazione
        (`transfer_data[destination]`), questa riga diventerebbe una perdita piena: la
        documentazione Stripe avverte che rimborsare un addebito NON tocca i trasferimenti.

        Ritorna sempre un dict, mai None: `{'ok': bool, 'id': 're_...', 'motivo': str}`.
        Il motivo c'e' anche quando va male, perche' un osservabile debole e' un difetto
        (regola ferrea 9): «rimborso fallito» senza il perche' non si sa nemmeno se ritentare.
        """
        if not (isinstance(payment_intent, str) and payment_intent.startswith("pi_")):
            return {"ok": False, "id": "", "motivo": "payment_intent_assente"}
        if not _intero_pos(importo_cents):
            return {"ok": False, "id": "", "motivo": "importo_non_valido"}
        if not (isinstance(chiave_idem, str) and chiave_idem.strip()):
            return {"ok": False, "id": "", "motivo": "chiave_idempotenza_assente"}
        try:
            from urllib.parse import urlencode
            params: List[Tuple[str, str]] = [
                ("payment_intent", payment_intent),
                ("amount", str(int(importo_cents))),
                ("metadata[origine]", "bookinvip_admin"),
            ]
            body = urlencode(params).encode("utf-8")
            headers = {"Authorization": "Bearer " + self._key,
                       "Content-Type": "application/x-www-form-urlencoded",
                       "Idempotency-Key": chiave_idem.strip()}
            resp = self._fetch(RIMBORSI_URL, body, headers)
            rid = resp.get("id") if isinstance(resp, dict) else None
            if isinstance(rid, str) and rid.startswith("re_"):
                return {"ok": True, "id": rid,
                        "motivo": str((resp or {}).get("status") or "creato")}
            # Non e' un'eccezione: Stripe ha risposto qualcosa che non e' un rimborso.
            # Va detto per intero, non ridotto a un booleano.
            return {"ok": False, "id": "", "motivo": "risposta_inattesa: %r" % (resp,)}
        except Exception as exc:
            logger.error("Stripe: RIMBORSO FALLITO pi=%s importo=%r -> %s: %s",
                         payment_intent, importo_cents, exc.__class__.__name__, exc,
                         exc_info=True)
            return {"ok": False, "id": "",
                    "motivo": "%s: %s" % (exc.__class__.__name__, exc)}

    # Rimborsi che valgono come denaro GIA' USCITO (o in uscita). Un rimborso 'failed' o
    # 'canceled' NON ha restituito niente: contarlo come fatto toglierebbe la riga dalla lista
    # di chi aspetta lasciando l'ospite senza i suoi soldi E senza nessuno che lo sappia --
    # il peggiore dei due errori possibili. Gli stati sono quelli dichiarati dalla
    # documentazione Stripe (oggetto Refund, campo `status`: pending, requires_action,
    # succeeded, failed, canceled).
    STATI_RIMBORSO_VIVO = ("succeeded", "pending", "requires_action")

    def rimborsi_di(self, payment_intent: Any) -> Dict[str, Any]:
        """CHIEDE A STRIPE se su quel pagamento e' gia' uscito un rimborso. E' la meta' LETTA
        del rimborso, e senza di essa la lista dei rimborsi dovuti dovrebbe fidarsi del nostro
        database -- che il 2026-08-16 diceva 'rimborsato' su una prenotazione dove non era
        partito un centesimo. La verita' su dove sono i soldi ce l'ha chi li muove.

        ⛔ `ok=False` NON SIGNIFICA «nessun rimborso»: significa «NON LO SO». Confondere le due
        cose e' il modo esatto in cui si rimborsa due volte la stessa persona, o in cui una
        lista vuota si legge come «niente da fare» mentre nessuno ha potuto guardare. Percio'
        l'esito della domanda (`ok`) e la risposta (`rimborsi`) stanno in campi diversi, e chi
        chiama e' costretto a distinguerli.

        ⚠️ DICHIARATO (D18 condizione 3): si leggono i primi 100 rimborsi di quel pagamento e
        NON si segue la paginazione. Una prenotazione con piu' di 100 rimborsi parziali non
        esiste nel nostro prodotto; se un giorno esistesse, questa funzione ne vedrebbe solo
        una parte -- e la sottostima porta a rimborsare di nuovo, quindi va rifatta prima.

        Ritorna sempre un dict: {'ok', 'rimborsi', 'rimborsato_cents', 'motivo'}."""
        if not (isinstance(payment_intent, str) and payment_intent.startswith("pi_")):
            return {"ok": False, "rimborsi": [], "rimborsato_cents": 0,
                    "motivo": "payment_intent_assente"}
        try:
            from urllib.parse import urlencode
            url = RIMBORSI_URL + "?" + urlencode([("payment_intent", payment_intent),
                                                  ("limit", "100")])
            resp = self._fetch(url, None, {"Authorization": "Bearer " + self._key})
            if not (isinstance(resp, dict) and isinstance(resp.get("data"), list)):
                # Stripe ha risposto qualcosa che non e' un elenco: non e' «nessun rimborso»,
                # e' una risposta che non so leggere. Va detta per intero (regola ferrea 9).
                return {"ok": False, "rimborsi": [], "rimborsato_cents": 0,
                        "motivo": "risposta_inattesa: %r" % (resp,)}
            vivi = [r for r in resp["data"] if isinstance(r, dict)
                    and str(r.get("status") or "") in self.STATI_RIMBORSO_VIVO]
            return {"ok": True, "rimborsi": vivi, "motivo": "",
                    "rimborsato_cents": sum(int(r.get("amount") or 0) for r in vivi)}
        except Exception as exc:
            logger.error("Stripe: LETTURA RIMBORSI FALLITA pi=%s -> %s: %s",
                         payment_intent, exc.__class__.__name__, exc, exc_info=True)
            return {"ok": False, "rimborsi": [], "rimborsato_cents": 0,
                    "motivo": "%s: %s" % (exc.__class__.__name__, exc)}

    def crea_link_anticipo(self, dati: Dict[str, Any]) -> Optional[str]:
        """PAGA IN STRUTTURA: Checkout Session che addebita SUBITO solo l'ANTICIPO
        (commissione + fee + copertura carta = tutto NOSTRO, fase188) E salva la carta per la
        penale no-show/tardiva (FASE 3). La carta va dall'ospite a Stripe, MAI da noi (hosted).
        Il SALDO **non** si incassa qui: lo paga l'ospite all'host DI PERSONA -> nessun escrow,
        nessun payout, nessun auto-rilascio. Il webhook riconosce la prenotazione dai metadata
        (`modo=in_struttura`, `anticipo_cents`, `saldo_cents`). Ritorna l'URL hosted o None.

        Deliberatamente SEPARATO da `crea_link` (flusso online LIVE): lo lasciamo intatto."""
        try:
            if not isinstance(dati, dict):
                return None
            anticipo = dati.get("anticipo_cents")
            if not _intero_pos(anticipo):
                return None
            saldo = dati.get("saldo_cents")
            saldo = saldo if (isinstance(saldo, int) and not isinstance(saldo, bool)
                              and saldo >= 0) else 0
            ref = str(dati.get("riferimento", ""))
            valuta = dati.get("valuta")
            valuta = valuta.lower() if isinstance(valuta, str) and valuta.strip() else self._valuta
            import time as _t
            scade_sec = dati.get("scade_secondi")
            if not (isinstance(scade_sec, int) and not isinstance(scade_sec, bool)):
                scade_sec = 1800
            scade_sec = max(1800, min(86100, scade_sec))
            scade_at = int(_t.time()) + scade_sec
            params: List[Tuple[str, str]] = [
                ("mode", "payment"),
                # SALVA LA CARTA insieme all'incasso dell'anticipo (una sola pagina hosted):
                # servira' off-session per la penale no-show (FASE 3). customer_creation=always
                # crea il customer a cui Stripe lega la carta.
                ("customer_creation", "always"),
                ("payment_intent_data[setup_future_usage]", "off_session"),
                ("payment_intent_data[metadata][riferimento]", ref),
                ("payment_intent_data[metadata][scopo]", "anticipo_paga_struttura"),
                ("expires_at", str(scade_at)),
                ("success_url", self._ok or "https://bookinvip.com/grazie.html"),
                ("cancel_url", self._ko or "https://bookinvip.com/annullato.html"),
                ("line_items[0][quantity]", "1"),
                ("line_items[0][price_data][currency]", valuta),
                ("line_items[0][price_data][unit_amount]", str(int(anticipo))),
                ("line_items[0][price_data][product_data][name]",
                 "BookinVIP anticipo " + (ref or "prenotazione")),
                ("client_reference_id", ref),
                ("metadata[riferimento]", ref),
                ("metadata[modo]", "in_struttura"),
                ("metadata[anticipo_cents]", str(int(anticipo))),
                ("metadata[saldo_cents]", str(int(saldo))),
            ]
            email = dati.get("email")
            if isinstance(email, str) and "@" in email:
                params.append(("customer_email", email))
            from urllib.parse import urlencode
            body = urlencode(params).encode("utf-8")
            headers = {"Authorization": "Bearer " + self._key,
                       "Content-Type": "application/x-www-form-urlencoded"}
            resp = self._fetch(STRIPE_URL, body, headers)
            url = resp.get("url") if isinstance(resp, dict) else None
            return url if isinstance(url, str) and url else None
        except Exception:
            logger.warning("Stripe: creazione link ANTICIPO fallita (ISOLATA -> None)",
                           exc_info=True)
            return None

    @staticmethod
    def _fetch_reale(url: str, body: bytes,
                     headers: Dict[str, str]) -> Dict[str, Any]:  # pragma: no cover
        import urllib.request
        # Il metodo lo decide il CORPO, non il chiamante: con un corpo si scrive (POST), senza
        # si legge (GET). Serve a `rimborsi_di`, che INTERROGA Stripe invece di muovere denaro.
        # Cablarlo a POST manderebbe una scrittura vuota all'elenco dei rimborsi.
        req = urllib.request.Request(url, data=body, headers=headers,
                                     method=("POST" if body else "GET"))
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())


def crea_provider_stripe(secret_key: Optional[str], success_url: str = "",
                         cancel_url: str = "", *, valuta: str = "eur",
                         fetch: Any = None) -> Optional[ProviderStripe]:
    """Factory GATED: ritorna un provider solo se c'e' una chiave; altrimenti None
    (il sistema resta senza link di pagamento, come oggi)."""
    if not (isinstance(secret_key, str) and secret_key.strip()):
        return None
    return ProviderStripe(secret_key.strip(), success_url, cancel_url, valuta=valuta,
                          fetch=fetch)
