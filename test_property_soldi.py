"""
PROPERTY-BASED TESTING (Hypothesis) sui MOTORI DEI SOLDI.

Invece di scegliere noi i casi, Hypothesis GENERA centinaia di input (anche cattivi/estremi) e
verifica che gli INVARIANTI reggano SEMPRE. Se trova un controesempio, lo restringe al piu'
piccolo e lo mostra. Copre: motore "paga in struttura" (fase188), rampa commissioni (fase98),
rimborso cancellazione (fase111). Zero rete, deterministico (seed fisso via profilo).
"""
import unittest

from hypothesis import given, settings, strategies as st, HealthCheck

import fase188_paga_struttura as PS
import fase98_policy_commissione as POL
import fase111_cancellazione as CANC
import fase162_pagamenti_pendenti as PEND

_S = settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _stripe_peggiore(x):
    return 25 + x * 325 // 10000


class TestMotorePagaStruttura(unittest.TestCase):
    @_S
    @given(prezzo=st.integers(min_value=0, max_value=5_000_000),
           notti=st.integers(min_value=1, max_value=90),
           comm=st.integers(min_value=0, max_value=6_000_000),
           psp=st.integers(min_value=0, max_value=1000))
    def test_invarianti_sempre(self, prezzo, notti, comm, psp):
        r = PS.calcola(prezzo, notti, comm, psp_bps=psp)
        A, S = r["anticipo_online_cents"], r["saldo_in_loco_cents"]
        # niente negativi, mai
        for k, v in r.items():
            self.assertGreaterEqual(v, 0, "%s negativo: %s" % (k, r))
        # conservazione + totale ospite = prezzo + fee
        self.assertEqual(r["ospite_paga_totale_cents"], max(0, prezzo) + r["fee_cents"])
        self.assertEqual(A + S, r["ospite_paga_totale_cents"])
        # host prende TUTTO dal saldo (no giro storto)
        self.assertEqual(r["host_incassa_cents"], S)
        # NON SI PERDE MAI: quello che incassiamo online copre il costo Stripe peggiore
        if A > 0:
            self.assertGreater(A - _stripe_peggiore(A), 0, "PERDITA su %s" % r)
        # margine PIENO quando l'anticipo non e' tosato (saldo > 0)
        if S > 0 and A > 0:
            self.assertGreaterEqual(r["gateway_cents"], _stripe_peggiore(A))

    @_S
    @given(prezzo=st.integers(min_value=1, max_value=5_000_000),
           notti=st.integers(min_value=1, max_value=60))
    def test_fee_sempre_150_per_notte(self, prezzo, notti):
        r = PS.calcola(prezzo, notti, 0)
        self.assertEqual(r["fee_cents"], 150 * notti)


class TestRampaCommissioni(unittest.TestCase):
    @_S
    @given(giorni=st.integers(min_value=-1000, max_value=100000))
    def test_scaglioni_0_8_10(self, giorni):
        bps = POL.commissione_bps_lancio(giorni)
        # sempre uno dei tre scaglioni ufficiali
        self.assertIn(bps, (0, POL.LANCIO_BPS_FASE1, POL.LANCIO_BPS_REGIME),
                      "bps fuori scaglione: %d (giorni %d)" % (bps, giorni))
        if giorni < 0:
            # FAIL-SAFE del fondatore: giorni non validi -> tariffa a regime (non si regala lo 0%)
            self.assertEqual(bps, POL.LANCIO_BPS_REGIME, "giorni negativi devono dare la tariffa a regime (fail-safe)")
        elif giorni < POL.LANCIO_GIORNI_GRATIS:
            self.assertEqual(bps, 0)
        elif giorni < POL.LANCIO_GIORNI_FASE1:
            self.assertEqual(bps, POL.LANCIO_BPS_FASE1)
        else:
            self.assertEqual(bps, POL.LANCIO_BPS_REGIME)

    @_S
    @given(g1=st.integers(min_value=0, max_value=100000),
           g2=st.integers(min_value=0, max_value=100000))
    def test_monotona(self, g1, g2):
        # su giorni VALIDI (>=0): piu' anzianita' -> commissione mai minore (la rampa non torna
        # indietro). Sui giorni negativi vale il fail-safe (regime), fuori dalla monotonia.
        if g1 <= g2:
            self.assertLessEqual(POL.commissione_bps_lancio(g1), POL.commissione_bps_lancio(g2))


class TestRimborsoCancellazione(unittest.TestCase):
    @_S
    @given(pagato=st.integers(min_value=0, max_value=5_000_000),
           giorni=st.integers(min_value=-30, max_value=400),
           politica=st.sampled_from(["flessibile", "moderata", "rigida", "non_rimborsabile"]),
           ripens=st.booleans())
    def test_rimborso_mai_oltre_il_pagato(self, pagato, giorni, politica, ripens):
        r = CANC.calcola_rimborso(pagato, giorni, politica=politica, entro_ripensamento=ripens)
        rimb = r.get("rimborso_cents", 0)
        tratt = r.get("trattenuto_cents", 0)
        # niente negativi
        self.assertGreaterEqual(rimb, 0, f"rimborso negativo: {r}")
        self.assertGreaterEqual(tratt, 0, f"trattenuto negativo: {r}")
        # MAI rimborsare piu' di quanto pagato (regalo di soldi)
        self.assertLessEqual(rimb, max(0, pagato), f"rimborso > pagato: {r}")
        # conservazione: rimborso + trattenuto == pagato
        self.assertEqual(rimb + tratt, max(0, pagato), f"rimborso+trattenuto != pagato: {r}")

    @_S
    @given(pagato=st.integers(min_value=1, max_value=1_000_000),
           giorni=st.integers(min_value=3, max_value=400))
    def test_ripensamento_rende_tutto(self, pagato, giorni):
        # dentro il ripensamento 48h (arrivo >= 3 giorni) si rende il 100% (diritto legale)
        r = CANC.calcola_rimborso(pagato, giorni, politica="non_rimborsabile", entro_ripensamento=True)
        self.assertEqual(r.get("rimborso_cents", 0), pagato, f"ripensamento non rende tutto: {r}")


# ─────────────────────────────────────────────────────────────────────────────────────────
# LA RIGA SQL DELLA PURGA — provata COME SQL (2026-08-17)
# ─────────────────────────────────────────────────────────────────────────────────────────
_STATI = ("in_attesa", "in_attesa_host", "scaduto", "pagato", "rimborsato", "cancellata_host")


@st.composite
def _record(draw):
    """Un pendente: uno stato qualsiasi, nato fra 0 e 400 ore nel passato."""
    return (draw(st.sampled_from(_STATI)),
            draw(st.integers(min_value=0, max_value=400)))


class TestLaPurgaNonPuoPerdereChiAspettaISoldi(unittest.TestCase):
    """⛔ LA RIGA PIÙ RISCHIOSA DEL LAVORO DEL 2026-08-17, e non era provata come SQL.

    `fase162.pulisci_vecchi` esegue un `DELETE ... WHERE stato=? AND creato_ts<?`. Una
    condizione sbagliata lì non rompe niente in modo visibile: cancella **in silenzio** il
    record dove vive lo `stripe_pi`, cioè l'unico modo di restituire i soldi a chi aspetta.
    È esattamente il difetto trovato il 2026-08-17 — la soglia contava da `creato_ts`, cioè
    dalla PRENOTAZIONE — e un difetto di quella famiglia non lo prende un caso scelto a mano.

    ⚠️ LA FORMA della prova viene dal **TLP (Ternary Logic Partitioning)**, ricerca sui
    database (SQLancer, Rigger) — ⛔ **NON è una tecnica AWS**, e non va attribuita ad AWS:
    per il suo database AWS usa simulazione deterministica, metodi formali e iniezione di
    guasti, che sono già fra le nostre 11. Il TLP dice: le righe CANCELLATE e quelle RIMASTE
    devono ricomporre **esattamente** la tabella di partenza — nessuna persa, nessuna doppia.

    Gli attrezzi sono due che il progetto ha già (test a proprietà · oracolo indipendente):
    l'insieme atteso è ricalcolato **in Python**, non in SQL, così due errori uguali non si
    coprono a vicenda.
    """

    @_S
    @given(righe=st.lists(_record(), min_size=1, max_size=10),
           eta_sec=st.integers(min_value=0, max_value=400_000),
           ore_dopo=st.integers(min_value=0, max_value=500))
    def test_toglie_ESATTAMENTE_gli_scaduti_vecchi_e_nientaltro(self, righe, eta_sec, ore_dopo):
        base = 1_700_000_000
        clock = {"t": base}
        p = PEND.crea_pagamenti_pendenti(":memory:", orologio=lambda: clock["t"])
        p.inizializza_schema()
        tutti = set()
        for i, (stato, eta_ore) in enumerate(righe):
            rif = "R%d" % i
            clock["t"] = base - eta_ore * 3600          # nasce nel passato: è il punto
            p.registra(rif, alloggio_id="a", check_in="2026-10-01", check_out="2026-10-02",
                       stato=("in_attesa_host" if stato == "in_attesa_host" else "in_attesa"))
            if stato == "scaduto":
                p.scadi(rif)
            elif stato == "pagato":
                p.conferma(rif)
            elif stato == "rimborsato":
                p.marca_da_rimborsare(rif)
            elif stato == "cancellata_host":
                p.marca_cancellata_host(rif, 0)
            tutti.add(rif)
        clock["t"] = base
        ora = base + ore_dopo * 3600
        taglio = ora - max(60, eta_sec)
        # ── ORACOLO INDIPENDENTE: lo stesso conto, scritto in Python invece che in SQL ──
        attesi_via = {"R%d" % i for i, (stato, eta_ore) in enumerate(righe)
                      if stato == "scaduto" and (base - eta_ore * 3600) < taglio}
        quanti = p.pulisci_vecchi(eta_sec=eta_sec, ora_ts=ora)
        rimasti = {r for r in tutti if p.info(r) is not None}
        # ── TLP: le due parti devono ricomporre ESATTAMENTE la tabella ──
        self.assertEqual(rimasti | attesi_via, tutti,
                         "righe PERSE dalla partizione: cancellate + rimaste non ricompongono "
                         "la tabella. via=%r rimasti=%r" % (sorted(attesi_via), sorted(rimasti)))
        self.assertEqual(rimasti & attesi_via, set(),
                         "una riga risulta insieme cancellata E rimasta: %r"
                         % sorted(rimasti & attesi_via))
        self.assertEqual(quanti, len(attesi_via),
                         "il conto dei rimossi non torna con l'oracolo: dice %d, atteso %d"
                         % (quanti, len(attesi_via)))
        # ── E LA PROPRIETÀ CHE VALE I SOLDI, dichiarata a parte perché è quella che conta ──
        for i, (stato, _e) in enumerate(righe):
            if stato in ("rimborsato", "cancellata_host"):
                self.assertIsNotNone(
                    p.info("R%d" % i),
                    "la purga ha portato via un record in stato '%s': con lui se ne va lo "
                    "`stripe_pi` e quei soldi non si possono più restituire dal pannello"
                    % stato)


if __name__ == "__main__":
    unittest.main(verbosity=2)
