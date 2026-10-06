"""Test rotte /api/messaggi (fase113 cablato nel server fase83). Puro via gestisci."""
import json
import unittest

from fase83_server import crea_router
from fase113_messaggistica import crea_messaggistica


class Sys:
    attivo = True

    def __init__(self, con_msg=True):
        self.registro_host = None
        self.messaggistica = None
        if con_msg:
            self.messaggistica = crea_messaggistica(":memory:")
            self.messaggistica.inizializza_schema()


H = {"X-Host-Key": "k"}


class TestMessaggiEndpoint(unittest.TestCase):
    def _router(self, con_msg=True):
        return crea_router(Sys(con_msg), host_key="k")

    def test_invia_e_thread(self):
        r = self._router()
        s, c = r.gestisci("POST", "/api/messaggi", {},
                          json.dumps({"prenotazione_id": "REF1", "guest_id": "g@x.it",
                                      "testo": "A che ora il check-in?"}), H)
        self.assertEqual(s, 201)
        s2, c2 = r.gestisci("GET", "/api/messaggi", {"prenotazione_id": "REF1"}, None, H)
        self.assertEqual(s2, 200)
        self.assertEqual(len(c2["messaggi"]), 1)
        self.assertEqual(c2["messaggi"][0]["mittente"], "host")

    def test_maschera_pii(self):
        r = self._router()
        r.gestisci("POST", "/api/messaggi", {},
                   json.dumps({"prenotazione_id": "R", "guest_id": "g@x.it",
                               "testo": "scrivimi a mario@gmail.com"}), H)
        c = r.gestisci("GET", "/api/messaggi", {"prenotazione_id": "R"}, None, H)[1]
        self.assertNotIn("mario@gmail.com", c["messaggi"][0]["testo"])

    def test_unauth(self):
        s, _ = self._router().gestisci("POST", "/api/messaggi", {}, "{}", {})
        self.assertEqual(s, 401)

    def test_gated_senza_modulo(self):
        s, c = crea_router(Sys(con_msg=False), host_key="k").gestisci(
            "POST", "/api/messaggi", {}, "{}", H)
        self.assertEqual(s, 503)

    def test_campi_invalidi(self):
        s, _ = self._router().gestisci("POST", "/api/messaggi", {},
                                       json.dumps({"prenotazione_id": "R"}), H)
        self.assertEqual(s, 422)


class TestLaChatEDellaPrenotazioneEDelSuoHost(unittest.TestCase):
    """V1 della busta 6 (Compito 50, 2026-10-05): `POST /api/messaggi` prendeva prenotazione e
    guest_id dal corpo senza controllare niente, e `fase113.thread` restituisce un thread VUOTO se
    anche una sola riga ha un partecipante diverso. Una riga con guest_id diverso da 'ospite' --
    anche scritta per sbaglio dall'host della prenotazione nel modulo manuale del pannello --
    toglieva la chat all'ospite e all'arbitro e spegneva `_subentro_per_disaccordo`: la garanzia
    si sbloccava da sola e i soldi andavano all'host malgrado il disaccordo scritto. E un host
    estraneo che conosceva un riferimento scriveva nella chat di una prenotazione non sua.
    Sistema vero, due host veri, la prenotazione vera (il pendente) dell'host A."""

    CHECKIN = 1_800_000_000

    def setUp(self):
        import shutil
        import tempfile
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"m" * 32, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db",
            db_messaggi=f"{d}/m.db", db_domanda=f"{d}/dom.db", db_garanzia=f"{d}/g.db",
            db_payout=f"{d}/y.db", db_pendenti=f"{d}/p.db", file_referral=f"{d}/ref.json"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        a = self.sis.registro_host.registra("a@host.it", "password-a-1", accetta_termini=True)
        b = self.sis.registro_host.registra("b@host.it", "password-b-1", accetta_termini=True)
        self.assertTrue(a.ok and b.ok)
        self.hid_a, self.tok_a, self.tok_b = a.host_id, a.token, b.token
        self.assertTrue(self.sis.pagamenti_pendenti.registra(
            "RIF-A", alloggio_id="casa-di-a", check_in="2027-03-01", check_out="2027-03-03",
            host_id=self.hid_a))
        self.msg = self.sis.messaggistica

    def _post(self, tok, corpo):
        return self.r.gestisci("POST", "/api/messaggi", {}, json.dumps(corpo),
                               {"X-Host-Token": tok})

    def test_L_HOST_DELLA_PRENOTAZIONE_NON_PUO_SVUOTARE_LA_CHAT_DELL_OSPITE(self):
        self.assertTrue(self.msg.invia("RIF-A", self.hid_a, "ospite", "ospite", "la doccia non va"))
        s, _ = self._post(self.tok_a, {"prenotazione_id": "RIF-A", "guest_id": "mario",
                                       "testo": "non e' vero"})
        self.assertEqual(201, s)
        testi = [m["testo"] for m in self.msg.thread("RIF-A", "ospite")]
        self.assertIn("la doccia non va", testi)      # l'ospite e l'arbitro la vedono ancora
        self.assertIn("non e' vero", testi)           # e vedono anche la risposta dell'host

    def test_IL_SUBENTRO_PER_DISACCORDO_RESTA_ACCESO(self):
        import fase83_server as S
        self.assertTrue(self.sis.garanzia.apri("RIF-A", 17000, alloggio_id="casa-di-a",
                                               ora_checkin_ts=self.CHECKIN))
        self.msg._now = lambda: self.CHECKIN + 3600
        self.assertTrue(self.msg.invia("RIF-A", self.hid_a, "ospite", "ospite", "la doccia non va"))
        self.msg._now = lambda: self.CHECKIN + 7200
        s, _ = self._post(self.tok_a, {"prenotazione_id": "RIF-A", "guest_id": "mario",
                                       "testo": "non e' vero"})
        self.assertEqual(201, s)
        self.assertEqual(["RIF-A"], S._subentro_per_disaccordo(
            self.sis, ora_ts=self.CHECKIN + 24 * 3600 + 60))
        self.assertEqual("contestato", self.sis.garanzia.stato("RIF-A")["stato"])

    def test_UN_ALTRO_HOST_NON_SCRIVE_NELLA_CHAT_DI_UNA_PRENOTAZIONE_NON_SUA(self):
        self.assertTrue(self.msg.invia("RIF-A", self.hid_a, "ospite", "ospite", "ciao"))
        s, _ = self._post(self.tok_b, {"prenotazione_id": "RIF-A", "guest_id": "ospite",
                                       "testo": "paga qui"})
        self.assertEqual(403, s)
        self.assertEqual(["ciao"], [m["testo"] for m in self.msg.thread("RIF-A", "ospite")])
        self.assertEqual(["ciao"], [m["testo"] for m in self.msg.thread("RIF-A", self.hid_a)])

    def test_UN_ALTRO_HOST_NON_LEGGE_LA_CHAT_DI_UNA_PRENOTAZIONE_NON_SUA(self):
        self.assertTrue(self.msg.invia("RIF-A", self.hid_a, "ospite", "ospite", "ciao"))
        s, c = self.r.gestisci("GET", "/api/messaggi", {"prenotazione_id": "RIF-A"}, None,
                               {"X-Host-Token": self.tok_b})
        self.assertEqual(403, s)
        self.assertNotIn("messaggi", c)

    def test_UNA_PRENOTAZIONE_CHE_NON_ESISTE_NON_HA_CHAT(self):
        s, _ = self._post(self.tok_a, {"prenotazione_id": "NON-ESISTE", "guest_id": "ospite",
                                       "testo": "ciao"})
        self.assertEqual(404, s)
        s, _ = self.r.gestisci("GET", "/api/messaggi", {"prenotazione_id": "NON-ESISTE"}, None,
                               {"X-Host-Token": self.tok_a})
        self.assertEqual(404, s)

    def test_SE_IL_PADRONE_NON_SI_PUO_LEGGERE_SI_NEGA(self):
        # D19: lo stato «impossibile» costruito a mano -- il catalogo che non risponde.
        def _guasto(*_a, **_k):
            raise RuntimeError("catalogo giu'")
        self.sis.catalogo.host_di_alloggio = _guasto
        s, c = self._post(self.tok_a, {"prenotazione_id": "RIF-A", "guest_id": "ospite",
                                       "testo": "ciao"})
        self.assertEqual((403, {"errore": "non_tua"}), (s, c))
        self.assertEqual([], self.msg.thread("RIF-A", self.hid_a))

    def test_SENZA_UN_PADRONE_LEGGIBILE_NESSUN_HOST_ENTRA(self):
        # il pendente senza host_id (come in V7) su un annuncio che il catalogo non conosce
        self.assertTrue(self.sis.pagamenti_pendenti.registra(
            "RIF-ORFANO", alloggio_id="casa-sparita", check_in="2027-03-01",
            check_out="2027-03-03", host_id=""))
        for tok in (self.tok_a, self.tok_b):
            s, _ = self._post(tok, {"prenotazione_id": "RIF-ORFANO", "guest_id": "ospite",
                                    "testo": "ciao"})
            self.assertEqual(403, s)

    def test_IL_PADRONE_SI_RILEGGE_DALL_ANNUNCIO(self):
        # il pendente non porta il padrone, l'annuncio si': decide l'annuncio
        self.assertTrue(self.sis.pagamenti_pendenti.registra(
            "RIF-X", alloggio_id="casa-di-a", check_in="2027-03-01", check_out="2027-03-03",
            host_id=""))
        self.sis.catalogo.host_di_alloggio = \
            lambda slug: self.hid_a if slug == "casa-di-a" else None
        s, _ = self._post(self.tok_a, {"prenotazione_id": "RIF-X", "guest_id": "ospite",
                                       "testo": "ciao"})
        self.assertEqual(201, s)
        s, _ = self._post(self.tok_b, {"prenotazione_id": "RIF-X", "guest_id": "ospite",
                                       "testo": "ciao"})
        self.assertEqual(403, s)

    def test_IL_PADRONE_SCRIVE_E_LEGGE_LA_SUA_CHAT(self):
        s, _ = self._post(self.tok_a, {"prenotazione_id": "RIF-A", "guest_id": "ospite",
                                       "testo": "benvenuto"})
        self.assertEqual(201, s)
        s, c = self.r.gestisci("GET", "/api/messaggi", {"prenotazione_id": "RIF-A"}, None,
                               {"X-Host-Token": self.tok_a})
        self.assertEqual(200, s)
        self.assertEqual(["benvenuto"], [m["testo"] for m in c["messaggi"]])


if __name__ == "__main__":
    unittest.main()
