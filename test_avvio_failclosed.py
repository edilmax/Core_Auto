"""Test collaudo — l'avvio DEVE fallire CHIUSO se mancano le chiavi d'accesso.

MINA TROVATA in collaudo 2026-07-15 (non era una falla attiva: in prod le chiavi ci sono e
l'ho verificato live — tutti gli endpoint host/admin rispondono 401 — ma era un default
PERICOLOSO):
  `RouterHTTP._auth_host` ha un ramo comodo per lo sviluppo:
      if self._host_key is None: return True      # passa CHIUNQUE
  e gli endpoint host ripiegano su `query['host_id']` quando non c'e' un token:
      host_id = self._host_id_da_token(headers) or query.get("host_id")
  Combinati: se HOST_KEY sparisce dall'ambiente (server nuovo, typo, .env resettato) l'API
  host diventa APERTA A TUTTI -> `/api/host/payout?host_id=<tizio>` restituirebbe payout,
  prenotazioni e dati personali di QUALSIASI host. Un fail-OPEN silenzioso: peggio del sito giu'.

FIX al confine del deploy (`main_casavip.py`), non nel router: cosi' i test che usano
`crea_router()` in modalita' sviluppo restano invariati, ma un DEPLOY senza chiavi non parte.
"""
from __future__ import annotations

import os
import unittest


class TestAvvioFailClosed(unittest.TestCase):

    def setUp(self):
        self._orig = dict(os.environ)
        os.environ["CASAVIP_SEGRETO"] = "00112233445566778899aabbccddeeff"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig)

    def _avvia(self):
        import importlib
        import main_casavip
        importlib.reload(main_casavip)
        return main_casavip.main()

    def test_senza_host_key_non_parte(self):
        """Meglio non partire che partire spalancati."""
        os.environ.pop("HOST_KEY", None)
        os.environ["ADMIN_KEY"] = "x"
        with self.assertRaises(SystemExit) as ctx:
            self._avvia()
        self.assertEqual(ctx.exception.code, 2)

    def test_senza_admin_key_non_parte(self):
        os.environ["HOST_KEY"] = "x"
        os.environ.pop("ADMIN_KEY", None)
        with self.assertRaises(SystemExit) as ctx:
            self._avvia()
        self.assertEqual(ctx.exception.code, 2)

    def test_chiave_vuota_vale_come_mancante(self):
        """HOST_KEY='' non deve valere: `or None` la trasformerebbe in dev-open."""
        os.environ["HOST_KEY"] = ""
        os.environ["ADMIN_KEY"] = "x"
        with self.assertRaises(SystemExit):
            self._avvia()

    def test_il_ramo_dev_open_esiste_ancora_nel_router(self):
        """Se un domani il router diventasse fail-closed da solo, questa guardia va rivista.

        Documenta PERCHE' la guardia sta in main e non nel router: i test usano crea_router()
        senza chiavi e si appoggiano al ramo dev-open.
        """
        import io
        with io.open("fase83_server.py", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("if self._host_key is None:", src,
                      "il router non ha piu' il ramo dev-open: la guardia in main va rivalutata")


if __name__ == "__main__":
    unittest.main()
