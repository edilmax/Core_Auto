"""L'ESAME DELLA CASELLA 3 DEL BLOCCO SOLDI — «hold, payout e penale scadono davvero in un giro
contro Stripe di PROVA con l'orologio NOSTRO spostato, e i tre esiti si rileggono da Stripe».

    python collaudi/esame_orologi.py                 tre rami contro Stripe di PROVA, misura e MOSTRA
    python collaudi/esame_orologi.py --scrivi        misura e SCRIVE nella scheda (anche un rosso,
                                                     col suo motivo)
    python collaudi/esame_orologi.py --ramo hold     un ramo solo (prova in piccolo; NON scrive):
                                                     hold | payout | penale
    python collaudi/esame_orologi.py --con-guasto    l'orologio dell'hold NON avanza (il guasto):
                                                     l'esame deve gridare, e NON scrive mai
    python collaudi/esame_orologi.py --autoprova     il giudizio sui passi, nelle due direzioni,
                                                     senza rete (D18 punto 2)

PERCHE' L'OROLOGIO E' IL NOSTRO, misurato il 3 e il 4 settembre 2026 su docs.stripe.com (7 pagine):
le Simulazioni/test clock di Stripe si agganciano SOLO a Customer, abbonamenti, fatture e preventivi
(tre clienti, tre abbonamenti per cliente, dieci preventivi); nessun test helper fa scadere
un'autorizzazione, maturare un bonifico o spostare un PaymentIntent/Transfer/Payout; in prova «le
transazioni vengono regolate immediatamente». Le nostre tre scadenze sono timer NOSTRI nel nostro
database: `fase162.scadenza_ts` (hold), `fase160.sblocco_auto_ts` (payout, check-in + 24 h),
`fase111` sui giorni all'arrivo (penale). Quindi qui si sposta l'orologio iniettato di `fase162` e
`fase160` (`orologio=`), per la penale si prenota a due giorni dall'arrivo (fase83 conta i giorni
dal calendario, non da un orologio), e IL VERDETTO LO DA' STRIPE, riletto dopo ogni operazione.

I TRE RAMI, e cosa Stripe rilegge:
  HOLD    prenotazione con hold di 2 minuti su un alloggio a UNA unita'; pagamento VERO di prova
          (pi_); l'orologio del pendente avanza di un'ora -> lo sweeper di produzione
          (`sweep_hold_una_passata`) fa scadere l'hold e libera la stanza -> un secondo ospite la
          prende -> arriva il webhook tardivo del primo pagamento -> `_conferma_pagamento` non
          puo' ribloccare, marca il rimborso dovuto -> lista col pulsante -> premuto -> STRIPE
          vede ESATTAMENTE UN rimborso, dell'intero pagato.
  PAYOUT  l'host ha un conto Connect di prova gia' abilitato; prenotazione pagata con check-in
          domani; la garanzia nasce con `sblocco_auto_ts` = check-in + 24 h; l'orologio della
          garanzia avanza oltre -> `auto_rilascia` + `_trasferisci_all_host` (le due righe del
          tick di produzione) -> STRIPE vede il Transfer `tr_` con l'importo e il destinatario.
  PENALE  politica «moderata», arrivo fra due giorni (fuori dal ripensamento 48 h, che vale con
          arrivo >= 3 giorni); l'ospite cancella -> la politica riconosce il 50 % -> lista col
          pulsante -> premuto -> STRIPE vede UN rimborso del 50 %, e il PaymentIntent trattiene
          il resto: la penale e' quel resto.

⛔ IL TESTO DELLA CASELLA NON SI RICOPIA: si legge da `collaudi/piano.py` (e' la chiave).
⛔ LA CHIAVE NON SI STAMPA MAI; l'esame si rifiuta di partire con una chiave viva (`sk_live`):
   lo fa `e2e_rimborso_stripe.leggi_chiave`, riusata tale e quale.
⛔ NON LO RACCOGLIE `unittest discover`: tocca la rete e muove denaro di PROVA.

⛔ D18, LE QUATTRO CONDIZIONI: 1. `precondizioni()` ferma il giro; 2. `--autoprova` nelle due
   direzioni e `--con-guasto` sul vivo; 3. `NON_GUARDA`; 4. guardia
   `test_pipeline_ci.TestLEsameDegliOrologiNonPuoBARARE`.
"""
import datetime
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.parse

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
for _p in (RADICE, QUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import scheda  # noqa: E402
from piano import BLOCCHI  # noqa: E402
import e2e_rimborso_stripe as e2e  # noqa: E402  (leggi_chiave, _chiama, rimborsi_su_stripe)

BLOCCO_SOLDI = 1
INDICE_CASELLA = 2                       # la terza casella del blocco (0-based)
COMANDO = "python collaudi/esame_orologi.py --scrivi"
RAMI = ("hold", "payout", "penale")
FILE_CHIAVE = e2e.FILE_CHIAVE
PREZZO_NOTTE = 20000
ATTESA_CAPACITA_S = 45                   # quanto si aspetta che Stripe attivi `transfers` sul conto

NON_GUARDA = (
    "la scadenza dell'autorizzazione DI STRIPE (7 giorni, `capture_before`): non e' un nostro "
    "timer e Stripe non offre modo di accelerarla; qui scadono le nostre tre finestre",
    "la modalita' viva: tutto e' in PROVA (`sk_test`), e l'esame si rifiuta con una chiave viva",
    "il modulo di attivazione del conto Connect che l'host compila sulle pagine di Stripe: il "
    "conto ricevente nasce gia' abilitato, cosa possibile SOLO in prova (come prova_bonifico_host)",
    "la penale dell'HOST che cancella (15 %, `PENALE_HOST_BPS`): qui la penale e' quella "
    "dell'ospite secondo la politica di cancellazione",
    "le prenotazioni «paga in struttura» e le valute diverse da EUR",
    "per la penale l'orologio non si sposta: fase83 conta i giorni all'arrivo dal calendario, "
    "quindi si prenota a due giorni dall'arrivo (e' equivalente, ed e' dichiarato)",
    "le altre cinque caselle del blocco: non le tocca",
)

PASSI = []


class Orologio(object):
    """Un orologio che si sposta a mano. `fase162` e `fase160` lo ricevono come `orologio=`."""

    def __init__(self, ts):
        self.ts = int(ts)

    def __call__(self):
        return self.ts


def passo(ramo, nome, ok, dettaglio=""):
    PASSI.append((ramo, nome, bool(ok), dettaglio))
    print("  %s  [%s] %s%s" % ("OK  " if ok else "ROSSO", ramo, nome,
                                ("  -> " + dettaglio) if dettaglio else ""))
    return bool(ok)


# --------------------------------------------------------------------------------------
# IL GIUDIZIO (puro): riceve i passi, rende (verde, motivi, denominatore)
# --------------------------------------------------------------------------------------
def giudica(passi, rami=RAMI):
    """Verde SOLO se ognuno dei tre rami ha almeno un passo e nessun passo e' rosso."""
    motivi = []
    for ramo in rami:
        suoi = [p for p in passi if p[0] == ramo]
        if not suoi:
            motivi.append("ramo «%s» NON misurato" % ramo)
            continue
        rossi = [p for p in suoi if not p[2]]
        for _r, nome, _ok, dettaglio in rossi:
            motivi.append("[%s] %s%s" % (ramo, nome, (" (%s)" % dettaglio) if dettaglio else ""))
    fuori = [p for p in passi if p[0] not in rami]
    if fuori:
        motivi.append("passi fuori dai tre rami: %d" % len(fuori))
    return (not motivi), motivi, len(passi)


# --------------------------------------------------------------------------------------
# MISURA PRIMA SE STESSO (D18 punto 1)
# --------------------------------------------------------------------------------------
def precondizioni(con_rete=True):
    fuori = []
    try:
        blocco = [b for b in BLOCCHI if b["ordine"] == BLOCCO_SOLDI]
        cond = blocco[0]["finito_quando"] if len(blocco) == 1 else ()
        testo = " ".join(str(cond[INDICE_CASELLA]).split()) if len(cond) > INDICE_CASELLA else ""
        fuori.append(("la casella esiste nel piano e parla dell'orologio NOSTRO",
                      "orologio NOSTRO" in testo, testo[:80] or "manca la terza casella"))
    except Exception as e:
        fuori.append(("la casella esiste nel piano", False, "%s: %s" % (type(e).__name__, e)))
    try:
        impronta = scheda.impronta_del_blocco(BLOCCO_SOLDI)
        fuori.append(("il blocco ha un'impronta", bool(impronta), impronta or "il piano non si legge"))
    except Exception as e:
        fuori.append(("il blocco ha un'impronta", False, str(e)))
    try:
        import inspect
        from fase160_escrow_garanzia import crea_escrow_garanzia
        from fase162_pagamenti_pendenti import crea_pagamenti_pendenti
        from fase83_server import sweep_hold_una_passata  # noqa: F401
        ok = all("orologio" in inspect.signature(f).parameters
                 for f in (crea_escrow_garanzia, crea_pagamenti_pendenti))
        fuori.append(("fase162 e fase160 accettano un orologio iniettato, e lo sweeper esiste", ok,
                      "crea_pagamenti_pendenti(orologio=), crea_escrow_garanzia(orologio=), "
                      "sweep_hold_una_passata"))
    except Exception as e:
        fuori.append(("fase162 e fase160 accettano un orologio iniettato", False,
                      "%s: %s" % (type(e).__name__, e)))
    if con_rete:
        fuori.append(("la chiave di PROVA esiste (non si legge qui, non si stampa mai)",
                      os.path.isfile(FILE_CHIAVE), FILE_CHIAVE))
    return all(ok for _, ok, _ in fuori), fuori


# --------------------------------------------------------------------------------------
# IL BANCO: un sistema vero, in una cartella temporanea, con Stripe di PROVA e gli orologi
# --------------------------------------------------------------------------------------
class Banco(object):

    def __init__(self, chiave, cartella):
        os.environ.setdefault("PAGAMENTO_BPS", "500")
        os.environ.setdefault("PAGAMENTO_BPS_ESTERA", "700")
        os.environ.setdefault("PAGAMENTO_FISSO_CENTS", "25")
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase83_server import crea_router
        from fase160_escrow_garanzia import crea_escrow_garanzia
        from fase162_pagamenti_pendenti import crea_pagamenti_pendenti
        d = cartella
        self.chiave = chiave
        self.WH = "whsec_esame_orologi"
        self.cfg = ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"O" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db", db_finanza=f"{d}/fin.db",
            commissione_bps=1000, psp_bps=500,
            stripe_secret_key=chiave, stripe_webhook_secret=self.WH,
            stripe_success_url="https://bookinvip.com/ok", stripe_cancel_url="https://bookinvip.com/no")
        self.sis = crea_sistema(self.cfg)
        # GLI OROLOGI NOSTRI: gli stessi archivi, con un orologio che si sposta a mano
        self.orologio_hold = Orologio(time.time())
        self.orologio_garanzia = Orologio(time.time())
        self.sis.pagamenti_pendenti = crea_pagamenti_pendenti(self.cfg.db_pendenti,
                                                              orologio=self.orologio_hold)
        self.sis.garanzia = crea_escrow_garanzia(self.cfg.db_garanzia, orologio=self.orologio_garanzia)
        self.router = crea_router(self.sis, host_key="hk", admin_key="ak",
                                  base_url="https://bookinvip.com")
        self.tok = None

    def g(self, metodo, path, body=None, headers=None):
        return self.router.gestisci(metodo, path, {},
                                    json.dumps(body) if body is not None else None, headers or {})

    def host(self):
        from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "host.esame.orologi@bookinvip.com", "password": "password1",
                       "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        if s != 201:
            raise SystemExit("registrazione host fallita (stato %s; corpo non stampato: "
                             "contiene il token dell'host)" % s)
        self.tok = c["token"]
        return self.tok

    def alloggio(self, slug, *, unita, politica, da, a):
        h = {"X-Host-Token": self.tok}
        s, c = self.g("POST", "/api/host/pubblica",
                      {"slug": slug, "titolo": "Villa " + slug, "citta": "Roma",
                       "prezzo_notte_cents": PREZZO_NOTTE, "capacita": 4,
                       "politica_cancellazione": politica}, h)
        if s not in (200, 201):
            raise SystemExit("pubblica %s fallita (stato %s, errore=%r)" % (slug, s, (c or {}).get("errore")))
        s, c = self.g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": slug, "da": da, "a": a, "unita_totali": unita,
                       "prezzo_netto_cents": PREZZO_NOTTE}, h)
        if s not in (200, 201):
            raise SystemExit("disponibilita %s fallita (stato %s, errore=%r)" % (slug, s, (c or {}).get("errore")))

    def prenota(self, slug, ci, co):
        st, q = self.g("POST", "/api/concierge/quote",
                       {"alloggio_id": slug, "check_in": ci, "check_out": co, "party": 2})
        if st != 200:
            raise SystemExit("preventivo %s %s..%s fallito (stato %s, errore=%r; corpo non "
                             "stampato: contiene il quote_token)" % (slug, ci, co, st, (q or {}).get("errore")))
        st, b = self.g("POST", "/api/concierge/book",
                       {"quote_token": q["quote_token"], "email": "ospite.orologi@bookinvip.com"})
        if st != 201:
            raise SystemExit("book fallito (stato %s, errore=%r; corpo non stampato: contiene il "
                             "voucher_token)" % (st, (b or {}).get("errore")))
        return q, b

    def paga_su_stripe(self, totale, causale):
        return e2e._chiama(self.chiave, "payment_intents", {
            "amount": totale, "currency": "eur", "payment_method": "pm_card_visa",
            "confirm": "true", "description": "esame orologi BookinVIP (prova): " + causale,
            "automatic_payment_methods[enabled]": "true",
            "automatic_payment_methods[allow_redirects]": "never"})

    def webhook(self, rif, pi_):
        from fase87_stripe_webhook import firma_di_test
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": "cs_" + pi_, "payment_intent": pi_,
                                             "metadata": {"riferimento": rif}}}})
        return self.router.gestisci("POST", "/api/payments/webhook", {}, pl,
                                    {"Stripe-Signature": firma_di_test(pl, self.WH, int(time.time()))})

    def lista(self):
        return self.g("GET", "/api/admin/rimborsi_dovuti", None, {"X-Admin-Key": "ak"})

    @staticmethod
    def riga_di(corpo, rif):
        for x in ((corpo or {}).get("rimborsi") or []):
            if x.get("riferimento") == rif:
                return x
        return None

    def premi(self, rif):
        return self.g("POST", "/api/admin/rimborsa_dovuto", {"riferimento": rif}, {"X-Admin-Key": "ak"})

    def rimborsato_da_stripe(self, ramo, pi_, dovuto):
        """I tre passi che Stripe rilegge dopo un rimborso: uno, dell'importo esatto, riuscito."""
        righe, err = e2e.rimborsi_su_stripe(self.chiave, pi_)
        passo(ramo, "Stripe risponde all'interrogazione sui rimborsi", err is None, repr(err))
        if righe is None:
            return False
        ok = passo(ramo, "STRIPE vede ESATTAMENTE UN rimborso", len(righe) == 1, "trovati=%d" % len(righe))
        if righe:
            ok = passo(ramo, "e l'importo su STRIPE e' quello dovuto, al centesimo",
                       int(righe[0].get("amount") or 0) == dovuto,
                       "stripe=%s dovuto=%d id=%s" % (righe[0].get("amount"), dovuto,
                                                    str(righe[0].get("id"))[:14])) and ok
            ok = passo(ramo, "il rimborso su Stripe e' riuscito",
                       righe[0].get("status") in ("succeeded", "pending"),
                       "stato=%s" % righe[0].get("status")) and ok
        return ok


# --------------------------------------------------------------------------------------
# I TRE RAMI
# --------------------------------------------------------------------------------------
def ramo_hold(b, con_guasto=False):
    print("\n--- HOLD: l'hold scade (orologio NOSTRO), la stanza va a un altro, il pagamento tardivo torna ---")
    b.alloggio("villa-hold", unita=1, politica="flessibile", da="2027-04-01", a="2027-06-30")
    q, bk = b.prenota("villa-hold", "2027-04-05", "2027-04-08")
    rif, totale = bk["riferimento"], int(q["totale_cents"])
    rec = b.sis.pagamenti_pendenti.info(rif) or {}
    passo("hold", "la prenotazione e' un hold 'in_attesa' con una scadenza di 2 minuti sul NOSTRO orologio",
          rec.get("stato") == "in_attesa" and 0 < int(rec.get("scadenza_ts") or 0) - b.orologio_hold.ts <= 120,
          "stato=%s scadenza-orologio=%s s" % (rec.get("stato"), int(rec.get("scadenza_ts") or 0) - b.orologio_hold.ts))
    pag = b.paga_su_stripe(totale, "hold " + rif)
    if "_errore" in pag:
        passo("hold", "Stripe ha accettato il pagamento di prova", False, repr(pag["_errore"]))
        return
    pi_ = pag.get("id") or ""
    passo("hold", "un pagamento VERO (in prova) esiste su Stripe, dell'importo del preventivo",
          pag.get("status") == "succeeded" and pi_.startswith("pi_") and int(pag.get("amount") or 0) == totale,
          "pi=%s... stato=%s importo=%s" % (pi_[:12], pag.get("status"), pag.get("amount")))
    # L'OROLOGIO NOSTRO AVANZA DI UN'ORA (col guasto dentro, resta fermo: l'hold non scade mai)
    if not con_guasto:
        b.orologio_hold.ts += 3600
    from fase83_server import sweep_hold_una_passata
    sweep_hold_una_passata(b.sis, b.router)
    rec = b.sis.pagamenti_pendenti.info(rif) or {}
    passo("hold", "lo sweeper di produzione ha fatto scadere l'hold (stato 'scaduto')",
          rec.get("stato") == "scaduto", "stato=%s" % rec.get("stato"))
    libera = b.sis.inventario.disponibile("villa-hold", "2027-04-05", "2027-04-08")
    passo("hold", "e ha liberato la stanza", libera is True, "disponibile=%r" % (libera,))
    if rec.get("stato") != "scaduto" or libera is not True:
        return
    q2, bk2 = b.prenota("villa-hold", "2027-04-05", "2027-04-08")
    passo("hold", "un SECONDO ospite prende la stessa stanza (hold vivo)",
          (b.sis.pagamenti_pendenti.info(bk2["riferimento"]) or {}).get("stato") == "in_attesa")
    st, _ = b.webhook(rif, pi_)
    rec = b.sis.pagamenti_pendenti.info(rif) or {}
    passo("hold", "il webhook TARDIVO del primo pagamento non trova la stanza: il pendente e' 'rimborsato'",
          st in (200, 503) and rec.get("stato") == "rimborsato", "webhook=%s stato=%s" % (st, rec.get("stato")))
    st, corpo = b.lista()
    riga = b.riga_di(corpo, rif)
    passo("hold", "il primo ospite compare fra chi aspetta i suoi soldi, per l'INTERO pagato, col pulsante",
          riga is not None and int(riga.get("dovuto_cents") or 0) == totale and bool(riga.get("bottone")),
          "riga=%s" % ({k: riga.get(k) for k in ("dovuto_cents", "bottone", "manca")} if riga else None))
    if riga is None or not riga.get("bottone"):
        return
    st, es = b.premi(rif)
    passo("hold", "premuto il pulsante, la rotta dice di aver rimborsato", st == 200 and es.get("stato") == "rimborsato",
          "stato=%s corpo=%s" % (st, str(es)[:100]))
    b.rimborsato_da_stripe("hold", pi_, totale)
    st, corpo = b.lista()
    passo("hold", "e la riga esce dalla lista perche' lo dice Stripe", b.riga_di(corpo, rif) is None)


def _conto_connect_di_prova(chiave):
    """Un conto ricevente 'custom' GIA' abilitato ai transfer: possibile SOLO in prova (la stessa
    ricetta di `collaudi/prova_bonifico_host.py`, passo [4], misurata il 2026-08-09)."""
    marca = str(int(time.time()))
    ex = e2e._chiama(chiave, "accounts", {
        "type": "custom", "country": "IT", "email": "ricevente-orologi-%s@example.com" % marca,
        "business_type": "individual", "capabilities[transfers][requested]": "true",
        "individual[first_name]": "Mario", "individual[last_name]": "Rossi",
        "individual[email]": "ricevente-orologi-%s@example.com" % marca,
        "individual[dob][day]": "1", "individual[dob][month]": "1", "individual[dob][year]": "1980",
        "individual[address][line1]": "Via Roma 1", "individual[address][city]": "Roma",
        "individual[address][postal_code]": "00100", "individual[address][country]": "IT",
        "individual[phone]": "+390612345678",
        "business_profile[url]": "https://bookinvip.com", "business_profile[mcc]": "7011",
        "tos_acceptance[date]": str(int(time.time())), "tos_acceptance[ip]": "127.0.0.1",
        "external_account[object]": "bank_account", "external_account[country]": "IT",
        "external_account[currency]": "eur", "external_account[account_number]": "IT89370400440532013000"})
    if "_errore" in ex:
        return None, repr(ex["_errore"])
    acct = ex.get("id") or ""
    inizio = time.time()
    stato = ""
    while time.time() - inizio < ATTESA_CAPACITA_S:
        a = e2e._chiama(chiave, "accounts/" + urllib.parse.quote(acct))
        stato = ((a.get("capabilities") or {}).get("transfers")) if "_errore" not in a else "?"
        if stato == "active":
            return acct, "transfers=active"
        time.sleep(5)
    return acct, "transfers=%s dopo %d s" % (stato, ATTESA_CAPACITA_S)


def ramo_payout(b):
    print("\n--- PAYOUT: la garanzia matura a check-in + 24 h (orologio NOSTRO) e il bonifico parte ---")
    oggi = datetime.date.today()
    ci, co = (oggi + datetime.timedelta(days=1)).isoformat(), (oggi + datetime.timedelta(days=2)).isoformat()
    b.alloggio("villa-payout", unita=2, politica="flessibile", da=oggi.isoformat(),
               a=(oggi + datetime.timedelta(days=40)).isoformat())
    acct, dettaglio = _conto_connect_di_prova(b.chiave)
    passo("payout", "nasce un conto Connect di prova per l'host, abilitato ai transfer",
          bool(acct) and dettaglio == "transfers=active", "%s %s" % ((acct or "")[:14], dettaglio))
    if not acct or dettaglio != "transfers=active":
        return
    host_id = b.sis.catalogo.host_di_alloggio("villa-payout") or ""
    passo("payout", "il conto viene agganciato all'host nel registro",
          bool(host_id) and b.sis.registro_host.imposta_stripe_account(host_id, acct)
          and (b.sis.registro_host.info_host(host_id) or {}).get("stripe_account_id") == acct)
    q, bk = b.prenota("villa-payout", ci, co)
    rif, totale = bk["riferimento"], int(q["totale_cents"])
    pag = b.paga_su_stripe(totale, "payout " + rif)
    if "_errore" in pag:
        passo("payout", "Stripe ha accettato il pagamento di prova", False, repr(pag["_errore"]))
        return
    pi_ = pag.get("id") or ""
    st, _ = b.webhook(rif, pi_)
    rec = b.sis.pagamenti_pendenti.info(rif) or {}
    passo("payout", "prenotazione PAGATA (pagamento vero di prova + webhook)",
          rec.get("stato") == "pagato" and pi_.startswith("pi_"), "stato=%s pi=%s..." % (rec.get("stato"), pi_[:12]))
    aperta = [g for g in b.sis.garanzia.aperte() if g.get("prenotazione_id") == rif]
    sblocco = int(aperta[0]["sblocco_auto_ts"]) if aperta else 0
    passo("payout", "la garanzia e' aperta con lo sblocco a check-in + 24 h (sul NOSTRO orologio)",
          bool(aperta) and sblocco > b.orologio_garanzia.ts,
          "sblocco fra %.1f h" % ((sblocco - b.orologio_garanzia.ts) / 3600.0) if aperta else "nessuna garanzia")
    pay = b.sis.payout.info(rif) or {}
    passo("payout", "il payout dell'host e' 'maturato' con un importo positivo",
          pay.get("stato") == "maturato" and int(pay.get("minori") or 0) > 0,
          "stato=%s minori=%s" % (pay.get("stato"), pay.get("minori")))
    if not aperta or pay.get("stato") != "maturato":
        return
    bal = e2e._chiama(b.chiave, "balance")
    disp = sum(int(v.get("amount") or 0) for v in (bal.get("available") or []) if v.get("currency") == "eur")
    if disp < int(pay["minori"]):
        # come prova_bonifico_host [3]: in prova il saldo si crea con una carta finta
        e2e._chiama(b.chiave, "charges", {"amount": max(20000, int(pay["minori"])), "currency": "eur",
                                          "source": "tok_bypassPending",
                                          "description": "ricarica banco per l'esame degli orologi"})
        time.sleep(2)
        bal = e2e._chiama(b.chiave, "balance")
        disp = sum(int(v.get("amount") or 0) for v in (bal.get("available") or []) if v.get("currency") == "eur")
    passo("payout", "c'e' saldo disponibile (in prova) per il bonifico", disp >= int(pay["minori"]),
          "disponibile=%d minori=%s" % (disp, pay["minori"]))
    # L'OROLOGIO NOSTRO AVANZA OLTRE LO SBLOCCO; poi le due righe del tick di produzione
    b.orologio_garanzia.ts = sblocco + 60
    pp = b.sis.pagamenti_pendenti

    def rimborsata(r):
        try:
            i = pp.info(r)
            return bool(i) and i.get("stato") in ("rimborsato", "cancellata_host")
        except Exception:
            return False
    rilasciate = b.sis.garanzia.auto_rilascia(dettagli=True, salta_se=rimborsata) or []
    mia = [r for r in rilasciate if r.get("prenotazione_id") == rif]
    passo("payout", "auto_rilascia rilascia la garanzia scaduta all'host",
          bool(mia) and int(mia[0].get("host_riceve_cents") or 0) == int(pay["minori"]),
          "rilasciate=%r" % (rilasciate,))
    if not mia:
        return
    b.router._trasferisci_all_host(rif, int(mia[0]["host_riceve_cents"]))
    stato_pay = b.sis.payout.stato_di(rif)
    passo("payout", "il bonifico e' partito (payout 'in_transito')", stato_pay == "in_transito", "stato=%s" % stato_pay)
    tr = ""
    for ev in b.sis.finanza.stream_giornale():
        if ev.get("tipo") == "payout_host" and str(ev.get("riferimento")) == rif:
            m = re.search(r"tr_[A-Za-z0-9]+", str(ev.get("causale") or ""))
            tr = m.group(0) if m else ""
    passo("payout", "il giornale porta il tr_ del bonifico", tr.startswith("tr_"), tr[:14])
    if not tr:
        return
    t = e2e._chiama(b.chiave, "transfers/" + urllib.parse.quote(tr))
    passo("payout", "STRIPE vede il Transfer: importo dell'host, destinatario il suo conto, euro",
          "_errore" not in t and int(t.get("amount") or 0) == int(mia[0]["host_riceve_cents"])
          and t.get("destination") == acct and t.get("currency") == "eur",
          "stripe=%s -> %s %s" % (t.get("amount"), str(t.get("destination"))[:14], t.get("currency"))
          if "_errore" not in t else repr(t["_errore"]))


def ramo_penale(b):
    print("\n--- PENALE: arrivo fra due giorni, politica moderata: l'ospite cancella e paga il 50 % ---")
    from fase111_cancellazione import calcola_rimborso
    oggi = datetime.date.today()
    ci, co = (oggi + datetime.timedelta(days=2)).isoformat(), (oggi + datetime.timedelta(days=3)).isoformat()
    b.alloggio("villa-penale", unita=2, politica="moderata", da=oggi.isoformat(),
               a=(oggi + datetime.timedelta(days=40)).isoformat())
    q, bk = b.prenota("villa-penale", ci, co)
    rif, vt, totale = bk["riferimento"], bk["voucher_token"], int(q["totale_cents"])
    pag = b.paga_su_stripe(totale, "penale " + rif)
    if "_errore" in pag:
        passo("penale", "Stripe ha accettato il pagamento di prova", False, repr(pag["_errore"]))
        return
    pi_ = pag.get("id") or ""
    b.webhook(rif, pi_)
    rec = b.sis.pagamenti_pendenti.info(rif) or {}
    passo("penale", "prenotazione PAGATA con arrivo fra due giorni", rec.get("stato") == "pagato",
          "stato=%s arrivo=%s" % (rec.get("stato"), ci))
    st, canc = b.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
    dovuto = int((canc or {}).get("rimborso_cents") or 0)
    passo("penale", "l'ospite cancella e la politica riconosce una PARTE (non tutto: la penale e' il resto)",
          st == 200 and 0 < dovuto < totale, "stato=%s dovuto=%d pagato=%d" % (st, dovuto, totale))
    atteso = calcola_rimborso(totale, 2, politica="moderata")
    atteso_cents = int(getattr(atteso, "rimborso_cents", atteso) if not isinstance(atteso, dict)
                       else atteso.get("rimborso_cents", 0))
    passo("penale", "la cifra e' quella della politica «moderata» a 2 giorni (50 %)", dovuto == atteso_cents,
          "dovuto=%d politica=%d" % (dovuto, atteso_cents))
    if not (0 < dovuto < totale):
        return
    st, corpo = b.lista()
    riga = b.riga_di(corpo, rif)
    passo("penale", "compare in lista con la cifra della politica e il pulsante",
          riga is not None and int(riga.get("dovuto_cents") or 0) == dovuto and bool(riga.get("bottone")),
          "riga=%s" % ({k: riga.get(k) for k in ("dovuto_cents", "bottone", "manca")} if riga else None))
    if riga is None or not riga.get("bottone"):
        return
    st, es = b.premi(rif)
    passo("penale", "premuto il pulsante, la rotta dice di aver rimborsato la parte dovuta",
          st == 200 and es.get("stato") == "rimborsato", "stato=%s corpo=%s" % (st, str(es)[:100]))
    b.rimborsato_da_stripe("penale", pi_, dovuto)
    p = e2e._chiama(b.chiave, "payment_intents/" + urllib.parse.quote(pi_))
    ricevuto = int(p.get("amount_received") or 0) if "_errore" not in p else -1
    passo("penale", "e su STRIPE il PaymentIntent ha incassato l'intero: la penale e' il resto trattenuto",
          ricevuto == totale and totale - dovuto > 0,
          "ricevuto=%d rimborsato=%d trattenuto=%d" % (ricevuto, dovuto, totale - dovuto))
    st, corpo = b.lista()
    passo("penale", "e la riga esce dalla lista perche' lo dice Stripe", b.riga_di(corpo, rif) is None)


# --------------------------------------------------------------------------------------
# AUTOPROVA (D18 punto 2): il giudizio, senza rete
# --------------------------------------------------------------------------------------
def passi_finti(rossi=(), senza=()):
    fuori = []
    for ramo in RAMI:
        if ramo in senza:
            continue
        for i in range(3):
            fuori.append((ramo, "passo %d" % i, not (ramo in rossi and i == 1), ""))
    return fuori


def autoprova():
    casi = (("tre rami tutti verdi", passi_finti(), True),
            ("un passo rosso nell'hold", passi_finti(rossi=("hold",)), False),
            ("un passo rosso nel payout", passi_finti(rossi=("payout",)), False),
            ("un passo rosso nella penale", passi_finti(rossi=("penale",)), False),
            ("il ramo payout NON misurato", passi_finti(senza=("payout",)), False),
            ("nessun passo", [], False))
    righe, riuscita = [], True
    for nome, passi, atteso in casi:
        verde, motivi, den = giudica(passi)
        ok = verde == atteso
        riuscita = riuscita and ok
        righe.append("   %-32s -> %-6s (atteso %-6s) denominatore %d%s"
                     % (nome, "VERDE" if verde else "ROSSO", "VERDE" if atteso else "ROSSO", den,
                        "" if ok else "   ⛔ NON E' QUELLO CHE DOVEVA DIRE: %s" % "; ".join(motivi)))
    return riuscita, righe


def _stampa_non_guarda():
    print("-" * 86)
    print("⛔ COSA QUESTO ESAME NON HA ESAMINATO (D18 punto 3)")
    for r in NON_GUARDA:
        print("   · %s" % r)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    os.chdir(RADICE)
    del PASSI[:]
    print("=" * 86)
    print("🧾 ESAME DEL BLOCCO SOLDI — casella 3: hold, payout e penale scadono davvero (orologio NOSTRO, Stripe rilegge)")
    print("=" * 86)

    if "--autoprova" in argv:
        print("🔁 AUTOPROVA — il giudizio si vede gridare e tacere su passi costruiti (D18 punto 2)")
        riuscita, righe = autoprova()
        for r in righe:
            print(r)
        _stampa_non_guarda()
        print("=" * 86)
        print("VERDETTO: %s" % ("✅ il giudizio grida sui passi rossi e tace sui verdi" if riuscita
                                else "⛔ IL GIUDIZIO NON E' AFFIDABILE"))
        return 0 if riuscita else 1

    con_guasto = "--con-guasto" in argv
    solo = argv[argv.index("--ramo") + 1] if "--ramo" in argv else None
    if (con_guasto or solo) and "--scrivi" in argv:
        # ⛔ Un `if`, non un commento: la misura di una macchina rotta apposta, o di un ramo solo,
        #    non e' la casella (stessa cura degli altri esami).
        print("⛔ FERMO: `--con-guasto` e `--ramo` non scrivono. Servono a vedere l'esame gridare e a")
        print("   provare in piccolo; registrare quel giro metterebbe nella scheda una misura parziale.")
        return 2

    tutte_ok, righe = precondizioni()
    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    for nome, ok, motivo in righe:
        print("  %-9s %-70s %s" % ("OK" if ok else "⛔ NO", nome, motivo))
    if not tutte_ok:
        print("VERDETTO: ⛔ FERMO — una precondizione non regge, quindi NON misuro e NON scrivo.")
        _stampa_non_guarda()
        return 2

    chiave = e2e.leggi_chiave()            # si ferma da sola con una chiave viva o assente
    print("GIUDICE ESTERNO: STRIPE di PROVA (chiave %s..., %d caratteri)" % (chiave[:8], len(chiave)))
    if con_guasto:
        print("⚠️  PASSATA COL GUASTO DENTRO: l'orologio dell'hold NON avanza (l'hold non scade mai)")
    d = tempfile.mkdtemp()
    try:
        b = Banco(chiave, d)
        b.host()
        for ramo, f in (("hold", lambda: ramo_hold(b, con_guasto)), ("payout", lambda: ramo_payout(b)),
                        ("penale", lambda: ramo_penale(b))):
            if solo and ramo != solo:
                continue
            try:
                f()
            except SystemExit as e:
                passo(ramo, "il ramo si e' FERMATO", False, str(e))
            except Exception as e:                       # noqa: BLE001 - un ramo rotto e' un rosso, non un crash
                passo(ramo, "il ramo e' ESPLOSO", False, "%s: %s" % (type(e).__name__, e))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    verde, motivi, denominatore = giudica(PASSI, rami=(solo,) if solo else RAMI)
    print("")
    print("VERDETTO: %s — passi %d, rossi %d, denominatore %d"
          % ("✅ VERDE" if verde else "⛔ ROSSO", len(PASSI), sum(1 for p in PASSI if not p[2]), denominatore))
    for m in motivi:
        print("   perche': %s" % m)

    condizioni = [bl for bl in BLOCCHI if bl["ordine"] == BLOCCO_SOLDI][0]["finito_quando"]
    if "--scrivi" in argv:
        print("")
        print("SCRITTURA NELLA SCHEDA")
        riga = scheda.registra(condizioni[INDICE_CASELLA], esito=verde, denominatore=denominatore,
                               comando=COMANDO, ordine=BLOCCO_SOLDI, motivo="; ".join(motivi) or None)
        print("  scritta: blocco %d · esito %s · denominatore %d · impronta %s · motivo: %s"
              % (riga["blocco"], riga["esito"], riga["denominatore"], riga["impronta"], riga.get("motivo") or "-"))
    else:
        print("")
        print("(non ho scritto niente: aggiungi --scrivi per registrare nella scheda)")
    _stampa_non_guarda()
    print("=" * 86)
    return 0 if verde else 1


if __name__ == "__main__":
    sys.exit(main())
