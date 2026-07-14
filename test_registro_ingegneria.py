"""
Guardia di PROCESSO: il REGISTRO_INGEGNERIA.md deve elencare OGNI modulo `faseNN_*.py`.

Regola del fondatore ("da veri ingegneri, così non si perde nulla"): ogni cosa creata va
scritta nel registro. Questo test la rende AUTO-APPLICANTE: se aggiungi una nuova fase e
dimentichi di registrarla, la suite fallisce e ti obbliga ad aggiornare il registro.
"""
import glob
import os
import re
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
REGISTRO = os.path.join(QUI, "REGISTRO_INGEGNERIA.md")


class TestRegistroIngegneria(unittest.TestCase):
    def test_registro_esiste(self):
        self.assertTrue(os.path.exists(REGISTRO),
                        "Manca REGISTRO_INGEGNERIA.md: ogni funzione va registrata lì.")

    def test_ogni_fase_e_registrata(self):
        testo = open(REGISTRO, encoding="utf-8").read()
        moduli = sorted(os.path.basename(p) for p in glob.glob(os.path.join(QUI, "fase*.py")))
        mancanti = [m for m in moduli if m not in testo]
        self.assertEqual(
            mancanti, [],
            "Queste fasi NON sono nel REGISTRO_INGEGNERIA.md (aggiungile all'inventario, "
            "sezione 5, con scopo+stato): %s" % ", ".join(mancanti))

    def test_ha_le_sezioni_chiave(self):
        testo = open(REGISTRO, encoding="utf-8").read()
        for atteso in ("REGOLA DI PROCESSO", "ACCESO e LIVE",
                       "COSTRUITO ma SPENTO", "INVENTARIO COMPLETO"):
            self.assertIn(atteso, testo, "Sezione mancante nel registro: %s" % atteso)


if __name__ == "__main__":
    unittest.main()
