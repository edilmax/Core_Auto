"""GUARDIA — la plausibilità del dato: «questo numero ha senso nel mondo vero?»

PERCHE' ESISTE, detto senza attenuanti.

Il 2026-07-21 il fondatore ha guardato la vetrina e ha visto `Zen House Shibuya` a
**¥1.800.000 a notte** — circa 11.000 euro. Lo yen non ha decimali: il prezzo era stato
salvato ×100 come si fa con l'euro.

**Nessuno dei collaudi l'aveva visto.** Suite verde con 3011 test, dieci strumenti di
verifica, test di mutazione, piramide a sei livelli — e un errore da diecimila per cento
in bella mostra sulla pagina principale.

Il motivo e' strutturale e va ricordato:
  · tutti gli altri collaudi provano il **codice**, con dati **inventati da loro**;
  · quel difetto stava nei **dati veri**, dove nessuno guardava;
  · e nessuna verifica faceva la domanda piu' semplice: **«ha senso?»**

`1800000` e' un intero valido, in una colonna tipizzata, con una valuta esistente: nessun
controllo di FORMATO poteva accorgersene. Era un errore di **significato**.

Qui si presidia la logica del riconoscimento. Lo strumento che guarda i dati VERI e'
`collaudi/plausibilita.py` (si lancia con `--dati=<cartella>`, anche sul backup di
produzione): questo test garantisce che quella logica sappia davvero riconoscere
l'assurdo, compreso il caso esatto che ci e' sfuggito.
"""

import os
import sqlite3
import tempfile
import unittest

import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "collaudi"))
import plausibilita as pl                                    # noqa: E402


class TestConversioneValute(unittest.TestCase):
    """Il cuore: quante cifre decimali ha davvero ogni valuta."""

    def test_le_valute_senza_decimali_sono_riconosciute(self):
        for valuta in ("JPY", "KRW", "VND", "CLP", "ISK"):
            self.assertEqual(pl._esponente(valuta), 0,
                             "%s ha decimali secondo noi: e' la trappola del x100"
                             % valuta)

    def test_le_valute_con_tre_decimali(self):
        for valuta in ("KWD", "BHD", "OMR", "JOD", "TND"):
            self.assertEqual(pl._esponente(valuta), 3, valuta)

    def test_le_valute_normali_ne_hanno_due(self):
        for valuta in ("EUR", "USD", "GBP", "AED", "CHF"):
            self.assertEqual(pl._esponente(valuta), 2, valuta)

    def test_una_valuta_sconosciuta_non_fa_esplodere(self):
        for valuta in (None, "", "ZZZ", 123, "eur"):
            try:
                pl._esponente(valuta)
                pl.in_euro(10000, valuta)
            except Exception as e:
                self.fail("valuta %r fa sollevare %s" % (valuta, type(e).__name__))

    def test_la_conversione_tiene_conto_dei_decimali_veri(self):
        """18000 unita' minori di yen sono 18.000 yen (non 180), circa 110 euro."""
        self.assertAlmostEqual(pl.in_euro(18000, "JPY"), 18000 * 0.0062, places=2)
        self.assertAlmostEqual(pl.in_euro(15000, "EUR"), 150.0, places=2)
        self.assertAlmostEqual(pl.in_euro(90000, "AED"), 900 * 0.25, places=2)


class TestRiconosceLAssurdo(unittest.TestCase):
    """Il caso reale, piu' i suoi parenti."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.percorso = os.path.join(self.d, "catalogo.db")
        con = sqlite3.connect(self.percorso)
        con.execute("""CREATE TABLE alloggi (slug TEXT, titolo TEXT, citta TEXT,
            prezzo_notte_cents INTEGER, valuta TEXT, capacita INTEGER, stato TEXT)""")
        self.con = con
        pl.VIOL.clear()
        pl.CONTA["controlli"] = 0
        pl.CONTA["righe"] = 0

    def _metti(self, righe):
        self.con.executemany(
            "INSERT INTO alloggi VALUES (?,?,?,?,?,?,?)", righe)
        self.con.commit()

    def _controlla(self):
        pl.VIOL.clear()
        pl.prezzi_alloggi(self.d)
        return list(pl.VIOL)

    def _sani(self):
        return [("attico-roma", "Attico", "Roma", 24500, "EUR", 4, "pubblicato"),
                ("flat-london", "Flat", "London", 13000, "GBP", 2, "pubblicato"),
                ("villa-dubai", "Villa", "Dubai", 90000, "AED", 6, "pubblicato"),
                ("zen-tokyo", "Zen", "Tokyo", 18000, "JPY", 2, "pubblicato")]

    def test_i_prezzi_giusti_passano(self):
        self._metti(self._sani())
        self.assertEqual(self._controlla(), [],
                         "segnala come assurdi dei prezzi normali")

    def test_IL_CASO_VERO_lo_yen_moltiplicato_per_cento(self):
        """Il difetto che il fondatore ha trovato guardando il sito, mentre 3011 test
        erano verdi. Se un giorno questo test tornasse verde col valore sbagliato,
        vorrebbe dire che abbiamo perso di nuovo l'unica difesa che ce l'ha fatta
        vedere."""
        righe = self._sani()
        righe[3] = ("zen-tokyo", "Zen", "Tokyo", 1800000, "JPY", 2, "pubblicato")
        self._metti(righe)
        viol = self._controlla()
        self.assertTrue(viol, "¥1.800.000 a notte NON viene riconosciuto come assurdo")
        testo = " ".join(d for _a, _c, d in viol)
        self.assertIn("11160", testo.replace(".", ""),
                      "non traduce l'assurdo in una cifra comprensibile (euro)")
        self.assertIn("100", testo, "non nomina la causa: la moltiplicazione per cento")

    def test_lo_stesso_errore_su_ogni_valuta_senza_decimali(self):
        for valuta, giusto in (("JPY", 18000), ("KRW", 150000), ("VND", 2500000)):
            righe = [("prova", "P", "C", giusto * 100, valuta, 2, "pubblicato")]
            con = sqlite3.connect(self.percorso)
            con.execute("DELETE FROM alloggi")
            con.executemany("INSERT INTO alloggi VALUES (?,?,?,?,?,?,?)", righe)
            con.commit()
            con.close()
            self.assertTrue(self._controlla(),
                            "un x100 su %s non viene riconosciuto" % valuta)

    def test_anche_il_prezzo_troppo_BASSO_e_sospetto(self):
        """L'errore inverso: dividere per cento. Un attico a 2 euro non esiste."""
        righe = self._sani()
        righe[0] = ("attico-roma", "Attico", "Roma", 245, "EUR", 4, "pubblicato")
        self._metti(righe)
        self.assertTrue(self._controlla(), "2,45 euro a notte non viene segnalato")

    def test_prezzo_a_zero_o_negativo(self):
        for cattivo in (0, -1, -24500):
            con = sqlite3.connect(self.percorso)
            con.execute("DELETE FROM alloggi")
            con.execute("INSERT INTO alloggi VALUES (?,?,?,?,?,?,?)",
                        ("p", "P", "C", cattivo, "EUR", 2, "pubblicato"))
            con.commit()
            con.close()
            self.assertTrue(self._controlla(), "prezzo %s non segnalato" % cattivo)

    def test_capacita_impossibile(self):
        for cap in (0, -3, 500):
            con = sqlite3.connect(self.percorso)
            con.execute("DELETE FROM alloggi")
            con.execute("INSERT INTO alloggi VALUES (?,?,?,?,?,?,?)",
                        ("p", "P", "C", 15000, "EUR", cap, "pubblicato"))
            con.commit()
            con.close()
            self.assertTrue(self._controlla(), "capacita %s non segnalata" % cap)

    def test_titolo_o_citta_vuoti(self):
        con = sqlite3.connect(self.percorso)
        con.execute("INSERT INTO alloggi VALUES (?,?,?,?,?,?,?)",
                    ("p", "", "", 15000, "EUR", 2, "pubblicato"))
        con.commit()
        con.close()
        pl.VIOL.clear()
        pl.testi_non_vuoti(self.d)
        self.assertGreaterEqual(len(pl.VIOL), 2, "titolo e citta' vuoti non segnalati")

    def test_un_prezzo_fuori_scala_rispetto_agli_altri(self):
        """Anche dentro la banda, cinquanta volte la mediana e' un campanello."""
        righe = [("a%d" % i, "A", "C", 15000, "EUR", 2, "pubblicato") for i in range(6)]
        righe.append(("fuori", "F", "C", 15000 * 60, "EUR", 2, "pubblicato"))
        self._metti(righe)
        pl.VIOL.clear()
        pl.coerenza_prezzi_fra_loro(self.d)
        self.assertTrue(pl.VIOL, "un prezzo 60 volte la mediana non viene notato")


class TestNonSollevaMai(unittest.TestCase):

    def test_archivio_assente_o_rotto(self):
        d = tempfile.mkdtemp()
        for funzione in (pl.prezzi_alloggi, pl.coerenza_prezzi_fra_loro,
                         pl.importi_di_denaro, pl.date_sensate, pl.testi_non_vuoti):
            try:
                pl.VIOL.clear()
                funzione(d)
            except Exception as e:
                self.fail("%s solleva %s su cartella vuota"
                          % (funzione.__name__, type(e).__name__))

    def test_tabella_senza_le_colonne_attese(self):
        d = tempfile.mkdtemp()
        con = sqlite3.connect(os.path.join(d, "catalogo.db"))
        con.execute("CREATE TABLE alloggi (altro TEXT)")
        con.commit()
        con.close()
        try:
            pl.VIOL.clear()
            pl.prezzi_alloggi(d)
        except Exception as e:
            self.fail("solleva %s su schema inatteso" % type(e).__name__)


if __name__ == "__main__":
    unittest.main(verbosity=2)
