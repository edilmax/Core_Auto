"""
Test Fase 77 - Portability Import Engine.

Copre: prezzo_a_cents (decimal-string -> cents, float/negativi rifiutati), adapter
booking/airbnb, normalizzazione + validazione (campi mancanti), disponibilita' (notti,
prezzo per-notte o ereditato), dry-run, apply isolato a catalogo/inventario fake,
INTEGRAZIONE reale fase57+fase58 (proprieta' cercabile+prenotabile dopo l'import),
robustezza.
"""
import unittest

from fase77_portability import (
    ReportImport, da_airbnb, da_booking, importa, prezzo_a_cents,
)


class TestPrezzo(unittest.TestCase):
    def test_decimal_string(self):
        self.assertEqual(prezzo_a_cents("82.00"), 8200)
        self.assertEqual(prezzo_a_cents("82"), 8200)
        self.assertEqual(prezzo_a_cents("82.5"), 8250)
        self.assertEqual(prezzo_a_cents("0.99"), 99)

    def test_rifiuta_float_e_negativi(self):
        self.assertIsNone(prezzo_a_cents(82.0))     # float -> no
        self.assertIsNone(prezzo_a_cents("-5"))
        self.assertIsNone(prezzo_a_cents("abc"))
        self.assertIsNone(prezzo_a_cents(8200))     # int ambiguo -> no


class TestAdapter(unittest.TestCase):
    def test_booking(self):
        c = da_booking({"property_name": "Casa", "city": "Roma", "base_rate": "82.00",
                        "max_occupancy": 4, "host_id": "h1", "property_id": "p1"})
        self.assertEqual(c["titolo"], "Casa")
        self.assertEqual(c["citta"], "Roma")
        self.assertEqual(c["prezzo_notte"], "82.00")

    def test_airbnb(self):
        c = da_airbnb({"listing_title": "Loft", "city": "Milano",
                       "nightly_price": "99.00", "accommodates": 2, "host_id": "h2",
                       "listing_id": "L9"})
        self.assertEqual(c["titolo"], "Loft")
        self.assertEqual(c["capacita"], 2)

    def test_adapter_non_dict(self):
        self.assertEqual(da_booking("x"), {})


CANONICO = {
    "host_id": "h1", "slug": "casa-roma", "titolo": "Casa a Roma", "citta": "Roma",
    "prezzo_notte": "100.00", "capacita": 4, "descrizione": "Bella",
    "servizi": ["WiFi", "Piscina"], "immagini": ["https://x/1.jpg", "ftp://x/2"],
    "disponibilita": [
        {"giorno": "2026-07-01", "unita": 1, "prezzo": "100.00"},
        {"giorno": "2026-07-02", "unita": 1},          # eredita il prezzo base
        {"giorno": "bad-date", "unita": 1},            # scartata
    ],
}


class TestNormalizzazione(unittest.TestCase):
    def test_dry_run(self):
        r = importa(CANONICO)
        self.assertTrue(r.ok)
        self.assertEqual(r.scheda["prezzo_notte_cents"], 10000)
        self.assertEqual(r.scheda["servizi"], ("wifi", "piscina"))
        self.assertEqual(r.immagini, ["https://x/1.jpg"])   # ftp scartato
        self.assertEqual(len(r.notti), 2)                   # bad-date scartata
        self.assertEqual(r.notti[1]["prezzo_cents"], 10000)  # ereditato

    def test_prezzo_invalido(self):
        bad = dict(CANONICO, prezzo_notte="gratis")
        r = importa(bad)
        self.assertFalse(r.ok)
        self.assertIn("prezzo_non_valido", r.errori)

    def test_campi_mancanti(self):
        r = importa({"slug": "x"})
        self.assertFalse(r.ok)
        self.assertIn("host_id_mancante", r.errori)

    def test_da_booking_end_to_end(self):
        raw = {"property_name": "Hotel X", "city": "Roma", "base_rate": "82.00",
               "max_occupancy": 2, "host_id": "h1", "property_id": "p1"}
        r = importa(raw, sorgente="booking")
        self.assertTrue(r.ok)
        self.assertEqual(r.scheda["prezzo_notte_cents"], 8200)


class _FakeCatalogo:
    def __init__(self):
        self.pubblicati = []
    def pubblica(self, scheda, immagini):
        self.pubblicati.append((scheda, immagini))


class _FakeCatalogoRotto:
    def pubblica(self, scheda, immagini):
        raise RuntimeError("db giu'")


class _FakeInventario:
    def __init__(self):
        self.giorni = {}
    def imposta_disponibilita(self, slug, giorno, *, unita_totali, prezzo_netto_cents):
        self.giorni[(slug, giorno)] = (unita_totali, prezzo_netto_cents)
        return True


class TestApply(unittest.TestCase):
    def test_applica_catalogo_inventario(self):
        cat, inv = _FakeCatalogo(), _FakeInventario()
        r = importa(CANONICO, catalogo=cat, inventario=inv)
        self.assertTrue(r.catalogo_applicato)
        self.assertEqual(len(cat.pubblicati), 1)
        self.assertEqual(r.notti_applicate, 2)

    def test_catalogo_isolato(self):
        r = importa(CANONICO, catalogo=_FakeCatalogoRotto())
        self.assertTrue(r.ok)                       # non crasha
        self.assertFalse(r.catalogo_applicato)
        self.assertIn("catalogo_non_applicato", r.errori)


class TestIntegrazioneReale(unittest.TestCase):
    def test_import_rende_cercabile_e_prenotabile(self):
        from fase57_vetrina import CriteriRicerca, crea_catalogo
        from fase58_channel_manager import crea_channel_manager
        cat = crea_catalogo()
        inv = crea_channel_manager()
        r = importa(CANONICO, catalogo=cat, inventario=inv)
        self.assertTrue(r.catalogo_applicato)
        # cercabile in vetrina
        res = cat.cerca(CriteriRicerca(citta="Roma"))
        self.assertEqual(res["totale"], 1)
        self.assertEqual(res["risultati"][0]["slug"], "casa-roma")
        # prenotabile sull'inventario importato
        self.assertTrue(inv.disponibile("casa-roma", "2026-07-01", "2026-07-02"))
        e = inv.blocca("casa-roma", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertTrue(e.ok)


class TestValuta(unittest.TestCase):
    def test_prezzo_per_valuta(self):
        self.assertEqual(prezzo_a_cents("82.00", "EUR"), 8200)   # exp 2
        self.assertEqual(prezzo_a_cents("8000", "JPY"), 8000)    # exp 0 (no ×100)
        self.assertEqual(prezzo_a_cents("3500.50", "THB"), 350050)
        self.assertEqual(prezzo_a_cents("82.00"), 8200)          # default EUR invariato

    def test_valuta_preservata_nell_import(self):
        raw = dict(CANONICO, valuta="THB", prezzo_notte="3500.00",
                   disponibilita=[{"giorno": "2026-07-01", "unita": 1}])
        r = importa(raw)
        self.assertTrue(r.ok, r.errori)
        self.assertEqual(r.scheda["valuta"], "THB")
        self.assertEqual(r.scheda["prezzo_notte_cents"], 350000)
        self.assertEqual(r.notti[0]["prezzo_cents"], 350000)     # notte eredita in THB

    def test_valuta_jpy_esponente_zero(self):
        raw = dict(CANONICO, valuta="JPY", prezzo_notte="12000",
                   disponibilita=[])
        r = importa(raw)
        self.assertEqual(r.scheda["prezzo_notte_cents"], 12000)  # NON 1.200.000

    def test_valuta_invalida_default_eur(self):
        r = importa(dict(CANONICO, valuta="ZZZZ"))
        self.assertEqual(r.scheda["valuta"], "EUR")


class TestOverrideSicuro(unittest.TestCase):
    def test_host_id_e_slug_forzati(self):
        # il pannello forza il proprietario (dal token) e lo slug (auto) -> no furto/collisioni
        r = importa(dict(CANONICO, host_id="EXPORT_HOST", slug="export-slug"),
                    host_id="OWNER_TOKEN", genera_slug=lambda t, c: "auto-" + (t or "x")[:4].lower())
        self.assertTrue(r.ok, r.errori)
        self.assertEqual(r.scheda["host_id"], "OWNER_TOKEN")     # dal token, non dall'export
        self.assertEqual(r.scheda["slug"], "auto-casa")          # generato, non dall'export

    def test_non_muta_input_chiamante(self):
        src = dict(CANONICO)
        importa(src, host_id="X", genera_slug=lambda t, c: "y")
        self.assertEqual(src["host_id"], "h1")                   # input invariato
        self.assertEqual(src["slug"], "casa-roma")


class TestRehost(unittest.TestCase):
    def test_rehost_ri_ospita_e_scarta_falliti(self):
        cat = _FakeCatalogo()
        raw = dict(CANONICO, immagini=["https://x/1.jpg", "https://x/2.jpg"])
        # rehost: la 1 va bene (nuovo URL nostro), la 2 fallisce (None) -> scartata
        reh = lambda u: "/uploads/ok.jpg" if u.endswith("1.jpg") else None
        r = importa(raw, catalogo=cat, rehost=reh)
        self.assertTrue(r.catalogo_applicato)
        _, immagini = cat.pubblicati[0]
        self.assertEqual([im.url for im in immagini], ["/uploads/ok.jpg"])   # solo la ri-ospitata
        self.assertEqual(r.immagini, ["/uploads/ok.jpg"])

    def test_rehost_che_solleva_non_rompe(self):
        cat = _FakeCatalogo()
        def reh(u): raise RuntimeError("rete giu'")
        r = importa(dict(CANONICO), catalogo=cat, rehost=reh)
        self.assertTrue(r.catalogo_applicato)             # import prosegue
        _, immagini = cat.pubblicati[0]
        self.assertEqual(immagini, [])                    # nessuna foto (tutte scartate)


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        for bad in (None, 123, "x", [], {}):
            try:
                importa(bad)
                importa(bad, sorgente="booking")
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")


if __name__ == "__main__":
    unittest.main()
