#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# BookinVIP — BACKUP OFFSITE "PULL" (gira sul PC del fondatore, NON sul VPS).
#
# PERCHE' PULL e non PUSH: e' il PC a collegarsi al VPS e a TIRARE giu' i backup
# (SSH cifrato). Il VPS non ha nessuna chiave verso il PC -> se il server viene
# compromesso/cifrato da un ransomware, l'attaccante NON puo' raggiungere ne'
# distruggere queste copie. E' la disposizione anti-ransomware corretta.
#
# COSA FA, in ordine:
#   1) sul VPS lancia un giro di backup FRESCO (snapshot consistente di ogni .db);
#   2) TIRA giu' l'intera cartella backup/ (archivi .gz + .sha256 + MANIFEST) via
#      rsync-su-ssh (incrementale: scarica solo cio' che manca);
#   3) RI-VERIFICA ogni checksum in locale (integrita' end-to-end origine->copia);
#   4) impacchetta il giro in UN archivio CIFRATO (AES-256) con data e ora, e
#      tiene uno storico locale (retention configurabile).
#
# REQUISITI sul PC: bash (Git-Bash su Windows va bene), ssh, openssl, tar.
# rsync e' OPZIONALE: se manca (tipico su Windows) si scarica via tar-su-ssh.
# USO:
#   BV_PASS='una-passphrase-forte' bash deploy/pull_offsite.sh
#   (oppure crea deploy/.offsite.env con le variabili — vedi sotto — e lancialo)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── config (override via ambiente o deploy/.offsite.env, NON committato) ──────
QUI="$(cd "$(dirname "$0")" && pwd)"
[ -f "$QUI/.offsite.env" ] && . "$QUI/.offsite.env"

VPS_HOST="${VPS_HOST:-root@76.13.44.167}"
VPS_KEY="${VPS_KEY:-$HOME/.ssh/id_ed25519}"
VPS_DATA="${VPS_DATA:-/var/lib/docker/volumes/bookinvip_casavip_data/_data}"
VPS_BACKUP="${VPS_BACKUP:-$VPS_DATA/backup}"
# dove conservare le copie offsite SUL PC (fuori dal repo git!):
DEST="${DEST:-$HOME/bookinvip-offsite}"
RETENTION_OFFSITE="${RETENTION_OFFSITE:-30}"   # quanti pacchetti cifrati tenere
# passphrase di cifratura: OBBLIGATORIA, mai scritta nel repo
BV_PASS="${BV_PASS:-}"

SSH="ssh -o BatchMode=yes -o ConnectTimeout=20 -i $VPS_KEY"
TS="$(date +%Y%m%d-%H%M%S)"
STAGE="$DEST/.stage-$TS"

rosso(){ printf '\033[31m%s\033[0m\n' "$*" >&2; }
verde(){ printf '\033[32m%s\033[0m\n' "$*"; }

if [ -z "$BV_PASS" ]; then
  rosso "ERRORE: manca BV_PASS (la passphrase di cifratura)."
  rosso "  Esempio:  BV_PASS='frase-lunga-e-segreta' bash deploy/pull_offsite.sh"
  exit 2
fi
command -v openssl >/dev/null || { rosso "manca openssl"; exit 2; }
command -v tar     >/dev/null || { rosso "manca tar";     exit 2; }

mkdir -p "$DEST" "$STAGE"
trap 'rm -rf "$STAGE"' EXIT

# ── 1) backup FRESCO sul VPS (snapshot consistente di OGNI .db) ───────────────
verde "[1/4] backup fresco sul VPS…"
$SSH "$VPS_HOST" "cd /var/www/bookinvip && DATA_DIR='$VPS_DATA' BACKUP_DIR='$VPS_BACKUP' sh deploy/backup_casavip.sh" >/dev/null
verde "      fatto."

# ── 2) PULL della cartella backup/ (rsync se c'e', altrimenti tar-su-ssh) ──────
mkdir -p "$STAGE/backup"
if command -v rsync >/dev/null 2>&1; then
  verde "[2/4] scarico i backup dal VPS (rsync incrementale)…"
  rsync -az --delete -e "$SSH" "$VPS_HOST:$VPS_BACKUP/" "$STAGE/backup/"
else
  verde "[2/4] scarico i backup dal VPS (tar-su-ssh: niente rsync, va bene lo stesso)…"
  # impacchetta lato VPS e srotola in locale: un solo stream SSH cifrato
  $SSH "$VPS_HOST" "tar -czf - -C '$VPS_BACKUP' ." | tar -xzf - -C "$STAGE/backup"
fi
N="$(find "$STAGE/backup" -name '*.db.gz' | wc -l | tr -d ' ')"
[ "$N" -gt 0 ] || { rosso "nessun archivio scaricato: controlla SSH/percorso VPS."; exit 1; }
verde "      $N archivi in staging."

# ── 3) RI-VERIFICA dei checksum in locale (origine->copia integra) ────────────
verde "[3/4] verifico i checksum…"
falliti=0; verificati=0
while IFS= read -r sig; do
  dir="$(dirname "$sig")"; base="$(basename "$sig" .sha256)"
  atteso="$(awk '{print $1}' "$sig" 2>/dev/null || true)"
  [ -f "$dir/$base" ] || { rosso "  MANCA l'archivio di $base"; falliti=$((falliti+1)); continue; }
  reale="$( { sha256sum "$dir/$base" 2>/dev/null || shasum -a 256 "$dir/$base"; } | awk '{print $1}')"
  if [ -n "$atteso" ] && [ "$atteso" = "$reale" ]; then
    verificati=$((verificati+1))
  else
    rosso "  CHECKSUM ROTTO: $base (atteso $atteso, reale $reale)"; falliti=$((falliti+1))
  fi
done < <(find "$STAGE/backup" -name '*.sha256')
if [ "$falliti" -ne 0 ]; then
  rosso "INTEGRITA' FALLITA: $falliti archivi corrotti/incompleti. Copia offsite NON creata."
  exit 1
fi
verde "      $verificati/$verificati archivi integri."

# ── 4) pacchetto CIFRATO + storico ────────────────────────────────────────────
verde "[4/4] cifro il pacchetto offsite…"
TAR="$STAGE/bookinvip-$TS.tar.gz"
( cd "$STAGE/backup" && tar -czf "$TAR" . )
OUT="$DEST/bookinvip-$TS.tar.gz.enc"
# AES-256-CBC + PBKDF2 (100k iter). Per decifrare serve SOLO la passphrase.
openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt \
  -in "$TAR" -out "$OUT" -pass env:BV_PASS
{ sha256sum "$OUT" 2>/dev/null || shasum -a 256 "$OUT"; } > "$OUT.sha256"
# retention offsite: tieni gli ultimi N pacchetti cifrati
ls -1t "$DEST"/bookinvip-*.tar.gz.enc 2>/dev/null | tail -n +"$((RETENTION_OFFSITE+1))" | while read -r v; do
  rm -f "$v" "$v.sha256"
done

verde "OK — copia offsite cifrata:"
verde "     $OUT"
verde "     ($N database, $verificati checksum verificati)"
echo  "Per il ripristino: vedi 'RESTORE DA ZERO' in RIPRENDI_QUI.md"
