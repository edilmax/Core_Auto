"""GUARDIA — il gate host (/entra-host) non deve MAI essere un vicolo cieco: chi arriva senza
account (es. dal bot Telegram) deve poter REGISTRARSI, e chi ha perso la password deve poter
RECUPERARE. Prima il gate era solo 'Accedi' → l'host nuovo restava bloccato (bug logico del fondatore).

Vista ROSSA: senza i link Registrati / Password dimenticata, questi asserti falliscono.
"""
import unittest

from fase83_server import pagina_login_gate


class TestGateHostNonVicoloCieco(unittest.TestCase):
    def test_host_offre_registrazione_e_recupero(self):
        h = pagina_login_gate("host", "https://bookinvip.com")
        # login: email + password
        self.assertIn('id="em"', h)
        self.assertIn('id="pw"', h)
        # REGISTRAZIONE per il nuovo host
        self.assertIn("/diventa-host.html", h, "manca il link Registrati verso la registrazione")
        self.assertIn("Registrati", h)
        # RECUPERO password (richiesta del link)
        self.assertIn("Password dimenticata", h)
        self.assertIn("/api/host/password_dimenticata", h, "manca il flusso di recupero password")
        # COMPLETAMENTO reset dal link email: il gate PUBBLICO deve gestire il #reset (host.html è
        # gated 302 -> il reset non partirebbe mai da lì). Il gate chiede la nuova password e la applica.
        self.assertIn("#reset=", h, "il gate non gestisce il link di reset (#reset)")
        self.assertIn("/api/host/password_reset", h, "il gate non applica la nuova password")

    def test_admin_e_bunker_non_hanno_registrazione(self):
        # solo l'host è pubblico e registrabile; admin/bunker NO
        for liv in ("admin", "bunker"):
            g = pagina_login_gate(liv, "https://bookinvip.com")
            self.assertNotIn("/diventa-host.html", g, "%s non deve offrire registrazione host" % liv)
            self.assertNotIn("/api/host/password_dimenticata", g)


if __name__ == "__main__":
    unittest.main(verbosity=2)
