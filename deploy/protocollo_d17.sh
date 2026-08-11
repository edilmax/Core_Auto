#!/bin/sh
# PROTOCOLLO D17 — il deploy a rischio zero, nei tre passi che DEVONO stare in quest'ordine.
#
# PERCHE' ESISTE, visto che DEPLOY.md descrive gia' la procedura. Perche' D17 aggiunge tre
# cose che a parole si saltano, e che infatti sono state saltate:
#   · il punto di ritorno va RILETTO dal disco (scriverlo non basta: un file vuoto sembra
#     un file scritto);
#   · il paracadute `:prec` va RI-AGGANCIATO all'immagine che gira ADESSO. Il 2026-08-07
#     puntava a un'immagine di CINQUE giorni prima, e il 2026-08-08 di nuovo a una vecchia:
#     due volte in due giorni. Un paracadute agganciato all'immagine sbagliata e' PEGGIO di
#     nessun paracadute, perche' ci si salta convinti di tornare all'ultimo stato buono;
#   · il salvataggio si verifica APRENDOLO, non guardando la data.
#
# USO, sul VPS:
#     sh deploy/protocollo_d17.sh prima      # punto di ritorno + paracadute + backup
#     sh deploy/protocollo_d17.sh scambio    # pull + build + rm-first + up
#     sh deploy/protocollo_d17.sh dopo       # sonde nelle due direzioni + giudice
#
# ⛔ `docker compose` (DUE PAROLE) e' la v2. `docker-compose` col trattino e' la v1 e BUTTA
#    GIU' nginx, cioe' il sito. In questo file la v1 non compare mai.
set -e
FASE="${1:-}"
C="docker compose -f docker-compose.casavip.yml"
# I due valori qui sotto si possono sovrascrivere SOLO per poter provare questo script: in
# produzione valgono i predefiniti. Senza, le guardie del passo di sicurezza non potrebbero
# eseguirlo affatto -- e una difesa che non si puo' mettere alla prova e' indistinguibile da
# codice morto (D19).
RADICE="${RADICE_D17:-/var/www/bookinvip}"
GETTONE="${GETTONE_D17:-/root/.d17_gettone}"
FRESCHEZZA=3600     # un `prima` vale un'ora: dopo, l'immagine viva puo' essere gia' cambiata
cd "$RADICE"

# ⛔ IL PASSO DI SICUREZZA NON E' UN CONSIGLIO: E' UNA PRECONDIZIONE DELLO SCAMBIO.
# Il paracadute e' finito agganciato all'immagine sbagliata SEI volte in sei giorni. Il
# 2026-08-11 si e' capito perche': non mancava lo strumento -- questo file esiste dal
# 2026-08-07 e il controllo [1b] funziona -- mancava l'OBBLIGO di passarci. Le tre fasi erano
# indipendenti, quindi si poteva fare `scambio` senza aver mai fatto `prima`, o deployare a
# mano saltando tutto (che e' esattamente cio' che e' successo). Una procedura corretta che si
# puo' saltare non e' un controllo: e' la stessa malattia del gancio pre-commit, scoperta lo
# stesso giorno. Da qui in poi `scambio` PRETENDE la prova che `prima` sia stata fatta, e da poco.
pretendi_gettone() {
  if [ ! -f "$GETTONE" ]; then
    echo "GETTONE_MANCANTE: non risulta eseguita la fase 'prima'."
    echo "  Senza, il paracadute :prec puo' puntare a un'immagine vecchia: tirando la"
    echo "  maniglia si tornerebbe indietro OLTRE l'ultimo stato buono, in silenzio."
    echo "  Rimedio:  sh deploy/protocollo_d17.sh prima"
    return 1
  fi
  # `|| true` DICHIARATO (regola ferrea 12): non nasconde niente, perche' il valore letto
  # viene validato subito sotto e l'assenza diventa un rifiuto esplicito.
  EPOCA=$(grep '^epoca=' "$GETTONE" | cut -d= -f2 || true)
  if [ -z "$EPOCA" ]; then
    echo "GETTONE_ILLEGGIBILE: $GETTONE non dice quando e' stato scritto."
    echo "  Un gettone che non si sa quando e' nato non prova niente."
    echo "  Rimedio:  sh deploy/protocollo_d17.sh prima"
    return 1
  fi
  ETA=$(( $(date +%s) - EPOCA ))
  if [ "$ETA" -gt "$FRESCHEZZA" ] || [ "$ETA" -lt 0 ]; then
    echo "GETTONE_SCADUTO: la fase 'prima' risale a ${ETA}s fa (limite ${FRESCHEZZA}s)."
    echo "  Nel frattempo l'immagine che gira puo' essere cambiata: il paracadute non e'"
    echo "  piu' una prova, e' un ricordo."
    echo "  Rimedio:  sh deploy/protocollo_d17.sh prima"
    return 1
  fi
  echo "  gettone OK: la fase 'prima' e' stata fatta ${ETA}s fa"
  return 0
}

# --------------------------------------------------------------- GETTONE ----
# Solo il controllo, senza toccare ne' git ne' docker. Esiste perche' le guardie possano
# ESEGUIRLO DAVVERO invece di cercare parole nel sorgente (una guardia che conta nel testo
# la soddisferebbe anche un commento -- sbaglio S6).
if [ "$FASE" = "gettone" ]; then
  pretendi_gettone || exit 1
  exit 0
fi

# ---------------------------------------------------------------- PRIMA ----
if [ "$FASE" = "prima" ]; then
  echo "=== [1a] PUNTO DI RITORNO — scritto E RILETTO dal disco"
  TS=$(date +%Y%m%d-%H%M%S)
  PRIMA=$(git rev-parse --short HEAD)
  echo "$PRIMA" > "/root/PRE_DEPLOY_$TS.commit"
  echo "  scritto:  /root/PRE_DEPLOY_$TS.commit"
  echo "  RILETTO:  $(cat "/root/PRE_DEPLOY_$TS.commit")   (deve dire $PRIMA)"

  echo
  echo "=== [1b] PARACADUTE :prec — ri-agganciato all'immagine CHE GIRA ADESSO"
  VIVA=$(docker inspect --format="{{.Image}}" casavip_app)
  echo "  immagine viva: $VIVA"
  echo "  :prec PRIMA:   $(docker inspect --format='{{.Id}}' casavip-app:prec 2>/dev/null || echo assente)"
  docker tag "$VIVA" casavip-app:prec
  echo "  :prec DOPO:    $(docker inspect --format='{{.Id}}' casavip-app:prec)"
  [ "$(docker inspect --format='{{.Id}}' casavip-app:prec)" = "$VIVA" ] || {
    echo "  ⛔ il paracadute NON coincide con l'immagine viva — MI FERMO"; exit 1; }
  echo "  OK: il paracadute e' agganciato a cio' che sta servendo il sito adesso"

  echo
  echo "=== [1c] IL SALVATAGGIO, VERIFICATO APRENDOLO (non guardando la data)"
  ULTIMO=$(docker exec casavip_app sh -c 'ls -1t /data/backup/finanza-*.db.gz 2>/dev/null | head -1')
  [ -n "$ULTIMO" ] || { echo "  ⛔ NESSUN backup di finanza — MI FERMO"; exit 1; }
  echo "  archivio: $ULTIMO"
  docker exec casavip_app sh -c "gzip -t '$ULTIMO' && echo '  gzip -t: integro'"
  docker exec casavip_app sh -c "gzip -dc '$ULTIMO' | head -c 16 | od -c | head -1"
  echo "  (i primi byte devono dire: SQLite format 3)"

  echo
  echo "=== [1d] STATO PRIMA DELLO SCAMBIO"
  docker ps --format "  {{.Names}} | {{.Status}}"
  echo "  commit dei file: $PRIMA"

  echo
  echo "=== [1e] GETTONE — la prova, scritta E RILETTA, che questo passo e' stato fatto"
  {
    echo "epoca=$(date +%s)"
    echo "immagine=$VIVA"
    echo "commit=$PRIMA"
  } > "$GETTONE"
  echo "  scritto:  $GETTONE"
  echo "  RILETTO:  $(tr '\n' ' ' < "$GETTONE")"
  [ -s "$GETTONE" ] || { echo "  ⛔ il gettone e' VUOTO — MI FERMO"; exit 1; }
  echo "  Da adesso 'scambio' puo' partire, e solo per i prossimi ${FRESCHEZZA}s."
  exit 0
fi

# -------------------------------------------------------------- SCAMBIO ----
if [ "$FASE" = "scambio" ]; then
  echo "=== [2z] IL PASSO DI SICUREZZA E' STATO FATTO? (precondizione, non consiglio)"
  pretendi_gettone || exit 1

  echo
  echo "=== [2a] PRENDO IL CODICE NUOVO"
  git pull --ff-only
  echo "  commit dei file ora: $(git rev-parse --short HEAD)"

  echo
  echo "=== [2b] COSTRUISCO (il sito continua a girare su quella vecchia)"
  $C build app
  NUOVA=$(docker inspect --format="{{.Id}}" casavip-app:latest)
  PREC=$(docker inspect --format="{{.Id}}" casavip-app:prec)
  echo "  :latest  $NUOVA"
  echo "  :prec    $PREC"
  [ "$NUOVA" != "$PREC" ] || {
    echo "  ⛔ :latest e :prec COINCIDONO: il ritorno non esisterebbe. MI FERMO."; exit 1; }
  echo "  OK: sono diverse, quindi il paracadute e' un paracadute"

  echo
  echo "=== [2c] SCAMBIO (sequenza rm-first di DEPLOY.md §3)"
  $C stop app backup
  $C rm -f app backup
  $C up -d

  echo
  echo "=== [2d] ASPETTO CHE TORNI SANO (max 90s)"
  i=0
  while [ $i -lt 45 ]; do
    S=$(docker inspect --format="{{.State.Health.Status}}" casavip_app 2>/dev/null || echo assente)
    [ "$S" = "healthy" ] && break
    i=$((i+1)); sleep 2
  done
  echo "  stato: $S   (dopo $((i*2))s)"
  docker ps --format "  {{.Names}} | {{.Status}}"

  echo
  echo "=== [2e] L'AVVIO"
  docker logs casavip_app 2>&1 | grep -oE "'money_path_pronto': [A-Za-z]+|'avvisi': \[[^]]*\]" | tail -2
  echo "  atteso: money_path_pronto True · avvisi []"
  echo
  echo "=== [2f] L'IMMAGINE CHE GIRA E' QUELLA NUOVA?"
  echo "  gira:    $(docker inspect --format='{{.Image}}' casavip_app)"
  echo "  :latest  $NUOVA"

  echo
  echo "=== [2g] CONSUMO IL GETTONE — vale per UNO scambio, non per la giornata"
  # Se restasse, un secondo deploy piu' tardi passerebbe col paracadute agganciato
  # all'immagine di PRIMA di questo: cioe' di nuovo alla cosa sbagliata, che e' il difetto
  # che questo controllo esiste per impedire.
  rm -f "$GETTONE"
  echo "  tolto: $GETTONE  (il prossimo scambio dovra' rifare 'prima')"
  exit 0
fi

# ----------------------------------------------------------------- DOPO ----
if [ "$FASE" = "dopo" ]; then
  echo "=== [3a] SONDE POSITIVE — su HTTPS, la porta che usa la gente"
  # ⛔ NON su http://localhost: li' TUTTO risponde 301 (il rimando a HTTPS di nginx arriva
  #    prima dell'applicazione), quindi si misurerebbe nginx e non i permessi. Errore fatto
  #    davvero il 2026-08-08.
  for u in / /api/health; do
    printf "  %-14s -> %s\n" "$u" "$(curl -s -o /dev/null -w '%{http_code}' "https://bookinvip.com$u")"
  done
  echo "  attesi: 200 e 200"

  echo
  echo "=== [3b] SONDA NEGATIVA — un indirizzo che ESISTE e deve rifiutare"
  printf "  %-26s -> %s\n" "/api/bunker/invarianti" \
    "$(curl -s -o /dev/null -w '%{http_code}' https://bookinvip.com/api/bunker/invarianti)"
  echo "  atteso: 403. ⛔ NON si inventano percorsi: /api/admin/lista risponde 404, cioe'"
  echo "  «non esiste», e un 404 non prova MAI che qualcosa sia protetto (D17)."

  echo
  echo "=== [3c] IL GIUDICE DEL PROGETTO — sull'HOST (collaudi/ non e' nell'immagine),"
  echo "    e con l'uscita letta SENZA TUBI (regola ferrea 7)"
  python3 collaudi/verifica_produzione.py > /tmp/_vp.txt 2>&1
  ESITO=$?
  echo "  USCITA: $ESITO   (0 = nessuna violazione)"
  tail -6 /tmp/_vp.txt
  rm -f /tmp/_vp.txt

  echo
  echo "=== [3d] LA PROVA VERA: cosa c'e' DENTRO il contenitore che gira"
  echo "  (non «l'ho spinto»: si guarda dentro)"
  echo "  commit dei file: $(git rev-parse --short HEAD)"
  echo "  immagine viva:   $(docker inspect --format='{{.Image}}' casavip_app | cut -c1-20)"
  echo "  paracadute prec: $(docker inspect --format='{{.Id}}' casavip-app:prec | cut -c1-20)"
  exit 0
fi

echo "uso: sh deploy/protocollo_d17.sh [prima|scambio|dopo]"
exit 2
