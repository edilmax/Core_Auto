"""
Test Fase 73 - Firma Agile (crypto-agility + anti-downgrade + ibrida).

Copre: round-trip HMAC, manomissione payload/firma, chiave diversa, token malformati,
ALGORITHM-CONFUSION (alg:none / alg ignoto / duplicato), ANTI-DOWNGRADE (richiesti
mancanti), firma IBRIDA (entrambe valide / una rotta), algoritmo che solleva (isolato),
crypto-agility (swap algoritmo), determinismo, costruzione invalida.
"""
import base64
import json
import unittest

from fase73_firma_agile import (
    AlgoritmoHMAC, FirmaAgile, firma_ibrida, firma_solo_hmac,
)

SEG = b"0123456789abcdef0123456789abcdef"
SEG2 = b"ffffffffffffffffffffffffffffffff"


def _ALG2():
    # secondo algoritmo "indipendente" (HMAC con chiave/nome diversi) per testare ibrido
    return AlgoritmoHMAC(SEG2, nome="alg2")


class TestBase(unittest.TestCase):
    def test_round_trip(self):
        f = firma_solo_hmac(SEG)
        t = f.codifica({"prezzo": 1000, "x": "y"})
        self.assertEqual(f.decodifica(t)["prezzo"], 1000)

    def test_manomissione_payload(self):
        f = firma_solo_hmac(SEG)
        t = f.codifica({"prezzo": 1000})
        b64, algsigs = t.split(".")
        payload = json.loads(base64.urlsafe_b64decode(b64))
        payload["prezzo"] = 1
        b64f = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode()
        self.assertIsNone(f.decodifica(b64f + "." + algsigs))

    def test_manomissione_firma(self):
        f = firma_solo_hmac(SEG)
        t = f.codifica({"a": 1})
        self.assertIsNone(f.decodifica(t[:-2] + ("aa" if not t.endswith("aa") else "bb")))

    def test_chiave_diversa(self):
        t = firma_solo_hmac(SEG).codifica({"a": 1})
        self.assertIsNone(firma_solo_hmac(SEG2).decodifica(t))

    def test_token_malformati(self):
        f = firma_solo_hmac(SEG)
        for bad in (None, 123, "", "senza-punto", "a.b.c", "b64.", ".sig",
                    "b64.alg_senza_sig"):
            self.assertIsNone(f.decodifica(bad))


class TestConfusion(unittest.TestCase):
    def test_alg_none_rifiutato(self):
        f = firma_solo_hmac(SEG)
        t = f.codifica({"a": 1})
        b64 = t.split(".")[0]
        self.assertIsNone(f.decodifica(b64 + ".none:00"))

    def test_alg_ignoto_rifiutato(self):
        f = firma_solo_hmac(SEG)
        t = f.codifica({"a": 1})
        b64 = t.split(".")[0]
        self.assertIsNone(f.decodifica(b64 + ".sconosciuto:abcd"))

    def test_duplicato_rifiutato(self):
        f = firma_solo_hmac(SEG)
        t = f.codifica({"a": 1})
        b64, algsigs = t.split(".")
        self.assertIsNone(f.decodifica(b64 + "." + algsigs + "+" + algsigs))


class TestAntiDowngrade(unittest.TestCase):
    def test_richiesto_mancante_rifiutato(self):
        # firma con HMAC+alg2, entrambi richiesti; un token con solo HMAC -> downgrade
        ibr = firma_ibrida(SEG, _ALG2())
        solo = firma_solo_hmac(SEG)
        t_solo = solo.codifica({"a": 1})
        self.assertIsNone(ibr.decodifica(t_solo))     # manca alg2 -> rifiutato

    def test_consentito_ma_non_richiesto_ok(self):
        # accetta HMAC, ma se presente anche alg2 dev'essere valido
        f = FirmaAgile([AlgoritmoHMAC(SEG), _ALG2()], richiesti=["hmac-sha256"])
        t = f.codifica({"a": 1})        # firma con entrambi
        self.assertIsNotNone(f.decodifica(t))


class TestIbrida(unittest.TestCase):
    def test_entrambe_valide(self):
        ibr = firma_ibrida(SEG, _ALG2())
        t = ibr.codifica({"a": 1})
        self.assertEqual(len(t.split(".")[1].split("+")), 2)   # due firme
        self.assertIsNotNone(ibr.decodifica(t))

    def test_una_firma_rotta_rifiuta(self):
        ibr = firma_ibrida(SEG, _ALG2())
        # verificatore con SEG2 diverso per alg2 -> la firma alg2 non combacia
        ibr_diverso = firma_ibrida(SEG, AlgoritmoHMAC(b"x" * 32, nome="alg2"))
        t = ibr.codifica({"a": 1})
        self.assertIsNone(ibr_diverso.decodifica(t))


class TestIsolamento(unittest.TestCase):
    def test_algoritmo_che_solleva(self):
        class AlgBoom:
            nome = "boom"
            def firma(self, msg):
                return "00"
            def verifica(self, msg, sig):
                raise RuntimeError("hw crypto giu'")
        f = FirmaAgile([AlgBoom()])
        t = f.codifica({"a": 1})
        self.assertIsNone(f.decodifica(t))     # isolato -> rifiuto, non crash


class TestAgilita(unittest.TestCase):
    def test_swap_algoritmo(self):
        # crypto-agility: stesso payload, algoritmo diverso, protocollo identico
        f1 = firma_solo_hmac(SEG, nome="hmac-sha256")
        f2 = firma_solo_hmac(SEG, nome="hmac-v2")
        self.assertIn("hmac-sha256", f1.codifica({"a": 1}))
        self.assertIn("hmac-v2", f2.codifica({"a": 1}))

    def test_determinismo(self):
        f = firma_solo_hmac(SEG)
        self.assertEqual(f.codifica({"a": 1, "b": 2}), f.codifica({"b": 2, "a": 1}))

    def test_algoritmi_proprieta(self):
        self.assertEqual(firma_ibrida(SEG, _ALG2()).algoritmi, ["alg2", "hmac-sha256"])


class TestCostruzione(unittest.TestCase):
    def test_nome_invalido(self):
        class AlgCattivo:
            nome = "ha:due:punti"
            def firma(self, m): return "0"
            def verifica(self, m, s): return True
        with self.assertRaises(ValueError):
            FirmaAgile([AlgCattivo()])

    def test_nessun_algoritmo(self):
        with self.assertRaises(ValueError):
            FirmaAgile([])

    def test_segreto_corto(self):
        with self.assertRaises(ValueError):
            AlgoritmoHMAC(b"corto")

    def test_richiesti_incoerenti(self):
        with self.assertRaises(ValueError):
            FirmaAgile([AlgoritmoHMAC(SEG)], richiesti=["inesistente"])


if __name__ == "__main__":
    unittest.main()
