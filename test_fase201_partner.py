# -*- coding: utf-8 -*-
"""Guardia PROGRAMMA PARTNER (fase201): GDPR-gate consenso (visto ROSSO: senza consenso non si
scrive NULLA), validazioni, dedup email, tetto orario, persistenza su FILE, rotte pubbliche/admin."""
import json
import os
import re
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase201_partner import MAX_CANDIDATURE_ORA, crea_gestore_partner


class TestGestorePartner(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.orologio = [1000000]
        self.g = crea_gestore_partner(self.d + "/partner.db",
                                      orologio=lambda: self.orologio[0])
        self.g.inizializza_schema()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_registra_valida(self):
        e = self.g.registra("Mario PM", "pm@example.com", "property_manager",
                            citta="Roma", messaggio="Gestisco 30 case", consenso=True)
        self.assertEqual(e, {"ok": True})
        c = self.g.candidati()
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["email"], "pm@example.com")
        self.assertEqual(c[0]["tipo"], "property_manager")

    def test_gdpr_senza_consenso_non_scrive_nulla(self):
        e = self.g.registra("Mario", "pm@example.com", "creator", consenso=False)
        self.assertEqual(e, {"errore": "consenso_richiesto"})
        e2 = self.g.registra("Mario", "pm@example.com", "creator", consenso="true")
        self.assertEqual(e2, {"errore": "consenso_richiesto"})   # solo il booleano True vale
        self.assertEqual(self.g.conta(), 0)                       # ZERO righe scritte

    def test_validazioni(self):
        self.assertIn("errore", self.g.registra("Mario", "niente-email", "creator", consenso=True))
        self.assertIn("errore", self.g.registra("M", "a@b.it", "creator", consenso=True))
        self.assertIn("errore", self.g.registra("Mario", "a@b.it", "hacker", consenso=True))
        self.assertEqual(self.g.conta(), 0)

    def test_dedup_email_aggiorna(self):
        self.g.registra("Mario", "pm@example.com", "creator", consenso=True)
        self.g.registra("Mario Rossi", "PM@EXAMPLE.COM", "agenzia", consenso=True)
        self.assertEqual(self.g.conta(), 1)
        self.assertEqual(self.g.candidati()[0]["tipo"], "agenzia")

    def test_tetto_orario_globale(self):
        for i in range(MAX_CANDIDATURE_ORA):
            e = self.g.registra("Nome %d" % i, "u%d@example.com" % i, "altro", consenso=True)
            self.assertEqual(e, {"ok": True})
        pieno = self.g.registra("Extra", "extra@example.com", "altro", consenso=True)
        self.assertEqual(pieno, {"errore": "riprova_piu_tardi"})
        self.orologio[0] += 3601                                  # passata l'ora, si riparte
        dopo = self.g.registra("Extra", "extra@example.com", "altro", consenso=True)
        self.assertEqual(dopo, {"ok": True})

    def test_persistenza_su_file(self):
        self.g.registra("Mario", "pm@example.com", "creator", consenso=True)
        riaperto = crea_gestore_partner(self.d + "/partner.db")
        self.assertEqual(riaperto.conta(), 1)                     # sopravvive alla riapertura

    def test_campi_lunghi_troncati(self):
        self.g.registra("N" * 500, "x@y.it", "altro", citta="C" * 500,
                        messaggio="M" * 99999, consenso=True)
        c = self.g.candidati()[0]
        self.assertLessEqual(len(c["nome"]), 80)
        self.assertLessEqual(len(c["citta"]), 80)
        self.assertLessEqual(len(c["messaggio"]), 2000)


class TestRottePartner(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"h" * 32,
                                              db_partner=self.d + "/partner.db"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def test_post_pubblica_e_admin_legge(self):
        st, corpo = self.g("POST", "/api/partner",
                           {"nome": "Anna Creator", "email": "anna@example.com",
                            "tipo": "creator", "citta": "Milano",
                            "messaggio": "Blog di viaggi", "consenso": True})
        self.assertEqual((st, corpo), (201, {"ok": True}))
        st2, corpo2 = self.g("GET", "/api/admin/partner", None, {"X-Admin-Key": "ak"})
        self.assertEqual(st2, 200)
        self.assertEqual(corpo2["totale"], 1)
        self.assertEqual(corpo2["candidati"][0]["email"], "anna@example.com")

    def test_post_senza_consenso_422(self):
        st, corpo = self.g("POST", "/api/partner",
                           {"nome": "Anna", "email": "anna@example.com", "tipo": "creator"})
        self.assertEqual(st, 422)
        self.assertEqual(corpo, {"errore": "consenso_richiesto"})

    def test_admin_senza_chiave_401(self):
        st, _ = self.g("GET", "/api/admin/partner", None, {"X-Admin-Key": "sbagliata"})
        self.assertEqual(st, 401)

    def test_json_rotto_400(self):
        st, _ = self.r.gestisci("POST", "/api/partner", {}, "{non-json", {})
        self.assertEqual(st, 400)


class TestPaginaPartner(unittest.TestCase):
    """Sorveglianza della PAGINA pubblica partner.html (guardia «nessuna pagina senza guardiani»):
    il form punta alla rotta VERA, il consenso GDPR c'è, le 8 lingue sono complete, e la pagina
    NON promette percentuali ai partner (le condizioni economiche le firma il fondatore)."""

    @classmethod
    def setUpClass(cls):
        base = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(base, "deploy", "partner.html"), encoding="utf-8") as f:
            cls.pag = f.read()

    def test_form_cablato_alla_rotta_vera(self):
        self.assertIn('fetch("/api/partner"', self.pag)          # stessa rotta del router
        self.assertIn('id="consenso"', self.pag)
        self.assertIn('type="checkbox"', self.pag)
        self.assertIn("consenso:true", self.pag)                  # inviato solo se spuntato

    def test_otto_lingue_complete_stesse_chiavi(self):
        for l in ("it:{", "en:{", "es:{", "fr:{", "de:{", "pt:{", "ja:{", "zh:{"):
            self.assertIn(l, self.pag, "manca la lingua " + l)
        for chiave in ("ok_msg", "err_msg", "err_consenso", "f_invia", "pro_h", "host_h", "nota"):
            self.assertEqual(self.pag.count(chiave + ':"'), 8,
                             "chiave '%s' non presente in tutte le 8 lingue" % chiave)

    def test_onesta_nessuna_percentuale_promessa(self):
        # nei TESTI (blocco TR) niente percentuali: le condizioni economiche le firma il
        # fondatore caso per caso (il 100% del CSS width non c'entra e resta fuori dal blocco)
        m = re.search(r"const TR=\{.*?\n\};", self.pag, re.S)
        self.assertIsNotNone(m)
        self.assertNotRegex(m.group(0), r"\d+\s*%")

    def test_consenso_client_bloccante(self):
        # il submit senza spunta mostra err_consenso e NON chiama la rete
        js = self.pag[self.pag.index("onsubmit"):]
        self.assertLess(js.index("err_consenso"), js.index("fetch("))


if __name__ == "__main__":
    unittest.main()
