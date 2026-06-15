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


class TestCIWorkflow(unittest.TestCase):
    def test_workflow_esiste_e_lancia_la_suite(self):
        import yaml
        with open(os.path.join(".github", "workflows", "ci.yml"), encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        # 'on' viene interpretato da YAML come True -> accetto entrambe le chiavi
        trigger = doc.get("on", doc.get(True))
        self.assertIn("push", trigger)
        self.assertIn("pull_request", trigger)
        steps = doc["jobs"]["test"]["steps"]
        testo = json.dumps(steps)
        self.assertIn("actions/checkout", testo)
        self.assertIn("actions/setup-python", testo)
        self.assertIn("unittest discover", testo)


if __name__ == "__main__":
    unittest.main()
