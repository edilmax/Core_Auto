"""
CORE_AUTO / Tavola VIP MVP - Fase 34: Motore Prenotazioni (overlap + atomica).

Espone il cuore del prodotto autonomo "Tavola VIP": creare una prenotazione di un
"tavolo" (= alloggio/risorsa nel DB: stessa logica risorsa+data+capacita') in modo
ATOMICO e con guardia ANTI-DOPPIA-PRENOTAZIONE basata su SOVRAPPOSIZIONE di date.

Due garanzie dure:
1. NIENTE DOPPIA PRENOTAZIONE: la disponibilita' e' verificata con un test di
   OVERLAP a intervalli semi-aperti [check_in, check_out) -> il turnover in giornata
   (check-out = check-in di un altro) NON e' un conflitto. La verifica e' rifatta
   DENTRO la transazione (BEGIN IMMEDIATE) per chiudere la finestra TOCTOU sotto
   concorrenza.
2. DENARO ESATTO: lo split (totale = commissione + quota_partner) e' in centesimi
   interi e validato da fase17.valida_split (zero float).

Compartimento stagno: opera sulle tabelle gia' esistenti (prenotazioni,
pagamenti_split, escrow_fondi) ma puo' anche crearle da solo (inizializza_schema)
per girare come prodotto indipendente. L'idempotenza della create e' fornita dal
layer HTTP (decoratore @idempotent di fase15); qui resta la mutua esclusione.
"""
from __future__ import annotations

import datetime
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

from fase17_money import valida_split

logger = logging.getLogger("core_auto.prenotazioni")

# Stati che OCCUPANO SEMPRE il tavolo. L'hold 'in_attesa_pagamento' occupa solo
# finche' NON e' scaduto (vedi hold_ttl_secondi); 'annullata'/'scaduta' liberano.
STATI_SEMPRE_BLOCCANTI = ("confermata", "pagata", "occupato")
STATO_INIZIALE = "in_attesa_pagamento"
STATO_SCADUTA = "scaduta"
HOLD_TTL_SECONDI_DEFAULT = 1800  # 30 minuti: un hold non pagato libera il tavolo


@dataclass(frozen=True)
class RichiestaPrenotazione:
    """Dati per creare una prenotazione. Importi in CENTESIMI interi (fase17)."""
    alloggio_id: str           # candidato_url = identita' del "tavolo"
    ospite_nome: str
    ospite_email: str
    check_in: str              # 'YYYY-MM-DD'
    check_out: str             # 'YYYY-MM-DD' (esclusa: intervallo semi-aperto)
    importo_totale_cents: int
    commissione_cents: int     # quota Tavola; quota_partner = totale - commissione
    origine: str = "diretto"


@dataclass(frozen=True)
class EsitoPrenotazione:
    ok: bool
    motivo: str                # "creata"|"non_disponibile"|"date_non_valide"|"importi_non_validi"
    prenotazione_id: Optional[int] = None
    pagamento_id: Optional[int] = None
    stato: str = ""


class MotorePrenotazioni:
    """Crea/annulla/conferma prenotazioni con guardia overlap e atomicita'.
    Connessione-per-operazione via `conn_factory` (come DistributedLockManager)."""

    def __init__(self, conn_factory: Callable[[], sqlite3.Connection],
                 hold_ttl_secondi: int = HOLD_TTL_SECONDI_DEFAULT) -> None:
        self._conn_factory = conn_factory
        self._hold_ttl = hold_ttl_secondi

    def _cutoff_hold(self) -> str:
        """Timestamp di taglio: un hold creato PRIMA di questo e' scaduto."""
        scad = datetime.datetime.now() - datetime.timedelta(seconds=self._hold_ttl)
        return scad.isoformat(timespec="seconds")

    # --- schema autonomo (idempotente, allineato al monolite) ---
    def inizializza_schema(self) -> None:
        con = self._apri()
        try:
            with con:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS prenotazioni (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        candidato_url TEXT, ospite_nome TEXT DEFAULT '',
                        ospite_email TEXT DEFAULT '', check_in TEXT DEFAULT '',
                        check_out TEXT DEFAULT '', stato TEXT DEFAULT 'richiesta',
                        origine TEXT DEFAULT '', uid_ical TEXT DEFAULT '',
                        data_creazione TEXT)""")
                con.execute("""
                    CREATE TABLE IF NOT EXISTS pagamenti_split (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        prenotazione_id INTEGER NOT NULL,
                        importo_totale INTEGER NOT NULL,
                        commissione_tavola INTEGER NOT NULL,
                        quota_partner INTEGER NOT NULL,
                        status TEXT DEFAULT 'pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (prenotazione_id)
                            REFERENCES prenotazioni(id) ON DELETE CASCADE)""")
                con.execute("""
                    CREATE TABLE IF NOT EXISTS escrow_fondi (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        pagamento_id INTEGER NOT NULL,
                        stato TEXT DEFAULT 'bloccato', data_sblocco TIMESTAMP,
                        FOREIGN KEY (pagamento_id)
                            REFERENCES pagamenti_split(id) ON DELETE CASCADE)""")
                con.execute("""
                    CREATE TABLE IF NOT EXISTS voucher_prenotazioni (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        prenotazione_id INTEGER UNIQUE,
                        codice_voucher TEXT UNIQUE,
                        pdf_path TEXT,
                        emesso_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (prenotazione_id)
                            REFERENCES prenotazioni(id) ON DELETE CASCADE)""")
                con.execute("CREATE INDEX IF NOT EXISTS idx_prenotazioni_overlap "
                            "ON prenotazioni(candidato_url, stato)")
        finally:
            con.close()

    def _apri(self) -> sqlite3.Connection:
        con = self._conn_factory()
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    # --- disponibilita' (test di OVERLAP a intervalli semi-aperti) ---
    @staticmethod
    def _date_valide(check_in: str, check_out: str) -> bool:
        try:
            ci = datetime.date.fromisoformat(check_in)
            co = datetime.date.fromisoformat(check_out)
        except (ValueError, TypeError):
            return False
        return ci < co  # almeno una notte; intervallo semi-aperto

    def disponibile(self, con: sqlite3.Connection, alloggio_id: str,
                    check_in: str, check_out: str,
                    escludi_id: Optional[int] = None) -> bool:
        """True se NESSUNA prenotazione bloccante si sovrappone a [check_in,
        check_out). Overlap fra [a_ci,a_co) e [b_ci,b_co): a_ci < b_co AND b_ci < a_co
        (turnover in giornata NON e' conflitto). Un hold 'in_attesa_pagamento'
        SCADUTO non blocca. `escludi_id` ignora una prenotazione (per la conferma)."""
        sempre = ",".join("?" * len(STATI_SEMPRE_BLOCCANTI))
        sql = (f"SELECT 1 FROM prenotazioni WHERE candidato_url=? "
               f"AND check_in < ? AND ? < check_out "
               f"AND ( stato IN ({sempre}) "
               f"      OR (stato=? AND data_creazione >= ?) )")  # hold non scaduto
        params = [alloggio_id, check_out, check_in, *STATI_SEMPRE_BLOCCANTI,
                  STATO_INIZIALE, self._cutoff_hold()]
        if escludi_id is not None:
            sql += " AND id <> ?"
            params.append(escludi_id)
        return con.execute(sql + " LIMIT 1", params).fetchone() is None

    # --- creazione ATOMICA ---
    def crea(self, r: RichiestaPrenotazione) -> EsitoPrenotazione:
        """Crea prenotazione + split + escrow in un'unica transazione. Ritorna
        l'esito; se il tavolo non e' libero -> non_disponibile (nessuna scrittura)."""
        if not self._date_valide(r.check_in, r.check_out):
            return EsitoPrenotazione(False, "date_non_valide")
        quota_partner = r.importo_totale_cents - r.commissione_cents
        try:
            valida_split(r.importo_totale_cents, r.commissione_cents, quota_partner)
        except ValueError:
            return EsitoPrenotazione(False, "importi_non_validi")

        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")  # mutua esclusione: chiude la TOCTOU
            if not self.disponibile(con, r.alloggio_id, r.check_in, r.check_out):
                con.execute("ROLLBACK")
                return EsitoPrenotazione(False, "non_disponibile")
            adesso = datetime.datetime.now().isoformat(timespec="seconds")
            cur = con.execute(
                "INSERT INTO prenotazioni (candidato_url, ospite_nome, ospite_email,"
                " check_in, check_out, stato, origine, data_creazione) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (r.alloggio_id, r.ospite_nome, r.ospite_email, r.check_in,
                 r.check_out, STATO_INIZIALE, r.origine, adesso))
            pren_id = cur.lastrowid
            cur = con.execute(
                "INSERT INTO pagamenti_split (prenotazione_id, importo_totale, "
                "commissione_tavola, quota_partner, status) VALUES (?,?,?,?, 'pending')",
                (pren_id, r.importo_totale_cents, r.commissione_cents, quota_partner))
            pag_id = cur.lastrowid
            con.execute("INSERT INTO escrow_fondi (pagamento_id, stato) "
                        "VALUES (?, 'bloccato')", (pag_id,))
            con.execute("COMMIT")
            return EsitoPrenotazione(True, "creata", pren_id, pag_id, STATO_INIZIALE)
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            logger.error("Prenotazione: errore in crea (-> rollback)", exc_info=True)
            raise
        finally:
            con.close()

    # --- conferma pagamento (chiamata dal webhook PSP) ---
    def conferma_pagamento(self, pagamento_id: int) -> Optional[int]:
        """Marca pagamento 'paid' e prenotazione 'pagata' (atomico). Idempotente:
        se gia' pagata, non cambia nulla. Ritorna l'id prenotazione (per il voucher)."""
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT prenotazione_id, status FROM pagamenti_split "
                              "WHERE id=?", (pagamento_id,)).fetchone()
            if row is None:
                con.execute("ROLLBACK")
                return None
            pren_id = row["prenotazione_id"]
            prow = con.execute("SELECT stato, candidato_url, check_in, check_out "
                               "FROM prenotazioni WHERE id=?", (pren_id,)).fetchone()
            if prow is None:
                con.execute("ROLLBACK")
                return None
            if prow["stato"] == "pagata":
                con.execute("ROLLBACK")        # gia' confermata: idempotente
                return pren_id
            # L'hold poteva scadere: confermo solo se il tavolo e' ANCORA libero
            # (escludendo me stesso). Altrimenti il pagamento va rimborsato a parte.
            if not self.disponibile(con, prow["candidato_url"], prow["check_in"],
                                    prow["check_out"], escludi_id=pren_id):
                con.execute("ROLLBACK")
                logger.warning("Conferma su tavolo gia' occupato (pren=%s): "
                               "pagamento da RIMBORSARE", pren_id)
                return None
            con.execute("UPDATE pagamenti_split SET status='paid' WHERE id=?",
                        (pagamento_id,))
            con.execute("UPDATE prenotazioni SET stato='pagata' WHERE id=?", (pren_id,))
            con.execute("COMMIT")
            return pren_id
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    def annulla(self, prenotazione_id: int) -> bool:
        """Annulla una prenotazione ancora in attesa di pagamento (libera il tavolo).
        Ritorna True se ha annullato qualcosa."""
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            cur = con.execute(
                "UPDATE prenotazioni SET stato='annullata' "
                "WHERE id=? AND stato=?", (prenotazione_id, STATO_INIZIALE))
            con.execute("COMMIT")
            return cur.rowcount > 0
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    def libera_hold_scaduti(self) -> int:
        """Housekeeping: marca 'scaduta' gli hold non pagati piu' vecchi del TTL
        (cosi' il conteggio resta pulito; la disponibilita' li ignora gia'). Da
        chiamare periodicamente. Ritorna quante prenotazioni ha liberato."""
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            cur = con.execute(
                "UPDATE prenotazioni SET stato=? "
                "WHERE stato=? AND data_creazione < ?",
                (STATO_SCADUTA, STATO_INIZIALE, self._cutoff_hold()))
            con.execute("COMMIT")
            return cur.rowcount
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    def emetti_voucher(self, prenotazione_id: int) -> Optional[str]:
        """Emette (o recupera) il voucher di una prenotazione PAGATA. Idempotente
        via UNIQUE(prenotazione_id): ri-emettere ritorna lo stesso codice."""
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT stato FROM prenotazioni WHERE id=?",
                              (prenotazione_id,)).fetchone()
            if row is None or row["stato"] != "pagata":
                con.execute("ROLLBACK")
                return None
            esistente = con.execute(
                "SELECT codice_voucher FROM voucher_prenotazioni WHERE prenotazione_id=?",
                (prenotazione_id,)).fetchone()
            if esistente is not None:
                con.execute("ROLLBACK")
                return esistente["codice_voucher"]
            codice = "VIP-" + uuid.uuid4().hex[:12].upper()
            con.execute("INSERT INTO voucher_prenotazioni (prenotazione_id, "
                        "codice_voucher) VALUES (?,?)", (prenotazione_id, codice))
            con.execute("COMMIT")
            return codice
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    def stato(self, prenotazione_id: int) -> Optional[dict]:
        con = self._apri()
        try:
            row = con.execute(
                "SELECT p.id, p.candidato_url, p.ospite_nome, p.ospite_email, "
                "p.check_in, p.check_out, p.stato, s.id AS pagamento_id, "
                "s.importo_totale, s.commissione_tavola, s.quota_partner, s.status "
                "FROM prenotazioni p LEFT JOIN pagamenti_split s "
                "ON s.prenotazione_id = p.id WHERE p.id=?",
                (prenotazione_id,)).fetchone()
            return dict(row) if row else None
        finally:
            con.close()
