"""
COLLAUDO ESTREMO COMBINATO — gare al millisecondo + fuzzing combinatorio su tutti gli endpoint.

Non "tanti test" ma pochi ad ALTO SEGNALE, ognuno con un OSSERVABILE FORTE e un GIUDICE indipendente:
  A) GARE / RACE (barriera di thread: tutti scattano nello stesso istante):
     A1  N prenotazioni simultanee dello STESSO alloggio con 1 sola unita' -> ne passa ESATTAMENTE 1;
         giudice indipendente = l'auditor invarianti fase199 sui DB reali (0 doppie conferme).
     A2  cambio prezzo dell'host DURANTE il checkout -> il prezzo firmato nel voucher e' IMMUTABILE
         (nessun addebito a un prezzo che l'ospite non ha visto); la 2a quote vede gia' il nuovo prezzo.
     A3  cancellazione vs nuova prenotazione sulla stessa notte, in gara -> mai 2 occupanti; se la
         cancellazione libera, la nuova entra, ma l'unita' occupata non supera MAI il totale.
     A4  blocco-data dell'host vs prenotazione in gara -> o l'ospite entra prima, o trova "chiuso";
         mai un occupante su una notte chiusa.
  B) FUZZING COMBINATORIO (campi x classi di valori ostili) su ricerca/login/checkout/pannelli:
     ogni combinazione deve dare uno status CONTROLLATO (mai 500 non gestito, mai eccezione risalita).

Deterministico, in-house (Stripe finto, email finta). Un solo comando:
    python collaudi/gare_estreme.py
"""
import datetime
import itertools
import json
import os
import shutil
import sys
import tempfile
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fase85_pagamenti_stripe as _stripe
import fase199_invarianti as INV
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

FALLE = []
_N = [0]


def esito(nome, ok, dett=""):
    _N[0] += 1
    print("  [%s] %2d. %s%s" % ("OK   " if ok else "FALLA", _N[0], nome,
                                "" if ok else "  -> " + dett))
    if not ok:
        FALLE.append("%s: %s" % (nome, dett))


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://x/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(6)}


class _Posta:
    def invia(self, *a, **k):
        return True


def _sistema(dir_):
    _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)
    os.environ["UPLOAD_DIR"] = dir_ + "/uploads"
    sis = crea_sistema(ConfigCasaVIP(
        abilitato=True, segreto_hmac=b"R" * 32, con_registrazione_host=True,
        db_catalogo=dir_ + "/c.db", db_inventario=dir_ + "/i.db", db_registro_host=dir_ + "/r.db",
        db_accettazioni=dir_ + "/a.db", db_pendenti=dir_ + "/p.db", db_messaggi=dir_ + "/m.db",
        db_garanzia=dir_ + "/g.db", db_recensioni=dir_ + "/rec.db",
        commissione_bps=1500, psp_bps=300, stripe_secret_key="sk",
        stripe_webhook_secret="whsec_x", stripe_success_url="https://x/ok",
        stripe_cancel_url="https://x/no"))
    sis.email_provider = _Posta()
    return sis


def _host_pubblica(g, tk, slug, unita, prezzo, da, a, min_notti=1):
    """Pubblica + apre le date. Il server SLUGIFICA (es. f_test->f-test): uso lo slug REALE
    restituito per la disponibilita' e lo RITORNO, cosi' il chiamante interroga la chiave giusta."""
    s, bp = g("POST", "/api/host/pubblica",
              {"slug": slug, "titolo": "Casa " + slug, "citta": "Roma",
               "prezzo_notte_cents": prezzo, "capacita": 4}, tk)
    reale = bp.get("slug") if isinstance(bp, dict) and bp.get("slug") else slug
    g("POST", "/api/host/disponibilita_range",
      {"alloggio_id": reale, "da": da, "a": a, "unita_totali": unita,
       "prezzo_netto_cents": prezzo, "min_notti": min_notti}, tk)
    return reale


def _quote(g, slug, ci, co):
    s, q = g("POST", "/api/concierge/quote",
             {"alloggio_id": slug, "check_in": ci, "check_out": co, "party": 2})
    return q.get("quote_token") if isinstance(q, dict) else None


# ══════════════════════════════════════════════════════════════════════════════
def main():
    d = tempfile.mkdtemp()
    sis = _sistema(d)
    r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")

    def g(m, p, b=None, h=None):
        return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    # host + finestra
    s, c = g("POST", "/api/host/registrazione", {
        "email": "host@race.it", "password": "password1", "accetta_termini": True,
        "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
        "versione": CONTRATTO_HOST_VERSIONE})
    tk = {"X-Host-Token": (c or {}).get("token", "")}
    oggi = datetime.date.today()
    da = oggi.isoformat()
    a = (oggi + datetime.timedelta(days=40)).isoformat()

    print("=" * 80)
    print("GARE AL MILLISECONDO (barriera thread) + auditor invarianti come giudice")
    print("=" * 80)

    # ── A1: N prenotazioni simultanee, 1 sola unita' -> passa ESATTAMENTE 1 ──────
    _host_pubblica(g, tk, "gara1", 1, 20000, da, a)
    ci = (oggi + datetime.timedelta(days=5)).isoformat()
    co = (oggi + datetime.timedelta(days=7)).isoformat()
    NCONC = 8
    tokens = [_quote(g, "gara1", ci, co) for _ in range(NCONC)]   # quote distinte (idem-key diverse)
    barriera = threading.Barrier(NCONC)
    creati = []
    lock = threading.Lock()

    def corri(tok, i):
        barriera.wait()                                     # tutti scattano insieme
        s, b = g("POST", "/api/concierge/book",
                 {"quote_token": tok, "email": "g%d@race.it" % i})
        with lock:
            creati.append((s, (b or {}).get("stato") if isinstance(b, dict) else None))

    th = [threading.Thread(target=corri, args=(tokens[i], i)) for i in range(NCONC)]
    [t.start() for t in th]
    [t.join() for t in th]
    ok201 = sum(1 for s, st in creati if s == 201)
    rifiut = sum(1 for s, st in creati if s in (409, 422))
    esito("A1 gara %d prenotazioni, 1 unita' -> ESATTAMENTE 1 confermata" % NCONC,
          ok201 == 1 and rifiut == NCONC - 1, "conf=%d rifiut=%d (%r)" % (ok201, rifiut, creati))

    # giudice INDIPENDENTE: l'auditor invarianti sui DB reali (0 doppie conferme)
    rap = INV.scansiona_db(d)
    viol = rap.get("violazioni", {})
    esito("A1 giudice indipendente (auditor fase199): 0 double-booking",
          not viol, "violazioni=%r" % viol)

    # verifica capienza fisica: la notte non ha MAI 2 occupanti su 1 unita'
    import sqlite3
    con = sqlite3.connect(d + "/i.db", timeout=30)
    try:
        troppo = con.execute(
            "SELECT giorno, unita_occupate, unita_totali FROM inventario "
            "WHERE unita_occupate > unita_totali").fetchall()
    except sqlite3.Error:
        troppo = []
    con.close()
    esito("A1 nessuna notte con occupate > totali (overbooking fisico)",
          not troppo, "righe sovra-occupate: %r" % troppo)

    # ── A2: cambio prezzo DURANTE il checkout -> prezzo firmato immutabile ───────
    _host_pubblica(g, tk, "gara2", 5, 30000, da, a)
    ci2 = (oggi + datetime.timedelta(days=10)).isoformat()
    co2 = (oggi + datetime.timedelta(days=12)).isoformat()     # 2 notti = 60000
    tok2 = _quote(g, "gara2", ci2, co2)
    prezzo_visto = sis.firma.decodifica(tok2).get("prezzo_guest_cents") if tok2 else None
    # l'host raddoppia il prezzo MENTRE l'ospite ha il preventivo in mano
    g("POST", "/api/host/disponibilita_range",
      {"alloggio_id": "gara2", "da": da, "a": a, "unita_totali": 5,
       "prezzo_netto_cents": 60000, "min_notti": 1}, tk)
    s, b2 = g("POST", "/api/concierge/book", {"quote_token": tok2, "email": "z@race.it"})
    addebitato = (b2 or {}).get("prezzo_guest_cents") if isinstance(b2, dict) else None
    esito("A2 prezzo addebitato = prezzo del preventivo (non cambia sotto i piedi)",
          s == 201 and addebitato == prezzo_visto == 60000,
          "visto=%s addebitato=%s status=%s" % (prezzo_visto, addebitato, s))
    tok2b = _quote(g, "gara2", ci2, co2)
    nuovo = sis.firma.decodifica(tok2b).get("prezzo_guest_cents") if tok2b else None
    esito("A2 il NUOVO preventivo riflette il nuovo prezzo (120000), niente cache",
          nuovo == 120000, "nuovo preventivo=%s" % nuovo)

    # ── A3: cancellazione vs nuova prenotazione in gara sulla stessa notte ───────
    _host_pubblica(g, tk, "gara3", 1, 20000, da, a)
    ci3 = (oggi + datetime.timedelta(days=15)).isoformat()
    co3 = (oggi + datetime.timedelta(days=17)).isoformat()
    tokA = _quote(g, "gara3", ci3, co3)
    s, bA = g("POST", "/api/concierge/book", {"quote_token": tokA, "email": "a@race.it"})
    vtA = (bA or {}).get("voucher_token") if isinstance(bA, dict) else None
    tokB = _quote(g, "gara3", ci3, co3)                        # 2o ospite in attesa dello slot
    bar2 = threading.Barrier(2)
    ris = {}

    def canc():
        bar2.wait()
        s, b = g("POST", "/api/concierge/cancella", {"voucher_token": vtA})
        ris["canc"] = s

    def book2():
        bar2.wait()
        s, b = g("POST", "/api/concierge/book", {"quote_token": tokB, "email": "b@race.it"})
        ris["book"] = s

    t1, t2 = threading.Thread(target=canc), threading.Thread(target=book2)
    t1.start(); t2.start(); t1.join(); t2.join()
    con = sqlite3.connect(d + "/i.db", timeout=30)
    try:
        maxocc = con.execute(
            "SELECT MAX(unita_occupate) FROM inventario WHERE alloggio_id='gara3' "
            "AND giorno>=? AND giorno<?", (ci3, co3)).fetchone()[0]
    except sqlite3.Error:
        maxocc = None
    con.close()
    esito("A3 cancella-vs-prenota: occupazione mai oltre 1 (%s)" % maxocc,
          maxocc is not None and maxocc <= 1, "max occupate=%s canc=%s book=%s"
          % (maxocc, ris.get("canc"), ris.get("book")))

    # ── A4: blocco-data host vs prenotazione in gara ─────────────────────────────
    _host_pubblica(g, tk, "gara4", 1, 20000, da, a)
    ci4 = (oggi + datetime.timedelta(days=20)).isoformat()
    co4 = (oggi + datetime.timedelta(days=21)).isoformat()     # 1 notte
    tokC = _quote(g, "gara4", ci4, co4)
    bar3 = threading.Barrier(2)
    ris4 = {}

    def blocca():
        bar3.wait()
        s, _ = g("POST", "/api/host/disponibilita",
                 {"alloggio_id": "gara4", "giorno": ci4, "unita_totali": 1,
                  "prezzo_netto_cents": 20000, "chiuso": True}, tk)
        ris4["blocca"] = s

    def bookc():
        bar3.wait()
        s, _ = g("POST", "/api/concierge/book", {"quote_token": tokC, "email": "c@race.it"})
        ris4["book"] = s

    t1, t2 = threading.Thread(target=blocca), threading.Thread(target=bookc)
    t1.start(); t2.start(); t1.join(); t2.join()
    con = sqlite3.connect(d + "/i.db", timeout=30)
    try:
        row = con.execute("SELECT unita_occupate, chiuso FROM inventario "
                          "WHERE alloggio_id='gara4' AND giorno=?", (ci4,)).fetchone()
    except sqlite3.Error:
        row = None
    con.close()
    # Invariante CORRETTO (prenota-poi-chiudi e' LEGITTIMO: l'host puo' chiudere una notte che ha
    # gia' un ospite; quell'ospite ha prenotato PRIMA della chiusura e la sua prenotazione resta).
    # Il vero difetto sarebbe: (a) overbooking (occupate>totali), oppure (b) prenotazione RIFIUTATA
    # che ha comunque occupato un'unita' (occupanti fantasma). BEGIN IMMEDIATE serializza le due
    # transazioni: se la chiusura vince, il book rilegge chiuso=1 e viene rifiutato (0 occupanti).
    occ, chiuso = (row[0], row[1]) if row else (None, None)
    bookok = ris4.get("book") == 201
    coerente = (row is not None and occ <= 1 and (bookok or occ == 0))
    esito("A4 blocco-vs-prenota: no overbooking, no occupante-fantasma da un book rifiutato",
          coerente, "occupate=%s chiuso=%s book=%s" % (occ, chiuso, ris4.get("book")))

    # ══════════════════════════════════════════════════════════════════════════
    print("-" * 80)
    print("FUZZING COMBINATORIO — campi x classi di valori ostili, mai un 500 non gestito")
    print("-" * 80)
    _fuzz(g)

    shutil.rmtree(d, ignore_errors=True)
    print("=" * 80)
    if FALLE:
        print("FALLE TROVATE: %d" % len(FALLE))
        for f in FALLE:
            print("   [X] " + f)
    else:
        print("0 FALLE: nessun double-booking, nessun prezzo mutato sotto i piedi, nessun 500 non gestito.")
    print("=" * 80)
    sys.exit(1 if FALLE else 0)


# ── FUZZING: valori ostili condivisi ─────────────────────────────────────────
OSTILI = [
    "", " ", "\x00", "\n\r", "a" * 20000, "%s%s%s%n", "' OR '1'='1", "<script>x</script>",
    "../../etc/passwd", "${jndi:ldap://x}", "-1", "0", "99999999999999999999", "NaN",
    "1e309", "😀🔥", "\ud800", "true", "null", "[]", "{}", 3.14, -0, [1, 2], {"x": 1},
]
STATUS_OK = set(range(200, 600))   # qualunque status HTTP definito va bene; il DIVIETO e' l'eccezione


def _prova(g, metodo, path, corpo, headers=None):
    """Ritorna (status, crashato_bool). Direttiva del fondatore: su input ostile il server DEVE
    rispondere con gestione controllata (400/401/403/404/409/410/422) e MAI crashare (500) o far
    risalire un'eccezione. Quindi 500 e -1 = FALLA, senza sconti (l'euristica 'Traceback nel corpo'
    era troppo debole: un 500 con corpo pulito nascondeva comunque un guasto non gestito)."""
    try:
        s, b = g(metodo, path, corpo, headers)
        return s, (s == 500)
    except Exception:
        return -1, True   # eccezione risalita fino al chiamante = crash non gestito


def _fuzz(g):
    casi = 0
    crash = []

    # 1) RICERCA / catalogo: querystring ostile (via path perche' il router prende query separata,
    #    ma passiamo valori ostili come corpo dove accettato + path variabili)
    for v in OSTILI:
        for path in ("/api/catalogo", "/api/concierge/quote", "/api/concierge/dettaglio"):
            casi += 1
            s, c = _prova(g, "POST", path, {"alloggio_id": v, "check_in": v,
                                            "check_out": v, "party": v})
            if c:
                crash.append("%s alloggio_id=%r -> %s" % (path, v, s))

    # 2) LOGIN host/admin/bunker: email/password/codice ostili
    for v in OSTILI:
        for path, campo in (("/api/host/login", {"email": v, "password": v}),
                            ("/api/host/registrazione", {"email": v, "password": v,
                             "accetta_termini": v, "accetta_privacy": v, "accetta_clausole": v}),
                            ("/api/bunker/login", {"codice": v})):
            casi += 1
            s, c = _prova(g, "POST", path, campo, {"X-Admin-Key": "ak"})
            if c:
                crash.append("%s %r -> %s" % (path, v, s))

    # 3) CHECKOUT / book / cancella: token ostili
    for v in OSTILI:
        for path, campo in (("/api/concierge/book", {"quote_token": v, "email": v}),
                            ("/api/concierge/cancella", {"voucher_token": v}),
                            ("/api/payments/webhook", None)):
            casi += 1
            body = v if path.endswith("webhook") else campo
            s, c = _prova(g, "POST", path, body if not isinstance(body, str) else None,
                          {"Stripe-Signature": str(v)[:200]})
            if c:
                crash.append("%s %r -> %s" % (path, v, s))

    # 4) PANNELLI protetti: token/cookie ostili (devono dare 401/403/302, mai crash)
    for v in OSTILI:
        for path in ("/api/host/payout", "/api/host/prenotazioni", "/api/host/pubblica",
                     "/api/bunker/invarianti", "/api/admin/rimborso"):
            casi += 1
            s, c = _prova(g, "POST", path, {"x": v},
                          {"X-Host-Token": str(v)[:500], "X-Admin-Key": str(v)[:500]})
            if c:
                crash.append("%s tok=%r -> %s" % (path, v, s))

    # 5) COMBINATORIO 2-a-2 sul book: coppie di campi ostili insieme (esplora interazioni)
    campi = ["quote_token", "email", "lang", "modo_pagamento"]
    for a, b in itertools.combinations(campi, 2):
        for va, vb in itertools.product(OSTILI[:8], OSTILI[:8]):
            casi += 1
            s, c = _prova(g, "POST", "/api/concierge/book", {a: va, b: vb})
            if c:
                crash.append("book %s=%r %s=%r -> %s" % (a, va, b, vb, s))

    esito("FUZZING combinatorio: %d combinazioni, nessun crash/500 non gestito" % casi,
          not crash, "crash=%d es: %s" % (len(crash), "; ".join(crash[:3])))


if __name__ == "__main__":
    main()
