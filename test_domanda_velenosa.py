# -*- coding: utf-8 -*-
"""Guardia CARATTERI VELENOSI sulla lista d'attesa PUBBLICA (fase158 + rotta /api/domanda).

Difetto VERO trovato dalla campagna adversarial del 2026-07-27 (segnalato da un agente fuori dal
proprio compartimento e riprodotto): un surrogato unicode isolato ('\\ud800', che arriva come
escape ASCII dentro il JSON e supera nginx e il decode del body) in email o citta' faceva
esplodere l'INSERT con UnicodeEncodeError -> 500 su una rotta PUBBLICA senza autenticazione
(la cattura di cold-start, cioe' il modulo di crescita piu' importante). Il NUL byte invece
entrava in archivio e troncava la stringa in ogni consumatore a valle (CSV, log, librerie C).

VISTO ROSSO: rimuovendo il filtro _velenoso da _email_ok/_pulisci in fase158_domanda.py questi
test falliscono (UnicodeEncodeError propagata / NUL archiviato).
"""
import json
import os
import shutil
import tempfile
import unittest

from fase158_domanda import crea_gestore_domanda
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

SURROGATO = "\ud800"


class TestDomandaVelenosa(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.g = crea_gestore_domanda(os.path.join(self.d, "dom.db"))
        self.g.inizializza_schema()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_surrogato_in_citta_rifiutato_senza_esplodere(self):
        self.assertFalse(self.g.registra("a@b.it", SURROGATO))       # solo veleno -> niente citta'
        self.assertEqual(self.g.conta(), 0)

    def test_surrogato_in_email_rifiutato(self):
        self.assertFalse(self.g.registra("a" + SURROGATO + "@b.it", "Roma"))
        self.assertEqual(self.g.conta(), 0)

    def test_citta_valida_con_veleno_viene_ripulita_e_salvata(self):
        # una richiesta VERA non deve essere persa per un byte sporco: si ripulisce, non si butta
        self.assertTrue(self.g.registra("a@b.it", "Ro" + SURROGATO + "ma"))
        self.assertEqual(self.g.conta("roma"), 1)

    def test_nul_byte_non_entra_in_archivio(self):
        self.assertTrue(self.g.registra("a@b.it", "Ro\x00ma"))
        righe = self.g.per_citta()
        self.assertTrue(righe)
        for r in righe:
            self.assertNotIn("\x00", r["citta"])

    def test_citta_normale_intatta(self):
        self.assertTrue(self.g.registra("a@b.it", "Città di Roma"))  # accenti e spazi restano
        self.assertEqual(self.g.per_citta()[0]["citta"], "città di roma")


class TestRottaDomandaVelenosa(unittest.TestCase):
    """La rotta pubblica non deve MAI rispondere 500 a un payload velenoso."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"h" * 32,
                                              db_domanda=os.path.join(self.d, "dom.db")))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_rotta_pubblica_mai_500(self):
        for corpo in ('{"email":"a@b.it","citta":"Roma\\ud800"}',
                      '{"email":"a\\ud800@b.it","citta":"Roma"}',
                      '{"email":"a@b.it","citta":"Ro\\u0000ma"}'):
            st, _ = self.r.gestisci("POST", "/api/domanda", {}, corpo, {})
            self.assertIn(st, (201, 422), "payload velenoso -> stato %s (atteso 201/422)" % st)
            self.assertNotEqual(st, 500)


if __name__ == "__main__":
    unittest.main()
