"""Test Fase 102 - Motore autonomo vendi+incassa. Componenti finti: nessuna rete."""
import unittest

from fase102_motore_autonomo import MotoreVendita, crea_motore_vendita


class Resp:
    def __init__(self, status, corpo):
        self.status = status
        self.corpo = corpo


class ConciergeOK:
    def quota(self, r):
        return Resp(200, {"quote_token": "tok.aaa.bbb", "prezzo_guest_cents": 11200,
                          "commissione_cents": 1500, "valuta": "usd"})

    def prenota(self, p):
        return Resp(200, {"confermata": True, "idem": p["quote_token"]})


class PayFinto:
    def crea_link(self, d):
        self.visto = d
        return "https://pay/x"


REQ = {"alloggio_id": "casa-1", "check_in": "2026-07-01", "check_out": "2026-07-02"}


class TestVendi(unittest.TestCase):
    def test_flusso_completo(self):
        pay = PayFinto()
        m = crea_motore_vendita(ConciergeOK(), pagamento=pay,
                                risolvi_account=lambda slug: "acct_" + slug)
        out = m.vendi(REQ, "a@b.com")
        self.assertTrue(out["ok"])
        self.assertEqual(out["prezzo_guest_cents"], 11200)
        self.assertEqual(out["payment_url"], "https://pay/x")
        self.assertEqual(pay.visto["host_account"], "acct_casa-1")
        self.assertEqual(pay.visto["commissione_cents"], 1500)
        self.assertTrue(out["prenotazione"]["confermata"])

    def test_quota_fallita(self):
        class C:
            def quota(self, r):
                return Resp(409, {"errore": "non_disponibile"})
        out = MotoreVendita(C()).vendi(REQ, "a@b.com")
        self.assertFalse(out["ok"])
        self.assertEqual(out["fase"], "quota")

    def test_prenota_fallita(self):
        class C(ConciergeOK):
            def prenota(self, p):
                return Resp(410, {"errore": "quote_scaduta"})
        out = MotoreVendita(C()).vendi(REQ, "a@b.com")
        self.assertFalse(out["ok"])
        self.assertEqual(out["fase"], "prenota")

    def test_senza_account_niente_link(self):
        out = MotoreVendita(ConciergeOK(), pagamento=PayFinto()).vendi(REQ, "a@b.com")
        self.assertTrue(out["ok"])
        self.assertIsNone(out["payment_url"])

    def test_split_gruppo(self):
        m = MotoreVendita(ConciergeOK(),
                          split_fn=lambda tot, parti: {"tot": tot, "n": len(parti)})
        out = m.vendi(REQ, "a@b.com", partecipanti=["x", "y", "z"])
        self.assertEqual(out["split_gruppo"], {"tot": 11200, "n": 3})

    def test_isolato_concierge_esplode(self):
        class C:
            def quota(self, r):
                raise RuntimeError("giu")
        out = MotoreVendita(C()).vendi(REQ, "a@b.com")
        self.assertFalse(out["ok"])
        self.assertEqual(out["fase"], "interno")


if __name__ == "__main__":
    unittest.main()
