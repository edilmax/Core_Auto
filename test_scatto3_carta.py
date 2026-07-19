# -*- coding: utf-8 -*-
"""SCATTO ③ — carta host off-session (fase183). Il provider e' fetch-iniettabile: qui si
provano gli esiti con uno Stripe FINTO, senza toccare la rete ne' muovere denaro vero.

Invarianti:
  - salvataggio carta (webhook mode=setup) -> customer+pm salvati sull'host;
  - addebito RIUSCITO -> debito saldato + UNA riga 'penale_incassata' a giornale;
  - IDEMPOTENZA: ritentare lo stesso addebito NON raddoppia (giornale + Stripe idem-key);
  - carta RIFIUTATA -> debito resta 'aperto' + backoff (tentativi++/prossimo_ts), MAI saldato;
  - SCA (requires_action) -> debito aperto, nessun incasso segnato;
  - GATE: senza SCATTO3_ATTIVO lo sweep NON addebita (dormiente);
  - catena hash del giornale integra.
"""
import json
import os
import unittest

from fase177_financial_controller import crea_financial_controller
from fase183_carta_offsession import ProviderCarta


class _StripeFinto:
    """Fetch finto: registra le chiamate e risponde a piacere (succeeded/declined/SCA)."""
    def __init__(self, esito="succeeded"):
        self.esito = esito
        self.chiamate = []
        self.idem_visti = {}

    def __call__(self, metodo, url, body, headers):
        self.chiamate.append((metodo, url))
        if url.endswith("/payment_intents"):
            idem = headers.get("Idempotency-Key", "")
            # Stripe: stessa idem-key -> stessa risposta (dedup), un solo "addebito"
            if idem and idem in self.idem_visti:
                return self.idem_visti[idem]
            if self.esito == "succeeded":
                r = {"id": "pi_" + os.urandom(3).hex(), "status": "succeeded"}
            elif self.esito == "declined":
                r = {"error": {"code": "card_declined", "type": "card_error"}}
            elif self.esito == "sca":
                r = {"error": {"code": "authentication_required",
                               "payment_intent": {"id": "pi_sca"}}}
            else:
                r = {"status": "processing", "id": "pi_x"}
            if idem:
                self.idem_visti[idem] = r
            return r
        return {}


class TestScatto3Carta(unittest.TestCase):
    def setUp(self):
        self.fc = crea_financial_controller(":memory:")
        self.fc.inizializza_schema()
        # crea un debito 'aperto' scoperto: emette ND penale, nessun payout da cui offset
        class _NoPayout:
            def elenca(self, *a, **k):
                return []
        self.fc.processa_penale(riferimento="RIF1", host_id="h1", penale_cents=5000,
                                valuta="EUR", payout=_NoPayout())
        aperti = self.fc.debiti_host("h1", stato="aperto")
        self.assertEqual(len(aperti), 1)
        self.assertEqual(aperti[0]["residuo_cents"], 5000)

    def _prov(self, esito):
        return ProviderCarta("sk", fetch=_StripeFinto(esito))

    def test_addebito_riuscito_salda_e_giornale(self):
        r = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=self._prov("succeeded"),
                                      customer="cus_1", payment_method="pm_1")
        self.assertEqual(r["debiti_saldati"], 1)
        self.assertEqual(r["incassati_cents"], 5000)
        self.assertEqual(self.fc.debiti_host("h1", stato="aperto"), [])
        movs = self.fc.movimenti("RIF1")
        inc = [m for m in movs if m["tipo"] == "penale_incassata"]
        self.assertEqual(len(inc), 1)
        self.assertEqual(int(inc[0]["importo_cents"]), 5000)
        self.assertTrue(self.fc.verifica_catena().get("ok"))

    def test_idempotente_non_raddoppia(self):
        prov = self._prov("succeeded")
        self.fc.riscuoti_da_carta(host_id="h1", provider_carta=prov,
                                  customer="cus_1", payment_method="pm_1")
        # ritento (es. sweep ripetuto): il debito e' gia' saldato -> nessun nuovo addebito
        r2 = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=prov,
                                       customer="cus_1", payment_method="pm_1")
        self.assertEqual(r2["debiti_saldati"], 0)
        inc = [m for m in self.fc.movimenti("RIF1") if m["tipo"] == "penale_incassata"]
        self.assertEqual(len(inc), 1, "penale_incassata raddoppiata")

    def test_carta_rifiutata_resta_aperto_e_backoff(self):
        r = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=self._prov("declined"),
                                      customer="cus_1", payment_method="pm_1")
        self.assertEqual(r["falliti"], 1)
        self.assertEqual(r["debiti_saldati"], 0)
        aperti = self.fc.debiti_host("h1", stato="aperto")
        self.assertEqual(len(aperti), 1, "il debito NON deve sparire su carta rifiutata")
        self.assertEqual(aperti[0]["residuo_cents"], 5000)
        self.assertEqual(int(aperti[0]["tentativi"]), 1)
        self.assertTrue(int(aperti[0]["prossimo_ts"]) > 0)
        self.assertEqual([m for m in self.fc.movimenti("RIF1")
                          if m["tipo"] == "penale_incassata"], [],
                         "nessun incasso a giornale se la carta e' rifiutata")

    def test_sca_richiede_azione_niente_incasso(self):
        r = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=self._prov("sca"),
                                      customer="cus_1", payment_method="pm_1")
        self.assertEqual(r["richiede_azione"], 1)
        self.assertEqual(r["debiti_saldati"], 0)
        self.assertEqual(len(self.fc.debiti_host("h1", stato="aperto")), 1)

    def test_senza_carta_non_addebita(self):
        r = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=self._prov("succeeded"),
                                      customer="", payment_method="")
        self.assertEqual(r["incassati_cents"], 0)
        self.assertEqual(len(self.fc.debiti_host("h1", stato="aperto")), 1)

    def test_backoff_blocca_ritentativo_immediato(self):
        prov = self._prov("declined")
        self.fc.riscuoti_da_carta(host_id="h1", provider_carta=prov,
                                  customer="cus_1", payment_method="pm_1")
        # subito dopo (stesso istante) il backoff impedisce un nuovo tentativo
        prov2 = _StripeFinto("succeeded")
        r2 = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=ProviderCarta("sk", fetch=prov2),
                                       customer="cus_1", payment_method="pm_1")
        self.assertEqual(r2["debiti_saldati"], 0, "il backoff deve saltare il ritentativo")
        self.assertEqual([c for c in prov2.chiamate if c[1].endswith("/payment_intents")], [],
                         "non deve nemmeno chiamare Stripe durante il backoff")

    def test_addebito_provider_shape(self):
        """Il provider costruisce la richiesta giusta e mappa gli esiti."""
        prov = ProviderCarta("sk", fetch=_StripeFinto("succeeded"))
        out = prov.addebita(customer="cus_1", payment_method="pm_1", importo_cents=5000,
                            valuta="EUR", riferimento="RIF1", idem="carta:x:5000")
        self.assertEqual(out["stato"], "riuscito")
        out2 = prov.addebita(customer="", payment_method="pm_1", importo_cents=5000,
                             valuta="EUR", riferimento="RIF1")
        self.assertEqual(out2["stato"], "config")


class TestScatto3Router(unittest.TestCase):
    """Integrazione via router: webhook salva-carta + endpoint host + sweep GATED."""
    def _build(self):
        import datetime
        import tempfile
        import fase85_pagamenti_stripe as _stripe
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase83_server import crea_router
        from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
        _stripe.ProviderStripe._fetch_reale = staticmethod(
            lambda u, b, h: {"url": "x", "id": "cs_x"})
        d = tempfile.mkdtemp()
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_finanza=f"{d}/f.db",
            commissione_bps=1000, psp_bps=300, stripe_secret_key="sk",
            stripe_webhook_secret="whx", stripe_success_url="x", stripe_cancel_url="x"))
        r = crea_router(sis, host_key="hk", base_url="https://b.com")
        # carta provider FINTO (niente rete): salva-carta e addebito deterministici
        finto = _StripeFinto("succeeded")

        class _CartaFinta(ProviderCarta):
            def crea_link_carta(self, *, host_id, email=""):
                return "https://checkout.stripe/setup/" + host_id

            def dettagli_da_sessione(self, sid):
                return {"customer": "cus_" + sid[-4:], "payment_method": "pm_" + sid[-4:]}
        sis.carta = _CartaFinta("sk", fetch=finto)
        _, c = r.gestisci("POST", "/api/host/registrazione", {}, json.dumps(
            {"email": "h@c.it", "password": "password1", "accetta_termini": True,
             "accetta_clausole": True, "doc_sha256": doc_sha256(),
             "versione": CONTRATTO_HOST_VERSIONE}), {})
        return sis, r, c["token"], c["host_id"]

    def test_webhook_setup_salva_carta(self):
        import time
        from fase87_stripe_webhook import firma_di_test
        sis, r, tok, hid = self._build()
        obj = {"id": "cs_setup_9999", "mode": "setup",
               "metadata": {"host_id": hid, "scopo": "mandato_penale_offsession"}}
        pl = json.dumps({"type": "checkout.session.completed", "data": {"object": obj}})
        st, out = r.gestisci("POST", "/api/payments/webhook", {}, pl,
                             {"Stripe-Signature": firma_di_test(pl, "whx", int(time.time()))})
        self.assertEqual(st, 200)
        info = sis.registro_host.info_host(hid)
        self.assertTrue(info["stripe_customer_id"].startswith("cus_"))
        self.assertTrue(info["stripe_payment_method"].startswith("pm_"))

    def test_host_carta_link_da_mandato(self):
        sis, r, tok, hid = self._build()
        st, out = r.gestisci("POST", "/api/host/carta_link", {}, None,
                             {"X-Host-Token": tok})
        self.assertEqual(st, 200, out)
        self.assertIn("checkout.stripe", out["url"])
        self.assertIn("Autorizzo BookinVIP", out["mandato"])

    def test_sweep_gated_dormiente(self):
        import os
        sis, r, tok, hid = self._build()
        os.environ.pop("SCATTO3_ATTIVO", None)
        self.assertEqual(r.riscuoti_debiti_carta().get("saltato"), "non_attivo")

    def test_sweep_attivo_incassa(self):
        import os
        sis, r, tok, hid = self._build()
        # carta salvata + debito scoperto
        sis.registro_host.imposta_carta(hid, "cus_1", "pm_1")
        class _NoPayout:
            def elenca(self, *a, **k):
                return []
        sis.finanza.processa_penale(riferimento="R1", host_id=hid, penale_cents=3000,
                                    valuta="EUR", payout=_NoPayout())
        os.environ["SCATTO3_ATTIVO"] = "1"
        try:
            esito = r.riscuoti_debiti_carta()
        finally:
            os.environ.pop("SCATTO3_ATTIVO", None)
        self.assertEqual(esito.get("saldati"), 1, esito)
        self.assertEqual(sis.finanza.debiti_host(hid, stato="aperto"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
