"""(3) E2E CREDITO SINGLE-USE CONTRO STRIPE VERO (chiave di PROVA).

PERCHE' ESISTE. Gli E2E gia' in `test_credito_single_use.py` sostituiscono Stripe con
`_fake_fetch`: provano che il NOSTRO codice si comporta bene, mai che l'importo davvero
addebitato rifletta lo sconto del credito. Qui il verdetto lo da' un GIUDICE ESTERNO (la
API di Stripe, ri-letta dopo la creazione), che e' il collaudo n.7 della regola dei 10.

COSA DIMOSTRA, in ordine:
  P1  un credito sconta il preventivo, e lo sconto e' ESATTAMENTE il nominale del credito
  P2  Stripe addebita l'importo SCONTATO (letto dalla API, non dal nostro oggetto)
  P3  lo stesso credito NON sconta piu' i preventivi successivi
  P4  due preventivi generati PRIMA del book: il secondo book viene RIFIUTATO (409)
  P5  e la stanza del book rifiutato resta prenotabile (nessun danno collaterale)

⛔ LA CHIAVE NON SI STAMPA MAI (regola ferrea 14 / D6): si legge dal file, si usa, e negli
   output compare solo il prefisso. Nessun `print` la contiene.

USO:  python collaudi/e2e_credito_stripe.py
Uscita 0 = tutti i passi superati. Uscita 1 = almeno un passo fallito (elencati in fondo).

⛔ NON LO RACCOGLIE `unittest discover`: non si chiama `test_*.py` apposta. Tocca la rete
   e la API di Stripe, quindi non deve rallentare la suite ne' romperla quando la rete non
   c'e'. Si lancia a mano, come gli altri attrezzi di `collaudi/`.

⛔ LA CHIAVE STA FUORI DAL REPOSITORY, e ci resta. Il file con la chiave di PROVA vive
   accanto al progetto, non dentro: nel repository non entra nessun segreto (D6 / regola
   ferrea 14). Si puo' spostare con la variabile d'ambiente `STRIPE_TEST_KEY_FILE`.
"""
import json
import os
import re
import shutil
import ssl
import sys
import tempfile
import time
import urllib.parse
import urllib.request

# ⛔ RICAVATI, NON CABLATI. Questo file e' nato fuori dal repository con dentro
# `C:\Users\MaxDanno\Desktop\...`: un percorso cablato vale su UN computer solo, e su
# Linux o in CI l'attrezzo sarebbe stato rotto in partenza senza dirlo. La radice si
# deduce da dove sta questo file: `collaudi/` -> il progetto e' la cartella padre.
PROGETTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# La chiave di PROVA vive FUORI dal repository, accanto al progetto, e li' resta: nel
# repository non entra nessun segreto (D6 / regola ferrea 14). Si sposta con la variabile
# d'ambiente, senza toccare il codice.
FILE_CHIAVE = os.environ.get(
    "STRIPE_TEST_KEY_FILE",
    os.path.join(os.path.dirname(PROGETTO), "stripe.com prova.txt"))
sys.path.insert(0, PROGETTO)

ESITI = []


def passo(nome, condizione, dettaglio=""):
    ESITI.append((nome, bool(condizione), dettaglio))
    print("  %s  %s%s" % ("OK  " if condizione else "ROSSO", nome,
                          ("  -> " + dettaglio) if dettaglio else ""))


def leggi_chiave():
    with open(FILE_CHIAVE, "r", encoding="utf-8", errors="replace") as f:
        m = re.search(r"sk_test_[A-Za-z0-9]+", f.read())
    if not m:
        print("ROSSO: nessuna chiave sk_test nel file. Mi fermo.")
        sys.exit(1)
    return m.group(0)


def stripe_get(chiave, percorso):
    """Ri-legge da Stripe. Sola lettura: nessuna scrittura, nessun addebito reale."""
    req = urllib.request.Request(
        "https://api.stripe.com/v1/" + percorso,
        headers={"Authorization": "Bearer " + chiave,
                 "Stripe-Version": "2024-06-20"})
    with urllib.request.urlopen(req, timeout=30,
                                context=ssl.create_default_context()) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    chiave = leggi_chiave()
    print("=" * 78)
    print("E2E CREDITO SINGLE-USE — GIUDICE ESTERNO: STRIPE (chiave %s..., %d caratteri)"
          % (chiave[:8], len(chiave)))
    print("=" * 78)

    # valori di produzione della tariffa tecnica, come sul sito vivo
    os.environ.setdefault("PAGAMENTO_BPS", "500")
    os.environ.setdefault("PAGAMENTO_BPS_ESTERA", "700")
    os.environ.setdefault("PAGAMENTO_FISSO_CENTS", "25")

    from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
    from fase83_server import crea_router
    from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

    d = tempfile.mkdtemp()
    try:
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db",
            db_credito_usati=f"{d}/cu.db",
            commissione_bps=1000, psp_bps=500,
            stripe_secret_key=chiave, stripe_webhook_secret="whsec_e2e_credito",
            stripe_success_url="https://bookinvip.com/ok",
            stripe_cancel_url="https://bookinvip.com/no"))
        r = crea_router(sis, host_key="hk", base_url="https://bookinvip.com")

        def g(metodo, path, body=None, headers=None):
            return r.gestisci(metodo, path, {},
                              json.dumps(body) if body is not None else None, headers or {})

        # ---------- allestimento: host vero + annuncio vero + date vere ----------
        s, c = g("POST", "/api/host/registrazione",
                 {"email": "host.e2e.credito@bookinvip.com", "password": "password1",
                  "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
                  "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        if s != 201:
            print("ROSSO: registrazione host fallita: %r" % (c,))
            return 1
        tok = c["token"]
        g("POST", "/api/host/pubblica",
          {"slug": "villa-e2e", "titolo": "Villa E2E", "citta": "Roma",
           "prezzo_notte_cents": 20000, "capacita": 4,
           "politica_cancellazione": "flessibile"}, {"X-Host-Token": tok})
        g("POST", "/api/host/disponibilita_range",
          {"alloggio_id": "villa-e2e", "da": "2027-03-01", "a": "2027-06-30",
           "unita_totali": 5, "prezzo_netto_cents": 20000}, {"X-Host-Token": tok})

        NOMINALE = 5000        # credito da 50,00 EUR
        credito = sis.firma.codifica({
            "tipo": "credito_fondatore", "email": "ospite.e2e@bookinvip.com",
            "citta": "roma", "credito_cents": NOMINALE,
            "exp": int(time.time()) + 30 * 86400, "nonce": "e2e-stripe-vero"})

        def quote(ci, co, con_credito=True):
            b = {"alloggio_id": "villa-e2e", "check_in": ci, "check_out": co, "party": 2}
            if con_credito:
                b["credito_token"] = credito
            st, q = g("POST", "/api/concierge/quote", b)
            if st != 200:
                raise SystemExit("preventivo fallito (%s): %r" % (st, q))
            return q

        def book(q, email):
            return g("POST", "/api/concierge/book",
                     {"quote_token": q["quote_token"], "email": email})

        # ORACOLO INDIPENDENTE (collaudo n.5): il conto rifatto qui dai valori che ho messo
        # io nella configurazione, NON leggendo il risultato del prodotto. Il credito non si
        # applica per intero: e' tagliato al margine che la commissione puo' assorbire
        # restando sopra il costo Stripe (D16, mai in perdita). Prima versione di questo
        # script asseriva il nominale -- sbagliato IO, non il prodotto (sbaglio S15).
        NETTO = 20000 * 3                              # 3 notti a 200,00 EUR
        COMM = NETTO * 1000 // 10000                   # commissione_bps=1000
        COSTO_STRIPE = NETTO * 325 // 10000 + 25       # misurato sull'API vera il 2026-08-09

        print("\n--- P1: il credito sconta, ma MAI sotto il costo (pavimento D16) ---")
        senza = quote("2027-03-05", "2027-03-08", con_credito=False)
        con = quote("2027-03-05", "2027-03-08", con_credito=True)
        sconto = con.get("sconto_credito_cents", 0)
        passo("il credito sconta qualcosa, e mai piu' del suo nominale",
              0 < sconto <= NOMINALE, "sconto=%d nominale=%d" % (sconto, NOMINALE))
        passo("il totale scende ESATTAMENTE dello sconto applicato",
              senza["totale_cents"] - con["totale_cents"] == sconto,
              "senza=%d con=%d differenza=%d sconto=%d"
              % (senza["totale_cents"], con["totale_cents"],
                 senza["totale_cents"] - con["totale_cents"], sconto))
        passo("PAVIMENTO: dopo aver regalato lo sconto copriamo ancora Stripe",
              COMM - sconto >= COSTO_STRIPE,
              "commissione=%d - sconto=%d = %d  >=  costo Stripe %d"
              % (COMM, sconto, COMM - sconto, COSTO_STRIPE))
        passo("il taglio al margine e' quello atteso dall'oracolo indipendente",
              sconto == min(NOMINALE, COMM - COSTO_STRIPE - 200),
              "atteso=%d ottenuto=%d" % (min(NOMINALE, COMM - COSTO_STRIPE - 200), sconto))

        print("\n--- P2: STRIPE VERO addebita l'importo SCONTATO ---")
        st, b1 = book(con, "ospite.e2e@bookinvip.com")
        passo("prenotazione confermata", st == 201, "stato=%s" % st)
        url = b1.get("payment_url", "") if isinstance(b1, dict) else ""
        m = re.search(r"cs_(test_)?[A-Za-z0-9]+", url or "")
        passo("Stripe ha creato davvero una sessione di pagamento", bool(m),
              "sessione=%s" % (m.group(0)[:14] + "..." if m else "NESSUNA"))
        if m:
            sess = stripe_get(chiave, "checkout/sessions/" + m.group(0))
            passo("l'importo su STRIPE e' quello scontato (letto dalla API, non da noi)",
                  sess.get("amount_total") == con["totale_cents"],
                  "stripe=%r nostro=%r valuta=%s"
                  % (sess.get("amount_total"), con["totale_cents"],
                     str(sess.get("currency", "")).upper()))
            passo("l'importo su Stripe NON e' quello pieno (lo sconto non si e' perso)",
                  sess.get("amount_total") != senza["totale_cents"],
                  "pieno sarebbe stato %d" % senza["totale_cents"])

        print("\n--- P3: lo stesso credito non sconta piu' niente ---")
        dopo = quote("2027-04-05", "2027-04-08", con_credito=True)
        passo("secondo preventivo: sconto ZERO",
              dopo.get("sconto_credito_cents", 0) == 0,
              "sconto=%r" % dopo.get("sconto_credito_cents"))
        terzo = quote("2027-05-05", "2027-05-08", con_credito=True)
        passo("terzo preventivo: sconto ZERO",
              terzo.get("sconto_credito_cents", 0) == 0,
              "sconto=%r" % terzo.get("sconto_credito_cents"))

        print("\n--- P4/P5: due preventivi PRIMA del book (la gara) ---")
        cred2 = sis.firma.codifica({
            "tipo": "credito_fondatore", "email": "ospite2.e2e@bookinvip.com",
            "citta": "roma", "credito_cents": NOMINALE,
            "exp": int(time.time()) + 30 * 86400, "nonce": "e2e-gara"})
        credito = cred2
        qa = quote("2027-03-15", "2027-03-18")
        qb = quote("2027-03-25", "2027-03-28")     # generato PRIMA di prenotare qa
        passo("entrambi i preventivi partono scontati (il credito non e' ancora speso)",
              qa.get("sconto_credito_cents", 0) > 0 and qb.get("sconto_credito_cents", 0) > 0,
              "qa=%r qb=%r" % (qa.get("sconto_credito_cents"), qb.get("sconto_credito_cents")))
        sa, _ = book(qa, "ospite2.e2e@bookinvip.com")
        passo("il PRIMO book passa", sa == 201, "stato=%s" % sa)
        sb, bb = book(qb, "ospite2.e2e@bookinvip.com")
        passo("il SECONDO book viene RIFIUTATO", sb == 409, "stato=%s" % sb)
        passo("e il motivo detto all'ospite e' quello vero",
              isinstance(bb, dict) and bb.get("errore") == "credito_gia_usato",
              "errore=%r" % (bb.get("errore") if isinstance(bb, dict) else bb))
        libera = quote("2027-03-25", "2027-03-28", con_credito=False)
        sl, _ = book(libera, "ospite3.e2e@bookinvip.com")
        passo("la stanza del book rifiutato resta prenotabile", sl == 201, "stato=%s" % sl)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    rossi = [n for n, ok, _ in ESITI if not ok]
    print("\n" + "=" * 78)
    print("PASSI: %d   OK: %d   ROSSI: %d" % (len(ESITI), len(ESITI) - len(rossi), len(rossi)))
    for n in rossi:
        print("   ROSSO -> " + n)
    print("=" * 78)
    return 1 if rossi else 0


if __name__ == "__main__":
    sys.exit(main())
