"""GUARDIA — la valuta regge dal PREZZO DIGITATO fino all'ADDEBITO, senza cambiare scala.

LA DOMANDA CHE NESSUN TEST FACEVA.
Ogni pezzo della catena era provato per conto suo: la tabella delle valute nel browser, la
convalida della scheda, il calcolo del preventivo, i parametri di Stripe, la formattazione
dell'importo. Nessuno pero' seguiva **lo stesso numero** per tutta la strada chiedendo:

    l'host digita ¥18.000 a notte. Quanto viene addebitato davvero all'ospite?

E' la domanda del fondatore («dal primo prezzo visto sulla pagina fino all'addebito finale
e all'email di ricevuta»), ed e' anche la forma generale del difetto che ha trovato a
occhio: **un errore di SCALA**, non di formato. Un ×100 non fa eccezione, non rompe niente,
non lascia traccia nei log: produce solo un numero piu' grande che sembra ancora un prezzo.

PERCHE' PROPRIO LO YEN.
Perche' non ha decimali. Su una valuta a 2 decimali un errore di scala si vede subito
(18.000 € a notte); sullo yen ¥1.800.000 sembra plausibile a chi non conosce il cambio —
ed e' precisamente cio' che e' andato in vetrina il 2026-07-21 senza che nessuno dei 3011
test se ne accorgesse.

COSA SI SEGUE, ANELLO PER ANELLO
  1. l'host pubblica in JPY il prezzo 18000 (unita' minori dello yen = yen interi);
  2. il preventivo per 3 notti deve dire JPY e 54000 — non 5.400.000;
  3. cio' che va a Stripe deve avere `currency=jpy` e `unit_amount` **identico** al totale
     del preventivo: Stripe vuole lo yen NON moltiplicato per cento;
  4. l'importo scritto per un essere umano non deve avere decimali;
  5. lo stesso giro in EUR deve invece avere i decimali: se sparissero, vorrebbe dire che
     abbiamo "risolto" lo yen rompendo l'euro.

Il confronto fra 2 e 5 e' la parte che conta: prova che il sistema **distingue** le valute,
non che le tratta tutte allo stesso modo.
"""

import json
import re
import shutil
import tempfile
import unittest
import urllib.parse

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

PREZZO_YEN = 18000          # ¥18.000 a notte: un buon hotel a Tokyo
PREZZO_EURO = 15000         # €150,00 a notte, in centesimi
NOTTI = 3

# ogni chiamata a Stripe viene intercettata e conservata: e' l'ADDEBITO vero
CHIAMATE = []


def _fake_fetch(url, body, headers):
    import secrets
    CHIAMATE.append({"url": url, "body": body})
    return {"url": "https://t/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


def _params_ultima_chiamata():
    """I parametri dell'ultima sessione di pagamento, come li riceve Stripe."""
    if not CHIAMATE:
        return {}
    corpo = CHIAMATE[-1]["body"]
    if isinstance(corpo, bytes):
        corpo = corpo.decode("utf-8", "replace")
    return dict(urllib.parse.parse_qsl(str(corpo)))


class _GiroValuta(unittest.TestCase):
    """Un host, un alloggio nella valuta scelta, un preventivo, un pagamento."""

    VALUTA = "EUR"
    PREZZO = PREZZO_EURO

    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        del CHIAMATE[:]
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"V" * 32, con_registrazione_host=True,
            db_catalogo="%s/c.db" % d, db_inventario="%s/i.db" % d,
            db_registro_host="%s/r.db" % d, db_accettazioni="%s/acc.db" % d,
            db_pendenti="%s/p.db" % d, db_payout="%s/pay.db" % d,
            db_garanzia="%s/g.db" % d, db_tassa_comunale="%s/t.db" % d,
            commissione_bps=1000, psp_bps=300, stripe_secret_key="sk",
            stripe_success_url="https://bookinvip.com/grazie.html",
            stripe_cancel_url="https://bookinvip.com/annullato.html"))
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@valuta.it", "password": "password1",
                       "accetta_termini": True, "accetta_clausole": True,
                       "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        s, c = self.g("POST", "/api/host/pubblica",
                      {"slug": "stanza", "titolo": "Stanza", "citta": "Tokyo",
                       "prezzo_notte_cents": self.PREZZO, "valuta": self.VALUTA,
                       "capacita": 2, "politica_cancellazione": "flessibile",
                       "tassa_soggiorno_cents": 0},
                      {"X-Host-Token": self.tok})
        self.assertIn(s, (200, 201), c)
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "stanza", "da": "2026-09-01", "a": "2026-09-30",
                "unita_totali": 1, "prezzo_netto_cents": self.PREZZO},
               {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _preventivo(self):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "stanza", "check_in": "2026-09-05",
                       "check_out": "2026-09-08", "party": 2})
        self.assertEqual(s, 200, q)
        return q

    def _prenota(self, q):
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@valuta.it"})
        self.assertIn(s, (200, 201), b)
        return b


class TestYenNonVieneMoltiplicatoPerCento(_GiroValuta):

    VALUTA = "JPY"
    PREZZO = PREZZO_YEN

    def test_anello_1_l_annuncio_conserva_prezzo_e_valuta(self):
        s, d = self.g("GET", "/api/catalogo/stanza")
        self.assertEqual(s, 200, d)
        self.assertEqual(d.get("valuta"), "JPY", "la valuta si e' persa per strada")
        self.assertEqual(d.get("prezzo_notte_cents"), PREZZO_YEN,
                         "il prezzo e' cambiato di scala fra scrittura e lettura")

    def test_anello_2_il_preventivo_resta_in_yen_interi(self):
        q = self._preventivo()
        self.assertEqual(q.get("valuta"), "JPY",
                         "il preventivo cambia valuta: l'ospite pagherebbe in un'altra "
                         "moneta rispetto a quella vista")
        totale = q.get("totale_cents") or q.get("prezzo_guest_cents")
        self.assertEqual(
            totale, PREZZO_YEN * NOTTI,
            "3 notti a ¥%d devono fare ¥%d. Se qui compare %s, da qualche parte si "
            "moltiplica per cento come se lo yen avesse i decimali."
            % (PREZZO_YEN, PREZZO_YEN * NOTTI, totale))

    def test_anello_3_a_stripe_va_lo_STESSO_numero_e_la_valuta_giusta(self):
        q = self._preventivo()
        self._prenota(q)
        p = _params_ultima_chiamata()
        self.assertTrue(p, "nessuna chiamata a Stripe: l'anello non e' stato percorso")
        self.assertEqual(p.get("line_items[0][price_data][currency]"), "jpy",
                         "Stripe addebiterebbe in un'altra valuta")
        atteso = q.get("totale_cents") or q.get("prezzo_guest_cents")
        self.assertEqual(
            p.get("line_items[0][price_data][unit_amount]"), str(atteso),
            "l'importo mandato a Stripe non e' quello del preventivo: Stripe vuole lo "
            "yen NON moltiplicato per cento")

    def test_anello_4_l_importo_scritto_per_una_persona_non_ha_decimali(self):
        testo = self.r._fmt_importo(PREZZO_YEN * NOTTI, "JPY")
        self.assertNotIn(".", testo, "lo yen non ha decimali: '%s' e' sbagliato" % testo)
        self.assertIn(str(PREZZO_YEN * NOTTI), testo,
                      "l'importo mostrato non e' quello addebitato: '%s'" % testo)

    def test_lo_scarto_fra_visto_e_addebitato_e_zero(self):
        """La domanda in una riga sola: chi guarda paga quello che ha visto?"""
        q = self._preventivo()
        self._prenota(q)
        visto = q.get("totale_cents") or q.get("prezzo_guest_cents")
        addebitato = int(_params_ultima_chiamata()
                         .get("line_items[0][price_data][unit_amount]", -1))
        self.assertEqual(visto, addebitato,
                         "visto ¥%s, addebitato ¥%s" % (visto, addebitato))


class TestEuroNonVienePeggiorato(_GiroValuta):
    """Il controllo dell'altro lato: distinguere le valute, non appiattirle."""

    VALUTA = "EUR"
    PREZZO = PREZZO_EURO

    def test_l_euro_conserva_i_centesimi(self):
        q = self._preventivo()
        self.assertEqual(q.get("valuta"), "EUR")
        totale = q.get("totale_cents") or q.get("prezzo_guest_cents")
        self.assertEqual(totale, PREZZO_EURO * NOTTI)

    def test_l_euro_si_scrive_CON_i_decimali(self):
        testo = self.r._fmt_importo(PREZZO_EURO * NOTTI, "EUR")
        self.assertRegex(testo, r"\d+[.,]\d{2}",
                         "l'euro ha due decimali: '%s' li ha persi (avremmo 'aggiustato' "
                         "lo yen rompendo l'euro)" % testo)

    def test_a_stripe_va_l_euro_in_centesimi(self):
        q = self._preventivo()
        self._prenota(q)
        p = _params_ultima_chiamata()
        self.assertEqual(p.get("line_items[0][price_data][currency]"), "eur")
        self.assertEqual(p.get("line_items[0][price_data][unit_amount]"),
                         str(q.get("totale_cents") or q.get("prezzo_guest_cents")))


class TestLeAltrePorteDelDenaro(unittest.TestCase):
    """Le strade che il giro qui sopra NON attraversa — trovate da una mutazione viva.

    Rompendo `fase101` (valuta fissa "eur") il test end-to-end restava VERDE: la cassa
    vera passa da `fase85`, e `fase101` serve ai BONIFICI verso l'host e al gateway Asia
    (Alipay/WeChat). Un mutante sopravvissuto non e' mai neutro: o il codice e' morto, o
    non e' sorvegliato. Qui non e' morto — sposta denaro — quindi va sorvegliato.
    """

    def test_il_bonifico_all_host_non_moltiplica_lo_yen(self):
        # `trasferisci` sta in ProviderConnect (i bonifici), non in
        # ProviderStripeConnect (le sessioni di pagamento): sbagliare classe qui vuol
        # dire che il finto non intercetta nulla e il test tenta la rete VERA.
        from fase101_stripe_connect import ProviderConnect
        visti = {}

        class Finto(ProviderConnect):
            def _post(self, url, dati, idem_key=None):
                visti.update(dati)
                return {"id": "tr_ok"}

        p = Finto("sk_test")
        p.trasferisci("acct_x", 54000, "JPY", "rif1")
        self.assertEqual(visti.get("amount"), "54000",
                         "l'importo del bonifico e' cambiato di scala")
        self.assertEqual(visti.get("currency"), "jpy",
                         "l'host verrebbe pagato in un'altra valuta")

    def test_il_gateway_asia_rispetta_la_valuta_dell_annuncio(self):
        from fase104_gateway_asia import costruisci_params_asia
        p = costruisci_params_asia(54000, 5400, "acct_x", "alipay", valuta="JPY",
                                   riferimento="r1")
        self.assertIsNotNone(p)
        self.assertEqual(p["line_items[0][price_data][currency]"], "jpy")
        self.assertEqual(p["line_items[0][price_data][unit_amount]"], "54000")

    def test_i_parametri_connect_non_impongono_l_euro(self):
        from fase101_stripe_connect import costruisci_params
        p = costruisci_params(54000, 5400, "acct_x", valuta="JPY", riferimento="r1")
        self.assertIsNotNone(p)
        self.assertEqual(p["line_items[0][price_data][currency]"], "jpy",
                         "la valuta dell'annuncio viene ignorata e si addebita in euro")
        self.assertEqual(p["line_items[0][price_data][unit_amount]"], "54000")


class TestDueValuteNonSiMescolano(unittest.TestCase):
    """Sommare importi di valute diverse e' il modo silenzioso di perdere denaro."""

    def test_il_denaro_tipizzato_rifiuta_le_somme_fra_valute(self):
        from fase99_multicurrency import Denaro
        a, b = Denaro(1000, "EUR"), Denaro(1000, "JPY")
        with self.assertRaises(Exception,
                               msg="EUR + JPY non solleva: si possono mescolare valute"):
            _ = a + b

    def test_stesso_numero_valute_diverse_vale_diversamente(self):
        """1000 in EUR sono 10,00 €; 1000 in JPY sono ¥1.000. Il numero è lo stesso, il
        valore no: e' tutta qui la trappola."""
        from fase99_multicurrency import esponente
        self.assertEqual(esponente("EUR"), 2)
        self.assertEqual(esponente("JPY"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
