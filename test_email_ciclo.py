"""EMAIL DI CICLO + RICEVUTA (C3, 2026-07-20): prima il cliente pagava/cancellava/
contestava nel SILENZIO, l'host non sapeva di essere stato pagato e chi pagava soldi
veri non riceveva alcun documento.

Guardie di questo compartimento:
  - CONFERMA PAGAMENTO: dopo il webhook 'pagato' parte UNA email al cliente con
    importo e link voucher; il webhook DUPLICATO (retry Stripe) NON la rimanda.
  - CANCELLAZIONE: email onesta con l'esito del rimborso (solo se aveva pagato).
  - ESITO CONTROVERSIA: l'ospite riceve l'esito dell'arbitrato.
  - INVITO RECENSIONE (store fase162): solo PAGATE con soggiorno CONCLUSO, finestra
    14gg (mai spam sugli antichi al primo avvio), una sola volta per riferimento.
  - RICEVUTA: pagina stampabile dal token voucher firmato, SOLO pagate; link nel
    voucher solo se pagata; rotta /ricevuta/ cablata nel server (guardia sorgente).
  - CORPI EMAIL: XSS-safe (titolo ostile escapato), importi da centesimi interi.
Le email di ciclo sono BEST-EFFORT in background: mai bloccare i soldi.
"""
import datetime
import json
import os
import shutil
import tempfile
import threading
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase59_concierge import codice_prenotazione
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, pagina_ricevuta_html, pagina_voucher_html
from fase86_email import (corpo_cancellazione_html, corpo_esito_controversia_html,
                          corpo_invito_recensione_html,
                          corpo_pagamento_confermato_html, corpo_payout_host_html)
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://x/" + secrets.token_hex(5), "id": "cs_" + secrets.token_hex(5)}


class Finta:
    """Provider email finto: raccoglie gli invii (le email C3 partono in thread)."""

    def __init__(self):
        self.inviate = []
        self._cv = threading.Condition()

    def invia(self, dest, oggetto, html):
        with self._cv:
            self.inviate.append((dest, oggetto, html))
            self._cv.notify_all()
        return True

    def attendi(self, filtro, n=1, timeout=8):
        """True quando almeno n email il cui oggetto contiene `filtro` sono arrivate."""
        fine = time.time() + timeout
        with self._cv:
            while len([1 for _, o, _h in self.inviate if filtro in o]) < n:
                resto = fine - time.time()
                if resto <= 0:
                    return False
                self._cv.wait(resto)
        return True

    def per_oggetto(self, filtro):
        return [(d, o, h) for d, o, h in self.inviate if filtro in o]


class TestEmailCiclo(unittest.TestCase):
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
                      {"email": "h@ec.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
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
                "unita_totali": 2, "prezzo_netto_cents": 20000}, tk)
        self.ci = (oggi + datetime.timedelta(days=3)).isoformat()
        self.co = (oggi + datetime.timedelta(days=5)).isoformat()
        self.rif, self.vt = self._prenota(self.ci, self.co)
        # il provider si aggancia DOPO il book: qui si contano SOLO le email C3
        self.posta = Finta()
        self.sis.email_provider = self.posta

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _prenota(self, ci, co):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ec.it", "lang": "it"})
        self.assertEqual(s, 201, b)
        return b["riferimento"], b["voucher_token"]

    def _webhook(self, rif):
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        return self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                               {"Stripe-Signature": firma_di_test(pl, "whsec_x",
                                                                  int(time.time()))})

    # ── 1. conferma pagamento: una email, mai due sul retry ─────────────────────
    def test_conferma_pagamento_una_sola_email(self):
        self._webhook(self.rif)
        self.assertTrue(self.posta.attendi("Pagamento ricevuto"),
                        "email di conferma pagamento mai partita")
        dest, ogg, corpo = self.posta.per_oggetto("Pagamento ricevuto")[0]
        self.assertEqual(dest, "cli@ec.it")
        self.assertIn("/voucher/", corpo)                 # link al voucher
        self.assertIn("400.00 EUR", corpo)                # 2 notti x 20000 = 40000 cents
        # RETRY Stripe (webhook duplicato): nessuna seconda email al cliente
        self._webhook(self.rif)
        time.sleep(0.6)                                   # margine ai thread background
        self.assertEqual(len(self.posta.per_oggetto("Pagamento ricevuto")), 1,
                         "il webhook duplicato ha rimandato l'email di conferma")

    # ── 2. cancellazione: esito rimborso nero su bianco ─────────────────────────
    def test_email_cancellazione_dopo_pagata(self):
        self._webhook(self.rif)
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": self.vt})
        self.assertEqual(s, 200, c)
        self.assertEqual(c["stato"], "cancellata")
        self.assertTrue(self.posta.attendi("Cancellazione confermata"),
                        "email di cancellazione mai partita")
        dest, _o, corpo = self.posta.per_oggetto("Cancellazione confermata")[0]
        self.assertEqual(dest, "cli@ec.it")
        self.assertIn("Prenotazione cancellata", corpo)
        # l'esito economico c'è SEMPRE: o l'importo del rimborso o "non è previsto"
        self.assertTrue(("Rimborso:" in corpo) or ("non è previsto" in corpo), corpo)

    def test_cancellazione_non_pagata_nessuna_email(self):
        rif2, vt2 = self._prenota(
            (datetime.date.today() + datetime.timedelta(days=8)).isoformat(),
            (datetime.date.today() + datetime.timedelta(days=10)).isoformat())
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": vt2})
        self.assertEqual(s, 200, c)
        time.sleep(0.5)
        self.assertEqual(self.posta.per_oggetto("Cancellazione confermata"), [],
                         "email di cancellazione partita per una NON pagata")

    # ── 3. esito controversia all'ospite ─────────────────────────────────────────
    def test_email_esito_controversia(self):
        self._webhook(self.rif)
        s, c = self.g("POST", "/api/garanzia/contesta", {"voucher_token": self.vt})
        self.assertEqual(s, 200, c)
        s, c = self.g("POST", "/api/admin/controversia/risolvi",
                      {"riferimento": self.rif, "percentuale_ospite": 100},
                      {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, c)
        self.assertTrue(self.posta.attendi("Esito della tua segnalazione"),
                        "email esito controversia mai partita")
        dest, _o, corpo = self.posta.per_oggetto("Esito della tua segnalazione")[0]
        self.assertEqual(dest, "cli@ec.it")
        self.assertIn("rimborsato", corpo)                # 100% all'ospite -> importo

    # ── 4. invito recensione: store fase162 (finestra, una-volta, solo pagate) ──
    def test_invito_recensione_selezione_e_finestra(self):
        pp = self.sis.pagamenti_pendenti
        self._webhook(self.rif)
        dopo = (datetime.date.fromisoformat(self.co)
                + datetime.timedelta(days=1)).isoformat()
        righe = pp.da_invitare_recensione(oggi=dopo)
        self.assertIn(self.rif, [r["riferimento"] for r in righe])
        # fuori finestra 14gg (primo avvio: niente spam sugli antichi)
        tardi = (datetime.date.fromisoformat(self.co)
                 + datetime.timedelta(days=20)).isoformat()
        self.assertNotIn(self.rif,
                         [r["riferimento"] for r in pp.da_invitare_recensione(oggi=tardi)])
        # segnato -> mai due inviti per lo stesso soggiorno
        self.assertTrue(pp.segna_invito_recensione(self.rif))
        self.assertNotIn(self.rif,
                         [r["riferimento"] for r in pp.da_invitare_recensione(oggi=dopo)])
        # una NON pagata non si invita mai (anche a soggiorno "concluso")
        rif2, _vt2 = self._prenota(
            (datetime.date.today() + datetime.timedelta(days=8)).isoformat(),
            (datetime.date.today() + datetime.timedelta(days=10)).isoformat())
        lontano = (datetime.date.today() + datetime.timedelta(days=11)).isoformat()
        self.assertNotIn(rif2,
                         [r["riferimento"] for r in pp.da_invitare_recensione(oggi=lontano)])
        # input non validi: mai un crash, lista vuota
        self.assertEqual(pp.da_invitare_recensione(oggi=""), [])
        self.assertEqual(pp.da_invitare_recensione(oggi="non-una-data"), [])
        self.assertFalse(pp.segna_invito_recensione(""))

    # ── 5. ricevuta: pagina firmata, solo pagate, link nel voucher ───────────────
    def test_ricevuta_solo_pagate(self):
        # NON ancora pagata: niente ricevuta, niente link nel voucher
        self.assertIsNone(pagina_ricevuta_html(self.sis, self.vt))
        self.assertNotIn("/ricevuta/", pagina_voucher_html(self.sis, self.vt, "it"))
        self._webhook(self.rif)
        pagina = pagina_ricevuta_html(self.sis, self.vt)
        self.assertIsNotNone(pagina, "ricevuta assente su prenotazione PAGATA")
        self.assertIn("Ricevuta di pagamento", pagina)
        self.assertIn(codice_prenotazione(self.rif), pagina)
        self.assertIn("400.00 EUR", pagina)               # totale pagato
        self.assertIn("P.IVA 11795700969", pagina)        # identità gestore reale
        self.assertIn("non costituisce fattura fiscale", pagina)  # onestà
        # ora il voucher offre la ricevuta
        self.assertIn("/ricevuta/", pagina_voucher_html(self.sis, self.vt, "it"))
        # token manomesso/estraneo -> nessuna pagina (mai dati altrui)
        self.assertIsNone(pagina_ricevuta_html(self.sis, "token-farlocco"))
        self.assertIsNone(pagina_ricevuta_html(self.sis, self.vt[:-4] + "AAAA"))

    def test_ricevuta_sparisce_dopo_rimborso(self):
        self._webhook(self.rif)
        self.assertIsNotNone(pagina_ricevuta_html(self.sis, self.vt))
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": self.vt})
        self.assertEqual(s, 200, c)
        # cancellata/rimborsata: la ricevuta non attesta più un pagamento valido
        self.assertIsNone(pagina_ricevuta_html(self.sis, self.vt))

    # ── 6. corpi email: XSS-safe e importi al centesimo ─────────────────────────
    def test_corpi_email_xss_e_importi(self):
        ostile = "<script>alert(1)</script>"
        for corpo in (
                corpo_pagamento_confermato_html(ostile, "https://x/v", 12345, "EUR"),
                corpo_cancellazione_html(ostile, 12345, "EUR", 500),
                corpo_invito_recensione_html(ostile, "https://x/v"),
                corpo_payout_host_html(12345, "EUR", ostile)):
            self.assertNotIn("<script>", corpo)
            self.assertIn("&lt;script&gt;", corpo)
        self.assertIn("123.45 EUR", corpo_pagamento_confermato_html("Casa", "", 12345, "EUR"))
        # cancellazione: rimborso positivo vs zero (frasi diverse, sempre oneste)
        con_r = corpo_cancellazione_html("Casa", 7000, "EUR")
        self.assertIn("70.00 EUR", con_r)
        senza_r = corpo_cancellazione_html("Casa", 0, "EUR", lingua="it")
        self.assertIn("non è previsto", senza_r)
        # credito anti-rimpianto mostrato solo se c'è
        self.assertIn("Credito Viaggio", corpo_cancellazione_html("Casa", 0, "EUR", 900, lingua="it"))
        self.assertNotIn("Credito Viaggio", corpo_cancellazione_html("Casa", 0, "EUR", 0))
        # esito controversia: rimborso vs nessun rimborso
        self.assertIn("50.00 EUR", corpo_esito_controversia_html(5000, "EUR", lingua="it"))
        self.assertIn("non è stato riconosciuto", corpo_esito_controversia_html(0, "EUR", lingua="it"))
        # importi rotti non fanno mai crashare (0 onesto)
        self.assertIn("0.00 EUR", corpo_pagamento_confermato_html("Casa", "", "boh", "EUR"))

    # ── 7. cablaggi nel server: rotta ricevuta + sweep invito recensione ────────
    def test_rotta_ricevuta_e_tick_cablati(self):
        import inspect
        import fase83_server as srv
        src = inspect.getsource(srv)
        self.assertIn('u.path.startswith("/ricevuta/")', src,
                      "rotta /ricevuta/ non cablata nel server")
        self.assertIn("target=_tick_invito_recensione", src,
                      "sweep invito recensione non avviato in servi()")
        # e il gancio email conferma sta nel punto giusto: DOPO la riasserzione
        # idempotente, MAI nel ramo retry (stato gia' 'pagato' esce prima)
        self.assertIn("self._email_pagamento_confermato(rec)", src)


if __name__ == "__main__":
    unittest.main()
