#!/bin/sh
# BANCO DI PROVA — una copia isolata del sito, con Stripe in MODALITA' PROVA.
#
# A COSA SERVE. Tutti gli altri collaudi girano con uno Stripe FINTO. Questo fa
# l'unica cosa che loro non possono fare: percorrere la catena vera fino a Stripe,
# con carte finte e zero soldi. E' il banco su cui si fa la "prova generale".
# Nato il 2026-08-08.
#
# ⛔ FEDELTA' — LA LEZIONE CHE E' COSTATA UNA DIAGNOSI INTERA (2026-08-08, sera).
#    Fino a quel giorno il banco partiva coi soli `--env-file`, e gli mancavano le
#    DICIOTTO variabili del blocco `environment:` del compose: QUATTORDICI dicono
#    DOVE salvare i database. Senza, `main_casavip.py:105` ripiega su `data/…`
#    RELATIVO — dentro il contenitore — e 13 database (pendenti, payout, garanzia,
#    accettazioni, marche temporali) finivano in /app/data, che muore col contenitore.
#    Il banco riproduceva ESATTAMENTE il guasto che il compose esiste per impedire:
#      DB_MARCHE: /data/marche.db  # senza questa riga i token finirebbero in /app/data
#    Costo reale: la «prova generale» ha concluso che la cancellazione non lasciava
#    traccia del rimborso. La traccia c'era (6 pendenti su 6 marcati 'rimborsato'),
#    ma stava su uno scaffale che nessuno guardava, e `docker rm -f` l'ha cancellato.
#    Ora l'ambiente si PRENDE dal contenitore vero (passo [2b]) e un controllo FERMA
#    il banco se non e' fedele (passo [5b]). Guardie: test_pipeline_ci.py,
#    TestIlBancoDiProvaMisuraLaStessaMacchinaDellaProduzione.
#
# ⛔ I SEGRETI NON SI COPIANO dalla produzione al banco: un banco che gira con la
#    chiave vera e' un banco che puo' muovere soldi veri. Arrivano dai --env-file qui
#    sotto; `fedelta_banco.py` li salta per CRITERIO (nome che contiene
#    KEY/SECRET/TOKEN/PASSWORD/…), non per elenco — un elenco nessuno lo aggiorna.
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
PROD=casavip_app                  # il contenitore VERO: da lui si copia l'ambiente
IMG=banco-prova:test
PORTA=18081
DATI=/root/banco_prova_dati
ENVDER=/root/.env.banco_derivato  # GENERATO a ogni giro, mai scritto a mano

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
echo "=== [2b] L'AMBIENTE LO PRENDO DAL CONTENITORE CHE GIRA DAVVERO"
# Non da un elenco ricopiato qui dentro: quello marcisce il giorno che il compose
# cambia, e nessuno se ne accorge finche' non costa una diagnosi sbagliata.
if ! python3 /var/www/bookinvip/collaudi/fedelta_banco.py ambiente "$PROD" "$ENVDER"; then
  echo "  non ho potuto derivare l'ambiente dalla produzione: mi fermo."
  exit 1
fi
chmod 600 "$ENVDER"

echo
echo "=== [3] ACCENDO (isolata, porta solo su 127.0.0.1:$PORTA)"
# ORDINE VOLUTO: i segreti, poi i percorsi presi dalla produzione, e per ULTIMA la
# chiave di prova. L'ultimo --env-file vince: cosi' Stripe resta in modalita' PROVA
# anche se la produzione dovesse portare qualcosa con lo stesso nome.
docker run -d --name "$NOME" \
  --env-file /var/www/bookinvip/.env.casavip \
  --env-file "$ENVDER" \
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
echo "=== [5b] IL BANCO E' FEDELE ALLA PRODUZIONE?  (se no, MI FERMO)"
# Stesso principio del passo [5]: un avviso stampato non basta. Un banco con un
# ambiente diverso non prova il prodotto, prova un'ALTRA macchina -- e i suoi numeri
# sembrano veri lo stesso, che e' il verde peggiore di tutti.
if ! python3 /var/www/bookinvip/collaudi/fedelta_banco.py controlla "$NOME" "$PROD"; then
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
