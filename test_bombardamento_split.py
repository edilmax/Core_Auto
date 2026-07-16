"""BOMBARDAMENTO split-payment di gruppo (2026-07-17, strategia "10.000 menti").

K co-ospiti pagano la propria quota NELLO STESSO istante (barriera) + alcuni pagano DUE
volte (duplicato concorrente). Il motore fase65 usa BEGIN IMMEDIATE con idempotenza
per-partecipante e completamento atomico (`raccolto >= totale`).

INVARIANTI (conservazione del centesimo sotto contesa):
  - raccolto == totale quando tutti hanno pagato (nessun doppio-conteggio da duplicati),
  - somma delle quote CREATE == totale (lo split non perde/crea centesimi),
  - 'completato' esattamente quando raccolto>=totale, mancante == 0.
"""
import random
import shutil
import tempfile
import threading
import unittest

from fase65_split_payment import crea_gestore_split


class TestBombardamentoSplit(unittest.TestCase):
    def _tempesta(self, seed, K):
        rnd = random.Random(seed)
        d = tempfile.mkdtemp()
        try:
            eng = crea_gestore_split(f"{d}/s.db")
            part = ["p%d" % i for i in range(K)]
            totale = rnd.choice([9999, 10000, 12345, 100000])
            cid = eng.crea_conto("PREN1", "casa", totale, part, metodo="equo")
            self.assertTrue(cid)
            barrier = threading.Barrier(K + K // 3)

            def paga(pid):
                barrier.wait()
                eng.registra_pagamento(cid, pid, idem_key=cid + ":" + pid)

            ths = [threading.Thread(target=paga, args=(pid,)) for pid in part]
            for pid in part[:K // 3]:                      # duplicati concorrenti
                ths.append(threading.Thread(target=paga, args=(pid,)))
            rnd.shuffle(ths)
            for t in ths:
                t.start()
            for t in ths:
                t.join(30)

            st = eng.stato_conto(cid)
            self.assertEqual(st["raccolto_cents"], totale,
                             "conservazione: raccolto != totale (doppio conteggio?)")
            self.assertTrue(st["completato"])
            self.assertEqual(st.get("mancante_cents", 0), 0)
            somma_quote = sum(q["dovuto_cents"] for q in st.get("quote", []))
            self.assertEqual(somma_quote, totale,
                             "split ha perso/creato centesimi: somma quote != totale")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_pagamenti_concorrenti_conservano(self):
        for seed in range(4):
            for K in (3, 5, 8):
                self._tempesta(seed, K)


if __name__ == "__main__":
    unittest.main(verbosity=2)
