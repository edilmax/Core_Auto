"""Test dedicato di fase177: il primo occhio del Giudice sulle righe dello storno della penale."""
import os
import shutil
import tempfile
import unittest

from fase177_financial_controller import crea_financial_controller


class _Registro:
    """Registro dei bonifici finto: righe in memoria, e restituzione che riesce o no a comando."""

    def __init__(self, righe=(), restituisce=True):
        self.righe = {pid: minori for pid, minori in righe}
        self.restituisce = restituisce

    def elenca(self, host_id, stato=None, valuta=None):
        return [{"prenotazione_id": p, "minori": m} for p, m in self.righe.items()]

    def imposta_importo(self, pid, minori, solo_se_stato=None):
        self.righe[pid] = minori
        return True

    def rimuovi(self, pid, solo_se_stato=None):
        self.righe.pop(pid, None)
        return True

    def registra_maturato(self, pid, host_id, minori, valuta):
        return self.restituisce


class TestStornoDellaPenale(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.fc = crea_financial_controller(os.path.join(self.dir, "fin.db"))
        self.fc.inizializza_schema()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _penale(self, payout):
        return self.fc.processa_penale(riferimento="R1", host_id="h1", penale_cents=3000,
                                       valuta="EUR", payout=payout)

    def test_penale_gia_in_storno_lo_dice(self):
        vuoto = _Registro()
        nota = self._penale(vuoto)["nota_id"]
        self.fc.storna_penale(nota_id=nota, payout=vuoto)
        esito = self._penale(vuoto)
        self.assertIs(esito["stornata"], True)
        self.assertEqual(esito["offset_cents"], 0)

    def test_a_meta_solo_se_la_restituzione_non_e_riuscita(self):
        nota = self._penale(_Registro([("P1", 5000)]))["nota_id"]
        self.assertIs(self.fc.storna_penale(nota_id=nota, payout=_Registro(restituisce=False))["a_meta"],
                      True)
        self.assertIs(self.fc.storna_penale(nota_id=nota, payout=_Registro(restituisce=True))["a_meta"],
                      False)

    def _prenotazione_incassata(self, rif):
        for tipo, importo in (("incasso", 10000), ("commissione", 1000)):
            self.assertIsNotNone(self.fc.movimento(tipo=tipo, riferimento=rif, soggetto="host:h1",
                                                   importo_cents=importo, valuta="EUR", causale="x"))

    def _tipi(self, rif):
        return [m["tipo"] for m in self.fc.movimenti(rif)]

    def test_PY1_crash_fra_le_due_righe_si_completa_ritentando(self):
        self._prenotazione_incassata("RC")
        vero = self.fc.movimento

        def muore_alla_seconda(**kw):
            if kw["tipo"] == "storno_commissione":
                raise RuntimeError("processo morto")
            return vero(**kw)

        self.fc.movimento = muore_alla_seconda
        with self.assertRaises(RuntimeError):
            self.fc.storna_prenotazione(riferimento="RC")
        del self.fc.movimento
        self.assertNotIn("storno_commissione", self._tipi("RC"))        # premessa
        self.fc.storna_prenotazione(riferimento="RC")
        tipi = self._tipi("RC")
        self.assertEqual((tipi.count("debito_all_ospite"), tipi.count("storno_commissione")), (1, 1))

    # 1 gennaio 2026, 00:30 in Italia: per l'ora di Greenwich e' ancora il 31 dicembre 2025
    _CAPODANNO = 1767223800

    def test_PY6_la_ritenuta_di_capodanno_sta_nell_anno_italiano(self):
        self.fc._now = lambda: self._CAPODANNO
        self.fc.movimento(tipo="ritenuta", riferimento="RT", soggetto="host:h1", importo_cents=100,
                          valuta="EUR", causale="ritenuta base=500")
        self.assertEqual(self.fc.ritenute_anno(2026)["mesi"], {"2026-01": {"EUR": 100}})
        self.assertEqual(self.fc.ritenute_anno(2025)["mesi"], {})

    def test_PY6_l_incasso_di_capodanno_sta_nell_anno_italiano_per_dac7(self):
        self.fc._now = lambda: self._CAPODANNO
        self.fc.movimento(tipo="incasso", riferimento="RI", soggetto="host:h1", importo_cents=100,
                          valuta="EUR", causale="x")
        self.assertIn("h1", self.fc.aggrega_dac7(2026))
        self.assertNotIn("h1", self.fc.aggrega_dac7(2025))

    def test_PY1_ripetere_a_lavoro_completo_non_raddoppia(self):
        self._prenotazione_incassata("RD")
        self.assertIs(self.fc.storna_prenotazione(riferimento="RD")["gia_fatto"], False)
        self.assertIs(self.fc.storna_prenotazione(riferimento="RD")["gia_fatto"], True)
        tipi = self._tipi("RD")
        self.assertEqual((tipi.count("debito_all_ospite"), tipi.count("storno_commissione")), (1, 1))

    def test_storno_entrato_a_meta_giro_lascia_il_debito_com_era(self):
        self._penale(_Registro())
        risposte = iter([False, True])
        self.fc._storno_partito = lambda nota_id: next(risposte)
        self.fc.riscuoti_debiti(host_id="h1", payout=_Registro([("P1", 1000), ("P2", 1000)]))
        debito = self.fc.debiti_host("h1")[0]
        self.assertEqual((debito["stato"], debito["residuo_cents"]), ("aperto", 3000))


if __name__ == "__main__":
    unittest.main()
