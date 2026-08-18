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
import re
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


class TestNessunCodiceInternoInFacciaAllOspite(unittest.TestCase):
    """Il vocabolario degli errori (`BV.ERR_AUTH`) e l'ultima spiaggia di `BV.fraseErrore`.

    DIFETTO VIVO, trovato il 2026-08-18 dal percorso col browser (`collaudi/
    percorso_ospite_host.js`, atto 'rifiuto'): con il gateway dei pagamenti muto, l'ospite
    legge a schermo **`pagamento_non_disponibile`** -- il nostro codice interno -- proprio
    mentre sta cercando di pagare. E' la stessa classe di difetto gia' corretta per
    `motivo` in `index.html` («l'ospite leggeva 'pieno', 'min_notti' cosi' com'erano»),
    rimasta aperta sul ramo `errore`.

    ⛔ E LA CAUSA NON E' LA PAROLA MANCANTE, E' L'ULTIMA SPIAGGIA. `BV.fraseErrore`, quando
    il codice non e' nel vocabolario, restituisce **il codice**. Misurato lo stesso giorno:
    il percorso di prenotazione puo' produrre ~24 codici e 13 non hanno traduzione -- quindi
    tradurne uno per uno sarebbe una cura che lascia viva la malattia, e il prossimo codice
    aggiunto ricomincerebbe da capo. Si chiude la CLASSE (regola ferrea 11: il difetto sta
    in chi chiama, non nel singolo caso), e si traduce a mano solo cio' che un ospite VERO
    incontra davvero.
    """

    # DENOMINATORE DICHIARATO (ogni guardia dichiara il suo, CLAUDE.md). NON sono tutti i
    # codici del server: sono quelli che un ospite ONESTO puo' incontrare percorrendo il
    # sito -- cercare, farsi un preventivo, prenotare. Restano fuori di proposito quelli
    # raggiungibili solo manomettendo la richiesta (`payload_non_oggetto`, `quote_corrotta`,
    # `party_non_valido`...): li' un codice grezzo non fa danno a nessun cliente vero, e
    # pretenderne la traduzione sarebbe lavoro che nessuno legge.
    CODICI_CHE_L_OSPITE_INCONTRA = (
        'pagamento_non_disponibile',   # il gateway non risponde: succede MENTRE paga
        'transazioni_sospese',         # blocco globale acceso
        'quote_scaduta',               # il preventivo e' scaduto guardando la pagina
        'quote_non_valida',
        'preventivo_scaduto',          # ha lasciato la pagina aperta e poi ha premuto Prenota
        'prenotazione_annullata',      # torna su un link di pagamento ormai morto
        'non_quotabile',               # il prezzo non si riesce a calcolare per quelle date
        'date_non_valide',             # partenza prima dell'arrivo
        'alloggio_non_disponibile',
        'non_disponibile',
        'service_unavailable',
        'credito_gia_usato',
    )

    # ⛔ COSA RESTA FUORI, DICHIARATO (D18 punto 3). Gli altri codici del server NON sono
    # tradotti a mano ed e' una scelta: o sono raggiungibili solo manomettendo la richiesta
    # (`payload_non_oggetto`, `quote_corrotta`, `party_non_valido`, `json_non_valido`...), o
    # dicono all'ospite la stessa cosa di un codice che c'e' gia' (`not_found` e
    # `catalogo_non_disponibile`). Per tutti loro vale la frase generica dell'ultima spiaggia,
    # provata dal terzo controllo qui sotto: nessuno di essi puo' piu' uscire in chiaro.

    LINGUE = ('it', 'en', 'es', 'fr', 'de', 'pt', 'ja', 'zh')

    def _vocabolario(self):
        """{lingua: set(codici)} letto DAL FILE VERO, non da una copia scritta qui.

        ⛔ COME SI LEGGE, E PERCHE' COSI'. Nel file ogni lingua sta su UNA RIGA
        (`it:{chiave:'frase',...},`): si prende la riga e si estraggono le chiavi. La prima
        stesura di questa guardia cercava invece il blocco con un'espressione regolare
        `(.*?)\\}` sull'intero testo, e il 2026-08-18 ha prodotto un FALSO ALLARME -- accusava
        l'italiano di non tradurre tre codici che traduce eccome (verificato caricando
        `app.js` in un motore JavaScript vero: 32 codici identici in tutte e 8 le lingue).
        Un falso allarme e' un difetto quanto un allarme mancato: insegna a ignorare il rosso
        (regola ferrea 10). ⚠️ Se un giorno il vocabolario non sara' piu' «una lingua per
        riga», questa guardia lo dice CON QUESTE PAROLE invece di accusare il prodotto.
        """
        sorgente = _leggi('app.js')
        inizio = sorgente.find('BV.ERR_AUTH = {')
        self.assertNotEqual(inizio, -1, "non trovo la definizione `BV.ERR_AUTH = {` in "
                                        "app.js: il vocabolario degli errori e' stato "
                                        "spostato o rinominato, e questa guardia non sa "
                                        "piu' cosa sta leggendo (NON e' un difetto del "
                                        "prodotto: e' questa guardia da aggiornare)")
        fine = sorgente.find('BV.fraseErrore', inizio)
        self.assertGreater(fine, inizio, "non trovo la fine del vocabolario")
        righe = sorgente[inizio:fine].splitlines()
        fuori = {}
        for lingua in self.LINGUE:
            riga = [r for r in righe if r.strip().startswith('%s:{' % lingua)]
            self.assertEqual(len(riga), 1,
                             "la lingua %r non sta su UNA riga sua nel vocabolario (trovate "
                             "%d righe): il formato e' cambiato e questa guardia va "
                             "aggiornata -- non e' un difetto del prodotto"
                             % (lingua, len(riga)))
            # ⛔ LE DUE VIRGOLETTE, non una: l'italiano scrive `email_non_valida:"L'indirizzo
            # ..."` con le DOPPIE, perche' la frase contiene un apostrofo. Cercando solo
            # l'apice questa guardia perdeva 3 chiavi su 32 e accusava l'italiano di non
            # tradurle (falso allarme del 2026-08-18, il secondo dello stesso lettore).
            fuori[lingua] = set(re.findall(r"""[\{,]([a-z][a-z_0-9]*):["']""", riga[0]))
            self.assertTrue(fuori[lingua], "la lingua %r risulta VUOTA: si e' rotto il "
                                           "lettore di questa guardia, non il prodotto"
                            % lingua)
        return fuori

    def test_ogni_lingua_traduce_ESATTAMENTE_gli_stessi_codici(self):
        """Una traduzione a macchie e' peggio di nessuna: chi parla giapponese vedrebbe il
        codice grezzo dove un italiano legge una frase, e nessuno se ne accorgerebbe."""
        voc = self._vocabolario()
        riferimento = voc['it']
        for lingua in self.LINGUE:
            mancanti = sorted(riferimento - voc[lingua])
            in_piu = sorted(voc[lingua] - riferimento)
            self.assertEqual((mancanti, in_piu), ([], []),
                             "la lingua %r non allinea l'italiano: mancano %s, in piu' %s"
                             % (lingua, mancanti, in_piu))

    def test_i_codici_che_l_OSPITE_incontra_sono_TUTTI_tradotti(self):
        voc = self._vocabolario()
        for lingua in self.LINGUE:
            mancanti = [c for c in self.CODICI_CHE_L_OSPITE_INCONTRA if c not in voc[lingua]]
            self.assertEqual(mancanti, [],
                             "in %r un ospite vero puo' vedere questi codici INTERNI invece "
                             "di una frase: %s" % (lingua, mancanti))

    def test_un_codice_SCONOSCIUTO_non_finisce_mai_in_faccia_all_ospite(self):
        """La rete che chiude la CLASSE. Senza questa, ogni codice nuovo aggiunto al server
        nasce gia' capace di uscire in chiaro, e lo si scopre da un cliente."""
        sorgente = _leggi('app.js')
        inizio = sorgente.find('BV.fraseErrore = function')
        self.assertNotEqual(inizio, -1, 'BV.fraseErrore non esiste piu\'')
        corpo = sorgente[inizio:sorgente.find('\n  };', inizio)]
        self.assertNotIn("return String(cod", corpo,
                         "ULTIMA SPIAGGIA GUASTA: quando il codice non e' nel vocabolario, "
                         "fraseErrore restituisce IL CODICE. E' cosi' che l'ospite legge "
                         "'pagamento_non_disponibile' mentre paga. Deve restituire una "
                         "frase generica presa dal vocabolario.")
        voc = self._vocabolario()
        for lingua in self.LINGUE:
            self.assertIn('generico', voc[lingua],
                          "manca la frase generica in %r: senza, l'ultima spiaggia non ha "
                          "niente da dire e tornerebbe a stampare il codice" % lingua)

    def test_un_codice_ASSENTE_torna_VUOTO_cosi_la_catena_dei_tentativi_prosegue(self):
        """DIFETTO MIO, introdotto e trovato lo stesso giorno (2026-08-18), dal percorso col
        browser e non da una rilettura.

        Chi mostra l'errore all'ospite INCATENA i tentativi:
        `fraseErrore(r.motivo) || fraseErrore(r.errore) || t('errore')`. Appena l'ultima
        spiaggia ha cominciato a rispondere con la frase generica, ha risposto anche quando
        il codice era ASSENTE (`r.motivo` non c'e' quasi mai): la catena si fermava al PRIMO
        anello, sempre, e la traduzione buona -- quella del pagamento -- non veniva MAI
        raggiunta. Un difetto invisibile leggendo il codice: a schermo compariva una frase
        umana e sensata, solo che era quella sbagliata."""
        sorgente = _leggi('app.js')
        inizio = sorgente.find('BV.fraseErrore = function')
        corpo = sorgente[inizio:sorgente.find('\n  };', inizio)]
        self.assertIn("if(cod==null || cod==='') return '';", corpo,
                      "l'assenza di codice deve tornare STRINGA VUOTA: se torna una frase, "
                      "la catena `fraseErrore(motivo)||fraseErrore(errore)` si ferma al "
                      "primo anello e l'ospite legge sempre il messaggio generico")
        # e la catena dev'essere ancora una catena: se sparisse, questa guardia sorveglierebbe
        # una precauzione che non serve piu' a nessuno, cioe' diventerebbe un ornamento.
        self.assertIn("fraseErrore(r.motivo)||fraseErrore(r.errore)", _leggi('index.html'),
                      'il checkout non incatena piu\' i due tentativi: se e\' voluto, questa '
                      'guardia va riscritta insieme al cambiamento')


if __name__ == '__main__':
    unittest.main()
