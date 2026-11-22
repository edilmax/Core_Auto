"""L'ESAME DELLA CASELLA «MYPY CONTROLLA I TIPI DEI MODULI CHE MUOVONO SOLDI» — blocco SOLDI.

    python collaudi/esame_mypy.py               misura e MOSTRA, senza scrivere (cosi' gira in CI)
    python collaudi/esame_mypy.py --scrivi      misura e SCRIVE la casella (anche falsa)
    python collaudi/esame_mypy.py --autoprova   si vede gridare e tacere (D18 punto 2)

⛔ IL TESTO DELLA CASELLA NON SI RICOPIA: si cerca in `piano.py` per contenuto e deve comparire
   UNA volta sola; se sparisce o si sdoppia, l'esame si ferma.

COME MISURA. La casella chiede due cose, e le misura tutte e due:
  1. ZERO errori di mypy sugli otto moduli che muovono soldi (MODULI qui sotto), con le viti
     strette (OPZIONI) e alla versione di Python della produzione (3.11, quella del Dockerfile);
  2. che in CI questo controllo BLOCCHI: il job `qualita` (uno di quelli che il `gate` aspetta)
     esegue proprio QUESTO esame, senza `|| true` e senza `continue-on-error`. La CI non
     ricopia l'elenco dei file: lo legge da qui, cosi' le due liste non possono divergere.

Nato il 2026-11-22 (mappa del fondatore del 15/11). Prima mypy girava su 3 file con `|| true`:
non bloccava niente. Misurato quel giorno sugli otto moduli: 29 errori in 5 file, NESSUNO un
difetto vivo -- ogni valore era gia' controllato prima dell'uso, mypy non seguiva il
ragionamento (una verifica salvata in una variabile, un corpo vuoto che vale GET, una
connessione condivisa che fa le veci di quella di sqlite). Corretti con annotazioni, `cast` e
un `assert`, senza cambiare cosa fa il codice.

⛔ D18: precondizioni che fermano il giro, autoprova nelle due direzioni su file costruiti
   apposta, NON_GUARDA stampato a ogni giro, e la guardia
   `TestLEsameMypyNonPuoBARARE` in test_pipeline_ci.py.
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
for _p in (RADICE, QUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from piano import BLOCCHI  # noqa: E402
import scheda  # noqa: E402

BLOCCO_SOLDI = 1
SEGNALE = "mypy controlla i tipi dei moduli che muovono soldi"
COMANDO = "python collaudi/esame_mypy.py --scrivi"
CI = os.path.join(RADICE, ".github", "workflows", "ci.yml")
JOB_CI = "qualita"
PASSO_CI = "python collaudi/esame_mypy.py"
PYTHON_PRODUZIONE = "3.11"
# I cinque del percorso del denaro (piano.py, `moduli_mutazione` del blocco 1) e i tre motori
# nominati dalla casella: commissione, cancellazione, paga in struttura.
MODULI = (
    "fase65_split_payment.py", "fase85_pagamenti_stripe.py", "fase87_stripe_webhook.py",
    "fase101_stripe_connect.py", "fase131_payout_dashboard.py",
    "fase98_policy_commissione.py", "fase111_cancellazione.py", "fase188_paga_struttura.py",
)
# Le viti strette del vecchio passo «Mypy severo sui motori-soldi» di lint-severo, piu'
# --follow-imports=silent: i moduli importati si leggono per capire i tipi ma i LORO errori
# non si contano (la casella parla di questi otto, non di tutto il prodotto).
OPZIONI = (
    "--python-version", PYTHON_PRODUZIONE, "--ignore-missing-imports", "--warn-redundant-casts",
    "--warn-unused-ignores", "--no-implicit-optional", "--check-untyped-defs",
    "--follow-imports=silent", "--no-error-summary", "--show-error-codes",
)
NON_GUARDA = (
    "solo gli otto moduli di MODULI: gli altri moduli dei soldi (fase177, fase186, fase204, ...) "
    "non sono contati, i loro errori di tipo restano fuori da questa casella",
    "mypy controlla solo cio' che e' annotato o deducibile: una funzione che riceve `Any` (gli "
    "ingressi validati a mano) non viene verificata sul tipo, ma sul controllo scritto dentro",
    "`--ignore-missing-imports`: le librerie senza tipi (nessuna oggi fra gli import degli otto, "
    "tutte stdlib) sarebbero trattate come `Any`",
    "non dimostra che il codice e' giusto: dimostra che i tipi dichiarati sono coerenti fra "
    "loro. Un importo sbagliato ma intero passa",
)

# La lettera del disco («C:\...») su Windows: senza, un percorso assoluto non si riconosce e
# l'errore sparisce dal conto (visto il 22/11: l'autoprova sul file temporaneo non gridava).
_RIGA_ERRORE = re.compile(
    r"^(?P<file>(?:[A-Za-z]:)?[^:\r\n]+\.py):(?P<riga>\d+): error: (?P<msg>.*)$")


def testo_casella():
    """Il testo della casella DAL PIANO, cercato per contenuto e preteso UNICO."""
    condizioni = BLOCCHI[BLOCCO_SOLDI - 1]["finito_quando"]
    trovate = [" ".join(str(c).split()) for c in condizioni if SEGNALE in " ".join(str(c).split())]
    if len(trovate) != 1:
        raise ValueError("nel blocco %d le caselle che nominano %r sono %d, non 1: il piano e' "
                         "cambiato e questo esame non sa piu' a cosa punta"
                         % (BLOCCO_SOLDI, SEGNALE, len(trovate)))
    return trovate[0]


def passo_ci_bloccante(testo_ci):
    """(ok, dettaglio): il job JOB_CI esegue PASSO_CI ESATTAMENTE, e niente ne spegne l'esito.

    ⛔ Si legge il YAML com'e' (PyYAML, `safe_load`), non per sottostringhe. Il primo controllo
    del 22/11 cercava il testo del comando e `|| true`: il cacciatore di errori silenziosi ha
    trovato cinque modi di spegnere il passo che passavano -- `--autoprova` (prova solo se
    stesso ed esce 0 senza misurare), `; true`, `if: false` sul passo o sul job,
    `continue-on-error: 'true'` tra virgolette. Ora: il job non ha `if` ne'
    `continue-on-error`; UN solo passo nomina l'esame, e il suo `run` e' il comando esatto,
    senza argomenti; il passo non ha `if`, `continue-on-error`, `shell`, `working-directory`;
    il gate lo aspetta."""
    try:
        import yaml
    except Exception as e:
        return False, "PyYAML non si importa: il file della CI non si puo' leggere (%s)" % e
    try:
        doc = yaml.safe_load(testo_ci)
    except Exception as e:
        return False, "ci.yml illeggibile come YAML: %s" % e
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, dict) or not isinstance(jobs.get(JOB_CI), dict):
        return False, "il job %r non c'e' in ci.yml" % JOB_CI
    job = jobs[JOB_CI]
    for chiave in ("if", "continue-on-error"):
        if chiave in job:
            return False, "il job %r ha %r: %r" % (JOB_CI, chiave, job[chiave])
    passi = [s for s in (job.get("steps") or [])
             if isinstance(s, dict) and PASSO_CI in str(s.get("run", ""))]
    if len(passi) != 1:
        return False, "il job %r esegue %r %d volte, non una" % (JOB_CI, PASSO_CI, len(passi))
    passo = passi[0]
    comando = str(passo.get("run", "")).strip()
    if comando != PASSO_CI:
        return False, "il comando del passo dev'essere esattamente %r, e' %r" % (PASSO_CI, comando)
    for chiave in ("if", "continue-on-error", "shell", "working-directory"):
        if chiave in passo:
            return False, "il passo ha %r: %r" % (chiave, passo[chiave])
    gate = jobs.get("gate")
    needs = gate.get("needs") if isinstance(gate, dict) else None
    if isinstance(needs, str):
        needs = [needs]
    if not isinstance(needs, list) or JOB_CI not in needs:
        return False, "il job %r non e' fra quelli che il gate aspetta" % JOB_CI
    return True, "%s esegue %r, bloccante, aspettato dal gate" % (JOB_CI, PASSO_CI)


def esegui_mypy(file):
    """(codice_uscita, errori, uscita_grezza) di mypy sui file dati, nella cartella principale."""
    proc = subprocess.run([sys.executable, "-m", "mypy"] + list(OPZIONI) + list(file),
                          cwd=RADICE, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    uscita = (proc.stdout or "") + (proc.stderr or "")
    errori = []
    for r in uscita.splitlines():
        m = _RIGA_ERRORE.match(r.strip())
        if m:
            errori.append((os.path.basename(m.group("file")), int(m.group("riga")), m.group("msg")))
    return proc.returncode, errori, uscita


def precondizioni():
    """(tutte_ok, righe). Un metro storto va scoperto dal metro (D18 punto 1)."""
    righe = []
    try:
        testo_casella()
        righe.append(("la casella si legge dal piano, una volta sola", True, SEGNALE))
    except Exception as e:
        righe.append(("la casella si legge dal piano, una volta sola", False, str(e)))
    mancanti = [m for m in MODULI if not os.path.isfile(os.path.join(RADICE, m))]
    righe.append(("gli otto moduli esistono", not mancanti and len(MODULI) == 8,
                  "mancano: %s" % mancanti if mancanti else "%d file" % len(MODULI)))
    try:
        proc = subprocess.run([sys.executable, "-m", "mypy", "--version"], capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        versione = (proc.stdout or proc.stderr or "").strip()
        righe.append(("mypy si esegue", proc.returncode == 0 and versione.startswith("mypy "),
                      versione or "nessuna uscita"))
    except Exception as e:
        righe.append(("mypy si esegue", False, str(e)))
    try:
        with io.open(CI, encoding="utf-8") as f:
            ok, dettaglio = passo_ci_bloccante(f.read())
    except Exception as e:
        ok, dettaglio = False, str(e)
    righe.append(("in CI il controllo BLOCCA", ok, dettaglio))
    return all(ok for _, ok, _ in righe), righe


def misura():
    codice, errori, uscita = esegui_mypy(MODULI)
    # S7: mypy che esce 2 (opzione sbagliata, file illeggibile) non ha guardato niente: non e'
    # «zero errori». Uscita 0 senza errori = verde; uscita 1 con errori = rosso; il resto e'
    # una misura non valida e diventa rossa col suo testo.
    if codice == 0 and not errori:
        return True, len(MODULI), "", errori
    if codice == 1 and errori:
        per_file = {}
        for f, _ln, _msg in errori:
            per_file[f] = per_file.get(f, 0) + 1
        motivo = "%d errori di mypy: %s" % (len(errori), ", ".join(
            "%s %d" % (f, n) for f, n in sorted(per_file.items())))
        return False, len(MODULI), motivo, errori
    return False, len(MODULI), "misura non valida: mypy uscito %s con %d errori riconosciuti: %s" % (
        codice, len(errori), " ".join(uscita.split())[:200]), errori


def autoprova():
    """D18 punto 2: su un file costruito apposta (un importo che puo' essere None usato in un
    conto) mypy deve GRIDARE; sulla sua versione corretta deve TACERE."""
    cartella = tempfile.mkdtemp(prefix="esame_mypy_")
    try:
        guasto = os.path.join(cartella, "soldi_col_guasto.py")
        sano = os.path.join(cartella, "soldi_sani.py")
        with io.open(guasto, "w", encoding="utf-8") as f:
            f.write("from typing import Optional\n"
                    "def totale(importo_cents: Optional[int]) -> int:\n"
                    "    return importo_cents + 25\n")
        with io.open(sano, "w", encoding="utf-8") as f:
            f.write("from typing import Optional\n"
                    "def totale(importo_cents: Optional[int]) -> int:\n"
                    "    if importo_cents is None:\n"
                    "        return 0\n"
                    "    return importo_cents + 25\n")
        cg, eg, _ = esegui_mypy([guasto])
        cs, es, _ = esegui_mypy([sano])
        return (cg == 1 and len(eg) == 1), (cs == 0 and not es)
    finally:
        shutil.rmtree(cartella, ignore_errors=True)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    tutte_ok, righe = precondizioni()
    print("=" * 86)
    print("🔤 ESAME MYPY — «i tipi dei moduli che muovono soldi, e la CI blocca» (blocco SOLDI)")
    print("=" * 86)
    for nome, ok, dettaglio in righe:
        print("  %-6s %s  %s" % ("OK" if ok else "ROSSO", nome, dettaglio))
    if "--autoprova" in argv:
        grida, tace = autoprova()
        print("  AUTOPROVA: grida col guasto=%s · tace a macchina sana=%s" % (grida, tace))
        return 0 if (grida and tace) else 1
    if not all(ok for nome, ok, _ in righe if nome != "in CI il controllo BLOCCA"):
        print("VERDETTO: ⛔ NON ESEGUIBILE — le precondizioni non reggono (S7): niente "
              "scritture, niente numeri")
        return 2
    # D18 punto 1, a OGNI giro (anche in CI, dove questo esame e' l'unico posto con mypy):
    # un mypy che non grida su un importo Optional usato in un conto darebbe «zero errori»
    # senza aver guardato niente.
    grida, tace = autoprova()
    print("  %-6s il metro si prova da solo  grida col guasto=%s · tace a macchina sana=%s"
          % ("OK" if (grida and tace) else "ROSSO", grida, tace))
    if not (grida and tace):
        print("VERDETTO: ⛔ NON ESEGUIBILE — l'autoprova non regge: niente scritture, niente "
              "numeri")
        return 2
    esito, denominatore, motivo, errori = misura()
    ci_ok = tutte_ok
    if not ci_ok:
        esito = False
        motivo = "; ".join(x for x in (motivo, "in CI il controllo NON blocca: " + [
            d for n, ok, d in righe if n == "in CI il controllo BLOCCA"][0]) if x)
    for f, ln, msg in errori:
        print("  ERRORE %s:%s  %s" % (f, ln, msg[:110]))
    print("  casella %s  (denominatore %d moduli)%s"
          % ("☑" if esito else "☐", denominatore,
             ("\n     perche': %s" % motivo) if motivo else ""))
    print("  ⛔ COSA NON GUARDA:")
    for r in NON_GUARDA:
        print("     · %s" % r)
    if "--scrivi" in argv:
        scheda.registra(testo_casella(), esito=esito, denominatore=denominatore,
                        comando=COMANDO, ordine=BLOCCO_SOLDI, motivo=motivo or None)
        print("  🗂️  casella scritta%s" % ("" if esito else " (falsa, col motivo)"))
    print("VERDETTO: %s — %d errori di mypy su %d moduli, CI %s"
          % ("✅" if esito else "⛔", len(errori), denominatore,
             "bloccante" if ci_ok else "NON bloccante"))
    return 0 if esito else 1


if __name__ == "__main__":
    sys.exit(main())
