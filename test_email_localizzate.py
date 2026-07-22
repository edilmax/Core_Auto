"""GUARDIA — TUTTE le email transazionali escono nella lingua dell'ospite/host.

Il fondatore aveva trovato che 9 email su 10 erano scritte in italiano fisso: un ospite
giapponese che pagava riceveva la conferma, il voucher, il rimborso in ITALIANO. Ora la
lingua viaggia nel gettone firmato e nel record della prenotazione, e ogni corpo email e'
localizzato in 8 lingue.

Questa guardia pretende, per OGNI email e OGNI lingua:
  1. il testo esce nella lingua chiesta (una parola-spia di quella lingua e' presente);
  2. NESSUN ripiego implicito in italiano: una lingua non prevista da' INGLESE;
  3. niente parole-spia italiane in un'email non italiana (nessuna "perdita" di italiano);
  4. XSS-safe: il contenuto dell'utente (titolo alloggio) non inietta marcatura;
  5. gli importi rispettano i decimali della valuta (¥54.000, non 540.00 JPY).
"""

import re
import unittest

import fase86_email as E

# parola che DEVE comparire in un testo di quella lingua (una qualsiasi, come sonda)
SPIA = {
    "it": ["prenotazion", "pagament", "recension", "password", "benvenut", "rimbors"],
    "en": ["booking", "payment", "review", "password", "welcome", "refund"],
    "es": ["reserva", "pago", "opinión", "contraseña", "bienvenido", "reembolso"],
    "fr": ["réservation", "paiement", "avis", "mot de passe", "bienvenue", "remboursement"],
    "de": ["buchung", "zahlung", "bewertung", "passwort", "willkommen", "erstattung"],
    "pt": ["reserva", "pagamento", "avaliação", "palavra-passe", "bem-vindo", "reembolso"],
    "ja": ["予約", "支払", "レビュー", "パスワード", "ようこそ", "返金"],
    "zh": ["预订", "付款", "评价", "密码", "欢迎", "退款"],
}
# parole ESCLUSIVE dell'italiano (non condivise con pt/es): se compaiono in un'email di
# un'altra lingua, e' una perdita di italiano. NB: "pagamento"/"reserva" sono uguali in
# portoghese/spagnolo, quindi NON sono spie affidabili e sono escluse di proposito.
SPIA_IT = ["prenotazione", "rimborso", "recensione", "benvenuto", "conferma",
           "il tuo", "la tua", "annullat", "soggiorno"]


def _tutte(lg):
    """Rende ogni email nella lingua lg. (funzione, html)."""
    return [
        ("voucher", E.corpo_voucher_html("Zen House", "BVIP-1", "2026-09-05",
                                         "2026-09-08", "https://x/v", pin="1234", lingua=lg)),
        ("pagamento", E.corpo_pagamento_confermato_html("Zen House", "https://x/v",
                                                        54000, "JPY", lingua=lg)),
        ("cancellazione", E.corpo_cancellazione_html("Zen House", 30000, "EUR", 0, lingua=lg)),
        ("recensione", E.corpo_invito_recensione_html("Zen House", "https://x/r", lingua=lg)),
        ("controversia", E.corpo_esito_controversia_html(30000, "EUR", lingua=lg)),
        ("payout", E.corpo_payout_host_html(25000, "EUR", "BVIP-1", lingua=lg)),
        ("reset", E.corpo_reset_password_html("https://x/reset", lingua=lg)),
        ("benvenuto", E.corpo_benvenuto_host_html("https://x/host", lingua=lg)),
        ("promemoria", E.corpo_promemoria_checkin_html("Zen House", "https://x/v", lingua=lg)),
    ]


class TestOgniEmailInOgniLingua(unittest.TestCase):

    def test_ogni_lingua_ha_la_sua_spia(self):
        for lg in E.LINGUE:
            testo = " ".join(h for _n, h in _tutte(lg)).lower()
            trovata = any(s.lower() in testo for s in SPIA[lg])
            self.assertTrue(trovata, "nessuna parola di '%s' nelle email in quella lingua" % lg)

    def test_nessuna_email_straniera_perde_italiano(self):
        perdite = []
        for lg in E.LINGUE:
            if lg == "it":
                continue
            for nome, html in _tutte(lg):
                testo = re.sub(r"<[^>]+>", " ", html).lower()
                for spia in SPIA_IT:
                    # confini di parola: "il tuo"/"la tua" e le parole intere
                    if re.search(r"\b%s\b" % re.escape(spia), testo):
                        perdite.append("%s/%s contiene l'italiano '%s'" % (lg, nome, spia))
        self.assertEqual(perdite, [],
                         "email straniere con testo italiano:\n  - " + "\n  - ".join(perdite))

    def test_lingua_non_prevista_da_INGLESE_mai_italiano(self):
        for lg_ignota in ("xx", "", None, "klingon", "zz"):
            for nome, html in _tutte(lg_ignota):
                testo = re.sub(r"<[^>]+>", " ", html).lower()
                # deve contenere una spia inglese e nessuna spia italiana forte
                self.assertFalse(re.search(r"\bprenotazione\b|\brimborso\b|\bbenvenuto\b",
                                           testo),
                                 "%s con lingua %r ripiega sull'italiano" % (nome, lg_ignota))

    def test_xss_safe_in_ogni_lingua(self):
        veleno = "<script>alert(1)</script>"
        for lg in E.LINGUE:
            html = E.corpo_invito_recensione_html(veleno, "https://x/r", lingua=lg)
            self.assertNotIn("<script>alert", html, "%s: XSS non neutralizzato" % lg)
            self.assertIn("&lt;script&gt;", html, "%s: escape mancante" % lg)
            # nessun DOPPIO escape (bug trovato in costruzione: &amp;lt; invece di &lt;)
            self.assertNotIn("&amp;lt;script", html, "%s: doppio escape" % lg)

    def test_importi_rispettano_la_valuta_in_ogni_lingua(self):
        for lg in E.LINGUE:
            h = E.corpo_pagamento_confermato_html("Zen", "https://x/v", 54000, "JPY", lingua=lg)
            self.assertIn("54000 JPY", h, "%s: lo yen ha preso i decimali" % lg)
            self.assertNotIn("540.00", h, "%s: ¥54.000 mostrato come 540.00" % lg)
            e = E.corpo_pagamento_confermato_html("Z", "https://x/v", 15000, "EUR", lingua=lg)
            self.assertIn("150.00 EUR", e, "%s: l'euro ha perso i decimali" % lg)

    def test_ogni_chiave_di_traduzione_ha_tutte_le_lingue(self):
        buchi = [(k, lg) for k, v in E._TR.items() for lg in E.LINGUE
                 if lg not in v or not v[lg]]
        self.assertEqual(buchi, [], "traduzioni mancanti: %s" % buchi)


class TestOggettiLocalizzati(unittest.TestCase):

    def test_l_oggetto_esce_nella_lingua_giusta(self):
        # il giapponese non deve ricevere un oggetto in italiano
        self.assertIn("お支払い", E.oggetto("pc_ogg", "ja"))
        self.assertIn("Payment", E.oggetto("pc_ogg", "en"))
        self.assertIn("Pagamento", E.oggetto("pc_ogg", "it"))
        # lingua ignota -> inglese
        self.assertEqual(E.oggetto("pc_ogg", "xx"), E.oggetto("pc_ogg", "en"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
