"""
Test Fase 90 - Marketing & Growth Engine 360°. Tutto deterministico, ZERO rete.
"""
import unittest

from fase90_marketing import (
    CanaleStub, GeneratoreContenuti, MotoreMarketing, Post, calendario_editoriale,
    crea_motore_marketing, genera_card_svg,
)


class TestCardSVG(unittest.TestCase):
    def test_svg_valido(self):
        svg = genera_card_svg("Tieni di più.", "commissione bassa")
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("BookinVIP", svg)
        self.assertIn("1080", svg)

    def test_xss_safe(self):
        svg = genera_card_svg("<script>x</script>", "")
        self.assertNotIn("<script>x</script>", svg)
        self.assertIn("&lt;script&gt;", svg)


class TestGeneratore(unittest.TestCase):
    def setUp(self):
        self.g = GeneratoreContenuti("https://bookinvip.com")

    def test_post_host_it(self):
        p = self.g.crea("host", "it")
        self.assertEqual(p.lingua, "it")
        self.assertIn("BookinVIP", p.testo)
        self.assertIn("/diventa-host.html", p.link)
        self.assertIn("#bookinvip", p.hashtag)
        self.assertTrue(p.immagine_svg.startswith("<svg"))

    def test_lingue_e_temi(self):
        self.assertEqual(self.g.crea("guest", "en").lingua, "en")
        self.assertEqual(self.g.crea("host", "xx").lingua, "it")     # lingua ignota -> it
        self.assertIsNone(self.g.crea("inesistente", "it"))

    def test_campagna_completa(self):
        post = self.g.campagna_completa(("it", "en"))
        self.assertEqual(len(post), 6)                               # 3 temi x 2 lingue


class TestCalendario(unittest.TestCase):
    def test_pianifica_deterministico(self):
        g = GeneratoreContenuti()
        post = g.campagna_completa(("it",))                         # 3 post
        piano = calendario_editoriale(post, ["telegram", "instagram"],
                                      partenza="2026-03-01")
        self.assertEqual(len(piano), 3)
        self.assertEqual(piano[0]["canale"], "telegram")
        self.assertEqual(piano[1]["canale"], "instagram")
        self.assertEqual(piano[0]["data"], "2026-03-01")


class TestMotore(unittest.TestCase):
    def test_pubblica_piano(self):
        g = GeneratoreContenuti()
        tg, ig = CanaleStub(), CanaleStub()
        m = MotoreMarketing(g, {"telegram": tg, "instagram": ig})
        piano = calendario_editoriale(g.campagna_completa(("it", "en")),
                                      ["telegram", "instagram"])
        rep = m.pubblica_piano(piano)
        self.assertEqual(rep["pubblicati"], 6)
        self.assertEqual(len(tg.pubblicati) + len(ig.pubblicati), 6)

    def test_canale_mancante_saltato(self):
        g = GeneratoreContenuti()
        m = MotoreMarketing(g, {"telegram": CanaleStub()})
        piano = calendario_editoriale([g.crea("host", "it")], ["instagram"])
        rep = m.pubblica_piano(piano)
        self.assertEqual(rep["pubblicati"], 0)
        self.assertEqual(rep["saltati"], 1)

    def test_email_campagna_gated(self):
        inviate = []
        class FakeEmail:
            def invia(self, d, o, c):
                inviate.append(d); return True
        m = crea_motore_marketing(email_provider=FakeEmail())
        post = m._gen.crea("host", "it")
        n = m.invia_email_campagna(["a@b.it", "c@d.it"], "Offerta", post)
        self.assertEqual(n, 2)
        # senza provider -> 0
        m2 = crea_motore_marketing()
        self.assertEqual(m2.invia_email_campagna(["a@b.it"], "x", post), 0)


if __name__ == "__main__":
    unittest.main()
