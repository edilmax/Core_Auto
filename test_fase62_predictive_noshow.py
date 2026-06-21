"""
Test Fase 62 - Predictive No-Show + Overbooking controllato.

Copre: store presenze (record idempotente atomico + conteggi), stima CONSERVATIVA
(fail-closed sotto min-campione, smoothing verso 0, monotonia con l'evidenza, tetto),
consiglio posti virtuali (cap rispettato, 0 su dati sottili), applicazione ISOLATA a
fase58, piano di compensazione (esuberi, voucher in centesimi dal CORE, fail-closed),
robustezza (mai solleva), e stress concorrente 10x sui conteggi.
"""
import os
import shutil
import tempfile
import threading
import unittest

from fase58_channel_manager import crea_channel_manager
from fase62_predictive_noshow import (
    CompensazioneVoce, GestoreNoShow, PoliticaNoShow, StoricoPresenze,
    crea_gestore_noshow, crea_storico_presenze, segmento_da_data,
)


def _popola(st, alloggio, seg, presentati, no_show):
    for _ in range(presentati):
        st.registra_esito(alloggio, seg, "presentato")
    for _ in range(no_show):
        st.registra_esito(alloggio, seg, "no_show")


class TestStorico(unittest.TestCase):
    def setUp(self):
        self.st = crea_storico_presenze()

    def test_record_e_conteggi(self):
        _popola(self.st, "a", "ven", 8, 2)
        c = self.st.conteggi("a", "ven")
        self.assertEqual((c["presentati"], c["no_show"], c["totale"]), (8, 2, 10))

    def test_esito_invalido_rifiutato(self):
        self.assertFalse(self.st.registra_esito("a", "ven", "boh"))
        self.assertFalse(self.st.registra_esito("", "ven", "presentato"))

    def test_conteggi_vuoti(self):
        c = self.st.conteggi("mai", "visto")
        self.assertEqual(c["totale"], 0)

    def test_segmento_da_data(self):
        self.assertTrue(segmento_da_data("2026-07-03").startswith("dow_"))
        self.assertEqual(segmento_da_data("non-data"), "na")


class TestStimaConservativa(unittest.TestCase):
    def test_sotto_min_campione_zero(self):
        g = crea_gestore_noshow(politica=PoliticaNoShow(min_campione=20))
        _popola(g._st, "a", "ven", 0, 1)   # 1/1 no-show ma campione = 1
        self.assertEqual(g.tasso_noshow_bps("a", "ven"), 0)   # fail-closed

    def test_non_stima_100_su_dati_sottili(self):
        # campione appena sopra il min: lo smoothing tiene il tasso lontano da 10000
        g = crea_gestore_noshow(politica=PoliticaNoShow(min_campione=5, prior_k=20))
        _popola(g._st, "a", "ven", 0, 5)   # 5/5 no-show
        bps = g.tasso_noshow_bps("a", "ven")
        self.assertGreater(bps, 0)
        self.assertLess(bps, 3000)          # 5*10000//25 = 2000, NON 10000

    def test_monotonia_con_evidenza(self):
        g = crea_gestore_noshow(politica=PoliticaNoShow(min_campione=10, prior_k=20))
        _popola(g._st, "a", "ven", 80, 20)  # 20%
        basso = g.tasso_noshow_bps("a", "ven")
        g2 = crea_gestore_noshow(politica=PoliticaNoShow(min_campione=10, prior_k=20))
        _popola(g2._st, "a", "ven", 60, 40)  # 40%
        alto = g2.tasso_noshow_bps("a", "ven")
        self.assertGreater(alto, basso)

    def test_tasso_intero(self):
        g = crea_gestore_noshow(politica=PoliticaNoShow(min_campione=10, prior_k=0))
        _popola(g._st, "a", "ven", 90, 10)
        self.assertIsInstance(g.tasso_noshow_bps("a", "ven"), int)


class TestConsiglioOverbooking(unittest.TestCase):
    def test_posti_virtuali_con_tetto(self):
        g = crea_gestore_noshow(politica=PoliticaNoShow(
            min_campione=10, prior_k=0, safety_bps=10000, max_overbooking_bps=2000))
        _popola(g._st, "a", "ven", 70, 30)   # 30% no-show
        # capacita 10, attesi=3, safety 100% -> 3, ma tetto 20% di 10 = 2 -> min=2
        self.assertEqual(g.consiglia_posti_virtuali(10, "a", "ven"), 2)

    def test_safety_factor_riduce(self):
        g = crea_gestore_noshow(politica=PoliticaNoShow(
            min_campione=10, prior_k=0, safety_bps=5000, max_overbooking_bps=10000))
        _popola(g._st, "a", "ven", 60, 40)   # 40%
        # capacita 10, attesi=4, safety 50% -> 2
        self.assertEqual(g.consiglia_posti_virtuali(10, "a", "ven"), 2)

    def test_dati_sottili_zero(self):
        g = crea_gestore_noshow(politica=PoliticaNoShow(min_campione=20))
        _popola(g._st, "a", "ven", 1, 1)
        self.assertEqual(g.consiglia_posti_virtuali(10, "a", "ven"), 0)

    def test_capacita_invalida_zero(self):
        g = crea_gestore_noshow()
        self.assertEqual(g.consiglia_posti_virtuali(0, "a", "ven"), 0)
        self.assertEqual(g.consiglia_posti_virtuali(-5, "a", "ven"), 0)
        self.assertEqual(g.consiglia_posti_virtuali(10.0, "a", "ven"), 0)


class TestApplicaInventario(unittest.TestCase):
    def test_apre_posti_virtuali_su_fase58(self):
        g = crea_gestore_noshow(politica=PoliticaNoShow(
            min_campione=10, prior_k=0, safety_bps=10000, max_overbooking_bps=5000))
        _popola(g._st, "casa", segmento_da_data("2026-07-03"), 70, 30)  # 30%
        inv = crea_channel_manager()
        virt = g.applica_a_inventario(inv, "casa", "2026-07-03",
                                      capacita_reale=10, prezzo_netto_cents=10000)
        stato = inv.stato_giorno("casa", "2026-07-03")
        self.assertEqual(stato["unita_totali"], 10 + virt)
        self.assertGreater(virt, 0)

    def test_inventario_che_solleva_isolato(self):
        class InvRotto:
            def imposta_disponibilita(self, *a, **k):
                raise RuntimeError("db giu'")
        g = crea_gestore_noshow(politica=PoliticaNoShow(
            min_campione=10, prior_k=0, safety_bps=10000, max_overbooking_bps=5000))
        _popola(g._st, "casa", segmento_da_data("2026-07-03"), 70, 30)
        self.assertEqual(g.applica_a_inventario(InvRotto(), "casa", "2026-07-03",
                         capacita_reale=10, prezzo_netto_cents=10000), 0)


class TestCompensazione(unittest.TestCase):
    def _pren(self, n, prezzo=10000):
        return [{"prenotazione_id": "p%d" % i, "prezzo_guest_cents": prezzo}
                for i in range(n)]

    def test_esuberi_compensati(self):
        g = crea_gestore_noshow()
        piano = g.piano_compensazione(self._pren(12), capacita_reale=10,
                                      voucher_bps=2000)
        self.assertEqual(len(piano), 2)                 # 12 - 10 = 2 esuberi
        self.assertEqual(piano[0].voucher_cents, 2000)  # 20% di 10000
        self.assertTrue(all(isinstance(v, CompensazioneVoce) for v in piano))
        # sono gli ULTIMI prenotati
        self.assertEqual({v.prenotazione_id for v in piano}, {"p10", "p11"})

    def test_nessun_esubero_piano_vuoto(self):
        g = crea_gestore_noshow()
        self.assertEqual(g.piano_compensazione(self._pren(8), capacita_reale=10), [])

    def test_voucher_intero(self):
        g = crea_gestore_noshow()
        piano = g.piano_compensazione(self._pren(11, prezzo=9999), capacita_reale=10,
                                      voucher_bps=1500)
        self.assertEqual(piano[0].voucher_cents, (9999 * 1500) // 10000)
        self.assertIsInstance(piano[0].voucher_cents, int)

    def test_input_invalido_fail_closed(self):
        g = crea_gestore_noshow()
        self.assertEqual(g.piano_compensazione("non lista", 10), [])
        self.assertEqual(g.piano_compensazione([{"x": 1}], 10), [])   # voci invalide scartate
        self.assertEqual(g.piano_compensazione(self._pren(12), -1), [])


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        g = crea_gestore_noshow()
        for bad in (None, 123, [], "x"):
            try:
                g.tasso_noshow_bps(bad, bad)
                g.consiglia_posti_virtuali(bad, bad, bad)
                g.piano_compensazione(bad, bad)
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")


class TestStress(unittest.TestCase):
    def test_conteggi_concorrenti_10x(self):
        for rip in range(10):
            d = tempfile.mkdtemp()
            try:
                st = StoricoPresenze(
                    lambda p=os.path.join(d, f"s{rip}.db"): __import__("sqlite3").connect(p))
                errori = []

                def worker():
                    try:
                        for _ in range(25):
                            st.registra_esito("a", "ven", "no_show")
                    except Exception as e:  # pragma: no cover
                        errori.append(e)

                th = [threading.Thread(target=worker) for _ in range(8)]
                for t in th:
                    t.start()
                for t in th:
                    t.join()
                self.assertEqual(errori, [])
                self.assertEqual(st.conteggi("a", "ven")["no_show"], 8 * 25)
            finally:
                shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
