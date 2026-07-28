"""GUARDIA — TRANSIZIONI DI STATO dimostrate con Z3 (fase199) + CONCORDANZA modello<->codice VERO.

Tre livelli, ognuno con un lavoro diverso (nessuno da solo basta):
  1. TEOREMI Z3 (`dimostra_transizioni`): UNSAT del controesempio = proprieta' vera per TUTTI
     gli infiniti casi (cammini di ogni lunghezza, ogni intero). Skip pulito se z3 assente.
  2. CONCORDANZA (senza z3): il MODELLO su cui i teoremi sono dimostrati deve coincidere con
     il CODICE VERO — si pilota il DB reale (fase162/fase160) su TUTTI gli stati x TUTTI gli
     eventi e su valori limite, e si pretende la stessa relazione/gli stessi numeri.
     Se un guard SQL o un clamp cambia in produzione, QUI diventa rosso.
  3. IDEMPOTENZA REALE: il replay (webhook duplicato) eseguito sul DB vero non cambia nulla.

VISTO ROSSO (regola aurea): ogni livello e' stato provato a fallire rompendo temporaneamente
la produzione (tabella payout con 'pagato'->'maturato'; whitelist di `conferma` allargata a
'rimborsato'; clamp di `risolvi` rimosso) e il modello (replay che somma l'importo) —
dettagli nel report di collaudo. Codice ripristinato identico, test di nuovo verdi.
"""
import os
import shutil
import sqlite3
import tempfile
import unittest

from fase199_invarianti import (EVENTI_PRENOTAZIONE, TERMINALI_NEGATIVI_PRENOTAZIONE,
                                formula_split_proporzionale, formula_split_risolvi,
                                transizioni_prenotazione)

# Test di RIMOZIONE (anti-finti-verdi): l'elenco e' ESPLICITO. Se un teorema sparisce dal
# motore (refactoring che lo perde), il get() ritorna None != 'DIMOSTRATO' -> rosso.
TEOREMI_ATTESI = (
    "PREN_terminale_assorbente", "PREN_mai_pagato_da_terminale",
    "PREN_pagato_solo_da_pagabili", "PREN_monotona_senza_cicli",
    "PAY_pagato_assorbente", "PAY_mai_ritorno_in_coda",
    "PAY_monotono_mai_indietro", "PAY_cicli_solo_coppia_hold",
    "ESC_risolvi_conservazione_clamp", "ESC_proporzionale_conservazione_clamp",
    "IDEM_eventi_prenotazione", "IDEM_eventi_payout", "IDEM_webhook_pagamento",
)


class TestTeoremiTransizioni(unittest.TestCase):
    """Ogni teorema DEVE risultare 'DIMOSTRATO' (UNSAT del controesempio)."""

    def test_tutti_i_teoremi_dimostrati(self):
        try:
            import z3  # noqa: F401
        except Exception:
            self.skipTest("z3 non installato in questo ambiente (gira dove z3-solver e' presente)")
        from fase199_invarianti import dimostra_transizioni
        ris = dimostra_transizioni()
        for nome in TEOREMI_ATTESI:
            self.assertEqual(ris.get(nome), "DIMOSTRATO",
                             "%s NON dimostrato: %r" % (nome, ris.get(nome)))


class TestConcordanzaPrenotazione(unittest.TestCase):
    """Il modello formale delle transizioni PRENOTAZIONE deve coincidere con il codice VERO:
    si mette il DB reale (fase162) in OGNI stato, si applica OGNI evento, e la relazione
    osservata deve essere ESATTAMENTE quella su cui i teoremi Z3 sono dimostrati.
    (Ogni arco del modello e' prodotto da UN solo evento -> l'uguaglianza degli insiemi
    verifica presenza E assenza di ogni singolo arco, evento per evento.)"""

    def test_relazione_osservata_uguale_al_modello(self):
        from fase162_pagamenti_pendenti import crea_pagamenti_pendenti
        d = tempfile.mkdtemp()
        try:
            db = os.path.join(d, "pend.db")
            pp = crea_pagamenti_pendenti(db)
            pp.inizializza_schema()
            osservate = set()
            k = 0
            for stato in sorted(transizioni_prenotazione()):
                for nome_ev, _srcs, _target in EVENTI_PRENOTAZIONE:
                    k += 1
                    rif = "r%03d" % k
                    self.assertTrue(pp.registra(rif, alloggio_id="A", check_in="2026-09-01",
                                                check_out="2026-09-03"))
                    con = sqlite3.connect(db)
                    with con:
                        con.execute("UPDATE pendenti SET stato=? WHERE riferimento=?",
                                    (stato, rif))
                    con.close()
                    # applica l'evento sul CODICE VERO (mai sul modello)
                    if nome_ev == "conferma":
                        pp.conferma(rif)
                    elif nome_ev == "scadi":
                        pp.scadi(rif)
                    elif nome_ev == "marca_da_rimborsare":
                        pp.marca_da_rimborsare(rif)
                    elif nome_ev == "marca_cancellata_host":
                        pp.marca_cancellata_host(rif, 0)
                    else:
                        self.fail("evento del modello senza pilota reale: %r" % nome_ev)
                    dopo = pp.info(rif)["stato"]
                    if dopo != stato:
                        osservate.add((stato, dopo))
            attese = {(s, t) for s, vs in transizioni_prenotazione().items() for t in vs}
            self.assertEqual(osservate, attese,
                             "la macchina VERA (fase162) diverge dal modello dimostrato con Z3")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_terminali_negativi_davvero_terminali_nel_modello(self):
        tab = transizioni_prenotazione()
        for t in TERMINALI_NEGATIVI_PRENOTAZIONE:
            self.assertEqual(tab[t], set(), "%r deve essere assorbente nel modello" % t)


class TestConcordanzaEscrow(unittest.TestCase):
    """Le formule-selettore (le STESSE che Z3 dimostra ∀ intero) eseguite concrete devono
    dare ESATTAMENTE i numeri del codice vero (fase160) sui valori limite: negativo abnorme,
    -1, 0, 1, meta', importo-1, importo, importo+1, abnorme positivo."""

    IMP = 1000
    CASI = (-10 ** 9, -1, 0, 1, 499, 999, 1000, 1001, 10 ** 9)

    def test_risolvi_concorda_e_conserva(self):
        from fase160_escrow_garanzia import crea_escrow_garanzia
        d = tempfile.mkdtemp()
        try:
            gz = crea_escrow_garanzia(os.path.join(d, "gz.db"))
            gz.inizializza_schema()
            for i, x in enumerate(self.CASI):
                rif = "e%02d" % i
                self.assertTrue(gz.apri(rif, self.IMP))
                self.assertTrue(gz.contesta(rif)["ok"])
                r = gz.risolvi(rif, rimborso_ospite_cents=x)
                self.assertTrue(r["ok"], "risolvi fallita su x=%d: %r" % (x, r))
                host_m, rimb_m = formula_split_risolvi(self.IMP, x)
                self.assertEqual((r["host_riceve_cents"], r["ospite_rimborso_cents"]),
                                 (host_m, rimb_m),
                                 "fase160.risolvi diverge dalla formula dimostrata su x=%d" % x)
                self.assertEqual(r["host_riceve_cents"] + r["ospite_rimborso_cents"], self.IMP)
                self.assertTrue(0 <= r["ospite_rimborso_cents"] <= self.IMP)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_proporzionale_concorda_e_conserva(self):
        from fase160_escrow_garanzia import crea_escrow_garanzia
        d = tempfile.mkdtemp()
        try:
            gz = crea_escrow_garanzia(os.path.join(d, "gz.db"))
            gz.inizializza_schema()
            for i, x in enumerate(self.CASI):
                rif = "p%02d" % i
                self.assertTrue(gz.apri(rif, self.IMP))
                r = gz.chiudi_proporzionale(rif, x)
                self.assertTrue(r["ok"], "chiudi_proporzionale fallita su x=%d: %r" % (x, r))
                host_m, rimb_m = formula_split_proporzionale(self.IMP, x)
                self.assertEqual((r["host_riceve_cents"], r["ospite_rimborso_cents"]),
                                 (host_m, rimb_m),
                                 "fase160.chiudi_proporzionale diverge dalla formula su x=%d" % x)
                self.assertEqual(r["host_riceve_cents"] + r["ospite_rimborso_cents"], self.IMP)
                self.assertTrue(0 <= r["host_riceve_cents"] <= self.IMP)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestIdempotenzaReale(unittest.TestCase):
    """Il replay (webhook consegnato due volte) sul DB VERO: stato e importi INVARIATI."""

    def test_doppia_conferma_non_cambia_stato(self):
        from fase162_pagamenti_pendenti import crea_pagamenti_pendenti
        d = tempfile.mkdtemp()
        try:
            pp = crea_pagamenti_pendenti(os.path.join(d, "pend.db"))
            pp.inizializza_schema()
            self.assertTrue(pp.registra("rif1", alloggio_id="A", check_in="2026-09-01",
                                        check_out="2026-09-03"))
            r1 = pp.conferma("rif1")
            self.assertEqual(r1["stato"], "in_attesa")     # stato PRECEDENTE: CAS vinto
            r2 = pp.conferma("rif1")                       # webhook DUPLICATO
            self.assertEqual(r2["stato"], "pagato",
                             "il replay deve segnalare 'gia' pagato', non ri-confermare")
            self.assertEqual(pp.info("rif1")["stato"], "pagato")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_replay_registra_maturato_non_tocca_importo(self):
        from fase131_payout_dashboard import crea_payout_dashboard
        d = tempfile.mkdtemp()
        try:
            pd = crea_payout_dashboard(os.path.join(d, "pay.db"))
            pd.inizializza_schema()
            self.assertTrue(pd.registra_maturato("rif1", "h1", 5000, "EUR"))
            # replay con importo DIVERSO (webhook duplicato dopo un ricalcolo): ignorato
            self.assertTrue(pd.registra_maturato("rif1", "h1", 9999, "EUR"))
            info = pd.info("rif1")
            self.assertEqual((info["minori"], info["stato"]), (5000, "maturato"),
                             "il replay ha riscritto il payout: %r" % (info,))
            # replay del passo di stato: maturato->maturato non e' una transizione -> no-op
            self.assertFalse(pd.aggiorna_stato("rif1", "maturato"))
            self.assertEqual(pd.stato_di("rif1"), "maturato")
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
