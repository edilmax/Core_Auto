"""
CORE_AUTO - Fase 178: WATCHDOG / AUTO-DIAGNOSI (il "sistema nervoso").

NON gestisce dati: OSSERVA la salute e dice se qualcosa e' rotto. Puro, READ-ONLY,
ZERO dipendenze (stdlib), ZERO import del money-path (isola: puo' diagnosticare anche
se fase177 e' rotta). Tre condizioni critiche + due di contorno:

  a) UPTIME              -> lo controlla il bash (curl esterno): un processo non puo'
                            dire "sono morto". Qui restano le cose che solo chi guarda
                            i FILE puo' sapere:
  b) INTEGRITA' CATENA   -> ricalcola la catena di hash del giornale (fase177): se un
                            record e' stato manomesso, lo dice e punta la riga.
  c) BACKUP FRESCO       -> l'ultimo *.db.gz e' piu' recente della soglia?
  d) SPAZIO DISCO        -> sotto la soglia? (disco pieno = SQLite non scrive piu' = sito fermo)
  e) DB PRESENTI         -> i database attesi ci sono tutti (nessuno sparito)?

`valuta(misure)` e' PURA (misure -> verdetto): testabile senza toccare disco/rete.
`diagnosi(...)` raccoglie le misure reali e chiama `valuta`. CLI: stampa JSON (per il bash).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from typing import Any, Dict, List, Optional

# database il cui giornale va verificato per la catena hash
DB_GIORNALE = "finanza"

# ── IL BATTITO DEL GUARDIANO DEI SOLDI (dead man's switch) ───────────────────
# `fase186_guardiano` confronta i nostri conti con Stripe una volta al giorno, in un thread
# daemon. Se quel thread muore, i log semplicemente TACCIONO -- e il silenzio somiglia alla
# pace: nessuno grida sull'ASSENZA. Qui la logica e' rovesciata rispetto a un allarme
# normale: si grida quando un segnale ATTESO non arriva.
# Il nome del file sta in UN POSTO SOLO, qui: chi scrive il battito (`fase83_server.py`, il
# tick) importa questa costante invece di ripeterla. Lo stesso fatto in due posti, con la
# seconda copia che resta indietro, e' il difetto che abbiamo inseguito tutta la notte.
NOME_BATTITO = "guardiano_ultimo_giro"
# 24 ore di intervallo + 1 di grazia. La grazia non e' prudenza generica: serve a non
# trasformare un ritardo normale in un allarme, e un allarme che grida per niente viene
# spento da chi lo riceve (regola ferrea 10, che lo considera grave quanto uno mancato).
MAX_ETA_BATTITO_SEC = 25 * 3600


# ── verifiche read-only ─────────────────────────────────────────────────────
def verifica_catena_file(percorso: str) -> Dict[str, Any]:
    """Ricalcola la catena di hash del giornale contabile aprendo il file in SOLA
    LETTURA (mai un lock sugli scrittori). Indipendente da fase177: se quel modulo
    e' rotto, il watchdog vede lo stesso. Ritorna ok/seq_rotta/righe."""
    if not os.path.exists(percorso):
        return {"ok": True, "assente": True, "righe": 0}
    try:
        # connessione di lettura NORMALE (non 'mode=ro'): su un DB WAL vivo il mode=ro
        # NON vede i commit ancora nel journal WAL -> il watchdog leggerebbe la versione
        # VECCHIA e mancherebbe la manomissione appena avvenuta (bug provato nel dry-run).
        # Non scriviamo mai (solo SELECT) e i trigger del giornale vietano comunque le
        # scritture: la sola-lettura e' garantita dall'intento, non dal flag.
        con = sqlite3.connect(percorso, timeout=5)
        con.row_factory = sqlite3.Row
    except sqlite3.Error:
        return {"ok": False, "errore": "apertura_fallita", "righe": 0}
    try:
        # ⛔ PRIMA SI CHIEDE SE IL FILE SI LEGGE, POI SE LA TABELLA C'E' (2026-08-02).
        # `sqlite3.connect` RIESCE su qualunque file: non legge niente finche' non gli si
        # chiede qualcosa. Quindi un libro giornale CORROTTO arrivava alla query, falliva,
        # e finiva nel ramo «tabella non ancora creata» -> il guardiano rispondeva
        # {"ok": True, "assente": True}, cioe' ESATTAMENTE come su un'installazione nuova.
        # Tre situazioni diverse, una sola risposta: «tutto bene».
        # Difetto VIVO trovato il 2026-08-02 mentre si scrivevano le guardie: se il libro
        # dei soldi si corrompe (settore guasto, copia interrotta, ripristino a meta') il
        # guardiano lo dichiara sano, e lui e' il modulo su cui contano tutti gli altri.
        try:
            tabelle = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.Error as e:
            return {"ok": False, "errore": "illeggibile",
                    "dettaglio": str(e)[:120], "righe": 0}
        if "libro_giornale" not in tabelle:
            return {"ok": True, "assente": True, "righe": 0}   # tabella non ancora creata
        try:
            righe = con.execute("SELECT * FROM libro_giornale ORDER BY seq").fetchall()
        except sqlite3.Error as e:
            # la tabella C'E' ma non si legge: non e' un'installazione nuova, e' un guasto
            return {"ok": False, "errore": "lettura_fallita",
                    "dettaglio": str(e)[:120], "righe": 0}
        prev = "GENESI"
        for r in righe:
            canon = "|".join([r["evento_id"], str(r["ts"]), r["tipo"], r["riferimento"],
                              r["soggetto"], r["conto_dare"], r["conto_avere"],
                              str(r["importo_cents"]), r["valuta"], r["causale"],
                              r["emittente"], r["prev_hash"]])
            h = hashlib.sha256(canon.encode("utf-8")).hexdigest()
            if r["prev_hash"] != prev or r["hash"] != h:
                return {"ok": False, "seq_rotta": int(r["seq"]), "righe": len(righe)}
            prev = r["hash"]
        return {"ok": True, "righe": len(righe)}
    finally:
        con.close()


def eta_backup_sec(dir_backup: str, *, ora: Optional[int] = None) -> Optional[int]:
    """Eta' (secondi) del *.db.gz piu' recente. None se la cartella non ha backup."""
    ora = ora if isinstance(ora, int) else int(time.time())
    if not os.path.isdir(dir_backup):
        return None
    piu_recente = None
    for nome in os.listdir(dir_backup):
        if nome.endswith(".db.gz"):
            try:
                m = int(os.path.getmtime(os.path.join(dir_backup, nome)))
            except OSError:
                continue
            if piu_recente is None or m > piu_recente:
                piu_recente = m
    return None if piu_recente is None else max(0, ora - piu_recente)


def segna_battito_guardiano(dir_dati: str, *, ora: Optional[int] = None) -> bool:
    """Lascia il battito. Lo chiama il tick giornaliero ALLA FINE e SOLO se il giro e'
    riuscito: se il Guardiano muore a meta', non deve restare un battito che dice «sto bene».

    Ritorna False invece di sollevare quando non c'e' una cartella vera -- `db_finanza` vale
    `:memory:` di serie, e `os.path.dirname(":memory:")` e' la stringa vuota. Timbrare un
    battito in un posto che non esiste sarebbe un segnale FINTO, cioe' peggio di nessun
    segnale: rassicura. E un guasto qui non deve mai far cadere il giro del Guardiano.
    """
    if not dir_dati or not os.path.isdir(dir_dati):
        return False
    ora = ora if isinstance(ora, int) else int(time.time())
    try:
        percorso = os.path.join(dir_dati, NOME_BATTITO)
        with open(percorso, "w") as f:
            f.write("%d\n" % ora)
        os.utime(percorso, (ora, ora))     # l'eta' si legge dall'mtime, non dal contenuto
        return True
    except OSError:
        return False


def eta_battito_guardiano_sec(dir_dati: str, *, ora: Optional[int] = None) -> Optional[int]:
    """Eta' (secondi) dell'ultimo battito. None se non c'e': o non ha mai girato, o qualcuno
    l'ha cancellato -- e le due cose vanno trattate uguale, perche' in tutti e due i casi
    NON SAPPIAMO se il Guardiano sta girando."""
    ora = ora if isinstance(ora, int) else int(time.time())
    if not dir_dati:
        return None
    try:
        m = int(os.path.getmtime(os.path.join(dir_dati, NOME_BATTITO)))
    except OSError:
        return None
    return max(0, ora - m)


def db_presenti(dir_dati: str) -> List[str]:
    """Prefissi dei .db presenti nella cartella dati (per notare un DB sparito)."""
    if not os.path.isdir(dir_dati):
        return []
    return sorted(os.path.splitext(n)[0] for n in os.listdir(dir_dati)
                  if n.endswith(".db"))


def spazio_disco_pct(percorso: str) -> Optional[int]:
    """% di disco USATO sul volume che contiene `percorso` (cross-piattaforma)."""
    try:
        u = shutil.disk_usage(percorso if os.path.exists(percorso) else ".")
        return int(round(u.used * 100.0 / u.total)) if u.total else None
    except OSError:
        return None


# ── decisione PURA (misure -> verdetto): testabile senza I/O ─────────────────
def valuta(misure: Dict[str, Any], *, max_eta_backup_sec: int = 8 * 3600,
           max_disco_pct: int = 85, db_attesi: Optional[List[str]] = None,
           max_eta_battito_sec: int = MAX_ETA_BATTITO_SEC
           ) -> Dict[str, Any]:
    """misure: {catena:{ok,..}, eta_backup_sec:int|None, disco_pct:int|None,
    db_presenti:[...], uptime_ok:bool|None}. Ritorna {ok, allarmi:[...], dettagli}."""
    allarmi: List[Dict[str, str]] = []

    up = misure.get("uptime_ok")
    if up is False:
        allarmi.append({"cod": "uptime", "grav": "critico",
                        "msg": "il sito NON risponde (health check fallito)"})

    cat = misure.get("catena") or {}
    if cat.get("ok") is False:
        seq = cat.get("seq_rotta")
        allarmi.append({"cod": "catena", "grav": "critico",
                        "msg": "GIORNALE MANOMESSO" + (" alla riga %s" % seq if seq else "")})

    # solo se la freschezza backup e' stata MISURATA (chiave presente): in modalita'
    # remota/parziale non si valuta cio' che non si e' guardato.
    if "eta_backup_sec" in misure:
        eta = misure.get("eta_backup_sec")
        if eta is None:
            allarmi.append({"cod": "backup", "grav": "critico",
                            "msg": "NESSUN backup trovato"})
        elif eta > max_eta_backup_sec:
            allarmi.append({"cod": "backup", "grav": "avviso",
                            "msg": "ultimo backup vecchio di %dh (soglia %dh)"
                                   % (eta // 3600, max_eta_backup_sec // 3600)})

    # Stessa disciplina del backup qui sopra: la chiave ASSENTE vuol dire «non l'ho
    # guardato», e non si giudica cio' che non si e' guardato. Senza questo, il watchdog in
    # modalita' REMOTA (dal PC, che il volume del server non lo vede) griderebbe «guardiano
    # muto» a ogni giro: un falso allarme perenne, cioe' un allarme che finisce spento.
    if "eta_battito_guardiano_sec" in misure:
        eb = misure.get("eta_battito_guardiano_sec")
        if eb is None:
            allarmi.append({"cod": "guardiano_muto", "grav": "critico",
                            "msg": "il Guardiano dei soldi non ha lasciato NESSUN battito: "
                                   "o non ha mai girato, o il segnale e' sparito. I conti "
                                   "contro Stripe potrebbero non essere piu' controllati"})
        elif eb > max_eta_battito_sec:
            allarmi.append({"cod": "guardiano_muto", "grav": "critico",
                            "msg": "il Guardiano dei soldi non batte da %dh (soglia %dh): "
                                   "nessuno sta piu' confrontando i nostri conti con Stripe"
                                   % (eb // 3600, max_eta_battito_sec // 3600)})

    disco = misure.get("disco_pct")
    if isinstance(disco, int) and disco >= max_disco_pct:
        allarmi.append({"cod": "disco", "grav": "critico" if disco >= 95 else "avviso",
                        "msg": "disco al %d%% (soglia %d%%)" % (disco, max_disco_pct)})

    if db_attesi:
        presenti = set(misure.get("db_presenti") or [])
        mancanti = [d for d in db_attesi if d not in presenti]
        if mancanti:
            allarmi.append({"cod": "db_mancanti", "grav": "critico",
                            "msg": "database SPARITI: %s" % ", ".join(mancanti)})

    return {"ok": len(allarmi) == 0, "allarmi": allarmi, "misure": misure}


def diagnosi(*, dir_dati: str, dir_backup: str, uptime_ok: Optional[bool] = None,
             max_eta_backup_sec: int = 8 * 3600, max_disco_pct: int = 85,
             db_attesi: Optional[List[str]] = None,
             max_eta_battito_sec: int = MAX_ETA_BATTITO_SEC) -> Dict[str, Any]:
    """Raccoglie le misure reali (read-only) e le valuta. `uptime_ok` lo passa il
    chiamante (il bash lo misura da FUORI: un processo interno non puo' dire di essere
    morto)."""
    misure = {
        "uptime_ok": uptime_ok,
        "catena": verifica_catena_file(os.path.join(dir_dati, DB_GIORNALE + ".db")),
        "eta_backup_sec": eta_backup_sec(dir_backup),
        "eta_battito_guardiano_sec": eta_battito_guardiano_sec(dir_dati),
        "disco_pct": spazio_disco_pct(dir_dati),
        "db_presenti": db_presenti(dir_dati),
    }
    return valuta(misure, max_eta_backup_sec=max_eta_backup_sec,
                  max_disco_pct=max_disco_pct, db_attesi=db_attesi,
                  max_eta_battito_sec=max_eta_battito_sec)


if __name__ == "__main__":   # pragma: no cover — CLI per il bash
    import argparse
    p = argparse.ArgumentParser(description="Watchdog / auto-diagnosi BookinVIP")
    p.add_argument("--dati", default=os.environ.get("DATA_DIR", "/data"))
    p.add_argument("--backup", default=os.environ.get("BACKUP_DIR", "/data/backup"))
    p.add_argument("--uptime", choices=["ok", "ko", "skip"], default="skip")
    p.add_argument("--max-eta-h", type=int, default=8)
    p.add_argument("--max-disco", type=int, default=85)
    a = p.parse_args()
    up = True if a.uptime == "ok" else False if a.uptime == "ko" else None
    r = diagnosi(dir_dati=a.dati, dir_backup=a.backup, uptime_ok=up,
                 max_eta_backup_sec=a.max_eta_h * 3600, max_disco_pct=a.max_disco)
    print(json.dumps(r, ensure_ascii=False))
    raise SystemExit(0 if r["ok"] else 1)
