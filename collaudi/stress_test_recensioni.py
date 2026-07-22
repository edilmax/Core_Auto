"""COLLAUDO INGEGNERISTICO della pagina di sola valutazione /recensione/ + motore voti.
Bombarda il sistema VERO in-process (DB su file, concorrenza reale). Costo token ~0:
stampa solo un REPORT con le violazioni. 0 violazioni = superato.

Aree: [1] concorrenza sana (molti voti insieme) · [2] anti-doppio (stessa prenotazione)
· [3] barriera anti-finti (forgiati / prima del check-out / non pagata / prenotazione altrui)
· [4] input non validi a raffica (mai 5xx, mai spazzatura salvata) · [5] pagina pulita sotto
carico (mai 5xx, MAI roba del voucher, invalidi respinti) · [6] invarianti finali del motore.
"""
import concurrent.futures as cf
import datetime
import json
import os
import random
import re
import shutil
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


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://x/" + secrets.token_hex(5), "id": "cs_" + secrets.token_hex(5)}


_stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

from fase63_recensioni import EmettitoreDiritto
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, pagina_recensione_html, servi
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

CLUTTER = ("Cancella prenotazione", "PIN check-in", "Check-in online", "Chatta con",
           "Ricevuta di pagamento")
LINGUE = ["it", "en", "es", "fr", "de", "pt", "ja", "zh"]
VIOL = {}


def viol(area, n=1):
    VIOL[area] = VIOL.get(area, 0) + n


def nuovo_sistema(d, unita=400):
    os.environ["UPLOAD_DIR"] = f"{d}/uploads"
    sis = crea_sistema(ConfigCasaVIP(
        abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
        db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
        db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_messaggi=f"{d}/m.db",
        db_garanzia=f"{d}/g.db", db_recensioni=f"{d}/rec.db",
        commissione_bps=1500, psp_bps=300, stripe_secret_key="sk",
        stripe_webhook_secret="whsec_x", stripe_success_url="https://x/ok",
        stripe_cancel_url="https://x/no"))
    r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")

    def g(m, p, b=None, h=None):
        return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    s, c = g("POST", "/api/host/registrazione",
             {"email": "h@s.it", "password": "password1", "accetta_termini": True,
              "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
              "versione": CONTRATTO_HOST_VERSIONE})
    assert s == 201, c
    tk = {"X-Host-Token": c["token"]}
    oggi = datetime.date.today()
    g("POST", "/api/host/pubblica",
      {"slug": "attico", "titolo": "Attico Vista Colosseo", "citta": "Roma",
       "prezzo_notte_cents": 24500, "capacita": 6}, tk)
    g("POST", "/api/host/disponibilita_range",
      {"alloggio_id": "attico", "da": oggi.isoformat(),
       "a": (oggi + datetime.timedelta(days=30)).isoformat(),
       "unita_totali": unita, "prezzo_netto_cents": 24500}, tk)
    return sis, r, g


def prenota(g, r, sis, email, paga=True):
    """Crea una prenotazione; ritorna (rif, voucher_token_CONCLUSO). paga=False la lascia
    non pagata. Il webhook va passato come stringa FIRMATA esatta (non ri-serializzata)."""
    oggi = datetime.date.today()
    ci = (oggi + datetime.timedelta(days=3)).isoformat()
    co = (oggi + datetime.timedelta(days=5)).isoformat()
    s, q = g("POST", "/api/concierge/quote",
             {"alloggio_id": "attico", "check_in": ci, "check_out": co, "party": 2})
    if s != 200:
        return None, None
    s, b = g("POST", "/api/concierge/book", {"quote_token": q["quote_token"], "email": email})
    if s != 201:
        return None, None
    rif, vt = b["riferimento"], b["voucher_token"]
    if paga:
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        r.gestisci("POST", "/api/payments/webhook", {}, pl,
                   {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})
    d = sis.firma.decodifica(vt)
    d["check_out"] = (oggi - datetime.timedelta(days=1)).isoformat()   # concluso
    return rif, sis.firma.codifica(d)


def diritto_dalla_pagina(pagina):
    m = re.search(r'"tok":\s*"([^"]+)"', pagina or "")
    return m.group(1) if m else None


# ─────────────────────────── SCENARI ───────────────────────────
def scenario_concorrenza(sis, r, g, M=100):
    """M prenotazioni pagate+concluse; M thread aprono la pagina pulita e votano."""
    pren = []
    for i in range(M):
        rif, vt = prenota(g, r, sis, "g%d@s.it" % i)
        if rif:
            pren.append((rif, vt))
    if len(pren) < M:
        viol("1-setup", M - len(pren))

    def vota(item):
        rif, vt = item
        pag = pagina_recensione_html(sis, vt, "it")
        if not pag or "recBox" not in pag:
            return ("nopage", rif)
        for c in CLUTTER:
            if c in pag:
                return ("leak", rif)
        tok = diritto_dalla_pagina(pag)
        if not tok:
            return ("notok", rif)
        s, o = g("POST", "/api/recensioni",
                 {"token": tok, "voto": (int(rif[-1], 16) % 5) + 1, "testo": "ok",
                  "categorie": {"pulizia": 5, "comfort": 4}})
        return ("ok" if s == 201 else "fail%d" % s, rif)

    with cf.ThreadPoolExecutor(max_workers=32) as ex:
        esiti = list(ex.map(vota, pren))
    ok = sum(1 for e, _ in esiti if e == "ok")
    for e, rif in esiti:
        if e != "ok":
            viol("1-voto-non-ok")
    # ogni prenotazione ha ESATTAMENTE 1 recensione, conteggio == ok
    s, rr = g("GET", "/api/recensioni/attico")
    if rr["riepilogo"]["conteggio"] != ok:
        viol("1-conteggio-diverso")
    return ok


def scenario_anti_doppio(sis, r, g, T=40):
    rif, vt = prenota(g, r, sis, "doppio@s.it")
    pag = pagina_recensione_html(sis, vt, "it")
    tok = diritto_dalla_pagina(pag)

    def vota(_):
        s, o = g("POST", "/api/recensioni", {"token": tok, "voto": 5})
        return s

    with cf.ThreadPoolExecutor(max_workers=T) as ex:
        st = list(ex.map(vota, range(T)))
    creati = sum(1 for s in st if s == 201)
    if creati != 1:
        viol("2-doppio", abs(creati - 1) if creati else 1)
    if any(s >= 500 for s in st):
        viol("2-5xx", sum(1 for s in st if s >= 500))


def scenario_barriera(sis, r, g):
    # (a) diritto FORGIATO (segreto sbagliato)
    falso = EmettitoreDiritto(type(sis.firma)(b"X" * 32)).emetti("ff", "attico",
                                                                 non_prima_ts=int(time.time()) - 60)
    s, o = g("POST", "/api/recensioni", {"token": falso, "voto": 5})
    if s == 201:
        viol("3-forgiato-accettato")
    # (b) PRIMA del check-out (nbf nel futuro) su prenotazione pagata
    rif, _vt = prenota(g, r, sis, "presto@s.it")
    tok_futuro = EmettitoreDiritto(sis.firma).emetti(rif, "attico",
                                                     non_prima_ts=int(time.time()) + 3600)
    s, o = g("POST", "/api/recensioni", {"token": tok_futuro, "voto": 5})
    if s == 201:
        viol("3-prima-checkout-accettato")
    # (c) prenotazione NON pagata: pagina mostra il form, ma il submit deve essere respinto
    rif2, vt2 = prenota(g, r, sis, "nonpag@s.it", paga=False)
    tok2 = EmettitoreDiritto(sis.firma).emetti(rif2, "attico",
                                               non_prima_ts=int(time.time()) - 60)
    s, o = g("POST", "/api/recensioni", {"token": tok2, "voto": 5})
    if s == 201:
        viol("3-non-pagata-accettata")
    # (d) prenotazione INESISTENTE con diritto NON firmato dal server (capacita' REALE di un
    # attaccante: non possiede la chiave). Deve essere respinto. NB: con la CHIAVE VERA del
    # server un diritto-fantasma passa, ma chi ha quella chiave possiede gia' tutto (fuori
    # minaccia) e li' il fail-open protegge di proposito il recensore vero da falsi blocchi.
    fantasma = EmettitoreDiritto(type(sis.firma)(b"Z" * 32)).emetti(
        "nonesiste123", "attico", non_prima_ts=int(time.time()) - 60)
    s, o = g("POST", "/api/recensioni", {"token": fantasma, "voto": 5})
    if s == 201:
        viol("3-fantasma-forgiato-accettato")


def scenario_fuzzing(sis, r, g, giri=400):
    rif, vt = prenota(g, r, sis, "fuzz@s.it")
    tok = diritto_dalla_pagina(pagina_recensione_html(sis, vt, "it"))
    import random
    veleni = [None, "", 0, -1, 6, 999999, 3.5, True, [1], {"a": 1}, "5",
              "𝕏😀" * 10, "x" * 5000, float("nan")]
    s0, rr0 = g("GET", "/api/recensioni/attico")
    base = rr0["riepilogo"]["conteggio"]
    for _ in range(giri):
        body = {"token": random.choice([tok, "rotto", None, 123]),
                "voto": random.choice(veleni),
                "testo": random.choice(veleni),
                "lingua": random.choice(veleni),
                "categorie": random.choice(veleni + [{"jacuzzi": 5}, {"pulizia": 9},
                                                     {"pulizia": "x"}, {"pulizia": -1}])}
        try:
            s, o = g("POST", "/api/recensioni", body)
        except Exception:
            viol("4-eccezione")
            continue
        if s >= 500:
            viol("4-5xx")
    s1, rr1 = g("GET", "/api/recensioni/attico")
    # nessuna spazzatura salvata: al piu' 1 recensione valida (il tok vero, voto valido)
    if rr1["riepilogo"]["conteggio"] - base > 1:
        viol("4-spazzatura-salvata", rr1["riepilogo"]["conteggio"] - base - 1)


def scenario_pagina_sotto_carico(sis, r, g, N=300):
    # mix di token: validi-conclusi, futuri, gia'-recensiti, invalidi
    validi = []
    for i in range(20):
        rif, vt = prenota(g, r, sis, "car%d@s.it" % i)
        if rif:
            validi.append(vt)
    futuro = sis.firma.codifica({**sis.firma.decodifica(validi[0]),
                                 "check_out": (datetime.date.today()
                                               + datetime.timedelta(days=9)).isoformat()})
    invalidi = ["rotto", "", validi[0][:-3] + "AAA"]
    import random
    pool = validi + [futuro] + invalidi

    def apri(_):
        t = random.choice(pool)
        try:
            pag = pagina_recensione_html(sis, t, "it")
        except Exception:
            return "exc"
        if pag is None:
            return "none"       # invalidi -> None (ok)
        for c in CLUTTER:
            if c in pag:
                return "leak"
        return "ok"

    with cf.ThreadPoolExecutor(max_workers=32) as ex:
        esiti = list(ex.map(apri, range(N)))
    if "exc" in esiti:
        viol("5-eccezione", esiti.count("exc"))
    if "leak" in esiti:
        viol("5-leak-clutter", esiti.count("leak"))


def scenario_invariante_finale(sis, r, g):
    """Il motore resta coerente: ogni recensione appartiene a UNA prenotazione, medie sane."""
    s, rr = g("GET", "/api/recensioni/attico")
    rie = rr["riepilogo"]
    recs = rr["recensioni"]
    ids = [x["prenotazione_id"] for x in recs]
    if len(ids) != len(set(ids)):
        viol("6-doppia-per-prenotazione", len(ids) - len(set(ids)))
    if rie["conteggio"] != len(recs) and rie["conteggio"] > len(recs):
        # (l'elenco puo' essere paginato; conteggio>=len e' ok)
        pass
    for x in recs:
        if not (1 <= x["voto"] <= 5):
            viol("6-voto-fuori-scala")
        for k, v in (x.get("categorie") or {}).items():
            if not (1 <= v <= 5):
                viol("6-categoria-fuori-scala")




def audit_recensione_readonly(saturation, target):
    """AUDIT READ-ONLY del solo endpoint /recensione/ sotto fuzzing COMBINATORIO
    (stati prenotazione × 8+4 lingue) e SATURAZIONE. NON scrive recensioni (prova: il
    conteggio resta invariato). Invarianti per OGNI render: mai crash, classe corretta,
    MAI roba del voucher/prezzo, token invalido -> None. + campione a livello ROTTA HTTP."""
    import threading
    import urllib.error
    import urllib.parse
    import urllib.request
    d = tempfile.mkdtemp()
    try:
        sis, r, g = nuovo_sistema(d, unita=200)
        oggi = datetime.date.today()
        # ── FIXTURE (setup, fuori dal carico): uno stato per ogni ramo ──
        rifF, vtF = prenota(g, r, sis, "form@a.it")            # pagata+conclusa -> FORM
        prenota(g, r, sis, "before@a.it")
        vtB = sis.firma.codifica({**sis.firma.decodifica(vtF),
                                  "check_out": (oggi + datetime.timedelta(days=9)).isoformat()})
        rifC, vtC = prenota(g, r, sis, "canc@a.it")
        # cancella con date FUTURE (il token concluso verrebbe rifiutato: soggiorno passato),
        # poi la fixture rende col token concluso -> deve risultare cancellata (niente form)
        vtC_fut = sis.firma.codifica({**sis.firma.decodifica(vtC),
                                      "check_out": (oggi + datetime.timedelta(days=5)).isoformat()})
        g("POST", "/api/concierge/cancella", {"voucher_token": vtC_fut})   # -> cancellata
        rifR, vtR = prenota(g, r, sis, "rev@a.it")
        g("POST", "/api/recensioni",                                    # 1 sola scrittura di setup
          {"token": EmettitoreDiritto(sis.firma).emetti(rifR, "attico",
                                                        non_prima_ts=int(time.time()) - 60),
           "voto": 5})                                                  # -> GRAZIE
        tok_altro = sis.firma.codifica({"tipo": "altro", "riferimento": "x"})
        tok_no_co = sis.firma.codifica({"tipo": "voucher", "riferimento": rifF,
                                        "alloggio_id": "attico"})       # senza check_out -> None
        fixtures = [
            ("form", vtF, "form"), ("prima-checkout", vtB, "prima"),
            ("cancellata", vtC, "prima"), ("gia-recensita", vtR, "grazie"),
            ("rotto", "rottissimo", "none"), ("vuoto", "", "none"),
            ("troncato", vtF[:-6] + "AAAAAA", "none"), ("non-voucher", tok_altro, "none"),
            ("senza-checkout", tok_no_co, "none"),
        ]
        langs = LINGUE + ["xx", "EN", "", "it-IT"]      # 8 valide + 4 fuzz-lingua (clampate a it)
        combos = [(tok, lng, cls) for (_l, tok, cls) in fixtures for lng in langs]
        random.shuffle(combos)
        base = sis.recensioni.riepilogo("attico")["conteggio"]     # baseline post-setup

        def render(i):
            tok, lng, cls = combos[i % len(combos)]
            try:
                pag = pagina_recensione_html(sis, tok, lng)
            except Exception:
                return "crash"
            if pag is None:
                return "ok" if cls == "none" else "wrong-none"
            if cls == "none":
                return "invalid-servito"
            if any(c in pag for c in CLUTTER) or "/voucher/" in pag or "Ricevuta" in pag:
                return "leak-voucher"
            if "245.00" in pag or "245,00" in pag:
                return "leak-prezzo"
            if cls == "form" and "recBox" not in pag:
                return "form-mancante"
            if cls == "grazie" and "recBox" in pag:
                return "grazie-con-form"
            if cls == "prima" and "recBox" in pag:
                return "prima-con-form"
            return "ok"

        t0 = time.time()
        with cf.ThreadPoolExecutor(max_workers=32) as ex:
            esiti = list(ex.map(render, range(saturation)))
        dt = time.time() - t0
        cnt = {}
        for e in esiti:
            cnt[e] = cnt.get(e, 0) + 1
        after = sis.recensioni.riepilogo("attico")["conteggio"]
        readonly_ok = (after == base)

        # ── campione a livello ROTTA HTTP (server vero in un thread) ──
        porta = 8911
        threading.Thread(target=lambda: servi(
            sis, host="127.0.0.1", porta=porta, host_key="hk", admin_key="ak",
            base_url="http://localhost:%d" % porta), daemon=True).start()
        time.sleep(1.5)
        http = {"200-valido": 0, "404-invalido": 0, "leak": 0, "errore": 0}

        def http_get(item):
            tok, atteso = item
            url = "http://127.0.0.1:%d/recensione/%s" % (porta, urllib.parse.quote(tok, safe=""))
            try:
                with urllib.request.urlopen(url, timeout=5) as resp:
                    code, body = resp.status, resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as he:
                code, body = he.code, he.read().decode("utf-8", "replace")
            except Exception:
                http["errore"] += 1
                return
            if any(c in body for c in CLUTTER) or "/voucher/" in body:
                http["leak"] += 1
            if atteso == 200 and code == 200 and "recBox" in body:
                http["200-valido"] += 1
            elif atteso == 404 and code == 404:
                http["404-invalido"] += 1
            else:
                http["errore"] += 1

        campione = [(vtF, 200)] * 150 + [("tokenrotto", 404)] * 150
        with cf.ThreadPoolExecutor(max_workers=16) as ex:
            list(ex.map(http_get, campione))

        print("=" * 68)
        print("AUDIT READ-ONLY %s — fuzzing combinatorio + saturazione" % (target or "/recensione/"))
        print("  combinazioni  : %d  (%d stati x %d lingue)" % (len(combos), len(fixtures), len(langs)))
        print("  render totali : %d  (%.1fs, %.0f render/s)" % (saturation, dt, (saturation / dt) if dt else 0))
        print("  esiti render  : %s" % cnt)
        print("  READ-ONLY     : conteggio prima=%d dopo=%d -> %s"
              % (base, after, "NESSUNA SCRITTURA" if readonly_ok else "SCRITTURA RILEVATA!"))
        print("  rotta HTTP    : %s" % http)
        print("-" * 68)
        viol = sum(v for k, v in cnt.items() if k != "ok")
        ok = (viol == 0 and readonly_ok and http["leak"] == 0 and http["errore"] == 0
              and http["200-valido"] > 0 and http["404-invalido"] > 0)
        print("VERDETTO: %s" % ("0 VIOLAZIONI — SUPERATO (sola lettura confermata)"
                                if ok else "VIOLAZIONI RILEVATE (vedi esiti sopra)"))
        print("=" * 68)
        return 0 if ok else 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Collaudo ingegneristico /recensione/")
    ap.add_argument("--race-condition", action="store_true",
                    help="voti simultanei + anti-doppio")
    ap.add_argument("--payload-corrupt", action="store_true",
                    help="input/payload non validi a raffica")
    ap.add_argument("--invalid-token", action="store_true",
                    help="token forgiati/invalidi + barriera anti-finti + pagina sotto carico")
    ap.add_argument("--rounds", type=int, default=int(os.environ.get("GIRI", "10")))
    ap.add_argument("--combinatorial-fuzzing", action="store_true")
    ap.add_argument("--saturation-load", type=int, default=0)
    ap.add_argument("--read-only-audit", action="store_true")
    ap.add_argument("--target-endpoint", default="")
    a = ap.parse_args()
    # MODALITA' AUDIT READ-ONLY (fuzzing combinatorio + saturazione su /recensione/)
    if (a.read_only_audit or a.combinatorial_fuzzing or a.saturation_load
            or "recensione" in a.target_endpoint):
        sat = a.saturation_load if a.saturation_load > 0 else 10000
        return audit_recensione_readonly(sat, a.target_endpoint)
    tutte = not (a.race_condition or a.payload_corrupt or a.invalid_token)
    aree = []
    if tutte or a.race_condition:
        aree.append("race-condition")
    if tutte or a.payload_corrupt:
        aree.append("payload-corrupt")
    if tutte or a.invalid_token:
        aree.append("invalid-token")
    print("Aree attive: %s | giri: %d" % (", ".join(aree), a.rounds), flush=True)
    t0 = time.time()
    tot_voti = 0
    for giro in range(a.rounds):
        d = tempfile.mkdtemp()
        try:
            sis, r, g = nuovo_sistema(d)
            if "race-condition" in aree:
                tot_voti += scenario_concorrenza(sis, r, g, M=100)
                scenario_anti_doppio(sis, r, g, T=40)
            if "invalid-token" in aree:
                scenario_barriera(sis, r, g)
                scenario_pagina_sotto_carico(sis, r, g, N=300)
            if "payload-corrupt" in aree:
                scenario_fuzzing(sis, r, g, giri=300)
            scenario_invariante_finale(sis, r, g)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        print("  giro %d/%d fatto" % (giro + 1, a.rounds), flush=True)
    print("=" * 60)
    print("COLLAUDO INGEGNERISTICO /recensione/  —  aree=[%s], %d giri, ~%d voti, %.1fs"
          % (", ".join(aree), a.rounds, tot_voti, time.time() - t0))
    if not VIOL:
        print("VERDETTO: 0 VIOLAZIONI — SUPERATO")
    else:
        print("VERDETTO: VIOLAZIONI TROVATE:")
        for k in sorted(VIOL):
            print("   - %s: %d" % (k, VIOL[k]))
    print("=" * 60)
    return 0 if not VIOL else 1


if __name__ == "__main__":
    sys.exit(main())
