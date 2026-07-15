"""Test collaudo — HEAD deve funzionare come GET, senza corpo.

BUG trovato in collaudo 2026-07-15: `BaseHTTPRequestHandler` risponde **501 Unsupported
method ('HEAD')** se il metodo non e' implementato, e non lo era. Verificato in produzione:
  HEAD /            -> 501
  HEAD /api/health  -> 501     (GET /api/health -> 200)
Perche' conta (non e' pedanteria HTTP): i **monitor di uptime** (UptimeRobot & co.) usano HEAD
di default -> avrebbero segnalato "SITO GIU'" mentre il sito e' perfettamente vivo. Un falso
allarme cronico e' peggio di nessun allarme: ci si abitua a ignorarlo.

FIX: `do_HEAD` riusa `do_GET` (stessi header, stesso status) e scarta il corpo con il flag
`_solo_head` sui 4 punti che scrivono `self.wfile`.
"""
from __future__ import annotations

import re
import unittest

import fase83_server


class TestHeadHttp(unittest.TestCase):

    def setUp(self):
        with open(fase83_server.__file__, encoding="utf-8") as f:
            self.src = f.read()

    def test_do_head_esiste(self):
        """Senza do_HEAD, http.server risponde 501 a ogni HEAD."""
        self.assertIn("def do_HEAD(self):", self.src,
                      "manca do_HEAD -> HEAD torna 501 e i monitor dicono 'sito giu''")

    def test_head_riusa_get(self):
        """Stessi header e stesso status di GET: niente logica duplicata che diverge."""
        m = re.search(r"def do_HEAD\(self\):(.+?)def do_OPTIONS", self.src, re.S)
        self.assertIsNotNone(m)
        corpo = m.group(1)
        self.assertIn("self.do_GET()", corpo, "do_HEAD deve riusare do_GET")
        self.assertIn("_solo_head", corpo, "do_HEAD deve segnalare di saltare il corpo")
        self.assertIn("finally", corpo, "il flag va sempre rimesso a posto (anche su eccezione)")

    def test_corpo_saltato_in_head(self):
        """Ogni punto che scrive il corpo deve rispettare il flag: HEAD non ha corpo."""
        scritture = re.findall(r"^\s*self\.wfile\.write\(dati\)", self.src, re.M)
        protette = re.findall(
            r"if not getattr\(self, '_solo_head', False\):.*\n\s*self\.wfile\.write\(dati\)",
            self.src)
        self.assertEqual(len(scritture), len(protette),
                         "%d scritture del corpo ma solo %d protette dal flag HEAD"
                         % (len(scritture), len(protette)))
        self.assertGreaterEqual(len(protette), 4, "attesi almeno 4 punti protetti")


if __name__ == "__main__":
    unittest.main()
