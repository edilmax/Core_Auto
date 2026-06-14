#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test FASE 6 - Onboarding partner automato (+ Sentinella V8 reintrodotta).

Adattati all'architettura reale: si usa DatabaseCandidati con un file SQLite
temporaneo (il modello e' connessione-per-operazione) e la connection factory
e' DatabaseCandidati.connessione. La 'sentinella' e' SentinellaV8.

Esecuzione:  python -m unittest test_fase6_onboarding -v
"""

import os
import tempfile
import unittest

import assistente_gestionale as ag


class TestFase6Onboarding(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = ag.DatabaseCandidati(os.path.join(self._tmp.name, "db.sqlite3"))
        self.sentinella = ag.SentinellaV8(self.db.connessione)
        self.engine = ag.PartnerOnboardingEngine(self.db.connessione,
                                                 self.sentinella)

    def tearDown(self):
        self._tmp.cleanup()

    def test_onboarding_completo(self):
        # pending -> parsing_ok -> verifying -> verified -> probation
        result = self.engine.processa_nuovo_partner(
            "+39123456789",
            "Sono Marco, chef con 10 anni esperienza, email marco@chef.it")
        self.assertEqual(result["status"], "verifying")
        self.assertIn("token", result)

        result = self.engine.verifica_codice("+39123456789", result["token"])
        self.assertEqual(result["status"], "probation")
        self.assertGreaterEqual(result["score"], 50)

    def test_rate_limiting_onboarding(self):
        # 4 tentativi in 1 ora sullo stesso sender -> banned
        for _ in range(4):
            self.engine.processa_nuovo_partner("+39999999999", "test")
        partner = self.engine._get_partner("+39999999999")
        self.assertEqual(partner["status"], "banned")

    def test_codice_errato_retry(self):
        self.engine.processa_nuovo_partner("+39111111111", "Test partner")
        result = self.engine.verifica_codice("+39111111111", "CODICE_ERRATO")
        self.assertEqual(result["error"], "codice_errato")
        self.assertEqual(result["attempts_left"], 2)

    def test_token_scaduto(self):
        self.engine.processa_nuovo_partner("+39222222222", "Test partner")
        conn = self.db.connessione()
        try:
            conn.execute("UPDATE partner_candidates SET token_expiry = "
                         "datetime('now', '-1 day') WHERE sender_id = ?",
                         ("+39222222222",))
            conn.commit()
        finally:
            conn.close()
        result = self.engine.verifica_codice("+39222222222", "QUALSIASI")
        self.assertEqual(result["error"], "token_scaduto")

    def test_scoring_evolutivo(self):
        self.engine.processa_nuovo_partner("+39333333333", "Test partner")
        partner = self.engine._get_partner("+39333333333")
        self.engine.verifica_codice("+39333333333", partner["verification_token"])

        score_engine = ag.PartnerScoreEvolutivo(self.db.connessione)
        nuovo_score = score_engine.aggiorna_score_post_transazione(
            partner_id=1,
            transazione_data={"puntualita": True, "qualita": 5,
                              "dispute": False, "completamento": True})
        self.assertGreater(nuovo_score, 50)


if __name__ == "__main__":
    unittest.main(verbosity=2)
