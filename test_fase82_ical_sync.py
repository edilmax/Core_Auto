"""
Test Fase 82 - iCal Sync.

Copre: parser VEVENT (DATE e DATE-TIME), line unfolding, eventi multipli, DTEND
esclusivo (semi-aperto), eventi malformati ignorati, sincronizzazione su fase58 (giorni
bloccati -> non disponibili), idempotenza, blocco non scende sotto l'occupato reale,
robustezza.
"""
import unittest

from fase58_channel_manager import crea_channel_manager
from fase82_ical_sync import analizza_ical, sincronizza

ICS_BASE = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Airbnb//EN
BEGIN:VEVENT
DTSTART;VALUE=DATE:20260701
DTEND;VALUE=DATE:20260703
UID:abc@airbnb
SUMMARY:Reserved
END:VEVENT
END:VCALENDAR
"""


class TestParser(unittest.TestCase):
    def test_vevent_date(self):
        self.assertEqual(analizza_ical(ICS_BASE), [("2026-07-01", "2026-07-03")])

    def test_date_time(self):
        ics = ("BEGIN:VEVENT\nDTSTART:20260801T140000Z\nDTEND:20260803T110000Z\n"
               "END:VEVENT")
        self.assertEqual(analizza_ical(ics), [("2026-08-01", "2026-08-03")])

    def test_eventi_multipli(self):
        ics = ("BEGIN:VEVENT\nDTSTART;VALUE=DATE:20260701\nDTEND;VALUE=DATE:20260702\n"
               "END:VEVENT\n"
               "BEGIN:VEVENT\nDTSTART;VALUE=DATE:20260710\nDTEND;VALUE=DATE:20260712\n"
               "END:VEVENT")
        self.assertEqual(len(analizza_ical(ics)), 2)

    def test_unfolding(self):
        ics = ("BEGIN:VEVENT\nDTSTART;VALUE=DATE:2026\n 0701\nDTEND;VALUE=DATE:20260702\n"
               "END:VEVENT")
        self.assertEqual(analizza_ical(ics), [("2026-07-01", "2026-07-02")])

    def test_malformato_ignorato(self):
        ics = ("BEGIN:VEVENT\nDTSTART;VALUE=DATE:20260703\nDTEND;VALUE=DATE:20260701\n"
               "END:VEVENT")   # DTEND < DTSTART -> scartato
        self.assertEqual(analizza_ical(ics), [])

    def test_senza_date_ignorato(self):
        self.assertEqual(analizza_ical("BEGIN:VEVENT\nSUMMARY:x\nEND:VEVENT"), [])

    def test_non_stringa(self):
        self.assertEqual(analizza_ical(None), [])
        self.assertEqual(analizza_ical(123), [])


class TestSincronizza(unittest.TestCase):
    def test_blocca_giorni(self):
        inv = crea_channel_manager()
        r = sincronizza(inv, "casa", ICS_BASE)
        self.assertEqual(r["eventi"], 1)
        self.assertEqual(r["giorni_bloccati"], 2)            # 01 e 02 (03 escluso)
        # quei giorni NON sono disponibili
        self.assertFalse(inv.disponibile("casa", "2026-07-01", "2026-07-02"))
        self.assertFalse(inv.disponibile("casa", "2026-07-02", "2026-07-03"))
        # il 03 (escluso da DTEND) resta libero da caricare
        self.assertIsNone(inv.stato_giorno("casa", "2026-07-03"))

    def test_idempotente(self):
        inv = crea_channel_manager()
        sincronizza(inv, "casa", ICS_BASE)
        r2 = sincronizza(inv, "casa", ICS_BASE)
        self.assertEqual(r2["giorni_bloccati"], 2)           # ri-blocca, nessun errore
        self.assertEqual(inv.stato_giorno("casa", "2026-07-01")["unita_totali"], 0)

    def test_non_scende_sotto_occupato(self):
        inv = crea_channel_manager()
        inv.imposta_disponibilita("casa", "2026-07-01", unita_totali=1,
                                  prezzo_netto_cents=10000)
        inv.blocca("casa", "2026-07-01", "2026-07-02", idem_key="reale")  # 1 occupato
        # l'iCal prova a portare a 0, ma c'e' 1 occupato reale -> fase58 rifiuta (fail-safe)
        sincronizza(inv, "casa", ICS_BASE)
        self.assertEqual(inv.stato_giorno("casa", "2026-07-01")["unita_totali"], 1)

    def test_robustezza(self):
        inv = crea_channel_manager()
        for bad in (None, 123, ""):
            try:
                sincronizza(inv, "casa", bad)
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")


class TestLeGuardieDeiPuntiScoperti(unittest.TestCase):
    """Una guardia per ogni punto che il Giudice della mutazione ha trovato SCOPERTO col
    solo occhio dedicato (2026-09-05, Blocco 2 casella 4: 6 punti su 19)."""

    def test_le_date_fuori_da_un_VEVENT_non_fanno_un_evento(self):
        # righe 77 e 91: `dentro` nasce False e una riga fuori da un evento si salta.
        self.assertEqual(analizza_ical("DTSTART:20260701\nDTEND:20260703\nEND:VEVENT"), [])

    def test_dopo_END_VEVENT_si_e_fuori(self):
        # riga 89: `dentro = False` dopo la fine -- un DTEND vagante non muove un evento.
        ics = ("BEGIN:VEVENT\nDTSTART:20260701\nDTEND:20260702\nEND:VEVENT\n"
               "DTEND:20260710\nEND:VEVENT")
        self.assertNotIn(("2026-07-01", "2026-07-10"), analizza_ical(ics))

    def test_evento_di_zero_giorni_scartato_e_il_tetto_e_incluso(self):
        # riga 86: `dtstart < dtend`; riga 87: `<= MAX_GIORNI_EVENTO` (366 passa, 367 no).
        self.assertEqual(analizza_ical("BEGIN:VEVENT\nDTSTART:20260701\nDTEND:20260701\n"
                                       "END:VEVENT"), [])
        self.assertEqual(analizza_ical("BEGIN:VEVENT\nDTSTART:20260101\nDTEND:20270102\n"
                                       "END:VEVENT"), [("2026-01-01", "2027-01-02")])
        self.assertEqual(analizza_ical("BEGIN:VEVENT\nDTSTART:20260101\nDTEND:20270103\n"
                                       "END:VEVENT"), [])

    def test_un_inventario_che_esplode_lascia_la_traccia(self):
        # riga 133: `exc_info=True` -- l'avviso porta LA COSA, del tipo giusto.
        class InvRotto:
            def imposta_disponibilita(self, *a, **k):
                raise RuntimeError("db giu'")
        with self.assertLogs("core_auto.ical_sync", level="WARNING") as registro:
            r = sincronizza(InvRotto(), "casa", ICS_BASE)
        self.assertEqual(r["giorni_bloccati"], 0)
        traccia = registro.records[0].exc_info
        self.assertIsInstance(traccia, tuple)
        self.assertIs(traccia[0], RuntimeError)


class TestLeGuardieDelGiro2(unittest.TestCase):
    """Una guardia per ogni punto SOPRAVVISSUTO al giro 2 di mutazione del Blocco 2
    (22/10/2026, commit 118593e): 8 punti, tutti in `prodid` e nei cinque risultati di
    `sincronizza`. Il flag `eco_ignorata` e i `exc_info` erano scritti e nessuno li leggeva."""

    ICS_NOSTRO = ICS_BASE.replace("PRODID:-//Airbnb//EN", "PRODID:-//BookinVIP//Calendario//IT")
    ICS_VUOTO = "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Airbnb//EN\nEND:VCALENDAR\n"

    def test_il_prodid_e_proprio_quello_della_riga_PRODID(self):
        # riga 119: `== "PRODID"` -- con `!=` si prenderebbe la PRIMA riga che non e'
        # PRODID («BEGIN:VCALENDAR» -> «VCALENDAR») e l'eco non si riconoscerebbe piu'.
        from fase82_ical_sync import prodid
        self.assertEqual(prodid(ICS_BASE), "-//Airbnb//EN")
        self.assertEqual(prodid(self.ICS_NOSTRO), "-//BookinVIP//Calendario//IT")

    def test_il_nostro_feed_riesportato_e_ignorato_e_lo_dice(self):
        # riga 170: `eco_ignorata: True` -- chi legge il risultato deve sapere PERCHE'
        # nessuna notte e' stata chiusa; e l'inventario resta intatto.
        inv = crea_channel_manager()
        r = sincronizza(inv, "casa", self.ICS_NOSTRO)
        self.assertIs(r["eco_ignorata"], True)
        self.assertEqual(r["eventi"], 0)
        self.assertIsNone(inv.stato_giorno("casa", "2026-07-01"))

    def test_un_feed_estraneo_non_e_mai_un_eco_in_nessun_ramo(self):
        # righe 191, 211, 239, 253: `eco_ignorata: False` in ognuna delle quattro uscite
        # che NON sono l'eco. Un True li' direbbe al pannello «era il nostro calendario».
        class SoloVecchio:                       # ramo un_verso_solo (riga 191)
            def imposta_disponibilita(self, *a, **k):
                return True
        r = sincronizza(SoloVecchio(), "casa", ICS_BASE)
        self.assertIn("un_verso_solo", r)
        self.assertIs(r["eco_ignorata"], False)

        inv = crea_channel_manager()             # ramo normale (riga 253)
        r = sincronizza(inv, "casa", ICS_BASE, feed_id="airbnb")
        self.assertEqual(r["anomalia"], "")
        self.assertIs(r["eco_ignorata"], False)
        # riga 204: `prima and not giorni` -- lo STESSO feed riletto con le sue notti non e'
        # un feed azzerato. Con `or` ogni secondo giro gridava «feed_azzerato» e non chiudeva
        # niente di nuovo: falso allarme e calendario fermo.
        r = sincronizza(inv, "casa", ICS_BASE, feed_id="airbnb")
        self.assertEqual(r["anomalia"], "")
        self.assertEqual(r["giorni_bloccati"], 2)

        r = sincronizza(inv, "casa", self.ICS_VUOTO, feed_id="airbnb")   # da N a zero (211)
        self.assertTrue(r["anomalia"].startswith("feed_azzerato"))
        self.assertIs(r["eco_ignorata"], False)

    def test_se_feed_applica_esplode_si_blocca_lo_stesso_e_resta_la_traccia(self):
        # righe 227 e 236: `exc_info=True` sull'errore di feed_applica e sull'avviso del
        # singolo giorno; riga 239: `eco_ignorata: False` anche nel ripiego.
        class ApplicaRotta:
            def feed_giorni(self, *a):
                return []
            def feed_applica(self, *a):
                raise ValueError("feed_applica giu'")
            def imposta_disponibilita(self, *a, **k):
                raise RuntimeError("giorno giu'")
        with self.assertLogs("core_auto.ical_sync", level="WARNING") as registro:
            r = sincronizza(ApplicaRotta(), "casa", ICS_BASE)
        self.assertIs(r["eco_ignorata"], False)
        self.assertEqual(r["giorni_bloccati"], 0)
        errori = [x for x in registro.records if x.levelname == "ERROR"]
        avvisi = [x for x in registro.records if x.levelname == "WARNING"]
        self.assertEqual(len(errori), 1)
        self.assertIsInstance(errori[0].exc_info, tuple)
        self.assertIs(errori[0].exc_info[0], ValueError)
        self.assertEqual(len(avvisi), 2)         # i due giorni, 01 e 02
        for a in avvisi:
            self.assertIsInstance(a.exc_info, tuple)
            self.assertIs(a.exc_info[0], RuntimeError)


if __name__ == "__main__":
    unittest.main()
