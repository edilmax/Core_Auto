"""GUARDIA — il testo italiano congelato puo' solo DIMINUIRE, mai aumentare.

COSA SORVEGLIA.
`collaudi/occhio_del_fondatore.py` conta, pagina per pagina, quante parole visibili
restano in italiano qualunque lingua scelga l'utente (tutto cio' che sta fuori dagli
elementi marcati `data-t` / `data-i18n` non viene mai sostituito).

Oggi sono **1034**. Erano **1808**: termini e privacy sono diventati gusci serviti
dal motore in 8 lingue, e le due pagine di esito pagamento (`grazie`, `annullato`) hanno
smesso di conoscere solo italiano e inglese. E' un debito vero, aperto, che si paga pagina per pagina.

PERCHE' UN TETTO E NON UN «TUTTO A ZERO».
Pretendere zero subito renderebbe la suite rossa per un lavoro non ancora fatto, e una
suite stabilmente rossa smette di essere letta: e' il modo piu' rapido per perdere una
guardia. Il tetto invece rende il debito **visibile e monodirezionale**: si puo' solo
scendere. Chi aggiunge una frase italiana non marcata trova subito rosso, e nessuna
pagina nuova puo' entrare in silenzio.

I NUMERI SONO SCRITTI A MANO, DI PROPOSITO.
Non esiste un comando che li rigeneri. Una baseline che si riscrive da sola approva se
stessa — errore gia' commesso e gia' corretto altrove in questo progetto. Per abbassare
un numero bisogna aver tradotto davvero, e cambiarlo a mano qui e' l'atto con cui lo si
dichiara.

Ordine di lavoro deciso dal fondatore: prima cio' che leggono ospiti e host
(`termini`, `privacy`, `grazie`, `annullato`), poi il resto.
"""

import os
import sys
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(QUI, "collaudi"))
import occhio_del_fondatore as occhio                          # noqa: E402

# pagina -> parole italiane che oggi restano ferme. SI ABBASSA SOLO A MANO, dopo aver
# tradotto. Se un numero e' piu' alto del reale, il test lo dice: va allineato in basso.
TETTO = {
    "admin.html": 27,
    "annullato.html": 1,
    "bunker.html": 306,
    "commissioni.html": 2,
    "contratto-host.html": 1,
    "diventa-host.html": 1,
    "grazie.html": 1,
    "guida-operativa.html": 280,
    "host.html": 3,
    "index.html": 24,
    "kit-marketing.html": 386,
    "privacy.html": 1,
    "termini.html": 1,
}

TOTALE_OGGI = 1034


class TestNessunPassoIndietro(unittest.TestCase):

    def setUp(self):
        self.misure = {}
        for pagina in sorted(os.listdir(occhio.PAGINE)):
            if pagina.endswith(".html"):
                self.misure[pagina] = occhio.esamina(
                    os.path.join(occhio.PAGINE, pagina))["congelate"]

    def test_nessuna_pagina_peggiora(self):
        peggiorate = []
        for pagina, ferme in sorted(self.misure.items()):
            tetto = TETTO.get(pagina)
            if tetto is None:
                continue
            if ferme > tetto:
                peggiorate.append("%s: %d parole ferme, il tetto era %d (+%d)"
                                  % (pagina, ferme, tetto, ferme - tetto))
        self.assertEqual(
            peggiorate, [],
            "E' stato aggiunto testo italiano che NON verra' mai tradotto.\n"
            "Marcalo con data-t / data-i18n e aggiungi la voce al dizionario.\n  - "
            + "\n  - ".join(peggiorate))

    def test_ogni_pagina_e_dichiarata(self):
        """Una pagina nuova non puo' entrare senza che qualcuno guardi le sue lingue."""
        ignote = [p for p, ferme in self.misure.items()
                  if p not in TETTO and ferme > 0]
        self.assertEqual(ignote, [],
                         "pagine nuove con testo italiano non tradotto, mai dichiarate: "
                         "%s — aggiungile a TETTO dopo averle guardate" % ignote)

    def test_il_tetto_non_e_gonfiato(self):
        """Un tetto piu' alto del reale e' spazio libero per peggiorare senza accorgersene:
        appena una pagina migliora, il suo numero va abbassato."""
        larghi = ["%s: tetto %d, reale %d" % (p, TETTO[p], self.misure[p])
                  for p in sorted(TETTO)
                  if p in self.misure and self.misure[p] < TETTO[p]]
        self.assertEqual(larghi, [],
                         "il tetto e' piu' alto del reale: abbassalo, il lavoro e' fatto"
                         ".\n  - " + "\n  - ".join(larghi))

    def test_il_totale_dichiarato_corrisponde(self):
        vero = sum(self.misure.get(p, 0) for p in TETTO)
        self.assertEqual(vero, TOTALE_OGGI,
                         "il debito totale e' %d, non %d: aggiorna TOTALE_OGGI"
                         % (vero, TOTALE_OGGI))


class TestLoStrumentoVedeDavvero(unittest.TestCase):
    """La regola madre: una guardia che non e' mai fallita non e' una guardia."""

    def _misura(self, html):
        import tempfile
        d = tempfile.mkdtemp()
        p = os.path.join(d, "prova.html")
        with open(p, "w", encoding="utf-8") as f:
            f.write(html)
        return occhio.esamina(p)

    def test_riconosce_una_pagina_tutta_congelata(self):
        r = self._misura(
            "<html><body><h1>Grazie per la prenotazione</h1>"
            "<p>La tua stanza e' confermata e riceverai una email fra poco.</p>"
            "</body></html>")
        self.assertEqual(r["tradotte"], 0)
        self.assertGreater(r["congelate"], 8, "non vede il testo italiano fermo")
        self.assertEqual(r["copertura"], 0.0)

    def test_riconosce_una_pagina_tradotta(self):
        r = self._misura(
            "<html><body><h1 data-t='grazie'>Grazie per la prenotazione</h1>"
            "<p data-i18n='conf'>La tua stanza e' confermata e riceverai una email.</p>"
            "</body></html>")
        self.assertEqual(r["congelate"], 0, "conta come ferme parole gia' marcate")
        self.assertEqual(r["copertura"], 100.0)

    def test_il_testo_dentro_un_marcatore_copre_anche_i_figli(self):
        r = self._misura("<div data-t='x'>ecco il <b>testo annidato</b> completo</div>")
        self.assertEqual(r["congelate"], 0)

    def test_non_conta_gli_script_ne_i_nomi_propri(self):
        r = self._misura(
            "<html><body><script>var messaggio='questo non si vede mai';</script>"
            "<style>.x{color:red}</style>"
            "<option>New York</option><option>Buenos Aires</option>"
            "<span>bookinvip.com</span></body></html>")
        self.assertEqual(r["congelate"], 0,
                         "conta come da tradurre script, stili o nomi di citta'")

    def test_una_frase_vera_non_viene_scambiata_per_nome_proprio(self):
        r = self._misura("<p>pubblica il tuo alloggio ora</p>")
        self.assertGreater(r["congelate"], 2,
                           "una frase minuscola vera scambiata per nome proprio")


class TestPagineEsitoPagamento(unittest.TestCase):
    """`grazie.html` e `annullato.html`: le legge OGNI ospite che paga.

    Prima parlavano italiano, con una sola eccezione per l'inglese decisa dalla lingua
    del BROWSER — e ignoravano la lingua che l'utente aveva gia' scelto sul sito. Chi
    aveva navigato in giapponese e aveva appena pagato leggeva italiano nel momento in
    cui conta di piu': la conferma che i soldi sono partiti.
    """

    LINGUE = ("it", "en", "es", "fr", "de", "pt", "ja", "zh")

    def _pagina(self, nome):
        p = os.path.join(occhio.PAGINE, nome)
        self.assertTrue(os.path.exists(p), "pagina sparita: %s" % nome)
        with open(p, encoding="utf-8") as f:
            return f.read()

    def test_tutte_e_otto_le_lingue(self):
        import re
        for nome in ("grazie.html", "annullato.html"):
            testo = self._pagina(nome)
            for lang in self.LINGUE:
                self.assertRegex(testo, r"%s\s*:\s*\{\s*h:" % lang,
                                 "%s non parla '%s'" % (nome, lang))

    def test_rispettano_la_lingua_gia_scelta_sul_sito(self):
        """Non basta guardare il browser: l'utente puo' aver scelto un'altra lingua."""
        for nome in ("grazie.html", "annullato.html"):
            testo = self._pagina(nome)
            self.assertIn("localStorage.getItem('lang')", testo,
                          "%s ignora la lingua scelta dall'utente" % nome)

    def test_una_lingua_sconosciuta_non_ricade_sull_italiano(self):
        for nome in ("grazie.html", "annullato.html"):
            testo = self._pagina(nome)
            self.assertIn("return T[n] ? n : 'en';", testo,
                          "%s farebbe ripiego su una lingua non universale" % nome)

    def test_nessun_testo_visibile_resta_dentro_l_html(self):
        for nome in ("grazie.html", "annullato.html"):
            testo = self._pagina(nome)
            for spia in ('<h1 id="h">G', '<h1 id="h">P', 'id="p1">La ', 'id="p1"><strong>'):
                self.assertNotIn(spia, testo,
                                 "%s ha di nuovo testo fisso nell'HTML" % nome)


if __name__ == "__main__":
    unittest.main(verbosity=2)
