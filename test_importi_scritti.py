"""GUARDIA — ogni importo SCRITTO PER UNA PERSONA rispetta i decimali della sua valuta.

IL DIFETTO CHE HA FATTO NASCERE QUESTA GUARDIA (2026-07-21).
Il fondatore ha chiesto di verificare che «dal primo prezzo visto sulla pagina fino
all'addebito finale e all'email di ricevuta la valuta sia coerente e priva di errori di
scala». Cercando, sono saltati fuori **tre** posti che dividevano per cento **a mano**,
sempre, qualunque valuta:

    fase86_email._soldi          "%d.%02d %s" % (c // 100, c % 100, valuta)
    fase145_contratto_pdf._euro  "%d.%02d"    % (c // 100, c % 100)
    fase119_calendario_prezzi    "€%d.%02d"   % (pd // 100, pd % 100)   <- pure il SIMBOLO

Conseguenza provata: un ospite giapponese che paga **¥54.000** riceveva l'email di
conferma con scritto **540.00 JPY**, e il **PDF del contratto** — il documento che le
parti firmano — riportava lo stesso importo sbagliato di cento volte.

PERCHE' ERA IL CASO PEGGIORE.
Il sito e Stripe erano **corretti**: la strada dei soldi usa da sempre l'esponente della
valuta. Quindi l'addebito era giusto e **il racconto dell'addebito era falso**. Niente si
rompe, niente finisce nei log, nessun test cade: si scopre quando un cliente protesta,
oppure mai.

LA CAUSA, ancora una volta, e' la DUPLICAZIONE. `fase99.Denaro.formatta()` esisteva gia'
ed era gia' giusto per tutte le valute. Nessuno lo chiamava.

COSA PRETENDE QUESTA GUARDIA
  1. ogni funzione che scrive importi da' lo stesso risultato del motore, su ogni valuta;
  2. sulle valute senza decimali non compare **mai** un separatore decimale;
  3. sulle valute a 2 e 3 decimali i decimali ci sono **tutti** (aggiustare lo yen
     rompendo l'euro sarebbe solo spostare il difetto);
  4. **nessun modulo torna a dividere per cento a mano** per scrivere denaro — e' il
     controllo che impedisce alla classe intera di ripresentarsi.
"""

import io
import os
import re
import unittest

from fase99_multicurrency import Denaro, esponente

QUI = os.path.dirname(os.path.abspath(__file__))

# (valuta, unita' minori, come DEVE essere scritto)
CASI = [
    ("EUR", 15000, "150.00 EUR"),
    ("EUR", 5, "0.05 EUR"),
    ("USD", 123456, "1234.56 USD"),
    ("JPY", 54000, "54000 JPY"),
    ("JPY", 1800000, "1800000 JPY"),
    ("KRW", 150000, "150000 KRW"),
    ("VND", 2500000, "2500000 VND"),
    ("KWD", 25500, "25.500 KWD"),
    ("BHD", 1234, "1.234 BHD"),
]

SENZA_DECIMALI = ("JPY", "KRW", "VND", "CLP", "ISK")
CON_TRE = ("KWD", "BHD", "OMR", "TND", "JOD")


def _leggi(nome):
    with io.open(os.path.join(QUI, nome), encoding="utf-8") as f:
        return f.read()


class TestChiScriveGliImportiDiceIlVERO(unittest.TestCase):
    """Le tre funzioni che erano sbagliate, piu' quella del server che era giusta."""

    def _scrittori(self):
        from fase86_email import _soldi
        from fase119_calendario_prezzi import _importo as importo_calendario
        from fase145_contratto_pdf import _importo as importo_contratto
        return {
            "email (fase86)": _soldi,
            "contratto PDF (fase145)": importo_contratto,
            "calendario host (fase119)": importo_calendario,
            "motore (fase99)": lambda c, v: Denaro(c, v).formatta(),
        }

    def test_tutti_scrivono_come_il_motore(self):
        sbagli = []
        for nome, f in self._scrittori().items():
            for valuta, minori, atteso in CASI:
                ottenuto = f(minori, valuta)
                if ottenuto != atteso:
                    sbagli.append("%s: %d %s -> %r invece di %r"
                                  % (nome, minori, valuta, ottenuto, atteso))
        self.assertEqual(
            sbagli, [],
            "Qualcuno racconta l'importo in modo diverso da come viene addebitato.\n  - "
            + "\n  - ".join(sbagli))

    def test_le_valute_senza_decimali_non_hanno_MAI_la_virgola(self):
        for nome, f in self._scrittori().items():
            for valuta in SENZA_DECIMALI:
                scritto = f(54000, valuta)
                self.assertNotIn(".", scritto, "%s: %s scritto %r" % (nome, valuta, scritto))
                self.assertNotIn(",", scritto, "%s: %s scritto %r" % (nome, valuta, scritto))
                self.assertIn("54000", scritto,
                              "%s: %s perde l'importo (%r)" % (nome, valuta, scritto))

    def test_l_euro_conserva_i_due_decimali(self):
        """Non si aggiusta lo yen rompendo l'euro."""
        for nome, f in self._scrittori().items():
            self.assertRegex(f(15000, "EUR"), r"150[.,]00",
                             "%s ha perso i centesimi dell'euro" % nome)

    def test_le_valute_a_tre_decimali(self):
        for nome, f in self._scrittori().items():
            for valuta in CON_TRE:
                self.assertRegex(f(25500, valuta), r"25[.,]500",
                                 "%s: %s vuole TRE decimali" % (nome, valuta))

    def test_il_server_formatta_come_tutti_gli_altri(self):
        """`_fmt_importo` del server era gia' corretto: qui si pretende che RESTI
        allineato agli altri, cosi' pagina ed email non possono divergere."""
        from fase83_server import RouterHTTP
        for valuta, minori, atteso in CASI:
            self.assertEqual(RouterHTTP._fmt_importo(None, minori, valuta), atteso,
                             "il server scrive %d %s diversamente dagli altri"
                             % (minori, valuta))

    def test_il_motore_RIFIUTA_una_valuta_non_valida(self):
        """Non e' un difetto, e' la difesa: formattare una sigla inventata vorrebbe dire
        indovinarne l'esponente, cioe' scrivere un importo falso con l'aria di uno vero.
        Il motore preferisce fermarsi."""
        for valuta in (None, "", "EURO", 123):
            with self.assertRaises(Exception,
                                   msg="il motore accetta la valuta %r" % valuta):
                Denaro(1000, valuta).formatta()

    def test_chi_scrive_a_una_PERSONA_non_si_rompe_mai(self):
        """Le pagine e le email invece devono reggere: un'eccezione mentre si compone
        una ricevuta farebbe saltare la ricevuta. Ripiegano su un numero grezzo con la
        sigla — brutto ma vero — invece che su un numero plausibile e falso."""
        for nome, f in self._scrittori().items():
            if nome.startswith("motore"):
                continue
            for valuta in (None, "", "ZZZ", "eur", 123):
                try:
                    scritto = f(1000, valuta)
                except Exception as e:
                    self.fail("%s solleva su valuta %r: %s" % (nome, valuta, e))
                # l'importo deve comunque comparire: un ripiego che perde il numero
                # sarebbe peggio dell'eccezione che stiamo evitando
                self.assertIn("1000", str(scritto).replace(".", "").replace(",", ""),
                              "%s perde l'importo su valuta %r: %r"
                              % (nome, valuta, scritto))


class TestNessunoTornaADividerePerCentoAMano(unittest.TestCase):
    """Il controllo che impedisce alla CLASSE di difetto di ripresentarsi.

    Scrivere `%d.%02d % (c // 100, c % 100)` e' il gesto che ha prodotto tutti e tre i
    difetti. E' sempre sbagliato per il denaro, perche' presume due decimali; e' invece
    legittimo per percentuali e millesimi (bps), che con la valuta non c'entrano.
    """

    # `// 10000` sono i punti base (commissioni): niente a che vedere col formato dei soldi
    SOSPETTO = re.compile(r"%d\.%02d[^\n]*//\s*100\b")

    ESENTI = {
        # scrive numeri per la contabilita' interna, non per un essere umano
        "fase103_reverse_charge.py",
        # tabella "quanto risparmi rispetto agli OTA" della pagina di marketing: usa un
        # prezzo DIMOSTRATIVO fisso (`prezzo_demo_cents=10000`, cioe' 100,00 in una sola
        # valuta) uguale per tutti. Non e' l'importo di nessun annuncio e di nessuna
        # prenotazione: e' un esempio, e un esempio ha la valuta che gli si da'.
        "fase97_inbound_seo.py",
    }

    # Non e' denaro: un VOTO da 1 a 5 (4.25 stelle) ha sempre due decimali per
    # definizione, e non ha una valuta. L'esenzione e' sulla RIGA, non sul file:
    # esentare un intero file nasconderebbe anche gli importi veri che contiene.
    NON_E_DENARO = re.compile(r"rating|voto|stelle|media", re.I)

    def test_nessun_modulo_scrive_denaro_dividendo_per_cento(self):
        colpevoli = []
        for nome in sorted(os.listdir(QUI)):
            if not (nome.startswith("fase") and nome.endswith(".py")):
                continue
            if nome in self.ESENTI:
                continue
            testo = _leggi(nome)
            for n, riga in enumerate(testo.splitlines(), 1):
                if self.SOSPETTO.search(riga) and not self.NON_E_DENARO.search(riga):
                    colpevoli.append("%s:%d  %s" % (nome, n, riga.strip()[:80]))
        self.assertEqual(
            colpevoli, [],
            "Qualcuno e' tornato a scrivere il denaro dividendo per cento a mano: "
            "presume due decimali e sbaglia di cento volte su yen e won.\n"
            "Usa fase99.Denaro(minori, valuta).formatta().\n  - " + "\n  - ".join(colpevoli))

    def test_il_controllo_saprebbe_riconoscere_il_gesto(self):
        """Se il criterio non riconoscesse piu' il difetto originale, questa guardia
        diventerebbe un ornamento senza che nessuno se ne accorga."""
        originale = '    return "%d.%02d %s" % (c // 100, c % 100, valuta or "EUR")'
        self.assertRegex(originale, self.SOSPETTO,
                         "il criterio non riconosce piu' il codice che ha causato il "
                         "difetto: va corretto, non allargato")


class TestIlSimboloDellEuroNonEFisso(unittest.TestCase):
    """Un annuncio in yen a cui si stampa davanti "€" mente due volte."""

    def test_il_calendario_prezzi_non_ha_l_euro_scritto_dentro(self):
        testo = _leggi("fase119_calendario_prezzi.py")
        righe = [r.strip() for r in testo.splitlines()
                 if "€" in r and not r.strip().startswith("#")]
        self.assertEqual(righe, [],
                         "simbolo dell'euro fisso nel calendario prezzi: %s" % righe)


if __name__ == "__main__":
    unittest.main(verbosity=2)
