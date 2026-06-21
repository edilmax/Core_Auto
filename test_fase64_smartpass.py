"""
Test Fase 64 - Smart-Pass d'ingresso / self check-in.

Copre: emissione + apertura nella finestra, troppo presto/scaduto, porta sbagliata,
firma manomessa, date invalide, revoca (consentito/negato/fail-closed su errore),
payload Wallet, robustezza (mai solleva). Orologio iniettato per determinismo.
"""
import base64
import json
import unittest

from fase59_concierge import FirmaQuote
from fase64_smartpass import (
    EmettitorePass, EsitoAccesso, VerificatorePass, _epoch_da_data_ora,
    costruisci_pass_wallet, crea_emettitore_pass, crea_verificatore_pass,
)

SEGRETO = b"0123456789abcdef0123456789abcdef"

# finestra: check-in 2026-07-01 15:00 UTC .. check-out 2026-07-03 11:00 UTC
DA = _epoch_da_data_ora("2026-07-01", 15)
A = _epoch_da_data_ora("2026-07-03", 11)
DENTRO = (DA + A) // 2


def _coppia(clock_val):
    em = crea_emettitore_pass(SEGRETO)
    ver = crea_verificatore_pass(SEGRETO, orologio=lambda: clock_val[0])
    return em, ver


class TestFinestra(unittest.TestCase):
    def test_apre_nella_finestra(self):
        clock = [DENTRO]
        em, ver = _coppia(clock)
        token = em.emetti("p1", "casa", "2026-07-01", "2026-07-03")
        self.assertTrue(ver.verifica(token, "casa").consentito)

    def test_troppo_presto(self):
        clock = [DA - 3600]
        em, ver = _coppia(clock)
        token = em.emetti("p1", "casa", "2026-07-01", "2026-07-03")
        e = ver.verifica(token, "casa")
        self.assertFalse(e.consentito)
        self.assertEqual(e.motivo, "troppo_presto")

    def test_scaduto(self):
        clock = [A + 3600]
        em, ver = _coppia(clock)
        token = em.emetti("p1", "casa", "2026-07-01", "2026-07-03")
        e = ver.verifica(token, "casa")
        self.assertFalse(e.consentito)
        self.assertEqual(e.motivo, "scaduto")

    def test_estremi_inclusi(self):
        em = crea_emettitore_pass(SEGRETO)
        token = em.emetti("p1", "casa", "2026-07-01", "2026-07-03")
        for t in (DA, A):
            ver = crea_verificatore_pass(SEGRETO, orologio=lambda tt=t: tt)
            self.assertTrue(ver.verifica(token, "casa").consentito)


class TestSicurezza(unittest.TestCase):
    def test_porta_sbagliata(self):
        ver = crea_verificatore_pass(SEGRETO, orologio=lambda: DENTRO)
        token = crea_emettitore_pass(SEGRETO).emetti("p1", "casa", "2026-07-01",
                                                     "2026-07-03")
        e = ver.verifica(token, "villa-vicina")
        self.assertFalse(e.consentito)
        self.assertEqual(e.motivo, "alloggio_errato")

    def test_firma_manomessa(self):
        ver = crea_verificatore_pass(SEGRETO, orologio=lambda: DENTRO)
        token = crea_emettitore_pass(SEGRETO).emetti("p1", "casa", "2026-07-01",
                                                     "2026-07-03")
        b64, sig = token.split(".")
        payload = json.loads(base64.urlsafe_b64decode(b64))
        payload["valido_a"] = payload["valido_a"] + 10 * 86400   # prova a prolungare
        b64f = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode()
        e = ver.verifica(b64f + "." + sig, "casa")
        self.assertFalse(e.consentito)
        self.assertEqual(e.motivo, "pass_non_valido")

    def test_chiave_diversa(self):
        token = crea_emettitore_pass(SEGRETO).emetti("p1", "casa", "2026-07-01",
                                                     "2026-07-03")
        ver = crea_verificatore_pass(b"X" * 32, orologio=lambda: DENTRO)
        self.assertFalse(ver.verifica(token, "casa").consentito)

    def test_token_garbage(self):
        ver = crea_verificatore_pass(SEGRETO, orologio=lambda: DENTRO)
        for bad in (None, 123, "", "a.b", "senza-punto"):
            self.assertFalse(ver.verifica(bad, "casa").consentito)


class TestRevoca(unittest.TestCase):
    def test_revocato_negato(self):
        ver = crea_verificatore_pass(SEGRETO, orologio=lambda: DENTRO,
                                     revocato=lambda pid: pid == "p1")
        token = crea_emettitore_pass(SEGRETO).emetti("p1", "casa", "2026-07-01",
                                                     "2026-07-03")
        e = ver.verifica(token, "casa")
        self.assertFalse(e.consentito)
        self.assertEqual(e.motivo, "revocato")

    def test_non_revocato_consentito(self):
        ver = crea_verificatore_pass(SEGRETO, orologio=lambda: DENTRO,
                                     revocato=lambda pid: False)
        token = crea_emettitore_pass(SEGRETO).emetti("p2", "casa", "2026-07-01",
                                                     "2026-07-03")
        self.assertTrue(ver.verifica(token, "casa").consentito)

    def test_revoca_che_solleva_fail_closed(self):
        def boom(pid):
            raise RuntimeError("db revoche giu'")
        ver = crea_verificatore_pass(SEGRETO, orologio=lambda: DENTRO, revocato=boom)
        token = crea_emettitore_pass(SEGRETO).emetti("p1", "casa", "2026-07-01",
                                                     "2026-07-03")
        e = ver.verifica(token, "casa")
        self.assertFalse(e.consentito)                       # fail-closed: NEGA
        self.assertEqual(e.motivo, "verifica_revoca_fallita")


class TestEmissione(unittest.TestCase):
    def test_date_invalide_none(self):
        em = crea_emettitore_pass(SEGRETO)
        self.assertIsNone(em.emetti("p1", "casa", "non-data", "2026-07-03"))
        self.assertIsNone(em.emetti("p1", "casa", "2026-07-03", "2026-07-01"))  # invertite

    def test_orari_configurabili(self):
        em = EmettitorePass(FirmaQuote(SEGRETO), ora_checkin=14, ora_checkout=10)
        token = em.emetti("p1", "casa", "2026-07-01", "2026-07-03")
        da = _epoch_da_data_ora("2026-07-01", 14)
        ver_prima = crea_verificatore_pass(SEGRETO, orologio=lambda: da - 60)
        ver_dopo = crea_verificatore_pass(SEGRETO, orologio=lambda: da + 60)
        self.assertFalse(ver_prima.verifica(token, "casa").consentito)
        self.assertTrue(ver_dopo.verifica(token, "casa").consentito)


class TestWallet(unittest.TestCase):
    def test_payload(self):
        token = crea_emettitore_pass(SEGRETO).emetti("p1", "casa", "2026-07-01",
                                                     "2026-07-03")
        p = costruisci_pass_wallet(token, alloggio_id="casa", titolo="Casa al mare",
                                   check_in="2026-07-01", check_out="2026-07-03")
        self.assertEqual(p["payload"], token)
        self.assertEqual(p["formato"], "qr")
        self.assertIn("istruzioni", p)


if __name__ == "__main__":
    unittest.main()
