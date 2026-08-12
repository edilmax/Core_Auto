"""
Test Fase 66 - Tassa di soggiorno (jurisdiction-agnostic).

Copre: default ZERO (giurisdizione ignota/non configurata), componente fissa
per-persona-notte, cap notti, esenzioni, componente percentuale, combinazione, tetto
per-persona, registro + da_env, fail-closed su input invalidi, purezza interi.
"""
import os
import unittest

from fase66_tassa_soggiorno import (
    MAX_CENTS, REGOLA_ZERO, CalcoloTassa, RegistroTasse, RegolaTassa, calcola_tassa,
    crea_registro_tasse,
)


class TestDefaultZero(unittest.TestCase):
    def test_regola_zero(self):
        c = calcola_tassa(REGOLA_ZERO, notti=3, ospiti=2, imponibile_cents=30000)
        self.assertEqual(c.tassa_cents, 0)

    def test_giurisdizione_ignota_zero(self):
        reg = crea_registro_tasse()
        c = reg.calcola("citta-mai-vista", notti=5, ospiti=4, imponibile_cents=50000)
        self.assertEqual(c.tassa_cents, 0)            # mai inventare una tassa


class TestComponenteFissa(unittest.TestCase):
    def test_per_persona_notte(self):
        regola = RegolaTassa(per_persona_notte_cents=350)   # 3.50 a persona/notte
        c = calcola_tassa(regola, notti=3, ospiti=2)
        # 350 * 3 notti * 2 ospiti = 2100
        self.assertEqual(c.tassa_cents, 2100)
        self.assertEqual(c.componente_fissa_cents, 2100)

    def test_cap_notti(self):
        regola = RegolaTassa(per_persona_notte_cents=350, max_notti_tassabili=7)
        c = calcola_tassa(regola, notti=10, ospiti=1)   # solo 7 notti tassate
        self.assertEqual(c.notti_tassabili, 7)
        self.assertEqual(c.tassa_cents, 350 * 7)

    def test_esenzioni(self):
        regola = RegolaTassa(per_persona_notte_cents=350)
        c = calcola_tassa(regola, notti=2, ospiti=4, esenti=2)  # 2 bambini esenti
        self.assertEqual(c.ospiti_tassabili, 2)
        self.assertEqual(c.tassa_cents, 350 * 2 * 2)

    def test_tetto_per_persona(self):
        regola = RegolaTassa(per_persona_notte_cents=500,
                             tetto_per_persona_soggiorno_cents=1000)
        c = calcola_tassa(regola, notti=10, ospiti=2)   # 500*10=5000 cappato a 1000
        self.assertEqual(c.tassa_cents, 1000 * 2)


class TestComponentePercentuale(unittest.TestCase):
    def test_percentuale(self):
        regola = RegolaTassa(percentuale_bps=500)       # 5%
        c = calcola_tassa(regola, notti=3, ospiti=2, imponibile_cents=20000)
        self.assertEqual(c.componente_percentuale_cents, 1000)  # 5% di 20000
        self.assertEqual(c.tassa_cents, 1000)

    def test_percentuale_intera_no_float(self):
        regola = RegolaTassa(percentuale_bps=333)       # 3.33%
        c = calcola_tassa(regola, notti=1, ospiti=1, imponibile_cents=9999)
        self.assertEqual(c.componente_percentuale_cents, (333 * 9999) // 10000)
        self.assertIsInstance(c.componente_percentuale_cents, int)

    def test_combinata(self):
        regola = RegolaTassa(per_persona_notte_cents=200, percentuale_bps=300)
        c = calcola_tassa(regola, notti=2, ospiti=2, imponibile_cents=10000)
        fissa = 200 * 2 * 2          # 800
        perc = (300 * 10000) // 10000  # 300
        self.assertEqual(c.tassa_cents, fissa + perc)


class TestFailClosed(unittest.TestCase):
    def test_input_invalidi_zero(self):
        regola = RegolaTassa(per_persona_notte_cents=350)
        for notti, ospiti in ((-1, 2), (3, -1), (3.0, 2), (3, True)):
            c = calcola_tassa(regola, notti=notti, ospiti=ospiti)
            self.assertEqual(c.tassa_cents, 0)

    def test_regola_non_regola(self):
        c = calcola_tassa("non una regola", notti=3, ospiti=2)
        self.assertEqual(c.tassa_cents, 0)

    def test_imponibile_invalido_ignorato(self):
        regola = RegolaTassa(percentuale_bps=500)
        c = calcola_tassa(regola, notti=1, ospiti=1, imponibile_cents=-100)
        self.assertEqual(c.componente_percentuale_cents, 0)


class TestRegistroEnv(unittest.TestCase):
    def test_da_env(self):
        os.environ["TASSE_TEST_X"] = "roma=350:10:0,amsterdam=0::700"
        try:
            reg = RegistroTasse.da_env("TASSE_TEST_X")
            roma = reg.calcola("Roma", notti=15, ospiti=2)   # case-insensitive, cap 10
            self.assertEqual(roma.tassa_cents, 350 * 10 * 2)
            ams = reg.calcola("amsterdam", notti=2, ospiti=1, imponibile_cents=10000)
            self.assertEqual(ams.tassa_cents, (700 * 10000) // 10000)  # 7%
            self.assertEqual(reg.calcola("berlino", notti=2, ospiti=1).tassa_cents, 0)
        finally:
            del os.environ["TASSE_TEST_X"]

    def test_da_env_malformato_ignorato(self):
        os.environ["TASSE_TEST_Y"] = "spazzatura,roma=abc:def,valida=100::0"
        try:
            reg = RegistroTasse.da_env("TASSE_TEST_Y")
            self.assertEqual(reg.calcola("roma", notti=1, ospiti=1).tassa_cents, 0)
            self.assertEqual(reg.calcola("valida", notti=2, ospiti=1).tassa_cents, 200)
        finally:
            del os.environ["TASSE_TEST_Y"]


class TestContratto(unittest.TestCase):
    def test_as_dict_interi(self):
        regola = RegolaTassa(per_persona_notte_cents=350)
        d = calcola_tassa(regola, notti=2, ospiti=2).as_dict()
        self.assertEqual(d["money_unit"], "cents_integer")
        self.assertIsInstance(d["tassa_cents"], int)


class TestUnaRegolaMALFORMATANonPuoFarPagareDIPIU(unittest.TestCase):
    """⛔ IL CONTRATTO DICHIARATO DAL MODULO, PRESO SUL SERIO.

    La docstring di `fase66` promette: *«validazione fail-closed (input non interi/negativi
    -> tassa 0, mai un'eccezione)»* e *«una giurisdizione sconosciuta NON paga una tassa
    inventata da noi»*.

    Per DUE campi la promessa era rotta, e rotta nella direzione peggiore. Sono i due campi
    `Optional`: `max_notti_tassabili` e `tetto_per_persona_soggiorno_cents`. Per tutti e due
    il codice trattava **«invalido» e «assente» come la stessa cosa** -- e per questi due
    campi «assente» non significa «niente tassa», significa **«non applicare lo sconto»**.
    Quindi un meno di troppo in configurazione non spegneva la tassa: **toglieva il tetto**.

    MISURATO PRIMA DELLA RIPARAZIONE, non dedotto (sonda eseguita il 2026-08-12):
        cap=7  (valido)   -> notti_tassabili= 7  tassa=4900 cents
        cap=-1 (INVALIDO) -> notti_tassabili=30  tassa=21000 cents
    Cioe' l'ospite pagava **161,00 EUR in piu'** per lo stesso soggiorno, in silenzio.

    ⛔ PERCHE' L'OSSERVABILE E' `tassa_cents == 0` E NON «minore di prima»: un confronto
    relativo ("non deve pagare piu' del caso valido") lo soddisferebbe anche una riparazione
    che tassa 29 notti invece di 30. Il contratto non dice «meno»: dice **zero**. Una regola
    che non si sa leggere non e' una regola dolce, e' una regola assente -- e una
    giurisdizione senza regola non paga niente.
    """

    NOTTI, OSPITI = 30, 2

    def _tassa(self, **campi):
        return calcola_tassa(RegolaTassa(per_persona_notte_cents=350, **campi),
                             notti=self.NOTTI, ospiti=self.OSPITI)

    def test_il_caso_SANO_resta_intatto(self):
        """Prima di tutto la direzione opposta: la riparazione non deve spegnere il buono.

        Regola ferrea 10: una guardia che grida sempre non distingue niente. Questo e' il
        ramo che deve TACERE.
        """
        c = self._tassa(max_notti_tassabili=7)
        self.assertEqual(7, c.notti_tassabili)
        self.assertEqual(350 * 7 * 2, c.tassa_cents)

    def test_cap_notti_NEGATIVO_non_diventa_NESSUN_cap(self):
        c = self._tassa(max_notti_tassabili=-1)
        self.assertEqual(
            0, c.tassa_cents,
            "un cap notti negativo (-1) e' una regola MALFORMATA: il modulo promette "
            "fail-closed, cioe' tassa 0. Invece toglieva il tetto e tassava tutte le %d "
            "notti, facendo pagare all'ospite piu' di qualunque configurazione valida."
            % self.NOTTI)

    def test_cap_notti_NON_INTERO_non_diventa_NESSUN_cap(self):
        """Stessa porta, chiave diversa: un `7.0` letto da un JSON invece di un `7`."""
        c = self._tassa(max_notti_tassabili=7.0)
        self.assertEqual(0, c.tassa_cents,
                         "un cap notti non intero e' malformato quanto uno negativo: "
                         "`7.0` arriva da qualunque JSON e non deve togliere il tetto")

    def test_tetto_per_persona_NEGATIVO_non_diventa_NESSUN_tetto(self):
        """LA SECONDA PORTA, e nessuno l'aveva mai guardata."""
        c = self._tassa(tetto_per_persona_soggiorno_cents=-1)
        self.assertEqual(
            0, c.tassa_cents,
            "un tetto per-persona negativo e' malformato: trattandolo come «assente» il "
            "modulo toglieva il tetto al soggiorno e faceva pagare l'intero per-persona-notte")

    def test_il_valore_ASSENTE_resta_legittimo(self):
        """⛔ «INVALIDO» E «ASSENTE» DEVONO RESTARE DUE COSE DIVERSE.

        Se la riparazione facesse cadere anche `None`, spegnerebbe la tassa di ogni citta'
        senza cap -- che sono la maggioranza. Questa e' la guardia che impedisce di
        «riparare» accecando: e' la stessa forma dello sbaglio gia' visto, dove restringere
        un controllo lo aveva reso cieco invece che preciso.
        """
        c = self._tassa(max_notti_tassabili=None, tetto_per_persona_soggiorno_cents=None)
        self.assertEqual(self.NOTTI, c.notti_tassabili)
        self.assertEqual(350 * self.NOTTI * 2, c.tassa_cents)

    def test_cap_ZERO_resta_valido_e_significa_zero_notti(self):
        """`0` e' un intero non-negativo: e' una regola VALIDA che dice «non tassare».
        Non va confusa con una malformata. Comportamento invariato, pinnato qui."""
        c = self._tassa(max_notti_tassabili=0)
        self.assertEqual(0, c.notti_tassabili)
        self.assertEqual(0, c.tassa_cents)


class TestLaCinturaAntiAbusoNonPuoRompereIlBILANCIO(unittest.TestCase):
    """⛔ LE DUE VOCI DEVONO SEMPRE SOMMARE AL TOTALE. SEMPRE.

    `calcola_tassa` restituisce il totale **e** le due componenti che lo formano. Chi
    riconcilia (il giornale di `fase177`, il breakdown di `fase69`) si fida di
    `tassa == fissa + percentuale`. La cintura anti-abuso tagliava il totale a MAX_CENTS
    **senza toccare le componenti**, e da quel momento il record era internamente falso.

    MISURATO PRIMA DELLA RIPARAZIONE (sonda del 2026-08-12):
        tassa_cents ........... 100000000
        fissa + percentuale ... 400000010     -> buco di 300000010 cents

    ⛔ SCELTA DICHIARATA, non un dettaglio: sopra il tetto si va a **tassa 0**, non a
    `MAX_CENTS`. Una tassa di soggiorno da un milione di euro non esiste in nessuna citta'
    del mondo: e' una configurazione rotta, e per una configurazione rotta questo modulo ha
    gia' una risposta scritta -- non inventare una tassa. Restituire `MAX_CENTS` significava
    incassare dall'ospite un milione di euro «per prudenza».
    """

    def test_identita_delle_componenti_nel_caso_normale(self):
        """Il ramo che deve TACERE (regola ferrea 10)."""
        c = calcola_tassa(RegolaTassa(per_persona_notte_cents=200, percentuale_bps=300),
                          notti=2, ospiti=2, imponibile_cents=10000)
        self.assertEqual(c.componente_fissa_cents + c.componente_percentuale_cents,
                         c.tassa_cents)
        self.assertEqual(800 + 300, c.tassa_cents)

    def test_oltre_il_tetto_si_va_a_ZERO_e_le_componenti_seguono(self):
        c = calcola_tassa(RegolaTassa(per_persona_notte_cents=MAX_CENTS, percentuale_bps=1),
                          notti=2, ospiti=2, imponibile_cents=100000)
        self.assertEqual(0, c.tassa_cents,
                         "una tassa oltre MAX_CENTS e' una configurazione rotta: "
                         "fail-closed, non un milione di euro addebitato all'ospite")
        self.assertEqual(
            (0, 0), (c.componente_fissa_cents, c.componente_percentuale_cents),
            "il totale e' stato azzerato ma le componenti no: il record resta internamente "
            "falso ed e' esattamente il difetto che questa guardia esiste per impedire")

    def test_l_identita_vale_su_TUTTI_i_casi_di_questo_file(self):
        """L'invariante non e' un caso particolare: e' una proprieta' del modulo."""
        casi = [
            (RegolaTassa(per_persona_notte_cents=350), 3, 2, 0, 0),
            (RegolaTassa(percentuale_bps=500), 3, 2, 20000, 0),
            (RegolaTassa(per_persona_notte_cents=200, percentuale_bps=300), 2, 2, 10000, 0),
            (RegolaTassa(per_persona_notte_cents=350, max_notti_tassabili=7), 10, 4, 5000, 1),
            (RegolaTassa(per_persona_notte_cents=500,
                         tetto_per_persona_soggiorno_cents=1000), 10, 2, 0, 0),
            (REGOLA_ZERO, 5, 5, 99999, 0),
        ]
        for regola, notti, ospiti, imp, esenti in casi:
            c = calcola_tassa(regola, notti=notti, ospiti=ospiti,
                              imponibile_cents=imp, esenti=esenti)
            self.assertEqual(
                c.componente_fissa_cents + c.componente_percentuale_cents, c.tassa_cents,
                "identita' rotta su regola=%r notti=%d ospiti=%d" % (regola, notti, ospiti))


class TestLaCONFIGURAZIONEMalformataNonEntraDiNascosto(unittest.TestCase):
    """`da_env` e' la TERZA porta dello stesso difetto: la stringa che l'operatore scrive.

    `TASSE_SOGGIORNO='roma=350:-1:0'` -- un meno battuto per sbaglio -- non veniva scartato:
    diventava «Roma, 3,50 a persona a notte, NESSUN tetto di notti».
    MISURATO PRIMA (sonda del 2026-08-12): `roma=350:-1:0` -> 30 notti tassate, 21000 cents.
    """

    def setUp(self):
        self._var = "TASSE_TEST_MALFORMATE"

    def tearDown(self):
        os.environ.pop(self._var, None)

    def _reg(self, spec):
        os.environ[self._var] = spec
        return RegistroTasse.da_env(self._var)

    def test_citta_con_cap_negativo_viene_SCARTATA(self):
        reg = self._reg("roma=350:-1:0,milano=350:7:0")
        self.assertEqual(
            0, reg.calcola("roma", notti=30, ospiti=2).tassa_cents,
            "una riga di configurazione malformata deve essere scartata come se non "
            "esistesse (citta' ignota -> tassa 0), non accettata senza il suo tetto")

    def test_le_citta_SANE_della_stessa_riga_sopravvivono(self):
        """⛔ Scartare la riga rotta NON deve buttare via anche quelle giuste: sarebbe una
        riparazione che spegne il prodotto. E' il ramo che deve TACERE."""
        reg = self._reg("roma=350:-1:0,milano=350:7:0")
        self.assertEqual(350 * 7 * 2, reg.calcola("milano", notti=30, ospiti=2).tassa_cents)

    def test_il_formato_VALIDO_resta_intatto(self):
        reg = self._reg("roma=350:10:0,amsterdam=0::700")
        self.assertEqual(350 * 10 * 2, reg.calcola("roma", notti=15, ospiti=2).tassa_cents)
        self.assertEqual(700, reg.calcola("amsterdam", notti=2, ospiti=1,
                                          imponibile_cents=10000).tassa_cents)


class TestLaValutaNonPuoEsserePRESUNTA(unittest.TestCase):
    """L'endpoint pubblico `/api/tassa` (fase83:_tassa) mostra `as_dict()`, valuta compresa.

    `da_env` non aveva un campo per la valuta, quindi ogni regola caricata da configurazione
    nasceva `EUR`: Londra rispondeva **200 EUR** invece di 200 GBP.
    MISURATO PRIMA (sonda del 2026-08-12): `londra=200::0` -> as_dict()['valuta'] = 'EUR'.

    ⚠️ LIMITE DICHIARATO (D18 punto 3): questo tocca **l'etichetta mostrata**, non i soldi
    incassati. Sul percorso del denaro la regola NON viene da `da_env`: viene da
    `fase57.regola_tassa_di`, che legge `valuta` dalla stessa riga di `alloggi` da cui
    `fase59` prende la valuta dell'addebito -- quindi li' le due valute coincidono per
    costruzione. Verificato leggendo tutti e due i moduli, non supposto.
    """

    def setUp(self):
        self._var = "TASSE_TEST_VALUTA"

    def tearDown(self):
        os.environ.pop(self._var, None)

    def test_la_valuta_dichiarata_arriva_fino_ad_as_dict(self):
        os.environ[self._var] = "londra=200::0:GBP"
        reg = RegistroTasse.da_env(self._var)
        d = reg.calcola("londra", notti=2, ospiti=1).as_dict()
        self.assertEqual("GBP", d["valuta"],
                         "la valuta dichiarata in configurazione non arriva all'endpoint: "
                         "l'ospite di Londra vede la sua tassa etichettata in EUR")

    def test_senza_valuta_resta_EUR_come_prima(self):
        """Compatibilita' all'indietro: le configurazioni gia' scritte non cambiano."""
        os.environ[self._var] = "roma=350:10:0"
        reg = RegistroTasse.da_env(self._var)
        self.assertEqual("EUR", reg.calcola("roma", notti=2, ospiti=1).as_dict()["valuta"])

    def test_una_valuta_malformata_non_passa(self):
        os.environ[self._var] = "roma=350:10:0:eu ro"
        reg = RegistroTasse.da_env(self._var)
        self.assertEqual(
            0, reg.calcola("roma", notti=2, ospiti=1).tassa_cents,
            "una valuta malformata rende la riga malformata: si scarta, non si indovina")


class TestAZZERARE_NON_E_CHIUDERE(unittest.TestCase):
    """⛔ QUESTA CLASSE E' STATA RISCRITTA PERCHE' LA PRIMA VERSIONE CERTIFICAVA UNA
    CONCLUSIONE SBAGLIATA. La riga che segue e' la lezione piu' cara del 2026-08-12.

    La mattina di quel giorno avevo concluso -- e scritto in **due documenti** -- che la
    porta del database fosse «gia' chiusa a monte», perche' `fase57._tax()` azzerava ogni
    valore negativo prima che entrasse. Su quella conclusione avevo deciso di **non**
    riparare `fase57`, e avevo scritto una guardia che verificava proprio l'azzeramento:
    una guardia verde che sanciva il difetto.

    ⛔ AZZERARE NON E' CHIUDERE, QUANDO LO ZERO SIGNIFICA «NESSUN LIMITE».
    Nella tabella `alloggi` lo `0` di `tassa_max_notti` e' anche il DEFAULT, e
    `regola_tassa_di` lo legge come «nessun tetto» (`mx if mx > 0 else None`; l'oracolo
    indipendente di `test_happy_conti` dice lo stesso). Quindi il sanificatore non fermava
    il valore rotto: lo trasformava nella lettura **piu' cara per l'ospite**, cancellando
    ogni traccia dell'errore. `fase66` riceveva un `None` legittimo e non poteva accorgersi
    di niente -- la riparazione di `fase66` non copriva questa strada, e non poteva.

    L'ha smentita l'**E2E sulla catena vera** (`test_tassa_pre_acquisto`), non un
    ragionamento:
        host scrive  7 -> pubblica 201 -> tassa  4900 cents
        host scrive -1 -> pubblica 201 -> tassa 21000 cents
    +161,00 EUR addebitati per un refuso, e nessun avviso a nessuno.

    💡 LA LEZIONE OLTRE IL CASO: avevo guardato il sanificatore e mi ero fermato li'. Un
    valore «reso sicuro» non e' sicuro finche' non si guarda **che cosa significa quel
    valore per chi lo legge dopo**. Due moduli della stessa catena, lo stesso numero,
    significati opposti. ⛔ E il livello di collaudo che l'ha trovato -- l'E2E -- era
    esattamente quello che stavo per saltare dichiarandolo «gia' coperto».

    Qui si sorveglia il comportamento nuovo al livello di `valida_scheda`; la stessa cosa
    attraverso il server (422 + il nome del campo) sta in `test_tassa_pre_acquisto`.
    """

    BASE = {"host_id": "host-guardia", "slug": "casa-guardia", "titolo": "Casa Guardia",
            "citta": "Roma", "prezzo_notte_cents": 10000, "capacita": 2}

    def _valida(self, **campi):
        from fase57_vetrina import valida_scheda
        dati = dict(self.BASE)
        dati.update(campi)
        return valida_scheda(dati)

    def test_un_cap_notti_NEGATIVO_fa_RIFIUTARE_la_scheda(self):
        ok, motivo, scheda = self._valida(tassa_max_notti=-1)
        self.assertFalse(ok, "la scheda passa: il valore viene azzerato, lo zero significa "
                             "«nessun tetto» e l'ospite paga la tassa su TUTTE le notti")
        self.assertEqual("tassa_max_notti_non_valido", motivo)
        self.assertIsNone(scheda)

    def test_un_cap_notti_NON_INTERO_fa_RIFIUTARE_la_scheda(self):
        ok, motivo, _ = self._valida(tassa_max_notti=7.5)
        self.assertFalse(ok)
        self.assertEqual("tassa_max_notti_non_valido", motivo)

    def test_una_tassa_per_persona_NEGATIVA_fa_RIFIUTARE_la_scheda(self):
        ok, motivo, _ = self._valida(tassa_pp_notte_cents=-350)
        self.assertFalse(ok)
        self.assertEqual("tassa_pp_notte_cents_non_valido", motivo)

    def test_una_percentuale_FUORI_SCALA_fa_RIFIUTARE_la_scheda(self):
        """Il tetto vale in tutt'e due i versi: 10001 bps sarebbe piu' del 100%."""
        ok, motivo, _ = self._valida(tassa_perc_bps=10001)
        self.assertFalse(ok)
        self.assertEqual("tassa_perc_bps_non_valido", motivo)

    def test_un_BOOLEANO_non_e_un_numero(self):
        """`True` in Python vale 1: senza il controllo sui bool passerebbe per un intero
        valido e diventerebbe «tetto di 1 notte» senza che nessuno l'abbia chiesto."""
        ok, motivo, _ = self._valida(tassa_max_notti=True)
        self.assertFalse(ok)
        self.assertEqual("tassa_max_notti_non_valido", motivo)

    def test_i_valori_VALIDI_passano_intatti(self):
        """Il ramo che deve TACERE: la riparazione non deve rifiutare le tasse vere."""
        ok, motivo, s = self._valida(tassa_pp_notte_cents=350, tassa_max_notti=7,
                                     tassa_perc_bps=500)
        self.assertTrue(ok, "rifiutata una scheda valida (%r)" % motivo)
        self.assertEqual((350, 7, 500),
                         (s.tassa_pp_notte_cents, s.tassa_max_notti, s.tassa_perc_bps))

    def test_ASSENTE_e_NULLO_restano_legittimi(self):
        """⛔ «Assente» non e' «invalido» -- e' la distinzione che regge tutto il lavoro di
        oggi. Se cadesse anche questa, nessun host potrebbe piu' pubblicare senza tassa."""
        for campi in ({}, {"tassa_max_notti": 0}, {"tassa_max_notti": None},
                      {"tassa_max_notti": ""}):
            ok, motivo, s = self._valida(**campi)
            self.assertTrue(ok, "rifiutato un annuncio SENZA tassa (%r -> %r)"
                                % (campi, motivo))
            self.assertEqual(0, s.tassa_max_notti)


class TestIPuntiCHEILGIUDICEHaTrovatoSCOPERTI(unittest.TestCase):
    """⛔ QUESTE GUARDIE NON LE HO PENSATE IO: ME LE HA CHIESTE IL GIUDICE.

    Al primo giro di mutazione su `fase66` (2026-08-12): **30 mutanti provati, 14 uccisi,
    16 SOPRAVVISSUTI**. Un sopravvissuto e' un punto del codice che si puo' rompere senza
    che nessun collaudo se ne accorga. Qui si chiudono quelli **uccidibili**, e ognuno
    racconta una cosa che il ragionamento non aveva visto.
    """

    def test_la_regola_e_IMMUTABILE(self):
        """MUTANTE riga 86: `@dataclass(frozen=True)` -> `frozen=False`. Sopravvissuto.

        Nessun collaudo verificava che una regola non si possa modificare dopo la nascita.
        Non e' pedanteria: `RegolaTassa` viene letta dal catalogo e passata in giro; se
        diventasse scrivibile, un modulo a valle potrebbe alzare la tassa di un annuncio
        **dopo** che il preventivo l'ha calcolata, e il totale firmato non corrisponderebbe
        piu' a nulla di verificabile.
        """
        import dataclasses
        regola = RegolaTassa(per_persona_notte_cents=350)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            regola.per_persona_notte_cents = 999999

    def test_il_calcolo_e_IMMUTABILE(self):
        """MUTANTE riga 99: stessa cosa su `CalcoloTassa`. Sopravvissuto.

        Questo e' il record che finisce nel preventivo e nel giornale: se fosse scrivibile,
        l'importo della tassa potrebbe cambiare fra il calcolo e la registrazione contabile.
        """
        import dataclasses
        calcolo = calcola_tassa(RegolaTassa(per_persona_notte_cents=350), notti=2, ospiti=1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            calcolo.tassa_cents = 0

    def test_una_tassa_per_persona_NON_VALIDA_spegne_TUTTA_la_regola(self):
        """MUTANTE riga 78: il primo `return True` di `_regola_malformata`. Sopravvissuto.

        ⛔ E il motivo per cui sopravviveva insegna piu' del mutante: **tutte** le mie
        guardie sulla regola malformata usavano un `per_persona_notte_cents` VALIDO (350) e
        rompevano solo i due campi `Optional`. Quel primo ciclo non lo attraversava nessuno.
        Una guardia che non passa da un ramo non lo sorveglia, anche se il file «e' coperto».

        L'osservabile e' la componente PERCENTUALE, non il totale: prima della riparazione
        un `per_persona` rotto azzerava solo la sua componente e la percentuale **continuava
        a essere addebitata**. Se guardassi solo `tassa_cents` non distinguerei le due cose.
        """
        c = calcola_tassa(RegolaTassa(per_persona_notte_cents=-1, percentuale_bps=500),
                          notti=2, ospiti=1, imponibile_cents=20000)
        self.assertEqual(0, c.componente_percentuale_cents,
                         "una regola con un campo rotto non e' meta' valida: e' rotta. "
                         "La percentuale non deve essere addebitata lo stesso")
        self.assertEqual(0, c.tassa_cents)

    def test_una_percentuale_NON_VALIDA_spegne_TUTTA_la_regola(self):
        """Stessa porta, secondo campo del ciclo: qui e' la componente FISSA a dover tacere."""
        c = calcola_tassa(RegolaTassa(per_persona_notte_cents=350, percentuale_bps=-500),
                          notti=2, ospiti=1, imponibile_cents=20000)
        self.assertEqual(0, c.componente_fissa_cents)
        self.assertEqual(0, c.tassa_cents)

    def test_la_riga_scartata_NON_ENTRA_nel_registro(self):
        """MUTANTE riga 223: `or` -> `and` nel controllo dei valori negativi. Sopravvissuto.

        ⛔ QUESTA E' LA LEZIONE PIU' IMPORTANTE DEL GIRO, e riguarda una MIA guardia.
        `test_citta_con_cap_negativo_viene_SCARTATA` guardava la **tassa** risultante (0) e
        col mutante restava verde lo stesso: perche' la riga rotta entrava nel registro, ma
        poi `_regola_malformata` la fermava piu' a valle. **Le due riparazioni si coprivano
        a vicenda**, e la mia guardia stava misurando la seconda credendo di misurare la
        prima. Difesa in profondita' e' una virtu' del PRODOTTO e una trappola per i TEST.

        Qui l'osservabile e' il registro stesso: la citta' non deve proprio esserci.
        """
        var = "TASSE_TEST_REGISTRO"
        os.environ[var] = "roma=350:-1:0"
        try:
            reg = RegistroTasse.da_env(var)
            self.assertIs(
                REGOLA_ZERO, reg.regola("roma"),
                "la riga malformata e' entrata nel registro: viene fermata solo piu' a "
                "valle, e se un domani cadesse quella seconda difesa nessuno se ne "
                "accorgerebbe da qui")
        finally:
            os.environ.pop(var, None)

    def test_OGNI_campo_negativo_scarta_la_riga_DA_SOLO(self):
        """MUTANTE riga 223: il PRIMO `or` -> `and`. Sopravvissuto al giro precedente.

        ⛔ IL MOTIVO E' UNA PRECEDENZA DI OPERATORI, e mi era sfuggito: `A and B or C` si
        legge `(A and B) or C`. La mia prova usava una riga dove era vero **solo** `C`
        (`roma=350:-1:0`), quindi il mutante restava verde: `C` da solo bastava ancora a
        scartarla. Un controllo con tre condizioni in `or` va provato **una condizione alla
        volta**, altrimenti si sta verificando la piu' comoda.
        """
        var = "TASSE_TEST_OGNI_CAMPO"
        for spec, quale in (("roma=-350:7:0", "tassa per persona negativa"),
                            ("roma=350:7:-500", "percentuale negativa"),
                            ("roma=350:-1:0", "cap notti negativo")):
            os.environ[var] = spec
            try:
                reg = RegistroTasse.da_env(var)
                self.assertIs(REGOLA_ZERO, reg.regola("roma"),
                              "%r (%s) doveva bastare DA SOLO a far scartare la riga"
                              % (spec, quale))
            finally:
                os.environ.pop(var, None)

    def test_un_cap_notti_ZERO_e_valido_e_NON_fa_scartare_la_riga(self):
        """MUTANTE riga 223: `maxn < 0` -> `maxn <= 0`. Sopravvissuto.

        `0` e' un intero non-negativo: e' una regola valida che dice «non tassare nessuna
        notte». Confonderla con una malformata butterebbe via una configurazione legittima.
        Nessuna prova stava sul confine fra `0` e `-1` **passando da `da_env`**: la stavo
        provando solo costruendo la `RegolaTassa` a mano, cioe' saltando il parser.
        """
        var = "TASSE_TEST_CAP_ZERO"
        os.environ[var] = "roma=350:0:0"
        try:
            regola = RegistroTasse.da_env(var).regola("roma")
            self.assertIsNot(REGOLA_ZERO, regola,
                             "una riga con cap 0 e' valida: non deve essere scartata")
            self.assertEqual(0, regola.max_notti_tassabili)
        finally:
            os.environ.pop(var, None)

    def test_una_tassa_ESATTAMENTE_al_tetto_si_paga_ancora(self):
        """MUTANTE riga 153: `tassa > MAX_CENTS` -> `>=`. Sopravvissuto.

        Un errore di un passo sul confine: col `>=` una tassa esattamente pari al tetto
        verrebbe buttata a zero invece di essere incassata. Nessun collaudo stava sul
        confine -- stavano tutti ben oltre.
        """
        c = calcola_tassa(RegolaTassa(per_persona_notte_cents=MAX_CENTS),
                          notti=1, ospiti=1)
        self.assertEqual(MAX_CENTS, c.tassa_cents,
                         "una tassa esattamente pari al tetto e' ancora dentro il tetto: "
                         "il tetto e' un limite superiore, non un valore proibito")
        self.assertEqual(MAX_CENTS, c.componente_fissa_cents)


class TestLORACOLO_LaProvaDellaRimozione(unittest.TestCase):
    """⛔ LA DIMOSTRAZIONE CHE HA GIUSTIFICATO UNA RIMOZIONE DI CODICE DI PRODUZIONE.

    Il 2026-08-12 sono stati tolti da `calcola_tassa` i controlli diventati ridondanti dopo
    la precondizione `_regola_malformata`. Erano 11 punti che il Giudice segnalava come non
    sorvegliati e che **nessun collaudo poteva uccidere**, perche' non cambiavano nessun
    risultato osservabile. La scelta era: dichiararli equivalenti (vietato da B6 senza
    dimostrazione, e nell'unico posto dove un errore diventa cecita' permanente) oppure
    togliere il codice morto **dimostrando** che il risultato non cambia.

    ⛔ MA UNA DIMOSTRAZIONE CHE VIVE IN UNA CARTELLA TEMPORANEA NON E' UNA DIMOSTRAZIONE:
    sparisce a fine sessione e resta solo la parola di chi l'ha scritta, in un commento. E'
    la lezione degli attrezzi orfani trovati per fortuna il 2026-08-11. Per questo la
    versione prudente vive in `collaudi/oracolo_tassa.py` e viene rimessa alla prova **a
    ogni giro di suite**, non una volta sola nel giorno in cui faceva comodo.

    Costo misurato: **0,53 secondi** per 90.400 combinazioni.
    """

    @staticmethod
    def _oracolo():
        import importlib.util
        import os
        percorso = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "collaudi", "oracolo_tassa.py")
        spec = importlib.util.spec_from_file_location("_oracolo_tassa", percorso)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo

    def test_la_versione_vera_coincide_con_quella_PRUDENTE(self):
        o = self._oracolo()
        provate, differenze, eccezioni = o.confronta()
        self.assertGreater(provate, 90000,
                           "la griglia si e' ristretta a %d casi: una dimostrazione che si "
                           "assottiglia in silenzio non dimostra piu' quello che diceva"
                           % provate)
        self.assertEqual([], eccezioni[:5],
                         "`calcola_tassa` ha sollevato un'eccezione: il contratto dice "
                         "«mai un'eccezione, input invalidi -> tassa 0»")
        self.assertEqual(
            [], differenze[:5],
            "togliere quei controlli HA cambiato un risultato: la rimozione del 2026-08-12 "
            "non era neutra e va ripensata (%d casi diversi su %d)"
            % (len(differenze), provate))

    def test_L_ORACOLO_GRIDA_se_la_funzione_e_SBAGLIATA(self):
        """⛔ IL RAMO CHE DEVE GRIDARE (regola ferrea 10) — senza questo, il verde qui
        sopra sarebbe indistinguibile da un oracolo rotto che dice sempre «uguali».

        Il guasto iniettato e' minuscolo apposta: **un centesimo in piu'** sulla tassa,
        solo quando c'e' una tassa. Se l'oracolo vedesse solo le differenze grosse, non
        servirebbe a niente: i difetti sui soldi di questo progetto sono stati quasi tutti
        da un passo -- un giorno, un confine, un arrotondamento.
        """
        o = self._oracolo()

        def quasi_giusta(*args):
            tassa, fissa, perc, notti, ospiti = o._vero(*args)
            return (tassa + 1 if tassa else 0, fissa, perc, notti, ospiti)

        provate, differenze, eccezioni = o.confronta(funzione_vera=quasi_giusta)
        self.assertEqual([], eccezioni[:5])
        self.assertGreater(
            len(differenze), 0,
            "con una funzione sbagliata di UN CENTESIMO l'oracolo tace: non e' un oracolo, "
            "e' un ornamento (su %d combinazioni provate)" % provate)


if __name__ == "__main__":
    unittest.main()
