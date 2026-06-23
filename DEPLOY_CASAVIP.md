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

## 4. HTTPS / dominio — PRONTO, un comando (Let's Encrypt automatico)
Usa lo stack TLS già pronto: `docker-compose.casavip.ssl.yml` + `deploy/nginx.casavip.ssl.conf`
+ lo script di bootstrap che ottiene il certificato e risolve l'uovo-e-gallina da solo.

**Prerequisiti:** DNS di `bookinvip.com` **e** `www.bookinvip.com` (record A) → IP del VPS;
porte 80 e 443 aperte; `.env.casavip` già creato (passo 1).

```bash
# (se cambi dominio/email: modificali in cima a deploy/init-letsencrypt.sh
#  e i 3 'bookinvip.com' in deploy/nginx.casavip.ssl.conf)

chmod +x deploy/init-letsencrypt.sh
./deploy/init-letsencrypt.sh        # cert finto -> nginx su -> certbot ottiene il vero -> reload
```
Da qui in poi avvii/aggiorni così (rinnovo automatico: certbot ogni 12h, nginx reload ogni 6h):
```bash
docker compose -f docker-compose.casavip.ssl.yml up -d --build
```
> 💡 Per provare senza consumare il rate-limit di Let's Encrypt, metti `STAGING=1` in cima
> allo script (cert di test), poi rimetti `STAGING=0` e rilancia per quello vero.
> Verifica: `https://bookinvip.com` (lucchetto verde) e `https://bookinvip.com/api/health`.

*(Il vecchio compose `docker-compose.casavip.yml` resta valido per test SOLO-HTTP in locale.)*

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
