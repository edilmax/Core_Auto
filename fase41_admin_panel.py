"""
CORE_AUTO / Tavola VIP - Fase 41: Pannello Admin Web (ponte di comando operativo).

Dashboard web MINIMALE e ULTRA-SICURA per operare senza terminale/curl: vedere lo
stato delle prenotazioni (ordinate per data = vista calendario), e APPROVARE i
rimborsi agganciandosi al flusso gated del #2 (richiesta -> admin approva/rifiuta).

Approccio = **Variante B** (UI integrata Flask, HTML server-rendered), vincitrice di
un benchmark a rubrica (JSON-only / UI-Flask / SPA): elimina davvero il curl, ZERO
toolchain frontend (dipendenza assente), superficie minima, testabile col test_client.

Sicurezza forte e a strati:
- HTTP **Basic auth** (utente+password da env, confronto TIMING-SAFE) su OGNI rotta.
- **Token CSRF** obbligatorio su tutte le azioni POST (un attaccante non puo' leggere
  la pagina perche' gated da Basic auth -> non conosce il token).
- FAIL-CLOSED: senza credenziali configurate il pannello e' DISABILITATO (503).
- Header di sicurezza (no-store, X-Frame-Options DENY, nosniff, CSP restrittiva).
- Auto-escape Jinja su tutti i dati; nessun segreto renderizzato. Da servire dietro
  HTTPS (lo stack nginx TLS e' gia' pronto, FASE 5.1).
"""
from __future__ import annotations

import hmac
import logging
import secrets
from typing import Any, Optional

logger = logging.getLogger("core_auto.admin_panel")

_TEMPLATE = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<title>Tavola VIP - Admin</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:system-ui,sans-serif;margin:1.5rem;background:#f7f7f8;color:#222}
h1{font-size:1.3rem}h2{font-size:1rem;margin-top:1.5rem}table{border-collapse:collapse;width:100%;background:#fff}
th,td{border:1px solid #ddd;padding:.4rem .6rem;text-align:left;font-size:.85rem}
th{background:#f0f0f3}.s{font-size:.75rem;padding:.1rem .4rem;border-radius:.3rem;background:#eee}
button{cursor:pointer;padding:.25rem .6rem;border:1px solid #bbb;border-radius:.3rem;background:#fff}
.ok{color:#0a7d2c}.warn{color:#b25000}.msg{padding:.5rem;background:#eef;border:1px solid #ccd;margin:.5rem 0}</style>
</head><body>
<h1>🥭 Tavola VIP — Ponte di comando</h1>
{% if msg %}<div class="msg">{{ msg }}</div>{% endif %}

<h2>Rimborsi da approvare ({{ rimborsi|length }})</h2>
{% if rimborsi %}<table><tr><th>ID</th><th>Tavolo</th><th>Ospite</th><th>Date</th><th>Azioni</th></tr>
{% for p in rimborsi %}<tr><td>{{ p.id }}</td><td>{{ p.candidato_url }}</td><td>{{ p.ospite_email }}</td>
<td>{{ p.check_in }} → {{ p.check_out }}</td><td>
<form method="post" action="{{ base }}/refund/{{ p.id }}/approve" style="display:inline">
<input type="hidden" name="csrf" value="{{ csrf }}"><button class="ok">Approva rimborso</button></form>
<form method="post" action="{{ base }}/refund/{{ p.id }}/reject" style="display:inline">
<input type="hidden" name="csrf" value="{{ csrf }}"><button class="warn">Rifiuta</button></form>
</td></tr>{% endfor %}</table>{% else %}<p>Nessun rimborso in attesa.</p>{% endif %}

<h2>Prenotazioni (vista calendario, per data) — {{ prenotazioni|length }}</h2>
<table><tr><th>ID</th><th>Tavolo</th><th>Ospite</th><th>Tel</th><th>Check-in</th><th>Check-out</th><th>Stato</th><th></th></tr>
{% for p in prenotazioni %}<tr><td>{{ p.id }}</td><td>{{ p.candidato_url }}</td><td>{{ p.ospite_email }}</td>
<td>{{ p.ospite_telefono }}</td><td>{{ p.check_in }}</td><td>{{ p.check_out }}</td>
<td><span class="s">{{ p.stato }}</span></td><td>
{% if p.stato == 'in_attesa_pagamento' %}
<form method="post" action="{{ base }}/reservation/{{ p.id }}/cancel" style="display:inline">
<input type="hidden" name="csrf" value="{{ csrf }}"><button class="warn">Annulla</button></form>{% endif %}
</td></tr>{% endfor %}</table>
</body></html>"""


def registra_pannello(target: Any, motore: Any, servizio: Any, *,
                      utente: Optional[str], password: Optional[str],
                      csrf_token: Optional[str] = None,
                      base: str = "/admin") -> None:
    """Registra il pannello su un Blueprint/app Flask. Senza utente+password il
    pannello e' DISABILITATO (ogni rotta -> 503). Il token CSRF, se non fornito,
    e' generato casualmente per-processo."""
    from flask import request, render_template_string, redirect, Response

    abilitato = bool(utente and password)
    token = csrf_token or secrets.token_hex(16)

    def _disabilitato() -> Optional[Response]:
        if not abilitato:
            return Response("Pannello admin disabilitato (configura le credenziali).",
                            status=503)
        return None

    def _auth_ok() -> bool:
        a = request.authorization
        if a is None:
            return False
        u = hmac.compare_digest(a.username or "", utente)
        p = hmac.compare_digest(a.password or "", password)
        return u and p

    def _nega_auth() -> Response:
        return Response("Autenticazione richiesta", status=401, headers={
            "WWW-Authenticate": 'Basic realm="Tavola VIP Admin"'})

    def _csrf_ok() -> bool:
        return hmac.compare_digest(request.form.get("csrf", ""), token)

    def _intestazioni(resp: Response) -> Response:
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
        return resp

    def _azione(esegui) -> Response:
        giu = _disabilitato()
        if giu is not None:
            return giu
        if not _auth_ok():
            return _nega_auth()
        if not _csrf_ok():
            return _intestazioni(Response("CSRF non valido", status=403))
        esito = esegui()
        return _intestazioni(redirect(f"{base}?msg={esito}", code=303))

    @target.route(base, methods=["GET"], endpoint="admin_dashboard")
    def _dashboard():
        giu = _disabilitato()
        if giu is not None:
            return giu
        if not _auth_ok():
            return _nega_auth()
        html = render_template_string(
            _TEMPLATE, base=base, csrf=token,
            msg=request.args.get("msg", ""),
            rimborsi=motore.elenco(stato="rimborso_richiesto"),
            prenotazioni=motore.elenco())
        return _intestazioni(Response(html, mimetype="text/html"))

    @target.route(f"{base}/refund/<int:pid>/approve", methods=["POST"],
                  endpoint="admin_refund_approve")
    def _approve(pid: int):
        return _azione(lambda: servizio.approva_rimborso(pid).esito)

    @target.route(f"{base}/refund/<int:pid>/reject", methods=["POST"],
                  endpoint="admin_refund_reject")
    def _reject(pid: int):
        return _azione(lambda: ("rifiutato" if servizio.rifiuta_rimborso(pid)
                                else "stato_non_valido"))

    @target.route(f"{base}/reservation/<int:pid>/cancel", methods=["POST"],
                  endpoint="admin_cancel")
    def _cancel(pid: int):
        return _azione(lambda: ("annullata" if motore.annulla(pid)
                                else "non_annullabile"))


def crea_app_admin(motore: Any, servizio: Any, *, utente: Optional[str],
                   password: Optional[str], csrf_token: Optional[str] = None) -> Any:
    """App Flask standalone del solo pannello admin (utile per test e deploy isolato)."""
    from flask import Flask
    app = Flask("tavola_vip_admin")
    registra_pannello(app, motore, servizio, utente=utente, password=password,
                      csrf_token=csrf_token)
    return app


def crea_app_admin_da_env() -> Any:
    """Bootstrap del pannello da env: ADMIN_PANEL_USER / ADMIN_PANEL_PASSWORD /
    ADMIN_PANEL_CSRF, DB_PATH (condiviso col servizio booking). Senza credenziali
    -> pannello disabilitato (503)."""
    import os
    import sqlite3
    from fase34_prenotazioni import MotorePrenotazioni
    from fase35_pagamenti import crea_provider_pagamenti, ServizioPagamenti

    db_path = os.environ.get("DB_PATH", "data/tavolavip.db")
    motore = MotorePrenotazioni(lambda: sqlite3.connect(db_path, timeout=30))
    motore.inizializza_schema()
    servizio = ServizioPagamenti(motore, crea_provider_pagamenti())
    return crea_app_admin(motore, servizio,
                          utente=os.environ.get("ADMIN_PANEL_USER"),
                          password=os.environ.get("ADMIN_PANEL_PASSWORD"),
                          csrf_token=os.environ.get("ADMIN_PANEL_CSRF"))
