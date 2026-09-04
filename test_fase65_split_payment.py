"""
Test Fase 65 - Split-payment di gruppo.

Copre: riparto equo esatto (conservazione al centesimo), creazione conto (equo/importi/
fail-closed), pagamento quote + completamento, idempotenza, partecipante ignoto, conto
non aperto, scadenza, ridistribuzione su rinuncia (esatta), annullamento, robustezza, e
stress concorrente (tutti pagano -> raccolto == totale, completato una volta) 10x.
"""
import dataclasses
import os
import shutil
import tempfile
import threading
import unittest

from fase65_split_payment import (
    MAX_PARTECIPANTI, EsitoQuota, GestoreSplit, VoceRidistribuzione,
    crea_gestore_split, riparti_equo,
)


class TestRipartoEquo(unittest.TestCase):
    def test_conservazione_esatta(self):
        for tot, n in ((10000, 3), (10001, 7), (1, 4), (99999, 13), (100, 3)):
            quote = riparti_equo(tot, n)
            self.assertEqual(len(quote), n)
            self.assertEqual(sum(quote), tot)              # zero centesimi persi
            self.assertLessEqual(max(quote) - min(quote), 1)  # equo

    def test_invalido(self):
        self.assertEqual(riparti_equo(-1, 3), [])
        self.assertEqual(riparti_equo(100, 0), [])
        self.assertEqual(riparti_equo(10.0, 3), [])


class TestCreazione(unittest.TestCase):
    def setUp(self):
        self.g = crea_gestore_split()

    def test_crea_equo(self):
        cid = self.g.crea_conto("pren1", "casa", 10000, ["a", "b", "c"])
        st = self.g.stato_conto(cid)
        dovuti = sorted(q["dovuto_cents"] for q in st["quote"])
        self.assertEqual(dovuti, [3333, 3333, 3334])
        self.assertEqual(sum(dovuti), 10000)

    def test_crea_importi_custom(self):
        cid = self.g.crea_conto("pren1", "casa", 10000, ["a", "b"],
                                metodo="importi", importi={"a": 7000, "b": 3000})
        st = self.g.stato_conto(cid)
        self.assertEqual({q["partecipante_id"]: q["dovuto_cents"] for q in st["quote"]},
                         {"a": 7000, "b": 3000})

    def test_importi_somma_sbagliata_rifiutato(self):
        self.assertIsNone(self.g.crea_conto("p", "casa", 10000, ["a", "b"],
                          metodo="importi", importi={"a": 7000, "b": 2000}))

    def test_input_invalido(self):
        self.assertIsNone(self.g.crea_conto("", "casa", 10000, ["a"]))
        self.assertIsNone(self.g.crea_conto("p", "casa", 0, ["a"]))
        self.assertIsNone(self.g.crea_conto("p", "casa", 10.0, ["a"]))
        self.assertIsNone(self.g.crea_conto("p", "casa", 100, []))
        self.assertIsNone(self.g.crea_conto("p", "casa", 100, ["a", "a"]))  # duplicati


class TestPagamento(unittest.TestCase):
    def setUp(self):
        self.g = crea_gestore_split()
        self.cid = self.g.crea_conto("pren1", "casa", 9000, ["a", "b", "c"])

    def test_pagamento_e_completamento(self):
        self.assertFalse(self.g.registra_pagamento(self.cid, "a", idem_key="ka").completato)
        self.g.registra_pagamento(self.cid, "b", idem_key="kb")
        e = self.g.registra_pagamento(self.cid, "c", idem_key="kc")
        self.assertTrue(e.completato)
        st = self.g.stato_conto(self.cid)
        self.assertEqual(st["raccolto_cents"], 9000)
        self.assertEqual(st["mancante_cents"], 0)
        self.assertTrue(st["pronto_per_escrow"])

    def test_idempotente(self):
        self.g.registra_pagamento(self.cid, "a", idem_key="ka")
        e = self.g.registra_pagamento(self.cid, "a", idem_key="ka2")
        self.assertTrue(e.idempotente)
        self.assertEqual(self.g.stato_conto(self.cid)["raccolto_cents"], 3000)

    def test_partecipante_ignoto(self):
        e = self.g.registra_pagamento(self.cid, "zzz", idem_key="k")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "partecipante_ignoto")

    def test_conto_inesistente(self):
        e = self.g.registra_pagamento("mai", "a", idem_key="k")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "conto_inesistente")

    def test_scaduto(self):
        t = {"v": 1000}
        g = crea_gestore_split(orologio=lambda: t["v"])
        cid = g.crea_conto("p", "casa", 6000, ["a", "b"], scadenza=2000)
        t["v"] = 3000
        e = g.registra_pagamento(cid, "a", idem_key="k")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "scaduto")


class TestRidistribuzione(unittest.TestCase):
    def test_chi_paga_copre(self):
        g = crea_gestore_split()
        cid = g.crea_conto("p", "casa", 9000, ["a", "b", "c"])  # 3000 ciascuno
        g.registra_pagamento(cid, "a", idem_key="ka")
        g.registra_pagamento(cid, "b", idem_key="kb")           # c non paga (3000)
        piano = g.ridistribuisci_mancante(cid)
        self.assertTrue(piano["coperto"])
        self.assertEqual(piano["mancante_cents"], 3000)
        self.assertEqual(sum(v.extra_cents for v in piano["voci"]), 3000)  # esatto
        self.assertEqual({v.partecipante_id for v in piano["voci"]}, {"a", "b"})

    def test_nessun_pagatore_non_coperto(self):
        g = crea_gestore_split()
        cid = g.crea_conto("p", "casa", 9000, ["a", "b", "c"])
        piano = g.ridistribuisci_mancante(cid)
        self.assertFalse(piano["coperto"])

    def test_completato_niente_da_ridistribuire(self):
        g = crea_gestore_split()
        cid = g.crea_conto("p", "casa", 6000, ["a", "b"])
        g.registra_pagamento(cid, "a", idem_key="ka")
        g.registra_pagamento(cid, "b", idem_key="kb")
        self.assertFalse(g.ridistribuisci_mancante(cid)["coperto"])

    def test_voci_sono_dataclass(self):
        g = crea_gestore_split()
        cid = g.crea_conto("p", "casa", 9000, ["a", "b", "c"])
        g.registra_pagamento(cid, "a", idem_key="ka")
        piano = g.ridistribuisci_mancante(cid)
        self.assertTrue(all(isinstance(v, VoceRidistribuzione) for v in piano["voci"]))


class TestAnnulla(unittest.TestCase):
    def test_annulla_blocca_pagamenti(self):
        g = crea_gestore_split()
        cid = g.crea_conto("p", "casa", 6000, ["a", "b"])
        self.assertTrue(g.annulla(cid))
        e = g.registra_pagamento(cid, "a", idem_key="k")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "conto_non_aperto")


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        g = crea_gestore_split()
        for bad in (None, 123, [], ""):
            try:
                g.crea_conto(bad, bad, bad, bad)
                g.registra_pagamento(bad, bad, idem_key="k")
                g.stato_conto(bad)
                g.ridistribuisci_mancante(bad)
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")


class TestStress(unittest.TestCase):
    def test_pagamenti_concorrenti_10x(self):
        for rip in range(10):
            d = tempfile.mkdtemp()
            try:
                g = crea_gestore_split(os.path.join(d, f"s{rip}.db"))
                partecipanti = ["u%d" % i for i in range(12)]
                cid = g.crea_conto("p", "casa", 12000, partecipanti)
                esiti = []
                lock = threading.Lock()

                def paga(p):
                    e = g.registra_pagamento(cid, p, idem_key="idem-%s" % p)
                    with lock:
                        esiti.append(e)

                th = [threading.Thread(target=paga, args=(p,)) for p in partecipanti]
                for t in th:
                    t.start()
                for t in th:
                    t.join()
                st = g.stato_conto(cid)
                self.assertEqual(st["raccolto_cents"], 12000)   # conservazione esatta
                self.assertTrue(st["completato"])
                # esattamente un pagamento ha visto il completamento
                self.assertEqual(sum(1 for e in esiti if e.completato), 1)
            finally:
                shutil.rmtree(d, ignore_errors=True)


class TestIBuchiTrovatiDallaMutazione(unittest.TestCase):
    """I punti che il giudice della mutazione ha trovato SCOPERTI il 2026-09-02.

    `fase65_split_payment.py` ha **59 punti di logica sbagliabili e 4 sorveglianti**: il
    rapporto peggiore di tutta la macchina, e il giro l'ha confermato — **15 sopravvissuti
    su 42 punti provati** (i restanti 17 non sono sicuri: non sono stati guardati).
    Nessuno di questi guasti rompe il sito. Fanno sbagliare un conto ogni tanto, che sul
    percorso del denaro e' il modo peggiore di rompersi.

    ⛔ OGNI guardia qui sotto e' stata scritta DOPO aver eseguito il codice sano e
    registrato l'uscita vera, e verificata nei DUE VERSI: verde sul sano, rossa col
    mutante dentro. Non e' pignoleria: ragionando sulla *descrizione* della mutazione
    («`<` diventa `<=`») invece che sul comportamento, l'atteso si inverte con la stessa
    facilita' con cui si azzecca — ed era gia' successo su `riparti_equo`, dove «lo zero
    va respinto» sembrava ovvio ed e' **falso** (lo respinge il mutante, non il sano).
    Una guardia invertita e' rossa sul codice buono, e il passo dopo e' «ripariamo il
    codice» — cioe' il difetto entra passando dalla porta principale.

    ⛔ LA MATRICE GUASTO x GUARDIA, misurata il 2026-09-02 e scritta QUI perche' una
    matrice che vive solo nel registro di una sessione non esiste piu' il giorno dopo.
    Dice quale guardia vede quale guasto: se qualcuno «semplifica» una di queste prove,
    questa tabella dice cosa resta scoperto.

        riga  mutazione                        guardia che diventa ROSSA
        ────  ───────────────────────────────  ─────────────────────────────────────────
         55   totale_cents < 0   ->  <= 0      ..CONTRATTO_anche_a_totale_zero
         62   frozen=True        ->  False     ..gli_esiti_sono_DAVVERO_immutabili
         66   idempotente=False  ->  True      ..pagamento_ESEGUITO_non_si_dichiara_replay
         67   completato=False   ->  True      ..pagamento_FALLITO_non_dichiara..completato
         70   frozen=True        ->  False     ..gli_esiti_sono_DAVVERO_immutabili
        132   `and`              ->  `or`      ..un_alloggio_senza_nome_e_respinto
        141   > MAX_PARTECIPANTI ->  >=        ..confine_dei_partecipanti_e_dove_dice..
        147   `or`               ->  `and`     ..importi_con_chiavi_che_non_sono_i_parte..
        149   `or`               ->  `and`     ..un_importo_NEGATIVO_e_respinto
        149   v < 0              ->  v <= 0    ..un_importo_a_ZERO_e_invece_LEGITTIMO
         83   `or`               ->  `and`     ..l_orologio_iniettato_viene_DAVVERO_usato
        199   `and`              ->  `or`      ..senza_chiave_di_idempotenza_si_RIFIUTA..
        200   EsitoQuota(False)  ->  (True)    ..senza_chiave_di_idempotenza_si_RIFIUTA..
        216   `==`               ->  `!=`      ..il_replay_dice_la_VERITA_sul_completamento
        222   > scadenza         ->  >=        ..la_scadenza_scade_DOPO_l_istante_non_SULL..
        278   `or`               ->  `and`     ..ridistribuire_un_conto_INESISTENTE_non_esplode
        278   <= 0               ->  < 0       ..niente_da_ridistribuire_quando_manca_ZERO
        294   rowcount > 0       ->  >= 0      ..annullare_DUE_VOLTE_non_riesce_la_seconda
        325   check_same_thread  ->  True      ..gestore_in_memoria_si_usa_da_un_ALTRO_thread
        ────  19 celle su 19 ROSSE col guasto dentro · classe intera VERDE sul banco sano
              (la matrice intera costa 5,5 s: gira UNA prova per cella, non i sorveglianti)

    L'iniezione e' avvenuta su una **copia fuori dal progetto**, non qui dentro: mutare
    `fase65_split_payment.py` vorrebbe dire toccare produzione (B4) senza averne il via,
    e non serve — si copiano modulo e prove in una cartella di lavoro e si muta li'.
    Cosi' non resta nemmeno niente da ripristinare byte-identico se la sessione muore a
    meta', che e' il rischio che la ferrea 2 accetta e che questo metodo toglie gratis.
    ⚠️ E il banco va rifatto DA ZERO a ogni cella: la prima versione riusava la cartella e
    tre celle risultavano verdi col guasto dentro — non erano guardie cieche, era un
    `.pyc` vecchio. Un banco che sporca le proprie misure **accusa guardie innocenti**, e
    se ne accorge solo chi rifa' una cella a mano invece di credere all'attrezzo.

    ✅ IL GIRO DEFINITIVO, 2026-09-03 (18 minuti, EXIT=1):
        provati **59 su 59** · uccisi 55 · SOPRAVVISSUTI 4 · scoperti 0 · equivalenti 0
        NON DETERMINABILI 0 · UCCISI SOLO A VOLTE 0
        ri-conferme: 3 chieste, 55 rieseguiti, **non ri-confermati 0**
        NON PROVATI: oltre il tetto **0** · oltre il tempo **0**
    ⇒ Il tetto non ha tagliato niente, e le 15 guardie scritte prima **hanno retto sotto il
      Giudice**: nessuno dei punti gia' chiusi e' tornato vivo. I 4 sopravvissuti erano
      tutti fra i 17 che il giro precedente non aveva mai raggiunto, e sono chiusi qui.

    ⛔ COSA QUESTA CLASSE NON COPRE (D18 punto 3), perche' «19 su 19» non vuol dire «tutto»:
    · le **2 rinunce del generatore** (`{'catena': 2}`): punti che il generatore **non sa
      rompere** e non prova nemmeno. ⚠️ Un punto che nessuno sa rompere **non e' un punto
      sicuro, e' un punto mai guardato** — e restano fuori da qualunque conteggio di uccisi;
    · questo e' **UN modulo su cinque** del percorso del denaro. La casella 5 parla di tutti
      e cinque, e l'attrezzo del Giudice si e' rifiutato da solo di spuntarla: *«questo giro
      ha guardato 1 modulo su 5 ... "non misurata" e' vero, "misurata e non passa" sarebbe
      falso»*;
    · le 19 celle provano che le guardie uccidono i guasti **iniettati a mano**. Il Giudice
      muta a modo suo: che stavolta i due elenchi coincidano non e' garantito per sempre.

    🔑 E la lezione che questo modulo ha pagato per tutti: dei **17 punti «mai esaminati»**
    del giro precedente, **quattro erano abitati**. Non erano «probabilmente a posto»: erano
    non guardati. Il primo l'ha trovato la corsia B **leggendo il codice**, dove il Giudice
    non era ancora arrivato; il Giudice ci e' arrivato dopo e ha detto la stessa cosa.
    **Lettura umana e generatore non si sostituiscono: si coprono i buchi a vicenda.**
    """

    def setUp(self):
        self.g = crea_gestore_split()
        self.cid = self.g.crea_conto("pren1", "casa", 9000, ["a", "b", "c"])

    # ── riga 66: `idempotente: bool = False` ────────────────────────────────────
    def test_un_pagamento_ESEGUITO_non_si_dichiara_replay(self):
        """Il valore di partenza dice «questa operazione e' stata fatta DAVVERO».

        Rovesciato, ogni primo pagamento si annuncia come replay: chi legge quel campo
        per decidere se saltare il lavoro salta un pagamento vero. La guardia non
        asserisce il campo e basta — asserisce che **i soldi si siano mossi quando dice
        di essersi mossi, e non si muovano quando dice di no**: cosi' uccide il mutante
        *e* impedisce il danno, invece di sorvegliare una costante.
        """
        prima = self.g.stato_conto(self.cid)["raccolto_cents"]
        e1 = self.g.registra_pagamento(self.cid, "a", idem_key="k1")
        dopo = self.g.stato_conto(self.cid)["raccolto_cents"]
        self.assertTrue(e1.ok)
        self.assertGreater(dopo, prima,
                           "il primo pagamento non ha mosso niente: la premessa di questa "
                           "guardia non regge e il resto non significherebbe nulla")
        self.assertFalse(e1.idempotente,
                         "un pagamento ESEGUITO si dichiara replay: chi lo legge per "
                         "saltare il lavoro saltera' un pagamento vero")

        e2 = self.g.registra_pagamento(self.cid, "a", idem_key="k2")
        self.assertTrue(e2.idempotente, "il replay non si dichiara replay")
        self.assertEqual(self.g.stato_conto(self.cid)["raccolto_cents"], dopo,
                         "il replay ha mosso altri soldi: e' un doppio addebito")

    # ── riga 67: `completato: bool = False` ─────────────────────────────────────
    def test_un_pagamento_FALLITO_non_dichiara_il_conto_completato(self):
        """Il piu' pericoloso dei quindici, e non sembra.

        Cinque rami di fallimento costruiscono `EsitoQuota(False, "motivo")` e lasciano
        `completato` al suo valore di partenza. Rovesciato, **un pagamento fallito
        annuncia il conto COMPLETATO** — e `completato` e' il campo su cui si decide se
        i soldi sono pronti per uscire dall'escrow. Nessun test lo guardava: si
        controllava il motivo, che e' giusto ma non basta.
        """
        for partecipante, conto, atteso in (("zzz", self.cid, "partecipante_ignoto"),
                                            ("a", "conto_che_non_esiste", "conto_inesistente")):
            e = self.g.registra_pagamento(conto, partecipante, idem_key="k_%s" % atteso)
            self.assertFalse(e.ok)
            self.assertEqual(e.motivo, atteso)
            self.assertFalse(e.completato,
                             "il pagamento e' FALLITO (%s) e l'esito dichiara il conto "
                             "completato: chi legge questo campo libera i soldi su un "
                             "pagamento mai avvenuto" % atteso)

    # ── riga 55: `totale_cents < 0` ─────────────────────────────────────────────
    def test_il_riparto_rispetta_il_CONTRATTO_anche_a_totale_zero(self):
        """Non si asserisce il caso singolo, si asserisce il contratto del docstring.

        ⛔ E `sum` da solo NON basta: col totale a zero il mutante restituisce `[]`, e
        `sum([]) == 0 == totale` **torna lo stesso**. E' `len` che uccide. Un invariante
        che regge anche sul vuoto non e' un invariante che distingue il vuoto.
        """
        for totale, n in ((0, 3), (0, 1), (1, 4), (10, 3), (99999, 13)):
            quote = riparti_equo(totale, n)
            self.assertEqual(len(quote), n,
                             "riparti_equo(%d, %d) ha restituito %d quote invece di %d"
                             % (totale, n, len(quote), n))
            self.assertEqual(sum(quote), totale, "centesimi persi o creati")
            self.assertLessEqual(max(quote) - min(quote), 1, "riparto non equo")

    # ── righe 62 e 70: `@dataclass(frozen=True)` ────────────────────────────────
    def test_gli_esiti_sono_DAVVERO_immutabili(self):
        """Codice difensivo, quindi D19: non si aspetta l'incidente per sapere se la rete
        regge. `frozen=True` non cambia niente finche' nessuno prova a scrivere — ed e'
        esattamente il caso in cui «tanto non capita» non e' una motivazione. Si
        costruisce lo stato «impossibile» adesso, che costa tre righe.
        """
        esito = self.g.registra_pagamento(self.cid, "a", idem_key="kf")
        self.assertIsInstance(
            esito, EsitoQuota,
            "PREMESSA NON VALIDA: non ho in mano un EsitoQuota ma %r. ⛔ Senza questa "
            "riga la prova passava anche su `None`, perche' `None.ok = False` alza un "
            "AttributeError -- che e' un'`Exception` e veniva catturato: diceva "
            "«immutabile» senza aver mai toccato l'oggetto. Trovato dalla corsia B in "
            "revisione incrociata, e verificato: con un oggetto rotto era VERDE." % (esito,))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            esito.ok = False
        voce = VoceRidistribuzione("a", 1)
        self.assertIsInstance(voce, VoceRidistribuzione, "PREMESSA NON VALIDA")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            voce.partecipante_id = "altro"

    # ── riga 132: `isinstance(alloggio_id, str) and alloggio_id.strip()` ────────
    def test_un_alloggio_senza_nome_e_respinto(self):
        """Scambiare `and` con `or` in una validazione non rompe niente: **allarga in
        silenzio cio' che passa**. Qui il mutante accetta un alloggio con id vuoto, e da
        li' in poi esiste un conto attaccato a niente."""
        for vuoto in ("", "   "):
            self.assertIsNone(self.g.crea_conto("p_v", vuoto, 900, ["a"]),
                              "accettato un conto con alloggio_id %r" % vuoto)

    # ── riga 141: `len(ids) > MAX_PARTECIPANTI` ─────────────────────────────────
    def test_il_confine_dei_partecipanti_e_dove_dice_di_essere(self):
        """Il mutante (`>=`) respinge il gruppo da esattamente MAX. Si provano tutti e due
        i lati del confine: quello che deve passare e quello che non deve."""
        al_limite = ["p%d" % i for i in range(MAX_PARTECIPANTI)]
        self.assertIsNotNone(
            self.g.crea_conto("p_max", "casa", MAX_PARTECIPANTI * 100, al_limite),
            "un gruppo da esattamente %d partecipanti e' stato respinto" % MAX_PARTECIPANTI)
        oltre = ["p%d" % i for i in range(MAX_PARTECIPANTI + 1)]
        self.assertIsNone(
            self.g.crea_conto("p_over", "casa", (MAX_PARTECIPANTI + 1) * 100, oltre),
            "un gruppo da %d partecipanti e' passato" % (MAX_PARTECIPANTI + 1))

    # ── righe 147 e 149: le validazioni del metodo 'importi' ────────────────────
    def test_importi_con_chiavi_che_non_sono_i_partecipanti(self):
        """Riga 147, `or` -> `and`: col mutante un dizionario con le chiavi sbagliate
        **prosegue**, e si costruisce un conto le cui quote non appartengono a nessuno."""
        self.assertIsNone(
            self.g.crea_conto("i1", "casa", 300, ["a", "b"], metodo="importi",
                              importi={"a": 100, "zzz": 200}),
            "accettati importi con chiavi diverse dai partecipanti")

    def test_un_importo_NEGATIVO_e_respinto(self):
        """Riga 149, `or` -> `and`: il sano respinge se un importo non e' intero **oppure**
        e' negativo; il mutante solo se e' tutt'e due. Un intero negativo passa — cioe'
        una quota che TOGLIE denaro invece di metterlo, e la somma torna lo stesso."""
        self.assertIsNone(
            self.g.crea_conto("i2", "casa", 300, ["a", "b"], metodo="importi",
                              importi={"a": -100, "b": 400}),
            "accettata una quota negativa")

    def test_un_importo_a_ZERO_e_invece_LEGITTIMO(self):
        """Riga 149, `<` -> `<=`: il mutante respinge la quota a zero. Ma zero e' una
        quota valida — un ospite che non paga nulla perche' un altro copre la sua parte.
        ⛔ Questa guardia pretende che una cosa **passi**, non che venga respinta: e' il
        verso in cui e' facile scrivere l'atteso al contrario, ed e' stato misurato sul
        codice sano prima di essere scritto."""
        self.assertIsNotNone(
            self.g.crea_conto("i3", "casa", 300, ["a", "b"], metodo="importi",
                              importi={"a": 0, "b": 300}),
            "una quota legittima da zero centesimi e' stata respinta")

    # ── riga 83: `self._now = orologio or (lambda: int(time.time()))` ───────────
    def test_l_orologio_iniettato_viene_DAVVERO_usato(self):
        """Col mutante (`or` -> `and`) l'orologio passato dal chiamante viene **buttato** e
        si usa l'ora vera: `orologio and (lambda...)` vale la lambda, non l'orologio.

        ⛔ E si capisce perche' era sopravvissuto: `self._now()` viene chiamato **solo se il
        conto ha una scadenza** (riga 222), e quasi nessuna prova ne mette una. Un pezzo di
        codice che si esegue solo in un ramo raro e' scoperto anche quando il file ha molti
        test: la copertura del FILE non dice niente sulla copertura del RAMO.
        """
        g = crea_gestore_split(orologio=lambda: 999)
        cid = g.crea_conto("p_orol", "casa", 900, ["a"], scadenza=1000)
        e = g.registra_pagamento(cid, "a", idem_key="k")
        self.assertTrue(e.ok,
                        "l'orologio fermo a 999 dice che la scadenza (1000) non e' passata, "
                        "ma il pagamento e' stato rifiutato con %r: l'orologio iniettato non "
                        "viene usato, si guarda l'ora vera" % (e.motivo,))

    # ── riga 222: `self._now() > conto["scadenza"]` ─────────────────────────────
    def test_la_scadenza_scade_DOPO_l_istante_non_SULL_istante(self):
        """Confine: si provano l'istante esatto e il primo che lo supera.

        Misurato sul codice sano prima di scrivere: **a scadenza esatta il pagamento
        PASSA** — si e' in ritardo dall'istante successivo. Col mutante (`>=`) chi paga
        allo scoccare del termine si vede rifiutare, e non capisce perche'.
        """
        for ora, ok_atteso, motivo_atteso in ((999, True, ""),
                                              (1000, True, ""),
                                              (1001, False, "scaduto")):
            g = crea_gestore_split(orologio=lambda o=ora: o)
            cid = g.crea_conto("p_scad", "casa", 900, ["a"], scadenza=1000)
            e = g.registra_pagamento(cid, "a", idem_key="k")
            self.assertEqual(e.ok, ok_atteso,
                             "scadenza 1000, orologio a %d: atteso ok=%s, ottenuto ok=%s "
                             "(motivo %r)" % (ora, ok_atteso, e.ok, e.motivo))
            self.assertEqual(e.motivo, motivo_atteso)

    # ── righe 199 e 200: la chiave di idempotenza ───────────────────────────────
    def test_senza_chiave_di_idempotenza_si_RIFIUTA_e_non_si_muove_niente(self):
        """Due mutanti in un colpo, e il secondo e' il grave.

        · riga 199 (`and` -> `or`): una chiave vuota **passa la validazione**, e il
          pagamento viene registrato senza nessuna chiave che lo renda ripetibile in
          sicurezza — cioe' si perde proprio la protezione contro il doppio addebito.
        · riga 200 (`False` -> `True`): il rifiuto si annuncia come **successo**. Chi lo
          legge crede di aver incassato e non ha incassato niente.
        ⇒ Per questo non basta guardare `motivo`: si guarda `ok` **e** che i soldi non si
          siano mossi. Il motivo giusto con l'esito sbagliato e' peggio di nessun motivo.
        """
        prima = self.g.stato_conto(self.cid)["raccolto_cents"]
        for chiave in ("", "   ", None):
            e = self.g.registra_pagamento(self.cid, "a", idem_key=chiave)
            self.assertFalse(e.ok,
                             "chiave di idempotenza %r accettata, o rifiutata dichiarando "
                             "successo" % (chiave,))
            self.assertEqual(e.motivo, "idem_key_mancante")
        self.assertEqual(self.g.stato_conto(self.cid)["raccolto_cents"], prima,
                         "un pagamento senza chiave ha comunque mosso i soldi")

    # ── riga 216: `completo = conto["stato"] == "completato"` ───────────────────
    def test_il_replay_dice_la_VERITA_sul_completamento(self):
        """Il ramo del replay ricalcola se il conto e' completo. Col mutante (`==` -> `!=`)
        la risposta e' **rovesciata**: chi ripete un pagamento su un conto a meta' si sente
        dire che e' completo — e `completato` e' il campo su cui si decide se i soldi
        escono. Si provano tutti e due i lati, se no meta' del guasto resta invisibile.
        """
        self.g.registra_pagamento(self.cid, "a", idem_key="k1")
        meta = self.g.registra_pagamento(self.cid, "a", idem_key="k2")
        self.assertTrue(meta.idempotente, "la premessa non regge: questo non e' un replay")
        self.assertFalse(meta.completato,
                         "replay su un conto pagato per un terzo, e l'esito dice che e' "
                         "COMPLETO: chi legge questo campo libera i soldi a meta' incasso")

        self.g.registra_pagamento(self.cid, "b", idem_key="k3")
        self.g.registra_pagamento(self.cid, "c", idem_key="k4")
        self.assertEqual(self.g.stato_conto(self.cid)["stato"], "completato",
                         "la premessa non regge: il conto doveva essere completo")
        pieno = self.g.registra_pagamento(self.cid, "c", idem_key="k5")
        self.assertTrue(pieno.idempotente)
        self.assertTrue(pieno.completato,
                        "replay su un conto COMPLETO, e l'esito dice che non lo e'")

    # ── riga 294: `return cur.rowcount > 0` (compare-and-swap di `annulla`) ─────
    def test_annullare_DUE_VOLTE_non_riesce_la_seconda(self):
        """`annulla` e' un COMPARE-AND-SWAP: `UPDATE ... WHERE stato='aperto'`, e risponde
        guardando **quante righe ha davvero cambiato**. Il vecchio
        `test_annulla_blocca_pagamenti` prova solo il caso in cui il CAS **vince**; quello
        che conta e' il secondo, dove non deve vincere piu'.

        Col mutante (`>= 0`) `rowcount` vale 0 e la risposta e' comunque `True`: due
        persone credono entrambe di aver annullato, e la seconda non sa che stava
        chiudendo un conto gia' chiuso da un'altra.
        🔑 Questo punto ha DUE conferme indipendenti: la corsia B l'ha trovato **leggendo**
        il codice, dove il Giudice non era ancora arrivato (era fra i 17 punti mai
        esaminati), e il giro definitivo l'ha poi confermato SOPRAVVISSUTO. Lettura umana e
        generatore non si sostituiscono: si coprono i buchi a vicenda.
        """
        self.assertTrue(self.g.annulla(self.cid),
                        "PREMESSA NON VALIDA: il primo annullamento doveva riuscire")
        self.assertFalse(self.g.annulla(self.cid),
                         "il SECONDO annullamento dice di essere riuscito: il "
                         "compare-and-swap non risponde su cio' che ha davvero cambiato")
        self.assertFalse(self.g.annulla("conto_mai_esistito"),
                         "annullare un conto inesistente dice di essere riuscito")

    # ── riga 278, primo `or`: `st is None or st["completato"] or ...` ──────────
    def test_ridistribuire_un_conto_INESISTENTE_non_esplode(self):
        """Col mutante (`or` -> `and`) la guardia diventa `st is None and st["completato"]`:
        quando `st` E' None, Python valuta comunque il secondo pezzo e alza
        `TypeError: 'NoneType' object is not subscriptable`.

        ⛔ Il cortocircuito di `or` non e' uno stile: **e' la protezione**. Scambiarlo con
        `and` trasforma un ritorno pulito in un'eccezione, e un'eccezione qui arriva a chi
        sta chiudendo un conto scaduto.
        """
        piano = self.g.ridistribuisci_mancante("conto_mai_esistito")
        self.assertEqual(piano, {"coperto": False, "mancante_cents": 0, "voci": []},
                         "un conto inesistente non produce il piano vuoto: %r" % (piano,))

    # ── riga 278, `<=`: `st["mancante_cents"] <= 0` ────────────────────────────
    def test_niente_da_ridistribuire_quando_manca_ZERO(self):
        """⛔ QUESTO MUTANTE SEMBRAVA EQUIVALENTE, E NON LO E'.

        Ragionamento che invitava a dichiararlo tale: `mancante_cents` non va mai sotto
        zero (le quote sommano esattamente al totale), e vale zero **solo** quando il conto
        e' completato — che la condizione precedente ha gia' intercettato. Quindi `<= 0` e
        `< 0` sembrano indistinguibili.
        ⇒ Ma e' una conclusione **con una premessa**: vale *per merito di*
        `registra_pagamento`, che marca «completato» quando il raccolto arriva al totale.
        D19 punto 1 vieta esattamente questo — «oggi non si raggiunge» non e' una proprieta'
        del codice, e' un'ipotesi su un'altra funzione. E B6 vieta di dichiarare equivalente
        un mutante senza dimostrazione.
        👉 Quindi lo stato «impossibile» si costruisce **a mano, adesso, che costa tre
        righe** (D19 punto 3): un conto pagato per intero a cui si rimette lo stato
        «aperto». Li' `mancante` vale 0 con `completato` falso, e i due operatori si
        separano: il sano dice «niente da ridistribuire», il mutante prosegue e
        ridistribuisce ZERO fra chi ha pagato, restituendo `coperto=True` con voci a zero.
        """
        for x in ("a", "b", "c"):
            self.g.registra_pagamento(self.cid, x, idem_key="k" + x)
        con = self.g._apri()
        try:
            con.execute("UPDATE conti SET stato='aperto' WHERE conto_id=?", (self.cid,))
            con.commit()
        finally:
            con.close()

        st = self.g.stato_conto(self.cid)
        self.assertEqual(st["mancante_cents"], 0,
                         "PREMESSA NON VALIDA: doveva mancare zero")
        self.assertFalse(st["completato"],
                         "PREMESSA NON VALIDA: lo stato «impossibile» non e' stato costruito")

        piano = self.g.ridistribuisci_mancante(self.cid)
        self.assertFalse(piano["coperto"],
                         "manca ZERO e il piano dice di aver coperto qualcosa: si sta "
                         "ridistribuendo il nulla fra chi ha gia' pagato (%r)" % (piano,))
        self.assertEqual(piano["voci"], [], "voci a zero centesimi in un piano vuoto")

    # ── riga 325: `sqlite3.connect(":memory:", check_same_thread=False)` ───────
    def test_il_gestore_in_memoria_si_usa_da_un_ALTRO_thread(self):
        """`check_same_thread=False` non e' un dettaglio di configurazione: e' cio' che
        permette al server di servire due richieste su thread diversi con lo stesso
        gestore. Col mutante (`True`) qualunque uso da un altro thread alza
        `ProgrammingError`, e il primo a scoprirlo sarebbe un ospite che paga.

        ⚠️ Il banco esistente sotto carico usa un percorso su file, non `:memory:`: per
        questo il punto era rimasto scoperto pur avendo il file un test di concorrenza.
        """
        esito = {}

        def _da_un_altro_thread():
            try:
                esito["r"] = self.g.registra_pagamento(self.cid, "a", idem_key="kt")
            except Exception as e:                       # noqa: BLE001 — serve il nome
                esito["errore"] = "%s: %s" % (type(e).__name__, e)

        t = threading.Thread(target=_da_un_altro_thread)
        t.start()
        t.join(timeout=30)
        self.assertNotIn("errore", esito,
                         "il gestore in memoria non si lascia usare da un altro thread: %s"
                         % esito.get("errore"))
        self.assertTrue(esito["r"].ok)
        self.assertEqual(self.g.stato_conto(self.cid)["raccolto_cents"], 3000,
                         "il pagamento dall'altro thread non ha lasciato traccia")


class TestIBuchiDelGiudice(unittest.TestCase):
    """Una guardia, per l'unico mutante SOPRAVVISSUTO al giro del Giudice del 2026-09-04 col SOLO
    test dedicato (59 punti: 58 uccisi). Vista ROSSA contro il mutante prima che verde (D20).
    Con questa il dedicato basta da solo a sorvegliare il modulo."""

    def test_riga218_un_replay_e_un_successo_ok_True_non_un_fallimento_travestito(self):
        # Col mutante (True -> False) il replay risponde ok=False con motivo vuoto: chi legge `ok`
        # per decidere se ritentare ritenta un pagamento gia' fatto, e chi mostra l'esito
        # all'ospite gli dice «fallito» su una quota gia' pagata.
        g = crea_gestore_split()
        cid = g.crea_conto("pren1", "casa", 9000, ["a", "b", "c"])
        self.assertIs(g.registra_pagamento(cid, "a", idem_key="k1").ok, True)
        e = g.registra_pagamento(cid, "a", idem_key="k2")            # replay
        self.assertIs(e.ok, True)
        self.assertEqual(e.motivo, "")
        self.assertIs(e.idempotente, True)
        self.assertIs(e.completato, False)
        g.registra_pagamento(cid, "b", idem_key="kb")
        g.registra_pagamento(cid, "c", idem_key="kc")
        e3 = g.registra_pagamento(cid, "c", idem_key="kc2")          # replay su conto completato
        self.assertEqual((e3.ok, e3.idempotente, e3.completato), (True, True, True))


if __name__ == "__main__":
    unittest.main()
