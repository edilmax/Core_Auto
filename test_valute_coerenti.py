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
                    "%s: browser %d decimali, motore %d -> il prezzo LETTO e quello "
                    "ADDEBITATO differiscono di %d volte"
                    % (valuta, e_browser, e_motore, 10 ** abs(e_browser - e_motore)))
        self.assertEqual(
            disaccordi, [],
            # ⛔ Qui c'era scritto «il numero mandato a Stripe lo calcola il BROWSER».
            # E' FALSO, e ha fermato una riparazione il 2026-08-28 facendola sembrare
            # incompleta. Il prezzo lo calcola e lo FIRMA il server, e al pagamento si
            # rilegge dal token firmato (`fase59_concierge.py:513`,
            # `dati = self._firma.decodifica(token)` -> 400 se la firma e' rotta): dal
            # browser non passa nessun importo. Una guardia che si giustifica con
            # un'affermazione falsa e' peggio di una guardia assente, perche' manda a
            # cercare il difetto dove non e'.
            "Browser e motore non concordano: l'ospite LEGGE un prezzo e ne PAGA un "
            "altro. L'addebito resta quello firmato dal server -- il danno e' il prezzo "
            "mostrato, ed e' quello su cui il cliente decide.\n  - "
            + "\n  - ".join(disaccordi))

    def test_le_valute_senza_decimali_sono_marcate_nel_browser(self):
        """Le trappole del x100: se il browser le credesse normali, MOSTREREBBE un prezzo
        cento volte diverso da quello che l'ospite si vede addebitare.
        ⛔ ISK non e' in questo elenco, e non e' una dimenticanza: Stripe la vuole
        rappresentata a DUE decimali per retrocompatibilita' («to charge 5 ISK, provide an
        amount value of 500», docs.stripe.com/currencies, 2026-08-28). La sua guardia sta
        in `test_profondo_valute.test_ISK_e_UGX_si_addebitano_come_valute_a_DUE_decimali`.
        ⚠️ Questo elenco e' una delle TRE copie della stessa conoscenza (le altre due:
        `test_importi_scritti.SENZA_DECIMALI` e `test_plausibilita`). Non si fanno derivare
        da `fase99.esponente()`: l'atteso preso dal codice sotto esame non prova niente."""
        for valuta in ("JPY", "KRW", "VND", "CLP"):
            if valuta in self.browser:
                self.assertEqual(
                    self.browser[valuta], 0,
                    "%s NON ha decimali: il browser che crede il contrario MOSTRA cento "
                    "volte l'importo vero" % valuta)

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


#  L'ELENCO DI STRIPE, letto il 2026-11-04 da docs.stripe.com/currencies («Supported presentment
#  currencies», 134 sigle; nella pagina le valute senza decimali portano il link «zero-decimal»).
#  E' una copia DATATA, apposta: e' il giudice esterno, non il codice sotto esame. Se Stripe ne
#  aggiunge una, il menu non la offre finche' qualcuno non la legge e la aggiunge qui.
STRIPE_VALUTE_20261104 = tuple((
    "AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BIF "
    "BMD BND BOB BRL BSD BWP BYN BZD CAD CDF CHF CLP CNY COP "
    "CRC CVE CZK DJF DKK DOP DZD EGP ETB EUR FJD FKP GBP GEL "
    "GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR ISK JMD "
    "JPY KES KGS KHR KMF KRW KYD KZT LAK LBP LKR LRD LSL MAD "
    "MDL MGA MKD MMK MNT MOP MUR MVR MWK MXN MYR MZN NAD NGN "
    "NIO NOK NPR NZD PAB PEN PGK PHP PKR PLN PYG QAR RON RSD "
    "RUB RWF SAR SBD SCR SEK SGD SHP SLE SOS SRD STD SZL THB "
    "TJS TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VND VUV WST "
    "XAF XCD XCG XOF XPF YER ZAR ZMW ").split())
STRIPE_SENZA_DECIMALI_20261104 = frozenset(
    "BIF CLP DJF GNF JPY KMF KRW MGA PYG RWF UGX VND VUV XAF XOF XPF".split())
#  UGX e ISK: «backward compatibility requires you to represent it as a two-decimal value» (stessa
#  pagina, «Special cases»): si mandano a Stripe a DUE decimali anche se non ne hanno.
STRIPE_A_DUE_PER_RETROCOMPATIBILITA = frozenset(("UGX", "ISK"))


class TestOgniMonetaDiStripeSiPuoScegliereCoiDecimaliDiStripe(unittest.TestCase):
    """⛔ 4/11, il fondatore: «deve valere per tutte le nazioni del mondo». Il server accetta
    qualunque sigla, ma il menu dell'host ne offriva 24 (il peso filippino no). Ora la tabella
    del browser ha ogni moneta con cui Stripe accetta pagamenti, e qui la si giudica con
    l'elenco di STRIPE, non col motore: due fonti diverse, e il motore ha gia' la sua guardia
    sopra (`TestBrowserEMotoreConcordano`)."""

    def setUp(self):
        self.browser = tabella_browser()

    def _attesi(self, valuta):
        if valuta in STRIPE_A_DUE_PER_RETROCOMPATIBILITA:
            return 2
        return 0 if valuta in STRIPE_SENZA_DECIMALI_20261104 else 2

    def test_l_elenco_di_stripe_e_stato_letto(self):
        self.assertEqual(len(STRIPE_VALUTE_20261104), 134, "misura non valida: elenco di Stripe")
        self.assertEqual(len(set(STRIPE_VALUTE_20261104)), 134, "sigle doppie nell'elenco")

    def test_il_menu_offre_ogni_moneta_di_stripe(self):
        mancanti = sorted(set(STRIPE_VALUTE_20261104) - set(self.browser) - IN_ATTESA_DEL_SERVER)
        self.assertEqual(mancanti, [],
                         "MONETE DI STRIPE CHE L'HOST NON PUO' SCEGLIERE (%d): %s"
                         % (len(mancanti), " ".join(mancanti)))
        self.assertIn("PHP", self.browser, "il peso filippino non si puo' scegliere")

    def test_ogni_moneta_offerta_e_di_stripe_e_ha_i_decimali_che_vuole_stripe(self):
        fuori = sorted(set(self.browser) - set(STRIPE_VALUTE_20261104))
        self.assertEqual(fuori, [], "monete offerte che Stripe non incassa: %s" % fuori)
        sbagliate = ["%s: pagina %d, Stripe %d" % (v, e, self._attesi(v))
                     for v, e in sorted(self.browser.items()) if e != self._attesi(v)]
        self.assertEqual(sbagliate, [],
                         "DECIMALI DIVERSI DA STRIPE: l'ospite leggerebbe un prezzo cento volte "
                         "diverso da quello addebitato -> %s" % sbagliate)

    def test_il_menu_dell_host_si_legge_dalla_tabella_e_non_da_una_lista_sua(self):
        """Una seconda lista nel pannello resterebbe indietro il giorno che la tabella cresce
        (fino al 4/11 il menu ne offriva 24 su 27 della tabella)."""
        t = _leggi(HOST_HTML)
        self.assertRegex(t, r"const VAL_ORDINE\s*=\s*VAL_PRIME\.concat\(Object\.keys\(BV\.VALUTE\)",
                         "il menu delle monete dell'host non si legge piu' dalla tabella di app.js")
        prime = re.search(r"const VAL_PRIME\s*=\s*\[([^\]]*)\]", t)
        self.assertIsNotNone(prime, "misura non valida: VAL_PRIME non trovato")
        sigle = re.findall(r"'([A-Z]{3})'", prime.group(1))
        self.assertEqual([s for s in sigle if s not in self.browser], [],
                         "il menu mette in cima monete che la tabella non conosce")

    def test_una_moneta_su_cui_server_e_stripe_non_concordano_non_si_offre(self):
        """MGA (ariary malgascio): Stripe la tratta senza decimali, `fase99.esponente` ne conta
        2. Offrirla farebbe addebitare cento volte il prezzo. Resta fuori dal menu finche' il
        server non la conta come Stripe (voce di RIPRENDI); il giorno che lo fa, questa prova
        lo dice e la moneta puo' entrare."""
        for v in IN_ATTESA_DEL_SERVER:
            if esponente(v) != self._attesi(v):
                self.assertNotIn(v, self.browser,
                                 "%s e' nel menu ma il server ne conta %d decimali e Stripe %d"
                                 % (v, esponente(v), self._attesi(v)))
        self.assertTrue(all(esponente(v) == self._attesi(v)
                            for v in set(STRIPE_VALUTE_20261104) - IN_ATTESA_DEL_SERVER),
                        "una moneta di Stripe ha nel server decimali diversi da Stripe: %s"
                        % [v for v in STRIPE_VALUTE_20261104
                           if v not in IN_ATTESA_DEL_SERVER and esponente(v) != self._attesi(v)])


#  Le monete di Stripe su cui il server sbaglia i decimali: fuori dal menu finche' non si ripara.
#  Vuoto dal 4/11: MGA (l'unica) l'ha riparata la voce 251. Se un giorno Stripe ne aggiunge una che
#  il motore conta diversa, si mette qui e il menu non la offre finche' il motore non la impara.
IN_ATTESA_DEL_SERVER = frozenset()


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
