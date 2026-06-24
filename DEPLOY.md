> 🔄 Aggiornato 2026-06-24 · **BookinVIP** · suite **1740 test** (0 regressioni) · moduli `faseNN`→151 · infra VPS Aruba 89.46.65.6 ATTIVO · fonte di verità: **STATO_FINALE.md**

# CORE_AUTO — Guida al Deploy

Stack a **compartimenti stagni**: `nginx` (unico esposto) → `app` (gunicorn) →
`postgres`. Self-healing integrato (riavvio automatico + healthcheck).

## Prerequisiti
- Docker + Docker Compose v2 (`docker compose version`).
- Una macchina/host raggiungibile (per SSL serve anche un dominio).

## 1. Configurazione

```bash
cp .env.example .env
# genera segreti robusti (uno per riga):
python -c "import secrets; print(secrets.token_hex(32))"
```
Compila in `.env` almeno: `HMAC_SECRET`, `API_KEY`, `BEARER_TOKEN`,
`ADMIN_TOKEN`, `POSTGRES_PASSWORD`. **Non** lasciare i valori `cambiami_*`
(in `FLASK_ENV=production` l'app **non parte** se i segreti mancano — fail-fast).

> `.env` è git-ignored: i segreti reali non finiscono mai nel repo.

## 2. Avvio (un comando)

```bash
docker compose up -d            # build + avvio di nginx, app, postgres
docker compose ps              # stato + colonna health
docker compose logs -f app     # log applicazione
```
L'ordine è gestito da `depends_on: service_healthy`: l'app parte solo a Postgres
sano, nginx instrada solo ad app sana.

## 3. Verifica

```bash
curl -i http://localhost/api/v1/health      # 200 {"status":"ok"} via nginx
curl -i http://localhost/healthz            # 200 ok (healthcheck del proxy)
```
Validazione dello stack a livello config (senza Docker):
```bash
python -m unittest test_deploy_config
```
Validazione **live** del dialetto Postgres (con lo stack su):
```bash
# DATABASE_URL punta al Postgres dello stack
python -m unittest test_postgres_live
```

## 4. Operazioni

| Azione | Comando |
|--------|---------|
| Stop (dati salvi) | `docker compose down` |
| Stop + **cancella i dati** | `docker compose down -v` |
| Riavvio singolo servizio | `docker compose restart app` |
| Aggiornare l'immagine | `docker compose build app && docker compose up -d` |
| Backup Postgres | `docker exec core_auto_pg pg_dump -U core core_auto > backup.sql` |
| Backup DB SQLite (core) | `docker cp core_auto_app:/data/marketplace.db ./backup.db` |

I dati persistono nei volumi `core_auto_pgdata` (Postgres) e `core_auto_appdata`
(SQLite del core): sopravvivono a `down`, si cancellano solo con `down -v`.

## 5. Sicurezza (note)
- **Solo nginx** è esposto sull'host; `app` e `postgres` vivono sulla rete interna.
- Immagine app: multi-stage, **non-root** (uid 10001), slim, senza build-tools.
- Header di sicurezza impostati sia dall'app sia da nginx; body limitato a 1 MiB.
- Rate-limit di prima linea su nginx + rate-limit applicativo per-IP.

## 6. HTTPS / dominio (passo 5.1)
In produzione aggiungere in `deploy/nginx.conf` un server `listen 443 ssl` con
certificati Let's Encrypt e il redirect `80 → 443`, poi `HTTP_PORT=443` in `.env`.

## 7. Stato del datastore (nota importante)
Oggi il **core** gira su **SQLite** (volume `core_auto_appdata`); **Postgres è già
provvisto e pronto**. Outbox e idempotenza sono già Postgres-ready. Il *cutover*
del core a Postgres (`DB_BACKEND=postgres`) avverrà dopo il porting `1.3c`
(vedi `MASTERPLAN.md`), validandolo con `test_postgres_live` sullo stack vivo.

## Modulo Tavola VIP (prenotazioni + pagamenti Stripe)

Prodotto autonomo per prenotare un "tavolo" (alloggio/risorsa) con pagamento reale.

### Configurazione (`.env`)
```
STRIPE_API_KEY=sk_test_...           # chiave segreta Stripe (RUOTALA se esposta)
STRIPE_WEBHOOK_SECRET=whsec_...       # Dashboard Stripe > Developers > Webhooks
BOOKING_API_KEY=...                   # header X-Booking-Key per le route prenotazione
BOOKING_SUCCESS_URL=https://.../ok
BOOKING_CANCEL_URL=https://.../ko
```
Senza `STRIPE_API_KEY` il servizio usa uno stub di sviluppo (NON per produzione).

### Avvio (servizio standalone)
```bash
gunicorn -b 0.0.0.0:8001 'fase36_booking_api:crea_app_da_env()'
```
Lo schema (prenotazioni/pagamenti_split/escrow/voucher) viene creato al boot.

### Endpoint (`/api/v1`)
- `POST /reservations` (header `X-Booking-Key`) -> 201 + `payment_url` (link Stripe)
- `GET  /reservations/<id>` -> stato
- `POST /reservations/<id>/cancel` -> libera il tavolo
- `POST /payments/webhook` -> notifica Stripe (autenticata dalla FIRMA, non da X-Booking-Key)

### Webhook Stripe
Su Stripe Dashboard crea un endpoint webhook verso `https://<host>/api/v1/payments/webhook`
per l'evento `checkout.session.completed`, e copia il signing secret in `STRIPE_WEBHOOK_SECRET`.
> La firma del webhook e verificata: una notifica non firmata NON conferma nulla.

## Go-live Tavola VIP — stack dedicato (servizio standalone)

Stack isolato `nginx -> booking` (gunicorn), DB su SQLite in volume persistente.
Riusa la stessa immagine della fortezza (nessun Dockerfile nuovo).

```bash
# 1) configura i segreti (file .env, gitignored)
cp .env.example .env        # se non esiste gia'
#   compila almeno: STRIPE_API_KEY, STRIPE_WEBHOOK_SECRET, BOOKING_API_KEY,
#   BOOKING_SUCCESS_URL, BOOKING_CANCEL_URL, HTTP_PORT
nano .env

# 2) build + avvio (un comando)
docker compose -f docker-compose.tavolavip.yml up -d --build
docker compose -f docker-compose.tavolavip.yml ps      # colonna health

# 3) SMOKE TEST: raggiungibilita' + risposte API (prima del lancio vero)
BASE_URL=http://127.0.0.1 BOOKING_API_KEY=<la_tua_BOOKING_API_KEY> \
  bash deploy/smoke_tavolavip.sh

# 4) operazioni
docker compose -f docker-compose.tavolavip.yml logs -f booking
docker compose -f docker-compose.tavolavip.yml down      # stop
docker compose -f docker-compose.tavolavip.yml down -v   # stop + CANCELLA il DB
```

Webhook Stripe: su Dashboard crea l'endpoint verso `https://<host>/api/v1/payments/webhook`
(evento `checkout.session.completed`), copia il signing secret in `STRIPE_WEBHOOK_SECRET`
e riavvia (`up -d`). Se i segreti mancano in `.env`, il deploy si FERMA (fail-fast).

### HTTPS / SSL — go-live pubblico (BLOCCO 5.1)

Prerequisito: un **dominio** che punta all'IP del server (record A).

```bash
# 1) metti il TUO dominio in deploy/nginx.tavolavip.ssl.conf (sostituisci tavolavip.example)
sed -i 's/tavolavip.example/tavolavip.tuodominio.it/g' deploy/nginx.tavolavip.ssl.conf

# 2) ottieni i certificati Let's Encrypt (porta 80 libera durante l'emissione)
docker run --rm -p 80:80 -v /etc/letsencrypt:/etc/letsencrypt \
  certbot/certbot certonly --standalone -d tavolavip.tuodominio.it --agree-tos -m info@bookinvip.com -n

# 3) avvia lo stack HTTPS (al posto del compose base)
docker compose -f docker-compose.tavolavip.ssl.yml up -d --build

# 4) smoke su HTTPS
BASE_URL=https://tavolavip.tuodominio.it BOOKING_API_KEY=<la_tua> bash deploy/smoke_tavolavip.sh

# 5) rinnovo automatico (cron mensile)
#   docker run --rm -v /etc/letsencrypt:/etc/letsencrypt certbot/certbot renew \
#     && docker compose -f docker-compose.tavolavip.ssl.yml exec nginx nginx -s reload
```
HTTP (80) reindirizza a HTTPS (443); HSTS attivo. Aggiorna l'URL del webhook Stripe a
`https://tavolavip.tuodominio.it/api/v1/payments/webhook`.

### Backup automatico del DB (Tavola VIP)

Snapshot **consistente** (Online Backup API, cattura anche il WAL) + retention
**size-cap** (lo spazio totale non supera mai `BACKUP_MAX_BYTES` -> il disco non si
riempie). I backup sono gzippati nel volume persistente.

```bash
# manuale (dentro il container, scrive in /data/backup sul volume persistente)
docker compose -f docker-compose.tavolavip.yml exec -T booking \
  env BACKUP_DIR=/data/backup bash deploy/backup_tavolavip.sh

# CRON host (ogni 6 ore):
0 */6 * * * cd /percorso/repo && docker compose -f docker-compose.tavolavip.yml \
  exec -T booking env BACKUP_DIR=/data/backup bash deploy/backup_tavolavip.sh >> /var/log/tavolavip-backup.log 2>&1

# ripristino di un backup:
python -c "import fase38_backup as b; b.ripristina('/data/backup/tavolavip-XXENGINE.db.gz','/data/tavolavip.db')"
```

### Pannello Admin web (ponte di comando)

UI minimale e sicura (Basic auth + CSRF) per vedere prenotazioni, vista calendario e
APPROVARE i rimborsi senza terminale/curl. Servire SEMPRE dietro HTTPS.

```bash
# avvio (servizio dedicato, stessa immagine)
gunicorn -b 0.0.0.0:8002 'fase41_admin_panel:crea_app_admin_da_env()'
# poi apri  https://<host>/admin  e autenticati (ADMIN_PANEL_USER/ADMIN_PANEL_PASSWORD)
```
Senza `ADMIN_PANEL_USER`/`ADMIN_PANEL_PASSWORD` il pannello e' disabilitato (503).

### Observability (log JSON + metriche) e CI

- **Log JSON**: chiama `fase42_observability.configura_logging_json("INFO")` all'avvio
  (o nel gunicorn.conf) -> ogni riga di log diventa un oggetto JSON interrogabile.
- **Metriche Prometheus**: l'app booking espone `GET /api/v1/metrics`... in realta'
  `GET /metrics` (richieste + latenze). Esponilo SOLO alla rete interna dello scraper.
- **CI**: `.github/workflows/ci.yml` lancia l'intera suite di test (matrice Python
  3.9 e 3.11) ad ogni push e pull request -> gate di regressione automatico.
