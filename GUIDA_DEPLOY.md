> 🔄 Aggiornato 2026-06-29 · **BookinVIP** · suite **1835 test** (0 regressioni) · moduli `faseNN`→158 · infra VPS Aruba 89.46.65.6 ATTIVO · fonte di verità: **STATO_FINALE.md**

# BookinVIP — Guida primo deploy (passo-passo)

Runbook copia-incolla: da un VPS vuoto al sito online su **https://bookinvip.com**.
Tutto gira su Docker; l'app è pura stdlib (niente da installare nell'immagine).

> Legenda: i comandi vanno dati **sul VPS** (via SSH), come utente con sudo.
> Dove vedi `bookinvip.com`, è già il tuo dominio. Sostituisci solo le email/chiavi.

---

## PASSO 0 — Cosa ti serve davanti
- Un **VPS Ubuntu 22.04/24.04** (1–2 GB RAM) con il suo **IP pubblico**.
- Accesso **SSH** al VPS.
- Il dominio **bookinvip.com** (per puntare il DNS).
- (Per dopo) chiavi **Stripe** e dati **SMTP** — il sito parte anche senza, le aggiungi poi.

---

## PASSO 1 — DNS: punta il dominio al VPS
Nel pannello del tuo registrar (dove hai comprato bookinvip.com), crea/aggiorna:
- Record **A**: `bookinvip.com` → `IP_DEL_VPS`
- Record **A**: `www.bookinvip.com` → `IP_DEL_VPS` (opzionale)

La propagazione può richiedere da pochi minuti a qualche ora. Verifica:
```bash
ping bookinvip.com      # deve rispondere l'IP del VPS
```

---

## PASSO 2 — Entra nel VPS e aggiorna
```bash
ssh root@IP_DEL_VPS          # o il tuo utente
apt update && apt -y upgrade
```

## PASSO 3 — Installa Docker + Compose
```bash
curl -fsSL https://get.docker.com | sh
docker --version
docker compose version       # deve stampare v2.x
```

## PASSO 4 — Firewall (apri solo 22/80/443)
```bash
apt -y install ufw
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status
```

## PASSO 5 — Scarica il codice
```bash
apt -y install git
cd /opt
git clone https://github.com/edilmax/Core_Auto.git bookinvip
cd /opt/bookinvip
```

## PASSO 6 — Genera i segreti (.env)
```bash
sh deploy/genera_segreti.sh         # crea .env.casavip con segreti sicuri (chmod 600)
nano .env.casavip                   # aggiungi BASE_URL e, se le hai, le chiavi
```
In `.env.casavip` assicurati di avere almeno:
```
CASAVIP_SEGRETO=...(già generato)...
HOST_KEY=...(già generato)...
ADMIN_KEY=...(metti un valore tuo)...
BASE_URL=https://bookinvip.com
# Stripe/SMTP: lasciali vuoti per ora, li metti al PASSO 10/11
```
Salva con `Ctrl+O`, `Invio`, esci con `Ctrl+X`.

## PASSO 7 — Primo avvio (HTTP) e verifica
```bash
docker compose -f docker-compose.casavip.yml up -d --build
docker compose -f docker-compose.casavip.yml ps        # colonna health: healthy
curl -i http://localhost/api/health                    # 200 {"status":"ok"}
```
Apri nel browser `http://bookinvip.com/` → deve comparire la **vetrina BookinVIP**.
(`/host.html` = pannello host, `/admin.html` = rimborsi.)

> Se non si apre: controlla i log → `docker compose -f docker-compose.casavip.yml logs -f`

---

## PASSO 8 — HTTPS con Let's Encrypt (gratis)
Fermiamo lo stack per liberare la porta 80, prendiamo i certificati, poi riaccendiamo.
```bash
docker compose -f docker-compose.casavip.yml down

docker run --rm -p 80:80 -v /etc/letsencrypt:/etc/letsencrypt \
  certbot/certbot certonly --standalone \
  -d bookinvip.com -d www.bookinvip.com \
  --agree-tos -m TUA_EMAIL@esempio.com -n
```
Devono comparire i file in `/etc/letsencrypt/live/bookinvip.com/`.

## PASSO 9 — Attiva HTTPS (nginx + compose) e riavvia
```bash
nano deploy/nginx.casavip.conf
```
→ **scommenta i due blocchi HTTPS** in fondo (sono già con `bookinvip.com`). Salva ed esci.
```bash
nano docker-compose.casavip.yml
```
→ nel servizio `nginx`: **scommenta** `- "443:443"` e il volume
   `- /etc/letsencrypt:/etc/letsencrypt:ro`. Salva ed esci.
```bash
docker compose -f docker-compose.casavip.yml up -d --build
curl -i https://bookinvip.com/api/health               # 200 via HTTPS
```
Apri `https://bookinvip.com/` → lucchetto verde. 🔒

---

## PASSO 10 — Stripe (per incassare)
1. Su **dashboard.stripe.com** crea il webhook:
   - URL: `https://bookinvip.com/api/payments/webhook`
   - Evento: `checkout.session.completed`
   - Copia il **Signing secret** (`whsec_...`).
2. Copia la **Secret key** (`sk_live_...`).
3. Mettile nel `.env`:
```bash
nano .env.casavip
```
```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_SUCCESS_URL=https://bookinvip.com/grazie
STRIPE_CANCEL_URL=https://bookinvip.com/annullato
```
```bash
docker compose -f docker-compose.casavip.yml up -d      # riavvia con le chiavi
```
Da ora ogni prenotazione genera un **link di pagamento reale** e il webhook conferma.

## PASSO 11 — Email (voucher all'ospite)
Dal tuo provider email (Zoho/Google Workspace) prendi i dati SMTP e mettili nel `.env`:
```
SMTP_HOST=smtp.tuoprovider.com
SMTP_PORT=587
SMTP_USER=info@bookinvip.com
SMTP_PASSWORD=...
EMAIL_MITTENTE=info@bookinvip.com
```
```bash
docker compose -f docker-compose.casavip.yml up -d
```

---

## PASSO 12 — Prova reale (carta di test Stripe)
1. Apri `https://bookinvip.com/host.html`, metti la tua `HOST_KEY`, pubblica un alloggio
   di prova e apri un periodo di disponibilità.
2. Apri la vetrina, prenota, paga con la **carta di test Stripe** `4242 4242 4242 4242`
   (data futura, CVC qualsiasi).
3. Verifica: arriva il voucher via email, e in `/admin.html` vedi la prenotazione.
4. Quando tutto va, passa Stripe in **modalità live** e sei online davvero.

---

## OPERAZIONI QUOTIDIANE
| Azione | Comando |
|---|---|
| Vedere i log | `docker compose -f docker-compose.casavip.yml logs -f` |
| Stato/health | `docker compose -f docker-compose.casavip.yml ps` |
| Aggiornare il codice | `git pull && docker compose -f docker-compose.casavip.yml up -d --build` |
| Stop (dati salvi) | `docker compose -f docker-compose.casavip.yml down` |
| Backup manuale dati | `docker cp casavip_app:/data ./backup-$(date +%F)` |

Il **backup automatico** gira già (sidecar nel compose, ogni 6h, in `/data/backup`).
Rinnovo certificati (cron, una volta al mese):
```bash
0 3 1 * * docker run --rm -v /etc/letsencrypt:/etc/letsencrypt certbot/certbot renew \
  && docker compose -f /opt/bookinvip/docker-compose.casavip.yml exec nginx nginx -s reload
```

---

## PROBLEMI COMUNI
- **Il sito non si apre**: `docker compose ... ps` (health?) + `... logs -f`. Spesso è il
  DNS non ancora propagato (PASSO 1) o la porta 80 occupata.
- **certbot fallisce**: la porta 80 deve essere libera (fai prima `... down`) e il DNS
  deve già puntare al VPS.
- **`unhealthy`**: controlla `CASAVIP_SEGRETO` nel `.env` (deve essere >= 32 hex).
- **Pagamenti non partono**: senza `STRIPE_SECRET_KEY` la prenotazione conferma ma non
  incassa (è il comportamento gated; metti la chiave al PASSO 10).

Fatto questo, **BookinVIP è online**. 🥭
