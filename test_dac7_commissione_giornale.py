# -*- coding: utf-8 -*-
"""GUARDIA: la commissione DAC7 e' CORRETTA anche col bonifico in HOLD (fix 2026-07-19).

BUG (trovato col metodo differenziale fase59-vs-DAC7): aggrega_dac7 leggeva il netto
host SOLO dai bonifici COMPLETATI (payout_host a giornale). Un host REPORTABILE con
payout trattenuto (dati fiscali mancanti / verifica revocata) -> nessun payout_host ->
netto=0 -> commissioni = lordo - 0 = LORDO PIENO. Dichiaravamo al Fisco che la
piattaforma trattiene TUTTO l'incassato dell'host in commissione (nel test: 513000 invece
di 78000 cents, +558%), e che l'host ha ricevuto quasi nulla.

FIX: la commissione NETTA (comm + costo carta - credito) si registra a giornale al
PAGAMENTO (idempotente su evento_id 'commissione:<rif>'), e aggrega_dac7 calcola
netto = lordo - commissione quando la riga c'e' (retrocompat: storico pre-fix dal payout).
"""
import datetime
import json
import os
import sqlite3
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_dc"


def _fake(url, body, headers):
    return {"url": "https://x/cs", "id": "cs_" + os.urandom(5).hex()}


class TestDac7CommissioneGiornale(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def _build(self):
        d = tempfile.mkdtemp()
        reg = f"{d}/r.db"
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=reg,
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_finanza=f"{d}/f.db", db_tassa_comunale=f"{d}/t.db",
            commissione_bps=1000, psp_bps=300, stripe_secret_key="sk",
            stripe_webhook_secret=WH, stripe_success_url="x", stripe_cancel_url="x"))
        r = crea_router(sis, host_key="hk", base_url="https://b.com")
        sis.connect.trasferisci = lambda a, m, c, rf: "tr_" + os.urandom(3).hex()
        return sis, r, reg

    @staticmethod
    def _g(r):
        def g(m, p, b=None, h=None):
            return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})
        return g

    def _host_vecchio(self, sis, r, reg, *, con_dati_fiscali):
        g = self._g(r)
        oggi = datetime.date.today()
        _, c = g("POST", "/api/host/registrazione",
                 {"email": "big@x.it", "password": "password1", "accetta_termini": True,
                  "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                  "versione": CONTRATTO_HOST_VERSIONE})
        tok, hid = c["token"], c["host_id"]
        con = sqlite3.connect(reg)                    # invecchia -> 10% commissione
        con.execute("UPDATE host SET creato_ts=? WHERE host_id=?",
                    (int(time.time()) - 400 * 86400, hid))
        con.commit(); con.close()
        sis.registro_host.imposta_stripe_account(hid, "acct_big")
        if con_dati_fiscali:
            g("POST", "/api/host/dati_fiscali",
              {"codice_fiscale": "CFXX", "indirizzo_fiscale": "Via 1", "paese": "IT",
               "iban": "IT60X0542811101000000123456"}, {"X-Host-Token": tok})
        g("POST", "/api/host/pubblica",
          {"slug": "big", "titolo": "B", "citta": "Roma", "valuta": "EUR",
           "prezzo_notte_cents": 50000, "capacita": 4}, {"X-Host-Token": tok})
        g("POST", "/api/host/disponibilita_range",
          {"alloggio_id": "big", "da": oggi.isoformat(),
           "a": (oggi + datetime.timedelta(days=120)).isoformat(),
           "unita_totali": 9, "prezzo_netto_cents": 50000}, {"X-Host-Token": tok})
        # 6 soggiorni ~1000 EUR -> >2000 -> host REPORTABILE
        comm_vero = netto_vero = guest_vero = 0
        for i in range(6):
            ci = (oggi + datetime.timedelta(days=3 + i * 5)).isoformat()
            co = (oggi + datetime.timedelta(days=5 + i * 5)).isoformat()
            _, q = g("POST", "/api/concierge/quote",
                     {"alloggio_id": "big", "check_in": ci, "check_out": co, "party": 2})
            _, b = g("POST", "/api/concierge/book",
                     {"quote_token": q["quote_token"], "email": "c%d@x.it" % i})
            rif, vt = b["riferimento"], b["voucher_token"]
            pl = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"metadata": {"riferimento": rif}}}})
            r.gestisci("POST", "/api/payments/webhook", {}, pl,
                       {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
            g("POST", "/api/garanzia/conferma", {"voucher_token": vt})
            dj = json.loads(sis.pagamenti_pendenti.info(rif).get("corpo_json") or "{}")
            comm_vero += int(dj["commissione_cents"]) + int(dj["costo_pagamento_cents"])
            netto_vero += int(dj["netto_host_cents"])
            guest_vero += int(dj["totale_cents"]) - int(dj["tassa_soggiorno_cents"])
        return hid, comm_vero, netto_vero, guest_vero

    def test_commissione_corretta_con_payout_in_hold(self):
        """Host reportabile SENZA dati fiscali -> payout in hold -> il report deve comunque
        dichiarare la commissione VERA (non il lordo pieno)."""
        sis, r, reg = self._build()
        hid, comm_vero, netto_vero, guest_vero = self._host_vecchio(
            sis, r, reg, con_dati_fiscali=False)
        agg = sis.finanza.aggrega_dac7(datetime.date.today().year).get(hid, {})
        # senza il fix: commissioni sarebbe ~lordo (513000); col fix == comm vera
        self.assertEqual(int(agg.get("commissioni", -1)), comm_vero,
                         "commissioni DAC7 gonfiate col payout in hold")
        self.assertEqual(int(agg.get("netto", -1)), netto_vero,
                         "netto host DAC7 sottostimato col payout in hold")
        self.assertEqual(int(agg.get("lordo", -1)), guest_vero)
        self.assertTrue(sis.finanza.verifica_catena().get("ok"), "catena hash rotta")

    def test_stessa_commissione_con_o_senza_hold(self):
        """La commissione dichiarata NON deve dipendere dal fatto che il bonifico sia
        partito o sia in hold: stesso identico numero."""
        sis1, r1, reg1 = self._build()
        hid1, comm1, netto1, _ = self._host_vecchio(sis1, r1, reg1, con_dati_fiscali=True)
        a1 = sis1.finanza.aggrega_dac7(datetime.date.today().year).get(hid1, {})
        sis2, r2, reg2 = self._build()
        hid2, comm2, netto2, _ = self._host_vecchio(sis2, r2, reg2, con_dati_fiscali=False)
        a2 = sis2.finanza.aggrega_dac7(datetime.date.today().year).get(hid2, {})
        self.assertEqual(int(a1["commissioni"]), int(a2["commissioni"]),
                         "la commissione DAC7 cambia se il payout e' in hold (non deve!)")
        self.assertEqual(int(a1["netto"]), int(a2["netto"]))

    def test_webhook_replay_non_raddoppia_commissione(self):
        """Idempotenza: il retry del webhook non deve scrivere due righe 'commissione'."""
        sis, r, reg = self._build()
        g = self._g(r)
        oggi = datetime.date.today()
        _, c = g("POST", "/api/host/registrazione",
                 {"email": "h@x.it", "password": "password1", "accetta_termini": True,
                  "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                  "versione": CONTRATTO_HOST_VERSIONE})
        tok = c["token"]
        con = sqlite3.connect(reg)
        con.execute("UPDATE host SET creato_ts=? WHERE host_id=?",
                    (int(time.time()) - 400 * 86400, c["host_id"]))
        con.commit(); con.close()
        g("POST", "/api/host/pubblica",
          {"slug": "h", "titolo": "H", "citta": "Roma", "valuta": "EUR",
           "prezzo_notte_cents": 20000, "capacita": 4}, {"X-Host-Token": tok})
        g("POST", "/api/host/disponibilita_range",
          {"alloggio_id": "h", "da": oggi.isoformat(),
           "a": (oggi + datetime.timedelta(days=20)).isoformat(),
           "unita_totali": 3, "prezzo_netto_cents": 20000}, {"X-Host-Token": tok})
        ci = (oggi + datetime.timedelta(days=3)).isoformat()
        co = (oggi + datetime.timedelta(days=5)).isoformat()
        _, q = g("POST", "/api/concierge/quote",
                 {"alloggio_id": "h", "check_in": ci, "check_out": co, "party": 2})
        _, b = g("POST", "/api/concierge/book",
                 {"quote_token": q["quote_token"], "email": "z@x.it"})
        rif = b["riferimento"]
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        for _ in range(4):                       # replay x4
            r.gestisci("POST", "/api/payments/webhook", {}, pl,
                       {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        righe = [m for m in sis.finanza.movimenti(rif) if m["tipo"] == "commissione"]
        self.assertEqual(len(righe), 1, "commissione raddoppiata dal replay del webhook")


if __name__ == "__main__":
    unittest.main(verbosity=2)
