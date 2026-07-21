"""
Collaudo — recupero prenotazione fallita (errore dei colossi = spam; noi UNA email onesta).
Quando un hold di pagamento scade senza incasso, il cliente riceve un'email "le date sono di
nuovo libere, riprova" con il link all'alloggio. Best-effort: senza email/provider -> silenzio.
"""
import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase57_vetrina import SchedaAlloggio


class _FakeEmail:
    def __init__(self):
        self.inviate = []

    def invia(self, dest, ogg, html):
        self.inviate.append((dest, ogg, html))
        return True


class TestRecuperoHold(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32,
            db_catalogo=f"{self.d}/c.db", db_inventario=f"{self.d}/i.db"))
        self.sys.email_provider = _FakeEmail()
        self.r = crea_router(self.sys, base_url="https://bookinvip.com")
        self.sys.catalogo.pubblica(SchedaAlloggio(
            host_id="h1", slug="casa", titolo="Casa Bella", citta="Roma",
            prezzo_notte_cents=10000, capacita=2))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _attendi_email(self, n=1, timeout=3.0):
        t0 = time.time()
        while len(self.sys.email_provider.inviate) < n and time.time() - t0 < timeout:
            time.sleep(0.05)
        return self.sys.email_provider.inviate

    def test_email_di_recupero(self):
        rec = {"riferimento": "r1", "alloggio_id": "casa", "email": "cli@x.it",
               "check_in": "2026-09-01", "check_out": "2026-09-03"}
        self.r._email_recupero_hold(rec)
        inv = self._attendi_email(1)
        self.assertEqual(len(inv), 1)
        dest, ogg, html = inv[0]
        self.assertEqual(dest, "cli@x.it")
        self.assertIn("di nuovo libere", ogg)
        self.assertIn("Casa Bella", html)                        # titolo vero
        self.assertIn("/alloggio/casa", html)                    # link per riprovare
        self.assertIn("Nessun addebito", html)                   # onestà

    def test_senza_email_o_provider_silenzio(self):
        # "silenzio" significa che NON parte nessuna email, non che il codice non
        # esplode: prima si chiamava e basta, e il test non poteva fallire.
        partite_prima = len(getattr(self.sys.email_provider, "inviate", []) or [])
        self.r._email_recupero_hold({"riferimento": "r2", "alloggio_id": "casa",
                                     "email": "", "check_in": "x", "check_out": "y"})
        self.r._email_recupero_hold(None)
        partite_dopo = len(getattr(self.sys.email_provider, "inviate", []) or [])
        self.assertEqual(partite_dopo, partite_prima,
                         "senza indirizzo e' partita un'email lo stesso")
        self.sys.email_provider = None
        self.r._email_recupero_hold({"riferimento": "r3", "alloggio_id": "casa",
                                     "email": "a@b.it"})
        self.assertIsNone(self.sys.email_provider,
                          "senza provider il giro deve restare in silenzio, non ricrearlo")
        time.sleep(0.1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
