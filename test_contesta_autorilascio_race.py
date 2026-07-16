"""Collaudo BUG #20 (2026-07-16, metodo libro - gara contesta vs auto-rilascio 24h).

BUG PROVATO (3 violazioni su 300 al collaudo): in `fase160.auto_rilascia` la SELECT dei
candidati gira in AUTOCOMMIT (fuori transazione) e l'UPDATE non aveva guardia di stato:
una contestazione committata tra lettura e scrittura veniva SOVRASCRITTA ('contestato'
-> 'rilasciato') e il rif finiva nella lista bonifici del tick = HOST PAGATO con la
disputa APERTA (e l'ospite, che aveva ricevuto ok=True, silenziosamente scavalcato).

Fix: CAS per riga (`... WHERE prenotazione_id=? AND stato='in_garanzia'`) e la lista
ritornata contiene SOLO le righe realmente acquisite (rowcount=1).

Il test e' un martello concorrente: N garanzie scadute, un thread fa il tick mentre due
thread contestano tutto. INVARIANTE (deve valere SEMPRE): nessun rif e' sia 'contesta
ok' sia rilasciato/in lista bonifici; ogni rif finisce in ESATTAMENTE uno dei due esiti.
"""
import shutil
import tempfile
import threading
import time
import unittest

from fase160_escrow_garanzia import crea_escrow_garanzia


class TestContestaAutorilascioRace(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.gz = crea_escrow_garanzia(self.dir + r"\g.db")
        self.gz.inizializza_schema()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_un_solo_vincitore_mai_host_pagato_con_disputa(self):
        N = 200
        ora = int(time.time())
        for i in range(N):
            self.gz.apri("rif%03d" % i, 10000, ora_checkin_ts=ora - 90000)
        rilasciati, esiti = [], {}
        barrier = threading.Barrier(3)

        def tick():
            barrier.wait()
            rilasciati.extend(self.gz.auto_rilascia(dettagli=True))

        def contestatore(indici):
            barrier.wait()
            for i in indici:
                esiti["rif%03d" % i] = self.gz.contesta("rif%03d" % i, "muffa")

        th = [threading.Thread(target=tick),
              threading.Thread(target=contestatore, args=(range(0, N, 2),)),
              threading.Thread(target=contestatore, args=(range(1, N, 2),))]
        for t in th:
            t.start()
        for t in th:
            t.join(60)
        ril_set = {r["prenotazione_id"] for r in rilasciati}
        n_contestate = 0
        for i in range(N):
            rif = "rif%03d" % i
            ok = bool(esiti.get(rif, {}).get("ok"))
            st = self.gz.stato(rif)["stato"]
            if ok:
                n_contestate += 1
                # MAI: contesta accettata ma fondi rilasciati / bonifico in lista
                self.assertEqual(st, "contestato", rif)
                self.assertNotIn(rif, ril_set,
                                 "%s: host in lista bonifici con disputa APERTA" % rif)
            else:
                self.assertEqual(st, "rilasciato", rif)
                self.assertIn(rif, ril_set, rif)
        # conservazione delle decisioni: ogni rif in ESATTAMENTE un esito
        self.assertEqual(n_contestate + len(ril_set), N)

    def test_contestata_prima_del_tick_mai_rilasciata(self):
        ora = int(time.time())
        self.gz.apri("rifX", 5000, ora_checkin_ts=ora - 90000)
        self.assertTrue(self.gz.contesta("rifX", "sporco")["ok"])
        out = self.gz.auto_rilascia(dettagli=True)
        self.assertEqual(out, [])
        self.assertEqual(self.gz.stato("rifX")["stato"], "contestato")


if __name__ == "__main__":
    unittest.main(verbosity=2)
