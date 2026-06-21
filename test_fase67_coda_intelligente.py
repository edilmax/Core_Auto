"""
Test Fase 67 - Coda Intelligente + Cancellazione Garantita.

Copre: gate prob conservativo (offerta/fail-closed/min-campione), iscrizione FIFO +
idempotenza, rinuncia (deposito trattenuto), liberazione->offerta al primo, accetta
(entro timeout + delega isolata + fallita->riapre), scadenza offerta + passaggio al
next, prezzo esclusivo (sconto+tetto), conversione voucher, stato coda, robustezza,
stress concorrente. Orologio iniettato per determinismo.
"""
import os
import shutil
import tempfile
import threading
import unittest

from fase67_coda_intelligente import (
    EsitoAccetta, GestoreCoda, PoliticaCoda, crea_gestore_coda,
)

CI, CO = "2026-08-15", "2026-08-17"


def _con_storia(g, alloggio, liberati, non_liberati):
    for _ in range(liberati):
        g.registra_liberazione(alloggio, True)
    for _ in range(non_liberati):
        g.registra_liberazione(alloggio, False)


class TestGateProbabilita(unittest.TestCase):
    def test_offerta_se_prob_alta(self):
        g = crea_gestore_coda(politica=PoliticaCoda(min_campione=10, prior_k=0,
                                                    soglia_bps=2000))
        _con_storia(g, "casa", 30, 70)        # 30%
        v = g.valuta_iscrizione("casa")
        self.assertTrue(v["disponibile"])
        self.assertEqual(v["deposito_cents"], 2000)
        self.assertEqual(v["voucher_cents"], 2500)

    def test_fail_closed_prob_bassa(self):
        g = crea_gestore_coda(politica=PoliticaCoda(min_campione=10, prior_k=0,
                                                    soglia_bps=2000))
        _con_storia(g, "casa", 3, 97)         # 3%
        self.assertFalse(g.valuta_iscrizione("casa")["disponibile"])

    def test_fail_closed_pochi_dati(self):
        g = crea_gestore_coda(politica=PoliticaCoda(min_campione=20))
        _con_storia(g, "casa", 5, 0)
        self.assertFalse(g.valuta_iscrizione("casa")["disponibile"])


class TestIscrizione(unittest.TestCase):
    def setUp(self):
        self.g = crea_gestore_coda()

    def test_fifo(self):
        self.assertEqual(self.g.iscrivi("casa", CI, CO, "a").posizione, 1)
        self.assertEqual(self.g.iscrivi("casa", CI, CO, "b").posizione, 2)
        self.assertEqual(self.g.iscrivi("casa", CI, CO, "c").posizione, 3)

    def test_idempotente(self):
        self.g.iscrivi("casa", CI, CO, "a")
        e = self.g.iscrivi("casa", CI, CO, "a")
        self.assertTrue(e.idempotente)
        self.assertEqual(e.posizione, 1)
        self.assertEqual(len(self.g.stato_coda("casa", CI, CO)), 1)

    def test_date_invalide(self):
        self.assertFalse(self.g.iscrivi("casa", CO, CI, "a").ok)


class TestRinuncia(unittest.TestCase):
    def test_deposito_trattenuto(self):
        g = crea_gestore_coda()
        g.iscrivi("casa", CI, CO, "a")
        r = g.rinuncia("casa", CI, CO, "a")
        self.assertTrue(r["ok"])
        self.assertEqual(r["deposito_trattenuto_cents"], 2000)
        # rimossa dagli attivi -> il successivo e' posizione 1
        self.assertEqual(g.iscrivi("casa", CI, CO, "b").posizione, 1)

    def test_rinuncia_inesistente(self):
        g = crea_gestore_coda()
        self.assertFalse(g.rinuncia("casa", CI, CO, "x")["ok"])


class TestLiberazioneAccetta(unittest.TestCase):
    def setUp(self):
        self.clock = [1000]
        self.g = crea_gestore_coda(politica=PoliticaCoda(timeout_offerta_sec=7200),
                                   orologio=lambda: self.clock[0])
        for o in ("a", "b", "c"):
            self.g.iscrivi("casa", CI, CO, o)

    def test_offerta_al_primo(self):
        e = self.g.libera("casa", CI, CO)
        self.assertEqual((e.esito, e.ospite_id), ("offerto", "a"))

    def test_doppia_libera_non_riprende(self):
        self.g.libera("casa", CI, CO)
        e = self.g.libera("casa", CI, CO)
        self.assertEqual((e.esito, e.ospite_id), ("gia_offerto", "a"))

    def test_accetta_entro_timeout(self):
        self.g.libera("casa", CI, CO)
        self.clock[0] = 1000 + 3600           # 1h dopo, entro 2h
        e = self.g.accetta("casa", CI, CO, "a")
        self.assertTrue(e.ok)

    def test_accetta_idempotente(self):
        self.g.libera("casa", CI, CO)
        self.g.accetta("casa", CI, CO, "a")
        self.assertTrue(self.g.accetta("casa", CI, CO, "a").idempotente)

    def test_accetta_chi_non_e_offerto(self):
        self.g.libera("casa", CI, CO)
        e = self.g.accetta("casa", CI, CO, "b")   # offerto e' 'a'
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "offerta_non_attiva")

    def test_accetta_scaduta(self):
        self.g.libera("casa", CI, CO)
        self.clock[0] = 1000 + 8000           # oltre 2h
        e = self.g.accetta("casa", CI, CO, "a")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "offerta_scaduta")

    def test_scadenza_poi_passa_al_secondo(self):
        self.g.libera("casa", CI, CO)         # offerto 'a'
        self.clock[0] = 1000 + 8000
        self.assertEqual(self.g.scadi_offerte("casa", CI, CO), 1)
        e = self.g.libera("casa", CI, CO)     # ora offre 'b'
        self.assertEqual((e.esito, e.ospite_id), ("offerto", "b"))

    def test_prenota_delegata_fallisce_riapre(self):
        self.g.libera("casa", CI, CO)
        e = self.g.accetta("casa", CI, CO, "a", prenota=lambda *a: False)
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "prenotazione_fallita")
        # offerta riaperta: 'a' e' ancora l'offerto
        self.assertEqual(self.g.libera("casa", CI, CO).ospite_id, "a")

    def test_prenota_delegata_solleva_isolata(self):
        self.g.libera("casa", CI, CO)
        def boom(*a):
            raise RuntimeError("booking giu'")
        e = self.g.accetta("casa", CI, CO, "a", prenota=boom)
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "prenotazione_errore")


class TestPrezzoVoucher(unittest.TestCase):
    def test_prezzo_esclusivo_con_tetto(self):
        g = crea_gestore_coda(politica=PoliticaCoda(sconto_esclusivo_bps=1500,
                                                    tetto_sconto_cents=1500))
        # 10000 * 15% = 1500, sotto il tetto -> 8500
        self.assertEqual(g.prezzo_esclusivo(10000), 8500)
        # 20000 * 15% = 3000, ma tetto 1500 -> 18500
        self.assertEqual(g.prezzo_esclusivo(20000), 18500)

    def test_prezzo_invalido(self):
        g = crea_gestore_coda()
        self.assertEqual(g.prezzo_esclusivo(0), 0)
        self.assertEqual(g.prezzo_esclusivo(10.0), 0)

    def test_converti_voucher(self):
        g = crea_gestore_coda()
        g.iscrivi("casa", CI, CO, "a")
        r = g.converti_voucher("casa", CI, CO, "a")
        self.assertTrue(r["ok"])
        self.assertEqual(r["voucher_cents"], 2500)
        # confermato non convertibile
        self.assertFalse(g.converti_voucher("casa", CI, CO, "a")["ok"])


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        g = crea_gestore_coda()
        for bad in (None, 123, ""):
            try:
                g.iscrivi(bad, bad, bad, bad)
                g.libera(bad, bad, bad)
                g.accetta(bad, bad, bad, bad)
                g.rinuncia(bad, bad, bad, bad)
                g.prob_liberazione_bps(bad)
                g.prezzo_esclusivo(bad)
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")


class TestStress(unittest.TestCase):
    def test_iscrizioni_concorrenti_10x(self):
        for rip in range(10):
            d = tempfile.mkdtemp()
            try:
                g = crea_gestore_coda(os.path.join(d, f"c{rip}.db"))
                ospiti = ["u%d" % i for i in range(20)]
                errori = []
                lock = threading.Lock()

                def iscr(o):
                    try:
                        e = g.iscrivi("casa", CI, CO, o)
                        with lock:
                            errori.append(e.ok)
                    except Exception as ex:  # pragma: no cover
                        with lock:
                            errori.append(ex)

                th = [threading.Thread(target=iscr, args=(o,)) for o in ospiti]
                for t in th:
                    t.start()
                for t in th:
                    t.join()
                self.assertTrue(all(x is True for x in errori))
                stato = g.stato_coda("casa", CI, CO)
                self.assertEqual(len(stato), 20)
                # posizioni uniche 1..20
                pos = sorted(g.posizione("casa", CI, CO, o) for o in ospiti)
                self.assertEqual(pos, list(range(1, 21)))
            finally:
                shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
