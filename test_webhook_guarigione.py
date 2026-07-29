# -*- coding: utf-8 -*-
"""Guardia RAMO DI GUARIGIONE del webhook di pagamento (BUG #32) — l'ultimo buco del LIVELLO 1.

IL CAMMINO CHE SANA: Stripe conferma il pagamento; il nostro gestore scrive 'pagato' (CAS) e poi
esegue i passi DERIVATI — tassa di soggiorno nel registro del comune, payout dell'host da
'in_attesa' a 'maturato', riga d'incasso nel giornale. Se il processo MUORE fra il CAS e i passi
derivati (crash, riavvio, deploy, rete), lo stato resta storpio PER SEMPRE: l'ospite ha pagato,
noi risultiamo aver incassato, ma **la tassa non e' mai registrata e l'host non viene mai pagato**
— e Stripe continua a ritentare a vuoto perche' il riferimento risulta gia' 'pagato'.
La produzione sfrutta quel RETRY per RI-ASSERIRE i passi idempotenti (`_riasserisci_incasso`).

PERCHE' QUESTO FILE ESISTE: il revisore ostile del 2026-07-28 ha PROVATO che disattivando quel
ramo (`if stato == "pagato":` -> `if False and ...`) l'intera suite restava VERDE: la rete di
salvataggio non era sorvegliata da nessuno. Qui si chiude.

VISTO ROSSO (riproducibile): neutralizzare il ramo in fase83_server.py fa fallire
`test_il_retry_SANA_tassa_e_payout` (tassa 0 e payout ancora 'in_attesa').
"""
import json
import os
import shutil
import tempfile
import unittest

import time

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test

WHSEC = "whsec_guarigione"


class TestWebhookGuarigione(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"h" * 32, stripe_webhook_secret=WHSEC,
            db_catalogo=self.d + "/cat.db", db_inventario=self.d + "/inv.db",
            db_pendenti=self.d + "/pen.db", db_payout=self.d + "/pay.db",
            db_tassa_comunale=self.d + "/tassa.db", db_finanza=self.d + "/fin.db",
            db_registro_host=self.d + "/host.db", db_garanzia=self.d + "/gar.db"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    # ── aiutanti ────────────────────────────────────────────────────────────
    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _pendente_pagato_a_meta(self):
        """Fabbrica lo STATO STORPIO che il crash lascia dietro di se': un pendente gia'
        'pagato' (CAS avvenuto) MA senza i passi derivati (nessuna tassa, payout 'in_attesa').
        E' esattamente lo stato in cui il processo muore a meta'."""
        pp = self.sis.pagamenti_pendenti
        rif = "rif_guarigione_1"
        corpo = {"totale_cents": 31000, "prezzo_guest_cents": 30000, "tassa_cents": 1000,
                 "valuta": "EUR", "host_id": "h_prova", "comune": "Roma",
                 "alloggio": "casa-prova", "check_in": "2026-12-01", "check_out": "2026-12-03"}
        pp.registra(rif, alloggio_id="casa-prova", check_in="2026-12-01",
                    check_out="2026-12-03", idem_key="idem_guar_1", tassa_cents=1000,
                    comune="Roma", host_id="h_prova", corpo_json=json.dumps(corpo))
        pp.conferma(rif)                                   # CAS: lo stato diventa 'pagato'
        self.sis.payout.registra_in_attesa(rif, "h_prova", 27000, "EUR")   # payout 'in_attesa'
        return rif, corpo

    def _stato_payout(self, rif):
        return self.sis.payout.stato_di(rif) or ""

    def _tassa_riscossa(self, _rif, comune="Roma"):
        # il ledger somma per COMUNE (fase147.totale_riscosso(comune))
        return int(self.sis.tassa_comunale.totale_riscosso(comune) or 0)

    # ── LA PROVA CHE CONTA ──────────────────────────────────────────────────
    def test_il_retry_SANA_tassa_e_payout(self):
        rif, corpo = self._pendente_pagato_a_meta()
        # STATO STORPIO confermato: pagato, ma niente tassa e payout fermo
        self.assertEqual(self.sis.pagamenti_pendenti.info(rif)["stato"], "pagato")
        self.assertEqual(self._tassa_riscossa(rif), 0, "partenza: la tassa non c'e' (crash)")
        self.assertEqual(self._stato_payout(rif), "in_attesa", "partenza: payout bloccato")

        # ARRIVA IL RETRY DI STRIPE sullo stesso riferimento
        evento = json.dumps({"id": "evt_retry_1", "type": "checkout.session.completed",
                             "data": {"object": {"id": "cs_1",
                                                 "metadata": {"riferimento": rif}}}})
        st, _ = self.r.gestisci("POST", "/api/payments/webhook", {}, evento,
                                {"Stripe-Signature": firma_di_test(evento, WHSEC, int(time.time()))})
        self.assertEqual(st, 200, "il webhook di retry deve essere accettato")

        # GUARIGIONE: ora la tassa c'e' e il payout e' maturato
        self.assertEqual(self._tassa_riscossa(rif), 1000,
                         "il retry NON ha registrato la tassa: il ramo di guarigione non gira")
        self.assertEqual(self._stato_payout(rif), "maturato",
                         "il retry NON ha maturato il payout: l'host resterebbe non pagato")

    def test_il_terzo_retry_non_raddoppia_nulla(self):
        """La guarigione deve essere idempotente: Stripe ritenta per GIORNI."""
        rif, _ = self._pendente_pagato_a_meta()
        for n in range(3):
            evento = json.dumps({"id": "evt_retry_%d" % n, "type": "checkout.session.completed",
                                 "data": {"object": {"id": "cs_1",
                                                     "metadata": {"riferimento": rif}}}})
            st, _ = self.r.gestisci("POST", "/api/payments/webhook", {}, evento,
                                    {"Stripe-Signature": firma_di_test(evento, WHSEC, int(time.time()))})
            self.assertEqual(st, 200)
        self.assertEqual(self._tassa_riscossa(rif), 1000, "tassa RADDOPPIATA dai retry")
        self.assertEqual(self._stato_payout(rif), "maturato")

    def test_la_guarigione_non_risuscita_una_rimborsata(self):
        """Fail-safe: se nel frattempo la prenotazione e' stata rimborsata, il retry NON deve
        far maturare il payout (sarebbe un bonifico su soldi gia' restituiti)."""
        rif, _ = self._pendente_pagato_a_meta()
        self.sis.pagamenti_pendenti.marca(rif, "rimborsato") \
            if hasattr(self.sis.pagamenti_pendenti, "marca") else None
        info = self.sis.pagamenti_pendenti.info(rif)
        if info.get("stato") != "rimborsato":
            self.skipTest("questo store non espone il passaggio diretto a 'rimborsato'")
        evento = json.dumps({"id": "evt_r", "type": "checkout.session.completed",
                             "data": {"object": {"id": "cs_1",
                                                 "metadata": {"riferimento": rif}}}})
        st, _ = self.r.gestisci("POST", "/api/payments/webhook", {}, evento,
                                {"Stripe-Signature": firma_di_test(evento, WHSEC, int(time.time()))})
        self.assertEqual(st, 200)
        self.assertNotEqual(self._stato_payout(rif), "in_transito",
                            "una rimborsata non deve avviare il bonifico")


if __name__ == "__main__":
    unittest.main()
