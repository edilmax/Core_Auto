"""
Test Fase 76 - Viral Loop Engine.

Copre: codice idempotente, registrazione referee (crediti a entrambi), anti-frode
(auto-referral, dedup referee, firma falsificata, codice inesistente), credito
disponibile, uso credito (riduzione del dovuto, non-cashabile, mai sotto zero/oltre
dovuto, FIFO scadenza, crediti scaduti esclusi), robustezza, stress concorrente.
"""
import os
import shutil
import tempfile
import threading
import unittest

from fase76_viral_loop import ViralLoopEngine, crea_viral_loop

SEG = b"0123456789abcdef0123456789abcdef"
GIORNO = 86400


def _eng(clock=None):
    return crea_viral_loop(":memory:", SEG, credito_referente_cents=5000,
                           credito_referee_cents=2000, orologio=clock)


class TestCodice(unittest.TestCase):
    def test_idempotente(self):
        e = _eng()
        c1 = e.genera_codice("host1")
        c2 = e.genera_codice("host1")
        self.assertEqual(c1, c2)

    def test_tipi_distinti(self):
        e = _eng()
        self.assertNotEqual(e.genera_codice("u1", tipo="host"),
                            e.genera_codice("u1", tipo="guest"))

    def test_input_invalido(self):
        e = _eng()
        self.assertIsNone(e.genera_codice(""))
        self.assertIsNone(e.genera_codice("u1", tipo="alieno"))


class TestReferral(unittest.TestCase):
    def test_crediti_a_entrambi(self):
        e = _eng()
        cod = e.genera_codice("host1")
        r = e.registra_referee(cod, "host2")
        self.assertTrue(r.ok)
        self.assertEqual(r.credito_referente_cents, 5000)
        self.assertEqual(r.credito_referee_cents, 2000)
        self.assertEqual(e.credito_disponibile("host1"), 5000)
        self.assertEqual(e.credito_disponibile("host2"), 2000)

    def test_auto_referral_rifiutato(self):
        e = _eng()
        cod = e.genera_codice("host1")
        r = e.registra_referee(cod, "host1")
        self.assertFalse(r.ok)
        self.assertEqual(r.motivo, "auto_referral")

    def test_dedup_referee(self):
        e = _eng()
        cod = e.genera_codice("host1")
        e.registra_referee(cod, "host2")
        r = e.registra_referee(cod, "host2")        # stesso referee, di nuovo
        self.assertFalse(r.ok)
        self.assertEqual(r.motivo, "gia_referito")
        self.assertEqual(e.credito_disponibile("host2"), 2000)   # non raddoppia

    def test_firma_falsificata(self):
        e = _eng()
        r = e.registra_referee("codice.inventato", "host2")
        self.assertFalse(r.ok)
        self.assertEqual(r.motivo, "firma_invalida")

    def test_codice_firmato_ma_non_registrato(self):
        e = _eng()
        # codice con firma valida ma mai salvato nel registro
        altro = ViralLoopEngine.__new__(ViralLoopEngine)  # non serve; usiamo la firma
        cod_valido_non_salvato = e._firma.codifica({"ref": "fantasma", "tipo": "host",
                                                    "n": "abc"})
        r = e.registra_referee(cod_valido_non_salvato, "host2")
        self.assertFalse(r.ok)
        self.assertEqual(r.motivo, "codice_inesistente")

    def test_referente_accumula_da_piu_referee(self):
        e = _eng()
        cod = e.genera_codice("host1")
        e.registra_referee(cod, "a")
        e.registra_referee(cod, "b")
        self.assertEqual(e.credito_disponibile("host1"), 10000)   # 5000 x2


class TestUsoCredito(unittest.TestCase):
    def test_riduce_dovuto(self):
        e = _eng()
        cod = e.genera_codice("host1")
        e.registra_referee(cod, "host2")            # host1 ha 5000
        r = e.usa_credito("host1", 8000)
        self.assertEqual(r["scontato_cents"], 5000)
        self.assertEqual(r["da_pagare_cents"], 3000)
        self.assertEqual(e.credito_disponibile("host1"), 0)

    def test_non_oltre_il_dovuto(self):
        e = _eng()
        cod = e.genera_codice("host1")
        e.registra_referee(cod, "host2")            # 5000
        r = e.usa_credito("host1", 2000)            # dovuto < credito
        self.assertEqual(r["scontato_cents"], 2000)
        self.assertEqual(r["da_pagare_cents"], 0)
        self.assertEqual(e.credito_disponibile("host1"), 3000)   # residuo resta

    def test_non_cashabile_nessun_payout(self):
        # non esiste alcun metodo per ritirare: solo usa_credito riduce un dovuto
        e = _eng()
        self.assertFalse(hasattr(e, "ritira_credito"))
        self.assertFalse(hasattr(e, "payout"))

    def test_credito_scaduto_escluso(self):
        t = {"v": 1000}
        e = _eng(clock=lambda: t["v"])
        cod = e.genera_codice("host1")
        e.registra_referee(cod, "host2")            # scadenza = 1000 + 365g
        t["v"] = 1000 + 366 * GIORNO
        self.assertEqual(e.credito_disponibile("host1"), 0)
        self.assertEqual(e.usa_credito("host1", 5000)["scontato_cents"], 0)

    def test_dovuto_invalido(self):
        e = _eng()
        self.assertEqual(e.usa_credito("host1", 0)["scontato_cents"], 0)
        self.assertEqual(e.usa_credito("host1", -5)["scontato_cents"], 0)


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        e = _eng()
        for bad in (None, 123, ""):
            try:
                e.genera_codice(bad)
                e.registra_referee(bad, bad)
                e.credito_disponibile(bad)
                e.usa_credito(bad, bad)
            except Exception as ex:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {ex}")


class TestStress(unittest.TestCase):
    def test_referee_concorrenti_10x(self):
        for rip in range(10):
            d = tempfile.mkdtemp()
            try:
                e = crea_viral_loop(os.path.join(d, f"v{rip}.db"), SEG,
                                    credito_referente_cents=5000)
                cod = e.genera_codice("host1")
                ok = []
                lock = threading.Lock()

                def reg(i):
                    r = e.registra_referee(cod, "ref%d" % i)
                    with lock:
                        ok.append(r.ok)

                th = [threading.Thread(target=reg, args=(i,)) for i in range(15)]
                for t in th:
                    t.start()
                for t in th:
                    t.join()
                self.assertEqual(sum(1 for x in ok if x), 15)
                self.assertEqual(e.credito_disponibile("host1"), 15 * 5000)
            finally:
                shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
