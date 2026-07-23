"""
CORE_AUTO - Fase 189: SMART PRICE ALERT ("Avvisami quando il prezzo scende").

STRATEGIA 1 (fondatore, 2026-07-23). L'ospite lascia un desiderio: destinazione, date (con
flessibilita'), budget massimo, e come vuole essere avvisato (email / WhatsApp / Telegram / SMS).
Quando un Host abbassa il prezzo o pubblica un last-minute che RIENTRA nei parametri, gli si
manda UN avviso con link 1-click al checkout (opzione "Paga in Struttura" pre-selezionabile).

Questo modulo e' il CUORE PURO e testabile: lo STORE (tabella `price_alerts`) + il MATCHMAKING
(quali avvisi far scattare data un'offerta). NON invia nulla da solo: la consegna la fa il
dispatcher multi-canale gia' esistente (fase152); lo scatto lo dara' un giro schedulato (wiring
successivo). GATED e DORMIENTE finche' non viene cablato: zero effetto sul live.

REGOLE (dal fondatore):
 - anti-spam: MAX 1 avviso al giorno per alert (tutela la reputazione del brand);
 - match solo se stessa VALUTA e prezzo offerto <= budget target, e le date si sovrappongono
   entro la flessibilita' richiesta;
 - zero PII di troppo: si tiene email + telefono (col prefisso) solo per avvisare.

STDLIB pura (sqlite3), niente dipendenze. Soldi: NESSUNO qui (solo avvisi).
"""
from __future__ import annotations

import datetime
import sqlite3
import time as _time
from typing import Any, Callable, Dict, List, Optional

GIORNO_SEC = 86400
CANALI = ("email", "whatsapp", "telegram", "sms", "line", "wechat")


def _i(v: Any, d: int = 0) -> int:
    try:
        if isinstance(v, bool):
            return d
        return int(v)
    except (TypeError, ValueError):
        return d


def _email_ok(e: Any) -> bool:
    return isinstance(e, str) and "@" in e and "." in e.split("@")[-1] and len(e) <= 254


def _norm(s: Any) -> str:
    return str(s).strip().lower() if s is not None else ""


def _date(s: Any) -> Optional[datetime.date]:
    try:
        return datetime.date.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None


def date_compatibili(alert_ci: str, alert_co: str, off_ci: str, off_co: str,
                     flex_giorni: int) -> bool:
    """L'offerta (off_ci..off_co) soddisfa la richiesta (alert_ci..alert_co) se le date coincidono
    entro `flex_giorni`. Se l'alert non ha date, qualsiasi offerta va bene (solo destinazione+budget)."""
    aci, aco = _date(alert_ci), _date(alert_co)
    if aci is None or aco is None:
        return True                       # nessuna data richiesta: basta destinazione+budget
    oci, oco = _date(off_ci), _date(off_co)
    if oci is None or oco is None:
        return False
    f = max(0, _i(flex_giorni))
    return abs((oci - aci).days) <= f and abs((oco - aco).days) <= f


def offerta_rientra(alert: Dict[str, Any], offerta: Dict[str, Any]) -> bool:
    """PURO: True se l'offerta fa scattare l'alert (destinazione, valuta, budget, date).
    Non guarda l'anti-spam (quello lo fa `da_avvisare`)."""
    if not isinstance(alert, dict) or not isinstance(offerta, dict):
        return False
    if not _i(alert.get("attivo", 1)):
        return False
    if _norm(alert.get("destinazione")) != _norm(offerta.get("destinazione")):
        return False
    # stessa valuta: confrontare budget e prezzo in monete diverse sarebbe un errore di soldi
    if _norm(alert.get("valuta", "EUR")) != _norm(offerta.get("valuta", "EUR")):
        return False
    prezzo = _i(offerta.get("prezzo_cents"), -1)
    budget = _i(alert.get("budget_cents"), -1)
    if prezzo < 0 or budget < 0 or prezzo > budget:
        return False
    return date_compatibili(alert.get("check_in", ""), alert.get("check_out", ""),
                            offerta.get("check_in", ""), offerta.get("check_out", ""),
                            alert.get("flessibilita_giorni", 0))


def da_avvisare(alert: Dict[str, Any], offerta: Dict[str, Any], ora_ts: int) -> bool:
    """PURO: l'alert va avvisato ORA? Rientra nei parametri E non e' gia' stato avvisato nelle
    ultime 24h (anti-spam: max 1/giorno)."""
    if not offerta_rientra(alert, offerta):
        return False
    ultimo = _i(alert.get("ultimo_avviso_ts"), 0)
    return (ora_ts - ultimo) >= GIORNO_SEC if ultimo > 0 else True


class _ConnCondivisa:
    """Wrapper che ignora close() (per iniettare una connessione unica, es. :memory:, nei test).
    Inoltra sia le letture sia le SCRITTURE di attributo (es. row_factory) alla connessione vera."""
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
        setattr(self._con, n, v)      # es. row_factory finisce sulla connessione vera


class GestorePriceAlert:
    """Store degli avvisi-prezzo + matchmaking. Best-effort e isolato: un errore non deve mai
    rompere una prenotazione o una pubblicazione (gli avvisi sono un di piu')."""

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
            con.execute("""CREATE TABLE IF NOT EXISTS price_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ospite_email TEXT NOT NULL,
                telefono TEXT NOT NULL DEFAULT '',
                destinazione TEXT NOT NULL,
                check_in TEXT NOT NULL DEFAULT '',
                check_out TEXT NOT NULL DEFAULT '',
                flessibilita_giorni INTEGER NOT NULL DEFAULT 0,
                budget_cents INTEGER NOT NULL,
                valuta TEXT NOT NULL DEFAULT 'EUR',
                canale TEXT NOT NULL DEFAULT 'email',
                attivo INTEGER NOT NULL DEFAULT 1,
                creato_ts INTEGER NOT NULL,
                ultimo_avviso_ts INTEGER NOT NULL DEFAULT 0)""")
            con.execute("CREATE INDEX IF NOT EXISTS ix_pa_dest "
                        "ON price_alerts(destinazione, attivo)")

    def registra(self, *, ospite_email: Any, destinazione: Any, budget_cents: Any,
                 telefono: str = "", check_in: str = "", check_out: str = "",
                 flessibilita_giorni: Any = 0, valuta: str = "EUR",
                 canale: str = "email") -> Optional[int]:
        """Salva un avviso-prezzo. Ritorna l'id, o None se i dati minimi non sono validi
        (email, destinazione, budget > 0). Il canale non riconosciuto ripiega su 'email'."""
        email = _norm(ospite_email)
        dest = _norm(destinazione)
        budget = _i(budget_cents, 0)
        if not _email_ok(email) or not dest or budget <= 0:
            return None
        can = _norm(canale)
        if can not in CANALI:
            can = "email"
        # WhatsApp/SMS/Telegram senza un contatto diretto non consegnerebbero: ripiega su email
        if can in ("whatsapp", "sms") and not str(telefono).strip():
            can = "email"
        with self._apri() as con:
            cur = con.execute(
                "INSERT INTO price_alerts (ospite_email, telefono, destinazione, check_in, "
                "check_out, flessibilita_giorni, budget_cents, valuta, canale, attivo, creato_ts) "
                "VALUES (?,?,?,?,?,?,?,?,?,1,?)",
                (email, str(telefono).strip(), dest, str(check_in or ""), str(check_out or ""),
                 max(0, _i(flessibilita_giorni)), budget, (valuta or "EUR").upper(), can,
                 int(self._ora())))
            return cur.lastrowid

    def attivi_per_destinazione(self, destinazione: Any, *, limit: int = 5000) -> List[Dict[str, Any]]:
        with self._apri() as con:
            rows = con.execute(
                "SELECT * FROM price_alerts WHERE destinazione=? AND attivo=1 "
                "ORDER BY id LIMIT ?", (_norm(destinazione), int(limit))).fetchall()
        return [dict(r) for r in rows]

    def match_offerta(self, offerta: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Data un'offerta {destinazione, prezzo_cents, valuta, check_in?, check_out?}, ritorna gli
        alert DA AVVISARE ora (rientrano nei parametri E non spammati nelle ultime 24h)."""
        ora = int(self._ora())
        fuori = []
        for a in self.attivi_per_destinazione(offerta.get("destinazione")):
            if da_avvisare(a, offerta, ora):
                fuori.append(a)
        return fuori

    def segna_avvisato(self, alert_id: Any, *, ora_ts: Optional[int] = None) -> bool:
        ts = int(ora_ts if ora_ts is not None else self._ora())
        with self._apri() as con:
            cur = con.execute("UPDATE price_alerts SET ultimo_avviso_ts=? WHERE id=?",
                              (ts, _i(alert_id)))
            return cur.rowcount > 0

    def disattiva(self, alert_id: Any) -> bool:
        with self._apri() as con:
            cur = con.execute("UPDATE price_alerts SET attivo=0 WHERE id=?", (_i(alert_id),))
            return cur.rowcount > 0

    def conta(self, *, solo_attivi: bool = True) -> int:
        with self._apri() as con:
            q = "SELECT COUNT(*) c FROM price_alerts" + (" WHERE attivo=1" if solo_attivi else "")
            return int(con.execute(q).fetchone()["c"])


def crea_gestore_price_alerts(percorso: str, *, orologio: Any = None) -> GestorePriceAlert:
    """Factory. `percorso` = file sqlite (o ':memory:'). DORMIENTE finche' non lo si cabla
    nel sistema (fase81) e non si aggiunge il giro di matchmaking."""
    def _cf() -> sqlite3.Connection:
        return sqlite3.connect(percorso, timeout=30)   # bug #36: aspetta il turno sotto contesa
    return GestorePriceAlert(_cf, orologio=orologio)
