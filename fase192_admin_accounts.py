"""
CORE_AUTO - Fase 192: Account OPERATORE ADMIN con RUOLI (gestione permessi multi-admin).

Additivo e retro-compatibile: la `ADMIN_KEY` resta il SUPER-POTERE "root" (piena potenza, come
prima). Questi sono operatori AGGIUNTIVI con permessi LIMITATI per ruolo, che il super-admin
(bunker) crea/revoca/modifica. Cosi', quando arriva un team di supporto, ognuno ha il suo accesso
e l'audit log puo' dire CHI ha fatto cosa.

RUOLI:
  · 'admin'    → pieno (come la root, ma tracciato per persona);
  · 'supporto' → letture e assistenza (ricerca, prenotazioni, verifiche) ma NIENTE SOLDI
                 (rimborsi, storni, payout) e niente moderazione distruttiva.

Sicurezza: password PBKDF2-HMAC-SHA256 (200k iter) + salt per-account (mai in chiaro, mai nell'API).
Confronto in tempo COSTANTE (hmac.compare_digest). SQLite durevole. Stdlib puro, isolato,
idempotente. La revoca disattiva (non cancella): l'account resta nell'audit storico.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional

PBKDF2_ITER = 200_000
RUOLI = ("admin", "supporto")
# azioni RISERVATE al ruolo 'admin' (soldi / moderazione distruttiva): 'supporto' NON puo' farle
AZIONI_SOLO_ADMIN = ("rimborso", "storno_penale", "cancella_attivita",
                     "alloggio_stato", "controversia_risolvi", "blocco_globale")


def puo(ruolo: Any, azione: str) -> bool:
    """Il ruolo puo' compiere l'azione? admin=tutto; supporto=tutto TRANNE le azioni-soldi."""
    r = str(ruolo or "").strip().lower()
    if r == "admin":
        return True
    if r == "supporto":
        return str(azione) not in AZIONI_SOLO_ADMIN
    return False                     # ruolo ignoto -> nega (fail-closed)


def _hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt, PBKDF2_ITER).hex()


def _norm_email(e: Any) -> str:
    return str(e or "").strip().lower()


class AdminAccounts:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection],
                 *, orologio: Optional[Callable[[], int]] = None) -> None:
        self._cf = conn_factory
        self._now = orologio or (lambda: int(time.time()))
        self._init()

    def _apri(self) -> sqlite3.Connection:
        con = self._cf()
        try:
            con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        return con

    def _init(self) -> None:
        con = self._apri()
        try:
            with con:
                con.execute("""CREATE TABLE IF NOT EXISTS admin_account (
                    email TEXT PRIMARY KEY, salt TEXT NOT NULL, pw_hash TEXT NOT NULL,
                    ruolo TEXT NOT NULL, attivo INTEGER NOT NULL DEFAULT 1,
                    creato_ts INTEGER NOT NULL, creato_da TEXT NOT NULL DEFAULT '')""")
        finally:
            con.close()

    def crea(self, email: str, password: str, ruolo: str, *, creato_da: str = "root") -> Dict[str, Any]:
        em = _norm_email(email)
        if not em or "@" not in em:
            return {"ok": False, "errore": "email_non_valida"}
        if not (isinstance(password, str) and len(password) >= 8):
            return {"ok": False, "errore": "password_troppo_corta"}   # minimo 8
        if ruolo not in RUOLI:
            return {"ok": False, "errore": "ruolo_non_valido"}
        salt = os.urandom(16)
        con = self._apri()
        try:
            with con:
                con.execute("INSERT OR REPLACE INTO admin_account "
                            "(email, salt, pw_hash, ruolo, attivo, creato_ts, creato_da) "
                            "VALUES (?,?,?,?,1,?,?)",
                            (em, salt.hex(), _hash(password, salt), ruolo,
                             self._now(), str(creato_da)[:60]))
            return {"ok": True, "email": em, "ruolo": ruolo}
        except Exception:
            return {"ok": False, "errore": "db"}
        finally:
            con.close()

    def verifica(self, email: str, password: str) -> Dict[str, Any]:
        """Login: (ok, ruolo) se email+password corretti e account ATTIVO. Tempo costante."""
        em = _norm_email(email)
        con = self._apri()
        try:
            r = con.execute("SELECT salt, pw_hash, ruolo, attivo FROM admin_account WHERE email=?",
                            (em,)).fetchone()
        except Exception:
            r = None
        finally:
            con.close()
        if not r:
            _hash(password, b"x" * 16)               # confronto fittizio: non trapelare l'esistenza
            return {"ok": False, "errore": "credenziali_non_valide"}
        atteso = r[1]
        calcolato = _hash(password, bytes.fromhex(r[0]))
        if not hmac.compare_digest(atteso, calcolato):
            return {"ok": False, "errore": "credenziali_non_valide"}
        if not int(r[3]):
            return {"ok": False, "errore": "account_revocato"}
        return {"ok": True, "email": em, "ruolo": r[2]}

    def ruolo_attivo(self, email: str) -> Optional[str]:
        """Ruolo CORRENTE se l'account e' ATTIVO, altrimenti None. Serve a invalidare all'ISTANTE
        i token di un operatore appena revocato o a cui e' cambiato il ruolo (ri-lettura dal DB)."""
        con = self._apri()
        try:
            r = con.execute("SELECT ruolo, attivo FROM admin_account WHERE email=?",
                            (_norm_email(email),)).fetchone()
            return r[0] if (r and int(r[1])) else None
        except Exception:
            return None
        finally:
            con.close()

    def imposta_ruolo(self, email: str, ruolo: str) -> bool:
        if ruolo not in RUOLI:
            return False
        con = self._apri()
        try:
            with con:
                cur = con.execute("UPDATE admin_account SET ruolo=? WHERE email=?",
                                  (ruolo, _norm_email(email)))
            return cur.rowcount > 0
        except Exception:
            return False
        finally:
            con.close()

    def revoca(self, email: str) -> bool:
        """Disattiva (non cancella: resta nell'audit). Idempotente."""
        con = self._apri()
        try:
            with con:
                cur = con.execute("UPDATE admin_account SET attivo=0 WHERE email=?",
                                  (_norm_email(email),))
            return cur.rowcount > 0
        except Exception:
            return False
        finally:
            con.close()

    def riattiva(self, email: str) -> bool:
        con = self._apri()
        try:
            with con:
                cur = con.execute("UPDATE admin_account SET attivo=1 WHERE email=?",
                                  (_norm_email(email),))
            return cur.rowcount > 0
        except Exception:
            return False
        finally:
            con.close()

    def lista(self) -> List[Dict[str, Any]]:
        """Elenco account (MAI salt/hash: solo email, ruolo, attivo, quando/chi)."""
        con = self._apri()
        try:
            rows = con.execute("SELECT email, ruolo, attivo, creato_ts, creato_da "
                               "FROM admin_account ORDER BY creato_ts DESC").fetchall()
            return [{"email": x[0], "ruolo": x[1], "attivo": bool(x[2]),
                     "creato_ts": x[3], "creato_da": x[4]} for x in rows]
        except Exception:
            return []
        finally:
            con.close()


def crea_admin_accounts(percorso: str, *, orologio: Any = None) -> AdminAccounts:
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return AdminAccounts(lambda: _ConnCondivisa(con), orologio=orologio)
    return AdminAccounts(lambda: sqlite3.connect(percorso, timeout=30), orologio=orologio)


class _ConnCondivisa:
    """Wrapper per :memory: (una sola connessione condivisa, non chiudibile fra le chiamate)."""
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
