"""
CORE_AUTO / Tavola VIP MVP - Fase 36: API HTTP delle prenotazioni.

Espone via HTTP il flusso del prodotto autonomo (niente ricerca pubblica: il link
lo genera l'agente/PR e lo manda al cliente):
  POST /reservations            -> crea prenotazione + ritorna il LINK di pagamento
  GET  /reservations/<id>       -> stato
  POST /reservations/<id>/cancel-> annulla (libera il tavolo)
  POST /payments/webhook        -> notifica PSP (FIRMATA) -> conferma + voucher

Isolamento (come registra_gateway, fase28): import LAZY di Flask; il modulo e'
importabile anche senza Flask. Le route di prenotazione sono protette da una
API-key opzionale (per l'agente/PR); il webhook NON usa quella auth: e' autenticato
dalla FIRMA del PSP (verificata in fase35), cosi' un webhook non firmato non
conferma nulla.
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Any, Optional

from fase17_money import parse_cent
from fase34_prenotazioni import RichiestaPrenotazione

logger = logging.getLogger("core_auto.booking_api")


def registra_rotte(target: Any, motore: Any, servizio: Any, *,
                   api_key: Optional[str] = None, admin_key: Optional[str] = None,
                   firma_header: str = "X-Pagamento-Firma") -> None:
    """Registra le route su un Blueprint/app Flask. `api_key`: se impostata, le
    route di prenotazione richiedono `X-Booking-Key`. `admin_key`: richiesta da
    `X-Admin-Key` per APPROVARE/RIFIUTARE i rimborsi (movimento di denaro). Il
    webhook e' autenticato dalla sola firma del PSP."""
    from flask import request, jsonify

    def _auth_ok() -> bool:
        if not api_key:
            return True
        return hmac.compare_digest(request.headers.get("X-Booking-Key", ""), api_key)

    def _admin_ok() -> bool:
        # Niente admin_key configurata => nessuno puo' muovere denaro (fail-closed).
        return bool(admin_key) and hmac.compare_digest(
            request.headers.get("X-Admin-Key", ""), admin_key)

    @target.route("/health", methods=["GET"], endpoint="tv_health")
    def _health():
        # Liveness/readiness per healthcheck Docker/nginx (no auth).
        return jsonify({"status": "ok", "service": "tavolavip"}), 200

    @target.route("/reservations", methods=["POST"], endpoint="tv_crea")
    def _crea():
        if not _auth_ok():
            return jsonify({"error": "unauthorized"}), 401
        d = request.get_json(silent=True)
        if not isinstance(d, dict):
            return jsonify({"error": "invalid_payload"}), 400
        try:
            req = RichiestaPrenotazione(
                alloggio_id=str(d["alloggio_id"]),
                ospite_nome=str(d.get("ospite_nome", "")),
                ospite_email=str(d.get("ospite_email", "")),
                ospite_telefono=str(d.get("ospite_telefono", "")),
                check_in=str(d["check_in"]), check_out=str(d["check_out"]),
                importo_totale_cents=parse_cent(d["importo_totale_cents"], "importo_totale_cents"),
                commissione_cents=parse_cent(d["commissione_cents"], "commissione_cents"))
        except (KeyError, ValueError, TypeError) as e:
            return jsonify({"error": "invalid_payload", "dettaglio": str(e)}), 400
        esito = motore.crea(req)
        if not esito.ok:
            return jsonify({"error": esito.motivo}), (409 if esito.motivo == "non_disponibile" else 400)
        link = servizio.crea_link_pagamento(
            pagamento_id=esito.pagamento_id,
            importo_cents=req.importo_totale_cents, email=req.ospite_email)
        return jsonify({"prenotazione_id": esito.prenotazione_id,
                        "pagamento_id": esito.pagamento_id, "stato": esito.stato,
                        "payment_url": link.url}), 201

    @target.route("/reservations/<int:pid>", methods=["GET"], endpoint="tv_stato")
    def _stato(pid: int):
        if not _auth_ok():
            return jsonify({"error": "unauthorized"}), 401
        st = motore.stato(pid)
        return (jsonify(st), 200) if st else (jsonify({"error": "not_found"}), 404)

    @target.route("/reservations/<int:pid>/cancel", methods=["POST"], endpoint="tv_cancel")
    def _cancel(pid: int):
        if not _auth_ok():
            return jsonify({"error": "unauthorized"}), 401
        return ((jsonify({"annullata": True}), 200) if motore.annulla(pid)
                else (jsonify({"error": "non_annullabile"}), 409))

    @target.route("/reservations/<int:pid>/refund-request", methods=["POST"],
                  endpoint="tv_refund_req")
    def _refund_req(pid: int):
        if not _auth_ok():
            return jsonify({"error": "unauthorized"}), 401
        return ((jsonify({"rimborso_richiesto": True}), 200)
                if servizio.richiedi_rimborso(pid)
                else (jsonify({"error": "non_rimborsabile"}), 409))

    @target.route("/reservations/<int:pid>/refund-approve", methods=["POST"],
                  endpoint="tv_refund_approve")
    def _refund_approve(pid: int):
        if not _admin_ok():                    # SOLO admin: muove denaro reale
            return jsonify({"error": "forbidden"}), 403
        r = servizio.approva_rimborso(pid)
        codici = {"rimborsata": 200, "non_trovata": 404,
                  "stato_non_valido": 409, "refund_psp_fallito": 502}
        return jsonify({"esito": r.esito, "riferimento": r.riferimento}), \
            codici.get(r.esito, 500)

    @target.route("/reservations/<int:pid>/refund-reject", methods=["POST"],
                  endpoint="tv_refund_reject")
    def _refund_reject(pid: int):
        if not _admin_ok():
            return jsonify({"error": "forbidden"}), 403
        return ((jsonify({"rifiutato": True}), 200)
                if servizio.rifiuta_rimborso(pid)
                else (jsonify({"error": "stato_non_valido"}), 409))

    @target.route("/payments/webhook", methods=["POST"], endpoint="tv_webhook")
    def _webhook():
        firma = request.headers.get(firma_header, "")
        esito = servizio.gestisci_webhook(request.get_data(), firma)
        codice = 200 if esito.esito in ("confermato", "ignorato",
                                        "pagamento_sconosciuto") else 400
        return jsonify({"esito": esito.esito,
                        "prenotazione_id": esito.prenotazione_id,
                        "voucher": esito.voucher}), codice


def crea_app_booking(motore: Any, servizio: Any, *, api_key: Optional[str] = None,
                     admin_key: Optional[str] = None,
                     prefisso: str = "/api/v1") -> Any:
    """Crea un'app Flask standalone per il prodotto Tavola VIP (utile per il
    deploy autonomo e per i test). Le route sono montate sotto `prefisso`."""
    from flask import Flask, Blueprint
    app = Flask("tavola_vip")
    bp = Blueprint("tavola_vip", __name__, url_prefix=prefisso)
    registra_rotte(bp, motore, servizio, api_key=api_key, admin_key=admin_key)
    app.register_blueprint(bp)
    return app


def crea_app_da_env() -> Any:
    """Bootstrap del servizio Tavola VIP da variabili d'ambiente (target gunicorn:
    `gunicorn 'fase36_booking_api:crea_app_da_env()'`). Legge: DB_PATH,
    BOOKING_API_KEY, STRIPE_API_KEY/STRIPE_WEBHOOK_SECRET, BOOKING_SUCCESS_URL,
    BOOKING_CANCEL_URL. Crea lo schema al boot e sceglie il PSP reale se la chiave
    Stripe e' presente (altrimenti stub di sviluppo)."""
    import sqlite3
    from fase34_prenotazioni import MotorePrenotazioni
    from fase35_pagamenti import crea_provider_pagamenti, ServizioPagamenti

    db_path = os.environ.get("DB_PATH", "data/marketplace.db")
    motore = MotorePrenotazioni(lambda: sqlite3.connect(db_path, timeout=30))
    motore.inizializza_schema()
    provider = crea_provider_pagamenti(
        success_url=os.environ.get("BOOKING_SUCCESS_URL"),
        cancel_url=os.environ.get("BOOKING_CANCEL_URL"))
    from fase39_whatsapp import crea_servizio_notifiche_completo
    servizio = ServizioPagamenti(motore, provider,
                                 notifiche=crea_servizio_notifiche_completo())
    return crea_app_booking(motore, servizio,
                            api_key=os.environ.get("BOOKING_API_KEY"),
                            admin_key=os.environ.get("BOOKING_ADMIN_KEY"))
