# -*- coding: utf-8 -*-
"""IL DEDICATO DI fase180_bunker — il secondo fattore e la sessione blindata del super-admin.

Fino al 2026-09-06 questo modulo non aveva un test dedicato: il Giudice lo dichiarava NON
GIUDICABILE (46 punti mai esaminati). Tutto in memoria: una FirmaQuote con un segreto di
prova e un orologio iniettato. NESSUNA chiamata al bunker vero, nessuna rete, nessun segreto
letto dall'ambiente.

Il TOTP si prova contro il VETTORE DELLO STANDARD (RFC 6238, Appendice B: segreto ASCII
«12345678901234567890», SHA-1, T=59 s -> «94287082» a 8 cifre, cioe' «287082» a 6): un
giudice esterno, non il nostro stesso codice.

VISTA ROSSA (2026-09-06, con l'editor, ripristino byte-identico sha256): fase180:140 `<=` -> `<`
(la sessione vale ANCORA nel secondo esatto della scadenza) ->
`test_la_sessione_scade_nel_secondo_esatto_e_non_un_secondo_dopo` ROSSO; fase180:142 il
confronto dell'IP tolto (`False`) -> `test_un_token_rubato_da_un_altro_ip_e_negato` ROSSO.
"""
import base64
import unittest

from fase59_concierge import FirmaQuote
from fase180_bunker import (DURATA_SESSIONE_SEC, Bunker, _codice_at, crea_bunker,
                            genera_segreto, otpauth_uri, verifica_totp)

SEGRETO_RFC = base64.b32encode(b"12345678901234567890").decode("ascii")   # RFC 6238 App. B


class _Orologio:
    def __init__(self, t=1_700_000_000.0):
        self.t = float(t)

    def __call__(self):
        return self.t

    def avanza(self, sec):
        self.t += sec


# Le password di prova stanno in costanti, come in test_marca_temporale_server (`bunker_password=PW`):
# passate come stringhe letterali contano per bandit come segreti cablati (B106).
PW = "Pass@word1"
PW_ACCENTI = "càffè-Ünïcode"
PW_VUOTA = ""
PW_X = "x"


def _bunker(**kw):
    oro = _Orologio()
    base = dict(totp_secret=SEGRETO_RFC, password=PW, break_glass="ROMPI-VETRO")
    base.update(kw)
    return crea_bunker(FirmaQuote(b"S" * 32), orologio=oro, **base), oro


class TestIlTOTP(unittest.TestCase):

    def test_il_codice_coincide_col_vettore_dello_standard_RFC_6238(self):
        # T=59 s -> contatore 1 -> 94287082 (8 cifre) -> ultime 6: 287082
        self.assertEqual(_codice_at(SEGRETO_RFC, 1), "287082")
        self.assertTrue(verifica_totp(SEGRETO_RFC, "287082", ora=59, finestra=0))
        # T=1111111109 s -> contatore 37037036 -> 07081804 -> 081804
        self.assertEqual(_codice_at(SEGRETO_RFC, 37037036), "081804")
        self.assertTrue(verifica_totp(SEGRETO_RFC, "081804", ora=1111111109, finestra=0))

    def test_la_finestra_accetta_un_passo_prima_e_dopo_e_rifiuta_due(self):
        ora = 1_700_000_000
        t = ora // 30
        for d, atteso in ((-1, True), (0, True), (1, True), (-2, False), (2, False)):
            self.assertEqual(verifica_totp(SEGRETO_RFC, _codice_at(SEGRETO_RFC, t + d), ora=ora),
                             atteso, "drift di %d passi" % d)
        self.assertTrue(verifica_totp(SEGRETO_RFC, _codice_at(SEGRETO_RFC, t + 2), ora=ora, finestra=2))

    def test_i_codici_malformati_e_i_segreti_vuoti_o_rotti_sono_rifiutati(self):
        ora = 1_700_000_000
        buono = _codice_at(SEGRETO_RFC, ora // 30)
        for codice in (None, 123456, "", "12345", "1234567", "12a456", " ", buono + "0"):
            self.assertFalse(verifica_totp(SEGRETO_RFC, codice, ora=ora), repr(codice))
        self.assertTrue(verifica_totp(SEGRETO_RFC, " %s " % buono, ora=ora), "gli spazi attorno si tolgono")
        self.assertFalse(verifica_totp("", buono, ora=ora))
        self.assertFalse(verifica_totp(None, buono, ora=ora))
        self.assertFalse(verifica_totp("!!!non-base32!!!", buono, ora=ora), "segreto rotto -> False, mai un'eccezione")

    def test_il_segreto_generato_e_base32_e_l_uri_lo_porta_intero(self):
        seg = genera_segreto()
        self.assertEqual(len(seg), 32)
        self.assertTrue(base64.b32decode(seg + "=" * (-len(seg) % 8)))
        uri = otpauth_uri(seg, account="capo", issuer="BookinVIP")
        self.assertTrue(uri.startswith("otpauth://totp/BookinVIP%3Acapo?secret=" + seg))
        self.assertIn("&digits=6&period=30", uri)
        self.assertIn("algorithm=SHA1", uri)


class TestIlSecondoFattore(unittest.TestCase):

    def test_riconosce_totp_password_e_break_glass_e_rifiuta_il_resto(self):
        b, oro = _bunker()
        self.assertEqual(b.verifica_secondo_fattore(_codice_at(SEGRETO_RFC, int(oro()) // 30)), "totp")
        self.assertEqual(b.verifica_secondo_fattore("Pass@word1"), "password")
        self.assertEqual(b.verifica_secondo_fattore("  Pass@word1 "), "password", "gli spazi attorno si tolgono")
        self.assertEqual(b.verifica_secondo_fattore("ROMPI-VETRO"), "break_glass")
        for sbagliato in ("Pass@word2", "000000", "", "   ", None, 12, b"Pass@word1"):
            self.assertEqual(b.verifica_secondo_fattore(sbagliato), "", repr(sbagliato))

    def test_una_password_con_accenti_funziona_e_una_sbagliata_con_accenti_non_esplode(self):
        b, _ = _bunker(password=PW_ACCENTI)
        self.assertEqual(b.verifica_secondo_fattore("càffè-Ünïcode"), "password")
        self.assertEqual(b.verifica_secondo_fattore("càffè-Ünïcodé"), "", "diverso, senza TypeError")

    def test_un_codice_vuoto_non_apre_mai_nemmeno_con_password_vuota(self):
        b, _ = _bunker(totp_secret=PW_VUOTA, password=PW_VUOTA, break_glass="")
        self.assertFalse(b.configurato)
        self.assertEqual(b.verifica_secondo_fattore(""), "")
        b2, _ = _bunker(totp_secret=PW_VUOTA, password=PW_VUOTA, break_glass="X")
        self.assertTrue(b2.configurato)
        self.assertEqual(b2.verifica_secondo_fattore(""), "")
        self.assertEqual(b2.verifica_secondo_fattore("X"), "break_glass")

    def test_configurato_vuole_la_firma_E_almeno_un_fattore(self):
        self.assertFalse(Bunker(None, password=PW_X).configurato)
        self.assertFalse(Bunker(FirmaQuote(b"S" * 32)).configurato)
        self.assertTrue(Bunker(FirmaQuote(b"S" * 32), totp_secret=SEGRETO_RFC).configurato)


class TestLaSessioneBlindata(unittest.TestCase):

    def test_una_sessione_appena_creata_vale_dal_suo_ip_e_porta_iat_ed_exp(self):
        b, oro = _bunker()
        tok = b.crea_sessione("203.0.113.5")
        self.assertIsInstance(tok, str)
        esito = b.valida_sessione(tok, "203.0.113.5")
        self.assertTrue(esito["ok"], esito)
        self.assertEqual(esito["iat"], int(oro()))
        self.assertEqual(esito["exp"], int(oro()) + DURATA_SESSIONE_SEC)
        self.assertEqual(DURATA_SESSIONE_SEC, 15 * 60, "policy del fondatore: quindici minuti")

    def test_la_sessione_scade_nel_secondo_esatto_e_non_un_secondo_dopo(self):
        b, oro = _bunker()
        tok = b.crea_sessione("1.2.3.4")
        oro.avanza(DURATA_SESSIONE_SEC - 1)
        self.assertTrue(b.valida_sessione(tok, "1.2.3.4")["ok"], "un secondo prima vale ancora")
        oro.avanza(1)
        self.assertEqual(b.valida_sessione(tok, "1.2.3.4"), {"ok": False, "motivo": "sessione_scaduta"},
                         "nel secondo esatto della scadenza NON vale piu' (exp <= ora)")

    def test_un_token_rubato_da_un_altro_ip_e_negato(self):
        b, _ = _bunker()
        tok = b.crea_sessione("1.2.3.4")
        self.assertEqual(b.valida_sessione(tok, "5.6.7.8"), {"ok": False, "motivo": "ip_non_coincidente"})
        self.assertEqual(b.valida_sessione(tok, ""), {"ok": False, "motivo": "ip_non_coincidente"})
        self.assertTrue(b.valida_sessione(tok, "1.2.3.4")["ok"])

    def test_un_token_manomesso_o_di_un_altro_tipo_e_negato(self):
        b, oro = _bunker()
        tok = b.crea_sessione("1.2.3.4")
        rotto = tok[:-3] + ("AAA" if not tok.endswith("AAA") else "BBB")
        self.assertEqual(b.valida_sessione(rotto, "1.2.3.4")["motivo"], "sessione_assente_o_manomessa")
        for vuoto in (None, "", "x", 42):
            self.assertEqual(b.valida_sessione(vuoto, "1.2.3.4")["motivo"], "sessione_assente_o_manomessa")
        # un token FIRMATO BENE ma di un altro tipo (un voucher) non e' una sessione del bunker
        firma = FirmaQuote(b"S" * 32)
        altro = firma.codifica({"k": "voucher", "exp": int(oro()) + 999, "ip": "1.2.3.4", "nonce": "n"})
        self.assertEqual(b.valida_sessione(altro, "1.2.3.4")["motivo"], "sessione_assente_o_manomessa")

    def test_la_scadenza_si_controlla_PRIMA_dell_ip(self):
        b, oro = _bunker()
        tok = b.crea_sessione("1.2.3.4")
        oro.avanza(DURATA_SESSIONE_SEC)
        self.assertEqual(b.valida_sessione(tok, "9.9.9.9")["motivo"], "sessione_scaduta")

    def test_il_logout_revoca_subito_e_solo_quella_sessione(self):
        b, oro = _bunker()
        t1 = b.crea_sessione("1.2.3.4")
        oro.avanza(1)                            # nonce diverso: dipende da ip|ora
        t2 = b.crea_sessione("1.2.3.4")
        self.assertNotEqual(t1, t2)
        self.assertTrue(b.revoca(t1))
        self.assertEqual(b.valida_sessione(t1, "1.2.3.4"), {"ok": False, "motivo": "sessione_revocata"})
        self.assertTrue(b.valida_sessione(t2, "1.2.3.4")["ok"], "l'altra sessione vive")
        self.assertFalse(b.revoca("spazzatura"))
        self.assertFalse(b.revoca(None))
        self.assertFalse(b.revoca(FirmaQuote(b"S" * 32).codifica({"k": "bunker", "exp": 1})),
                         "senza nonce non c'e' niente da revocare")

    def test_la_denylist_si_pulisce_dei_revocati_scaduti(self):
        b, oro = _bunker()
        t1 = b.crea_sessione("1.2.3.4")
        b.revoca(t1)
        self.assertEqual(len(b._revocati), 1)
        oro.avanza(DURATA_SESSIONE_SEC)          # t1 e' scaduto: alla prossima revoca si butta
        t2 = b.crea_sessione("1.2.3.4")
        b.revoca(t2)
        self.assertEqual(len(b._revocati), 1, "resta solo il nonce di t2")
        self.assertNotIn(b._firma.decodifica(t1)["nonce"], b._revocati)

    def test_senza_firma_non_si_creano_ne_valgono_sessioni(self):
        b = Bunker(None, password=PW_X, orologio=lambda: 1.0)
        self.assertIsNone(b.crea_sessione("1.2.3.4"))
        self.assertEqual(b.valida_sessione("qualunque", "1.2.3.4"), {"ok": False, "motivo": "bunker_non_configurato"})
        self.assertFalse(b.revoca("qualunque"))

    def test_una_firma_che_esplode_non_fa_esplodere_il_bunker(self):
        class _FirmaRotta:
            def codifica(self, d):
                raise RuntimeError("segreto perso")

            def decodifica(self, t):
                return None
        b = Bunker(_FirmaRotta(), password=PW_X, orologio=lambda: 1.0)
        self.assertIsNone(b.crea_sessione("1.2.3.4"))


if __name__ == "__main__":
    unittest.main()
