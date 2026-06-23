"""Test Fase 127 - Check-in digitale. SQLite :memory:, emettitore pass finto."""
import unittest

from fase127_checkin_digitale import crea_checkin_digitale, valida_ospiti


class PassFinto:
    def emetti(self, pren, alloggio, **kw):
        return "PASS-%s-%s" % (pren, alloggio)


OSP = [{"nome": "Mario Rossi", "documento": "AB12345"}]


def cd():
    c = crea_checkin_digitale(":memory:", PassFinto())
    c.inizializza_schema()
    return c


class TestValida(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(len(valida_ospiti(OSP, 2)), 1)

    def test_oltre_capacita(self):
        self.assertIsNone(valida_ospiti(OSP * 3, 2))

    def test_documento_invalido(self):
        self.assertIsNone(valida_ospiti([{"nome": "X Y", "documento": "!!"}], 2))

    def test_vuoto(self):
        self.assertIsNone(valida_ospiti([], 2))


class TestCheckin(unittest.TestCase):
    def test_flusso_e_sblocco(self):
        c = cd()
        r = c.pre_registra("p1", "casa-1", OSP, 2)
        self.assertTrue(r["ok"])
        self.assertTrue(c.completato("p1"))
        self.assertEqual(c.sblocca("p1", "casa-1"), "PASS-p1-casa-1")

    def test_sblocco_negato_senza_checkin(self):
        c = cd()
        self.assertIsNone(c.sblocca("p1", "casa-1"))        # non pre-registrato

    def test_ospiti_invalidi_no_checkin(self):
        c = cd()
        r = c.pre_registra("p1", "casa-1", [{"nome": "X", "documento": "!!"}], 2)
        self.assertFalse(r["ok"])
        self.assertFalse(c.completato("p1"))

    def test_id_mancante(self):
        c = cd()
        self.assertFalse(c.pre_registra("", "casa-1", OSP, 2)["ok"])

    def test_pass_solleva_isolato(self):
        class Boom:
            def emetti(self, *a, **k):
                raise RuntimeError("pass giu")
        c = crea_checkin_digitale(":memory:", Boom())
        c.inizializza_schema()
        c.pre_registra("p1", "casa-1", OSP, 2)
        self.assertIsNone(c.sblocca("p1", "casa-1"))


if __name__ == "__main__":
    unittest.main()
