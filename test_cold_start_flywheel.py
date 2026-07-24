"""GUARDIA — COLD-START flywheel: un host pubblica il PRIMO annuncio in una citta -> gli ospiti in
lista d'attesa (fase158) per quella citta ricevono un'email col link + Credito Fondatore. Solo al
primo annuncio (niente re-spam). Vista ROSSA: senza il trigger, la domanda raccolta non viene mai
avvisata (nessuna email)."""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router


class _EmailStub:
    def __init__(self):
        self.inviate = []          # [(email, oggetto, html)]

    def invia(self, dest, oggetto, html):
        self.inviate.append((dest, oggetto, html))
        return True


class TestColdStartFlywheel(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"h" * 32,
                                              db_payout=self.d + "/p.db",
                                              db_domanda=self.d + "/dom.db"))
        self.mail = _EmailStub()
        self.sis.email_provider = self.mail        # inietta un provider email che registra
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _pubblica(self, slug, citta="Milano"):
        return self.g("POST", "/api/host/pubblica", {
            "host_id": "h", "slug": slug, "titolo": "Casa " + slug, "citta": citta,
            "paese": "IT", "cin": "IT058091C2X5V0ABCD", "descrizione": "Bella",
            "prezzo_notte_cents": 12000, "capacita": 2, "lat_micro": 45464203,
            "lon_micro": 9189982, "servizi": [], "immagini": []}, {"X-Host-Key": "hk"})

    def test_lista_attesa_avvisata_al_primo_annuncio(self):
        # un ospite si mette in lista d'attesa per Milano
        s, _ = self.g("POST", "/api/domanda", {"email": "ospite@x.it", "citta": "Milano"})
        self.assertIn(s, (200, 201))
        # l'host pubblica il PRIMO annuncio a Milano
        s, o = self._pubblica("casa-mi-1", "Milano")
        self.assertEqual(s, 201, o)
        # l'ospite in lista ha ricevuto l'email col link + credito
        self.assertEqual(len(self.mail.inviate), 1, "l'ospite in lista d'attesa doveva essere avvisato")
        dest, ogg, html = self.mail.inviate[0]
        self.assertEqual(dest, "ospite@x.it")
        self.assertIn("/alloggio/casa-mi-1", html)         # link all'annuncio
        self.assertIn("credito=", html.lower() + html)     # link col Credito Fondatore
        self.assertIn("Milano", ogg)

    def test_niente_respam_al_secondo_annuncio(self):
        self.g("POST", "/api/domanda", {"email": "ospite@x.it", "citta": "Milano"})
        self._pubblica("casa-mi-1", "Milano")              # 1o -> avvisa (1 email)
        self.mail.inviate.clear()
        self._pubblica("casa-mi-2", "Milano")              # 2o -> NON deve ri-avvisare
        self.assertEqual(self.mail.inviate, [], "il secondo annuncio NON deve ri-spammare la lista")

    def test_citta_senza_lista_nessuna_email(self):
        s, o = self._pubblica("casa-rm-1", "Roma")         # nessuno in lista per Roma
        self.assertEqual(s, 201, o)
        self.assertEqual(self.mail.inviate, [])

    def test_publish_non_si_rompe_senza_email_provider(self):
        self.sis.email_provider = None                     # email spenta -> publish deve funzionare
        self.g("POST", "/api/domanda", {"email": "o@x.it", "citta": "Torino"})
        s, o = self._pubblica("casa-to-1", "Torino")
        self.assertEqual(s, 201, o)                         # nessun crash, pubblica lo stesso


if __name__ == "__main__":
    unittest.main(verbosity=2)
