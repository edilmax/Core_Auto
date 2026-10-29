"""Collaudo FINANCIAL CONTROLLER (fase177) — Scatto ①: Giornale + Note + Offset.

Invarianti difesi:
  1. IMMUTABILITA' VERA: UPDATE/DELETE sul giornale ABORTISCONO nel database stesso;
     manomissione col trucco (drop del trigger + riscrittura) -> la CATENA DI HASH
     la denuncia (verifica_catena punta la riga rotta);
  2. IDEMPOTENZA: stesso evento_id due volte = UNA riga (stesso seq);
  3. NOTE: ND/NC numerate per anno, vincolate a [riferimento, causale, ts, emittente];
     correzione = STORNO (nota contraria), mai modifica;
  4. OFFSET al centesimo: penale 100 su payout 60+30 (FIFO) -> compensa 90, residuo 10
     a debito 'aperto'; conservazione Σoffset+residuo == penale; il payout della
     prenotazione cancellata NON si tocca; valute diverse NON si mischiano;
  5. ATOMICITA' end-to-end (_host_cancella): il 200 arriva SOLO con la ND nel
     giornale; doppio click = UNA sola ND; gara admin-rimborso vs host-cancella:
     se vince l'admin NESSUNA ND spuria;
  6. GOLDEN "saldo 0": ospite rimborsato + date libere + ND + debito aperto pieno
     (scatto ①: la riscossione carta/Debt Status arriva negli scatti ②-③);
  7. RIASSERZIONE (pattern #32): cancellata_host con penale ma senza ND (crash
     simulato) -> lo sweeper la sana, senza doppiare gli offset.
"""
import hashlib
import hmac
import json
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, sweep_hold_una_passata
from fase177_financial_controller import crea_financial_controller
from unittest import mock

import fase59_concierge

# IL PREVENTIVO SI CHIEDE PRIMA DEL SOGGIORNO (bombe a tempo del lotto D, 2026-10-10): il passato
# non si vende piu', e le date fisse di questo file si quotano con l'orologio del preventivo fermo
# al 1 gennaio 2026, prima di tutte; il resto del sistema resta sull'ora vera.
_PREVENTIVO_PRIMA = mock.patch.object(fase59_concierge, "time",
                                      mock.Mock(time=lambda: 1767225600))


def setUpModule():
    _PREVENTIVO_PRIMA.start()


def tearDownModule():
    _PREVENTIVO_PRIMA.stop()


SEG = b"h" * 32
HK = {"X-Host-Key": "hk"}
AK = {"X-Admin-Key": "ak"}
WHSEC = "whsec_test"
CI, CO = "2027-11-10", "2027-11-12"


class TestGiornale(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = f"{self.dir}/fin.db"
        self.fc = crea_financial_controller(self.db)
        self.fc.inizializza_schema()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _mv(self, ev, importo=1000):
        return self.fc.registra(evento_id=ev, tipo="nota_debito", riferimento="R1",
                                soggetto="host:h1", conto_dare="crediti_vs_host",
                                conto_avere="ricavi_penali", importo_cents=importo,
                                valuta="EUR", causale="test", emittente="sistema")

    def test_append_only_forzato_dal_db(self):
        self._mv("e1")
        con = sqlite3.connect(self.db)
        with self.assertRaises(sqlite3.DatabaseError):
            con.execute("UPDATE libro_giornale SET importo_cents=1 WHERE seq=1")
        with self.assertRaises(sqlite3.DatabaseError):
            con.execute("DELETE FROM libro_giornale")
        con.close()

    def test_catena_hash_denuncia_la_manomissione(self):
        for i in range(5):
            self._mv("e%d" % i, importo=1000 + i)
        self.assertTrue(self.fc.verifica_catena()["ok"])
        # attaccante furbo: droppa il trigger e riscrive una riga a mano
        con = sqlite3.connect(self.db)
        con.execute("DROP TRIGGER lg_no_update")
        with con:
            con.execute("UPDATE libro_giornale SET importo_cents=1 WHERE seq=3")
        con.close()
        v = self.fc.verifica_catena()
        self.assertFalse(v["ok"])
        self.assertEqual(v["seq_rotta"], 3)

    def test_idempotenza_stesso_evento(self):
        a = self._mv("stesso")
        b = self._mv("stesso")
        self.assertFalse(a["idempotente"])
        self.assertTrue(b["idempotente"])
        self.assertEqual(a["seq"], b["seq"])
        self.assertEqual(len(self.fc.movimenti("R1")), 1)

    def test_gara_scritture_catena_intatta(self):
        via = threading.Barrier(8)
        def scrivi(i):
            via.wait()
            for k in range(10):
                self._mv("g%d-%d" % (i, k))
        ths = [threading.Thread(target=scrivi, args=(i,)) for i in range(8)]
        for t in ths:
            t.start()
        for t in ths:
            t.join(timeout=60)
        v = self.fc.verifica_catena()
        self.assertTrue(v["ok"], v)
        self.assertEqual(len(self.fc.movimenti("R1")), 80)

    def test_note_vincoli_e_storno(self):
        n = self.fc.emetti_nota(tipo="debito", riferimento="TX9", soggetto="host:h1",
                                importo_cents=3120, valuta="EUR",
                                causale="penale 15% cancellazione host",
                                emittente="admin")
        self.assertTrue(n["nota_id"].startswith("ND-"))
        salvata = self.fc.nota(n["nota_id"])
        for campo in ("riferimento", "causale", "ts", "emittente"):
            self.assertTrue(salvata.get(campo), campo)
        st = self.fc.storna_nota(n["nota_id"], emittente="admin", causale="errore")
        self.assertTrue(st["nota_id"].startswith("NC-"))
        self.assertEqual(self.fc.nota(n["nota_id"])["stato"], "stornata")
        self.assertIsNone(self.fc.storna_nota(n["nota_id"], emittente="admin",
                                              causale="doppio"), "doppio storno vietato")
        self.assertTrue(self.fc.verifica_catena()["ok"])


class _BancoOffset(unittest.TestCase):
    """Il sistema vero col giornale (fase177), pendenti, bonifici e garanzia, e il router. Lo usa
    anche test_fase83_server per le guardie della voce 137: il Giudice della mutazione accende per
    primo il test DEDICATO del modulo (`scegli_sorveglianti`), e questo file per fase83 restava
    fuori dagli otto occhi. L'orologio del preventivo fermo sta qui dentro (non solo nel
    `setUpModule` di questo file), cosi' vale per chiunque usi il banco."""

    def setUp(self):
        _orologio = mock.patch.object(fase59_concierge, "time", mock.Mock(time=lambda: 1767225600))
        _orologio.start()
        self.addCleanup(_orologio.stop)
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db", db_domanda=f"{d}/dom.db",
            db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_tassa_comunale=f"{d}/tc.db", db_finanza=f"{d}/fin.db",
            file_referral=f"{d}/ref.json",
            commissione_bps=1500, stripe_webhook_secret=WHSEC))
        self.sis.concierge._link = lambda dati: "https://pay/" + str(dati.get("riferimento", ""))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "hotel",
               "titolo": "H", "citta": "Roma", "descrizione": "x",
               "prezzo_notte_cents": 10000, "capacita": 2, "servizi": [], "immagini": [],
               "tassa_pp_notte_cents": 0}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "hotel",
               "da": "2027-11-01", "a": "2027-11-30", "unita_totali": 10,
               "prezzo_netto_cents": 10000}, HK)
        self._seq = 0

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _prenota_paga(self):
        self._seq += 1
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "hotel",
                      "check_in": CI, "check_out": CO, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": f"f{self._seq}@collaudo.invalid"})
        rif = b["riferimento"]
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        ts = str(int(time.time()))
        mac = hmac.new(WHSEC.encode(), f"{ts}.{pl}".encode(), hashlib.sha256).hexdigest()
        s, _ = self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                               {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})
        self.assertEqual(s, 200)
        return rif

    def _tipi(self, rif):
        return [m["tipo"] for m in self.sis.finanza.movimenti(rif)]

    def _note_debito(self, rif):
        # PROTON P1-SEXIES (b): la riga `penale:<rif>` del giornale e' UNICA per costruzione, quindi
        # contarla non vede la nota DOPPIA, che vive nella tabella `note`: si conta li'.
        return [n for n in self.sis.finanza.note_per_riferimento(rif) if n.get("tipo") == "debito"]


class TestOffsetEFlusso(_BancoOffset):

    def test_offset_al_centesimo_fifo_e_valute(self):
        fc = self.sis.finanza
        pd = self.sis.payout
        pd.registra_maturato("P1", "h1", 60, "EUR")
        pd.registra_maturato("P2", "h1", 30, "EUR")
        pd.registra_maturato("P3", "h1", 500, "JPY")        # valuta diversa: intoccabile
        pd.registra_maturato("RIF", "h1", 999, "EUR")       # payout della cancellata: intoccabile
        e = fc.processa_penale(riferimento="RIF", host_id="h1", penale_cents=100,
                               valuta="EUR", payout=pd)
        self.assertEqual(e["offset_cents"], 90)             # 60 + 30, FIFO
        self.assertEqual(e["residuo_cents"], 10)
        self.assertEqual(e["offset_cents"] + e["residuo_cents"], e["penale_cents"],
                         "conservazione: offset + residuo == penale")
        self.assertIsNone(pd.info("P1"), "P1 consumato per intero -> rimosso")
        self.assertIsNone(pd.info("P2"))
        self.assertEqual(pd.info("P3")["minori"], 500)      # JPY intatto
        self.assertEqual(pd.info("RIF")["minori"], 999)     # la cancellata non si autocompensa
        deb = fc.debiti_host("h1", stato="aperto")
        self.assertEqual([d["residuo_cents"] for d in deb], [10])
        self.assertTrue(fc.verifica_catena()["ok"])
        # replay (riasserzione): niente doppi tocchi, stessi numeri
        e2 = fc.processa_penale(riferimento="RIF", host_id="h1", penale_cents=100,
                                valuta="EUR", payout=pd)
        self.assertEqual((e2["offset_cents"], e2["residuo_cents"]), (90, 10))
        self.assertEqual(pd.info("RIF")["minori"], 999)

    def test_offset_parziale_di_riga(self):
        fc = self.sis.finanza
        pd = self.sis.payout
        pd.registra_maturato("PX", "h2", 500, "EUR")
        e = fc.processa_penale(riferimento="RX", host_id="h2", penale_cents=120,
                               valuta="EUR", payout=pd)
        self.assertEqual(e["residuo_cents"], 0)
        self.assertEqual(pd.info("PX")["minori"], 380)      # 500-120, riga riallineata
        self.assertEqual(fc.debiti_host("h2")[0]["stato"], "saldato")
        self.assertEqual(fc.nota(e["nota_id"])["stato"], "saldata")

    def test_atomicita_cancellazione_end_to_end(self):
        rif = self._prenota_paga()
        s, c = self.g("POST", "/api/host/cancella", {"riferimento": rif, "host_id": "demo"}, HK)
        self.assertEqual(s, 200)
        # il 200 porta la ND, e la ND sta nel giornale con catena valida
        self.assertTrue(c.get("nota_debito", "").startswith("ND-"), c)
        mv = self.sis.finanza.movimenti(rif)
        self.assertIn("nota_debito", [m["tipo"] for m in mv])
        self.assertTrue(self.sis.finanza.verifica_catena()["ok"])
        # doppio click: UNA sola ND
        s2, _ = self.g("POST", "/api/host/cancella", {"riferimento": rif, "host_id": "demo"}, HK)
        self.assertEqual(s2, 409)
        self.assertEqual(sum(1 for m in self.sis.finanza.movimenti(rif)
                             if m["tipo"] == "nota_debito"), 1)

    def test_golden_saldo_zero(self):
        rif = self._prenota_paga()
        # il payout della prenotazione stessa non conta come saldo: l'host e' a 0
        s, c = self.g("POST", "/api/host/cancella", {"riferimento": rif, "host_id": "demo"}, HK)
        self.assertEqual(s, 200)
        self.assertEqual(c["penale_compensata_cents"], 0)
        self.assertEqual(c["penale_residua_cents"], c["penale_host_cents"])
        deb = self.sis.finanza.debiti_host("demo", stato="aperto")
        self.assertEqual(len(deb), 1)
        self.assertEqual(deb[0]["residuo_cents"], c["penale_host_cents"])
        # ospite protetto: date di nuovo prenotabili SUBITO
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "hotel",
                      "check_in": CI, "check_out": CO, "party": 2})
        self.assertTrue(q.get("quote_token"), "le date devono essere libere")

    def test_gara_admin_vince_nessuna_nd_spuria(self):
        rif = self._prenota_paga()
        idem = self.sis.pagamenti_pendenti.info(rif)["idem_key"]
        s, _ = self.g("POST", "/api/admin/rimborso", {"alloggio_id": "hotel",
                      "check_in": CI, "check_out": CO, "idem_key": idem}, AK)
        self.assertEqual(s, 200)
        s2, _ = self.g("POST", "/api/host/cancella", {"riferimento": rif, "host_id": "demo"}, HK)
        self.assertEqual(s2, 409)
        # il giornale ora traccia i movimenti ordinari (incasso/rimborso): l'intento del
        # test e' che NON ci sia una nota_debito (penale) spuria per l'host.
        self.assertNotIn("nota_debito", [m["tipo"] for m in self.sis.finanza.movimenti(rif)],
                         "decisione admin: NESSUNA penale spuria per l'host")

    def test_riasserzione_dopo_crash(self):
        rif = self._prenota_paga()
        # crash simulato: la cancellazione ha vinto il CAS (stato+penale nel pendente)
        # ma il giornale non e' mai stato scritto
        pp = self.sis.pagamenti_pendenti
        self.assertTrue(pp.marca_cancellata_host(rif, 3000))
        # prima dello sweep: nessuna PENALE ancora (i movimenti incasso/tassa del pagamento
        # ci sono gia' ed e' corretto; e' la nota_debito che ancora manca).
        self.assertNotIn("nota_debito", [m["tipo"] for m in self.sis.finanza.movimenti(rif)])
        sweep_hold_una_passata(self.sis, self.r)
        mv = self.sis.finanza.movimenti(rif)
        self.assertIn("nota_debito", [m["tipo"] for m in mv])
        self.assertEqual(self.sis.finanza.debiti_host("demo", stato="aperto")[0]
                         ["residuo_cents"], 3000)
        # secondo sweep: nessun doppione
        sweep_hold_una_passata(self.sis, self.r)
        self.assertEqual(sum(1 for m in self.sis.finanza.movimenti(rif)
                             if m["tipo"] == "nota_debito"), 1)
        self.assertTrue(self.sis.finanza.verifica_catena()["ok"])

    # ⛔ VOCE 137: le guardie G1-G7 (e quelle nate dal Giudice) stanno in test_fase83_server.py,
    # classe `TestLaCancellazioneDellHostArrivaSempreInFondo`, sopra il banco `_BancoOffset`.


class _Payout:
    """Ledger dei payout finto: ricorda con quale «solo se lo stato e'» gli si chiede di
    scrivere."""

    def __init__(self, righe=None):
        self.righe = righe or []
        self.stati = []

    def elenca(self, host_id, stato=None, valuta=None):
        return list(self.righe)

    def imposta_importo(self, pid, n, solo_se_stato=None):
        self.stati.append(("imposta_importo", solo_se_stato))
        return True

    def rimuovi(self, pid, solo_se_stato=None):
        self.stati.append(("rimuovi", solo_se_stato))
        return True


class TestLeCompensazioniScrivonoSoloSuUnBonificoAncoraMaturato(unittest.TestCase):
    """Voce 139. Era in test_scatto3_carta.py: per fase177 il Giudice accende il test dedicato,
    che non c'e', e poi gli 8 file che lo importano in ordine alfabetico; quello e' l'undicesimo,
    e un mutante su `solo_se_stato` sopravviveva anche con la prova scritta."""

    def setUp(self):
        self.fc = crea_financial_controller(":memory:")
        self.fc.inizializza_schema()

    def _debito(self, valuta="EUR", cents=5000, rif="RIF1", host="h1"):
        class _NoPayout:
            def elenca(self, *a, **k):
                return []
        self.fc.processa_penale(riferimento=rif, host_id=host, penale_cents=cents,
                                valuta=valuta, payout=_NoPayout())
        return self.fc.debiti_host(host, stato="aperto")

    def test_139_le_due_compensazioni_scrivono_SOLO_SE_il_bonifico_e_ancora_maturato(self):
        """Voce 139: fra la lettura dei 'maturato' e la scrittura il bonifico puo' essere stato
        fermato (contestazione) o tolto. La penale (`processa_penale`) e la riscossione
        (`riscuoti_debiti`) chiedono al registro di scrivere solo se e' ancora 'maturato': senza,
        riducono o cancellano soldi fermati. Le righe sono in ordine apposta: la prima (100) si
        consuma intera (`rimuovi`), la seconda si riduce (`imposta_importo`)."""
        attese = [("rimuovi", "maturato"), ("imposta_importo", "maturato")]
        righe = [{"prenotazione_id": "P_PICCOLO", "minori": 100},
                 {"prenotazione_id": "P_GRANDE", "minori": 9999}]
        p = _Payout(list(righe))
        self.fc.processa_penale(riferimento="RIF_PEN", host_id="h1", penale_cents=5000,
                                valuta="EUR", payout=p)
        self.assertEqual(attese, p.stati, "la PENALE scrive sui bonifici senza chiedere che "
                                          "siano ancora 'maturato': %r" % (p.stati,))
        self._debito(cents=5000, rif="RIF_DEB")
        p2 = _Payout(list(righe))
        self.fc.riscuoti_debiti(host_id="h1", payout=p2)
        self.assertEqual(attese, p2.stati, "la RISCOSSIONE scrive sui bonifici senza chiedere "
                                           "che siano ancora 'maturato': %r" % (p2.stati,))


class TestQuantoLePenaliHannoPresoDaUnaRiga(unittest.TestCase):
    """Busta A4 di Proton (29/10), punto (a): la riga che una penale usa per intero sparisce dal
    ledger dei bonifici, e l'arbitro chiede al giornale quanto le penali le hanno preso
    (`compensato_su_payout`). La prova dell'arbitro sta in test_fase83_server
    (`test_A4_3a_...`); qui, nel file che il Giudice accende per fase177, la lettura da sola."""

    def setUp(self):
        self.fc = crea_financial_controller(":memory:")
        self.fc.inizializza_schema()

    def test_A4_3_conta_le_compensazioni_della_riga_meno_gli_storni_e_SOLO_di_quella_riga(self):
        # la penale da 150: la prima riga (100) si consuma intera, la seconda perde 50
        self.fc.processa_penale(riferimento="RIF_PEN", host_id="h1", penale_cents=150,
                                valuta="EUR", payout=_Payout([
                                    {"prenotazione_id": "P1", "minori": 100},
                                    {"prenotazione_id": "XP1", "minori": 9999}]))
        self.assertEqual((100, 50, 0), (self.fc.compensato_su_payout("P1"),
                                        self.fc.compensato_su_payout("XP1"),
                                        self.fc.compensato_su_payout("1")),
                         "la lettura confonde le righe (P1, XP1, e la sola coda «1»)")

        class _NonScrive(_Payout):
            def rimuovi(self, pid, solo_se_stato=None):
                return False                          # il ledger rifiuta: segue lo storno
        self.fc.processa_penale(riferimento="RIF_PEN2", host_id="h2", penale_cents=70,
                                valuta="EUR",
                                payout=_NonScrive([{"prenotazione_id": "P2", "minori": 70}]))
        self.assertEqual(0, self.fc.compensato_su_payout("P2"),
                         "la compensazione stornata conta ancora come presa dalla riga")
        # la riscossione di un debito sui bonifici dopo: stesso schema, conta anche lei
        self._debito_senza_righe("RIF_DEB", "h3", 40)
        self.fc.riscuoti_debiti(host_id="h3", payout=_Payout([
            {"prenotazione_id": "P3", "minori": 40}]))
        self.assertEqual(40, self.fc.compensato_su_payout("P3"),
                         "la riscossione del debito sulla riga non risulta presa")

    def _debito_senza_righe(self, rif, host, cents):
        class _NoPayout:
            def elenca(self, *a, **k):
                return []
        self.fc.processa_penale(riferimento=rif, host_id=host, penale_cents=cents,
                                valuta="EUR", payout=_NoPayout())


if __name__ == "__main__":
    unittest.main()
