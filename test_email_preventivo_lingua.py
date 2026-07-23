"""
L'email di RECUPERO PREVENTIVO (`/api/preventivo/email`) deve partire nella lingua
dell'ospite fra tutte e 8, non piu' it/en binario. ROSSO sul vecchio: prima un ospite
spagnolo/giapponese riceveva ETICHETTE righe e OGGETTO in inglese anche se il corpo del
template era gia' tradotto (il chiamante `_preventivo_email` collassava la lingua a it/en).
Ripiego INGLESE per lingua ignota, MAI italiano.
"""
import datetime
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router


class Finta:
    def __init__(self):
        self.inviate = []

    def invia(self, dest, oggetto, html):
        self.inviate.append((dest, oggetto, html))
        return True


class TestPreventivoEmailLingua(unittest.TestCase):
    HK = {"X-Host-Key": "hk"}

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db"))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")
        oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"host_id": "demo", "slug": "casa", "titolo": "Villa Sole", "citta": "Roma",
                "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
                "servizi": [], "immagini": [], "politica_cancellazione": "flessibile"}, self.HK)
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": oggi.isoformat(),
                "a": (oggi + datetime.timedelta(days=30)).isoformat(),
                "unita_totali": 1, "prezzo_netto_cents": 10000}, self.HK)
        self.ci = (oggi + datetime.timedelta(days=5)).isoformat()
        self.co = (oggi + datetime.timedelta(days=7)).isoformat()
        self.posta = Finta()
        self.sis.email_provider = self.posta

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _invia(self, lang, email):
        # email diversa per test: il throttle e' su (email, alloggio, date)
        s, c = self.g("POST", "/api/preventivo/email",
                      {"alloggio_id": "casa", "check_in": self.ci, "check_out": self.co,
                       "party": 2, "email": email, "lang": lang})
        self.assertEqual(s, 200, c)
        self.assertTrue(self.posta.inviate, "nessuna email catturata")
        return self.posta.inviate[-1]   # (dest, oggetto, html)

    def test_spagnolo(self):
        _, ogg, html = self._invia("es", "es@x.it")
        self.assertIn("presupuesto", ogg.lower())   # OGGETTO in spagnolo
        self.assertIn("Estancia", html)             # etichetta riga in spagnolo
        self.assertIn("Total", html)

    def test_giapponese(self):
        _, ogg, html = self._invia("ja", "ja@x.it")
        self.assertIn("お見積り", ogg)
        self.assertIn("滞在", html)

    def test_tedesco(self):
        _, ogg, html = self._invia("de", "de@x.it")
        self.assertIn("Angebot", ogg)
        self.assertIn("Gesamt", html)               # 'Totale' -> 'Gesamt'

    def test_ripiego_EN_mai_italiano(self):
        _, ogg, html = self._invia("xx", "xx@x.it")   # lingua ignota
        self.assertIn("quote", ogg.lower())
        self.assertIn("Stay", html)
        self.assertNotIn("Soggiorno", html)


if __name__ == "__main__":
    unittest.main()
