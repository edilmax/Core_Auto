"""L'ESAME DELLA CASELLA 6 DEL BLOCCO SOLDI — «gli invarianti sono verificati in PRODUZIONE».

    python collaudi/esame_produzione.py                 legge il server VIVO, misura e MOSTRA
    python collaudi/esame_produzione.py --scrivi        misura e SCRIVE nella scheda (anche un
                                                        rosso, col suo motivo)
    python collaudi/esame_produzione.py --salva F       oltre a misurare, salva le letture in F
    python collaudi/esame_produzione.py --da-file F     giudica letture salvate (niente rete)
    python collaudi/esame_produzione.py --con-guasto    storce le letture (una violazione):
                                                        deve gridare, e NON scrive mai
    python collaudi/esame_produzione.py --autoprova     si vede gridare e tacere, senza rete
                                                        (D18 punto 2)

⛔ IL TESTO DELLA CASELLA NON SI RICOPIA: si legge da `collaudi/piano.py` (e' la chiave della
   scheda; una copia a mano spunterebbe una casella diversa il giorno che il piano cambia).

COSA MISURA, e da dove (tutto letto dal server vivo, niente e' dedotto dal codice sul computer):
  1. `/api/health` risponde 200, `status ok`, e `guardiano ok`: il battito quotidiano del
     Guardiano dei soldi e' vivo (lo misura il server stesso: fase178, tetto 25 ore);
  2. nel registro del container vivo (`docker logs casavip_app`, ultime 26 ore) c'e' la riga
     `INVARIANTI ARCHIVI` scritta da `fase202` -- il giro quotidiano che verifica i cinque
     invarianti di `fase199` sugli archivi veri -- ed e' piu' giovane di 25 ore;
  3. quella riga dice: verificati TUTTI e cinque (I1..I5), `violazioni=0`, `non_eseguiti=0`,
     `ciechi=0`; e il giro del Guardiano che la contiene e' finito «nessuno stato anomalo»;
  4. il codice che gira sul server e' quello di `master` (HEAD del VPS == `origin/master`):
     una misura fatta su un altro commit non parlerebbe di questo codice.
  Il denominatore e' 5 (gli invarianti) + i passi sopra: la scheda sa su quante cose ha guardato.

⛔ D18, LE QUATTRO CONDIZIONI DI UNO STRUMENTO CHE MISURA:
   1. misura PRIMA se stesso (`precondizioni`): senza chiave SSH, senza `ssh`, senza piano si
      FERMA e non scrive;
   2. provato nelle DUE direzioni: `--autoprova` lo vede gridare su letture storte (una
      violazione, una riga vecchia di 26 ore, quattro invarianti su cinque, battito muto) e
      tacere su letture sane -- senza rete, con letture costruite;
   3. dichiara cosa NON ha esaminato: `NON_GUARDA`, stampato a ogni giro;
   4. e' sotto guardia: `test_pipeline_ci.TestLEsameDellaProduzioneNonPuoBARARE`.

⛔ NIENTE SEGRETI: la chiave SSH resta nel suo file (si passa a `ssh -i`), nessun token viene
   letto ne' stampato; l'API della salute e' pubblica.
"""
import calendar
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

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
from fase202_invarianti_archivi import CODICI, MARCA  # noqa: E402
from fase178_watchdog import MAX_ETA_BATTITO_SEC  # noqa: E402

BLOCCO_SOLDI = 1
INDICE_CASELLA = 5                       # la sesta casella del blocco (0-based)
COMANDO = "python collaudi/esame_produzione.py --scrivi"
SALUTE = os.environ.get("BOOKINVIP_SALUTE", "https://bookinvip.com/api/health")
VPS = os.environ.get("BOOKINVIP_VPS", "root@76.13.44.167")
CHIAVE_SSH = os.environ.get("BOOKINVIP_CHIAVE_SSH",
                            os.path.join(os.path.expanduser("~"), ".ssh", "id_ed25519"))
CARTELLA_VPS = "/var/www/bookinvip"
CONTENITORE = "casavip_app"
FINESTRA_REGISTRO = "26h"                 # si legge un po' oltre il tetto, per vedere la riga vecchia
MAX_ETA_SEC = MAX_ETA_BATTITO_SEC         # 25 ore: lo stesso tetto del battito (fase178)
RIGA = re.compile(re.escape(MARCA) + r" \| verificati=(\S+) \| letti=(.*?) \| violazioni=(\d+)"
                  r" \| non_eseguiti=(\d+) \| ciechi=(\d+)")
GUARDIANO_PULITO = "GUARDIANO: nessuno stato anomalo"
SEGNA_REGISTRO, SEGNA_HEAD = "@@REGISTRO@@", "@@HEAD@@"

NON_GUARDA = (
    "che i cinque invarianti siano quelli GIUSTI: qui si legge che il server li ha verificati "
    "sugli archivi veri e non ha trovato violazioni; la bonta' delle formule la provano Z3 e "
    "Hypothesis nei test (casella 1)",
    "gli archivi con un nome che fase202 non riconosce (legge `pendenti`, `inventario`, "
    "`garanzia`, `payout`, `libro_giornale` e ogni colonna `*_cents`): un archivio nuovo non "
    "entra nel giro finche' non viene nominato li'",
    "le prenotazioni «paga in struttura» per I2: il saldo non passa da noi e il giornale non "
    "puo' contenerlo; il server le conta fra i NON ESEGUITI, e qui `non_eseguiti=0` e' una "
    "condizione: se un giorno ce ne sara' una, questa casella diventa rossa e lo dice",
    "quante prenotazioni c'erano negli archivi: `letti=` e' stampato ma non e' una condizione. "
    "Un prodotto con zero prenotazioni ha invarianti verificati su zero righe, ed e' la verita'",
    "il bottone manuale del bunker (`/api/bunker/invarianti`, solo I1): resta com'e', non e' "
    "il giro quotidiano",
    "le altre cinque caselle del blocco: non le tocca",
)


# --------------------------------------------------------------------------------------
# 1. LE LETTURE DAL VIVO (l'unica parte che tocca la rete)
# --------------------------------------------------------------------------------------
def _salute():
    try:
        with urllib.request.urlopen(SALUTE, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return 0, {"_errore": "%s: %s" % (type(e).__name__, e)}


def _ssh(comando):
    esito = subprocess.run(["ssh", "-i", CHIAVE_SSH, "-o", "IdentitiesOnly=yes",
                            "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", VPS, comando],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    return esito.returncode, esito.stdout.decode("utf-8", "replace")


def letture_dal_vivo():
    """Un dizionario con tutto cio' che il giudizio guarda. Tre letture: la salute (HTTP),
    il registro + HEAD del server (UNA sessione SSH), master su GitHub (git, dal computer)."""
    http, corpo = _salute()
    comando = ("echo %s; docker logs %s --since %s -t 2>&1 | grep -E %s; echo %s; "
               "git -C %s rev-parse HEAD"
               % (SEGNA_REGISTRO, CONTENITORE, FINESTRA_REGISTRO,
                  "'%s|GUARDIANO:'" % MARCA, SEGNA_HEAD, CARTELLA_VPS))
    try:
        uscita_ssh, testo = _ssh(comando)
    except Exception as e:
        uscita_ssh, testo = -1, "%s: %s" % (type(e).__name__, e)
    registro, head = "", ""
    if SEGNA_REGISTRO in testo and SEGNA_HEAD in testo:
        registro = testo.split(SEGNA_REGISTRO, 1)[1].split(SEGNA_HEAD, 1)[0].strip()
        head = testo.split(SEGNA_HEAD, 1)[1].strip().splitlines()[0].strip() if \
            testo.split(SEGNA_HEAD, 1)[1].strip() else ""
    try:
        g = subprocess.run(["git", "ls-remote", "origin", "refs/heads/master"], cwd=RADICE,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        master = g.stdout.decode("utf-8", "replace").split("\t", 1)[0].strip()
    except Exception:
        master = ""
    return {"ora": int(time.time()), "salute_http": http, "salute": corpo,
            "registro": registro, "uscita_ssh": uscita_ssh, "vps_head": head, "master": master}


# --------------------------------------------------------------------------------------
# 2. IL GIUDIZIO (puro: riceve letture, rende passi)
# --------------------------------------------------------------------------------------
def _istante(riga):
    """L'istante di una riga di `docker logs -t` (RFC 3339, UTC). None se non si legge."""
    try:
        return calendar.timegm(time.strptime(riga[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return None


def _ultima_riga_invarianti(registro):
    """(indice, istante, campi) dell'ULTIMA riga INVARIANTI ARCHIVI, o (None, None, None)."""
    righe = (registro or "").splitlines()
    for i in range(len(righe) - 1, -1, -1):
        m = RIGA.search(righe[i])
        if m:
            return i, _istante(righe[i]), {"verificati": m.group(1).split(","),
                                            "letti": m.group(2), "violazioni": int(m.group(3)),
                                            "non_eseguiti": int(m.group(4)),
                                            "ciechi": int(m.group(5))}
    return None, None, None


def giudica(letture, ora=None):
    """(verde, passi, motivi, denominatore). Ogni passo e' (nome, ok, dettaglio)."""
    ora = int(letture.get("ora") or 0) if ora is None else int(ora)
    passi = []

    def passo(nome, ok, dettaglio=""):
        passi.append((nome, bool(ok), dettaglio))

    http, sal = letture.get("salute_http"), letture.get("salute") or {}
    passo("/api/health risponde 200 con status ok", http == 200 and sal.get("status") == "ok",
          "http=%s status=%s %s" % (http, sal.get("status"), sal.get("_errore", "")))
    passo("il battito quotidiano del Guardiano e' vivo (guardiano=ok, tetto 25 h)",
          sal.get("guardiano") == "ok", "guardiano=%s" % sal.get("guardiano"))

    registro = letture.get("registro") or ""
    indice, quando, campi = _ultima_riga_invarianti(registro)
    eta = (ora - quando) if (quando is not None) else None
    passo("il registro del server ha la riga %s, piu' giovane di 25 h" % MARCA,
          campi is not None and eta is not None and 0 <= eta <= MAX_ETA_SEC,
          ("eta %d s (%.1f h)" % (eta, eta / 3600.0)) if eta is not None else
          ("nessuna riga %s nelle ultime %s del registro" % (MARCA, FINESTRA_REGISTRO)
           if campi is None else "riga senza istante leggibile"))
    if campi is None:
        campi = {"verificati": [], "violazioni": -1, "non_eseguiti": -1, "ciechi": -1,
                 "letti": ""}
    passo("il giro ha verificato TUTTI e cinque gli invarianti (%s)" % ",".join(CODICI),
          list(campi["verificati"]) == list(CODICI), "verificati=%s" % ",".join(campi["verificati"]))
    passo("violazioni=0", campi["violazioni"] == 0, "violazioni=%s" % campi["violazioni"])
    passo("non_eseguiti=0 (nessun invariante saltato)", campi["non_eseguiti"] == 0,
          "non_eseguiti=%s" % campi["non_eseguiti"])
    passo("ciechi=0 (ogni archivio si e' letto)", campi["ciechi"] == 0, "ciechi=%s" % campi["ciechi"])
    dopo = registro.splitlines()[indice + 1:] if indice is not None else []
    guard = [r for r in dopo if "GUARDIANO:" in r]
    passo("il giro del Guardiano che la contiene e' finito pulito (%s)" % GUARDIANO_PULITO,
          bool(guard) and GUARDIANO_PULITO in guard[0],
          guard[0][guard[0].find("GUARDIANO:"):][:100] if guard else "nessuna riga GUARDIANO dopo quella")
    head, master = letture.get("vps_head") or "", letture.get("master") or ""
    passo("il codice in produzione e' master (HEAD del VPS == origin/master)",
          bool(head) and len(head) >= 7 and head == master,
          "vps=%s master=%s" % (head[:12] or "?", master[:12] or "?"))

    motivi = ["%s (%s)" % (n, d) if d else n for n, ok, d in passi if not ok]
    verde = not motivi
    denominatore = len(CODICI) + len(passi)
    return verde, passi, motivi, denominatore


# --------------------------------------------------------------------------------------
# 3. MISURA PRIMA SE STESSO (D18 punto 1)
# --------------------------------------------------------------------------------------
def precondizioni(con_rete=True):
    fuori = []
    try:
        blocco = [b for b in BLOCCHI if b["ordine"] == BLOCCO_SOLDI]
        cond = blocco[0]["finito_quando"] if len(blocco) == 1 else ()
        fuori.append(("la casella esiste nel piano", len(cond) > INDICE_CASELLA,
                      " ".join(str(cond[INDICE_CASELLA]).split())[:70] if len(cond) > INDICE_CASELLA
                      else "il blocco dei soldi non ha una sesta casella"))
    except Exception as e:
        fuori.append(("la casella esiste nel piano", False, "%s: %s" % (type(e).__name__, e)))
    try:
        impronta = scheda.impronta_del_blocco(BLOCCO_SOLDI)
        fuori.append(("il blocco ha un'impronta", bool(impronta),
                      impronta or "il piano non si legge: una misura senza ancoraggio non vale"))
    except Exception as e:
        fuori.append(("il blocco ha un'impronta", False, str(e)))
    fuori.append(("la riga del registro e' riconoscibile (regex e marca di fase202 d'accordo)",
                  RIGA.search("%s | verificati=I1,I2,I3,I4,I5 | letti=a:1 | violazioni=0 | "
                              "non_eseguiti=0 | ciechi=0" % MARCA) is not None, MARCA))
    if con_rete:
        import shutil
        fuori.append(("la chiave SSH esiste (non si legge, non si stampa)",
                      os.path.isfile(CHIAVE_SSH), CHIAVE_SSH))
        fuori.append(("`ssh` e' sul PATH", bool(shutil.which("ssh")), shutil.which("ssh") or "assente"))
        fuori.append(("`git` e' sul PATH", bool(shutil.which("git")), shutil.which("git") or "assente"))
    return all(ok for _, ok, _ in fuori), fuori


# --------------------------------------------------------------------------------------
# 4. L'AUTOPROVA (D18 punto 2): letture costruite, nelle due direzioni, senza rete
# --------------------------------------------------------------------------------------
def letture_finte(ora, *, violazioni=0, eta_sec=600, verificati=CODICI, guardiano="ok",
                  pulito=True, non_eseguiti=0, ciechi=0, head="a" * 40, master="a" * 40):
    quando = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ora - eta_sec))
    righe = ["%s.000000000Z 2026-01-01 00:00:00,000 INFO core_auto.invarianti_archivi "
             "%s | verificati=%s | letti=archivi:25 prenotazioni:0 | violazioni=%d | "
             "non_eseguiti=%d | ciechi=%d"
             % (quando, MARCA, ",".join(verificati), violazioni, non_eseguiti, ciechi),
             "%s.100000000Z 2026-01-01 00:00:00,100 INFO core_auto.server %s"
             % (quando, GUARDIANO_PULITO if pulito else "GUARDIANO: 1 stato/i anomalo/i -> {...}")]
    return {"ora": ora, "salute_http": 200, "salute": {"status": "ok", "guardiano": guardiano},
            "registro": "\n".join(righe), "uscita_ssh": 0, "vps_head": head, "master": master}


def inietta_il_guasto(letture):
    """Le letture di un server con UNA violazione: la riga dice violazioni=1."""
    storte = dict(letture)
    storte["registro"] = re.sub(r"violazioni=\d+", "violazioni=1", storte.get("registro") or "")
    return storte


def autoprova():
    ora = 1_800_000_000
    casi = (
        ("letture SANE", letture_finte(ora), True),
        ("UNA violazione", inietta_il_guasto(letture_finte(ora)), False),
        ("riga vecchia di 26 ore", letture_finte(ora, eta_sec=26 * 3600), False),
        ("quattro invarianti su cinque", letture_finte(ora, verificati=CODICI[:4]), False),
        ("battito del Guardiano MUTO", letture_finte(ora, guardiano="muto"), False),
        ("giro del Guardiano NON pulito", letture_finte(ora, pulito=False), False),
        ("un archivio CIECO", letture_finte(ora, ciechi=1), False),
        ("il VPS non e' su master", letture_finte(ora, head="b" * 40), False),
        ("registro VUOTO", dict(letture_finte(ora), registro=""), False),
    )
    righe, riuscita = [], True
    for nome, letture, atteso in casi:
        verde, _passi, motivi, den = giudica(letture)
        ok = (verde == atteso)
        riuscita = riuscita and ok
        righe.append("   %-32s -> %-6s (atteso %-6s) denominatore %d%s"
                     % (nome, "VERDE" if verde else "ROSSO", "VERDE" if atteso else "ROSSO", den,
                        "" if ok else "   ⛔ NON E' QUELLO CHE DOVEVA DIRE: %s" % "; ".join(motivi)))
    return riuscita, righe


# --------------------------------------------------------------------------------------
def _stampa_non_guarda():
    print("-" * 86)
    print("⛔ COSA QUESTO ESAME NON HA ESAMINATO (D18 punto 3)")
    for r in NON_GUARDA:
        print("   · %s" % r)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    os.chdir(RADICE)
    print("=" * 86)
    print("🧾 ESAME DEL BLOCCO SOLDI — casella 6: gli invarianti sono verificati in PRODUZIONE")
    print("=" * 86)

    if "--autoprova" in argv:
        print("🔁 AUTOPROVA — l'esame si vede gridare e tacere su letture costruite (D18 punto 2)")
        riuscita, righe = autoprova()
        for r in righe:
            print(r)
        _stampa_non_guarda()
        print("=" * 86)
        print("VERDETTO: %s" % ("✅ l'esame grida sulle letture storte e tace su quelle sane"
                                if riuscita else "⛔ L'ESAME NON E' AFFIDABILE"))
        return 0 if riuscita else 1

    if "--con-guasto" in argv and "--scrivi" in argv:
        # ⛔ Un `if`, non un commento: registrare la misura di letture storte apposta e' il
        #    barare che D18 vieta (stessa cura degli altri esami).
        print("⛔ FERMO: `--con-guasto` non scrive. Serve a vedere l'esame gridare; registrare")
        print("   quel rosso metterebbe nella scheda un server rotto apposta.")
        return 2

    da_file = argv[argv.index("--da-file") + 1] if "--da-file" in argv else None
    tutte_ok, righe = precondizioni(con_rete=da_file is None)
    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    for nome, ok, motivo in righe:
        print("  %-9s %-62s %s" % ("OK" if ok else "⛔ NO", nome, motivo))
    if not tutte_ok:
        print("-" * 86)
        print("VERDETTO: ⛔ FERMO — una precondizione non regge, quindi NON misuro e NON scrivo.")
        _stampa_non_guarda()
        print("=" * 86)
        return 2

    if da_file:
        try:
            with io.open(da_file, encoding="utf-8") as f:
                letture = json.load(f)
        except Exception as e:
            print("VERDETTO: ⛔ FERMO — le letture salvate non si leggono (%s: %s)"
                  % (type(e).__name__, e))
            return 2
        print("LETTURE: dal file %s (ora della lettura: %s)" % (da_file, letture.get("ora")))
    else:
        print("LETTURE DAL VIVO: %s · ssh %s (registro del container %s, HEAD) · git ls-remote"
              % (SALUTE, VPS, CONTENITORE))
        letture = letture_dal_vivo()
        if "--salva" in argv:
            dove = argv[argv.index("--salva") + 1]
            with io.open(dove, "w", encoding="utf-8") as f:
                json.dump(letture, f, indent=1, ensure_ascii=False)
            print("  letture salvate in %s" % dove)
    if "--con-guasto" in argv:
        print("⚠️  PASSATA COL GUASTO DENTRO: la riga del registro dice violazioni=1")
        letture = inietta_il_guasto(letture)

    print("")
    print("REGISTRO DEL SERVER (righe %s e GUARDIANO nelle ultime %s):" % (MARCA, FINESTRA_REGISTRO))
    for r in (letture.get("registro") or "").splitlines()[-6:] or ["  (vuoto)"]:
        print("   %s" % r[:170])
    print("")
    verde, passi, motivi, denominatore = giudica(letture)
    for nome, ok, dettaglio in passi:
        print("  %s  %s%s" % ("OK  " if ok else "ROSSO", nome, ("  -> " + dettaglio) if dettaglio else ""))
    motivo = "; ".join(motivi)
    print("")
    print("VERDETTO: %s — %d passi su %d, denominatore %d (5 invarianti + %d passi)"
          % ("✅ VERDE" if verde else "⛔ ROSSO", sum(1 for _n, ok, _d in passi if ok),
             len(passi), denominatore, len(passi)))
    if motivo:
        print("   perche': %s" % motivo)

    condizioni = [b for b in BLOCCHI if b["ordine"] == BLOCCO_SOLDI][0]["finito_quando"]
    if "--scrivi" in argv:
        print("")
        print("SCRITTURA NELLA SCHEDA")
        riga = scheda.registra(condizioni[INDICE_CASELLA], esito=verde, denominatore=denominatore,
                               comando=COMANDO, ordine=BLOCCO_SOLDI, motivo=motivo or None)
        print("  scritta: blocco %d · esito %s · denominatore %d · impronta %s · motivo: %s"
              % (riga["blocco"], riga["esito"], riga["denominatore"], riga["impronta"],
                 riga.get("motivo") or "-"))
    else:
        print("")
        print("(non ho scritto niente: aggiungi --scrivi per registrare nella scheda)")
    _stampa_non_guarda()
    print("=" * 86)
    return 0 if verde else 1


if __name__ == "__main__":
    sys.exit(main())
