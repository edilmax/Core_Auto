"""Test Fase 151 - Alloggiati Web. Larghezza fissa, deterministico."""
import datetime
import shutil
import tempfile
import unittest

from fase151_alloggiati_web import (ITALIA, LUNGHEZZA_RECORD, TIPO_ALLOGGIATO, carica_tabelle,
                                    errori_schedina, genera_file, genera_schedina)

OSP = {"ruolo": "singolo", "cognome": "Rossi", "nome": "Mario",
       "data_arrivo": "2026-08-01", "giorni": 3, "sesso": "M",
       "data_nascita": "1980-05-10", "comune_nascita": "412058091", "prov_nascita": "RM",
       "stato_nascita": "100000100", "cittadinanza": "100000100",
       "tipo_doc": "IDENT", "num_doc": "AB12345", "luogo_doc": "412058091"}
ESTERO = dict(OSP, cognome="Smith", nome="Anna", sesso="F", comune_nascita="",
              prov_nascita="", stato_nascita="100000219", cittadinanza="100000219",
              tipo_doc="PASOR", num_doc="X1234567", luogo_doc="100000219")


class TestSchedina(unittest.TestCase):
    def test_lunghezza_fissa(self):
        r = genera_schedina(OSP)
        self.assertEqual(len(r), LUNGHEZZA_RECORD)

    def test_campi_posizionati(self):
        r = genera_schedina(OSP)
        self.assertEqual(r[:2], "16")                       # tipo singolo
        self.assertEqual(r[2:12], "01/08/2026")             # data arrivo
        self.assertEqual(r[12:14], "03")                    # giorni
        self.assertTrue(r[14:64].startswith("ROSSI"))       # cognome uppercase

    def test_familiare_senza_documento(self):
        fam = dict(OSP, ruolo="familiare")
        r = genera_schedina(fam)
        self.assertEqual(r[:2], "19")
        # campi documento (tipo_doc 5 + num_doc 20 + luogo_doc 9 = ultimi 34) = spazi
        self.assertEqual(r[-34:].strip(), "")

    def test_accenti_ascii(self):
        r = genera_schedina(dict(OSP, cognome="Verdì"))
        self.assertIn("VERDI", r)

    def test_dati_minimi_mancanti(self):
        self.assertEqual(genera_schedina({"cognome": "Rossi"}), "")   # manca arrivo/nome
        self.assertEqual(genera_schedina("x"), "")

    def test_giorni_fuori_misura_non_diventano_un_giorno(self):
        self.assertEqual(genera_schedina(dict(OSP, giorni=99)), "")


class TestLaSchedinaNonMenteAllaQuestura(unittest.TestCase):
    """Difetti vivi trovati il 30/9 rileggendo il manuale (CREAFILE.pdf p. 4-7): la schedina
    usciva lo stesso, con un dato falso o con un campo obbligatorio vuoto. Il portale la
    scarta, oppure -- peggio -- la accetta col dato sbagliato, e l'obbligo e' dell'host."""

    def test_OLTRE_30_giorni_non_si_scrive_un_giorno(self):
        self.assertEqual(genera_schedina(dict(OSP, giorni=30))[12:14], "30")
        for giorni in (31, 0, -2, "3", 2.5, True, None):
            self.assertEqual(genera_schedina(dict(OSP, giorni=giorni)), "", giorni)

    def test_un_a_capo_dentro_un_campo_non_spezza_il_file(self):
        for campo in ("cognome", "nome", "num_doc"):
            for sporco in ("Ros\r\nsi", "Ros\nsi", "Ros\tsi", "Ros\x00si", "Ros\x7fsi"):
                self.assertEqual(genera_schedina(dict(OSP, **{campo: sporco})), "",
                                 (campo, sporco))
                self.assertEqual(errori_schedina(dict(OSP, **{campo: sporco})),
                                 ["%s: caratteri di controllo (a capo, tabulazione...)" % campo])

    def test_lo_spazio_non_e_un_carattere_di_controllo(self):
        r = genera_schedina(dict(OSP, cognome="De Luca", nome="Anna Maria"))
        self.assertEqual(r[14:21], "DE LUCA")
        self.assertEqual(r[64:74], "ANNA MARIA")

    def test_i_campi_obbligatori_per_tutti(self):
        for campo in ("sesso", "data_nascita", "stato_nascita", "cittadinanza"):
            for ruolo in ("singolo", "familiare"):
                self.assertEqual(genera_schedina(dict(OSP, ruolo=ruolo, **{campo: ""})), "",
                                 (campo, ruolo))

    def test_il_documento_e_obbligatorio_per_singolo_capofamiglia_capogruppo(self):
        for ruolo in ("singolo", "capofamiglia", "capogruppo"):
            for campo in ("tipo_doc", "num_doc", "luogo_doc"):
                self.assertEqual(genera_schedina(dict(OSP, ruolo=ruolo, **{campo: ""})), "",
                                 (ruolo, campo))
        senza_doc = dict(OSP, ruolo="familiare", tipo_doc="", num_doc="", luogo_doc="")
        self.assertEqual(len(genera_schedina(senza_doc)), LUNGHEZZA_RECORD)

    def test_nato_in_Italia_vuole_comune_e_provincia_nato_fuori_no(self):
        self.assertEqual(genera_schedina(dict(OSP, comune_nascita="")), "")
        self.assertEqual(genera_schedina(dict(OSP, prov_nascita="")), "")
        self.assertEqual(len(genera_schedina(ESTERO)), LUNGHEZZA_RECORD)
        self.assertEqual(genera_schedina(dict(ESTERO, comune_nascita="412058091")), "")

    def test_una_data_che_non_esiste_non_si_scrive(self):
        self.assertEqual(genera_schedina(dict(OSP, data_nascita="1980-02-31")), "")
        self.assertEqual(genera_schedina(dict(OSP, data_arrivo="2026-13-01")), "")

    def test_un_ruolo_sconosciuto_non_diventa_ospite_singolo(self):
        self.assertEqual(genera_schedina(dict(OSP, ruolo="capo")), "")
        self.assertEqual(genera_schedina({k: v for k, v in OSP.items() if k != "ruolo"})[:2],
                         "16")

    def test_il_sesso_ammette_solo_i_due_codici_del_manuale(self):
        for sesso in ("X", "3", "maschio"):
            self.assertEqual(genera_schedina(dict(OSP, sesso=sesso)), "", sesso)

    def test_un_campo_troppo_lungo_non_si_taglia_in_silenzio(self):
        # rilievo a1 di GML (Compito 7): un numero di documento tagliato e' un numero FALSO
        for campo, lung in (("num_doc", 20), ("cognome", 50), ("nome", 30)):
            giusto = dict(OSP, **{campo: "A" * lung})
            self.assertEqual(len(genera_schedina(giusto)), LUNGHEZZA_RECORD, campo)
            lungo = dict(OSP, **{campo: "A" * (lung + 1)})
            self.assertEqual(genera_schedina(lungo), "", campo)
            self.assertTrue(errori_schedina(lungo)[0].startswith(campo), campo)

    def test_una_lettera_che_non_si_trascrive_non_sparisce(self):
        # rilievo a2 e b1 di GML: «Łukasz» usciva «UKASZ», un nome cinese «cognome mancante»
        for cognome in ("Łukasz", "Sørensen", "Weiß", "Đorđević", "Æsir", "王"):
            ospite = dict(OSP, cognome=cognome)
            self.assertEqual(genera_schedina(ospite), "", cognome)
            self.assertIn("caratteri latini", errori_schedina(ospite)[0], cognome)
        for cognome, atteso in (("Verdì", "VERDI"), ("Niccolò", "NICCOLO"),
                                ("Müller", "MULLER"), ("Ñúñez", "NUNEZ")):
            self.assertEqual(genera_schedina(dict(OSP, cognome=cognome))[14:14 + len(atteso)],
                             atteso)

    def test_nessuno_nasce_dopo_l_arrivo(self):
        # rilievo a3 di GML: «nato nel 2090» usciva nel file
        self.assertEqual(genera_schedina(dict(OSP, data_nascita="2090-01-01")), "")
        self.assertEqual(genera_schedina(dict(OSP, data_nascita="2026-08-02")), "")
        self.assertEqual(len(genera_schedina(dict(OSP, data_nascita="2026-08-01"))),
                         LUNGHEZZA_RECORD)

    def test_l_errore_dice_il_perche(self):
        self.assertEqual(errori_schedina(OSP), [])
        self.assertEqual(errori_schedina(dict(OSP, giorni=31)), ["giorni: da 1 a 30"])
        self.assertEqual(errori_schedina(dict(OSP, ruolo="familiare", cittadinanza="")),
                         ["cittadinanza mancante"])


class TestLeTabelleUfficiali(unittest.TestCase):
    """Le 4 tabelle del portale (area download, senza login), copiate in deploy/alloggiati/."""

    @classmethod
    def setUpClass(cls):
        cls.t = carica_tabelle()

    def test_le_tabelle_vere_si_caricano(self):
        self.assertGreater(len(self.t["COMUNI"]), 11000)
        self.assertGreater(len(self.t["STATI"]), 230)
        self.assertGreater(len(self.t["DOCUMENTI"]), 90)
        self.assertEqual(self.t["COMUNI"]["412058091"]["descrizione"], "ROMA")
        self.assertEqual(self.t["COMUNI"]["412058091"]["provincia"], "RM")
        self.assertEqual(self.t["STATI"][ITALIA]["descrizione"], "ITALIA")

    def test_i_tipi_del_programma_sono_quelli_della_tabella(self):
        self.assertEqual(set(self.t["TIPO_ALLOGGIATO"]), set(TIPO_ALLOGGIATO.values()))

    def test_gli_ospiti_buoni_passano_coi_codici_veri(self):
        self.assertEqual(errori_schedina(OSP, self.t), [])
        self.assertEqual(errori_schedina(ESTERO, self.t), [])
        self.assertEqual(len(genera_schedina(OSP, self.t)), LUNGHEZZA_RECORD)

    def test_un_codice_sbagliato_ferma_la_schedina(self):
        casi = {"stato_nascita": dict(OSP, stato_nascita="100009999", comune_nascita="",
                                      prov_nascita=""),
                "cittadinanza": dict(OSP, cittadinanza="100000210"),   # Cecoslovacchia
                "comune_nascita": dict(OSP, comune_nascita="999999999"),
                "prov_nascita": dict(OSP, prov_nascita="MI"),
                "tipo_doc": dict(OSP, tipo_doc="XXXXX"),
                "luogo_doc": dict(OSP, luogo_doc=ITALIA)}
        for campo, ospite in casi.items():
            errori = errori_schedina(ospite, self.t)
            self.assertEqual(len(errori), 1, (campo, errori))
            self.assertTrue(errori[0].startswith(campo), (campo, errori))
            self.assertEqual(genera_schedina(ospite, self.t), "", campo)
            self.assertEqual(len(genera_schedina(ospite)), LUNGHEZZA_RECORD, campo)

    def test_un_comune_soppresso_vale_solo_per_chi_e_nato_prima(self):
        # ABBADIA ALPINA (TO), fine validita' 31/12/1983 nella tabella ufficiale
        self.assertIsNotNone(self.t["COMUNI"]["401001501"]["fine"])
        prima = dict(OSP, comune_nascita="401001501", prov_nascita="TO",
                     data_nascita="1980-05-10")
        self.assertEqual(errori_schedina(prima, self.t), [])
        dopo = dict(prima, data_nascita="1990-05-10")
        self.assertEqual(len(errori_schedina(dopo, self.t)), 1)
        # il giorno di fine validita' conta ancora (la tabella non lo dice: scelto il piu'
        # largo, cosi' un ospite vero non resta fuori), quello dopo no
        self.assertEqual(errori_schedina(dict(prima, data_nascita="1983-12-31"), self.t), [])
        self.assertEqual(len(errori_schedina(dict(prima, data_nascita="1984-01-01"),
                                             self.t)), 1)

    def test_senza_tabelle_non_si_scrive_niente(self):
        vuota = tempfile.mkdtemp()
        try:
            nessuna = carica_tabelle(vuota)
        finally:
            shutil.rmtree(vuota, ignore_errors=True)
        self.assertEqual(nessuna, {n: {} for n in ("COMUNI", "STATI", "DOCUMENTI",
                                                   "TIPO_ALLOGGIATO")})
        self.assertIn("tabelle ufficiali assenti", errori_schedina(OSP, nessuna)[0])
        self.assertEqual(genera_file([OSP], attivo=True, tabelle=nessuna), "")

    def test_l_arrivo_solo_oggi_o_ieri(self):
        arrivo = datetime.date(2026, 8, 1)          # la data_arrivo di OSP
        for oggi in (arrivo, arrivo + datetime.timedelta(days=1)):
            self.assertEqual(errori_schedina(OSP, oggi=oggi), [], oggi)
        for oggi in (arrivo + datetime.timedelta(days=2), arrivo - datetime.timedelta(days=1)):
            self.assertEqual(errori_schedina(OSP, oggi=oggi),
                             ["data_arrivo: il portale accetta solo oggi o ieri"], oggi)


class TestFile(unittest.TestCase):
    def test_gated_default_off(self):
        self.assertEqual(genera_file([OSP]), "")

    def test_attivo_genera_righe(self):
        out = genera_file([OSP, dict(OSP, cognome="Bianchi")], attivo=True)
        self.assertEqual(out.count("\r\n"), 1)
        self.assertEqual(len(out.split("\r\n")[0]), LUNGHEZZA_RECORD)

    def test_record_invalidi_saltati(self):
        out = genera_file([OSP, {"cognome": "X"}, None], attivo=True)
        self.assertEqual(out, genera_schedina(OSP))


class TestACapoComeDiceIlManuale(unittest.TestCase):
    """Manuale del portale (CREAFILE.pdf, p. 6-7): CR+LF alla fine di ogni riga, «Solo per
    l'ultima riga, ovvero per l'ultimo alloggiato dell'elenco, non vanno aggiunti tali
    caratteri». Righe da 170 caratteri, l'ultima da 168."""

    def test_NESSUN_a_capo_dopo_l_ultima_riga(self):
        out = genera_file([OSP, dict(OSP, cognome="Bianchi"), dict(OSP, cognome="Verdi")],
                          attivo=True)
        self.assertFalse(out.endswith("\r\n"), repr(out[-6:]))
        righe = out.split("\r\n")
        self.assertEqual([len(r) for r in righe], [LUNGHEZZA_RECORD] * 3)
        self.assertEqual(len(out), 3 * LUNGHEZZA_RECORD + 2 * 2)

    def test_un_ospite_solo_e_una_riga_senza_a_capo(self):
        out = genera_file([OSP], attivo=True)
        self.assertEqual(len(out), LUNGHEZZA_RECORD)
        self.assertNotIn("\r", out)
        self.assertNotIn("\n", out)


if __name__ == "__main__":
    unittest.main()
