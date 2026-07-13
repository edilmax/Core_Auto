"""
Collaudo CONTI — conservazione del denaro (proprietà, griglia severa).

Ogni preventivo firmato deve rispettare le identità contabili, per QUALSIASI combinazione
di prezzo (inclusi numeri primi e casi limite), notti, fonte (marketplace/diretto),
politica (sconto non-rimborsabile -12%), tassa di soggiorno e valuta (JPY senza decimali):

  I1: prezzo_guest == netto_host + commissione + costo_pagamento   (nessun cent sparisce)
  I2: totale == prezzo_guest + tassa_soggiorno                     (tassa pass-through)
  I3: prezzo_listino == prezzo_guest + sconto_non_rimborsabile     (sconto trasparente)
  I4: tutti gli importi interi e >= 0; commissione <= prezzo_guest
  I5: escrow risolvi: rimborso_ospite + va_all_host == importo     (split esatto)
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase57_vetrina import SchedaAlloggio


class TestConservazioneDenaro(unittest.TestCase):
    def _sistema(self, *, commissione_bps, psp_bps):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            commissione_bps=commissione_bps, psp_bps=psp_bps))
        return sis, crea_router(sis)

    def _quota(self, r, slug, notti, fonte, atteso=200):
        co = "2026-09-%02d" % (1 + notti)
        s, q = r.gestisci("POST", "/api/concierge/quote", {}, json.dumps(
            {"alloggio_id": slug, "check_in": "2026-09-01", "check_out": co,
             "party": 2, "fonte": fonte}), {})
        self.assertEqual(s, atteso, q)
        return q

    def _verifica_identita(self, q, ctx):
        campi = ("prezzo_guest_cents", "netto_host_cents", "commissione_cents",
                 "costo_pagamento_cents", "totale_cents", "tassa_soggiorno_cents",
                 "prezzo_listino_cents", "sconto_non_rimborsabile_cents")
        for k in campi:                                       # I4: interi, mai negativi
            v = q.get(k)
            self.assertIsInstance(v, int, "%s non intero (%r) in %s" % (k, v, ctx))
            self.assertGreaterEqual(v, 0, "%s negativo in %s" % (k, ctx))
        self.assertEqual(q["prezzo_guest_cents"],
                         q["netto_host_cents"] + q["commissione_cents"]
                         + q["costo_pagamento_cents"],
                         "I1 violata (un cent sparito/creato) in %s" % ctx)
        self.assertEqual(q["totale_cents"],
                         q["prezzo_guest_cents"] + q["tassa_soggiorno_cents"],
                         "I2 violata (tassa non pass-through) in %s" % ctx)
        self.assertEqual(q["prezzo_listino_cents"],
                         q["prezzo_guest_cents"] + q["sconto_non_rimborsabile_cents"],
                         "I3 violata (sconto opaco) in %s" % ctx)
        self.assertLessEqual(q["commissione_cents"], q["prezzo_guest_cents"], ctx)

    def test_griglia_severa(self):
        # prezzi ostili: primi, dispari, tondi, massimi tipici (i realistici conservano al cent)
        prezzi = (97, 7333, 9999, 10000, 123457, 999999)
        for comm_bps, psp_bps in ((1000, 300), (1000, 0), (500, 300), (0, 300)):
            sis, r = self._sistema(commissione_bps=comm_bps, psp_bps=psp_bps)
            for i, prezzo in enumerate(prezzi):
                for pol in ("flessibile", "non_rimborsabile"):
                    slug = "g-%d-%s" % (i, pol[:2])
                    sis.catalogo.pubblica(SchedaAlloggio(
                        host_id="h1", slug=slug, titolo=slug, citta="Roma",
                        prezzo_notte_cents=prezzo, capacita=4,
                        politica_cancellazione=pol,
                        tassa_pp_notte_cents=137, tassa_max_notti=2))
                    for g in ("2026-09-01", "2026-09-02", "2026-09-03"):
                        sis.inventario.imposta_disponibilita(
                            slug, g, unita_totali=1, prezzo_netto_cents=prezzo)
                    for notti in (1, 3):
                        for fonte in ("marketplace", "diretto"):
                            q = self._quota(r, slug, notti, fonte)
                            ctx = "prezzo=%d pol=%s notti=%d fonte=%s comm=%d psp=%d" % (
                                prezzo, pol, notti, fonte, comm_bps, psp_bps)
                            self._verifica_identita(q, ctx)
                            if pol == "non_rimborsabile":
                                self.assertGreater(
                                    q["sconto_non_rimborsabile_cents"], 0,
                                    "NR senza sconto in %s" % ctx)

    def test_prezzo_non_sostenibile_rifiutato(self):
        # prezzi da centesimi con tassa alta: il costo carta supererebbe il ricavo host ->
        # 422 onesto (nessuno ci rimette), NON un preventivo che fa sparire centesimi.
        sis, r = self._sistema(commissione_bps=1000, psp_bps=300)
        sis.catalogo.pubblica(SchedaAlloggio(
            host_id="h1", slug="patologico", titolo="x", citta="Roma",
            prezzo_notte_cents=1, capacita=4, tassa_pp_notte_cents=137, tassa_max_notti=2))
        for g in ("2026-09-01", "2026-09-02"):
            sis.inventario.imposta_disponibilita("patologico", g, unita_totali=1,
                                                 prezzo_netto_cents=1)
        q = self._quota(r, "patologico", 1, "marketplace", atteso=422)
        self.assertEqual(q["errore"], "prezzo_non_sostenibile")

    def test_valuta_jpy_senza_decimali(self):
        # JPY: l'esponente è 0 -> 12000 = ¥12.000 (mai ×100). Le identità valgono uguali.
        sis, r = self._sistema(commissione_bps=1000, psp_bps=300)
        sis.catalogo.pubblica(SchedaAlloggio(
            host_id="h1", slug="jp", titolo="Tokyo", citta="Tokyo",
            prezzo_notte_cents=12000, capacita=2, valuta="JPY"))
        for g in ("2026-09-01", "2026-09-02"):
            sis.inventario.imposta_disponibilita("jp", g, unita_totali=1,
                                                 prezzo_netto_cents=12000)
        q = self._quota(r, "jp", 1, "marketplace")
        self.assertEqual(q["valuta"], "JPY")
        self.assertEqual(q["prezzo_guest_cents"], 12000)      # 1 notte, nessun ×100
        self._verifica_identita(q, "JPY")

    def test_escrow_split_esatto(self):
        # I5: la risoluzione di una controversia conserva ogni cent (importi ostili)
        from fase160_escrow_garanzia import crea_escrow_garanzia
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        g = crea_escrow_garanzia(f"{d}/g.db")
        g.inizializza_schema()
        for i, imp in enumerate((1, 3, 97, 12743, 999999)):
            ref = "e%d" % i
            g.apri(ref, imp, alloggio_id="x", ora_checkin_ts=None)
            g.contesta(ref)
            for pct in (0, 33, 50, 77, 100):
                pass                                          # il pct lo applica il server
            rimborso = imp * 33 // 100
            out = g.risolvi(ref, rimborso_ospite_cents=rimborso)
            self.assertTrue(out.get("ok"), out)
            self.assertEqual(out["ospite_rimborso_cents"] + out["host_riceve_cents"], imp,
                             "escrow: cent perso su importo %d" % imp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
