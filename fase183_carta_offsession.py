# -*- coding: utf-8 -*-
"""
CORE_AUTO - Fase 183: SCATTO ③ del Financial Controller — carta host off-session.

SCOPO (rete di sicurezza "noi mai in perdita"): i debiti dell'host (penale 15% quando
cancella una prenotazione GIA' pagata) si recuperano PRIMA dai bonifici futuri (Scatto ②,
fase177.riscuoti_debiti). Ma un host che cancella e poi SPARISCE (nessun incasso futuro
da cui trattenere) lascerebbe il debito scoperto -> ci rimetteremmo noi. Qui: se l'host ha
salvato una carta (flusso HOSTED, la carta va da lui a Stripe, MAI da noi), un debito
'aperto' certo si addebita OFF-SESSION su quella carta.

MODELLO (scelta fondatore, opzione "facoltativa + just-in-time"): la carta NON e'
obbligatoria (land-grab a basso attrito); l'host la aggiunge per il badge "Host Verificato+"
e per i bonifici prioritari, OPPURE gliela chiediamo quando nasce un debito scoperto. Solo
un debito CERTO viene addebitato, con MANDATO esplicito accettato al salvataggio carta.

STDLIB pura (niente SDK Stripe), fetch INIETTABILE (test senza rete). GATED dalla chiave:
senza chiave -> provider None, funzione dormiente. NON muove denaro reale finche' il
fondatore non attiva (chiave sk_live gia' presente) e testa con una carta vera.

Zero PII carta da noi: salviamo SOLO gli identificativi opachi di Stripe (customer id
'cus_...', payment_method id 'pm_...'). Il numero carta non transita e non si archivia.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("core_auto.carta_offsession")

_BASE = "https://api.stripe.com/v1"


def _intero_pos(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


class ProviderCarta:
    """Salvataggio carta (Checkout mode=setup, HOSTED) + addebito off-session (PaymentIntent).
    `fetch(metodo, url, body_bytes_or_None, headers) -> dict` iniettabile per i test."""

    def __init__(self, secret_key: str, *, success_url: str = "", cancel_url: str = "",
                 fetch: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
        self._key = secret_key.strip()
        self._ok = success_url or "https://bookinvip.com/host?carta=ok"
        self._ko = cancel_url or "https://bookinvip.com/host?carta=annullata"
        self._fetch = fetch or self._fetch_reale

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": "Bearer " + self._key,
                "Content-Type": "application/x-www-form-urlencoded"}

    # ── 1) SALVA CARTA: pagina HOSTED (la carta va all'host->Stripe, mai da noi) ──
    def crea_link_carta(self, *, host_id: str, email: str = "") -> Optional[str]:
        """Checkout Session mode=setup: ritorna l'URL hosted dove l'host salva la carta.
        `customer_creation=always` -> Stripe crea il customer; il webhook ci dara' customer
        + payment_method da conservare. metadata[host_id] per sapere di chi e' la carta."""
        try:
            from urllib.parse import urlencode
            params = [
                ("mode", "setup"),
                ("customer_creation", "always"),
                ("success_url", self._ok),
                ("cancel_url", self._ko),
                ("payment_method_types[0]", "card"),
                ("metadata[host_id]", str(host_id)),
                ("metadata[scopo]", "mandato_penale_offsession"),
            ]
            if isinstance(email, str) and "@" in email:
                params.append(("customer_email", email))
            resp = self._fetch("POST", _BASE + "/checkout/sessions",
                               urlencode(params).encode("utf-8"), self._headers())
            url = resp.get("url") if isinstance(resp, dict) else None
            return url if isinstance(url, str) and url else None
        except Exception:
            logger.warning("carta: crea_link fallita (ISOLATA -> None)", exc_info=True)
            return None

    def dettagli_da_sessione(self, session_id: str) -> Optional[Dict[str, str]]:
        """Dopo il webhook mode=setup: dal checkout session id -> (customer, payment_method).
        Fa 2 GET: la sessione (per customer + setup_intent) e il setup_intent (per il pm)."""
        try:
            s = self._fetch("GET", "%s/checkout/sessions/%s" % (_BASE, session_id),
                            None, self._headers())
            if not isinstance(s, dict):
                return None
            customer = s.get("customer") or ""
            si = s.get("setup_intent") or ""
            pm = ""
            if si:
                sio = self._fetch("GET", "%s/setup_intents/%s" % (_BASE, si), None,
                                  self._headers())
                pm = (sio.get("payment_method") if isinstance(sio, dict) else "") or ""
            if customer and pm:
                return {"customer": str(customer), "payment_method": str(pm)}
            return None
        except Exception:
            logger.warning("carta: dettagli_da_sessione falliti (ISOLATO)", exc_info=True)
            return None

    # ── 2) ADDEBITO OFF-SESSION (host non presente): PaymentIntent confirm ──
    def addebita(self, *, customer: str, payment_method: str, importo_cents: Any,
                 valuta: str, riferimento: str,
                 idem: str = "") -> Dict[str, Any]:
        """Addebita OFF-SESSION la carta salvata. Ritorna:
          {'stato': 'riuscito'|'richiede_azione'|'fallito'|'config', 'pi': id, 'motivo': ...}
        - 'riuscito' = incassato (status succeeded);
        - 'richiede_azione' = serve autenticazione (SCA): NON incassato, si avvisa l'host;
        - 'fallito' = carta rifiutata / errore;
        - 'config' = provider/argomenti non validi (nessun addebito tentato).
        IDEMPOTENTE via Idempotency-Key = idem (Stripe deduplica il retry)."""
        if not (isinstance(customer, str) and customer
                and isinstance(payment_method, str) and payment_method):
            return {"stato": "config", "motivo": "carta_non_collegata"}
        if not _intero_pos(importo_cents):
            return {"stato": "config", "motivo": "importo_non_valido"}
        val = valuta.lower() if isinstance(valuta, str) and valuta.strip() else "eur"
        try:
            from urllib.parse import urlencode
            params = [
                ("amount", str(int(importo_cents))),
                ("currency", val),
                ("customer", customer),
                ("payment_method", payment_method),
                ("off_session", "true"),
                ("confirm", "true"),
                ("description", "BookinVIP recupero penale " + str(riferimento or "")),
                ("metadata[riferimento]", str(riferimento or "")),
                ("metadata[scopo]", "recupero_penale"),
            ]
            headers = dict(self._headers())
            if idem:
                headers["Idempotency-Key"] = str(idem)
            resp = self._fetch("POST", _BASE + "/payment_intents",
                               urlencode(params).encode("utf-8"), headers)
            if not isinstance(resp, dict):
                return {"stato": "fallito", "motivo": "risposta_non_valida"}
            # errore Stripe (es. card_declined / authentication_required)
            if resp.get("error"):
                err = resp["error"] if isinstance(resp["error"], dict) else {}
                code = str(err.get("code") or err.get("type") or "errore")
                if code in ("authentication_required",):
                    return {"stato": "richiede_azione", "motivo": code,
                            "pi": str(err.get("payment_intent", {}).get("id", ""))}
                return {"stato": "fallito", "motivo": code}
            status = str(resp.get("status") or "")
            pi = str(resp.get("id") or "")
            if status == "succeeded":
                return {"stato": "riuscito", "pi": pi}
            if status in ("requires_action", "requires_confirmation", "requires_payment_method"):
                return {"stato": "richiede_azione", "pi": pi, "motivo": status}
            return {"stato": "fallito", "pi": pi, "motivo": status or "sconosciuto"}
        except Exception:
            logger.warning("carta: addebito off-session fallito (ISOLATO)", exc_info=True)
            return {"stato": "fallito", "motivo": "eccezione"}

    @staticmethod
    def _fetch_reale(metodo: str, url: str, body: Optional[bytes],
                     headers: Dict[str, str]) -> Dict[str, Any]:  # pragma: no cover
        import urllib.error
        import urllib.request
        req = urllib.request.Request(url, data=body, headers=headers, method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            # Stripe manda il dettaglio dell'errore nel corpo anche sui 4xx (es. carta rifiutata)
            try:
                return json.loads(e.read())
            except Exception:
                return {"error": {"code": "http_%d" % e.code}}


def crea_provider_carta(secret_key: Optional[str], *, success_url: str = "",
                        cancel_url: str = "",
                        fetch: Any = None) -> Optional[ProviderCarta]:
    """Factory GATED: provider solo se c'e' una chiave; altrimenti None (Scatto ③ dormiente)."""
    if not (isinstance(secret_key, str) and secret_key.strip()):
        return None
    return ProviderCarta(secret_key.strip(), success_url=success_url,
                         cancel_url=cancel_url, fetch=fetch)
