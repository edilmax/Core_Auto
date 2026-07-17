# -*- coding: utf-8 -*-
"""Ispettore totale BookinVIP: analizza OGNI riga di OGNI file del progetto in locale
e produce un verbale compatto dei soli SOSPETTI, raggruppati per classe di bug.
Classi tarate sulle 36 famiglie di bug reali già trovate nel progetto."""
import ast, os, re, sys, json, builtins

ROOT = os.path.dirname(os.path.abspath(__file__)) or "."
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console Windows cp1252
except Exception:
    pass
finding = []  # (sev, classe, file, line, msg)

def add(sev, classe, f, ln, msg):
    finding.append((sev, classe, os.path.basename(f), ln, msg[:160]))

PY_BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__", "__spec__", "__builtins__", "__loader__", "__annotations__"}

class Vis(ast.NodeVisitor):
    def __init__(self, f, src_lines, is_test):
        self.f = f; self.L = src_lines; self.is_test = is_test
        self.money_file = any(re.search(r"cents|centesimi|payout|importo", l, re.I) for l in src_lines)

    def visit_Call(self, n):
        fn = n.func
        name = ""
        if isinstance(fn, ast.Name): name = fn.id
        elif isinstance(fn, ast.Attribute): name = fn.attr
        # soldi in float
        if name == "float" and self.money_file and not self.is_test:
            line = self.L[n.lineno-1]
            if re.search(r"cents|importo|prezzo|payout|comm|tassa|netto|rimbors", line, re.I):
                add("ALTA", "money-float", self.f, n.lineno, line.strip())
        if name == "round" and not self.is_test:
            line = self.L[n.lineno-1]
            if re.search(r"cents|importo|payout|netto|rimbors|comm(?!ent)", line, re.I):
                add("ALTA", "money-round", self.f, n.lineno, line.strip())
        # SQL costruito con f-string/format/%
        if name in ("execute", "executemany") and n.args:
            a0 = n.args[0]
            if isinstance(a0, ast.JoinedStr):
                add("ALTA", "sql-fstring", self.f, n.lineno, self.L[n.lineno-1].strip())
            elif isinstance(a0, ast.BinOp) and isinstance(a0.op, (ast.Add, ast.Mod)):
                add("ALTA", "sql-concat", self.f, n.lineno, self.L[n.lineno-1].strip())
            elif isinstance(a0, ast.Call) and isinstance(a0.func, ast.Attribute) and a0.func.attr == "format":
                add("ALTA", "sql-format", self.f, n.lineno, self.L[n.lineno-1].strip())
        # urlopen senza timeout
        if name == "urlopen":
            if not any(k.arg == "timeout" for k in n.keywords):
                add("MEDIA", "rete-no-timeout", self.f, n.lineno, self.L[n.lineno-1].strip())
        # Request esterna senza User-Agent (classe Groq/IndexNow)
        if name == "Request":
            hdr = [k for k in n.keywords if k.arg == "headers"]
            if hdr and isinstance(hdr[0].value, ast.Dict):
                keys = [getattr(k, "value", None) for k in hdr[0].value.keys if isinstance(k, ast.Constant)]
                if keys and not any("user-agent" == str(k).lower() for k in keys):
                    add("BASSA", "rete-no-ua", self.f, n.lineno, self.L[n.lineno-1].strip())
        self.generic_visit(n)

    def visit_ExceptHandler(self, n):
        # except muto: pass/continue senza log (classe error-boundary)
        if not self.is_test and len(n.body) == 1 and isinstance(n.body[0], (ast.Pass, ast.Continue)):
            add("MEDIA", "except-muto", self.f, n.lineno, self.L[n.lineno-1].strip())
        self.generic_visit(n)

def nomi_indefiniti(f, src):
    """Nomi globali usati ma mai definiti/importati nel modulo (classe bug #34 money() JS... versione py)."""
    out = []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        add("ALTA", "SINTASSI", f, e.lineno or 0, str(e.msg)); return out
    defined = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): defined.add(n.name)
        elif isinstance(n, ast.Import):
            for a in n.names: defined.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            for a in n.names: defined.add(a.asname or a.name)
        elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            tgts = n.targets if isinstance(n, ast.Assign) else [n.target]
            for t in tgts:
                for x in ast.walk(t):
                    if isinstance(x, ast.Name): defined.add(x.id)
        elif isinstance(n, (ast.For, ast.comprehension)):
            t = n.target
            for x in ast.walk(t):
                if isinstance(x, ast.Name): defined.add(x.id)
        elif isinstance(n, ast.With):
            for it in n.items:
                if it.optional_vars:
                    for x in ast.walk(it.optional_vars):
                        if isinstance(x, ast.Name): defined.add(x.id)
        elif isinstance(n, ast.ExceptHandler):
            if n.name: defined.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            defined.update(n.names)
        elif isinstance(n, ast.Lambda):
            for a in n.args.args + n.args.kwonlyargs: defined.add(a.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            pass
    # parametri funzione
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = n.args
            for p in a.args + a.kwonlyargs + a.posonlyargs: defined.add(p.arg)
            if a.vararg: defined.add(a.vararg.arg)
            if a.kwarg: defined.add(a.kwarg.arg)
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            if n.id not in defined and n.id not in PY_BUILTINS:
                out.append((n.id, n.lineno))
    return out

RE_UPDATE_NOWHERE = re.compile(r'"\s*UPDATE\s+\w+\s+SET\s+[^"]*"', re.I)
RE_DELETE_NOWHERE = re.compile(r'"\s*DELETE\s+FROM\s+\w+\s*"', re.I)

def scan_py(f):
    src = open(f, encoding="utf-8", errors="replace").read()
    lines = src.splitlines()
    is_test = os.path.basename(f).startswith("test_")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        add("ALTA", "SINTASSI", f, e.lineno or 0, str(e.msg)); return
    Vis(f, lines, is_test).visit(tree)
    if not is_test:
        for nome, ln in nomi_indefiniti(f, src):
            add("ALTA", "nome-indefinito", f, ln, nome)
        for i, l in enumerate(lines, 1):
            if RE_UPDATE_NOWHERE.search(l) and "WHERE" not in l.upper():
                add("ALTA", "sql-update-senza-where", f, i, l.strip())
            if RE_DELETE_NOWHERE.search(l) and "WHERE" not in l.upper():
                add("ALTA", "sql-delete-senza-where", f, i, l.strip())
            if re.search(r"\bdatetime\.now\(\)|\bdate\.today\(\)", l) and "utc" not in l.lower():
                add("BASSA", "orario-locale", f, i, l.strip())
            if ":memory:" in l:
                add("MEDIA", "sqlite-memory", f, i, l.strip())

RE_INTERP = re.compile(r"\$\{([^}]+)\}")

def scan_html(f):
    src = open(f, encoding="utf-8", errors="replace").read()
    lines = src.splitlines()
    for i, l in enumerate(lines, 1):
        # interpolazione JS in HTML senza escape (classe XSS #1-4)
        if "innerHTML" in l or "insertAdjacentHTML" in l:
            for m in RE_INTERP.finditer(l):
                e = m.group(1)
                if not re.search(r"\besc\w*\(|encodeURIComponent|Number\(|\.length|_http", e):
                    add("ALTA", "xss-interp", f, i, e.strip())
        if re.search(r"\)\s*\)\s*\.json\(\)", l):
            add("MEDIA", "fetch-json-diretto", f, i, l.strip())
        for m in RE_INTERP.finditer(l):
            e = m.group(1)
            if re.search(r"onclick|onerror|href", l) and not re.search(r"\besc\w*\(|encodeURIComponent", e):
                if not re.search(r"^\s*(idx|i|n|id)\b|\(\)", e):
                    add("MEDIA", "xss-attr", f, i, (e + " @ " + l.strip()[:80]))

grafo = {}
def grafo_modulo(f):
    src = open(f, encoding="utf-8", errors="replace").read()
    try: tree = ast.parse(src)
    except SyntaxError: return
    deps = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.startswith("fase"): deps.add(a.name.split("_")[0])
        elif isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("fase"):
            deps.add(n.module.split("_")[0])
    grafo[os.path.basename(f)] = sorted(deps)

def main():
    py, html = [], []
    for nome in sorted(os.listdir(ROOT)):
        p = os.path.join(ROOT, nome)
        if nome.endswith(".py") and nome != os.path.basename(__file__): py.append(p)
    dep = os.path.join(ROOT, "deploy")
    for nome in sorted(os.listdir(dep)):
        if nome.endswith(".html"): html.append(os.path.join(dep, nome))
    for f in py:
        scan_py(f)
        if not os.path.basename(f).startswith("test_"): grafo_modulo(f)
    for f in html: scan_html(f)
    sev_ord = {"ALTA": 0, "MEDIA": 1, "BASSA": 2}
    finding.sort(key=lambda x: (sev_ord[x[0]], x[1], x[2], x[3]))
    # verbale compatto
    from collections import Counter
    print("FILE ANALIZZATI: %d py + %d html | RIGHE: %d" % (
        len(py), len(html),
        sum(len(open(f, encoding='utf-8', errors='replace').read().splitlines()) for f in py + html)))
    print("TOTALE SOSPETTI:", len(finding))
    for k, v in Counter("%s/%s" % (s, c) for s, c, *_ in finding).most_common():
        print("  %-28s %d" % (k, v))
    print("---DETTAGLIO (ALTA + MEDIA)---")
    for s, c, f, ln, msg in finding:
        if s in ("ALTA", "MEDIA"):
            print("%s %s %s:%s %s" % (s, c, f, ln, msg))
    # grafo delle dipendenze: --grafo lo stampa (JSON), altrimenti solo il conteggio
    if "--grafo" in sys.argv:
        print(json.dumps(grafo, indent=0, sort_keys=True))
    print("---grafo: %d moduli mappati (usa --grafo per stamparlo)---" % len(grafo))

if __name__ == "__main__":
    main()
