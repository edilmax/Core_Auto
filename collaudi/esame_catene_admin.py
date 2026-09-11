# -*- coding: utf-8 -*-
"""L'ESAME DELLE CATENE DEL PANNELLO ADMIN — il perimetro lo CONTA la macchina leggendo la
pagina, e per ogni voce pretende una catena dichiarata (bottone · soldi · archivio) e
PERCORSA anello per anello.

    python collaudi/esame_catene_admin.py                 misura e MOSTRA (tutto in-process)
    python collaudi/esame_catene_admin.py --scrivi        misura e SCRIVE la casella
    python collaudi/esame_catene_admin.py --perimetro     solo il conteggio dalla pagina, con le identita'
    python collaudi/esame_catene_admin.py --con-guasto    due guasti dentro: deve gridare, NON scrive
    python collaudi/esame_catene_admin.py --autoprova     il giudizio nelle due direzioni, senza banco

PERCHE' ESISTE (RIPRENDI_QUI, 10 settembre sera, parole del fondatore: «fare gli incroci
dall'inizio alla fine e non lasciare fuori niente»; «sia dal lato dei soldi sia dal lato dei
bottoni, perche' poi subentrano anche i database»). Per ogni gesto che una persona puo' fare
servono TRE colonne: il BOTTONE (premo questo: cosa deve succedere, e dove finisce?), i SOLDI
(quali importi si muovono, e cosa deve coincidere al centesimo?), l'ARCHIVIO (dove si scrive,
ci resta, si cancella, per quale legge e quanti anni?).

🔑 E LA COSA CHE RENDE VERO «NON CI SCAPPA NIENTE» NON E' COPRIRE LE VOCI DI OGGI: E' CHE A
   CONTARLE SIA LA MACCHINA. Un elenco scritto a mano copre tutto oggi e domani non sa del
   bottone numero 22 -- e non sbaglia: TACE. Quindi qui le rotte, i bottoni e i campi si
   LEGGONO da `deploy/admin.html` a ogni giro; le catene sono dichiarate in questo file, e
   ogni voce della pagina senza catena e' ROSSA quel giorno stesso. Vale anche al contrario:
   una catena dichiarata per una voce che la pagina non nomina piu' e' un elenco invecchiato,
   ed e' rossa uguale.

COME SI CONTA (sbaglio S4: un numero dichiara COSA conta):
  · ROTTE   = ogni `/api/...` distinta nominata nella pagina (HTML e script insieme);
  · BOTTONI = ogni tag `<button` della pagina, anche quelli dentro le stringhe di script che
              la pagina disegna a runtime (sono bottoni che una persona preme); l'identita' e'
              `#id`, se no la funzione dell'`onclick`, se no la classe;
  · CAMPI   = ogni `<input`, `<select` e `<textarea`, stessa identita' (gli id generati con
              `${i}` diventano `*`).
  ⚠️ Il 10/9 sera il foglio diceva «27 bottoni · 12 campi» senza il comando che li aveva
     contati: questo attrezzo li conta e STAMPA come, e il suo numero vale finche' non cambia
     la pagina.

LA PRIMA CATENA (foglio `CATENA_1_admin_annunci.txt`, scritto PRIMA di percorrerla): la voce
«Tutti gli annunci», cioe' `GET /api/admin/alloggi` + `POST /api/admin/alloggio_stato`. La
rotta cambia UN campo in UN archivio (`catalogo.alloggi.stato`); tutto il resto del prodotto
deve accorgersene DA SOLO leggendo quel campo. Gli anelli, ognuno una DIFFERENZA (prima non
c'e', dopo c'e'): porta · vede · sospendi · vetrina · prenota · host · ripubblica · esistenti
· traccia. La colonna SOLDI: sospendere non muove denaro ma tocca la PORTA del denaro -- se
[prenota] non regge, si incassa per una stanza che l'admin credeva chiusa: si prova col
preventivo E con la conferma, e con un preventivo firmato PRIMA della sospensione.

✅ IL DIFETTO VIVO CHE QUESTO ESAME HA TROVATO, e com'e' finito. L'anello [traccia] era ROSSO, e
   il difetto era del PRODOTTO: **riparato il 2026-09-11** con l'«autorizzato» del fondatore (4
   righe `ADMIN_ACTION` in `fase83_server.py`, una per gesto), nell'ordine di D20 -- prima la
   guardia `test_pipeline_ci.TestOgniGestoDellAdminLasciaLaSuaRiga`, vista ROSSA su tutti e
   quattro i gesti, poi la riparazione, poi verde. Lo stato di prima, misurato il 2026-09-10
   leggendo il corpo di ogni funzione admin (non una finestra di righe: il corpo fino al `def`
   successivo, perche' sconfinando il conto diceva il falso):
     · `_admin_alloggi` e `_admin_search` -- due LETTURE -- scrivono `AUDIT ... ip=...`;
     · `_admin_verifica_stato` e' l'unica SCRITTURA con la riga intera (`ADMIN_ACTION | OGGETTO |
       AZIONE | MOTIVO | IP`);
     · `_admin_rimborso` e `_admin_rimborsa_dovuto` scrivono l'ESITO (`RIMBORSO ESEGUITO rif=...
       importo=...`) ma non CHI l'ha fatto;
     · `_admin_alloggio_stato`, `_admin_storno_penale`, `_admin_controversia_risolvi` e
       `_admin_cancella_attivita` non scrivono NIENTE (solo le eccezioni isolate).
   La riga del bunker (`BUNKER: azione '%s' autorizzata ip=%s`) dava chi e che TIPO di azione, mai
   su quale oggetto -- e solo a bunker configurato. ⇒ Per quattro gesti su sette nessuna riga diceva
   *chi ha fatto cosa su cosa*: sospendere un annuncio, stornare una penale, decidere quanto torna
   all'ospite e cancellare un host non erano ricostruibili, mentre GUARDARE l'elenco degli annunci
   lo era.
   ⚠️ **Cosa resta, ed e' dichiarato:** `_admin_rimborso` e `_admin_rimborsa_dovuto` scrivono
   l'esito (`RIMBORSO ESEGUITO rif=... importo=...`) ma ancora **non l'ip di chi ha premuto**. Non
   e' stato toccato perche' l'autorizzazione era per quattro righe e lo scopo non si allarga da se'
   (ferrea 15): la' l'informazione del *cosa* esiste, mancava del tutto per gli altri quattro.

⛔ D18, LE QUATTRO CONDIZIONI DI UNO STRUMENTO CHE MISURA:
   1. misura PRIMA se stesso (`precondizioni`): senza la casella nel piano, senza la pagina o
      senza il banco si FERMA e non scrive;
   2. provato nelle DUE direzioni: `--con-guasto` inietta DUE guasti che colpiscono meta'
      diverse -- il concierge smette di guardare lo stato dell'annuncio (l'anello [prenota]
      deve gridare) e la pagina nomina una rotta in piu' (il perimetro deve gridare);
      `--autoprova` giudica perimetri e passi costruiti, senza banco;
   3. dichiara cosa NON ha esaminato: `NON_GUARDA`, stampato a ogni giro;
   4. e' sotto guardia: `test_pipeline_ci.TestLEsameDelleCateneAdminNonPuoBARARE`.

⛔ AMBIENTE INTATTO: il banco e' quello di `esame_percorso_ruoli` (salva e rimette `UPLOAD_DIR`
   e il fetch di Stripe); il guasto sul concierge sta sull'ISTANZA del banco, mai sulla classe.
"""
import io
import json
import logging
import os
import re
import shutil
import sys
import tempfile
from urllib.parse import unquote

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
import esame_percorso_ruoli as ruoli  # noqa: E402

BLOCCO = 3
MARCA = "CONTATI dalla pagina"
COMANDO = "python collaudi/esame_catene_admin.py --scrivi"
PAGINA = os.path.join(RADICE, "deploy", "admin.html")

ADMIN = ruoli.ADMIN
IP = ruoli.IP
PASSI = []

NON_GUARDA = (
    "la PAGINA come la disegna il browser: qui si legge il suo testo (rotte, bottoni, campi) e si "
    "misurano le risposte delle rotte JSON; i clic veri li fa `collaudi/clickthrough_pannelli.js`",
    "le voci del pannello HOST, del BUNKER (super admin) e del sito dell'OSPITE: il fondatore ha "
    "deciso l'ordine («si parte dalla prima voce del pannello admin e si scende»), e questo esame "
    "legge SOLO `deploy/admin.html`; le altre tre pagine avranno il loro perimetro",
    "le rotte che il pannello NON nomina ma il server espone (es. `/api/admin/partner`): un "
    "perimetro letto dalla pagina vede i gesti di una persona, non l'API intera -- quella la "
    "enumera dal codice `esame_accessi` (Blocco 3, caselle 1-3)",
    "le catene delle rotte DIVERSE da «Tutti gli annunci»: oggi sono dichiarate solo per la prima "
    "voce, e le altre risultano ROSSE per costruzione, non per un guasto -- e' lo stato vero",
    "la colonna ARCHIVIO oltre la dichiarazione: qui si scrive DOVE la voce scrive e se resta; che "
    "il diritto all'oblio raggiunga davvero quell'archivio lo misura la casella di `fase156_erasure` "
    "(Blocco 5), e i 27 archivi del server hanno ancora da avere la loro riga uno per uno",
    "l'impronta del Blocco 3 non copre `fase83_server`, `fase57_vetrina` e `fase59_concierge`, che "
    "questa catena attraversa: se cambiano, la casella NON scade da sola. Il limite e' dello "
    "schedario (le impronte sono per blocco), ed e' dichiarato qui perche' chi legge lo sappia",
    "QUALE voce e' entrata nel pannello: il cricchetto e' un NUMERO (le rotte senza catena non "
    "possono essere piu' di quante erano), quindi dice CHE una voce e' entrata, non quale -- quello "
    "lo dice il diff di `deploy/admin.html`. Un elenco scritto a mano direbbe anche quale, e in "
    "cambio tacerebbe il giorno che qualcuno si dimentica di aggiornarlo: e' lo scambio che il "
    "fondatore ha chiesto («a contarle deve essere la macchina»)",
)

#  L'ultimo giro, in forma leggibile da una guardia (la stampa serve a chi legge, non a un test).
ULTIMO = {}


def passo(anello, nome, ok, dettaglio=""):
    PASSI.append((anello, nome, bool(ok), dettaglio))
    print("  %s  [%s] %s%s" % ("OK  " if ok else "ROSSO", anello, nome,
                               ("  -> " + dettaglio) if dettaglio else ""))
    return bool(ok)


# --------------------------------------------------------------------------------------
# IL PERIMETRO: letto dalla pagina, mai da un elenco
# --------------------------------------------------------------------------------------
_RE_ROTTA = re.compile(r"/api/[a-z_/]+")
_RE_APERTURA = re.compile(r"<(button|input|select|textarea)\b", re.I)
_RE_ATTR = re.compile(r"""\b(id|class|onclick|name|type)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.S)
_RE_ONCLICK_FN = re.compile(r"(?:conScudo\s*\(\s*this\s*,\s*\(\s*\)\s*=>\s*)?([A-Za-z_]\w*)\s*\(")
_CLASSI_DI_STILE = {"btn-riga", "danger"}


def _corpo_del_tag(testo, inizio):
    """Dal nome del tag fino al `>` che lo chiude DAVVERO, ignorando i `>` dentro le stringhe.

    ⛔ PERCHE' NON UN `[^>]*`. Tre bottoni di questa pagina hanno una arrow function
    nell'`onclick` (`conScudo(this,()=>risolviCtr(...))`): il `>` di `=>` chiudeva il tag in
    anticipo, l'attributo arrivava tagliato a `conScudo(this,()=` e TRE gesti diversi
    finivano in UNA sola identita' anonima. Il perimetro non sbagliava un numero: TACEVA su
    due bottoni, che e' esattamente il difetto che questo attrezzo esiste per non avere.
    """
    i, n, virgoletta = inizio, len(testo), ""
    while i < n:
        c = testo[i]
        if virgoletta:
            if c == virgoletta:
                virgoletta = ""
        elif c in "\"'":
            virgoletta = c
        elif c == ">":
            return testo[inizio:i]
        i += 1
    return testo[inizio:]


def _tag_della_pagina(testo):
    """(tag, attributi) per ogni `<button|input|select|textarea` della pagina, script compreso."""
    for m in _RE_APERTURA.finditer(testo):
        yield m.group(1).lower(), _attributi(_corpo_del_tag(testo, m.end()))


def _attributi(testo):
    a = {}
    for m in _RE_ATTR.finditer(testo):
        a[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)
    return a


def _identita(tag, attr):
    """`#id` · se no la funzione dell'onclick · se no la classe non di stile · se no il tipo.
    Gli id generati a runtime (`pct_${i}`) diventano `pct_*`: sono UN campo disegnato N volte."""
    id_ = (attr.get("id") or "").strip()
    if id_:
        return "#" + re.sub(r"\$\{[^}]*\}", "*", id_)
    oc = attr.get("onclick") or ""
    m = _RE_ONCLICK_FN.search(oc)
    if m:
        return m.group(1) + "()"
    classi = (attr.get("class") or "").split()
    utili = [c for c in classi if c not in _CLASSI_DI_STILE]
    #  ⛔ Se NESSUNA classe resta, si ripiega su quelle di stile invece di lasciare la voce
    #     anonima: il bottone «Rimborsa» della tabella delle prenotazioni ha solo
    #     `class="danger btn-riga"` e lo script lo aggancia proprio con `button.danger`.
    #     Una voce anonima e' una voce su cui il perimetro TACE.
    if utili or classi:
        return "." + (utili or classi)[0]
    if attr.get("name"):
        return "@" + attr["name"]
    return "<%s type=%s>" % (tag, attr.get("type") or "?")


def perimetro(pagina=PAGINA, testo=None):
    """{rotte: [..], bottoni: {identita: n}, campi: {identita: n}} letti dalla pagina."""
    if testo is None:
        with io.open(pagina, encoding="utf-8") as f:
            testo = f.read()
    rotte = sorted(set(r.rstrip("/") for r in _RE_ROTTA.findall(testo)))
    bottoni, campi = {}, {}
    for tag, attr in _tag_della_pagina(testo):
        dest = bottoni if tag == "button" else campi
        ide = _identita(tag, attr)
        dest[ide] = dest.get(ide, 0) + 1
    return {"rotte": rotte, "bottoni": bottoni, "campi": campi}


# --------------------------------------------------------------------------------------
# LE CATENE DICHIARATE: tre colonne per ogni gesto. Scritte PRIMA, percorse dopo.
# --------------------------------------------------------------------------------------
class Catena(object):
    def __init__(self, voce, rotte, anelli, bottone, soldi, archivio, percorre=None):
        self.voce = voce            # come la legge una persona nel pannello
        self.rotte = tuple(rotte)   # le rotte che il gesto attraversa
        self.anelli = tuple(anelli)
        self.bottone = bottone      # colonna 1: premo questo, deve succedere questo
        self.soldi = soldi          # colonna 2: quali importi si muovono, cosa deve coincidere
        self.archivio = archivio    # colonna 3: dove scrive, ci resta, si cancella, per quale legge
        self.percorre = percorre    # la funzione che la percorre sul banco; None = scritta, mai percorsa


ANELLI_CATENA_1 = ("porta", "vede", "sospendi", "vetrina", "prenota", "host", "ripubblica",
                   "esistenti", "traccia")


def _chiedi(b, metodo, percorso, corpo=None, headers=None):
    """Come `Banco.g`, ma SPEZZA la query string prima di consegnarla al router.

    ⛔ `router.gestisci(metodo, path, query, corpo, headers)` vuole il path PURO e la query
       GIA' in un dizionario: dargli `"/api/catalogo?citta=Roma"` fa rispondere 404
       `rotta_non_trovata`. E un 404 qui somiglia in tutto a «la vetrina non mostra
       l'annuncio»: al primo giro quattro anelli di questa catena erano rossi per questo, e
       l'anello [vetrina] avrebbe potuto essere VERDE per il motivo sbagliato. L'ha trovato il
       DUE TEMPI (prima c'era, dopo no): col solo «dopo» era un verde che non aveva guardato.
    """
    percorso, _, q = percorso.partition("?")
    query = {}
    for pezzo in q.split("&"):
        if pezzo:
            k, _, v = pezzo.partition("=")
            query[unquote(k)] = unquote(v)
    return b.router.gestisci(metodo, percorso, query,
                             json.dumps(corpo) if corpo is not None else None, headers or {})


def percorre_catena_1(b, BH, con_guasto=False):
    """La voce «Tutti gli annunci»: sospendere un annuncio, e tutto il prodotto se ne accorge."""
    from collaudi.gare_estreme import _quote
    print("\n--- CATENA 1, «Tutti gli annunci»: sospendi -> vetrina, prenotazione, host, ripubblica ---")

    def admin_riga(slug):
        s, c = _chiedi(b, "GET", "/api/admin/alloggi?host_id=%s" % b.host_id, None, ADMIN)
        righe = [a for a in ((c or {}).get("alloggi") or []) if a.get("slug") == slug] if s == 200 else []
        return righe[0] if len(righe) == 1 else None

    def in_vetrina(slug):
        s, c = _chiedi(b, "GET", "/api/catalogo?citta=Roma&limit=50", None, {})
        trovati = [r for r in ((c or {}).get("risultati") or []) if r.get("slug") == slug] if s == 200 else []
        s_d, _ = b.g("GET", "/api/catalogo/" + slug, None, {})
        return len(trovati), s_d

    def host_stato(slug):
        s, c = b.g("GET", "/api/host/alloggi", None, b.tk)
        righe = [a for a in ((c or {}).get("alloggi") or []) if a.get("slug") == slug] if s == 200 else []
        return righe[0].get("stato") if len(righe) == 1 else None

    def prenotazioni_sul(slug):
        return [p for p in b.prenotazioni_admin() if p.get("alloggio_id") == slug]

    # -- prima: l'annuncio non c'e'; poi l'host lo pubblica e l'admin lo VEDE -------------
    slug = "casa-catena-uno"
    prima = admin_riga(slug)
    slug = b.alloggio(slug, 3, "2027-07-01", "2027-07-31")
    riga = admin_riga(slug)
    passo("vede", "l'annuncio pubblicato dall'host COMPARE nell'elenco dell'admin con stato "
                  "'pubblicato' (prima non c'era)",
          prima is None and riga is not None and riga.get("stato") == "pubblicato",
          "prima=%s dopo=%s" % (prima, (riga or {}).get("stato")))

    # una prenotazione PAGATA prima della sospensione, e un preventivo firmato prima
    rif, vt = b.pagata(slug, "2027-07-05", "2027-07-07")
    if not rif:
        raise RuntimeError("il banco non ha prodotto una prenotazione pagata")
    tok_prima = _quote(b.g, slug, "2027-07-10", "2027-07-12")
    vetrina_prima = in_vetrina(slug)
    host_prima = host_stato(slug)
    esistenti_prima = len(prenotazioni_sul(slug))
    s_g1, g1 = _chiedi(b, "GET", "/api/garanzia/stato?ref=" + rif, None, ADMIN)
    netto_prima = (b.payout_host().get("EUR") or {}).get("maturato")

    if con_guasto:
        # IL GUASTO 1, sull'ISTANZA del banco e mai sul codice: il concierge smette di guardare
        # lo stato dell'annuncio. E' esattamente il difetto che questa catena esiste per vedere
        # («la sospensione nascondeva dalla ricerca ma non bloccava le vendite», fase59:263).
        b.sis.concierge._alloggio_vendibile = lambda slug: True

    # -- la porta: senza chiave, senza secondo fattore, col ruolo 'supporto' ---------------
    corpo = {"slug": slug, "stato": "sospeso"}
    s_senza, _ = b.g("POST", "/api/admin/alloggio_stato", corpo, {})
    s_solo_admin, c_solo = b.g("POST", "/api/admin/alloggio_stato", corpo, ADMIN)
    b.g("POST", "/api/bunker/admin_accounts",
        {"azione": "crea", "email": "supporto@esame.it", "password": "password123",
         "ruolo": "supporto"}, BH)
    s_op, c_op = b.g("POST", "/api/admin/login", {"email": "supporto@esame.it", "password": "password123"})
    #  ⛔ GLI HEADER DELL'OPERATORE NON PORTANO LA CHIAVE ROOT, e non e' un dettaglio del banco:
    #     `_ruolo_operatore` su una richiesta che presenta `X-Admin-Key` legge «admin», perche'
    #     chi ha la chiave root E' root e il token d'operatore non lo declassa -- e' giusto cosi'.
    #     Al primo giro passavo tutt'e due e la rotta rispondeva 200: un rosso dell'attrezzo che
    #     somigliava in tutto a una scalata di privilegi (il difetto vero del 2026-07-28). La
    #     sessione del bunker resta, perche' quella e' legata all'IP, non alla chiave.
    op = ({"X-Admin-Op": (c_op or {}).get("op_token", ""),
           "X-Bunker-Session": BH.get("X-Bunker-Session", ""),
           "X-Forwarded-For": IP["X-Forwarded-For"]} if s_op == 200 else None)
    s_supp, c_supp = b.g("POST", "/api/admin/alloggio_stato", corpo, op) if op else (None, {})
    passo("porta", "senza chiave 401 · con la sola chiave 403 'bunker_richiesto' · col ruolo "
                   "'supporto' (anche dietro il bunker) 403 'permesso_negato_ruolo'",
          s_senza == 401 and s_solo_admin == 403 and (c_solo or {}).get("errore") == "bunker_richiesto"
          and s_supp == 403 and (c_supp or {}).get("errore") == "permesso_negato_ruolo",
          "senza=%s solo_admin=%s/%s supporto=%s/%s" % (s_senza, s_solo_admin, (c_solo or {}).get("errore"),
                                                        s_supp, (c_supp or {}).get("errore")))
    ancora = admin_riga(slug)
    passo("porta", "e nessuna delle tre porte chiuse ha cambiato lo stato",
          (ancora or {}).get("stato") == "pubblicato", "stato=%s" % (ancora or {}).get("stato"))

    # -- il bottone, col secondo fattore: e la traccia che lascia ------------------------
    registro = []

    class _Presa(logging.Handler):
        def emit(self, record):
            try:
                registro.append(record.getMessage())
            except Exception:
                registro.append(str(record.msg))
    presa = _Presa()
    log_server = logging.getLogger("core_auto.server")
    livello_prima = log_server.level
    log_server.addHandler(presa)
    log_server.setLevel(logging.DEBUG)
    try:
        s_sosp, c_sosp = b.g("POST", "/api/admin/alloggio_stato", corpo, BH)
    finally:
        log_server.removeHandler(presa)
        log_server.setLevel(livello_prima)
    dopo = admin_riga(slug)
    passo("sospendi", "col secondo fattore risponde 200 {stato: sospeso}, e nell'elenco dell'admin "
                      "lo stato E' CAMBIATO (prima 'pubblicato', dopo 'sospeso')",
          s_sosp == 200 and (c_sosp or {}).get("stato") == "sospeso" and (dopo or {}).get("stato") == "sospeso",
          "http=%s risposta=%s elenco=%s" % (s_sosp, (c_sosp or {}).get("stato"), (dopo or {}).get("stato")))
    righe_gesto = [r for r in registro if slug in r and "sospeso" in r]
    passo("traccia", "il gesto lascia UNA riga che unisce CHI (ip), QUANDO e SU COSA (lo slug e lo stato "
                     "nuovo), come fa la verifica KYC (`ADMIN_ACTION | OGGETTO | AZIONE | IP`)",
          len(righe_gesto) >= 1 and any("ip" in r.lower() for r in righe_gesto),
          "righe scritte durante il gesto=%d, con slug e stato=%d%s"
          % (len(registro), len(righe_gesto),
             ("; l'unica riga: %r" % registro[0][:90]) if registro and not righe_gesto else ""))

    # -- la vetrina, la prenotazione, l'host: si accorgono DA SOLI -------------------------
    vetrina_dopo = in_vetrina(slug)
    passo("vetrina", "l'annuncio sospeso SPARISCE dalla ricerca pubblica e la sua scheda risponde 404 "
                     "(prima c'era: ricerca 1, scheda 200)",
          vetrina_prima == (1, 200) and vetrina_dopo == (0, 404),
          "prima=%s dopo=%s" % (vetrina_prima, vetrina_dopo))

    s_q, c_q = b.g("POST", "/api/concierge/quote",
                   {"alloggio_id": slug, "check_in": "2027-07-15", "check_out": "2027-07-17", "party": 2})
    s_b, c_b = b.g("POST", "/api/concierge/book", {"quote_token": tok_prima, "email": "ospite2@esame.it"})
    passo("prenota", "un ospite NON riesce a prenotarlo: il preventivo rifiuta (404) E la conferma con un "
                     "preventivo firmato PRIMA della sospensione rifiuta (404) -- e' l'anello che vale i soldi",
          bool(tok_prima) and s_q == 404 and (c_q or {}).get("errore") == "alloggio_non_disponibile"
          and s_b == 404 and (c_b or {}).get("errore") == "alloggio_non_disponibile",
          "preventivo_prima=%s quote=%s/%s book=%s/%s" % (bool(tok_prima), s_q, (c_q or {}).get("errore"),
                                                          s_b, (c_b or {}).get("errore")))

    host_dopo = host_stato(slug)
    passo("host", "l'host lo vede 'sospeso' nel SUO pannello (prima 'pubblicato'): non lo scopre dai clienti",
          host_prima == "pubblicato" and host_dopo == "sospeso", "prima=%s dopo=%s" % (host_prima, host_dopo))

    # -- cio' che esisteva gia' non si tocca -----------------------------------------------
    s_g2, g2 = _chiedi(b, "GET", "/api/garanzia/stato?ref=" + rif, None, ADMIN)
    netto_dopo = (b.payout_host().get("EUR") or {}).get("maturato")
    esistenti_dopo = len(prenotazioni_sul(slug))
    st1 = (g1 or {}).get("stato") if isinstance(g1, dict) else None
    st2 = (g2 or {}).get("stato") if isinstance(g2, dict) else None
    passo("esistenti", "la prenotazione GIA' pagata resta: stessa riga per l'admin, stessa garanzia, stesso "
                       "netto maturato dell'host (sospendere non cancella un contratto gia' fatto)",
          esistenti_prima == 1 and esistenti_dopo == 1 and s_g1 == 200 and s_g2 == 200 and st1 == st2
          and netto_prima is not None and netto_prima == netto_dopo,
          "righe %d->%d garanzia %s->%s netto %s->%s" % (esistenti_prima, esistenti_dopo, st1, st2,
                                                       netto_prima, netto_dopo))

    # -- le due direzioni: ripubblicare rimette tutto ----------------------------------------
    s_pub, c_pub = b.g("POST", "/api/admin/alloggio_stato", {"slug": slug, "stato": "pubblicato"}, BH)
    vetrina_ri = in_vetrina(slug)
    tok_dopo = _quote(b.g, slug, "2027-07-20", "2027-07-22")
    riga_ri = admin_riga(slug)
    passo("ripubblica", "rimesso 'pubblicato': torna in vetrina (ricerca 1, scheda 200), il preventivo torna "
                        "a firmare, e l'admin lo rilegge 'pubblicato' (sospendere non e' irreversibile)",
          s_pub == 200 and vetrina_ri == (1, 200) and bool(tok_dopo) and (riga_ri or {}).get("stato") == "pubblicato",
          "http=%s vetrina=%s preventivo=%s elenco=%s" % (s_pub, vetrina_ri, bool(tok_dopo),
                                                          (riga_ri or {}).get("stato")))


CATENA_1 = Catena(
    voce="Tutti gli annunci: pubblica / sospendi",
    rotte=("/api/admin/alloggi", "/api/admin/alloggio_stato"),
    anelli=ANELLI_CATENA_1,
    bottone="premo Sospendi (o Pubblica) su una riga: la rotta cambia il campo `stato` di quell'annuncio "
            "nel catalogo; la vetrina, il preventivo, la conferma e il pannello dell'host se ne accorgono "
            "da soli leggendo quel campo; l'admin rilegge lo stato nuovo nell'elenco",
    soldi="non muove denaro. Ma e' la PORTA del denaro: se [prenota] non regge si incassa per una stanza che "
          "l'admin credeva chiusa. Le prenotazioni gia' pagate non cambiano di un centesimo (netto maturato "
          "dell'host uguale prima e dopo)",
    archivio="scrive SOLO `catalogo.alloggi.stato` (+ `aggiornato_ts`), archivio `c.db`/catalogo; l'inventario "
             "delle notti resta com'e' (chi impedisce la vendita e' il controllo sullo stato, anello [prenota]). "
             "Nessun dato personale nuovo: niente da cancellare per l'oblio, niente da conservare per legge. "
             "La traccia del gesto (chi/quando/cosa) va nel registro del server, anello [traccia]",
    percorre=percorre_catena_1,
)

#  ⛔ Una rotta qui che la pagina non nomina piu' e' ROSSA (dichiarazione invecchiata).
CATENE = {rotta: CATENA_1 for rotta in CATENA_1.rotte}

#  Ogni BOTTONE e ogni CAMPO della pagina va attribuito: alla rotta che il gesto attraversa
#  (e allora la sua catena e' quella della rotta), oppure a `PAGINA_SOLA` con il perche' --
#  non manda niente al server da se'. Una voce NON attribuita e' rossa: e' il «bottone numero
#  22», cioe' un gesto entrato nel pannello che nessuno ha guardato.
#  ⛔ Le identita' le stampa `--perimetro`: si prendono da li', mai a memoria (sbaglio S2).
PAGINA_SOLA = "pagina"

BOTTONI = {
    "#btnCarica": "/api/admin/prenotazioni",          # ricarica: verifiche + annunci + prenotazioni
    "#btnLogout": "/api/gate/logout",                 # chiude anche la sessione bunker
    "#btnSearch": "/api/admin/search",
    "#sr_prec": "/api/admin/search",
    "#sr_succ": "/api/admin/search",
    "#btnAudit": "/api/admin/audit",
    "auditApri()": "/api/admin/audit",                # x2: il tasto e i candidati di un id ambiguo
    #  ⛔ QUESTA RIGA L'AVEVO DIMENTICATA, e l'ha trovata il censimento al primo giro: il
    #     bottone «storna» vive DENTRO la scheda audit, e a occhio non si vede. E' la prova in
    #     piccolo di perche' la mappa non puo' essere l'unica fonte -- una lista scritta a mano
    #     non sbaglia: TACE. Qui la pagina ha parlato per lei.
    "stornaPenale()": "/api/admin/storno_penale",
    "#btnKyc": "/api/admin/verifiche",
    "verDettaglio()": "/api/admin/verifiche/dettaglio",
    "verStato()": "/api/admin/verifica_stato",         # x3: approva · revoca · ri-approva
    "verFascicolo()": "/api/admin/verifiche/fascicolo",
    "#btnBunker": "/api/bunker/login",
    "#btnCerca": "/api/admin/alloggi",
    "#al_prec": "/api/admin/alloggi",
    "#al_succ": "/api/admin/alloggi",
    "srFiltraId()": "/api/admin/alloggi",             # imposta il filtro e RICARICA l'elenco
    "srFiltraHost()": "/api/admin/alloggi",
    ".alStato": "/api/admin/alloggio_stato",           # x2: sospendi · pubblica
    ".alDel": PAGINA_SOLA,                            # NON cancella: seleziona l'host nel riquadro rosso
    "srCopia()": PAGINA_SOLA,                         # copia il testo negli appunti
    "#btnCampagna": "/api/marketing/campagna",
    "#btnRimborsiDovuti": "/api/admin/rimborsi_dovuti",
    "eseguiRimborsoDovuto()": "/api/admin/rimborsa_dovuto",
    "#btnControversie": "/api/admin/controversie",
    "vediChat()": "/api/admin/messaggi",
    "risolviCtr()": "/api/admin/controversia/risolvi",
    ".danger": "/api/admin/rimborso",                 # «Rimborsa» nella tabella delle prenotazioni
    "#btnCancellaHost": "/api/admin/cancella_attivita",
}

CAMPI = {
    "#adminkey": "/api/admin/prenotazioni",           # la chiave: scriverla RICARICA il pannello
    "#sr_q": "/api/admin/search",
    "#ky_q": "/api/admin/verifiche",
    "#ky_st": "/api/admin/verifiche",
    "#bunkerpw": "/api/bunker/login",
    "#f_id": "/api/admin/alloggi",
    "#f_host": "/api/admin/alloggi",
    "#f_stato": "/api/admin/alloggi",
    ".lng": "/api/marketing/campagna",                # x5: le lingue della campagna
    "#pct_*": "/api/admin/controversia/risolvi",       # la % e gli euro sono DUE vie allo stesso
    "#eur_*": "/api/admin/controversia/risolvi",       #   campo: la cifra da dare al cliente
    "#del_host": "/api/admin/cancella_attivita",
    "#lang": PAGINA_SOLA,                             # lingua dell'interfaccia (localStorage)
}

#  ⛔ IL CRICCHETTO, e non e' un elenco scritto a mano. Le rotte senza catena non si elencano:
#     si CONTANO (rotte della pagina meno quelle con una catena percorsa). Questo numero puo'
#     solo CALARE: se domani entra nel pannello una voce nuova, il conto sale, supera il tetto
#     e l'esame dice «e' entrata una voce senza catena» quel giorno stesso -- mentre un elenco
#     scritto a mano sarebbe rimasto zitto. Un tetto abbassato e' lavoro fatto; alzarlo e' un
#     gesto che si vede nel diff e va spiegato.
#     Misurato il 2026-09-10 con `python collaudi/esame_catene_admin.py --perimetro`:
#     21 rotte nella pagina, 2 con la catena 1 -> 19 senza.
ROTTE_SENZA_CATENA_TETTO = 19


# --------------------------------------------------------------------------------------
# IL GIUDIZIO (puro: riceve il perimetro, le dichiarazioni e i passi; rende il verdetto)
# --------------------------------------------------------------------------------------
def censimento(per, catene=None, bottoni=None, campi=None, tetto=None):
    """IL CANCELLO: ogni voce della pagina e' censita, e il debito non e' cresciuto.

    (verde, motivi, denominatore, scoperte). Qui NON si pretende che le catene esistano --
    quello e' l'altro verdetto: si pretende che nessuna voce sia **fuori dal censimento** e
    che le rotte senza catena non siano piu' di quante erano. E' il pezzo che grida il giorno
    del bottone numero 22, ed e' l'unico che puo' essere verde mentre il lavoro e' in corso.
    """
    catene = CATENE if catene is None else catene
    bottoni = BOTTONI if bottoni is None else bottoni
    campi = CAMPI if campi is None else campi
    tetto = ROTTE_SENZA_CATENA_TETTO if tetto is None else tetto
    motivi = []
    rotte = list(per["rotte"])
    if not rotte:
        return False, ["la pagina non nomina NESSUNA rotta: un perimetro vuoto non e' una misura, "
                       "e' una pagina che non si e' riusciti a leggere"], 0, []
    for r in sorted(catene):
        if r not in rotte:
            motivi.append("catena orfana (la pagina non nomina piu' la rotta): %s" % r)
    for r in rotte:
        if r in catene and catene[r].percorre is None:
            motivi.append("catena scritta ma mai percorsa: %s" % r)
    for nome, visti, dichiarati in (("bottone", per["bottoni"], bottoni), ("campo", per["campi"], campi)):
        for ide in sorted(visti):
            dest = dichiarati.get(ide)
            if dest is None:
                motivi.append("%s MAI CENSITO (e' entrato nel pannello e nessuno l'ha guardato): %s"
                              % (nome, ide))
            elif dest != PAGINA_SOLA and dest not in rotte:
                motivi.append("%s attribuito a una rotta che la pagina non nomina piu': %s -> %s"
                              % (nome, ide, dest))
        for ide in sorted(dichiarati):
            if ide not in visti:
                motivi.append("%s fantasma (dichiarato, ma la pagina non lo ha): %s" % (nome, ide))
    scoperte = [r for r in rotte if r not in catene or catene[r].percorre is None]
    if len(scoperte) > tetto:
        motivi.append("le rotte senza catena sono %d e il tetto dichiarato e' %d: una voce NUOVA e' "
                      "entrata nel pannello senza la sua catena. Il cricchetto dice CHE e' entrata, "
                      "non QUALE: le scoperte di adesso sono [%s] -- la nuova si trova nel diff di "
                      "deploy/admin.html" % (len(scoperte), tetto, ", ".join(scoperte)))
    den = len(rotte) + sum(per["bottoni"].values()) + sum(per["campi"].values())
    return (not motivi), motivi, den, scoperte


def giudica_perimetro(per, catene=None, bottoni=None, campi=None, tetto=None):
    verde, motivi, den, _scoperte = censimento(per, catene, bottoni, campi, tetto)
    return verde, motivi, den


giudica = ruoli.giudica          # lo stesso giudizio sugli anelli: un anello senza passi e' NON misurato
passi_finti = ruoli.passi_finti


def condizione():
    b = [x for x in BLOCCHI if x["ordine"] == BLOCCO]
    cond = b[0]["finito_quando"] if len(b) == 1 else ()
    trovate = [c for c in cond if MARCA in str(c)]
    if len(trovate) != 1:
        raise ValueError("il blocco %d ha %d caselle con «%s», ne serve esattamente una"
                         % (BLOCCO, len(trovate), MARCA))
    return trovate[0]


# --------------------------------------------------------------------------------------
# MISURA PRIMA SE STESSO (D18 punto 1)
# --------------------------------------------------------------------------------------
def precondizioni(pagina=PAGINA):
    fuori = []
    try:
        fuori.append(("la casella esiste nel piano, una sola", True, " ".join(condizione().split())[:66]))
    except Exception as e:
        fuori.append(("la casella esiste nel piano, una sola", False, "%s: %s" % (type(e).__name__, e)))
    try:
        impronta = scheda.impronta_del_blocco(BLOCCO)
        fuori.append(("il blocco %d ha un'impronta" % BLOCCO, bool(impronta),
                      impronta or "il piano non si legge: una misura senza ancoraggio non vale"))
    except Exception as e:
        fuori.append(("il blocco %d ha un'impronta" % BLOCCO, False, str(e)))
    try:
        per = perimetro(pagina)
        fuori.append(("la pagina si legge e nomina almeno una rotta, un bottone e un campo",
                      bool(per["rotte"]) and bool(per["bottoni"]) and bool(per["campi"]),
                      "%s: rotte %d · bottoni %d · campi %d" % (os.path.relpath(pagina, RADICE), len(per["rotte"]),
                                                                sum(per["bottoni"].values()), sum(per["campi"].values()))))
    except Exception as e:
        fuori.append(("la pagina si legge e nomina almeno una rotta, un bottone e un campo", False,
                      "%s: %s" % (type(e).__name__, e)))
    ok_banco, fuori_banco = ruoli.precondizioni()
    fuori.append(("il banco di `esame_percorso_ruoli` regge le sue precondizioni", ok_banco,
                  "" if ok_banco else "; ".join("%s: %s" % (n, d) for n, ok, d in fuori_banco if not ok)))
    return all(ok for _, ok, _ in fuori), fuori


# --------------------------------------------------------------------------------------
# L'AUTOPROVA (D18 punto 2): perimetri e passi costruiti, nelle due direzioni, senza banco
# --------------------------------------------------------------------------------------
def _perimetro_finto(rotte=("/api/a", "/api/b"), bottoni=("#x",), campi=("#y",)):
    return {"rotte": list(rotte), "bottoni": {b: 1 for b in bottoni}, "campi": {c: 1 for c in campi}}


def autoprova():
    percorsa = Catena("v", ("/api/a", "/api/b"), ("uno",), "b", "s", "a", percorre=lambda *a, **k: None)
    scritta = Catena("v", ("/api/a", "/api/b"), ("uno",), "b", "s", "a", percorre=None)
    tutte = {"/api/a": percorsa, "/api/b": percorsa}
    sola_a = {"/api/a": percorsa}
    casi = [
        ("censimento: ogni voce censita, debito zero", _perimetro_finto(), tutte,
         {"#x": "/api/a"}, {"#y": PAGINA_SOLA}, 0, True),
        ("censimento: una rotta senza catena, DENTRO il tetto", _perimetro_finto(), sola_a,
         {"#x": "/api/a"}, {"#y": PAGINA_SOLA}, 1, True),
        ("censimento: una rotta senza catena, FUORI dal tetto", _perimetro_finto(), sola_a,
         {"#x": "/api/a"}, {"#y": PAGINA_SOLA}, 0, False),
        ("censimento: una rotta NUOVA oltre il tetto", _perimetro_finto(rotte=("/api/a", "/api/b", "/api/c")),
         tutte, {"#x": "/api/a"}, {"#y": PAGINA_SOLA}, 0, False),
        ("censimento: catena scritta, mai percorsa", _perimetro_finto(), {"/api/a": scritta, "/api/b": scritta},
         {"#x": "/api/a"}, {"#y": PAGINA_SOLA}, 2, False),
        ("censimento: catena orfana", _perimetro_finto(rotte=("/api/a",)), tutte, {"#x": "/api/a"},
         {"#y": PAGINA_SOLA}, 0, False),
        ("censimento: un bottone in piu' nella pagina", _perimetro_finto(bottoni=("#x", "#z")), tutte,
         {"#x": "/api/a"}, {"#y": PAGINA_SOLA}, 0, False),
        ("censimento: un bottone fantasma", _perimetro_finto(), tutte, {"#x": "/api/a", "#w": "/api/a"},
         {"#y": PAGINA_SOLA}, 0, False),
        ("censimento: un campo mai censito", _perimetro_finto(), tutte, {"#x": "/api/a"}, {}, 0, False),
        ("censimento: bottone attribuito a una rotta ignota", _perimetro_finto(), tutte, {"#x": "/api/zz"},
         {"#y": PAGINA_SOLA}, 0, False),
        ("censimento: pagina senza rotte", _perimetro_finto(rotte=()), {}, {"#x": PAGINA_SOLA},
         {"#y": PAGINA_SOLA}, 0, False),
    ]
    righe, riuscita = [], True
    for nome, per, cat, bot, cam, tetto, atteso in casi:
        verde, motivi, den, _sc = censimento(per, cat, bot, cam, tetto)
        ok = (verde == atteso)
        riuscita = riuscita and ok
        righe.append("   %-52s -> %-6s (atteso %-6s) denominatore %d%s"
                     % (nome, "VERDE" if verde else "ROSSO", "VERDE" if atteso else "ROSSO", den,
                        "" if ok else "   ⛔ NON E' QUELLO CHE DOVEVA DIRE: %s" % "; ".join(motivi)))
    anelli = ANELLI_CATENA_1
    for nome, passi, atteso in (("anelli: tutti verdi", passi_finti(anelli), True),
                                ("anelli: [prenota] ROSSO", passi_finti(anelli, rossi=("prenota",)), False),
                                ("anelli: [traccia] NON misurato", passi_finti(anelli, senza=("traccia",)), False),
                                ("anelli: nessun passo", [], False)):
        verde, motivi, den = giudica(passi, anelli)
        ok = (verde == atteso)
        riuscita = riuscita and ok
        righe.append("   %-52s -> %-6s (atteso %-6s) denominatore %d%s"
                     % (nome, "VERDE" if verde else "ROSSO", "VERDE" if atteso else "ROSSO", den,
                        "" if ok else "   ⛔ NON E' QUELLO CHE DOVEVA DIRE: %s" % "; ".join(motivi)))
    return riuscita, righe


# --------------------------------------------------------------------------------------
def _stampa_perimetro(per):
    print("PERIMETRO letto da deploy/admin.html (contato adesso, non ricordato)")
    print("  rotte distinte: %d   ·   con una catena percorsa: %d   ·   senza: %d (tetto %d)"
          % (len(per["rotte"]), len([r for r in per["rotte"] if r in CATENE]),
             len([r for r in per["rotte"] if r not in CATENE]), ROTTE_SENZA_CATENA_TETTO))
    for r in per["rotte"]:
        print("     %-40s %s" % (r, ("catena: " + CATENE[r].voce) if r in CATENE else "— senza catena"))
    print("  bottoni (tag <button>, anche quelli disegnati dallo script): %d in %d identita'"
          % (sum(per["bottoni"].values()), len(per["bottoni"])))
    for ide in sorted(per["bottoni"]):
        print("     %-26s x%-2d %s" % (ide, per["bottoni"][ide], BOTTONI.get(ide, "⛔ MAI CENSITO")))
    print("  campi (input/select/textarea): %d in %d identita'" % (sum(per["campi"].values()), len(per["campi"])))
    for ide in sorted(per["campi"]):
        print("     %-26s x%-2d %s" % (ide, per["campi"][ide], CAMPI.get(ide, "⛔ MAI CENSITO")))


def _stampa_non_guarda():
    print("-" * 86)
    print("⛔ COSA QUESTO ESAME NON HA ESAMINATO (D18 punto 3)")
    for r in NON_GUARDA:
        print("   · %s" % r)


def main(argv=None):
    global PASSI
    argv = list(sys.argv[1:] if argv is None else argv)
    os.chdir(RADICE)
    scrivi = "--scrivi" in argv
    con_guasto = "--con-guasto" in argv
    if con_guasto and scrivi:
        print("⛔ FERMO: `--con-guasto` non scrive. Serve a vedere l'esame gridare; registrare")
        print("   quel rosso metterebbe nella scheda un guasto costruito apposta.")
        return 2

    print("=" * 86)
    print("🧾 ESAME DELLE CATENE DEL PANNELLO ADMIN — il perimetro lo conta la pagina, ogni voce vuole la sua catena")
    print("=" * 86)

    if "--autoprova" in argv:
        print("🔁 AUTOPROVA — il giudizio nelle due direzioni, senza banco (D18 punto 2)")
        riuscita, righe = autoprova()
        for r in righe:
            print(r)
        _stampa_non_guarda()
        print("=" * 86)
        print("VERDETTO: %s" % ("✅ il giudizio grida sulle voci scoperte e tace su quelle coperte"
                                if riuscita else "⛔ IL GIUDIZIO NON SA DISTINGUERE"))
        return 0 if riuscita else 1

    if "--perimetro" in argv:
        per = perimetro()
        _stampa_perimetro(per)
        verde, motivi, den, scoperte = censimento(per)
        print("\nVERDETTO censimento: %s — voci guardate %d, rilievi %d, rotte senza catena %d"
              % ("✅ VERDE" if verde else "⛔ ROSSO", den, len(motivi), len(scoperte)))
        for m in motivi:
            print("   perche': %s" % m)
        return 0 if verde else 1

    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    ok_pre, fuori = precondizioni()
    for nome, ok, dettaglio in fuori:
        print("  %s      %-62s %s" % ("OK  " if ok else "ROSSO", nome, dettaglio))
    if not ok_pre:
        print("VERDETTO: ⛔ FERMO — le precondizioni non reggono, non misuro e non scrivo")
        return 2

    per = perimetro()
    if con_guasto:
        # IL GUASTO 2: la pagina nomina una rotta in piu', e nessuno le ha scritto la catena.
        # E' il «bottone numero 22» del foglio: il perimetro deve gridare quel giorno stesso.
        per["rotte"] = sorted(per["rotte"] + ["/api/admin/rotta_nata_ieri"])
    print()
    _stampa_perimetro(per)
    verde_per, motivi_per, den_per, scoperte = censimento(per)

    PASSI = []
    salvato = ruoli._ambiente_salvato()
    d = tempfile.mkdtemp(prefix="catene_")
    esiti = []
    try:
        b = ruoli.Banco(d)
        s_bunker, BH = b.bunker_headers()
        if s_bunker != 200:
            raise RuntimeError("il bunker del banco non apre: http=%s" % s_bunker)
        fatte = []
        for r in per["rotte"]:
            cat = CATENE.get(r)
            if cat is None or cat.percorre is None or any(cat is c for c in fatte):
                continue
            fatte.append(cat)
            PASSI = []
            cat.percorre(b, BH, con_guasto=con_guasto)
            verde, motivi, den = giudica(list(PASSI), cat.anelli)
            esiti.append((cat, verde, motivi, den))
    finally:
        ruoli._ambiente_ripristinato(salvato)
        shutil.rmtree(d, ignore_errors=True)

    print()
    print("VERDETTO censimento (il cancello: nessuna voce fuori, e il debito non e' cresciuto):")
    print("   %s — voci guardate %d, rilievi %d" % ("✅ VERDE" if verde_per else "⛔ ROSSO", den_per, len(motivi_per)))
    for m in motivi_per:
        print("   perche': %s" % m)
    for cat, verde, motivi, den in esiti:
        print("VERDETTO catena «%s»: %s — anelli %d, rossi %d, denominatore %d"
              % (cat.voce, "✅ VERDE" if verde else "⛔ ROSSO", len(cat.anelli), len(motivi), den))
        for m in motivi:
            print("   perche': %s" % m)

    catene_verdi = all(v for _c, v, _m, _d in esiti) and bool(esiti)
    #  ⛔ LA CASELLA E' VERDE SOLO A DEBITO ZERO. Il censimento verde dice «non ci e' sfuggito
    #     niente», non «e' fatto»: finche' una rotta del pannello non ha la sua catena percorsa,
    #     quella casella resta ROSSA col suo motivo. Un verde qui sarebbe la frase piu' falsa di
    #     tutto il lavoro -- «non ci deve scappare niente» con venti voci mai seguite.
    tutto = verde_per and catene_verdi and not scoperte
    den = den_per + sum(dd for _c, _v, _m, dd in esiti)
    motivi = list(motivi_per) + ["catena «%s»: %s" % (c.voce, m) for c, _v, ms, _d in esiti for m in ms]
    if scoperte:
        motivi.append("%d rotte del pannello su %d non hanno ancora una catena percorsa (debito "
                      "dichiarato, tetto %d): %s" % (len(scoperte), len(per["rotte"]),
                                                     ROTTE_SENZA_CATENA_TETTO, ", ".join(scoperte)))
    print("VERDETTO della casella: %s — censimento %s · catene percorse %d su %d rotte"
          % ("✅ VERDE" if tutto else "⛔ ROSSO", "verde" if verde_per else "ROSSO",
             len(per["rotte"]) - len(scoperte), len(per["rotte"])))
    ULTIMO.clear()
    ULTIMO.update({"censimento": verde_per, "motivi_censimento": motivi_per, "scoperte": scoperte,
                   "perimetro": per, "denominatore": den,
                   "catene": [{"voce": c.voce, "verde": v, "motivi": ms, "denominatore": dd,
                               "rossi": [m.split("]")[0].lstrip("[") for m in ms]}
                              for c, v, ms, dd in esiti]})

    if scrivi:
        print("\nSCRITTURA NELLA SCHEDA")
        riga = scheda.registra(condizione(), esito=tutto, denominatore=den, comando=COMANDO,
                               ordine=BLOCCO, motivo=("; ".join(motivi)[:600] if motivi else None))
        print("  scritta: blocco %s · esito %s · denominatore %s · impronta %s · motivo: %s"
              % (riga.get("blocco"), riga.get("esito"), riga.get("denominatore"),
                 riga.get("impronta"), (riga.get("motivo") or "-")[:200]))
    else:
        print("\n(non ho scritto niente: aggiungi --scrivi per registrare nella scheda)")

    _stampa_non_guarda()
    print("=" * 86)
    return 0 if tutto else 1


if __name__ == "__main__":
    sys.exit(main())
