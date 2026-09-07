"""
Test Fase 72 - Digital Twin (telemetria + manutenzione predittiva).

Copre: registrazione letture + stato, validazione (no float), anomalie (fuori banda),
predizione guasti (trend su/giu verso soglia, stabile non predice, gia' oltre non
predice), agibilita' (critici in banda / assenti / fuori banda), report pre/post,
robustezza, stress concorrente. Orologio iniettato.
"""
import dataclasses
import os
import shutil
import tempfile
import threading
import time
import unittest

from fase72_digital_twin import (
    Anomalia, DigitalTwin, PredizioneGuasto, SensoreConfig, crea_digital_twin,
)

# temperatura in centi-gradi, umidita' in per-mille
TEMP = SensoreConfig(banda_min=1800, banda_max=2500, critico=True)
UMID = SensoreConfig(banda_min=300, banda_max=600, soglia_guasto=800, direzione="su")
CONFIG = {"temp": TEMP, "umidita": UMID}


class TestLetture(unittest.TestCase):
    def setUp(self):
        self.t = crea_digital_twin()

    def test_registra_e_stato(self):
        self.t.registra_lettura("casa", "temp", 2100, ts=100)
        self.t.registra_lettura("casa", "temp", 2200, ts=200)
        st = self.t.stato("casa")
        self.assertEqual(st["temp"]["valore"], 2200)     # l'ultima

    def test_valore_float_rifiutato(self):
        self.assertFalse(self.t.registra_lettura("casa", "temp", 21.5, ts=100))
        self.assertFalse(self.t.registra_lettura("casa", "temp", True, ts=100))

    def test_input_invalido(self):
        self.assertFalse(self.t.registra_lettura("", "temp", 2000))
        self.assertFalse(self.t.registra_lettura("casa", "", 2000))


class TestAnomalie(unittest.TestCase):
    def test_fuori_banda(self):
        t = crea_digital_twin()
        t.registra_lettura("casa", "temp", 3000, ts=100)   # troppo caldo (>2500)
        an = t.anomalie("casa", CONFIG)
        self.assertEqual(len(an), 1)
        self.assertEqual(an[0].sensore, "temp")
        self.assertIsInstance(an[0], Anomalia)

    def test_in_banda_nessuna(self):
        t = crea_digital_twin()
        t.registra_lettura("casa", "temp", 2100, ts=100)
        self.assertEqual(t.anomalie("casa", CONFIG), [])


class TestPredizione(unittest.TestCase):
    def test_trend_su_verso_soglia(self):
        t = crea_digital_twin()
        # umidita' sale 400->500->600->700 in 3000s; soglia guasto 800
        for i, v in enumerate((400, 500, 600, 700)):
            t.registra_lettura("casa", "umidita", v, ts=1000 + i * 1000)
        pred = t.predici_guasti("casa", CONFIG, orizzonte_sec=2000)
        self.assertEqual(len(pred), 1)
        self.assertEqual(pred[0].sensore, "umidita")
        self.assertGreaterEqual(pred[0].valore_proiettato, 800)
        self.assertIsInstance(pred[0], PredizioneGuasto)

    def test_stabile_non_predice(self):
        t = crea_digital_twin()
        for i in range(5):
            t.registra_lettura("casa", "umidita", 450, ts=1000 + i * 1000)
        self.assertEqual(t.predici_guasti("casa", CONFIG, orizzonte_sec=10000), [])

    def test_gia_oltre_soglia_non_predice(self):
        t = crea_digital_twin()
        for i, v in enumerate((820, 850, 900)):
            t.registra_lettura("casa", "umidita", v, ts=1000 + i * 1000)
        # gia' oltre la soglia -> e' anomalia, non predizione
        self.assertEqual(t.predici_guasti("casa", CONFIG, orizzonte_sec=10000), [])

    def test_trend_giu(self):
        t = crea_digital_twin()
        cfg = {"batteria": SensoreConfig(banda_min=0, banda_max=10000,
                                         soglia_guasto=1000, direzione="giu")}
        for i, v in enumerate((5000, 4000, 3000, 2000)):
            t.registra_lettura("casa", "batteria", v, ts=1000 + i * 1000)
        pred = t.predici_guasti("casa", cfg, orizzonte_sec=2000)
        self.assertEqual(len(pred), 1)
        self.assertLessEqual(pred[0].valore_proiettato, 1000)

    def test_orizzonte_breve_non_predice(self):
        t = crea_digital_twin()
        for i, v in enumerate((400, 410, 420)):     # sale lentamente
            t.registra_lettura("casa", "umidita", v, ts=1000 + i * 1000)
        self.assertEqual(t.predici_guasti("casa", CONFIG, orizzonte_sec=100), [])


class TestAgibilita(unittest.TestCase):
    def test_critico_in_banda_pronto(self):
        t = crea_digital_twin()
        t.registra_lettura("casa", "temp", 2100, ts=100)
        self.assertTrue(t.pronto_per_arrivo("casa", CONFIG))

    def test_critico_fuori_banda_non_pronto(self):
        t = crea_digital_twin()
        t.registra_lettura("casa", "temp", 3000, ts=100)
        self.assertFalse(t.pronto_per_arrivo("casa", CONFIG))

    def test_critico_assente_fail_closed(self):
        t = crea_digital_twin()
        t.registra_lettura("casa", "umidita", 400, ts=100)  # solo umidita', temp manca
        self.assertFalse(t.pronto_per_arrivo("casa", CONFIG))


class TestReport(unittest.TestCase):
    def test_pre_post(self):
        t = crea_digital_twin()
        t.registra_lettura("casa", "energia", 100, ts=1000)
        t.registra_lettura("casa", "energia", 250, ts=5000)
        r = t.report_soggiorno("casa", "energia", 1000, 5000)
        self.assertEqual(r, {"inizio": 100, "fine": 250, "delta": 150})

    def test_intervallo_vuoto(self):
        t = crea_digital_twin()
        self.assertIsNone(t.report_soggiorno("casa", "x", 0, 100))


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        t = crea_digital_twin()
        for bad in (None, 123, ""):
            try:
                t.registra_lettura(bad, bad, bad)
                t.stato(bad)
                t.anomalie(bad, {})
                t.predici_guasti(bad, {}, orizzonte_sec=100)
                t.pronto_per_arrivo(bad, {})
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")


class TestStress(unittest.TestCase):
    def test_letture_concorrenti_10x(self):
        for rip in range(10):
            d = tempfile.mkdtemp()
            try:
                t = crea_digital_twin(os.path.join(d, f"tw{rip}.db"))
                errori = []
                lock = threading.Lock()

                def worker(i):
                    try:
                        for k in range(20):
                            t.registra_lettura("casa", "s%d" % i, k, ts=1000 + k)
                    except Exception as ex:  # pragma: no cover
                        with lock:
                            errori.append(ex)

                th = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
                for x in th:
                    x.start()
                for x in th:
                    x.join()
                self.assertEqual(errori, [])
                self.assertEqual(len(t.stato("casa")), 8)   # 8 sensori distinti
            finally:
                shutil.rmtree(d, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════════════
# I 30 PUNTI SOPRAVVISSUTI DELLA NOTTE FRA IL 6 E IL 7 SETTEMBRE 2026 (Giudice, Blocco 7)
# ═══════════════════════════════════════════════════════════════════════════════════════

BATTERIA = SensoreConfig(banda_min=0, banda_max=10000, soglia_guasto=1000, direzione="giu")


class TestI30PuntiSopravvissutiDellaNotteDel7Settembre(unittest.TestCase):
    """Il Giudice (giudice_notte_blocchi_4_7) ha trovato 30 punti in cui il guasto passa e
    i test restano verdi. UNA guardia per punto, col numero di riga nel nome, vista ROSSA
    col mutante iniettato con l'editor e ripristino byte-identico.

    Le famiglie: i CONFINI delle bande e delle soglie (il valore ESATTO sul bordo e' in
    banda, la soglia raggiunta e' anomalia e non predizione, la proiezione che tocca la
    soglia e' una predizione); gli `or`/`and` delle guardie sugli ingressi (un tipo
    storto risponde vuoto, mai TypeError/ZeroDivisionError); i tre `frozen=True`; e il
    `check_same_thread=False` della connessione condivisa."""

    def setUp(self):
        self.t = crea_digital_twin()

    def _conta_aperture(self, twin):
        fabbrica = twin._conn_factory
        conto = {"n": 0}

        def contata():
            conto["n"] += 1
            return fabbrica()
        twin._conn_factory = contata
        return conto

    def _serie(self, sensore, valori, passo=1000, inizio=1000):
        """Non pretende il True di registra_lettura: quello ha la SUA guardia (riga 127),
        cosi' ogni altra guardia va rossa solo per il suo punto."""
        for i, v in enumerate(valori):
            self.t.registra_lettura("casa", sensore, v, ts=inizio + i * passo)

    # ── righe 50 · 59 · 67: i tre valori sono IMMUTABILI (e quindi usabili come chiavi) ─
    def test_riga50_SensoreConfig_e_congelato(self):
        cfg = SensoreConfig(banda_min=1, banda_max=2)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            cfg.banda_min = 0
        self.assertEqual(hash(SensoreConfig(banda_min=1, banda_max=2)), hash(cfg))

    def test_riga59_Anomalia_e_congelata(self):
        a = Anomalia("temp", 3000, 1800, 2500)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            a.valore = 0
        self.assertEqual(hash(Anomalia("temp", 3000, 1800, 2500)), hash(a))

    def test_riga67_PredizioneGuasto_e_congelata(self):
        p = PredizioneGuasto("umidita", 700, 800, 800, 1000)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.quando_sec = 0
        self.assertEqual(hash(PredizioneGuasto("umidita", 700, 800, 800, 1000)), hash(p))

    # ── riga 83: l'orologio INIETTATO e' quello usato; senza, quello vero ──────────
    def test_riga83_l_orologio_iniettato_firma_le_letture_senza_ts(self):
        t = crea_digital_twin(orologio=lambda: 777)
        self.assertTrue(t.registra_lettura("casa", "temp", 2100))
        self.assertEqual(777, t.stato("casa")["temp"]["ts"], "l'orologio iniettato e' ignorato")

    def test_riga83_senza_orologio_iniettato_si_usa_quello_vero(self):
        prima = int(time.time())
        self.assertTrue(self.t.registra_lettura("casa", "temp", 2100))
        ts = self.t.stato("casa")["temp"]["ts"]
        self.assertTrue(prima <= ts <= int(time.time()) + 1, "ts %r non e' l'ora vera" % (ts,))

    # ── riga 127: una lettura valida risponde True ─────────────────────────────────
    def test_riga127_una_lettura_valida_risponde_True(self):
        self.assertIs(True, self.t.registra_lettura("casa", "temp", 2100, ts=100))

    # ── riga 153: il valore ESATTO sul bordo della banda NON e' un'anomalia ────────
    def test_riga153_il_minimo_esatto_della_banda_e_in_banda_e_un_passo_sotto_no(self):
        self.t.registra_lettura("casa", "temp", 1800, ts=100)          # = banda_min
        self.assertEqual([], self.t.anomalie("casa", CONFIG), "il minimo esatto segnalato come anomalia")
        self.t.registra_lettura("casa", "temp", 1799, ts=200)
        self.assertEqual(1, len(self.t.anomalie("casa", CONFIG)), "un passo sotto il minimo non e' anomalia")

    def test_riga153_il_massimo_esatto_della_banda_e_in_banda_e_un_passo_sopra_no(self):
        self.t.registra_lettura("casa", "temp", 2500, ts=100)          # = banda_max
        self.assertEqual([], self.t.anomalie("casa", CONFIG), "il massimo esatto segnalato come anomalia")
        self.t.registra_lettura("casa", "temp", 2501, ts=200)
        self.assertEqual(1, len(self.t.anomalie("casa", CONFIG)), "un passo sopra il massimo non e' anomalia")

    # ── riga 161: un orizzonte non valido risponde vuoto, senza toccare l'archivio ──
    def test_riga161_un_orizzonte_di_tipo_storto_risponde_vuoto_senza_esplodere(self):
        self._serie("umidita", (400, 500, 600, 700))
        for cattivo in ("abc", None, True, 3.5):
            self.assertEqual([], self.t.predici_guasti("casa", CONFIG, orizzonte_sec=cattivo),
                             "orizzonte %r accettato" % (cattivo,))

    def test_riga161_un_orizzonte_di_ZERO_risponde_vuoto_senza_aprire_l_archivio(self):
        self._serie("umidita", (400, 500, 600, 700))
        conto = self._conta_aperture(self.t)
        self.assertEqual([], self.t.predici_guasti("casa", CONFIG, orizzonte_sec=0))
        self.assertEqual([], self.t.predici_guasti("casa", CONFIG, orizzonte_sec=-1))
        self.assertEqual(0, conto["n"], "un orizzonte non positivo ha aperto l'archivio")

    # ── riga 163: la finestra ripiega su 10 se assurda, e vale ESATTAMENTE se e' 2 ──
    def test_riga163_una_finestra_ASSURDA_ripiega_sul_valore_di_serie(self):
        self._serie("umidita", (400, 500, 600, 700))
        for cattiva in (1, 0, "abc", None):
            pred = self.t.predici_guasti("casa", CONFIG, orizzonte_sec=2000, finestra=cattiva)
            self.assertEqual(1, len(pred), "con finestra=%r la predizione sparisce" % (cattiva,))

    def test_riga163_una_finestra_di_DUE_letture_guarda_solo_le_ultime_due(self):
        """400,400,400,600: sulle ultime DUE il trend e' +200/1000 s e in 1000 s tocca la
        soglia 800; su TUTTE e quattro e' +200/3000 s e non la tocca. Se il 2 ripiegasse
        su 10, la predizione sparirebbe."""
        self._serie("umidita", (400, 400, 400, 600))
        self.assertEqual(1, len(self.t.predici_guasti("casa", CONFIG, orizzonte_sec=1000, finestra=2)))
        self.assertEqual([], self.t.predici_guasti("casa", CONFIG, orizzonte_sec=1000, finestra=10))

    # ── riga 168: una configurazione storta si salta, non fa esplodere il giro ─────
    def test_riga168_una_voce_di_config_NON_valida_viene_saltata_senza_esplodere(self):
        self._serie("umidita", (400, 500, 600, 700))
        config = {"rotto": None, "tupla": (1, 2), "umidita": UMID}
        pred = self.t.predici_guasti("casa", config, orizzonte_sec=2000)
        self.assertEqual(["umidita"], [p.sensore for p in pred])

    def test_riga168_un_sensore_SENZA_soglia_di_guasto_non_si_proietta(self):
        self._serie("temp", (1900, 2000, 2100, 2200))                      # TEMP: nessuna soglia
        self.assertEqual([], self.t.predici_guasti("casa", CONFIG, orizzonte_sec=100000))

    # ── riga 174: DUE letture bastano per un trend ─────────────────────────────────
    def test_riga174_due_letture_bastano_per_predire(self):
        self._serie("umidita", (500, 700))
        pred = self.t.predici_guasti("casa", CONFIG, orizzonte_sec=1000)
        self.assertEqual(1, len(pred), "con esattamente due letture non si predice")
        self.assertEqual(900, pred[0].valore_proiettato)

    # ── riga 180: due letture nello STESSO secondo non dividono per zero ───────────
    def test_riga180_due_letture_nello_stesso_secondo_non_esplodono(self):
        self.assertTrue(self.t.registra_lettura("casa", "umidita", 500, ts=1000))
        self.assertTrue(self.t.registra_lettura("casa", "umidita", 700, ts=1000))
        self.assertEqual([], self.t.predici_guasti("casa", CONFIG, orizzonte_sec=1000))

    # ── riga 196 (direzione «su»): i tre confini della proiezione ──────────────────
    def test_riga196_un_trend_NULLO_non_si_proietta_nemmeno_chiamando_la_proiezione_diretta(self):
        self.assertIsNone(DigitalTwin._proietta("umidita", UMID, 500, 0, 1000, 1000))

    def test_riga196_alla_soglia_ESATTA_e_un_anomalia_non_una_predizione(self):
        self._serie("umidita", (600, 700, 800))                            # attuale = soglia
        self.assertEqual([], self.t.predici_guasti("casa", CONFIG, orizzonte_sec=1000))

    def test_riga196_la_proiezione_che_TOCCA_la_soglia_e_una_predizione(self):
        self._serie("umidita", (600, 700))                                 # +100 in 1000 s
        pred = self.t.predici_guasti("casa", CONFIG, orizzonte_sec=1000)   # proiettato = 800
        self.assertEqual(1, len(pred), "proiezione esattamente sulla soglia ignorata")
        self.assertEqual(800, pred[0].valore_proiettato)
        self.assertEqual(1000, pred[0].quando_sec)

    # ── riga 200 (direzione «giu»): i cinque confini della proiezione ──────────────
    def test_riga200_un_trend_NULLO_non_si_proietta_nemmeno_chiamando_la_proiezione_diretta(self):
        self.assertIsNone(DigitalTwin._proietta("batteria", BATTERIA, 5000, 0, 1000, 1000))

    def test_riga200_una_batteria_GIA_sotto_la_soglia_che_scende_e_un_anomalia_non_una_predizione(self):
        self._serie("batteria", (900, 800))
        self.assertEqual([], self.t.predici_guasti("casa", {"batteria": BATTERIA}, orizzonte_sec=1000))

    def test_riga200_una_batteria_che_scende_ma_NON_arriva_alla_soglia_non_si_predice(self):
        self._serie("batteria", (5000, 4900))                              # -100 in 1000 s
        self.assertEqual([], self.t.predici_guasti("casa", {"batteria": BATTERIA}, orizzonte_sec=1000))

    def test_riga200_alla_soglia_ESATTA_che_scende_e_un_anomalia_non_una_predizione(self):
        self._serie("batteria", (1100, 1000))                              # attuale = soglia
        self.assertEqual([], self.t.predici_guasti("casa", {"batteria": BATTERIA}, orizzonte_sec=1000))

    def test_riga200_la_proiezione_che_TOCCA_la_soglia_scendendo_e_una_predizione(self):
        self._serie("batteria", (1200, 1100))                              # -100 in 1000 s
        pred = self.t.predici_guasti("casa", {"batteria": BATTERIA}, orizzonte_sec=1000)
        self.assertEqual(1, len(pred), "proiezione esattamente sulla soglia ignorata (giu)")
        self.assertEqual(1000, pred[0].valore_proiettato)
        self.assertEqual(1000, pred[0].quando_sec)

    # ── riga 216: l'agibilita' sul bordo ESATTO della banda ────────────────────────
    def test_riga216_il_critico_al_minimo_esatto_e_pronto_e_un_passo_sotto_no(self):
        self.t.registra_lettura("casa", "temp", 1800, ts=100)
        self.assertIs(True, self.t.pronto_per_arrivo("casa", CONFIG), "minimo esatto: non pronto")
        self.t.registra_lettura("casa", "temp", 1799, ts=200)
        self.assertIs(False, self.t.pronto_per_arrivo("casa", CONFIG))

    def test_riga216_il_critico_al_massimo_esatto_e_pronto_e_un_passo_sopra_no(self):
        self.t.registra_lettura("casa", "temp", 2500, ts=100)
        self.assertIs(True, self.t.pronto_per_arrivo("casa", CONFIG), "massimo esatto: non pronto")
        self.t.registra_lettura("casa", "temp", 2501, ts=200)
        self.assertIs(False, self.t.pronto_per_arrivo("casa", CONFIG))

    # ── riga 223: l'intervallo del report ──────────────────────────────────────────
    def test_riga223_un_estremo_di_tipo_storto_risponde_None_senza_esplodere(self):
        self.t.registra_lettura("casa", "energia", 100, ts=1000)
        for a, b in ((1000, "abc"), ("abc", 1000), (1000, None), (None, 5000), (True, 5000)):
            self.assertIsNone(self.t.report_soggiorno("casa", "energia", a, b),
                              "intervallo %r-%r accettato" % (a, b))

    def test_riga223_un_intervallo_ROVESCIATO_risponde_None_anche_se_le_letture_ci_sono(self):
        self.t.registra_lettura("casa", "energia", 100, ts=1000)
        self.t.registra_lettura("casa", "energia", 250, ts=5000)
        self.assertIsNone(self.t.report_soggiorno("casa", "energia", 5000, 1000),
                          "un intervallo con inizio > fine ha prodotto un report")

    def test_riga223_un_intervallo_di_un_ISTANTE_e_valido(self):
        self.t.registra_lettura("casa", "energia", 100, ts=1000)
        self.assertEqual({"inizio": 100, "fine": 100, "delta": 0},
                         self.t.report_soggiorno("casa", "energia", 1000, 1000))

    # ── riga 237: manca UN estremo -> None, non TypeError ──────────────────────────
    def test_riga237_se_manca_la_lettura_di_UN_solo_estremo_il_report_e_None(self):
        self.t.registra_lettura("casa", "energia", 100, ts=1000)
        self.assertIsNone(self.t.report_soggiorno("casa", "energia", 2000, 3000),   # niente >= 2000
                          "report prodotto senza la lettura iniziale")
        self.assertIsNone(self.t.report_soggiorno("casa", "energia", 0, 500),       # niente <= 500
                          "report prodotto senza la lettura finale")

    # ── riga 269: la connessione in memoria e' condivisa FRA I THREAD ──────────────
    def test_riga269_il_twin_in_memoria_accetta_letture_da_un_altro_thread(self):
        errori = []

        def lavoratore():
            try:
                self.t.registra_lettura("casa", "temp", 2100, ts=100)
            except Exception as e:
                errori.append(repr(e))
        th = threading.Thread(target=lavoratore)
        th.start()
        th.join()
        self.assertEqual([], errori, "la connessione in memoria rifiuta un altro thread")
        self.assertEqual(2100, self.t.stato("casa")["temp"]["valore"])


if __name__ == "__main__":
    unittest.main()
