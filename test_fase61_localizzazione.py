"""
Test Fase 61 - Localizzazione (i18n) a costo zero.

Copre: deduzione lingua da prefisso (longest-prefix + fallback), notifiche localizzate,
fallback lingua/tipo ignoti, etichette servizi (codici fase57) + fallback, stati,
tagging contenuti pass-through, e l'integrazione reale col notificatore di fase58
(l'host riceve il testo nella SUA lingua dedotta dal telefono). Nessuna funzione solleva.
"""
import unittest

from fase58_channel_manager import crea_channel_manager
from fase61_localizzazione import (
    LINGUA_DEFAULT, LINGUE_SUPPORTATE, Localizzatore,
    crea_notificatore_localizzato, lingua_da_telefono, tagga_contenuto,
)


class TestLinguaDaTelefono(unittest.TestCase):
    def test_prefissi(self):
        self.assertEqual(lingua_da_telefono("+39 333 1234567"), "it")
        self.assertEqual(lingua_da_telefono("+44 20 7946 0000"), "en")
        self.assertEqual(lingua_da_telefono("+81-90-1234-5678"), "ja")
        self.assertEqual(lingua_da_telefono("+49 30 123456"), "de")

    def test_longest_prefix(self):
        # +351 (Portogallo) deve vincere su prefissi piu' corti
        self.assertEqual(lingua_da_telefono("+351912345678"), "pt")
        # +1 USA -> en
        self.assertEqual(lingua_da_telefono("+1 415 555 0100"), "en")

    def test_fallback(self):
        self.assertEqual(lingua_da_telefono("senza prefisso"), LINGUA_DEFAULT)
        self.assertEqual(lingua_da_telefono(None), LINGUA_DEFAULT)
        self.assertEqual(lingua_da_telefono("+999 sconosciuto"), LINGUA_DEFAULT)
        self.assertEqual(lingua_da_telefono("123", default="it"), "it")


class TestNotifiche(unittest.TestCase):
    def setUp(self):
        self.loc = Localizzatore()

    def test_render_lingue(self):
        it = self.loc.notifica("nuova_prenotazione", "it", alloggio="casa",
                               ci="2026-07-01", co="2026-07-03", origine="concierge")
        self.assertIn("Nuova prenotazione", it)
        self.assertIn("casa", it)
        en = self.loc.notifica("nuova_prenotazione", "en", alloggio="casa",
                               ci="2026-07-01", co="2026-07-03", origine="concierge")
        self.assertIn("New booking", en)

    def test_lingua_ignota_fallback_default(self):
        out = self.loc.notifica("nuova_prenotazione", "xx", alloggio="casa",
                                ci="a", co="b", origine="o")
        atteso = self.loc.notifica("nuova_prenotazione", LINGUA_DEFAULT, alloggio="casa",
                                   ci="a", co="b", origine="o")
        self.assertEqual(out, atteso)

    def test_tipo_ignoto_generico(self):
        out = self.loc.notifica("evento_mai_visto", "it", alloggio="casa", ci="a", co="b")
        self.assertIn("casa", out)
        self.assertIn("evento_mai_visto", out)

    def test_localizza_da_payload_fase58(self):
        payload = {"tipo": "nuova_prenotazione", "alloggio_id": "casa-mare",
                   "check_in": "2026-07-01", "check_out": "2026-07-03",
                   "origine": "esterno:booking"}
        out = self.loc.localizza_notifica(payload, "de")
        self.assertIn("Neue Buchung", out)
        self.assertIn("casa-mare", out)

    def test_localizza_payload_non_dict(self):
        self.assertEqual(self.loc.localizza_notifica("non dict", "it"), "")


class TestServiziStati(unittest.TestCase):
    def setUp(self):
        self.loc = Localizzatore()

    def test_servizio(self):
        self.assertEqual(self.loc.servizio("piscina", "en"), "Pool")
        self.assertEqual(self.loc.servizio("piscina", "it"), "Piscina")
        self.assertEqual(self.loc.servizio("piscina", "de"), "Pool")

    def test_servizio_codice_ignoto(self):
        self.assertEqual(self.loc.servizio("teletrasporto", "en"), "teletrasporto")

    def test_servizio_lingua_ignota_fallback(self):
        self.assertEqual(self.loc.servizio("wifi", "xx"),
                         self.loc.servizio("wifi", LINGUA_DEFAULT))

    def test_servizi_lista(self):
        out = self.loc.servizi(["wifi", "cucina"], "it")
        self.assertEqual(out, ["Wi-Fi", "Cucina"])

    def test_stato(self):
        self.assertEqual(self.loc.stato("confermata", "fr"), "Confirmée")
        self.assertEqual(self.loc.stato("ignoto", "it"), "ignoto")


class TestRisolviLingua(unittest.TestCase):
    def test_esplicita_vince(self):
        loc = Localizzatore("en")
        self.assertEqual(loc.risolvi_lingua(esplicita="ja", telefono="+39000"), "ja")

    def test_da_telefono(self):
        loc = Localizzatore("en")
        self.assertEqual(loc.risolvi_lingua(telefono="+39 333 000"), "it")

    def test_default(self):
        loc = Localizzatore("it")
        self.assertEqual(loc.risolvi_lingua(), "it")

    def test_esplicita_non_supportata_ignorata(self):
        loc = Localizzatore("en")
        self.assertEqual(loc.risolvi_lingua(esplicita="klingon", telefono="+49000"),
                         "de")


class TestTagging(unittest.TestCase):
    def test_tag_lingua_origine(self):
        t = tagga_contenuto("Bellissimo appartamento in centro", "it")
        self.assertEqual(t, {"text": "Bellissimo appartamento in centro", "lang": "it"})

    def test_tag_lingua_ignota_default(self):
        self.assertEqual(tagga_contenuto("x", "xx")["lang"], LINGUA_DEFAULT)

    def test_tag_testo_non_stringa(self):
        self.assertEqual(tagga_contenuto(123, "it")["text"], "")


class TestIntegrazioneFase58(unittest.TestCase):
    def test_host_riceve_nella_sua_lingua(self):
        """Inietto un notificatore localizzato in fase58: l'host tedesco riceve tedesco,
        l'host italiano italiano, dedotti dal telefono."""
        for telefono, atteso in (("+49 30 111", "Neue Buchung"),
                                  ("+39 333 111", "Nuova prenotazione"),
                                  ("+81 90 111", "新しい予約")):
            ricevute = []
            notif = crea_notificatore_localizzato(
                ricevute.append, lambda p, tel=telefono: lingua_da_telefono(tel))
            cm = crea_channel_manager(notificatore=notif)
            cm.imposta_disponibilita("casa", "2026-07-01", unita_totali=1,
                                     prezzo_netto_cents=10000)
            cm.blocca("casa", "2026-07-01", "2026-07-02", idem_key="k1")
            self.assertEqual(len(ricevute), 1)
            self.assertIn(atteso, ricevute[0]["testo"])
            self.assertIn("lingua", ricevute[0])

    def test_lingua_fissa(self):
        ricevute = []
        notif = crea_notificatore_localizzato(ricevute.append, "es")
        cm = crea_channel_manager(notificatore=notif)
        cm.imposta_disponibilita("casa", "2026-07-01", unita_totali=1,
                                 prezzo_netto_cents=10000)
        cm.blocca("casa", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertIn("Nueva reserva", ricevute[0]["testo"])


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        loc = Localizzatore()
        for bad in (None, 123, [], {}):
            try:
                loc.localizza_notifica(bad, "it")
                loc.servizio(bad, "it")
                loc.servizi(bad, "it")
                lingua_da_telefono(bad)
                tagga_contenuto(bad, "it")
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")

    def test_tutte_le_lingue_hanno_notifica_base(self):
        loc = Localizzatore()
        for lng in LINGUE_SUPPORTATE:
            out = loc.notifica("nuova_prenotazione", lng, alloggio="x", ci="a",
                               co="b", origine="o")
            self.assertTrue(out and "x" in out)


if __name__ == "__main__":
    unittest.main()
