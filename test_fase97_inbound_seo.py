"""Test Fase 97 - Inbound SEO/AEO. Funzioni PURE: deterministico, nessun I/O."""
import json
import unittest

from fase97_inbound_seo import (CITTA_SEED, citta_da_slug, faq_jsonld,
                                genera_landing_host, llms_txt, risparmio_notte,
                                sitemap_inbound, slug_citta)


class TestSlug(unittest.TestCase):
    def test_slug_ascii_trattini(self):
        self.assertEqual(slug_citta("Mexico City"), "mexico-city")
        self.assertEqual(slug_citta("São Paulo"), "sao-paulo")
        self.assertEqual(slug_citta(""), "")

    def test_reverse_solo_citta_note(self):
        self.assertEqual(citta_da_slug("roma"), "Roma")
        self.assertEqual(citta_da_slug("new-york"), "New York")
        self.assertIsNone(citta_da_slug("citta-inventata-spam"))  # anti thin-content


class TestRisparmio(unittest.TestCase):
    def test_math_cents_interi(self):
        r = risparmio_notte(10000, 1500, 2500)        # €100, noi 15%, OTA 25%
        self.assertEqual(r["commissione_noi"], 1500)
        self.assertEqual(r["commissione_ota"], 2500)
        self.assertEqual(r["netto_noi"], 8500)
        self.assertEqual(r["netto_ota"], 7500)
        self.assertEqual(r["risparmio"], 1000)         # +€10 a notte

    def test_invarianti_non_negativi(self):
        r = risparmio_notte(-5, -10, 999999)
        self.assertGreaterEqual(r["prezzo"], 0)
        self.assertGreaterEqual(r["netto_noi"], 0)


class TestLanding(unittest.TestCase):
    def test_contiene_seo_essenziale(self):
        h = genera_landing_host("Austin", lingua="en", base_url="https://bookinvip.com")
        self.assertIn("<title>", h)
        self.assertIn("Austin", h)
        self.assertIn('rel="canonical"', h)
        self.assertIn("/affitta/austin", h)
        self.assertIn("/diventa-host.html?ref=seo-austin", h)   # CTA con referral
        self.assertIn("application/ld+json", h)                  # FAQ strutturata

    def test_calcolo_risparmio_in_pagina(self):
        h = genera_landing_host("Roma", lingua="it", commissione_bps=1500, ota_bps=2500,
                                prezzo_demo_cents=10000)
        self.assertIn("85.00", h)        # netto noi
        self.assertIn("75.00", h)        # netto OTA
        self.assertIn("10.00", h)        # risparmio

    def test_xss_safe(self):
        h = genera_landing_host('Roma"><script>alert(1)</script>', lingua="it")
        self.assertNotIn("<script>alert(1)", h)        # escapato
        self.assertIn("&lt;script&gt;", h)

    def test_link_interni_correlati(self):
        h = genera_landing_host("Roma", citta_correlate=["Milano", "Roma", "Napoli"])
        self.assertIn("/affitta/milano", h)
        self.assertIn("/affitta/napoli", h)
        # non si auto-linka nel nav (il canonical href="/affitta/roma" è invece legittimo)
        self.assertNotIn('/affitta/roma">Roma</a>', h)

    def test_tutte_le_lingue(self):
        for lng in ("it", "en", "es", "fr", "de"):
            h = genera_landing_host("Paris", lingua=lng)
            self.assertIn('lang="%s"' % lng, h)
            self.assertIn("<title>", h)


class TestStrutturaSemantica(unittest.TestCase):
    """Guardia landmark HTML5 (SSR + crawler/AEO): il contenuto primario deve essere isolato
    dal boilerplate. UN solo <main>, la navigazione FUORI dal <main>, la FAQ in una <section>
    etichettata. Regressione = pagina di nuovo 'piatta' dentro <body>."""

    def test_main_unico_nav_fuori_faq_in_section(self):
        h = genera_landing_host("Roma", lingua="it", base_url="https://bookinvip.com",
                                citta_correlate=["Milano", "Firenze"])
        self.assertEqual(h.count("<main>"), 1, "deve esserci UN solo <main>")
        self.assertEqual(h.count("</main>"), 1)
        # un solo <h1>, dentro il <main>
        self.assertEqual(h.count("<h1>"), 1)
        self.assertLess(h.index("<main>"), h.index("<h1>"))
        self.assertLess(h.index("<h1>"), h.index("</main>"))
        # FAQ = <section> etichettata dal suo <h2>, dentro il <main>
        self.assertIn('<section aria-labelledby="faq">', h)
        self.assertIn('<h2 id="faq">', h)
        self.assertLess(h.index("<main>"), h.index('<section aria-labelledby="faq">'))
        self.assertLess(h.index('<section aria-labelledby="faq">'), h.index("<details>"))
        self.assertLess(h.index("</section>"), h.index("</main>"))
        # il <nav> 'altre città' sta FUORI (dopo) il </main>: è navigazione, non contenuto
        self.assertIn("<nav", h)
        self.assertLess(h.index("</main>"), h.index("<nav"))

    def test_landmark_reggono_senza_citta_correlate(self):
        # senza correlate niente <nav>, ma <main> e <section> FAQ restano
        h = genera_landing_host("Roma", lingua="it")
        self.assertEqual(h.count("<main>"), 1)
        self.assertNotIn("<nav", h)
        self.assertIn('<section aria-labelledby="faq">', h)


class TestFaqJsonld(unittest.TestCase):
    def test_jsonld_valido_e_faqpage(self):
        raw = (faq_jsonld("it", commissione_bps=1500, ota_bps=2500)
               .replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&"))
        d = json.loads(raw)
        self.assertEqual(d["@type"], "FAQPage")
        self.assertGreaterEqual(len(d["mainEntity"]), 3)
        self.assertEqual(d["mainEntity"][0]["@type"], "Question")

    def test_percentuali_iniettate(self):
        raw = faq_jsonld("en", commissione_bps=1500, ota_bps=2500)
        self.assertIn("15%", raw)
        self.assertIn("25%", raw)


class TestLlmsTxt(unittest.TestCase):
    def test_contenuto_aeo(self):
        t = llms_txt("https://bookinvip.com", commissione_bps=1500)
        self.assertIn("# BookinVIP", t)
        self.assertIn("/api/mcp", t)                    # agent-discoverable
        self.assertIn("/diventa-host.html", t)
        self.assertIn("15%", t)


class TestSitemap(unittest.TestCase):
    def test_sitemap_xml_valido(self):
        xml = sitemap_inbound("https://bookinvip.com", citta=["Roma", "Tokyo"],
                              lingue=["it", "en"])
        self.assertIn("<urlset", xml)
        self.assertIn("/affitta/roma", xml)
        self.assertIn("/affitta/tokyo?lang=en", xml)
        self.assertEqual(xml.count("<url>"), 4)         # 2 città × 2 lingue

    def test_sitemap_lastmod(self):
        # ogni <url> porta il <lastmod> (data template) per il budget di scansione
        from fase97_inbound_seo import SEO_LASTMOD
        xml = sitemap_inbound("https://bookinvip.com", citta=["Roma"], lingue=["it", "en"])
        self.assertEqual(xml.count("<lastmod>"), 2)     # una per url
        self.assertIn("<lastmod>%s</lastmod>" % SEO_LASTMOD, xml)
        # disattivabile passando lastmod="" (retro-compatibilità)
        senza = sitemap_inbound("https://bookinvip.com", citta=["Roma"], lingue=["it"],
                                lastmod="")
        self.assertNotIn("<lastmod>", senza)

    def test_seed_non_vuoto(self):
        self.assertGreater(len(CITTA_SEED), 10)


class TestMaglia(unittest.TestCase):
    def test_deterministica_e_grado(self):
        from fase97_inbound_seo import maglia_link_interni, CITTA_SEED
        m1 = maglia_link_interni(CITTA_SEED, k=6)
        m2 = maglia_link_interni(list(reversed(CITTA_SEED)), k=6)
        self.assertEqual(m1, m2, "ordine input non deve cambiare la maglia (canonica)")
        for c, vic in m1.items():
            self.assertEqual(len(vic), 6)
            self.assertNotIn(c, vic)

    def test_casi_limite(self):
        from fase97_inbound_seo import maglia_link_interni, vicini_di
        self.assertEqual(maglia_link_interni([], k=6), {})
        self.assertEqual(maglia_link_interni(["Roma"], k=6), {"Roma": []})
        due = maglia_link_interni(["Roma", "Milano"], k=6)   # k>n-1 → cap
        self.assertEqual(len(due["Roma"]), 1)
        self.assertEqual(vicini_di("Ignota", ["Roma", "Milano"]), [])


class TestBreadcrumb(unittest.TestCase):
    def test_valido_e_due_livelli(self):
        from fase97_inbound_seo import breadcrumb_jsonld
        raw = (breadcrumb_jsonld("Roma", "https://bookinvip.com", lingua="it")
               .replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&"))
        d = json.loads(raw)
        self.assertEqual(d["@type"], "BreadcrumbList")
        self.assertEqual(len(d["itemListElement"]), 2)
        self.assertEqual(d["itemListElement"][1]["name"], "Roma")

    def test_xss_safe(self):
        from fase97_inbound_seo import breadcrumb_jsonld
        raw = breadcrumb_jsonld('X"><script>alert(1)</script>', "https://x")
        self.assertNotIn("<script>alert(1)", raw)


if __name__ == "__main__":
    unittest.main()
