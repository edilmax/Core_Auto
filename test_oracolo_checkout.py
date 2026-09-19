"""IL SECONDO CONTO SUL PREVENTIVO DEL CHECKOUT — e la prova che sa GRIDARE (Tappa 1).

Il fratello maggiore `test_quote_coerenza.py` chiede alla risposta: «sei coerente con te
stessa?». Qui si chiede di piu': «sei IL NUMERO GIUSTO, ricalcolato da zero da qualcun
altro?». `collaudi/oracolo_checkout.py` e' quel qualcuno: rampa di lancio, tassa di soggiorno,
sconti di soggiorno e costo carta riscritti a mano e confrontati col motore VERO, sulla
griglia 9 annunci x 8 notti x 3 party x 2 fonti.

⛔ QUATTRO DOMANDE, NON UNA (come l'oracolo del payout):
  1. sulla griglia il secondo conto coincide col motore, senza eccezioni;
  2. le PROPRIETA' del modello 0% ospite reggono dove si vedono (fonte, rampa, valuta);
  3. l'oracolo GRIDA con il guasto dentro (le due direzioni, regola 10);
  4. il TESTIMONE: le costanti scritte a mano non si sono allontanate da fase98.
"""
import datetime
import json
import shutil
import tempfile
import unittest

from collaudi import oracolo_checkout as O


class TestIDueContiCoincidono(unittest.TestCase):
    """Il giro completo della griglia: ogni cent del preventivo ricalcolato da zero."""

    def test_griglia_zero_differenze(self):
        provate, differenze, eccezioni = O.confronta()
        self.assertGreater(provate, 300,
                           "griglia troppo corta: %d combinazioni" % provate)
        self.assertEqual([], differenze[:5], "il secondo conto e il motore divergono")
        self.assertEqual([], eccezioni[:5], "il contratto dice: MAI un'eccezione")


class TestLeProprietaDelModelloZeroOspite(unittest.TestCase):
    """Dove l'ospite non deve ACCORGERSI di cio' che cambia dietro: fonte, rampa, valuta."""

    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp(prefix="oracolo_checkout_proprieta_")
        cls.r, cls.oggi, cls.per_slug = O.banco(cls.d)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def _quote(self, slug, notti=2, party=1, fonte="marketplace"):
        ci = self.oggi + datetime.timedelta(days=10)
        co = ci + datetime.timedelta(days=notti)
        s, c = self.r.gestisci("POST", "/api/concierge/quote", {},
                               json.dumps({"alloggio_id": slug,
                                           "check_in": ci.isoformat(),
                                           "check_out": co.isoformat(),
                                           "party": party, "fonte": fonte}))
        self.assertEqual(200, s, c)
        return c

    def test_la_fonte_diretta_non_cambia_il_totale_all_ospite(self):
        """5% o 10% lo decide l'HOST, non l'ospite: stesso totale, commissione diversa."""
        mk = self._quote("oracolo-vecchio-base", fonte="marketplace")
        di = self._quote("oracolo-vecchio-base", fonte="diretto")
        self.assertEqual(mk["totale_cents"], di["totale_cents"])
        self.assertEqual(mk["prezzo_guest_cents"], di["prezzo_guest_cents"])
        self.assertGreater(di["commissione_cents"], 0)
        self.assertNotEqual(mk["commissione_cents"], di["commissione_cents"])

    def test_la_rampa_di_lancio_non_cambia_il_totale_all_ospite(self):
        """Host dei primi 90 giorni o a regime: l'ospite paga uguale, cambia il netto host."""
        giovane = self._quote("oracolo-giovane-base")
        vecchio = self._quote("oracolo-vecchio-base")
        self.assertEqual(giovane["totale_cents"], vecchio["totale_cents"])
        self.assertEqual(0, giovane["commissione_cents"])       # rampa: 0% <90gg
        self.assertGreater(vecchio["commissione_cents"], 0)     # regime: 10%

    def test_la_valuta_estera_non_cambia_il_totale_all_ospite(self):
        """Il 7% contro il 5% e' un costo del GATEWAY, non dell'ospite: paga lo stesso
        prezzo (nella valuta dell'annuncio); cambia solo quanto l'host cede alla carta."""
        eur = self._quote("oracolo-medio-base")
        usd = self._quote("oracolo-medio-estera")
        self.assertEqual(eur["totale_cents"], usd["totale_cents"])
        self.assertEqual("USD", usd["valuta"])
        self.assertGreater(usd["costo_pagamento_cents"], eur["costo_pagamento_cents"])

    def test_il_costo_carta_non_tocca_mai_il_totale(self):
        """A parita' di tutto, un annuncio con carta piu' cara non costa un cent in piu'
        all'ospite: la differenza esce tutta dal netto host (modello 0% ospite)."""
        eur = self._quote("oracolo-medio-base")
        usd = self._quote("oracolo-medio-estera")
        differenza_carta = usd["costo_pagamento_cents"] - eur["costo_pagamento_cents"]
        differenza_host = eur["netto_host_cents"] - usd["netto_host_cents"]
        self.assertEqual(differenza_carta, differenza_host)


class TestLOracoloSaGridare(unittest.TestCase):
    """⛔ LA PROVA CHE VALE PIU' DEL VERDE: col guasto dentro, il secondo conto dice NO."""

    def test_grida_se_la_tassa_viene_dimenticata(self):
        """Il guasto piu' probabile: il secondo conto smette di contare la tassa."""
        _, differenze, _ = O.confronta(guasto=lambda s: s.update(tassa_pp=0, tassa_perc=0))
        self.assertTrue(differenze, "l'oracolo NON si e' accorto della tassa persa")

    def test_grida_se_la_rampa_viene_ignorata(self):
        """Il secondo conto tratta tutti gli host come se fossero a regime."""
        _, differenze, _ = O.confronta(guasto=lambda s: s.update(giorni_host=10 ** 9))
        self.assertTrue(differenze, "l'oracolo NON si e' accorto della rampa ignorata")

    def test_grida_se_la_valuta_estera_viene_trattata_come_euro(self):
        """Il secondo conto usa il 5% anche sull'annuncio in dollari."""
        _, differenze, _ = O.confronta(guasto=lambda s: s.update(valuta="EUR"))
        self.assertTrue(differenze, "l'oracolo NON vede la tariffa estera ignorata")

    def test_grida_su_un_cent_solo(self):
        """Un cent. Se non lo vede, non serve a niente: gli errori sui soldi partono li'."""
        def un_cent_in_meno(attesi):
            attesi["totale_cents"] = attesi["totale_cents"] - 1
        _, differenze, _ = O.confronta(guasto_attesi=un_cent_in_meno)
        self.assertTrue(differenze, "l'oracolo NON vede una differenza di UN cent")


class TestIlTestimoneNonSiEAllontanato(unittest.TestCase):
    """Le costanti del secondo conto sono scritte A MANO: se produzione le cambia, il
    testimone diventa rosso INVECE di seguire il cambiamento in silenzio."""

    def test_le_costanti_della_rampa_coincidono_con_fase98(self):
        import fase98_policy_commissione as f98
        self.assertEqual(O.RAMPA_GIORNI_GRATIS, f98.LANCIO_GIORNI_GRATIS)
        self.assertEqual(O.RAMPA_BPS_FASE1, f98.LANCIO_BPS_FASE1)
        self.assertEqual(O.RAMPA_GIORNI_FASE1, f98.LANCIO_GIORNI_FASE1)
        self.assertEqual(O.BPS_DIRETTO, f98.BPS_DIRETTO)

    def test_la_rampa_calcola_come_fase98_sui_confini(self):
        """Il giorno prima e il giorno dopo ogni scaglione: dove gli off-by-one vivono."""
        import fase98_policy_commissione as f98
        for giorni in (0, 89, 90, 91, 364, 365, 366, 10 ** 6):
            self.assertEqual(O.rampa_bps(giorni, "marketplace"),
                             f98.commissione_bps_lancio(giorni),
                             "la rampa diverge al giorno %d" % giorni)
        self.assertEqual(O.rampa_bps(10, "diretto"), f98.commissione_bps_fonte("diretto"))

    def test_lo_sconto_non_rimborsabile_e_quello_dichiarato(self):
        """Il 12% di sconto non-rimborsabile in fase59 e' un LETTERALE nel sorgente (non
        una costante con nome): il testimone lo rilegge da li', cosi' se qualcuno lo
        cambia l'oracolo grida invece di contare col numero vecchio."""
        import os
        import re
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "fase59_concierge.py"), encoding="utf-8").read()
        m = re.search(r"sconto_nr = netto \* (\d+) // 10000", src)
        self.assertIsNotNone(m, "fase59 non calcola piu' lo sconto non-rimborsabile "
                                "con la forma 'netto * N // 10000': aggiorna il testimone")
        self.assertEqual(O.SCONTO_NR_BPS, int(m.group(1)),
                         "il secondo conto usa %d, fase59 usa %s: aggiorna chi e' rimasto "
                         "indietro CON COSCIENZA (e' un patto pubblico, non un dettaglio)"
                         % (O.SCONTO_NR_BPS, m.group(1)))


if __name__ == "__main__":
    unittest.main()
