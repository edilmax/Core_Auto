#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# BookinVIP — RESTORE DA ZERO da una copia offsite cifrata.
# "Idiota-proof": lo lanci, ti guida, e alla fine ti dice se i dati sono INTEGRI.
#
# COSA FA:
#   1) decifra il pacchetto offsite (chiede/legge la passphrase);
#   2) verifica il checksum di OGNI archivio (nessuna copia corrotta passa);
#   3) scompatta e RICOSTRUISCE ogni <db>.db dallo snapshot piu' recente
#      (de-gzip -> file .db pronto per il container);
#   3b) controlla che gli archivi vengano TUTTI dallo stesso giro di backup e che
#      non ne manchi nessuno di quelli elencati nel manifesto (un ripristino a
#      pezzi, con il giornale di ieri e il catalogo di oggi, e' peggio di nessun
#      ripristino); scappatoia dichiarata per l'emergenza: BV_RESTORE_PARZIALE=1;
#   4) PROVA d'integrita': ogni DB passa `PRAGMA integrity_check`, e per il
#      giornale contabile (finanza.db) ricalcola la CATENA DI HASH end-to-end.
#   5) stampa la cartella pronta: bastera' montarla come volume /data.
#
# USO:
#   BV_PASS='la-passphrase' bash deploy/restore_offsite.sh <pacchetto.tar.gz.enc> [dest_dir]
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ENC="${1:-}"
DEST="${2:-./restore-$(date +%Y%m%d-%H%M%S)}"
BV_PASS="${BV_PASS:-}"

rosso(){ printf '\033[31m%s\033[0m\n' "$*" >&2; }
verde(){ printf '\033[32m%s\033[0m\n' "$*"; }
giallo(){ printf '\033[33m%s\033[0m\n' "$*"; }

# Python che FUNZIONA davvero (su Windows 'python3' e' spesso uno stub finto del
# Microsoft Store che non esegue nulla): si prova a farlo stampare e si tiene il primo vero.
PY=""
for cand in python3 python py; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "print(1)" >/dev/null 2>&1; then
    PY="$cand"; break
  fi
done
[ -n "$PY" ] || { rosso "manca un Python funzionante (serve per la prova d'integrita')"; exit 2; }

[ -n "$ENC" ] && [ -f "$ENC" ] || { rosso "Uso: BV_PASS=... bash restore_offsite.sh <pacchetto.enc> [dest]"; exit 2; }
[ -n "$BV_PASS" ] || { rosso "manca BV_PASS (la passphrase usata per cifrare)"; exit 2; }
command -v openssl >/dev/null || { rosso "manca openssl"; exit 2; }

# verifica il checksum del pacchetto cifrato, se presente accanto
if [ -f "$ENC.sha256" ]; then
  atteso="$(awk '{print $1}' "$ENC.sha256")"
  reale="$( { sha256sum "$ENC" 2>/dev/null || shasum -a 256 "$ENC"; } | awk '{print $1}')"
  [ "$atteso" = "$reale" ] || { rosso "pacchetto CORROTTO (checksum enc non torna)"; exit 1; }
  verde "[0] pacchetto cifrato integro."
fi

mkdir -p "$DEST"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

verde "[1] decifro…"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
  -in "$ENC" -out "$TMP/backup.tar.gz" -pass env:BV_PASS \
  || { rosso "decifratura fallita (passphrase errata?)"; exit 1; }

verde "[2] scompatto e verifico i checksum…"
mkdir -p "$TMP/backup"
tar -xzf "$TMP/backup.tar.gz" -C "$TMP/backup"
falliti=0
while IFS= read -r sig; do
  dir="$(dirname "$sig")"; base="$(basename "$sig" .sha256)"
  [ -f "$dir/$base" ] || { rosso "  manca $base"; falliti=$((falliti+1)); continue; }
  a="$(awk '{print $1}' "$sig")"
  r="$( { sha256sum "$dir/$base" 2>/dev/null || shasum -a 256 "$dir/$base"; } | awk '{print $1}')"
  [ "$a" = "$r" ] || { rosso "  CHECKSUM ROTTO: $base"; falliti=$((falliti+1)); }
done < <(find "$TMP/backup" -name '*.sha256')
[ "$falliti" -eq 0 ] || { rosso "STOP: $falliti archivi corrotti."; exit 1; }

verde "[3] ricostruisco i database (snapshot piu' recente per ciascuno)…"
# per ogni prefisso <db>, prendi il .gz col timestamp piu' alto
for gz in $(find "$TMP/backup" -name '*.db.gz' | sort); do
  db="$(basename "$gz" | sed -E 's/-[0-9]{8}-[0-9]{6}\.db\.gz$//')"
  echo "$db"
done | sort -u | while read -r db; do
  ultimo="$(ls -1t "$TMP"/backup/"$db"-*.db.gz | head -1)"
  gunzip -c "$ultimo" > "$DEST/$db.db"
  basename "$ultimo" >> "$TMP/scelti.txt"
  echo "   $db.db  <-  $(basename "$ultimo")"
done

# ─────────────────────────────────────────────────────────────────────────────
# [3b] IL RIPRISTINO E' TUTTO INTERO E DI UN SOLO ISTANTE?  (difetto chiuso
#      2026-07-29 da una revisione ostile: prima non lo chiedeva nessuno)
#
#   · STRACCIATO: il passo 3 prende per OGNI archivio il suo snapshot piu' recente.
#     Se l'ultimo giro di backup e' morto a meta' (disco pieno, container ucciso,
#     un solo `.gz` perso), finanza.db torna da ieri e catalogo.db da stamattina:
#     prenotazioni senza le righe di giornale che le pagano. Il vecchio script
#     stampava "RESTORE OK — dati integri" e usciva 0. PROVATO: 2 giri di backup,
#     tolto il piu' recente di finanza -> catalogo con 2 alloggi e giornale con 3
#     righe invece di 5, esito 0, nessun avviso.
#   · INCOMPLETO: un pacchetto con UN archivio su 23 (offsite troncato, tar a
#     meta') veniva ripristinato e dichiarato OK: host, accettazioni e payout
#     semplicemente non c'erano. PROVATO anche questo.
#
# Chi rimette in piedi il server alle 3 di notte si fida della riga verde: qui
# quella riga deve diventare rossa. Scappatoia dichiarata per l'emergenza vera
# (l'unica copia rimasta E' mista): BV_RESTORE_PARZIALE=1, che declassa il rosso
# ad avviso — ma va scelto, non subito in silenzio.
# ─────────────────────────────────────────────────────────────────────────────
strappi=0
PARZIALE_OK="${BV_RESTORE_PARZIALE:-0}"
verde "[3b] stesso giro di backup per tutti gli archivi?"
if [ -s "$TMP/scelti.txt" ]; then
  istanti="$(sed -E 's/^.*-([0-9]{8}-[0-9]{6})\.db\.gz$/\1/' "$TMP/scelti.txt" | sort -u)"
  quanti="$(printf '%s\n' "$istanti" | wc -l | tr -d ' ')"
  if [ "$quanti" -gt 1 ]; then
    rosso "   RESTORE STRACCIATO: gli archivi vengono da $quanti giri di backup diversi"
    printf '%s\n' "$istanti" | while read -r t; do rosso "     istante: $t"; done
    sed 's/^/     /' "$TMP/scelti.txt" >&2
    strappi=$((strappi+1))
  else
    verde "   tutti dallo stesso istante: $istanti"
  fi
else
  rosso "   nessun archivio ricostruito: il pacchetto non conteneva nessun .db.gz"
  strappi=$((strappi+1))
fi

verde "[3c] ci sono TUTTI gli archivi dell'ultimo giro? (manifesto)"
# `find` esce 0 anche quando non trova nulla: cosi' il caso "manifesto assente" arriva al
# controllo qui sotto e diventa un ROSSO PARLANTE, invece di far morire lo script muto per
# via di `set -e`. Niente `|| true` (REGOLA FERREA 12): non serve a nascondere un esito, e
# infatti non c'e'. Ordinamento per NOME e non per data del file: il nome porta l'istante
# vero del backup, la data di modifica mente dopo una copia.
manifesto="$(find "$TMP/backup" -maxdepth 1 -name 'MANIFEST-*.txt' | sort -r | head -1)"
if [ -n "${manifesto:-}" ] && [ -f "$manifesto" ]; then
  mancanti=0
  while IFS= read -r riga; do
    case "$riga" in ''|'#'*) continue;; esac
    atteso="$(echo "$riga" | sed -E 's/-[0-9]{8}-[0-9]{6}\.db\.gz$//')"
    if [ ! -f "$DEST/$atteso.db" ]; then
      rosso "   MANCA $atteso.db (il manifesto $(basename "$manifesto") lo elenca)"
      mancanti=$((mancanti+1))
    fi
  done < "$manifesto"
  if [ "$mancanti" -gt 0 ]; then
    rosso "   RESTORE INCOMPLETO: $mancanti archivi del manifesto non sono stati ripristinati"
    strappi=$((strappi+1))
  else
    verde "   completo: c'e' ogni archivio elencato in $(basename "$manifesto")"
  fi
else
  # Senza manifesto la completezza non e' verificabile: e' esattamente la forma che
  # prende un pacchetto TRONCATO (tar interrotto, pull a meta'). PROVATO: un pacchetto
  # col solo finanza.db, senza manifesto, veniva dichiarato "RESTORE OK". "Non lo so"
  # non e' "va bene": si ferma, e chi sa cosa sta facendo usa BV_RESTORE_PARZIALE=1.
  rosso "   NESSUN MANIFESTO nel pacchetto: non e' verificabile che sia COMPLETO"
  rosso "   (un pacchetto troncato ha esattamente questo aspetto)"
  strappi=$((strappi+1))
fi

if [ "$strappi" -gt 0 ] && [ "$PARZIALE_OK" = "1" ]; then
  giallo "   BV_RESTORE_PARZIALE=1: ripristino misto/incompleto ACCETTATO su tua richiesta."
  strappi=0
fi

verde "[4] PROVA D'INTEGRITA'…"
prob=0
for db in "$DEST"/*.db; do
  chk="$("$PY" -c "import sqlite3,sys;print(sqlite3.connect(sys.argv[1]).execute('PRAGMA integrity_check').fetchone()[0])" "$db" 2>/dev/null || echo FALLITO)"
  if [ "$chk" = "ok" ]; then verde "   ok   $(basename "$db")"; else rosso "   ROTTO $(basename "$db"): $chk"; prob=$((prob+1)); fi
done

# CATENA DI HASH del giornale contabile (fase177): la prova che i soldi non sono stati toccati
if [ -f "$DEST/finanza.db" ]; then
  cat="$("$PY" - "$DEST/finanza.db" <<'PYEOF'
import sqlite3,sys,hashlib
c=sqlite3.connect(sys.argv[1]); c.row_factory=sqlite3.Row
try:
    rows=list(c.execute("SELECT * FROM libro_giornale ORDER BY seq"))
except Exception:
    print("NO_TABLE"); sys.exit(0)
prev="GENESI"
for r in rows:
    canon="|".join([r["evento_id"],str(r["ts"]),r["tipo"],r["riferimento"],r["soggetto"],
                    r["conto_dare"],r["conto_avere"],str(r["importo_cents"]),r["valuta"],
                    r["causale"],r["emittente"],r["prev_hash"]])
    h=hashlib.sha256(canon.encode()).hexdigest()
    if r["prev_hash"]!=prev or r["hash"]!=h:
        print("ROTTA_SEQ_%s"%r["seq"]); sys.exit(0)
    prev=r["hash"]
print("CATENA_OK_%d_righe"%len(rows))
PYEOF
)"
  case "$cat" in
    CATENA_OK_*) verde "   giornale contabile: $cat (immutabilita' verificata)";;
    NO_TABLE)    giallo "   giornale contabile: tabella assente (nessun movimento ancora)";;
    *)           rosso  "   GIORNALE MANOMESSO: $cat"; prob=$((prob+1));;
  esac
fi

echo
if [ "$prob" -eq 0 ] && [ "$strappi" -eq 0 ]; then
  verde "RESTORE OK — dati integri in:  $DEST"
  echo  "Passo finale (vedi RIPRENDI_QUI.md): copia questi .db nel volume /data del nuovo server e riavvia."
else
  rosso "RESTORE con $((prob+strappi)) problemi: NON usare questi dati, prova un pacchetto piu' vecchio."
  echo  "(se la copia mista/incompleta e' l'unica rimasta: BV_RESTORE_PARZIALE=1 bash $0 ...)" >&2
  exit 1
fi
