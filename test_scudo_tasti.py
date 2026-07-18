# -*- coding: utf-8 -*-
"""GUARDIE: scudo anti-doppio-clic + esiti visivi (compartimento 'UX e Feedback dei Tasti').

Cosa proteggono (sul codice PRECEDENTE fallivano):
- doppio clic su Pubblica/Prenota/Registrati/Approva/Campagna = azione doppia
  (annuncio duplicato, doppia registrazione, doppia campagna social);
- Approva/Rifiuta richiesta senza alcun esito (fetch alla cieca): se falliva,
  l'host credeva di avere approvato;
- Sospendi/Pubblica in admin senza alcun esito in caso di errore.

Le guardie sono STATICHE (leggono i 3 file deploy/*.html): se qualcuno rimuove lo
scudo, il finally, il blocco-larghezza o gli esiti, la suite diventa rossa.
"""
import io
import os
import re
import unittest

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deploy')


def _leggi(nome):
    with io.open(os.path.join(BASE, nome), encoding='utf-8') as f:
        return f.read()


PAGINE = ('index.html', 'host.html', 'admin.html')


class TestScudoPresenteOvunque(unittest.TestCase):
    """Lo scudo esiste, identico nel comportamento, in TUTTE e 3 le pagine."""

    def test_conscudo_definito_in_tutte_le_pagine(self):
        for p in PAGINE:
            html = _leggi(p)
            self.assertIn('async function conScudo(btn, fn)', html, p)
            self.assertIn('function scudoTasti(ids)', html, p)

    def test_scudo_spegne_il_tasto_e_mostra_attesa(self):
        for p in PAGINE:
            html = _leggi(p)
            corpo = html.split('async function conScudo', 1)[1][:900]
            self.assertIn('btn.disabled = true', corpo, p)
            self.assertIn("btn.innerHTML = '⏳'", corpo, p)

    def test_scudo_si_riaccende_sempre_anche_su_errore(self):
        # finally = il tasto NON puo' restare morto se la chiamata fallisce
        for p in PAGINE:
            corpo = _leggi(p).split('async function conScudo', 1)[1][:900]
            self.assertIn('finally', corpo, p)
            self.assertIn('btn.disabled = false', corpo, p)

    def test_scudo_non_fa_saltare_il_layout(self):
        # blocca la larghezza prima dello spinner e la libera dopo (UI che non si accavalla)
        for p in PAGINE:
            corpo = _leggi(p).split('async function conScudo', 1)[1][:900]
            self.assertIn("btn.style.minWidth = w+'px'", corpo, p)
            self.assertIn("btn.style.minWidth = ''", corpo, p)

    def test_scudo_anti_rientro_e_resta_spento(self):
        for p in PAGINE:
            corpo = _leggi(p).split('async function conScudo', 1)[1][:900]
            # un tasto gia' spento non riparte (il doppio clic muore qui)
            self.assertIn('if(!btn || btn.disabled) return;', corpo, p)
            # chi vuole restare spento dopo il successo viene rispettato
            self.assertIn('restaSpento', corpo, p)


class TestScudoHost(unittest.TestCase):
    HTML = None

    @classmethod
    def setUpClass(cls):
        cls.HTML = _leggi('host.html')

    def test_tasti_fissi_avvolti(self):
        m = re.search(r"scudoTasti\(\[(.*?)\]\)", self.HTML, re.S)
        self.assertIsNotNone(m, 'manca la chiamata scudoTasti in host.html')
        ids = re.findall(r"'([^']+)'", m.group(1))
        attesi = {'btnLogin', 'btnRegister', 'btnPubblica', 'btnPin', 'btnDisp',
                  'btnTrasp', 'btnHostCanc', 'btnRange', 'btnIcal', 'cv_send',
                  'btnCalTutti', 'btnCalPrezzi', 'btnIcalExport', 'btnStripeLink',
                  'btnTgLink', 'btnImporta', 'btnMetriche', 'btnMiei', 'btnExport',
                  'btnCal', 'btnMsgInvia', 'btnMsgCarica', 'btnDp', 'btnSeo'}
        self.assertTrue(attesi.issubset(set(ids)),
                        'mancano dallo scudo: %s' % (attesi - set(ids)))

    def test_tasti_riga_avvolti(self):
        # Approva/Rifiuta + Sospendi/Modifica/Elimina nelle righe: conScudo inline
        for frammento in ("conScudo(b,()=>dec(b.dataset.r,true)",
                          "conScudo(b,()=>dec(b.dataset.r,false)",
                          "conScudo(b,()=>cambiaStato(",
                          "conScudo(b,()=>caricaModifica(",
                          "conScudo(b,()=>eliminaAnnuncio("):
            self.assertIn(frammento, self.HTML, frammento)

    def test_approva_rifiuta_mostra_esito(self):
        # niente piu' fetch alla cieca: dec passa da post() e mostra ✅/❌ in req_msg
        self.assertIn('id="req_msg"', self.HTML)
        corpo = self.HTML.split('const dec = async (rif, ok)=>{', 1)
        self.assertEqual(len(corpo), 2, 'dec riscritta o rimossa: aggiornare la guardia')
        dec = corpo[1][:600]
        self.assertIn("post('/api/host/richieste/'+(ok?'approva':'rifiuta')", dec)
        self.assertIn("'✅ '+T(ok?'req_ok_app':'req_ok_rif')", dec)
        # dal compartimento Gestione Errori: il codice passa da fraseErrore (frase gentile)
        self.assertIn("'❌ '+(r.data.errore?fraseErrore(r.data.errore):r.status)", dec)

    def test_esiti_tradotti_in_8_lingue(self):
        self.assertEqual(self.HTML.count('req_ok_app:'), 8)
        self.assertEqual(self.HTML.count('req_ok_rif:'), 8)


class TestScudoAdmin(unittest.TestCase):
    HTML = None

    @classmethod
    def setUpClass(cls):
        cls.HTML = _leggi('admin.html')

    def test_tasti_fissi_avvolti(self):
        m = re.search(r"scudoTasti\(\[(.*?)\]\)", self.HTML, re.S)
        self.assertIsNotNone(m)
        ids = set(re.findall(r"'([^']+)'", m.group(1)))
        self.assertTrue({'btnCarica', 'btnCampagna', 'btnControversie',
                         'btnCancellaHost'}.issubset(ids), ids)

    def test_tasti_riga_avvolti(self):
        self.assertIn("conScudo(b,()=>cambiaStatoAdmin(", self.HTML)
        self.assertIn("conScudo(b,()=>rimborsa(b.dataset))", self.HTML)
        self.assertIn("conScudo(this,()=>vediChat(", self.HTML)
        self.assertIn("conScudo(this,()=>risolviCtr(", self.HTML)

    def test_sospendi_pubblica_mostra_esito(self):
        corpo = self.HTML.split('async function cambiaStatoAdmin', 1)
        self.assertEqual(len(corpo), 2)
        fn = corpo[1][:900]
        # esito in OGNI ramo: successo, errore del server, errore di rete (con frase
        # gentile che distingue anche il timeout: fraseErrore(codRete(e)))
        self.assertIn("msg('✅ '+slug+' → '+stato", fn)
        self.assertIn("msg('❌ '+slug+':", fn)
        self.assertIn("msg('❌ '+fraseErrore(codRete(e))", fn)
        # il vecchio difetto (successo silenzioso senza else) non deve tornare
        self.assertNotIn('if(res.status===200) caricaAlloggi();', fn)


class TestScudoOspite(unittest.TestCase):
    HTML = None

    @classmethod
    def setUpClass(cls):
        cls.HTML = _leggi('index.html')

    def test_tasti_avvolti(self):
        m = re.search(r"scudoTasti\(\[(.*?)\]\)", self.HTML, re.S)
        self.assertIsNotNone(m)
        ids = set(re.findall(r"'([^']+)'", m.group(1)))
        self.assertTrue({'btnPrenota', 'btnMappa'}.issubset(ids), ids)
        # Cerca: lo scudo passa dal submit del form (Enter incluso)
        self.assertIn("conScudo(document.getElementById('btnCerca'), cerca)", self.HTML)
        # tasti creati al volo: Avvisami (waitlist) e Invia preventivo
        self.assertIn('b.onclick=()=>conScudo(b, async ()=>{', self.HTML)
        self.assertIn('bpm.onclick=()=>conScudo(bpm, async()=>{', self.HTML)

    def test_invia_preventivo_resta_spento_dopo_successo(self):
        # prima faceva bpm.disabled=true (che lo scudo avrebbe riacceso):
        # ora usa la convenzione restaSpento, che lo scudo rispetta
        self.assertIn("bpm.dataset.restaSpento='1'", self.HTML)
        self.assertNotIn('bpm.disabled=true', self.HTML)


if __name__ == '__main__':
    unittest.main()
