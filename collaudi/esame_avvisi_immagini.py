"""L'ESAME DELLA CASELLA «OGNI IMMAGINE PRESA DA FUORI ... FASCIA VULNERABLE» — blocco 3.

    python collaudi/esame_avvisi_immagini.py               misura e MOSTRA (cosi' gira in CI)
    python collaudi/esame_avvisi_immagini.py --scrivi      misura e SCRIVE la casella (anche falsa)
    python collaudi/esame_avvisi_immagini.py --autoprova   si vede gridare e tacere (D18 punto 2)

Uscita: 0 nessuna falla con la riparazione pronta · 1 ce n'e' almeno una · 2 non ha guardato
(rete, fonte cambiata, controprova fallita): il 2 NON e' un verde.

⛔ IL TESTO DELLA CASELLA NON SI RICOPIA: si cerca in `piano.py` per contenuto, UNA volta sola.

PERCHE' ESISTE (24/11/2026). In produzione girava nginx 1.31.8 sei giorni dopo la 1.31.9, che
ripara falle «major» sulla nostra strada; Dependabot taceva per la sua attesa di tre giorni e
nessuna macchina leggeva gli avvisi. Questa macchina li legge OGNI NOTTE (job `avvisi` della
CI) e il rosso arriva su Telegram dal guardiano del VPS, che legge i controlli di master.

COSA MISURA. Le immagini prese da fuori si leggono dal compose di produzione e dal Dockerfile
dell'app (una nuova, non coperta, ferma l'esame), e si aprono DAL REGISTRO per impronta, senza
docker: ogni manifesto, configurazione e strato si ricontrolla col suo sha256. Tre fronti:
  1. NGINX  — nginx.org/en/security_advisories.html: la versione e' vulnerabile se sta in una
     fascia «Vulnerable» e nessun «X+» dello STESSO ramo (o del ramo piu' nuovo) la copre.
  2. PYTHON — l'archivio della PSF (github.com/psf/advisory-database) scrive COMMIT riparatori,
     non versioni: si chiede a OSV.dev per il commit del tag (`git ls-remote`, il commit vero
     `^{}`, non l'oggetto del tag annotato, che risponde sempre vuoto).
  3. ALPINE — i pacchetti di sistema dentro l'immagine di nginx (lib/apk/db/installed, letto
     dagli strati), chiesti a OSV.dev nell'ecosistema del suo ramo (Alpine:vX.Y). Rossa una
     falla CON riparazione pubblicata; quelle senza riparazione si stampano e non fanno rosso
     (un allarme sempre acceso si spegne, e allora non serve piu').
  E che il job notturno esista, giri tutti i giorni ed esegua QUESTO esame senza scappatoie.

⛔ CONTROPROVE A OGNI GIRO, sulle fonti vere: nginx 1.31.8, Python 3.11.0 e openssl 3.5.0-r0
   DEVONO risultare vulnerabili. Il 24/11 un primo conteggio a mano aveva scritto «1 avviso»
   per la 3.11.18: era la risposta vuota `{}` contata come un avviso (S1). Senza controprova,
   una fonte muta o un parser rotto direbbero «zero falle» senza aver guardato niente.
"""
import hashlib
import html
import io
import json
import os
import re
import subprocess
import sys
import tarfile
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

from piano import BLOCCHI  # noqa: E402
import scheda  # noqa: E402

BLOCCO = 3
SEGNALE = "ogni immagine presa da fuori che il server esegue"
COMANDO = "python collaudi/esame_avvisi_immagini.py --scrivi"
CI = os.path.join(RADICE, ".github", "workflows", "ci.yml")
COMPOSE = os.path.join(RADICE, "docker-compose.casavip.yml")
DOCKERFILE = os.path.join(RADICE, "Dockerfile.casavip")
JOB_CI = "avvisi"
PASSO_CI = "python collaudi/esame_avvisi_immagini.py"
CONDIZIONE_JOB = "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
IMMAGINE_COSTRUITA = "casavip-app"        # la costruiamo noi da DOCKERFILE: si guarda la sua base
# Il VPS e' x86_64 (misurato il 24/11 con `uname -m`): dall'indice multi-piattaforma si apre
# solo il manifesto linux/amd64, quello che il server scarica davvero.
PIATTAFORMA = ("linux", "amd64")
FONTE_NGINX = "https://nginx.org/en/security_advisories.html"
OSV = "https://api.osv.dev/v1"
CPYTHON_GIT = "https://github.com/python/cpython"
REGISTRO = "https://registry-1.docker.io/v2"
CONTROPROVA_NGINX = "1.31.8"              # 11 falle riparate dalla 1.31.9 (18/11/2026)
CONTROPROVA_PYTHON = "3.11.0"             # 39 avvisi PSF misurati il 24/11
CONTROPROVA_ALPINE = ("openssl", "3.5.0-r0")
MINIMO_AVVISI_NGINX = 70                  # 79 il 24/11: meno di cosi' = pagina cambiata
TETTO_BYTE = 200 * 1024 * 1024
_RE_NGINX = re.compile(r"^nginx:(?P<ver>\d+\.\d+\.\d+)-alpine@(?P<dig>sha256:[0-9a-f]{64})$")
_RE_PYTHON = re.compile(r"^FROM\s+python:(?P<ramo>\d+\.\d+)-slim@(?P<dig>sha256:[0-9a-f]{64})\s*$")
# I pacchetti che l'immagine ufficiale prende dal repository di nginx.org, non da Alpine: li
# giudica il fronte 1, e chiesti ad Alpine sarebbero confrontati col nginx di un altro progetto.
_RE_PACCHETTO_NGINX_ORG = re.compile(r"^nginx(-module-[a-z0-9-]+)?$")

# ⛔ LE ECCEZIONI PORTANO LA LORO PROVA, RIMISURATA A OGNI GIRO, E SCADONO DA SOLE.
#    Un avviso con la riparazione pronta resta rosso, salvo che qui sotto ci sia: (1) il
#    motivo, (2) i SIMBOLI del codice difettoso, che l'esame cerca nei file dell'immagine e
#    che devono MANCARE (un file non trovato non e' una prova: e' rosso), (3) una scadenza,
#    passata la quale torna rosso anche se la prova regge. Un elenco di eccezioni senza prova
#    e' un interruttore per spegnere l'allarme: questo non lo e'.
ECCEZIONI = {
    # 24/11/2026. CVE-2026-4738 e' una falla di gdal nel codice «contrib/infback9» di zlib
    # (inftree9.c); Alpine l'ha attribuita al pacchetto zlib e la «ripara» con la 1.4-r0.
    # Misurato quel giorno sull'immagine nginx:1.31.10-alpine (sha256:aceb952b...): la
    # libz.so.1.3.2 contiene `inflateBack` ma NON `inflateBack9`, la funzione PUBBLICA di
    # contrib/infback9 (se il codice fosse compilato, il nome sarebbe esportato e visibile
    # anche in una libreria senza simboli di debug). Vale solo per zlib 1.3.2-r1 e scade in
    # 30 giorni: o nginx pubblica un'immagine con zlib nuova, o si rimisura.
    ("zlib", "ALPINE-CVE-2026-4738"): {
        "motivo": "il codice difettoso (contrib/infback9) non e' compilato nella libz dell'immagine",
        "versione": "1.3.2-r1",
        "file": "usr/lib/libz.so.",
        "simboli_assenti": ("inflateBack9",),
        "dal": "2026-11-24",
        "scadenza": "2026-12-24",
    },
}

NON_GUARDA = (
    "i pacchetti Debian e pip dell'immagine dell'app: il Dockerfile fa `apt-get upgrade` alla "
    "costruzione, quindi la base ufficiale non e' cio' che gira. Li guarda Trivy nel job "
    "`immagine`, ma su un'immagine costruita FRESCA in CI, non su quella del server",
    "i moduli dinamici di nginx (njs, acme) hanno i loro avvisi: qui si guarda nginx, non njs",
    "OSV.dev e' uno specchio: un avviso che la fonte pubblica e OSV non ha ancora importato "
    "arriva il giorno dopo (Alpine e PSF sono importati di continuo)",
    "le falle SENZA riparazione si stampano ma non fanno rosso",
    "le ECCEZIONI (oggi una: zlib CVE-2026-4738) non fanno rosso finche' la loro prova regge "
    "e non sono scadute: la prova cerca simboli nel file, non dimostra che il resto sia sano",
    "la gravita' non si pesa: qualunque falla con la riparazione pronta e' rossa",
    "le immagini si leggono dal compose e dal Dockerfile di MASTER, non da cio' che gira sul "
    "VPS: se il server restasse indietro rispetto a master, questo esame non lo vede (lo vede "
    "il confronto dei tre posti, D7)",
    "gli altri compose del repository (docker-compose.yml, docker-compose.tavolavip*.yml, "
    "docker-compose.postgres.yml) e il Dockerfile generico: misurato il 24/11 che il VPS avvia "
    "solo docker-compose.casavip.yml (`docker compose ls`)",
    "Python: OSV risponde `{}` anche per un commit che non ha ancora indicizzato; la controprova "
    "sulla 3.11.0 prova che conosce il ramo, non quel commit",
    "nginx.org: non c'e' un controllo di freschezza della pagina (una copia vecchia in una cache "
    "passerebbe); si controlla solo che arrivi intera e che ogni voce sia letta",
    "se il giro notturno NON PARTE (GitHub salta i giri programmati), nessuno lo vede: il "
    "guardiano del VPS legge i controlli di master, non l'eta' dell'ultimo giro",
)


class FonteMuta(Exception):
    """La fonte non ha risposto o ha cambiato forma: non e' un verde, e' una misura mancata."""


def testo_casella():
    condizioni = BLOCCHI[BLOCCO - 1]["finito_quando"]
    trovate = [" ".join(str(c).split()) for c in condizioni if SEGNALE in " ".join(str(c).split())]
    if len(trovate) != 1:
        raise ValueError("nel blocco %d le caselle che nominano %r sono %d, non 1"
                         % (BLOCCO, SEGNALE, len(trovate)))
    return trovate[0]


# ── rete ───────────────────────────────────────────────────────────────────────────────
def _http(url, intestazioni=None, corpo=None, tentativi=3):
    """I byte della risposta. Tre tentativi sui guasti di rete, sui 5xx e sul 429; poi
    FonteMuta col codice E il corpo della risposta (regola ferrea 9: mai il solo stato).

    ⛔ La chiave del registro (`Authorization`) NON segue i rimandi: il registro manda gli
    strati a una CDN di un altro dominio, e urllib ricopierebbe la chiave anche li'."""
    import http.client
    ultimo = None
    for n in range(tentativi):
        try:
            dati = json.dumps(corpo).encode() if corpo is not None else None
            h = dict(intestazioni or {})
            chiave = h.pop("Authorization", None)
            if dati is not None:
                h["Content-Type"] = "application/json"
            richiesta = urllib.request.Request(url, data=dati, headers=h)
            if chiave:
                richiesta.add_unredirected_header("Authorization", chiave)
            with urllib.request.urlopen(richiesta, timeout=90) as r:  # nosec B310 - indirizzi fissi https  # noqa: S310
                b = r.read(TETTO_BYTE + 1)
                attesi = r.headers.get("Content-Length")
            if attesi and attesi.isdigit() and int(attesi) != len(b):
                raise http.client.IncompleteRead(b, int(attesi) - len(b))
            if len(b) > TETTO_BYTE:
                raise FonteMuta("%s: risposta oltre %d byte" % (url, TETTO_BYTE))
            return b
        except urllib.error.HTTPError as e:
            try:
                testo = " ".join(e.read(300).decode("utf-8", "replace").split())
            except Exception:  # noqa: BLE001 - il corpo e' solo diagnosi
                testo = ""
            ultimo = "HTTP %s %s" % (e.code, testo)
            if e.code < 500 and e.code != 429:
                break
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            ultimo = "%s: %s" % (type(e).__name__, e)
        if n + 1 < tentativi:
            time.sleep(2 * (n + 1))
    raise FonteMuta("%s non risponde: %s" % (url.split("?")[0], ultimo))


def _json(b, dove):
    try:
        return json.loads(b.decode("utf-8"))
    except Exception as e:
        raise FonteMuta("%s: risposta non JSON (%s)" % (dove, e)) from e


# ── le immagini dal codice ─────────────────────────────────────────────────────────────
def immagini_dal_codice(testo_compose, testo_dockerfile):
    """[(nome, repo, impronta, versione_attesa)] delle immagini prese da fuori.

    ⛔ Ogni `image:` del compose dev'essere l'immagine che costruiamo noi o il nginx fissato
    per impronta: una terza immagine presa da fuori non e' coperta da questo esame e lo ferma
    (la casella dice «ogni immagine»), invece di passare in silenzio."""
    import yaml
    doc = yaml.safe_load(testo_compose)
    servizi = (doc or {}).get("services") or {}
    if not servizi:
        raise ValueError("nel compose non ci sono servizi")
    trovate = []
    for nome, s in sorted(servizi.items()):
        img = str((s or {}).get("image") or "")
        if img == IMMAGINE_COSTRUITA:
            continue
        m = _RE_NGINX.match(img)
        if not m:
            raise ValueError("il servizio %r esegue %r: un'immagine presa da fuori che questo "
                             "esame non sa leggere (solo nginx:X.Y.Z-alpine@sha256)" % (nome, img))
        trovate.append(("nginx", "library/nginx", m.group("dig"), m.group("ver")))
    if len(trovate) != 1:
        raise ValueError("nginx compare %d volte nel compose, non 1" % len(trovate))
    froms = [r for r in testo_dockerfile.splitlines() if r.strip().upper().startswith("FROM")]
    if len(froms) != 1:
        raise ValueError("il Dockerfile dell'app ha %d righe FROM, non 1" % len(froms))
    m = _RE_PYTHON.match(froms[0].strip())
    if not m:
        raise ValueError("FROM inatteso nel Dockerfile dell'app: %r" % froms[0])
    trovate.append(("python", "library/python", m.group("dig"), m.group("ramo")))
    return trovate


# ── il registro ────────────────────────────────────────────────────────────────────────
_ACCETTA = ",".join((
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json"))


def _verifica(b, impronta, cosa):
    vera = "sha256:" + hashlib.sha256(b).hexdigest()
    if vera != impronta:
        raise FonteMuta("%s: il registro ha mandato %s invece di %s" % (cosa, vera, impronta))


def _token(repo):
    b = _http("https://auth.docker.io/token?service=registry.docker.io&scope=repository:%s:pull"
              % repo)
    t = _json(b, "token del registro").get("token")
    if not t:
        raise FonteMuta("il registro non ha dato il token per %s" % repo)
    return t


def apri_immagine(repo, impronta):
    """(token, manifesto, configurazione) del manifesto linux/amd64, tutto per impronta."""
    t = _token(repo)
    h = {"Authorization": "Bearer " + t, "Accept": _ACCETTA}
    b = _http("%s/%s/manifests/%s" % (REGISTRO, repo, impronta), h)
    _verifica(b, impronta, "%s@%s" % (repo, impronta[:19]))
    m = _json(b, "manifesto")
    if "manifests" in m:
        scelti = [x for x in m["manifests"]
                  if (x.get("platform") or {}).get("os") == PIATTAFORMA[0]
                  and (x.get("platform") or {}).get("architecture") == PIATTAFORMA[1]
                  and not (x.get("platform") or {}).get("variant")]
        if len(scelti) != 1:
            raise FonteMuta("%s: %d manifesti %s/%s nell'indice, non 1"
                            % (repo, len(scelti), PIATTAFORMA[0], PIATTAFORMA[1]))
        d = scelti[0]["digest"]
        b = _http("%s/%s/manifests/%s" % (REGISTRO, repo, d), h)
        _verifica(b, d, "manifesto %s" % PIATTAFORMA[1])
        m = _json(b, "manifesto")
    cfg_d = (m.get("config") or {}).get("digest") or ""
    b = _http("%s/%s/blobs/%s" % (REGISTRO, repo, cfg_d), {"Authorization": "Bearer " + t})
    _verifica(b, cfg_d, "configurazione")
    cfg = _json(b, "configurazione")
    if cfg.get("architecture") != PIATTAFORMA[1]:
        raise FonteMuta("%s: la configurazione e' per %r" % (repo, cfg.get("architecture")))
    return t, m, cfg


def variabile(cfg, nome):
    for e in (cfg.get("config") or {}).get("Env") or []:
        if e.startswith(nome + "="):
            return e.split("=", 1)[1]
    raise FonteMuta("la configurazione dell'immagine non ha %s" % nome)


def leggi_apk(strati, cerca=()):
    """(VERSION_ID, testo del db apk, {file: byte}) dagli strati in ordine: vince l'ultimo che
    li scrive, e un «whiteout» di Docker (`.wh.<nome>`) li cancella. `cerca`: i prefissi dei
    file che servono alle prove delle ECCEZIONI."""
    fissi = ("lib/apk/db/installed", "etc/os-release", "usr/lib/os-release")
    disco = {}
    for b in strati:
        try:
            tf = tarfile.open(fileobj=io.BytesIO(b), mode="r:*")
        except tarfile.TarError as e:
            raise FonteMuta("uno strato non si apre come archivio (%s)" % e) from e
        with tf:
            membri = tf.getmembers()
            # Prima le cancellazioni di QUESTO strato (valgono sugli strati di sotto), poi i
            # suoi file. `.wh.<nome>` cancella un file o una cartella intera; `.wh..wh..opq`
            # svuota la cartella.
            for mb in membri:
                n = mb.name[2:] if mb.name.startswith("./") else mb.name
                cartella, base = n.rsplit("/", 1) if "/" in n else ("", n)
                if base == ".wh..wh..opq":
                    via = cartella + "/" if cartella else ""
                elif base.startswith(".wh."):
                    via = (cartella + "/" if cartella else "") + base[4:]
                else:
                    continue
                for k in [k for k in disco if k == via or k.startswith(via.rstrip("/") + "/")]:
                    del disco[k]
            for mb in membri:
                n = mb.name[2:] if mb.name.startswith("./") else mb.name
                if mb.isfile() and not n.rsplit("/", 1)[-1].startswith(".wh.") and (
                        n in fissi or any(n.startswith(p) for p in cerca)):
                    disco[n] = tf.extractfile(mb).read()
    db = disco.get("lib/apk/db/installed")
    db = db.decode("utf-8", "replace") if db else None
    ver = None
    for nome in ("etc/os-release", "usr/lib/os-release"):
        if nome in disco:
            m = re.search(r"(?m)^VERSION_ID=\"?([0-9.]+)\"?$", disco[nome].decode("utf-8", "replace"))
            if m:
                ver = m.group(1)
                break
    file = {k: v for k, v in disco.items() if any(k.startswith(p) for p in cerca)}
    if not ver or not db:
        raise FonteMuta("negli strati mancano os-release (%s) o il db di apk (%s)"
                        % (bool(ver), bool(db)))
    return ver, db, file


def eccezione_regge(ecc, file, oggi):
    """(regge, perche'). Regge solo se non e' scaduta, il file c'e' e NESSUN simbolo vietato
    compare in nessuna sua versione: un file assente non prova niente."""
    if not ecc.get("simboli_assenti") or not ecc.get("motivo"):
        return False, "eccezione senza simboli da cercare o senza motivo: non e' una prova"
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(ecc.get("scadenza", ""))):
        return False, "eccezione senza una scadenza AAAA-MM-GG"
    if oggi > ecc["scadenza"]:
        return False, "eccezione scaduta il %s: si rimisura o si ripara" % ecc["scadenza"]
    trovati = {n: b for n, b in file.items() if n.startswith(ecc["file"])}
    if not trovati:
        return False, "il file %s non c'e' nell'immagine: la prova non si fa" % ecc["file"]
    for n, b in sorted(trovati.items()):
        for s in ecc["simboli_assenti"]:
            if s.encode() in b:
                return False, "%s contiene %r: il codice difettoso C'E'" % (n, s)
    return True, "%s senza %s (%d file guardati), scade il %s" % (
        ecc["file"], "/".join(ecc["simboli_assenti"]), len(trovati), ecc["scadenza"])


def pacchetti_apk(testo_db):
    """[(nome, versione, origine)] dal formato di lib/apk/db/installed (record separati da una
    riga vuota, campi «P:» nome, «V:» versione, «o:» pacchetto d'origine)."""
    pacchetti, cur = [], {}
    for r in testo_db.splitlines() + [""]:
        if not r.strip():
            if cur:
                if not cur.get("P") or not cur.get("V"):
                    raise ValueError("record apk senza nome o versione: %r" % cur)
                pacchetti.append((cur["P"], cur["V"], cur.get("o") or cur["P"]))
                cur = {}
        elif len(r) > 2 and r[1] == ":":
            cur.setdefault(r[0], r[2:])
    return pacchetti


# ── fronte 1: nginx.org ────────────────────────────────────────────────────────────────
def _v(testo):
    return tuple(int(x) for x in testo.split("."))


def _gettone(t):
    t = t.strip()
    if t in ("all",):
        return ("tutte",)
    if t in ("none",):
        return ("nessuna",)
    if t.startswith("nginx/Windows"):
        return ("windows",)
    m = re.match(r"^(\d+(?:\.\d+)+)\+$", t)
    if m:
        return ("da", _v(m.group(1)))
    m = re.match(r"^(\d+(?:\.\d+)+)-(\d+(?:\.\d+)+)$", t)
    if m:
        return ("fascia", _v(m.group(1)), _v(m.group(2)))
    m = re.match(r"^(\d+(?:\.\d+)+)$", t)
    if m:
        return ("solo", _v(m.group(1)))
    raise ValueError("forma sconosciuta negli avvisi di nginx: %r" % t)


def avvisi_nginx(testo_html):
    """[{titolo, cve, vulnerabili, non_vulnerabili}]. ⛔ Ogni voce ha UNA riga «Vulnerable:» e
    UNA «Not vulnerable:»; una forma nuova ferma l'esame (ValueError), non si salta."""
    voci = []
    for blocco in re.findall(r"<li\b[^>]*>(.*?)</li\s*>", testo_html, re.S | re.I):
        if "Vulnerable:" not in blocco:
            continue
        righe = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", r)).split())
                 for r in re.split(r"<br\s*/?>", blocco)]
        vul = [r for r in righe if r.startswith("Vulnerable:")]
        non = [r for r in righe if r.startswith("Not vulnerable:")]
        if len(vul) != 1 or len(non) != 1:
            raise ValueError("voce con %d righe Vulnerable e %d Not vulnerable: %r"
                             % (len(vul), len(non), righe[:1]))
        cve = re.findall(r"CVE-\d{4}-\d+", blocco)
        voci.append({
            "titolo": righe[0] if righe else "?",
            "cve": cve[0] if cve else "senza CVE",
            "vulnerabili": [_gettone(x) for x in vul[0].split(":", 1)[1].split(",") if x.strip()],
            "non_vulnerabili": [_gettone(x) for x in non[0].split(":", 1)[1].split(",")
                                if x.strip()],
        })
    # ⛔ Ogni «Not vulnerable:» della pagina dev'essere in una voce letta: una voce scritta in
    #    una forma che il lettore non riconosce (un tag diverso, un annidamento) non sparisce
    #    in silenzio, ferma l'esame. E' la voce NUOVA quella che rischia di cambiare forma.
    nella_pagina = len(re.findall(r"Not vulnerable:", html.unescape(re.sub(r"<[^>]+>", " ",
                                                                           testo_html))))
    if nella_pagina != len(voci):
        raise ValueError("la pagina ha %d «Not vulnerable:», lette %d voci"
                         % (nella_pagina, len(voci)))
    return voci


def e_vulnerabile(versione, voce):
    v = _v(versione)
    # «X+» sotto Vulnerable = da X in su (una falla ancora aperta si scriverebbe cosi').
    esplicito = any((g[0] == "solo" and v == g[1]) or (g[0] == "fascia" and g[1] <= v <= g[2])
                    for g in voce["vulnerabili"])
    aperto = any(g[0] == "tutte" or (g[0] == "da" and v >= g[1]) for g in voce["vulnerabili"])
    if not (esplicito or aperto):
        return False
    da = [g[1] for g in voce["non_vulnerabili"] if g[0] == "da"]
    piu_nuovo = max(da) if da else None
    for x in da:
        # Lo STESSO ramo copre sempre. Il ramo piu' nuovo della riparazione copre solo una
        # versione che nessuna fascia esplicita nomina: «Vulnerable: 1.21.4-1.31.10» con la
        # sola riparazione «1.30.8+» lascia la 1.31.10 VULNERABILE.
        if v >= x and (v[:2] == x[:2] or (x == piu_nuovo and not esplicito)):
            return False
    return not any(g[0] == "solo" and g[1] == v for g in voce["non_vulnerabili"])


def nginx_ha_riparazione(voce):
    """False se nginx non ha MAI pubblicato una versione riparata («Not vulnerable: none»,
    come CVE-2009-4487 sui log non ripuliti, «Severity: none»): si dichiara, non fa rosso."""
    return any(g[0] in ("da", "solo") for g in voce["non_vulnerabili"])


# ── fronte 2: Python (PSF via OSV) ─────────────────────────────────────────────────────
def vulns_da_risposta(obj):
    """La lista degli avvisi di una risposta OSV. ⛔ `{}` vuol dire ZERO (24/11: contata come
    «1» a mano); una risposta che non e' un oggetto non e' zero, e' una fonte muta."""
    if not isinstance(obj, dict):
        raise FonteMuta("OSV ha risposto %r invece di un oggetto" % type(obj).__name__)
    v = obj.get("vulns", [])
    if not isinstance(v, list):
        raise FonteMuta("OSV: «vulns» non e' una lista")
    return v


def osv_query(corpo):
    """Tutti gli avvisi di una query OSV, pagina dopo pagina."""
    trovati, pagina = [], None
    for _ in range(50):
        c = dict(corpo)
        if pagina:
            c["page_token"] = pagina
        r = _json(_http(OSV + "/query", corpo=c), "OSV")
        trovati.extend(vulns_da_risposta(r))
        pagina = r.get("next_page_token")
        if not pagina:
            return trovati
    raise FonteMuta("OSV: piu' di 50 pagine")


def commit_del_tag(versione):
    """Il COMMIT (non l'oggetto tag) di vX.Y.Z in cpython, da `git ls-remote`."""
    rif = "refs/tags/v%s^{}" % versione
    p = subprocess.run(["git", "ls-remote", CPYTHON_GIT, rif],  # nosec B603 B607 - git, argomenti fissi  # noqa: S603 S607
                       capture_output=True, text=True, timeout=120)
    righe = [r.split() for r in (p.stdout or "").splitlines() if r.strip()]
    trovate = [r[0] for r in righe if len(r) == 2 and r[1] == rif and re.match(r"^[0-9a-f]{40}$",
                                                                              r[0])]
    if p.returncode != 0 or len(trovate) != 1:
        raise FonteMuta("cpython: il commit di %s non si legge (uscita %s, %d righe)"
                        % (rif, p.returncode, len(righe)))
    return trovate[0]


def avvisi_python(versione):
    return [x.get("id", "?") for x in osv_query({"commit": commit_del_tag(versione)})]


def ultima_del_ramo(ramo):
    """L'ultima vX.Y.Z pubblicata del ramo (es. 3.11), dai tag di cpython."""
    p = subprocess.run(["git", "ls-remote", "--tags", CPYTHON_GIT, "refs/tags/v%s.*" % ramo],  # nosec B603 B607 - git, argomenti fissi  # noqa: S603 S607
                       capture_output=True, text=True, timeout=120)
    numeri = [int(m.group(1)) for m in re.finditer(
        r"refs/tags/v%s\.(\d+)\^\{\}$" % re.escape(ramo), p.stdout or "", re.M)]
    if p.returncode != 0 or not numeri:
        raise FonteMuta("cpython: i tag del ramo %s non si leggono (uscita %s)"
                        % (ramo, p.returncode))
    return "%s.%d" % (ramo, max(numeri))


def dividi_python(nostri, dell_ultima, e_l_ultima):
    """(riparabili, senza). Un avviso sulla nostra versione e' «riparabile» se l'ultima
    versione pubblicata dello STESSO ramo non ce l'ha: allora la riparazione esiste e basta
    aggiornare l'immagine. Se ce l'ha anche l'ultima (o la nostra E' l'ultima), il ramo non
    ha ancora una versione riparata: si dichiara, non fa rosso."""
    if e_l_ultima:
        return [], list(nostri)
    return ([i for i in nostri if i not in set(dell_ultima)],
            [i for i in nostri if i in set(dell_ultima)])


# ── fronte 3: Alpine via OSV ───────────────────────────────────────────────────────────
def riparabile(vuln, ecosistema, nome):
    """True se l'avviso pubblica una versione riparatrice per QUEL pacchetto in QUEL ramo."""
    for a in vuln.get("affected") or []:
        p = a.get("package") or {}
        if p.get("ecosystem") == ecosistema and p.get("name") == nome:
            for rg in a.get("ranges") or []:
                if any("fixed" in e for e in rg.get("events") or []):
                    return True
    return False


def falle_alpine(pacchetti, ecosistema):
    """(riparabili, senza_riparazione, quanti_chiesti): liste di (origine, versione, id)."""
    chiesti = sorted({(o, v) for n, v, o in pacchetti if not _RE_PACCHETTO_NGINX_ORG.match(o)})
    q = {"queries": [{"package": {"name": o, "ecosystem": ecosistema}, "version": v}
                     for o, v in chiesti]}
    risultati = _json(_http(OSV + "/querybatch", corpo=q), "OSV querybatch").get("results")
    if not isinstance(risultati, list) or len(risultati) != len(chiesti):
        raise FonteMuta("OSV querybatch: %s risultati per %d pacchetti"
                        % (len(risultati) if isinstance(risultati, list) else "nessun",
                           len(chiesti)))
    # ⛔ OSV risponde `{}` anche per un NOME che non conosce, e `{}` sembra «zero falle».
    #    Seconda fonte, quella da cui OSV copia: secdb di Alpine. Ogni nostro pacchetto che
    #    secdb conosce come colpito in passato, OSV deve conoscerlo (domanda senza versione).
    ramo = ecosistema.split(":", 1)[1]
    in_secdb = set()
    for deposito in ("main", "community"):
        d = _json(_http("https://secdb.alpinelinux.org/%s/%s.json" % (ramo, deposito)), "secdb")
        for p in d.get("packages") or []:
            pk = p.get("pkg") or {}
            if pk.get("secfixes"):
                in_secdb.add(pk.get("name"))
    da_riconoscere = sorted({o for o, _v2 in chiesti} & in_secdb)
    if len(da_riconoscere) < 5:
        raise FonteMuta("secdb di Alpine %s: solo %d dei nostri pacchetti noti, la fonte e' "
                        "cambiata" % (ramo, len(da_riconoscere)))
    noti = _json(_http(OSV + "/querybatch", corpo={"queries": [
        {"package": {"name": o, "ecosystem": ecosistema}} for o in da_riconoscere]}),
        "OSV querybatch").get("results") or []
    sconosciuti = [o for o, r in zip(da_riconoscere, noti) if not vulns_da_risposta(r)]
    if len(noti) != len(da_riconoscere) or sconosciuti:
        raise FonteMuta("OSV non conosce in %s pacchetti che secdb conosce: %s"
                        % (ecosistema, sconosciuti or "risposta troncata"))
    rip, senza = [], []
    for (o, v), r in zip(chiesti, risultati):
        ids = [x.get("id") for x in vulns_da_risposta(r)]
        if r.get("next_page_token"):
            ids = [x.get("id") for x in osv_query({"package": {"name": o, "ecosystem": ecosistema},
                                                   "version": v})]
        for i in ids:
            # Il nome arriva da fuori e finisce in un indirizzo: solo lettere, cifre, . _ -
            if not re.match(r"^[A-Za-z0-9._-]{1,80}$", str(i or "")) or ".." in str(i):
                raise FonteMuta("OSV ha dato un nome d'avviso inatteso: %r" % (i,))
            vuln = _json(_http("%s/vulns/%s" % (OSV, i)), "OSV %s" % i)
            (rip if riparabile(vuln, ecosistema, o) else senza).append((o, v, i))
    return rip, senza, len(chiesti), len(da_riconoscere)


# ── la CI ──────────────────────────────────────────────────────────────────────────────
def _giorni(campo):
    giorni = set()
    for pezzo in campo.split(","):
        if pezzo == "*":
            return set(range(7))
        m = re.match(r"^(\d)(?:-(\d))?$", pezzo)
        if not m:
            return set()
        a = int(m.group(1))
        b = int(m.group(2) or a)
        giorni.update(x % 7 for x in range(a, b + 1))
    return giorni


def job_ci_quotidiano(testo_ci):
    """(ok, dettaglio): il workflow gira OGNI giorno e il job JOB_CI esegue PASSO_CI esatto,
    solo sui giri programmati e a mano, senza niente che ne spenga l'esito."""
    try:
        import yaml
        doc = yaml.safe_load(testo_ci)
    except Exception as e:
        return False, "ci.yml illeggibile come YAML: %s" % e
    if not isinstance(doc, dict):
        return False, "ci.yml non e' una mappa"
    on = doc.get("on", doc.get(True))           # PyYAML legge la chiave `on` come True
    crons = [str(c.get("cron", "")) for c in ((on or {}).get("schedule") or [])
             if isinstance(c, dict)] if isinstance(on, dict) else []
    giorni = set()
    for c in crons:
        campi = c.split()
        if len(campi) == 5 and campi[2] == "*" and campi[3] == "*":
            giorni |= _giorni(campi[4])
    if giorni != set(range(7)):
        return False, "i giri programmati non coprono i sette giorni: %r" % crons
    if not isinstance(on, dict) or "workflow_dispatch" not in on:
        return False, "manca l'avvio a mano (workflow_dispatch)"
    # ⛔ ELENCHI CHIUSI, non elenchi di divieti: `defaults` (anche del workflow), `env`,
    #    `needs`, `strategy` o un passo in piu' possono spegnere il comando senza toccarlo.
    for chiave in ("defaults", "env"):
        if chiave in doc:
            return False, "il workflow ha %r: puo' cambiare come gira il comando" % chiave
    job = (doc.get("jobs") or {}).get(JOB_CI)
    if not isinstance(job, dict):
        return False, "il job %r non c'e' in ci.yml" % JOB_CI
    estranee = sorted(set(job) - {"name", "timeout-minutes", "runs-on", "if", "steps"})
    if estranee:
        return False, "il job %r ha chiavi non ammesse: %s" % (JOB_CI, estranee)
    if " ".join(str(job.get("if", "")).split()) != CONDIZIONE_JOB:
        return False, "il job %r ha if=%r, non %r" % (JOB_CI, job.get("if"), CONDIZIONE_JOB)
    passi = job.get("steps") or []
    if not all(isinstance(s, dict) for s in passi):
        return False, "un passo del job %r non e' una mappa" % JOB_CI
    for s in passi:
        estranee = sorted(set(s) - {"name", "uses", "with", "run"})
        if estranee:
            return False, "un passo del job %r ha chiavi non ammesse: %s" % (JOB_CI, estranee)
        uses = str(s.get("uses", ""))
        run = " ".join(str(s.get("run", "")).split())
        if uses and not re.match(r"^actions/(checkout|setup-python)@v\d+$", uses):
            return False, "il job %r usa un'azione non ammessa: %r" % (JOB_CI, uses)
        if (uses and run) or (not uses and run not in ("pip install pyyaml", PASSO_CI)):
            return False, "il job %r ha un passo non ammesso: %r" % (JOB_CI, run or uses)
    comandi = [" ".join(str(s.get("run", "")).split()) for s in passi]
    if comandi.count(PASSO_CI) != 1 or not comandi or comandi[-1] != PASSO_CI:
        return False, "il job %r deve eseguire %r una volta, come ULTIMO passo" % (JOB_CI, PASSO_CI)
    return True, "%s esegue %r ogni giorno (%d cron) e a mano" % (JOB_CI, PASSO_CI, len(crons))


# ── autoprova (senza rete) ─────────────────────────────────────────────────────────────
_HTML_PROVA = (
    "<ul><li>english<br></li>"
    "<li><p>Falla finta<br>Severity: major<br>CVE-2099-1<br>"
    "Not vulnerable: 9.9.9+, 9.8.4+<br>Vulnerable: 1.0.0-9.9.8</p></li>"
    "<li><p>Falla vecchia<br>Severity: low<br>"
    "Not vulnerable: 0.8.15+, 0.7.62+<br>Vulnerable: 0.1.0-0.8.14, nginx/Windows 0.7.52-0.8.14"
    "</p></li>"
    "<li><p>Mai riparata<br>Severity: none<br>CVE-2099-2<br>"
    "Not vulnerable: none<br>Vulnerable: all</p></li></ul>")


def autoprova():
    """(grida, tace): i quattro lettori su dati costruiti apposta, nelle due direzioni."""
    voci = avvisi_nginx(_HTML_PROVA)
    grida = (len(voci) == 3 and e_vulnerabile("9.9.8", voci[0]) and e_vulnerabile("9.8.3", voci[0])
             and e_vulnerabile("0.7.61", voci[1]) and nginx_ha_riparazione(voci[0]))
    tace = (not e_vulnerabile("9.9.9", voci[0]) and not e_vulnerabile("9.8.4", voci[0])
            and not e_vulnerabile("10.0.1", voci[0]) and not e_vulnerabile("0.7.62", voci[1])
            and e_vulnerabile("9.9.9", voci[2]) and not nginx_ha_riparazione(voci[2]))
    try:
        avvisi_nginx(_HTML_PROVA.replace("1.0.0-9.9.8", "1.0.0 fino a 9.9.8"))
        grida = False                                    # una forma nuova deve FERMARE
    except ValueError:
        pass
    grida = grida and len(vulns_da_risposta({"vulns": [{"id": "PSF-X"}]})) == 1
    tace = tace and vulns_da_risposta({}) == []
    try:
        vulns_da_risposta([])
        grida = False
    except FonteMuta:
        pass
    con = {"affected": [{"package": {"ecosystem": "Alpine:v3.24", "name": "zlib"},
                         "ranges": [{"events": [{"introduced": "0"}, {"fixed": "1.4-r0"}]}]}]}
    senza = {"affected": [{"package": {"ecosystem": "Alpine:v3.24", "name": "zlib"},
                           "ranges": [{"events": [{"introduced": "0"}]}]}]}
    grida = grida and riparabile(con, "Alpine:v3.24", "zlib")
    tace = (tace and not riparabile(senza, "Alpine:v3.24", "zlib")
            and not riparabile(con, "Alpine:v3.23", "zlib"))
    ecc = {"file": "usr/lib/libz.so", "simboli_assenti": ("inflateBack9",),
           "scadenza": "2099-01-01", "motivo": "prova", "versione": "1.3.2-r1"}
    grida = grida and not eccezione_regge(dict(ecc, simboli_assenti=()),
                                          {"usr/lib/libz.so.1": b"x"}, "2026-11-24")[0]
    tace = tace and eccezione_regge(ecc, {"usr/lib/libz.so.1": b"..inflateBack.."}, "2026-11-24")[0]
    grida = (grida
             and not eccezione_regge(ecc, {"usr/lib/libz.so.1": b"inflateBack9"}, "2026-11-24")[0]
             and not eccezione_regge(ecc, {}, "2026-11-24")[0]
             and not eccezione_regge(ecc, {"usr/lib/libz.so.1": b"x"}, "2099-01-02")[0])
    aperta = {"vulnerabili": [("da", (1, 31, 0))], "non_vulnerabili": [("nessuna",)]}
    vecchio = {"vulnerabili": [("fascia", (1, 21, 4), (1, 31, 10))],
               "non_vulnerabili": [("da", (1, 30, 8))]}
    grida = (grida and e_vulnerabile("1.31.10", aperta) and e_vulnerabile("1.31.10", vecchio))
    tace = tace and not e_vulnerabile("1.30.9", aperta) and not e_vulnerabile("1.30.8", vecchio)
    grida = grida and dividi_python(["PSF-1", "PSF-2"], ["PSF-2"], False) == (["PSF-1"], ["PSF-2"])
    tace = tace and dividi_python(["PSF-1"], [], True) == ([], ["PSF-1"])
    # Gli strati: il db scritto, poi cancellato da una cancellazione di cartella e riscritto;
    # una libreria cancellata con `.wh.` e una cartella svuotata con `.wh..wh..opq`.

    def _strato(voci):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for nome, dati in voci:
                info = tarfile.TarInfo(nome)
                info.size = len(dati)
                tf.addfile(info, io.BytesIO(dati))
        return buf.getvalue()
    osr = b"VERSION_ID=3.24.4\n"
    s1 = _strato([("etc/os-release", osr), ("lib/apk/db/installed", b"P:vecchio\nV:1-r0\n"),
                  ("usr/lib/libz.so.1", b"inflateBack9"), ("usr/lib/x/libz.so.9", b"y")])
    s2 = _strato([("lib/apk/.wh.db", b""), ("lib/apk/db/installed", b"P:nuovo\nV:2-r0\n"),
                  ("./usr/lib/.wh.libz.so.1", b""), ("usr/lib/x/.wh..wh..opq", b"")])
    ver, db2, file = leggi_apk([s1, s2], cerca=("usr/lib/libz.so", "usr/lib/x/"))
    tace = tace and ver == "3.24.4" and "nuovo" in db2 and "vecchio" not in db2 and file == {}
    db = "P:zlib\nV:1.3.2-r1\no:zlib\n\nP:libssl3\nV:3.5.9-r1\no:openssl\n"
    grida = grida and pacchetti_apk(db) == [("zlib", "1.3.2-r1", "zlib"),
                                            ("libssl3", "3.5.9-r1", "openssl")]
    return bool(grida), bool(tace)


# ── la misura ──────────────────────────────────────────────────────────────────────────
def misura():
    """(esito, denominatore, motivo, righe). Solleva FonteMuta se non ha potuto guardare."""
    with io.open(COMPOSE, encoding="utf-8") as f:
        compose = f.read()
    with io.open(DOCKERFILE, encoding="utf-8") as f:
        dockerfile = f.read()
    immagini = immagini_dal_codice(compose, dockerfile)
    rossi, righe = [], []
    pagina = _http(FONTE_NGINX).decode("utf-8", "replace")
    voci = avvisi_nginx(pagina)
    if len(voci) < MINIMO_AVVISI_NGINX:
        raise FonteMuta("nginx.org: %d avvisi letti, meno di %d" % (len(voci), MINIMO_AVVISI_NGINX))
    controprova = [x for x in voci if e_vulnerabile(CONTROPROVA_NGINX, x)]
    if not controprova:
        raise FonteMuta("controprova: nginx %s risulta senza falle" % CONTROPROVA_NGINX)
    if not avvisi_python(CONTROPROVA_PYTHON):
        raise FonteMuta("controprova: Python %s risulta senza avvisi" % CONTROPROVA_PYTHON)
    for nome, repo, impronta, attesa in immagini:
        tok, man, cfg = apri_immagine(repo, impronta)
        if nome == "nginx":
            ver = variabile(cfg, "NGINX_VERSION")
            if ver != attesa:
                raise FonteMuta("il compose dice nginx %s, l'immagine %s" % (attesa, ver))
            falle = [x for x in voci if e_vulnerabile(ver, x)]
            senza_n = [x for x in falle if not nginx_ha_riparazione(x)]
            falle = [x for x in falle if nginx_ha_riparazione(x)]
            righe.append("nginx %s: %d avvisi letti su nginx.org, %d con riparazione lo toccano, "
                         "%d senza (controprova %s: %d)"
                         % (ver, len(voci), len(falle), len(senza_n), CONTROPROVA_NGINX,
                            len(controprova)))
            righe += ["   senza riparazione (non fa rosso): nginx %s %s (%s)"
                      % (ver, x["cve"], x["titolo"][:60]) for x in senza_n]
            rossi += ["nginx %s: %s (%s)" % (ver, x["cve"], x["titolo"][:60]) for x in falle]
            strati = []
            for s in man.get("layers") or []:
                b = _http("%s/%s/blobs/%s" % (REGISTRO, repo, s["digest"]),
                          {"Authorization": "Bearer " + tok})
                _verifica(b, s["digest"], "strato")
                strati.append(b)
            ver_os, db, file = leggi_apk(strati, cerca=tuple(
                e["file"] for e in ECCEZIONI.values()))
            eco = "Alpine:v%s" % ".".join(ver_os.split(".")[:2])
            n, v = CONTROPROVA_ALPINE
            if not osv_query({"package": {"name": n, "ecosystem": eco}, "version": v}):
                raise FonteMuta("controprova: %s %s risulta senza falle in %s" % (n, v, eco))
            pacchetti = pacchetti_apk(db)
            rip, senza, chiesti, riconosciuti = falle_alpine(pacchetti, eco)
            righe.append("%s dentro nginx: %d pacchetti d'origine chiesti a OSV (%d riconosciuti "
                         "anche da secdb), %d falle con riparazione, %d senza"
                         % (eco, chiesti, riconosciuti, len(rip), len(senza)))
            versioni = {o: ve2 for _n, ve2, o in pacchetti}
            righe += ["   senza riparazione (non fa rosso): %s %s %s" % x for x in senza]
            oggi = time.strftime("%Y-%m-%d", time.gmtime())
            for o, ve, i in rip:
                ecc = ECCEZIONI.get((o, i))
                regge, perche = eccezione_regge(ecc, file, oggi) if ecc else (False, "")
                if regge and ecc.get("versione") != versioni.get(o):
                    regge, perche = False, ("vale per %s %s, nell'immagine c'e' %s"
                                            % (o, ecc.get("versione"), versioni.get(o)))
                if regge:
                    righe.append("   ECCEZIONE con prova (non fa rosso): %s %s %s -- %s; %s"
                                 % (o, ve, i, ecc["motivo"], perche))
                else:
                    rossi.append("%s %s %s: riparazione pubblicata in %s%s"
                                 % (o, ve, i, eco, (" (eccezione: %s)" % perche) if perche else ""))
        else:
            ver = variabile(cfg, "PYTHON_VERSION")
            if not ver.startswith(attesa + "."):
                raise FonteMuta("il Dockerfile dice python %s, l'immagine %s" % (attesa, ver))
            ids = avvisi_python(ver)
            ultima = ultima_del_ramo(attesa)
            if _v(ultima) < _v(ver):
                raise FonteMuta("cpython: l'ultima %s e' piu' vecchia della nostra %s"
                                % (ultima, ver))
            e_l_ultima = ultima == ver
            rip, senza = dividi_python(ids, [] if e_l_ultima or not ids else avvisi_python(ultima),
                                       e_l_ultima)
            righe.append("Python %s (base dell'app; ultima del ramo %s): %d avvisi sul suo "
                         "commit, %d riparati in una versione piu' nuova, %d senza riparazione"
                         % (ver, ultima, len(ids), len(rip), len(senza)))
            righe += ["   senza riparazione nel ramo (non fa rosso): Python %s %s" % (ver, i)
                      for i in senza]
            rossi += ["Python %s: %s riparato nella %s" % (ver, i, ultima) for i in rip]
    return not rossi, len(immagini), "; ".join(rossi), righe


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    print("=" * 86)
    print("🛡️  ESAME AVVISI — «nessuna immagine presa da fuori in una fascia Vulnerable» (blocco 3)")
    print("=" * 86)
    grida, tace = autoprova()
    print("  %-6s il metro si prova da solo  grida=%s · tace=%s"
          % ("OK" if (grida and tace) else "ROSSO", grida, tace))
    if "--autoprova" in argv:
        return 0 if (grida and tace) else 1
    try:
        testo_casella()
        with io.open(CI, encoding="utf-8") as f:
            ci_ok, ci_det = job_ci_quotidiano(f.read())
    except Exception as e:
        print("VERDETTO: ⛔ NON ESEGUIBILE — %s" % e)
        return 2
    print("  %-6s il job notturno  %s" % ("OK" if ci_ok else "ROSSO", ci_det))
    if not (grida and tace):
        print("VERDETTO: ⛔ NON ESEGUIBILE — l'autoprova non regge")
        return 2
    try:
        esito, denominatore, motivo, righe = misura()
    except Exception as e:  # noqa: BLE001 - qualunque guasto e' «non ha guardato» (2), mai «falla» (1)
        print("VERDETTO: ⛔ NON ESEGUIBILE — non ha guardato: %s: %s" % (type(e).__name__, e))
        print("::error title=Avvisi non letti::%s: %s" % (type(e).__name__, str(e)[:300]))
        return 2
    for r in righe:
        print("  " + r)
    if not ci_ok:
        esito = False
        motivo = "; ".join(x for x in (motivo, "job notturno: " + ci_det) if x)
    print("  casella %s  (denominatore %d immagini prese da fuori)%s"
          % ("☑" if esito else "☐", denominatore, ("\n     perche': %s" % motivo) if motivo else ""))
    print("  ⛔ COSA NON GUARDA:")
    for r in NON_GUARDA:
        print("     · %s" % r)
    if "--scrivi" in argv:
        scheda.registra(testo_casella(), esito=esito, denominatore=denominatore,
                        comando=COMANDO, ordine=BLOCCO, motivo=motivo or None)
        print("  🗂️  casella scritta%s" % ("" if esito else " (falsa, col motivo)"))
    if not esito:
        print("::error title=Falla con la riparazione pronta::%s" % motivo[:600])
    print("VERDETTO: %s" % ("✅ nessuna falla con la riparazione pronta" if esito
                            else "⛔ " + motivo[:300]))
    return 0 if esito else 1


if __name__ == "__main__":
    sys.exit(main())
