# ✅ RISOLTO — il sito è ONLINE con HTTPS (aggiornato 2026-07-10)

> `https://bookinvip.com` e `https://www.bookinvip.com` funzionano con il **lucchetto verde** 🔒.
> La lista d'attesa registra le email anche in HTTPS. Il certificato si **rinnova da solo**.

## 🎯 QUAL ERA IL VERO PROBLEMA (dopo giorni di caccia)
Il codice, il server e i dati erano SEMPRE stati a posto. Il vero problema era **uno solo**:
- Il sito girava **solo in HTTP (porta 80)**; la **porta 443 (HTTPS) era spenta** → i browser, che oggi
  pretendono l'HTTPS, non si connettevano e mostravano "errore" (e il vecchio service worker in cache
  faceva apparire "offline").
- **NON era**: né il codice, né la cache, né "Aruba vs Hostinger". I vecchi documenti che parlavano di
  **Aruba 89.46.65.6 erano SBAGLIATI**: quello è un server-fantasma con un Flask morto. Il dominio punta
  al **VPS Hostinger `76.13.44.167`** (`srv1781683.hstgr.cloud`), dove gira davvero l'app.

Perché l'HTTPS non era mai partito: (1) sul VPS c'è solo `docker-compose` **v1.29.2**, ma il file SSL e
lo script `init-letsencrypt.sh` usano i comandi della **v2** (`docker compose`) → davano errore; (2) il
certificato Let's Encrypt esisteva già in `/etc/letsencrypt` ma il file SSL lo cercava in `certbot/conf`.

## 🔧 COSA È STATO FATTO (2026-07-10, direttamente sul VPS)
1. In `docker-compose.casavip.yml`, servizio **nginx**, ora attivi (prima commentati):
   - `- "443:443"`
   - conf: `./deploy/nginx.casavip.ssl.conf:/etc/nginx/conf.d/default.conf:ro`
   - `- /etc/letsencrypt:/etc/letsencrypt:ro`   (il certificato vero)
   - `- ./certbot/www:/var/www/certbot:ro`      (per la sfida di rinnovo)
   - Backup del file originale: `docker-compose.casavip.yml.bak.*` nella stessa cartella.
2. Rinnovo automatico corretto per funzionare con nginx-in-Docker: in
   `/etc/letsencrypt/renewal/bookinvip.com.conf` cambiato `authenticator = nginx` → **`webroot`**
   (webroot = `/var/www/bookinvip/certbot/www`) + `renew_hook = docker exec casavip_nginx nginx -s reload`.
   Collaudato con `certbot renew --dry-run` → **success**. `certbot.timer` è enabled+active.

## ▶️ COME AGGIORNARE IL SITO D'ORA IN POI (procedura SICURA)
Dalla cartella del VPS `/var/www/bookinvip`:
```bash
git pull                                   # NON usare 'git reset --hard': cancellerebbe la config HTTPS!
docker rm -f casavip_nginx                 # evita il bug KeyError:ContainerConfig di compose v1.29.2
docker-compose -f docker-compose.casavip.yml up -d
```
> ⚠️ La modifica che accende l'HTTPS è **solo nel working tree del VPS**, non ancora su GitHub.
> Un `git reset --hard origin/master` la CANCELLA (→ addio 443). Per renderla permanente: fare commit +
> push su GitHub (`edilmax/Core_Auto`) del `docker-compose.casavip.yml` modificato, poi allineare il VPS.
> (Meglio ancora, a lungo termine: installare `docker compose` v2 e usare `docker-compose.casavip.ssl.yml`.)

## 📌 CONTROLLI RAPIDI (dal proprio PC)
```bash
curl -sS -o /dev/null -w "HTTP %{http_code} cert=%{ssl_verify_result}\n" https://bookinvip.com/   # atteso: HTTP 200 cert=0
curl -sS -X POST https://bookinvip.com/api/domanda -H 'Content-Type: application/json' -d '{"email":"a@b.com","citta":"roma"}'  # atteso: {"ok": true,...}
```

## 🧹 COSE MINORI (non urgenti)
- Container `casavip_backup` risulta **unhealthy**: è solo estetico (usa l'immagine app ma non avvia il
  server, quindi l'healthcheck fallisce sempre). Il backup gira lo stesso. Si può ignorare o disabilitare
  l'healthcheck del solo container backup.
- Server **fantasma Aruba `89.46.65.6`** (Flask/Werkzeug morto): non c'entra col sito. Se lo si paga, si
  può dismettere; se non lo si controlla, ignorarlo.

## 🔑 ACCESSO
- VPS: `ssh root@76.13.44.167` (Hostinger, Ubuntu 24.04). La chiave pubblica `edilmax` (id_ed25519) è
  installata in `/root/.ssh/authorized_keys`. Fallback sempre disponibile: **hPanel Hostinger → VPS →
  Terminale del browser** (root, senza password).
- Fonte di verità funzionalità: `STATO_FINALE.md`. Cose da fare prodotto: `COSE_DA_FARE.md`.
