# -*- coding: utf-8 -*-
"""GUARDIE dell'audit "10 moduli" (2026-07-19) — tre invarianti strutturali:

1. SQLITE TIMEOUT: ogni connect su FILE dello stack CasaVIP (fase>=57) dichiara
   timeout>=15 (standard 30, dal bug #36): sotto contesa si ASPETTA il turno invece
   di fallire con 'database is locked' -> False silenzioso (classe del bug prova-foto).
   I ':memory:' sono esclusi (usano _ConnCondivisa col lucchetto).
2. CSV ANTI-FORMULA: i report fiscali (DAC7 + estratto certificato) si aprono in
   Excel: una cella che inizia con = + - @ e' una FORMULA. La cella ostile viene
   neutralizzata (prefisso apostrofo) e ENTRAMBI i generatori passano dal filtro.
3. EMAIL ANTI HEADER-INJECTION: un a-capo in destinatario/oggetto (es. titolo
   annuncio scritto dall'host) inietterebbe header SMTP (Bcc di massa dal nostro
   dominio -> blacklist). Destinatario con a-capo -> rifiutato SENZA invio;
   oggetto -> whitespace collassato in spazi.
"""
import os
import re
import unittest

REPO = os.path.dirname(os.path.abspath(__file__))


class TestSqliteTimeout(unittest.TestCase):
    def test_ogni_connect_su_file_ha_timeout(self):
        colpevoli = []
        for f in sorted(os.listdir(REPO)):
            m = re.match(r"fase(\d+).*\.py$", f)
            if not m or int(m.group(1)) < 57:
                continue
            src = open(os.path.join(REPO, f), encoding="utf-8", errors="replace").read()
            for chiamata in re.finditer(r"sqlite3\.connect\(([^)]*)\)", src):
                args = chiamata.group(1)
                if '":memory:"' in args or "':memory:'" in args:
                    continue
                if "timeout" not in args:
                    riga = src[:chiamata.start()].count("\n") + 1
                    colpevoli.append("%s:%d %s" % (f, riga, args.strip()[:60]))
        self.assertEqual(colpevoli, [],
                         "connect SQLite su file senza timeout (standard: timeout=30):\n"
                         + "\n".join(colpevoli))


class TestCsvAntiFormula(unittest.TestCase):
    def _filtro(self):
        from fase83_server import RouterHTTP
        return RouterHTTP._cella_csv_sicura

    def test_celle_ostili_neutralizzate(self):
        f = self._filtro()
        for ostile in ("=HYPERLINK(\"http://x\",\"clicca\")", "=2+5", "+cmd", "-2+3+cmd",
                       "@SUM(A1)", "\t=1+1", "\r=1"):
            out = f(ostile)
            self.assertTrue(out.startswith("'"), "non neutralizzata: %r -> %r" % (ostile, out))

    def test_valori_legittimi_intatti(self):
        f = self._filtro()
        for buono in ("Rossi Srl", "-12.34", "-5", "150.00", "h_abc", "", 7, 12.5, None,
                      "via Roma 1", "incasso prenotazione"):
            self.assertEqual(f(buono), buono, "alterato senza motivo: %r" % (buono,))

    def test_entrambi_i_generatori_passano_dal_filtro(self):
        src = open(os.path.join(REPO, "fase83_server.py"),
                   encoding="utf-8", errors="replace").read()
        for gen in ("def genera_dac7_csv", "def genera_estratto_csv"):
            inizio = src.index(gen)
            corpo = src[inizio:inizio + 6000]
            self.assertIn("_cella_csv_sicura", corpo,
                          "%s non passa dal filtro anti-formula" % gen)


class TestEmailAntiHeaderInjection(unittest.TestCase):
    def _provider(self, registro):
        from fase86_email import ProviderEmail
        def send(dest, ogg, html):
            registro.append((dest, ogg))
            return True
        return ProviderEmail("smtp.x", 465, "u", "p", "noreply@x.it",
                             send=send, sleep=lambda s: None)

    def test_destinatario_con_acapo_rifiutato_senza_invio(self):
        visti = []
        p = self._provider(visti)
        self.assertFalse(p.invia("a@b.it\r\nRCPT TO: vittima@x.it", "Ciao", "<p>x</p>"))
        self.assertFalse(p.invia("a@b.it\nBcc: vittima@x.it", "Ciao", "<p>x</p>"))
        self.assertEqual(visti, [], "il provider NON deve essere chiamato")

    def test_oggetto_con_acapo_collassato(self):
        visti = []
        p = self._provider(visti)
        self.assertTrue(p.invia("a@b.it", "Preventivo\r\nBcc: vittima@x.it\r\nX", "<p>x</p>"))
        self.assertEqual(len(visti), 1)
        dest, ogg = visti[0]
        self.assertNotIn("\r", ogg)
        self.assertNotIn("\n", ogg)
        self.assertEqual(ogg, "Preventivo Bcc: vittima@x.it X")

    def test_oggetto_normale_intatto(self):
        visti = []
        p = self._provider(visti)
        self.assertTrue(p.invia("a@b.it", "Il tuo preventivo BookinVIP", "<p>x</p>"))
        self.assertEqual(visti[0][1], "Il tuo preventivo BookinVIP")


if __name__ == "__main__":
    unittest.main(verbosity=2)
