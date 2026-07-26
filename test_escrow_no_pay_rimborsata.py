"""GUARDIA — l'auto-rilascio dell'escrow NON deve pagare l'host se la prenotazione e' RIMBORSATA.

Difetto trovato dalla caccia profonda agli stati impossibili (collaudi/stati_impossibili.py):
`auto_rilascia` versa all'host ogni garanzia 'in_garanzia' a finestra scaduta, controllando le
CONTESTAZIONI ma NON lo stato di rimborso. Se il passo che chiude l'escrow durante un rimborso
salta in isolamento (crash), al rilascio l'host verrebbe pagato per una prenotazione gia'
rimborsata = PERDITA secca (soldi versati due volte: rimborso all'ospite + bonifico all'host).
Il guardiano fase186 lo VEDE, ma solo a posteriori; questa e' la PREVENZIONE al momento esatto
del rilascio (`salta_se`): la prenotazione rimborsata viene chiusa 'annullato', host 0.

Vista ROSSA: senza `salta_se` (comportamento vecchio) la prenotazione rimborsata finisce nella
lista dei bonifici -> host pagato. Fail-safe: in dubbio si RILASCIA (l'host legittimo non resta
mai non pagato per una lettura fallita).
"""
import shutil
import tempfile
import unittest

from fase160_escrow_garanzia import crea_escrow_garanzia


class TestEscrowNonPagaSuRimborsata(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.esc = crea_escrow_garanzia(self.d + "/g.db")
        self.esc.inizializza_schema()
        # due garanzie con finestra GIA' scaduta (rilascio nel passato)
        self.esc.apri("rif_rimb", 50000, alloggio_id="x", ora_checkin_ts=1000, finestra_ore=1)
        self.esc.apri("rif_ok", 40000, alloggio_id="y", ora_checkin_ts=1000, finestra_ore=1)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_rimborsata_non_pagata_legittima_pagata(self):
        # rif_rimb e' "rimborsata"; rif_ok no. Rilascio con l'ora molto avanti (finestra scaduta).
        rilasciati = self.esc.auto_rilascia(
            ora_ts=10_000_000, dettagli=True,
            salta_se=lambda rif: rif == "rif_rimb")
        pagati = {r["prenotazione_id"] for r in rilasciati}
        # la rimborsata NON e' pagata all'host...
        self.assertNotIn("rif_rimb", pagati, "PERDITA: host pagato su prenotazione rimborsata")
        st = self.esc.stato("rif_rimb")
        self.assertEqual(st["stato"], "annullato", "l'escrow rimborsato va CHIUSO, non lasciato aperto")
        self.assertEqual(st["host_riceve_cents"], 0, "host non deve ricevere nulla sulla rimborsata")
        # ...la legittima SI'
        self.assertIn("rif_ok", pagati, "l'host legittimo DEVE essere pagato")
        self.assertEqual(self.esc.stato("rif_ok")["stato"], "rilasciato")

    def test_vista_rossa_senza_filtro_la_rimborsata_verrebbe_pagata(self):
        # senza salta_se (comportamento VECCHIO) la rimborsata finirebbe nei bonifici -> la perdita
        rilasciati = self.esc.auto_rilascia(ora_ts=10_000_000, dettagli=True)
        pagati = {r["prenotazione_id"] for r in rilasciati}
        self.assertIn("rif_rimb", pagati,
                      "il test di rimozione conferma che il filtro e' cio' che previene la perdita")

    def test_fail_safe_predicato_che_esplode_rilascia(self):
        # se il predicato solleva, NON si deve bloccare il pagamento dell'host legittimo
        def _boom(_rif):
            raise RuntimeError("lettura pendenti giu'")
        rilasciati = self.esc.auto_rilascia(ora_ts=10_000_000, dettagli=True, salta_se=_boom)
        pagati = {r["prenotazione_id"] for r in rilasciati}
        self.assertIn("rif_ok", pagati, "fail-safe: in errore si rilascia (host non penalizzato)")
        self.assertIn("rif_rimb", pagati, "fail-safe: predicato rotto -> nessuno viene saltato")


if __name__ == "__main__":
    unittest.main(verbosity=2)
