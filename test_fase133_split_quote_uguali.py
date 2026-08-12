"""Test Fase 133 - Split quote uguali. SQLite :memory:, cents interi."""
import unittest

from fase133_split_quote_uguali import crea_split_quote, riparti_uguale


class TestRiparti(unittest.TestCase):
    def test_conservazione_esatta(self):
        for tot, k in ((10000, 3), (100, 3), (1, 4), (999, 7), (12345, 10)):
            q = riparti_uguale(tot, k)
            self.assertEqual(sum(q), tot)
            self.assertEqual(len(q), k)
            self.assertLessEqual(max(q) - min(q), 1)        # quasi uguali

    def test_resto_primi(self):
        self.assertEqual(riparti_uguale(100, 3), [34, 33, 33])

    def test_invalidi(self):
        self.assertEqual(riparti_uguale(100, 0), [])
        self.assertEqual(riparti_uguale(-5, 3), [])
        self.assertEqual(riparti_uguale("x", 3), [])

    def test_UN_TOTALE_ZERO_E_LEGITTIMO_E_DA_QUOTE_A_ZERO(self):
        """⛔ IL BUCO CHE HA TROVATO IL GIUDICE, non il ragionamento.

        Il giro di mutazione del 2026-08-12 ha lasciato vivi DUE mutanti, entrambi sullo stesso
        confine e entrambi su codice VIVO:
            riga 43   `totale_cents >= 0`  ->  `> 0`
            riga 46   `if tot < 0`         ->  `if tot <= 0`
        Con l'uno o con l'altro, `riparti_uguale(0, 3)` smette di dare `[0, 0, 0]` e dà `[]`,
        cioe' la rotta pubblica risponderebbe **400 «parametri_non_validi»** su un totale che
        non ha niente di invalido. Nessun collaudo lo vedeva: `test_invalidi` qui sopra prova
        `-5` e `"x"`, mai lo **zero** -- e zero e' il confine, non un caso strano.

        LA SCELTA CHE QUESTO TEST DICHIARA, perche' finora non era scritta da nessuna parte:
        **zero e' un totale legittimo**, e tre persone che dividono zero prendono zero ciascuna.
        Il contratto dice «quote che sommano ESATTAMENTE a totale_cents», e `[0,0,0]` somma 0.
        Un soggiorno regalato non e' un errore di chi chiama, e rispondere 400 sarebbe dare la
        colpa all'utente per una cosa giusta.
        ⛔ Da qui in avanti, chi cambia quel confine trova rosso lo stesso giorno.
        """
        self.assertEqual([0, 0, 0], riparti_uguale(0, 3),
                         "un totale di zero non e' invalido: tre persone che dividono zero "
                         "prendono zero ciascuna, e la somma resta esatta")
        self.assertEqual([0], riparti_uguale(0, 1), "e vale anche per una persona sola")
        self.assertEqual(0, sum(riparti_uguale(0, 7)),
                         "la conservazione esatta vale anche a zero")
        self.assertEqual(7, len(riparti_uguale(0, 7)),
                         "e le quote sono quante le persone, non zero quote")
        # E il confine NON si sposta dall'altro lato: -1 resta invalido.
        self.assertEqual([], riparti_uguale(-1, 3),
                         "un totale negativo resta invalido: lo zero e' il confine, e un "
                         "confine che si sposta di uno da entrambi i lati non e' un confine")


def sp():
    s = crea_split_quote(":memory:")
    s.inizializza_schema()
    return s


class TestSplit(unittest.TestCase):
    def test_crea_e_stato(self):
        s = sp()
        self.assertTrue(s.crea_gruppo("g1", 10000, ["a", "b", "c"]))
        st = s.stato("g1")
        self.assertEqual(st["totale_cents"], 10000)
        self.assertEqual(sum(st["quote"].values()), 10000)
        self.assertFalse(st["completato"])

    def test_pagamento_e_completamento(self):
        s = sp()
        s.crea_gruppo("g1", 9000, ["a", "b", "c"])
        for p in ("a", "b", "c"):
            self.assertTrue(s.paga("g1", p))
        st = s.stato("g1")
        self.assertTrue(st["completato"])
        self.assertEqual(st["mancanti"], [])

    def test_paga_idempotente(self):
        s = sp()
        s.crea_gruppo("g1", 9000, ["a", "b", "c"])
        self.assertTrue(s.paga("g1", "a"))
        self.assertFalse(s.paga("g1", "a"))                 # già pagato

    def test_duplicato_gruppo(self):
        s = sp()
        s.crea_gruppo("g1", 9000, ["a", "b"])
        self.assertFalse(s.crea_gruppo("g1", 1, ["x"]))

    def test_partecipanti_duplicati(self):
        s = sp()
        self.assertFalse(s.crea_gruppo("g1", 9000, ["a", "a"]))

    def test_vuoto(self):
        self.assertEqual(sp().stato("gX"), {})


class TestUnNGrandeNonPuoFarAllOCARE_IL_SERVER(unittest.TestCase):
    """⛔ UN `n` GRANDE ARRIVA DA UNA ROTTA PUBBLICA, E QUESTO MODULO SI DICHIARA BLINDATO.

    `fase83_server.py:6748` passa `dati.get("n")` -- cioe' un numero che arriva dal browser --
    dritto a `riparti_uguale`, dietro `POST /api/split/preview`. Quella rotta e' **pubblica**:
    `gestisci` (fase83_server.py:1757) chiama `_instrada` senza nessun controllo di sessione,
    e fra la riga 1797 e la 1849 non c'e' un solo `if` di autenticazione.

    Il modulo promette di se stesso «BLINDATO: input invalido -> [] / no-op». **E' falso per
    questo caso**, ed e' la stessa forma del difetto di `fase66`, che prometteva «fail-closed»
    e faceva il contrario: un `n` enorme non e' *invalido* per i suoi controlli -- e' un intero
    positivo, quindi passa, e la lista viene costruita elemento per elemento.

    MISURATO il 2026-08-12 su questa macchina, non estrapolato:
        n=1.000.000  ->  0,035 s   8.448.728 byte
        n=4.000.000  ->  0,145 s  34.724.184 byte
    Crescita LINEARE in n. A `n=10**9` la richiesta chiede ~8,7 GB (questa si' e'
    un'estrapolazione, e va detto): il processo muore.
    ⚠️ E il rate limit NON copre questo difetto: non servono mille richieste, ne basta UNA da
    quaranta byte. Sul VPS, che ha una sola CPU, l'effetto e' il sito giu'.

    ⛔ PERCHE' LA GUARDIA USA 2.000.000 E NON 10**9. Con `10**9` un giro senza la riparazione
    non fallirebbe: morirebbe, portandosi via la suite (ed e' l'errore di lanciare un lavoro
    con il guinzaglio sbagliato, sbaglio S8). Con 2.000.000 il costo e' 17 MB misurati -- il
    test VEDE la lista sbagliata e grida, invece di uccidere il giro. La proprieta' e' la
    stessa perche' la crescita e' lineare: se rifiuta 2 milioni rifiuta anche un miliardo.
    """

    N_ASSURDO = 2000000

    def test_IL_MODULO_DICHIARA_UN_TETTO_SUI_PARTECIPANTI(self):
        import fase133_split_quote_uguali as m
        tetto = getattr(m, "MAX_PARTECIPANTI", None)
        self.assertIsNotNone(
            tetto,
            "il modulo non dichiara nessun tetto sul numero di partecipanti, e riceve quel "
            "numero da una rotta PUBBLICA. Un limite che non e' scritto da nessuna parte non "
            "e' un limite: e' una speranza sul comportamento di chi chiama.")
        self.assertGreaterEqual(
            tetto, 100,
            "il tetto e' %r: troppo basso. Un gruppo vero di amici che divide un conto arriva "
            "a decine di persone, e un tetto che rifiuta un caso legittimo fa perdere l'host "
            "(D16: si dichiara chi ci perde se va storta)." % (tetto,))
        self.assertLessEqual(
            tetto, 100000,
            "il tetto e' %r: cosi' alto non protegge da niente. A 100.000 la lista costa gia' "
            "800 KB per richiesta, misurati." % (tetto,))

    def test_UN_N_ENORME_VIENE_RIFIUTATO_NON_ALLOCATO(self):
        q = riparti_uguale(100, self.N_ASSURDO)
        self.assertEqual(
            [], q,
            "con n=%d il modulo ha costruito una lista di %d elementi invece di rifiutare. "
            "Una richiesta HTTP pubblica da quaranta byte puo' far allocare al server memoria "
            "lineare in n, e il contratto del modulo dichiara di essere BLINDATO."
            % (self.N_ASSURDO, len(q)))

    def test_IL_CONFINE_DEL_TETTO_E_ESATTO(self):
        """Il tetto vale ESATTAMENTE dove dice: uno dentro passa, uno fuori no. Un confine
        approssimativo e' un confine che nessuno sa dove sia."""
        import fase133_split_quote_uguali as m
        tetto = getattr(m, "MAX_PARTECIPANTI", None)
        if tetto is None:
            self.fail("il modulo non dichiara MAX_PARTECIPANTI: niente da confinare")
        dentro = riparti_uguale(tetto, tetto)
        self.assertEqual(tetto, len(dentro),
                         "esattamente AL tetto deve funzionare: %d quote invece di %d"
                         % (len(dentro), tetto))
        self.assertEqual(tetto, sum(dentro), "e la conservazione esatta regge anche al tetto")
        self.assertEqual([], riparti_uguale(100, tetto + 1),
                         "uno OLTRE il tetto deve essere rifiutato")

    def test_I_GRUPPI_VERI_NON_SONO_TOCCATI(self):
        """Le due direzioni (regola ferrea 10): il tetto non deve rompere l'uso normale.
        Un falso allarme e' un difetto quanto un allarme mancato -- e qui il «falso allarme»
        sarebbe un host che non riesce piu' a dividere il conto fra dieci amici."""
        for k in (1, 2, 3, 7, 10, 50, 100):
            q = riparti_uguale(10000, k)
            self.assertEqual(k, len(q), "il gruppo da %d e' legittimo e viene rifiutato" % k)
            self.assertEqual(10000, sum(q), "conservazione esatta rotta per k=%d" % k)
            self.assertLessEqual(max(q) - min(q), 1, "quote non piu' quasi uguali per k=%d" % k)


class TestLaCatenaVeraRifiutaUnNAssurdo(unittest.TestCase):
    """③ E2E — LA ROTTA PUBBLICA, ATTRAVERSATA PER DAVVERO.

    ⛔ Non si salta dicendo «e' gia' coperto dagli unitari»: il 2026-08-12 questo e'
    esattamente il livello che ha trovato il piu' grave dei cinque difetti di `fase66`, quello
    che i livelli ① e ② non potevano vedere **per costruzione**. L'unitario prova la funzione;
    qui si prova che il SERVER risponda invece di morire, e che risponda con un errore ONESTO
    invece di un 200 con dentro un numero sbagliato.
    """

    SEG = b"0123456789abcdef0123456789abcdef"

    def _router(self):
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase83_server import crea_router
        return crea_router(crea_sistema(ConfigCasaVIP(abilitato=True,
                                                      segreto_hmac=self.SEG)))

    def test_LA_ROTTA_PUBBLICA_RIFIUTA_UN_N_ASSURDO(self):
        import json
        stato, corpo = self._router().gestisci(
            "POST", "/api/split/preview", None,
            json.dumps({"totale_cents": 100, "n": 2000000}))
        self.assertEqual(
            400, stato,
            "POST /api/split/preview con n=2.000.000 ha risposto %s: la rotta e' PUBBLICA "
            "(nessuna sessione fra fase83_server.py:1797 e :1849), quindi chiunque puo' far "
            "allocare al server memoria lineare in n con quaranta byte. Corpo: %r"
            % (stato, corpo))
        self.assertEqual(
            "parametri_non_validi", corpo.get("errore"),
            "e' 400, ma non dice perche': un errore senza motivo non permette a chi chiama "
            "di distinguere «numero fuori scala» da «json rotto» (regola ferrea 9). %r" % corpo)

    def test_LA_ROTTA_PUBBLICA_FUNZIONA_ANCORA_PER_UN_GRUPPO_VERO(self):
        """Le due direzioni. Il «falso allarme» qui sarebbe grave: `deploy/index.html:669`
        chiama questa rotta per mostrare all'ospite «= X-Y a testa». Se il tetto avesse murato
        l'anteprima, avremmo riparato un difetto rompendo una cosa che funzionava."""
        import json
        stato, corpo = self._router().gestisci(
            "POST", "/api/split/preview", None,
            json.dumps({"totale_cents": 10000, "n": 3}))
        self.assertEqual(200, stato, "l'anteprima che il sito mostra davvero non risponde "
                                     "piu' 200: %r" % corpo)
        self.assertEqual([3334, 3333, 3333], corpo["quote"],
                         "le quote non sono piu' quelle esatte: %r" % corpo)
        self.assertEqual(10000, corpo["totale_cents"],
                         "conservazione esatta rotta attraverso la rotta vera: %r" % corpo)
        self.assertEqual(3333, corpo["per_persona_min_cents"])
        self.assertEqual(3334, corpo["per_persona_max_cents"])


if __name__ == "__main__":
    unittest.main()
