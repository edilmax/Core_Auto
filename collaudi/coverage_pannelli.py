"""AUDIT MILLIMETRICO dei 3 PANNELLI: ogni endpoint chiamato da host/admin/bunker(super-admin)
-> e' GESTITO dal server? e' TESTATO? Un endpoint chiamato ma NON gestito = tasto morto (bug);
gestito ma NON referenziato dai test = buco di copertura. Esce 1 se trova tasti morti.

Uso:  python collaudi/coverage_pannelli.py     (dalla radice del repo)
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY = os.path.join(ROOT, "deploy")
PANNELLI = {"HOST": "host.html", "ADMIN": "admin.html", "SUPER-ADMIN": "bunker.html"}


def leggi(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


server = leggi(os.path.join(ROOT, "fase83_server.py"))
test_blob = "\n".join(leggi(p) for p in glob.glob(os.path.join(ROOT, "test_*.py")))


def endpoints_di(html):
    eps = set(re.findall(r"/api/[a-zA-Z0-9_/-]+", html))
    return sorted({e.rstrip("/") for e in eps if len(e) > 5})


def gestito(ep):
    return ('"%s"' % ep) in server or ("'%s'" % ep) in server or ep in server


def testato(ep):
    return ep in test_blob


morti_totali, buchi_totali = [], []
print("=" * 78)
print("AUDIT COPERTURA DEI 3 PANNELLI — ogni tasto -> endpoint -> gestito? testato?")
print("=" * 78)
for nome, file in PANNELLI.items():
    eps = endpoints_di(leggi(os.path.join(DEPLOY, file)))
    morti = [e for e in eps if not gestito(e)]
    buchi = [e for e in eps if gestito(e) and not testato(e)]
    ok = len(eps) - len(morti) - len(buchi)
    print("\n%s (%s): %d endpoint | gestiti+testati %d | MORTI %d | non testati %d"
          % (nome, file, len(eps), ok, len(morti), len(buchi)))
    if morti:
        print("  TASTI MORTI (endpoint inesistente): " + ", ".join(morti))
    if buchi:
        print("  NON TESTATI: " + ", ".join(buchi))
    morti_totali += morti
    buchi_totali += buchi

print("\n" + "=" * 78)
print("TOTALE: tasti morti=%d | endpoint non testati=%d" % (len(morti_totali), len(buchi_totali)))
if morti_totali:
    print("ROSSO: ci sono bottoni che chiamano endpoint inesistenti.")
    sys.exit(1)
print("OK: nessun tasto morto — ogni controllo dei pannelli mappa a una funzione reale del server.")
sys.exit(0)
