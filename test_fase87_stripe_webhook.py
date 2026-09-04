"""
Test Fase 87 - Webhook Stripe.

Copre: firma valida -> verificata, payload manomesso -> rifiutato, secret errato ->
rifiutato, timestamp scaduto (anti-replay) -> rifiutato, header malformato -> rifiutato,
gestisci_webhook (parse evento), robustezza (mai solleva).
E le sette guardie di `TestIBuchiDelGiudice`, nate dai mutanti sopravvissuti (2026-09-04).
"""
import json
import time
import unittest

from fase87_stripe_webhook import (
    firma_di_test, gestisci_webhook, verifica_firma_stripe,
)

SECRET = "whsec_testsegreto"
PAYLOAD = json.dumps({"type": "checkout.session.completed",
                      "data": {"object": {"metadata": {"riferimento": "ABC123"}}}})


class TestFirma(unittest.TestCase):
    def test_valida(self):
        h = firma_di_test(PAYLOAD, SECRET, 1000)
        self.assertTrue(verifica_firma_stripe(PAYLOAD, h, SECRET, ora=1000))

    def test_payload_manomesso(self):
        h = firma_di_test(PAYLOAD, SECRET, 1000)
        self.assertFalse(verifica_firma_stripe(PAYLOAD + "x", h, SECRET, ora=1000))

    def test_secret_errato(self):
        h = firma_di_test(PAYLOAD, SECRET, 1000)
        self.assertFalse(verifica_firma_stripe(PAYLOAD, h, "whsec_altro", ora=1000))

    def test_replay_timestamp_vecchio(self):
        h = firma_di_test(PAYLOAD, SECRET, 1000)
        # ora molto dopo -> oltre la tolleranza -> rifiutato
        self.assertFalse(verifica_firma_stripe(PAYLOAD, h, SECRET, ora=1000 + 10000))

    def test_header_malformato(self):
        for bad in ("", "spazzatura", "t=abc,v1=x", "v1=soloquesto", None, 123):
            self.assertFalse(verifica_firma_stripe(PAYLOAD, bad, SECRET, ora=1000))

    def test_secret_vuoto(self):
        h = firma_di_test(PAYLOAD, SECRET, 1000)
        self.assertFalse(verifica_firma_stripe(PAYLOAD, h, "", ora=1000))


class TestGestisci(unittest.TestCase):
    def test_evento_valido(self):
        h = firma_di_test(PAYLOAD, SECRET, 1000)
        ok, tipo, dati = gestisci_webhook(PAYLOAD, h, SECRET, ora=1000)
        self.assertTrue(ok)
        self.assertEqual(tipo, "checkout.session.completed")
        self.assertEqual(dati["object"]["metadata"]["riferimento"], "ABC123")

    def test_firma_invalida_niente_evento(self):
        ok, tipo, dati = gestisci_webhook(PAYLOAD, "t=1000,v1=falso", SECRET, ora=1000)
        self.assertFalse(ok)
        self.assertEqual(tipo, "")
        self.assertIsNone(dati)

    def test_payload_non_json(self):
        h = firma_di_test("non-json", SECRET, 1000)
        ok, _, _ = gestisci_webhook("non-json", h, SECRET, ora=1000)
        self.assertFalse(ok)

    def test_mai_solleva(self):
        for bad in (None, 123, [], {}):
            try:
                verifica_firma_stripe(bad, bad, bad)
                gestisci_webhook(bad, bad, bad)
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")


class TestIBuchiDelGiudice(unittest.TestCase):
    """Sette guardie, una per ciascuno dei 7 mutanti SOPRAVVISSUTI al giro del Giudice del
    2026-09-04 col solo test dedicato (15 punti: 8 uccisi, 7 vivi). Ognuna porta nel nome la
    riga del mutante, e' stata vista ROSSA contro il mutante prima che verde (D20), e difende
    un contratto vero del webhook. Nessun mutante e' stato dichiarato equivalente (B6)."""

    def test_riga42_un_payload_che_NON_e_str_viene_rifiutato_senza_sollevare_anche_con_header_valido(self):
        # Il body arriva dal web server: se e' bytes (o altro) la risposta e' False, non un TypeError
        # a meta' HMAC. Col mutante (and -> or) la guardia passa e `t + "." + payload` esplode.
        h = firma_di_test(PAYLOAD, SECRET, 1000)
        for non_str in (PAYLOAD.encode("utf-8"), 123, None, [PAYLOAD], {"body": PAYLOAD}):
            with self.subTest(payload=type(non_str).__name__):
                self.assertIs(verifica_firma_stripe(non_str, h, SECRET, ora=1000), False)
                self.assertEqual(gestisci_webhook(non_str, h, SECRET, ora=1000), (False, "", None))

    def test_riga43_un_segreto_vuoto_non_verifica_niente_nemmeno_una_firma_fatta_col_segreto_vuoto(self):
        # Col mutante (and -> or) `secret=""` supera la guardia e l'HMAC con chiave vuota combacia con
        # una firma calcolata con chiave vuota: chiunque conosca il trucco conferma pagamenti finti.
        h_vuota = firma_di_test(PAYLOAD, "", 1000)
        self.assertIs(verifica_firma_stripe(PAYLOAD, h_vuota, "", ora=1000), False)
        self.assertEqual(gestisci_webhook(PAYLOAD, h_vuota, "", ora=1000), (False, "", None))

    def test_riga52_se_LEGGERE_l_header_fallisce_la_risposta_e_False_mai_True(self):
        # Il ramo `except` del parser e' chiuso per difetto. Un `str` vero non fa fallire split/strip:
        # serve una sottoclasse di str (passa isinstance) il cui split esplode. Col mutante
        # (False -> True) un header ILLEGGIBILE conferma un pagamento.
        class HeaderCheEsplode(str):
            def split(self, *a, **k):
                raise RuntimeError("header illeggibile")

        h = HeaderCheEsplode(firma_di_test(PAYLOAD, SECRET, 1000))
        self.assertIs(verifica_firma_stripe(PAYLOAD, h, SECRET, ora=1000), False)
        self.assertEqual(gestisci_webhook(PAYLOAD, h, SECRET, ora=1000), (False, "", None))

    def test_riga54_un_header_con_il_solo_timestamp_o_la_sola_firma_non_e_una_firma(self):
        # Servono ENTRAMBI t e v1. Col mutante (and -> or) ne basta uno: con `t=1000` senza v1 si
        # arriva a compare_digest(None, ...) e la funzione esplode invece di rispondere False.
        for h in ("t=1000", "t=1000,", "v1=" + "0" * 64, "t=1000,v2=abc"):
            with self.subTest(header=h):
                self.assertIs(verifica_firma_stripe(PAYLOAD, h, SECRET, ora=1000), False)

    def test_riga60_senza_orologio_iniettato_si_usa_quello_vero_e_un_bool_non_e_un_orologio(self):
        # In produzione nessuno passa `ora`: None deve voler dire «adesso». Col mutante (and -> or)
        # None supera il controllo, `adesso` diventa None e `abs(None - ts)` esplode: OGNI webhook
        # vero verrebbe respinto con un'eccezione. E `True` non e' un orologio: vale come «adesso».
        ts = int(time.time())
        h = firma_di_test(PAYLOAD, SECRET, ts)
        self.assertIs(verifica_firma_stripe(PAYLOAD, h, SECRET), True)
        self.assertIs(verifica_firma_stripe(PAYLOAD, h, SECRET, ora=None), True)
        self.assertIs(verifica_firma_stripe(PAYLOAD, h, SECRET, ora=True), True)
        self.assertIs(gestisci_webhook(PAYLOAD, h, SECRET)[0], True)

    def test_riga61_uno_scarto_ESATTAMENTE_pari_alla_tolleranza_passa_un_secondo_oltre_no(self):
        # La tolleranza e' inclusiva. Col mutante (> -> >=) un webhook arrivato esattamente al limite
        # viene respinto: un pagamento vero perso per un secondo.
        h = firma_di_test(PAYLOAD, SECRET, 1000)
        self.assertIs(verifica_firma_stripe(PAYLOAD, h, SECRET, ora=1000 + 300), True)
        self.assertIs(verifica_firma_stripe(PAYLOAD, h, SECRET, ora=1000 - 300), True)
        self.assertIs(verifica_firma_stripe(PAYLOAD, h, SECRET, ora=1000 + 301), False)
        self.assertIs(verifica_firma_stripe(PAYLOAD, h, SECRET, ora=1000 - 301), False)
        self.assertIs(verifica_firma_stripe(PAYLOAD, h, SECRET, ora=1005, tolleranza_sec=5), True)
        self.assertIs(verifica_firma_stripe(PAYLOAD, h, SECRET, ora=1006, tolleranza_sec=5), False)

    def test_riga81_un_evento_firmato_ma_che_NON_e_un_oggetto_JSON_non_e_creduto(self):
        # Una lista o un numero firmati bene sono JSON valido ma non sono un evento Stripe. Col
        # mutante (False -> True) `gestisci_webhook` risponde «firma ok» su un payload senza tipo.
        for corpo in (json.dumps([1, 2, 3]), json.dumps(42), json.dumps("stringa"), json.dumps(None)):
            with self.subTest(corpo=corpo):
                h = firma_di_test(corpo, SECRET, 1000)
                self.assertEqual(gestisci_webhook(corpo, h, SECRET, ora=1000), (False, "", None))


if __name__ == "__main__":
    unittest.main()
