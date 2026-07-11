"""
Test Fase 89 - Jurisdiction B2B Radar & Outreach (PRIMO MICRO-TEST).

Dimostra, in modo deterministico e SENZA rete: ricerca (fonte stub) + gate giurisdizione +
commissione auto -5% + email "Prima Emilia" nella lingua del destinatario + invio (stub).
Verifica che NON si invii dove non è permesso (es. UE) e che l'opt-out sia sovrano.
"""
import unittest

from fase89_jurisdiction_outreach import (
    Contatto, FonteAPIUfficiale, FonteStub, MotoreRadarOutreach, crea_fonte_api,
    commissione_sotto_concorrenza, componi_email_prima_emilia,
)


class TestFonteAPIUfficiale(unittest.TestCase):
    """Fonte REALE testata con fetch STUB: nessuna rete, nessuno scraping."""
    PAYLOAD = {"results": [
        {"name": "Sunset Inn", "email": "owner@sunset.us", "country": "US",
         "is_public_business": True, "source": "directory_b2b"},
        {"name": "Senza Email", "country": "US", "is_public_business": True},  # scartato
        {"name": "Privato", "email": "x@priv.us", "country": "US",
         "is_public_business": False},                                          # scartato (no pubblico)
    ]}

    def test_mappa_solo_business_pubblici(self):
        f = FonteAPIUfficiale("https://api.dir/b2b", "K", fetch=lambda url: self.PAYLOAD)
        res = f.cerca(paese="US")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].email, "owner@sunset.us")
        self.assertTrue(res[0].contatto_pubblico_business)

    def test_passa_key_e_paese_nella_query(self):
        visti = {}
        f = FonteAPIUfficiale("https://api.dir/b2b", "SEGRETA",
                              fetch=lambda url: visti.update(url=url) or self.PAYLOAD)
        f.cerca(paese="us", limit=10)
        self.assertIn("country=US", visti["url"])
        self.assertIn("key=SEGRETA", visti["url"])

    def test_gated_senza_chiave(self):
        self.assertEqual(crea_fonte_api("https://api.dir", "").cerca(paese="US"), [])
        self.assertEqual(crea_fonte_api("", "K").cerca(paese="US"), [])

    def test_fetch_solleva_isolato(self):
        def boom(url):
            raise RuntimeError("api giu'")
        f = FonteAPIUfficiale("https://api.dir", "K", fetch=boom)
        self.assertEqual(f.cerca(paese="US"), [])        # [] non crash

    def test_integrazione_motore(self):
        f = FonteAPIUfficiale("https://api.dir", "K", fetch=lambda url: self.PAYLOAD)
        inviate = []
        m = MotoreRadarOutreach(giurisdizioni_permesse=("US",))
        rep = m.esegui(f, paese="US", concorrenti_bps={"booking": 2000},
                       invia=lambda e, o, c, l: inviate.append(e) or True)
        self.assertEqual(rep["inviati"], 1)              # solo il business pubblico US
        self.assertEqual(inviate, ["owner@sunset.us"])


class TestCommissioneSottoConcorrenza(unittest.TestCase):
    def test_cinque_percento_sotto(self):
        # colossi: min 2000 (20%) -> noi 1500 (15%) = 5% in meno
        self.assertEqual(commissione_sotto_concorrenza(
            {"booking": 2000, "airbnb": 2200, "expedia": 2500}), 1500)

    def test_floor_e_cap(self):
        self.assertEqual(commissione_sotto_concorrenza({"x": 400}, floor_bps=300), 300)
        self.assertEqual(commissione_sotto_concorrenza({"x": 9000}, cap_bps=2000), 2000)

    def test_nessun_benchmark_default(self):
        self.assertEqual(commissione_sotto_concorrenza({}), 1000)        # default = 10% a regime
        self.assertEqual(commissione_sotto_concorrenza({"x": "abc"}), 1000)


class TestEmailLocalizzata(unittest.TestCase):
    def test_lingua_e_contenuto(self):
        c = Contatto("Hotel Sol", "info@sol.mx", "MX", contatto_pubblico_business=True)
        lng, ogg, corpo = componi_email_prima_emilia(c, 1500, link_opt_out="https://x/stop")
        self.assertEqual(lng, "es")                      # MX -> spagnolo
        self.assertIn("15%", corpo)
        self.assertIn("Prima Emilia", corpo)
        self.assertIn("https://x/stop", corpo)           # opt-out presente

    def test_opt_out_obbligatorio(self):
        c = Contatto("H", "a@b.us", "US", contatto_pubblico_business=True)
        self.assertIsNone(componi_email_prima_emilia(c, 1500, link_opt_out=""))


class TestRadarOutreach(unittest.TestCase):
    def setUp(self):
        # fonte lecita simulata: 1 US (business pubblico), 1 IT (UE), 1 US non-pubblico
        self.fonte = FonteStub([
            Contatto("Sunset Inn", "owner@sunset.us", "US", contatto_pubblico_business=True),
            Contatto("Hotel Roma", "info@roma.it", "IT", contatto_pubblico_business=True),
            Contatto("Private LLC", "x@priv.us", "US", contatto_pubblico_business=False),
        ])
        self.inviate = []
        self.invia = lambda email, ogg, corpo, lng: (
            self.inviate.append((email, lng)) or True)

    def test_invia_solo_dove_legale(self):
        m = MotoreRadarOutreach(giurisdizioni_permesse=("US",))
        rep = m.esegui(self.fonte, paese="US", concorrenti_bps={"booking": 2000},
                       invia=self.invia)
        # solo il contatto US business pubblico riceve l'email
        self.assertEqual(rep["inviati"], 1)
        self.assertEqual(self.inviate[0][0], "owner@sunset.us")
        self.assertEqual(rep["nostra_commissione_bps"], 1500)   # 15%

    def test_ue_bloccata(self):
        # cerco in IT (UE) ma IT non è nell'allow-list -> nessun invio
        m = MotoreRadarOutreach(giurisdizioni_permesse=("US",))
        rep = m.esegui(self.fonte, paese="IT", concorrenti_bps={"booking": 2000},
                       invia=self.invia)
        self.assertEqual(rep["inviati"], 0)
        self.assertEqual(self.inviate, [])
        self.assertIn("giurisdizione_non_permessa", rep["motivi"])

    def test_opt_out_sovrano(self):
        m = MotoreRadarOutreach(giurisdizioni_permesse=("US",))
        m.opt_out("owner@sunset.us")
        rep = m.esegui(self.fonte, paese="US", concorrenti_bps={"booking": 2000},
                       invia=self.invia)
        self.assertEqual(rep["inviati"], 0)              # chi ha detto stop NON è contattato
        self.assertIn("opt_out", rep["motivi"])


if __name__ == "__main__":
    unittest.main()
