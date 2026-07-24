# -*- coding: utf-8 -*-
"""SISTEMA ⑩ — AUDIT ACCESSIBILITA' (WCAG) statico + guardia permanente.

Controlla gli invarianti WCAG che si possono provare senza browser sulle 3 pagine
(+ le due minori): lingua dichiarata, zoom NON bloccato, ogni <img> con alt, bottoni
solo-icona con nome accessibile (aria-label), campi-chiave con etichetta, regioni di
stato "live" (gli errori vengono ANNUNCIATI dagli screen reader), e nessun campo
password senza label. Ogni violazione futura fa diventare rossa la suite.
"""
import io
import os
import re
import unittest

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deploy')
PAGINE = ('index.html', 'host.html', 'admin.html')
TUTTE = PAGINE + ('contratto-host.html', 'diventa-host.html')

# bottoni il cui contenuto e' SOLO un'icona/emoji: DEVONO avere aria-label
SOLO_ICONA = ('✕', '‹', '›', '🗑', '❤', '🤍', '📍', '✈', '📷', '▶', '🎵')


def _leggi(nome):
    with io.open(os.path.join(BASE, nome), encoding='utf-8') as f:
        return f.read()


class TestAccessibilita(unittest.TestCase):
    def test_lingua_dichiarata(self):
        for p in TUTTE:
            self.assertRegex(_leggi(p), r'<html[^>]*\blang=', p + ': manca lang su <html>')

    def test_zoom_mai_bloccato(self):
        # WCAG 1.4.4: l'utente DEVE poter ingrandire -> vietati user-scalable=no / maximum-scale
        for p in TUTTE:
            html = _leggi(p)
            self.assertNotIn('user-scalable=no', html, p)
            self.assertNotIn('user-scalable=0', html, p)
            self.assertNotRegex(html, r'maximum-scale\s*=\s*1', p + ': zoom limitato')

    def test_ogni_img_ha_alt(self):
        for p in TUTTE:
            html = _leggi(p)
            # niente falsi positivi: togli commenti HTML, commenti JS e stringhe dove un
            # "<img ...>" e' un ESEMPIO (es. le note anti-XSS), non un vero tag renderizzato
            pulito = re.sub(r'<!--.*?-->', '', html, flags=re.S)
            pulito = re.sub(r'//[^\n]*', '', pulito)
            pulito = re.sub(r'`[^`]*`', '``', pulito)
            for tag in re.findall(r'<img\b[^>]*>', pulito):
                self.assertIn('alt=', tag, '%s: <img> senza alt -> %s' % (p, tag[:80]))

    def test_bottoni_solo_icona_hanno_nome_accessibile(self):
        for p in PAGINE:
            for tag, dentro in re.findall(r'(<button\b[^>]*>)(.*?)</button>', _leggi(p), re.S):
                testo = re.sub(r'<[^>]+>', '', dentro).strip()
                # solo-icona = il testo ripulito e' vuoto o e' una delle icone note
                if testo == '' or testo in SOLO_ICONA:
                    self.assertIn('aria-label', tag,
                                  '%s: bottone icona senza aria-label -> %s' % (p, (tag+testo)[:90]))

    def test_regioni_di_stato_live(self):
        # gli errori/esiti dinamici devono essere ANNUNCIATI: le regioni chiave hanno aria-live
        attesi = {
            'index.html': ['id="risultati"', 'id="mMsg"'],
            'host.html': ['id="msgAuth"', 'id="msgPub"'],
            'admin.html': ['id="msg"'],
        }
        for p, ids in attesi.items():
            html = _leggi(p)
            for idattr in ids:
                # trova il tag che porta quell'id e verifica che abbia aria-live
                m = re.search(r'<[^>]*' + re.escape(idattr) + r'[^>]*>', html)
                self.assertIsNotNone(m, '%s: manca %s' % (p, idattr))
                self.assertIn('aria-live', m.group(0),
                              '%s: %s senza aria-live (errori non annunciati)' % (p, idattr))

    def test_campi_chiave_etichettati(self):
        # i campi password/chiave fuori da un <label> devono avere aria-label
        self.assertIn('aria-label="Chiave host', _leggi('host.html'))
        self.assertIn('aria-label="Chiave amministratore"', _leggi('admin.html'))

    def test_select_e_upload_del_pannello_host_etichettati(self):
        # WCAG 4.1.2 / 1.3.1: un <select> e un <input type=file> FUORI da un <label> devono
        # avere un nome accessibile. Trovati SCOPERTI il 2026-07-24 dall'audit Axe-Core sul
        # pannello host (mai visti prima: gli audit colpivano solo la versione gated/login).
        html = _leggi('host.html')
        m_lang = re.search(r'<select[^>]*id="lang"[^>]*>', html)
        self.assertIsNotNone(m_lang, 'host.html: manca il select #lang')
        self.assertRegex(m_lang.group(0), r'aria-label(ledby)?=',
                         'host.html: il selettore lingua #lang non ha nome accessibile')
        m_file = re.search(r'<input[^>]*id="p_files"[^>]*>', html)
        self.assertIsNotNone(m_file, 'host.html: manca l\'upload foto #p_files')
        self.assertRegex(m_file.group(0), r'aria-label(ledby)?=',
                         'host.html: l\'upload foto #p_files non ha etichetta accessibile')

    def test_close_modale_accessibile_da_tastiera(self):
        html = _leggi('index.html')
        m = re.search(r'<span class="close"[^>]*>', html)
        self.assertIsNotNone(m)
        self.assertIn('role="button"', m.group(0))
        self.assertIn('tabindex="0"', m.group(0))
        self.assertIn('aria-label', m.group(0))
        self.assertIn("getElementById('close').onkeydown", html,
                      'close: manca il gestore tastiera Invio/Spazio')


if __name__ == '__main__':
    unittest.main(verbosity=2)
