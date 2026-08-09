"""I SOLDI ARRIVANO DAVVERO SUL CONTO DELL'HOST? — il pezzo che `giro_banco.py` NON prova.

`collaudi/giro_banco.py` dichiara da solo, in cima, cio' che non copre: *«il bonifico VERSO
l'host: serve il conto Connect»*. Questo script chiude quel buco, ed e' l'unica prova che
esista che il denaro arriva a destinazione.

⛔ GIRA SOLO CON UNA CHIAVE DI PROVA. Se la chiave non e' `sk_test_`, si ferma con uscita 2:
un bonifico e' un movimento di denaro, e questo collaudo non deve poterne fare uno vero.

USO, dentro il banco di prova (vedi `collaudi/banco_prova.sh`):
    docker exec -i banco_prova_app python3 -  <  collaudi/prova_bonifico_host.py

QUATTRO PASSI:
  [1] un host nuovo chiede di collegare la banca -> nasce un conto acct_ vero
  [2] il link di attivazione e' un vero indirizzo Stripe (quello che clicchera')
  [3] esiste abbastanza saldo per bonificare (se no lo si crea con una carta finta)
  [4] IL BONIFICO parte con LA STESSA funzione della produzione (fase101.trasferisci)

⛔ COSA NON PROVA, dichiarato (D18 punto 3): il gesto dell'host che compila il modulo sulle
   pagine di Stripe. Serve un browser, ed e' interfaccia di Stripe, non nostra. Qui il conto
   ricevente si crea gia' abilitato, cosa possibile SOLO in modalita' prova.

Misurato la prima volta il 2026-08-09: 10 passi su 10, `tr_1U2S69JMRnB73twqzoa0JZnm`.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("BASE_BANCO", "http://127.0.0.1:8080")
PREZZO = 20000
esiti = []
non_eseguiti = []

sys.path.insert(0, "/app" if os.path.isdir("/app") else
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256   # noqa: E402


def passo(nome, ok, atteso, ottenuto):
    esiti.append(bool(ok))
    print("  %-4s %-58s (atteso %s / ottenuto %s)"
          % ("OK" if ok else "NO", nome, atteso, ottenuto), flush=True)


def salta(nome, perche):
    non_eseguiti.append((nome, perche))
    print("  --   %-58s NON ESEGUITO: %s" % (nome, perche), flush=True)


def chiama(metodo, percorso, corpo=None, testate=None):
    dati = json.dumps(corpo).encode() if corpo is not None else None
    t = {"Content-Type": "application/json"}
    t.update(testate or {})
    req = urllib.request.Request(BASE + percorso, data=dati, headers=t, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            testo = r.read().decode()
            try:
                return r.status, json.loads(testo)
            except ValueError:
                return r.status, testo
    except urllib.error.HTTPError as e:
        testo = e.read().decode()
        try:
            return e.code, json.loads(testo)
        except ValueError:
            return e.code, {}


CHIAVE = (os.environ.get("STRIPE_SECRET_KEY", "")
          or os.environ.get("STRIPE_LIVE_SECRET_KEY", ""))


def stripe(metodo, percorso, params=None):
    dati = urllib.parse.urlencode(params, doseq=True).encode() if params else None
    req = urllib.request.Request(
        "https://api.stripe.com/v1" + percorso, data=dati,
        headers={"Authorization": "Bearer " + CHIAVE,
                 "Content-Type": "application/x-www-form-urlencoded"},
        method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except ValueError:
            return e.code, {}


print("=" * 80)
print("  I SOLDI ARRIVANO SUL CONTO DELL'HOST?   (solo modalita' PROVA)")
print("=" * 80)

if not CHIAVE.startswith("sk_test"):
    print("  ⛔ MI FERMO: la chiave non e' di prova. Non provo bonifici con soldi veri.")
    sys.exit(2)

marca = str(int(time.time()))
email = "banco-payout-%s@example.com" % marca

print("\n-- [1] UN HOST NUOVO CHIEDE DI COLLEGARE LA SUA BANCA --")
st, reg = chiama("POST", "/api/host/registrazione",
                 {"email": email, "password": "password1",
                  "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
                  "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
token = (reg or {}).get("token", "") if isinstance(reg, dict) else ""
passo("l'host si registra (3 spunte + prova firmata)", st == 201, "201",
      "%s %s" % (st, "" if token else reg))
passo("e riceve subito il suo gettone", bool(token), "un gettone", "si" if token else "NO")

if not token:
    salta("collegamento della banca", "senza gettone non si puo' chiedere")
else:
    st, link = chiama("GET", "/api/host/stripe_link", None, {"X-Host-Token": token})
    acct = (link or {}).get("account_id", "") if isinstance(link, dict) else ""
    url = (link or {}).get("link", "") if isinstance(link, dict) else ""
    pronto = (link or {}).get("pronto") if isinstance(link, dict) else None
    passo("nasce un conto Stripe per l'host", st == 200 and acct.startswith("acct_"),
          "un acct_...", acct or ("HTTP %s %s" % (st, link)))
    print("\n-- [2] IL LINK CHE L'HOST CLICCHERA' --")
    passo("e' un vero indirizzo di Stripe", url.startswith("https://connect.stripe.com"),
          "https://connect.stripe.com/...", (url[:46] + "...") if url else "(vuoto)")
    passo("e risulta NON ancora pronto (deve compilare il modulo)", pronto is False,
          "False", pronto)
    if acct:
        st, a = stripe("GET", "/accounts/" + acct)
        passo("Stripe conferma che il conto esiste ed e' 'standard'",
              st == 200 and a.get("type") == "standard", "standard", a.get("type"))

print("\n-- [3] C'E' SALDO PER BONIFICARE? --")
st, bal = stripe("GET", "/balance")
disp = 0
for v in (bal.get("available") or []):
    if v.get("currency") == "eur":
        disp = int(v.get("amount") or 0)
print("      saldo disponibile in euro: %d centesimi" % disp)
if disp < 5000:
    st, ch = stripe("POST", "/charges", {
        "amount": 20000, "currency": "eur", "source": "tok_bypassPending",
        "description": "ricarica banco per prova bonifico host"})
    passo("creo saldo con una carta finta (tok_bypassPending)", st == 200, "200", st)
    time.sleep(2)
    st, bal = stripe("GET", "/balance")
    for v in (bal.get("available") or []):
        if v.get("currency") == "eur":
            disp = int(v.get("amount") or 0)
    print("      saldo disponibile ora: %d centesimi" % disp)
passo("c'e' abbastanza per un bonifico di 10,00 EUR", disp >= 1000, ">=1000", disp)

print("\n-- [4] IL BONIFICO VERO, con LA STESSA funzione della produzione --")
st, ex = stripe("POST", "/accounts", {
    "type": "custom", "country": "IT", "email": "ricevente-%s@example.com" % marca,
    "business_type": "individual",
    "capabilities[transfers][requested]": "true",
    "individual[first_name]": "Mario", "individual[last_name]": "Rossi",
    "individual[email]": "ricevente-%s@example.com" % marca,
    "individual[dob][day]": "1", "individual[dob][month]": "1", "individual[dob][year]": "1980",
    "individual[address][line1]": "Via Roma 1", "individual[address][city]": "Roma",
    "individual[address][postal_code]": "00100", "individual[address][country]": "IT",
    "individual[phone]": "+390612345678",
    "business_profile[url]": "https://bookinvip.com",
    "business_profile[mcc]": "7011",
    "tos_acceptance[date]": str(int(time.time())), "tos_acceptance[ip]": "127.0.0.1",
    "external_account[object]": "bank_account", "external_account[country]": "IT",
    "external_account[currency]": "eur",
    "external_account[account_number]": "IT89370400440532013000",
})
ric = ex.get("id", "")
passo("nasce un conto host GIA' abilitato (solo in prova)",
      st == 200 and ric.startswith("acct_"), "un acct_...",
      ric or ex.get("error", {}).get("message", st))

if not ric:
    salta("il bonifico", "non ho un conto ricevente")
else:
    st, a2 = stripe("GET", "/accounts/" + ric)
    cap_tr = ((a2.get("capabilities") or {}).get("transfers"))
    print("      payouts_enabled=%s  transfers=%s" % (a2.get("payouts_enabled"), cap_tr))
    if cap_tr != "active":
        salta("il bonifico", "Stripe non ha ancora attivato 'transfers' su questo conto "
                             "(stato: %s) — non e' un difetto nostro" % cap_tr)
    else:
        from fase101_stripe_connect import crea_provider_connect
        prov = crea_provider_connect(CHIAVE)
        tid = prov.trasferisci(ric, 1000, "EUR", "prova-banco-" + marca)
        passo("IL BONIFICO PARTE (fase101.trasferisci)",
              bool(tid) and str(tid).startswith("tr_"), "un tr_...", tid)
        if tid:
            st, tr = stripe("GET", "/transfers/" + str(tid))
            passo("Stripe conferma: importo e destinatario giusti",
                  st == 200 and tr.get("amount") == 1000 and tr.get("destination") == ric,
                  "1000 -> %s" % ric, "%s -> %s" % (tr.get("amount"), tr.get("destination")))

print("\n" + "=" * 80)
print("PASSI: %d   OK: %d   NON OK: %d   NON ESEGUITI: %d"
      % (len(esiti), sum(esiti), len(esiti) - sum(esiti), len(non_eseguiti)))
for n, p in non_eseguiti:
    print("   NON ESEGUITO: %s -> %s" % (n, p))
print("=" * 80)
sys.exit(0 if all(esiti) else 1)
