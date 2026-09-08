"""L'ESAME DELLE CASELLE 1 E 2 DEL BLOCCO 10 (CORE LEGACY / MANGO) — le tre uscite, e la prova prima di togliere.

    python collaudi/esame_legacy.py                  misura e MOSTRA le due caselle (sola lettura, niente rete)
    python collaudi/esame_legacy.py --scrivi         misura e SCRIVE le due caselle nella scheda (anche un rosso)
    python collaudi/esame_legacy.py --casella uscite|prova [--scrivi]
    python collaudi/esame_legacy.py --con-guasto     due guasti costruiti (un modulo VIVO senza test dedicato; un giro
                                                     che lascia un file nella radice): deve gridare, NON scrive
    python collaudi/esame_legacy.py --autoprova      il giudizio e i censimenti, nelle due direzioni

⛔ I TESTI DELLE CASELLE NON SI RICOPIANO: si leggono da `collaudi/piano.py` per SOTTOSTRINGA (`MARCHE`).
⛔ QUESTO ATTREZZO NON CANCELLA NIENTE, MAI (regola ferrea 5): non contiene chiamate che tolgono file (la guardia in
   test_pipeline_ci lo verifica sull'albero sintattico) e un giro lascia l'elenco dei file com'era.

COSA MISURA, dichiarato (D18) — le definizioni sono quelle date da B il 2026-09-07 (SendMessage), rovesciabili.
Per OGNI modulo del blocco 10 (elenco letto da piano.py, campo `moduli`) si misurano CINQUE fatti:
  raggiunto   la produzione lo accende: sta fra i «vivi» di `collaudi/raggiungibilita.cammina()` (D10: si riusa
              l'attrezzo che parte dagli ingressi VERI dell'artefatto, non un grep a mano);
  collaudato  esiste un test dedicato `test_faseNN_*.py` (o `test_faseNN.py`);
  voce        il REGISTRO_INGEGNERIA lo nomina (`faseNN_nome.py`);
  accensione  il REGISTRO, sezione «COSTRUITO ma SPENTO — come si ACCENDE», ha una RIGA con il suo numero nella
              prima colonna (cioe' dice COME si accende);
  usato_vivo  qualcosa di VIVO lo nomina: un modulo raggiunto, `main_casavip.py`, i file di deploy (Dockerfile*,
              docker-compose*, deploy/*.sh|*.yml|*.conf, .github/workflows), anche dello stack vecchio.
E le TRE USCITE (una sola per modulo, altrimenti ROSSO col motivo):
  SERVE E SI COLLAUDA          raggiunto E collaudato;
  SPENTO E SI DICE COME SI ACCENDE   non raggiunto E ha la riga d'accensione;
  ESTRANEO E SI TOGLIE         non raggiunto, NON collaudato, NESSUNA voce, e nulla di vivo lo usa.
  Un modulo raggiunto ma senza test e' «serve ma NON si collauda» (rosso). Un modulo non raggiunto che ha ancora test
  e voce ma NESSUNA riga d'accensione e' «morto che si collauda e si documenta senza dire come si accende» (rosso: e'
  proprio la decisione che la casella chiede di prendere: o si scrive come si accende, o si toglie).

CASELLA «uscite»   un passo per modulo: verde se ha UNA uscita. Denominatore = moduli.
CASELLA «prova»    per ogni modulo NON raggiunto l'attrezzo STAMPA la prova di cosa lo usa (riferimenti divisi fra
                   PRODUZIONE VIVA e FUORI: moduli morti, collaudi/, test_*.py, documenti) e dichiara se «nulla di
                   vivo lo usa»; un passo per modulo non raggiunto + un passo «l'attrezzo non ha tolto nessun file».
                   La casella e' verde se ogni prova e' stata PRODOTTA (non se e' «pulita»): e' la casella del
                   metodo -- prima la prova, poi (una persona) decide.

⛔ D18: `precondizioni()` ferma il giro; `--autoprova` e `--con-guasto`; `NON_GUARDA`; guardia
   `test_pipeline_ci.TestLEsameDelLegacyNonPuoBARARE`. `os.environ` non viene toccato (confronto per intero).
"""
import io
import os
import re
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
for _p in (RADICE, QUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import raggiungibilita  # noqa: E402  (D10: si riusa)
import scheda  # noqa: E402
from piano import BLOCCHI  # noqa: E402

BLOCCO = 10
MARCHE = {"uscite": "UNA delle tre uscite", "prova": "non si cancella niente"}
COMANDI = {k: "python collaudi/esame_legacy.py --casella %s --scrivi" % k for k in MARCHE}
SITUAZIONI = {"uscite": ("uscite",), "prova": ("prove", "mani_in_tasca")}
USCITE = ("SERVE E SI COLLAUDA", "SPENTO E SI DICE COME SI ACCENDE", "ESTRANEO E SI TOGLIE")
TITOLO_SEZIONE_SPENTO = "COSTRUITO ma SPENTO"
FILE_DI_DEPLOY = re.compile(r"^(Dockerfile.*|docker-compose.*\.yml|requirements.*\.txt|Procfile|.*\.toml)$")
PASSI = {"uscite": [], "prova": []}

NON_GUARDA = (
    "se un modulo «raggiunto» sia anche ESEGUITO davvero (raggiungibilita conta gli import, non le chiamate: "
    "spento non e' morto, memoria del 2026-08-17); qui «serve» = la produzione lo importa",
    "se il test dedicato sia BUONO (quello lo dice il Giudice): qui si pretende solo che esista",
    "se la riga «come si accende» sia VERA: qui si pretende che ci sia; provarla e' la casella del modulo",
    "cosa c'e' sul VPS fuori dal repository (cron, unita' systemd, script in /root): B lo legge con ssh; qui si "
    "guardano i file di deploy DENTRO il repository, compreso lo stack vecchio (Dockerfile, docker-compose.tavolavip*)",
    "i documenti e i collaudi che nominano un modulo morto: sono riferimenti FUORI dalla produzione, stampati nella "
    "prova ma non contano come «vivo»",
)


def passo(casella, situazione, nome, ok, dettaglio=""):
    PASSI[casella].append((situazione, nome, bool(ok), dettaglio))
    print("  %s  [%s/%s] %s%s" % ("OK  " if ok else "ROSSO", casella, situazione, nome,
                                   ("  -> " + dettaglio) if dettaglio else ""))
    return bool(ok)


def giudica(passi, situazioni):
    motivi = []
    for s in situazioni:
        suoi = [p for p in passi if p[0] == s]
        if not suoi:
            motivi.append("situazione «%s» NON misurata" % s)
            continue
        for _s, nome, ok, dettaglio in suoi:
            if not ok:
                motivi.append("[%s] %s%s" % (s, nome, (" (%s)" % dettaglio) if dettaglio else ""))
    fuori = [p for p in passi if p[0] not in situazioni]
    if fuori:
        motivi.append("passi fuori dalle situazioni: %d" % len(fuori))
    return (not motivi), motivi, len(passi)


def condizione(casella):
    blocco = [b for b in BLOCCHI if b["ordine"] == BLOCCO]
    cond = blocco[0]["finito_quando"] if len(blocco) == 1 else ()
    trovate = [c for c in cond if MARCHE[casella] in str(c)]
    if len(trovate) != 1:
        raise RuntimeError("nel blocco %d trovo %d caselle con «%s»: ne serve UNA" % (BLOCCO, len(trovate), MARCHE[casella]))
    return trovate[0]


def moduli_del_blocco():
    blocco = [b for b in BLOCCHI if b["ordine"] == BLOCCO]
    return tuple(blocco[0]["moduli"]) if len(blocco) == 1 else ()


def _leggi(percorso):
    with io.open(percorso, encoding="utf-8", errors="replace") as f:
        return f.read()


# ---- i cinque fatti ----
def righe_di_accensione(registro):
    """I numeri di fase nella prima colonna della tabella «COSTRUITO ma SPENTO»."""
    i = registro.find(TITOLO_SEZIONE_SPENTO)
    while i >= 0 and not registro[max(0, i - 8):i].strip().endswith("##") and "## " not in registro[max(0, i - 12):i]:
        i = registro.find(TITOLO_SEZIONE_SPENTO, i + 1)
    if i < 0:
        return set()
    j = registro.find("\n## ", i + 1)
    sezione = registro[i:j if j > 0 else len(registro)]
    return set(re.findall(r"^\|\s*\**(\d+)\**\s*\|", sezione, re.M))


def test_dedicato(modulo, radice=None):
    base = radice or RADICE
    n = modulo.split("_")[0]
    return sorted(t for t in os.listdir(base) if t == "test_%s.py" % n or (t.startswith("test_%s_" % n) and t.endswith(".py")))


def file_di_deploy(radice=None):
    base = radice or RADICE
    fuori = [n for n in os.listdir(base) if FILE_DI_DEPLOY.match(n)]
    for cartella, suffissi in (("deploy", (".sh", ".yml", ".yaml", ".conf", ".py", ".env", ".service")),
                               (os.path.join(".github", "workflows"), (".yml", ".yaml"))):
        p = os.path.join(base, cartella)
        if os.path.isdir(p):
            fuori.extend(os.path.join(cartella, n) for n in sorted(os.listdir(p)) if n.endswith(suffissi))
    return sorted(fuori)


def riferimenti(modulo, vivi, radice=None):
    """Chi nomina il modulo, diviso fra PRODUZIONE VIVA e FUORI. Cerca il nome intero (`fase25_brain`)
    e il nome del file; un modulo non si conta da solo."""
    base = radice or RADICE
    bersaglio = re.compile(r"\b%s\b" % re.escape(modulo))
    vivo, fuori = [], []
    nomi = sorted(os.listdir(base))
    for n in nomi:
        if n == modulo + ".py":
            continue
        if re.fullmatch(r"fase\d+[A-Za-z0-9_]*\.py", n):
            if bersaglio.search(_leggi(os.path.join(base, n))):
                (vivo if n[:-3] in vivi else fuori).append(n)
        elif n == "main_casavip.py":
            if bersaglio.search(_leggi(os.path.join(base, n))):
                vivo.append(n)
        elif n.startswith("test_") and n.endswith(".py"):
            if bersaglio.search(_leggi(os.path.join(base, n))):
                fuori.append(n)
        elif n.endswith(".md"):
            if bersaglio.search(_leggi(os.path.join(base, n))):
                fuori.append(n)
    for n in file_di_deploy(base):
        if bersaglio.search(_leggi(os.path.join(base, n))):
            vivo.append(n)
    c = os.path.join(base, "collaudi")
    if os.path.isdir(c):
        for n in sorted(os.listdir(c)):
            if n.endswith(".py") and bersaglio.search(_leggi(os.path.join(c, n))):
                fuori.append("collaudi/" + n)
    return vivo, fuori


def fatti(modulo, vivi, registro, radice=None):
    return {"raggiunto": modulo in vivi,
            "collaudato": test_dedicato(modulo, radice),
            "voce": ("`%s.py`" % modulo) in registro or ("%s.py" % modulo) in registro,
            "accensione": modulo.split("_")[0][4:] in righe_di_accensione(registro)}


def uscita(f):
    """(uscita | None, motivo). PURA: dipende solo dai cinque fatti."""
    if f["raggiunto"] and f["collaudato"]:
        return USCITE[0], "raggiunto dalla produzione, test dedicato %s" % ",".join(f["collaudato"])
    if f["raggiunto"]:
        return None, "raggiunto dalla produzione ma SENZA test dedicato: serve ma non si collauda"
    if f["accensione"]:
        return USCITE[1], "non raggiunto; il registro dice come si accende"
    if not f["collaudato"] and not f["voce"] and not f.get("usato_vivo"):
        return USCITE[2], "non raggiunto, nessun test, nessuna voce, nulla di vivo lo usa"
    if f.get("usato_vivo"):
        return None, "non raggiunto ma qualcosa di vivo lo nomina (%s): ne' spento ne' estraneo" % ",".join(f["usato_vivo"])
    return None, ("non raggiunto, senza riga «come si accende», ma ha ancora %s%s: morto che si collauda e si "
                  "documenta senza dire come si accende" % ("test (%s)" % ",".join(f["collaudato"]) if f["collaudato"] else "",
                                                             " e voce nel registro" if f["voce"] else ""))


def precondizioni():
    fuori = []
    for k in MARCHE:
        try:
            fuori.append(("la casella «%s» esiste nel piano, una sola" % MARCHE[k], True, " ".join(str(condizione(k)).split())[:70]))
        except Exception as e:
            fuori.append(("la casella «%s» esiste nel piano, una sola" % MARCHE[k], False, str(e)))
    try:
        impronta = scheda.impronta_del_blocco(BLOCCO)
        fuori.append(("il blocco ha un'impronta", bool(impronta), impronta or "il piano non si legge"))
    except Exception as e:
        fuori.append(("il blocco ha un'impronta", False, str(e)))
    mod = moduli_del_blocco()
    fuori.append(("il blocco elenca dei moduli e i file esistono", bool(mod) and all(
        os.path.isfile(os.path.join(RADICE, m + ".py")) for m in mod), "%d moduli" % len(mod)))
    try:
        vivi, morti, tutti = raggiungibilita.cammina(RADICE)
        fuori.append(("raggiungibilita.cammina parte dagli ingressi veri e trova dei vivi", len(vivi) > 0 and len(tutti) > len(vivi),
                      "vivi %d, morti %d, ingressi %s" % (len(vivi), len(morti), ",".join(raggiungibilita.ingressi_veri(RADICE)))))
    except Exception as e:
        fuori.append(("raggiungibilita.cammina parte dagli ingressi veri", False, "%s: %s" % (type(e).__name__, e)))
    reg = os.path.join(RADICE, "REGISTRO_INGEGNERIA.md")
    righe = righe_di_accensione(_leggi(reg)) if os.path.isfile(reg) else set()
    fuori.append(("il REGISTRO ha la sezione «%s» con delle righe" % TITOLO_SEZIONE_SPENTO, len(righe) > 0, "%d righe" % len(righe)))
    return all(ok for _, ok, _ in fuori), fuori


# ---- le misure ----
def misura(con_guasto=False, scelte=("uscite", "prova")):
    vivi, _morti, _tutti = raggiungibilita.cammina(RADICE)
    registro = _leggi(os.path.join(RADICE, "REGISTRO_INGEGNERIA.md"))
    moduli = moduli_del_blocco()
    prima = sorted(os.listdir(RADICE))
    if "uscite" in scelte:
        print("\n--- USCITE: i cinque fatti per ogni modulo del blocco, e l'unica uscita che ne segue ---")
    if "prova" in scelte:
        print("    (le prove dei non raggiunti seguono sotto)")
    conteggio = {}
    prove = []
    for m in moduli:
        f = fatti(m, vivi, registro)
        vivo, fuori = riferimenti(m, vivi)
        f["usato_vivo"] = vivo
        if con_guasto and f["raggiunto"]:
            f["collaudato"] = []                    # IL GUASTO 1: un modulo VIVO senza test dedicato
        u, motivo = uscita(f)
        conteggio[u] = conteggio.get(u, 0) + 1
        if "uscite" in scelte:
            passo("uscite", "uscite", "%s: %s" % (m, u or "NESSUNA USCITA"), u is not None,
                  "%s | raggiunto=%s test=%s voce=%s accensione=%s usato_vivo=%s"
                  % (motivo, f["raggiunto"], bool(f["collaudato"]), f["voce"], f["accensione"], vivo or "-"))
        if not f["raggiunto"]:
            prove.append((m, u, vivo, fuori))
    if "prova" in scelte:
        print("\n--- PROVA: per ogni modulo NON raggiunto, chi lo nomina (la prova si stampa, nessuno cancella) ---")
        for m, u, vivo, fuori in prove:
            passo("prova", "prove", "%s: prova prodotta -- PRODUZIONE VIVA: %s | FUORI: %d riferimenti (%s)"
                  % (m, ", ".join(vivo) if vivo else "NESSUNO (nulla di vivo lo usa)", len(fuori),
                     ", ".join(fuori[:6]) + (" ..." if len(fuori) > 6 else "")), True,
                  "uscita: %s" % (u or "da decidere"))
        if not prove:
            passo("prova", "prove", "nessun modulo del blocco e' fuori dalla produzione: niente da provare", True)
        dopo = sorted(os.listdir(RADICE))
        if con_guasto:
            dopo = sorted(dopo + ["fase999_lasciato_qui.py"])   # IL GUASTO 2: un giro che lascia un file
        passo("prova", "mani_in_tasca", "l'attrezzo non ha tolto ne' aggiunto nessun file nella radice", prima == dopo,
              "%d file prima, %d dopo" % (len(prima), len(dopo)))
    print("\n  riepilogo: %s" % ", ".join("%s=%d" % (k or "NESSUNA USCITA", v) for k, v in sorted(conteggio.items(), key=lambda kv: str(kv[0]))))
    return conteggio


# ---- autoprova ----
def passi_finti(casella, rossi=(), senza=()):
    fuori = []
    for s in SITUAZIONI[casella]:
        if s in senza:
            continue
        for i in range(2):
            fuori.append((s, "passo %d" % i, not (s in rossi and i == 1), ""))
    return fuori


def autoprova():
    righe, riuscita = [], True
    for casella, situazioni in SITUAZIONI.items():
        casi = [("%s: tutte le situazioni verdi" % casella, passi_finti(casella), True)]
        for s in situazioni:
            casi.append(("%s: un passo rosso in «%s»" % (casella, s), passi_finti(casella, rossi=(s,)), False))
            casi.append(("%s: «%s» non misurata" % (casella, s), passi_finti(casella, senza=(s,)), False))
        casi.append(("%s: nessun passo" % casella, [], False))
        for nome, passi, atteso in casi:
            verde, motivi, den = giudica(passi, situazioni)
            ok = verde == atteso
            riuscita = riuscita and ok
            righe.append("   %-46s -> %-6s (atteso %-6s) den %d%s" % (nome, "VERDE" if verde else "ROSSO",
                                                                        "VERDE" if atteso else "ROSSO", den,
                                                                        "" if ok else "   ⛔ NON E' QUELLO CHE DOVEVA DIRE"))
    # la funzione delle uscite, pura, sui cinque fatti
    casi_uscita = [
        ({"raggiunto": True, "collaudato": ["t"], "voce": True, "accensione": False, "usato_vivo": []}, USCITE[0]),
        ({"raggiunto": True, "collaudato": [], "voce": True, "accensione": False, "usato_vivo": []}, None),
        ({"raggiunto": False, "collaudato": ["t"], "voce": True, "accensione": True, "usato_vivo": []}, USCITE[1]),
        ({"raggiunto": False, "collaudato": [], "voce": False, "accensione": False, "usato_vivo": []}, USCITE[2]),
        ({"raggiunto": False, "collaudato": [], "voce": False, "accensione": False, "usato_vivo": ["Dockerfile"]}, None),
        ({"raggiunto": False, "collaudato": ["t"], "voce": True, "accensione": False, "usato_vivo": []}, None),
    ]
    ok = all(uscita(f)[0] == atteso for f, atteso in casi_uscita)
    riuscita = riuscita and ok
    righe.append("   %-46s -> %s" % ("le tre uscite sui cinque fatti (6 casi)", "OK" if ok else "⛔ ROTTE"))
    reg_finto = "## 1) x\n| 25 | a |\n## 2) COSTRUITO ma SPENTO\n| Fase | Cosa |\n|---|---|\n| **46** | b |\n| 92 | c |\n## 3) y\n| 99 | z |\n"
    ok2 = righe_di_accensione(reg_finto) == {"46", "92"}
    riuscita = riuscita and ok2
    righe.append("   %-46s -> %s" % ("il lettore della sezione «come si accende»", "OK" if ok2 else "⛔ ROTTO"))
    return riuscita, righe


def _stampa_non_guarda():
    print("-" * 86)
    print("⛔ COSA QUESTO ESAME NON HA ESAMINATO (D18 punto 3)")
    for r in NON_GUARDA:
        print("   · %s" % r)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    os.chdir(RADICE)
    for k in PASSI:
        del PASSI[k][:]
    scelte = [argv[argv.index("--casella") + 1]] if "--casella" in argv else list(MARCHE)
    for c in scelte:
        if c not in MARCHE:
            print("⛔ casella sconosciuta: %s (valide: %s)" % (c, ", ".join(MARCHE)))
            return 2
    print("=" * 86)
    print("🧾 ESAME DEL BLOCCO 10 — legacy: %s" % ", ".join("«%s»" % MARCHE[c] for c in scelte))
    print("=" * 86)
    if "--autoprova" in argv:
        print("🔁 AUTOPROVA — il giudizio, le uscite e il lettore del registro nelle due direzioni (D18 punto 2)")
        riuscita, righe = autoprova()
        for r in righe:
            print(r)
        _stampa_non_guarda()
        print("=" * 86)
        print("VERDETTO: %s" % ("✅ il giudizio grida sui passi rossi e tace sui verdi" if riuscita
                                else "⛔ IL GIUDIZIO NON E' AFFIDABILE"))
        return 0 if riuscita else 1
    con_guasto = "--con-guasto" in argv
    if con_guasto and "--scrivi" in argv:
        print("⛔ FERMO: `--con-guasto` non scrive. Serve a vedere l'esame gridare; registrare quel")
        print("   rosso metterebbe nella scheda un guasto costruito apposta.")
        return 2
    tutte_ok, righe = precondizioni()
    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    for nome, ok, motivo in righe:
        print("  %-9s %-72s %s" % ("OK" if ok else "⛔ NO", nome, motivo))
    if not tutte_ok:
        print("VERDETTO: ⛔ FERMO — una precondizione non regge, quindi NON misuro e NON scrivo.")
        _stampa_non_guarda()
        return 2
    if con_guasto:
        print("⚠️  PASSATA COI GUASTI DENTRO: i moduli vivi senza test dedicato; un file lasciato nella radice")
    ambiente_prima = dict(os.environ)
    try:
        misura(con_guasto, tuple(scelte))
    except Exception as e:                                        # noqa: BLE001 - una misura rotta e' un rosso
        for c in scelte:
            passo(c, SITUAZIONI[c][0], "la misura e' ESPLOSA", False, "%s: %s" % (type(e).__name__, e))
    for c in scelte:
        passo(c, SITUAZIONI[c][0], "l'ambiente (os.environ) e' identico a prima della misura", dict(os.environ) == ambiente_prima)
    uscita_processo = 0
    for c in scelte:
        verde, motivi, denominatore = giudica(PASSI[c], SITUAZIONI[c])
        print("")
        print("— casella «%s» —" % MARCHE[c])
        print("VERDETTO: %s — passi %d, rossi %d, denominatore %d"
              % ("✅ VERDE" if verde else "⛔ ROSSO", len(PASSI[c]), sum(1 for p in PASSI[c] if not p[2]), denominatore))
        for m in motivi:
            print("   perche': %s" % m[:220])
        uscita_processo = uscita_processo or (0 if verde else 1)
        if "--scrivi" in argv:
            riga = scheda.registra(condizione(c), esito=verde, denominatore=denominatore, comando=COMANDI[c],
                                   ordine=BLOCCO, motivo="; ".join(motivi)[:600] or None)
            print("  SCRITTA nella scheda: blocco %d · esito %s · denominatore %d · impronta %s · motivo: %s"
                  % (riga["blocco"], riga["esito"], riga["denominatore"], riga["impronta"], riga.get("motivo") or "-"))
    if "--scrivi" not in argv:
        print("")
        print("(non ho scritto niente: aggiungi --scrivi per registrare nella scheda)")
    _stampa_non_guarda()
    print("=" * 86)
    return uscita_processo


if __name__ == "__main__":
    sys.exit(main())
