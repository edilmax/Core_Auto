"""Test politica di cancellazione scelta dall'HOST per alloggio (modello Booking) + sicurezza:
la politica è BLOCCATA nel voucher firmato, la cancellazione la usa (NON quella passata
dall'ospite furbo) + Credito Viaggio anti-rimpianto sulla penale."""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

SEG = b"p" * 32
HK = {"X-Host-Key": "hk"}


class TestPoliticaCancellazione(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db",
            db_messaggi=f"{d}/m.db", db_domanda=f"{d}/dom.db", file_referral=f"{d}/ref.json",
            commissione_bps=1500))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, body=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {},
                               json.dumps(body) if body is not None else None, h or {})

    def _pubblica(self, politica):
        self.g("POST", "/api/host/pubblica", {
            "host_id": "demo", "slug": "casa", "titolo": "Casa", "citta": "Roma",
            "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
            "servizi": [], "immagini": [], "politica_cancellazione": politica}, HK)
        self.g("POST", "/api/host/disponibilita_range", {
            "alloggio_id": "casa", "da": "2026-07-01", "a": "2026-07-31",
            "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)

    def test_host_sceglie_e_ospite_la_vede(self):
        self._pubblica("rigida")
        _, c = self.g("GET", "/api/catalogo/casa")
        self.assertEqual(c["politica_cancellazione"], "rigida")
        self.assertEqual(self.sis.catalogo.politica_cancellazione_di("casa"), "rigida")

    def test_politica_invalida_default_flessibile(self):
        self._pubblica("inventata_xyz")
        self.assertEqual(self.sis.catalogo.politica_cancellazione_di("casa"), "flessibile")

    def test_ANTIFURBATA_ospite_non_puo_scegliersi_la_politica(self):
        self._pubblica("rigida")                                  # host: RIGIDA
        _, q = self.g("POST", "/api/concierge/quote", {
            "alloggio_id": "casa", "check_in": "2026-07-08", "check_out": "2026-07-10",
            "party": 1})                                          # ~9 giorni all'arrivo
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "o@x.it"})
        # l'ospite prova a barare passando 'flessibile' nella richiesta di cancellazione
        _, c = self.g("POST", "/api/concierge/cancella",
                      {"voucher_token": b["voucher_token"], "politica": "flessibile"})
        self.assertEqual(c["politica"], "rigida")                 # ha VINTO quella dell'host
        self.assertEqual(c["rimborso_cents"], 10000)              # 50% (rigida a 9gg), non 100%
        self.assertEqual(c["trattenuto_cents"], 10000)

    def test_credito_viaggio_anti_rimpianto_sulla_penale(self):
        self._pubblica("rigida")
        _, q = self.g("POST", "/api/concierge/quote", {
            "alloggio_id": "casa", "check_in": "2026-07-08", "check_out": "2026-07-10",
            "party": 1})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "o@x.it"})
        _, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(c["credito_viaggio_cents"], 5000)        # 50% di 10000 trattenuti
        self.assertTrue(c["credito_viaggio_token"])               # token firmato, riscattabile


if __name__ == "__main__":
    unittest.main()
