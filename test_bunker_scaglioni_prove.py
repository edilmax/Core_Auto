"""SALA CONTROLLO SUPER-ADMIN: scaglioni · prove legali · tariffa tecnica · dossier
(2026-07-21, dall'audit "il super-admin è cieco").

Cosa mancava prima:
  - nessuna vista degli SCAGLIONI: per sapere a che tariffa stava un host bisognava
    leggere il database a mano; e la rampa era calcolata in DUE punti con parametri
    diversi (motore vs vetrina) -> potevano divergere in silenzio;
  - le PROVE legali (IP, ora, firma HMAC) si vedevano dal pannello operativo con la SOLA
    chiave admin, e nessuno verificava mai che fossero ancora integre;
  - la TARIFFA TECNICA persa sui rimborsi (Stripe non la restituisce) non compariva da
    nessuna parte: perdita reale invisibile al commercialista;
  - nessun export unico con valore probatorio.

Guardie di questo compartimento:
  - FONTE UNICA: il bps mostrato dal Bunker == quello che il motore ADDEBITA (a ogni età).
  - SCAGLIONI: etichetta, giorni al prossimo scatto e DATA del cambio corretti agli estremi.
  - PERMESSI: tutte e 4 le rotte 403 senza sessione Bunker (la sola chiave admin non basta).
  - PROVE: IP, ora UTC, versione, firma HMAC e flag `integra`; manomissione -> smascherata.
  - FIELD CIECO: /api/admin/verifiche/dettaglio non espone piu' IP ne' impronta.
  - COSTI: la tariffa tecnica di una prenotazione rimborsata finisce nelle PERDITE.
  - DOSSIER: CSV e JSON completi e CERTIFICATI (riga finale con l'impronta).
"""
import datetime
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase98_policy_commissione import (LANCIO_BPS_FASE1, LANCIO_BPS_REGIME,
                                       LANCIO_GIORNI_GRATIS, stato_scaglione)
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

PW = "SuperPw@1"
AK = {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9", "User-Agent": "Firefox"}
PSP = 300
PREZZO = 20000


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://x/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


class BaseSala(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        self.dir = d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        os.environ["UPLOAD_DIR"] = f"{d}/uploads"
        self.db_reg, self.db_acc = f"{d}/r.db", f"{d}/a.db"
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=self.db_reg,
            db_accettazioni=self.db_acc, db_pendenti=f"{d}/p.db", db_messaggi=f"{d}/m.db",
            db_garanzia=f"{d}/g.db", db_finanza=f"{d}/f.db", db_recensioni=f"{d}/rec.db",
            commissione_bps=1000, psp_bps=PSP, promo_lancio_attiva=True, bunker_password=PW,
            stripe_secret_key="sk", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {},
                               json.dumps(b) if b is not None else None, h or AK)

    def bunker(self):
        s, o = self.g("POST", "/api/bunker/login", {"codice": PW})
        self.assertEqual(s, 200, o)
        d = dict(AK)
        d["X-Bunker-Session"] = o["sessione"]
        return d

    def host(self, email="h@sala.local", slug="casa"):
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": email, "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        tk = {"X-Host-Token": c["token"]}
        oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": slug, "titolo": "Casa", "citta": "Roma",
                "prezzo_notte_cents": PREZZO, "capacita": 4}, tk)
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": slug, "da": oggi.isoformat(),
                "a": (oggi + datetime.timedelta(days=20)).isoformat(),
                "unita_totali": 5, "prezzo_netto_cents": PREZZO}, tk)
        return c["host_id"], tk

    def invecchia(self, hid, giorni):
        con = sqlite3.connect(self.db_reg)
        try:
            con.execute("UPDATE host SET creato_ts=? WHERE host_id=?",
                        (int(time.time()) - giorni * 86400 - 60, hid))
            con.commit()
        finally:
            con.close()

    def prenota_e_paga(self, slug="casa", giorni_avanti=3):
        oggi = datetime.date.today()
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": slug,
                       "check_in": (oggi + datetime.timedelta(days=giorni_avanti)).isoformat(),
                       "check_out": (oggi + datetime.timedelta(days=giorni_avanti + 1)).isoformat(),
                       "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "osp@sala.local"})
        self.assertEqual(s, 201, b)
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": b["riferimento"]}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})
        return b["riferimento"], b["voucher_token"], q


class TestPermessi(BaseSala):
    def test_tutte_le_rotte_403_senza_bunker(self):
        """La sola chiave admin NON basta: sono dati legali e fiscali."""
        for rotta in ("scaglioni_host", "prove_legali", "costi_tecnici", "export_legale"):
            s, o = self.g("GET", "/api/bunker/" + rotta)
            self.assertEqual(s, 403, "%s accessibile senza Bunker: %s" % (rotta, o))
            self.assertEqual(o.get("errore"), "bunker_richiesto")

    def test_field_non_vede_piu_ip_ne_impronta(self):
        """Il pannello operativo mostra lo STATO della prova, mai i dati legali/personali."""
        hid, _tk = self.host()
        s, d = self.g("GET", "/api/admin/verifiche/dettaglio", None, AK, {"host_id": hid})
        self.assertEqual(s, 200, d)
        for p in d["contratto_prove"]:
            self.assertNotIn("ip", p, "il Field espone ancora l'IP senza secondo fattore")
            self.assertNotIn("doc_sha256", p, "il Field espone ancora l'impronta")
            self.assertNotIn("firma", p)
            self.assertIn("integra", p)          # lo stato sì: serve a lavorare


class TestScaglioni(BaseSala):
    def test_scaglioni_agli_estremi_con_date(self):
        hid, _tk = self.host()
        bk = self.bunker()
        attesi = [(0, "promo", 0, LANCIO_GIORNI_GRATIS), (89, "promo", 0, 1),
                  (90, "fase1", LANCIO_BPS_FASE1, 275), (364, "fase1", LANCIO_BPS_FASE1, 1),
                  (365, "regime", LANCIO_BPS_REGIME, None), (900, "regime", LANCIO_BPS_REGIME, None)]
        for giorni, scaglione, bps, al_prossimo in attesi:
            self.invecchia(hid, giorni)
            s, d = self.g("GET", "/api/bunker/scaglioni_host", None, bk)
            self.assertEqual(s, 200, d)
            v = d["host"][0]
            self.assertEqual(v["scaglione"], scaglione, "a %d giorni" % giorni)
            self.assertEqual(v["bps"], bps, "a %d giorni" % giorni)
            self.assertEqual(v["giorni_al_prossimo"], al_prossimo, "a %d giorni" % giorni)
            if al_prossimo is None:
                self.assertEqual(v["prossimo_scatto_il"], "")
            else:
                atteso = (datetime.date.today()
                          + datetime.timedelta(days=al_prossimo)).isoformat()
                self.assertEqual(v["prossimo_scatto_il"], atteso, "data scatto a %d gg" % giorni)
            self.assertEqual(v["bps_diretto"], 500)      # il diretto non lo tocca la rampa

    def test_il_bunker_mostra_ESATTAMENTE_cio_che_il_motore_addebita(self):
        """La prova che conta: il numero della sala controllo == quello del preventivo."""
        hid, _tk = self.host()
        bk = self.bunker()
        for giorni in (0, 45, 90, 200, 365, 800):
            self.invecchia(hid, giorni)
            s, d = self.g("GET", "/api/bunker/scaglioni_host", None, bk)
            mostrato = d["host"][0]["bps"]
            oggi = datetime.date.today()
            s, q = self.g("POST", "/api/concierge/quote",
                          {"alloggio_id": "casa",
                           "check_in": (oggi + datetime.timedelta(days=2)).isoformat(),
                           "check_out": (oggi + datetime.timedelta(days=3)).isoformat(),
                           "party": 2})
            addebitato = q["commissione_cents"] * 10000 // PREZZO
            self.assertEqual(mostrato, addebitato,
                             "a %d giorni il Bunker mostra %d bps ma il motore ne addebita %d"
                             % (giorni, mostrato, addebitato))

    def test_filtri_e_conteggi(self):
        h1, _ = self.host("a@sala.local", "casa1")
        h2, _ = self.host("b@sala.local", "casa2")
        self.invecchia(h1, 0)             # promo
        self.invecchia(h2, 500)           # regime
        bk = self.bunker()
        s, d = self.g("GET", "/api/bunker/scaglioni_host", None, bk)
        self.assertEqual(d["conteggi"]["promo"], 1)
        self.assertEqual(d["conteggi"]["regime"], 1)
        s, d = self.g("GET", "/api/bunker/scaglioni_host", None, bk, {"scaglione": "promo"})
        self.assertEqual([x["host_id"] for x in d["host"]], [h1])
        s, d = self.g("GET", "/api/bunker/scaglioni_host", None, bk, {"q": "b@sala"})
        self.assertEqual([x["host_id"] for x in d["host"]], [h2])

    def test_indicatore_riaccettazione(self):
        """Chi non e' in regola con la versione CORRENTE del contratto deve risultare
        'da ri-accettare' nella sala controllo: prima era invisibile a chiunque."""
        hid, _tk = self.host()
        bk = self.bunker()
        s, d = self.g("GET", "/api/bunker/scaglioni_host", None, bk)
        self.assertEqual(d["da_riaccettare"], 0, "host appena registrato: gia' in regola")
        self.assertFalse(d["host"][0]["deve_riaccettare"])
        self.assertEqual(d["versione_contratto_corrente"], CONTRATTO_HOST_VERSIONE)
        # simulo un contratto aggiornato: le prove restano su una versione vecchia
        con = sqlite3.connect(self.db_acc)
        try:
            con.execute("UPDATE accettazioni SET versione='2020-01-01' WHERE host_id=?", (hid,))
            con.commit()
        finally:
            con.close()
        s, d = self.g("GET", "/api/bunker/scaglioni_host", None, bk)
        self.assertEqual(d["da_riaccettare"], 1, "l'host indietro non viene segnalato")
        self.assertTrue(d["host"][0]["deve_riaccettare"])
        self.assertIn("versione del contratto", d["nota_riaccettazione"])

    def test_host_senza_data_non_regala_lo_zero(self):
        hid, _tk = self.host()
        con = sqlite3.connect(self.db_reg)
        try:
            con.execute("UPDATE host SET creato_ts=NULL WHERE host_id=?", (hid,))
            con.commit()
        except Exception:
            self.skipTest("colonna NOT NULL: caso non riproducibile")
        finally:
            con.close()
        s, d = self.g("GET", "/api/bunker/scaglioni_host", None, self.bunker())
        self.assertEqual(d["host"][0]["scaglione"], "regime")
        self.assertEqual(d["host"][0]["bps"], LANCIO_BPS_REGIME)


class TestProveLegali(BaseSala):
    def test_prove_complete_e_integre(self):
        hid, _tk = self.host()
        s, d = self.g("GET", "/api/bunker/prove_legali", None, self.bunker())
        self.assertEqual(s, 200, d)
        self.assertEqual(d["totale"], 2)                  # contratto + privacy
        self.assertTrue(d["integrita_ok"])
        self.assertEqual(d["manomesse"], 0)
        c = [p for p in d["prove"] if p["documento"] == "contratto_host"][0]
        self.assertEqual(c["ip"], "203.0.113.9")
        self.assertEqual(c["versione"], CONTRATTO_HOST_VERSIONE)
        self.assertEqual(c["doc_sha256"], doc_sha256())
        self.assertTrue(c["accettato_utc"].endswith("UTC"))
        self.assertTrue(c["clausole_vessatorie"])
        self.assertEqual(len(c["firma_hmac_sha256"]), 64)   # HMAC-SHA256 esadecimale
        self.assertTrue(c["integra"])
        self.assertTrue(any(p["documento"] == "privacy_gdpr" for p in d["prove"]))

    def test_manomissione_smascherata(self):
        hid, _tk = self.host()
        con = sqlite3.connect(self.db_acc)
        try:
            con.execute("UPDATE accettazioni SET ip='1.2.3.4' WHERE host_id=?", (hid,))
            con.commit()
        finally:
            con.close()
        s, d = self.g("GET", "/api/bunker/prove_legali", None, self.bunker())
        self.assertFalse(d["integrita_ok"])
        self.assertEqual(d["manomesse"], 2)
        self.assertTrue(all(not p["integra"] for p in d["prove"]))

    def test_filtro_per_host(self):
        h1, _ = self.host("x@sala.local", "casa1")
        self.host("y@sala.local", "casa2")
        s, d = self.g("GET", "/api/bunker/prove_legali", None, self.bunker(), {"host_id": h1})
        self.assertEqual(d["totale"], 2)
        self.assertTrue(all(p["host_id"] == h1 for p in d["prove"]))


class TestCostiTecnici(BaseSala):
    def test_incassata_vs_persa_su_rimborso(self):
        self.host()
        self.prenota_e_paga(giorni_avanti=3)                       # resta pagata
        _rif2, vt2, _q = self.prenota_e_paga(giorni_avanti=8)      # poi cancellata
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": vt2})
        self.assertEqual(s, 200, c)
        s, d = self.g("GET", "/api/bunker/costi_tecnici", None, self.bunker())
        self.assertEqual(s, 200, d)
        tecnica = PREZZO * PSP // 10000
        self.assertEqual(d["incassate"]["conteggio"], 1)
        self.assertEqual(d["incassate"]["cents"], tecnica)
        self.assertEqual(d["perdite"]["conteggio"], 1, "il rimborso non è finito nelle perdite")
        self.assertEqual(d["perdite"]["cents"], tecnica)
        self.assertEqual(d["coperto_cents"], 0)                    # una copre, una perde
        self.assertEqual(d["tariffa_tecnica_bps"], PSP)
        self.assertIn("EUR", d["per_valuta"])

    def test_etichetta_fiscale_esplicita(self):
        """Il commercialista deve leggere la voce e sapere cosa farne, senza interpretare:
        la quota Stripe non restituita sui rimborsi e' un COSTO IRRECUPERABILE deducibile."""
        self.host()
        s, d = self.g("GET", "/api/bunker/costi_tecnici", None, self.bunker())
        self.assertEqual(s, 200, d)
        self.assertIn("COSTO TECNICO IRRECUPERABILE", d["perdite"]["voce_fiscale"])
        self.assertIn("deducibile", d["perdite"]["voce_fiscale"])
        self.assertIn("COSTO TECNICO IRRECUPERABILE", d["nota"])
        self.assertIn("perdite", d["classificazione_fiscale"])
        self.assertIn("coperto", d["incassate"]["voce_fiscale"].lower())

    def test_senza_pagamenti_tutto_zero(self):
        self.host()
        s, d = self.g("GET", "/api/bunker/costi_tecnici", None, self.bunker())
        self.assertEqual(d["incassate"]["cents"], 0)
        self.assertEqual(d["perdite"]["cents"], 0)


class TestDossierLegale(BaseSala):
    def test_csv_completo_e_certificato(self):
        hid, _tk = self.host()
        self.invecchia(hid, 0)
        self.prenota_e_paga()
        s, d = self.g("GET", "/api/bunker/export_legale", None, self.bunker(),
                      {"formato": "csv"})
        self.assertEqual(s, 200, d)
        csv = d["contenuto"]
        self.assertTrue(d["certificato"])
        self.assertIn("# FINE DOSSIER - INTEGRITÀ:", csv)          # non troncato
        for colonna in ("host_id", "contratto_sha256", "contratto_ip",
                        "contratto_firma_hmac_sha256", "clausole_vessatorie",
                        "privacy_versione", "scaglione", "commissione_marketplace_pct"):
            self.assertIn(colonna, csv, "colonna mancante: %s" % colonna)
        self.assertIn("203.0.113.9", csv)                          # IP reale
        self.assertIn(doc_sha256(), csv)                           # impronta del contratto
        self.assertIn("PROSPETTO TARIFFA TECNICA", csv)
        self.assertIn("perdita_tecnica_su_rimborsi", csv)
        self.assertIn("promo", csv)                                # scaglione dell'host

    def test_json_strutturato(self):
        hid, _tk = self.host()
        self.invecchia(hid, 400)
        s, d = self.g("GET", "/api/bunker/export_legale", None, self.bunker(),
                      {"formato": "json"})
        self.assertEqual(s, 200, d)
        testo = d["contenuto"]
        self.assertIn("# FINE DOSSIER", testo)
        dati = json.loads(testo.split("\n# FINE DOSSIER")[0])
        self.assertEqual(dati["totale_host"], 1)
        self.assertEqual(dati["prove_manomesse"], 0)
        h = dati["host"][0]
        self.assertEqual(h["scaglione"], "regime")
        self.assertEqual(h["commissione_marketplace_pct"], "10.00")
        self.assertEqual(h["contratto_ip"], "203.0.113.9")
        self.assertEqual(len(h["contratto_firma_hmac_sha256"]), 64)
        self.assertEqual(h["clausole_vessatorie"], "SI")
        self.assertEqual(dati["tariffa_tecnica"]["bps"], PSP)

    def test_dossier_dichiara_le_prove_manomesse(self):
        hid, _tk = self.host()
        con = sqlite3.connect(self.db_acc)
        try:
            con.execute("UPDATE accettazioni SET ip='9.9.9.9' WHERE host_id=?", (hid,))
            con.commit()
        finally:
            con.close()
        s, d = self.g("GET", "/api/bunker/export_legale", None, self.bunker(),
                      {"formato": "json"})
        dati = json.loads(d["contenuto"].split("\n# FINE DOSSIER")[0])
        self.assertEqual(dati["prove_manomesse"], 1)
        self.assertEqual(dati["host"][0]["contratto_integra"], "NO")


class TestFonteUnica(unittest.TestCase):
    """Il calcolo dello scaglione deve vivere in UN SOLO posto (fase98)."""

    def test_stato_scaglione_e_deterministico(self):
        for giorni, atteso in ((0, 0), (89, 0), (90, LANCIO_BPS_FASE1),
                               (364, LANCIO_BPS_FASE1), (365, LANCIO_BPS_REGIME)):
            self.assertEqual(stato_scaglione(giorni)["bps"], atteso)

    def test_fail_safe_anzianita_ignota(self):
        for cattivo in (None, -1, "ieri", True, 3.5):
            st = stato_scaglione(cattivo)
            self.assertEqual(st["bps"], LANCIO_BPS_REGIME, "%r regala lo 0%%" % (cattivo,))
            self.assertFalse(st["anzianita_nota"])

    def test_rampa_mai_oltre_il_regime_configurato(self):
        for regime in (500, 800, 1000, 1500):
            for giorni in (0, 90, 200, 400):
                st = stato_scaglione(giorni, bps_regime_config=regime)
                self.assertLessEqual(st["bps"], regime,
                                     "a %d giorni la rampa supera il regime %d" % (giorni, regime))

    def test_promo_spenta_sempre_regime(self):
        for giorni in (0, 45, 400):
            st = stato_scaglione(giorni, promo_attiva=False, bps_regime_config=1200)
            self.assertEqual(st["bps"], 1200)
            self.assertIsNone(st["giorni_al_prossimo"])


if __name__ == "__main__":
    unittest.main()
