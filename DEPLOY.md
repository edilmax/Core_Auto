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

> ⛔ **SI USA SOLO `docker compose` (v2, senza trattino): versione `2.29.7`, plugin in
> `/usr/local/lib/docker/cli-plugins/`.** La vecchia v1 (`1.29.2`) **non esiste più su questa
> macchina**: è stata **sradicata il 2026-07-30**.
>
> **PERCHÉ era pericolosa.** Moriva con `KeyError: 'ContainerConfig'` **dopo** aver già rinominato
> e fermato `casavip_nginx`: lasciava il **sito irraggiungibile** e un container-residuo col nome
> sporco (`<hash>_casavip_nginx`) che al deploy successivo sarebbe diventato un duplicato.
> **Ci è costata ~1 minuto di sito giù il 2026-07-30**, seguendo questa stessa pagina quando
> ancora prescriveva la v1.
>
> **COME è stata sradicata (tre serrature, tutte verificate sul campo):**
> 1. **pacchetto rimosso** — `apt purge docker-compose`. La simulazione, fatta prima, mostrava un
>    solo pacchetto in uscita: `docker.io` e `containerd` **non** sono stati toccati, e i container
>    non si sono nemmeno accorti (identificativi e istante di avvio identici prima e dopo).
>    Nessun cron, nessuna unità systemd e nessuno script della cartella viva la chiamava: verificato
>    prima di rimuoverla, perché è così che un guasto diventa silenzioso.
> 2. **apt non può più rimetterla** — `/etc/apt/preferences.d/99-blocca-compose-v1` la fissa a
>    priorità `-1`: `apt-cache policy docker-compose` risponde `Candidate: (none)`. Nota utile: su
>    questo Ubuntu il nome `docker-compose` è ormai **fornito dal pacchetto `docker-compose-v2`**
>    (`Provides: docker-compose`), quindi anche chi digitasse `apt install docker-compose` in buona
>    fede otterrebbe una **v2 sana**, non il guasto.
> 3. **un segnaposto che spiega** — `/usr/local/bin/docker-compose` non è un programma: stampa
>    perché quel comando non esiste più, indica la v2 e **esce con codice 1**. Serve contro
>    l'errore umano più probabile: leggere «command not found» e pensare *«manca, lo reinstallo»*.
>    ⚠️ Il segnaposto **non** blocca apt (quello lo fa il pin del punto 2) e **non** è visibile ai
>    cron, che usano un `PATH` senza `/usr/local/bin`: è un cartello, non una serratura.
>
> **Se un domani serve rimuovere il blocco** (serve una ragione vera, e va scritta qui):
> `rm /etc/apt/preferences.d/99-blocca-compose-v1`
>
> Nota storica: la v1 era l'unica presente ai primi deploy, da cui la vecchia istruzione. Il
> `rm-first` qui sotto era il rimedio a un *altro* sintomo della stessa v1; con la v2 non serve più,
> ma **resta innocuo** e lo si tiene perché non tocca il volume dei dati.
> Ricreare nginx (immagine nuova, configurazione nuova, un montaggio toccato) si fa **solo** con
> `sh deploy/protocollo_d17.sh nginx` (§3, «Solo nginx»): punto di ritorno, paracadute e traccia dello
> scambio, come per l'app. Se il contenitore `casavip_nginx` non esiste più, o è fermo o in riavvio
> continuo, la fase si ferma (non c'è una configurazione viva da tenere per il ritorno) e l'emergenza è `docker compose -f docker-compose.casavip.yml up -d --no-deps nginx`
> (`--no-deps` perché nginx dipende dall'app: senza, compose potrebbe ricreare anche lei):
> la casella «il deploy passa sempre dal protocollo» resta rossa finché la fase nginx non lo ricrea, ed è giusto.

## 2. Prima di ogni deploy: la suite INTERA deve essere verde

```bash
# sul computer, dentro la cartella del progetto (Windows, Python 3.9)
python -m unittest discover -s . -p "test_*.py"
```

**Nessun deploy con anche un solo test rosso.** Poi si committa e si spinge su GitHub.

> ### ⛔ SU `master` NON SI SPINGE PIÙ — corretto il 2026-08-18
> Questa riga diceva `git push origin master`, e **quel comando è bloccato dal cancello**
> (regola di protezione del ramo su GitHub, attiva dal 2026-08-16). Chi seguiva questa
> pagina alla lettera sbatteva contro un muro senza capire perché: è **lo stesso difetto**
> che la regola ferrea 3 cita come proprio esempio — *«`DEPLOY.md` prescriveva un comando
> rotto»*, costato un minuto di sito irraggiungibile. Trovato mentre si controllava se i
> documenti fossero rimasti indietro rispetto al lavoro fatto.

```bash
# 1) un RAMO, mai master
git checkout -b nome-del-lavoro origin/master
git add <i file dichiarati> && git commit -m "descrizione del lavoro"
git push -u origin nome-del-lavoro
```

**2) poi la richiesta di unione**, e si aspetta che il job **`gate`** sia verde prima di
unire. ⛔ `gh` **non è installato** su questa macchina: si usa l'API di GitHub con
`Invoke-RestMethod`, prendendo le credenziali da `git credential fill` **senza stamparle**
(D6). ⛔ E dopo l'unione si **verifica con una SECONDA chiamata** che dica
`merged=True`: è già capitato **tre volte** che una richiesta risultasse solo *aperta*
mentre la si credeva unita.

**3) infine si allinea il computer**: `git checkout master && git pull --ff-only`.

## 3. Deploy — procedura "rm-first" (obbligatoria)

### ⛔ [1b] PRIMA DI TUTTO: AGGANCIARE IL PARACADUTE ALL'IMMAGINE CHE GIRA DAVVERO

**Questo è il passo che è mancato quattro volte in quattro giorni** (2026-08-05, -07, -08 e
-08 sera). `CLAUDE.md` lo prescriveva da giorni come «D17 punto [1b]» — ma **il punto [1b]
in questo file non esisteva**, e chi deploya segue questo file. Scritto il 2026-08-10, dopo
aver cercato invano `prec`, `docker tag` e `paracadute` in tutta la procedura.

`casavip-app:prec` è l'immagine a cui si torna se il deploy va male. Se punta a qualcosa di
diverso da ciò che sta girando **adesso**, saltare col paracadute ti riporta a uno stato che
non è l'ultimo buono: **è peggio di non avere paracadute**, perché ci si butta convinti.

```bash
cd /var/www/bookinvip
VIVA=$(docker inspect casavip_app --format '{{.Image}}')
echo "immagine viva: $VIVA"
docker tag "$VIVA" casavip-app:prec
# e SI FERMA se non coincide: un paracadute che "sembra" agganciato non vale niente
test "$(docker inspect casavip-app:prec --format '{{.Id}}')" = "$VIVA" \
  || { echo "PARACADUTE NON AGGANCIATO -> NON PROCEDERE"; exit 1; }
echo "$(git rev-parse HEAD)" > "PRE_DEPLOY_$(date +%Y%m%d_%H%M%S).commit"
```

**Come si torna indietro** (se la verifica del §4 va male):
```bash
docker tag casavip-app:prec casavip-app:latest && \
docker compose -f docker-compose.casavip.yml up -d --force-recreate app
```

⚠️ **`:prec` va agganciata PRIMA del `build`**, non dopo: dopo il build l'etichetta `:latest`
punta già alla nuova, e si finirebbe per agganciare il paracadute alla stessa immagine che si
sta installando — cioè a niente.

### Poi lo scambio

Da eseguire sul VPS, **in questo ordine**:

```bash
cd /var/www/bookinvip && \
git pull --ff-only && \
docker compose -f docker-compose.casavip.yml build app && \
docker compose -f docker-compose.casavip.yml stop app backup && \
docker compose -f docker-compose.casavip.yml rm -f app backup && \
docker compose -f docker-compose.casavip.yml up -d app backup
```

⛔ **`up -d app backup`, non `up -d` da solo** (26/11/2026): senza nomi, compose ricrea anche nginx se
nello stesso invio è cambiata la sua definizione, senza `nginx -t` e senza il suo paracadute. nginx si
cambia solo con la fase «Solo nginx» qui sotto.

**Perché "rm-first":** con Compose v1 un `up -d` su container esistenti dopo un `build`
falliva con `KeyError: ContainerConfig`, e fermare+rimuovere prima di ricreare era l'unica
sequenza che funzionasse. Con la v2 non è più necessario, e **si tiene perché è provato**:
il volume dei dati non viene toccato — `rm -f` rimuove i container, non i dati.
⛔ **CORREZIONE 2026-08-20: qui c'era scritto «resta innocuo». Non è innocuo.** Fra lo `stop`
e l'applicazione di nuovo in piedi il sito **non c'è**, e quella finestra è più lunga di
quanto serva: sono due passi (ferma, rimuovi) prima di ricominciare. Misurato il 19/08:
`casavip_app` è ripartito alle `21:44:47Z`, e la sentinella esterna alle `21:45:43Z` è morta
con `curl: (28) Connection timed out after 20001 ms`. Il rosso era **vero**.
⛔ Usare **`docker compose`** (v2) in ogni riga: la v1 col trattino butta giù nginx (vedi §1).

### ⏱️ COSA VEDE UN UTENTE DURANTE LO SCAMBIO (e cosa vedeva prima)

**Prima:** una pagina bianca **fino a un minuto**. Non per colpa dell'applicazione che
riparte — quello dura pochi secondi — ma perché `location /` non dichiarava
`proxy_connect_timeout` e il valore di serie di nginx è **60 secondi**: nginx teneva
l'indirizzo del contenitore sparito e restava lì ad aspettare. Era anche il motivo per cui la
sentinella vedeva un *timeout* invece di un errore.

**Ora** (2026-08-20, `deploy/nginx.casavip.ssl.conf`): l'attesa di connessione è **3 secondi**
e c'è `@manutenzione`, che risponde **503 + `Retry-After: 20`** con una pagina che dice
«torniamo subito». La finestra **c'è ancora**, ma smette di essere un'attesa muta.
⚠️ **Non è un deploy senza interruzione**, e non va raccontato come tale: per quello servono
due contenitori vivi insieme e nginx che passa dall'uno all'altro. È un lavoro a sé.
⛔ E la sentinella **deve continuare** ad andare rossa durante il deploy: il sito è davvero
indisponibile, e una pagina di cortesia che rispondesse `200` spegnerebbe l'unico allarme che
guarda da fuori (regola ferrea 10).
⛔ `proxy_intercept_errors` resta **spento e scritto**: se si accendesse, nginx sostituirebbe
anche i `503` che manda l'**applicazione** — cioè il fail-safe «gateway giù = non si conferma
niente». Un rimedio che spegne una difesa non è un rimedio. Lo sorveglia
`TestIlDeployNONLASCIAILSITOAPPESO` in `test_deploy_casavip.py`.

> Se la modifica riguarda **solo i documenti** (`.md`), basta `git pull`: niente rebuild.
>
> ⚠️ **Modifiche alla configurazione nginx**: `git pull` + `nginx -s reload` **non basta** e
> fallisce in silenzio (Docker monta quel file per inode, git lo sostituisce creandone uno
> nuovo e il container resta sul vecchio). Serve ricreare nginx, con la fase «Solo nginx» qui sotto.
>
> ⚠️ **Mai `git reset --hard` sul VPS**: cancellerebbe eventuali file locali non tracciati.

### Solo nginx: `sh deploy/protocollo_d17.sh nginx`

Il 24/11/2026 nginx è stato aggiornato (1.31.8 → 1.31.10) da uno script a parte,
`/root/aggiorna_nginx_20261124.sh`, che non lasciava né il punto di ritorno né la traccia dello
scambio: per `collaudi/esame_deploy.py` era un contenitore ricreato a mano, e la casella del Blocco 8
è diventata rossa. Dal 26/11 nginx si cambia **solo** con la sua fase del protocollo, poi `dopo`:

```bash
cd /var/www/bookinvip
sh deploy/protocollo_d17.sh nginx     # [Na]-[Ni]: si ferma da sola al primo controllo che non regge
sh deploy/protocollo_d17.sh dopo      # le sonde e il giudice, come dopo l'app; poi la ZAP dal computer
```

Cosa fa, in quest'ordine. **[Na]** Fissa il commit di origin/master (un `git fetch` a metà non lo
cambia) e si rifiuta se: il codice nuovo cambia file diversi dal compose e da quelli che sul server non
girano (i `.md` e le `test_*.py` della radice, `collaudi/`, `.github/`; un file spostato conta col nome
vecchio e col nuovo) — l'immagine dell'app (`main_casavip.py`, `fase*.py`,
`deploy/`, `Dockerfile.casavip`) o un file che nginx monta vanno prima con `prima` + `scambio` + `dopo`,
poi questa fase (per questo anche un cambio di `deploy/nginx.casavip.ssl.conf` passa prima dallo
scambio dell'app); il compose nuovo cambia qualcosa **fuori dal blocco di nginx** (app, backup, reti,
volumi: confronto riga per riga, e due letture vuote sono «misura non valida», non «uguali»); oppure il
disco non potrebbe andare avanti veloce dopo lo scambio (commit del disco non antenato, file del progetto
modificati sul server, un file nuovo che esiste già). **[Nb]** Scrive e rilegge `/root/PRE_DEPLOY_*.commit`.
**[Nc]** Si ferma se nginx non è in esecuzione (fermo o in riavvio: emergenza in §1); aggancia
`casavip-nginx:prec` e `casavip-nginx:prec-<ora>` all'immagine che nginx usa adesso, copia la
configurazione che nginx sta usando **dentro** il contenitore e prepara il ritorno
(`/root/nginx_prec_<ora>.yml` e `.conf`, un nome nuovo a ogni giro, con l'etichetta `:prec-<ora>` del
giro: un giro dopo non lo cambia; provato con `config -q`).
**[Nd]** Prova la definizione nuova con `nginx -t` in un contenitore usa e getta, leggendola da una copia
del compose di origin/master (`/root/nginx_nuovo_<ora>.yml`). **[Ne]** Si rifiuta ai minuti 9, 0 e 1 di
ogni decina, guardati subito prima dello scambio (il guardiano gira ogni 10 minuti e nginx giù in quel
secondo è un falso allarme). **[Nf]** Solo allora apre la traccia `/root/deploy_scambio_*.log`.
**[Ng]** Ricrea **solo** nginx col compose nuovo (`up -d --no-deps --force-recreate nginx`: app e backup
non si toccano) e aspetta `/api/health` 200 su HTTPS per fino a 30 tentativi, uno al secondo e ognuno al
massimo 5 secondi (al peggio circa tre minuti: **non interromperla**). Se la ricreazione fallisce o la
risposta non arriva, **torna indietro da sola**: la traccia dice `USCITA` diversa da 0, senza «SCAMBIO
FATTO», e con «RITORNO RIUSCITO» se dopo il ritorno il sito risponde. **[Nh]** Solo dopo uno scambio
riuscito porta il disco al commit fissato in [Na] (`git merge --ff-only`); se proprio lì fallisse, lo dice
e stampa come allineare il disco o tornare indietro.

⛔ **Si lancia staccata dalla sessione ssh**, e poi si legge il file: se ssh cade a metà, la shell muore
senza scrivere `USCITA` e senza ritorno. Per esempio:

```bash
cd /var/www/bookinvip
setsid nohup sh deploy/protocollo_d17.sh nginx > /root/fase_nginx_$(date -u +%Y%m%d_%H%M%S).txt 2>&1 < /dev/null &
```

⛔ **Il disco resta al codice di prima finché lo scambio non è riuscito**, apposta: il ritorno usa il
compose del disco più l'immagine e la configurazione tenute in [Nc], e nessuno scambio successivo può
rimettere su la definizione appena respinta. Torna **tutto** com'era quando il compose del disco è quello
da cui il nginx vivo è nato (il caso normale: cambia l'impronta di nginx); se il disco è già più avanti
(codice preso prima da uno `scambio`), il ritorno rimette immagine e configurazione ma non le altre righe
nuove di nginx nel compose.

⚠️ **Dopo un ritorno la casella del deploy resta rossa** anche dopo un giro riuscito: la traccia di quel
giro ha `USCITA` diversa da 0, e l'esame non sa ancora leggere «RITORNO RIUSCITO» (RIPRENDI_QUI.md, n8).

⛔ **Non usa il gettone di `prima`, apposta**: `prima` riaggancia il paracadute dell'**app** alla viva,
e dopo un cambio del solo nginx il ritorno dell'app non esisterebbe più. Paracadute e punto di ritorno
di nginx li prende la fase stessa, nello stesso giro dello scambio.

**Come si torna indietro a mano** dopo uno scambio riuscito (immagine e configurazione di prima, quelle
tenute in `[Nc]`; il nome esatto lo stampa la fase in `[Ni]`). Il compose del disco a quel punto è già
quello nuovo: si torna all'immagine e alla configurazione, non alle altre righe di nginx nel compose.
```bash
cd /var/www/bookinvip
docker compose -f docker-compose.casavip.yml -f /root/nginx_prec_<ora>.yml up -d --no-deps --force-recreate nginx
```

Ritirati il 26/11/2026 alle 12:07 UTC: `/root/aggiorna_nginx.sh` (5/11), `/root/aggiorna_nginx_20261124.sh`
(24/11) e il compose che quest'ultimo teneva per il suo ritorno (`/root/compose_prima_di_nginx_13110.yml`),
spostati in `/root/ritirati_20261126/` con le impronte sha256 identiche (`f9de3cc2…`, `ff705088…`, `75ca72e9…`).
Prima dello spostamento: nessun cron, timer di systemd o script li chiamava (li nominavano solo documenti e prove).

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

### Dopo il deploy: la ZAP

Decisione del fondatore del 23/11/2026: la scansione OWASP ZAP (passiva, non attacca) gira
**ogni giorno** da sola e **subito dopo ogni messa online**, perché il sito cambia proprio lì.
Il VPS non ha e non deve avere una chiave di GitHub: si avvia **dal computer** il workflow
`BookinVIP CI` su master (`workflow_dispatch`), col gettone letto da `git credential fill` e
**mai stampato**, poi si legge dall'API il job `zap` di quel giro (atteso: `success`; un
`failure` vuol dire che una regola di `.zap/regole.tsv` è peggiorata sul sito vivo).

```powershell
# dal computer, PowerShell: avvia il giro e poi leggi il job `zap` del giro appena partito
$cred = "protocol=https`nhost=github.com`n`n" | git credential fill
$tok = ($cred | Where-Object { $_ -like 'password=*' }) -replace '^password=',''
$h = @{ Authorization = "token $tok"; Accept = "application/vnd.github+json" }
$api = "https://api.github.com/repos/edilmax/Core_Auto/actions"
Invoke-RestMethod -Method Post -Uri "$api/workflows/ci.yml/dispatches" -Headers $h -Body '{"ref":"master"}'
$giro = (Invoke-RestMethod -Uri "$api/workflows/ci.yml/runs?event=workflow_dispatch&per_page=1" -Headers $h).workflow_runs[0]
(Invoke-RestMethod -Uri "$api/runs/$($giro.id)/jobs" -Headers $h).jobs | Where-Object name -eq 'zap' | Select-Object status, conclusion
```

## 5. Variabili d'ambiente nuove

Se il lavoro introduce una variabile nuova che governa **denaro o percorsi di database**,
va scritta in `/var/www/bookinvip/.env.casavip` **PRIMA** del deploy: altrimenti il
container parte e va in errore (già successo, ~3 minuti di sito giù).

### ⛔ E il contrario, che è più subdolo: una variabile VECCHIA che vince sul codice nuovo

**La variabile sul server batte sempre il valore scritto nel codice.** Se si cambia un
numero in `main_casavip.py` ma sul server esiste ancora la variabile col valore vecchio, il
deploy riesce, i test sono verdi, il sito **continua a fare come prima** — e non se ne
accorge nessuno. È il verde falso perfetto: nulla è rotto, semplicemente la riparazione non
è arrivata.

✅ **RISOLTO — rimisurato il 2026-08-18 prima del deploy** (`docker exec casavip_app env |
grep -E '^PAGAMENTO_'` → **nessuna riga**; stessa misura del 2026-08-17, stesso esito): sul
VPS non esiste più nessuna `PAGAMENTO_*`,
quindi valgono i **default del codice** — tariffa tecnica **5% + 0,25 €**, **7%** in valuta
estera. ⚠️ Questa tabella dichiarava una `PAGAMENTO_BPS` con la **percentuale superata** come
«in attesa al prossimo deploy»: era **il documento** rimasto indietro, non il server (S10).

| variabile sul VPS | stato misurato 2026-08-18 | cosa vale |
|---|---|---|
| `PAGAMENTO_BPS` | **assente** | il valore del codice |
| `PAGAMENTO_BPS_ESTERA` | assente | il valore del codice |
| `PAGAMENTO_FISSO_CENTS` | assente | il valore del codice |

⛔ **Qui le cifre non si scrivono, e non è pigrizia:** una tariffa ricopiata in un documento
diventa falsa il giorno che cambia nel motore, e nessuno se ne accorge (sbaglio S17, capitato
sei volte in un giorno). La tariffa vera sta in `README.md` e nel codice, con la guardia che
li confronta.

⛔ **Il controllo resta obbligatorio a ogni deploy**, e non perché oggi è a posto: una
variabile vecchia che vince sul codice nuovo è il verde falso perfetto — nulla è rotto,
semplicemente la riparazione non è arrivata.

**Come si controlla che la riparazione sia arrivata davvero**, dopo lo scambio:
```bash
docker exec casavip_app env | grep -E '^PAGAMENTO_' || echo 'nessuna: valgono i default del codice'
```

## 6. Backup e ripristino

I backup girano da soli (container `casavip_backup`, ogni 6 ore, 14 copie per database,
tutti i `*.db` del volume). In più esiste una copia **cifrata fuori dal server**:

```bash
BV_PASS='la-passphrase-segreta' bash deploy/pull_offsite.sh      # crea la copia dal PC
BV_PASS='la-passphrase-segreta' bash deploy/restore_offsite.sh <file.enc> ~/RESTORE
```

Il restore verifica ogni database (`PRAGMA integrity_check`) **e la catena hash del libro
giornale**: se dice "GIORNALE MANOMESSO" quel pacchetto non va usato.

**Ricostruzione da zero** su un server nuovo: installare `docker.io` e il plugin `docker compose`
(**v2**, mai la v1: vedi §1),
clonare il repo in `/var/www/bookinvip`, ricreare `.env.casavip` (le chiavi Stripe si
riprendono da dashboard.stripe.com), creare il volume e copiarci dentro i `.db` restaurati,
poi `build` + `up -d`. Obiettivo: **meno di un'ora**, DNS e certificato esclusi.

## 7. Operazioni comuni

| Azione | Comando (sul VPS) |
|---|---|
| Stato dei container | `docker ps` |
| Log applicazione | `docker logs -f casavip_app` |
| Riavvio pulito dell'app | `docker compose -f docker-compose.casavip.yml restart app` |
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

# 3. se per errore un mount è stato toccato: ricreare il container che lo usa (nginx: la sua fase D17, §3)
sh deploy/protocollo_d17.sh nginx

# 4. e VERIFICARE che il rinnovo funzioni davvero
certbot renew --dry-run           # atteso: "all simulated renewals succeeded"
echo prova > certbot/www/_t && docker exec casavip_nginx cat /var/www/certbot/_t && rm certbot/www/_t
```

> La verifica del punto 4 è la sola che conta: se il container **vede** il file appena scritto,
> il mount è agganciato bene e Let's Encrypt riuscirà a rinnovare.

### 🔒 Il certificato HTTPS: lo rinnova il certbot DEL SERVER (misurato il 2026-11-06)

- `certbot` è installato sul VPS (`/usr/bin/certbot`), `certbot.timer` è acceso (`systemctl is-enabled`
  → `enabled`); certificato `bookinvip.com` per `bookinvip.com` e `www.bookinvip.com`.
- `/etc/letsencrypt/renewal/bookinvip.com.conf`: `authenticator = webroot`, cartella
  `/var/www/bookinvip/certbot/www` (montata in nginx su `/var/www/certbot`), e
  `renew_hook = docker exec casavip_nginx nginx -s reload`.
- nginx legge i certificati da `/etc/letsencrypt` del server, montato in sola lettura dal compose di
  produzione. Su un server nuovo il certificato si prende con questo certbot (sezione «SE IL SERVER
  MUORE», passo 5).

⛔ **Ritirati il 2026-11-06: `docker-compose.casavip.ssl.yml` e `deploy/init-letsencrypt.sh`.** Erano
un secondo modo di avviare il sito, più vecchio: `name: casavip` (un altro progetto Docker, quindi un
magazzino dei dati **nuovo e vuoto** al posto di `bookinvip_casavip_data`), e nginx, certbot e autoheal
senza impronta. Sul server nessuno li usava (nessun cron, timer o script; il sito è il progetto
`bookinvip` avviato da `docker-compose.casavip.yml`). Li sorveglia
`TestOgniComposeCheUnoScriptDiDeployAvviaHaLeImpronte` in `test_deploy_casavip.py`: uno script di
`deploy/` che avvia un compose diverso da quello di produzione la fa diventare rossa.

---

### Nota storica

La procedura dell'impianto **precedente** (server e tecnologie ora dismessi) è conservata nei
documenti in `_archivio/`: **non si applica al prodotto attuale** e i suoi comandi **non vanno
eseguiti** su questa macchina.

---

# 💾 SE IL SERVER MUORE — copia fuori dal server e ripristino da zero

> **Spostato qui da `RIPRENDI_QUI.md` il 2026-08-22.** Non è racconto: è la procedura che
> serve nel giorno peggiore, e `RIPRENDI_QUI.md` da oggi contiene **solo** cosa manca
> (REGOLA ZERO 3). Il posto giusto è qui, accanto a come si mette online: mettere su e
> rimettere in piedi sono la stessa operazione vista dai due lati.

## 💾 BACKUP OFFSITE + RESTORE DA ZERO (contro il data-loss catastrofico) — 2026-07-18
> **Perché**: i backup di bordo (container `casavip_backup`, ogni 6h, 14 per DB) vivono sul
> disco del VPS. Se il disco muore / ransomware / cancello il volume: dati E backup spariscono
> insieme. Difesa: una copia **CIFRATA fuori macchina**, tirata dal PC (mai il VPS che spinge).
> **Scoperto quel giorno**: il backup aveva una LISTA FISSA e NON salvava `finanza.db` (il
> giornale contabile) + checkin/coda/split/geocache/poicache → ora fa **glob `*.db`** (salva
> tutto, sempre). Guardia: `test_backup_completo.py`.

### 1) FARE una copia offsite (dal PC, quando vuoi — ideale: ogni sera)
```bash
cd ~/Desktop/Core_Auto
BV_PASS='UNA-PASSPHRASE-LUNGA-E-SEGRETA' bash deploy/pull_offsite.sh
# -> crea ~/bookinvip-offsite/bookinvip-<data>.tar.gz.enc  (AES-256, verificato coi checksum)
```
> La **passphrase** è l'unica cosa che NON deve stare nel repo né sul VPS: scrivila dove tieni
> le password. Senza, la copia non si può decifrare (è il punto: nemmeno un ladro può).
> Requisiti PC: `ssh`, `openssl`, `tar` (rsync NON serve: c'è il ripiego tar-su-ssh).

### 2) RESTORE DA ZERO (server nuovo, disco morto — procedura idiota-proof)
**A. Ricostruisci i dati dalla copia offsite (sul PC):**
```bash
cd ~/Desktop/Core_Auto
BV_PASS='LA-STESSA-PASSPHRASE' bash deploy/restore_offsite.sh ~/bookinvip-offsite/bookinvip-<data>.tar.gz.enc ~/RESTORE
# verifica OGNI db (PRAGMA integrity_check) + la CATENA HASH del giornale.
# Se dice "GIORNALE MANOMESSO" o "RESTORE con N problemi": NON usare, prova un pacchetto più vecchio.
# Se dice "RESTORE OK": in ~/RESTORE hai tutti i .db pronti.
```
**B. Rimetti in piedi il server (su un VPS Ubuntu pulito):**
```bash
# 1. installa docker + docker compose e git
apt update && apt install -y docker.io git
# 2. prendi il codice (è su GitHub, mai perso)
git clone https://github.com/edilmax/Core_Auto.git /var/www/bookinvip && cd /var/www/bookinvip
# 3. ricrea il file dei segreti .env.casavip (chiavi Stripe da dashboard.stripe.com)
#    e le env DB_* (DB_FINANZA=/data/finanza.db, DB_CHECKIN=..., ecc. — vedi main_casavip.py)
# 4. crea il volume dati e COPIA DENTRO i .db restaurati
docker volume create bookinvip_casavip_data
VOL=$(docker volume inspect --format '{{.Mountpoint}}' bookinvip_casavip_data)
scp ~/RESTORE/* root@<nuovo-vps>:$VOL/      # dal PC; oppure cp se già sul server. Copia anche blocco_globale.flag: bonifici fermi finché una persona non confronta con Stripe (Bunker, riconciliazione) e toglie il blocco
# 5. avvia (HTTPS: serve /etc/letsencrypt — rigenera con certbot se il dominio punta qui)
docker compose -f docker-compose.casavip.yml build app
docker compose -f docker-compose.casavip.yml run --rm --no-deps --user root --entrypoint chown app -R app:app /data   # i file li ha copiati root: senza, l'app non scrive e il blocco non si toglie
docker compose -f docker-compose.casavip.yml up -d
# 6. verifica: curl -sS -o /dev/null -w "%{http_code}\n" https://bookinvip.com/api/health  -> 200
```
> ⛔ **`docker compose` (due parole, v2).** Il testo originale del 18 luglio diceva
> `docker-compose` col trattino: quella è la v1 e **butta giù nginx** (D17). Corretto nello
> spostamento del 2026-08-22.
> **Obiettivo < 1 ora**: i passi 1-2 sono ~10 min, il 4 (copia dati) è secondi (i DB sono piccoli).
> Il collo di bottiglia vero è il DNS/certificato HTTPS. **Esercitazione fatta 2026-07-18**: pull
> reale (172 archivi, 51 checksum ok) + restore su ambiente isolato (17 DB integri) + prova col
> dente (giornale manomesso → beccato a `seq=2`, restore rifiutato). ⚠️ **DA provare col fondatore**
> su un VPS di staging vero, cronometro alla mano (bus-factor: che funzioni anche per un tecnico
> che non conosce il progetto).

## 🧯 ZERO-KNOWLEDGE — per un tecnico che NON ha mai visto questo progetto
> Leggi questo se devi rimettere in piedi BookinVIP e non sai nulla del codice.
> **Cos'è**: un sito (Python stdlib dietro nginx, in Docker) su UN server Hostinger
> `76.13.44.167`, dominio `bookinvip.com`. I dati sono **file SQLite** in un volume Docker.
> Il codice è su GitHub (`edilmax/Core_Auto`, mai perso). I dati stanno **solo** nel volume
> + nelle **copie offsite cifrate** sul PC del proprietario.

### (a) DOVE stanno i dati — percorsi esatti (scoperta automatica di OGNI .db)
- Nel server, volume Docker montato come `/data` dentro i container. Sul disco del VPS:
  `/var/lib/docker/volumes/bookinvip_casavip_data/_data/`
  (trovalo sempre con: `docker volume inspect --format '{{.Mountpoint}}' bookinvip_casavip_data`)
- Lì dentro: **tutti i `*.db`** (misurati **25** il 2026-08-22; erano 17 a luglio: catalogo,
  inventario, registro_host, accettazioni, payout, **finanza** = giornale contabile, garanzia,
  pendenti, tassa_comunale, viral, messaggi, domanda, checkin, coda, split, geocache, poicache,
  admin_accounts, credito_usati, deposito, kyc, marche, partner, poi, recensioni)
  + la cartella `backup/` (snapshot .db.gz + .sha256).
  Il backup li scopre da solo (`*.db`): **non c'è una lista da aggiornare**, ed è per questo
  che il numero può crescere senza che nessuno tocchi niente.

### (b) DECIFRARE una copia offsite (sul PC)
```bash
# le copie sono ~/bookinvip-offsite/bookinvip-<data>.tar.gz.enc (AES-256).
# serve SOLO la passphrase scelta a suo tempo (NON è nel repo né sul server: chiedila al proprietario).
BV_PASS='LA-PASSPHRASE' bash deploy/restore_offsite.sh ~/bookinvip-offsite/bookinvip-<data>.tar.gz.enc ~/RESTORE
# -> verifica ogni checksum + PRAGMA integrity_check + CATENA HASH del giornale.
#    Se dice "GIORNALE MANOMESSO"/"RESTORE con N problemi" -> usa un pacchetto più vecchio.
#    Se dice "RESTORE OK" -> in ~/RESTORE ci sono tutti i .db pronti.
# (decrypt "a mano" senza lo script, se serve:)
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -in <pacchetto>.enc -out backup.tar.gz -pass env:BV_PASS
```

### (c) RIPRISTINO CRONOMETRATO (server nuovo Ubuntu, obiettivo < 1 ora)
```bash
# [~10 min] 1. strumenti
apt update && apt install -y docker.io git python3
# [~2 min]  2. codice (da GitHub, mai perso)
git clone https://github.com/edilmax/Core_Auto.git /var/www/bookinvip && cd /var/www/bookinvip
# [~3 min]  3. segreti: ricrea /var/www/bookinvip/.env.casavip (chiavi Stripe da dashboard.stripe.com;
#            TELEGRAM_BOT_TOKEN/CHAT_ID; e le env DB_* -> vedi main_casavip.py). Vedi anche la sez. 🔑 ACCESSO.
# [~1 min]  4. volume + dati restaurati (dal punto b, dal PC):
docker volume create bookinvip_casavip_data
VOL=$(docker volume inspect --format '{{.Mountpoint}}' bookinvip_casavip_data)
scp ~/RESTORE/* root@<NUOVO-VPS>:$VOL/            # i .db e blocco_globale.flag: i soldi ripartono fermi, lo toglie una persona dal Bunker dopo il confronto con Stripe
# [~15 min] 5. HTTPS: punta il DNS di bookinvip.com al nuovo IP, poi certbot
# [~5 min]  6. avvia
docker compose -f docker-compose.casavip.yml build app
docker compose -f docker-compose.casavip.yml run --rm --no-deps --user root --entrypoint chown app -R app:app /data   # i file li ha copiati root: senza, l'app non scrive e il blocco non si toglie
docker compose -f docker-compose.casavip.yml up -d
# 7. VERIFICA: curl -sS -o /dev/null -w "%{http_code}\n" https://bookinvip.com/api/health   # -> 200
#    e la catena del giornale: python3 fase178_watchdog.py --dati $VOL --backup $VOL/backup --uptime skip
```
> Collo di bottiglia reale = DNS+certificato (passo 5). ⚠️ **DA provare col fondatore** davvero
> su uno staging, cronometro alla mano (bus-factor: che funzioni per un estraneo, non solo sulla carta).

## 🩺 WATCHDOG (sistema nervoso) — installazione e uso
> Sorveglia salute e AVVISA su Telegram. Read-only, non tocca dati. **Due teste** (l'allarme non muore col server):
```bash
# SUL VPS (auto-diagnosi: catena hash + backup fresco + disco + uptime) — cron ogni 10 min:
( crontab -l 2>/dev/null; echo "*/10 * * * * cd /var/www/bookinvip && sh deploy/watchdog.sh >/dev/null 2>&1" ) | crontab -
# DAL PC (l'unico che vede "il server è morto") — quando il PC è acceso, o via Task Scheduler:
REMOTO=1 bash deploy/watchdog.sh    # legge Telegram da deploy/.watchdog.env (gitignored)
```
> Log persistente in `/data/watchdog.log`. Diagnosi on-demand: `GET /api/admin/diagnosi` (admin-key).
> ✅ **Verificato attivo il 2026-08-22**: il cron c'è, e la copia di bordo più fresca era delle 07:38
> dello stesso giorno. Consigliato in più (gratis): un uptime-monitor esterno su `/api/health`.

## 📌 CONTROLLI RAPIDI (dal proprio PC)
```bash
curl -sS -o /dev/null -w "HTTP %{http_code} cert=%{ssl_verify_result}\n" https://bookinvip.com/   # atteso: HTTP 200 cert=0
curl -sS -X POST https://bookinvip.com/api/domanda -H 'Content-Type: application/json' -d '{"email":"a@b.com","citta":"roma"}'  # atteso: {"ok": true,...}
```

## 🔑 ACCESSO
- VPS: `ssh root@76.13.44.167` (Hostinger, Ubuntu 24.04). La chiave pubblica `edilmax` (id_ed25519) è
  installata in `/root/.ssh/authorized_keys`. Fallback sempre disponibile: **hPanel Hostinger → VPS →
  Terminale del browser** (root, senza password).
- ⛔ **Nota del 2026-08-22:** la riga originale rimandava a `STATO_FINALE.md` e `COSE_DA_FARE.md`.
  **Quei due file non esistono più.** Cosa fa la macchina: `README.md`. Cosa manca: `RIPRENDI_QUI.md`
  e `python collaudi/piano.py` — e se i due si contraddicono, **vince `piano.py`**.

## 🧹 COSE MINORI (non urgenti)
- Container `casavip_backup`: healthcheck vero (ultimo backup in `/data/backup/*.gz` più fresco di
  7 ore). In produzione risulta **healthy**; se torna rosso, i backup sono DAVVERO fermi.
- ⛔ *Qui c'era una riga su un vecchio server dismesso, spostata insieme al resto il
  2026-08-22 e **tolta subito dopo**: `test_deploy_md` vieta in questo documento ogni nome
  del vecchio impianto, e ha ragione. Chi ripristina di fretta non deve trovare qui niente
  di copiabile per errore. Il fatto storico resta in `REGISTRO_INGEGNERIA.md`, che è il
  diario. È la seconda volta oggi che quella guardia mi prende: la prima sul nome della
  vecchia tecnologia, la seconda sul nome del vecchio fornitore.*
