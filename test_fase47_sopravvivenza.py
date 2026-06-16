"""
Suite di SOPRAVVIVENZA TOTALE per M5 (fase47) - Manifesto dell'Eternita'.
CHAOS (input corrotti, GDPR fail-closed), FUZZING (capacita'/dedup/ordine su
migliaia di lead), ISOLAMENTO (policy rotta non contagia), IDEMPOTENZA.
"""
import random
import unittest

from fase47_venditore import (
    Lead, StatoContatto, PoliticaOutreachConsensata, PoliticaOutreach,
    MotoreVenditore, crea_venditore)


def _lead(id, pain=1000):
    return Lead(id, pain, "email", id + "@h.it")


class TestChaosVenditore(unittest.TestCase):
    def test_lead_corrotto_rifiutato(self):
        for kw in (dict(proprieta_id="", pain_score=1, canale="email", contatto="x"),
                   dict(proprieta_id="a", pain_score=-1, canale="email", contatto="x"),
                   dict(proprieta_id="a", pain_score=1, canale="", contatto="x")):
            with self.assertRaises(ValueError):
                Lead(**kw)

    def test_stato_corrotto_rifiutato(self):
        for kw in (dict(consenso="si"), dict(tocchi=-1), dict(ultimo_giorno=-5)):
            with self.assertRaises(ValueError):
                StatoContatto(**kw)

    def test_gdpr_fail_closed_default(self):
        # un lead senza stato non viene MAI contattato (default = nessun consenso)
        mot = crea_venditore()
        leads = [_lead("a"), _lead("b")]
        self.assertEqual(mot.pianifica(leads, {}, giorno=10, capacita=100), [])


class TestFuzzingVenditore(unittest.TestCase):
    def test_fuzz_invarianti(self):
        mot = crea_venditore()
        rng = random.Random(47)
        for _ in range(300):
            n = rng.randint(0, 300)
            leads = [_lead("L%03d" % i, rng.randint(0, 10**7)) for i in range(n)]
            stato = {l.proprieta_id: StatoContatto(
                consenso=rng.random() > 0.3, opt_out=rng.random() < 0.15,
                tocchi=rng.randint(0, 4),
                ultimo_giorno=rng.choice([None, rng.randint(0, 10)])) for l in leads}
            cap = rng.randint(0, 50)
            plan = mot.pianifica(leads, stato, giorno=10, capacita=cap)
            self.assertLessEqual(len(plan), cap)                       # backpressure
            ids = [i.proprieta_id for i in plan]
            self.assertEqual(len(ids), len(set(ids)))                  # nessun duplicato
            for i in plan:                                             # GDPR + dedup + cadenza
                s = stato[i.proprieta_id]
                self.assertTrue(s.consenso and not s.opt_out and s.tocchi < 4)
                self.assertTrue(s.ultimo_giorno is None or 10 - s.ultimo_giorno >= 3)


class TestIsolamentoIdempotenza(unittest.TestCase):
    def test_policy_rotta_non_contagia(self):
        class PoliticaEsplosiva(PoliticaOutreach):
            def eleggibile(self, lead, stato, giorno): raise RuntimeError("rotta")
            def chiave_ordine(self, lead): return 0
            def descrizione(self): return "x"
        leads = [_lead("a")]
        stato = {"a": StatoContatto(consenso=True)}
        with self.assertRaises(RuntimeError):
            MotoreVenditore(PoliticaEsplosiva()).pianifica(leads, stato, 10, 10)
        # il motore sano resta operativo
        self.assertEqual(len(crea_venditore().pianifica(leads, stato, 10, 10)), 1)

    def test_idempotenza(self):
        mot = crea_venditore()
        leads = [_lead("a", 5000), _lead("b", 9000), _lead("c", 1000)]
        stato = {x: StatoContatto(consenso=True) for x in ("a", "b", "c")}
        a = [i.proprieta_id for i in mot.pianifica(leads, stato, 10, 2)]
        b = [i.proprieta_id for i in mot.pianifica(leads, stato, 10, 2)]
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
