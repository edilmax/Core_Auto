"""GUARDIA — l'alloggio ha il suo FUSO, e i calcoli sul tempo lo rispettano.

L'audit del 2026-07-22 aveva trovato che ogni calcolo sul tempo usava il fuso del SERVER,
e l'alloggio non aveva un fuso nel modello dati: a Honolulu (UTC-10) le 24 ore di
contestazione si chiudevano dopo 12 ore vere. Come rimedio provvisorio si era ancorato al
fuso "prudente" (l'estremo del pianeta), largo ma non esatto.

Ora l'alloggio ha il suo fuso IANA ('Asia/Tokyo', 'Pacific/Honolulu', ...) nel database, e
tutti i calcoli — check-in, pass serratura, sblocco recensioni, finestra di cancellazione —
sono ancorati all'ora LOCALE del posto. Questa guardia lo prova, e prova che due alloggi in
due fusi diversi danno istanti diversi (il che, col vecchio codice, non poteva succedere).

ZERO DIPENDENZE: `zoneinfo` (stdlib) col database IANA di sistema, presente in produzione.
"""

import datetime as dt
import os
import sqlite3
import tempfile
import unittest

import fase187_fuso_orario as F
from fase57_vetrina import crea_catalogo, valida_scheda
from fase83_server import _istante_checkin, _mezzanotte_checkout


class TestUtilityFuso(unittest.TestCase):

    def test_15_locali_sono_istanti_diversi_in_fusi_diversi(self):
        tokyo = F.istante_locale("2026-09-05", 15, "Asia/Tokyo")
        roma = F.istante_locale("2026-09-05", 15, "Europe/Rome")
        hono = F.istante_locale("2026-09-05", 15, "Pacific/Honolulu")
        # tre momenti distinti (col vecchio codice erano tutti uguali)
        self.assertEqual(len({tokyo, roma, hono}), 3)
        # e nell'ordine giusto: Tokyo (est) prima di Roma, Roma prima di Honolulu (ovest)
        self.assertLess(tokyo, roma)
        self.assertLess(roma, hono)
        # Honolulu 15:00 = 19 ore dopo Tokyo 15:00 dello stesso giorno
        self.assertEqual((hono - tokyo) / 3600, 19)

    def test_deduzione_da_citta_e_paese(self):
        self.assertEqual(F.fuso_da_luogo("Honolulu", "US"), "Pacific/Honolulu")
        self.assertEqual(F.fuso_da_luogo("Tokyo", "JP"), "Asia/Tokyo")
        self.assertEqual(F.fuso_da_luogo("Roma", "IT"), "Europe/Rome")
        # citta' ignota in un paese MULTI-fuso (US) -> vuoto, mai indovinare
        self.assertEqual(F.fuso_da_luogo("Cittadina Ignota", "US"), "")

    def test_fuso_finto_non_e_valido(self):
        self.assertFalse(F.fuso_valido("Pippo/Baudo"))
        self.assertFalse(F.fuso_valido(""))
        self.assertTrue(F.fuso_valido("Asia/Tokyo"))

    def test_non_solleva_mai(self):
        for cattivo in (None, 123, "", "x/y/z", "2026-13-40"):
            try:
                F.istante_locale(cattivo, 15, "Asia/Tokyo")
                F.istante_locale("2026-09-05", 15, cattivo)
                F.fuso_da_luogo(cattivo, cattivo)
            except Exception as e:
                self.fail("solleva su %r: %s" % (cattivo, e))


class TestModelloDati(unittest.TestCase):
    """Il fuso si salva nel DB dell'alloggio e si rilegge."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.cat = crea_catalogo(os.path.join(d, "c.db"))
        self.cat.inizializza_schema()

    def _pubblica(self, slug, citta, paese="", fuso=None):
        dati = {"host_id": "h1", "slug": slug, "titolo": "T", "citta": citta,
                "paese": paese, "prezzo_notte_cents": 15000, "capacita": 2}
        if fuso is not None:
            dati["fuso"] = fuso
        ok, cod, sc = valida_scheda(dati)
        self.assertTrue(ok, cod)
        self.cat.pubblica(sc)
        return self.cat.dettaglio(slug)

    def test_fuso_dedotto_e_salvato(self):
        self.assertEqual(self._pubblica("h", "Honolulu", "US")["fuso"], "Pacific/Honolulu")
        self.assertEqual(self._pubblica("t", "Tokyo", "JP")["fuso"], "Asia/Tokyo")

    def test_fuso_esplicito_valido_vince(self):
        self.assertEqual(self._pubblica("z", "Ovunque", "", "Asia/Dubai")["fuso"],
                         "Asia/Dubai")

    def test_fuso_esplicito_invalido_scartato(self):
        self.assertEqual(self._pubblica("w", "Ovunque", "", "Fuso/Falso")["fuso"], "")

    def test_citta_ignota_paese_ambiguo_resta_vuoto(self):
        self.assertEqual(self._pubblica("x", "Cittadina Ignota", "US")["fuso"], "")


class TestAncoraggioAiCalcoli(unittest.TestCase):
    """I calcoli del server usano il fuso dell'alloggio quando c'e'."""

    def test_checkin_ancorato_al_fuso_vero(self):
        tokyo = _istante_checkin("2026-09-05", "Asia/Tokyo")
        hono = _istante_checkin("2026-09-05", "Pacific/Honolulu")
        self.assertIsNotNone(tokyo)
        self.assertIsNotNone(hono)
        self.assertNotEqual(tokyo, hono, "due fusi diversi danno lo stesso istante")
        # Tokyo 15:00 e' PRIMA di Honolulu 15:00 (19h di differenza)
        self.assertEqual((hono - tokyo) / 3600, 19)

    def test_senza_fuso_ripiego_prudente_non_solleva(self):
        # senza fuso si usa il ripiego prudente (mai None su una data valida)
        self.assertIsNotNone(_istante_checkin("2026-09-05", ""))
        self.assertIsNotNone(_mezzanotte_checkout("2026-09-08", ""))

    def test_recensione_mezzanotte_locale(self):
        m_tokyo = _mezzanotte_checkout("2026-09-08", "Asia/Tokyo")
        m_hono = _mezzanotte_checkout("2026-09-08", "Pacific/Honolulu")
        self.assertNotEqual(m_tokyo, m_hono)
        # mezzanotte a Tokyo arriva 19h PRIMA che a Honolulu
        self.assertEqual((m_hono - m_tokyo) / 3600, 19)

    def test_il_vecchio_calcolo_appiattiva_tutto(self):
        """La prova che il fuso serve: col vecchio metodo (UTC per tutti) Tokyo e Honolulu
        avrebbero dato lo STESSO istante. Se un giorno tornassero uguali, il fuso non
        starebbe piu' ancorando niente."""
        tokyo = _istante_checkin("2026-09-05", "Asia/Tokyo")
        hono = _istante_checkin("2026-09-05", "Pacific/Honolulu")
        self.assertNotEqual(tokyo, hono)


if __name__ == "__main__":
    unittest.main(verbosity=2)
