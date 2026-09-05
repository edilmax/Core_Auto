"""
Test Fase 58 - Channel Manager / Inventario host in tempo reale (anti-overbooking).

Copre: set disponibilita' + fail-closed, lettura disponibile() (firma provider vetrina),
blocco atomico, idempotenza (replay), rifiuti (pieno/chiuso/min_notti/giorno assente),
multi-notte all-or-nothing, rilascio idempotente, ingest esterno (anti-overbooking
cross-canale), parser comandi blindato, comandi applicati, notifica isolata, e lo
STRESS concorrente: N thread sulla STESSA notte da 1 unita' -> esattamente 1 vince
(zero doppie vendite), ripetuto 10x.
"""
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest

from fase58_channel_manager import (
    MAX_UNITA, ChannelManager, ComandoHost, EsitoComando, EsitoPrenotazione,
    crea_channel_manager, interpreta_comando, notti,
)


def _cm():
    return crea_channel_manager()


def _carica(cm, alloggio="a", giorni=("2026-07-01", "2026-07-02", "2026-07-03"),
            unita=1, prezzo=10000, chiuso=False, min_notti=1):
    for g in giorni:
        assert cm.imposta_disponibilita(alloggio, g, unita_totali=unita,
                                        prezzo_netto_cents=prezzo, chiuso=chiuso,
                                        min_notti=min_notti)


class TestNotti(unittest.TestCase):
    def test_semiaperto(self):
        self.assertEqual(notti("2026-07-01", "2026-07-03"),
                         ["2026-07-01", "2026-07-02"])

    def test_invalide(self):
        self.assertIsNone(notti("2026-07-03", "2026-07-01"))
        self.assertIsNone(notti("x", "y"))
        self.assertIsNone(notti("2026-07-01", "2026-07-01"))


class TestDisponibilita(unittest.TestCase):
    def setUp(self):
        self.cm = _cm()

    def test_set_e_stato(self):
        self.assertTrue(self.cm.imposta_disponibilita("a", "2026-07-01",
                        unita_totali=3, prezzo_netto_cents=12000))
        s = self.cm.stato_giorno("a", "2026-07-01")
        self.assertEqual(s["unita_totali"], 3)
        self.assertEqual(s["prezzo_netto_cents"], 12000)

    def test_prezzo_float_rifiutato(self):
        self.assertFalse(self.cm.imposta_disponibilita("a", "2026-07-01",
                         unita_totali=1, prezzo_netto_cents=120.0))

    def test_unita_negativa_rifiutata(self):
        self.assertFalse(self.cm.imposta_disponibilita("a", "2026-07-01",
                         unita_totali=-1, prezzo_netto_cents=100))

    def test_data_invalida_rifiutata(self):
        self.assertFalse(self.cm.imposta_disponibilita("a", "non-data",
                         unita_totali=1, prezzo_netto_cents=100))

    def test_non_scende_sotto_occupato(self):
        _carica(self.cm, unita=2)
        self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        # 1 occupato quel giorno -> non posso impostare totali=0
        self.assertFalse(self.cm.imposta_disponibilita("a", "2026-07-01",
                         unita_totali=0, prezzo_netto_cents=100))

    def test_disponibile_provider(self):
        _carica(self.cm, unita=1)
        self.assertTrue(self.cm.disponibile("a", "2026-07-01", "2026-07-03"))
        self.assertIsNone(self.cm.disponibile("a", "bad", "bad"))
        # giorno non caricato -> non disponibile (fail-closed)
        self.assertFalse(self.cm.disponibile("a", "2026-07-01", "2026-07-10"))


class TestBlocco(unittest.TestCase):
    def setUp(self):
        self.cm = _cm()
        _carica(self.cm, unita=1)

    def test_blocco_ok_scala(self):
        e = self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertTrue(e.ok)
        self.assertEqual(self.cm.stato_giorno("a", "2026-07-01")["unita_occupate"], 1)
        self.assertFalse(self.cm.disponibile("a", "2026-07-01", "2026-07-02"))

    def test_idempotenza_replay(self):
        e1 = self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        e2 = self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertTrue(e1.ok and e2.ok)
        self.assertTrue(e2.idempotente)
        # NON scala due volte
        self.assertEqual(self.cm.stato_giorno("a", "2026-07-01")["unita_occupate"], 1)

    def test_rifiuto_pieno(self):
        self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        e = self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k2")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "pieno")

    def test_rifiuto_chiuso(self):
        self.cm.applica_comando("CHIUDI a 2026-07-01")
        e = self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "chiuso")

    def test_rifiuto_min_notti(self):
        cm = _cm()
        _carica(cm, unita=1, min_notti=2)
        e = cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")  # 1 notte
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "min_notti")

    def test_rifiuto_giorno_non_caricato(self):
        e = self.cm.blocca("a", "2026-08-01", "2026-08-02", idem_key="k1")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "giorno_non_caricato")

    def test_date_non_valide(self):
        e = self.cm.blocca("a", "2026-07-03", "2026-07-01", idem_key="k1")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "date_non_valide")

    def test_idem_key_mancante(self):
        e = self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="")
        self.assertFalse(e.ok)

    def test_multinotte_all_or_nothing(self):
        cm = _cm()
        # notte 1 libera, notte 2 piena
        cm.imposta_disponibilita("a", "2026-07-01", unita_totali=1, prezzo_netto_cents=100)
        cm.imposta_disponibilita("a", "2026-07-02", unita_totali=1, prezzo_netto_cents=100)
        cm.blocca("a", "2026-07-02", "2026-07-03", idem_key="occupa2")  # riempi notte 2
        e = cm.blocca("a", "2026-07-01", "2026-07-03", idem_key="k1")   # spana 1+2
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "pieno")
        # notte 1 NON deve essere stata scalata (atomicita')
        self.assertEqual(cm.stato_giorno("a", "2026-07-01")["unita_occupate"], 0)


class TestRilascioEsterno(unittest.TestCase):
    def setUp(self):
        self.cm = _cm()
        _carica(self.cm, unita=1)

    def test_rilascio_libera(self):
        self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        e = self.cm.rilascia("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertTrue(e.ok)
        self.assertEqual(self.cm.stato_giorno("a", "2026-07-01")["unita_occupate"], 0)
        self.assertTrue(self.cm.disponibile("a", "2026-07-01", "2026-07-02"))

    def test_rilascio_idempotente(self):
        self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.cm.rilascia("a", "2026-07-01", "2026-07-02", idem_key="k1")
        e = self.cm.rilascia("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertTrue(e.idempotente)
        self.assertEqual(self.cm.stato_giorno("a", "2026-07-01")["unita_occupate"], 0)

    def test_rilascio_senza_blocco(self):
        e = self.cm.rilascia("a", "2026-07-01", "2026-07-02", idem_key="mai")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "blocco_inesistente")

    def test_evento_esterno_anti_overbooking(self):
        # una prenotazione da un'altra OTA consuma l'unica unita' -> la nostra rifiuta
        e_ext = self.cm.registra_evento_esterno("a", "2026-07-01", "2026-07-02",
                                                idem_key="BK123", fonte="booking")
        self.assertTrue(e_ext.ok)
        e_noi = self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="nostra")
        self.assertFalse(e_noi.ok)
        self.assertEqual(e_noi.motivo, "pieno")

    def test_evento_esterno_idempotente(self):
        self.cm.registra_evento_esterno("a", "2026-07-01", "2026-07-02",
                                        idem_key="BK1", fonte="booking")
        e = self.cm.registra_evento_esterno("a", "2026-07-01", "2026-07-02",
                                            idem_key="BK1", fonte="booking")
        self.assertTrue(e.idempotente)
        self.assertEqual(self.cm.stato_giorno("a", "2026-07-01")["unita_occupate"], 1)


class TestElencoPrenotazioni(unittest.TestCase):
    def setUp(self):
        self.cm = _cm()
        _carica(self.cm, unita=2)

    def test_elenco_e_rimborso(self):
        self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.cm.blocca("a", "2026-07-02", "2026-07-03", idem_key="k2")
        el = self.cm.elenco_prenotazioni()
        self.assertEqual(len(el), 2)
        self.assertFalse(el[0]["rimborsato"])
        self.assertIn("idem_key", el[0])
        # rimborso (rilascio) -> ora risulta rimborsato
        self.cm.rilascia("a", "2026-07-01", "2026-07-02", idem_key="k1")
        el2 = self.cm.elenco_prenotazioni()
        rim = {e["idem_key"]: e["rimborsato"] for e in el2}
        self.assertTrue(rim["k1"])
        self.assertFalse(rim["k2"])

    def test_filtro_alloggio(self):
        self.cm.imposta_disponibilita("b", "2026-07-01", unita_totali=1,
                                      prezzo_netto_cents=100)
        self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="ka")
        self.cm.blocca("b", "2026-07-01", "2026-07-02", idem_key="kb")
        self.assertEqual(len(self.cm.elenco_prenotazioni(alloggio_id="b")), 1)

    def test_solo_occupati(self):
        # un rifiuto (pieno) non deve comparire
        self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k2")  # ok (2 unita)
        self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k3")  # pieno -> rifiutato
        self.assertEqual(len(self.cm.elenco_prenotazioni()), 2)


class TestMetriche(unittest.TestCase):
    def test_revenue_e_occupazione(self):
        cm = _cm()
        # 3 notti a 10000, capienza 1 ciascuna
        for g in ("2026-07-01", "2026-07-02", "2026-07-03"):
            cm.imposta_disponibilita("a", g, unita_totali=1, prezzo_netto_cents=10000)
        cm.blocca("a", "2026-07-01", "2026-07-03", idem_key="k1")   # occupa 2 notti
        m = cm.metriche(alloggio_id="a")
        self.assertEqual(m["notti_totali"], 3)
        self.assertEqual(m["notti_occupate"], 2)
        self.assertEqual(m["revenue_cents"], 20000)                  # 2 x 10000
        self.assertEqual(m["occupazione_bps"], 2 * 10000 // 3)       # ~66.6%

    def test_periodo(self):
        cm = _cm()
        for g in ("2026-07-01", "2026-08-01"):
            cm.imposta_disponibilita("a", g, unita_totali=1, prezzo_netto_cents=5000)
        m = cm.metriche(alloggio_id="a", da="2026-07-01", a="2026-07-31")
        self.assertEqual(m["giorni"], 1)                             # solo luglio

    def test_vuoto(self):
        m = _cm().metriche(alloggio_id="mai")
        self.assertEqual(m["revenue_cents"], 0)
        self.assertEqual(m["occupazione_bps"], 0)


class TestCalendario(unittest.TestCase):
    def test_stati(self):
        cm = _cm()
        cm.imposta_disponibilita("a", "2026-07-01", unita_totali=1, prezzo_netto_cents=9000)
        cm.imposta_disponibilita("a", "2026-07-02", unita_totali=1, prezzo_netto_cents=9000)
        cm.applica_comando("CHIUDI a 2026-07-02")
        cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")    # 01 pieno
        cal = cm.calendario("a", "2026-07-01", "2026-07-04")
        stati = {c["giorno"]: c["stato"] for c in cal}
        self.assertEqual(stati["2026-07-01"], "pieno")
        self.assertEqual(stati["2026-07-02"], "chiuso")
        self.assertEqual(stati["2026-07-03"], "non_caricato")

    def test_date_invalide(self):
        self.assertEqual(_cm().calendario("a", "2026-07-03", "2026-07-01"), [])


class TestComandi(unittest.TestCase):
    def setUp(self):
        self.cm = _cm()

    def test_parser_valido(self):
        c = interpreta_comando("CHIUDI casa 2026-07-01")
        self.assertEqual((c.azione, c.alloggio_id, c.giorno), ("chiudi", "casa", "2026-07-01"))
        d = interpreta_comando("DISPO casa 2026-07-01 5")
        self.assertEqual((d.azione, d.valore), ("dispo", 5))

    def test_parser_robusto(self):
        for bad in (None, 123, "", "CHIUDI", "DISPO casa 2026-07-01 abc",
                    "CHIUDI casa data-storta", "PIPPO casa 2026-07-01"):
            self.assertIsNone(interpreta_comando(bad))

    def test_applica_dispo_e_prezzo(self):
        self.assertTrue(self.cm.applica_comando("DISPO a 2026-07-01 4").ok)
        self.assertTrue(self.cm.applica_comando("PREZZO a 2026-07-01 13000").ok)
        s = self.cm.stato_giorno("a", "2026-07-01")
        self.assertEqual((s["unita_totali"], s["prezzo_netto_cents"]), (4, 13000))

    def test_applica_chiudi_apri(self):
        _carica(self.cm, unita=1, giorni=("2026-07-01",))
        self.assertTrue(self.cm.applica_comando("CHIUDI a 2026-07-01").ok)
        self.assertFalse(self.cm.disponibile("a", "2026-07-01", "2026-07-02"))
        self.assertTrue(self.cm.applica_comando("APRI a 2026-07-01").ok)
        self.assertTrue(self.cm.disponibile("a", "2026-07-01", "2026-07-02"))

    def test_comando_ignoto(self):
        e = self.cm.applica_comando("BLABLA")
        self.assertFalse(e.ok)
        self.assertEqual(e.azione, "ignoto")


class TestNotifica(unittest.TestCase):
    def test_notifica_su_nuovo_blocco(self):
        ricevute = []
        cm = crea_channel_manager(notificatore=ricevute.append)
        _carica(cm, unita=1)
        cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertEqual(len(ricevute), 1)
        self.assertEqual(ricevute[0]["tipo"], "nuova_prenotazione")
        # replay: NESSUNA nuova notifica
        cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertEqual(len(ricevute), 1)

    def test_notifica_isolata_se_solleva(self):
        def boom(_):
            raise RuntimeError("canale giu'")
        cm = crea_channel_manager(notificatore=boom)
        _carica(cm, unita=1)
        e = cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertTrue(e.ok)  # la prenotazione resta valida nonostante la notifica giu'


class TestStressOverbooking(unittest.TestCase):
    def test_nessuna_doppia_vendita_10x(self):
        """10 ripetizioni: 1 unita', 24 thread prenotano la STESSA notte -> 1 solo ok."""
        for rip in range(10):
            d = tempfile.mkdtemp()
            try:
                path = os.path.join(d, f"cm{rip}.db")
                cm = crea_channel_manager(path)
                cm.imposta_disponibilita("a", "2026-07-01", unita_totali=1,
                                         prezzo_netto_cents=10000)
                esiti = []
                lock = threading.Lock()

                def prenota(i):
                    e = cm.blocca("a", "2026-07-01", "2026-07-02", idem_key=f"key-{i}")
                    with lock:
                        esiti.append(e)

                th = [threading.Thread(target=prenota, args=(i,)) for i in range(24)]
                for t in th:
                    t.start()
                for t in th:
                    t.join()

                ok = [e for e in esiti if e.ok]
                self.assertEqual(len(ok), 1, f"rip {rip}: attesi 1 ok, trovati {len(ok)}")
                self.assertEqual(cm.stato_giorno("a", "2026-07-01")["unita_occupate"], 1)
                self.assertTrue(all(e.motivo == "pieno" for e in esiti if not e.ok))
            finally:
                shutil.rmtree(d, ignore_errors=True)


class TestLeGuardieDeiPuntiScoperti(unittest.TestCase):
    """Una guardia per ogni punto che il Giudice della mutazione ha trovato SCOPERTO col
    solo occhio dedicato (2026-09-05, Blocco 2 casella 4: 83 punti su 147 passavano coi
    test verdi). Ogni test dice quale riga difende, cosi' fra sei mesi si sa perche'.

    Sette punti (righe 76, 79, 180, 396 x3, 399) erano mascherati da un controllo
    RIDONDANTE nella stessa funzione e nessun test poteva distinguerli: il 2026-09-05, con
    l'«autorizzato» del fondatore, quelle righe sono state RISCRITTE con una condizione sola
    (`notti`: `n < 1`; `cancella_alloggio`: `max(0, rowcount)`; `prima_finestra`: quattro
    controlli separati e `n > span`), cosi' ogni guasto e' visibile e le guardie qui sotto lo
    prendono. Nessuna dichiarazione di equivalenza resta per questo modulo.
    """

    # ── notti() ─────────────────────────────────────────────────────────────────
    def test_una_data_sola_invalida_da_None_senza_sollevare(self):
        # riga 76: `ci is None OR co is None OR ci >= co` -- con `and` una sola data
        # invalida farebbe confrontare None con una data (TypeError).
        self.assertIsNone(notti("x", "2026-07-03"))
        self.assertIsNone(notti("2026-07-01", "y"))

    def test_il_tetto_delle_notti_e_incluso_e_una_in_piu_e_rifiutata(self):
        # riga 79: `n > MAX_NOTTI` -- 366 notti passano, 367 no (con `and` il tetto sparirebbe).
        self.assertEqual(len(notti("2026-01-01", "2027-01-02")), 366)
        self.assertIsNone(notti("2026-01-01", "2027-01-03"))

    # ── esiti congelati ─────────────────────────────────────────────────────────
    def test_gli_esiti_e_il_comando_sono_congelati(self):
        # righe 87, 95, 102: `frozen=True` -- un esito che si puo' riscrivere dopo non
        # e' un esito.
        from dataclasses import FrozenInstanceError
        for oggetto, campo in ((EsitoPrenotazione(True, ""), "ok"),
                               (EsitoComando(True, "chiudi"), "ok"),
                               (ComandoHost("chiudi", "a", "2026-07-01"), "azione")):
            with self.subTest(tipo=type(oggetto).__name__):
                with self.assertRaises(FrozenInstanceError):
                    setattr(oggetto, campo, "cambiato")

    def test_un_blocco_nuovo_non_e_un_replay(self):
        # riga 91: `idempotente: bool = False` -- il primo blocco non e' un replay.
        cm = _cm()
        _carica(cm, unita=1)
        e = cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertTrue(e.ok)
        self.assertIs(e.idempotente, False)

    # ── cancella / conta ────────────────────────────────────────────────────────
    def test_un_identificativo_non_testuale_non_cancella_e_non_conta_senza_sollevare(self):
        # righe 173 e 185: `isinstance(x, str) AND x` -- con `or` un valore non testuale
        # passerebbe al database (una lista solleva) invece di valere 0.
        cm = _cm()
        _carica(cm, unita=1)
        self.assertEqual(cm.cancella_alloggio(["a"]), 0)
        self.assertEqual(cm.conta_alloggio(["a"]), 0)
        self.assertEqual(cm.conta_alloggio("a"), 3)      # e l'inventario e' intatto

    def test_un_conteggio_negativo_del_database_non_esce_mai(self):
        # riga 180: `cur.rowcount AND cur.rowcount > 0` -- sqlite risponde -1 quando non
        # sa contare: con `or` quel -1 uscirebbe come «righe cancellate».
        base = sqlite3.connect(":memory:", check_same_thread=False)

        class CursoreCieco:
            rowcount = -1

            def __init__(self, cur):
                self._cur = cur

            def __getattr__(self, nome):
                return getattr(self._cur, nome)

        class ConnessioneCieca:
            def __init__(self, con):
                object.__setattr__(self, "_con", con)

            def execute(self, sql, *a):
                cur = self._con.execute(sql, *a)
                return CursoreCieco(cur) if sql.lstrip().upper().startswith("DELETE") else cur

            def close(self):
                pass

            def __enter__(self):
                return self._con.__enter__()

            def __exit__(self, *a):
                return self._con.__exit__(*a)

            def __getattr__(self, nome):
                return getattr(self._con, nome)

            def __setattr__(self, nome, valore):
                setattr(self._con, nome, valore)

        cm = ChannelManager(lambda: ConnessioneCieca(base))
        _carica(cm, unita=1)
        self.assertEqual(cm.cancella_alloggio("a"), 0)

    # ── imposta_disponibilita ───────────────────────────────────────────────────
    def test_alloggio_non_testuale_o_vuoto_rifiutato_senza_scrivere(self):
        # righe 201-202: `not isinstance OR not strip()` -> False; con `and` un None
        # solleverebbe, con `return True` un nome vuoto verrebbe accettato senza scrivere.
        cm = _cm()
        self.assertFalse(cm.imposta_disponibilita(None, "2026-07-01", unita_totali=1,
                                                  prezzo_netto_cents=100))
        self.assertFalse(cm.imposta_disponibilita("   ", "2026-07-01", unita_totali=1,
                                                  prezzo_netto_cents=100))
        self.assertIsNone(cm.stato_giorno("   ", "2026-07-01"))

    def test_unita_non_intere_o_oltre_il_tetto_rifiutate(self):
        # riga 205: `_intero(u) AND 0 <= u <= MAX_UNITA` -- con `or` ne basterebbe una.
        cm = _cm()
        for u in (1.0, MAX_UNITA + 1):
            with self.subTest(unita=u):
                self.assertFalse(cm.imposta_disponibilita("a", "2026-07-01", unita_totali=u,
                                                          prezzo_netto_cents=100))
        self.assertIsNone(cm.stato_giorno("a", "2026-07-01"))

    def test_min_notti_zero_o_non_intero_rifiutato_senza_scrivere(self):
        # righe 209-210: `_intero(min_notti) AND 1 <= min_notti <= MAX_NOTTI` -> False.
        cm = _cm()
        for mn in (0, 1.5):
            with self.subTest(min_notti=mn):
                self.assertFalse(cm.imposta_disponibilita("a", "2026-07-01", unita_totali=1,
                                                          prezzo_netto_cents=100, min_notti=mn))
        self.assertIsNone(cm.stato_giorno("a", "2026-07-01"))

    def test_totali_pari_alle_occupate_sono_ammessi(self):
        # riga 219: `unita_totali < occupate` -- pareggiare le unita' all'occupato e' lecito.
        cm = _cm()
        _carica(cm, unita=2, giorni=("2026-07-01",))
        self.assertTrue(cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1").ok)
        self.assertTrue(cm.imposta_disponibilita("a", "2026-07-01", unita_totali=1,
                                                 prezzo_netto_cents=100))
        self.assertEqual(cm.stato_giorno("a", "2026-07-01")["unita_totali"], 1)

    # ── lo specchio del prezzo ──────────────────────────────────────────────────
    def test_lo_specchio_collegato_viene_avvisato_e_se_esplode_resta_la_traccia(self):
        # riga 277: `self._specchio is None` -> con `is not` lo specchio collegato non
        # verrebbe mai avvisato; riga 288: `exc_info=True` -- l'errore porta la traccia.
        cm = _cm()
        avvisati = []
        cm.collega_specchio(avvisati.append)
        self.assertTrue(cm.imposta_disponibilita("a", "2026-07-01", unita_totali=1,
                                                 prezzo_netto_cents=100))
        self.assertEqual(avvisati, ["a"])

        def esplode(_):
            raise RuntimeError("vetrina giu'")
        cm.collega_specchio(esplode)
        with self.assertLogs("core_auto.channel_manager", level="ERROR") as registro:
            self.assertTrue(cm.imposta_disponibilita("a", "2026-07-02", unita_totali=1,
                                                     prezzo_netto_cents=100))
        traccia = registro.records[0].exc_info
        self.assertIsInstance(traccia, tuple)
        self.assertIs(traccia[0], RuntimeError)

    # ── prezzo_minimo_prenotabile ───────────────────────────────────────────────
    def test_il_prezzo_minimo_salta_i_giorni_chiusi_pieni_e_gratis(self):
        # righe 311, 313, 316: chiuso -> salta; totali - occupate <= 0 -> salta;
        # prezzo <= 0 -> salta. Resta solo il giorno che un ospite puo' comprare.
        cm = _cm()
        cm.imposta_disponibilita("a", "2026-07-01", unita_totali=1, prezzo_netto_cents=50,
                                 chiuso=True)                                   # chiuso
        cm.imposta_disponibilita("a", "2026-07-02", unita_totali=1, prezzo_netto_cents=60)
        cm.blocca("a", "2026-07-02", "2026-07-03", idem_key="pieno")            # pieno
        cm.imposta_disponibilita("a", "2026-07-03", unita_totali=1, prezzo_netto_cents=0)  # gratis
        cm.imposta_disponibilita("a", "2026-07-04", unita_totali=1, prezzo_netto_cents=100)
        self.assertEqual(cm.prezzo_minimo_prenotabile("a", "2026-07-01", "2026-07-04"), 100)

    # ── _muta_giorno (comandi) ──────────────────────────────────────────────────
    def test_dispo_pari_all_occupato_e_lecita_e_sotto_e_rifiutata_senza_scrivere(self):
        # righe 338 e 340: `unita_totali < unita_occupate` -> rifiuto (False, e non
        # scrive); il pareggio passa.
        cm = _cm()
        _carica(cm, unita=2, giorni=("2026-07-01",))
        cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertTrue(cm.applica_comando("DISPO a 2026-07-01 1").ok)
        self.assertFalse(cm.applica_comando("DISPO a 2026-07-01 0").ok)
        self.assertEqual(cm.stato_giorno("a", "2026-07-01")["unita_totali"], 1)

    # ── disponibile: soggiorno minimo ───────────────────────────────────────────
    def test_il_soggiorno_minimo_e_quello_della_prima_notte(self):
        # righe 380-381: `i == 0 and len(notti) < min_notti` -> False. Conta la PRIMA notte.
        cm = _cm()
        cm.imposta_disponibilita("a", "2026-07-01", unita_totali=1, prezzo_netto_cents=100,
                                 min_notti=3)
        cm.imposta_disponibilita("a", "2026-07-02", unita_totali=1, prezzo_netto_cents=100,
                                 min_notti=1)
        self.assertFalse(cm.disponibile("a", "2026-07-01", "2026-07-03"))   # 2 notti < 3
        cm.imposta_disponibilita("a", "2026-07-01", unita_totali=1, prezzo_netto_cents=100,
                                 min_notti=1)
        cm.imposta_disponibilita("a", "2026-07-02", unita_totali=1, prezzo_netto_cents=100,
                                 min_notti=3)
        self.assertTrue(cm.disponibile("a", "2026-07-01", "2026-07-03"))    # la seconda non conta

    # ── prima_finestra ──────────────────────────────────────────────────────────
    def test_la_prima_finestra_e_la_prima_disponibile_e_prova_anche_l_ultimo_giorno(self):
        # righe 396 (`is None`, `or`), 399 (`span > 120`, `or`), 403 (`d <= ultimo`),
        # 406 (`is True`): la finestra e' la prima DISPONIBILE, l'ultimo inizio possibile
        # si prova, 120 giorni di ampiezza passano e 121 no, una data invalida da None.
        cm = _cm()
        cm.imposta_disponibilita("a", "2026-01-01", unita_totali=1, prezzo_netto_cents=100,
                                 chiuso=True)                                   # non disponibile
        cm.imposta_disponibilita("a", "2026-04-30", unita_totali=1, prezzo_netto_cents=100)
        self.assertEqual(cm.prima_finestra("a", "2026-01-01", "2026-05-01", 1),
                         ("2026-04-30", "2026-05-01"))                          # 120 giorni
        self.assertIsNone(cm.prima_finestra("a", "2026-01-01", "2026-05-02", 1))  # 121 giorni
        self.assertIsNone(cm.prima_finestra("a", "x", "2026-05-01", 1))
        self.assertIsNone(cm.prima_finestra("a", "2026-01-01", "y", 1))

    def test_una_finestra_di_zero_notti_non_e_disponibile_ne_indisponibile(self):
        # `disponibile` con arrivo e partenza uguali risponde None (non True): zero notti non
        # sono ne' libere ne' occupate.
        cm = _cm()
        _carica(cm, unita=1)
        self.assertIsNone(cm.disponibile("a", "2026-07-01", "2026-07-01"))

    def test_la_finestra_larga_quanto_il_periodo_ci_sta_e_una_in_piu_no(self):
        # righe 396-402 riscritte: `n > span` -> None; n == span e' l'unica finestra possibile;
        # un periodo di UN giorno con n == 1 la trova; n == 0 non e' una finestra.
        cm = _cm()
        _carica(cm, unita=1, giorni=("2026-07-01", "2026-07-02"))
        self.assertEqual(cm.prima_finestra("a", "2026-07-01", "2026-07-03", 2),
                         ("2026-07-01", "2026-07-03"))
        self.assertIsNone(cm.prima_finestra("a", "2026-07-01", "2026-07-03", 3))
        self.assertEqual(cm.prima_finestra("a", "2026-07-01", "2026-07-02", 1),
                         ("2026-07-01", "2026-07-02"))
        self.assertIsNone(cm.prima_finestra("a", "2026-07-01", "2026-07-03", 0))
        self.assertIsNone(cm.prima_finestra("a", "2026-07-01", "2026-07-01", 1))

    def test_stato_range_rifiuta_anche_una_sola_data_invalida(self):
        # riga 426: `da is None OR a is None` -> {}. Con `and` una fine invalida farebbe
        # passare un BETWEEN aperto; con `is not` le date buone darebbero {}.
        cm = _cm()
        _carica(cm, unita=1)
        self.assertEqual(len(cm.stato_range("a", "2026-07-01", "2026-07-03")), 3)
        self.assertEqual(cm.stato_range("a", "2026-07-01", "x"), {})
        self.assertEqual(cm.stato_range("a", "x", "2026-07-03"), {})

    # ── elenco_prenotazioni (admin) ─────────────────────────────────────────────
    def test_elenco_con_limite_finto_e_filtro_vuoto_da_tutto(self):
        # riga 441: `limit` intero, non bool, in 1..500, altrimenti 50; riga 448:
        # `isinstance(alloggio_id, str) AND alloggio_id` -- un filtro vuoto non filtra.
        cm = _cm()
        _carica(cm, unita=2)
        cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        cm.blocca("a", "2026-07-02", "2026-07-03", idem_key="k2")
        self.assertEqual(len(cm.elenco_prenotazioni(limit=True)), 2)
        self.assertEqual(len(cm.elenco_prenotazioni(alloggio_id="")), 2)

    # ── pagina e conteggio della dashboard host ─────────────────────────────────
    def _tre_prenotazioni_due_vive(self):
        cm = _cm()
        _carica(cm, unita=2)
        cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="viva1")
        cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="viva2")
        cm.blocca("a", "2026-07-02", "2026-07-03", idem_key="chiusa")
        cm.rilascia("a", "2026-07-02", "2026-07-03", idem_key="chiusa")
        return cm

    def test_attive_e_archivio_sono_viste_diverse_e_dicono_il_vero_sul_rimborso(self):
        # righe 478, 502, 526, 544: 'attive' = senza rilascio, 'archivio' = rilasciate;
        # una vista sconosciuta vale 'attive'; `rimborsato` segue la vista.
        cm = self._tre_prenotazioni_due_vive()
        attive = cm.elenco_prenotazioni_pagina(alloggi=["a"], vista="attive")
        archivio = cm.elenco_prenotazioni_pagina(alloggi=["a"], vista="archivio")
        self.assertEqual({r["idem_key"] for r in attive}, {"viva1", "viva2"})
        self.assertEqual([r["idem_key"] for r in archivio], ["chiusa"])
        self.assertIs(attive[0]["rimborsato"], False)
        self.assertIs(archivio[0]["rimborsato"], True)
        self.assertEqual(cm.conta_prenotazioni(alloggi=["a"], vista="attive"), 2)
        self.assertEqual(cm.conta_prenotazioni(alloggi=["a"], vista="archivio"), 1)
        boh = cm.elenco_prenotazioni_pagina(alloggi=["a"], vista="boh")
        self.assertEqual({r["idem_key"] for r in boh}, {"viva1", "viva2"})
        self.assertEqual(cm.conta_prenotazioni(alloggi=["a"], vista="boh"), 2)

    def test_limite_e_scarto_finti_nella_pagina_valgono_i_default(self):
        # righe 528 e 530: limit/offset bool -> default 10 e 0 (True varrebbe 1).
        cm = self._tre_prenotazioni_due_vive()
        self.assertEqual(len(cm.elenco_prenotazioni_pagina(alloggi=["a"], limit=True)), 2)
        self.assertEqual(len(cm.elenco_prenotazioni_pagina(alloggi=["a"], offset=True)), 2)

    def test_alloggi_ed_esclusioni_non_testuali_vengono_scartati_senza_sollevare(self):
        # righe 487 e 493: `isinstance(x, str) AND x` -- con `or` una lista passerebbe al
        # database e solleverebbe.
        cm = self._tre_prenotazioni_due_vive()
        self.assertEqual(cm.conta_prenotazioni(alloggi=[["a"]]), 0)
        self.assertEqual(len(cm.elenco_prenotazioni_pagina(alloggi=["a"],
                                                           escludi_idem=[["x"]])), 2)

    # ── metriche ────────────────────────────────────────────────────────────────
    def test_le_metriche_ignorano_filtri_vuoti_o_non_testuali_senza_sollevare(self):
        # righe 552, 555, 558: `isinstance(x, str) AND x` -- con `or` una lista andrebbe
        # al database (solleva) e un alloggio vuoto filtrerebbe via tutto.
        cm = _cm()
        _carica(cm, unita=1)
        self.assertEqual(cm.metriche()["giorni"], 3)
        self.assertEqual(cm.metriche(alloggio_id="")["giorni"], 3)
        self.assertEqual(cm.metriche(alloggio_id=["a"])["giorni"], 3)
        self.assertEqual(cm.metriche(da=["2026-07-01"])["giorni"], 3)
        self.assertEqual(cm.metriche(a=["2026-07-03"])["giorni"], 3)

    # ── calendario ──────────────────────────────────────────────────────────────
    def test_venduta_vince_su_chiusa_e_zero_unita_e_pieno(self):
        # righe 602, 603, 607: 1/1 e chiusa -> 'pieno' (la vendita non si nasconde);
        # 0 unita' chiusa -> 'chiuso'; 0 unita' aperta -> 'pieno'.
        cm = _cm()
        cm.imposta_disponibilita("a", "2026-07-01", unita_totali=1, prezzo_netto_cents=100)
        cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        cm.applica_comando("CHIUDI a 2026-07-01")
        cm.imposta_disponibilita("a", "2026-07-02", unita_totali=0, prezzo_netto_cents=100,
                                 chiuso=True)
        cm.imposta_disponibilita("a", "2026-07-03", unita_totali=0, prezzo_netto_cents=100)
        stati = {c["giorno"]: c["stato"] for c in cm.calendario("a", "2026-07-01", "2026-07-04")}
        self.assertEqual(stati, {"2026-07-01": "pieno", "2026-07-02": "chiuso",
                                 "2026-07-03": "pieno"})

    # ── rilascia ────────────────────────────────────────────────────────────────
    def test_il_rilascio_con_date_invalide_dice_no_e_il_secondo_rilascio_dice_si(self):
        # righe 699 e 709.
        cm = _cm()
        _carica(cm, unita=1)
        self.assertFalse(cm.rilascia("a", "2026-07-03", "2026-07-01", idem_key="k1").ok)
        cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertTrue(cm.rilascia("a", "2026-07-01", "2026-07-02", idem_key="k1").ok)
        secondo = cm.rilascia("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertTrue(secondo.ok)
        self.assertTrue(secondo.idempotente)

    # ── orfani / libera_orfani ──────────────────────────────────────────────────
    def test_gli_orfani_sono_i_blocchi_senza_pendente_e_una_riga_monca_non_conta(self):
        # righe 743, 746, 761: `idem_validi or ()`; `ora_ts` intero non-bool altrimenti
        # «adesso»; `idem not in validi AND check_in AND check_out`.
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "orfani.db")
        cm = crea_channel_manager(path)
        _carica(cm, unita=2)
        cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="con_pendente")
        cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="orfano")
        con = sqlite3.connect(path)
        con.execute("INSERT INTO movimenti (idem_key, alloggio_id, tipo, esito, check_in, "
                    "check_out, origine, ts) VALUES ('monco', 'a', 'blocco', 'occupato', "
                    "NULL, '2026-07-02', '', '2020-01-01T00:00:00')")
        con.commit()
        con.close()
        futuro = int(time.time()) + 10 * 24 * 3600
        trovati = [o["idem_key"] for o in cm.orfani(["con_pendente"], ora_ts=futuro,
                                                    grazia_sec=0)]
        self.assertEqual(trovati, ["orfano"])
        time.sleep(1.1)      # un secondo intero dopo il blocco: «adesso» lo vede
        trovati2 = [o["idem_key"] for o in cm.orfani(["con_pendente"], ora_ts=True,
                                                     grazia_sec=0)]
        self.assertEqual(trovati2, ["orfano"])

    def test_libera_orfani_conta_solo_i_rilasci_riusciti_e_isola_chi_esplode(self):
        # righe 772 e 776: un rilascio che non risponde non e' «liberato»; uno che
        # esplode viene isolato e l'avviso porta la traccia vera.
        cm = _cm()
        _carica(cm, unita=1)
        cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="orfano")
        futuro = int(time.time()) + 10 * 24 * 3600
        cm.rilascia = lambda *a, **k: None
        self.assertEqual(cm.libera_orfani([], ora_ts=futuro, grazia_sec=0), [])

        def esplode(*a, **k):
            raise RuntimeError("db giu'")
        cm.rilascia = esplode
        with self.assertLogs("core_auto.channel_manager", level="WARNING") as registro:
            self.assertEqual(cm.libera_orfani([], ora_ts=futuro, grazia_sec=0), [])
        traccia = registro.records[0].exc_info
        self.assertIsInstance(traccia, tuple)
        self.assertIs(traccia[0], RuntimeError)

    # ── applica_comando / notifica ──────────────────────────────────────────────
    def test_un_azione_non_supportata_e_un_errore_interno_dicono_no_e_lasciano_traccia(self):
        # righe 804, 807, 808: l'azione ignota (stato impossibile costruito a mano, D19)
        # -> False; un'eccezione dentro -> isolata, False, con la traccia nel registro.
        import fase58_channel_manager as modulo
        cm = _cm()
        originale = modulo.interpreta_comando
        modulo.interpreta_comando = lambda testo: ComandoHost("boh", "a", "2026-07-01")
        try:
            e = cm.applica_comando("qualunque")
        finally:
            modulo.interpreta_comando = originale
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "azione_non_supportata")

        def esplode(*a, **k):
            raise RuntimeError("db giu'")
        cm._muta_giorno = esplode
        with self.assertLogs("core_auto.channel_manager", level="ERROR") as registro:
            e2 = cm.applica_comando("CHIUDI a 2026-07-01")
        self.assertFalse(e2.ok)
        self.assertEqual(e2.motivo, "errore_interno")
        traccia = registro.records[0].exc_info
        self.assertIsInstance(traccia, tuple)
        self.assertIs(traccia[0], RuntimeError)

    def test_la_notifica_che_esplode_lascia_la_traccia(self):
        # riga 826: `exc_info=True`.
        def boom(_):
            raise RuntimeError("canale giu'")
        cm = crea_channel_manager(notificatore=boom)
        _carica(cm, unita=1)
        with self.assertLogs("core_auto.channel_manager", level="WARNING") as registro:
            self.assertTrue(cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1").ok)
        traccia = registro.records[0].exc_info
        self.assertIsInstance(traccia, tuple)
        self.assertIs(traccia[0], RuntimeError)

    # ── parser dei comandi ──────────────────────────────────────────────────────
    def test_il_parser_pretende_quattro_parti_solo_per_dispo_e_prezzo(self):
        # riga 848: `azione in (dispo, prezzo) AND len == 4` -- con `or` un DISPO a tre
        # parti solleverebbe (IndexError) e un CHIUDI a quattro parti passerebbe.
        self.assertIsNone(interpreta_comando("DISPO casa 2026-07-01"))
        self.assertIsNone(interpreta_comando("CHIUDI casa 2026-07-01 5"))

    def test_i_confini_del_valore_zero_e_tetto_inclusi_negativo_no_tetti_diversi(self):
        # riga 853: `valore < 0 or valore > (MAX_UNITA se dispo, altrimenti MAX_CENTS)`.
        zero = interpreta_comando("DISPO casa 2026-07-01 0")
        self.assertIsNotNone(zero)
        self.assertEqual(zero.valore, 0)
        tetto = interpreta_comando("DISPO casa 2026-07-01 %d" % MAX_UNITA)
        self.assertIsNotNone(tetto)
        self.assertEqual(tetto.valore, MAX_UNITA)
        self.assertIsNone(interpreta_comando("DISPO casa 2026-07-01 -1"))
        self.assertIsNone(interpreta_comando("DISPO casa 2026-07-01 %d" % (MAX_UNITA + 1)))
        prezzo = interpreta_comando("PREZZO casa 2026-07-01 %d" % (MAX_UNITA + 1))
        self.assertIsNotNone(prezzo)
        self.assertEqual(prezzo.valore, MAX_UNITA + 1)

    # ── connessione in memoria ──────────────────────────────────────────────────
    def test_l_inventario_in_memoria_si_usa_da_un_altro_thread(self):
        # riga 886: `check_same_thread=False` -- il server e' a thread.
        cm = _cm()
        _carica(cm, unita=1)
        esiti = []

        def lavoro():
            try:
                esiti.append(cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1").ok)
            except Exception as e:  # pragma: no cover
                esiti.append(repr(e))

        t = threading.Thread(target=lavoro)
        t.start()
        t.join()
        self.assertEqual(esiti, [True])


if __name__ == "__main__":
    unittest.main()
