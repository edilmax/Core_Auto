# -*- coding: utf-8 -*-
"""SECURITY (audit resilienza comp.2 - IDOR) — Approva/Rifiuta richiesta su-richiesta.

BUG (fail-open): _decidi_richiesta verificava l'ownership SOLO se rec["host_id"] era
valorizzato. Ma il record della richiesta puo' avere host_id='' (se al book la lookup
dell'alloggio fallisce). In quel caso il controllo era SALTATO -> QUALSIASI host
autenticato poteva approvare/rifiutare una richiesta ALTRUI (bypass di autorizzazione
su azione che muove stato + money-path).

FIX (fail-closed): l'ownership si ri-deriva dall'alloggio della richiesta; per un host
self-service deve coincidere col token, e se non e' confermabile -> DENY.

I test provano: (1) host B NON puo' decidere la richiesta di host A (403 non_tua),
anche col caso vulnerabile host_id='' forzato; (2) host A puo' ancora decidere la sua.
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

WH = "whsec_idor"


def _fake_fetch(url, body, headers):
    return {"url": "https://x/cs", "id": "cs_" + str(time.time_ns())}


class TestIdorRichieste(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def _mk(self):
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

        def registra(email):
            _, c = g("POST", "/api/host/registrazione",
                     {"email": email, "password": "password1", "accetta_termini": True,
                      "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                      "versione": CONTRATTO_HOST_VERSIONE})
            return {"X-Host-Token": c["token"]}
        return sis, g, registra

    def _crea_richiesta_di_A(self, sis, g, HA):
        oggi = datetime.date.today()
        ci = (oggi + datetime.timedelta(days=3)).isoformat()
        co = (oggi + datetime.timedelta(days=5)).isoformat()
        g("POST", "/api/host/pubblica",
          {"slug": "casa-A", "titolo": "Casa A", "citta": "Roma",
           "prezzo_notte_cents": 10000, "capacita": 2,
           "modalita_prenotazione": "su_richiesta"}, HA)
        g("POST", "/api/host/disponibilita_range",
          {"alloggio_id": "casa-A", "da": ci, "a": co,
           "unita_totali": 1, "prezzo_netto_cents": 10000}, HA)
        _, q = g("POST", "/api/concierge/quote",
                 {"alloggio_id": "casa-A", "check_in": ci, "check_out": co, "party": 2})
        _, b = g("POST", "/api/concierge/book",
                 {"quote_token": q["quote_token"], "email": "guest@x.it"})
        # deve essere una richiesta da approvare (su_richiesta)
        self.assertEqual(b.get("stato"), "in_attesa_host", b)
        return b["riferimento"]

    def test_altro_host_non_puo_decidere(self):
        sis, g, registra = self._mk()
        HA, HB = registra("a@idor.it"), registra("b@idor.it")
        ref = self._crea_richiesta_di_A(sis, g, HA)
        # host B (col SUO token) prova ad approvare e rifiutare la richiesta di A
        for azione in ("approva", "rifiuta"):
            st, out = g("POST", "/api/host/richieste/" + azione, {"riferimento": ref}, HB)
            self.assertEqual(st, 403, "IDOR: B ha potuto %s la richiesta di A -> %s" % (azione, out))
            self.assertEqual(out.get("errore"), "non_tua")
        # la richiesta e' ancora VIVA (B non l'ha toccata)
        self.assertEqual(sis.pagamenti_pendenti.info(ref)["stato"], "in_attesa_host")

    def test_caso_vulnerabile_host_id_vuoto(self):
        # il buco vero: record con host_id='' (lookup fallita al book). PRIMA passava; ORA
        # l'owner si ri-deriva dall'alloggio (casa-A e' di A) -> B resta 403.
        sis, g, registra = self._mk()
        HA, HB = registra("a2@idor.it"), registra("b2@idor.it")
        ref = self._crea_richiesta_di_A(sis, g, HA)
        # forza lo scenario: azzera l'host_id memorizzato sulla richiesta
        con = sis.pagamenti_pendenti._apri()
        try:
            with con:
                con.execute("UPDATE pendenti SET host_id='' WHERE riferimento=?", (ref,))
        finally:
            con.close()
        self.assertEqual(sis.pagamenti_pendenti.info(ref).get("host_id"), "")
        st, out = g("POST", "/api/host/richieste/approva", {"riferimento": ref}, HB)
        self.assertEqual(st, 403, "IDOR fail-open: host_id vuoto -> B ha deciso richiesta altrui")
        self.assertEqual(out.get("errore"), "non_tua")
        self.assertEqual(sis.pagamenti_pendenti.info(ref)["stato"], "in_attesa_host")

    def test_proprietario_puo_ancora_decidere(self):
        # NON-REGRESSIONE: A approva la SUA richiesta -> ok (link Stripe generato)
        sis, g, registra = self._mk()
        HA = registra("a3@idor.it")
        ref = self._crea_richiesta_di_A(sis, g, HA)
        st, out = g("POST", "/api/host/richieste/approva", {"riferimento": ref}, HA)
        self.assertEqual(st, 200, "il proprietario deve poter approvare -> %s" % out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
