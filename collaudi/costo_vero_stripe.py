# -*- coding: utf-8 -*-
"""💳 QUANTO SI E' PRESO STRIPE DAVVERO — sola lettura, dalla fonte.

⛔ PERCHE' ESISTE (2026-08-17). Fino a oggi il costo del gateway lo prendevamo dal LISTINO
(`https://stripe.com/it/pricing`, letto il 2026-08-09), perche' sul conto non era mai passato
niente: `GET /v1/balance_transactions` rispondeva `"data": []`. `collaudi/conti_stripe.py`
dichiara da se', nella sua intestazione, *«il giorno che ce ne saranno, la verita' va riletta
da li'»*. Il 2026-08-16 e' passato il PRIMO pagamento vero — una prova da 1,00 EUR, poi
rimborsata — e quel giorno e' arrivato.

⛔ E QUESTO ATTREZZO NASCE PERCHE' STAVA PER RESTARE FUORI DAL REPOSITORY. Le due letture che
hanno trovato il difetto le avevo scritte in una cartella temporanea. E' esattamente il caso
che il controllo 8 del pre-fatto esiste per impedire: *«un attrezzo che sta fuori dal
repository non viaggia con la chiavetta, non gira in CI, e il giorno che serve non c'e'»*.

COSA HA TROVATO, la prima volta che e' girato (conto LIVE, 2026-08-17):
    charge  EUR  importo=100  fee=27  netto=73    ch_3U53IsJMRnB73twq1Vr2rHmz
                 fee_details: stripe_fee = 27 ("Stripe processing fees")
    refund  EUR  importo=-100 fee= 0  netto=-100  re_3U53IsJMRnB73twq1QLzUCu9
Il `fee: 0` sul rimborso e' il punto: **Stripe la sua fetta non la restituisce**. Abbiamo
incassato 73 e restituito 100 -> il saldo Stripe e' andato a **-0,27 EUR**, cioe' un ADDEBITO
in arrivo, non un mancato incasso. Il nostro giornale, nello stesso momento, dichiarava cassa
**0** e un **ricavo** di 30.

⛔ NON SCRIVE NIENTE, ne' da noi ne' su Stripe. ⛔ NON STAMPA MAI LA CHIAVE (regola ferrea 14):
la legge dall'ambiente e non la mostra, e nemmeno i corpi grezzi degli errori (potrebbero
riportare l'intestazione di autorizzazione).

⚠️ DOVE GIRA. La chiave vive sul SERVER, non sul PC del fondatore. Da qui:
    ssh root@<vps> 'docker exec -i casavip_app python -' < collaudi/costo_vero_stripe.py
oppure, se un giorno la chiave fosse nell'ambiente locale, direttamente:
    python collaudi/costo_vero_stripe.py

COSA NON GUARDA (D18 punto 3): solo le ultime 100 transazioni (nessuna paginazione: quando
saranno di piu' va aggiunta, e finche' non c'e' lo dice la riga «TRONCATO»); non incrocia con
il nostro giornale (quello e' un altro lavoro); non distingue le valute nel totale per tipo
oltre al raggruppamento gia' fatto.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LIMITE = 100


def chiave():
    return (os.environ.get("STRIPE_SECRET_KEY", "")
            or os.environ.get("STRIPE_LIVE_SECRET_KEY", ""))


def get(percorso, params=None, k=None):
    """Una GET a Stripe. `None` se fallisce — e il motivo si stampa SENZA il corpo grezzo."""
    k = k or chiave()
    url = "https://api.stripe.com/v1" + percorso
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + k})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:                                   # noqa: BLE001
        print("  RICHIESTA FALLITA su %s: %s" % (percorso, e.__class__.__name__))
        return None


def costo_di(payment_intent, k=None):
    """La commissione VERA di UN pagamento: `pi_...` -> latest_charge -> balance_transaction.

    E' la strada che serve alla riparazione del prospetto del commercialista, e non passa dai
    metadata: ⛔ il charge li ha **vuoti** (misurato) — il `riferimento` della prenotazione sta
    nella sessione di Checkout. Si parte dal `stripe_pi`, che `fase162` gia' salva sul record.
    Ritorna `{'fee', 'netto', 'valuta', 'charge', 'balance_transaction'}` oppure `None`:
    ⛔ `None` vuol dire **«non lo so»**, e chi chiama deve dirlo invece di stimare.
    """
    if not (isinstance(payment_intent, str) and payment_intent.startswith("pi_")):
        return None
    pi = get("/payment_intents/" + payment_intent, k=k)
    ch_id = (pi or {}).get("latest_charge")
    if not ch_id:
        return None
    ch = get("/charges/" + str(ch_id), k=k)
    bt_id = (ch or {}).get("balance_transaction")
    if not bt_id:
        return None
    bt = get("/balance_transactions/" + str(bt_id), k=k)
    if not bt:
        return None
    return {"fee": int(bt.get("fee") or 0), "netto": int(bt.get("net") or 0),
            "valuta": str(bt.get("currency", "")).upper(),
            "charge": ch_id, "balance_transaction": bt_id}


def main():
    k = chiave()
    if not k:
        print("⛔ CHIAVE ASSENTE nell'ambiente: NON ESEGUITO.")
        print("   Non e' uno zero — e' un controllo che non ha potuto guardare (sbaglio S7).")
        print("   La chiave vive sul server: ssh <vps> 'docker exec -i casavip_app python -'"
              " < collaudi/costo_vero_stripe.py")
        return 2
    print("=" * 92)
    print("💳 COSTO VERO DI STRIPE — letto dalla fonte, non dal listino")
    print("   MODO: %s" % ("LIVE" if k.startswith("sk_live")
                           else ("TEST" if k.startswith("sk_test") else "SCONOSCIUTO")))
    print("=" * 92)
    bt = get("/balance_transactions", {"limit": LIMITE}, k=k)
    if bt is None:
        return 3
    dati = bt.get("data") or []
    print("  movimenti letti: %d%s" % (len(dati),
                                       "  ⚠️ TRONCATO al tetto di %d: manca la paginazione, "
                                       "il quadro NON e' completo" % LIMITE
                                       if bt.get("has_more") else ""))
    if not dati:
        print("  (nessuno) -> sul conto non e' ancora passato niente. Finche' e' cosi', il")
        print("  costo si prende dal LISTINO e va dichiarato come tale.")
        return 0
    print()
    print("  %-20s %-9s %-4s %8s %8s %8s  %s"
          % ("quando (UTC)", "tipo", "val", "importo", "fee", "netto", "sorgente"))
    print("  " + "-" * 88)
    for t in dati:
        print("  %-20s %-9s %-4s %8d %8d %8d  %s"
              % (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(int(t.get("created") or 0))),
                 str(t.get("type"))[:9], str(t.get("currency", "")).upper(),
                 int(t.get("amount") or 0), int(t.get("fee") or 0), int(t.get("net") or 0),
                 str(t.get("source") or "")))
    # ⛔ IL NUMERO CHE CONTA, e non e' la somma delle fee: e' il SALDO. Un rimborso restituisce
    # l'importo ma NON la fee (fee=0 sulla riga di rimborso), quindi il netto complessivo va
    # sotto zero e Stripe viene a prendersi la differenza. E' cio' che il fondatore ha visto
    # sulla sua dashboard il 2026-08-17: «In entrata -0,27 EUR».
    per_valuta = {}
    for t in dati:
        v = str(t.get("currency", "")).upper()
        p = per_valuta.setdefault(v, {"fee": 0, "netto": 0, "n": 0})
        p["fee"] += int(t.get("fee") or 0)
        p["netto"] += int(t.get("net") or 0)
        p["n"] += 1
    print()
    print("  IL NUMERO CHE CONTA — il NETTO, non la somma delle commissioni:")
    for v, p in sorted(per_valuta.items()):
        segnale = ""
        if p["netto"] < 0:
            segnale = ("   🔴 SOTTO ZERO: Stripe ha anticipato %d cents e verra' a "
                       "riprenderseli" % (-p["netto"]))
        print("    %-4s  movimenti=%d  commissioni=%d  NETTO=%+d%s"
              % (v, p["n"], p["fee"], p["netto"], segnale))
    print()
    print("  ⛔ Una fee su un rimborso vale 0: la commissione dell'addebito originale NON")
    print("     torna indietro (documentazione Stripe, `docs.stripe.com/refunds`). Percio' un")
    print("     rimborso totale lascia SEMPRE il netto sotto di quella cifra.")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    sys.exit(main())
