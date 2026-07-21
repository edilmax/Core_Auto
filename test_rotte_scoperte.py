"""GUARDIA — le due rotte che nessun test nominava.

TROVATE IL 2026-07-21 dalla `mappa_scoperta.py`, che censisce tutte le 138 porte HTTP
e cerca quelle che nessun file di test menziona mai. Nessuna delle due era un buco di
sicurezza — ma una porta che nessuno prova puo' essere rotta per settimane senza che una
sola suite diventi rossa: la suite resterebbe verde per il motivo peggiore, cioe' perche'
non guarda da quella parte.

  · `/api/host/carta_stato`   (fase183, carta off-session: modulo DORMIENTE ma la rotta
                               e' cablata e risponde) -> deve chiedere il token host
  · `/api/bunker/marca.tsr`   (scarico del token della marca temporale) -> vive nel
                               livello HTTP, non nel router: qui si presidia il confine
"""

import json
import os
import shutil
import tempfile
import unittest

AK = {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.7", "User-Agent": "F"}


class BaseRotte(unittest.TestCase):

    def setUp(self):
        os.environ["MARCA_TEMPORALE"] = "1"   # archivio acceso: serve a
        # esercitare la rotta del token, non solo il caso "spento"
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase83_server import crea_router
        self.d = d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/a.db",
            db_pendenti=f"{d}/p.db", db_finanza=f"{d}/f.db",
            db_marche=f"{d}/m.db", bunker_password="SuperPw@1"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {},
                               json.dumps(b) if b is not None else None, h or AK)


class TestCartaStato(BaseRotte):
    """`/api/host/carta_stato` — fase183 e' dormiente, ma la porta e' aperta e cablata."""

    def test_senza_token_host_e_401(self):
        for testate in ({}, {"X-Admin-Key": "sbagliata"}, AK,
                        {"X-Host-Token": "inventato"}):
            st, o = self.g("GET", "/api/host/carta_stato", None, dict(testate))
            self.assertEqual(st, 401,
                             "la rotta risponde %s con testate %s: dovrebbe chiedere "
                             "il token host" % (st, list(testate) or "nessuna"))
            self.assertNotIn("stripe_customer_id", json.dumps(o, default=str),
                             "trapelano identificativi di pagamento senza credenziali")

    def test_non_trapela_nulla_nella_risposta_negata(self):
        st, o = self.g("GET", "/api/host/carta_stato", None, {})
        testo = json.dumps(o, default=str)
        for spia in ("cus_", "pm_", "sk_", "@"):
            self.assertNotIn(spia, testo, "la risposta negata contiene '%s'" % spia)

    def test_il_router_non_solleva_mai_su_questa_rotta(self):
        for metodo in ("GET", "POST", "PUT", "DELETE"):
            for testate in ({}, AK, {"X-Host-Token": "x" * 500}):
                try:
                    st, _ = self.g(metodo, "/api/host/carta_stato", None, dict(testate))
                except Exception as e:
                    self.fail("il router ha sollevato %s su %s"
                              % (type(e).__name__, metodo))
                self.assertIsInstance(st, int)


class TestMarcaTsr(BaseRotte):
    """`/api/bunker/marca.tsr` — l'unica rotta che esce in BINARIO, quindi vive nel
    livello HTTP e non nel router. Qui si presidia proprio quel confine: se un domani
    qualcuno la spostasse nel router senza protezione, questo test lo vedrebbe."""

    def test_il_router_NON_la_serve_ed_e_voluto(self):
        st, o = self.g("GET", "/api/bunker/marca.tsr", None, AK)
        self.assertEqual(st, 404,
                         "il router risponde %s: il token binario deve passare dal "
                         "livello HTTP, non da qui" % st)

    def test_la_rotta_esiste_nel_livello_HTTP(self):
        import io
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fase83_server.py")
        s = io.open(p, encoding="utf-8").read()
        self.assertIn('u.path == "/api/bunker/marca.tsr"', s,
                      "la rotta non e' piu' servita dal livello HTTP")
        i = s.index('u.path == "/api/bunker/marca.tsr"')
        blocco = s[i:i + 1400]
        self.assertIn("router.scarica_marca", blocco,
                      "il livello HTTP non passa piu' dal controllo dei permessi")
        self.assertIn("application/timestamp-reply", blocco)
        self.assertIn("attachment; filename=", blocco)

    def test_lo_scarico_richiede_il_bunker(self):
        stato, token = self.r.scarica_marca(1, {})
        self.assertEqual(stato, 403)
        self.assertIsNone(token)
        stato, token = self.r.scarica_marca(1, dict(AK))
        self.assertEqual(stato, 403, "la sola chiave admin non basta: serve il Bunker")
        self.assertIsNone(token)

    def test_id_assurdi_non_fanno_sollevare(self):
        st, o = self.g("POST", "/api/bunker/login", {"codice": "SuperPw@1"})
        self.assertEqual(st, 200, o)
        h = dict(AK)
        h["X-Bunker-Session"] = o["sessione"]
        for cattivo in ("", "abc", "-1", "9" * 40, None, "1;DROP TABLE marche"):
            try:
                stato, token = self.r.scarica_marca(cattivo, h)
            except Exception as e:
                self.fail("sollevata %s con id %r" % (type(e).__name__, cattivo))
            self.assertIn(stato, (400, 404),
                          "id %r -> stato %s inatteso" % (cattivo, stato))
            self.assertIsNone(token)

    def test_con_la_marca_SPENTA_risponde_servizio_non_disponibile(self):
        """Caso scoperto scrivendo questo test: con `MARCA_TEMPORALE=0` l'archivio non
        esiste e la rotta risponde 503, non 404. E' corretto — ma va detto, altrimenti
        domani qualcuno lo scambia per un guasto (o, peggio, lo "aggiusta")."""
        self.sis.marche = None
        stato, token = self.r.scarica_marca(1, self._sessione_bunker())
        self.assertEqual(stato, 503)
        self.assertIsNone(token)

    def _sessione_bunker(self):
        st, o = self.g("POST", "/api/bunker/login", {"codice": "SuperPw@1"})
        self.assertEqual(st, 200, o)
        h = dict(AK)
        h["X-Bunker-Session"] = o["sessione"]
        return h


class TestLaMappaRestaPulita(unittest.TestCase):
    """Che nessuna rotta torni scoperta: la mappa va rieseguita, non ricordata."""

    def test_ogni_rotta_del_router_e_nominata_da_almeno_un_test(self):
        import io as _io
        import re
        qui = os.path.dirname(os.path.abspath(__file__))
        with _io.open(os.path.join(qui, "fase83_server.py"),
                      encoding="utf-8") as fh:
            server = fh.read()
        rotte = sorted(set(re.findall(r'path == "(/[^"]+)"', server))
                       | set(re.findall(r'u\.path == "(/[^"]+)"', server)))
        testi = []
        for f in os.listdir(qui):
            if f.startswith("test_") and f.endswith(".py"):
                with _io.open(os.path.join(qui, f), encoding="utf-8") as fh:
                    testi.append(fh.read())
        tutto = chr(10).join(testi)
        scoperte = [r for r in rotte if r not in tutto]
        self.assertEqual(scoperte, [],
                         "queste porte HTTP non sono nominate da NESSUN test: "
                         "potrebbero rompersi senza che la suite se ne accorga: %s"
                         % scoperte)


if __name__ == "__main__":
    unittest.main(verbosity=2)
