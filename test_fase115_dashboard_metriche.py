"""Test Fase 115 - Dashboard metriche avanzate. Puro, cents/bps interi."""
import unittest

from fase115_dashboard_metriche import calcola_metriche

PREN = [
    {"prezzo_guest_cents": 10000, "notti": 3, "lead_time_giorni": 10, "voto": 5},
    {"prezzo_guest_cents": 6000, "notti": 2, "lead_time_giorni": 20, "voto": 4},
    {"prezzo_guest_cents": 5000, "notti": 1, "rimborsato": True, "voto": 3},
]


class TestMetriche(unittest.TestCase):
    def test_revenue_solo_attive(self):
        m = calcola_metriche(PREN, giorni_periodo=30, unita=1)
        self.assertEqual(m["revenue_cents"], 16000)         # esclude rimborsata
        self.assertEqual(m["prenotazioni_attive"], 2)
        self.assertEqual(m["cancellate"], 1)

    def test_notti_e_occupazione(self):
        m = calcola_metriche(PREN, giorni_periodo=30, unita=1)
        self.assertEqual(m["notti_vendute"], 5)             # 3+2 (attive)
        self.assertEqual(m["notti_disponibili"], 30)
        self.assertEqual(m["occupazione_bps"], 5 * 10000 // 30)

    def test_adr_revpar(self):
        m = calcola_metriche(PREN, giorni_periodo=30)
        self.assertEqual(m["adr_cents"], 16000 // 5)        # 3200
        self.assertEqual(m["revpar_cents"], 16000 // 30)

    def test_cancellazione_e_rating(self):
        m = calcola_metriche(PREN)
        self.assertEqual(m["tasso_cancellazione_bps"], 1 * 10000 // 3)
        self.assertEqual(m["rating_medio_centi"], (5 + 4 + 3) * 100 // 3)   # 400

    def test_lead_time_medio(self):
        m = calcola_metriche(PREN)
        self.assertEqual(m["lead_time_medio_giorni"], 15)   # (10+20)/2 attive

    def test_vuoto_zero(self):
        m = calcola_metriche([])
        self.assertEqual(m["revenue_cents"], 0)
        self.assertEqual(m["occupazione_bps"], 0)
        self.assertEqual(m["adr_cents"], 0)

    def test_record_invalidi_ignorati(self):
        m = calcola_metriche([{"prezzo_guest_cents": "x"}, None, 5], giorni_periodo=10)
        self.assertEqual(m["revenue_cents"], 0)
        self.assertEqual(m["prenotazioni_totali"], 1)       # solo il dict valido

    def test_occupazione_cap_100(self):
        tanti = [{"prezzo_guest_cents": 1000, "notti": 50}]
        m = calcola_metriche(tanti, giorni_periodo=30, unita=1)
        self.assertEqual(m["occupazione_bps"], 10000)       # cap a 100%

    def test_interi(self):
        m = calcola_metriche(PREN)
        for v in m.values():
            self.assertIsInstance(v, int)


# ═══════════════════════════════════════════════════════════════════════════════════════
# I 2 PUNTI SOPRAVVISSUTI DELLA NOTTE FRA IL 6 E IL 7 SETTEMBRE 2026 (Giudice, Blocco 4)
# ═══════════════════════════════════════════════════════════════════════════════════════

class TestI2PuntiSopravvissutiDellaNotteDel7Settembre(unittest.TestCase):
    """Il Giudice (giudice_notte_blocchi_4_7) ha trovato 2 punti: una prenotazione con
    `notti` a ZERO deve ricalcolare le notti dalle date (non fidarsi dello zero), e un
    lead time di ZERO giorni (prenotato il giorno stesso) entra nella media. UNA guardia
    per punto, vista ROSSA col mutante iniettato con l'editor."""

    def test_riga20_con_notti_a_ZERO_le_notti_si_ricalcolano_dalle_date(self):
        p = [{"prezzo_guest_cents": 20000, "notti": 0,
              "check_in": "2026-09-10", "check_out": "2026-09-12"}]
        m = calcola_metriche(p, giorni_periodo=30, unita=1)
        self.assertEqual(2, m["notti_vendute"], "notti=0 e' stato preso per buono")
        self.assertEqual(10000, m["adr_cents"])

    def test_riga50_un_lead_time_di_ZERO_giorni_entra_nella_media(self):
        p = [{"prezzo_guest_cents": 100, "notti": 1, "lead_time_giorni": 0},
             {"prezzo_guest_cents": 100, "notti": 1, "lead_time_giorni": 4}]
        self.assertEqual(2, calcola_metriche(p)["lead_time_medio_giorni"],
                         "la prenotazione del giorno stesso e' uscita dalla media")
        p_neg = [{"prezzo_guest_cents": 100, "notti": 1, "lead_time_giorni": -1}]
        self.assertEqual(0, calcola_metriche(p_neg)["lead_time_medio_giorni"])


if __name__ == "__main__":
    unittest.main()
