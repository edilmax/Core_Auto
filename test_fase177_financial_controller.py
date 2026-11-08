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

    def test_storno_entrato_a_meta_giro_lascia_il_debito_com_era(self):
        self._penale(_Registro())
        risposte = iter([False, True])
        self.fc._storno_partito = lambda nota_id: next(risposte)
        self.fc.riscuoti_debiti(host_id="h1", payout=_Registro([("P1", 1000), ("P2", 1000)]))
        debito = self.fc.debiti_host("h1")[0]
        self.assertEqual((debito["stato"], debito["residuo_cents"]), ("aperto", 3000))


if __name__ == "__main__":
    unittest.main()
