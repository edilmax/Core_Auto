"""GUARDIA — amplificazione GRATIS: Open Graph sulle pagine annuncio + feed RSS.

Open Graph = quando un link /alloggio/slug e' condiviso (WhatsApp/social/aggregatori) mostra
un'anteprima RICCA (foto+titolo+prezzo) invece di un link nudo. RSS = syndication autonoma.
Entrambi ZERO-chiave, sempre-attivi. Vista ROSSA: senza i tag OG / senza il feed, i test falliscono.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, feed_rss_xml, pagina_alloggio_html


class _Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"h" * 32,
                                              db_payout=self.d + "/p.db"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, o = self.r.gestisci("POST", "/api/host/pubblica", {}, json.dumps({
            "host_id": "h", "slug": "casa-roma", "titolo": "Attico Roma", "citta": "Roma",
            "paese": "IT", "cin": "IT058091C2X5V0ABCD", "descrizione": "Vista Colosseo, terrazza",
            "prezzo_notte_cents": 18000, "capacita": 2, "lat_micro": 41902782,
            "lon_micro": 12496366, "servizi": [], "immagini": []}), {"X-Host-Key": "hk"})
        self.assertIn(s, (200, 201), "setup: publish fallita -> %s" % (o,))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)


class TestOpenGraph(_Base):
    def test_tag_open_graph_presenti(self):
        html = pagina_alloggio_html(self.sis, "casa-roma", "https://bookinvip.com")
        self.assertIsNotNone(html)
        for att in ('property="og:type"', 'property="og:title"', 'property="og:image"',
                    'property="og:url"', 'name="twitter:card" content="summary_large_image"',
                    'property="product:price:amount"'):
            self.assertIn(att, html, "manca il tag Open Graph: %s" % att)
        self.assertIn("Attico Roma", html)
        self.assertIn("/alloggio/casa-roma", html)
        self.assertIn("180.00", html)                       # prezzo nel product:price

    def test_og_image_sempre_presente(self):
        # annuncio SENZA foto -> og:image ripiega su Pollinations (gratis) -> mai anteprima nuda
        html = pagina_alloggio_html(self.sis, "casa-roma", "https://bookinvip.com")
        self.assertRegex(html, r'property="og:image" content="https?://[^"]+"')

    def test_annuncio_inesistente_404(self):
        self.assertIsNone(pagina_alloggio_html(self.sis, "non-esiste", "https://bookinvip.com"))


class TestRSS(_Base):
    def test_feed_valido_con_annuncio(self):
        xml = feed_rss_xml(self.sis, "https://bookinvip.com")
        self.assertTrue(xml.startswith("<?xml"))
        self.assertIn('<rss version="2.0">', xml)
        self.assertIn("<item>", xml)
        self.assertIn("Attico Roma", xml)
        self.assertIn("https://bookinvip.com/alloggio/casa-roma", xml)
        self.assertIn("<enclosure url=", xml)               # immagine nell'item
        self.assertIn("180.00", xml)

    def test_feed_robusto_su_catalogo_vuoto(self):
        # nessun annuncio -> feed VALIDO senza item (mai un crash, mai XML rotto)
        vuoto = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"h" * 32,
                                           db_payout=self.d + "/vuoto.db"))
        xml = feed_rss_xml(vuoto, "https://bookinvip.com")
        self.assertTrue(xml.startswith("<?xml"))
        self.assertIn("<channel>", xml)
        self.assertNotIn("<item>", xml)


if __name__ == "__main__":
    unittest.main(verbosity=2)
