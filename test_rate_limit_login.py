"""Collaudo RATE LIMIT autenticazione (fase179 + agganci fase83) — anti brute-force.

Policy (RICALIBRATA 2026-07-22): 8 tentativi/min per IP sul login, primo blocco 30s, blocco
MASSIMO 10 min. Prima era 5/min con blocco fino a 1h: un caso VERO nei log di prod aveva chiuso
fuori un host onesto che provava la password. Piu' spazio per lo sbaglio in buona fede, stessa
difesa dal brute-force (+ backoff crescente, PER-IP mai per-email = niente account-lockout DoS).
Kimi-NTU: Testare (9 richieste rapide -> il 9° e' 429), Isolare (in-process, nessun I/O),
Verificare (IP diversi = bucket diversi -> l'app vede DAVVERO chi chiama), Scalare (soglie).
Invarianti:
  1. RateLimiter (meccanismo, soglia d'esempio 5): N fallimenti/finestra -> lockout; successo
     azzera; backoff raddoppia; memoria limitata (sfratto LRU) -> chi ruota chiavi non gonfia RAM;
  2. login: 9 tentativi rapidi dallo STESSO IP -> il 9° e' 429 (loggato); un ALTRO IP NON
     e' bloccato (traffico legittimo non influenzato); un login RIUSCITO azzera il contatore;
  3. la chiave admin sbagliata a raffica da un IP -> lockout di QUELL'IP; la chiave giusta
     da un altro IP funziona sempre.
"""
import json
import shutil
import tempfile
import unittest

from fase179_rate_limit import RateLimiter
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router


class TestRateLimiterPuro(unittest.TestCase):
    def _rl(self, t0=1000.0):
        self.clock = {"t": t0}
        return RateLimiter(soglia=5, finestra_sec=60, base_blocco_sec=60,
                           max_blocco_sec=3600, orologio=lambda: self.clock["t"])

    def test_lockout_dopo_soglia_e_backoff(self):
        rl = self._rl()
        for _ in range(4):
            self.assertEqual(rl.fallito("k")[0], False)     # 4 fallimenti: ancora ok
            self.assertTrue(rl.consenti("k")[0])
        self.assertEqual(rl.fallito("k")[0], True)          # 5° -> lockout
        ok, attesa = rl.consenti("k")
        self.assertFalse(ok)
        self.assertGreater(attesa, 0)
        # scaduto il blocco (60s): riparte
        self.clock["t"] += 61
        self.assertTrue(rl.consenti("k")[0])
        # secondo lockout = doppio (120s)
        for _ in range(5):
            rl.fallito("k")
        self.assertGreaterEqual(rl.consenti("k")[1], 110)

    def test_successo_azzera(self):
        rl = self._rl()
        for _ in range(4):
            rl.fallito("k")
        rl.riuscito("k")
        # ripartito da zero: altri 4 fallimenti NON bloccano
        for _ in range(4):
            self.assertFalse(rl.fallito("k")[0])

    def test_finestra_scorrevole(self):
        rl = self._rl()
        for _ in range(4):
            rl.fallito("k")
        self.clock["t"] += 61                # i 4 vecchi escono dalla finestra
        self.assertFalse(rl.fallito("k")[0], "i fallimenti vecchi non contano piu'")

    def test_memoria_limitata(self):
        rl = RateLimiter(soglia=5, finestra_sec=60, max_chiavi=100,
                         orologio=lambda: 1.0)
        for i in range(500):
            rl.fallito("k%d" % i)
        self.assertLessEqual(len(rl._m), 100, "tetto memoria non rispettato (DoS RAM)")


class TestLoginThrottle(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"h" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_pendenti=f"{d}/p.db"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        self.sis.registro_host.registra("vero@collaudo.invalid", "passwordgiusta",
                                        accetta_termini=True)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _login(self, email, pw, ip):
        return self.r.gestisci("POST", "/api/host/login", {},
                               json.dumps({"email": email, "password": pw}),
                               {"X-Forwarded-For": ip})

    def test_otto_rapide_ok_poi_il_nono_e_429(self):
        # policy ricalibrata: 8 tentativi/min ammessi, il 9° blocca (soglia=8)
        ip = "203.0.113.7"
        for i in range(8):
            s, _ = self._login("vero@collaudo.invalid", "sbagliata", ip)
            self.assertEqual(s, 401, "tentativo %d deve essere 401 (sotto soglia 8)" % (i + 1))
        s, body = self._login("vero@collaudo.invalid", "sbagliata", ip)
        self.assertEqual(s, 429, "il 9° tentativo deve essere BLOCCATO (429)")
        self.assertEqual(body["errore"], "troppi_tentativi")
        self.assertGreater(body["riprova_tra_sec"], 0)

    def test_altro_ip_non_influenzato(self):
        for _ in range(6):
            self._login("vero@collaudo.invalid", "sbagliata", "203.0.113.7")
        # traffico legittimo da un IP DIVERSO: NON bloccato (prova che l'app vede l'IP,
        # e che il throttle e' PER-IP: nessun account-lockout DoS cross-IP)
        s, _ = self._login("vero@collaudo.invalid", "sbagliata", "198.51.100.9")
        self.assertEqual(s, 401, "un altro IP non deve ereditare il blocco")
        # e la password GIUSTA dall'IP pulito passa
        s, _ = self._login("vero@collaudo.invalid", "passwordgiusta", "198.51.100.9")
        self.assertEqual(s, 200)

    def test_login_riuscito_azzera(self):
        ip = "203.0.113.20"
        for _ in range(4):
            self._login("vero@collaudo.invalid", "sbagliata", ip)
        s, _ = self._login("vero@collaudo.invalid", "passwordgiusta", ip)
        self.assertEqual(s, 200, "la password giusta deve passare")
        # contatore azzerato: altri 4 sbagli NON bloccano subito
        for _ in range(4):
            s, _ = self._login("vero@collaudo.invalid", "sbagliata", ip)
            self.assertEqual(s, 401)

    def test_admin_key_brute_force_per_ip(self):
        ip = "203.0.113.66"
        h = lambda k: {"X-Admin-Key": k, "X-Forwarded-For": ip}
        for _ in range(8):     # soglia ricalibrata a 8: servono 8 fallimenti per il lockout
            self.r.gestisci("GET", "/api/admin/alloggi", {}, None, h("chiave-sbagliata"))
        # QUELL'IP ora e' in lockout: anche la chiave GIUSTA da lì e' negata
        s, _ = self.r.gestisci("GET", "/api/admin/alloggi", {}, None, h("ak"))
        self.assertEqual(s, 401, "IP in lockout: bloccato anche con chiave giusta")
        # ma da un ALTRO IP la chiave giusta funziona
        s, _ = self.r.gestisci("GET", "/api/admin/alloggi", {}, None,
                               {"X-Admin-Key": "ak", "X-Forwarded-For": "198.51.100.1"})
        self.assertEqual(s, 200, "un altro IP con chiave giusta deve funzionare")


if __name__ == "__main__":
    unittest.main()
