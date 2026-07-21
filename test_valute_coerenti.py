"""GUARDIA — browser e motore devono dire la STESSA cosa su ogni valuta.

PERCHE' ESISTE, e perche' e' una guardia sui soldi e non sull'estetica.

Il numero che finisce su Stripe lo calcola **il browser**:

    BV.toCents(valore_digitato, valuta) = round(valore x 10^esponente)

Il server poi lo prende per buono, lo salva e lo manda a Stripe come `unit_amount`.
Quindi **l'esponente che conosce il browser E' l'addebito**. Se `deploy/app.js` e
`fase99_multicurrency` non concordano su una sola valuta, succede questo:

  · l'host giapponese digita 18000 (yen a notte);
  · il browser, se credesse che lo yen ha 2 decimali, manderebbe 1.800.000;
  · il server lo salva, Stripe addebita **¥1.800.000** invece di ¥18.000.

E' esattamente il numero che il fondatore ha visto sulla vetrina il 2026-07-21 — quella
volta era un dato dimostrativo, ma la stessa cifra puo' nascere da un disaccordo fra le
due tabelle, e nessun test lo guardava.

LA REGOLA GENERALE, che vale oltre le valute:
**due copie della stessa verita' divergono sempre, e la copia sbagliata non fa rumore.**
E' successo davvero: `collaudi/plausibilita.py` teneva una terza tabella e dichiarava
HUF, TWD e COP senza decimali quando ne hanno due. Uno strumento nato per trovare gli
errori di scala li avrebbe insieme inventati (prezzo ungherese corretto denunciato) e
nascosti (banda cento volte piu' larga). Ora quel file legge dal motore; qui si sorveglia
che nemmeno il browser possa scostarsene.
"""

import io
import os
import re
import unittest

from fase99_multicurrency import esponente

QUI = os.path.dirname(os.path.abspath(__file__))
APP_JS = os.path.join(QUI, "deploy", "app.js")
HOST_HTML = os.path.join(QUI, "deploy", "host.html")


def _leggi(p):
    with io.open(p, encoding="utf-8") as f:
        return f.read()


def tabella_browser():
    """{valuta: esponente} come la conosce il browser (BV.VALUTE in app.js)."""
    js = _leggi(APP_JS)
    return dict((m.group(1), int(m.group(2)))
                for m in re.finditer(r"\b([A-Z]{3}):\{s:'[^']*',e:(\d)", js))


class TestBrowserEMotoreConcordano(unittest.TestCase):

    def setUp(self):
        self.browser = tabella_browser()

    def test_la_tabella_del_browser_e_stata_letta(self):
        """Se il formato di app.js cambiasse, questa guardia diventerebbe muta senza
        dirlo: meglio accorgersene qui che scoprirlo su un addebito."""
        self.assertGreaterEqual(len(self.browser), 20,
                                "non riesco piu' a leggere BV.VALUTE da app.js: la "
                                "guardia starebbe controllando il vuoto")
        self.assertIn("EUR", self.browser)
        self.assertIn("JPY", self.browser)

    def test_ogni_valuta_del_browser_ha_l_esponente_del_motore(self):
        disaccordi = []
        for valuta, e_browser in sorted(self.browser.items()):
            e_motore = esponente(valuta)
            if e_browser != e_motore:
                disaccordi.append(
                    "%s: browser %d decimali, motore %d -> l'addebito sarebbe "
                    "sbagliato di %d volte"
                    % (valuta, e_browser, e_motore, 10 ** abs(e_browser - e_motore)))
        self.assertEqual(
            disaccordi, [],
            "Browser e motore non concordano. Il numero mandato a Stripe lo calcola il "
            "BROWSER: un disaccordo qui e' un addebito sbagliato, non un dettaglio.\n  - "
            + "\n  - ".join(disaccordi))

    def test_le_valute_senza_decimali_sono_marcate_nel_browser(self):
        """Le tre trappole: se il browser le credesse normali, moltiplicherebbe x100."""
        for valuta in ("JPY", "KRW", "VND", "CLP", "ISK"):
            if valuta in self.browser:
                self.assertEqual(
                    self.browser[valuta], 0,
                    "%s NON ha decimali: il browser che crede il contrario manda a "
                    "Stripe cento volte l'importo" % valuta)

    def test_nessuna_valuta_offerta_e_sconosciuta(self):
        """Tutto cio' che l'host puo' scegliere dev'essere una sigla ISO di 3 lettere:
        il server ora le rifiuta, e un'opzione irraggiungibile sarebbe una trappola."""
        for valuta in self.browser:
            self.assertEqual(len(valuta), 3, valuta)
            self.assertTrue(valuta.isalpha() and valuta.isupper(), valuta)


class TestIlServerRifiutaLeValuteInventate(unittest.TestCase):
    """Il pannello offre un elenco chiuso, ma l'API si chiama anche da fuori."""

    def _valida(self, valuta):
        from fase57_vetrina import valida_scheda
        return valida_scheda({
            "host_id": "h", "slug": "prova-valuta", "titolo": "Prova", "citta": "Roma",
            "prezzo_notte_cents": 12000, "capacita": 2, "valuta": valuta})

    def test_accetta_le_sigle_vere(self):
        for valuta in ("EUR", "USD", "JPY", "GBP", "AED", "KWD"):
            ok, errore, scheda = self._valida(valuta)
            self.assertTrue(ok, "rifiuta la valuta valida %s (%s)" % (valuta, errore))
            self.assertEqual(scheda.valuta, valuta)

    def test_normalizza_in_maiuscolo(self):
        """'eur' ed 'EUR' come due etichette diverse spezzerebbero in due il riepilogo
        degli incassi dell'host, che e' raggruppato per valuta."""
        ok, _e, scheda = self._valida("  eur ")
        self.assertTrue(ok)
        self.assertEqual(scheda.valuta, "EUR")

    def test_rifiuta_tutto_cio_che_non_e_una_sigla_ISO(self):
        for cattiva in ("", "E", "EU", "EURO", "BITCOIN", "€", "12", "E1R", "eur oo"):
            ok, errore, _s = self._valida(cattiva)
            self.assertFalse(ok, "accetta la valuta inventata %r" % cattiva)
            self.assertEqual(errore, "valuta_non_valida", cattiva)

    def test_rifiuta_i_tipi_sbagliati(self):
        for cattiva in (None, 12, [], {}, True):
            ok, errore, _s = self._valida(cattiva)
            self.assertFalse(ok, "accetta valuta %r" % cattiva)


class TestLoStrumentoDiCollaudoNonTieneUnaCopia(unittest.TestCase):
    """La regola generale: due copie della stessa verita' divergono sempre."""

    def test_plausibilita_chiede_al_motore(self):
        import sys
        sys.path.insert(0, os.path.join(QUI, "collaudi"))
        import plausibilita as pl
        for valuta in ("JPY", "KRW", "HUF", "TWD", "COP", "KWD", "BHD", "EUR", "USD"):
            self.assertEqual(
                pl._esponente(valuta), esponente(valuta),
                "il collaudo e il motore non concordano su %s: il collaudo teneva una "
                "tabella sua e diceva il falso su HUF/TWD/COP" % valuta)

    def test_plausibilita_non_ha_piu_una_tabella_propria(self):
        testo = _leggi(os.path.join(QUI, "collaudi", "plausibilita.py"))
        self.assertNotRegex(
            testo, r"(?m)^ESPONENTE\s*=\s*\{",
            "e' tornata una tabella locale degli esponenti: divergera' di nuovo")
        self.assertIn("from fase99_multicurrency import esponente", testo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
