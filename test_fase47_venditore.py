"""
Test funzionali del Venditore del Core (fase47, M5). Outreach consensato GDPR,
dedup, cadenza, backpressure, prioritizzazione pain, iniezione.
"""
import unittest

from fase47_venditore import (
    Lead, StatoContatto, OutreachIntent, PoliticaOutreachConsensata,
    MotoreVenditore, crea_venditore)


def _lead(id, pain=1000):
    return Lead(id, pain, "email", id + "@host.it")


class TestPianificazione(unittest.TestCase):
    def setUp(self):
        self.mot = crea_venditore()

    def test_prioritizza_pain_entro_capacita(self):
        leads = [_lead("a", 100), _lead("b", 9000), _lead("c", 5000)]
        stato = {x: StatoContatto(consenso=True) for x in ("a", "b", "c")}
        plan = self.mot.pianifica(leads, stato, giorno=10, capacita=2)
        self.assertEqual([i.proprieta_id for i in plan], ["b", "c"])   # i 2 piu' caldi

    def test_consenso_mancante_fail_closed(self):
        leads = [_lead("a")]
        plan = self.mot.pianifica(leads, {}, giorno=10, capacita=10)   # nessuno stato
        self.assertEqual(plan, [])

    def test_optout_rispettato(self):
        leads = [_lead("a")]
        stato = {"a": StatoContatto(consenso=True, opt_out=True)}
        self.assertEqual(self.mot.pianifica(leads, stato, 10, 10), [])

    def test_dedup_max_tocchi(self):
        leads = [_lead("a")]
        stato = {"a": StatoContatto(consenso=True, tocchi=4)}            # gia' al massimo
        self.assertEqual(self.mot.pianifica(leads, stato, 10, 10), [])

    def test_cadenza_gap(self):
        leads = [_lead("a")]
        recente = {"a": StatoContatto(consenso=True, ultimo_giorno=9)}   # contattato ieri
        self.assertEqual(self.mot.pianifica(leads, recente, 10, 10), [])
        vecchio = {"a": StatoContatto(consenso=True, ultimo_giorno=5)}   # 5 giorni fa
        self.assertEqual(len(self.mot.pianifica(leads, vecchio, 10, 10)), 1)

    def test_passo_incrementa(self):
        leads = [_lead("a")]
        stato = {"a": StatoContatto(consenso=True, tocchi=2, ultimo_giorno=1)}
        plan = self.mot.pianifica(leads, stato, 10, 10)
        self.assertEqual(plan[0].passo, 3)                              # tocchi 2 -> passo 3

    def test_capacita_backpressure(self):
        leads = [_lead("L%02d" % i, pain=i) for i in range(100)]
        stato = {l.proprieta_id: StatoContatto(consenso=True) for l in leads}
        self.assertEqual(len(self.mot.pianifica(leads, stato, 10, 30)), 30)


class TestIniezione(unittest.TestCase):
    def test_politica_piu_permissiva(self):
        leads = [_lead("a")]
        stato = {"a": StatoContatto(consenso=True, tocchi=4)}
        stretta = MotoreVenditore(PoliticaOutreachConsensata(max_tocchi=4))
        larga = MotoreVenditore(PoliticaOutreachConsensata(max_tocchi=6))
        self.assertEqual(stretta.pianifica(leads, stato, 10, 10), [])    # bloccato a 4
        self.assertEqual(len(larga.pianifica(leads, stato, 10, 10)), 1)  # consentito fino a 6


if __name__ == "__main__":
    unittest.main()
