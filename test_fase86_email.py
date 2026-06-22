"""
Test Fase 86 - Provider Email.

Copre: invio (con send STUB, niente SMTP reale), destinatario invalido -> False, send che
solleva -> False (isolato), factory gated (no host -> None), corpo voucher HTML (link +
XSS-safe).
"""
import unittest

from fase86_email import ProviderEmail, corpo_voucher_html, crea_provider_email


class SendSpy:
    def __init__(self, ritorna=True, solleva=False):
        self.chiamate = []
        self._r = ritorna
        self._solleva = solleva

    def __call__(self, dest, oggetto, html):
        if self._solleva:
            raise RuntimeError("smtp giu'")
        self.chiamate.append((dest, oggetto, html))
        return self._r


class TestInvio(unittest.TestCase):
    def test_invio_ok(self):
        spy = SendSpy()
        p = ProviderEmail("smtp.x", 587, "u", "pw", "no-reply@bookinvip.com", send=spy)
        self.assertTrue(p.invia("g@x.it", "Conferma", "<p>ciao</p>"))
        self.assertEqual(spy.chiamate[0][0], "g@x.it")
        self.assertEqual(spy.chiamate[0][1], "Conferma")

    def test_destinatario_invalido(self):
        p = ProviderEmail("smtp.x", 587, "u", "pw", "m@x.it", send=SendSpy())
        self.assertFalse(p.invia("non-email", "x", "y"))
        self.assertFalse(p.invia(None, "x", "y"))

    def test_send_solleva_isolato(self):
        p = ProviderEmail("smtp.x", 587, "u", "pw", "m@x.it", send=SendSpy(solleva=True))
        self.assertFalse(p.invia("g@x.it", "x", "y"))      # False, non crash


class TestFactory(unittest.TestCase):
    def test_gated(self):
        self.assertIsNone(crea_provider_email(None))
        self.assertIsNone(crea_provider_email(""))
        self.assertIsNotNone(crea_provider_email("smtp.x", 587, "u", "pw", "m@x.it",
                                                 send=SendSpy()))


class TestCorpo(unittest.TestCase):
    def test_html_con_link(self):
        h = corpo_voucher_html("Casa Roma", "ABC123", "2026-09-01", "2026-09-02",
                               "https://bookinvip.com/voucher/tok")
        self.assertIn("Prenotazione confermata", h)
        self.assertIn("ABC123", h)
        self.assertIn("https://bookinvip.com/voucher/tok", h)

    def test_xss_safe(self):
        h = corpo_voucher_html("<script>x</script>", "r", "a", "b", "")
        self.assertNotIn("<script>x</script>", h)
        self.assertIn("&lt;script&gt;", h)


if __name__ == "__main__":
    unittest.main()
