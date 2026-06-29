"""Test ESCROW DI GARANZIA (fase160): i soldi all'host solo se l'ospite conferma o passa la
finestra; contestazione blocca; risoluzione a conservazione esatta. + E2E book->garanzia->conferma."""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase160_escrow_garanzia import crea_escrow_garanzia

SEG = b"g" * 32
HK = {"X-Host-Key": "hk"}
AK = {"X-Admin-Key": "ak"}


class TestModulo(unittest.TestCase):
    def setUp(self):
        self.clock = {"t": 1000}
        self.g = crea_escrow_garanzia(":memory:", orologio=lambda: self.clock["t"])
        self.g.inizializza_schema()

    def test_conferma_rilascia_tutto_allhost(self):
        self.assertTrue(self.g.apri("P1", 8500, ora_checkin_ts=1000))
        out = self.g.conferma_ospite("P1")
        self.assertTrue(out["ok"]); self.assertEqual(out["stato"], "rilasciato")
        self.assertEqual(out["host_riceve_cents"], 8500)
        self.assertEqual(self.g.stato("P1")["host_riceve_cents"], 8500)

    def test_apri_idempotente_e_importo_zero(self):
        self.assertTrue(self.g.apri("P2", 5000, ora_checkin_ts=1000))
        self.assertTrue(self.g.apri("P2", 9999, ora_checkin_ts=1000))   # idempotente
        self.assertEqual(self.g.stato("P2")["importo_host_cents"], 5000)
        self.assertFalse(self.g.apri("P3", 0))                          # importo nullo -> no

    def test_contesta_blocca_e_risolvi_conserva(self):
        self.g.apri("P4", 10000, ora_checkin_ts=1000)
        self.assertEqual(self.g.contesta("P4", "manca il wifi dichiarato")["stato"], "contestato")
        # auto-rilascio NON tocca una contestata anche se la finestra e' passata
        self.clock["t"] = 10**9
        self.assertEqual(self.g.auto_rilascia(), 0)
        r = self.g.risolvi("P4", rimborso_ospite_cents=4000)
        self.assertTrue(r["ok"])
        st = self.g.stato("P4")
        self.assertEqual(st["ospite_rimborso_cents"], 4000)
        self.assertEqual(st["host_riceve_cents"], 6000)
        self.assertEqual(st["host_riceve_cents"] + st["ospite_rimborso_cents"], 10000)  # conservazione

    def test_auto_rilascio_dopo_finestra(self):
        self.g.apri("P5", 7000, ora_checkin_ts=1000, finestra_ore=24)
        self.clock["t"] = 1000 + 25 * 3600
        self.assertEqual(self.g.auto_rilascia(), 1)
        self.assertEqual(self.g.stato("P5")["stato"], "rilasciato")

    def test_conferma_solo_da_in_garanzia(self):
        self.g.apri("P6", 5000, ora_checkin_ts=1000)
        self.g.conferma_ospite("P6")
        self.assertFalse(self.g.conferma_ospite("P6")["ok"])           # gia' rilasciata

    def test_annulla_blocca_auto_rilascio(self):
        # prenotazione cancellata -> garanzia annullata -> MAI payout all'host (no auto-rilascio)
        self.g.apri("P7", 5000, ora_checkin_ts=1000)
        self.assertEqual(self.g.annulla("P7")["stato"], "annullato")
        self.clock["t"] = 10 ** 9
        self.assertEqual(self.g.auto_rilascia(), 0)


class TestE2E(unittest.TestCase):
    def test_book_apre_garanzia_e_ospite_conferma(self):
        d = tempfile.mkdtemp(); self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db",
            db_domanda=f"{d}/dom.db", db_garanzia=f"{d}/g.db", file_referral=f"{d}/ref.json",
            commissione_bps=1500))
        r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")
        def g(m, p, b=None, h=None, q=None):
            return r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})
        g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "casa", "titolo": "Casa",
          "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
          "servizi": [], "immagini": []}, HK)
        g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa", "da": "2026-11-01",
          "a": "2026-11-30", "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)
        _, q = g("POST", "/api/concierge/quote", {"alloggio_id": "casa", "check_in": "2026-11-10",
                 "check_out": "2026-11-12", "party": 1})
        _, b = g("POST", "/api/concierge/book", {"quote_token": q["quote_token"], "email": "o@x.it"})
        ref = b["riferimento"]
        # garanzia aperta col netto host (20000 - 15% = 17000)
        s, st = g("GET", "/api/garanzia/stato", q={"ref": ref}, h=AK)
        self.assertEqual(s, 200)
        self.assertEqual(st["stato"], "in_garanzia")
        self.assertEqual(st["importo_host_cents"], 17000)
        # l'ospite conferma "tutto ok" col voucher -> rilasciato all'host
        s, c = g("POST", "/api/garanzia/conferma", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200); self.assertEqual(c["stato"], "rilasciato")
        # contestazione su una gia' rilasciata -> rifiutata
        s2, _ = g("POST", "/api/garanzia/contesta", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s2, 409)


if __name__ == "__main__":
    unittest.main()
