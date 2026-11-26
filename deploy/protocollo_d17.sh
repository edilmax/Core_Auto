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
#     sh deploy/protocollo_d17.sh nginx      # SOLO nginx: ritorno e paracadute suoi + prova + scambio (poi `dopo`)
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
  # LA TRACCIA DELLO SCAMBIO LA SCRIVE LO SCRIPT (22/10/2026): «SCAMBIO FATTO» solo se si arriva in
  # fondo, e «USCITA=» sempre, anche quando `set -e` ferma tutto a meta'. La legge
  # `collaudi/esame_deploy.py` (casella «il deploy passa sempre dal protocollo D17»); prima stava
  # solo nel file che chi lanciava sceglieva a mano, e il codice d'uscita solo se se ne ricordava.
  REGISTRO="${REGISTRI_D17:-/root}/deploy_scambio_$(date -u +%Y%m%d_%H%M%S).log"
  trap 'u=$?; { [ "$u" -eq 0 ] && echo "SCAMBIO FATTO alle $(date -u +%H:%M:%SZ) commit $(git rev-parse --short HEAD 2>/dev/null)"; echo "USCITA=$u"; } >> "$REGISTRO"' EXIT
  echo "  traccia dello scambio: $REGISTRO"

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
  # SOLO app e backup (26/11/2026): un `up -d` senza nomi ricreava anche nginx se nello stesso invio cambiava la sua
  # definizione, senza `nginx -t` e senza il suo paracadute. nginx si cambia solo con la fase `nginx`, qui sotto.
  $C up -d app backup

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
  echo
  echo "=== [3e] ADESSO, DAL PC: LA SCANSIONE ZAP SUL SITO APPENA CAMBIATO"
  echo "  (decisione del fondatore 23/11/2026: ZAP ogni giorno E subito dopo ogni messa"
  echo "  online). Il VPS non ha e non deve avere una chiave di GitHub: dal PC si avvia il"
  echo "  workflow 'BookinVIP CI' a mano (workflow_dispatch su master) e se ne legge il job"
  echo "  'zap' dall'API. Come si fa: DEPLOY.md, «Dopo il deploy: la ZAP»."
  exit 0
fi

# ---------------------------------------------------------------- NGINX ----
# (26/11/2026, n1 di RIPRENDI_QUI.md) Il 24/11 nginx l'ha ricreato /root/aggiorna_nginx_20261124.sh, fuori da qui:
# nessun punto di ritorno, nessuna traccia dello scambio, e `collaudi/esame_deploy.py` l'ha visto (giustamente) come
# ricreato a mano. Da qui in poi nginx -- la sua immagine nel compose o la sua configurazione -- si cambia SOLO con
# questa fase, e poi `dopo`.
# PERCHE' una fase a se' e non un pezzo di `scambio`: il compose non entra nell'immagine dell'app (.dockerignore),
# quindi un cambio della sola impronta di nginx lascia l'app identica e `scambio` si fermerebbe a [2b] («:latest e
# :prec COINCIDONO»). E PERCHE' senza il gettone di `prima`: `prima` riaggancia il paracadute dell'APP alla viva, e
# dopo un cambio del solo nginx il ritorno dell'app non esisterebbe piu'. Punto di ritorno e paracadute di nginx li
# prende questa fase, nello stesso giro dello scambio: non fanno in tempo a invecchiare.
# E IL DISCO RESTA AL CODICE DI PRIMA FINCHE' LO SCAMBIO NON E' RIUSCITO (code-review del 26/11): la definizione nuova
# si prova e si usa da una copia del compose di origin/master; se nginx non torna, il ritorno usa il compose del disco
# piu' immagine e configurazione di prima, e nessuno `scambio` successivo puo' rimettere su la definizione respinta.
# ⚠️ Torna TUTTO com'era solo se il compose del disco e' quello da cui il nginx vivo e' nato (il caso normale: un
# cambio dell'impronta). Se il disco e' gia' piu' avanti (codice preso prima da uno `scambio`), il ritorno rimette
# immagine e configurazione ma non le altre righe nuove di nginx nel compose (RIPRENDI_QUI.md, n7).
if [ "$FASE" = "nginx" ]; then
  REGISTRI="${REGISTRI_D17:-/root}"
  TS=$(date +%Y%m%d-%H%M%S)        # un nome nuovo per ogni giro: il ritorno di un giro vecchio puo' essere montato
  NUOVO="$REGISTRI/nginx_nuovo_$TS.yml"
  CN="docker compose -f $NUOVO --project-directory $RADICE"
  aspetta_200() {   # fino a 30 prove, una al secondo, ognuna al massimo 5 s: un curl appeso non ferma il ritorno
    i=0; CODICE=000
    while [ $i -lt 30 ]; do
      CODICE=$(curl -s -m 5 --connect-timeout 3 -o /dev/null -w '%{http_code}' https://bookinvip.com/api/health) || CODICE=000
      [ "$CODICE" = 200 ] && return 0
      i=$((i+1)); sleep 1
    done
    return 1
  }
  fuori_da_nginx() {   # il compose SENZA il blocco del servizio nginx: da «  nginx:» al servizio o alla sezione dopo
    awk '/^  [^ #][^:]*:/ { dentro = ($1 == "nginx:") } /^[^ #]/ { dentro = 0 } !dentro' "$1"
  }
  echo "=== [Na] IL CODICE NUOVO CAMBIA SOLO NGINX? E IL DISCO POTRA' ANDARE AVANTI DOPO LO SCAMBIO?"
  git fetch -q origin
  # fissato ADESSO: un altro `git fetch` durante la fase non cambia cosa si prova e cosa si porta sul disco
  NUOVO_SHA=$(git rev-parse origin/master)
  # (1) i file: solo il compose e file che sul server non girano (documenti, prove, collaudi, .github). Il resto --
  #     l'immagine dell'app (main_casavip.py, fase*.py, deploy/, Dockerfile.casavip) o un file che nginx monta -- va
  #     prima nello scambio dell'app: il compose nuovo legge i suoi montaggi dal disco, che resta vecchio fino a [Nh]
  #     `--no-renames`: un file spostato conta col nome vecchio E col nuovo (senza, git mostra solo il nuovo). Un
  #     nome per riga, letto intero (spazi compresi); un nome con caratteri speciali git lo scrive fra virgolette
  #     e qui non corrisponde a niente di ammesso: si rifiuta, dalla parte sicura.
  CAMBIATI=$(git diff --no-renames --name-only HEAD "$NUOVO_SHA")
  FUORI=$(printf '%s\n' "$CAMBIATI" | while IFS= read -r f; do
    case "$f" in
      ''|collaudi/*|.github/*) ;;
      */*) printf '%s\n' "$f" ;;         # ogni altra cartella, deploy/ compresa (anche un .md: entra nell'immagine)
      docker-compose.casavip.yml|*.md|test_*.py) ;;
      *) printf '%s\n' "$f" ;;
    esac
  done)
  if [ -n "$FUORI" ]; then
    echo "  ⛔ il codice nuovo cambia file che il server usa oltre al compose (l'immagine dell'app o file montati):"
    printf '%s\n' "$FUORI" | while IFS= read -r f; do echo "     $f"; done
    echo "  Prima 'prima' + 'scambio' + 'dopo' (prendono il codice e rifanno l'app), poi questa fase. MI FERMO"
    exit 1
  fi
  # (2) il compose: fuori dal blocco di nginx (app, backup, reti, volumi) deve restare identico riga per riga. Due
  #     letture vuote non sono «uguali», sono una misura non valida (sbaglio S1).
  git show "$NUOVO_SHA:docker-compose.casavip.yml" > "$NUOVO"
  RESTO_DISCO=$(fuori_da_nginx docker-compose.casavip.yml)
  RESTO_NUOVO=$(fuori_da_nginx "$NUOVO")
  [ -n "$RESTO_DISCO" ] && [ -n "$RESTO_NUOVO" ] || {
    echo "  ⛔ misura non valida: il compose del disco o quello nuovo si legge vuoto. MI FERMO"; exit 1; }
  if [ "$RESTO_DISCO" != "$RESTO_NUOVO" ]; then
    echo "  ⛔ il compose nuovo cambia anche fuori da nginx (app, backup, reti o volumi): questa fase ricrea solo"
    echo "     nginx e quel cambio resterebbe sul disco senza essere applicato (RIPRENDI_QUI.md, blocco 8, n3). MI FERMO"
    exit 1
  fi
  $CN config -q
  # (3) l'avanti veloce di [Nh] arriva DOPO lo scambio: le tre cose che lo farebbero fallire si guardano adesso
  git merge-base --is-ancestor HEAD "$NUOVO_SHA" || {
    echo "  ⛔ il commit del disco non e' un antenato di $NUOVO_SHA: niente avanti veloce possibile. MI FERMO"; exit 1; }
  SPORCHI=$(git status --porcelain --untracked-files=no)
  [ -z "$SPORCHI" ] || {
    echo "  ⛔ file del progetto modificati sul server (l'avanti veloce si fermerebbe):"; printf '     %s\n' "$SPORCHI"
    echo "  MI FERMO"; exit 1; }
  AGGIUNTI=$(git diff --no-renames --name-only --diff-filter=A HEAD "$NUOVO_SHA")
  GIA=$(printf '%s\n' "$AGGIUNTI" | while IFS= read -r f; do [ -z "$f" ] || [ ! -e "$f" ] || printf '%s\n' "$f"; done)
  [ -z "$GIA" ] || {
    echo "  ⛔ arriva col codice nuovo ma esiste gia' sul server (l'avanti veloce si fermerebbe): $GIA. MI FERMO"; exit 1; }
  echo "  OK: cambiano solo nginx, documenti o prove; codice nuovo $NUOVO_SHA, compose nuovo in $NUOVO"

  echo
  echo "=== [Nb] PUNTO DI RITORNO — scritto E RILETTO dal disco"
  PRIMA=$(git rev-parse --short HEAD)
  echo "$PRIMA" > "$REGISTRI/PRE_DEPLOY_$TS.commit"
  RILETTO=$(cat "$REGISTRI/PRE_DEPLOY_$TS.commit")
  echo "  scritto:  $REGISTRI/PRE_DEPLOY_$TS.commit"
  echo "  RILETTO:  $RILETTO   (deve dire $PRIMA)"
  [ "$RILETTO" = "$PRIMA" ] || { echo "  ⛔ il punto di ritorno non si rilegge — MI FERMO"; exit 1; }

  echo
  echo "=== [Nc] PARACADUTE casavip-nginx:prec — l'immagine e la configurazione che nginx usa ADESSO"
  [ "$(docker inspect --format='{{.State.Running}}' casavip_nginx)" = true ] || {
    echo "  ⛔ casavip_nginx non e' in esecuzione (fermo o in riavvio): non c'e' una configurazione viva da tenere"
    echo "     per il ritorno. Emergenza: DEPLOY.md §1. MI FERMO"; exit 1; }
  NGINX_VIVA=$(docker inspect --format="{{.Image}}" casavip_nginx)
  echo "  immagine viva di nginx: $NGINX_VIVA"
  # `:prec` e' il paracadute di cui parlano DEPLOY.md e l'esame; `:prec-<ora>` e' quello di QUESTO giro, e il file
  # del ritorno usa lui: un giro successivo riaggancia `:prec`, ma il ritorno di questo resta coerente
  docker tag "$NGINX_VIVA" casavip-nginx:prec
  docker tag "$NGINX_VIVA" "casavip-nginx:prec-$TS"
  for t in casavip-nginx:prec "casavip-nginx:prec-$TS"; do
    [ "$(docker inspect --format='{{.Id}}' "$t")" = "$NGINX_VIVA" ] || {
      echo "  ⛔ il paracadute di nginx ($t) NON coincide con l'immagine viva — MI FERMO"; exit 1; }
  done
  # la configurazione si legge DENTRO il contenitore: quella del disco puo' essere gia' nuova (git sostituisce il
  # file e Docker resta agganciato al vecchio per inode: DEPLOY.md §3). File nuovo a ogni giro: dopo un ritorno
  # nginx tiene MONTATO il file del giro di allora, e riscriverlo lo svuoterebbe sotto il nginx vivo.
  CONF_PREC="$REGISTRI/nginx_prec_$TS.conf"
  RITORNO="$REGISTRI/nginx_prec_$TS.yml"
  docker exec casavip_nginx cat /etc/nginx/conf.d/default.conf > "$CONF_PREC"
  [ -s "$CONF_PREC" ] || { echo "  ⛔ la configurazione viva letta da nginx e' VUOTA: niente ritorno possibile — MI FERMO"; exit 1; }
  printf 'services:\n  nginx:\n    image: casavip-nginx:prec-%s\n    volumes:\n      - %s:/etc/nginx/conf.d/default.conf:ro\n' \
    "$TS" "$CONF_PREC" > "$RITORNO"
  $C -f "$RITORNO" config -q
  echo "  OK: il ritorno ($RITORNO, sul compose di adesso) e' pronto e valido, prima di toccare il sito"

  echo
  echo "=== [Nd] LA DEFINIZIONE NUOVA DI NGINX, PROVATA PRIMA DI TOCCARE IL SITO"
  # un contenitore usa e getta con la definizione del compose NUOVO (rete, montaggi in sola lettura): il nginx vivo
  # e il disco non si toccano. Se l'immagine nuova manca, Docker la scarica qui.
  $CN run --rm --no-deps -T nginx nginx -t || {
    echo "  ⛔ la definizione nuova non regge: nginx e il disco sono come prima, il sito non e' stato toccato. MI FERMO"
    exit 1; }

  echo
  echo "=== [Ne] LONTANO DAL GUARDIANO (cron ogni 10 minuti: nginx giu' in quel secondo = un falso allarme)"
  # si guarda ADESSO, subito prima dello scambio: le preparazioni qui sopra possono scaricare un'immagine e durare.
  # Senza i due punti apposta: GUARDIANO_D17="" (lo usano solo le guardie di prova) vuol dire «nessun minuto vietato».
  M=$(date -u +%M); M=${M#0}
  for v in ${GUARDIANO_D17-9 0 1}; do
    [ $((M % 10)) -ne "$v" ] || {
      echo "  ⛔ minuto $M: troppo vicino al guardiano. Il sito non e' stato toccato: rilancia questa fase fra due minuti"
      exit 1; }
  done
  echo "  minuto $M: lontano dal guardiano"

  echo
  echo "=== [Nf] TRACCIA DELLO SCAMBIO (la legge collaudi/esame_deploy.py, come quella dell'app)"
  REGISTRO="$REGISTRI/deploy_scambio_$(date -u +%Y%m%d_%H%M%S).log"
  trap 'u=$?; { [ "$u" -eq 0 ] && echo "SCAMBIO FATTO alle $(date -u +%H:%M:%SZ) commit $(git rev-parse --short HEAD 2>/dev/null) (nginx)"; echo "USCITA=$u"; } >> "$REGISTRO"' EXIT
  echo "  traccia dello scambio: $REGISTRO"

  echo
  echo "=== [Ng] SCAMBIO: ricreo SOLO nginx col compose nuovo (app e backup non si toccano), poi /api/health"
  # se la ricreazione fallisce non si guarda /api/health: il nginx vecchio potrebbe ancora rispondere 200, e si
  # scriverebbe «SCAMBIO FATTO» per uno scambio mai avvenuto. Si va diritti al ritorno.
  SANO=no
  if $CN up -d --no-deps --force-recreate nginx; then
    if aspetta_200; then
      SANO=si; echo "  /api/health -> 200 al tentativo $((i+1)) di 30"
    else
      echo "  /api/health -> $CODICE: nessun 200 in 30 tentativi"
    fi
  else
    echo "  ⛔ la ricreazione di nginx e' fallita"
  fi
  if [ "$SANO" != si ]; then
    echo "  ⛔ nginx non e' tornato: TORNO INDIETRO DA SOLO (compose del disco, immagine e configurazione di prima)"
    if $C -f "$RITORNO" up -d --no-deps --force-recreate nginx && aspetta_200; then
      echo "  ritorno riuscito: /api/health -> 200 al tentativo $((i+1)). Il disco e' rimasto al codice di prima ($PRIMA)."
      # la traccia distingue «tornato indietro e il sito risponde» da «fallito e basta» (USCITA resta diversa da 0)
      echo "RITORNO RIUSCITO alle $(date -u +%H:%M:%SZ) commit $PRIMA (nginx)" >> "$REGISTRO"
    else
      echo "  ⛔⛔ ANCHE IL RITORNO NON RISPONDE (/api/health -> $CODICE): il sito puo' essere GIU'."
      echo "     Subito: docker ps -a; docker logs casavip_nginx; DEPLOY.md, «Solo nginx»."
    fi
    exit 1
  fi

  echo
  echo "=== [Nh] IL CODICE NUOVO SUL DISCO (solo avanti veloce), ora che nginx lo usa e risponde"
  git merge --ff-only "$NUOVO_SHA" || {
    echo "  ⛔ nginx gira gia' col compose nuovo ma il disco NON e' andato avanti: allinearlo prima di qualunque altro"
    echo "     deploy (git merge --ff-only $NUOVO_SHA), oppure tornare indietro: $C -f $RITORNO up -d --no-deps --force-recreate nginx"
    exit 1; }
  echo "  commit dei file ora: $(git rev-parse --short HEAD)"

  echo
  echo "=== [Ni] COSA GIRA ADESSO"
  echo "  nginx gira:       $(docker inspect --format='{{.Image}}' casavip_nginx)"
  echo "  paracadute nginx: $(docker inspect --format='{{.Id}}' casavip-nginx:prec)"
  echo "  il ritorno, se servisse (prima di un altro deploy): $C -f $RITORNO up -d --no-deps --force-recreate nginx"
  echo "  Adesso: sh deploy/protocollo_d17.sh dopo   (e poi la ZAP dal computer)"
  exit 0
fi

echo "uso: sh deploy/protocollo_d17.sh [prima|scambio|dopo|nginx]"
exit 2
