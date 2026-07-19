"""Collaudo MOTORE DAC7 (Incremento 5): raccolta dati fiscali + audit conformità +
aggregazione + report certificato (Bunker only).

Invarianti:
  1. l'host fornisce i dati fiscali (/api/host/dati_fiscali) -> salvati; mancanti calcolati;
  2. aggregazione dal GIORNALE per host/anno/trimestre corretta (lordo = incasso - tassa,
     netto = payout, commissioni = lordo - netto, per trimestre);
  3. CONFORMITÀ (Bunker): elenca host, segnala INCOMPLETI e REPORTABILI (soglia UE
     30 pren O 2000€); flag 'urgente' = reportabile MA dati incompleti;
  4. REPORT DAC7 (Bunker): SOLO host reportabili, con dati fiscali + remunerazione +
     trimestri + immobili; footer '# FINE REPORT DAC7 - INTEGRITÀ: <hash>'; gated (403);
  5. host SOTTO soglia NON compare nel report.
"""
import json
import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router


class TestDAC7(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"h" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_finanza=f"{d}/fin.db", bunker_password="SuperPw@1"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        self.anno = time.gmtime().tm_year
        # 2 host registrati
        self.h_big = self.sis.registro_host.registra("big@x.it", "password12",
                                                     accetta_termini=True).host_id
        self.h_small = self.sis.registro_host.registra("small@x.it", "password12",
                                                       accetta_termini=True).host_id
        fc = self.sis.finanza
        # host BIG: 1 prenotazione da 2500 lordo (>= 2000 -> reportabile)
        fc.movimento(tipo="incasso", riferimento="B1", soggetto="host:" + self.h_big,
                     importo_cents=255000, valuta="EUR", causale="pagamento")
        fc.movimento(tipo="tassa_incassata", riferimento="B1", soggetto="comune:Roma",
                     importo_cents=5000, valuta="EUR", causale="tassa")   # lordo=250000
        fc.movimento(tipo="payout_host", riferimento="B1", soggetto="host:" + self.h_big,
                     importo_cents=210000, valuta="EUR", causale="bonifico")  # netto=210000
        # host SMALL: 1 prenotazione da 300 (sotto soglia)
        fc.movimento(tipo="incasso", riferimento="S1", soggetto="host:" + self.h_small,
                     importo_cents=30000, valuta="EUR", causale="pagamento")
        fc.movimento(tipo="payout_host", riferimento="S1", soggetto="host:" + self.h_small,
                     importo_cents=25000, valuta="EUR", causale="bonifico")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _sess(self):
        s, out = self.r.gestisci("POST", "/api/bunker/login", {},
                                 json.dumps({"codice": "SuperPw@1"}),
                                 {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(s, 200, out)
        return out["sessione"]

    def _hb(self, sess):
        return {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9",
                "X-Bunker-Session": sess}

    def _token_host(self, hid):
        return self.sis.firma_host_token(hid) if hasattr(self.sis, "firma_host_token") else None

    def test_aggregazione_giornale(self):
        agg = self.sis.finanza.aggrega_dac7(self.anno)
        a = agg[self.h_big]
        self.assertEqual(a["n"], 1)
        self.assertEqual(a["lordo"], 250000)          # 255000 - 5000 tassa
        self.assertEqual(a["netto"], 210000)
        self.assertEqual(a["commissioni"], 40000)     # 250000 - 210000
        self.assertEqual(a["tasse"], 5000)
        self.assertEqual(sum(a["trim"].values()), 250000)

    def test_conformita_segnala_incompleti_e_reportabili(self):
        s, d = self.r.gestisci("GET", "/api/bunker/dac7_conformita",
                               {"anno": str(self.anno)}, None, self._hb(self._sess()))
        self.assertEqual(s, 200, d)
        per_host = {h["host_id"]: h for h in d["host"]}
        big = per_host[self.h_big]
        self.assertTrue(big["reportabile"])           # 2500 >= 2000
        self.assertFalse(big["completo"])             # dati fiscali mancanti
        self.assertTrue(big["urgente"])               # reportabile + incompleto = ROSSO
        self.assertIn("codice_fiscale/partita_iva", big["mancanti"])
        self.assertFalse(per_host[self.h_small]["reportabile"])
        self.assertGreaterEqual(d["reportabili"], 1)
        self.assertEqual(d["urgenti"], 1)            # big è reportabile ma incompleto
        self.assertEqual(per_host[self.h_big]["ricavi_cents"], 250000)

    def test_host_fornisce_dati_e_diventa_completo(self):
        # l'host BIG fa login e salva i dati fiscali
        s, c = self.r.gestisci("POST", "/api/host/login", {},
                               json.dumps({"email": "big@x.it", "password": "password12"}),
                               {"X-Forwarded-For": "1.2.3.4"})
        self.assertEqual(s, 200, c)
        tok = c["token"]
        s, o = self.r.gestisci("POST", "/api/host/dati_fiscali", {},
                               json.dumps({"codice_fiscale": "RSSMRA80A01H501U",
                                           "indirizzo_fiscale": "Via Roma 1, Milano",
                                           "paese": "IT", "iban": "IT60X0542811101000000123456",
                                           "tipo_soggetto": "individuo"}),
                               {"X-Host-Token": tok})
        self.assertEqual(s, 200, o)
        self.assertEqual(o["mancanti"], [])           # ora completo
        info = self.sis.registro_host.info_host(self.h_big)
        self.assertEqual(info["codice_fiscale"], "RSSMRA80A01H501U")
        # conformità: ora NON è più urgente
        s, d = self.r.gestisci("GET", "/api/bunker/dac7_conformita",
                               {"anno": str(self.anno)}, None, self._hb(self._sess()))
        big = {h["host_id"]: h for h in d["host"]}[self.h_big]
        self.assertTrue(big["completo"])
        self.assertFalse(big["urgente"])

    def test_report_dac7_solo_reportabili_e_footer(self):
        s, _ = self.r.gestisci("GET", "/api/bunker/dac7_report",
                               {"anno": str(self.anno)}, None,
                               {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(s, 403)                       # senza sessione Bunker
        s, d = self.r.gestisci("GET", "/api/bunker/dac7_report",
                               {"anno": str(self.anno)}, None, self._hb(self._sess()))
        self.assertEqual(s, 200, d)
        csv_txt = d["csv"]
        self.assertTrue(d["integro"])
        self.assertIn("# FINE REPORT DAC7 - INTEGRITÀ:", csv_txt)
        self.assertIn(self.h_big, csv_txt)             # reportabile presente
        self.assertNotIn(self.h_small, csv_txt)        # sotto soglia ESCLUSO
        self.assertIn("2500.00", csv_txt)              # corrispettivo lordo eur
        self.assertIn("# host_reportabili,1", csv_txt)


if __name__ == "__main__":
    unittest.main()
