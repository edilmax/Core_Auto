"""
CORE_AUTO - Fase 202: GLI INVARIANTI SUGLI ARCHIVI VERI -- il giro quotidiano in PRODUZIONE.

Nasce il 2026-09-04 dalla casella 6 del blocco SOLDI («gli invarianti sono verificati in
PRODUZIONE, non solo nei test»), con l'«autorizzato» del fondatore. Misurato nel codice vivo
prima di scrivere questo modulo: dei cinque invarianti di `fase199`, I3 e I4 erano controllati a
ogni prenotazione (guardia pre-commit in `fase83`), I1 solo quando qualcuno premeva il bottone
del bunker (`/api/bunker/invarianti`, che legge il solo I1), I2 e I5 da nessuna parte; il
Guardiano quotidiano (`fase186`) guardava otto stati impossibili, non questi cinque per nome.

COSA FA. Ogni giorno, dentro il giro del Guardiano (`fase83`, tick giornaliero), legge gli
archivi veri della cartella dati e verifica i CINQUE invarianti di `fase199` -- le stesse
funzioni pure dimostrate con Z3 e Hypothesis nei test, NON una copia riscritta qui:

  I1  nessuna notte sovraprenotata: nel libro dell'inventario `unita_occupate <= unita_totali`
      su ogni notte; e fra le prenotazioni PAGATE dello stesso alloggio nessuna sovrapposizione
      oltre la capienza (a una unita' decide `i1_doppia_conferma`, il nucleo dimostrato; a piu'
      unita' si contano le prenotazioni per notte contro `unita_totali` di quella notte);
  I2  bilancio dei pagamenti: per ogni prenotazione la somma degli INCASSI nel giornale non
      supera il totale dovuto (`corpo_json.totale_cents`), e se e' PAGATA la eguaglia;
  I3  prova prima del commit: nessuna prenotazione PAGATA senza `quote_token` -- la STESSA
      definizione della guardia a runtime di `fase83` (`prova_firmata = bool(quote_token)`);
  I4  denaro mai negativo: ogni colonna `*_cents` (e `minori` dei payout) di ogni tabella di
      ogni archivio e' >= 0;
  I5  escrow coerente: una garanzia `rilasciato` ha una prenotazione che lo giustifica.

COME TRADUCE gli stati del prodotto nel vocabolario di `fase199` (I5), dichiarato perche' e'
l'unico punto in cui questo modulo INTERPRETA invece di leggere:
      prenotazione 'pagato'           -> esito 'completata'      (il soggiorno c'e' stato o e' in
                                                                  corso e nessuno ha chiesto indietro
                                                                  i soldi: il rilascio e' giustificato)
      prenotazione 'rimborsato'       -> esito 'rimborsata'
      prenotazione 'cancellata_host'  -> esito 'cancellata_host'
      prenotazione assente            -> esito 'sconosciuta'     (VIOLAZIONE: garanzia senza prenotazione)
      qualunque altro stato           -> quello stato, tale e quale (VIOLAZIONE: non giustifica)
  Le garanzie 'in_garanzia', 'contestato', 'risolto', 'annullato' NON sono giudicate da I5 (il
  suo vocabolario e' rilasciato/trattenuto): le aperte le guarda il Guardiano (escrow bloccati,
  soldi su rimborsata).

COSA NON FA, dichiarato (D18 punto 3):
  - non scrive MAI: `PRAGMA query_only=1` su ogni connessione, e un archivio che non si apre e'
    un controllo CIECO (anomalia), mai «pulito»;
  - I2 non giudica le prenotazioni «paga in struttura»: il saldo non passa da noi e il giornale
    non puo' contenerlo; sono contate fra i NON ESEGUITI, con il numero;
  - non ripara niente: GRIDA nel registro (riga `INVARIANTI ARCHIVI`, letta anche dalla sonda
    esterna `collaudi/esame_produzione.py`) e riempie il rapporto del Guardiano, che manda
    l'email;
  - le tabelle le riconosce dal NOME (`pendenti`, `inventario`, `garanzia`, `payout`,
    `libro_giornale`): un archivio con un nome nuovo non viene letto, e lo dice nei `letti`.

Puro rispetto al sistema (riceve una cartella), stdlib, deterministico, tollerante allo schema.
"""
from __future__ import annotations

import datetime
import glob
import json
import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from fase199_invarianti import (STATI_OCCUPANTI, i1_doppia_conferma, i2_bilancio_pagamenti,
                                i3_prova_prima_del_commit, i4_denaro_non_negativo,
                                i5_escrow_coerente)

logger = logging.getLogger("core_auto.invarianti_archivi")

# La marca della riga di registro che la sonda esterna (`collaudi/esame_produzione.py`) cerca
# nel registro del container: se cambia qui deve cambiare anche li', e la guardia
# `test_fase202_invarianti_archivi` li tiene insieme.
MARCA = "INVARIANTI ARCHIVI"
CODICI = ("I1", "I2", "I3", "I4", "I5")
# La chiave sotto cui le violazioni entrano nel rapporto del Guardiano (`anomalie`): il
# riassunto dell'email la stampa cosi' com'e' (fase186 non la conosce per nome).
CHIAVE_ANOMALIA = "invarianti_violati"
TIMEOUT_SQLITE = 30          # standard del progetto (bug #36): sotto contesa aspetta, mai 'locked'
# Stati di `fase162` (pendenti) tradotti nel vocabolario di I5 (vedi il docstring).
_ESITO_DA_STATO = {"pagato": "completata", "rimborsato": "rimborsata",
                   "cancellata_host": "cancellata_host"}


def _apri_sola_lettura(percorso: str) -> sqlite3.Connection:
    """Una connessione che NON PUO' scrivere. Gira contro gli archivi vivi di produzione, in
    concorrenza col sito: `timeout` per aspettare il turno, `query_only` perche' una
    scansione che potesse scrivere non sarebbe una scansione."""
    con = sqlite3.connect(percorso, timeout=TIMEOUT_SQLITE)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=1")
    return con


def _tabelle(con: sqlite3.Connection) -> List[str]:
    return [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]


def _colonne(con: sqlite3.Connection, tabella: str) -> List[str]:
    return [c[1] for c in con.execute('PRAGMA table_info("%s")' % tabella.replace('"', '""'))]


def _intero(v: Any) -> Optional[int]:
    """Un intero vero (non bool, non stringa): altrimenti None. I4 giudica solo i numeri."""
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _notti(check_in: Any, check_out: Any) -> List[str]:
    """Le notti [check_in, check_out) come stringhe ISO. Lista vuota se le date non si leggono."""
    try:
        a = datetime.date.fromisoformat(str(check_in))
        b = datetime.date.fromisoformat(str(check_out))
    except (TypeError, ValueError):
        return []
    fuori = []
    g = a
    while g < b and len(fuori) < 400:            # 400 notti: piu' di un anno, tetto anti-runaway
        fuori.append(g.isoformat())
        g += datetime.timedelta(days=1)
    return fuori


def leggi_archivi(dir_dati: str) -> Dict[str, Any]:
    """Legge (sola lettura) tutto cio' che serve ai cinque invarianti. Ogni archivio e' isolato:
    uno rotto finisce in `ciechi` (col motivo nel registro) e gli altri si leggono lo stesso."""
    dati: Dict[str, Any] = {"prenotazioni": [], "inventario": [], "garanzie": [], "payout": [],
                            "giornale": [], "importi": {}, "archivi": 0, "ciechi": [],
                            "tabelle_lette": []}
    for percorso in sorted(glob.glob(os.path.join(dir_dati, "*.db"))):
        nome = os.path.basename(percorso)
        try:
            con = _apri_sola_lettura(percorso)
            try:
                dati["archivi"] += 1
                for t in _tabelle(con):
                    cols = _colonne(con, t)
                    # I4 su OGNI tabella: ogni colonna di denaro, di qualunque archivio
                    soldi = [c for c in cols if c.endswith("_cents") or c == "minori"]
                    if soldi:
                        # `rowid AS _riga`: senza l'alias, in una tabella con una chiave
                        # primaria intera (`seq` del giornale) la colonna torna col SUO nome
                        # e `r["rowid"]` non esiste -- visto al primo giro dei collaudi.
                        # noqa/nosec qui sotto: cio' che si interpola sono NOMI di tabella e di
                        # colonna letti da `sqlite_master`/`PRAGMA table_info` dell'archivio
                        # stesso, virgolettati e con le virgolette raddoppiate -- nessun dato
                        # dell'utente entra nel testo della query (stessa lettura una per una
                        # degli S608 prescritta da `ruff.toml`, come in fase162).
                        q = 'SELECT rowid AS _riga, %s FROM "%s"' % (  # nosec B608  # noqa: S608
                            ", ".join('"%s"' % c for c in soldi), t.replace('"', '""'))
                        for r in con.execute(q):
                            for c in soldi:
                                v = _intero(r[c])
                                if v is not None:
                                    dati["importi"]["%s.%s.%s#%s" % (nome, t, c, r["_riga"])] = v
                    if t == "pendenti" and {"riferimento", "alloggio_id", "check_in",
                                            "check_out", "stato"} <= set(cols):
                        dati["tabelle_lette"].append("%s.pendenti" % nome)
                        for r in con.execute("SELECT * FROM pendenti"):
                            k = r.keys()
                            dati["prenotazioni"].append({
                                "rif": r["riferimento"], "alloggio_id": r["alloggio_id"],
                                "check_in": r["check_in"], "check_out": r["check_out"],
                                "stato": r["stato"],
                                "quote_token": (r["quote_token"] if "quote_token" in k else ""),
                                "corpo_json": (r["corpo_json"] if "corpo_json" in k else "")})
                    elif t == "inventario" and {"alloggio_id", "giorno", "unita_totali",
                                                "unita_occupate"} <= set(cols):
                        dati["tabelle_lette"].append("%s.inventario" % nome)
                        for r in con.execute("SELECT alloggio_id, giorno, unita_totali, "
                                             "unita_occupate FROM inventario"):
                            dati["inventario"].append(dict(r))
                    elif t == "garanzia" and {"prenotazione_id", "stato"} <= set(cols):
                        dati["tabelle_lette"].append("%s.garanzia" % nome)
                        for r in con.execute("SELECT prenotazione_id, stato FROM garanzia"):
                            dati["garanzie"].append(dict(r))
                    elif t == "payout" and {"prenotazione_id", "host_id", "stato",
                                            "minori"} <= set(cols):
                        dati["tabelle_lette"].append("%s.payout" % nome)
                        for r in con.execute("SELECT prenotazione_id, host_id, stato, minori "
                                             "FROM payout"):
                            dati["payout"].append(dict(r))
                    elif t == "libro_giornale" and {"tipo", "riferimento",
                                                    "importo_cents"} <= set(cols):
                        dati["tabelle_lette"].append("%s.libro_giornale" % nome)
                        for r in con.execute("SELECT tipo, riferimento, importo_cents "
                                             "FROM libro_giornale"):
                            dati["giornale"].append(dict(r))
            finally:
                con.close()
        except Exception:
            # ⛔ La traccia e' l'unica cosa che distingue «corrotto» da «disco pieno» da
            #    «schema cambiato» (lezione di fase199, 2026-08-01): si registra e si va avanti.
            logger.error("invarianti archivi: archivio illeggibile (ISOLATO, resta CIECO): %s",
                         nome, exc_info=True)
            dati["ciechi"].append(nome)
    return dati


def _capienza(inventario: List[Dict[str, Any]]) -> Dict[Tuple[str, str], int]:
    return {(str(r["alloggio_id"]), str(r["giorno"])): int(r["unita_totali"] or 0)
            for r in inventario if _intero(r.get("unita_totali")) is not None}


def _giudica_i1(prenotazioni: List[Dict[str, Any]], inventario: List[Dict[str, Any]]
                ) -> Tuple[List[Any], List[str]]:
    viol: List[Any] = []
    note: List[str] = []
    # (a) il libro dell'inventario, notte per notte
    for r in inventario:
        tot, occ = _intero(r.get("unita_totali")), _intero(r.get("unita_occupate"))
        if tot is None or occ is None:
            continue
        if occ > tot:
            viol.append((r.get("alloggio_id"), r.get("giorno"),
                         "notte sovraprenotata: occupate %d > totali %d" % (occ, tot)))
    # (b) le prenotazioni PAGATE, per alloggio, contro la capienza
    cap = _capienza(inventario)
    per_alloggio: Dict[str, List[Dict[str, Any]]] = {}
    illeggibili = 0
    for p in prenotazioni:
        if p.get("stato") not in STATI_OCCUPANTI:
            continue
        if not _notti(p.get("check_in"), p.get("check_out")):
            illeggibili += 1
            continue
        per_alloggio.setdefault(str(p.get("alloggio_id")), []).append(p)
    if illeggibili:
        note.append("I1: %d prenotazioni pagate con date illeggibili, non giudicate" % illeggibili)
    for alloggio, ps in per_alloggio.items():
        capienze = [c for (a, _g), c in cap.items() if a == alloggio]
        massima = max(capienze) if capienze else 1
        if massima <= 1:
            # a UNA unita' decide il nucleo dimostrato con Z3
            viol.extend(i1_doppia_conferma([dict(p, unita=alloggio) for p in ps]))
            continue
        conta: Dict[str, List[Any]] = {}
        for p in ps:
            for notte in _notti(p["check_in"], p["check_out"]):
                conta.setdefault(notte, []).append(p["rif"])
        for notte, rifs in sorted(conta.items()):
            tot = cap.get((alloggio, notte), massima)
            if len(rifs) > tot:
                viol.append((alloggio, notte, "%d prenotazioni pagate su %d unita': %s"
                             % (len(rifs), tot, ", ".join(str(x) for x in rifs))))
    return viol, note


def _corpo(p: Dict[str, Any]) -> Dict[str, Any]:
    try:
        d = json.loads(p.get("corpo_json") or "{}")
        return d if isinstance(d, dict) else {}
    except (TypeError, ValueError):
        return {}


def _giudica_i2(prenotazioni: List[Dict[str, Any]], giornale: List[Dict[str, Any]]
                ) -> Tuple[List[Any], List[str]]:
    incassi: Dict[str, List[int]] = {}
    for r in giornale:
        if r.get("tipo") == "incasso":
            v = _intero(r.get("importo_cents"))
            incassi.setdefault(str(r.get("riferimento")), []).append(v if v is not None else -1)
    astratte = []
    in_struttura = 0
    for p in prenotazioni:
        c = _corpo(p)
        if c.get("modo_pagamento") == "in_struttura":
            in_struttura += 1           # il saldo lo incassa l'host di persona: non e' nel giornale
            continue
        dovuto = _intero(c.get("totale_cents"))
        if dovuto is None:
            dovuto = _intero(c.get("prezzo_guest_cents"))
        astratte.append({"rif": p.get("rif"), "stato": p.get("stato"),
                         "totale_dovuto_cents": dovuto if dovuto is not None else 0,
                         "pagamenti_cents": incassi.get(str(p.get("rif")), [])})
    note = []
    if in_struttura:
        note.append("I2: %d prenotazioni «paga in struttura» non giudicate (il saldo non passa "
                    "da noi, il giornale non puo' contenerlo)" % in_struttura)
    return i2_bilancio_pagamenti(astratte), note


def _giudica_i3(prenotazioni: List[Dict[str, Any]]) -> List[Any]:
    return i3_prova_prima_del_commit([{"rif": p.get("rif"), "stato": p.get("stato"),
                                       "prova_firmata": bool(p.get("quote_token"))}
                                      for p in prenotazioni])


def _giudica_i5(garanzie: List[Dict[str, Any]], prenotazioni: List[Dict[str, Any]]) -> List[Any]:
    stato_di = {str(p.get("rif")): p.get("stato") for p in prenotazioni}
    astratte = []
    for g in garanzie:
        if g.get("stato") != "rilasciato":
            continue
        rif = str(g.get("prenotazione_id"))
        st = stato_di.get(rif)
        esito = "sconosciuta" if st is None else _ESITO_DA_STATO.get(str(st), str(st))
        astratte.append({"rif": rif, "stato_garanzia": "rilasciato", "esito_prenotazione": esito})
    return i5_escrow_coerente(astratte)


def scansiona_archivi(dir_dati: str, *, ora: Any = None) -> Dict[str, Any]:
    """Il giro: legge, giudica coi cinque invarianti, GRIDA nel registro. Non solleva mai.
    Ritorna {violazioni, verificati, non_eseguiti, letti, ciechi, ts}."""
    ora_ts = int((ora or time.time)())
    dati = leggi_archivi(dir_dati)
    violazioni: Dict[str, List[Any]] = {}
    verificati: List[str] = []
    non_eseguiti: List[str] = []

    def _tenta(codice, f):
        try:
            esito = f()
            viol, note = esito if isinstance(esito, tuple) else (esito, [])
            verificati.append(codice)
            non_eseguiti.extend(note)
            if viol:
                violazioni[codice] = list(viol)
        except Exception:
            logger.error("invarianti archivi: %s non giudicabile (ISOLATO)", codice, exc_info=True)
            non_eseguiti.append("%s: il giudizio e' fallito (vedi registro)" % codice)

    _tenta("I1", lambda: _giudica_i1(dati["prenotazioni"], dati["inventario"]))
    if any(t.endswith(".libro_giornale") for t in dati["tabelle_lette"]):
        _tenta("I2", lambda: _giudica_i2(dati["prenotazioni"], dati["giornale"]))
    else:
        non_eseguiti.append("I2: manca il giornale (libro_giornale): il bilancio dei pagamenti "
                            "non e' stato verificato")
    _tenta("I3", lambda: _giudica_i3(dati["prenotazioni"]))
    _tenta("I4", lambda: i4_denaro_non_negativo(dati["importi"]))
    _tenta("I5", lambda: _giudica_i5(dati["garanzie"], dati["prenotazioni"]))

    letti = {"archivi": dati["archivi"], "prenotazioni": len(dati["prenotazioni"]),
             "notti": len(dati["inventario"]), "garanzie": len(dati["garanzie"]),
             "payout": len(dati["payout"]), "giornale": len(dati["giornale"]),
             "importi": len(dati["importi"])}
    rapporto = {"violazioni": violazioni, "verificati": verificati, "non_eseguiti": non_eseguiti,
                "letti": letti, "ciechi": list(dati["ciechi"]), "ts": ora_ts}
    riga = formatta_riga(rapporto)
    if violazioni:
        logger.error("%s -> VIOLATI: %r", riga, {k: len(v) for k, v in violazioni.items()})
    else:
        logger.info(riga)
    return rapporto


def formatta_riga(rapporto: Dict[str, Any]) -> str:
    """La riga del registro. UNA forma sola, condivisa con la sonda esterna che la legge."""
    letti = rapporto.get("letti") or {}
    return ("%s | verificati=%s | letti=%s | violazioni=%d | non_eseguiti=%d | ciechi=%d"
            % (MARCA, ",".join(rapporto.get("verificati") or []) or "-",
               " ".join("%s:%s" % (k, letti[k]) for k in sorted(letti)) or "-",
               sum(len(v) for v in (rapporto.get("violazioni") or {}).values()),
               len(rapporto.get("non_eseguiti") or []), len(rapporto.get("ciechi") or [])))


def con_invarianti(rapporto: Dict[str, Any], dir_dati: str) -> Dict[str, Any]:
    """Arricchisce il rapporto del Guardiano (fase186.scansiona) col giro sugli archivi:
    le violazioni diventano un'anomalia (email), gli archivi ciechi un controllo cieco, i
    non eseguiti restano dichiarati. Senza cartella dati: NON ESEGUITO, mai «pulito»."""
    ne = rapporto.setdefault("non_eseguiti", [])
    if not dir_dati or not os.path.isdir(dir_dati):
        ne.append("invarianti_archivi: nessuna cartella dati (db_finanza in memoria o assente): "
                  "i cinque invarianti NON sono stati verificati sugli archivi")
        return rapporto
    inv = scansiona_archivi(dir_dati)
    rapporto["invarianti"] = inv
    an = rapporto.setdefault("anomalie", {})
    aggiunte = 0
    if inv["violazioni"]:
        an[CHIAVE_ANOMALIA] = inv["violazioni"]
        aggiunte += sum(len(v) for v in inv["violazioni"].values())
    if inv["ciechi"]:
        an.setdefault("controllo_cieco", []).extend("invarianti_archivi:" + c for c in inv["ciechi"])
        aggiunte += len(inv["ciechi"])
    ne.extend("invarianti_archivi: " + m for m in inv["non_eseguiti"])
    if aggiunte:
        rapporto["conta"] = int(rapporto.get("conta") or 0) + aggiunte
        rapporto["pulito"] = False
    return rapporto


def giro_quotidiano(sistema: Any) -> Dict[str, Any]:
    """Il giro che il tick giornaliero di `fase83` chiama al posto del solo `scansiona`:
    Guardiano (fase186) + i cinque invarianti sugli archivi. Se questo pezzo fallisce, il
    Guardiano ha gia' fatto il suo giro e lo dice nel rapporto: mai un rapporto perso."""
    from fase186_guardiano import scansiona
    rapporto = scansiona(sistema)
    try:
        fin = getattr(getattr(sistema, "config", None), "db_finanza", "") or ""
        # `in`, non `fin and fin != ":memory:"`: quella forma aveva un mutante (`and` -> `or`)
        # EQUIVALENTE per costruzione, e un equivalente si toglie dal codice, non si dichiara.
        dati = "" if fin in ("", ":memory:") else os.path.dirname(fin)
        rapporto = con_invarianti(rapporto, dati)
    except Exception:
        logger.error("invarianti archivi: giro fallito (ISOLATO: il Guardiano prosegue)",
                     exc_info=True)
        rapporto.setdefault("non_eseguiti", []).append(
            "invarianti_archivi: il giro e' fallito (vedi registro): i cinque invarianti NON "
            "sono stati verificati")
    return rapporto
