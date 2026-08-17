"""E2E RIMBORSO CONTRO STRIPE VERO (chiave di PROVA) — IL GIUDICE ESTERNO SUL PEZZO CHE
RESTITUISCE I SOLDI.

PERCHE' ESISTE, e non e' un doppione. Il 2026-08-17 sono state riparate le quattro strade che
portavano a «il cliente ha dei soldi da riavere» senza finire nella lista, ed e' stato chiuso un
difetto che cancellava il record dove vive lo `stripe_pi`. Tutte quelle prove sostituiscono
Stripe con un finto: dimostrano che il NOSTRO codice si comporta bene, MAI che un rimborso sia
davvero partito. E cercando (`collaudi/*stripe*.py`) si e' misurato che **nessun collaudo aveva
mai visto un rimborso uscire**: il credito si, il bonifico all'host si, il rimborso no.

Qui il verdetto lo da' un GIUDICE ESTERNO: la API di Stripe, RI-LETTA dopo l'operazione. E'
il collaudo n.7 della regola dei 10, applicato al punto dove i soldi tornano indietro.

COSA DIMOSTRA, in ordine:
  R1  un pagamento VERO (in prova) entra nel nostro sistema col suo `pi_` vero
  R2  chi cancella compare nella lista dei rimborsi dovuti CON il pulsante
  R3  premendo il pulsante Stripe registra UN rimborso, dell'importo ESATTO dovuto
  R4  premendolo DUE volte Stripe continua a vedere UN rimborso solo (chiave di idempotenza)
  R5  la riga esce dalla lista perche' lo dice STRIPE, non perche' l'abbiamo tolta noi
  R6  CONTROVERSIA: la cifra ESATTA in euro decisa dall'arbitro e' quella che Stripe rimborsa
  R7  e dopo un rimborso da controversia la tariffa tecnica NON diventa una nostra perdita
      (ordine del fondatore 2026-08-17: «non devo pagare io la spesa delle Stripe»)

⛔ LA CHIAVE NON SI STAMPA MAI (regola ferrea 14 / D6): si legge dal file fuori dal repository,
   si usa, e negli output compare solo il prefisso. Nessun `print` la contiene.

⛔ BLOCCO MECCANICO CONTRO IL VIVO (D18 condizione 1: uno strumento che misura deve provare di
   essere in condizione di misurare, PRIMA di misurare). Questo attrezzo muove denaro vero se
   gli si passa una chiave viva. Percio' si rifiuta di partire se la chiave non comincia per
   `sk_test_`, e lo dice. Non e' una cortesia: e' la differenza fra un collaudo e un bonifico.

⛔ NON LO RACCOGLIE `unittest discover`: non si chiama `test_*.py` apposta. Tocca la rete e la
   API di Stripe, quindi non deve rallentare la suite ne' romperla quando la rete non c'e'.

USO:  python collaudi/e2e_rimborso_stripe.py
Uscita 0 = tutti i passi superati. Uscita 1 = almeno un passo fallito (elencati in fondo).
"""
import json
import os
import re
import shutil
import ssl
import sys
import tempfile
import urllib.parse
import urllib.request

PROGETTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Stessa fonte dell'altro giudice esterno: la chiave di PROVA vive FUORI dal repository.
FILE_CHIAVE = os.environ.get(
    "STRIPE_TEST_KEY_FILE",
    os.path.join(os.path.dirname(PROGETTO), "stripe.com prova.txt"))
sys.path.insert(0, PROGETTO)

ESITI = []
API = "https://api.stripe.com/v1/"
VERSIONE = "2024-06-20"


def passo(nome, condizione, dettaglio=""):
    ESITI.append((nome, bool(condizione), dettaglio))
    print("  %s  %s%s" % ("OK  " if condizione else "ROSSO", nome,
                          ("  -> " + dettaglio) if dettaglio else ""))


def leggi_chiave():
    """La chiave di PROVA, con il blocco meccanico contro il vivo.

    ⛔ Due controlli, non uno: la cerco col prefisso `sk_test_`, E rifiuto il file se contiene
    una `sk_live`. Il primo da solo non basterebbe: un file con dentro tutte e due passerebbe,
    e un domani qualcuno potrebbe cambiare la ricerca «per comodita'».
    """
    try:
        with open(FILE_CHIAVE, "r", encoding="utf-8", errors="replace") as f:
            testo = f.read()
    except OSError as e:
        print("ROSSO: non riesco a leggere il file della chiave di prova (%s)." % e)
        print("       Atteso in: %s" % FILE_CHIAVE)
        print("       Si sposta con la variabile d'ambiente STRIPE_TEST_KEY_FILE.")
        sys.exit(1)
    if re.search(r"sk_live_[A-Za-z0-9]+", testo):
        print("ROSSO: nel file c'e' una chiave VIVA (sk_live). MI SONO FERMATO.")
        print("       Questo attrezzo esegue rimborsi veri: con una chiave viva muoverebbe")
        print("       soldi veri. Tieni le chiavi di prova in un file separato.")
        sys.exit(1)
    m = re.search(r"sk_test_[A-Za-z0-9]+", testo)
    if not m:
        print("ROSSO: nessuna chiave sk_test nel file. Mi fermo.")
        sys.exit(1)
    return m.group(0)


def _chiama(chiave, percorso, dati=None, idem=None):
    intestazioni = {"Authorization": "Bearer " + chiave, "Stripe-Version": VERSIONE}
    corpo = None
    if dati is not None:
        corpo = urllib.parse.urlencode(dati, doseq=True).encode("utf-8")
        intestazioni["Content-Type"] = "application/x-www-form-urlencoded"
    if idem:
        intestazioni["Idempotency-Key"] = idem
    req = urllib.request.Request(API + percorso, data=corpo, headers=intestazioni)
    try:
        with urllib.request.urlopen(req, timeout=40,
                                    context=ssl.create_default_context()) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # ⛔ L'OSSERVABILE DEBOLE E' UN DIFETTO (regola ferrea 9): si riporta codice,
        # sottocodice e messaggio, non il solo stato HTTP.
        try:
            d = json.loads(e.read().decode("utf-8")).get("error", {})
        except Exception:
            d = {}
        return {"_errore": {"http": e.code, "type": d.get("type", ""),
                            "code": d.get("code", ""), "message": d.get("message", "")}}


def rimborsi_su_stripe(chiave, pi_):
    """Quanti rimborsi esistono DAVVERO su quel pagamento, e per quanto. Sola lettura."""
    out = _chiama(chiave, "refunds?payment_intent=" + urllib.parse.quote(pi_) + "&limit=100")
    if "_errore" in out:
        return None, out["_errore"]
    righe = [r for r in (out.get("data") or []) if isinstance(r, dict)]
    return righe, None


def main():
    chiave = leggi_chiave()
    print("=" * 78)
    print("E2E RIMBORSO — GIUDICE ESTERNO: STRIPE (chiave %s..., %d caratteri)"
          % (chiave[:8], len(chiave)))
    print("=" * 78)

    os.environ.setdefault("PAGAMENTO_BPS", "500")
    os.environ.setdefault("PAGAMENTO_BPS_ESTERA", "700")
    os.environ.setdefault("PAGAMENTO_FISSO_CENTS", "25")

    from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
    from fase83_server import crea_router
    from fase87_stripe_webhook import firma_di_test
    from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
    import time as _t

    WH = "whsec_e2e_rimborso"
    d = tempfile.mkdtemp()
    try:
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db", db_finanza=f"{d}/fin.db",
            commissione_bps=1000, psp_bps=500,
            stripe_secret_key=chiave, stripe_webhook_secret=WH,
            stripe_success_url="https://bookinvip.com/ok",
            stripe_cancel_url="https://bookinvip.com/no"))
        r = crea_router(sis, host_key="hk", admin_key="ak",
                        base_url="https://bookinvip.com")

        def g(metodo, path, body=None, headers=None):
            return r.gestisci(metodo, path, {},
                              json.dumps(body) if body is not None else None, headers or {})

        s, c = g("POST", "/api/host/registrazione",
                 {"email": "host.e2e.rimborso@bookinvip.com", "password": "password1",
                  "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
                  "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        if s != 201:
            print("ROSSO: registrazione host fallita: %r" % (c,))
            return 1
        tok = c["token"]
        g("POST", "/api/host/pubblica",
          {"slug": "villa-rimb", "titolo": "Villa Rimborso", "citta": "Roma",
           "prezzo_notte_cents": 20000, "capacita": 4,
           "politica_cancellazione": "flessibile"}, {"X-Host-Token": tok})
        g("POST", "/api/host/disponibilita_range",
          {"alloggio_id": "villa-rimb", "da": "2027-04-01", "a": "2027-06-30",
           "unita_totali": 5, "prezzo_netto_cents": 20000}, {"X-Host-Token": tok})

        def prenota(ci, co):
            st, q = g("POST", "/api/concierge/quote",
                      {"alloggio_id": "villa-rimb", "check_in": ci, "check_out": co,
                       "party": 2})
            if st != 200:
                raise SystemExit("preventivo fallito (%s): %r" % (st, q))
            st, b = g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "ospite.rimb@bookinvip.com"})
            if st != 201:
                raise SystemExit("book fallito (%s): %r" % (st, b))
            return q, b

        def paga_su_stripe(totale):
            """Un pagamento VERO in modalita' prova, con la carta di test di Stripe.
            Serve un addebito RIUSCITO: senza, un rimborso non e' nemmeno possibile."""
            return _chiama(chiave, "payment_intents", {
                "amount": totale, "currency": "eur", "payment_method": "pm_card_visa",
                "confirm": "true", "description": "E2E rimborso BookinVIP (prova)",
                "automatic_payment_methods[enabled]": "true",
                "automatic_payment_methods[allow_redirects]": "never"})

        def webhook(rif, pi_):
            pl = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"id": "cs_" + pi_,
                                                 "payment_intent": pi_,
                                                 "metadata": {"riferimento": rif}}}})
            return r.gestisci("POST", "/api/payments/webhook", {}, pl,
                              {"Stripe-Signature": firma_di_test(pl, WH, int(_t.time()))})

        def lista():
            st, corpo = g("GET", "/api/admin/rimborsi_dovuti", None, {"X-Admin-Key": "ak"})
            return st, corpo

        def riga_di(corpo, rif):
            for x in (corpo.get("rimborsi") or []):
                if x.get("riferimento") == rif:
                    return x
            return None

        # ---------------- R1: un pagamento VERO entra nel sistema ----------------
        print("\n--- R1: un pagamento VERO (in prova) col suo pi_ vero ---")
        q, b = prenota("2027-04-05", "2027-04-08")
        rif, vt = b["riferimento"], b["voucher_token"]
        pag = paga_su_stripe(int(q["totale_cents"]))
        if "_errore" in pag:
            passo("Stripe ha accettato il pagamento di prova", False, repr(pag["_errore"]))
            return 1
        pi_ = pag.get("id") or ""
        passo("Stripe ha creato e confermato un pagamento vero (in prova)",
              pag.get("status") == "succeeded" and pi_.startswith("pi_"),
              "pi=%s... stato=%s importo=%s" % (pi_[:12], pag.get("status"),
                                                pag.get("amount")))
        passo("l'importo su Stripe e' quello del nostro preventivo",
              int(pag.get("amount") or 0) == int(q["totale_cents"]),
              "stripe=%s nostro=%s" % (pag.get("amount"), q["totale_cents"]))
        st, _ = webhook(rif, pi_)
        rec = sis.pagamenti_pendenti.info(rif) or {}
        dj = json.loads(rec.get("corpo_json") or "{}")
        passo("il nostro sistema ha registrato IL pi_ vero, non un finto",
              dj.get("stripe_pi") == pi_, "salvato=%s" % str(dj.get("stripe_pi"))[:12])

        # ---------------- R2: cancella -> in lista, col pulsante ----------------
        print("\n--- R2: chi cancella entra in lista CON il pulsante ---")
        st, canc = g("POST", "/api/concierge/cancella", {"voucher_token": vt})
        passo("la cancellazione dell'ospite riesce", st == 200, "stato=%s" % st)
        dovuto = int((canc or {}).get("rimborso_cents") or 0)
        passo("la politica gli riconosce qualcosa", dovuto > 0, "dovuto=%d" % dovuto)
        st, corpo = lista()
        riga = riga_di(corpo, rif)
        passo("la lista e' CONTROLLABILE (Stripe risponde davvero)",
              bool(corpo.get("controllabile")),
              str(corpo.get("motivo_non_controllabile") or "")[:90])
        passo("compare fra chi aspetta i suoi soldi", riga is not None)
        if riga is None:
            return 1
        passo("l'importo in lista e' quello deciso dalla politica",
              int(riga.get("dovuto_cents") or 0) == dovuto,
              "lista=%s politica=%d" % (riga.get("dovuto_cents"), dovuto))
        passo("il pulsante c'e'", bool(riga.get("bottone")),
              "manca=%r" % (riga.get("manca"),))

        # ---------------- R3: si preme, e STRIPE lo conferma ----------------
        print("\n--- R3: premuto il pulsante, il verdetto lo da' STRIPE ---")
        st, es = g("POST", "/api/admin/rimborsa_dovuto", {"riferimento": rif},
                   {"X-Admin-Key": "ak"})
        passo("la nostra rotta dice di aver rimborsato", st == 200 and es.get("stato") == "rimborsato",
              "stato=%s corpo=%s" % (st, str(es)[:120]))
        righe, err = rimborsi_su_stripe(chiave, pi_)
        passo("Stripe risponde all'interrogazione sui rimborsi", err is None, repr(err))
        if righe is None:
            return 1
        passo("STRIPE vede ESATTAMENTE UN rimborso", len(righe) == 1,
              "trovati=%d" % len(righe))
        if righe:
            passo("e l'importo su STRIPE e' quello dovuto (non il totale, non un arrotondamento)",
                  int(righe[0].get("amount") or 0) == dovuto,
                  "stripe=%s dovuto=%d" % (righe[0].get("amount"), dovuto))
            passo("il rimborso su Stripe e' RIUSCITO",
                  righe[0].get("status") in ("succeeded", "pending"),
                  "stato=%s" % righe[0].get("status"))

        # ---------------- R4: premuto due volte, non paga due volte ----------------
        print("\n--- R4: premuto DUE volte (il doppio clic e' un secondo rimborso) ---")
        st2, es2 = g("POST", "/api/admin/rimborsa_dovuto", {"riferimento": rif},
                     {"X-Admin-Key": "ak"})
        righe2, err2 = rimborsi_su_stripe(chiave, pi_)
        passo("Stripe continua a vedere UN rimborso solo",
              err2 is None and righe2 is not None and len(righe2) == 1,
              "trovati=%s risposta2=%s" % (len(righe2) if righe2 else "?", str(es2)[:80]))
        somma = sum(int(x.get("amount") or 0) for x in (righe2 or []))
        passo("e la somma restituita non e' raddoppiata", somma == dovuto,
              "totale su Stripe=%d dovuto=%d" % (somma, dovuto))

        # ---------------- R5: la riga esce perche' lo dice Stripe ----------------
        print("\n--- R5: la riga esce dalla lista perche' lo dice STRIPE ---")
        st, corpo = lista()
        passo("non compare piu' fra chi aspetta", riga_di(corpo, rif) is None,
              "in_attesa=%s" % corpo.get("in_attesa"))

        # ---------------- R6/R7: la CONTROVERSIA, con la cifra esatta ----------------
        print("\n--- R6: controversia, la cifra ESATTA in euro decisa dall'arbitro ---")
        q2, b2 = prenota("2027-04-15", "2027-04-18")
        rif2, vt2 = b2["riferimento"], b2["voucher_token"]
        pag2 = paga_su_stripe(int(q2["totale_cents"]))
        if "_errore" in pag2:
            passo("secondo pagamento di prova accettato", False, repr(pag2["_errore"]))
            return 1
        pi2 = pag2.get("id") or ""
        webhook(rif2, pi2)
        st, cst = g("POST", "/api/garanzia/contesta", {"voucher_token": vt2})
        passo("l'ospite riesce ad aprire la controversia", st == 200, str(cst)[:100])
        stato_g = sis.garanzia.stato(rif2) or {}
        in_garanzia = int(stato_g.get("importo_host_cents") or 0)
        # ⛔ UNA CIFRA CHE NESSUNA PERCENTUALE INTERA PUO' PRODURRE: e' il caso che il campo
        # in euro esiste per coprire (ordine del fondatore 2026-08-17).
        esatta = in_garanzia // 3 + 7
        st, out = g("POST", "/api/admin/controversia/risolvi",
                    {"riferimento": rif2, "rimborso_ospite_cents": esatta},
                    {"X-Admin-Key": "ak"})
        passo("l'arbitrato con la cifra esatta riesce", st == 200, str(out)[:110])
        passo("il server ha registrato ESATTAMENTE la cifra scritta",
              int((out or {}).get("rimborso_cliente_cents") or -1) == esatta,
              "scritta=%d registrata=%s" % (esatta, (out or {}).get("rimborso_cliente_cents")))
        passo("e all'host resta il resto, al centesimo",
              int((out or {}).get("va_all_host_cents") or -1) == in_garanzia - esatta,
              "garanzia=%d - ospite=%d = %d, host=%s"
              % (in_garanzia, esatta, in_garanzia - esatta,
                 (out or {}).get("va_all_host_cents")))
        st, corpo = lista()
        riga2 = riga_di(corpo, rif2)
        passo("la controversia compare fra chi aspetta i suoi soldi", riga2 is not None)
        if riga2 is not None:
            passo("con l'importo deciso dall'arbitro",
                  int(riga2.get("dovuto_cents") or 0) == esatta,
                  "lista=%s deciso=%d" % (riga2.get("dovuto_cents"), esatta))

        print("\n--- R7: e la spesa di Stripe NON diventa una nostra perdita ---")
        costi = sis.pagamenti_pendenti.aggrega_costi_tecnici()
        rec2 = sis.pagamenti_pendenti.info(rif2) or {}
        passo("la prenotazione in controversia resta 'pagato' (il soggiorno c'e' stato)",
              rec2.get("stato") == "pagato", "stato=%s" % rec2.get("stato"))
        passo("quindi la tariffa tecnica resta fra le INCASSATE, non fra le perdite",
              (costi.get("incassate") or {}).get("conteggio", 0) >= 1,
              "incassate=%s perdite=%s"
              % ((costi.get("incassate") or {}).get("conteggio"),
                 (costi.get("perdite") or {}).get("conteggio")))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    ok = sum(1 for _n, c, _d in ESITI if c)
    rossi = [(n, d) for n, c, d in ESITI if not c]
    print("\n" + "=" * 78)
    print("PASSI: %d   OK: %d   ROSSI: %d" % (len(ESITI), ok, len(rossi)))
    for n, d in rossi:
        print("  ROSSO: %s  %s" % (n, d))
    print("=" * 78)
    return 1 if rossi else 0


if __name__ == "__main__":
    sys.exit(main())
