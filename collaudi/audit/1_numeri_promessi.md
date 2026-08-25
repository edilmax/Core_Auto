# B19 — PASSAGGIO 1 · I NUMERI PROMESSI CONTRO I VALORI VERI NEL CODICE

> **Referto di misura, non lista di cose da fare.** Sola lettura: nessun file di prodotto è
> stato toccato, nessuna suite eseguita, nessun commit.
> Misurato il **2026-08-24**, su `HEAD = 584f0e9`.
> Perimetro: ogni cifra che una **pagina**, un'**email**, un **contratto** o una **landing**
> mostra a un cliente o a un host, confrontata con la costante che la produce, **in tutte e 8
> le lingue**.

---

## 0. LA VERITÀ, LETTA DAL MOTORE (non dai documenti)

| Cosa | Valore vero | Dove sta scritto |
|---|---|---|
| Tariffa tecnica (annuncio in euro) | **500 bps = 5%** | `main_casavip.py:150` |
| Tariffa tecnica (valuta estera) | **700 bps = 7%** | `main_casavip.py:151` |
| Quota fissa per transazione | **25 cent = 0,25 €** | `main_casavip.py:152` |
| Commissione a regime | **1000 bps = 10%** | `main_casavip.py:131` |
| Rampa di lancio | **0% per 90 gg → 8% fino a 365 gg → 10%** | `fase98_policy_commissione.py:74-77` |
| Canale diretto | **500 bps = 5%** | `fase98_policy_commissione.py:37` |
| Commissione ospite | **0 bps = 0%** | `fase125_confronto_guest.py:20` |
| Penale cancellazione host | **1500 bps = 15%**, ospite rimborsato 100% | `fase83_server.py:923-924` |
| Ripensamento | **48 h** (`48*3600`), solo se arrivo ≥ 3 giorni | `fase83_server.py:472`, `:6732` |
| Soglia DAC7 | **30 prenotazioni o 2000 €/anno** | `fase100_dac7.py:24-25` |
| Referral: bonus al referrer | **10 € / 15 € / 20 €** a scaglioni | `fase109_referral_host.py:23` |
| Referral: quando scatta | alla **PRIMA** prenotazione del referee | `fase109_referral_host.py:84-95` |
| Lingue del prodotto | **8**: it,en,es,fr,de,pt,ja,zh | `fase61_localizzazione.py:41` · `fase86_email.py:126` · `fase185_testi_legali.py:35` |
| `PAGAMENTO_BPS` in produzione | **ASSENTE** → vale il default del codice | `DEPLOY.md:227` |

**Come è stata prodotta questa tabella:** letta riga per riga dai file sopra, non da
`README.md` né da `REGISTRO_INGEGNERIA.md`.

---

## 1. INCONGRUENZE TROVATE — 15

### 🔴 N1 — L'EMAIL DI RECLUTAMENTO PROMETTE **4%**. IL MOTORE PRENDE **5% + 0,25 €**. IN 8 LINGUE.

- **Dove:** `fase89_jurisdiction_outreach.py:189` — `_tecnica_bps()` ripiega su `400` (4%).
- **Cosa dice il testo:** *«c'è una tariffa tecnica del **4%** sempre dovuta»* — `fase89:219` (it)
  e le altre 7 versioni di `_TEMPLATE_ROMA` (`:218-233`) e di `_TEMPLATE` (`:196-208`).
- **Cosa fa il codice:** `main_casavip.py:150` addebita `500` bps = **5%**, più `0,25 €` fissi
  che l'email **non nomina mai**.
- **Perché è attivo in produzione, non teorico:** `DEPLOY.md:227` dichiara `PAGAMENTO_BPS`
  **assente** dall'ambiente → il ripiego `400` è il valore che l'host riceve davvero.
- **Lingua:** tutte e 8 (il segnaposto `{tecnica}` è nello stesso punto di ogni template).
- **Come l'ho misurato** (D22), eseguito con l'ambiente pulito:
  ```
  _tecnica_bps() = 400 -> testo: 4%
  main default PAGAMENTO_BPS = 500
  TECNICA NEL TESTO: ['tariffa tecnica del 4%']
  ```
- ⛔ **Direzione del danno:** promette **meno** di quanto prendiamo, come B16 punto (a).

### 🔴 N2 — LA DOCSTRING CHE DOVEVA IMPEDIRLO DICE IL FALSO

- **Dove:** `fase89_jurisdiction_outreach.py:184-185`.
- **Cosa dice:** *«altrimenti il default **400 (4%)** dichiarato in `main_casavip.py`. Mai una
  cifra scritta a mano qui»*.
- **Cosa fa il codice:** `main_casavip.py:150` dichiara **500**. La riga che vieta le cifre a
  mano ne contiene una, ed è sbagliata. È lo sbaglio S17 (il numero vecchio sopravvive nel
  commento che spiega il nuovo), qui **dentro il codice eseguito**, non solo nel commento.

### 🔴 N3 — `diventa-host.html` PROMETTE **3%** IN TUTTE E 8 LE LINGUE — **ITALIANO COMPRESO**

- **Dove:** `deploy/diventa-host.html:60` (markup statico, IT) e `:98,99,100,101,102,103,104,105`
  (chiave `c1_p`, una per lingua). **9 occorrenze.**
- **Cosa dice:** *«In ogni periodo, anche a 0%, resta dovuta una tariffa tecnica del **3%** che
  copre il costo della carta»*.
- **Cosa fa il codice:** **5% + 0,25 €** (`main_casavip.py:150,152`).
- ⛔ **E la stessa riga si contraddice da sola:** a `:98` la chiave `copy` dice
  *«tariffa tecnica **5% + 0,25 €** sempre dovuta»*. Sulla **stessa riga dello stesso file**,
  nella **stessa lingua**, convivono `3%` e `5% + 0,25 €`.
- ⚠️ **Correzione a B16 punto (a):** B16 (`RIPRENDI_QUI.md:701-706`) dà l'italiano di questa
  pagina per corretto citando `:92, :98`. L'italiano di `:60` e `:98` (chiave `c1_p`) dice **3%**.
  Il difetto è **8 lingue su 8**, non 7.

### 🔴 N4 — `bunker.html`: **3%** IN 7 LINGUE (conferma di B16 a, con le righe esatte)

- **Dove:** `deploy/bunker.html:215` (en), `:216` (es), `:217` (fr), `:218` (de), `:219` (pt),
  `:220` (ja), `:221` (zh) — chiave `ct_h`.
- **Cosa dice:** *«Stripe technical fee (3%) and losses»* e traduzioni.
- **Cosa fa il codice:** 5% + 0,25 €. L'italiano `:214` è **corretto**
  (*«Tariffa tecnica Stripe (5% + 0,25 €)»*), come il markup statico `:183`.

### 🔴 N5 — `kit-marketing.html`: **3% fisso** IN 7 LINGUE (conferma di B16 a)

- **Dove:** `deploy/kit-marketing.html:128` (en), `:129` (es), `:130` (fr), `:131` (de),
  `:132` (pt), `:133` (ja), `:134` (zh) — chiave `box2`.
- **Cosa dice:** *«a **fixed 3% technical fee** on the transaction amount»*.
- **Cosa fa il codice:** 5% + 0,25 €, e **7% + 0,25 €** in valuta estera — che l'italiano `:127`
  dice e le altre 7 lingue **tacciono**.
- ⛔ È il **kit che gli host copiano e incollano**: il numero sbagliato viene ripubblicato da loro.

> **Totale delle promesse «3%» vive oggi: 23** (9 in `diventa-host.html` · 7 in `bunker.html` ·
> 7 in `kit-marketing.html`). Contate con `grep -c "3%"`, escluse le righe che parlano di terzi
> (`commissioni.html:58,61,62`).

### 🔴 N6 — IL REFERRAL PROMETTE **10 € + 40 € DOPO 3 PRENOTAZIONI**. IL MOTORE DÀ **10 € ALLA PRIMA**.

- **Dove:** `deploy/host.html:503` (it) e `:504` (en), chiave `ref_p`.
- **Cosa dice:** *«il nuovo host riceve subito **€10** di benvenuto, e tu ricevi **€40** di
  credito quando lui riceve le sue **prime 3 prenotazioni**»*.
- **Cosa fa il codice:**
  - `fase109_referral_host.py:23` → `TIERS_DEFAULT = ((3, 1000), (9, 1500), (10**9, 2000))`
    = **10 € / 15 € / 20 €** al **referrer**. Il **40 € non esiste**.
  - `fase109:84-95` `conferma_qualifica()` → scatta alla **prima** prenotazione, non alla terza.
  - **Nessun credito di benvenuto al referee**: in tutto il modulo l'unico accredito è
    `crediti[referrer] += bonus` (`:93`).
  - `fase81_bootstrap_casavip.py:505` costruisce il referral **senza sovrascrivere i tiers**.

### 🟠 N7 — LA STESSA PROMESSA, IN 6 LINGUE, DICE UN'ALTRA COSA ANCORA — E ANCHE QUELLA È FALSA

- **Dove:** `deploy/host.html:173` (markup statico) e `:505` (es), `:506` (fr), `:507` (de),
  `:508` (pt), `:509` (ja), `:510` (zh).
- **Cosa dice:** *«quando un host **si registra**, **tu e lui** ricevete un credito»*.
- **Cosa fa il codice:** `fase109:73-82` `registra_referral()` **non accredita nulla**; l'accredito
  avviene solo alla prima **prenotazione** (`:84-95`) e va **solo al referrer**.
- ⛔ Sulla stessa pagina convivono **tre versioni diverse** della stessa promessa: markup statico,
  it/en, e le altre 6 lingue. Nessuna delle tre coincide col motore.

### 🟠 N8 — LA CIFRA «DEI COLOSSI» È CALCOLATA DAL **NOSTRO** TARIFFARIO

- **Dove:** `fase89_jurisdiction_outreach.py:253` e `:275` — `pct=_pct(_intero_bps(nostra_bps) + 500)`.
- **Cosa dice il testo:** *«poi 10% a regime, contro il **15%** e oltre di Booking e Airbnb»*
  (`fase89:219`, e in tutte e 8 le lingue).
- **Cosa fa il codice:** prende **la nostra** commissione e ci somma 5 punti. Nessuna costante,
  nessuna misura, nessuna fonte riguarda Booking o Airbnb. Se domani `COMMISSIONE_BPS` cambia,
  **cambia anche la percentuale che attribuiamo a loro**.

### 🟠 N9 — QUATTRO CIFRE DIVERSE PER GLI STESSI CONCORRENTI, NELLO STESSO PRODOTTO

| Fonte | Cosa dichiara | Lingue |
|---|---|---|
| `deploy/commissioni.html:57-58` | Airbnb **15,5%** · Booking **10–25% (media 15%)** | 8 |
| `fase69_trasparenza.py:44-49` | Airbnb **15%** · Booking **18%** | motore |
| `deploy/kit-marketing.html:69,84,103` · `deploy/diventa-host.html:98-105` | OTA **18–25%** | 8 |
| `fase90_marketing.py:88-96` | OTA **fino al 20%** | **5** (it,en,es,fr,de — mancano pt,ja,zh) |
| `fase89_jurisdiction_outreach.py:253` | **nostra_bps + 5 punti** (oggi 15%) | 8 |

- **Fonte citata:** nessuna. `deploy/commissioni.html:67` dice *«Fonti: pagine ufficiali e portali
  di settore»* senza nominarne una.
- ⚠️ Il fondatore ha già deciso (`RIPRENDI_QUI.md:758-762`) di **togliere i nomi** e scrivere
  «i grandi portali»: questa riga misura **quante cifre** dovranno sparire con i nomi, non
  riapre la decisione.

### 🟠 N10 — I NUMERI DELLA CANCELLAZIONE ESCONO **SOLO IN ITALIANO**, SU OGNI PAGINA ANNUNCIO

- **Dove:** `fase173_motore_seo.py:196-206` (`_RIPENSAMENTO_IT`, `_POLITICA_IT`) →
  `fase83_server.py:636-645` che le stampa nella FAQ **di ogni pagina alloggio**.
- **Cosa dice:** *«Entro **48 ore** dalla prenotazione (se l'arrivo è ad almeno **3 giorni**) il
  rimborso è totale… rimborso pieno fino a **30 giorni** prima, metà fino a **7 giorni**…»*
- **Cosa fa il codice:** i numeri sono **giusti** (`fase111_cancellazione.py:23-30`,
  `fase83_server.py:472`), ma `fase173:174` dichiara *«etichette in italiano (la pagina è
  lang=it)»* e `fase83:636` non passa **nessuna lingua**: un visitatore giapponese legge le
  condizioni di rimborso in italiano.
- **Lingue:** 1 su 8.

### 🟠 N11 — IL RIPENSAMENTO DI 48 ORE NON È SCRITTO IN NESSUNA PAGINA, IN NESSUNA LINGUA

- **Misura:** `grep -rn "48" deploy/*.html` → **zero** occorrenze del diritto di ripensamento.
- **Cosa fa il codice:** `fase83_server.py:472` + `:6732` concedono **100% di rimborso entro 48 h**
  se l'arrivo è ≥ 3 giorni, **vincendo su qualunque politica dell'host**, compresa
  `non_rimborsabile` (`fase111:47-50, 68-70`).
- **Conseguenza numerica:** `deploy/host.html:384` offre all'host l'opzione
  *«Non rimborsabile (prezzo più basso)»* senza dire che per 48 ore **è rimborsabile al 100%**.
  Il numero che l'ospite legge sulla pagina annuncio (N10) è in italiano; quello che l'host
  legge nel pannello non c'è.

### 🟡 N12 — IL CONTRATTO HOST HA LE CIFRE GIUSTE, MA **SCRITTE A MANO** — E IN 2 LINGUE SU 8

- **Dove:** `fase163_accettazioni.py:90-106` (IT) e `:218-231` (EN).
- **Cosa dice:** 5% · 0,25 EUR · 7% · 0% · 90 giorni · 8% · 10% · 5% diretto · penale
  disintermediazione **+50%**.
- **Verifica:** tutte **coincidono** col motore oggi (unica eccezione il **50%** di `:110-112`
  e `:234`, che **non corrisponde a nessuna costante**: cercato `50` in tutti i moduli, non
  esiste codice che applichi quella maggiorazione).
- ⛔ **Il difetto è il metodo, non la cifra:** `fase185_testi_legali.py:59-83` prende gli stessi
  numeri **dal motore** con un ripiego sorvegliato; `fase163` li ha battuti a mano. È lo stesso
  meccanismo che nel 2026-08-10 ha lasciato «4%» nei termini per un giorno intero
  (`fase185:64-69`). Qui non c'è guardia equivalente.

### 🔴 N13 — LA GUARDIA UFFICIALE È **CIECA AL 100%** SULLE PAGINE TRADOTTE

- **Dove:** `collaudi/audit_coerenza_tariffe.py:106-109` (`KW_ALTRUI` / `KW_ALTRO_NOSTRO`),
  agganciata alla batteria in `collaudi/batteria.py:163`.
- **Meccanismo:** l'audit lavora **riga per riga**, ma i dizionari i18n dei `deploy/*.html`
  tengono **l'intera pagina su una riga sola per lingua**. Basta che quella riga contenga
  *un* nome di concorrente (`booking`, `airbnb`, …) o *una* parola come `rimbors`/`penale`/`tassa`
  perché l'audit **esenti l'intera lingua**.
- **Misura (denominatore dichiarato):**
  ```
  righe-dizionario con % + parola di costo: 40
  di queste ESENTATE dalla guardia        : 40
  controllate davvero                     : 0
  ```
  (8 lingue × 5 file: `bunker.html:214-221`, `commissioni.html:96-103`,
  `diventa-host.html:98-105`, `host.html:503-510`, `kit-marketing.html:127-134`.)
- **Conferma puntuale sulle 20 righe dei difetti N3/N4/N5:** 20 su 20 → `ESENTATA`.
- ⛔ **Ecco perché B16 (a) l'ha trovato una persona e non lo strumento:** l'audit gira, esce
  verde su quelle righe, e la batteria non se ne accorge.

### 🔴 N14 — LA GUARDIA CHIEDE «C'È LA CIFRA GIUSTA?», NON «C'È UNA CIFRA SBAGLIATA?»

- **Dove:** `test_trasparenza_costi.py:385-396` (`test_le_percentuali_delle_pagine_sono_quelle_del_motore`),
  `:411-417`, `:343-351`, `:299-303`.
- **Meccanismo:** concatenano **l'intero file** e fanno `assertIn` / `assertRegex`: verificano
  che il numero **esista da qualche parte**, mai che il numero **vecchio sia sparito**, mai
  **per lingua**.
- **Prova viva:** `test_le_percentuali_delle_pagine_sono_quelle_del_motore` legge proprio
  `kit-marketing.html` + `diventa-host.html` — i due file di N3 e N5 — e **passa**, perché il
  «5%» compare nella chiave `copy`. Ventitré «3%» gli scorrono accanto.
- È la stessa famiglia di *«NON È NULLO» NON È UNA GUARDIA*: la domanda giusta non è
  «c'è qualcosa?» ma «**c'è LA COSA, e non c'è quella sbagliata?**».

### 🟡 N15 — LE GUARDIE NON VEDONO I TESTI A SEGNAPOSTO, CIOÈ PROPRIO QUELLI FATTI BENE

- **Dove:** `collaudi/audit_coerenza_tariffe.py:73` — `PERC = re.compile(r"(\d{1,3})...%")`
  pretende **cifre**.
- **Conseguenza:** i testi che usano `{tecnica}%` / `{TECNICA}%` — `fase89` (N1, il difetto
  vero) e `fase185` (l'unico modulo fatto bene) — sono **invisibili** all'audit. L'unico
  controllo sui ripieghi è `test_trasparenza_costi.py:60`, che copre **solo `fase185`**:
  nessun test confronta il ripiego di `fase89:189` con `main_casavip.py:150`.
- Nel rapporto ufficiale (`collaudi/rapporto_coerenza.txt`, rigenerato oggi) le **58 anomalie**
  trovate sono in `_archivio/`, `REGISTRO_INGEGNERIA.md`, `CLAUDE.md` e nei test. **Zero** sono
  in `deploy/`. E `baseline_tariffe.txt` contiene **66 righe già dichiarate legittime**: un
  silenziatore che nessuno rilegge.

---

## 2. VERIFICATO E CORRETTO — non rifare questi controlli

| Cosa | Esito | Dove |
|---|---|---|
| Termini e Privacy, 8 lingue | ✅ **tutte** le cifre da segnaposto, **zero** numeri letterali nei testi | `fase185_testi_legali.py:59-83`, `:99-660` |
| `termini.html` / `privacy.html` | ✅ gusci che chiamano `/api/legale/documento` — nessuna cifra propria | `deploy/termini.html:34,90` |
| Email di benvenuto host, 8 lingue | ✅ 5% + 0,25 € **e** 7% + 0,25 € in tutte | `fase86_email.py:458-465` |
| `host.html` `dir_p`, `h_prezzo_osp`, 8 lingue | ✅ 5%/10%/0,25 € corretti ovunque | `deploy/host.html:503-510` |
| Simulazione su 100 € | ✅ 100 − 10 − 5,25 = **84,75**; diretto 100 − 5 − 5,25 = **89,75** | `deploy/commissioni.html:71-79` |
| Rampa 0/8/10 e 90/365 giorni | ✅ ovunque compaia | `fase98:74-77` |
| Penale 15% + rimborso 100% | ✅ | `fase83_server.py:923-924, 6371` · `deploy/host.html:189` |
| Politiche cancellazione 30/7 · 5/1 · 24h | ✅ testo = scaglioni | `fase111:23-30` · `deploy/host.html:381-384` |
| DAC7 30 prenotazioni / 2000 € | ✅ in tutte e 8 le lingue | `fase100_dac7.py:24-25` · `deploy/bunker.html:214-221` |
| «0% all'ospite» | ✅ `nostra_guest_fee_bps = 0` | `fase125_confronto_guest.py:20` · `deploy/index.html:173` |
| Base della tariffa tecnica | ✅ `(totale × psp)/10000 + fisso` sul **totale addebitato** (tassa inclusa) — coerente con la formula del contratto *«% dell'importo della transazione»* | `fase59_concierge.py:348-350` · `fase163:90` |
| Campagna persuasiva it/en | ✅ 5% + 0,25 € / EUR 0.25 | `fase200_campagna_persuasiva.py:61-65, 117-126` |

---

## 3. FALSI POSITIVI DEL MIO STRUMENTO — dichiarati per non farli ricontrollare

Il confronto fra lingue l'ho fatto con un estrattore scritto per questo passaggio
(`scratchpad/estrai_i18n.py`, fuori dal progetto). Ha segnalato 5 divergenze che **non** sono difetti:

1. `deploy/bunker.html:215` chiave `conf_p` — il mio regex ha letto `€2,000` (separatore delle
   migliaia inglese) come «2,00 €». Il testo è corretto in tutte e 8 le lingue.
2. `deploy/diventa-host.html:99,104,105` chiave `copy`; `deploy/host.html:504,509,510` chiavi
   `dir_p`, `h_prezzo_osp`, `co_*` — dicono `EUR 0.25`, `0,25 ユーロ`, `0,25 欧元`: il mio regex
   cercava solo il simbolo `€`. **Testi corretti.**
3. `deploy/privacy.html` e `deploy/termini.html` risultavano a 7 lingue: il giapponese c'è
   (`termini.html:58`), su più righe, e il mio parser leggeva una riga sola. **Nessun difetto**
   (e comunque quei due file non contengono cifre di costo).

⛔ **E un limite del metodo, non dello strumento:** il confronto fra lingue trova solo ciò che
**diverge**. N3 — «3%» in **tutte** e 8 — è passato invisibile e l'ho trovato solo cercando
`grep -c "3%"` a mano. È lo stesso identico buco di N14: *concordi* non vuol dire *veri*.

---

## 4. COSA È RIMASTO FUORI (D18 punto 3)

1. **Il VPS non è stato interrogato.** `PAGAMENTO_BPS`, `PAGAMENTO_BPS_ESTERA`,
   `PAGAMENTO_FISSO_CENTS`, `PAGA_STRUTTURA_ATTIVO` li ho letti **solo** dai default del codice
   e da `DEPLOY.md:227`. Sul server le variabili d'ambiente **vincono sul codice**: se qualcuno
   ha impostato `PAGAMENTO_BPS`, **N1 cambia di forma** e va rimisurato in SSH.
2. **`PAGA_STRUTTURA_ATTIVO`**: il codice ha default `"0"` (`fase83_server.py:5320, 6941, 7528`),
   la memoria lo dà **acceso** in produzione. Non l'ho verificato. Se è acceso, l'ospite che
   sceglie «paga in struttura» paga **1,50 €/notte** (`fase188_paga_struttura.py:35`) mentre 8
   lingue promettono *«0% all'ospite»*: è una **quota fissa**, non una percentuale, quindi la
   frase resta letteralmente vera — ma la coppia va guardata da chi decide.
3. **Non ho aperto a mano** `deploy/admin.html`, `partner.html`, `grazie.html`, `annullato.html`:
   la scansione automatica non vi ha trovato cifre di costo. `guida-operativa.html` sì (8 lingue,
   nessuna divergenza numerica).
4. **`_archivio/` escluso di proposito**: 18 delle 58 anomalie del rapporto ufficiale stanno lì e
   sono documenti storici, non prodotto.
5. **Numeri non-tariffari non guardati**, perché non sono promesse al cliente: prezzi dinamici
   (`fase106:26-27`, ±15%), fedeltà (`fase137:23`), coda (`fase67:79-80`), POI (`fase171:89`).
6. **JS e PWA fuori da `deploy/*.html` non scansionati** per il confronto fra lingue.
7. **Nessuna suite eseguita.** L'unico programma lanciato è `collaudi/audit_coerenza_tariffe.py`,
   che è una **misura** in sola lettura: scrive solo la propria uscita
   (`collaudi/rapporto_coerenza.txt`, ignorata da git — `.gitignore:120`). `git status` dopo il
   passaggio mostra gli stessi 3 file già modificati prima di iniziare
   (`CLAUDE.md`, `RIPRENDI_QUI.md`, `deploy/index.html`) e nient'altro.
8. **Non ho riparato niente**, come prescrive B19.

---

## 5. IL FILO CHE LEGA TUTTO

Tredici delle quindici incongruenze stanno in **testi tradotti** o in **ripieghi**. Non è un caso:
sono i due posti dove la sorveglianza non arriva. **N13** dice che l'audit ufficiale esenta
**40 righe su 40** delle pagine tradotte; **N14** dice che i test chiedono la presenza del numero
giusto invece dell'assenza di quello sbagliato; **N15** dice che i testi a segnaposto — cioè quelli
scritti bene — sono invisibili a entrambi.

Il prodotto è quasi sempre giusto. **A essere cieca è la sorveglianza**, esattamente come per la
tariffa tecnica nei sei posti.
