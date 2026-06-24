"""
CORE_AUTO - Fase 151: Export "Alloggiati Web" (Questura / Polizia di Stato).

Genera il file a larghezza fissa delle schedine alloggiati (adempimento IT per le strutture
ricettive) dai dati ospiti. GATED/IT-specifico (jurisdiction): attivo=False di default;
formato CONFIGURABILE. Record a campi fissi (168 char), uppercase ASCII, padding a spazi,
date GG/MM/AAAA. Solo capo/singolo/gruppo portano i campi documento. PURO/deterministico.
BLINDATO: ospite invalido → saltato; mai eccezione.
"""
from __future__ import annotations

import unicodedata
from typing import Any, Dict, List, Sequence

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


def _ascii(s: Any) -> str:
    t = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii")
    return t.upper()


def _campo(valore: Any, lung: int) -> str:
    return _ascii(valore)[:lung].ljust(lung)


def _data(d: Any) -> str:
    try:
        a, m, g = str(d).split("-")
        if len(a) == 4:
            return "%02d/%02d/%04d" % (int(g), int(m), int(a))
    except Exception:
        return ""
    return ""


def genera_schedina(ospite: Dict[str, Any]) -> str:
    """Una riga a larghezza fissa per un ospite. '' se dati minimi mancanti."""
    if not isinstance(ospite, dict):
        return ""
    tipo = TIPO_ALLOGGIATO.get(str(ospite.get("ruolo", "singolo")), "16")
    cognome = ospite.get("cognome", "")
    nome = ospite.get("nome", "")
    arrivo = _data(ospite.get("data_arrivo"))
    if not (cognome and nome and arrivo):
        return ""
    giorni = ospite.get("giorni", 1)
    giorni = giorni if isinstance(giorni, int) and not isinstance(giorni, bool) \
        and 1 <= giorni <= 30 else 1
    val = {
        "tipo": tipo, "data_arrivo": arrivo, "giorni": "%02d" % giorni,
        "cognome": cognome, "nome": nome,
        "sesso": SESSO.get(str(ospite.get("sesso", "")).lower(), " "),
        "data_nascita": _data(ospite.get("data_nascita")),
        "comune_nascita": ospite.get("comune_nascita", ""),
        "prov_nascita": ospite.get("prov_nascita", ""),
        "stato_nascita": ospite.get("stato_nascita", ""),
        "cittadinanza": ospite.get("cittadinanza", ""),
    }
    if tipo in _CON_DOC:
        val.update({"tipo_doc": ospite.get("tipo_doc", ""),
                    "num_doc": ospite.get("num_doc", ""),
                    "luogo_doc": ospite.get("luogo_doc", "")})
    else:
        val.update({"tipo_doc": "", "num_doc": "", "luogo_doc": ""})
    return "".join(_campo(val.get(c, ""), l) for c, l in CAMPI)


def genera_file(ospiti: Sequence[Dict[str, Any]], *, attivo: bool = False) -> str:
    """File completo (righe CRLF). GATED: attivo=False (jurisdiction) → stringa vuota."""
    if not attivo or not isinstance(ospiti, (list, tuple)):
        return ""
    righe = [s for s in (genera_schedina(o) for o in ospiti) if s]
    return "".join(r + "\r\n" for r in righe)
