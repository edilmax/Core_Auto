"""Collaudo ramo REFERRAL (2026-07-16, metodo libro) — soglia '==' fragile.

BUG: `_forse_qualifica_referral` premiava il referente SOLO se `conta_pagati == soglia`
ESATTO. Due webhook CONCORRENTI (3a e 4a prenotazione pagate nello stesso istante)
aggiornano entrambi il payout a 'maturato' PRIMA che uno dei due conti -> entrambi
contano 4 -> la finestra '==3' e' persa PER SEMPRE e il premio (€40) non scatta mai.
Il "una volta sola" e' gia' garantito dallo store (fase76.qualifica_referee: BEGIN
IMMEDIATE + dedup 'gia_qualificato') -> il fix e' `>=`: si recupera al pagamento
successivo e il dedup impedisce il doppio premio.
"""
import shutil
import tempfile
import unittest

from fase76_viral_loop import crea_viral_loop


class _PayoutFinto:
    def __init__(self, n):
        self.n = n

    def conta_pagati(self, host_id):
        return self.n


class _Cfg:
    referral_soglia_prenotazioni = 3
    referral_premio_cents = 4000


class _SysFinto:
    def __init__(self, viral):
        self.viral = viral
        self.config = _Cfg()


class TestReferralSoglia(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.viral = crea_viral_loop(self.dir + r"\v.db", b"S" * 32)
        cod = self.viral.genera_codice("referente1")
        self.assertTrue(cod)
        self.assertTrue(self.viral.registra_referee(cod, "invitato1").ok)
        # la registrazione stessa accredita un benvenuto al referente: misuro i DELTA
        self.base = self.viral.credito_disponibile("referente1")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _qualifica(self, n_pagate):
        from fase83_server import RouterHTTP
        r = RouterHTTP.__new__(RouterHTTP)          # solo il metodo sotto test
        r._sys = _SysFinto(self.viral)
        r._forse_qualifica_referral("invitato1", _PayoutFinto(n_pagate))

    def test_finestra_saltata_recupera(self):
        # scenario della GARA: il conteggio ha gia' superato la soglia (==3 mai visto)
        self._qualifica(4)
        self.assertEqual(self.viral.credito_disponibile("referente1") - self.base, 4000,
                         "soglia SUPERATA (non ==): il premio deve scattare lo stesso")

    def test_mai_doppio_premio(self):
        self._qualifica(3)
        self.assertEqual(self.viral.credito_disponibile("referente1") - self.base, 4000)
        self._qualifica(4)                          # pagamento successivo: dedup
        self._qualifica(5)
        self.assertEqual(self.viral.credito_disponibile("referente1") - self.base, 4000,
                         "il dedup dello store deve impedire il doppio premio")

    def test_sotto_soglia_niente_premio(self):
        self._qualifica(2)
        self.assertEqual(self.viral.credito_disponibile("referente1") - self.base, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
