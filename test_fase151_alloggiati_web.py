"""Test Fase 151 - Alloggiati Web. Larghezza fissa, deterministico."""
import unittest

from fase151_alloggiati_web import (LUNGHEZZA_RECORD, genera_file, genera_schedina)

OSP = {"ruolo": "singolo", "cognome": "Rossi", "nome": "Mario",
       "data_arrivo": "2026-08-01", "giorni": 3, "sesso": "M",
       "data_nascita": "1980-05-10", "cittadinanza": "100000100",
       "tipo_doc": "IDENT", "num_doc": "AB12345", "luogo_doc": "100000100"}


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

    def test_giorni_clamp(self):
        self.assertEqual(genera_schedina(dict(OSP, giorni=99))[12:14], "01")


class TestFile(unittest.TestCase):
    def test_gated_default_off(self):
        self.assertEqual(genera_file([OSP]), "")

    def test_attivo_genera_righe(self):
        out = genera_file([OSP, dict(OSP, cognome="Bianchi")], attivo=True)
        self.assertEqual(out.count("\r\n"), 2)
        self.assertEqual(len(out.split("\r\n")[0]), LUNGHEZZA_RECORD)

    def test_record_invalidi_saltati(self):
        out = genera_file([OSP, {"cognome": "X"}, None], attivo=True)
        self.assertEqual(out.count("\r\n"), 1)


if __name__ == "__main__":
    unittest.main()
