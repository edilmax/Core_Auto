"""
Test Fase 86 - Provider Email.

Copre: invio (con send STUB, niente SMTP reale), destinatario invalido -> False, send che
solleva -> False (isolato), factory gated (no host -> None), corpo voucher HTML (link +
XSS-safe).
"""
import unittest

from fase86_email import ProviderEmail, corpo_voucher_html, crea_provider_email


class SendSpy:
    def __init__(self, ritorna=True, solleva=False, solleva_prime=0):
        """`solleva_prime=N`: le prime N chiamate sollevano (singhiozzo transitorio),
        poi funziona. `solleva=True`: solleva SEMPRE (SMTP giu' del tutto)."""
        self.chiamate = []
        self.tentativi = 0
        self._r = ritorna
        self._solleva = solleva
        self._solleva_prime = solleva_prime

    def __call__(self, dest, oggetto, html):
        self.tentativi += 1
        if self._solleva or self.tentativi <= self._solleva_prime:
            raise RuntimeError("smtp giu'")
        self.chiamate.append((dest, oggetto, html))
        return self._r


class SleepSpy:
    def __init__(self):
        self.pause = []

    def __call__(self, secondi):
        self.pause.append(secondi)


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
        spy, dormi = SendSpy(solleva=True), SleepSpy()
        p = ProviderEmail("smtp.x", 587, "u", "pw", "m@x.it", send=spy, sleep=dormi)
        self.assertFalse(p.invia("g@x.it", "x", "y"))      # False, non crash
        self.assertEqual(spy.tentativi, 2)                 # ha ritentato una volta
        self.assertEqual(len(dormi.pause), 1)              # una sola pausa tra i due

    def test_retry_su_singhiozzo_transitorio(self):
        # Il caso VERO visto in prod (2026-07-15): SMTP chiude la connessione una volta,
        # al secondo tentativo (connessione fresca) va -> l'email NON e' persa.
        spy, dormi = SendSpy(solleva_prime=1), SleepSpy()
        p = ProviderEmail("smtp.x", 587, "u", "pw", "m@x.it", send=spy, sleep=dormi)
        self.assertTrue(p.invia("g@x.it", "Conferma", "<p>ok</p>"))
        self.assertEqual(spy.tentativi, 2)
        self.assertEqual(dormi.pause, [1.5])
        self.assertEqual(spy.chiamate[0][0], "g@x.it")     # consegnata al 2o giro

    def test_no_retry_su_false_pulito(self):
        # Il provider risponde 'no' senza eccezione -> NIENTE retry (ha gia' deciso).
        spy, dormi = SendSpy(ritorna=False), SleepSpy()
        p = ProviderEmail("smtp.x", 587, "u", "pw", "m@x.it", send=spy, sleep=dormi)
        self.assertFalse(p.invia("g@x.it", "x", "y"))
        self.assertEqual(spy.tentativi, 1)
        self.assertEqual(dormi.pause, [])

    def test_invia_non_solleva_mai_neanche_con_sleep_rotto(self):
        # Perfino uno sleep che solleva non deve far uscire eccezioni da `invia`.
        def sleep_rotto(_s):
            raise RuntimeError("clock rotto")
        p = ProviderEmail("smtp.x", 587, "u", "pw", "m@x.it",
                          send=SendSpy(solleva=True), sleep=sleep_rotto)
        try:
            esito = p.invia("g@x.it", "x", "y")
        except Exception as exc:  # pragma: no cover
            self.fail("invia ha sollevato: %r" % exc)
        self.assertFalse(esito)


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
