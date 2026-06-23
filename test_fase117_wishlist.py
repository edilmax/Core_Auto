"""Test Fase 117 - Wishlist guest. SQLite :memory:."""
import unittest

from fase117_wishlist import LISTA_DEFAULT, crea_wishlist


def wl():
    w = crea_wishlist(":memory:")
    w.inizializza_schema()
    return w


class TestWishlist(unittest.TestCase):
    def test_aggiungi_elenca_contiene(self):
        w = wl()
        self.assertTrue(w.aggiungi("g1", "casa-roma"))
        self.assertTrue(w.aggiungi("g1", "casa-milano"))
        self.assertEqual(w.elenca("g1"), ["casa-roma", "casa-milano"])
        self.assertTrue(w.contiene("g1", "casa-roma"))
        self.assertFalse(w.contiene("g1", "casa-x"))

    def test_idempotente(self):
        w = wl()
        w.aggiungi("g1", "casa-roma")
        w.aggiungi("g1", "casa-roma")
        self.assertEqual(w.elenca("g1"), ["casa-roma"])

    def test_rimuovi(self):
        w = wl()
        w.aggiungi("g1", "casa-roma")
        self.assertTrue(w.rimuovi("g1", "casa-roma"))
        self.assertEqual(w.elenca("g1"), [])
        self.assertFalse(w.rimuovi("g1", "casa-roma"))

    def test_liste_multiple(self):
        w = wl()
        w.aggiungi("g1", "casa-roma")                       # Preferiti default
        w.aggiungi("g1", "casa-mare", lista="Estate")
        self.assertEqual(sorted(w.liste("g1")), ["Estate", LISTA_DEFAULT])
        self.assertEqual(w.elenca("g1", lista="Estate"), ["casa-mare"])

    def test_isolamento_guest(self):
        w = wl()
        w.aggiungi("g1", "casa-roma")
        self.assertEqual(w.elenca("g2"), [])

    def test_input_invalido(self):
        w = wl()
        self.assertFalse(w.aggiungi("", "casa"))
        self.assertFalse(w.aggiungi("g1", ""))
        self.assertEqual(w.elenca(""), [])


if __name__ == "__main__":
    unittest.main()
