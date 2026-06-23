"""Test Fase 123 - Web Push. SQLite :memory:, fetch/firma iniettati: nessuna rete."""
import unittest

from fase123_web_push import crea_web_push

SUB = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "k", "auth": "a"}}


def wp(**kw):
    w = crea_web_push(":memory:", **kw)
    w.inizializza_schema()
    return w


class TestWebPush(unittest.TestCase):
    def test_registra_e_disiscrivi(self):
        w = wp()
        self.assertTrue(w.registra("g1", SUB))
        self.assertTrue(w.disiscrivi("g1", SUB["endpoint"]))
        self.assertFalse(w.disiscrivi("g1", SUB["endpoint"]))

    def test_sub_invalida_rifiutata(self):
        w = wp()
        self.assertFalse(w.registra("g1", {"endpoint": "http://x"}))   # no https/keys
        self.assertFalse(w.registra("", SUB))

    def test_gated_senza_vapid(self):
        w = wp()
        w.registra("g1", SUB)
        self.assertEqual(w.invia("g1", "T", "C"), 0)        # niente VAPID -> 0

    def test_invio_ok(self):
        visti = {}
        w = wp(vapid_public="pub", firma_vapid=lambda ep: "vapid t=" + ep,
               fetch=lambda u, b, h: visti.update(u=u, h=h) or 201)
        w.registra("g1", SUB)
        self.assertEqual(w.invia("g1", "Prenotazione", "confermata", url="/voucher"), 1)
        self.assertEqual(visti["u"], SUB["endpoint"])
        self.assertTrue(visti["h"]["Authorization"].startswith("vapid"))

    def test_invio_isolato_su_errore(self):
        def boom(*a):
            raise RuntimeError("push giu")
        w = wp(vapid_public="pub", firma_vapid=lambda ep: "x", fetch=boom)
        w.registra("g1", SUB)
        self.assertEqual(w.invia("g1", "T", "C"), 0)

    def test_invio_guest_senza_sub(self):
        w = wp(vapid_public="pub", firma_vapid=lambda ep: "x", fetch=lambda *a: 201)
        self.assertEqual(w.invia("g2", "T", "C"), 0)


if __name__ == "__main__":
    unittest.main()
