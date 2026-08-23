"""LE GUARDIE SU `collaudi/prezzi_coerenti.py` -- il difetto B1.

⛔ IL DIFETTO, misurato sui dati VERI il 2026-08-22: due annunci PUBBLICATI in vetrina a
   100 cents (1,00 EURO) a notte, e la cassa che ne addebitava 9000 (90,00 EURO) su tutte
   e 30 le notti future. Novanta volte tanto. Il numero della vetrina e' quello che finisce
   su Google, nei filtri di ricerca e nell'anteprima dei link.

💡 PERCHE' QUESTE GUARDIE ESISTONO, e non basta l'attrezzo. L'attrezzo dice se i dati di
   OGGI mentono. Queste dicono se l'ATTREZZO sa riconoscere una bugia -- e soprattutto se
   sa dire di NO quando la bugia non c'e'. Un controllo che risponde sempre "rosso" e' un
   ornamento tanto quanto uno che risponde sempre "verde" (modo di rompersi n.4).

⛔ LA TRAPPOLA VERA, ed e' venuta dai dati veri e non dalla fantasia: `filippine-makati`
   aveva UNA notte a 100 cents datata 2026-08-16, cioe' GIA' PASSATA, piu' 30 notti future
   a 9000. Un controllo che guardasse tutti i giorni troverebbe minimo 100, direbbe
   "coincide con la vetrina" e ASSOLVEREBBE il difetto -- con un giorno che nessuno puo'
   piu' prenotare. E' `test_LA_NOTTE_PASSATA_NON_ASSOLVE`.
"""

import datetime
import os
import sqlite3
import shutil
import tempfile
import threading
import time
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))

_ATTREZZO = []          # cache: il modulo si carica una volta sola


def _pc():
    """`collaudi/prezzi_coerenti.py`, caricato una volta sola (come fa il pre-volo)."""
    if not _ATTREZZO:
        import importlib.util
        p = os.path.join(QUI, "collaudi", "prezzi_coerenti.py")
        spec = importlib.util.spec_from_file_location("_prezzi_coerenti", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _ATTREZZO.append(m)
    return _ATTREZZO[0]


OGGI = "2026-08-22"          # ⛔ il tempo entra come DATO, mai letto dall'orologio


def giorno(data, prezzo, *, chiuso=0, totali=1, occupate=0):
    return {"giorno": data, "prezzo_netto_cents": prezzo, "chiuso": chiuso,
            "unita_totali": totali, "unita_occupate": occupate}


def notti_a(prezzo, quante=30, dal="2026-08-23"):
    """`quante` notti future tutte allo stesso prezzo, a partire da `dal`.

    ⛔ I giorni si contano con `datetime`, non concatenando numeri al mese: «2026-08-23»
    piu' 30 non fa «2026-08-53». Un generatore che produce date impossibili regge il
    confronto fra stringhe e per questo NON si nota -- finche' un giorno qualcuno le
    scrive in un archivio vero.
    """
    d0 = datetime.date.fromisoformat(dal)
    return [giorno((d0 + datetime.timedelta(days=i)).isoformat(), prezzo)
            for i in range(quante)]


class TestIlGiudizioSaDireSiENo(unittest.TestCase):
    """Le due direzioni. Se dicesse sempre la stessa cosa non varrebbe niente."""

    def test_IL_GIUDIZIO_SA_DIRE_SI_E_NO(self):
        pc = _pc()
        oneste = pc.notti_prenotabili(notti_a(9000), OGGI)
        self.assertEqual(pc.giudica(9000, oneste), [],
                         "vetrina uguale alla notte piu' economica: non c'e' nessuna bugia")
        self.assertNotEqual(pc.giudica(100, oneste), [],
                            "vetrina 100 contro notti da 9000: questa E' una bugia")

    def test_LA_FOTOGRAFIA_DI_STASERA_E_UNA_BUGIA(self):
        """I numeri veri del 2026-08-22, non un caso inventato."""
        pc = _pc()
        notti = pc.notti_prenotabili(notti_a(9000), OGGI)
        motivi = pc.giudica(100, notti)
        self.assertEqual(len(motivi), 1)
        self.assertIn("100", motivi[0])
        self.assertIn("9000", motivi[0],
                      "il motivo deve NOMINARE i due numeri: chi lo legge deve poter "
                      "rifare la misura senza fidarsi")
        self.assertIn("ATTIRA PIU' BASSO", motivi[0])

    def test_ANCHE_PIU_ALTO_E_UNA_BUGIA(self):
        """Il danno e' minore ma il numero resta falso: l'ospite scarta un annuncio che
        poteva permettersi."""
        pc = _pc()
        notti = pc.notti_prenotabili(notti_a(5000), OGGI)
        motivi = pc.giudica(9000, notti)
        self.assertEqual(len(motivi), 1)
        self.assertIn("SPAVENTA PIU' ALTO", motivi[0])


class TestCosaNonAssolveLaVetrina(unittest.TestCase):
    """Una notte a buon mercato che l'ospite NON puo' comprare non rende onesta la vetrina.
    Ognuno di questi casi, senza il suo filtro, farebbe risultare COERENTE il difetto vero."""

    def setUp(self):
        self.pc = _pc()

    def _resta_bugia(self, giorni, quale):
        notti = self.pc.notti_prenotabili(giorni, OGGI)
        self.assertNotEqual(
            self.pc.giudica(100, notti), [],
            "una notte %s a 100 cents ha assolto la vetrina: ma quella notte nessuno la "
            "puo' comprare, quindi il prezzo mostrato resta falso" % quale)

    def test_LA_NOTTE_PASSATA_NON_ASSOLVE(self):
        # ⛔ E' esattamente la forma dei dati veri di `filippine-makati`.
        self._resta_bugia([giorno("2026-08-16", 100)] + notti_a(9000), "gia' passata")

    def test_LA_NOTTE_CHIUSA_NON_ASSOLVE(self):
        self._resta_bugia([giorno("2026-08-25", 100, chiuso=1)] + notti_a(9000), "chiusa")

    def test_LA_NOTTE_PIENA_NON_ASSOLVE(self):
        self._resta_bugia([giorno("2026-08-25", 100, totali=2, occupate=2)] + notti_a(9000),
                          "senza unita' libere")

    def test_LA_NOTTE_SENZA_PREZZO_NON_ASSOLVE(self):
        # prezzo 0 -> `fase59_concierge` risponde 422 non_quotabile: non e' vendibile.
        self._resta_bugia([giorno("2026-08-25", 0)] + notti_a(9000), "a prezzo zero")

    def test_MA_UNA_NOTTE_VERA_A_QUEL_PREZZO_ASSOLVE(self):
        """La direzione opposta: se la notte economica esiste DAVVERO ed e' comprabile,
        la vetrina dice il vero e la guardia deve tacere."""
        giorni = [giorno("2026-08-25", 100)] + notti_a(9000)
        notti = self.pc.notti_prenotabili(giorni, OGGI)
        self.assertEqual(self.pc.giudica(100, notti), [],
                         "quella notte si compra davvero: «da 1,00 EURO» e' vero")


class TestLaVetrinaSenzaNientaDaVendere(unittest.TestCase):

    def test_NESSUNA_NOTTE_PRENOTABILE_E_UNA_BUGIA(self):
        """Pubblicato con un prezzo e zero calendario: chi prova a prenotare prende
        422 non_quotabile. La vetrina promette una cosa che la cassa non sa vendere."""
        pc = _pc()
        motivi = pc.giudica(9000, [])
        self.assertEqual(len(motivi), 1)
        self.assertIn("non_quotabile", motivi[0])

    def test_UN_PREZZO_NON_VALIDO_E_UNA_BUGIA(self):
        pc = _pc()
        for cattivo in (0, -1, None, "9000", True):
            self.assertNotEqual(pc.giudica(cattivo, pc.notti_prenotabili(notti_a(9000), OGGI)), [],
                                "prezzo vetrina %r accettato come valido" % (cattivo,))


class TestPrezziDiversiSiDICHIARANO(unittest.TestCase):
    """⚠️ Notti a prezzi diversi NON sono una bugia: sono la ragione per cui un numero solo
    non basta. Con la scelta B del fondatore (2026-08-22) la scheda mostra il prezzo DELLE
    DATE chieste; senza date, «da <minimo>»."""

    def test_LE_RICONOSCE(self):
        pc = _pc()
        notti = pc.notti_prenotabili(notti_a(8000, 5) + notti_a(12000, 5, dal="2026-09-01"), OGGI)
        self.assertEqual(pc.notti_a_prezzi_diversi(notti), (8000, 12000))

    def test_E_TACE_QUANDO_SONO_UGUALI(self):
        pc = _pc()
        notti = pc.notti_prenotabili(notti_a(8000), OGGI)
        self.assertIsNone(pc.notti_a_prezzi_diversi(notti))

    def test_LA_VETRINA_AL_MINIMO_NON_E_UNA_BUGIA(self):
        """Prezzi variabili e vetrina al piu' basso: «da X» e' vero, la guardia tace."""
        pc = _pc()
        notti = pc.notti_prenotabili(notti_a(8000, 5) + notti_a(12000, 5, dal="2026-09-01"), OGGI)
        self.assertEqual(pc.giudica(8000, notti), [])


class TestLAttrezzoSugliArchiviVeri(unittest.TestCase):
    """L'attrezzo intero, dagli archivi all'uscita. ⛔ Deve saper dire 1 E 0: un attrezzo
    che esce sempre 1 blocca tutto e viene spento; uno che esce sempre 0 non ha mai
    guardato niente."""

    def setUp(self):
        self.cartella = tempfile.mkdtemp(prefix="prezzi_")

    def tearDown(self):
        shutil.rmtree(self.cartella, ignore_errors=True)

    def _archivi(self, annunci, giorni_per_slug):
        cat = os.path.join(self.cartella, "catalogo.db")
        con = sqlite3.connect(cat)
        con.execute("CREATE TABLE alloggi (id INTEGER PRIMARY KEY, slug TEXT, "
                    "prezzo_notte_cents INTEGER, valuta TEXT, stato TEXT)")
        con.executemany("INSERT INTO alloggi (slug, prezzo_notte_cents, valuta, stato) "
                        "VALUES (?,?,?,?)", annunci)
        con.commit()
        con.close()
        inv = os.path.join(self.cartella, "inventario.db")
        con = sqlite3.connect(inv)
        con.execute("CREATE TABLE inventario (alloggio_id TEXT, giorno TEXT, "
                    "unita_totali INTEGER, unita_occupate INTEGER, "
                    "prezzo_netto_cents INTEGER, chiuso INTEGER)")
        for slug, giorni in giorni_per_slug.items():
            con.executemany("INSERT INTO inventario VALUES (?,?,?,?,?,?)",
                            [(slug, g["giorno"], g["unita_totali"], g["unita_occupate"],
                              g["prezzo_netto_cents"], g["chiuso"]) for g in giorni])
        con.commit()
        con.close()

    def test_SUI_DATI_DI_STASERA_ESCE_1(self):
        """La fotografia del 2026-08-22, ricostruita: due annunci pubblicati a 100 cents,
        il calendario a 9000. L'attrezzo deve gridare."""
        self._archivi(
            [("filippine-makati", 100, "EUR", "pubblicato"),
             ("filippine-makati-2", 100, "EUR", "pubblicato")],
            {"filippine-makati": [giorno("2026-08-16", 100)] + notti_a(9000),
             "filippine-makati-2": notti_a(9000)})
        uscita = _pc().main(["--cartella", self.cartella, "--oggi", OGGI])
        self.assertEqual(uscita, 1, "sui dati veri di stasera l'attrezzo NON ha gridato: "
                                    "un controllo che nasce verde sul difetto che deve "
                                    "sorvegliare non sta guardando la cosa giusta")

    def test_SUI_DATI_ONESTI_ESCE_0(self):
        """L'altra direzione, ed e' quella che rende l'uscita 1 una notizia."""
        self._archivi([("casa-onesta", 9000, "EUR", "pubblicato")],
                      {"casa-onesta": notti_a(9000)})
        self.assertEqual(_pc().main(["--cartella", self.cartella, "--oggi", OGGI]), 0)

    def test_LE_BOZZE_NON_MENTONO_A_NESSUNO(self):
        """Un annuncio NON pubblicato non lo vede nessuno: non puo' ingannare nessuno,
        e non deve tenere l'attrezzo rosso per sempre."""
        self._archivi([("casa-onesta", 9000, "EUR", "pubblicato"),
                       ("bozza-storta", 1, "EUR", "bozza")],
                      {"casa-onesta": notti_a(9000)})
        self.assertEqual(_pc().main(["--cartella", self.cartella, "--oggi", OGGI]), 0)

    def test_ARCHIVIO_ASSENTE_NON_E_UN_VERDE(self):
        """Il vuoto non e' un valore: e' l'assenza di misura (sbaglio S1)."""
        self.assertEqual(_pc().main(["--cartella", self.cartella, "--oggi", OGGI]), 2)

    def test_ZERO_ANNUNCI_PUBBLICATI_NON_E_UN_VERDE(self):
        self._archivi([("bozza", 100, "EUR", "bozza")], {})
        self.assertEqual(_pc().main(["--cartella", self.cartella, "--oggi", OGGI]), 2)

    def test_NON_SCRIVE_MAI_NIENTE(self):
        """Gli archivi si aprono in sola lettura: l'attrezzo non puo' alterare i dati che
        sta giudicando. Provato sulle IMPRONTE dei file, non sulle intenzioni."""
        import hashlib
        self._archivi([("casa", 100, "EUR", "pubblicato")], {"casa": notti_a(9000)})

        def impronte():
            out = {}
            for n in ("catalogo.db", "inventario.db"):
                with open(os.path.join(self.cartella, n), "rb") as f:
                    out[n] = hashlib.sha256(f.read()).hexdigest()
            return out

        prima = impronte()
        _pc().main(["--cartella", self.cartella, "--oggi", OGGI])
        self.assertEqual(prima, impronte(), "l'attrezzo ha modificato gli archivi")


def giorni_futuri(quanti, prezzo, salta=0):
    """`quanti` giorni a partire da OGGI VERO, come (giorno, prezzo).

    ⛔ MAI date fisse qui dentro. Il prodotto rispecchia il prezzo guardando da OGGI in
    avanti, quindi un collaudo con scritto «2026-08-23» passa oggi e fallisce domani --
    una bomba a tempo, che e' il difetto che `collaudi/bombe_a_tempo.py` va a cercare.
    """
    oggi = datetime.date.today()
    return [((oggi + datetime.timedelta(days=salta + i)).isoformat(), prezzo)
            for i in range(quanti)]


class TestLoSpecchioDelPrezzo(unittest.TestCase):
    """IL PEZZO 2a: il prezzo in vetrina e' lo SPECCHIO del calendario.

    ⛔ Qui si prova il PRODOTTO, non l'attrezzo di collaudo: vetrina e inventario veri,
    cablati come li cabla `fase81_bootstrap_casavip.py`. Su archivi su FILE e non in
    memoria, perche' l'ultimo collaudo interroga l'oracolo indipendente, che apre i file.
    """

    def setUp(self):
        from fase57_vetrina import crea_catalogo
        from fase58_channel_manager import crea_channel_manager
        self.cartella = tempfile.mkdtemp(prefix="specchio_")
        self.inv = crea_channel_manager(os.path.join(self.cartella, "inventario.db"))
        self.cat = crea_catalogo(os.path.join(self.cartella, "catalogo.db"),
                                 disponibilita=self.inv.disponibile,
                                 prezzo_minimo=self.inv.prezzo_minimo_prenotabile)
        self.inv.collega_specchio(self.cat.rispecchia_prezzo)

    def tearDown(self):
        shutil.rmtree(self.cartella, ignore_errors=True)

    def _pubblica(self, slug, prezzo):
        from fase57_vetrina import valida_scheda
        ok, err, scheda = valida_scheda(
            {"host_id": "h1", "slug": slug, "titolo": "Casa", "citta": "Roma",
             "prezzo_notte_cents": prezzo, "capacita": 2})
        self.assertTrue(ok, "scheda di prova non valida: %s" % err)
        self.cat.pubblica(scheda)
        self.cat.imposta_stato(slug, "pubblicato")

    def _giorno(self, slug, giorno, prezzo, unita=1):
        return self.inv.imposta_disponibilita(slug, giorno, unita_totali=unita,
                                              prezzo_netto_cents=prezzo)

    def _vetrina(self, slug):
        return self.cat.dettaglio_owner(slug)["prezzo_notte_cents"]

    def test_SALVARE_UN_GIORNO_RISPECCHIA_LA_VETRINA(self):
        self._pubblica("casa", 100)
        giorno, prezzo = giorni_futuri(1, 9000)[0]
        self.assertTrue(self._giorno("casa", giorno, prezzo))
        self.assertEqual(self._vetrina("casa"), 9000,
                         "l'host ha messo 90 EUR nel calendario e la vetrina dice ancora "
                         "un altro numero: e' esattamente il difetto B1")

    def test_L_ICAL_CHE_BLOCCA_LA_NOTTE_ECONOMICA_ALZA_LA_VETRINA(self):
        """⛔ IL CASO PER CUI LO SPECCHIO STA SUL CONFINE DEI DATI E NON SUI PULSANTI.

        Nessuno tocca il pannello: un calendario esterno occupa la notte piu' economica,
        l'iCal la blocca DA SOLO, e da quel momento la notte prenotabile piu' economica
        costa di piu'. Se la vetrina non lo seguisse, la bugia tornerebbe da sola.

        💡 Si usa `fase82_ical_sync.sincronizza` VERO, non una sua imitazione: un collaudo
        che rifa' a mano cio' che fa l'attrezzo prova solo che so copiare l'attrezzo.
        """
        from fase82_ical_sync import sincronizza
        self._pubblica("casa", 100)
        (g_economico, _), (g_caro, _) = giorni_futuri(2, 0)
        self._giorno("casa", g_economico, 8000)
        self._giorno("casa", g_caro, 12000)
        self.assertEqual(self._vetrina("casa"), 8000,
                         "«da 80 EUR» e' vero finche' quella notte si compra")

        esito = sincronizza(self.inv, "casa", (
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\n"
            "DTSTART;VALUE=DATE:%s\r\nDTEND;VALUE=DATE:%s\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
            % (g_economico.replace("-", ""), g_caro.replace("-", ""))))
        self.assertGreaterEqual(
            esito.get("giorni_bloccati", 0), 1,
            "l'iCal non ha bloccato niente: il collaudo non sta provando quello che dice")

        self.assertEqual(self._vetrina("casa"), 12000,
                         "la notte da 80 non si compra piu' e la vetrina la mostra ancora: "
                         "il sito attira con un prezzo che non esiste")

    def test_PUBBLICARE_UN_ANNUNCIO_NON_PUO_MENTIRE(self):
        """L'host scrive 1,00 EUR nella casella della vetrina mentre il suo calendario
        dice 90,00. Vince il calendario, perche' e' quello che si paga."""
        for giorno, prezzo in giorni_futuri(3, 9000):
            self._giorno("casa", giorno, prezzo)
        self._pubblica("casa", 100)
        self.assertEqual(self._vetrina("casa"), 9000)

    def test_SENZA_NOTTI_PRENOTABILI_NON_INVENTA_UN_PREZZO(self):
        """Nessun calendario: non c'e' un numero onesto da mostrare. Lasciare quello
        vecchio e' un difetto -- che la guardia dira' -- ma inventarne uno lo NASCONDE."""
        self._pubblica("casa", 5000)
        self.assertIsNone(self.cat.rispecchia_prezzo("casa"))
        self.assertEqual(self._vetrina("casa"), 5000)

    def test_LE_NOTTI_CHE_NON_SI_COMPRANO_NON_FANNO_PREZZO(self):
        """Le stesse esclusioni dell'oracolo, ma provate sul PRODOTTO: passata, chiusa,
        piena, a prezzo zero. Ognuna, se contasse, farebbe risultare onesta una vetrina
        che mente."""
        self._pubblica("casa", 100)
        for giorno, prezzo in giorni_futuri(3, 9000, salta=1):
            self._giorno("casa", giorno, prezzo)
        ieri = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        self._giorno("casa", ieri, 100)                                   # passata
        self.inv.imposta_disponibilita("casa", giorni_futuri(1, 0, salta=10)[0][0],
                                       unita_totali=1, prezzo_netto_cents=100, chiuso=True)
        self._giorno("casa", giorni_futuri(1, 0, salta=11)[0][0], 100, unita=0)   # piena
        self._giorno("casa", giorni_futuri(1, 0, salta=12)[0][0], 0)              # senza prezzo
        self.assertEqual(self._vetrina("casa"), 9000,
                         "una notte che l'ospite non puo' comprare ha fatto da prezzo in "
                         "vetrina")

    def test_SE_LO_SPECCHIO_ESPLODE_L_HOST_SALVA_LO_STESSO(self):
        """⛔ La scelta dichiarata: meglio una vetrina con un prezzo vecchio che un host
        che non riesce a salvare le sue date. Ma NON in silenzio."""
        def esplode(_slug):
            raise RuntimeError("specchio rotto di proposito")
        self._pubblica("casa", 100)
        self.inv.collega_specchio(esplode)
        giorno, prezzo = giorni_futuri(1, 7000)[0]
        with self.assertLogs("core_auto.channel_manager", level="ERROR"):
            salvato = self._giorno("casa", giorno, prezzo)
        self.assertTrue(salvato, "lo specchio rotto ha fatto fallire il salvataggio")
        self.assertEqual(self.inv.stato_giorno("casa", giorno)["prezzo_netto_cents"], 7000,
                         "il giorno non e' finito nell'archivio")

    def test_DOPO_OGNI_SCRITTURA_L_ORACOLO_INDIPENDENTE_TACE(self):
        """LA PROVA CHE CHIUDE B1: scrive il PRODOTTO, giudica un SECONDO CALCOLO che non
        condivide una riga con lui (`collaudi/prezzi_coerenti.py`). Se condividessero il
        codice, un errore nel calcolo del minimo sarebbe invisibile a tutt'e due."""
        self._pubblica("casa", 100)
        for giorno, prezzo in giorni_futuri(5, 9000):
            self._giorno("casa", giorno, prezzo)
        esiti = _pc().esamina(self.cartella, datetime.date.today().isoformat())
        self.assertTrue(esiti, "nessun annuncio esaminato: la misura non vale")
        self.assertEqual([e["motivi"] for e in esiti if e["motivi"]], [],
                         "il prodotto ha scritto e l'oracolo indipendente trova ancora "
                         "una bugia")


class TestLeValidazioniCheNessunoGuardava(unittest.TestCase):
    """I BUCHI TROVATI DALLA MUTAZIONE, chiusi uno per uno.

    ⛔ Il giro del Giudice sulle righe nuove (2026-08-23) ha dato 18 punti provati, 7
    uccisi, 11 SOPRAVVISSUTI. Nessuno dei sopravvissuti era equivalente: erano validazioni
    scritte e mai guardate da nessun collaudo. Un `if` che non ha un test e' un `if` che
    puo' essere cancellato senza che niente diventi rosso.

    💡 UNO DEI BUCHI ERA IL PIU' INSIDIOSO DI TUTTI: il caso «notte a prezzo zero» ESISTEVA
    gia' nei collaudi, ma passava per il motivo sbagliato -- la vetrina era gia' al valore
    giusto per una scrittura precedente, quindi il mutante non cambiava l'esito. Un test
    verde che non prova cio' che crede. Qui si guarda il MINIMO, non la vetrina.
    """

    def setUp(self):
        from fase57_vetrina import crea_catalogo, valida_scheda
        from fase58_channel_manager import crea_channel_manager
        self.cartella = tempfile.mkdtemp(prefix="valid_")
        self.inv = crea_channel_manager(os.path.join(self.cartella, "i.db"))
        self.cat = crea_catalogo(os.path.join(self.cartella, "c.db"),
                                 disponibilita=self.inv.disponibile,
                                 prezzo_minimo=self.inv.prezzo_minimo_prenotabile)
        self.inv.collega_specchio(self.cat.rispecchia_prezzo)
        ok, err, scheda = valida_scheda(
            {"host_id": "h1", "slug": "casa", "titolo": "Casa", "citta": "Roma",
             "prezzo_notte_cents": 5000, "capacita": 2})
        self.assertTrue(ok, err)
        self.cat.pubblica(scheda)

    def tearDown(self):
        shutil.rmtree(self.cartella, ignore_errors=True)

    def _vetrina(self):
        return self.cat.dettaglio_owner("casa")["prezzo_notte_cents"]

    def _minimo(self):
        oggi = datetime.date.today()
        return self.inv.prezzo_minimo_prenotabile(
            "casa", oggi.isoformat(),
            (oggi + datetime.timedelta(days=60)).isoformat())

    # ── fase57: `rispecchia_prezzo` non si fida di chi gli passa il minimo ──────────
    def test_UN_MINIMO_NON_VALIDO_NON_FINISCE_IN_VETRINA(self):
        """Se il fornitore del minimo restituisce spazzatura, la vetrina non la mostra.
        ⛔ Zero e' il caso che conta: `<= 0` contro `< 0` e' un errore di un carattere, e
        un prezzo di 0 centesimi in vetrina e' un annuncio che dice «gratis»."""
        for cattivo in (0, -1, None, "9000", True, 3.5):
            self.cat._prezzo_min = lambda s, d, a, v=cattivo: v
            self.assertIsNone(self.cat.rispecchia_prezzo("casa"),
                              "minimo %r accettato come valido" % (cattivo,))
            self.assertEqual(self._vetrina(), 5000,
                             "la vetrina e' cambiata per un minimo %r" % (cattivo,))

    # ── fase57: `aggiorna_prezzo_vetrina` e' l'ultima porta prima dell'archivio ─────
    def test_LA_SCRITTURA_RIFIUTA_I_PREZZI_IMPOSSIBILI(self):
        for cattivo in (0, -1, None, "9000", True, 12.5):
            self.assertFalse(self.cat.aggiorna_prezzo_vetrina("casa", cattivo),
                             "prezzo %r accettato" % (cattivo,))
        self.assertEqual(self._vetrina(), 5000)

    def test_LA_SCRITTURA_RIFIUTA_GLI_SLUG_IMPOSSIBILI(self):
        for cattivo in (None, "", "   ", 123, True, ["casa"]):
            self.assertFalse(self.cat.aggiorna_prezzo_vetrina(cattivo, 9000),
                             "slug %r accettato" % (cattivo,))
        self.assertEqual(self._vetrina(), 5000)

    def test_DICE_FALSO_QUANDO_NON_HA_CAMBIATO_NIENTE(self):
        """`True` vuol dire «ho cambiato», non «va tutto bene». Chi legge quel valore per
        sapere se ha aggiornato qualcosa deve poterci contare."""
        self.assertTrue(self.cat.aggiorna_prezzo_vetrina("casa", 9000),
                        "prima scrittura: ha cambiato, deve dire True")
        self.assertFalse(self.cat.aggiorna_prezzo_vetrina("casa", 9000),
                         "stesso valore: non ha cambiato niente, deve dire False")
        self.assertFalse(self.cat.aggiorna_prezzo_vetrina("non-esiste", 9000),
                         "slug inesistente: non ha cambiato niente, deve dire False")

    # ── fase58: le notti che non si comprano, guardate SUL MINIMO ──────────────────
    def test_UNA_NOTTE_VENDUTA_NON_FA_PREZZO(self):
        """La notte c'e', e' aperta, costa poco -- ed e' gia' venduta. Non puo' fare da
        prezzo in vetrina. ⛔ L'unita' si occupa con `blocca`, il metodo VERO: un collaudo
        che scrive a mano nell'archivio prova la propria SQL, non il prodotto."""
        oggi = datetime.date.today()
        economica = (oggi + datetime.timedelta(days=1)).isoformat()
        cara = (oggi + datetime.timedelta(days=5)).isoformat()
        self.inv.imposta_disponibilita("casa", economica, unita_totali=1,
                                       prezzo_netto_cents=2000)
        self.inv.imposta_disponibilita("casa", cara, unita_totali=1,
                                       prezzo_netto_cents=9000)
        self.assertEqual(self._minimo(), 2000, "prima della vendita il minimo e' 2000")

        esito = self.inv.blocca("casa", economica,
                                (oggi + datetime.timedelta(days=2)).isoformat(),
                                idem_key="prova-venduta")
        self.assertTrue(getattr(esito, "ok", False),
                        "la notte non e' stata venduta: la misura non vale (%r)" % (esito,))
        self.assertEqual(self._minimo(), 9000,
                         "una notte GIA' VENDUTA fa ancora da prezzo in vetrina")

    def test_UNA_NOTTE_A_PREZZO_ZERO_NON_FA_PREZZO(self):
        """⛔ Si guarda il MINIMO, non la vetrina: e' il buco che la mutazione ha trovato.
        Guardando la vetrina, il caso passava perche' il valore era gia' quello giusto da
        prima -- verde per il motivo sbagliato."""
        oggi = datetime.date.today()
        self.inv.imposta_disponibilita(
            "casa", (oggi + datetime.timedelta(days=1)).isoformat(),
            unita_totali=1, prezzo_netto_cents=0)
        self.inv.imposta_disponibilita(
            "casa", (oggi + datetime.timedelta(days=2)).isoformat(),
            unita_totali=1, prezzo_netto_cents=9000)
        self.assertEqual(self._minimo(), 9000,
                         "una notte a prezzo zero e' entrata nel minimo: la cassa la "
                         "rifiuterebbe con 422 non_quotabile")

    # ── fase58: la difesa che CodeQL riconosce ────────────────────────────────────
    def test_IL_REGISTRO_NON_PRENDE_LE_ANDATE_A_CAPO(self):
        """Il nome dell'alloggio arriva dall'esterno. Se ci finisse dentro un a-capo, una
        riga sola di registro potrebbe fingersene due e raccontare un'altra storia.
        ⛔ E' la forma che CodeQL riconosce (`.replace("\\n", ...)`), e nessun collaudo
        provava che ci fosse: il mutante che la toglieva sopravviveva."""
        def esplode(_slug):
            raise RuntimeError("specchio rotto di proposito")
        self.inv.collega_specchio(esplode)
        with self.assertLogs("core_auto.channel_manager", level="ERROR") as registro:
            self.inv.imposta_disponibilita(
                "ca\nsa\rmia", (datetime.date.today()).isoformat(),
                unita_totali=1, prezzo_netto_cents=9000)
        scritto = registro.records[0].getMessage()
        self.assertNotIn("\n", scritto, "un a-capo e' finito nel registro: %r" % scritto)
        self.assertNotIn("\r", scritto, "un ritorno a capo e' finito nel registro")
        self.assertIn("ca sa mia", scritto,
                      "il nome e' sparito del tutto invece di essere ripulito: chi "
                      "ripara non saprebbe QUALE alloggio")

    def test_IL_REGISTRO_PORTA_ANCHE_LA_TRACCIA(self):
        """`exc_info=True` non e' decorazione: senza, il registro dice CHE lo specchio e'
        fallito e non PERCHE'. Chi ripara ha solo quella riga.

        ⛔ E NON BASTA CHIEDERE «c'e' qualcosa?». `exc_info=False` produce **False, non
        None**: un controllo `is not None` lo lascerebbe passare, ed e' uno sbaglio gia'
        pagato da questo progetto. La domanda giusta e' «c'e' LA COSA, del tipo giusto?»
        -- cioe' la terna (tipo, valore, traccia) con dentro l'eccezione vera.
        """
        def esplode(_slug):
            raise RuntimeError("specchio rotto di proposito")
        self.inv.collega_specchio(esplode)
        with self.assertLogs("core_auto.channel_manager", level="ERROR") as registro:
            self.inv.imposta_disponibilita(
                "casa", datetime.date.today().isoformat(),
                unita_totali=1, prezzo_netto_cents=9000)
        info = registro.records[0].exc_info
        self.assertIsInstance(info, tuple,
                              "nessuna traccia nel registro: si saprebbe CHE e' fallito "
                              "ma non PERCHE' (exc_info=%r)" % (info,))
        self.assertEqual(len(info), 3, "traccia malformata: %r" % (info,))
        self.assertIs(info[0], RuntimeError,
                      "la traccia non porta l'eccezione vera, ma %r" % (info[0],))


class _SerraturaFinta:
    """Non chiude niente. Serve a rimettere dentro il guasto e vedere la guardia ROSSA:
    una prova che non fallisce col difetto dentro non prova niente."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestLaGaraSulloSpecchio(unittest.TestCase):
    """DUE SCRITTURE NELLO STESSO ISTANTE: la vetrina resta giusta?

    ⛔ IL DIFETTO, TROVATO E DIMOSTRATO IL 2026-08-23. Lo specchio fa leggi-poi-scrivi su
    DUE archivi diversi (inventario e catalogo), quindi i due passi non stanno in una
    transazione sola. Senza serratura:
        il filo A scrive un giorno a 90 EUR, il suo specchio LEGGE e vede solo 90
        gli altri scrivono giorni a 40 e 20, i loro specchi scrivono 20
        A riprende e scrive la sua lettura VECCHIA -> in vetrina resta 90
    Misurato: ordine delle scritture [2000, 2000, 9000], vetrina 9000, cassa 2000. Cioe'
    il difetto B1 rientrato dalla porta di servizio, DENTRO la sua riparazione.

    ⚠️ E NON SI VEDEVA DA SOLO: 150 giri di sonda col tempismo naturale, ZERO divergenze.
    Si e' visto solo costruendo l'incastro a mano. «Non si e' visto» non voleva dire «non
    c'e'»: voleva dire che l'esperimento era sbagliato. Una delle sonde ha perfino avuto
    la gara sotto gli occhi e l'ha dichiarata sana, perche' un terzo filo passava dopo e
    ripuliva PER CASO -- guardando solo il valore finale, sembrava tutto a posto.

    💡 Per questo il collaudo guarda anche l'ORDINE delle scritture, non solo l'esito.
    """

    # 0,8 s: gli altri due fili impiegano ~0,2 s. Margine 4x, non 1,2x -- una prova che
    # dipende da venti millisecondi e' una prova che un giorno diventera' instabile, e un
    # test instabile insegna a ignorare il rosso (regola ferrea 10).
    RITARDO = 0.8

    def _scenario(self, serratura_vera):
        from fase57_vetrina import crea_catalogo, valida_scheda
        from fase58_channel_manager import crea_channel_manager
        cartella = tempfile.mkdtemp(prefix="gara_")
        try:
            inv = crea_channel_manager(os.path.join(cartella, "i.db"))
            cat = crea_catalogo(os.path.join(cartella, "c.db"),
                                disponibilita=inv.disponibile,
                                prezzo_minimo=inv.prezzo_minimo_prenotabile)
            if not serratura_vera:
                cat._serratura_specchio = _SerraturaFinta()

            letture, ordine = [], []
            vero_min = inv.prezzo_minimo_prenotabile

            def min_spiato(slug, da, a):
                v = vero_min(slug, da, a)
                letture.append(v)
                return v

            vero_agg = cat.aggiorna_prezzo_vetrina
            primo = {"fatto": False}

            def agg_lento(slug, prezzo):
                if not primo["fatto"]:
                    primo["fatto"] = True
                    time.sleep(self.RITARDO)      # A resta nella finestra leggi→scrivi
                r = vero_agg(slug, prezzo)
                ordine.append(prezzo)
                return r

            cat._prezzo_min = min_spiato
            cat.aggiorna_prezzo_vetrina = agg_lento
            inv.collega_specchio(cat.rispecchia_prezzo)

            ok, err, scheda = valida_scheda(
                {"host_id": "h1", "slug": "casa", "titolo": "Casa", "citta": "Roma",
                 "prezzo_notte_cents": 5000, "capacita": 2})
            self.assertTrue(ok, "scheda di prova non valida: %s" % err)
            cat.pubblica(scheda)

            def scrivi(giorni, prezzo):
                inv.imposta_disponibilita(
                    "casa",
                    (datetime.date.today() + datetime.timedelta(days=giorni)).isoformat(),
                    unita_totali=1, prezzo_netto_cents=prezzo)

            caro = threading.Thread(target=scrivi, args=(1, 9000))
            caro.start()
            time.sleep(0.05)                      # A ha letto ed e' nella finestra
            altri = [threading.Thread(target=scrivi, args=(2, 4000)),
                     threading.Thread(target=scrivi, args=(3, 2000))]
            for f in altri:
                f.start()
            for f in [caro] + altri:
                f.join(timeout=30)

            oggi = datetime.date.today().isoformat()
            fine = (datetime.date.today() + datetime.timedelta(days=60)).isoformat()
            return {"vetrina": cat.dettaglio_owner("casa")["prezzo_notte_cents"],
                    "cassa": vero_min("casa", oggi, fine),
                    "ordine": ordine, "letture": letture}
        finally:
            shutil.rmtree(cartella, ignore_errors=True)

    def test_DUE_SCRITTURE_INSIEME_LA_VETRINA_RESTA_GIUSTA(self):
        e = self._scenario(serratura_vera=True)
        # ⛔ PRIMA si controlla che l'incastro sia successo davvero: se A non avesse letto
        #    un valore vecchio, questa prova passerebbe senza aver provato niente -- il
        #    verde peggiore, quello che non ha guardato.
        self.assertIn(9000, e["letture"],
                      "il filo che doveva restare indietro non ha mai letto 9000: "
                      "l'incastro non e' avvenuto e questa misura non vale")
        self.assertEqual(e["vetrina"], e["cassa"],
                         "vetrina %s e cassa %s: due scritture simultanee hanno lasciato "
                         "in vetrina un prezzo che la cassa non addebiterebbe "
                         "(ordine delle scritture: %s)"
                         % (e["vetrina"], e["cassa"], e["ordine"]))

    def test_E_SENZA_LA_SERRATURA_LA_VETRINA_MENTIREBBE(self):
        """La riprova: col guasto rimesso dentro, la guardia qui sopra DEVE fallire.
        Senza questa, non sapremmo se sta guardando la cosa giusta."""
        e = self._scenario(serratura_vera=False)
        self.assertIn(9000, e["letture"], "l'incastro non e' avvenuto")
        self.assertNotEqual(
            e["vetrina"], e["cassa"],
            "senza serratura la vetrina resta giusta lo stesso: allora la serratura non "
            "sta riparando quello che credo, e la prova qui sopra e' un ornamento "
            "(ordine delle scritture: %s)" % (e["ordine"],))
        self.assertEqual(e["ordine"][-1], 9000,
                         "il filo rimasto indietro non ha scritto per ultimo: "
                         "l'esperimento non ha riprodotto la gara")


class TestIlCablaggioNonPuoSparire(unittest.TestCase):
    """⛔ LA PROVA PIU' IMPORTANTE DEL FILE, e nasce da un buco nel collaudo stesso.

    Tutti i collaudi qui sopra cablano lo specchio DA SOLI, nel loro `setUp`. Se qualcuno
    cancellasse la riga `inventario.collega_specchio(catalogo.rispecchia_prezzo)` da
    `fase81_bootstrap_casavip.py`, la produzione tornerebbe a mentire e quei collaudi
    resterebbero tutti VERDI: proverebbero che il meccanismo FUNZIONA, non che e'
    ACCESO.

    E' la regola #23 -- COSTRUITO != COLLEGATO -- la stessa che in questo progetto ha
    lasciato 63 moduli costruiti e mai accesi, `fase15_idempotency` compreso. Qui il
    sistema si monta con `crea_sistema`, cioe' come lo monta la produzione.
    """

    def test_LO_SPECCHIO_E_CABLATO_NEL_SISTEMA_VERO(self):
        from fase57_vetrina import valida_scheda
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        d = tempfile.mkdtemp(prefix="cablaggio_")
        os.environ["UPLOAD_DIR"] = os.path.join(d, "uploads")
        try:
            sis = crea_sistema(ConfigCasaVIP(
                abilitato=True, segreto_hmac=b"S" * 32,
                db_catalogo=os.path.join(d, "c.db"),
                db_inventario=os.path.join(d, "i.db"),
                db_registro_host=os.path.join(d, "r.db"),
                db_accettazioni=os.path.join(d, "a.db"),
                db_pendenti=os.path.join(d, "p.db"),
                db_messaggi=os.path.join(d, "m.db"),
                db_garanzia=os.path.join(d, "g.db")))
            ok, err, scheda = valida_scheda(
                {"host_id": "h1", "slug": "casa", "titolo": "Casa", "citta": "Roma",
                 "prezzo_notte_cents": 100, "capacita": 2})
            self.assertTrue(ok, "scheda di prova non valida: %s" % err)
            sis.catalogo.pubblica(scheda)
            giorno, prezzo = giorni_futuri(1, 9000)[0]
            self.assertTrue(sis.inventario.imposta_disponibilita(
                "casa", giorno, unita_totali=1, prezzo_netto_cents=prezzo))
            self.assertEqual(
                sis.catalogo.dettaglio_owner("casa")["prezzo_notte_cents"], 9000,
                "il sistema VERO non ha rispecchiato il prezzo: il cablaggio in "
                "fase81_bootstrap_casavip.py non c'e' piu', e la produzione e' tornata "
                "a mostrare un numero diverso da quello che addebita")
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
