"""Test Fase 131 - Payout dashboard. SQLite :memory:.
E le guardie di `TestIBuchiDelGiudice` (2026-09-04), nate dai 24 mutanti sopravvissuti al giro
intero del Giudice con i sei occhi (dedicato + cinque che importano il modulo)."""
import sqlite3
import threading
import unittest

from fase131_payout_dashboard import PayoutDashboard, crea_payout_dashboard


def pd():
    p = crea_payout_dashboard(":memory:")
    p.inizializza_schema()
    return p


class TestPayout(unittest.TestCase):
    def test_maturato_e_riepilogo_per_valuta(self):
        p = pd()
        self.assertTrue(p.registra_maturato("p1", "h1", 9700, "USD"))
        self.assertTrue(p.registra_maturato("p2", "h1", 5000, "EUR"))
        r = p.riepilogo("h1")
        self.assertEqual(r["USD"]["maturato"], 9700)
        self.assertEqual(r["EUR"]["maturato"], 5000)

    def test_transizioni_valide(self):
        p = pd()
        p.registra_maturato("p1", "h1", 9700, "USD")
        self.assertTrue(p.aggiorna_stato("p1", "in_transito"))
        self.assertTrue(p.aggiorna_stato("p1", "pagato"))
        self.assertFalse(p.aggiorna_stato("p1", "maturato"))   # pagato è terminale

    def test_transizione_illegale(self):
        p = pd()
        p.registra_maturato("p1", "h1", 9700, "USD")
        self.assertFalse(p.aggiorna_stato("p1", "pagato"))     # maturato->pagato no
        self.assertFalse(p.aggiorna_stato("p1", "boh"))

    def test_da_pagare(self):
        p = pd()
        p.registra_maturato("p1", "h1", 9700, "USD")
        p.registra_maturato("p2", "h1", 3000, "USD")
        p.aggiorna_stato("p2", "in_transito")
        self.assertEqual(p.da_pagare("h1", "USD"), 12700)
        p.aggiorna_stato("p2", "pagato")
        self.assertEqual(p.da_pagare("h1", "USD"), 9700)       # pagato escluso

    def test_input_invalido(self):
        p = pd()
        self.assertFalse(p.registra_maturato("p1", "h1", -5, "USD"))
        self.assertFalse(p.registra_maturato("p1", "h1", 100, "EURO"))
        self.assertFalse(p.registra_maturato("", "h1", 100, "USD"))

    def test_idempotente(self):
        p = pd()
        p.registra_maturato("p1", "h1", 9700, "USD")
        p.registra_maturato("p1", "h1", 9999, "USD")           # IGNORE
        self.assertEqual(p.riepilogo("h1")["USD"]["maturato"], 9700)

    def test_host_vuoto(self):
        self.assertEqual(pd().riepilogo("hX"), {})


class _ConnCheEsplode:
    """Una connessione che esplode a ogni istruzione: esercita il ramo `except` di OGNI metodo.
    `_apri` ingoia l'errore del PRAGMA (e' un `except sqlite3.Error`), quindi si arriva al metodo."""

    def execute(self, *a, **k):
        raise sqlite3.OperationalError("disco rotto (finto)")

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestIBuchiDelGiudice(unittest.TestCase):
    """Guardie nate dai 24 mutanti SOPRAVVISSUTI al giro intero del Giudice del 2026-09-04
    (62 punti, sei occhi: dedicato + cinque che importano il modulo; 38 uccisi). Ognuna porta
    nel nome le righe dei mutanti, e' stata vista ROSSA contro di loro prima che verde (D20)
    e difende un contratto scritto nel modulo. Nessun mutante e' stato dichiarato equivalente (B6)."""

    def test_riga46_98_119_un_payout_a_ZERO_si_registra_e_vale_zero_non_viene_rifiutato(self):
        # Col mutante `_pos(0)` vale -1 (o il confine `< 0` diventa `<= 0`) e un payout a ZERO viene
        # rifiutato. Zero e' un importo legittimo (quota host azzerata da una controversia): «un
        # payout a zero e' un numero, non un buco». Nessuno dei sei occhi registrava uno zero.
        p = pd()
        self.assertIs(p.registra_maturato("p0", "h1", 0, "USD"), True)
        self.assertEqual(p.riepilogo("h1"), {"USD": {"maturato": 0}})
        self.assertEqual(p.info("p0")["minori"], 0)
        self.assertIs(p.registra_in_attesa("a0", "h1", 0, "EUR"), True)
        self.assertEqual(p.stato_di("a0"), "in_attesa")
        # e sotto zero resta rifiutato: il confine e' 0, non 1
        self.assertIs(p.registra_maturato("neg", "h1", -1, "USD"), False)
        self.assertEqual(p.stato_di("neg"), "")

    def test_riga109_e_sorelle_un_errore_del_DB_lascia_nel_log_L_ECCEZIONE_non_solo_la_frase(self):
        # Il modulo ha DODICI rami d'errore uguali (uno per metodo) e la stessa mutazione
        # (`exc_info=True` -> `False`) e' sopravvissuta in ognuno. ⛔ `False` non e' `None`:
        # «assertIsNotNone» lo lascerebbe vivo (lezione gia' pagata dal progetto). La guardia
        # pretende LA COSA, del tipo giusto: la tupla (tipo, eccezione, traceback) con dentro
        # l'eccezione del disco rotto. Senza traceback, un errore del DB sui soldi dell'host si
        # scoprirebbe da una frase generica: nessuno saprebbe COSA e' rotto.
        p = PayoutDashboard(lambda: _ConnCheEsplode(), orologio=lambda: 1)
        chiamate = [
            ("registra_maturato", ("p1", "h1", 100, "EUR"), False),    # 109
            ("registra_in_attesa", ("p1", "h1", 100, "EUR"), False),   # 130
            ("rimuovi", ("p1",), False),                               # 145
            ("aggiorna_stato", ("p1", "in_transito"), False),          # 164
            ("riepilogo", ("h1",), {}),                                # 181
            ("conta_pagati", ("h1",), 0),                              # 195
            ("stato_di", ("p1",), ""),                                 # 214
            ("aumenta_payout", ("p1", 5), False),                      # 232
            ("info", ("p1",), None),                                   # 251
            ("elenca", ("h1",), []),                                   # 281
            ("tutti", (), []),                                         # 306
            ("imposta_importo", ("p1", 5), False),                     # 327
        ]
        for nome, args, atteso in chiamate:
            with self.subTest(metodo=nome):
                with self.assertLogs("core_auto.payout_dashboard", level="WARNING") as cm:
                    self.assertEqual(getattr(p, nome)(*args), atteso)
                rec = cm.records[-1]
                self.assertIsInstance(rec.exc_info, tuple,
                                      "%s: exc_info=%r (False non e' un traceback)" % (nome, rec.exc_info))
                self.assertIsInstance(rec.exc_info[1], sqlite3.OperationalError, nome)

    def test_riga203_240_261_318_un_id_che_non_e_una_stringa_non_trova_niente_nemmeno_se_il_numero_coincide(self):
        # SQLite confronta '123' (TEXT) con 123 (INTEGER) applicando l'affinita' TEXT: senza la
        # guardia `isinstance(..., str)` un intero troverebbe la riga. Col mutante (and -> or) la
        # guardia lascia passare i non-stringa: un chiamante che sbaglia tipo legge o modifica
        # soldi altrui.
        p = pd()
        self.assertIs(p.registra_maturato("123", "456", 9700, "USD"), True)
        self.assertEqual(p.stato_di(123), "")                                        # 203
        self.assertIsNone(p.info(123))                                               # 240
        self.assertEqual(p.elenca(456), [])                                          # 261
        self.assertIs(p.imposta_importo(123, 500), False)                            # 318
        self.assertEqual(p.info("123")["minori"], 9700)                              # l'importo non e' stato toccato
        self.assertEqual(p.stato_di("123"), "maturato")
        self.assertEqual(len(p.elenca("456")), 1)

    def test_riga267_270_295_un_filtro_vuoto_o_non_stringa_non_filtra_niente(self):
        p = pd()
        p.registra_maturato("p1", "h1", 100, "USD")
        p.registra_in_attesa("p2", "h1", 200, "EUR")
        tutti = [r["prenotazione_id"] for r in p.elenca("h1")]
        self.assertEqual(tutti, ["p1", "p2"])
        for vuoto in ("", None, 0, 123):
            with self.subTest(filtro=vuoto):
                self.assertEqual([r["prenotazione_id"] for r in p.elenca("h1", stato=vuoto)], tutti)    # 267
                self.assertEqual([r["prenotazione_id"] for r in p.elenca("h1", valuta=vuoto)], tutti)   # 270
                self.assertEqual([r["prenotazione_id"] for r in p.tutti(stato=vuoto)], tutti)           # 295
        self.assertEqual([r["prenotazione_id"] for r in p.elenca("h1", stato="in_attesa")], ["p2"])
        self.assertEqual([r["prenotazione_id"] for r in p.elenca("h1", valuta=" eur ")], ["p2"])

    def test_riga263_292_un_limite_fuori_misura_ricade_sul_predefinito_e_non_fa_esplodere_la_lettura(self):
        p = pd()
        for i in range(3):
            p.registra_maturato("p%d" % i, "h1", 100, "USD")
        for limite in (0, -1, 5001, "5", 2.5, None):
            with self.subTest(limite=limite):
                self.assertEqual(len(p.tutti(limit=limite)), 3)                       # 292: ricade su 2000
                self.assertEqual(len(p.elenca("h1", limit=limite)), 3)                # 263: ricade su 200
        self.assertEqual(len(p.tutti(limit=2)), 2)
        self.assertEqual(len(p.elenca("h1", limit=2)), 2)

    # Le tre guardie qui sotto chiudono gli 11 mutanti che sopravvivono al SOLO test dedicato
    # (li uccidevano gli altri cinque occhi): cosi' il dedicato basta da solo, e un giro sul
    # modulo costa 0,1 s di normale invece di 68.
    def test_riga46_119_120_un_importo_o_un_id_non_validi_sono_rifiutati_anche_dal_payout_in_attesa(self):
        # `_pos` vuole un int vero, non bool, >= 0 (col mutante and -> or passano float e bool, e una
        # stringa fa esplodere il confronto); `registra_in_attesa` ha la stessa guardia d'ingresso di
        # `registra_maturato`, ma nessun test la esercitava con ingressi sbagliati.
        p = pd()
        for pid, host, minori, valuta in (("p1", "h1", 2.5, "USD"), ("p1", "h1", True, "USD"),
                                         ("p1", "h1", "5", "USD"), ("p1", "h1", None, "USD"),
                                         ("p1", "h1", -5, "USD"), ("p1", "", 100, "USD"),
                                         ("", "h1", 100, "USD"), ("p1", "h1", 100, "EURO"),
                                         ("p1", "h1", 100, "")):
            with self.subTest(pid=pid, host=host, minori=minori, valuta=valuta):
                self.assertIs(p.registra_maturato(pid, host, minori, valuta), False)      # 46
                self.assertIs(p.registra_in_attesa(pid, host, minori, valuta), False)     # 119, 120
        self.assertEqual(p.tutti(), [], "un ingresso rifiutato non lascia righe")

    def test_riga143_223_224_318_rimuovi_dice_True_e_aumenta_o_imposta_l_importo_solo_con_un_delta_o_una_quota_positivi(self):
        p = pd()
        p.registra_maturato("p1", "h1", 9700, "USD")
        for delta in (0, -5, True, 2.5, "5", None):
            with self.subTest(delta=delta):
                self.assertIs(p.aumenta_payout("p1", delta), False)                        # 223, 224
                self.assertIs(p.imposta_importo("p1", delta), False)                       # 318
                self.assertEqual(p.info("p1")["minori"], 9700)
        self.assertIs(p.aumenta_payout("p1", 300), True)
        self.assertEqual(p.info("p1")["minori"], 10000)
        self.assertIs(p.aumenta_payout("manca", 300), False)                               # nessuna riga toccata
        self.assertIs(p.imposta_importo("p1", 4200), True)
        self.assertEqual(p.info("p1")["minori"], 4200)
        self.assertIs(p.imposta_importo("manca", 4200), False)
        self.assertIs(p.rimuovi("p1"), True)                                               # 143
        self.assertIsNone(p.info("p1"))
        self.assertIs(p.rimuovi("p1"), True, "idempotente: rimuovere il gia' rimosso e' True")

    def test_riga343_il_ledger_in_memoria_si_usa_anche_da_un_altro_thread(self):
        # Il web server serve ogni richiesta in un thread diverso: `check_same_thread=False` esiste
        # per questo. Col mutante (False -> True) la prima scrittura da un altro thread fallisce in
        # silenzio (ProgrammingError catturato -> False): il payout dell'host non viene mai registrato.
        p = pd()
        esiti = []
        t = threading.Thread(target=lambda: esiti.append(p.registra_maturato("p1", "h1", 100, "USD")))
        t.start()
        t.join(5)
        self.assertEqual(esiti, [True])
        self.assertEqual(p.stato_di("p1"), "maturato")


if __name__ == "__main__":
    unittest.main()
