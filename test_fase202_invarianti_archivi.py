"""GUARDIA -- gli invarianti di fase199 sono verificati sugli ARCHIVI VERI, ogni giorno (fase202).

Casella 6 del blocco SOLDI («gli invarianti sono verificati in PRODUZIONE, non solo nei test»),
2026-09-04, «autorizzato» del fondatore. Prima di questo modulo: I3 e I4 a ogni prenotazione,
I1 solo dal bottone del bunker, I2 e I5 da nessuna parte (misurato nel codice vivo).

Qui ogni invariante viene messo davanti a un archivio VERO (gli stessi file sqlite che il
prodotto scrive, costruiti con le sue API) rotto in UN punto, e si pretende che il giro lo veda
-- e che su archivi sani taccia (mai gridare al lupo: l'email del Guardiano si impara a
ignorare). In piu': la scansione non scrive, un archivio illeggibile e' CIECO e non «pulito»,
il rapporto del Guardiano viene arricchito e non sostituito, e il tick giornaliero di fase83
chiama DAVVERO il giro con gli invarianti (una guardia sull'albero sintattico: il tick e' una
chiusura dentro `servi()`, non si puo' eseguire senza accendere un server).
"""
import ast
import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
import fase202_invarianti_archivi as A

QUI = os.path.dirname(os.path.abspath(__file__))


class _Archivi(unittest.TestCase):
    """Un sistema vero su file, in una cartella temporanea: e' la «cartella dati»."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        d = self.d
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"I" * 32, con_registrazione_host=True,
            db_catalogo="%s/c.db" % d, db_inventario="%s/i.db" % d,
            db_registro_host="%s/r.db" % d, db_garanzia="%s/g.db" % d,
            db_payout="%s/y.db" % d, db_pendenti="%s/p.db" % d,
            db_accettazioni="%s/a.db" % d, db_tassa_comunale="%s/t.db" % d,
            db_finanza="%s/finanza.db" % d))

    # -- appoggi: la stessa strada del prodotto, non INSERT a mano (salvo per ROMPERE) --
    def _notti(self, alloggio, giorni, totali=1):
        for g in giorni:
            self.assertTrue(self.sys.inventario.imposta_disponibilita(
                alloggio, g, unita_totali=totali, prezzo_netto_cents=10000))

    def _pagata(self, rif, alloggio="villa", ci="2027-05-01", co="2027-05-03", totale=30000,
                firma="quote-firmato", idem=None, extra=None):
        # `firma` e' il quote_token e `idem` l'idem_key (la firma del quote_token): la prova di I3
        # e' l'uno O l'altro (o il voucher nel corpo). Tutti e tre vuoti = prenotazione senza prova.
        corpo = {"totale_cents": totale, "host_id": "h1", "valuta": "EUR"}
        corpo.update(extra or {})
        pp = self.sys.pagamenti_pendenti
        self.assertTrue(pp.registra(rif, alloggio_id=alloggio, check_in=ci, check_out=co,
                                    idem_key=("idem-" + rif) if idem is None else idem,
                                    quote_token=firma, corpo_json=json.dumps(corpo)))
        self.assertIsNotNone(pp.conferma(rif))
        self.assertEqual(pp.info(rif)["stato"], "pagato")

    def _incasso(self, rif, cents, evento="incasso"):
        r = self.sys.finanza.registra(evento_id="%s:%s" % (evento, rif), tipo="incasso",
                                      riferimento=rif, soggetto="host:h1", conto_dare="cassa",
                                      conto_avere="ricavi", importo_cents=cents, valuta="EUR",
                                      causale="collaudo", emittente="test")
        self.assertIsNotNone(r)

    def _sql(self, nome, comando, parametri=()):
        con = sqlite3.connect(os.path.join(self.d, nome))
        with con:
            con.execute(comando, parametri)
        con.close()

    def _giro(self):
        return A.scansiona_archivi(self.d, ora=lambda: 1_800_000_000)


class TestSuArchiviSaniTace(_Archivi):

    def test_su_archivi_sani_ZERO_violazioni_e_CINQUE_invarianti_verificati(self):
        self._notti("villa", ["2027-05-01", "2027-05-02"])
        self._pagata("R1")
        self._incasso("R1", 30000)
        self.assertTrue(self.sys.garanzia.apri("R1", 25000, alloggio_id="villa",
                                               ora_checkin_ts=1000))
        self.assertTrue(self.sys.payout.registra_maturato("R1", "h1", 25000, "EUR"))
        with self.assertLogs("core_auto.invarianti_archivi", level="INFO") as reg:
            r = self._giro()
        self.assertEqual(r["violazioni"], {}, r)
        self.assertEqual(list(r["verificati"]), list(A.CODICI))
        self.assertEqual(r["ciechi"], [])
        self.assertEqual(r["non_eseguiti"], [], r["non_eseguiti"])
        self.assertEqual(r["letti"]["prenotazioni"], 1)
        self.assertEqual(r["letti"]["notti"], 2)
        self.assertEqual(r["letti"]["garanzie"], 1)
        self.assertEqual(r["letti"]["payout"], 1)
        self.assertGreaterEqual(r["letti"]["giornale"], 1)
        self.assertGreaterEqual(r["letti"]["importi"], 4)
        # UNA riga INFO, con la marca che la sonda esterna cerca, e nessun ERROR
        self.assertEqual(1, len(reg.records), reg.output)
        self.assertEqual("INFO", reg.records[0].levelname)
        self.assertIn(A.MARCA, reg.output[0])
        self.assertIn("violazioni=0", reg.output[0])

    def test_la_scansione_NON_SCRIVE_negli_archivi(self):
        self._notti("villa", ["2027-05-01"])
        self._pagata("R1", co="2027-05-02")
        self._incasso("R1", 30000)

        def impronte():
            fuori = {}
            for n in sorted(os.listdir(self.d)):
                if n.endswith(".db"):
                    with io.open(os.path.join(self.d, n), "rb") as f:
                        fuori[n] = hashlib.sha256(f.read()).hexdigest()
            return fuori
        prima = impronte()
        self._giro()
        self.assertEqual(prima, impronte(), "la scansione ha cambiato un archivio")

    def test_la_connessione_di_lettura_RIFIUTA_una_scrittura(self):
        con = A._apri_sola_lettura(os.path.join(self.d, "p.db"))
        try:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("CREATE TABLE prova_scrittura (x INTEGER)")
        finally:
            con.close()


class TestOgniInvarianteVedeIlSuoGuasto(_Archivi):

    def test_I1_una_notte_sovraprenotata_nel_libro_inventario(self):
        self._notti("villa", ["2027-05-01"])
        self._sql("i.db", "UPDATE inventario SET unita_occupate=2 WHERE alloggio_id='villa'")
        r = self._giro()
        self.assertIn("I1", r["violazioni"], r)
        self.assertIn("sovraprenotata", str(r["violazioni"]["I1"]))

    def test_I1_due_pagate_sovrapposte_su_un_alloggio_a_UNA_unita(self):
        self._notti("villa", ["2027-05-01", "2027-05-02", "2027-05-03"], totali=1)
        self._pagata("R1", ci="2027-05-01", co="2027-05-03")
        self._pagata("R2", ci="2027-05-02", co="2027-05-04")
        for rif in ("R1", "R2"):
            self._incasso(rif, 30000)
        r = self._giro()
        self.assertIn("I1", r["violazioni"], r)

    def test_I1_due_pagate_sovrapposte_su_DUE_unita_sono_regolari(self):
        self._notti("villa", ["2027-05-01", "2027-05-02", "2027-05-03"], totali=2)
        self._pagata("R1", ci="2027-05-01", co="2027-05-03")
        self._pagata("R2", ci="2027-05-02", co="2027-05-04")
        for rif in ("R1", "R2"):
            self._incasso(rif, 30000)
        r = self._giro()
        self.assertNotIn("I1", r["violazioni"], "ha gridato su una capienza rispettata: %r" % r)
        self._pagata("R3", ci="2027-05-02", co="2027-05-03")
        self._incasso("R3", 30000)
        r = self._giro()
        self.assertIn("I1", r["violazioni"], "tre pagate su due unita' e non lo vede: %r" % r)

    def test_I2_un_incasso_oltre_il_dovuto_e_OVERPAY(self):
        self._notti("villa", ["2027-05-01"])
        self._pagata("R1", co="2027-05-02")
        self._incasso("R1", 30000)
        self._incasso("R1", 500, evento="incasso_bis")
        r = self._giro()
        self.assertIn("I2", r["violazioni"], r)
        self.assertIn("OVERPAY", str(r["violazioni"]["I2"]))

    def test_I2_una_pagata_SENZA_incasso_nel_giornale(self):
        self._notti("villa", ["2027-05-01"])
        self._pagata("R1", co="2027-05-02")
        r = self._giro()
        self.assertIn("I2", r["violazioni"], r)

    def test_I2_paga_in_struttura_NON_e_giudicata_ma_DICHIARATA(self):
        self._notti("villa", ["2027-05-01"])
        self._pagata("R1", co="2027-05-02", extra={"modo_pagamento": "in_struttura",
                                                   "anticipo_online_cents": 3000})
        r = self._giro()
        self.assertNotIn("I2", r["violazioni"], r)
        self.assertTrue(any("in struttura" in m and "1 " in m for m in r["non_eseguiti"]),
                        r["non_eseguiti"])

    def test_I2_senza_giornale_e_NON_ESEGUITO_non_pulito(self):
        os.remove(os.path.join(self.d, "finanza.db"))
        r = self._giro()
        self.assertNotIn("I2", r["verificati"])
        self.assertTrue(any(m.startswith("I2") for m in r["non_eseguiti"]), r["non_eseguiti"])

    def test_I3_ognuna_delle_tre_prove_BASTA_da_sola(self):
        """Il sopravvissuto del giro 3 del Giudice (`or -> and` in `_prova_firmata`): ogni
        prova va provata DA SOLA, senza le altre due, o l'`and` passa inosservato."""
        self._notti("villa", ["2027-05-01", "2027-05-02", "2027-05-03"], totali=3)
        self._pagata("SOLO_QUOTE", co="2027-05-02", firma="quote-firmato", idem="")
        self._pagata("SOLO_IDEM", ci="2027-05-02", co="2027-05-03", firma="", idem="firma-del-quote")
        self._pagata("SOLO_VOUCHER", ci="2027-05-03", co="2027-05-04", firma="", idem="",
                     extra={"voucher_token": "voucher-firmato"})
        for rif in ("SOLO_QUOTE", "SOLO_IDEM", "SOLO_VOUCHER"):
            self._incasso(rif, 30000)
        r = self._giro()
        self.assertNotIn("I3", r["violazioni"], r)

    def test_I3_una_pagata_senza_PROVA_FIRMATA(self):
        self._notti("villa", ["2027-05-01"])
        self._pagata("R1", co="2027-05-02", firma="", idem="")
        self._incasso("R1", 30000)
        r = self._giro()
        self.assertIn("I3", r["violazioni"], r)
        self.assertEqual(r["violazioni"]["I3"], ["R1"])

    def test_I4_un_importo_NEGATIVO_in_qualunque_archivio(self):
        self.assertTrue(self.sys.garanzia.apri("R9", 25000, alloggio_id="villa",
                                               ora_checkin_ts=1000))
        self._sql("g.db", "UPDATE garanzia SET host_riceve_cents=-5 WHERE prenotazione_id='R9'")
        r = self._giro()
        self.assertIn("I4", r["violazioni"], r)
        self.assertIn("g.db.garanzia.host_riceve_cents", str(r["violazioni"]["I4"]))

    def test_I5_una_garanzia_RILASCIATA_senza_prenotazione(self):
        self.assertTrue(self.sys.garanzia.apri("FANTASMA", 25000, alloggio_id="villa",
                                               ora_checkin_ts=1000))
        self.assertEqual(1, self.sys.garanzia.auto_rilascia(ora_ts=10 ** 10))
        r = self._giro()
        self.assertIn("I5", r["violazioni"], r)
        self.assertIn("sconosciuta", str(r["violazioni"]["I5"]))

    def test_I5_una_garanzia_rilasciata_su_una_PAGATA_e_regolare(self):
        self._notti("villa", ["2027-05-01"])
        self._pagata("R1", co="2027-05-02")
        self._incasso("R1", 30000)
        self.assertTrue(self.sys.garanzia.apri("R1", 25000, alloggio_id="villa",
                                               ora_checkin_ts=1000))
        self.assertEqual(1, self.sys.garanzia.auto_rilascia(ora_ts=10 ** 10))
        r = self._giro()
        self.assertNotIn("I5", r["violazioni"], r)


class TestUnArchivioRottoECieco(_Archivi):

    def test_un_archivio_ILLEGGIBILE_e_CIECO_e_gli_altri_si_leggono_lo_stesso(self):
        self._notti("villa", ["2027-05-01"])
        with io.open(os.path.join(self.d, "rotto.db"), "wb") as f:
            f.write(b"non sono un database sqlite, sono byte a caso" * 40)
        with self.assertLogs("core_auto.invarianti_archivi", level="INFO") as reg:
            r = self._giro()
        self.assertEqual(r["ciechi"], ["rotto.db"])
        self.assertEqual(r["letti"]["notti"], 1, "l'archivio rotto ha fermato la lettura degli altri")
        errori = [x for x in reg.records if x.levelname == "ERROR"]
        self.assertEqual(1, len(errori), reg.output)
        self.assertIsNotNone(errori[0].exc_info, "l'errore e' registrato SENZA la traccia")
        self.assertIn("ciechi=1", reg.output[-1])


class TestIlRapportoDelGuardiano(_Archivi):

    def _rapporto_pulito(self):
        return {"pulito": True, "conta": 0, "anomalie": {}, "non_eseguiti": []}

    def test_con_una_violazione_il_rapporto_NON_e_piu_pulito_e_conta_cresce(self):
        self._notti("villa", ["2027-05-01"])
        self._pagata("R1", co="2027-05-02", firma="", idem="")
        self._incasso("R1", 30000)
        rap = A.con_invarianti(self._rapporto_pulito(), self.d)
        self.assertFalse(rap["pulito"])
        self.assertEqual(rap["conta"], 1)
        self.assertEqual(rap["anomalie"][A.CHIAVE_ANOMALIA]["I3"], ["R1"])
        self.assertEqual(rap["invarianti"]["verificati"], list(A.CODICI))

    def test_su_archivi_sani_il_rapporto_resta_pulito_MA_porta_la_misura(self):
        self._notti("villa", ["2027-05-01"])
        rap = A.con_invarianti(self._rapporto_pulito(), self.d)
        self.assertTrue(rap["pulito"])
        self.assertEqual(rap["conta"], 0)
        self.assertNotIn(A.CHIAVE_ANOMALIA, rap["anomalie"])
        self.assertIn("invarianti", rap)

    def test_senza_cartella_dati_e_NON_ESEGUITO_mai_pulito_per_silenzio(self):
        rap = A.con_invarianti(self._rapporto_pulito(), "")
        self.assertNotIn("invarianti", rap)
        self.assertTrue(any("NON sono stati verificati" in m for m in rap["non_eseguiti"]),
                        rap["non_eseguiti"])

    def test_un_archivio_cieco_entra_fra_i_controlli_ciechi_del_Guardiano(self):
        with io.open(os.path.join(self.d, "rotto.db"), "wb") as f:
            f.write(b"x" * 1000)
        rap = A.con_invarianti(self._rapporto_pulito(), self.d)
        self.assertFalse(rap["pulito"])
        self.assertEqual(rap["anomalie"]["controllo_cieco"], ["invarianti_archivi:rotto.db"])

    def test_il_giro_quotidiano_fa_il_Guardiano_E_gli_invarianti(self):
        rap = A.giro_quotidiano(self.sys)
        self.assertIn("anomalie", rap)            # e' il rapporto di fase186...
        self.assertIn("soglie", rap)
        self.assertEqual(rap["invarianti"]["verificati"], list(A.CODICI))   # ...piu' il nostro
        self.assertTrue(rap["pulito"], rap["anomalie"])

    def test_il_giro_quotidiano_con_db_finanza_in_memoria_lo_DICHIARA(self):
        sis = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"M" * 32))
        rap = A.giro_quotidiano(sis)
        self.assertNotIn("invarianti", rap)
        self.assertTrue(any(m.startswith("invarianti_archivi") for m in rap["non_eseguiti"]),
                        rap["non_eseguiti"])

    def test_la_riga_del_registro_ha_UNA_forma_sola(self):
        r = {"verificati": ["I1", "I2"], "letti": {"archivi": 3, "notti": 2},
             "violazioni": {"I1": [1, 2]}, "non_eseguiti": ["x"], "ciechi": []}
        self.assertEqual(A.formatta_riga(r),
                         "INVARIANTI ARCHIVI | verificati=I1,I2 | letti=archivi:3 notti:2 | "
                         "violazioni=2 | non_eseguiti=1 | ciechi=0")


class TestIConfiniCheIlGiudiceHaTrovatoScoperti(unittest.TestCase):
    """Una guardia per ogni sopravvissuto del primo giro del Giudice della mutazione
    (`corsia_B_2026-09-04/giudice_fase202_giro1.log`: 59 provati, 23 sopravvissuti). Nessun
    criterio allargato: ogni confine qui sotto e' un comportamento che il modulo promette."""

    def test_intero_vero_non_bool_non_stringa(self):
        self.assertEqual(A._intero(5), 5)
        self.assertEqual(A._intero(-1), -1)
        self.assertEqual(A._intero(0), 0)
        self.assertIsNone(A._intero(True))
        self.assertIsNone(A._intero(False))
        self.assertIsNone(A._intero("5"))
        self.assertIsNone(A._intero(None))
        self.assertIsNone(A._intero(2.0))

    def test_le_notti_sono_l_intervallo_semiaperto_esatto(self):
        self.assertEqual(A._notti("2027-05-01", "2027-05-03"), ["2027-05-01", "2027-05-02"])
        self.assertEqual(A._notti("2027-05-01", "2027-05-02"), ["2027-05-01"])
        self.assertEqual(A._notti("2027-05-01", "2027-05-01"), [])
        self.assertEqual(A._notti("2027-05-03", "2027-05-01"), [])
        self.assertEqual(A._notti("boh", "2027-05-01"), [])

    def test_il_tetto_delle_notti_e_ESATTAMENTE_quattrocento(self):
        self.assertEqual(len(A._notti("2020-01-01", "2030-01-01")), 400)

    def test_su_una_notte_PIENA_ma_non_sovraprenotata_I1_tace(self):
        viol, note = A._giudica_i1([], [{"alloggio_id": "v", "giorno": "2027-05-01",
                                         "unita_totali": 2, "unita_occupate": 2}])
        self.assertEqual(viol, [])
        self.assertEqual(note, [])

    def test_una_notte_con_un_conteggio_NULLO_si_salta_senza_far_cadere_I1(self):
        viol, _n = A._giudica_i1([], [{"alloggio_id": "v", "giorno": "2027-05-01",
                                       "unita_totali": 1, "unita_occupate": None},
                                      {"alloggio_id": "v", "giorno": "2027-05-02",
                                       "unita_totali": None, "unita_occupate": 3}])
        self.assertEqual(viol, [])

    def test_a_UNA_unita_decide_il_nucleo_dimostrato_e_la_violazione_ha_la_sua_forma(self):
        pagate = [{"rif": "R1", "alloggio_id": "v", "stato": "pagato",
                   "check_in": "2027-05-01", "check_out": "2027-05-03"},
                  {"rif": "R2", "alloggio_id": "v", "stato": "pagato",
                   "check_in": "2027-05-02", "check_out": "2027-05-04"}]
        viol, _n = A._giudica_i1(pagate, [{"alloggio_id": "v", "giorno": "2027-05-01",
                                           "unita_totali": 1, "unita_occupate": 1}])
        self.assertEqual(viol, [("v", "R1", "R2")])
        # senza inventario la capienza e' 1: stessa forma
        viol2, _n = A._giudica_i1(pagate, [])
        self.assertEqual(viol2, [("v", "R1", "R2")])


class TestLeTabelleSiRiconosconoDalNomeEDalleColonne(unittest.TestCase):
    """Archivi SINTETICI (non del prodotto) per provare i confini del riconoscimento: il nome
    giusto con le colonne minime si legge; il nome sbagliato con le colonne giuste no."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def _archivio(self, nome, *comandi):
        con = sqlite3.connect(os.path.join(self.d, nome))
        with con:
            for c in comandi:
                con.execute(c)
        con.close()

    def test_le_colonne_MINIME_bastano_per_ogni_tabella(self):
        self._archivio("p.db", "CREATE TABLE pendenti (riferimento TEXT, alloggio_id TEXT, "
                               "check_in TEXT, check_out TEXT, stato TEXT)",
                       "INSERT INTO pendenti VALUES ('R1','v','2027-05-01','2027-05-02','pagato')")
        self._archivio("i.db", "CREATE TABLE inventario (alloggio_id TEXT, giorno TEXT, "
                               "unita_totali INTEGER, unita_occupate INTEGER)",
                       "INSERT INTO inventario VALUES ('v','2027-05-01',1,1)")
        self._archivio("g.db", "CREATE TABLE garanzia (prenotazione_id TEXT, stato TEXT)",
                       "INSERT INTO garanzia VALUES ('R1','in_garanzia')")
        self._archivio("y.db", "CREATE TABLE payout (prenotazione_id TEXT, host_id TEXT, "
                               "stato TEXT, minori INTEGER)",
                       "INSERT INTO payout VALUES ('R1','h','maturato',5)")
        self._archivio("f.db", "CREATE TABLE libro_giornale (tipo TEXT, riferimento TEXT, "
                               "importo_cents INTEGER)",
                       "INSERT INTO libro_giornale VALUES ('incasso','R1',7)")
        dati = A.leggi_archivi(self.d)
        self.assertEqual(dati["ciechi"], [])
        self.assertEqual((len(dati["prenotazioni"]), len(dati["inventario"]), len(dati["garanzie"]),
                          len(dati["payout"]), len(dati["giornale"])), (1, 1, 1, 1, 1))
        self.assertEqual(sorted(dati["tabelle_lette"]),
                         ["f.db.libro_giornale", "g.db.garanzia", "i.db.inventario",
                          "p.db.pendenti", "y.db.payout"])

    def test_il_nome_SBAGLIATO_con_le_colonne_giuste_NON_si_legge(self):
        self._archivio("x.db",
                       "CREATE TABLE pendenti_vecchi (riferimento TEXT, alloggio_id TEXT, "
                       "check_in TEXT, check_out TEXT, stato TEXT)",
                       "INSERT INTO pendenti_vecchi VALUES ('R1','v','2027-05-01','2027-05-02','pagato')",
                       "CREATE TABLE inventario_vecchio (alloggio_id TEXT, giorno TEXT, "
                       "unita_totali INTEGER, unita_occupate INTEGER)",
                       "INSERT INTO inventario_vecchio VALUES ('v','2027-05-01',1,9)",
                       "CREATE TABLE garanzie (prenotazione_id TEXT, stato TEXT)",
                       "INSERT INTO garanzie VALUES ('R1','rilasciato')",
                       "CREATE TABLE payout_vecchio (prenotazione_id TEXT, host_id TEXT, "
                       "stato TEXT, minori INTEGER)",
                       "INSERT INTO payout_vecchio VALUES ('R1','h','maturato',5)",
                       "CREATE TABLE giornale_vecchio (tipo TEXT, riferimento TEXT, "
                       "importo_cents INTEGER)",
                       "INSERT INTO giornale_vecchio VALUES ('incasso','R1',7)")
        dati = A.leggi_archivi(self.d)
        self.assertEqual(dati["ciechi"], [])
        self.assertEqual((dati["prenotazioni"], dati["inventario"], dati["garanzie"],
                          dati["payout"], dati["giornale"]), ([], [], [], [], []))
        self.assertEqual(dati["tabelle_lette"], [])
        # ...ma le colonne di DENARO si leggono ovunque (I4 non guarda il nome della tabella)
        self.assertEqual(len(dati["importi"]), 2)           # minori + importo_cents

    def test_I4_guarda_SOLO_le_colonne_di_denaro(self):
        self._archivio("z.db", "CREATE TABLE t (a_cents INTEGER, b INTEGER, c TEXT, minori INTEGER)",
                       "INSERT INTO t VALUES (1, -7, 'x', 2)",
                       "INSERT INTO t VALUES (3, -8, '-9', -3)")
        r = A.scansiona_archivi(self.d, ora=lambda: 1_800_000_000)
        self.assertEqual(r["letti"]["importi"], 4)          # a_cents e minori, due righe
        self.assertEqual(r["violazioni"].get("I4"), [("z.db.t.minori#2", -3)])

    def test_una_cartella_INESISTENTE_e_NON_ESEGUITO_e_il_conteggio_del_Guardiano_si_SOMMA(self):
        rap = A.con_invarianti({"pulito": False, "conta": 3, "anomalie": {"x": [1, 2, 3]},
                                "non_eseguiti": []}, os.path.join(self.d, "non", "esiste"))
        self.assertNotIn("invarianti", rap)
        self.assertEqual(rap["conta"], 3)
        self.assertTrue(any("NON sono stati verificati" in m for m in rap["non_eseguiti"]))
        self._archivio("g.db", "CREATE TABLE garanzia (prenotazione_id TEXT, stato TEXT, "
                               "host_riceve_cents INTEGER)",
                       "INSERT INTO garanzia VALUES ('R1','in_garanzia',-1)")
        rap = A.con_invarianti({"pulito": False, "conta": 3, "anomalie": {"x": [1, 2, 3]},
                                "non_eseguiti": []}, self.d)
        self.assertEqual(rap["conta"], 4, "il conteggio del Guardiano non si e' sommato")
        self.assertFalse(rap["pulito"])


class TestGliErroriPortanoLaTraccia(unittest.TestCase):
    """`exc_info=False` e' False, non None (lezione gia' pagata): qui si pretende LA traccia,
    una tupla col tipo dell'errore, in tutti e tre i punti in cui il modulo isola un guasto."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def _traccia(self, reg):
        errori = [x for x in reg.records if x.levelname == "ERROR"]
        self.assertEqual(1, len(errori), reg.output)
        self.assertIsInstance(errori[0].exc_info, tuple, "l'errore e' senza traccia")
        return errori[0].exc_info[0]

    def test_un_archivio_rotto_porta_la_traccia_di_sqlite(self):
        with io.open(os.path.join(self.d, "rotto.db"), "wb") as f:
            f.write(b"byte a caso" * 100)
        with self.assertLogs("core_auto.invarianti_archivi", level="ERROR") as reg:
            A.leggi_archivi(self.d)
        self.assertTrue(issubclass(self._traccia(reg), sqlite3.DatabaseError))

    def test_un_giudizio_che_esplode_e_NON_ESEGUITO_con_la_traccia(self):
        vero = A.i4_denaro_non_negativo

        def esplode(_importi):
            raise RuntimeError("il giudizio e' rotto")
        A.i4_denaro_non_negativo = esplode
        try:
            with self.assertLogs("core_auto.invarianti_archivi", level="INFO") as reg:
                r = A.scansiona_archivi(self.d, ora=lambda: 1_800_000_000)
        finally:
            A.i4_denaro_non_negativo = vero
        self.assertIs(self._traccia(reg), RuntimeError)
        self.assertNotIn("I4", r["verificati"])
        self.assertIn("I4: il giudizio e' fallito (vedi registro)", r["non_eseguiti"])

    def test_se_il_giro_degli_invarianti_esplode_il_Guardiano_prosegue_e_lo_DICE(self):
        vero = A.con_invarianti

        def esplode(_rap, _dir):
            raise RuntimeError("il giro e' rotto")
        A.con_invarianti = esplode
        try:
            sis = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"E" * 32))
            with self.assertLogs("core_auto.invarianti_archivi", level="ERROR") as reg:
                rap = A.giro_quotidiano(sis)
        finally:
            A.con_invarianti = vero
        self.assertIs(self._traccia(reg), RuntimeError)
        self.assertIn("anomalie", rap)
        self.assertTrue(any("il giro e' fallito" in m for m in rap["non_eseguiti"]),
                        rap["non_eseguiti"])


class TestI3SullaProvaFirmataVera(unittest.TestCase):
    """⛔ DIFETTO TROVATO LEGGENDO IL 2026-09-05 (latente: 0 pendenti in produzione). La
    prenotazione istantanea (`fase83._registra_hold`) salva `idem_key` (derivata dal quote_token
    firmato) e il `voucher_token` firmato nel corpo_json, ma NON la colonna `quote_token`; solo la
    richiesta 'in_attesa_host' la salva. Il primo giro di fase202 giudicava I3 col solo
    `quote_token`: ogni prenotazione PAGATA dalle rotte vere sarebbe risultata «senza prova» ->
    email quotidiana falsa sul Guardiano dei soldi. VISTA ROSSA sulla prima stesura.

    Qui la prenotazione la fanno le ROTTE VERE (quote -> book -> webhook), non un INSERT: e' l'unico
    modo di sapere cosa il prodotto scrive davvero nel record."""

    def setUp(self):
        import fase85_pagamenti_stripe as _stripe
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self._fetch_vero = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(
            lambda url, body, headers: {"url": "https://x/y", "id": "cs_prova202"})
        self.addCleanup(setattr, _stripe.ProviderStripe, "_fetch_reale", self._fetch_vero)
        d = self.d
        # valori FINTI che accendono il provider (la rete e' sostituita sopra): non sono segreti
        chiave_finta, firma_webhook_finta = "sk", "whsec_x"
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"P" * 32, con_registrazione_host=True,
            db_catalogo="%s/c.db" % d, db_inventario="%s/i.db" % d,
            db_registro_host="%s/r.db" % d, db_garanzia="%s/g.db" % d,
            db_payout="%s/y.db" % d, db_pendenti="%s/p.db" % d,
            db_accettazioni="%s/a.db" % d, db_tassa_comunale="%s/t.db" % d,
            db_finanza="%s/finanza.db" % d,
            stripe_secret_key=chiave_finta, stripe_webhook_secret=firma_webhook_finta,
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        from fase83_server import crea_router
        self.router = crea_router(self.sys, host_key="hk", admin_key="ak",
                                  base_url="https://bookinvip.com")

    def _g(self, metodo, path, body=None, headers=None):
        return self.router.gestisci(metodo, path, {},
                                    json.dumps(body) if body is not None else None, headers or {})

    def _prenotazione_pagata_dalle_rotte(self):
        import time
        from fase87_stripe_webhook import firma_di_test
        from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
        s, c = self._g("POST", "/api/host/registrazione",
                       {"email": "h202@x.it", "password": "password1", "accetta_termini": True,
                        "accetta_clausole": True, "accetta_privacy": True,
                        "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201)
        h = {"X-Host-Token": c["token"]}
        s, _ = self._g("POST", "/api/host/pubblica",
                       {"slug": "villa-202", "titolo": "Villa 202", "citta": "Roma",
                        "prezzo_notte_cents": 10000, "capacita": 2}, h)
        self.assertIn(s, (200, 201))
        s, _ = self._g("POST", "/api/host/disponibilita_range",
                       {"alloggio_id": "villa-202", "da": "2027-05-01", "a": "2027-05-10",
                        "unita_totali": 1, "prezzo_netto_cents": 10000}, h)
        self.assertIn(s, (200, 201))
        s, q = self._g("POST", "/api/concierge/quote",
                       {"alloggio_id": "villa-202", "check_in": "2027-05-02",
                        "check_out": "2027-05-04", "party": 2})
        self.assertEqual(s, 200)
        s, b = self._g("POST", "/api/concierge/book",
                       {"quote_token": q["quote_token"], "email": "o202@x.it"})
        self.assertEqual(s, 201, b)
        rif = b["riferimento"]
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        s, _ = self.router.gestisci("POST", "/api/payments/webhook", {}, pl,
                                    {"Stripe-Signature": firma_di_test(pl, "whsec_x",
                                                                       int(time.time()))})
        self.assertEqual(s, 200)
        rec = self.sys.pagamenti_pendenti.info(rif)
        self.assertEqual(rec["stato"], "pagato")
        return rif, rec

    def test_una_prenotazione_PAGATA_dalle_rotte_vere_ha_la_prova_firmata(self):
        rif, rec = self._prenotazione_pagata_dalle_rotte()
        r = A.scansiona_archivi(self.d, ora=lambda: 1_800_000_000)
        self.assertNotIn("I3", r["violazioni"],
                         "una prenotazione pagata dalle rotte vere risulta SENZA prova: il giudizio "
                         "I3 non guarda dove il prodotto scrive la prova (record: quote_token=%r "
                         "idem_key=%r)" % (rec.get("quote_token"), rec.get("idem_key")))
        self.assertIn("I3", r["verificati"])

    def test_una_riga_senza_NESSUNA_prova_e_una_violazione(self):
        pp = self.sys.pagamenti_pendenti
        self.assertTrue(pp.registra("NUDA", alloggio_id="villa-202", check_in="2027-05-06",
                                    check_out="2027-05-07", corpo_json=json.dumps({"totale_cents": 1})))
        self.assertIsNotNone(pp.conferma("NUDA"))
        r = A.scansiona_archivi(self.d, ora=lambda: 1_800_000_000)
        self.assertEqual(r["violazioni"].get("I3"), ["NUDA"])


class TestIlTickDiFase83ChiamaIlGiro(unittest.TestCase):
    """Il tick giornaliero e' una chiusura dentro `servi()`: si legge l'albero sintattico.
    VISTA ROSSA prima della modifica a fase83 (il tick chiamava il solo `scansiona`)."""

    def test_IL_TICK_GIORNALIERO_DI_fase83_CHIAMA_IL_GIRO_CON_GLI_INVARIANTI(self):
        with io.open(os.path.join(QUI, "fase83_server.py"), encoding="utf-8") as f:
            albero = ast.parse(f.read())
        tick = [n for n in ast.walk(albero)
                if isinstance(n, ast.FunctionDef) and n.name == "_tick_guardiano"]
        self.assertEqual(1, len(tick), "il tick giornaliero del Guardiano non si trova piu'")
        chiamate = {n.func.id for n in ast.walk(tick[0])
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("giro_quotidiano", chiamate,
                      "il tick non chiama `giro_quotidiano`: i cinque invarianti NON girano "
                      "in produzione ogni giorno")
        self.assertNotIn("scansiona", chiamate,
                         "il tick chiama ancora il solo `scansiona`: gli invarianti resterebbero fuori")
        importi = [n for n in ast.walk(tick[0]) if isinstance(n, ast.ImportFrom)
                   and n.module == "fase202_invarianti_archivi"]
        self.assertTrue(importi, "il tick non importa `giro_quotidiano` da fase202")


if __name__ == "__main__":
    unittest.main()
