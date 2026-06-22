# Casa VIP — Deploy sul VPS (guida pratica)

Stack: **nginx** (unico esposto) → **app** (server stdlib, zero dipendenze) → volume SQLite.
Self-healing: riavvio automatico + healthcheck.

## Prerequisiti
- Un VPS con **Docker + Docker Compose v2** (`docker compose version`).
- (Per HTTPS) un **dominio** che punta all'IP del VPS (record A).

## 1. Configura i segreti
```bash
cp .env.casavip.example .env.casavip
python -c "import secrets; print(secrets.token_hex(32))"   # incolla in CASAVIP_SEGRETO
nano .env.casavip                                          # imposta CASAVIP_SEGRETO, HOST_KEY
```

## 2. Avvio (un comando)
```bash
docker compose -f docker-compose.casavip.yml up -d --build
docker compose -f docker-compose.casavip.yml ps           # colonna health
docker compose -f docker-compose.casavip.yml logs -f app
```
Apri `http://IP_DEL_VPS/` → vetrina. `http://IP_DEL_VPS/host.html` → pannello host.

## 3. Verifica
```bash
curl -i http://localhost/api/health     # 200 {"status":"ok"} via nginx
curl -i http://localhost/healthz        # 200 ok (healthcheck proxy)
```

## 4. HTTPS / dominio (quando hai il dominio)
```bash
# 1) ottieni i certificati (porta 80 libera durante l'emissione)
docker run --rm -p 80:80 -v /etc/letsencrypt:/etc/letsencrypt \
  certbot/certbot certonly --standalone -d casa.tuodominio.it --agree-tos -m tu@email.it -n

# 2) in deploy/nginx.casavip.conf: scommenta i due blocchi HTTPS e metti il tuo dominio
# 3) in docker-compose.casavip.yml: scommenta '443:443' e il volume /etc/letsencrypt
docker compose -f docker-compose.casavip.yml up -d
```
Rinnovo automatico (cron mensile):
```bash
0 3 1 * * docker run --rm -v /etc/letsencrypt:/etc/letsencrypt certbot/certbot renew \
  && docker compose -f docker-compose.casavip.yml exec nginx nginx -s reload
```

## 5. Operazioni
| Azione | Comando |
|---|---|
| Stop (dati salvi) | `docker compose -f docker-compose.casavip.yml down` |
| Stop + cancella dati | `docker compose -f docker-compose.casavip.yml down -v` |
| Aggiorna immagine | `docker compose -f docker-compose.casavip.yml up -d --build` |
| Backup DB | `docker cp casavip_app:/data ./backup-data` |

## Note
- Casa VIP gira su **pura stdlib** → immagine minima, **non-root** (uid 10001), zero pip install.
- Solo nginx è esposto; l'app vive sulla rete interna.
- I dati persistono nel volume `casavip_data` (sopravvive a `down`, si cancella con `down -v`).
- Sicurezza OS (OSSEC/Wazuh/Fail2ban) si aggiunge sul VPS, non nell'immagine.
