"""Test Fase 59 host-aware: commissione_alloggio (netto, slug) ha priorita' sul flat."""
import unittest

from fase59_concierge import ProtocolloConcierge, FirmaQuote

SEG = b"k" * 32


class InvFinto:
    def disponibile(self, a, ci, co):
        return True

    def stato_giorno(self, a, g):
        return {"prezzo_netto_cents": 10000}


def proto(**kw):
    return ProtocolloConcierge(InvFinto(), FirmaQuote(SEG), **kw)


class TestHostAware(unittest.TestCase):
    REQ = {"alloggio_id": "casa-1", "check_in": "2026-07-01",
           "check_out": "2026-07-02", "party": 1}

    def test_priorita_su_flat(self):
        visti = {}
        p = proto(commissione=lambda n: 9999,
                  commissione_alloggio=lambda n, slug: visti.update(slug=slug) or n * 3 // 100)
        r = p.quota(self.REQ)
        self.assertEqual(r.corpo["commissione_cents"], 300)   # 3% host-aware, non 9999
        self.assertEqual(visti["slug"], "casa-1")

    def test_fallback_flat_se_assente(self):
        r = proto(commissione=lambda n: n * 15 // 100).quota(self.REQ)
        self.assertEqual(r.corpo["commissione_cents"], 1500)  # flat 15%

    def test_resolver_solleva_usa_flat(self):
        def boom(n, slug):
            raise RuntimeError("x")
        r = proto(commissione=lambda n: 1500, commissione_alloggio=boom).quota(self.REQ)
        self.assertEqual(r.corpo["commissione_cents"], 1500)  # isolato -> flat


if __name__ == "__main__":
    unittest.main()
