"""CACCIA AI FINTI VERDI — un test che non puo' fallire e' peggio di nessun test.

Un test verde da' sicurezza. Se e' verde per costruzione — perche' non asserisce nulla,
perche' e' saltato, perche' un `except` si mangia l'errore, perche' la sua guardia e' un
`True` scritto a mano — quella sicurezza e' FALSA, ed e' peggio del non avere il test:
si smette di guardare proprio dove si crede di essere coperti.

Questo strumento cerca, in TUTTA la suite e in TUTTI i collaudi:

  F1  TEST SALTATI          - skipTest/skipIf/skipUnless: quanti e perche'
  F2  TEST SENZA ASSERZIONI - metodi `test_*` che non verificano niente
  F3  ERRORI INGOIATI       - `except: pass` dentro i test, che nasconde il fallimento
  F4  GUARDIE COSTANTI      - `assertTrue(True)`, `check(..., True)`: non possono fallire
  F5  BASELINE COMPIACENTI  - elenchi di eccezioni che si auto-creano accettando tutto
  F6  TEST VUOTI            - corpo `pass` o solo docstring

Non e' un test: e' un'ispezione. Stampa cio' che trova e lascia il giudizio a chi legge,
perche' alcune di queste cose sono legittime (uno `skip` motivato, un `except` che e'
esso stesso l'oggetto della prova). Cio' che NON e' legittimo e' non saperlo.
"""
import ast
import io
import os
import re
import sys

try:  # Windows: console cp1252 non regge box-drawing/emoji -> uscita UTF-8 tollerante
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)

SOSPETTI = {"F1": [], "F2": [], "F3": [], "F4": [], "F5": [], "F6": []}

ASSERZIONI = re.compile(r"\b(assert\w*|check|self\.fail|pytest\.raises|VIOL\.append)\b")


def _corpo_vuoto(nodo):
    corpo = [n for n in nodo.body
             if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                     and isinstance(n.value.value, str))]
    return not corpo or all(isinstance(n, ast.Pass) for n in corpo)


def ispeziona(percorso):
    rel = os.path.relpath(percorso, REPO).replace("\\", "/")
    try:
        testo = io.open(percorso, encoding="utf-8").read()
        albero = ast.parse(testo)
    except Exception:
        return
    righe = testo.splitlines()

    for nodo in ast.walk(albero):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not nodo.name.startswith("test"):
            continue
        sorgente = "\n".join(righe[nodo.lineno - 1:getattr(nodo, "end_lineno", nodo.lineno)])

        if _corpo_vuoto(nodo):
            SOSPETTI["F6"].append("%s:%d %s" % (rel, nodo.lineno, nodo.name))
            continue
        if "skipTest" in sorgente:
            motivo = re.search(r"skipTest\(([^)]{0,70})", sorgente)
            SOSPETTI["F1"].append("%s:%d %s -> %s"
                                  % (rel, nodo.lineno, nodo.name,
                                     motivo.group(1) if motivo else "?"))
        if not ASSERZIONI.search(sorgente):
            # Prima di gridare: molti test DELEGANO a un aiutante (`self._tempesta(...)`,
            # `self._run(...)`) che contiene le verifiche, oppure provano che una
            # chiamata NON SOLLEVA — che e' una verifica vera. Si guarda dentro gli
            # aiutanti chiamati, un livello. Resta sospetto solo cio' che non verifica
            # niente ne' direttamente ne' tramite un aiutante.
            aiutanti = set(re.findall(r"self\.(_\w+)\s*\(", sorgente))
            aiutanti |= set(re.findall(r"(_?[a-z]\w*)\s*\(", sorgente))
            delega = False
            for altra in ast.walk(albero):
                if (isinstance(altra, ast.FunctionDef)
                        and altra.name in aiutanti
                        and not altra.name.startswith("test")):
                    corpo2 = "\n".join(
                        righe[altra.lineno - 1:getattr(altra, "end_lineno",
                                                       altra.lineno)])
                    if ASSERZIONI.search(corpo2):
                        delega = True
                        break
            if not delega:
                SOSPETTI["F2"].append("%s:%d %s" % (rel, nodo.lineno, nodo.name))

    # decoratori di salto sull'intera classe o sul metodo
    for m in re.finditer(r"@unittest\.skip\w*\(([^)]{0,80})", testo):
        n = testo[:m.start()].count("\n") + 1
        # Un decoratore CITATO in un commento non salta niente: prenderlo per vero
        # e' un falso allarme, e i falsi allarmi fanno ignorare la guardia.
        if righe[n - 1].lstrip().startswith("#"):
            continue
        SOSPETTI["F1"].append("%s:%d (decoratore) -> %s" % (rel, n, m.group(1)))

    # except che ingoia dentro un file di test/collaudo
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.ExceptHandler):
            solo_pass = all(isinstance(x, ast.Pass) for x in nodo.body)
            if solo_pass and nodo.type is None:
                SOSPETTI["F3"].append("%s:%d  except NUDO che ingoia tutto"
                                      % (rel, nodo.lineno))

    # guardie che non possono fallire
    for m in re.finditer(r"assertTrue\(\s*True\s*\)|assertFalse\(\s*False\s*\)"
                         r"|assertEqual\(\s*(\d+)\s*,\s*\1\s*\)", testo):
        n = testo[:m.start()].count("\n") + 1
        SOSPETTI["F4"].append("%s:%d  %s" % (rel, n, m.group(0)[:40]))
    for m in re.finditer(r"check\(\s*\"[^\"]+\"\s*,\s*\"[^\"]+\"\s*,\s*True\s*[,)]", testo):
        n = testo[:m.start()].count("\n") + 1
        SOSPETTI["F4"].append("%s:%d  check(..., True) letterale" % (rel, n))

    # baseline che si auto-creano
    if "baseline" in testo.lower() and "os.path.exists" in testo:
        if re.search(r"else:\s*\n\s*io\.open\([^)]*BASE[^)]*\"w\"", testo):
            SOSPETTI["F5"].append("%s  crea la baseline da sola al primo giro "
                                  "(accetta tutto senza che nessuno guardi)" % rel)


if __name__ == "__main__":
    for cartella in (REPO, os.path.join(REPO, "collaudi")):
        for f in sorted(os.listdir(cartella)):
            if f.endswith(".py") and (f.startswith("test_") or f.startswith("collaudo")
                                      or f.startswith("audit") or f.startswith("super")
                                      or f.startswith("e2e") or f.startswith("stress")
                                      or f.startswith("verifica")):
                ispeziona(os.path.join(cartella, f))

    titoli = {
        "F1": "TEST SALTATI (non girano mai: verdi per assenza)",
        "F2": "TEST SENZA NESSUNA ASSERZIONE (non verificano niente)",
        "F3": "ERRORI INGOIATI DA UN except NUDO (il fallimento sparisce)",
        "F4": "GUARDIE COSTANTI (non possono fallire per costruzione)",
        "F5": "BASELINE COMPIACENTI (si auto-creano accettando tutto)",
        "F6": "TEST VUOTI (corpo `pass` o sola docstring)",
    }
    print("=" * 78)
    print("CACCIA AI FINTI VERDI")
    print("=" * 78)
    totale = 0
    for k in ("F1", "F2", "F3", "F4", "F5", "F6"):
        v = SOSPETTI[k]
        totale += len(v)
        print("\n%s  %s: %d" % (k, titoli[k], len(v)))
        for x in v[:25]:
            print("    " + x)
        if len(v) > 25:
            print("    ... e altri %d" % (len(v) - 25))
    print("\n" + "=" * 78)
    print("SOSPETTI TOTALI: %d  (da leggere uno per uno: non tutti sono difetti)" % totale)
    sys.exit(0)
