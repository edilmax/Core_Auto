"""Promemoria post-check-in al cliente: dopo il check-in di una prenotazione PAGATA, il
cliente riceve 'tutto ok? / segnala un problema entro 24h'. Inviato UNA volta sola."""
import os
import shutil
import sqlite3
import tempfile
import unittest

from fase162_pagamenti_pendenti import crea_pagamenti_pendenti
from fase86_email import corpo_promemoria_checkin_html


class TestPromemoria(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.pp = crea_pagamenti_pendenti(os.path.join(self.dir, "p.db"))
        self.pp.inizializza_schema()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _prenota_pagata(self, ref, ci, email="cliente@x.it"):
        self.pp.registra(ref, alloggio_id="casa", check_in=ci, check_out="2026-12-31",
                         email=email, corpo_json='{"voucher_token":"vt.sig","titolo":"Casa Bella"}')
        self.pp.conferma(ref)     # -> 'pagato'

    def test_promemoria_solo_dopo_checkin(self):
        self._prenota_pagata("R1", "2026-01-10")           # check-in passato
        self._prenota_pagata("R2", "2099-01-01")           # check-in futuro
        da = self.pp.da_promemoriare(oggi="2026-06-01")
        refs = [r["riferimento"] for r in da]
        self.assertIn("R1", refs)                          # check-in arrivato
        self.assertNotIn("R2", refs)                       # troppo presto

    def test_inviato_una_volta_sola(self):
        self._prenota_pagata("R3", "2026-01-10")
        self.assertEqual(len(self.pp.da_promemoriare(oggi="2026-06-01")), 1)
        self.pp.segna_promemoria("R3")
        self.assertEqual(self.pp.da_promemoriare(oggi="2026-06-01"), [])   # non riappare

    def test_solo_pagate_con_email(self):
        # 'in_attesa' (non pagata) non riceve il promemoria
        self.pp.registra("R4", alloggio_id="casa", check_in="2026-01-10", check_out="2026-01-12",
                         email="a@b.it")
        self.assertEqual(self.pp.da_promemoriare(oggi="2026-06-01"), [])
        # pagata ma senza email -> niente promemoria
        self.pp.registra("R5", alloggio_id="casa", check_in="2026-01-10", check_out="2026-01-12")
        self.pp.conferma("R5")
        self.assertNotIn("R5", [r["riferimento"] for r in self.pp.da_promemoriare(oggi="2026-06-01")])

    def test_email_template_valido(self):
        html = corpo_promemoria_checkin_html("Casa Bella", "https://bookinvip.com/voucher/vt.sig", lingua="it")
        self.assertIn("Casa Bella", html)
        self.assertIn("24 ore", html)
        self.assertIn("Segnala un problema", html)
        self.assertIn("https://bookinvip.com/voucher/vt.sig", html)
        # XSS-safe
        h2 = corpo_promemoria_checkin_html("<script>x</script>", "")
        self.assertNotIn("<script>x", h2)


if __name__ == "__main__":
    unittest.main()
