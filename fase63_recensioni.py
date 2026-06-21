"""
CORE_AUTO - Fase 63: Recensioni VERIFICATE (anti-fake) - fiducia a prova di crittografia.

Le recensioni false sono la piaga cronica delle OTA: farm di recensioni, voti gonfiati,
manomissioni. E' un loro punto debole strutturale (vivono di volume, non di verita').
Noi rendiamo la recensione FALSIFICABILE-IMPOSSIBILE a costo zero: puo' recensire SOLO
chi ha davvero pagato e soggiornato.

Come (prova di soggiorno crittografica, "Nostr-style" ma locale e gratis):
  1. quando una prenotazione e' confermata e pagata, il CORE emette un DIRITTO DI
     RECENSIONE firmato HMAC (riusa fase59.FirmaQuote) legato a (prenotazione_id,
     alloggio_id), con scadenza opzionale;
  2. l'ospite invia la recensione presentando quel token; il CORE ri-verifica la firma
     -> recensione marchiata 'verificata'. Senza token valido NON si recensisce;
  3. una sola recensione per prenotazione (dedup idempotente sulla PK) -> niente spam,
     niente voti multipli dello stesso soggiorno;
  4. il testo libero e' marchiato con la lingua d'origine (fase61) -> l'agente del
     cliente traduce; il voto e' un INTERO 1..5 (zero float, medie in centesimi interi).

VINCITRICE DEL BENCHMARK (4 modelli di fiducia):
  V3 'prova-di-soggiorno HMAC emessa dal CORE + verifica + una-per-prenotazione'.
  Infalsificabile, deterministica, zero dipendenze. Le altre perdono: V1 'recensioni
  aperte a tutti' = farm di falsi (il problema di Booking); V2 'flag verified
  auto-dichiarato' = spoofabile; V4 'recensioni on-chain/blockchain' = pesante, costa
  gas, overkill (l'HMAC da' la stessa verificabilita' a costo zero, in locale).

SOPRAVVIVENZA TOTALE: store durevole (conn-per-op, WAL, BEGIN IMMEDIATE, idem schema);
validatore BLINDATO che non solleva mai; token manomesso/scaduto/assente -> rifiuto
fail-closed; medie in interi; orologio iniettabile (test deterministici).
"""
from __future__ import annotations

import datetime
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from fase59_concierge import FirmaQuote

logger = logging.getLogger("core_auto.recensioni")

VOTO_MIN, VOTO_MAX = 1, 5
LIMITE_TESTO = 2000
LINGUE_NOTE = ("en", "it", "es", "fr", "de", "pt", "ja", "zh")


def _intero(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


@dataclass(frozen=True)
class EsitoRecensione:
    ok: bool
    motivo: str = ""
    verificata: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Emissione del diritto di recensione (lato booking, dopo pagamento confermato)
# ─────────────────────────────────────────────────────────────────────────────
class EmettitoreDiritto:
    """Firma il diritto di recensione legato a una prenotazione pagata."""

    def __init__(self, firma: FirmaQuote, *, ttl_giorni: int = 90,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._firma = firma
        self._ttl = max(0, int(ttl_giorni)) * 86400
        self._now = orologio or (lambda: int(time.time()))

    def emetti(self, prenotazione_id: str, alloggio_id: str) -> str:
        payload: Dict[str, Any] = {
            "prenotazione_id": str(prenotazione_id),
            "alloggio_id": str(alloggio_id),
        }
        if self._ttl > 0:
            payload["exp"] = self._now() + self._ttl
        return self._firma.codifica(payload)


# ─────────────────────────────────────────────────────────────────────────────
# Registro durevole delle recensioni
# ─────────────────────────────────────────────────────────────────────────────
class RegistroRecensioni:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], firma: FirmaQuote,
                 *, orologio: Optional[Callable[[], int]] = None) -> None:
        self._conn_factory = conn_factory
        self._firma = firma
        self._now = orologio or (lambda: int(time.time()))
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
                    CREATE TABLE IF NOT EXISTS recensioni (
                        prenotazione_id TEXT PRIMARY KEY,
                        alloggio_id TEXT NOT NULL,
                        voto INTEGER NOT NULL,
                        testo TEXT NOT NULL DEFAULT '',
                        lingua TEXT NOT NULL DEFAULT 'en',
                        verificata INTEGER NOT NULL DEFAULT 0,
                        ts TEXT NOT NULL)""")
                con.execute("CREATE INDEX IF NOT EXISTS idx_rec_alloggio "
                            "ON recensioni(alloggio_id)")
        finally:
            con.close()

    def invia(self, token: Any, voto: Any, testo: Any = "",
              lingua: Any = "en") -> EsitoRecensione:
        """Invia una recensione presentando il diritto firmato. BLINDATO, fail-closed."""
        dati = self._firma.decodifica(token)
        if dati is None:
            return EsitoRecensione(False, "diritto_non_valido")   # firma rotta/assente
        exp = dati.get("exp")
        if exp is not None and (not _intero(exp) or exp < self._now()):
            return EsitoRecensione(False, "diritto_scaduto")
        prenotazione_id = dati.get("prenotazione_id")
        alloggio_id = dati.get("alloggio_id")
        if not (isinstance(prenotazione_id, str) and prenotazione_id
                and isinstance(alloggio_id, str) and alloggio_id):
            return EsitoRecensione(False, "diritto_corrotto")
        if not _intero(voto) or not (VOTO_MIN <= voto <= VOTO_MAX):
            return EsitoRecensione(False, "voto_non_valido")
        if not isinstance(testo, str) or len(testo) > LIMITE_TESTO:
            return EsitoRecensione(False, "testo_non_valido")
        lingua = lingua if (isinstance(lingua, str) and lingua in LINGUE_NOTE) else "en"
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            esiste = con.execute("SELECT 1 FROM recensioni WHERE prenotazione_id=?",
                                 (prenotazione_id,)).fetchone()
            if esiste is not None:                      # una sola recensione per soggiorno
                con.execute("COMMIT")
                return EsitoRecensione(False, "gia_recensita")
            con.execute(
                "INSERT INTO recensioni (prenotazione_id, alloggio_id, voto, testo, "
                "lingua, verificata, ts) VALUES (?,?,?,?,?,1,?)",
                (prenotazione_id, alloggio_id, voto, testo.strip(), lingua, ts))
            con.execute("COMMIT")
            return EsitoRecensione(True, "", verificata=True)
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()

    def riepilogo(self, alloggio_id: str) -> Dict[str, Any]:
        """Conteggio + media (in CENTESIMI di stella, intero) + distribuzione voti."""
        con = self._apri()
        try:
            row = con.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(voto),0) AS somma "
                "FROM recensioni WHERE alloggio_id=? AND verificata=1",
                (str(alloggio_id),)).fetchone()
            distrib = {v: 0 for v in range(VOTO_MIN, VOTO_MAX + 1)}
            for r in con.execute(
                    "SELECT voto, COUNT(*) AS c FROM recensioni "
                    "WHERE alloggio_id=? AND verificata=1 GROUP BY voto",
                    (str(alloggio_id),)):
                distrib[r["voto"]] = r["c"]
        finally:
            con.close()
        n = row["n"]
        media_cento = (row["somma"] * 100) // n if n else 0   # es. 425 = 4.25 stelle
        return {"conteggio": int(n), "media_centesimi": int(media_cento),
                "distribuzione": distrib}

    def elenco(self, alloggio_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        limit = max(1, min(100, limit if _intero(limit) else 20))
        con = self._apri()
        try:
            righe = con.execute(
                "SELECT prenotazione_id, voto, testo, lingua, ts FROM recensioni "
                "WHERE alloggio_id=? AND verificata=1 ORDER BY ts DESC, rowid DESC "
                "LIMIT ?", (str(alloggio_id), limit)).fetchall()
        finally:
            con.close()
        return [{"prenotazione_id": r["prenotazione_id"], "voto": int(r["voto"]),
                 # testo TAGGATO con la lingua d'origine: l'agente del cliente traduce
                 "testo": {"text": r["testo"], "lang": r["lingua"]}, "ts": r["ts"]}
                for r in righe]


# ─────────────────────────────────────────────────────────────────────────────
# Connessione condivisa per :memory:
# ─────────────────────────────────────────────────────────────────────────────
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


def crea_registro_recensioni(percorso: str, segreto: bytes, *,
                             orologio: Optional[Callable[[], int]] = None
                             ) -> RegistroRecensioni:
    firma = FirmaQuote(segreto)
    if percorso == ":memory:":
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return RegistroRecensioni(lambda: _ConnCondivisa(con), firma, orologio=orologio)
    return RegistroRecensioni(lambda: sqlite3.connect(percorso), firma, orologio=orologio)
