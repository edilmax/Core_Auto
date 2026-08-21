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
                                      "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
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
                       "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
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

    def test_factory_cabla_quartiere_se_il_geocoder_lo_sa_fare(self):
        # se il sistema espone un geocoder con .quartiere (fase166 esteso), il motore
        # lo usa nel contesto; senza coordinate nel dettaglio -> niente quartiere
        class FintoGeo:
            def quartiere(self, lat_micro, lon_micro):
                return "Monti" if isinstance(lat_micro, int) else None
        self.sis.geocoder = FintoGeo()
        m = crea_motore_da_sistema(self.sis)
        det = dict(self.sis.catalogo.dettaglio("casa-seo") or {})
        det["lat_micro"], det["lon_micro"] = 41_900_000, 12_500_000
        self.assertEqual(m.contesto(det).get("quartiere"), "Monti")
        det2 = dict(det)
        det2.pop("lat_micro"), det2.pop("lon_micro")
        self.assertNotIn("quartiere", m.contesto(det2))

    def test_factory_geocoder_vecchio_senza_reverse_ignorato(self):
        # un geocoder che sa solo geocodificare (niente .quartiere) non rompe la factory
        class SoloAvanti:
            def geocodifica(self, citta, indirizzo="", paese=""):
                return (1, 2)
        self.sis.geocoder = SoloAvanti()
        m = crea_motore_da_sistema(self.sis)
        det = dict(self.sis.catalogo.dettaglio("casa-seo") or {})
        det["lat_micro"], det["lon_micro"] = 41_900_000, 12_500_000
        self.assertNotIn("quartiere", m.contesto(det))


class TestLaFAQNONPUOPROMETTEREQUELLOCHEILMOTORESMENTISCE(unittest.TestCase):
    """⛔ LA FAQ DELLE LANDING DICEVA IL FALSO A CHI STAVA PER PAGARE.

    Misurato il 2026-08-20 e riparato il 2026-08-21: `_POLITICA_IT["non_rimborsabile"]`
    rispondeva *«La tariffa non e' rimborsabile»* mentre il motore, entro la finestra di
    ripensamento, **restituisce il 100%**. Le altre tre risposte non erano false ma erano
    VAGHE -- «entro i termini indicati», «secondo i termini» -- cioe' non dicevano NIENTE
    a chi le legge, e la finestra non la nominava nessuna.

    ⛔ QUESTE GUARDIE NON CONFRONTANO IL TESTO CON UN ALTRO TESTO: interrogano il MOTORE
    (`fase111.calcola_rimborso` e i suoi scaglioni) e pretendono che la pagina pubblica non
    lo contraddica. E' la differenza fra un collaudo e una fotocopia: se domani qualcuno
    cambia uno scaglione, questa diventa rossa da sola.

    💡 E la ragione per cui esiste ora: fino al 2026-08-21 `RIPRENDI_QUI.md` la dava per
    GIA' SCRITTA, con questo nome esatto. Non esisteva (sbaglio S10).
    """

    def _politiche(self):
        from fase111_cancellazione import POLITICHE
        from fase173_motore_seo import _POLITICA_IT
        return POLITICHE, _POLITICA_IT

    def test_OGNI_politica_ha_la_sua_risposta_nella_FAQ(self):
        """Il denominatore: se nasce una politica nuova e nessuno scrive la sua risposta,
        la FAQ tace su un caso che il motore invece tratta."""
        POLITICHE, _POLITICA_IT = self._politiche()
        self.assertEqual(
            sorted(POLITICHE), sorted(_POLITICA_IT),
            "le politiche del motore e le risposte della FAQ non coincidono: o una politica "
            "non ha risposta, o una risposta parla di una politica che non esiste piu'")

    def test_NESSUNA_risposta_puo_dire_che_NON_si_rimborsa_quando_il_motore_RIMBORSA(self):
        """Il difetto vero del 2026-08-20, per nome.

        Entro la finestra il motore rende TUTTO a prescindere dalla politica: qualunque
        risposta che parli di rimborso senza nominare quella finestra sta mentendo a chi
        legge la pagina prima di pagare.
        """
        from fase111_cancellazione import calcola_rimborso
        POLITICHE, _POLITICA_IT = self._politiche()
        for nome in sorted(POLITICHE):
            with self.subTest(politica=nome):
                r = calcola_rimborso(10000, 10, politica=nome, entro_ripensamento=True)
                self.assertEqual(
                    10000, r["rimborso_cents"],
                    "premessa cambiata: entro la finestra il motore NON rende piu' tutto "
                    "sulla politica %r. Allora e' questa guardia a dover cambiare, non la "
                    "FAQ" % nome)
                testo = _POLITICA_IT[nome]
                self.assertIn(
                    "48 ore", testo,
                    "la risposta pubblica per %r non nomina la finestra di ripensamento, "
                    "mentre il motore entro quella finestra restituisce il 100%%: la pagina "
                    "dice il falso a chi sta per pagare. Testo: %r" % (nome, testo))

    def test_I_GIORNI_scritti_nella_FAQ_sono_quelli_VERI_degli_scaglioni(self):
        """⛔ I numeri della pagina si RICAVANO dal motore, non si ricopiano.

        Ogni soglia in giorni che il motore usa per rendere il 100% o la meta' deve
        comparire nella risposta pubblica. Se qualcuno sposta uno scaglione e dimentica la
        pagina, questa diventa rossa lo stesso giorno.
        """
        import re
        POLITICHE, _POLITICA_IT = self._politiche()
        for nome in sorted(POLITICHE):
            with self.subTest(politica=nome):
                soglie = [s for s, bps in POLITICHE[nome].scaglioni if bps > 0 and s > 0]
                if not soglie:
                    continue           # `non_rimborsabile`: nessuna soglia da dichiarare
                testo = _POLITICA_IT[nome]
                numeri = set(int(n) for n in re.findall(r"\d+", testo))
                for s in soglie:
                    self.assertIn(
                        s, numeri,
                        "la politica %r rende qualcosa fino a %d giorni prima dell'arrivo, "
                        "ma quel numero non compare nella risposta pubblica: chi legge non "
                        "puo' sapere entro quando cancellare. Testo: %r"
                        % (nome, s, testo))

    def test_la_FAQ_generata_MOSTRA_la_risposta_giusta_alla_domanda_giusta(self):
        """Il cablaggio (modo di rompersi n. 2): il testo puo' essere giusto e non arrivare
        mai in pagina. Qui si guarda la FAQ VERA prodotta da `genera_faq`."""
        POLITICHE, _POLITICA_IT = self._politiche()
        for nome in sorted(POLITICHE):
            with self.subTest(politica=nome):
                det = dict(DETTAGLIO)
                det["politica_cancellazione"] = nome
                rap = valuta_annuncio(det)
                voci = [v for v in genera_faq(rap, det)
                        if "cancellare" in v.get("q", "").lower()]
                self.assertTrue(
                    voci, "la FAQ non contiene piu' la domanda sulla cancellazione per %r: "
                          "il testo giusto non serve a niente se non arriva in pagina" % nome)
                self.assertEqual(
                    _POLITICA_IT[nome], voci[0]["a"],
                    "in pagina finisce una risposta diversa da quella dichiarata per %r"
                    % nome)


if __name__ == "__main__":
    unittest.main(verbosity=2)
