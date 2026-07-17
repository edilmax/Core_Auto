"""
SANDBOX SEO — simulazione di CRAWL su TUTTA la superficie inbound (fase97/83), con verifica di
una batteria di INVARIANTI tecnici Google-policy che nessun singolo test copriva finora.

Filosofia: non "spammare" per salire (black-hat, penalizzato) ma rendere il sito TECNICAMENTE
IRREPRENSIBILE e a prova di penalizzazione. Un crawler simulato genera ogni landing (città ×
lingua), ricostruisce il grafo dei link interni e controlla:

  GRAFO (maglia small-world):  nessun self-loop · grado costante k · anello hamiltoniano →
    fortemente connesso · nessun orfano (in-degree ≥ 1) · diametro piccolo (small-world, non
    l'anello n-1) · ogni link punta a una città reale (no dangling).
  PAGINA (ogni città × lingua):  un solo <h1> · <main> unico · <html lang> corretto · viewport
    (mobile-first) · charset · <title> non vuoto e ragionevole · meta description presente ·
    canonical ASSOLUTO e SELF-REFERENTE · hreflang completo (tutte le lingue + x-default) e
    RECIPROCO · JSON-LD FAQPage E BreadcrumbList validi (rich-result eligibility) · link interni
    RILEVANTI e LIMITATI a k (non link-farm) · niente breakout XSS.
  UNICITÀ:  title e description UNICI per lingua (niente duplicati = niente diluizione).
  DETERMINISMO / NO-CLOAKING:  stesso input → stesso output (idempotente).
  COPERTURA:  la sitemap-host contiene OGNI landing (sitemap ⊇ pagine crawlabili); robots
    permette la scansione e dichiara le sitemap; sitemap XML ben formate con <lastmod>.
"""
import json
import re
import types
import unittest
import xml.dom.minidom as minidom

from fase97_inbound_seo import (CITTA_SEED, LINGUE, breadcrumb_jsonld, genera_landing_host,
                                maglia_link_interni, sitemap_inbound, slug_citta, vicini_di)
from fase83_server import robots_txt, sitemap_xml

BASE = "https://bookinvip.com"
K = 6


# ── estrattori (un "parser" da crawler) ─────────────────────────────────────────
def _fra(h, apri, chiudi):
    i = h.find(apri)
    if i < 0:
        return ""
    j = h.find(chiudi, i + len(apri))
    return h[i + len(apri):j] if j >= 0 else ""

def _title(h):
    return _fra(h, "<title>", "</title>")

def _meta(h, nome):
    m = re.search(r'<meta name="%s" content="([^"]*)"' % re.escape(nome), h)
    return m.group(1) if m else None

def _canonical(h):
    m = re.search(r'<link rel="canonical" href="([^"]*)"', h)
    return m.group(1) if m else None

def _hreflang(h):
    return dict(re.findall(r'<link rel="alternate" hreflang="([^"]*)" href="([^"]*)"', h))

def _jsonld_blocchi(h):
    fuori = []
    for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S):
        testo = raw.replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&")
        fuori.append(json.loads(testo))            # solleva se non valido → test rosso
    return fuori

def _nav_slugs(h):
    nav = _fra(h, "<nav", "</nav>")
    return re.findall(r'/affitta/([a-z0-9-]+)"', nav)


class TestSEOSandbox(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mesh = maglia_link_interni(CITTA_SEED, k=K)
        cls.nomi = sorted({c for c in CITTA_SEED}, key=slug_citta)
        cls.slug_noti = {slug_citta(c) for c in CITTA_SEED}

    # ---- GRAFO ---------------------------------------------------------------
    def test_grafo_niente_selfloop_e_grado_k(self):
        n = len(self.nomi)
        for c, vic in self.mesh.items():
            self.assertNotIn(c, vic, "self-loop su %s" % c)
            self.assertEqual(len(vic), min(K, n - 1), "grado != k su %s" % c)
            self.assertEqual(len(set(vic)), len(vic), "vicini duplicati su %s" % c)
            for v in vic:
                self.assertIn(slug_citta(v), self.slug_noti, "link a città ignota: %s" % v)

    def test_grafo_anello_hamiltoniano(self):
        # i→(i+1) presente per ogni i → ciclo che copre tutti → fortemente connesso
        n = len(self.nomi)
        for i, c in enumerate(self.nomi):
            succ = self.nomi[(i + 1) % n]
            self.assertIn(succ, self.mesh[c], "anello rotto: %s non linka %s" % (c, succ))

    def test_grafo_fortemente_connesso_e_nessun_orfano(self):
        idx = {c: i for i, c in enumerate(self.nomi)}
        adj = {i: [idx[v] for v in self.mesh[c]] for i, c in enumerate(self.nomi)}
        n = len(self.nomi)

        def raggiunti(start, grafo):
            visti, pila = {start}, [start]
            while pila:
                x = pila.pop()
                for y in grafo[x]:
                    if y not in visti:
                        visti.add(y)
                        pila.append(y)
            return visti

        rev = {i: [] for i in range(n)}
        for a in adj:
            for b in adj[a]:
                rev[b].append(a)
        self.assertEqual(len(raggiunti(0, adj)), n, "non fortemente connesso (forward)")
        self.assertEqual(len(raggiunti(0, rev)), n, "non fortemente connesso (reverse)")
        for i in range(n):                          # nessun orfano: in-degree ≥ 1
            self.assertGreaterEqual(len(rev[i]), 1, "orfano: %s" % self.nomi[i])

    def test_grafo_diametro_piccolo_small_world(self):
        idx = {c: i for i, c in enumerate(self.nomi)}
        adj = {i: [idx[v] for v in self.mesh[c]] for i, c in enumerate(self.nomi)}
        n = len(self.nomi)

        def ecc(start):
            dist = {start: 0}
            coda = [start]
            while coda:
                x = coda.pop(0)
                for y in adj[x]:
                    if y not in dist:
                        dist[y] = dist[x] + 1
                        coda.append(y)
            return max(dist.values()) if len(dist) == n else 10 ** 9

        diam = max(ecc(i) for i in range(n))
        # anello puro avrebbe diametro n-1 (=27); small-world deve essere ≪ (prova la topologia)
        self.assertLessEqual(diam, 8, "diametro %d troppo grande (small-world fallito)" % diam)

    def test_vicini_di_coerente_con_maglia(self):
        for c in CITTA_SEED:
            self.assertEqual(vicini_di(c, CITTA_SEED, k=K), self.mesh[c])
        self.assertEqual(vicini_di("Città-Inventata", CITTA_SEED, k=K), [])

    # ---- PAGINA (ogni città × lingua) ---------------------------------------
    def test_ogni_landing_invarianti(self):
        for c in CITTA_SEED:
            for lng in LINGUE:
                h = genera_landing_host(c, lingua=lng, base_url=BASE, commissione_bps=1500,
                                        citta_correlate=vicini_di(c, CITTA_SEED, k=K))
                ctx = "%s/%s" % (c, lng)
                self.assertEqual(h.count("<h1>"), 1, "h1 non unico: %s" % ctx)
                self.assertEqual(h.count("<main>"), 1, "main non unico: %s" % ctx)
                self.assertIn('<html lang="%s">' % lng, h, ctx)
                self.assertIn('name="viewport"', h, "viewport mancante: %s" % ctx)
                self.assertIn('charset="utf-8"', h, ctx)
                titolo = _title(h)
                self.assertTrue(10 <= len(titolo) <= 100, "title fuori scala (%d): %s"
                                % (len(titolo), ctx))
                desc = _meta(h, "description")
                self.assertIsNotNone(desc, "description mancante: %s" % ctx)
                self.assertGreaterEqual(len(desc), 50, "description troppo corta: %s" % ctx)
                # canonical assoluto + self-referente
                can = _canonical(h)
                self.assertTrue(can and can.startswith("https://"), "canonical non assoluto: %s" % ctx)
                atteso = BASE + "/affitta/" + slug_citta(c) + ("" if lng == "it" else "?lang=" + lng)
                self.assertEqual(can, atteso, "canonical non self-referente: %s" % ctx)
                # hreflang completo + x-default
                hl = _hreflang(h)
                for L in LINGUE:
                    self.assertIn(L, hl, "hreflang %s mancante: %s" % (L, ctx))
                self.assertIn("x-default", hl, "x-default mancante: %s" % ctx)
                # link interni: rilevanti (città note) e limitati a k
                navs = _nav_slugs(h)
                self.assertEqual(len(navs), min(K, len(CITTA_SEED) - 1),
                                 "link interni != k: %s" % ctx)
                for s in navs:
                    self.assertIn(s, self.slug_noti, "link interno a città ignota: %s" % ctx)
                    self.assertNotEqual(s, slug_citta(c), "auto-link nel nav: %s" % ctx)
                # niente breakout XSS
                self.assertNotIn("<script>alert", h, ctx)

    def test_jsonld_ricco_faqpage_e_breadcrumb(self):
        for c in ("Roma", "Tokyo", "New York"):
            for lng in ("it", "en", "ja"):
                h = genera_landing_host(c, lingua=lng, base_url=BASE)
                tipi = {b.get("@type") for b in _jsonld_blocchi(h)}
                self.assertIn("FAQPage", tipi, "FAQPage assente %s/%s" % (c, lng))
                self.assertIn("BreadcrumbList", tipi, "BreadcrumbList assente %s/%s" % (c, lng))
        # breadcrumb: 2 livelli, item assoluti
        b = json.loads(breadcrumb_jsonld("Roma", BASE, lingua="it")
                       .replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&"))
        el = b["itemListElement"]
        self.assertEqual([x["position"] for x in el], [1, 2])
        self.assertTrue(el[0]["item"].startswith("https://"))
        self.assertTrue(el[1]["item"].endswith("/affitta/roma"))

    def test_hreflang_reciproco_e_identico(self):
        # tutte le varianti-lingua di una città devono dichiarare lo STESSO set di alternate
        for c in ("Roma", "Bangkok"):
            insiemi = []
            for lng in LINGUE:
                h = genera_landing_host(c, lingua=lng, base_url=BASE)
                insiemi.append(frozenset(_hreflang(h).items()))
            self.assertEqual(len(set(insiemi)), 1,
                             "hreflang non reciproco/uniforme per %s" % c)

    def test_titoli_e_desc_unici_per_lingua(self):
        for lng in LINGUE:
            titoli, descr = set(), set()
            for c in CITTA_SEED:
                h = genera_landing_host(c, lingua=lng, base_url=BASE)
                titoli.add(_title(h))
                descr.add(_meta(h, "description"))
            self.assertEqual(len(titoli), len(CITTA_SEED), "title duplicati in %s" % lng)
            self.assertEqual(len(descr), len(CITTA_SEED), "description duplicate in %s" % lng)

    def test_deterministico_no_cloaking(self):
        for c in ("Roma", "Dubai"):
            a = genera_landing_host(c, lingua="en", base_url=BASE,
                                    citta_correlate=vicini_di(c, CITTA_SEED, k=K))
            b = genera_landing_host(c, lingua="en", base_url=BASE,
                                    citta_correlate=vicini_di(c, CITTA_SEED, k=K))
            self.assertEqual(a, b, "output non deterministico (rischio cloaking): %s" % c)

    # ---- COPERTURA / robots / sitemap ---------------------------------------
    def test_copertura_sitemap_host_superset_pagine(self):
        xml = sitemap_inbound(BASE)
        for c in CITTA_SEED:
            s = slug_citta(c)
            for lng in LINGUE:
                url = BASE + "/affitta/" + s + ("" if lng == "it" else "?lang=" + lng)
                self.assertIn("<loc>%s</loc>" % url, xml, "sitemap non copre %s/%s" % (c, lng))
        self.assertEqual(xml.count("<lastmod>"), len(CITTA_SEED) * len(LINGUE))
        minidom.parseString(xml)                    # ben formata

    def test_robots_permette_e_dichiara_sitemap(self):
        r = robots_txt(BASE)
        self.assertIn("User-agent: *", r)
        self.assertIn("Allow: /", r)
        self.assertIn("Sitemap: %s/sitemap.xml" % BASE, r)
        self.assertIn("Sitemap: %s/sitemap-host.xml" % BASE, r)

    def test_sitemap_xml_schede_ben_formata_con_lastmod(self):
        from fase57_vetrina import crea_catalogo, SchedaAlloggio
        cat = crea_catalogo()
        cat.pubblica(SchedaAlloggio(host_id="h", slug="casa-mare", titolo="Casa", citta="Roma",
                                    prezzo_notte_cents=12000, capacita=4))
        sistema = types.SimpleNamespace(catalogo=cat)
        xml = sitemap_xml(sistema, BASE)
        self.assertIn("<loc>%s/alloggio/casa-mare</loc>" % BASE, xml)
        self.assertRegex(xml, r"<lastmod>\d{4}-\d{2}-\d{2}</lastmod>")
        minidom.parseString(xml)                    # ben formata


if __name__ == "__main__":
    unittest.main(verbosity=2)
