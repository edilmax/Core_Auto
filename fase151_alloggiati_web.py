"""
CORE_AUTO - Fase 151: Export "Alloggiati Web" (Questura / Polizia di Stato).

Genera il file a larghezza fissa delle schedine alloggiati (adempimento IT per le strutture
ricettive) dai dati ospiti. GATED/IT-specifico (jurisdiction): attivo=False di default;
formato CONFIGURABILE. Record a campi fissi (168 char), uppercase ASCII, padding a spazi,
date GG/MM/AAAA. Solo capo/singolo/gruppo portano i campi documento. PURO/deterministico.
BLINDATO: ospite invalido → saltato; mai eccezione.

Le regole sono quelle del manuale del portale (CREAFILE.pdf, p. 4-7): `errori_schedina` dice
PERCHE' una schedina non si scrive, invece di scriverla con un dato falso. Con le tabelle
ufficiali (`carica_tabelle`: copie in deploy/alloggiati/, scaricate senza login dall'area
download del portale) controlla anche i codici di comuni, stati e documenti.
"""
from __future__ import annotations

import csv
import datetime
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional, Sequence

# (campo, lunghezza) nell'ordine del tracciato Alloggiati Web.
CAMPI = (
    ("tipo", 2), ("data_arrivo", 10), ("giorni", 2), ("cognome", 50), ("nome", 30),
    ("sesso", 1), ("data_nascita", 10), ("comune_nascita", 9), ("prov_nascita", 2),
    ("stato_nascita", 9), ("cittadinanza", 9), ("tipo_doc", 5), ("num_doc", 20),
    ("luogo_doc", 9),
)
LUNGHEZZA_RECORD = sum(l for _, l in CAMPI)   # 168

TIPO_ALLOGGIATO = {"singolo": "16", "capofamiglia": "17", "capogruppo": "18",
                   "familiare": "19", "membro_gruppo": "20"}
_CON_DOC = {"16", "17", "18"}
SESSO = {"m": "1", "f": "2", "1": "1", "2": "2"}
ITALIA = "100000100"          # l'Italia nella tabella STATI
GIORNI_MAX = 30               # «Massimo 30 gg» (CREAFILE.pdf p. 7)
TABELLE = ("COMUNI", "STATI", "DOCUMENTI", "TIPO_ALLOGGIATO")
CARTELLA_TABELLE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "deploy", "alloggiati")
_DATA_ISO = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")
# i campi che arrivano come testo e vanno nel file cosi' come sono (gli altri si ricavano)
_TESTUALI = tuple((c, l) for c, l in CAMPI
                  if c not in ("tipo", "data_arrivo", "giorni", "sesso", "data_nascita"))


def _ascii(s: Any) -> str:
    t = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii")
    return t.upper()


def _testo(v: Any) -> str:
    """Il valore come finira' nel file (ASCII maiuscolo, senza spazi ai bordi); None = vuoto."""
    return "" if v is None else _ascii(v).strip()


def _intrascrivibili(v: Any) -> str:
    """Le lettere che l'ASCII butterebbe via senza dirlo (Ł, Ø, ß, ideogrammi...). Gli
    accenti no: si tolgono e la lettera resta (Niccolò -> NICCOLO)."""
    if not isinstance(v, str):
        return ""
    return "".join(c for c in unicodedata.normalize("NFKD", v)
                   if ord(c) > 127 and not unicodedata.combining(c))


def _campo(valore: Any, lung: int) -> str:
    return _ascii(valore)[:lung].ljust(lung)


def _giorno(d: Any) -> Optional[datetime.date]:
    """'AAAA-MM-GG' -> la data, None se non esiste (il 31 febbraio compreso)."""
    if not _DATA_ISO.match(str(d)):
        return None
    try:
        return datetime.datetime.strptime(str(d), "%Y-%m-%d").date()
    except ValueError:
        return None


def _data(d: Any) -> str:
    g = _giorno(d)
    return "%02d/%02d/%04d" % (g.day, g.month, g.year) if g else ""


def _fine_validita(testo: Any) -> Optional[datetime.date]:
    """La colonna DataFineVal delle tabelle ('31/12/1983 00:00:00'); vuota = ancora valido."""
    try:
        return datetime.datetime.strptime(str(testo).strip()[:10], "%d/%m/%Y").date()
    except ValueError:
        return None


def carica_tabelle(cartella: str = CARTELLA_TABELLE) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Le 4 tabelle ufficiali: {tabella: {codice: {"descrizione", "provincia", "fine"}}}.
    Una tabella che manca o non si legge resta {}: chi controlla i codici la tratta come
    «non posso verificare», e la schedina NON si scrive."""
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for nome in TABELLE:
        righe: Dict[str, Dict[str, Any]] = {}
        try:
            with open(os.path.join(cartella, nome + ".csv"), encoding="utf-8",
                      newline="") as f:
                for r in csv.DictReader(f):
                    codice = (r.get("Codice") or "").strip()
                    if codice:
                        righe[codice] = {"descrizione": (r.get("Descrizione") or "").strip(),
                                         "provincia": (r.get("Provincia") or "").strip(),
                                         "fine": _fine_validita(r.get("DataFineVal") or "")}
        except (OSError, UnicodeDecodeError, csv.Error):
            righe = {}
        out[nome] = righe
    return out


def _esisteva(voce: Dict[str, Any], giorno: Optional[datetime.date]) -> bool:
    return voce["fine"] is None or (giorno is not None and giorno <= voce["fine"])


def _errori_codici(ospite: Dict[str, Any], tipo: Optional[str], tabelle: Dict[str, Any],
                   nascita: Optional[datetime.date]) -> List[str]:
    comuni, stati, documenti = (tabelle.get(n) or {} for n in ("COMUNI", "STATI", "DOCUMENTI"))
    mancanti = [n for n, t in (("COMUNI", comuni), ("STATI", stati),
                               ("DOCUMENTI", documenti)) if not t]
    if mancanti:
        return ["tabelle ufficiali assenti (%s): i codici non si possono verificare"
                % ", ".join(mancanti)]
    err = []
    stato = _testo(ospite.get("stato_nascita"))
    if stato and not (stato in stati and _esisteva(stati[stato], nascita)):
        err.append("stato_nascita %s: non e' nella tabella STATI alla data di nascita" % stato)
    cittadinanza = _testo(ospite.get("cittadinanza"))
    if cittadinanza and not (cittadinanza in stati and stati[cittadinanza]["fine"] is None):
        err.append("cittadinanza %s: non e' uno stato valido oggi" % cittadinanza)
    comune = _testo(ospite.get("comune_nascita"))
    if comune:
        voce = comuni.get(comune)
        if voce is None or not _esisteva(voce, nascita):
            err.append("comune_nascita %s: non e' nella tabella COMUNI alla data di nascita"
                       % comune)
        elif voce["provincia"] != _testo(ospite.get("prov_nascita")):
            err.append("prov_nascita: il comune %s e' in provincia %s"
                       % (comune, voce["provincia"]))
    if tipo in _CON_DOC:
        tipo_doc = _testo(ospite.get("tipo_doc"))
        if tipo_doc and tipo_doc not in documenti:
            err.append("tipo_doc %s: non e' nella tabella DOCUMENTI" % tipo_doc)
        luogo = _testo(ospite.get("luogo_doc"))
        if luogo and luogo not in comuni and (luogo not in stati or luogo == ITALIA):
            err.append("luogo_doc %s: il comune che l'ha rilasciato, o lo stato estero"
                       % luogo)
    return err


def errori_schedina(ospite: Any, tabelle: Optional[Dict[str, Any]] = None,
                    oggi: Optional[datetime.date] = None) -> List[str]:
    """Perche' il portale scarterebbe questa schedina; [] = si puo' scrivere.
    Con `tabelle` controlla anche i codici; con `oggi`, che l'arrivo sia oggi o ieri
    («La data di arrivo può essere quella odierna o quella relativa al giorno precedente»)."""
    if not isinstance(ospite, dict):
        return ["non e' un ospite"]
    err = ["%s: caratteri di controllo (a capo, tabulazione...)" % c
           for c, v in sorted(ospite.items(), key=lambda kv: str(kv[0]))
           if isinstance(v, str) and any(ord(x) < 32 or ord(x) == 127 for x in v)]
    for c, lung in _TESTUALI:
        persi = _intrascrivibili(ospite.get(c))
        if persi:
            err.append("%s: lettere che non esistono in caratteri latini (%s): va scritto come "
                       "nella riga in caratteri latini del documento" % (c, persi[:5]))
        elif len(_testo(ospite.get(c))) > lung:
            err.append("%s: %d caratteri, il tracciato ne tiene %d (tagliarlo lo renderebbe "
                       "falso)" % (c, len(_testo(ospite.get(c))), lung))
    ruolo = ospite.get("ruolo", "singolo")
    tipo = TIPO_ALLOGGIATO.get(ruolo) if isinstance(ruolo, str) else None
    if tipo is None:
        err.append("ruolo sconosciuto: %r" % (ruolo,))
    for c in ("cognome", "nome"):
        if not _testo(ospite.get(c)):
            err.append("%s mancante" % c)
    arrivo = _giorno(ospite.get("data_arrivo"))
    if arrivo is None:
        err.append("data_arrivo mancante o inesistente")
    elif oggi is not None and not (oggi - datetime.timedelta(days=1) <= arrivo <= oggi):
        err.append("data_arrivo: il portale accetta solo oggi o ieri")
    giorni = ospite.get("giorni", 1)
    if not (isinstance(giorni, int) and not isinstance(giorni, bool)
            and 1 <= giorni <= GIORNI_MAX):
        err.append("giorni: da 1 a %d" % GIORNI_MAX)
    if SESSO.get(str(ospite.get("sesso", "")).lower()) is None:
        err.append("sesso: 1 (M) o 2 (F)")
    nascita = _giorno(ospite.get("data_nascita"))
    if nascita is None:
        err.append("data_nascita mancante o inesistente")
    elif arrivo is not None and nascita > arrivo:
        err.append("data_nascita: dopo l'arrivo")
    stato = _testo(ospite.get("stato_nascita"))
    for c in ("stato_nascita", "cittadinanza"):
        if not _testo(ospite.get(c)):
            err.append("%s mancante" % c)
    nato_in_italia = [c for c in ("comune_nascita", "prov_nascita") if _testo(ospite.get(c))]
    if stato == ITALIA:
        err += ["%s obbligatorio per chi e' nato in Italia" % c
                for c in ("comune_nascita", "prov_nascita") if c not in nato_in_italia]
    elif nato_in_italia:
        err.append("comune e provincia di nascita solo per chi e' nato in Italia")
    if tipo in _CON_DOC:
        err += ["%s obbligatorio per il tipo %s" % (c, tipo)
                for c in ("tipo_doc", "num_doc", "luogo_doc") if not _testo(ospite.get(c))]
    if tabelle is not None:
        err += _errori_codici(ospite, tipo, tabelle, nascita)
    return err


def genera_schedina(ospite: Dict[str, Any], tabelle: Optional[Dict[str, Any]] = None,
                    oggi: Optional[datetime.date] = None) -> str:
    """Una riga a larghezza fissa per un ospite. '' se `errori_schedina` trova qualcosa."""
    if errori_schedina(ospite, tabelle, oggi):
        return ""
    tipo = TIPO_ALLOGGIATO[ospite.get("ruolo", "singolo")]
    val = {c: _testo(ospite.get(c)) for c, _ in CAMPI}
    val.update({"tipo": tipo, "data_arrivo": _data(ospite.get("data_arrivo")),
                "giorni": "%02d" % ospite.get("giorni", 1),
                "sesso": SESSO[str(ospite.get("sesso")).lower()],
                "data_nascita": _data(ospite.get("data_nascita"))})
    if tipo not in _CON_DOC:
        val.update({"tipo_doc": "", "num_doc": "", "luogo_doc": ""})
    return "".join(_campo(val[c], l) for c, l in CAMPI)


def genera_file(ospiti: Sequence[Dict[str, Any]], *, attivo: bool = False,
                tabelle: Optional[Dict[str, Any]] = None,
                oggi: Optional[datetime.date] = None) -> str:
    """File completo: CRLF fra le righe, NON dopo l'ultima (manuale del portale, CREAFILE.pdf
    p. 6-7). GATED: attivo=False (jurisdiction) → stringa vuota."""
    if not attivo or not isinstance(ospiti, (list, tuple)):
        return ""
    righe = [s for s in (genera_schedina(o, tabelle, oggi) for o in ospiti) if s]
    return "\r\n".join(righe)
