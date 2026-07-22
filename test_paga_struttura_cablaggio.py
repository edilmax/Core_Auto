"""
CABLAGGIO "Paga in Struttura" — FASE 1 (collaudo #2 di CLAUDE.md: anello per anello).

fase188 calcola i conti (testato a tavolino da test_paga_struttura). Qui si prova l'ALTRA meta':
che il pezzo sia DAVVERO COLLEGATO dal toggle dell'host fino a cio' che l'ospite vede nel
preventivo. Il modo di rompersi #2 ("cablaggio mancante — il pezzo e' perfetto e non e'
collegato", come la promo 0% mai applicata): fase188 poteva restare un modulo dormiente.

Si prova, sul router VERO (fase83), col flusso VERO (registra host -> pubblica -> quote):
  1. annuncio che ACCETTA (default ON)  -> il preventivo porta `paga_in_struttura.accettato=True`
     con anticipo+saldo COERENTI (== ricalcolo indipendente di fase188 sul totale del preventivo);
  2. annuncio che NON accetta (toggle OFF) -> `paga_in_struttura.accettato=False`, niente numeri;
  3. le INVARIANTI di soldi valgono anche qui end-to-end: anticipo+saldo == totale ospite ==
     totale_soggiorno + fee(1.50*notti); l'ospite in struttura paga un po' di piu' (la fee).

Visto ROSSO: se si toglie il cablaggio in fase83 `_concierge_quote`, il punto 1 fallisce
(chiave assente) -> non e' un ornamento.
"""
import json
import os
import shutil
import tempfile
import unittest

import fase188_paga_struttura as PS
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256


class TestPagaStrutturaCablaggio(unittest.TestCase):
    def setUp(self):
        # la vetrina ospite e' in DARK LAUNCH (spenta di default): qui la accendiamo per
        # provare il comportamento reale. tearDown ripristina il valore precedente.
        self._flag_prima = os.environ.get("PAGA_STRUTTURA_ATTIVO")
        os.environ["PAGA_STRUTTURA_ATTIVO"] = "1"
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db",
            commissione_bps=1000, psp_bps=0, stripe_secret_key="sk",
            stripe_webhook_secret="whsec_x", stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@ps.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.tok = c["token"]
        # annuncio A: ACCETTA paga in struttura (default, non lo passa nemmeno)
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa-si", "titolo": "Casa Si", "citta": "Roma",
                "prezzo_notte_cents": 30000, "capacita": 4,
                "politica_cancellazione": "flessibile"}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa-si", "da": "2026-09-01", "a": "2026-09-30",
                "unita_totali": 1, "prezzo_netto_cents": 30000}, {"X-Host-Token": self.tok})
        # annuncio B: NON accetta (toggle OFF esplicito)
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa-no", "titolo": "Casa No", "citta": "Roma",
                "prezzo_notte_cents": 30000, "capacita": 4, "paga_in_struttura": False,
                "politica_cancellazione": "flessibile"}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa-no", "da": "2026-09-01", "a": "2026-09-30",
                "unita_totali": 1, "prezzo_netto_cents": 30000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        if self._flag_prima is None:
            os.environ.pop("PAGA_STRUTTURA_ATTIVO", None)
        else:
            os.environ["PAGA_STRUTTURA_ATTIVO"] = self._flag_prima
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _quote(self, slug, ci="2026-09-05", co="2026-09-08"):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": slug, "check_in": ci, "check_out": co, "party": 2})
        self.assertEqual(s, 200, q)
        return q

    def test_annuncio_che_accetta_porta_lopzione_nel_preventivo(self):
        q = self._quote("casa-si")
        self.assertIn("paga_in_struttura", q, "CABLAGGIO ROTTO: opzione assente dal preventivo")
        ps = q["paga_in_struttura"]
        self.assertTrue(ps.get("accettato"), "annuncio che accetta ma opzione spenta: %s" % ps)
        # ricalcolo INDIPENDENTE (oracolo): fase188 sul totale VERO del preventivo
        atteso = PS.calcola(q["totale_cents"], q["notti"], q["commissione_cents"])
        for k in ("ospite_paga_totale_cents", "anticipo_online_cents",
                  "saldo_in_loco_cents", "fee_cents"):
            self.assertEqual(ps[k], atteso[k], "%s diverso dal ricalcolo fase188" % k)

    def test_annuncio_che_non_accetta_non_mostra_lopzione(self):
        q = self._quote("casa-no")
        ps = q.get("paga_in_struttura")
        self.assertIsNotNone(ps, "chiave sempre presente per un frontend prevedibile")
        self.assertFalse(ps.get("accettato"), "toggle OFF ma opzione ACCESA: %s" % ps)
        # niente numeri da mostrare quando non accetta
        self.assertNotIn("anticipo_online_cents", ps)

    def test_dark_launch_spento_di_default_nasconde_lopzione(self):
        # con PAGA_STRUTTURA_ATTIVO != 1 (default di produzione) l'ospite NON deve vedere
        # l'opzione, anche su un annuncio che la accetta: e' il dark launch della FASE 1.
        # Visto ROSSO togliendo il gate `attivo and ...` in fase83.
        os.environ["PAGA_STRUTTURA_ATTIVO"] = "0"
        q = self._quote("casa-si")
        ps = q.get("paga_in_struttura")
        self.assertIsNotNone(ps, "chiave sempre presente")
        self.assertFalse(ps.get("accettato"),
                         "DARK LAUNCH ROTTO: l'ospite vede l'opzione con la feature spenta: %s" % ps)
        self.assertNotIn("anticipo_online_cents", ps)

    def test_invarianti_soldi_end_to_end(self):
        q = self._quote("casa-si", "2026-09-10", "2026-09-13")   # 3 notti
        ps = q["paga_in_struttura"]
        notti = q["notti"]
        # l'ospite in struttura paga il totale + fee 1.50/notte
        self.assertEqual(ps["fee_cents"], 150 * notti)
        self.assertEqual(ps["ospite_paga_totale_cents"], q["totale_cents"] + 150 * notti)
        # conservazione: anticipo online + saldo in loco == totale ospite
        self.assertEqual(ps["anticipo_online_cents"] + ps["saldo_in_loco_cents"],
                         ps["ospite_paga_totale_cents"])
        # mai negativi
        for k in ("anticipo_online_cents", "saldo_in_loco_cents", "fee_cents"):
            self.assertGreaterEqual(ps[k], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
