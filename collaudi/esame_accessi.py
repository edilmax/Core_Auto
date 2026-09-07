"""L'ESAME DEL BLOCCO 3 (IDENTITA', ACCESSI E SICUREZZA) — le tre caselle della porta.

    python collaudi/esame_accessi.py                    misura (router locale + sito vivo) e MOSTRA
    python collaudi/esame_accessi.py --scrivi           misura e SCRIVE le tre caselle nella scheda
                                                        (anche un rosso, col suo motivo)
    python collaudi/esame_accessi.py --casella scrive|matrice|sonde [--scrivi]
                                                        una casella sola
    python collaudi/esame_accessi.py --locale           solo il router locale (niente rete): le
                                                        caselle che vogliono il sito vero NON si
                                                        scrivono (restano NON MISURATE)
    python collaudi/esame_accessi.py --salva F          oltre a misurare, salva le letture in F
    python collaudi/esame_accessi.py --da-file F        giudica letture salvate (niente rete)
    python collaudi/esame_accessi.py --con-guasto       storce le letture (una porta aperta): deve
                                                        gridare, e NON scrive mai
    python collaudi/esame_accessi.py --autoprova        si vede gridare e tacere, senza rete e
                                                        senza router (D18 punto 2)

⛔ IL TESTO DELLE CASELLE NON SI RICOPIA: si legge da `collaudi/piano.py` (Blocco 3, «finito_quando»),
   cercandolo per TESTO (`SCRIVE senza identita'`, `matrice dei permessi`, `diverso da 404`): il
   posto nella lista puo' cambiare, il verdetto no.

LE TRE DOMANDE, e come si misurano (D25: OWASP ASVS 4.0.3 §V4 «Access Control», 2021 — «deny by
default», «enforce access control rules on a trusted service layer»; OWASP WSTG v4.2, 2020 —
WSTG-ATHZ-02 «Testing for Bypassing Authorization Schema» e WSTG-ATHZ-04 «Insecure Direct Object
References»; OWASP API Security Top 10, 2023 — API1 «Broken Object Level Authorization», API5
«Broken Function Level Authorization»):

  1. «nessuna rotta pubblica SCRIVE senza identita'» — LE ROTTE SI ENUMERANO DAL CODICE (il
     sorgente di `RouterHTTP._instrada`, mai una lista a mano: una rotta nuova entra da sola).
     Ogni rotta che NON e' GET viene chiamata sul router VERO (un sistema in una cartella
     temporanea) SENZA credenziali e con un corpo vuoto `{}`. Se risponde 401/403 e' protetta
     da un'identita' (chiave, sessione, token firmato: la porta si chiude PRIMA di guardare il
     corpo). Se risponde 2xx SCRIVE senza identita' -> ROSSO. Se risponde altro (400/422/404/
     409/503) la rotta o e' pubblica per progetto (dichiarata in `PUBBLICHE_PER_PROGETTO`, col
     motivo) oppure e' NON DETERMINATA: la validazione del corpo precede l'identita', e da fuori
     non si vede quale delle due manca. Le NON DETERMINATE sono elencate e tengono la casella
     ROSSA: «non lo so» non e' «verde» (D18 punto 3).
  2. «la matrice dei permessi e' verde su ogni rotta riservata, provata SUL SITO VERO» — le
     rotte riservate (prefissi `/api/host`, `/api/admin`, `/api/bunker`, `/api/gate`, meno le
     pubbliche per progetto) su DUE assi: (a) senza credenziali, sul router locale E sul sito
     vivo: ognuna deve rispondere 401 o 403; (b) con le credenziali di un ALTRO host (locale:
     due host registrati davvero, l'host B chiama le rotte con l'annuncio dell'host A): mai 2xx
     (WSTG-ATHZ-04, API1 BOLA). Le risposte diverse da 401/403/404 sull'asse (b) sono NON
     DETERMINATE (la validazione precede la proprieta') e sono elencate.
  3. «ogni sonda negativa interroga un indirizzo che risponde diverso da 404» — sul sito vivo,
     ogni sonda dell'asse (a) e ogni sonda con credenziali INVENTATE deve ricevere 401/403, MAI
     404 (un 404 e' «questa pagina non c'e'», e come prova di sicurezza vale zero: D17). E un
     indirizzo inventato apposta deve rispondere 404: cosi' si sa che il 404 e' distinguibile.
     In piu': la lista a mano di `verifica_produzione.p3_porte_chiuse` deve stare DENTRO le rotte
     del codice (una lista scritta a mano invecchia: qui la si confronta col router).

⛔ D18, LE QUATTRO CONDIZIONI DI UNO STRUMENTO CHE MISURA:
   1. misura PRIMA se stesso (`precondizioni`): le tre caselle esistono nel piano, una sola
      ciascuna; il router si legge e ha piu' di 100 rotte; il sistema locale si costruisce;
      per il vivo, l'indirizzo di controllo risponde 404 (se no i 404 non dicono niente);
   2. provato nelle DUE direzioni: `--autoprova` costruisce letture sane e storte (una porta 2xx
      senza credenziali, un 404 su una sonda, un 200 per l'altro host, una rotta non dichiarata)
      e pretende ROSSO li' e VERDE sulle sane, senza rete e senza router;
   3. dichiara cosa NON ha esaminato: `NON_GUARDA`, stampato a ogni giro, piu' le rotte NON
      MISURATE (prefissi `startswith`) e le NON DETERMINATE, nominate una per una;
   4. e' sotto guardia: `test_esame_accessi.py` (l'autoprova, l'enumerazione, le due direzioni).

⛔ NIENTE SEGRETI: sul sito vivo si mandano SOLO credenziali inventate o nessuna; nessuna chiave
   vera viene letta ne' stampata. ⚠️ Le sonde senza credenziali CONTANO come tentativi falliti
   nel buttafuori per IP (fase179: 8 in 60 s -> il TUO IP e' negato in blocco per un minuto,
   raddoppiando): il verdetto non cambia (una porta chiusa resta chiusa, e una rotta che non
   chiama l'identita' risponde 2xx lo stesso), ma il registro del server mostra righe
   `RATE-LIMIT` con l'IP di chi misura. E' dichiarato, non nascosto.
"""
import io
import json
import os
import re
import shutil
import sys
import tempfile
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

BLOCCO = 3
MARCHE = {
    "scrive": "SCRIVE senza identita'",
    "matrice": "matrice dei permessi",
    "sonde": "diverso da 404",
}
COMANDI = {k: "python collaudi/esame_accessi.py --casella %s --scrivi" % k for k in MARCHE}
SITO = os.environ.get("BOOKINVIP_SITO", "https://bookinvip.com")
PREFISSI_RISERVATI = ("/api/host/", "/api/admin/", "/api/bunker/", "/api/gate/")
CHIUSA = (401, 403)
PAUSA_VIVO_SEC = 0.25
# Un indirizzo che NON esiste, per sapere che il 404 del sito e' distinguibile (D17).
CONTROLLO_404 = "/api/questa-rotta-non-esiste-esame-accessi"
IP_SONDA = {"X-Forwarded-For": "203.0.113.77"}

# Rotte che DEVONO rispondere anche senza credenziali, col motivo (una lista dichiarata,
# non dedotta: chi legge sa perche' quella porta e' aperta). Ognuna resta sotto la stessa
# prova: con un corpo vuoto NON deve rispondere 2xx (non scrive niente senza dati veri).
PUBBLICHE_PER_PROGETTO = {
    "/api/host/registrazione": "chi si registra non ha ancora credenziali (crea l'identita')",
    "/api/host/login": "il login E' il modo di ottenere l'identita'",
    "/api/host/password_dimenticata": "chi ha perso la password non ha credenziali",
    "/api/host/password_reset": "il gettone di reset arriva per email: e' lui l'identita'",
    "/api/host/invito/registra": "registrazione su invito: il gettone d'invito e' l'identita'",
    "/api/admin/login": "il login dell'operatore (fase192) E' il modo di ottenere l'identita'",
    "/api/bunker/login": "il login del bunker: chiave admin + secondo fattore",
    "/api/bunker/logout": "uscire non richiede di essere dentro (sessione gia' invalidata)",
    # ⛔ «/api/host/logout» NON esiste nel router (l'uscita dell'host e' /api/gate/logout): la
    # lista di `mappa_scoperta.py` la nomina lo stesso, e la guardia
    # `test_le_liste_dichiarate_nominano_solo_rotte_che_esistono` l'ha vista rossa qui il
    # 2026-09-06 prima che fosse tolta. Una dichiarazione su una rotta inventata e' S2.
    "/api/gate/logout": "uscire non richiede di essere dentro",
    "/api/domanda": "lista d'attesa: l'email e' il dato, non c'e' un conto da proteggere",
    "/api/partner": "candidatura partner: modulo pubblico con consenso GDPR, dedup per email",
    "/api/concierge/quote": "un preventivo non scrive: firma un token (e' l'inizio dell'identita')",
    "/api/concierge/book": "l'identita' e' il quote_token FIRMATO nel corpo (fase59:512-515)",
    "/api/concierge/cancella": "l'identita' e' il voucher FIRMATO nel corpo",
    "/api/preventivo/email": "manda un preventivo a un'email: non scrive stato",
    "/api/split/preview": "anteprima di un conto di gruppo: non scrive",
    "/api/contratto": "l'identita' e' il token firmato nel corpo",
    "/api/voucher/messaggio": "l'identita' e' il voucher FIRMATO nel corpo (chat ospite)",
    "/api/voucher/prova": "l'identita' e' il voucher FIRMATO nel corpo",
    "/api/checkin/pre_registra": "l'identita' e' il voucher FIRMATO nel corpo",
    "/api/garanzia/conferma": "l'identita' e' il voucher FIRMATO nel corpo",
    "/api/garanzia/contesta": "l'identita' e' il voucher FIRMATO nel corpo",
    "/api/recensioni": "l'identita' e' il diritto di recensione FIRMATO (token nel corpo)",
    "/api/split/crea": "l'identita' e' il voucher FIRMATO nel corpo (chiuso il 2026-08-20)",
    "/api/split/paga": "l'identita' e' il voucher FIRMATO della STESSA prenotazione (2026-08-20)",
    "/api/payments/webhook": "l'identita' e' la firma HMAC di Stripe sul corpo grezzo (fase87)",
    "/api/telegram/webhook": "l'identita' e' il segreto del webhook Telegram",
    "/api/mcp": "porta MCP: dichiarata qui per non tacere, la sua identita' va letta a parte",
    "/api/marketing/campagna": "richiede la chiave admin: e' riservata, non pubblica (vedi matrice)",
}

# Rotte pubbliche che rispondono 200 anche a un corpo VUOTO, col motivo letto nel codice: un 200
# qui NON e' una scrittura senza identita'. Un 200 a vuoto su una rotta che NON sta in questa
# lista e' ROSSO: la lista e' chiusa, e si allarga solo leggendo il gestore.
RISPONDONO_200_A_VUOTO = {
    "/api/host/password_dimenticata": "risponde SEMPRE 200 (anti-enumerazione: mai dire se "
                                      "un'email esiste; fase83 `_host_password_dimenticata`)",
    "/api/telegram/webhook": "un webhook risponde 200 a Telegram per non farlo ritentare; il "
                             "segreto, se impostato, chiude con 403 (fase83 `_telegram_webhook`)",
    "/api/bunker/logout": "uscire e' idempotente: sempre 200 (fase83 `_bunker_logout`)",
    "/api/gate/logout": "uscire e' idempotente: sempre 200 (fase83 `_gate_logout`)",
    "/api/mcp": "JSON-RPC 2.0: un corpo vuoto e' un errore -32600 DENTRO un 200 (fase60); "
                "prenotare esige il quote_token firmato, come /api/concierge/book",
}

NON_GUARDA = (
    "le rotte a PREFISSO (`path.startswith(...)`: catalogo, recensioni, pagine): sono enumerate "
    "e stampate come NON MISURATE, perche' un prefisso non e' un indirizzo da chiamare",
    "l'asse «altro host» sul SITO VIVO: servirebbero due conti veri in produzione; si misura "
    "sul router locale con due host registrati davvero, e lo si dice",
    "la matrice per RUOLO degli operatori admin (fase192: chi puo' fare cosa fra gli admin): "
    "qui si prova «senza credenziali» e «altro host», non «operatore con ruolo sbagliato»",
    "le porte del BUNKER con una sessione VERA ma dall'IP sbagliato (la sessione e' legata "
    "all'IP): qui si prova con una sessione inventata",
    "cosa fa ogni rotta DOPO la porta: qui si misura solo se la porta si apre, non se dentro "
    "il conto e' giusto (quello lo fanno i test dedicati e il Giudice)",
    "le rotte pubbliche per progetto: la LISTA e' dichiarata a mano col motivo; una rotta nuova "
    "che non c'e' nella lista e non chiude la porta risulta NON DETERMINATA, e la casella "
    "resta rossa finche' qualcuno non la dichiara o la chiude",
    "le risposte 5xx del sito vivo: contano come «porta non aperta» per la sonda, ma un 5xx "
    "e' un difetto suo e viene stampato",
)


# --------------------------------------------------------------------------------------
# 1. LE ROTTE, DAL CODICE
# --------------------------------------------------------------------------------------
def rotte_dal_codice(percorso=None):
    """[(metodo, path, gestore)] per ogni `if metodo == "M" and path == "P": return self.G(`
    nel sorgente di `_instrada`; e a parte i PREFISSI (`startswith`), che non si chiamano."""
    percorso = percorso or os.path.join(RADICE, "fase83_server.py")
    with io.open(percorso, encoding="utf-8") as f:
        src = f.read()
    i = src.index("def _instrada(")
    fine = src.index('return 404, {"errore": "rotta_non_trovata"}', i)
    blocco = src[i:fine]
    esatte = []
    for m in re.finditer(r'metodo == "(\w+)" and path == "([^"]+)":\s*\n\s*return self\.(\w+)\(',
                         blocco):
        esatte.append((m.group(1), m.group(2), m.group(3)))
    prefissi = sorted(set(re.findall(r'path\.startswith\("([^"]+)"\)', blocco)))
    # Le rotte servite FUORI da `_instrada`, nel gestore HTTP (`u.path == "..."`, es. il
    # download binario della marca): si enumerano lo stesso, o una lista a mano le perderebbe.
    # Sono GET; non hanno un gestore del router, e sul router locale non si chiamano.
    for p in sorted(set(re.findall(r'u\.path == "(/api/[^"]+)"', src))):
        if not any(pp == p for _m, pp, _g in esatte):
            esatte.append(("GET", p, "do_GET"))
    return esatte, prefissi


def _gestori_con_oggetto(percorso=None):
    """I gestori del router che nominano un OGGETTO altrui (un annuncio, una prenotazione): solo
    su questi ha senso l'asse «altro host». Gli altri (password, stato del proprio conto...)
    lavorano sul conto di chi chiama e non hanno niente di A da proteggere."""
    percorso = percorso or os.path.join(RADICE, "fase83_server.py")
    with io.open(percorso, encoding="utf-8") as f:
        src = f.read()
    fuori = {}
    for m in re.finditer(r"\n    def (_\w+)\(self", src):
        nome = m.group(1)
        fine = src.find("\n    def ", m.end())
        corpo = src[m.start():fine if fine > 0 else None]
        # «prenotazione» da solo non basta: `_host_dati_fiscali` la nomina per trasferire i
        # propri payout e non riceve nessun oggetto altrui dal chiamante
        fuori[nome] = any(k in corpo for k in ("_verifica_proprieta(", "alloggio_id", "slug",
                                               "riferimento", "\"rif\""))
    return fuori


def riservata(path):
    return path.startswith(PREFISSI_RISERVATI) and path not in PUBBLICHE_PER_PROGETTO


# --------------------------------------------------------------------------------------
# 2. IL ROUTER LOCALE, con due host veri
# --------------------------------------------------------------------------------------
def _g(n):
    import datetime
    return (datetime.date.today() + datetime.timedelta(days=30 + n)).isoformat()


def sistema_locale():
    """Un sistema in una cartella temporanea, due host registrati dalle rotte VERE, un annuncio
    dell'host A. Torna (router, cartella, dati) — chi chiama cancella la cartella."""
    from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
    from fase83_server import crea_router
    from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
    d = tempfile.mkdtemp(prefix="esame_accessi_")
    # La marca temporale (fase184) si spegne SOLO per costruire questo sistema: fase81 legge
    # la variabile una volta, a `crea_sistema`; alle richieste il server guarda l'archivio.
    # Il valore di prima si rimette SUBITO: lasciato a "0", nella suite intera (un processo
    # solo) spegneva la marca a test_marca_temporale_server, test_qualifica_catena e
    # test_rotte_ostile — 23 rossi nella CI su 2c60533, tutti 503 marca_temporale_non_attiva.
    marca_prima = os.environ.get("MARCA_TEMPORALE")
    os.environ["MARCA_TEMPORALE"] = "0"
    kw = dict(abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
              bunker_password="SuperPw@1")
    for campo in ConfigCasaVIP.__dataclass_fields__:
        if campo.startswith("db_"):
            kw[campo] = os.path.join(d, campo + ".db")
    try:
        sis = crea_sistema(ConfigCasaVIP(**kw))
    finally:
        if marca_prima is None:
            os.environ.pop("MARCA_TEMPORALE", None)
        else:
            os.environ["MARCA_TEMPORALE"] = marca_prima
    router = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")

    def registra(email, ip):
        st, out = router.gestisci("POST", "/api/host/registrazione", {}, json.dumps({
            "email": email, "password": "password1", "accetta_termini": True,
            "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
            "versione": CONTRATTO_HOST_VERSIONE}), {"X-Forwarded-For": ip})
        if st != 201 or not out.get("token"):
            raise RuntimeError("registrazione host fallita: %s %s" % (st, out))
        return out["host_id"], {"X-Forwarded-For": ip, "X-Host-Token": out["token"]}

    hid_a, tok_a = registra("host-a@esame.test", "203.0.113.1")
    hid_b, tok_b = registra("host-b@esame.test", "203.0.113.2")
    slug = "casa-esame-a"
    st, out = router.gestisci("POST", "/api/host/pubblica", {}, json.dumps({
        "slug": slug, "titolo": "Casa esame A", "citta": "Roma", "paese": "IT",
        "cin": "IT058091C2X5V0ABCD", "descrizione": "annuncio dell'host A per l'esame",
        "prezzo_notte_cents": 30000, "capacita": 4, "politica_cancellazione": "flessibile",
        "tassa_pp_notte_cents": 150, "lat_micro": 41902782, "lon_micro": 12496366,
        "servizi": ["wifi"], "immagini": []}), tok_a)
    if st != 201:
        raise RuntimeError("pubblicazione dell'annuncio A fallita: %s %s" % (st, out))
    return router, d, {"hid_a": hid_a, "tok_a": tok_a, "hid_b": hid_b, "tok_b": tok_b,
                       "slug": slug}


def corpo_dell_altro_host(dati):
    """Un corpo plausibile che nomina SEMPRE l'annuncio dell'host A: cosi' la prova misura la
    proprieta', non la validazione dei campi."""
    s = dati["slug"]
    return {"alloggio_id": s, "slug": s, "alloggio": s, "giorno": _g(1), "unita_totali": 1,
            "prezzo_netto_cents": 1000, "da": _g(1), "a": _g(3), "riferimento": "BVIP-XXXX-XXXX",
            "rif": "BVIP-XXXX-XXXX", "stato": "pubblicato", "url": "https://esempio.test/c.ics",
            "ical": "BEGIN:VCALENDAR\nEND:VCALENDAR", "titolo": "x", "email": "host-a@esame.test",
            "nome_file": "x.png", "id": "1", "messaggio": "x", "testo": "x",
            "password_attuale": "password1", "password_nuova": "password2",
            "dati": {"slug": s, "titolo": "Casa di A riscritta da B", "citta": "Roma",
                     "prezzo_notte_cents": 1000, "capacita": 2, "descrizione": "x"}}


def letture_locali():
    """Ogni rotta esatta del router, chiamata SENZA credenziali (corpo `{}` se non e' GET) e,
    se riservata, con le credenziali dell'host B sull'annuncio dell'host A."""
    esatte, prefissi = rotte_dal_codice()
    con_oggetto = _gestori_con_oggetto()
    router, d, dati = sistema_locale()
    righe = []
    # Cio' che di A NON deve comparire nella risposta data a B: il suo annuncio, il suo id,
    # la sua email. Se compare, B ha letto (o toccato) roba di A.
    # come TOKEN JSON esatti (fra virgolette): uno slug DERIVATO da quello di A («casa-esame-a-2»,
    # generato dall'importazione) non e' lo slug di A e non deve far gridare
    impronte_di_a = ['"%s"' % dati["slug"], '"%s"' % dati["hid_a"], '"host-a@esame.test"']
    try:
        corpo_b = json.dumps(corpo_dell_altro_host(dati))
        q_b = {"alloggio": dati["slug"], "alloggio_id": dati["slug"], "slug": dati["slug"],
               "da": _g(0), "a": _g(10), "citta": "Roma", "rif": "BVIP-XXXX-XXXX",
               "riferimento": "BVIP-XXXX-XXXX", "id": "1", "notti": "2", "ospiti": "2"}
        for metodo, path, gestore in esatte:
            if gestore == "do_GET":
                righe.append({"metodo": metodo, "path": path, "gestore": gestore,
                              "senza": "NON MISURATA (servita fuori dal router)",
                              "altro_host": None, "applicabile": False})
                continue
            corpo = None if metodo == "GET" else "{}"
            try:
                # senza X-Forwarded-For: in locale niente buttafuori per IP (fase83
                # `_auth_con_rate`: «IP vuoto = nessun throttle»), cosi' ogni rotta e' misurata
                # per quello che fa lei, non per il lockout scattato tre rotte prima
                st, _ = router.gestisci(metodo, path, {}, corpo, {})
            except Exception as e:
                st = "ECCEZIONE %s" % type(e).__name__
            altro, perde_a, applicabile = None, False, False
            if riservata(path) and path.startswith("/api/host/"):
                applicabile = bool(con_oggetto.get(gestore))
                if applicabile:
                    try:
                        altro, risp = router.gestisci(metodo, path, q_b if metodo == "GET" else {},
                                                      None if metodo == "GET" else corpo_b,
                                                      dict(dati["tok_b"]))
                        testo = json.dumps(risp, default=str) if risp else ""
                        perde_a = any(x in testo for x in impronte_di_a)
                    except Exception as e:
                        altro = "ECCEZIONE %s" % type(e).__name__
            righe.append({"metodo": metodo, "path": path, "gestore": gestore, "senza": st,
                          "altro_host": altro, "altro_host_vede_A": perde_a,
                          "applicabile": applicabile})
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return {"rotte": righe, "prefissi": prefissi}


# --------------------------------------------------------------------------------------
# 3. IL SITO VIVO (solo sonde negative: nessuna credenziale vera esce da qui)
# --------------------------------------------------------------------------------------
def _chiedi_vivo(metodo, path, testate=None, timeout=25):
    corpo = b"{}" if metodo != "GET" else None
    req = urllib.request.Request(SITO + path, data=corpo, method=metodo,
                                 headers=dict({"User-Agent": "BookinVIP-esame-accessi/1.0",
                                               "Content-Type": "application/json"},
                                              **(testate or {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return "ERRORE %s" % type(e).__name__


def letture_vive(esatte=None):
    """Sul sito vivo: ogni rotta riservata senza credenziali; tre rotte con credenziali
    inventate (poche apposta: contano nel buttafuori); l'indirizzo di controllo."""
    esatte = esatte if esatte is not None else rotte_dal_codice()[0]
    righe = []
    for metodo, path, _g in esatte:
        if not riservata(path):
            continue
        righe.append({"metodo": metodo, "path": path, "senza": _chiedi_vivo(metodo, path)})
        time.sleep(PAUSA_VIVO_SEC)
    # Le tre sonde con credenziali INVENTATE: i percorsi si prendono dalle rotte ENUMERATE (la
    # prima GET riservata di ogni prefisso), mai scritti a mano. Alla prima misura, il
    # 2026-09-06, un percorso scritto a mano qui («/api/host/miei») non esisteva e rispondeva
    # 404: l'esame ha gridato sul suo stesso errore, ed e' proprio il difetto D17 che la
    # casella vieta.
    inventate = []
    for prefisso, testate in (("/api/admin/", {"X-Admin-Key": "chiave-inventata-xyz"}),
                              ("/api/bunker/", {"X-Bunker-Session": "sessione-inventata"}),
                              ("/api/host/", {"X-Host-Token": "gettone-inventato"})):
        scelta = [p for m, p, g in esatte if m == "GET" and p.startswith(prefisso)
                  and riservata(p) and g != "do_GET"]
        if not scelta:
            inventate.append({"metodo": "GET", "path": prefisso, "credenziali": list(testate)[0],
                              "stato": "NESSUNA ROTTA GET RISERVATA"})
            continue
        inventate.append({"metodo": "GET", "path": scelta[0], "credenziali": list(testate)[0],
                          "stato": _chiedi_vivo("GET", scelta[0], testate)})
        time.sleep(PAUSA_VIVO_SEC)
    controllo = _chiedi_vivo("GET", CONTROLLO_404)
    return {"riservate": righe, "inventate": inventate, "controllo_404": controllo}


def lista_p3_di_verifica_produzione():
    """I percorsi scritti A MANO in `verifica_produzione.p3_porte_chiuse` (letti dal sorgente)."""
    with io.open(os.path.join(QUI, "verifica_produzione.py"), encoding="utf-8") as f:
        src = f.read()
    i = src.index("def p3_porte_chiuse(")
    j = src.find("\ndef ", i + 10)
    return sorted(set(p.split("?")[0] for p in re.findall(r'"(/api/[^"]+)"', src[i:j])))


# --------------------------------------------------------------------------------------
# 4. I GIUDIZI (puri: letture -> passi)
# --------------------------------------------------------------------------------------
def _e2xx(st):
    return isinstance(st, int) and 200 <= st < 300


def giudica_scrive(letture):
    """Casella 1. (verde, passi, motivi, denominatore). Il denominatore e' il numero di rotte
    che scrivono (non GET) enumerate dal codice."""
    passi, aperte, indeterminate, dichiarate_2xx = [], [], [], []
    rotte = letture.get("rotte") or []
    scrivono = [r for r in rotte if r["metodo"] != "GET"]
    for r in scrivono:
        st = r["senza"]
        if _e2xx(st):
            if r["path"] in RISPONDONO_200_A_VUOTO:
                dichiarate_2xx.append("%s %s -> %s" % (r["metodo"], r["path"], st))
            else:
                aperte.append("%s %s -> %s" % (r["metodo"], r["path"], st))
            continue
        if st in CHIUSA or r["path"] in PUBBLICHE_PER_PROGETTO:
            continue
        indeterminate.append("%s %s -> %s" % (r["metodo"], r["path"], st))

    def passo(nome, ok, dettaglio=""):
        passi.append((nome, bool(ok), dettaglio))

    passo("il router ha rotte enumerate dal codice (piu' di 100)", len(rotte) > 100,
          "%d rotte esatte, %d prefissi non misurati" % (len(rotte), len(letture.get("prefissi") or [])))
    passo("nessuna rotta che scrive risponde 2xx senza identita' (salvo le %d dichiarate col motivo)"
          % len(RISPONDONO_200_A_VUOTO), not aperte,
          "; ".join(aperte) if aperte else "%d rotte che scrivono; 200 a vuoto dichiarati: %s"
          % (len(scrivono), "; ".join(dichiarate_2xx) or "nessuno"))
    passo("ogni rotta che scrive senza chiudere la porta (401/403) e' dichiarata pubblica per progetto",
          not indeterminate, "; ".join(indeterminate))
    motivi = ["%s (%s)" % (n, d) if d else n for n, ok, d in passi if not ok]
    return not motivi, passi, motivi, len(scrivono)


def giudica_matrice(letture):
    """Casella 2. Asse (a) senza credenziali, locale E vivo; asse (b) altro host, locale."""
    passi = []
    rotte = letture.get("rotte") or []
    ris = [r for r in rotte if riservata(r["path"]) and r.get("gestore") != "do_GET"]
    fuori_router = [r["path"] for r in rotte if riservata(r["path"]) and r.get("gestore") == "do_GET"]
    aperte_loc = ["%s %s -> %s" % (r["metodo"], r["path"], r["senza"]) for r in ris
                  if r["senza"] not in CHIUSA]
    con_altro = [r for r in ris if r.get("altro_host") is not None]
    # 2xx che MOSTRA i dati di A -> B ha letto roba di A (IDOR); 2xx senza traccia di A -> e'
    # la lista di B, non un buco (una rotta «i miei annunci» ignora il parametro e risponde 200)
    altro_vede_a = ["%s %s -> %s (la risposta nomina A)" % (r["metodo"], r["path"], r["altro_host"])
                    for r in con_altro if _e2xx(r["altro_host"]) and r.get("altro_host_vede_A")]
    altro_200_propri = ["%s %s" % (r["metodo"], r["path"]) for r in con_altro
                        if _e2xx(r["altro_host"]) and not r.get("altro_host_vede_A")]
    altro_spenti = ["%s %s -> 503" % (r["metodo"], r["path"]) for r in con_altro
                    if r["altro_host"] == 503]
    altro_indet = ["%s %s -> %s" % (r["metodo"], r["path"], r["altro_host"]) for r in con_altro
                   if not _e2xx(r["altro_host"]) and r["altro_host"] not in CHIUSA + (404, 503)]
    vive = letture.get("vivo")
    vive_ris = (vive or {}).get("riservate") or []
    aperte_vivo = ["%s %s -> %s" % (r["metodo"], r["path"], r["senza"]) for r in vive_ris
                   if r["senza"] not in CHIUSA]

    def passo(nome, ok, dettaglio=""):
        passi.append((nome, bool(ok), dettaglio))

    passo("ci sono rotte riservate enumerate dal codice", len(ris) > 30,
          "%d riservate nel router%s" % (len(ris), (" + %d servite fuori dal router, non misurate in "
                                                     "locale: %s" % (len(fuori_router), ", ".join(fuori_router)))
                                          if fuori_router else ""))
    passo("LOCALE: ogni rotta riservata senza credenziali risponde 401/403", not aperte_loc,
          "; ".join(aperte_loc))
    passo("LOCALE: nessuna rotta host mostra o tocca i dati di A quando chiama un ALTRO host",
          not altro_vede_a, "; ".join(altro_vede_a) if altro_vede_a else
          "%d rotte con un oggetto altrui provate; 200 con dati PROPRI (non di A): %d"
          % (len(con_altro), len(altro_200_propri)))
    passo("LOCALE: nessuna rotta NON DETERMINATA sull'asse «altro host» (validazione prima della proprieta')",
          not altro_indet, "; ".join(altro_indet) + ("; connettori SPENTI in locale (503, non misurabili "
                                                     "qui): %s" % "; ".join(altro_spenti) if altro_spenti else ""))
    passo("SITO VIVO: le letture ci sono", vive is not None and len(vive_ris) > 30,
          "%d rotte lette dal vivo" % len(vive_ris) if vive is not None else "NON MISURATO (--locale)")
    passo("SITO VIVO: ogni rotta riservata senza credenziali risponde 401/403",
          vive is not None and not aperte_vivo, "; ".join(aperte_vivo))
    motivi = ["%s (%s)" % (n, d) if d else n for n, ok, d in passi if not ok]
    return not motivi, passi, motivi, len(ris) + len(vive_ris)


def giudica_sonde(letture, p3=None):
    """Casella 3. Ogni sonda negativa sul sito vivo: 401/403, mai 404; il controllo: 404."""
    passi = []
    vive = letture.get("vivo")
    ris = (vive or {}).get("riservate") or []
    inv = (vive or {}).get("inventate") or []
    con_404 = ["%s %s" % (r["metodo"], r["path"]) for r in ris if r["senza"] == 404]
    non_chiuse = ["%s %s -> %s" % (r["metodo"], r["path"], r["senza"]) for r in ris
                  if r["senza"] not in CHIUSA]
    inv_ko = ["%s [%s] -> %s" % (r["path"], r["credenziali"], r["stato"]) for r in inv
              if r["stato"] not in CHIUSA]
    controllo = (vive or {}).get("controllo_404")
    p3 = p3 if p3 is not None else letture.get("p3") or []
    rotte_codice = set(r["path"] for r in (letture.get("rotte") or []))
    fuori = [p for p in p3 if rotte_codice and p not in rotte_codice]

    def passo(nome, ok, dettaglio=""):
        passi.append((nome, bool(ok), dettaglio))

    passo("SITO VIVO: le letture ci sono", vive is not None and len(ris) > 30,
          "%d sonde" % len(ris) if vive is not None else "NON MISURATO (--locale)")
    passo("l'indirizzo di controllo (che non esiste) risponde 404: il 404 e' distinguibile",
          controllo == 404, "%s -> %s" % (CONTROLLO_404, controllo))
    passo("nessuna sonda negativa riceve 404", vive is not None and not con_404, "; ".join(con_404))
    passo("ogni sonda negativa senza credenziali riceve 401/403", vive is not None and not non_chiuse,
          "; ".join(non_chiuse))
    passo("le sonde con credenziali INVENTATE ricevono 401/403", bool(inv) and not inv_ko,
          "; ".join(inv_ko) if inv_ko else "%d sonde" % len(inv))
    passo("la lista a mano di verifica_produzione.p3 sta dentro le rotte del codice",
          bool(p3) and not fuori, "; ".join(fuori) if fuori else "%d percorsi" % len(p3))
    motivi = ["%s (%s)" % (n, d) if d else n for n, ok, d in passi if not ok]
    return not motivi, passi, motivi, len(ris) + len(inv) + 1


GIUDIZI = {"scrive": giudica_scrive, "matrice": giudica_matrice, "sonde": giudica_sonde}


def condizione(casella):
    """Il testo ESATTO della casella, letto dal piano: una e una sola, o si ferma."""
    blocco = [b for b in BLOCCHI if b["ordine"] == BLOCCO]
    cond = blocco[0]["finito_quando"] if len(blocco) == 1 else ()
    trovate = [c for c in cond if MARCHE[casella] in str(c)]
    if len(trovate) != 1:
        raise ValueError("il Blocco %d ha %d caselle con «%s», ne serve esattamente una"
                         % (BLOCCO, len(trovate), MARCHE[casella]))
    return trovate[0]


# --------------------------------------------------------------------------------------
# 5. MISURA PRIMA SE STESSO (D18 punto 1)
# --------------------------------------------------------------------------------------
def precondizioni(con_rete=True, con_router=True):
    fuori = []
    for k in MARCHE:
        try:
            fuori.append(("la casella «%s» esiste nel piano, una sola" % MARCHE[k], True,
                          " ".join(str(condizione(k)).split())[:70]))
        except Exception as e:
            fuori.append(("la casella «%s» esiste nel piano, una sola" % MARCHE[k], False,
                          "%s: %s" % (type(e).__name__, e)))
    try:
        impronta = scheda.impronta_del_blocco(BLOCCO)
        fuori.append(("il blocco ha un'impronta", bool(impronta), impronta or "il piano non si legge"))
    except Exception as e:
        fuori.append(("il blocco ha un'impronta", False, str(e)))
    try:
        esatte, prefissi = rotte_dal_codice()
        fuori.append(("le rotte si leggono dal router (piu' di 100 esatte)", len(esatte) > 100,
                      "%d esatte, %d prefissi" % (len(esatte), len(prefissi))))
    except Exception as e:
        fuori.append(("le rotte si leggono dal router (piu' di 100 esatte)", False, str(e)))
    if con_router:
        try:
            _r, d, dati = sistema_locale()
            shutil.rmtree(d, ignore_errors=True)
            fuori.append(("il sistema locale si costruisce con due host e un annuncio", True,
                          "host A, host B, annuncio %s" % dati["slug"]))
        except Exception as e:
            fuori.append(("il sistema locale si costruisce con due host e un annuncio", False,
                          "%s: %s" % (type(e).__name__, e)))
    if con_rete:
        st = _chiedi_vivo("GET", CONTROLLO_404)
        fuori.append(("il sito vivo risponde 404 a un indirizzo inventato (il 404 e' distinguibile)",
                      st == 404, "%s%s -> %s" % (SITO, CONTROLLO_404, st)))
    return all(ok for _, ok, _ in fuori), fuori


# --------------------------------------------------------------------------------------
# 6. L'AUTOPROVA (D18 punto 2): letture costruite, nelle due direzioni
# --------------------------------------------------------------------------------------
def letture_finte(*, aperta=None, altro_200=None, altro_200_proprio=None, aperta_dichiarata=False,
                  indet=None, vivo_404=None, vivo_200=None, controllo=404, inventata_200=False,
                  p3_fuori=False, senza_vivo=False):
    rotte = []
    for i in range(60):
        rotte.append({"metodo": "GET", "path": "/api/host/lettura%d" % i, "gestore": "g",
                      "senza": 401, "altro_host": 403})
        rotte.append({"metodo": "POST", "path": "/api/host/scrittura%d" % i, "gestore": "g",
                      "senza": 401, "altro_host": 403})
    rotte.append({"metodo": "POST", "path": "/api/host/login", "gestore": "g", "senza": 422,
                  "altro_host": None})
    rotte.append({"metodo": "POST", "path": "/api/concierge/book", "gestore": "g", "senza": 400,
                  "altro_host": None})
    if aperta:
        rotte.append({"metodo": "POST", "path": aperta, "gestore": "g", "senza": 201, "altro_host": 403})
    if altro_200:
        rotte.append({"metodo": "POST", "path": altro_200, "gestore": "g", "senza": 401,
                      "altro_host": 200, "altro_host_vede_A": True})
    if altro_200_proprio:
        rotte.append({"metodo": "GET", "path": altro_200_proprio, "gestore": "g", "senza": 401,
                      "altro_host": 200, "altro_host_vede_A": False})
    if aperta_dichiarata:
        rotte.append({"metodo": "POST", "path": "/api/bunker/logout", "gestore": "g", "senza": 200,
                      "altro_host": None})
    if indet:
        rotte.append({"metodo": "POST", "path": indet, "gestore": "g", "senza": 422, "altro_host": 422})
    vive = [{"metodo": r["metodo"], "path": r["path"], "senza": 401} for r in rotte if riservata(r["path"])]
    if vivo_404:
        vive.append({"metodo": "GET", "path": vivo_404, "senza": 404})
    if vivo_200:
        vive.append({"metodo": "GET", "path": vivo_200, "senza": 200})
    inventate = [{"metodo": "GET", "path": "/api/admin/prenotazioni", "credenziali": "X-Admin-Key",
                  "stato": 200 if inventata_200 else 401}]
    vivo = None if senza_vivo else {"riservate": vive, "inventate": inventate, "controllo_404": controllo}
    p3 = ["/api/host/lettura1", "/api/bunker/inventata"] if p3_fuori else ["/api/host/lettura1"]
    return {"rotte": rotte, "prefissi": ["/api/catalogo/"], "vivo": vivo, "p3": p3}


def inietta_il_guasto(letture):
    """Le letture di un router con UNA porta aperta: una rotta host che scrive risponde 201
    senza credenziali (in locale e dal vivo)."""
    storte = json.loads(json.dumps(letture))
    for r in storte.get("rotte") or []:
        if r["metodo"] != "GET" and riservata(r["path"]):
            r["senza"] = 201
            break
    for r in (storte.get("vivo") or {}).get("riservate") or []:
        if r["metodo"] != "GET":
            r["senza"] = 200
            break
    return storte


def autoprova():
    casi = (
        ("scrive", "letture SANE", letture_finte(), True),
        ("scrive", "una rotta host scrive 201 senza credenziali", letture_finte(aperta="/api/host/x"), False),
        ("scrive", "una rotta NON DETERMINATA (422 senza credenziali)", letture_finte(indet="/api/host/y"), False),
        ("scrive", "un 200 a vuoto DICHIARATO (logout) resta verde", letture_finte(aperta_dichiarata=True), True),
        ("scrive", "il guasto iniettato", inietta_il_guasto(letture_finte()), False),
        ("matrice", "letture SANE", letture_finte(), True),
        ("matrice", "l'ALTRO host ottiene 200 CON i dati di A", letture_finte(altro_200="/api/host/z"), False),
        ("matrice", "l'ALTRO host ottiene 200 con i dati SUOI (lista propria)",
         letture_finte(altro_200_proprio="/api/host/miei"), True),
        ("matrice", "asse altro host NON DETERMINATO (422)", letture_finte(indet="/api/host/y"), False),
        ("matrice", "dal VIVO una riservata risponde 200", letture_finte(vivo_200="/api/admin/w"), False),
        ("matrice", "senza letture dal vivo (--locale)", letture_finte(senza_vivo=True), False),
        ("matrice", "il guasto iniettato", inietta_il_guasto(letture_finte()), False),
        ("sonde", "letture SANE", letture_finte(), True),
        ("sonde", "una sonda riceve 404", letture_finte(vivo_404="/api/admin/v"), False),
        ("sonde", "il controllo NON risponde 404 (200)", letture_finte(controllo=200), False),
        ("sonde", "credenziali inventate accettate (200)", letture_finte(inventata_200=True), False),
        ("sonde", "la lista p3 nomina una rotta che il codice non ha", letture_finte(p3_fuori=True), False),
        ("sonde", "senza letture dal vivo (--locale)", letture_finte(senza_vivo=True), False),
    )
    righe, riuscita = [], True
    for casella, nome, letture, atteso in casi:
        verde, _passi, motivi, den = GIUDIZI[casella](letture)
        ok = (verde == atteso)
        riuscita = riuscita and ok
        righe.append("   %-8s %-52s -> %-6s (atteso %-6s) den %d%s"
                     % (casella, nome, "VERDE" if verde else "ROSSO", "VERDE" if atteso else "ROSSO",
                        den, "" if ok else "   ⛔ NON E' QUELLO CHE DOVEVA DIRE: %s" % "; ".join(motivi)))
    # l'enumerazione: le rotte vengono dal codice, non da una lista
    try:
        esatte, _pref = rotte_dal_codice()
        ok = len(esatte) > 100 and any(p == "/api/split/paga" for _m, p, _h in esatte)
    except Exception:
        ok = False
    riuscita = riuscita and ok
    righe.append("   %-8s %-52s -> %s" % ("rotte", "enumerate dal sorgente di _instrada (>100, con /api/split/paga)",
                                          "OK" if ok else "⛔ NO"))
    return riuscita, righe


# --------------------------------------------------------------------------------------
def _stampa_non_guarda(letture=None):
    print("-" * 86)
    print("⛔ COSA QUESTO ESAME NON HA ESAMINATO (D18 punto 3)")
    for r in NON_GUARDA:
        print("   · %s" % r)
    for p in (letture or {}).get("prefissi") or []:
        print("   · rotta a PREFISSO non misurata: %s" % p)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    os.chdir(RADICE)
    scelte = [argv[argv.index("--casella") + 1]] if "--casella" in argv else list(MARCHE)
    for s in scelte:
        if s not in MARCHE:
            print("⛔ casella sconosciuta: %s (valide: %s)" % (s, ", ".join(MARCHE)))
            return 2
    locale = "--locale" in argv
    print("=" * 86)
    print("🧾 ESAME DEL BLOCCO 3 — accessi: %s" % ", ".join("«%s»" % MARCHE[s] for s in scelte))
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
        print("⛔ FERMO: `--con-guasto` non scrive. Serve a vedere l'esame gridare; registrare")
        print("   quel rosso metterebbe nella scheda una porta aperta apposta.")
        return 2

    da_file = argv[argv.index("--da-file") + 1] if "--da-file" in argv else None
    tutte_ok, righe = precondizioni(con_rete=(da_file is None and not locale),
                                    con_router=(da_file is None))
    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    for nome, ok, motivo in righe:
        print("  %-9s %-70s %s" % ("OK" if ok else "⛔ NO", nome, motivo))
    if not tutte_ok:
        print("-" * 86)
        print("VERDETTO: ⛔ FERMO — una precondizione non regge, quindi NON misuro e NON scrivo.")
        _stampa_non_guarda()
        print("=" * 86)
        return 2

    if da_file:
        with io.open(da_file, encoding="utf-8") as f:
            letture = json.load(f)
        print("LETTURE: dal file %s" % da_file)
    else:
        print("LETTURE DAL ROUTER LOCALE (sistema temporaneo, due host, un annuncio)...")
        letture = letture_locali()
        letture["p3"] = lista_p3_di_verifica_produzione()
        if locale:
            letture["vivo"] = None
            print("  --locale: il sito vivo NON viene interrogato (le caselle 2 e 3 restano rosse)")
        else:
            print("LETTURE DAL SITO VIVO %s (solo sonde negative, pausa %.2f s)..." % (SITO, PAUSA_VIVO_SEC))
            letture["vivo"] = letture_vive([(r["metodo"], r["path"], r["gestore"]) for r in letture["rotte"]])
        letture["ora"] = int(time.time())
        if "--salva" in argv:
            dove = argv[argv.index("--salva") + 1]
            with io.open(dove, "w", encoding="utf-8") as f:
                json.dump(letture, f, indent=1, ensure_ascii=False)
            print("  letture salvate in %s" % dove)
    if "--con-guasto" in argv:
        print("⚠️  PASSATA COL GUASTO DENTRO: una rotta che scrive risponde 2xx senza credenziali")
        letture = inietta_il_guasto(letture)

    rotte = letture.get("rotte") or []
    print("")
    print("ROTTE: %d esatte dal codice · %d che scrivono · %d riservate · %d pubbliche per progetto"
          % (len(rotte), sum(1 for r in rotte if r["metodo"] != "GET"),
             sum(1 for r in rotte if riservata(r["path"])),
             sum(1 for r in rotte if r["path"] in PUBBLICHE_PER_PROGETTO)))
    uscita = 0
    for s in scelte:
        verde, passi, motivi, den = GIUDIZI[s](letture)
        print("")
        print("— casella «%s» —" % MARCHE[s])
        for nome, ok, dettaglio in passi:
            print("  %s  %s%s" % ("OK  " if ok else "ROSSO", nome,
                                  ("  -> " + dettaglio[:600]) if dettaglio else ""))
        print("  VERDETTO: %s — %d passi su %d, denominatore %d"
              % ("✅ VERDE" if verde else "⛔ ROSSO", sum(1 for _n, ok, _d in passi if ok), len(passi), den))
        if "--scrivi" in argv:
            riga = scheda.registra(condizione(s), esito=verde, denominatore=den, comando=COMANDI[s],
                                   ordine=BLOCCO, motivo="; ".join(motivi)[:900] or None)
            print("  SCRITTA nella scheda: blocco %d · esito %s · denominatore %d · impronta %s"
                  % (riga["blocco"], riga["esito"], riga["denominatore"], riga["impronta"]))
        if not verde:
            uscita = 1
    if "--scrivi" not in argv:
        print("")
        print("(non ho scritto niente: aggiungi --scrivi per registrare nella scheda)")
    _stampa_non_guarda(letture)
    print("=" * 86)
    return uscita


if __name__ == "__main__":
    sys.exit(main())
