"""
SMART PRICE ALERT (fase189) — store + matchmaking, con regola Anti-Finti-Verdi.

Copre: registrazione (validazioni), match SOLO se destinazione+valuta+budget+date-flessibili,
anti-spam (max 1 avviso/giorno), negative testing (email/budget/valuta sbagliati, over budget),
e gli invarianti del matchmaking puro. Osservabili FORTI (il match vero, il timestamp anti-spam).
"""
import sqlite3
import unittest

import fase189_price_alerts as PA


def _mem():
    con = sqlite3.connect(":memory:")
    return PA.GestorePriceAlert(lambda: PA._ConnCondivisa(con))


class TestStore(unittest.TestCase):
    def setUp(self):
        self.g = _mem()

    def test_registra_e_conta(self):
        aid = self.g.registra(ospite_email="a@b.it", destinazione="Roma", budget_cents=8000)
        self.assertTrue(aid)
        self.assertEqual(self.g.conta(), 1)

    def test_validazioni_rifiutano_dati_invalidi(self):
        for kw in ({"ospite_email": "senza-chiocciola", "destinazione": "Roma", "budget_cents": 8000},
                   {"ospite_email": "a@b.it", "destinazione": "", "budget_cents": 8000},
                   {"ospite_email": "a@b.it", "destinazione": "Roma", "budget_cents": 0},
                   {"ospite_email": "a@b.it", "destinazione": "Roma", "budget_cents": -5}):
            self.assertIsNone(self.g.registra(**kw), "doveva rifiutare: %s" % kw)
        self.assertEqual(self.g.conta(), 0)

    def test_canale_diretto_senza_telefono_ripiega_email(self):
        aid = self.g.registra(ospite_email="a@b.it", destinazione="Roma", budget_cents=8000,
                              canale="whatsapp")   # senza telefono
        row = self.g.attivi_per_destinazione("Roma")[0]
        self.assertEqual(row["canale"], "email")
        # con telefono, resta whatsapp
        self.g.registra(ospite_email="c@b.it", destinazione="Roma", budget_cents=8000,
                        canale="whatsapp", telefono="+39 333 1234567")
        canali = {r["canale"] for r in self.g.attivi_per_destinazione("Roma")}
        self.assertIn("whatsapp", canali)


class TestMatchmaking(unittest.TestCase):
    def setUp(self):
        self.g = _mem()
        self.aid = self.g.registra(ospite_email="a@b.it", destinazione="Roma", budget_cents=10000,
                                   check_in="2026-09-10", check_out="2026-09-13",
                                   flessibilita_giorni=2, valuta="EUR")

    def _off(self, **kw):
        base = {"destinazione": "Roma", "prezzo_cents": 9000, "valuta": "EUR",
                "check_in": "2026-09-10", "check_out": "2026-09-13"}
        base.update(kw)
        return base

    def test_match_quando_prezzo_sotto_budget(self):
        m = self.g.match_offerta(self._off(prezzo_cents=9000))
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["id"], self.aid)

    def test_NIENTE_match_sopra_budget(self):
        self.assertEqual(self.g.match_offerta(self._off(prezzo_cents=10001)), [])
        # esattamente al budget: match (<=)
        self.assertEqual(len(self.g.match_offerta(self._off(prezzo_cents=10000))), 1)

    def test_NIENTE_match_valuta_diversa(self):
        # budget in EUR, offerta in USD: MAI confrontare monete diverse (errore di soldi)
        self.assertEqual(self.g.match_offerta(self._off(prezzo_cents=5000, valuta="USD")), [])

    def test_NIENTE_match_altra_destinazione(self):
        self.assertEqual(self.g.match_offerta(self._off(destinazione="Milano")), [])

    def test_flessibilita_date(self):
        # +2 giorni: dentro la flessibilita' -> match
        self.assertEqual(len(self.g.match_offerta(
            self._off(check_in="2026-09-12", check_out="2026-09-15"))), 1)
        # +3 giorni: fuori -> niente
        self.assertEqual(self.g.match_offerta(
            self._off(check_in="2026-09-13", check_out="2026-09-16")), [])

    def test_alert_senza_date_matcha_su_destinazione_budget(self):
        g2 = _mem()
        g2.registra(ospite_email="x@y.it", destinazione="Roma", budget_cents=10000)  # niente date
        self.assertEqual(len(g2.match_offerta(self._off(prezzo_cents=8000))), 1)


class TestAntiSpam(unittest.TestCase):
    def test_max_un_avviso_al_giorno(self):
        con = sqlite3.connect(":memory:")
        clock = {"t": 1_000_000}
        g = PA.GestorePriceAlert(lambda: PA._ConnCondivisa(con), orologio=lambda: clock["t"])
        aid = g.registra(ospite_email="a@b.it", destinazione="Roma", budget_cents=10000)
        off = {"destinazione": "Roma", "prezzo_cents": 9000, "valuta": "EUR"}
        # 1o match: si avvisa
        self.assertEqual(len(g.match_offerta(off)), 1)
        g.segna_avvisato(aid)                       # registra l'avviso (ora)
        # subito dopo (stesso giorno): NIENTE secondo avviso
        self.assertEqual(g.match_offerta(off), [], "anti-spam rotto: 2 avvisi lo stesso giorno")
        # dopo 23h: ancora no
        clock["t"] += 23 * 3600
        self.assertEqual(g.match_offerta(off), [])
        # dopo 24h+: di nuovo avvisabile
        clock["t"] += 2 * 3600
        self.assertEqual(len(g.match_offerta(off)), 1, "dopo 24h l'avviso deve poter ripartire")


class TestPuro(unittest.TestCase):
    def test_offerta_rientra_input_assurdi_non_solleva(self):
        for a, o in ((None, None), ({}, {}), ({"attivo": 1}, {"prezzo_cents": "x"}),
                     ({"destinazione": "Roma", "budget_cents": None}, {"destinazione": "Roma"})):
            try:
                PA.offerta_rientra(a, o)
                PA.da_avvisare(a, o, 123)
            except Exception as e:
                self.fail("ha sollevato su (%r,%r): %s" % (a, o, e))

    def test_disattiva_esclude_dal_match(self):
        g = _mem()
        aid = g.registra(ospite_email="a@b.it", destinazione="Roma", budget_cents=10000)
        g.disattiva(aid)
        self.assertEqual(g.match_offerta({"destinazione": "Roma", "prezzo_cents": 1, "valuta": "EUR"}), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
