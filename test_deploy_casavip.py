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

    def test_ogni_immagine_presa_da_fuori_ha_versione_e_impronta(self):
        """Voce 263 di RIPRENDI (5/11/2026). nginx di produzione era `image: nginx:alpine`: un nome
        che su Docker Hub cambia a ogni versione ma che il server NON riscarica da solo. Il VPS e'
        rimasto su nginx 1.31.2 (immagine del 22/6) mentre nginx.org pubblicava le riparazioni di nove
        falle del 2026 (la 1.31.2 sta nella fascia di CVE-2026-93479 e CVE-2026-42533: nginx.org/en/CHANGES).
        L'ha trovato la ricerca del giorno, non una prova: il Dockerfile era fissato per impronta,
        questo file no, e Dependabot guardava solo i Dockerfile.
        Regola: un'immagine presa da FUORI si scrive `nome:versione@sha256:<64 cifre>`, cosi' e' la
        stessa ogni volta e quella nuova arriva solo da una PR che passa dalla CI. Non vale per le
        immagini costruite QUI (servizio con `build:`) ne' per chi riusa una di quelle (il backup
        usa l'immagine dell'app)."""
        import re
        # La sezione `services:` fino alla prossima chiave di primo livello (un commento a colonna
        # 0 non la chiude).
        m = re.search(r"(?ms)^services:[ \t]*\n(.*?)(?=^[^\s#]|\Z)", self.testo)
        self.assertIsNotNone(m, "manca la sezione `services:` nel compose")
        sezione = m.group(1)
        nomi = re.findall(r"(?m)^  (\w[\w-]*):\s*$", sezione)
        immagini, costruite_qui = {}, set()
        for nome in nomi:
            blocco = _blocco_servizio(sezione, nome)
            img = re.search(r"(?m)^\s{4}image:\s*(\S+)", blocco)   # niente `$`: regge un commento in coda
            if img:
                immagini[nome] = img.group(1).strip("\"'")
                if re.search(r"(?m)^\s{4}build:", blocco):
                    costruite_qui.add(immagini[nome])
        # Premesse: se il file cambia forma questa prova deve diventare ROSSA, non verde per assenza.
        self.assertIn("nginx", immagini, "premessa: il servizio nginx con la sua `image:`")
        self.assertIn("casavip-app", costruite_qui, "premessa: l'immagine dell'app si costruisce qui")
        fissata = re.compile(r"^[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$")
        libere = sorted("%s: %s" % (n, i) for n, i in immagini.items()
                        if i not in costruite_qui and not fissata.match(i))
        self.assertEqual(libere, [], "immagini prese da fuori SENZA versione e impronta "
                         "(`nome:versione@sha256:...`): %s" % libere)

    def test_dependabot_propone_anche_le_immagini_del_compose(self):
        """Stessa voce 263. Con il solo ecosistema `docker` Dependabot legge i Dockerfile e nessuno
        propone la versione nuova di nginx. Quale file legge `docker-compose` lo decide il suo codice
        (dependabot-core, docker/lib/dependabot/docker_compose/file_fetcher.rb, letto il 5/11):
        `FILENAME_REGEX = /(docker-)?compose(-[\\w]+)?(?>\\.[\\w-]+)?\\.ya?ml/i`, cercato nella cartella
        data: con `directory: "/"` prende anche `docker-compose.casavip.yml`."""
        import re
        d = _leggi(os.path.join(".github", "dependabot.yml"))
        voci = re.split(r"(?m)^\s*-\s*package-ecosystem:", d)[1:]
        compose = [v for v in voci
                   if re.match(r"""\s*["']?docker-compose["']?\s*$""", v.splitlines()[0])]
        self.assertEqual(len(compose), 1,
                         "Dependabot non guarda i file docker-compose: nginx resta senza proposte")
        self.assertRegex(compose[0], r"""(?m)^\s*directory:\s*["']/["']\s*$""",
                         "il compose di produzione sta nella radice: `directory: \"/\"`")
        # E il file di produzione non deve stare fra gli esclusi, nemmeno per un glob scritto largo
        # (es. "docker-compose*.yml"): Dependabot tornerebbe cieco su nginx e questa prova verde.
        import fnmatch
        esclusi = []
        if "exclude-paths:" in compose[0]:
            dopo = compose[0].split("exclude-paths:", 1)[1]
            esclusi = re.findall(r"""(?m)^\s*-\s*["']?([^"'\s]+)["']?\s*$""", dopo)
        # `fnmatch` legge «**/» alla lettera, Dependabot no («**» = anche nessuna cartella):
        # «**/*.yml» escluderebbe il compose della radice, quindi si prova anche senza «**/».
        presi = [e for e in esclusi
                 if fnmatch.fnmatch("docker-compose.casavip.yml", e)
                 or fnmatch.fnmatch("docker-compose.casavip.yml", e.replace("**/", ""))]
        self.assertEqual(presi, [], "il compose di produzione e' escluso da Dependabot: %s" % presi)


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


class TestIlDeployNONLASCIAILSITOAPPESO(unittest.TestCase):
    """⏱️ IL SITO NON DEVE RESTARE APPESO QUANDO L'APPLICAZIONE NON C'E'.

    **Il fatto, misurato il 2026-08-20.** Il 19/08 alle 21:45:43 UTC la sentinella esterna e'
    andata rossa con `curl: (28) Connection timed out after 20001 ms` su `/api/health`.
    Il rosso era **vero**: `casavip_app` era ripartito 56 secondi prima (`StartedAt
    2026-08-19T21:44:47Z`, letto da `docker inspect`). Ma il difetto non e' che l'applicazione
    riparta — quello dura pochi secondi: e' che **nginx resta appeso**. L'upstream e' uno solo
    e su `location /` non c'era `proxy_connect_timeout`: il valore di serie di nginx e'
    **60 secondi**. Chi apriva il sito durante il deploy vedeva una pagina bianca per un
    minuto, senza sapere se stesse caricando o se fosse rotto.

    Qui si pretendono le tre cose che trasformano un'attesa cieca in una risposta onesta:
      1. **ogni** porta che inoltra all'applicazione dichiara un tetto all'attesa di
         connessione (non «almeno una»: le location con `proxy_pass` sono due);
      2. c'e' una via d'uscita per gli errori che genera **nginx** quando l'applicazione non
         risponde (`502`/`504`), che risponde subito invece di far aspettare;
      3. ⛔ e `proxy_intercept_errors` resta **spento**, dichiarato per iscritto: se si
         accendesse, nginx si mangerebbe anche i `503` che manda l'APPLICAZIONE — cioe' il
         fail-safe «gateway giu' = non si conferma niente», che e' la regola dei soldi vista
         dal browser. Un rimedio che spegne una difesa non e' un rimedio.

    ⛔ COSA QUESTA GUARDIA NON FA (D18 punto 3): non rende il deploy senza interruzione. Per
    quello servono due contenitori vivi insieme, ed e' un lavoro a se'. Qui la finestra resta,
    ma smette di essere un'attesa muta di un minuto.
    """

    def setUp(self):
        self.n = _leggi("deploy/nginx.casavip.ssl.conf")

    def _blocchi_con_proxy(self):
        """I pezzi di configurazione che inoltrano all'applicazione, uno per uno."""
        pezzi = []
        for blocco in self.n.split("location "):
            if "proxy_pass" in blocco:
                pezzi.append(blocco)
        return pezzi

    def test_ogni_porta_verso_l_applicazione_ha_un_tetto_all_attesa(self):
        blocchi = self._blocchi_con_proxy()
        self.assertGreaterEqual(len(blocchi), 2,
                                "mi aspettavo almeno due location con proxy_pass: se sono "
                                "cambiate, questa guardia sta contando la cosa sbagliata")
        for b in blocchi:
            prima_riga = b.strip().splitlines()[0]
            self.assertIn("proxy_connect_timeout", b,
                          "la location `%s` inoltra all'applicazione senza tetto all'attesa "
                          "di connessione: di serie nginx aspetta 60 secondi, e durante il "
                          "deploy il sito resta appeso" % prima_riga)

    def test_c_e_una_risposta_pronta_quando_l_applicazione_non_risponde(self):
        self.assertRegex(self.n, r"error_page\s+502\s+504",
                         "nessuna via d'uscita per 502/504: quando l'applicazione non c'e', "
                         "chi apre il sito non riceve niente finche' non scade l'attesa")
        self.assertIn("@manutenzione", self.n,
                      "manca la location con la risposta di cortesia")
        self.assertRegex(self.n, r"return\s+503",
                         "la pagina di attesa deve rispondere 503, non 200: il sito e' "
                         "davvero indisponibile, e dire 200 mentirebbe alla sentinella")

    def test_il_503_DELL_APPLICAZIONE_arriva_intatto_al_browser(self):
        """La riga che protegge il fail-safe dei soldi: `proxy_intercept_errors` spento e
        detto. Di serie e' gia' spento, ma un valore di serie non e' una decisione."""
        for b in self._blocchi_con_proxy():
            self.assertRegex(
                b, r"proxy_intercept_errors\s+off",
                "questa location non dichiara `proxy_intercept_errors off`: senza quella "
                "riga nessuno sa se il 503 «pagamento non disponibile» dell'applicazione "
                "arriva all'ospite o viene sostituito dalla pagina di attesa")


class TestIlManifestoDellAppStaNelProgetto(unittest.TestCase):
    """6/11/2026, voce 263 di RIPRENDI, limite (d). `deploy/index.html` e `deploy/host.html`
    citano `<link rel="manifest" href="/manifest.json">`, ma `deploy/manifest.json` esisteva SOLO
    sul VPS (433 byte, 24/6): la riga `*.json` del `.gitignore` lo escludeva in silenzio (lo
    sbaglio S13). In produzione 200, sulla copia del sito 404, e un server rifatto da zero
    l'avrebbe perso. Qui: ogni manifesto citato dalle pagine c'e', NON e' escluso da git, e le
    sue icone esistono."""

    def test_ogni_manifesto_citato_dalle_pagine_e_nel_progetto(self):
        import glob
        import json
        import re
        import subprocess  # nosec B404 - `git check-ignore` su un percorso del progetto
        citati = set()
        for pagina in glob.glob(os.path.join("deploy", "*.html")):
            citati.update(re.findall(
                r"""<link[^>]*rel=["']manifest["'][^>]*href=["']/([^"']+)["']""", _leggi(pagina)))
        self.assertTrue(citati, "premessa: le pagine citano un manifesto")
        for nome in sorted(citati):
            percorso = os.path.join("deploy", nome)
            self.assertTrue(os.path.isfile(percorso),
                            "le pagine citano /%s ma deploy/%s non c'e'" % (nome, nome))
            # `--no-index` (ricontrollo del 6/11): senza, `check-ignore` dice «non escluso» per
            # ogni file gia' tracciato, e togliere l'eccezione dal `.gitignore` restava VERDE.
            ignorato = subprocess.run(["git", "check-ignore", "-q", "--no-index", percorso],  # nosec B603 B607  # noqa: S603, S607
                                      capture_output=True).returncode == 0
            self.assertFalse(ignorato, "deploy/%s e' ESCLUSO da git: in CI e su un server "
                             "nuovo non ci sarebbe" % nome)
            dati = json.loads(_leggi(percorso))
            self.assertEqual(dati.get("start_url"), "/", "manifesto senza start_url")
            icone = [i.get("src", "") for i in dati.get("icons") or []]
            self.assertTrue(icone, "manifesto senza icone")
            for src in icone:
                self.assertTrue(os.path.isfile(os.path.join("deploy", src.lstrip("/"))),
                                "il manifesto cita l'icona %s che non c'e'" % src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
