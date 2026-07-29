# -*- coding: utf-8 -*-
"""COLLAUDO PROFONDO — LE QUESTIONI RIMASTE APERTE (+ l'instabilità).

Cinque compartimenti, uno per questione aperta. Ogni guardia qui dentro è stata VISTA ROSSA
rompendo di proposito il codice che sorveglia (elenco in fondo al file, sezione «VISTO ROSSO»).

1) ANTI-FLAKY — «l'orologio del test contro l'orologio del server».
   Uno schema che fa cadere una suite verde a cavallo della mezzanotte/di Capodanno UTC:
   il SERVER calcola un giorno/anno con `utcnow()`, il TEST lo ricalcola un istante dopo con
   `utcnow()` e pretende che siano UGUALI. Il 99,99% delle volte lo sono. Poi, una notte, no.
   `SchemaOrologio` è un rilevatore AST che trova questo schema in TUTTI i test e lo divide
   in DUE classi, perché il rischio è diversissimo:
     · **DUE OROLOGI** — il valore NON è mai stato spedito al server: il server l'ha calcolato
       col SUO orologio, il test lo ricalcola col PROPRIO. Salta a MEZZANOTTE, ogni notte.
       È il difetto: zero tollerati oltre al debito congelato in `DEBITO_OROLOGIO`.
     · **ECO** — il valore è stato spedito come parametro e il server lo rimanda indietro:
       un orologio solo, nessun salto notturno. Si segnala ma non si vieta.

   ⚠️ RIGHE DA CORREGGERE (file di un'altra squadra: NON toccate qui, per non fare conflitto).
   Numeri di riga al 2026-07-28; la guardia li ristampa aggiornati a ogni esecuzione.

   A) DUE OROLOGI — salta ogni notte, priorità:
     · test_happy_admin.py:802
       `self.assertEqual(out["giorno"], datetime.datetime.utcnow().strftime("%Y-%m-%d"))`
       Il `giorno` lo scrive `fase184.marca_i_registri` con l'orologio del SERVER.
       CORREZIONE: finestra di tolleranza — calcolare ieri/oggi PRIMA della chiamata e
       `self.assertIn(out["giorno"], {ieri, oggi})`; oppure confrontare con
       `el["marche"][0]["giorno"]` (stessa fonte: nessun secondo orologio).
     · test_bunker_scaglioni_prove.py:172
       `prossimo_scatto_il` (calcolato dal server) vs `date.today() + timedelta(al_prossimo)`.
       CORREZIONE: stessa finestra (oggi/domani) sul confine di mezzanotte LOCALE.

   B) ECO col rischio di CAPODANNO — una volta l'anno, ma vera:
     · test_happy_admin.py:739  `anno = datetime.datetime.utcnow().year`, usato come query a
       742/756. L'eco `out["anno"] == anno` è stabile, MA con quell'anno si selezionano i
       dati: se il setUp registra la prenotazione il 31/12 e la riga 739 gira il 1/1, le
       asserzioni sui DATI (`out["totale"] == 1`, `h["ricavi_cents"]`) cadono.
       CORREZIONE: ricavare l'anno dai DATI e non dall'orologio — p.es. dal `ts` del
       movimento appena scritto nel giornale (è ciò che fa `_anno_dei_dati` qui sotto).

2) LE 4 ROTTE `/api/bunker/*` INTERCETTATE DAL LIVELLO HTTP (export_contabile, export_legale,
   dac7_report, marca.tsr): non passano dal router, le serve l'`Handler` in streaming diretto
   sul socket. Il router non le vede: vanno provate col SERVER VERO (thread + http.client).

3) CORS: `Access-Control-Allow-Headers` dichiarava solo `Content-Type, X-Host-Key` mentre
   l'autenticazione vera usa anche X-Host-Token, X-Admin-Key, X-Admin-Op, X-Bunker-Session.

4) KILL-SWITCH GLOBALE (`POST /api/bunker/blocco_globale`): accende/spegne davvero il freeze?
   I soldi rispondono 503 e il sito resta navigabile? Lo spegnimento riapre tutto?

5) ASIMMETRIA DI RANGE sui due campi data `da`/`a` fra LETTURA e SCRITTURA del calendario.
"""
import ast
import datetime
import glob
import hashlib
import hmac
import http.client
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest

import fase85_pagamenti_stripe as _stripe
import fase184_marca_temporale as _marca
import fase83_server
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

RADICE = os.path.dirname(os.path.abspath(__file__))


# ═════════════════════════════════════════════════════════════════════════════════
# 1) ANTI-FLAKY — rilevatore dello schema «orologio del test vs orologio del server»
# ═════════════════════════════════════════════════════════════════════════════════
_OROLOGI = {"utcnow", "now", "today", "time", "monotonic", "utcfromtimestamp"}
_UGUAGLIANZE = {"assertEqual", "assertEquals", "assertNotEqual", "assertTupleEqual",
                "assertListEqual", "assertDictEqual", "assertSetEqual"}


class SchemaOrologio:
    """Trova, con l'AST, le uguaglianze ESATTE fra un valore che ARRIVA dal server e un
    valore ricalcolato dal test leggendo l'orologio. È lo schema che salta a mezzanotte.

    Non è flaky (e quindi non si segnala):
      · confronto fra DUE valori entrambi letti dalla risposta (nessun secondo orologio);
      · `assertIn` / `assertGreaterEqual` / `assertAlmostEqual` (= c'è una tolleranza);
      · l'orologio usato come PARAMETRO d'ingresso e non come termine di paragone.
    """

    @staticmethod
    def _orologio(nodo):
        """Nome della funzione-orologio chiamata dentro `nodo` ('' se non ce n'è)."""
        for n in ast.walk(nodo):
            if isinstance(n, ast.Call):
                f = n.func
                nome = f.attr if isinstance(f, ast.Attribute) else (
                    f.id if isinstance(f, ast.Name) else "")
                if nome in _OROLOGI:
                    return nome
        return ""

    @staticmethod
    def _dalla_risposta(nodo):
        """L'espressione ha la forma di un valore letto dalla risposta: out["x"], d.get("y")."""
        for n in ast.walk(nodo):
            if isinstance(n, ast.Subscript):
                return True
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                    and n.func.attr == "get":
                return True
        return False

    @staticmethod
    def _e_assert(nodo):
        return (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr.startswith("assert"))

    @classmethod
    def _nomi_spediti(cls, fn):
        """Nomi che il test manda al SERVER (argomenti di una chiamata che non è un assert:
        `self.g(...)`, `self.rotta(..., query={"anno": str(anno)})`, ...).

        Serve a separare i due casi, che hanno rischi diversissimi:
          · ECO — il valore d'orologio è stato SPEDITO e il server lo rimanda indietro:
            un solo orologio, nessun salto a mezzanotte;
          · DUE OROLOGI — il server calcola col SUO orologio, il test ricalcola col PROPRIO:
            fra le due letture la mezzanotte può passare. Questo è il difetto.
        """
        dentro_assert = set()
        for n in ast.walk(fn):
            if cls._e_assert(n):
                for q in ast.walk(n):
                    dentro_assert.add(id(q))
        spediti = set()
        for n in ast.walk(fn):
            if not isinstance(n, ast.Call) or cls._e_assert(n) or id(n) in dentro_assert:
                continue
            for pezzo in list(n.args) + [k.value for k in n.keywords]:
                for q in ast.walk(pezzo):
                    if isinstance(q, ast.Name):
                        spediti.add(q.id)
        return spediti

    @classmethod
    def _sorgente(cls, testo, etichetta):
        try:
            albero = ast.parse(testo)
        except SyntaxError:
            return []
        righe = testo.splitlines()
        trovati = []
        for fn in ast.walk(albero):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # variabili del test che nascono da una lettura dell'orologio (a catena)
            derivate = {}
            for _giro in range(3):
                for n in ast.walk(fn):
                    if not isinstance(n, ast.Assign):
                        continue
                    nomi = {q.id for q in ast.walk(n.value) if isinstance(q, ast.Name)}
                    o = cls._orologio(n.value) or ",".join(
                        sorted({derivate[k] for k in (nomi & set(derivate))}))
                    if o:
                        for t in n.targets:
                            if isinstance(t, ast.Name):
                                derivate.setdefault(t.id, o)
            spediti = cls._nomi_spediti(fn)
            for n in ast.walk(fn):
                if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr in _UGUAGLIANZE and len(n.args) >= 2):
                    continue
                for x, y in ((n.args[0], n.args[1]), (n.args[1], n.args[0])):
                    if cls._dalla_risposta(x):
                        continue                    # il lato-orologio dev'essere PURO
                    nomi = {q.id for q in ast.walk(x) if isinstance(q, ast.Name)}
                    radici = nomi & set(derivate)
                    o = cls._orologio(x) or ",".join(sorted({derivate[k] for k in radici}))
                    if o and cls._dalla_risposta(y):
                        eco = bool(radici) and bool(radici & spediti)
                        testo_riga = (righe[n.lineno - 1].strip()
                                      if 0 < n.lineno <= len(righe) else "")
                        trovati.append({"file": etichetta, "riga": n.lineno,
                                        "funzione": fn.name, "orologio": o,
                                        "classe": "eco" if eco else "due_orologi",
                                        "codice": testo_riga})
                        break
        return trovati

    @classmethod
    def in_testo(cls, testo, etichetta="<memoria>"):
        return cls._sorgente(testo, etichetta)

    @classmethod
    def in_file(cls, percorso):
        with open(percorso, encoding="utf-8") as f:
            return cls._sorgente(f.read(), os.path.basename(percorso))

    @classmethod
    def in_cartella(cls, cartella):
        fuori = []
        for p in sorted(glob.glob(os.path.join(cartella, "test_*.py"))
                        + glob.glob(os.path.join(cartella, "collaudi", "*.py"))):
            fuori.extend(cls.in_file(p))
        return fuori

    @staticmethod
    def chiave(t):
        """Identità STABILE di un difetto: file + funzione + orologio. Non la riga (così la
        squadra proprietaria può muovere il codice senza far diventare rossa questa guardia)."""
        return (t["file"], t["funzione"], t["orologio"])

    @staticmethod
    def pericolosi(trovati):
        """Solo i DUE OROLOGI: quelli che possono saltare stanotte."""
        return [t for t in trovati if t["classe"] == "due_orologi"]

    @staticmethod
    def echi(trovati):
        """Valore d'orologio SPEDITO al server e riecheggiato: nessun salto di mezzanotte.
        Resta però il rischio ANNUALE se quel valore SELEZIONA i dati (vedi Capodanno)."""
        return [t for t in trovati if t["classe"] == "eco"]


# Debito NOTO al 2026-07-28, congelato: chiave -> quante uguaglianze in quella funzione.
# Solo la classe pericolosa (DUE OROLOGI). Questa tabella può solo RIMPICCIOLIRE.
# ✅ DEBITO SALDATO il 2026-07-29 dal coordinatore: i due confronti a due orologi sono stati
# corretti con una FINESTRA di tolleranza (prima/dopo la chiamata), e la correzione e' stata
# PROVATA riproducendo la mezzanotte DURANTE la chiamata (l'orologio del test avanza solo
# dalla seconda lettura): prima cadeva, ora regge.
# Da qui in poi vale il CRICCHETTO: il debito e' ZERO e puo' solo restare zero. Chiunque
# introduca un nuovo confronto a due orologi fa diventare ROSSA questa guardia, che gli dice
# file, riga e rimedio.
DEBITO_OROLOGIO = {}

# Campioni di controllo del rilevatore: (sorgente, classe attesa o None se non segnalabile)
_CAMPIONI = [
    # ── DUE OROLOGI: il difetto vero, quello che salta a mezzanotte ──────────────
    ("""
class T:
    def test_a(self):
        out = api()
        self.assertEqual(out["giorno"], datetime.datetime.utcnow().strftime("%Y-%m-%d"))
""", "due_orologi"),
    ("""
class T:
    def test_b(self):
        anno = datetime.datetime.utcnow().year
        out = api()
        self.assertEqual(out["anno"], anno)
""", "due_orologi"),
    ("""
class T:
    def test_c(self):
        atteso = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
        self.assertEqual(v["scatto_il"], atteso)
""", "due_orologi"),
    ("""
class T:
    def test_d(self):
        adesso = int(time.time())
        self.assertEqual(risposta.get("ts"), adesso)
""", "due_orologi"),
    # ── ECO: il valore è stato SPEDITO al server, che lo rimanda. Un orologio solo. ─
    ("""
class T:
    def test_eco_query(self):
        anno = datetime.datetime.utcnow().year
        out = self.rotta("GET", "/api/x", query={"anno": str(anno)})
        self.assertEqual(out["anno"], anno)
""", "eco"),
    ("""
class T:
    def test_eco_derivato(self):
        oggi = datetime.date.today()
        da = (oggi + datetime.timedelta(days=10)).isoformat()
        st, cal = self.g("GET", "/api/host/calendario", None, tk, {"da": da})
        self.assertEqual([g["giorno"] for g in cal["giorni"]], [da])
""", "eco"),
    # ── NEGATIVI: NON devono essere segnalati (o la guardia diventa un ornamento) ─
    ("""
class T:
    def test_e(self):
        anno = datetime.datetime.utcnow().year
        out = api(anno=anno)
        self.assertEqual(out["anno"], out["anno_richiesto"])
""", None),
    ("""
class T:
    def test_f(self):
        oggi = datetime.date.today().isoformat()
        ieri = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        self.assertIn(out["giorno"], (ieri, oggi))
""", None),
    ("""
class T:
    def test_g(self):
        a1 = aggrega(datetime.date.today().year).get(h1, {})
        a2 = aggrega(datetime.date.today().year).get(h2, {})
        self.assertEqual(int(a1["commissioni"]), int(a2["commissioni"]))
""", None),
    ("""
class T:
    def test_h(self):
        self.assertEqual(out["stato"], "pagato")
""", None),
    ("""
class T:
    def test_i(self):
        t0 = time.monotonic()
        fai_qualcosa()
        self.assertLess(time.monotonic() - t0, 2.0)
""", None),
]


class TestAntiFlakyOrologio(unittest.TestCase):
    """Questione 1: vietare lo schema che rende instabile una suite sana."""

    def test_il_rilevatore_distingue_i_due_orologi_dall_eco(self):
        """Prima di fidarsi della guardia: sa distinguere? 4 «due orologi», 2 «eco»,
        5 casi sani. La distinzione è il cuore: senza, o urla sempre o non urla mai."""
        for i, (sorgente, atteso) in enumerate(_CAMPIONI):
            trovati = SchemaOrologio.in_testo(sorgente, "campione_%d" % i)
            classi = [t["classe"] for t in trovati]
            self.assertEqual(classi, [atteso] if atteso else [],
                             "campione %d: attesa %r, trovati %r" % (i, atteso, trovati))
        # non basta «c'è»: il rilevatore nomina riga, funzione, orologio e codice
        t = SchemaOrologio.in_testo(_CAMPIONI[1][0], "campione_1")[0]
        self.assertEqual((t["funzione"], t["orologio"], t["riga"], t["classe"]),
                         ("test_b", "utcnow", 6, "due_orologi"))
        self.assertEqual(t["codice"], 'self.assertEqual(out["anno"], anno)')

    def test_nessun_nuovo_confronto_a_due_orologi(self):
        """Il debito pericoloso è quello dichiarato in testa al file: mai uno in più."""
        trovati = SchemaOrologio.pericolosi(SchemaOrologio.in_cartella(RADICE))
        conta = {}
        for t in trovati:
            conta[SchemaOrologio.chiave(t)] = conta.get(SchemaOrologio.chiave(t), 0) + 1
        nuovi = sorted(k for k in conta if k not in DEBITO_OROLOGIO)
        dettaglio = "\n".join(
            "    %(file)s:%(riga)d  %(funzione)s  [%(orologio)s]  %(codice)s" % t
            for t in trovati if SchemaOrologio.chiave(t) in set(nuovi))
        self.assertEqual(nuovi, [],
                         "NUOVO confronto a DUE OROLOGI (il server calcola col suo, il test "
                         "ricalcola col proprio): salta a mezzanotte UTC. Rimedi: una "
                         "FINESTRA di tolleranza (assertIn con ieri/oggi), oppure spedire "
                         "il valore al server e verificarne l'eco:\n" + dettaglio)
        for k, atteso in DEBITO_OROLOGIO.items():
            self.assertLessEqual(conta.get(k, 0), atteso,
                                 "il debito orologio è CRESCIUTO in %s" % (k,))

    def test_le_righe_esatte_da_correggere_sono_indicate(self):
        """La guardia non dice solo «c'è un problema»: dice DOVE, riga per riga.
        DEBITO SALDATO (2026-07-29): l'elenco degli aperti dev'essere VUOTO, e se un domani
        qualcuno riapre il debito questa guardia lo nomina file per file."""
        tutti = SchemaOrologio.in_cartella(RADICE)
        pericolosi = SchemaOrologio.pericolosi(tutti)
        aperti = [t for t in pericolosi if SchemaOrologio.chiave(t) in DEBITO_OROLOGIO]
        self.assertEqual(len(aperti), sum(DEBITO_OROLOGIO.values()), aperti)
        # ✅ ZERO confronti a due orologi in TUTTA la suite: il debito e' saldato e resta tale.
        residui = "\n".join("    %(file)s:%(riga)d  %(funzione)s  ->  %(codice)s" % t
                            for t in sorted(pericolosi, key=lambda x: (x["file"], x["riga"])))
        self.assertEqual(pericolosi, [],
                         "il debito orologio era ZERO: qualcuno ha reintrodotto un confronto "
                         "fra l'orologio del server e quello del test (salta a mezzanotte).\n"
                         "Rimedio: finestra di tolleranza (prima/dopo la chiamata) oppure eco "
                         "del valore spedito al server.\n" + residui)
        print("\n[aperte/1] DUE OROLOGI — debito SALDATO, elenco aperti:", file=sys.stderr)
        for t in sorted(aperti, key=lambda x: (x["file"], x["riga"])):
            print("    %(file)s:%(riga)d  %(funzione)s  ->  %(codice)s" % t, file=sys.stderr)
        print("[aperte/1] ECO — un orologio solo (rischio limitato al CAPODANNO, se quel "
              "valore seleziona i dati):", file=sys.stderr)
        for t in sorted(SchemaOrologio.echi(tutti), key=lambda x: (x["file"], x["riga"])):
            print("    %(file)s:%(riga)d  %(funzione)s  ->  %(codice)s" % t, file=sys.stderr)

    def test_la_guardia_boccia_una_violazione_nuova(self):
        """VISTO ROSSO della POLITICA (non solo del rilevatore): si mette un file nuovo
        col difetto in una cartella finta e si verifica che la stessa logica del test
        precedente produca un elenco NON vuoto (cioè fallirebbe)."""
        d = tempfile.mkdtemp(prefix="aperte_orologio_")
        try:
            with open(os.path.join(d, "test_intruso.py"), "w", encoding="utf-8") as f:
                f.write("import datetime\n"
                        "class T:\n"
                        "    def test_nuovo(self):\n"
                        "        self.assertEqual(out['giorno'],"
                        " datetime.datetime.utcnow().strftime('%Y-%m-%d'))\n")
            trovati = SchemaOrologio.pericolosi(SchemaOrologio.in_cartella(d))
            nuovi = sorted({SchemaOrologio.chiave(t) for t in trovati}
                           - set(DEBITO_OROLOGIO))
            self.assertEqual(nuovi, [("test_intruso.py", "test_nuovo", "utcnow")], trovati)
            self.assertEqual(trovati[0]["riga"], 4)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_questo_file_non_contiene_lo_schema_vietato(self):
        """Chi fa la regola la rispetta."""
        self.assertEqual(SchemaOrologio.in_file(os.path.abspath(__file__)), [])


# ═════════════════════════════════════════════════════════════════════════════════
# 2)+3) SERVER VERO: le 4 rotte intercettate dall'Handler + il preflight CORS
# ═════════════════════════════════════════════════════════════════════════════════
WH = "whsec_profondo_aperte"
PREZZO_NOTTE = 250000                     # 2.500,00 EUR x 2 notti = sopra soglia DAC7
TSR_FINTO = b"\x30\x82\x01\x0aTSR-FINTO-RFC3161\x00\xff"   # token binario, non vuoto
IP_BUNKER = "198.51.100.9"


def _porta_libera():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _stripe_checkout_finto(url, body, headers):
    import secrets
    return {"url": "https://stripe.finto/" + secrets.token_hex(4),
            "id": "cs_" + secrets.token_hex(8)}


def _marca_finta(impronta_sha256, *, url=None, timeout=12.0, trasporto=None):
    """Confine di rete della TSA RFC 3161: token BINARIO vero (è il file che si scarica)."""
    return {"ok": True, "token": TSR_FINTO, "tsa": "https://tsa.finta/tsr",
            "policy": "1.2.3.4.5", "seriale": "00AB", "gen_time": int(time.time()),
            "qualificata": True}


class TestRotteHTTPIntercettate(unittest.TestCase):
    """Questioni 2 e 3. Server VERO in un thread: streaming sul socket, header, CORS.

    Il router non vede queste 4 rotte: `do_GET` le intercetta PRIMA di `router.gestisci`
    e scrive direttamente sul socket. Provarle col router (come fa il resto della suite)
    NON prova nulla di ciò che l'utente riceve davvero: né gli header, né il binario,
    né la chiusura del flusso.
    """

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="aperte_http_")
        d = cls.dir
        cls._env0 = {k: os.environ.get(k) for k in
                     ("DATA_DIR", "MARCA_TEMPORALE", "BLOCCO_GLOBALE")}
        os.environ["DATA_DIR"] = d
        os.environ["MARCA_TEMPORALE"] = "1"
        os.environ.pop("BLOCCO_GLOBALE", None)
        cls._orig = (_stripe.ProviderStripe.__dict__["_fetch_reale"], _marca.chiedi_marca)
        _stripe.ProviderStripe._fetch_reale = staticmethod(_stripe_checkout_finto)
        _marca.chiedi_marca = _marca_finta

        cls.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"P" * 32, con_registrazione_host=True,
            db_catalogo=d + "/catalogo.db", db_inventario=d + "/inventario.db",
            db_registro_host=d + "/registro_host.db", db_accettazioni=d + "/accettazioni.db",
            db_pendenti=d + "/pendenti.db", db_payout=d + "/payout.db",
            db_finanza=d + "/finanza.db", db_marche=d + "/marche.db",
            db_tassa_comunale=d + "/tassa.db", db_garanzia=d + "/garanzia.db",
            commissione_bps=1000, psp_bps=300, stripe_webhook_secret=WH,
            bunker_password="SuperPw@1"))
        # niente chiave Stripe viva: nessun collegamento di rete parte da questo collaudo
        cls.sis.concierge._link = lambda dati: "https://pay/" + str(
            dati.get("riferimento", ""))
        # stato del mondo VERO (via router, stessi DB del server): host + annuncio +
        # prenotazione PAGATA -> il giornale ha righe da esportare, il DAC7 una riga vera.
        cls.rs = crea_router(cls.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        cls.host_id, cls.rif = cls._prepara_stato()

        cls.porta = _porta_libera()
        cls.thread = threading.Thread(
            target=fase83_server.servi,
            kwargs=dict(sistema=cls.sis, host="127.0.0.1", porta=cls.porta,
                        cartella_statica="deploy", host_key="hk", admin_key="ak",
                        base_url="https://bookinvip.com"),
            daemon=True)
        cls.thread.start()
        for _ in range(300):
            try:
                if cls._http("GET", "/robots.txt")[0] == 200:
                    break
            except Exception:
                pass
            time.sleep(0.03)
        else:                                                       # pragma: no cover
            raise AssertionError("il server vero non ha risposto")

        cls.sessione = cls._login_bunker()
        cls.BK = {"X-Admin-Key": "ak", "X-Bunker-Session": cls.sessione,
                  "X-Forwarded-For": IP_BUNKER}
        cls.marca_id = cls._marca_oggi()
        cls.anno_dati = cls._anno_dei_dati()

    @classmethod
    def tearDownClass(cls):
        (_stripe.ProviderStripe._fetch_reale, _marca.chiedi_marca) = cls._orig
        for k, v in cls._env0.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.dir, ignore_errors=True)

    # ── attrezzi ────────────────────────────────────────────────────────────────
    @classmethod
    def _http(cls, metodo, percorso, headers=None, corpo=None):
        """Ritorna (stato, header-minuscoli, corpo BYTE): il binario non si decodifica."""
        c = http.client.HTTPConnection("127.0.0.1", cls.porta, timeout=20)
        c.request(metodo, percorso, body=corpo, headers=headers or {})
        r = c.getresponse()
        dati = r.read()
        hd = {k.lower(): v for k, v in r.getheaders()}
        stato = r.status
        c.close()
        return stato, hd, dati

    @classmethod
    def _router(cls, metodo, percorso, corpo=None, headers=None, query=None):
        return cls.rs.gestisci(metodo, percorso, query or {},
                               json.dumps(corpo) if corpo is not None else None,
                               headers or {})

    @classmethod
    def _prepara_stato(cls):
        st, out = cls._router("POST", "/api/host/registrazione",
                              {"email": "host@aperte.invalid", "password": "password1",
                               "accetta_termini": True, "accetta_clausole": True,
                               "accetta_privacy": True, "doc_sha256": doc_sha256(),
                               "versione": CONTRATTO_HOST_VERSIONE})
        assert st == 201, out
        hid, HT = out["host_id"], {"X-Host-Token": out["token"]}
        base = datetime.date.today() + datetime.timedelta(days=30)
        g0, g2, g4, g10 = (base.isoformat(),
                           (base + datetime.timedelta(days=2)).isoformat(),
                           (base + datetime.timedelta(days=4)).isoformat(),
                           (base + datetime.timedelta(days=10)).isoformat())
        st, out = cls._router("POST", "/api/host/pubblica",
                              {"slug": "villa-aperte", "titolo": "Villa Aperte",
                               "citta": "Roma", "prezzo_notte_cents": PREZZO_NOTTE,
                               "capacita": 4}, HT)
        assert st == 201, out
        st, out = cls._router("POST", "/api/host/disponibilita_range",
                              {"alloggio_id": "villa-aperte", "da": g0, "a": g10,
                               "unita_totali": 1, "prezzo_netto_cents": PREZZO_NOTTE}, HT)
        assert st == 200, out
        st, out = cls._router("POST", "/api/host/dati_fiscali",
                              {"codice_fiscale": "RSSMRA80A01H501U",
                               "partita_iva": "12345678901",
                               "indirizzo_fiscale": "Via Roma 1, 00184 Roma", "paese": "IT",
                               "iban": "IT60X0542811101000000123456",
                               "tipo_soggetto": "privato",
                               "data_nascita": "1980-01-01"}, HT)
        assert (st, out["mancanti"]) == (200, []), out
        st, q = cls._router("POST", "/api/concierge/quote",
                            {"alloggio_id": "villa-aperte", "check_in": g2,
                             "check_out": g4, "party": 2})
        assert st == 200, q
        st, b = cls._router("POST", "/api/concierge/book",
                            {"quote_token": q["quote_token"],
                             "email": "ospite@aperte.invalid", "lang": "it"})
        assert st == 201, b
        rif = b["riferimento"]
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"id": "cs_" + rif[:10],
                                                  "metadata": {"riferimento": rif}}}})
        ts = str(int(time.time()))
        mac = hmac.new(WH.encode(), ("%s.%s" % (ts, payload)).encode(),
                       hashlib.sha256).hexdigest()
        st, out = cls.rs.gestisci("POST", "/api/payments/webhook", {}, payload,
                                  {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})
        assert st == 200, out
        assert (cls.sis.pagamenti_pendenti.info(rif) or {}).get("stato") == "pagato"
        return hid, rif

    @classmethod
    def _login_bunker(cls):
        st, _hd, corpo = cls._http(
            "POST", "/api/bunker/login",
            {"X-Admin-Key": "ak", "X-Forwarded-For": IP_BUNKER,
             "Content-Type": "application/json"},
            json.dumps({"codice": "SuperPw@1"}))
        assert st == 200, corpo
        return json.loads(corpo)["sessione"]

    @classmethod
    def _marca_oggi(cls):
        st, _hd, corpo = cls._http("POST", "/api/bunker/marca_ora", cls.BK, "{}")
        assert st == 200, corpo
        assert json.loads(corpo)["ok"] is True, corpo
        st, _hd, corpo = cls._http("GET", "/api/bunker/marche_temporali", cls.BK)
        assert st == 200, corpo
        return int(json.loads(corpo)["marche"][0]["id"])

    @classmethod
    def _anno_dei_dati(cls):
        """L'anno lo dicono i DATI (il ts scritto dal server), MAI l'orologio del test:
        è esattamente lo schema instabile della questione 1."""
        anni = {datetime.datetime.utcfromtimestamp(int(r["ts"])).year
                for r in cls.sis.finanza.stream_giornale()}
        assert len(anni) == 1, anni
        return anni.pop()

    def _senza_bunker(self):
        return {"X-Admin-Key": "ak", "X-Forwarded-For": IP_BUNKER}

    # ── 2a) estratto contabile: streaming CSV certificato ───────────────────────
    def test_export_contabile_streaming_reale(self):
        st, hd, corpo = self._http("GET", "/api/bunker/export_contabile",
                                   self._senza_bunker())
        self.assertEqual(st, 403)
        self.assertEqual(json.loads(corpo), {"errore": "bunker_richiesto"})
        self.assertEqual(hd["content-type"], "application/json; charset=utf-8")

        st, hd, corpo = self._http("GET", "/api/bunker/export_contabile", self.BK)
        self.assertEqual(st, 200, corpo[:300])
        self.assertEqual(hd["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(hd["content-disposition"],
                         'attachment; filename="estratto_contabile_bookinvip.csv"')
        self.assertEqual(hd["cache-control"], "no-store")
        testo = corpo.decode("utf-8")
        self.assertIn("# BookinVIP - Estratto contabile certificato (streaming)", testo)
        self.assertIn("seq,data_utc,tipo,riferimento,soggetto,conto_dare,conto_avere,",
                      testo)
        self.assertIn(self.rif, testo)                 # la prenotazione VERA è dentro
        # il file si CHIUDE: senza la riga finale un download troncato passerebbe per buono
        m = re.search(r"# righe,(\d+)\r\n# FINE ESTRATTO - INTEGRITÀ VERIFICATA: ([0-9a-f]{64})\r\n$",
                      testo)
        self.assertIsNotNone(m, testo[-300:])
        righe_dichiarate = int(m.group(1))
        righe_vere = sum(1 for _ in self.sis.finanza.stream_giornale())
        self.assertEqual(righe_dichiarate, righe_vere)
        self.assertGreaterEqual(righe_vere, 1)
        # la riga di chiusura porta l'ultimo hash della catena, non un hash qualsiasi
        ultimo = [r["hash"] for r in self.sis.finanza.stream_giornale()][-1]
        self.assertEqual(m.group(2), ultimo)
        self.assertNotIn("NON CHIUSO / CORROTTO", testo)

    # ── 2b) dossier legale: CSV e JSON ──────────────────────────────────────────
    def test_export_legale_streaming_reale(self):
        st, hd, corpo = self._http("GET", "/api/bunker/export_legale",
                                   self._senza_bunker())
        self.assertEqual((st, json.loads(corpo)), (403, {"errore": "bunker_richiesto"}))

        st, hd, corpo = self._http("GET", "/api/bunker/export_legale", self.BK)
        self.assertEqual(st, 200, corpo[:300])
        self.assertEqual(hd["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(hd["content-disposition"],
                         'attachment; filename="dossier_legale_bookinvip.csv"')
        self.assertEqual(hd["cache-control"], "no-store")
        testo = corpo.decode("utf-8")
        self.assertIn(self.host_id, testo)
        self.assertIn(CONTRATTO_HOST_VERSIONE, testo)
        self.assertIn("# host,1\r\n", testo)
        self.assertIn("# prove_manomesse,0\r\n", testo)
        self.assertIn("# marche_temporali,1\r\n", testo)
        self.assertTrue(re.search(r"# FINE DOSSIER - INTEGRITÀ: [0-9a-f]{64}\r\n$", testo),
                        testo[-200:])

        st, hd, corpo = self._http(
            "GET", "/api/bunker/export_legale?formato=json", self.BK)
        self.assertEqual(st, 200)
        self.assertEqual(hd["content-type"], "application/json; charset=utf-8")
        self.assertEqual(hd["content-disposition"],
                         'attachment; filename="dossier_legale_bookinvip.json"')
        testo = corpo.decode("utf-8")
        self.assertIn(self.host_id, testo)
        self.assertTrue(re.search(r"# FINE DOSSIER - INTEGRITÀ: [0-9a-f]{64}\n$", testo),
                        testo[-200:])

    # ── 2c) report DAC7 ─────────────────────────────────────────────────────────
    def test_dac7_report_streaming_reale(self):
        st, _hd, corpo = self._http("GET", "/api/bunker/dac7_report?anno=%d" % self.anno_dati,
                                    self._senza_bunker())
        self.assertEqual((st, json.loads(corpo)), (403, {"errore": "bunker_richiesto"}))

        st, hd, corpo = self._http(
            "GET", "/api/bunker/dac7_report?anno=%d" % self.anno_dati, self.BK)
        self.assertEqual(st, 200, corpo[:300])
        self.assertEqual(hd["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(hd["content-disposition"],
                         'attachment; filename="dac7_report_%d.csv"' % self.anno_dati)
        self.assertEqual(hd["cache-control"], "no-store")
        testo = corpo.decode("utf-8")
        self.assertIn("- anno %d\r\n" % self.anno_dati, testo)
        self.assertIn(self.host_id, testo)
        self.assertIn("IT60X0542811101000000123456", testo)      # IBAN dell'host vero
        self.assertIn("# host_reportabili,1\r\n", testo)
        self.assertTrue(re.search(r"# FINE REPORT DAC7 - INTEGRITÀ: [0-9a-f]{64}\r\n$",
                                  testo), testo[-200:])
        # un anno SENZA dati: il file esiste, è chiuso, e dichiara ZERO host
        st, hd, corpo = self._http(
            "GET", "/api/bunker/dac7_report?anno=%d" % (self.anno_dati - 3), self.BK)
        self.assertEqual(st, 200)
        self.assertEqual(hd["content-disposition"],
                         'attachment; filename="dac7_report_%d.csv"' % (self.anno_dati - 3))
        self.assertIn("# host_reportabili,0\r\n", corpo.decode("utf-8"))

    # ── 2d) marca temporale: l'UNICO binario che esce ───────────────────────────
    def test_marca_tsr_binaria_reale(self):
        st, _hd, corpo = self._http("GET", "/api/bunker/marca.tsr?id=%d" % self.marca_id,
                                    self._senza_bunker())
        self.assertEqual((st, json.loads(corpo)), (403, {"errore": "non_disponibile"}))

        st, hd, corpo = self._http("GET", "/api/bunker/marca.tsr?id=%d" % self.marca_id,
                                   self.BK)
        self.assertEqual(st, 200)
        self.assertEqual(hd["content-type"], "application/timestamp-reply")
        self.assertEqual(hd["content-disposition"],
                         'attachment; filename="marca_%d.tsr"' % self.marca_id)
        self.assertEqual(hd["cache-control"], "no-store")
        # BYTE PER BYTE il token dell'Autorità: è ciò che si consegna a un perito
        self.assertEqual(corpo, TSR_FINTO)
        self.assertEqual(hd["content-length"], str(len(TSR_FINTO)))

        st, _hd, corpo = self._http("GET", "/api/bunker/marca.tsr?id=999999", self.BK)
        self.assertEqual((st, json.loads(corpo)), (404, {"errore": "non_disponibile"}))
        st, _hd, corpo = self._http("GET", "/api/bunker/marca.tsr?id=non-un-numero", self.BK)
        self.assertEqual((st, json.loads(corpo)), (400, {"errore": "non_disponibile"}))

    # ── 2e) HEAD: gli uptime monitor non devono scaricare i megabyte ────────────
    def test_head_sulle_rotte_intercettate_non_manda_il_corpo(self):
        for percorso in ("/api/bunker/export_contabile", "/api/bunker/export_legale",
                         "/api/bunker/dac7_report?anno=%d" % self.anno_dati,
                         "/api/bunker/marca.tsr?id=%d" % self.marca_id):
            st, hd, corpo = self._http("HEAD", percorso, self.BK)
            self.assertEqual(st, 200, percorso)
            self.assertEqual(corpo, b"", percorso)
            self.assertEqual(hd["cache-control"], "no-store", percorso)

    # ── 3) CORS: il preflight autorizza TUTTI gli header di autenticazione ──────
    @staticmethod
    def _insieme_header(valore):
        return {x.strip().lower() for x in (valore or "").split(",") if x.strip()}

    def test_preflight_dichiara_ogni_header_di_autenticazione(self):
        st, hd, _corpo = self._http("OPTIONS", "/api/catalogo", {
            "Origin": "https://partner.esempio",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-admin-key, x-host-token"})
        self.assertEqual(st, 204)
        self.assertEqual(hd["access-control-allow-origin"], "*")
        self.assertEqual(self._insieme_header(hd["access-control-allow-methods"]),
                         {"get", "post", "options"})
        self.assertEqual(
            self._insieme_header(hd["access-control-allow-headers"]),
            {"content-type", "x-host-key", "x-host-token", "x-admin-key", "x-admin-op",
             "x-bunker-session"})
        # nessuna credenziale ambientale: con Origin "*" i cookie non partono mai
        self.assertNotIn("access-control-allow-credentials", hd)

    def test_ogni_header_letto_dall_auth_e_dichiarato_nel_preflight(self):
        """Guardia AUTO-APPLICANTE: gli header li si legge DAL CODICE di autenticazione.
        Se domani nasce un `X-Qualcosa` di auth e nessuno tocca il CORS, qui è rosso."""
        import inspect
        sorgente = "".join(inspect.getsource(f) for f in (
            fase83_server.RouterHTTP._auth_host,
            fase83_server.RouterHTTP._host_id_da_token,
            fase83_server.RouterHTTP._auth_admin,
            fase83_server.RouterHTTP._bunker_auth))
        letti = {h.lower() for h in re.findall(r"X-[A-Za-z]+(?:-[A-Za-z]+)*", sorgente)}
        letti -= {"x-forwarded-for", "x-real-ip"}          # provenienza, non credenziali
        self.assertTrue(letti, "nessun header estratto: la lettura del codice è rotta")
        _st, hd, _c = self._http("OPTIONS", "/api/catalogo")
        dichiarati = self._insieme_header(hd["access-control-allow-headers"])
        self.assertEqual(sorted(letti - dichiarati), [],
                         "header di autenticazione NON dichiarati nel CORS: il browser "
                         "cross-origin non li spedisce -> 401 senza spiegazione")
        self.assertEqual(sorted(letti),
                         ["x-admin-key", "x-admin-op", "x-bunker-session", "x-host-key",
                          "x-host-token"])

    def test_impatto_vero_l_header_dichiarato_e_una_credenziale_che_funziona(self):
        """L'header dichiarato non è decorativo: con quello si entra, senza si è respinti."""
        st, hd, corpo = self._http("GET", "/api/admin/prenotazioni",
                                   {"X-Admin-Key": "ak", "X-Forwarded-For": IP_BUNKER})
        self.assertEqual(st, 200, corpo[:200])
        self.assertEqual(len(json.loads(corpo)["prenotazioni"]), 1)
        self.assertIn("x-admin-key", self._insieme_header(hd["access-control-allow-headers"]))
        st, _hd, _c = self._http("GET", "/api/admin/prenotazioni",
                                 {"X-Forwarded-For": IP_BUNKER})
        self.assertEqual(st, 401)

    def test_il_cors_c_e_anche_sulle_rotte_intercettate(self):
        """Le 4 rotte non passano dal router: il loro CORS è scritto a mano nell'Handler.
        Se qualcuno lo dimentica lì, un client di altra origine non scarica nulla."""
        attesi = {"content-type", "x-host-key", "x-host-token", "x-admin-key", "x-admin-op",
                  "x-bunker-session"}
        casi = [("/api/bunker/export_contabile", self.BK, 200),
                ("/api/bunker/export_contabile", self._senza_bunker(), 403),
                ("/api/bunker/export_legale", self.BK, 200),
                ("/api/bunker/dac7_report?anno=%d" % self.anno_dati, self.BK, 200),
                ("/api/bunker/marca.tsr?id=%d" % self.marca_id, self.BK, 200)]
        for percorso, hdr, atteso in casi:
            st, hd, _c = self._http("GET", percorso, hdr)
            self.assertEqual(st, atteso, percorso)
            self.assertEqual(hd.get("access-control-allow-origin"), "*", percorso)
            self.assertEqual(self._insieme_header(hd.get("access-control-allow-headers")),
                             attesi, percorso)


# ═════════════════════════════════════════════════════════════════════════════════
# 4) KILL-SWITCH GLOBALE: congela i soldi, lascia vivo il sito
# ═════════════════════════════════════════════════════════════════════════════════
WH2 = "whsec_killswitch"
CI, CO = "2027-08-10", "2027-08-12"


class _ConnectContatore:
    """Connect finto che CONTA i bonifici: prova che il freeze NON lo chiama."""

    def __init__(self):
        self.chiamate = []

    def trasferisci(self, acct, importo, valuta, rif):
        self.chiamate.append((acct, int(importo), valuta, str(rif)))
        return "tr_OK"


class TestKillSwitchGlobale(unittest.TestCase):
    """Questione 4: l'interruttore accende e spegne DAVVERO?"""

    def setUp(self):
        d = self.dir = tempfile.mkdtemp(prefix="aperte_freeze_")
        os.environ.pop("BLOCCO_GLOBALE", None)
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"K" * 32, con_registrazione_host=True,
            db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
            db_pendenti=d + "/p.db", db_payout=d + "/po.db", db_finanza=d + "/fin.db",
            db_tassa_comunale=d + "/tc.db", db_garanzia=d + "/g.db",
            commissione_bps=1500, stripe_webhook_secret=WH2, bunker_password="SuperPw@1"))
        self.sis.concierge._link = lambda dati: "https://pay/" + str(
            dati.get("riferimento", ""))
        self.connect = _ConnectContatore()
        self.sis.connect = self.connect
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        self.bg = self.sis.blocco_globale
        self.flag = os.path.join(d, "blocco_globale.flag")
        es = self.sis.registro_host.registra("freeze@aperte.invalid", "password12",
                                             accetta_termini=True)
        self.hid = es.host_id
        self.sis.registro_host.imposta_stripe_account(self.hid, "acct_TEST")
        st, _o = self.g("POST", "/api/host/pubblica",
                        {"host_id": self.hid, "slug": "casa", "titolo": "C", "citta": "Roma",
                         "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
                         "servizi": [], "immagini": []}, {"X-Host-Key": "hk"})
        self.assertEqual(st, 201)
        st, _o = self.g("POST", "/api/host/disponibilita_range",
                        {"alloggio_id": "casa", "da": "2027-08-01", "a": "2027-08-31",
                         "unita_totali": 5, "prezzo_netto_cents": 10000},
                        {"X-Host-Key": "hk"})
        self.assertEqual(st, 200)
        self.BK = {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.7",
                   "X-Bunker-Session": self._sessione()}

    def tearDown(self):
        os.environ.pop("BLOCCO_GLOBALE", None)
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, metodo, percorso, corpo=None, headers=None, query=None):
        return self.r.gestisci(metodo, percorso, query or {},
                               json.dumps(corpo) if corpo is not None else None,
                               headers or {})

    def _sessione(self):
        st, out = self.g("POST", "/api/bunker/login", {"codice": "SuperPw@1"},
                         {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.7"})
        self.assertEqual(st, 200, out)
        return out["sessione"]

    def _prenota_e_paga(self):
        st, q = self.g("POST", "/api/concierge/quote",
                       {"alloggio_id": "casa", "check_in": CI, "check_out": CO, "party": 2})
        self.assertEqual(st, 200, q)
        st, b = self.g("POST", "/api/concierge/book",
                       {"quote_token": q["quote_token"], "email": "o@aperte.invalid"})
        self.assertEqual(st, 201, b)
        rif = b["riferimento"]
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": rif}}}})
        ts = str(int(time.time()))
        mac = hmac.new(WH2.encode(), ("%s.%s" % (ts, payload)).encode(),
                       hashlib.sha256).hexdigest()
        st, out = self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                                  {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})
        self.assertEqual(st, 200, out)
        return rif

    def _stato_book(self):
        return self.g("POST", "/api/concierge/book", {"quote_token": "non-valido"})[0]

    # ── 4a) l'interruttore muove uno STATO VERO, su disco ───────────────────────
    def test_accende_e_spegne_con_traccia_su_disco(self):
        st, out = self.g("GET", "/api/bunker/blocco_globale", None, self.BK)
        self.assertEqual((st, out), (200, {"attivo": False, "env": False,
                                           "runtime": False, "dettaglio": None}))
        self.assertFalse(os.path.exists(self.flag))

        st, out = self.g("POST", "/api/bunker/blocco_globale",
                         {"attivo": True, "motivo": "gateway impazzito"}, self.BK)
        self.assertEqual(st, 200, out)
        self.assertEqual((out["attivo"], out["env"], out["runtime"], out["impostato"]),
                         (True, False, True, True))
        self.assertEqual(out["dettaglio"]["motivo"], "gateway impazzito")
        self.assertEqual(out["dettaglio"]["chi"], "super-admin")
        self.assertIsInstance(out["dettaglio"]["ts"], int)
        # la traccia è un FILE, non una variabile in RAM: sopravvive al processo
        self.assertTrue(os.path.exists(self.flag))
        with open(self.flag, encoding="utf-8") as f:
            su_disco = json.load(f)
        self.assertEqual(su_disco["attivo"], True)
        self.assertEqual(su_disco["motivo"], "gateway impazzito")
        self.assertEqual(su_disco["chi"], "super-admin")

        st, out = self.g("GET", "/api/bunker/blocco_globale", None, self.BK)
        self.assertEqual((st, out["attivo"], out["runtime"]), (200, True, True))

        st, out = self.g("POST", "/api/bunker/blocco_globale",
                         {"attivo": False, "motivo": "rientrato"}, self.BK)
        self.assertEqual((st, out["attivo"], out["runtime"], out["impostato"]),
                         (200, False, False, True))
        self.assertIsNone(out["dettaglio"])
        self.assertFalse(os.path.exists(self.flag))

    def test_il_freeze_sopravvive_al_riavvio(self):
        """Un incidente non deve finire perché è ripartito un container."""
        self.g("POST", "/api/bunker/blocco_globale",
               {"attivo": True, "motivo": "sospetto frode"}, self.BK)
        d = self.dir
        risorto = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"K" * 32, db_payout=d + "/po.db",
            db_finanza=d + "/fin.db", bunker_password="SuperPw@1"))
        self.assertTrue(risorto.blocco_globale.attivo(),
                        "il freeze si è dimenticato al riavvio: i soldi ripartono da soli")
        self.assertEqual(risorto.blocco_globale.stato()["dettaglio"]["motivo"],
                         "sospetto frode")

    # ── 4b) i tre movimenti di denaro si fermano DAVVERO (uno per prova) ────────
    def _accendi(self, motivo="incidente"):
        st, out = self.g("POST", "/api/bunker/blocco_globale",
                         {"attivo": True, "motivo": motivo}, self.BK)
        self.assertEqual((st, out["attivo"]), (200, True), out)

    def _spegni(self):
        st, out = self.g("POST", "/api/bunker/blocco_globale", {"attivo": False}, self.BK)
        self.assertEqual((st, out["attivo"]), (200, False), out)

    def test_freeze_blocca_la_nuova_prenotazione(self):
        self._accendi()
        st, q = self.g("POST", "/api/concierge/quote",
                       {"alloggio_id": "casa", "check_in": "2027-08-20",
                        "check_out": "2027-08-22", "party": 2})
        self.assertEqual(st, 200, q)             # il PREVENTIVO non è un movimento: vive
        st, out = self.g("POST", "/api/concierge/book",
                         {"quote_token": q["quote_token"], "email": "x@aperte.invalid"})
        self.assertEqual((st, out), (503, {"errore": "transazioni_sospese"}))
        self._spegni()
        st, out = self.g("POST", "/api/concierge/book",
                         {"quote_token": q["quote_token"], "email": "x@aperte.invalid"})
        self.assertEqual(st, 201, out)           # stesso preventivo, ora passa

    def test_freeze_blocca_il_rimborso_anche_col_bunker(self):
        rif = self._prenota_e_paga()
        idem = (self.sis.pagamenti_pendenti.info(rif) or {}).get("idem_key")
        self.assertTrue(idem)
        self._accendi()
        # doppia chiave valida: il 503 non è un problema di permessi, è il freeze
        st, out = self.g("POST", "/api/admin/rimborso",
                         {"alloggio_id": "casa", "check_in": CI, "check_out": CO,
                          "idem_key": idem}, self.BK)
        self.assertEqual((st, out), (503, {"errore": "transazioni_sospese"}))
        self.assertEqual((self.sis.pagamenti_pendenti.info(rif) or {}).get("stato"),
                         "pagato", "il rimborso rifiutato ha comunque toccato lo stato")
        self._spegni()
        st, out = self.g("POST", "/api/admin/rimborso",
                         {"alloggio_id": "casa", "check_in": CI, "check_out": CO,
                          "idem_key": idem}, self.BK)
        self.assertEqual(st, 200, out)

    def test_freeze_blocca_il_bonifico_senza_perdere_i_soldi(self):
        rif = self._prenota_e_paga()
        netto = self.sis.payout.riepilogo(self.hid)["EUR"]["maturato"]
        self.assertGreater(netto, 0)
        self._accendi()
        self.r._trasferisci_all_host(rif, netto)
        self.assertEqual(self.connect.chiamate, [])
        self.assertEqual(self.sis.payout.stato_di(rif), "maturato")   # parcheggiato
        self.assertNotIn("payout_host",
                         [m["tipo"] for m in self.sis.finanza.movimenti(rif)])
        # ── a freeze spento il bonifico riparte da solo: stesso rif, stesso importo
        self._spegni()
        self.r._trasferisci_all_host(rif, netto)
        self.assertEqual(len(self.connect.chiamate), 1, self.connect.chiamate)
        self.assertEqual(self.connect.chiamate[0], ("acct_TEST", netto, "EUR", rif))
        self.assertEqual(self.sis.payout.stato_di(rif), "in_transito")
        self.assertIn("payout_host",
                      [m["tipo"] for m in self.sis.finanza.movimenti(rif)])

    def test_durante_il_freeze_il_sito_resta_navigabile(self):
        """Congelare i soldi NON deve spegnere il negozio: si guarda, non si compra."""
        self.g("POST", "/api/bunker/blocco_globale", {"attivo": True}, self.BK)
        self.assertTrue(self.bg.attivo())
        st, out = self.g("GET", "/api/catalogo")
        self.assertEqual(st, 200, out)
        self.assertEqual([a["slug"] for a in out["risultati"]], ["casa"])
        st, out = self.g("GET", "/api/catalogo/casa")
        self.assertEqual((st, out["slug"]), (200, "casa"))
        st, out = self.g("GET", "/api/host/calendario", None, {"X-Host-Key": "hk"},
                         {"alloggio": "casa", "da": "2027-08-01", "a": "2027-08-05"})
        self.assertEqual((st, len(out["giorni"])), (200, 4))
        st, out = self.g("GET", "/api/bunker/blocco_globale", None, self.BK)
        self.assertEqual((st, out["attivo"]), (200, True))

    # ── 4c) chi può girare l'interruttore, e chi comanda su chi ─────────────────
    def test_solo_il_super_admin_puo_girare_l_interruttore(self):
        st, out = self.g("POST", "/api/bunker/blocco_globale", {"attivo": True},
                         {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.7"})
        self.assertEqual((st, out), (403, {"errore": "bunker_richiesto"}))
        self.assertFalse(self.bg.attivo(), "un 403 ha acceso qualcosa")
        self.assertFalse(os.path.exists(self.flag))
        st, out = self.g("GET", "/api/bunker/blocco_globale", None, {"X-Admin-Key": "ak"})
        self.assertEqual((st, out), (403, {"errore": "bunker_richiesto"}))

    def test_l_env_e_autorevole_il_pannello_non_la_spegne(self):
        """La env è la rete di sicurezza: dal pannello non si deve poter sbloccare
        un freeze deciso a livello server (si toglie solo cambiando la env)."""
        os.environ["BLOCCO_GLOBALE"] = "1"
        self.assertTrue(self.bg.attivo())
        self.assertEqual(self._stato_book(), 503)
        st, out = self.g("POST", "/api/bunker/blocco_globale",
                         {"attivo": False, "motivo": "provo a sbloccare"}, self.BK)
        self.assertEqual(st, 200, out)
        self.assertEqual((out["attivo"], out["env"], out["runtime"]), (True, True, False))
        self.assertEqual(self._stato_book(), 503, "il pannello ha scavalcato la env")
        os.environ["BLOCCO_GLOBALE"] = "0"
        self.assertFalse(self.bg.attivo())
        self.assertNotEqual(self._stato_book(), 503)


# ═════════════════════════════════════════════════════════════════════════════════
# 5) I DUE CAMPI DATA: lettura e scrittura devono raccontare la stessa storia
# ═════════════════════════════════════════════════════════════════════════════════
class TestRangeCalendario(unittest.TestCase):
    """Questione 5.

    DECISO — il comportamento corretto è UNO: `da`/`a` = intervallo di NOTTI semi-aperto
    [da, a), al massimo 366. È il contratto di tutta la macchina (fase34 prenotazione,
    `fase58.notti`, POST /api/host/disponibilita_range, import iCal). Chi legge e chi
    scrive devono rispondere allo STESSO modo agli stessi due campi.

    Prima: la SCRITTURA rifiutava 422 (`date_non_valide` / `intervallo_non_valido`), la
    LETTURA rispondeva 200 con la lista VUOTA. Nel pannello host i due campi sono gli
    stessi (`c_da`, `c_a`) per tutti e tre i pulsanti: chi sbagliava le date leggeva
    «0 giorni» — cioè «il tuo calendario è vuoto», che è una BUGIA su cui un host può
    riaprire disponibilità già vendute. Ora leggono e scrivono lo stesso vocabolario.

    RESTA DIVERSA, di proposito, una cosa sola: /api/host/calendario_prezzi (fase119) usa
    un range INCLUSIVO [da, a]. Non è una svista: è una griglia di PREZZI, il suo contratto
    (`da == a` -> 1 cella) è fissato da test_fase119 / test_calendario_prezzi /
    test_happy_host, e cambiarlo romperebbe quei contratti. Qui sotto è INCHIODATA con
    un'asserzione esatta, così la differenza resta nota e misurata invece che sospetta.
    """

    HK = {"X-Host-Key": "hk"}

    def setUp(self):
        d = self.dir = tempfile.mkdtemp(prefix="aperte_range_")
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"R" * 32, con_registrazione_host=True,
            db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_payout=d + "/po.db",
            db_registro_host=d + "/r.db"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        self.base = datetime.date(2027, 3, 1)
        st, _o = self.g("POST", "/api/host/pubblica",
                        {"host_id": "h", "slug": "casa", "titolo": "C", "citta": "Roma",
                         "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
                         "servizi": [], "immagini": []}, self.HK)
        self.assertEqual(st, 201)
        st, out = self.g("POST", "/api/host/disponibilita_range",
                         {"alloggio_id": "casa", "da": self.gg(0), "a": self.gg(30),
                          "unita_totali": 1, "prezzo_netto_cents": 10000}, self.HK)
        self.assertEqual((st, out), (200, {"giorni_impostati": 30}))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def gg(self, i):
        return (self.base + datetime.timedelta(days=i)).isoformat()

    def g(self, metodo, percorso, corpo=None, headers=None, query=None):
        return self.r.gestisci(metodo, percorso, query or {},
                               json.dumps(corpo) if corpo is not None else None,
                               headers or {})

    def _leggi(self, da, a):
        return self.g("GET", "/api/host/calendario", None, self.HK,
                      {"alloggio": "casa", "da": da, "a": a})

    def _scrivi(self, da, a):
        return self.g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": "casa", "da": da, "a": a, "unita_totali": 1,
                       "prezzo_netto_cents": 10000}, self.HK)

    # ── 5a) stesso range assurdo -> stessa identica risposta ────────────────────
    def test_lettura_e_scrittura_rifiutano_lo_stesso_range_allo_stesso_modo(self):
        casi = [
            ("a prima di da", self.gg(5), self.gg(2), "intervallo_non_valido"),
            ("a uguale a da", self.gg(5), self.gg(5), "intervallo_non_valido"),
            ("367 notti", "2027-01-01", "2028-01-03", "intervallo_non_valido"),
            ("mese 13", "2027-13-01", "2027-13-05", "date_non_valide"),
            ("giorno 32", "2027-01-32", "2027-02-01", "date_non_valide"),
            ("stringa vuota", "", self.gg(3), "date_non_valide"),
            ("non una data", "domani", "dopodomani", "date_non_valide"),
            ("formato all'americana", "03/01/2027", "03/05/2027", "date_non_valide"),
        ]
        for etichetta, da, a, atteso in casi:
            st_l, out_l = self._leggi(da, a)
            st_s, out_s = self._scrivi(da, a)
            self.assertEqual((st_l, out_l), (422, {"errore": atteso}),
                             "LETTURA %s (%s -> %s)" % (etichetta, da, a))
            self.assertEqual((st_s, out_s), (422, {"errore": atteso}),
                             "SCRITTURA %s (%s -> %s)" % (etichetta, da, a))
            self.assertEqual(out_l, out_s, "lettura e scrittura divergono su %s" % etichetta)

    def test_niente_piu_calendario_vuoto_bugiardo(self):
        """Il difetto in una riga: prima `da` dopo `a` dava 200 con zero giorni, e il
        pannello scriveva «0 giorni» in verde come se il calendario fosse vuoto."""
        st, out = self._leggi(self.gg(10), self.gg(3))
        self.assertEqual(st, 422)
        self.assertEqual(out, {"errore": "intervallo_non_valido"})
        self.assertNotIn("giorni", out)
        # e la vista multi-alloggio, che nel pannello divide gli STESSI due campi, idem
        st, out = self.g("GET", "/api/host/calendario_tutti", None, self.HK,
                         {"host_id": "h", "da": self.gg(10), "a": self.gg(3)})
        self.assertEqual((st, out), (422, {"errore": "intervallo_non_valido"}))

    # ── 5b) il range BUONO continua a leggersi identico (nessuna regressione) ───
    def test_il_range_valido_resta_semiaperto_e_identico_fra_le_rotte(self):
        st, cal = self._leggi(self.gg(0), self.gg(5))
        self.assertEqual(st, 200, cal)
        self.assertEqual([x["giorno"] for x in cal["giorni"]],
                         [self.gg(i) for i in range(5)])       # [da, a): 5 notti, NON 6
        self.assertEqual({x["stato"] for x in cal["giorni"]}, {"libero"})
        self.assertEqual({x["prezzo_netto_cents"] for x in cal["giorni"]}, {10000})

        st, tutti = self.g("GET", "/api/host/calendario_tutti", None, self.HK,
                           {"host_id": "h", "da": self.gg(0), "a": self.gg(5)})
        self.assertEqual(st, 200, tutti)
        self.assertEqual([x["giorno"] for x in tutti["alloggi"][0]["giorni"]],
                         [self.gg(i) for i in range(5)])

        st, out = self._scrivi(self.gg(0), self.gg(5))
        self.assertEqual((st, out), (200, {"giorni_impostati": 5}))   # stesso conteggio

    def test_i_confini_esatti_365_366_367(self):
        st, out = self._leggi("2027-01-01", "2028-01-01")          # 365 notti
        self.assertEqual((st, len(out["giorni"])), (200, 365))
        st, out = self._leggi("2027-01-01", "2028-01-02")          # 366: ultimo consentito
        self.assertEqual((st, len(out["giorni"])), (200, 366))
        st, out = self._leggi("2027-01-01", "2028-01-03")          # 367: uno di troppo
        self.assertEqual((st, out), (422, {"errore": "intervallo_non_valido"}))
        st, out = self._scrivi("2027-01-01", "2028-01-03")
        self.assertEqual((st, out), (422, {"errore": "intervallo_non_valido"}))

    def test_i_campi_mancanti_restano_come_prima(self):
        """La correzione non ha cambiato il caso «non hai proprio scritto le date»."""
        st, out = self.g("GET", "/api/host/calendario", None, self.HK, {"alloggio": "casa"})
        self.assertEqual((st, out), (422, {"errore": "campi_non_validi"}))
        st, out = self.g("GET", "/api/host/calendario", None, self.HK,
                         {"da": self.gg(0), "a": self.gg(3)})
        self.assertEqual((st, out), (422, {"errore": "campi_non_validi"}))
        st, out = self.g("GET", "/api/host/calendario_tutti", None, self.HK,
                         {"host_id": "h"})
        self.assertEqual((st, out), (422, {"errore": "date_mancanti"}))

    def test_l_ordine_dei_controlli_non_diventa_un_oracolo(self):
        """Il 403 «non è tuo» deve venire PRIMA della validazione delle date: altrimenti
        un estraneo capirebbe, dalla differenza fra 422 e 403, se lo slug esiste."""
        st, out = self.g("POST", "/api/host/pubblica",
                         {"host_id": "altro", "slug": "villa-altrui", "titolo": "V",
                          "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 9000,
                          "capacita": 2, "servizi": [], "immagini": []}, self.HK)
        self.assertEqual(st, 201, out)
        es = self.sis.registro_host.registra("estraneo@aperte.invalid", "password12",
                                             accetta_termini=True)
        self.assertTrue(es.ok and es.token, es)
        token = {"X-Host-Token": es.token}
        for da, a in ((self.gg(0), self.gg(3)), (self.gg(3), self.gg(0)), ("x", "y")):
            s, o = self.g("GET", "/api/host/calendario", None, token,
                          {"alloggio": "villa-altrui", "da": da, "a": a})
            self.assertEqual((s, o), (403, {"errore": "non_tuo"}), (da, a))

    # ── 5c) l'asimmetria che RESTA, inchiodata e spiegata ───────────────────────
    def test_asimmetria_documentata_del_calendario_prezzi(self):
        """fase119 = griglia PREZZI, range INCLUSIVO [da, a]. Con gli stessi due campi
        del pannello mostra esattamente UN giorno in più del calendario disponibilità.
        Documentato qui, non corretto: il suo contratto è fissato da altri test."""
        st, cal = self._leggi(self.gg(0), self.gg(5))
        self.assertEqual(st, 200)
        st, prezzi = self.g("GET", "/api/host/calendario_prezzi", None, self.HK,
                            {"alloggio": "casa", "da": self.gg(0), "a": self.gg(5)})
        self.assertEqual(st, 200, prezzi)
        self.assertEqual(len(prezzi["celle"]), len(cal["giorni"]) + 1)
        self.assertEqual([c["giorno"] for c in prezzi["celle"]],
                         [self.gg(i) for i in range(6)])
        self.assertEqual(prezzi["celle"][-1]["giorno"], self.gg(5))   # = `a`, incluso
        self.assertEqual(cal["giorni"][-1]["giorno"], self.gg(4))     # = `a` - 1 notte
        # `da == a`: una cella di prezzo, zero notti da vendere. Le due letture NON sono
        # intercambiabili e chi le usa deve saperlo.
        st, prezzi = self.g("GET", "/api/host/calendario_prezzi", None, self.HK,
                            {"alloggio": "casa", "da": self.gg(0), "a": self.gg(0)})
        self.assertEqual((st, len(prezzi["celle"])), (200, 1))
        st, out = self._leggi(self.gg(0), self.gg(0))
        self.assertEqual((st, out), (422, {"errore": "intervallo_non_valido"}))


# ═════════════════════════════════════════════════════════════════════════════════
# VISTO ROSSO — ogni guardia è stata provata rompendo il codice che sorveglia.
#
# 1) SchemaOrologio, 4 guasti provati (11 campioni di controllo + una cartella finta):
#    `_dalla_risposta`->False, `_dalla_risposta`->True, `_orologio`->"" e
#    `_nomi_spediti`->set() (= eco non distinta) rendono rosse 2-3 prove ciascuno.
#    Prova sul campo: la guardia È diventata rossa da sola quando un'altra squadra ha
#    aggiunto `test_profondo_pagine_api.py` — ed è così che si è scoperto che il
#    rilevatore doveva separare l'ECO dai DUE OROLOGI.
# 2) 4 rotte HTTP: `TSR_FINTO = b""` -> marca.tsr torna 404 (3 prove rosse); generatore
#    dell'estratto senza la riga «# FINE ESTRATTO» -> rossa la prova dell'estratto.
# 3) CORS: rimettendo `"Content-Type, X-Host-Key"` in `_cors` -> rosse tutte e quattro le
#    prove CORS (preflight, guardia auto-applicante, impatto vero, rotte intercettate:
#    quest'ultima legge l'header proprio dalle 4 rotte scritte a mano nell'Handler).
# 4) Kill-switch: `_transazioni_bloccate`->False (= come se la guardia non ci fosse in
#    nessuno dei 3 punti) -> rosse le 3 prove del freeze + quella della env autorevole;
#    `BloccoGlobale.imposta` che non scrive il flag -> 6 prove rosse.
# 5) Range: togliendo `_errore_range_notti` da `_host_calendario` -> 4 prove rosse;
#    togliendolo da `_host_calendario_tutti` -> rossa `test_niente_piu_calendario_vuoto
#    _bugiardo`.
# ═════════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    unittest.main(verbosity=2)
