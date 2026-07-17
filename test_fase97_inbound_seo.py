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
        # <header> dentro il <main>, <footer> dopo con link interno alla home
        self.assertIn("<header>", h)
        self.assertLess(h.index("<main>"), h.index("<header>"))
        self.assertLess(h.index("<header>"), h.index("</main>"))
        self.assertIn("<footer>", h)
        self.assertLess(h.index("</main>"), h.index("<footer>"))
        self.assertIn('<a href="https://bookinvip.com/">BookinVIP</a>', h)

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


class TestRegistroCitta(unittest.TestCase):
    def test_seed_sempre_piu_inventario_dedup_ordinato(self):
        from fase97_inbound_seo import registro_citta, CITTA_SEED, slug_citta
        r = registro_citta(["Porto", "Roma"])          # Roma è già seed, Porto è nuovo
        self.assertIn("Porto", r)
        for c in CITTA_SEED:
            self.assertIn(c, r)                         # seed sempre presente
        self.assertEqual(sum(1 for x in r if slug_citta(x) == "roma"), 1)   # dedup per slug
        self.assertEqual(r, sorted(r, key=slug_citta))  # ordine canonico

    def test_gate_anti_doorway(self):
        from fase97_inbound_seo import registro_citta, citta_da_slug
        r = registro_citta(["Porto"])
        self.assertEqual(citta_da_slug("porto", r), "Porto")    # inventario reale → pagina
        self.assertIsNone(citta_da_slug("citta-fantasma", r))   # fuori dal registro → 404


class TestHreflangRegione(unittest.TestCase):
    def test_parse_locale_bcp47(self):
        from fase97_inbound_seo import _lang_regione
        self.assertEqual(_lang_regione("es-MX"), ("es", "MX"))
        self.assertEqual(_lang_regione("es"), ("es", None))
        self.assertEqual(_lang_regione("es-ZZ"), ("es", None))   # regione fuori mappa → ignorata
        self.assertEqual(_lang_regione("xx"), ("en", None))       # lingua ignota → fallback
        self.assertEqual(_lang_regione(None), ("it", None))

    def test_locali_ordine_e_validi(self):
        from fase97_inbound_seo import locali_hreflang
        loc = locali_hreflang()
        self.assertEqual(len(loc), len(set(loc)))                 # nessun duplicato
        for c in loc:
            self.assertRegex(c, r"^[a-z]{2}(-[A-Z]{2})?$")        # BCP-47
        self.assertIn("es-MX", loc)
        self.assertIn("pt-BR", loc)
        self.assertNotIn("it-IT", loc)                           # it = solo lingua

    def test_pagina_regione_self_canonical_e_locale(self):
        h = genera_landing_host("Roma", lingua="es-MX", base_url="https://bookinvip.com")
        self.assertIn('<html lang="es-MX">', h)
        self.assertIn('rel="canonical" href="https://bookinvip.com/affitta/roma?lang=es-MX"', h)
        self.assertIn('og:locale" content="es_MX"', h)
        self.assertIn("Alquila", h)                              # testo in spagnolo (lingua base)

    def test_hreflang_reciproco_regione(self):
        import re
        def hl(x):
            return dict(re.findall(r'hreflang="([^"]*)" href="([^"]*)"', x))
        a = genera_landing_host("Roma", lingua="es", base_url="https://x")
        b = genera_landing_host("Roma", lingua="es-MX", base_url="https://x")
        self.assertEqual(hl(a), hl(b))                           # stesso set = reciproco
        self.assertIn("x-default", hl(a))


class TestSitemapIndex(unittest.TestCase):
    def test_shard_partiziona_e_scala(self):
        from fase97_inbound_seo import shard_citta, registro_citta, slug_citta
        reg = registro_citta([])                          # solo seed
        # forza più shard per provare la logica di scala (>50k)
        sh = shard_citta(reg, per_shard=40)               # 40/8 lingue = 5 città a shard
        piatto = [c for g in sh for c in g]
        self.assertEqual(sorted(map(slug_citta, piatto)), sorted(map(slug_citta, reg)))  # copre tutto
        self.assertEqual(len(piatto), len(set(map(slug_citta, piatto))))                 # no overlap
        self.assertTrue(all(len(g) <= 5 for g in sh))                                    # sotto tetto
        self.assertEqual(shard_citta([]), [[]])           # edge: vuoto → un gruppo vuoto

    def test_index_referenzia_e_valido(self):
        import xml.dom.minidom as minidom
        from fase97_inbound_seo import sitemap_index
        idx = sitemap_index("https://bookinvip.com",
                            voci=[("/sitemap.xml", ""), ("/sitemap-host-0.xml", "2026-07-17")])
        self.assertIn("<sitemapindex", idx)
        self.assertIn("<loc>https://bookinvip.com/sitemap-host-0.xml</loc>", idx)
        self.assertIn("<lastmod>2026-07-17</lastmod>", idx)
        minidom.parseString(idx)                          # ben formato


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
