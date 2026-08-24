# B19 — PASSAGGIO 7 · TUTTI I VALORI SCRITTI A MANO NEL CODICE CHE DOVREBBERO STARE IN UN POSTO SOLO

> **Referto di misura, non lista di cose da fare.** Sola lettura: nessun file di prodotto è
> stato toccato, nessuna riparazione fatta, nessuna suite eseguita, nessun commit.
> Misurato il **2026-08-25**, su `HEAD = 584f0e9` (`git status --porcelain`: modificati
> `CLAUDE.md`, `RIPRENDI_QUI.md`, `deploy/index.html` + la cartella non tracciata
> `collaudi/audit/`; **nessun `fase*.py` toccato, nessun file sotto `deploy/` toccato**).
>
> Perimetro, come lo definisce il passaggio: **lo stesso valore scritto a mano in più posti.**
> ⛔ E la regola in più di questo passaggio: **il referto dice DOVE dovrebbe stare l'unico
> posto**, non solo dove sono le copie. Per ogni voce qui sotto c'è una riga
> «**l'unico posto**» con `file:riga`.

---

## RISULTATO IN UNA RIGA

**20 valori sparsi** — 🔴 **6 gravi** · 🟠 **11 medi** · 🟡 **3 minori** — più **6 sospetti
verificati e scartati** (scritti apposta perché non si riaprano) e **3 voci al confine col
passaggio 8**, segnalate e **non contate**.

🔑 **La forma di famiglia, e non è quella che mi aspettavo.** In questo prodotto **l'unico
posto quasi sempre ESISTE GIÀ**. Su 20 voci, in **17** la fonte unica è scritta, commentata e
funzionante: `ConfigCasaVIP` per i soldi, `fase98` per la rampa, `fase99.esponente()` per le
valute, `fase61.LINGUE_SUPPORTATE` per le lingue, `fase23_datastore` per SQLite, `BV.money`
in `deploy/app.js`. **Il difetto non è l'assenza della fonte: è che la fonte non è quella che
la produzione raggiunge.** Si rompe in tre modi, e li ho contati:

| come si rompe | voci | esempio più caro |
|---|---|---|
| la fonte unica è **completa ma in un modulo che la produzione non raggiunge mai** | 2 | `fase23_datastore.py:146-152` — la ricetta SQLite intera, **mai raggiunta**; 62 aperture a mano nei 32 moduli vivi |
| la fonte unica è **viva, e i consumatori la riscrivono invece di chiederla** | 13 | `deploy/app.js` si dichiara «FONTE UNICA» a `:1`, e 4 pagine riscrivono la formattazione del denaro **37 volte** |
| la fonte unica è viva e **la guardia che la sorveglia copre solo una parte** | 5 | `test_trasparenza_costi.py:60` confronta `tecnica` ed `estera` con `main`, **mai `fisso`** |

💡 Il corollario pratico: **queste 20 voci non si riparano scrivendo una costante.** La
costante c'è. Si riparano **collegando** — è la regola #23 del regolamento, «COSTRUITO ≠
COLLEGATO», che qui si presenta per la seconda volta in tre passaggi.

---

## DENOMINATORE DICHIARATO

Cosa contiene la produzione (`Dockerfile.casavip:25-27`: `COPY main_casavip.py`,
`COPY fase*.py`, `COPY deploy`; `CMD python main_casavip.py`):

| grandezza | numero | come è stata misurata |
|---|---|---|
| moduli di produzione | **152** | `main_casavip.py` + 151 `fase*.py` |
| righe di produzione (solo `.py`) | **50.915** | `cat fase*.py main_casavip.py \| wc -l` |
| pagine servite | **14** | `ls deploy/*.html \| wc -l` (+ `deploy/app.js`, 226 righe) |
| moduli **raggiungibili** da `main_casavip.py` | **93** | grafo degli import (AST + import dinamici da stringa), script di sessione |
| moduli **mai raggiunti** | **59** | idem — **riproduce esattamente il numero dei passaggi 4 e 5**, con uno scanner scritto oggi |
| letterali **numerici** nel codice di produzione | **5.119** (281 distinti) | scanner AST di sessione, escluse le docstring |
| letterali **stringa** nel codice di produzione | **24.175** (8.993 distinti) | idem |
| numeri **presenti in ≥2 file distinti** (esclusi i banali 0/1/2/…/1024) | **86** | idem, raggruppati per valore |
| stringhe **presenti in ≥2 file distinti** | **1.134** | idem |

### Come sono stati cercati i valori sparsi, e con tre attrezzi diversi

1. **Scanner AST** su tutti i 152 moduli: ogni `ast.Constant` registrato con
   `file:riga:contesto`, docstring escluse, poi raggruppato per valore e filtrato su
   «compare in ≥2 file». Ha prodotto i **86 numeri** e le **1.134 stringhe** del denominatore.
   ⚠️ **Da solo non basta**, ed è la lezione del passaggio: il grezzo è dominato da rumore
   (codici HTTP `401` in 7 file, `10000` denominatore dei bps in 20, chiavi di dizionario
   come `'stato'` in 27). Delle 86+1.134 candidate, **le voci vere sono 20**.
2. **Setaccio semantico per famiglia** (`grep -rIn` mirato): tariffa tecnica, rampa di
   commissione, penale, quota fissa, valuta, lingue, dominio, endpoint Stripe, percorsi
   degli archivi, PRAGMA di SQLite, formattazione del denaro. È quello che ha stanato le
   voci **1, 2, 3 e 5** — cioè le più gravi — perché le copie **non hanno lo stesso valore**
   e quindi lo scanner per valore non le vedeva vicine.
3. **Incrocio col grafo di raggiungibilità.** Ogni volta che ho trovato una fonte unica ho
   chiesto: *la produzione ci arriva?* È l'unica domanda che separa «c'è una fonte unica» da
   «c'è una fonte unica **che serve a qualcosa**». Ha capovolto la voce 2.

---

## 🔴 LE SEI GRAVI

### 1. La tariffa tecnica ha **quattro ripieghi scritti a mano in quattro file, con tre valori diversi**

| dove | riga | valore | cosa dichiara |
|---|---|---|---|
| `main_casavip.py` | `:150-152` | **500 / 700 / 25** | il valore vero che parte in produzione |
| `fase185_testi_legali.py` | `:71,75,76` | 500 / 700 / 25 | rilegge **da sé** `PAGAMENTO_BPS` per scrivere i termini in 8 lingue |
| `fase185_testi_legali.py` | `:83-84` | 5 / 7 / «0,25» | **terzo** ripiego, nel ramo `except` |
| `fase89_jurisdiction_outreach.py` | `:189` | **400** | l'email di reclutamento (già trovato dal **passaggio 1**) |
| `fase188_paga_struttura.py` | `:64` e `:87` | **300** | **nuovo: non lo aveva contato nessuno** |

**L'unico posto:** `fase81_bootstrap_casavip.py:52-54` (`ConfigCasaVIP.psp_bps`,
`psp_bps_valuta_estera`, `psp_fisso_cents`), riempito da `main_casavip.py:150-152` e passato
al motore a `fase81_bootstrap_casavip.py:325-327`. **Nessun altro modulo dovrebbe leggere
`PAGAMENTO_BPS` dall'ambiente.** Oggi lo leggono in tre (`fase185:71`, `fase89:189`,
`main:150`), e sul VPS le variabili d'ambiente **vincono sul codice**: basta impostarne una e
i tre ripieghi restano quelli che erano.

⛔ **Il pezzo nuovo, e fa un danno preciso.** `fase188_paga_struttura.calcola()` dichiara
`psp_bps: int = 300` (`:64`) e lo ribadisce a `:87` (`max(0, _intero(psp_bps, 300))`).
**Nessuno dei due chiamanti lo passa**: `fase83_server.py:5341` e `fase83_server.py:7536`
chiamano `_ps.calcola(...)` con `valuta_estera=` e basta. Quindi in produzione — dove
`PAGA_STRUTTURA_ATTIVO=1` è **acceso** — vale **300**. Conseguenza misurata sul codice:
`_gw()` a `:98-100` restituisce `max(minimo, per_stripe, per_psp)` con
`per_stripe = 55 + addebito·325/10000` e `per_psp = addebito·300/10000`; **3% è sempre minore
di 3,25% + 0,55**, quindi il ramo `per_psp` **non scatta mai**. Il commento due righe sopra
(`:96-97`) promette «*mai sotto la tariffa tecnica psp*»: **quella promessa oggi è inerte.**
Col valore vero (500) scatterebbe sopra un anticipo di **31,43 €**
(`175·a/10000 > 55 → a > 3.142,8 centesimi`). ⚠️ Non è una perdita dimostrata su una
prenotazione vera: è **una garanzia scritta nel file e disattivata da una copia del numero**.

### 2. La ricetta di apertura di SQLite è copiata **62 volte nei moduli vivi**, e la copia completa sta dove la produzione non arriva

**L'unico posto:** `fase23_datastore.py:146-152` (`_connect_raw`) — `timeout=30.0`,
`isolation_level=None`, `row_factory=Row`, `PRAGMA busy_timeout=30000`,
`PRAGMA synchronous=NORMAL`, `PRAGMA foreign_keys=ON`, più `journal_mode=WAL` una volta sola
alla creazione (`:138-143`) e `BEGIN IMMEDIATE` a `:154`. È completo, è commentato, è il
«seam di persistenza BLOCCO 1».

⛔ **`fase23_datastore` è MAI RAGGIUNTO dalla produzione** (grafo degli import, riprodotto
oggi). I suoi unici tre utenti — `fase15_idempotency.py:34`, `fase16_outbox.py:46`,
`fase33_persistenza.py:35` — **sono anch'essi mai raggiunti**. Quindi **zero** delle
connessioni che la produzione apre davvero passa dalla fonte unica.

Cosa apre invece la produzione, contato sui **32 moduli vivi** che chiamano `sqlite3.connect`
(**62 chiamate**):

| impostazione | moduli vivi che ce l'hanno | su |
|---|---|---|
| `journal_mode=WAL` | **30** | 32 |
| `PRAGMA busy_timeout` | **1** (`fase184_marca_temporale.py:547`) | 32 |
| `PRAGMA synchronous` | **1** (`fase163_accettazioni.py:403`) | 32 |
| `PRAGMA foreign_keys` | **1** (`fase177_financial_controller.py:125`) | 32 |
| `BEGIN IMMEDIATE` | **21** | 32 |

I due vivi **senza WAL**: `fase178_watchdog.py`, `fase199_invarianti.py`.
⚠️ `timeout=` sulla `connect` c'è su 45 chiamate su 83 e attenua il problema del
`busy_timeout` mancante, ma non lo sostituisce (è il timeout della singola connessione, non
il comportamento del lock). **Nota di misura:** ho contato *quali impostazioni ci sono*, non
ho riprodotto un lock né misurato una perdita: la voce è grave per la **divergenza fra 32
copie**, non per un guasto osservato.

### 3. `deploy/app.js` si dichiara «FONTE UNICA» — e la formattazione del denaro è riscritta a mano **37 volte**

`deploy/app.js:1-8` dice, testualmente: *«FONTE UNICA (Single Source of Truth)… Prima ogni
pagina aveva la SUA copia (3 tabelle valute, 5 funzioni di escape…): copie = divergenza
garantita»*. E la fonte **c'è ed è giusta**: `BV.VALUTE` (`:62-80`, 30 valute con
l'esponente), `BV.valExp` (`:81`), `BV.valSym` (`:82`), `BV.money` (`:83`),
`BV.toCents`/`BV.fromCents` (`:84-85`).

**L'unico posto:** `deploy/app.js:83` (`BV.money`). Misurato pagina per pagina:

| pagina | usi della fonte unica | copie a mano `/100).toFixed(...)` | carica `app.js` |
|---|---|---|---|
| `index.html` | **19** (`:291` `const money = BV.money`) | 5 | sì |
| `host.html` | **5** (`:561` `const fmt = BV.money`) | **14** | sì |
| `admin.html` | **1** (`:254` `const money = BV.money`) | 4 | sì |
| `bunker.html` | **0** | **14** | sì (usa solo `esc`/`occhielli`) |

⛔ **La forma più insidiosa: la fonte è importata in cima e poi ombreggiata da una copia
privata più in basso, nello stesso file.** `admin.html:254` alias `money = BV.money`, e poi
`:447` definisce `auEur()` e `:638` definisce `const eur = c=>'€'+((c||0)/100).toFixed(2)`.
Stessa cosa in `host.html:1258` e `:1440`, e in `bunker.html:495`.

**Cosa costa.** Le copie fanno due assunzioni che la fonte non fa: **`/100`** (esponente 2) e
**il simbolo `€` cablato**. Su un annuncio in **JPY, KRW, VND o CLP** — esponente 0 per
`fase99_multicurrency.py:31-32` e per `BV.VALUTE` stesso — un importo mostrato dalle copie
è **cento volte più piccolo del vero** ed è etichettato in euro. Le pagine colpite includono
`bunker.html:273,344,346,390-395,434` — cioè **la sala di controllo del fondatore**: debiti
host, payout fermi, riconciliazione Stripe↔giornale, tariffa tecnica.
⚠️ **Non ho riprodotto la schermata**: affermo la struttura (divisione per 100 fissa e `€`
fisso in 37 punti), non un errore osservato su un annuncio vero. Oggi nessun annuncio in
valuta a esponente 0 è stato contato — è **latente**, e diventa vero il giorno del primo host
giapponese o vietnamita.

Il server, per confronto, **ce l'ha giusto**: `fase83_server.py:7552-7562` (`_fmt_importo`)
chiede l'esponente a `fase99`. La strada di riparazione più corta è quindi **far tornare
dall'API l'importo già formattato**, non aggiungere una trentottesima copia.

### 4. L'elenco delle **8 lingue** è scritto a mano in 4 tuple Python + 1 array JS, in due ordini diversi

| dove | riga | contenuto |
|---|---|---|
| `fase61_localizzazione.py` | `:41` `LINGUE_SUPPORTATE` | `("en","it","es","fr","de","pt","ja","zh")` |
| `fase63_recensioni.py` | `:46` `LINGUE_NOTE` | `("en","it","es","fr","de","pt","ja","zh")` |
| `fase185_testi_legali.py` | `:35` `LINGUE` | `("it","en","es","fr","de","pt","ja","zh")` — **ordine diverso** |
| `fase198_blog.py` | `:23` `BLOG_LINGUE` | `("it","en","es","fr","de","pt","ja","zh")` — **ordine diverso** |
| `deploy/index.html` | `:277` `SUPP` | `['it','en','es','fr','de','pt','ja','zh']` |

**L'unico posto:** `fase61_localizzazione.py:41` — è già quello che il server importa
(`fase83_server.py:41`) e che l'API delle lingue restituisce (`fase59_concierge.py:620-621`).
Le altre quattro sono copie. L'ordine diverso non è cosmetico: in tre di questi elenchi il
**primo elemento è il ripiego** quando la lingua richiesta non c'è.

⚠️ E l'elenco **non è l'unico posto dove le 8 lingue vivono**: ci sono anche 26 dizionari
lingua-per-lingua (contati dal **passaggio 6**), che sono *dati*, non copie di una costante.
Qui conto solo gli **elenchi**.

### 5. La chiave `'lang'` è scritta a mano **13 volte**, e una pagina ne usa un'altra

`localStorage` è dove ogni pagina ricorda la lingua scelta. Contato con
`grep -rIno "localStorage.\(get\|set\)Item(['\"][a-z_]*['\"]"` su `deploy/`:

- **12 pagine + `app.js`** usano la chiave `'lang'`, scritta a mano ogni volta
  (`admin:799` · `annullato:51` · `bunker:224,672` · `commissioni:106,110` ·
  `diventa-host:109,137` · `grazie:51` · `guida-operativa:136,140` · `host:1562` ·
  `index:347` · `kit-marketing:137,141` · `privacy:69,88` · `termini:69,88` · `app.js:98`).
- 🔴 **`deploy/partner.html:100` e `:103` usano `"bv_lang"`.** È l'unica pagina che scrive in
  un cassetto diverso: **chi sceglie una lingua su partner.html non la ritrova da nessun'altra
  parte, e viceversa.**

**L'unico posto:** `deploy/app.js:96-102` (`BV.linguaIniziale`), che già incapsula chiave +
lingua del browser + ripiego. Lo usano **3 pagine** (`admin`, `host`, `index`). Le altre
quattro riscrivono una `pick()` propria — e **il ripiego finale non coincide**: `'it'` in
`bunker.html:224` e `guida-operativa.html:136`, `'en'` in `commissioni.html:106`,
`kit-marketing.html:137`, `grazie.html:52`, `annullato.html:52`, `privacy.html:70`,
`termini.html:70`, e di nuovo `'it'` in `contratto-host.html:48` e `partner.html:100`.
**Otto pagine su quattordici non caricano nemmeno `app.js`.**

### 6. `"EUR"` è scritto a mano come ripiego **84 volte in 13 moduli**

`grep -rIno 'or "EUR"|, "EUR")|"EUR").upper'` sui 152 moduli → **84 occorrenze** in
`fase119`, `fase139`, `fase145`, `fase162`, `fase173`, `fase177`, `fase189`, `fase190`,
`fase57`, `fase59`, `fase66`, `fase83`, `fase86`.

**L'unico posto:** `ConfigCasaVIP.valuta` (`fase81_bootstrap_casavip.py`, riempito da
`main_casavip.py:142` con `os.environ.get("VALUTA", "EUR")`). Il concierge la riceve
correttamente e la usa come riferimento (`fase59_concierge.py:348`, `self._valuta`); gli
altri 12 moduli la riscrivono. Conseguenza strutturale: **impostare `VALUTA=USD` sul VPS non
cambierebbe 84 punti su 84** — la configurazione esiste e non comanda.
⚠️ Si incrocia col **passaggio 5** («la quota fissa è un numero in euro sommato alle unità
minori di qualunque valuta»): lì il difetto era la *quota*, qui è il *codice valuta*.

---

## 🟠 LE UNDICI MEDIE

7. 🟠 **La stessa variabile d'ambiente `DB_PATH` ha due ripieghi diversi.**
   `data/marketplace.db` a `fase23_datastore.py:238` e `fase36_booking_api.py:166`;
   `data/tavolavip.db` a `fase38_backup.py:146` e `fase41_admin_panel.py:167`.
   Chi imposta `DB_PATH` una volta sola cambia **quattro moduli che si aspettavano due file
   diversi**. **L'unico posto:** i 25 percorsi stanno già tutti in `main_casavip.py:77-128`,
   uno per archivio, ciascuno con la sua variabile (`DB_FINANZA`, `DB_KYC`, …): questi quattro
   moduli sono gli unici rimasti fuori da quello schema. ⚠️ Tre dei quattro
   (`fase23`, `fase38`, `fase41`) sono **mai raggiunti** dalla produzione; `fase36` è vivo.

8. 🟠 **`COMMISSIONE_BPS` riletto dall'ambiente dentro il server, con ripiego scritto a mano.**
   `fase83_server.py:10898` e `:10938` fanno `int(os.environ.get("COMMISSIONE_BPS", "1000"))`
   — due copie del ripiego di `main_casavip.py:143`. Servono la landing di città
   (`/affitta/...`) e `llms.txt`. **L'unico posto:** `ConfigCasaVIP.commissione_bps`, che il
   router ha già. ⛔ E c'è un secondo strato: quel `1000` è la tariffa **a regime**, mentre
   chi prenota davvero paga la **rampa** di `fase98_policy_commissione.py:74-77`
   (0% → 8% → 10% per anzianità). Le pagine indicizzate da Google mostrano quindi una cifra
   piatta che per un host nei primi 90 giorni è **il triplo di quella vera**.

9. 🟠 **`data/finanza.db` riscritto dentro il server.** `fase83_server.py:3845`
   (`_os.environ.get("DB_FINANZA", "data/finanza.db")`) è una copia di `main_casavip.py:119`.
   **L'unico posto:** `ConfigCasaVIP.db_finanza`.

10. 🟠 **Il modello di costo Stripe vive in due moduli, con quote fisse diverse.**
    `fase188_paga_struttura.py:36-49`: `GATEWAY_MINIMO_CENTS=50`, `GATEWAY_FISSO_CENTS=**55**`
    (= 25 Stripe + 30 di sicurezza), `GATEWAY_BPS=325`, `GATEWAY_BPS_CAMBIO=200`.
    `fase59_concierge.py:501-502`: gli stessi numeri **in linea e diversi** —
    `_bps = 325 if … else 525` (cioè 325+200 precalcolato) e `costo = netto*_bps//10000 + **25**
    + 200`. Due file, stesso costo, **quota fissa 55 contro 25** e buffer 30 contro 200.
    **L'unico posto:** le quattro costanti di `fase188_paga_struttura.py:36-49`, che sono già
    nominate, commentate e datate («misurato il 2026-08-09 sull'API vera»).

11. 🟠 **Il dominio è scritto a mano come ripiego 24 volte.** `or "https://bookinvip.com"`
    compare **23 volte in `fase83_server.py`** e 1 in `fase97_inbound_seo.py:744`. In totale
    la stringa `bookinvip.com` è su **67 righe in 15 moduli** (dentro anche
    `fase101_stripe_connect.py:40,41,199,200` — i quattro URL di ritorno di Stripe —,
    `fase183_carta_offsession.py:46,47`, `fase135_ical_bidirezionale.py:36,38` e tre
    `User-Agent`). **L'unico posto:** `main_casavip.py:256` (`BASE_URL`) → il `base_url` del
    router (`fase83_server.py:1832`). Il ripiego dovrebbe essere **una costante sola**, non
    ripetuto a ogni uso: oggi cambiare dominio significa cambiare 24 righe e sperare.

12. 🟠 **`https://api.stripe.com/v1` scritto a mano 14 volte in 6 moduli**
    (`fase85_pagamenti_stripe.py:34,35,38,39,40` · `fase101_stripe_connect.py:19,112,113,114`
    · `fase143_kyc_host.py:181,209` · `fase181_audit_console.py:48` ·
    `fase182_riconciliazione.py:32` · `fase183_carta_offsession.py:32`). Due moduli hanno già
    fatto la cosa giusta a metà (`fase183:32 _BASE`, `fase182:32` percorso relativo).
    **L'unico posto:** una costante `STRIPE_BASE` in `fase85_pagamenti_stripe.py`, che è il
    modulo dei pagamenti e già ne dichiara cinque.

13. 🟠 **Lo sconto «non rimborsabile» è in due posti scollegati.** Il calcolo:
    `fase59_concierge.py:309`, `sconto_nr = netto * **1200** // 10000` — un numero nudo, in
    linea, senza costante. L'etichetta mostrata all'ospite: `fase83_server.py:132`, chiave
    `non_rimb`, **«−12%» ripetuto in tutte e 8 le lingue**. Nove posti per una cifra.
    **L'unico posto:** una costante accanto alle altre politiche di sconto — il catalogo
    espone già `sconto_lungo_di()` (`fase59_concierge.py:298`) e la percentuale del non
    rimborsabile è l'unica rimasta cablata.

14. 🟠 **La penale del 15% è cablata nei testi, mentre la fonte esiste e funziona.**
    **L'unico posto è giusto e vivo:** `fase83_server.py:924` `PENALE_HOST_BPS = 1500`, usato
    a `:6371` e — bene — **derivato** dai testi legali a `fase185_testi_legali.py:89-90`.
    Fuori da lì è scritto a mano: `deploy/host.html:189` (it) e `:503-504` (it/en,
    `hc_p`/`hc_conferma`), `deploy/guida-operativa.html:87` e `:126-128` (it/en/es), più
    quattro commenti (`fase177:21,652,667`, `fase183:5`, `fase83:6337`).
    ⚠️ Il **passaggio 6** ha già misurato che `host.html` in de/es/fr/pt/ja/zh ripiega
    sull'inglese: quindi la penale è dichiarata a mano in 2 lingue e mostrata in 8.

15. 🟠 **La rampa 0% / 90 giorni / 8% / 365 giorni / 10% è ricopiata a mano in ogni documento,
    e nessuno di quei moduli importa la fonte.**
    **L'unico posto è scritto e vivo:** `fase98_policy_commissione.py:74-77`
    (`LANCIO_GIORNI_GRATIS=90`, `LANCIO_BPS_FASE1=800`, `LANCIO_GIORNI_FASE1=365`,
    `LANCIO_BPS_REGIME=1000`), più `BPS_DIRETTO=500` a `:37`. **Chi la usa davvero:**
    `fase185_testi_legali.py:59-77` (che la importa — è l'esempio da imitare) e la sala di
    controllo, che dichiara esplicitamente di non ricalcolare (`fase83_server.py:3852-3856`).
    **Chi la riscrive a mano** — verificato: nessuno di questi importa `fase98` né `fase185`:
    - `fase163_accettazioni.py:98-99` (it) e `:224-225` (en) — **il contratto che vincola l'host**;
    - `fase86_email.py:458-465` — l'email di reclutamento, **in 8 lingue**;
    - `fase200_campagna_persuasiva.py:36-40,57-58,117-126,262-271` — le campagne;
    - `deploy/commissioni.html:96-103` (`cta_note`, **8 lingue**) e `deploy/diventa-host.html`;
    - `deploy/host.html:503-504` (`co_r1`…`co_r4`).
    ⚠️ Una guardia parziale esiste: `test_trasparenza_costi.py:91-108` verifica che la
    percentuale tecnica compaia in `host.html`, nei termini in 8 lingue e nel contratto it/en.
    Non copre `fase86_email.py`, `fase200`, `commissioni.html`, né i **giorni** (90/365).
    Nessun test nomina `b_commissioni` (`grep` su tutti i 406 `test_*.py` → 0).

16. 🟠 **Il divisore `100` (cents → unità) è cablato in 12 moduli e 3 pagine**, mentre la
    fonte sa che JPY vale 0 e BHD vale 3. Esempi aperti a mano:
    `fase171_cervello_seo.py:461` (`prezzo_notte_cents // 100`),
    `fase97_inbound_seo.py:237` (`"%d.%02d"`, due decimali fissi),
    `fase83_server.py:1009` (JS iniettato nella pagina del voucher:
    `(d.rimborso_cents/100).toFixed(2)+' EUR'` — **divisore e valuta entrambi cablati, sulla
    pagina che l'ospite vede dopo una cancellazione**),
    `fase185_testi_legali.py:78` (`"%d,%02d" % (fisso//100, fisso%100)`).
    **L'unico posto:** `fase99_multicurrency.py:36-39` (`esponente()`), che
    `fase83_server.py:7559-7560` già usa correttamente in `_fmt_importo`.

17. 🟠 **L'identità legale è dichiarata fonte unica e poi copiata due volte.**
    `fase185_testi_legali.py:48-55` porta il commento *«Dati del titolare: UNA sola volta,
    riusati in tutte le lingue. Se cambiano, cambiano ovunque insieme»* — ed è vero **dentro
    fase185**. Fuori: `fase83_server.py:1349-1350` riscrive ragione sociale, P.IVA e
    indirizzo nel piè di pagina servito dal motore, e `deploy/index.html:247` li riscrive una
    terza volta. **L'unico posto:** `fase185_testi_legali.py:50-55` (`GESTORE`).

---

## 🟡 LE TRE MINORI

18. 🟡 **La guardia sulla tariffa copre due terzi del valore.**
    `test_trasparenza_costi.py:60-89` toglie dall'ambiente **tutte e tre** le variabili
    (`:72-73`) e poi confronta con `main_casavip.py` solo `p["tecnica"]` (`:80`) e
    `p["tecnica_estera"]` (`:87`). **`p["fisso"]` non è mai asserito.** La quota fissa —
    il pezzo che la memoria del progetto indica come «lo stesso numero in sei posti» — è
    l'unico dei tre senza una macchina che confronti le due copie.

19. 🟡 **Il terzo ripiego di `fase185` non è sotto nessuna guardia.**
    `fase185_testi_legali.py:83-84`, nel ramo `except`, riscrive **sette numeri**
    (`giorni_promo: 90, fase1: 8, regime: 10, diretto: 5, tecnica: 5, tecnica_estera: 7,
    fisso: "0,25"`). Il test del punto 18 misura il ramo normale: quello scatta solo se
    l'import di `fase98` fallisce, quindi nessuna prova lo esercita. **L'unico posto:**
    `fase98_policy_commissione.py:37,74-77` + `ConfigCasaVIP` — e se l'import fallisce, la
    strada onesta è **non produrre il documento**, non produrne uno con numeri di scorta.

20. 🟡 **Il tempo massimo di rete è scelto a occhio, sette volte.** Su 83 `sqlite3.connect`
    e le chiamate HTTP dei 152 moduli: `timeout=30` (44), `15` (16), `10` (10), `5` (3),
    `20`, `12`, `8`. Nessuna costante, nessun criterio scritto. Il frontend, per contrasto,
    **ce l'ha in un posto solo**: `deploy/app.js:110` (`window.__TEMPO_MAX_MS || 15000`).
    **L'unico posto:** una costante per classe di chiamata (rete esterna / archivio locale).

---

## ✅ SEI SOSPETTI VERIFICATI E SCARTATI

Scritti apposta perché non si riaprano.

1. **`// 10000` in 20 moduli, 62 righe.** Non è un valore sparso: è **l'unità di misura** dei
   bps (1 punto base = 1/10000). Un'unità non si configura, si definisce. Scartato.
2. **`'PRAGMA journal_mode=WAL'`, `'BEGIN IMMEDIATE'`, `'COMMIT'`, `'ROLLBACK'` come
   stringhe ripetute.** Sono **SQL**, cioè un linguaggio, non una costante del prodotto.
   Il difetto vero non è la stringa ripetuta ma **l'insieme di pragma che diverge** — ed è
   la voce 2, contata lì e non due volte.
3. **`':memory:'` in 40 moduli.** È il ripiego dei test, ed è **sorvegliato**:
   `main_casavip.py:180-196` rifiuta di partire se un archivio di produzione è in memoria.
   La fonte unica esiste e la guardia è collegata. Scartato.
4. **Le durate di sessione diverse** (`fase83_server.py:2466` 28.800s host,
   `:9523` 43.200s admin, `fase180_bunker.py:27` 900s bunker). Sono **tre valori diversi a
   ragione** — livelli di privilegio diversi, e il più corto è una scelta dichiarata del
   fondatore. Non è lo stesso valore in tre posti. Scartato.
5. **Le chiavi di dizionario ripetute** (`'stato'` 27 file, `'errore'` 29, `'valuta'` 23,
   `'check_in'`/`'check_out'` 20-21). Sono un **protocollo fra moduli**, non un valore
   configurabile. Un protocollo si rompe se lo cambi in un posto solo, ed è proprio per
   questo che si scrive uguale ovunque. Scartato — ma vedi la nota al passaggio 8.
6. **Le 48 ore del ripensamento.** `fase83_server.py:472`
   (`SECONDI_RIPENSAMENTO = 48 * 3600`) è **l'unico posto che decide**, ed è usato da
   `_entro_ripensamento` (`:475-496`) e dall'unico chiamante (`:6732`). I «48 ore» che
   compaiono altrove (`fase111_cancellazione.py:47`, `fase173_motore_seo.py:196`) sono
   **prosa nei testi**, non calcoli. La condizione «arrivo ≥ 72 ore» è scritta una volta sola
   (`fase83_server.py:6732`, come `giorni >= 3`). Fonte unica sana. Scartato.

---

## ⚠️ TRE VOCI AL CONFINE COL PASSAGGIO 8 — segnalate, NON contate

Sono «numeri che non coincidono», che è il perimetro del **passaggio 8**. Le lascio qui
perché il passaggio 8 le trovi già misurate, e **non le sommo alle 20**.

1. `deploy/commissioni.html:58` dice Booking «10–25% (media **15%**)» e `:96-103` lo ripete
   in 8 lingue; `fase69_trasparenza.py:45` usa **18%**. È il difetto già noto (B16).
2. `fase98_policy_commissione.py:34-35` tiene ancora `HOST_BPS=200` / `GUEST_BPS=800`
   («split asimmetrico 2%/8%»), che il commento a `:4-7` dichiara **legacy e mai cablato**.
   Un valore vivo accanto a uno morto, nello stesso file: non è una copia, è un residuo.
3. `fase89_jurisdiction_outreach.py:189` (400 = 4%) contro `main_casavip.py:150` (500 = 5%):
   contato al punto **1** come *copia*, ma la sua **conseguenza** (l'email dice una cifra e
   il motore ne addebita un'altra) appartiene al passaggio 8. Già trovato dal passaggio 1.

---

## ⛔ COSA È RIMASTO FUORI (D18 punto 3)

Un taglio silenzioso fa sembrare «coperto» ciò che nessuno ha visto. Ecco i tagli, dichiarati:

1. **Non ho eseguito niente.** Nessun test, nessuna suite, nessuna chiamata all'API, nessun
   giro sul VPS. Tutto è **letto**. In particolare: la soglia dei 31,43 € al punto 1, il
   «cento volte più piccolo» al punto 3 e la landing al 10% al punto 8 sono **ricostruiti dal
   codice, non riprodotti**. Chi vorrà ripararli deve prima riprodurli.
2. **`collaudi/` e i 406 `test_*.py` non sono stati setacciati per valori sparsi**, se non
   dove servivano a rispondere «esiste una guardia?» (punti 14, 15, 18). Il perimetro del
   passaggio è la produzione. Un numero cablato dentro una guardia **non è in questo referto**
   — ed è il posto dove ha già fatto danno (`test_trasparenza_costi.py:59-63` racconta di
   quando fu proprio il file dei test a dichiarare il falso).
3. **I 59 moduli mai raggiunti sono stati guardati solo di riflesso**, quando una fonte unica
   ci finiva dentro (punti 2 e 7). Sono **12.055 righe**: dentro ci sono sicuramente altre
   copie che non ho contato, perché non toccano la produzione.
4. **Lo scanner AST salta le docstring, e le copie dentro i commenti non sono contate come
   voci.** Le nomino dove aiutano a capire (punto 10, punto 14) ma non entrano nel 20: un
   commento sbagliato è un difetto di documento, non un valore sparso.
5. **Le pagine `deploy/*.html` sono state misurate per famiglia, non lette per intero.**
   Le 14 pagine sono state contate con `grep` mirato (chiave `lang`, `/100).toFixed`,
   `BV.*`, `app.js`, tariffe); aperte davvero solo `app.js` (per intero) e i punti citati di
   `host.html`, `bunker.html`, `admin.html`, `index.html`, `partner.html`.
6. **Non ho misurato nessun cambio valutario** e non affermo nessun importo in euro. Dove
   dico «cento volte più piccolo» parlo dell'**esponente** (`fase99:31-32`), non di un tasso.
7. **Non ho aperto il VPS.** Le variabili d'ambiente lì **vincono sul codice**: tutti i valori
   citati (`PAGAMENTO_BPS=500`, `COMMISSIONE_BPS=1000`, `VALUTA=EUR`, `DB_*`) sono i
   **default del codice**, **non** ciò che gira in produzione adesso. Il punto 1 e il punto 6
   sono *più* gravi se sul VPS quei valori differiscono, non meno.
8. **Il conto «20» è di famiglie, non di righe.** Una famiglia può valere 1 riga (punto 9) o
   62 (punto 2). Il numero che conta per il lavoro non è 20: sono le colonne «dove» di ogni
   voce.
9. **Non ho riparato niente**, come prescrive B19. Nessun file di produzione toccato, nessuna
   costante spostata, nessun import aggiunto. Questo referto è l'unico file scritto.
