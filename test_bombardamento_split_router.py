"""BOMBARDAMENTO Split-payment via ROUTER (2026-07-17, strategia "10.000 menti").

DIFFERENZA da test_bombardamento_split (motore, stesso conto): qui la tempesta passa
dalle ROTTE VIVE (/api/split/crea|paga|stato) col sistema composto da fase81, come in
produzione (server prod = ThreadingHTTPServer -> thread reali).

BUG #36 (provato dal vivo, cablaggio prod PRE-fix): fase81 creava lo split HARDCODED
su ":memory:" = connessione CONDIVISA fra thread -> sotto pagamenti simultanei
'cannot start a transaction within a transaction' => 538/960 richieste in 503, e i
conti di gruppo SPARIVANO a ogni riavvio del container. FIX: ConfigCasaVIP.db_split
(env DB_SPLIT, prod default data/split.db) + timeout 30s (il default 5s dava ancora
'database is locked' sotto burst: 43/960). Post-fix: 5 seed -> 503=0, violazioni=0.

INVARIANTI: nessun 503; somma quote == totale (conservazione al centesimo);
raccolto == somma quote pagate; completato <=> raccolto == totale; replay idempotente.
"""
import json
import os
import random
import shutil
import tempfile
import threading
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router


class TestBombardamentoSplitRouter(unittest.TestCase):
    def _sistema(self, d):
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_split=f"{d}/s.db"))
        return crea_router(sis, host_key="hk")

    def _g(self, r, m, p, b=None, q=None):
        return r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, {})

    def _tempesta(self, seed, n_conti=4, n_membri=6):
        rnd = random.Random(seed)
        d = tempfile.mkdtemp()
        try:
            r = self._sistema(d)
            conti = []
            for i in range(n_conti):
                membri = ["m%d_%d" % (i, j) for j in range(n_membri)]
                s, c = self._g(r, "POST", "/api/split/crea",
                               {"prenotazione_id": "pren%d" % i, "alloggio_id": "casa",
                                "totale_cents": 100003 + i, "partecipanti": membri})
                self.assertEqual(s, 201, c)
                conti.append((c["conto_id"], membri, 100003 + i))

            errs, lock = [], threading.Lock()
            barrier = threading.Barrier(n_conti * n_membri * 2)

            def paga(cid, m):
                barrier.wait()
                for _ in range(2):                          # replay incluso
                    s, o = self._g(r, "POST", "/api/split/paga",
                                   {"conto_id": cid, "partecipante_id": m})
                    if s != 200:
                        with lock:
                            errs.append(("PAGA_KO", s, o))

            ths = [threading.Thread(target=paga, args=(cid, m))
                   for cid, membri, _ in conti for m in membri for _ in range(2)]
            rnd.shuffle(ths)
            for t in ths:
                t.start()
            for t in ths:
                t.join(120)

            for cid, membri, tot in conti:
                s, st = self._g(r, "GET", "/api/split/stato", q={"conto_id": cid})
                self.assertEqual(s, 200)
                somma = sum(q["dovuto_cents"] for q in st["quote"])
                racc = sum(q["dovuto_cents"] for q in st["quote"] if q["pagato"])
                if somma != tot:
                    errs.append(("CONSERVAZIONE", cid, somma, tot))
                if st["raccolto_cents"] != racc:
                    errs.append(("RACCOLTO_INCOERENTE", cid))
                if not (st["completato"] and st["raccolto_cents"] == tot
                        and st["mancante_cents"] == 0):
                    errs.append(("COMPLETAMENTO", cid, st["raccolto_cents"], tot))
            self.assertEqual(errs, [], "seed=%d: %s" % (seed, errs[:4]))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_tempesta_2_seed(self):
        for seed in range(2):
            self._tempesta(seed)

    def test_percorso_senza_cartella_non_crasha(self):
        """Incidente deploy 2026-07-17: path con cartella mancante -> 'unable to open
        database file' -> APP in crash-loop all'avvio. Ora il genitore si crea da solo
        (fase65 e fase67)."""
        from fase65_split_payment import crea_gestore_split
        from fase67_coda_intelligente import crea_gestore_coda
        d = tempfile.mkdtemp()
        try:
            s = crea_gestore_split(os.path.join(d, "nuova", "cart", "s.db"))
            self.assertIsNotNone(s.crea_conto("p", "a", 100, ["x", "y"]))
            gc = crea_gestore_coda(os.path.join(d, "altra", "coda.db"))
            self.assertTrue(gc.iscrivi("casa", "2026-09-01", "2026-09-02", "o1").ok)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_db_split_durevole_al_riavvio(self):
        """I conti di gruppo devono SOPRAVVIVERE al riavvio (prima: :memory: = persi)."""
        d = tempfile.mkdtemp()
        try:
            r = self._sistema(d)
            s, c = self._g(r, "POST", "/api/split/crea",
                           {"prenotazione_id": "p1", "alloggio_id": "casa",
                            "totale_cents": 9001, "partecipanti": ["a", "b", "c"]})
            self.assertEqual(s, 201)
            cid = c["conto_id"]
            self._g(r, "POST", "/api/split/paga",
                    {"conto_id": cid, "partecipante_id": "a"})
            r2 = self._sistema(d)                     # riavvio simulato: stesso d
            s, st = self._g(r2, "GET", "/api/split/stato", q={"conto_id": cid})
            self.assertEqual(s, 200, st)
            self.assertEqual(st["totale_cents"], 9001)
            self.assertEqual(sum(q["dovuto_cents"] for q in st["quote"]), 9001)
            self.assertTrue(any(q["pagato"] for q in st["quote"]))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
