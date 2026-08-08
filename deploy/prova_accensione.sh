#!/bin/sh
# PROVA DI ACCENSIONE — «se carico questa chiavetta su una VPS, il sito riparte?»
#
# La prova di ripristino dimostra che il CODICE e' completo (la suite gira).
# Non dimostra che si ACCENDE: sono due cose diverse, e la seconda e' quella che
# serve davvero il giorno del guasto. Qui l'immagine viene costruita DAI FILE
# DELLA CHIAVETTA -- non da quelli del repository -- e avviata con i suoi dati
# e le sue chiavi.
#
# ⛔ NON TOCCA IL SITO VERO: nome diverso, immagine diversa, e la porta e'
# pubblicata SOLO su 127.0.0.1 (non raggiungibile da fuori). Le 80/443 restano
# dove sono. Alla fine si smonta tutto.
set -e
BASE=/root/prova_accensione
NOME=prova_chiavetta_app
IMG=prova-chiavetta:test
PORTA=18080

echo "=== PULIZIA DI EVENTUALI GIRI PRECEDENTI ==="
docker rm -f "$NOME" 2>/dev/null || true
rm -rf "$BASE"
mkdir -p "$BASE/progetto" "$BASE/dati"

echo "=== ESTRAGGO DALLA CHIAVETTA (gli stessi due archivi, non i file del repo) ==="
tar xzf /root/clone_progetto.tgz -C "$BASE/progetto"
tar xzf /root/clone_dati.tgz     -C "$BASE/dati"
echo "  file di progetto: $(find "$BASE/progetto" -type f | wc -l)"
echo "  database:         $(ls -1 "$BASE/dati"/*.db | wc -l)"

# ⛔ IL PASSO CHE MANCAVA, E CHE MANCA A CHIUNQUE RIPRISTINI.
# Dentro il contenitore l'applicazione NON gira da amministratore: e' l'utente
# `app`, uid 10001 gid 999 (misurato: `docker exec casavip_app id`). Chi ripristina
# copia i database da root, quindi restano di root, e l'applicazione non ci puo'
# scrivere. Il sito allora NON PARTE, con due errori che non dicono la vera causa:
#   PermissionError: [Errno 13] ... '/data/app.log'
#   sqlite3.OperationalError: attempt to write a readonly database
# Succede davvero: questa prova e' fallita cosi' al primo giro.
chown -R 10001:999 "$BASE/dati"
echo "  proprietario dati: $(stat -c '%u:%g' "$BASE/dati")  (deve essere 10001:999)"

echo
echo "=== COSTRUISCO L IMMAGINE DA QUEI FILE ==="
cd "$BASE/progetto"
docker build -q -f Dockerfile.casavip -t "$IMG" . > /tmp/_img.txt 2>&1 || { echo "BUILD FALLITA:"; tail -20 /tmp/_img.txt; exit 1; }
echo "  costruita: $(cat /tmp/_img.txt | tail -1 | cut -c1-26)"

echo
echo "=== ACCENDO (isolata, porta solo su 127.0.0.1) ==="
docker run -d --name "$NOME" \
  --env-file "$BASE/progetto/.env.casavip" \
  -v "$BASE/dati":/data \
  -p 127.0.0.1:$PORTA:8080 \
  "$IMG" > /dev/null
echo "  avviata"

echo
echo "=== ASPETTO CHE RISPONDA (max 60s) ==="
i=0
while [ $i -lt 30 ]; do
  CODICE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORTA/api/health" 2>/dev/null || echo 000)
  if [ "$CODICE" = "200" ]; then break; fi
  i=$((i+1)); sleep 2
done
echo "  /api/health -> $CODICE   (dopo $((i*2)) secondi)"

echo
echo "=== IL LOG D AVVIO: si e' acceso tutto? ==="
docker logs "$NOME" 2>&1 | grep -oE "'money_path_pronto': [A-Za-z]+|'avvisi': \[[^]]*\]" | head -4
echo "--- eventuali errori nel log ---"
docker logs "$NOME" 2>&1 | grep -icE "traceback|critical" || true

echo
echo "=== ALTRE DUE SONDE (una pagina e una porta CHIUSA) ==="
curl -s -o /dev/null -w "  /            -> %{http_code}\n" "http://127.0.0.1:$PORTA/"
# ⛔ NON /api/admin/lista: risponde 404, cioe' «questa pagina non c'e'», e un 404 non
#    prova MAI che qualcosa sia protetto -- e' l'ornamento che D17 vieta, ed era rimasto
#    qui dentro fino all'8 agosto. L'indirizzo giusto ESISTE e risponde 403.
curl -s -o /dev/null -w "  /api/bunker/invarianti -> %{http_code}   (atteso 403; un 404 vorrebbe dire che sto interrogando un indirizzo che non esiste)\n" "http://127.0.0.1:$PORTA/api/bunker/invarianti"

echo
echo "=== SMONTO TUTTO ==="
docker rm -f "$NOME" > /dev/null
docker rmi -f "$IMG" > /dev/null 2>&1 || true
rm -rf "$BASE" /tmp/_img.txt
echo "  smontato. Il sito vero non e' stato toccato:"
docker ps --format "  {{.Names}} | {{.Status}}"
