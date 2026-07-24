"""COLLAUDO COMPORTAMENTALE LIVE dei pannelli: la funzione fa ESATTAMENTE cio' che dichiara.
Serve il server visivo:  python collaudi/avvia_server_visivo.py 8099  poi  python collaudi/beh_pannelli.py
Prova end-to-end: blocco calendario -> data non prenotabile (istantaneo) + iCal import; admin sospende
(richiede super-admin) -> sparisce dalla ricerca -> riattiva; super-admin doppia chiave + rampa commissioni.
"""
import json, os, sys, urllib.request, urllib.parse, datetime
BASE = os.environ.get("BASE_VISIVO", "http://127.0.0.1:8099")
def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items(): req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode(); return r.status, (json.loads(raw) if raw[:1] in "{[" else raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(); return e.code, (json.loads(raw) if raw[:1] in "{[" else raw)

esiti = []
def check(nome, cond, extra=""):
    esiti.append(cond); print(("  OK   " if cond else "  ROSSO ") + nome + (" | " + extra if extra else ""))

TOK = call("POST", "/api/host/login", {"email": "host@visivo.it", "password": "password1"})[1]["token"]
HH = {"X-Host-Token": TOK}; AH = {"X-Admin-Key": "ak"}
BS = call("POST", "/api/bunker/login", {"codice": "SuperPw@1"}, AH)[1].get("sessione", "")
ABH = {"X-Admin-Key": "ak", "X-Bunker-Session": BS}   # admin + sessione super-admin
oggi = datetime.date.today()
d_in = (oggi + datetime.timedelta(days=40)).isoformat(); d_out = (oggi + datetime.timedelta(days=42)).isoformat()
SLUG = "attico-roma-visivo"
def in_catalogo():
    return SLUG in json.dumps(call("GET", "/api/catalogo?" + urllib.parse.urlencode({"citta": "Roma"}))[1])
def prenotabile():
    s, r = call("POST", "/api/concierge/quote", {"alloggio_id": SLUG, "check_in": d_in, "check_out": d_out, "party": 2})
    return s == 200 and isinstance(r, dict) and not r.get("errore")

print("== HOST · BLOCCO CALENDARIO (chiuso=manutenzione) -> effetto ISTANTANEO su quote ==")
check("prima: la data e' prenotabile", prenotabile())
s, _ = call("POST", "/api/host/disponibilita", {"alloggio_id": SLUG, "giorno": d_in, "unita_totali": 3, "prezzo_netto_cents": 18000, "chiuso": True}, HH)
check("blocco data accettato (chiuso=True)", s == 200, "HTTP %s" % s)
check("DOPO il blocco: la stessa data NON e' piu' prenotabile (istantaneo)", not prenotabile())
s, _ = call("POST", "/api/host/disponibilita", {"alloggio_id": SLUG, "giorno": d_in, "unita_totali": 3, "prezzo_netto_cents": 18000, "chiuso": False}, HH)
check("SBLOCCO: la data torna prenotabile (istantaneo)", prenotabile())

print("== HOST · flusso iCal (import feed esterno) blocca le date ==")
gg = (oggi + datetime.timedelta(days=44))
ics = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART;VALUE=DATE:%s\nDTEND;VALUE=DATE:%s\nEND:VEVENT\nEND:VCALENDAR" % (
    gg.strftime("%Y%m%d"), (gg + datetime.timedelta(days=1)).strftime("%Y%m%d"))
s, ir = call("POST", "/api/host/ical", {"alloggio_id": SLUG, "ical": ics}, HH)
check("import iCal blocca almeno 1 giorno", s == 200 and isinstance(ir, dict) and ir.get("giorni_bloccati", 0) >= 1, "HTTP %s %s" % (s, str(ir)[:50]))

print("== ADMIN · SOSPENSIONE (richiede super-admin) -> sparisce dalla ricerca pubblica ==")
check("annuncio visibile in ricerca PRIMA", in_catalogo())
s403, _ = call("POST", "/api/admin/alloggio_stato", {"slug": SLUG, "stato": "sospeso"}, AH)   # senza bunker
check("SICUREZZA: sospendere senza super-admin e' NEGATO (403)", s403 == 403, "HTTP %s" % s403)
s, _ = call("POST", "/api/admin/alloggio_stato", {"slug": SLUG, "stato": "sospeso"}, ABH)      # con bunker
check("con super-admin la sospensione passa (200)", s == 200, "HTTP %s" % s)
check("DOPO sospensione: annuncio NON in ricerca pubblica", not in_catalogo())
call("POST", "/api/admin/alloggio_stato", {"slug": SLUG, "stato": "pubblicato"}, ABH)
check("RIATTIVAZIONE: annuncio torna visibile", in_catalogo())

print("== SUPER-ADMIN · doppia chiave: la sessione e' viva ==")
check("sessione bunker ottenuta (2a chiave)", bool(BS) and len(BS) > 8)
s, sc = call("GET", "/api/bunker/scaglioni_host", None, ABH)
check("parametro finanziario globale leggibile (rampa commissioni)", s == 200, "HTTP %s" % s)

n_ok = sum(esiti); print("\n== COMPORTAMENTALE LIVE: %d/%d verdi ==" % (n_ok, len(esiti)))
sys.exit(0 if n_ok == len(esiti) else 1)
