#!/bin/sh
# BookinVIP - bootstrap HTTPS Let's Encrypt (pattern nginx+certbot, idempotente).
# Eseguire UNA VOLTA sul VPS, dalla cartella del progetto, DOPO aver puntato il DNS
# (A record di bookinvip.com e www.bookinvip.com -> IP del server) e creato .env.casavip:
#
#   chmod +x deploy/init-letsencrypt.sh && ./deploy/init-letsencrypt.sh
#
# Risolve l'uovo-e-gallina: nginx non parte senza certificato, il certificato non si
# ottiene senza nginx. Soluzione: cert FINTO temporaneo -> nginx su -> certbot ottiene
# il VERO -> reload. Poi il rinnovo è automatico (servizi certbot+nginx nel compose).
set -e

# ── CONFIG (cambia se usi un altro dominio/email) ─────────────────────────────
DOMAIN="bookinvip.com"
WWW="www.bookinvip.com"
EMAIL="info@bookinvip.com"     # avvisi di scadenza Let's Encrypt
STAGING=0                        # 1 = certificati di TEST (per provare senza consumare il
                                 #     rate-limit di LE). Metti 0 per il certificato VERO.
# ──────────────────────────────────────────────────────────────────────────────

COMPOSE="docker compose -f docker-compose.casavip.ssl.yml"
CONF_DIR="./certbot/conf"
WWW_DIR="./certbot/www"
LIVE="/etc/letsencrypt/live/$DOMAIN"

mkdir -p "$CONF_DIR" "$WWW_DIR"

# 1) Parametri TLS raccomandati (una volta sola)
if [ ! -e "$CONF_DIR/options-ssl-nginx.conf" ] || [ ! -e "$CONF_DIR/ssl-dhparams.pem" ]; then
  echo "### Scarico i parametri TLS raccomandati di certbot ..."
  curl -sSf https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf > "$CONF_DIR/options-ssl-nginx.conf"
  curl -sSf https://raw.githubusercontent.com/certbot/certbot/master/certbot/certbot/ssl-dhparams.pem > "$CONF_DIR/ssl-dhparams.pem"
fi

# 2) Certificato FINTO temporaneo: serve solo a far PARTIRE nginx (altrimenti
#    ssl_certificate punta a un file inesistente e nginx muore al boot).
echo "### Creo un certificato finto temporaneo per $DOMAIN ..."
$COMPOSE run --rm --entrypoint "\
  sh -c 'mkdir -p $LIVE && \
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout $LIVE/privkey.pem -out $LIVE/fullchain.pem -subj /CN=localhost'" certbot

# 3) Avvio nginx (e app) con il cert finto, così risponde sulla porta 80/443
echo "### Avvio app + nginx ..."
$COMPOSE up --force-recreate -d app nginx

# 4) Cancello il cert finto e chiedo quello VERO via sfida webroot
echo "### Rimuovo il certificato finto ..."
$COMPOSE run --rm --entrypoint "\
  sh -c 'rm -Rf /etc/letsencrypt/live/$DOMAIN && \
  rm -Rf /etc/letsencrypt/archive/$DOMAIN && \
  rm -Rf /etc/letsencrypt/renewal/$DOMAIN.conf'" certbot

STAGING_ARG=""
[ "$STAGING" != "0" ] && STAGING_ARG="--staging"

echo "### Richiedo il certificato Let's Encrypt per $DOMAIN, $WWW ..."
$COMPOSE run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot $STAGING_ARG \
    -d $DOMAIN -d $WWW \
    --email $EMAIL --agree-tos --no-eff-email --force-renewal" certbot

# 5) Ricarico nginx col certificato vero e avvio l'intero stack (certbot+backup)
echo "### Ricarico nginx e avvio lo stack completo ..."
$COMPOSE exec nginx nginx -s reload
$COMPOSE up -d

echo "### FATTO. Visita: https://$DOMAIN"
echo "### (Se STAGING=1, era un cert di TEST: rimetti STAGING=0 e rilancia per il vero.)"
