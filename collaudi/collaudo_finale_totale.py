"""COLLAUDO FINALE TOTALE — consensi + tariffe + catena soldi, multi-metodo.

Metodi indipendenti (se uno sbaglia, un altro lo becca):
  A1 CONCORRENZA CONSENSI - 240 registrazioni simultanee con combinazioni casuali delle 3
                            spunte: SOLO quelle complete creano un account (conteggio esatto).
  A2 PROVA COMPLETA       - ogni account creato ha ESATTAMENTE 2 prove integre (contratto con
                            vessatorie + privacy), con versione/impronta/IP/dispositivo/ora.
  A3 ANTI-MANOMISSIONE    - alterando righe a caso nel DB, `integra` diventa False SOLO per
                            quelle toccate (la firma non da' falsi positivi ne' falsi negativi).
  A4 PAYLOAD OSTILI       - 600 corpi malformati sulle spunte: mai 5xx, mai account senza prove.
  A5 RI-ACCETTAZIONE      - 12 ri-accettazioni simultanee: stato finale coerente, prove vecchie
                            conservate (append-only), nessuna riga corrotta.
  B1 TESTI == MOTORE      - ogni cifra che il motore applica DEVE comparire nei testi ufficiali
                            (README, termini, pannello host, contratto) e viceversa.
  C1 CATENA COMPLETA      - host a 0/90/365 giorni: registra(3 spunte)->pubblica->prenota->paga
                            ->payout, conti esatti al centesimo su ogni scaglione.
0 violazioni = macchina perfetta su tutto il compartimento nuovo.
"""
import concurrent.futures as cf
import datetime
import json
import os
import random
import re
import shutil
import sqlite3
import sys

try:  # Windows: console cp1252 non regge box-drawing/emoji -> uscita UTF-8 tollerante
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
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
from fase98_policy_commissione import (BPS_DIRETTO, LANCIO_BPS_FASE1, LANCIO_BPS_REGIME,
                                       LANCIO_GIORNI_GRATIS)
from fase163_accettazioni import (CONTRATTO_HOST_VERSIONE, DOCUMENTO_HOST, DOCUMENTO_PRIVACY,
                                  PRIVACY_VERSIONE, doc_sha256, privacy_sha256)

VIOL = {}
PSP = 300


def viol(k, n=1, det=""):
    VIOL[k] = VIOL.get(k, 0) + n
    if det:
        print("   [VIOLAZIONE] %s: %s" % (k, det), flush=True)


def costruisci(promo=True, bps=1000):
    d = tempfile.mkdtemp()
    os.environ["UPLOAD_DIR"] = d + "/u"
    sis = crea_sistema(ConfigCasaVIP(
        abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
        db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
        db_accettazioni=d + "/a.db", db_pendenti=d + "/p.db", db_messaggi=d + "/m.db",
        db_garanzia=d + "/g.db", db_recensioni=d + "/rec.db",
        commissione_bps=bps, psp_bps=PSP, promo_lancio_attiva=promo,
        stripe_secret_key="sk", stripe_webhook_secret="whsec_x",
        stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
    r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")
    return d, sis, r


def G(r, m, p, b=None, h=None):
    return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})


HDR = {"X-Forwarded-For": "203.0.113.9", "User-Agent": "Mozilla/prova"}


# ══════════════ A1+A2 CONCORRENZA CONSENSI + PROVA COMPLETA ══════════════
def a1_a2(n=240):
    print("A1/A2: %d registrazioni simultanee con spunte casuali" % n, flush=True)
    d, sis, r = costruisci()
    try:
        casi = []
        for i in range(n):
            t = random.random() < 0.75
            c = random.random() < 0.75
            p = random.random() < 0.75
            casi.append((i, t, c, p))
        attesi_ok = sum(1 for _i, t, c, p in casi if t and c and p)

        def registra(caso):
            i, t, c, p = caso
            s, o = G(r, "POST", "/api/host/registrazione",
                     {"email": "u%03d@t.local" % i, "password": "password1",
                      "accetta_termini": t, "accetta_clausole": c, "accetta_privacy": p}, HDR)
            if s >= 500:
                return ("5xx", None)
            if t and c and p:
                return ("ok", o.get("host_id")) if s == 201 else ("negato-a-torto", None)
            if s == 201:
                return ("creato-senza-consensi", o.get("host_id"))
            if s != 422 or o.get("errore") != "consensi_mancanti":
                return ("errore-sbagliato", None)
            return ("respinto", None)

        with cf.ThreadPoolExecutor(max_workers=24) as ex:
            esiti = list(ex.map(registra, casi))
        creati = [h for e, h in esiti if e == "ok" and h]
        for e, _h in esiti:
            if e in ("5xx", "negato-a-torto", "creato-senza-consensi", "errore-sbagliato"):
                viol("A1-" + e)
        if len(creati) != attesi_ok:
            viol("A1-conteggio", det="creati %d, attesi %d" % (len(creati), attesi_ok))
        # A2: ogni account creato ha 2 prove integre e complete
        for hid in creati:
            righe = sis.accettazioni.elenco(hid)
            if len(righe) != 2:
                viol("A2-prove-mancanti", det="host %s ha %d prove" % (hid, len(righe)))
                continue
            per = {x["documento"]: x for x in righe}
            c = per.get(DOCUMENTO_HOST)
            p = per.get(DOCUMENTO_PRIVACY)
            if not c or not p:
                viol("A2-documento-assente")
                continue
            if not (c["integra"] and p["integra"]):
                viol("A2-firma-non-valida")
            if not c["vessatorie"]:
                viol("A2-vessatorie-non-registrate")
            if c["versione"] != CONTRATTO_HOST_VERSIONE or c["doc_sha256"] != doc_sha256():
                viol("A2-versione-contratto")
            if p["versione"] != PRIVACY_VERSIONE or p["doc_sha256"] != privacy_sha256():
                viol("A2-versione-privacy")
            for x in (c, p):
                if x["ip"] != "203.0.113.9" or not x["user_agent"] or x["accettato_ts"] <= 0:
                    viol("A2-metadati", det="ip/ua/ts incompleti")
        print("   account creati: %d (attesi %d) | prove verificate: %d"
              % (len(creati), attesi_ok, len(creati) * 2), flush=True)
        return d, sis, r, creati
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise


# ══════════════════════ A3 ANTI-MANOMISSIONE ══════════════════════
def a3(d, sis, creati):
    print("A3: manomissione mirata di righe nel database", flush=True)
    if len(creati) < 6:
        viol("A3-setup", det="pochi host")
        return
    vittime = random.sample(creati, 5)
    con = sqlite3.connect(d + "/a.db")
    try:
        for hid in vittime:
            con.execute("UPDATE accettazioni SET ip='9.9.9.9' WHERE host_id=? AND documento=?",
                        (hid, DOCUMENTO_HOST))
        con.commit()
    finally:
        con.close()
    for hid in creati:
        for riga in sis.accettazioni.elenco(hid):
            manomessa = (hid in vittime and riga["documento"] == DOCUMENTO_HOST)
            if manomessa and riga["integra"]:
                viol("A3-manomissione-non-vista", det=hid)
            if (not manomessa) and (not riga["integra"]):
                viol("A3-falso-positivo", det=hid)
    print("   5 righe alterate: tutte rilevate, nessun falso allarme sulle altre", flush=True)


# ══════════════════════ A4 PAYLOAD OSTILI ══════════════════════
def a4(r, sis, giri=600):
    print("A4: %d corpi malformati sulle spunte" % giri, flush=True)
    veleni = [None, "", 0, 1, -1, "true", "True", "si", [], {}, [True], {"a": 1},
              float("nan"), 999999, "  ", True]
    prima = sis.accettazioni.conta()
    creati = 0
    for i in range(giri):
        body = {"email": "fz%04d@t.local" % i, "password": "password1",
                "accetta_termini": random.choice(veleni),
                "accetta_clausole": random.choice(veleni),
                "accetta_privacy": random.choice(veleni)}
        try:
            s, o = G(r, "POST", "/api/host/registrazione", body, HDR)
        except Exception:
            viol("A4-eccezione")
            continue
        if s >= 500:
            viol("A4-5xx")
        if s == 201:
            creati += 1
            # se e' nato, TUTTE e 3 dovevano essere vere e le prove devono esserci
            if not all(bool(body[k]) for k in
                       ("accetta_termini", "accetta_clausole", "accetta_privacy")):
                viol("A4-creato-senza-consensi", det=str({k: body[k] for k in body if k.startswith("accetta")}))
            elif len(sis.accettazioni.elenco(o.get("host_id", ""))) != 2:
                viol("A4-prove-mancanti")
    dopo = sis.accettazioni.conta()
    if dopo - prima != creati * 2:
        viol("A4-prove-sbilanciate", det="account %d, prove nuove %d" % (creati, dopo - prima))
    print("   account nati da payload ostili: %d (solo con 3 valori 'veri') | prove +%d"
          % (creati, dopo - prima), flush=True)


# ══════════════════════ A5 RI-ACCETTAZIONE CONCORRENTE ══════════════════════
def a5(t=12):
    print("A5: %d ri-accettazioni simultanee dello stesso host" % t, flush=True)
    d, sis, r = costruisci()
    try:
        s, o = G(r, "POST", "/api/host/registrazione",
                 {"email": "ra@t.local", "password": "password1", "accetta_termini": True,
                  "accetta_clausole": True, "accetta_privacy": True}, HDR)
        hid, tok = o["host_id"], {"X-Host-Token": o["token"], **HDR}
        # riporto le prove a una versione vecchia
        con = sqlite3.connect(d + "/a.db")
        try:
            con.execute("DELETE FROM accettazioni WHERE host_id=?", (hid,))
            con.commit()
        finally:
            con.close()
        sis.accettazioni.registra(hid, versione="2026-01-01", ip="1.1.1.1",
                                  user_agent="vecchio", vessatorie=True)
        s, st = r.gestisci("GET", "/api/host/contratto_stato", {}, None, tok)
        if not st.get("deve_riaccettare"):
            viol("A5-non-chiede-riaccettazione")

        def riaccetta(_):
            s, o = r.gestisci("POST", "/api/host/riaccetta", {},
                              json.dumps({"accetta_termini": True, "accetta_clausole": True,
                                          "accetta_privacy": True,
                                          "doc_sha256": doc_sha256()}), tok)
            return s

        with cf.ThreadPoolExecutor(max_workers=t) as ex:
            st_list = list(ex.map(riaccetta, range(t)))
        if any(x >= 500 for x in st_list):
            viol("A5-5xx", sum(1 for x in st_list if x >= 500))
        righe = sis.accettazioni.elenco(hid)
        if any(not x["integra"] for x in righe):
            viol("A5-riga-corrotta")
        versioni = {x["versione"] for x in righe}
        if "2026-01-01" not in versioni:
            viol("A5-prova-vecchia-persa")     # append-only: non si cancella il passato
        if CONTRATTO_HOST_VERSIONE not in versioni:
            viol("A5-nuova-non-scritta")
        s, st2 = r.gestisci("GET", "/api/host/contratto_stato", {}, None, tok)
        if st2.get("deve_riaccettare"):
            viol("A5-resta-non-conforme")
        print("   esiti: %s | prove totali: %d | storico conservato: %s"
              % (sorted(set(st_list)), len(righe), "2026-01-01" in versioni), flush=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ══════════════════════ B1 TESTI == MOTORE ══════════════════════
def b1():
    print("B1: le cifre del motore compaiono nei testi ufficiali", flush=True)
    fonti = {
        "README.md": open(os.path.join(REPO, "README.md"), encoding="utf-8").read(),
        "deploy/host.html": open(os.path.join(REPO, "deploy", "host.html"), encoding="utf-8").read(),
        "deploy/commissioni.html": open(os.path.join(REPO, "deploy", "commissioni.html"), encoding="utf-8").read(),
    }
    from fase163_accettazioni import CONTRATTO_HOST
    fonti["contratto (IT)"] = CONTRATTO_HOST["it"]
    fonti["contratto (EN)"] = CONTRATTO_HOST["en"]
    # I termini pubblici sono un GUSCIO servito dal motore (fase185, dopo il refactor i18n):
    # il file statico termini.html non contiene piu' testo fisso. La tariffa tecnica si legge
    # nel testo VERO generato dal motore, non nel guscio -> si controlla testo_termini().
    from fase185_testi_legali import testo_termini
    fonti["termini (motore IT)"] = testo_termini("it")
    fonti["termini (motore EN)"] = testo_termini("en")
    attesi = {"tariffa tecnica": "%d%%" % (PSP // 100),
              "commissione regime": "%d%%" % (LANCIO_BPS_REGIME // 100),
              "fase intermedia": "%d%%" % (LANCIO_BPS_FASE1 // 100),
              "canale diretto": "%d%%" % (BPS_DIRETTO // 100),
              "giorni gratis": str(LANCIO_GIORNI_GRATIS)}
    # dove OGNI cifra deve comparire (le pagine legali/tariffarie e il README)
    obbligatori = ["README.md", "deploy/host.html", "contratto (IT)", "contratto (EN)"]
    for nome in obbligatori:
        testo = fonti[nome]
        for etichetta, cifra in attesi.items():
            if cifra not in testo:
                viol("B1-cifra-assente", det="%s: manca %s (%s)" % (nome, cifra, etichetta))
    # il 3% deve esserci ANCHE nei termini pubblici (testo del motore, non il guscio) e nel tariffario
    for nome in ("termini (motore IT)", "termini (motore EN)", "deploy/commissioni.html"):
        if "3%" not in fonti[nome]:
            viol("B1-tecnica-assente", det=nome)
    print("   verificate %d cifre su %d fonti ufficiali"
          % (len(attesi), len(obbligatori) + 2), flush=True)


# ══════════════════════ C1 CATENA COMPLETA PER SCAGLIONE ══════════════════════
def c1():
    print("C1: catena registra->pubblica->prenota->paga->payout per scaglione", flush=True)
    d, sis, r = costruisci()
    try:
        oggi = datetime.date.today()
        for giorni, bps in ((0, 0), (LANCIO_GIORNI_GRATIS, LANCIO_BPS_FASE1), (400, LANCIO_BPS_REGIME)):
            s, o = G(r, "POST", "/api/host/registrazione",
                     {"email": "c%d@t.local" % giorni, "password": "password1",
                      "accetta_termini": True, "accetta_clausole": True,
                      "accetta_privacy": True}, HDR)
            if s != 201:
                viol("C1-registrazione", det="s=%s" % s)
                continue
            hid, tk = o["host_id"], {"X-Host-Token": o["token"]}
            con = sqlite3.connect(d + "/r.db")
            try:
                con.execute("UPDATE host SET creato_ts=? WHERE host_id=?",
                            (int(time.time()) - giorni * 86400 - 60, hid))
                con.commit()
            finally:
                con.close()
            slug = "casa%d" % giorni
            G(r, "POST", "/api/host/pubblica",
              {"slug": slug, "titolo": "Casa", "citta": "Roma",
               "prezzo_notte_cents": 20000, "capacita": 4}, tk)
            G(r, "POST", "/api/host/disponibilita_range",
              {"alloggio_id": slug, "da": oggi.isoformat(),
               "a": (oggi + datetime.timedelta(days=15)).isoformat(),
               "unita_totali": 3, "prezzo_netto_cents": 20000}, tk)
            s, q = G(r, "POST", "/api/concierge/quote",
                     {"alloggio_id": slug, "check_in": (oggi + datetime.timedelta(days=2)).isoformat(),
                      "check_out": (oggi + datetime.timedelta(days=3)).isoformat(), "party": 2})
            comm_attesa = 20000 * bps // 10000
            tec_attesa = 20000 * PSP // 10000
            if q["commissione_cents"] != comm_attesa:
                viol("C1-commissione", det="%dgg: %d != %d" % (giorni, q["commissione_cents"], comm_attesa))
            if q["costo_pagamento_cents"] != tec_attesa:
                viol("C1-tariffa-tecnica", det="%dgg" % giorni)
            netto = 20000 - comm_attesa - tec_attesa
            if q["netto_host_cents"] != netto:
                viol("C1-netto", det="%dgg: %d != %d" % (giorni, q["netto_host_cents"], netto))
            s, b = G(r, "POST", "/api/concierge/book",
                     {"quote_token": q["quote_token"], "email": "osp@t.local"})
            rif = b["riferimento"]
            pl = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"metadata": {"riferimento": rif}}}})
            r.gestisci("POST", "/api/payments/webhook", {}, pl,
                       {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})
            info = sis.payout.info(rif)
            if not info or int(info.get("minori", -1)) != netto:
                viol("C1-payout", det="%dgg: payout %s != %d" % (giorni, info and info.get("minori"), netto))
            if (sis.pagamenti_pendenti.info(rif) or {}).get("stato") != "pagato":
                viol("C1-stato")
            print("   %4dgg: commissione %5d | tecnica %4d | host incassa %6d | payout OK"
                  % (giorni, comm_attesa, tec_attesa, netto), flush=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    t0 = time.time()
    print("=" * 74, flush=True)
    d, sis, r, creati = a1_a2()
    try:
        a3(d, sis, creati)
        a4(r, sis)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    a5()
    b1()
    c1()
    print("=" * 74)
    print("COLLAUDO FINALE TOTALE - durata %.1fs" % (time.time() - t0))
    if not VIOL:
        print("VERDETTO: 0 VIOLAZIONI - TUTTO CONFERMATO")
    else:
        print("VERDETTO: VIOLAZIONI:")
        for k in sorted(VIOL):
            print("   - %s: %d" % (k, VIOL[k]))
    print("=" * 74)
    sys.exit(0 if not VIOL else 1)
