# B19 — PASSAGGIO 16 · L'AMBIENTE DEL VPS CONTRO I DEFAULT DEL CODICE

> **Referto di misura, non lista di lavori.** Sola lettura **anche sul VPS**: solo comandi di
> lettura (`git rev-parse`, `docker ps`, `docker inspect`, `grep`, `cat`, `curl`, `ls`, `date`).
> **Nessuna variabile cambiata, nessun contenitore riavviato, nessun deploy, nessuna scrittura.**
> Nessun `fase*.py` toccato, nessuna suite eseguita, nessun commit.
>
> ⛔ **Nessun valore segreto è stato stampato, né qui né a schermo.** Per ogni nome che contiene
> `KEY`, `SECRET`, `TOKEN`, `PASSWORD`, `PASS`, `SEGRETO`, `RECOVERY`, `TOTP`, `APP_ID`, `IBAN`
> o `DATABASE_URL`, il filtro sul VPS ha sostituito il valore con `<PRESENTE, N byte>` **prima**
> che uscisse dal server. Di quei nomi questo referto dice **solo se ci sono e quanto sono
> lunghi**, mai cosa contengono.
>
> Misurato il **2026-08-25** con computer, GitHub e VPS tutti su `cb45c80`
> (`git rev-parse --short HEAD` sul VPS: **cb45c80**; contenitore `casavip_app` **Up 24 hours
> (healthy)**, immagine `sha256:859f637a…`).
>
> **Perché questo passaggio esiste:** **nove referti su nove** dichiarano, nella loro sezione
> «cosa è rimasto fuori», di aver letto **i default del codice** e non l'ambiente vero — e sul
> VPS **le variabili d'ambiente vincono sul codice**. Finché non si leggevano, almeno nove voci
> dell'audit erano scritte su un'ipotesi.

---

## RISULTATO IN UNA RIGA

**Su 132 variabili lette dal codice, 57 sono impostate in produzione e 24 no** (per quelle vince
il default). **Nove voci dei nove referti cambiano forma**: 🔴 **3 passano da «dipende
dall'ambiente» a CONFERMATE IN PRODUZIONE**, 🔄 **1 si ribalta** (era «spento di serie», in
produzione è **acceso**), 🟢 **1 decade** (in produzione non si applica), e **4 restano latenti,
ora per misura e non per ipotesi**. Più **12 variabili impostate che nessuna riga del prodotto
legge** — fra cui **tre segreti vivi**.

---

## DENOMINATORE DICHIARATO

| grandezza | numero | come è stata misurata |
|---|---|---|
| variabili lette dal codice di produzione | **132** | scanner di sessione su `main_casavip.py` + 151 `fase*.py`, quattro forme (`os.environ.get` con e senza default, `os.environ[...]`, `os.getenv`) |
| righe di ambiente nel contenitore vivo | **87** | `docker inspect --format='{{range .Config.Env}}…'` su `casavip_app`, filtrate e ordinate |
| file `.env` sul server | **2** su 3 cercati | `.env` (1.257 byte, 15 righe con `=`) · `.env.casavip` (2.935 byte, 54 righe) · `.env.prod` **non esiste** |
| moduli raggiungibili da `main_casavip.py` | **89 vivi / 63 mai raggiunti** su 152 | grafo degli import (statici + `__import__`/`import_module` da stringa), scanner di sessione |
| lette dal codice **vivo** e **assenti** in produzione | **24** | incrocio dei due elenchi |
| lette dal codice **vivo** e **presenti** | **57** | idem |
| impostate e lette **solo da moduli mai raggiunti** | **4** | idem |
| impostate e **lette da nessuno** | **12** (+5 dell'immagine Python) | idem, **dopo la controprova** |

### Due attrezzi indipendenti, e il secondo ha corretto il primo

1. **Scanner delle forme** (`os.environ.get(...)` su una riga): trova il **default dichiarato**,
   che è l'altra metà della domanda.
2. **Controprova testuale**: cerca **ogni nome dell'ambiente VPS come stringa** in tutti i moduli,
   senza pretendere una forma.

⚠️ **I due non concordavano su 7 nomi su 87, e ha ragione il secondo.** Il primo dichiarava «non
la legge nessuno» per `CAMPAGNA_STATO_FILE`, `GROQ_API_KEY`, `INDEXNOW_HOST`, `META_PAGE_ID`,
`META_PAGE_TOKEN`, `OUTREACH_OPTOUT_FILE` e classificava male `TELEGRAM_CHAT_ID`: sono tutte
**lette davvero**, da righe **spezzate su due righe** che una `regex` di riga non vede
(`fase83_server.py:10517-10518` è l'esempio). **Le 7 correzioni sono state applicate prima di
scrivere questo referto**, e nessuna conclusione poggia sul primo attrezzo da solo.

⚠️ **E il grafo dà 89 vivi / 63 mai raggiunti, mentre i passaggi 4, 5, 7 e 8 danno 93 / 59.**
La discordanza era **già dichiarata aperta dal passaggio 6** (punto 6 del suo «rimasto fuori») e
**non la risolvo qui**: il mio universo comprende i `fase*.py` e `main_casavip.py`, e il mio
scanner segue anche gli import dinamici da stringa. ⛔ **Nessuna voce di questo referto dipende
da quale dei due numeri sia giusto**: le tre variabili classificate «spente» lo sono in entrambi.

---

# 🔴 LE TRE CHE PASSANO DA «DIPENDE» A **CONFERMATE IN PRODUZIONE**

## 1. `PAGAMENTO_BPS` **non è impostata** — quindi i tre ripieghi divergono davvero, adesso

```
in produzione : ASSENTE
nel codice    : main_casavip.py:150            -> ripiego 500 bps
                fase89_jurisdiction_outreach.py:189 -> ripiego 400 bps
                fase185_testi_legali.py:71     -> rilegge la variabile per conto suo
```

- **Cosa cambia:** il passaggio 1 (N1), il passaggio 8 (voce 2) e il **GIRO B1** del piano
  contenevano tutti la stessa riserva — *«se sul VPS la variabile è impostata, l'email e il motore
  concordano»*. **Non è impostata.** L'email di reclutamento promette la cifra del suo ripiego e
  il motore addebita quella del suo: **la divergenza è viva in produzione**, non ipotetica.
- ⚠️ Stessa storia per le due sorelle: **`PAGAMENTO_BPS_ESTERA` e `PAGAMENTO_FISSO_CENTS` sono
  anch'esse assenti** → valgono i ripieghi del codice, e la quota fissa resta il numero in euro
  che il passaggio 5 (voce 5) ha trovato sommato alle unità minori di qualunque valuta.
- 💡 **Il rimedio è di una riga di ambiente**, e **non** è la riparazione: mettere la variabile
  farebbe concordare i tre ripieghi *oggi* e li lascerebbe divergere al primo che ne aggiunge un
  quarto. Il GIRO B1 resta come scritto.

## 2. `PAGA_STRUTTURA_ATTIVO=1` — è **acceso**

```
in produzione : 1
nel codice    : fase83_server.py:5320, :6941, :7528  -> default "0"
```

- **Cosa cambia:** le voci **8·6** (l'host paga una tariffa che il contratto firmato non prevede)
  e **9·9** (il pannello dice «incassi uguale» e «l'ospite paga il prezzo pulito» mentre il
  gateway addebita) erano marcate **latenti**. **Non lo sono.** Ogni ospite che sceglie «paga in
  struttura» oggi paga la quota a notte di `fase188_paga_struttura.py:37`, e l'host assorbe la
  copertura carta di `:80`.
- **Cosa NON cambia:** la **decisione D7** del piano resta una decisione (quale tariffa vale,
  quella del contratto o quella del gateway). Sapere che è acceso la rende **urgente**, non
  risolta.

## 3. `DAC7_BLOCCO_PAYOUT` **non è impostata** → vale il default **`"1"`**: il blocco è **ACCESO**

```
in produzione : ASSENTE  ->  fase83_server.py:6036 legge il default "1"
fase100_dac7  : attivo = False   (il modulo è spento)
```

- **Cosa cambia:** la voce **5·4** diceva *«il gate di giurisdizione esiste e l'unico punto che
  blocca i soldi non lo consulta»*, e il passaggio 5 ci aveva già corretto **B18 punto 3**. Ora è
  misurato nella forma peggiore: **il modulo DAC7 è spento e il blocco dei bonifici è acceso**.
  In produzione, un host sopra soglia senza dati fiscali completi **non viene pagato**, e la
  decisione di bloccarlo non passa da nessuna regola di giurisdizione.
- Il **GIRO B3** del piano sale di priorità: non è una precauzione, è una porta chiusa attiva.

---

# 🔄 LA VOCE CHE SI RIBALTA

## 4. Il marketing automatico **è acceso**, e parla **due lingue su otto**

```
in produzione : CAMPAGNA_AUTO_GIORNI=3      CAMPAGNA_LINGUE=it,en
nel codice    : fase83_server.py:10512      default ""  -> scheduler NON avviato
                fase83_server.py:10521      default ""  -> "default del motore (tutte)"
```

- 🔄 **La voce 9·6 va corretta.** Diceva *«il marketing automatico è spento di serie»*: **vero nel
  codice, falso in produzione**. Sul server lo scheduler parte, e pubblica **ogni 3 giorni**.
- 🔴 **E il difetto vero è l'altra variabile.** Il passaggio 6 (voci 13 e 14) aveva misurato che il
  motore parla **5 lingue su 8** e scarta le altre in silenzio, e che il commento del server
  dice «tutte». In produzione `CAMPAGNA_LINGUE=it,en`: **le campagne escono in 2 lingue su 8**.
  Il prodotto si vende in otto lingue e si promuove in due.
- ⚠️ **Nessuno l'avrebbe visto leggendo il codice**, ed è esattamente la ragione per cui questo
  passaggio esiste: il commento a `:10521` dice «vuoto → tutte», e in produzione **non è vuoto**.

---

# 🟢 LA VOCE CHE DECADE

## 5. Il Bunker **è configurato**: il fascicolo non esce con la sola chiave admin

```
in produzione : BUNKER_PASSWORD <PRESENTE, 23 byte>   BUNKER_TOTP_SECRET <PRESENTE, 32 byte>
                BUNKER_RECOVERY  ASSENTE
```

- La voce **9·8** aveva due rami: con il Bunker non configurato, `_bunker_ok_o_field`
  (`fase83_server.py:3082-3095`) lascia passare le operazioni distruttive con la sola chiave
  admin. **Quel ramo non si applica**: la password c'è. L'enforcement è attivo.
- ⚠️ **Resta l'altra metà**, che non dipendeva dall'ambiente: la frase del bunker dice che i dati
  personali sono *«visibili solo da qui, mai nel pannello operativo»*, e il fascicolo si scarica
  **da `admin.html`** — protetto, ma da lì.
- ⚠️ **`BUNKER_RECOVERY` è assente.** Non è un difetto di per sé; è un fatto da sapere: se si
  perdono password e secondo fattore, **non c'è una via di rientro configurata**.

---

# ✅ LE QUATTRO CHE RESTANO LATENTI — ora per misura, non per ipotesi

| voce del piano | variabile | in produzione | conseguenza |
|---|---|---|---|
| **B4** · il kill-switch non copre `riscuoti_debiti_carta` | `SCATTO3_ATTIVO` | **ASSENTE** → default `"0"` | lo sweep che addebita le carte **non parte**: il buco resta chiuso finché quella variabile non si accende |
| **9·5** · la carta serve solo a saldare una penale scoperta | `SCATTO3_ATTIVO` | **ASSENTE** | la carta salvata oggi **non viene usata per niente** |
| rampa e promo | `PROMO_LANCIO`, `COMMISSIONE_BPS` | **ASSENTI** → `"true"`, `"1000"` | la promozione di lancio **è attiva** e la commissione a regime è quella del ripiego |
| valuta di incasso | `VALUTA` | **ASSENTE** → `"EUR"` | conferma la premessa del passaggio 5 (voce 5): incassiamo in una valuta sola |

---

# 🟠 QUATTRO COSE NUOVE, CHE NESSUN ALTRO PASSAGGIO POTEVA VEDERE

## 6. Tre segreti vivi nell'ambiente che **nessuna riga del prodotto legge**

| variabile | nel contenitore | chi la legge |
|---|---|---|
| `STRIPE_LIVE_SECRET_KEY` | `<PRESENTE, 107 byte>` | **nessuno** (il prodotto usa `STRIPE_SECRET_KEY`) |
| `STRIPE_LIVE_PUBLIC_KEY` | `<PRESENTE, 107 byte>` | **nessuno** |
| `META_APP_SECRET` | `<PRESENTE, 32 byte>` | **nessuno** (`fase91_canali_social` usa `META_PAGE_TOKEN`) |
| `TIKTOK_CLIENT_SECRET` | `<PRESENTE, 32 byte>` | **nessuno** |
| `META_APP_ID`, `TIKTOK_CLIENT_KEY` | presenti | **nessuno** |

- 🔴 **Una chiave `sk_live` in più nell'ambiente è superficie d'attacco senza contropartita**: chi
  legge l'ambiente del contenitore la ottiene, e nessuna funzione del prodotto la userebbe. Sono
  **quattro segreti** che si possono togliere senza cambiare una riga di codice.
- ⛔ **Non l'ho tolta né toccata**, e non va tolta senza controllare che nessuno script di deploy
  la usi: `docker-compose.casavip.ssl.yml` la passa via `env_file: .env.casavip`, quindi va tolta
  **dal file**, non dal contenitore, e con un deploy dichiarato.

## 7. L'identità fiscale è **nell'ambiente**, e il codice la scrive **a mano**

```
in produzione : PARTITA_IVA_STARTUP=<impostata>   REGIME_FISCALE=regime_forfettario
                STARTUP_PAYOUT_IBAN=<PRESENTE, 20 byte>
chi le legge  : nessuno
dove sta il valore, cablato:
   fase185_testi_legali.py:52      "piva": "…"
   fase83_server.py:1349           "Edil Max di Foti Massimo — P.IVA … — "
   deploy/index.html:247           il piè di pagina pubblico
```

- 💡 **È il passaggio 7 girato al contrario.** Lì la fonte unica esisteva e la produzione non la
  raggiungeva; qui **la fonte unica è stata messa nell'ambiente dal fondatore** e il codice non
  sa che esiste. Il risultato è identico: **cambiare quel dato richiede di toccare tre file**, e
  chi lo cambia nell'ambiente non cambia niente.
- ⚠️ **L'IBAN di incasso della startup è nell'ambiente e nessuno lo legge.** Il valore non è
  stampato qui.

## 8. Due canali social **configurati e spenti**

```
MASTODON_TOKEN, MASTODON_INSTANCE  -> letti solo da fase193_canale_mastodon
NOSTR_PRIVATE_KEY, NOSTR_RELAYS    -> letti solo da fase197_canale_nostr
```

Entrambi i moduli stanno fra i **63 mai raggiunti** da `main_casavip.py`. Il fondatore ha messo
i token; i moduli **non partono**. `X_ENABLED=false` e `ALIPAY_WECHAT_CONNECT_SPLIT=true` non
compaiono in **nessun file del progetto**: sono variabili che non esistono per il codice.

## 9. `SMTP_PORT=465` contro il default `587`, e un `.env` di un altro prodotto nella stessa cartella

- **`SMTP_PORT`**: in produzione **465** (SSL implicito), nel codice il ripiego è **587**
  (STARTTLS). Le email dei soldi partono da qui (passaggio 3, S11: sono tutte spara-e-dimentica).
  ⚠️ **Non ho inviato nessuna email**: non affermo che funzioni, dico che i due numeri sono
  diversi e che il codice non lo saprebbe mai.
- **`HOST=0.0.0.0`** contro il default `127.0.0.1`: corretto dentro un contenitore, ed è l'unica
  variabile che allarga la superficie di rete. Scritta qui perché nessun referto l'ha mai detta.
- **`/var/www/bookinvip/.env`** è il file di **TavolaVIP** (15 righe): contiene un altro
  `STRIPE_API_KEY`, un altro `STRIPE_WEBHOOK_SECRET` e credenziali `mailtrap` di sandbox.
  ✅ **Non entra nel processo**: il compose di CasaVIP dichiara `env_file: .env.casavip`
  (`docker-compose.casavip.ssl.yml:18`). Resta un file di segreti di un altro prodotto nella
  cartella di questo.

---

# 📋 LE DUE TABELLE

## A) Lette dal codice VIVO e **ASSENTI** in produzione → vince il default (24)

| variabile | default che vince | dove si legge |
|---|---|---|
| `PAGAMENTO_BPS` | 500 bps / 400 bps (due ripieghi) | `main_casavip.py:150` · `fase89…:189` · `fase185…:71` |
| `PAGAMENTO_BPS_ESTERA` | ripiego del codice | `main_casavip.py:151` · `fase185…:75` |
| `PAGAMENTO_FISSO_CENTS` | quota fissa in euro | `main_casavip.py:152` · `fase185…:76` |
| `COMMISSIONE_BPS` | 1000 bps | `main_casavip.py:131` · `fase83_server.py:10898,10938` |
| `VALUTA` | `EUR` | `main_casavip.py:130` |
| `PROMO_LANCIO` | `true` | `main_casavip.py:133` |
| `DAC7_BLOCCO_PAYOUT` | **`1` (blocco ACCESO)** | `fase83_server.py:6036` |
| `SCATTO3_ATTIVO` | `0` (sweep carta spento) | `fase83_server.py:7911,7921` |
| `PAGE_GATE` | `1` (gate pagine attivo) | `fase83_server.py:10650` |
| `PULIZIA_UPLOADS` | `1` | `fase83_server.py:2229` |
| `DATA_DIR` | `/data` | `main_casavip.py:76` · `fase178…:261` · `fase83_server.py:3844` |
| `BACKUP_DIR` | tre ripieghi diversi | `fase178…:262` · `fase38…:147` · `fase83_server.py:3833` |
| `MARCA_TEMPORALE` | `1` (marche attive) | `fase184…:717` |
| `MARCA_SOLO_QUALIFICATA` | `0` | `fase184…:442` |
| `MARCA_ACCETTA_RIPIEGO`, `TSA_URL` | vuoti | `fase184…:738`, `:449` |
| `DOMANDA_SOGLIA` | `5` | `fase83_server.py:7241` |
| `DOMANDA_ALLARME_FILE` | vuoto | `fase83_server.py:7244` |
| `SENTINEL`, `SENTINEL_DIR` | vuoti | `main_casavip.py:167-168` |
| `BUNKER_RECOVERY` | vuoto | `main_casavip.py:123` |
| `POOL_AI_STATO` | nessuno | `fase81…:571` |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID` | vuoti | `main_casavip.py:163-164` |

⚠️ **`BACKUP_DIR` ha tre ripieghi diversi in tre file e nessuno la imposta**: è la stessa forma
del punto 1 del passaggio 7, su una cosa che decide **dove finiscono le copie di sicurezza**.

## B) Lette dal codice VIVO e **PRESENTI** (57) — le sole che cambiano qualcosa rispetto al codice

| variabile | in produzione | default del codice |
|---|---|---|
| `PAGA_STRUTTURA_ATTIVO` | **1** | `0` |
| `CAMPAGNA_AUTO_GIORNI` | **3** | vuoto (spento) |
| `CAMPAGNA_LINGUE` | **it,en** | vuoto («tutte») |
| `HOST` | **0.0.0.0** | `127.0.0.1` |
| `SMTP_PORT` | **465** | `587` |
| `STATIC_DIR` | `/app/deploy` | `deploy` |
| `VIDEO_DIR` | `/app/video_pubblici` | vuoto |
| i 21 `DB_*`, `UPLOAD_DIR`, `FILE_REFERRAL` | tutti sotto `/data/…` | tutti sotto `data/…` (relativi) |
| `BASE_URL`, `STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL` | i domini veri | vuoti |
| `ALERT_EMAIL`, `EMAIL_MITTENTE`, `SMTP_HOST`, `SMTP_USER` | impostati | vuoti |
| `GEOCODING`, `POI_OSM`, `PORTA` | uguali al default | — |
| `CASAVIP_SEGRETO` · `HOST_KEY` · `ADMIN_KEY` · `BUNKER_PASSWORD` · `BUNKER_TOTP_SECRET` · `STRIPE_SECRET_KEY` · `STRIPE_WEBHOOK_SECRET` · `STRIPE_IDENTITY_KEY` · `TELEGRAM_BOT_TOKEN` · `TELEGRAM_WEBHOOK_SECRET` · `INDEXNOW_KEY` · `OXR_APP_ID` · `SMTP_PASSWORD` | **tutte PRESENTI** | vuote |

✅ **`OXR_APP_ID` è impostata.** Era segnata come lavoro aperto in memoria (*«`OXR_APP_ID` sul
VPS»*): **è fatto**, e il cambio valuta ha la sua chiave.
✅ **`STRIPE_WEBHOOK_SECRET` è impostata** (38 byte): la premessa di **S8** del passaggio 3 (il
webhook che rifiuta un pagamento senza lasciare una riga) è viva, ma la verifica della firma
**c'è**, non è saltata.

---

## ✅ VERIFICATO E SANO — misurato adesso, non ricordato

```
git rev-parse --short HEAD (VPS)     cb45c80      = computer = GitHub
docker ps                            casavip_app  Up 24 hours (healthy)
                                     casavip_backup Up 24 hours (healthy)
                                     casavip_nginx  Up 4 days
immagine viva                        sha256:859f637a882efdb0…
GET https://bookinvip.com/           HTTP 200 in 0,025 s
GET /api/health                      {"status":"ok","money_unit":"cents_integer","guardiano":"ok"}
GET /api/health/ready                200
/data/guardiano_ultimo_giro          1787618039  ->  19,1 minuti fa (ora del contenitore 1787619185)
```

**Il battito del guardiano è vivo e recente.** ⚠️ E vale la pena dirlo insieme al passaggio 9:
quel battito **il fondatore non lo vede in nessun pannello** — `/api/bunker/guardiano` esiste e lo
interroga solo la cartella `collaudi/`.

---

## ⛔ COSA È RIMASTO FUORI (D18 punto 3)

1. **Non ho letto l'ambiente dei processi figli né quello di `casavip_backup`.** Ho letto
   `.Config.Env` di `casavip_app`, cioè ciò che il contenitore dichiara. Una variabile impostata
   **a runtime** dentro il processo (da codice) non comparirebbe.
2. **Non ho eseguito nulla dentro il prodotto.** L'unico `docker exec` è stato `ls`, `cat` e
   `date` sul file del battito: lettura pura. Nessuna funzione del prodotto è stata chiamata.
3. **Non ho verificato che i valori funzionino.** Che `SMTP_PORT=465` consegni davvero, che la
   chiave Stripe sia valida, che `OXR_APP_ID` risponda: **non misurato**. Questo referto confronta
   **due elenchi**, non prova un comportamento.
4. **`docker-compose` non è stato letto per intero**: ho contato le righe `env_file`/`environment`
   e non ho espanso i blocchi `environment:` di `casavip_nginx` e `casavip_backup`. Se uno di
   quei due imposta qualcosa per l'app, non lo vedo.
5. **Le 50 variabili lette solo da moduli mai raggiunti e assenti non sono state elencate**: sono
   irrilevanti per la produzione di oggi, e diventerebbero rilevanti solo con la decisione **D9**.
6. **La discordanza 89/63 contro 93/59 sui moduli raggiungibili non è risolta**, solo dichiarata.
7. **Nessuna variabile è stata cambiata, nessun file `.env` toccato, nessun contenitore
   riavviato, nessun deploy.** Questo referto è l'unico file scritto, e **non è committato**.
