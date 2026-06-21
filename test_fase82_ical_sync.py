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


if __name__ == "__main__":
    unittest.main()
