#!/usr/bin/env bash
# Smoke test del GO-LIVE Tavola VIP: verifica che il server sia RAGGIUNGIBILE e
# risponda CORRETTAMENTE alle chiamate API. Da lanciare DOPO il deploy, dal server
# (o da una macchina che raggiunge nginx). NON e' distruttivo (crea e annulla).
#
#   BASE_URL=https://tuo-host BOOKING_API_KEY=... ./deploy/smoke_tavolavip.sh
set -u
BASE_URL="${BASE_URL:-http://127.0.0.1}"
KEY="${BOOKING_API_KEY:?serve BOOKING_API_KEY (stessa di .env)}"
PASS=0; FAIL=0

chk() {  # descrizione  atteso  ottenuto
  if [ "$2" = "$3" ]; then echo "  PASS  $1 ($3)"; PASS=$((PASS + 1))
  else echo "  FAIL  $1  atteso=$2 ottenuto=$3"; FAIL=$((FAIL + 1)); fi
}
code() { curl -s -o /dev/null -w "%{http_code}" "$@"; }

echo "== SMOKE Tavola VIP @ $BASE_URL =="

# 1) reverse proxy vivo
chk "nginx /healthz -> 200" 200 "$(code "$BASE_URL/healthz")"
# 2) app viva e raggiungibile
chk "GET /api/v1/health -> 200" 200 "$(code "$BASE_URL/api/v1/health")"
# 3) auth obbligatoria sulle route di prenotazione
chk "POST /reservations SENZA chiave -> 401" 401 \
  "$(code -X POST "$BASE_URL/api/v1/reservations" -H 'Content-Type: application/json' -d '{}')"

# 4) crea una prenotazione reale (alloggio/date unici per non collidere)
CI="2030-01-01"; CO="2030-01-03"; ALL="smoke-$(date +%s)"
PAYLOAD="{\"alloggio_id\":\"$ALL\",\"check_in\":\"$CI\",\"check_out\":\"$CO\",\"importo_totale_cents\":12000,\"commissione_cents\":1200}"
BODY=$(curl -s -X POST "$BASE_URL/api/v1/reservations" -H "X-Booking-Key: $KEY" \
  -H 'Content-Type: application/json' -d "$PAYLOAD")
if echo "$BODY" | grep -q '"payment_url"'; then
  echo "  PASS  POST /reservations -> 201 + payment_url"; PASS=$((PASS + 1))
else
  echo "  FAIL  create senza payment_url: $BODY"; FAIL=$((FAIL + 1))
fi
PID=$(echo "$BODY" | sed -n 's/.*"prenotazione_id":[ ]*\([0-9]*\).*/\1/p')

# 5) stato leggibile
chk "GET /reservations/$PID -> 200" 200 \
  "$(code "$BASE_URL/api/v1/reservations/$PID" -H "X-Booking-Key: $KEY")"
# 6) la guardia overlap respinge le stesse date
chk "overlap stesse date -> 409" 409 \
  "$(code -X POST "$BASE_URL/api/v1/reservations" -H "X-Booking-Key: $KEY" \
    -H 'Content-Type: application/json' -d "$PAYLOAD")"
# 7) webhook con firma errata NON deve confermare nulla
chk "webhook firma errata -> 400" 400 \
  "$(code -X POST "$BASE_URL/api/v1/payments/webhook" -H 'X-Pagamento-Firma: BAD' \
    -H 'Content-Type: application/json' -d '{"pagamento_id":1,"pagato":true}')"
# 8) cancel libera il tavolo (cleanup)
chk "cancel /reservations/$PID -> 200" 200 \
  "$(code -X POST "$BASE_URL/api/v1/reservations/$PID/cancel" -H "X-Booking-Key: $KEY")"

echo "== RISULTATO: $PASS PASS / $FAIL FAIL =="
[ "$FAIL" -eq 0 ] || { echo "SMOKE FALLITO -> NON lanciare."; exit 1; }
echo "SMOKE OK -> server pronto al lancio."
