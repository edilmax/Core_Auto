# -*- coding: utf-8 -*-
"""IL DEDICATO DI fase192_admin_accounts — gli operatori admin coi ruoli.

Fino al 2026-09-06 questo modulo non aveva un test dedicato: il Giudice lo dichiarava NON
GIUDICABILE (33 punti mai esaminati). Tutto in memoria (`:memory:`), orologio iniettato,
POCHE chiamate a `crea`/`verifica` perche' ogni PBKDF2 a 200k iterazioni costa un decimo di
secondo: la lentezza e' voluta dal modulo, non dal test.

Cosa misura: la matrice ruolo x azione (ogni azione-soldi negata al supporto, tutte le altre
concesse; ruolo ignoto negato); la creazione che rifiuta email/password/ruolo sbagliati e
normalizza l'email; il login che risponde con lo STESSO errore a password sbagliata e a
email inesistente (niente enumerazione) e che controlla la password PRIMA dello stato; la
revoca che disattiva senza cancellare, all'istante anche per `ruolo_attivo`; la riattivazione;
il cambio ruolo; la lista che non mostra mai salt e hash; il salt per account.

VISTA ROSSA (2026-09-06, con l'editor, ripristino byte-identico sha256): fase192:40 `not in` ->
`in` (il supporto puo' fare SOLO le azioni-soldi) -> `test_la_matrice_ruolo_per_azione` ROSSO;
fase192:119 `if not int(r[3])` -> `if False` (un account revocato entra) ->
`test_la_revoca_disattiva_senza_cancellare_e_vale_all_istante` ROSSO.
"""
import sqlite3
import unittest

from fase192_admin_accounts import (AZIONI_SOLO_ADMIN, RUOLI, crea_admin_accounts, puo)


class _Orologio:
    def __init__(self):
        self.t = 1_700_000_000

    def __call__(self):
        return self.t


class TestLaMatriceDeiRuoli(unittest.TestCase):

    def test_la_matrice_ruolo_per_azione(self):
        self.assertEqual(RUOLI, ("admin", "supporto"))
        self.assertEqual(len(AZIONI_SOLO_ADMIN), 6)
        for azione in AZIONI_SOLO_ADMIN:
            self.assertTrue(puo("admin", azione), azione)
            self.assertFalse(puo("supporto", azione), "il supporto NON tocca i soldi: " + azione)
        for azione in ("search", "prenotazioni", "verifiche", "diagnosi", "audit", ""):
            self.assertTrue(puo("admin", azione), azione)
            self.assertTrue(puo("supporto", azione), azione)

    def test_un_ruolo_ignoto_o_vuoto_e_negato_su_tutto_e_il_ruolo_si_normalizza(self):
        for ruolo in (None, "", "root", "ADMINISTRATOR", 0, "supporter"):
            self.assertFalse(puo(ruolo, "search"), repr(ruolo))
            self.assertFalse(puo(ruolo, "rimborso"), repr(ruolo))
        self.assertTrue(puo("  Admin ", "rimborso"), "maiuscole e spazi non contano")
        self.assertTrue(puo("SUPPORTO", "search"))
        self.assertFalse(puo("SUPPORTO", "rimborso"))


class TestGliAccountOperatore(unittest.TestCase):

    def setUp(self):
        self.oro = _Orologio()
        self.acc = crea_admin_accounts(":memory:", orologio=self.oro)

    def test_la_creazione_rifiuta_email_password_e_ruolo_sbagliati(self):
        self.assertEqual(self.acc.crea("senza-chiocciola", "password1", "admin")["errore"], "email_non_valida")
        self.assertEqual(self.acc.crea("", "password1", "admin")["errore"], "email_non_valida")
        self.assertEqual(self.acc.crea(None, "password1", "admin")["errore"], "email_non_valida")
        self.assertEqual(self.acc.crea("a@b.it", "sette77", "admin")["errore"], "password_troppo_corta")
        self.assertEqual(self.acc.crea("a@b.it", None, "admin")["errore"], "password_troppo_corta")
        self.assertEqual(self.acc.crea("a@b.it", 12345678, "admin")["errore"], "password_troppo_corta")
        self.assertEqual(self.acc.crea("a@b.it", "password1", "root")["errore"], "ruolo_non_valido")
        self.assertEqual(self.acc.crea("a@b.it", "password1", "Admin")["errore"], "ruolo_non_valido")
        self.assertEqual(self.acc.lista(), [], "nessun rifiuto ha scritto niente")

    def test_la_creazione_normalizza_l_email_e_il_login_pure(self):
        esito = self.acc.crea("  Capo@BookinVIP.com ", "otto8888", "supporto", creato_da="root")
        self.assertEqual(esito, {"ok": True, "email": "capo@bookinvip.com", "ruolo": "supporto"})
        v = self.acc.verifica("CAPO@bookinvip.COM", "otto8888")
        self.assertEqual(v, {"ok": True, "email": "capo@bookinvip.com", "ruolo": "supporto"})
        self.assertEqual(self.acc.ruolo_attivo(" capo@BOOKINVIP.com"), "supporto")

    def test_il_login_dice_lo_stesso_errore_a_password_sbagliata_e_a_email_inesistente(self):
        self.acc.crea("op@x.it", "password1", "admin")
        sbagliata = self.acc.verifica("op@x.it", "password2")
        inesistente = self.acc.verifica("nessuno@x.it", "password1")
        self.assertEqual(sbagliata, {"ok": False, "errore": "credenziali_non_valide"})
        self.assertEqual(inesistente, sbagliata, "niente enumerazione delle email")
        self.assertEqual(self.acc.verifica("op@x.it", "password1")["ok"], True)

    def test_la_revoca_disattiva_senza_cancellare_e_vale_all_istante(self):
        self.acc.crea("op@x.it", "password1", "admin")
        self.assertTrue(self.acc.revoca("op@x.it"))
        self.assertEqual(self.acc.verifica("op@x.it", "password1"),
                         {"ok": False, "errore": "account_revocato"})
        self.assertIsNone(self.acc.ruolo_attivo("op@x.it"), "un token vivo di un revocato muore qui")
        self.assertEqual(self.acc.lista()[0]["attivo"], False, "resta nell'audit, disattivato")
        self.assertTrue(self.acc.revoca("op@x.it"), "idempotente")
        self.assertFalse(self.acc.revoca("mai@x.it"), "un'email ignota non revoca niente")

    def test_su_un_revocato_la_password_si_controlla_PRIMA_dello_stato(self):
        self.acc.crea("op@x.it", "password1", "admin")
        self.acc.revoca("op@x.it")
        self.assertEqual(self.acc.verifica("op@x.it", "password2")["errore"], "credenziali_non_valide",
                         "chi non ha la password non viene a sapere che l'account esiste ed e' revocato")

    def test_la_riattivazione_riapre_e_il_cambio_ruolo_si_legge_subito(self):
        self.acc.crea("op@x.it", "password1", "admin")
        self.acc.revoca("op@x.it")
        self.assertTrue(self.acc.riattiva("op@x.it"))
        self.assertEqual(self.acc.verifica("op@x.it", "password1")["ruolo"], "admin")
        self.assertTrue(self.acc.imposta_ruolo("op@x.it", "supporto"))
        self.assertEqual(self.acc.ruolo_attivo("op@x.it"), "supporto")
        self.assertFalse(self.acc.imposta_ruolo("op@x.it", "root"), "ruolo non valido")
        self.assertEqual(self.acc.ruolo_attivo("op@x.it"), "supporto", "il ruolo non e' cambiato")
        self.assertFalse(self.acc.imposta_ruolo("mai@x.it", "admin"))
        self.assertFalse(self.acc.riattiva("mai@x.it"))
        self.assertIsNone(self.acc.ruolo_attivo("mai@x.it"))

    def test_ricreare_lo_stesso_account_cambia_la_password_e_lo_riattiva(self):
        self.acc.crea("op@x.it", "password1", "supporto")
        self.acc.revoca("op@x.it")
        self.oro.t += 10
        self.assertTrue(self.acc.crea("op@x.it", "password2", "admin")["ok"])
        self.assertEqual(self.acc.verifica("op@x.it", "password1")["errore"], "credenziali_non_valide")
        v = self.acc.verifica("op@x.it", "password2")
        self.assertEqual((v["ok"], v["ruolo"]), (True, "admin"))
        self.assertEqual(len(self.acc.lista()), 1)

    def test_la_lista_e_ordinata_dal_piu_recente_e_non_mostra_mai_salt_o_hash(self):
        self.acc.crea("primo@x.it", "password1", "admin", creato_da="root")
        self.oro.t += 100
        self.acc.crea("secondo@x.it", "password1", "supporto", creato_da="x" * 200)
        lista = self.acc.lista()
        self.assertEqual([r["email"] for r in lista], ["secondo@x.it", "primo@x.it"])
        self.assertEqual(lista[0]["creato_ts"], 1_700_000_100)
        self.assertEqual(lista[0]["creato_da"], "x" * 60, "chi crea e' tagliato a 60")
        self.assertEqual(lista[1], {"email": "primo@x.it", "ruolo": "admin", "attivo": True,
                                    "creato_ts": 1_700_000_000, "creato_da": "root"})
        for r in lista:
            self.assertEqual(sorted(r), ["attivo", "creato_da", "creato_ts", "email", "ruolo"])

    def test_due_account_con_la_stessa_password_hanno_salt_e_hash_diversi(self):
        con = sqlite3.connect(":memory:", check_same_thread=False)
        from fase192_admin_accounts import AdminAccounts, _ConnCondivisa
        acc = AdminAccounts(lambda: _ConnCondivisa(con), orologio=self.oro)
        acc.crea("a@x.it", "stessa-password", "admin")
        acc.crea("b@x.it", "stessa-password", "admin")
        righe = con.execute("SELECT email, salt, pw_hash FROM admin_account ORDER BY email").fetchall()
        self.assertEqual(len(righe), 2)
        self.assertNotEqual(righe[0][1], righe[1][1], "salt per account")
        self.assertNotEqual(righe[0][2], righe[1][2], "stessa password, hash diversi")
        self.assertNotIn("stessa-password", righe[0][2] + righe[0][1], "mai in chiaro")
        self.assertEqual(len(bytes.fromhex(righe[0][1])), 16)


if __name__ == "__main__":
    unittest.main()
