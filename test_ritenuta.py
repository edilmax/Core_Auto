"""LA RITENUTA SULLE LOCAZIONI BREVI -- costruita SPENTA, si accende con un tasto.

Il fondatore, 29/9 notte: «costruiscilo, e lo attiviamo con un tasto se serve».

La regola (art. 4 comma 5 DL 50/2017; Agenzia delle Entrate, circolare 24/E del 2017 e guida
«Locazioni brevi»): chi INCASSA i canoni di locazioni brevi di persone fisiche fuori
dall'attivita' d'impresa opera la ritenuta «all'atto del pagamento al beneficiario», su
«l'intero importo indicato nel contratto che il conduttore e' tenuto a versare», provvigione
compresa se trattenuta sul canone; NON sulle somme a titolo di deposito cauzionale o di
PENALE. La tassa di soggiorno fuori (la paga il turista: fonte secondaria, domanda aperta
per il commercialista).

Invarianti provati qui, ognuno nei due stati dell'interruttore dove ha senso:
  1. SPENTA (di serie) il bonifico e' quello di sempre, e nel giornale non c'e' nessuna riga;
  2. ACCESA, host privato senza partita IVA, casa in Italia, soggiorno breve: il bonifico cala
     della ritenuta, il giornale la scrive verso l'Erario, e il registro dei bonifici lo dice
     (anche a chi paga a mano da `da_pagare`);
  3. UNA volta sola, per quante volte si ritenti il bonifico;
  4. NON si opera su impresa, partita IVA, casa fuori Italia, soggiorno lungo, penale,
     «paga in struttura»;
  5. la base e' il prezzo del soggiorno pagato dall'ospite, meno cio' che l'arbitro gli ha
     restituito, SENZA la tassa di soggiorno;
  6. se non si puo' operare (giornale che non scrive, ritenuta oltre il bonifico) il bonifico
     NON parte: soldi dello Stato pagati all'host non tornano piu';
  7. il pannello del super-admin vede l'interruttore, lo accende e lo spegne, e legge i totali
     del mese (F24) e dell'anno per host (Certificazione Unica).
"""
import hashlib
import hmac
import json
import os
import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

SEG = b"r" * 32
HK = {"X-Host-Key": "hk"}
WHSEC = "whsec_test"
CI, CO = "2027-08-10", "2027-08-12"          # 2 notti
IP = "203.0.113.9"
# Una costante, non una stringa letterale nel banco: per bandit una password passata come
# letterale e' un segreto cablato (B106), ed e' lo stesso rimedio di test_bunker_controlroom.
_CHIAVE_BUNKER_DI_PROVA = "SuperPw@1"


class _ConnectContatore:
    def __init__(self, tid="tr_OK"):
        self.tid = tid
        self.chiamate = []

    def trasferisci(self, acct, importo, valuta, rif):
        self.chiamate.append((acct, int(importo), valuta, str(rif)))
        return self.tid


class _Base(unittest.TestCase):
    PAESE = "IT"
    CIN = "IT058091C2ABCDEF12"
    TASSA = 0
    VALUTA = "EUR"

    def setUp(self):
        os.environ.pop("RITENUTA_ATTIVA", None)
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db", db_domanda=f"{d}/dom.db",
            db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_tassa_comunale=f"{d}/tc.db", db_finanza=f"{d}/fin.db",
            file_referral=f"{d}/ref.json",
            commissione_bps=1000, stripe_webhook_secret=WHSEC,
            bunker_password=_CHIAVE_BUNKER_DI_PROVA))
        self.sis.concierge._link = lambda dati: "https://pay/" + str(dati.get("riferimento", ""))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        es = self.sis.registro_host.registra("rit@collaudo.invalid", "password12",
                                             accetta_termini=True)
        self.hid = es.host_id
        self.sis.registro_host.imposta_stripe_account(self.hid, "acct_TEST")
        self.connect = _ConnectContatore()
        self.sis.connect = self.connect
        s, c = self.g("POST", "/api/host/pubblica", {
            "host_id": self.hid, "slug": "casa", "titolo": "C", "citta": "Roma",
            "paese": self.PAESE, "cin": self.CIN, "descrizione": "x",
            "prezzo_notte_cents": 10000, "capacita": 2, "servizi": [], "immagini": [],
            "tassa_pp_notte_cents": self.TASSA, "valuta": self.VALUTA}, HK)
        self.assertEqual(s, 201, c)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa",
               "da": "2027-08-01", "a": "2027-09-30", "unita_totali": 5,
               "prezzo_netto_cents": 10000}, HK)

    def tearDown(self):
        os.environ.pop("RITENUTA_ATTIVA", None)
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _paga(self, rif):
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        ts = str(int(time.time()))
        mac = hmac.new(WHSEC.encode(), f"{ts}.{pl}".encode(), hashlib.sha256).hexdigest()
        return self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                               {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})[0]

    def _prenota_paga(self, ci=CI, co=CO):
        s, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa",
                      "check_in": ci, "check_out": co, "party": 2})
        self.assertEqual(s, 200, q)
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "o@collaudo.invalid"})
        rif = b["riferimento"]
        self.assertEqual(self._paga(rif), 200)
        return rif, q

    def _accendi(self):
        self.assertTrue(self.sis.ritenuta.imposta(True, motivo="collaudo", chi="test"))
        self.assertTrue(self.sis.ritenuta.attivo())

    def _maturato(self, rif):
        return self.sis.payout.info(rif)["minori"]

    def _righe(self, rif, tipo):
        return [m for m in self.sis.finanza.movimenti(rif) if m["tipo"] == tipo]

    def _bunker(self):
        s, out = self.g("POST", "/api/bunker/login", {"codice": _CHIAVE_BUNKER_DI_PROVA},
                        {"X-Admin-Key": "ak", "X-Forwarded-For": IP})
        self.assertEqual(s, 200, out)
        return {"X-Admin-Key": "ak", "X-Forwarded-For": IP, "X-Bunker-Session": out["sessione"]}


class TestSpentaDiSerie(_Base):
    def test_l_interruttore_esiste_ed_e_SPENTO_di_serie(self):
        self.assertIsNotNone(self.sis.ritenuta, "manca l'interruttore della ritenuta nel sistema")
        self.assertFalse(self.sis.ritenuta.attivo(), "la ritenuta deve nascere SPENTA")

    def test_spenta_il_bonifico_e_INTERO_e_il_giornale_non_ha_ritenute(self):
        rif, _q = self._prenota_paga()
        pieno = self._maturato(rif)
        self.r._trasferisci_all_host(rif, pieno)
        self.assertEqual(self.connect.chiamate, [("acct_TEST", pieno, "EUR", rif)])
        self.assertEqual(self._righe(rif, "ritenuta"), [])

    def test_la_leva_d_ambiente_la_accende_senza_il_tasto(self):
        os.environ["RITENUTA_ATTIVA"] = "1"
        self.assertTrue(self.sis.ritenuta.attivo())


class TestAccesa(_Base):
    def test_host_privato_casa_in_italia_il_bonifico_cala_della_ritenuta(self):
        self._accendi()
        rif, q = self._prenota_paga()
        pieno = self._maturato(rif)
        base = q["prezzo_guest_cents"]
        attesa = (base * 2100 + 5000) // 10000
        self.assertEqual(base, 20000)
        self.assertEqual(attesa, 4200)
        self.r._trasferisci_all_host(rif, pieno)
        self.assertEqual(self.connect.chiamate, [("acct_TEST", pieno - attesa, "EUR", rif)],
                         "il bonifico doveva calare della ritenuta")
        righe = self._righe(rif, "ritenuta")
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0]["importo_cents"], attesa)
        self.assertEqual((righe[0]["conto_dare"], righe[0]["conto_avere"]),
                         ("debiti_vs_host", "debiti_vs_erario"))
        self.assertIn("base=%d" % base, righe[0]["causale"])
        self.assertEqual(self._righe(rif, "payout_host")[0]["importo_cents"], pieno - attesa)
        self.assertEqual(self._maturato(rif), pieno - attesa)
        self.assertTrue(self.sis.finanza.verifica_catena()["ok"])

    def test_host_senza_stripe_da_pagare_a_mano_e_gia_al_netto(self):
        self._accendi()
        self.sis.registro_host.imposta_stripe_account(self.hid, "")
        rif, _q = self._prenota_paga()
        pieno = self._maturato(rif)
        self.r._trasferisci_all_host(rif, pieno)
        self.assertEqual(self.connect.chiamate, [])
        self.assertEqual(self.sis.payout.da_pagare(self.hid, "EUR"), pieno - 4200)
        self.assertEqual(len(self._righe(rif, "ritenuta")), 1)

    def test_UNA_volta_sola_per_quanti_ritentativi(self):
        self._accendi()
        self.sis.registro_host.imposta_stripe_account(self.hid, "")
        rif, _q = self._prenota_paga()
        pieno = self._maturato(rif)
        for _ in range(3):
            self.r._trasferisci_all_host(rif, self._maturato(rif))
        self.assertEqual(self._maturato(rif), pieno - 4200)
        self.assertEqual(len(self._righe(rif, "ritenuta")), 1)

    def test_con_partita_iva_VERIFICATA_valida_NON_si_trattiene(self):
        self._accendi()
        self.sis.registro_host.imposta_dati_fiscali(self.hid, {"partita_iva": "IT01234567890",
                                                               "tipo_soggetto": "individuo"})
        self.assertTrue(self.sis.registro_host.registra_verifica_piva(
            self.hid, "IT01234567890", "valida", "WAPIAAAAaDxc__Zb", "ROSSI MARIO"))
        rif, _q = self._prenota_paga()
        pieno = self._maturato(rif)
        self.r._trasferisci_all_host(rif, pieno)
        self.assertEqual(self.connect.chiamate[0][1], pieno)
        self.assertEqual(self._righe(rif, "ritenuta"), [])

    def test_partita_iva_DICHIARATA_ma_non_verificata_si_trattiene(self):
        """D23: chi scrive una partita IVA falsa non scavalca la ritenuta."""
        for esito in ("", "non_valida", "errore", "non_verificabile"):
            with self.subTest(esito=esito):
                self.sis.registro_host.imposta_dati_fiscali(
                    self.hid, {"partita_iva": "IT0123456789%d" % len(esito)})
                if esito:
                    self.sis.registro_host.registra_verifica_piva(
                        self.hid, "IT0123456789%d" % len(esito), esito, "", "")
                info = self.sis.registro_host.info_host(self.hid)
                self.assertEqual(info["piva_vies_esito"], esito)
                self._accendi()
                rif, _q = self._prenota_paga()
                self.r._trasferisci_all_host(rif, self._maturato(rif))
                self.assertEqual(len(self._righe(rif, "ritenuta")), 1)

    def test_societa_senza_partita_iva_verificata_si_trattiene(self):
        """«Societa'» e' una dichiarazione dell'host: senza una partita IVA verificata non
        esenta (una societa' italiana ce l'ha sempre)."""
        self._accendi()
        self.sis.registro_host.imposta_dati_fiscali(self.hid, {"tipo_soggetto": "societa"})
        rif, _q = self._prenota_paga()
        self.r._trasferisci_all_host(rif, self._maturato(rif))
        self.assertEqual(len(self._righe(rif, "ritenuta")), 1)

    def test_oltre_trenta_notti_NON_si_trattiene(self):
        self._accendi()
        # 31 notti superano la soglia DAC7: senza dati fiscali il bonifico si fermerebbe per
        # quello, e la prova direbbe «verde» per il motivo sbagliato
        self.sis.registro_host.imposta_dati_fiscali(self.hid, {
            "codice_fiscale": "RSSMRA80A01H501U", "indirizzo_fiscale": "Via Roma 1",
            "paese": "IT", "iban": "IT60X0542811101000000123456", "tipo_soggetto": "individuo"})
        rif, _q = self._prenota_paga("2027-08-01", "2027-09-01")     # 31 notti
        pieno = self._maturato(rif)
        self.r._trasferisci_all_host(rif, pieno)
        self.assertEqual(self.connect.chiamate[0][1], pieno)
        self.assertEqual(self._righe(rif, "ritenuta"), [])

    def test_trenta_notti_si_trattiene(self):
        self._accendi()
        rif, _q = self._prenota_paga("2027-08-01", "2027-08-31")     # 30 notti
        self.r._trasferisci_all_host(rif, self._maturato(rif))
        self.assertEqual(len(self._righe(rif, "ritenuta")), 1)

    def test_la_PENALE_di_una_cancellazione_NON_si_trattiene(self):
        self._accendi()
        rif, _q = self._prenota_paga()
        pieno = self._maturato(rif)
        self.r._trasferisci_all_host(rif, pieno, penale=True)
        self.assertEqual(self.connect.chiamate[0][1], pieno)
        self.assertEqual(self._righe(rif, "ritenuta"), [])

    def test_paga_in_struttura_NON_si_trattiene(self):
        self._accendi()
        rif, _q = self._prenota_paga()
        rec = dict(self.sis.pagamenti_pendenti.info(rif))
        corpo = json.loads(rec["corpo_json"])
        corpo["modo_pagamento"] = "in_struttura"
        rec["corpo_json"] = json.dumps(corpo)
        pieno = self._maturato(rif)
        self.assertTrue(self.r._opera_ritenuta(rif, rec, self.hid,
                                               self.sis.registro_host.info_host(self.hid), False))
        self.assertEqual(self._maturato(rif), pieno)
        self.assertEqual(self._righe(rif, "ritenuta"), [])

    def test_una_ritenuta_di_zero_centesimi_non_si_scrive_e_non_ferma_il_bonifico(self):
        """Sopravvissuti del giro sul diff (fase83:6685-6686), stato costruito a mano (D19):
        una base di due centesimi da' una ritenuta di zero -- niente riga e il bonifico va."""
        self._accendi()
        rif, _q = self._prenota_paga()
        rec = dict(self.sis.pagamenti_pendenti.info(rif))
        corpo = json.loads(rec["corpo_json"])
        corpo["prezzo_guest_cents"] = 2
        rec["corpo_json"] = json.dumps(corpo)
        pieno = self._maturato(rif)
        self.assertIs(self.r._opera_ritenuta(rif, rec, self.hid,
                                             self.sis.registro_host.info_host(self.hid), False),
                      True)
        self.assertEqual(self._maturato(rif), pieno)
        self.assertEqual(self._righe(rif, "ritenuta"), [])

    def test_ritenuta_fatta_bonifico_in_hold_DAC7_poi_riparte_UNA_volta_ridotto(self):
        """Sopravvissuto del giro sul diff (fase83:6663): il ritentativo dopo un hold DAC7
        trova la ritenuta gia' fatta e deve PAGARE (ridotto), non fermarsi."""
        self._accendi()
        for i in range(3):                                   # host sopra la soglia DAC7
            self.sis.finanza.movimento(tipo="incasso", riferimento="VOL%d" % i,
                                       soggetto="host:" + self.hid, importo_cents=100000,
                                       valuta="EUR", causale="volume")
        rif, _q = self._prenota_paga()
        pieno = self._maturato(rif)
        self.r._trasferisci_all_host(rif, pieno)
        self.assertEqual(self.connect.chiamate, [], "doveva fermarsi per i dati DAC7")
        self.assertEqual(len(self._righe(rif, "ritenuta")), 1)
        s, tok = self.g("POST", "/api/host/login", {"email": "rit@collaudo.invalid",
                                                     "password": "password12"})
        self.assertEqual(s, 200, tok)
        s, c = self.g("POST", "/api/host/dati_fiscali", {
            "codice_fiscale": "RSSMRA80A01H501U", "indirizzo_fiscale": "Via Roma 1",
            "paese": "IT", "iban": "IT60X0542811101000000123456", "tipo_soggetto": "individuo"},
            {"X-Host-Token": tok["token"]})
        self.assertEqual(s, 200, c)
        self.assertEqual(self.connect.chiamate, [("acct_TEST", pieno - 4200, "EUR", rif)])
        self.assertEqual(len(self._righe(rif, "ritenuta")), 1)

    def test_casa_italiana_SENZA_CIN_si_trattiene_lo_stesso(self):
        """Sopravvissuto del giro sul diff (fase83:6677): un annuncio italiano pubblicato prima
        dell'obbligo del CIN non ce l'ha; basta il paese."""
        import sqlite3
        con = sqlite3.connect(os.path.join(self.dir, "c.db"))
        with con:
            con.execute("UPDATE alloggi SET cin='' WHERE slug='casa'")
        con.close()
        self._accendi()
        rif, _q = self._prenota_paga()
        self.r._trasferisci_all_host(rif, self._maturato(rif))
        self.assertEqual(len(self._righe(rif, "ritenuta")), 1)

    def test_senza_finanza_si_ferma_e_dice_PERCHE(self):
        """Sopravvissuti del giro sul diff (fase83:6660 e 6710): il motivo nella traccia."""
        self._accendi()
        rif, _q = self._prenota_paga()
        pieno = self._maturato(rif)
        self.sis.finanza = None
        with self.assertLogs("core_auto.server", level="ERROR") as log:
            self.r._trasferisci_all_host(rif, pieno)
        self.assertEqual(self.connect.chiamate, [])
        rec = [r for r in log.records if "RITENUTA NON OPERATA" in r.getMessage()]
        self.assertEqual(len(rec), 1, log.output)
        self.assertIsInstance(rec[0].exc_info, tuple)
        self.assertIn("giornale o registro dei bonifici assente", str(rec[0].exc_info[1]))

    def test_la_PENALE_vera_di_una_cancellazione_arriva_intera_all_host(self):
        """Sopravvissuto del giro sul diff (fase83:7443): la cancellazione con penale passa
        `penale=True`, dal percorso VERO (rotta dell'ospite), non da una chiamata a mano."""
        import datetime
        s, c = self.g("POST", "/api/host/pubblica", {
            "host_id": self.hid, "slug": "casa-rig", "titolo": "R", "citta": "Roma",
            "paese": "IT", "cin": self.CIN, "descrizione": "x", "prezzo_notte_cents": 10000,
            "capacita": 2, "servizi": [], "immagini": [],
            "politica_cancellazione": "rigida"}, HK)
        self.assertEqual(s, 201, c)
        # arrivo fra due giorni: fuori dal ripensamento (vuole arrivo a 3 giorni o piu') e
        # dentro la soglia della rigida -> penale piena all'host
        ci = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
        co = (datetime.date.today() + datetime.timedelta(days=4)).isoformat()
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa-rig", "da": ci,
               "a": co, "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)
        self._accendi()
        s, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa-rig",
                      "check_in": ci, "check_out": co, "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "o@collaudo.invalid"})
        self.assertEqual(s, 201, b)
        rif = b["riferimento"]
        self.assertEqual(self._paga(rif), 200)
        s, canc = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, canc)
        self.assertEqual(len(self.connect.chiamate), 1, "la penale doveva partire verso l'host")
        self.assertEqual(self.connect.chiamate[0][1], self._maturato(rif))
        self.assertEqual(self._righe(rif, "ritenuta"), [], "una penale non e' canone")

    def test_controversia_la_base_toglie_cio_che_l_arbitro_ha_reso(self):
        self._accendi()
        rif, q = self._prenota_paga()
        self.assertTrue(self.sis.garanzia.contesta(rif, "collaudo")["ok"])
        hb = self._bunker()
        s, c = self.g("POST", "/api/admin/controversia/risolvi",
                      {"riferimento": rif, "rimborso_ospite_cents": 5000}, hb)
        self.assertEqual(s, 200, c)
        base = q["prezzo_guest_cents"] - 5000
        attesa = (base * 2100 + 5000) // 10000
        righe = self._righe(rif, "ritenuta")
        self.assertEqual([r["importo_cents"] for r in righe], [attesa])
        self.assertIn("base=%d" % base, righe[0]["causale"])


class TestAccesaConTassaDiSoggiorno(_Base):
    TASSA = 300

    def test_la_tassa_di_soggiorno_NON_entra_nella_base(self):
        self._accendi()
        rif, q = self._prenota_paga()
        self.assertGreater(q["tassa_soggiorno_cents"], 0)
        self.r._trasferisci_all_host(rif, self._maturato(rif))
        base = q["prezzo_guest_cents"]
        self.assertEqual(self._righe(rif, "ritenuta")[0]["importo_cents"],
                         (base * 2100 + 5000) // 10000)


class TestCasaFuoriItalia(_Base):
    PAESE = "FR"
    CIN = ""

    def test_casa_fuori_italia_NON_si_trattiene(self):
        self._accendi()
        rif, _q = self._prenota_paga()
        pieno = self._maturato(rif)
        self.r._trasferisci_all_host(rif, pieno)
        self.assertEqual(self.connect.chiamate[0][1], pieno)
        self.assertEqual(self._righe(rif, "ritenuta"), [])


class TestCasaConSoloIlCIN(_Base):
    """Sopravvissuto del giro sul diff (fase83:6677): il paese vuoto ma il CIN c'e' -- il CIN
    esiste solo in Italia, quindi la casa e' in Italia."""
    PAESE = ""

    def test_il_CIN_basta_a_dire_Italia(self):
        self._accendi()
        rif, _q = self._prenota_paga()
        self.r._trasferisci_all_host(rif, self._maturato(rif))
        self.assertEqual(len(self._righe(rif, "ritenuta")), 1)


class TestAnnuncioInValutaNonEuro(_Base):
    """Sopravvissuto del giro sul diff (fase83:6697): la riga della ritenuta porta la valuta
    del pagamento, non «EUR» d'ufficio."""
    VALUTA = "USD"

    def test_la_ritenuta_e_nella_valuta_del_pagamento(self):
        self._accendi()
        rif, _q = self._prenota_paga()
        self.r._trasferisci_all_host(rif, self._maturato(rif))
        righe = self._righe(rif, "ritenuta")
        self.assertEqual([r["valuta"] for r in righe], ["USD"])
        self.assertEqual(self.connect.chiamate[0][2], "USD")


class TestIlPannelloNeiCasiDiBordo(_Base):
    """Sopravvissuti del giro sul diff (fase83:4500, 4512, 4530)."""

    def test_senza_anno_e_l_anno_in_corso_e_un_anno_sbagliato_e_422(self):
        hb = self._bunker()
        s, d = self.g("GET", "/api/bunker/ritenuta", None, hb)
        self.assertEqual((s, d["anno"]), (200, time.gmtime().tm_year))
        s, d = self.g("GET", "/api/bunker/ritenuta", None, hb, q={"anno": "duemila"})
        self.assertEqual(s, 422, d)

    def test_interruttore_assente_si_dice_assente_e_spento(self):
        hb = self._bunker()
        self.sis.ritenuta = None
        s, d = self.g("GET", "/api/bunker/ritenuta", None, hb)
        self.assertEqual(s, 200, d)
        self.assertIs(d["attivo"], False)
        self.assertIs(d["assente"], True)
        s, d = self.g("POST", "/api/bunker/ritenuta", {"attivo": True}, hb)
        self.assertEqual(s, 503, d)

    def test_il_registro_dice_ACCESA_col_motivo_o_col_trattino(self):
        hb = self._bunker()
        with self.assertLogs("core_auto.server", level="WARNING") as log:
            self.g("POST", "/api/bunker/ritenuta", {"attivo": True, "motivo": "prova F24"}, hb)
            self.g("POST", "/api/bunker/ritenuta", {"attivo": False}, hb)
        righe = [x for x in log.output if "RITENUTA LOCAZIONI BREVI" in x]
        self.assertTrue(any("ACCESA | motivo=prova F24" in x for x in righe), righe)
        self.assertTrue(any("spenta | motivo=-" in x for x in righe), righe)

    def test_SE_L_INTERRUTTORE_NON_SI_SCRIVE_IL_REGISTRO_NON_MENTE(self):
        # la gemella del check-in (1/10): la risposta era 500 e il registro scriveva lo stesso
        # «ACCESA»; senza archivio dei bonifici l'interruttore non ha un file in cui scriversi
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{self.dir}/c2.db",
            db_inventario=f"{self.dir}/i2.db", bunker_password=_CHIAVE_BUNKER_DI_PROVA))
        self.r = crea_router(sis, host_key="hk", admin_key="ak")
        hb = self._bunker()
        for attivo, detto in ((True, "ACCESA"), (False, "spenta")):
            with self.subTest(attivo=attivo):
                with self.assertLogs("core_auto.server", level="WARNING") as visti:
                    s, d = self.g("POST", "/api/bunker/ritenuta", {"attivo": attivo}, hb)
                self.assertEqual((s, d.get("attivo"), d.get("impostato")), (500, False, False), d)
                righe = [x for x in visti.output if "RITENUTA LOCAZIONI BREVI" in x]
                self.assertFalse([x for x in righe if "LOCAZIONI BREVI " + detto in x],
                                 "il registro dice %s e non lo e': %s" % (detto, righe))
                atteso = ("RITENUTA LOCAZIONI BREVI NON %s: l'interruttore non si e' scritto | "
                          "motivo=-" % detto.lower())
                self.assertTrue([x for x in righe if x.endswith(atteso)], righe)


class TestSeNonSiPuoOperareIlBonificoNonParte(_Base):
    def test_giornale_che_non_scrive_bonifico_fermo_e_registro_intatto(self):
        self._accendi()
        rif, _q = self._prenota_paga()
        pieno = self._maturato(rif)
        vero = self.sis.finanza.movimento

        def rotto(**kw):
            if kw.get("tipo") == "ritenuta":
                return None
            return vero(**kw)
        self.sis.finanza.movimento = rotto
        with self.assertLogs("core_auto.server", level="ERROR") as log:
            self.r._trasferisci_all_host(rif, pieno)
        self.assertEqual(self.connect.chiamate, [], "senza la riga della ritenuta NON si paga")
        self.assertEqual(self._maturato(rif), pieno, "il registro dei bonifici torna intero")
        rec = [r for r in log.records if "RITENUTA NON OPERATA" in r.getMessage()]
        self.assertEqual(len(rec), 1, log.output)
        self.assertIsInstance(rec[0].exc_info, tuple)

    def test_ritenuta_oltre_il_bonifico_ferma_e_grida(self):
        """Anche al CONFINE (ritenuta uguale al bonifico: all'host resterebbe zero) -- e il
        motivo e' quello giusto (sopravvissuto del giro sul diff, fase83:6691)."""
        for bonifico in (100, 4200):
            with self.subTest(bonifico=bonifico):
                self._accendi()
                rif, _q = self._prenota_paga()
                self.assertTrue(self.sis.payout.imposta_importo(rif, bonifico))
                with self.assertLogs("core_auto.server", level="ERROR") as log:
                    self.r._trasferisci_all_host(rif, bonifico)
                self.assertEqual(self.connect.chiamate, [])
                self.assertEqual(self._maturato(rif), bonifico)
                self.assertEqual(self._righe(rif, "ritenuta"), [])
                rec = [r for r in log.records if "RITENUTA NON OPERATA" in r.getMessage()]
                self.assertEqual(len(rec), 1, log.output)
                self.assertIn("non sta nel bonifico", str(rec[0].exc_info[1]))


class TestLaQuotaHostCopreSempreLaRitenuta(_Base):
    def test_su_prezzi_e_notti_veri_il_netto_host_supera_la_ritenuta(self):
        """Commissione e tariffa tecnica insieme non arrivano mai a lasciare all'host meno
        della ritenuta: la ritenuta e' sempre operabile dal suo bonifico."""
        for prezzo in (500, 1000, 5000, 10000, 50000):
            self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa",
                   "da": "2027-08-01", "a": "2027-09-30", "unita_totali": 5,
                   "prezzo_netto_cents": prezzo}, HK)
            for co in ("2027-08-11", "2027-08-12", "2027-08-31"):
                s, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa",
                              "check_in": "2027-08-10", "check_out": co, "party": 2})
                self.assertEqual(s, 200, q)
                rit = (q["prezzo_guest_cents"] * 2100 + 5000) // 10000
                self.assertGreater(q["netto_host_cents"] + q["tassa_soggiorno_cents"], rit,
                                   (prezzo, co, q))


class TestIlGiornaleConosceLaRitenuta(unittest.TestCase):
    def setUp(self):
        from fase177_financial_controller import crea_financial_controller
        self.fc = crea_financial_controller(":memory:")
        self.fc.inizializza_schema()

    def test_movimento_ritenuta_verso_l_erario(self):
        r = self.fc.movimento(tipo="ritenuta", riferimento="R1", soggetto="host:h1",
                              importo_cents=4200, valuta="EUR",
                              causale="ritenuta locazione breve | base=20000 | notti=2")
        self.assertIsNotNone(r)
        m = self.fc.movimenti("R1")[0]
        self.assertEqual((m["conto_dare"], m["conto_avere"]), ("debiti_vs_host", "debiti_vs_erario"))

    def test_ritenute_dell_anno_per_mese_e_per_host(self):
        self.fc.movimento(tipo="ritenuta", riferimento="R1", soggetto="host:h1",
                          importo_cents=4200, valuta="EUR",
                          causale="ritenuta locazione breve | base=20000 | notti=2")
        self.fc.movimento(tipo="ritenuta", riferimento="R2", soggetto="host:h1",
                          importo_cents=2100, valuta="EUR",
                          causale="ritenuta locazione breve | base=10000 | notti=1")
        self.fc.movimento(tipo="ritenuta", riferimento="R3", soggetto="host:h2",
                          importo_cents=1050, valuta="EUR",
                          causale="ritenuta locazione breve | base=5000 | notti=1")
        anno = time.gmtime().tm_year
        mese = "%04d-%02d" % (anno, time.gmtime().tm_mon)
        r = self.fc.ritenute_anno(anno)
        self.assertEqual(r["mesi"], {mese: {"EUR": 7350}})
        self.assertEqual(r["host"]["h1"], {"n": 2, "base": 30000, "ritenuta": 6300})
        self.assertEqual(r["host"]["h2"], {"n": 1, "base": 5000, "ritenuta": 1050})
        self.assertEqual(len(r["righe"]), 3)
        self.assertEqual(self.fc.ritenute_anno(anno - 1)["righe"], [])

    def test_DAC7_senza_riga_commissione_la_ritenuta_resta_reddito_dell_host(self):
        """Il ramo storico del rapporto DAC7 ricava il netto dai bonifici: la ritenuta non e'
        una nostra commissione, e' reddito dell'host versato allo Stato per lui."""
        self.fc.movimento(tipo="incasso", riferimento="R1", soggetto="host:h1",
                          importo_cents=20000, valuta="EUR", causale="incasso")
        self.fc.movimento(tipo="ritenuta", riferimento="R1", soggetto="host:h1",
                          importo_cents=4200, valuta="EUR", causale="base=20000")
        self.fc.movimento(tipo="payout_host", riferimento="R1", soggetto="host:h1",
                          importo_cents=13800, valuta="EUR", causale="bonifico")
        a = self.fc.aggrega_dac7(time.gmtime().tm_year)["h1"]
        self.assertEqual(a["netto"], 18000)
        self.assertEqual(a["commissioni"], 2000)


class TestIlPannelloDelSuperAdmin(_Base):
    def test_senza_sessione_bunker_403(self):
        s, _ = self.g("GET", "/api/bunker/ritenuta", None, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 403)
        s, _ = self.g("POST", "/api/bunker/ritenuta", {"attivo": True}, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 403)
        self.assertFalse(self.sis.ritenuta.attivo())

    def test_accende_spegne_e_legge_i_totali(self):
        hb = self._bunker()
        s, d = self.g("GET", "/api/bunker/ritenuta", None, hb)
        self.assertEqual(s, 200, d)
        self.assertFalse(d["attivo"])
        self.assertEqual(d["aliquota_bps"], 2100)
        s, d = self.g("POST", "/api/bunker/ritenuta", {"attivo": True, "motivo": "prova"}, hb)
        self.assertEqual(s, 200, d)
        self.assertTrue(self.sis.ritenuta.attivo())
        self.sis.registro_host.imposta_dati_fiscali(self.hid, {"codice_fiscale": "RSSMRA80A01H501U"})
        rif, _q = self._prenota_paga()
        self.r._trasferisci_all_host(rif, self._maturato(rif))
        s, d = self.g("GET", "/api/bunker/ritenuta", None, hb,
                      q={"anno": str(time.gmtime().tm_year)})
        self.assertEqual(s, 200, d)
        self.assertEqual(sum(v["EUR"] for v in d["mesi"].values()), 4200)
        riga = {h["host_id"]: h for h in d["host"]}[self.hid]
        self.assertEqual((riga["base"], riga["ritenuta"], riga["codice_fiscale"]),
                         (20000, 4200, "RSSMRA80A01H501U"))
        s, d = self.g("POST", "/api/bunker/ritenuta", {"attivo": False}, hb)
        self.assertEqual(s, 200, d)
        self.assertFalse(self.sis.ritenuta.attivo())


if __name__ == "__main__":
    unittest.main()
