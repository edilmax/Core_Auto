"""
Test Fase 79 - Dichiarazione Vincolante.

Copre: dichiara (claim noto/ignoto, penale default/custom), ritira, dichiarazioni
attive, contestazione (claim non dichiarato -> niente; prove sufficienti -> accolta con
rimborso+penale; prove insufficienti -> respinta), idempotenza, prezzo invalido,
robustezza, stress concorrente.
"""
import os
import shutil
import tempfile
import threading
import unittest

from fase79_dichiarazione import (
    CLAIM, DichiarazioneEngine, EsitoContestazione, crea_dichiarazione,
)


class TestDichiara(unittest.TestCase):
    def setUp(self):
        self.e = crea_dichiarazione()

    def test_dichiara_default(self):
        self.assertTrue(self.e.dichiara("casa", "no_allergeni"))
        att = self.e.dichiarazioni_attive("casa")
        self.assertEqual(att, [{"claim": "no_allergeni",
                                "penale_cents": CLAIM["no_allergeni"]["penale"]}])

    def test_dichiara_penale_custom(self):
        self.e.dichiara("casa", "silenzio_garantito", penale_cents=5000)
        self.assertEqual(self.e.dichiarazioni_attive("casa")[0]["penale_cents"], 5000)

    def test_claim_ignoto(self):
        self.assertFalse(self.e.dichiara("casa", "vola"))

    def test_ritira(self):
        self.e.dichiara("casa", "pet_friendly")
        self.assertTrue(self.e.ritira("casa", "pet_friendly"))
        self.assertEqual(self.e.dichiarazioni_attive("casa"), [])

    def test_dichiara_upsert(self):
        self.e.dichiara("casa", "no_allergeni", penale_cents=10000)
        self.e.dichiara("casa", "no_allergeni", penale_cents=30000)
        self.assertEqual(self.e.dichiarazioni_attive("casa")[0]["penale_cents"], 30000)


class TestContestazione(unittest.TestCase):
    def setUp(self):
        self.e = crea_dichiarazione()
        self.e.dichiara("casa", "no_allergeni", penale_cents=20000)

    def test_accolta_con_prove(self):
        g = self.e.contesta("casa", "pren1", "no_allergeni", 12000,
                            {"certificato_medico": True})
        self.assertEqual(g.stato, "accolta")
        self.assertEqual(g.rimborso_cents, 12000)   # rimborso intero
        self.assertEqual(g.penale_cents, 20000)     # penale dichiarata

    def test_respinta_senza_prove(self):
        g = self.e.contesta("casa", "pren1", "no_allergeni", 12000, {})
        self.assertEqual(g.stato, "respinta")
        self.assertEqual(g.rimborso_cents, 0)
        self.assertEqual(g.penale_cents, 0)

    def test_prova_non_true_respinta(self):
        g = self.e.contesta("casa", "pren1", "no_allergeni", 12000,
                            {"certificato_medico": "si"})   # solo True esatto vale
        self.assertEqual(g.stato, "respinta")

    def test_non_dichiarato(self):
        # claim valido ma NON dichiarato da questo alloggio -> niente impegno
        g = self.e.contesta("casa", "pren1", "pet_friendly", 12000,
                            {"foto_pet_rifiutato": True})
        self.assertEqual(g.stato, "non_dichiarato")

    def test_idempotente(self):
        self.e.contesta("casa", "pren1", "no_allergeni", 12000,
                        {"certificato_medico": True})
        g2 = self.e.contesta("casa", "pren1", "no_allergeni", 12000,
                             {"certificato_medico": True})
        self.assertTrue(g2.idempotente)
        self.assertEqual(g2.stato, "accolta")
        self.assertEqual(g2.rimborso_cents, 12000)

    def test_claim_ignoto(self):
        self.assertEqual(self.e.contesta("casa", "p", "vola", 100, {}).stato,
                         "claim_ignoto")

    def test_prezzo_invalido(self):
        self.assertEqual(self.e.contesta("casa", "p", "no_allergeni", 0, {}).stato,
                         "prezzo_non_valido")

    def test_esito(self):
        self.e.contesta("casa", "pren1", "no_allergeni", 12000,
                        {"certificato_medico": True})
        self.assertEqual(self.e.esito("pren1", "no_allergeni")["stato"], "accolta")


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        e = crea_dichiarazione()
        for bad in (None, 123, ""):
            try:
                e.dichiara(bad, bad)
                e.contesta(bad, bad, bad, bad, bad)
                e.dichiarazioni_attive(bad)
            except Exception as ex:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {ex}")


class TestStress(unittest.TestCase):
    def test_contestazioni_concorrenti_10x(self):
        for rip in range(10):
            d = tempfile.mkdtemp()
            try:
                e = crea_dichiarazione(os.path.join(d, f"d{rip}.db"))
                e.dichiara("casa", "no_allergeni", penale_cents=20000)
                esiti = []
                lock = threading.Lock()

                def worker(i):
                    g = e.contesta("casa", "pren%d" % i, "no_allergeni", 10000,
                                   {"certificato_medico": True})
                    with lock:
                        esiti.append(g.stato)

                th = [threading.Thread(target=worker, args=(i,)) for i in range(15)]
                for t in th:
                    t.start()
                for t in th:
                    t.join()
                self.assertEqual(esiti.count("accolta"), 15)
            finally:
                shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
