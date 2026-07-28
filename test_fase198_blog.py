"""GUARDIA — BLOG multilingua (fase198): ogni articolo × lingua è una pagina SEO tecnicamente
irreprensibile (un solo <h1>, canonical self-referente assoluto, hreflang completo+reciproco,
JSON-LD Article+BreadcrumbList validi, link interni, XSS-safe), indice e sitemap coerenti.

Vista ROSSA: se manca l'h1/canonical/hreflang, se il JSON-LD non è valido, se lo slug ignoto non
desse 404, o se la sitemap non coprisse ogni pagina, i test falliscono.
"""
import json
import re
import unittest
import xml.dom.minidom as minidom

from fase198_blog import (ARTICOLI, BLOG_LINGUE, genera_articolo_html, genera_indice_blog,
                          sitemap_blog, url_blog)

BASE = "https://bookinvip.com"


def _hreflang(h):
    return dict(re.findall(r'<link rel="alternate" hreflang="([^"]*)" href="([^"]*)"', h))


def _jsonld_blocchi(h):
    fuori = []
    for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S):
        testo = raw.replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&")
        fuori.append(json.loads(testo))                # solleva se non valido → rosso
    return fuori


class TestArticoli(unittest.TestCase):
    def test_ogni_articolo_ogni_lingua_invarianti(self):
        for a in ARTICOLI:
            slug = a["slug"]
            for lng in BLOG_LINGUE:
                h = genera_articolo_html(slug, lingua=lng, base_url=BASE)
                ctx = "%s/%s" % (slug, lng)
                self.assertIsNotNone(h, ctx)
                self.assertEqual(h.count("<h1>"), 1, "h1 non unico: %s" % ctx)
                self.assertEqual(h.count("<main>"), 1, "main non unico: %s" % ctx)
                self.assertIn('<html lang="%s">' % lng, h, ctx)
                self.assertIn('name="viewport"', h, ctx)
                self.assertIn('charset="utf-8"', h, ctx)
                # title
                titolo = h[h.find("<title>") + 7:h.find("</title>")]
                self.assertTrue(10 <= len(titolo) <= 120, "title fuori scala (%d): %s"
                                % (len(titolo), ctx))
                # description
                self.assertRegex(h, r'<meta name="description" content="[^"]{30,}">',
                                 "description assente/corta: %s" % ctx)
                # canonical assoluto + self-referente
                can = re.search(r'<link rel="canonical" href="([^"]*)"', h).group(1)
                atteso = BASE + "/blog/" + slug + ("" if lng == "it" else "?lang=" + lng)
                self.assertEqual(can, atteso, "canonical non self-referente: %s" % ctx)
                # hreflang completo + x-default
                hl = _hreflang(h)
                for L in BLOG_LINGUE:
                    self.assertIn(L, hl, "hreflang %s mancante: %s" % (L, ctx))
                self.assertIn("x-default", hl, ctx)
                # JSON-LD Article + BreadcrumbList validi
                tipi = {b.get("@type") for b in _jsonld_blocchi(h)}
                self.assertIn("Article", tipi, "Article JSON-LD assente: %s" % ctx)
                self.assertIn("BreadcrumbList", tipi, "Breadcrumb assente: %s" % ctx)
                # link interno alla conversione
                self.assertIn("/diventa-host.html", h, "manca CTA diventa-host: %s" % ctx)
                # XSS-safe
                self.assertNotIn("<script>alert", h)

    def test_hreflang_reciproco_uniforme(self):
        for a in ("prenotazioni-dirette",):
            insiemi = [frozenset(_hreflang(genera_articolo_html(a, lingua=L, base_url=BASE)).items())
                       for L in BLOG_LINGUE]
            self.assertEqual(len(set(insiemi)), 1, "hreflang non uniforme per %s" % a)

    def test_slug_ignoto_none(self):
        self.assertIsNone(genera_articolo_html("non-esiste-xyz", base_url=BASE))

    def test_deterministico(self):
        a = genera_articolo_html("check-in-automatico", lingua="en", base_url=BASE)
        b = genera_articolo_html("check-in-automatico", lingua="en", base_url=BASE)
        self.assertEqual(a, b)

    def test_lingua_ignota_ripiega_INGLESE(self):
        """Ripiegava sull'ITALIANO: chi arrivava col russo (servito dalle landing di
        fase97 ma non dal blog) o con un codice qualsiasi leggeva italiano. Su un blog
        che esiste per portare traffico dal mondo, il ripiego e' l'inglese."""
        for ignota in ("xx", "sw", "ru", "", None, 42):
            h = genera_articolo_html("prenotazioni-dirette", lingua=ignota, base_url=BASE)
            self.assertIn('<html lang="en">', h, "lingua %r -> non inglese" % ignota)
            self.assertEqual(h, genera_articolo_html("prenotazioni-dirette",
                                                     lingua="en", base_url=BASE))

    def test_corpo_presente(self):
        # il testo dei paragrafi dev'essere davvero nella pagina (non solo il titolo)
        h = genera_articolo_html("prenotazioni-dirette", lingua="it", base_url=BASE)
        self.assertIn("passaparola", h)
        self.assertGreaterEqual(h.count("<p>"), 3, "corpo articolo troppo scarno")


class TestIndice(unittest.TestCase):
    def test_indice_elenca_tutti(self):
        for lng in BLOG_LINGUE:
            h = genera_indice_blog(lingua=lng, base_url=BASE)
            self.assertEqual(h.count("<h1>"), 1)
            self.assertIn('<html lang="%s">' % lng, h)
            for a in ARTICOLI:
                self.assertIn("/blog/" + str(a["slug"]), h,
                              "indice non linka %s (%s)" % (a["slug"], lng))
            can = re.search(r'<link rel="canonical" href="([^"]*)"', h).group(1)
            self.assertEqual(can, BASE + "/blog" + ("" if lng == "it" else "?lang=" + lng))


class TestSitemapBlog(unittest.TestCase):
    def test_sitemap_copre_tutto_e_ben_formata(self):
        xml = sitemap_blog(BASE)
        minidom.parseString(xml)                       # ben formata o solleva
        for lng in BLOG_LINGUE:
            self.assertIn("<loc>%s</loc>" % (BASE + "/blog" + ("" if lng == "it" else "?lang=" + lng)),
                          xml, "sitemap non copre l'indice %s" % lng)
            for a in ARTICOLI:
                url = BASE + "/blog/" + str(a["slug"]) + ("" if lng == "it" else "?lang=" + lng)
                self.assertIn("<loc>%s</loc>" % url, xml, "sitemap non copre %s/%s" % (a["slug"], lng))
        attesi = len(BLOG_LINGUE) * (1 + len(ARTICOLI))
        self.assertEqual(xml.count("<lastmod>"), attesi)
        self.assertEqual(len(url_blog(BASE)), attesi)


if __name__ == "__main__":
    unittest.main(verbosity=2)
