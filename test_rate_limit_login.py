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


class TestRateLimitOttoBuchiTrovatiDallaMutazione(unittest.TestCase):
    """⛔ OTTO BUCHI VERI NELLA DIFESA DAL BRUTE-FORCE (mutazione, 2026-08-02).

    Campagna su tutti e 15 i punti di `fase179_rate_limit`: 7 uccisi, 8 sopravvissuti --
    il 53%, il rapporto peggiore incontrato finora. Un solo file di prove (questo), usato
    tutto dalla campagna: nessuna scorciatoia, sono buchi reali.

    E' il modulo che impedisce a qualcuno di provare le password a raffica su conti che
    muovono denaro. Il commento in cima al file lo dice: nginx frena 20 richieste al
    secondo per IP, ma un brute-force LENTO e distribuito passava indisturbato.
    """

    def _rl(self, t0=1000.0, **kw):
        self.clock = {"t": t0}
        p = dict(soglia=5, finestra_sec=60, base_blocco_sec=60, max_blocco_sec=3600)
        p.update(kw)
        return RateLimiter(orologio=lambda: self.clock["t"], **p)

    def test_una_chiave_NON_VALIDA_non_blocca_nessuno_e_non_lascia_traccia(self):
        """⛔ CINQUE DEGLI OTTO STANNO QUI.

            if not (isinstance(chiave, str) and chiave):
                return True, 0          # consenti: passa
                return False, 0         # fallito:  non registra niente

        Tre funzioni (`consenti`, `fallito`, `riuscito`) hanno lo stesso controllo, e in
        tutte e tre il guasto ha due facce:
          · con `or` al posto di `and` una chiave vuota SUPERA il controllo e finisce nel
            registro dei tentativi -- e da quel momento tutti quelli senza chiave
            condividono lo stesso contatore: bastano cinque falliti a bloccare CHIUNQUE
            arrivi senza identificativo;
          · con `True` -> `False` in `consenti`, una chiave non valida viene **respinta
            subito**: il contrario di quello che serve.

        In tutti e due i casi si trasforma una difesa in un modo per bloccare gli altri.
        """
        rl = self._rl()
        for storta in ("", None, 0, [], {}, 123):
            # non deve mai bloccare
            ok, attesa = rl.consenti(storta)
            self.assertTrue(ok, "una chiave non valida (%r) viene RESPINTA: chi arriva "
                                "senza identificativo resta fuori" % (storta,))
            self.assertEqual(0, attesa)
            # non deve registrare niente, nemmeno dopo molti fallimenti
            for _ in range(10):
                bloccato, _a = rl.fallito(storta)
                self.assertFalse(bloccato,
                                 "dieci fallimenti su una chiave non valida (%r) hanno "
                                 "prodotto un blocco: e' un contatore CONDIVISO fra tutti "
                                 "quelli senza chiave" % (storta,))
            rl.riuscito(storta)
        self.assertEqual({}, rl._m,
                         "una chiave non valida ha lasciato traccia nel registro: %r"
                         % (rl._m,))
        # ...e il verso opposto: una chiave VERA viene contata e bloccata come deve
        for _ in range(5):
            rl.fallito("mario@esempio.it")
        self.assertFalse(rl.consenti("mario@esempio.it")[0],
                         "dopo cinque fallimenti veri la chiave non e' bloccata")

        # ⛔ LA SECONDA DIFESA VA PROVATA DA SOLA.
        # I controlli in `consenti` e `riuscito` oggi non si raggiungono mai, perche'
        # `fallito` rifiuta prima le chiavi storte e nel registro non ne entra nessuna. Ma
        # sono scritti come SECONDA difesa -- e una seconda difesa che non si puo' provare
        # non e' una difesa: il giorno che la prima cede, nessuno sa se la seconda regge.
        # Qui lo stato si inietta a mano, cosi' il controllo viene messo alla prova da solo.
        rl2 = self._rl()
        for storta in ("", 0):
            rl2._m[storta] = {"fail": [], "blocco_fino": self.clock["t"] + 9999,
                              "lockout": 3, "visto": self.clock["t"]}
            ok, _a = rl2.consenti(storta)
            self.assertTrue(ok,
                            "una chiave non valida (%r) viene bloccata leggendo uno stato "
                            "che non avrebbe mai dovuto esistere: la seconda difesa non "
                            "regge" % (storta,))
            rl2.riuscito(storta)
            self.assertIn(storta, rl2._m,
                          "`riuscito` ha agito su una chiave non valida (%r): tocca uno "
                          "stato che non deve nemmeno guardare" % (storta,))

    def test_il_blocco_finisce_all_ISTANTE_ESATTO(self):
        """`if r["blocco_fino"] > ora` con `>=`: nel momento preciso in cui il blocco
        scade, il codice sano lascia passare e il codice guasto tiene ancora fuori.

        Un istante solo, ma e' l'unico punto in cui le due versioni si distinguono: provare
        «durante» e «dopo» lascia vivo il guasto. E dalla parte dell'utente e' la
        differenza fra «il blocco e' finito» e «il blocco non finisce mai davvero».
        """
        rl = self._rl()
        for _ in range(5):
            rl.fallito("k")
        ok, attesa = rl.consenti("k")
        self.assertFalse(ok, "il blocco non e' scattato")
        blocco_fino = rl._m["k"]["blocco_fino"]
        # un istante PRIMA della scadenza: ancora bloccato
        self.clock["t"] = blocco_fino - 0.001
        self.assertFalse(rl.consenti("k")[0], "sbloccato prima del tempo")
        # ESATTAMENTE alla scadenza: libero
        self.clock["t"] = blocco_fino
        self.assertTrue(rl.consenti("k")[0],
                        "all'istante esatto della scadenza il blocco e' finito e deve "
                        "lasciar passare: invece tiene ancora fuori")

    def test_la_finestra_dei_fallimenti_tiene_il_confine(self):
        """`[t for t in r["fail"] if t >= taglio]` con `>`: il fallimento che cade
        ESATTAMENTE sul bordo della finestra viene buttato via.

        Sembra un dettaglio da un secondo, ma sposta la difesa: chi attacca con un ritmo
        calibrato sul bordo non raggiunge mai la soglia, e il blocco non scatta MAI.
        E' il brute-force lento che questo modulo esiste per fermare.
        """
        rl = self._rl(soglia=3, finestra_sec=60)
        rl.fallito("k")                      # t=1000
        self.clock["t"] = 1060.0             # esattamente 60s dopo: il primo e' SUL bordo
        rl.fallito("k")
        bloccato, _ = rl.fallito("k")
        self.assertTrue(bloccato,
                        "il fallimento sul bordo esatto della finestra e' stato scartato: "
                        "con un ritmo calibrato sul confine il blocco non scatta mai "
                        "(fallimenti visti: %r)" % (rl._m.get("k", {}).get("fail"),))
        # ...e il verso opposto: un fallimento FUORI dalla finestra non deve contare
        rl2 = self._rl(soglia=3, finestra_sec=60)
        rl2.fallito("z")
        self.clock["t"] = 1061.0             # un secondo oltre il bordo
        rl2.fallito("z")
        bloccato2, _ = rl2.fallito("z")
        self.assertFalse(bloccato2,
                         "un fallimento vecchio oltre la finestra viene ancora contato: "
                         "si bloccano utenti legittimi per tentativi di ieri")

    def test_lo_SFRATTO_delle_chiavi_vecchie_tiene_il_tetto(self):
        """`if len(self._m) <= self._max_chiavi: return` con `<`: al numero ESATTO del
        tetto lo sfratto parte comunque e butta via una chiave che non doveva sparire.

        Il tetto esiste per non farsi riempire la memoria da chi inventa identificativi
        (anti-DoS). Ma buttare una chiave di troppo significa **azzerare il contatore di
        qualcuno che stava per essere bloccato**: chi attacca ha solo bisogno di generare
        rumore per farsi dimenticare.
        """
        rl = self._rl()
        rl._max_chiavi = 3
        for k in ("a", "b", "c"):
            self.clock["t"] += 1
            rl.fallito(k)
        self.assertEqual(3, len(rl._m),
                         "al numero esatto del tetto e' gia' stata sfrattata una chiave: "
                         "%r" % (sorted(rl._m),))
        self.clock["t"] += 1
        rl.fallito("d")                       # ora si supera: la piu' vecchia se ne va
        self.assertEqual(3, len(rl._m), "il tetto non e' stato rispettato: %r" % (sorted(rl._m),))
        self.assertNotIn("a", rl._m, "sfrattata la chiave sbagliata (non la piu' vecchia)")
        self.assertIn("d", rl._m)


if __name__ == "__main__":
    unittest.main()
