"""
Test Fase 42 / Tavola VIP - Observability (log JSON + metriche + CI).

Copre: il FormatterJSON (JSON valido, correlation_id, eccezione), il RegistroMetriche
thread-safe (conteggio ESATTO sotto concorrenza, istogramma, cronometro, reset,
formato Prometheus), l'aggancio Flask (/metrics + strumentazione richieste) e la
validazione strutturale del workflow CI.
"""
import json
import logging
import os
import sys
import threading
import unittest

from fase42_observability import (FormatterJSON, RegistroMetriche,
                                  registra_metriche, strumenta_app)


class TestLogJSON(unittest.TestCase):
    def _record(self, **extra):
        rec = logging.LogRecord("core.test", logging.INFO, "p.py", 10,
                                "ciao %s", ("mondo",), None)
        for k, v in extra.items():
            setattr(rec, k, v)
        return rec

    def test_json_valido_campi_base(self):
        d = json.loads(FormatterJSON().format(self._record()))
        self.assertEqual(d["msg"], "ciao mondo")
        self.assertEqual(d["livello"], "INFO")
        self.assertEqual(d["logger"], "core.test")
        self.assertIn("ts", d)

    def test_correlation_id_e_extra(self):
        d = json.loads(FormatterJSON().format(self._record(correlation_id="cid-1")))
        self.assertEqual(d["correlation_id"], "cid-1")

    def test_eccezione_allegata(self):
        try:
            raise ValueError("boom")
        except ValueError:
            rec = logging.LogRecord("c", logging.ERROR, "p", 1, "errore", (),
                                    sys.exc_info())
        d = json.loads(FormatterJSON().format(rec))
        self.assertIn("ValueError", d["exc"])


class TestMetriche(unittest.TestCase):
    def setUp(self):
        self.reg = RegistroMetriche()

    def test_contatore_e_etichette(self):
        self.reg.incrementa("prenotazioni_totali")
        self.reg.incrementa("prenotazioni_totali")
        self.reg.incrementa("pagamenti_totali", {"esito": "ok"})
        out = self.reg.esporre()
        self.assertIn("prenotazioni_totali 2", out)
        self.assertIn('pagamenti_totali{esito="ok"} 1', out)
        self.assertIn("# TYPE prenotazioni_totali counter", out)

    def test_conteggio_esatto_sotto_concorrenza(self):
        def w():
            for _ in range(2000):
                self.reg.incrementa("hit")
        ths = [threading.Thread(target=w) for _ in range(8)]
        for t in ths: t.start()
        for t in ths: t.join()
        self.assertIn("hit 16000", self.reg.esporre())   # 8*2000, nessun perso

    def test_istogramma(self):
        self.reg.osserva("durata_secondi", 0.2)
        self.reg.osserva("durata_secondi", 2.0)
        out = self.reg.esporre()
        self.assertIn("# TYPE durata_secondi histogram", out)
        self.assertIn("durata_secondi_count 2", out)
        self.assertIn("durata_secondi_sum 2.2", out)
        self.assertIn('durata_secondi_bucket{le="+Inf"} 2', out)
        self.assertIn('durata_secondi_bucket{le="0.25"} 1', out)   # solo lo 0.2

    def test_cronometra(self):
        with self.reg.cronometra("op_secondi"):
            pass
        self.assertIn("op_secondi_count 1", self.reg.esporre())

    def test_reset(self):
        self.reg.incrementa("x")
        self.reg.reset()
        self.assertNotIn("\nx ", "\n" + self.reg.esporre())

    def test_bucket_ordinati_in_esposizione(self):
        reg = RegistroMetriche(buckets=(1.0, 0.1, 0.5))   # forniti NON ordinati
        reg.osserva("d_secondi", 0.2)
        out = reg.esporre()
        self.assertLess(out.index('le="0.1"'), out.index('le="0.5"'))
        self.assertLess(out.index('le="0.5"'), out.index('le="1.0"'))   # ascendente

    def test_bucket_invalidi_errore(self):
        with self.assertRaises(ValueError):
            RegistroMetriche(buckets=())
        with self.assertRaises(ValueError):
            RegistroMetriche(buckets=(-1, 0))

    def test_help_prometheus(self):
        self.reg.descrivi("ordini", "Numero totale di ordini")
        self.reg.incrementa("ordini")
        self.assertIn("# HELP ordini Numero totale di ordini", self.reg.esporre())


class TestFlask(unittest.TestCase):
    def setUp(self):
        from flask import Flask
        self.reg = RegistroMetriche()
        self.app = Flask("obs_test")
        @self.app.route("/ping")
        def _ping():
            return "pong"
        strumenta_app(self.app, self.reg)
        registra_metriche(self.app, self.reg)
        self.c = self.app.test_client()

    def test_endpoint_metrics(self):
        self.reg.incrementa("manuale")
        r = self.c.get("/metrics")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/plain", r.headers["Content-Type"])
        self.assertIn("manuale 1", r.get_data(as_text=True))

    def test_strumentazione_richieste(self):
        self.c.get("/ping")
        out = self.reg.esporre()
        self.assertIn("http_richieste_totale", out)
        self.assertIn('endpoint="_ping"', out)
        self.assertIn("http_durata_secondi_count", out)

    def test_metrics_non_auto_misurato(self):
        self.c.get("/metrics")
        self.c.get("/metrics")
        # l'endpoint /metrics non deve generare metriche su se stesso
        self.assertNotIn('endpoint="metrics_export"', self.reg.esporre())


class TestCIWorkflow(unittest.TestCase):
    def _doc(self):
        import yaml
        with open(os.path.join(".github", "workflows", "ci.yml"), encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_workflow_esiste_e_lancia_la_suite(self):
        doc = self._doc()
        # 'on' viene interpretato da YAML come True -> accetto entrambe le chiavi
        trigger = doc.get("on", doc.get(True))
        self.assertIn("push", trigger)
        self.assertIn("pull_request", trigger)
        testo = json.dumps(doc["jobs"])
        self.assertIn("actions/checkout", testo)
        self.assertIn("actions/setup-python", testo)
        # la suite INTERA gira per davvero (in un job qualunque, non piu' per forza 'test')
        self.assertIn("unittest discover", testo)

    def test_workflow_hardening(self):
        doc = self._doc()
        # 1) token di CI a privilegi minimi (least-privilege): i job non scrivono nel repo
        self.assertEqual(doc["permissions"]["contents"], "read")
        # 2) la scansione ZAP del sito LIVE NON deve girare ad ogni push (solo schedule/manuale):
        #    e' una tutela della produzione (niente crawl ad ogni commit). Guardia del gating.
        zap_if = doc["jobs"]["zap"].get("if", "")
        self.assertIn("schedule", zap_if)
        self.assertIn("workflow_dispatch", zap_if)

    # NOTA (2026-07-23): le vecchie asserzioni su un singolo job 'test' con matrice
    # multi-versione (fail-fast:false) e cache pip riflettevano un CI SUPERATO. Ora il CI e'
    # multi-job (money-smoke/full-suite/mutazione/qualita/w3c/atheris/zap) su Python 3.9 (= la
    # produzione). Le guardie sopra difendono l'INTENTO che conta: privilegi minimi, la suite
    # intera gira davvero, e ZAP non tocca la produzione ad ogni push.


if __name__ == "__main__":
    unittest.main()
