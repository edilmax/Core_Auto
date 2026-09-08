"""L'ESAME DELLE CASELLE 1 E 2 DEL BLOCCO 9 (CRESCITA E MARKETING) — l'interruttore e il diritto di pubblicare.

    python collaudi/esame_marketing.py                  misura e MOSTRA le due caselle (in-process, ZERO rete)
    python collaudi/esame_marketing.py --scrivi         misura e SCRIVE le due caselle nella scheda (anche un rosso)
    python collaudi/esame_marketing.py --casella interruttore|giurisdizioni [--scrivi]
    python collaudi/esame_marketing.py --con-guasto     due guasti costruiti (una fabbrica che sforna un canale
                                                        SENZA credenziali; un paese vietato da fase154 nella lista
                                                        di fase89): deve gridare, NON scrive
    python collaudi/esame_marketing.py --autoprova      il giudizio sui passi, nelle due direzioni

⛔ I TESTI DELLE CASELLE NON SI RICOPIANO: si leggono da `collaudi/piano.py` per SOTTOSTRINGA (`MARCHE`).

COSA MISURA, dichiarato (D18) — decisione della chat A il 2026-09-07 col mandato di B, rovesciabile.

CASELLA «interruttore» — ogni canale che pubblica si spegne da una persona, e da spento e' spento
  CANALI     il denominatore lo conta una macchina: i moduli del Blocco 9 (elenco letto da piano.py) il cui SORGENTE
             apre la rete (`urlopen`, `requests.`, `smtplib`, `socket.create_connection`). Ogni canale cosi' trovato
             deve avere una riga nella tabella `INTERRUTTORI` di questo file (chi lo spegne e come si prova): un canale
             con la rete e senza riga e' ROSSO (fail-closed: un canale sconosciuto e' un canale che nessuno ferma).
  SPENTO     per ogni canale la sua FABBRICA eseguita con un ambiente VUOTO ({}) non sforna nessun canale (o un
             oggetto inerte che risponde «disattivo» e non chiama la rete): l'interruttore e' l'assenza della chiave
             in ambiente, cioe' una riga del .env che una persona toglie.
  TICK       il tick del programmatore della campagna (fase94) su un motore SENZA canali non pubblica nulla (0
             pubblicazioni, il tick lo dice); l'invio email dell'outreach (fase95) senza provider risponde False e
             l'outreach di fase89 con quell'invio manda 0 email; il server (fase83, letto dal sorgente) avvia il
             programmatore SOLO se `CAMPAGNA_AUTO_GIORNI` e' in ambiente, e i canali social nascono in fase81 SOLO da
             `crea_canali_da_env()`.

CASELLA «giurisdizioni» — si pubblica solo dove fase154 dice che si puo'
  CHIAMANTI  i `fase*.py` e main_casavip.py che importano fase154 (albero sintattico, non grep): oggi ZERO, e allora la
             casella e' ROSSA col motivo (non si aggira: il modulo delle leggi esiste e nessuno lo interroga);
  DECISORI   i moduli del Blocco 9 che decidono un paese per conto loro (`ALLOW_LIST_DEFAULT`, `giurisdizioni_permesse`)
             devono passare da fase154: ognuno che non lo importa e' un passo rosso;
  COERENZA   intanto, ogni paese nella lista cablata di fase89 e' un paese in cui fase154 ammette il contatto a freddo
             via email; e fase154 risponde (US ammesso, IT no: opt-in).

⛔ D18: `precondizioni()` ferma il giro; `--autoprova` e `--con-guasto`; `NON_GUARDA`; guardia
   `test_pipeline_ci.TestLEsameDelMarketingNonPuoBARARE`. ZERO rete: ogni fabbrica riceve `{}` e ogni `fetch` finto
   esplode se chiamato. `os.environ` confrontato per intero prima e dopo.
"""
import ast
import io
import os
import re
import sys
from datetime import datetime

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

BLOCCO = 9
MARCHE = {"interruttore": "possa fermarlo", "giurisdizioni": "giurisdizioni le decide fase154"}
COMANDI = {k: "python collaudi/esame_marketing.py --casella %s --scrivi" % k for k in MARCHE}
SITUAZIONI = {"interruttore": ("canali", "spento", "tick"), "giurisdizioni": ("chiamanti", "decisori", "coerenza")}
CHIAMATE_DI_RETE = ("urlopen", "create_connection", "SMTP", "SMTP_SSL")
CHIAMATE_REQUESTS = ("post", "get", "put")
NOMI_DI_USCITA = ("pubblica", "invia", "send", "submit", "posta", "esegui")
# moduli che aprono la rete SOLO per LEGGERE (entrano dati, non escono): la ragione e' dichiarata
# e VERIFICATA sul sorgente (nessun metodo di uscita), altrimenti il modulo torna fra i canali.
SOLO_LETTURA = {"fase96_fonte_osm": "interroga OpenStreetMap (Overpass) per trovare alloggi: entra un elenco, non esce niente"}
PASSI = {"interruttore": [], "giurisdizioni": []}

NON_GUARDA = (
    "se le CHIAVI sul server siano davvero assenti o presenti: qui si prova che senza chiave il canale non nasce; "
    "cosa c'e' nel .env del VPS lo sa solo B (esame_produzione / ssh)",
    "i canali che pubblicano SENZA aprire la rete da soli (fase198 blog e fase173 SEO scrivono pagine nostre; "
    "fase169 IndexNow e' misurato): pubblicare sul NOSTRO sito non e' un canale esterno",
    "le email transazionali (conferme, voucher, avvisi host: fase86/fase152): non sono marketing",
    "la qualita' del testo generato (fase164/165, pool AI): qui si misura solo che senza canali non esce",
    "se fase154 abbia RAGIONE sulle leggi (casella 3 del blocco 5: un avvocato); qui si misura chi lo interroga",
    "l'opt-out durevole (fase95 StoreOptOut): guardato dal suo test dedicato",
)


def _esplode(*a, **k):
    raise AssertionError("la rete e' stata chiamata: il canale NON era spento")


# ---- la tabella degli interruttori: modulo -> (come si prova che da spento e' spento) ----
def _fabbrica_vuota(modulo, nome):
    m = __import__(modulo)
    f = getattr(m, nome)
    try:
        return f({}, fetch=_esplode)
    except TypeError:
        return f({})


def _prova_fase91():
    return _fabbrica_vuota("fase91_canali_social", "crea_canali_da_env") == {}, "crea_canali_da_env({}) == {}"


def _prova_none(modulo, nome):
    def prova():
        r = _fabbrica_vuota(modulo, nome)
        return r is None, "%s({}) -> %r" % (nome, r)
    return prova


def _prova_fase169():
    from fase169_indexnow import crea_indexnow
    ix = crea_indexnow({})
    esito = ix.submit(["https://bookinvip.com/"]) if hasattr(ix, "submit") else {}
    return (not ix.attivo) and esito.get("inviato") is False, "attivo=%r submit=%r" % (ix.attivo, esito)


def _prova_fase89():
    from fase89_jurisdiction_outreach import Contatto, FonteStub, MotoreRadarOutreach
    from fase95_outreach_email import adatta_invio_email
    invia = adatta_invio_email(None)
    c = Contatto(nome="Host", email="host@example.com", paese="US", contatto_pubblico_business=True)
    rep = MotoreRadarOutreach().esegui(FonteStub([c]), paese="US", concorrenti_bps={}, invia=invia)
    return invia("host@example.com", "o", "c") is False and rep.get("inviati") == 0 and rep.get("trovati") == 1, \
        "invio senza provider=%r report=%r" % (invia("host@example.com", "o", "c"), rep)


def _prova_fase24():
    import fase13_protocollo_finale as f13
    import fase24_channels as f24
    vero = f13.Config.TELEGRAM_BOT_TOKEN
    try:
        f13.Config.TELEGRAM_BOT_TOKEN = ""
        ad = f24.TelegramAdapter() if hasattr(f24, "TelegramAdapter") else None
        if ad is None:
            return False, "TelegramAdapter non trovato in fase24"
        import requests
        vero_post = requests.post
        requests.post = _esplode
        try:
            msg = f24.ChannelMessage(channel="telegram", recipient="", text="prova") if hasattr(f24, "ChannelMessage") else None
            esito = ad.send(msg)
        finally:
            requests.post = vero_post
        return esito is True, "senza token: send -> %r senza toccare la rete (dice «consegnato»: e' un no-op dichiarato)" % (esito,)
    finally:
        f13.Config.TELEGRAM_BOT_TOKEN = vero


INTERRUTTORI = {
    "fase91_canali_social": ("TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID / META_PAGE_ID+META_PAGE_TOKEN", _prova_fase91),
    "fase92_canale_x": ("X_API_KEY/SECRET/ACCESS_TOKEN/ACCESS_SECRET", _prova_none("fase92_canale_x", "crea_canale_x_da_env")),
    "fase93_canale_tiktok": ("TIKTOK_*", _prova_none("fase93_canale_tiktok", "crea_canale_tiktok_da_env")),
    "fase193_canale_mastodon": ("MASTODON_*", _prova_none("fase193_canale_mastodon", "crea_canale_mastodon_da_env")),
    "fase194_canale_bluesky": ("BLUESKY_*", _prova_none("fase194_canale_bluesky", "crea_canale_bluesky_da_env")),
    "fase195_canale_reddit": ("REDDIT_*", _prova_none("fase195_canale_reddit", "crea_canale_reddit_da_env")),
    "fase196_video_ai": ("VIDEO_AI_*", _prova_none("fase196_video_ai", "crea_video_ai_da_env")),
    "fase197_canale_nostr": ("NOSTR_*", _prova_none("fase197_canale_nostr", "crea_canale_nostr_da_env")),
    "fase169_indexnow": ("INDEXNOW_KEY (default OFF)", _prova_fase169),
    "fase89_jurisdiction_outreach": ("il provider email iniettato (fase95.adatta_invio_email: None -> False)", _prova_fase89),
    "fase24_channels": ("Config.TELEGRAM_BOT_TOKEN (fase13, da ambiente)", _prova_fase24),
}


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


def _sorgente(nome):
    with io.open(os.path.join(RADICE, nome + ".py"), encoding="utf-8", errors="replace") as f:
        return f.read()


# ---- censimenti (macchina, non elenco a mano; albero sintattico: un commento non conta, S6) ----
def apre_la_rete(sorgente):
    """Vero se nel sorgente c'e' una CHIAMATA eseguibile che apre la rete (urlopen, socket,
    smtplib, requests.post/get/put)."""
    try:
        albero = ast.parse(sorgente)
    except SyntaxError:
        return False
    for nodo in ast.walk(albero):
        if not isinstance(nodo, ast.Call):
            continue
        f = nodo.func
        nome = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
        if nome in CHIAMATE_DI_RETE:
            return True
        if nome in CHIAMATE_REQUESTS and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                and f.value.id == "requests":
            return True
    return False


def ha_metodi_di_uscita(sorgente):
    try:
        albero = ast.parse(sorgente)
    except SyntaxError:
        return False
    return any(isinstance(n, ast.FunctionDef) and n.name.split("_")[0] in NOMI_DI_USCITA for n in ast.walk(albero))


def canali_con_la_rete(moduli=None):
    """I moduli del blocco il cui sorgente apre la rete. Chi sta in SOLO_LETTURA resta fuori
    SOLO se il sorgente conferma che non ha metodi di uscita; altrimenti rientra."""
    fuori = []
    for m in (moduli if moduli is not None else moduli_del_blocco()):
        try:
            src = _sorgente(m)
        except OSError:
            continue
        if apre_la_rete(src) and not (m in SOLO_LETTURA and not ha_metodi_di_uscita(src)):
            fuori.append(m)
    return fuori


def _importa(sorgente, nome):
    try:
        albero = ast.parse(sorgente)
    except SyntaxError:
        return False
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.Import) and any(a.name.split(".")[0] == nome for a in nodo.names):
            return True
        if isinstance(nodo, ast.ImportFrom) and (nodo.module or "").split(".")[0] == nome:
            return True
    return False


def chiamanti_di_fase154():
    fuori = []
    for nome in sorted(os.listdir(RADICE)):
        if not ((nome.startswith("fase") and nome.endswith(".py")) or nome == "main_casavip.py"):
            continue
        if nome.startswith("fase154"):
            continue
        if _importa(_sorgente(nome[:-3]), "fase154_giurisdizioni_marketing"):
            fuori.append(nome[:-3])
    return fuori


def decisori_di_paese(moduli=None):
    return [m for m in (moduli if moduli is not None else moduli_del_blocco())
            if os.path.isfile(os.path.join(RADICE, m + ".py"))
            and re.search(r"ALLOW_LIST_DEFAULT\s*=|giurisdizioni_permesse", _sorgente(m))]


def precondizioni():
    fuori = []
    for k in MARCHE:
        try:
            fuori.append(("la casella «%s» esiste nel piano, una sola" % MARCHE[k], True,
                          " ".join(str(condizione(k)).split())[:70]))
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
        import fase154_giurisdizioni_marketing as f154
        ok, _m = f154.puo_contattare_a_freddo("US", "email")
        fuori.append(("fase154 risponde", ok is True, "US email -> %r" % (ok,)))
    except Exception as e:
        fuori.append(("fase154 risponde", False, "%s: %s" % (type(e).__name__, e)))
    return all(ok for _, ok, _ in fuori), fuori


# ---- casella «interruttore» ----
def misura_interruttore(con_guasto=False):
    print("\n--- INTERRUTTORE: i canali con la rete, la loro fabbrica a ambiente vuoto, il tick ---")
    canali = canali_con_la_rete()
    passo("interruttore", "canali", "il censimento trova canali che aprono la rete (denominatore contato dal sorgente)",
          len(canali) > 0, "%d: %s" % (len(canali), ", ".join(canali)))
    for m, perche in SOLO_LETTURA.items():
        src = _sorgente(m)
        passo("interruttore", "canali", "%s e' escluso perche' legge soltanto, e il sorgente lo conferma" % m,
              apre_la_rete(src) and not ha_metodi_di_uscita(src), perche)
    for c in canali:
        passo("interruttore", "canali", "%s: ha una riga nella tabella degli interruttori" % c, c in INTERRUTTORI,
              INTERRUTTORI.get(c, ("NESSUNA: canale che nessuno sa fermare",))[0])
    for c in canali:
        if c not in INTERRUTTORI:
            continue
        chi, prova = INTERRUTTORI[c]
        if con_guasto and c == "fase92_canale_x":
            import fase92_canale_x as f92
            prova = lambda: (f92.CanaleX("k", "s", "t", "x", fetch=_esplode) is None, "fabbrica che sforna un canale senza chiavi")  # noqa: E731
        try:
            ok, dett = prova()
        except Exception as e:                                    # noqa: BLE001 - una prova rotta e' un rosso
            ok, dett = False, "%s: %s" % (type(e).__name__, e)
        passo("interruttore", "spento", "%s: con l'ambiente VUOTO non nasce nessun canale (%s)" % (c, chi), ok, dett)
    # il tick
    from fase90_marketing import crea_motore_marketing
    from fase94_scheduler_campagna import crea_scheduler_campagna
    motore = crea_motore_marketing(canali={}, email_provider=None)
    sched = crea_scheduler_campagna(motore, cadenza_giorni=1, clock=lambda: datetime(2030, 1, 1), ultimo=None)
    rep = sched.tick(["it"])
    pubblicati = int(rep.get("pubblicati") or 0) + int(rep.get("inviati") or 0)
    passo("interruttore", "tick", "fase94: il tick su un motore SENZA canali gira e pubblica ZERO",
          rep.get("eseguito") is True and pubblicati == 0 and not rep.get("canali_configurati"),
          "report=%r" % ({k: rep.get(k) for k in ("eseguito", "pubblicati", "post_generati", "canali_configurati", "errori")},))
    src83 = _sorgente("fase83_server")
    m = re.search(r"_giorni\s*=\s*os\.environ\.get\(\"CAMPAGNA_AUTO_GIORNI\".*?\n\s*if _giorni and", src83, re.S)
    passo("interruttore", "tick", "fase83: il programmatore della campagna parte SOLO se CAMPAGNA_AUTO_GIORNI e' in ambiente",
          bool(m), "letto dal sorgente")
    src81 = _sorgente("fase81_bootstrap_casavip")
    passo("interruttore", "tick", "fase81: i canali social del sistema nascono SOLO da crea_canali_da_env()",
          "crea_motore_marketing(canali=crea_canali_da_env()" in src81, "letto dal sorgente")


# ---- casella «giurisdizioni» ----
def misura_giurisdizioni(con_guasto=False):
    print("\n--- GIURISDIZIONI: chi interroga fase154, chi decide un paese da solo, coerenza ---")
    import fase154_giurisdizioni_marketing as f154
    import fase89_jurisdiction_outreach as f89
    chiamanti = chiamanti_di_fase154()
    passo("giurisdizioni", "chiamanti", "almeno un modulo di produzione importa fase154 (albero sintattico)",
          len(chiamanti) > 0, "chiamanti=%r" % (chiamanti,))
    decisori = decisori_di_paese()
    passo("giurisdizioni", "decisori", "il censimento trova chi decide un paese da solo", len(decisori) > 0, repr(decisori))
    for d in decisori:
        passo("giurisdizioni", "decisori", "%s decide un paese: passa da fase154" % d, d in chiamanti,
              "non importa fase154" if d not in chiamanti else "")
    lista = tuple(f89.ALLOW_LIST_DEFAULT) + (("IT",) if con_guasto else ())
    vietati = [p for p in lista if f154.puo_contattare_a_freddo(p, "email")[0] is not True]
    passo("giurisdizioni", "coerenza", "ogni paese nella lista cablata di fase89 e' ammesso da fase154 per l'email",
          bool(lista) and not vietati, "lista=%r vietati=%r" % (lista, vietati))
    us, it = f154.puo_contattare_a_freddo("US", "email"), f154.puo_contattare_a_freddo("IT", "email")
    passo("giurisdizioni", "coerenza", "fase154 distingue: US ammesso, IT no (opt-in)", us[0] is True and it[0] is False,
          "US=%r IT=%r" % (us, it))
    consentite = f154.giurisdizioni_consentite("email")
    passo("giurisdizioni", "coerenza", "fase154 elenca le giurisdizioni consentite e nessuna e' nell'UE (opt-in)",
          bool(consentite) and not any(p in consentite for p in ("IT", "FR", "DE", "ES", "NL", "IE", "AT", "PT")),
          "%d consentite" % len(consentite))


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
            righe.append("   %-50s -> %-6s (atteso %-6s) den %d%s" % (nome, "VERDE" if verde else "ROSSO",
                                                                        "VERDE" if atteso else "ROSSO", den,
                                                                        "" if ok else "   ⛔ NON E' QUELLO CHE DOVEVA DIRE"))
    # i censimenti nelle due direzioni, su sorgenti finti
    ok = (_importa("import fase154_giurisdizioni_marketing as g\n", "fase154_giurisdizioni_marketing")
          and _importa("from fase154_giurisdizioni_marketing import regole_paese\n", "fase154_giurisdizioni_marketing")
          and not _importa("# fase154_giurisdizioni_marketing solo nel commento\nimport os\n", "fase154_giurisdizioni_marketing")
          and apre_la_rete("r = urllib.request.urlopen(req)\n") and not apre_la_rete("# urlopen( nel commento\nx = 1\n")
          and apre_la_rete("import requests\nrequests.post(u)\n") and not apre_la_rete("s = 'requests.post(u)'\n")
          and ha_metodi_di_uscita("def pubblica(p):\n    pass\n") and not ha_metodi_di_uscita("def cerca():\n    pass\n"))
    riuscita = riuscita and ok
    righe.append("   %-50s -> %s" % ("censimenti (import AST e rete) nelle due direzioni", "OK" if ok else "⛔ ROTTI"))
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
    print("🧾 ESAME DEL BLOCCO 9 — marketing: %s" % ", ".join("«%s»" % MARCHE[c] for c in scelte))
    print("=" * 86)
    if "--autoprova" in argv:
        print("🔁 AUTOPROVA — il giudizio e i censimenti nelle due direzioni (D18 punto 2)")
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
        print("   rosso metterebbe nella scheda un canale senza interruttore costruito apposta.")
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
        print("⚠️  PASSATA COI GUASTI DENTRO: fabbrica di X che sforna un canale senza chiavi; IT nella lista di fase89")
    ambiente_prima = dict(os.environ)
    misure = {"interruttore": misura_interruttore, "giurisdizioni": misura_giurisdizioni}
    for c in scelte:
        try:
            misure[c](con_guasto)
        except Exception as e:                                    # noqa: BLE001 - una misura rotta e' un rosso
            passo(c, SITUAZIONI[c][0], "la misura e' ESPLOSA", False, "%s: %s" % (type(e).__name__, e))
        passo(c, SITUAZIONI[c][0], "l'ambiente (os.environ) e' identico a prima della misura",
              dict(os.environ) == ambiente_prima)
    uscita = 0
    for c in scelte:
        verde, motivi, denominatore = giudica(PASSI[c], SITUAZIONI[c])
        print("")
        print("— casella «%s» —" % MARCHE[c])
        print("VERDETTO: %s — passi %d, rossi %d, denominatore %d"
              % ("✅ VERDE" if verde else "⛔ ROSSO", len(PASSI[c]), sum(1 for p in PASSI[c] if not p[2]), denominatore))
        for m in motivi:
            print("   perche': %s" % m)
        uscita = uscita or (0 if verde else 1)
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
    return uscita


if __name__ == "__main__":
    sys.exit(main())
