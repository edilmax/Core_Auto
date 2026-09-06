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


def _pren(n, prezzo=10000):
    return [{"prenotazione_id": "p%d" % i, "prezzo_guest_cents": prezzo} for i in range(n)]


class TestLeGuardieDeiPuntiScoperti(unittest.TestCase):
    """Una guardia per ogni punto che il Giudice della mutazione ha trovato SCOPERTO col
    solo occhio dedicato (2026-09-05, Blocco 2 casella 4): il guasto passava e i test
    restavano verdi. Ogni test dice quale riga difende, cosi' fra sei mesi si sa perche'."""

    def test_la_politica_e_congelata(self):
        # riga 63: `frozen=True` -- una politica che si puo' cambiare a mano dopo la
        # costruzione e' una politica che nessuno sa piu' quale sia.
        from dataclasses import FrozenInstanceError
        pol = PoliticaNoShow()
        with self.assertRaises(FrozenInstanceError):
            pol.min_campione = 0

    def test_la_voce_di_compensazione_e_congelata(self):
        # riga 71: `frozen=True` sulla voce che porta i centesimi del voucher.
        from dataclasses import FrozenInstanceError
        voce = CompensazioneVoce(prenotazione_id="p", voucher_cents=1)
        with self.assertRaises(FrozenInstanceError):
            voce.voucher_cents = 0

    def test_segmento_non_stringa_o_vuoto_rifiutato_senza_sollevare(self):
        # righe 114-115: `not isinstance(...) OR not strip()` -> False. Con `and` un
        # segmento None solleverebbe; con `return True` uno vuoto verrebbe accettato.
        st = crea_storico_presenze()
        self.assertFalse(st.registra_esito("a", None, "presentato"))
        self.assertFalse(st.registra_esito("a", "   ", "presentato"))
        self.assertEqual(st.conteggi("a", "   ")["totale"], 0)

    def test_registrazione_valida_dice_vero(self):
        # riga 131: chi registra un esito deve sapere che e' andato a buon fine.
        st = crea_storico_presenze()
        self.assertTrue(st.registra_esito("a", "ven", "presentato"))
        self.assertEqual(st.conteggi("a", "ven")["presentati"], 1)

    def test_l_avviso_porta_la_traccia_dell_errore(self):
        # riga 200: `exc_info=True` -- l'avviso deve portare LA COSA, del tipo giusto
        # (una tupla con l'eccezione vera), non un `False` che sembra "niente".
        class InvRotto:
            def imposta_disponibilita(self, *a, **k):
                raise RuntimeError("db giu'")
        g = crea_gestore_noshow()
        with self.assertLogs("core_auto.predictive_noshow", level="WARNING") as cm:
            esito = g.applica_a_inventario(InvRotto(), "casa", "2026-07-03",
                                           capacita_reale=10, prezzo_netto_cents=10000)
        self.assertEqual(esito, 0)
        traccia = cm.records[0].exc_info
        self.assertIsInstance(traccia, tuple)
        self.assertIs(traccia[0], RuntimeError)

    def test_capacita_invalida_non_consulta_nemmeno_lo_storico(self):
        # riga 176: `capacita <= 0` -- con capacita' zero si esce PRIMA di leggere lo
        # storico (con `< 0` lo zero passerebbe e andrebbe a leggere il database).
        class StoricoRotto:
            def conteggi(self, *a, **k):
                raise RuntimeError("storico letto quando non doveva")
        g = GestoreNoShow(StoricoRotto())
        self.assertEqual(g.consiglia_posti_virtuali(0, "a", "ven"), 0)

    def test_un_tasso_di_un_solo_punto_base_conta_gia(self):
        # riga 179 riscritta (`rate_bps < 1`): a 1 bps, con capacita' 10000, safety 100% e
        # tetto 100%, un no-show atteso c'e' -> 1 posto virtuale (con `<= 1` sarebbe 0).
        g = crea_gestore_noshow(politica=PoliticaNoShow(
            min_campione=20, prior_k=9980, safety_bps=10000, max_overbooking_bps=10000))
        _popola(g._st, "a", "ven", 19, 1)          # 1 * 10000 // (20 + 9980) = 1 bps esatto
        self.assertEqual(g.tasso_noshow_bps("a", "ven"), 1)
        self.assertEqual(g.consiglia_posti_virtuali(10000, "a", "ven"), 1)

    def test_capacita_zero_compensa_tutti(self):
        # riga 210: `capacita_reale < 0` -- zero posti e' un caso valido: tutti esuberi.
        g = crea_gestore_noshow()
        piano = g.piano_compensazione(_pren(2), capacita_reale=0, voucher_bps=1000)
        self.assertEqual([v.prenotazione_id for v in piano], ["p0", "p1"])

    def test_prezzo_zero_conta_come_prenotazione_valida(self):
        # riga 217: `prezzo_guest_cents >= 0` -- una prenotazione gratuita occupa un
        # posto e conta nell'eccedenza (con `> 0` sparirebbe dal conto).
        g = crea_gestore_noshow()
        pren = [{"prenotazione_id": "gratis", "prezzo_guest_cents": 0}] + _pren(1)
        piano = g.piano_compensazione(pren, capacita_reale=1, voucher_bps=2000)
        self.assertEqual([v.prenotazione_id for v in piano], ["p0"])

    def test_esattamente_pieni_nessuna_compensazione(self):
        # riga 219: `eccedenza <= 0` -- con `<` un'eccedenza ZERO farebbe
        # `validi[-0:]`, cioe' TUTTI i prenotati compensati.
        g = crea_gestore_noshow()
        self.assertEqual(g.piano_compensazione(_pren(10), capacita_reale=10,
                                               voucher_bps=2000), [])

    def test_voucher_bps_non_intero_vale_zero_senza_sollevare(self):
        # riga 221: `not _intero(voucher_bps) OR voucher_bps < 0` -> 0. Con `and` un
        # voucher_bps non numerico solleverebbe TypeError dentro il piano.
        g = crea_gestore_noshow()
        piano = g.piano_compensazione(_pren(11), capacita_reale=10, voucher_bps="x")
        self.assertEqual([v.voucher_cents for v in piano], [0])

    def test_lo_storico_in_memoria_si_usa_da_un_altro_thread(self):
        # riga 257: `check_same_thread=False` -- il server e' a thread: lo storico in
        # memoria dev'essere usabile da un thread diverso da chi l'ha creato.
        st = crea_storico_presenze()
        errori = []

        def lavoro():
            try:
                st.registra_esito("a", "ven", "no_show")
            except Exception as e:  # pragma: no cover
                errori.append(repr(e))

        t = threading.Thread(target=lavoro)
        t.start()
        t.join()
        self.assertEqual(errori, [])
        self.assertEqual(st.conteggi("a", "ven")["no_show"], 1)


if __name__ == "__main__":
    unittest.main()
