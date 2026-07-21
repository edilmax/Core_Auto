"""PROVA ESEGUIBILE — gli archivi sono davvero sorvegliati? Non si chiede: si verifica.

IL PROBLEMA CHE RISOLVE.
`piramide.py` giudicava la copertura CERCANDO IL NOME dentro i test: se la stringa
`DB_CATALOGO` non compariva da nessuna parte, dichiarava l'archivio scoperto. Ma la
guardia vera (`test_db_persistenti.py`) non nomina nessun archivio: **li scorre tutti**
partendo dalla configurazione. E' una copertura piu' forte di quella cercata — e la
piramide la giudicava assente. **Rosso falso.**

Un rosso falso non e' innocuo: insegna a ignorare lo strumento, e il giorno che il rosso
e' vero nessuno lo guarda piu'.

LA SOLUZIONE, che non si puo' falsificare in nessuna delle due direzioni.
Non si cerca una stringa: **si aggiunge un archivio finto alla configurazione e si
pretende che la suite diventi ROSSA.**

  · se diventa rossa → la sorveglianza esiste davvero, ed e' automatica: copre anche
    gli archivi che ancora non esistono, cioe' quelli che verranno aggiunti domani;
  · se resta verde → gli archivi NON sono sorvegliati, per quante volte il loro nome
    compaia nei test.

E' la regola madre applicata allo strumento stesso: nessun verde vale finche' non e'
stato visto rosso. Qui il rosso viene provocato apposta, a ogni esecuzione.
"""
import io
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Il finto archivio: non dichiarato nel compose, non letto da main. Se la sorveglianza
# funziona, la sua sola esistenza deve far cadere la guardia.
INIETTA = r'''
import sys, dataclasses, unittest
sys.path.insert(0, %r)
import fase81_bootstrap_casavip as boot

campo = dataclasses.field(default=":memory:")
campo.name = "db_fantasma"
campo.type = str
boot.ConfigCasaVIP.__dataclass_fields__["db_fantasma"] = campo

import test_db_persistenti as g
ris = unittest.TextTestRunner(verbosity=0).run(
    unittest.defaultTestLoader.loadTestsFromModule(g))
caduti = len(ris.failures) + len(ris.errors)
print("CADUTI=%%d" %% caduti)
''' % REPO


def prova():
    """True se l'archivio fantasma fa cadere la guardia (= sorveglianza viva)."""
    codice = os.path.join(REPO, "_prova_fantasma_tmp.py")
    with io.open(codice, "w", encoding="utf-8", newline="\n") as f:
        f.write(INIETTA)
    try:
        p = subprocess.run([sys.executable, codice], cwd=REPO,
                           capture_output=True, text=True, timeout=300)
        uscita = (p.stdout or "") + (p.stderr or "")
        caduti = 0
        for riga in uscita.splitlines():
            if riga.startswith("CADUTI="):
                caduti = int(riga.split("=")[1])
        return caduti > 0, caduti, uscita
    finally:
        if os.path.exists(codice):
            os.remove(codice)


if __name__ == "__main__":
    print("=" * 88)
    print("PROVA DI COPERTURA DEGLI ARCHIVI — si aggiunge un archivio FINTO alla")
    print("configurazione e si pretende che la suite se ne accorga.")
    print("=" * 88)
    viva, caduti, uscita = prova()
    if viva:
        print("\n  OK  la guardia e' CADUTA su 'db_fantasma' (%d test rossi)." % caduti)
        print("      La sorveglianza degli archivi e' viva e AUTOMATICA: copre anche")
        print("      gli archivi che verranno aggiunti in futuro, senza toccare nulla.")
        sys.exit(0)
    print("\n  X   la guardia e' rimasta VERDE con un archivio mai dichiarato.")
    print("      Gli archivi NON sono sorvegliati: un database nuovo puo' finire in")
    print("      RAM e sparire a ogni deploy, in silenzio.")
    print(uscita[-1500:])
    sys.exit(1)
