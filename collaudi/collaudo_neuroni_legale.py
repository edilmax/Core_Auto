"""COLLAUDO A NEURONI del compartimento LEGALE-FISCALE (2026-07-21) — 0 ERRORI.

Percorre ogni regola (neurone), ogni collegamento (sotto-neurone) e ogni caso terminale
(sotto-sotto-neurone) di: consensi · legame identita' · scaglioni · prove · costi tecnici ·
dossier. In-process sul sistema VERO. Stampa solo il verdetto.

NEURONI:
  A CONSENSI      - 3 spunte obbligatorie, rifiuto a monte, 2 prove firmate
  B IDENTITA'     - legame prima/dopo la firma, verificabile, idempotente, manomissione
  C SCAGLIONI     - fonte unica: cio' che il Bunker MOSTRA == cio' che il motore ADDEBITA
  D COSTI         - tariffa tecnica coperta vs persa, etichetta fiscale
  E DOSSIER       - completo, certificato, non troncato, dichiara il vero
  F PERMESSI      - nessuna rotta legale/fiscale raggiungibile senza sessione Bunker
  G INTEGRITA'    - ogni manomissione (contratto/privacy/identita) viene smascherata
  H CONCORRENZA   - N host in parallelo: nessuna contaminazione, tutte le prove integre
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
from fase98_policy_commissione import (LANCIO_BPS_FASE1, LANCIO_BPS_REGIME,
                                       LANCIO_GIORNI_GRATIS)
from fase163_accettazioni import (CONTRATTO_HOST_VERSIONE, DOCUMENTO_HOST, DOCUMENTO_IDENTITA,
                                  DOCUMENTO_PRIVACY, doc_sha256, impronta_identita)

PW = "SuperPw@1"
AK = {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9", "User-Agent": "Firefox"}
PSP, PREZZO = 300, 20000
MAPPA = []


def N(neurone, regola, ok, det=""):
    MAPPA.append((neurone, regola, bool(ok), det))
    if not ok:
        print("   [KO] %s / %s  %s" % (neurone, regola, det), flush=True)


def build(d):
    os.environ["UPLOAD_DIR"] = d + "/u"
    sis = crea_sistema(ConfigCasaVIP(
        abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
        db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
        db_accettazioni=d + "/a.db", db_pendenti=d + "/p.db", db_messaggi=d + "/m.db",
        db_garanzia=d + "/g.db", db_finanza=d + "/f.db", db_kyc=d + "/k.db",
        commissione_bps=1000, psp_bps=PSP, promo_lancio_attiva=True, bunker_password=PW,
        stripe_secret_key="sk", stripe_webhook_secret="whsec_x",
        stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
    r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")

    def g(m, p, b=None, h=None, q=None):
        return r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or AK)

    return sis, r, g


def bunker(g):
    s, o = g("POST", "/api/bunker/login", {"codice": PW})
    d = dict(AK)
    d["X-Bunker-Session"] = o.get("sessione", "")
    return d


def crea_host(g, email, slug=None):
    s, c = g("POST", "/api/host/registrazione",
             {"email": email, "password": "password1", "accetta_termini": True,
              "accetta_clausole": True, "accetta_privacy": True,
              "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
    if s != 201:
        return None, None
    tk = {"X-Host-Token": c["token"]}
    if slug:
        oggi = datetime.date.today()
        g("POST", "/api/host/pubblica",
          {"slug": slug, "titolo": "Casa", "citta": "Roma",
           "prezzo_notte_cents": PREZZO, "capacita": 4}, tk)
        g("POST", "/api/host/disponibilita_range",
          {"alloggio_id": slug, "da": oggi.isoformat(),
           "a": (oggi + datetime.timedelta(days=25)).isoformat(),
           "unita_totali": 5, "prezzo_netto_cents": PREZZO}, tk)
    return c["host_id"], tk


def invecchia(d, hid, giorni):
    con = sqlite3.connect(d + "/r.db")
    try:
        con.execute("UPDATE host SET creato_ts=? WHERE host_id=?",
                    (int(time.time()) - giorni * 86400 - 60, hid))
        con.commit()
    finally:
        con.close()


# ═══════════════════════════ A · CONSENSI ═══════════════════════════
def neurone_A(sis, r, g):
    for k in ("accetta_termini", "accetta_clausole", "accetta_privacy"):
        body = {"email": "no_%s@n.local" % k, "password": "password1",
                "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True}
        body[k] = False
        s, o = g("POST", "/api/host/registrazione", body)
        N("A-consensi", "A1 senza %s -> rifiutato" % k,
          s == 422 and o.get("errore") == "consensi_mancanti" and "token" not in o,
          "s=%s" % s)
    hid, _tk = crea_host(g, "a@n.local")
    prove = sis.accettazioni.elenco(hid)
    N("A-consensi", "A2 due prove firmate", len(prove) == 2, "n=%d" % len(prove))
    N("A-consensi", "A3 tutte integre", all(p["integra"] for p in prove))
    N("A-consensi", "A4 vessatorie approvate",
      any(p["documento"] == DOCUMENTO_HOST and p["vessatorie"] for p in prove))
    N("A-consensi", "A5 privacy separata",
      any(p["documento"] == DOCUMENTO_PRIVACY for p in prove))
    N("A-consensi", "A6 IP e dispositivo catturati",
      all(p["ip"] == "203.0.113.9" and p["user_agent"] for p in prove))


# ═══════════════════════════ B · IDENTITÀ ═══════════════════════════
def neurone_B(sis, r, g):
    acc = sis.accettazioni
    # B1 host non verificato: nessuna promessa
    hid, _ = crea_host(g, "b1@n.local")
    N("B-identita", "B1 non verificato -> nessun legame",
      not acc.identita_legata(hid)["legata"])
    # B2 verifica DOPO la firma
    sis.kyc.registra_avvio(hid, "vs_B2")
    sis.kyc.conferma(hid, "verificato")
    r._lega_identita_se_possibile(acc, hid, ip="203.0.113.9", ua="Firefox")
    st = acc.identita_legata(hid)
    N("B-identita", "B2 verifica dopo la firma -> legame scritto",
      st["legata"] and st["integra"])
    # B3 impronta VERIFICABILE (ricalcolabile da chiunque)
    N("B-identita", "B3 impronta ricalcolabile",
      st["impronta_legame"] == impronta_identita("vs_B2", doc_sha256()) and st["verificabile"])
    # B4 idempotenza
    for _ in range(4):
        r._lega_identita_se_possibile(acc, hid)
    n = len([p for p in acc.elenco(hid) if p["documento"] == DOCUMENTO_IDENTITA])
    N("B-identita", "B4 idempotente (nessun doppione)", n == 1, "n=%d" % n)
    # B5 manomissione del riferimento -> firma non torna
    con = sqlite3.connect(sis.accettazioni and (r._sys.config.db_accettazioni))
    try:
        con.execute("UPDATE accettazioni SET riferimento='vs_FALSO' WHERE documento=? AND host_id=?",
                    (DOCUMENTO_IDENTITA, hid))
        con.commit()
    finally:
        con.close()
    riga = [p for p in acc.elenco(hid) if p["documento"] == DOCUMENTO_IDENTITA][0]
    N("B-identita", "B5 riferimento alterato -> smascherato", not riga["integra"])
    # B6 le altre due prove restano integre
    altre = [p for p in acc.elenco(hid) if p["documento"] != DOCUMENTO_IDENTITA]
    N("B-identita", "B6 contratto e privacy NON toccati", all(p["integra"] for p in altre))
    # B7 sessione vuota -> niente legame inventato
    hid2, _ = crea_host(g, "b7@n.local")
    out = acc.lega_identita(hid2, "", "verificato")
    N("B-identita", "B7 sessione vuota -> rifiutata", not out.get("ok"))


# ═══════════════════════════ C · SCAGLIONI ═══════════════════════════
def neurone_C(sis, r, g, d):
    hid, tk = crea_host(g, "c@n.local", "casaC")
    bk = bunker(g)
    for giorni, atteso in ((0, 0), (89, 0), (90, LANCIO_BPS_FASE1), (364, LANCIO_BPS_FASE1),
                           (365, LANCIO_BPS_REGIME), (900, LANCIO_BPS_REGIME)):
        invecchia(d, hid, giorni)
        s, v = g("GET", "/api/bunker/scaglioni_host", None, bk)
        riga = [x for x in v["host"] if x["host_id"] == hid][0]
        N("C-scaglioni", "C1 scaglione a %dgg" % giorni, riga["bps"] == atteso,
          "%d != %d" % (riga["bps"], atteso))
        oggi = datetime.date.today()
        s, q = g("POST", "/api/concierge/quote",
                 {"alloggio_id": "casaC",
                  "check_in": (oggi + datetime.timedelta(days=2)).isoformat(),
                  "check_out": (oggi + datetime.timedelta(days=3)).isoformat(), "party": 2})
        addebitato = q["commissione_cents"] * 10000 // PREZZO
        N("C-scaglioni", "C2 mostrato==addebitato a %dgg" % giorni,
          riga["bps"] == addebitato, "mostra %d addebita %d" % (riga["bps"], addebitato))
        if riga["giorni_al_prossimo"] is not None:
            atteso_data = (datetime.date.today()
                           + datetime.timedelta(days=riga["giorni_al_prossimo"])).isoformat()
            N("C-scaglioni", "C3 data scatto a %dgg" % giorni,
              riga["prossimo_scatto_il"] == atteso_data)
    N("C-scaglioni", "C4 diretto sempre 5%",
      all(x["bps_diretto"] == 500 for x in v["host"]))


# ═══════════════════════════ D · COSTI TECNICI ═══════════════════════════
def neurone_D(sis, r, g):
    hid, tk = crea_host(g, "d@n.local", "casaD")
    oggi = datetime.date.today()

    def prenota(giorni):
        s, q = g("POST", "/api/concierge/quote",
                 {"alloggio_id": "casaD",
                  "check_in": (oggi + datetime.timedelta(days=giorni)).isoformat(),
                  "check_out": (oggi + datetime.timedelta(days=giorni + 1)).isoformat(),
                  "party": 2})
        s, b = g("POST", "/api/concierge/book",
                 {"quote_token": q["quote_token"], "email": "o@n.local"})
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": b["riferimento"]}}}})
        r.gestisci("POST", "/api/payments/webhook", {}, pl,
                   {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})
        return b["riferimento"], b["voucher_token"]

    prenota(3)
    _rif, vt = prenota(9)
    g("POST", "/api/concierge/cancella", {"voucher_token": vt})
    s, c = g("GET", "/api/bunker/costi_tecnici", None, bunker(g))
    tec = PREZZO * PSP // 10000
    N("D-costi", "D1 coperta = 1 prenotazione", c["incassate"]["conteggio"] == 1)
    N("D-costi", "D2 persa = 1 rimborso", c["perdite"]["conteggio"] == 1)
    N("D-costi", "D3 importi esatti",
      c["incassate"]["cents"] == tec and c["perdite"]["cents"] == tec)
    N("D-costi", "D4 saldo netto", c["coperto_cents"] == 0)
    N("D-costi", "D5 etichetta fiscale esplicita",
      "IRRECUPERABILE" in c["perdite"]["voce_fiscale"] and "deducibile" in c["perdite"]["voce_fiscale"])


# ═══════════════════════════ E · DOSSIER ═══════════════════════════
def neurone_E(sis, r, g):
    hid, _ = crea_host(g, "e@n.local")
    sis.kyc.registra_avvio(hid, "vs_E")
    sis.kyc.conferma(hid, "verificato")
    r._lega_identita_se_possibile(sis.accettazioni, hid)
    bk = bunker(g)
    s, d1 = g("GET", "/api/bunker/export_legale", None, bk, {"formato": "csv"})
    csv = d1["contenuto"]
    N("E-dossier", "E1 CSV certificato", d1["certificato"] and "# FINE DOSSIER" in csv)
    for col in ("contratto_ip", "contratto_firma_hmac_sha256", "identita_sessione_stripe",
                "identita_impronta_legame", "scaglione", "privacy_versione"):
        N("E-dossier", "E2 colonna %s" % col, col in csv)
    N("E-dossier", "E3 prospetto tecnico con classificazione",
      "IRRECUPERABILE" in csv and "PROSPETTO TARIFFA TECNICA" in csv)
    N("E-dossier", "E4 dati reali presenti", "203.0.113.9" in csv and "vs_E" in csv
      and doc_sha256() in csv)
    s, d2 = g("GET", "/api/bunker/export_legale", None, bk, {"formato": "json"})
    dati = json.loads(d2["contenuto"].split("\n# FINE DOSSIER")[0])
    h = [x for x in dati["host"] if x["host_id"] == hid][0]
    N("E-dossier", "E5 JSON dichiara identita verificata",
      h["identita_verificata"] == "SI" and h["identita_legame_verificabile"] == "SI")
    N("E-dossier", "E6 nessuna prova manomessa dichiarata", dati["prove_manomesse"] == 0)


# ═══════════════════════════ F · PERMESSI ═══════════════════════════
def neurone_F(sis, r, g):
    for rotta in ("scaglioni_host", "prove_legali", "costi_tecnici", "export_legale"):
        s, o = g("GET", "/api/bunker/" + rotta, None, AK)
        N("F-permessi", "F1 %s chiuso senza Bunker" % rotta,
          s == 403 and o.get("errore") == "bunker_richiesto", "s=%s" % s)
    hid, _ = crea_host(g, "f@n.local")
    s, d = g("GET", "/api/admin/verifiche/dettaglio", None, AK, {"host_id": hid})
    campi = set()
    for p in d.get("contratto_prove", []):
        campi |= set(p.keys())
    N("F-permessi", "F2 Field cieco su IP/impronta/firma",
      not (campi & {"ip", "doc_sha256", "firma", "riferimento"}), "campi=%s" % sorted(campi))


# ═══════════════════════════ G · INTEGRITÀ ═══════════════════════════
def neurone_G(sis, r, g, d):
    hid, _ = crea_host(g, "g@n.local")
    sis.kyc.registra_avvio(hid, "vs_G")
    sis.kyc.conferma(hid, "verificato")
    r._lega_identita_se_possibile(sis.accettazioni, hid)
    for doc, campo, valore in ((DOCUMENTO_HOST, "ip", "'1.1.1.1'"),
                               (DOCUMENTO_PRIVACY, "versione", "'x'"),
                               (DOCUMENTO_IDENTITA, "riferimento", "'vs_x'")):
        con = sqlite3.connect(d + "/a.db")
        try:
            con.execute("UPDATE accettazioni SET %s=%s WHERE host_id=? AND documento=?"
                        % (campo, valore), (hid, doc))
            con.commit()
        finally:
            con.close()
        riga = [p for p in sis.accettazioni.elenco(hid) if p["documento"] == doc][0]
        N("G-integrita", "G1 manomissione %s smascherata" % doc, not riga["integra"])
    s, o = g("GET", "/api/bunker/prove_legali", None, bunker(g))
    N("G-integrita", "G2 il Bunker le conta", o["manomesse"] >= 3 and not o["integrita_ok"],
      "manomesse=%s" % o.get("manomesse"))


# ═══════════════════════════ H · CONCORRENZA ═══════════════════════════
def neurone_H(sis, r, g, n=40):
    def lavoro(i):
        hid, _ = crea_host(g, "h%03d@n.local" % i)
        if hid is None:
            return "no-host"
        if i % 2 == 0:
            sis.kyc.registra_avvio(hid, "vs_H%03d" % i)
            sis.kyc.conferma(hid, "verificato")
            r._lega_identita_se_possibile(sis.accettazioni, hid)
        prove = sis.accettazioni.elenco(hid)
        attese = 3 if i % 2 == 0 else 2
        if len(prove) != attese:
            return "prove-%d" % len(prove)
        if not all(p["integra"] for p in prove):
            return "non-integra"
        if i % 2 == 0:
            st = sis.accettazioni.identita_legata(hid)
            if st["session_ref"] != "vs_H%03d" % i:
                return "contaminazione"
        return "ok"

    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        esiti = list(ex.map(lavoro, range(n)))
    cattivi = [e for e in esiti if e != "ok"]
    N("H-concorrenza", "H1 %d host in parallelo, tutti coerenti" % n,
      not cattivi, "anomalie=%s" % cattivi[:5])


def main():
    giri = int(os.environ.get("GIRI", "3"))
    t0 = time.time()
    for giro in range(giri):
        d = tempfile.mkdtemp()
        try:
            sis, r, g = build(d)
            neurone_A(sis, r, g)
            neurone_B(sis, r, g)
            neurone_C(sis, r, g, d)
            neurone_D(sis, r, g)
            neurone_E(sis, r, g)
            neurone_F(sis, r, g)
            neurone_G(sis, r, g, d)
            neurone_H(sis, r, g)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        print("  giro %d/%d fatto" % (giro + 1, giri), flush=True)
    print("=" * 70)
    per = {}
    for neur, _reg, ok, _d in MAPPA:
        per.setdefault(neur, [0, 0])
        per[neur][0] += 1
        per[neur][1] += 1 if ok else 0
    for neur in sorted(per):
        tot, ok = per[neur]
        print("  %-16s %d/%d regole verdi" % (neur, ok, tot))
    err = [(n, reg, dd) for n, reg, ok, dd in MAPPA if not ok]
    print("-" * 70)
    print("COLLAUDO NEURONI LEGALE — %d regole × %d giri, %.1fs" % (len(MAPPA) // giri, giri,
                                                                    time.time() - t0))
    if not err:
        print("VERDETTO: 0 ERRORI — TUTTI I NEURONI VERDI")
    else:
        print("VERDETTO: %d ERRORI" % len(err))
        for n, reg, dd in err[:20]:
            print("   - %s / %s  %s" % (n, reg, dd))
    print("=" * 70)
    return 0 if not err else 1


if __name__ == "__main__":
    sys.exit(main())
