"""Test Fase 173 - Motore SEO autonomo (orchestratore del cervello fase171).
Copre: COERENZA specchio<->JSON-LD reale (anti-deriva, lezione bug #33), provider
blindati, gancio publish che non rompe mai, IndexNow gated con URL giusti, rotta
/api/host/seo_report (auth+proprieta'), vista host senza ledger grezzo."""
import json
import unittest

from fase83_server import crea_router, jsonld_alloggio, pagina_alloggio_html
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
from fase171_cervello_seo import valuta_annuncio
from fase173_motore_seo import (MotoreSEO, crea_motore_da_sistema, faq_jsonld, genera_faq,
                                markup_pagina, rapporto_host)

DETTAGLIO = {
    "slug": "casa-roma", "titolo": "Casa a Roma", "descrizione": "x" * 320,
    "citta": "Roma", "paese": "IT", "prezzo_notte_cents": 12000, "valuta": "EUR",
    "capacita": 4, "camere": 2, "bagni": 1,
    "servizi": ["wifi", "piscina"], "politica_cancellazione": "flessibile",
    "modalita_prenotazione": "immediata", "lat_micro": 41_900_000,
    "lon_micro": 12_500_000,
    "immagini": [{"url": "/uploads/a.jpg", "ordine": 0, "alt": "salotto"}],
}

def _scheda_dettaglio():
    """Dettaglio con coordinate (vicine al POI di test) per le FAQ POI/tassa."""
    s = dict(DETTAGLIO)
    s["lat_micro"], s["lon_micro"] = 41_900_000, 12_500_000
    s["servizi"] = ["wifi", "piscina", "animali_ammessi"]
    return s


# mappa slot-ledger -> come si riconosce nel JSON-LD reale della pagina
_LD_ATTESO = {
    "prezzo_notte": lambda ld: "price" in ld.get("offers", {}),
    "capacita": lambda ld: "occupancy" in ld,
    "camere": lambda ld: "numberOfRooms" in ld,
    "bagni": lambda ld: "numberOfBathroomsTotal" in ld,
    "coordinate": lambda ld: "geo" in ld,
    "foto": lambda ld: bool(ld.get("image")),
    "rating_verificato": lambda ld: "aggregateRating" in ld,
}


class TestSpecchioMarkup(unittest.TestCase):
    def test_ogni_slot_dichiarato_emesso_esiste_nel_jsonld_reale(self):
        rec = {"conteggio": 4, "media_centesimi": 450}
        ld = jsonld_alloggio(DETTAGLIO, "https://bookinvip.com", rec)
        for slot in markup_pagina(DETTAGLIO, rec):
            if slot.startswith("amenita:"):
                cod = slot.split(":", 1)[1]
                nomi = {a["name"] for a in ld.get("amenityFeature", [])}
                self.assertIn(cod, nomi, slot)
            else:
                self.assertTrue(_LD_ATTESO[slot](ld),
                                "specchio dice emesso ma il JSON-LD reale non ha: %s" % slot)

    def test_specchio_non_dichiara_cio_che_manca(self):
        d = dict(DETTAGLIO)
        d["lat_micro"] = None
        d["immagini"] = []
        emessi = markup_pagina(d, None)
        self.assertNotIn("coordinate", emessi)
        self.assertNotIn("foto", emessi)
        self.assertNotIn("rating_verificato", emessi)
        ld = jsonld_alloggio(d, "https://x")
        self.assertNotIn("geo", ld)
        self.assertNotIn("image", ld)

    def test_geo_stringhe_senza_float(self):
        ld = jsonld_alloggio(DETTAGLIO, "https://x")
        self.assertEqual(ld["geo"]["latitude"], "41.900000")
        d = dict(DETTAGLIO)
        d["lat_micro"] = -5_250_000
        self.assertEqual(jsonld_alloggio(d, "https://x")["geo"]["latitude"], "-5.250000")


class TestMotoreBlindato(unittest.TestCase):
    def test_provider_rotti_non_rompono(self):
        def bomba(*_a):
            raise RuntimeError("provider giu'")
        m = MotoreSEO(tassa_regola_fn=bomba, poi_fn=bomba, quartiere_fn=bomba,
                      geocode_fn=bomba, recensioni_fn=bomba, coorte_fn=bomba)
        r = m.valuta(DETTAGLIO)
        self.assertTrue(0 <= r["punteggio"] <= 100)
        esito = m.su_pubblicazione(DETTAGLIO, "https://bookinvip.com")
        self.assertIn("valutazione", esito)
        self.assertFalse(esito["indexnow"]["inviato"])

    def test_tassa_zero_non_entra_nel_contesto(self):
        m0 = MotoreSEO(tassa_regola_fn=lambda c: {"per_persona_notte_cents": 0})
        self.assertNotIn("comune_tassa", m0.contesto(DETTAGLIO))
        m1 = MotoreSEO(tassa_regola_fn=lambda c: {"per_persona_notte_cents": 350})
        self.assertIn("comune_tassa", m1.contesto(DETTAGLIO))

    def test_indexnow_attivo_riceve_gli_url_giusti(self):
        chiamate = []

        class Finto:
            attivo = True

            def submit(self, urls):
                chiamate.append(list(urls))
                return {"inviato": True, "url": len(urls), "stato": 200}

        m = MotoreSEO(indexnow=Finto())
        esito = m.su_pubblicazione(DETTAGLIO, "https://bookinvip.com")
        self.assertTrue(esito["indexnow"]["inviato"])
        self.assertEqual(chiamate, [["https://bookinvip.com/alloggio/casa-roma",
                                     "https://bookinvip.com/affitta/roma"]])

    def test_rapporto_host_nasconde_il_grezzo(self):
        m = MotoreSEO()
        vista = rapporto_host(m.valuta(DETTAGLIO))
        self.assertNotIn("fatti", vista)
        self.assertIn("punteggio", vista)
        for g in vista["cosa_migliorare"]:
            self.assertNotEqual(g["tipo"], "sistema")   # i lavori nostri non sono dell'host


class TestFAQ(unittest.TestCase):
    def _rapporto(self, ctx=None):
        return valuta_annuncio(_scheda_dettaglio(), ctx or {}, None, ())

    def test_faq_dai_fatti_reali(self):
        ctx = {"comune_tassa": {"ppn_cents": 350, "max_notti": 10},
               "poi": [{"nome": "Colosseo", "cat": "attraction",
                        "lat_micro": 41_900_050, "lon_micro": 12_500_050}]}
        faq = genera_faq(valuta_annuncio(_scheda_dettaglio(), ctx, None, ()),
                         _scheda_dettaglio())
        testo = " ".join(x["q"] + " " + x["a"] for x in faq)
        self.assertIn("120.00", testo)                 # prezzo esatto (cents interi)
        self.assertIn("Colosseo", testo)               # POI con distanza
        self.assertIn("metri", testo)
        self.assertIn("tassa di soggiorno", testo)
        self.assertIn("3.50", testo)                   # tassa esatta
        self.assertLessEqual(len(faq), 8)

    def test_white_hat_solo_fatti_presenti(self):
        # niente animali dichiarati -> nessuna FAQ "sono ammessi animali"
        s = dict(_scheda_dettaglio())
        s["servizi"] = ["wifi"]
        faq = genera_faq(valuta_annuncio(s, {}, None, ()), s)
        self.assertFalse(any("animali" in x["a"].lower() for x in faq))
        # niente prezzo -> niente FAQ prezzo
        s2 = dict(s)
        s2["prezzo_notte_cents"] = 0
        faq2 = genera_faq(valuta_annuncio(s2, {}, None, ()), s2)
        self.assertFalse(any("prezzo" in x["a"].lower() for x in faq2))

    def test_jsonld_faqpage_coerente_col_visibile(self):
        # ogni domanda del FAQPage JSON-LD deve comparire come <details> visibile nella pagina
        import tempfile
        d = tempfile.mkdtemp()
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/a.db",
            db_pendenti=f"{d}/p.db", db_messaggi=f"{d}/m.db", db_garanzia=f"{d}/g.db",
            commissione_bps=1500))
        r = crea_router(sis, host_key="hk", base_url="https://bookinvip.com")
        _, c = r.gestisci("POST", "/api/host/registrazione", {},
                          json.dumps({"email": "h@f.it", "password": "password1",
                                      "accetta_termini": True, "accetta_clausole": True,
                                      "doc_sha256": doc_sha256(),
                                      "versione": CONTRATTO_HOST_VERSIONE}), {})
        r.gestisci("POST", "/api/host/pubblica", {},
                   json.dumps({"slug": "faq-casa", "titolo": "Casa FAQ", "citta": "Roma",
                               "prezzo_notte_cents": 12000, "capacita": 4, "camere": 2,
                               "bagni": 1, "servizi": ["wifi", "piscina"]}),
                   {"X-Host-Token": c["token"]})
        html = pagina_alloggio_html(sis, "faq-casa", "https://bookinvip.com")
        self.assertIn("FAQPage", html)
        self.assertIn("Domande frequenti", html)
        rapporto = crea_motore_da_sistema(sis).valuta(sis.catalogo.dettaglio("faq-casa"))
        for x in genera_faq(rapporto, sis.catalogo.dettaglio("faq-casa")):
            import html as _h
            self.assertIn(_h.escape(x["q"]), html, "domanda FAQ non visibile: %s" % x["q"])

    def test_faq_jsonld_vuoto_e_none(self):
        self.assertIsNone(faq_jsonld([]))
        ld = faq_jsonld([{"q": "Q?", "a": "A."}])
        self.assertEqual(ld["@type"], "FAQPage")
        self.assertEqual(ld["mainEntity"][0]["name"], "Q?")


class TestRottaEPublish(unittest.TestCase):
    def setUp(self):
        import tempfile
        d = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/a.db",
            db_pendenti=f"{d}/p.db", db_messaggi=f"{d}/m.db",
            db_garanzia=f"{d}/g.db", commissione_bps=1500))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@seo.it", "password": "password1",
                       "accetta_termini": True, "accetta_clausole": True,
                       "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        assert s == 201, c
        self.tok = c["token"]
        s, c = self.g("POST", "/api/host/pubblica",
                      {"slug": "casa-seo", "titolo": "Casa SEO", "citta": "Roma",
                       "prezzo_notte_cents": 11000, "capacita": 4, "camere": 2,
                       "bagni": 1, "servizi": ["wifi", "piscina"]},
                      {"X-Host-Token": self.tok})
        assert s == 201, c

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None,
                               h or {})

    def test_report_richiede_auth_e_proprieta(self):
        s, _ = self.r.gestisci("GET", "/api/host/seo_report",
                               {"alloggio_id": "casa-seo"}, None, {})
        self.assertEqual(s, 401)
        s, _ = self.r.gestisci("GET", "/api/host/seo_report",
                               {"alloggio_id": "inesistente"}, None,
                               {"X-Host-Token": self.tok})
        self.assertIn(s, (403, 404))

    def test_report_del_proprietario(self):
        s, c = self.r.gestisci("GET", "/api/host/seo_report",
                               {"alloggio_id": "casa-seo"}, None,
                               {"X-Host-Token": self.tok})
        self.assertEqual(s, 200, c)
        self.assertTrue(0 <= c["punteggio"] <= 100)
        self.assertIn("query_vincibili", c)
        self.assertIn("cosa_migliorare", c)
        self.assertNotIn("fatti", c)

    def test_publish_scatta_il_motore_senza_rompersi(self):
        # spia: il gancio DEVE essere stato invocabile; un motore che esplode non
        # deve toccare l'esito della pubblicazione
        class Esplosivo:
            def su_pubblicazione(self, *_a, **_k):
                raise RuntimeError("boom")
        self.r._motore_seo_cache = Esplosivo()
        s, c = self.g("POST", "/api/host/pubblica",
                      {"slug": "casa-seo", "titolo": "Casa SEO agg", "citta": "Roma",
                       "prezzo_notte_cents": 12000, "capacita": 4},
                      {"X-Host-Token": self.tok})
        self.assertEqual(s, 201, c)

    def test_factory_dal_sistema(self):
        m = crea_motore_da_sistema(self.sis)
        r = m.valuta(self.sis.catalogo.dettaglio("casa-seo"))
        self.assertTrue(0 <= r["punteggio"] <= 100)

    def test_factory_cabla_provider_poi_se_presente(self):
        # se il sistema espone poi_provider, il motore lo usa nel contesto
        class FintoPOI:
            def vicini(self, dettaglio):
                return [{"nome": "Colosseo", "cat": "attraction",
                         "lat_micro": 41_900_050, "lon_micro": 12_500_050}]
        self.sis.poi_provider = FintoPOI()
        m = crea_motore_da_sistema(self.sis)
        det = dict(self.sis.catalogo.dettaglio("casa-seo") or {})
        det["lat_micro"], det["lon_micro"] = 41_900_000, 12_500_000
        ctx = m.contesto(det)
        self.assertTrue(any(p["nome"] == "Colosseo" for p in ctx.get("poi", [])))


if __name__ == "__main__":
    unittest.main(verbosity=2)
