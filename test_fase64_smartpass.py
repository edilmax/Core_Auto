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

# La finestra del pass ora e' all'ORA LOCALE dell'alloggio (non UTC per tutti, che era
# il bug). Si ancora a un fuso vero per avere orari esatti e verificabili.
FUSO = "Europe/Rome"
# check-in 2026-07-01 15:00 e check-out 2026-07-03 11:00 ORA DI ROMA
DA = _epoch_da_data_ora("2026-07-01", 15, FUSO)
A = _epoch_da_data_ora("2026-07-03", 11, FUSO)
DENTRO = (DA + A) // 2


def _coppia(clock_val):
    em = crea_emettitore_pass(SEGRETO)
    ver = crea_verificatore_pass(SEGRETO, orologio=lambda: clock_val[0])
    return em, ver


class TestFinestra(unittest.TestCase):
    def test_apre_nella_finestra(self):
        clock = [DENTRO]
        em, ver = _coppia(clock)
        token = em.emetti("p1", "casa", "2026-07-01", "2026-07-03", fuso=FUSO)
        self.assertTrue(ver.verifica(token, "casa").consentito)

    def test_troppo_presto(self):
        clock = [DA - 3600]
        em, ver = _coppia(clock)
        token = em.emetti("p1", "casa", "2026-07-01", "2026-07-03", fuso=FUSO)
        e = ver.verifica(token, "casa")
        self.assertFalse(e.consentito)
        self.assertEqual(e.motivo, "troppo_presto")

    def test_scaduto(self):
        clock = [A + 3600]
        em, ver = _coppia(clock)
        token = em.emetti("p1", "casa", "2026-07-01", "2026-07-03", fuso=FUSO)
        e = ver.verifica(token, "casa")
        self.assertFalse(e.consentito)
        self.assertEqual(e.motivo, "scaduto")

    def test_estremi_inclusi(self):
        em = crea_emettitore_pass(SEGRETO)
        token = em.emetti("p1", "casa", "2026-07-01", "2026-07-03", fuso=FUSO)
        for t in (DA, A):
            ver = crea_verificatore_pass(SEGRETO, orologio=lambda tt=t: tt)
            self.assertTrue(ver.verifica(token, "casa").consentito)


class TestSicurezza(unittest.TestCase):
    def test_porta_sbagliata(self):
        ver = crea_verificatore_pass(SEGRETO, orologio=lambda: DENTRO)
        token = crea_emettitore_pass(SEGRETO).emetti("p1", "casa", "2026-07-01",
                                                     "2026-07-03", fuso=FUSO)
        e = ver.verifica(token, "villa-vicina")
        self.assertFalse(e.consentito)
        self.assertEqual(e.motivo, "alloggio_errato")

    def test_firma_manomessa(self):
        ver = crea_verificatore_pass(SEGRETO, orologio=lambda: DENTRO)
        token = crea_emettitore_pass(SEGRETO).emetti("p1", "casa", "2026-07-01",
                                                     "2026-07-03", fuso=FUSO)
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
                                                     "2026-07-03", fuso=FUSO)
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
                                                     "2026-07-03", fuso=FUSO)
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
                                                     "2026-07-03", fuso=FUSO)
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
        token = em.emetti("p1", "casa", "2026-07-01", "2026-07-03", fuso=FUSO)
        da = _epoch_da_data_ora("2026-07-01", 14, FUSO)     # stesso fuso del token
        ver_prima = crea_verificatore_pass(SEGRETO, orologio=lambda: da - 60)
        ver_dopo = crea_verificatore_pass(SEGRETO, orologio=lambda: da + 60)
        self.assertFalse(ver_prima.verifica(token, "casa").consentito)
        self.assertTrue(ver_dopo.verifica(token, "casa").consentito)


class TestWallet(unittest.TestCase):
    def test_payload(self):
        token = crea_emettitore_pass(SEGRETO).emetti("p1", "casa", "2026-07-01",
                                                     "2026-07-03", fuso=FUSO)
        p = costruisci_pass_wallet(token, alloggio_id="casa", titolo="Casa al mare",
                                   check_in="2026-07-01", check_out="2026-07-03")
        self.assertEqual(p["payload"], token)
        self.assertEqual(p["formato"], "qr")
        self.assertIn("istruzioni", p)


class TestGliOttoSopravvissutiDellaNotte(unittest.TestCase):
    """Una guardia per ognuno degli 8 punti che il Giudice ha trovato scoperti nella notte del
    2026-09-06 (giudice_notte_blocco3_2.log): ognuna e' stata vista ROSSA col mutante
    iniettato con l'editor e ripristino byte-identico."""

    def _pass_firmato(self, **campi):
        dati = {"prenotazione_id": "p1", "alloggio_id": "casa", "check_in": "2026-07-01",
                "check_out": "2026-07-03", "valido_da": DA, "valido_a": A}
        dati.update(campi)
        return FirmaQuote(SEGRETO).codifica(dati)

    def test_riga50_un_valore_che_NON_e_un_intero_vero_rende_il_pass_corrotto(self):
        ver = crea_verificatore_pass(SEGRETO, orologio=lambda: DENTRO)
        for storto in ("123", 1.5, True, None, [DA]):
            e = ver.verifica(self._pass_firmato(valido_da=storto), "casa")
            self.assertEqual((e.consentito, e.motivo), (False, "pass_corrotto"), repr(storto))
            e = ver.verifica(self._pass_firmato(valido_a=storto), "casa")
            self.assertEqual((e.consentito, e.motivo), (False, "pass_corrotto"), repr(storto))

    def test_riga82_l_esito_della_porta_non_si_riscrive(self):
        import dataclasses
        e = EsitoAccesso(False, "scaduto")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            e.consentito = True
        self.assertFalse(e.consentito)

    def test_riga108_un_pass_che_apre_e_chiude_nello_stesso_istante_non_si_emette(self):
        em = EmettitorePass(FirmaQuote(SEGRETO), ora_checkin=11, ora_checkout=11)
        self.assertIsNone(em.emetti("p1", "casa", "2026-07-01", "2026-07-01", fuso=FUSO),
                          "valido_da == valido_a: finestra vuota, niente pass")
        self.assertIsNotNone(em.emetti("p1", "casa", "2026-07-01", "2026-07-02", fuso=FUSO))

    def test_riga140_141_ogni_campo_del_pass_deve_avere_il_tipo_giusto_da_solo(self):
        ver = crea_verificatore_pass(SEGRETO, orologio=lambda: DENTRO)
        casi = (dict(prenotazione_id=123), dict(alloggio_id=["casa"]),
                dict(valido_da="%d" % DA), dict(valido_a=float(A)))
        for storto in casi:
            e = ver.verifica(self._pass_firmato(**storto), "casa")
            self.assertEqual((e.consentito, e.motivo), (False, "pass_corrotto"), repr(storto))
        buono = ver.verifica(self._pass_firmato(), "casa")
        self.assertTrue(buono.consentito, "il pass sano entra: la guardia distingue")

    def test_riga142_un_pass_corrotto_NON_e_consentito(self):
        ver = crea_verificatore_pass(SEGRETO, orologio=lambda: DENTRO)
        e = ver.verifica(self._pass_firmato(prenotazione_id=None), "casa")
        self.assertIs(e.consentito, False)
        self.assertEqual(e.motivo, "pass_corrotto")

    def test_riga156_la_revoca_che_esplode_lascia_la_TRACCIA_nel_registro(self):
        def boom(pid):
            raise RuntimeError("db revoche giu'")
        ver = crea_verificatore_pass(SEGRETO, orologio=lambda: DENTRO, revocato=boom)
        token = crea_emettitore_pass(SEGRETO).emetti("p1", "casa", "2026-07-01",
                                                     "2026-07-03", fuso=FUSO)
        with self.assertLogs("core_auto.smartpass", level="ERROR") as reg:
            e = ver.verifica(token, "casa")
        self.assertFalse(e.consentito)
        rec = [r for r in reg.records if "revoca" in r.getMessage()][0]
        self.assertIsInstance(rec.exc_info, tuple, "exc_info=True: la traccia c'e', non un False")
        self.assertIs(rec.exc_info[0], RuntimeError, "ed e' l'eccezione della revoca")

    def test_riga176_le_istruzioni_del_wallet_hanno_un_testo_di_serie_e_uno_proprio(self):
        p = costruisci_pass_wallet("tok", alloggio_id="casa", titolo="Casa", check_in="2026-07-01",
                                   check_out="2026-07-03")
        self.assertEqual(p["istruzioni"], "Avvicina questo codice alla serratura per entrare.")
        p2 = costruisci_pass_wallet("tok", alloggio_id="casa", titolo="Casa", check_in="2026-07-01",
                                    check_out="2026-07-03", istruzioni="Codice al citofono: 4")
        self.assertEqual(p2["istruzioni"], "Codice al citofono: 4")


if __name__ == "__main__":
    unittest.main()
