"""Test Fase 119 - Calendario prezzi visuale. Provider iniettato: nessun DB."""
import unittest

from fase119_calendario_prezzi import (calendario_html, costruisci_calendario)


def stato_finto(slug, g):
    if g == "2026-08-08":                                  # sabato agosto, prenotato
        return {"prezzo_netto_cents": 10000, "unita": 1, "venduto": 1}
    if g == "2026-08-09":
        return {"prezzo_netto_cents": 10000, "unita": 2, "venduto": 0}
    return {}                                              # non aperto


def stato_reale(slug, g):
    """Chiavi ESATTE di fase58.stato_giorno (riga DB): unita_occupate/chiuso,
    MAI venduto/occupati. Il vecchio finto mascherava il bug #33."""
    righe = {
        "2026-08-08": {"prezzo_netto_cents": 10000, "unita_totali": 1,
                       "unita_occupate": 1, "chiuso": 0, "min_notti": 1},
        "2026-08-09": {"prezzo_netto_cents": 10000, "unita_totali": 2,
                       "unita_occupate": 0, "chiuso": 0, "min_notti": 1},
        "2026-08-10": {"prezzo_netto_cents": 10000, "unita_totali": 1,
                       "unita_occupate": 0, "chiuso": 1, "min_notti": 1},
        "2026-08-11": {"prezzo_netto_cents": 0, "unita_totali": 0,
                       "unita_occupate": 0, "chiuso": 1, "min_notti": 1},
        "2026-08-12": {"prezzo_netto_cents": 10000, "unita_totali": 1,
                       "unita_occupate": 1, "chiuso": 1, "min_notti": 1},
    }
    return righe.get(g)


class TestContrattoProviderReale(unittest.TestCase):
    """Bug #33 (provato live): col provider reale un giorno PIENO appariva
    'libero' e un giorno CHIUSO appariva 'libero' con prezzo suggerito."""

    def test_pieno_e_chiuso_col_provider_reale(self):
        c = costruisci_calendario("casa", "2026-08-08", "2026-08-12",
                                  stato_giorno=stato_reale)
        stati = {x["giorno"]: x["stato"] for x in c}
        self.assertEqual(stati["2026-08-08"], "prenotato")
        self.assertEqual(stati["2026-08-09"], "libero")
        self.assertEqual(stati["2026-08-10"], "chiuso")
        self.assertEqual(stati["2026-08-11"], "chiuso")   # chiuso senza prezzo
        # bug #35: VENDUTA vince su CHIUSA (mai nascondere una prenotazione viva)
        self.assertEqual(stati["2026-08-12"], "prenotato")

    def test_chiuso_senza_prezzo_niente_prezzi(self):
        c = costruisci_calendario("casa", "2026-08-11", "2026-08-11",
                                  stato_giorno=stato_reale)
        self.assertIsNone(c[0]["prezzo_cents"])
        self.assertIsNone(c[0]["prezzo_dinamico_cents"])

    def test_chiuso_con_prezzo_mantiene_il_prezzo(self):
        c = costruisci_calendario("casa", "2026-08-10", "2026-08-10",
                                  stato_giorno=stato_reale)
        self.assertEqual(c[0]["stato"], "chiuso")
        self.assertEqual(c[0]["prezzo_cents"], 10000)


class TestCalendario(unittest.TestCase):
    def test_celle_per_giorno(self):
        c = costruisci_calendario("casa", "2026-08-08", "2026-08-10",
                                  stato_giorno=stato_finto, occupazione_bps=5000)
        self.assertEqual(len(c), 3)
        self.assertEqual(c[0]["stato"], "prenotato")
        self.assertEqual(c[1]["stato"], "libero")
        self.assertEqual(c[2]["stato"], "non_aperto")

    def test_prezzo_dinamico_applicato(self):
        c = costruisci_calendario("casa", "2026-08-09", "2026-08-09",
                                  stato_giorno=stato_finto, occupazione_bps=5000)
        # 2026-08-09 domenica, agosto 13000 -> 10000*1.3 = 13000
        self.assertEqual(c[0]["prezzo_cents"], 10000)
        self.assertEqual(c[0]["prezzo_dinamico_cents"], 13000)

    def test_range_invalido_vuoto(self):
        self.assertEqual(costruisci_calendario("c", "2026-08-10", "2026-08-01",
                         stato_giorno=stato_finto), [])

    def test_provider_solleva_cella_errore(self):
        def boom(s, g):
            raise RuntimeError("db giu")
        c = costruisci_calendario("c", "2026-08-08", "2026-08-08", stato_giorno=boom)
        self.assertEqual(c[0]["stato"], "errore")

    def test_html_xss_safe(self):
        celle = [{"giorno": "2026-08-08", "stato": "libero",
                  "prezzo_dinamico_cents": 13000}]
        h = calendario_html(celle)
        self.assertIn("<table", h)
        # prima si pretendeva "€130.00": il simbolo dell'euro era SCRITTO DENTRO
        # il calendario, quindi un annuncio in yen mostrava "€" davanti a degli
        # yen. Ora l'importo porta la sua valuta e rispetta i suoi decimali.
        self.assertIn("130.00 EUR", h)
        from fase119_calendario_prezzi import calendario_html as _ch
        self.assertIn("13000 JPY", _ch(celle, "JPY"))
        self.assertNotIn("€", _ch(celle, "JPY"))

    def test_html_non_aperto(self):
        h = calendario_html([{"giorno": "2026-08-08", "stato": "non_aperto",
                              "prezzo_dinamico_cents": None}])
        self.assertIn("-", h)


def _fra(giorni):
    """Data RELATIVA a oggi, mai cablata (appendice R1 punto 4: le date fisse
    diventano bombe a tempo). Serve a esercitare i fattori temporali."""
    from datetime import date, timedelta
    return (date.today() + timedelta(days=giorni)).isoformat()


class TestFattoreTemporaleCollegato(unittest.TestCase):
    """⛔ DIFETTO VIVO: `costruisci_calendario` NON passa mai `giorni_all_arrivo`
    a fase106, quindi il parametro resta al default 30 e i DUE fattori temporali
    del motore — last-minute (8500 = -15%) e anticipo (10500 = +5%) — valgono
    10000 per ogni giorno, per sempre.

    DENOMINATORE (appendice #15): il motore applica QUATTRO fattori
    (occupazione · stagione · weekend · anticipo). Il calendario ne alimenta
    TRE; questa classe copre il quarto, cioè 1 su 4.

    Il lead time («time to arrival») e' un fattore standard del ricavo
    alberghiero, non un'invenzione nostra: Mews 2026 e Lighthouse lo elencano
    accanto a occupazione e stagionalita' (fonti in appendice, voce R2).

    ORACOLO INDIPENDENTE (collaudo 5): il valore atteso non e' scritto a mano,
    lo ricalcola fase106 ricevendo la distanza VERA del giorno da oggi. Cosi'
    la guardia non conosce il numero: conosce la relazione."""

    def _calendario_di(self, giorno):
        return costruisci_calendario(
            "casa", giorno, giorno, occupazione_bps=5000,
            stato_giorno=lambda s, g: {"prezzo_netto_cents": 10000,
                                       "unita_totali": 1, "unita_occupate": 0,
                                       "chiuso": 0})[0]

    def _atteso(self, giorno, distanza):
        import fase106_dynamic_pricing as dyn
        return dyn.calcola_prezzo(10000, occupazione_bps=5000, data=giorno,
                                  giorni_all_arrivo=distanza)

    def test_last_minute_abbassa_il_suggerito(self):
        """Un giorno a due passi da oggi va svenduto, non tenuto a listino."""
        g = _fra(1)
        cella, atteso = self._calendario_di(g), self._atteso(g, 1)
        self.assertEqual(cella["prezzo_dinamico_cents"], atteso["prezzo_cents"],
                         "il fattore last-minute non arriva al calendario")
        self.assertEqual(atteso["fattori"]["anticipo"], 8500)

    def test_anticipo_alza_il_suggerito(self):
        """Un giorno molto lontano vale di piu': chi prenota adesso paga il posto."""
        g = _fra(200)
        cella, atteso = self._calendario_di(g), self._atteso(g, 200)
        self.assertEqual(cella["prezzo_dinamico_cents"], atteso["prezzo_cents"],
                         "il fattore anticipo non arriva al calendario")
        self.assertEqual(atteso["fattori"]["anticipo"], 10500)

    def test_un_giorno_gia_passato_non_prende_lo_sconto_ultimo_minuto(self):
        """⛔ Difetto INTRODOTTO dalla riparazione e ripreso da un test che
        c'era gia': la prima versione passava al motore la distanza NEGATIVA di
        un giorno trascorso, il motore la leggeva come «<= 2 giorni» e applicava
        -15% a notti gia' finite. Il calendario dell'host mostra anche il
        passato, e una notte del mese scorso non si riempie svendendola.
        DENOMINATORE: 3 giorni nel passato (ieri, una settimana fa, un mese fa),
        piu' oggi stesso che invece DEVE restare last-minute."""
        import fase106_dynamic_pricing as dyn
        for indietro in (-1, -7, -30):
            g = _fra(indietro)
            neutro = dyn.calcola_prezzo(10000, occupazione_bps=5000, data=g,
                                        giorni_all_arrivo=30)
            self.assertEqual(
                self._calendario_di(g)["prezzo_dinamico_cents"],
                neutro["prezzo_cents"],
                "il giorno %s e' gia' passato e ha preso un fattore temporale" % g)
        oggi = _fra(0)
        self.assertEqual(
            self._calendario_di(oggi)["prezzo_dinamico_cents"],
            self._atteso(oggi, 0)["prezzo_cents"],
            "oggi stesso deve restare last-minute: e' ancora vendibile")

    def test_tre_distanze_diverse_ognuna_col_suo_fattore(self):
        """Appendice #9: la correzione si accetta su input che nel test non
        c'erano — tre distanze, una per fascia (last-minute · neutra · anticipo).

        ⚠️ La prima versione di questa guardia chiedeva solo che i tre
        moltiplicatori fossero DIVERSI, ed era VERDE col difetto dentro: giorni
        diversi hanno gia' stagione e weekend diversi, quindi i tre numeri non
        coincidevano comunque. Un test che passa per il motivo sbagliato e' un
        ornamento (regola ferrea 2). Ora ogni fascia si confronta con l'oracolo
        indipendente calcolato sulla SUA distanza vera.
        DENOMINATORE: 3 fasce su 3."""
        for distanza, atteso_bps in ((1, 8500), (30, 10000), (200, 10500)):
            g = _fra(distanza)
            cella, atteso = self._calendario_di(g), self._atteso(g, distanza)
            self.assertEqual(atteso["fattori"]["anticipo"], atteso_bps,
                             "fascia sbagliata nel collaudo, non nel prodotto")
            self.assertEqual(
                cella["prezzo_dinamico_cents"], atteso["prezzo_cents"],
                "a %d giorni da oggi il calendario suggerisce %s, il motore "
                "interrogato con la distanza vera dice %s"
                % (distanza, cella["prezzo_dinamico_cents"], atteso["prezzo_cents"]))


class TestRelazioniMetamorfiche(unittest.TestCase):
    """Il prezzo suggerito non ha un oracolo comodo: si verificano RELAZIONI fra
    input trasformati (metamorphic testing — Hillel Wayne 2019; Segura et al.,
    «A Survey on Metamorphic Testing», IEEE TSE 2016; arXiv 2211.12003).
    Tre relazioni, tutte sull'aritmetica del prezzo."""

    def test_scala_raddoppiare_la_base_raddoppia_il_suggerito(self):
        """f(2b) == 2·f(b), a meno del troncamento della divisione intera.
        Lo scarto ammesso e' 1 cent e va DICHIARATO: la divisione intera non e'
        lineare (fixed-point arithmetic, specbranch.com 2021)."""
        import fase106_dynamic_pricing as dyn
        for base in (1, 7, 99, 137, 10000, 12345, 999999):
            a = dyn.calcola_prezzo(base, occupazione_bps=9000,
                                   data="2026-08-15")["prezzo_cents"]
            b = dyn.calcola_prezzo(base * 2, occupazione_bps=9000,
                                   data="2026-08-15")["prezzo_cents"]
            self.assertLessEqual(abs(2 * a - b), 1,
                                 "base=%d: 2*%d != %d" % (base, a, b))

    def test_permutazione_l_ordine_dei_fattori_sposta_al_massimo_un_bps(self):
        """⚠️ Questa relazione NON vale in modo esatto, ed e' MISURATO: la catena
        `m = m * v // 10000` tronca a ogni passo, quindi l'ordine dei fattori
        puo' cambiare il risultato (la divisione intera non e' lineare —
        fixed-point arithmetic, specbranch.com 2021).

        Il campione non bastava a vederlo: su due quaterne scelte a mano l'ordine
        NON contava, e solo la prova ESAUSTIVA ha trovato il caso vero. E' il
        motivo per cui questa guardia gira su tutte le combinazioni possibili.

        Oggi l'ordine e' FISSO (ordine di inserimento nel dict `fattori`:
        occupazione · stagione · weekend · anticipo), quindi il prezzo e'
        deterministico e nessuno ci perde. Non e' un difetto vivo: e' una
        fragilita'. Questa guardia CONGELA il debito misurato e vieta che
        cresca — se qualcuno aggiunge un fattore o cambia l'accumulo e lo
        scarto peggiora, diventa rossa lo stesso giorno.

        MISURATO il 2026-08-13: 13 quaterne su 216 sono sensibili all'ordine,
        scarto massimo 1 punto base (= 1 centesimo su 100 €, 1 € su 10.000 €).
        DENOMINATORE: 216 quaterne · 24 ordini = 5184 catene."""
        import itertools
        import fase106_dynamic_pricing as dyn
        p = dyn.PoliticaPrezzo()
        occ = (p.occ_alta_bps, p.occ_bassa_bps, 10000)
        sta = tuple(p.stagione_bps.values())
        wk = (p.weekend_bps, 10000)
        ant = (p.last_minute_bps, p.anticipo_bps, 10000)
        quaterne = catene = sensibili = 0
        peggior_scarto = 0
        for q in itertools.product(occ, sta, wk, ant):
            quaterne += 1
            valori = set()
            for perm in itertools.permutations(q):
                m = 10000
                for v in perm:
                    m = m * v // 10000
                valori.add(m)
                catene += 1
            scarto = max(valori) - min(valori)
            if scarto:
                sensibili += 1
                peggior_scarto = max(peggior_scarto, scarto)
        self.assertEqual((quaterne, catene), (216, 5184))   # il denominatore
        self.assertLessEqual(peggior_scarto, 1,
                             "l'ordine dei fattori ora sposta il moltiplicatore "
                             "di %d punti base (era 1)" % peggior_scarto)
        self.assertLessEqual(sensibili, 13,
                             "le quaterne sensibili all'ordine sono %d (erano 13): "
                             "il debito di troncamento e' cresciuto" % sensibili)

    def test_monotonia_piu_occupazione_mai_meno_prezzo(self):
        """Riempirsi non puo' MAI far scendere il suggerito. DENOMINATORE: 41
        livelli di occupazione da 0 a 10000 bps, passo 250."""
        import fase106_dynamic_pricing as dyn
        prec, letti = None, 0
        for occ in range(0, 10001, 250):
            p = dyn.calcola_prezzo(10000, occupazione_bps=occ,
                                   data="2026-08-15")["prezzo_cents"]
            letti += 1
            if prec is not None:
                self.assertGreaterEqual(p, prec,
                                        "occupazione %d fa SCENDERE il prezzo "
                                        "(%d -> %d)" % (occ, prec, p))
            prec = p
        self.assertEqual(letti, 41)                         # il denominatore


class TestIQuattroBuchiDelGiudice(unittest.TestCase):
    """I quattro mutanti SOPRAVVISSUTI al giro del 2026-08-13 (17 punti, 13
    uccisi). ⛔ Nessuno e' stato dichiarato equivalente: per ognuno e' stato
    MISURATO l'input che distingue il codice sano dal mutante, e quell'input e'
    l'asserzione qui sotto. Un buco di mutazione si chiude scrivendo il test che
    manca, non addolcendo il codice.
    DENOMINATORE: 4 sopravvissuti su 4."""

    def _celle(self, da, a):
        return costruisci_calendario(
            "c", da, a, oggi="2026-06-01",
            stato_giorno=lambda s, g: {"prezzo_netto_cents": 10000,
                                       "unita_totali": 1, "unita_occupate": 0,
                                       "chiuso": 0})

    def test_il_tetto_del_range_sta_sui_GIORNI_non_sulle_celle(self):
        """Mutante riga 26 `> 366` -> `>= 366`. Il tetto guarda la DIFFERENZA fra
        le due date, che e' una notte in meno del numero di celle: il range piu'
        lungo accettato ha `.days == 366`, cioe' **367 celle**. Misurato, non
        dedotto — e il confine si prova SUL confine (D4)."""
        self.assertEqual(len(self._celle("2026-01-01", "2027-01-01")), 366)
        self.assertEqual(len(self._celle("2026-01-01", "2027-01-02")), 367)  # ultimo buono
        self.assertEqual(len(self._celle("2026-01-01", "2027-01-03")), 0)    # primo fuori

    def test_zero_unita_disponibili_non_e_un_giorno_prenotato(self):
        """Mutante riga 94 `unita > 0` -> `unita >= 0`. Con `>=`, un giorno che
        ha prezzo ma ZERO unita' passa il controllo «venduto >= unita» (0 >= 0) e
        viene mostrato all'host come **prenotato**: una prenotazione che non
        esiste. Peggio ancora sul giorno chiuso, dove nasconderebbe la chiusura."""
        def con(unita, venduto, chiuso):
            return costruisci_calendario(
                "c", "2026-06-15", "2026-06-15", oggi="2026-06-01",
                stato_giorno=lambda s, g: {"prezzo_netto_cents": 10000,
                                           "unita_totali": unita,
                                           "unita_occupate": venduto,
                                           "chiuso": chiuso})[0]["stato"]
        self.assertEqual(con(0, 0, 0), "libero")      # mutante: "prenotato"
        self.assertEqual(con(0, 0, 1), "chiuso")      # mutante: "prenotato"
        self.assertEqual(con(1, 1, 0), "prenotato")   # il caso vero resta vero
        self.assertEqual(con(2, 1, 0), "libero")      # mezzo pieno non e' pieno

    def test_la_cella_fallita_registra_la_TRACCIA_dell_errore(self):
        """Mutante riga 110 `exc_info=True` -> `False`. Il valore di ritorno non
        cambia (la cella resta «errore»), quindi nessun test lo vedeva: cambia
        cio' che finisce nel registro. Senza traccia resta «una cella e' fallita»
        e non si sa perche' — e' l'osservabile debole della regola ferrea 9."""
        import logging
        def boom(s, g):
            raise RuntimeError("db giu")
        with self.assertLogs("core_auto.calendario_prezzi", level=logging.WARNING) as reg:
            celle = costruisci_calendario("c", "2026-06-15", "2026-06-15",
                                          stato_giorno=boom)
        self.assertEqual(celle[0]["stato"], "errore")
        self.assertEqual(len(reg.records), 1)                    # il denominatore
        self.assertIsNotNone(reg.records[0].exc_info,
                             "il registro non porta la traccia: la diagnosi e' cieca")
        self.assertIn("RuntimeError", reg.output[0] + str(reg.records[0].exc_info))

    def test_un_importo_non_numerico_vale_zero_e_non_esplode(self):
        """Mutante riga 122 `and` -> `or`. Con `or` un booleano passa per numero
        (`True` diventa 1 centesimo) e una stringa arriva fino a `'%d' %` che
        solleva TypeError FUORI dal try: la griglia esplode invece di mostrare
        zero. Misurato su sei ingressi."""
        from fase119_calendario_prezzi import _importo
        for storto in (True, False, "ciao", None, 3.5):
            self.assertEqual(_importo(storto, "EUR"), "0.00 EUR",
                             "ingresso %r non azzerato" % (storto,))
        self.assertEqual(_importo(13000, "EUR"), "130.00 EUR")   # il caso buono regge


if __name__ == "__main__":
    unittest.main()
