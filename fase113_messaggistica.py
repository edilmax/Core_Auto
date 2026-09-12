"""
CORE_AUTO - Fase 113: Messaggistica host-guest in-app (thread per prenotazione).

Thread di messaggi legato a una prenotazione: solo i due partecipanti (host, guest) scrivono
e leggono. Store DUREVOLE (SQLite WAL, conn-per-op + _ConnCondivisa per :memory:). Anti-abuso:
mittente deve appartenere al thread; testo limitato; mascheramento PII (email/telefono) per
spostare lo scambio fuori-piattaforma. BLINDATO: errore → False/[]. Orologio iniettabile.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("core_auto.messaggistica")

MAX_TESTO = 4000
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_TEL = re.compile(r"(?:(?:\+|00)\d[\d\s().-]{6,}\d)|(?:\b\d[\d\s().-]{7,}\d\b)")
# Url di una PROVA FOTO come la genera il server: token_hex(16) + estensione da magic-bytes.
# Volutamente STRETTA (32 esadecimali esatti): un testo qualunque non ci passa.
_URL_PROVA = re.compile(r"/uploads/[0-9a-f]{32}\.(?:png|jpg|webp|gif)")


def maschera_pii(testo: str) -> str:
    # PROTEZIONE URL PROVE (fix 2026-07-19): il filtro anti-telefono scambiava per numero
    # un run "00"+cifre DENTRO il nome esadecimale della foto (es. ...fa005754588289...)
    # e lo storpiava in "[contatto rimosso]" -> link rotto in chat (l'arbitro non apre la
    # prova) e file non piu' "citato" -> la pulizia orfani l'avrebbe CANCELLATO dopo 7gg.
    # Gli url /uploads/ (di sistema, charset ristretto) si accantonano PRIMA delle maschere
    # e si ripristinano DOPO; \x00 non puo' fondersi con cifre adiacenti in un falso match.
    salvati = []

    def _accantona(m):
        salvati.append(m.group(0))
        return "\x00U%d\x00" % (len(salvati) - 1)

    t = _URL_PROVA.sub(_accantona, testo)
    t = _EMAIL.sub("[email rimossa]", t)
    t = _TEL.sub("[contatto rimosso]", t)
    for i, u in enumerate(salvati):
        t = t.replace("\x00U%d\x00" % i, u)
    return t


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


class Messaggistica:
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
                con.execute("""CREATE TABLE IF NOT EXISTS messaggi (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prenotazione_id TEXT NOT NULL, host_id TEXT NOT NULL,
                    guest_id TEXT NOT NULL, mittente TEXT NOT NULL,
                    testo TEXT NOT NULL, ts INTEGER NOT NULL,
                    letto INTEGER NOT NULL DEFAULT 0)""")
                con.execute("CREATE INDEX IF NOT EXISTS ix_msg_pren "
                            "ON messaggi(prenotazione_id, id)")
        finally:
            con.close()

    def cancella_messaggi_host(self, host_id: Any) -> int:
        """CANCELLAZIONE TOTALE dei messaggi di un host (oblio/pulizia).

        ⛔ SOVRASCRIVE, come `cancella_thread`. Fino al 2026-09-12 il pragma stava solo nel
        giro della conservazione: la cancellazione con l'obbligo piu' DEBOLE (un termine che
        ci siamo dati noi) era fatta meglio di quella con l'obbligo piu' FORTE — l'oblio
        dell'art. 17, che la persona chiede e la legge impone. Misurato: senza il pragma il
        testo si rilegge dai byte del file dopo la cancellazione."""
        if not (isinstance(host_id, str) and host_id):
            return 0
        con = self._apri()
        try:
            try:
                con.execute("PRAGMA secure_delete=ON")
            except sqlite3.Error:
                logger.warning("secure_delete non applicabile su questo database")
            with con:
                cur = con.execute("DELETE FROM messaggi WHERE host_id=?", (host_id,))
            return cur.rowcount if (cur.rowcount and cur.rowcount > 0) else 0
        finally:
            con.close()

    def cancella_thread(self, prenotazione_id: Any) -> int:
        """La conversazione di UNA prenotazione, cancellata perche' il termine di
        conservazione dichiarato nell'informativa e' passato. Ritorna quanti messaggi.

        ⛔ SOVRASCRIVE, non solo scollega. Un `DELETE` di SQLite marca lo spazio come
        riutilizzabile e lascia il testo nelle pagine libere, da cui si rilegge con
        strumenti forensi ordinari (`sqlite.org/pragma.html#pragma_secure_delete`; la
        ricostruzione dei record cancellati e' letteratura, vedi bring2lite, Forensic
        Science International: Digital Investigation, 2019). Un'informativa che promette
        la cancellazione deve restare vera anche aprendo il file con un editor
        esadecimale, quindi il contenuto si azzera.
        ⚠️ LIMITE DICHIARATO: in `journal_mode=WAL` tracce possono sopravvivere nel file
        `-wal` finche' non viene riassorbito, e il pragma non le raggiunge.
        ⛔ SOLLEVA su errore del database, come `nomi_uploads`: il chiamante e'
        fail-closed e deve poter trattenere la riga invece di darla per cancellata.
        """
        if not (isinstance(prenotazione_id, str) and prenotazione_id):
            return 0
        con = self._apri()
        try:
            try:
                con.execute("PRAGMA secure_delete=ON")
            except sqlite3.Error:
                logger.warning("secure_delete non applicabile su questo database")
            with con:
                cur = con.execute("DELETE FROM messaggi WHERE prenotazione_id=?",
                                  (str(prenotazione_id),))
            return cur.rowcount if (cur.rowcount and cur.rowcount > 0) else 0
        finally:
            con.close()

    def prenotazioni_con_ultimo_messaggio(self, *, limit: int = 200) -> List[Dict[str, Any]]:
        """Una riga per conversazione: la prenotazione e la data dell'ULTIMO messaggio.

        ⛔ PARTE DALLE CHAT, e il verso non e' indifferente. Girando sulle prenotazioni,
        una conversazione la cui riga di prenotazione e' stata purgata non sarebbe piu'
        raggiungibile da nessuno, e resterebbe in eterno senza che niente lo dica: la
        promessa dell'informativa vale per OGNI chat, non per quelle ancora agganciate.
        Le piu' vecchie prima, cosi' il tetto per passata non lascia indietro le scadute.
        ⛔ SOLLEVA su errore del database: il chiamante e' fail-closed."""
        lim = limit if (isinstance(limit, int) and not isinstance(limit, bool)
                        and 0 < limit <= 5000) else 200
        con = self._apri()
        try:
            rows = con.execute(
                "SELECT prenotazione_id, MAX(ts) AS ultimo_ts, COUNT(*) AS n "
                "FROM messaggi GROUP BY prenotazione_id "
                "ORDER BY ultimo_ts LIMIT ?", (lim,)).fetchall()
            return [{"prenotazione_id": p, "ultimo_ts": int(t or 0), "messaggi": int(n)}
                    for p, t, n in rows]
        finally:
            con.close()

    def conta_messaggi_host(self, host_id: Any) -> int:
        if not (isinstance(host_id, str) and host_id):
            return 0
        con = self._apri()
        try:
            r = con.execute("SELECT COUNT(*) FROM messaggi WHERE host_id=?",
                            (host_id,)).fetchone()
            return int(r[0]) if r else 0
        finally:
            con.close()

    def invia(self, prenotazione_id: str, host_id: str, guest_id: str,
              mittente: str, testo: Any) -> bool:
        if not (prenotazione_id and host_id and guest_id and mittente):
            return False
        if mittente not in (host_id, guest_id):
            return False                                  # mittente fuori dal thread
        if not isinstance(testo, str) or not testo.strip():
            return False
        corpo = maschera_pii(testo.strip()[:MAX_TESTO])
        con = self._apri()
        try:
            with con:
                con.execute("INSERT INTO messaggi (prenotazione_id, host_id, guest_id, "
                            "mittente, testo, ts) VALUES (?,?,?,?,?,?)",
                            (str(prenotazione_id), str(host_id), str(guest_id),
                             str(mittente), corpo, self._now()))
            return True
        except Exception:
            logger.warning("invia messaggio fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()

    def nomi_uploads(self) -> set:
        """Basename dei file /uploads/ citati nelle chat (prove foto). Per la pulizia
        orfani: SOLLEVA su errore DB — il chiamante e' fail-closed."""
        import re as _re
        con = self._apri()
        try:
            rows = con.execute("SELECT testo FROM messaggi "
                               "WHERE testo LIKE '%/uploads/%'").fetchall()
            out: set = set()
            for (t,) in rows:
                out.update(_re.findall(r"/uploads/([A-Za-z0-9_.\-]+)", str(t)))
            return out
        finally:
            con.close()

    def conversazioni_host(self, host_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
        """Le conversazioni dell'HOST (per il pannello: si caricano DA SOLE, niente codici da
        digitare): una riga per prenotazione con ultimo messaggio e conteggio."""
        if not (isinstance(host_id, str) and host_id):
            return []
        lim = limit if isinstance(limit, int) and 0 < limit <= 200 else 50
        con = self._apri()
        try:
            rows = con.execute(
                "SELECT prenotazione_id, COUNT(*) AS n, MAX(id) AS ultimo_id "
                "FROM messaggi WHERE host_id=? GROUP BY prenotazione_id "
                "ORDER BY ultimo_id DESC LIMIT ?", (host_id, lim)).fetchall()
            out = []
            for pren, n, uid in rows:
                u = con.execute("SELECT mittente, testo, ts FROM messaggi WHERE id=?",
                                (uid,)).fetchone()
                out.append({"prenotazione_id": pren, "messaggi": int(n),
                            "ultimo_mittente": u[0], "ultimo_testo": u[1], "ultimo_ts": u[2]})
            return out
        except Exception:
            logger.warning("conversazioni_host fallita (ISOLATA)", exc_info=True)
            return []
        finally:
            con.close()

    def thread(self, prenotazione_id: str, richiedente: str) -> List[Dict[str, Any]]:
        if not (prenotazione_id and richiedente):
            return []
        con = self._apri()
        try:
            rows = con.execute(
                "SELECT mittente, testo, ts, host_id, guest_id FROM messaggi "
                "WHERE prenotazione_id=? ORDER BY id",
                (str(prenotazione_id),)).fetchall()
            out = []
            for m, t, ts, h, g in rows:
                if richiedente not in (h, g):
                    return []                             # estraneo: niente accesso
                out.append({"mittente": m, "testo": t, "ts": ts})
            return out
        except Exception:
            logger.warning("thread fallita (ISOLATA)", exc_info=True)
            return []
        finally:
            con.close()

    def segna_letti(self, prenotazione_id: str, lettore: str) -> int:
        if not (prenotazione_id and lettore):
            return 0
        con = self._apri()
        try:
            with con:
                cur = con.execute("UPDATE messaggi SET letto=1 WHERE prenotazione_id=? "
                                  "AND mittente!=? AND letto=0",
                                  (str(prenotazione_id), str(lettore)))
            return cur.rowcount
        except Exception:
            logger.warning("segna_letti: errore DB (ISOLATO)", exc_info=True)
            return 0
        finally:
            con.close()


def crea_messaggistica(percorso: str, *, orologio: Any = None) -> Messaggistica:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return Messaggistica(lambda: _ConnCondivisa(con), orologio=orologio)
    return Messaggistica(lambda: sqlite3.connect(percorso, timeout=30), orologio=orologio)
