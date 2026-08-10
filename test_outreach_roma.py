"""GUARDIA — reclutamento host di ROMA (fase89.componi_email_prima_roma): 8 lingue SINCRONIZZATE
con la web app (it/en/es/fr/de/pt/ja/zh), cifre REALI di fase98, opt-out obbligatorio (GDPR),
e la tariffa tecnica dichiarata in OGNI lingua (regola d'oro: dirla PRIMA della firma).

Vista ROSSA: se manca una lingua, se una cifra non si aggiorna, se resta un {segnaposto}, o se
sparisce la tariffa tecnica da una lingua, questi asserti falliscono.

⛔ La CIFRA non e' scritta qui e non deve esserlo: si legge dal motore (`_tecnica_bps()`).
Questo file diceva «3%» fino al 2026-08-10, e la prosa e' rimasta indietro al primo cambio.
Un commento che nomina la cifra puo' diventare falso; uno che non la nomina, no.
"""
import unittest

import fase89_jurisdiction_outreach as O
from fase98_policy_commissione import (BPS_DIRETTO, LANCIO_BPS_FASE1, LANCIO_BPS_REGIME,
                                       LANCIO_GIORNI_GRATIS)

LINGUE_WEBAPP = ("it", "en", "es", "fr", "de", "pt", "ja", "zh")
OPT = "https://bookinvip.com/stop"


def _c(paese="IT", nome="Marco", email="host@roma.it"):
    return O.Contatto(email=email, nome=nome, paese=paese)


class TestOutreachRoma(unittest.TestCase):
    def test_otto_lingue_della_webapp(self):
        self.assertEqual(set(O._TEMPLATE_ROMA), set(LINGUE_WEBAPP),
                         "il set di lingue deve combaciare con la web app (fase86.LINGUE)")

    def test_cifre_reali_di_fase98_e_nessun_segnaposto(self):
        for lng in LINGUE_WEBAPP:
            r = O.componi_email_prima_roma(_c(), 1000, link_opt_out=OPT, lingua=lng)
            self.assertIsNotNone(r, lng)
            _l, ogg, corpo = r
            # cifre reali (0% promo, 90 giorni, 8/10/5/3%)
            self.assertIn(str(LANCIO_GIORNI_GRATIS), corpo, lng)          # 90
            for n in (LANCIO_BPS_FASE1, LANCIO_BPS_REGIME, BPS_DIRETTO):  # 8/10/5
                self.assertIn("%d%%" % (n // 100), corpo, "%s manca %d" % (lng, n // 100))
            # nessun placeholder rimasto né nell'oggetto né nel corpo
            for campo in (ogg, corpo):
                self.assertNotIn("{", campo, "%s: segnaposto non sostituito" % lng)
                self.assertNotIn("}", campo, lng)

    def test_lingua_sincronizzata_con_la_scelta(self):
        # passare la lingua della web app fa uscire il messaggio in QUELLA lingua
        marker = {"it": "Ciao", "en": "Hi ", "es": "Hola", "fr": "Bonjour",
                  "de": "Hallo", "pt": "Olá", "ja": "様", "zh": "您好"}
        for lng, m in marker.items():
            _l, _o, corpo = O.componi_email_prima_roma(_c(), 1000, link_opt_out=OPT, lingua=lng)
            self.assertEqual(_l, lng)
            self.assertIn(m, corpo, "%s: la lingua non è sincronizzata" % lng)

    def test_ripiego_su_inglese_mai_italiano(self):
        # lingua sconosciuta -> inglese (come il ripiego del sito), MAI italiano
        lng, _o, corpo = O.componi_email_prima_roma(_c(paese="XX"), 1000,
                                                    link_opt_out=OPT, lingua="xx")
        self.assertEqual(lng, "en")
        self.assertIn("commission", corpo)
        self.assertNotIn("commissione", corpo)

    def test_tariffa_3pct_dichiarata_in_ogni_lingua(self):
        # onestà: la tariffa tecnica va detta PRIMA della firma, in TUTTE le lingue
        for lng in LINGUE_WEBAPP:
            _l, _o, corpo = O.componi_email_prima_roma(_c(), 1000, link_opt_out=OPT, lingua=lng)
            # la cifra si prende DAL MOTORE: scriverla a mano qui e' come tacerla,
            # perche' il giorno che cambia il test resta verde su una bugia.
            _t = "%d%%" % (O._tecnica_bps() // 100)
            self.assertIn(_t, corpo, "%s: manca la tariffa tecnica %s (disonesto)"
                          % (lng, _t))

    def test_optout_obbligatorio_e_email_valida(self):
        self.assertIsNone(O.componi_email_prima_roma(_c(), 1000, link_opt_out="", lingua="it"),
                          "senza opt-out deve tornare None (GDPR)")
        self.assertIsNone(O.componi_email_prima_roma(_c(email="non-una-email"), 1000,
                                                     link_opt_out=OPT, lingua="it"))

    def test_opt_out_nel_corpo(self):
        _l, _o, corpo = O.componi_email_prima_roma(_c(), 1000, link_opt_out=OPT, lingua="it")
        self.assertIn(OPT, corpo, "il link di disiscrizione deve comparire nel corpo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
