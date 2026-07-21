"""GUARDIA — email normalizzata, alloggio chiamato col suo NOME, lingua conservata.

Nasce da un audit chiesto dal fondatore su input e casi limite. Quattro difetti veri,
trovati **facendo il giro** (registrazione → pubblicazione → preventivo → prenotazione →
email → contratto) e non leggendo il codice.

1) L'EMAIL DELL'OSPITE NON VENIVA NORMALIZZATA.
   `Mario.Rossi@Gmail.com` restava tale e finiva cosi' nell'archivio `pendenti`, quello
   del recupero pagamento. Quella dell'HOST invece era gia' normalizzata: il sistema era
   incoerente con se stesso. La stessa persona che scrive una volta con la maiuscola e
   una volta senza diventa due persone; e i controlli che confrontano in minuscolo (il
   tetto anti-abuso sui preventivi) non riconoscono la riga salvata com'e' stata digitata.

2) L'ALLOGGIO VENIVA CHIAMATO COL SUO SLUG.
   Nell'email del voucher e nel **contratto PDF** compariva `attico-citta-studi` invece
   di «Attico Citta' Studi». Sul contratto e' serio: e' il documento che identifica il
   bene locato, e lo identificava con una stringa presa dall'indirizzo web. Il titolo era
   gia' a disposizione — `_contratto` chiamava gia' `catalogo.dettaglio()` per la citta'
   e buttava via il nome.

3) LE LETTERE FUORI DA LATIN-1 DIVENTAVANO `?`.
   Il PDF usa i font base: «Lukasz» col L polacco diventava `?ukasz`. Ora quelle lettere
   si traslitterano (restano leggibili e giuste); per cio' che resta irrappresentabile
   (giapponese, cinese) si usa lo SLUG, che e' ASCII per costruzione — meglio un
   identificativo tecnico ma leggibile che quattro punti interrogativi su un contratto.

4) LA LINGUA DELL'OSPITE NON VENIVA CONSERVATA.
   Il browser non la mandava al momento di prenotare, e nulla la salvava: ogni email e
   ogni pagina successiva ripiegavano sull'italiano. Ora viaggia dentro il **gettone
   firmato del voucher** (l'unico contenitore che accompagna la prenotazione ovunque, e
   non e' manomettibile) e ogni link del voucher spedito per email porta `?lang=`.
   Quando la lingua non si sa il ripiego e' **inglese**: su un mercato mondiale
   «non lo so» non puo' voler dire «italiano».
"""

import json
import re
import shutil
import tempfile
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

TITOLO = "Attico Città Studî di Łukasz"     # accenti latini + una lettera polacca
INVIATE = []


def _fake_fetch(url, body, headers):
    return {"url": "https://t/x", "id": "cs_x"}


class _ProviderEmailFinto:
    def invia(self, destinatario, oggetto, html):
        INVIATE.append({"a": destinatario, "oggetto": oggetto, "html": html})
        return True


class _Giro(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        del INVIATE[:]
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"I" * 32, con_registrazione_host=True,
            db_catalogo="%s/c.db" % d, db_inventario="%s/i.db" % d,
            db_registro_host="%s/r.db" % d, db_accettazioni="%s/a.db" % d,
            db_pendenti="%s/p.db" % d, db_payout="%s/y.db" % d,
            db_garanzia="%s/g.db" % d, db_tassa_comunale="%s/t.db" % d,
            commissione_bps=1000, psp_bps=300, stripe_secret_key="sk"))
        self.sys.email_provider = _ProviderEmailFinto()
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        st, c = self.g("POST", "/api/host/registrazione",
                       {"email": "Host.Grande@Gmail.COM", "password": "password1",
                        "accetta_termini": True, "accetta_clausole": True,
                        "accetta_privacy": True, "doc_sha256": doc_sha256(),
                        "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(st, 201, c)
        self.tok = c["token"]
        st, c = self.g("POST", "/api/host/pubblica",
                       {"slug": "attico-studi", "titolo": TITOLO, "citta": "Torino",
                        "prezzo_notte_cents": 15000, "valuta": "EUR", "capacita": 2,
                        "politica_cancellazione": "flessibile"},
                       {"X-Host-Token": self.tok})
        self.assertIn(st, (200, 201), c)
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "attico-studi", "da": "2026-09-01", "a": "2026-10-30",
                "unita_totali": 1, "prezzo_netto_cents": 15000},
               {"X-Host-Token": self.tok})

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _prenota(self, email="Mario.Rossi@Gmail.com", lang="ja",
                 ci="2026-09-05", co="2026-09-08"):
        st, q = self.g("POST", "/api/concierge/quote",
                       {"alloggio_id": "attico-studi", "check_in": ci,
                        "check_out": co, "party": 2})
        self.assertEqual(st, 200, q)
        corpo = {"quote_token": q["quote_token"], "email": email}
        if lang is not None:
            corpo["lang"] = lang
        st, b = self.g("POST", "/api/concierge/book", corpo)
        self.assertIn(st, (200, 201), b)
        return b


class TestEmailNormalizzata(_Giro):

    def test_l_email_dell_ospite_va_in_minuscolo(self):
        self._prenota(email="Mario.Rossi@Gmail.com")
        self.assertTrue(INVIATE, "nessuna email spedita")
        for m in INVIATE:
            self.assertEqual(m["a"], m["a"].lower(),
                             "email spedita cosi' com'e' digitata: %r" % m["a"])

    def test_maiuscole_e_minuscole_sono_la_STESSA_persona(self):
        del INVIATE[:]          # via l'email di benvenuto dell'host: qui conta l'OSPITE
        self._prenota(email="Mario.Rossi@Gmail.com", ci="2026-09-05", co="2026-09-08")
        self._prenota(email="mario.rossi@gmail.com", ci="2026-09-20", co="2026-09-22")
        ospiti = {m["a"] for m in INVIATE if "rossi" in m["a"].lower()}
        self.assertEqual(ospiti, {"mario.rossi@gmail.com"},
                         "la stessa persona risulta due indirizzi diversi: %s" % ospiti)

    def test_anche_l_host_resta_normalizzato(self):
        """Era gia' cosi': qui si pretende che RESTI, cosi' i due lati non divergono.
        Si prova entrando: se l'indirizzo fosse salvato con le maiuscole, l'accesso in
        minuscolo non funzionerebbe."""
        for scritto in ("host.grande@gmail.com", "HOST.GRANDE@GMAIL.COM",
                        "  Host.Grande@Gmail.Com  "):
            e = self.sys.registro_host.login(scritto, "password1")
            self.assertTrue(getattr(e, "ok", False),
                            "l'host non entra scrivendo %r: l'indirizzo non e' "
                            "normalizzato" % scritto)


class TestAlloggioChiamatoColSuoNome(_Giro):

    def test_l_email_del_voucher_mostra_il_NOME_non_lo_slug(self):
        self._prenota()
        html = "".join(m["html"] for m in INVIATE)
        self.assertIn("Attico", html,
                      "l'email non nomina l'alloggio col suo titolo")
        self.assertNotIn("attico-studi", html,
                         "l'email chiama l'alloggio con lo slug dell'indirizzo web")

    def test_il_contratto_identifica_il_bene_col_suo_NOME(self):
        b = self._prenota()
        st, c = self.g("POST", "/api/contratto",
                       {"voucher_token": b["voucher_token"], "lingua": "it"})
        self.assertEqual(st, 200, c)
        righe = " | ".join(str(x) for x in (c.get("righe") or []))
        self.assertIn("Attico", righe,
                      "il contratto identifica l'immobile con lo slug: %s" % righe[:200])

    def test_gli_accenti_sopravvivono_fino_al_contratto(self):
        b = self._prenota()
        st, c = self.g("POST", "/api/contratto",
                       {"voucher_token": b["voucher_token"], "lingua": "it"})
        righe = " | ".join(str(x) for x in (c.get("righe") or []))
        self.assertIn("Città", righe, "gli accenti si perdono: %s" % righe[:200])


class TestCaratteriFuoriDaLatin1(unittest.TestCase):
    """Il PDF usa i font base: quello che non ci sta va traslitterato, non buttato."""

    def test_le_lettere_europee_si_traslitterano(self):
        from fase145_contratto_pdf import _escape
        for prima, dopo in (("Łukasz", "Lukasz"), ("Şişli", "Sisli"),
                            ("Đorđe", "Dorde"), ("Škoda", "Skoda")):
            self.assertEqual(_escape(prima), dopo,
                             "%r diventa %r invece di %r" % (prima, _escape(prima), dopo))

    def test_gli_accenti_latini_restano_intatti(self):
        from fase145_contratto_pdf import _escape
        for t in ("Città", "Zoë", "Müller", "Straße", "François"):
            self.assertEqual(_escape(t), t, "%r viene alterato: %r" % (t, _escape(t)))

    def test_si_sa_riconoscere_cio_che_NON_si_puo_scrivere(self):
        """Serve a chi chiama, per ripiegare invece di stampare '????'."""
        from fase145_contratto_pdf import rappresentabile
        self.assertTrue(rappresentabile("Attico Città di Łukasz"))
        self.assertFalse(rappresentabile("日本の宿"))
        self.assertFalse(rappresentabile("Москва"))


class TestLinguaDellOspiteConservata(_Giro):

    def _lingua_nel_gettone(self, b):
        v = self.sys.firma.decodifica(b.get("voucher_token")) or {}
        return v.get("lang")

    def _lingua_nel_link(self):
        html = "".join(m["html"] for m in INVIATE)
        m = re.search(r"/voucher/[^\"'?]+\?lang=(\w+)", html)
        return m.group(1) if m else None

    def test_la_lingua_scelta_arriva_fino_al_link_del_voucher(self):
        for i, lang in enumerate(("ja", "de", "zh", "es")):
            with self.subTest(lang=lang):
                del INVIATE[:]
                b = self._prenota(lang=lang, ci="2026-09-%02d" % (2 + i * 5),
                                  co="2026-09-%02d" % (4 + i * 5))
                self.assertEqual(self._lingua_nel_gettone(b), lang,
                                 "il gettone non conserva la lingua")
                self.assertEqual(self._lingua_nel_link(), lang,
                                 "il link del voucher nell'email non porta la lingua: "
                                 "la pagina ripiegherebbe sull'italiano")

    def test_lingua_ignota_o_assente_ripiega_su_INGLESE_non_su_italiano(self):
        for i, lang in enumerate((None, "xx", "")):
            with self.subTest(lang=lang):
                del INVIATE[:]
                b = self._prenota(lang=lang, ci="2026-10-%02d" % (2 + i * 5),
                                  co="2026-10-%02d" % (4 + i * 5))
                self.assertEqual(
                    self._lingua_nel_gettone(b), "en",
                    "con lingua %r si ripiega su %r: su un mercato mondiale «non lo so» "
                    "non puo' voler dire «italiano»"
                    % (lang, self._lingua_nel_gettone(b)))

    def test_il_browser_manda_davvero_la_lingua_quando_prenota(self):
        """Il cablaggio: senza questa riga nella pagina, tutto il resto e' inutile."""
        import io
        import os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "deploy", "index.html")
        with io.open(p, encoding="utf-8") as f:
            testo = f.read()
        self.assertRegex(
            testo, r"quote_token\s*:\s*QUOTE\s*,\s*email\s*:\s*email\s*,\s*lang\s*:\s*LANG",
            "la pagina prenota senza mandare la lingua: il server non avrebbe nulla da "
            "conservare e ogni email successiva ripiegherebbe sull'inglese")


class TestContrattoNonRipiegaSullItaliano(_Giro):

    def test_una_lingua_non_prevista_da_l_INGLESE(self):
        b = self._prenota(lang="ja")
        st, c = self.g("POST", "/api/contratto",
                       {"voucher_token": b["voucher_token"], "lingua": "ja"})
        self.assertEqual(st, 200, c)
        righe = " | ".join(str(x) for x in (c.get("righe") or []))
        self.assertIn("Total price", righe,
                      "un ospite giapponese riceve il contratto in italiano: %s"
                      % righe[:200])
        self.assertNotIn("Corrispettivo totale", righe)

    def test_l_italiano_esplicito_resta_italiano(self):
        b = self._prenota(lang="it")
        st, c = self.g("POST", "/api/contratto",
                       {"voucher_token": b["voucher_token"], "lingua": "it"})
        righe = " | ".join(str(x) for x in (c.get("righe") or []))
        self.assertIn("Corrispettivo totale", righe)


if __name__ == "__main__":
    unittest.main(verbosity=2)
