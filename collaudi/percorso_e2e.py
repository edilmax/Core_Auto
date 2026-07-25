"""
CAMMINO E2E COMPLETO — un bot percorre TUTTO il viaggio host e ospite come un utente vero, e a OGNI
passo verifica non solo che "risponda" ma che succeda la COSA GIUSTA (l'effetto). Segnala ogni punto
dove un utente si bloccherebbe o dove l'effetto atteso non avviene.

VIAGGIO HOST:   registra -> login -> pubblica -> apri le date -> l'annuncio e' cercabile
VIAGGIO OSPITE: cerca -> preventivo (prezzo esatto) -> prenota -> le DATE SI BLOCCANO ->
                voucher PRE-pagamento (niente PIN) -> paga (webhook) -> email conferma ->
                voucher POST-pagamento (PIN + controversia) -> l'host vede l'incasso
ECCEZIONE:      cancella -> rimborso -> le DATE SI RIAPRONO (una nuova prenotazione riprende)

Deterministico, in-house (Stripe finto, email finta). Un solo comando:  python collaudi/percorso_e2e.py
"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, pagina_voucher_html
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

BLOCCHI = []
_PASSI = [0]


def passo(nome, ok, dettaglio=""):
    _PASSI[0] += 1
    if ok:
        print("  [OK    ] %2d. %s" % (_PASSI[0], nome))
    else:
        print("  [BLOCCO] %2d. %s  -> %s" % (_PASSI[0], nome, dettaglio))
        BLOCCHI.append("%s: %s" % (nome, dettaglio))


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://x/" + secrets.token_hex(5), "id": "cs_" + secrets.token_hex(5)}


class _Posta:
    def __init__(self):
        self.inviate = []

    def invia(self, dest, oggetto, html):
        self.inviate.append((dest, oggetto, html))
        return True

    def ha(self, filtro):
        return any(filtro in o for _, o, _h in self.inviate)


def main():
    _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)
    d = tempfile.mkdtemp()
    os.environ["UPLOAD_DIR"] = d + "/uploads"
    sis = crea_sistema(ConfigCasaVIP(
        abilitato=True, segreto_hmac=b"E" * 32, con_registrazione_host=True,
        db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
        db_accettazioni=d + "/a.db", db_pendenti=d + "/p.db", db_messaggi=d + "/m.db",
        db_garanzia=d + "/g.db", db_recensioni=d + "/rec.db",
        commissione_bps=1500, psp_bps=300, stripe_secret_key="sk",
        stripe_webhook_secret="whsec_x", stripe_success_url="https://x/ok",
        stripe_cancel_url="https://x/no"))
    posta = _Posta()
    sis.email_provider = posta
    r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")

    def g(m, p, b=None, h=None):
        return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    print("=" * 78)
    print("CAMMINO E2E — viaggio HOST + OSPITE + eccezioni, effetto verificato a ogni passo")
    print("=" * 78)
    print("-- VIAGGIO HOST --")

    # H1 registrazione (dal gate pubblico)
    s, c = g("POST", "/api/host/registrazione", {
        "email": "host@e2e.it", "password": "password1", "accetta_termini": True,
        "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
        "versione": CONTRATTO_HOST_VERSIONE})
    tok = c.get("token") if isinstance(c, dict) else None
    passo("Registrazione host -> account creato", s == 201 and bool(tok), "status %s" % s)
    tk = {"X-Host-Token": tok or ""}

    # H2 login
    s, cl = g("POST", "/api/host/login", {"email": "host@e2e.it", "password": "password1"})
    passo("Login host -> token", s == 200 and isinstance(cl, dict) and bool(cl.get("token")), "status %s" % s)

    # H3 pubblica
    s, _p = g("POST", "/api/host/pubblica", {
        "slug": "casa-e2e", "titolo": "Attico E2E", "citta": "Roma",
        "prezzo_notte_cents": 20000, "capacita": 4}, tk)
    passo("Pubblica alloggio", s in (200, 201), "status %s (%s)" % (s, _p))

    # H4 apri disponibilita (1 sola unita -> il blocco date sara' netto)
    oggi = datetime.date.today()
    ci = (oggi + datetime.timedelta(days=5)).isoformat()
    co = (oggi + datetime.timedelta(days=7)).isoformat()
    s, _d = g("POST", "/api/host/disponibilita_range", {
        "alloggio_id": "casa-e2e", "da": oggi.isoformat(),
        "a": (oggi + datetime.timedelta(days=20)).isoformat(),
        "unita_totali": 1, "prezzo_netto_cents": 20000}, tk)
    passo("Apri le date (disponibilita)", s in (200, 201), "status %s" % s)

    # H5 l'annuncio e' cercabile
    s, cat = g("GET", "/api/catalogo")
    ris = cat.get("risultati", cat) if isinstance(cat, dict) else cat
    trovato = isinstance(ris, list) and any(
        (x.get("slug") or x.get("id")) == "casa-e2e" for x in ris)
    passo("L'annuncio compare nella ricerca pubblica", trovato, "catalogo=%s" % (ris if not trovato else "ok"))

    print("-- VIAGGIO OSPITE --")

    # G1 preventivo (prezzo esatto: 2 notti x 20000)
    s, q = g("POST", "/api/concierge/quote", {
        "alloggio_id": "casa-e2e", "check_in": ci, "check_out": co, "party": 2})
    listino = q.get("prezzo_listino_cents") if isinstance(q, dict) else None
    passo("Preventivo -> prezzo esatto (2 notti = 40000)", s == 200 and listino == 40000,
          "status %s listino %s" % (s, listino))
    qtok = q.get("quote_token") if isinstance(q, dict) else None

    # G2 prenota
    s, b = g("POST", "/api/concierge/book", {"quote_token": qtok, "email": "osp@e2e.it", "lang": "it"})
    rif = b.get("riferimento") if isinstance(b, dict) else None
    vt = b.get("voucher_token") if isinstance(b, dict) else None
    passo("Prenota -> riferimento + voucher", s == 201 and bool(rif) and bool(vt), "status %s" % s)

    # G3 EFFETTO: le date si BLOCCANO (seconda prenotazione stesse date, 1 unita -> deve fallire)
    s2, q2 = g("POST", "/api/concierge/quote", {
        "alloggio_id": "casa-e2e", "check_in": ci, "check_out": co, "party": 2})
    b2 = None
    if s2 == 200 and isinstance(q2, dict) and q2.get("quote_token"):
        s2b, b2r = g("POST", "/api/concierge/book",
                     {"quote_token": q2["quote_token"], "email": "altro@e2e.it"})
        b2 = s2b
    passo("Le date si BLOCCANO (2a prenotazione stesse date rifiutata)", b2 not in (201,),
          "seconda prenotazione status %s" % b2)

    # G4 voucher PRE-pagamento: niente PIN reale, invito a pagare
    pin = sis.firma.pin_checkin(rif) if rif else "____"
    pag_pre = pagina_voucher_html(sis, vt, "it") or ""
    passo("Voucher PRE-pagamento: NIENTE PIN, invito a pagare",
          pin not in pag_pre and "Completa il pagamento" in pag_pre, "pin visibile o CTA assente")

    # G5 paga (webhook Stripe) -> email conferma
    pl = json.dumps({"type": "checkout.session.completed",
                     "data": {"object": {"metadata": {"riferimento": rif}}}})
    s, _w = g("POST", "/api/payments/webhook", pl if isinstance(pl, str) else None,
              {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})
    # (il body del webhook va passato grezzo, non ri-serializzato)
    s, _w = r.gestisci("POST", "/api/payments/webhook", {}, pl,
                       {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})
    passo("Paga (webhook Stripe) -> confermato", s in (200, 409), "status %s" % s)
    passo("Email di conferma pagamento parte all'ospite", posta.ha("Pagamento ricevuto"),
          "nessuna email 'Pagamento ricevuto'")

    # G6 voucher POST-pagamento: PIN + controversia sbloccati
    pag_post = pagina_voucher_html(sis, vt, "it") or ""
    passo("Voucher POST-pagamento: PIN + controversia sbloccati",
          pin in pag_post and "/api/garanzia/" in pag_post, "pin o controversia assenti")

    # G7 l'host VEDE l'incasso (payout dashboard)
    s, pay = g("GET", "/api/host/payout", None, tk)
    testo_pay = json.dumps(pay) if isinstance(pay, (dict, list)) else str(pay)
    passo("L'host vede l'incasso in maturazione", s == 200 and ("cents" in testo_pay or "maturato" in testo_pay
          or "valuta" in testo_pay), "status %s" % s)

    print("-- ECCEZIONE: cancellazione --")

    # E1 cancella -> le date si RIAPRONO
    s, canc = g("POST", "/api/concierge/cancella", {"voucher_token": vt})
    stato_c = canc.get("stato") if isinstance(canc, dict) else None
    passo("Cancellazione prenotazione", s == 200 and stato_c in ("cancellata", "rimborsata"),
          "status %s stato %s" % (s, stato_c))

    s3, q3 = g("POST", "/api/concierge/quote", {
        "alloggio_id": "casa-e2e", "check_in": ci, "check_out": co, "party": 2})
    b3 = None
    if s3 == 200 and isinstance(q3, dict) and q3.get("quote_token"):
        s3b, _b3 = g("POST", "/api/concierge/book",
                     {"quote_token": q3["quote_token"], "email": "nuovo@e2e.it"})
        b3 = s3b
    passo("Le date si RIAPRONO (nuova prenotazione riprende)", b3 == 201,
          "nuova prenotazione status %s" % b3)

    shutil.rmtree(d, ignore_errors=True)
    print("-" * 78)
    if BLOCCHI:
        print("PUNTI DI BLOCCO NEL VIAGGIO: %d" % len(BLOCCHI))
        for x in BLOCCHI:
            print("   [X] " + x)
    else:
        print("VIAGGIO COMPLETO: 0 blocchi — host e ospite arrivano in fondo, ogni effetto avviene.")
    print("=" * 78)
    sys.exit(1 if BLOCCHI else 0)


if __name__ == "__main__":
    main()
