# -*- coding: utf-8 -*-
"""PARITA' DI AMBIENTE — la CI deve provare il prodotto sul Python su cui il prodotto VIVE.

IL BUCO CHE QUESTO FILE CHIUDE
------------------------------
E' il modo di rompersi n.8 di `CLAUDE.md` ("ambiente diverso: locale != produzione"), ed era
aperto e **non dichiarato**: la produzione gira dentro l'immagine di `Dockerfile.casavip`
(`FROM python:3.11-slim`), mentre TUTTA la CI girava su un Python diverso. Verde in CI non
voleva dire verde in produzione, e nessuno se ne accorgeva. Misura presa il 2026-07-29 prima
di scrivere il job: la suite intera su 3.11 dava **22 rossi** che su 3.9 erano verdi.

Peggio: nessun job costruiva l'immagine. La CI provava i sorgenti sparsi sul runner; l'unica
cosa che gira davvero sul VPS non veniva mai assemblata ne' avviata.

PERCHE' QUESTO FILE ESISTE, E NON E' UN DOPPIONE DI `test_pipeline_ci.py`
------------------------------------------------------------------------
`test_pipeline_ci.py` prova che il **cancello** e' cablato bene (chi blocca, chi no, i needs).
Qui si prova un'altra cosa: che quello che `ci.yml` **dichiara a parole** corrisponda alla
**macchina vera**. Il blocco "PARITA' DI AMBIENTE" in testa a `ci.yml` non e' un commento
gentile: e' un DATO, e questo file e' la guardia che quel file nomina. Senza, era una frase
ornamentale — vietate dalla REGOLA FERREA 2.

OGNI CONTROLLO DICHIARA IL SUO DENOMINATORE (regola 15 dell'appendice del registro): si chiede
"c'e' OVUNQUE?", mai "c'e'?". Le versioni usate e quelle dichiarate si confrontano come
INSIEMI UGUALI, cosi' il rosso arriva in tutte e due le direzioni: una versione usata e non
dichiarata, e una dichiarata che nessuno usa piu'.
"""
from __future__ import annotations

import io
import os
import re
import unittest

import yaml

QUI = os.path.dirname(os.path.abspath(__file__))
CI_YML = os.path.join(QUI, ".github", "workflows", "ci.yml")
DOCKERFILE = os.path.join(QUI, "Dockerfile.casavip")
INDEX_HTML = os.path.join(QUI, "deploy", "index.html")
SERVER_PY = os.path.join(QUI, "fase83_server.py")


def _leggi(percorso: str) -> str:
    with io.open(percorso, encoding="utf-8") as f:
        return f.read()


def _versione_di_produzione() -> str:
    """L'unica verita' su cosa gira davvero: la riga FROM del Dockerfile di produzione."""
    righe = [r.strip() for r in _leggi(DOCKERFILE).splitlines() if r.strip().startswith("FROM ")]
    if len(righe) != 1:
        raise AssertionError(
            "Dockerfile.casavip ha %d righe FROM (attesa 1): con piu' stadi la 'versione di "
            "produzione' non e' piu' univoca e questa guardia va riscritta di proposito" % len(righe))
    m = re.search(r"FROM\s+python:(\d+\.\d+)", righe[0])
    if not m:
        raise AssertionError("la riga FROM non nomina una versione di python: %r" % righe[0])
    return m.group(1)


class TestVersioniDiPythonDichiarateEUSATE(unittest.TestCase):
    """Il blocco 'PARITA' DI AMBIENTE' di ci.yml e' un dato, e deve dire il vero."""

    def setUp(self):
        self.testo = _leggi(CI_YML)
        self.prod = _versione_di_produzione()
        # dichiarate: le righe "#      3.11 - MOTIVO: ..." del blocco in testa a ci.yml
        self.dichiarate = re.findall(r"^#\s+(\d+\.\d+)\s+- MOTIVO:", self.testo, re.M)
        # usate: ogni setup-python del file
        self.usate = re.findall(r"python-version:\s*'([\d.]+)'", self.testo)

    def test_il_blocco_di_dichiarazione_esiste_ancora(self):
        """Se qualcuno cancella il blocco, questo test diventa rosso: e' il suo scopo."""
        self.assertIn("PARITA' DI AMBIENTE", self.testo,
                      "il blocco di dichiarazione della parita' d'ambiente e' sparito da ci.yml")
        self.assertGreaterEqual(
            len(self.dichiarate), 1,
            "il blocco c'e' ma non dichiara nessuna versione con la sua riga '- MOTIVO:'")

    def test_ogni_versione_dichiarata_una_volta_sola(self):
        self.assertEqual(len(self.dichiarate), len(set(self.dichiarate)),
                         "una versione e' dichiarata due volte con due motivi diversi: %r"
                         % (self.dichiarate,))

    def test_usate_e_dichiarate_sono_LO_STESSO_INSIEME(self):
        """Rosso nelle DUE direzioni — e' il punto di tutta la guardia.

        · una versione usata da un job e non dichiarata = parita' non piu' governata;
        · una versione dichiarata che nessun job usa = la dichiarazione e' diventata
          un ornamento (qualcuno ha tolto il job e lasciato la prosa).
        """
        self.assertEqual(
            sorted(set(self.usate)), sorted(set(self.dichiarate)),
            "le versioni di Python USATE nei job e quelle DICHIARATE nel blocco "
            "'PARITA' DI AMBIENTE' non coincidono. usate=%r dichiarate=%r"
            % (sorted(set(self.usate)), sorted(set(self.dichiarate))))

    def test_la_dichiarazione_nomina_la_versione_della_PRODUZIONE(self):
        self.assertIn(
            self.prod, self.dichiarate,
            "Dockerfile.casavip gira su python:%s ma quella versione non e' dichiarata in "
            "ci.yml: la CI non sa piu' su cosa vive il prodotto" % self.prod)
        self.assertIn(
            "PRODUZIONE: python:%s-slim" % self.prod, self.testo,
            "la riga 'PRODUZIONE: python:X.Y-slim' di ci.yml non coincide piu' con la riga "
            "FROM del Dockerfile (Dockerfile dice %s)" % self.prod)


class TestLaSuiteGiraSulPythonDiProduzione(unittest.TestCase):
    """Dichiarare la versione non basta: qualcuno ci deve far girare la suite INTERA."""

    def setUp(self):
        self.testo = _leggi(CI_YML)
        self.ci = yaml.safe_load(self.testo)
        self.jobs = self.ci["jobs"]
        self.prod = _versione_di_produzione()

    def _versione_del_job(self, job):
        for passo in job.get("steps", []):
            v = (passo.get("with") or {}).get("python-version")
            if v:
                return str(v)
        return None

    def _comandi(self, job):
        return "\n".join(str(p.get("run", "")) for p in job.get("steps", []))

    def test_esiste_un_job_che_gira_la_suite_sul_python_di_produzione(self):
        candidati = [n for n, j in self.jobs.items()
                     if self._versione_del_job(j) == self.prod
                     and "unittest" in self._comandi(j)]
        self.assertTrue(
            candidati,
            "nessun job gira `unittest` su python %s (la versione di PRODUZIONE): la suite non "
            "vede mai il Python su cui il prodotto vive davvero" % self.prod)

    def test_il_debito_dichiarato_e_un_CRICCHETTO_che_puo_solo_stringersi(self):
        """L'elenco delle esclusioni su 3.11 deve stare DENTRO il job, esplicito e contato.

        Un filtro che nessuno rilegge diventa un buco permanente: qui si pretende che
        (a) l'elenco esista scritto a mano nel comando, (b) il job si difenda da un filtro
        troppo goloso con una soglia minima di moduli, (c) il debito continui a GIRARE in un
        passo report-only, cosi' resta visibile nel log invece di sparire.
        """
        job = self.jobs.get("full-suite-311")
        self.assertIsNotNone(job, "il job full-suite-311 non c'e' piu'")
        cmd = self._comandi(job)
        self.assertIn("grep -vE", cmd, "l'elenco del debito non e' piu' esplicito nel comando")
        self.assertRegex(cmd, r"-lt\s+300",
                         "manca la soglia minima di moduli: un filtro sbagliato potrebbe "
                         "mangiare la suite e restare verde")
        self.assertTrue(any((p.get("if") == "always()" or p.get("if") is True)
                            and "unittest" in str(p.get("run", ""))
                            for p in job.get("steps", [])),
                        "il debito non gira piu' in un passo report-only: sparirebbe dalla vista")

    def test_i_moduli_esclusi_esistono_davvero(self):
        """Un'esclusione su un file inesistente e' un'esclusione che non protegge niente,
        e nasconde il fatto che il debito e' stato spostato altrove."""
        cmd = self._comandi(self.jobs["full-suite-311"])
        m = re.search(r"grep -vE '\^\(([^)]+)\)", cmd)
        self.assertIsNotNone(m, "l'elenco dei moduli esclusi non e' piu' leggibile nel comando")
        esclusi = m.group(1).split("|")
        mancanti = [x for x in esclusi if not os.path.exists(os.path.join(QUI, x + ".py"))]
        self.assertEqual([], mancanti,
                         "questi moduli sono esclusi dalla suite su 3.11 ma NON esistono piu': "
                         "l'esclusione va tolta. %r" % (mancanti,))


class TestIlJobImmagineDiceIlVEROSullArtefatto(unittest.TestCase):
    """Il job `immagine` afferma cose sull'artefatto. Ogni affermazione va confrontata con
    la macchina vera: un'asserzione che nessuno confronta e' un ornamento."""

    def setUp(self):
        self.testo = _leggi(CI_YML)
        self.jobs = yaml.safe_load(self.testo)["jobs"]
        self.job = self.jobs.get("immagine")
        self.assertIsNotNone(self.job, "il job `immagine` non c'e' piu'")
        self.cmd = "\n".join(str(p.get("run", "")) for p in self.job.get("steps", []))

    def test_costruisce_un_dockerfile_che_esiste(self):
        m = re.search(r"docker build -f (\S+)", self.cmd)
        self.assertIsNotNone(m, "il job non costruisce piu' nessuna immagine")
        self.assertTrue(os.path.exists(os.path.join(QUI, m.group(1))),
                        "il job costruisce %s, che non esiste" % m.group(1))

    def test_uid_preteso_uguale_a_quello_del_dockerfile(self):
        # ancorata a UID_VERO: senza l'ancora la stessa forma pesca il `!= "200"` del
        # controllo HTTP, e la guardia confronta due numeri che non c'entrano nulla.
        m = re.search(r'\$UID_VERO"?\s*!=\s*"(\d+)"', self.cmd)
        self.assertIsNotNone(m, "il job non verifica piu' che il container NON giri da root")
        atteso = m.group(1)
        d = re.search(r"useradd[^\n]*-u\s+(\d+)", _leggi(DOCKERFILE))
        self.assertIsNotNone(d, "il Dockerfile non crea piu' un utente con uid esplicito")
        self.assertEqual(atteso, d.group(1),
                         "la CI pretende uid %s ma il Dockerfile ne crea %s: la guardia "
                         "sarebbe rossa per sempre (falso allarme) oppure cieca"
                         % (atteso, d.group(1)))

    def test_il_titolo_preteso_esiste_davvero_nella_home(self):
        m = re.search(r'grep -q "([^"]*<title>[^"]*)" pagina\.html', self.cmd)
        self.assertIsNotNone(m, "il job non verifica piu' che / sia la home del prodotto")
        self.assertIn(m.group(1), _leggi(INDEX_HTML),
                      "la CI cerca %r nella home, ma deploy/index.html non lo contiene: "
                      "guardia destinata a un rosso permanente" % m.group(1))

    def test_le_chiavi_pretese_nella_sonda_esistono_nel_server(self):
        attese = re.findall(r"for ATTESO in ((?:'[^']*'\s*)+)", self.cmd)
        self.assertTrue(attese, "il job non controlla piu' il CORPO della sonda: un 200 da "
                                "solo non dimostra che il prodotto sia dentro l'immagine")
        pezzi = re.findall(r"'([^']+)'", attese[0])
        self.assertGreaterEqual(len(pezzi), 2,
                                "il corpo della sonda e' controllato su meno di 2 chiavi")
        server = _leggi(SERVER_PY).replace(" ", "")
        for atteso in pezzi:
            self.assertIn(atteso.replace(" ", ""), server,
                          "la CI pretende %r nel corpo di /api/health, ma il server non lo "
                          "produce da nessuna parte" % atteso)

    def test_il_container_viene_spento_SEMPRE(self):
        """Un container lasciato acceso avvelena i job successivi del runner."""
        spegni = [p for p in self.job["steps"] if "docker rm -f" in str(p.get("run", ""))]
        self.assertTrue(spegni, "il job non spegne piu' il container")
        self.assertTrue(all(p.get("if") == "always()" or p.get("if") is True for p in spegni),
                        "lo spegnimento del container non e' `if: always()`: dopo un passo "
                        "rosso il container resterebbe acceso")

    def test_nessuna_chiave_vera_nel_job(self):
        """REGOLA FERREA 14: le chiavi non si stampano. Qui devono essere FINTE e dichiarate."""
        self.assertNotRegex(self.cmd, r"sk_live_[A-Za-z0-9]{10,}",
                            "c'e' una chiave Stripe VIVA dentro ci.yml")
        for nome in ("HOST_KEY", "ADMIN_KEY"):
            m = re.search(nome + r"=(\S+)", self.cmd)
            self.assertIsNotNone(m, "il job non imposta piu' %s" % nome)
            self.assertIn("finta", m.group(1),
                          "%s non e' dichiarata finta nel job immagine: %r" % (nome, m.group(1)))


class TestINuoviJobNonHannoScappatoie(unittest.TestCase):
    """Un job che non puo' far fallire il gate non protegge niente."""

    def setUp(self):
        self.ci = yaml.safe_load(_leggi(CI_YML))
        self.jobs = self.ci["jobs"]

    def test_i_due_job_nuovi_sono_nei_needs_del_gate(self):
        needs = self.jobs["gate"]["needs"]
        for nome in ("full-suite-311", "immagine"):
            self.assertIn(nome, needs,
                          "%s non e' nei needs del gate: il suo rosso non fermerebbe nulla"
                          % nome)

    def test_niente_continue_on_error_ne_pipe_true_nei_job_nuovi(self):
        for nome in ("full-suite-311", "immagine"):
            job = self.jobs[nome]
            self.assertNotIn("continue-on-error", job,
                             "%s ha continue-on-error: il suo rosso sarebbe decorativo" % nome)
            for passo in job.get("steps", []):
                run = str(passo.get("run", ""))
                if "|| true" in run:
                    # ammesso SOLO dove serve a non mascherare l'esito (log e pulizia finale)
                    self.assertTrue("docker logs" in run or "docker rm" in run,
                                    "`|| true` in un passo che decide l'esito di %s: "
                                    "REGOLA FERREA 12" % nome)


if __name__ == "__main__":
    unittest.main()
