"""Collaudo BUG #18+#19 (2026-07-16, metodo libro - controversia/cancellazione LATO SOLDI).

#18 SPLIT PARZIALE controversia: il transfer Connect partiva con la quota host GIUSTA ma
    il ledger payout restava all'importo PIENO -> dashboard host gonfiata e, per i bonifici
    MANUALI fatti da `da_pagare`, all'host arrivava ANCHE la quota appena rimborsata
    all'ospite (perdita reale, stessa classe del bug 'rimborso admin pagava anche l'host').

#19 CANCELLAZIONE ospite CON PENALE (politica rigida): l'escrow decideva host_riceve>0
    (la penale e' DELL'HOST) ma il payout finiva 'trattenuto' PIENO (= "non incassi
    niente") e NESSUN bonifico partiva mai (l'auto-rilascio guarda solo 'in_garanzia')
    -> la quota dell'host restava alla piattaforma, invisibile a tutti.

Fix: fase131.imposta_importo (riallinea il ledger alla quota DECISA) + fase83:
controversia parziale -> imposta_importo+transfer della quota; cancellazione -> chiusura
escrow PRIMA, poi quota host: imposta_importo+transfer (prima di marca_da_rimborsare,
il transfer esige il pendente 'pagato'); nessuna quota -> trattenuto come prima.
"""
import datetime
import json
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

AK = {"X-Admin-Key": "ak"}


class ConnectFinto:
    def __init__(self):
        self.transfers = []

    def trasferisci(self, acct, amount, currency, rif):
        self.transfers.append((acct, amount, currency, rif))
        return "tr_%d" % len(self.transfers)


class TestSplitPenalePayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(
            lambda u, b, h: {"url": "https://checkout.stripe.test/cs", "id": "cs_1"})

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db",
            db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db", db_garanzia=f"{d}/g.db",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_x", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.fc = ConnectFinto()
        self.sis.connect = self.fc
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@sp.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.hid, self.tok = c["host_id"], c["token"]
        self.sis.registro_host.imposta_stripe_account(self.hid, "acct_test")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None,
                               h or {})

    def _pubblica(self, slug, politica="flessibile"):
        oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": slug, "titolo": "Casa SP", "citta": "Roma",
                "prezzo_notte_cents": 10000, "capacita": 2,
                "politica_cancellazione": politica}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": slug, "da": oggi.isoformat(),
                "a": (oggi + datetime.timedelta(days=60)).isoformat(),
                "unita_totali": 1, "prezzo_netto_cents": 10000}, {"X-Host-Token": self.tok})

    def _book_paga(self, slug, giorni_all_arrivo=30):
        oggi = datetime.date.today()
        ci = (oggi + datetime.timedelta(days=giorni_all_arrivo)).isoformat()
        co = (oggi + datetime.timedelta(days=giorni_all_arrivo + 2)).isoformat()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": slug, "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@sp.it"})
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata":
                                                  {"riferimento": b["riferimento"]}}}})
        sig = firma_di_test(payload, "whsec_x", int(time.time()))
        self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                        {"Stripe-Signature": sig})
        self.assertEqual(self.sis.pagamenti_pendenti.info(b["riferimento"])["stato"],
                         "pagato")
        return b

    def _netto(self, ref):
        return self.sis.garanzia.stato(ref)["importo_host_cents"]

    def test_split_parziale_ledger_e_transfer_alla_quota_host(self):
        self._pubblica("casa-a")
        b = self._book_paga("casa-a")
        ref, netto = b["riferimento"], self._netto(b["riferimento"])
        s, _ = self.g("POST", "/api/garanzia/contesta",
                      {"voucher_token": b["voucher_token"], "motivo": "muffa"})
        self.assertEqual(s, 200)
        s, c = self.g("POST", "/api/admin/controversia/risolvi",
                      {"riferimento": ref, "percentuale_ospite": 40}, AK)
        self.assertEqual(s, 200, c)
        quota = netto - netto * 40 // 100
        self.assertEqual(c["va_all_host_cents"], quota)
        # conservazione esatta
        self.assertEqual(c["rimborso_cliente_cents"] + c["va_all_host_cents"], netto)
        # transfer con la QUOTA, non col pieno
        self.assertEqual(self.fc.transfers[-1][1], quota)
        # ledger riallineato: l'host vede la quota vera, non il pieno
        rie = self.sis.payout.riepilogo(self.hid)["EUR"]
        self.assertEqual(rie.get("in_transito", 0), quota)
        self.assertEqual(self.sis.payout.da_pagare(self.hid, "EUR"), quota)

    def test_split_parziale_senza_connect_da_pagare_giusto(self):
        self.sis.connect = None                       # bonifico manuale da `da_pagare`
        self._pubblica("casa-b")
        b = self._book_paga("casa-b")
        ref, netto = b["riferimento"], self._netto(b["riferimento"])
        self.g("POST", "/api/garanzia/contesta",
               {"voucher_token": b["voucher_token"], "motivo": "x"})
        s, _ = self.g("POST", "/api/admin/controversia/risolvi",
                      {"riferimento": ref, "percentuale_ospite": 40}, AK)
        self.assertEqual(s, 200)
        quota = netto - netto * 40 // 100
        # PRIMA del fix: da_pagare = netto PIENO -> il manuale pagava anche la quota ospite
        self.assertEqual(self.sis.payout.da_pagare(self.hid, "EUR"), quota)

    def test_rimborso_pieno_controversia_payout_rimosso(self):
        self._pubblica("casa-c")
        b = self._book_paga("casa-c")
        ref = b["riferimento"]
        self.g("POST", "/api/garanzia/contesta",
               {"voucher_token": b["voucher_token"], "motivo": "x"})
        s, _ = self.g("POST", "/api/admin/controversia/risolvi",
                      {"riferimento": ref, "percentuale_ospite": 100}, AK)
        self.assertEqual(s, 200)
        self.assertEqual(self.sis.payout.da_pagare(self.hid, "EUR"), 0)
        self.assertEqual(self.fc.transfers, [])       # niente bonifico all'host

    def test_cancellazione_con_penale_paga_la_quota_host(self):
        self._pubblica("casa-d", politica="rigida")
        b = self._book_paga("casa-d", giorni_all_arrivo=2)   # rigida+vicino: penale piena
        ref, netto = b["riferimento"], self._netto(b["riferimento"])
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, c)
        self.assertEqual(c["rimborso_soggiorno_cents"], 0)   # rigida a 2 giorni: 0 all'ospite
        st = self.sis.garanzia.stato(ref)
        self.assertEqual(st["stato"], "risolto")
        self.assertEqual(st["host_riceve_cents"], netto)
        # PRIMA del fix: payout 'trattenuto' pieno e NESSUN transfer -> host mai pagato
        self.assertEqual(self.sis.payout.stato_di(ref), "in_transito")
        self.assertEqual(self.fc.transfers[-1][1], netto)
        # il tick auto-rilascio NON duplica (escrow gia' 'risolto')
        n_prima = len(self.fc.transfers)
        self.sis.garanzia.auto_rilascia(ora_ts=int(time.time()) + 10 * 86400)
        self.assertEqual(len(self.fc.transfers), n_prima)

    def test_cancellazione_rimborso_pieno_resta_trattenuto(self):
        # NESSUNA regressione: flessibile e lontano -> ospite 100%, host 0, zero transfer
        self._pubblica("casa-e", politica="flessibile")
        b = self._book_paga("casa-e", giorni_all_arrivo=30)
        ref = b["riferimento"]
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, c)
        self.assertEqual(self.sis.payout.stato_di(ref), "trattenuto")
        self.assertEqual(self.fc.transfers, [])
        self.assertEqual(self.sis.garanzia.stato(ref)["stato"], "annullato")

    def test_disputa_aperta_payout_fuori_dal_giro(self):
        # BUG #21: con la disputa APERTA il payout restava 'maturato' -> `da_pagare`
        # lo includeva = il bonifico manuale pagava l'host mentre l'arbitro decideva.
        self._pubblica("casa-g")
        b = self._book_paga("casa-g")
        ref = b["riferimento"]
        self.assertGreater(self.sis.payout.da_pagare(self.hid, "EUR"), 0)
        s, _ = self.g("POST", "/api/garanzia/contesta",
                      {"voucher_token": b["voucher_token"], "motivo": "muffa"})
        self.assertEqual(s, 200)
        self.assertEqual(self.sis.payout.stato_di(ref), "trattenuto")
        self.assertEqual(self.sis.payout.da_pagare(self.hid, "EUR"), 0)
        # l'arbitro decide 60/40 -> la quota host torna PAGABILE (e parte il transfer)
        netto = self._netto(ref)
        s, c = self.g("POST", "/api/admin/controversia/risolvi",
                      {"riferimento": ref, "percentuale_ospite": 40}, AK)
        self.assertEqual(s, 200, c)
        quota = netto - netto * 40 // 100
        self.assertEqual(self.fc.transfers[-1][1], quota)
        self.assertEqual(self.sis.payout.da_pagare(self.hid, "EUR"), quota)

    def test_pagamento_tardivo_la_garanzia_risorge(self):
        # BUG #22: pagamento tardivo (hold scaduto, sweeper: garanzia annullata) su stanza
        # ancora libera -> re-block ok, payout ricreato... ma la garanzia restava
        # 'annullato' (INSERT DO NOTHING non resuscita) = escrow MORTO: conferma/contesta
        # ospite in 409, auto-rilascio mai, host mai pagato in automatico.
        import sqlite3
        from fase83_server import sweep_hold_una_passata
        self._pubblica("casa-h")
        oggi = datetime.date.today()
        ci = (oggi + datetime.timedelta(days=30)).isoformat()
        co = (oggi + datetime.timedelta(days=32)).isoformat()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-h", "check_in": ci, "check_out": co, "party": 2})
        _, bk = self.g("POST", "/api/concierge/book",
                       {"quote_token": q["quote_token"], "email": "cli@sp.it"})
        ref = bk["riferimento"]
        con = sqlite3.connect(f"{self.dir}/p.db")
        with con:
            con.execute("UPDATE pendenti SET scadenza_ts=? WHERE riferimento=?",
                        (int(time.time()) - 5, ref))
        con.close()
        sweep_hold_una_passata(self.sis, self.r)
        self.assertEqual(self.sis.garanzia.stato(ref)["stato"], "annullato")
        # pagamento TARDIVO (link vivo, stanza ancora libera)
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": ref}}}})
        sig = firma_di_test(payload, "whsec_x", int(time.time()))
        self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                        {"Stripe-Signature": sig})
        self.assertEqual(self.sis.pagamenti_pendenti.info(ref)["stato"], "pagato")
        st = self.sis.garanzia.stato(ref)
        self.assertEqual(st["stato"], "in_garanzia", "la garanzia DEVE risorgere")
        # e le tutele rivivono: l'ospite puo' confermare -> transfer all'host
        s, c = self.g("POST", "/api/garanzia/conferma", {"voucher_token": bk["voucher_token"]})
        self.assertEqual(s, 200, c)
        self.assertEqual(self.fc.transfers[-1][3], ref)

    def test_revive_non_tocca_stati_decisi(self):
        # apri() NON deve resuscitare garanzie gia' DECISE (rilasciato/risolto/contestato)
        gz = self.sis.garanzia
        gz.apri("rifZ", 9000)
        gz.contesta("rifZ", "x")
        gz.apri("rifZ", 9000)                        # replay: NON deve riaprire
        self.assertEqual(gz.stato("rifZ")["stato"], "contestato")
        gz.risolvi("rifZ", rimborso_ospite_cents=1000)
        gz.apri("rifZ", 9000)
        self.assertEqual(gz.stato("rifZ")["stato"], "risolto")

    def test_cancellazione_non_pagata_zero_soldi(self):
        # book senza webhook: nessun incasso -> nessuna quota, nessun transfer
        self._pubblica("casa-f", politica="rigida")
        oggi = datetime.date.today()
        ci = (oggi + datetime.timedelta(days=2)).isoformat()
        co = (oggi + datetime.timedelta(days=4)).isoformat()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-f", "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@sp.it"})
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, c)
        self.assertEqual(c["rimborso_cents"], 0)
        self.assertEqual(self.fc.transfers, [])
        self.assertNotEqual(self.sis.payout.stato_di(b["riferimento"]), "in_transito")


if __name__ == "__main__":
    unittest.main(verbosity=2)
