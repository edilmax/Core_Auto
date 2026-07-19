"""
CORE_AUTO - Fase 162: Pagamenti PENDENTI (hold prima del pagamento) — chiude il buco logico
per cui una prenotazione non pagata bloccava la stanza per sempre.

Quando serve un pagamento (Stripe configurato), al book la stanza va in HOLD e qui si registra
la prenotazione 'in_attesa' con una SCADENZA. Il webhook Stripe (pagamento riuscito) la
'conferma'. Uno sweeper periodico LIBERA gli hold scaduti non pagati (fase58.rilascia +
garanzia.annulla). Conserva anche tassa+comune per registrarli nel ledger (fase147) al pagamento.

Durevole SQLite (conn-per-op, row_factory=Row), idempotente, denaro in cents interi.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional

HOLD_SECONDI_DEFAULT = 120           # 2 minuti per pagare, poi la stanza si libera (urgenza tipo Agoda: chi paga prima se la prende)


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


class PagamentiPendenti:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._cf = conn_factory
        self._now = orologio or (lambda: int(time.time()))

    def _apri(self) -> sqlite3.Connection:
        con = self._cf()
        try:
            con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        return con

    def inizializza_schema(self) -> None:
        con = self._apri()
        try:
            with con:
                con.execute("""CREATE TABLE IF NOT EXISTS pendenti (
                    riferimento TEXT PRIMARY KEY,
                    alloggio_id TEXT NOT NULL, check_in TEXT NOT NULL, check_out TEXT NOT NULL,
                    idem_key TEXT NOT NULL DEFAULT '',
                    tassa_cents INTEGER NOT NULL DEFAULT 0, comune TEXT NOT NULL DEFAULT '',
                    host_id TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
                    quote_token TEXT NOT NULL DEFAULT '', corpo_json TEXT NOT NULL DEFAULT '',
                    scadenza_ts INTEGER NOT NULL, stato TEXT NOT NULL DEFAULT 'in_attesa',
                    promemoria_ts INTEGER NOT NULL DEFAULT 0,
                    creato_ts INTEGER NOT NULL)""")
                for _c in ("host_id", "email", "quote_token", "corpo_json"):
                    try:
                        con.execute("ALTER TABLE pendenti ADD COLUMN %s TEXT NOT NULL DEFAULT ''" % _c)
                    except sqlite3.OperationalError:
                        pass
                try:      # colonna INTEGER separata (promemoria check-in inviato)
                    con.execute("ALTER TABLE pendenti ADD COLUMN promemoria_ts INTEGER NOT NULL DEFAULT 0")
                except sqlite3.OperationalError:
                    pass
        finally:
            con.close()

    def _riga(self, r: sqlite3.Row) -> Dict[str, Any]:
        k = r.keys()
        g = lambda n, d="": (r[n] if n in k else d)
        return {"riferimento": r["riferimento"], "alloggio_id": r["alloggio_id"],
                "check_in": r["check_in"], "check_out": r["check_out"],
                "idem_key": r["idem_key"], "tassa_cents": int(r["tassa_cents"]),
                "comune": r["comune"], "stato": r["stato"], "scadenza_ts": int(r["scadenza_ts"]),
                "host_id": g("host_id"), "email": g("email"),
                "quote_token": g("quote_token"), "corpo_json": g("corpo_json")}

    def registra(self, riferimento: Any, *, alloggio_id: str, check_in: str, check_out: str,
                 idem_key: str = "", tassa_cents: int = 0, comune: str = "",
                 host_id: str = "", email: str = "", quote_token: str = "",
                 corpo_json: str = "", stato: str = "in_attesa",
                 scadenza_ts: Optional[int] = None) -> bool:
        if not (isinstance(riferimento, str) and riferimento and alloggio_id):
            return False
        now = self._now()
        sca = scadenza_ts if isinstance(scadenza_ts, int) and not isinstance(scadenza_ts, bool) \
            else now + HOLD_SECONDI_DEFAULT
        t = tassa_cents if isinstance(tassa_cents, int) and not isinstance(tassa_cents, bool) \
            and tassa_cents > 0 else 0
        st = stato if stato in ("in_attesa", "in_attesa_host") else "in_attesa"
        con = self._apri()
        try:
            with con:
                con.execute(
                    "INSERT INTO pendenti (riferimento, alloggio_id, check_in, check_out, "
                    "idem_key, tassa_cents, comune, host_id, email, quote_token, corpo_json, "
                    "scadenza_ts, stato, creato_ts) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(riferimento) DO NOTHING",
                    (riferimento, alloggio_id, check_in, check_out, str(idem_key or ""),
                     t, str(comune or ""), str(host_id or ""), str(email or ""),
                     str(quote_token or ""), str(corpo_json or ""), sca, st, now))
            return True
        finally:
            con.close()

    def da_approvare(self, host_id: Any, *, limit: int = 100) -> List[Dict[str, Any]]:
        """Richieste 'in_attesa_host' per il pannello dell'host."""
        if not (isinstance(host_id, str) and host_id):
            return []
        lim = limit if isinstance(limit, int) and 0 < limit <= 500 else 100
        con = self._apri()
        try:
            righe = con.execute("SELECT * FROM pendenti WHERE stato='in_attesa_host' AND "
                                "host_id=? ORDER BY creato_ts LIMIT ?", (host_id, lim)).fetchall()
            return [self._riga(r) for r in righe]
        finally:
            con.close()

    def salva_stripe_session(self, riferimento: Any, cs_id: Any) -> bool:
        """AUDIT CONSOLE (prerequisito): salva l'id sessione Stripe (cs_...) arrivato col
        webhook, dentro corpo_json (merge, MAI sovrascrive il resto). Da qui in poi lo
        shadow-check Stripe della scheda contabile puo' verificare il pagamento alla fonte.
        Idempotente e ISOLATO (un fallimento qui non tocca la conferma del pagamento)."""
        if not (isinstance(riferimento, str) and riferimento
                and isinstance(cs_id, str) and cs_id.startswith("cs_")):
            return False
        import json as _j
        con = self._apri()
        try:
            with con:
                r = con.execute("SELECT corpo_json FROM pendenti WHERE riferimento=?",
                                (riferimento,)).fetchone()
                if r is None:
                    return False
                try:
                    dj = _j.loads(r["corpo_json"] or "{}")
                    if not isinstance(dj, dict):
                        dj = {}
                except Exception:
                    dj = {}
                if dj.get("stripe_cs") == cs_id:
                    return True                       # gia' salvato (retry webhook)
                dj["stripe_cs"] = cs_id
                con.execute("UPDATE pendenti SET corpo_json=? WHERE riferimento=?",
                            (_j.dumps(dj, ensure_ascii=False), riferimento))
                return True
        except Exception:
            logger.warning("salva_stripe_session fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()

    def cerca_prenotazioni(self, termine: Any, *, limit: int = 10, offset: int = 0
                           ) -> Dict[str, Any]:
        """RICERCA OPERATIVA (Field, Incremento 7): prenotazioni per RIFERIMENTO (prefisso,
        usa l'indice PK) o EMAIL ospite (LIKE). Wildcard dell'utente neutralizzate.
        Read-only, SOLO campi operativi (mai corpo_json/idem_key). {'prenotazioni', 'totale'}."""
        if not (isinstance(termine, str) and len(termine.strip()) >= 2):
            return {"prenotazioni": [], "totale": 0}
        lim = limit if isinstance(limit, int) and 0 < limit <= 50 else 10
        off = offset if isinstance(offset, int) and 0 <= offset <= 10 ** 6 else 0
        t = termine.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where = ("WHERE riferimento LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\'")
        par = (t + "%", "%" + t + "%")               # rif = prefisso (indice), email = contiene
        con = self._apri()
        try:
            tot = con.execute("SELECT COUNT(*) FROM pendenti " + where, par).fetchone()[0]
            righe = con.execute(
                "SELECT riferimento, alloggio_id, check_in, check_out, stato, host_id, email"
                " FROM pendenti " + where + " ORDER BY creato_ts DESC LIMIT ? OFFSET ?",
                par + (lim, off)).fetchall()
        except Exception:
            logger.warning("cerca_prenotazioni fallita (ISOLATA)", exc_info=True)
            return {"prenotazioni": [], "totale": 0}
        finally:
            con.close()
        return {"prenotazioni": [{"riferimento": r["riferimento"],
                                  "alloggio_id": r["alloggio_id"],
                                  "check_in": r["check_in"], "check_out": r["check_out"],
                                  "stato": r["stato"],
                                  "host_id": (r["host_id"] if "host_id" in r.keys() else "") or "",
                                  "email": (r["email"] if "email" in r.keys() else "") or ""}
                                 for r in righe],
                "totale": int(tot)}

    def notti_per_alloggio(self, host_id: Any, anno: int) -> Dict[str, Dict[str, int]]:
        """DAC7 ('giorni-affitto per immobile'): notti LOCATE per alloggio nell'anno.
        Conta SOLO le prenotazioni PAGATE (le rimborsate/cancellate non sono locazione)
        e attribuisce le notti all'anno del SOGGIORNO: un soggiorno a cavallo d'anno si
        divide (notti di dicembre all'anno vecchio, di gennaio al nuovo). Read-only,
        a prova di data malformata (una riga rotta non rompe mai il report).
        Ritorna {alloggio_id: {'notti': n, 'pren': m}}."""
        import datetime as _dt
        if not (isinstance(host_id, str) and host_id
                and isinstance(anno, int) and not isinstance(anno, bool)):
            return {}
        try:
            ini, fine = _dt.date(anno, 1, 1), _dt.date(anno + 1, 1, 1)
        except (ValueError, OverflowError):
            return {}
        con = self._apri()
        try:
            righe = con.execute("SELECT alloggio_id, check_in, check_out FROM pendenti "
                                "WHERE host_id=? AND stato='pagato'", (host_id,)).fetchall()
        except Exception:
            logger.warning("notti_per_alloggio fallita (ISOLATA)", exc_info=True)
            return {}
        finally:
            con.close()
        out: Dict[str, Dict[str, int]] = {}
        for r in righe:
            try:
                ci = _dt.date.fromisoformat(str(r["check_in"]))
                co = _dt.date.fromisoformat(str(r["check_out"]))
            except (ValueError, TypeError):
                continue                     # data rotta: si salta la riga, non il report
            n = (min(co, fine) - max(ci, ini)).days   # overlap [check_in, check_out) ∩ anno
            if n <= 0:
                continue
            d = out.setdefault(str(r["alloggio_id"]), {"notti": 0, "pren": 0})
            d["notti"] += n
            d["pren"] += 1
        return out

    def conferma(self, riferimento: Any) -> Optional[Dict[str, Any]]:
        """Pagamento riuscito -> 'pagato', ma SOLO da 'in_attesa' o 'scaduto' (CAS in
        BEGIN IMMEDIATE: chiude la GARA con lo sweeper che nello stesso istante può
        star liberando le date). Ritorna il record con lo stato PRECEDENTE: il
        chiamante decide il ramo DOPO l'acquisizione atomica ('in_attesa' = stanza
        ancora bloccata; 'scaduto' = serve re-block; 'pagato' = webhook duplicato;
        altri stati = NON confermata, rimborsare). None se il riferimento non esiste.
        Prima era read-then-write in due tempi: un webhook con lettura 'in_attesa'
        appena stantia sovrascriveva 'pagato' su date già liberate dallo sweeper ->
        cliente pagato senza stanza garantita (doppia prenotazione possibile)."""
        if not (isinstance(riferimento, str) and riferimento):
            return None
        con = self._apri()
        try:
            r = None
            for _ in range(8):
                r = con.execute("SELECT * FROM pendenti WHERE riferimento=?",
                                (riferimento,)).fetchone()
                if r is None:
                    return None
                if r["stato"] not in ("in_attesa", "scaduto"):
                    return self._riga(r)      # pagato/cancellata/...: nessuna scrittura
                with con:
                    cur = con.execute(
                        "UPDATE pendenti SET stato='pagato' WHERE riferimento=? AND stato=?",
                        (riferimento, r["stato"]))
                if cur.rowcount:
                    return self._riga(r)      # CAS vinto: r = lo stato PRECEDENTE, esatto
                # CAS perso: lo stato è cambiato tra lettura e scrittura (es. lo sweeper
                # ha appena marcato 'scaduto') -> rileggi e rigioca. Il loop converge:
                # gli stati confermabili sono 2 e le transizioni finiscono su stati fermi.
            return self._riga(r)
        finally:
            con.close()

    def aggiorna_idem(self, riferimento: Any, idem_key: Any) -> bool:
        """Aggiorna la idem_key del record (dopo un RE-BLOCK con chiave fresca: i flussi
        futuri — cancellazione/rimborso — devono accoppiarsi al blocco ATTIVO, non a
        quello originale già rilasciato, o il rilascio sarebbe un replay a vuoto)."""
        if not (isinstance(riferimento, str) and riferimento
                and isinstance(idem_key, str) and idem_key):
            return False
        con = self._apri()
        try:
            with con:
                cur = con.execute("UPDATE pendenti SET idem_key=? WHERE riferimento=?",
                                  (idem_key, riferimento))
            return bool(cur.rowcount)
        finally:
            con.close()

    def scaduti(self, *, ora_ts: Optional[int] = None) -> List[Dict[str, Any]]:
        ora = ora_ts if isinstance(ora_ts, int) and not isinstance(ora_ts, bool) else self._now()
        con = self._apri()
        try:
            righe = con.execute("SELECT * FROM pendenti WHERE stato IN "
                                "('in_attesa','in_attesa_host') AND scadenza_ts<=?",
                                (ora,)).fetchall()
            return [self._riga(r) for r in righe]
        finally:
            con.close()

    def rimuovi(self, riferimento: Any) -> bool:
        if not (isinstance(riferimento, str) and riferimento):
            return False
        con = self._apri()
        try:
            with con:
                cur = con.execute("DELETE FROM pendenti WHERE riferimento=?", (riferimento,))
            return bool(cur.rowcount)
        finally:
            con.close()

    def rimuovi_se_stato(self, riferimento: Any, stato: Any) -> bool:
        """Rimozione CONDIZIONATA (CAS): elimina il record SOLO se e' ancora nello stato
        atteso. E' l'acquisizione atomica della decisione approva/rifiuta: due decisioni
        concorrenti (doppio click, approva vs rifiuta, approva vs sweeper che scade) ne
        vincono UNA sola; il perdente vede False e non tocca date/escrow/pagamenti.
        Prima era rimuovi() incondizionato: approva+rifiuta simultanei confermavano una
        prenotazione su date gia' liberate (overbooking + cliente invitato a pagare)."""
        if not (isinstance(riferimento, str) and riferimento
                and isinstance(stato, str) and stato):
            return False
        con = self._apri()
        try:
            with con:
                cur = con.execute("DELETE FROM pendenti WHERE riferimento=? AND stato=?",
                                  (riferimento, stato))
            return bool(cur.rowcount)
        finally:
            con.close()

    def scadi(self, riferimento: Any) -> bool:
        """Hold scaduto (non pagato entro i 2 min): NON cancella il record, lo marca 'scaduto'
        conservando i dati. Serve a gestire un eventuale pagamento TARDIVO (link Stripe ancora
        vivo): al pagamento si ri-tenta il blocco stanza; se libera -> ancora sua, se presa da
        chi ha pagato prima -> rimborso. Evita 'soldi senza stanza'."""
        if not (isinstance(riferimento, str) and riferimento):
            return False
        con = self._apri()
        try:
            with con:
                cur = con.execute(
                    "UPDATE pendenti SET stato='scaduto' WHERE riferimento=? AND "
                    "stato IN ('in_attesa','in_attesa_host')", (riferimento,))
            return bool(cur.rowcount)
        finally:
            con.close()

    def marca_da_rimborsare(self, riferimento: Any) -> bool:
        """Pagamento tardivo su stanza già presa: marca 'rimborsato' (il cliente va rimborsato).
        Non riappare negli scaduti; verrà ripulito da pulisci_vecchi.
        CONDIZIONATA (anti-gara admin∥host, BUG provato): NON retrocede mai un record già
        'cancellata_host' — quello stato porta la PENALE dell'host nel corpo_json e riscriverlo
        creava il mostro "stato rimborsato + penale registrata" (multa incoerente). Il transfer
        è comunque bloccato in entrambi gli stati. Idempotente: replay su 'rimborsato' = no-op."""
        if not (isinstance(riferimento, str) and riferimento):
            return False
        con = self._apri()
        try:
            with con:
                cur = con.execute(
                    "UPDATE pendenti SET stato='rimborsato' WHERE riferimento=? "
                    "AND stato NOT IN ('cancellata_host','rimborsato')", (riferimento,))
            return bool(cur.rowcount)
        finally:
            con.close()

    def marca_cancellata_host(self, riferimento: Any, penale_cents: int = 0) -> bool:
        """L'host ha annullato: marca 'cancellata_host' e registra la penale nel corpo_json.
        CAS (acquisizione atomica della decisione, pattern #16/#31): scrive SOLO se il record
        non è già chiuso ('cancellata_host'/'rimborsato'). Chi perde la gara (doppio click,
        admin rimborso nello stesso istante) vede False e NON deve applicare penale/effetti."""
        if not (isinstance(riferimento, str) and riferimento):
            return False
        con = self._apri()
        try:
            with con:
                r = con.execute("SELECT corpo_json FROM pendenti WHERE riferimento=?",
                                (riferimento,)).fetchone()
                cj = {}
                if r and r["corpo_json"]:
                    try:
                        import json as _j
                        cj = _j.loads(r["corpo_json"])
                    except Exception:
                        cj = {}
                cj["penale_host_cents"] = int(penale_cents) if isinstance(penale_cents, int) else 0
                import json as _j2
                cur = con.execute(
                    "UPDATE pendenti SET stato='cancellata_host', corpo_json=? "
                    "WHERE riferimento=? AND stato NOT IN ('cancellata_host','rimborsato')",
                    (_j2.dumps(cj), riferimento))
            return bool(cur.rowcount)
        finally:
            con.close()

    def cancellate_host(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        """Le cancellazioni-host piu' recenti (per la RIASSERZIONE penali del Financial
        Controller fase177: un crash tra il CAS e il giornale lascia la penale annotata
        qui ma senza Nota di Debito -> lo sweeper la sana, pattern #32)."""
        lim = limit if isinstance(limit, int) and 0 < limit <= 500 else 50
        con = self._apri()
        try:
            righe = con.execute("SELECT * FROM pendenti WHERE stato='cancellata_host' "
                                "ORDER BY creato_ts DESC LIMIT ?", (lim,)).fetchall()
            return [self._riga(r) for r in righe]
        finally:
            con.close()

    def attivi_per_alloggio(self, alloggio_id: Any, *,
                            ora_ts: Optional[int] = None) -> List[Dict[str, Any]]:
        """Hold/richieste ANCORA VIVI per un alloggio ('in_attesa' = in attesa di pagamento,
        'in_attesa_host' = in attesa di approvazione). Per il calendario host: quei giorni
        sono 'in trattativa' (arancione), non prenotazioni confermate."""
        if not (isinstance(alloggio_id, str) and alloggio_id):
            return []
        ora = ora_ts if isinstance(ora_ts, int) and not isinstance(ora_ts, bool) else self._now()
        con = self._apri()
        try:
            righe = con.execute(
                "SELECT * FROM pendenti WHERE alloggio_id=? AND stato IN "
                "('in_attesa','in_attesa_host') AND scadenza_ts>?",
                (alloggio_id, ora)).fetchall()
            return [self._riga(r) for r in righe]
        finally:
            con.close()

    def attivi_multi(self, slugs: Any, *,
                     ora_ts: Optional[int] = None) -> Dict[str, List[Dict[str, Any]]]:
        """Hold vivi per PIU' alloggi in UNA sola query -> {slug: [record, ...]}.
        Evita l'N+1 della vista calendario multi-alloggio (prima: 1 connessione+query
        PER slug). Stessa semantica di attivi_per_alloggio, batch: stati vivi
        ('in_attesa'/'in_attesa_host') e scadenza non passata. Slug non-str ignorati."""
        lista = [s for s in (slugs or []) if isinstance(s, str) and s]
        if not lista:
            return {}
        ora = ora_ts if isinstance(ora_ts, int) and not isinstance(ora_ts, bool) else self._now()
        ph = ",".join("?" * len(lista))
        con = self._apri()
        try:
            righe = con.execute(
                "SELECT * FROM pendenti WHERE alloggio_id IN (%s) AND stato IN "
                "('in_attesa','in_attesa_host') AND scadenza_ts>?" % ph,
                (*lista, ora)).fetchall()
        finally:
            con.close()
        out: Dict[str, List[Dict[str, Any]]] = {}
        for r in righe:
            d = self._riga(r)
            out.setdefault(d.get("alloggio_id"), []).append(d)
        return out

    def pulisci_vecchi(self, *, eta_sec: int = 93600, ora_ts: Optional[int] = None) -> int:
        """Elimina i record 'scaduto'/'rimborsato' più vecchi di eta_sec (default 26h: una
        sessione Stripe può vivere fino a 24h — su-richiesta approvata — e finché il link è
        vivo il record DEVE esistere, così un pagamento su una prenotazione cancellata/scaduta
        viene riconosciuto e mai confermato alla cieca). Ritorna quanti rimossi."""
        ora = ora_ts if isinstance(ora_ts, int) and not isinstance(ora_ts, bool) else self._now()
        con = self._apri()
        try:
            with con:
                cur = con.execute(
                    "DELETE FROM pendenti WHERE stato IN ('scaduto','rimborsato') AND creato_ts<?",
                    (ora - max(60, int(eta_sec)),))
            return cur.rowcount
        finally:
            con.close()

    def da_promemoriare(self, *, oggi: str, limit: int = 200) -> List[Dict[str, Any]]:
        """Prenotazioni PAGATE il cui check-in è arrivato (check_in <= oggi) e a cui non è
        ancora stato inviato il promemoria (promemoria_ts=0) e con email presente. Per il
        promemoria post-check-in ('tutto ok? / segnala un problema entro 24h')."""
        if not (isinstance(oggi, str) and oggi):
            return []
        lim = limit if isinstance(limit, int) and not isinstance(limit, bool) \
            and 0 < limit <= 500 else 200
        con = self._apri()
        try:
            righe = con.execute(
                "SELECT * FROM pendenti WHERE stato='pagato' AND check_in<=? "
                "AND promemoria_ts=0 AND email!='' ORDER BY check_in LIMIT ?",
                (oggi, lim)).fetchall()
            return [self._riga(r) for r in righe]
        finally:
            con.close()

    def segna_promemoria(self, riferimento: Any, ts: Optional[int] = None) -> bool:
        if not (isinstance(riferimento, str) and riferimento):
            return False
        t = ts if isinstance(ts, int) and not isinstance(ts, bool) else self._now()
        con = self._apri()
        try:
            with con:
                cur = con.execute("UPDATE pendenti SET promemoria_ts=? WHERE riferimento=?",
                                  (t, riferimento))
            return bool(cur.rowcount)
        finally:
            con.close()

    def info(self, riferimento: Any) -> Optional[Dict[str, Any]]:
        if not (isinstance(riferimento, str) and riferimento):
            return None
        con = self._apri()
        try:
            r = con.execute("SELECT * FROM pendenti WHERE riferimento=?", (riferimento,)).fetchone()
        finally:
            con.close()
        return self._riga(r) if r is not None else None


def crea_pagamenti_pendenti(percorso: str, *, orologio: Any = None) -> PagamentiPendenti:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        con.row_factory = sqlite3.Row
        return PagamentiPendenti(lambda: _ConnCondivisa(con), orologio=orologio)

    def cf() -> sqlite3.Connection:
        c = sqlite3.connect(percorso)
        c.row_factory = sqlite3.Row
        return c
    return PagamentiPendenti(cf, orologio=orologio)
