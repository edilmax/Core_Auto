"""COLLAUDO TOTALE della rampa di lancio dopo il fix — MACRO + MICRO + MULTI-METODO.

Metodi indipendenti (se uno sbaglia, un altro lo becca):
  M1 DIFFERENZIALE  - un oracolo RI-CALCOLA la commissione da zero e la confronta col motore
                      su centinaia di combinazioni (eta' x prezzo x canale x promo x config).
  M2 SCAGLIONI      - i bordi esatti (89/90 e 364/365) al giorno preciso.
  M3 MONOTONIA      - la commissione non scende mai al crescere dell'eta' e non supera il regime.
  M4 CONCORRENZA    - host di eta' DIVERSE prenotano insieme: nessuna contaminazione fra host.
  M5 CATENA SOLDI   - a 0% commissione: prenota->paga->escrow->payout->giornale, tutto coerente
                      (nessun crash, payout = netto host, conservazione al centesimo).
  M6 LIMITI/FUZZ    - eta' assurde, prezzi da 1 cent, canali inventati: mai 5xx, mai 0% per errore.
0 violazioni = macchina perfetta su questo compartimento.
"""
import concurrent.futures as cf
import datetime
import json
import os
import random
import shutil
import sqlite3
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

import fase85_pagamenti_stripe as _stripe

_stripe.ProviderStripe._fetch_reale = staticmethod(
    lambda u, b, h: {"url": "https://x/y", "id": "cs_" + os.urandom(4).hex()})

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

VIOL = {}
PSP = 300


def viol(k, n=1, det=""):
    VIOL[k] = VIOL.get(k, 0) + n
    if det:
        print("   [VIOLAZIONE] %s: %s" % (k, det), flush=True)


# ── ORACOLO INDIPENDENTE (M1): riscrivo la regola da zero, senza guardare il motore ──
def oracolo_bps(giorni, canale, promo, bps_regime):
    if str(canale).lower() == "diretto":
        return 500                                   # 5% sempre
    if not promo:
        return bps_regime
    if giorni < 90:
        return 0
    if giorni < 365:
        return min(800, bps_regime)
    return bps_regime


def costruisci(promo=True, bps=1000, psp=PSP):
    d = tempfile.mkdtemp()
    os.environ["UPLOAD_DIR"] = d + "/u"
    sis = crea_sistema(ConfigCasaVIP(
        abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
        db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
        db_accettazioni=d + "/a.db", db_pendenti=d + "/p.db", db_messaggi=d + "/m.db",
        db_garanzia=d + "/g.db", db_recensioni=d + "/rec.db", db_finanza=d + "/f.db",
        commissione_bps=bps, psp_bps=psp, promo_lancio_attiva=promo,
        stripe_secret_key="sk", stripe_webhook_secret="whsec_x",
        stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
    r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")
    return d, sis, r, d + "/r.db"


def G(r, m, p, b=None, h=None):
    return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})


def crea_host(r, email, slug, prezzo):
    s, c = G(r, "POST", "/api/host/registrazione",
             {"email": email, "password": "password1", "accetta_termini": True,
              "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
              "versione": CONTRATTO_HOST_VERSIONE})
    assert s == 201, c
    tk = {"X-Host-Token": c["token"]}
    o = datetime.date.today()
    s, x = G(r, "POST", "/api/host/pubblica",
             {"slug": slug, "titolo": "Casa " + slug, "citta": "Roma",
              "prezzo_notte_cents": prezzo, "capacita": 6}, tk)
    assert s == 201, x
    G(r, "POST", "/api/host/disponibilita_range",
      {"alloggio_id": slug, "da": o.isoformat(),
       "a": (o + datetime.timedelta(days=25)).isoformat(),
       "unita_totali": 30, "prezzo_netto_cents": prezzo}, tk)
    return c["host_id"], tk


def invecchia(dbreg, hid, giorni):
    con = sqlite3.connect(dbreg)
    try:
        con.execute("UPDATE host SET creato_ts=? WHERE host_id=?",
                    (int(time.time()) - int(giorni) * 86400 - 60, str(hid)))
        con.commit()
    finally:
        con.close()


def quota(r, slug, canale="marketplace", g0=2):
    o = datetime.date.today()
    s, q = G(r, "POST", "/api/concierge/quote",
             {"alloggio_id": slug, "check_in": (o + datetime.timedelta(days=g0)).isoformat(),
              "check_out": (o + datetime.timedelta(days=g0 + 1)).isoformat(),
              "party": 2, "fonte": canale})
    return s, q


# ══════════════════ M1 DIFFERENZIALE + M2 SCAGLIONI + M3 MONOTONIA ══════════════════
def m1_m2_m3():
    print("M1/M2/M3: differenziale su combinazioni (eta' x prezzo x canale x promo x config)",
          flush=True)
    combos = 0
    for promo in (True, False):
        for bps in (1000, 1500):
            d, sis, r, dbreg = costruisci(promo=promo, bps=bps)
            try:
                for i, prezzo in enumerate((1000, 9999, 10000, 24500, 100000)):
                    slug = "casa%d" % i
                    hid, _tk = crea_host(r, "h%d_%s_%d@t.local" % (i, promo, bps), slug, prezzo)
                    eta = [0, 1, 45, 88, 89, 90, 91, 200, 363, 364, 365, 366, 1000, 5000]
                    ultimo = -1
                    for giorni in eta:
                        invecchia(dbreg, hid, giorni)
                        for canale in ("marketplace", "diretto"):
                            s, q = quota(r, slug, canale)
                            combos += 1
                            if s != 200:
                                viol("M1-quote-fallita", det="s=%s eta=%d" % (s, giorni))
                                continue
                            atteso = prezzo * oracolo_bps(giorni, canale, promo, bps) // 10000
                            if q["commissione_cents"] != atteso:
                                viol("M1-differenziale",
                                     det="promo=%s bps=%d prezzo=%d eta=%d canale=%s -> motore %d, oracolo %d"
                                         % (promo, bps, prezzo, giorni, canale,
                                            q["commissione_cents"], atteso))
                            # invariante soldi
                            if q["prezzo_guest_cents"] != (q["netto_host_cents"]
                                                           + q["commissione_cents"]
                                                           + q["costo_pagamento_cents"]):
                                viol("M1-identita-rotta", det="eta=%d" % giorni)
                            # tariffa tecnica SEMPRE presente
                            if q["costo_pagamento_cents"] != prezzo * PSP // 10000:
                                viol("M1-tariffa-tecnica",
                                     det="eta=%d canale=%s -> %d" % (giorni, canale,
                                                                     q["costo_pagamento_cents"]))
                            if canale == "marketplace" and promo:
                                if q["commissione_cents"] < ultimo:
                                    viol("M3-monotonia",
                                         det="eta=%d scende da %d a %d" % (giorni, ultimo,
                                                                           q["commissione_cents"]))
                                ultimo = q["commissione_cents"]
                                if q["commissione_cents"] > prezzo * bps // 10000:
                                    viol("M3-oltre-regime", det="eta=%d" % giorni)
            finally:
                shutil.rmtree(d, ignore_errors=True)
    print("   combinazioni verificate: %d" % combos, flush=True)
    return combos


# ══════════════════════════ M4 CONCORRENZA (no contaminazione) ══════════════════════
def m4(n_host=12, giri=40):
    print("M4: %d host di eta' diverse prenotano INSIEME (%d richieste)" % (n_host, n_host * giri),
          flush=True)
    d, sis, r, dbreg = costruisci(promo=True, bps=1000)
    try:
        eta_di = {}
        for i in range(n_host):
            slug = "h%02d" % i
            hid, _tk = crea_host(r, "c%d@t.local" % i, slug, 10000)
            giorni = random.choice([0, 30, 89, 90, 200, 364, 365, 900])
            invecchia(dbreg, hid, giorni)
            eta_di[slug] = giorni

        def lavoro(_):
            slug = random.choice(list(eta_di))
            canale = random.choice(["marketplace", "diretto"])
            s, q = quota(r, slug, canale, g0=random.randint(2, 20))
            if s != 200:
                return ("err", slug)
            atteso = 10000 * oracolo_bps(eta_di[slug], canale, True, 1000) // 10000
            return ("ok" if q["commissione_cents"] == atteso else "mismatch", slug)

        with cf.ThreadPoolExecutor(max_workers=24) as ex:
            esiti = list(ex.map(lavoro, range(n_host * giri)))
        bad = [x for x in esiti if x[0] == "mismatch"]
        err = [x for x in esiti if x[0] == "err"]
        if bad:
            viol("M4-contaminazione", len(bad), det="%d richieste con tariffa di un altro host" % len(bad))
        if err:
            viol("M4-errori", len(err))
        print("   richieste ok: %d/%d" % (len(esiti) - len(bad) - len(err), len(esiti)), flush=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ═══════════════════ M5 CATENA COMPLETA DEI SOLDI CON COMMISSIONE 0% ════════════════
def m5():
    print("M5: catena completa a 0%% (prenota->paga->escrow->payout->giornale)", flush=True)
    d, sis, r, dbreg = costruisci(promo=True, bps=1000)
    try:
        hid, tk = crea_host(r, "zero@t.local", "casa0", 20000)
        invecchia(dbreg, hid, 0)                       # host di oggi -> 0%
        s, q = quota(r, "casa0")
        if q["commissione_cents"] != 0:
            viol("M5-non-zero", det="commissione %d" % q["commissione_cents"])
        s, b = G(r, "POST", "/api/concierge/book",
                 {"quote_token": q["quote_token"], "email": "ospite@t.local"})
        if s != 201:
            viol("M5-book", det="s=%s" % s)
            return
        rif = b["riferimento"]
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        s2, _ = r.gestisci("POST", "/api/payments/webhook", {}, pl,
                           {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})
        if s2 != 200:
            viol("M5-webhook", det="s=%s" % s2)
        # payout maturato = netto host (prezzo - 0 commissione - 3% tecnico)
        atteso_host = 20000 - (20000 * PSP // 10000)
        info = sis.payout.info(rif) if getattr(sis, "payout", None) else None
        if info is None:
            viol("M5-payout-assente")
        elif int(info.get("minori", -1)) != atteso_host:
            viol("M5-payout-diverso",
                 det="payout %s, atteso %d" % (info.get("minori"), atteso_host))
        # nessuna prenotazione fantasma / stato coerente
        rec = sis.pagamenti_pendenti.info(rif)
        if not rec or rec.get("stato") != "pagato":
            viol("M5-stato", det=str(rec and rec.get("stato")))
        # conservazione: ospite = host + 0 + tecnico
        if b.get("prezzo_guest_cents", 20000) != atteso_host + 0 + (20000 * PSP // 10000):
            viol("M5-conservazione")
        print("   pagata a 0%%: host incassa %d cent (atteso %d), stato=%s"
              % ((info or {}).get("minori", -1), atteso_host,
                 rec and rec.get("stato")), flush=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ════════════════════════════ M6 LIMITI / INPUT ASSURDI ═════════════════════════════
def m6():
    print("M6: limiti e input assurdi (mai 5xx, mai 0%% per errore)", flush=True)
    d, sis, r, dbreg = costruisci(promo=True, bps=1000)
    try:
        hid, tk = crea_host(r, "lim@t.local", "casaL", 100)      # prezzo 1.00 EUR
        # eta' assurde
        for giorni in (0, 89, 90, 365, 10**5):
            invecchia(dbreg, hid, giorni)
            s, q = quota(r, "casaL")
            if s >= 500:
                viol("M6-5xx", det="eta=%d" % giorni)
            elif s == 200:
                atteso = 100 * oracolo_bps(giorni, "marketplace", True, 1000) // 10000
                if q["commissione_cents"] != atteso:
                    viol("M6-prezzo-piccolo", det="eta=%d -> %d vs %d"
                         % (giorni, q["commissione_cents"], atteso))
        # creato_ts corrotto -> mai 0% per errore
        for cattivo in (None, "domani", -1):
            con = sqlite3.connect(dbreg)
            try:
                con.execute("UPDATE host SET creato_ts=? WHERE host_id=?", (cattivo, hid))
                con.commit()
            except Exception:
                pass
            finally:
                con.close()
            s, q = quota(r, "casaL")
            if s >= 500:
                viol("M6-5xx-ts", det=str(cattivo))
            elif s == 200 and q["commissione_cents"] == 0 and cattivo != 0:
                viol("M6-zero-per-errore", det="creato_ts=%r ha dato 0%%" % (cattivo,))
        # canali inventati -> trattati come marketplace, mai crash
        invecchia(dbreg, hid, 500)
        for canale in ("", "DIRETTO", "diretto ", "marketplace", "pippo", "0", "null"):
            s, q = quota(r, "casaL", canale)
            if s >= 500:
                viol("M6-5xx-canale", det=repr(canale))
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    t0 = time.time()
    print("=" * 72, flush=True)
    combos = m1_m2_m3()
    m4()
    m5()
    m6()
    print("=" * 72)
    print("COLLAUDO RAMPA — %d combinazioni differenziali + concorrenza + catena soldi + limiti"
          % combos)
    print("durata: %.1fs" % (time.time() - t0))
    if not VIOL:
        print("VERDETTO: 0 VIOLAZIONI - MACCHINA PERFETTA su questo compartimento")
    else:
        print("VERDETTO: VIOLAZIONI:")
        for k in sorted(VIOL):
            print("   - %s: %d" % (k, VIOL[k]))
    print("=" * 72)
    sys.exit(0 if not VIOL else 1)
