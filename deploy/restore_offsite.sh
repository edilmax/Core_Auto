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
  echo "   $db.db  <-  $(basename "$ultimo")"
done

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
if [ "$prob" -eq 0 ]; then
  verde "RESTORE OK — dati integri in:  $DEST"
  echo  "Passo finale (vedi RIPRENDI_QUI.md): copia questi .db nel volume /data del nuovo server e riavvia."
else
  rosso "RESTORE con $prob problemi: NON usare questi dati, prova un pacchetto piu' vecchio."
  exit 1
fi
