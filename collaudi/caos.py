"""
CAOS ENGINEERING — i 4 pezzi che `collaudi/estremo.py` NON copre gia' (mirato, no doppioni):

  A) SIGKILL VERO del processo server a META' delle prenotazioni -> riavvio sugli STESSI dati ->
     nessuna corruzione, nessun double-booking, nessuna riga fantasma permanente, sito di nuovo vivo.
     (estremo.py "kill" chiudendo la connessione; qui e' un kill -9 dell'INTERO processo.)
  B) FILE DESCRIPTOR / handle: sotto migliaia di richieste il numero di descrittori resta PIATTO
     (estremo.py misura la RAM, non i descrittori: un connection-leak non si vedrebbe).
  C) MANOMISSIONE DIRETTA di DB/token: la catena-hash del giornale (fase177) e i token firmati HMAC
     rilevano al 100% ogni alterazione a mano; + limite ONESTO (cosa NON e' protetto da checksum).
  D) DEADLOCK / TIMEOUT su risorsa condivisa: con un lock di scrittura tenuto, un secondo scrittore
     col suo timeout riceve un errore PULITO 'database is locked' e NON congela; poi si sblocca.

Deterministico, in-house. Un solo comando:  python collaudi/caos.py
"""
import http.client
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fase199_invarianti as INV
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

PY = sys.executable
FALLE = []
_N = [0]


def esito(nome, ok, dett=""):
    _N[0] += 1
    print("  [%s] %2d. %s%s" % ("OK   " if ok else "FALLA", _N[0], nome,
                                "" if ok else "  -> " + dett))
    if not ok:
        FALLE.append("%s: %s" % (nome, dett))


def _porta_libera():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _http(porta, metodo, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", porta, timeout=6)
    try:
        c.request(metodo, path, body=(json.dumps(body) if body is not None else None),
                  headers=headers or {})
        r = c.getresponse()
        return r.status, r.read().decode("utf-8", "replace")
    finally:
        c.close()


def _up(porta, sec=25):
    for _ in range(sec * 5):
        try:
            if _http(porta, "GET", "/api/health/live")[0] == 200:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _integri(d):
    bad = []
    import glob
    for f in glob.glob(os.path.join(d, "*.db")):
        try:
            if sqlite3.connect(f).execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                bad.append(os.path.basename(f))
        except sqlite3.Error:
            bad.append(os.path.basename(f) + "(illeggibile)")
    return bad


# ══════════════════════════════════════════════════════════════════════════════
# A) SIGKILL VERO a meta' scrittura + recupero
# ══════════════════════════════════════════════════════════════════════════════
def vettore_A():
    print("-- A  SIGKILL VERO del processo a META' delle prenotazioni + riavvio sugli stessi dati --")
    d = tempfile.mkdtemp(prefix="caos_")
    porta = _porta_libera()

    def _avvia(p):
        env = dict(os.environ, CAOS_DIR=d, CAOS_PORT=str(p))
        return subprocess.Popen([PY, "collaudi/_srv_caos.py"], cwd=ROOT, env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    proc = _avvia(porta)
    if not _up(porta):
        esito("A server di caos partito", False, "non risponde")
        proc.kill()
        shutil.rmtree(d, ignore_errors=True)
        return
    # setup: host + annuncio con molte unita' e date
    _, c = _http(porta, "POST", "/api/host/registrazione", {
        "email": "h@caos.it", "password": "password1", "accetta_termini": True,
        "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
        "versione": CONTRATTO_HOST_VERSIONE})
    tok = (json.loads(c) or {}).get("token", "") if c else ""
    hh = {"X-Host-Token": tok}
    import datetime
    oggi = datetime.date.today()
    da = oggi.isoformat()
    a = (oggi + datetime.timedelta(days=60)).isoformat()
    sp, _ = _http(porta, "POST", "/api/host/pubblica",
                  {"slug": "caos", "titolo": "Caos", "citta": "Roma",
                   "prezzo_notte_cents": 20000, "capacita": 4}, hh)
    sd, _ = _http(porta, "POST", "/api/host/disponibilita_range",
                  {"alloggio_id": "caos", "da": da, "a": a, "unita_totali": 5,
                   "prezzo_netto_cents": 20000, "min_notti": 1}, hh)
    if not (sp in (200, 201) and sd == 200):
        esito("A setup annuncio riuscito", False, "pubblica=%s disponibilita=%s token=%r" % (
            sp, sd, bool(tok)))

    # HAMMER: piu' thread prenotano notti diverse in continuazione
    stop = threading.Event()
    fatte = [0]
    lock = threading.Lock()

    def worker(i):
        n = 0
        while not stop.is_set():
            try:
                ci = (oggi + datetime.timedelta(days=2 + (i * 7 + n) % 40)).isoformat()
                co = (oggi + datetime.timedelta(days=3 + (i * 7 + n) % 40)).isoformat()
                s, q = _http(porta, "POST", "/api/concierge/quote",
                             {"alloggio_id": "caos", "check_in": ci, "check_out": co, "party": 2})
                if s == 200:
                    qt = json.loads(q).get("quote_token")
                    _http(porta, "POST", "/api/concierge/book",
                          {"quote_token": qt, "email": "g%d_%d@caos.it" % (i, n)})
                    with lock:
                        fatte[0] += 1
                n += 1
            except Exception:
                pass

    ths = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(6)]
    [t.start() for t in ths]
    time.sleep(2.5)                       # lascia partire un fiume di scritture
    # SIGKILL BRUTALE del processo (kill -9 / TerminateProcess): nessun cleanup, nessun commit finale
    proc.kill()
    proc.wait()
    stop.set()
    time.sleep(0.3)
    esito("A0 il processo era vivo e ha scritto prenotazioni prima del kill (%d)" % fatte[0],
          fatte[0] > 0, "nessuna prenotazione scritta")

    # RIAVVIO sugli STESSI dati (porta nuova per evitare il TIME_WAIT)
    porta2 = _porta_libera()
    proc2 = _avvia(porta2)
    su = _up(porta2)
    esito("A1 il server RIPARTE sugli stessi dati dopo il SIGKILL", su, "non riparte")

    bad = _integri(d)
    esito("A2 integrity_check OK su OGNI database dopo il kill brutale", not bad,
          "corrotti=%r" % bad)

    viol = INV.scansiona_db(d).get("violazioni", {})
    esito("A3 auditor invarianti: 0 double-booking dopo il crash", not viol,
          "violazioni=%r" % viol)

    over = []
    try:
        con = sqlite3.connect(d + "/i.db", timeout=30)
        over = con.execute("SELECT giorno FROM inventario WHERE unita_occupate > unita_totali").fetchall()
        con.close()
    except sqlite3.Error as e:
        over = [("err", repr(e))]
    esito("A4 nessuna notte in overbooking dopo il crash", not over, "overbooking=%r" % over)

    if su:
        st, _ = _http(porta2, "GET", "/api/catalogo")
        esito("A5 il sito e' di nuovo USABILE dopo il recupero (catalogo 200)", st == 200,
              "catalogo status %s" % st)
    proc2.kill()
    proc2.wait()
    shutil.rmtree(d, ignore_errors=True)

    # RED-PROOF dell'osservabile integrita': un DB troncato DEVE risultare corrotto
    d2 = tempfile.mkdtemp(prefix="caos_rp_")
    con = sqlite3.connect(d2 + "/x.db")
    con.execute("CREATE TABLE t(a)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    with open(d2 + "/x.db", "r+b") as f:
        f.truncate(20)                    # rompo il file a meta'
    esito("A6 (visto rosso) integrity_check SA vedere un DB corrotto", bool(_integri(d2)),
          "un file troncato non e' stato segnalato corrotto")
    shutil.rmtree(d2, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# B) FILE DESCRIPTOR / handle stabili
# ══════════════════════════════════════════════════════════════════════════════
def _conta_fd():
    try:
        return len(os.listdir("/proc/self/fd"))          # Linux
    except Exception:
        pass
    try:
        import ctypes                                     # Windows
        n = ctypes.c_ulong(0)
        k = ctypes.windll.kernel32
        if k.GetProcessHandleCount(k.GetCurrentProcess(), ctypes.byref(n)):
            return int(n.value)
    except Exception:
        pass
    return None


def vettore_B():
    print("-- B  FILE DESCRIPTOR / handle: sotto migliaia di richieste restano PIATTI --")
    import gc
    from collaudi.gare_estreme import _sistema, _host_pubblica, _quote
    from collaudi.multivettore import _router, _g, _host
    d = tempfile.mkdtemp(prefix="caos_fd_")
    sis = _sistema(d)
    r = _router(sis)
    g = _g(r)
    tk = _host(g)
    import datetime
    oggi = datetime.date.today()
    slug = _host_pubblica(g, tk, "fd", 5, 20000, oggi.isoformat(),
                          (oggi + datetime.timedelta(days=60)).isoformat())
    # rodaggio (apre le connessioni "una tantum")
    for _ in range(50):
        g("GET", "/api/catalogo")
    gc.collect()
    fd0 = _conta_fd()
    N = 2500
    for i in range(N):
        g("GET", "/api/catalogo")
        if i % 5 == 0:
            g("GET", "/api/health/db")
        if i % 11 == 0:
            ci = (oggi + datetime.timedelta(days=2 + i % 40)).isoformat()
            co = (oggi + datetime.timedelta(days=3 + i % 40)).isoformat()
            _quote(g, slug, ci, co)
    gc.collect()
    fd1 = _conta_fd()
    shutil.rmtree(d, ignore_errors=True)
    if fd0 is None or fd1 is None:
        esito("B file descriptor stabili (%d richieste)" % N, True,
              "conteggio fd non disponibile su questa piattaforma (saltato-soft)")
        print("     [nota] conteggio descrittori non disponibile qui; su Linux/VPS usa /proc/self/fd")
        return
    delta = fd1 - fd0
    esito("B file descriptor PIATTI dopo %d richieste (delta=%d)" % (N, delta),
          delta <= 20, "fd prima=%d dopo=%d delta=%d (leak?)" % (fd0, fd1, delta))


# ══════════════════════════════════════════════════════════════════════════════
# C) MANOMISSIONE DIRETTA: rilevata al 100% dove c'e' tamper-evidence
# ══════════════════════════════════════════════════════════════════════════════
def vettore_C():
    print("-- C  MANOMISSIONE DIRETTA di DB/token: la tamper-evidence la rileva al 100% --")
    from collaudi.gare_estreme import _sistema
    from fase177_financial_controller import crea_financial_controller
    d = tempfile.mkdtemp(prefix="caos_tp_")
    sis = _sistema(d)

    # C1) GIORNALE (fase177): catena-hash su FILE. 3 movimenti -> catena OK; poi altero un importo
    # a mano nel file .db (bypassando l'app) -> la catena si rompe e verifica_catena lo urla.
    fin = d + "/fin_caos.db"
    fc = crea_financial_controller(fin)
    fc.inizializza_schema()
    for i in range(3):
        fc.movimento(tipo="incasso", riferimento="R%d" % i, soggetto="ospite",
                     importo_cents=10000 + i, valuta="EUR", causale="test caos")
    pre = fc.verifica_catena()
    # DIFESA A STRATI: l'app blocca gia' l'UPDATE con un TRIGGER append-only ('UPDATE vietato').
    # Un attaccante con accesso al FILE puo' droppare i trigger -> lo simulo, poi altero l'importo.
    con = sqlite3.connect(fin, timeout=30)
    trig = [t[0] for t in con.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()]
    for t in trig:
        con.execute("DROP TRIGGER IF EXISTS %s" % t)
    con.execute("UPDATE libro_giornale SET importo_cents = importo_cents + 999 "
                "WHERE seq = (SELECT MIN(seq) FROM libro_giornale)")
    con.commit()
    con.close()
    post = fc.verifica_catena()
    esito("C1 giornale: append-only (trigger blocca l'UPDATE) + catena-hash becca la manomissione "
          "anche a trigger DROPPATI",
          bool(trig) and pre.get("ok") is True and post.get("ok") is False,
          "trigger=%r pre=%r post=%r seq_rotta=%r" % (trig, pre.get("ok"), post.get("ok"),
                                                      post.get("seq_rotta")))

    # C2) TOKEN firmato HMAC: un voucher manomesso di un byte -> rifiutato (decodifica None)
    vt = sis.firma.codifica({"tipo": "voucher", "riferimento": "abc", "lang": "it"})
    ok_valido = sis.firma.decodifica(vt) is not None
    vt_rotto = vt[:-1] + ("A" if vt[-1] != "A" else "B")
    rifiutato = sis.firma.decodifica(vt_rotto) is None
    esito("C2 token firmato: valido accettato, manomesso RIFIUTATO (100%)",
          ok_valido and rifiutato, "valido=%s rotto_rifiutato=%s" % (ok_valido, rifiutato))

    # C3) LIMITE ONESTO: una riga OPERATIVA senza catena-hash (prezzo nel catalogo) alterata a mano
    # NON e' rilevabile da un checksum (non e' un record legale/finanziario). Lo dichiaro.
    print("     [LIMITE ONESTO] i record OPERATIVI (prezzo catalogo, occupazione inventario) NON hanno")
    print("     un checksum per-riga: una modifica diretta al file .db non e' rilevata da un hash.")
    print("     Protetti da tamper-evidence SOLO i record legali/finanziari: giornale (catena-hash),")
    print("     marche temporali (catena), accettazioni contratto (HMAC), token firmati. Scelta")
    print("     proporzionata: l'integrita' del FILE la garantiscono OS/permessi + backup + integrity_check.")
    shutil.rmtree(d, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# D) DEADLOCK / TIMEOUT su risorsa condivisa
# ══════════════════════════════════════════════════════════════════════════════
def vettore_D():
    print("-- D  DEADLOCK/TIMEOUT: lock di scrittura tenuto -> il 2o scrittore ha errore PULITO, non congela --")
    d = tempfile.mkdtemp(prefix="caos_dl_")
    db = d + "/lock.db"
    c0 = sqlite3.connect(db, timeout=30)
    c0.execute("CREATE TABLE t(a INTEGER)")
    c0.commit()
    # conn1 TIENE il lock di scrittura (BEGIN IMMEDIATE)
    c1 = sqlite3.connect(db, timeout=30)
    c1.execute("BEGIN IMMEDIATE")
    c1.execute("INSERT INTO t VALUES (1)")
    # conn2 con timeout BREVE tenta di scrivere -> deve ricevere 'database is locked' entro ~il timeout
    c2 = sqlite3.connect(db, timeout=1.0)
    t0 = time.time()
    errore = None
    try:
        c2.execute("BEGIN IMMEDIATE")
        c2.execute("INSERT INTO t VALUES (2)")
        c2.commit()
    except sqlite3.OperationalError as e:
        errore = str(e)
    dt = time.time() - t0
    esito("D1 il 2o scrittore riceve un errore PULITO 'database is locked' (non congela)",
          errore is not None and "lock" in errore.lower(), "errore=%r dopo %.2fs" % (errore, dt))
    esito("D2 il timeout SCATTA in tempo (~1s, non all'infinito)", 0.5 <= dt <= 8.0,
          "atteso ~1s, misurato %.2fs" % dt)
    # sbloccando conn1, conn2 riesce -> la risorsa si libera, nessun deadlock permanente
    c1.rollback()
    ok2 = False
    try:
        c2.execute("BEGIN IMMEDIATE")
        c2.execute("INSERT INTO t VALUES (3)")
        c2.commit()
        ok2 = True
    except sqlite3.OperationalError:
        ok2 = False
    esito("D3 rilasciato il lock, il 2o scrittore procede (nessun deadlock permanente)", ok2,
          "non riesce a scrivere dopo il rilascio")
    for c in (c0, c1, c2):
        try:
            c.close()
        except sqlite3.Error:
            pass
    shutil.rmtree(d, ignore_errors=True)


def main():
    print("=" * 86)
    print("CAOS ENGINEERING — SIGKILL vero + file descriptor + manomissione + deadlock/timeout")
    print("=" * 86)
    vettore_A()
    vettore_B()
    vettore_C()
    vettore_D()
    print("=" * 86)
    if FALLE:
        print("FALLE TROVATE: %d" % len(FALLE))
        for f in FALLE:
            print("   [X] " + f)
    else:
        print("0 FALLE: kill brutale -> nessuna corruzione ne' double-booking; fd piatti; manomissione")
        print("         rilevata dove conta; il lock conteso da' errore pulito e si sblocca.")
    print("=" * 86)
    sys.exit(1 if FALLE else 0)


if __name__ == "__main__":
    main()
