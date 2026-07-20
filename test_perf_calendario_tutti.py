# -*- coding: utf-8 -*-
"""PERF (compartimento 1) — la vista calendario multi-alloggio non deve piu' essere N+1.

Prima: /api/host/calendario_tutti apriva UNA connessione SQLite + UNA query sui pendenti
PER OGNI alloggio (attivi_per_alloggio in un ciclo) -> 20 alloggi = 20 connessioni.
Ora: UNA sola query bulk (attivi_multi) per tutti gli slug -> 1 connessione.
Il test conta le aperture di connessione sullo store pendenti (fase162._apri) e prova
che il colore del calendario (giorni 'in_trattativa') e' IDENTICO ai due percorsi.
"""
import datetime
import json
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_perf"
N_ALLOGGI = 20


def _fake_fetch(url, body, headers):
    return {"url": "https://x/cs", "id": "cs_" + str(time.time_ns())}


class TestPerfCalendarioTutti(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def _setup(self):
        d = tempfile.mkdtemp()
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_viral=f"{d}/v.db", commissione_bps=1500,
            psp_bps=300, stripe_secret_key="sk", stripe_webhook_secret=WH,
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        r = crea_router(sis, host_key="hk", base_url="https://b.com")

        def g(m, p, b=None, h=None, q=None):
            return r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

        _, c = g("POST", "/api/host/registrazione",
                 {"email": "perf@ct.it", "password": "password1", "accetta_termini": True,
                  "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                  "versione": CONTRATTO_HOST_VERSIONE})
        H = {"X-Host-Token": c["token"]}
        oggi = datetime.date.today()
        self.da = oggi.isoformat()
        self.a = (oggi + datetime.timedelta(days=6)).isoformat()
        self.ci = (oggi + datetime.timedelta(days=1)).isoformat()
        self.co = (oggi + datetime.timedelta(days=2)).isoformat()
        slugs = ["perf-casa%d" % i for i in range(N_ALLOGGI)]
        for sl in slugs:
            g("POST", "/api/host/pubblica",
              {"slug": sl, "titolo": "P " + sl, "citta": "Roma",
               "prezzo_notte_cents": 10000, "capacita": 2}, H)
            g("POST", "/api/host/disponibilita_range",
              {"alloggio_id": sl, "da": self.da, "a": self.a,
               "unita_totali": 1, "prezzo_netto_cents": 10000}, H)
        # un HOLD VIVO su perf-casa0 (quote+book, senza pagare): giorno -> in_trattativa
        _, q = g("POST", "/api/concierge/quote",
                 {"alloggio_id": "perf-casa0", "check_in": self.ci,
                  "check_out": self.co, "party": 2})
        g("POST", "/api/concierge/book", {"quote_token": q["quote_token"], "email": "x@ct.it"})
        return sis, g, H

    def _conta_apri(self, sis, g, H, batch):
        pp = sis.pagamenti_pendenti
        orig_apri = pp._apri
        n = {"apri": 0}

        def contato():
            n["apri"] += 1
            return orig_apri()
        pp._apri = contato
        salvato = None
        try:
            if not batch:
                salvato = pp.attivi_multi
                pp.attivi_multi = None      # callable(None) False -> il server ricade sul per-slug
            _, out = g("GET", "/api/host/calendario_tutti", None, H,
                       {"da": self.da, "a": self.a})
        finally:
            pp._apri = orig_apri
            if salvato is not None:
                pp.attivi_multi = salvato
        # estrai i giorni colorati in_trattativa (per la prova di NON regressione)
        tratt = set()
        for al in out.get("alloggi", []):
            for gg in al.get("giorni", []):
                if isinstance(gg, dict) and gg.get("stato") == "in_trattativa":
                    tratt.add((al["slug"], gg["giorno"]))
        return n["apri"], tratt

    def test_batch_azzera_nplus1_e_non_regredisce(self):
        sis, g, H = self._setup()
        apri_old, tratt_old = self._conta_apri(sis, g, H, batch=False)
        apri_new, tratt_new = self._conta_apri(sis, g, H, batch=True)
        print("\n== PERF calendario_tutti (%d alloggi): connessioni pendenti OLD=%d -> NEW=%d =="
              % (N_ALLOGGI, apri_old, apri_new))
        print("   giorni 'in_trattativa': OLD=%d NEW=%d (identici=%s)"
              % (len(tratt_old), len(tratt_new), tratt_old == tratt_new))
        # BEFORE: una connessione per alloggio (~20)
        self.assertEqual(apri_old, N_ALLOGGI, "atteso il vecchio costo N+1")
        # AFTER: una sola query bulk
        self.assertEqual(apri_new, 1, "il batch deve aprire UNA sola connessione pendenti")
        # NESSUNA REGRESSIONE: colorazione identica, e l'hold c'e' davvero
        self.assertEqual(tratt_old, tratt_new, "colorazione calendario cambiata (regressione!)")
        self.assertTrue(any(s == "perf-casa0" for s, _ in tratt_new),
                        "l'hold vivo deve risultare in_trattativa")


if __name__ == "__main__":
    unittest.main(verbosity=2)
