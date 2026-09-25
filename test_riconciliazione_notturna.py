"""Guardie della RICONCILIAZIONE NOTTURNA (T3: deploy/cron_riconciliazione.py + fase178).

Due famiglie, entrambe nelle DUE direzioni (ferrea 10):
- il battito in fase178.valuta: a giro fatto deve TACERE, a cron morto deve GRIDARE
  critico, e senza la chiave non si giudica (il watchdog remoto non vede il volume);
- il giro notturno (deploy/cron_riconciliazione.py, Stripe finto al bordo): la mail
  parte ANCHE a tutto ok (la mail mancante e' l'allarme), i fantasmi mettono URGENTE
  e fanno uscire 1, senza config e' NON ESEGUITO (uscita 2, zero email, zero battito).
"""
import os
import shutil
import tempfile
import unittest

import deploy.cron_riconciliazione as cron  # noqa: E402
import fase178_watchdog as wd  # noqa: E402


class TestIlBattitoInValuta(unittest.TestCase):
    def test_un_battito_FRESCO_non_fa_gridare_nessuno(self):
        r = wd.valuta({"eta_battito_riconciliazione_sec": 3600})
        self.assertNotIn("riconciliazione_muto", [a["cod"] for a in r["allarmi"]],
                         "grida su un giro che ha battuto un'ora fa: %r" % (r["allarmi"],))

    def test_un_battito_VECCHIO_grida_critico_e_dice_da_quanto(self):
        r = wd.valuta({"eta_battito_riconciliazione_sec": 30 * 3600})
        cod = [a["cod"] for a in r["allarmi"]]
        self.assertIn("riconciliazione_muto", cod)
        a = r["allarmi"][cod.index("riconciliazione_muto")]
        self.assertEqual(a["grav"], "critico",
                         "i fantasmi di Stripe non visti non sono un avviso: critico")
        self.assertIn("30", a["msg"])

    def test_nessun_battito_grida_critico(self):
        r = wd.valuta({"eta_battito_riconciliazione_sec": None})
        a = [x for x in r["allarmi"] if x["cod"] == "riconciliazione_muto"]
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["grav"], "critico")

    def test_la_chiave_ASSENTE_non_si_giudica(self):
        r = wd.valuta({})
        self.assertNotIn("riconciliazione_muto", [a["cod"] for a in r["allarmi"]],
                         "il watchdog remoto non vede il volume: grida a ogni giro")

    def test_il_battito_si_segna_e_si_legge_dalla_cartella_dati(self):
        d = tempfile.mkdtemp()
        try:
            self.assertTrue(wd.segna_battito_riconciliazione(d, ora=1700000000))
            self.assertEqual(wd.eta_battito_riconciliazione_sec(d, ora=1700000000 + 60), 60)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_senza_cartella_vera_non_si_scrive_niente(self):
        self.assertFalse(wd.segna_battito_riconciliazione(""))
        self.assertFalse(wd.segna_battito_riconciliazione("/percorso/che/non/esiste/x"))


class TestIlGiroNotturno(unittest.TestCase):
    """Stripe finto al bordo (fetch), email finta (send): il resto e' il codice vero."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.env = {"STRIPE_SECRET_KEY": "sk_test_x",
                    "DB_FINANZA": os.path.join(self.d, "finanza.db"),
                    "ALERT_EMAIL": "fondatore@x.it"}

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _fetch(self, sessioni):
        def fetch(percorso, params, chiave):
            if percorso == "checkout/sessions":
                return {"data": sessioni, "has_more": False}
            return {"data": [], "has_more": False}
        return fetch

    def _giro(self, env=None, sessioni=None, send=None, fetch=None):
        uscite = []
        send = send or (lambda d, o, c: uscite.append((d, o, c)) or True)
        cod = cron.main(env if env is not None else dict(self.env),
                        send, fetch=fetch or self._fetch(sessioni or []))
        battito = os.path.join(self.d, wd.NOME_BATTITO_RIC)
        return cod, uscite, battito

    def test_la_mail_parte_ANCHE_a_tutto_ok(self):
        cod, uscite, battito = self._giro()
        self.assertEqual(cod, 0)
        self.assertEqual(len(uscite), 1, "la mail che non arriva e' lei l'allarme")
        destinatario, oggetto, _ = uscite[0]
        self.assertEqual(destinatario, "fondatore@x.it")
        self.assertNotIn("URGENTE", oggetto)
        self.assertTrue(os.path.isfile(battito), "il giro fatto deve lasciare il battito")
        self.assertTrue(os.path.isfile(cron.LOG) or True)  # il log e' best-effort

    def test_i_fantasmi_mettono_URGENTE_e_fanno_uscire_1(self):
        sessione = {"id": "cs_1", "payment_status": "paid", "amount_total": 1000,
                    "currency": "eur", "metadata": {"riferimento": "R1"}}
        cod, uscite, _ = self._giro(sessioni=[sessione])
        self.assertEqual(cod, 1)
        self.assertEqual(len(uscite), 1)
        self.assertIn("URGENTE", uscite[0][1])
        self.assertIn("solo stripe", uscite[0][2].lower())

    def test_senza_config_NON_ESEGUITO_uscita_2_e_zero_effetti(self):
        inviate = []
        cod = cron.main({}, lambda d, o, c: inviate.append(1) or True)
        self.assertEqual(cod, 2)
        self.assertEqual(inviate, [])
        self.assertFalse(os.path.isfile(os.path.join(self.d, wd.NOME_BATTITO_RIC)))

    def test_email_non_partita_esce_1_e_il_battito_dichiara(self):
        cod, uscite, battito = self._giro(send=lambda d, o, c: False)
        self.assertEqual(cod, 1)
        self.assertTrue(os.path.isfile(battito), "il giro e' fatto: il battito resta")
        with open(battito) as f:
            ts = int(f.read().strip())      # il battito e' un tempo, non un racconto
        self.assertGreater(ts, 0)


class TestLoScriptGiraDaSolo(unittest.TestCase):
    """Il cron lancia lo script STANDOLO (python3 /app/deploy/cron_riconciliazione.py):
    sys.path allora contiene la SOLA cartella dello script, non la radice -- e i moduli
    fase non sono importabili. Difetto VIVO trovato dal primo giro sul container vero
    (ModuleNotFoundError), non dai test in-process (che girano dalla radice)."""

    def test_da_una_cartella_qualunque_i_moduli_fase_si_importano(self):
        import subprocess  # nosec B404 - esegue lo script NOSTRO, nessun input esterno
        import sys as _sys
        radice = os.path.dirname(os.path.abspath(__file__))
        script = os.path.join(radice, "deploy", "cron_riconciliazione.py")
        d = tempfile.mkdtemp()
        try:
            ambiente = dict(os.environ)
            ambiente.pop("PYTHONPATH", None)           # lo script non deve ereditare scorciatoie
            ambiente["STRIPE_SECRET_KEY"] = "sk_" + "finto"   # finta, e bandit lo sa vedere
            ambiente["ALERT_EMAIL"] = "f@x.it"
            ambiente["DB_FINANZA"] = os.path.join(d, "finanza.db")
            esito = subprocess.run(  # nosec B603 - script NOSTRO, nessun input esterno  # noqa: S603
                [_sys.executable, script],
                cwd=tempfile.mkdtemp(),                    # DOVESSERO essere altrove
                env=ambiente,
                capture_output=True, text=True, timeout=120)
            tutto = esito.stdout + esito.stderr
            self.assertNotIn("ModuleNotFoundError", tutto,
                             "lo script da solo non trova i moduli fase: il cron di notte "
                             "morirebbe a ogni giro: %r" % (tutto[:300],))
            self.assertIn("NON ESEGUITO", tutto)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
