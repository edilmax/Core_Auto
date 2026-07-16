"""Collaudo BUG #17 (2026-07-16, metodo libro - attore cliente/email): la richiesta
su-richiesta finiva nel SILENZIO o nella BUGIA.
  (a) host RIFIUTA -> il cliente non riceveva NIENTE (aspettava a vuoto un esito
      che non sarebbe mai arrivato);
  (b) host NON RISPONDE entro 24h -> lo sweeper mandava l'email di recupero hold
      'Il pagamento non e' andato a buon fine' — FALSA e allarmante: per una
      richiesta mai approvata il cliente non doveva pagare niente.

Fix: `_email_esito_richiesta` (rifiutata/scaduta, 'nessun addebito', onesta) chiamata
dal rifiuto e dallo sweep (che ora distingue 'in_attesa_host' da un vero hold di
pagamento). L'email di recupero classica per l'instant-book non pagato e' INVARIATA.
"""
import json
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, sweep_hold_una_passata
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE


class EmailFinta:
    def __init__(self):
        self.inviate = []

    def invia(self, a, oggetto, corpo):
        self.inviate.append((a, oggetto, corpo))
        return True


class TestEmailEsitoRichiesta(unittest.TestCase):
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
        self.sis.email_provider = EmailFinta()
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@er.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None,
                               h or {})

    def _pubblica(self, slug, modalita):
        self.g("POST", "/api/host/pubblica",
               {"slug": slug, "titolo": "Casa ER", "citta": "Roma",
                "prezzo_notte_cents": 10000, "capacita": 2,
                "modalita_prenotazione": modalita}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": slug, "da": "2026-09-01", "a": "2026-09-30",
                "unita_totali": 1, "prezzo_netto_cents": 10000}, {"X-Host-Token": self.tok})

    def _book(self, slug):
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": slug, "check_in": "2026-09-10",
                       "check_out": "2026-09-12", "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cliente@er.it"})
        return b["riferimento"]

    def _al_cliente(self, da=0):
        # le email partono in thread daemon: piccola attesa attiva
        for _ in range(40):
            got = [e for e in self.sis.email_provider.inviate[da:]
                   if e[0] == "cliente@er.it"]
            if got:
                return got
            time.sleep(0.05)
        return []

    def _scadenza_passata(self, ref):
        pp = self.sis.pagamenti_pendenti
        con = pp._apri()
        try:
            with con:
                con.execute("UPDATE pendenti SET scadenza_ts=? WHERE riferimento=?",
                            (int(time.time()) - 10, ref))
        finally:
            con.close()

    def test_rifiuto_avvisa_il_cliente(self):
        self._pubblica("casa-r", "su_richiesta")
        ref = self._book("casa-r")
        prima = len(self.sis.email_provider.inviate)
        s, c = self.g("POST", "/api/host/richieste/rifiuta",
                      {"riferimento": ref}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 200, c)
        got = self._al_cliente(prima)
        self.assertEqual(len(got), 1, "il cliente DEVE sapere che e' stata rifiutata")
        _, ogg, corpo = got[0]
        self.assertIn("non ha potuto accettare", ogg)
        self.assertIn("Nessun addebito", corpo)
        self.assertNotIn("pagamento non", corpo.lower())

    def test_scadenza_richiesta_email_onesta_non_pagamento_fallito(self):
        self._pubblica("casa-s", "su_richiesta")
        ref = self._book("casa-s")
        self._scadenza_passata(ref)
        prima = len(self.sis.email_provider.inviate)
        sweep_hold_una_passata(self.sis, self.r)
        got = self._al_cliente(prima)
        self.assertEqual(len(got), 1)
        _, ogg, corpo = got[0]
        self.assertIn("non ha risposto", ogg)
        self.assertIn("Nessun addebito", corpo)
        # MAI piu' la bugia 'il pagamento non e' andato a buon fine' su una richiesta
        self.assertNotIn("pagamento non", corpo.lower())
        self.assertEqual(self.sis.pagamenti_pendenti.info(ref)["stato"], "scaduto")

    def test_hold_instant_scaduto_email_recupero_invariata(self):
        # NESSUNA regressione: l'instant-book non pagato riceve ancora il recupero classico
        self._pubblica("casa-i", "immediata")
        ref = self._book("casa-i")
        self.assertEqual(self.sis.pagamenti_pendenti.info(ref)["stato"], "in_attesa")
        self._scadenza_passata(ref)
        prima = len(self.sis.email_provider.inviate)
        sweep_hold_una_passata(self.sis, self.r)
        got = self._al_cliente(prima)
        self.assertEqual(len(got), 1)
        _, ogg, corpo = got[0]
        self.assertIn("di nuovo libere", ogg)
        self.assertIn("pagamento non", corpo.lower())     # qui il pagamento c'era davvero


if __name__ == "__main__":
    unittest.main(verbosity=2)
