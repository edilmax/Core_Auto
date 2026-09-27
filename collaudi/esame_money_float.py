"""L'ESAME DELLA CASELLA «NESSUN NUMERO CON LA VIRGOLA TOCCA UN PREZZO» — blocco SOLDI.

    python collaudi/esame_money_float.py               misura e MOSTRA, senza scrivere
    python collaudi/esame_money_float.py --scrivi      misura e SCRIVE la casella
                                                       (anche falsa, coi rilievi nel motivo)
    python collaudi/esame_money_float.py --autoprova   si vede gridare e tacere (D18 punto 2)

⛔ IL TESTO DELLA CASELLA NON SI RICOPIA: si cerca in `piano.py` per contenuto («money-float»)
   e deve comparire UNA volta sola; se sparisce o si sdoppia, l'esame si ferma.

COME MISURA. La casella nomina il proprio metro: «l'ispettore statico conta ZERO rilievi
money-float su tutto il codice». Si usa quindi la regola VERA di `ispettore_statico.py`
(la sua `scan_py`, importata, non ricopiata), ma su un perimetro piu' largo del suo:
l'ispettore da solo guarda i `.py` della cartella principale e NON quelli di `deploy/`, che
sono produzione anche loro (gli script del cron: riconciliazione, sweeper). Misurato il
2026-09-27: senza `deploy/` lo zero avrebbe voluto dire «tutto tranne il cron».

⛔ D18: precondizioni che fermano il giro, autoprova nelle due direzioni su file costruiti
   apposta, NON_GUARDA stampato a ogni giro, e la guardia
   `TestLEsameMoneyFloatNonPuoBARARE` in test_pipeline_ci.py.
"""
import glob
import io
import os
import shutil
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
SEGNALE = "money-float"
COMANDO = "python collaudi/esame_money_float.py --scrivi"
CLASSE = "money-float"
NON_GUARDA = (
    "la regola dell'ispettore e' STRETTA: vede una chiamata `float(` su una riga che nomina "
    "un importo, in un file che parla di centesimi/importi. Non vede la divisione `/` che "
    "produce un float, i letterali come 0.1 moltiplicati per un importo, i numeri che "
    "arrivano gia' float da json.loads: lo zero e' lo zero DI QUESTA REGOLA",
    "i file `test_*.py` sono esclusi dalla regola stessa dell'ispettore, e `collaudi/` non "
    "e' nel perimetro: sono attrezzi che misurano, non codice che tocca un prezzo",
    "non distingue il codice raggiungibile dalla produzione da quello spento: conta TUTTO, "
    "come chiede la casella (misurato il 2026-09-27: i rilievi rimasti stavano in moduli "
    "che `collaudi/raggiungibilita.py` da' per non raggiungibili)",
)


def testo_casella():
    """Il testo della casella DAL PIANO, cercato per contenuto e preteso UNICO."""
    condizioni = BLOCCHI[BLOCCO_SOLDI - 1]["finito_quando"]
    trovate = [" ".join(str(c).split()) for c in condizioni if SEGNALE in str(c)]
    if len(trovate) != 1:
        raise ValueError("nel blocco %d le caselle che nominano %r sono %d, non 1: il piano e' "
                         "cambiato e questo esame non sa piu' a cosa punta"
                         % (BLOCCO_SOLDI, SEGNALE, len(trovate)))
    return trovate[0]


def perimetro():
    """I file che la casella chiama «tutto il codice»: i .py della cartella principale
    (tranne l'ispettore stesso, come fa lui) e quelli di deploy/."""
    radice = sorted(f for f in glob.glob(os.path.join(RADICE, "*.py"))
                    if os.path.basename(f) != "ispettore_statico.py")
    return radice + sorted(glob.glob(os.path.join(RADICE, "deploy", "*.py")))


def rilievi(file):
    """Esegue la regola VERA dell'ispettore sui file dati e torna i rilievi money-float."""
    import ispettore_statico as isp
    isp.finding[:] = []
    for f in file:
        isp.scan_py(f)
    trovati = [(f, ln, msg) for _sev, classe, f, ln, msg in isp.finding if classe == CLASSE]
    isp.finding[:] = []
    return trovati


def precondizioni():
    """(tutte_ok, righe). Un metro storto va scoperto dal metro (D18 punto 1)."""
    righe = []
    try:
        testo_casella()
        righe.append(("la casella si legge dal piano, una volta sola", True, SEGNALE))
    except Exception as e:
        righe.append(("la casella si legge dal piano, una volta sola", False, str(e)))
    try:
        import ispettore_statico as isp
        ok = callable(getattr(isp, "scan_py", None)) and isinstance(isp.finding, list)
        righe.append(("la regola dell'ispettore si importa", ok,
                      "ispettore_statico.scan_py" if ok else "scan_py/finding mancanti"))
    except Exception as e:
        righe.append(("la regola dell'ispettore si importa", False, str(e)))
    file = perimetro()
    n_deploy = sum(1 for f in file if os.sep + "deploy" + os.sep in f)
    # S7: un perimetro vuoto darebbe «zero rilievi» senza aver guardato niente.
    righe.append(("il perimetro non e' vuoto", len(file) > 100 and n_deploy > 0,
                  "%d file .py, di cui %d in deploy/" % (len(file), n_deploy)))
    return all(ok for _, ok, _ in righe), righe


def misura():
    file = perimetro()
    trovati = rilievi(file)
    esito = len(trovati) == 0
    motivo = ""
    if not esito:
        motivo = "%d rilievi money-float: %s" % (len(trovati), "; ".join(
            "%s:%s %s" % (os.path.basename(f), ln, msg[:70]) for f, ln, msg in trovati))
    return esito, len(file), motivo, trovati


def autoprova():
    """D18 punto 2: su un file costruito apposta la regola deve GRIDARE, sulla sua
    versione corretta (Decimal) deve TACERE."""
    cartella = tempfile.mkdtemp(prefix="esame_money_float_")
    try:
        guasto = os.path.join(cartella, "soldi_col_guasto.py")
        sano = os.path.join(cartella, "soldi_sani.py")
        with io.open(guasto, "w", encoding="utf-8") as f:
            f.write("def totale(riga):\n"
                    "    importo_cents = float(riga['importo'])\n"
                    "    return importo_cents\n")
        with io.open(sano, "w", encoding="utf-8") as f:
            f.write("from decimal import Decimal\n"
                    "def totale(riga):\n"
                    "    importo_cents = Decimal(str(riga['importo']))\n"
                    "    return importo_cents\n")
        grida = len(rilievi([guasto])) == 1
        tace = len(rilievi([sano])) == 0
        return grida, tace
    finally:
        shutil.rmtree(cartella, ignore_errors=True)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    tutte_ok, righe = precondizioni()
    print("=" * 86)
    print("🧾 ESAME MONEY-FLOAT — «nessun numero con la virgola tocca un prezzo» (blocco SOLDI)")
    print("=" * 86)
    for nome, ok, dettaglio in righe:
        print("  %-6s %s  %s" % ("OK" if ok else "ROSSO", nome, dettaglio))
    if not tutte_ok:
        print("VERDETTO: ⛔ NON ESEGUIBILE — le precondizioni non reggono (S7): niente "
              "scritture, niente numeri")
        return 2
    esito, denominatore, motivo, trovati = misura()
    for f, ln, msg in trovati:
        print("  RILIEVO %s:%s  %s" % (os.path.relpath(f, RADICE), ln, msg[:100]))
    print("  casella %s  (denominatore %d file)%s"
          % ("☑" if esito else "☐", denominatore,
             ("\n     perche': %s" % motivo) if motivo else ""))
    print("  ⛔ COSA NON GUARDA:")
    for r in NON_GUARDA:
        print("     · %s" % r)
    if "--autoprova" in argv:
        grida, tace = autoprova()
        print("  AUTOPROVA: grida col guasto=%s · tace a macchina sana=%s" % (grida, tace))
        return 0 if (grida and tace) else 1
    if "--scrivi" in argv:
        scheda.registra(testo_casella(), esito=esito, denominatore=denominatore,
                        comando=COMANDO, ordine=BLOCCO_SOLDI, motivo=motivo or None)
        print("  🗂️  casella scritta%s" % ("" if esito else " (falsa, coi rilievi nel motivo)"))
    print("VERDETTO: %s — %d rilievi money-float su %d file"
          % ("✅" if esito else "⛔", len(trovati), denominatore))
    return 0 if esito else 1


if __name__ == "__main__":
    sys.exit(main())
