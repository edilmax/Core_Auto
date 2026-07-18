"""Collaudo ESTRATTO CONTABILE CERTIFICATO in STREAMING (Centro Fiscale, Incremento 4.1).

Il file fiscale non e' MAI parziale: si legge il giornale riga per riga (generatore lazy,
zero RAM), si calcola la catena hash ON-THE-FLY, e si CHIUDE col footer obbligatorio.
Invarianti:
  1. genera_estratto_csv e' un GENERATORE (streaming, non una lista in RAM);
  2. estratto integro -> footer '# FINE ESTRATTO - INTEGRITÀ VERIFICATA: <hash>' + ogni
     movimento presente (centesimi interi + euro leggibili);
  3. giornale MANOMESSO -> footer '# NON CHIUSO / CORROTTO - manomissione ...' e NIENTE
     'INTEGRITÀ VERIFICATA' (un file corrotto non puo' spacciarsi per buono);
  4. endpoint gated: SENZA sessione Bunker -> 403;
  5. la firma di chiusura (hash) = testa della catena: certifica l'intero estratto.
"""
import inspect
import json
import shutil
import sqlite3
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router


class TestEstrattoStreaming(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.fin = f"{d}/fin.db"
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"h" * 32, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_finanza=self.fin, bunker_password="SuperPw@1"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        fc = self.sis.finanza
        fc.movimento(tipo="incasso", riferimento="B1", soggetto="host:h1",
                     importo_cents=20800, valuta="EUR", causale="pagamento ospite")
        fc.movimento(tipo="tassa_incassata", riferimento="B1", soggetto="comune:Roma",
                     importo_cents=800, valuta="EUR", causale="tassa soggiorno")
        fc.movimento(tipo="payout_host", riferimento="B1", soggetto="host:h1",
                     importo_cents=17000, valuta="EUR", causale="bonifico host")
        self.n = 3

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _sess(self):
        s, out = self.r.gestisci("POST", "/api/bunker/login", {},
                                 json.dumps({"codice": "SuperPw@1"}),
                                 {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(s, 200, out)
        return out["sessione"]

    def _h(self, sess):
        return {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9",
                "X-Bunker-Session": sess}

    def test_e_un_generatore_streaming(self):
        g = self.r.genera_estratto_csv(ip="1.2.3.4")
        self.assertTrue(inspect.isgenerator(g), "l'estratto deve essere un GENERATORE (streaming)")
        primo = next(g)                        # produce senza aver letto tutto
        self.assertIn("BookinVIP", primo)
        g.close()

    def test_integro_footer_e_movimenti(self):
        csv_txt = "".join(self.r.genera_estratto_csv(ip="1.2.3.4"))
        self.assertIn("seq,data_utc,tipo", csv_txt)          # intestazione colonne
        self.assertIn("incasso", csv_txt)
        self.assertIn("208.00", csv_txt)                     # 20800 cents -> euro
        self.assertIn("# FINE ESTRATTO - INTEGRITÀ VERIFICATA:", csv_txt)
        self.assertNotIn("NON CHIUSO", csv_txt)
        # la firma di chiusura = testa della catena (hash dell'ultimo movimento)
        testa = self.sis.finanza.verifica_catena()["testa"]
        self.assertIn("INTEGRITÀ VERIFICATA: " + testa, csv_txt)
        # righe dati == n movimenti
        self.assertEqual(csv_txt.count("# righe,%d" % self.n), 1)

    def test_manomesso_marcato_corrotto(self):
        con = sqlite3.connect(self.fin)
        con.execute("DROP TRIGGER lg_no_update")
        with con:
            con.execute("UPDATE libro_giornale SET importo_cents=1 WHERE seq=1")
        con.close()
        csv_txt = "".join(self.r.genera_estratto_csv(ip="1.2.3.4"))
        self.assertIn("# NON CHIUSO / CORROTTO - manomissione alla riga 1", csv_txt)
        self.assertNotIn("INTEGRITÀ VERIFICATA", csv_txt)

    def test_endpoint_gated_e_shape(self):
        s, _ = self.r.gestisci("GET", "/api/bunker/export_contabile", {}, None,
                               {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(s, 403)                             # senza sessione
        s, d = self.r.gestisci("GET", "/api/bunker/export_contabile", {}, None,
                               self._h(self._sess()))
        self.assertEqual(s, 200, d)
        self.assertTrue(d["catena_integra"])
        self.assertFalse(d["corrotto"])
        self.assertIn("INTEGRITÀ VERIFICATA", d["csv"])


if __name__ == "__main__":
    unittest.main()
