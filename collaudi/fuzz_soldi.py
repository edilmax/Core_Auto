"""
FUZZING coverage-guided (Atheris) sui MOTORI DEI SOLDI.

Atheris genera byte casuali guidati dalla copertura, li trasforma in input per i motori
finanziari e verifica che gli INVARIANTI reggano SEMPRE (nessun crash, nessun negativo,
conservazione). Se trova un input che rompe un invariante, si ferma e lo mostra.

Gira su Linux (CI Ubuntu): `python collaudi/fuzz_soldi.py -atheris_runs=200000`.
Su Windows Atheris non compila (serve clang/libFuzzer) -> vedi test_property_soldi.py (Hypothesis).

NOTA sugli invarianti: alcuni valgono per QUALSIASI input (conservazione, non-negativita');
altri (host_incassa==saldo, gateway>=Stripe) valgono nel REGIME REALISTICO. Sotto prezzo
minuscolo il motore comprime fee/commissione entro l'anticipo (corner sub-cent che nel mondo
reale non esiste: nessuna prenotazione costa 3 centesimi) e li' quelle uguaglianze non tengono.
Vengono quindi verificate solo dove il motore lavora davvero -> nessun falso-rosso in CI.
"""
import os
import sys

# La radice del repo (dove vivono i fase*.py) DEVE stare nel path: lanciando
# "python collaudi/fuzz_soldi.py" Python mette collaudi/ nel path, non la radice.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import atheris

with atheris.instrument_imports():
    import fase188_paga_struttura as PS
    import fase98_policy_commissione as POL
    import fase111_cancellazione as CANC


def TestOneInput(data):
    fdp = atheris.FuzzedDataProvider(data)

    # 1) MOTORE PAGA IN STRUTTURA -----------------------------------------------------------
    prezzo = fdp.ConsumeIntInRange(0, 10 ** 9)
    notti = fdp.ConsumeIntInRange(1, 366)
    comm = fdp.ConsumeIntInRange(0, 10 ** 9)
    psp = fdp.ConsumeIntInRange(0, 500)
    r = PS.calcola(prezzo, notti, comm, psp_bps=psp)

    # --- BLINDATI: valgono per OGNI input, per costruzione ---
    assert all(isinstance(v, int) and v >= 0 for v in r.values()), ("negativo", r)
    assert r["anticipo_online_cents"] + r["saldo_in_loco_cents"] == r["ospite_paga_totale_cents"], ("conservazione", r)
    assert r["commissione_cents"] <= max(0, prezzo), ("comm>prezzo", prezzo, r)
    assert r["noi_incassiamo_cents"] == r["commissione_cents"] + r["fee_cents"], ("ricavo storto", r)
    assert r["anticipo_online_cents"] <= r["ospite_paga_totale_cents"], ("anticipo>totale", r)

    # --- BUSINESS: solo nel regime realistico (niente compressione da prezzo-minuscolo) ---
    if prezzo >= 5000 and comm <= prezzo // 5:
        A = r["anticipo_online_cents"]
        assert r["host_incassa_cents"] == r["saldo_in_loco_cents"], ("host!=saldo", r)
        # il gateway copre SEMPRE lo Stripe peggiore (costanti del modulo stesso -> non derivano)
        stripe_peggiore = PS.GATEWAY_FISSO_CENTS + A * PS.GATEWAY_BPS // 10000
        assert r["gateway_cents"] >= stripe_peggiore, ("sotto-Stripe = PERDITA", r)

    # 2) RAMPA COMMISSIONI ------------------------------------------------------------------
    g = fdp.ConsumeIntInRange(-1000, 100000)
    bps = POL.commissione_bps_lancio(g)
    assert bps in (0, POL.LANCIO_BPS_FASE1, POL.LANCIO_BPS_REGIME), ("scaglione fuori regola", g, bps)

    # 3) RIMBORSO CANCELLAZIONE -------------------------------------------------------------
    pagato = fdp.ConsumeIntInRange(0, 10 ** 9)
    giorni = fdp.ConsumeIntInRange(-60, 500)
    pol = ["flessibile", "moderata", "rigida", "non_rimborsabile"][fdp.ConsumeIntInRange(0, 3)]
    rr = CANC.calcola_rimborso(pagato, giorni, politica=pol,
                               entro_ripensamento=fdp.ConsumeBool())
    rimb = rr.get("rimborso_cents", 0)
    tratt = rr.get("trattenuto_cents", 0)
    assert 0 <= rimb <= max(0, pagato), ("rimborso oltre pagato", pagato, rr)
    assert rimb + tratt == max(0, pagato), ("conservazione rimborso", pagato, rr)


atheris.Setup(sys.argv, TestOneInput)
atheris.Fuzz()
