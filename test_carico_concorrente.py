"""
Collaudo SOTTO CARICO (richiesta fondatore: "come se ci fossero tantissime richieste da tutti").
Molti thread simultanei sul router REALE: ricerche, preventivi, e la GARA di prenotazione
sulla stessa stanza (1 unità, 30 clienti) -> ESATTAMENTE 1 vince, mai doppia prenotazione.
+ endpoint metriche avanzate (fase115 attivata).
"""
import json
import shutil
import tempfile
import threading
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase57_vetrina import SchedaAlloggio
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE


class TestCaricoConcorrente(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{self.d}/c.db", db_inventario=f"{self.d}/i.db",
            db_registro_host=f"{self.d}/r.db", db_accettazioni=f"{self.d}/a.db"))
        self.r = crea_router(self.sys, host_key="hk")
        self.sys.catalogo.pubblica(SchedaAlloggio(
            host_id="h1", slug="unica", titolo="Stanza Unica", citta="Roma",
            prezzo_notte_cents=10000, capacita=2))
        for g in ("2026-09-01", "2026-09-02"):
            self.sys.inventario.imposta_disponibilita("unica", g, unita_totali=1,
                                                      prezzo_netto_cents=10000)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _parallelo(self, fn, n):
        esiti, thread = [None] * n, []
        def run(i):
            try:
                esiti[i] = fn(i)
            except Exception as e:                     # un crash sotto carico = bocciato
                esiti[i] = ("EXC", str(e))
        for i in range(n):
            t = threading.Thread(target=run, args=(i,))
            thread.append(t)
            t.start()
        for t in thread:
            t.join(timeout=60)
        return esiti

    def test_40_ricerche_simultanee_tutte_ok(self):
        esiti = self._parallelo(
            lambda i: self.g("GET", "/api/catalogo", q={"citta": "Roma"})[0], 40)
        self.assertEqual(esiti, [200] * 40, "ricerche fallite sotto carico: %r" % esiti[:5])

    def test_gara_prenotazione_vince_uno_solo(self):
        # 30 clienti, 1 stanza, stesse date: quote+book concorrenti -> ESATTAMENTE 1 confermata
        def cliente(i):
            s, q = self.g("POST", "/api/concierge/quote",
                          {"alloggio_id": "unica", "check_in": "2026-09-01",
                           "check_out": "2026-09-03", "party": 2})
            if s != 200:
                return ("no_quote", s)
            s2, b = self.g("POST", "/api/concierge/book",
                           {"quote_token": q["quote_token"], "email": "c%d@x.it" % i})
            return ("BOOKED" if s2 == 201 else "no", s2)
        esiti = self._parallelo(cliente, 30)
        vincitori = [e for e in esiti if isinstance(e, tuple) and e[0] == "BOOKED"]
        eccezioni = [e for e in esiti if isinstance(e, tuple) and e[0] == "EXC"]
        self.assertEqual(len(eccezioni), 0, "crash sotto carico: %r" % eccezioni[:3])
        self.assertEqual(len(vincitori), 1,
                         "OVERBOOKING o stanza persa: %d vincitori su 30" % len(vincitori))
        # la stanza risulta davvero occupata
        s, q2 = self.g("POST", "/api/concierge/quote",
                       {"alloggio_id": "unica", "check_in": "2026-09-01",
                        "check_out": "2026-09-03", "party": 2})
        self.assertFalse(q2.get("quote_token"))

    def test_metriche_avanzate_endpoint(self):
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@load.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        # NB: l'host del catalogo è h1 (pubblicato in setUp); registro un annuncio suo
        tok = c["token"]
        self.g("POST", "/api/host/pubblica",
               {"slug": "mia", "titolo": "Mia", "citta": "Roma",
                "prezzo_notte_cents": 9000, "capacita": 2}, {"X-Host-Token": tok})
        s, d = self.g("GET", "/api/host/metriche_avanzate", h={"X-Host-Token": tok})
        self.assertEqual(s, 200, d)
        self.assertIn("metriche", d)
        s, _ = self.g("GET", "/api/host/metriche_avanzate")
        self.assertEqual(s, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
