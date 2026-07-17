"""
Test Fase 57 - Vetrina / Catalogo pubblico.

Copre: schema idempotente, pubblicazione + dettaglio, upsert idempotente per slug,
ordine immagini, validatore blindato (float/bool/negativi/mancanti/oversize),
ricerca per citta/prezzo/capacita/servizi(bitmask)/bbox, paginazione + tetto,
ordinamenti, visibilita' (solo 'pubblicato'), provider disponibilita' + isolamento,
purezza dei contratti JSON (zero float), e stress concorrente ripetuto (10x).
"""
import threading
import unittest

from fase57_vetrina import (
    SERVIZI, CatalogoVetrina, CriteriRicerca, Immagine, SchedaAlloggio,
    crea_catalogo, maschera_servizi, servizi_da_maschera, valida_scheda,
    PAGINA_MAX,
)


def _scheda(slug="casa-mare", **kw):
    base = dict(host_id="host1", slug=slug, titolo="Bella casa", citta="Roma",
                prezzo_notte_cents=12000, capacita=4)
    base.update(kw)
    return SchedaAlloggio(**base)


class TestServiziBitmask(unittest.TestCase):
    def test_round_trip(self):
        codici = ["wifi", "piscina", "cucina"]
        mask = maschera_servizi(codici)
        self.assertEqual(set(servizi_da_maschera(mask)), set(codici))

    def test_codici_ignoti_ignorati(self):
        self.assertEqual(maschera_servizi(["wifi", "teletrasporto"]),
                         SERVIZI["wifi"])

    def test_maschera_invalida_robusta(self):
        self.assertEqual(servizi_da_maschera(-1), [])
        self.assertEqual(servizi_da_maschera(True), [])
        self.assertEqual(servizi_da_maschera("x"), [])


class TestValidatore(unittest.TestCase):
    def test_scheda_valida(self):
        ok, codice, s = valida_scheda(dict(
            host_id="h", slug="s", titolo="t", citta="Milano",
            prezzo_notte_cents=9900, capacita=2, servizi=["wifi"]))
        self.assertTrue(ok, codice)
        self.assertEqual(s.prezzo_notte_cents, 9900)

    def test_prezzo_float_rifiutato(self):
        ok, codice, _ = valida_scheda(dict(
            host_id="h", slug="s", titolo="t", citta="x",
            prezzo_notte_cents=99.0, capacita=2))
        self.assertFalse(ok)
        self.assertEqual(codice, "prezzo_non_intero")

    def test_prezzo_stringa_rifiutato(self):
        ok, codice, _ = valida_scheda(dict(
            host_id="h", slug="s", titolo="t", citta="x",
            prezzo_notte_cents="9900", capacita=2))
        self.assertFalse(ok)
        self.assertEqual(codice, "prezzo_non_intero")

    def test_prezzo_bool_rifiutato(self):
        ok, codice, _ = valida_scheda(dict(
            host_id="h", slug="s", titolo="t", citta="x",
            prezzo_notte_cents=True, capacita=2))
        self.assertFalse(ok)
        self.assertEqual(codice, "prezzo_non_intero")

    def test_prezzo_negativo_e_zero(self):
        for p in (-1, 0):
            ok, codice, _ = valida_scheda(dict(
                host_id="h", slug="s", titolo="t", citta="x",
                prezzo_notte_cents=p, capacita=2))
            self.assertFalse(ok)

    def test_campi_mancanti(self):
        ok, codice, _ = valida_scheda(dict(slug="s", titolo="t", citta="x",
                                           prezzo_notte_cents=100, capacita=1))
        self.assertFalse(ok)
        self.assertEqual(codice, "host_id_non_valido")

    def test_payload_non_dict(self):
        ok, codice, _ = valida_scheda("non un dict")
        self.assertFalse(ok)
        self.assertEqual(codice, "payload_non_oggetto")

    def test_oversize_titolo(self):
        ok, codice, _ = valida_scheda(dict(
            host_id="h", slug="s", titolo="x" * 5000, citta="x",
            prezzo_notte_cents=100, capacita=1))
        self.assertFalse(ok)

    def test_stato_non_valido(self):
        ok, codice, _ = valida_scheda(dict(
            host_id="h", slug="s", titolo="t", citta="x",
            prezzo_notte_cents=100, capacita=1, stato="online"))
        self.assertFalse(ok)
        self.assertEqual(codice, "stato_non_valido")

    def test_geo_float_rifiutata(self):
        ok, codice, _ = valida_scheda(dict(
            host_id="h", slug="s", titolo="t", citta="x",
            prezzo_notte_cents=100, capacita=1, lat_micro=41.9))
        self.assertFalse(ok)
        self.assertEqual(codice, "lat_micro_non_intero")

    def test_validatore_non_solleva_mai(self):
        for bad in (None, 123, [], "", {"a": object()}, {"host_id": 1}):
            try:
                ok, _, _ = valida_scheda(bad)
                self.assertFalse(ok)
            except Exception as e:  # pragma: no cover
                self.fail(f"validatore ha sollevato su {bad!r}: {e}")


class TestPubblicazione(unittest.TestCase):
    def setUp(self):
        self.cat = crea_catalogo()

    def test_schema_idempotente(self):
        self.cat.inizializza_schema()  # secondo giro, nessun errore
        self.cat.inizializza_schema()

    def test_pubblica_e_dettaglio(self):
        self.cat.pubblica(_scheda(servizi=("wifi", "piscina"), descrizione="vista"),
                          [Immagine("https://x/1.jpg", 0, "a"),
                           Immagine("https://x/2.jpg", 1, "b")])
        d = self.cat.dettaglio("casa-mare")
        self.assertIsNotNone(d)
        self.assertEqual(d["prezzo_notte_cents"], 12000)
        self.assertEqual(d["tavolo_id"], "casa-mare")
        self.assertEqual(len(d["immagini"]), 2)
        self.assertEqual(set(d["servizi"]), {"wifi", "piscina"})

    def test_upsert_idempotente(self):
        self.cat.pubblica(_scheda(prezzo_notte_cents=10000))
        id2 = self.cat.pubblica(_scheda(prezzo_notte_cents=20000, titolo="Aggiornata"))
        d = self.cat.dettaglio("casa-mare")
        self.assertEqual(d["prezzo_notte_cents"], 20000)
        self.assertEqual(d["titolo"], "Aggiornata")
        # una sola riga (upsert, non duplicato)
        res = self.cat.cerca(CriteriRicerca(citta="Roma"))
        self.assertEqual(res["totale"], 1)

    def test_immagini_sostituite_e_ordinate(self):
        self.cat.pubblica(_scheda(), [Immagine("https://x/1.jpg", 5)])
        self.cat.pubblica(_scheda(), [Immagine("https://x/b.jpg", 1),
                                      Immagine("https://x/a.jpg", 0)])
        d = self.cat.dettaglio("casa-mare")
        self.assertEqual([i["url"] for i in d["immagini"]],
                         ["https://x/a.jpg", "https://x/b.jpg"])

    def test_immagini_invalide_scartate(self):
        self.cat.pubblica(_scheda(), [Immagine("ftp://x/1.jpg", 0),
                                      Immagine("javascript:alert(1)", 1),
                                      Immagine("https://ok/2.jpg", 2)])
        d = self.cat.dettaglio("casa-mare")
        self.assertEqual([i["url"] for i in d["immagini"]], ["https://ok/2.jpg"])

    def test_stato_nasconde_dalla_vetrina(self):
        self.cat.pubblica(_scheda(stato="bozza"))
        self.assertIsNone(self.cat.dettaglio("casa-mare"))
        self.assertEqual(self.cat.cerca(CriteriRicerca()).get("totale"), 0)
        self.assertTrue(self.cat.imposta_stato("casa-mare", "pubblicato"))
        self.assertIsNotNone(self.cat.dettaglio("casa-mare"))

    def test_imposta_stato_invalido(self):
        self.cat.pubblica(_scheda())
        self.assertFalse(self.cat.imposta_stato("casa-mare", "online"))

    def test_alloggi_host(self):
        self.cat.pubblica(_scheda("a", host_id="h1"))
        self.cat.pubblica(_scheda("b", host_id="h1", stato="bozza"))
        self.cat.pubblica(_scheda("c", host_id="h2"))
        miei = self.cat.alloggi_host("h1")
        self.assertEqual({m["slug"] for m in miei}, {"a", "b"})   # anche la bozza
        stati = {m["slug"]: m["stato"] for m in miei}
        self.assertEqual(stati["b"], "bozza")
        self.assertEqual(self.cat.alloggi_host("ignoto"), [])


class TestRicerca(unittest.TestCase):
    def setUp(self):
        self.cat = crea_catalogo()
        self.cat.pubblica(_scheda("a", citta="Roma", prezzo_notte_cents=10000,
                                  capacita=2, servizi=("wifi",)))
        self.cat.pubblica(_scheda("b", citta="Roma", prezzo_notte_cents=20000,
                                  capacita=4, servizi=("wifi", "piscina")))
        self.cat.pubblica(_scheda("c", citta="Milano", prezzo_notte_cents=15000,
                                  capacita=6, servizi=("wifi", "piscina", "cucina")))

    def test_filtro_citta(self):
        r = self.cat.cerca(CriteriRicerca(citta="Roma"))
        self.assertEqual(r["totale"], 2)

    def test_filtro_prezzo_range(self):
        r = self.cat.cerca(CriteriRicerca(prezzo_min_cents=12000,
                                          prezzo_max_cents=18000))
        self.assertEqual({x["slug"] for x in r["risultati"]}, {"c"})

    def test_filtro_capacita(self):
        r = self.cat.cerca(CriteriRicerca(capacita_min=5))
        self.assertEqual({x["slug"] for x in r["risultati"]}, {"c"})

    def test_filtro_servizi_AND(self):
        r = self.cat.cerca(CriteriRicerca(servizi=("wifi", "piscina")))
        self.assertEqual({x["slug"] for x in r["risultati"]}, {"b", "c"})
        r2 = self.cat.cerca(CriteriRicerca(servizi=("piscina", "cucina")))
        self.assertEqual({x["slug"] for x in r2["risultati"]}, {"c"})

    def test_ordinamento_prezzo(self):
        asc = self.cat.cerca(CriteriRicerca(ordine="prezzo_asc"))
        self.assertEqual([x["prezzo_notte_cents"] for x in asc["risultati"]],
                         [10000, 15000, 20000])
        desc = self.cat.cerca(CriteriRicerca(ordine="prezzo_desc"))
        self.assertEqual([x["prezzo_notte_cents"] for x in desc["risultati"]],
                         [20000, 15000, 10000])

    def test_paginazione(self):
        r = self.cat.cerca(CriteriRicerca(ordine="prezzo_asc", limit=2, offset=0))
        self.assertEqual(r["totale"], 3)
        self.assertEqual(len(r["risultati"]), 2)
        r2 = self.cat.cerca(CriteriRicerca(ordine="prezzo_asc", limit=2, offset=2))
        self.assertEqual(len(r2["risultati"]), 1)

    def test_limit_clamp(self):
        r = self.cat.cerca(CriteriRicerca(limit=99999))
        self.assertLessEqual(r["limit"], PAGINA_MAX)
        r0 = self.cat.cerca(CriteriRicerca(limit=0))
        self.assertGreaterEqual(r0["limit"], 1)

    def test_bbox_geo(self):
        self.cat.pubblica(_scheda("geo", citta="Napoli", lat_micro=40_800_000,
                                  lon_micro=14_200_000))
        r = self.cat.cerca(CriteriRicerca(
            bbox=(40_000_000, 41_000_000, 14_000_000, 15_000_000)))
        self.assertIn("geo", {x["slug"] for x in r["risultati"]})

    def test_contratto_solo_interi(self):
        r = self.cat.cerca(CriteriRicerca(citta="Roma"))
        for card in r["risultati"]:
            self.assertIsInstance(card["prezzo_notte_cents"], int)
            self.assertNotIsInstance(card["prezzo_notte_cents"], bool)
            self.assertIsInstance(card["capacita"], int)


class TestDisponibilita(unittest.TestCase):
    def test_annotazione(self):
        # il provider riceve lo SLUG (string), come fase58/concierge
        cat = crea_catalogo(disponibilita=lambda slug, ci, co: slug == "a")
        cat.pubblica(_scheda("a"))
        r = cat.cerca(CriteriRicerca(check_in="2026-07-01", check_out="2026-07-03"))
        card = r["risultati"][0]
        self.assertTrue(card["disponibile"])

    def test_senza_date_ignoto(self):
        cat = crea_catalogo(disponibilita=lambda aid, ci, co: True)
        cat.pubblica(_scheda("a"))
        r = cat.cerca(CriteriRicerca())
        self.assertIsNone(r["risultati"][0]["disponibile"])

    def test_provider_che_solleva_isolato(self):
        def boom(aid, ci, co):
            raise RuntimeError("motore booking giu'")
        cat = crea_catalogo(disponibilita=boom)
        cat.pubblica(_scheda("a"))
        # non deve schiantare: degrada a 'ignoto'
        r = cat.cerca(CriteriRicerca(check_in="2026-07-01", check_out="2026-07-03"))
        self.assertIsNone(r["risultati"][0]["disponibile"])


class TestStress(unittest.TestCase):
    def test_carico_e_concorrenza_10x(self):
        """10 ripetizioni: popola un catalogo, letture concorrenti, risultati stabili."""
        for _ in range(10):
            cat = crea_catalogo()
            for i in range(200):
                cat.pubblica(_scheda(
                    f"slug-{i}", citta="Roma" if i % 2 else "Milano",
                    prezzo_notte_cents=10000 + i * 100, capacita=(i % 6) + 1,
                    servizi=("wifi",) if i % 3 == 0 else ("wifi", "piscina")))
            self.assertEqual(cat.cerca(CriteriRicerca(limit=PAGINA_MAX))["totale"], 200)

            errori = []

            def lettore():
                try:
                    for _ in range(20):
                        r = cat.cerca(CriteriRicerca(citta="Roma", servizi=("wifi",),
                                                     ordine="prezzo_asc", limit=50))
                        prezzi = [c["prezzo_notte_cents"] for c in r["risultati"]]
                        assert prezzi == sorted(prezzi)
                except Exception as e:  # pragma: no cover
                    errori.append(e)

            th = [threading.Thread(target=lettore) for _ in range(8)]
            for t in th:
                t.start()
            for t in th:
                t.join()
            self.assertEqual(errori, [], f"letture concorrenti fallite: {errori}")


class TestSlugLastmod(unittest.TestCase):
    """Metodo dedicato per il <lastmod> della sitemap: solo schede PUBBLICATE, data ISO."""

    def test_solo_pubblicati_con_data(self):
        import re
        cat = crea_catalogo()
        cat.pubblica(_scheda("visibile", citta="Roma"))
        cat.pubblica(_scheda("nascosta", stato="bozza"))
        coppie = cat.slug_lastmod_pubblicati()
        slugs = {s for s, _ in coppie}
        self.assertIn("visibile", slugs)
        self.assertNotIn("nascosta", slugs)             # la bozza NON entra in sitemap
        for _s, d in coppie:
            self.assertRegex(d, r"^\d{4}-\d{2}-\d{2}$")  # 'YYYY-MM-DD'

    def test_blindato_limit_invalido(self):
        cat = crea_catalogo()
        cat.pubblica(_scheda("x"))
        self.assertEqual(len(cat.slug_lastmod_pubblicati(limit=-5)), 1)  # fallback a default


if __name__ == "__main__":
    unittest.main()
