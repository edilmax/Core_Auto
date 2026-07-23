"""
GUARDIA (vista ROSSA sul codice vecchio): il Guardiano fase186 deve accorgersi dei SOLDI
ancora incamminati verso l'host per una prenotazione RIMBORSATA all'ospite o CANCELLATA
dall'host — la "PERDITA PIENA" documentata in fase83:3638 (payout 'maturato' o escrow che
si auto-rilascia quando uno dei passi di sicurezza del rimborso e' fallito in isolamento).

Usa i DB VERI in memoria (fase131 payout, fase160 escrow, fase162 pendenti): niente stub,
cosi' la guardia prova la correlazione reale sulla chiave condivisa 'riferimento'.

Test di REMOZIONE inclusi: uno stato CORRETTO (payout trattenuto, escrow annullato) e una
prenotazione NORMALE (pagata, con payout maturato = legittimo) NON devono far scattare nulla
-> la guardia non e' compiacente.
"""
import types
import unittest

import fase186_guardiano as G
from fase131_payout_dashboard import crea_payout_dashboard
from fase160_escrow_garanzia import crea_escrow_garanzia
from fase162_pagamenti_pendenti import crea_pagamenti_pendenti

ORA = 1_700_000_000
CLOCK = (lambda: ORA)   # scansiona(ora=...) vuole un OROLOGIO (callable), non un int


def _sistema():
    orol = (lambda: ORA)
    pay = crea_payout_dashboard(":memory:", orologio=orol); pay.inizializza_schema()
    gar = crea_escrow_garanzia(":memory:", orologio=orol); gar.inizializza_schema()
    pp = crea_pagamenti_pendenti(":memory:", orologio=orol); pp.inizializza_schema()
    return types.SimpleNamespace(
        payout=pay, garanzia=gar, pagamenti_pendenti=pp,
        config=types.SimpleNamespace(stripe_secret_key=""),   # niente Stripe -> niente riconciliazione
        finanza=None, tassi=None, registro_host=None)


def _pendente(pp, rif, stato):
    pp.registra(rif, alloggio_id="allog-1", check_in="2026-08-01", check_out="2026-08-03")
    if stato == "rimborsato":
        assert pp.marca_da_rimborsare(rif)
    elif stato == "cancellata_host":
        assert pp.marca_cancellata_host(rif)
    elif stato == "pagato":
        pp.conferma(rif)
    elif stato == "in_attesa":
        pass
    else:
        raise ValueError(stato)
    got = pp.info(rif)["stato"]
    assert got == stato, (rif, got, stato)


def _payout(pay, rif, stato, host="host-1"):
    assert pay.registra_maturato(rif, host, 5000, "EUR")
    if stato in ("in_transito", "trattenuto"):
        assert pay.aggiorna_stato(rif, stato), (rif, stato)
    assert pay.stato_di(rif) == stato, (rif, pay.stato_di(rif), stato)


def _escrow_scaduto(gar, rif, annullato=False):
    # sblocco nel PASSATO rispetto a ORA -> aperte_scadute(grazia_ore=0) lo trova
    assert gar.apri(rif, 5000, alloggio_id="allog-1", ora_checkin_ts=ORA - 100000, finestra_ore=1)
    if annullato:
        assert gar.annulla(rif)["ok"]


class TestSoldiSuRimborsata(unittest.TestCase):

    # --- POSITIVI: la guardia DEVE gridare (rossi sul codice vecchio) ---
    def test_payout_maturato_su_rimborsata(self):
        s = _sistema()
        _pendente(s.pagamenti_pendenti, "R1", "rimborsato")
        _payout(s.payout, "R1", "maturato")
        rep = G.scansiona(s, ora=CLOCK)
        self.assertFalse(rep["pulito"])
        self.assertIn("payout_su_rimborsata", rep["anomalie"])
        rif_trovati = [r["prenotazione_id"] for r in rep["anomalie"]["payout_su_rimborsata"]]
        self.assertIn("R1", rif_trovati)
        self.assertEqual(rep["anomalie"]["payout_su_rimborsata"][0]["stato_pendente"], "rimborsato")

    def test_payout_in_transito_su_cancellata_host(self):
        s = _sistema()
        _pendente(s.pagamenti_pendenti, "R2", "cancellata_host")
        _payout(s.payout, "R2", "in_transito")
        rep = G.scansiona(s, ora=CLOCK)
        self.assertIn("payout_su_rimborsata", rep["anomalie"])
        self.assertIn("R2", [r["prenotazione_id"] for r in rep["anomalie"]["payout_su_rimborsata"]])

    def test_escrow_scaduto_su_rimborsata(self):
        s = _sistema()
        _pendente(s.pagamenti_pendenti, "R3", "rimborsato")
        _escrow_scaduto(s.garanzia, "R3")
        rep = G.scansiona(s, ora=CLOCK)
        self.assertIn("escrow_su_rimborsata", rep["anomalie"])
        self.assertIn("R3", [r["prenotazione_id"] for r in rep["anomalie"]["escrow_su_rimborsata"]])

    # --- REMOZIONE / NON-compiacenza: la guardia NON deve gridare ---
    def test_payout_maturato_su_prenotazione_PAGATA_e_ok(self):
        # una prenotazione normale, pagata, con payout maturato in attesa di bonifico: LEGITTIMO.
        s = _sistema()
        _pendente(s.pagamenti_pendenti, "N1", "pagato")
        _payout(s.payout, "N1", "maturato")
        rep = G.scansiona(s, ora=CLOCK)
        self.assertNotIn("payout_su_rimborsata", rep["anomalie"])

    def test_payout_trattenuto_su_rimborsata_e_ok(self):
        # stato CORRETTO dopo un rimborso: il payout e' 'trattenuto' -> nessun soldo all'host.
        s = _sistema()
        _pendente(s.pagamenti_pendenti, "OK1", "rimborsato")
        _payout(s.payout, "OK1", "trattenuto")
        rep = G.scansiona(s, ora=CLOCK)
        self.assertNotIn("payout_su_rimborsata", rep["anomalie"])

    def test_escrow_annullato_su_rimborsata_e_ok(self):
        # stato CORRETTO: l'escrow e' stato annullato dal rimborso -> non si auto-rilascia.
        s = _sistema()
        _pendente(s.pagamenti_pendenti, "OK2", "rimborsato")
        _escrow_scaduto(s.garanzia, "OK2", annullato=True)
        rep = G.scansiona(s, ora=CLOCK)
        self.assertNotIn("escrow_su_rimborsata", rep["anomalie"])

    def test_tutto_sano_e_pulito(self):
        s = _sistema()
        _pendente(s.pagamenti_pendenti, "S1", "pagato")
        _payout(s.payout, "S1", "maturato")
        rep = G.scansiona(s, ora=CLOCK)
        self.assertTrue(rep["pulito"], rep["anomalie"])

    # --- ROBUSTEZZA ---
    def test_moduli_assenti_non_esplode(self):
        vuoto = types.SimpleNamespace(config=types.SimpleNamespace(stripe_secret_key=""),
                                      finanza=None, tassi=None)
        rep = G.scansiona(vuoto, ora=CLOCK)
        self.assertTrue(rep["pulito"])

    def test_read_only_doppio_giro_non_scrive(self):
        s = _sistema()
        _pendente(s.pagamenti_pendenti, "RO", "rimborsato")
        _payout(s.payout, "RO", "maturato")
        _escrow_scaduto(s.garanzia, "RO")
        G.scansiona(s, ora=CLOCK)
        G.scansiona(s, ora=CLOCK)   # due giri: se scrivesse, cambierebbe qualcosa
        self.assertEqual(s.payout.stato_di("RO"), "maturato")
        self.assertEqual(s.pagamenti_pendenti.info("RO")["stato"], "rimborsato")
        self.assertEqual(s.garanzia.stato("RO")["stato"], "in_garanzia")


if __name__ == "__main__":
    unittest.main()
