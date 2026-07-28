# -*- coding: utf-8 -*-
"""COLLAUDO PROFONDO — IL CONTRATTO «PAGINE ↔ API» (quello che l'utente tocca davvero).

Le suite esistenti provano il server dal lato del server. Qui si prova dal lato del
DITO DELL'UTENTE: si legge il codice HTML/JS di TUTTE le pagine in `deploy/`, si estrae
cio' che le pagine PROMETTONO (rotte chiamate, campi inviati, tasti, messaggi) e si
pretende che il server MANTENGA ognuna di quelle promesse.

Quattro promesse, quattro modi di romperle:

  1. ROTTA CHIAMATA E INESISTENTE — la pagina chiama `/api/x`, il router non ce l'ha:
     l'utente clicca e non succede NULLA (404 muto dentro un catch).
  2. CAMPO INVIATO E IGNORATO — il modulo manda `sconto_mese_bps`, il server lo scarta:
     l'host CREDE di aver messo lo sconto, il prezzo non cambia mai. E' il difetto piu'
     velenoso perche' la schermata dice «salvato».
  3. TASTO MORTO — un <button> che nessun codice cabla: l'utente preme e non accade nulla.
  4. MESSAGGIO SENZA TRADUZIONE — la pagina mostra una chiave nuda (`err_key`) o un codice
     tecnico del server (`min_notti`) al posto di una frase.

METODO ANTI-FINTO-VERDE. Un estrattore statico che non trova niente sarebbe verde per il
motivo peggiore. Percio' `TestEstrattoreVedeDavvero` prova PRIMA l'estrattore stesso su un
sorgente finto di cui si conosce la risposta esatta, e impone un minimo per ogni pagina
vera: se domani una regex smette di agganciare, il test diventa rosso subito.

VISTO ROSSO (regola aurea — nessun verde vale finche' non e' stato visto rosso). OGNI
guardia di questo file e' stata messa davanti al guasto che deve vedere, con il mutante
iniettato nel sorgente e subito ripristinato byte per byte (sha256 confrontato):

  DIFETTI VERI, trovati scrivendo il file e poi CORRETTI
  · `fase191_blocco_globale.imposta` senza la guardia sul percorso vuoto (modalita'
    «solo-env») -> lasciava un file `.tmp` spazzatura nella cartella di lavoro del
    processo a ogni pressione del tasto rosso, e il router rispondeva 500.
    Guardia: test_kill_switch_senza_file_non_sporca_la_cartella.
  · `deploy/app.js` senza i 12 codici del giro ospite nel dizionario -> l'ospite che non
    riusciva a prenotare leggeva `pieno`, `min_notti`, `giorno_non_caricato`,
    `transazioni_sospese` cosi' com'erano. Guardia: test_i_codici_che_l_ospite_puo_
    vedere_sono_tradotti_in_8_lingue + test_le_frasi_dei_codici_ospite_non_sono_il_codice.
  · `deploy/index.html` stampava `r.motivo` GREZZO (senza passare dal dizionario).
    Guardia: test_il_motivo_del_rifiuto_passa_dal_dizionario.

  MUTANTI INIETTATI (una riga di prodotto guastata -> la guardia si accende)
  · rotta rinominata `/api/host/payout` -> `_payout_RINOMINATA`  ......  rotta esiste (x2:
    controllo statico sulla tabella + interrogazione DAL VIVO del router)
  · `dati.pop("sconto_mese_bps")` in `_host_pubblica`  .............  campo ignorato
  · chiave `sconto_mese_bps` rinominata in host.html  ...............  campo non provato
  · `iban` tolto da `RegistroHost.CAMPI_FISCALI`  ...................  campo fiscale perso
  · `ragione_sociale=""` in `_host_registrazione`  ..................  campo facoltativo perso
  · `capacita_min=None` in `_catalogo`  .............................  filtro che non filtra
  · `geo = None` in `_catalogo`  ....................................  «vicino a me» spento
  · lat/lon scambiati nel GeoJSON di `_mappa`  ......................  pin sull'altro emisfero
  · `host_id = None` in `_admin_alloggi`  ...........................  filtro admin ignorato
  · soglia dei 2 caratteri disattivata in `_admin_search`  ..........  ricerca senza guardia
  · `limit` fisso a 10 in `_host_prenotazioni`  .....................  paginazione ignorata
  · `imposta_stato(slug, "pubblicato")` in `_host_stato`  ...........  «sospendi» che non sospende
  · `politica_cancellazione` fissa in `_dettaglio_json` (fase57)  ...  scelta host non arriva all'ospite
  · `"paese"` rinominata in `_card_json` (fase57)  ..................  card muta in vetrina
  · `prezzo_netto_cents=1` forzato in `_host_disponibilita_range`  ..  prezzo del calendario perso
  · `n=3` forzato in `_split_preview`  ..............................  numero persone ignorato
  · `occupazione_bps` fisso in `_prezzo_suggerito`  .................  manopola scollegata
  · `prezzo_cents` fisso in `_trasparenza`  .........................  confronto sempre uguale
  · `motivo = ""` in `_bunker_blocco_globale_imposta`  ..............  emergenza senza motivo
  · `_host_login` che risponde sempre 401 generico  .................  contratto di risposta rotto
  · `_admin_prenotazioni` che risponde 200 a chiunque  ..............  pannello senza chiave
  · rotta binaria `marca.tsr` spostata dentro il router  ............  confine HTTP violato
  · id `c_slug` rinominato in host.html  ............................  getElementById -> null
  · `<button id=btnCerca>` rinominato in admin.html  ................  tasto morto
  · `onsubmit` disattivato in partner.html  .........................  modulo che ricarica
  · chiave tolta da `TR.zh` in bunker.html  .........................  «undefined» al super-admin
  · chiave tolta da `TR.en` in admin.html  ..........................  chiave nuda in faccia
  · `t('caricamento')` -> chiave inventata in index.html  ...........  chiave non nel motore
  · chiave in piu' nella sola `fr` di host.html  ....................  debito che cresce
  · `_fallback` disattivato in host.html  ...........................  ripiego perso
  · index.html che chiama una rotta admin  ..........................  confine pubblico violato

  DUE GUARDIE SONO STATE TROVATE CIECHE E CORRETTE (la lezione del file):
  · «ogni bottone e' cablato» cercava il nome dell'id nel sorgente COMPLETO: l'attributo
    `id="btnX"` del bottone faceva da testimone di SE STESSO e un tasto mai cablato
    passava. Ora gli `id=...` si tolgono prima di cercare chi lo NOMINA.
  · «ogni rotta esiste» da sola non vede una rotta DISATTIVATA (`if False and path ==`):
    la tabella si legge dal sorgente e il testo resta. Per questo c'e' anche la prova
    DAL VIVO, che interroga il router vero: quella la vede.

Stdlib pura, zero rete, DB su file temporanei (mai :memory:), deterministico.
"""
import datetime
import io
import json
import os
import re
import shutil
import tempfile
import unittest

from fase61_localizzazione import LINGUE_SUPPORTATE
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import _dizionario_i18n, crea_router
from fase88_registro_host import RegistroHost
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

QUI = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.join(QUI, "deploy")

# Le 14 pagine che l'utente puo' aprire + il modulo comune app.js.
PAGINE = ("index.html", "host.html", "admin.html", "bunker.html", "partner.html",
          "diventa-host.html", "commissioni.html", "termini.html", "privacy.html",
          "contratto-host.html", "guida-operativa.html", "kit-marketing.html",
          "grazie.html", "annullato.html", "app.js")

# Quante rotte DEVE almeno trovare l'estrattore, pagina per pagina (fotografia del
# 2026-07-28). Serve solo a smascherare un estrattore rotto: se una regex smette di
# agganciare, questi numeri crollano e il test diventa rosso PRIMA di dare falsi verdi.
MINIMO_ROTTE = {"index.html": 12, "host.html": 45, "admin.html": 19, "bunker.html": 20,
                "partner.html": 1, "diventa-host.html": 1, "termini.html": 1,
                "privacy.html": 1, "contratto-host.html": 1}

# Rotta servita dal livello HTTP e NON dal router (esce in BINARIO: token della marca
# temporale). Presidiata da test_rotte_scoperte; qui si dichiara l'eccezione per non
# scambiarla per una chiamata a vuoto.
ROTTA_FUORI_ROUTER = "/api/bunker/marca.tsr"
# Prefisso composto a runtime: '/api/host/richieste/' + ('approva'|'rifiuta').
PREFISSO_RUNTIME = {"/api/host/richieste/": ("approva", "rifiuta")}


def _leggi(nome):
    with io.open(os.path.join(DEPLOY, nome), encoding="utf-8") as f:
        return f.read()


# ══════════════════════════════════════════════════════════════════════════════════
# ESTRATTORE STATICO — legge le pagine come le legge il browser
# ══════════════════════════════════════════════════════════════════════════════════
_RE_ROTTA = re.compile(r"""(['"`])(/api/[^'"`\s]*)""")


def rotte_di(sorgente):
    """Ogni riferimento a una rotta `/api/...` presente in un letterale di stringa.
    Cattura sia `fetch('/api/x')` sia `api('/api/x?'+params)` sia `post('/api/x', ...)`:
    quello che conta e' il PATH, comunque sia costruita la query."""
    return {m.group(2).split("?")[0] for m in _RE_ROTTA.finditer(sorgente)}


def _bilanciato(s, j):
    """Il letterale-oggetto JS che comincia a `s[j] == '{'`, stringhe rispettate."""
    profondita, k = 0, j
    while k < len(s):
        c = s[k]
        if c in "'\"`":
            q = c
            k += 1
            while k < len(s) and s[k] != q:
                if s[k] == "\\":
                    k += 1
                k += 1
        elif c == "{":
            profondita += 1
        elif c == "}":
            profondita -= 1
            if profondita == 0:
                return s[j:k + 1]
        k += 1
    return None


def _pezzi_primo_livello(oggetto):
    """Le voci di primo livello di un letterale-oggetto JS (annidamenti ignorati)."""
    pezzi, livello, inizio, i = [], 0, 1, 1
    while i < len(oggetto) - 1:
        c = oggetto[i]
        if c in "'\"`":
            q = c
            i += 1
            while i < len(oggetto) and oggetto[i] != q:
                if oggetto[i] == "\\":
                    i += 1
                i += 1
        elif c in "{[(":
            livello += 1
        elif c in "}])":
            livello -= 1
        elif c == "," and livello == 0:
            pezzi.append(oggetto[inizio:i])
            inizio = i + 1
        i += 1
    pezzi.append(oggetto[inizio:len(oggetto) - 1])
    return pezzi


def chiavi_di(oggetto):
    """I nomi delle chiavi di primo livello (`{a:1, 'b':2, c}` -> ['a','b','c'])."""
    fuori = []
    for p in _pezzi_primo_livello(oggetto):
        m = re.match(r"\s*['\"]?([A-Za-z_$][\w$]*)['\"]?\s*:", p)
        if m:
            fuori.append(m.group(1))
            continue
        m2 = re.match(r"\s*([A-Za-z_$][\w$]*)\s*$", p)
        if m2:
            fuori.append(m2.group(1))
    return fuori


def campi_inviati(sorgente):
    """{rotta: {campi del corpo JSON}} per ogni chiamata che spedisce un corpo.

    Copre le due forme che le pagine usano davvero:
      post('/api/x', {a:1, b:2})                      -> corpo diretto
      fetch('/api/x', {method:'POST', body:JSON.stringify({a:1})})
    """
    fuori = {}
    for m in _RE_ROTTA.finditer(sorgente):
        rotta = m.group(2).split("?")[0]
        j = sorgente.find("{", m.end(), m.end() + 260)
        if j < 0:
            continue
        oggetto = _bilanciato(sorgente, j)
        if oggetto is None:
            continue
        chiavi = chiavi_di(oggetto)
        if "body" in chiavi or "method" in chiavi:
            i = oggetto.find("JSON.stringify(")
            if i < 0:
                continue                       # POST senza corpo (es. logout)
            interno = _bilanciato(oggetto, oggetto.find("{", i))
            if interno is None:
                continue
            chiavi = chiavi_di(interno)
        elif "headers" in chiavi:
            continue                            # GET con sole testate: nessun corpo
        fuori.setdefault(rotta, set()).update(chiavi)
    return fuori


def bottoni(sorgente):
    """Gli attributi di ogni `<button ...>` della pagina."""
    return [m.group(1) for m in re.finditer(r"<button\b([^>]*)>", sorgente, re.I)]


def id_dichiarati(sorgente):
    return set(re.findall(r"""\bid\s*=\s*["']([^"']+)["']""", sorgente))


def id_usati(sorgente):
    """Gli id cercati dal JS: `getElementById('x')` e la scorciatoia `$('x')`."""
    a = set(re.findall(r"""getElementById\(\s*['"]([^'"]+)['"]\s*\)""", sorgente))
    b = set(re.findall(r"""\$\(\s*['"]([^'"]+)['"]\s*\)""", sorgente))
    return a | b


def dizionario_tr(sorgente):
    """{lingua: {chiavi}} del blocco `const TR = {...}` della pagina."""
    m = re.search(r"const\s+TR\s*=\s*\{", sorgente)
    if m is None:
        return {}
    oggetto = _bilanciato(sorgente, m.end() - 1)
    lingue = {}
    for pezzo in _pezzi_primo_livello(oggetto):
        t = re.match(r"\s*['\"]?([a-z]{2}(?:-[a-z]{2})?)['\"]?\s*:\s*", pezzo)
        if t is None:
            continue
        resto = pezzo[t.end():].strip()
        if resto.startswith("{"):
            lingue[t.group(1)] = set(chiavi_di(_bilanciato(resto, 0)))
    return lingue


def chiavi_i18n_usate(sorgente):
    """Le chiavi di traduzione che la pagina chiede davvero: `T('x')`, `T.x`, `t('x')`
    e gli attributi `data-i18n` / `data-i18n-html` / `data-i18n-ph`."""
    fun = set(re.findall(r"""\b[tT]\(\s*['"]([^'"]+)['"]\s*\)""", sorgente))
    prop = set(re.findall(r"\bT\.([A-Za-z_$][\w$]*)\b", sorgente))
    attr = set(re.findall(
        r"""data-i18n(?:-html|-ph)?\s*=\s*["']([^"']+)["']""", sorgente))
    return fun | prop | attr


def tabella_rotte_router():
    """(rotte esatte, prefissi) servite dal router, LETTE DAL SORGENTE di `_instrada`.
    Non una lista scritta a mano: se domani si aggiunge/toglie una rotta, qui si vede."""
    with io.open(os.path.join(QUI, "fase83_server.py"), encoding="utf-8") as f:
        s = f.read()
    i = s.index("def _instrada")
    j = s.index('return 404, {"errore": "rotta_non_trovata"}')
    blocco = s[i:j]
    esatte = set(re.findall(r'path == "(/[^"]+)"', blocco))
    prefissi = set(re.findall(r'path\.startswith\("(/[^"]+)"\)', blocco))
    return esatte, prefissi


# ══════════════════════════════════════════════════════════════════════════════════
# 0. L'ESTRATTORE VEDE DAVVERO (anti-finto-verde)
# ══════════════════════════════════════════════════════════════════════════════════
class TestEstrattoreVedeDavvero(unittest.TestCase):
    """Se le regex smettessero di agganciare, TUTTI i test di questo file passerebbero
    a vuoto. Qui l'estrattore viene provato su un sorgente finto di cui si conosce la
    risposta ESATTA, e poi su ogni pagina vera con un pavimento minimo."""

    FINTO = """
      const a = await post('/api/finto/uno', {alfa:1, beta:'x', gamma:[1,2]});
      const b = await getJson('/api/finto/due?q='+x, {headers:{'X-K':k}});
      fetch('/api/finto/tre', {method:'POST', headers:{}, body:JSON.stringify({delta:9})});
      <button id="b1" onclick="vai()">ok</button><button class="riga" data-s="1">x</button>
    """

    def test_estrae_le_rotte_esatte_del_sorgente_finto(self):
        self.assertEqual(rotte_di(self.FINTO),
                         {"/api/finto/uno", "/api/finto/due", "/api/finto/tre"})

    def test_estrae_i_campi_del_corpo_nelle_due_forme(self):
        campi = campi_inviati(self.FINTO)
        self.assertEqual(campi["/api/finto/uno"], {"alfa", "beta", "gamma"})
        self.assertEqual(campi["/api/finto/tre"], {"delta"})
        self.assertNotIn("/api/finto/due", campi,
                         "una GET con sole testate non manda campi: non va scambiata "
                         "per un corpo (falso positivo che sporcherebbe tutto il file)")

    def test_estrae_i_bottoni_e_gli_id(self):
        self.assertEqual(len(bottoni(self.FINTO)), 2)
        self.assertEqual(id_dichiarati(self.FINTO), {"b1"})

    def test_ogni_pagina_vera_supera_il_suo_minimo(self):
        for pagina, minimo in sorted(MINIMO_ROTTE.items()):
            with self.subTest(pagina=pagina):
                trovate = rotte_di(_leggi(pagina))
                self.assertGreaterEqual(
                    len(trovate), minimo,
                    "%s: trovate %d rotte invece di almeno %d -> l'estrattore e' cieco "
                    "(oppure la pagina ha perso delle chiamate)" % (pagina, len(trovate),
                                                                    minimo))

    def test_la_tabella_del_router_non_e_vuota(self):
        esatte, prefissi = tabella_rotte_router()
        self.assertGreaterEqual(len(esatte), 120,
                                "lette solo %d rotte da _instrada: il lettore del "
                                "sorgente e' rotto" % len(esatte))
        self.assertIn("/api/catalogo/", prefissi)
        self.assertIn("/api/host/pubblica", esatte)


# ══════════════════════════════════════════════════════════════════════════════════
# INFRASTRUTTURA: sistema vero + router vero (nessun finto)
# ══════════════════════════════════════════════════════════════════════════════════
class _BasePagine(unittest.TestCase):

    def setUp(self):
        self._env0 = {k: os.environ.get(k) for k in ("UPLOAD_DIR", "PAGA_STRUTTURA_ATTIVO")}
        self.d = d = tempfile.mkdtemp(prefix="pagine_api_")
        os.environ["UPLOAD_DIR"] = d + "/uploads"
        os.environ["PAGA_STRUTTURA_ATTIVO"] = "0"
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"P" * 32, con_registrazione_host=True,
            db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
            db_accettazioni=d + "/a.db", db_pendenti=d + "/p.db", db_payout=d + "/po.db",
            db_finanza=d + "/f.db", db_messaggi=d + "/m.db", db_domanda=d + "/dom.db",
            db_partner=d + "/par.db", db_recensioni=d + "/rec.db",
            file_blocco_globale=d + "/bg.flag", bunker_password="SuperPw@1",
            commissione_bps=1000, psp_bps=300))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        self.admin = {"X-Admin-Key": "ak"}

    def tearDown(self):
        for k, v in self._env0.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, metodo, path, corpo=None, testate=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(corpo) if corpo is not None else None,
                               testate or {})

    def host(self, email="host@pagine.it"):
        """Un host registrato: (host_id, testate col token self-service)."""
        st, c = self.g("POST", "/api/host/registrazione", {
            "email": email, "password": "password1", "accetta_termini": True,
            "accetta_clausole": True, "accetta_privacy": True,
            "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE,
            "ragione_sociale": "Immobiliare Prova SRL", "telefono": "+390612345678"})
        self.assertEqual(st, 201, c)
        return c["host_id"], {"X-Host-Token": c["token"]}

    def bunker(self):
        st, o = self.g("POST", "/api/bunker/login", {"codice": "SuperPw@1"}, self.admin)
        self.assertEqual(st, 200, o)
        testate = dict(self.admin)
        testate["X-Bunker-Session"] = o["sessione"]
        return testate


# ══════════════════════════════════════════════════════════════════════════════════
# 1. NESSUNA CHIAMATA A VUOTO — ogni rotta che le pagine chiamano ESISTE
# ══════════════════════════════════════════════════════════════════════════════════
class TestOgniRottaChiamataEsiste(_BasePagine):

    @classmethod
    def setUpClass(cls):
        cls.riferimenti = {}
        for pagina in PAGINE:
            for rotta in rotte_di(_leggi(pagina)):
                cls.riferimenti.setdefault(rotta, set()).add(pagina)

    def test_almeno_ottanta_rotte_distinte_sono_chiamate_dalle_pagine(self):
        self.assertGreaterEqual(len(self.riferimenti), 80,
                                "solo %d rotte distinte: l'estrattore e' cieco"
                                % len(self.riferimenti))

    def test_ogni_rotta_chiamata_dalle_pagine_esiste(self):
        """STATICO: ogni path nominato dalle pagine e' nella tabella del router."""
        esatte, prefissi = tabella_rotte_router()
        orfane = []
        for rotta, pagine in sorted(self.riferimenti.items()):
            if rotta in esatte or rotta == ROTTA_FUORI_ROUTER:
                continue
            if any(rotta.startswith(p) and rotta != p for p in prefissi):
                continue
            if rotta in prefissi:
                continue
            if rotta in PREFISSO_RUNTIME:
                mancano = [s for s in PREFISSO_RUNTIME[rotta] if rotta + s not in esatte]
                if mancano:
                    orfane.append("%s + %s (%s)" % (rotta, mancano, sorted(pagine)))
                continue
            orfane.append("%s (chiamata da %s)" % (rotta, sorted(pagine)))
        self.assertEqual(orfane, [],
                         "queste rotte sono chiamate dalle pagine e NON esistono nel "
                         "router: l'utente clicca e non succede niente -> %s" % orfane)

    def test_dal_vivo_il_router_non_risponde_mai_rotta_non_trovata(self):
        """DAL VIVO: il router VERO interrogato su ogni path nominato dalle pagine.
        Corpo assente -> le POST si fermano su `json_non_valido`: nessun effetto
        collaterale, ma la porta deve comunque ESSERE APERTA."""
        for rotta in sorted(self.riferimenti):
            if rotta == ROTTA_FUORI_ROUTER:
                continue
            candidate = ([rotta + s for s in PREFISSO_RUNTIME[rotta]]
                         if rotta in PREFISSO_RUNTIME else [rotta])
            for path in candidate:
                for metodo in ("GET", "POST"):
                    st, corpo = self.g(metodo, path)
                    if st == 404 and corpo.get("errore") == "rotta_non_trovata":
                        continue        # 404 su UNO dei due metodi e' normale
                    break
                else:
                    self.fail("%s: ne' GET ne' POST sono serviti dal router "
                              "(rotta_non_trovata su entrambi)" % path)

    def test_la_rotta_binaria_resta_fuori_dal_router_ed_e_voluto(self):
        """`marca.tsr` esce in binario: vive nel livello HTTP. Se qualcuno la spostasse
        nel router (dove non puo' uscire binaria) il bunker smetterebbe di scaricarla."""
        self.assertIn(ROTTA_FUORI_ROUTER, self.riferimenti,
                      "bunker.html non la chiama piu': l'eccezione va tolta")
        st, corpo = self.g("GET", ROTTA_FUORI_ROUTER, None, self.admin)
        self.assertEqual((st, corpo), (404, {"errore": "rotta_non_trovata"}))
        with io.open(os.path.join(QUI, "fase83_server.py"), encoding="utf-8") as f:
            self.assertIn('u.path == "%s"' % ROTTA_FUORI_ROUTER, f.read())

    def test_nessuna_pagina_chiama_una_rotta_admin_dalla_vetrina_pubblica(self):
        """Confine: le pagine dell'OSPITE non devono nominare rotte admin/bunker (una
        chiave admin non finirebbe mai in una pagina pubblica, ma il nome della rotta e'
        gia' un invito a bussare)."""
        for pagina in ("index.html", "diventa-host.html", "partner.html", "commissioni.html",
                       "grazie.html", "annullato.html", "termini.html", "privacy.html"):
            for rotta in sorted(rotte_di(_leggi(pagina))):
                self.assertFalse(rotta.startswith(("/api/admin/", "/api/bunker/")),
                                 "%s (pagina pubblica) nomina %s" % (pagina, rotta))


# ══════════════════════════════════════════════════════════════════════════════════
# 2. NESSUN CAMPO IGNORATO IN SILENZIO
#    Il modo di rompersi peggiore: la pagina dice «salvato», il server ha buttato via
#    il campo. Qui NON basta un 200: si rilegge il valore e si pretende identico.
# ══════════════════════════════════════════════════════════════════════════════════
class TestNessunCampoIgnorato(_BasePagine):

    # Valori DISTINTIVI: se un campo venisse ignorato e sostituito da un default, il
    # valore letto sarebbe diverso da questo (un default non e' mai 1500 o 'Via Test 7').
    CAMPI_ANNUNCIO = {
        "slug": "casa-contratto", "titolo": "Attico del Contratto", "citta": "Roma",
        "paese": "IT", "cin": "IT058091C2X5V0ABCD",
        "descrizione": "Descrizione distintiva 20260728", "indirizzo": "Via Test 7",
        "lat_micro": 41902782, "lon_micro": 12496366, "pin_manuale": True,
        "valuta": "EUR", "prezzo_notte_cents": 12345,
        "politica_cancellazione": "non_rimborsabile", "tassa_pp_notte_cents": 222,
        "tassa_max_notti": 3, "sconto_settimana_bps": 1500, "sconto_mese_bps": 2500,
        "modalita_prenotazione": "su_richiesta", "paga_in_struttura": False,
        "capacita": 7, "servizi": ["wifi", "piscina"], "immagini": ["/uploads/prova.jpg"],
    }

    def test_il_modulo_annuncio_della_pagina_non_ha_campi_sconosciuti(self):
        """Il banco di prova qui sotto deve coprire OGNI campo che host.html spedisce:
        se domani la pagina aggiunge una casella e nessuno la prova, questo test lo dice."""
        dalla_pagina = campi_inviati(_leggi("host.html"))["/api/host/pubblica"]
        scoperti = sorted(dalla_pagina - set(self.CAMPI_ANNUNCIO))
        self.assertEqual(scoperti, [],
                         "host.html manda campi che nessuno prova: %s" % scoperti)
        self.assertGreaterEqual(len(dalla_pagina), 20,
                                "solo %d campi estratti dal modulo annuncio: estrattore "
                                "cieco" % len(dalla_pagina))

    def test_pubblica_nessun_campo_del_modulo_viene_ignorato(self):
        """Ogni casella del modulo «pubblica annuncio» torna indietro col SUO valore."""
        _hid, tk = self.host()
        st, corpo = self.g("POST", "/api/host/pubblica", dict(self.CAMPI_ANNUNCIO), tk)
        self.assertEqual(st, 201, corpo)
        self.assertEqual(corpo["slug"], self.CAMPI_ANNUNCIO["slug"])

        st, det = self.g("GET", "/api/host/alloggio", None, tk,
                         {"slug": self.CAMPI_ANNUNCIO["slug"]})
        self.assertEqual(st, 200, det)
        perduti = []
        for campo, atteso in sorted(self.CAMPI_ANNUNCIO.items()):
            if campo in ("titolo", "immagini"):
                continue                       # provati a parte (forma diversa)
            if campo not in det:
                perduti.append("%s: assente nella scheda" % campo)
            elif det[campo] != atteso:
                perduti.append("%s: inviato %r, riletto %r" % (campo, atteso, det[campo]))
        self.assertEqual(perduti, [],
                         "campi INVIATI dal modulo e non conservati (l'host crede di "
                         "averli impostati): %s" % perduti)
        self.assertEqual(det["titolo"], self.CAMPI_ANNUNCIO["titolo"])
        self.assertEqual([i["url"] for i in det["immagini"]],
                         self.CAMPI_ANNUNCIO["immagini"])
        # i soldi restano INTERI: nessun float si e' infilato nel giro
        for campo in ("prezzo_notte_cents", "tassa_pp_notte_cents"):
            self.assertIsInstance(det[campo], int)
            self.assertNotIsInstance(det[campo], bool)

    def test_le_scelte_dell_host_arrivano_fino_all_ospite(self):
        """Non basta che il campo sia SALVATO: deve arrivare in vetrina. Un campo salvato
        ma non esposto e' identico, per l'ospite, a un campo ignorato."""
        _hid, tk = self.host()
        st, _ = self.g("POST", "/api/host/pubblica", dict(self.CAMPI_ANNUNCIO), tk)
        self.assertEqual(st, 201)
        st, pub = self.g("GET", "/api/catalogo/" + self.CAMPI_ANNUNCIO["slug"])
        self.assertEqual(st, 200, pub)
        self.assertEqual(pub["prezzo_notte_cents"], 12345)
        self.assertEqual(pub["capacita"], 7)
        self.assertEqual(pub["valuta"], "EUR")
        self.assertEqual(pub["politica_cancellazione"], "non_rimborsabile")
        self.assertEqual(pub["modalita_prenotazione"], "su_richiesta")
        self.assertEqual(sorted(pub["servizi"]), ["piscina", "wifi"])

    def test_dati_fiscali_ogni_campo_del_modulo_e_conosciuto_dal_registro(self):
        """I 6 campi che host.html manda esistono nel contratto del registro: uno in piu'
        sarebbe scartato in silenzio e l'host resterebbe «incompleto» senza capire perche'."""
        dalla_pagina = campi_inviati(_leggi("host.html"))["/api/host/dati_fiscali"]
        self.assertGreaterEqual(len(dalla_pagina), 6)
        ignorati = sorted(dalla_pagina - set(RegistroHost.CAMPI_FISCALI))
        self.assertEqual(ignorati, [],
                         "campi fiscali inviati dalla pagina e NON scritti dal registro: "
                         "%s" % ignorati)

        hid, tk = self.host()
        st, esito = self.g("POST", "/api/host/dati_fiscali", {
            "codice_fiscale": "RSSMRA80A01H501U", "partita_iva": "12345678901",
            "indirizzo_fiscale": "Via Roma 1, Roma", "paese": "IT",
            "iban": "IT60X0542811101000000123456", "tipo_soggetto": "societa"}, tk)
        self.assertEqual((st, esito["salvato"], esito["mancanti"]), (200, True, []))
        st, det = self.g("GET", "/api/admin/verifiche/dettaglio", None, self.admin,
                         {"host_id": hid})
        self.assertEqual(st, 200, det)
        self.assertEqual(det["fiscale"]["paese"], "IT")
        self.assertEqual(det["tipo_soggetto"], "societa")
        self.assertTrue(det["fiscale"]["iban_maschera"].endswith("3456"))
        self.assertTrue(det["fiscale"]["cf_maschera"].endswith("501U"))
        self.assertEqual(det["fiscale"]["mancanti"], [])

    def test_registrazione_i_campi_facoltativi_non_evaporano(self):
        hid, _tk = self.host(email="anagrafica@pagine.it")
        st, det = self.g("GET", "/api/admin/verifiche/dettaglio", None, self.admin,
                         {"host_id": hid})
        self.assertEqual(st, 200, det)
        self.assertEqual(det["ragione_sociale"], "Immobiliare Prova SRL")
        self.assertEqual(det["email"], "anagrafica@pagine.it")

    def test_calendario_a_intervallo_scrive_unita_E_prezzo_di_ogni_giorno(self):
        _hid, tk = self.host()
        self.g("POST", "/api/host/pubblica", dict(self.CAMPI_ANNUNCIO), tk)
        oggi = datetime.date.today()
        da = (oggi + datetime.timedelta(days=10)).isoformat()
        a = (oggi + datetime.timedelta(days=13)).isoformat()
        st, esito = self.g("POST", "/api/host/disponibilita_range", {
            "alloggio_id": "casa-contratto", "da": da, "a": a,
            "unita_totali": 4, "prezzo_netto_cents": 7777}, tk)
        self.assertEqual((st, esito), (200, {"giorni_impostati": 3}))
        st, cal = self.g("GET", "/api/host/calendario", None, tk,
                         {"alloggio": "casa-contratto", "da": da, "a": a})
        self.assertEqual(st, 200, cal)
        self.assertEqual([g["giorno"] for g in cal["giorni"]],
                         [da, (oggi + datetime.timedelta(days=11)).isoformat(),
                          (oggi + datetime.timedelta(days=12)).isoformat()])
        for giorno in cal["giorni"]:
            self.assertEqual(giorno["unita_totali"], 4)
            self.assertEqual(giorno["prezzo_netto_cents"], 7777)

        # il modulo «un giorno solo» deve poter SOVRASCRIVERE l'intervallo
        st, _ = self.g("POST", "/api/host/disponibilita", {
            "alloggio_id": "casa-contratto", "giorno": da,
            "unita_totali": 1, "prezzo_netto_cents": 9999}, tk)
        self.assertEqual(st, 200)
        st, cal2 = self.g("GET", "/api/host/calendario", None, tk,
                          {"alloggio": "casa-contratto", "da": da, "a": a})
        self.assertEqual(cal2["giorni"][0]["unita_totali"], 1)
        self.assertEqual(cal2["giorni"][0]["prezzo_netto_cents"], 9999)
        self.assertEqual(cal2["giorni"][1]["prezzo_netto_cents"], 7777,
                         "il giorno singolo ha travolto anche gli altri")

    def test_il_tasto_sospendi_toglie_davvero_l_annuncio_dalla_vetrina(self):
        _hid, tk = self.host()
        self.g("POST", "/api/host/pubblica", dict(self.CAMPI_ANNUNCIO), tk)
        st, cat = self.g("GET", "/api/catalogo")
        self.assertEqual((st, cat["totale"]), (200, 1))
        st, esito = self.g("POST", "/api/host/stato",
                           {"slug": "casa-contratto", "stato": "sospeso"}, tk)
        self.assertEqual((st, esito), (200, {"stato": "sospeso"}))
        st, cat = self.g("GET", "/api/catalogo")
        self.assertEqual((st, cat["totale"]), (200, 0),
                         "sospeso ma ancora in vetrina: il campo 'stato' e' ignorato")

    def test_split_preview_usa_sia_il_totale_sia_il_numero_di_persone(self):
        st, r = self.g("POST", "/api/split/preview", {"totale_cents": 10000, "n": 3})
        self.assertEqual(st, 200, r)
        self.assertEqual(r["quote"], [3334, 3333, 3333])
        self.assertEqual(sum(r["quote"]), 10000)
        st, r4 = self.g("POST", "/api/split/preview", {"totale_cents": 10000, "n": 4})
        self.assertEqual(r4["quote"], [2500, 2500, 2500, 2500])
        self.assertNotEqual(r4["quote"], r["quote"], "il campo 'n' non sposta nulla")

    def test_prezzo_suggerito_ogni_parametro_del_modulo_sposta_il_prezzo(self):
        """Quattro caselle nel pannello host: se una fosse ignorata, l'host regolerebbe
        una manopola scollegata."""
        _hid, tk = self.host()
        base = {"prezzo_base_cents": "10000", "occupazione_bps": "5000",
                "data": "2026-08-15", "giorni": "30"}

        def prezzo(**cambia):
            q = dict(base)
            q.update(cambia)
            st, r = self.g("GET", "/api/host/prezzo_suggerito", None, tk, q)
            self.assertEqual(st, 200, r)
            self.assertIsInstance(r["prezzo_cents"], int)
            return r["prezzo_cents"]

        riferimento = prezzo()
        self.assertNotEqual(prezzo(prezzo_base_cents="20000"), riferimento)
        self.assertNotEqual(prezzo(occupazione_bps="9500"), riferimento)
        self.assertNotEqual(prezzo(data="2026-01-15"), riferimento)
        self.assertNotEqual(prezzo(giorni="2"), riferimento)

    def test_trasparenza_usa_prezzo_e_ota_scelti_dalla_pagina(self):
        st, r = self.g("GET", "/api/trasparenza", None, None,
                       {"prezzo_cents": "100000", "ota": "booking"})
        self.assertEqual(st, 200, r)
        self.assertEqual(r["prezzo_riferimento_cents"], 100000)
        self.assertEqual(r["scenario_ota"]["commissione_cents"], 18000)
        self.assertEqual(r["scenario_nostro"]["commissione_cents"], 10000)
        st, r2 = self.g("GET", "/api/trasparenza", None, None,
                        {"prezzo_cents": "200000", "ota": "booking"})
        self.assertEqual(r2["prezzo_riferimento_cents"], 200000)
        self.assertEqual(r2["scenario_ota"]["commissione_cents"], 36000)

    def test_kill_switch_del_bunker_usa_attivo_E_motivo(self):
        """Il tasto rosso del bunker: `attivo` congela i soldi, `motivo` resta agli atti.
        Se `motivo` fosse ignorato, dopo un'emergenza nessuno saprebbe PERCHE'."""
        bk = self.bunker()
        st, prima = self.g("GET", "/api/bunker/blocco_globale", None, bk)
        self.assertEqual((st, prima["attivo"]), (200, False))
        st, acceso = self.g("POST", "/api/bunker/blocco_globale",
                            {"attivo": True, "motivo": "sospetto frode 42"}, bk)
        self.assertEqual(st, 200, acceso)
        self.assertEqual((acceso["attivo"], acceso["impostato"]), (True, True))
        self.assertEqual(acceso["dettaglio"]["motivo"], "sospetto frode 42")
        self.assertEqual(acceso["dettaglio"]["chi"], "super-admin")
        # effetto VERO: i soldi si fermano
        st, corpo = self.g("POST", "/api/concierge/book", {"quote_token": "qualsiasi"})
        self.assertEqual((st, corpo), (503, {"errore": "transazioni_sospese"}))
        st, spento = self.g("POST", "/api/bunker/blocco_globale",
                            {"attivo": False, "motivo": "cessato allarme"}, bk)
        self.assertEqual((st, spento["attivo"]), (200, False))
        st, _ = self.g("POST", "/api/concierge/book", {"quote_token": "qualsiasi"})
        self.assertNotEqual(st, 503, "il freeze non si spegne piu'")

    def test_kill_switch_senza_file_non_sporca_la_cartella(self):
        """Configurazione «solo-env» (nessun file-flag): l'interruttore a caldo non e'
        disponibile e deve dirlo restituendo False — SENZA lasciare rifiuti sul disco.
        VISTO ROSSO: senza la guardia, `imposta` creava un file `.tmp` nella cartella di
        lavoro del processo a ogni pressione del tasto."""
        from fase191_blocco_globale import crea_blocco_globale
        cartella = tempfile.mkdtemp(prefix="bg_vuoto_")
        self.addCleanup(shutil.rmtree, cartella, True)
        vecchia = os.getcwd()
        os.chdir(cartella)
        try:
            bg = crea_blocco_globale("")
            self.assertIs(bg.imposta(True, motivo="prova", chi="super-admin"), False)
            self.assertIs(bg.attivo(), False)
            self.assertEqual(sorted(os.listdir(".")), [],
                             "l'interruttore ha lasciato dei file nella cartella di "
                             "lavoro: %s" % sorted(os.listdir(".")))
        finally:
            os.chdir(vecchia)


# ══════════════════════════════════════════════════════════════════════════════════
# 3. NESSUN FILTRO IGNORATO — le caselle della ricerca e dei pannelli
# ══════════════════════════════════════════════════════════════════════════════════
class TestNessunFiltroIgnorato(_BasePagine):

    def setUp(self):
        super().setUp()
        _hid, self.tk = self.host()
        self.hid = _hid
        comune = {"citta": "Roma", "paese": "IT", "cin": "IT058091C2X5V0ABCD",
                  "immagini": [], "titolo": "Prova"}
        st, _ = self.g("POST", "/api/host/pubblica", dict(
            comune, slug="a-economico", prezzo_notte_cents=5000, capacita=2,
            servizi=["wifi"], politica_cancellazione="flessibile"), self.tk)
        self.assertEqual(st, 201)
        st, _ = self.g("POST", "/api/host/pubblica", dict(
            comune, slug="b-lusso", prezzo_notte_cents=50000, capacita=8,
            servizi=["wifi", "piscina"], politica_cancellazione="non_rimborsabile",
            lat_micro=41902782, lon_micro=12496366), self.tk)
        self.assertEqual(st, 201)

    def cerca(self, **query):
        st, corpo = self.g("GET", "/api/catalogo", None, None,
                           {k: str(v) for k, v in query.items()})
        self.assertEqual(st, 200, corpo)
        return [a["slug"] for a in corpo["risultati"]]

    def test_il_modulo_di_ricerca_non_manda_filtri_sconosciuti(self):
        """I nomi delle caselle sono scritti in index.html: qui si prova che il server
        li conosce TUTTI (uno sconosciuto = filtro che l'ospite imposta e non fa nulla)."""
        pagina = _leggi("index.html")
        blocco = pagina[pagina.index("async function cerca()"):]
        blocco = blocco[:blocco.index("/api/catalogo?")]
        inviati = set(re.findall(r"params\.([a-z_]+)\s*=", blocco))
        inviati |= set(re.findall(r"^\s*([a-z_]+)\s*:", blocco, re.M))
        noti = {"citta", "check_in", "check_out", "lang", "prezzo_max_cents",
                "prezzo_min_cents", "capacita_min", "servizi", "solo_gratuita",
                "flex_giorni", "lat_micro", "lon_micro", "raggio_km", "ordine",
                "limit", "offset"}
        self.assertGreaterEqual(len(inviati), 8,
                                "solo %d filtri estratti: estrattore cieco" % len(inviati))
        self.assertEqual(sorted(inviati - noti), [],
                         "index.html manda filtri che il catalogo non conosce: %s"
                         % sorted(inviati - noti))

    def test_ogni_filtro_della_ricerca_filtra_davvero(self):
        self.assertEqual(sorted(self.cerca()), ["a-economico", "b-lusso"])
        self.assertEqual(self.cerca(prezzo_max_cents=10000), ["a-economico"])
        self.assertEqual(self.cerca(prezzo_min_cents=10000), ["b-lusso"])
        self.assertEqual(self.cerca(capacita_min=5), ["b-lusso"])
        self.assertEqual(self.cerca(servizi="piscina"), ["b-lusso"])
        self.assertEqual(self.cerca(solo_gratuita=1), ["a-economico"])
        self.assertEqual(self.cerca(citta="Milano"), [])
        self.assertEqual(self.cerca(ordine="prezzo_asc"), ["a-economico", "b-lusso"])
        self.assertEqual(self.cerca(ordine="prezzo_desc"), ["b-lusso", "a-economico"])
        self.assertEqual(len(self.cerca(limit=1)), 1)

    def test_vicino_a_me_usa_posizione_e_raggio(self):
        """La casella «vicino a me» manda lat/lon in microgradi + raggio km."""
        vicino = self.cerca(lat_micro=41902782, lon_micro=12496366, raggio_km=5)
        self.assertEqual(vicino, ["b-lusso"], "solo l'annuncio con coordinate e' vicino")
        lontano = self.cerca(lat_micro=48856614, lon_micro=2352222, raggio_km=5)
        self.assertEqual(lontano, [], "da Parigi non si vede Roma a 5 km")

    def test_la_mappa_espone_solo_i_pin_con_coordinate(self):
        st, geo = self.g("GET", "/api/mappa", None, None, {"capacita_min": "5"})
        self.assertEqual(st, 200, geo)
        self.assertEqual(geo["type"], "FeatureCollection")
        self.assertEqual([f["properties"]["slug"] for f in geo["features"]], ["b-lusso"])
        punto = geo["features"][0]["geometry"]["coordinates"]
        self.assertAlmostEqual(punto[0], 12.496366, places=6)
        self.assertAlmostEqual(punto[1], 41.902782, places=6)

    def test_i_filtri_del_field_admin_filtrano_davvero(self):
        def elenco(**query):
            st, r = self.g("GET", "/api/admin/alloggi", None, self.admin,
                           {k: str(v) for k, v in query.items()})
            self.assertEqual(st, 200, r)
            return r

        self.assertEqual(elenco()["totale"], 2)
        self.assertEqual(elenco(host_id=self.hid)["totale"], 2)
        self.assertEqual(elenco(host_id="h_inesistente")["totale"], 0)
        self.assertEqual(elenco(stato="pubblicato")["totale"], 2)
        self.assertEqual(elenco(stato="sospeso")["totale"], 0)
        una = elenco(limit=1, page=1)
        self.assertEqual((una["limit"], len(una["alloggi"]), una["pagine"]), (1, 1, 2))
        due = elenco(limit=1, page=2)
        self.assertNotEqual(due["alloggi"][0]["slug"], una["alloggi"][0]["slug"],
                            "la paginazione non pagina: 'page' e' ignorato")

    def test_la_barra_di_ricerca_admin_usa_q_e_page(self):
        st, r = self.g("GET", "/api/admin/search", None, self.admin, {"q": "lusso"})
        self.assertEqual(st, 200, r)
        self.assertEqual([a["slug"] for a in r["annunci"]], ["b-lusso"])
        st, vuoto = self.g("GET", "/api/admin/search", None, self.admin,
                           {"q": "zzzzinesistente"})
        self.assertEqual(vuoto["totale"], 0)
        st, corto = self.g("GET", "/api/admin/search", None, self.admin, {"q": "z"})
        self.assertEqual((st, corto["errore"]), (422, "termine_troppo_corto"))

    def test_le_prenotazioni_dell_host_rispettano_vista_page_e_limit(self):
        for vista in ("attive", "archivio"):
            st, r = self.g("GET", "/api/host/prenotazioni", None, self.tk,
                           {"vista": vista})
            self.assertEqual(st, 200, r)
            self.assertEqual(r["vista"], vista)
        st, r = self.g("GET", "/api/host/prenotazioni", None, self.tk,
                       {"vista": "inventata", "limit": "3", "page": "2"})
        self.assertEqual(r["vista"], "attive", "vista ostile -> default garbato")
        self.assertEqual((r["limit"], r["page"]), (3, 2))


# ══════════════════════════════════════════════════════════════════════════════════
# 4. NESSUN TASTO MORTO
# ══════════════════════════════════════════════════════════════════════════════════
class TestNessunTastoMorto(unittest.TestCase):

    def test_ogni_bottone_e_cablato_a_qualcosa(self):
        """Un <button> vive se: ha `onclick` inline, e' `type=submit` dentro un modulo,
        ha un id a cui il JS assegna `.onclick`, oppure porta un `data-*`/`class` che il
        JS aggancia con querySelectorAll (righe create al volo)."""
        morti = []
        for pagina in PAGINE:
            if pagina.endswith(".js"):
                continue
            s = _leggi(pagina)
            # ATTENZIONE (guardia vista CIECA e poi corretta): cercare il nome dell'id
            # nel sorgente COMPLETO era inutile — l'attributo `id="btnX"` del bottone
            # stesso faceva da testimone di se' stesso, e un tasto mai cablato passava.
            # Qui gli attributi `id=...` si tolgono PRIMA: resta solo chi lo NOMINA.
            senza_id = re.sub(r"""\bid\s*=\s*(["'])[^"']*\1""", "", s)
            for attributi in bottoni(s):
                if re.search(r"\bonclick\s*=", attributi, re.I):
                    continue
                if re.search(r"""type\s*=\s*["']submit["']""", attributi, re.I):
                    continue
                mid = re.search(r"""\bid\s*=\s*["']([^"']+)["']""", attributi)
                if mid:
                    eid = mid.group(1)
                    if re.search(r"""(?:getElementById|\$)\(\s*['"]%s['"]\s*\)\s*\.onclick"""
                                 % re.escape(eid), s):
                        continue
                    if ("'%s'" % eid) in senza_id or ('"%s"' % eid) in senza_id:
                        continue                # cablato in lista (es. scudoTasti([...]))
                    morti.append("%s: <button id=%s> non riceve mai un onclick"
                                 % (pagina, eid))
                    continue
                agganci = re.findall(r"""\bdata-([a-z0-9-]+)\s*=""", attributi)
                classi = re.findall(r"""class\s*=\s*["']([^"']+)["']""", attributi)
                agganciato = any(("data-%s" % d) in s or (".dataset." in s and d in s)
                                 for d in agganci)
                if not agganciato:
                    agganciato = any(("." + c) in s
                                     for gruppo in classi for c in gruppo.split())
                if not agganciato:
                    morti.append("%s: <button%s> non ha ne' id, ne' onclick, ne' un "
                                 "aggancio (data-*/class) usato dal JS"
                                 % (pagina, attributi[:70]))
        self.assertEqual(morti, [], "TASTI MORTI (l'utente preme e non succede "
                                    "nulla): %s" % morti)

    def test_ogni_id_cercato_dal_js_esiste_nella_pagina(self):
        """`getElementById('x')` su un id inesistente ritorna null: la riga dopo esplode
        e il resto della pagina smette di funzionare (tasti morti a valanga)."""
        for pagina in PAGINE:
            if pagina.endswith(".js"):
                continue
            with self.subTest(pagina=pagina):
                s = _leggi(pagina)
                usati, dichiarati = id_usati(s), id_dichiarati(s)
                self.assertGreater(len(dichiarati), 0)
                mancanti = sorted(usati - dichiarati)
                self.assertEqual(mancanti, [],
                                 "%s: il JS cerca id che non esistono -> null e pagina "
                                 "morta: %s" % (pagina, mancanti))

    def test_i_moduli_hanno_un_gestore_di_invio(self):
        """Un <form> senza `onsubmit` (e senza action) ricarica la pagina e perde i dati."""
        for pagina in PAGINE:
            if pagina.endswith(".js"):
                continue
            s = _leggi(pagina)
            for m in re.finditer(r"<form\b([^>]*)>", s, re.I):
                attributi = m.group(1)
                with self.subTest(pagina=pagina, form=attributi[:60]):
                    mid = re.search(r"""\bid\s*=\s*["']([^"']+)["']""", attributi)
                    cablato = ("onsubmit" in attributi.lower()
                               or re.search(r"\baction\s*=", attributi, re.I) is not None)
                    if not cablato and mid:
                        cablato = re.search(
                            r"""(?:getElementById|\$)\(\s*['"]%s['"]\s*\)\s*\.onsubmit"""
                            % re.escape(mid.group(1)), s) is not None
                    self.assertTrue(cablato,
                                    "%s: <form%s> non ha un gestore di invio: premere "
                                    "Invio ricarica la pagina e perde i dati"
                                    % (pagina, attributi[:60]))


# ══════════════════════════════════════════════════════════════════════════════════
# 5. NESSUN MESSAGGIO SENZA TRADUZIONE
# ══════════════════════════════════════════════════════════════════════════════════
LINGUE_PAGINA = ("it", "en", "es", "fr", "de", "pt", "ja", "zh")

# I codici che l'OSPITE puo' davvero leggere sulla pagina di prenotazione: escono da
# `/api/concierge/book` (campo `errore` oppure `motivo` del rifiuto d'inventario), da
# `/api/split/preview` e dal modulo lista-d'attesa. Se non sono nel dizionario, in
# faccia all'utente finisce il codice tecnico.
CODICI_OSPITE = ("pieno", "chiuso", "min_notti", "giorno_non_caricato",
                 "quote_scaduta", "quote_non_valida", "alloggio_non_disponibile",
                 "transazioni_sospese", "credito_gia_usato", "service_unavailable",
                 "parametri_non_validi", "domanda_non_attiva")

# DEBITO DICHIARATO (fotografia 2026-07-28): quante chiavi di ogni pagina non sono
# ancora tradotte e ricadono sull'inglese. NON e' un permesso: e' un CRICCHETTO — puo'
# solo scendere. Se qualcuno aggiunge testo non tradotto, il numero sale e il test si
# accende. Le pagine qui sotto hanno una catena di ripiego dichiarata, quindi il debito
# vale «in inglese», MAI «chiave nuda in faccia».
DEBITO_NON_TRADOTTO = {"host.html": 148, "admin.html": 91}


class TestMessaggiInOttoLingue(unittest.TestCase):

    def test_bunker_ogni_chiave_in_tutte_e_8_le_lingue(self):
        """bunker.html legge il dizionario con `T.chiave`: una chiave mancante non
        ripiega su niente — stampa «undefined» in faccia al super-admin."""
        s = _leggi("bunker.html")
        lingue = dizionario_tr(s)
        self.assertEqual(sorted(lingue), sorted(LINGUE_PAGINA))
        usate = chiavi_i18n_usate(s)
        self.assertGreaterEqual(len(usate), 150,
                                "solo %d chiavi estratte da bunker.html: estrattore "
                                "cieco" % len(usate))
        for lingua in sorted(lingue):
            mancanti = sorted(usate - lingue[lingua])
            self.assertEqual(mancanti, [],
                             "bunker.html/%s: %d chiavi assenti -> la pagina stampa "
                             "'undefined': %s" % (lingua, len(mancanti), mancanti[:10]))

    def test_nessuna_pagina_mostra_mai_una_chiave_nuda(self):
        """Invariante forte: ogni chiave chiesta dalla pagina si RISOLVE. Le pagine con
        catena di ripiego risolvono sull'inglese; quindi la lingua 'en' deve essere
        COMPLETA, altrimenti l'utente legge la chiave tecnica (`err_key`)."""
        for pagina in ("host.html", "admin.html", "partner.html", "diventa-host.html",
                       "commissioni.html"):
            with self.subTest(pagina=pagina):
                s = _leggi(pagina)
                lingue = dizionario_tr(s)
                self.assertIn("en", lingue, "%s non ha il dizionario inglese" % pagina)
                usate = chiavi_i18n_usate(s)
                self.assertGreater(len(usate), 15)
                nude = sorted(usate - lingue["en"])
                self.assertEqual(nude, [],
                                 "%s: chiavi che nessuna lingua sa risolvere -> l'utente "
                                 "legge il nome tecnico: %s" % (pagina, nude))

    def test_host_html_dichiara_la_catena_di_ripiego(self):
        """host.html ha 6 lingue incomplete: senza `_fallback` quelle chiavi uscirebbero
        NUDE. La catena e' la sola cosa che trasforma un debito in un ripiego onesto."""
        s = _leggi("host.html")
        self.assertRegex(s, r"_fallback\s*=\s*\{\s*['\"]\*['\"]\s*:\s*['\"]en['\"]\s*\}",
                         "host.html non dichiara piu' il ripiego su 'en'")

    def test_il_debito_di_traduzione_non_cresce(self):
        """Cricchetto: il numero di chiavi non tradotte puo' solo SCENDERE."""
        for pagina, tetto in sorted(DEBITO_NON_TRADOTTO.items()):
            lingue = dizionario_tr(_leggi(pagina))
            tutte = set().union(*lingue.values())
            for lingua in sorted(lingue):
                if lingua in ("it", "en"):
                    continue
                mancanti = len(tutte - lingue[lingua])
                with self.subTest(pagina=pagina, lingua=lingua):
                    self.assertLessEqual(
                        mancanti, tetto,
                        "%s/%s: %d chiavi non tradotte (tetto dichiarato %d): il debito "
                        "e' cresciuto" % (pagina, lingua, mancanti, tetto))

    def test_index_html_chiede_solo_chiavi_che_il_motore_conosce(self):
        """index.html non ha un dizionario proprio: prende le frasi da /api/i18n. Una
        chiave che il motore non ha verrebbe stampata nuda in vetrina."""
        s = _leggi("index.html")
        usate = set(re.findall(r"""\bt\(\s*['"]([^'"]+)['"]\s*\)""", s))
        self.assertGreaterEqual(len(usate), 40,
                                "solo %d chiavi estratte da index.html" % len(usate))
        for lingua in LINGUE_SUPPORTATE:
            ui = _dizionario_i18n(lingua).get("ui", {})
            mancanti = sorted(k for k in usate if k not in ui)
            with self.subTest(lingua=lingua):
                self.assertEqual(mancanti, [],
                                 "la vetrina chiede chiavi che /api/i18n?lang=%s non ha: "
                                 "%s" % (lingua, mancanti))

    def test_i_codici_che_l_ospite_puo_vedere_sono_tradotti_in_8_lingue(self):
        """VISTO ROSSO: senza queste voci l'ospite leggeva `min_notti` o `pieno`."""
        app = _leggi("app.js")
        blocco = re.search(r"BV\.ERR_AUTH\s*=\s*\{.*?\n\s*\};", app, re.S)
        self.assertIsNotNone(blocco, "BV.ERR_AUTH non trovato in app.js")
        dizionario = blocco.group(0)
        for codice in CODICI_OSPITE:
            with self.subTest(codice=codice):
                n = len(re.findall(r"(?<![A-Za-z_])%s:" % re.escape(codice), dizionario))
                self.assertEqual(n, len(LINGUE_PAGINA),
                                 "'%s' spiegato in %d lingue su 8: nelle altre l'ospite "
                                 "legge il codice tecnico" % (codice, n))

    def test_le_frasi_dei_codici_ospite_non_sono_il_codice_stesso(self):
        """Anti-finto-verde: `pieno:'pieno'` passerebbe il conteggio e non spiega nulla."""
        app = _leggi("app.js")
        dizionario = re.search(r"BV\.ERR_AUTH\s*=\s*\{.*?\n\s*\};", app, re.S).group(0)
        for codice in CODICI_OSPITE:
            for m in re.finditer(r"(?<![A-Za-z_])%s:\s*(['\"])(.*?)(?<!\\)\1"
                                 % re.escape(codice), dizionario):
                frase = m.group(2)
                self.assertNotEqual(frase, codice)
                self.assertGreater(len(frase), 12,
                                   "%s: frase troppo corta %r" % (codice, frase))
                self.assertNotIn("_", frase,
                                 "%s: la frase sembra un codice tecnico (%r)"
                                 % (codice, frase))

    def test_il_motivo_del_rifiuto_passa_dal_dizionario(self):
        """VISTO ROSSO: index.html stampava `r.motivo` GREZZO (l'ospite leggeva 'pieno').
        Ora anche il motivo passa da fraseErrore, come l'errore."""
        s = _leggi("index.html")
        self.assertNotRegex(s, r"\$\{\s*esc\(\s*r\.motivo\s*\|\|",
                            "index.html stampa ancora r.motivo senza dizionario")
        self.assertIn("fraseErrore(r.motivo", s,
                      "il motivo del rifiuto non passa dal dizionario")

    def test_il_dizionario_degli_errori_copre_le_8_lingue_del_motore(self):
        app = _leggi("app.js")
        for lingua in LINGUE_PAGINA:
            self.assertRegex(app, r"(?<![A-Za-z_])%s:\{" % lingua,
                             "app.js non ha la lingua %s" % lingua)
        self.assertEqual(sorted(LINGUE_PAGINA), sorted(LINGUE_SUPPORTATE),
                         "le lingue delle pagine non sono quelle del motore")


# ══════════════════════════════════════════════════════════════════════════════════
# 6. IL SERVER DICE LE STESSE COSE CHE LE PAGINE ASPETTANO
# ══════════════════════════════════════════════════════════════════════════════════
class TestFormaDelleRisposte(_BasePagine):
    """Le pagine leggono chiavi PRECISE dalle risposte. Se il server ne cambia il nome,
    la schermata resta muta senza nessun errore: qui si fissano quelle che contano."""

    def test_il_catalogo_espone_le_chiavi_che_la_vetrina_disegna(self):
        _hid, tk = self.host()
        st, _ = self.g("POST", "/api/host/pubblica", {
            "slug": "scheda-vetrina", "titolo": "Scheda", "citta": "Roma", "paese": "IT",
            "cin": "IT058091C2X5V0ABCD", "prezzo_notte_cents": 9900, "capacita": 3,
            "servizi": ["wifi"], "immagini": []}, tk)
        self.assertEqual(st, 201)
        st, cat = self.g("GET", "/api/catalogo", None, None, {"citta": "Roma"})
        self.assertEqual(st, 200, cat)
        scheda = cat["risultati"][0]
        for chiave in ("slug", "titolo", "citta", "paese", "prezzo_notte_cents",
                       "valuta", "recensioni", "politica_cancellazione"):
            self.assertIn(chiave, scheda,
                          "la vetrina disegna '%s': senza, la card esce vuota" % chiave)
        self.assertIsInstance(scheda["prezzo_notte_cents"], int)
        self.assertEqual(cat["totale"], 1)

    def test_il_login_host_risponde_con_le_chiavi_che_il_pannello_legge(self):
        self.host(email="login@pagine.it")
        st, ok = self.g("POST", "/api/host/login",
                        {"email": "login@pagine.it", "password": "password1"})
        self.assertEqual(st, 200, ok)
        self.assertIsInstance(ok["token"], str)
        self.assertIsInstance(ok["host_id"], str)
        st, ko = self.g("POST", "/api/host/login",
                        {"email": "login@pagine.it", "password": "sbagliata9"})
        self.assertEqual((st, ko["errore"]), (401, "credenziali_non_valide"))
        self.assertNotIn("token", ko)

    def test_le_rotte_admin_chiamate_dalla_pagina_chiedono_la_chiave(self):
        """Ogni rotta admin/bunker nominata da admin.html e bunker.html deve rifiutare
        una chiamata SENZA credenziali: una sola porta aperta e' un buco."""
        esatte, _ = tabella_rotte_router()
        rotte = set()
        for pagina in ("admin.html", "bunker.html"):
            rotte |= {r for r in rotte_di(_leggi(pagina))
                      if r.startswith(("/api/admin/", "/api/bunker/")) and r in esatte}
        rotte.discard("/api/bunker/login")     # e' la porta stessa: la prova e' altrove
        rotte.discard("/api/admin/login")
        # I logout sono IDEMPOTENTI di proposito (revocare una sessione gia' morta e'
        # sempre lecito e non svela nulla): rispondono 200 anche senza credenziali.
        rotte.discard("/api/bunker/logout")
        self.assertGreaterEqual(len(rotte), 15, "solo %d rotte protette" % len(rotte))
        aperte = []
        for rotta in sorted(rotte):
            for metodo in ("GET", "POST"):
                st, _ = self.g(metodo, rotta, None, {})
                if st in (200, 201):
                    aperte.append("%s %s" % (metodo, rotta))
        self.assertEqual(aperte, [],
                         "rotte di pannello servite SENZA credenziali: %s" % aperte)


if __name__ == "__main__":
    unittest.main(verbosity=2)
