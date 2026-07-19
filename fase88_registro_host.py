"""
CORE_AUTO - Fase 88: Registro Host self-service (l'host si iscrive e si carica DA SOLO).

Il modello di BookinVIP è "niente dipendenti": nessuno deve onboardare gli host a mano.
Questo modulo permette all'host di **registrarsi da solo**, accettare i termini, e ricevere
un TOKEN firmato con cui gestisce SOLO i propri alloggi (non quelli altrui). Toglie il
lavoro manuale di registrazione: l'unico ingresso umano che restava sparisce.

Sicurezza (cablata):
  - Password con HASH PBKDF2-HMAC-SHA256 + salt casuale (stdlib hashlib), MAI in chiaro;
    confronto a tempo costante.
  - Email unica (un account per email); validazione email/password.
  - Accettazione termini OBBLIGATORIA e registrata (versione + timestamp) per il GDPR.
  - Token firmato HMAC (riusa fase59.FirmaQuote) con scadenza: prova "sono io" senza
    ri-mandare la password; l'host può agire solo come sé stesso (host_id nel token).
  - BLINDATO: nessun metodo solleva; input invalido -> esito motivato; fail-closed.

VINCITRICE DEL BENCHMARK (4 modi di gestire le credenziali host):
  V2 'PBKDF2+salt+token-firmato-con-scadenza'. Le altre perdono: V1 'password in chiaro' =
  catastrofe; V3 'hash veloce (sha256 nudo)' = crackabile in massa; V4 'sessioni in RAM' =
  si perdono al riavvio e non scalano multi-worker (il token firmato è stateless).

Denaro: nessuno qui (è autenticazione). Persistenza durevole conn-per-operazione + WAL.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import logging
import secrets
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional

from fase59_concierge import FirmaQuote

logger = logging.getLogger("core_auto.registro_host")

PBKDF2_ITER = 200_000
TTL_TOKEN_DEFAULT = 30 * 86400          # 30 giorni
TERMINI_VERSIONE_CORRENTE = "1.0"


def _email_valida(v: Any) -> bool:
    return (isinstance(v, str) and 3 <= len(v) <= 254 and v.count("@") == 1
            and "." in v.split("@")[-1] and " " not in v)


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                               PBKDF2_ITER).hex()


class EsitoHost:
    def __init__(self, ok: bool, host_id: str = "", token: str = "",
                 errore: str = "") -> None:
        self.ok = ok
        self.host_id = host_id
        self.token = token
        self.errore = errore

    def as_dict(self) -> Dict[str, Any]:
        if self.ok:
            return {"ok": True, "host_id": self.host_id, "token": self.token}
        return {"ok": False, "errore": self.errore}


class RegistroHost:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], firma: FirmaQuote,
                 *, orologio: Optional[Callable[[], int]] = None,
                 ttl_token: int = TTL_TOKEN_DEFAULT) -> None:
        self._conn_factory = conn_factory
        self._firma = firma
        self._now = orologio or (lambda: int(time.time()))
        self._ttl = ttl_token if isinstance(ttl_token, int) and ttl_token > 0 else TTL_TOKEN_DEFAULT
        self.inizializza_schema()

    def _apri(self) -> sqlite3.Connection:
        con = self._conn_factory()
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        return con

    def inizializza_schema(self) -> None:
        con = self._apri()
        try:
            with con:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS host (
                        host_id TEXT PRIMARY KEY,
                        email TEXT NOT NULL UNIQUE,
                        salt TEXT NOT NULL,
                        pw_hash TEXT NOT NULL,
                        ragione_sociale TEXT NOT NULL DEFAULT '',
                        telefono TEXT NOT NULL DEFAULT '',
                        line_token TEXT NOT NULL DEFAULT '',
                        wechat_webhook TEXT NOT NULL DEFAULT '',
                        telegram_chat_id TEXT NOT NULL DEFAULT '',
                        stripe_account_id TEXT NOT NULL DEFAULT '',
                        termini_versione TEXT NOT NULL,
                        termini_ts INTEGER NOT NULL,
                        stato TEXT NOT NULL DEFAULT 'attivo',
                        creato_ts INTEGER NOT NULL)""")
                # migrazione idempotente per DB esistenti (canali contatto host + DATI FISCALI
                # DAC7: codice fiscale/P.IVA, indirizzo, paese, IBAN, tipo soggetto, nascita)
                for col in ("telefono", "line_token", "wechat_webhook", "telegram_chat_id",
                            "stripe_account_id", "codice_fiscale", "partita_iva",
                            "indirizzo_fiscale", "paese", "iban", "tipo_soggetto",
                            "data_nascita"):
                    try:
                        con.execute("ALTER TABLE host ADD COLUMN %s TEXT NOT NULL DEFAULT ''" % col)
                    except sqlite3.OperationalError:
                        pass
        finally:
            con.close()

    def _token(self, host_id: str, email: str) -> str:
        return self._firma.codifica({"tipo": "host_token", "host_id": host_id,
                                     "email": email, "exp": self._now() + self._ttl})

    def registra(self, email: Any, password: Any, *, accetta_termini: bool = False,
                 ragione_sociale: str = "", telefono: str = "", line_token: str = "",
                 wechat_webhook: str = "",
                 versione_termini: str = TERMINI_VERSIONE_CORRENTE) -> EsitoHost:
        """L'host crea il proprio account. Fail-closed su ogni requisito mancante."""
        if not accetta_termini:
            return EsitoHost(False, errore="termini_non_accettati")
        if not _email_valida(email):
            return EsitoHost(False, errore="email_non_valida")
        if not (isinstance(password, str) and len(password) >= 8):
            return EsitoHost(False, errore="password_troppo_corta")  # min 8
        email_n = email.strip().lower()
        salt = secrets.token_bytes(16)
        pw_hash = _hash_password(password, salt)
        host_id = "h_" + secrets.token_hex(8)
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            esiste = con.execute("SELECT 1 FROM host WHERE email=?", (email_n,)).fetchone()
            if esiste is not None:
                con.execute("COMMIT")
                return EsitoHost(False, errore="email_gia_registrata")
            con.execute(
                "INSERT INTO host (host_id, email, salt, pw_hash, ragione_sociale, telefono, "
                "line_token, wechat_webhook, termini_versione, termini_ts, stato, creato_ts) "
                "VALUES (?,?,?,?,?,?,?,?,?,?, 'attivo', ?)",
                (host_id, email_n, salt.hex(), pw_hash, str(ragione_sociale or ""),
                 str(telefono or "").strip(), str(line_token or "").strip(),
                 str(wechat_webhook or "").strip(), str(versione_termini),
                 self._now(), self._now()))
            con.execute("COMMIT")
            return EsitoHost(True, host_id=host_id, token=self._token(host_id, email_n))
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            logger.warning("registra host fallita (ISOLATA)", exc_info=True)
            return EsitoHost(False, errore="errore_interno")
        finally:
            con.close()

    def login(self, email: Any, password: Any) -> EsitoHost:
        """L'host rientra con email+password e riceve un token fresco."""
        if not _email_valida(email) or not isinstance(password, str):
            return EsitoHost(False, errore="credenziali_non_valide")
        email_n = email.strip().lower()
        con = self._apri()
        try:
            r = con.execute("SELECT host_id, salt, pw_hash, stato FROM host WHERE email=?",
                            (email_n,)).fetchone()
        finally:
            con.close()
        if r is None:
            return EsitoHost(False, errore="credenziali_non_valide")    # niente leak utenti
        if r["stato"] != "attivo":
            return EsitoHost(False, errore="account_sospeso")
        atteso = r["pw_hash"]
        calcolato = _hash_password(password, bytes.fromhex(r["salt"]))
        if not hmac.compare_digest(atteso, calcolato):
            return EsitoHost(False, errore="credenziali_non_valide")
        return EsitoHost(True, host_id=r["host_id"],
                         token=self._token(r["host_id"], email_n))

    def verifica_token(self, token: Any) -> Optional[str]:
        """Ritorna l'host_id se il token è firmato, è un host_token e non è scaduto;
        altrimenti None. Verifica anche che l'account esista e sia attivo."""
        dati = self._firma.decodifica(token)
        if not isinstance(dati, dict) or dati.get("tipo") != "host_token":
            return None
        exp = dati.get("exp")
        if not isinstance(exp, int) or isinstance(exp, bool) or exp < self._now():
            return None
        host_id = dati.get("host_id")
        if not (isinstance(host_id, str) and host_id):
            return None
        con = self._apri()
        try:
            r = con.execute("SELECT stato FROM host WHERE host_id=?", (host_id,)).fetchone()
        finally:
            con.close()
        if r is None or r["stato"] != "attivo":
            return None
        return host_id

    def info_host(self, host_id: Any) -> Optional[Dict[str, str]]:
        """Contatti dell'host per le notifiche di prenotazione (email + telefono).
        None se l'host non esiste. Usato da fase152 per avvisare l'host."""
        if not (isinstance(host_id, str) and host_id):
            return None
        con = self._apri()
        try:
            r = con.execute("SELECT email, telefono, line_token, wechat_webhook, "
                            "telegram_chat_id, stripe_account_id, ragione_sociale, "
                            "codice_fiscale, partita_iva, indirizzo_fiscale, paese, iban, "
                            "tipo_soggetto, data_nascita "
                            "FROM host WHERE host_id=?",
                            (host_id,)).fetchone()
        finally:
            con.close()
        if r is None:
            return None
        g = lambda k: (r[k] if k in r.keys() and r[k] is not None else "")
        return {"email": r["email"] or "", "telefono": (r["telefono"] or ""),
                "line_token": (r["line_token"] or ""),
                "wechat_webhook": (r["wechat_webhook"] or ""),
                "telegram_chat_id": (r["telegram_chat_id"] or ""),
                "stripe_account_id": (r["stripe_account_id"] or ""),
                "ragione_sociale": (r["ragione_sociale"] or ""),
                "codice_fiscale": g("codice_fiscale"), "partita_iva": g("partita_iva"),
                "indirizzo_fiscale": g("indirizzo_fiscale"), "paese": g("paese"),
                "iban": g("iban"), "tipo_soggetto": g("tipo_soggetto"),
                "data_nascita": g("data_nascita")}

    # ── DATI FISCALI (DAC7): raccolta + audit di conformita' ────────────────
    CAMPI_FISCALI = ("codice_fiscale", "partita_iva", "indirizzo_fiscale", "paese",
                     "iban", "tipo_soggetto", "data_nascita")

    def imposta_dati_fiscali(self, host_id: Any, dati: Dict[str, Any]) -> bool:
        """Salva/aggiorna i dati fiscali dell'host (per DAC7). Scrive SOLO i campi forniti
        e non vuoti; validazione minima (lunghezze). Blindato."""
        if not (isinstance(host_id, str) and host_id and isinstance(dati, dict)):
            return False
        set_cols, par = [], []
        for c in self.CAMPI_FISCALI:
            v = dati.get(c)
            if isinstance(v, str) and v.strip():
                set_cols.append("%s=?" % c)
                par.append(v.strip()[:200])
        if not set_cols:
            return False
        par.append(host_id)
        con = self._apri()
        try:
            with con:
                cur = con.execute("UPDATE host SET %s WHERE host_id=?" % ", ".join(set_cols),
                                  par)
            return bool(cur.rowcount)
        except Exception:
            logger.warning("imposta_dati_fiscali fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()

    def elenco_host(self, *, limit: int = 5000) -> List[Dict[str, str]]:
        """Tutti gli host con i campi identita'+fiscali, per l'audit di conformita' DAC7.
        Read-only. NON include password/salt."""
        lim = limit if isinstance(limit, int) and 0 < limit <= 100000 else 5000
        con = self._apri()
        try:
            righe = con.execute(
                "SELECT host_id, email, ragione_sociale, stato, codice_fiscale, "
                "partita_iva, indirizzo_fiscale, paese, iban, tipo_soggetto "
                "FROM host ORDER BY creato_ts LIMIT ?", (lim,)).fetchall()
        finally:
            con.close()
        out = []
        for r in righe:
            g = lambda k: (r[k] if k in r.keys() and r[k] is not None else "")
            out.append({"host_id": r["host_id"], "email": r["email"] or "",
                        "ragione_sociale": r["ragione_sociale"] or "", "stato": r["stato"],
                        "codice_fiscale": g("codice_fiscale"), "partita_iva": g("partita_iva"),
                        "indirizzo_fiscale": g("indirizzo_fiscale"), "paese": g("paese"),
                        "iban": g("iban"), "tipo_soggetto": g("tipo_soggetto")})
        return out

    def imposta_stripe_account(self, host_id: Any, account_id: Any) -> bool:
        """Collega il conto Stripe Connect dell'host (per i bonifici automatici)."""
        if not (isinstance(host_id, str) and host_id):
            return False
        con = self._apri()
        try:
            with con:
                cur = con.execute("UPDATE host SET stripe_account_id=? WHERE host_id=?",
                                  (str(account_id or ""), host_id))
            return bool(cur.rowcount)
        except Exception:
            logger.warning("imposta_stripe_account fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()

    def imposta_telegram_chat(self, host_id: Any, chat_id: Any) -> bool:
        """Collega (o scollega, con chat_id vuoto) il Telegram dell'host per gli avvisi."""
        if not (isinstance(host_id, str) and host_id):
            return False
        con = self._apri()
        try:
            with con:
                cur = con.execute("UPDATE host SET telegram_chat_id=? WHERE host_id=?",
                                  (str(chat_id or ""), host_id))
            return bool(cur.rowcount)
        except Exception:
            logger.warning("imposta_telegram_chat fallita (ISOLATA)", exc_info=True)
            return False
        finally:
            con.close()

    def cancella_host(self, host_id: Any) -> int:
        """CANCELLAZIONE TOTALE dell'account host (diritto all'oblio / pulizia)."""
        if not (isinstance(host_id, str) and host_id):
            return 0
        con = self._apri()
        try:
            with con:
                cur = con.execute("DELETE FROM host WHERE host_id=?", (host_id,))
            return cur.rowcount if (cur.rowcount and cur.rowcount > 0) else 0
        finally:
            con.close()

    def esiste_host(self, host_id: Any) -> bool:
        if not (isinstance(host_id, str) and host_id):
            return False
        con = self._apri()
        try:
            r = con.execute("SELECT 1 FROM host WHERE host_id=?", (host_id,)).fetchone()
            return r is not None
        finally:
            con.close()

    def imposta_stato(self, host_id: str, stato: str) -> bool:
        if stato not in ("attivo", "sospeso"):
            return False
        con = self._apri()
        try:
            with con:
                cur = con.execute("UPDATE host SET stato=? WHERE host_id=?",
                                  (stato, str(host_id)))
            return cur.rowcount > 0
        finally:
            con.close()

    def conta_host(self) -> int:
        """Quanti host censiti (per metriche e DAC7)."""
        con = self._apri()
        try:
            r = con.execute("SELECT COUNT(*) FROM host").fetchone()
            return int(r[0]) if r else 0
        except Exception:
            logger.warning("conta_host fallita (ISOLATA -> 0)", exc_info=True)
            return 0
        finally:
            con.close()

    def numero_host(self, host_id: str) -> int:
        """Ordinale 1-based dell'host per ordine di registrazione (creato_ts, host_id).
        0 se l'host non esiste. Solo per metriche: la tariffa NON dipende dall'ordine
        (la leva è la rampa temporale di lancio, non l'ordinale)."""
        con = self._apri()
        try:
            row = con.execute("SELECT creato_ts FROM host WHERE host_id=?",
                              (str(host_id),)).fetchone()
            if not row:
                return 0
            ts = row[0]
            n = con.execute(
                "SELECT COUNT(*) FROM host WHERE creato_ts < ? "
                "OR (creato_ts = ? AND host_id <= ?)",
                (ts, ts, str(host_id))).fetchone()
            return int(n[0]) if n else 0
        except Exception:
            logger.warning("numero_host fallita (ISOLATA -> 0)", exc_info=True)
            return 0
        finally:
            con.close()

    def giorni_da_registrazione(self, host_id: Any, *, ora_ts: Any = None) -> int:
        """Giorni interi dalla registrazione dell'host (per la RAMPA di lancio della commissione).
        Host ignoto/errore -> numero molto grande (nessuno sconto lancio per sbaglio)."""
        import time as _t
        now = int(ora_ts) if isinstance(ora_ts, int) and not isinstance(ora_ts, bool) \
            else int(_t.time())
        con = self._apri()
        try:
            row = con.execute("SELECT creato_ts FROM host WHERE host_id=?",
                              (str(host_id),)).fetchone()
            if not row or not isinstance(row[0], int):
                return 10**9
            return max(0, (now - int(row[0])) // 86400)
        except Exception:
            logger.warning("giorni_da_registrazione fallita (ISOLATA -> grande)", exc_info=True)
            return 10**9
        finally:
            con.close()


class _ConnCondivisa:
    def __init__(self, con: sqlite3.Connection) -> None:
        object.__setattr__(self, "_con", con)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self._con.__enter__()

    def __exit__(self, *a):
        return self._con.__exit__(*a)

    def __getattr__(self, name):
        return getattr(self._con, name)

    def __setattr__(self, name, value):
        setattr(self._con, name, value)


def crea_registro_host(percorso: str, segreto: bytes, *,
                       orologio: Optional[Callable[[], int]] = None,
                       ttl_token: int = TTL_TOKEN_DEFAULT) -> RegistroHost:
    firma = FirmaQuote(segreto)
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return RegistroHost(lambda: _ConnCondivisa(con), firma, orologio=orologio,
                            ttl_token=ttl_token)
    return RegistroHost(lambda: sqlite3.connect(percorso), firma, orologio=orologio,
                        ttl_token=ttl_token)
