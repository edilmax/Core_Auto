"""
Collaudo LOOP 3 — sconti soggiorni lunghi (l'host li offre, come Airbnb/Booking).
>=7 notti -> sconto settimana; >=28 -> sconto mese (prevale). Applicato sul netto ->
l'ospite paga meno, l'host riempie più notti; commissione sul netto scontato (mai in perdita).
Identità: prezzo_listino == prezzo_guest + sconto_non_rimborsabile + sconto_soggiorno_lungo.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase57_vetrina import SchedaAlloggio


class TestScontoLungo(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32,
            db_catalogo=f"{self.d}/c.db", db_inventario=f"{self.d}/i.db",
            commissione_bps=1000, psp_bps=300))
        self.r = crea_router(self.sys)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _pubblica(self, slug, **kw):
        self.sys.catalogo.pubblica(SchedaAlloggio(
            host_id="h1", slug=slug, titolo=slug, citta="Roma",
            prezzo_notte_cents=10000, capacita=4, **kw))
        import datetime
        d0 = datetime.date(2026, 9, 1)
        for i in range(40):
            g = (d0 + datetime.timedelta(days=i)).isoformat()
            self.sys.inventario.imposta_disponibilita(slug, g, unita_totali=1,
                                                      prezzo_netto_cents=10000)

    def _quota(self, slug, ci, co):
        s, q = self.r.gestisci("POST", "/api/concierge/quote", {}, json.dumps(
            {"alloggio_id": slug, "check_in": ci, "check_out": co, "party": 2}), {})
        self.assertEqual(s, 200, q)
        return q

    def _identita(self, q):
        self.assertEqual(
            q["prezzo_listino_cents"],
            q["prezzo_guest_cents"] + q["sconto_non_rimborsabile_cents"]
            + q["sconto_soggiorno_lungo_cents"],
            "identità listino violata")

    def test_settimana_applica_sotto_no(self):
        self._pubblica("casa-w", sconto_settimana_bps=1000)   # -10% da 7 notti
        # 3 notti -> NIENTE sconto
        q3 = self._quota("casa-w", "2026-09-01", "2026-09-04")
        self.assertEqual(q3["sconto_soggiorno_lungo_cents"], 0)
        self.assertEqual(q3["prezzo_listino_cents"], 30000)
        # 7 notti -> -10% su 70000 = 7000
        q7 = self._quota("casa-w", "2026-09-01", "2026-09-08")
        self.assertEqual(q7["prezzo_listino_cents"], 70000)
        self.assertEqual(q7["sconto_soggiorno_lungo_cents"], 7000)
        self.assertEqual(q7["prezzo_guest_cents"], 63000)     # paga meno
        self._identita(q7)
        # netto host e commissione sul netto SCONTATO (mai in perdita)
        self.assertEqual(q7["commissione_cents"], 6300)       # 10% di 63000
        self.assertEqual(q7["netto_host_cents"], 63000 - 6300 - q7["costo_pagamento_cents"])

    def test_mese_prevale_su_settimana(self):
        self._pubblica("casa-m", sconto_settimana_bps=1000, sconto_mese_bps=2500)
        # 28 notti -> mese -25% su 280000 = 70000
        q = self._quota("casa-m", "2026-09-01", "2026-09-29")
        self.assertEqual(q["notti"], 28)
        self.assertEqual(q["prezzo_listino_cents"], 280000)
        self.assertEqual(q["sconto_soggiorno_lungo_cents"], 70000)   # 25%, non 10%
        self.assertEqual(q["prezzo_guest_cents"], 210000)
        self._identita(q)

    def test_si_impila_con_non_rimborsabile(self):
        self._pubblica("casa-nr", sconto_settimana_bps=1000,
                       politica_cancellazione="non_rimborsabile")
        q = self._quota("casa-nr", "2026-09-01", "2026-09-08")   # 7 notti
        self.assertEqual(q["sconto_soggiorno_lungo_cents"], 7000)   # -10% su 70000
        # nr -12% sul netto GIÀ scontato (63000) = 7560
        self.assertEqual(q["sconto_non_rimborsabile_cents"], 63000 * 1200 // 10000)
        self._identita(q)

    def test_zero_default_invariato(self):
        self._pubblica("casa-0")                              # nessuno sconto
        q = self._quota("casa-0", "2026-09-01", "2026-09-10")   # 9 notti
        self.assertEqual(q["sconto_soggiorno_lungo_cents"], 0)
        self.assertEqual(q["prezzo_listino_cents"], q["prezzo_guest_cents"])

    def test_publish_edit_round_trip_endpoint(self):
        # via endpoint host: publish con % -> bps memorizzati; dettaglio_owner li ritorna
        from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE
        s, c = self.r.gestisci("POST", "/api/host/registrazione", {}, json.dumps(
            {"email": "h@sl.it", "password": "password1", "accetta_termini": True,
             "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
             "versione": CONTRATTO_HOST_VERSIONE}), {})
        self.assertEqual(s, 201, c)
        tok = c["token"]
        s, _ = self.r.gestisci("POST", "/api/host/pubblica", {}, json.dumps(
            {"slug": "casa-ep", "titolo": "EP", "citta": "Roma", "prezzo_notte_cents": 10000,
             "capacita": 2, "sconto_settimana_bps": 1500, "sconto_mese_bps": 3000}),
            {"X-Host-Token": tok})
        self.assertEqual(s, 201)
        d = self.sys.catalogo.dettaglio_owner("casa-ep")
        self.assertEqual(d["sconto_settimana_bps"], 1500)
        self.assertEqual(d["sconto_mese_bps"], 3000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
