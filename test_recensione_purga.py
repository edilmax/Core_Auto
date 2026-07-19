"""Collaudo ramo RECENSIONE POST-SOGGIORNO (2026-07-16, metodo libro) — 3 difetti:

(a) BUG PROVATO: la guardia anti-fake (`_recensione_ammessa`) reggeva sul record
    pendente, ma l'housekeeping PURGA i 'rimborsato' dopo ~26h -> da quel momento la
    guardia falliva-APERTA e una prenotazione CANCELLATA tornava recensibile
    "verificata" (5 stelle per un soggiorno mai avvenuto — stessa classe del bug
    credito #95: guardia che muore con la purga). Fix: segnale DUREVOLE dal flag
    `rimborsato` dei movimenti INVENTARIO (la purga dei pendenti non li tocca).
(b) CHIAVE SBAGLIATA: fase58 espone `rimborsato`, ma `_host_prenotazioni` leggeva
    `rilasciato` (sempre None) -> OGNI prenotazione appariva "Confermata" nel pannello,
    anche le rimborsate (host che prepara la casa per ospiti che non arriveranno).
(c) STESSA chiave sbagliata in `_host_alloggio_elimina` -> le prenotazioni GIA'
    rimborsate bloccavano per sempre l'eliminazione di un annuncio.
"""
import datetime
import json
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE


class TestRecensionePurga(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(
            lambda u, b, h: {"url": "https://x/cs", "id": "cs_1"})

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db",
            db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db", db_garanzia=f"{d}/g.db",
            db_recensioni=f"{d}/rec.db", commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_x", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@rp.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa-rp", "titolo": "Casa RP", "citta": "Roma",
                "prezzo_notte_cents": 10000, "capacita": 2}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa-rp", "da": oggi.isoformat(),
                "a": (oggi + datetime.timedelta(days=40)).isoformat(),
                "unita_totali": 1, "prezzo_netto_cents": 10000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None,
                               h or {})

    def _book_paga_cancella(self):
        oggi = datetime.date.today()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-rp",
                       "check_in": (oggi + datetime.timedelta(days=10)).isoformat(),
                       "check_out": (oggi + datetime.timedelta(days=12)).isoformat(),
                       "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@rp.it"})
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": b["riferimento"]}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})
        s, _ = self.g("POST", "/api/concierge/cancella",
                      {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200)
        return b

    def test_recensione_bloccata_anche_dopo_la_purga(self):
        b = self._book_paga_cancella()
        s, _ = self.g("POST", "/api/recensioni",
                      {"token": b["diritto_recensione"], "voto": 5, "testo": "mai stato"})
        self.assertEqual(s, 402)                       # guardia normale
        # +30h: l'housekeeping purga il record 'rimborsato'
        n = self.sis.pagamenti_pendenti.pulisci_vecchi(ora_ts=int(time.time()) + 30 * 3600)
        self.assertGreaterEqual(n, 1)
        self.assertIsNone(self.sis.pagamenti_pendenti.info(b["riferimento"]))
        s, o = self.g("POST", "/api/recensioni",
                      {"token": b["diritto_recensione"], "voto": 5, "testo": "mai stato"})
        self.assertEqual(s, 402, "PURGA = la guardia non deve fallire-aperta: %r" % (o,))
        _, rec = self.g("GET", "/api/recensioni/casa-rp")
        self.assertEqual(rec["riepilogo"]["conteggio"], 0)

    def test_recensione_pagata_resta_ammessa(self):
        oggi = datetime.date.today()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-rp",
                       "check_in": (oggi + datetime.timedelta(days=20)).isoformat(),
                       "check_out": (oggi + datetime.timedelta(days=22)).isoformat(),
                       "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@rp.it"})
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": b["riferimento"]}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})
        # NBF (2026-07-20): prima del check-out il diritto del book dice troppo_presto;
        # per il "pagata resta ammessa" si usa un diritto maturo (stessa firma di sistema)
        s, o = self.g("POST", "/api/recensioni",
                      {"token": b["diritto_recensione"], "voto": 4, "testo": "bello"})
        self.assertEqual(s, 400, o)
        self.assertEqual(o.get("motivo"), "troppo_presto")
        import time as _t
        from fase63_recensioni import EmettitoreDiritto
        maturo = EmettitoreDiritto(self.sis.firma).emetti(
            b["riferimento"], "casa", non_prima_ts=int(_t.time()) - 60)
        s, o = self.g("POST", "/api/recensioni", {"token": maturo, "voto": 4, "testo": "bello"})
        self.assertEqual(s, 201, o)
        self.assertTrue(o["verificata"])

    def test_pannello_host_marca_rimborsata(self):
        self._book_paga_cancella()
        # dal 2026-07-18 le annullate vivono nella vista ARCHIVIO (paginazione server):
        # la vista di default resta pulita, la rimborsata deve stare nell'archivio.
        s, pr = self.g("GET", "/api/host/prenotazioni", h={"X-Host-Token": self.tok},
                       q={"vista": "archivio"})
        self.assertEqual(s, 200)
        stati = [p["stato"] for p in pr["prenotazioni"]]
        self.assertIn("rimborsata", stati,
                      "chiave 'rimborsato': la cancellata deve apparire RIMBORSATA")
        s, pr = self.g("GET", "/api/host/prenotazioni", h={"X-Host-Token": self.tok})
        self.assertNotIn("rimborsata", [p["stato"] for p in pr["prenotazioni"]],
                         "la vista di default NON deve contenere le annullate")

    def test_elimina_annuncio_con_sole_rimborsate_future(self):
        self._book_paga_cancella()
        s, o = self.g("POST", "/api/host/alloggio_elimina", {"slug": "casa-rp"},
                      {"X-Host-Token": self.tok})
        self.assertEqual(s, 200, "le rimborsate non devono bloccare l'eliminazione: %r" % (o,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
