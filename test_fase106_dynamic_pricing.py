"""Test Fase 106 - Dynamic pricing. Puro, deterministico, cents interi."""
import unittest

from fase106_dynamic_pricing import (PoliticaPrezzo, calcola_prezzo,
                                     crea_politica_prezzo)


class TestPricing(unittest.TestCase):
    def test_base_neutro(self):
        # occupazione media 50%, mese aprile (10000), feriale, anticipo normale -> base
        r = calcola_prezzo(10000, occupazione_bps=5000, data="2026-04-08",
                           giorni_all_arrivo=30)
        self.assertEqual(r["fattori"]["occupazione"], 10000)
        self.assertEqual(r["fattori"]["stagione"], 10000)
        self.assertEqual(r["fattori"]["weekend"], 10000)
        self.assertEqual(r["prezzo_cents"], 10000)

    def test_domanda_alta_aumenta(self):
        r = calcola_prezzo(10000, occupazione_bps=9000, data="2026-04-08",
                           giorni_all_arrivo=30)
        self.assertEqual(r["fattori"]["occupazione"], 13000)
        self.assertEqual(r["prezzo_cents"], 13000)              # +30%

    def test_domanda_bassa_sconta(self):
        r = calcola_prezzo(10000, occupazione_bps=2000, data="2026-04-08",
                           giorni_all_arrivo=30)
        self.assertEqual(r["prezzo_cents"], 9000)               # -10%

    def test_weekend_e_stagione_agosto(self):
        # 2026-08-08 è sabato; agosto stagione 13000; occ media
        r = calcola_prezzo(10000, occupazione_bps=5000, data="2026-08-08",
                           giorni_all_arrivo=30)
        self.assertEqual(r["fattori"]["weekend"], 11500)
        self.assertEqual(r["fattori"]["stagione"], 13000)
        # 10000 * 1.3 * 1.15 = 14950
        self.assertEqual(r["prezzo_cents"], 14950)

    def test_last_minute_sconto(self):
        r = calcola_prezzo(10000, occupazione_bps=5000, data="2026-04-08",
                           giorni_all_arrivo=1)
        self.assertEqual(r["fattori"]["anticipo"], 8500)
        self.assertEqual(r["prezzo_cents"], 8500)

    def test_anticipo_lungo_premio(self):
        r = calcola_prezzo(10000, occupazione_bps=5000, data="2026-04-08",
                           giorni_all_arrivo=90)
        self.assertEqual(r["fattori"]["anticipo"], 10500)

    def test_cap_e_floor(self):
        pol = PoliticaPrezzo(cap_bps=12000, floor_bps=9500)
        alto = calcola_prezzo(10000, occupazione_bps=9000, data="2026-08-08",
                              giorni_all_arrivo=90, pol=pol)
        self.assertEqual(alto["prezzo_cents"], 12000)          # cappato a 120%
        basso = calcola_prezzo(10000, occupazione_bps=2000, data="2026-01-08",
                               giorni_all_arrivo=1, pol=pol)
        self.assertEqual(basso["prezzo_cents"], 9500)          # floored a 95%

    def test_base_invalido(self):
        self.assertEqual(calcola_prezzo(0)["prezzo_cents"], 0)
        self.assertEqual(calcola_prezzo(-5)["prezzo_cents"], 0)

    def test_cents_interi(self):
        r = calcola_prezzo(9999, occupazione_bps=9000, data="2026-07-04",
                           giorni_all_arrivo=5)
        self.assertIsInstance(r["prezzo_cents"], int)

    def test_factory(self):
        self.assertEqual(crea_politica_prezzo(weekend_bps=12000).weekend_bps, 12000)


class TestFattoreTemporale(unittest.TestCase):
    """I due fattori temporali presi SUI confini, e per RELAZIONE invece che per cifra.

    Il fattore temporale era gia' guardato in sei posti (qui :38 e :44, piu' quattro
    in test_fase119_calendario_prezzi.py). Misurato il 2026-09-01, quelle sei
    esercitano le distanze 0 · 1 · 5 · 30 · 90 · 200: nessuna tocca i confini veri,
    che il motore mette a `g <= 2` e `g >= 60` (fase106_dynamic_pricing.py:78-85).
    Uno spostamento di un solo giorno sopravvive a tutte e sei.

    ⛔ I MOLTIPLICATORI NON SI RICOPIANO: si chiedono alla politica. Cinque delle sei
    guardie esistenti li scrivono a mano, quindi cambiarli domani manderebbe rosso un
    test che parla d'altro -- e chi lo ripara allinea la copia e non si accorge di
    niente. Una guardia che ripete la stessa convinzione del codice non la controlla.
    ⚠️ Le SOGLIE (2 e 60) invece si scrivono, ed e' voluto: sono il contratto che
    questa guardia fissa. Se qualcuno le sposta, questa classe DEVE diventare rossa."""

    # Il punto d'iniezione del guasto. La politica sta qui e non dentro i metodi
    # perche' cosi' la si sostituisce da fuori (una sottoclasse) per vedere il rosso,
    # senza toccare `fase106_dynamic_pricing.py`, che e' produzione (B4).
    POLITICA = PoliticaPrezzo()

    # Mercoledi' d'aprile: occupazione media, stagione e weekend restano tutti neutri,
    # quindi l'unico fattore che si muove fra una chiamata e l'altra e' il tempo.
    GIORNO_NEUTRO = "2026-04-08"
    BASE_CENTS = 10000
    NEUTRO_BPS = 10000  # 10000 bps = x1.0: l'unita' del sistema, non una soglia

    def _fattori(self, giorni):
        return calcola_prezzo(self.BASE_CENTS, occupazione_bps=5000,
                              data=self.GIORNO_NEUTRO, giorni_all_arrivo=giorni,
                              pol=self.POLITICA)

    def test_il_fattore_temporale_cambia_ESATTAMENTE_sui_confini(self):
        """Il confine si prova SUL confine (D4), da tutt'e due i lati.

        DENOMINATORE: 7 distanze = le 3 fasce piu' i 2 confini presi a cavallo.

        ⛔ COSA QUESTA GUARDIA NON VEDE, misurato il 2026-09-01 iniettando il guasto
        e non dedotto (D18 punto 3): NON vede due moltiplicatori azzerati. Chiede i
        valori attesi alla politica, quindi con la politica neutralizzata confronta il
        neutro col neutro e si autoconferma -- e' uscita `ok` col guasto dentro.
        Quel guasto lo vede l'altra guardia, per relazione. ⚠️ Le due NON sono
        ridondanti e nessuna delle due si toglie: questa copre il confine spostato,
        quella copre il fattore spento, e ognuna e' cieca al guasto dell'altra."""
        p = self.POLITICA
        atteso = ((0, p.last_minute_bps), (1, p.last_minute_bps), (2, p.last_minute_bps),
                  (3, self.NEUTRO_BPS), (59, self.NEUTRO_BPS),
                  (60, p.anticipo_bps), (61, p.anticipo_bps))
        for giorni, bps in atteso:
            self.assertEqual(
                bps, self._fattori(giorni)["fattori"]["anticipo"],
                "a %d giorni dall'arrivo il fattore temporale non e' quello della sua "
                "fascia: un confine si e' spostato" % giorni)

    def test_la_relazione_del_tempo_REGGE_qualunque_siano_le_cifre(self):
        """La relazione, non i numeri: attraversando un confine il prezzo salta, e
        salta nel verso giusto. Resta vera se domani i moltiplicatori cambiano --
        che e' esattamente cio' che un'asserzione sulle cifre non sa fare.

        DENOMINATORE: i 2 confini, la fascia neutra in mezzo, e il verso dei 2 fattori."""
        vicino, appena_dopo = self._fattori(2), self._fattori(3)
        quasi, lontano = self._fattori(59), self._fattori(60)
        self.assertLess(
            vicino["prezzo_cents"], appena_dopo["prezzo_cents"],
            "l'ultimo minuto non sconta piu': a 2 giorni si paga come a 3")
        self.assertLess(
            quasi["prezzo_cents"], lontano["prezzo_cents"],
            "l'anticipo non premia piu': a 60 giorni si paga come a 59")
        self.assertEqual(
            appena_dopo["prezzo_cents"], quasi["prezzo_cents"],
            "la fascia in mezzo non e' piatta: fra 3 e 59 giorni il tempo non deve pesare")
        self.assertLess(
            self.POLITICA.last_minute_bps, self.NEUTRO_BPS,
            "l'ultimo minuto deve SCONTARE: serve a riempire i buchi, e un buco non si "
            "riempie alzando il prezzo")
        self.assertLess(
            self.NEUTRO_BPS, self.POLITICA.anticipo_bps,
            "l'anticipo deve PREMIARE: chi blocca il posto con mesi di anticipo lo paga")

    def test_QUESTA_guardia_sa_diventare_rossa(self):
        """L'anti-ornamento (ferrea 2, D18 punto 2): una guardia mai vista fallire non
        e' una guardia, e le due direzioni si provano tutt'e due.

        Il guasto si inietta nella POLITICA: neutralizzare i due moltiplicatori e'
        l'osservabile esatto di un motore che ha smesso di applicarli. Cosi' non si
        tocca `fase106_dynamic_pricing.py` -- e' produzione (B4) -- e non resta niente
        da ripristinare byte per byte se la sessione muore a meta'.

        DENOMINATORE: 2 direzioni x 2 confini."""
        spenta = crea_politica_prezzo(last_minute_bps=self.NEUTRO_BPS,
                                      anticipo_bps=self.NEUTRO_BPS)

        def prezzo(giorni, pol):
            return calcola_prezzo(self.BASE_CENTS, occupazione_bps=5000,
                                  data=self.GIORNO_NEUTRO, giorni_all_arrivo=giorni,
                                  pol=pol)["prezzo_cents"]

        # col guasto dentro il salto sparisce: e' il rosso che la guardia deve saper dare
        self.assertEqual(prezzo(2, spenta), prezzo(3, spenta),
                         "il guasto non e' entrato: la prova qui sotto non dimostra niente")
        self.assertEqual(prezzo(59, spenta), prezzo(60, spenta),
                         "il guasto non e' entrato: la prova qui sotto non dimostra niente")
        # e a macchina sana il salto c'e'. Senza questa meta', le due righe sopra
        # sarebbero soddisfatte anche da un motore che non calcola piu' niente.
        self.assertNotEqual(prezzo(2, self.POLITICA), prezzo(3, self.POLITICA),
                            "a macchina sana il confine dei 2 giorni deve farsi sentire")
        self.assertNotEqual(prezzo(59, self.POLITICA), prezzo(60, self.POLITICA),
                            "a macchina sana il confine dei 60 giorni deve farsi sentire")


if __name__ == "__main__":
    unittest.main()
