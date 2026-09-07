"""
Test Fase 75 - Guardian Engine.

Copre: water leak (critico, stato manutenzione), fuoco/CO (emergenza, evacuazione),
muffa (richiede durata sostenuta: scatta solo oltre 48h, non sul transitorio), nessun
pericolo (ok), letture non-intere ignorate, pericoli multipli (union azioni, severita'
max), esecuzione attuatori isolata, regole custom, robustezza.
"""
import dataclasses
import logging
import unittest

from fase75_guardian_engine import (
    GuardianEngine, Pericolo, RegolaPericolo, ReportGuardian, crea_guardian,
)

H48 = 172800


class TestRilevamento(unittest.TestCase):
    def setUp(self):
        self.g = crea_guardian()

    def test_water_leak(self):
        r = self.g.valuta("casa", {"water": 1})
        self.assertTrue(r.critico)
        self.assertEqual(r.pericoli[0].tipo, "water_leak")
        self.assertIn("chiudi_acqua", r.azioni_consigliate)
        self.assertIn("genera_claim", r.azioni_consigliate)
        self.assertEqual(r.stato_consigliato, "manutenzione")

    def test_fuoco_emergenza(self):
        r = self.g.valuta("casa", {"fumo": 1})
        self.assertEqual(r.stato_consigliato, "emergenza")
        self.assertIn("evacua_ospite", r.azioni_consigliate)
        self.assertIn("chiama_emergenza", r.azioni_consigliate)

    def test_co(self):
        r = self.g.valuta("casa", {"co": 80})       # >50 ppm
        self.assertTrue(r.critico)
        self.assertEqual(r.stato_consigliato, "emergenza")

    def test_co_sotto_soglia_no(self):
        r = self.g.valuta("casa", {"co": 20})
        self.assertEqual(r.pericoli, [])

    def test_nessun_pericolo(self):
        r = self.g.valuta("casa", {"water": 0, "fumo": 0, "co": 10, "umidita": 450})
        self.assertEqual(r.pericoli, [])
        self.assertEqual(r.stato_consigliato, "ok")


class TestMuffaDurata(unittest.TestCase):
    def setUp(self):
        self.g = crea_guardian()

    def test_muffa_sostenuta(self):
        r = self.g.valuta("casa", {"umidita": 650},
                          durate_sostenute={"umidita": H48})
        self.assertEqual(len(r.pericoli), 1)
        self.assertEqual(r.pericoli[0].tipo, "mold_risk")
        self.assertIn("pulizia_prioritaria", r.azioni_consigliate)

    def test_umidita_alta_ma_transitoria_no(self):
        # umidita' oltre soglia ma solo per 1h (doccia) -> nessun falso positivo
        r = self.g.valuta("casa", {"umidita": 700}, durate_sostenute={"umidita": 3600})
        self.assertEqual(r.pericoli, [])

    def test_umidita_alta_senza_durata_no(self):
        r = self.g.valuta("casa", {"umidita": 700})   # nessuna durata fornita -> 0
        self.assertEqual(r.pericoli, [])


class TestMultiplo(unittest.TestCase):
    def test_water_piu_fuoco(self):
        g = crea_guardian()
        r = g.valuta("casa", {"water": 1, "fumo": 1})
        self.assertEqual(len(r.pericoli), 2)
        self.assertEqual(r.stato_consigliato, "emergenza")   # emergenza prevale
        # azioni unite senza duplicati
        self.assertEqual(len(r.azioni_consigliate), len(set(r.azioni_consigliate)))


class TestEsecuzione(unittest.TestCase):
    def test_attuatori_isolati(self):
        g = crea_guardian()
        r = g.valuta("casa", {"water": 1})
        eseguite = []

        def ok_fn(rep):
            eseguite.append(rep.alloggio_id)

        def boom(rep):
            raise RuntimeError("valvola bloccata")

        attuatori = {"chiudi_acqua": boom, "notifica_urgente": ok_fn,
                     "blocca_manutenzione": ok_fn, "genera_claim": ok_fn}
        esiti = g.esegui(r, attuatori)
        self.assertFalse(esiti["chiudi_acqua"])     # isolato, non crasha
        self.assertTrue(esiti["notifica_urgente"])
        self.assertEqual(len(eseguite), 3)

    def test_azione_senza_attuatore(self):
        g = crea_guardian()
        r = g.valuta("casa", {"fumo": 1})
        esiti = g.esegui(r, {})                      # nessun attuatore
        self.assertTrue(all(v is False for v in esiti.values()))


class TestCustom(unittest.TestCase):
    def test_regola_custom_giu(self):
        # es. temperatura troppo bassa (gelo): valore <= soglia
        regole = (RegolaPericolo("gelo", "temp", 0, "avviso", ("riscalda",),
                                 direzione="giu"),)
        g = crea_guardian(regole)
        self.assertEqual(len(g.valuta("casa", {"temp": -50}).pericoli), 1)
        self.assertEqual(g.valuta("casa", {"temp": 200}).pericoli, [])


class TestRobustezza(unittest.TestCase):
    def test_letture_non_intere_ignorate(self):
        g = crea_guardian()
        r = g.valuta("casa", {"water": 1.0, "fumo": True, "co": "80"})
        self.assertEqual(r.pericoli, [])            # nessuna lettura intera valida

    def test_mai_solleva(self):
        g = crea_guardian()
        for bad in (None, 123, "x", []):
            try:
                rep = g.valuta("casa", bad)
                g.esegui(rep, bad)
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════════════
# I 6 PUNTI SOPRAVVISSUTI DELLA NOTTE FRA IL 6 E IL 7 SETTEMBRE 2026 (Giudice, Blocco 7)
# ═══════════════════════════════════════════════════════════════════════════════════════

class TestI6PuntiSopravvissutiDellaNotteDel7Settembre(unittest.TestCase):
    """Il Giudice (giudice_notte_blocchi_4_7) ha trovato 6 punti in cui il guasto passa e i
    test restano verdi: il confine ESATTO di una soglia «giu», una regola immediata che
    si lasciava spegnere da una durata di tipo storto, lo stato 'manutenzione' deciso al
    contrario, la traccia dell'attuatore che esplode, e i due `frozen`. UNA guardia per
    punto, vista ROSSA col mutante iniettato con l'editor."""

    # ── righe 47 · 77: regola e pericolo sono IMMUTABILI ──────────────────────────
    def test_riga47_RegolaPericolo_e_congelata(self):
        r = RegolaPericolo("gelo", "temp", 0, "avviso", ("riscalda",), direzione="giu")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.soglia = 100
        self.assertEqual(hash(RegolaPericolo("gelo", "temp", 0, "avviso", ("riscalda",),
                                             direzione="giu")), hash(r))

    def test_riga77_Pericolo_e_congelato(self):
        p = Pericolo("fire", "fumo", 1, "critico", ("allarme",))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.severita = "avviso"
        self.assertEqual(hash(Pericolo("fire", "fumo", 1, "critico", ("allarme",))), hash(p))

    # ── riga 115: la soglia «giu» scatta ANCHE sul valore esatto ───────────────────
    def test_riga115_una_soglia_giu_scatta_sul_valore_ESATTO_e_non_un_passo_sopra(self):
        regole = (RegolaPericolo("gelo", "temp", 0, "avviso", ("riscalda",), direzione="giu"),)
        g = crea_guardian(regole)
        self.assertEqual(1, len(g.valuta("casa", {"temp": 0}).pericoli), "temp = soglia ignorata")
        self.assertEqual([], g.valuta("casa", {"temp": 1}).pericoli)

    # ── riga 118: una regola IMMEDIATA non guarda le durate, nemmeno se sono storte ─
    def test_riga118_una_regola_immediata_scatta_anche_con_una_durata_di_tipo_storto(self):
        g = crea_guardian()
        for durate in ({"water": "n/d"}, {"water": None}, {"water": -1}, {"water": 0}):
            rep = g.valuta("casa", {"water": 1}, durate_sostenute=durate)
            self.assertEqual(["water_leak"], [p.tipo for p in rep.pericoli],
                             "la perdita d'acqua non scatta con durate=%r" % (durate,))

    # ── riga 134: 'manutenzione' solo se c'e' DAVVERO l'azione di blocco ───────────
    def test_riga134_lo_stato_manutenzione_dipende_dall_azione_di_blocco_non_dalle_altre(self):
        solo_avviso = (RegolaPericolo("x", "s", 1, "avviso", ("notifica_host",)),)
        self.assertEqual("ok", crea_guardian(solo_avviso).valuta("casa", {"s": 1}).stato_consigliato,
                         "un avviso senza blocco e' diventato 'manutenzione'")
        solo_blocco = (RegolaPericolo("x", "s", 1, "avviso", ("blocca_manutenzione",)),)
        self.assertEqual("manutenzione",
                         crea_guardian(solo_blocco).valuta("casa", {"s": 1}).stato_consigliato)

    # ── riga 156: l'attuatore che esplode lascia LA traccia nel registro ──────────
    def test_riga156_un_attuatore_che_esplode_grida_ERROR_con_la_traccia(self):
        g = crea_guardian()
        rep = g.valuta("casa", {"fumo": 1})

        def boom(_):
            raise RuntimeError("sirena muta")
        with self.assertLogs("core_auto.guardian", level="ERROR") as cm:
            esiti = g.esegui(rep, {"allarme": boom})
        self.assertIs(False, esiti["allarme"])
        self.assertEqual(1, len(cm.records))
        rec = cm.records[0]
        self.assertEqual(logging.ERROR, rec.levelno)
        self.assertIsInstance(rec.exc_info, tuple, "l'attuatore fallito non lascia la traccia")
        self.assertIs(RuntimeError, rec.exc_info[0])


if __name__ == "__main__":
    unittest.main()
