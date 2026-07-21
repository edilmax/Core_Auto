"""
Test strutturale del deploy Casa VIP (anti-drift sulle proprieta' di sicurezza).
Non avvia Docker: verifica che i file di deploy mantengano le garanzie dichiarate
(non-root, zero pip, app non esposta sull'host, rete interna, backup, hardening nginx).
"""
import os
import unittest

# (nessuna libreria esterna: le verifiche sono testuali)


def _leggi(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def _blocco_servizio(testo, nome):
    """Il blocco di un servizio del compose, senza parser YAML: dalla riga `  nome:`
    fino al servizio successivo allo stesso livello di indentazione."""
    import re
    m = re.search(r"(?m)^  %s:\s*$" % re.escape(nome), testo)
    if not m:
        return ""
    resto = testo[m.end():]
    fine = re.search(r"(?m)^  \w[\w-]*:\s*$|^\w", resto)
    return resto[:fine.start()] if fine else resto



class TestDockerfile(unittest.TestCase):
    def setUp(self):
        self.d = _leggi("Dockerfile.casavip")

    def test_non_root(self):
        self.assertIn("USER app", self.d)
        self.assertIn("10001", self.d)

    def test_zero_pip(self):
        # Casa VIP gira su pura stdlib: NESSUN pip install
        self.assertNotIn("pip install", self.d)

    def test_healthcheck_ed_expose(self):
        self.assertIn("HEALTHCHECK", self.d)
        self.assertIn("EXPOSE 8080", self.d)
        self.assertIn("/api/health", self.d)


# ─────────────────────────────────────────────────────────────────────────────────
# FINTO VERDE CHIUSO (2026-07-21). Questa classe era gated su `pyyaml` con
# `@unittest.skipUnless(HA_YAML, ...)`: su una macchina senza quella libreria
# **tredici test non giravano affatto**, e fra questi c'erano le verifiche sulla
# corazza di nginx, sull'HTTPS, sui segreti nel .gitignore e sulla generazione delle
# chiavi. Verdi per assenza, cioe' peggio che assenti: si credeva di essere coperti.
#
# Ora le verifiche sono TESTUALI sul file di compose (lo stesso metodo gia' usato con
# successo da `test_db_persistenti.py`): niente dipendenze, e girano SEMPRE.
# ─────────────────────────────────────────────────────────────────────────────────
class TestCompose(unittest.TestCase):
    """Le garanzie del compose di produzione, verificate senza librerie esterne."""

    def setUp(self):
        self.testo = _leggi("docker-compose.casavip.yml")
        self.app = _blocco_servizio(self.testo, "app")
        self.nginx = _blocco_servizio(self.testo, "nginx")

    def test_app_non_esposta_sull_host(self):
        """`ports:` nel servizio app significherebbe raggiungibile da Internet
        scavalcando nginx. Deve esserci solo `expose:` (rete interna)."""
        self.assertNotRegex(self.app, r"(?m)^\s{4}ports:",
                            "il servizio app pubblica una porta sull'host!")
        self.assertRegex(self.app, r"(?m)^\s{4}expose:")

    def test_solo_nginx_esposto(self):
        self.assertRegex(self.nginx, r"(?m)^\s{4}ports:")
        for porta in ('"80:80"', '"443:443"'):
            self.assertIn(porta, self.nginx)

    def test_self_healing(self):
        self.assertRegex(self.app, r"(?m)^\s{4}restart:\s*unless-stopped")
        self.assertRegex(self.app, r"(?m)^\s{4}healthcheck:")
        self.assertRegex(self.nginx, r"condition:\s*service_healthy")

    def test_rete_interna_isolata(self):
        self.assertRegex(self.app, r"(?m)^\s{4}networks:\s*\n\s*-\s*interna")
        self.assertRegex(self.testo, r"(?m)^networks:\s*\n\s*interna:")

    def test_backup_service(self):
        self.assertRegex(self.testo, r"(?m)^\s{2}backup:")
        self.assertIn("backup_casavip.sh", _blocco_servizio(self.testo, "backup"))

    def test_volume_persistente(self):
        self.assertRegex(self.testo, r"(?m)^volumes:\s*\n\s*casavip_data:")
        self.assertIn("casavip_data:/data", self.app)

    def test_nessun_segreto_scritto_nel_compose(self):
        """I segreti stanno in .env.casavip (gitignorato), mai qui dentro."""
        for spia in ("sk_live", "sk_test", "whsec_", "BEGIN PRIVATE KEY"):
            self.assertNotIn(spia, self.testo, "segreto nel compose: %s" % spia)


class TestCorazzaNginx(unittest.TestCase):
    """Erano dentro la classe saltata: sono verifiche di SICUREZZA e devono girare."""

    def setUp(self):
        self.n = _leggi("deploy/nginx.casavip.ssl.conf")

    def test_rate_limit_definito_E_applicato(self):
        """FINTO VERDE CHIUSO (2026-07-21, terza lezione della giornata). Prima bastava
        che la sottostringa `limit_req` comparisse: ma nel file c'e' sia la DEFINIZIONE
        della zona (`limit_req_zone ...`) sia la sua APPLICAZIONE (`limit_req zone=...`),
        e togliendo la seconda — cioe' disattivando davvero il rate-limit — il test
        restava verde perche' trovava la prima."""
        import re
        self.assertRegex(self.n, r"(?m)^\s*limit_req_zone\s+\S+\s+zone=\w+",
                         "la zona di rate-limit non e' definita")
        # OGNI porta verso l'applicazione deve avere il proprio rate-limit: contarne
        # "almeno uno" lascerebbe scoperta una location e il test non se ne accorgerebbe
        # (successo davvero: le location con proxy_pass sono due).
        porte = re.findall(r"location[^\n{]*\{(?:[^{}]|\{[^}]*\})*?\}", self.n, re.S)
        verso_app = [b for b in porte if "proxy_pass" in b]
        self.assertGreaterEqual(len(verso_app), 1,
                                "nessuna location inoltra all'applicazione?")
        scoperte = [b.split("\n")[0].strip()[:60]
                    for b in verso_app if "limit_req zone=" not in b]
        self.assertEqual(scoperte, [],
                         "queste porte verso l'applicazione NON hanno rate-limit "
                         "(raffiche di richieste passerebbero): %s" % scoperte)

    def test_percorsi_pericolosi_bloccati(self):
        """Traversal (anche codificato), byte nulli e dotfile."""
        import re
        blocco = re.search(r"location[^\n]*%2e%2e[^\n]*\{[^}]*\}", self.n)
        self.assertIsNotNone(blocco, "manca il blocco che respinge il path traversal")
        self.assertIn("403", blocco.group(0), "il traversal non viene respinto con 403")
        self.assertRegex(self.n, r"location\s+~\s*/\\\.",
                         "i file nascosti (dotfile) non sono bloccati")

    def test_sonda_di_salute_presente(self):
        import re
        self.assertRegex(self.n, r"location\s*=\s*/healthz",
                         "senza /healthz i controlli di salute non funzionano")

    def test_server_tokens_spento_in_OGNI_blocco(self):
        """FINTO VERDE CHIUSO (2026-07-21). Prima si chiedeva solo se la stringa
        `server_tokens off` comparisse DA QUALCHE PARTE. Ma i blocchi `server` sono
        due e la direttiva compare due volte: accendendone uno solo, il test restava
        verde perche' trovava l'altro. Per una direttiva di sicurezza la domanda giusta
        non e' "c'e'?" ma "c'e' OVUNQUE serva, e non c'e' MAI il suo contrario?"."""
        import re
        self.assertNotRegex(self.n, r"server_tokens\s+on",
                            "da qualche parte la versione di nginx viene mostrata")
        blocchi = len(re.findall(r"(?m)^\s*server\s*\{", self.n))
        spenti = len(re.findall(r"server_tokens\s+off", self.n))
        self.assertGreaterEqual(blocchi, 1, "nessun blocco server nel file?")
        self.assertEqual(spenti, blocchi,
                         "server_tokens off compare %d volte ma i blocchi server sono "
                         "%d: qualcuno resta scoperto" % (spenti, blocchi))

    def test_gli_header_di_sicurezza_sono_su_OGNI_blocco_che_serve_traffico(self):
        """Stessa lezione applicata agli header: non basta che ci siano una volta."""
        import re
        blocchi = re.split(r"(?m)^\s*server\s*\{", self.n)[1:]
        serventi = [b for b in blocchi if "listen 443" in b or "proxy_pass" in b]
        self.assertGreaterEqual(len(serventi), 1)
        for i, b in enumerate(serventi):
            self.assertIn("X-Content-Type-Options", b,
                          "il blocco servente n.%d non manda l'header anti-sniffing" % i)

    def test_https_pronto(self):
        self.assertIn("listen 443 ssl", self.n)
        self.assertIn("letsencrypt", self.n)


class TestSegretiEScript(unittest.TestCase):
    """Anche queste erano ferme: riguardano le chiavi vere."""

    def test_env_example(self):
        e = _leggi(".env.casavip.example")
        self.assertIn("CASAVIP_SEGRETO", e)
        self.assertIn("HOST_KEY", e)

    def test_script_presenti(self):
        self.assertTrue(os.path.isfile("deploy/genera_segreti.sh"))
        self.assertTrue(os.path.isfile("deploy/backup_casavip.sh"))

    def test_genera_segreti_usa_csprng(self):
        s = _leggi("deploy/genera_segreti.sh")
        self.assertTrue("openssl rand" in s or "secrets.token_hex" in s,
                        "le chiavi non nascono da un generatore crittografico")
        self.assertIn("chmod 600", s)

    def test_backup_atomico(self):
        b = _leggi("deploy/backup_casavip.sh")
        self.assertTrue(".backup" in b or ".backup(" in b)
        self.assertIn("RETENTION", b)

    def test_gitignore_segreti(self):
        g = _leggi(".gitignore")
        self.assertIn(".env", g)


if __name__ == "__main__":
    unittest.main(verbosity=2)
