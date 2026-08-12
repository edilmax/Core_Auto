# -*- coding: utf-8 -*-
"""🛡️ LE GUARDIE SUL PIANO DEI SOLDI — il giudizio sta in `collaudi/piano_dei_soldi.py`.

⛔ QUI NON C'E' NESSUN CRITERIO. Le regole di lettura, i marcatori e il testo dei rossi
stanno in **un posto solo**, `collaudi/piano_dei_soldi.py`, che questo file importa e che il
**pre-fatto** usa per fermare il commit in 0,1 secondi. Copiarne un pezzo qui sarebbe la
malattia che tutto questo lavoro esiste per curare: *lo stesso criterio scritto due volte, e
la seconda copia che resta indietro.*

I MODULI FINTI SI CHIAMANO `fase9NN`, E NON E' UN VEZZO. Nominare `fase133` in un esempio fa
salire il conto dei «test che lo nominano», cioe' la colonna con cui il piano decide **quale
modulo e' piu' cieco**. E' la trappola scritta a `RIPRENDI_QUI.md:718` -- *«fase85 ha 77 test
che lo nominano ma lo FINGONO: nominare non e' provare»*. Con numeri inventati quel rumore
non c'e'. I nomi veri restano **solo** dove la voce vera E' l'oggetto della prova (`fase147`
con la spunta, `fase133 (gia' fatto in 1)`): li' il legame col difetto reale e' il punto.
"""
import unittest

from collaudi import piano_dei_soldi as pds
from collaudi import raggiungibilita

FATTO, DA_FARE, MORTO = pds.FATTO, pds.DA_FARE, pds.MORTO


# --------------------------------------------------------------------------------------
# un piano SANO in miniatura, con moduli INVENTATI: e' il banco su cui si iniettano i guasti
# --------------------------------------------------------------------------------------
SANO_REGISTRO = (
    "## 2-bis) DA FARE\n\n"
    "\U0001f4ca **DOVE SIAMO, rimisurato col censimento il 2026-01-01**:\n"
    "**1 moduli dei soldi giudicati** · **1 che restano, per 24 punti**. "
    "Uno: uno sono stati fatti (`fase901`) e **uno e' uscito perche' e' codice\n"
    "morto** (`fase903` 31 = **31 punti che non vanno fatti**).\n\n"
    "| blocco | moduli | punti |\n|---|---|---|\n"
    "| **1** | ✅ `fase901_credito` **FATTO 2026-01-01** · ▶️ `fase902_split` (24) | 24 |\n"
    "| **2** | ⛔ `fase903_commissione` **TOLTO: e' CODICE MORTO** | 0 |\n\n")
SANO_CONSEGNE = (
    "### QUANTO MANCA SUI SOLDI\n\n"
    "**Moduli dei SOLDI GIÀ passati dal giudice — 1:**\n"
    "✅ **`fase901_credito`** (11 su 11 uccisi).\n\n"
    "**Moduli dei SOLDI CHE RESTANO — 1, per 24 punti.**\n\n"
    "| modulo | punti | lo nominano | blocco |\n|---|---|---|---|\n"
    "| `fase902_split` | 24 | **2** | 1 |\n\n"
    "⛔ **FUORI DALL'ELENCO PERCHÈ SONO CODICE MORTO**:\n"
    "`fase903_commissione` (31) = **31 punti che NON vanno fatti**.\n\n")


def _veri():
    return pds.leggi(pds.REGISTRO), pds.leggi(pds.CONSEGNE)


# --------------------------------------------------------------------------------------
# ① i documenti VERI di adesso
# --------------------------------------------------------------------------------------
class TestIlPianoVeroNonSiContraddice(unittest.TestCase):
    """Il difetto del 2026-08-12: FATTO in un posto, DA FARE in un altro."""

    def setUp(self):
        self.registro, self.consegne = _veri()
        self.tutte = pds.osservazioni(self.registro, self.consegne)

    def test_I_TRE_POSTI_VERI_SONO_D_ACCORDO(self):
        _vivi, morti, _t = raggiungibilita.cammina()
        va_bene, righe = pds.rapporto(self.registro, self.consegne, morti)
        self.assertTrue(va_bene,
                        "\n".join(righe) + "\n\nAllinea i tre posti nello STESSO commit, non "
                        "«dopo»: il «dopo» e' dove si perde (sbaglio S10).\n\nCosa questo "
                        "controllo NON esamina:\n" + pds.limiti_dichiarati())

    def test_IL_DENOMINATORE_NON_E_CROLLATO(self):
        """Se un posto smettesse di nominare i moduli, il confronto sarebbe fra insiemi di
        cui uno vuoto -- e non troverebbe mai niente, restando verde per sempre (S1)."""
        for nome, quante in (
                ("tabella dei blocchi", pds.posto1_tabella_dei_blocchi(self.registro)),
                ("riepilogo DOVE SIAMO", pds.posto2_riepilogo(self.registro)[0]),
                ("QUANTO MANCA SUI SOLDI", pds.posto3_censimento(self.consegne)[0])):
            self.assertTrue(
                quante,
                "il posto «%s» non nomina nessun modulo: un confronto fra tre posti di cui "
                "uno vuoto e' un verde che non guarda niente" % nome)
        distinti = set(m for m, _s, _d in self.tutte)
        self.assertGreaterEqual(
            len(distinti), 15,
            "il guardiano legge solo %d moduli dai tre posti: al 2026-08-12 erano 20 (6 "
            "fatti + 11 da fare + 3 morti). Un denominatore che crolla e' un controllo che "
            "ha smesso di guardare, non un piano che si e' accorciato" % len(distinti))

    def test_OGNI_MODULO_CHE_RESTA_STA_ANCHE_IN_UN_BLOCCO(self):
        """⛔ IL DIFETTO DI `fase147`, che il confronto fra stati NON PUO' VEDERE.

        L'11 agosto `fase147_tassa_comunale` era **vivo, dei soldi, e in nessun blocco**:
        fuori da ogni blocco significa **mai giudicato, per sempre**. Cercare contraddizioni
        non lo trova, perche' un modulo che sta in UN posto solo non contraddice nessuno.
        Serve l'altra domanda: *ogni modulo da fare e' stato assegnato a un blocco?*
        """
        orfani = pds.orfani_senza_blocco(self.registro, self.consegne)
        self.assertEqual(
            [], orfani,
            "questi moduli dei soldi sono nella tabella «che restano» ma NON stanno in "
            "nessun blocco: %s. Fuori da ogni blocco vuol dire che nessuno li prendera' in "
            "mano -- mai giudicati, per sempre. E' il difetto di `fase147_tassa_comunale`, "
            "trovato l'11 agosto." % ", ".join(orfani))

    def test_NESSUN_MODULO_DA_FARE_E_CODICE_MORTO(self):
        """Il difetto del 2026-08-11: `fase43_commissione` nel piano, e la produzione non lo
        raggiunge. Erano 31 punti su 506 che stavano per essere buttati."""
        _vivi, morti, _t = raggiungibilita.cammina()
        sprecati = pds.da_fare_ma_morti(self.tutte, morti)
        self.assertEqual(
            [], sprecati,
            "il piano manda a setacciare %d modulo/i che la produzione NON RAGGIUNGE: %s. "
            "Togli quei moduli dichiarando i punti che NON vanno fatti, come e' stato fatto "
            "per fase43/fase44/fase35.\n\nCosa NON esamina:\n%s"
            % (len(sprecati), ", ".join(sprecati), pds.limiti_dichiarati()))


class TestIContiDelPianoVeroTornano(unittest.TestCase):
    """Un elenco senza denominatore non dice quanto manca (D22).

    ⛔ IL CRITERIO NON E' RICOPIATO QUI: sta in `pds.conti_che_non_tornano`, che e' la stessa
    funzione che il pre-fatto chiama al commit. Riscriverlo qui sarebbe una seconda copia --
    e con due copie, il giorno che una cambia, l'altra assolve.
    """

    def test_I_CONTI_DEL_PIANO_VERO_TORNANO(self):
        registro, consegne = _veri()
        guasti = pds.conti_che_non_tornano(registro, consegne)
        self.assertEqual([], guasti, "\n   ".join([""] + guasti))

    def test_OGNI_CONTO_SBAGLIATO_VIENE_VISTO_UNO_ALLA_VOLTA(self):
        """Le quattro cifre scritte a mano, sporcate una per una sul banco finto.

        ⛔ Una per volta e non tutte insieme: se ne sporcassi due e vedessi un rosso, non
        saprei quale delle due l'ha prodotto -- e una potrebbe non essere guardata affatto.
        E' il denominatore applicato alle iniezioni.
        """
        self.assertEqual([], pds.conti_che_non_tornano(SANO_REGISTRO, SANO_CONSEGNE),
                         "grida su un piano sano: allarme sempre acceso, verra' spento")
        iniezioni = (
            ("il conto dei giudicati nel REGISTRO",
             SANO_REGISTRO.replace("**1 moduli dei soldi giudicati**",
                                   "**7 moduli dei soldi giudicati**"), SANO_CONSEGNE),
            ("il titolo dei giudicati nelle CONSEGNE", SANO_REGISTRO,
             SANO_CONSEGNE.replace("passati dal giudice — 1:", "passati dal giudice — 4:")),
            ("il numero di quelli che restano", SANO_REGISTRO,
             SANO_CONSEGNE.replace("CHE RESTANO — 1, per 24", "CHE RESTANO — 9, per 24")),
            ("il totale dei punti", SANO_REGISTRO,
             SANO_CONSEGNE.replace("CHE RESTANO — 1, per 24", "CHE RESTANO — 1, per 99")),
        )
        for cosa, reg, con in iniezioni:
            self.assertTrue(
                pds.conti_che_non_tornano(reg, con),
                "ho sporcato %s e il guardiano non se n'e' accorto: quella cifra non e' "
                "sorvegliata da nessuno" % cosa)


# --------------------------------------------------------------------------------------
# ② le DUE DIREZIONI, sul banco finto
# --------------------------------------------------------------------------------------
class TestIlGuardianoSaDireANCHESI(unittest.TestCase):
    """Un guardiano provato in un verso solo potrebbe tacere sempre: sarebbe indistinguibile
    da un ornamento (regola ferrea 10)."""

    def test_TACE_SU_UN_PIANO_SANO(self):
        va_bene, righe = pds.rapporto(SANO_REGISTRO, SANO_CONSEGNE, ["fase999_inesistente"])
        self.assertTrue(va_bene, "grida su un piano sano: %s" % righe)
        self.assertEqual([], righe)

    def test_GRIDA_SUL_DIFETTO_DEL_12_AGOSTO(self):
        """`fase902` finito nei blocchi e ancora aperto nelle consegne: la forma esatta."""
        rotto = SANO_REGISTRO.replace("▶️ `fase902_split` (24)",
                                      "✅ `fase902_split` **FATTO 2026-01-02**")
        self.assertNotEqual(rotto, SANO_REGISTRO, "l'iniezione non ha cambiato niente")
        trovate = pds.contraddizioni(pds.osservazioni(rotto, SANO_CONSEGNE))
        self.assertIn("fase902", trovate,
                      "il modulo e' FATTO in un posto e DA FARE nell'altro e il guardiano tace")
        self.assertEqual(set([FATTO, DA_FARE]), set(trovate["fase902"]))

    def test_GRIDA_SU_UN_MODULO_MORTO_LASCIATO_NEL_PIANO(self):
        tutte = pds.osservazioni(SANO_REGISTRO, SANO_CONSEGNE)
        self.assertEqual([], pds.da_fare_ma_morti(tutte, ["fase999_inesistente"]),
                         "nessun modulo del piano e' fra i morti: deve tacere")
        self.assertEqual(["fase902"], pds.da_fare_ma_morti(tutte, ["fase902_split"]),
                         "il modulo da fare e' dichiarato morto e il guardiano non lo dice")

    def test_QUATTRO_VARIANTI_DELLO_STESSO_DIFETTO(self):
        """⛔ REGOLA #9 DELL'APPENDICE: «un fix cucito sul caso di prova supera anche il
        visto-rosso ed e' sbagliato lo stesso: la guardia ha visto IL BUG, non IL
        COMPORTAMENTO». Le due iniezioni storiche non bastano: qui quattro forme diverse,
        ognuna un modo di rompersi che altrimenti non saprei.
        """
        # V1 -- un ALTRO modulo: scopre se il giudizio e' cucito su un numero particolare.
        v1 = SANO_REGISTRO.replace("⛔ `fase903_commissione` **TOLTO: e' CODICE MORTO**",
                                   "✅ `fase903_commissione` **FATTO**")
        self.assertIn("fase903", pds.contraddizioni(pds.osservazioni(v1, SANO_CONSEGNE)),
                      "V1: cambia il modulo e il giudizio diventa cieco")

        # V2 -- coppia di stati MAI esercitata: FATTO contro CODICE MORTO.
        v2 = set(pds.contraddizioni([("fase904", FATTO, "posto A"),
                                     ("fase904", MORTO, "posto B")])["fase904"])
        self.assertEqual(set([FATTO, MORTO]), v2,
                         "V2: FATTO-contro-MORTO e' una contraddizione come le altre")

        # V3 -- il difetto DENTRO UN POSTO SOLO: due blocchi della stessa tabella.
        v3 = SANO_REGISTRO.replace(
            "| **2** | ⛔ `fase903_commissione` **TOLTO: e' CODICE MORTO** | 0 |",
            "| **2** | ✅ `fase902_split` **FATTO** | 0 |")
        self.assertIn("fase902", pds.contraddizioni(pds.posto1_tabella_dei_blocchi(v3)),
                      "V3: due blocchi della STESSA tabella si contraddicono e nessuno lo dice")

        # V4 -- nome INTERO in un posto e ABBREVIATO nell'altro: i documenti veri lo fanno.
        v4 = SANO_CONSEGNE.replace("| `fase902_split` |", "| `fase902` |")
        self.assertNotEqual(v4, SANO_CONSEGNE, "l'iniezione non ha cambiato niente")
        va_bene, _righe = pds.rapporto(SANO_REGISTRO, v4, ["fase999_x"])
        self.assertTrue(va_bene,
                        "V4: `fase902` e `fase902_split` sono LO STESSO modulo, e il "
                        "guardiano li ha trattati come due: griderebbe a torto ogni volta "
                        "che un documento abbrevia un nome")

    def test_IL_ROSSO_NOMINA_IL_COLPEVOLE(self):
        """Non basta che gridi: deve gridare PER QUESTO. Un allarme che suona per la ragione
        sbagliata passerebbe lo stesso, e nessuno saprebbe dove guardare."""
        rotto = SANO_REGISTRO.replace("▶️ `fase902_split` (24)",
                                      "✅ `fase902_split` **FATTO 2026-01-02**")
        va_bene, righe = pds.rapporto(rotto, SANO_CONSEGNE, ["fase903_commissione"])
        self.assertFalse(va_bene)
        testo = "\n".join(righe)
        self.assertIn("fase902", testo, "il rapporto non nomina il modulo colpevole: %s" % testo)
        self.assertIn("2026-08-12", testo, "non dice di quale difetto storico si tratta")
        self.assertIn("blocco", testo, "non dice in QUALE posto: %s" % testo)

    def test_LA_SPUNTA_VERDE_NON_E_IL_MARCATORE(self):
        """`✅ fase147 AGGIUNTO` ha la spunta e NON e' fatto. Leggere la spunta darebbe un
        falso allarme su un modulo aperto, e un falso allarme insegna a ignorare i segnali."""
        self.assertEqual(DA_FARE, pds.stato_della_voce(
            " ✅ `fase147_tassa_comunale` **AGGIUNTO: e' VIVO e il piano se lo dimenticava**"))
        self.assertEqual(FATTO, pds.stato_della_voce(
            " ✅ `fase66_tassa_soggiorno` **FATTO 2026-08-12** (24/24 uccisi)"))
        self.assertEqual(MORTO, pds.stato_della_voce(
            " ⛔ `fase43_commissione` **TOLTO: e' CODICE MORTO**"))

    def test_GIA_FATTO_IN_MINUSCOLO_NON_E_UN_FATTO(self):
        """Nel Blocco 3 c'e' `fase133 (gia' fatto in 1)`: vuol dire «gia' ELENCATO nel Blocco
        1». Con un `.upper()` diventerebbe FATTO e il guardiano griderebbe a torto."""
        self.assertEqual(DA_FARE, pds.stato_della_voce(" `fase133` (gia' fatto in 1)"))
        self.assertEqual(DA_FARE, pds.stato_della_voce(" `fase133` (già fatto in 1)"))

    def test_UN_POSTO_CHE_MANCA_NON_E_UN_VERDE(self):
        """S1: il vuoto non e' un valore, e' assenza di misura. Un guardiano che sui documenti
        riscritti resta verde e' peggio di nessun guardiano, perche' rassicura."""
        for testo, cosa in (("nessuna tabella qui", "prosa senza tabella"),
                            ("", "documento vuoto")):
            with self.assertRaises(pds.MisuraNonValida, msg="%s: passato liscio" % cosa):
                pds.posto1_tabella_dei_blocchi(testo)
        with self.assertRaises(pds.MisuraNonValida):
            pds.posto2_riepilogo("niente riepilogo")
        with self.assertRaises(pds.MisuraNonValida):
            pds.posto3_censimento("niente censimento")
        # E anche quando l'ancora c'e' ma il conto e' sparito: mezza misura non e' una misura.
        senza = SANO_REGISTRO.replace("**1 moduli dei soldi giudicati**", "tanti")
        with self.assertRaises(pds.MisuraNonValida):
            pds.posto2_riepilogo(senza)

    def test_GLI_ESTREMI_NON_LO_FANNO_NE_MENTIRE_NE_ESPLODERE(self):
        """Collaudo ⑥. Un guardiano che esplode blocca il lavoro di tutti; uno che tace su un
        documento assurdo e' peggio. Qui gli estremi che un documento vero puo' assumere."""
        # una tabella «che restano» SENZA righe: dichiara 1 e ne ha 0 -> il conto non torna,
        # e il guardiano lo deve dire invece di considerarla vuota-e-quindi-sana.
        vuota = SANO_CONSEGNE.replace("| `fase902_split` | 24 | **2** | 1 |\n", "")
        _oss, conti = pds.posto3_censimento(vuota)
        self.assertEqual(0, conti["punti_tabella"],
                         "una tabella senza righe deve sommare 0, non inventare")
        self.assertEqual(1, conti["restano"],
                         "il titolo dichiara ancora 1: e' il disallineamento da vedere")

        # `fase0`: numero valido e limite basso. Non deve esplodere nell'ordinamento.
        self.assertEqual(["fase0"], pds.da_fare_ma_morti(
            [("fase0", DA_FARE, "posto A")], ["fase0_zero"]))

        # un numero assurdamente grande: e' testo, non deve rompere niente.
        grande = "fase99999999999"
        self.assertEqual([grande], pds.da_fare_ma_morti(
            [(grande, DA_FARE, "posto A")], [grande + "_x"]))

        # lo STESSO modulo dichiarato dieci volte nello stesso stato non e' una contraddizione.
        dieci = [("fase905", DA_FARE, "posto %d" % i) for i in range(10)]
        self.assertEqual({}, pds.contraddizioni(dieci),
                         "dieci volte lo stesso stato non e' un disaccordo")

        # nessun modulo da nessuna parte: `contraddizioni` non inventa un rosso...
        self.assertEqual({}, pds.contraddizioni([]))
        # ...ma `posto1` su un testo senza moduli GRIDA, perche' li' il vuoto e' sospetto.
        with self.assertRaises(pds.MisuraNonValida):
            pds.posto1_tabella_dei_blocchi("| **1** | nessun modulo qui | 0 |")

    def test_DICHIARA_COSA_NON_CONTROLLA(self):
        """D18 punto 3. Le righe finiscono dentro il testo di ogni rosso, cioe' si leggono nel
        momento in cui servono, non in un documento che nessuno apre."""
        self.assertGreaterEqual(len(pds.NON_CONTROLLO), 4)
        for riga in pds.NON_CONTROLLO:
            self.assertGreater(len(riga), 40,
                               "un limite dichiarato in tre parole non e' un limite "
                               "dichiarato: %r" % riga)
        tutto = " ".join(pds.NON_CONTROLLO)
        self.assertIn("QUARTO posto", tutto,
                      "manca il limite dei TRE posti noti: se qualcuno ne apre un quarto, "
                      "questo guardiano non lo sa")
        self.assertIn("MODULO VIVO CON DENTRO CODICE MORTO", tutto,
                      "manca il buco piu' grosso, misurato il 2026-08-12 su fase133: "
                      "`raggiungibilita.py` conta gli import, non i simboli usati")


# --------------------------------------------------------------------------------------
# ③ IL GIUDICE, sul giudizio stesso
# --------------------------------------------------------------------------------------
def _modulo_mutato(cerca, sostituisci):
    """`collaudi/piano_dei_soldi.py` con UNA decisione rotta, eseguito in memoria.

    ⛔ IL FILE SU DISCO NON VIENE TOCCATO. B2 vieta le sostituzioni testuali sui file del
    progetto, e un collaudo che riscrive un attrezzo vero e' un rischio che non serve
    correre: se il giro muore a meta', il guasto resta dentro. Qui si legge il sorgente, si
    sostituisce nella stringa e si esegue in un modulo nuovo -- il disco resta intatto.
    ⛔ E si pretende che la riga cercata combaci UNA VOLTA SOLA: un mutante che non trova il
    suo bersaglio e' un verde che non ha guardato niente.
    """
    import io
    import os
    import types
    percorso = os.path.join(pds.RADICE, "collaudi", "piano_dei_soldi.py")
    with io.open(percorso, encoding="utf-8") as f:
        sorgente = f.read()
    quante = sorgente.count(cerca)
    if quante != 1:
        raise AssertionError(
            "il mutante non trova il suo bersaglio una volta sola (%d volte): %r. Il "
            "giudizio e' stato riscritto e questo mutante non prova piu' niente."
            % (quante, cerca))
    modulo = types.ModuleType("piano_dei_soldi_mutato")
    # `__file__` serve al modulo per ricavare la radice del progetto: si passa quello VERO,
    # se no il mutante cercherebbe i documenti nel posto sbagliato e morirebbe per il motivo
    # sbagliato -- un rosso che non c'entra niente col guasto iniettato.
    modulo.__dict__["__file__"] = percorso
    codice = compile(sorgente.replace(cerca, sostituisci), "<mutato>", "exec")
    exec(codice, modulo.__dict__)  # noqa: S102  -- e' il mestiere di un giudice di mutazione
    return modulo


class TestIlGiudizioNonSopravviveAiMutanti(unittest.TestCase):
    """④ LA MUTAZIONE, PER ULTIMA -- l'unico collaudo che giudica i COLLAUDI, non il codice.

    `collaudi/mutazione_prodotto.py` mette alla prova i `fase*.py` della produzione: un
    attrezzo dentro `collaudi/` non lo guarda nessuno. Qui il giudizio sul piano dei soldi
    viene rotto di proposito, **un mutante per ogni decisione che prende**, e si pretende che
    il verdetto CAMBI. Se non cambia, quella decisione non e' sorvegliata da niente.

    ⛔ I mutanti non sono scelti per confermare i guasti che avevo già in mente (appendice
    #12): sono uno per `if`, uno per operatore di insiemi, uno per blocco di `rapporto`.
    ⛔ E ognuno porta con se' **l'ingresso che lo uccide**: un mutante senza il suo caso e'
    una domanda senza risposta.
    """

    # SANO -> il verdetto atteso e' True (va bene). Ogni riga qui e' (etichetta, cerca,
    # sostituisci, registro, consegne, morti, verdetto_atteso_dal_giudizio_SANO).
    def _verdetto(self, modulo, reg, con, morti):
        return modulo.rapporto(reg, con, morti)[0]

    def test_OGNI_DECISIONE_DEL_GIUDIZIO_E_SORVEGLIATA(self):
        rotto_contraddizione = SANO_REGISTRO.replace(
            "▶️ `fase902_split` (24)", "✅ `fase902_split` **FATTO**")
        rotto_minuscolo = SANO_REGISTRO.replace(
            "▶️ `fase902_split` (24)", "`fase902_split` (gia' fatto in 1)")
        rotto_orfano = SANO_REGISTRO.replace(" · ▶️ `fase902_split` (24)", "")
        rotto_conti = SANO_CONSEGNE.replace("CHE RESTANO — 1, per 24",
                                            "CHE RESTANO — 9, per 24")
        sani = ["fase999_inesistente"]

        mutanti = (
            ("① il ramo CODICE MORTO in `stato_della_voce`",
             'if "CODICE MORTO" in voce:\n        return MORTO\n    if "FATTO" in voce:',
             'if "FATTO" in voce:',
             SANO_REGISTRO, SANO_CONSEGNE, sani, True),
            ("② il case di `FATTO` (il tranello di «gia' fatto»)",
             'if "FATTO" in voce:\n        return FATTO',
             'if "FATTO" in voce.upper():\n        return FATTO',
             rotto_minuscolo, SANO_CONSEGNE, sani, True),
            ("③ la soglia di `contraddizioni`",
             "if len(s) > 1)", "if len(s) > 2)",
             rotto_contraddizione, SANO_CONSEGNE, sani, False),
            ("④ l'intersezione di `da_fare_ma_morti`",
             "return sorted(dichiarati & numeri_morti", "return sorted(set() & numeri_morti",
             SANO_REGISTRO, SANO_CONSEGNE, ["fase902_split"], False),
            ("⑤ la differenza di `orfani_senza_blocco`",
             "return sorted(da_fare - nei_blocchi", "return sorted(da_fare - da_fare",
             rotto_orfano, SANO_CONSEGNE, sani, False),
            ("⑥ il blocco dei conti dentro `rapporto`",
             'for guasto in conti_che_non_tornano(registro, consegne):\n        righe.append',
             'for guasto in []:\n        righe.append',
             SANO_REGISTRO, rotto_conti, sani, False),
        )

        sopravvissuti = []
        for etichetta, cerca, sostituisci, reg, con, morti, atteso in mutanti:
            sano = self._verdetto(pds, reg, con, morti)
            self.assertEqual(
                atteso, sano,
                "il giudizio SANO non da' il verdetto atteso su «%s»: prima di giudicare un "
                "mutante bisogna sapere cosa dice la macchina sana, se no il confronto non "
                "significa niente (D18 punto 1)" % etichetta)
            mutato = self._verdetto(_modulo_mutato(cerca, sostituisci), reg, con, morti)
            if mutato == sano:
                sopravvissuti.append(etichetta)

        self.assertEqual(
            [], sopravvissuti,
            "%d mutante/i SOPRAVVISSUTO/I: %s.\nUn mutante che sopravvive e' la prova "
            "matematica che quella decisione del giudizio non e' sorvegliata da niente -- "
            "si puo' romperla e tutto resta verde. ⛔ Non si dichiara equivalente per "
            "comodita' (B6): o c'e' una dimostrazione, o si scrive il collaudo che manca."
            % (len(sopravvissuti), " · ".join(sopravvissuti)))

    def test_IL_GIUDICE_SA_DIRE_ANCHE_SOPRAVVISSUTO(self):
        """D18 punto 2 -- le DUE direzioni, applicate al giudice stesso.

        «0 sopravvissuti» vale solo se questo giudice e' capace di dire «sopravvissuto». Uno
        che sa dire solo «ucciso» e' indistinguibile da uno rotto, ed e' esattamente lo
        sbaglio che il 2026-08-01 ha prodotto un «42 mutanti su 42 uccisi» che era aria.
        """
        # (a) un mutante che cambia solo un simbolo DECORATIVO deve risultare SOPRAVVISSUTO.
        innocuo = _modulo_mutato('"   ⚠ " + riga', '"   ! " + riga')
        sano = self._verdetto(pds, SANO_REGISTRO, SANO_CONSEGNE, ["fase999_x"])
        self.assertEqual(
            sano, self._verdetto(innocuo, SANO_REGISTRO, SANO_CONSEGNE, ["fase999_x"]),
            "un mutante che cambia un simbolo decorativo ha cambiato il verdetto: allora il "
            "confronto non misura il giudizio, misura il rumore")
        self.assertIn("!", innocuo.limiti_dichiarati(),
                      "la mutazione non e' stata applicata affatto: il confronto qui sopra "
                      "non provava niente")

        # (b) un mutante che non trova il suo bersaglio GRIDA, non passa per verde.
        with self.assertRaises(AssertionError):
            _modulo_mutato("questa riga non esiste nel sorgente", "x")


if __name__ == "__main__":
    unittest.main(verbosity=2)
