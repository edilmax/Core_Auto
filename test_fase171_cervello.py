"""Test Fase 171 - CERVELLO SEO/AEO Fact-Ledger. Batteria-sandbox: determinismo,
limiti, partizione ESATTA gap<->punteggio, monotonia white-hat, anti-stuffing,
query oneste (mai teste, mai fatti assenti), fairness di posizione, anti-spoof,
niente float, cold-start, bombardamento seedato. Funzione PURA: zero rete."""
import json
import random
import unittest

from fase57_vetrina import SERVIZI
from fase171_cervello_seo import (AMENITA_ALTA, AMENITA_COMMODITY, _AMENITA_TUTTE,
                                  _MARKUP_ELIGIBLE, distanza_metri, valuta_annuncio)

LAT, LON = 41_900_000, 12_500_000            # Roma-ish, microgradi


def _scheda_piena():
    return {
        "citta": "Roma", "paese": "IT", "titolo": "Casa vista Colosseo",
        "prezzo_notte_cents": 12000, "valuta": "EUR",
        "capacita": 4, "camere": 2, "bagni": 1,
        "servizi": tuple(_AMENITA_TUTTE),
        "politica_cancellazione": "flessibile", "modalita_prenotazione": "immediata",
        "sconto_settimana_bps": 1000, "sconto_mese_bps": 0,
        "foto": 8, "lat_micro": LAT, "lon_micro": LON, "pin_manuale": False,
        "descrizione": ("Appartamento luminoso nel cuore di Trastevere, a due passi "
                        "dal fiume: colazione sul balcone, cucina completa, wifi "
                        "veloce e check-in autonomo a qualsiasi ora. La zona e' "
                        "piena di trattorie storiche e botteghe artigiane; la "
                        "fermata del tram e' sotto casa e il centro si raggiunge "
                        "a piedi in un quarto d'ora senza traffico."),
    }


def _ctx_pieno():
    return {
        "quartiere": "Trastevere",
        "poi": [
            {"nome": "Colosseo", "cat": "attraction", "lat_micro": LAT + 5000,
             "lon_micro": LON + 5000},
            {"nome": "Stazione Trastevere", "cat": "station",
             "lat_micro": LAT - 4000, "lon_micro": LON - 3000},
            {"nome": "Villa Sciarra", "cat": "park", "lat_micro": LAT + 2000,
             "lon_micro": LON - 6000},
        ],
        "comune_tassa": {"per_persona_notte_cents": 350, "max_notti": 10},
        "reviews": {"n": 5, "media_centesimi": 470},
        "geocode_micro": (LAT, LON),
    }


MARKUP_TUTTO = tuple(sorted(_MARKUP_ELIGIBLE))


def _no_float(x, path="root"):
    if isinstance(x, bool):
        return
    if isinstance(x, float):
        raise AssertionError("float in output: %s = %r" % (path, x))
    if isinstance(x, dict):
        for k, v in x.items():
            _no_float(v, path + "." + str(k))
    elif isinstance(x, (list, tuple)):
        for i, v in enumerate(x):
            _no_float(v, path + "[%d]" % i)


def _dump(r):
    return json.dumps(r, sort_keys=True, ensure_ascii=False, default=repr)


class TestClassificazione(unittest.TestCase):
    def test_tutti_i_codici_fase57_classificati(self):
        self.assertEqual(set(SERVIZI), set(_AMENITA_TUTTE))
        self.assertEqual(set(AMENITA_ALTA) & set(AMENITA_COMMODITY), set())


class TestDeterminismo(unittest.TestCase):
    def test_stesso_input_stesso_output(self):
        a = valuta_annuncio(_scheda_piena(), _ctx_pieno(), None, MARKUP_TUTTO)
        b = valuta_annuncio(_scheda_piena(), _ctx_pieno(), None, MARKUP_TUTTO)
        self.assertEqual(_dump(a), _dump(b))

    def test_permutazioni_ininfluenti(self):
        s1, s2 = _scheda_piena(), _scheda_piena()
        s2["servizi"] = tuple(reversed(s2["servizi"]))
        c1, c2 = _ctx_pieno(), _ctx_pieno()
        c2["poi"] = list(reversed(c2["poi"]))
        self.assertEqual(_dump(valuta_annuncio(s1, c1, None, MARKUP_TUTTO)),
                         _dump(valuta_annuncio(s2, c2, None, MARKUP_TUTTO)))


class TestLimitiEPienezza(unittest.TestCase):
    def test_scheda_piena_fa_esattamente_100(self):
        r = valuta_annuncio(_scheda_piena(), _ctx_pieno(), None, MARKUP_TUTTO)
        self.assertEqual(r["punteggio_milli"], 100_000, r["gap"][:4])
        self.assertEqual(r["punteggio"], 100)
        scored = [g for g in r["gap"] if g["punti_persi_milli"] > 0]
        self.assertEqual(scored, [])

    def test_scheda_vuota_non_solleva(self):
        r = valuta_annuncio({}, {}, None, ())
        self.assertTrue(0 <= r["punteggio"] <= 100)
        self.assertLessEqual(r["punteggio"], 35, "scheda vuota deve stare in basso")

    def test_input_spazzatura_blindato(self):
        for rotto in (None, "x", 42, [1], {"prezzo_notte_cents": "molto"},
                      {"servizi": 99, "foto": "tre", "lat_micro": 1.5}):
            r = valuta_annuncio(rotto if isinstance(rotto, dict) else rotto,
                                {"poi": "niente"}, {"n_citta": "boh"}, None)
            self.assertTrue(0 <= r["punteggio"] <= 100)

    def test_fairness_posizione_zona_senza_poi(self):
        # niente POI/quartiere/tassa nel ctx: la scheda completa fa COMUNQUE 100
        r = valuta_annuncio(_scheda_piena(), {"reviews": {"n": 3}}, None, MARKUP_TUTTO)
        self.assertEqual(r["punteggio"], 100, r["gap"][:4])


class TestPartizioneEsatta(unittest.TestCase):
    def _controlla(self, scheda, ctx, markup):
        r = valuta_annuncio(scheda, ctx, None, markup)
        somma = sum(g["punti_persi_milli"] for g in r["gap"])
        self.assertEqual(somma, 100_000 - r["punteggio_milli"],
                         "partizione rotta: %d vs %d" % (somma,
                                                         100_000 - r["punteggio_milli"]))

    def test_su_fixture_diverse(self):
        self._controlla({}, {}, ())
        self._controlla(_scheda_piena(), _ctx_pieno(), ())
        s = _scheda_piena()
        s["servizi"] = ("wifi", "piscina")
        s["foto"] = 2
        del s["descrizione"]
        self._controlla(s, _ctx_pieno(), ("prezzo_notte", "coordinate"))


class TestMonotoniaWhiteHat(unittest.TestCase):
    def setUp(self):
        self.s = _scheda_piena()
        self.s["servizi"] = ("wifi",)
        self.s["foto"] = 2
        self.ctx = _ctx_pieno()
        self.base = valuta_annuncio(self.s, self.ctx, None, ())["punteggio_milli"]

    def _sale(self, **mod):
        s2 = dict(self.s)
        s2.update(mod)
        dopo = valuta_annuncio(s2, self.ctx, None, ())["punteggio_milli"]
        self.assertGreaterEqual(dopo, self.base, mod)

    def test_aggiunte_vere_non_abbassano_mai(self):
        self._sale(servizi=("wifi", "piscina"))
        self._sale(foto=8)
        self._sale(sconto_mese_bps=500)
        s2 = dict(self.s)
        dopo = valuta_annuncio(s2, self.ctx, None,
                               ("prezzo_notte",))["punteggio_milli"]
        self.assertGreaterEqual(dopo, self.base, "emettere markup non puo' abbassare")

    def test_togliere_non_alza(self):
        s2 = dict(self.s)
        s2["servizi"] = ()
        dopo = valuta_annuncio(s2, self.ctx, None, ())["punteggio_milli"]
        self.assertLessEqual(dopo, self.base)

    def test_coordinate_sbloccano_mai_penalizzano(self):
        senza = dict(self.s)
        senza["lat_micro"] = None
        senza["lon_micro"] = None
        prima = valuta_annuncio(senza, self.ctx, None, ())["punteggio_milli"]
        self.assertGreaterEqual(self.base, prima)


class TestAntiStuffing(unittest.TestCase):
    def test_amenita_nel_testo_senza_codice_vale_zero(self):
        s = _scheda_piena()
        s["servizi"] = ()
        s["descrizione"] = ("piscina " * 60) + s["descrizione"]
        r = valuta_annuncio(s, _ctx_pieno(), None, ())
        f = {x["slot"]: x for x in r["fatti"]}["amenita:piscina"]
        self.assertEqual(f["cit"], 0)
        for q in r["query"]:
            self.assertNotIn("piscina", q["testo"], "query da testo senza codice")

    def test_descrizione_ripetuta_non_paga(self):
        s = _scheda_piena()
        r1 = valuta_annuncio(s, _ctx_pieno(), None, ())["punteggio_milli"]
        s2 = dict(s)
        s2["descrizione"] = s["descrizione"] * 10
        r2 = valuta_annuncio(s2, _ctx_pieno(), None, ())["punteggio_milli"]
        self.assertEqual(r1, r2)


class TestQueryOneste(unittest.TestCase):
    def test_mai_fatti_assenti_e_mai_teste(self):
        for scheda, ctx in ((_scheda_piena(), _ctx_pieno()),
                            ({"citta": "Roma", "capacita": 2, "camere": 1,
                              "prezzo_notte_cents": 8000}, {})):
            r = valuta_annuncio(scheda, ctx, None, ())
            pres = {f["slot"]: f["presenza"] for f in r["fatti"]}
            for q in r["query"]:
                self.assertGreaterEqual(q["k"], 2, q)
                for slot in q["fatti"]:
                    self.assertGreaterEqual(pres.get(slot, 0), 1000,
                                            "query su fatto assente: %r" % q)
                self.assertTrue(0 <= q["vincibilita"] <= 100)

    def test_senza_coordinate_niente_query_geo(self):
        s = _scheda_piena()
        s["lat_micro"] = None
        s["lon_micro"] = None
        r = valuta_annuncio(s, _ctx_pieno(), None, ())
        for q in r["query"]:
            self.assertFalse(any(sl.startswith("poi:")
                                 or sl in ("coordinate", "quartiere")
                                 for sl in q["fatti"]), q)
        # anche il FATTO quartiere non esiste senza coordinate (deriva dal pin)
        self.assertNotIn("quartiere", {f["slot"] for f in r["fatti"]})

    def test_citazioni_pronte_sottoinsieme(self):
        r = valuta_annuncio(_scheda_piena(), _ctx_pieno(), None, MARKUP_TUTTO)
        self.assertTrue(all(q["vincibilita"] >= 60 for q in r["citazioni_pronte"]))


class TestAntiSpoof(unittest.TestCase):
    def test_pin_lontano_dal_geocode_costa(self):
        s = _scheda_piena()
        s["pin_manuale"] = True
        ctx = _ctx_pieno()
        onesto = valuta_annuncio(s, ctx, None, ())["punteggio_milli"]
        ctx2 = _ctx_pieno()
        ctx2["geocode_micro"] = (LAT + 500_000, LON)      # ~55 km piu' in la'
        r2 = valuta_annuncio(s, ctx2, None, ())
        self.assertLess(r2["punteggio_milli"], onesto)
        self.assertTrue(any("conferma l'indirizzo" in g["azione"] for g in r2["gap"]))
        for q in r2["query"]:
            self.assertFalse(any(sl.startswith("poi:") for sl in q["fatti"]))


class TestGapCoerenza(unittest.TestCase):
    def test_chiudere_un_gap_rende_il_delta_promesso(self):
        s = _scheda_piena()
        markup = tuple(sorted(_MARKUP_ELIGIBLE - {"amenita:piscina"}))
        r = valuta_annuncio(s, _ctx_pieno(), None, markup)
        g = next(x for x in r["gap"] if x["slot"] == "amenita:piscina")
        self.assertEqual(g["tipo"], "sistema")
        dopo = valuta_annuncio(s, _ctx_pieno(), None, MARKUP_TUTTO)["punteggio_milli"]
        delta = dopo - r["punteggio_milli"]
        self.assertLessEqual(abs(delta - g["punti_persi_milli"]), 10,
                             "promesso %d, reso %d" % (g["punti_persi_milli"], delta))

    def test_gap_amenita_assente_condizionale(self):
        s = _scheda_piena()
        s["servizi"] = ("wifi",)
        r = valuta_annuncio(s, _ctx_pieno(), None, ())
        g = next(x for x in r["gap"] if x["slot"] == "amenita:piscina")
        self.assertTrue(g["condizionale"])
        self.assertIn("SE", g["azione"])


class TestNoFloatEColdStart(unittest.TestCase):
    def test_nessun_float_nell_output(self):
        # `_no_float` SOLLEVA se trova un numero a virgola mobile: il controllo c'era
        # ma non si vedeva, e un test che sembra muto prima o poi viene "semplificato".
        uscita = valuta_annuncio(_scheda_piena(), _ctx_pieno(),
                                 {"n_citta": 20, "hanno": {"wifi": 18}}, MARKUP_TUTTO)
        _no_float(uscita)
        self.assertIsInstance(uscita, dict)
        with self.assertRaises(AssertionError,
                               msg="il criterio non riconosce piu' un float"):
            _no_float({"prezzo": 1.5})

    def test_coorte_cieca_usa_prior(self):
        a = valuta_annuncio(_scheda_piena(), _ctx_pieno(), None, ())
        b = valuta_annuncio(_scheda_piena(), _ctx_pieno(), {"n_citta": 3}, ())
        self.assertEqual(_dump(a), _dump(b))

    def test_coorte_vera_cambia_la_distintivita(self):
        rara = valuta_annuncio(_scheda_piena(), _ctx_pieno(),
                               {"n_citta": 20, "hanno": {"piscina": 1}}, ())
        comune = valuta_annuncio(_scheda_piena(), _ctx_pieno(),
                                 {"n_citta": 20, "hanno": {"piscina": 20}}, ())
        vq = {q["testo"]: q["vincibilita"] for q in rara["query"]}
        for q in comune["query"]:
            if "piscina" in q["testo"] and q["testo"] in vq:
                self.assertGreaterEqual(vq[q["testo"]], q["vincibilita"])


class TestDistanza(unittest.TestCase):
    def test_metri_interi_simmetrici(self):
        d1 = distanza_metri(LAT, LON, LAT + 9000, LON)     # ~1km a nord
        self.assertTrue(950 <= d1 <= 1050, d1)
        self.assertEqual(d1, distanza_metri(LAT + 9000, LON, LAT, LON))
        self.assertEqual(distanza_metri(LAT, LON, LAT, LON), 0)


class TestBombardamentoSeedato(unittest.TestCase):
    """Mini '10.000 menti' del cervello: schede casuali-ma-plausibili, invarianti su tutte."""

    def test_invarianti_su_600_schede(self):
        citta = ("Roma", "Porto", "Bangkok", "X")
        for seme in range(10):
            rnd = random.Random(1000 + seme)
            for _ in range(60):
                s = {"citta": rnd.choice(citta)}
                if rnd.random() < 0.9:
                    s["prezzo_notte_cents"] = rnd.choice((0, 5000, 12000, 99900))
                s["capacita"] = rnd.choice((0, 1, 2, 4, 8))
                s["camere"] = rnd.choice((0, 1, 2, 4))
                s["bagni"] = rnd.choice((0, 1, 2))
                s["servizi"] = tuple(rnd.sample(_AMENITA_TUTTE,
                                                rnd.randrange(0, 13)))
                s["foto"] = rnd.randrange(0, 11)
                if rnd.random() < 0.7:
                    s["lat_micro"], s["lon_micro"] = LAT, LON
                    s["pin_manuale"] = rnd.random() < 0.3
                s["politica_cancellazione"] = rnd.choice(
                    ("flessibile", "rigida", "boh", ""))
                s["modalita_prenotazione"] = rnd.choice(("immediata", "su_richiesta"))
                if rnd.random() < 0.6:
                    s["descrizione"] = "Trastevere e' vicino. " * rnd.randrange(0, 30)
                ctx = {}
                if rnd.random() < 0.6:
                    ctx = _ctx_pieno()
                    if rnd.random() < 0.3:
                        ctx["geocode_micro"] = (LAT + 400_000, LON)
                coorte = rnd.choice((None, {"n_citta": 2},
                                     {"n_citta": 15, "hanno": {"wifi": 12,
                                                               "piscina": 2}}))
                markup = tuple(rnd.sample(sorted(_MARKUP_ELIGIBLE),
                                          rnd.randrange(0, 8)))
                r = valuta_annuncio(s, ctx, coorte, markup)
                self.assertTrue(0 <= r["punteggio"] <= 100)
                self.assertNotIn("errore", r, "degradata su input plausibile")
                somma = sum(g["punti_persi_milli"] for g in r["gap"])
                self.assertEqual(somma, 100_000 - r["punteggio_milli"])
                pres = {f["slot"]: f["presenza"] for f in r["fatti"]}
                for q in r["query"]:
                    self.assertGreaterEqual(q["k"], 2)
                    for slot in q["fatti"]:
                        self.assertGreaterEqual(pres.get(slot, 0), 1000)
                _no_float(r)
                self.assertEqual(_dump(r), _dump(valuta_annuncio(s, ctx, coorte,
                                                                 markup)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
