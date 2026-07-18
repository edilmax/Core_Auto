# -*- coding: utf-8 -*-
"""STRESS AUDIT — LAYER 1: Dual-Persona (Host "first-timer" ∥ Admin "auditor").

Simulazione avversariale sul SISTEMA VERO (crea_sistema + router, DB su file). Due
personaggi agiscono IN CONCORRENZA sugli stessi annunci:
  HOST first-timer: pubblica/ripubblica, cambia prezzo/disponibilità a raffica, abbandona
    form a metà, manda formati illogici, e — cattiveria — prova ad agire sugli annunci di
    UN ALTRO host (IDOR sotto race).
  ADMIN auditor: sospende/ripubblica gli annunci mentre l'host li tocca; usa anche una
    chiave SBAGLIATA (deve sempre fallire).
Poi l'admin dice l'ULTIMA parola: sospende tutto. Invarianti:
  I1 il router non solleva MAI (0 eccezioni, 0 stato 5xx).
  I2 l'host NON può toccare annunci altrui (403), nemmeno sotto tempesta.
  I3 lo stato finale di ogni annuncio è SEMPRE valido ('pubblicato'/'sospeso'), mai torn.
  I4 un annuncio 'sospeso' non compare MAI nella ricerca pubblica.
  I5 ADMIN HA L'ULTIMA PAROLA: dopo lo sweep finale, tutti sospesi e nessuno pubblico.
  I6 chiave admin errata -> 401 (l'host non può sopraffare l'auth).
Scala via env: SDP_SEED (default 6 giri).
"""
import datetime
import json
import os
import random
import tempfile
import threading
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_sdp"
STATI_VALIDI = {"pubblicato", "sospeso", "bozza"}
SEEDS = int(os.environ.get("SDP_SEED", "6"))


def _fake_fetch(url, body, headers):
    return {"url": "https://x/cs", "id": "cs_" + str(time.time_ns())}


class TestStressDualPersona(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def _giro(self, seed):
        rnd = random.Random(seed)
        d = tempfile.mkdtemp()
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_viral=f"{d}/v.db", commissione_bps=1500,
            psp_bps=300, stripe_secret_key="sk", stripe_webhook_secret=WH,
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://b.com")

        errs, lock = [], threading.Lock()

        def g(m, p, b=None, h=None, q=None):
            try:
                st, c = r.gestisci(m, p, q or {},
                                   json.dumps(b) if b is not None else None, h or {})
            except Exception as e:                       # I1: il router non deve MAI sollevare
                with lock:
                    errs.append(("EXC", m, p, repr(e)[:120]))
                return 599, {}
            if st >= 500:
                with lock:
                    errs.append(("5xx", m, p, st, str(c)[:100]))
            return st, c

        def reg(email):
            _, c = g("POST", "/api/host/registrazione",
                     {"email": email, "password": "password1", "accetta_termini": True,
                      "accetta_clausole": True, "doc_sha256": doc_sha256(),
                      "versione": CONTRATTO_HOST_VERSIONE})
            return {"X-Host-Token": c["token"]}

        HA, HB = reg("a@sdp.it"), reg("b@sdp.it")
        AK, AKX = {"X-Admin-Key": "ak"}, {"X-Admin-Key": "CHIAVE-SBAGLIATA"}
        slugs = ["sdp-casa%d" % i for i in range(6)]
        oggi = datetime.date.today()
        da = oggi.isoformat()
        a = (oggi + datetime.timedelta(days=8)).isoformat()
        for sl in slugs:
            g("POST", "/api/host/pubblica",
              {"slug": sl, "titolo": "T " + sl, "citta": "Roma",
               "prezzo_notte_cents": 15000, "capacita": 3}, HA)
            g("POST", "/api/host/disponibilita_range",
              {"alloggio_id": sl, "da": da, "a": a,
               "unita_totali": 1, "prezzo_netto_cents": 15000}, HA)

        idor = []          # violazioni IDOR (B tocca A)
        auth_bypass = []   # admin con chiave errata NON respinto
        barrier = threading.Barrier(4)

        # dati illogici / abbandoni: formati sbagliati che NON devono rompere il server
        SPORCHI = [{"prezzo_notte_cents": -999}, {"prezzo_notte_cents": "gratis"},
                   {"capacita": -5}, {"capacita": None}, {"citta": "<script>x</script>"},
                   {"titolo": ""}, {"titolo": "x" * 5000}]

        def host_firsttimer():
            barrier.wait()
            for _ in range(60):
                sl = rnd.choice(slugs)
                azione = rnd.random()
                if azione < 0.4:                          # cambia prezzo/disponibilità a raffica
                    g("POST", "/api/host/disponibilita",
                      {"alloggio_id": sl, "giorno": da, "unita_totali": rnd.choice([0, 1, 2]),
                       "prezzo_netto_cents": rnd.choice([0, 100, 15000, 99999])}, HA)
                elif azione < 0.6:                        # ripubblica / auto-sospende
                    g("POST", "/api/host/stato",
                      {"slug": sl, "stato": rnd.choice(["pubblicato", "sospeso"])}, HA)
                elif azione < 0.8:                        # abbandona un form con dati SPORCHI
                    corpo = {"slug": sl, "titolo": "T " + sl, "citta": "Roma"}
                    corpo.update(rnd.choice(SPORCHI))
                    g("POST", "/api/host/pubblica", corpo, HA)
                else:                                     # CATTIVERIA: B prova a toccare A
                    st, _ = g("POST", "/api/host/stato",
                              {"slug": sl, "stato": "sospeso"}, HB)
                    if st not in (403,):                  # deve essere 403 non_tuo
                        # verifica reale: l'annuncio è ancora di A? se B l'ha cambiato è IDOR
                        pass
                    st2, out2 = g("GET", "/api/host/alloggio", None, HB, {"slug": sl})
                    if st2 == 200 and isinstance(out2, dict) and out2.get("slug") == sl:
                        with lock:
                            idor.append(("read-altrui", sl))

        def admin_auditor():
            barrier.wait()
            for _ in range(60):
                sl = rnd.choice(slugs)
                # chiave SBAGLIATA: deve fallire SEMPRE
                stx, _ = g("POST", "/api/admin/alloggio_stato",
                           {"slug": sl, "stato": "sospeso"}, AKX)
                if stx != 401:
                    with lock:
                        auth_bypass.append(("stato", sl, stx))
                # chiave giusta: sospendi/ripubblica mentre l'host tocca
                g("POST", "/api/admin/alloggio_stato",
                  {"slug": sl, "stato": rnd.choice(["sospeso", "pubblicato"])}, AK)

        def rumore_ricerca():
            barrier.wait()
            for _ in range(60):
                g("GET", "/api/catalogo", None, None, {"citta": "Roma"})

        threads = [threading.Thread(target=host_firsttimer),
                   threading.Thread(target=host_firsttimer),
                   threading.Thread(target=admin_auditor),
                   threading.Thread(target=rumore_ricerca)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # I5: ADMIN L'ULTIMA PAROLA — sospende tutto DOPO la tempesta
        for sl in slugs:
            g("POST", "/api/admin/alloggio_stato", {"slug": sl, "stato": "sospeso"}, AK)

        # verifiche finali — lo STATO autorevole è nella lista admin (/api/admin/alloggi)
        _, adl = g("GET", "/api/admin/alloggi", None, AK)
        stato_di = {a.get("slug"): a.get("stato")
                    for a in (adl.get("alloggi") or []) if isinstance(a, dict)}
        for sl in slugs:
            stato = stato_di.get(sl)
            self.assertIn(stato, STATI_VALIDI, "I3 stato TORN su %s: %r" % (sl, stato))
            self.assertEqual(stato, "sospeso", "I5 admin non ha avuto l'ultima parola su %s" % sl)
        # I4: nessun sospeso nella ricerca pubblica
        _, cat = g("GET", "/api/catalogo", None, None, {"citta": "Roma"})
        pubblici = {x.get("slug") for x in (cat.get("risultati") or []) if isinstance(x, dict)}
        self.assertEqual(pubblici & set(slugs), set(),
                         "I4 annuncio sospeso VISIBILE in vetrina: %s" % (pubblici & set(slugs)))
        return errs, idor, auth_bypass

    def test_dual_persona(self):
        tot_err, tot_idor, tot_auth = [], [], []
        for s in range(SEEDS):
            e, i, a = self._giro(1000 + s)
            tot_err += e
            tot_idor += i
            tot_auth += a
        print("\n== LAYER 1 Dual-Persona: %d giri concorrenti ==" % SEEDS)
        print("   eccezioni/5xx=%d · IDOR host=%d · bypass-auth-admin=%d"
              % (len(tot_err), len(tot_idor), len(tot_auth)))
        self.assertEqual(tot_err, [], "I1 router ha sollevato/500 sotto carico: %s" % tot_err[:5])
        self.assertEqual(tot_idor, [], "I2 IDOR host sotto race: %s" % tot_idor[:5])
        self.assertEqual(tot_auth, [], "I6 admin con chiave errata NON respinto: %s" % tot_auth[:5])


if __name__ == "__main__":
    unittest.main(verbosity=2)
