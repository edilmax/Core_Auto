"""Test collaudo — l'endpoint preventivo-email non deve diventare un mezzo per spammare terzi.

BUG PROVATO (collaudo 2026-07-15): `POST /api/preventivo/email` manda posta a un indirizzo
scelto dal CHIAMANTE. Il throttle esisteva ma con chiave `(email, alloggio, check_in, check_out)`
-> bastava **cambiare data** per avere un secchiello nuovo. Prova: 5 richieste con 5 date
diverse -> **5 email spedite alla stessa vittima, zero 429**.

Perche' e' grave (il danno non e' lo spam in se'): le email partono da info@bookinvip.com con
la SMTP del fondatore. Un abusante che bombarda estranei fa finire il dominio in BLACKLIST ->
voucher e avvisi agli host **non vengono piu' consegnati**: il prodotto muore in silenzio.

FIX: tetto per INDIRIZZO (MAX_PREVENTIVI_EMAIL_ORA/ora), indipendente da annuncio e date,
in aggiunta al throttle esistente per (email,alloggio,date).
"""
from __future__ import annotations

import json
import unittest

from fase57_vetrina import SchedaAlloggio
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import MAX_PREVENTIVI_EMAIL_ORA, crea_router


class _ProviderFinto:
    """Conta gli invii senza mandare nulla (regola: mai email a estranei, nemmeno nei test)."""
    def __init__(self):
        self.inviate = []

    def invia(self, dest, oggetto, html):
        self.inviate.append(dest)
        return True


class TestAbusoEmailPreventivo(unittest.TestCase):

    def setUp(self):
        self.sys = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"0" * 32))
        self.p = _ProviderFinto()
        self.sys.email_provider = self.p
        self.sys.catalogo.pubblica(SchedaAlloggio(
            host_id="h", slug="casa-x", titolo="T", citta="Roma",
            prezzo_notte_cents=10000, capacita=2))
        for g in range(1, 12):
            self.sys.inventario.imposta_disponibilita(
                "casa-x", "2026-09-%02d" % g, unita_totali=1, prezzo_netto_cents=10000)
        self.r = crea_router(self.sys)

    def _chiedi(self, email, giorno):
        return self.r.gestisci("POST", "/api/preventivo/email", body=json.dumps({
            "email": email, "alloggio_id": "casa-x",
            "check_in": "2026-09-%02d" % giorno, "check_out": "2026-09-%02d" % (giorno + 1)}))[0]

    def test_cambiare_data_non_aggira_piu_il_tetto(self):
        """Il bug: date diverse = secchielli diversi -> email illimitate a una vittima."""
        esiti = [self._chiedi("vittima@estraneo.example", g) for g in range(1, 8)]
        self.assertEqual(esiti.count(200), MAX_PREVENTIVI_EMAIL_ORA,
                         "passate %s email invece di %d" % (esiti.count(200),
                                                            MAX_PREVENTIVI_EMAIL_ORA))
        self.assertGreater(esiti.count(429), 0, "il tetto per indirizzo non scatta")
        self.assertEqual(len(self.p.inviate), MAX_PREVENTIVI_EMAIL_ORA,
                         "spedite piu' email del tetto: si puo' ancora bombardare")

    def test_utente_vero_non_penalizzato(self):
        """Il tetto e' per INDIRIZZO: un altro utente non deve pagare per l'abusante."""
        for g in range(1, 8):
            self._chiedi("abusante@estraneo.example", g)
        self.assertEqual(self._chiedi("utente.vero@example.com", 1), 200,
                         "un utente vero viene bloccato dall'abuso di un altro")

    def test_doppio_invio_stesse_date_bloccato(self):
        """Il throttle originale (anti doppio-clic) deve restare."""
        self.assertEqual(self._chiedi("tizio@example.com", 1), 200)
        self.assertEqual(self._chiedi("tizio@example.com", 1), 429)

    def test_memoria_non_cresce_all_infinito(self):
        """La storia per indirizzo va potata: e' in-process, non deve diventare un leak."""
        for i in range(30):
            self._chiedi("u%d@example.com" % i, 1)
        storia = getattr(self.r, "_prev_email_storia", {})
        self.assertTrue(all(v for v in storia.values()),
                        "restano chiavi vuote: la potatura non funziona")


if __name__ == "__main__":
    unittest.main()
