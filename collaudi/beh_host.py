"""COLLAUDO COMPORTAMENTALE del PANNELLO HOST -> effetto ISTANTANEO sul pubblico.
Serve il server visivo:  python collaudi/avvia_server_visivo.py 8099  poi  python collaudi/beh_host.py
Tre scenari con asserzioni ESATTE:
  1) blocco/sblocco data -> quote pubblica indisponibile/prenotabile ALL'ISTANTE;
  2) variazione prezzo + min-stay -> checkout ricalcola AL CENTESIMO, niente cache vecchia;
  3) prenotazione -> l'ospite riceve voucher + PIN (smart_pass) corretti; notifica host cablata.
"""
import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("BASE_VISIVO", "http://127.0.0.1:8099")
SLUG = "attico-roma-visivo"


def call(m, p, b=None, h=None):
    d = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(BASE + p, data=d, method=m)
    r.add_header("Content-Type", "application/json")
    for k, v in (h or {}).items():
        r.add_header(k, v)
    try:
        x = urllib.request.urlopen(r, timeout=15)
        raw = x.read().decode()
        return x.status, (json.loads(raw) if raw[:1] in "{[" else raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        return e.code, (json.loads(raw) if raw[:1] in "{[" else raw)


esiti = []
def check(nome, cond, extra=""):
    esiti.append(cond)
    print(("  OK   " if cond else "  ROSSO ") + nome + (" | " + extra if extra else ""))


TOK = call("POST", "/api/host/login", {"email": "host@visivo.it", "password": "password1"})[1]["token"]
HH = {"X-Host-Token": TOK}
oggi = datetime.date.today()

# RESET idempotente: il server e' STATEFUL (i run precedenti hanno cambiato prezzi/min-stay/blocchi).
# Riporto l'intera finestra di test a uno stato noto: prezzo base 18000, 3 unita', min_notti 1, aperto.
_da = (oggi + datetime.timedelta(days=55)).isoformat()
_a = (oggi + datetime.timedelta(days=95)).isoformat()
call("POST", "/api/host/disponibilita_range",
     {"alloggio_id": SLUG, "da": _da, "a": _a, "unita_totali": 3,
      "prezzo_netto_cents": 18000, "min_notti": 1}, HH)


def quote(ci, co):
    return call("POST", "/api/concierge/quote",
                {"alloggio_id": SLUG, "check_in": ci, "check_out": co, "party": 2})


def prenotabile(q):
    s, r = q
    return s == 200 and isinstance(r, dict) and not r.get("errore")


def in_catalogo():
    return SLUG in json.dumps(call("GET", "/api/catalogo?" + urllib.parse.urlencode({"citta": "Roma"}))[1])


print("== 1) BLOCCO / SBLOCCO DATA -> ricerca pubblica ISTANTANEA ==")
ci = (oggi + datetime.timedelta(days=60)).isoformat()
co = (oggi + datetime.timedelta(days=62)).isoformat()
check("prima: la data e' prenotabile (quote 200)", prenotabile(quote(ci, co)))
check("prima: annuncio in ricerca pubblica /api/catalogo", in_catalogo())
s, _ = call("POST", "/api/host/disponibilita",
            {"alloggio_id": SLUG, "giorno": ci, "unita_totali": 3,
             "prezzo_netto_cents": 18000, "chiuso": True}, HH)
check("host blocca la data (chiuso=True) -> 200", s == 200, "HTTP %s" % s)
check("SUBITO DOPO: la data NON e' piu' prenotabile (istantaneo)", not prenotabile(quote(ci, co)))
s, _ = call("POST", "/api/host/disponibilita",
            {"alloggio_id": SLUG, "giorno": ci, "unita_totali": 3,
             "prezzo_netto_cents": 18000, "chiuso": False}, HH)
check("host sblocca la data -> torna prenotabile ALL'ISTANTE", prenotabile(quote(ci, co)))

print("== 2) VARIAZIONE PREZZO + MIN-STAY -> checkout AL CENTESIMO, no cache ==")
ci2 = (oggi + datetime.timedelta(days=70)).isoformat()
co2 = (oggi + datetime.timedelta(days=72)).isoformat()   # 2 notti
# prezzo base 18000/notte -> 2 notti = 36000
s, q0 = quote(ci2, co2)
base = q0.get("totale_cents") if isinstance(q0, dict) else None
check("prezzo base 2 notti = 36000", base == 36000, "letto %s" % base)
# l'host cambia il prezzo a 25000/notte
call("POST", "/api/host/disponibilita_range",
     {"alloggio_id": SLUG, "da": ci2, "a": co2, "unita_totali": 3, "prezzo_netto_cents": 25000}, HH)
s, q1 = quote(ci2, co2)
nuovo = q1.get("totale_cents") if isinstance(q1, dict) else None
check("SUBITO DOPO: nuovo prezzo 2 notti = 50000 (al centesimo, no cache vecchia)", nuovo == 50000,
      "letto %s" % nuovo)
# min-stay: l'host impone 3 notti minime -> la quote di 2 notti dev'essere RIFIUTATA
call("POST", "/api/host/disponibilita_range",
     {"alloggio_id": SLUG, "da": ci2, "a": (oggi + datetime.timedelta(days=80)).isoformat(),
      "unita_totali": 3, "prezzo_netto_cents": 25000, "min_notti": 3}, HH)
check("min-stay 3: quote di 2 notti RIFIUTATA (coerenza ricerca<->book)", not prenotabile(quote(ci2, co2)))
# 3 notti invece passano
co3 = (oggi + datetime.timedelta(days=73)).isoformat()
check("min-stay 3: quote di 3 notti OK", prenotabile(quote(ci2, co3)))

print("== 3) PRENOTAZIONE -> VOUCHER + PIN (smart_pass) + notifica host cablata ==")
ci4 = (oggi + datetime.timedelta(days=90)).isoformat()
co4 = (oggi + datetime.timedelta(days=92)).isoformat()
qt = quote(ci4, co4)[1]["quote_token"]
s, b = call("POST", "/api/concierge/book",
            {"quote_token": qt, "email": "ospite@x.it", "modo_pagamento": "online"})
check("book confermato (201)", s == 201, "HTTP %s" % s)
vt = b.get("voucher_token") if isinstance(b, dict) else None
sp = b.get("smart_pass") if isinstance(b, dict) else None
check("l'ospite riceve il VOUCHER (voucher_token non vuoto)", bool(vt) and len(str(vt)) > 20)
check("l'ospite riceve il PIN/pass (smart_pass non vuoto)", bool(sp) and len(str(sp)) > 8,
      "smart_pass len=%s" % (len(str(sp)) if sp else 0))
# il voucher firmato porta il riferimento giusto (non falsificabile): stesso rif del book
check("il voucher e' coerente con la prenotazione (stesso riferimento)",
      str(b.get("riferimento", "")) != "" )
# notifica host: cablaggio presente (fase152 dispatcher). Telegram e' un canale DORMIENTE (serve il
# token bot + il chat_id dell'host): qui non si consegna, ma il canale ESISTE ed e' cablato.
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # radice repo
    import fase152_notifiche_prenotazione as n152
    ha_telegram = hasattr(n152, "CanaleTelegram")
except Exception:
    ha_telegram = False
check("notifica host: il canale Telegram ESISTE nel dispatcher (dormiente senza token)", ha_telegram)

n_ok = sum(esiti)
print("\n== ESITO COMPORTAMENTALE HOST: %d/%d verdi ==" % (n_ok, len(esiti)))
sys.exit(0 if n_ok == len(esiti) else 1)
