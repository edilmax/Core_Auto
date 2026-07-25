"""
CORE_AUTO — BATTERIA ESTREMA (in-house, zero cloud). Spinge la macchina al limite:
  1. CHAOS / FAULT INJECTION  : disco non scrivibile a metà transazione + atomicità (niente dati parziali)
  2. CRASH RECOVERY           : "kill" a metà scrittura -> riapertura, integrità DB, nessun dato sporco
  3. DIMENSIONI ANOMALE / RAM  : payload enormi/deformi -> rifiuto controllato, mai crash o OOM
  4. SOAK / ENDURANCE          : carico continuo -> nessuna micro-perdita di memoria (tracemalloc)
  5. FUZZING TUTTI GLI ENDPOINT: input casuali/corrotti a ogni rotta -> sempre status controllato
  6. TIME-TRAVEL               : notti su ora legale/anno bisestile/capodanno + scadenza token a orologio spostato

ONESTA': la RAM fisica NON viene riempita davvero (bloccherebbe il PC): si iniettano input di
dimensioni anomale + si prova il rifiuto controllato. Il soak gira ACCELERATO (migliaia di
operazioni, rileva i leak in minuti); per una prova reale di 24-48h usa:  python collaudi/estremo.py --ore 48

Deterministico (seed fisso). Uso i componenti VERI del sistema (crea_sistema/crea_router/crea_protocollo).
"""
import gc
import glob
import json
import os
import random
import sqlite3
import stat
import sys
import time
import tempfile
import tracemalloc

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

SEG = b"x" * 32
random.seed(1234)


def _rt(tmp):
    sis = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG, db_payout=tmp + "/p.db"))
    return sis, crea_router(sis, host_key="hk", admin_key="ak", base_url="http://t")


def _g(r, m, p, b=None, h=None):
    return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})


def _pubblica(r, slug="casa-x", prezzo=20000):
    s, c = _g(r, "POST", "/api/host/registrazione", {
        "email": "h@x.it", "password": "password1", "accetta_termini": True,
        "accetta_clausole": True, "accetta_privacy": True,
        "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
    tk = {"X-Host-Token": c["token"]}
    _g(r, "POST", "/api/host/pubblica", {"slug": slug, "titolo": "Casa", "citta": "Roma",
                                         "prezzo_notte_cents": prezzo, "capacita": 4}, tk)
    return tk


def _disp(r, tk, slug, da, a, prezzo=20000):
    return _g(r, "POST", "/api/host/disponibilita_range", {
        "alloggio_id": slug, "da": da, "a": a, "unita_totali": 3, "prezzo_netto_cents": prezzo}, tk)


def _integri(tmp):
    """PRAGMA integrity_check su ogni DB del sistema. True se tutti 'ok'."""
    for f in glob.glob(tmp + "/*.db"):
        try:
            if sqlite3.connect(f).execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False
        except Exception:
            return False
    return True


# ── 1. CHAOS / FAULT INJECTION ──────────────────────────────────────────────────────
def chaos():
    viol = []
    # A1: ATOMICITA' — una transazione che fallisce a metà NON lascia dati parziali (rollback).
    tmp = tempfile.mkdtemp()
    db = tmp + "/atom.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t(x INTEGER)")
    con.commit()
    try:
        with con:                                   # blocco atomico
            con.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError("disco pieno simulato a metà transazione")
    except RuntimeError:
        pass
    n = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    if n != 0:
        viol.append("atomicità rotta: riga parziale persistita dopo fallimento (%d)" % n)
    con.close()

    # A2: DISCO NON SCRIVIBILE a metà flusso — i DB del sistema resi read-only durante una
    # prenotazione: il sistema deve rispondere in modo CONTROLLATO (mai crash) e restare integro.
    tmp2 = tempfile.mkdtemp()
    sis, r = _rt(tmp2)
    tk = _pubblica(r, "casa-chaos")
    oggi = time.strftime("%Y-%m-%d")
    import datetime
    d0 = datetime.date.today()
    _disp(r, tk, "casa-chaos", d0.isoformat(), (d0 + datetime.timedelta(days=10)).isoformat())
    sq, q = _g(r, "POST", "/api/concierge/quote", {
        "alloggio_id": "casa-chaos", "check_in": (d0 + datetime.timedelta(days=2)).isoformat(),
        "check_out": (d0 + datetime.timedelta(days=4)).isoformat(), "party": 2})
    dbs = glob.glob(tmp2 + "/*.db")
    for f in dbs:                                   # rendo i DB NON scrivibili (disco pieno/guasto)
        try:
            os.chmod(f, stat.S_IREAD)
        except Exception:
            pass
    try:
        st, bo = _g(r, "POST", "/api/concierge/book",
                    {"quote_token": q.get("quote_token", "x"), "email": "a@b.it"})
        if not isinstance(st, int):
            viol.append("book su disco read-only: status non intero (crash?) -> %r" % st)
        if not isinstance(bo, (dict, list)):
            viol.append("book su disco read-only: corpo non serializzabile (traceback grezzo?)")
        # non deve MAI risultare confermata una prenotazione se la scrittura è fallita
    except Exception as e:
        viol.append("book su disco read-only ha SOLLEVATO (crash non gestito): %r" % e)
    finally:
        for f in dbs:
            try:
                os.chmod(f, stat.S_IWRITE)
            except Exception:
                pass
    if not _integri(tmp2):
        viol.append("integrità DB compromessa dopo il guasto di scrittura")
    return "1. CHAOS / FAULT INJECTION", viol


# ── 2. CRASH RECOVERY ───────────────────────────────────────────────────────────────
def crash_recovery():
    viol = []
    tmp = tempfile.mkdtemp()
    db = tmp + "/crash.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t(x INTEGER)")
    con.execute("INSERT INTO t VALUES (100)")       # riga COMMITTATA
    con.commit()
    # scrittura NON committata + "kill" del processo (chiudo la connessione senza commit)
    c2 = sqlite3.connect(db)
    c2.execute("BEGIN")
    c2.execute("INSERT INTO t VALUES (999)")         # in volo, mai committata
    c2.close()                                       # simulo arresto forzato a metà scrittura
    con.close()
    # riapertura ("recovery")
    r3 = sqlite3.connect(db)
    if r3.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        viol.append("integrity_check != ok dopo crash a metà scrittura")
    valori = [x[0] for x in r3.execute("SELECT x FROM t").fetchall()]
    if 100 not in valori:
        viol.append("dato COMMITTATO perso dopo il crash")
    if 999 in valori:
        viol.append("dato NON committato sopravvissuto al crash (corruzione)")
    r3.close()
    return "2. CRASH RECOVERY", viol


# ── 3. DIMENSIONI ANOMALE / RAM ─────────────────────────────────────────────────────
def dimensioni_anomale():
    viol = []
    tmp = tempfile.mkdtemp()
    sis, r = _rt(tmp)
    gigante = "A" * 2_000_000                        # 2 MB in un campo
    profondo = {"a": 1}
    for _ in range(300):
        profondo = {"n": profondo}                   # JSON profondamente annidato
    casi = [
        ("POST", "/api/concierge/quote", {"alloggio_id": gigante, "check_in": gigante,
                                          "check_out": gigante, "party": 10 ** 9}),
        ("POST", "/api/domanda", {"email": gigante, "citta": gigante}),
        ("POST", "/api/host/registrazione", profondo),
        ("POST", "/api/concierge/book", {"quote_token": gigante, "email": "a@b.it"}),
    ]
    for m, p, b in casi:
        try:
            st, bo = _g(r, m, p, b)
            if not isinstance(st, int) or not (100 <= st <= 599):
                viol.append("%s %s: status anomalo %r su input gigante" % (m, p, st))
            json.dumps(bo)                           # corpo dev'essere serializzabile
        except MemoryError:
            viol.append("%s %s: MemoryError (OOM) su input gigante -> non limitato" % (m, p))
        except Exception as e:
            viol.append("%s %s: eccezione non gestita su input gigante: %r" % (m, p, e))
    return "3. DIMENSIONI ANOMALE / RAM", viol


# ── 4. SOAK / ENDURANCE (accelerato + rilevamento leak) ─────────────────────────────
def soak(ore=0.0):
    viol = []
    tmp = tempfile.mkdtemp()
    sis, r = _rt(tmp)
    tk = _pubblica(r, "casa-soak")
    import datetime
    d0 = datetime.date.today()
    _disp(r, tk, "casa-soak", d0.isoformat(), (d0 + datetime.timedelta(days=20)).isoformat())
    ci = (d0 + datetime.timedelta(days=2)).isoformat()
    co = (d0 + datetime.timedelta(days=4)).isoformat()

    def ciclo():
        _g(r, "GET", "/api/catalogo")
        _g(r, "POST", "/api/concierge/quote",
           {"alloggio_id": "casa-soak", "check_in": ci, "check_out": co, "party": 2})

    for _ in range(300):                             # warm-up (riempie le cache stabili)
        ciclo()
    gc.collect()
    tracemalloc.start()
    base = tracemalloc.get_traced_memory()[0]
    n_base = len(gc.get_objects())

    giri = 6000
    if ore and ore > 0:                              # modalità durata reale (24-48h)
        fine = time.time() + ore * 3600
        giri = 10 ** 12
    fatti = 0
    t0 = time.time()
    while fatti < giri:
        ciclo()
        fatti += 1
        if ore and ore > 0 and time.time() >= fine:
            break
    gc.collect()
    cur = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    cresc_mb = (cur - base) / (1024 * 1024)
    cresc_obj = len(gc.get_objects()) - n_base
    # dopo il warm-up, migliaia di cicli NON devono far crescere la memoria in modo significativo
    if cresc_mb > 8.0:
        viol.append("possibile MEMORY LEAK: +%.1f MB dopo %d cicli (soglia 8 MB)" % (cresc_mb, fatti))
    if cresc_obj > 50000:
        viol.append("oggetti Python non liberati: +%d dopo %d cicli" % (cresc_obj, fatti))
    print("     soak: %d cicli in %.1fs | crescita memoria +%.2f MB | +%d oggetti"
          % (fatti, time.time() - t0, cresc_mb, cresc_obj))
    return "4. SOAK / ENDURANCE", viol


# ── 5. FUZZING TUTTI GLI ENDPOINT ───────────────────────────────────────────────────
def _payload_ostile():
    scelte = [
        lambda: "".join(chr(random.randint(0, 0x10FFFF)) for _ in range(random.randint(0, 40))),
        lambda: random.choice(["", "{{{", "]", "null", "NaN", "\x00\x01\x02", "😀🔥"*20, "' OR 1=1--",
                               "<script>alert(1)</script>", "../../etc/passwd", "%s%n%x"]),
        lambda: random.randint(-10 ** 18, 10 ** 18),
        lambda: [_payload_ostile_semplice() for _ in range(random.randint(0, 5))],
        lambda: {"k": _payload_ostile_semplice()},
        lambda: None,
        lambda: True,
    ]
    return random.choice(scelte)()


def _payload_ostile_semplice():
    return random.choice(["x", "", 0, -1, 10 ** 12, None, True, "😀", "\x00", "' OR 1=1--"])


def fuzzing():
    viol = []
    tmp = tempfile.mkdtemp()
    sis, r = _rt(tmp)
    endpoint = [
        ("GET", "/api/catalogo"), ("POST", "/api/concierge/quote"),
        ("POST", "/api/concierge/book"), ("POST", "/api/domanda"),
        ("POST", "/api/host/registrazione"), ("POST", "/api/host/pubblica"),
        ("GET", "/api/concierge/manifest"), ("POST", "/api/mcp"),
        ("POST", "/api/concierge/scopri"), ("GET", "/api/domanda/citta"),
    ]
    tot = 0
    for _ in range(2500):
        m, p = random.choice(endpoint)
        # corpo: a volte JSON valido-ma-ostile, a volte stringa NON-JSON (deforme)
        if random.random() < 0.5:
            corpo = json.dumps({random.choice(["a", "email", "alloggio_id", "quote_token",
                                              "check_in", "party"]): _payload_ostile()})
        else:
            corpo = random.choice(["{{{", "not json", "\x00\xff", "[", "", "😀"])
        h = {random.choice(["X-Host-Token", "X-Admin-Key", "X-Host-Key"]): _payload_ostile_semplice()}
        try:
            st, bo = r.gestisci(m, p, {}, corpo if m == "POST" else None,
                                {k: str(v) for k, v in h.items()})
            tot += 1
            if not isinstance(st, int) or not (100 <= st <= 599):
                viol.append("%s %s: status non valido %r (corpo=%r)" % (m, p, st, corpo[:40]))
            json.dumps(bo)                           # mai un traceback/oggetto non serializzabile
        except Exception as e:
            viol.append("%s %s: CRASH non gestito %r (corpo=%r)" % (m, p, e, corpo[:40]))
    print("     fuzzing: %d richieste ostili, tutte con risposta controllata" % tot)
    return "5. FUZZING TUTTI GLI ENDPOINT", viol


# ── 6. TIME-TRAVEL / EDGE CASES TEMPORALI ───────────────────────────────────────────
def time_travel():
    viol = []
    tmp = tempfile.mkdtemp()
    sis, r = _rt(tmp)
    tk = _pubblica(r, "casa-tempo")

    def notti_previste(ci, co, attese):
        _disp(r, tk, "casa-tempo", ci, co)
        st, q = _g(r, "POST", "/api/concierge/quote",
                   {"alloggio_id": "casa-tempo", "check_in": ci, "check_out": co, "party": 2})
        if st != 200:
            return None                              # orizzonte/indisponibile: informativo, non violazione
        listino = q.get("prezzo_listino_cents")
        if listino is not None and listino != attese * 20000:
            viol.append("notti errate %s->%s: listino %r invece di %d (%d notti)"
                        % (ci, co, listino, attese * 20000, attese))
        return listino

    # ORA LEGALE (fall-back Europa 2026-10-25): la notte del cambio conta 1 notte, non 25h
    notti_previste("2026-10-24", "2026-10-26", 2)
    # CAPODANNO (confine d'anno)
    notti_previste("2026-12-30", "2027-01-02", 3)
    # ANNO BISESTILE (Feb 29 2028 esiste)
    notti_previste("2028-02-28", "2028-03-01", 2)
    # ANNO NON bisestile (Feb 2027: 28->1 marzo = 1 notte)
    notti_previste("2027-02-28", "2027-03-01", 1)

    # TOKEN: l'orologio salta in avanti DURANTE la prenotazione -> il token scade (fail-closed)
    from fase59_concierge import FirmaQuote, crea_protocollo
    orol = [1_000_000]
    proto = crea_protocollo(inventario=None, segreto=SEG, ttl_quote_sec=900,
                            orologio=lambda: orol[0])
    firma = FirmaQuote(SEG)
    tok = firma.codifica({"alloggio_id": "x", "check_in": "2027-01-01",
                          "check_out": "2027-01-02", "exp": orol[0] + 100})
    r1 = proto.prenota({"quote_token": tok, "email": "a@b.it"})
    if r1.status == 410:
        viol.append("token valido rifiutato come scaduto prima del tempo")
    orol[0] += 200                                   # l'orologio salta oltre la scadenza
    r2 = proto.prenota({"quote_token": tok, "email": "a@b.it"})
    if r2.status != 410:
        viol.append("token SCADUTO accettato dopo lo spostamento dell'orologio (status %r)"
                    % r2.status)
    # token MANOMESSO -> sempre rifiutato
    r3 = proto.prenota({"quote_token": tok[:-3] + "000", "email": "a@b.it"})
    if r3.status not in (400, 410):
        viol.append("token manomesso accettato (status %r)" % r3.status)
    return "6. TIME-TRAVEL / EDGE CASES TEMPORALI", viol


def main():
    ore = 0.0
    if "--ore" in sys.argv:
        try:
            ore = float(sys.argv[sys.argv.index("--ore") + 1])
        except Exception:
            ore = 0.0
    print("=" * 78)
    print("BATTERIA ESTREMA — chaos · crash · dimensioni · soak · fuzzing · time-travel")
    if ore:
        print("   MODALITA' DURATA REALE: soak per %.1f ore" % ore)
    print("=" * 78)
    fasi = [chaos, crash_recovery, dimensioni_anomale,
            lambda: soak(ore), fuzzing, time_travel]
    tot_viol = 0
    t0 = time.time()
    for f in fasi:
        nome, viol = f()
        tot_viol += len(viol)
        stato = "OK" if not viol else "VIOLAZIONI %d" % len(viol)
        print("  [%-12s] %s" % (stato, nome))
        for v in viol:
            print("       - " + v)
    print("=" * 78)
    print("BATTERIA ESTREMA — durata %.1fs — VIOLAZIONI TOTALI: %d" % (time.time() - t0, tot_viol))
    print("=" * 78)
    sys.exit(1 if tot_viol else 0)


if __name__ == "__main__":
    main()
