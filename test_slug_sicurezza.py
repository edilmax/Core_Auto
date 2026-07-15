"""Test FASE 1 (collaudo) — SICUREZZA slug: niente XSS/traversal dal catalogo.

BUG trovato in collaudo 2026-07-15 (stored XSS, provato): `valida_scheda` accettava QUALSIASI
stringa come `slug`. Lo slug e' auto-generato e ripulito da `fase83._slug_unico` SOLO se l'host
non lo manda; ma via API l'host poteva mandarne uno suo, e uno slug nuovo non ha proprietario
-> `_verifica_proprieta` lo consentiva. Lo slug finisce poi nel frontend dentro:
  - il popup mappa:  onclick="apri('<slug>')"        -> `x');alert(1);//`  = injection JS
  - le card:         data-slug="<slug>"              -> `a" onmouseover=…` = injection HTML
  - gli URL:         /api/catalogo/<slug>            -> `../../etc/passwd` = traversal
FIX alla radice (fase57 `_norm_slug`): lo slug e' NORMALIZZATO a SOLO [a-z0-9-]. Si normalizza
(non si rifiuta) ed e' DETERMINISTICO, cosi' gli import per id esterno (fase77) restano stabili
e il dedup per slug continua a funzionare.
"""
from __future__ import annotations

import re
import unittest

from fase57_vetrina import SLUG_MAX, valida_scheda

SLUG_OK = re.compile(r"^[a-z0-9-]+$")


def _valida(slug):
    return valida_scheda({"host_id": "h", "slug": slug, "titolo": "T", "citta": "Roma",
                          "prezzo_notte_cents": 10000, "capacita": 2})


class TestSlugSicurezza(unittest.TestCase):

    def test_payload_xss_neutralizzati(self):
        """Nessun apice/parentesi/tag puo' entrare nel catalogo (erano injection nel frontend)."""
        cattivi = ["x');alert(1);//",
                   'a" onmouseover=alert(1) x="',
                   "<script>alert(1)</script>",
                   "'; DROP TABLE alloggi;--",
                   "casa<img src=x onerror=alert(1)>"]
        for s in cattivi:
            ok, err, sch = _valida(s)
            self.assertTrue(ok, "%r: atteso normalizzato, non respinto (%s)" % (s, err))
            self.assertRegex(sch.slug, SLUG_OK, "%r -> slug ancora pericoloso: %r" % (s, sch.slug))
            for ch in "'\"<>();/\\":
                self.assertNotIn(ch, sch.slug, "%r: carattere %r sopravvissuto" % (s, ch))

    def test_path_traversal_neutralizzato(self):
        """Lo slug sta negli URL: niente punti/slash o si esce dalla cartella."""
        ok, _, sch = _valida("../../etc/passwd")
        self.assertTrue(ok)
        self.assertEqual(sch.slug, "etc-passwd")
        self.assertNotIn("..", sch.slug)
        self.assertNotIn("/", sch.slug)

    def test_slug_legittimi_invariati(self):
        """NON deve rompere gli annunci esistenti ne' gli import per id esterno (fase77)."""
        for s in ("casa-a-roma", "12345678", "bella-casa-2"):
            ok, _, sch = _valida(s)
            self.assertTrue(ok)
            self.assertEqual(sch.slug, s, "slug legittimo alterato: %r -> %r" % (s, sch.slug))

    def test_normalizzazione_deterministica(self):
        """Stesso input -> stesso slug: il dedup per slug degli import deve restare stabile."""
        for s in ("Bella Casa_Roma", "Appartamento  Centro!!", "ÀÉÎÕÜ casa"):
            primo = _valida(s)[2].slug
            for _ in range(5):
                self.assertEqual(_valida(s)[2].slug, primo)
            self.assertRegex(primo, SLUG_OK)

    def test_slug_vuoto_dopo_pulizia_respinto(self):
        """Se dopo la pulizia non resta nulla, non e' un identificatore: respinto."""
        for s in ('"""', "!!!", "///", "  ", "<>"):
            ok, err, _ = _valida(s)
            self.assertFalse(ok, "%r doveva essere respinto" % s)
            self.assertEqual(err, "slug_non_valido")

    def test_slug_non_stringa_respinto(self):
        for s in (None, 123, [], {}):
            self.assertFalse(_valida(s)[0], "%r doveva essere respinto" % (s,))

    def test_lunghezza_limitata(self):
        """Slug lungo ma plausibile -> TAGLIATO a SLUG_MAX (resta un identificatore)."""
        ok, _, sch = _valida("a" * 200)          # entro LIMITE_CAMPO (256)
        self.assertTrue(ok)
        self.assertLessEqual(len(sch.slug), SLUG_MAX)

    def test_slug_assurdo_respinto(self):
        """Oltre LIMITE_CAMPO (256) resta respinto come prima del fix: anti-abuso, non e' un id."""
        self.assertFalse(_valida("a" * 300)[0])


if __name__ == "__main__":
    unittest.main()
