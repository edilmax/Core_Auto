"""Test Fase 104 - Gateway Asia (Alipay/WeChat) + Weibo. fetch STUB: nessuna rete."""
import unittest

from fase90_marketing import GeneratoreContenuti
from fase104_gateway_asia import (CanaleWeibo, ProviderAsia, costruisci_params_asia,
                                  crea_canale_weibo_da_env, crea_provider_asia_da_env)

POST = GeneratoreContenuti().crea("guest", "it")
DATI = {"prezzo_guest_cents": 11200, "commissione_cents": 1500,
        "host_account": "acct_1", "metodo": "alipay", "valuta": "cny"}


class TestParamsAsia(unittest.TestCase):
    def test_alipay_split_invariato(self):
        p = costruisci_params_asia(11200, 1500, "acct_1", "alipay")
        self.assertEqual(p["payment_method_types[0]"], "alipay")
        self.assertEqual(p["payment_intent_data[application_fee_amount]"], "1500")
        self.assertEqual(p["payment_intent_data[transfer_data][destination]"], "acct_1")

    def test_wechat_client_web(self):
        p = costruisci_params_asia(11200, 1500, "acct_1", "wechat_pay")
        self.assertEqual(p["payment_method_options[wechat_pay][client]"], "web")

    def test_metodo_invalido(self):
        self.assertIsNone(costruisci_params_asia(11200, 1500, "acct_1", "boleto"))


class TestProviderAsia(unittest.TestCase):
    def test_crea_link_alipay(self):
        visti = {}
        p = ProviderAsia("sk", fetch=lambda u, b, h: visti.update(b=b) or {"url": "https://pay/cn"})
        self.assertEqual(p.crea_link(DATI), "https://pay/cn")
        self.assertIn(b"alipay", visti["b"])

    def test_gated_e_isolato(self):
        self.assertIsNone(ProviderAsia("").crea_link(DATI))
        self.assertIsNone(crea_provider_asia_da_env({}))
        self.assertIsNone(ProviderAsia("sk", fetch=lambda *a: (_ for _ in ()).throw(RuntimeError())).crea_link(DATI))


class TestWeibo(unittest.TestCase):
    def test_pubblica_ok(self):
        c = CanaleWeibo("TOK", fetch=lambda u, d: {"idstr": "9"})
        self.assertTrue(c.pubblica(POST))

    def test_gated(self):
        self.assertFalse(CanaleWeibo("").pubblica(POST))
        self.assertIsNone(crea_canale_weibo_da_env({}))
        self.assertIsNotNone(crea_canale_weibo_da_env({"WEIBO_ACCESS_TOKEN": "t"},
                                                      fetch=lambda *a: {}))

    def test_isolato(self):
        def boom(*a):
            raise RuntimeError("weibo giu")
        self.assertFalse(CanaleWeibo("TOK", fetch=boom).pubblica(POST))


if __name__ == "__main__":
    unittest.main()
