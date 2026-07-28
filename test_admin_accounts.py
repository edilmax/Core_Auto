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

    # ── IL TOKEN OPERATORE E' UNA CREDENZIALE: firma e scadenza sono l'unica cosa che lo tiene ──
    # LACUNA TROVATA dalla mutazione (A4, 2026-07-27): neutralizzando in `_verifica_op` il
    # `compare_digest` sulla firma — oppure il controllo di scadenza — l'INTERA suite restava
    # verde. Significa: chiunque conoscesse l'email di un operatore poteva FABBRICARE un token
    # (`op|email|ruolo|exp|nonce|firma-a-caso`) ed entrare come lui, e un token rubato non
    # scadeva mai. Queste due guardie sono state VISTE ROSSE su entrambi i mutanti.
    def _token_forgiato(self, email, ruolo="admin", exp=9999999999, sig="0" * 32):
        return "op|%s|%s|%d|nonce1|%s" % (email, ruolo, exp, sig)

    def test_token_operatore_con_firma_falsa_non_autentica(self):
        self._crea("sup@x.it", "password123", "supporto")
        vero = self._login_op("sup@x.it", "password123")[1]["op_token"]
        # (a) token interamente FABBRICATO con l'email di un operatore che esiste davvero
        for tok in (self._token_forgiato("sup@x.it", "supporto"),
                    self._token_forgiato("sup@x.it", "admin"),      # + tentata escalation di ruolo
                    vero[:-1] + ("a" if vero[-1] != "a" else "b")):  # (b) firma vera alterata di 1 char
            s, _ = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Op": tok, **IP})
            self.assertEqual(s, 401, "token con firma non valida deve essere RIFIUTATO: %r" % tok)
        # e non deve nemmeno poter muovere soldi
        h = {"X-Admin-Op": self._token_forgiato("sup@x.it", "admin"),
             "X-Bunker-Session": self.BH["X-Bunker-Session"], **IP}
        s, _ = self.g("POST", "/api/admin/rimborso",
                      {"alloggio_id": "c", "check_in": "2027-12-10", "check_out": "2027-12-12",
                       "idem_key": "kf"}, h)
        self.assertEqual(s, 401, "un token forgiato non deve MAI arrivare al rimborso")
        # il verificatore stesso, a livello di router: firma falsa -> None
        self.assertIsNone(self.r._verifica_op(self._token_forgiato("sup@x.it", "admin")))

    def test_token_operatore_scaduto_non_autentica(self):
        self._crea("sup@x.it", "password123", "supporto")
        # firma AUTENTICA (emessa dal router) ma gia' scaduta: deve valere zero
        scaduto = self.r._firma_op("sup@x.it", "supporto", ttl_sec=-10)
        self.assertIsNone(self.r._verifica_op(scaduto), "token scaduto: il verificatore deve dare None")
        s, _ = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Op": scaduto, **IP})
        self.assertEqual(s, 401, "un token operatore SCADUTO non deve piu' autenticare")
        # controprova (il test non e' vacuo): lo STESSO token, emesso valido, autentica
        valido = self.r._firma_op("sup@x.it", "supporto", ttl_sec=600)
        self.assertEqual(self.g("GET", "/api/admin/prenotazioni", None,
                                {"X-Admin-Op": valido, **IP})[0], 200)

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


class TestCoerenzaAutenticazioneAutorizzazione(unittest.TestCase):
    """I DUE strati (chi sei / cosa puoi) devono dire la STESSA cosa sullo stesso chiamante.

    Regressione vera: senza ADMIN_KEY configurata, _auth_admin apre a chiunque come root
    ('aperto (dev)'), ma _ruolo_operatore tornava None e _puo_azione negava le azioni
    riservate -> 403 permesso_negato_ruolo sull'arbitrato di una controversia (soldi veri
    fermi) mentre TUTTO il resto del pannello admin restava spalancato.
    """

    def setUp(self):
        self.d = tempfile.mkdtemp()
        # NIENTE bunker_password: cosi' la rotta arriva fino alla logica e il 403 eventuale
        # puo' venire SOLO dal gate di ruolo (con il bunker acceso vincerebbe 'bunker_richiesto'
        # e il test diventerebbe vacuo, verde per il motivo sbagliato).
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"h" * 32, db_payout=self.d + "/p.db",
            db_finanza=self.d + "/fin.db"))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _r(self, admin_key):
        return crea_router(self.sis, host_key="hk", admin_key=admin_key, base_url="https://x")

    AZIONI = ("rimborso", "storno_penale", "cancella_attivita",
              "alloggio_stato", "controversia_risolvi", "blocco_globale")

    def test_senza_chiave_admin_il_ruolo_e_admin_pieno(self):
        """Modalita' aperta (dev): chi passa _auth_admin deve poter fare TUTTO, senza eccezioni."""
        r = self._r(None)
        self.assertTrue(r._auth_admin(IP), "senza chiave configurata _auth_admin apre (dev)")
        self.assertEqual(r._ruolo_operatore(IP), "admin",
                         "auth dice 'sei root' e il ruolo deve dire la STESSA cosa")
        for azione in self.AZIONI:
            self.assertTrue(r._puo_azione(IP, azione),
                            "azione '%s' negata a chi _auth_admin riconosce come root" % azione)

    def test_senza_chiave_admin_l_arbitrato_non_e_403_di_ruolo(self):
        """Osservabile d'EFFETTO sulla rotta vera che si era rotta (non solo sui predicati)."""
        r = self._r(None)
        s, out = r.gestisci("POST", "/api/admin/controversia/risolvi", {},
                            json.dumps({"riferimento": "NON_ESISTE", "percentuale_ospite": 40}), IP)
        self.assertNotEqual(out.get("errore"), "permesso_negato_ruolo",
                            "arbitrato bloccato da un 403 di RUOLO in modalita' aperta: %r" % (out,))
        self.assertEqual(s, 404, "la rotta deve arrivare alla logica (riferimento inesistente): %r" % (out,))

    def test_con_chiave_configurata_il_gate_di_ruolo_resta_intatto(self):
        """Anti-vacuita': la correzione NON deve spegnere i permessi dove la chiave c'e'."""
        r = self._r("ak")
        self.assertIsNone(r._ruolo_operatore(IP), "senza credenziali il ruolo non e' 'admin'")
        for azione in self.AZIONI:
            self.assertFalse(r._puo_azione(IP, azione),
                             "con chiave configurata l'anonimo non puo' '%s'" % azione)
        H = {"X-Admin-Key": "ak", **IP}
        self.assertEqual(r._ruolo_operatore(H), "admin", "la ROOT resta admin pieno")
        H_falsa = {"X-Admin-Key": "chiave-sbagliata", **IP}
        self.assertIsNone(r._ruolo_operatore(H_falsa), "una chiave errata non promuove ad admin")


if __name__ == "__main__":
    unittest.main(verbosity=2)
