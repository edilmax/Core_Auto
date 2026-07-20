"""PAGINA DI SOLA VALUTAZIONE /recensione/ (2026-07-20, richiesta fondatore: il cliente
deve vedere SOLO il voto, non il voucher pieno di cancella/prezzo/check-in).

Guardie di questo compartimento:
  - PULITA: la pagina mostra il form voto (stelle + categorie, POST /api/recensioni) e NON
    contiene le voci del voucher (cancella, PIN, check-in, chat, ricevuta, prezzo).
  - STESSO MECCANISMO: il voto inviato dalla pagina pulita si salva davvero (stesso motore).
  - FASI: prima del check-out -> messaggio "dopo il soggiorno"; gia' recensita -> grazie;
    token non valido -> None (la rotta mostra la pagina gentile).
  - VOUCHER INTATTO: pagina_voucher_html mostra ANCORA il suo form (non e' stato toccato).
  - COLLEGAMENTO: l'email invito post-soggiorno punta a /recensione/ (non piu' al voucher);
    conferma-pagamento e promemoria check-in restano sul voucher.
"""
import datetime
import json
import os
import re
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase63_recensioni import EmettitoreDiritto
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import (crea_router, pagina_recensione_html, pagina_voucher_html)
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

VOUCHER_CLUTTER = ["Cancella prenotazione", "PIN check-in", "Check-in online",
                   "Chatta con", "Ricevuta di pagamento"]


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://x/" + secrets.token_hex(5), "id": "cs_" + secrets.token_hex(5)}


class TestPaginaRecensione(unittest.TestCase):
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
                      {"email": "h@pr.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        tk = {"X-Host-Token": c["token"]}
        oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": "attico", "titolo": "Attico Vista Colosseo", "citta": "Roma",
                "prezzo_notte_cents": 24500, "capacita": 4}, tk)
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "attico", "da": oggi.isoformat(),
                "a": (oggi + datetime.timedelta(days=20)).isoformat(),
                "unita_totali": 1, "prezzo_netto_cents": 24500}, tk)
        ci = (oggi + datetime.timedelta(days=3)).isoformat()
        co = (oggi + datetime.timedelta(days=5)).isoformat()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "attico", "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@pr.it"})
        self.rif, self.vt = b["riferimento"], b["voucher_token"]
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": self.rif}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _vt_con_checkout(self, giorni_delta):
        """Rifirma il voucher con check-out spostato (per simulare il soggiorno concluso)."""
        dati = self.sis.firma.decodifica(self.vt)
        dati["check_out"] = (datetime.date.today()
                             + datetime.timedelta(days=giorni_delta)).isoformat()
        return self.sis.firma.codifica(dati)

    def _diritto_maturo(self):
        return EmettitoreDiritto(self.sis.firma).emetti(
            self.rif, "attico", non_prima_ts=int(time.time()) - 60)

    # ── 1. pulita: SOLO il voto, niente roba del voucher ────────────────────────
    def test_pagina_pulita_solo_voto(self):
        pagina = pagina_recensione_html(self.sis, self._vt_con_checkout(-1), "it")
        self.assertIsNotNone(pagina)
        self.assertIn("recBox", pagina)                       # il form c'è
        self.assertIn("/api/recensioni", pagina)              # stesso endpoint
        self.assertIn("Pulizia", pagina)
        self.assertIn("Comfort", pagina)
        self.assertIn("andato il tuo soggiorno", pagina)   # apostrofo escapato (sicuro)
        self.assertIn("Attico Vista Colosseo", pagina)
        for clutter in VOUCHER_CLUTTER:                       # NIENTE roba del voucher
            self.assertNotIn(clutter, pagina, "la pagina pulita contiene: " + clutter)
        self.assertNotIn("245.00", pagina)                    # niente prezzo
        self.assertNotIn("245,00", pagina)

    # ── 2. stesso meccanismo: il voto inviato da qui si salva DAVVERO ────────────
    def test_submit_dalla_pagina_pulita_salva(self):
        pagina = pagina_recensione_html(self.sis, self._vt_con_checkout(-1), "it")
        m = re.search(r'"tok":\s*"([^"]+)"', pagina)          # il diritto emesso in pagina
        self.assertIsNotNone(m, "diritto non incorporato nella pagina")
        diritto = m.group(1)
        s, o = self.g("POST", "/api/recensioni",
                      {"token": diritto, "voto": 5, "testo": "perfetto", "lingua": "it",
                       "categorie": {"pulizia": 5, "comfort": 4}})
        self.assertEqual(s, 201, o)
        s, rr = self.g("GET", "/api/recensioni/attico")
        self.assertEqual(rr["riepilogo"]["conteggio"], 1)
        self.assertEqual(rr["riepilogo"]["categorie"]["pulizia"]["media_centesimi"], 500)

    # ── 3. fasi: prima del soggiorno / già recensita ────────────────────────────
    def test_prima_del_checkout_niente_form(self):
        pagina = pagina_recensione_html(self.sis, self._vt_con_checkout(+5), "it")
        self.assertIsNotNone(pagina)
        self.assertNotIn("recBox", pagina)
        self.assertIn("termine del soggiorno", pagina)

    def test_gia_recensita_grazie(self):
        s, o = self.g("POST", "/api/recensioni", {"token": self._diritto_maturo(), "voto": 4})
        self.assertEqual(s, 201, o)
        pagina = pagina_recensione_html(self.sis, self._vt_con_checkout(-1), "it")
        self.assertNotIn("recBox", pagina)
        self.assertIn("recensione verificata è pubblicata", pagina)

    def test_token_non_valido_none(self):
        self.assertIsNone(pagina_recensione_html(self.sis, "token-farlocco"))
        self.assertIsNone(pagina_recensione_html(self.sis, self.vt[:-4] + "AAAA"))

    # ── 4. il VOUCHER non è stato toccato: mostra ancora il suo form ────────────
    def test_voucher_resta_intatto(self):
        v = self.sis.firma.decodifica(self.vt)
        v["check_out"] = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        voucher = pagina_voucher_html(self.sis, self.sis.firma.codifica(v), "it")
        self.assertIn("recBox", voucher)                      # il voucher HA ancora il voto
        self.assertIn("Cancella prenotazione", voucher)       # e le sue voci di sempre
        self.assertIn("PIN check-in", voucher)

    # ── 5. collegamento: l'email invito punta a /recensione/, gli altri al voucher ─
    def test_email_invito_ricollegata(self):
        import inspect
        import fase83_server as srv
        src = inspect.getsource(srv)
        self.assertIn('u.path.startswith("/recensione/")', src, "rotta /recensione/ assente")
        # nel tick invito: /recensione/ subito prima di corpo_invito_recensione_html
        blocco = src[src.index("_tick_invito_recensione"):]
        pezzo = blocco[:blocco.index("corpo_invito_recensione_html")]
        self.assertIn('"/recensione/"', pezzo,
                      "l'email invito recensione NON è collegata a /recensione/")


if __name__ == "__main__":
    unittest.main()
