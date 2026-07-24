"""GUARDIA — Account operatore ADMIN con RUOLI (fase192) + gestione dal super-admin.

Prova il ciclo completo: il super-admin (bunker) crea un operatore 'supporto'; l'operatore fa
login con email+password e riceve un token col RUOLO; il token autentica gli endpoint admin di
LETTURA; ma il ruolo 'supporto' NON puo' muovere soldi (rimborso -> 403). Revoca e cambio-ruolo
sono ISTANTANEI (il token ri-controlla il DB). Vista ROSSA: neutralizzando il controllo di ruolo,
'supporto' riuscirebbe a rimborsare.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

IP = {"X-Forwarded-For": "203.0.113.5"}


class TestAdminAccounts(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"h" * 32, db_payout=self.d + "/p.db",
            db_finanza=self.d + "/fin.db", bunker_password="SuperPw@1"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak", base_url="https://x")
        self.BH = self._bunker()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _bunker(self):
        s, o = self.g("POST", "/api/bunker/login", {"codice": "SuperPw@1"}, {"X-Admin-Key": "ak", **IP})
        self.assertEqual(s, 200, o)
        return {"X-Admin-Key": "ak", "X-Bunker-Session": o["sessione"], **IP}

    def _crea(self, email, pw, ruolo):
        return self.g("POST", "/api/bunker/admin_accounts",
                      {"azione": "crea", "email": email, "password": pw, "ruolo": ruolo}, self.BH)

    def _login_op(self, email, pw):
        return self.g("POST", "/api/admin/login", {"email": email, "password": pw})

    # ── gestione (crea/lista/revoca/ruolo) e' SOLO super-admin ─────────────
    def test_gestione_solo_super_admin(self):
        s, o = self.g("POST", "/api/bunker/admin_accounts",
                      {"azione": "crea", "email": "x@x.it", "password": "password123",
                       "ruolo": "supporto"}, {"X-Admin-Key": "ak", **IP})   # senza sessione bunker
        self.assertEqual(s, 403, o)
        s, o = self.g("GET", "/api/bunker/admin_accounts", None, {"X-Admin-Key": "ak", **IP})
        self.assertEqual(s, 403, o)

    def test_crea_login_e_lista(self):
        self.assertEqual(self._crea("Sup@x.it", "password123", "supporto")[0], 200)
        s, lg = self._login_op("sup@x.it", "password123")
        self.assertEqual(s, 200, lg)
        self.assertEqual(lg["ruolo"], "supporto")
        self.assertTrue(lg.get("op_token"))
        # lista: mai salt/hash
        s, l = self.g("GET", "/api/bunker/admin_accounts", None, self.BH)
        self.assertEqual(s, 200)
        self.assertIn("supporto", json.dumps(l["account"]))
        self.assertNotIn("salt", json.dumps(l))
        self.assertNotIn("pw_hash", json.dumps(l))

    def test_login_credenziali_sbagliate(self):
        self._crea("sup@x.it", "password123", "supporto")
        self.assertEqual(self._login_op("sup@x.it", "sbagliata")[0], 401)
        self.assertEqual(self._login_op("nessuno@x.it", "password123")[0], 401)

    def test_token_operatore_autentica_letture(self):
        self._crea("sup@x.it", "password123", "supporto")
        tok = self._login_op("sup@x.it", "password123")[1]["op_token"]
        s, _ = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Op": tok, **IP})
        self.assertEqual(s, 200, "il token operatore deve autenticare gli endpoint admin di lettura")

    def test_supporto_non_muove_soldi(self):
        self._crea("sup@x.it", "password123", "supporto")
        tok = self._login_op("sup@x.it", "password123")[1]["op_token"]
        h = {"X-Admin-Op": tok, "X-Bunker-Session": self.BH["X-Bunker-Session"], **IP}
        s, o = self.g("POST", "/api/admin/rimborso",
                      {"alloggio_id": "c", "check_in": "2027-12-10", "check_out": "2027-12-12",
                       "idem_key": "k"}, h)
        self.assertEqual(s, 403, o)
        self.assertEqual(o.get("errore"), "permesso_negato_ruolo")

    def test_admin_puo_muovere_soldi(self):
        self._crea("boss@x.it", "password123", "admin")
        tok = self._login_op("boss@x.it", "password123")[1]["op_token"]
        h = {"X-Admin-Op": tok, "X-Bunker-Session": self.BH["X-Bunker-Session"], **IP}
        s, o = self.g("POST", "/api/admin/rimborso",
                      {"alloggio_id": "c", "check_in": "2027-12-10", "check_out": "2027-12-12",
                       "idem_key": "k"}, h)
        self.assertNotEqual(s, 403, "il ruolo 'admin' deve poter fare il rimborso (non 403 di ruolo)")

    def test_revoca_e_cambio_ruolo_istantanei(self):
        self._crea("sup@x.it", "password123", "supporto")
        tok = self._login_op("sup@x.it", "password123")[1]["op_token"]
        H = {"X-Admin-Op": tok, **IP}
        self.assertEqual(self.g("GET", "/api/admin/prenotazioni", None, H)[0], 200)
        # promuovo a 'admin' -> il token esistente ora e' admin (ruolo ri-letto dal DB)
        self.g("POST", "/api/bunker/admin_accounts", {"azione": "ruolo", "email": "sup@x.it",
               "ruolo": "admin"}, self.BH)
        hh = {"X-Admin-Op": tok, "X-Bunker-Session": self.BH["X-Bunker-Session"], **IP}
        s, _ = self.g("POST", "/api/admin/rimborso", {"alloggio_id": "c", "check_in": "2027-12-10",
               "check_out": "2027-12-12", "idem_key": "k2"}, hh)
        self.assertNotEqual(s, 403, "dopo promozione ad admin, il rimborso non e' piu' 403 di ruolo")
        # revoca -> il token non autentica piu' (istantaneo)
        self.g("POST", "/api/bunker/admin_accounts", {"azione": "revoca", "email": "sup@x.it"}, self.BH)
        self.assertEqual(self.g("GET", "/api/admin/prenotazioni", None, H)[0], 401,
                         "dopo la revoca il token operatore non deve piu' autenticare")


if __name__ == "__main__":
    unittest.main(verbosity=2)
