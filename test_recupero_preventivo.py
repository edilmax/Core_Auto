"""
Collaudo RECUPERO PREVENTIVO onesto — l'ospite CHIEDE la sua quote via email
(bottone sotto il preventivo): UNA email transazionale col riepilogo e il link
per completare. Niente tracking, niente archivio marketing, niente promemoria.

Blindato qui: ricalcolo lato server (mai fidarsi del client); date non più
disponibili -> 422 e NIENTE email; throttle 10 minuti per (email, alloggio,
date); provider spento -> 503; invio fallito -> 502 onesto; XSS-safe; valute
a esponente 0 (JPY) formattate giuste; link con slug+date.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE


class SpyEmail:
    def __init__(self, esito=True):
        self.inviate = []
        self._esito = esito

    def invia(self, dest, oggetto, html):
        self.inviate.append((dest, oggetto, html))
        return self._esito


class TestRecuperoPreventivo(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/a.db"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@prev.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        self.spy = SpyEmail()
        self.sys.email_provider = self.spy

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, metodo, path, body=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None, headers or {})

    def _pubblica(self, slug="casa-prev", titolo="Casa Preventivo", valuta="EUR",
                  prezzo=9000):
        s, r = self.g("POST", "/api/host/pubblica",
                      {"slug": slug, "titolo": titolo, "citta": "Roma", "valuta": valuta,
                       "prezzo_notte_cents": prezzo, "capacita": 2},
                      {"X-Host-Token": self.tok})
        self.assertEqual(s, 201, r)
        for gio in ("2026-09-01", "2026-09-02"):
            self.g("POST", "/api/host/disponibilita",
                   {"alloggio_id": slug, "giorno": gio, "unita_totali": 1,
                    "prezzo_netto_cents": prezzo}, {"X-Host-Token": self.tok})

    def _chiedi(self, email="ospite@x.it", slug="casa-prev", lang="it",
                ci="2026-09-01", co="2026-09-02"):
        return self.g("POST", "/api/preventivo/email",
                      {"alloggio_id": slug, "check_in": ci, "check_out": co,
                       "party": 2, "email": email, "lang": lang})

    def test_invio_ok_contenuto_e_link(self):
        self._pubblica()
        s, r = self._chiedi()
        self.assertEqual(s, 200, r)
        self.assertEqual(r["stato"], "inviata")
        self.assertEqual(len(self.spy.inviate), 1)
        dest, ogg, html = self.spy.inviate[0]
        self.assertEqual(dest, "ospite@x.it")
        self.assertIn("Casa Preventivo", ogg)
        self.assertIn("Casa Preventivo", html)
        self.assertIn("apri=casa-prev", html)
        self.assertIn("ci=2026-09-01", html)
        self.assertIn("EUR", html)
        self.assertIn("preventivo", html.lower())

    def test_ricalcolo_server_non_si_fida_del_client(self):
        # il client NON manda prezzi: l'email contiene il prezzo VERO del listino
        self._pubblica(prezzo=12345)
        s, r = self._chiedi()
        self.assertEqual(s, 200, r)
        html = self.spy.inviate[0][2]
        self.assertIn("123.45", html, "prezzo ricalcolato dal server, al centesimo")

    def test_valuta_esponente_zero(self):
        self._pubblica(slug="casa-jpy", titolo="Casa JPY", valuta="JPY", prezzo=9000)
        s, r = self._chiedi(slug="casa-jpy")
        self.assertEqual(s, 200, r)
        html = self.spy.inviate[0][2]
        self.assertIn("9000 JPY", html, "JPY ha esponente 0: niente decimali inventati")
        self.assertNotIn("90.00 JPY", html)

    def test_date_non_disponibili_niente_email(self):
        self._pubblica()
        s, r = self._chiedi(ci="2027-01-01", co="2027-01-02")   # nessuna disponibilità
        self.assertEqual(s, 422, r)
        self.assertEqual(r["errore"], "non_disponibile")
        self.assertEqual(len(self.spy.inviate), 0, "date impossibili -> NIENTE email")

    def test_email_invalida_e_campi_mancanti(self):
        self._pubblica()
        s, r = self._chiedi(email="non-email")
        self.assertEqual(s, 422)
        s, r = self.g("POST", "/api/preventivo/email",
                      {"email": "a@b.it", "check_in": "2026-09-01"})
        self.assertEqual(s, 422)
        self.assertEqual(len(self.spy.inviate), 0)

    def test_throttle_10_minuti(self):
        self._pubblica()
        s, _ = self._chiedi()
        self.assertEqual(s, 200)
        s, r = self._chiedi()                          # stessa richiesta subito dopo
        self.assertEqual(s, 429, r)
        self.assertEqual(len(self.spy.inviate), 1, "un solo invio, niente spam")
        # email DIVERSA -> passa (throttle per email+alloggio+date, non globale)
        s, _ = self._chiedi(email="altro@x.it")
        self.assertEqual(s, 200)

    def test_provider_spento_503(self):
        self._pubblica()
        self.sys.email_provider = None
        s, r = self._chiedi()
        self.assertEqual(s, 503, r)

    def test_invio_fallito_502_onesto(self):
        self._pubblica()
        self.sys.email_provider = SpyEmail(esito=False)
        s, r = self._chiedi()
        self.assertEqual(s, 502, r)
        # il fallimento NON brucia il throttle: si può riprovare subito
        self.sys.email_provider = self.spy
        s, r = self._chiedi()
        self.assertEqual(s, 200, r)

    def test_xss_safe(self):
        self._pubblica(slug="casa-xss", titolo="Casa <script>alert(1)</script>")
        s, r = self._chiedi(slug="casa-xss")
        self.assertEqual(s, 200, r)
        html = self.spy.inviate[0][2]
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_lingua_inglese(self):
        self._pubblica()
        s, r = self._chiedi(lang="en")
        self.assertEqual(s, 200, r)
        _, ogg, html = self.spy.inviate[0]
        self.assertIn("Your quote", ogg)
        self.assertIn("Complete your booking", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
