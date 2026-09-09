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

⛔ DAL 2026-09-08 (chat A col mandato di B): LA CASELLA PRETENDE UN MONITOR ESTERNO VERO, non solo GitHub Actions.
   Misurato il 7/9: GitHub esegue ~7 giri al giorno con buchi di 333 minuti, e la sua documentazione lo dichiara
   («The schedule event can be delayed during periods of high loads ... some queued jobs may be dropped»; il minimo
   e' 5 minuti; gli schedule si spengono dopo 60 giorni senza attivita'). Fonti lette prima (D25):
   docs.github.com «Events that trigger workflows» §schedule (2026) · uptimerobot.com/pricing (2026: piano gratuito
   50 monitor, «5 min. monitoring interval», API inclusa) · uptimerobot.com/api/v2 (2026: `getMonitors`, chiave
   «Read-only ... fetching data with all the get* API endpoints», campi interval/status/logs) · betterstack.com/uptime
   (2026: 10 monitor, «Up to 30 seconds check frequency», REST API). Scelto UptimeRobot: l'intervallo di 5 minuti e'
   quello che la casella chiede, la chiave e' di SOLA LETTURA, zero carta; Better Stack va altrettanto bene (30 s) e
   l'esame accetta letture di qualunque servizio nel formato `esterno` qui sotto.
  ESTERNO    nelle letture c'e' un monitor ESTERNO (non GitHub) che guarda bookinvip.com/api/health, con INTERVALLO
             <= 5 minuti, non in pausa; nelle ultime 24 ore i suoi controlli non hanno BUCHI > 15 minuti e l'ultimo
             ha meno di 15 minuti; sa gridare (ha un contatto d'allarme e nella sua storia c'e' almeno un «giu'»).
             Con un monitor esterno sano, i giri di GitHub restano la seconda linea: si stampano, non decidono.
             SENZA monitor esterno la casella e' ROSSA col motivo (serve un conto: lo apre il fondatore, D12), e i
             giri di GitHub decidono da soli come prima (e oggi non bastano).
  Letture del monitor: `--monitor uptimerobot` legge `getMonitors` con la chiave di SOLA LETTURA nella variabile
  d'ambiente UPTIMEROBOT_API_KEY (mai stampata, mai nel repository; se manca, e' una precondizione rossa), oppure
  `--da-file` con il campo `esterno` gia' riempito:
    "esterno": {"servizio": "uptimerobot", "nome": "...", "url": "https://bookinvip.com/api/health",
                "intervallo_sec": 300, "stato": "up"|"down"|"pausa"|"?", "controlli": ["<ISO UTC>", ...] (ultime 24 h),
                "giu_in_storia": 1, "contatti_allarme": 1}

⛔ D18: `precondizioni()` ferma il giro; `--autoprova` e `--con-guasto` (che non scrive mai); `NON_GUARDA`; guardia
   `test_pipeline_ci.TestLEsameDellaSentinellaNonPuoBARARE`. `os.environ` non viene toccato (la chiave si LEGGE).
"""
import io
import json
import os
import re
import subprocess  # nosec B404 - solo `git remote get-url`, argomenti fissi
import sys
import urllib.parse
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
MONITOR_INTERVALLO_MAX_SEC = 5 * 60
MONITOR_BUCO_MAX_MIN = 15
MONITOR_ULTIMO_MAX_MIN = 15
VARIABILE_CHIAVE = "UPTIMEROBOT_API_KEY"
API_UPTIMEROBOT = "https://api.uptimerobot.com/v2/getMonitors"
SALUTE = "bookinvip.com/api/health"
PASSI = []

NON_GUARDA = (
    "se il fondatore LEGGE l'email che GitHub o il monitor mandano quando il sito muore: nessuna macchina lo puo' dire",
    "PERCHE' un giro e' andato rosso (sito morto, buco di rete, GitHub in ritardo): lo dicono i log di nginx sul "
    "VPS, che legge B; qui si misura solo CHE la sentinella sa gridare",
    "la testa INTERNA (deploy/watchdog.sh in cron sul VPS, Telegram): sta dentro la stanza in fiamme; B la legge",
    "il monitor esterno finche' non esiste: senza un conto (lo apre il fondatore) le letture `esterno` mancano e la "
    "casella e' ROSSA col motivo; quando c'e', qui si legge cio' che l'API del servizio dichiara, non il servizio stesso",
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


def _post_json(url, dati):
    if url != API_UPTIMEROBOT:
        raise ValueError("solo l'API di UptimeRobot: %r" % (url,))
    corpo = urllib.parse.urlencode(dati).encode("utf-8")
    req = urllib.request.Request(url, data=corpo, headers={"Content-Type": "application/x-www-form-urlencoded",
                                                           "Cache-Control": "no-cache", "User-Agent": "esame_sentinella"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310  # nosec B310 - https fisso, sola lettura (getMonitors)
        return r.status, json.loads(r.read().decode("utf-8", "replace"))


def monitor_da_uptimerobot(risposta, adesso):
    """Il campo `esterno` dalle righe di `getMonitors` (logs=1, response_times=1). Prende il monitor che guarda la
    salute del sito; se non c'e', torna None. Stato: 2 = up, 8/9 = giu', 0 = pausa (api/v2)."""
    monitor = [m for m in (risposta.get("monitors") or []) if SALUTE in str(m.get("url") or "")]
    if not monitor:
        return None
    m = monitor[0]
    stati = {2: "up", 8: "down", 9: "down", 0: "pausa", 1: "?"}
    da = adesso - timedelta(hours=24)
    controlli = []
    for rt in m.get("response_times") or []:
        try:
            t = datetime.fromtimestamp(int(rt.get("datetime")), tz=timezone.utc)
        except Exception:
            continue
        if t >= da:
            controlli.append(t.strftime("%Y-%m-%dT%H:%M:%SZ"))
    return {"servizio": "uptimerobot", "nome": str(m.get("friendly_name") or ""), "url": str(m.get("url") or ""),
            "intervallo_sec": int(m.get("interval") or 0), "stato": stati.get(m.get("status"), "?"),
            "controlli": sorted(controlli),
            "giu_in_storia": sum(1 for lg in (m.get("logs") or []) if lg.get("type") == 1),
            "contatti_allarme": len(m.get("alert_contacts") or [])}


def leggi_monitor(adesso):
    """Legge il monitor con la chiave di SOLA LETTURA in UPTIMEROBOT_API_KEY. La chiave non viene mai stampata."""
    chiave = os.environ.get(VARIABILE_CHIAVE, "")
    if not chiave:
        raise RuntimeError("manca la variabile d'ambiente %s (chiave di sola lettura di UptimeRobot)" % VARIABILE_CHIAVE)
    da = int((adesso - timedelta(hours=24)).timestamp())
    _s, risposta = _post_json(API_UPTIMEROBOT, {
        "api_key": chiave, "format": "json", "logs": 1, "logs_limit": 50, "alert_contacts": 1,
        "response_times": 1, "response_times_start_date": da, "response_times_end_date": int(adesso.timestamp())})
    if risposta.get("stat") != "ok":
        err = risposta.get("error") or {}
        raise RuntimeError("UptimeRobot risponde %r: %s" % (risposta.get("stat"), err.get("message") or err.get("type") or "?"))
    return monitor_da_uptimerobot(risposta, adesso)


def workflow_letto():
    p = os.path.join(RADICE, WORKFLOW)
    if not os.path.isfile(p):
        return None
    with io.open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def _buco_massimo(tempi, adesso, ore=24):
    """(quanti nelle ultime `ore`, buco massimo in minuti fra due istanti consecutivi, compreso quello fino ad adesso)."""
    recenti = sorted((t for t in tempi if adesso - t <= timedelta(hours=ore)), reverse=True)
    buchi = [(a - b).total_seconds() / 60 for a, b in zip(recenti, recenti[1:])]
    if recenti:
        buchi.append((adesso - recenti[0]).total_seconds() / 60)
    return len(recenti), (max(buchi) if buchi else None)


def misura(letture, con_guasto=False):
    print("\n--- LA SENTINELLA: esiste, e' sveglia, sa gridare, non scade (monitor esterno + GitHub) ---")
    testo = workflow_letto() or ""
    passo("esiste", "il workflow %s esiste ed e' a orario (`schedule` con un `cron`)" % WORKFLOW,
          bool(testo) and re.search(r"^\s*schedule:\s*$", testo, re.M) is not None and "cron:" in testo)
    passo("esiste", "interroga la salute del sito dall'esterno (%s) con curl" % SALUTE, SALUTE in testo and "curl" in testo)
    adesso = _quando(letture["adesso"]) if letture.get("adesso") else datetime.now(timezone.utc)

    # IL MONITOR ESTERNO (dal 2026-09-08 e' lui che decide; senza, i giri di GitHub decidono e non bastano)
    est = letture.get("esterno") if isinstance(letture.get("esterno"), dict) else None
    if con_guasto:
        est = None                                   # IL GUASTO 1: nessun monitor esterno
    controlli = sorted((_quando(c) for c in (est or {}).get("controlli") or []), reverse=True)
    n24, buco_m = _buco_massimo(controlli, adesso)
    ultimo_m = (adesso - controlli[0]).total_seconds() / 60 if controlli else None
    monitor_c_e = bool(est) and SALUTE in str(est.get("url") or "")
    passo("esiste", "un monitor ESTERNO (non GitHub) esiste e guarda %s" % SALUTE, monitor_c_e,
          ("%s «%s» %s" % (est.get("servizio"), est.get("nome"), est.get("url"))) if est else
          "nessun monitor esterno nelle letture: serve un conto (UptimeRobot o Better Stack, gratuito), lo apre il fondatore")
    fitto = monitor_c_e and 0 < int(est.get("intervallo_sec") or 0) <= MONITOR_INTERVALLO_MAX_SEC
    passo("sveglia", "il monitor esterno controlla almeno ogni %d minuti e non e' in pausa" % (MONITOR_INTERVALLO_MAX_SEC // 60),
          fitto and est.get("stato") != "pausa",
          ("intervallo %s s, stato %s" % (est.get("intervallo_sec"), est.get("stato"))) if est else "nessun monitor esterno")
    monitor_sveglio = fitto and est.get("stato") != "pausa" and buco_m is not None and buco_m <= MONITOR_BUCO_MAX_MIN \
        and ultimo_m is not None and ultimo_m <= MONITOR_ULTIMO_MAX_MIN
    passo("sveglia", "nelle ultime 24 ore i controlli del monitor non hanno buchi > %d minuti e l'ultimo ha meno di %d minuti"
          % (MONITOR_BUCO_MAX_MIN, MONITOR_ULTIMO_MAX_MIN), monitor_sveglio,
          "controlli nelle 24 ore: %d, buco massimo %s, ultimo %s" % (n24, ("%.0f min" % buco_m) if buco_m is not None else "-",
                                                                       ("%.0f min fa" % ultimo_m) if ultimo_m is not None else "-"))

    # I GIRI DI GITHUB: la seconda linea. Si stampano sempre; DECIDONO solo se il monitor esterno non c'e' o non e' sveglio.
    giri = list(letture.get("giri") or [])
    if con_guasto:
        giri = [dict(g, quando=(_quando(g["quando"]) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"), esito="success") for g in giri]
    tempi = sorted((_quando(g["quando"]) for g in giri), reverse=True)
    eta = (adesso - tempi[0]).total_seconds() / 60 if tempi else None
    n_giri, buco_max = _buco_massimo(tempi, adesso)
    github_sveglio = eta is not None and eta <= ULTIMO_MAX_MIN and buco_max is not None and buco_max <= BUCO_MAX_MIN
    passo("sveglia", "GitHub (seconda linea): ultimo giro entro %d minuti e buco massimo nelle 24 ore sotto i %d minuti%s"
          % (ULTIMO_MAX_MIN, BUCO_MAX_MIN, " — informativo, decide il monitor" if monitor_sveglio else " — DECIDE, perche' il monitor esterno manca o non e' sveglio"),
          github_sveglio or monitor_sveglio,
          "ultimo giro %s (%.0f minuti fa), giri nelle 24 ore: %d, buco massimo %.0f minuti"
          % (tempi[0].strftime("%Y-%m-%d %H:%M UTC") if tempi else "-", eta or -1, n_giri, buco_max or -1))
    verdi = sum(1 for g in giri if g.get("esito") == "success")
    rossi_recenti = sum(1 for g in giri if g.get("esito") == "failure")
    rossi = letture.get("rossi_totali")
    rossi = rossi if isinstance(rossi, int) else rossi_recenti
    if con_guasto:
        rossi = 0                                    # IL GUASTO 2: una sentinella che non ha mai gridato
    github_grida = verdi > 0 and rossi > 0
    monitor_grida = monitor_c_e and int(est.get("contatti_allarme") or 0) > 0 and int(est.get("giu_in_storia") or 0) > 0
    passo("grida", "il monitor esterno ha un contatto d'allarme e nella sua storia c'e' almeno un «giu'» (sa gridare)%s"
          % ("" if monitor_c_e else " — manca il monitor: decide GitHub"),
          monitor_grida or (not monitor_c_e and github_grida),
          ("contatti %s, giu' in storia %s" % (est.get("contatti_allarme"), est.get("giu_in_storia"))) if est else "nessun monitor esterno")
    passo("grida", "GitHub: nella storia c'e' almeno un giro VERDE e almeno un giro ROSSO (le due direzioni)%s"
          % (" — informativo" if monitor_grida else " — DECIDE"), github_grida or monitor_grida,
          "verdi (ultimi %d): %d, rossi in storia: %d" % (len(giri), verdi, rossi))
    up = letture.get("ultimo_push")
    giorni = (adesso - _quando(up)).days if up else None
    passo("non_scade", "GitHub: un push da meno di %d giorni (oltre, gli schedule si spengono)%s"
          % (INATTIVITA_MAX_GIORNI, " — informativo: il monitor esterno non scade" if monitor_sveglio else " — DECIDE"),
          (giorni is not None and giorni < INATTIVITA_MAX_GIORNI) or monitor_sveglio, "ultimo push %s (%s giorni)" % (up, giorni))


ADESSO_FINTO = datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc)


def monitor_finto(intervallo=300, ultimo=2, buco=5, n=288, stato="up", giu=1, contatti=1, url="https://" + SALUTE, salto=None):
    """Un monitor esterno come lo descrive `esterno`: n controlli ogni `buco` minuti, l'ultimo `ultimo` minuti fa;
    `salto=(da, minuti)` toglie i controlli fra `da` e `da+minuti` minuti fa (un buco)."""
    controlli = []
    for i in range(n):
        m = ultimo + i * buco
        if salto and salto[0] <= m <= salto[0] + salto[1]:
            continue
        controlli.append((ADESSO_FINTO - timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return {"servizio": "finto", "nome": "bookinvip salute", "url": url, "intervallo_sec": intervallo, "stato": stato,
            "controlli": sorted(controlli), "giu_in_storia": giu, "contatti_allarme": contatti}


def letture_finte(minuti_fa=5, buco=15, rossi=3, push_giorni=1, n=96, esterno="sano"):
    adesso = ADESSO_FINTO
    giri = [{"n": n - i, "evento": "schedule", "stato": "completed", "esito": "success",
             "quando": (adesso - timedelta(minutes=minuti_fa + i * buco)).strftime("%Y-%m-%dT%H:%M:%SZ")} for i in range(n)]
    let = {"adesso": adesso.strftime("%Y-%m-%dT%H:%M:%SZ"), "giri": giri, "rossi_totali": rossi,
           "ultimo_push": (adesso - timedelta(days=push_giorni)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if esterno == "sano":
        let["esterno"] = monitor_finto()
    elif isinstance(esterno, dict):
        let["esterno"] = esterno
    return let


def autoprova():
    oggi = dict(buco=333, n=8, minuti_fa=40)             # i giri di GitHub come misurati il 7/9: 7 al giorno, buchi di ore
    casi = [("GitHub fitto + monitor sano", letture_finte(), True),
            ("GitHub come oggi (buchi di 333 min) + monitor sano -> il monitor decide", letture_finte(esterno="sano", **oggi), True),
            ("GitHub come oggi, NESSUN monitor esterno", letture_finte(esterno=None, **oggi), False),
            ("GitHub fitto ma NESSUN monitor esterno", letture_finte(esterno=None), False),
            ("monitor ogni 10 minuti", letture_finte(esterno=monitor_finto(intervallo=600, buco=10, n=144), **oggi), False),
            ("monitor in pausa", letture_finte(esterno=monitor_finto(stato="pausa"), **oggi), False),
            ("monitor con un buco di 40 minuti stanotte", letture_finte(esterno=monitor_finto(salto=(300, 40)), **oggi), False),
            ("monitor il cui ultimo controllo e' di 30 minuti fa", letture_finte(esterno=monitor_finto(ultimo=30), **oggi), False),
            ("monitor senza contatto d'allarme", letture_finte(esterno=monitor_finto(contatti=0), **oggi), False),
            ("monitor che non e' mai andato giu' (e GitHub mai rosso)", letture_finte(esterno=monitor_finto(giu=0), rossi=0, **oggi), False),
            ("monitor su un altro indirizzo", letture_finte(esterno=monitor_finto(url="https://bookinvip.com/"), **oggi), False),
            ("ultimo giro GitHub di due ore fa, senza monitor", letture_finte(minuti_fa=120, esterno=None), False),
            ("giri GitHub ogni 5 ore, senza monitor", letture_finte(buco=300, n=8, esterno=None), False),
            ("mai un rosso GitHub in storia, senza monitor", letture_finte(rossi=0, esterno=None), False),
            ("repository fermo da 70 giorni, senza monitor", letture_finte(push_giorni=70, esterno=None), False),
            ("repository fermo da 70 giorni, CON monitor sano (non scade)", letture_finte(push_giorni=70), True),
            ("nessun giro e nessun monitor", {"adesso": "2026-09-07T18:00:00Z", "giri": [], "rossi_totali": 0, "ultimo_push": None}, False)]
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
        righe.append("   %-66s -> %-6s (atteso %-6s) den %d%s" % (nome, "VERDE" if verde else "ROSSO",
                                                                    "VERDE" if atteso else "ROSSO", den,
                                                                    "" if ok else "   ⛔ NON E' QUELLO CHE DOVEVA DIRE: %s" % "; ".join(motivi)[:160]))
    # il lettore della risposta di UptimeRobot, nelle due direzioni
    ts = int(ADESSO_FINTO.timestamp())
    risposta = {"stat": "ok", "monitors": [
        {"friendly_name": "altro", "url": "https://example.org/", "interval": 300, "status": 2, "response_times": [], "logs": []},
        {"friendly_name": "salute", "url": "https://" + SALUTE, "interval": 300, "status": 2,
         "response_times": [{"datetime": ts - 60 * i, "value": 120} for i in (2, 302, 602)] + [{"datetime": ts - 30 * 3600}],
         "logs": [{"type": 1, "datetime": ts - 86400}, {"type": 2, "datetime": ts - 86000}], "alert_contacts": [{"id": "1"}]}]}
    est = monitor_da_uptimerobot(risposta, ADESSO_FINTO)
    ok = (est is not None and est["url"].endswith(SALUTE) and est["intervallo_sec"] == 300 and est["stato"] == "up"
          and len(est["controlli"]) == 3 and est["giu_in_storia"] == 1 and est["contatti_allarme"] == 1
          and monitor_da_uptimerobot({"stat": "ok", "monitors": [risposta["monitors"][0]]}, ADESSO_FINTO) is None
          and monitor_da_uptimerobot({"stat": "ok", "monitors": [dict(risposta["monitors"][1], status=0)]}, ADESSO_FINTO)["stato"] == "pausa")
    riuscita = riuscita and ok
    righe.append("   %-66s -> %s" % ("il lettore della risposta di UptimeRobot (monitor giusto, 24 ore, pausa, assente)", "OK" if ok else "⛔ ROTTO"))
    del PASSI[:]
    return riuscita, righe


def precondizioni(con_rete=True, con_monitor=False):
    fuori = []
    if con_monitor:
        fuori.append(("la chiave di SOLA LETTURA del monitor e' nell'ambiente (%s), e non si stampa" % VARIABILE_CHIAVE,
                      bool(os.environ.get(VARIABILE_CHIAVE)), "presente" if os.environ.get(VARIABILE_CHIAVE) else "assente"))
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
    monitor = argv[argv.index("--monitor") + 1] if "--monitor" in argv and argv.index("--monitor") + 1 < len(argv) else None
    if monitor is not None and monitor != "uptimerobot":
        print("⛔ monitor sconosciuto: %s (valido: uptimerobot; per altri servizi usa --da-file col campo `esterno`)" % monitor)
        return 2
    tutte_ok, righe = precondizioni(con_rete=da_file is None, con_monitor=monitor is not None)
    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    for nome, ok, motivo in righe:
        print("  %-9s %-76s %s" % ("OK" if ok else "⛔ NO", nome, motivo))
    if not tutte_ok:
        print("VERDETTO: ⛔ FERMO — una precondizione non regge, quindi NON misuro e NON scrivo.")
        _stampa_non_guarda()
        return 2
    if con_guasto:
        print("⚠️  PASSATA COL GUASTO DENTRO: nessun monitor esterno; i giri di GitHub spostati indietro di tre giorni, tutti verdi")
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
        if monitor == "uptimerobot":
            letture["esterno"] = leggi_monitor(_quando(letture["adesso"]))
            est = letture["esterno"] or {}
            print("monitor esterno (UptimeRobot, chiave di sola lettura, mai stampata): %s"
                  % (("«%s» %s, intervallo %s s, stato %s, %d controlli nelle 24 ore" % (est.get("nome"), est.get("url"),
                      est.get("intervallo_sec"), est.get("stato"), len(est.get("controlli") or []))) if est
                     else "nessun monitor su %s in questo conto" % SALUTE))
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
