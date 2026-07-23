"""GUARDIA: fase162 (soldi/hold) deve avere un `logger` definito.

Bug trovato da ruff (F821) 2026-07-23: i gestori `except` usavano `logger.warning(...)` senza
che `logger` fosse mai importato/definito -> in produzione, quando un fail-safe scattava,
si andava in NameError invece di loggare-e-proseguire (l'"ISOLATO" diventava un crash).
Rossa sul codice vecchio (nessun attributo `logger` nel modulo).
"""
import logging
import unittest

import fase162_pagamenti_pendenti as PP


class TestLoggerDefinito(unittest.TestCase):
    def test_logger_e_un_logger_vero(self):
        self.assertTrue(hasattr(PP, "logger"), "fase162 non definisce `logger` -> NameError negli except")
        self.assertIsInstance(PP.logger, logging.Logger)

    def test_gli_except_lo_usano_senza_crash(self):
        # il logger deve rispondere ai metodi usati negli except (warning) senza sollevare
        try:
            PP.logger.warning("prova guardia (ignorare)")
        except Exception as e:
            self.fail("logger.warning ha sollevato: %s" % e)


if __name__ == "__main__":
    unittest.main(verbosity=2)
