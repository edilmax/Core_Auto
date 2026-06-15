"""
CORE_AUTO / Tavola VIP - Fase 38: Backup automatico del DB (snapshot + retention).

La sicurezza dei dati prima di ogni feature. Due garanzie, ciascuna vincitrice di
un benchmark:
1. SNAPSHOT CONSISTENTE: si usa la **Online Backup API** di sqlite3
   (`Connection.backup`), non una copia di file grezza. Una copia grezza del solo
   `.db` PERDE i commit ancora nel WAL (nel benchmark: file illeggibile / righe
   perse); la backup API cattura uno snapshot transazionalmente consistente e
   COMPLETO anche con scritture concorrenti.
2. RETENTION SIZE-CAP: si cancellano i backup PIU' VECCHI finche' lo spazio totale
   non scende sotto `max_bytes` (tenendo sempre almeno il piu' recente). Una policy
   "tieni N" non limita i BYTE e puo' riempire il disco se i backup crescono; il
   size-cap GARANTISCE il tetto -> zero spreco di spazio. I backup sono gzippati.

Stdlib pura (sqlite3 + gzip): nessuna dipendenza. Entrypoint `python -m fase38_backup`
per il cron (legge DB_PATH / BACKUP_DIR / BACKUP_MAX_BYTES).
"""
from __future__ import annotations

import datetime
import gzip
import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass
from typing import List, Tuple

logger = logging.getLogger("core_auto.backup")

PREFISSO_DEFAULT = "tavolavip"
MAX_BYTES_DEFAULT = 500 * 1024 * 1024  # 500 MB di backup totali (tetto disco)


@dataclass(frozen=True)
class RisultatoBackup:
    percorso: str          # file appena creato
    bytes: int             # dimensione del nuovo backup
    rimossi: int           # backup vecchi cancellati dalla retention
    totale_bytes: int      # spazio occupato da TUTTI i backup dopo la retention
    num_backup: int        # quanti backup restano


def _snapshot_consistente(db_path: str, dst_db: str) -> None:
    """Online Backup API: snapshot consistente (gestisce WAL e scritture concorrenti)."""
    src = sqlite3.connect(db_path, timeout=30)
    try:
        dst = sqlite3.connect(dst_db)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def esegui_backup(db_path: str, dir_backup: str, *,
                  max_bytes: int = MAX_BYTES_DEFAULT,
                  prefisso: str = PREFISSO_DEFAULT,
                  comprimi: bool = True) -> RisultatoBackup:
    """Crea uno snapshot consistente (gzip) e applica la retention size-cap."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DB non trovato: {db_path}")
    if max_bytes <= 0:
        raise ValueError("max_bytes deve essere > 0")
    os.makedirs(dir_backup, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    tmp = os.path.join(dir_backup, f".tmp-{ts}.db")
    _snapshot_consistente(db_path, tmp)
    try:
        if comprimi:
            finale = os.path.join(dir_backup, f"{prefisso}-{ts}.db.gz")
            with open(tmp, "rb") as fi, gzip.open(finale, "wb") as fo:
                shutil.copyfileobj(fi, fo)
        else:
            finale = os.path.join(dir_backup, f"{prefisso}-{ts}.db")
            os.replace(tmp, finale)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    rimossi = _applica_retention(dir_backup, prefisso, max_bytes)
    elenco = lista_backup(dir_backup, prefisso)
    tot = sum(b for _, b, _ in elenco)
    logger.info("Backup %s (%d B); retention: rimossi %d; totale %d B in %d file",
                finale, os.path.getsize(finale), rimossi, tot, len(elenco))
    return RisultatoBackup(finale, os.path.getsize(finale), rimossi, tot, len(elenco))


def lista_backup(dir_backup: str,
                 prefisso: str = PREFISSO_DEFAULT) -> List[Tuple[str, int, float]]:
    """Backup esistenti come (percorso, bytes, mtime), dal piu' VECCHIO al piu'
    recente (il nome contiene il timestamp zero-padded -> ordine cronologico)."""
    if not os.path.isdir(dir_backup):
        return []
    out = []
    for nome in os.listdir(dir_backup):
        if nome.startswith(prefisso + "-") and not nome.startswith(".tmp"):
            p = os.path.join(dir_backup, nome)
            if os.path.isfile(p):
                out.append((p, os.path.getsize(p), os.path.getmtime(p)))
    out.sort(key=lambda x: os.path.basename(x[0]))  # nome = ordine cronologico
    return out


def _applica_retention(dir_backup: str, prefisso: str, max_bytes: int) -> int:
    """Cancella i backup PIU' VECCHI finche' il totale <= max_bytes, tenendo
    SEMPRE almeno il piu' recente (anche se da solo supera il tetto)."""
    elenco = lista_backup(dir_backup, prefisso)   # vecchio -> recente
    tot = sum(b for _, b, _ in elenco)
    rimossi, i = 0, 0
    while tot > max_bytes and (len(elenco) - i) > 1:
        percorso, b, _ = elenco[i]
        try:
            os.remove(percorso)
            tot -= b
            rimossi += 1
        except OSError:
            logger.warning("Retention: impossibile rimuovere %s", percorso)
        i += 1
    return rimossi


def ripristina(backup_path: str, dest_db: str) -> None:
    """Ripristina un backup (.db.gz o .db) in `dest_db`."""
    if backup_path.endswith(".gz"):
        with gzip.open(backup_path, "rb") as fi, open(dest_db, "wb") as fo:
            shutil.copyfileobj(fi, fo)
    else:
        shutil.copy2(backup_path, dest_db)


if __name__ == "__main__":   # entrypoint per il cron
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    db = os.environ.get("DB_PATH", "data/tavolavip.db")
    cartella = os.environ.get("BACKUP_DIR", "data/backup")
    mx = int(os.environ.get("BACKUP_MAX_BYTES", str(MAX_BYTES_DEFAULT)))
    r = esegui_backup(db, cartella, max_bytes=mx)
    print(f"backup={r.percorso} bytes={r.bytes} rimossi={r.rimossi} "
          f"totale={r.totale_bytes} num={r.num_backup}")
