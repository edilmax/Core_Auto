# -*- coding: utf-8 -*-
"""GUARDIA: la copertura misurata deve restare ONESTA nel tempo.

PERCHE' ESISTE (revisione ostile del 2026-07-29).
`test_pipeline_ci.py` verifica che il .coveragerc *contenga* certe righe
(`branch = True`, `source = .`, qualche voce di omit). Non verifica la cosa che
conta davvero: **che la lista `omit` non escluda codice che gira in produzione**.

Con quella sola guardia, chiunque potrebbe aggiungere domani

    omit =
        fase83_server.py

e la percentuale schizzerebbe in alto senza che un solo test diventi rosso: il
cricchetto (COVERAGE_MIN) resterebbe soddisfatto misurando meno prodotto. Una
soglia su un denominatore che si puo' rimpicciolire di nascosto non e' un gate,
e' un ornamento (modo di rompersi #4: «il controllo che non controlla»).

COSA INCHIODA QUESTO FILE
  1. Nessun modulo RAGGIUNGIBILE dall'avvio di produzione (`main_casavip.py`,
     chiusura degli import locali) puo' stare nella lista `omit`.
  2. Nessun modulo misurato puo' importare o nominare un modulo omesso: e' il
     modo in cui il vecchio stack (fase13-56) tornerebbe vivo restando invisibile
     alla misura.
  3. Ogni modulo della chiusura di produzione deve essere fra i file che il
     `Dockerfile.casavip` copia dentro l'immagine (altrimenti l'immagine e' rotta
     e la misura misura una cosa diversa da cio' che gira).
  4. Il denominatore non puo' rimpicciolirsi: il numero di moduli di prodotto
     misurati ha un pavimento.

VISTO ROSSO (obbligatorio, regola aurea del progetto): la classe
`TestIlControlloSaFallire` avvelena la configurazione VERA e una cartella finta,
e pretende che il controllo se ne accorga. Se un domani il controllo diventasse
cieco, sono quei test a cadere per primi.
"""

from __future__ import annotations

import ast
import fnmatch
import io
import os
import re
import shutil
import tempfile
import unittest

RADICE = os.path.dirname(os.path.abspath(__file__))
COVERAGERC = os.path.join(RADICE, ".coveragerc")
DOCKERFILE = os.path.join(RADICE, "Dockerfile.casavip")
AVVIO = "main_casavip"

# I motori che NON possono sparire dalla misura: se uno di questi non risulta
# piu' raggiungibile, non e' l'omit ad essere cambiato — e' il prodotto, e va
# guardato subito.
MOTORI_IRRINUNCIABILI = (
    "fase83_server",
    "fase81_bootstrap_casavip",
    "fase85_pagamenti_stripe",
    "fase98_policy_commissione",
    "fase101_stripe_connect",
    "fase111_cancellazione",
    "fase177_financial_controller",
    "fase186_guardiano",
    "fase188_paga_struttura",
)

# Pavimento del denominatore: oggi i moduli di prodotto misurati sono 114
# (114 fase*.py + main_casavip.py meno i 38 del vecchio stack). Si tiene un
# margine di 4 per la normale potatura, non di piu': serve ad accorgersi di un
# omit che si allarga, non a lasciarlo allargare.
PAVIMENTO_MODULI_MISURATI = 110


# ---------------------------------------------------------------------------
#  Lettura della configurazione e dell'immagine
# ---------------------------------------------------------------------------
def leggi_omit(percorso_coveragerc):
    """Le voci della lista `omit` del .coveragerc, in ordine di file."""
    with io.open(percorso_coveragerc, encoding="utf-8") as f:
        righe = f.read().splitlines()
    voci = []
    dentro = False
    for riga in righe:
        nuda = riga.strip()
        if not nuda or nuda.startswith("#"):
            continue
        if re.match(r"^omit\s*=", nuda):
            dentro = True
            resto = nuda.split("=", 1)[1].strip()
            if resto:
                voci.append(resto)
            continue
        if dentro:
            # una voce della lista e' indentata; qualsiasi altra cosa la chiude
            if riga[:1] in (" ", "\t") and "=" not in nuda and not nuda.startswith("["):
                voci.append(nuda)
            else:
                dentro = False
    return voci


def e_omesso(nome_file, modelli):
    """Il file (percorso relativo alla radice) cade in uno dei modelli di omit?"""
    nome_file = nome_file.replace("\\", "/")
    for m in modelli:
        m = m.replace("\\", "/")
        if fnmatch.fnmatch(nome_file, m) or fnmatch.fnmatch(nome_file, "*/" + m):
            return True
    return False


def copiati_dal_dockerfile(percorso_dockerfile):
    """I modelli di file che l'immagine di produzione copia dentro se stessa."""
    with io.open(percorso_dockerfile, encoding="utf-8") as f:
        testo = f.read()
    modelli = []
    for riga in testo.splitlines():
        nuda = riga.strip()
        if nuda.upper().startswith("COPY "):
            pezzi = nuda.split()[1:]
            if len(pezzi) >= 2:
                modelli.extend(pezzi[:-1])
    return modelli


# ---------------------------------------------------------------------------
#  Grafo degli import (statico, senza importare nulla)
# ---------------------------------------------------------------------------
def moduli_locali(cartella):
    return set(
        os.path.splitext(n)[0]
        for n in os.listdir(cartella)
        if n.endswith(".py") and os.path.isfile(os.path.join(cartella, n))
    )


def import_diretti(cartella, modulo, locali):
    percorso = os.path.join(cartella, modulo + ".py")
    if not os.path.isfile(percorso):
        return set()
    with io.open(percorso, encoding="utf-8") as f:
        sorgente = f.read()
    try:
        albero = ast.parse(sorgente)
    except SyntaxError:
        return set()
    trovati = set()
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                base = alias.name.split(".")[0]
                if base in locali:
                    trovati.add(base)
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.level == 0 and nodo.module:
                base = nodo.module.split(".")[0]
                if base in locali:
                    trovati.add(base)
    return trovati


def chiusura_di_produzione(cartella, avvio=AVVIO):
    """Tutti i moduli locali raggiungibili dall'avvio, import dopo import."""
    locali = moduli_locali(cartella)
    visti = set()
    da_fare = [avvio]
    while da_fare:
        modulo = da_fare.pop()
        if modulo in visti:
            continue
        visti.add(modulo)
        da_fare.extend(import_diretti(cartella, modulo, locali) - visti)
    return visti


# ---------------------------------------------------------------------------
#  I TRE CONTROLLI (funzioni pure: si possono avvelenare in una cartella finta)
# ---------------------------------------------------------------------------
def produzione_esclusa_dalla_misura(cartella, modelli_omit, avvio=AVVIO):
    """Moduli che GIRANO in produzione e che la misura NON conta. Deve essere []."""
    return sorted(
        m for m in chiusura_di_produzione(cartella, avvio)
        if e_omesso(m + ".py", modelli_omit)
    )


def legacy_risvegliato(cartella, modelli_omit, avvio=AVVIO):
    """Moduli MISURATI che citano un modulo OMESSO: {omesso: [chi lo cita]}.

    Non basta guardare gli `import`: un `import_module("fase43_commissione")` o
    una tabella di nomi in chiaro riaccenderebbero il vecchio stack lasciandolo
    fuori dalla misura. Qui si cerca il nome del modulo in qualunque forma.
    """
    tutti = sorted(n for n in os.listdir(cartella) if n.endswith(".py"))
    # Si guardano SOLO i moduli-fase esclusi (il vecchio stack): sono gli unici
    # con un nome abbastanza distintivo da cercare per intero senza falsi
    # allarmi. `app.py` e i `test_*.py` restano fuori da questo controllo — la
    # parola "app" compare ovunque e li' un riscontro non vorrebbe dire nulla.
    omessi = [os.path.splitext(n)[0] for n in tutti
              if e_omesso(n, modelli_omit) and re.match(r"^fase\d+_", n)]
    # E si guardano solo i file che sono PRODOTTO (fase*.py + l'avvio): gli
    # script d'officina in radice non finiscono nell'immagine.
    misurati = [n for n in tutti
                if not e_omesso(n, modelli_omit)
                and (n.startswith("fase") or n == AVVIO + ".py")]
    guai = {}
    for nome in misurati:
        with io.open(os.path.join(cartella, nome), encoding="utf-8") as f:
            testo = f.read()
        for morto in omessi:
            if re.search(r"\b%s\b" % re.escape(morto), testo):
                guai.setdefault(morto, []).append(nome)
    return guai


def moduli_misurati(cartella, modelli_omit):
    return sorted(
        n for n in os.listdir(cartella)
        if n.endswith(".py") and not e_omesso(n, modelli_omit)
    )


# ===========================================================================
#  1. LA MISURA CONTA TUTTO IL PRODOTTO VIVO
# ===========================================================================
class TestNienteProduzioneFuoriDallaMisura(unittest.TestCase):

    def setUp(self):
        self.omit = leggi_omit(COVERAGERC)
        self.chiusura = chiusura_di_produzione(RADICE)

    def test_l_omit_e_stato_letto_davvero(self):
        """Se la lettura dell'omit tornasse vuota, tutti i test qui sotto
        sarebbero verdi per costruzione: e' la prima cosa da inchiodare."""
        self.assertGreaterEqual(len(self.omit), 8, self.omit)
        for atteso in ("test_*.py", "collaudi/*", "_archivio/*", "app.py"):
            self.assertIn(atteso, self.omit)

    def test_la_chiusura_di_produzione_non_e_un_insieme_vuoto(self):
        self.assertGreaterEqual(
            len(self.chiusura), 80,
            "la chiusura degli import da main_casavip.py e' crollata a %d moduli: "
            "o il prodotto e' cambiato o questo controllo si e' rotto — in "
            "entrambi i casi NON e' un verde da accettare" % len(self.chiusura))
        for motore in MOTORI_IRRINUNCIABILI:
            self.assertIn(
                motore, self.chiusura,
                "%s non risulta piu' raggiungibile dall'avvio: la guardia sulla "
                "copertura starebbe controllando un prodotto che non esiste" % motore)

    def test_nessun_modulo_di_produzione_e_escluso_dalla_misura(self):
        """IL CUORE. Un modulo che gira in produzione ma non entra nella misura
        rende la percentuale una bugia: si alza togliendo prodotto, non
        aggiungendo prove."""
        fuori = produzione_esclusa_dalla_misura(RADICE, self.omit)
        self.assertEqual(
            fuori, [],
            "questi moduli GIRANO in produzione e sono esclusi dalla misura di "
            "copertura: %s — o si tolgono dall'omit, o la percentuale del "
            "cricchetto non vale nulla" % fuori)

    def test_il_denominatore_non_puo_rimpicciolirsi_di_nascosto(self):
        misurati = moduli_misurati(RADICE, self.omit)
        self.assertGreaterEqual(
            len(misurati), PAVIMENTO_MODULI_MISURATI,
            "i moduli di prodotto misurati sono scesi a %d (pavimento %d): la "
            "soglia COVERAGE_MIN si puo' soddisfare anche restringendo cio' che "
            "si misura, ed e' esattamente cio' che questo pavimento vieta"
            % (len(misurati), PAVIMENTO_MODULI_MISURATI))
        self.assertIn("main_casavip.py", misurati)

    def test_il_vecchio_stack_escluso_e_davvero_morto(self):
        """I 38 moduli fase13-56 stanno fuori dalla misura perche' nessuno li
        chiama. Il giorno in cui uno di essi venisse richiamato, sarebbe codice
        vivo e non misurato: qui diventa rosso."""
        guai = legacy_risvegliato(RADICE, self.omit)
        self.assertEqual(
            guai, {},
            "moduli MISURATI citano moduli ESCLUSI dalla misura: %s — se il "
            "vecchio stack torna in gioco deve tornare anche sotto misura" % guai)

    def test_l_omit_esclude_solo_il_vecchio_stack_e_i_non_prodotto(self):
        """Nessun modulo con numero di fase >= 57 puo' finire nell'omit: da li'
        in poi e' tutto prodotto vivo."""
        for nome in sorted(os.listdir(RADICE)):
            m = re.match(r"^fase(\d+)_.*\.py$", nome)
            if not m:
                continue
            if int(m.group(1)) >= 57:
                self.assertFalse(
                    e_omesso(nome, self.omit),
                    "%s ha numero di fase >= 57 (prodotto vivo) ed e' escluso "
                    "dalla misura" % nome)


# ===========================================================================
#  2. CIO' CHE SI MISURA E' CIO' CHE ENTRA NELL'IMMAGINE
# ===========================================================================
class TestMisuraEImmagineCoincidono(unittest.TestCase):

    def setUp(self):
        self.omit = leggi_omit(COVERAGERC)
        self.copie = copiati_dal_dockerfile(DOCKERFILE)

    def test_il_dockerfile_dichiara_le_copie_che_ci_aspettiamo(self):
        self.assertIn("main_casavip.py", self.copie, self.copie)
        self.assertIn("fase*.py", self.copie, self.copie)

    def test_ogni_modulo_di_produzione_finisce_dentro_l_immagine(self):
        """Un modulo raggiungibile dall'avvio ma non copiato = immagine che non
        parte: la copertura misurerebbe un prodotto che in produzione non c'e'."""
        mancanti = []
        for modulo in sorted(chiusura_di_produzione(RADICE)):
            nome = modulo + ".py"
            if not any(fnmatch.fnmatch(nome, p) for p in self.copie):
                mancanti.append(nome)
        self.assertEqual(
            mancanti, [],
            "il Dockerfile di produzione NON copia questi moduli, che pero' "
            "l'avvio importa: %s" % mancanti)

    def test_il_coveragerc_dice_la_verita_su_cosa_esclude(self):
        """Modo di rompersi #3: un commento che promette una cosa e il codice ne
        fa un'altra. Il .coveragerc NON puo' sostenere che gli esclusi restino
        fuori dall'immagine: `COPY fase*.py` li porta dentro tutti; restano fuori
        dalla misura perche' sono CODICE MORTO, che e' un'altra affermazione."""
        with io.open(COVERAGERC, encoding="utf-8") as f:
            testo = f.read()
        legacy = [n for n in os.listdir(RADICE)
                  if n.endswith(".py") and e_omesso(n, leggi_omit(COVERAGERC))
                  and n.startswith("fase")]
        self.assertTrue(legacy, "nessun modulo legacy trovato: controllo cieco")
        # l'immagine li copia davvero (e' un fatto, non un'opinione)
        self.assertTrue(any(fnmatch.fnmatch(legacy[0], p) for p in self.copie),
                        "il Dockerfile non copia %s: il commento andrebbe "
                        "riletto in senso opposto" % legacy[0])
        self.assertIn("codice morto", testo.lower(),
                      "il .coveragerc deve dichiarare il motivo VERO "
                      "dell'esclusione (codice morto, mai importato), non un "
                      "motivo falso (che non entri nell'immagine: ci entra)")


# ===========================================================================
#  3. VISTO ROSSO — il controllo sa accorgersi del guasto?
# ===========================================================================
class TestIlControlloSaFallire(unittest.TestCase):
    """Ogni controllo qui sopra viene messo davanti al guasto che deve vedere.
    Un controllo che non e' mai fallito non e' una guardia."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="copertura_onesta_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _scrivi(self, nome, testo):
        with io.open(os.path.join(self.tmp, nome), "w", encoding="utf-8") as f:
            f.write(testo)

    def _finto_prodotto(self):
        self._scrivi("main_casavip.py", "import fase90_vivo\n")
        self._scrivi("fase90_vivo.py", "from fase91_vivo import x\n")
        self._scrivi("fase91_vivo.py", "x = 1\n")
        self._scrivi("fase20_morto.py", "y = 2\n")

    # --- 1. produzione esclusa ------------------------------------------------
    def test_vede_un_modulo_vivo_finito_nell_omit(self):
        self._finto_prodotto()
        self.assertEqual(
            produzione_esclusa_dalla_misura(self.tmp, ["fase2?_*.py"]), [],
            "omit onesto: non deve gridare")
        self.assertEqual(
            produzione_esclusa_dalla_misura(self.tmp, ["fase2?_*.py", "fase91_*.py"]),
            ["fase91_vivo"],
            "un modulo raggiungibile e' stato messo nell'omit e il controllo "
            "non se ne e' accorto")

    def test_vede_il_vivo_nascosto_dietro_un_carattere_jolly(self):
        self._finto_prodotto()
        self.assertEqual(
            produzione_esclusa_dalla_misura(self.tmp, ["fase9?_*.py"]),
            ["fase90_vivo", "fase91_vivo"])

    def test_sul_prodotto_VERO_avvelenare_l_omit_col_server_lo_fa_gridare(self):
        """La prova piu' importante: non su una cartella finta, sul repo vero.
        Si aggiunge `fase83_server.py` all'omit (il modulo da ~10.000 righe che
        da solo sposta la percentuale) e il controllo deve vederlo."""
        vero = leggi_omit(COVERAGERC)
        self.assertEqual(produzione_esclusa_dalla_misura(RADICE, vero), [])
        avvelenato = vero + ["fase83_server.py"]
        self.assertIn("fase83_server",
                      produzione_esclusa_dalla_misura(RADICE, avvelenato),
                      "escludendo il server dalla misura il controllo resta "
                      "verde: e' cieco proprio dove serve")

    def test_sul_prodotto_VERO_un_omit_troppo_largo_sfonda_il_pavimento(self):
        vero = leggi_omit(COVERAGERC)
        self.assertGreaterEqual(len(moduli_misurati(RADICE, vero)),
                                PAVIMENTO_MODULI_MISURATI)
        largo = vero + ["fase1??_*.py"]
        self.assertLess(len(moduli_misurati(RADICE, largo)),
                        PAVIMENTO_MODULI_MISURATI,
                        "un omit che cancella tutte le fasi 100-199 non fa "
                        "scattare il pavimento: il pavimento e' un ornamento")

    # --- 2. legacy risvegliato ------------------------------------------------
    def test_vede_il_legacy_richiamato_da_un_modulo_misurato(self):
        self._finto_prodotto()
        self.assertEqual(legacy_risvegliato(self.tmp, ["fase2?_*.py"]), {})
        self._scrivi("fase91_vivo.py", "import fase20_morto\nx = 1\n")
        self.assertEqual(legacy_risvegliato(self.tmp, ["fase2?_*.py"]),
                         {"fase20_morto": ["fase91_vivo.py"]})

    def test_vede_il_legacy_richiamato_per_nome_e_non_con_import(self):
        """`__import__("fase20_morto")` non e' un nodo Import: se il controllo
        guardasse solo l'albero degli import, questo gli sfuggirebbe."""
        self._finto_prodotto()
        self._scrivi("fase91_vivo.py",
                     'm = __import__("fase20_morto")\nx = 1\n')
        self.assertEqual(legacy_risvegliato(self.tmp, ["fase2?_*.py"]),
                         {"fase20_morto": ["fase91_vivo.py"]})

    # --- 3. immagine ----------------------------------------------------------
    def test_vede_l_omit_che_non_si_riesce_nemmeno_a_leggere(self):
        self._scrivi(".coveragerc", "[run]\nbranch = True\nsource = .\n")
        self.assertEqual(leggi_omit(os.path.join(self.tmp, ".coveragerc")), [])
        self._scrivi(".coveragerc",
                     "[run]\nbranch = True\nomit =\n    a.py\n    b/*\n"
                     "\n[report]\nprecision = 1\n")
        self.assertEqual(leggi_omit(os.path.join(self.tmp, ".coveragerc")),
                         ["a.py", "b/*"])

    def test_vede_il_dockerfile_che_smette_di_copiare_i_moduli(self):
        self._scrivi("Dockerfile.x", "FROM python\nCOPY main_casavip.py ./\n")
        copie = copiati_dal_dockerfile(os.path.join(self.tmp, "Dockerfile.x"))
        self.assertEqual(copie, ["main_casavip.py"])
        self.assertFalse(any(fnmatch.fnmatch("fase83_server.py", p) for p in copie),
                         "il lettore del Dockerfile inventa copie che non ci sono")


if __name__ == "__main__":
    unittest.main()
