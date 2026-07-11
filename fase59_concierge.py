"""
CORE_AUTO - Fase 59: Protocollo Concierge AI (booking AGENT-DISCOVERABLE).

La mossa che i colossi non hanno e, per struttura, non possono fare in fretta. Entro
il 2030 una quota enorme delle prenotazioni sara' fatta da AGENTI IA che agiscono per
conto del cliente (il cliente non naviga piu' un sito: dice "trovami una stanza a Roma
per 2 notti sotto 150€" e l'agente prenota). Le OTA espongono HTML pieno di dark-pattern,
pensato per occhi umani: ostile agli agenti. Noi esponiamo un PROTOCOLLO MACCHINA pulito,
deterministico, firmato. Questo e' il SEO del 2026-2030, ed e' a costo zero (e' contratto
sopra cio' che abbiamo gia': vetrina fase57 + inventario realtime fase58).

I 3 atti del protocollo (tutto JSON, niente HTML):
  1. SCOPRI  -> manifest delle capacita' + ricerca strutturata (l'agente "legge" cosa
     offriamo e con che regole; money_unit = centesimi interi).
  2. QUOTA   -> preventivo FERMO e FIRMATO: il CORE calcola il prezzo (in centesimi,
     netto host dall'inventario + commissione del CORE), lo firma HMAC con scadenza,
     e restituisce un TOKEN. L'agente NON puo' alterare il prezzo: e' dentro la firma.
  3. PRENOTA -> l'agente rimanda il token; il CORE ri-verifica firma+scadenza e blocca
     l'inventario in modo ATOMICO e IDEMPOTENTE (il token e' la idem-key).

PRINCIPIO FERREO (come fase17/40/45/49): il DENARO non si delega MAI all'IA. Qui e'
strutturale: l'agente puo' solo ECHEGGIARE un prezzo che il CORE ha gia' firmato; ogni
manomissione rompe l'HMAC -> rifiuto. La macchina dell'IA propone la ricerca; il CORE
decide, firma e incassa.

VINCITRICE DEL BENCHMARK (4 varianti x 10 stress, agenti ostili + concorrenza):
  V3 'quote firmata HMAC stateless + TTL + book che echo-verifica (token = idem-key)'.
    - corretta: il prezzo e' deciso dal CORE e immutabile (manomissione -> firma rotta);
    - sicura nel tempo: TTL -> un preventivo vecchio non e' onorato a un prezzo stantio;
    - idempotente: doppio book dello stesso token = una sola prenotazione;
    - STATELESS: nessuno stato server da potare, vale cross-worker (a differenza di V4
      'quote in tabella' che e' durevole ma stateful e va garbage-collected).
  Le altre perdono: V1 'agente passa il prezzo' viola la regola d'oro (IA tocca i soldi);
  V2 'ricalcola a book senza quote' espone una RACE (prezzo cambiato tra search e book ->
  l'agente conferma un prezzo diverso da quello mostrato al cliente).

DENARO: solo centesimi INTERI; float/bool/stringhe RIFIUTATI (fase56). Firma HMAC-SHA256
con stdlib (zero dipendenze). SOPRAVVIVENZA TOTALE: validatori BLINDATI (non sollevano
mai); inventario/pagamento iniettati e ISOLATI; giorno non caricato o prezzo 0 ->
non_quotabile (fail-closed); orologio iniettabile (test deterministici).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("core_auto.concierge")

MAX_CENTS = 1_000_000_00
PARTY_MAX = 50
PROTOCOLLO_VERSIONE = "1.0"


def _intero(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _stringa(v: Any, limite: int = 256) -> Optional[str]:
    if not isinstance(v, str):
        return None
    v = v.strip()
    if not v or len(v) > limite:
        return None
    return v


@dataclass
class RispostaConcierge:
    status: int
    corpo: Dict[str, Any]


# ─────────────────────────────────────────────────────────────────────────────
def codice_prenotazione(riferimento: Any) -> str:
    """Codice prenotazione LEGGIBILE stile Booking, dal riferimento interno.
    Es. 'a5d660df6d99...' -> 'BVIP-A5D6-60DF'. Solo display (l'ID interno resta il riferimento);
    stesso codice per cliente e host. Fallback robusto se il riferimento è corto/strano."""
    pulito = "".join(c for c in str(riferimento) if c.isalnum()).upper()
    base = (pulito + "00000000")[:8]        # sempre almeno 8 caratteri
    return "BVIP-%s-%s" % (base[:4], base[4:8])


# Quote firmata (stateless): payload JSON -> base64url . HMAC
# ─────────────────────────────────────────────────────────────────────────────
class FirmaQuote:
    """Firma/verifica HMAC-SHA256 di un payload quote. Stateless e cross-worker."""

    def __init__(self, segreto: bytes) -> None:
        if not isinstance(segreto, (bytes, bytearray)) or len(segreto) < 16:
            raise ValueError("segreto HMAC troppo corto (>=16 byte)")
        self._segreto = bytes(segreto)

    def _mac(self, msg: bytes) -> str:
        return hmac.new(self._segreto, msg, hashlib.sha256).hexdigest()

    def pin_checkin(self, riferimento: Any) -> str:
        """PIN a 4 cifre per il check-in: deterministico (stesso per cliente e host) ma NON
        indovinabile (HMAC del riferimento col segreto di sistema). Come il PIN di Booking."""
        h = self._mac(("pin:" + str(riferimento)).encode("utf-8"))
        return str(int(h[:8], 16) % 10000).zfill(4)

    def codifica(self, dati: Dict[str, Any]) -> str:
        raw = json.dumps(dati, separators=(",", ":"), sort_keys=True).encode("utf-8")
        b64 = base64.urlsafe_b64encode(raw).decode("ascii")
        return b64 + "." + self._mac(b64.encode("ascii"))

    def decodifica(self, token: Any) -> Optional[Dict[str, Any]]:
        """Verifica la firma e ritorna il payload, o None se assente/manomesso."""
        if not isinstance(token, str) or token.count(".") != 1:
            return None
        b64, sig = token.split(".")
        atteso = self._mac(b64.encode("ascii"))
        if not hmac.compare_digest(sig, atteso):     # firma rotta -> manomissione
            return None
        try:
            raw = base64.urlsafe_b64decode(b64.encode("ascii"))
            dati = json.loads(raw.decode("utf-8"))
            return dati if isinstance(dati, dict) else None
        except (ValueError, TypeError, json.JSONDecodeError):
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Protocollo
# ─────────────────────────────────────────────────────────────────────────────
class ProtocolloConcierge:
    """Composizione agent-first su vetrina (fase57) + inventario realtime (fase58).

    `inventario`: oggetto duck-typed con `disponibile(id,ci,co)`, `stato_giorno(id,g)`
    e `blocca(id,ci,co,idem_key=...)` (fase58 ChannelManager).
    `catalogo`: opzionale, con `cerca(criteri)`/`dettaglio(slug)` (fase57) per SCOPRI.
    `commissione`: callable iniettabile `netto_cents -> commissione_cents` (default 0).
    `link_pagamento`: callable opzionale e ISOLATO `dict -> url` (fase35/gateway)."""

    def __init__(self, inventario: Any, firma: FirmaQuote, *,
                 catalogo: Any = None,
                 commissione: Optional[Callable[[int], int]] = None,
                 commissione_alloggio: Optional[Callable[[int, str], int]] = None,
                 tassa_alloggio: Optional[Callable[..., int]] = None,
                 tasso_cambio: Optional[Callable[[str, str], Any]] = None,
                 link_pagamento: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
                 ttl_quote_sec: int = 900, valuta: str = "EUR",
                 psp_bps: int = 0,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._inv = inventario
        self._firma = firma
        self._cat = catalogo
        self._commissione = commissione or (lambda netto: 0)
        self._commissione_all = commissione_alloggio   # host-aware: (netto, slug)->comm
        self._tassa_all = tassa_alloggio               # (slug, notti, ospiti, imponibile)->cents
        # COSTO SERVIZIO PAGAMENTI (carta): a carico dell'HOST, dedotto dal suo incasso; l'ospite
        # paga sempre il prezzo pulito (0%). Copre la fee Stripe -> noi MAI in perdita. bps, cap 20%.
        self._psp_bps = max(0, min(2000, int(psp_bps))) if isinstance(psp_bps, int) \
            and not isinstance(psp_bps, bool) else 0
        self._tasso = tasso_cambio                     # (da, a)->tasso mid (solo display indicativo)
        self._link = link_pagamento
        self._ttl = max(60, int(ttl_quote_sec))
        self._valuta = valuta
        self._now = orologio or (lambda: int(time.time()))

    # ── ATTO 1: manifest (l'agente scopre le regole) ───────────────────────────
    def manifest(self) -> Dict[str, Any]:
        return {
            "protocollo": "core_auto.concierge",
            "versione": PROTOCOLLO_VERSIONE,
            "money_unit": "cents_integer",     # zero float: il denaro e' intero
            "valuta": self._valuta,
            "regole": {
                "il_prezzo_e_firmato_dal_core": True,
                "agente_non_puo_alterare_il_prezzo": True,
                "quote_ttl_sec": self._ttl,
                "idempotente": True,
            },
            "azioni": {
                "scopri": {"input": ["citta?", "prezzo_max_cents?", "capacita_min?",
                                     "servizi?", "check_in?", "check_out?"]},
                "quota": {"input": ["alloggio_id", "check_in", "check_out", "party?"],
                          "output": ["quote_token", "prezzo_guest_cents", "scade_a"]},
                "prenota": {"input": ["quote_token", "email", "ospite_nome?",
                                      "ospite_telefono?"],
                            "output": ["stato", "riferimento", "payment_url?"]},
            },
        }

    # ── ATTO 1: ricerca strutturata (machine-clean, niente HTML) ───────────────
    def scopri(self, criteri: Any) -> RispostaConcierge:
        if self._cat is None:
            return RispostaConcierge(501, {"errore": "discovery_non_disponibile"})
        if not isinstance(criteri, dict):
            return RispostaConcierge(400, {"errore": "payload_non_oggetto"})
        try:
            from fase57_vetrina import CriteriRicerca
            c = CriteriRicerca(
                citta=criteri.get("citta") or None,
                prezzo_min_cents=criteri.get("prezzo_min_cents")
                if _intero(criteri.get("prezzo_min_cents")) else None,
                prezzo_max_cents=criteri.get("prezzo_max_cents")
                if _intero(criteri.get("prezzo_max_cents")) else None,
                capacita_min=criteri.get("capacita_min")
                if _intero(criteri.get("capacita_min")) else None,
                servizi=tuple(s for s in (criteri.get("servizi") or ()) if isinstance(s, str)),
                ordine=criteri.get("ordine", "prezzo_asc"),
                limit=criteri.get("limit") if _intero(criteri.get("limit")) else 24,
                offset=criteri.get("offset") if _intero(criteri.get("offset")) else 0,
                check_in=criteri.get("check_in") or None,
                check_out=criteri.get("check_out") or None)
            res = self._cat.cerca(c)
            return RispostaConcierge(200, {"money_unit": "cents_integer", **res})
        except Exception:
            logger.error("scopri: eccezione ISOLATA", exc_info=True)
            return RispostaConcierge(503, {"errore": "service_unavailable"})

    # ── ATTO 2: preventivo firmato ─────────────────────────────────────────────
    def quota(self, richiesta: Any) -> RispostaConcierge:
        if not isinstance(richiesta, dict):
            return RispostaConcierge(400, {"errore": "payload_non_oggetto"})
        alloggio = _stringa(richiesta.get("alloggio_id"))
        if alloggio is None or "|" in alloggio:
            return RispostaConcierge(400, {"errore": "alloggio_id_non_valido"})
        ci = _stringa(richiesta.get("check_in"))
        co = _stringa(richiesta.get("check_out"))
        if ci is None or co is None:
            return RispostaConcierge(400, {"errore": "date_mancanti"})
        party = richiesta.get("party", 1)
        if not _intero(party) or not (1 <= party <= PARTY_MAX):
            return RispostaConcierge(400, {"errore": "party_non_valido"})
        fonte = _stringa(richiesta.get("fonte")) or "marketplace"   # diretto | marketplace
        valuta = self._valuta_alloggio(alloggio)   # LIKE-FOR-LIKE: si addebita nella valuta dell'host

        try:
            from fase58_channel_manager import notti
            elenco_notti = notti(ci, co)
            if elenco_notti is None:
                return RispostaConcierge(422, {"errore": "date_non_valide"})
            if self._inv.disponibile(alloggio, ci, co) is not True:
                return RispostaConcierge(409, {"errore": "non_disponibile"})
            netto = 0
            for g in elenco_notti:
                stato = self._inv.stato_giorno(alloggio, g)
                p = stato.get("prezzo_netto_cents") if isinstance(stato, dict) else None
                if not _intero(p) or p <= 0:
                    return RispostaConcierge(422, {"errore": "non_quotabile"})
                netto += p
            # SCONTO NON-RIMBORSABILE (onesto, finanziato dall'HOST come Booking/Airbnb): se l'host
            # ha scelto 'non_rimborsabile', accetta -12% sul netto in cambio della CERTEZZA (nessun
            # rimborso) -> l'ospite paga meno; noi prendiamo comm sul netto scontato -> mai in perdita.
            netto_listino = netto
            sconto_nr = 0
            try:
                if self._cat is not None and \
                        self._cat.politica_cancellazione_di(alloggio) == "non_rimborsabile":
                    sconto_nr = netto_listino * 1200 // 10000        # 12%
                    netto = netto_listino - sconto_nr
            except Exception:
                sconto_nr = 0
            try:
                comm = (self._commissione_all(netto, alloggio, fonte)
                        if self._commissione_all else self._commissione(netto))
            except Exception:
                comm = self._commissione(netto)
            if not _intero(comm) or comm < 0:
                comm = 0
            if comm > netto:
                comm = netto
            # MODELLO 0% OSPITE: l'ospite paga il PULITO; commissione DEDOTTA dall'host.
            netto_host = netto - comm
            # CREDITO FONDATORE: sconto all'ospite finanziato dalla NOSTRA commissione, con
            # guardia floor (la nostra presa resta sopra i costi) -> ZERO perdita. Host invariato.
            sconto = self._sconto_credito(richiesta.get("credito_token"), netto, comm)
            guest = netto - sconto
            if guest <= 0 or guest > MAX_CENTS:
                return RispostaConcierge(422, {"errore": "prezzo_fuori_banda"})
            # TASSA DI SOGGIORNO (pass-through alla citta', mostrata PRIMA dell'acquisto).
            # Calcolata dalla regola dichiarata dall'host; ignota -> 0 (mai inventare). Isolata.
            tassa = 0
            try:
                if self._tassa_all:
                    t = self._tassa_all(alloggio, notti=len(elenco_notti),
                                        ospiti=party, imponibile=netto)
                    tassa = t if (_intero(t) and t >= 0) else 0
            except Exception:
                tassa = 0
            totale = guest + tassa
            # COSTO SERVIZIO PAGAMENTI (carta): a carico dell'HOST, dedotto dal suo incasso.
            # Copre la fee Stripe sul TOTALE addebitato -> noi MAI in perdita. L'ospite paga
            # SEMPRE il prezzo pulito (0%): il totale non cambia, cambia solo il netto host.
            costo_pagamento = (totale * self._psp_bps) // 10000
            netto_host = max(0, netto_host - costo_pagamento)
        except Exception:
            logger.error("quota: eccezione ISOLATA", exc_info=True)
            return RispostaConcierge(503, {"errore": "service_unavailable"})

        scade_a = self._now() + self._ttl
        payload = {
            "alloggio_id": alloggio, "check_in": ci, "check_out": co, "party": party,
            "prezzo_netto_cents": netto, "commissione_cents": comm,
            "prezzo_guest_cents": guest, "netto_host_cents": netto_host,
            "sconto_credito_cents": sconto,
            "sconto_non_rimborsabile_cents": sconto_nr, "prezzo_listino_cents": netto_listino,
            "tassa_soggiorno_cents": tassa, "totale_cents": totale,
            "costo_pagamento_cents": costo_pagamento,
            "fonte": fonte, "exp": scade_a, "valuta": valuta,
            # nonce: ogni preventivo e' UNICO -> due clienti distinti per la stessa
            # stanza/date competono davvero (idem-key distinte); un retry dello stesso
            # token resta idempotente (stesso nonce -> stessa firma -> stessa idem-key).
            "nonce": secrets.token_hex(8),
        }
        token = self._firma.codifica(payload)
        # INDICATIVO (solo display): l'ospite vede ~la sua valuta, ma l'addebito resta in `valuta`
        v_osp = _stringa(richiesta.get("valuta_ospite"))
        tot_ind = self._converti_indicativo(valuta, v_osp, totale)
        return RispostaConcierge(200, {
            "quote_token": token,
            "alloggio_id": alloggio,
            "check_in": ci, "check_out": co, "party": party, "notti": len(elenco_notti),
            "prezzo_netto_cents": netto,        # prezzo di listino (lordo)
            "commissione_cents": comm,          # int (dedotta dall'host)
            "prezzo_guest_cents": guest,        # il soggiorno (pulito, 0% guest fee)
            "netto_host_cents": netto_host,     # l'host riceve QUESTO (gia' al netto del costo carta)
            "costo_pagamento_cents": costo_pagamento,  # costo carta a carico host (copre Stripe; ns 0 margine)
            "sconto_credito_cents": sconto,     # credito fondatore applicato (da nostra commissione)
            "sconto_non_rimborsabile_cents": sconto_nr,   # -12% se non-rimborsabile (finanziato host)
            "prezzo_listino_cents": netto_listino,        # prezzo pieno (per mostrare il risparmio)
            "tassa_soggiorno_cents": tassa,     # tassa citta' (pass-through, voce separata visibile)
            "totale_cents": totale,             # quello che l'ospite paga DAVVERO = soggiorno + tassa
            "fonte": fonte,
            "valuta": valuta,                   # valuta dell'ADDEBITO (like-for-like)
            "valuta_indicativa": (v_osp if tot_ind else ""),
            "totale_indicativo_cents": tot_ind,  # display ~valuta ospite (la sua banca converte)
            "scade_a": scade_a,
            "money_unit": "cents_integer",
        })

    def _converti_indicativo(self, da: str, a: Any, importo: int) -> int:
        """Stima indicativa nella valuta dell'ospite (tasso MID, nessun markup occulto). Solo
        display: l'addebito resta in `da`. 0 se manca il tasso o la valuta e' la stessa."""
        if not (self._tasso and isinstance(a, str) and a and a != da and _intero(importo)):
            return 0
        try:
            tasso = self._tasso(da, a)
            if tasso is None:
                return 0
            val = int(round(importo * float(tasso)))
            return val if 0 < val <= MAX_CENTS else 0
        except Exception:
            return 0

    def _valuta_alloggio(self, slug: Any) -> str:
        """LIKE-FOR-LIKE: valuta dell'annuncio (l'host prezza in X -> ospite paga X -> host
        incassa X -> commissione X). Nessuna conversione forzata = ZERO rischio cambio per noi."""
        try:
            if self._cat is not None:
                d = self._cat.dettaglio(slug)
                v = d.get("valuta") if isinstance(d, dict) else None
                if isinstance(v, str) and 1 <= len(v) <= 8:
                    return v
        except Exception:
            pass
        return self._valuta

    def _sconto_credito(self, token: Any, netto: int, comm: int) -> int:
        """Sconto Credito Fondatore: verifica il token firmato e applica al MASSIMO quanto la
        nostra commissione puo' assorbire restando sopra i costi (Stripe ~2.9%+0.25 + buffer).
        Non falsificabile, non scaduto. Se non c'e' margine -> 0 (mai in perdita)."""
        if not (isinstance(token, str) and token):
            return 0
        try:
            v = self._firma.decodifica(token)
            if not isinstance(v, dict) or v.get("tipo") != "credito_fondatore":
                return 0
            exp = v.get("exp")
            if not (isinstance(exp, int) and not isinstance(exp, bool) and exp >= self._now()):
                return 0
            cr = v.get("credito_cents", 0)
            cr = cr if (_intero(cr) and cr > 0) else 0
            costo = netto * 290 // 10000 + 25 + 200      # Stripe stimato + buffer prudenziale
            margine_disponibile = max(0, comm - costo)   # quanto possiamo regalare senza perdere
            return max(0, min(cr, margine_disponibile))
        except Exception:
            return 0

    # ── ATTO 3: prenotazione (verifica firma -> blocco atomico idempotente) ────
    def prenota(self, payload: Any) -> RispostaConcierge:
        if not isinstance(payload, dict):
            return RispostaConcierge(400, {"errore": "payload_non_oggetto"})
        token = payload.get("quote_token")
        dati = self._firma.decodifica(token)
        if dati is None:
            return RispostaConcierge(400, {"errore": "quote_non_valida"})  # firma rotta
        if not _intero(dati.get("exp")) or dati["exp"] < self._now():
            return RispostaConcierge(410, {"errore": "quote_scaduta"})
        email = _stringa(payload.get("email"))
        if email is None or "@" not in email:
            return RispostaConcierge(400, {"errore": "email_non_valida"})

        alloggio = dati.get("alloggio_id")
        ci, co = dati.get("check_in"), dati.get("check_out")
        guest = dati.get("prezzo_guest_cents")
        if not (isinstance(alloggio, str) and isinstance(ci, str) and isinstance(co, str)
                and _intero(guest)):
            return RispostaConcierge(400, {"errore": "quote_corrotta"})

        # idem-key = firma del token: doppio book dello stesso token -> una prenotazione
        idem = token.split(".")[-1]
        try:
            esito = self._inv.blocca(alloggio, ci, co, idem_key=idem, origine="concierge")
        except Exception:
            logger.error("prenota: blocco ISOLATO fallito", exc_info=True)
            return RispostaConcierge(503, {"errore": "service_unavailable"})

        if not getattr(esito, "ok", False):
            motivo = getattr(esito, "motivo", "errore")
            status = 409 if motivo in ("pieno", "chiuso", "min_notti",
                                       "giorno_non_caricato") else 422
            return RispostaConcierge(status, {"stato": "rifiutata", "motivo": motivo})

        riferimento = idem[:24]
        # l'ospite paga il TOTALE (soggiorno + tassa di soggiorno) -> la tassa viene incassata
        totale_charge = dati.get("totale_cents")
        totale_charge = totale_charge if _intero(totale_charge) and totale_charge > 0 else guest
        payment_url = self._link_isolato({
            "alloggio_id": alloggio, "check_in": ci, "check_out": co, "email": email,
            "prezzo_guest_cents": guest, "totale_cents": totale_charge,
            "riferimento": riferimento})
        corpo: Dict[str, Any] = {
            "stato": "confermata",
            "riferimento": riferimento,
            "alloggio_id": alloggio, "check_in": ci, "check_out": co,
            "prezzo_guest_cents": guest,         # int (quello firmato, immutabile)
            "netto_host_cents": dati.get("netto_host_cents", guest),   # l'host riceve QUESTO
            "tassa_soggiorno_cents": dati.get("tassa_soggiorno_cents", 0),
            "totale_cents": dati.get("totale_cents", guest),   # soggiorno + tassa
            "valuta": dati.get("valuta", self._valuta),
            "idempotente": bool(getattr(esito, "idempotente", False)),
            "money_unit": "cents_integer",
        }
        if payment_url:
            corpo["payment_url"] = payment_url
        return RispostaConcierge(201, corpo)

    # ── tool agent-facing aggiuntivi (read-only, deterministici) ───────────────
    def dettaglio(self, richiesta: Any) -> RispostaConcierge:
        """Scheda completa di un alloggio (per l'agente esterno). Read-only."""
        if not isinstance(richiesta, dict):
            return RispostaConcierge(400, {"errore": "payload_non_oggetto"})
        if self._cat is None:
            return RispostaConcierge(501, {"errore": "catalogo_non_disponibile"})
        slug = _stringa(richiesta.get("alloggio_id"))
        if slug is None:
            return RispostaConcierge(400, {"errore": "alloggio_id_non_valido"})
        try:
            d = self._cat.dettaglio(slug)
        except Exception:
            logger.error("dettaglio: eccezione ISOLATA", exc_info=True)
            return RispostaConcierge(503, {"errore": "service_unavailable"})
        if d is None:
            return RispostaConcierge(404, {"errore": "not_found"})
        return RispostaConcierge(200, {"money_unit": "cents_integer", **d})

    def lingue(self, richiesta: Any = None) -> RispostaConcierge:
        """Lingue supportate (l'agente sa che puo' localizzare l'offerta)."""
        from fase61_localizzazione import LINGUE_SUPPORTATE
        return RispostaConcierge(200, {"lingue": list(LINGUE_SUPPORTATE)})

    def confronto(self, richiesta: Any) -> RispostaConcierge:
        """Confronto noi-vs-OTA (fase69) per aiutare un agente a convincere un host.
        Read-only, denaro in centesimi interi, nessun effetto."""
        if not isinstance(richiesta, dict):
            return RispostaConcierge(400, {"errore": "payload_non_oggetto"})
        from fase69_trasparenza import confronta_piattaforma
        prezzo = richiesta.get("prezzo_cents")
        if not _intero(prezzo) or prezzo <= 0:
            return RispostaConcierge(400, {"errore": "prezzo_non_valido"})
        ota = richiesta.get("ota", "booking")
        ota = ota if isinstance(ota, str) else "booking"
        return RispostaConcierge(200, confronta_piattaforma(prezzo, ota).as_dict())

    def _link_isolato(self, dati: Dict[str, Any]) -> Optional[str]:
        if self._link is None:
            return None
        try:
            url = self._link(dati)
            return url if isinstance(url, str) and url else None
        except Exception:
            logger.warning("link pagamento fallito (ignorato)", exc_info=True)
            return None


def crea_protocollo(inventario: Any, segreto: bytes, **kw: Any) -> ProtocolloConcierge:
    return ProtocolloConcierge(inventario, FirmaQuote(segreto), **kw)


# ─────────────────────────────────────────────────────────────────────────────
# Rotte agent-discoverable (import lazy)
# ─────────────────────────────────────────────────────────────────────────────
def registra_concierge(target: Any, proto: ProtocolloConcierge, *,
                       base: str = "/concierge") -> None:
    from flask import request, jsonify

    @target.route(base + "/manifest", methods=["GET"], endpoint="concierge_manifest")
    def _manifest() -> Any:
        return jsonify(proto.manifest()), 200

    @target.route(base + "/search", methods=["POST"], endpoint="concierge_search")
    def _search() -> Any:
        r = proto.scopri(request.get_json(silent=True))
        return jsonify(r.corpo), r.status

    @target.route(base + "/quote", methods=["POST"], endpoint="concierge_quote")
    def _quote() -> Any:
        r = proto.quota(request.get_json(silent=True))
        return jsonify(r.corpo), r.status

    @target.route(base + "/book", methods=["POST"], endpoint="concierge_book")
    def _book() -> Any:
        r = proto.prenota(request.get_json(silent=True))
        return jsonify(r.corpo), r.status
