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
   2. provato nelle DUE direzioni: `--con-guasto` inietta i guasti che colpiscono meta'
      diverse -- il concierge smette di guardare lo stato dell'annuncio (l'anello [prenota]
      della catena 1 deve gridare), il pulsante «Lo pago io a mano» smette di guardare se la
      garanzia e' chiusa (l'anello [garanzia] della catena 2 deve gridare), la riga del bonifico
      dell'host non scende alla sua quota dopo la decisione dell'arbitro (l'anello [soldi] della
      catena 3 deve gridare) e la pagina nomina una rotta in piu' (il perimetro deve gridare);
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
    "le rotte del pannello che non hanno ancora una catena (l'elenco `CATENE` dice quali ce l'hanno; "
    "il numero lo stampa il verdetto della casella): risultano ROSSE per costruzione, non per un "
    "guasto -- e' lo stato vero. ⚠️ Il «Rimborsa» della tabella prenotazioni (catena 5) aspetta un pezzo "
    "del PRODOTTO: `_admin_rimborso` scrive l'esito ma non l'ip di chi ha premuto, quindi il suo anello "
    "[traccia] e' rosso sul codice sano finche' `fase83_server` non lo ripara (voce 35 di RIPRENDI)",
    "nella catena 3 la controversia aperta dalla BANCA (motivo 'chargeback:', decide la banca), la "
    "divisione al 100% all'ospite e quella in euro esatti: qui si percorre la divisione in "
    "percentuale aperta dall'ospite; gli altri rami li provano le guardie di `test_fase83_server`",
    "nella catena 2 il bonifico che Stripe ACCETTA, o il cui esito e' sconosciuto: lo Stripe del "
    "banco li rifiuta tutti. Quei due rami li provano `test_fase83_server.TestIlPagamentoAMano` e "
    "vicine (gia' su Stripe -> 409 'gia_su_stripe', Stripe muto -> 409 'stripe_non_risponde')",
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


ANELLI_CATENA_2 = ("porta", "vede", "garanzia", "prende", "soldi", "doppio", "traccia")


class _StripeCheRifiuta(object):
    """Lo Stripe del banco per i bonifici: OGNI bonifico viene rifiutato per saldo insufficiente
    (il caso vero di produzione: gli 11 centesimi del conto di prova), e la lista dei bonifici di
    un conto e' vuota. Conta i tentativi: dopo «Lo pago io a mano» non ne deve arrivare nessuno.
    ⛔ Sta sull'ISTANZA del banco (`b.sis.connect`), mai sulla classe: e senza di lui il Connect
    del banco parlerebbe con la rete vera."""

    def __init__(self):
        self.tentati = 0          # POST di bonifici ricevuti (tutti rifiutati)
        self.per_rif = {}         # gli stessi, per riferimento (`metadata[riferimento]`)
        self.inattesi = []        # chiamate che questo finto non sa servire

    def post(self, url, body, headers):
        import urllib.error
        from urllib.parse import parse_qsl
        if body is None:
            return self.get(url, headers)
        if url != "https://api.stripe.com/v1/transfers":
            self.inattesi.append(("POST", url))
            return {}
        self.tentati += 1
        rif = dict(parse_qsl(body.decode("utf-8"))).get("metadata[riferimento]", "")
        self.per_rif[rif] = self.per_rif.get(rif, 0) + 1
        corpo = json.dumps({"error": {"type": "invalid_request_error", "code": "balance_insufficient",
                                      "message": "Insufficient funds"}}).encode("utf-8")
        raise urllib.error.HTTPError(url, 400, "Bad Request", {}, io.BytesIO(corpo))

    def get(self, url, headers):
        from urllib.parse import urlsplit
        if urlsplit(url).path != "/v1/transfers":
            self.inattesi.append(("GET", url))
            return {}
        return {"object": "list", "data": [], "has_more": False}


def percorre_catena_2(b, BH, con_guasto=False):
    """La voce «Lo pago io a mano» della scheda audit: Stripe ha rifiutato il bonifico all'host,
    una persona lo prende in carico e lo paga dalla banca, e nessun giro automatico lo ripaga."""
    import dataclasses
    from fase101_stripe_connect import ProviderConnect
    from fase83_server import _rif_per_registro
    print("\n--- CATENA 2, «Lo pago io a mano»: Stripe rifiuta -> presa in carico -> nessun doppio ---")
    rotta = "/api/admin/payout/pagato_a_mano"
    stripe = _StripeCheRifiuta()
    connect_prima = b.sis.connect
    b.sis.connect = ProviderConnect("sk_test_catena", fetch=stripe.post, fetch_get=stripe.get)
    try:
        slug = b.alloggio("casa-catena-due", 3, "2027-08-01", "2027-08-31")
        b.sis.registro_host.imposta_stripe_account(b.host_id, "acct_CATENA2")
        rif, _vt = b.pagata(slug, "2027-08-05", "2027-08-07")
        rif_aperta, _vt2 = b.pagata(slug, "2027-08-10", "2027-08-12")
        if not (rif and rif_aperta):
            raise RuntimeError("il banco non ha prodotto le due prenotazioni pagate")
        netto = int((b.sis.payout.info(rif) or {}).get("minori") or 0)
        if not b.sis.garanzia.conferma_ospite(rif).get("ok"):
            raise RuntimeError("il banco non ha chiuso la garanzia della prima prenotazione")
        b.router._ritenta_bonifici_fermi()               # il giro orario: Stripe rifiuta

        def tipi(r):
            return [m.get("tipo") for m in b.sis.finanza.movimenti(r)]

        #  LA PREMESSA, che NON e' un anello: se manca l'esame non e' verde, e' FERMO (S7).
        if not (netto > 0 and stripe.tentati >= 1 and b.sis.payout.stato_di(rif) == "maturato"
                and "payout_manuale" in tipi(rif)):
            raise RuntimeError("premessa mancata: netto=%s tentativi=%s stato=%s giornale=%s"
                               % (netto, stripe.tentati, b.sis.payout.stato_di(rif), tipi(rif)))

        def audit(r):
            #  ⛔ La scheda audit rilegge Stripe con la chiave della configurazione (2 secondi, rete
            #     VERA). Per la lettura del banco la chiave si toglie sull'ISTANZA del sistema: la
            #     riga «payout» della scheda non dipende da Stripe, e un esame non esce in rete.
            cfg = b.sis.config
            b.sis.config = dataclasses.replace(cfg, stripe_secret_key="")
            try:
                s, c = _chiedi(b, "GET", "/api/admin/audit?id=" + r, None, ADMIN)
            finally:
                b.sis.config = cfg
            return (c or {}) if s == 200 else {}

        def host_eur():
            e = b.payout_host().get("EUR") or {}
            return int(e.get("maturato") or 0), int(e.get("in_transito") or 0)

        # -- la porta: senza chiave, senza secondo fattore, col ruolo 'supporto' ---------------
        corpo = {"riferimento": rif}
        s_senza, _ = b.g("POST", rotta, corpo, {})
        s_solo, c_solo = b.g("POST", rotta, corpo, ADMIN)
        b.g("POST", "/api/bunker/admin_accounts",
            {"azione": "crea", "email": "supporto2@esame.it", "password": "password123",
             "ruolo": "supporto"}, BH)
        s_op, c_op = b.g("POST", "/api/admin/login", {"email": "supporto2@esame.it", "password": "password123"})
        op = ({"X-Admin-Op": (c_op or {}).get("op_token", ""),
               "X-Bunker-Session": BH.get("X-Bunker-Session", ""),
               "X-Forwarded-For": IP["X-Forwarded-For"]} if s_op == 200 else None)
        s_supp, c_supp = b.g("POST", rotta, corpo, op) if op else (None, {})
        passo("porta", "senza chiave 401 · con la sola chiave 403 'bunker_richiesto' · col ruolo "
                       "'supporto' 403 'permesso_negato_ruolo' -- e il bonifico resta 'maturato', senza "
                       "nessuna riga 'payout_host' nel giornale",
              s_senza == 401 and s_solo == 403 and (c_solo or {}).get("errore") == "bunker_richiesto"
              and s_supp == 403 and (c_supp or {}).get("errore") == "permesso_negato_ruolo"
              and b.sis.payout.stato_di(rif) == "maturato" and "payout_host" not in tipi(rif),
              "senza=%s solo_admin=%s/%s supporto=%s/%s stato=%s"
              % (s_senza, s_solo, (c_solo or {}).get("errore"), s_supp, (c_supp or {}).get("errore"),
                 b.sis.payout.stato_di(rif)))

        # -- vede: la scheda audit mostra il bonifico fermo, ed e' li' che la pagina disegna il bottone
        a_prima = audit(rif)
        pay = a_prima.get("payout") or {}
        passo("vede", "la scheda audit della prenotazione dice payout 'maturato' con l'importo del "
                      "registro dei bonifici (la pagina disegna «Lo pago io a mano» solo li'), e il "
                      "rifiuto di Stripe e' nei movimenti ('payout_manuale')",
              a_prima.get("riferimento") == rif and pay.get("stato") == "maturato"
              and int(pay.get("minori") or -1) == netto
              and "payout_manuale" in [m.get("tipo") for m in (a_prima.get("movimenti") or [])],
              "riferimento=%s payout=%s netto=%s" % (a_prima.get("riferimento") == rif, pay, netto))

        # -- garanzia: un soggiorno non confermato non si paga (i soldi non sono ancora dell'host)
        if con_guasto:
            # IL GUASTO, sull'ISTANZA del router e mai sul codice: il pulsante smette di guardare
            # se la garanzia e' chiusa. E' l'anello che vale i soldi: pagare l'host prima che il
            # soggiorno sia confermato, cioe' con soldi che possono ancora tornare all'ospite.
            b.router._garanzia_chiusa = lambda _r: True
        s_ap, c_ap = b.g("POST", rotta, {"riferimento": rif_aperta}, BH)
        passo("garanzia", "su una prenotazione col soggiorno NON ancora confermato risponde 409 "
                          "'garanzia_aperta', e quel bonifico resta 'maturato' senza 'payout_host'",
              s_ap == 409 and (c_ap or {}).get("errore") == "garanzia_aperta"
              and b.sis.payout.stato_di(rif_aperta) == "maturato" and "payout_host" not in tipi(rif_aperta),
              "http=%s errore=%s stato=%s" % (s_ap, (c_ap or {}).get("errore"),
                                              b.sis.payout.stato_di(rif_aperta)))

        # -- prende: il bottone col secondo fattore, e la traccia che lascia ----------------------
        host_prima = host_eur()
        tentati_prima = stripe.per_rif.get(rif, 0)
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
            s_am, c_am = b.g("POST", rotta, corpo, BH)
        finally:
            log_server.removeHandler(presa)
            log_server.setLevel(livello_prima)
        c_am = c_am or {}
        passo("prende", "col secondo fattore risponde 200 'preso_in_carico' con l'importo del REGISTRO "
                        "(il browser manda solo il riferimento), e il bonifico passa a 'in_transito'",
              s_am == 200 and c_am.get("stato") == "preso_in_carico" and c_am.get("importo_cents") == netto
              and c_am.get("valuta") == "EUR" and b.sis.payout.stato_di(rif) == "in_transito",
              "http=%s risposta=%s/%s/%s netto=%s stato=%s"
              % (s_am, c_am.get("stato"), c_am.get("importo_cents"), c_am.get("valuta"), netto,
                 b.sis.payout.stato_di(rif)))

        # -- soldi: una riga nel giornale, al centesimo; l'host lo vede spostarsi, il totale no ----
        righe_ph = [m for m in b.sis.finanza.movimenti(rif) if m.get("tipo") == "payout_host"]
        host_dopo = host_eur()
        passo("soldi", "il giornale scrive UNA riga 'payout_host' di esattamente il netto, la catena "
                       "delle impronte regge, e nel pannello dell'host il netto passa da 'maturato' a "
                       "'in_transito' senza che il totale cambi di un centesimo",
              len(righe_ph) == 1 and int(righe_ph[0].get("importo_cents") or 0) == netto
              and b.sis.finanza.verifica_catena().get("ok") is True
              and host_dopo == (host_prima[0] - netto, host_prima[1] + netto),
              "righe payout_host=%d importo=%s netto=%s host %s->%s"
              % (len(righe_ph), [m.get("importo_cents") for m in righe_ph], netto, host_prima, host_dopo))

        # -- doppio: ne' il giro orario, ne' lo sblocco della verifica, ne' un secondo clic ---------
        b.router._ritenta_bonifici_fermi()
        s_ver, _ = b.g("POST", "/api/admin/verifica_stato", {"host_id": b.host_id, "stato": "verificato"}, BH)
        s_due, c_due = b.g("POST", rotta, corpo, BH)
        a_dopo = audit(rif)
        passo("doppio", "dopo la presa in carico il giro orario e lo sblocco della verifica NON provano "
                        "piu' a pagarlo con Stripe (zero tentativi nuovi su QUESTO riferimento), un "
                        "secondo clic risponde 409 'non_da_pagare', il giornale ha ancora UNA riga e la "
                        "scheda dice 'in_transito' (il bottone non si disegna piu')",
              stripe.per_rif.get(rif, 0) == tentati_prima and s_ver == 200 and s_due == 409
              and (c_due or {}).get("errore") == "non_da_pagare"
              and tipi(rif).count("payout_host") == 1
              and ((a_dopo.get("payout") or {}).get("stato")) == "in_transito"
              and stripe.inattesi == [],
              "tentativi %d->%d verifica=%s secondo_clic=%s/%s payout_host=%d scheda=%s inattesi=%s"
              % (tentati_prima, stripe.per_rif.get(rif, 0), s_ver, s_due, (c_due or {}).get("errore"),
                 tipi(rif).count("payout_host"), (a_dopo.get("payout") or {}).get("stato"), stripe.inattesi))

        righe_gesto = [r for r in registro if "ADMIN_ACTION" in r and "pagato_a_mano" in r
                       and _rif_per_registro(rif) in r]
        passo("traccia", "il gesto lascia UNA riga che unisce CHI (ip), COSA (pagato_a_mano) e SU COSA "
                         "(il riferimento), come gli altri gesti dell'admin",
              len(righe_gesto) == 1 and IP["X-Forwarded-For"] in righe_gesto[0],
              "righe scritte durante il gesto=%d, con azione e riferimento=%d"
              % (len(registro), len(righe_gesto)))
    finally:
        b.sis.connect = connect_prima
        b.router.__dict__.pop("_garanzia_chiusa", None)
        #  il conto Stripe dell'host torna com'era: con un conto e il Connect vero del banco, una
        #  catena percorsa dopo questa potrebbe chiedere un bonifico alla rete vera
        b.sis.registro_host.imposta_stripe_account(b.host_id, "")


CATENA_2 = Catena(
    voce="Scheda audit: Lo pago io a mano",
    rotte=("/api/admin/payout/pagato_a_mano",),
    anelli=ANELLI_CATENA_2,
    bottone="premo «Lo pago io a mano» nella scheda audit di una prenotazione col bonifico 'maturato' "
            "(Stripe l'ha rifiutato): la rotta prende in carico il bonifico all'host, lo toglie da ogni giro "
            "automatico e dice di farlo dalla banca; la scheda rilegge 'in_transito' e il bottone sparisce",
    soldi="muove il bonifico all'host, al centesimo: l'importo e' quello del registro dei bonifici dopo le "
          "stesse guardie del bonifico automatico, mai quello del browser. Si paga UNA volta: se il giro "
          "orario o lo sblocco della verifica lo ripagassero con Stripe, l'host prenderebbe due volte gli "
          "stessi soldi; e un soggiorno non confermato non si paga, perche' quei soldi possono ancora "
          "tornare all'ospite",
    archivio="scrive `payout.stato` ('maturato' -> 'in_transito') nell'archivio dei bonifici e UNA riga "
             "`payout_host` nel giornale dei soldi, che non si cancella e non si riscrive (catena di impronte): "
             "e' la prova contabile del bonifico. Nessun dato personale nuovo (il soggetto e' l'id dell'host). "
             "La traccia del gesto (chi/cosa/su quale riferimento) va nel registro del server, anello [traccia]",
    percorre=percorre_catena_2,
)


ANELLI_CATENA_3 = ("vede", "ferma", "porta", "fuori", "decide", "soldi", "doppio", "traccia")


def percorre_catena_3(b, BH, con_guasto=False):
    """Le voci «Controversie» e «Risolvi»: l'ospite contesta, l'admin vede la controversia, decide
    una divisione, e i conti si spostano esattamente come dice la decisione."""
    from unittest import mock
    from fase101_stripe_connect import ProviderConnect
    from fase83_server import _rif_per_registro
    print("\n--- CATENA 3, «Controversie»: l'ospite contesta -> l'admin divide -> i conti seguono ---")
    rotta = "/api/admin/controversia/risolvi"
    pct = 30
    stripe = _StripeCheRifiuta()
    connect_prima = b.sis.connect
    b.sis.connect = ProviderConnect("sk_test_catena", fetch=stripe.post, fetch_get=stripe.get)
    try:
        slug = b.alloggio("casa-catena-tre", 3, "2027-09-01", "2027-09-30")
        rif, vt = b.pagata(slug, "2027-09-05", "2027-09-07")
        rif_ok, _vt2 = b.pagata(slug, "2027-09-10", "2027-09-12")
        if not (rif and rif_ok):
            raise RuntimeError("il banco non ha prodotto le due prenotazioni pagate")
        importo = int((b.sis.garanzia.stato(rif) or {}).get("importo_host_cents") or 0)
        rimborso_atteso = importo * pct // 100

        def in_elenco(r):
            return [c for c in b.controversie_admin() if c.get("prenotazione_id") == r]

        def tipi(r):
            return [m.get("tipo") for m in b.sis.finanza.movimenti(r)]

        def stato_g(r):
            return (b.sis.garanzia.stato(r) or {}).get("stato")

        prima = in_elenco(rif)
        #  «c'e' un problema» vale dall'arrivo allo sblocco: l'ospite lo preme un'ora prima dello
        #  sblocco, come in `esame_percorso_ruoli` (il tempo si sposta solo per questa chiamata)
        sblocco = int((b.sis.garanzia.stato(rif) or {}).get("sblocco_auto_ts") or 0)
        with mock.patch("time.time", return_value=float(sblocco - 3600)):
            s_cont, _c = b.g("POST", "/api/garanzia/contesta",
                             {"voucher_token": vt, "motivo": "la stanza non era quella"})
        #  LA PREMESSA, che NON e' un anello: se manca l'esame e' FERMO, non verde (S7).
        if not (importo > 0 and s_cont == 200 and stato_g(rif) == "contestato"):
            raise RuntimeError("premessa mancata: importo=%s contesta=%s garanzia=%s"
                               % (importo, s_cont, stato_g(rif)))

        dopo = in_elenco(rif)
        passo("vede", "la controversia COMPARE nell'elenco dell'admin (prima non c'era) con la somma in "
                      "garanzia della prenotazione",
              prima == [] and len(dopo) == 1 and int(dopo[0].get("importo_host_cents") or -1) == importo,
              "prima=%d dopo=%d importo=%s/%s" % (len(prima), len(dopo),
                                                  (dopo[0] if dopo else {}).get("importo_host_cents"), importo))

        b.router._ritenta_bonifici_fermi()
        passo("ferma", "mentre la controversia e' aperta il bonifico dell'host e' 'trattenuto', e il giro "
                       "orario non prova a pagarlo (zero tentativi su questo riferimento)",
              b.sis.payout.stato_di(rif) == "trattenuto" and stripe.per_rif.get(rif, 0) == 0,
              "stato=%s tentativi=%s" % (b.sis.payout.stato_di(rif), stripe.per_rif.get(rif, 0)))

        # -- la porta: senza chiave, senza secondo fattore, col ruolo 'supporto' ---------------
        corpo = {"riferimento": rif, "percentuale_ospite": pct}
        s_senza, _ = b.g("POST", rotta, corpo, {})
        s_solo, c_solo = b.g("POST", rotta, corpo, ADMIN)
        b.g("POST", "/api/bunker/admin_accounts",
            {"azione": "crea", "email": "supporto3@esame.it", "password": "password123",
             "ruolo": "supporto"}, BH)
        s_op, c_op = b.g("POST", "/api/admin/login", {"email": "supporto3@esame.it", "password": "password123"})
        op = ({"X-Admin-Op": (c_op or {}).get("op_token", ""),
               "X-Bunker-Session": BH.get("X-Bunker-Session", ""),
               "X-Forwarded-For": IP["X-Forwarded-For"]} if s_op == 200 else None)
        s_supp, c_supp = b.g("POST", rotta, corpo, op) if op else (None, {})
        passo("porta", "senza chiave 401 · con la sola chiave 403 'bunker_richiesto' · col ruolo "
                       "'supporto' 403 'permesso_negato_ruolo' -- e la controversia resta aperta, senza "
                       "nessuna riga 'rimborso' nel giornale",
              s_senza == 401 and s_solo == 403 and (c_solo or {}).get("errore") == "bunker_richiesto"
              and s_supp == 403 and (c_supp or {}).get("errore") == "permesso_negato_ruolo"
              and stato_g(rif) == "contestato" and "rimborso" not in tipi(rif),
              "senza=%s solo_admin=%s/%s supporto=%s/%s garanzia=%s"
              % (s_senza, s_solo, (c_solo or {}).get("errore"), s_supp, (c_supp or {}).get("errore"),
                 stato_g(rif)))

        # -- fuori: una prenotazione NON contestata non si arbitra -------------------------------
        s_fu, c_fu = b.g("POST", rotta, {"riferimento": rif_ok, "percentuale_ospite": pct}, BH)
        passo("fuori", "una prenotazione senza controversia risponde 409 'non_in_controversia': la sua "
                       "garanzia, il suo bonifico e il giornale restano come erano",
              s_fu == 409 and (c_fu or {}).get("errore") == "non_in_controversia"
              and stato_g(rif_ok) == "in_garanzia" and b.sis.payout.stato_di(rif_ok) == "maturato"
              and "rimborso" not in tipi(rif_ok),
              "http=%s errore=%s garanzia=%s bonifico=%s" % (s_fu, (c_fu or {}).get("errore"),
                                                            stato_g(rif_ok), b.sis.payout.stato_di(rif_ok)))

        # -- decide: col secondo fattore, la divisione e la traccia che lascia ---------------------
        if con_guasto:
            # IL GUASTO, sull'ISTANZA dell'archivio dei bonifici e mai sul codice: la riscrittura della
            # riga dell'host dice «fatto» e non scrive niente. E' l'anello che vale i soldi: la riga
            # resterebbe all'importo PIENO, e all'host arriverebbe anche la parte data all'ospite.
            b.sis.payout.riallinea_maturato = lambda *a, **k: True
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
            s_ris, c_ris = b.g("POST", rotta, corpo, BH)
        finally:
            log_server.removeHandler(presa)
            log_server.setLevel(livello_prima)
        c_ris = c_ris or {}
        g_dopo = b.sis.garanzia.stato(rif) or {}
        passo("decide", "col secondo fattore risponde 200 'risolta' con la divisione esatta (all'ospite la "
                        "percentuale decisa della somma in garanzia, all'host il resto), e la garanzia "
                        "dice la stessa cosa",
              s_ris == 200 and c_ris.get("stato") == "risolta"
              and c_ris.get("rimborso_cliente_cents") == rimborso_atteso
              and c_ris.get("va_all_host_cents") == importo - rimborso_atteso
              and g_dopo.get("stato") == "risolto"
              and int(g_dopo.get("ospite_rimborso_cents") or -1) == rimborso_atteso
              and int(g_dopo.get("host_riceve_cents") or -1) == importo - rimborso_atteso,
              "http=%s risposta=%s/%s/%s attesi=%s/%s garanzia=%s/%s/%s"
              % (s_ris, c_ris.get("stato"), c_ris.get("rimborso_cliente_cents"), c_ris.get("va_all_host_cents"),
                 rimborso_atteso, importo - rimborso_atteso, g_dopo.get("stato"),
                 g_dopo.get("ospite_rimborso_cents"), g_dopo.get("host_riceve_cents")))

        # -- soldi: il giornale, la riga dell'host e la lista dei rimborsi dovuti -----------------
        righe_r = [m for m in b.sis.finanza.movimenti(rif) if m.get("tipo") == "rimborso"]
        riga_host = b.sis.payout.info(rif) or {}
        dovuti = [r for r in b.rimborsi_admin() if ruoli._riferimento(r).startswith(rif)]
        passo("soldi", "il giornale scrive UNA riga 'rimborso' della cifra decisa, la riga del bonifico "
                       "dell'host scende alla sua quota e torna pagabile ('maturato'), la cifra dell'ospite "
                       "compare fra i rimborsi dovuti, e la catena delle impronte regge",
              len(righe_r) == 1 and int(righe_r[0].get("importo_cents") or -1) == rimborso_atteso
              and int(riga_host.get("minori") or -1) == importo - rimborso_atteso
              and riga_host.get("stato") == "maturato"
              and len(dovuti) == 1 and ruoli._importo(dovuti[0]) == rimborso_atteso
              and b.sis.finanza.verifica_catena().get("ok") is True,
              "rimborso=%s riga_host=%s/%s dovuti=%s attesi %s + %s"
              % ([m.get("importo_cents") for m in righe_r], riga_host.get("minori"), riga_host.get("stato"),
                 [ruoli._importo(r) for r in dovuti], rimborso_atteso, importo - rimborso_atteso))

        # -- doppio: decidere di nuovo non sposta niente ------------------------------------------
        s_due, c_due = b.g("POST", rotta, corpo, BH)
        passo("doppio", "una seconda decisione sulla stessa prenotazione risponde 409 "
                        "'non_in_controversia': nessuna riga 'rimborso' in piu', la riga dell'host "
                        "non cambia di un centesimo",
              s_due == 409 and (c_due or {}).get("errore") == "non_in_controversia"
              and tipi(rif).count("rimborso") == 1
              and int((b.sis.payout.info(rif) or {}).get("minori") or -1) == int(riga_host.get("minori") or -2),
              "http=%s errore=%s rimborsi=%d riga_host=%s"
              % (s_due, (c_due or {}).get("errore"), tipi(rif).count("rimborso"),
                 (b.sis.payout.info(rif) or {}).get("minori")))

        righe_gesto = [r for r in registro if "ADMIN_ACTION" in r and "Controversia risolta" in r
                       and _rif_per_registro(rif) in r]
        passo("traccia", "la decisione lascia UNA riga che unisce CHI (ip), SU COSA (il riferimento) e "
                         "QUANTO torna all'ospite",
              len(righe_gesto) == 1 and IP["X-Forwarded-For"] in righe_gesto[0]
              and ("RIMBORSO_CENTS: %d" % rimborso_atteso) in righe_gesto[0],
              "righe scritte durante il gesto=%d, con azione e riferimento=%d"
              % (len(registro), len(righe_gesto)))
    finally:
        b.sis.connect = connect_prima
        b.sis.payout.__dict__.pop("riallinea_maturato", None)


CATENA_3 = Catena(
    voce="Controversie: elenco e Risolvi",
    rotte=("/api/admin/controversie", "/api/admin/controversia/risolvi"),
    anelli=ANELLI_CATENA_3,
    bottone="apro «Controversie»: compare la prenotazione che l'ospite ha contestato, con la somma in "
            "garanzia; premo «Risolvi» con la percentuale (o gli euro) da dare all'ospite: la rotta registra "
            "la decisione, chiude la garanzia e mette la cifra dell'ospite fra i rimborsi da eseguire",
    soldi="divide la somma in garanzia al centesimo: all'ospite la parte decisa (riga 'rimborso' del "
          "giornale e riga fra i rimborsi dovuti), all'host il resto (la riga del suo bonifico scende alla "
          "quota e torna pagabile). Mentre la controversia e' aperta il bonifico dell'host e' fermo; se la "
          "riga non scendesse, all'host arriverebbe anche la parte data all'ospite",
    archivio="scrive lo stato della garanzia ('contestato' -> 'risolto', con le due quote) nell'archivio "
             "delle garanzie, riscrive la riga dell'host nell'archivio dei bonifici, e UNA riga 'rimborso' "
             "nel giornale dei soldi, che non si cancella (catena di impronte). Nessun dato personale nuovo; "
             "il motivo scritto dall'ospite resta nella garanzia. La traccia della decisione va nel registro "
             "del server, anello [traccia]",
    percorre=percorre_catena_3,
)


ANELLI_CATENA_4 = ("porta", "vede", "cieco", "cifra", "rimborsa", "doppio", "divergenza", "traccia")


def percorre_catena_4(b, BH, con_guasto=False):
    """Le voci «Rimborsi dovuti» e «Rimborsa»: l'ospite ha cancellato, la lista dice a chi vanno
    restituiti i soldi e quanti, e il pulsante li restituisce UNA volta, nella cifra del giornale.

    ⛔ IL GATEWAY E' QUELLO DEL BANCO (`ruoli.GatewayDiProva`, su `b.sis.stripe`): TIENE CONTO di
       cosa ha restituito, e `muto` vuol dire «NON LO SO». Un finto che annuisse sempre farebbe
       uscire la riga dalla lista prima del pulsante, e [rimborsa] sarebbe verde senza un centesimo
       uscito (S7). Le prenotazioni di questa catena sono SUE: ogni lettura si filtra per riferimento,
       perche' le catene prima di lei lasciano righe loro sullo stesso banco."""
    from fase83_server import _rif_per_registro
    print("\n--- CATENA 4, «Rimborsi dovuti» e «Rimborsa»: cancella -> lista -> pulsante -> nessun doppio ---")
    lista_rotta, rotta = "/api/admin/rimborsi_dovuti", "/api/admin/rimborsa_dovuto"
    gw = b.gateway
    pi_viva, viva_prima = "", None
    try:
        slug = b.alloggio("casa-catena-quattro", 3, "2027-09-01", "2027-09-30")
        rif, vt = b.pagata(slug, "2027-09-05", "2027-09-07")
        rif_viva, _vt2 = b.pagata(slug, "2027-09-12", "2027-09-14")
        if not (rif and rif_viva):
            raise RuntimeError("il banco non ha prodotto le due prenotazioni pagate")

        def pi_di(r):
            #  il pagamento da restituire si legge dove lo legge il prodotto (i pagati recenti), non
            #  dalla ricetta del banco: se un giorno cambiassero, l'esame lo direbbe
            for rec in b.sis.pagamenti_pendenti.pagati_recenti(limit=500):
                if rec.get("riferimento") == r:
                    try:
                        return str(json.loads(rec.get("corpo_json") or "{}").get("stripe_pi") or "")
                    except ValueError:
                        return ""
            return ""

        def lista(h=None):
            s, c = _chiedi(b, "GET", lista_rotta, None, ADMIN if h is None else h)
            return s, (c or {})

        def mia(c, r):
            return [x for x in (c.get("rimborsi") or []) if x.get("riferimento") == r]

        def giornale(r, tipo):
            return [int(m.get("importo_cents") or 0) for m in b.sis.finanza.movimenti(r)
                    if m.get("tipo") == tipo]

        def richieste(p):
            return [c for c in gw.chiamate if c[0] == "rimborsa" and c[1] == p]

        def registro_di(fare):
            righe = []

            class _Presa(logging.Handler):
                def emit(self, record):
                    try:
                        righe.append(record.getMessage())
                    except Exception:
                        righe.append(str(record.msg))
            presa = _Presa()
            log_server = logging.getLogger("core_auto.server")
            livello_prima = log_server.level
            log_server.addHandler(presa)
            log_server.setLevel(logging.DEBUG)
            try:
                esito = fare()
            finally:
                log_server.removeHandler(presa)
                log_server.setLevel(livello_prima)
            return esito, righe

        #  ⛔ Il pagamento si legge PRIMA della cancellazione: dopo, la prenotazione non e' piu' fra i
        #     pagati recenti (al primo giro la premessa si e' fermata proprio qui, pi=False).
        pi, pi_viva = pi_di(rif), pi_di(rif_viva)
        viva_prima = gw.rimborsati.get(pi_viva)
        s_prima, c_prima = lista()
        s_canc, _c_canc = b.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
        pagato_g, dovuto_g = sum(giornale(rif, "incasso")), sum(giornale(rif, "rimborso"))

        #  LA PREMESSA, che NON e' un anello: se manca l'esame non e' verde, e' FERMO (S7).
        if not (s_prima == 200 and not mia(c_prima, rif) and s_canc == 200 and pagato_g > 0
                and 0 < dovuto_g <= pagato_g and pi and pi_viva and not richieste(pi)
                and not gw.rimborsati.get(pi_viva)):
            raise RuntimeError("premessa mancata: lista=%s cancella=%s pagato=%s dovuto=%s pi=%s/%s "
                               "richieste=%d" % (s_prima, s_canc, pagato_g, dovuto_g, bool(pi),
                                                 bool(pi_viva), len(richieste(pi))))

        # -- la porta: senza chiave, senza secondo fattore, col ruolo 'supporto' ---------------
        corpo = {"riferimento": rif}
        s_l_senza, _ = _chiedi(b, "GET", lista_rotta, None, {})
        s_senza, _ = b.g("POST", rotta, corpo, {})
        s_solo, c_solo = b.g("POST", rotta, corpo, ADMIN)
        b.g("POST", "/api/bunker/admin_accounts",
            {"azione": "crea", "email": "supporto4@esame.it", "password": "password123",
             "ruolo": "supporto"}, BH)
        s_op, c_op = b.g("POST", "/api/admin/login", {"email": "supporto4@esame.it", "password": "password123"})
        op = ({"X-Admin-Op": (c_op or {}).get("op_token", ""),
               "X-Bunker-Session": BH.get("X-Bunker-Session", ""),
               "X-Forwarded-For": IP["X-Forwarded-For"]} if s_op == 200 else None)
        s_supp, c_supp = b.g("POST", rotta, corpo, op) if op else (None, {})
        passo("porta", "senza chiave la lista e il pulsante rispondono 401 · il pulsante con la sola chiave "
                       "403 'bunker_richiesto' · col ruolo 'supporto' 403 'permesso_negato_ruolo' -- e a "
                       "Stripe non e' arrivata nessuna richiesta di rimborso",
              s_l_senza == 401 and s_senza == 401 and s_solo == 403
              and (c_solo or {}).get("errore") == "bunker_richiesto"
              and s_supp == 403 and (c_supp or {}).get("errore") == "permesso_negato_ruolo"
              and not richieste(pi),
              "lista_senza=%s senza=%s solo_admin=%s/%s supporto=%s/%s richieste=%d"
              % (s_l_senza, s_senza, s_solo, (c_solo or {}).get("errore"), s_supp,
                 (c_supp or {}).get("errore"), len(richieste(pi))))

        # -- vede: UNA riga, con le cifre del giornale e il pulsante pronto ---------------------
        s_v, c_v = lista()
        righe = mia(c_v, rif)
        r0 = righe[0] if len(righe) == 1 else {}
        passo("vede", "dopo la cancellazione dell'ospite la lista ha UNA riga per quella prenotazione, col "
                      "dovuto e il pagato del GIORNALE, il pagamento da restituire e il pulsante pronto",
              s_v == 200 and c_v.get("controllabile") is True and len(righe) == 1
              and int(r0.get("dovuto_cents") or -1) == dovuto_g
              and int(r0.get("pagato_cents") or -1) == pagato_g
              and r0.get("payment_intent") == pi and r0.get("bottone") is True
              and r0.get("gia_rimborsato") is False,
              "http=%s controllabile=%s righe=%d dovuto=%s/%s pagato=%s/%s pagamento_giusto=%s bottone=%s"
              % (s_v, c_v.get("controllabile"), len(righe), r0.get("dovuto_cents"), dovuto_g,
                 r0.get("pagato_cents"), pagato_g, r0.get("payment_intent") == pi, r0.get("bottone")))

        # -- cieco: Stripe che non sa rispondere vuol dire «non lo so», mai «niente da fare» -----
        gw.muto = True
        try:
            s_c, c_c = lista()
            s_cp, c_cp = b.g("POST", rotta, corpo, BH)
        finally:
            gw.muto = False
        sua_c = mia(c_c, rif)
        passo("cieco", "con Stripe che non sa rispondere la lista dice 'non controllabile' col motivo (non "
                       "«zero»), la riga c'e' ma SENZA pulsante, e il pulsante premuto lo stesso risponde 409 "
                       "'rifiutato' senza mandare niente a Stripe",
              s_c == 200 and c_c.get("controllabile") is False and bool(c_c.get("motivo_non_controllabile"))
              and len(sua_c) == 1 and sua_c[0].get("bottone") is False
              and all(x.get("bottone") is False for x in (c_c.get("rimborsi") or []))
              and s_cp == 409 and (c_cp or {}).get("stato") == "rifiutato" and not richieste(pi),
              "http=%s controllabile=%s motivo=%s sua_riga=%s pulsante=%s/%s richieste=%d"
              % (s_c, c_c.get("controllabile"), bool(c_c.get("motivo_non_controllabile")),
                 [x.get("bottone") for x in sua_c], s_cp, (c_cp or {}).get("stato"), len(richieste(pi))))

        # -- cifra e rimborsa: il pulsante, con cifre messe apposta nella richiesta ---------------
        if con_guasto:
            # IL GUASTO, sull'ISTANZA del router e mai sul codice: la scheda della riga smette di
            # tenere il dovuto entro il pagato e restituisce il doppio di quanto dice il giornale. E'
            # l'anello che vale i soldi: restituire all'ospite piu' di quanto ha pagato.
            _vera = b.router._rimborso_dovuto_scheda

            def _scheda_storta(r):
                riga, ok = _vera(r)
                if isinstance(riga, dict) and riga.get("dovuto_cents"):
                    riga = dict(riga, dovuto_cents=int(riga["dovuto_cents"]) * 2)
                return riga, ok
            b.router._rimborso_dovuto_scheda = _scheda_storta
        (s_r, c_r), registro = registro_di(lambda: b.g(
            "POST", rotta, {"riferimento": rif, "importo_cents": pagato_g * 50,
                            "dovuto_cents": pagato_g * 50}, BH))
        c_r = c_r or {}
        req = richieste(pi)
        passo("cifra", "il pulsante manda a Stripe ESATTAMENTE il dovuto del giornale, mai piu' del pagato, "
                       "con la chiave stabile 'rimborso:<riferimento>' -- e le cifre messe nella richiesta dal "
                       "browser non contano",
              len(req) == 1 and req[0][2] == dovuto_g and req[0][2] <= pagato_g
              and req[0][3] == "rimborso:" + rif,
              "richieste=%s dovuto=%s pagato=%s"
              % ([(x[2], x[3] == "rimborso:" + rif) for x in req], dovuto_g, pagato_g))
        s_d, c_d = lista()
        passo("rimborsa", "risponde 200 'rimborsato' con l'importo del giornale, Stripe ha restituito quella "
                          "cifra, e la riga ESCE dalla lista perche' Stripe lo conferma (non perche' l'abbiamo "
                          "tolta noi)",
              s_r == 200 and c_r.get("stato") == "rimborsato"
              and int(c_r.get("importo_cents") or -1) == dovuto_g
              and int(gw.rimborsati.get(pi, 0)) == dovuto_g and s_d == 200 and not mia(c_d, rif),
              "http=%s stato=%s importo=%s dovuto=%s restituito_su_stripe=%s ancora_in_lista=%s"
              % (s_r, c_r.get("stato"), c_r.get("importo_cents"), dovuto_g, gw.rimborsati.get(pi, 0),
                 bool(mia(c_d, rif))))

        # -- doppio: un secondo clic non fa uscire niente -----------------------------------------
        n_giornale = len(giornale(rif, "rimborso"))
        s_2, c_2 = b.g("POST", rotta, corpo, BH)
        passo("doppio", "un secondo clic risponde 200 'gia_rimborsato' e NON manda una seconda richiesta a "
                        "Stripe; il giornale ha ancora UNA riga 'rimborso'",
              s_2 == 200 and (c_2 or {}).get("stato") == "gia_rimborsato" and len(richieste(pi)) == 1
              and n_giornale == 1 and len(giornale(rif, "rimborso")) == 1,
              "http=%s stato=%s richieste=%d righe_rimborso=%d->%d"
              % (s_2, (c_2 or {}).get("stato"), len(richieste(pi)), n_giornale,
                 len(giornale(rif, "rimborso"))))

        # -- divergenza: UN centesimo restituito da Stripe fuori dalle nostre decisioni -----------
        # Il guasto sta NEI DATI del banco (lo stato del gateway finto), mai nel codice: Stripe dice
        # di aver restituito un centesimo su una prenotazione che per noi e' pagata e viva.
        gw.rimborsati[pi_viva] = (viva_prima or 0) + 1
        (s_dv, c_dv), registro_dv = registro_di(lambda: lista())
        allarmi = [a for a in (c_dv.get("allarmi") or []) if a.get("riferimento") == rif_viva]
        passo("divergenza", "se Stripe ha restituito anche UN centesimo su una prenotazione che per noi e' "
                            "pagata e viva, la lista lo mette fra gli allarmi (quanto su Stripe, quanto deciso "
                            "da noi), il registro grida 'DIVERGENZA CONTI' col riferimento, e quella "
                            "prenotazione NON diventa una riga col pulsante",
              s_dv == 200 and len(allarmi) == 1
              and int(allarmi[0].get("rimborsato_su_stripe_cents") or 0) == 1
              #  ⛔ confronto DIRETTO con 0: `x or -1` trasforma uno zero vero in -1 (primo giro: ROSSO
              #     con tutte le letture giuste -- lo strumento mentiva, non il prodotto, S3)
              and allarmi[0].get("deciso_da_noi_cents") == 0
              and any("DIVERGENZA CONTI" in x and rif_viva in x for x in registro_dv)
              and not mia(c_dv, rif_viva),
              "http=%s allarmi_suoi=%s grida=%s riga_col_pulsante=%s"
              % (s_dv, allarmi, any("DIVERGENZA CONTI" in x and rif_viva in x for x in registro_dv),
                 bool(mia(c_dv, rif_viva))))

        # -- traccia: chi, cosa, su cosa -------------------------------------------------------------
        rif_reg = _rif_per_registro(rif)
        righe_gesto = [x for x in registro if "ADMIN_ACTION" in x and rif_reg in x]
        passo("traccia", "il gesto lascia UNA riga che unisce CHI (ip), COSA (il rimborso) e SU COSA (il "
                         "riferimento), come gli altri gesti dell'admin che muovono denaro",
              len(righe_gesto) == 1 and IP["X-Forwarded-For"] in righe_gesto[0],
              "righe scritte durante il gesto=%d, ADMIN_ACTION col riferimento=%d, con l'ip=%s; righe col "
              "riferimento: %s" % (len(registro), len(righe_gesto),
                                   bool(righe_gesto) and IP["X-Forwarded-For"] in righe_gesto[0],
                                   [x[:80] for x in registro if rif_reg in x]))
    finally:
        gw.muto = False
        b.router.__dict__.pop("_rimborso_dovuto_scheda", None)
        #  lo stato del gateway torna com'era per la prenotazione viva: una catena percorsa dopo
        #  questa non deve trovarsi un rimborso che nessuno ha deciso
        if pi_viva:
            if viva_prima is None:
                gw.rimborsati.pop(pi_viva, None)
            else:
                gw.rimborsati[pi_viva] = viva_prima


CATENA_4 = Catena(
    voce="Rimborsi dovuti: elenco e Rimborsa",
    rotte=("/api/admin/rimborsi_dovuti", "/api/admin/rimborsa_dovuto"),
    anelli=ANELLI_CATENA_4,
    bottone="apro «Rimborsi dovuti»: compare la prenotazione che l'ospite ha cancellato, con quanto ha pagato "
            "e quanto gli spetta; premo «Rimborsa»: la rotta ricalcola la riga dal giornale, chiede a Stripe "
            "di restituire il dovuto, e la riga esce dalla lista solo quando Stripe conferma",
    soldi="restituisce all'ospite il dovuto scritto nel giornale alla cancellazione (riga 'rimborso'), mai "
          "piu' del pagato (riga 'incasso') e mai una cifra arrivata dal browser; UNA sola richiesta a Stripe "
          "con la chiave stabile 'rimborso:<riferimento>', cosi' un secondo clic non restituisce due volte. Se "
          "Stripe non risponde non parte niente; se Stripe ha restituito soldi che noi non abbiamo deciso, "
          "la lista grida",
    archivio="non scrive righe nuove nel giornale dei soldi (la riga 'rimborso' nasce alla cancellazione, e il "
             "giornale non si cancella: catena di impronte); il rimborso vive su Stripe, che fa da testimone, e "
             "la lista lo rilegge da li'. Nessun dato personale nuovo. La traccia del gesto va nel registro del "
             "server, anello [traccia]",
    percorre=percorre_catena_4,
)

ANELLI_CATENA_5 = ("porta", "vede", "rimborsa", "soldi", "doppio", "controversia", "traccia")


def percorre_catena_5(b, BH, con_guasto=False):
    """Il pulsante «Rimborsa» della tabella delle prenotazioni (`.danger`): l'admin annulla una
    prenotazione pagata, le date tornano libere, i soldi dell'host si fermano e quelli dell'ospite
    tornano indietro UNA volta, nella cifra pagata.

    Scritta il 2026-11-07 mentre il PC era occupato dalla mutazione del blocco 2: NON ancora
    percorsa sul banco quando e' stata scritta (lo dice RIPRENDI_QUI). Le letture si filtrano per
    riferimento, perche' le catene prima lasciano righe loro sullo stesso banco."""
    from fase83_server import _rif_per_registro
    print("\n--- CATENA 5, «Rimborsa» (tabella prenotazioni): annulla -> date -> soldi -> nessun doppio ---")
    rotta = "/api/admin/rimborso"
    gw = b.gateway
    try:
        #  UNA camera: con tre, una prenotazione lascia le date prenotabili e gli anelli che
        #  guardano le date non vedono niente (primo giro del 7/11: «occupate_prima=False»).
        slug = b.alloggio("casa-catena-cinque", 1, "2027-10-01", "2027-10-30")
        rif, _vt = b.pagata(slug, "2027-10-05", "2027-10-07")
        rif2, _vt2 = b.pagata(slug, "2027-10-12", "2027-10-14")
        if not (rif and rif2):
            raise RuntimeError("il banco non ha prodotto le due prenotazioni pagate")

        def riga_di(r):
            #  la riga si prende dalla lista che legge il pannello, come la prende il pulsante
            s, c = _chiedi(b, "GET", "/api/admin/prenotazioni", None, ADMIN)
            for p in ((c or {}).get("prenotazioni") or []):
                if str(p.get("idem_key") or "").startswith(r) or p.get("riferimento") == r:
                    return s, p
            return s, None

        def corpo_di(p):
            return {"alloggio_id": p.get("alloggio_id"), "check_in": p.get("check_in"),
                    "check_out": p.get("check_out"), "idem_key": p.get("idem_key")}

        def pi_di(r):
            for rec in b.sis.pagamenti_pendenti.pagati_recenti(limit=500):
                if rec.get("riferimento") == r:
                    try:
                        return str(json.loads(rec.get("corpo_json") or "{}").get("stripe_pi") or "")
                    except ValueError:
                        return ""
            return ""

        def giornale(r, tipo):
            return [int(m.get("importo_cents") or 0) for m in b.sis.finanza.movimenti(r)
                    if m.get("tipo") == tipo]

        def richieste(p):
            return [c for c in gw.chiamate if c[0] == "rimborsa" and c[1] == p]

        def libere(p):
            s, q = b.g("POST", "/api/concierge/quote", {"alloggio_id": p.get("alloggio_id"),
                                                        "check_in": p.get("check_in"),
                                                        "check_out": p.get("check_out"), "party": 2})
            return s == 200 and bool((q or {}).get("quote_token"))

        def registro_di(fare):
            righe = []

            class _Presa(logging.Handler):
                def emit(self, record):
                    try:
                        righe.append(record.getMessage())
                    except Exception:
                        righe.append(str(record.msg))
            presa = _Presa()
            log_server = logging.getLogger("core_auto.server")
            livello_prima = log_server.level
            log_server.addHandler(presa)
            log_server.setLevel(logging.DEBUG)
            try:
                esito = fare()
            finally:
                log_server.removeHandler(presa)
                log_server.setLevel(livello_prima)
            return esito, righe

        s_v, p = riga_di(rif)
        s_v2, p2 = riga_di(rif2)
        pi, pi2 = pi_di(rif), pi_di(rif2)
        pagato = sum(giornale(rif, "incasso"))
        #  LA PREMESSA, che NON e' un anello: senza, l'esame e' FERMO, non verde (S7).
        if not (p and p2 and pi and pi2 and pagato > 0 and not richieste(pi) and not richieste(pi2)):
            raise RuntimeError("premessa della catena 5 mancante: righe=%s/%s pi=%s/%s pagato=%s"
                               % (bool(p), bool(p2), bool(pi), bool(pi2), pagato))
        corpo = corpo_di(p)

        # -- porta ------------------------------------------------------------------------------------
        s_senza, _ = b.g("POST", rotta, corpo, {})
        s_solo, _ = b.g("POST", rotta, corpo, ADMIN)
        passo("porta", "senza chiave il pulsante risponde 401, con la sola chiave admin 403 (serve il "
                       "bunker: muove soldi), e nessuna delle due manda niente a Stripe",
              s_senza == 401 and s_solo == 403 and not richieste(pi),
              "senza=%s solo_chiave=%s richieste=%d" % (s_senza, s_solo, len(richieste(pi))))

        # -- vede -------------------------------------------------------------------------------------
        passo("vede", "la prenotazione pagata compare nella tabella del pannello come RIMBORSABILE, con "
                      "alloggio, date e chiave che il pulsante manda",
              s_v == 200 and p.get("rimborsabile") is True and all(corpo.values()),
              "http=%s rimborsabile=%s corpo=%s" % (s_v, p.get("rimborsabile"), corpo))

        # -- rimborsa ---------------------------------------------------------------------------------
        occupate_prima = not libere(p)
        if con_guasto:
            # IL GUASTO, sull'ISTANZA del router e mai sul codice: il rimborso «dimentica» di fermare
            # il bonifico dell'host. E' l'anello che vale i soldi: l'ospite riavrebbe tutto e l'host
            # incasserebbe lo stesso una prenotazione rimborsata -- la piattaforma paga due volte.
            b.router._payout_trattieni = lambda r: True
        (s_r, c_r), registro = registro_di(lambda: b.g("POST", rotta, corpo, BH))
        b.router.__dict__.pop("_payout_trattieni", None)
        c_r = c_r or {}
        passo("rimborsa", "risponde 200 'rimborsato' senza passi falliti, e le date che erano occupate "
                          "tornano prenotabili",
              s_r == 200 and c_r.get("stato") == "rimborsato" and c_r.get("passi_falliti") == []
              and occupate_prima and libere(p),
              "http=%s stato=%s falliti=%s occupate_prima=%s libere_dopo=%s rimborso=%s"
              % (s_r, c_r.get("stato"), c_r.get("passi_falliti"), occupate_prima, libere(p),
                 c_r.get("rimborso_stripe")))

        # -- soldi ------------------------------------------------------------------------------------
        rq = richieste(pi)
        st_pay = b.sis.payout.stato_di(rif) if getattr(b.sis, "payout", None) is not None else None
        try:
            st_gz = (b.sis.garanzia.stato(rif) or {}).get("stato")
        except Exception as e:
            st_gz = "illeggibile (%s)" % e
        #  Nessun soldo era partito verso l'host: `_payout_trattieni` TOGLIE la riga del bonifico
        #  (stato '' = assente), non la lascia 'trattenuto' -- cosi' il pannello host non la conta
        #  per sempre fra i soldi «Fermi» (D13 della prova vera, 29/9).
        passo("soldi", "UNA richiesta a Stripe per ESATTAMENTE il pagato, con la chiave stabile "
                       "'rimborso:<riferimento>'; UNA riga 'rimborso' nel giornale della stessa cifra; la "
                       "riga del bonifico dell'host TOLTA (nessun soldo era partito) e la garanzia "
                       "'annullato' (l'host non incassa una prenotazione rimborsata)",
              len(rq) == 1 and rq[0][2] == pagato and rq[0][3] == "rimborso:" + rif
              and gw.rimborsati.get(pi) == pagato and giornale(rif, "rimborso") == [pagato]
              and st_pay == "" and st_gz == "annullato",
              "richieste=%s pagato=%s rimborsati=%s giornale=%s bonifico=%s garanzia=%s"
              % ([(x[2], x[3]) for x in rq], pagato, gw.rimborsati.get(pi), giornale(rif, "rimborso"),
                 st_pay, st_gz))

        # -- doppio -----------------------------------------------------------------------------------
        s_2, c_2 = b.g("POST", rotta, corpo, BH)
        passo("doppio", "un secondo clic non restituisce di nuovo: Stripe ha restituito una volta sola e il "
                        "giornale ha ancora UNA riga 'rimborso'",
              s_2 in (200, 409) and gw.rimborsati.get(pi) == pagato
              and giornale(rif, "rimborso") == [pagato],
              "http=%s risposta=%s rimborsati=%s giornale=%s"
              % (s_2, {k: (c_2 or {}).get(k) for k in ("stato", "errore", "rimborso_stripe")},
                 gw.rimborsati.get(pi), giornale(rif, "rimborso")))

        # -- controversia -----------------------------------------------------------------------------
        #  con una controversia aperta decide l'arbitro o la banca: l'admin NON rimborsa (pacco 1, voce 2)
        esito_c = b.sis.garanzia.contesta(rif2, motivo="catena 5: l'ospite contesta")
        corpo2 = corpo_di(p2)
        s_c, c_c = b.g("POST", rotta, corpo2, BH)
        passo("controversia", "con la controversia aperta il pulsante risponde 409 'controversia_aperta', "
                              "Stripe non riceve niente e le date restano occupate",
              bool((esito_c or {}).get("ok")) and s_c == 409
              and (c_c or {}).get("errore") == "controversia_aperta" and not richieste(pi2)
              and not libere(p2),
              "contestata=%s http=%s errore=%s richieste=%d libere=%s"
              % ((esito_c or {}).get("ok"), s_c, (c_c or {}).get("errore"), len(richieste(pi2)),
                 libere(p2)))

        # -- traccia ----------------------------------------------------------------------------------
        rif_reg = _rif_per_registro(rif)
        righe_gesto = [x for x in registro if "ADMIN_ACTION" in x and rif_reg in x]
        passo("traccia", "il gesto lascia UNA riga che unisce CHI (ip), COSA (il rimborso) e SU COSA (il "
                         "riferimento), come gli altri gesti dell'admin che muovono denaro",
              len(righe_gesto) == 1 and IP["X-Forwarded-For"] in righe_gesto[0],
              "righe durante il gesto=%d, ADMIN_ACTION col riferimento=%d; righe col riferimento: %s"
              % (len(registro), len(righe_gesto), [x[:80] for x in registro if rif_reg in x]))
    except RuntimeError as e:
        for anello in ANELLI_CATENA_5:
            passo(anello, "premessa della catena 5", False, str(e))


CATENA_5 = Catena(
    voce="Prenotazioni: Rimborsa",
    rotte=("/api/admin/rimborso",),
    anelli=ANELLI_CATENA_5,
    bottone="nella tabella delle prenotazioni premo «Rimborsa» su una prenotazione pagata: la prenotazione "
            "e' annullata, le date tornano prenotabili e la riga lo dice",
    soldi="restituisce all'ospite ESATTAMENTE il pagato, con UNA richiesta a Stripe e la chiave stabile "
          "'rimborso:<riferimento>' (un secondo clic non restituisce due volte); la riga del bonifico dell'host "
          "si toglie (nessun soldo era partito) e la garanzia passa a 'annullato'. Con una controversia aperta non parte niente: decide "
          "l'arbitro o la banca",
    archivio="scrive UNA riga 'rimborso' nel giornale dei soldi (il debito verso l'ospite: il giornale non si "
             "cancella, catena di impronte); segna il pagamento 'da rimborsare' nei pendenti; nessun dato "
             "personale nuovo. La traccia del gesto va nel registro del server, anello [traccia]",
    percorre=percorre_catena_5,
)

ANELLI_CATENA_6 = ("porta", "vede", "motivo", "storna", "soldi", "doppio", "solo_penali", "traccia")


def percorre_catena_6(b, BH, con_guasto=False):
    """Il pulsante «↩️ Storna» della scheda audit, sulle note di debito (le penali): l'admin
    corregge una penale sbagliata. Il giornale non si cancella: nasce la nota di credito contraria,
    la penale e il suo debito si chiudono, e quello che era GIA' stato trattenuto all'host torna nei
    suoi «da pagare» -- una volta sola.

    Scritta il 2026-11-07. La premessa la costruisce il prodotto, non una scorciatoia: un bonifico
    dell'host 'maturato' (prenotazione A), poi l'host cancella una prenotazione pagata (B) e la
    penale si compensa su A. Lo Stripe dei bonifici e' quello della catena 2, che rifiuta tutto:
    senza, il banco parlerebbe con la rete vera."""
    import dataclasses
    from fase101_stripe_connect import ProviderConnect
    from fase83_server import _rif_per_registro
    print("\n--- CATENA 6, «Storna» (scheda audit): penale -> nota contraria -> trattenuto restituito ---")
    rotta = "/api/admin/storno_penale"
    fc = b.sis.finanza
    stripe = _StripeCheRifiuta()
    connect_prima = b.sis.connect
    b.sis.connect = ProviderConnect("sk_test_catena6", fetch=stripe.post, fetch_get=stripe.get)
    storna_vera = None
    try:
        slug = b.alloggio("casa-catena-sei", 1, "2027-11-01", "2027-11-30")
        rif_a, _va = b.pagata(slug, "2027-11-05", "2027-11-07")
        rif_b, _vb = b.pagata(slug, "2027-11-12", "2027-11-14")
        if not (rif_a and rif_b):
            raise RuntimeError("il banco non ha prodotto le due prenotazioni pagate")
        if not b.sis.garanzia.conferma_ospite(rif_a).get("ok"):
            raise RuntimeError("il banco non ha chiuso la garanzia della prenotazione A")
        netto_a = int((b.sis.payout.info(rif_a) or {}).get("minori") or 0)
        s_hc, c_hc = b.g("POST", "/api/host/cancella", {"riferimento": rif_b}, b.tk)

        def nd_di(r):
            return [n for n in fc.note_per_riferimento(r) if n.get("tipo") == "debito"]

        def offset_di(nid, r):
            tot = 0
            for m in fc.movimenti(r):
                ev = str(m.get("evento_id") or "")
                if m.get("tipo") == "penale_offset" and ev.startswith("offset:%s:" % nid):
                    tot += int(m.get("importo_cents") or 0)
            return tot

        def nc_di(nid, r):
            return [n for n in fc.note_per_riferimento(r)
                    if n.get("tipo") == "credito" and n.get("storno_di") == nid]

        def audit(r):
            #  come nella catena 2: la chiave di Stripe si toglie sull'ISTANZA, l'esame non esce in rete
            cfg = b.sis.config
            b.sis.config = dataclasses.replace(cfg, stripe_secret_key="")
            try:
                s, c = _chiedi(b, "GET", "/api/admin/audit?id=" + r, None, ADMIN)
            finally:
                b.sis.config = cfg
            return s, (c or {})

        def registro_di(fare):
            righe = []

            class _Presa(logging.Handler):
                def emit(self, record):
                    try:
                        righe.append(record.getMessage())
                    except Exception:
                        righe.append(str(record.msg))
            presa = _Presa()
            log_server = logging.getLogger("core_auto.server")
            livello_prima = log_server.level
            log_server.addHandler(presa)
            log_server.setLevel(logging.DEBUG)
            try:
                esito = fare()
            finally:
                log_server.removeHandler(presa)
                log_server.setLevel(livello_prima)
            return esito, righe

        nds = nd_di(rif_b)
        nd = nds[0] if len(nds) == 1 else {}
        nid = str(nd.get("nota_id") or "")
        penale = int(nd.get("importo_cents") or 0)
        trattenuto = offset_di(nid, rif_b) if nid else 0
        #  LA PREMESSA, che NON e' un anello: senza, l'esame e' FERMO, non verde (S7).
        #  ⚠️ La penale si compensa sul bonifico 'maturato' PIU' VECCHIO dell'host (FIFO), e sul banco
        #  le catene prima ne lasciano: non e' detto che sia quello di A. Si pretende solo che una parte
        #  sia stata trattenuta davvero (primo giro del 7/11: trattenuto 3000, A intatto a 16400).
        if not (s_hc == 200 and nid and penale > 0 and trattenuto > 0 and netto_a > 0
                and nd.get("stato") != "stornata"):
            raise RuntimeError("premessa della catena 6 mancante: cancella=%s/%s note_debito=%d penale=%s "
                               "trattenuto=%s netto_A=%s"
                               % (s_hc, (c_hc or {}).get("errore") or (c_hc or {}).get("stato"),
                                  len(nds), penale, trattenuto, netto_a))
        corpo = {"nota_id": nid, "motivo": "catena 6: penale emessa per sbaglio"}

        # -- porta ------------------------------------------------------------------------------------
        s_senza, _ = b.g("POST", rotta, corpo, {})
        s_solo, c_solo = b.g("POST", rotta, corpo, ADMIN)
        passo("porta", "senza chiave 401, con la sola chiave admin 403 'bunker_richiesto' (muove soldi), e "
                       "la penale resta com'era, senza nessuna nota contraria",
              s_senza == 401 and s_solo == 403 and (c_solo or {}).get("errore") == "bunker_richiesto"
              and (fc.nota(nid) or {}).get("stato") != "stornata" and not nc_di(nid, rif_b),
              "senza=%s solo_chiave=%s/%s stato_nota=%s note_contrarie=%d"
              % (s_senza, s_solo, (c_solo or {}).get("errore"), (fc.nota(nid) or {}).get("stato"),
                 len(nc_di(nid, rif_b))))

        # -- vede -------------------------------------------------------------------------------------
        s_au, au = audit(rif_b)
        sua = [n for n in (au.get("note") or []) if n.get("nota_id") == nid]
        passo("vede", "la scheda audit della prenotazione mostra la penale come nota di DEBITO non stornata, "
                      "con la cifra del giornale (la pagina disegna «Storna» solo li')",
              s_au == 200 and len(sua) == 1 and sua[0].get("tipo") == "debito"
              and sua[0].get("stato") != "stornata" and int(sua[0].get("importo_cents") or 0) == penale,
              "http=%s nota=%s" % (s_au, sua))

        # -- motivo -----------------------------------------------------------------------------------
        s_m, c_m = b.g("POST", rotta, {"nota_id": nid, "motivo": "   "}, BH)
        passo("motivo", "senza un perche' il pulsante risponde 422 'motivo_obbligatorio' e la penale non si "
                        "tocca: una correzione di soldi ha sempre un motivo scritto",
              s_m == 422 and (c_m or {}).get("errore") == "motivo_obbligatorio"
              and (fc.nota(nid) or {}).get("stato") != "stornata" and not nc_di(nid, rif_b),
              "http=%s errore=%s stato_nota=%s" % (s_m, (c_m or {}).get("errore"),
                                                   (fc.nota(nid) or {}).get("stato")))

        # -- storna -----------------------------------------------------------------------------------
        if con_guasto:
            # IL GUASTO, sull'ISTANZA del controllore e mai sul codice: lo storno chiude la penale ma
            # «dimentica» il registro dei bonifici, quindi il trattenuto non torna all'host. E' l'anello
            # che vale i soldi: l'host avrebbe pagato una penale che noi stessi diciamo sbagliata.
            storna_vera = fc.storna_penale

            def _senza_restituire(**k):
                k["payout"] = None
                return storna_vera(**k)
            fc.storna_penale = _senza_restituire
        (s_s, c_s), registro = registro_di(lambda: b.g("POST", rotta, corpo, BH))
        if storna_vera is not None:
            fc.__dict__.pop("storna_penale", None)
            storna_vera = None
        c_s = c_s or {}
        ncs = nc_di(nid, rif_b)
        debiti = [d for d in fc.debiti_host(b.host_id) if d.get("debito_id") == nid]
        passo("storna", "risponde 200 con la nota contraria; la penale diventa 'stornata', nasce UNA nota "
                        "di credito della STESSA cifra che la nomina, e il debito dell'host va a zero "
                        "('stornato'): nessun giro lo riscuotera' piu'",
              s_s == 200 and c_s.get("gia_stornata") is False and bool(c_s.get("nc_id"))
              and (fc.nota(nid) or {}).get("stato") == "stornata"
              and len(ncs) == 1 and int(ncs[0].get("importo_cents") or 0) == penale
              and all(int(d.get("residuo_cents") or 0) == 0 and d.get("stato") == "stornato" for d in debiti),
              "http=%s risposta=%s stato_nota=%s note_contrarie=%s debiti=%s"
              % (s_s, c_s, (fc.nota(nid) or {}).get("stato"),
                 [(n.get("nota_id"), n.get("importo_cents")) for n in ncs],
                 [(d.get("residuo_cents"), d.get("stato")) for d in debiti]))

        # -- soldi ------------------------------------------------------------------------------------
        riga_rest = b.sis.payout.info("stornoND-" + nid) or {}
        passo("soldi", "quello che era gia' stato trattenuto all'host torna nei suoi «da pagare»: UNA riga "
                       "'maturato' di ESATTAMENTE il trattenuto (non la penale intera, non zero), e la "
                       "risposta lo dice",
              int(c_s.get("riscosso_cents") or -1) == trattenuto
              and int(c_s.get("restituito_in_da_pagare") or -1) == trattenuto
              and b.sis.payout.stato_di("stornoND-" + nid) == "maturato"
              and int(riga_rest.get("minori") or 0) == trattenuto,
              "trattenuto=%s penale=%s risposta riscosso/restituito=%s/%s riga=%s/%s"
              % (trattenuto, penale, c_s.get("riscosso_cents"), c_s.get("restituito_in_da_pagare"),
                 b.sis.payout.stato_di("stornoND-" + nid), riga_rest.get("minori")))

        # -- doppio -----------------------------------------------------------------------------------
        s_2, c_2 = b.g("POST", rotta, corpo, BH)
        riga_dopo = b.sis.payout.info("stornoND-" + nid) or {}
        passo("doppio", "un secondo clic risponde 'gia_stornata' e non fa niente: ancora UNA nota contraria "
                        "e la riga restituita con la stessa cifra (l'host non e' rimborsato due volte)",
              s_2 == 200 and (c_2 or {}).get("gia_stornata") is True and len(nc_di(nid, rif_b)) == 1
              and int(riga_dopo.get("minori") or 0) == int(riga_rest.get("minori") or -1),
              "http=%s gia_stornata=%s note_contrarie=%d riga=%s->%s"
              % (s_2, (c_2 or {}).get("gia_stornata"), len(nc_di(nid, rif_b)), riga_rest.get("minori"),
                 riga_dopo.get("minori")))

        # -- solo_penali ------------------------------------------------------------------------------
        nc_id = str((ncs[0] if ncs else {}).get("nota_id") or "")
        s_nc, c_nc = b.g("POST", rotta, {"nota_id": nc_id, "motivo": "catena 6: provo a stornare il credito"},
                         BH)
        passo("solo_penali", "una nota di CREDITO non si storna: 404 'nota_non_trovata_o_non_ND', e non nasce "
                             "nessuna nota nuova",
              bool(nc_id) and s_nc == 404 and (c_nc or {}).get("errore") == "nota_non_trovata_o_non_ND"
              and len(fc.note_per_riferimento(rif_b)) == 2,
              "nc=%s http=%s errore=%s note=%d" % (nc_id, s_nc, (c_nc or {}).get("errore"),
                                                   len(fc.note_per_riferimento(rif_b))))

        # -- traccia ----------------------------------------------------------------------------------
        rif_reg = _rif_per_registro(nid)
        righe_gesto = [x for x in registro if "ADMIN_ACTION" in x and "Storno penale" in x and rif_reg in x]
        passo("traccia", "il gesto lascia UNA riga che unisce CHI (ip), COSA (lo storno, col motivo) e SU COSA "
                         "(la nota), come gli altri gesti dell'admin che muovono denaro",
              len(righe_gesto) == 1 and IP["X-Forwarded-For"] in righe_gesto[0],
              "righe durante il gesto=%d, ADMIN_ACTION con la nota=%d; %s"
              % (len(registro), len(righe_gesto), [x[:90] for x in righe_gesto]))
    except RuntimeError as e:
        for anello in ANELLI_CATENA_6:
            passo(anello, "premessa della catena 6", False, str(e))
    finally:
        if storna_vera is not None:
            fc.__dict__.pop("storna_penale", None)
        b.sis.connect = connect_prima


CATENA_6 = Catena(
    voce="Scheda audit: Storna la penale",
    rotte=("/api/admin/storno_penale",),
    anelli=ANELLI_CATENA_6,
    bottone="nella scheda audit premo «↩️ Storna» su una nota di debito (una penale), scrivo il perche' e "
            "confermo: la penale risulta 'stornata' e la scheda si ricarica",
    soldi="la penale si annulla con una nota di credito della stessa cifra (il giornale non si riscrive); il "
          "debito dell'host va a zero; quello che gli era gia' stato trattenuto torna nei suoi «da pagare» "
          "come riga 'maturato' da pagare A MANO (mai un bonifico automatico), una volta sola",
    archivio="scrive UNA nota di credito e la riga contraria nel giornale dei soldi (catena di impronte, non "
             "si cancella); cambia lo stato della nota e del debito; aggiunge la riga `stornoND-<nota>` "
             "nell'archivio dei bonifici. Nessun dato personale nuovo (il soggetto e' l'id dell'host). La "
             "traccia del gesto va nel registro del server, anello [traccia]",
    percorre=percorre_catena_6,
)

#  ⛔ Una rotta qui che la pagina non nomina piu' e' ROSSA (dichiarazione invecchiata).
CATENE = {rotta: cat for cat in (CATENA_1, CATENA_2, CATENA_3, CATENA_4, CATENA_5, CATENA_6)
          for rotta in cat.rotte}

#  Ogni BOTTONE e ogni CAMPO della pagina va attribuito: alla rotta che il gesto attraversa
#  (e allora la sua catena e' quella della rotta), oppure a `PAGINA_SOLA` con il perche' --
#  non manda niente al server da se'. Una voce NON attribuita e' rossa: e' il «bottone numero
#  22», cioe' un gesto entrato nel pannello che nessuno ha guardato.
#  ⛔ Le identita' le stampa `--perimetro`: si prendono da li', mai a memoria (sbaglio S2).
PAGINA_SOLA = "pagina"

BOTTONI = {
    "#btnCarica": "/api/admin/prenotazioni",          # ricarica: verifiche + annunci + prenotazioni
    "#pr_prec": "/api/admin/prenotazioni",            # le pagine delle prenotazioni (D16, 29/9)
    "#pr_succ": "/api/admin/prenotazioni",
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
    "pagoAMano()": "/api/admin/payout/pagato_a_mano",   # R1 (21/10): dentro la scheda audit
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
#     ⚠️ ALZATO A 20 IL 2026-10-21, e spiegato: e' entrato il pulsante «Lo pago io a mano»
#     (R1, `/api/admin/payout/pagato_a_mano`). Le sue tre colonne -- il bottone, i soldi (il
#     payout va in 'in_transito' e nessun giro lo ripaga), l'archivio (la riga `payout_host`
#     del giornale) -- le percorrono 12 prove di `test_fase83_server.TestIlPagamentoAMano` e
#     vicine, NON ancora una catena di questo esame: e' debito di questa casella, scritto in
#     RIPRENDI_QUI col suo posto, e il tetto torna a 19 quando la catena c'e'.
#     ✅ TORNATO A 19 IL 2026-11-04: la CATENA 2 («Lo pago io a mano») percorre quella rotta
#     anello per anello sul banco (porta · vede · garanzia · prende · soldi · doppio · traccia).
#     ✅ A 17 LO STESSO GIORNO: la CATENA 3 («Controversie: elenco e Risolvi») percorre le due rotte
#     della voce (vede · ferma · porta · fuori · decide · soldi · doppio · traccia).
#     ✅ A 15 IL 2026-11-06: la CATENA 4 («Rimborsi dovuti: elenco e Rimborsa») percorre le due rotte
#     della voce (porta · vede · cieco · cifra · rimborsa · doppio · divergenza · traccia).
#     ✅ A 13 IL 2026-11-07: la CATENA 5 («Prenotazioni: Rimborsa») e la CATENA 6 («Scheda audit:
#     Storna la penale») percorrono una rotta ciascuna.
ROTTE_SENZA_CATENA_TETTO = 13


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
