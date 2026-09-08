"""L'ESAME DELLA CASELLA 3 DEL BLOCCO 8 (INFRASTRUTTURA) — la testa che NON muore col server.

    python collaudi/esame_sentinella.py                 legge le esecuzioni della sentinella dall'API pubblica di
                                                        GitHub (sola lettura, nessuna credenziale), misura e MOSTRA
    python collaudi/esame_sentinella.py --scrivi        misura e SCRIVE nella scheda (anche un rosso, col motivo)
    python collaudi/esame_sentinella.py --salva F       salva le letture in F
    python collaudi/esame_sentinella.py --da-file F     giudica letture salvate: niente rete
    python collaudi/esame_sentinella.py --con-guasto    storce le letture (ultimo giro di tre giorni fa, mai un
                                                        rosso in storia): deve gridare, NON scrive
    python collaudi/esame_sentinella.py --autoprova     il giudizio su letture costruite, nelle due direzioni

⛔ IL TESTO DELLA CASELLA NON SI RICOPIA: si legge da `collaudi/piano.py` (e' la chiave della scheda).

COSA MISURA, dichiarato (D18) — decisione della chat A il 2026-09-07 col mandato di B (censimento in lettura), rovesciabile.
La sentinella esterna e' `.github/workflows/sentinella.yml`: GitHub Actions, fuori dal VPS, a orario (`schedule`),
interroga https://bookinvip.com/api/health e va ROSSA (email al proprietario) se il sito non risponde. «Si accorge se
il sito muore» vuol dire QUATTRO cose misurabili:
  ESISTE     il workflow c'e', e' a `schedule`, interroga la salute dall'esterno (letto dal file, non a memoria);
  E' SVEGLIA l'ultimo giro e' RECENTE e i giri nelle ultime 24 ore sono FITTI: la promessa scritta nel file e' «ogni
             ~15 minuti» (cron a minuti dispari); qui si pretende che l'ultimo giro abbia meno di 60 minuti e che il
             BUCO MASSIMO fra due giri consecutivi nelle ultime 24 ore stia sotto i 60 minuti (4 volte la promessa:
             GitHub ritarda gli schedule, e il file lo dichiara; un buco di ORE e' un sito che puo' morire per ore
             senza che nessuno se ne accorga);
  SA GRIDARE nella storia c'e' almeno un giro ROSSO e almeno uno VERDE (le due direzioni: un allarme mai andato
             rosso potrebbe non saper gridare, uno sempre rosso viene spento);
  NON SCADE  GitHub spegne gli schedule dopo 60 giorni senza attivita' del repository: l'ultimo push e' recente.
Denominatore = passi. Letture: API pubblica `GET /repos/<owner>/<repo>/actions/workflows/sentinella.yml/runs`
(il repository e' pubblico: nessun gettone; se GitHub limita le richieste, e' una precondizione rossa, non un verde).

⛔ D18: `precondizioni()` ferma il giro; `--autoprova` e `--con-guasto` (che non scrive mai); `NON_GUARDA`; guardia
   `test_pipeline_ci.TestLEsameDellaSentinellaNonPuoBARARE`. `os.environ` non viene toccato.
"""
import io
import json
import os
import re
import subprocess  # nosec B404 - solo `git remote get-url`, argomenti fissi
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
for _p in (RADICE, QUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import scheda  # noqa: E402
from piano import BLOCCHI  # noqa: E402

BLOCCO = 8
MARCA = "sentinella ESTERNA"
COMANDO = "python collaudi/esame_sentinella.py --scrivi"
WORKFLOW = os.path.join(".github", "workflows", "sentinella.yml")
SITUAZIONI = ("esiste", "sveglia", "grida", "non_scade")
ULTIMO_MAX_MIN = 60
BUCO_MAX_MIN = 60
INATTIVITA_MAX_GIORNI = 60
PASSI = []

NON_GUARDA = (
    "se il fondatore LEGGE l'email che GitHub manda quando il giro va rosso: nessuna macchina lo puo' dire",
    "PERCHE' un giro e' andato rosso (sito morto, buco di rete, GitHub in ritardo): lo dicono i log di nginx sul "
    "VPS, che legge B; qui si misura solo CHE la sentinella sa gridare",
    "la testa INTERNA (deploy/watchdog.sh in cron sul VPS, Telegram): sta dentro la stanza in fiamme; B la legge",
    "l'ultimo miglio dichiarato nel workflow stesso (UptimeRobot o simili): richiede un conto del fondatore, non "
    "esiste e non e' coperto",
    "i giri oltre i 100 piu' recenti: l'API ne serve una pagina; il buco massimo e' misurato sulle ultime 24 ore",
)


def passo(situazione, nome, ok, dettaglio=""):
    PASSI.append((situazione, nome, bool(ok), dettaglio))
    print("  %s  [%s] %s%s" % ("OK  " if ok else "ROSSO", situazione, nome, ("  -> " + dettaglio) if dettaglio else ""))
    return bool(ok)


def giudica(passi, situazioni=SITUAZIONI):
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


def condizione():
    blocco = [b for b in BLOCCHI if b["ordine"] == BLOCCO]
    cond = blocco[0]["finito_quando"] if len(blocco) == 1 else ()
    trovate = [c for c in cond if MARCA in str(c)]
    if len(trovate) != 1:
        raise RuntimeError("nel blocco %d trovo %d caselle con «%s»: ne serve UNA" % (BLOCCO, len(trovate), MARCA))
    return trovate[0]


def _quando(iso):
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def repo_da_git():
    esito = subprocess.run(["git", "remote", "get-url", "origin"], cwd=RADICE, stdout=subprocess.PIPE,  # nosec B603 B607
                           stderr=subprocess.PIPE, check=False)
    url = esito.stdout.decode("utf-8", "replace").strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def _get_json(url):
    if not str(url).startswith("https://api.github.com/"):
        raise ValueError("solo l'API pubblica di GitHub: %r" % (url,))
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "esame_sentinella"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310  # nosec B310 - https fisso, sola lettura
        return r.status, json.loads(r.read().decode("utf-8", "replace"))


def leggi_dal_vivo(repo):
    base = "https://api.github.com/repos/%s" % repo
    _s, giri = _get_json(base + "/actions/workflows/sentinella.yml/runs?per_page=100")
    _s, rossi = _get_json(base + "/actions/workflows/sentinella.yml/runs?status=failure&per_page=1")
    _s, info = _get_json(base)
    return {"repo": repo, "adesso": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "giri": [{"n": g["run_number"], "evento": g["event"], "stato": g["status"], "esito": g["conclusion"],
                      "quando": g["created_at"]} for g in giri.get("workflow_runs") or []],
            "totale": giri.get("total_count"), "rossi_totali": rossi.get("total_count"),
            "ultimo_push": info.get("pushed_at")}


def workflow_letto():
    p = os.path.join(RADICE, WORKFLOW)
    if not os.path.isfile(p):
        return None
    with io.open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def misura(letture, con_guasto=False):
    print("\n--- LA SENTINELLA: esiste, e' sveglia, sa gridare, non scade ---")
    testo = workflow_letto() or ""
    passo("esiste", "il workflow %s esiste ed e' a orario (`schedule` con un `cron`)" % WORKFLOW,
          bool(testo) and re.search(r"^\s*schedule:\s*$", testo, re.M) is not None and "cron:" in testo)
    passo("esiste", "interroga la salute del sito dall'esterno (bookinvip.com/api/health) con curl",
          "bookinvip.com/api/health" in testo and "curl" in testo)
    giri = list(letture.get("giri") or [])
    adesso = _quando(letture["adesso"]) if letture.get("adesso") else datetime.now(timezone.utc)
    if con_guasto:
        giri = [dict(g, quando=(_quando(g["quando"]) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"), esito="success") for g in giri]
    tempi = sorted((_quando(g["quando"]) for g in giri), reverse=True)
    eta = (adesso - tempi[0]).total_seconds() / 60 if tempi else None
    passo("sveglia", "l'ultimo giro ha meno di %d minuti" % ULTIMO_MAX_MIN, eta is not None and eta <= ULTIMO_MAX_MIN,
          "ultimo giro %s (%.0f minuti fa)" % (tempi[0].strftime("%Y-%m-%d %H:%M UTC") if tempi else "-", eta or -1))
    ultime24 = [t for t in tempi if adesso - t <= timedelta(hours=24)]
    buchi = [(a - b).total_seconds() / 60 for a, b in zip(ultime24, ultime24[1:])]
    if ultime24:
        buchi.append((adesso - ultime24[0]).total_seconds() / 60)
    buco_max = max(buchi) if buchi else None
    passo("sveglia", "nelle ultime 24 ore il buco massimo fra due giri e' sotto i %d minuti (promessa del file: ~15)" % BUCO_MAX_MIN,
          buco_max is not None and buco_max <= BUCO_MAX_MIN,
          "giri nelle 24 ore: %d, buco massimo %.0f minuti" % (len(ultime24), buco_max or -1))
    verdi = sum(1 for g in giri if g.get("esito") == "success")
    rossi_recenti = sum(1 for g in giri if g.get("esito") == "failure")
    rossi = letture.get("rossi_totali")
    rossi = rossi if isinstance(rossi, int) else rossi_recenti
    if con_guasto:
        rossi = 0                                    # IL GUASTO: una sentinella che non ha mai gridato
    passo("grida", "nella storia c'e' almeno un giro VERDE e almeno un giro ROSSO (le due direzioni)",
          verdi > 0 and rossi > 0, "verdi (ultimi %d): %d, rossi in storia: %d" % (len(giri), verdi, rossi))
    up = letture.get("ultimo_push")
    giorni = (adesso - _quando(up)).days if up else None
    passo("non_scade", "il repository ha avuto un push da meno di %d giorni (oltre, GitHub spegne gli schedule)" % INATTIVITA_MAX_GIORNI,
          giorni is not None and giorni < INATTIVITA_MAX_GIORNI, "ultimo push %s (%s giorni)" % (up, giorni))


def letture_finte(minuti_fa=5, buco=15, rossi=3, push_giorni=1, n=96):
    adesso = datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc)
    giri = [{"n": n - i, "evento": "schedule", "stato": "completed", "esito": "success",
             "quando": (adesso - timedelta(minutes=minuti_fa + i * buco)).strftime("%Y-%m-%dT%H:%M:%SZ")} for i in range(n)]
    return {"adesso": adesso.strftime("%Y-%m-%dT%H:%M:%SZ"), "giri": giri, "rossi_totali": rossi,
            "ultimo_push": (adesso - timedelta(days=push_giorni)).strftime("%Y-%m-%dT%H:%M:%SZ")}


def autoprova():
    casi = [("sentinella fitta, rossa una volta in storia", letture_finte(), True),
            ("ultimo giro di due ore fa", letture_finte(minuti_fa=120), False),
            ("giri ogni 5 ore", letture_finte(buco=300, n=8), False),
            ("mai un rosso in storia", letture_finte(rossi=0), False),
            ("repository fermo da 70 giorni", letture_finte(push_giorni=70), False),
            ("nessun giro", {"adesso": "2026-09-07T18:00:00Z", "giri": [], "rossi_totali": 0, "ultimo_push": None}, False)]
    righe, riuscita = [], True
    for nome, letture, atteso in casi:
        del PASSI[:]
        flusso, vero = io.StringIO(), sys.stdout
        sys.stdout = flusso
        try:
            misura(letture)
        finally:
            sys.stdout = vero
        verde, motivi, den = giudica(PASSI)
        ok = verde == atteso
        riuscita = riuscita and ok
        righe.append("   %-46s -> %-6s (atteso %-6s) den %d%s" % (nome, "VERDE" if verde else "ROSSO",
                                                                    "VERDE" if atteso else "ROSSO", den,
                                                                    "" if ok else "   ⛔ NON E' QUELLO CHE DOVEVA DIRE: %s" % "; ".join(motivi)[:160]))
    del PASSI[:]
    return riuscita, righe


def precondizioni(con_rete=True):
    fuori = []
    try:
        testo = " ".join(str(condizione()).split())
        fuori.append(("la casella esiste nel piano, una sola, e parla di una sentinella non nostra", "non nostra" in testo, testo[:70]))
    except Exception as e:
        fuori.append(("la casella esiste nel piano, una sola", False, str(e)))
    try:
        impronta = scheda.impronta_del_blocco(BLOCCO)
        fuori.append(("il blocco ha un'impronta", bool(impronta), impronta or "il piano non si legge"))
    except Exception as e:
        fuori.append(("il blocco ha un'impronta", False, str(e)))
    fuori.append(("il file del workflow esiste", workflow_letto() is not None, WORKFLOW))
    if con_rete:
        repo = repo_da_git()
        fuori.append(("il remoto origin e' un repository GitHub", bool(repo), repo or "?"))
        if repo:
            try:
                st, info = _get_json("https://api.github.com/repos/%s" % repo)
                fuori.append(("l'API pubblica di GitHub risponde e il repository e' pubblico", st == 200 and info.get("private") is False,
                              "http=%s private=%r" % (st, info.get("private"))))
            except Exception as e:
                fuori.append(("l'API pubblica di GitHub risponde", False, "%s: %s" % (type(e).__name__, e)))
    return all(ok for _, ok, _ in fuori), fuori


def _stampa_non_guarda():
    print("-" * 86)
    print("⛔ COSA QUESTO ESAME NON HA ESAMINATO (D18 punto 3)")
    for r in NON_GUARDA:
        print("   · %s" % r)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    os.chdir(RADICE)
    del PASSI[:]
    print("=" * 86)
    print("🧾 ESAME DEL BLOCCO 8 — casella 3: la sentinella esterna si accorge se il sito muore")
    print("=" * 86)
    if "--autoprova" in argv:
        print("🔁 AUTOPROVA — il giudizio su letture costruite, nelle due direzioni (D18 punto 2)")
        riuscita, righe = autoprova()
        for r in righe:
            print(r)
        _stampa_non_guarda()
        print("=" * 86)
        print("VERDETTO: %s" % ("✅ il giudizio grida sulle sentinelle addormentate e tace su quella sveglia" if riuscita
                                else "⛔ IL GIUDIZIO NON E' AFFIDABILE"))
        return 0 if riuscita else 1
    con_guasto = "--con-guasto" in argv
    if con_guasto and "--scrivi" in argv:
        print("⛔ FERMO: `--con-guasto` non scrive. Serve a vedere l'esame gridare; registrare quel")
        print("   rosso metterebbe nella scheda una sentinella addormentata apposta.")
        return 2
    da_file = argv[argv.index("--da-file") + 1] if "--da-file" in argv else None
    tutte_ok, righe = precondizioni(con_rete=da_file is None)
    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    for nome, ok, motivo in righe:
        print("  %-9s %-76s %s" % ("OK" if ok else "⛔ NO", nome, motivo))
    if not tutte_ok:
        print("VERDETTO: ⛔ FERMO — una precondizione non regge, quindi NON misuro e NON scrivo.")
        _stampa_non_guarda()
        return 2
    if con_guasto:
        print("⚠️  PASSATA COL GUASTO DENTRO: i giri spostati indietro di tre giorni, tutti verdi")
    ambiente_prima = dict(os.environ)
    try:
        if da_file:
            with io.open(da_file, encoding="utf-8") as f:
                letture = json.load(f)
            print("letture da file: %s (%d giri)" % (da_file, len(letture.get("giri") or [])))
        else:
            letture = leggi_dal_vivo(repo_da_git())
            print("letture dal vivo: %s (%d giri recenti, %r in totale, %r rossi in storia)"
                  % (letture["repo"], len(letture["giri"]), letture.get("totale"), letture.get("rossi_totali")))
            if "--salva" in argv:
                percorso = argv[argv.index("--salva") + 1]
                with io.open(percorso, "w", encoding="utf-8") as f:
                    json.dump(letture, f, ensure_ascii=False, indent=1)
                print("letture salvate in %s" % percorso)
        misura(letture, con_guasto)
    except Exception as e:                                        # noqa: BLE001 - una lettura rotta e' un rosso
        passo("esiste", "le letture o la misura sono ESPLOSE", False, "%s: %s" % (type(e).__name__, e))
    passo("esiste", "l'ambiente (os.environ) e' identico a prima della misura", dict(os.environ) == ambiente_prima)
    verde, motivi, denominatore = giudica(PASSI)
    print("")
    print("VERDETTO: %s — passi %d, rossi %d, denominatore %d"
          % ("✅ VERDE" if verde else "⛔ ROSSO", len(PASSI), sum(1 for p in PASSI if not p[2]), denominatore))
    for m in motivi:
        print("   perche': %s" % m)
    if "--scrivi" in argv:
        riga = scheda.registra(condizione(), esito=verde, denominatore=denominatore, comando=COMANDO, ordine=BLOCCO,
                               motivo="; ".join(motivi)[:600] or None)
        print("  SCRITTA nella scheda: blocco %d · esito %s · denominatore %d · impronta %s · motivo: %s"
              % (riga["blocco"], riga["esito"], riga["denominatore"], riga["impronta"], riga.get("motivo") or "-"))
    else:
        print("")
        print("(non ho scritto niente: aggiungi --scrivi per registrare nella scheda)")
    _stampa_non_guarda()
    print("=" * 86)
    return 0 if verde else 1


if __name__ == "__main__":
    sys.exit(main())
