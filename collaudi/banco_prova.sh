#!/bin/sh
# BANCO DI PROVA — una copia isolata del sito, con Stripe in MODALITA' PROVA.
#
# A COSA SERVE. Tutti gli altri collaudi girano con uno Stripe FINTO. Questo fa
# l'unica cosa che loro non possono fare: percorrere la catena vera fino a Stripe,
# con carte finte e zero soldi. E' il banco su cui si fa la "prova generale".
# Nato il 2026-08-08; con esso e' stato trovato il difetto del rimborso senza
# traccia, che nessuno dei 5457 test aveva mai visto.
#
# ⛔ NON TOCCA IL SITO VERO: nome diverso, immagine diversa, cartella dati VUOTA,
#    e la porta e' pubblicata SOLO su 127.0.0.1 (irraggiungibile da fuori).
# ⛔ LA CHIAVE non compare mai nella riga di comando (finirebbe nell'elenco dei
#    processi): arriva da /root/.env.prova, che va creato a mano con permessi 600:
#        STRIPE_SECRET_KEY=sk_test_...
#        STRIPE_LIVE_SECRET_KEY=sk_test_...
#        STRIPE_IDENTITY_KEY=
#        STRIPE_WEBHOOK_SECRET=whsec_bancoprova
#    La chiave di prova sta in dashboard.stripe.com/test/apikeys, sezione
#    "Chiavi standard -> Chiave privata", dietro il bottone "Rivela".
#    ⚠️ NON e' la tabella "Chiavi con limitazioni": quella e' un'altra cosa, e
#       cercarla li' e' costato mezz'ora il 2026-08-08.
#
# USO, sul VPS:   sh /var/www/bookinvip/collaudi/banco_prova.sh
# SMONTARE:       docker rm -f banco_prova_app && rm -rf /root/banco_prova_dati
# ⛔ PRIMA DI SMONTARE, LEGGERE I REGISTRI:
#        docker logs banco_prova_app 2>&1 | grep -iE "warning|error"
#    Il 2026-08-08 il banco e' stato smontato prima di leggerli, e si e' persa la
#    prova di PERCHE' la registrazione del pendente non avviene. Pulizia solo
#    dopo la prova: e' la regola ferrea 5, violata proprio da chi l'aveva letta.
set -e
NOME=banco_prova_app
IMG=banco-prova:test
PORTA=18081
DATI=/root/banco_prova_dati

echo "=== [1] PULIZIA DI GIRI PRECEDENTI"
docker rm -f "$NOME" 2>/dev/null || true
rm -rf "$DATI"; mkdir -p "$DATI"
# l'applicazione gira come utente `app` (uid 10001): senza questo non scrive, e
# fallisce con due errori che NON nominano la causa (PermissionError su
# /data/app.log e "attempt to write a readonly database").
chown -R 10001:999 "$DATI"
echo "  cartella dati vuota, proprietario $(stat -c '%u:%g' "$DATI")"

echo
echo "=== [2] COSTRUISCO L'IMMAGINE dal repository (stesso codice del sito vero)"
cd /var/www/bookinvip
echo "  commit: $(git rev-parse --short HEAD)"
docker build -q -f Dockerfile.casavip -t "$IMG" . > /tmp/_bimg.txt 2>&1 || {
  echo "  BUILD FALLITA:"; tail -20 /tmp/_bimg.txt; exit 1; }
echo "  costruita: $(tail -1 /tmp/_bimg.txt | cut -c1-26)"

echo
echo "=== [3] ACCENDO (isolata, porta solo su 127.0.0.1:$PORTA)"
docker run -d --name "$NOME" \
  --env-file /var/www/bookinvip/.env.casavip \
  --env-file /root/.env.prova \
  -v "$DATI":/data \
  -p 127.0.0.1:$PORTA:8080 \
  "$IMG" > /dev/null
echo "  avviata"

echo
echo "=== [4] ASPETTO CHE RISPONDA (max 60s)"
i=0
while [ $i -lt 30 ]; do
  C=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORTA/api/health" 2>/dev/null || echo 000)
  [ "$C" = "200" ] && break
  i=$((i+1)); sleep 2
done
echo "  /api/health -> $C   (dopo $((i*2))s)"

echo
echo "=== [5] CON QUALE STRIPE E' PARTITA?  (la chiave non viene mai stampata)"
# ⛔ QUESTO CONTROLLO DEVE FERMARE, NON SOLO DIRE. Una copia di prova partita con
#    la chiave VERA e' una copia che puo' muovere soldi veri: un avviso stampato
#    non basta, perche' al giro dopo non lo legge nessuno. Esce 1 e si smonta.
if ! docker exec "$NOME" python3 -c "
import os, sys
k = os.environ.get('STRIPE_SECRET_KEY','')
if k.startswith('sk_test_'):
    print('  modalita\': PROVA (sk_test_) -- nessun soldo vero puo\' muoversi')
elif k.startswith('sk_live'):
    print('  modalita\': VERA (sk_live_) -- MI FERMO: una copia di prova non gira con la chiave vera')
    sys.exit(1)
else:
    print('  modalita\': SCONOSCIUTA -- MI FERMO: non so con che chiave sto partendo')
    sys.exit(1)
print('  webhook secret impostato:', 'si' if os.environ.get('STRIPE_WEBHOOK_SECRET') else 'NO')
"; then
  echo "  smonto la copia di prova e mi fermo."
  docker rm -f "$NOME" > /dev/null 2>&1 || true
  exit 1
fi

echo
echo "=== [6] L'AVVIO: si e' acceso tutto?"
docker logs "$NOME" 2>&1 | grep -oE "'money_path_pronto': [A-Za-z]+|'avvisi': \[[^]]*\]" | tail -2
echo "  errori nel log: $(docker logs "$NOME" 2>&1 | grep -ciE 'traceback|critical' || true)"

echo
echo "=== [7] IL SITO VERO NON E' STATO TOCCATO:"
docker ps --format "  {{.Names}} | {{.Status}}"
echo
echo "  ora:  docker exec -i $NOME python3 -  <  collaudi/giro_banco.py"
