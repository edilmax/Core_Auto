"""IL TEST IMPOSSIBILE — un giapponese a Tokyo prenota un alloggio alle Hawaii.

Mette insieme, in UN SOLO flusso vero, tutti i difetti trovati e chiusi negli ultimi
giorni. Un ospite col browser in giapponese (UTC+9) prenota una casa a Honolulu (UTC-10),
prezzata in yen. Si pretende, dall'inizio alla fine:

  1. VALUTA: l'addebito su Stripe e le ricevute sono in YEN SENZA decimali (¥54.000 e
     mai 540.00 JPY, ne' .00).
  2. LINGUA: l'email di conferma e il voucher escono in GIAPPONESE (non in italiano, non
     nella lingua del server), e il link del voucher porta ?lang=ja.
  3. FUSO — PASS SERRATURA: il pass si abilita alle 15:00 ORA DI HONOLULU, non del fuso
     dell'ospite (Tokyo) ne' del server: un ospite non deve trovarsi la porta chiusa per
     19 ore per colpa del fuso sbagliato.
  4. FUSO — CONTESTAZIONE: la finestra dell'escrow parte dalle 15:00 di Honolulu.
  5. RIPENSAMENTO: le 48 ore sono 172.800 SECONDI VERI dall'istante della prenotazione,
     non un conteggio di giorni di calendario.

Se questo test e' verde, i quattro difetti "da catastrofe" non possono ripresentarsi
insieme senza che qualcuno se ne accorga.
"""

import base64
import datetime as dt
import json
import shutil
import tempfile
import time
import unittest
from zoneinfo import ZoneInfo

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

PREZZO_YEN = 18000            # ¥18.000 a notte
NOTTI = 3                     # -> ¥54.000
STRIPE_CALLS = []
INVIATE = []


def _fake_fetch(url, body, headers):
    import secrets
    STRIPE_CALLS.append(body)
    return {"url": "https://t/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


class _ProviderEmailFinto:
    def invia(self, destinatario, oggetto, html):
        INVIATE.append({"a": destinatario, "oggetto": oggetto, "html": html})
        return True


class TestGiapponeseAHonolulu(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        del STRIPE_CALLS[:]
        del INVIATE[:]
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"H" * 32, con_registrazione_host=True,
            db_catalogo="%s/c.db" % d, db_inventario="%s/i.db" % d,
            db_registro_host="%s/r.db" % d, db_accettazioni="%s/a.db" % d,
            db_pendenti="%s/p.db" % d, db_payout="%s/y.db" % d,
            db_garanzia="%s/g.db" % d, db_tassa_comunale="%s/t.db" % d,
            commissione_bps=1000, psp_bps=300, stripe_secret_key="sk",
            stripe_webhook_secret="whsec_x"))
        self.sys.email_provider = _ProviderEmailFinto()
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        st, c = self.g("POST", "/api/host/registrazione",
                       {"email": "host@hawaii.com", "password": "password1",
                        "accetta_termini": True, "accetta_clausole": True,
                        "accetta_privacy": True, "doc_sha256": doc_sha256(),
                        "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(st, 201, c)
        self.tok = c["token"]
        # alloggio a HONOLULU, prezzato in YEN, fuso Pacific/Honolulu
        st, c = self.g("POST", "/api/host/pubblica",
                       {"slug": "aloha", "titolo": "Aloha House", "citta": "Honolulu",
                        "paese": "US", "prezzo_notte_cents": PREZZO_YEN, "valuta": "JPY",
                        "capacita": 2, "politica_cancellazione": "flessibile"},
                       {"X-Host-Token": self.tok})
        self.assertIn(st, (200, 201), c)
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "aloha", "da": "2026-08-01", "a": "2026-12-31",
                "unita_totali": 1, "prezzo_netto_cents": PREZZO_YEN},
               {"X-Host-Token": self.tok})
        self.ci, self.co = "2026-09-05", "2026-09-08"

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _prenota_giapponese(self):
        st, q = self.g("POST", "/api/concierge/quote",
                       {"alloggio_id": "aloha", "check_in": self.ci,
                        "check_out": self.co, "party": 2})
        self.assertEqual(st, 200, q)
        self.assertEqual(q.get("valuta"), "JPY")
        st, b = self.g("POST", "/api/concierge/book",
                       {"quote_token": q["quote_token"], "email": "guest@tokyo.jp",
                        "lang": "ja"})
        self.assertIn(st, (200, 201), b)
        return q, b

    def _params_stripe(self):
        import urllib.parse
        corpo = STRIPE_CALLS[-1]
        if isinstance(corpo, bytes):
            corpo = corpo.decode("utf-8", "replace")
        return dict(urllib.parse.parse_qsl(str(corpo)))

    # ═══════════════════════════════════════════════════════════════════════════
    def test_1_addebito_stripe_in_yen_senza_decimali(self):
        q, _b = self._prenota_giapponese()
        p = self._params_stripe()
        self.assertEqual(p.get("line_items[0][price_data][currency]"), "jpy")
        totale = q.get("totale_cents") or q.get("prezzo_guest_cents")
        self.assertEqual(totale, PREZZO_YEN * NOTTI)          # ¥54.000, non 5.400.000
        self.assertEqual(p.get("line_items[0][price_data][unit_amount]"), str(totale))
        # e la ricevuta scritta per un umano: ¥54.000, mai 540.00
        from fase83_server import RouterHTTP
        self.assertEqual(RouterHTTP._fmt_importo(None, totale, "JPY"), "54000 JPY")
        self.assertNotIn(".", RouterHTTP._fmt_importo(None, totale, "JPY"))

    def test_2_email_e_voucher_in_giapponese(self):
        q, b = self._prenota_giapponese()
        # l'email del voucher e' partita ed e' in giapponese
        self.assertTrue(INVIATE, "nessuna email spedita")
        html = "".join(m["html"] for m in INVIATE)
        self.assertTrue(any(k in html for k in ("予約", "バウチャー", "お支払い")),
                        "l'email non e' in giapponese")
        # nessun testo italiano di sistema
        import re
        piatto = re.sub(r"<[^>]+>", " ", html)
        self.assertNotIn("Prenotazione", piatto)
        self.assertNotIn("Conserva questa email", piatto)
        # la lingua e' nel gettone firmato del voucher
        v = self.sys.firma.decodifica(b["voucher_token"])
        self.assertEqual(v.get("lang"), "ja")
        # il link del voucher nell'email porta ?lang=ja
        self.assertIn("?lang=ja", html)

    def test_3_pass_serratura_alle_15_di_HONOLULU(self):
        _q, b = self._prenota_giapponese()
        pass_token = b.get("smart_pass") or \
            self.sys.firma.decodifica(b["voucher_token"]).get("smart_pass")
        self.assertTrue(pass_token, "nessun pass emesso")
        payload = json.loads(base64.urlsafe_b64decode(pass_token.split(".")[0]))
        valido_da = payload["valido_da"]
        # 15:00 a Honolulu del 5 settembre
        atteso = int(dt.datetime(2026, 9, 5, 15, 0, 0,
                                 tzinfo=ZoneInfo("Pacific/Honolulu")).timestamp())
        self.assertEqual(valido_da, atteso,
                         "il pass NON si apre alle 15:00 di Honolulu")
        # e NON alle 15:00 di Tokyo (il fuso dell'ospite) ne' UTC
        tokyo = int(dt.datetime(2026, 9, 5, 15, 0, 0,
                                tzinfo=ZoneInfo("Asia/Tokyo")).timestamp())
        self.assertNotEqual(valido_da, tokyo)
        self.assertEqual((valido_da - tokyo) / 3600, 19,
                         "19 ore di scarto fra Tokyo e Honolulu: il fuso dev'essere quello "
                         "dell'ALLOGGIO")

    def test_4_finestra_contestazione_ancorata_a_honolulu(self):
        _q, b = self._prenota_giapponese()
        gar = self.sys.garanzia.stato(b["riferimento"])
        self.assertIsNotNone(gar, "escrow non aperto")
        # l'apertura e' ancorata alle 15:00 di Honolulu -> lo sblocco e' 24h dopo
        apertura_attesa = int(dt.datetime(2026, 9, 5, 15, 0, 0,
                                          tzinfo=ZoneInfo("Pacific/Honolulu")).timestamp())
        self.assertEqual(gar.get("sblocco_auto_ts"), apertura_attesa + 24 * 3600)

    def test_5_ripensamento_in_secondi_veri(self):
        _q, b = self._prenota_giapponese()
        v = self.sys.firma.decodifica(b["voucher_token"])
        ts = v.get("prenotato_ts")
        self.assertIsInstance(ts, int, "l'istante della prenotazione non e' nel voucher")
        # e' un istante vero, vicino ad ora (non una data di calendario)
        self.assertLess(abs(int(time.time()) - ts), 120)
        from fase83_server import SECONDI_RIPENSAMENTO, _entro_ripensamento
        self.assertEqual(SECONDI_RIPENSAMENTO, 172800)
        # 47h dopo: dentro; 49h dopo: fuori — a prescindere dal giorno di calendario
        self.assertTrue(_entro_ripensamento({"prenotato_ts": int(time.time()) - 47 * 3600}))
        self.assertFalse(_entro_ripensamento({"prenotato_ts": int(time.time()) - 49 * 3600}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
