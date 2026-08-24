# B19 — PASSAGGIO 8 · TUTTI I PUNTI DOVE DUE FILE DICONO NUMERI DIVERSI PER LA STESSA COSA

> **Referto di misura, non lista di cose da fare.** Sola lettura: nessun file di prodotto è
> stato toccato, nessuna riparazione fatta, nessuna suite eseguita, nessun commit, nessuna
> chiamata all'API, nessun giro sul VPS.
> Misurato il **2026-08-25**, su `HEAD = 584f0e9`, ramo `master`
> (`git status --porcelain`: modificati `CLAUDE.md`, `RIPRENDI_QUI.md`, `deploy/index.html`
> + la cartella non tracciata `collaudi/audit/`; **nessun `fase*.py` toccato, nessun file
> sotto `deploy/` toccato da me**).
>
> Perimetro, come lo definisce il passaggio: **due file che dicono cose diverse della stessa
> cosa.** ⛔ E la regola in più di questo passaggio: **non confondere «discordi» con «diversi
> a ragione»** — 5% e 7% sono due casi veri, non un conflitto. Per ogni voce qui sotto c'è
> quindi una riga «**quale delle due**», che dice qual è il numero giusto e perché.

---

## RISULTATO IN UNA RIGA

**17 coppie discordi** — 🔴 **6 gravi** · 🟠 **9 medie** · 🟡 **2 minori** — più **13 sospetti
verificati e scartati** (scritti apposta perché non si riaprano) e **3 conferme indipendenti**
di difetti già contati dai passaggi 1 e 6, **segnalate e NON sommate**.

🔑 **La forma di famiglia, e non è quella che mi aspettavo.** Cercavo «il numero vecchio
rimasto in un posto». Ne ho trovato uno solo di quella specie. **Le altre 16 sono di due
famiglie precise, e nessuna delle due si vede leggendo un file per volta:**

| famiglia | voci | cos'è, detto in una riga | esempio più caro |
|---|---|---|---|
| **il numero e la sua ETICHETTA vivono in file diversi** | 9 | il valore lo calcola un motore, la frase che lo racconta sta in una pagina, in un contratto o in una docstring — e nessuno confronta i due | `deploy/commissioni.html`: il riquadro dice **€84,75**, il paragrafo accanto dice **€87**, e sono a schermo insieme |
| **due motori RISPONDONO ALLA STESSA DOMANDA con numeri diversi** | 7 | non è una copia invecchiata: sono due implementazioni vive, entrambe collegate, entrambe raggiungibili dalla produzione | `/api/split/preview` accetta **1000** partecipanti, `/api/split/crea` ne rifiuta più di **50** |
| il numero vecchio rimasto indietro | 1 | la copia classica | `fase89:189` = **400** (4%) contro `main_casavip.py:150` = **500** (5%) |

💡 **Il corollario pratico, ed è scomodo: dieci di queste diciassette NON si riparano
cambiando un numero.** Bisogna prima decidere **quale dei due motori vive** (referral,
split, benchmark OTA, gateway paga-in-struttura) — e quella è una decisione del fondatore,
non una correzione. Le altre sette sono una riga sola ciascuna.

⚠️ **E il punto dove fa più male: sei voci su diciassette stanno sulla riga dei soldi che
l'host ha FIRMATO.** Il contratto (`fase163_accettazioni.py`) è l'unico documento che
l'host accetta con prova HMAC, e tre motori diversi addebitano cifre che quel testo non
prevede.

---

## DENOMINATORE DICHIARATO

Cosa ho guardato, e quanto è grande:

| grandezza | numero | come è stata misurata |
|---|---|---|
| file di produzione esaminati | **169** | `main_casavip.py` + 151 `fase*.py` + 14 `deploy/*.html` + `app.js` + `sw.js` + `manifest.json` (scanner di sessione) |
| righe di produzione (solo `.py`) | **50.915** | `cat fase*.py main_casavip.py \| wc -l` — **riproduce esattamente il numero del passaggio 7** |
| righe di pagine e script serviti | **5.303** | `cat deploy/*.html deploy/app.js deploy/sw.js \| wc -l` |
| file di configurazione e deploy (perimetro AGGIUNTO da me) | **28** | `deploy/*.conf`, `deploy/*.sh`, `docker-compose*.yml`, `Dockerfile*` |
| moduli **raggiungibili** da `main_casavip.py` | **93** | grafo degli import (AST + import dinamici da stringa), scanner di sessione |
| moduli **mai raggiunti** | **59** | idem — **coincide con i passaggi 4, 5 e 7**, con uno scanner riscritto oggi |
| occorrenze numeriche in righe che nominano un concetto | **13.417** | scanner di sessione: 16 famiglie di parole chiave × ogni numero con unità (`%`, `€`, `bps`, `giorni`, `ore`) |
| costanti a livello modulo con lo **stesso nome** e valore diverso in file diversi | **3** su ~1.100 | scanner AST di sessione (assegnazioni di modulo + campi di `dataclass`) |
| campi di `dataclass` con lo stesso nome e valore diverso | **2** | idem |

### Come sono stati cercati i numeri discordi, e con quattro attrezzi diversi

1. **Scanner per concetto** (di sessione): ogni riga dei 169 file che contiene un numero
   **e** una parola di una delle 16 famiglie (commissione, penale, ripensamento, tasse,
   soglie, tempi, lingue, payout, cauzione, rampa, referral, prezzi, KYC, recensioni,
   concorrenti, tariffa tecnica) viene indicizzata con `file:riga`, valore e unità; poi si
   guardano solo i concetti che hanno **≥ 2 valori distinti in ≥ 2 file**.
2. **Scanner AST delle costanti** (di sessione): tutte le assegnazioni a livello di modulo e
   tutti i campi di `dataclass` con valore numerico (anche `48 * 3600`, risolto), raggruppati
   **per nome**. Questo è l'attrezzo che ha stanato `MAX_PARTECIPANTI` (50 contro 1000) e
   `_MAX_POI` (6 contro 12): due numeri che nessuna parola chiave avrebbe accostato.
3. **Grafo di raggiungibilità** (di sessione): serve a dire, per ogni discordanza, **se
   entrambe le parti sono vive**. Senza questo un conflitto in un modulo morto sembra grave
   quanto uno in produzione. 93 vivi / 59 mai raggiunti.
4. **Lettura a mano**, riga per riga, di ogni coppia sospetta: **41 punti aperti e letti**
   (i due motori referral, i due split, i due confronti OTA, il gateway paga-in-struttura, il
   contratto in due lingue, i testi legali in otto, le quattro configurazioni nginx). È qui
   che sono morti gli 13 falsi positivi elencati in fondo.

⛔ **Nessun numero di questo referto è stato riprodotto eseguendo il codice.** Tutti sono
**letti** dai file. Dove ho fatto un conto (i €84,75, i 3,80 € del gateway) il conto è
aritmetica sui valori letti, e lo dichiaro voce per voce.

---

# 🔴 LE SEI GRAVI

## 1. La pagina delle commissioni si contraddice da sola, in tutte e 8 le lingue: **€84,75** nel riquadro, **€87** nel paragrafo accanto

- **Il riquadro** (HTML statico, sempre visibile): `deploy/commissioni.html:75` `<b>€84,75</b>`
  «l'host incassa», con accanto `:76` `<b>€10</b>` (commissione 10%) e `:77` `<b>€5,25</b>`
  (tariffa tecnica 5% + 0,25 €). **I tre numeri quadrano**: 100 − 10 − 5,25 = 84,75.
- **Il paragrafo** (`data-i18n="sim_p"`, sostituito dal dizionario a `:96-103`): dice
  «ospite €100, host **€87**. Se è un tuo cliente diretto (5%): ospite €100, host **€92**».
  Sono i numeri del **vecchio 3%**: 100 − 10 − 3 = 87, 100 − 5 − 3 = 92.
- **E non è un ripiego che scatta solo in una lingua**: il testo statico italiano a `:79`
  dice €84,75, ma `TR.it.sim_p` a `:96` dice €87, e l'applicatore a `:108` fa
  `el.textContent = d[k]` **sempre**, anche in italiano. Quindi la riga statica giusta viene
  **sovrascritta da quella sbagliata a ogni caricamento**, in tutte e 8 le lingue.
- **Misurato**: le 8 righe di dizionario `:96-103` contengono tutte `host €87` / `€92`
  (`grep -o "sim5:\"[^\"]*\"" ` e lettura del blocco `sim_p`); il riquadro non ha `data-i18n`
  sul valore, solo sull'etichetta.
- **Effetto collaterale sulla stessa riga**: l'etichetta statica `:77`
  «tariffa tecnica 5% + 0,25 € (a te)» viene sostituita da `sim5` = «costo carta (a te, 0
  nostro margine)» — cioè **il riquadro da €5,25 resta a schermo senza più la frase che dice
  cos'è**, in tutte e 8 le lingue.
- **Quale delle due**: **€84,75 / €89,75** (il riquadro). È l'unica coppia coerente con
  `main_casavip.py:131` (commissione 1000 bps) e `:150-152` (500 bps + 25 cents).

## 2. L'email di reclutamento dice **4%**, il motore addebita **5%**

- `fase89_jurisdiction_outreach.py:189`:
  `return _intero_bps(os.environ.get("PAGAMENTO_BPS", "400")) or 400` → **400 bps = 4%**.
- `main_casavip.py:150`: `psp_bps=int(os.environ.get("PAGAMENTO_BPS", "500"))` → **500 bps = 5%**.
- ⛔ **E la docstring della stessa funzione dichiara il contrario di ciò che fa**:
  `fase89:185` dice *«(4%) dichiarato in `main_casavip.py`. Mai una cifra scritta a mano
  qui»* — mentre il 4% è scritto a mano **due volte sulla riga 189** (il default della
  variabile d'ambiente e il ripiego dell'`or`), e in `main_casavip.py` quel numero **non
  esiste**: lì c'è 500.
- **Perché in produzione vince il 4%**: le due letture usano la **stessa** variabile
  `PAGAMENTO_BPS` con **default diversi**. Se la variabile è assente, l'email dice 4% e il
  motore prende 5%. (⚠️ *non ho misurato l'ambiente del VPS in questo passaggio*: vedi «cosa
  è rimasto fuori».)
- **Già trovato dal passaggio 1** come *cifra sbagliata nell'email*, e dal passaggio 7 come
  *copia*; **il passaggio 7 lo ha esplicitamente rimandato qui** per la sua conseguenza, che
  è questa: due file rispondono con numeri diversi alla stessa domanda. **Contato una volta,
  qui.**
- **Quale delle due**: **500 (5%)**. È quello che il contratto firmato dichiara
  (`fase163_accettazioni.py:215-218`, «TECHNICAL FEE of 5% … PLUS EUR 0.25») ed è quello che
  copre il costo Stripe misurato (`main_casavip.py:144-147`).

## 3. `deploy/diventa-host.html` promette **3%** e **5% + 0,25 €** nella stessa pagina, nella stessa lingua

- `c1_p` (il testo che spiega la tariffa): «In ogni periodo, anche a 0%, resta dovuta una
  tariffa tecnica del **3%** che copre il costo della carta: **su quella riga non guadagniamo
  nulla**» — riga statica `:60` e chiave `c1_p` in tutti e 8 i blocchi di dizionario.
- `copy` (il piè di pagina della stessa pagina): «nessuna commissione nascosta: tariffa
  tecnica **5% + 0,25 €**» — riga statica `:92` e chiave `copy` in tutti e 8 i blocchi.
- **Misurato**: contate riga per riga le 8 righe di dizionario `:98-105` →
  **3% presente 1 volta e «0,25» presente 1 volta in OGNI riga**, 8 su 8. Non è una lingua
  dimenticata: **è la stessa pagina che dice due cifre diverse, in tutte le lingue,
  contemporaneamente**.
- **Il passaggio 1 aveva contato il «3%»** come cifra sbagliata. Qui il difetto è un altro e
  si somma: **la cifra giusta è già scritta sulla stessa pagina**, dieci righe più in basso.
  Chi ripara il 3% deve sapere che non deve *aggiungere* la fonte: deve **togliere la
  seconda**.
- **Quale delle due**: **5% + 0,25 €** (`main_casavip.py:150-152`, contratto `fase163:215`).

## 4. Due motori di referral vivi, con **premi diversi** e **soglie di qualifica diverse**, sullo stesso link d'invito

Non è un residuo: **sono due catene complete, entrambe cablate in `fase81`, entrambe con
rotte HTTP vive.**

| | motore A — `fase76_viral_loop` | motore B — `fase109_referral_host` |
|---|---|---|
| cablato in | `fase81_bootstrap_casavip.py:356-361` | `fase81_bootstrap_casavip.py:504-506` |
| premio a chi invita | **€40** (`fase81:57` `referral_premio_cents = 4000`) | **€10 / €15 / €20** a scaglioni (`fase109:23` `TIERS_DEFAULT = ((3,1000),(9,1500),(10**9,2000))`) |
| benvenuto a chi arriva | **€10** (`fase81:56`) | **nessuno** |
| quando scatta | alla **3ª** prenotazione pagata (`fase81:58`, applicato a `fase83_server.py:8321`) | alla **1ª** prenotazione (`fase109:85`, docstring e codice) |
| rotta che genera il link | `GET /api/host/referral` (`fase83_server.py:2033` → `:8745`) | `GET /api/host/invito` (`fase83_server.py:2003` → `:8784`) |
| link prodotto | `/diventa-host.html?ref=<codice>` (`:8764`) | `/diventa-host.html?ref=<codice>` (`:8795`) — **identico** |
| chi lo usa davvero | il pannello host (`deploy/host.html:847` chiama `/api/host/referral`) | **nessuna pagina lo chiama** (`grep "host/invito" deploy/` → 0) |

- ⛔ **I due link sono indistinguibili e non sono intercambiabili.** La registrazione
  (`fase83_server.py:8695-8705`) consuma `codice_referral` **solo** col motore A. Un codice
  generato dal motore B, incollato nello stesso identico formato di URL, **non viene
  riconosciuto e chi ha invitato non prende niente, in silenzio**.
- **Quale delle due**: **da decidere** (è l'unica voce di questo referto che non ha una
  risposta tecnica). Oggi il pannello usa A; B è un motore completo con uno schedario
  durevole su file e una rotta admin di qualifica (`:8812`) che nessuno chiama. Finché
  vivono entrambi, **la domanda «quanto vale portare un host?» ha due risposte: €40 e €10**.

## 5. La prova fotografica di un problema muore a **~700 KB**, mentre l'app e il messaggio dicono **5 MB**

- **L'app**: `fase83_server.py:2327` `if not raw or len(raw) > 5 * 1024 * 1024` — il tetto è
  **5 MB**, ed è la funzione `_salva_foto_raw` (`:2318`) usata da `POST /api/voucher/prova`
  (`:1965` → `:2419`).
- **Il messaggio all'ospite**: `fase83_server.py:288` `v_js_foto_ko` = «Foto non valida
  (**max 5MB**, jpg/png)», in tutte e 8 le lingue.
- **Il proxy**: `deploy/nginx.casavip.ssl.conf:43` `client_max_body_size 1m` a livello di
  `server`, e **l'unica location che alza il tetto è un'altra**: `:80-83`
  `location = /api/host/upload_foto { … client_max_body_size 8m; }`. **Non esiste nessuna
  location per `/api/voucher/prova`**: cade in `location /` (`:113`) e resta a **1m**.
- **Misurato**: elencate tutte le `location` e tutti i `client_max_body_size` del file
  (righe 20, 25, 43, 74, 75, 77, 81, 83, 105, 106, 113, 136). Una sola eccezione, e non è
  questa rotta.
- **Perché è grave e non è un dettaglio**: una foto JPEG diventa **~1,37×** in base64 dentro
  il JSON. Con il tetto a 1 MB passa un'immagine di circa **700 KB** — cioè meno di uno
  scatto di telefono qualunque. E la foto in questione è **la prova che l'ospite carica per
  contestare** (`_voucher_prova`, `:2406-2419`): è l'unica prova che l'arbitro vedrà quando
  si decide **a chi vanno i soldi in garanzia**. L'ospite riceve un `413` di nginx, cioè un
  errore che l'app non ha scritto e che il testo tradotto in 8 lingue **contraddice**.
- **Quale delle due**: devono coincidere. Il tetto **voluto e dichiarato è 5 MB** (il
  commento di `deploy/nginx.casavip.ssl.conf:78-79` lo dice per l'altra rotta: «un'immagine
  fino a 5MB diventa ~7MB in base64»): **manca la stessa eccezione per `/api/voucher/prova`.**

## 6. Su «paga in struttura» l'host paga una tariffa che il contratto che ha firmato **non prevede**

- **Il contratto** (l'unico documento con prova HMAC): `fase163_accettazioni.py:215-221` —
  «a TECHNICAL FEE of **5%** … **PLUS EUR 0.25** per transaction … For Listings priced in a
  currency other than the euro the fee is **7%** plus EUR 0.25». Stessa cifra nei testi
  legali in 8 lingue (`fase185_testi_legali.py:132-134`, `:206-208`, `:280-283`, `:357-359`,
  `:433-435`, `:507-509` e seguenti), che la prendono **dinamicamente** da `fase98`/`fase83`
  (`fase185:62-79`).
- **Il motore**: `fase188_paga_struttura.py:41-43` e `:51` —
  `GATEWAY_FISSO_CENTS = 55`, `GATEWAY_BPS = 325`, `GATEWAY_BPS_CAMBIO = 200`,
  `GATEWAY_MINIMO_CENTS = 50`. Cioè **3,25% + 0,55 €** (e **+2%** se l'annuncio non è in
  euro), non 5% + 0,25 € (7% + 0,25 € in valuta estera).
- ⛔ **E il modulo dichiara di applicare l'altra cifra.** La sua docstring, `fase188:18-19`,
  dice che la copertura carta è *«assorbita dall'host **come la tariffa tecnica (5%, 7% in
  valuta estera)**»*. Il numero nominato nel commento e il numero nelle costanti, **nello
  stesso file**, non sono lo stesso numero.
- **Il conto, su 100 € (aritmetica sui valori letti, non riprodotta)**: contratto → l'host
  lascia **5,25 €** (euro) o **7,25 €** (valuta estera). `fase188` → l'host lascia
  **3,80 €** (euro) o **5,80 €** (valuta estera). **Discordanza in entrambi i versi, e in
  entrambi i casi paga meno di quanto ha firmato.**
- **Quale delle due**: **il contratto** (5% / 7% + 0,25 €). È l'unico testo che l'host ha
  accettato con prova, ed è quello che i testi legali producono in 8 lingue. La cifra di
  `fase188` è motivata bene nel suo commento (copre il caso peggiore Stripe + 30c di
  sicurezza) **ma nessuno l'ha mai scritta all'host**.
- ⚠️ **Quanto è viva**: `fase83_server.py:5320` legge `PAGA_STRUTTURA_ATTIVO` con default
  `"0"`, quindi **nel codice è spenta**. *Non ho misurato l'ambiente del VPS in questo
  passaggio* — vedi «cosa è rimasto fuori».

---

# 🟠 LE NOVE MEDIE

## 7. La tabella dei concorrenti: il motore e la pagina pubblica dicono numeri diversi su **cinque portali su cinque**

| portale | `fase69_trasparenza.py:44-48` (il motore) | `deploy/commissioni.html:57-63` (la pagina) | scarto |
|---|---|---|---|
| Booking | **1800 = 18%** | «10–25% (**media 15%**)» | 3 punti |
| Airbnb | **1500 = 15%** | «**15,5%** (modello unico 2026)» | 0,5 punti |
| Expedia | **2000 = 20%** | «15–20% (10–30%)» | al bordo |
| Agoda | **1800 = 18%** | «15–20%» | fuori dall'intervallo |
| TripAdvisor | **1500 = 15%** | «**~3%** (legacy)» | **cinque volte** |

- **Entrambi sono vivi e li vede la stessa persona**: `fase69` non è fra i 59 moduli mai
  raggiunti; `fase83_server.py:7315-7331` (`GET /api/trasparenza`) risponde con quei
  benchmark, e **il pannello host li mostra**: `deploy/host.html:413` è una tendina con
  `booking / airbnb / expedia` e `:1243` chiama `/api/trasparenza?…&ota=`. La pagina pubblica
  `commissioni.html` è linkata dalla stessa navigazione.
- **La coppia Booking 15/18 era già nota (B16)** ed è l'esempio con cui il passaggio è stato
  scritto; **le altre quattro no**. La più grossa è **TripAdvisor: 15% nel motore contro
  ~3% nella pagina** — se un host sceglie di confrontarsi con TripAdvisor, il pannello gli
  promette un guadagno extra calcolato su una commissione **cinque volte** più alta di quella
  che la nostra stessa pagina dichiara.
- **Quale delle due**: **nessuna delle due è misurata da noi.** `fase69:43` dice
  «default indicativi pubblici», `commissioni.html:67` dice «Fonti: pagine ufficiali e
  portali di settore». Il difetto qui non è quale numero è giusto: è che **la stessa
  affermazione ha due fonti indipendenti e nessuna guardia le confronta**.

## 8. Il risparmio mostrato all'ospite è calcolato su una commissione che la nostra stessa pagina dichiara **abolita**

- `fase125_confronto_guest.py:17-19`: `ota_markup_host_bps = 1500` (15%),
  **`ota_guest_fee_bps = 1400` (14%)**, `ota_dcc_bps = 400` (4%).
- `deploy/commissioni.html:57`: Airbnb, colonna «Commissione ospite» → «**0%** (era 14–16%)»,
  nota «dal dic 2025 fee solo-host». `:58`: Booking, commissione ospite → «**0%**».
- **Entrambi vivi**: `fase83_server.py:7487-7505` (`_concierge_quote`) chiama
  `confronta_guest` e mette `confronto_ota` nella risposta; `deploy/index.html:612-613` lo
  disegna: «su OTA pagheresti **€X** · risparmi **€Y** (**−Z%**)».
- **L'effetto**: il riquadro verde del risparmio somma al prezzo OTA una *guest fee* del 14%
  che **la pagina delle commissioni dello stesso sito dichiara non esistere più**. Su 100 €
  di netto host il conto di `fase125` produce ~131 € di totale OTA; la tabella di
  `commissioni.html` produce ~115–120 €.
- **Quale delle due**: **`commissioni.html`** — è la più recente e la più documentata
  («dal dic 2025 fee solo-host»). `fase125` va aggiornato o il riquadro va spento.

## 9. «**0 nostro margine**» contro «**1,75 punti di margine**»

- **Le pagine, in 8 lingue**: `deploy/commissioni.html:96-103` `sim5` = «costo carta (a te,
  **0 nostro margine**)»; `deploy/diventa-host.html:98-105` `c1_p` = «**su quella riga non
  guadagniamo nulla**».
- **Il motore**: `main_casavip.py:146-147`, in chiaro e con la misura accanto:
  «euro → 5% contro 3,25% = **1,75 punti di margine** · estera → 7% contro 5,25% = **1,75
  punti di margine**», con la fonte dichiarata («120 addebiti in modalità prova»,
  `main_casavip.py:144-145`).
- **Quale delle due**: **1,75 punti** (è un numero misurato, non una stima). La frase «0
  margine» era vera con la tariffa al 3%; con 5% + 0,25 € **non lo è più**, ed è la stessa
  frase che il passaggio 6 aveva trovato in 7 lingue nel kit di reclutamento.
- ⚠️ Non è solo marketing: è la frase che un host può citare per contestare la tariffa.

## 10. Quanto prendono le OTA: la stessa affermazione con **quattro intervalli diversi**

- `deploy/diventa-host.html:60` (e `c1_p` in 8 lingue): «Sotto il **18–25%** delle OTA».
- `deploy/commissioni.html` `cta_p` (8 lingue): «invece del **15–25%** delle OTA».
- `deploy/commissioni.html:58` (tabella): Booking «**10–25%** (media 15%)».
- `deploy/commissioni.html:67` `note_table`: «Media di mercato ponderata per quota
  **≈ 16–17%** totale».
- **Quale delle quattro**: nessuna è derivata dalle altre e **le prime due si escludono a
  vicenda** (il minimo è 18 o 15?). Va scelto **un** intervallo e ripetuto; oggi il numero
  cambia a seconda della pagina da cui l'host arriva.

## 11. Lo stesso conto di gruppo: la **preview** accetta 1000 persone, la **creazione** ne rifiuta più di 50

- `fase133_split_quote_uguali.py:32`: `MAX_PARTECIPANTI = 1000`, usato da
  `POST /api/split/preview` (`fase83_server.py:1955` → `:7437-7444`, che chiama
  `riparti_uguale`).
- `fase65_split_payment.py:45`: `MAX_PARTECIPANTI = 50`, il motore dietro
  `POST /api/split/crea` (`fase83_server.py:1991` → `:7700`, `self._sys.split`, cablato in
  `fase81_bootstrap_casavip.py:518-529`).
- ⛔ **E i due file argomentano il proprio numero in modo incompatibile.**
  `fase133:9-16` motiva il 1000 come tetto **anti-DoS** su una rotta pubblica, e a `:28-31`
  scrive: *«Un gruppo vero di persone che dividono un soggiorno sta in decine»* — cioè
  **descrive esattamente il 50 di `fase65`** e poi sceglie 1000.
- **L'effetto misurabile**: un gruppo di 60 persone ottiene una preview perfetta, con 60
  quote a conservazione esatta, e poi **non può creare il conto**.
- **Quale delle due**: **50** per la creazione (è il motore che muove i soldi), e la preview
  deve rifiutare **lo stesso** numero. Un tetto anti-DoS più alto della funzione vera non
  protegge: sposta solo l'errore dopo l'illusione.

## 12. `fase99` dichiara di riusare uno split «**3%/12%**» che in `fase98` **non esiste**

- `fase99_multicurrency.py:12` (docstring del modulo) e `:105` (docstring della funzione):
  «Riusa lo **split 3%/12%** di fase98».
- `fase99_multicurrency.py:102-103`: la funzione usa i valori veri,
  `host_bps = policy.HOST_BPS`, `guest_bps = policy.GUEST_BPS`.
- `fase98_policy_commissione.py:34-35`: `HOST_BPS = 200` (**2%**), `GUEST_BPS = 800` (**8%**).
- **Quale delle due**: **2%/8%** (è quello che il codice esegue). Il «3%/12%» non compare in
  nessun punto di `fase98`: è un numero che **non esiste più da nessuna parte** e sopravvive
  solo in due commenti di un modulo raggiungibile.

## 13. Nello stesso file, il tariffario vivo (**5% / 10%**) convive col tariffario morto (**2% / 8%**)

- `fase98_policy_commissione.py:34-35`: `HOST_BPS = 200`, `GUEST_BPS = 800` — lo «split
  asimmetrico 2%/8%».
- `fase98_policy_commissione.py:37-38`: `BPS_DIRETTO = 500` (**5%**),
  `BPS_MARKETPLACE = 1000` (**10%**) — il modello vivo.
- Il file stesso, a `:4-7`, dichiara il primo **legacy e mai cablato**: «le costanti 2%/8%
  restano solo per compatibilità storica: **NON descrivono il tariffario applicato**».
- **Ma quelle costanti non sono inerti**: sono i default di `ripartisci_host_guest`, che
  `fase99_multicurrency.py:102-103` usa come default della propria funzione pubblica
  `ripartisci_pagamento`. Un motore multi-valuta che chiama quella funzione senza argomenti
  **applica il tariffario che il file dichiara morto**.
- **Segnalato dal passaggio 7 come voce di confine e rimandato qui; contato qui, una volta.**
- **Quale delle due**: **5% / 10%** (`fase98:37-38`, contratto `fase163:224-227`).

## 14. Il gate di sicurezza DAC7 (**28 / 1.800 €**) non è quello che blocca i soldi (**30 / 2.000 €**)

- `fase100_dac7.py:24-27`: `soglia_pren = 30`, `soglia_ricavi_cents = 200000` (**la soglia
  legale**) **e** `margine_pren = 28`, `margine_ricavi_cents = 180000` (**il gate di
  sicurezza**, dichiarato nell'intestazione `:5-7` come il numero che sospende l'annuncio e
  blocca i payout *prima* di sforare).
- `fase83_server.py:6053`, l'unico punto che blocca davvero un bonifico, legge
  `valuta_dac7(...).deve_segnalare` — cioè `legale` a `fase100:46`, che usa **30 / 2.000 €**
  e **non guarda il margine**. Idem `fase83_server.py:3194` e `:3282` (il pannello).
- **L'effetto**: il margine di sicurezza — le due prenotazioni e i 200 € di anticipo che
  dovrebbero dare tempo all'host di completare i dati fiscali — **non scatta mai**. Il blocco
  arriva quando l'obbligo è già maturato.
- **Quale delle due**: **28 / 1.800 €** per il gate (è per questo che è stato scritto) e
  30 / 2.000 € per l'obbligo di segnalazione. Oggi il primo dei due numeri non lo legge
  nessuno.
- ⚠️ Il passaggio 5 aveva già misurato che **il modulo è spento ma il blocco payout no**;
  questa è la metà che mancava: **quale delle due soglie** quel blocco usa.

## 15. Due configurazioni nginx per lo stesso sito, con due tetti diversi sull'upload (**8m** contro **2m**)

- `deploy/nginx.casavip.ssl.conf:80-83` (**quella viva**, montata da
  `docker-compose.casavip.yml:82`): `location = /api/host/upload_foto` con
  `client_max_body_size 8m`, e il commento `:78-79` che spiega perché
  («un'immagine fino a 5MB diventa ~7MB in base64»).
- `deploy/nginx.host-vps.conf:26`: `client_max_body_size 2m` **a livello di server, senza
  nessuna location di eccezione** — e quel file ha **una sola** `location /` (`:29`).
- **Perché non è teoria**: quel file esiste per essere applicato, e le istruzioni sono dentro
  il file stesso (`:5-9`: `sudo cp deploy/nginx.host-vps.conf /etc/nginx/sites-available/…`).
  Chi lo applica ottiene un sito che **rifiuta ogni foto d'annuncio sopra ~1,4 MB**, con un
  `413` che nessun test coglie perché i test non passano da nginx.
- **Quale delle due**: **8m sulla rotta di upload** (e, per la voce 5, anche su
  `/api/voucher/prova`). Il 2m generale è ragionevole come anti-abuso: gli manca l'eccezione.

---

# 🟡 LE DUE MINORI

## 16. Si scaricano **12** punti d'interesse e se ne usano **6**

- `fase175_poi_osm.py:31`: `_MAX_POI = 12` (quanti POI il modulo scarica da Overpass).
- `fase171_cervello_seo.py:90`: `_MAX_POI = 6` (quanti ne cita il testo SEO).
- Il raggio invece **coincide di proposito** (`_RAGGIO_M = 1500` in entrambi,
  `fase175:30` e `fase171:89`) e `fase175:34` cita esplicitamente `fase171._POI_NOTABILI`:
  i due file si conoscono.
- **Quale delle due**: non è un errore di calcolo, è **metà del lavoro di rete buttato**.
  Va allineato a 6 o va dichiarato perché se ne scaricano 12 (es. per scartarne alcuni dopo
  il filtro di categoria).

## 17. La politica di cancellazione di default non è nessuna delle quattro che esistono

- `fase111_cancellazione.py:19`, default della `dataclass`:
  `scaglioni = ((7, 10000), (1, 5000), (0, 0))` — cioè ≥7 giorni 100%, 1-6 giorni 50%,
  0 giorni 0%.
- `fase111_cancellazione.py:25-28`, le quattro politiche vere: `flessibile` ((1,10000),(0,5000)),
  `moderata` ((5,10000),(1,5000),(0,0)), `rigida` ((30,10000),(7,5000),(0,0)),
  `non_rimborsabile` ((0,0)). **Il default non coincide con nessuna delle quattro.**
- E il commento `:23-24` dice «100% → 50% → 0% a scaglioni di giorni» mentre `flessibile` —
  quella consigliata nel pannello (`deploy/host.html:381`) e il ripiego del calcolo
  (`fase111:51`) — **non ha lo scaglione 0%**: sotto le 24 ore rimborsa comunque **50%**.
- **Quale delle due**: le **quattro nominate** (sono quelle che il pannello offre e che il
  voucher firmato trasporta). Il default della `dataclass` è una quinta politica che non ha
  nome, non è offerta a nessuno, e che si applicherebbe solo a chi costruisse una
  `PoliticaCancellazione()` senza argomenti.

---

## ✅ TRE CONFERME INDIPENDENTI — segnalate, NON contate

Le ho ritrovate da qui con attrezzi diversi. **Sono già contate dai passaggi 1 e 6 e non le
sommo alle 17.**

1. **Il numero di lingue del prodotto: 8, 5 o 13.** `fase61_localizzazione.py:41` e
   `fase185_testi_legali.py:35`, `fase86_email.py:126`, `fase63_recensioni.py:46` → **8**;
   `fase90_marketing.py:37` → **5** (`it, en, es, fr, de`); `fase97_inbound_seo.py:28` →
   **13**. *Passaggio 6.*
2. **La tariffa tecnica nella sala di controllo**: `deploy/bunker.html` `ct_h` dice
   «Tariffa tecnica Stripe (**5% + 0,25 €**)» in italiano e «(**3%**)» nelle altre **7**
   lingue (verificato oggi, 1 su 8 contro 7 su 8). *Passaggio 6.*
3. **`deploy/kit-marketing.html`**: 7 occorrenze di «3%» e 5 di «5% + 0,25» nello stesso
   file. *Passaggio 6.*

---

## ⛔ TREDICI SOSPETTI VERIFICATI E SCARTATI (scritti perché non si riaprano)

1. **Le politiche di cancellazione nelle pagine contro il motore.** Combaciano **esattamente**,
   e in tutte e 8 le lingue: `rigida` = «30 giorni, poi 50%, niente sotto i 7» in
   `deploy/host.html:383` (8 blocchi) e in `fase83_server.py:215` (8 lingue) contro
   `fase111:27` `((30,10000),(7,5000),(0,0))`; `flessibile` = 24h contro `(1,10000)`;
   `moderata` = 5 giorni contro `(5,10000)`. **Verde pieno, e va detto.**
2. **La lunghezza minima della password.** `fase88_registro_host.py:358` (`>= 8`),
   `fase88:286` (stesso controllo sul reset), `fase83_server.py:1630` e `:1674` (il
   controllo nel browser), `deploy/host.html` («min 8»). **Cinque punti, un solo numero.**
3. **La durata del link di reset.** `fase88_registro_host.py:274` `exp = now + 1800` contro
   `fase86_email.py:408` «Il link vale **30 minuti**» in 8 lingue. Coincidono.
4. **Il battito del Guardiano.** `fase178_watchdog.py:45` `MAX_ETA_BATTITO_SEC = 25 * 3600`
   contro il commento di `fase83_server.py:11115` «se ne accorge entro **25 ore**» e il giro
   giornaliero `:11132` `sleep(86400)`. 24 + 1 di grazia: **è un conto, non una copia**.
5. **La freschezza dei backup.** `docker-compose.casavip.yml:96` `sleep 21600` (ogni **6h**)
   contro `deploy/watchdog.sh:30` `MAX_ETA_H=8` e `fase178_watchdog.py:175`
   `max_eta_backup_sec = 8 * 3600`. 6 < 8: allineati con margine.
6. **Il tetto foto dell'host.** `fase83_server.py:2302` (5 MB) contro
   `deploy/nginx.casavip.ssl.conf:83` (8m) contro il testo `v_js_foto_ko`. **Questa rotta è
   giusta** — è l'altra (voce 5) a non avere l'eccezione.
7. **Gli sconti soggiorno lungo.** `fase59_concierge.py:292` (≥7 settimana, ≥28 mese) contro
   `deploy/host.html:388-389` («per 7+ notti», «per 28+ notti») contro il tetto
   `fase57_vetrina.py:330-331` (9000 bps = 90%) e `max="90"` nei due campi del pannello.
   **Quattro file, un solo numero per ciascuna soglia.**
8. **Lo sconto non-rimborsabile.** `fase59_concierge.py:309` (`1200` bps) contro
   `fase83_server.py:132` `non_rimb` = «Non rimborsabile **−12%**» in 8 lingue.
9. **La finestra della garanzia.** `fase160_escrow_garanzia.py:22`
   `FINESTRA_ORE_DEFAULT = 24` contro `fase83_server.py:151` «Hai **24 ore** dal check-in per
   segnalare» in 8 lingue. E la grazia del Guardiano (`fase186:47` `GRAZIA_ESCROW_ORE = 48`)
   **non è un terzo numero**: è quanto si aspetta *dopo* la scadenza prima di gridare.
10. **La penale host del 15%.** `fase83_server.py:924` `PENALE_HOST_BPS = 1500` contro
    `deploy/guida-operativa.html:87` («host paga il 15% di penale») contro
    `deploy/host.html` `hc_conferma` contro `fase177_financial_controller.py:21` e `:652`.
    **Coincidono.** ⚠️ Ma vedi la nota qui sotto.
11. **Le soglie DAC7 mostrate al fondatore.** `deploy/bunker.html` `conf_p`
    («**30 prenotazioni** o **2.000 €**», 8 lingue) contro `fase100_dac7.py:24-25`.
    Coincidono con la soglia **legale**; il difetto è sul *margine* (voce 14), non su questa.
12. **`LIMITE_TESTO` a 4000 / 2000 / 4000.** `fase57_vetrina.py:60`, `fase63_recensioni.py:45`,
    `fase77_portability.py:42`. Sono **tre campi diversi** (descrizione annuncio, testo
    recensione, esportazione dati): stesso nome, cose diverse. Scartato.
13. **`cap_bps` / `floor_bps` a 25000/700 e 6000/400.** `fase106_dynamic_pricing.py:29-30`
    contro `fase43_commissione.py:170-172`. Domini diversi (tetto sul prezzo dinamico contro
    tetto sulla commissione) e `fase43` è **fra i 59 moduli mai raggiunti**. Scartato.

> ⚠️ **Una nota sul punto 10, perché è un discorde LATENTE e non voglio che si perda.**
> `fase177_financial_controller.py:667` scrive nel **giornale immutabile** la causale
> `"penale 15% cancellazione host"` come **stringa fissa**, mentre l'importo arriva dal
> chiamante (`fase83_server.py:6371`, calcolato con `PENALE_HOST_BPS`). Oggi i due numeri
> coincidono, quindi **non lo conto**. Ma il giorno che la penale cambia, il giornale — che
> per costruzione **non si può correggere** — racconterà per sempre una percentuale che non
> è stata applicata. È un valore sparso (passaggio 7), che diventa un numero discorde
> **nell'unico posto dove non si può più riparare**.

---

## ⛔ COSA È RIMASTO FUORI (D18 punto 3)

Un taglio silenzioso fa sembrare «coperto» ciò che nessuno ha visto. Ecco i tagli, dichiarati:

1. **Non ho eseguito niente e non ho toccato il VPS.** Nessun test, nessuna suite, nessuna
   chiamata all'API, nessun `ssh`. In particolare **due voci dipendono dall'ambiente di
   produzione e io ho letto solo il codice**: la voce **2** (se `PAGAMENTO_BPS` è impostata
   sul VPS, email e motore concordano; se è assente, no) e la voce **6** (se
   `PAGA_STRUTTURA_ATTIVO=1` sul VPS, il gateway di `fase188` è vivo; nel codice il default è
   `"0"`). **Chi ripara deve prima leggere quelle due variabili sul server.**
2. **Nessun numero è stato riprodotto.** I €84,75, i €87, i 3,80 € del gateway e i ~700 KB
   della voce 5 sono **aritmetica sui valori letti**, non misure fatte girando il prodotto.
3. **`collaudi/` e i 406 `test_*.py` non sono stati setacciati.** Il perimetro è la
   produzione. Quindi **questo referto non dice se una guardia contiene un numero discorde**
   — ed è già successo (`test_trasparenza_costi.py`, passaggio 7 punto 18).
4. **I 59 moduli mai raggiunti sono stati guardati solo per escluderli.** Un conflitto fra
   due moduli morti non è in questo referto (es. `fase43_commissione` contro
   `fase104_gateway_asia`). Se un domani si riaccendono, **vanno riesaminati**.
5. **I dizionari di traduzione sono stati confrontati solo dove contenevano un NUMERO.**
   Le chiavi mancanti e i testi scompagnati sono il passaggio 6 e non li ho ricontati.
6. **Lo scanner per concetto ha un limite dichiarato**: indicizza un numero solo se sulla
   **stessa riga** compare una parola di una delle 16 famiglie. Un numero discorde scritto su
   una riga muta (una costante senza commento, un valore in una tabella senza intestazione)
   lo può trovare solo lo scanner AST (che copre le costanti di modulo e i campi di
   `dataclass`) o la lettura a mano. **I numeri dentro il corpo delle funzioni, senza nome e
   senza parola chiave accanto, non sono coperti da nessuno dei due.**
7. **Non ho confrontato il codice con il VPS né con i documenti** (`README.md`, `DEPLOY.md`,
   `REGISTRO_INGEGNERIA.md`): il perimetro del passaggio è **file di prodotto contro file di
   prodotto**. Le uniche eccezioni sono le 28 configurazioni di deploy, che ho **aggiunto**
   al perimetro perché `nginx.conf` e `docker-compose.yml` decidono numeri che il prodotto
   subisce (voci 5 e 15) — e la voce 5 è nata proprio lì.
8. **Le 8 lingue sono state contate, non lette.** Dove scrivo «in tutte e 8 le lingue» ho
   verificato la **presenza della cifra** in ciascuno degli 8 blocchi (conteggio per riga),
   non la correttezza della traduzione intorno.
