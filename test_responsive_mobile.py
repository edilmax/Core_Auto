"""Test FASE 1 (collaudo) - GUARDIA RESPONSIVE telefoni piccoli (320px).

Bug trovato in collaudo 2026-07-15: a 320px il sito sfondava in orizzontale.
  - index.html: `.risultati` usava `minmax(280px,1fr)` ma con `body{padding:1.5rem}` (48px)
    a 320px restano 272px utili -> 280 > 272 -> colonna piu' larga dello schermo -> scroll
    orizzontale. FIX: `minmax(min(280px,100%),1fr)` (la colonna non supera mai il contenitore).
  - host.html: form `.grid{1fr 1fr}` SENZA nessuna media query + elementi-griglia con
    `min-width:auto` (default) -> gli <input> non si restringono sotto la loro larghezza
    intrinseca -> il pannello host sfondava sul telefono. FIX: `min-width:0` sugli
    elementi-griglia + media query che collassa a 1 colonna.

Questi test leggono il CSS reale e bloccano il ritorno del bug (il browser non e' testabile qui,
gli invarianti si'). Puro: nessuna rete, nessun I/O oltre la lettura dei file.
"""
from __future__ import annotations

import os
import re
import unittest

RADICE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.join(RADICE, "deploy")


def _leggi(nome: str) -> str:
    with open(os.path.join(DEPLOY, nome), encoding="utf-8") as f:
        return f.read()


class TestResponsive320(unittest.TestCase):
    """Invarianti che tengono il sito dentro lo schermo sui telefoni piccoli."""

    def test_viewport_presente(self):
        """Senza <meta viewport> il telefono simula 980px e rimpicciolisce tutto."""
        for pag in ("index.html", "host.html"):
            self.assertIn("width=device-width", _leggi(pag),
                          "%s: manca il meta viewport" % pag)

    def test_griglia_risultati_non_sfonda(self):
        """`.risultati`: la colonna minima NON deve poter superare la larghezza disponibile."""
        html = _leggi("index.html")
        m = re.search(r"\.risultati\{[^}]*\}", html)
        self.assertIsNotNone(m, "regola .risultati non trovata")
        regola = m.group(0)
        self.assertIn("minmax(min(", regola.replace(" ", ""),
                      "la colonna deve usare minmax(min(Npx,100%),1fr) o sfonda a 320px")

    def test_nessun_minmax_rigido_nelle_pagine(self):
        """Nessun `minmax(NNNpx` nudo (>=200px) senza min(): sfonderebbe sui telefoni."""
        for pag in ("index.html", "host.html"):
            html = _leggi(pag).replace(" ", "")
            for larg in re.findall(r"minmax\((\d+)px", html):
                self.assertLess(int(larg), 200,
                                "%s: minmax(%spx nudo -> usa minmax(min(%spx,100%%),1fr)"
                                % (pag, larg, larg))

    def test_host_form_collassa_su_telefono(self):
        """host.html: il form a 2 colonne DEVE collassare a 1 colonna sotto 640px."""
        html = _leggi("host.html").replace(" ", "")
        self.assertIn("@media(max-width:640px)", html,
                      "host.html: manca la media query per i telefoni")
        media = html[html.index("@media(max-width:640px)"):]
        self.assertIn(".grid{grid-template-columns:1fr}", media,
                      "host.html: il form .grid deve diventare 1 colonna sul telefono")

    def test_host_griglia_puo_restringersi(self):
        """host.html: gli elementi-griglia servono `min-width:0` o gli input non si restringono."""
        html = _leggi("host.html")
        m = re.search(r"\.grid label\{[^}]*\}", html)
        self.assertIsNotNone(m, "regola .grid label non trovata")
        self.assertIn("min-width:0", m.group(0).replace(" ", ""),
                      ".grid label: serve min-width:0 (default auto = l'input non si restringe)")

    def test_index_no_overflow_orizzontale(self):
        """index.html: guard esplicito contro lo scroll orizzontale accidentale."""
        html = _leggi("index.html").replace(" ", "")
        self.assertIn("overflow-x:hidden", html,
                      "index.html: manca il guard overflow-x sul body")


class TestDesignTokens(unittest.TestCase):
    """FASE 2 carrozzeria — la palette sta in UN posto solo (design tokens).

    Prima: 31 colori hardcoded sparsi per pagina (x3 pagine) e nessun `:root` -> cambiare il
    brand voleva dire caccia al tesoro, e le tinte divergevano tra le pagine. Ora `:root` con
    token semantici; il refactor e' a PIXEL INVARIATI (stessi hex).
    """
    PAGINE = ("index.html", "host.html", "admin.html")

    def test_root_e_token_presenti(self):
        for pag in self.PAGINE:
            html = _leggi(pag)
            self.assertIn(":root{", html, "%s: manca il blocco :root dei design token" % pag)
            for tok in ("--brand:", "--testo:", "--bordo:", "--rosso:"):
                self.assertIn(tok, html, "%s: manca il token %s" % (pag, tok))

    def test_palette_usata_via_var(self):
        """I colori del brand devono passare da var(), non essere ri-scritti a mano."""
        for pag in self.PAGINE:
            html = _leggi(pag)
            self.assertIn("var(--brand)", html, "%s: il brand non usa il token" % pag)

    def test_theme_color_resta_hex(self):
        """<meta theme-color> NON supporta var(): deve restare un hex vero o il colore sparisce."""
        for pag in self.PAGINE:
            m = re.search(r'<meta name="theme-color" content="([^"]+)"', _leggi(pag))
            self.assertIsNotNone(m, "%s: manca theme-color" % pag)
            self.assertRegex(m.group(1), r"^#[0-9a-fA-F]{6}$",
                             "%s: theme-color deve essere hex, non var()" % pag)

    def test_niente_var_in_attributi_svg(self):
        """fill/stroke con var() non risolvono se l'SVG non eredita il :root: vietati."""
        for pag in self.PAGINE:
            html = _leggi(pag)
            for attr in ('fill="var(--', 'stroke="var(--'):
                self.assertNotIn(attr, html, "%s: %s non risolve" % (pag, attr))


if __name__ == "__main__":
    unittest.main()
