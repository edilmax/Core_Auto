"""
CORE_AUTO - Fase 177: FINANCIAL CONTROLLER (Scatto ①: Giornale + Note + Offset).

Il motore contabile di BookinVIP. Principio: il LIBRO GIORNALE e' l'UNICA verita';
note e debiti sono stato derivato, ricostruibile. Nessun movimento senza audit.

  ① LIBRO GIORNALE append-only:
     - immutabilita' FORZATA DAL DATABASE (trigger che abortiscono UPDATE/DELETE:
       nessun bug applicativo puo' alterare una riga);
     - CATENA DI HASH (ogni riga incorpora l'hash della precedente, precedente di
       casa: fase163): chi riscrivesse il file a mano — perfino droppando i trigger —
       rompe la catena e `verifica_catena()` lo urla. Limite onesto: root puo'
       distruggere tutto; contro quello valgono i backup orari + l'ancora esterna
       (hash di testa nel backup), non il codice;
     - IDEMPOTENZA per evento_id (UNIQUE): un replay non scrive due volte;
     - ZERO PII (solo id pseudonimi) -> l'erasure GDPR (fase156) non deve MAI
       toccare il libro contabile: niente conflitto legge-vs-immutabilita'.
  ② NOTE di credito/debito: documenti numerati ND-/NC-<anno>-<progressivo>, vincolate
     a [riferimento transazione, causale, timestamp, emittente]; correzione = STORNO
     (nota contraria), mai modifica.
  ③ OFFSET automatico (gerarchia penali, gradino a): la penale 15% si compensa dai
     payout 'maturato' dell'host (fase131), STESSA valuta, FIFO, anche parziale;
     il residuo apre un DEBITO (gradini b/c negli scatti successivi).

Soldi SEMPRE in centesimi interi. BEGIN IMMEDIATE sulle scritture. Connessione per
chiamata. Orologio iniettabile. Blindato: errore -> esito False/None, mai eccezioni
verso il chiamante del money-path.
"""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("core_auto.financial_controller")

TIPI_GIORNALE = ("nota_debito", "nota_credito", "penale_offset", "penale_incassata",
                 "storno", "debt_on", "debt_off",
                 # movimenti di denaro "ordinari" (log immutabile di TUTTO, non solo penali):
                 "incasso", "payout_host", "payout_manuale", "rimborso",
                 "tassa_incassata", "tassa_stornata")

# mappatura tipo -> (conto_dare, conto_avere) per i movimenti ordinari: partita doppia
# leggibile a colpo d'occhio nell'audit (cassa piattaforma vs debiti verso host/ospite/comune).
_CONTI_MOVIMENTO = {
    "incasso":         ("cassa_piattaforma", "debiti_vs_host"),      # entra denaro ospite
    "payout_host":     ("debiti_vs_host", "cassa_piattaforma"),      # esce verso l'host (auto)
    "payout_manuale":  ("debiti_vs_host", "cassa_piattaforma"),      # transfer fallito -> manuale
    "rimborso":        ("debiti_vs_ospite", "cassa_piattaforma"),    # esce verso l'ospite
    "tassa_incassata": ("cassa_piattaforma", "debiti_vs_comune"),    # quota tassa trattenuta
    "tassa_stornata":  ("debiti_vs_comune", "cassa_piattaforma"),    # tassa restituita
}


def _cent(v: Any) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


class FinancialController:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], *,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._cf = conn_factory
        self._now = orologio or (lambda: int(time.time()))

    def _apri(self) -> sqlite3.Connection:
        con = self._cf()
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA foreign_keys=ON")
        except sqlite3.Error:
            pass
        return con

    # ── schema ──────────────────────────────────────────────────────────────
    def inizializza_schema(self) -> None:
        con = self._apri()
        try:
            with con:
                con.execute("""CREATE TABLE IF NOT EXISTS libro_giornale (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    evento_id TEXT NOT NULL UNIQUE,
                    ts INTEGER NOT NULL,
                    tipo TEXT NOT NULL,
                    riferimento TEXT NOT NULL,
                    soggetto TEXT NOT NULL,
                    conto_dare TEXT NOT NULL,
                    conto_avere TEXT NOT NULL,
                    importo_cents INTEGER NOT NULL CHECK (importo_cents > 0),
                    valuta TEXT NOT NULL,
                    causale TEXT NOT NULL,
                    emittente TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    hash TEXT NOT NULL)""")
                # IMMUTABILITA' nel DB stesso: qualsiasi UPDATE/DELETE abortisce.
                con.execute("""CREATE TRIGGER IF NOT EXISTS lg_no_update
                    BEFORE UPDATE ON libro_giornale
                    BEGIN SELECT RAISE(ABORT, 'libro giornale: UPDATE vietato'); END""")
                con.execute("""CREATE TRIGGER IF NOT EXISTS lg_no_delete
                    BEFORE DELETE ON libro_giornale
                    BEGIN SELECT RAISE(ABORT, 'libro giornale: DELETE vietato'); END""")
                con.execute("CREATE INDEX IF NOT EXISTS ix_lg_rif "
                            "ON libro_giornale(riferimento)")
                con.execute("CREATE INDEX IF NOT EXISTS ix_lg_soggetto "
                            "ON libro_giornale(soggetto)")
                con.execute("""CREATE TABLE IF NOT EXISTS note (
                    nota_id TEXT PRIMARY KEY,
                    tipo TEXT NOT NULL CHECK (tipo IN ('credito','debito')),
                    riferimento TEXT NOT NULL,
                    causale TEXT NOT NULL,
                    ts INTEGER NOT NULL,
                    emittente TEXT NOT NULL,
                    soggetto TEXT NOT NULL,
                    importo_cents INTEGER NOT NULL CHECK (importo_cents > 0),
                    valuta TEXT NOT NULL,
                    stato TEXT NOT NULL DEFAULT 'emessa',
                    storno_di TEXT,
                    giornale_seq INTEGER NOT NULL)""")
                con.execute("CREATE INDEX IF NOT EXISTS ix_note_rif ON note(riferimento)")
                con.execute("""CREATE TABLE IF NOT EXISTS debiti (
                    debito_id TEXT PRIMARY KEY,
                    host_id TEXT NOT NULL,
                    riferimento TEXT NOT NULL,
                    residuo_cents INTEGER NOT NULL CHECK (residuo_cents >= 0),
                    valuta TEXT NOT NULL,
                    stato TEXT NOT NULL,
                    tentativi INTEGER NOT NULL DEFAULT 0,
                    prossimo_ts INTEGER,
                    aggiornato_ts INTEGER NOT NULL)""")
                con.execute("CREATE INDEX IF NOT EXISTS ix_debiti_host "
                            "ON debiti(host_id, stato)")
        finally:
            con.close()

    # ── giornale ────────────────────────────────────────────────────────────
    @staticmethod
    def _canonico(evento_id: str, ts: int, tipo: str, riferimento: str, soggetto: str,
                  dare: str, avere: str, importo: int, valuta: str, causale: str,
                  emittente: str, prev_hash: str) -> str:
        return "|".join([evento_id, str(ts), tipo, riferimento, soggetto, dare, avere,
                         str(importo), valuta, causale, emittente, prev_hash])

    def registra(self, *, evento_id: str, tipo: str, riferimento: str, soggetto: str,
                 conto_dare: str, conto_avere: str, importo_cents: int, valuta: str,
                 causale: str, emittente: str) -> Optional[Dict[str, Any]]:
        """Appende UNA riga al giornale (BEGIN IMMEDIATE: lettura dell'ultimo hash e
        scrittura sono atomiche -> la catena non si biforca nemmeno sotto gara).
        Idempotente su evento_id: un replay ritorna la riga gia' scritta."""
        imp = _cent(importo_cents)
        if not (evento_id and tipo in TIPI_GIORNALE and riferimento and soggetto
                and imp > 0 and isinstance(valuta, str) and len(valuta) == 3):
            return None
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            gia = con.execute("SELECT seq, hash, importo_cents FROM libro_giornale "
                              "WHERE evento_id=?", (evento_id,)).fetchone()
            if gia is not None:
                con.execute("ROLLBACK")
                return {"seq": int(gia["seq"]), "hash": gia["hash"],
                        "importo_cents": int(gia["importo_cents"]), "idempotente": True}
            ultimo = con.execute("SELECT hash FROM libro_giornale "
                                 "ORDER BY seq DESC LIMIT 1").fetchone()
            prev = ultimo["hash"] if ultimo else "GENESI"
            ts = self._now()
            h = hashlib.sha256(self._canonico(
                evento_id, ts, tipo, riferimento, soggetto, conto_dare, conto_avere,
                imp, valuta, causale, emittente, prev).encode("utf-8")).hexdigest()
            cur = con.execute(
                "INSERT INTO libro_giornale (evento_id, ts, tipo, riferimento, soggetto,"
                " conto_dare, conto_avere, importo_cents, valuta, causale, emittente,"
                " prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (evento_id, ts, tipo, riferimento, soggetto, conto_dare, conto_avere,
                 imp, valuta, causale, emittente, prev, h))
            con.execute("COMMIT")
            return {"seq": int(cur.lastrowid), "hash": h, "idempotente": False}
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            logger.error("giornale: registrazione fallita", exc_info=True)
            return None
        finally:
            con.close()

    def movimento(self, *, tipo: str, riferimento: str, soggetto: str,
                  importo_cents: int, valuta: str, causale: str,
                  evento_id: Optional[str] = None, emittente: str = "sistema"
                  ) -> Optional[Dict[str, Any]]:
        """Registra un MOVIMENTO DI DENARO ordinario nel giornale immutabile (incasso,
        bonifico host, rimborso, tassa). E' la scatola nera che NON si perde a un deploy:
        risponde a 'ma il bonifico e' partito?' con una riga hash-incatenata e datata.
        Idempotente su evento_id (default 'tipo:riferimento' -> un retract/retry non
        raddoppia). Best-effort per il chiamante: mai deve rompere il money-path, quindi
        chi lo chiama lo avvolge in try (qui ritorna None su input non valido)."""
        conti = _CONTI_MOVIMENTO.get(tipo)
        if conti is None:
            return None
        ev = evento_id or ("%s:%s" % (tipo, riferimento))
        return self.registra(evento_id=ev, tipo=tipo, riferimento=riferimento,
                             soggetto=soggetto, conto_dare=conti[0], conto_avere=conti[1],
                             importo_cents=importo_cents, valuta=valuta,
                             causale=causale, emittente=emittente)

    def verifica_catena(self) -> Dict[str, Any]:
        """Ricalcola TUTTA la catena: ogni manomissione (anche con i trigger droppati
        e il file riscritto a mano) rompe un anello e viene puntata per seq."""
        con = self._apri()
        try:
            prev = "GENESI"
            for r in con.execute("SELECT * FROM libro_giornale ORDER BY seq"):
                atteso = hashlib.sha256(self._canonico(
                    r["evento_id"], int(r["ts"]), r["tipo"], r["riferimento"],
                    r["soggetto"], r["conto_dare"], r["conto_avere"],
                    int(r["importo_cents"]), r["valuta"], r["causale"], r["emittente"],
                    r["prev_hash"]).encode("utf-8")).hexdigest()
                if r["prev_hash"] != prev or r["hash"] != atteso:
                    return {"ok": False, "seq_rotta": int(r["seq"])}
                prev = r["hash"]
            return {"ok": True, "seq_rotta": None, "testa": prev}
        finally:
            con.close()

    def esiste_evento(self, evento_id: str) -> bool:
        """Lookup O(1) sull'UNIQUE (per la riasserzione dello sweeper: salta il lavoro
        gia' fatto senza rigiocare l'intero processa_penale)."""
        con = self._apri()
        try:
            r = con.execute("SELECT 1 FROM libro_giornale WHERE evento_id=?",
                            (evento_id,)).fetchone()
            return r is not None
        finally:
            con.close()

    def movimenti(self, riferimento: str) -> List[Dict[str, Any]]:
        con = self._apri()
        try:
            return [dict(r) for r in con.execute(
                "SELECT * FROM libro_giornale WHERE riferimento=? ORDER BY seq",
                (riferimento,))]
        finally:
            con.close()

    def aggrega_dac7(self, anno: int) -> Dict[str, Dict[str, Any]]:
        """Aggrega il giornale per host per l'ANNO fiscale (DAC7). Raggruppa i movimenti
        per riferimento = ricostruisce l'economia di OGNI prenotazione (lordo alloggio,
        tassa, netto all'host, rimborsi), la attribuisce all'anno/trimestre dell'INCASSO,
        e somma per host. Fonte: il giornale immutabile (verita' contabile). Ritorna
        {host_id: {n, lordo, netto, commissioni, tasse, rimborsi, trim{1..4}, trim_n{1..4}}}."""
        import datetime as _dt
        try:
            anno = int(anno)
        except Exception:
            return {}
        per_rif: Dict[str, Dict[str, Any]] = {}
        for r in self.stream_giornale():
            rif = r["riferimento"]
            tipo = r["tipo"]
            imp = int(r["importo_cents"] or 0)
            sog = r["soggetto"] or ""
            d = per_rif.setdefault(rif, {"host": "", "ts": None, "incasso": 0,
                                         "tassa": 0, "netto": 0, "rimborso": 0})
            if tipo == "incasso":
                d["incasso"] += imp
                d["ts"] = r["ts"]
                if sog.startswith("host:"):
                    d["host"] = sog[5:]
            elif tipo == "tassa_incassata":
                d["tassa"] += imp
            elif tipo in ("payout_host", "payout_manuale"):
                d["netto"] += imp
                if sog.startswith("host:") and not d["host"]:
                    d["host"] = sog[5:]
            elif tipo == "rimborso":
                d["rimborso"] += imp
        agg: Dict[str, Dict[str, Any]] = {}
        for rif, d in per_rif.items():
            if not d["host"] or d["ts"] is None:
                continue
            try:
                dt = _dt.datetime.utcfromtimestamp(int(d["ts"]))
            except Exception:
                continue
            if dt.year != anno:
                continue
            q = (dt.month - 1) // 3 + 1
            lordo = max(0, int(d["incasso"]) - int(d["tassa"]))     # corrispettivo alloggio
            netto = int(d["netto"])
            commiss = max(0, lordo - netto)
            h = agg.setdefault(d["host"], {
                "n": 0, "lordo": 0, "netto": 0, "commissioni": 0, "tasse": 0,
                "rimborsi": 0, "trim": {1: 0, 2: 0, 3: 0, 4: 0},
                "trim_n": {1: 0, 2: 0, 3: 0, 4: 0}})
            h["n"] += 1
            h["lordo"] += lordo
            h["netto"] += netto
            h["commissioni"] += commiss
            h["tasse"] += int(d["tassa"])
            h["rimborsi"] += int(d["rimborso"])
            h["trim"][q] += lordo
            h["trim_n"][q] += 1
        return agg

    def conta_movimenti(self) -> int:
        con = self._apri()
        try:
            r = con.execute("SELECT COUNT(*) FROM libro_giornale").fetchone()
            return int(r[0]) if r else 0
        finally:
            con.close()

    def stream_giornale(self):
        """GENERATORE LAZY: legge il giornale RIGA PER RIGA dal cursore SQLite e la
        restituisce (yield) una alla volta -> ZERO caricamento in RAM, anche con milioni
        di movimenti (il cursore SQLite e' pigro per natura). Per l'estratto fiscale in
        streaming (Incremento 4.1). La connessione si chiude a fine iterazione."""
        con = self._apri()
        try:
            cur = con.execute(
                "SELECT seq, evento_id, ts, tipo, riferimento, soggetto, conto_dare, "
                "conto_avere, importo_cents, valuta, causale, emittente, prev_hash, hash "
                "FROM libro_giornale ORDER BY seq")
            for r in cur:
                yield dict(r)
        finally:
            con.close()

    def esporta_tutti(self, *, limit: int = 200000, offset: int = 0
                      ) -> List[Dict[str, Any]]:
        """TUTTO il giornale in ordine cronologico (seq) per l'estratto contabile
        certificato (Centro Fiscale). Read-only. `limit` alto ma bounded (un estratto
        enorme si pagina); di default copre l'intera storia realistica."""
        lim = limit if (isinstance(limit, int) and not isinstance(limit, bool)
                        and 0 < limit <= 500000) else 200000
        off = offset if (isinstance(offset, int) and not isinstance(offset, bool)
                         and offset >= 0) else 0
        con = self._apri()
        try:
            return [dict(r) for r in con.execute(
                "SELECT seq, evento_id, ts, tipo, riferimento, soggetto, conto_dare, "
                "conto_avere, importo_cents, valuta, causale, emittente, hash "
                "FROM libro_giornale ORDER BY seq LIMIT ? OFFSET ?", (lim, off))]
        finally:
            con.close()

    # ── note di credito/debito ──────────────────────────────────────────────
    def _prossimo_nota_id(self, con: sqlite3.Connection, tipo: str, anno: int) -> str:
        pref = ("ND" if tipo == "debito" else "NC") + "-%d-" % anno
        r = con.execute("SELECT nota_id FROM note WHERE nota_id LIKE ? "
                        "ORDER BY nota_id DESC LIMIT 1", (pref + "%",)).fetchone()
        n = int(r["nota_id"].rsplit("-", 1)[1]) + 1 if r else 1
        return pref + "%06d" % n

    def emetti_nota(self, *, tipo: str, riferimento: str, soggetto: str,
                    importo_cents: int, valuta: str, causale: str, emittente: str,
                    evento_id: Optional[str] = None,
                    storno_di: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Emette una nota di credito/debito: il documento nasce INSIEME alla sua riga
        di giornale (prima il giornale: se quello fallisce, la nota NON esiste).
        `evento_id` esplicito = idempotenza di flusso (es. 'penale:<rif>': il doppio
        click non emette due note). Correzione = storno (nota contraria), mai modifica."""
        imp = _cent(importo_cents)
        if tipo not in ("credito", "debito") or imp <= 0 or not (riferimento and soggetto
                                                                 and causale and emittente):
            return None
        anno = time.gmtime(self._now()).tm_year
        ev = evento_id or ("nota:%s:%s:%d" % (tipo, riferimento, self._now()))
        # prima il GIORNALE (verita'); ritorna anche in replay (idempotente)
        dare, avere = (("crediti_vs_host", "ricavi_penali") if tipo == "debito"
                       else ("costi_rimborsi", "debiti_vs_soggetto"))
        mv = self.registra(evento_id=ev, tipo="nota_" + tipo, riferimento=riferimento,
                           soggetto=soggetto, conto_dare=dare, conto_avere=avere,
                           importo_cents=imp, valuta=valuta,
                           causale=causale, emittente=emittente)
        if mv is None:
            return None
        con = self._apri()
        try:
            if mv.get("idempotente"):
                r = con.execute("SELECT * FROM note WHERE giornale_seq=?",
                                (mv["seq"],)).fetchone()
                if r is not None:
                    return dict(r)
                # riga di giornale senza nota (crash a meta'): la nota si RIASSERISCE
            con.execute("BEGIN IMMEDIATE")
            nota_id = self._prossimo_nota_id(con, tipo, anno)
            con.execute("INSERT INTO note (nota_id, tipo, riferimento, causale, ts,"
                        " emittente, soggetto, importo_cents, valuta, stato, storno_di,"
                        " giornale_seq) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (nota_id, tipo, riferimento, causale, self._now(), emittente,
                         soggetto, imp, valuta, "emessa", storno_di, mv["seq"]))
            con.execute("COMMIT")
            return {"nota_id": nota_id, "tipo": tipo, "riferimento": riferimento,
                    "importo_cents": imp, "valuta": valuta, "stato": "emessa",
                    "giornale_seq": mv["seq"]}
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            logger.error("nota: emissione fallita (giornale gia' scritto: seq=%s)",
                         mv.get("seq"), exc_info=True)
            return None
        finally:
            con.close()

    def storna_nota(self, nota_id: str, *, emittente: str,
                    causale: str) -> Optional[Dict[str, Any]]:
        """Annulla una nota con la CONTRARIA (credito<->debito). La nota originale resta
        (append-only); il suo stato diventa 'stornata'."""
        con = self._apri()
        try:
            r = con.execute("SELECT * FROM note WHERE nota_id=?", (nota_id,)).fetchone()
        finally:
            con.close()
        if r is None or r["stato"] == "stornata":
            return None
        contraria = self.emetti_nota(
            tipo=("credito" if r["tipo"] == "debito" else "debito"),
            riferimento=r["riferimento"], soggetto=r["soggetto"],
            importo_cents=int(r["importo_cents"]), valuta=r["valuta"],
            causale="storno di %s: %s" % (nota_id, causale), emittente=emittente,
            evento_id="storno:%s" % nota_id, storno_di=nota_id)
        if contraria is None:
            return None
        con = self._apri()
        try:
            with con:
                con.execute("UPDATE note SET stato='stornata' WHERE nota_id=?", (nota_id,))
            return contraria
        finally:
            con.close()

    def nota(self, nota_id: str) -> Optional[Dict[str, Any]]:
        con = self._apri()
        try:
            r = con.execute("SELECT * FROM note WHERE nota_id=?", (nota_id,)).fetchone()
            return dict(r) if r else None
        finally:
            con.close()

    # ── debiti ──────────────────────────────────────────────────────────────
    def _debito_scrivi(self, debito_id: str, host_id: str, riferimento: str,
                       residuo: int, valuta: str, stato: str) -> None:
        con = self._apri()
        try:
            with con:
                con.execute("INSERT INTO debiti (debito_id, host_id, riferimento,"
                            " residuo_cents, valuta, stato, aggiornato_ts)"
                            " VALUES (?,?,?,?,?,?,?)"
                            " ON CONFLICT(debito_id) DO UPDATE SET residuo_cents=?,"
                            " stato=?, aggiornato_ts=?",
                            (debito_id, host_id, riferimento, residuo, valuta, stato,
                             self._now(), residuo, stato, self._now()))
        finally:
            con.close()

    def debiti_host(self, host_id: str, *, stato: Optional[str] = None
                    ) -> List[Dict[str, Any]]:
        con = self._apri()
        try:
            if stato:
                cur = con.execute("SELECT * FROM debiti WHERE host_id=? AND stato=?"
                                  " ORDER BY aggiornato_ts", (host_id, stato))
            else:
                cur = con.execute("SELECT * FROM debiti WHERE host_id=?"
                                  " ORDER BY aggiornato_ts", (host_id,))
            return [dict(r) for r in cur]
        finally:
            con.close()

    # ── MOTORE PENALI, Scatto ①: ND + OFFSET sui payout esistenti ───────────
    def processa_penale(self, *, riferimento: str, host_id: str, penale_cents: int,
                        valuta: str, payout: Any,
                        emittente: str = "sistema") -> Optional[Dict[str, Any]]:
        """Gerarchia penali, gradino (a). IDEMPOTENTE per riferimento:
          1) emette la ND 15% ('penale:<rif>': il giornale e' il vincolo atomico —
             senza questa riga la cancellazione NON riceve conferma);
          2) OFFSET: compensa dai payout 'maturato' dell'host (fase131), STESSA
             valuta, FIFO, mai il payout della prenotazione stessa; consumo pieno ->
             riga rimossa dal ledger (il giornale ne conserva la verita'), parziale ->
             importo riallineato;
          3) residuo -> debito 'aperto' (gradini b/c: scatti successivi).
        Ritorna {nota_id, penale_cents, offset_cents, residuo_cents} o None se il
        giornale non e' scrivibile (il chiamante decide il 503 onesto)."""
        imp = _cent(penale_cents)
        if imp <= 0 or not (riferimento and host_id):
            return None
        nota = self.emetti_nota(tipo="debito", riferimento=riferimento,
                                soggetto="host:" + host_id, importo_cents=imp,
                                valuta=valuta,
                                causale="penale 15% cancellazione host",
                                emittente=emittente, evento_id="penale:" + riferimento)
        if nota is None:
            return None
        # RESIDUO DALLA VERITA' DEL GIORNALE (principio del modulo): in replay le righe
        # payout gia' consumate NON esistono piu' -> ricalcolare da quelle direbbe il
        # falso. Si somma quanto gia' compensato (offset - storni) e si riparte da li'.
        storico = 0
        for m in self.movimenti(riferimento):
            ev = str(m.get("evento_id") or "")
            if (m.get("tipo") == "penale_offset"
                    and ev.startswith("offset:%s:" % nota["nota_id"])):
                storico += int(m.get("importo_cents") or 0)
            elif (m.get("tipo") == "storno"
                  and ev.startswith("storno-offset:%s:" % nota["nota_id"])):
                storico -= int(m.get("importo_cents") or 0)
        residuo = max(0, imp - max(0, storico))
        righe = []
        if residuo > 0:
            try:
                righe = payout.elenca(host_id, stato="maturato", valuta=valuta) or []
            except Exception:
                logger.warning("offset: lettura payout fallita (ISOLATA)", exc_info=True)
        for r in righe:
            if residuo <= 0:
                break
            pid = r.get("prenotazione_id")
            disp = _cent(r.get("minori"))
            if not pid or pid == riferimento or disp <= 0:
                continue
            quota = min(disp, residuo)
            mv = self.registra(evento_id="offset:%s:%s" % (nota["nota_id"], pid),
                               tipo="penale_offset", riferimento=riferimento,
                               soggetto="host:" + host_id,
                               conto_dare="debiti_vs_host_payout",
                               conto_avere="crediti_vs_host",
                               importo_cents=quota, valuta=valuta,
                               causale="compensazione penale su payout %s" % pid,
                               emittente=emittente)
            if mv is None:
                continue                     # giornale prima: senza riga, non si tocca
            if mv.get("idempotente"):
                continue                     # gia' contato nello storico dal giornale
            try:
                ok = (payout.imposta_importo(pid, disp - quota) if disp - quota > 0
                      else payout.rimuovi(pid))
            except Exception:
                ok = False
            if not ok:
                # ledger non allineato: STORNO immediato della riga di offset
                self.registra(evento_id="storno-offset:%s:%s" % (nota["nota_id"], pid),
                              tipo="storno", riferimento=riferimento,
                              soggetto="host:" + host_id,
                              conto_dare="crediti_vs_host",
                              conto_avere="debiti_vs_host_payout",
                              importo_cents=quota, valuta=valuta,
                              causale="storno offset: ledger payout non aggiornabile",
                              emittente="sistema")
                continue
            residuo -= quota
        offset_tot = imp - residuo           # storico (dal giornale) + nuovi consumi
        stato_nota = "saldata" if residuo == 0 else "emessa"
        con = self._apri()
        try:
            with con:
                con.execute("UPDATE note SET stato=? WHERE nota_id=?",
                            (stato_nota, nota["nota_id"]))
        finally:
            con.close()
        if residuo > 0:
            self._debito_scrivi(nota["nota_id"], host_id, riferimento, residuo,
                                valuta, "aperto")
        else:
            self._debito_scrivi(nota["nota_id"], host_id, riferimento, 0,
                                valuta, "saldato")
        return {"nota_id": nota["nota_id"], "penale_cents": imp,
                "offset_cents": offset_tot, "residuo_cents": residuo}

    def nota(self, nota_id: Any) -> Optional[Dict[str, Any]]:
        """AUDIT CONSOLE: una nota per id (ND-/NC-anno-progressivo). Read-only."""
        if not (isinstance(nota_id, str) and nota_id):
            return None
        con = self._apri()
        try:
            r = con.execute("SELECT * FROM note WHERE nota_id=?",
                            (nota_id.strip().upper(),)).fetchone()
            return dict(r) if r is not None else None
        except Exception:
            logger.warning("nota lookup fallito (ISOLATO)", exc_info=True)
            return None
        finally:
            con.close()

    def note_per_riferimento(self, riferimento: Any) -> List[Dict[str, Any]]:
        """AUDIT CONSOLE: tutte le note (ND/NC) di una prenotazione. Read-only (ix_note_rif)."""
        if not (isinstance(riferimento, str) and riferimento):
            return []
        con = self._apri()
        try:
            cur = con.execute("SELECT * FROM note WHERE riferimento=? ORDER BY ts",
                              (riferimento,))
            return [dict(r) for r in cur]
        except Exception:
            logger.warning("note_per_riferimento fallito (ISOLATO)", exc_info=True)
            return []
        finally:
            con.close()

    def somme_periodo(self, da_ts: int, *, a_ts: Optional[int] = None
                      ) -> Dict[str, Dict[str, int]]:
        """RICONCILIAZIONE (fase182): somme del giornale per tipo e valuta nel periodo.
        Read-only. {tipo: {valuta: cents}}."""
        try:
            da = int(da_ts)
            fino = int(a_ts) if a_ts is not None else None
        except (TypeError, ValueError):
            return {}
        con = self._apri()
        try:
            sql = ("SELECT tipo, valuta, SUM(importo_cents) FROM libro_giornale "
                   "WHERE ts >= ?")
            par: List[Any] = [da]
            if fino is not None:
                sql += " AND ts <= ?"
                par.append(fino)
            sql += " GROUP BY tipo, valuta"
            out: Dict[str, Dict[str, int]] = {}
            for tipo, val, tot in con.execute(sql, par):
                out.setdefault(str(tipo), {})[str(val)] = int(tot or 0)
            return out
        except Exception:
            logger.warning("somme_periodo fallita (ISOLATA)", exc_info=True)
            return {}
        finally:
            con.close()

    def incassi_periodo(self, da_ts: int, *, a_ts: Optional[int] = None
                        ) -> Dict[str, Dict[str, Any]]:
        """RICONCILIAZIONE: gli 'incasso' del periodo per riferimento (match con le
        sessioni Stripe pagate). Read-only. {riferimento: {'cents': n, 'valuta': v}}."""
        try:
            da = int(da_ts)
            fino = int(a_ts) if a_ts is not None else None
        except (TypeError, ValueError):
            return {}
        con = self._apri()
        try:
            sql = ("SELECT riferimento, valuta, SUM(importo_cents) FROM libro_giornale "
                   "WHERE tipo='incasso' AND ts >= ?")
            par: List[Any] = [da]
            if fino is not None:
                sql += " AND ts <= ?"
                par.append(fino)
            sql += " GROUP BY riferimento, valuta"
            out: Dict[str, Dict[str, Any]] = {}
            for rif, val, tot in con.execute(sql, par):
                out[str(rif)] = {"cents": int(tot or 0), "valuta": str(val)}
            return out
        except Exception:
            logger.warning("incassi_periodo fallita (ISOLATA)", exc_info=True)
            return {}
        finally:
            con.close()

    def debiti_aperti(self, *, limit: int = 500) -> List[Dict[str, Any]]:
        """TUTTI i debiti 'aperto' (sala controllo Bunker): quanto ci devono gli host."""
        lim = limit if isinstance(limit, int) and 0 < limit <= 2000 else 500
        con = self._apri()
        try:
            cur = con.execute("SELECT * FROM debiti WHERE stato='aperto'"
                              " ORDER BY aggiornato_ts LIMIT ?", (lim,))
            return [dict(r) for r in cur]
        except Exception:
            logger.warning("debiti_aperti fallita (ISOLATA)", exc_info=True)
            return []
        finally:
            con.close()

    # ── MOTORE PENALI, Scatto ②: RISCOSSIONE debiti aperti sui payout FUTURI ─
    def riscuoti_debiti(self, *, host_id: str, payout: Any,
                        emittente: str = "sistema") -> Dict[str, Any]:
        """Debt Status (gradino b): quando l'host ha debiti 'aperto' (penali non coperte
        al momento della cancellazione), i payout 'maturato' SUCCESSIVI li saldano ALLA
        FONTE, prima di ogni bonifico. FIFO sui debiti (il piu' vecchio prima) e FIFO sui
        payout, STESSA valuta, mai il payout della prenotazione del debito stesso.
        STESSO schema evento_id di processa_penale ('offset:<nota_id>:<pid>') -> replay e
        idempotenza gratis: un payout gia' consumato per una nota non si riconsuma MAI
        (il giornale rifiuta il doppione e qui si salta). Metodo AUTONOMO di proposito:
        non tocca processa_penale (money-path collaudato). Giornale prima del ledger,
        storno immediato se il ledger non si aggiorna (identico a Scatto ①).
        Ritorna {'riscossi_cents': n, 'debiti_saldati': k, 'debiti_aperti': j}."""
        esito = {"riscossi_cents": 0, "debiti_saldati": 0, "debiti_aperti": 0}
        if not (isinstance(host_id, str) and host_id) or payout is None:
            return esito
        try:
            aperti = self.debiti_host(host_id, stato="aperto")
        except Exception:
            logger.warning("riscuoti: lettura debiti fallita (ISOLATA)", exc_info=True)
            return esito
        for deb in aperti:
            nota_id = str(deb.get("debito_id") or "")
            rif_deb = str(deb.get("riferimento") or "")
            valuta = str(deb.get("valuta") or "EUR")
            residuo = _cent(deb.get("residuo_cents"))
            if not nota_id or residuo <= 0:
                continue
            try:
                righe = payout.elenca(host_id, stato="maturato", valuta=valuta) or []
            except Exception:
                logger.warning("riscuoti: lettura payout fallita (ISOLATA)", exc_info=True)
                righe = []
            for r in righe:
                if residuo <= 0:
                    break
                pid = r.get("prenotazione_id")
                disp = _cent(r.get("minori"))
                if not pid or pid == rif_deb or disp <= 0:
                    continue
                quota = min(disp, residuo)
                mv = self.registra(evento_id="offset:%s:%s" % (nota_id, pid),
                                   tipo="penale_offset", riferimento=rif_deb,
                                   soggetto="host:" + host_id,
                                   conto_dare="debiti_vs_host_payout",
                                   conto_avere="crediti_vs_host",
                                   importo_cents=quota, valuta=valuta,
                                   causale="riscossione debito su payout %s" % pid,
                                   emittente=emittente)
                if mv is None or mv.get("idempotente"):
                    continue          # giornale giu' O payout gia' consumato per la nota
                try:
                    ok = (payout.imposta_importo(pid, disp - quota) if disp - quota > 0
                          else payout.rimuovi(pid))
                except Exception:
                    ok = False
                if not ok:
                    self.registra(evento_id="storno-offset:%s:%s" % (nota_id, pid),
                                  tipo="storno", riferimento=rif_deb,
                                  soggetto="host:" + host_id,
                                  conto_dare="crediti_vs_host",
                                  conto_avere="debiti_vs_host_payout",
                                  importo_cents=quota, valuta=valuta,
                                  causale="storno riscossione: ledger payout non aggiornabile",
                                  emittente="sistema")
                    continue
                residuo -= quota
                esito["riscossi_cents"] += quota
            if residuo != _cent(deb.get("residuo_cents")):
                stato = "saldato" if residuo == 0 else "aperto"
                self._debito_scrivi(nota_id, host_id, rif_deb, residuo, valuta, stato)
                if residuo == 0:
                    esito["debiti_saldati"] += 1
                    con = self._apri()
                    try:
                        with con:
                            con.execute("UPDATE note SET stato='saldata' WHERE nota_id=?",
                                        (nota_id,))
                    finally:
                        con.close()
                    logger.warning("DEBITO SALDATO | HOST_ID: %s | NOTA: %s | "
                                   "riscosso alla fonte sui payout", host_id, nota_id)
            if residuo > 0:
                esito["debiti_aperti"] += 1
        return esito


    # ── MOTORE PENALI: STORNO (correzione = nota contraria, MAI modifica) ────
    def storna_penale(self, *, nota_id: Any, motivo: str = "", payout: Any = None,
                      emittente: str = "super-admin") -> Optional[Dict[str, Any]]:
        """STORNO di una penale sbagliata (tool Bunker-gated). Il giornale e' immutabile:
        non si cancella MAI nulla — si emette la NOTA DI CREDITO contraria (storno_di=ND)
        per l'intero importo. Passi (tutti idempotenti o protetti da chiave):
          1) NC contraria (evento_id 'storno-nota:<ND>': doppio click = UNO storno);
          2) ND -> stato 'stornata'; il suo debito -> residuo 0, stato 'stornato'
             (riscuoti_debiti non lo riprendera' MAI piu': filtra stato='aperto');
          3) RESTITUZIONE dell'eventuale gia' RISCOSSO (verita' dal giornale: offset
             della nota meno storni) -> riga payout 'maturato' `stornoND-<ND>` visibile
             in da_pagare per il bonifico MANUALE del fondatore (una correzione la firma
             un umano, mai un transfer automatico; PK fissa = zero doppi accrediti).
        Ritorna {'nota_id','nc_id','riscosso_cents','restituito_in_da_pagare',
        'gia_stornata'} o None (nota inesistente/non-ND o giornale non scrivibile)."""
        n = self.nota(nota_id)
        if n is None or n.get("tipo") != "debito":
            return None                       # si stornano SOLO le note di debito (ND)
        nid = str(n["nota_id"])
        if str(n.get("stato")) == "stornata":
            return {"nota_id": nid, "nc_id": None, "riscosso_cents": 0,
                    "restituito_in_da_pagare": 0, "gia_stornata": True}
        rif = str(n["riferimento"])
        val = str(n["valuta"])
        imp = _cent(n["importo_cents"])
        host_id = str(n.get("soggetto") or "").partition(":")[2]
        # quanto era GIA' stato riscosso: verita' dal giornale (offset - storni della nota)
        riscosso = 0
        for m in self.movimenti(rif):
            ev = str(m.get("evento_id") or "")
            if m.get("tipo") == "penale_offset" and ev.startswith("offset:%s:" % nid):
                riscosso += int(m.get("importo_cents") or 0)
            elif m.get("tipo") == "storno" and ev.startswith("storno-offset:%s:" % nid):
                riscosso -= int(m.get("importo_cents") or 0)
        riscosso = max(0, riscosso)
        nc = self.emetti_nota(tipo="credito", riferimento=rif,
                              soggetto="host:" + host_id, importo_cents=imp,
                              valuta=val,
                              causale=("storno penale %s: %s"
                                       % (nid, (motivo or "senza motivo")[:200])),
                              emittente=emittente,
                              evento_id="storno-nota:%s" % nid, storno_di=nid)
        if nc is None:
            return None                       # giornale non scrivibile -> 503 onesto
        con = self._apri()
        try:
            with con:
                con.execute("UPDATE note SET stato='stornata' WHERE nota_id=?", (nid,))
        finally:
            con.close()
        self._debito_scrivi(nid, host_id, rif, 0, val, "stornato")
        restituito = 0
        if riscosso > 0 and payout is not None:
            try:
                if payout.registra_maturato("stornoND-" + nid, host_id, riscosso, val):
                    restituito = riscosso     # PK fissa: un replay NON riaccredita
            except Exception:
                logger.warning("storno: restituzione in da_pagare fallita (ISOLATA: "
                               "il riscosso resta documentato nel giornale)",
                               exc_info=True)
        logger.warning("PENALE_STORNATA | NOTA: %s | NC: %s | HOST: %s | IMPORTO: %d | "
                       "RISCOSSO_DA_RESTITUIRE: %d | MOTIVO: %s | EMITTENTE: %s",
                       nid, nc.get("nota_id"), host_id, imp, riscosso,
                       (motivo or "-")[:120], emittente)
        return {"nota_id": nid, "nc_id": nc.get("nota_id"),
                "riscosso_cents": riscosso, "restituito_in_da_pagare": restituito,
                "gia_stornata": False}


def crea_financial_controller(percorso: str, *, orologio: Any = None
                              ) -> FinancialController:
    if percorso != ":memory:":
        genitore = os.path.dirname(os.path.abspath(percorso))
        if genitore:
            os.makedirs(genitore, exist_ok=True)   # lezione bug #36: il genitore si crea
        return FinancialController(lambda: sqlite3.connect(percorso), orologio=orologio)
    con = sqlite3.connect(":memory:", check_same_thread=False)
    import threading
    _lock = threading.Lock()

    class _Cond:
        # i metodi SPECIALI (__enter__/__exit__) Python li cerca sul TIPO, non via
        # __getattr__: senza queste due righe `with con:` esplode e lo schema non
        # nasce mai (bug beccato dalla suite). close() rilascia il lucchetto: ogni
        # percorso chiude in finally, quindi la serializzazione e' garantita.
        def close(self):
            try:
                _lock.release()
            except RuntimeError:
                pass

        def __enter__(self):
            return con.__enter__()

        def __exit__(self, *a):
            return con.__exit__(*a)

        def __getattr__(self, n):
            return getattr(con, n)

    class _FC(FinancialController):
        def _apri(self):
            _lock.acquire()
            con.row_factory = sqlite3.Row
            return _Cond()

    return _FC(lambda: con, orologio=orologio)
