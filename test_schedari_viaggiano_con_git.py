# -*- coding: utf-8 -*-
"""UNO SCHEDARIO CHE GIT NON VEDE E' UNA MEMORIA CHE SI CANCELLA A OGNI SESSIONE.

⛔ IL DIFETTO VERO, MISURATO IL 2026-09-03 SU `463384a` (master pulito):

    $ python collaudi/scheda.py --blocco 1
      righe nella scheda: 0        ->  0 su 6
    $ python collaudi/esame_soldi.py --scrivi
      scritta: blocco 1 · esito True · denominatore 54 · impronta 4218eaec4034
      scritta: blocco 1 · esito True · denominatore 15 · impronta 4218eaec4034
    $ python collaudi/scheda.py --blocco 1
      righe nella scheda: 2        ->  2 su 6
    $ git status --porcelain
      (NIENTE)
    $ git add --dry-run collaudi/scheda.json
      The following paths are ignored by one of your .gitignore files:
      collaudi/scheda.json

Cioe': l'attrezzo misura davvero, spunta davvero, e **il risultato non puo' uscire da quel
computer**. `.gitignore` riga 25 dice `*.json` e si prende anche `collaudi/scheda.json`.
Conseguenza: il commit `85aea8b` («Le prime due caselle del blocco soldi, spuntate da una
macchina e non da una persona») dichiara «da 0 su 6 a 2 su 6», ma su master quelle due
caselle non ci sono -- e non ci sono mai state: `git log --all -- collaudi/scheda.json` e'
**vuoto in tutta la storia del progetto**. La scheda risponde 0 su 6 a chiunque la apra,
per sempre, qualunque lavoro sia stato fatto.

⛔ E' ESATTAMENTE LO SBAGLIO S13, la seconda volta. La prima fu `bombe_a_tempo.json`, e la
cura fu l'eccezione `!collaudi/bombe_a_tempo.json` scritta in `.gitignore` il 2026-08-13
con questa motivazione: «lo schedario DEVE viaggiare col progetto, se no in CI (e su
qualunque altro computer) il controllo non trova niente da leggere e risponde NON ESEGUITO
-- cioe' smette di proteggere restando silenzioso». Identica situazione, identico danno.
Quella cura pero' non ha lasciato NESSUNA guardia: e' stata una riparazione puntuale su un
file, non un criterio -- percio' il difetto e' potuto tornare su un file nuovo senza che
nessuno se ne accorgesse. Questo file e' il criterio che mancava.

🔑 PERCHE' IL CRITERIO NON NOMINA I FILE. Un elenco scritto a mano avrebbe protetto i due
schedari di oggi e non il terzo di domani -- cioe' avrebbe ricreato lo stesso buco con
l'aria di averlo chiuso. Qui gli schedari si **derivano dall'albero sintattico** dei moduli
di `collaudi/`: uno schedario e' una costante di modulo costruita con `os.path.join(...)`
su un nome che finisce in `.json`. Questo criterio non sa quanti sono ne' come si chiamano,
e domani ne trovera' uno che oggi non esiste.

⚠️ COSA QUESTO FILE NON FA (D18 punto 3):
  · non dice che il CONTENUTO dello schedario sia giusto: dice che puo' viaggiare;
  · non guarda gli schedari fuori dal repository (`/root/...` sul VPS): quelli non sono
    file del progetto e git non c'entra;
  · non guarda i file `.json` che nessun modulo dichiara come proprio schedario.
"""

from __future__ import unicode_literals

import ast
import io
import os
import subprocess
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
CARTELLA_COLLAUDI = os.path.join(QUI, "collaudi")


# ----------------------------------------------------------------------------------
#  LA DERIVAZIONE — chi e' uno "schedario"
# ----------------------------------------------------------------------------------

def schedari_di_una_sorgente(testo, nome_file="(memoria)"):
    """I nomi di file `.json` che QUESTA sorgente dichiara come propri schedari.

    Uno schedario e':
      · una assegnazione **di modulo** (non dentro una funzione: li' e' un dettaglio
        interno, non un file del progetto),
      · il cui valore e' una chiamata a `os.path.join(...)` -- cioe' un percorso
        **costruito dentro il repository**, non una stringa assoluta scritta a mano,
      · con un argomento costante che finisce in `.json` **e ha un nome davanti**.

    ⛔ Le tre condizioni servono tutte e tre, e ognuna esclude un falso allarme vero,
    misurato su questo repository il 2026-09-03:
      · senza «assegnazione di modulo» entrerebbero i percorsi temporanei costruiti
        dentro le funzioni;
      · senza «os.path.join» entrerebbero `STATO = "/root/drip_facebook.json"` di
        `drip_facebook.py` e `giro_video.py`, che sono file sul VPS: pretendere che git
        li porti sarebbe un allarme che non si puo' spegnere (regola ferrea 10);
      · senza «ha un nome davanti» entrerebbe la stringa `".json"` dentro le tuple
        `ESTENSIONI` e `TESTUALI`, che sono elenchi di estensioni e non file.
    """
    try:
        albero = ast.parse(testo, nome_file)
    except SyntaxError:
        return []
    trovati = []
    for nodo in albero.body:                       # SOLO il livello del modulo
        if not isinstance(nodo, ast.Assign):
            continue
        if not any(isinstance(b, ast.Name) for b in nodo.targets):
            continue
        for pezzo in ast.walk(nodo):
            if not isinstance(pezzo, ast.Call):
                continue
            f = pezzo.func
            if not (isinstance(f, ast.Attribute) and f.attr == "join"):
                continue
            for arg in pezzo.args:
                valore = getattr(arg, "value", None) if isinstance(arg, ast.Constant) else None
                if not isinstance(valore, str):
                    continue
                if valore.lower().endswith(".json") and len(valore) > len(".json"):
                    trovati.append(valore)
    return sorted(set(trovati))


def schedari_dichiarati(cartella=CARTELLA_COLLAUDI):
    """(schedari, quanti_moduli_letti). Il secondo numero E' IL DENOMINATORE: senza,
    «nessuno schedario e' ignorato» potrebbe voler dire «non ho guardato niente»."""
    schedari = {}
    letti = 0
    for nome in sorted(os.listdir(cartella)):
        if not nome.endswith(".py"):
            continue
        percorso = os.path.join(cartella, nome)
        try:
            with io.open(percorso, encoding="utf-8") as f:
                testo = f.read()
        except OSError:
            continue
        letti += 1
        for json_nome in schedari_di_una_sorgente(testo, nome):
            schedari.setdefault(os.path.join("collaudi", json_nome).replace("\\", "/"), nome)
    return schedari, letti


# ----------------------------------------------------------------------------------
#  LA DOMANDA A GIT
# ----------------------------------------------------------------------------------

def _git(*argomenti):
    """(codice_uscita, uscita). `None` SOLO se il comando `git` non esiste proprio."""
    try:
        esito = subprocess.run(["git"] + list(argomenti), cwd=QUI,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=30)
    except OSError:
        return None
    return (esito.returncode, esito.stdout.decode("utf-8", "replace"))


def puo_viaggiare(percorso_relativo):
    """Questo file puo' finire in un commit? `None` se git non c'e'.

    Due strade, e ne basta una: o e' gia' **tracciato** (allora viaggia comunque, anche se
    una riga di `.gitignore` lo nomina), oppure **non e' ignorato** (allora un `git add` lo
    prende). Chiedere una sola delle due direbbe il falso in un caso vero.
    """
    tracciato = _git("ls-files", "--error-unmatch", percorso_relativo)
    if tracciato is None:
        return None
    if tracciato[0] == 0:
        return True
    ignorato = _git("check-ignore", "-q", percorso_relativo)
    if ignorato is None:
        return None
    return ignorato[0] != 0


def eccezione_esplicita_nel_gitignore(percorso_relativo, testo_gitignore):
    """IL RIPIEGO DEBOLE: `.gitignore` contiene una riga `!<percorso>` per questo file?

    ⛔ NON e' una prova, ed e' scritto qui perche' non venga scambiato per tale: e'
    esattamente il ragionamento che lo sbaglio S13 vieta («leggere il `.gitignore` e
    concludere»), perche' non sa niente dell'ordine delle righe ne' di una regola piu' larga
    scritta piu' sotto. Serve a UNA cosa sola: quando `git` non risponde, questa guardia
    deve dire qualcosa invece di **sparire**.

    Un `skipTest` qui sarebbe il difetto che questa guardia combatte, un piano piu' su: il
    controllo si assolve da solo, esce dal rapporto come «saltato» e nessuno lo legge piu'.
    Meglio un'asserzione debole che si vede, di una forte che non c'e'.
    """
    atteso = "!" + percorso_relativo.replace("\\", "/")
    for riga in testo_gitignore.splitlines():
        if riga.strip() == atteso:
            return True
    return False


class TestGliSchedariViaggianoConIlProgetto(unittest.TestCase):
    """LA GUARDIA CHE MANCAVA QUANDO S13 E' TORNATO."""

    def test_IL_CRITERIO_NON_E_CIECO(self):
        """PRIMA di credere a un verde: l'attrezzo ha guardato qualcosa?

        Una guardia che deriva il proprio bersaglio puo' fallire in silenzio -- se la
        derivazione smette di trovare, dice «tutto a posto» su un insieme vuoto (sbaglio
        S7: denominatore zero non e' un giudizio)."""
        schedari, letti = schedari_dichiarati()
        self.assertGreater(letti, 0, "non ho letto NESSUN modulo in collaudi/: il "
                                     "denominatore e' zero e l'esito non vale niente")
        self.assertTrue(schedari, "la derivazione non trova piu' NESSUNO schedario fra "
                                  "%d moduli letti: il criterio si e' rotto, e da rotto "
                                  "direbbe sempre di si'" % letti)

    def test_OGNI_SCHEDARIO_DICHIARATO_PUO_VIAGGIARE_CON_GIT(self):
        """IL CUORE. Uno schedario che git non porta e' una memoria che si azzera.

        Non «`.gitignore` contiene la riga giusta», ma «questo file finirebbe in un
        commit»: cosi' la guardia sopravvive a una riscrittura di `.gitignore` e non si
        accontenta della forma.

        ⛔ E NON SI SALTA MAI, nemmeno senza `git`. La prima versione di questa guardia
        faceva `skipTest` quando git non rispondeva, e l'ha bocciata il controllo 3 del
        pre-volo: un test che si assolve da solo esce dal rapporto come «saltato» e nessuno
        lo rilegge -- cioe' **la guardia contro le memorie che spariscono, sparita in
        silenzio**. Senza git si asserisce la cosa piu' debole che si puo' ancora
        asserire (l'eccezione esplicita in `.gitignore`), dicendo a chiare lettere che e'
        il ripiego."""
        schedari, letti = schedari_dichiarati()
        git_risponde = _git("rev-parse", "--git-dir") is not None
        if not git_risponde:
            with io.open(os.path.join(QUI, ".gitignore"), encoding="utf-8") as f:
                gitignore = f.read()
        prigionieri = []
        esaminati = 0
        for percorso, modulo in sorted(schedari.items()):
            if git_risponde:
                esito = puo_viaggiare(percorso)
            else:
                esito = eccezione_esplicita_nel_gitignore(percorso, gitignore)
            esaminati += 1
            if not esito:
                prigionieri.append("%s (dichiarato da collaudi/%s)" % (percorso, modulo))
        self.assertGreater(esaminati, 0,
                           "denominatore zero: non ho esaminato nessuno schedario")
        self.assertEqual(
            [], prigionieri,
            "questi schedari NON possono uscire dal computer che li scrive, quindi la "
            "misura che contengono si perde a ogni sessione e chiunque li apra altrove "
            "legge «mai misurato»: %s. E' lo sbaglio S13: una riga di `.gitignore` scritta "
            "mesi prima per tutt'altro motivo esclude un file NUOVO senza dirlo. La cura e' "
            "un'eccezione esplicita `!<percorso>` accanto a quella di "
            "`collaudi/bombe_a_tempo.json`, col motivo scritto di fianco "
            "(denominatore: %d schedari su %d moduli letti · misurato %s)"
            % (", ".join(prigionieri), esaminati, letti,
               "chiedendolo a git" if git_risponde
               else "SENZA git: solo l'eccezione scritta in .gitignore, che e' il "
                    "ripiego debole e non prova l'ordine delle righe"))

    def test_LO_SCHEDARIO_DELLA_SCHEDA_E_FRA_QUELLI_SORVEGLIATI(self):
        """La controprova del bersaglio: se domani `scheda.py` cambiasse il modo di
        dichiarare il suo file, questa guardia continuerebbe a passare **guardando altro**,
        e nessuno se ne accorgerebbe. Qui si pretende che il bersaglio ci sia ancora."""
        schedari, _ = schedari_dichiarati()
        self.assertIn("collaudi/scheda.json", schedari,
                      "la scheda -- il posto dove una macchina scrive se un blocco e' "
                      "finito -- non risulta piu' fra gli schedari sorvegliati: o e' "
                      "cambiata la dichiarazione in collaudi/scheda.py, o si e' rotta la "
                      "derivazione. In tutt'e due i casi questa guardia sta guardando "
                      "un'altra cosa")


class TestIlCriterioMisuraSeStesso(unittest.TestCase):
    """PROVA DEL METODO, NON DELLO STATO.

    Ogni caso qui sotto e' scritto su sorgenti FINTE, passate a mano: cosi' misura il
    criterio e non il repository di oggi, e resta vero anche quando i file veri cambiano.
    Tre dei quattro casi sono falsi allarmi VERI, incontrati costruendo questa guardia."""

    def test_riconosce_uno_schedario_costruito_col_percorso_del_modulo(self):
        testo = 'import os\nQUI = os.path.dirname(__file__)\nSCHEDA = os.path.join(QUI, "scheda.json")\n'
        self.assertEqual(["scheda.json"], schedari_di_una_sorgente(testo))

    def test_riconosce_anche_la_forma_lunga_senza_variabile_intermedia(self):
        """`bombe_a_tempo.py` la scrive cosi': se il criterio vedesse solo la forma corta,
        lascerebbe fuori proprio lo schedario per cui S13 fu scoperto la prima volta."""
        testo = ('import os\nSCHEDARIO = os.path.join(os.path.dirname('
                 'os.path.abspath(__file__)), "bombe_a_tempo.json")\n')
        self.assertEqual(["bombe_a_tempo.json"], schedari_di_una_sorgente(testo))

    def test_NON_pretende_git_su_un_file_che_vive_sul_VPS(self):
        """`STATO = "/root/drip_facebook.json"` e' un file del server, non del progetto.
        Un allarme su quello non si potrebbe spegnere in nessun modo, e un falso allarme
        insegna a ignorare i segnali (regola ferrea 10)."""
        testo = 'STATO = "/root/drip_facebook.json"\n'
        self.assertEqual([], schedari_di_una_sorgente(testo))

    def test_NON_scambia_una_ESTENSIONE_per_un_file(self):
        """`ESTENSIONI = (".py", ".json", ...)` e' un elenco di suffissi. `".json"` finisce
        in `.json` -- e per un criterio scritto con `endswith` e basta sarebbe un file."""
        testo = 'ESTENSIONI = (".py", ".html", ".json", ".yml")\n'
        self.assertEqual([], schedari_di_una_sorgente(testo))

    def test_NON_guarda_dentro_le_funzioni(self):
        """Un percorso costruito dentro una funzione e' un dettaglio di lavoro -- spesso un
        file temporaneo -- e pretendere che git lo porti sarebbe un altro falso allarme."""
        testo = ('import os\ndef salva(d):\n'
                 '    p = os.path.join(d, "temporaneo.json")\n    return p\n')
        self.assertEqual([], schedari_di_una_sorgente(testo))

    def test_il_ripiego_riconosce_l_eccezione_esplicita(self):
        """Il ramo «senza git» dev'essere provato anche dove git c'e': altrimenti sarebbe
        codice difensivo mai eseguito, cioe' indistinguibile da codice morto (D19)."""
        testo = "*.json\n!collaudi/scheda.json\nforensic_logs/\n"
        self.assertTrue(eccezione_esplicita_nel_gitignore("collaudi/scheda.json", testo))

    def test_il_ripiego_NON_si_accontenta_di_una_riga_commentata(self):
        """Le eccezioni di questo `.gitignore` hanno sopra un commento che NOMINA il file.
        Un ripiego che cercasse la stringa direbbe di si' guardando la spiegazione invece
        della riga che agisce -- e' lo sbaglio S6 in miniatura."""
        testo = "*.json\n# qui andrebbe !collaudi/scheda.json, ma non c'e'\n"
        self.assertFalse(eccezione_esplicita_nel_gitignore("collaudi/scheda.json", testo))

    def test_una_sorgente_illeggibile_non_diventa_un_verde(self):
        """Se il file non si analizza, la risposta e' «niente trovato qui» -- e il
        denominatore di `schedari_dichiarati` lo dice comunque. Il vuoto non e' un valore
        (sbaglio S1), percio' il verde vero lo decide `test_IL_CRITERIO_NON_E_CIECO`."""
        self.assertEqual([], schedari_di_una_sorgente("def :::\n"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
