# -*- coding: utf-8 -*-
"""Guardia CHECK-IN: il tetto sono i PAGANTI, non la capienza della casa.

IL DIFETTO (fase83_server._checkin_pre_registra, righe ~5819-5825): il numero di ospiti
pre-registrati era validato contro la **capienza dell'annuncio** (`catalogo.dettaglio()['capacita']`)
invece che contro le **persone per cui si è pagato**. Su una casa da 6 posti con prenotazione
pagata per 2, l'ospite poteva registrare 5 nomi e ottenere `ok` — con due conseguenze reali:
  · la **tassa di soggiorno** resta quella incassata al preventivo (calcolata su `party`,
    fase59:311), quindi risulta riscossa **per meno teste di quelle presenti**;
  · il check-in completato **abilita il pass della porta** (fase127.sblocca) e l'export per le
    autorità dichiara più ospiti di quelli pagati.
`fase127.pre_registra` è corretto e generico: valida contro il numero che gli viene dato. Il
difetto è in CHI gli passa il numero.

LA CORREZIONE (3 righe, nessun modulo nuovo): il tetto diventa **min(paganti, capienza)**. Il
valore `party` è già **firmato nel voucher** (fase83:4856), quindi non manomettibile dall'ospite
e disponibile senza interrogare altri archivi. Se `party` manca (voucher storici) si ricade sulla
capienza: nessuna prenotazione vecchia diventa irregolare.

Scelta di prodotto del fondatore (2026-07-30): strada RIGOROSA — una persona in più viene
**RIFIUTATA** (422), come fanno tutti i portali, non accettata con segnalazione all'host.

VISTO ROSSO: senza il fix, `test_ospiti_oltre_i_paganti_RIFIUTATI` e
`test_il_tetto_e_il_MINORE_fra_paganti_e_capienza` passano con 200 invece di 422.
"""
import json
import shutil
import tempfile
import unittest

from fase57_vetrina import SchedaAlloggio
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

GIORNI = ("2026-09-01", "2026-09-02", "2026-09-03")


def _ospiti(n):
    return [{"nome": "Nome%d Cognome%d" % (i, i), "documento": "DOC%05d" % i}
            for i in range(1, n + 1)]


class _Base(unittest.TestCase):
    CAPIENZA = 6

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32,
            db_catalogo=self.d + "/c.db", db_inventario=self.d + "/i.db",
            db_checkin=self.d + "/ck.db"))
        self.assertIsNotNone(self.sys.checkin, "il check-in deve essere attivo")
        self.r = crea_router(self.sys)
        self.sys.catalogo.pubblica(SchedaAlloggio(
            host_id="h1", slug="casa", titolo="Casa", citta="Roma",
            prezzo_notte_cents=10000, capacita=self.CAPIENZA))
        for g in GIORNI:
            self.sys.inventario.imposta_disponibilita("casa", g, unita_totali=1,
                                                      prezzo_netto_cents=10000)

    def g(self, m, p, b=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, {})

    def voucher_per(self, paganti):
        """Voucher di una prenotazione pagata per `paganti` persone."""
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": GIORNI[0],
                       "check_out": GIORNI[1], "party": paganti})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "g@x.it"})
        self.assertEqual(s, 201, b)
        return b["voucher_token"]

    def checkin(self, voucher, n_ospiti):
        return self.g("POST", "/api/checkin/pre_registra",
                      {"voucher_token": voucher, "ospiti": _ospiti(n_ospiti)})

    def completato(self, voucher):
        s, st = self.g("GET", "/api/checkin/stato", q={"voucher_token": voucher})
        self.assertEqual(s, 200, st)
        return bool(st.get("completato"))


class TestCheckinPaganti(_Base):

    # ── IL CASO DEL DIFETTO ─────────────────────────────────────────────────
    def test_ospiti_oltre_i_paganti_RIFIUTATI(self):
        """Casa da 6, pagata per 2, si presentano 5: RIFIUTO. Prima passava con 200."""
        v = self.voucher_per(2)
        s, out = self.checkin(v, 5)
        self.assertEqual(s, 422, "registrati 5 ospiti su 2 pagati: %s" % out)
        self.assertFalse(out.get("ok"))
        # e soprattutto: il pass della porta NON deve essere abilitato
        self.assertFalse(self.completato(v),
                         "check-in completato con piu' ospiti dei paganti: pass abilitato")

    def test_anche_UNA_persona_in_piu_e_rifiutata(self):
        """La regola e' rigorosa (scelta del fondatore): 3 su 2 pagati = no."""
        v = self.voucher_per(2)
        self.assertEqual(self.checkin(v, 3)[0], 422)
        self.assertFalse(self.completato(v))

    def test_il_tetto_e_il_MINORE_fra_paganti_e_capienza(self):
        """Pagata per 8 su una casa da 6: vale la capienza (6), non i paganti."""
        v = self.voucher_per(8)
        self.assertEqual(self.checkin(v, 7)[0], 422, "7 ospiti in una casa da 6")
        s, out = self.checkin(v, 6)
        self.assertEqual(s, 200, "6 ospiti in una casa da 6, pagata per 8: %s" % out)
        self.assertTrue(out.get("ok"))

    # ── NON-REGRESSIONE: il caso legittimo resta identico ───────────────────
    def test_esattamente_i_paganti_ACCETTATI(self):
        v = self.voucher_per(2)
        s, out = self.checkin(v, 2)
        self.assertEqual(s, 200, out)
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("ospiti"), 2)
        self.assertTrue(self.completato(v), "il check-in legittimo deve abilitare il pass")

    def test_meno_dei_paganti_ACCETTATI(self):
        """Pagata per 4, se ne presentano 2: legittimo (uno rinuncia al viaggio)."""
        v = self.voucher_per(4)
        s, out = self.checkin(v, 2)
        self.assertEqual(s, 200, out)
        self.assertEqual(out.get("ospiti"), 2)

    # ── PRENOTAZIONI STORICHE: nessuna diventa irregolare ───────────────────
    def test_voucher_SENZA_paganti_ricade_sulla_capienza(self):
        """Voucher vecchio (nato prima che `party` fosse firmato): si torna al comportamento
        di prima — tetto = capienza — invece di bloccare un ospite legittimo."""
        v_storico = self.sys.firma.codifica({
            "tipo": "voucher", "riferimento": "rif_storico_1", "alloggio_id": "casa",
            "check_in": GIORNI[0], "check_out": GIORNI[1]})      # NESSUN 'party'
        s, out = self.g("POST", "/api/checkin/pre_registra",
                        {"voucher_token": v_storico, "ospiti": _ospiti(self.CAPIENZA)})
        self.assertEqual(s, 200, "un voucher storico non deve diventare irregolare: %s" % out)
        self.assertEqual(out.get("ospiti"), self.CAPIENZA)

    def test_voucher_con_paganti_ASSURDO_non_apre_la_casa(self):
        """Difesa: un `party` non intero o non positivo non deve allargare il tetto oltre la
        capienza ne' bloccare tutto. (Il voucher e' firmato da noi, ma la guardia costa zero.)"""
        for valore in (0, -3, "molti", None, 2.5):
            v = self.sys.firma.codifica({
                "tipo": "voucher", "riferimento": "rif_strano", "alloggio_id": "casa",
                "check_in": GIORNI[0], "check_out": GIORNI[1], "party": valore})
            s, _ = self.g("POST", "/api/checkin/pre_registra",
                          {"voucher_token": v, "ospiti": _ospiti(self.CAPIENZA)})
            self.assertEqual(s, 200, "party=%r ha rotto il check-in" % (valore,))
            s2, _ = self.g("POST", "/api/checkin/pre_registra",
                           {"voucher_token": v, "ospiti": _ospiti(self.CAPIENZA + 1)})
            self.assertEqual(s2, 422, "party=%r ha aperto la casa oltre la capienza" % (valore,))


if __name__ == "__main__":
    unittest.main()
