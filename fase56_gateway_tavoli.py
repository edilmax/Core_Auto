"""
CORE_AUTO - Fase 56: Gateway Tavoli VIP - Contratti JSON + integrazione Gateway.

Ponte Frontend<->Backend per la UI dei Tavoli VIP. Collega il Bootstrap (fase55
SistemaMango) al perimetro gateway gia' collaudato (fase28: ClientRegistry timing-safe,
risposte standardizzate, validatore che NON solleva mai) e definisce i CONTRATTI di
interscambio JSON per ricevere richieste di prenotazione tavolo dalla UI e restituire
risposte deterministiche.

REGOLE TASSATIVE:
  - Denaro SOLO in centesimi INTERI (`*_cents: int`). Float, bool e stringhe numeriche
    ("10.50", "1000") sono RIFIUTATE in ingresso (zero float mascherati nel JSON).
    In uscita ogni importo e' int; i tassi (conversion-rate) viaggiano in basis-point
    interi (no float). La valuta e' solo un'etichetta: la matematica resta in cents.
  - Zero disallineamenti di formato: contratto esplicito, validazione blindata.
  - Money-path unico = Ponte (fase49) via il SistemaMango (persistenza/quota/health
    riusate); il gateway non tocca il denaro direttamente.

ClientRegistry ENTERPRISE: i gestori dei locali notturni sono clienti enterprise
SEPARATI (api_key -> ClienteEnterprise{client_id, locale}); isolamento per-tenant
(la chiave d'idempotenza e' namespacata sul client_id -> nessuna collisione cross-locale).

SOPRAVVIVENZA TOTALE: `processa_*` non sollevano MAI (cintura -> 503). Auth timing-safe.
Gate salute (circuito fase53) e quota (governatore fase32) onorati. Default-off via
SistemaMango (sistema spento -> 503 service_disabled).
"""
from __future__ import annotations

import datetime
import hmac
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from fase49_ponte_booking import DatiConversione

logger = logging.getLogger("core_auto.gateway_tavoli")

LIMITE_CAMPO = 256
MAX_CENTS = 1_000_000_00  # 1.000.000 unita' valuta: tetto anti-overflow/abuso


# ─────────────────────────────────────────────────────────────────────────────
# ClientRegistry ENTERPRISE (gestori locali notturni come tenant separati)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ClienteEnterprise:
    client_id: str
    locale: str
    tier: str = "enterprise"


class RegistroEnterprise:
    """api_key -> ClienteEnterprise. Autenticazione timing-safe (full-scan, come fase28)."""

    def __init__(self, clienti: Optional[Dict[str, ClienteEnterprise]] = None) -> None:
        self._clienti = dict(clienti or {})

    @classmethod
    def da_dict(cls, mappa: Dict[str, Tuple[str, str]]) -> "RegistroEnterprise":
        """mappa: api_key -> (client_id, locale)."""
        return cls({k: ClienteEnterprise(cid, loc) for k, (cid, loc) in mappa.items()})

    @classmethod
    def da_env(cls, var: str = "TAVOLI_CLIENTS") -> "RegistroEnterprise":
        """Carica 'key:client_id:locale,...' dall'ambiente."""
        import os
        clienti: Dict[str, ClienteEnterprise] = {}
        for riga in os.environ.get(var, "").split(","):
            parti = [p.strip() for p in riga.split(":")]
            if len(parti) == 3 and all(parti):
                clienti[parti[0]] = ClienteEnterprise(parti[1], parti[2])
        return cls(clienti)

    def autentica(self, api_key: Any) -> Optional[ClienteEnterprise]:
        api_key = str(api_key or "")
        trovato: Optional[ClienteEnterprise] = None
        for k, cliente in self._clienti.items():
            if hmac.compare_digest(api_key, k):
                trovato = cliente            # nessun early-exit (no timing leak)
        return trovato


# ─────────────────────────────────────────────────────────────────────────────
# Contratto JSON di RICHIESTA (UI -> backend)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RichiestaTavolo:
    chiave_conversione: str
    tavolo_id: str
    check_in: str
    check_out: str
    email: str
    prezzo_guest_cents: int
    incasso_mango_cents: int
    ospite_nome: str = ""
    ospite_telefono: str = ""


@dataclass
class RispostaTavoli:
    status: int
    corpo: Dict[str, Any]


_CAMPI_STR = ("chiave_conversione", "tavolo_id", "check_in", "check_out", "email")
_CAMPI_CENTS = ("prezzo_guest_cents", "incasso_mango_cents")
_OPZIONALI_STR = ("ospite_nome", "ospite_telefono")


def _intero_cents(v: Any) -> bool:
    # SOLO int puro: niente bool, niente float (anche 10.0), niente stringa numerica
    return isinstance(v, int) and not isinstance(v, bool)


def valida_richiesta_tavolo(data: Any) -> Tuple[bool, str, Optional[RichiestaTavolo]]:
    """Validatore BLINDATO del contratto (non solleva mai). Denaro SOLO int cents."""
    if not isinstance(data, dict):
        return False, "payload_non_oggetto", None

    campi: Dict[str, str] = {}
    for nome in _CAMPI_STR:
        v = data.get(nome)
        if v is None:
            return False, f"campo_mancante:{nome}", None
        if not isinstance(v, str):
            return False, f"campo_non_stringa:{nome}", None
        v = v.strip()
        if not v:
            return False, f"campo_vuoto:{nome}", None
        if len(v) > LIMITE_CAMPO:
            return False, f"campo_troppo_lungo:{nome}", None
        campi[nome] = v

    if "@" not in campi["email"]:
        return False, "email_non_valida", None
    if not _data_iso(campi["check_in"]):
        return False, "data_non_valida:check_in", None
    if not _data_iso(campi["check_out"]):
        return False, "data_non_valida:check_out", None
    if _data_iso(campi["check_in"]) >= _data_iso(campi["check_out"]):
        return False, "date_incoerenti", None

    cents: Dict[str, int] = {}
    for nome in _CAMPI_CENTS:
        v = data.get(nome)
        if v is None:
            return False, f"campo_mancante:{nome}", None
        if not _intero_cents(v):
            return False, f"denaro_non_intero:{nome}", None   # float/str/bool -> KO
        if v < 0:
            return False, f"denaro_negativo:{nome}", None
        if v > MAX_CENTS:
            return False, f"denaro_oltre_tetto:{nome}", None
        cents[nome] = v

    if cents["incasso_mango_cents"] > cents["prezzo_guest_cents"]:
        return False, "incasso_oltre_prezzo", None
    if cents["prezzo_guest_cents"] <= 0:
        return False, "prezzo_nullo", None

    opz: Dict[str, str] = {}
    for nome in _OPZIONALI_STR:
        v = data.get(nome, "")
        if not isinstance(v, str):
            return False, f"campo_non_stringa:{nome}", None
        opz[nome] = v.strip()[:LIMITE_CAMPO]

    return True, "", RichiestaTavolo(
        chiave_conversione=campi["chiave_conversione"], tavolo_id=campi["tavolo_id"],
        check_in=campi["check_in"], check_out=campi["check_out"], email=campi["email"],
        prezzo_guest_cents=cents["prezzo_guest_cents"],
        incasso_mango_cents=cents["incasso_mango_cents"],
        ospite_nome=opz["ospite_nome"], ospite_telefono=opz["ospite_telefono"])


def _data_iso(s: str):
    try:
        return datetime.date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Mappa esito Ponte -> HTTP (contratto di RISPOSTA)
# ─────────────────────────────────────────────────────────────────────────────
_AZIONE_STATUS = {
    "agganciata": 201,
    "non_disponibile": 409,
    "importi_non_validi": 422,
    "date_non_valide": 422,
    "dati_non_validi": 400,
    "disattivato": 503,
}


class GatewayTavoli:
    """Perimetro JSON dei Tavoli VIP. Auth enterprise -> validazione contratto ->
    instradamento nel SistemaMango (money-path = Ponte) -> risposta standardizzata."""

    def __init__(self, registro: RegistroEnterprise, sistema: Any, *,
                 valuta: str = "EUR") -> None:
        self._reg = registro
        self._sys = sistema
        self._valuta = valuta

    # --- contratto: crea prenotazione tavolo ---
    def processa_prenotazione(self, api_key: Any, data: Any) -> RispostaTavoli:
        cliente = self._reg.autentica(api_key)
        if cliente is None:
            return RispostaTavoli(401, {"errore": "unauthorized"})
        ok, codice, req = valida_richiesta_tavolo(data)
        if not ok:
            return RispostaTavoli(400, {"errore": "invalid_payload", "dettaglio": codice})
        try:
            return self._instrada(cliente, req)
        except Exception:
            logger.error("GatewayTavoli: eccezione ISOLATA (-> 503)", exc_info=True)
            return RispostaTavoli(503, {"errore": "service_unavailable"})

    def _instrada(self, cliente: ClienteEnterprise, req: RichiestaTavolo) -> RispostaTavoli:
        if not getattr(self._sys.config, "abilitato", False):
            return RispostaTavoli(503, {"errore": "service_disabled"})
        # gate salute (circuito fase53): funnel in pausa -> rifiuta pulito
        if not self._sys.circuito.consenti():
            return RispostaTavoli(503, {"errore": "service_paused"})

        # tenant isolation: chiave d'idempotenza namespacata sul client_id
        dati = DatiConversione(
            chiave_conversione=f"{cliente.client_id}:{req.chiave_conversione}",
            alloggio_id=req.tavolo_id, check_in=req.check_in, check_out=req.check_out,
            email=req.email, prezzo_guest_cents=req.prezzo_guest_cents,
            incasso_mango_cents=req.incasso_mango_cents,
            ospite_nome=req.ospite_nome, ospite_telefono=req.ospite_telefono,
            origine=f"tavoli:{cliente.client_id}")

        # instradamento nel sistema: scheduler -> orchestratore -> Ponte (+persistenza/quota)
        esito = self._sys.scheduler.esegui([{"conversione": dati}])
        if not getattr(esito, "abilitato", False):
            return RispostaTavoli(503, {"errore": "service_disabled"})
        if esito.cicli_differiti:
            return RispostaTavoli(429, {"errore": "quota_superata"})
        if not esito.report:
            return RispostaTavoli(503, {"errore": "service_unavailable"})

        conv = esito.report[0].conversione
        if conv is None:
            return RispostaTavoli(503, {"errore": "money_path_off"})
        return self._risposta_da_esito(cliente, req, conv)

    def _risposta_da_esito(self, cliente: ClienteEnterprise, req: RichiestaTavolo,
                           conv: Any) -> RispostaTavoli:
        azione = getattr(conv, "azione", "errore")
        corpo: Dict[str, Any] = {
            "stato": azione,
            "locale": cliente.locale,
            "tavolo_id": req.tavolo_id,
            "prezzo_guest_cents": req.prezzo_guest_cents,   # int
            "incasso_mango_cents": req.incasso_mango_cents,  # int
            "valuta": self._valuta,                          # solo etichetta
            "idempotente": bool(getattr(conv, "idempotente", False)),
        }
        if getattr(conv, "ok", False):
            corpo["prenotazione_id"] = getattr(conv, "prenotazione_id", None)
            corpo["pagamento_id"] = getattr(conv, "pagamento_id", None)
            corpo["payment_url"] = getattr(conv, "payment_url", None)
        else:
            corpo["errore"] = azione
        return RispostaTavoli(_AZIONE_STATUS.get(azione, 502), corpo)

    # --- contratto: metriche del funnel (denaro/tassi interi) ---
    def processa_metriche(self, api_key: Any) -> RispostaTavoli:
        cliente = self._reg.autentica(api_key)
        if cliente is None:
            return RispostaTavoli(401, {"errore": "unauthorized"})
        try:
            m = self._sys.metriche()
            return RispostaTavoli(200, {
                "cicli_totali": int(m.cicli_totali),
                "cicli_ok": int(m.cicli_ok),
                "conversioni_tentate": int(m.conversioni_tentate),
                "conversioni_riuscite": int(m.conversioni_riuscite),
                # tasso in BASIS-POINT interi: zero float nel JSON
                "conversion_rate_bps": int(round(m.conversion_rate * 10000)),
                "circuito": self._sys.circuito.stato,
            })
        except Exception:
            logger.error("GatewayTavoli metriche: eccezione ISOLATA (-> 503)", exc_info=True)
            return RispostaTavoli(503, {"errore": "service_unavailable"})


def crea_gateway_tavoli(registro: RegistroEnterprise, sistema: Any, *,
                        valuta: str = "EUR") -> GatewayTavoli:
    return GatewayTavoli(registro, sistema, valuta=valuta)


def registra_gateway_tavoli(target: Any, gateway: GatewayTavoli, *,
                            path_prenota: str = "/tavoli/prenota",
                            path_metriche: str = "/tavoli/metriche") -> None:
    """Registra le route Flask (import lazy). Auth via header X-Client-Key."""
    from flask import request, jsonify

    @target.route(path_prenota, methods=["POST"], endpoint="tavoli_prenota")
    def _prenota() -> Any:
        r = gateway.processa_prenotazione(
            request.headers.get("X-Client-Key", ""), request.get_json(silent=True))
        return jsonify(r.corpo), r.status

    @target.route(path_metriche, methods=["GET"], endpoint="tavoli_metriche")
    def _metriche() -> Any:
        r = gateway.processa_metriche(request.headers.get("X-Client-Key", ""))
        return jsonify(r.corpo), r.status
