"""Test Fase 98 - Policy commissione: rampa di lancio + split 2%/8% (10% a regime). Puro + integra fase88."""
import unittest

from fase88_registro_host import crea_registro_host
from fase98_policy_commissione import (commissione_bps_fonte, commissione_bps_per_host,
                                       commissione_cents, e_fondatore,
                                       fattura_startup_cents, ripartisci_host_guest)

SEG = b"x" * 32


class TestPerFonte(unittest.TestCase):
    def test_diretto_5_marketplace_10(self):
        self.assertEqual(commissione_bps_fonte("diretto"), 500)
        self.assertEqual(commissione_bps_fonte("diretto", 5000), 500)   # sempre 5%
        self.assertEqual(commissione_bps_fonte("marketplace", 1), 1000)
        self.assertEqual(commissione_bps_fonte("marketplace", 2000), 1000)

    def test_default_e_ignoto_marketplace(self):
        self.assertEqual(commissione_bps_fonte(""), 1000)
        self.assertEqual(commissione_bps_fonte(None), 1000)
        self.assertEqual(commissione_bps_fonte("xyz"), 1000)

    def test_no_loss_diretto_su_100eur(self):
        # 5% su 100€ = 500 cents; Stripe peggiore 2.9%+0.25 = 315; resta margine positivo
        self.assertGreater(commissione_cents(10000, commissione_bps_fonte("diretto")), 315)


class TestPolicyLegacyOrdinale(unittest.TestCase):
    # La regola ordinale "primi 1000" è LEGACY e NEUTRA: con i default a 10% non concede
    # sconti ordinali (la leva strategica è la rampa temporale, non l'ordine d'iscrizione).
    def test_default_10(self):
        self.assertEqual(commissione_bps_per_host(1), 1000)
        self.assertEqual(commissione_bps_per_host(1000), 1000)
        self.assertTrue(e_fondatore(1))
        self.assertTrue(e_fondatore(1000))

    def test_oltre_soglia_usa_post(self):
        self.assertEqual(commissione_bps_per_host(1001, bps_dopo=1800), 1800)
        self.assertFalse(e_fondatore(1001))

    def test_ordinale_ignoto_e_invalido_failsafe(self):
        # ignoto/non valido -> tariffa standard (post), MAI 0
        self.assertEqual(commissione_bps_per_host(0, bps_dopo=1800), 1800)
        self.assertEqual(commissione_bps_per_host(-5, bps_dopo=1800), 1800)
        self.assertEqual(commissione_bps_per_host("x", bps_dopo=1800), 1800)
        self.assertEqual(commissione_bps_per_host(None), 1000)   # default post=10%

    def test_soglia_configurabile(self):
        self.assertEqual(commissione_bps_per_host(50, soglia=10, bps_dopo=2000), 2000)
        self.assertEqual(commissione_bps_per_host(5, soglia=10), 1000)


class TestSplitAsimmetrico(unittest.TestCase):
    def test_2_piu_8_uguale_10(self):
        r = ripartisci_host_guest(10000)               # €100
        self.assertEqual(r["host_fee"], 200)           # 2%
        self.assertEqual(r["guest_fee"], 800)          # 8%
        self.assertEqual(r["nostra_commissione"], 1000)  # 10% totale
        self.assertEqual(r["netto_host"], 9800)        # incassa 100 - 2
        self.assertEqual(r["totale_ospite"], 10800)    # paga 100 + 8

    def test_conservazione_esatta_fuzz(self):
        for p in (1, 99, 100, 333, 10000, 12345, 999999):
            r = ripartisci_host_guest(p)
            # nostra commissione = quanto paga l'ospite - quanto incassa l'host
            self.assertEqual(r["nostra_commissione"],
                             r["totale_ospite"] - r["netto_host"])
            self.assertEqual(r["nostra_commissione"], r["host_fee"] + r["guest_fee"])
            self.assertGreaterEqual(r["netto_host"], 0)

    def test_cents_interi_no_float(self):
        r = ripartisci_host_guest(12345)
        for v in r.values():
            self.assertIsInstance(v, int)

    def test_commissione_cents_floor_e_clamp(self):
        self.assertEqual(commissione_cents(10000, 1000), 1000)
        self.assertEqual(commissione_cents(-5, 1000), 0)        # mai negativa
        self.assertEqual(commissione_cents(10000, 99999), 10000)  # clamp 100%

    def test_fattura_startup_solo_commissione(self):
        # tutela forfettario: solo il 10% è nostro fatturato, non i 100
        self.assertEqual(fattura_startup_cents(10000), 1000)


class TestIntegrazioneFase88Counter(unittest.TestCase):
    def test_numero_e_conta_host(self):
        reg = crea_registro_host(":memory:", SEG)
        reg.inizializza_schema()
        self.assertEqual(reg.conta_host(), 0)
        ids = []
        for i in range(3):
            e = reg.registra("host%d@x.it" % i, "passw0rd!", accetta_termini=True)
            self.assertTrue(e.ok, e.errore)
            ids.append(e.host_id)
        self.assertEqual(reg.conta_host(), 3)
        # ogni host ha un ordinale 1..3, unico; la tariffa a regime è 10% per tutti
        ordinali = sorted(reg.numero_host(h) for h in ids)
        self.assertEqual(ordinali, [1, 2, 3])
        for h in ids:
            self.assertTrue(e_fondatore(reg.numero_host(h)))
            self.assertEqual(commissione_bps_per_host(reg.numero_host(h)), 1000)

    def test_host_inesistente_ordinale_zero(self):
        reg = crea_registro_host(":memory:", SEG)
        reg.inizializza_schema()
        self.assertEqual(reg.numero_host("h_inesistente"), 0)
        # ordinale 0 -> non fondatore (fail-safe)
        self.assertFalse(e_fondatore(reg.numero_host("h_inesistente")))


class TestStatoScaglioneBordi(unittest.TestCase):
    """`stato_scaglione` e' la FONTE UNICA di verita' sugli scaglioni (la chiamano il
    preventivo di fase81 e il pannello di fase83). Prima del 2026-07-21 era coperta solo
    di striscio: un test di MUTAZIONE ha dimostrato che portando lo scaglione centrale
    dall'8% al 10% — un sovrapprezzo del 2% su ogni prenotazione di quella fascia —
    l'intera suite restava verde. Qui si presidiano tutti i bordi."""

    def test_i_tre_scaglioni_ai_bordi_esatti(self):
        from fase98_policy_commissione import (LANCIO_BPS_FASE1, LANCIO_BPS_REGIME,
                                               LANCIO_GIORNI_FASE1, LANCIO_GIORNI_GRATIS,
                                               stato_scaglione)
        attesi = [
            (0, "promo", 0),
            (LANCIO_GIORNI_GRATIS - 1, "promo", 0),
            (LANCIO_GIORNI_GRATIS, "fase1", LANCIO_BPS_FASE1),
            (LANCIO_GIORNI_GRATIS + 1, "fase1", LANCIO_BPS_FASE1),
            (LANCIO_GIORNI_FASE1 - 1, "fase1", LANCIO_BPS_FASE1),
            (LANCIO_GIORNI_FASE1, "regime", LANCIO_BPS_REGIME),
            (LANCIO_GIORNI_FASE1 + 500, "regime", LANCIO_BPS_REGIME),
        ]
        for giorni, scaglione, bps in attesi:
            s = stato_scaglione(giorni)
            self.assertEqual(s["scaglione"], scaglione,
                             "al giorno %d lo scaglione dovrebbe essere %s"
                             % (giorni, scaglione))
            self.assertEqual(s["bps"], bps,
                             "al giorno %d la commissione dovrebbe essere %d bps (%d%%), "
                             "trovata %d" % (giorni, bps, bps // 100, s["bps"]))

    def test_lo_scaglione_centrale_NON_E_quello_di_regime(self):
        """Il cuore del buco: se i due coincidessero, l'host della fascia centrale
        pagherebbe come uno a regime senza che nulla lo segnali."""
        from fase98_policy_commissione import (LANCIO_BPS_FASE1, LANCIO_BPS_REGIME,
                                               LANCIO_GIORNI_FASE1, LANCIO_GIORNI_GRATIS,
                                               stato_scaglione)
        self.assertLess(LANCIO_BPS_FASE1, LANCIO_BPS_REGIME,
                        "lo scaglione centrale deve costare MENO del regime")
        centrale = stato_scaglione((LANCIO_GIORNI_GRATIS + LANCIO_GIORNI_FASE1) // 2)
        regime = stato_scaglione(LANCIO_GIORNI_FASE1 + 10)
        self.assertLess(centrale["bps"], regime["bps"],
                        "la fascia intermedia paga quanto il regime: sovrapprezzo "
                        "invisibile su ogni prenotazione fra i 3 mesi e l'anno")

    def test_la_commissione_non_scende_mai_col_passare_del_tempo(self):
        """Monotonia: un host non deve mai pagare MENO invecchiando (e mai piu' del
        regime), altrimenti la rampa avrebbe un buco da qualche parte."""
        from fase98_policy_commissione import LANCIO_BPS_REGIME, stato_scaglione
        precedente = -1
        for giorni in range(0, 800, 7):
            bps = stato_scaglione(giorni)["bps"]
            self.assertGreaterEqual(bps, precedente,
                                    "al giorno %d la commissione SCENDE" % giorni)
            self.assertLessEqual(bps, LANCIO_BPS_REGIME,
                                 "al giorno %d si supera il regime" % giorni)
            precedente = bps

    def test_i_giorni_al_prossimo_scatto_sono_veri(self):
        """Il pannello mostra "mancano N giorni": se fosse sbagliato, si prometterebbe
        all'host una data che non arriva."""
        from fase98_policy_commissione import LANCIO_GIORNI_GRATIS, stato_scaglione
        for giorni in (0, 10, LANCIO_GIORNI_GRATIS - 1):
            s = stato_scaglione(giorni)
            self.assertEqual(s["giorni_al_prossimo"], LANCIO_GIORNI_GRATIS - giorni,
                             "conteggio sbagliato al giorno %d" % giorni)
            fra = stato_scaglione(giorni + s["giorni_al_prossimo"])
            self.assertEqual(fra["bps"], s["prossimo_bps"],
                             "lo scatto promesso non corrisponde a quello che accade")


class TestGliOTTOPUNTITrovatiDalGiudice(unittest.TestCase):
    """Gli 8 punti che il Giudice ha trovato SCOPERTI il 2026-08-19 (18 punti, 10 uccisi,
    8 sopravvissuti). Questo modulo decide **quanto paga l'host**: e' la cifra su cui un host
    decide se fidarsi di noi.

    ⛔ Nessuno degli otto stava nell'aritmetica -- quella era gia' sorvegliata bene. Stanno
    tutti in due posti che nessuno guardava: la **regola ordinale** (che con i valori di
    serie e' neutra, quindi invisibile) e i **campi che dichiarano la verita' all'host**
    («la promozione e' attiva?», «la tua anzianita' e' nota?»). Un numero giusto accanto a
    una dichiarazione falsa e' comunque una bugia detta a un host.
    """

    def test_la_regola_ordinale_riconosce_il_PRIMO_host_e_il_MILLESIMO(self):
        """⛔ DUE CONFINI CHE NESSUN TEST TOCCAVA, e sono invisibili di serie.

        `commissione_bps_per_host` e' la vecchia regola «i primi N host pagano meno». Con i
        valori di serie e' **neutra** (fondatori 10% = dopo 10%), quindi qualunque sbaglio ai
        suoi confini non si vede: i due numeri coincidono. Ma la funzione accetta i valori dal
        chiamante, e con uno sconto vero i confini contano:
          · host n.1 -- il primo host in assoluto -- deve avere la tariffa dei fondatori;
          · host n.1000 -- l'ultimo dentro la soglia -- deve averla ancora.
        Il Giudice ha spostato tutt'e due i confini di **un passo** e nessun test se n'e'
        accorto: `n < 1` -> `n <= 1` (il primo host perde lo sconto) e `n <= soglia` ->
        `n < soglia` (il millesimo lo perde). Un errore di un passo su una tariffa e' denaro
        vero addebitato a una persona vera.
        """
        FONDATORI, DOPO, SOGLIA = 500, 1000, 1000       # sconto VERO, se no il difetto e' cieco
        def bps(n):
            return commissione_bps_per_host(n, bps_fondatori=FONDATORI, bps_dopo=DOPO,
                                            soglia=SOGLIA)
        self.assertEqual(bps(1), FONDATORI,
                         "il PRIMO host non ha la tariffa dei fondatori: il confine di sotto "
                         "e' spostato di un passo")
        self.assertEqual(bps(SOGLIA), FONDATORI,
                         "l'host numero %d -- l'ultimo DENTRO la soglia -- non ha la tariffa "
                         "dei fondatori: il confine di sopra e' spostato di un passo" % SOGLIA)
        self.assertEqual(bps(SOGLIA + 1), DOPO,
                         "il primo host FUORI soglia deve pagare la tariffa piena")
        # e sotto l'uno non esiste nessun host: e' un ordinale, non un conteggio
        self.assertEqual(bps(0), DOPO, "un ordinale ZERO non e' un host: tariffa piena")
        self.assertEqual(bps(-5), DOPO, "un ordinale negativo non e' un host: tariffa piena")

    def test_un_BOOLEANO_come_anzianita_non_regala_la_promozione(self):
        """⛔ IL BUCO CHE COSTA DI PIU', ed e' lo stesso di `fase111`, in un altro modulo.

        In Python `True` **e'** un intero e vale 1. Il modulo lo esclude apposta, ma nessun
        test lo verificava: rotta quella condizione, tutta la suite restava verde.

        Col guasto dentro, un host la cui anzianita' arriva come `True` verrebbe letto come
        **1 giorno dalla registrazione**, cioe' dentro la finestra promozionale: commissione
        **0%** invece del **10% a regime**. Su ogni prenotazione di quell'host, per sempre,
        finche' qualcuno non se ne accorge guardando i conti.

        ⚠️ E la regola di questo modulo e' scritta nel suo stesso docstring: *«anzianita'
        ignota -> tariffa a regime, non si regala lo 0% per errore»*. Un booleano E' una
        anzianita' ignota: non e' un numero di giorni, e' un interruttore.
        """
        from fase98_policy_commissione import LANCIO_BPS_REGIME, stato_scaglione
        for booleano in (True, False):
            s = stato_scaglione(booleano)
            self.assertEqual(
                s["bps"], LANCIO_BPS_REGIME,
                "anzianita' = %r ha ottenuto la commissione %d invece del regime %d: un "
                "booleano non e' un numero di giorni, e leggerlo come tale regala la "
                "promozione a chi non ne ha diritto" % (booleano, s["bps"], LANCIO_BPS_REGIME))
            self.assertEqual(s["scaglione"], "regime",
                             "anzianita' = %r ha ottenuto lo scaglione %r" % (booleano,
                                                                              s["scaglione"]))
            self.assertIs(s["anzianita_nota"], False,
                          "anzianita' = %r e' stata dichiarata NOTA: non lo e'" % booleano)

    def test_la_scheda_dice_la_VERITA_su_promozione_e_anzianita(self):
        """⛔ CINQUE PUNTI IN UNO: i campi che l'host legge non erano sorvegliati.

        `stato_scaglione` non restituisce solo un numero: restituisce anche **cosa dichiara
        di sapere** -- se la promozione e' attiva e se l'anzianita' e' nota. Sono i campi da
        cui un pannello decide cosa scrivere all'host. Il Giudice li ha rovesciati uno per
        uno (cinque mutanti su cinque righe diverse: `promo_attiva` vero al posto di falso e
        viceversa, `anzianita_nota` vero al posto di falso e viceversa) e **nessun test se
        n'e' accorto**: guardavamo il numero e mai la dichiarazione che gli sta accanto.

        💡 Un numero giusto con una dichiarazione falsa e' comunque una bugia: l'host legge
        «promozione attiva» quando non lo e', oppure «anzianita' nota» quando il sistema non
        sa da quanto e' iscritto -- e su quella riga decide se fidarsi.
        """
        from fase98_policy_commissione import LANCIO_BPS_REGIME, stato_scaglione

        # ① promozione SPENTA: si dichiara spenta, e l'anzianita' resta nota se lo e'
        spenta = stato_scaglione(10, promo_attiva=False)
        self.assertIs(spenta["promo_attiva"], False,
                      "la promozione e' spenta ma la scheda dichiara che e' attiva")
        self.assertEqual(spenta["bps"], LANCIO_BPS_REGIME)
        self.assertIs(spenta["anzianita_nota"], True,
                      "l'anzianita' era un numero valido: dichiararla ignota e' falso")

        # ② promozione ACCESA ma anzianita' IGNOTA: si dichiara accesa e l'anzianita' ignota
        ignota = stato_scaglione("non un numero")
        self.assertIs(ignota["promo_attiva"], True,
                      "la promozione e' accesa ma la scheda dichiara che e' spenta")
        self.assertIs(ignota["anzianita_nota"], False,
                      "l'anzianita' NON e' nota ma la scheda dichiara di saperla: e' la "
                      "dichiarazione piu' pericolosa, perche' fa sembrare misurato un "
                      "valore che e' stato messo di ripiego")
        self.assertIsNone(ignota["giorni_anzianita"],
                          "se l'anzianita' e' ignota non si inventa un numero di giorni")
        self.assertEqual(ignota["bps"], LANCIO_BPS_REGIME,
                         "anzianita' ignota -> regime: non si regala lo 0% per errore")

        # ③ il caso normale: promozione accesa e anzianita' nota, tutt'e due dichiarate
        normale = stato_scaglione(10)
        self.assertIs(normale["promo_attiva"], True,
                      "promozione accesa dichiarata spenta nel percorso normale")
        self.assertIs(normale["anzianita_nota"], True,
                      "anzianita' nota dichiarata ignota nel percorso normale")
        self.assertEqual(normale["giorni_anzianita"], 10,
                         "l'anzianita' dichiarata non e' quella ricevuta")


if __name__ == "__main__":
    unittest.main()
