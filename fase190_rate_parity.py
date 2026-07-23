"""
CORE_AUTO - Fase 190: RATE PARITY & BLINDO PREZZI ("prezzo pari o inferiore altrove").

STRATEGIA 2 (fondatore, 2026-07-23). Tuteliamo l'ospite (e la competitivita' di BookinVIP)
evitando che l'Host gonfi il prezzo da noi rispetto a Booking/Airbnb:
 1. CLAUSOLA contrattuale di parita' tariffaria (testo nel Contratto Host / termini) — vincola
    l'Host a garantire su BookinVIP un prezzo pari o INFERIORE a quello sulle altre piattaforme;
 2. tasto "SEGNALA PREZZO PIU' BASSO": l'ospite segnala con uno scatto se ha trovato la stessa
    struttura a meno altrove (OTA, prezzo, link) — questo modulo lo REGISTRA;
 3. PREMIO/PENALIZZAZIONE di VISIBILITA': chi rispetta la parita' prende il "Badge Prezzo VIP" e
    priorita' nei risultati; chi ha violazioni aperte viene penalizzato nel ranking.

Questo modulo e' il CUORE PURO+testabile: lo STORE (`parity_reports`) + il calcolo dello STATO di
parita' per annuncio + il segnale di VISIBILITA' (puro) che il motore di ricerca/SEO (fase173)
potra' usare. NON tocca il ranking da solo: e' un segnale che chi ordina i risultati puo' leggere.
DORMIENTE finche' non viene cablato (endpoint di segnalazione + lettura del segnale nel ranking).

STDLIB pura (sqlite3). Soldi: NESSUNO qui (solo segnalazioni + un segnale di ordinamento).
"""
from __future__ import annotations

import sqlite3
import time as _time
from typing import Any, Callable, Dict, List, Optional

# scostamento minimo perche' una segnalazione "sotto di poco" non penalizzi per rumore/valute
TOLLERANZA_BPS = 200                  # 2%: sotto questa differenza non e' una vera violazione
BONUS_BADGE_VIP = 15                  # spinta di ranking per chi garantisce la parita' (0 violazioni)
PENALITA_VIOLAZIONE = 40             # penalita' di ranking per violazioni aperte verificate

STATI = ("aperto", "verificato", "respinto", "risolto")


def _i(v: Any, d: int = 0) -> int:
    try:
        if isinstance(v, bool):
            return d
        return int(v)
    except (TypeError, ValueError):
        return d


def _norm(s: Any) -> str:
    return str(s).strip().lower() if s is not None else ""


def e_violazione(nostro_prezzo_cents: Any, ota_prezzo_cents: Any, *,
                 tolleranza_bps: int = TOLLERANZA_BPS) -> bool:
    """PURO: c'e' violazione di parita' se il PREZZO NOSTRO supera quello OTA oltre la tolleranza.
    (Se da noi costa uguale o meno, nessuna violazione: e' quello che vogliamo.)"""
    n = _i(nostro_prezzo_cents, -1)
    o = _i(ota_prezzo_cents, -1)
    if n < 0 or o <= 0:
        return False
    soglia = o + o * max(0, _i(tolleranza_bps)) // 10000
    return n > soglia


def punteggio_visibilita(base: Any, stato: Dict[str, Any]) -> int:
    """PURO: aggiusta il punteggio di ranking di un annuncio in base allo stato di parita'.
    +bonus se ha il Badge VIP (0 violazioni verificate), -penalita' se ne ha di aperte/verificate.
    Non scende mai sotto 0 (un annuncio non sparisce, viene solo spinto in basso)."""
    b = _i(base, 0)
    if not isinstance(stato, dict):
        return max(0, b)
    if _i(stato.get("violazioni_verificate")) > 0:
        b -= PENALITA_VIOLAZIONE
    elif stato.get("badge_vip"):
        b += BONUS_BADGE_VIP
    return max(0, b)


class _ConnCondivisa:
    def __init__(self, con: sqlite3.Connection) -> None:
        object.__setattr__(self, "_con", con)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self._con.__enter__()

    def __exit__(self, *a):
        return self._con.__exit__(*a)

    def __getattr__(self, n):
        return getattr(self._con, n)

    def __setattr__(self, n, v):
        setattr(self._con, n, v)


class GestoreRateParity:
    """Store delle segnalazioni di parita' + stato/segnale di visibilita' per annuncio."""

    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 orologio: Any = None) -> None:
        self._cf = conn_factory
        self._ora = orologio or (lambda: int(_time.time()))
        self.inizializza_schema()

    def _apri(self) -> sqlite3.Connection:
        con = self._cf()
        con.row_factory = sqlite3.Row
        return con

    def inizializza_schema(self) -> None:
        with self._apri() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS parity_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alloggio_slug TEXT NOT NULL,
                ospite_email TEXT NOT NULL DEFAULT '',
                ota_nome TEXT NOT NULL DEFAULT '',
                ota_url TEXT NOT NULL DEFAULT '',
                nostro_prezzo_cents INTEGER NOT NULL DEFAULT 0,
                ota_prezzo_cents INTEGER NOT NULL DEFAULT 0,
                valuta TEXT NOT NULL DEFAULT 'EUR',
                stato TEXT NOT NULL DEFAULT 'aperto',
                creato_ts INTEGER NOT NULL,
                risolto_ts INTEGER NOT NULL DEFAULT 0)""")
            con.execute("CREATE INDEX IF NOT EXISTS ix_pr_slug "
                        "ON parity_reports(alloggio_slug, stato)")

    def segnala(self, *, alloggio_slug: Any, ota_nome: Any, ota_prezzo_cents: Any,
                nostro_prezzo_cents: Any, ospite_email: str = "", ota_url: str = "",
                valuta: str = "EUR") -> Optional[int]:
        """Registra una segnalazione. Il suo STATO iniziale dipende dai numeri: se il prezzo
        nostro supera davvero l'OTA (oltre tolleranza) nasce 'aperto' (da verificare), altrimenti
        'respinto' subito (segnalazione infondata: da noi non costa di piu'). Ritorna l'id o None."""
        slug = _norm(alloggio_slug)
        if not slug or _i(ota_prezzo_cents, 0) <= 0:
            return None
        stato = "aperto" if e_violazione(nostro_prezzo_cents, ota_prezzo_cents) else "respinto"
        with self._apri() as con:
            cur = con.execute(
                "INSERT INTO parity_reports (alloggio_slug, ospite_email, ota_nome, ota_url, "
                "nostro_prezzo_cents, ota_prezzo_cents, valuta, stato, creato_ts) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (slug, _norm(ospite_email), str(ota_nome or "")[:80], str(ota_url or "")[:500],
                 _i(nostro_prezzo_cents), _i(ota_prezzo_cents), (valuta or "EUR").upper(),
                 stato, int(self._ora())))
            return cur.lastrowid

    def risolvi(self, report_id: Any, esito: str) -> bool:
        """Admin: chiude una segnalazione. esito in {'verificato','respinto','risolto'}."""
        es = _norm(esito)
        if es not in ("verificato", "respinto", "risolto"):
            return False
        with self._apri() as con:
            cur = con.execute("UPDATE parity_reports SET stato=?, risolto_ts=? WHERE id=?",
                              (es, int(self._ora()), _i(report_id)))
            return cur.rowcount > 0

    def stato_parita(self, alloggio_slug: Any) -> Dict[str, Any]:
        """Segnale per il ranking: quante violazioni aperte/verificate ha l'annuncio, e se merita
        il Badge Prezzo VIP (nessuna violazione aperta ne' verificata)."""
        slug = _norm(alloggio_slug)
        with self._apri() as con:
            ap = con.execute("SELECT COUNT(*) c FROM parity_reports WHERE alloggio_slug=? "
                             "AND stato='aperto'", (slug,)).fetchone()["c"]
            ver = con.execute("SELECT COUNT(*) c FROM parity_reports WHERE alloggio_slug=? "
                              "AND stato='verificato'", (slug,)).fetchone()["c"]
        aperte, verificate = int(ap), int(ver)
        return {"alloggio_slug": slug, "violazioni_aperte": aperte,
                "violazioni_verificate": verificate,
                "badge_vip": (aperte == 0 and verificate == 0),
                "penalita": verificate > 0}

    def segnalazioni(self, *, stato: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
        with self._apri() as con:
            if stato:
                rows = con.execute("SELECT * FROM parity_reports WHERE stato=? ORDER BY id DESC "
                                   "LIMIT ?", (_norm(stato), int(limit))).fetchall()
            else:
                rows = con.execute("SELECT * FROM parity_reports ORDER BY id DESC LIMIT ?",
                                   (int(limit),)).fetchall()
        return [dict(r) for r in rows]


def crea_gestore_rate_parity(percorso: str, *, orologio: Any = None) -> GestoreRateParity:
    """Factory. DORMIENTE finche' non lo si cabla (endpoint segnalazione + lettura del segnale
    di visibilita' nel ranking di ricerca)."""
    def _cf() -> sqlite3.Connection:
        return sqlite3.connect(percorso, timeout=30)   # bug #36: aspetta il turno sotto contesa
    return GestoreRateParity(_cf, orologio=orologio)
