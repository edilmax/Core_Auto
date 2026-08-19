# -*- coding: utf-8 -*-
"""COLLAUDO PROFONDO — IDEMPOTENZA: RIPETERE LA STESSA AZIONE VALIDA (doppio clic).

Ogni rotta che SCRIVE viene chiamata DUE VOLTE di fila con la STESSA richiesta valida.
L'esito deve essere SANO, cioe' una di queste due cose e nient'altro:
  (A) IDEMPOTENTE  -> stesso esito, nessuna riga in piu' in archivio, nessun soldo in piu';
  (B) RIFIUTO PULITO -> stato d'errore esplicito e leggibile (409/422/429/404), zero effetti.
MAI: due righe uguali in archivio · due addebiti · due crediti · due email · uno stato incoerente.

L'archivio si controlla DOPO, RIAPRENDO il file .db con una connessione NUOVA e contando le
righe (`self.conta`): un conteggio letto dagli oggetti in memoria non e' una prova.

C'e' anche la prova A DISTANZA DI TEMPO (orologio iniettato avanti) dove l'idempotenza ha una
finestra: hold scaduto dallo sweeper, pagamento gia' avvenuto, prenotazione gia' rimborsata,
diritto di recensione maturato.

──────────────────────────────────────────────────────────────────────────────────────────
DIFETTI TROVATI DA QUESTO COLLAUDO (2026-07-28) E CORRETTI ALLA RADICE
──────────────────────────────────────────────────────────────────────────────────────────
① fase83 `_book` — il doppio clic sul book RIFACEVA tutti gli effetti derivati anche quando
   fase59 aveva riconosciuto il REPLAY della idem-key (`idempotente=True`). Conseguenze reali:
     · SECONDA email identica all'ospite e NUOVO voucher_token con `prenotato_ts` fresco ->
       le 48h di ripensamento ripartivano da zero a ogni clic;
     · dopo il PAGAMENTO: risposta con `payment_url` + email "completa il pagamento" a chi
       aveva gia' pagato = invito al DOPPIO ADDEBITO (il webhook del 2o pagamento non lo
       avrebbe nemmeno segnalato: il CAS trova gia' 'pagato');
     · dopo la SCADENZA dell'hold: escrow e payout RIAPERTI su una prenotazione mai pagata e
       con le date gia' liberate -> l'auto-rilascio dell'escrow avrebbe BONIFICATO ALL'HOST
       soldi mai incassati (il `salta_se` del rilascio copre solo le rimborsate);
     · dopo il RIMBORSO: escrow di nuovo 'in_garanzia' su una prenotazione gia' rimborsata.
   CORREZIONE: `_replay_prenotazione` — su replay con pendente esistente non si ri-deriva
   nulla; si risponde con LA STESSA prenotazione (stesso voucher, senza secondo link di
   pagamento se e' gia' pagata) oppure si rifiuta pulito (409) se non e' piu' prenotabile.
② fase65 `crea_conto` — il doppio clic su "dividi il conto" creava un SECONDO conto per la
   STESSA prenotazione, con le stesse quote: il gruppo si spezzava su due conti (chi paga su
   quello sbagliato risulta non pagante) e il raccolto poteva arrivare al DOPPIO del dovuto.
   CORREZIONE: un solo conto APERTO per prenotazione; il replay restituisce quello che c'e'.

VISTO ROSSO (regola aurea): OGNI test di questo file e' stato visto fallire su un motore
guasto. 28 guasti iniettati uno per volta nel sorgente di produzione, lanciato il test che
doveva vederli, poi sorgente RIPRISTINATO byte per byte (verificato con un confronto esatto):

  fase83  `_book`: salto di `_replay_prenotazione` (correzione ① annullata) -> ROSSI i 4 test
          del doppio clic sul book (email doppia, doppio addebito, dopo-rimborso, dopo-scadenza)
  fase65  `crea_conto`: dedup del conto aperto rimossa (correzione ② annullata) -> 2 conti, 4 quote
  fase65  `registra_pagamento`: replay di quota gia' pagata non riconosciuto -> raccolto doppio
  fase58  `blocca`: ramo replay neutralizzato -> 2 blocchi, notti occupate due volte
  fase58  `imposta_disponibilita`: upsert -> DO NOTHING (il 2o clic non aggiorna piu' il giorno)
  fase58  `imposta_disponibilita`: `unita_occupate=0` sul conflitto (riaprire il periodo
          cancellava le notti gia' prenotate)
  fase177 `movimento`: chiave evento non piu' stabile -> 6 righe di giornale invece di 3
  fase158 `registra`: dedup email+citta' rimossa -> 2 righe in lista d'attesa
  fase160 `conferma_ospite` / `contesta`: guardia di stato allargata -> escrow rilasciato/
          contestato due volte
  fase63  `invia`: "una sola recensione per soggiorno" rimossa -> 2 recensioni
  fase57  `pubblica`: upsert per slug rotto (sempre INSERT) -> 2 annunci con lo stesso slug
  fase57  `imposta_stato`: il no-op diventa errore -> il 2o clic risponde 'rifiutato'
  fase201 `registra`: dedup email rimossa -> 2 candidature
  fase127 `pre_registra`: INSERT OR REPLACE -> INSERT (2 righe di check-in)
  fase88  `reset_password`: impronta single-use ignorata -> magic-link riusabile
  fase88  `registra`: dedup email rimossa -> 2 account con la stessa email
  fase113 `invia`: dedup del testo introdotta -> la chat perde una bolla legittima
  fase83  `_cancella_prenotazione`: replay non riconosciuto -> secondo rimborso pieno
  fase83  `_decidi_richiesta`: CAS di acquisizione tolto -> richiesta approvata due volte
  fase83  `_admin_controversia_risolvi`: guardia 'non_in_controversia' tolta -> secondo split
  fase83  `_admin_rimborso`: bandiera `idempotente` sempre falsa
  fase83  `_host_alloggio_elimina`: 404 mancante sul replay
  fase83  `_foto_elimina`: la 2a eliminazione dichiara fallimento
  fase83  `_admin_cancella_attivita`: il 2o giro mente sui residui
  fase83  `_host_riaccetta`: la ri-firma non lascia piu' traccia nel registro legale
  fase83  `_upload_foto`: nome del file deterministico -> due upload collidono
  fase83  `_preventivo_email`: throttle rimosso -> 2 email uguali

Stdlib pura, zero rete (Stripe/email finti), DB su file temporanei, deterministico.
"""
import datetime
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, sweep_hold_una_passata
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WHSEC = "whsec_idem_profondo"
SLUG = "casa-idem"
CIN_IT = "IT058091C2X5V0ABCD"
PNG1 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
        "60e6kgAAAABJRU5ErkJggg==")

# i conti attesi, al centesimo (interi, mai float) — annuncio 200,00/notte, 2 notti, 2 ospiti
PREZZO_NOTTE = 20000
NOTTI = 2
PARTY = 2
TASSA_PP_NOTTE = 300
NETTO = PREZZO_NOTTE * NOTTI                      # 40000
TASSA = TASSA_PP_NOTTE * NOTTI * PARTY            #  1200
TOTALE = NETTO + TASSA                            # 41200
COMMISSIONE = 4000                                # 10% di 40000
COSTO_CARTA = 1236                                # 3% di 41200
NETTO_HOST = NETTO - COMMISSIONE - COSTO_CARTA    # 34764
# ⛔ DUE FATTI DIVERSI, E VANNO TENUTI DIVERSI (decisione del fondatore, 2026-08-19:
# «la tassa passa all'host»). `NETTO_HOST` e' quello che l'host GUADAGNA dal soggiorno --
# la base di commissione e del report DAC7 -- mentre `VERSATO_HOST` e' quello che gli
# BONIFICHIAMO: il guadagno piu' la tassa di soggiorno, denaro in transito che lui deve
# girare al suo Comune. Sommarle in una voce sola dichiarerebbe al Fisco un reddito che
# l'host non ha. Prima la tassa restava nella nostra cassa, e il libro contabile
# dichiarava un debito verso il Comune che non ci compete (DL 34/2020 art. 180: il
# responsabile del pagamento e' il gestore della struttura).
VERSATO_HOST = NETTO_HOST + TASSA                 # 35964: quello che gli si bonifica


def _fake_stripe_fetch(url, body, headers):
    """Checkout Session finta: nessuna rete."""
    import secrets
    return {"url": "https://stripe.finto/" + secrets.token_hex(4),
            "id": "cs_" + secrets.token_hex(8)}


class _Posta:
    """Provider email finto: registra, non spedisce. Le email partono da thread daemon."""

    def __init__(self):
        self.inviate = []

    def invia(self, dest, oggetto, html):
        self.inviate.append((dest, oggetto, html))
        return True


class _Base(unittest.TestCase):
    """Sistema vero + router vero + un annuncio pubblicato con le date aperte."""

    SU_RICHIESTA = False

    def setUp(self):
        self._env0 = {k: os.environ.get(k) for k in
                      ("UPLOAD_DIR", "TASSE_SOGGIORNO", "PAGA_STRUTTURA_ATTIVO")}
        self.d = tempfile.mkdtemp(prefix="idem_profondo_")
        os.environ["UPLOAD_DIR"] = self.d + "/uploads"
        os.environ["TASSE_SOGGIORNO"] = "roma=350:10:0"
        os.environ["PAGA_STRUTTURA_ATTIVO"] = "0"
        self._fetch0 = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_stripe_fetch)

        d = self.d
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"I" * 32, con_registrazione_host=True,
            db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
            db_accettazioni=d + "/a.db", db_pendenti=d + "/p.db", db_payout=d + "/po.db",
            db_garanzia=d + "/g.db", db_finanza=d + "/f.db", db_messaggi=d + "/m.db",
            db_checkin=d + "/ck.db", db_split=d + "/sp.db", db_tassa_comunale=d + "/t.db",
            db_recensioni=d + "/rec.db", db_viral=d + "/v.db", db_domanda=d + "/dom.db",
            db_partner=d + "/pa.db", db_kyc=d + "/k.db",
            commissione_bps=1000, psp_bps=300, stripe_secret_key="sk",
            stripe_webhook_secret=WHSEC, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/ko"))
        self.posta = _Posta()
        self.sis.email_provider = self.posta
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        if getattr(self.sis, "connect", None) is not None:
            self.sis.connect.trasferisci = lambda *a, **k: "tr_finto"    # mai rete

        s, c = self.g("POST", "/api/host/registrazione", {
            "email": "host@idem.it", "password": "password1", "accetta_termini": True,
            "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
            "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.host_id = c["host_id"]
        self.tk = {"X-Host-Token": c["token"]}
        self.admin = {"X-Admin-Key": "ak"}

        oggi = datetime.date.today()
        self.ci = (oggi + datetime.timedelta(days=40)).isoformat()
        self.co = (oggi + datetime.timedelta(days=40 + NOTTI)).isoformat()
        pubblica = {"slug": SLUG, "titolo": "Attico Idem", "citta": "Roma", "paese": "IT",
                    "cin": CIN_IT, "descrizione": "Attico con terrazza",
                    "prezzo_notte_cents": PREZZO_NOTTE, "capacita": 4,
                    "tassa_pp_notte_cents": TASSA_PP_NOTTE, "servizi": [], "immagini": []}
        if self.SU_RICHIESTA:
            pubblica["modalita_prenotazione"] = "su_richiesta"
        s, p = self.g("POST", "/api/host/pubblica", pubblica, self.tk)
        self.assertEqual(s, 201, p)
        s, disp = self.g("POST", "/api/host/disponibilita_range", {
            "alloggio_id": SLUG, "da": (oggi + datetime.timedelta(days=30)).isoformat(),
            "a": (oggi + datetime.timedelta(days=70)).isoformat(),
            "unita_totali": 5, "prezzo_netto_cents": PREZZO_NOTTE}, self.tk)
        self.assertEqual(s, 200, disp)

    def tearDown(self):
        _stripe.ProviderStripe._fetch_reale = self._fetch0
        for k, v in self._env0.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.d, ignore_errors=True)

    # ── utilita' ────────────────────────────────────────────────────────────────
    def g(self, metodo, path, body=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None,
                               headers or {})

    def due_volte(self, metodo, path, body=None, headers=None, query=None):
        """La STESSA richiesta valida, due volte di fila. Ritorna (esito1, esito2)."""
        e1 = self.g(metodo, path, body, headers, query)
        e2 = self.g(metodo, path, body, headers, query)
        return e1, e2

    def conta(self, file_db, tabella, dove="", parametri=()):
        """Righe in archivio RIAPRENDO il file con una connessione NUOVA (prova vera)."""
        con = sqlite3.connect(os.path.join(self.d, file_db))
        try:
            sql = "SELECT COUNT(*) FROM " + tabella + (" WHERE " + dove if dove else "")
            return int(con.execute(sql, parametri).fetchone()[0])
        finally:
            con.close()

    def righe(self, file_db, sql, parametri=()):
        con = sqlite3.connect(os.path.join(self.d, file_db))
        try:
            return [tuple(r) for r in con.execute(sql, parametri)]
        finally:
            con.close()

    def email_assestate(self, passo=0.35, limite=4.0):
        """Le email partono da thread daemon: aspetta che il conteggio si assesti."""
        fine = time.time() + limite
        prec = -1
        while time.time() < fine:
            n = len(self.posta.inviate)
            if n == prec:
                break
            prec = n
            time.sleep(passo)
        return list(self.posta.inviate)

    def quote(self, ci=None, co=None, **extra):
        corpo = {"alloggio_id": SLUG, "check_in": ci or self.ci,
                 "check_out": co or self.co, "party": PARTY}
        corpo.update(extra)
        s, q = self.g("POST", "/api/concierge/quote", corpo)
        self.assertEqual(s, 200, q)
        return q

    def book(self, email="ospite@idem.it", quote_token=None, **extra):
        corpo = {"quote_token": quote_token or self.quote()["quote_token"],
                 "email": email, "lang": "it"}
        corpo.update(extra)
        return self.g("POST", "/api/concierge/book", corpo)

    def paga(self, riferimento, sessione="cs_pagamento"):
        """Webhook Stripe FIRMATO sul corpo grezzo (come lo manda Stripe)."""
        grezzo = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"id": sessione,
                                                 "metadata": {"riferimento": riferimento}}}})
        firma = firma_di_test(grezzo, WHSEC, int(time.time()))
        return self.r.gestisci("POST", "/api/payments/webhook", {}, grezzo,
                               {"Stripe-Signature": firma})

    def prenotazione_pagata(self, email="ospite@idem.it"):
        s, b = self.book(email=email)
        self.assertEqual(s, 201, b)
        self.assertEqual(self.paga(b["riferimento"])[0], 200)
        return b

    def stato_pendente(self, rif):
        rec = self.sis.pagamenti_pendenti.info(rif)
        return (rec or {}).get("stato")


# ══════════════════════════════════════════════════════════════════════════════
# 1) IL DOPPIO CLIC SUL DENARO: prenota · paga · cancella · rimborsa
# ══════════════════════════════════════════════════════════════════════════════
class TestDoppioClicDenaro(_Base):

    def test_book_doppio_una_sola_prenotazione(self):
        """POST /api/concierge/book ×2: UNA prenotazione, UN blocco, UN escrow, UN payout."""
        qt = self.quote()["quote_token"]
        (s1, b1), (s2, b2) = self.due_volte("POST", "/api/concierge/book",
                                            {"quote_token": qt, "email": "o@idem.it",
                                             "lang": "it"})
        self.assertEqual((s1, s2), (201, 201), (b1, b2))
        self.assertEqual(b1["riferimento"], b2["riferimento"])
        self.assertEqual(b2["stato"], "in_attesa_pagamento")
        self.assertIs(b2["idempotente"], True)
        # STESSO voucher: un secondo gettone firmato = un secondo diritto sulla stessa stanza
        # e le 48h di ripensamento che ripartono da zero.
        self.assertEqual(b1["voucher_token"], b2["voucher_token"])
        # i conti sono identici al centesimo
        for k in ("totale_cents", "prezzo_guest_cents", "netto_host_cents",
                  "commissione_cents", "tassa_soggiorno_cents", "costo_pagamento_cents"):
            self.assertEqual(b1[k], b2[k], k)
        self.assertEqual(b1["totale_cents"], TOTALE)
        # ARCHIVIO RIAPERTO: una riga per archivio, mai due
        self.assertEqual(self.conta("p.db", "pendenti"), 1)
        self.assertEqual(self.conta("g.db", "garanzia"), 1)
        self.assertEqual(self.conta("po.db", "payout"), 1)
        self.assertEqual(self.conta("i.db", "movimenti"), 1)
        # e le notti restano occupate UNA volta sola (mai il doppio consumo di unita')
        self.assertEqual(self.righe("i.db", "SELECT unita_occupate FROM inventario WHERE "
                                            "giorno>=? AND giorno<? ORDER BY giorno",
                                    (self.ci, self.co)), [(1,), (1,)])

    def test_book_doppio_una_sola_email(self):
        """Il doppio clic NON manda due email di conferma allo stesso ospite."""
        qt = self.quote()["quote_token"]
        self.due_volte("POST", "/api/concierge/book",
                       {"quote_token": qt, "email": "o@idem.it", "lang": "it"})
        inviate = self.email_assestate()
        allospite = [o for dest, o, _h in inviate if dest == "o@idem.it"]
        self.assertEqual(len(allospite), 1,
                         "doppio clic = due email identiche all'ospite: %r" % (allospite,))

    def test_webhook_doppio_un_solo_incasso(self):
        """POST /api/payments/webhook ×2 (retry Stripe): un solo incasso, una sola tassa."""
        s, b = self.book()
        self.assertEqual(s, 201, b)
        rif = b["riferimento"]
        # il webhook vuole il corpo GREZZO firmato (non il JSON ri-serializzato): si ripete
        # con l'helper, che firma esattamente gli stessi byte due volte.
        e1 = self.paga(rif)
        e2 = self.paga(rif)
        self.assertEqual(e1, (200, {"ricevuto": True, "tipo": "checkout.session.completed"}))
        self.assertEqual(e2, e1, "il replay del webhook deve dare lo STESSO esito")
        self.assertEqual(self.stato_pendente(rif), "pagato")
        # GIORNALE: esattamente 3 movimenti, con importi e chiavi evento esatte
        mov = self.righe("f.db", "SELECT tipo, importo_cents, evento_id FROM libro_giornale "
                                 "WHERE riferimento=? ORDER BY seq", (rif,))
        self.assertEqual(mov, [("incasso", TOTALE, "incasso:" + rif),
                               ("commissione", COMMISSIONE + COSTO_CARTA,
                                "commissione:" + rif),
                               ("tassa_incassata", TASSA, "tassa_incassata:" + rif)])
        self.assertEqual(self.conta("f.db", "libro_giornale"), 3)
        # TASSA DI SOGGIORNO: una sola riscossione (mai il doppio dovuto al comune)
        self.assertEqual(self.conta("t.db", "tassa_riscossione"), 1)
        # PAYOUT: una riga sola, maturata all'importo esatto
        self.assertEqual(self.righe("po.db", "SELECT prenotazione_id, minori, stato "
                                             "FROM payout"),
                         [(rif, VERSATO_HOST, "maturato")])
        # una sola email di conferma pagamento
        conferme = [o for _d, o, _h in self.email_assestate() if "Pagamento" in o
                    or "Payment" in o]
        self.assertEqual(len(conferme), 1, conferme)

    def test_cancella_doppio_un_solo_rimborso(self):
        """POST /api/concierge/cancella ×2: il 2o e' 'gia_cancellata' e rimborsa ZERO."""
        b = self.prenotazione_pagata()
        (s1, c1), (s2, c2) = self.due_volte("POST", "/api/concierge/cancella",
                                            {"voucher_token": b["voucher_token"]})
        self.assertEqual(s1, 200, c1)
        self.assertEqual(c1["stato"], "cancellata")
        self.assertEqual(c1["rimborso_cents"], TOTALE)
        self.assertEqual(s2, 200, c2)
        self.assertEqual(c2["stato"], "gia_cancellata")
        self.assertEqual(c2["rimborso_cents"], 0, "secondo rimborso sulla stessa prenotazione")
        self.assertEqual(c2["credito_viaggio_cents"], 0)
        self.assertEqual(self.stato_pendente(b["riferimento"]), "rimborsato")
        # l'escrow resta CHIUSO: nessun soldo verso l'host su una prenotazione rimborsata
        self.assertEqual(self.righe("g.db", "SELECT stato, host_riceve_cents FROM garanzia "
                                            "WHERE prenotazione_id=?", (b["riferimento"],)),
                         [("annullato", 0)])

    def test_admin_rimborso_doppio_una_sola_riga_di_giornale(self):
        """POST /api/admin/rimborso ×2: il 2o si dichiara idempotente e NON scrive di nuovo."""
        b = self.prenotazione_pagata()
        rif = b["riferimento"]
        idem = self.sis.pagamenti_pendenti.info(rif)["idem_key"]
        corpo = {"alloggio_id": SLUG, "check_in": self.ci, "check_out": self.co,
                 "idem_key": idem}
        (s1, r1), (s2, r2) = self.due_volte("POST", "/api/admin/rimborso", corpo, self.admin)
        self.assertEqual((s1, s2), (200, 200), (r1, r2))
        self.assertEqual(r1["stato"], "rimborsato")
        self.assertIs(r1["idempotente"], False)
        self.assertEqual(r2["stato"], "rimborsato")
        self.assertIs(r2["idempotente"], True)
        # UN SOLO movimento di rimborso nel giornale (mai due volte lo stesso denaro reso)
        rimborsi = self.righe("f.db", "SELECT importo_cents, evento_id FROM libro_giornale "
                                      "WHERE riferimento=? AND tipo='rimborso'", (rif,))
        self.assertEqual(rimborsi, [(TOTALE, "rimborso:" + rif)])
        self.assertEqual(self.stato_pendente(rif), "rimborsato")
        self.assertEqual(self.sis.payout.stato_di(rif), "trattenuto")

    def test_garanzia_conferma_doppia_un_solo_rilascio(self):
        """POST /api/garanzia/conferma ×2: il 2o e' 409, l'host non incassa due volte."""
        b = self.prenotazione_pagata()
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/garanzia/conferma",
                                            {"voucher_token": b["voucher_token"]})
        self.assertEqual((s1, o1), (200, {"ok": True, "stato": "rilasciato",
                                          "host_riceve_cents": VERSATO_HOST,
                                          "ospite_rimborso_cents": 0}))
        self.assertEqual((s2, o2), (409, {"ok": False, "motivo": "stato_non_valido",
                                          "stato": "rilasciato"}))
        self.assertEqual(self.righe("g.db", "SELECT stato, host_riceve_cents FROM garanzia"),
                         [("rilasciato", VERSATO_HOST)])
        self.assertEqual(self.conta("g.db", "garanzia"), 1)

    def test_garanzia_contesta_doppia_una_sola_disputa(self):
        """POST /api/garanzia/contesta ×2: il 2o e' 409, il payout resta trattenuto UNA volta."""
        b = self.prenotazione_pagata()
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/garanzia/contesta",
                                            {"voucher_token": b["voucher_token"],
                                             "motivo": "muffa in bagno"})
        self.assertEqual((s1, o1), (200, {"ok": True, "stato": "contestato",
                                          "host_riceve_cents": 0,
                                          "ospite_rimborso_cents": 0}))
        self.assertEqual((s2, o2), (409, {"ok": False, "motivo": "stato_non_valido",
                                          "stato": "contestato"}))
        self.assertEqual(self.sis.payout.stato_di(b["riferimento"]), "trattenuto")
        self.assertEqual(self.conta("po.db", "payout"), 1)

    def test_controversia_risolvi_doppia_uno_solo_split(self):
        """POST /api/admin/controversia/risolvi ×2: il 2o e' 409, il payout non raddoppia."""
        b = self.prenotazione_pagata()
        self.assertEqual(self.g("POST", "/api/garanzia/contesta",
                                {"voucher_token": b["voucher_token"],
                                 "motivo": "rumore"})[0], 200)
        corpo = {"riferimento": b["riferimento"], "percentuale_ospite": 50}
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/admin/controversia/risolvi",
                                            corpo, self.admin)
        self.assertEqual(s1, 200, o1)
        self.assertEqual(o1["stato"], "risolta")
        self.assertEqual(o1["rimborso_cliente_cents"], VERSATO_HOST // 2)
        self.assertEqual(o1["va_all_host_cents"], VERSATO_HOST - VERSATO_HOST // 2)
        self.assertEqual((s2, o2), (409, {"errore": "non_in_controversia",
                                          "stato": "risolto"}))
        self.assertEqual(self.righe("po.db", "SELECT minori, stato FROM payout"),
                         [(VERSATO_HOST - VERSATO_HOST // 2, "maturato")])
        self.assertEqual(self.conta("g.db", "garanzia"), 1)

    def test_split_crea_doppio_un_solo_conto(self):
        """POST /api/split/crea ×2: UN conto per prenotazione, quote NON duplicate."""
        b = self.prenotazione_pagata()
        corpo = {"prenotazione_id": b["riferimento"], "alloggio_id": SLUG,
                 "totale_cents": TOTALE, "partecipanti": ["anna", "bruno", "carla"]}
        (s1, c1), (s2, c2) = self.due_volte("POST", "/api/split/crea", corpo)
        self.assertEqual((s1, s2), (201, 201), (c1, c2))
        self.assertEqual(c1["conto_id"], c2["conto_id"],
                         "secondo conto di gruppo per la STESSA prenotazione")
        self.assertEqual(self.conta("sp.db", "conti"), 1)
        self.assertEqual(self.conta("sp.db", "quote"), 3)
        self.assertEqual([q["dovuto_cents"] for q in c2["stato"]["quote"]],
                         [13734, 13733, 13733])
        self.assertEqual(sum(q["dovuto_cents"] for q in c2["stato"]["quote"]), TOTALE)

    def test_split_paga_doppio_non_raccoglie_due_volte(self):
        """POST /api/split/paga ×2: il 2o e' idempotente, il raccolto non raddoppia."""
        b = self.prenotazione_pagata()
        s, c = self.g("POST", "/api/split/crea",
                      {"prenotazione_id": b["riferimento"], "alloggio_id": SLUG,
                       "totale_cents": TOTALE, "metodo": "importi",
                       "partecipanti": ["anna", "bruno"],
                       "importi": {"anna": 20000, "bruno": 21200}})
        self.assertEqual(s, 201, c)
        cid = c["conto_id"]
        (s1, p1), (s2, p2) = self.due_volte("POST", "/api/split/paga",
                                            {"conto_id": cid, "partecipante_id": "anna"})
        self.assertEqual((s1, p1), (200, {"stato": "pagato", "completato": False,
                                          "idempotente": False}))
        self.assertEqual((s2, p2), (200, {"stato": "pagato", "completato": False,
                                          "idempotente": True}))
        s, st = self.g("GET", "/api/split/stato", None, None, {"conto_id": cid})
        self.assertEqual((s, st["raccolto_cents"], st["mancante_cents"]),
                         (200, 20000, TOTALE - 20000))


# ══════════════════════════════════════════════════════════════════════════════
# 2) IL DOPPIO CLIC A DISTANZA DI TEMPO (orologio iniettato avanti)
# ══════════════════════════════════════════════════════════════════════════════
class TestDoppioClicNelTempo(_Base):

    def test_book_dopo_pagamento_niente_secondo_addebito(self):
        """Ripresentare lo STESSO preventivo DOPO aver pagato: nessun secondo link di
        pagamento, nessuna seconda email, nessun movimento in piu'."""
        qt = self.quote()["quote_token"]
        s, b1 = self.book(quote_token=qt)
        self.assertEqual(s, 201, b1)
        rif = b1["riferimento"]
        self.assertEqual(self.paga(rif)[0], 200)
        self.email_assestate()
        prima = len(self.posta.inviate)
        s2, b2 = self.book(quote_token=qt)
        self.assertEqual(s2, 201, b2)
        self.assertEqual(b2["riferimento"], rif)
        self.assertEqual(b2["stato"], "pagata")
        self.assertIs(b2["idempotente"], True)
        self.assertNotIn("payment_url", b2,
                         "secondo link di pagamento a chi ha GIA' pagato = doppio addebito")
        self.assertEqual(b2["voucher_token"], b1["voucher_token"])
        self.assertEqual(len(self.email_assestate()), prima,
                         "email 'completa il pagamento' a chi ha gia' pagato")
        self.assertEqual(self.stato_pendente(rif), "pagato")
        self.assertEqual(self.conta("f.db", "libro_giornale"), 3)
        self.assertEqual(self.conta("t.db", "tassa_riscossione"), 1)
        self.assertEqual(self.righe("po.db", "SELECT minori, stato FROM payout"),
                         [(VERSATO_HOST, "maturato")])

    def test_book_dopo_rimborso_rifiutato(self):
        """Ripresentare lo STESSO preventivo DOPO la cancellazione col rimborso: rifiuto
        pulito 409 e l'escrow NON si riapre."""
        qt = self.quote()["quote_token"]
        s, b = self.book(quote_token=qt)
        self.assertEqual(s, 201, b)
        rif = b["riferimento"]
        self.assertEqual(self.paga(rif)[0], 200)
        self.assertEqual(self.g("POST", "/api/concierge/cancella",
                                {"voucher_token": b["voucher_token"]})[0], 200)
        self.assertEqual(self.stato_pendente(rif), "rimborsato")
        s2, b2 = self.book(quote_token=qt)
        self.assertEqual(s2, 409, b2)
        self.assertEqual(b2["errore"], "prenotazione_annullata")
        self.assertEqual(b2["stato"], "rifiutata")
        self.assertEqual(b2["riferimento"], rif)
        self.assertEqual(self.righe("g.db", "SELECT stato, host_riceve_cents FROM garanzia"),
                         [("annullato", 0)],
                         "escrow RIAPERTO su una prenotazione gia' rimborsata")
        self.assertEqual(self.stato_pendente(rif), "rimborsato")
        self.assertEqual(self.conta("p.db", "pendenti"), 1)

    def test_book_dopo_scadenza_rifiutato(self):
        """Orologio AVANTI: hold scaduto e date liberate dallo sweeper. Ripresentare lo
        stesso preventivo -> rifiuto pulito, nessun payout ne' escrow fantasma."""
        qt = self.quote()["quote_token"]
        s, b = self.book(quote_token=qt)
        self.assertEqual(s, 201, b)
        rif = b["riferimento"]
        self.assertEqual(self.conta("po.db", "payout"), 1)
        # +1 ora: lo sweeper vede l'hold scaduto, libera le date e toglie il payout
        self.sis.pagamenti_pendenti._now = lambda: int(time.time()) + 3600
        sweep_hold_una_passata(self.sis, self.r)
        self.assertEqual(self.stato_pendente(rif), "scaduto")
        self.assertEqual(self.conta("po.db", "payout"), 0)
        self.assertEqual(self.righe("i.db", "SELECT unita_occupate FROM inventario WHERE "
                                            "giorno>=? AND giorno<?", (self.ci, self.co)),
                         [(0,), (0,)])
        s2, b2 = self.book(quote_token=qt)
        self.assertEqual(s2, 409, b2)
        self.assertEqual(b2["errore"], "preventivo_scaduto")
        self.assertEqual(b2["stato"], "rifiutata")
        # nessun guadagno fantasma e nessun escrow che poi si auto-rilascia all'host
        self.assertEqual(self.conta("po.db", "payout"), 0,
                         "payout FANTASMA su una prenotazione mai pagata")
        self.assertEqual(self.righe("g.db", "SELECT stato FROM garanzia"), [("annullato",)],
                         "escrow riaperto: l'auto-rilascio avrebbe pagato l'host")
        self.assertEqual(self.righe("i.db", "SELECT unita_occupate FROM inventario WHERE "
                                            "giorno>=? AND giorno<?", (self.ci, self.co)),
                         [(0,), (0,)])

    def test_recensione_doppia_una_sola_riga(self):
        """Orologio AVANTI (soggiorno finito): POST /api/recensioni ×2 -> 201 poi 409."""
        b = self.prenotazione_pagata()
        self.sis.recensioni._now = lambda: int(time.time()) + 60 * 86400
        corpo = {"token": b["diritto_recensione"], "voto": 5,
                 "testo": "Bellissimo posto, tornerei", "lingua": "it"}
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/recensioni", corpo)
        self.assertEqual((s1, o1), (201, {"ok": True, "motivo": "", "verificata": True}))
        self.assertEqual((s2, o2), (409, {"ok": False, "motivo": "gia_recensita",
                                          "verificata": False}))
        self.assertEqual(self.conta("rec.db", "recensioni"), 1)

    def test_preventivo_email_doppio_una_sola_email(self):
        """POST /api/preventivo/email ×2: la seconda e' respinta 429 (anti-spam), 1 email."""
        corpo = {"alloggio_id": SLUG, "check_in": self.ci, "check_out": self.co,
                 "party": PARTY, "email": "prev@idem.it", "lang": "it"}
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/preventivo/email", corpo)
        self.assertEqual((s1, o1), (200, {"stato": "inviata"}))
        self.assertEqual((s2, o2), (429, {"errore": "gia_inviato_riprova_piu_tardi"}))
        prev = [d for d, _o, _h in self.email_assestate() if d == "prev@idem.it"]
        self.assertEqual(len(prev), 1, prev)

    def test_password_reset_doppio_link_bruciato(self):
        """Il magic-link di reset e' SINGLE-USE: il secondo clic e' respinto pulito."""
        import re
        self.assertEqual(self.g("POST", "/api/host/password_dimenticata",
                                {"email": "host@idem.it"})[0], 200)
        tok = ""
        for _d, _o, html in self.email_assestate():
            m = re.search(r"#reset=([^\"'\s>]+)", html)
            if m:
                tok = m.group(1)
        self.assertTrue(tok, "nessun magic-link di reset nell'email")
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/host/password_reset",
                                            {"token": tok, "password": "nuovaPass9"})
        self.assertEqual(s1, 200, o1)
        self.assertIs(o1["ok"], True)
        self.assertEqual(o1["host_id"], self.host_id)
        self.assertEqual((s2, o2["ok"], o2["errore"]), (400, False, "link_non_valido"))
        # la password nuova vale (una sola volta), la vecchia no
        self.assertEqual(self.g("POST", "/api/host/login",
                                {"email": "host@idem.it", "password": "nuovaPass9"})[0], 200)
        self.assertEqual(self.g("POST", "/api/host/login",
                                {"email": "host@idem.it", "password": "password1"})[0], 401)


# ══════════════════════════════════════════════════════════════════════════════
# 3) IL DOPPIO CLIC SUL CATALOGO E SUI DATI DELL'HOST
# ══════════════════════════════════════════════════════════════════════════════
class TestDoppioClicCatalogo(_Base):

    def test_pubblica_doppia_un_solo_annuncio(self):
        """POST /api/host/pubblica ×2 con lo stesso slug: un solo annuncio, stesso id."""
        corpo = {"slug": "casa-bis", "titolo": "Bilocale Bis", "citta": "Roma",
                 "paese": "IT", "cin": CIN_IT, "descrizione": "Bilocale luminoso",
                 "prezzo_notte_cents": 9000, "capacita": 2, "servizi": [], "immagini": []}
        (s1, p1), (s2, p2) = self.due_volte("POST", "/api/host/pubblica", corpo, self.tk)
        self.assertEqual((s1, s2), (201, 201), (p1, p2))
        self.assertEqual(p1, p2)
        self.assertEqual(p1["stato"], "pubblicato")
        self.assertEqual(p1["slug"], "casa-bis")
        self.assertEqual(self.conta("c.db", "alloggi", "slug=?", ("casa-bis",)), 1)
        self.assertEqual(self.conta("c.db", "alloggi"), 2)      # quello del setUp + questo

    def test_disponibilita_range_doppio_stesse_notti(self):
        """POST /api/host/disponibilita_range ×2: le stesse 40 notti (non 80) e — soprattutto
        — le notti GIA' PRENOTATE restano occupate: riaprire il periodo non cancella chi c'e'
        gia' dentro (sarebbe overbooking silenzioso al secondo clic)."""
        s, b = self.book()
        self.assertEqual(s, 201, b)
        oggi = datetime.date.today()
        corpo = {"alloggio_id": SLUG, "da": (oggi + datetime.timedelta(days=30)).isoformat(),
                 "a": (oggi + datetime.timedelta(days=70)).isoformat(),
                 "unita_totali": 5, "prezzo_netto_cents": PREZZO_NOTTE}
        (s1, d1), (s2, d2) = self.due_volte("POST", "/api/host/disponibilita_range",
                                            corpo, self.tk)
        self.assertEqual((s1, d1), (200, {"giorni_impostati": 40}))
        self.assertEqual((s2, d2), (200, {"giorni_impostati": 40}))
        self.assertEqual(self.conta("i.db", "inventario"), 40)
        self.assertEqual(self.righe("i.db", "SELECT unita_totali, prezzo_netto_cents, "
                                            "unita_occupate FROM inventario WHERE "
                                            "giorno>=? AND giorno<? ORDER BY giorno",
                                    (self.ci, self.co)),
                         [(5, PREZZO_NOTTE, 1), (5, PREZZO_NOTTE, 1)])
        self.assertEqual(self.conta("i.db", "movimenti"), 1)

    def test_disponibilita_giorno_doppio_una_sola_riga(self):
        """POST /api/host/disponibilita ×2: la notte resta UNA riga con i valori nuovi."""
        corpo = {"alloggio_id": SLUG, "giorno": self.ci, "unita_totali": 3,
                 "prezzo_netto_cents": 19000}
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/host/disponibilita",
                                            corpo, self.tk)
        self.assertEqual((s1, o1), (200, {"stato": "ok"}))
        self.assertEqual((s2, o2), (200, {"stato": "ok"}))
        self.assertEqual(self.conta("i.db", "inventario", "giorno=?", (self.ci,)), 1)
        self.assertEqual(self.righe("i.db", "SELECT unita_totali, prezzo_netto_cents "
                                            "FROM inventario WHERE giorno=?", (self.ci,)),
                         [(3, 19000)])
        self.assertEqual(self.conta("i.db", "inventario"), 40)

    def test_host_stato_doppio_stesso_stato(self):
        """POST /api/host/stato ×2: l'annuncio resta uno, nello stato chiesto."""
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/host/stato",
                                            {"slug": SLUG, "stato": "sospeso"}, self.tk)
        self.assertEqual((s1, o1), (200, {"stato": "sospeso"}))
        self.assertEqual((s2, o2), (200, {"stato": "sospeso"}))
        self.assertEqual(self.righe("c.db", "SELECT stato FROM alloggi WHERE slug=?",
                                    (SLUG,)), [("sospeso",)])
        self.assertEqual(self.conta("c.db", "alloggi"), 1)

    def test_admin_alloggio_stato_doppio_stesso_stato(self):
        """POST /api/admin/alloggio_stato ×2: idem lato admin, nessuna riga in piu'."""
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/admin/alloggio_stato",
                                            {"slug": SLUG, "stato": "sospeso"}, self.admin)
        self.assertEqual((s1, o1), (200, {"stato": "sospeso"}))
        self.assertEqual((s2, o2), (200, {"stato": "sospeso"}))
        self.assertEqual(self.conta("c.db", "alloggi"), 1)
        self.assertEqual(self.righe("c.db", "SELECT stato FROM alloggi WHERE slug=?",
                                    (SLUG,)), [("sospeso",)])

    def test_alloggio_elimina_doppio_404_pulito(self):
        """POST /api/host/alloggio_elimina ×2: eliminato, poi 404 onesto."""
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/host/alloggio_elimina",
                                            {"slug": SLUG}, self.tk)
        self.assertEqual((s1, o1), (200, {"stato": "eliminato", "slug": SLUG}))
        self.assertEqual((s2, o2), (404, {"errore": "non_trovato"}))
        self.assertEqual(self.conta("c.db", "alloggi"), 0)

    def test_foto_elimina_doppio_idempotente(self):
        """POST /api/host/foto_elimina ×2: il file sparisce, il 2o clic non e' un errore."""
        s, up = self.g("POST", "/api/host/upload_foto",
                       {"alloggio_id": SLUG, "image_base64": PNG1}, self.tk)
        self.assertEqual(s, 201, up)
        percorso = os.path.join(os.environ["UPLOAD_DIR"], up["url"].split("/")[-1])
        self.assertTrue(os.path.isfile(percorso))
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/host/foto_elimina",
                                            {"url": up["url"]}, self.tk)
        self.assertEqual((s1, o1), (200, {"eliminata": True}))
        self.assertEqual((s2, o2), (200, {"eliminata": True}))
        self.assertFalse(os.path.exists(percorso))

    def test_registrazione_host_doppia_un_solo_account(self):
        """POST /api/host/registrazione ×2 con la stessa email: 201 poi 422 esplicito."""
        corpo = {"email": "nuovo@idem.it", "password": "password1",
                 "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
                 "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE}
        (s1, c1), (s2, c2) = self.due_volte("POST", "/api/host/registrazione", corpo)
        self.assertEqual(s1, 201, c1)
        self.assertIs(c1["ok"], True)
        self.assertEqual((s2, c2), (422, {"ok": False, "errore": "email_gia_registrata"}))
        self.assertEqual(self.conta("r.db", "host", "email=?", ("nuovo@idem.it",)), 1)
        self.assertEqual(self.conta("r.db", "host"), 2)          # quello del setUp + questo

    def test_domanda_doppia_una_sola_riga(self):
        """POST /api/domanda ×2 (stessa email, stessa citta'): UNA riga in lista d'attesa."""
        corpo = {"email": "ospite@idem.it", "citta": "Milano"}
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/domanda", corpo)
        self.assertEqual(s1, 201, o1)
        self.assertIs(o1["ok"], True)
        self.assertEqual(s2, 201, o2)
        self.assertIs(o2["ok"], True)
        self.assertEqual(self.conta("dom.db", "domanda"), 1)
        self.assertEqual(self.conta("dom.db", "domanda", "email=? AND citta=?",
                                    ("ospite@idem.it", "milano")), 1)

    def test_partner_doppio_una_sola_candidatura(self):
        """POST /api/partner ×2: dedup per email, una sola candidatura in archivio."""
        corpo = {"nome": "Anna Creator", "email": "anna@idem.it", "tipo": "creator",
                 "citta": "Milano", "messaggio": "Blog di viaggi", "consenso": True}
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/partner", corpo)
        self.assertEqual((s1, o1), (201, {"ok": True}))
        self.assertEqual((s2, o2), (201, {"ok": True}))
        self.assertEqual(self.conta("pa.db", "partner"), 1)
        s, elenco = self.g("GET", "/api/admin/partner", None, self.admin)
        self.assertEqual((s, elenco["totale"]), (200, 1))

    def test_checkin_doppio_stessi_ospiti(self):
        """POST /api/checkin/pre_registra ×2: una sola pre-registrazione, ospiti non doppi."""
        b = self.prenotazione_pagata()
        corpo = {"voucher_token": b["voucher_token"],
                 "ospiti": [{"nome": "Mario Rossi", "documento": "AB12345"},
                            {"nome": "Lucia Bianchi", "documento": "CD67890"}]}
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/checkin/pre_registra", corpo)
        self.assertEqual((s1, o1), (200, {"ok": True, "ospiti": 2}))
        self.assertEqual((s2, o2), (200, {"ok": True, "ospiti": 2}))
        self.assertEqual(self.conta("ck.db", "checkin"), 1)
        self.assertEqual(self.g("GET", "/api/checkin/stato", None, None,
                                {"voucher_token": b["voucher_token"]}),
                         (200, {"completato": True}))

    def test_admin_cancella_attivita_doppia_niente_da_cancellare(self):
        """POST /api/admin/cancella_attivita ×2: il 2o giro cancella ZERO (gia' pulito)."""
        corpo = {"host_id": self.host_id, "motivo": "richiesta GDPR"}
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/admin/cancella_attivita",
                                            corpo, self.admin)
        self.assertEqual(s1, 200, o1)
        self.assertIs(o1["ok"], True)
        self.assertEqual(o1["cancellati"], {"inventario": 40, "alloggi": 1,
                                            "messaggi": 0, "host": 1})
        self.assertEqual(s2, 200, o2)
        self.assertEqual(o2["cancellati"], {"inventario": 0, "alloggi": 0,
                                            "messaggi": 0, "host": 0})
        self.assertEqual(o2["residui"], {"alloggi": 0, "inventario": 0,
                                         "messaggi": 0, "host": 0})
        self.assertEqual(self.conta("c.db", "alloggi"), 0)
        self.assertEqual(self.conta("i.db", "inventario"), 0)
        self.assertEqual(self.conta("r.db", "host"), 0)


# ══════════════════════════════════════════════════════════════════════════════
# 4) SU RICHIESTA: la decisione dell'host si prende UNA volta sola
# ══════════════════════════════════════════════════════════════════════════════
class TestDoppioClicSuRichiesta(_Base):
    SU_RICHIESTA = True

    def test_approva_doppia_una_sola_finalizzazione(self):
        """POST /api/host/richieste/approva ×2: approvata, poi 404 (gia' evasa)."""
        s, b = self.book()
        self.assertEqual(s, 201, b)
        self.assertEqual(b["stato"], "in_attesa_host")
        self.assertNotIn("payment_url", b)
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/host/richieste/approva",
                                            {"riferimento": b["riferimento"]}, self.tk)
        self.assertEqual(s1, 200, o1)
        self.assertEqual(o1["stato"], "approvata")
        self.assertEqual(o1["riferimento"], b["riferimento"])
        self.assertEqual((s2, o2), (404, {"errore": "richiesta_non_trovata"}))
        # UNA finalizzazione: un escrow, un payout, un pendente
        self.assertEqual(self.conta("g.db", "garanzia"), 1)
        self.assertEqual(self.conta("po.db", "payout"), 1)
        self.assertEqual(self.conta("p.db", "pendenti"), 1)
        self.assertEqual(self.righe("g.db", "SELECT importo_host_cents, stato FROM garanzia"),
                         [(VERSATO_HOST, "in_garanzia")])

    def test_rifiuta_dopo_approva_non_disfa(self):
        """Approvata e poi RIFIUTATA per sbaglio: la decisione presa non si disfa da sola."""
        s, b = self.book()
        self.assertEqual(s, 201, b)
        self.assertEqual(self.g("POST", "/api/host/richieste/approva",
                                {"riferimento": b["riferimento"]}, self.tk)[0], 200)
        s2, o2 = self.g("POST", "/api/host/richieste/rifiuta",
                        {"riferimento": b["riferimento"]}, self.tk)
        self.assertEqual((s2, o2), (404, {"errore": "richiesta_non_trovata"}))
        self.assertEqual(self.conta("g.db", "garanzia"), 1)
        self.assertEqual(self.righe("g.db", "SELECT stato FROM garanzia"),
                         [("in_garanzia",)])


# ══════════════════════════════════════════════════════════════════════════════
# 5) RIPETIZIONI CHE NON SONO DUPLICATI (comportamento VOLUTO, qui documentato
#    e bloccato: se domani cambia, questo collaudo se ne accorge)
# ══════════════════════════════════════════════════════════════════════════════
class TestRipetizioniLegittime(_Base):

    def test_chat_stesso_testo_due_bolle(self):
        """La chat NON e' idempotente per scelta: mandare due volte lo stesso testo fa due
        bolle (in una conversazione ripetersi e' legittimo). Il filo resta coerente e
        ordinato: nessuno stato incoerente, nessun soldo coinvolto."""
        b = self.prenotazione_pagata()
        corpo = {"voucher_token": b["voucher_token"], "testo": "A che ora posso entrare?"}
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/voucher/messaggio", corpo)
        self.assertEqual((s1, o1), (201, {"stato": "inviato"}))
        self.assertEqual((s2, o2), (201, {"stato": "inviato"}))
        self.assertEqual(self.conta("m.db", "messaggi"), 2)
        s, th = self.g("GET", "/api/voucher/messaggi", None, None,
                       {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, th)
        self.assertEqual([m["testo"] for m in th["messaggi"]],
                         ["A che ora posso entrare?", "A che ora posso entrare?"])
        self.assertEqual([m["mittente"] for m in th["messaggi"]], ["ospite", "ospite"])
        self.assertLessEqual(th["messaggi"][0]["ts"], th["messaggi"][1]["ts"])

    def test_riaccetta_ogni_firma_e_una_prova_a_se(self):
        """Il registro delle accettazioni e' un libro in SOLA AGGIUNTA (prova legale): ogni
        ri-accettazione lascia la sua riga datata e firmata, anche se il testo e' lo stesso.
        Non e' un duplicato: e' la storia. Righe = 2 per firma (contratto + privacy)."""
        prima = self.conta("a.db", "accettazioni")
        corpo = {"accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
                 "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE}
        (s1, o1), (s2, o2) = self.due_volte("POST", "/api/host/riaccetta", corpo, self.tk)
        self.assertEqual(s1, 200, o1)
        self.assertEqual(s2, 200, o2)
        self.assertIs(o1["accettazione"]["registrata"], True)
        self.assertEqual(o1, o2)                       # stesso ESITO, sempre
        self.assertEqual(self.conta("a.db", "accettazioni"), prima + 4)
        # nessuno stato incoerente sul contratto in vigore: l'host resta IN REGOLA e non
        # gli viene richiesta un'altra firma per la stessa versione
        s, st = self.g("GET", "/api/host/contratto_stato", None, self.tk)
        self.assertEqual(s, 200, st)
        self.assertIs(st["deve_riaccettare"], False, st)
        self.assertEqual(st["versione_accettata"], CONTRATTO_HOST_VERSIONE, st)

    def test_upload_foto_doppio_due_file_distinti(self):
        """Due upload = due file (il contenuto puo' essere uguale, il nome no): nessun
        annuncio ne' riga di catalogo in piu'. Gli orfani li chiude la pulizia periodica."""
        corpo = {"alloggio_id": SLUG, "image_base64": PNG1}
        (s1, u1), (s2, u2) = self.due_volte("POST", "/api/host/upload_foto", corpo, self.tk)
        self.assertEqual((s1, s2), (201, 201), (u1, u2))
        self.assertNotEqual(u1["url"], u2["url"])
        for u in (u1, u2):
            self.assertTrue(u["url"].startswith("/uploads/"), u["url"])
            self.assertTrue(os.path.isfile(os.path.join(os.environ["UPLOAD_DIR"],
                                                        u["url"].split("/")[-1])))
        self.assertEqual(self.conta("c.db", "alloggi"), 1)
        self.assertEqual(self.conta("c.db", "alloggio_immagini"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
