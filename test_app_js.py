# -*- coding: utf-8 -*-
"""GUARDIE del compartimento 3 — app.js FONTE UNICA (Single Source of Truth).

Proteggono tre cose:
1) la fonte unica esiste e le 3 pagine importano da li' (alias), senza RIDEFINIRE
   in locale cio' che e' stato unificato (la ridefinizione = torna la divergenza);
2) i sigilli escape aggiunti in questo compartimento non possono sparire
   (galleria modale ospite, badge servizi, tabella "I miei alloggi", onclick admin);
3) le MEZZE-MISURE di escape (togliere solo <>) sono vietate per sempre nelle pagine.
"""
import io
import os
import unittest

RADICE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(RADICE, 'deploy')
PAGINE = ('index.html', 'host.html', 'admin.html')


def _leggi(nome):
    with io.open(os.path.join(BASE, nome), encoding='utf-8') as f:
        return f.read()


class TestFonteUnica(unittest.TestCase):
    def test_app_js_definisce_tutto(self):
        app = _leggi('app.js')
        for pezzo in ('BV.esc =', 'BV.VALUTE =', 'BV.valExp =', 'BV.valSym =',
                      'BV.money =', 'BV.toCents =', 'BV.fromCents =',
                      'BV.linguaIniziale =', 'BV.fetchTempo =', 'BV.codRete =',
                      'BV.getJson =', 'BV.post =', 'BV.ERR_FRASI =',
                      'BV.fraseErrore =', 'BV.conScudo =', 'BV.scudoTasti =',
                      'window.BV = BV'):
            self.assertIn(pezzo, app, pezzo)

    def test_pagine_importano_e_non_ridefiniscono(self):
        # gli ALIAS ci sono; le vecchie COPIE locali non possono tornare
        vietati = ('const _ESC', 'const _ESC_H', 'const A_VEXP', 'const A_VSYM',
                   'const VEXP', 'const VSYM', 'function money(', 'function fmt(',
                   'function esc(', 'function escH(', 'function pickLang(',
                   'function linguaIniziale(', 'function conScudo(',
                   'async function conScudo(', 'function scudoTasti(',
                   'async function getJson(', 'async function fetchTempo(',
                   'function codRete(', 'const ERR_T')
        for p in PAGINE:
            html = _leggi(p)
            self.assertIn('<script src="/app.js', html, p)
            for v in vietati:
                self.assertNotIn(v, html, '%s: RIDEFINIZIONE vietata: %s' % (p, v))
        # alias chiave per pagina (il resto lo copre la guardia helper-per-pagina)
        self.assertIn('const esc = BV.esc;', _leggi('index.html'))
        self.assertIn('const escH = BV.esc;', _leggi('host.html'))
        self.assertIn('const esc = BV.esc;', _leggi('admin.html'))

    def test_csp_nginx_permette_app_js(self):
        # senza 'self' in script-src la CSP BLOCCHEREBBE app.js -> sito senza JS condiviso
        conf = _leggi('nginx.casavip.ssl.conf')
        self.assertIn("script-src 'self'", conf)


class TestSigilliEscape(unittest.TestCase):
    def test_index_galleria_e_badge_escapati(self):
        html = _leggi('index.html')
        # galleria del modale: l'URL foto (fornito dall'host) va escapato nell'attributo src
        self.assertIn('src="${esc(u)}"', html)
        # badge servizi (testo libero dell'host): escapati in card E modale
        self.assertEqual(html.count('${esc(s)}'), 2, 'badge servizi: attesi 2 punti escapati')
        # recensioni: escape pieno, non mezza-misura
        self.assertIn('${esc(txt)}', html)

    def test_host_tabelle_e_righe_escapate(self):
        html = _leggi('host.html')
        for pezzo in ('<td>${escH(a.titolo)}</td>', '<td>${escH(a.citta)}</td>',
                      'data-t="${escH(a.titolo||\'\')}"', 'data-s="${escH(a.slug)}"',
                      'data-r="${escH(r.riferimento)}"',
                      'onclick="apriConv(\'${escH(c.prenotazione_id)}\')"'):
            self.assertIn(pezzo, html, pezzo)

    def test_admin_onclick_e_righe_escapate(self):
        html = _leggi('admin.html')
        self.assertIn("vediChat('${esc(c.prenotazione_id)}'", html)
        self.assertIn("risolviCtr('${esc(c.prenotazione_id)}'", html)
        self.assertIn('data-a="${esc(p.alloggio_id)}"', html)
        self.assertIn('<td>${esc(p.alloggio_id)}</td>', html)

    def test_niente_mezze_misure(self):
        # la firma della mezza-misura (togliere solo < e > o solo le virgolette)
        # non deve MAI tornare nelle pagine: sembra una difesa e non lo e'
        for p in PAGINE:
            html = _leggi(p)
            self.assertNotIn("replace(/[<>]/g,'')", html, p)
            self.assertNotIn('replace(/"/g,\'\')', html, p)
            self.assertNotIn("replace(/[<>&]/g", html, p)
            self.assertNotIn("replace(/</g,'&lt;')", html, p)


class TestPuliziaMinori(unittest.TestCase):
    """Compartimenti ⑤ (pulizie censite) e ④ lato ospite (niente prompt)."""

    def test_niente_service_worker_registrato(self):
        # index e host DISINSTALLANO ("sito sempre fresco"): il register non deve tornare
        for p in ('index.html', 'host.html'):
            html = _leggi(p)
            self.assertNotIn('serviceWorker.register', html, p)
            self.assertIn('getRegistrations', html, p)

    def test_date_default_vive_mai_fisse(self):
        self.assertIn('BV.dataISO = function', _leggi('app.js'))
        self.assertIn('BV.dataISO(7)', _leggi('index.html'))
        for pezzo in ('BV.dataISO(0)', 'BV.dataISO(14)', 'BV.dataISO(30)'):
            self.assertIn(pezzo, _leggi('host.html'), pezzo)
        # niente piu' date scritte fisse negli input (invecchiano e diventano passate)
        for p in ('index.html', 'host.html'):
            self.assertNotIn('value="2026-', _leggi(p), p)

    def test_capacita_mai_non_numero(self):
        self.assertIn("parseInt(document.getElementById('p_cap').value)||1", _leggi('host.html'))

    def test_css_hover_admin_corretto(self):
        html = _leggi('admin.html')
        self.assertIn('button.danger:hover', html)
        self.assertNotIn('.button.danger:hover', html)

    def test_pagine_minori_con_timeout(self):
        for p in ('contratto-host.html', 'diventa-host.html'):
            html = _leggi(p)
            self.assertIn('<script src="/app.js', html, p)
            self.assertIn('BV.fetchTempo(', html, p)
            self.assertNotIn('await fetch(', html, p)


if __name__ == '__main__':
    unittest.main()
