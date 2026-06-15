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
