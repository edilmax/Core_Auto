"""BOMBARDAMENTO Coda Intelligente fase67 (2026-07-17, strategia "10.000 menti").

Fase A: 3 thread PER OSPITE si iscrivono nello stesso istante (idempotenza sotto gara).
Fase B (barriera unica): libera (host cancella) || accetta (tutti gli ospiti, anche
non offerti) || rinuncia || converti_voucher || scadi_offerte, con orologio iniettato
che fa scadere offerte A META' tempesta; poi drenaggio FIFO fino a coda vuota.

INVARIANTI (riletti dal DB dopo la tempesta):
  - MAI due 'offerto' simultanei sulla stessa finestra (doppia offerta = doppia vendita).
  - Stati solo ammessi (macchina a stati chiusa).
  - FIFO: l'offerto corrente ha id MINORE di ogni 'in_coda' residuo.
  - CONFERMATI == PRENOTAZIONI RIUSCITE (mai booking senza riga 'confermato', mai
    riga 'confermato' senza booking: se prenota() fallisce la riga RIAPRE l'offerta).
  - MAI doppio booking per lo stesso ospite (accetta replay = idempotente).
  - Righe 'rinunciato' == rinunce riuscite; deposito trattenuto sempre 2000, voucher 2500.

Prova pesante (scratchpad): 10 seed = 63s, ZERO violazioni. Qui guardia snella: 2 seed.
NB: il DB della sonda DEVE essere un file (":memory:" = connessione condivisa fra
thread -> falsi 'transaction within a transaction', classe artefatto fase76).
STATO MODULO: fase67 resta COSTRUITO ma SPENTO (nessuna rotta nel router); da questo
round il percorso e' configurabile (ConfigCasaVIP.db_coda / env DB_CODA, prod=file):
all'accensione i DEPOSITI (denaro) saranno durevoli, non in RAM.
"""
import os
import random
import shutil
import sqlite3
import tempfile
import threading
import unittest

from fase67_coda_intelligente import PoliticaCoda, crea_gestore_coda

STATI = {"in_coda", "offerto", "rinunciato", "scaduto", "voucher", "confermato"}
CI, CO = "2026-09-01", "2026-09-04"


class TestBombardamentoCoda(unittest.TestCase):
    def _tempesta(self, seed):
        rnd = random.Random(seed)
        d = tempfile.mkdtemp()
        db = os.path.join(d, "coda.db")
        try:
            clock = [1000]
            gc = crea_gestore_coda(db, politica=PoliticaCoda(timeout_offerta_sec=50),
                                   orologio=lambda: clock[0])
            ospiti = ["osp%02d" % i for i in range(16)]
            errs, lock = [], threading.Lock()

            barA = threading.Barrier(len(ospiti) * 3)

            def iscrivi(o):
                barA.wait()
                e = gc.iscrivi("casa", CI, CO, o)
                if not e.ok:
                    with lock:
                        errs.append(("ISCRIZIONE_KO", o, e.motivo))

            ths = [threading.Thread(target=iscrivi, args=(o,))
                   for o in ospiti for _ in range(3)]
            for t in ths:
                t.start()
            for t in ths:
                t.join(60)
            self.assertEqual(len(gc.stato_coda("casa", CI, CO)), len(ospiti),
                             "iscrizioni duplicate o perse sotto gara")

            prenotati, rinunce_ok, lockB = {}, [0], threading.Lock()

            def prenota_cb(al, ci, co, osp):
                ok = rnd.random() > 0.3
                if ok:
                    with lockB:
                        prenotati[osp] = prenotati.get(osp, 0) + 1
                return ok

            nL, nR, nV, nS = 6, 4, 4, 3
            barB = threading.Barrier(nL + len(ospiti) + nR + nV + nS)

            def libera(i):
                barB.wait()
                for _ in range(3):
                    gc.libera("casa", CI, CO)
                    clock[0] += rnd.choice([0, 30, 60])

            def accetta(o):
                barB.wait()
                for _ in range(2):
                    gc.accetta("casa", CI, CO, o, prenota=prenota_cb)

            def rinuncia(i):
                barB.wait()
                r = gc.rinuncia("casa", CI, CO, rnd.choice(ospiti))
                if r["ok"]:
                    with lockB:
                        rinunce_ok[0] += 1
                    if r["deposito_trattenuto_cents"] != 2000:
                        with lock:
                            errs.append(("DEPOSITO_SBAGLIATO", r))

            def converti(i):
                barB.wait()
                v = gc.converti_voucher("casa", CI, CO, rnd.choice(ospiti))
                if v["ok"] and v["voucher_cents"] != 2500:
                    with lock:
                        errs.append(("VOUCHER_SBAGLIATO", v))

            def scadi(i):
                barB.wait()
                for _ in range(3):
                    gc.scadi_offerte("casa", CI, CO)

            ths = ([threading.Thread(target=libera, args=(i,)) for i in range(nL)] +
                   [threading.Thread(target=accetta, args=(o,)) for o in ospiti] +
                   [threading.Thread(target=rinuncia, args=(i,)) for i in range(nR)] +
                   [threading.Thread(target=converti, args=(i,)) for i in range(nV)] +
                   [threading.Thread(target=scadi, args=(i,)) for i in range(nS)])
            rnd.shuffle(ths)
            for t in ths:
                t.start()
            for t in ths:
                t.join(60)
            for _ in range(30):
                e = gc.libera("casa", CI, CO)
                if e.esito == "offerto":
                    gc.accetta("casa", CI, CO, e.ospite_id, prenota=prenota_cb)
                elif e.esito == "coda_vuota":
                    break

            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
            rows = con.execute("SELECT * FROM coda ORDER BY id").fetchall()
            con.close()
            off = [r for r in rows if r["stato"] == "offerto"]
            if len(off) > 1:
                errs.append(("DOPPIA_OFFERTA", [r["ospite_id"] for r in off]))
            for r in rows:
                if r["stato"] not in STATI:
                    errs.append(("STATO_ALIENO", r["ospite_id"], r["stato"]))
            if off:
                ic = [r["id"] for r in rows if r["stato"] == "in_coda"]
                if ic and min(ic) < off[0]["id"]:
                    errs.append(("FIFO_VIOLATA", off[0]["id"], min(ic)))
            confermati = {r["ospite_id"] for r in rows if r["stato"] == "confermato"}
            con_booking = {o for o, n in prenotati.items() if n > 0}
            if confermati != con_booking:
                errs.append(("CONFERMATI_VS_BOOKING", sorted(confermati ^ con_booking)))
            doppi = [o for o, n in prenotati.items() if n > 1]
            if doppi:
                errs.append(("DOPPIO_BOOKING", doppi))
            n_rin = sum(1 for r in rows if r["stato"] == "rinunciato")
            if n_rin != rinunce_ok[0]:
                errs.append(("RINUNCE_INCOERENTI", n_rin, rinunce_ok[0]))
            self.assertEqual(errs, [], "seed=%d: %s" % (seed, errs[:4]))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_tempesta_2_seed(self):
        for seed in range(2):
            self._tempesta(seed)

    def test_db_coda_configurabile(self):
        """La coda custodisce DEPOSITI: il bootstrap deve accettare un percorso FILE
        (all'accensione niente denaro in RAM)."""
        from fase81_bootstrap_casavip import ConfigCasaVIP
        d = tempfile.mkdtemp()
        try:
            cfg = ConfigCasaVIP(db_coda=os.path.join(d, "coda.db"))
            self.assertTrue(cfg.db_coda.endswith("coda.db"))
            gc = crea_gestore_coda(cfg.db_coda)
            gc.iscrivi("casa", CI, CO, "osp1")
            gc2 = crea_gestore_coda(cfg.db_coda)   # riavvio simulato: dati ancora li'
            self.assertEqual(gc2.posizione("casa", CI, CO, "osp1"), 1)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
