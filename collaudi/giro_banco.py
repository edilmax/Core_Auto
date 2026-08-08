"""IL GIRO SUL BANCO — dieci prenotazioni vere su Stripe di prova, e i conti che devono quadrare.

A COSA SERVE, e perche' non basta una sola prenotazione. Il 2026-08-08 ne e' stata fatta UNA e
i numeri tornavano tutti; il fondatore ha detto: *«la nuova chat rifà la prova con dieci
prenotazioni, e siamo più sicuri»*. Ha ragione: **una puo' andare bene per caso, dieci no**. E
con dieci si vedono le cose che si rompono SOLO quando ce n'e' piu' di una -- date che si
accavallano, conti che si sommano, una seconda prenotazione sulla stessa stanza.

COME SI LANCIA (il banco dev'essere gia' acceso, vedi collaudi/banco_prova.sh):
    docker exec -i banco_prova_app python3 -  <  collaudi/giro_banco.py

⛔ PRIMA DI SMONTARE IL BANCO, LEGGERE I REGISTRI:
    docker logs banco_prova_app 2>&1 | grep -iE "hold pagamento|warning|error"
   Il 2026-08-08 il banco e' stato smontato prima di leggerli e si e' persa la prova di PERCHE'
   la registrazione del pendente non avviene (sospetto: l'`except` che ingoia a fase83:5243).

⛔ LIMITE DICHIARATO: il gesto di digitare la carta sulla pagina di Stripe non e' simulabile
   senza un browser. Qui si prova che la sessione la crea Stripe DAVVERO, e si consegna il
   webhook di pagamento firmato col nostro segreto -- cioe' la stessa forma che Stripe manda.
"""
import datetime
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8080"
PREZZO = 500                 # 5,00 EUR a notte
NOTTI = 2
QUANTE = int(os.environ.get("GIRI", "10"))
esiti = []


def chiama(m, p, corpo=None, testate=None, grezzo=None):
    d = grezzo.encode() if grezzo is not None else (
        json.dumps(corpo).encode() if corpo is not None else None)
    h = {"Content-Type": "application/json"}
    h.update(testate or {})
    r = urllib.request.Request(BASE + p, data=d, headers=h, method=m)
    try:
        with urllib.request.urlopen(r, timeout=30) as x:
            t = x.read().decode("utf-8", "replace")
            try:
                return x.status, json.loads(t)
            except Exception:
                return x.status, t[:200]
    except urllib.error.HTTPError as e:
        t = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(t)
        except Exception:
            return e.code, t[:200]
    except Exception as e:
        return 0, repr(e)


def passo(nome, ok, atteso="", ott=""):
    esiti.append(bool(ok))
    print("  %s %-56s %s" % ("OK " if ok else "NO ", nome,
                             "" if (ok and not atteso) else "(atteso %s / ottenuto %s)" % (atteso, ott)))


def giornale():
    c = sqlite3.connect("file:/data/finanza.db?mode=ro", uri=True)
    try:
        return c.execute("SELECT seq,tipo,conto_dare,conto_avere,importo_cents,prev_hash,hash "
                         "FROM libro_giornale ORDER BY seq").fetchall()
    except Exception:
        return []
    finally:
        c.close()


def saldo_host():
    s = 0
    for _, _, dare, avere, imp, _, _ in giornale():
        if avere == "debiti_vs_host":
            s += imp
        if dare == "debiti_vs_host":
            s -= imp
    return s


def righe_pendenti():
    try:
        c = sqlite3.connect("file:/data/pendenti.db?mode=ro", uri=True)
        try:
            return c.execute("SELECT COUNT(*) FROM pendenti").fetchone()[0]
        finally:
            c.close()
    except Exception:
        return -1


def paga(rif):
    """Consegna il webhook di pagamento, costruito coi dati VERI della sessione Stripe."""
    k = os.environ.get("STRIPE_SECRET_KEY", "")
    req = urllib.request.Request("https://api.stripe.com/v1/checkout/sessions?limit=1",
                                 headers={"Authorization": "Bearer %s" % k,
                                          "User-Agent": "banco-prova"})
    with urllib.request.urlopen(req, timeout=25) as r:
        sess = json.load(r)["data"][0]
    if (sess.get("metadata") or {}).get("riferimento") != rif:
        return None, "la sessione piu' recente di Stripe non e' di questa prenotazione"
    from fase87_stripe_webhook import firma_di_test
    og = {"id": sess["id"], "mode": sess.get("mode", "payment"), "payment_status": "paid",
          "status": "complete", "amount_total": sess.get("amount_total"),
          "currency": sess.get("currency"), "metadata": sess.get("metadata") or {},
          "client_reference_id": sess.get("client_reference_id"),
          "payment_intent": sess.get("payment_intent") or ("pi_test_" + rif[:12])}
    carico = json.dumps({"type": "checkout.session.completed", "data": {"object": og}})
    f = firma_di_test(carico, os.environ.get("STRIPE_WEBHOOK_SECRET", ""), int(time.time()))
    s, _ = chiama("POST", "/api/payments/webhook", grezzo=carico, testate={"Stripe-Signature": f})
    return s, sess


print("=" * 78)
print("GIRO SUL BANCO — %d prenotazioni, %d EUR a notte, %d notti" % (QUANTE, PREZZO / 100, NOTTI))
print("=" * 78)

# --- l'host e l'annuncio -----------------------------------------------------
print("\n-- L'HOST E L'ANNUNCIO --")
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256   # noqa: E402
s, c = chiama("POST", "/api/host/registrazione", {
    "email": "banco@prova.it", "password": "password1", "accetta_termini": True,
    "accetta_clausole": True, "accetta_privacy": True,
    "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
tok = c.get("token") if isinstance(c, dict) else None
passo("registrazione host", s == 201 and bool(tok), "201 + token", s)
tk = {"X-Host-Token": tok or ""}

s, _ = chiama("POST", "/api/host/pubblica", {
    "slug": "banco-test", "titolo": "Banco di prova", "citta": "Milano",
    "prezzo_notte_cents": PREZZO, "capacita": 2}, tk)
passo("pubblica l'annuncio", s in (200, 201), "200/201", s)

oggi = datetime.date.today()
s, _ = chiama("POST", "/api/host/disponibilita_range", {
    "alloggio_id": "banco-test", "da": oggi.isoformat(),
    "a": (oggi + datetime.timedelta(days=120)).isoformat(),
    "unita_totali": 1, "prezzo_netto_cents": PREZZO}, tk)
passo("apre le date (120 giorni, 1 unita')", s in (200, 201), "200/201", s)

# --- i giri ------------------------------------------------------------------
print("\n-- LE %d PRENOTAZIONI --" % QUANTE)
print("     (pagate le pari, cancellate le dispari; la n.3 duplica le date della n.2;")
print("      l'ultima resta NON pagata di proposito)")
fatte, pagate, cancellate, rifiutate = [], 0, 0, 0
for i in range(QUANTE):
    giorno = 10 + i * 3
    if i == 3:                       # duplicato voluto: stesse date della n.2
        giorno = 10 + 2 * 3
    ci = (oggi + datetime.timedelta(days=giorno)).isoformat()
    co = (oggi + datetime.timedelta(days=giorno + NOTTI)).isoformat()
    s, q = chiama("POST", "/api/concierge/quote", {
        "alloggio_id": "banco-test", "check_in": ci, "check_out": co, "party": 2})
    if s != 200 or not isinstance(q, dict) or not q.get("quote_token"):
        if i == 3:
            rifiutate += 1
            print("  %2d  %s  RIFIUTATA (date gia' occupate) -- ATTESO" % (i + 1, ci))
        else:
            print("  %2d  %s  preventivo NEGATO (%s) -- non atteso" % (i + 1, ci, s))
            esiti.append(False)
        continue
    if q.get("prezzo_listino_cents") != PREZZO * NOTTI:
        passo("prezzo del giro %d" % (i + 1), False, PREZZO * NOTTI, q.get("prezzo_listino_cents"))
    s, b = chiama("POST", "/api/concierge/book",
                  {"quote_token": q["quote_token"], "email": "osp%d@prova.it" % i, "lang": "it"})
    if s != 201:
        if i == 3:
            rifiutate += 1
            print("  %2d  %s  RIFIUTATA in prenotazione -- ATTESO" % (i + 1, ci))
        else:
            print("  %2d  %s  PRENOTAZIONE NEGATA (%s %s)" % (i + 1, ci, s, b))
            esiti.append(False)
        continue
    rif, vt = b.get("riferimento"), b.get("voucher_token")
    ultima = (i == QUANTE - 1)
    if ultima:
        print("  %2d  %s  prenotata, LASCIATA NON PAGATA -- voluto" % (i + 1, ci))
        fatte.append((rif, vt, False))
        continue
    st, _ = paga(rif)
    if st != 200:
        print("  %2d  %s  PAGAMENTO NON REGISTRATO (%s)" % (i + 1, ci, st))
        esiti.append(False)
        continue
    pagate += 1
    if i % 2 == 1:                    # le dispari si cancellano
        s, canc = chiama("POST", "/api/concierge/cancella", {"voucher_token": vt})
        if s == 200 and isinstance(canc, dict) and canc.get("stato") in ("cancellata", "rimborsata"):
            cancellate += 1
            print("  %2d  %s  pagata e CANCELLATA (rimborso dichiarato %s)"
                  % (i + 1, ci, canc.get("rimborso_cents")))
        else:
            print("  %2d  %s  cancellazione FALLITA (%s)" % (i + 1, ci, s))
            esiti.append(False)
    else:
        print("  %2d  %s  pagata" % (i + 1, ci))
    fatte.append((rif, vt, True))

# --- i conti, che sono il punto ---------------------------------------------
print("\n-- I CONTI DEVONO QUADRARE (e' qui che una sola prenotazione non basta) --")
g = giornale()
inc = sum(i for _, t, _, _, i, _, _ in g if t == "incasso")
com = sum(i for _, t, _, _, i, _, _ in g if t == "commissione")
netto_atteso = pagate * PREZZO * NOTTI
passo("somma degli incassi = pagate x prezzo", inc == netto_atteso,
      "%d (%d x %d)" % (netto_atteso, pagate, PREZZO * NOTTI), inc)
passo("commissione = 3%% di ogni incasso", com == pagate * 30,
      "%d" % (pagate * 30), com)
passo("dovuto agli host = incassi - commissioni", saldo_host() == inc - com,
      "%d" % (inc - com), saldo_host())

prev = "GENESI"
rotta = None
for seq, _, _, _, _, ph, h in g:
    if ph != prev:
        rotta = seq
        break
    prev = h
passo("catena di impronte del libro giornale", rotta is None, "integra",
      "rotta alla riga %s" % rotta)

passo("la n.3 (date duplicate) e' stata RIFIUTATA", rifiutate >= 1, ">=1", rifiutate)

pend = righe_pendenti()
print("\n  righe nei pagamenti pendenti: %s   (0 = il difetto del 2026-08-08 e' ancora li')" % pend)
print("  righe nel libro giornale:     %d" % len(g))
print("  pagate %d · cancellate %d · rifiutate %d · non pagate %d"
      % (pagate, cancellate, rifiutate, 1 if QUANTE else 0))

print("\n⛔ ORA, PRIMA DI SMONTARE IL BANCO:")
print("     docker logs banco_prova_app 2>&1 | grep -iE 'hold pagamento|warning|error'")

print("\n" + "=" * 78)
print("PASSI: %d   OK: %d   NON OK: %d" % (len(esiti), sum(esiti), len(esiti) - sum(esiti)))
print("=" * 78)
sys.exit(0 if all(esiti) else 1)
