#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# BookinVIP — WATCHDOG (il "sistema nervoso"). NON gestisce dati: osserva la salute
# e URLA se qualcosa e' rotto. Read-only.
#
# DUE TESTE (elimina il punto singolo di fallimento DELL'ALLARME):
#   • sul VPS (default): uptime + catena hash del giornale + backup fresco + disco +
#     db presenti. E' l'auto-diagnosi. La logica vera vive in fase178_watchdog.py
#     (puro, testato); qui c'e' solo orchestrazione + Telegram + log.
#   • dal PC (REMOTO=1): SOLO uptime da FUORI -> l'unico allarme che il VPS non puo'
#     dare quando e' morto (un guardiano dentro la stanza in fiamme non chiama i pompieri).
#
# ALLARME: Telegram (riusa il bot del progetto) + log critico PERSISTENTE nel volume
# (/data/watchdog.log: sopravvive al deploy rm-first, a differenza dei log del container).
# ANTI-SPAM: allerta solo quando lo stato CAMBIA (ok<->allarme) o ogni REMINDER_H se resta rotto.
#
# USO sul VPS (cron):   sh deploy/watchdog.sh
# USO dal PC:           REMOTO=1 bash deploy/watchdog.sh
# ─────────────────────────────────────────────────────────────────────────────
set -u

QUI="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$QUI/.." && pwd)"

# ── config (override via ambiente o file .env) ───────────────────────────────
REMOTO="${REMOTO:-0}"
URL="${WATCHDOG_URL:-https://bookinvip.com/api/health}"
DATA_DIR="${DATA_DIR:-/var/lib/docker/volumes/bookinvip_casavip_data/_data}"
BACKUP_DIR="${BACKUP_DIR:-$DATA_DIR/backup}"
MAX_ETA_H="${MAX_ETA_H:-8}"          # backup piu' vecchio di N ore = avviso
MAX_DISCO="${MAX_DISCO:-85}"         # disco oltre N% = allarme
CI_REPO="${CI_REPO:-edilmax/Core_Auto}"   # di chi si guarda la CI (ramo master)
REMINDER_H="${REMINDER_H:-6}"        # se resta rotto, ri-avvisa ogni N ore
STATO_FILE="${STATO_FILE:-$DATA_DIR/.watchdog_stato}"
LOG="${WATCHDOG_LOG:-$DATA_DIR/watchdog.log}"

# Telegram: sul VPS dai segreti del progetto; sul PC da deploy/.watchdog.env (gitignored)
[ -f "$REPO/deploy/.watchdog.env" ] && . "$REPO/deploy/.watchdog.env"
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] && [ -f "$REPO/.env.casavip" ]; then
  TELEGRAM_BOT_TOKEN="$(awk -F= '/^TELEGRAM_BOT_TOKEN=/{print substr($0,index($0,"=")+1)}' "$REPO/.env.casavip")"
  TELEGRAM_CHAT_ID="$(awk -F= '/^TELEGRAM_CHAT_ID=/{print substr($0,index($0,"=")+1)}' "$REPO/.env.casavip")"
fi

PY=""; for c in python3 python py; do command -v "$c" >/dev/null 2>&1 && "$c" -c "print(1)" >/dev/null 2>&1 && { PY="$c"; break; }; done

log(){ mkdir -p "$(dirname "$LOG")" 2>/dev/null; echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG" 2>/dev/null; }

telegram(){  # $1 = testo
  [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ] || { log "TELEGRAM non configurato: $1"; return 0; }
  # -f OBBLIGATORIO: senza, curl esce 0 anche su 401/404 (token revocato) e il ramo di
  # errore qui sotto NON scatta MAI -> restiamo senza allarmi senza saperlo. Provato:
  # senza -f uscita 0, con -f uscita 22.
  curl -sSf -m 15 -o /dev/null \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=$1" \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    || log "CANALE DI ALLARME MUTO: invio Telegram fallito (token revocato? rete?) — msg: $1"
}

# ── misura uptime da dove gira (dentro o fuori) ──────────────────────────────
code="$(curl -sS -m 12 -o /dev/null -w '%{http_code}' "$URL" 2>/dev/null || echo 000)"
if [ "$code" = "200" ]; then UPTIME=ok; else UPTIME=ko; fi

# ── com'e' messa la CI su master ─────────────────────────────────────────────
# Nato dal 31 agosto: `master` e' rimasta ROSSA e nessuno se n'e' accorto per 37 ore. Il
# canale d'allarme c'era gia' e funzionava; mancava la DOMANDA.
# ⛔ NIENTE TOKEN: il repository e' pubblico e questo endpoint non chiede autenticazione.
#    (`git credential fill` dentro cron non ha un gestore e fallirebbe sempre, in silenzio.)
# ⛔ QUOTA: 60 chiamate/ora **PER INDIRIZZO IP, CONDIVISA** con qualunque altra cosa
#    interroghi GitHub da questa macchina. Un giro ogni 10 minuti = 6/ora = 10%. Chi
#    aggiunge un secondo strumento che chiama GitHub da qui deve rifare questo conto:
#    superata la quota si riceve 403 e il guardiano diventa CIECO, non rosso -- e il
#    silenzio somiglia alla salute. La cecita' prolungata la sorveglia `ci_cieca`.
# 🔑 Il riferimento e' il NOME DEL RAMO, non uno sha: cosi' si chiede «master com'e' messa
#    ADESSO», invece della CI del commit che per caso sta sul disco di questa macchina --
#    che qui e' quasi sempre indietro, e risponderebbe alla domanda sbagliata.
CI=skip
if [ "$REMOTO" != "1" ]; then
  CI=cieco                              # finche' non si dimostra di aver letto, si e' ciechi
  J="$(curl -sS -m 15 -H 'Accept: application/vnd.github+json' \
        "https://api.github.com/repos/$CI_REPO/commits/master/check-runs?per_page=100" \
        2>/dev/null)"
  if printf '%s' "$J" | grep -q '"check_runs"'; then
    tot="$(printf '%s' "$J" | grep -c '"status":')"
    aperti="$(printf '%s' "$J" | grep -o '"status": "[a-z_]*"' | grep -cv '"completed"')"
    if [ "$tot" -eq 0 ]; then
      CI=cieco                          # risposta valida ma senza job: non si giudica
    elif [ "$aperti" -gt 0 ]; then
      CI=in_corso                       # GitHub ha risposto: letto SI', verdetto NO
    else
      # ⛔ `cancelled` NON e' fra i buoni. Un job SCADUTO (tetto di tempo superato) si
      #    presenta cosi', non come `failure`: e' il caso vero del 1 settembre. Giudicare
      #    solo su `failure` avrebbe reso questo allarme muto proprio sull'incidente che
      #    lo motiva. `skipped` e `neutral` invece non sono rossi (zap gira a settimana).
      rossi="$(printf '%s' "$J" | grep -o '"conclusion": "[a-z_]*"' \
               | grep -cvE '"(success|skipped|neutral)"')"
      if [ "$rossi" -gt 0 ]; then CI=ko; else CI=ok; fi
    fi
  fi
fi

# ── raccogli gli ALLARMI ATTIVI (uno per riga: "cod|grav|msg") ───────────────
attivi=""
add(){ attivi="$attivi$1
"; }
[ "$UPTIME" = "ko" ] && add "uptime|critico|il sito NON risponde (HTTP $code) da $([ "$REMOTO" = 1 ] && echo 'ESTERNO/PC' || echo 'VPS')"

if [ "$REMOTO" != "1" ]; then
  # diagnosi locale (catena/backup/disco/db) via il modulo puro
  if [ -n "$PY" ]; then
    JSON="$("$PY" "$REPO/fase178_watchdog.py" --dati "$DATA_DIR" --backup "$BACKUP_DIR" \
              --uptime skip --ci "$CI" \
              --max-eta-h "$MAX_ETA_H" --max-disco "$MAX_DISCO" 2>/dev/null)"
    # estrai gli allarmi dal JSON senza dipendenze (con lo stesso Python)
    ALL="$(printf '%s' "$JSON" | "$PY" -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: sys.exit()
for a in d.get("allarmi",[]):
    print("%s|%s|%s"%(a["cod"],a["grav"],a["msg"]))' 2>/dev/null)"
    [ -n "$ALL" ] && attivi="$attivi$ALL
"
  else
    add "watchdog|critico|Python non disponibile sul VPS: auto-diagnosi impossibile"
  fi
fi

# normalizza: righe non vuote, ordinate
attivi="$(printf '%s' "$attivi" | sed '/^$/d' | sort)"
firma="$(printf '%s' "$attivi" | cut -d'|' -f1 | tr '\n' ',')"

# ── confronto con lo stato precedente (anti-spam) ────────────────────────────
prec_firma=""; prec_ts=0
if [ -f "$STATO_FILE" ]; then
  prec_firma="$(sed -n '1p' "$STATO_FILE" 2>/dev/null)"
  prec_ts="$(sed -n '2p' "$STATO_FILE" 2>/dev/null | grep -E '^[0-9]+$' || echo 0)"
fi
ora="$(date +%s)"

manda=0
if [ -n "$attivi" ]; then
  if [ "$firma" != "$prec_firma" ]; then manda=1                       # stato cambiato
  elif [ $((ora - prec_ts)) -ge $((REMINDER_H*3600)) ]; then manda=1; fi # reminder periodico
else
  if [ -n "$prec_firma" ]; then manda=1; fi                             # RIENTRATO: avvisa "tutto ok"
fi

# ── agisci ───────────────────────────────────────────────────────────────────
scope="$([ "$REMOTO" = 1 ] && echo 'esterno' || echo 'vps')"
if [ -n "$attivi" ]; then
  log "ALLARME ($scope): $(printf '%s' "$attivi" | tr '\n' ';')"
  if [ "$manda" = "1" ]; then
    testo="🚨 BookinVIP WATCHDOG ($scope)
$(printf '%s' "$attivi" | while IFS='|' read -r c g m; do
    ic='⚠️'; [ "$g" = 'critico' ] && ic='🔴'; echo "$ic $m"; done)
— $(date '+%Y-%m-%d %H:%M') UTC"
    telegram "$testo"
  fi
  printf '%s\n%s\n' "$firma" "$ora" > "$STATO_FILE" 2>/dev/null
  RC=1
else
  log "OK ($scope): uptime $UPTIME"
  if [ "$manda" = "1" ]; then
    telegram "✅ BookinVIP WATCHDOG ($scope): tutto rientrato, sistema sano — $(date '+%H:%M') UTC"
  fi
  : > "$STATO_FILE" 2>/dev/null || true
  RC=0
fi
exit $RC
