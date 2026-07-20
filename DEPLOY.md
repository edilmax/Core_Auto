# 🚀 DEPLOY — come si mette online BookinVIP

> Documento ufficiale, aggiornato **2026-07-20**. Descrive la procedura **reale** usata in
> produzione, e **solo quella**: qui dentro non c'è alcun comando che non si debba eseguire.
> La versione precedente di questo file descriveva un impianto e un server **dismessi**, con
> una sequenza di aggiornamento che su questa macchina **fallisce**: è stata archiviata in
> `_archivio/` e non va più consultata. **Seguire solo questo file.**

## 1. Dove gira il prodotto

| | |
|---|---|
| **Server** | VPS Hostinger **`76.13.44.167`** (`srv1781683.hstgr.cloud`) |
| **Dominio** | `bookinvip.com` (HTTPS con Let's Encrypt, rinnovo automatico) |
| **Cartella** | `/var/www/bookinvip` (clone del repo `edilmax/Core_Auto`) |
| **Accesso** | `ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes root@76.13.44.167` |
| **Container** | `casavip_app` (l'applicazione) · `casavip_nginx` (il proxy) · `casavip_backup` |
| **Dati** | volume Docker `bookinvip_casavip_data`, montato su `/data` |
| **Segreti** | `/var/www/bookinvip/.env.casavip` — **mai** nel repository |

> ⚠️ Sul VPS c'è **Docker Compose v1.29.2**: il comando è `docker-compose` **col trattino**.
> I comandi in stile v2 (`docker compose`) **non funzionano** su questa macchina.

## 2. Prima di ogni deploy: la suite INTERA deve essere verde

```bash
# sul computer, dentro la cartella del progetto (Windows, Python 3.9)
python -m unittest discover -s . -p "test_*.py"
```

**Nessun deploy con anche un solo test rosso.** Poi si committa e si spinge su GitHub:

```bash
git add -A && git commit -m "descrizione del lavoro" && git push origin master
```

## 3. Deploy — procedura "rm-first" (obbligatoria)

Da eseguire sul VPS, **in questo ordine**:

```bash
cd /var/www/bookinvip && \
git pull && \
docker-compose -f docker-compose.casavip.yml build app && \
docker-compose -f docker-compose.casavip.yml stop app backup && \
docker-compose -f docker-compose.casavip.yml rm -f app backup && \
docker-compose -f docker-compose.casavip.yml up -d
```

**Perché "rm-first" e non `up -d` diretto:** con Compose v1, un `up -d` su container
esistenti dopo un `build` fallisce con `KeyError: ContainerConfig`. Fermare e **rimuovere**
i container prima di ricrearli è l'unica sequenza che funziona. Il volume dei dati **non**
viene toccato: `rm -f` rimuove i container, non i dati.

> Se la modifica riguarda **solo i documenti** (`.md`), basta `git pull`: niente rebuild.
>
> ⚠️ **Modifiche alla configurazione nginx**: `git pull` + `nginx -s reload` **non basta** e
> fallisce in silenzio (Docker monta quel file per inode, git lo sostituisce creandone uno
> nuovo e il container resta sul vecchio). Serve:
> `docker rm -f casavip_nginx && docker-compose -f docker-compose.casavip.yml up -d`
>
> ⚠️ **Mai `git reset --hard` sul VPS**: cancellerebbe eventuali file locali non tracciati.

## 4. Verifica dopo il deploy

```bash
# sul VPS: i container devono essere "healthy" e l'avvio pulito
docker ps --format '{{.Names}} {{.Status}}' | grep casavip
docker logs casavip_app 2>&1 | grep -E 'money_path_pronto|avvisi'
```

Atteso nel log d'avvio: **`money_path_pronto: True, avvisi: []`**.

```bash
# dal computer: il sito risponde
curl -s -o /dev/null -w "%{http_code}\n" https://bookinvip.com/
curl -s -o /dev/null -w "%{http_code}\n" https://bookinvip.com/api/health
```

Attesi **200** entrambi. Infine si controlla che i tre posti siano allineati:

```bash
git rev-parse --short HEAD          # computer
git rev-parse --short origin/master # GitHub
ssh ... 'cd /var/www/bookinvip && git rev-parse --short HEAD'   # VPS
```

I tre valori **devono coincidere**.

## 5. Variabili d'ambiente nuove

Se il lavoro introduce una variabile nuova che governa **denaro o percorsi di database**,
va scritta in `/var/www/bookinvip/.env.casavip` **PRIMA** del deploy: altrimenti il
container parte e va in errore (già successo, ~3 minuti di sito giù).

## 6. Backup e ripristino

I backup girano da soli (container `casavip_backup`, ogni 6 ore, 14 copie per database,
tutti i `*.db` del volume). In più esiste una copia **cifrata fuori dal server**:

```bash
BV_PASS='la-passphrase-segreta' bash deploy/pull_offsite.sh      # crea la copia dal PC
BV_PASS='la-passphrase-segreta' bash deploy/restore_offsite.sh <file.enc> ~/RESTORE
```

Il restore verifica ogni database (`PRAGMA integrity_check`) **e la catena hash del libro
giornale**: se dice "GIORNALE MANOMESSO" quel pacchetto non va usato.

**Ricostruzione da zero** su un server nuovo: installare `docker.io` e `docker-compose`,
clonare il repo in `/var/www/bookinvip`, ricreare `.env.casavip` (le chiavi Stripe si
riprendono da dashboard.stripe.com), creare il volume e copiarci dentro i `.db` restaurati,
poi `build` + `up -d`. Obiettivo: **meno di un'ora**, DNS e certificato esclusi.

## 7. Operazioni comuni

| Azione | Comando (sul VPS) |
|---|---|
| Stato dei container | `docker ps` |
| Log applicazione | `docker logs -f casavip_app` |
| Riavvio pulito dell'app | `docker-compose -f docker-compose.casavip.yml restart app` |
| Girare i test dentro l'immagine di produzione | `docker run --rm -v /var/www/bookinvip:/app -w /app casavip-app python -m unittest <modulo>` |
| Vedere i backup | `ls -t $(docker volume inspect --format '{{.Mountpoint}}' bookinvip_casavip_data)/backup \| head` |

---

## 8. ⛔ PULIZIA DEL SERVER — la regola che ci è costata cara

**Mai eseguire `git clean` (né cancellazioni a mano) sul VPS senza aver prima controllato i
bind-mount del compose.** Alcune cartelle **non tracciate da git sono mount vivi**: cancellarle
non fa cadere il sito subito, lo fa morire **settimane dopo**.

**È già successo (2026-07-20):** una pulizia dei file orfani ha rimosso `certbot/`, che è
montata per la sfida di rinnovo del certificato. Il sito continuava a rispondere — il
certificato era ancora valido — ma il rinnovo era **rotto in silenzio**: HTTPS morto alla
scadenza, ~60 giorni dopo, senza alcun preavviso.

**Peggio:** ricreare la cartella **non basta**. Docker tiene il mount agganciato alla
directory **cancellata** (per inode), quindi il container continua a non vedere i file nuovi.
Serve **ricreare il container**.

Procedura corretta:

```bash
# 1. quali cartelle sono mount vivi? (da NON toccare mai)
cd /var/www/bookinvip
grep -E '^\s+- \./' docker-compose.casavip.yml | sed 's/^\s*- //' | cut -d: -f1 | sort -u

# 2. solo dopo, e con una copia di sicurezza:
cp -r <file-da-rimuovere> /root/backup-orfani-$(date +%Y%m%d)/
git clean -fd -e certbot          # -e ESCLUDE i mount vivi

# 3. se per errore un mount è stato toccato: ricreare il container che lo usa
docker rm -f casavip_nginx && docker-compose -f docker-compose.casavip.yml up -d

# 4. e VERIFICARE che il rinnovo funzioni davvero
certbot renew --dry-run           # atteso: "all simulated renewals succeeded"
echo prova > certbot/www/_t && docker exec casavip_nginx cat /var/www/certbot/_t && rm certbot/www/_t
```

> La verifica del punto 4 è la sola che conta: se il container **vede** il file appena scritto,
> il mount è agganciato bene e Let's Encrypt riuscirà a rinnovare.

---

### Nota storica

La procedura dell'impianto **precedente** (server e tecnologie ora dismessi) è conservata nei
documenti in `_archivio/`: **non si applica al prodotto attuale** e i suoi comandi **non vanno
eseguiti** su questa macchina.
