# B19 — PASSAGGIO 2 · LE PROMESSE FUNZIONALI CONTRO QUELLO CHE IL CODICE FA DAVVERO

> **Referto di misura, non lista di cose da fare.** Sola lettura: nessun file di prodotto è
> stato toccato, nessuna suite eseguita, nessun commit.
> Misurato il **2026-08-24**, su `HEAD = 584f0e9`.
> Perimetro: **non i numeri — i verbi.** «i soldi tornano», «ricevi i bonifici», «il sistema
> alza il prezzo da solo», «alloggi certificati». Per ognuna: **esiste il codice che la
> mantiene?**

**Denominatore dichiarato.** Esaminate **364** stringhe del dizionario italiano dei
`deploy/*.html` (chiavi con testo > 25 caratteri) più **68** stringhe della UI ospite in
`fase83_server.py:150-320`, più i template di `fase86_email.py`, `fase89_jurisdiction_outreach.py`,
`fase200_campagna_persuasiva.py`, `fase90_marketing.py`. Di queste, quelle che **affermano un
comportamento verificabile** sono state seguite fino al codice.

---

## 1. PROMESSE SENZA CODICE — 15

### 🔴 P1 — «ALLOGGI CERTIFICATI»: NON ESISTE NESSUNA CERTIFICAZIONE

- **Dove:** `fase83_server.py:168` (chiave `hero_sub`, **8 lingue**) → stampato in chiaro su
  `deploy/index.html:170`, **il primo rigo che legge ogni visitatore**.
- **Cosa dice:** *«**Alloggi certificati** · paghi il prezzo pulito · cancellazione gratuita»* ·
  *«Certified stays…»*.
- **Cosa fa il codice:** **niente.** `grep -rn "certificat"` su tutti i `fase*.py` e su
  `deploy/` non trova **nessuna** verifica, ispezione o marchio applicato a un alloggio: gli
  unici usi della parola sono l'estratto contabile certificato (`fase177:509`) e le marche
  temporali (`fase184`), che riguardano i **registri**, non le case.
- L'unica verifica che esiste è sull'**host** (KYC Stripe, `fase105`) e il **CIN** per l'Italia:
  nessuna delle due dice niente sull'alloggio.
- ⛔ **È la famiglia di B8**, sulla stessa pagina e con lo stesso peso: una qualità dichiarata a
  ogni visitatore, in 8 lingue, che nessuna riga di codice produce.

### 🔴 P2 — «CANCELLAZIONE GRATUITA» PROMESSA SENZA CONDIZIONI, MENTRE L'HOST PUÒ ESCLUDERLA

- **Dove:** stessa riga `fase83_server.py:168` → `deploy/index.html:170`, **8 lingue**, in testa
  alla homepage, **senza nessuna condizione**.
- **Cosa fa il codice:** l'host sceglie la politica (`deploy/host.html:381-384`), e una delle
  quattro è **`non_rimborsabile`** → `((0, 0),)`, rimborso **zero**
  (`fase111_cancellazione.py:29`). Anche `rigida` non è gratuita sotto i 7 giorni (`:28`).
- ⛔ **E la stessa applicazione sa già come dirlo bene:** a `deploy/index.html:402` il badge
  «Cancellazione gratuita» compare **solo se** `a.cancellazione_gratuita` è vero, per
  quell'alloggio. La versione onesta e quella falsa convivono nella stessa pagina: la
  condizionata sulla scheda, l'incondizionata nel titolo.

### 🔴 P3 — «CLASSE FONDATRICE · TARIFFA BLOCCATA»: NESSUN CODICE, E LA TARIFFA **SALE**

- **Dove:** `deploy/kit-marketing.html:53` (`box1`, *«classe fondatrice (tariffa bloccata)»*),
  `:103` (`msg3`, *«Ti blocco la tariffa da fondatore»*), `msg1` e `msg2`
  (*«Chi entra ora blocca la tariffa agevolata»*) — **8 lingue** · e
  `fase89_jurisdiction_outreach.py:219` (*«la classe fondatrice di Roma: chi entra adesso resta
  il primo»*), **8 lingue**.
- **Cosa fa il codice:** `fase98_policy_commissione.py:20-21` dichiara che la vecchia regola
  ordinale «primi 1000» è **mantenuta ma NEUTRA**, e `commissione_bps_fonte` (`:70`) passa lo
  **stesso valore** come `bps_fondatori` e `bps_dopo`: l'ordinale non può cambiare nulla.
- **Misura fatta adesso:**
  ```
  host n.1  marketplace: 1000 bps
  host n.5000 marketplace: 1000 bps
  legacy ordinale n.1: 1000   n.5000: 1000
    giorni    0 ->     0 bps (promo)
    giorni   90 ->   800 bps (fase1)
    giorni  365 ->  1000 bps (regime)
  ```
- ⛔ **La promessa è rovesciata:** non solo la tariffa non è bloccata — è l'unica cosa che
  **cresce da sola**, da 0% a 10% in un anno, uguale per il primo host e per il cinquemillesimo.

### 🔴 P4 — «IL SISTEMA ALZA/ABBASSA IL PREZZO DA SOLO»: NESSUNO SCRIVE MAI UN PREZZO

- **Dove:** `deploy/diventa-host.html:60` (markup) e `:98-105` (chiave `c2_p`, **8 lingue**) —
  *«Il sistema alza/abbassa il prezzo da solo (domanda, stagione, weekend): guadagni di più
  **senza pensarci**»*. Ripreso da `deploy/host.html` (`dp_p`) e da `fase83_server.py:230`.
- **Cosa fa il codice:** `fase106_dynamic_pricing.calcola_prezzo` ha **due soli chiamanti**:
  `fase83_server.py:8780` (`GET /api/host/prezzo_suggerito`, sola lettura, 401 se non sei
  l'host) e `fase119_calendario_prezzi.py:104` (disegna un calendario). **Nessun chiamante
  scrive un prezzo.** `fase59_concierge` — il motore che fa il preventivo — non importa mai
  `fase106`.
- Il prezzo cambia **solo** se l'host guarda il suggerimento e lo copia a mano nel modulo.

### 🔴 P5 — «ZERO ATTESE»: I SOLDI RESTANO IN GARANZIA FINO A CHECK-IN + 24 ORE

- **Dove:** `deploy/diventa-host.html:98-105` (chiave `c3_p`, **8 lingue**) — *«I soldi arrivano
  sul tuo conto, in modo sicuro. **Zero attese**, zero intermediari nascosti»* · *«No waiting»* ·
  *«Kein Warten»* · *«待ち时间なし»*.
- **Cosa fa il codice:** la quota dell'host resta **bloccata in escrow** (`fase160`) e viene
  rilasciata solo alla conferma dell'ospite **o 24 ore dopo il check-in**, dal giro orario
  `_tick_garanzia` (`fase83_server.py:11052-11069`).
- ⛔ **E il prodotto lo dice giusto altrove, sulla stessa campagna:**
  `deploy/kit-marketing.html:51` (`num3`) → *«l'host è pagato **solo DOPO il soggiorno**»*.
  Due pagine dello stesso sito raccontano il contrario l'una dell'altra, entrambe in 8 lingue.

### 🔴 P6 — «IL CLIENTE VIENE RIMBORSATO AL 100%»: NESSUN RIMBORSO PARTE DA SOLO

- **Dove:** `deploy/host.html:189` e `:503`/`:504` (`hc_p`, `hc_conferma`) — *«il cliente viene
  rimborsato al 100%»*, detto al presente, come un fatto automatico. E l'API risponde
  `"nota": "cliente rimborsato al 100%..."` (`fase83_server.py:6431`).
- **Cosa fa il codice, nel percorso di cancellazione dell'host** (`_host_cancella`,
  `fase83_server.py:6312-6437`): libera le date, rimuove il payout, storna la tassa, revoca il
  check-in, **scrive una riga «rimborso» nel giornale** (`:6421-6426`) — e **non chiama mai
  `fase85.rimborsa()`**. Nessun centesimo lascia Stripe.
- **Chi lo chiama davvero:** solo `_admin_rimborso` (`:4470`) e `_admin_rimborsa_dovuto`
  (`:4766`), cioè **due pulsanti che deve premere una persona**.
- ⚠️ **Il meccanismo manuale è una DECISIONE, non un difetto:** `fase83_server.py:4611-4620` la
  dichiara per esteso — *«all'inizio il rimborso si fa A MANO… l'automatico si accende dopo»*.
  **Il difetto è la promessa**, che non dice mai che è manuale né entro quando.
- ⛔ E la contro-prova sta nel documento del fondatore: `deploy/guida-operativa.html:65` gli
  ordina di *«andare su Stripe → Pagamenti → Rimborsa»* a mano. Il pannello host dice al mondo
  che è già fatto.

### 🔴 P7 — «I BONIFICI STANNO PARTENDO»: IL MESSAGGIO CONTA I TENTATIVI, NON I SOLDI

- **Dove:** `deploy/host.html:1049` — mostra `fx_sbloccati` (*«i bonifici in sospeso stanno
  partendo verso il tuo conto»*) se `d.payout_riprovati > 0`.
- **Cosa fa il codice:** `fase83_server.py:3130-3137` incrementa `riprovati` **a ogni riga
  ciclata**, subito dopo aver chiamato `_trasferisci_all_host`, che è una funzione **senza
  valore di ritorno** e con **sette uscite silenziose** (`:6173-6192`): kill-switch attivo,
  Connect assente, importo non valido, prenotazione non pagata, **host senza `stripe_account_id`**,
  payout già partito.
- **Conseguenza:** un host che completa i dati fiscali **senza aver collegato Stripe** legge un
  messaggio verde che dice che i suoi soldi stanno partendo, mentre **non parte nulla**.
  È B17 che riemerge dal lato del cliente: il silenzio del codice diventa una conferma sullo schermo.

### 🟠 P8 — «BONIFICI PRIORITARI» PER L'HOST VERIFICATO+: NESSUNA PRIORITÀ ESISTE

- **Dove:** `deploy/host.html:263` (`ca_p`) — *«Aggiungendo una carta ottieni il badge 'Host
  Verificato+' e **bonifici prioritari**»*.
- **Cosa fa il codice:** `carta_collegata` compare in **un solo punto di tutto il progetto**,
  `fase83_server.py:7912`, dentro una rotta di **sola lettura** che dice al pannello se
  disegnare il badge. **Nessuna coda di payout è ordinata** per presenza della carta: i bonifici
  partono dal giro orario dell'escrow, uguali per tutti.
- Il badge esiste (`deploy/host.html:1380`). La priorità no.

### 🔴 P9 — IL «CREDITO FONDATORE» PROMESSO A OGNI VISITATORE VALE **0,00 €** AL LANCIO

- **Dove:** `fase83_server.py:187` (`empty_lascia`, **8 lingue**) e `:241` (`wl_msg_tpl`,
  **8 lingue**) — *«ricevi un **Credito Fondatore** di benvenuto per la tua prima prenotazione»*.
  Emesso a `fase83_server.py:7195`, vale `CREDITO_FONDATORE_CENTS = 500` (`fase158_domanda.py:22`).
- **Cosa fa il codice al riscatto** (`fase59_concierge.py:498-503`): lo sconto è tagliato a
  **quanto la nostra commissione può assorbire**
  (`margine_disponibile = max(0, comm - costo)`).
- **Misura fatta adesso** (annuncio in EUR, formula del modulo):

  | Prenotazione | host in promo 0% | host 8% | host a regime 10% |
  |---|---|---|---|
  | 50 € | **0,00** | 0,13 | 1,13 |
  | 100 € | **0,00** | 2,50 | 4,50 |
  | 200 € | **0,00** | 5,00 | 5,00 |
  | 500 € | **0,00** | 5,00 | 5,00 |

- ⛔ **Nei primi 90 giorni di un host la commissione è 0, quindi il credito vale ZERO a
  qualunque importo** — e i primi 90 giorni sono la condizione di **tutti** gli host al lancio
  (`fase98:74`). È **B9 su un SECONDO credito**: B9 riguardava l'Anti-Rimpianto (nato da una
  penale), questo è il credito promesso **in homepage a ogni visitatore che lascia l'email**.

### 🔴 P10 — «DASHBOARD PAYOUT, COME SEMPRE»: QUELLA DASHBOARD NON ESISTE

- **Dove:** `deploy/bunker.html:119` e le traduzioni a `:214-221` — **8 lingue**, rivolto al
  fondatore: *«Per pagare comunque a mano: dashboard payout, come sempre»*.
- **Cosa fa il codice:** in tutto `fase83_server.py` l'unica rotta payout è
  **`GET /api/host/payout`** (`:2059`), che serve **all'host** per vedere i propri. Nessuna
  pagina in `deploy/`, nessuna rotta admin. Conferma di **B16 punto (f)**, rimisurata.

### 🔴 P11 — «SENZA COLLEGAMENTO IL PAGAMENTO ARRIVA CON BONIFICO MANUALE»: QUEL BONIFICO NON È UNA FUNZIONE

- **Dove:** `deploy/host.html:503` (it) e `:504` (en), chiave `sc_p`.
- **Cosa fa il codice:** `_trasferisci_all_host` **ritorna in silenzio** quando manca
  `stripe_account_id` (`fase83_server.py:6191-6192`). **Non esiste nessuna funzione di bonifico
  in nessun modulo**: l'unica strada verso i soldi dell'host passa da
  `fase101_stripe_connect.trasferisci` (`:226-243`). Conferma di **B16 (e)** e **B17**.
- ⚠️ **E c'è un secondo strato:** la frase esiste **solo in italiano e inglese**. Le altre 6
  lingue (`:505-510`) **non hanno affatto la chiave** `sc_p`: un host spagnolo, francese,
  tedesco, portoghese, giapponese o cinese non legge nemmeno l'avvertenza sbagliata. Lo stesso
  vale per l'intero blocco commissioni (`co_h`, `co_p`, `co_n`, `co_r1`-`co_r4`, `hc_p`,
  `hc_conferma`): **presenti in 2 lingue su 8**.

### 🟠 P12 — IL REFERRAL È PROMESSO IN **TRE** VERSIONI DIVERSE, E NESSUNA È QUELLA DEL CODICE

| Dove | Cosa promette | Lingue |
|---|---|---|
| `deploy/host.html:503-504` (`ref_p`) | 10 € al nuovo host + 40 € a te dopo le sue **prime 3** prenotazioni | it, en |
| `deploy/host.html:173` + `:505-510` | credito **a tutti e due**, **alla registrazione** | markup + 6 lingue |
| `deploy/partner.html:85` (`host_p`) | credito di benvenuto all'invitato + credito a te quando incassano **le prime prenotazioni** | 8 |

- **Cosa fa il codice:** `fase109_referral_host.py:73-82` `registra_referral()` **non accredita
  nulla**; `:84-95` `conferma_qualifica()` accredita **alla PRIMA prenotazione**, **solo al
  referrer**, **10 €** al primo scaglione (`:23`). **Nessun credito di benvenuto esiste** per
  l'invitato, in nessun ramo.

### 🟠 P13 — «TI RISPONDIAMO PERSONALMENTE»: LE CANDIDATURE PARTNER NON LE VEDE NESSUNO

- **Dove:** `deploy/partner.html:85` — *«Ti rispondiamo personalmente»*, *«Candidatura ricevuta:
  ti scriviamo presto»*, **8 lingue**, su un modulo pubblico che raccoglie **dati personali con
  consenso GDPR esplicito**.
- **Cosa fa il codice:** `_partner_registra` (`fase83_server.py:7137-7152`) **salva e basta** —
  nessuna email, nessun avviso, nessuna riga di allarme. La lista si legge solo da
  `GET /api/admin/partner` (`:7154`).
- **Misura:** `grep -n "partner" deploy/admin.html deploy/bunker.html` → **zero occorrenze**.
  **Nessun pannello chiama mai quella rotta.** Una candidatura arriva, si deposita in un
  archivio, e non esiste nessuno schermo al mondo che la mostri. Stessa forma di B17: il caso in
  cui qualcuno resta in attesa per sempre è anche quello che **non lascia traccia visibile**.

### 🟠 P14 — «ANTI-RIMPIANTO: I SOLDI TORNANO COME CREDITO» (conferma di B8)

- **Dove:** `fase83_server.py:172` → `deploy/index.html:175`, **8 lingue**.
- **Cosa fa il codice:** entro 48 ore torna **denaro vero al 100%** (`fase111:68-70`) — non un
  credito; fuori finestra torna un **credito** che, per la stessa formula di P9, può valere
  **zero**. Sbaglia in tutte e due le direzioni. Rimisurato, invariato rispetto a B8.

### 🟡 P15 — «COI TASTI APPROVA/RIFIUTA»: SONO LINK IN UN MESSAGGIO DI TESTO

- **Dove:** `deploy/host.html:503` (`tg_p`) — *«gli avvisi arrivano lì **coi tasti**
  Approva/Rifiuta, e approvi al volo dal telefono»*.
- **Cosa fa il codice:** `fase152_notifiche_prenotazione.py:136-147` chiama `sendMessage` con
  **solo `text`**. **Misura:** `grep -rn "inline_keyboard|reply_markup|callback_query"` su tutto
  il progetto → **zero occorrenze**. Non esistono tasti Telegram in nessun punto.
- ⚠️ **Ma la sostanza c'è:** i link Approva/Rifiuta sono generati e spediti davvero
  (`fase83_server.py:5594-5601`), e un tocco basta. È una parola sbagliata su una funzione che
  esiste — segnata perché il passaggio misura i verbi, non l'intenzione.

---

## 2. PROMESSE VERIFICATE E MANTENUTE — non rifare questi controlli

| Promessa | Dove è scritta | Dove è mantenuta |
|---|---|---|
| «da Booking/Airbnb… titolo, prezzo, valuta, foto e disponibilità entrano da soli» | `host.html` `imp_p` | `fase77_portability.py:98-142` (adapter `da_booking`/`da_airbnb`: tutti e cinque i campi mappati) + `fase83_server.py:9141-9185` |
| «incolla il .ics: le date occupate verranno bloccate» | `host.html` `ical_p` | `fase82` (import) |
| «esporta il TUO calendario… le date si bloccano lì» | `host.html` `icex_p` | `fase135_ical_bidirezionale.py:43-60` (VEVENT RFC5545) |
| «Email e telefoni vengono oscurati automaticamente» | `host.html` `msg_p` | `fase113_messaggistica.py:27-42`, applicato a `:125` |
| «Hai 24h: oltre, la stanza si libera da sola» | `host.html` `req_p` | `sweep_hold_una_passata` (`fase83_server.py:10417-10452`) + thread a `:11073` |
| «dopo 24 ore senza problemi i tuoi soldi partono da soli» | `host.html` `sc_p` | `_tick_garanzia` (`fase83_server.py:11052-11069`) — **se** Stripe è collegato (vedi P11) |
| «si sbloccano da soli appena completano i dati» (HOLD DAC7) | `bunker.html` `conf_p` | `fase83_server.py:3126-3137` (ritenta i `maturato`) — **ma vedi P7** sul messaggio |
| «La tua recensione **verificata** è pubblicata» | `fase83_server.py:255` | `fase63_recensioni.py:14, 181-186` (token del soggiorno obbligatorio; media solo su `verificata=1`) |
| «Congela subito tutti i movimenti di denaro» | `bunker.html` `ks_p` | `_transazioni_bloccate` su prenotazione (`:5188`), rimborso (`:4370`), bonifico (`:6173`), carta (`:6943`) |
| «l'ora datata da un'Autorità QUALIFICATA europea» | `bunker.html` `mt_p` | `fase184_marca_temporale.py` (RFC 3161, OID QcCompliance a `:83`) |
| «se una riga fosse manomessa la firma non torna» | `bunker.html` `pl_p` | `fase163_accettazioni.py` (HMAC-SHA256) |
| «il numero arriva dalla stessa funzione che addebita» | `bunker.html` `sc_p` | vero: `fase98.stato_scaglione` è chiamata sia da `fase81:266` (addebita) sia dalla vetrina |
| «Riceverai a breve un'email con il voucher» | `grazie.html` `p2` | `fase83_server.py:5497-5533` (`corpo_voucher_html`, invio in thread) |
| «Check-in autonomo: mostra questo codice alla serratura» | `fase83_server.py:238` | **stringa spenta**: `MOSTRA_PASS_SERRATURA = False` (`:920`), mai stampata (`:986-987`). Nessuna promessa fatta |
| «l'ospite vede la zona, l'indirizzo esatto solo dopo la prenotazione» | `host.html` `h_indirizzo` | il dettaglio pubblico non espone l'host né l'indirizzo (documentato in `fase81:271-273`) |

---

## 3. LIMITI DEL MODO DI LAVORARE — dichiarati

1. **Ho seguito le promesse fino al codice, non fino al comportamento.** Dove il codice esiste,
   ho verificato che sia **raggiungibile e chiamato**, non che funzioni sotto carico: quello è
   lavoro della batteria, che questo passaggio non esegue.
2. **Il confronto fra lingue non è l'oggetto di questo passaggio.** Le assenze annotate (P11)
   sono emerse per strada e appartengono al **passaggio 6**.
3. **Le promesse dei documenti legali** (`fase185_testi_legali.py`, 8 lingue) le ho lette solo
   per le cifre nel passaggio 1: i **verbi** dei Termini e della Privacy — diritti dell'interessato,
   tempi di risposta, cancellazione dei dati — **non sono stati verificati** e meritano un giro a sé.
4. **`deploy/guida-operativa.html` non è una promessa al cliente**: è il manuale del fondatore.
   L'ho usato come **contro-prova** (P6), non come fonte di difetti.
5. **`deploy/admin.html`** l'ho guardato solo per la ricerca su «partner» (P13): le sue promesse
   operative non sono state esaminate una per una.
6. **Non ho interrogato il VPS.** Le rotte e i thread li ho letti nel codice; non ho verificato
   che sul server girino davvero (per esempio se `_tick_garanzia` sia vivo nel container).
7. **Nessuna suite, nessun comando di scrittura.** L'unico programma eseguito è stato Python in
   sola lettura per misurare `stato_scaglione`, `commissione_bps_fonte` e la formula del credito.
   `git status` dopo il passaggio mostra gli stessi 3 file già modificati prima di iniziare
   (`CLAUDE.md`, `RIPRENDI_QUI.md`, `deploy/index.html`) più `collaudi/audit/`.
8. **Non ho riparato niente**, come prescrive B19.

---

## 4. IL FILO CHE LEGA TUTTO

Le quindici promesse cadono in **tre famiglie**, e sono famiglie diverse da quelle del passaggio 1.

**a) La qualità dichiarata che nessuno produce** (P1, P3, P8): «certificati», «tariffa bloccata»,
«bonifici prioritari». Non sono numeri sbagliati — sono **sostantivi senza referente**. Nessuno
strumento può accorgersene, perché non c'è niente da confrontare: la parola non punta a nulla.

**b) Il verbo al presente su un lavoro che deve fare una persona** (P6, P7, P13): «viene
rimborsato», «stanno partendo», «ti rispondiamo». Qui il codice fa **metà** del lavoro —
calcola, registra, deposita — e la promessa racconta anche l'altra metà, quella che dipende da
qualcuno che apra un pannello. In due casi su tre **quel pannello non esiste** (P10, P13).

**c) Il beneficio che il motore annulla più a valle** (P9, P14): il credito è emesso davvero, ed è
davvero di 5 €. Poi, quattrocento righe più in là, una formula lo taglia a zero proprio per gli
utenti a cui è stato promesso. **La promessa e la sua smentita non si toccano mai**: chi legge
l'una non vede l'altra.

⛔ **E il filo comune con B17:** ovunque una promessa non venga mantenuta, il codice **non grida**.
Ritorna in silenzio (P7, P11), scrive una riga di giornale che nessuno legge (P6), deposita in un
archivio che nessun pannello apre (P13). Non manca la strada: manca **chi dice che non è stata
percorsa**.
