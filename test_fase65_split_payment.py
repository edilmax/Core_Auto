"""
Test Fase 65 - Split-payment di gruppo.

Copre: riparto equo esatto (conservazione al centesimo), creazione conto (equo/importi/
fail-closed), pagamento quote + completamento, idempotenza, partecipante ignoto, conto
non aperto, scadenza, ridistribuzione su rinuncia (esatta), annullamento, robustezza, e
stress concorrente (tutti pagano -> raccolto == totale, completato una volta) 10x.
"""
import os
import shutil
import tempfile
import threading
import unittest

from fase65_split_payment import (
    GestoreSplit, VoceRidistribuzione, crea_gestore_split, riparti_equo,
)


class TestRipartoEquo(unittest.TestCase):
    def test_conservazione_esatta(self):
        for tot, n in ((10000, 3), (10001, 7), (1, 4), (99999, 13), (100, 3)):
            quote = riparti_equo(tot, n)
            self.assertEqual(len(quote), n)
            self.assertEqual(sum(quote), tot)              # zero centesimi persi
            self.assertLessEqual(max(quote) - min(quote), 1)  # equo

    def test_invalido(self):
        self.assertEqual(riparti_equo(-1, 3), [])
        self.assertEqual(riparti_equo(100, 0), [])
        self.assertEqual(riparti_equo(10.0, 3), [])


class TestCreazione(unittest.TestCase):
    def setUp(self):
        self.g = crea_gestore_split()

    def test_crea_equo(self):
        cid = self.g.crea_conto("pren1", "casa", 10000, ["a", "b", "c"])
        st = self.g.stato_conto(cid)
        dovuti = sorted(q["dovuto_cents"] for q in st["quote"])
        self.assertEqual(dovuti, [3333, 3333, 3334])
        self.assertEqual(sum(dovuti), 10000)

    def test_crea_importi_custom(self):
        cid = self.g.crea_conto("pren1", "casa", 10000, ["a", "b"],
                                metodo="importi", importi={"a": 7000, "b": 3000})
        st = self.g.stato_conto(cid)
        self.assertEqual({q["partecipante_id"]: q["dovuto_cents"] for q in st["quote"]},
                         {"a": 7000, "b": 3000})

    def test_importi_somma_sbagliata_rifiutato(self):
        self.assertIsNone(self.g.crea_conto("p", "casa", 10000, ["a", "b"],
                          metodo="importi", importi={"a": 7000, "b": 2000}))

    def test_input_invalido(self):
        self.assertIsNone(self.g.crea_conto("", "casa", 10000, ["a"]))
        self.assertIsNone(self.g.crea_conto("p", "casa", 0, ["a"]))
        self.assertIsNone(self.g.crea_conto("p", "casa", 10.0, ["a"]))
        self.assertIsNone(self.g.crea_conto("p", "casa", 100, []))
        self.assertIsNone(self.g.crea_conto("p", "casa", 100, ["a", "a"]))  # duplicati


class TestPagamento(unittest.TestCase):
    def setUp(self):
        self.g = crea_gestore_split()
        self.cid = self.g.crea_conto("pren1", "casa", 9000, ["a", "b", "c"])

    def test_pagamento_e_completamento(self):
        self.assertFalse(self.g.registra_pagamento(self.cid, "a", idem_key="ka").completato)
        self.g.registra_pagamento(self.cid, "b", idem_key="kb")
        e = self.g.registra_pagamento(self.cid, "c", idem_key="kc")
        self.assertTrue(e.completato)
        st = self.g.stato_conto(self.cid)
        self.assertEqual(st["raccolto_cents"], 9000)
        self.assertEqual(st["mancante_cents"], 0)
        self.assertTrue(st["pronto_per_escrow"])

    def test_idempotente(self):
        self.g.registra_pagamento(self.cid, "a", idem_key="ka")
        e = self.g.registra_pagamento(self.cid, "a", idem_key="ka2")
        self.assertTrue(e.idempotente)
        self.assertEqual(self.g.stato_conto(self.cid)["raccolto_cents"], 3000)

    def test_partecipante_ignoto(self):
        e = self.g.registra_pagamento(self.cid, "zzz", idem_key="k")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "partecipante_ignoto")

    def test_conto_inesistente(self):
        e = self.g.registra_pagamento("mai", "a", idem_key="k")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "conto_inesistente")

    def test_scaduto(self):
        t = {"v": 1000}
        g = crea_gestore_split(orologio=lambda: t["v"])
        cid = g.crea_conto("p", "casa", 6000, ["a", "b"], scadenza=2000)
        t["v"] = 3000
        e = g.registra_pagamento(cid, "a", idem_key="k")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "scaduto")


class TestRidistribuzione(unittest.TestCase):
    def test_chi_paga_copre(self):
        g = crea_gestore_split()
        cid = g.crea_conto("p", "casa", 9000, ["a", "b", "c"])  # 3000 ciascuno
        g.registra_pagamento(cid, "a", idem_key="ka")
        g.registra_pagamento(cid, "b", idem_key="kb")           # c non paga (3000)
        piano = g.ridistribuisci_mancante(cid)
        self.assertTrue(piano["coperto"])
        self.assertEqual(piano["mancante_cents"], 3000)
        self.assertEqual(sum(v.extra_cents for v in piano["voci"]), 3000)  # esatto
        self.assertEqual({v.partecipante_id for v in piano["voci"]}, {"a", "b"})

    def test_nessun_pagatore_non_coperto(self):
        g = crea_gestore_split()
        cid = g.crea_conto("p", "casa", 9000, ["a", "b", "c"])
        piano = g.ridistribuisci_mancante(cid)
        self.assertFalse(piano["coperto"])

    def test_completato_niente_da_ridistribuire(self):
        g = crea_gestore_split()
        cid = g.crea_conto("p", "casa", 6000, ["a", "b"])
        g.registra_pagamento(cid, "a", idem_key="ka")
        g.registra_pagamento(cid, "b", idem_key="kb")
        self.assertFalse(g.ridistribuisci_mancante(cid)["coperto"])

    def test_voci_sono_dataclass(self):
        g = crea_gestore_split()
        cid = g.crea_conto("p", "casa", 9000, ["a", "b", "c"])
        g.registra_pagamento(cid, "a", idem_key="ka")
        piano = g.ridistribuisci_mancante(cid)
        self.assertTrue(all(isinstance(v, VoceRidistribuzione) for v in piano["voci"]))


class TestAnnulla(unittest.TestCase):
    def test_annulla_blocca_pagamenti(self):
        g = crea_gestore_split()
        cid = g.crea_conto("p", "casa", 6000, ["a", "b"])
        self.assertTrue(g.annulla(cid))
        e = g.registra_pagamento(cid, "a", idem_key="k")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "conto_non_aperto")


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        g = crea_gestore_split()
        for bad in (None, 123, [], ""):
            try:
                g.crea_conto(bad, bad, bad, bad)
                g.registra_pagamento(bad, bad, idem_key="k")
                g.stato_conto(bad)
                g.ridistribuisci_mancante(bad)
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")


class TestStress(unittest.TestCase):
    def test_pagamenti_concorrenti_10x(self):
        for rip in range(10):
            d = tempfile.mkdtemp()
            try:
                g = crea_gestore_split(os.path.join(d, f"s{rip}.db"))
                partecipanti = ["u%d" % i for i in range(12)]
                cid = g.crea_conto("p", "casa", 12000, partecipanti)
                esiti = []
                lock = threading.Lock()

                def paga(p):
                    e = g.registra_pagamento(cid, p, idem_key="idem-%s" % p)
                    with lock:
                        esiti.append(e)

                th = [threading.Thread(target=paga, args=(p,)) for p in partecipanti]
                for t in th:
                    t.start()
                for t in th:
                    t.join()
                st = g.stato_conto(cid)
                self.assertEqual(st["raccolto_cents"], 12000)   # conservazione esatta
                self.assertTrue(st["completato"])
                # esattamente un pagamento ha visto il completamento
                self.assertEqual(sum(1 for e in esiti if e.completato), 1)
            finally:
                shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
