"""L'ESAME DELLA CASELLA 2 DEL BLOCCO 8 (INFRASTRUTTURA) — il deploy passa dal protocollo, mai a mano.

    python collaudi/esame_deploy.py --da-file F        giudica le LETTURE del VPS salvate in F (le fa B, sola lettura)
    python collaudi/esame_deploy.py --da-file F --scrivi   ... e SCRIVE nella scheda (anche un rosso, col motivo)
    python collaudi/esame_deploy.py                    senza letture: misura SOLO la parte «documento» (ROSSO: le
                                                       situazioni del VPS restano NON misurate, S7)
    python collaudi/esame_deploy.py --da-file F --con-guasto   storce le letture (paracadute uguale alla viva; uno
                                                       scambio senza punto di ritorno): deve gridare, NON scrive
                                                       (senza --da-file storce le letture FINTE dell'autoprova, e lo dice)
    python collaudi/esame_deploy.py --autoprova        il giudizio su letture costruite, nelle due direzioni

⛔ IL TESTO DELLA CASELLA NON SI RICOPIA: si legge da `collaudi/piano.py` (e' la chiave). ZERO rete e ZERO ssh da
   qui: le letture del server le produce B (formato JSON in `FORMATO_LETTURE`, sotto).

COSA MISURA, dichiarato (D18) — decisione della chat A il 2026-09-08 col mandato di B, rovesciabile.
  DOCUMENTO  DEPLOY.md e deploy/protocollo_d17.sh descrivono le STESSE tappe, e le giuste: il paracadute [1b]
             (`docker tag <viva> casavip-app:prec`, la prova che coincide, il file PRE_DEPLOY_*.commit), lo scambio
             rm-first (`git pull --ff-only`, build, stop, rm -f, up -d), la verifica (healthy, /api/health, i tre
             posti allineati) e il ritorno (`docker tag casavip-app:prec casavip-app:latest`); e in nessun blocco di
             comandi compare `docker-compose` col trattino (la v1 butta giu' nginx: DEPLOY.md §1).
  PULSANTE   il testo di /root/deploy_pulsante.sh (nelle letture) ha le stesse tappe (paracadute/scambio/verifica/
             indietro), riaggancia :prec e si ferma se non coincide, scrive PRE_DEPLOY, usa `docker compose` v2.
  TRACCE     ogni scambio registrato (/root/deploy_scambio_*.log) ha «SCAMBIO FATTO» con USCITA=0 e un PRE_DEPLOY_*.commit
             scritto PRIMA, nella stessa finestra (entro FINESTRA_MIN minuti); il paracadute di oggi (:prec) e'
             l'immagine che girava PRIMA dell'ultimo scambio (= la «viva» registrata dall'ultimo `prima`), ed e' DIVERSA
             dalla viva di oggi: il ritorno esiste ed e' l'ultimo stato buono precedente.
             ⚠️ Dichiarato: :prec NON deve coincidere con la viva di oggi fra un deploy e l'altro. Il protocollo lo
             riaggancia alla viva SOLO nel `prima` del deploy successivo (DEPLOY.md §3 [1b]: «prima del build»); se
             coincidesse adesso, il ritorno non esisterebbe (protocollo_d17.sh [2z]: «:latest e :prec COINCIDONO: il
             ritorno non esisterebbe. MI FERMO»).
  A_MANO     sul VPS `git status --porcelain` su fase*/main*/deploy/ e' vuoto, nessun commit esiste solo sul server
             (`git log origin/master..HEAD` = 0), HEAD del VPS e' un commit di origin/master, docker compose e' la v2
             e la v1 e' un segnaposto bloccato (apt candidate «(none)»).
Denominatore = passi. Senza letture, le tre situazioni del VPS sono NON MISURATE e la casella e' rossa (S7).

FORMATO_LETTURE (JSON, lo scrive B con sola lettura sul VPS; tempi in UTC «AAAA-MM-GGTHH:MM:SSZ», accettato anche
«+00:00»). Accanto a ogni campo, il comando di sola lettura che lo produce (proposta: B puo' cambiarlo, il valore no):
  {"adesso": ...,                                       date -u +%Y-%m-%dT%H:%M:%SZ
   "deploy_pulsante_sh": "<testo dello script>",        cat /root/deploy_pulsante.sh   (sha256sum accanto, in consegna)
   "scambi": [{"file": "/root/deploy_scambio_....log", "quando": ..., "scambio_fatto": true, "uscita": 0}],
        per ogni /root/deploy_scambio_*.log: quando = `date -u -r F +%Y-%m-%dT%H:%M:%SZ`; scambio_fatto = la riga
        «SCAMBIO FATTO» c'e'; uscita = il numero dopo «USCITA=» (assente -> null)
   "pulsante_scrive_uscita_dal": "2026-09-08T15:5x:xxZ",   (FACOLTATIVO) da quando il pulsante scrive «USCITA=» da se'
        (`trap 'echo "USCITA=$?"' EXIT`): mtime UTC del pulsante v2, o del v1 conservato. Un registro senza «USCITA=»
        PRECEDENTE a questa data, con «SCAMBIO FATTO» e `set -eu` nel pulsante, e' «riuscito per costruzione» (D12 A+B,
        2026-09-08); senza questo campo, o dopo, resta ROSSO.
   "pre_deploy": [{"file": "/root/PRE_DEPLOY_....commit", "quando": ..., "commit": "ae69c1f"}],
        per ogni /root/PRE_DEPLOY_*.commit: quando = mtime UTC come sopra; commit = `cat F`
   "paracadute": [{"quando": ..., "viva": "sha256:...", "prec_dopo": "sha256:..."}],
        dai registri del `prima`/paracadute (deploy_*_1_paracadute.log o l'uscita di protocollo_d17.sh prima):
        viva = la riga «immagine viva:», prec_dopo = la riga «:prec DOPO:»; quando = mtime UTC del registro
   "immagini": {"viva": "sha256:...", "prec": "sha256:...", "latest": "sha256:..."},
        docker inspect casavip_app --format '{{.Image}}' · docker inspect casavip-app:prec --format '{{.Id}}'
        · docker inspect casavip-app:latest --format '{{.Id}}'
   "git": {"status_porcelain_produzione": [], "commit_solo_sul_vps": 0, "head": "b51d74d", "head_in_origin_master": true},
        cd /var/www/bookinvip && git status --porcelain -- 'fase*.py' main_casavip.py deploy/   (le righe, una per voce)
        · git fetch -q origin && git rev-list --count origin/master..HEAD · git rev-parse --short HEAD
        · git merge-base --is-ancestor HEAD origin/master && echo true || echo false
   "compose": {"v2": "Docker Compose version v2.x", "v1_segnaposto": true, "v1_apt_candidate": "(none)"}}
        docker compose version · `head -c 200 /usr/local/bin/docker-compose` non e' un binario (e' il cartello di
        DEPLOY.md §1) · apt-cache policy docker-compose | grep Candidate  -> «(none)»
  ⚠️ Le letture si prendono A RIPOSO, non fra un `prima` e il suo `scambio`: in quella finestra (max un'ora, il
     gettone) :prec coincide con la viva per costruzione e l'esame direbbe ROSSO a ragione ma su uno stato transitorio.

⛔ D18: `precondizioni()` ferma il giro; `--autoprova` e `--con-guasto` (che non scrive mai); `NON_GUARDA`; guardia
   `test_pipeline_ci.TestLEsameDelDeployNonPuoBARARE`. `os.environ` non viene toccato.
"""
import io
import json
import os
import re
import sys
from datetime import datetime, timezone

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
MARCA = "protocollo D17"
COMANDO = "python collaudi/esame_deploy.py --da-file <letture> --scrivi"
SITUAZIONI = ("documento", "pulsante", "tracce", "a_mano")
FINESTRA_MIN = 180
TAPPE = ("paracadute", "scambio", "verifica", "indietro")
PASSI = []

NON_GUARDA = (
    "se il deploy di DOMANI passera' dal pulsante: qui si legge che ogni scambio REGISTRATO ha lasciato le tracce del "
    "protocollo; un deploy fatto a mano che non scrive nessun log e' invisibile per costruzione, e lo si vede da "
    "`git status` del VPS e da un HEAD fuori da origin/master (misurati)",
    "se le tappe del pulsante FUNZIONINO: qui si legge il testo dello script; il funzionamento lo prova ogni deploy "
    "(le tracce) e la prova del ritorno (`indietro`) non viene eseguita da questo esame",
    "le letture stesse: le fa B con ssh in sola lettura; qui si giudica il file che B consegna, con l'ora accanto",
    "il salvataggio prima del deploy (backup verificato leggibile): e' la casella 1 del blocco (esame_backup)",
    "lo stato fra un `prima` e il suo `scambio` (:prec == viva per costruzione, al massimo un'ora): le letture si "
    "prendono a riposo, e l'ora «adesso» delle letture sta accanto al verdetto",
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


def _leggi(nome):
    with io.open(os.path.join(RADICE, nome), encoding="utf-8", errors="replace") as f:
        return f.read()


def _quando(iso):
    """«AAAA-MM-GGTHH:MM:SSZ» o con «+00:00»; un tempo senza fuso e' UTC. Un tempo illeggibile fa esplodere la misura
    (che diventa un rosso, non un silenzio)."""
    q = datetime.fromisoformat(str(iso).strip().replace("Z", "+00:00"))
    return q if q.tzinfo else q.replace(tzinfo=timezone.utc)


def blocchi_di_comandi(markdown):
    return "\n".join(re.findall(r"```(?:bash|sh)?\n(.*?)```", markdown, re.S))


def compose_v1_nei_comandi(testo):
    """Le righe che INVOCANO `docker-compose` col trattino (non il nome del file .yml)."""
    return [r.strip() for r in testo.splitlines() if re.match(r"^\s*(sudo\s+)?docker-compose\s", r)]


# ---- DOCUMENTO ----
def misura_documento():
    print("\n--- DOCUMENTO: DEPLOY.md e deploy/protocollo_d17.sh dicono le stesse tappe, e le giuste ---")
    md = _leggi("DEPLOY.md")
    cmd = blocchi_di_comandi(md)
    sh = _leggi(os.path.join("deploy", "protocollo_d17.sh"))
    passo("documento", "DEPLOY.md §3 [1b]: il paracadute si aggancia alla viva, si prova che coincide, si scrive PRE_DEPLOY",
          "docker tag \"$VIVA\" casavip-app:prec" in cmd and "casavip-app:prec --format" in cmd and "PRE_DEPLOY_" in cmd)
    passo("documento", "DEPLOY.md §3: lo scambio e' rm-first (pull --ff-only, build, stop, rm -f, up -d) in quest'ordine",
          all(x in cmd for x in ("git pull --ff-only", "build app", "stop app", "rm -f app", "up -d"))
          and cmd.find("git pull --ff-only") < cmd.find("build app") < cmd.find("stop app") < cmd.find("rm -f app"))
    passo("documento", "DEPLOY.md §4: la verifica guarda i container healthy, /api/health e i tre posti allineati",
          "healthy" in md and "/api/health" in cmd and "rev-parse --short origin/master" in cmd)
    passo("documento", "DEPLOY.md: il ritorno e' `docker tag casavip-app:prec casavip-app:latest`",
          "docker tag casavip-app:prec casavip-app:latest" in cmd)
    v1 = compose_v1_nei_comandi(cmd)
    passo("documento", "DEPLOY.md: nessun blocco di comandi invoca `docker-compose` col trattino (v1)", not v1, repr(v1[:3]))
    passo("documento", "deploy/protocollo_d17.sh ha le fasi prima/scambio/dopo, riaggancia :prec e si ferma se non coincide",
          all(x in sh for x in ('"prima"', '"scambio"', '"dopo"', "docker tag \"$VIVA\" casavip-app:prec",
                                "NON coincide", "PRE_DEPLOY_")))
    passo("documento", "deploy/protocollo_d17.sh: scambio pretende la prova che `prima` sia stata fatta, e :prec != :latest",
          "COINCIDONO" in sh and "[2z]" in sh)
    passo("documento", "deploy/protocollo_d17.sh: nessuna riga invoca `docker-compose` col trattino",
          not compose_v1_nei_comandi(sh))


# ---- PULSANTE / TRACCE / A_MANO (dalle letture del VPS) ----
def misura_pulsante(let):
    print("\n--- PULSANTE: il testo di /root/deploy_pulsante.sh (dalle letture) ---")
    sh = let.get("deploy_pulsante_sh") or ""
    passo("pulsante", "lo script del pulsante e' nelle letture", bool(sh.strip()), "%d caratteri" % len(sh))
    for t in TAPPE:
        passo("pulsante", "il pulsante ha la tappa «%s»" % t, re.search(r"\b%s\b" % t, sh) is not None)
    passo("pulsante", "il pulsante riaggancia :prec alla viva e si ferma se non coincide",
          "casavip-app:prec" in sh and "docker tag" in sh and re.search(r"exit 1|MI FERMO|NON PROCEDERE", sh) is not None)
    passo("pulsante", "il pulsante scrive il punto di ritorno PRE_DEPLOY_*.commit", "PRE_DEPLOY_" in sh)
    passo("pulsante", "il pulsante usa `docker compose` (v2) e mai `docker-compose`",
          "docker compose" in sh and not compose_v1_nei_comandi(sh))


def misura_tracce(let, con_guasto=False):
    print("\n--- TRACCE: ogni scambio ha il suo punto di ritorno; il paracadute e' l'ultimo stato buono precedente ---")
    scambi = list(let.get("scambi") or [])
    pre = list(let.get("pre_deploy") or [])
    if con_guasto and scambi:
        scambi = scambi + [{"file": "/root/deploy_scambio_guasto.log", "quando": "2026-01-01T00:00:00Z",
                            "scambio_fatto": True, "uscita": 0}]                      # IL GUASTO 2: senza PRE_DEPLOY
    passo("tracce", "c'e' almeno uno scambio registrato", len(scambi) > 0, "%d scambi, %d punti di ritorno" % (len(scambi), len(pre)))
    # I REGISTRI STORICI SENZA RIGA «USCITA=» (deciso fra A e B il 2026-09-08, D12): fino all'8/9 il pulsante non scriveva
    # da se' il codice d'uscita (lo faceva chi lo lanciava, e due volte non l'ha fatto). Un registro SENZA «USCITA=» e'
    # «riuscito per costruzione» SOLO se (1) ha «SCAMBIO FATTO», (2) il pulsante ha `set -eu` (quella riga e' l'ultima del
    # ramo e non si stampa dopo un errore) e (3) e' PRECEDENTE a `pulsante_scrive_uscita_dal` (la data da cui il pulsante
    # la scrive da solo, nelle letture). Senza quella data, o dopo, un registro senza USCITA resta ROSSO: un numero non
    # misurato non si scrive a posteriori (D22), e chi lo lancia ora non ha piu' scuse. Il conteggio sta nel passo.
    sh = let.get("deploy_pulsante_sh") or ""
    dal = let.get("pulsante_scrive_uscita_dal")
    dal_q = _quando(dal) if dal else None
    storici = 0
    for s in scambi:
        q = _quando(s["quando"])
        nome = os.path.basename(str(s.get("file")))
        if s.get("uscita") is None and s.get("scambio_fatto") is True and "set -eu" in sh and dal_q is not None and q < dal_q:
            storici += 1
            passo("tracce", "%s: «SCAMBIO FATTO», riuscito PER COSTRUZIONE senza codice d'uscita (registro del %s, prima che il "
                  "pulsante lo scrivesse da se', %s)" % (nome, q.strftime("%Y-%m-%d"), dal), True, "set -eu nel pulsante")
        else:
            passo("tracce", "%s: «SCAMBIO FATTO» con USCITA=0" % nome,
                  s.get("scambio_fatto") is True and s.get("uscita") == 0,
                  "uscita=%r%s" % (s.get("uscita"), "" if s.get("uscita") is not None or dal else
                                   " (nessuna riga USCITA e nessun `pulsante_scrive_uscita_dal` nelle letture)"))
        finestra = [p for p in pre if 0 <= (q - _quando(p["quando"])).total_seconds() <= FINESTRA_MIN * 60]
        passo("tracce", "%s: un PRE_DEPLOY_*.commit scritto PRIMA, entro %d minuti" % (nome, FINESTRA_MIN),
              bool(finestra), ", ".join(os.path.basename(str(p["file"])) for p in finestra) or "nessuno")
    if storici:
        passo("tracce", "registri storici riusciti per costruzione, senza codice d'uscita: %d su %d (dichiarato)" % (storici, len(scambi)), True)
    imm = let.get("immagini") or {}
    para = sorted(let.get("paracadute") or [], key=lambda p: p.get("quando") or "")
    ultimo = para[-1] if para else {}
    prec = imm.get("prec")
    if con_guasto:
        prec = imm.get("viva")                                                      # IL GUASTO 1: nessun ritorno
    passo("tracce", ":prec di oggi == l'immagine che girava PRIMA dell'ultimo scambio (la «viva» dell'ultimo `prima`)",
          bool(prec) and prec == ultimo.get("viva") == ultimo.get("prec_dopo"),
          "prec=%s viva_di_prima=%s" % (str(prec)[:19], str(ultimo.get("viva"))[:19]))
    passo("tracce", ":prec e' DIVERSA dalla viva di oggi (il ritorno esiste)", bool(prec) and bool(imm.get("viva")) and prec != imm.get("viva"),
          "prec=%s viva=%s" % (str(prec)[:19], str(imm.get("viva"))[:19]))
    passo("tracce", ":latest e' la viva di oggi", bool(imm.get("latest")) and imm.get("latest") == imm.get("viva"))


def misura_a_mano(let):
    print("\n--- A MANO: niente modifiche fuori git sul server, nessun commit solo sul VPS, compose v2 ---")
    g = let.get("git") or {}
    c = let.get("compose") or {}
    sporchi = [r for r in (g.get("status_porcelain_produzione") or []) if r]
    passo("a_mano", "sul VPS `git status --porcelain` su fase*/main*/deploy/ e' vuoto", not sporchi, repr(sporchi[:5]))
    passo("a_mano", "nessun commit esiste solo sul VPS (git log origin/master..HEAD = 0)", g.get("commit_solo_sul_vps") == 0,
          "commit_solo_sul_vps=%r" % (g.get("commit_solo_sul_vps"),))
    passo("a_mano", "HEAD del VPS e' un commit di origin/master", g.get("head_in_origin_master") is True and bool(g.get("head")),
          "head=%r" % (g.get("head"),))
    passo("a_mano", "docker compose e' la v2", str(c.get("v2") or "").startswith("Docker Compose version v2"), repr(c.get("v2")))
    passo("a_mano", "docker-compose v1 e' un segnaposto bloccato (apt candidate «(none)»)",
          c.get("v1_segnaposto") is True and str(c.get("v1_apt_candidate")) == "(none)",
          "segnaposto=%r apt=%r" % (c.get("v1_segnaposto"), c.get("v1_apt_candidate")))


def letture_finte(**k):
    let = {"adesso": "2026-09-08T16:00:00Z",
           "deploy_pulsante_sh": "#!/bin/sh\ncase \"$1\" in\n paracadute) VIVA=$(docker inspect casavip_app --format '{{.Image}}'); "
                                 "docker tag \"$VIVA\" casavip-app:prec || exit 1; echo x > /root/PRE_DEPLOY_$TS.commit;;\n"
                                 " scambio) docker compose -f docker-compose.casavip.yml build app;;\n verifica) curl /api/health;;\n"
                                 " indietro) docker tag casavip-app:prec casavip-app:latest;;\nesac\n",
           "scambi": [{"file": "/root/deploy_scambio_20260907_151200.log", "quando": "2026-09-07T15:12:00Z", "scambio_fatto": True, "uscita": 0}],
           "pre_deploy": [{"file": "/root/PRE_DEPLOY_20260907_150900.commit", "quando": "2026-09-07T15:09:00Z", "commit": "ae69c1f"}],
           "paracadute": [{"quando": "2026-09-07T15:09:00Z", "viva": "sha256:aaa", "prec_dopo": "sha256:aaa"}],
           "immagini": {"viva": "sha256:bbb", "prec": "sha256:aaa", "latest": "sha256:bbb"},
           "git": {"status_porcelain_produzione": [], "commit_solo_sul_vps": 0, "head": "b51d74d", "head_in_origin_master": True},
           "compose": {"v2": "Docker Compose version v2.29.0", "v1_segnaposto": True, "v1_apt_candidate": "(none)"}}
    for chiave, valore in k.items():
        a, _, b = chiave.partition("__")
        if b:
            let[a][b] = valore
        else:
            let[a] = valore
    return let


def misura_tutto(let, con_guasto=False):
    """Documento sempre; pulsante/tracce/a_mano solo con le letture. Una misura che esplode e' un ROSSO, non un
    silenzio (S7): l'eccezione diventa un passo rosso col suo nome."""
    try:
        misura_documento()
        if let is not None:
            misura_pulsante(let)
            misura_tracce(let, con_guasto)
            misura_a_mano(let)
        else:
            print("\n(nessuna lettura del VPS: --da-file assente -> pulsante, tracce e a_mano restano NON misurate)")
    except Exception as e:                                        # noqa: BLE001 - una misura rotta e' un rosso
        passo("documento", "la misura e' ESPLOSA", False, "%s: %s" % (type(e).__name__, e))


def autoprova():
    casi = [("letture sane", letture_finte(), True),
            ("letture sane, tempi scritti con +00:00", letture_finte(scambi=[{"file": "/root/deploy_scambio_x.log", "quando": "2026-09-07T15:12:00+00:00", "scambio_fatto": True, "uscita": 0}]), True),
            ("scambio senza punto di ritorno nella finestra", letture_finte(pre_deploy=[]), False),
            ("scambio con un tempo illeggibile", letture_finte(scambi=[{"file": "x.log", "quando": "ieri", "scambio_fatto": True, "uscita": 0}]), False),
            ("scambio con USCITA=1", letture_finte(scambi=[{"file": "x.log", "quando": "2026-09-07T15:12:00Z", "scambio_fatto": False, "uscita": 1}]), False),
            ("registro STORICO senza USCITA, prima della data in cui il pulsante la scrive (set -eu): per costruzione",
             letture_finte(scambi=[{"file": "/root/deploy_scambio_vecchio.log", "quando": "2026-09-07T15:12:00Z", "scambio_fatto": True, "uscita": None}],
                           pulsante_scrive_uscita_dal="2026-09-08T15:50:00Z",
                           deploy_pulsante_sh="#!/bin/sh\nset -eu\ncase \"$1\" in\n paracadute) VIVA=$(docker inspect casavip_app --format '{{.Image}}'); "
                                              "docker tag \"$VIVA\" casavip-app:prec || exit 1; echo x > /root/PRE_DEPLOY_$TS.commit;;\n"
                                              " scambio) docker compose -f docker-compose.casavip.yml build app;;\n verifica) curl /api/health;;\n"
                                              " indietro) docker tag casavip-app:prec casavip-app:latest;;\nesac\n"), True),
            ("registro NUOVO senza USCITA, dopo quella data", letture_finte(scambi=[{"file": "/root/deploy_scambio_nuovo.log", "quando": "2026-09-09T10:00:00Z", "scambio_fatto": True, "uscita": None}],
                                                                             pre_deploy=[{"file": "/root/PRE_DEPLOY_20260909_095800.commit", "quando": "2026-09-09T09:58:00Z", "commit": "ae69c1f"}],
                                                                             pulsante_scrive_uscita_dal="2026-09-08T15:50:00Z"), False),
            ("registro senza USCITA e SENZA la data nelle letture", letture_finte(scambi=[{"file": "/root/deploy_scambio_vecchio.log", "quando": "2026-09-07T15:12:00Z", "scambio_fatto": True, "uscita": None}]), False),
            ("registro storico senza USCITA ma il pulsante senza set -eu", letture_finte(scambi=[{"file": "/root/deploy_scambio_vecchio.log", "quando": "2026-09-07T15:12:00Z", "scambio_fatto": True, "uscita": None}],
                                                                                          pulsante_scrive_uscita_dal="2026-09-08T15:50:00Z"), False),
            (":prec uguale alla viva (nessun ritorno)", letture_finte(immagini__prec="sha256:bbb"), False),
            (":prec che non e' la viva di prima", letture_finte(immagini__prec="sha256:ccc"), False),
            ("file di produzione modificato fuori git", letture_finte(git__status_porcelain_produzione=[" M fase83_server.py"]), False),
            ("un commit solo sul VPS", letture_finte(git__commit_solo_sul_vps=1), False),
            ("docker-compose v1 installato", letture_finte(compose__v1_apt_candidate="1.29.2-1"), False),
            ("pulsante senza la tappa indietro", letture_finte(deploy_pulsante_sh="paracadute scambio verifica docker tag casavip-app:prec exit 1 PRE_DEPLOY_ docker compose"), False),
            ("nessuna lettura del VPS", None, False)]
    righe, riuscita = [], True
    for nome, let, atteso in casi:
        del PASSI[:]
        flusso, vero = io.StringIO(), sys.stdout
        sys.stdout = flusso
        try:
            misura_tutto(let)
        finally:
            sys.stdout = vero
        verde, motivi, den = giudica(PASSI)
        ok = verde == atteso
        riuscita = riuscita and ok
        righe.append("   %-46s -> %-6s (atteso %-6s) den %d%s" % (nome, "VERDE" if verde else "ROSSO", "VERDE" if atteso else "ROSSO", den,
                                                                    "" if ok else "   ⛔ NON E' QUELLO CHE DOVEVA DIRE: %s" % "; ".join(motivi)[:160]))
    ok = compose_v1_nei_comandi("docker-compose up -d\n  sudo docker-compose ps\ndocker compose -f docker-compose.casavip.yml up -d\n") == \
        ["docker-compose up -d", "sudo docker-compose ps"]
    riuscita = riuscita and ok
    righe.append("   %-46s -> %s" % ("il lettore delle invocazioni v1 (due direzioni)", "OK" if ok else "⛔ ROTTO"))
    del PASSI[:]
    return riuscita, righe


def precondizioni():
    fuori = []
    try:
        testo = " ".join(str(condizione()).split())
        fuori.append(("la casella esiste nel piano, una sola, e parla del deploy a mano", "a mano" in testo, testo[:70]))
    except Exception as e:
        fuori.append(("la casella esiste nel piano, una sola", False, str(e)))
    try:
        impronta = scheda.impronta_del_blocco(BLOCCO)
        fuori.append(("il blocco ha un'impronta", bool(impronta), impronta or "il piano non si legge"))
    except Exception as e:
        fuori.append(("il blocco ha un'impronta", False, str(e)))
    for nome in ("DEPLOY.md", os.path.join("deploy", "protocollo_d17.sh")):
        fuori.append(("%s esiste" % nome, os.path.isfile(os.path.join(RADICE, nome)), ""))
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
    print("🧾 ESAME DEL BLOCCO 8 — casella 2: il deploy passa dal protocollo, mai a mano")
    print("=" * 86)
    if "--autoprova" in argv:
        print("🔁 AUTOPROVA — il giudizio su letture costruite, nelle due direzioni (D18 punto 2)")
        riuscita, righe = autoprova()
        for r in righe:
            print(r)
        _stampa_non_guarda()
        print("=" * 86)
        print("VERDETTO: %s" % ("✅ il giudizio grida sui deploy a mano e tace su quelli dal pulsante" if riuscita
                                else "⛔ IL GIUDIZIO NON E' AFFIDABILE"))
        return 0 if riuscita else 1
    con_guasto = "--con-guasto" in argv
    if con_guasto and "--scrivi" in argv:
        print("⛔ FERMO: `--con-guasto` non scrive. Serve a vedere l'esame gridare; registrare quel")
        print("   rosso metterebbe nella scheda un paracadute rotto apposta.")
        return 2
    tutte_ok, righe = precondizioni()
    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    for nome, ok, motivo in righe:
        print("  %-9s %-76s %s" % ("OK" if ok else "⛔ NO", nome, motivo))
    if not tutte_ok:
        print("VERDETTO: ⛔ FERMO — una precondizione non regge, quindi NON misuro e NON scrivo.")
        _stampa_non_guarda()
        return 2
    if con_guasto:
        print("⚠️  PASSATA COI GUASTI DENTRO: :prec uguale alla viva; uno scambio senza punto di ritorno")
    da_file = argv[argv.index("--da-file") + 1] if "--da-file" in argv else None
    ambiente_prima = dict(os.environ)
    let = None
    if da_file:
        try:
            with io.open(da_file, encoding="utf-8") as f:
                let = json.load(f)
            print("letture del VPS: %s (adesso=%s)" % (da_file, let.get("adesso")))
        except Exception as e:                                    # noqa: BLE001 - un file illeggibile e' un rosso
            passo("documento", "le letture del VPS si leggono (%s)" % da_file, False, "%s: %s" % (type(e).__name__, e))
    elif con_guasto:
        let = letture_finte()
        print("letture FINTE dell'autoprova (--da-file assente): il guasto si vede lo stesso, ma NON e' il VPS")
    misura_tutto(let, con_guasto)
    passo("documento", "l'ambiente (os.environ) e' identico a prima della misura", dict(os.environ) == ambiente_prima)
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
