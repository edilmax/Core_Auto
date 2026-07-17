"""Test Fase 169 - IndexNow. Builder puri + adapter GATED/blindato (fetch iniettabile)."""
import json
import unittest

from fase169_indexnow import (IndexNow, MAX_URL_BATCH, crea_indexnow, key_file_body,
                              payload_indexnow, urls_valide)

H = "bookinvip.com"


class TestPuri(unittest.TestCase):
    def test_key_file_body(self):
        self.assertEqual(key_file_body("  abc123 "), "abc123")
        self.assertEqual(key_file_body(None), "")

    def test_urls_valide_stesso_host_dedup(self):
        urls = ["https://bookinvip.com/affitta/roma",
                "https://bookinvip.com/affitta/roma",          # duplicato
                "https://ALTRO.com/x",                          # host diverso
                "ftp://bookinvip.com/y",                        # schema non http
                "non-un-url", 123]
        v = urls_valide(urls, H)
        self.assertEqual(v, ["https://bookinvip.com/affitta/roma"])

    def test_cap_10000(self):
        molti = ["https://bookinvip.com/p/%d" % i for i in range(MAX_URL_BATCH + 50)]
        self.assertEqual(len(urls_valide(molti, H)), MAX_URL_BATCH)

    def test_payload_struttura(self):
        p = payload_indexnow(H, "KEY", ["https://bookinvip.com/a"],
                             key_location="https://bookinvip.com/KEY.txt")
        self.assertEqual(p["host"], H)
        self.assertEqual(p["key"], "KEY")
        self.assertEqual(p["keyLocation"], "https://bookinvip.com/KEY.txt")
        self.assertEqual(p["urlList"], ["https://bookinvip.com/a"])


class TestAdapterGated(unittest.TestCase):
    def test_disattivo_senza_chiave(self):
        i = IndexNow(None, H)
        self.assertFalse(i.attivo)
        self.assertEqual(i.submit(["https://bookinvip.com/a"])["inviato"], False)
        self.assertEqual(i.submit(["https://bookinvip.com/a"])["motivo"], "disattivo")

    def test_attivo_invia_payload_giusto(self):
        catturato = {}

        def fake(url, body, headers):
            catturato["url"] = url
            catturato["body"] = json.loads(body.decode("utf-8"))
            catturato["ct"] = headers.get("Content-Type", "")
            return 200

        i = IndexNow("KEY", H, fetch=fake)
        self.assertTrue(i.attivo)
        res = i.submit(["https://bookinvip.com/affitta/roma", "https://altro.com/x"])
        self.assertEqual(res, {"inviato": True, "url": 1, "stato": 200})
        self.assertEqual(catturato["url"], "https://api.indexnow.org/indexnow")
        self.assertEqual(catturato["body"]["host"], H)
        self.assertEqual(catturato["body"]["key"], "KEY")
        self.assertEqual(catturato["body"]["urlList"], ["https://bookinvip.com/affitta/roma"])
        self.assertEqual(catturato["body"]["keyLocation"], "https://bookinvip.com/KEY.txt")
        self.assertIn("application/json", catturato["ct"])

    def test_nessun_url_valido(self):
        i = IndexNow("KEY", H, fetch=lambda *a: 200)
        self.assertEqual(i.submit(["https://altro.com/x"])["motivo"], "nessun_url_valido")

    def test_blindato_su_errore_rete(self):
        def esplode(*a):
            raise RuntimeError("rete giù")
        i = IndexNow("KEY", H, fetch=esplode)
        res = i.submit(["https://bookinvip.com/a"])          # NON deve sollevare
        self.assertEqual(res, {"inviato": False, "motivo": "errore_rete"})

    def test_factory_da_env(self):
        self.assertFalse(crea_indexnow({}).attivo)           # default OFF
        i = crea_indexnow({"INDEXNOW_KEY": "K", "INDEXNOW_HOST": H})
        self.assertTrue(i.attivo)


if __name__ == "__main__":
    unittest.main()
