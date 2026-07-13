"""
Test Fase 164 - Pool AI a rotazione con failover ("una funziona sempre").

Copre: failover sticky, passaggio automatico quando un provider finisce la quota/va in
errore, cooldown a backoff + scadenza, quota giornaliera + reset a mezzanotte UTC, round
robin, stato durevole (persistenza su file), robustezza (non solleva mai), diagnostica.
"""
import os
import shutil
import tempfile
import unittest

from fase164_pool_ai import (
    ErroreProvider, PoolAI, ProviderAI, QuotaEsaurita, crea_pool_ai,
)


class _Clock:
    def __init__(self, t=1_000_000.0):
        self.t = float(t)

    def __call__(self):
        return self.t

    def avanza(self, sec):
        self.t += sec


def _prov(nome, comportamento, quota=0):
    """comportamento: callable(richiesta)->risultato, oppure può sollevare."""
    return ProviderAI(nome=nome, chiama=comportamento, quota_giorno=quota)


class TestFailover(unittest.TestCase):
    def test_resta_sul_primo_finche_regge(self):
        chiamate = {"a": 0, "b": 0}
        def a(r): chiamate["a"] += 1; return "A:" + str(r)
        def b(r): chiamate["b"] += 1; return "B:" + str(r)
        pool = crea_pool_ai([_prov("a", a), _prov("b", b)], orologio=_Clock())
        for _ in range(5):
            out = pool.genera("x")
            self.assertTrue(out["ok"])
            self.assertEqual(out["provider"], "a")     # sticky: sempre 'a'
        self.assertEqual(chiamate, {"a": 5, "b": 0})   # 'b' mai toccato

    def test_passa_al_secondo_quando_il_primo_esaurisce(self):
        def a(r): raise QuotaEsaurita()
        def b(r): return "B"
        clk = _Clock()
        pool = crea_pool_ai([_prov("a", a), _prov("b", b)], orologio=clk)
        out = pool.genera("x")
        self.assertTrue(out["ok"])
        self.assertEqual(out["provider"], "b")         # 'a' esaurito -> 'b'
        self.assertEqual(out["tentati"], ["a", "b"])
        # 'a' resta in cooldown: la prossima parte diretta da 'b' (non ritenta 'a')
        out2 = pool.genera("y")
        self.assertEqual(out2["provider"], "b")
        self.assertEqual(out2["tentati"], ["b"])

    def test_tutti_esauriti(self):
        def morto(r): raise QuotaEsaurita()
        pool = crea_pool_ai([_prov("a", morto), _prov("b", morto)], orologio=_Clock())
        out = pool.genera("x")
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "tutti_esauriti")
        self.assertEqual(out["tentati"], ["a", "b"])

    def test_pool_vuoto(self):
        pool = crea_pool_ai([], orologio=_Clock())
        out = pool.genera("x")
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "nessun_provider")


class TestCooldown(unittest.TestCase):
    def test_cooldown_scade_e_rientra(self):
        stato = {"fail": True}
        def a(r):
            if stato["fail"]:
                raise ErroreProvider()
            return "A"
        def b(r): return "B"
        clk = _Clock()
        pool = crea_pool_ai([_prov("a", a), _prov("b", b)], orologio=clk,
                            cooldown_base_sec=300)
        self.assertEqual(pool.genera("x")["provider"], "b")   # 'a' fallisce -> 'b'
        stato["fail"] = False
        # entro il cooldown 'a' è saltato -> resta 'b'
        clk.avanza(100)
        self.assertEqual(pool.genera("x")["tentati"], ["b"])
        # dopo il cooldown 'a' rientra nel giro (failover riparte dal cursore = b, poi a)
        clk.avanza(300)
        out = pool.genera("x")
        self.assertTrue(out["ok"])
        self.assertIn("a", pool.stato()["provider"][0]["nome"])   # 'a' di nuovo disponibile
        self.assertTrue(pool.stato()["provider"][0]["disponibile"])

    def test_backoff_esponenziale(self):
        def a(r): raise ErroreProvider()
        clk = _Clock()
        pool = crea_pool_ai([_prov("a", a)], orologio=clk,
                            cooldown_base_sec=100, cooldown_max_sec=10000)
        pool.genera("x")                                  # 1° fallimento -> cd 100
        cd1 = pool.stato()["provider"][0]["cooldown_residuo_sec"]
        self.assertEqual(cd1, 100)
        clk.avanza(100)
        pool.genera("x")                                  # 2° fallimento -> cd 200
        self.assertEqual(pool.stato()["provider"][0]["cooldown_residuo_sec"], 200)
        clk.avanza(200)
        pool.genera("x")                                  # 3° -> cd 400
        self.assertEqual(pool.stato()["provider"][0]["cooldown_residuo_sec"], 400)

    def test_cooldown_ha_un_tetto(self):
        def a(r): raise ErroreProvider()
        clk = _Clock()
        pool = crea_pool_ai([_prov("a", a)], orologio=clk,
                            cooldown_base_sec=1000, cooldown_max_sec=1500)
        for _ in range(5):
            pool.genera("x")
            clk.avanza(2000)
        self.assertLessEqual(pool.stato()["provider"][0]["cooldown_residuo_sec"], 1500)


class TestQuota(unittest.TestCase):
    def test_quota_giornaliera_e_reset(self):
        usi = {"a": 0}
        def a(r): usi["a"] += 1; return "A"
        def b(r): return "B"
        clk = _Clock()
        pool = crea_pool_ai([_prov("a", a, quota=2), _prov("b", b)], orologio=clk)
        self.assertEqual(pool.genera("x")["provider"], "a")   # uso 1
        self.assertEqual(pool.genera("x")["provider"], "a")   # uso 2 (quota piena)
        self.assertEqual(pool.genera("x")["provider"], "b")   # 'a' esaurita -> 'b'
        self.assertEqual(usi["a"], 2)
        # il giorno dopo la quota si azzera -> 'a' rientra
        clk.avanza(86400)
        out = pool.genera("x")
        self.assertTrue(out["ok"])
        # (failover riparte dal cursore corrente; 'a' è comunque di nuovo disponibile)
        self.assertTrue(pool.stato()["provider"][0]["disponibile"])


class TestRoundRobin(unittest.TestCase):
    def test_distribuisce_a_giro(self):
        def a(r): return "A"
        def b(r): return "B"
        def c(r): return "C"
        pool = crea_pool_ai([_prov("a", a), _prov("b", b), _prov("c", c)],
                            strategia="round_robin", orologio=_Clock())
        seq = [pool.genera("x")["provider"] for _ in range(6)]
        self.assertEqual(seq, ["a", "b", "c", "a", "b", "c"])


class TestDurabilita(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "pool.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_stato_persistente_tra_riavvii(self):
        def a(r): raise QuotaEsaurita()
        def b(r): return "B"
        clk = _Clock()
        p1 = crea_pool_ai([_prov("a", a), _prov("b", b)], percorso_stato=self.path,
                          orologio=clk)
        p1.genera("x")                                    # 'a' -> cooldown, 'b' usato
        self.assertTrue(os.path.exists(self.path))
        # "riavvio": nuovo pool dallo stesso file -> 'a' ancora in cooldown, non lo ritenta
        p2 = crea_pool_ai([_prov("a", a), _prov("b", b)], percorso_stato=self.path,
                          orologio=clk)
        out = p2.genera("y")
        self.assertEqual(out["provider"], "b")
        self.assertEqual(out["tentati"], ["b"])           # 'a' saltato: stato ricordato

    def test_stato_corrotto_riparte_pulito(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{non json!!")
        def a(r): return "A"
        pool = crea_pool_ai([_prov("a", a)], percorso_stato=self.path, orologio=_Clock())
        self.assertTrue(pool.genera("x")["ok"])           # non crasha


class TestRobustezza(unittest.TestCase):
    def test_non_solleva_mai_su_errori_strani(self):
        def esplode(r): raise RuntimeError("boom")
        def none(r): return None                          # nessun risultato
        def ok(r): return "OK"
        pool = crea_pool_ai([_prov("x", esplode), _prov("y", none), _prov("z", ok)],
                            orologio=_Clock())
        out = pool.genera("q")
        self.assertTrue(out["ok"])
        self.assertEqual(out["provider"], "z")
        self.assertEqual(out["tentati"], ["x", "y", "z"])

    def test_diagnostica_stato(self):
        def a(r): return "A"
        pool = crea_pool_ai([_prov("a", a, quota=100)], orologio=_Clock())
        pool.genera("x")
        st = pool.stato()
        self.assertEqual(st["strategia"], "failover")
        self.assertEqual(st["provider"][0]["usi_oggi"], 1)
        self.assertEqual(st["provider"][0]["quota_giorno"], 100)


if __name__ == "__main__":
    unittest.main()
