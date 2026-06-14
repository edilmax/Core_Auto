#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FASE 13/14 - Protocollo finale: sicurezza, self-healing, ottimizzazione DB.
=============================================================================

Modulo operativo importabile da `app.py` (livello API/Flask). Contiene:
  - Config              : caricamento configurazione da variabili d'ambiente.
  - SecurityManager     : firma/verifica HMAC-SHA256 + decoratore X-API-Key.
  - DeepSeekIndexing    : creazione indici compositi avanzati + ANALYZE.
  - SelfHealingManager  : health-check del sistema (DB + memoria via psutil).

Nessuna dipendenza hard da Flask all'import: `flask` viene importato solo
quando il decoratore `require_api_key` viene effettivamente eseguito in un
contesto di richiesta, cosi' il modulo resta importabile anche senza Flask
installato (es. nei test del core).
"""

import os
import time
import hmac
import secrets
import sqlite3
import functools

import psutil


# ---------------------------------------------------------------------------
# 1. Configurazione
# ---------------------------------------------------------------------------
class Config:
    """Carica la configurazione dalle variabili d'ambiente (os.environ).

    Gli attributi sono valutati a livello di classe (pattern stile Flask). Se le
    variabili cambiano a runtime si puo' forzare la rilettura con `ricarica()`.
    """

    HMAC_SECRET = os.environ.get("HMAC_SECRET", "")
    API_KEY = os.environ.get("API_KEY", "")
    BEARER_TOKEN = os.environ.get("BEARER_TOKEN", "")
    DB_PATH = os.environ.get("DB_PATH", "marketplace.db")
    # Flag booleano: "true"/"1"/"yes"/"on" -> True (default attivo).
    DEEPSEEK_INDEXING = os.environ.get("DEEPSEEK_INDEXING", "true").strip().lower() \
        in ("1", "true", "yes", "on")

    @classmethod
    def ricarica(cls) -> None:
        """Rilegge le variabili d'ambiente (utile dopo load_dotenv o nei test)."""
        cls.HMAC_SECRET = os.environ.get("HMAC_SECRET", "")
        cls.API_KEY = os.environ.get("API_KEY", "")
        cls.BEARER_TOKEN = os.environ.get("BEARER_TOKEN", "")
        cls.DB_PATH = os.environ.get("DB_PATH", "marketplace.db")
        cls.DEEPSEEK_INDEXING = os.environ.get(
            "DEEPSEEK_INDEXING", "true").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# 2. Sicurezza: firma HMAC + protezione API key
# ---------------------------------------------------------------------------
class SecurityManager:
    """Firma/verifica dei payload (HMAC-SHA256) e protezione degli endpoint."""

    @staticmethod
    def generate_signature(payload, timestamp) -> str:
        """Genera la firma HMAC-SHA256 di `timestamp.payload` con HMAC_SECRET.
        Accetta payload come str o bytes; timestamp str/int."""
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        messaggio = f"{timestamp}.{payload}".encode("utf-8")
        chiave = Config.HMAC_SECRET.encode("utf-8")
        return hmac.new(chiave, messaggio, "sha256").hexdigest()

    @staticmethod
    def verify_signature(payload, timestamp, signature) -> bool:
        """Verifica la firma in modo costante-nel-tempo (anti timing-attack)."""
        atteso = SecurityManager.generate_signature(payload, timestamp)
        try:
            return hmac.compare_digest(atteso, signature or "")
        except (TypeError, ValueError):
            return False

    @staticmethod
    def require_api_key(func):
        """Decoratore Flask: consente l'accesso solo se l'header `X-API-Key`
        coincide con Config.API_KEY (confronto costante con secrets.compare_digest).
        Flask e' importato qui dentro per non vincolare l'import del modulo."""

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            from flask import request, jsonify  # import lazy
            chiave_ricevuta = request.headers.get("X-API-Key", "")
            atteso = Config.API_KEY or ""
            # compare_digest evita differenze di timing; richiede chiave non vuota.
            if not atteso or not secrets.compare_digest(chiave_ricevuta, atteso):
                return jsonify({"error": "unauthorized",
                                "message": "API key mancante o non valida."}), 401
            return func(*args, **kwargs)

        return wrapper


# ---------------------------------------------------------------------------
# 3. Ottimizzazione DB: indici avanzati
# ---------------------------------------------------------------------------
class DeepSeekIndexing:
    """Crea indici compositi avanzati sull'audit log e aggiorna le statistiche
    del query planner (ANALYZE)."""

    INDICI = (
        ("idx_audit_entita_data",
         "CREATE INDEX IF NOT EXISTS idx_audit_entita_data "
         "ON audit_logs(entita_tipo, entita_id, data_creazione)"),
        ("idx_audit_operatore",
         "CREATE INDEX IF NOT EXISTS idx_audit_operatore "
         "ON audit_logs(utente_tipo, utente_id)"),
        ("idx_audit_data_solo",
         "CREATE INDEX IF NOT EXISTS idx_audit_data_solo "
         "ON audit_logs(data_creazione)"),
    )

    @staticmethod
    def init_advanced_indices(db_path: str) -> dict:
        """Connette al DB, crea gli indici compositi (idempotenti) e lancia
        ANALYZE. Restituisce un riepilogo {indici_creati, analyze, esito}."""
        risultato = {"indici": [], "analyze": False, "esito": "ok"}
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            for nome, ddl in DeepSeekIndexing.INDICI:
                cursor.execute(ddl)
                risultato["indici"].append(nome)
            conn.commit()
            cursor.execute("ANALYZE")
            conn.commit()
            risultato["analyze"] = True
        except sqlite3.Error as e:
            risultato["esito"] = f"errore: {e}"
            raise
        finally:
            conn.close()
        return risultato


# ---------------------------------------------------------------------------
# 4. Self-healing / health-check
# ---------------------------------------------------------------------------
class SelfHealingManager:
    """Monitoraggio dello stato del sistema: raggiungibilita' del DB e uso di
    memoria (processo + sistema) tramite psutil."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or Config.DB_PATH

    def _check_db(self) -> dict:
        """Verifica la connessione al DB con una query banale."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            try:
                conn.execute("SELECT 1")
            finally:
                conn.close()
            return {"connesso": True, "percorso": self.db_path}
        except sqlite3.Error as e:
            return {"connesso": False, "percorso": self.db_path, "errore": str(e)}

    def get_health(self) -> dict:
        """Restituisce lo stato di salute del sistema. 'status' e' 'healthy' se
        il DB risponde, altrimenti 'unhealthy'."""
        db = self._check_db()
        try:
            processo = psutil.Process()
            rss_mb = round(processo.memory_info().rss / (1024 * 1024), 2)
            vm = psutil.virtual_memory()
            memoria = {
                "processo_mb": rss_mb,
                "sistema_percentuale_usata": vm.percent,
                "sistema_disponibile_mb": round(vm.available / (1024 * 1024), 2),
            }
        except Exception as e:  # psutil non deve far cadere l'health-check
            memoria = {"errore": str(e)}

        return {
            "status": "healthy" if db.get("connesso") else "unhealthy",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "database": db,
            "memoria": memoria,
        }
