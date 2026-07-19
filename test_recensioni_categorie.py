"""RECENSIONI STILE BOOKING/AGODA (2026-07-20, richiesta fondatore): voto generale +
sotto-voti per categoria (pulizia, comfort, posizione, servizi, host, qualita/prezzo).

Guardie di questo compartimento:
  - MOTORE: categorie valide salvate e medie INTERE per categoria; chiave sconosciuta o
    voto fuori scala = rifiuto; retro-compatibile (recensione senza categorie ok).
  - NBF (non-prima-di): il diritto emesso col check-out dentro il token FIRMATO ->
    recensire PRIMA del soggiorno e' impossibile (troppo_presto), come Booking/Agoda.
  - ENDPOINT: POST /api/recensioni accetta `categorie` e le espone in GET (riepilogo
    con medie + elenco coi sotto-voti); pagata resta obbligatoria (guardia esistente).
  - PAGINA VOUCHER: il form appare SOLO dopo il check-out; gia' recensita -> grazie;
    prima del check-out -> nessun form.
"""
import base64
import datetime
import json
import os
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase63_recensioni import CATEGORIE, EmettitoreDiritto, crea_registro_recensioni
from fase59_concierge import FirmaQuote
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, pagina_voucher_html
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://x/" + secrets.token_hex(5), "id": "cs_" + secrets.token_hex(5)}


class TestMotoreCategorie(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.seg = b"R" * 32
        self.reg = crea_registro_recensioni(f"{self.dir}/r.db", self.seg)
        self.em = EmettitoreDiritto(FirmaQuote(self.seg))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_categorie_salvate_e_medie_intere(self):
        t1 = self.em.emetti("P1", "casa")
        e = self.reg.invia(t1, 5, "top", "it",
                           categorie={"pulizia": 5, "comfort": 4, "host": 5})
        self.assertTrue(e.ok, e)
        t2 = self.em.emetti("P2", "casa")
        self.assertTrue(self.reg.invia(t2, 4, "", "it",
                                       categorie={"pulizia": 4}).ok)
        rie = self.reg.riepilogo("casa")
        self.assertEqual(rie["conteggio"], 2)
        self.assertEqual(rie["categorie"]["pulizia"],
                         {"conteggio": 2, "media_centesimi": 450})
        self.assertEqual(rie["categorie"]["comfort"],
                         {"conteggio": 1, "media_centesimi": 400})
        self.assertNotIn("posizione", rie["categorie"])   # mai votata -> assente, non 0
        voce = [x for x in self.reg.elenco("casa") if x["prenotazione_id"] == "P1"][0]
        self.assertEqual(voce["categorie"], {"pulizia": 5, "comfort": 4, "host": 5})

    def test_categorie_invalide_rifiutate(self):
        for cattive in ({"piscina": 5}, {"pulizia": 0}, {"pulizia": 6},
                        {"pulizia": "5"}, {"pulizia": True}, ["pulizia"], "x"):
            t = self.em.emetti("PX", "casa")
            e = self.reg.invia(t, 5, "", "it", categorie=cattive)
            self.assertFalse(e.ok, cattive)
            self.assertEqual(e.motivo, "categorie_non_valide", cattive)
        # e NON deve aver lasciato residui: la recensione non esiste
        self.assertFalse(self.reg.gia_recensita("PX"))

    def test_senza_categorie_retrocompatibile(self):
        t = self.em.emetti("P3", "casa")
        self.assertTrue(self.reg.invia(t, 3, "ok", "en").ok)
        self.assertEqual(self.reg.riepilogo("casa")["categorie"], {})

    def test_nbf_blocca_prima_del_checkout(self):
        adesso = int(time.time())
        orologio = lambda: adesso
        em = EmettitoreDiritto(FirmaQuote(self.seg), orologio=orologio)
        reg = crea_registro_recensioni(f"{self.dir}/r2.db", self.seg, orologio=orologio)
        tok = em.emetti("P4", "casa", non_prima_ts=adesso + 3600)   # check-out tra 1h
        e = reg.invia(tok, 5, "", "it")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "troppo_presto")
        # passato il check-out (orologio iniettato avanti) la STESSA firma vale
        adesso += 3601
        self.assertTrue(reg.invia(tok, 5, "", "it").ok)

    def test_nbf_exp_conta_dal_checkout(self):
        adesso = int(time.time())
        em = EmettitoreDiritto(FirmaQuote(self.seg), ttl_giorni=90,
                               orologio=lambda: adesso)
        co = adesso + 5 * 86400
        dati = FirmaQuote(self.seg).decodifica(em.emetti("P5", "casa", non_prima_ts=co))
        self.assertEqual(dati["nbf"], co)
        self.assertEqual(dati["exp"], co + 90 * 86400)   # 90gg DAL check-out, non dal book

    def test_gia_recensita(self):
        self.assertFalse(self.reg.gia_recensita("P9"))
        self.assertTrue(self.reg.invia(self.em.emetti("P9", "casa"), 4).ok)
        self.assertTrue(self.reg.gia_recensita("P9"))


class TestEndpointEPagina(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        self.dir = d = tempfile.mkdtemp()
        os.environ["UPLOAD_DIR"] = f"{d}/uploads"
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_messaggi=f"{d}/m.db",
            db_garanzia=f"{d}/g.db", db_recensioni=f"{d}/rec.db",
            commissione_bps=1500, psp_bps=300,
            stripe_secret_key="sk", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@rc.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        tk = {"X-Host-Token": c["token"]}
        oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "Casa", "citta": "Roma",
                "prezzo_notte_cents": 20000, "capacita": 4}, tk)
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": oggi.isoformat(),
                "a": (oggi + datetime.timedelta(days=20)).isoformat(),
                "unita_totali": 1, "prezzo_netto_cents": 20000}, tk)
        ci = (oggi + datetime.timedelta(days=3)).isoformat()
        co = (oggi + datetime.timedelta(days=5)).isoformat()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@rc.it"})
        self.assertIn("diritto_recensione", b)
        self.rif, self.vt, self.diritto = b["riferimento"], b["voucher_token"], b["diritto_recensione"]
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": self.rif}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _diritto_maturo(self):
        """Diritto con nbf gia' passato (stessa firma del sistema): simula il post-soggiorno."""
        return EmettitoreDiritto(self.sis.firma).emetti(
            self.rif, "casa", non_prima_ts=int(time.time()) - 60)

    def test_prima_del_checkout_403_troppo_presto(self):
        s, o = self.g("POST", "/api/recensioni",
                      {"token": self.diritto, "voto": 5, "categorie": {"pulizia": 5}})
        self.assertEqual(s, 400, o)
        self.assertEqual(o.get("motivo"), "troppo_presto")

    def test_dopo_il_checkout_categorie_in_riepilogo_ed_elenco(self):
        s, o = self.g("POST", "/api/recensioni",
                      {"token": self._diritto_maturo(), "voto": 5, "testo": "pulitissimo",
                       "lingua": "it",
                       "categorie": {"pulizia": 5, "comfort": 4, "qualita_prezzo": 5}})
        self.assertEqual(s, 201, o)
        self.assertTrue(o["verificata"])
        s, rr = self.g("GET", "/api/recensioni/casa")
        self.assertEqual(s, 200)
        self.assertEqual(rr["riepilogo"]["conteggio"], 1)
        self.assertEqual(rr["riepilogo"]["categorie"]["pulizia"]["media_centesimi"], 500)
        self.assertEqual(rr["recensioni"][0]["categorie"],
                         {"pulizia": 5, "comfort": 4, "qualita_prezzo": 5})
        # doppio invio -> 409, una sola recensione per soggiorno
        s2, o2 = self.g("POST", "/api/recensioni",
                        {"token": self._diritto_maturo(), "voto": 1})
        self.assertEqual(s2, 409, o2)

    def test_categorie_sconosciute_400(self):
        s, o = self.g("POST", "/api/recensioni",
                      {"token": self._diritto_maturo(), "voto": 5,
                       "categorie": {"jacuzzi": 5}})
        self.assertEqual(s, 400, o)
        self.assertEqual(o.get("motivo"), "categorie_non_valide")

    def test_pagina_voucher_prima_niente_form_dopo_si(self):
        # PRIMA del check-out (date future del setUp): nessun form
        pagina = pagina_voucher_html(self.sis, self.vt, "it")
        self.assertIsNotNone(pagina)
        self.assertNotIn("recBox", pagina)
        # DOPO: voucher con soggiorno gia' concluso (stessa firma, date passate)
        ieri = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        v = self.sis.firma.decodifica(self.vt)
        v["check_out"] = ieri
        pagina2 = pagina_voucher_html(self.sis, self.sis.firma.codifica(v), "it")
        self.assertIn("recBox", pagina2)
        self.assertIn("/api/recensioni", pagina2)
        for cat in CATEGORIE:                          # tutte le voci nel form
            self.assertIn(cat, pagina2)
        # in FRANCESE gli apostrofi delle traduzioni non rompono il JS (JSON, non entita')
        pagina_fr = pagina_voucher_html(self.sis, self.sis.firma.codifica(v), "fr")
        self.assertIn("recBox", pagina_fr)
        self.assertNotIn("&#x27;+", pagina_fr)
        # gia' recensita -> grazie, niente form
        s, o = self.g("POST", "/api/recensioni",
                      {"token": self._diritto_maturo(), "voto": 5})
        self.assertEqual(s, 201, o)
        pagina3 = pagina_voucher_html(self.sis, self.sis.firma.codifica(v), "it")
        self.assertNotIn("recBox", pagina3)
        self.assertIn("recensione verificata è pubblicata", pagina3)


if __name__ == "__main__":
    unittest.main()
