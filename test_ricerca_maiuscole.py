# -*- coding: utf-8 -*-
"""Guardia RICERCA PUBBLICA CIECA ALLE MAIUSCOLE — fase57_vetrina.cerca.

IL DIFETTO (2026-07-29): il filtro citta della ricerca pubblica confrontava alla lettera
(`a.citta = ?`, collazione BINARY) mentre la colonna conserva la citta COME L'HA SCRITTA
L'HOST. Un ospite che cerca "roma" o "ROMA" non trovava l'annuncio salvato come "Roma": zero
risultati, e al cliente compariva «stiamo aprendo a roma!» mentre la casa era pubblicata.
Perdita di prenotazioni silenziosa e invisibile nei log.
Lo stesso confronto era gia' stato reso insensibile alle maiuscole nel pannello admin
(`tutti_alloggi_pagina`): a restare scoperta era proprio la ricerca che porta i soldi.

LA CORREZIONE (una riga): `LOWER(a.citta) = LOWER(?)`.

VISTO ROSSO: rimettendo `a.citta = ?` questi test falliscono su "roma", "ROMA" e "RoMa".
"""
import unittest

from fase57_vetrina import CriteriRicerca, SchedaAlloggio, crea_catalogo


class TestRicercaMaiuscole(unittest.TestCase):

    def setUp(self):
        self.cat = crea_catalogo()
        self.cat.pubblica(SchedaAlloggio(host_id="h", slug="casa-roma", titolo="Casa a Roma",
                                         citta="Roma", prezzo_notte_cents=10000, capacita=4))

    def _trova(self, citta):
        return self.cat.cerca(CriteriRicerca(citta=citta))

    def test_come_scritta_dall_host(self):
        r = self._trova("Roma")
        self.assertEqual(r["totale"], 1, r)
        self.assertEqual(r["risultati"][0]["slug"], "casa-roma")

    def test_tutto_minuscolo(self):
        r = self._trova("roma")
        self.assertEqual(r["totale"], 1, "l'ospite che scrive 'roma' non trova la casa: %s" % r)
        self.assertEqual(r["risultati"][0]["slug"], "casa-roma")

    def test_tutto_maiuscolo(self):
        r = self._trova("ROMA")
        self.assertEqual(r["totale"], 1, "l'ospite che scrive 'ROMA' non trova la casa: %s" % r)

    def test_maiuscole_miste(self):
        r = self._trova("RoMa")
        self.assertEqual(r["totale"], 1, "l'ospite che scrive 'RoMa' non trova la casa: %s" % r)

    def test_una_citta_diversa_non_deve_comparire(self):
        """Il filtro resta un filtro: insensibile alle maiuscole, non permissivo."""
        self.assertEqual(self._trova("milano")["totale"], 0)
        self.assertEqual(self._trova("rom")["totale"], 0)


if __name__ == "__main__":
    unittest.main()
