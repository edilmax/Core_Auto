"""Test 'tasto cancella tutto + verifica ovunque' (fase156): registra host -> pubblica ->
disponibilita -> prenota -> messaggio, poi cancella_attivita_host -> tutto rimosso da OGNI
archivio + verifica residui 0. Endpoint admin + idempotenza."""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase156_erasure import cancella_attivita_host

SEG = b"e" * 32
HK = {"X-Host-Key": "hk"}
AK = {"X-Admin-Key": "ak"}


class TestErasure(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db",
            db_messaggi=f"{d}/m.db", file_referral=f"{d}/ref.json", commissione_bps=1500))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@x.it", "password": "passw0rd!", "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True})
        self.hid = c["host_id"]
        self.g("POST", "/api/host/pubblica", {
            "host_id": self.hid, "slug": "casa", "titolo": "Casa", "citta": "Roma",
            "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
            "servizi": [], "immagini": ["https://x/y.jpg"]}, HK)
        self.g("POST", "/api/host/disponibilita_range", {
            "alloggio_id": "casa", "da": "2026-08-01", "a": "2026-08-31",
            "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)
        _, q = self.g("POST", "/api/concierge/quote", {
            "alloggio_id": "casa", "check_in": "2026-08-10", "check_out": "2026-08-12",
            "party": 1})
        self.g("POST", "/api/concierge/book",
                {"quote_token": q["quote_token"], "email": "o@x.it"})
        self.sis.messaggistica.invia("P1", self.hid, "o@x.it", self.hid, "ciao")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, body=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {},
                               json.dumps(body) if body is not None else None, h or {})

    def test_dati_presenti_prima(self):
        self.assertEqual(self.sis.catalogo.conta_alloggi_host(self.hid), 1)
        self.assertTrue(self.sis.registro_host.esiste_host(self.hid))
        self.assertGreaterEqual(self.sis.inventario.conta_alloggio("casa"), 1)
        self.assertEqual(self.sis.messaggistica.conta_messaggi_host(self.hid), 1)

    def test_host_con_prenotazione_e_RIFIUTATO_senza_forza(self):
        """Dal 2026-07-22: questo host ha una prenotazione FUTURA (un ospite che ha
        pagato). Cancellarlo lo lascerebbe senza stanza -> la cancellazione DEVE
        rifiutare, a meno di forzarla. E' la riparazione (a) dell'audit integrita'."""
        rep = cancella_attivita_host(self.sis, self.hid)
        self.assertFalse(rep.get("ok"))
        self.assertEqual(rep.get("errore"), "obblighi_pendenti")
        self.assertIn("prenotazioni_attive", rep.get("obblighi", {}))
        # e NON ha cancellato nulla: l'host e i dati ci sono ancora
        self.assertTrue(self.sis.registro_host.esiste_host(self.hid))

    def test_cancella_ovunque_e_verifica(self):
        # il meccanismo di WIPE: con forza=True (obbligo legale inderogabile) deve
        # comunque togliere tutto da ogni archivio e verificare 0 residui.
        rep = cancella_attivita_host(self.sis, self.hid, forza=True)
        self.assertTrue(rep["ok"])                         # 0 residui ovunque
        self.assertIn("forzato_nonostante", rep)           # tracciato cosa c'era
        self.assertGreaterEqual(rep["cancellati"]["alloggi"], 1)
        self.assertEqual(rep["cancellati"]["host"], 1)
        self.assertTrue(all(v == 0 for v in rep["residui"].values()))
        # davvero sparito da ogni archivio:
        self.assertIsNone(self.sis.catalogo.dettaglio("casa"))
        self.assertFalse(self.sis.registro_host.esiste_host(self.hid))
        self.assertEqual(self.sis.inventario.conta_alloggio("casa"), 0)
        self.assertEqual(self.sis.messaggistica.conta_messaggi_host(self.hid), 0)

    def test_endpoint_admin(self):
        # senza forza: rifiutato (obblighi) -> 409
        s, c = self.g("POST", "/api/admin/cancella_attivita", {"host_id": self.hid}, AK)
        self.assertEqual(s, 409)
        self.assertEqual(c.get("errore"), "obblighi_pendenti")
        # con forza: eseguito -> 200
        s, c = self.g("POST", "/api/admin/cancella_attivita",
                      {"host_id": self.hid, "forza": True}, AK)
        self.assertEqual(s, 200)
        self.assertTrue(c["ok"])
        # senza chiave admin -> 401
        self.assertEqual(self.g("POST", "/api/admin/cancella_attivita",
                                {"host_id": self.hid}, {})[0], 401)

    def test_idempotente(self):
        # il WIPE e' idempotente: eseguito due volte (forzato, perche' restano obblighi
        # finanziari che di proposito NON si cancellano) lascia 0 residui negli archivi
        # che gestisce. NB: il payout/escrow di una prenotazione forzata resta — va
        # saldato a mano, ed e' giusto che `obblighi_pendenti` continui a segnalarlo.
        cancella_attivita_host(self.sis, self.hid, forza=True)
        rep2 = cancella_attivita_host(self.sis, self.hid, forza=True)
        self.assertTrue(rep2["ok"])
        self.assertTrue(all(v == 0 for v in rep2["residui"].values()))


if __name__ == "__main__":
    unittest.main()
