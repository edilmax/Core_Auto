"""Test Fase 147 - Tassa comunale. SQLite :memory:, cents interi."""
import unittest

from fase147_tassa_comunale import calcola_tassa, crea_tassa_comunale


def tc():
    t = crea_tassa_comunale(":memory:")
    t.inizializza_schema()
    return t


class TestCalcolo(unittest.TestCase):
    def test_per_persona_notte(self):
        # 2 paganti * 3 notti * 1.50 = 9.00
        self.assertEqual(calcola_tassa({"ppn_cents": 150}, 2, 3), 900)

    def test_cap_notti(self):
        self.assertEqual(calcola_tassa({"ppn_cents": 100, "max_notti": 2}, 1, 10), 200)

    def test_esenti(self):
        self.assertEqual(calcola_tassa({"ppn_cents": 100}, 3, 2, esenti=1), 400)  # 2 paganti

    def test_percentuale_su_imponibile(self):
        self.assertEqual(calcola_tassa({"perc_bps": 500}, 1, 1, imponibile_cents=10000), 500)

    def test_cap_persona(self):
        r = {"ppn_cents": 100, "cap_persona_cents": 250}
        self.assertEqual(calcola_tassa(r, 2, 10), 500)     # cap 2.50/persona * 2

    def test_zero_e_invalidi(self):
        self.assertEqual(calcola_tassa({}, 2, 3), 0)
        self.assertEqual(calcola_tassa({"ppn_cents": 100}, -1, 3), 0)


class TestRegistro(unittest.TestCase):
    def test_regola_e_applica(self):
        t = tc()
        self.assertTrue(t.imposta_regola("Roma", {"ppn_cents": 350, "max_notti": 10}))
        self.assertEqual(t.applica("roma", 2, 3), 2100)    # case-insensitive
        self.assertEqual(t.applica("CittaIgnota", 2, 3), 0)  # ignoto -> 0

    def test_ledger_riscossioni(self):
        t = tc()
        t.imposta_regola("Roma", {"ppn_cents": 350})
        imp = t.applica("Roma", 2, 2)
        self.assertTrue(t.registra_riscossione("p1", "Roma", imp))
        self.assertTrue(t.registra_riscossione("p2", "Roma", 700))
        self.assertEqual(t.totale_riscosso("roma"), imp + 700)

    def test_riscossione_idempotente(self):
        t = tc()
        t.registra_riscossione("p1", "Roma", 100)
        t.registra_riscossione("p1", "Roma", 999)          # IGNORE
        self.assertEqual(t.totale_riscosso("Roma"), 100)

    def test_input_invalido(self):
        t = tc()
        self.assertFalse(t.imposta_regola("", {"ppn_cents": 1}))
        self.assertFalse(t.registra_riscossione("", "Roma", 100))
        self.assertFalse(t.registra_riscossione("p1", "Roma", -5))


class TestI14PUNTITrovatiDalGiudice(unittest.TestCase):
    """I 14 punti che il Giudice ha trovato SCOPERTI il 2026-08-19 (29 punti, 15 uccisi,
    14 sopravvissuti: il modulo piu' scoperto del gruppo 2 dei soldi).

    ⛔ QUESTA NON E' UNA TASSA NOSTRA: e' denaro che incassiamo **per conto del Comune** e
    che dobbiamo versargli. Se lo contiamo male non perdiamo un margine, ne dobbiamo di
    piu' o di meno a un ente pubblico -- e la differenza la mettiamo noi.

    💡 E i 14 punti dicono tutti la stessa cosa: erano scoperti i **rami d'errore** e i
    **valori restituiti**, cioe' il codice che risponde «e' andata bene» o «e' andata male».
    E' la D19 in forma pura: *il codice difensivo e' indistinguibile da codice morto finche'
    qualcuno non costruisce a mano lo stato che lo esegue*.
    """

    class _ConnessioneRotta:
        """Un database che fallisce a ogni comando: costruisce a mano il guasto che nella
        vita vera capita una volta ogni mille (disco pieno, file bloccato, WAL corrotto).

        ⛔ L'errore e' un `sqlite3.OperationalError`, non un'eccezione qualunque, e non e' un
        dettaglio: e' la forma che il guasto ha DAVVERO. La prima versione di questa finta
        connessione sollevava un `RuntimeError` e faceva esplodere gia' l'apertura -- cioe'
        provava una cosa che in produzione non succede, e avrebbe fatto «riparare» un
        percorso inesistente. Un banco di prova che non somiglia alla macchina vera produce
        difetti immaginari e nasconde quelli veri.
        """
        def __init__(self):
            self.chiusa = False

        def execute(self, *a, **k):
            import sqlite3
            raise sqlite3.OperationalError("disco pieno (guasto iniettato dal collaudo)")

        def close(self):
            self.chiusa = True

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _tassa_rotta(self):
        from fase147_tassa_comunale import TassaComunale
        rotta = self._ConnessioneRotta()
        return TassaComunale(lambda: rotta), rotta

    # ── i confini del calcolo ────────────────────────────────────────────────────────
    def test_un_TETTO_ASSENTE_non_azzera_la_tassa(self):
        """⛔ IL BUCO PIU' CARO DEL MODULO. Il tetto per persona (`cap_persona_cents`) e'
        FACOLTATIVO: quasi nessun comune lo mette. Il codice applica il tetto solo se e'
        maggiore di zero -- ma nessun test lo verificava, e il Giudice ha cambiato quel
        `> 0` in `>= 0`.

        Col guasto dentro, un comune SENZA tetto (cap = 0) finisce in
        `min(tassa, 0 * paganti)` = **zero**: la tassa di soggiorno diventa ZERO per tutti i
        comuni che non dichiarano un massimale, e nessuno se ne accorge -- il conto torna,
        e' semplicemente vuoto. Al Comune non versiamo piu' niente.
        """
        senza_tetto = {"ppn_cents": 200, "max_notti": 0, "perc_bps": 0,
                       "cap_persona_cents": 0}
        self.assertEqual(
            calcola_tassa(senza_tetto, ospiti=2, notti=3), 1200,
            "un comune SENZA tetto per persona ha prodotto una tassa diversa da "
            "2 ospiti x 3 notti x 2,00 EUR: se e' zero, il tetto assente sta azzerando "
            "tutto e al Comune non versiamo piu' niente")
        # e il tetto, quando c'e' DAVVERO, taglia: le due direzioni insieme
        con_tetto = dict(senza_tetto, cap_persona_cents=300)
        self.assertEqual(calcola_tassa(con_tetto, ospiti=2, notti=3), 600,
                         "il tetto dichiarato non taglia: 2 persone x 3,00 EUR di massimale")

    def test_con_TUTTI_ESENTI_il_tetto_per_persona_non_azzera_la_percentuale(self):
        """⛔ L'ULTIMO PUNTO SCOPERTO, e sotto c'e' una DOMANDA FISCALE, non tecnica.

        Il tetto e' **per persona**: il codice lo applica solo se c'e' almeno un pagante.
        Con tutti gli ospiti esenti (paganti = 0) e una tassa a **percentuale
        sull'imponibile**, oggi la percentuale resta dovuta:
            2 ospiti, 2 esenti, imponibile 200,00 EUR, 5%  ->  10,00 EUR
        Col mutante (`paganti >= 0`) il tetto verrebbe applicato come `min(tassa, cap x 0)`
        e la tassa diventerebbe **zero**.

        ⚠️ **QUESTO TEST FISSA IL COMPORTAMENTO ATTUALE, NON DICHIARA CHE SIA GIUSTO.** La
        domanda vera -- *«se tutti gli ospiti sono esenti, la quota a percentuale e' ancora
        dovuta al Comune?»* -- e' una questione di legge locale, non di codice: la risposta
        cambia da comune a comune e va chiesta a un commercialista. Fissarla qui serve a due
        cose: che il punto smetta di essere cieco, e che il giorno in cui qualcuno cambia
        quella riga **se ne accorga qualcuno**, invece che scoprirlo dal conto del Comune.
        La domanda aperta e' scritta in REGISTRO_INGEGNERIA.md.
        """
        regola = {"ppn_cents": 0, "max_notti": 0, "perc_bps": 500,
                  "cap_persona_cents": 100}
        self.assertEqual(
            calcola_tassa(regola, ospiti=2, notti=3, esenti=2, imponibile_cents=20000),
            1000,
            "con tutti gli ospiti esenti la quota a percentuale e' cambiata. Se e' ZERO, il "
            "tetto per persona la sta azzerando: e' una decisione fiscale, e non deve "
            "capitare per un confronto scritto di sfuggita")
        # e con un pagante il tetto per persona torna a tagliare, come deve
        self.assertEqual(
            calcola_tassa(regola, ospiti=2, notti=3, esenti=1, imponibile_cents=20000),
            100,
            "con un pagante il tetto per persona deve tagliare a 1,00 EUR")

    def test_una_tassa_di_ZERO_si_registra_lo_stesso(self):
        """Zero non e' un errore: e' l'esito legittimo di un comune senza tassa, di un
        soggiorno tutto esente, o di una notte oltre il massimale. Il codice lo distingue da
        «importo mancante» usando -1 come valore di ripiego, e il Giudice ha spostato quel
        confine di un passo (due mutanti, righe diverse).

        Col guasto dentro, `registra_riscossione(..., 0)` risponde **False**: il chiamante
        crede che la registrazione sia fallita, il webhook ritenta all'infinito, e nel
        registro non resta traccia che quella prenotazione e' stata esaminata."""
        t = tc()
        self.assertTrue(t.registra_riscossione("p-zero", "Roma", 0),
                        "una tassa di ZERO e' un esito valido: rifiutarla fa credere a un "
                        "guasto che non c'e'")
        self.assertTrue(t.registra_riscossione("p-zero", "Roma", 0),
                        "la seconda registrazione identica deve essere idempotente e "
                        "rispondere TRUE, se no chi ritenta pensa di aver fallito")
        # e un importo NEGATIVO resta un errore vero
        self.assertFalse(t.registra_riscossione("p-neg", "Roma", -1),
                         "un importo negativo non e' una tassa")

    def test_una_registrazione_RIPETUTA_dice_che_e_andata_bene(self):
        """Il webhook di Stripe ritenta: la seconda chiamata trova la riga gia' li' e deve
        rispondere TRUE. Col mutante che rovescia quel `return`, ogni ritentativo risulta
        fallito e il pagamento resta in uno stato che nessuno sa chiudere."""
        t = tc()
        self.assertTrue(t.registra_riscossione("p-doppia", "Roma", 150))
        self.assertTrue(t.registra_riscossione("p-doppia", "Roma", 150),
                        "la registrazione ripetuta deve essere idempotente e dirlo")
        self.assertEqual(t.totale_riscosso("Roma"), 150,
                         "la ripetizione ha contato la tassa DUE volte: al Comune "
                         "dovremmo il doppio")

    # ── i rami d'errore: si costruiscono a mano, adesso (D19) ────────────────────────
    def test_se_il_DATABASE_ROMPE_nessuna_operazione_mente(self):
        """⛔ IL CUORE DEI 14. Sei mutanti stavano sui `return` dei rami `except`: rovesciati,
        ogni operazione fallita dichiara **successo**.

        Cosa vuol dire in concreto, ed e' scritto nel codice stesso:
          · `registra_riscossione` fallita ma dichiarata riuscita -> la tassa non e' nel
            registro, ma noi crediamo di averla incassata: al Comune ne dobbiamo di piu' di
            quanto risulta a noi;
          · `storna` fallita ma dichiarata riuscita -> *«tassa sovra-contata al Comune (a
            nostro carico)»*, dice il commento accanto: paghiamo noi una tassa che l'ospite
            si e' fatto rimborsare;
          · `imposta_regola` fallita ma dichiarata riuscita -> il comune crede di avere una
            regola configurata e invece ne ha un'altra (o nessuna).

        Il guasto e' iniettato a mano: un database che fallisce a ogni comando."""
        for operazione, chiamata in (
                ("imposta_regola", lambda t: t.imposta_regola("Roma", {"ppn_cents": 100})),
                ("registra_riscossione", lambda t: t.registra_riscossione("p1", "Roma", 100)),
                ("storna", lambda t: t.storna("p1"))):
            tassa, rotta = self._tassa_rotta()
            esito = chiamata(tassa)
            self.assertIs(esito, False,
                          "%s ha dichiarato SUCCESSO con il database rotto: un'operazione "
                          "sui soldi che fallisce in silenzio e' peggio di una che esplode"
                          % operazione)
            self.assertTrue(rotta.chiusa,
                            "%s non ha chiuso la connessione dopo il guasto" % operazione)

    def test_quando_ROMPE_il_registro_porta_la_TRACCIA_dell_errore(self):
        """⛔ «NON E' NULLO» NON E' UNA GUARDIA (lezione del 2026-08-04): `exc_info=False`
        produce **False**, non **None**. Tre mutanti hanno spento proprio quel campo, e
        nessun test se n'e' accorto.

        Senza traccia, nel registro resta una riga che dice «errore DB» e basta: chi ripara
        alle tre di notte non sa **quale** errore, **dove**, **perche'**. E' la regola ferrea
        9 -- l'osservabile debole e' un difetto -- applicata al posto in cui serve di piu':
        il ramo che si esegue solo quando qualcosa e' gia' andato storto."""
        import logging
        registrate = []

        class Ascoltatore(logging.Handler):
            def emit(self, record):
                registrate.append(record)

        ascolto = Ascoltatore()
        logger = logging.getLogger("core_auto.tassa_comunale")
        logger.addHandler(ascolto)
        self.addCleanup(logger.removeHandler, ascolto)
        for chiamata in (lambda t: t.imposta_regola("Roma", {"ppn_cents": 100}),
                         lambda t: t.registra_riscossione("p1", "Roma", 100),
                         lambda t: t.storna("p1")):
            tassa, _ = self._tassa_rotta()
            chiamata(tassa)
        self.assertEqual(len(registrate), 3,
                         "tre operazioni fallite devono lasciare tre righe nel registro: "
                         "trovate %d" % len(registrate))
        for record in registrate:
            self.assertIsNotNone(
                record.exc_info,
                "la riga %r non porta la traccia dell'errore: chi ripara di notte legge "
                "«errore DB» e non sa nemmeno quale" % record.getMessage()[:60])
            self.assertIsNot(record.exc_info, False,
                             "`exc_info=False` produce FALSE, non None: sembra una traccia "
                             "e non lo e' (lezione del 2026-08-04)")

    def test_uno_STORNO_con_identificativo_storto_non_scrive_niente(self):
        """Lo storno mette una **lapide permanente**: da quel momento nessuna riscossione
        tardiva puo' piu' risorgere su quella prenotazione. Proprio per questo l'identificativo
        deve essere un testo VERO: col mutante che allenta il controllo (`and` -> `or`), una
        stringa vuota o un numero passano, e si pianta una lapide su un identificativo che
        non esiste -- bloccando per sempre la riscossione di *qualcos'altro*."""
        t = tc()
        for storto in ("", None, 123, [], {}):
            self.assertIs(t.storna(storto), False,
                          "storna(%r) e' stato accettato: si sta piantando una lapide su un "
                          "identificativo che non e' una prenotazione" % (storto,))
        # e su un identificativo vero lo storno funziona e lo dichiara
        t.registra_riscossione("p-vera", "Roma", 500)
        self.assertIs(t.storna("p-vera"), True,
                      "uno storno riuscito deve dichiararlo: se dice False, chi cancella la "
                      "prenotazione crede che la tassa sia ancora dovuta")
        self.assertEqual(t.totale_riscosso("Roma"), 0,
                         "dopo lo storno la tassa non e' piu' dovuta al Comune")

    def test_il_registro_IN_MEMORIA_regge_i_thread(self):
        """`crea_tassa_comunale(":memory:")` condivide UNA connessione, e la condivide fra
        thread apposta: e' il banco su cui girano le prove di concorrenza (`test_tassa_race`),
        quelle che hanno scoperto le 107 violazioni della race webhook/cancellazione. Il
        Giudice ha rovesciato `check_same_thread=False` e nessun test se n'e' accorto:
        quel giorno le prove di concorrenza smetterebbero di girare, e nessuno lo saprebbe."""
        import threading
        t = tc()
        esiti = []

        def registra():
            try:
                esiti.append(t.registra_riscossione("p-thread", "Roma", 100))
            except Exception as e:
                esiti.append("ESPLOSO: %s" % type(e).__name__)

        filo = threading.Thread(target=registra)
        filo.start()
        filo.join(timeout=20)
        self.assertEqual(esiti, [True],
                         "il registro in memoria non regge una scrittura da un altro thread: "
                         "%r. Senza questo, le prove di concorrenza non possono girare" % esiti)


if __name__ == "__main__":
    unittest.main()
