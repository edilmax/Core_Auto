"""GUARDIA — chiude i 3 "punti scoperti" trovati da collaudi/mappa_scoperta.py:
  M1: la rotta /sitemap-blog.xml non era nominata da nessun test → qui la nominiamo e verifichiamo
      che robots.txt la dichiari e che il contenuto sia XML valido.
  M2: i moduli fase191 (kill-switch) e fase192 (multi-admin) erano testati SOLO via endpoint, mai
      importati direttamente → qui testiamo la loro LOGICA PURA (unità), così nessun ramo resta scoperto.

Vista ROSSA: se la RBAC lasciasse un 'supporto' toccare i soldi, se un revocato restasse attivo, o se
il kill-switch non rispondesse all'env, questi asserti falliscono.
"""
import os
import tempfile
import unittest
import xml.dom.minidom as minidom

from fase191_blocco_globale import BloccoGlobale, crea_blocco_globale
from fase192_admin_accounts import AZIONI_SOLO_ADMIN, crea_admin_accounts, puo
from fase198_blog import sitemap_blog
from fase83_server import robots_txt

BASE = "https://bookinvip.com"


class TestKillSwitch(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.flag = self.d + "/blocco.flag"
        self.b = crea_blocco_globale(self.flag, env_var="TEST_BLOCCO_XZ")

    def tearDown(self):
        os.environ.pop("TEST_BLOCCO_XZ", None)

    def test_default_spento(self):
        self.assertFalse(self.b.attivo())

    def test_toggle_runtime_file(self):
        self.assertTrue(self.b.imposta(True, motivo="incidente", chi="root"))
        self.assertTrue(self.b.attivo())
        self.assertTrue(self.b.stato()["runtime"])
        self.assertTrue(self.b.imposta(False))
        self.assertFalse(self.b.attivo())

    def test_env_autorevole(self):
        os.environ["TEST_BLOCCO_XZ"] = "1"
        self.assertTrue(self.b.attivo(), "l'ENV deve congelare (autorevole)")
        self.assertTrue(self.b.stato()["env"])

    def test_stato_read_only_chiavi(self):
        s = self.b.stato()
        for k in ("attivo", "env", "runtime", "dettaglio"):
            self.assertIn(k, s)


class TestRBAC(unittest.TestCase):
    def test_admin_tutto(self):
        for az in list(AZIONI_SOLO_ADMIN) + ["leggi", "qualsiasi"]:
            self.assertTrue(puo("admin", az), "admin deve poter fare %r" % az)

    def test_supporto_niente_soldi(self):
        for az in AZIONI_SOLO_ADMIN:
            self.assertFalse(puo("supporto", az), "supporto NON deve toccare i soldi: %r" % az)

    def test_supporto_puo_azioni_non_soldi(self):
        self.assertTrue(puo("supporto", "leggi_dashboard"))

    def test_ruolo_ignoto_negato(self):
        self.assertFalse(puo("sconosciuto", "leggi"))
        self.assertFalse(puo("", "leggi"))
        self.assertFalse(puo(None, "leggi"))


class TestAdminAccounts(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.a = crea_admin_accounts(self.d + "/adm.db")
        self.a.crea("op@bookinvip.com", "password-lunga-1", "supporto", creato_da="root")

    def test_login_giusto_e_sbagliato(self):
        ok = self.a.verifica("op@bookinvip.com", "password-lunga-1")
        self.assertTrue(ok["ok"] and ok["ruolo"] == "supporto")
        ko = self.a.verifica("op@bookinvip.com", "sbagliata")
        self.assertFalse(ko["ok"], "password sbagliata non deve autenticare")

    def test_revoca_istantanea(self):
        self.assertEqual(self.a.ruolo_attivo("op@bookinvip.com"), "supporto")
        self.assertTrue(self.a.revoca("op@bookinvip.com"))
        self.assertIsNone(self.a.ruolo_attivo("op@bookinvip.com"), "revocato deve sparire subito")
        self.assertFalse(self.a.verifica("op@bookinvip.com", "password-lunga-1")["ok"])
        self.assertTrue(self.a.riattiva("op@bookinvip.com"))
        self.assertEqual(self.a.ruolo_attivo("op@bookinvip.com"), "supporto")

    def test_cambio_ruolo(self):
        self.assertTrue(self.a.imposta_ruolo("op@bookinvip.com", "admin"))
        self.assertEqual(self.a.ruolo_attivo("op@bookinvip.com"), "admin")

    def test_password_non_in_chiaro(self):
        # la password non deve comparire da nessuna parte nel record elencato
        for r in self.a.lista():
            self.assertNotIn("password-lunga-1", str(r))


class TestRottaSitemapBlog(unittest.TestCase):
    def test_robots_dichiara_sitemap_blog(self):
        self.assertIn("/sitemap-blog.xml", robots_txt(BASE),
                      "robots.txt deve dichiarare /sitemap-blog.xml")

    def test_sitemap_blog_xml_valido(self):
        xml = sitemap_blog(BASE)
        minidom.parseString(xml)                     # ben formata o solleva
        self.assertIn("/blog/", xml)


if __name__ == "__main__":
    unittest.main(verbosity=2)
