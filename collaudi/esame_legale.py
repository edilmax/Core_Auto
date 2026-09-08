"""L'ESAME DELLE CASELLE 1 E 2 DEL BLOCCO 5 (LEGALE E CONFORMITA') — le tre spunte e le lingue dei testi.

    python collaudi/esame_legale.py                   misura e MOSTRA le due caselle (in-process, niente rete)
    python collaudi/esame_legale.py --scrivi          misura e SCRIVE le due caselle nella scheda (anche un
                                                      rosso, col suo motivo)
    python collaudi/esame_legale.py --casella spunte|lingue [--scrivi]
    python collaudi/esame_legale.py --con-guasto      due guasti costruiti (il pulsante del browser senza
                                                      `disabled`; il server che serve l'italiano a chi chiede
                                                      il tedesco dichiarandolo tedesco): deve gridare, NON scrive
    python collaudi/esame_legale.py --autoprova       il giudizio sui passi, nelle due direzioni

⛔ I TESTI DELLE CASELLE NON SI RICOPIANO: si leggono da `collaudi/piano.py` (sono la chiave della scheda).
   Qui si cercano per SOTTOSTRINGA (`MARCHE`), una casella per marca, UNA sola nel blocco.

COSA MISURA, dichiarato (D18) — decisione della chat A il 2026-09-07 col mandato di B, rovesciabile:

CASELLA «spunte» — il browser blocca il pulsante e il server rifiuta con 422
  SERVER   sul sistema VERO (fase81 crea_sistema + fase83 crea_router, cartella temporanea) la rotta
           /api/host/registrazione con OGNI combinazione di spunte mancanti (le 7 con almeno un False, le 3 con
           il campo ASSENTE, e i valori «falsi ma non booleani»: "false", "0", 0, None, []) risponde 422
           `consensi_mancanti` col nome esatto delle mancanti, senza token e SENZA creare l'account (il registro
           host conta gli stessi host di prima); con tutte e tre -> 201. Stessa prova su /api/host/riaccetta.
  BROWSER  i DUE moduli di registrazione che il browser puo' usare, letti dal FILE e dalla FUNZIONE che li
           producono, mai a memoria: `deploy/host.html` (tre caselle con id `au_terms/au_clausole/au_privacy`,
           pulsante `btnRegister` con `disabled` gia' nel markup, lo script che lo tiene bloccato finche'
           `consensiMancanti()` non e' vuoto, la chiamata che manda le tre chiavi) e la pagina `/entra-host`
           (prodotta da `fase83.pagina_login_gate("host", ...)`: tre caselle c1/c2/c3 e il controllo
           `.checked` su tutte e tre PRIMA del `fetch` della registrazione), in ogni lingua servita.

CASELLA «lingue» — i due documenti si leggono in ogni lingua che il sito promette
  DICHIARATE  l'UNIONE di cio' che dichiara il codice: `fase185.LINGUE`, `fase61.LINGUE_SUPPORTATE`, e le liste
              `LINGUE` scritte in `deploy/termini.html` e `deploy/privacy.html` (lette con un'espressione
              regolare dal file). Se una fonte dichiara una lingua che un'altra non ha, e' un passo rosso.
  SERVITE     per ogni documento (termini, privacy) e ogni lingua dichiarata, la rotta VERA
              /api/legale/documento?doc=..&lang=.. risponde 200 con `lang` == la lingua chiesta, `tradotto`
              True, un testo non vuoto che porta la versione, e DIVERSO dal testo di ogni altra lingua (un
              ripiego silenzioso sull'italiano o sull'inglese produrrebbe due lingue con lo stesso testo);
              una lingua sconosciuta ripiega sull'INGLESE e lo DICHIARA (`lang` en, `tradotto` False);
              `lingue` nella risposta == le dichiarate.
  ANELLO      le due pagine `deploy/termini.html` e `deploy/privacy.html` chiamano DAVVERO
              /api/legale/documento (il modo di rompersi n.2: il pezzo perfetto e non collegato).

Denominatore = passi eseguiti per casella. Una situazione senza passi e' ROSSA (S7).
⛔ D18: `precondizioni()` ferma il giro; `--autoprova` e `--con-guasto`; `NON_GUARDA`; guardia
   `test_pipeline_ci.TestLEsameLegaleNonPuoBARARE`. AMBIENTE INTATTO: `os.environ` confrontato per intero
   prima e dopo (il sistema locale non lo tocca; se lo toccasse, e' un passo rosso).
"""
import io
import itertools
import json
import os
import re
import shutil
import sys
import tempfile

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

BLOCCO = 5
MARCHE = {"spunte": "3 spunte obbligatorie", "lingue": "leggibili in tutte le lingue"}
COMANDI = {k: "python collaudi/esame_legale.py --casella %s --scrivi" % k for k in MARCHE}
SITUAZIONI = {"spunte": ("server", "browser"), "lingue": ("dichiarate", "servite", "anello")}
SPUNTE = ("accetta_termini", "accetta_clausole", "accetta_privacy")
FALSI_NON_BOOLEANI = ("false", "0", 0, None, [])
PASSWORD_DI_PROVA = "password1"          # solo per il sistema locale: nessun conto vero
HDR = {"X-Forwarded-For": "203.0.113.9", "User-Agent": "esame_legale/prova"}
PASSI = {"spunte": [], "lingue": []}

NON_GUARDA = (
    "se un browser VERO rispetti `disabled`: qui si legge il markup e lo script che lo impostano, non si "
    "esegue JavaScript (e' lo strato di esperienza; la difesa vera e' il 422 del server, misurato)",
    "la QUALITA' delle traduzioni e la loro conformita' legale: la casella 3 del blocco («un avvocato vero») "
    "non la puo' dire una macchina; qui si misura che ogni lingua dichiarata riceve un testo suo e dichiarato",
    "il contratto host (/api/legale/contratto-host, fase163): la casella nomina termini e privacy",
    "le email e le pagine dell'ospite in lingua: sono altre caselle (blocco 6) e altre guardie",
    "la prova firmata HMAC delle accettazioni (fase163): e' guardata da test_consensi_blindati, qui si pretende "
    "solo che senza le tre spunte l'account NON nasca",
    "il campo `tradotto` per una lingua SCONOSCIUTA: fase83 `_lingua` normalizza a «en» PRIMA di chiamare fase185, "
    "quindi la risposta dice `tradotto: true` anche a chi ha chiesto «xx» (misurato il 2026-09-07); la casella parla "
    "delle lingue DICHIARATE e qui si pretende solo che il ripiego sia l'inglese e sia scritto in `lang`",
)


def passo(casella, situazione, nome, ok, dettaglio=""):
    PASSI[casella].append((situazione, nome, bool(ok), dettaglio))
    print("  %s  [%s/%s] %s%s" % ("OK  " if ok else "ROSSO", casella, situazione, nome,
                                   ("  -> " + dettaglio) if dettaglio else ""))
    return bool(ok)


# --------------------------------------------------------------------------------------
# IL GIUDIZIO (puro)
# --------------------------------------------------------------------------------------
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
        raise RuntimeError("nel blocco %d trovo %d caselle con «%s»: ne serve UNA"
                           % (BLOCCO, len(trovate), MARCHE[casella]))
    return trovate[0]


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
    try:
        from fase61_localizzazione import LINGUE_SUPPORTATE  # noqa: F401
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema  # noqa: F401
        from fase83_server import crea_router, pagina_login_gate  # noqa: F401
        from fase185_testi_legali import LINGUE  # noqa: F401
        fuori.append(("il sistema, il router, la pagina d'ingresso e i testi legali si importano", True, ""))
    except Exception as e:
        fuori.append(("il sistema, il router, la pagina d'ingresso e i testi legali si importano", False,
                      "%s: %s" % (type(e).__name__, e)))
    for nome in ("host.html", "termini.html", "privacy.html"):
        p = os.path.join(RADICE, "deploy", nome)
        fuori.append(("deploy/%s esiste" % nome, os.path.isfile(p), p))
    return all(ok for _, ok, _ in fuori), fuori


# --------------------------------------------------------------------------------------
# IL SISTEMA LOCALE (vero, senza Stripe: qui non si paga niente)
# --------------------------------------------------------------------------------------
class Sistema(object):

    def __init__(self, d):
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase83_server import crea_router
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"L" * 32, con_registrazione_host=True,
            db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
            db_accettazioni=d + "/a.db"))
        self.router = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")
        self._n = 0

    def g(self, metodo, path, corpo=None, headers=None, query=None):
        return self.router.gestisci(metodo, path, query or {},
                                    json.dumps(corpo) if corpo is not None else None, headers or HDR)

    def registra(self, extra=None, togli=()):
        from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
        self._n += 1
        corpo = {"email": "h%d@esame.it" % self._n, "password": PASSWORD_DI_PROVA,
                 "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
                 "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE}
        corpo.update(extra or {})
        for k in togli:
            corpo.pop(k, None)
        return self.g("POST", "/api/host/registrazione", corpo)

    def conta_host(self):
        return self.sis.registro_host.conta_host()


def _leggi(nome):
    with io.open(os.path.join(RADICE, "deploy", nome), encoding="utf-8", errors="replace") as f:
        return f.read()


def lingue_dichiarate_in(pagina_html):
    """Le lingue della lista `LINGUE = [['it', ...], ['en', ...]]` scritta nella pagina."""
    m = re.search(r"const LINGUE\s*=\s*\[(.*?)\];", pagina_html, re.S)
    return tuple(re.findall(r"\[\s*'([a-z]{2})'\s*,", m.group(1))) if m else ()


# --------------------------------------------------------------------------------------
# CASELLA «spunte»
# --------------------------------------------------------------------------------------
def _breve(st, d):
    """Il dettaglio di una risposta SENZA il gettone (un registro non porta credenziali)."""
    d = d if isinstance(d, dict) else {}
    return "http=%s errore=%r mancanti=%r token=%s" % (st, d.get("errore"), d.get("mancanti"),
                                                       "presente" if d.get("token") else "assente")


def misura_spunte_server(s):
    print("\n--- SPUNTE / SERVER: ogni combinazione mancante -> 422, nessun account ---")
    prima = s.conta_host()
    st, d = s.registra()
    passo("spunte", "server", "con tutte e tre le spunte l'account nasce (201, token)",
          st == 201 and bool((d or {}).get("token")) and s.conta_host() == prima + 1, "http=%s" % st)
    prima = s.conta_host()
    for mancanti in itertools.chain.from_iterable(itertools.combinations(SPUNTE, n) for n in (1, 2, 3)):
        st, d = s.registra({k: False for k in mancanti})
        d = d if isinstance(d, dict) else {}
        passo("spunte", "server", "False su %s -> 422 consensi_mancanti con ESATTAMENTE quelle" % "+".join(mancanti),
              st == 422 and d.get("errore") == "consensi_mancanti" and sorted(d.get("mancanti", [])) == sorted(mancanti)
              and "token" not in d, _breve(st, d))
    for k in SPUNTE:
        st, d = s.registra(togli=(k,))
        d = d if isinstance(d, dict) else {}
        passo("spunte", "server", "campo %s ASSENTE -> 422 e lo nomina" % k,
              st == 422 and k in d.get("mancanti", []), _breve(st, d))
    passo("spunte", "server", "dopo i rifiuti (False e assenti) il registro host conta gli stessi host di prima",
          s.conta_host() == prima, "prima=%d dopo=%d" % (prima, s.conta_host()))
    prima = s.conta_host()
    for v in FALSI_NON_BOOLEANI:
        st, d = s.registra({"accetta_clausole": v})
        d = d if isinstance(d, dict) else {}
        passo("spunte", "server", "accetta_clausole=%r (falso ma non booleano) -> 422" % (v,),
              st == 422 and "accetta_clausole" in d.get("mancanti", []), _breve(st, d))
    passo("spunte", "server", "dopo i valori falsi-non-booleani il registro host conta gli stessi host di prima",
          s.conta_host() == prima, "prima=%d dopo=%d" % (prima, s.conta_host()))
    st, d = s.registra()
    tk = {"X-Host-Token": (d or {}).get("token", "")}
    tk.update(HDR)
    for k in SPUNTE:
        corpo = {x: True for x in SPUNTE}
        corpo[k] = False
        st2, d2 = s.g("POST", "/api/host/riaccetta", corpo, tk)
        d2 = d2 if isinstance(d2, dict) else {}
        passo("spunte", "server", "riaccetta senza %s -> 422 consensi_mancanti" % k,
              st2 == 422 and d2.get("errore") == "consensi_mancanti" and k in d2.get("mancanti", []),
              _breve(st2, d2))


def misura_spunte_browser(con_guasto=False):
    print("\n--- SPUNTE / BROWSER: il markup e lo script letti dal file e dalla funzione vera ---")
    html = _leggi("host.html")
    if con_guasto:
        html = html.replace('id="btnRegister" data-i18n="b_register" disabled', 'id="btnRegister" data-i18n="b_register"')
    ids = ("au_terms", "au_clausole", "au_privacy")
    caselle = [bool(re.search(r'<input[^>]*type="checkbox"[^>]*id="%s"' % i, html)) for i in ids]
    passo("spunte", "browser", "host.html: tre caselle distinte %s" % (ids,), all(caselle), "trovate=%r" % (caselle,))
    m = re.search(r'<button[^>]*id="btnRegister"[^>]*>', html)
    passo("spunte", "browser", "host.html: il pulsante «Registrati» nasce con `disabled` nel markup",
          bool(m) and " disabled" in m.group(0), (m.group(0)[:120] if m else "pulsante non trovato"))
    lista = re.search(r"var AU_CONSENSI\s*=\s*\[([^\]]*)\]", html)
    dichiarate = tuple(re.findall(r"'([a-z_]+)'", lista.group(1))) if lista else ()
    passo("spunte", "browser", "host.html: lo script sorveglia ESATTAMENTE le tre caselle (AU_CONSENSI)",
          sorted(dichiarate) == sorted(ids), "AU_CONSENSI=%r" % (dichiarate,))
    fn = re.search(r"function aggiornaTastoRegistra\(\)\s*\{(.*?)\n\}", html, re.S)
    corpo_fn = fn.group(1) if fn else ""
    passo("spunte", "browser", "host.html: `aggiornaTastoRegistra` imposta `disabled` da `consensiMancanti()`",
          "consensiMancanti()" in corpo_fn and "b.disabled=manca" in corpo_fn, corpo_fn.strip()[:100])
    passo("spunte", "browser", "host.html: ogni casella ha l'ascoltatore `change` che richiama il controllo",
          bool(re.search(r"AU_CONSENSI\.forEach\(.*?addEventListener\('change',\s*aggiornaTastoRegistra\)", html, re.S)))
    chiamata = re.search(r"authPost\('/api/host/registrazione',\s*\{(.*?)\}", html, re.S)
    inviate = re.findall(r"(accetta_[a-z]+):true", chiamata.group(1)) if chiamata else []
    passo("spunte", "browser", "host.html: la chiamata di registrazione manda le tre chiavi a true",
          sorted(inviate) == sorted(SPUNTE), "inviate=%r" % (inviate,))
    from fase83_server import pagina_login_gate
    from fase61_localizzazione import LINGUE_SUPPORTATE
    for lingua in LINGUE_SUPPORTATE:
        pag = pagina_login_gate("host", "", lingua)
        tre = all(re.search(r'<input type="checkbox" id="%s">' % c, pag) for c in ("c1", "c2", "c3"))
        i_check = [pag.find("getElementById('%s').checked" % c) for c in ("c1", "c2", "c3")]
        i_fetch = pag.find("fetch('/api/host/registrazione'")
        passo("spunte", "browser", "/entra-host (%s): tre caselle c1/c2/c3 e il controllo `.checked` su tutte PRIMA del fetch" % lingua,
              tre and min(i_check) >= 0 and i_fetch > max(i_check),
              "caselle=%s controlli=%r fetch=%d" % (tre, i_check, i_fetch))


# --------------------------------------------------------------------------------------
# CASELLA «lingue»
# --------------------------------------------------------------------------------------
def lingue_dichiarate():
    from fase61_localizzazione import LINGUE_SUPPORTATE
    from fase185_testi_legali import LINGUE
    return {"fase185.LINGUE": tuple(LINGUE), "fase61.LINGUE_SUPPORTATE": tuple(LINGUE_SUPPORTATE),
            "deploy/termini.html": lingue_dichiarate_in(_leggi("termini.html")),
            "deploy/privacy.html": lingue_dichiarate_in(_leggi("privacy.html"))}


def misura_lingue(s, con_guasto=False):
    print("\n--- LINGUE: dichiarate (quattro fonti), servite dalla rotta vera, e l'anello delle pagine ---")
    fonti = lingue_dichiarate()
    unione = sorted(set(itertools.chain.from_iterable(fonti.values())))
    for nome, lista in fonti.items():
        passo("lingue", "dichiarate", "%s dichiara le stesse lingue dell'unione" % nome,
              bool(lista) and sorted(set(lista)) == unione, "%r" % (lista,))
    if con_guasto:
        import fase185_testi_legali as f185
        vera = f185.documento

        def storta(nome, lang="it"):
            d = vera(nome, "it")                              # IL GUASTO: l'italiano a tutti,
            d["lang"] = str(lang)[:2]                         # dichiarato come la lingua chiesta
            d["tradotto"] = True
            return d
        f185.documento = storta
    try:
        for doc in ("termini", "privacy"):
            testi = {}
            for lingua in unione:
                st, d = s.g("GET", "/api/legale/documento", None, None, {"doc": doc, "lang": lingua})
                d = d if isinstance(d, dict) else {}
                testi[lingua] = d.get("testo") or ""
                passo("lingue", "servite", "%s in «%s»: 200, lang dichiarata == chiesta, tradotto, testo con la versione" % (doc, lingua),
                      st == 200 and d.get("lang") == lingua and d.get("tradotto") is True
                      and len(testi[lingua]) > 200 and str(d.get("versione") or "") in testi[lingua],
                      "http=%s lang=%r tradotto=%r len=%d" % (st, d.get("lang"), d.get("tradotto"), len(testi[lingua])))
                passo("lingue", "servite", "%s in «%s»: la rotta dichiara come disponibili le lingue dell'unione" % (doc, lingua),
                      sorted(d.get("lingue") or []) == unione, "lingue=%r" % (d.get("lingue"),))
            uguali = [(a, b) for a in unione for b in unione if a < b and testi[a] and testi[a] == testi[b]]
            passo("lingue", "servite", "%s: ogni lingua ha un testo DIVERSO dalle altre (nessun ripiego silenzioso)" % doc,
                  not uguali, "coppie uguali=%r" % (uguali,))
            st, d = s.g("GET", "/api/legale/documento", None, None, {"doc": doc, "lang": "xx"})
            d = d if isinstance(d, dict) else {}
            passo("lingue", "servite", "%s per una lingua SCONOSCIUTA: ripiega sull'INGLESE (dichiarato in `lang`), mai sull'italiano" % doc,
                  st == 200 and d.get("lang") == "en" and d.get("testo") == testi.get("en") and testi.get("en") != testi.get("it"),
                  "lang=%r tradotto=%r" % (d.get("lang"), d.get("tradotto")))
    finally:
        if con_guasto:
            f185.documento = vera
    for nome in ("termini.html", "privacy.html"):
        pag = _leggi(nome)
        passo("lingue", "anello", "deploy/%s chiama /api/legale/documento e passa la lingua scelta" % nome,
              "/api/legale/documento" in pag and "lang=" in pag and "DOC = '%s'" % nome.split(".")[0] in pag)


# --------------------------------------------------------------------------------------
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
        casi.append(("%s: un passo fuori dalle situazioni" % casella, passi_finti(casella) + [("altro", "x", True, "")], False))
        for nome, passi, atteso in casi:
            verde, motivi, den = giudica(passi, situazioni)
            ok = verde == atteso
            riuscita = riuscita and ok
            righe.append("   %-44s -> %-6s (atteso %-6s) denominatore %d%s"
                         % (nome, "VERDE" if verde else "ROSSO", "VERDE" if atteso else "ROSSO", den,
                            "" if ok else "   ⛔ NON E' QUELLO CHE DOVEVA DIRE: %s" % "; ".join(motivi)))
    # il lettore delle lingue dichiarate in una pagina, nelle due direzioni
    finta = "const LINGUE = [['it','x'],['en','y'],\n ['ja','z']];"
    ok = lingue_dichiarate_in(finta) == ("it", "en", "ja") and lingue_dichiarate_in("niente") == ()
    riuscita = riuscita and ok
    righe.append("   %-44s -> %s" % ("lettore LINGUE delle pagine (due direzioni)", "OK" if ok else "⛔ ROTTO"))
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
    print("🧾 ESAME DEL BLOCCO 5 — legale: %s" % ", ".join("«%s»" % MARCHE[c] for c in scelte))
    print("=" * 86)

    if "--autoprova" in argv:
        print("🔁 AUTOPROVA — il giudizio si vede gridare e tacere su passi costruiti (D18 punto 2)")
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
        print("   rosso metterebbe nella scheda un pulsante sbloccato e una lingua finta apposta.")
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
        print("⚠️  PASSATA COI GUASTI DENTRO: pulsante senza `disabled`; italiano servito come ogni lingua")

    ambiente_prima = dict(os.environ)
    d = tempfile.mkdtemp()
    try:
        try:
            s = Sistema(d)
        except Exception as e:                           # noqa: BLE001 - un sistema rotto e' un rosso
            for c in scelte:
                passo(c, SITUAZIONI[c][0], "il sistema locale e' ESPLOSO", False, "%s: %s" % (type(e).__name__, e))
            s = None
        if s is not None:
            misure = {"spunte": ((("server", lambda: misura_spunte_server(s)),
                                  ("browser", lambda: misura_spunte_browser(con_guasto)))),
                      "lingue": ((("dichiarate", lambda: misura_lingue(s, con_guasto)),))}
            for c in scelte:
                for situazione, f in misure[c]:
                    try:
                        f()
                    except Exception as e:               # noqa: BLE001 - una misura rotta e' un rosso
                        passo(c, situazione, "la misura e' ESPLOSA", False, "%s: %s" % (type(e).__name__, e))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    for c in scelte:
        passo(c, SITUAZIONI[c][0], "l'ambiente (os.environ) e' identico a prima della misura",
              dict(os.environ) == ambiente_prima,
              "cambiate=%r" % (sorted(k for k in set(os.environ) | set(ambiente_prima)
                                      if os.environ.get(k) != ambiente_prima.get(k)),))

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
            riga = scheda.registra(condizione(c), esito=verde, denominatore=denominatore,
                                   comando=COMANDI[c], ordine=BLOCCO, motivo="; ".join(motivi) or None)
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
