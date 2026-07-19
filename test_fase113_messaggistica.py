"""Test Fase 113 - Messaggistica host-guest. SQLite :memory:."""
import unittest

from fase113_messaggistica import Messaggistica, crea_messaggistica, maschera_pii


def msg():
    m = crea_messaggistica(":memory:")
    m.inizializza_schema()
    return m


class TestMessaggistica(unittest.TestCase):
    def test_invio_e_thread(self):
        m = msg()
        self.assertTrue(m.invia("p1", "H", "G", "G", "Ciao a che ora il check-in?"))
        self.assertTrue(m.invia("p1", "H", "G", "H", "Dalle 15"))
        t = m.thread("p1", "H")
        self.assertEqual(len(t), 2)
        self.assertEqual(t[0]["mittente"], "G")

    def test_mittente_fuori_thread_rifiutato(self):
        m = msg()
        self.assertFalse(m.invia("p1", "H", "G", "X", "spam"))

    def test_testo_vuoto_rifiutato(self):
        m = msg()
        self.assertFalse(m.invia("p1", "H", "G", "H", "   "))

    def test_estraneo_non_legge(self):
        m = msg()
        m.invia("p1", "H", "G", "H", "privato")
        self.assertEqual(m.thread("p1", "ESTRANEO"), [])

    def test_maschera_pii(self):
        m = msg()
        m.invia("p1", "H", "G", "G", "scrivimi a mario@x.com o +39 333 1234567")
        testo = m.thread("p1", "H")[0]["testo"]
        self.assertNotIn("mario@x.com", testo)
        self.assertIn("[email rimossa]", testo)
        self.assertIn("[contatto rimosso]", testo)

    def test_maschera_pii_pura(self):
        self.assertEqual(maschera_pii("ok"), "ok")
        self.assertIn("[email rimossa]", maschera_pii("a@b.com"))

    def test_maschera_non_storpia_url_prova(self):
        """REGRESSIONE (2026-07-19, radice VERA dei rossi 'orfano/persa' della suite):
        il filtro anti-telefono scambiava per numero il run '00'+8 cifre dentro il nome
        esadecimale della foto e lo storpiava -> link rotto in chat + prova destinata
        alla pulizia orfani. I due nomi qui sotto sono ESATTAMENTE quelli dei due
        fallimenti reali in suite: sul codice vecchio questo test e' ROSSO."""
        for nome in ("faa2e65a8a8376fa005754588289e254.png",
                     "52fea0069627654ae479cbc4fc24cbec.png"):
            t = "\U0001f4ce PROVA FOTO: /uploads/" + nome
            self.assertEqual(maschera_pii(t), t, nome)
        # e con TUTTE le estensioni ammesse dai magic-bytes
        for ext in ("png", "jpg", "webp", "gif"):
            u = "/uploads/" + "a0" * 4 + "0057545882890057" + "b1" * 4 + "." + ext
            self.assertEqual(maschera_pii(u), u, ext)

    def test_maschera_pii_resta_severa_attorno_alle_url(self):
        """La protezione url NON deve aprire buchi: telefono/email nello STESSO messaggio
        della url restano mascherati; una url 'finta' (non 32 esadecimali) NON e' protetta."""
        t = maschera_pii("guarda /uploads/faa2e65a8a8376fa005754588289e254.png "
                         "e chiamami al 0039 333 1234567 o su x@y.it")
        self.assertIn("/uploads/faa2e65a8a8376fa005754588289e254.png", t)
        self.assertIn("[contatto rimosso]", t)
        self.assertIn("[email rimossa]", t)
        self.assertNotIn("333", t)
        # furbo che traveste il numero da url: NON combacia col formato stretto -> mascherato
        self.assertNotIn("00393331234567", maschera_pii("/uploads/00393331234567.png"))
        # letterale \x00U0\x00 digitato dall'utente: nessuna url accantonata -> resta com'e',
        # e con una url presente NON deve produrre doppie sostituzioni sbagliate
        strano = maschera_pii("\x00U0\x00 /uploads/" + "ab" * 16 + ".png")
        self.assertEqual(strano.count("/uploads/"), 2)  # il letterale diventa la stessa url: innocuo

    def test_segna_letti(self):
        m = msg()
        m.invia("p1", "H", "G", "G", "uno")
        m.invia("p1", "H", "G", "G", "due")
        self.assertEqual(m.segna_letti("p1", "H"), 2)       # H legge i 2 di G
        self.assertEqual(m.segna_letti("p1", "H"), 0)       # già letti

    def test_isolato_input_vuoto(self):
        m = msg()
        self.assertFalse(m.invia("", "H", "G", "H", "x"))
        self.assertEqual(m.thread("", "H"), [])


if __name__ == "__main__":
    unittest.main()
