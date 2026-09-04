"""L'ESAME DELLA CASELLA 2 DEL BLOCCO SOLDI — «i soldi tornano DAVVERO da OGNI strada».

    python collaudi/esame_rimborsi.py               misura e MOSTRA, senza scrivere
    python collaudi/esame_rimborsi.py --scrivi      misura e SCRIVE nella scheda (anche un rosso,
                                                    col suo motivo: una casella vuota senza
                                                    motivo manda a caccia di un guasto che puo'
                                                    non esistere)
    python collaudi/esame_rimborsi.py --senza-e2e   non interroga Stripe di prova (la casella
                                                    NON puo' diventare verde: l'uscita vera
                                                    non e' stata vista)
    python collaudi/esame_rimborsi.py --autoprova   si vede gridare e tacere (D18 punto 2)

⛔ IL TESTO DELLA CASELLA NON SI RICOPIA: si legge da `collaudi/piano.py` (e' la chiave della
   scheda; una copia a mano spunterebbe una casella diversa il giorno che il piano cambia).

COME MISURA, in quattro anelli — e nessuno e' un'opinione:
  1. LE STRADE LE CONTA UNA MACCHINA. `test_rimborso_ogni_strada.chiamate_al_giornale()` legge
     l'albero sintattico di `fase83_server.py` e trova ogni `_giornale(tipo="rimborso", ...)`:
     quello e' il denominatore (oggi sette). Se ne compare un'ottava, compare anche qui.
  2. LE GUARDIE VERE SI ESEGUONO, NON SI RILEGGONO. Si accendono i moduli di test che nominano la
     lista dei rimborsi dovuti o il suo pulsante, e mentre girano un OSSERVATORE (installato sulla
     classe del server, dentro questo processo) annota tre fatti per ogni collaudo: ogni scrittura
     di un rimborso nel giornale (strada, riferimento, importo), ogni riga mostrata dalla lista
     (riferimento, dovuto, pulsante, cosa manca) e ogni richiesta che arriva al gateway
     (`stripe.rimborsa`: pagamento, importo). Il criterio NON e' riscritto qui: le guardie
     giudicano, l'osservatore dice solo CHI ha percorso COSA.
  3. PER OGNI STRADA si cerca UN collaudo VERDE in cui la catena e' intera: la strada scrive il
     dovuto X per la prenotazione R -> la lista mostra R con X e il pulsante -> il gateway riceve
     X su quel pagamento -> una lettura successiva non mostra piu' R (Stripe conferma). La strada
     che restituisce da se' (rimborso admin) e' intera quando scrive X e, nella stessa chiamata,
     il gateway riceve X. Una strada che in nessun collaudo verde chiude la catena e' dichiarata
     con quello che le manca, mai sottintesa.
  4. L'USCITA VERA LA GIUDICA STRIPE. `collaudi/e2e_rimborso_stripe.py` (R1-R7, chiave di PROVA
     fuori dal repository) deve essere verde: senza, la casella non si spunta, perche' un
     gateway finto prova il nostro codice e non che un centesimo sia uscito.

⛔ LA CASELLA E' VERDE SOLO SE TUTTE LE STRADE CHIUDONO LA CATENA E L'E2E E' VERDE. Una strada la
   cui uscita e' una persona nel pannello di Stripe (oggi: la controversia, per scelta dichiarata
   in `_admin_controversia_risolvi`) viene misurata e scritta come «uscita manuale dichiarata»:
   e' un fatto, non un verde. Chi vuole spuntare la casella deve o dare a quella strada un
   pulsante (produzione: serve «autorizzato») o riscrivere la casella (il fondatore).

⛔ D18, LE QUATTRO CONDIZIONI DI UNO STRUMENTO CHE MISURA:
   1. misura PRIMA se stesso: `precondizioni()` ferma il giro invece di stampare un numero;
   2. provato nelle DUE direzioni: `--autoprova` lo vede perdere una strada col guasto dentro e
      ritrovarla a macchina sana;
   3. dichiara cosa NON ha esaminato: `NON_GUARDA`, stampato a ogni giro;
   4. e' a sua volta sotto guardia: `test_pipeline_ci.TestLEsameDeiRimborsiNonPuoBARARE`.
"""
import ast
import io
import os
import re
import subprocess
import sys
import threading
import unittest

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

BLOCCO_SOLDI = 1
INDICE_CASELLA = 1                       # la seconda casella del blocco (0-based)
COMANDO = "python collaudi/esame_rimborsi.py --scrivi"
E2E = os.path.join(QUI, "e2e_rimborso_stripe.py")
# ⛔ Stessa fonte dell'E2E, che a sua volta la legge da qui: la chiave di PROVA vive FUORI dal
#    repository. Qui si guarda solo se il file ESISTE; non si legge, non si stampa.
FILE_CHIAVE = os.environ.get("STRIPE_TEST_KEY_FILE",
                             os.path.join(os.path.dirname(RADICE), "stripe.com prova.txt"))
GATEWAY = ("_admin_rimborso", "_admin_rimborsa_dovuto")   # i due punti che chiamano `.rimborsa(`
STRADA_DEL_GUASTO = "rimborso 100% per cancellazione host"

TORNA_DIRETTA = "TORNA (la strada restituisce da se', e il gateway riceve la cifra)"
TORNA_PULSANTE = "TORNA (in lista col pulsante, il gateway riceve la cifra, la riga esce)"
MANUALE = "USCITA MANUALE DICHIARATA (in lista con la cifra, SENZA pulsante)"
NON_ESCE = "IN LISTA, MA NESSUN COLLAUDO VERDE LA PORTA AL GATEWAY"
NON_IN_LISTA = "SCRITTA NEL GIORNALE, MA NESSUN COLLAUDO VERDE LA VEDE IN LISTA"
NON_MISURATA = "NON MISURATA: nessun collaudo verde percorre questa strada"
STATI_CHE_TORNANO = (TORNA_DIRETTA, TORNA_PULSANTE)

NON_GUARDA = (
    "il gateway dei collaudi e' FINTO (la rete di Stripe sostituita, il provider vero): la "
    "prova che un rimborso ESCE davvero la da' solo l'E2E contro Stripe di prova, e l'E2E "
    "percorre due strade (cancellazione ospite e controversia), non sette: per le altre cinque "
    "il gateway finto riceve la cifra, e oltre c'e' solo Stripe",
    "la persona che rimborsa A MANO dal pannello Stripe (l'uscita dichiarata della "
    "controversia): quel gesto avviene fuori dal prodotto, e nessuna macchina vede la cifra "
    "che digita. Il prodotto chiude la riga a QUALUNQUE rimborso > 0 visto su Stripe "
    "(`_rimborso_dovuto_scheda`, `gia`): un rimborso manuale minore del dovuto la chiude "
    "lo stesso -- limite misurato, scritto nel registro, non riparato qui",
    "`_giornale` e' un no-op silenzioso se `importo_cents <= 0` o se il modulo finanza e' "
    "spento: una strada che calcola zero non scrive e non compare, e questo esame non lo "
    "distingue da «nessun rimborso dovuto»",
    "le strade sono cercate SOLO in `fase83_server.py` (come il censimento): il vecchio stack "
    "`fase35/36/41` (nessun modulo di produzione lo importa) e la garanzia sonno `fase78` "
    "(creata nel bootstrap, `valuta_garanzia` mai chiamata) non passano dal giornale e non "
    "sono strade di questo prodotto: se un giorno lo diventano, il censimento non le vede",
    "i moduli di test da accendere sono scelti per NOME (chi nomina la lista o il pulsante nel "
    "sorgente, anche in un commento) E per IMPORT del server (albero sintattico): un nome in "
    "piu' accende una guardia in piu', mai una catena in piu' -- la catena la provano solo gli "
    "eventi osservati in un collaudo verde; un collaudo che guida il server senza importarlo "
    "(importlib, un altro modulo) non viene acceso",
    "le altre cinque caselle del blocco: non le tocca",
)


# --------------------------------------------------------------------------------------
# 1. LE STRADE, LETTE DAL CODICE (il denominatore non e' un elenco a mano)
# --------------------------------------------------------------------------------------
def strade_censite():
    """(lista di (causale, chiave), righe con `tipo` non leggibile) — dal censimento, che legge
    l'albero sintattico di `fase83_server.py`. Una funzione a se' perche' la guardia sull'esame
    la storce per vedere l'esame fermarsi (D18 punto 4)."""
    import test_rimborso_ogni_strada as censimento
    return censimento.chiamate_al_giornale()


def strade():
    """{causale_dichiarata: regex che riconosce la causale a RUNTIME}. Le causali con `%s`
    (una: lo stato della prenotazione) diventano un'espressione regolare."""
    fuori = {}
    for causale, _chiave in strade_censite()[0]:
        if causale is None:
            continue
        pezzi = [re.escape(p) for p in causale.split("%s")]
        fuori[causale] = re.compile("^" + ".*".join(pezzi) + "$")
    return fuori


def _quale_strada(causale_runtime, mappa):
    """La strada censita a cui appartiene una causale letta a RUNTIME (o None).
    ⛔ Si confronta la causale RUNTIME, non la chiave: la prima stesura confrontava l'espressione
    con la propria chiave e ogni scrittura finiva nella prima strada della mappa (7 strade, una
    sola «misurata»). L'ha preso lo script di prova, prima della guardia."""
    testo = str(causale_runtime or "")
    for causale, regex in mappa.items():
        if regex.match(testo):
            return causale
    return None


# --------------------------------------------------------------------------------------
# 2. L'OSSERVATORE — annota, non giudica
# --------------------------------------------------------------------------------------
EVENTI = []
CORRENTE = {"test": None}
_LOCALE = threading.local()
_INSTALLATO = {"fatto": False}
_CONTATORE = [0]


def _handler_corrente():
    return getattr(_LOCALE, "handler", None)


def _classe_del_server():
    """La classe di `fase83_server` che definisce `_giornale`: e' li' che passano tutte le
    strade (lo dichiara il suo docstring, e il censimento lo misura)."""
    import fase83_server
    for nome in dir(fase83_server):
        oggetto = getattr(fase83_server, nome)
        if isinstance(oggetto, type) and "_giornale" in vars(oggetto):
            return oggetto
    return None


def installa_osservatore():
    """Avvolge `_giornale`, la lista e i due punti che chiamano il gateway. Una volta sola per
    processo. ⛔ Nessun `fase*.py` viene toccato (B4): si sostituiscono attributi della classe
    importata, dentro questo processo, che muore alla fine della passata."""
    if _INSTALLATO["fatto"]:
        return True
    cls = _classe_del_server()
    if cls is None:
        return False

    vero_giornale = cls._giornale

    def giornale(self, *a, **k):
        if k.get("tipo") == "rimborso":
            f = sys._getframe(1)
            EVENTI.append({"tipo": "scrittura", "test": CORRENTE["test"],
                           "handler": _handler_corrente(), "causale": k.get("causale"),
                           "rif": str(k.get("riferimento")), "importo": k.get("importo_cents"),
                           "funzione": f.f_code.co_name, "riga": f.f_lineno})
        return vero_giornale(self, *a, **k)

    vera_lista = cls._admin_rimborsi_dovuti

    def lista(self, *a, **k):
        esito = vera_lista(self, *a, **k)
        try:
            stato, corpo = esito
        except Exception:
            return esito
        if stato == 200 and isinstance(corpo, dict):
            righe = [r for r in (corpo.get("rimborsi") or []) if isinstance(r, dict)]
            EVENTI.append({"tipo": "lettura", "test": CORRENTE["test"],
                           "rifs": [str(r.get("riferimento")) for r in righe],
                           "righe": [{"rif": str(r.get("riferimento")),
                                      "importo": r.get("dovuto_cents"),
                                      "pi": r.get("payment_intent"),
                                      "bottone": bool(r.get("bottone")),
                                      "manca": list(r.get("manca") or [])} for r in righe]})
        return esito

    def _con_gateway(nome, vero):
        def handler(self, *a, **k):
            _CONTATORE[0] += 1
            mio = (nome, _CONTATORE[0])
            prima = _handler_corrente()
            _LOCALE.handler = mio
            sp = getattr(self._sys, "stripe", None)
            vero_rimborsa = getattr(sp, "rimborsa", None) if sp is not None else None
            aveva = "rimborsa" in getattr(sp, "__dict__", {}) if sp is not None else False
            precedente = getattr(sp, "__dict__", {}).get("rimborsa") if aveva else None

            def rimborsa(*aa, **kk):
                EVENTI.append({"tipo": "gateway", "test": CORRENTE["test"], "handler": mio,
                               "pi": aa[0] if aa else kk.get("payment_intent"),
                               "importo": aa[1] if len(aa) > 1 else kk.get("importo_cents"),
                               "chiave": aa[2] if len(aa) > 2 else kk.get("chiave_idem")})
                return vero_rimborsa(*aa, **kk)

            agganciato = False
            if vero_rimborsa is not None:
                try:
                    sp.rimborsa = rimborsa
                    agganciato = True
                except Exception:
                    agganciato = False
            try:
                esito = vero(self, *a, **k)
            finally:
                if agganciato:
                    try:
                        if aveva:
                            sp.rimborsa = precedente
                        else:
                            del sp.rimborsa
                    except Exception:
                        pass
                _LOCALE.handler = prima
            try:
                stato, corpo = esito
                EVENTI.append({"tipo": "risposta", "test": CORRENTE["test"], "handler": mio,
                               "stato": stato,
                               "esito": corpo.get("stato") if isinstance(corpo, dict) else None})
            except Exception:
                pass
            return esito
        return handler

    cls._giornale = giornale
    cls._admin_rimborsi_dovuti = lista
    for nome in GATEWAY:
        setattr(cls, nome, _con_gateway(nome, getattr(cls, nome)))
    _INSTALLATO["fatto"] = True
    return True


class _RisultatoOsservato(unittest.TextTestResult):
    """Dice all'osservatore QUALE collaudo sta girando: senza, gli eventi non hanno un padrone
    e non si puo' dire «in questo collaudo verde la catena e' intera»."""

    def startTest(self, test):
        CORRENTE["test"] = test.id()
        super().startTest(test)

    def stopTest(self, test):
        super().stopTest(test)
        CORRENTE["test"] = None


# --------------------------------------------------------------------------------------
# 3. MISURA PRIMA SE STESSO (D18 punto 1)
# --------------------------------------------------------------------------------------
def _importa(sorgente, modulo):
    """Il sorgente IMPORTA il modulo A LIVELLO DI MODULO (`import X`, `from X import ...` fra le
    istruzioni di primo livello)? Albero sintattico, non sottostringa: un commento, una stringa
    o un docstring non contano. Stesso criterio di `mutazione_prodotto._importa_il_modulo`, con
    una differenza voluta: qui l'import dentro una FUNZIONE non conta. `test_pipeline_ci.py`
    importa `_rif_per_registro` dal server dentro due metodi, e con `ast.walk` veniva acceso
    come guardia delle catene (misurato: 325 collaudi estranei). Un banco del server lo importa
    in cima; chi lo importa in un metodo sta guardando un attrezzo."""
    try:
        albero = ast.parse(sorgente)
    except (SyntaxError, ValueError):
        return False
    for nodo in albero.body:
        if isinstance(nodo, ast.Import):
            if any(a.name == modulo or a.name.startswith(modulo + ".") for a in nodo.names):
                return True
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.module == modulo or (nodo.module or "").startswith(modulo + "."):
                return True
    return False


def guardie():
    """I moduli di test che nominano la lista dei rimborsi dovuti o il pulsante E importano il
    server (albero sintattico): e' la scelta di COSA accendere. La prova la fanno gli eventi.

    ⛔ L'import e' obbligatorio, e l'ha insegnato il primo giro con `--scrivi`: la sola
    sottostringa accendeva anche `test_pipeline_ci.py`, che nomina il pulsante in una stringa
    della guardia su QUESTO esame -- 325 collaudi in piu', 6 rossi estranei alla casella, e un
    motivo sbagliato scritto nella scheda. Chi non importa il server non puo' percorrere una
    strada: non e' una guardia di questa casella."""
    fuori = []
    for nome in sorted(os.listdir(RADICE)):
        if not (nome.startswith("test_") and nome.endswith(".py")):
            continue
        try:
            with io.open(os.path.join(RADICE, nome), encoding="utf-8") as f:
                sorgente = f.read()
        except Exception:
            continue
        if ("rimborsi_dovuti" in sorgente or "rimborsa_dovuto" in sorgente) \
                and _importa(sorgente, "fase83_server"):
            fuori.append(nome[:-3])
    return fuori


def precondizioni():
    """(tutte_ok, [(nome, ok, motivo)]). Un metro storto va scoperto dal metro."""
    fuori = []
    try:
        rimborsi, non_leggibili = strade_censite()
        fuori.append(("le strade si contano dal codice", bool(rimborsi),
                      "%d chiamate, %d causali distinte" % (len(rimborsi), len(dict(rimborsi)))
                      if rimborsi else "NESSUNA strada trovata: o `_giornale` e' stato "
                                       "rinominato, o il censimento non sa piu' leggere il "
                                       "codice. Il vuoto non e' un valore (sbaglio S1)"))
        fuori.append(("ogni `tipo` del giornale e' leggibile", not non_leggibili,
                      "righe con tipo non letterale: %r" % (non_leggibili,)
                      if non_leggibili else "nessuna riga con `tipo` illeggibile"))
    except Exception as e:
        fuori.append(("le strade si contano dal codice", False, "%s: %s" % (type(e).__name__, e)))
        fuori.append(("ogni `tipo` del giornale e' leggibile", False, "censimento non eseguibile"))
    try:
        cls = _classe_del_server()
        fuori.append(("la classe del server con `_giornale` si trova", cls is not None,
                      cls.__name__ if cls is not None else "nessuna classe definisce `_giornale`: "
                                                            "l'osservatore non avrebbe dove agganciarsi"))
        if cls is not None:
            mancanti = [n for n in ("_admin_rimborsi_dovuti",) + GATEWAY if not hasattr(cls, n)]
            fuori.append(("lista e pulsanti esistono sul server", not mancanti,
                          "mancano: %r" % (mancanti,) if mancanti else "lista + %s" % ", ".join(GATEWAY)))
    except Exception as e:
        fuori.append(("la classe del server con `_giornale` si trova", False, str(e)))
    g = guardie()
    fuori.append(("almeno una guardia nomina la lista o il pulsante", bool(g),
                  "%d moduli: %s" % (len(g), ", ".join(g)) if g else "NESSUN modulo di test nomina "
                                                                      "la lista: non c'e' niente da accendere"))
    fuori.append(("l'E2E contro Stripe di prova esiste", os.path.isfile(E2E), E2E))
    try:
        impronta = scheda.impronta_del_blocco(BLOCCO_SOLDI)
        fuori.append(("il blocco ha un'impronta", bool(impronta),
                      impronta or "il piano non si legge: una misura senza ancoraggio non vale"))
    except Exception as e:
        fuori.append(("il blocco ha un'impronta", False, str(e)))
    return all(ok for _, ok, _ in fuori), fuori


# --------------------------------------------------------------------------------------
# 4. IL GIRO E LA MISURA
# --------------------------------------------------------------------------------------
_GIRO = {}


def giro():
    """Accende le guardie UNA volta, con l'osservatore installato, e smista gli esiti."""
    if _GIRO:
        return _GIRO
    del EVENTI[:]
    caricatore = unittest.TestLoader()
    suite = unittest.TestSuite()
    for n in guardie():
        suite.addTests(caricatore.loadTestsFromName(n))
    flusso = io.StringIO()
    esito = unittest.TextTestRunner(stream=flusso, verbosity=1,
                                    resultclass=_RisultatoOsservato).run(suite)
    rossi = set(t.id() for t, _ in list(esito.failures) + list(esito.errors))
    saltati = set(t.id() for t, _ in esito.skipped)
    _GIRO.update({"eseguiti": esito.testsRun, "rossi": sorted(rossi),
                  "saltati": sorted(saltati), "testo": flusso.getvalue(),
                  "verdi": set(t for t in set(e["test"] for e in EVENTI if e.get("test"))
                               if t not in rossi and t not in saltati)})
    return _GIRO


def _catena(test, scrittura, eventi):
    """Lo stato della catena di UNA scrittura dentro UN collaudo, letto dagli eventi in ordine.
    Torna (stato, dettaglio)."""
    rif, importo = scrittura["rif"], scrittura["importo"]
    dopo = [e for e in eventi if e["test"] == test]
    # la strada che restituisce da se': scrive e, nella stessa chiamata, il gateway riceve X
    h = scrittura.get("handler")
    if h and h[0] in GATEWAY:
        for e in dopo:
            if e["tipo"] == "gateway" and e.get("handler") == h and e.get("importo") == importo:
                return TORNA_DIRETTA, "gateway: pi=%s importo=%s" % (e.get("pi"), importo)
        return NON_ESCE, "scritta in %s ma il gateway non ha ricevuto %s" % (h[0], importo)
    # le strade che passano dal pulsante
    riga_vista, pi_visto = None, None
    for e in dopo:
        if e["tipo"] == "lettura":
            for r in e["righe"]:
                if r["rif"] == rif and r["importo"] == importo:
                    riga_vista = r
                    if r["bottone"]:
                        pi_visto = r["pi"]
    if riga_vista is None:
        return NON_IN_LISTA, "nessuna lettura della lista mostra %s con %s" % (rif, importo)
    if not pi_visto:
        return MANUALE, "manca: %s" % ", ".join(riga_vista["manca"] or ["?"])
    indice_gateway = None
    for i, e in enumerate(dopo):
        if (e["tipo"] == "gateway" and e.get("pi") == pi_visto and e.get("importo") == importo
                and e.get("handler") and e["handler"][0] == "_admin_rimborsa_dovuto"):
            indice_gateway = i
            break
    if indice_gateway is None:
        return NON_ESCE, "in lista col pulsante (pi=%s), ma nessuna pressione ha raggiunto il gateway" % pi_visto
    for e in dopo[indice_gateway + 1:]:
        if e["tipo"] == "lettura" and rif not in e["rifs"]:
            return TORNA_PULSANTE, "gateway: pi=%s importo=%s; poi la riga e' uscita" % (pi_visto, importo)
    return NON_ESCE, "il gateway ha ricevuto %s ma nessuna lettura successiva la mostra uscita" % importo


_FORZA = {TORNA_DIRETTA: 5, TORNA_PULSANTE: 5, MANUALE: 4, NON_ESCE: 3, NON_IN_LISTA: 2,
          NON_MISURATA: 1}


def misura():
    """Per ogni strada censita, lo stato migliore raggiunto in un collaudo VERDE."""
    mappa = strade()
    g = giro()
    verdi = g["verdi"]
    esiti = {c: {"stato": NON_MISURATA, "dettaglio": "", "collaudo": None, "funzione": None}
             for c in mappa}
    fuori_censimento = set()
    for e in EVENTI:
        if e["tipo"] != "scrittura" or e["test"] not in verdi:
            continue
        causale = _quale_strada(e["causale"], mappa)
        if causale is None:
            fuori_censimento.add(str(e["causale"]))
            continue
        stato, dettaglio = _catena(e["test"], e, EVENTI)
        if _FORZA[stato] > _FORZA[esiti[causale]["stato"]]:
            esiti[causale] = {"stato": stato, "dettaglio": dettaglio, "collaudo": e["test"],
                              "funzione": "%s:%s" % (e["funzione"], e["riga"])}
    return esiti, sorted(fuori_censimento)


def e2e():
    """L'E2E contro Stripe di PROVA, in un processo a se'. (verde, righe)."""
    if not os.path.isfile(FILE_CHIAVE):
        return None, ["chiave di PROVA assente (%s): l'uscita vera non e' stata vista" % FILE_CHIAVE]
    try:
        p = subprocess.run([sys.executable, E2E], cwd=RADICE, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=900)
    except Exception as exc:
        return False, ["E2E non eseguibile: %s: %s" % (type(exc).__name__, exc)]
    testo = p.stdout.decode("utf-8", "replace")
    passi = [r.strip() for r in testo.splitlines() if r.strip().startswith(("OK ", "ROSSO"))]
    return p.returncode == 0, ["uscita %d, passi %d (rossi %d)" % (
        p.returncode, len(passi), sum(1 for r in passi if r.startswith("ROSSO")))] + passi


# --------------------------------------------------------------------------------------
# 5. L'AUTOPROVA (D18 punto 2): si vede perdere una strada, e ritrovarla
# --------------------------------------------------------------------------------------
def inietta_il_guasto():
    """Il difetto del 2026-08-16, rifatto a RUNTIME: una strada non scrive nel giornale, quindi
    non arriva in lista e nessuno rimborsa. Qui e' la cancellazione host. ⛔ Nessun `fase*.py`
    viene toccato (B4): si avvolge l'attributo della classe importata, dentro questo processo."""
    cls = _classe_del_server()
    vero = cls._giornale

    def muto(self, *a, **k):
        if k.get("tipo") == "rimborso" and k.get("causale") == STRADA_DEL_GUASTO:
            return None
        return vero(self, *a, **k)
    cls._giornale = muto


def _righe_strade(testo):
    """{causale: stato} dalle righe `STRADA|causale|stato` di una passata."""
    fuori = {}
    for riga in testo.splitlines():
        if riga.startswith("STRADA|"):
            pezzi = riga.split("|", 2)
            if len(pezzi) == 3:
                fuori[pezzi[1]] = pezzi[2].strip()
    return fuori


def autoprova():
    """Due passate IN PROCESSI NUOVI, senza E2E: col guasto la strada dell'host deve
    smettere di tornare e TUTTE le altre restare come sono; sana, deve tornare."""
    io_stesso = os.path.abspath(__file__)
    righe, esiti = [], {}
    for etichetta, extra in (("col guasto dentro", ["--con-guasto", "--senza-e2e"]),
                             ("a macchina SANA", ["--senza-e2e"])):
        e = subprocess.run([sys.executable, io_stesso] + extra, cwd=RADICE,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        testo = e.stdout.decode("utf-8", "replace")
        esiti[etichetta] = _righe_strade(testo)
        righe.append("   %-20s uscita=%d · strade lette: %d"
                     % (etichetta, e.returncode, len(esiti[etichetta])))
    guasto, sano = esiti["col guasto dentro"], esiti["a macchina SANA"]
    riuscita = True
    if not sano or set(sano) != set(guasto):
        righe.append("      ⛔ le due passate non descrivono le stesse strade (%d vs %d)"
                     % (len(sano), len(guasto)))
        riuscita = False
    else:
        if sano.get(STRADA_DEL_GUASTO) not in STATI_CHE_TORNANO:
            righe.append("      ⛔ a macchina sana la strada dell'host NON torna: %r"
                         % (sano.get(STRADA_DEL_GUASTO),))
            riuscita = False
        if guasto.get(STRADA_DEL_GUASTO) in STATI_CHE_TORNANO:
            righe.append("      ⛔ col guasto dentro la strada dell'host torna lo stesso: l'esame "
                         "non l'ha vista sparire")
            riuscita = False
        altre = [c for c in sano if c != STRADA_DEL_GUASTO and sano[c] != guasto[c]]
        if altre:
            righe.append("      ⛔ il guasto su UNA strada ha cambiato l'esito di altre: %r" % (altre,))
            riuscita = False
    righe.append("   %s" % ("atteso: la strada dell'host sparisce col guasto e torna sana; le altre non "
                            "cambiano" if riuscita else "⛔ NON E' QUELLO CHE DOVEVA SUCCEDERE"))
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
    print("🧾 ESAME DEL BLOCCO SOLDI — casella 2: i soldi tornano da OGNI strada")
    print("=" * 86)

    if "--autoprova" in argv:
        print("🔁 AUTOPROVA — l'esame si vede perdere una strada col guasto, e ritrovarla (D18 punto 2)")
        riuscita, righe = autoprova()
        for r in righe:
            print(r)
        _stampa_non_guarda()
        print("=" * 86)
        print("VERDETTO: %s" % ("✅ l'esame grida col guasto e tace a macchina sana" if riuscita
                                else "⛔ L'ESAME NON E' AFFIDABILE — non si comporta come promette"))
        return 0 if riuscita else 1

    if "--con-guasto" in argv and "--scrivi" in argv:
        # ⛔ Un `if`, non un commento: registrare la misura di una macchina rotta di proposito
        #    e' il barare che D18 vieta (stessa cura di `esame_soldi.py`).
        print("⛔ FERMO: `--con-guasto` non scrive. Serve a vedere l'esame perdere una strada;")
        print("   registrare quel rosso metterebbe nella scheda una macchina rotta apposta.")
        return 2

    tutte_ok, righe = precondizioni()
    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    for nome, ok, motivo in righe:
        print("  %-9s %-46s %s" % ("OK" if ok else "⛔ NO", nome, motivo))
    if not tutte_ok:
        print("-" * 86)
        print("VERDETTO: ⛔ FERMO — una precondizione non regge, quindi NON misuro e NON")
        print("scrivo niente. Un numero prodotto da un metro storto e' peggio di nessun numero.")
        _stampa_non_guarda()
        print("=" * 86)
        return 2

    if not installa_osservatore():
        print("VERDETTO: ⛔ FERMO — l'osservatore non si installa: niente da misurare")
        return 2
    if "--con-guasto" in argv:
        print("⚠️  PASSATA COL GUASTO DENTRO: la cancellazione host NON scrive nel giornale")
        inietta_il_guasto()

    print("")
    esiti, fuori = misura()
    g = giro()
    print("GUARDIE ACCESE: %s" % ", ".join(guardie()))
    print("  collaudi eseguiti %d · rossi %d · saltati %d · eventi osservati %d"
          % (g["eseguiti"], len(g["rossi"]), len(g["saltati"]), len(EVENTI)))
    for t in g["rossi"]:
        print("  ROSSO  %s" % t)
    for t in g["saltati"]:
        print("  SALTATO  %s" % t)
    print("")
    print("LE STRADE (dal censimento: %d), e cosa ha visto l'osservatore in un collaudo VERDE:" % len(esiti))
    tornano = 0
    for causale in sorted(esiti):
        r = esiti[causale]
        if r["stato"] in STATI_CHE_TORNANO:
            tornano += 1
        print("STRADA|%s|%s" % (causale, r["stato"]))
        if r["collaudo"]:
            print("      collaudo: %s   (scrittura in %s)" % (r["collaudo"], r["funzione"]))
        if r["dettaglio"]:
            print("      %s" % r["dettaglio"])
    for c in fuori:
        print("  ⚠️ scrittura con causale FUORI censimento: %r (una strada nuova? il censimento "
              "deve gridare per primo)" % c)
    print("STRADE_TORNANO=%d/%d" % (tornano, len(esiti)))

    print("")
    if "--con-guasto" in argv or "--senza-e2e" in argv:
        e2e_verde, righe_e2e = None, ["non eseguito (%s): l'uscita vera non e' stata vista"
                                      % ("--con-guasto" if "--con-guasto" in argv else "--senza-e2e")]
    else:
        print("L'USCITA VERA, GIUDICATA DA STRIPE DI PROVA (collaudi/e2e_rimborso_stripe.py)...")
        e2e_verde, righe_e2e = e2e()
    print("E2E: %s" % ("VERDE" if e2e_verde else ("NON ESEGUITO" if e2e_verde is None else "⛔ ROSSO")))
    for r in righe_e2e:
        print("      %s" % r)
    passi_e2e = sum(1 for r in righe_e2e if r.startswith(("OK ", "ROSSO")))

    motivi = []
    for causale in sorted(esiti):
        if esiti[causale]["stato"] not in STATI_CHE_TORNANO:
            motivi.append("«%s»: %s" % (causale, esiti[causale]["stato"]))
    if fuori:
        motivi.append("scritture fuori censimento: %s" % ", ".join(fuori))
    if g["rossi"]:
        motivi.append("%d guardie rosse" % len(g["rossi"]))
    if e2e_verde is None:
        motivi.append("E2E contro Stripe di prova non eseguito")
    elif not e2e_verde:
        motivi.append("E2E contro Stripe di prova ROSSO")
    verde = not motivi
    denominatore = len(esiti) + passi_e2e
    motivo = "; ".join(motivi)

    print("")
    print("VERDETTO: %s — strade che tornano %d/%d, E2E %s, denominatore %d"
          % ("✅ VERDE" if verde else "⛔ ROSSO", tornano, len(esiti),
             "verde" if e2e_verde else "non verde", denominatore))
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
