"""Test Fase 127 - Check-in digitale. SQLite :memory:, emettitore pass finto."""
import sqlite3
import threading
import unittest

from fase127_checkin_digitale import CheckinDigitale, crea_checkin_digitale, valida_ospiti


class PassFinto:
    def emetti(self, pren, alloggio, **kw):
        return "PASS-%s-%s" % (pren, alloggio)


OSP = [{"nome": "Mario Rossi", "documento": "AB12345"}]


def cd():
    c = crea_checkin_digitale(":memory:", PassFinto())
    c.inizializza_schema()
    return c


class TestValida(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(len(valida_ospiti(OSP, 2)), 1)

    def test_oltre_capacita(self):
        self.assertIsNone(valida_ospiti(OSP * 3, 2))

    def test_documento_invalido(self):
        self.assertIsNone(valida_ospiti([{"nome": "X Y", "documento": "!!"}], 2))

    def test_vuoto(self):
        self.assertIsNone(valida_ospiti([], 2))


class TestCheckin(unittest.TestCase):
    def test_flusso_e_sblocco(self):
        c = cd()
        r = c.pre_registra("p1", "casa-1", OSP, 2)
        self.assertTrue(r["ok"])
        self.assertTrue(c.completato("p1"))
        self.assertEqual(c.sblocca("p1", "casa-1"), "PASS-p1-casa-1")

    def test_sblocco_negato_senza_checkin(self):
        c = cd()
        self.assertIsNone(c.sblocca("p1", "casa-1"))        # non pre-registrato

    def test_ospiti_invalidi_no_checkin(self):
        c = cd()
        r = c.pre_registra("p1", "casa-1", [{"nome": "X", "documento": "!!"}], 2)
        self.assertFalse(r["ok"])
        self.assertFalse(c.completato("p1"))

    def test_id_mancante(self):
        c = cd()
        self.assertFalse(c.pre_registra("", "casa-1", OSP, 2)["ok"])

    def test_pass_solleva_isolato(self):
        class Boom:
            def emetti(self, *a, **k):
                raise RuntimeError("pass giu")
        c = crea_checkin_digitale(":memory:", Boom())
        c.inizializza_schema()
        c.pre_registra("p1", "casa-1", OSP, 2)
        self.assertIsNone(c.sblocca("p1", "casa-1"))


class _ConnRotta:
    """Una connessione che lascia creare lo schema e poi ESPLODE su ogni altra query: serve a
    vedere i rami «ISOLATA» dei metodi eseguiti davvero (D19), non solo letti."""
    def __init__(self, con):
        object.__setattr__(self, "_con", con)
        object.__setattr__(self, "rotta", False)

    def execute(self, sql, *a):
        if self.rotta and "CREATE TABLE" not in sql and "PRAGMA" not in sql:
            raise sqlite3.OperationalError("disco in fiamme")
        return self._con.execute(sql, *a)

    def close(self):
        pass

    def __enter__(self):
        return self._con.__enter__()

    def __exit__(self, *a):
        return self._con.__exit__(*a)

    def __getattr__(self, n):
        return getattr(self._con, n)


def _cd_rompibile():
    con = _ConnRotta(sqlite3.connect(":memory:", check_same_thread=False))
    c = CheckinDigitale(lambda: con, PassFinto(), lucchetto=threading.Lock())
    c.inizializza_schema()
    return c, con


class TestIQuattordiciSopravvissutiDellaNotte(unittest.TestCase):
    """Una guardia per ognuno dei 14 punti trovati scoperti dal Giudice la notte del 2026-09-06
    (giudice_notte_blocco3_2.log), vista ROSSA col mutante iniettato con l'editor."""

    LOG = "core_auto.checkin_digitale"

    def _traccia(self, reg, frase):
        rec = [r for r in reg.records if frase in r.getMessage()]
        self.assertEqual(len(rec), 1, [r.getMessage() for r in reg.records])
        self.assertIsInstance(rec[0].exc_info, tuple, "exc_info=True: la traccia c'e', non un False")
        self.assertIs(rec[0].exc_info[0], sqlite3.OperationalError)

    def test_riga46_una_capacita_che_NON_e_un_intero_vero_vale_nessun_limite(self):
        tre = OSP * 3
        self.assertEqual(len(valida_ospiti(tre, "1")), 3, "una stringa non e' una capacita': nessun limite, nessun crash")
        self.assertEqual(len(valida_ospiti(tre, None)), 3)
        self.assertEqual(len(valida_ospiti(tre, True)), 3, "True non e' un intero vero: nessun limite")
        self.assertIsNone(valida_ospiti(tre, 2), "un intero vero limita")

    def test_riga47_il_confine_della_capacita_e_esatto_e_zero_vuol_dire_nessun_limite(self):
        self.assertEqual(len(valida_ospiti(OSP * 2, 2)), 2, "len == cap: dentro")
        self.assertIsNone(valida_ospiti(OSP * 3, 2), "len == cap + 1: fuori")
        self.assertEqual(len(valida_ospiti(OSP * 5, 0)), 5, "cap 0 = nessun limite")
        self.assertEqual(len(valida_ospiti(OSP * 5, -1)), 5, "cap negativo = nessun limite")

    def test_riga119_dopo_la_revoca_il_check_in_NON_e_ok(self):
        c = cd()
        self.assertTrue(c.revoca("p1"))
        esito = c.pre_registra("p1", "casa", OSP, 2)
        self.assertIs(esito["ok"], False)
        self.assertEqual(esito["errore"], "prenotazione_cancellata")
        self.assertFalse(c.completato("p1"))

    def test_riga126_127_pre_registra_col_disco_rotto_risponde_NON_ok_e_lascia_la_traccia(self):
        c, con = _cd_rompibile()
        con.rotta = True
        with self.assertLogs(self.LOG, level="WARNING") as reg:
            esito = c.pre_registra("p1", "casa", OSP, 2)
        self.assertEqual(esito, {"ok": False, "errore": "interno"})
        self.assertIs(esito["ok"], False)
        self._traccia(reg, "pre_registra fallita")

    def test_riga139_140_completato_col_disco_rotto_risponde_False_e_lascia_la_traccia(self):
        c, con = _cd_rompibile()
        self.assertTrue(c.pre_registra("p1", "casa", OSP, 2)["ok"])
        self.assertTrue(c.completato("p1"))
        con.rotta = True
        with self.assertLogs(self.LOG, level="WARNING") as reg:
            self.assertIs(c.completato("p1"), False, "in dubbio, NON completato (fail-closed)")
        self._traccia(reg, "completato: errore DB")

    def test_riga151_152_revoca_vuole_una_stringa_non_vuota(self):
        c = cd()
        for cattivo in (123, None, "", b"p1", ["p1"]):
            self.assertIs(c.revoca(cattivo), False, repr(cattivo))
        self.assertFalse(c.pre_registra("123", "casa", OSP, 2).get("errore") == "prenotazione_cancellata",
                         "revoca(123) non deve aver scritto un tombstone per «123»")
        self.assertTrue(c.revoca("p1"))

    def test_riga169_170_revoca_col_disco_rotto_risponde_False_e_lascia_la_traccia(self):
        c, con = _cd_rompibile()
        con.rotta = True
        with self.assertLogs(self.LOG, level="WARNING") as reg:
            self.assertIs(c.revoca("p1"), False)
        self._traccia(reg, "revoca check-in fallita")

    def test_riga182_l_emettitore_che_esplode_lascia_la_traccia_e_niente_pass(self):
        class Boom:
            def emetti(self, *a, **k):
                raise RuntimeError("serratura muta")
        c = crea_checkin_digitale(":memory:", Boom())
        c.inizializza_schema()
        c.pre_registra("p1", "casa", OSP, 2)
        with self.assertLogs(self.LOG, level="WARNING") as reg:
            self.assertIsNone(c.sblocca("p1", "casa"))
        rec = [r for r in reg.records if "emissione pass fallita" in r.getMessage()][0]
        self.assertIsInstance(rec.exc_info, tuple)
        self.assertIs(rec.exc_info[0], RuntimeError)

    def test_riga189_il_check_in_in_memoria_si_usa_anche_da_un_altro_thread(self):
        c = cd()
        esiti = {}

        def lavoro():
            try:
                esiti["esito"] = c.pre_registra("p1", "casa", OSP, 2)
            except Exception as e:
                esiti["errore"] = "%s: %s" % (type(e).__name__, e)
        t = threading.Thread(target=lavoro)
        t.start()
        t.join(10)
        self.assertNotIn("errore", esiti, esiti.get("errore"))
        self.assertTrue(esiti["esito"]["ok"], esiti)
        self.assertTrue(c.completato("p1"))


if __name__ == "__main__":
    unittest.main()
