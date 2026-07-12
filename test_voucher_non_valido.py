"""Link voucher non valido/scaduto -> pagina GENTILE (non un errore tecnico crudo)."""
import unittest

from fase83_server import pagina_voucher_non_valido_html, pagina_voucher_html


class _SysFinto:
    firma = None      # senza firma, pagina_voucher_html -> None (token non verificabile)


class TestVoucherNonValido(unittest.TestCase):
    def test_pagina_gentile_it(self):
        h = pagina_voucher_non_valido_html("it")
        self.assertIn("BookinVIP", h)
        self.assertIn("non è valido", h)
        self.assertIn("info@bookinvip.com", h)
        self.assertIn("<html", h)                 # è una PAGINA, non un JSON di errore
        self.assertNotIn("\"errore\"", h)

    def test_pagina_gentile_en(self):
        h = pagina_voucher_non_valido_html("en")
        self.assertIn("isn't valid", h)
        self.assertIn('lang="en"', h)

    def test_token_finto_non_apre_voucher(self):
        # un token a caso (es. 'esempio') non produce un voucher -> None -> pagina gentile a valle
        self.assertIsNone(pagina_voucher_html(_SysFinto(), "esempio", "it"))


if __name__ == "__main__":
    unittest.main()
