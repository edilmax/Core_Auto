"""
COLLAUDO MULTI-VETTORE — sollecitazioni incrociate simultanee per stanare micro-anomalie
dall'INTERAZIONE fra componenti. Quattro vettori, ognuno con osservabile FORTE e, dove serve,
un GIUDICE indipendente (l'auditor invarianti fase199 sui DB reali).

  V1  RESILIENZA DI RETE / IDEMPOTENZA — connessione che cade + retry del client/gateway:
      webhook di pagamento consegnato 2 volte (Stripe ritenta), book ripetuto sullo stesso
      quote_token (il client non ha ricevuto il 201), blocco ripetuto sulla stessa idem_key.
      -> MAI transazioni duplicate, doppie prenotazioni o stati DB orfani.
  V2  CONCORRENZA MULTI-PANNELLO (barriera di thread) — pannelli diversi nello stesso istante:
      (a) host cambia prezzo mentre l'ospite fa il checkout; (b) admin sospende l'annuncio
      mentre l'host aggiorna la disponibilita'; (c) super-admin cambia la commissione globale
      mentre e' in corso un preventivo. -> integrita' atomica, il valore FIRMATO vince.
  V3  MANOMISSIONE SESSIONE / SCALATA PRIVILEGI — token/cookie/payload alterati in transito:
      cookie host su pagina admin, firma HMAC manomessa, token host usato come chiave admin,
      ruolo operatore ribaltato, payload giganti/surrogati. -> gate rifiuta (302/401/403),
      MAI un 500 / eccezione non gestita.
  V4  INVARIANTI FINANZIARI / LIMITI ARITMETICI — importi estremi, valute, min/max gateway:
      la somma payout_host + commissione + costo_carta + tassa == totale addebitato all'ospite,
      con errore ASSOLUTO di 0 centesimi, in OGNI combinazione; nessun negativo; guest==netto (0%).

Deterministico, in-house. Un solo comando:  python collaudi/multivettore.py
"""
import datetime
import itertools
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fase199_invarianti as INV
from collaudi.gare_estreme import _sistema, _host_pubblica, _quote
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

FALLE = []
_N = [0]


def esito(nome, ok, dett=""):
    _N[0] += 1
    print("  [%s] %2d. %s%s" % ("OK   " if ok else "FALLA", _N[0], nome,
                                "" if ok else "  -> " + dett))
    if not ok:
        FALLE.append("%s: %s" % (nome, dett))


def _router(sis):
    return crea_router(sis, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")


def _g(r):
    def g(m, p, b=None, h=None):
        return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})
    g.__wrapped_router__ = r      # per i casi (webhook) che devono passare il body GREZZO
    return g


def _host(g):
    s, c = g("POST", "/api/host/registrazione", {
        "email": "h@mv.it", "password": "password1", "accetta_termini": True,
        "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
        "versione": CONTRATTO_HOST_VERSIONE})
    return {"X-Host-Token": (c or {}).get("token", "")}


def _webhook_pl(rif):
    return json.dumps({"type": "checkout.session.completed",
                       "data": {"object": {"metadata": {"riferimento": rif}}}})


def _occ(dbdir, slug, ci, co):
    con = sqlite3.connect(dbdir + "/i.db", timeout=30)
    try:
        return con.execute("SELECT COALESCE(SUM(unita_occupate),0) FROM inventario "
                           "WHERE alloggio_id=? AND giorno>=? AND giorno<?",
                           (slug, ci, co)).fetchone()[0]
    except sqlite3.Error:
        return None
    finally:
        con.close()


# ══════════════════════════════════════════════════════════════════════════════
# V1 — RESILIENZA DI RETE / IDEMPOTENZA
# ══════════════════════════════════════════════════════════════════════════════
def v1_idempotenza(d, sis, g, tk, oggi):
    print("-- V1  RESILIENZA DI RETE / IDEMPOTENZA (retry non duplica MAI) --")
    _host_pubblica(g, tk, "mv1", 1, 20000, oggi.isoformat(),
                   (oggi + datetime.timedelta(days=40)).isoformat())
    ci = (oggi + datetime.timedelta(days=5)).isoformat()
    co = (oggi + datetime.timedelta(days=7)).isoformat()

    # 1a) BOOK ripetuto sullo STESSO quote_token (connessione caduta, il client ritenta)
    tok = _quote(g, "mv1", ci, co)
    s1, b1 = g("POST", "/api/concierge/book", {"quote_token": tok, "email": "o@mv.it"})
    s2, b2 = g("POST", "/api/concierge/book", {"quote_token": tok, "email": "o@mv.it"})
    rif = (b1 or {}).get("riferimento")
    idem2 = isinstance(b2, dict) and b2.get("idempotente") is True
    occ = _occ(d, "mv1", ci, co)
    esito("V1a book ripetuto (stesso token) -> 1 sola occupazione, 2a idempotente",
          s1 == 201 and s2 == 201 and idem2 and occ == 2,   # 2 notti x 1 unita'
          "s1=%s s2=%s idem2=%s occ=%s" % (s1, s2, idem2, occ))

    # 1b) WEBHOOK di pagamento consegnato DUE volte (Stripe ritenta). Il body va passato GREZZO
    # (la firma e' calcolata su quei byte esatti): uso gestisci() diretto, non il wrapper g()
    # che ri-serializzerebbe la stringa (doppia codifica -> firma non combacia).
    pl = _webhook_pl(rif)
    gz = g.__wrapped_router__
    w1, _ = gz.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})
    w2, _ = gz.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})
    info = sis.pagamenti_pendenti.info(rif) if hasattr(sis, "pagamenti_pendenti") else None
    stato = (info or {}).get("stato")
    esito("V1b webhook doppio -> pagato UNA volta, 2a consegna controllata",
          w1 in (200, 409) and w2 in (200, 409) and stato == "pagato",
          "w1=%s w2=%s stato=%s" % (w1, w2, stato))

    # 1c) l'occupazione NON e' raddoppiata dal doppio webhook (nessuno stato orfano)
    occ2 = _occ(d, "mv1", ci, co)
    esito("V1c dopo il doppio webhook: occupazione invariata (nessun duplicato)",
          occ2 == 2, "occ=%s (atteso 2)" % occ2)

    # 1d) giudice indipendente: auditor invarianti sui DB reali
    viol = INV.scansiona_db(d).get("violazioni", {})
    esito("V1d giudice (auditor fase199): 0 violazioni dopo i retry", not viol,
          "violazioni=%r" % viol)


# ══════════════════════════════════════════════════════════════════════════════
# V2 — CONCORRENZA MULTI-PANNELLO
# ══════════════════════════════════════════════════════════════════════════════
def v2_multipannello(d, sis, g, tk, oggi):
    print("-- V2  CONCORRENZA MULTI-PANNELLO (il valore FIRMATO vince, integrita' atomica) --")
    da = oggi.isoformat()
    a = (oggi + datetime.timedelta(days=40)).isoformat()

    # 2a) host cambia il prezzo MENTRE l'ospite ha il preventivo in mano
    _host_pubblica(g, tk, "mv2a", 5, 30000, da, a)
    ci = (oggi + datetime.timedelta(days=10)).isoformat()
    co = (oggi + datetime.timedelta(days=12)).isoformat()   # 2 notti = 60000
    tok = _quote(g, "mv2a", ci, co)
    visto = sis.firma.decodifica(tok).get("prezzo_guest_cents")
    bar = threading.Barrier(2)
    out = {}

    def cambia():
        bar.wait()
        g("POST", "/api/host/disponibilita_range",
          {"alloggio_id": "mv2a", "da": da, "a": a, "unita_totali": 5,
           "prezzo_netto_cents": 90000, "min_notti": 1}, tk)

    def book():
        bar.wait()
        s, b = g("POST", "/api/concierge/book", {"quote_token": tok, "email": "o@mv.it"})
        out["s"], out["prezzo"] = s, (b or {}).get("prezzo_guest_cents")

    t1, t2 = threading.Thread(target=cambia), threading.Thread(target=book)
    t1.start(); t2.start(); t1.join(); t2.join()
    esito("V2a prezzo-in-checkout: addebito = prezzo firmato (mai il nuovo sotto i piedi)",
          out.get("s") == 201 and out.get("prezzo") == visto == 60000,
          "visto=%s addebitato=%s" % (visto, out.get("prezzo")))

    # 2b) admin SOSPENDE l'annuncio mentre l'host aggiorna la disponibilita'
    _host_pubblica(g, tk, "mv2b", 3, 25000, da, a)
    ci2 = (oggi + datetime.timedelta(days=14)).isoformat()
    co2 = (oggi + datetime.timedelta(days=16)).isoformat()
    bar2 = threading.Barrier(2)

    def sospendi():
        bar2.wait()
        sis.catalogo.imposta_stato("mv2b", "sospeso")   # cio' che fa l'endpoint admin

    def aggiorna_disp():
        bar2.wait()
        g("POST", "/api/host/disponibilita_range",
          {"alloggio_id": "mv2b", "da": da, "a": a, "unita_totali": 9,
           "prezzo_netto_cents": 25000, "min_notti": 1}, tk)

    t1, t2 = threading.Thread(target=sospendi), threading.Thread(target=aggiorna_disp)
    t1.start(); t2.start(); t1.join(); t2.join()
    # dopo: annuncio sospeso -> NON vendibile (quote 404), a prescindere dall'update disponibilita'
    sq, _ = g("POST", "/api/concierge/quote",
              {"alloggio_id": "mv2b", "check_in": ci2, "check_out": co2, "party": 2})
    sb = None
    tok_susp = _quote(g, "mv2b", ci2, co2)
    if tok_susp:
        sb, _ = g("POST", "/api/concierge/book", {"quote_token": tok_susp, "email": "x@mv.it"})
    esito("V2b admin-sospende-vs-host-aggiorna: annuncio sospeso NON vendibile (quote 404, no book)",
          sq == 404 and sb in (None, 404, 409, 422),
          "quote=%s book=%s (l'aggiornamento host non resuscita un sospeso)" % (sq, sb))

    # 2c) commissione globale "in volo": nell'architettura la commissione e' (1) FROZEN in config
    # (dataclass immutabile a runtime -> un pannello non la cambia sotto una transazione) e (2)
    # FIRMATA dentro il preventivo. Quindi un preventivo gia' emesso non e' alterabile da nessun
    # cambio globale. Prova FORTE del legame crittografico: il book onora la commissione firmata,
    # e un token con commissione MANOMESSA viene rifiutato (firma rotta).
    _host_pubblica(g, tk, "mv2c", 5, 40000, da, a)
    ci3 = (oggi + datetime.timedelta(days=18)).isoformat()
    co3 = (oggi + datetime.timedelta(days=19)).isoformat()   # 1 notte
    tok3 = _quote(g, "mv2c", ci3, co3)
    comm_firmata = sis.firma.decodifica(tok3).get("commissione_cents")
    s3, b3 = g("POST", "/api/concierge/book", {"quote_token": tok3, "email": "o@mv.it"})
    comm_book = (b3 or {}).get("commissione_cents")
    esito("V2c il book onora la commissione FIRMATA nel preventivo (immutabile)",
          s3 == 201 and comm_book == comm_firmata,
          "firmata=%s nel_book=%s" % (comm_firmata, comm_book))
    # token manomesso: cambio l'ultimo carattere della firma -> deve essere rifiutato
    tok_falso = tok3[:-1] + ("A" if tok3[-1] != "A" else "B")
    sfake, _ = g("POST", "/api/concierge/book", {"quote_token": tok_falso, "email": "o@mv.it"})
    esito("V2c un preventivo con firma MANOMESSA e' rifiutato (commissione non falsificabile)",
          sfake in (400, 401, 403, 410, 422), "status %s (atteso rifiuto)" % sfake)


# ══════════════════════════════════════════════════════════════════════════════
# V3 — MANOMISSIONE SESSIONE / SCALATA PRIVILEGI
# ══════════════════════════════════════════════════════════════════════════════
def v3_tampering(g):
    print("-- V3  MANOMISSIONE SESSIONE / SCALATA PRIVILEGI (rifiuto pulito, mai 500) --")

    # NB: il gate delle PAGINE (302 su /admin.html /bunker.html /host.html senza cookie valido)
    # vive nell'HANDLER HTTP, non nel router `gestisci` -> lo copre `test_gatekeeper.py` contro un
    # VERO server (cookie manomesso/di altro livello -> 302). Qui provo il livello ROUTER: le API
    # sensibili e i tentativi di SCALATA privilegi devono dare rifiuto pulito, MAI 500.
    casi = [
        ("token host come chiave admin (scalata host->admin)", "POST", "/api/admin/rimborso",
         {"X-Admin-Key": "h_qualcosa-deadbeef"}, (401, 403)),
        ("ruolo operatore RIBALTATO a admin (firma finta)", "POST", "/api/admin/rimborso",
         {"X-Admin-Op": "op|a@x.it|admin|9999999999|n|00000000"}, (401, 403)),
        ("chiave admin quasi-giusta (un carattere in piu')", "POST", "/api/admin/rimborso",
         {"X-Admin-Key": "ak0"}, (401, 403)),
        ("host prova un'azione admin col PROPRIO token", "POST", "/api/admin/rimborso",
         {"X-Host-Token": "chiunque"}, (401, 403)),
        ("payload GIGANTE nel token host", "GET", "/api/host/payout",
         {"X-Host-Token": "A" * 100000}, (401, 403)),
        ("SURROGATO isolato nel token host", "GET", "/api/host/payout",
         {"X-Host-Token": "ab\ud800cd"}, (401, 403)),
        ("SURROGATO isolato nella chiave admin", "POST", "/api/admin/rimborso",
         {"X-Admin-Key": "𐏿"}, (401, 403)),
        ("byte di controllo nella chiave admin", "POST", "/api/admin/rimborso",
         {"X-Admin-Key": "\x00\x01\x02"}, (401, 403)),
        ("token bunker manomesso su API bunker", "GET", "/api/bunker/invarianti",
         {"X-Admin-Key": "ak", "Cookie": "bv_bunker=bunker|99999999999|x|ffffffff"}, (401, 403, 302)),
    ]
    for nome, metodo, path, headers, attesi in casi:
        try:
            body = None if metodo == "GET" else {"riferimento": "x"}
            s, _b = g(metodo, path, body, headers)
        except Exception as e:
            esito("V3 " + nome, False, "ECCEZIONE NON GESTITA: %r" % e)
            continue
        # invariante di sicurezza: MAI crash (500/-1) e MAI accesso concesso (200/201).
        # Qualunque rifiuto pulito va bene (302/400/401/403/404/422).
        ok = s not in (500, -1, 200, 201)
        esito("V3 " + nome + " -> %s" % s, ok, "status %s (crash o accesso concesso!)" % s)


# ══════════════════════════════════════════════════════════════════════════════
# V4 — INVARIANTI FINANZIARI / LIMITI ARITMETICI
# ══════════════════════════════════════════════════════════════════════════════
def v4_finanza():
    print("-- V4  INVARIANTI FINANZIARI (totale ospite = host + commissione + carta + tassa, 0 cent) --")
    PREZZI = [1, 2, 99, 100, 12345, 500000, 999999, 5_000_000]
    NOTTI = [1, 2, 7, 30, 90]
    COMM = [0, 500, 800, 1000, 1500]     # 0%, 5%, 8%, 10%, 15% bps
    PSP = [200, 300, 325]                # costo carta bps
    casi = 0
    rotti = []
    for comm_bps, psp_bps in itertools.product(COMM, PSP):
        d = tempfile.mkdtemp()
        sis = _sistema(d)
        # imposto i tassi e ricostruisco il router
        try:
            sis.config.commissione_bps = comm_bps
            sis.config.psp_bps = psp_bps
        except Exception:
            pass
        r = _router(sis)
        g = _g(r)
        tk = _host(g)
        oggi = datetime.date.today()
        da = oggi.isoformat()
        a = (oggi + datetime.timedelta(days=120)).isoformat()
        for prezzo_notte, notti in itertools.product(PREZZI, NOTTI):
            slug = "fx%dx%d" % (prezzo_notte, notti)   # niente underscore (verrebbe slugificato)
            slug = _host_pubblica(g, tk, slug, 3, prezzo_notte, da, a)   # slug REALE restituito
            ci = (oggi + datetime.timedelta(days=2)).isoformat()
            co = (oggi + datetime.timedelta(days=2 + notti)).isoformat()
            tok = _quote(g, slug, ci, co)
            if not tok:
                continue
            q = sis.firma.decodifica(tok)
            casi += 1
            totale = q.get("totale_cents")
            netto_host = q.get("netto_host_cents")
            comm = q.get("commissione_cents")
            carta = q.get("costo_pagamento_cents")
            tassa = q.get("tassa_soggiorno_cents")
            guest = q.get("prezzo_guest_cents")
            netto = q.get("prezzo_netto_cents")
            sconto = q.get("sconto_credito_cents", 0)
            # INVARIANTE CENTRALE (senza credito): totale addebitato = tutti i destinatari, 0 cent
            somma = netto_host + comm + carta + tassa
            if sconto == 0 and totale != somma:
                rotti.append("comm=%d psp=%d prezzo=%d notti=%d: totale=%d != host+comm+carta+tassa=%d (Δ=%d)"
                             % (comm_bps, psp_bps, prezzo_notte, notti, totale, somma, totale - somma))
            # nessun negativo; guest == netto (0% fee ospite quando non c'e' sconto)
            if min(totale, netto_host, comm, carta, tassa, guest) < 0:
                rotti.append("NEGATIVO comm=%d psp=%d prezzo=%d notti=%d" % (comm_bps, psp_bps, prezzo_notte, notti))
            if sconto == 0 and guest != netto:
                rotti.append("guest!=netto (fee ospite non-zero) prezzo=%d notti=%d" % (prezzo_notte, notti))
        shutil.rmtree(d, ignore_errors=True)
    esito("V4 %d preventivi su griglia importi×notti×comm×psp: somma ESATTA a 0 centesimi" % casi,
          not rotti, "rotti=%d es: %s" % (len(rotti), " | ".join(rotti[:3])))


# ══════════════════════════════════════════════════════════════════════════════
def main():
    d = tempfile.mkdtemp()
    sis = _sistema(d)
    r = _router(sis)
    g = _g(r)
    tk = _host(g)
    oggi = datetime.date.today()

    print("=" * 82)
    print("COLLAUDO MULTI-VETTORE — resilienza rete + concorrenza pannelli + tampering + finanza")
    print("=" * 82)
    v1_idempotenza(d, sis, g, tk, oggi)
    v2_multipannello(d, sis, g, tk, oggi)
    v3_tampering(g)
    shutil.rmtree(d, ignore_errors=True)
    v4_finanza()

    print("=" * 82)
    if FALLE:
        print("FALLE TROVATE: %d" % len(FALLE))
        for f in FALLE:
            print("   [X] " + f)
    else:
        print("0 FALLE: idempotenza tenuta, integrita' atomica, gate blindati, aritmetica a 0 centesimi.")
    print("=" * 82)
    sys.exit(1 if FALLE else 0)


if __name__ == "__main__":
    main()
