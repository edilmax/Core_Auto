"""
Test Fase 70 - Automated Turnover.

Copre: creazione con finestra + idempotenza, date invalide, assegna/completa (in tempo
e in ritardo), gate agibilita' (pronto/non pronto/assente), allarme ritardi (a_rischio
+ segnala isolato), robustezza, stress concorrente. Orologio iniettato.
"""
import dataclasses
import logging
import os
import shutil
import tempfile
import threading
import unittest

from fase70_turnover import (
    EsitoTurnover, GestoreTurnover, _epoch_da_data_ora, _intero_nn, crea_gestore_turnover,
)

# finestra default: checkout 11:00, checkin successivo 15:00
DA = _epoch_da_data_ora("2026-09-10", 11)
A = _epoch_da_data_ora("2026-09-10", 15)        # stesso giorno, back-to-back


class TestCreazione(unittest.TestCase):
    def setUp(self):
        self.g = crea_gestore_turnover()

    def test_crea_con_finestra(self):
        tid = self.g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        st = self.g.stato_turnover(tid)
        self.assertEqual(st["finestra_da"], DA)
        self.assertEqual(st["finestra_a"], A)
        self.assertEqual(st["stato"], "da_fare")

    def test_idempotente(self):
        a = self.g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        b = self.g.crea_turnover("casa", "2026-09-10", "2026-09-12")
        self.assertEqual(a, b)                  # stesso (alloggio, checkout) -> stesso task

    def test_senza_prossimo_checkin(self):
        tid = self.g.crea_turnover("casa", "2026-09-10")
        self.assertIsNone(self.g.stato_turnover(tid)["finestra_a"])

    def test_date_invalide(self):
        self.assertIsNone(self.g.crea_turnover("casa", "non-data"))
        # prossimo check-in prima del checkout -> invalido
        self.assertIsNone(self.g.crea_turnover("casa", "2026-09-10", "2026-09-09"))
        self.assertIsNone(self.g.crea_turnover("", "2026-09-10"))


class TestCompletamento(unittest.TestCase):
    def test_pronto_in_tempo(self):
        g = crea_gestore_turnover(orologio=lambda: DA + 3600)   # 1h dopo checkout, < A
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        self.assertTrue(g.assegna(tid, "addetto1").ok)
        e = g.completa(tid)
        self.assertEqual(e.stato, "pronto")

    def test_pronto_in_ritardo(self):
        g = crea_gestore_turnover(orologio=lambda: A + 3600)    # oltre la finestra
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        g.assegna(tid, "addetto1")
        e = g.completa(tid)
        self.assertEqual(e.stato, "pronto_in_ritardo")

    def test_completa_idempotente(self):
        g = crea_gestore_turnover(orologio=lambda: DA + 3600)
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        g.completa(tid)
        e = g.completa(tid)
        self.assertTrue(e.ok)
        self.assertEqual(e.stato, "pronto")

    def test_assegna_inesistente(self):
        g = crea_gestore_turnover()
        self.assertFalse(g.assegna(99999, "x").ok)


class TestAgibilita(unittest.TestCase):
    def test_non_pronto_blocca(self):
        g = crea_gestore_turnover()
        g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        # turnover 'da_fare' -> check-in del 2026-09-10 NON agibile (fail-closed)
        self.assertFalse(g.agibile("casa", "2026-09-10"))

    def test_pronto_agibile(self):
        g = crea_gestore_turnover(orologio=lambda: DA + 3600)
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        g.completa(tid)
        self.assertTrue(g.agibile("casa", "2026-09-10"))

    def test_nessun_turnover_agibile(self):
        g = crea_gestore_turnover()
        # nessuna pulizia schedulata per quel check-in -> agibile
        self.assertTrue(g.agibile("casa", "2026-12-25"))

    def test_in_ritardo_resta_agibile(self):
        g = crea_gestore_turnover(orologio=lambda: A + 3600)
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        g.completa(tid)                          # pronto_in_ritardo
        self.assertTrue(g.agibile("casa", "2026-09-10"))   # pulito, anche se tardi


class TestAllarmeRitardi(unittest.TestCase):
    def test_a_rischio(self):
        g = crea_gestore_turnover(orologio=lambda: A + 7200)   # finestra chiusa
        g.crea_turnover("casa", "2026-09-10", "2026-09-10")    # 'da_fare', in ritardo
        rischi = g.a_rischio()
        self.assertEqual(len(rischi), 1)
        self.assertEqual(rischi[0]["alloggio_id"], "casa")

    def test_non_a_rischio_se_pronto(self):
        g = crea_gestore_turnover(orologio=lambda: A + 7200)
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        g.completa(tid)
        self.assertEqual(g.a_rischio(), [])

    def test_segnala_isolato(self):
        ricevute = []
        g = crea_gestore_turnover(orologio=lambda: A + 7200,
                                  notificatore=ricevute.append)
        g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        n = g.segnala_ritardi()
        self.assertEqual(n, 1)
        self.assertEqual(ricevute[0]["tipo"], "turnover_a_rischio")

    def test_segnala_notificatore_che_solleva(self):
        def boom(_):
            raise RuntimeError("canale giu'")
        g = crea_gestore_turnover(orologio=lambda: A + 7200, notificatore=boom)
        g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        self.assertEqual(g.segnala_ritardi(), 1)   # non si schianta


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        g = crea_gestore_turnover()
        for bad in (None, 123, ""):
            try:
                g.crea_turnover(bad, bad, bad)
                g.assegna(bad, bad)
                g.completa(bad)
                g.agibile(bad, bad)
                g.a_rischio(ora=bad)
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")


class TestStress(unittest.TestCase):
    def test_crea_concorrenti_10x(self):
        for rip in range(10):
            d = tempfile.mkdtemp()
            try:
                g = crea_gestore_turnover(os.path.join(d, f"t{rip}.db"))
                errori = []
                lock = threading.Lock()

                def worker(i):
                    try:
                        tid = g.crea_turnover("casa%d" % i, "2026-09-10", "2026-09-10")
                        with lock:
                            errori.append(tid is not None)
                    except Exception as ex:  # pragma: no cover
                        with lock:
                            errori.append(ex)

                th = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
                for t in th:
                    t.start()
                for t in th:
                    t.join()
                self.assertTrue(all(x is True for x in errori))
            finally:
                shutil.rmtree(d, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════════════
# I 13 PUNTI SOPRAVVISSUTI DELLA NOTTE FRA IL 6 E IL 7 SETTEMBRE 2026 (Giudice, Blocco 7)
# ═══════════════════════════════════════════════════════════════════════════════════════

class TestI13PuntiSopravvissutiDellaNotteDel7Settembre(unittest.TestCase):
    """Il Giudice (giudice_notte_blocchi_4_7) ha trovato 13 punti in cui il guasto passa e i
    test restano verdi. UNA guardia per punto, col numero di riga nel nome, vista ROSSA col
    mutante iniettato con l'editor e ripristino byte-identico.

    Quasi tutti nascono dallo stesso buco: i test vecchi guardano `.stato` o `.motivo` e
    mai `.ok`, e dopo `assegna` nessuno rilegge lo stato dall'archivio. Un rifiuto che
    dice `ok=True` manda il pannello a credere che la pulizia sia assegnata; una
    transizione che «riesce» senza scrivere lascia la stanza sporca con la chiave che
    apre."""

    def _gestore(self, orologio=lambda: DA + 3600, **kw):
        return crea_gestore_turnover(orologio=orologio, **kw)

    def _stato(self, g, tid):
        return g.stato_turnover(tid)["stato"]

    # ── riga 51: lo ZERO e' un intero non negativo ─────────────────────────────────
    def test_riga51_lo_zero_e_un_intero_non_negativo(self):
        self.assertIs(True, _intero_nn(0))
        self.assertIs(False, _intero_nn(-1))
        self.assertIs(False, _intero_nn(False))

    def test_riga51_a_rischio_all_ora_ZERO_non_trova_niente_perche_nulla_e_scaduto_all_epoca(self):
        g = self._gestore(orologio=lambda: A + 7200)               # ADESSO la finestra e' chiusa
        g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        self.assertEqual(1, len(g.a_rischio()), "premessa: adesso e' a rischio")
        self.assertEqual([], g.a_rischio(ora=0),
                         "ora=0 e' stato scartato e sostituito dall'orologio")

    # ── riga 66: l'esito e' IMMUTABILE ─────────────────────────────────────────────
    def test_riga66_EsitoTurnover_e_congelato(self):
        e = EsitoTurnover(False, "inesistente")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            e.ok = True
        self.assertEqual(hash(EsitoTurnover(False, "inesistente")), hash(e))

    # ── riga 136: check-in nello STESSO istante del check-out e' una finestra valida ─
    def test_riga136_una_finestra_di_ampiezza_ZERO_e_valida(self):
        g = crea_gestore_turnover(ora_checkout=15, ora_checkin=15)
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        self.assertIsNotNone(tid, "finestra [15:00, 15:00] rifiutata")
        st = g.stato_turnover(tid)
        self.assertEqual(st["finestra_da"], st["finestra_a"])
        self.assertIsNone(g.crea_turnover("casa", "2026-09-11", "2026-09-10"),
                          "check-in PRIMA del check-out accettato")

    # ── riga 171: addetto non valido -> RIFIUTO ────────────────────────────────────
    def test_riga171_un_addetto_non_valido_e_un_RIFIUTO_e_non_cambia_lo_stato(self):
        g = self._gestore()
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        for cattivo in ("", "   ", None, 42):
            e = g.assegna(tid, cattivo)
            self.assertIs(False, e.ok, "assegnazione a %r RIUSCITA" % (cattivo,))
            self.assertEqual("addetto_non_valido", e.motivo)
        self.assertEqual("da_fare", self._stato(g, tid))

    # ── riga 184: completare un turnover inesistente -> RIFIUTO ────────────────────
    def test_riga184_completare_un_turnover_INESISTENTE_e_un_RIFIUTO(self):
        g = self._gestore()
        e = g.completa(99999)
        self.assertIs(False, e.ok)
        self.assertEqual("inesistente", e.motivo)

    # ── riga 190: uno stato sconosciuto nell'archivio -> RIFIUTO, e resta com'e' ───
    def test_riga190_uno_stato_SCONOSCIUTO_non_si_completa_e_resta_intatto(self):
        """Stato costruito a mano (D19): nessuna transizione porta a 'annullato', quindi
        si scrive con una UPDATE. Il completamento deve rifiutare e NON toccarlo."""
        g = self._gestore()
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        con = g._apri()
        try:
            with con:
                con.execute("UPDATE turnover SET stato='annullato' WHERE id=?", (tid,))
        finally:
            con.close()
        e = g.completa(tid)
        self.assertIs(False, e.ok, "un turnover in stato sconosciuto e' stato completato")
        self.assertEqual("stato_non_valido", e.motivo)
        self.assertEqual("annullato", self._stato(g, tid))

    # ── riga 192: completare nel SECONDO ESATTO della chiusura non e' in ritardo ───
    def test_riga192_completare_nel_secondo_esatto_della_finestra_e_PRONTO_non_in_ritardo(self):
        g = self._gestore(orologio=lambda: A)
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        self.assertEqual("pronto", g.completa(tid).stato)
        g2 = self._gestore(orologio=lambda: A + 1)
        tid2 = g2.crea_turnover("casa", "2026-09-10", "2026-09-10")
        self.assertEqual("pronto_in_ritardo", g2.completa(tid2).stato)

    # ── riga 197: un completamento riuscito dice ok=True ───────────────────────────
    def test_riga197_un_completamento_riuscito_dice_ok_True(self):
        g = self._gestore()
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        e = g.completa(tid)
        self.assertIs(True, e.ok, "completamento riuscito raccontato come fallito")
        self.assertEqual("", e.motivo)
        self.assertEqual("pronto", self._stato(g, tid))

    # ── righe 217 · 219: la transizione SCRIVE, e ripeterla e' idempotente ─────────
    def test_riga217_assegnare_SCRIVE_davvero_lo_stato_e_l_addetto(self):
        g = self._gestore()
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        e = g.assegna(tid, "addetto1")
        self.assertIs(True, e.ok)
        st = g.stato_turnover(tid)
        self.assertEqual("in_corso", st["stato"], "assegnazione 'riuscita' senza scrivere lo stato")
        self.assertEqual("addetto1", st["addetto_id"])

    def test_riga219_assegnare_due_volte_e_idempotente_e_dice_ok_True(self):
        g = self._gestore()
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        self.assertTrue(g.assegna(tid, "addetto1").ok)
        e = g.assegna(tid, "addetto2")
        self.assertIs(True, e.ok, "la seconda assegnazione e' un rifiuto")
        self.assertEqual("in_corso", e.stato)
        self.assertEqual("addetto1", g.stato_turnover(tid)["addetto_id"],
                         "la seconda assegnazione ha sovrascritto l'addetto")

    # ── riga 222: assegnare un turnover gia' PRONTO e' un RIFIUTO ──────────────────
    def test_riga222_assegnare_un_turnover_gia_PRONTO_e_un_RIFIUTO_che_dice_lo_stato(self):
        g = self._gestore()
        tid = g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        self.assertTrue(g.completa(tid).ok)
        e = g.assegna(tid, "addetto1")
        self.assertIs(False, e.ok, "un turnover PRONTO e' tornato in lavorazione")
        self.assertEqual("transizione_non_valida", e.motivo)
        self.assertEqual("pronto", e.stato)
        self.assertEqual("pronto", self._stato(g, tid))

    # ── riga 282: la notifica che esplode lascia LA traccia nel registro ───────────
    def test_riga282_una_notifica_che_esplode_grida_WARNING_con_la_traccia(self):
        def boom(_):
            raise RuntimeError("canale giu'")
        g = self._gestore(orologio=lambda: A + 7200, notificatore=boom)
        g.crea_turnover("casa", "2026-09-10", "2026-09-10")
        with self.assertLogs("core_auto.turnover", level="WARNING") as cm:
            self.assertEqual(1, g.segnala_ritardi())
        self.assertEqual(1, len(cm.records))
        rec = cm.records[0]
        self.assertEqual(logging.WARNING, rec.levelno)
        self.assertIsInstance(rec.exc_info, tuple, "la notifica fallita non lascia la traccia")
        self.assertIs(RuntimeError, rec.exc_info[0])

    # ── riga 323: la connessione in memoria e' condivisa FRA I THREAD ──────────────
    def test_riga323_il_gestore_in_memoria_accetta_lavoro_da_un_altro_thread(self):
        g = self._gestore()
        esiti = []

        def lavoratore():
            try:
                esiti.append(g.crea_turnover("casa", "2026-09-10", "2026-09-10"))
            except Exception as e:
                esiti.append(repr(e))
        th = threading.Thread(target=lavoratore)
        th.start()
        th.join()
        self.assertEqual(1, len(esiti))
        self.assertIsInstance(esiti[0], int, "la connessione in memoria rifiuta un altro thread: %r"
                              % (esiti[0],))
        self.assertEqual("da_fare", self._stato(g, esiti[0]))


if __name__ == "__main__":
    unittest.main()
