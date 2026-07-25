"""GUARDIA — email e notifiche coerenti con lo stato del pagamento (direttiva fondatore:
"anche mail e bot messaggistica devono essere giusti, mai mandare cose sbagliate prima del pagamento").

Contratto:
- EMAIL cliente (`corpo_voucher_html`): se c'è un pagamento da completare (payment_url), NON contiene il
  PIN e mostra il pulsante di pagamento; a pagamento fatto (nessun payment_url) il PIN c'è.
  [Il chiamante in fase83._finalizza_prenotazione passa pin="" quando payment_url è presente.]
- NOTIFICA HOST (`componi_avviso_host`): senza pin -> nessuna riga PIN; con pin -> la riga c'è.
  [Il chiamante passa pin="" quando il pagamento è pendente.]
Vista ROSSA: se il PIN comparisse in un documento pre-pagamento, questi asserti lo vedrebbero.
"""
import unittest

from fase86_email import corpo_voucher_html


class TestEmailStatoPagamento(unittest.TestCase):
    def test_email_pre_pagamento_niente_pin_ma_bottone_paga(self):
        h = corpo_voucher_html("Attico Roma", "BVIP-1234-5678", "2026-09-01", "2026-09-03",
                               "https://bookinvip.com/voucher/tok", pin="",
                               payment_url="https://pay.stripe/x", lingua="it")
        self.assertNotIn("9999", h)                        # nessun PIN reale
        self.assertNotIn("PIN check-in", h)                # nessuna riga PIN
        self.assertIn("pay.stripe", h)                     # c'è il link di pagamento

    def test_email_post_pagamento_ha_il_pin(self):
        h = corpo_voucher_html("Attico Roma", "BVIP-1234-5678", "2026-09-01", "2026-09-03",
                               "https://bookinvip.com/voucher/tok", pin="4321",
                               payment_url="", lingua="it")
        self.assertIn("4321", h)                           # PIN presente a pagamento fatto
        self.assertNotIn("pay.stripe", h)                  # nessun invito a pagare


class TestPreventivoSoloPreventivo(unittest.TestCase):
    """Il PREVENTIVO (fase più a monte) deve essere SOLO preventivo: prezzo + date + invito a
    prenotare. MAI PIN, smart-pass, controversia o voucher (quelli nascono dopo il pagamento)."""

    def test_email_preventivo_niente_pin_ne_postvendita(self):
        from fase86_email import corpo_preventivo_html
        h = corpo_preventivo_html("Attico Roma", "2026-09-01", "2026-09-03",
                                  [("2 notti", "€200,00"), ("Tassa soggiorno", "€8,00")],
                                  "https://bookinvip.com/prenota/x", lingua="it")
        for vietato in ("PIN", "smart_pass", "garanzia", "controvers", "serratura",
                        "self check-in", "self-check", "voucher_token", "/api/garanzia/"):
            self.assertNotIn(vietato, h, "il preventivo NON deve contenere %r" % vietato)
        self.assertIn("200", h)                            # il prezzo c'è
        self.assertIn("prenota", h.lower())                # invito a prenotare/pagare


class TestNotificaHostStatoPagamento(unittest.TestCase):
    def _avviso(self, pin):
        from fase152_notifiche_prenotazione import componi_avviso_host
        from fase61_localizzazione import Localizzatore
        return componi_avviso_host(Localizzatore(), alloggio="Attico", ci="2026-09-01",
                                   co="2026-09-03", origine="instant", riferimento="BVIP-1-2",
                                   pin=pin, link_pannello="https://bookinvip.com/host.html",
                                   lingua="it")

    def test_host_senza_pin_nessuna_riga_pin(self):
        _ogg, testo = self._avviso("")
        self.assertNotIn("PIN check-in", testo)
        self.assertNotIn("7777", testo)

    def test_host_con_pin_riga_presente(self):
        _ogg, testo = self._avviso("7777")
        self.assertIn("7777", testo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
