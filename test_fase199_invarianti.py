"""GUARDIA + PROVA FORMALE — motore degli invarianti (fase199).

- Test diretti (vista ROSSA): ogni invariante rileva la violazione nota e lascia passare lo stato valido.
- PROVA property-based (Hypothesis): migliaia di stati generati a caso; un ORACOLO INDIPENDENTE
  (ricalcolo O(n²) scritto separatamente) deve concordare con l'invariante → dimostrazione empirica
  che il checker è corretto su tutto lo spazio degli stati piccoli.
- Guardia pre-commit: un'operazione che violerebbe un invariante viene BLOCCATA (eccezione) prima del DB.
"""
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from fase199_invarianti import (STATI_OCCUPANTI, ViolazioneInvariante, guardia_prenotazione,
                                i1_doppia_conferma, i2_bilancio_pagamenti, i3_prova_prima_del_commit,
                                i4_denaro_non_negativo, i5_escrow_coerente, verifica_stato)

OCC = list(STATI_OCCUPANTI)


def _p(rif, unita, ci, co, stato="pagato", **kw):
    d = {"rif": rif, "unita": unita, "check_in": ci, "check_out": co, "stato": stato,
         "prova_firmata": True, "totale_dovuto_cents": 0, "pagamenti_cents": []}
    d.update(kw)
    return d


class TestInvariantiDiretti(unittest.TestCase):
    def test_i1_sovrapposti_rilevati(self):
        v = i1_doppia_conferma([_p(1, "A", 0, 5), _p(2, "A", 3, 8)])
        self.assertEqual(len(v), 1, "doppia conferma sovrapposta NON rilevata")

    def test_i1_confini_che_si_toccano_ok(self):
        self.assertEqual(i1_doppia_conferma([_p(1, "A", 0, 5), _p(2, "A", 5, 9)]), [])

    def test_i1_unita_diverse_ok(self):
        self.assertEqual(i1_doppia_conferma([_p(1, "A", 0, 5), _p(2, "B", 0, 5)]), [])

    def test_i1_annullata_non_occupa(self):
        self.assertEqual(i1_doppia_conferma([_p(1, "A", 0, 5), _p(2, "A", 0, 5, stato="cancellata")]), [])

    def test_i2_overpay_rilevato(self):
        v = i2_bilancio_pagamenti([_p(1, "A", 0, 2, totale_dovuto_cents=1000, pagamenti_cents=[600, 600])])
        self.assertTrue(v)

    def test_i2_negativo_rilevato(self):
        self.assertTrue(i2_bilancio_pagamenti([_p(1, "A", 0, 2, totale_dovuto_cents=1000,
                                                  pagamenti_cents=[-100])]))

    def test_i2_saldato_esatto_ok(self):
        self.assertEqual(i2_bilancio_pagamenti([_p(1, "A", 0, 2, stato="pagato",
                                                  totale_dovuto_cents=1000, pagamenti_cents=[400, 600])]), [])

    def test_i2_saldato_ma_incompleto_rilevato(self):
        self.assertTrue(i2_bilancio_pagamenti([_p(1, "A", 0, 2, stato="pagato",
                                                  totale_dovuto_cents=1000, pagamenti_cents=[400])]))

    def test_i3_conferma_senza_prova_rilevata(self):
        self.assertEqual(i3_prova_prima_del_commit([_p(1, "A", 0, 2, prova_firmata=False)]), [1])

    def test_i3_tentativo_senza_prova_ok(self):
        self.assertEqual(i3_prova_prima_del_commit([_p(1, "A", 0, 2, stato="in_attesa",
                                                      prova_firmata=False)]), [])

    def test_i4_negativo(self):
        self.assertTrue(i4_denaro_non_negativo({"payout": -1, "incasso": 10}))
        self.assertEqual(i4_denaro_non_negativo({"payout": 0, "incasso": 10}), [])

    def test_i5_escrow_incoerente(self):
        self.assertTrue(i5_escrow_coerente([{"rif": 1, "stato_garanzia": "rilasciato",
                                             "esito_prenotazione": "in_attesa"}]))
        self.assertEqual(i5_escrow_coerente([{"rif": 1, "stato_garanzia": "rilasciato",
                                             "esito_prenotazione": "checkout"}]), [])


class TestGuardiaPreCommit(unittest.TestCase):
    def test_blocca_doppia_conferma(self):
        esistenti = [_p(1, "A", 0, 5)]
        with self.assertRaises(ViolazioneInvariante) as cm:
            guardia_prenotazione(_p(2, "A", 3, 8), esistenti)
        self.assertEqual(cm.exception.codice, "I1_DOPPIA_CONFERMA")

    def test_blocca_overpay(self):
        with self.assertRaises(ViolazioneInvariante):
            guardia_prenotazione(_p(2, "A", 0, 2, totale_dovuto_cents=1000,
                                    pagamenti_cents=[2000]), [])

    def test_blocca_conferma_senza_prova(self):
        with self.assertRaises(ViolazioneInvariante):
            guardia_prenotazione(_p(2, "A", 0, 2, prova_firmata=False), [])

    def test_passa_operazione_valida(self):
        guardia_prenotazione(_p(2, "B", 0, 2, totale_dovuto_cents=1000, pagamenti_cents=[1000]),
                             [_p(1, "A", 0, 5)])          # nessuna eccezione = OK

    def test_verifica_stato_pulito(self):
        self.assertEqual(verifica_stato([_p(1, "A", 0, 5)], importi={"x": 10}), {})


# ── PROVA FORMALE (property-based): I1 corretto su tutto lo spazio degli stati ───────
@st.composite
def _prenotazione(draw):
    ci = draw(st.integers(min_value=0, max_value=15))
    dur = draw(st.integers(min_value=1, max_value=8))
    return {"unita": draw(st.sampled_from(["A", "B", "C"])),
            "check_in": ci, "check_out": ci + dur,
            "stato": draw(st.sampled_from(OCC + ["cancellata", "scaduta", "in_attesa", "rifiutata"]))}


class TestProvaFormale(unittest.TestCase):
    @settings(max_examples=800)
    @given(st.lists(_prenotazione(), max_size=12))
    def test_i1_concorda_con_oracolo_indipendente(self, prens):
        for i, p in enumerate(prens):
            p["rif"] = i
        ottenuto = {frozenset((a, b)) for (_u, a, b) in i1_doppia_conferma(prens)}
        # ORACOLO INDIPENDENTE: doppio ciclo, definizione diretta di overlap semiaperto
        conf = [p for p in prens if p["stato"] in STATI_OCCUPANTI]
        atteso = set()
        for x in conf:
            for y in conf:
                if (x["rif"] < y["rif"] and x["unita"] == y["unita"]
                        and x["check_in"] < y["check_out"] and y["check_in"] < x["check_out"]):
                    atteso.add(frozenset((x["rif"], y["rif"])))
        self.assertEqual(ottenuto, atteso,
                         "I1 diverge dall'oracolo su %r" % (prens,))

    @settings(max_examples=500)
    @given(st.integers(0, 5000), st.lists(st.integers(0, 5000), max_size=6))
    def test_i2_mai_falso_positivo_su_bilanciato(self, dovuto, pagamenti):
        # se la somma NON supera il dovuto e non è saldato, e non ci sono negativi -> nessuna violazione
        p = {"rif": 1, "stato": "in_attesa", "totale_dovuto_cents": dovuto,
             "pagamenti_cents": pagamenti}
        viol = i2_bilancio_pagamenti([p])
        if sum(pagamenti) <= dovuto:
            self.assertEqual(viol, [], "I2 falso positivo su pagamento non-overpay")
        else:
            self.assertTrue(viol, "I2 non ha visto un overpay")


class TestAuditorDB(unittest.TestCase):
    """L'auditor `scansiona_db` legge i DB reali (schema-tollerante) e conta le violazioni."""

    def test_scan_pulito_e_doppia_conferma(self):
        import os
        import shutil
        import sqlite3
        import tempfile
        from fase199_invarianti import scansiona_db
        d = tempfile.mkdtemp()
        try:
            con = sqlite3.connect(os.path.join(d, "pren.db"))
            con.execute("CREATE TABLE pren(alloggio_id TEXT, check_in TEXT, check_out TEXT, stato TEXT)")
            con.execute("INSERT INTO pren VALUES ('A','2026-09-01','2026-09-05','pagato')")
            con.commit()
            r1 = scansiona_db(d)
            self.assertEqual(r1["violazioni"], {}, "scan pulito non deve avere violazioni")
            self.assertGreaterEqual(r1["prenotazioni_lette"], 1)
            # aggiungo una prenotazione SOVRAPPOSTA e confermata sulla stessa unità
            con.execute("INSERT INTO pren VALUES ('A','2026-09-03','2026-09-08','confermata')")
            con.commit()
            con.close()
            r2 = scansiona_db(d)
            self.assertIn("I1_DOPPIA_CONFERMA", r2["violazioni"], "doppia conferma non rilevata dall'auditor")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_scan_dir_inesistente_non_solleva(self):
        from fase199_invarianti import scansiona_db
        self.assertEqual(scansiona_db("/dir/che/non/esiste/xyz")["violazioni"], {})


class TestRottaBunkerInvarianti(unittest.TestCase):
    def test_rotta_registrata_e_gated(self):
        import json
        import shutil
        import tempfile
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase83_server import crea_router
        d = tempfile.mkdtemp()
        try:
            sis = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"k" * 32,
                                             db_payout=d + "/p.db"))
            r = crea_router(sis, host_key="hk", admin_key="ak", base_url="http://t")
            st, out = r.gestisci("GET", "/api/bunker/invarianti", {}, None, {})
            # la rotta ESISTE (non 404 rotta_non_trovata) ed è protetta dal bunker
            self.assertNotEqual((st, out.get("errore") if isinstance(out, dict) else None),
                                (404, "rotta_non_trovata"), "rotta /api/bunker/invarianti non registrata")
            self.assertIn(st, (403, 401), "endpoint invarianti deve essere bunker-gated")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestDimostrazioneZ3(unittest.TestCase):
    """Prova UNIVERSALE (Z3/SMT): non un campione, ma TUTTI gli infiniti interi. UNSAT = teorema."""

    def test_invarianti_critici_dimostrati(self):
        try:
            import z3  # noqa: F401
        except Exception:
            self.skipTest("z3 non installato in questo ambiente (gira dove z3-solver è presente)")
        from fase199_invarianti import dimostra_formalmente
        ris = dimostra_formalmente()
        for inv in ("I1_zero_double_booking", "I2_atomicita_finanziaria", "I3_isolamento_pii"):
            self.assertEqual(ris.get(inv), "DIMOSTRATO",
                             "%s NON dimostrato: %r" % (inv, ris.get(inv)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
