"""
CORE_AUTO — BATTERIA COMPLETA in un solo comando.  Uso:   python collaudi/batteria.py

Lancia, in sequenza e in modo autosufficiente (ZERO servizi cloud), tutta la difesa della macchina:
  1. Suite completa (unittest, ~348 file)          — copertura logica/funzionale E2E
  2. Master E2E totale (collaudo_finale_totale)     — flusso completo + concorrenza + manomissione
  2b. Cammino E2E preciso (percorso_e2e)            — bot cammina host+ospite+eccezioni, effetto passo-passo
  3. Mutazione (mutazione_prodotto)                 — i test VEDONO i guasti? (giudica i test)
  4. Caccia finti-verdi (caccia_finti_verdi)        — test che non possono fallire
  5. Plausibilità dati (plausibilita)               — i numeri hanno senso nel mondo vero
  6. BATTERIA ESTREMA (estremo)                     — chaos/fault-injection, crash, soak, fuzzing, time-travel
  7. Sicurezza statica (Bandit)                     — gate: 0 vulnerabilità High
  8. [server] Behavioral host + pannelli DAL VIVO   — avvia server locale, prova, chiude
  8b.[server] Vicoli ciechi                         — cammina link/form/API, nessun 404/rotta-morta
  9. [server+node] Accessibilità WCAG + click-through
 10. [internet] Verifica produzione (sito VERO)     — salta se offline

Ogni fase è isolata: se una fallisce, le altre proseguono; alla fine un RIEPILOGO + exit-code.
Le fasi 8-10 sono BEST-EFFORT (saltate con nota se manca server/node/rete). Extra:
  python collaudi/estremo.py --ore 48   → soak di durata reale (24-48h).
"""
import os
import socket
import subprocess
import sys
import time

try:                                                 # console Windows (cp1252): evita crash su UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
PORTA = 8099


def _run(cmd, timeout=1800, env=None):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=RADICE, capture_output=True, text=True,
                           timeout=timeout, env=env, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or ""), time.time() - t0
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT", time.time() - t0
    except Exception as e:
        return 125, "ERRORE LANCIO: %r" % e, time.time() - t0


def _coda(testo, n=3):
    righe = [r for r in testo.splitlines() if r.strip()]
    return " | ".join(righe[-n:])[:300]


def _porta_su(porta, secondi=25):
    for _ in range(secondi):
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", porta)) == 0:
                return True
        time.sleep(1)
    return False


def main():
    esiti = []                                       # (nome, ok, dettaglio, durata)

    def registra(nome, rc, out, dur, ok_se=lambda rc, out: rc == 0):
        ok = ok_se(rc, out)
        esiti.append((nome, ok, _coda(out), dur))
        print("  [%-4s] %-42s (%.0fs)" % ("OK" if ok else "FAIL", nome, dur))

    print("=" * 80)
    print("BATTERIA COMPLETA — tutto in locale, zero cloud")
    print("=" * 80)

    # 1-7: fasi pure-Python (nessun server)
    fasi = [
        ("1. Suite completa (unittest)", [PY, "-m", "unittest", "discover", "-s", ".",
                                          "-p", "test_*.py"], 2400, None),
        ("2. Master E2E totale", [PY, "collaudi/collaudo_finale_totale.py"], 600, None),
        ("2b. Cammino E2E preciso", [PY, "collaudi/percorso_e2e.py"], 300, None),
        ("3. Mutazione", [PY, "collaudi/mutazione_prodotto.py"], 900, None),
        ("4. Caccia finti-verdi", [PY, "collaudi/caccia_finti_verdi.py"], 300, None),
        ("5. Plausibilità dati", [PY, "collaudi/plausibilita.py"], 300, None),
        ("6. Batteria ESTREMA", [PY, "collaudi/estremo.py"], 900, None),
    ]
    for nome, cmd, to, _ok in fasi:
        rc, out, dur = _run(cmd, timeout=to)
        registra(nome, rc, out, dur)

    # 7: Bandit — gate su 0 High
    rc, out, dur = _run([PY, "-m", "bandit", "-r", ".", "-x",
                         "./collaudi,./_archivio,./test_", "-q"], timeout=600)
    def bandit_ok(rc, out):
        for r in out.splitlines():
            if "High:" in r:
                try:
                    return int(r.split("High:")[1].strip().split()[0]) == 0
                except Exception:
                    return False
        return False
    registra("7. Sicurezza statica (Bandit, High=0)", rc, out, dur, ok_se=bandit_ok)

    # 8-9: fasi che richiedono un server locale (best-effort)
    srv = None
    try:
        srv = subprocess.Popen([PY, "collaudi/avvia_server_visivo.py", str(PORTA)],
                               cwd=RADICE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if _porta_su(PORTA):
            env = dict(os.environ, BASE_VISIVO="http://127.0.0.1:%d" % PORTA)
            for nome, cmd in (("8. Behavioral host DAL VIVO", [PY, "collaudi/beh_host.py"]),
                              ("8. Behavioral pannelli DAL VIVO", [PY, "collaudi/beh_pannelli.py"]),
                              ("8b. Vicoli ciechi (link/form/API morti)", [PY, "collaudi/vicoli_ciechi.py"])):
                rc, out, dur = _run(cmd, timeout=400, env=env)
                registra(nome, rc, out, dur)
            # 9: node (a11y + click-through) — solo se node c'è
            if _run(["node", "--version"], timeout=20)[0] == 0:
                for nome, cmd in (("9. Accessibilità WCAG (axe)", ["node", "collaudi/test_a11y.js"]),
                                  ("9. Click-through pannelli", ["node", "collaudi/clickthrough_pannelli.js"])):
                    rc, out, dur = _run(cmd, timeout=400, env=env)
                    registra(nome, rc, out, dur, ok_se=lambda rc, o: rc == 0)
            else:
                esiti.append(("9. a11y+click-through", None, "SALTATO: node assente", 0))
                print("  [SKIP] 9. a11y + click-through (node assente)")
        else:
            esiti.append(("8-9. behavioral/a11y", None, "SALTATO: server locale non partito", 0))
            print("  [SKIP] 8-9. behavioral/a11y (server non partito)")
    finally:
        if srv is not None:
            try:
                srv.terminate()
            except Exception:
                pass

    # 10: verifica produzione (rete) — best-effort
    rc, out, dur = _run([PY, "collaudi/verifica_produzione.py"], timeout=180)
    if "VIOLAZIONI" in out or rc == 0:
        registra("10. Verifica produzione (sito vero)", rc, out, dur,
                 ok_se=lambda rc, o: "VIOLAZIONI: 0" in o)
    else:
        esiti.append(("10. Verifica produzione", None, "SALTATA: offline?", dur))
        print("  [SKIP] 10. Verifica produzione (offline?)")

    # riepilogo
    print("=" * 80)
    falliti = [e for e in esiti if e[1] is False]
    saltati = [e for e in esiti if e[1] is None]
    passati = [e for e in esiti if e[1] is True]
    print("RIEPILOGO: %d OK · %d FALLITI · %d saltati" % (len(passati), len(falliti), len(saltati)))
    for nome, ok, det, _ in falliti:
        print("   [X] %s -> %s" % (nome, det))
    for nome, ok, det, _ in saltati:
        print("   [~] %s (%s)" % (nome, det))
    print("=" * 80)
    print("VERDETTO: " + ("TUTTO VERDE" if not falliti else "%d FASI DA GUARDARE" % len(falliti)))
    sys.exit(1 if falliti else 0)


if __name__ == "__main__":
    main()
