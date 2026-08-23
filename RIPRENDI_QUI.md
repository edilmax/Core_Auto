# 🧭 COSA MANCA — la lista è UNA SOLA, e questo è il posto

> **Riscritto da zero il 2026-08-22, per ordine del fondatore.** Prima questo file aveva
> **10.178 righe** e conteneva **sette liste diverse** di «cosa fare»: ogni sessione ne
> sceglieva una e ripartiva da un punto diverso. Il racconto di com'è andata sta in
> `REGISTRO_INGEGNERIA.md`, che è un **diario**. Qui c'è **solo cosa manca**.
>
> ⛔ **REGOLA ZERO 3:** nessun altro file — `.md`, `.py` o commento nel codice — può
> contenere elenchi di cose da fare. Lo sorveglia `test_UNA_SOLA_LISTA_DI_COSE_DA_FARE`.
>
> 🔑 **E se questo file e `collaudi/piano.py` si contraddicono, VINCE `piano.py`:**
> quello lo misura una macchina, questo lo scrive una persona.
>
> ```
> python collaudi/piano.py               <- la macchina: cosa fa e cosa manca
> python collaudi/scheda.py --blocco 1   <- il blocco su cui si lavora adesso
> ```

---

## 📏 STATO MISURATO — numeri, non ricordi

> ⛔ **Questo riquadro NON è una lista di lavori** (REGOLA ZERO 3 non lo vieta): sono i numeri
> che descrivono la macchina, ognuno col comando che li ha prodotti. Esiste perché un numero
> tenuto a memoria mente: la D22 nasce da `Ran 5429`, un totale calcolato a mente e finito qui
> come se fosse stato misurato. Sei guardie in `test_pipeline_ci.py` leggono queste righe.
> ⚠️ **Riscrivendo il file il 2026-08-22 le avevo tolte per errore**, credendole «vecchia
> forma»: erano lo stato misurato, e toglierle era un passo indietro. Rimesse lo stesso giorno.

```
CONSEGNE AGGIORNATE A: 04f2ecd

SUITE ATTUALE: Ran 5985 test
AMBIENTE: Windows · Python 3.9.10 · hypothesis + pyyaml + coverage installati
          · ⛔ openssl NON nel PATH da PowerShell (`Get-Command openssl` -> ASSENTE):
            le guardie sul ripristino dei backup si mettono da parte IN BLOCCO e non
            entrano nel totale ESEGUITO. E' il caso descritto da D23 punto 3, ed e' la
            ragione dello scarto fra RACCOLTI (5943) ed ESEGUITI (5938).
COMANDO:  python -m unittest discover -s . -p "test_*.py"
```

⛔ **Il numero della suite si misura PRIMA di lanciarla, non dopo** (sbaglio S14, costato tre
giri da un'ora). Due secondi, dal caricatore, senza eseguire niente:
```
python -c "import unittest; print(unittest.TestLoader().discover('.', pattern='test_*.py').countTestCases())"
```

⛔ **E la suite NON si lancia da Git Bash.** Da lì `openssl` c'è e da PowerShell no: le guardie
sui backup si comportano in modo diverso e il giro non misura la stessa macchina (sbaglio S11,
direttiva D23). C'è una guardia che se ne accorge da sola — e il 2026-08-22 ha preso me.

### I quattro posti si LEGGONO, non si ricordano

Primo gesto di ogni sessione. **Quattro comandi, e il quarto è quello che manca sempre:**
```bash
git rev-parse --short HEAD                      # 1. il computer
git ls-remote origin refs/heads/master          # 2. GitHub
ssh root@76.13.44.167 "cd /var/www/bookinvip && git rev-parse --short HEAD"   # 3. il VPS
ssh root@76.13.44.167 'docker inspect --format="{{.Image}}" casavip_app'      # 4. L'IMMAGINE VIVA
```
⛔ **Il quarto non è un doppione del terzo.** Con i soli `git rev-parse` si può dichiarare
«quattro posti allineati» mentre il sito **serve codice di giorni prima**: il codice è
aggiornato sul disco del server, ma il contenitore gira ancora l'immagine vecchia. È successo
davvero il **2026-08-07**. `docker inspect` è l'unico che guarda cosa sta girando **adesso**.

⚠️ E le richieste di unione **si chiedono all'API, non ai documenti**: già tre volte un
documento ne dava una per chiusa mentre era ancora aperta.

---

# A) COSA FUNZIONA — provato, con la prova accanto

| cosa | la prova |
|---|---|
| **Il sito è online** | `curl https://bookinvip.com/` → **HTTP 200 in 0,039 s** (2026-08-22) |
| **Prende pagamenti veri** | chiave `sk_live` nel contenitore vivo — i soldi si muovono davvero |
| **I soldi tornano all'ospite** | **1 euro vero restituito** il 2026-08-16 · Stripe: `re_3U53IsJMRnB73twq1QLzUCu9 succeeded 1,00 EUR` · tre conferme indipendenti, una **non nostra** |
| **Il viaggio completo regge** | `collaudi/percorso_e2e.py`: host si iscrive → pubblica → l'ospite cerca, prenota, paga, riceve il voucher col PIN → **le date si bloccano** (una seconda prenotazione sulle stesse date viene rifiutata) |
| **I dati sopravvivono** | 25 database su disco nel volume Docker · **nessuno in RAM** · contratti firmati in `data/accettazioni.db`, giornale contabile in `/data/finanza.db` |
| **I dati hanno una copia** | copia di bordo **ogni 6 ore** (l'ultima: 2026-08-22 07:38) + copia verificata ogni notte alle 3:40 (`/root/salva_dati.py`, riapre l'archivio e controlla tutti e 25 i database) |
| **E una copia FUORI dal server** | `bookinvip-20260822-161346.tar.gz.enc`, **652.624 byte**, cifrata, sul PC del fondatore · impronta sha256 verificata ✅ · lo script la **riapre e la conta** prima di dichiararla riuscita, e la **cancella** se non si apre |
| **La posta è firmata** | SPF ✅ · DKIM ✅ (`hostingermail1`) · DMARC ✅ presente |
| **Il server è chiuso bene** | SSH **solo con chiave** (niente password) · firewall attivo, aperte solo 80, 443, 22 |
| **I tre posti sono allineati** | computer = GitHub = VPS · CI verde su `28c35c6` (BookinVIP CI + CodeQL) |
| **La macchina è sorvegliata** | 151 moduli · 405 file di test · **5.985 test** · 0 moduli che nessun test nomina |

---

# B) COSA MANCA PER APRIRE AL PUBBLICO — dieci cose, non una di più

> ⚠️ **Erano quattro la mattina del 2026-08-23, sono diventate sette, a fine giornata sei, e
> con lo studio dell'Anti-Rimpianto sono NOVE.** Le tre della mappa (B5, B6, B7) vengono dalla
> **mappa dei 39 pezzi** misurata quel giorno: non sono lavori inventati, sono i tre punti in
> cui un pezzo che tocca i soldi ha test verdi e **non ha addosso la tecnica che quel tipo di
> codice richiede**. **B1 è uscito**: declassato ad 🟠 e spostato in sezione C la sera stessa,
> dopo il deploy e la prova sui dati veri.
> Il resto della mappa — 15 pezzi «solo unitari» che non bloccano l'apertura — sta in sezione C.
>
> 🆕 **B8, B9 e B10 (2026-08-23) vengono da un posto diverso: nessuna mappa e nessun attrezzo.**
> Sono usciti leggendo il Credito Viaggio riga per riga, ed è il motivo per cui vanno letti
> insieme: **l'Anti-Rimpianto non è sorvegliato da nessuna guardia** (vedi il riquadro dopo
> B10). Non sono tre difetti trovati da tre strumenti: sono tre difetti trovati **perché
> nessuno strumento guardava lì**.

### 🔴 B2 — CAMBIARE TUTTE LE CHIAVI PROVVISORIE E ACCENDERE LA GUARDIA SULLA LUNGHEZZA
**Ultimo lavoro prima di aprire.** *(deciso dal fondatore il 2026-08-22: le chiavi di adesso
sono provvisorie e non c'è ancora nessun cliente vero, quindi si cambiano **tutte insieme**
l'ultimo giorno — non una alla volta adesso.)*

> *Misurato il 2026-08-22 sul contenitore vivo, senza mai stampare i valori:*
> ```
> ssh root@76.13.44.167 "docker exec casavip_app printenv ADMIN_KEY | wc -c"
> ADMIN_KEY 11 · HOST_KEY 64 · CASAVIP_SEGRETO 64 · BUNKER_PASSWORD 23
> ```
> `ADMIN_KEY` è l'unica corta, ed è quella che apre il pannello **da cui si fanno i rimborsi**.

**Perché era corta** — è la parte che conta, perché si ripeterebbe: `deploy/genera_segreti.sh`
genera `CASAVIP_SEGRETO` e `HOST_KEY`, **`ADMIN_KEY` no**. Ma `main_casavip.py:229`, quando
rifiuta di partire, dice «Genera le chiavi vere con: `sh deploy/genera_segreti.sh`». La
macchina non l'ha mai prodotta, quindi l'ha scritta a mano una persona. `DEPLOY.md` non la
nomina mai.

**La guardia sulla lunghezza è COSTRUITA e SPENTA di proposito.** All'avvio il prodotto già
rifiuta la chiave mancante, vuota, di soli spazi e uguale al segnaposto pubblico — ma
**nessuno guardava quanto è lunga** (nei test `ADMIN_KEY="x"` è una chiave valida). Ora il
giudizio si esegue a **ogni** avvio e finisce nei log: è solo la conseguenza — rifiutare di
partire — a essere spenta. Si accende **senza toccare il codice**, mettendo
`CHIAVI_LUNGHEZZA_MINIMA=32` in `.env.casavip`.
⛔ **Non accenderla prima di aver cambiato le chiavi:** con `ADMIN_KEY` a 11 caratteri il
contenitore **rifiuta di partire e il sito va giù**. Prima le chiavi, poi l'interruttore.

⚠️ **Cambiare la chiave NON chiude le sessioni già aperte:** il cookie `bv_admin` è firmato
con `CASAVIP_SEGRETO`, non con la chiave admin, e dura **12 ore**
(`fase83_server.py:9491`-`9506`). Chi è dentro resta dentro fino a scadenza.

**Due cose viste per strada il 2026-08-22, da chiudere in quello stesso giorno:** la chiave di
adesso è in chiaro in `/root/.bash_history` e in ~20 copie di riserva di `.env.casavip`; e
`/var/www/bookinvip/.env` è **leggibile da chiunque** (`-rw-r--r--`) con 6 righe che sembrano
segreti.

### 🔴 B3 — IL RIMBORSO CHIESTO DALL'OSPITE NON È MAI STATO PROVATO CON SOLDI VERI
Quello dal **pannello** sì (l'euro del 16 agosto). Quello che parte **dall'ospite** no, mai.
Il pulsante esiste (dentro la pagina del voucher), la porta del server esiste
(`/api/concierge/cancella`), il calcolo esiste — ma **nessuno ha mai visto i tre pezzi
lavorare insieme su un euro vero**. Serve una prova a mano, con carta vera. Costo: 27 centesimi.

### 🟠 B4 — SUL RIMBORSO PIENO CI RIMETTIAMO NOI LA COMMISSIONE
`fase111_cancellazione.calcola_rimborso` **non sottrae mai** il costo Stripe: all'ospite torna
tutto, la commissione la perde la piattaforma e non la recupera. Su 1 € sono 0,27; su una
prenotazione da 300 € cancellata a rimborso pieno sono **~4,75 € persi, ogni volta**.
⚠️ **Decisione del fondatore, non tecnica:** assorbirlo · trattenerlo dichiarandolo nelle
condizioni · assorbirlo solo dentro la finestra legale dei 48h e trattenerlo fuori.
⛔ La finestra di ripensamento **non si tocca**: quel 100% copre obblighi di legge.

### 🔴 B5 — `fase59_concierge` NON È MAI STATO GIUDICATO, ED È QUELLO CHE CALCOLA IL PREZZO
*(dalla mappa dei 39 pezzi, 2026-08-23.)* Il catalogo dei punti di mutazione in
`collaudi/mutazione_prodotto.py` copre **21 moduli su 151**, e `fase59_concierge` **non c'è**.
È il modulo che somma il conto del soggiorno: ogni preventivo e ogni prenotazione ci passano
dentro. Ha cinque file di test, tutti verdi, e una gara vera (`test_race_hold_conferma`) — ma
nessuno ha mai rotto quel codice di proposito per vedere se un test se ne accorge.
> ⛔ **Verde non vuol dire guardato.** Su `fase59` è già successo: il 2026-08-14 risultava
> «FATTO» nel piano dei soldi mentre aveva **42 punti scoperti**, 39 su codice che la
> produzione esegue a ogni preventivo. È la direttiva **D26**, ed è nata proprio qui.

### 🔴 B6 — IL PAYOUT ALL'HOST NON HA UN SECONDO CONTO CHE LO RICALCOLI
*(dalla mappa dei 39 pezzi, 2026-08-23.)* Sei file di test sul bonifico all'host
(`test_fase131_payout_dashboard`, `test_payout_in_attesa`, `test_payout_valuta_storica`,
`test_split_penale_payout`, `test_dac7_blocco_payout`, `test_fase101_stripe_connect`) e
**nessun oracolo indipendente**: quanto spetta all'host viene riletto, mai ricalcolato da zero
da un secondo conto scritto diverso. È la tecnica **04**, ed esiste già in casa in due punti
(`collaudi/prezzi_coerenti.py` sul prezzo, `collaudi/oracolo_tassa.py` sulla tassa): manca qui.
> ⛔ **È il primo numero che un host vero controlla.** Se sbaglia, non lo scopriamo noi: lo
> scopre lui, e lo scopre sul suo conto corrente.

### 🔴 B7 — LA RICONCILIAZIONE CHIUDE CONTRO SE STESSA, NON CONTRO STRIPE
*(dalla mappa dei 39 pezzi, 2026-08-23.)* `fase182_riconciliazione` è provata da
`test_riconciliazione`, `test_riconciliazione_interlibro` e `test_movimenti_giornale`: il libro
torna **contro il libro**. Il confronto col **traffico vero di Stripe** — il terzo che tiene i
soldi davvero — non esiste.
> 💡 **È esattamente il metodo che ci manca secondo la ricerca industriale** (AWS: verificare
> le regole dei soldi sul traffico VERO). Finché il conto chiude solo contro se stesso, un
> errore sistematico nostro è invisibile per costruzione: sbaglia due volte allo stesso modo e
> il confronto torna.

### 🔴 B8 — LA HOMEPAGE DICE IL FALSO IN 8 LINGUE
*(misurato il 2026-08-23 leggendo il codice.)* `deploy/index.html:175` porta un badge in
**otto lingue** (i testi stanno in `fase83_server.py:172`):

> «**Anti-Rimpianto: i soldi tornano come credito**» · «Regret-free: money back as credit»

**Il codice fa un'altra cosa, e sbaglia in tutte e due le direzioni:**

| Caso | La homepage promette | Il codice fa davvero |
|---|---|---|
| Cancella **entro 48h** | i soldi tornano **come credito** | i soldi tornano **come soldi**, il **100%** (`fase111_cancellazione.py:66-68`) |
| Cancella **fuori finestra**, penale 300 € | «i soldi tornano» | un credito da **50 €** (tetto), che al riscatto può valere **0** (vedi B9) |

⛔ **La riga che conta è la seconda: promette più di quello che diamo.** È il rischio di
pubblicità ingannevole — la stessa famiglia di B1 (i due prezzi), ma sulla pagina che vede
**ogni** visitatore, non nel pannello host.
> 💡 La prima riga sbaglia al contrario: **sottovaluta** quello che diamo. Entro le 48 ore
> rendiamo denaro vero al 100%, e la homepage lo racconta come un buono. Un difetto che ci
> costa clienti invece di procurarci guai — ma resta un difetto, ed è lo stesso.

⚠️ **E non esiste NESSUNA pagina che spieghi le regole.** Cercato in tutte le pagine di
`deploy/`: la parola «rimpianto» compare **una volta sola**, in quel badge. Né la percentuale,
né il tetto di 50 €, né la scadenza, né il fatto che sconta solo fin dove arriva la nostra
commissione sono scritti da nessuna parte per il cliente.

### 🔴 B9 — IL CREDITO VALE ZERO PER GLI HOST IN PROMO, E L'EMAIL DICE «50 €»
*(misurato il 2026-08-23.)* Il credito si conia a `fase83_server.py:7080-7101`: vale il **50%
della penale**, tetto **5.000 unità minori** (50 €), dura **365 giorni**. Ma quel numero non è
quello che l'ospite ottiene. Al riscatto, `fase59_concierge.py:498-503`:

```python
costo = netto * _bps // 10000 + 25 + 200     # 3,25% + 0,25 + 2 EUR di buffer
margine_disponibile = max(0, comm - costo)   # comm = la NOSTRA commissione
return max(0, min(cr, margine_disponibile)), credito_id
```

**Lo sconto è tagliato a quanto la nostra commissione può assorbire.** Un credito da 50 €
vale davvero questo (calcolato dalla formula, annuncio in EUR):

| Nuova prenotazione | host in promo 0% | host 8% | host a regime 10% |
|---|---|---|---|
| 50 € | **0,00** | 0,13 | 1,13 |
| 100 € | **0,00** | 2,50 | 4,50 |
| 300 € | **0,00** | 12,00 | 18,00 |
| 500 € | **0,00** | 21,50 | 31,50 |
| 800 € | **0,00** | 35,75 | **50,00** |

⛔ **Nei primi 90 giorni la commissione è 0, quindi il margine è 0, quindi il credito vale
ZERO a qualunque importo.** Sono **esattamente gli host che stiamo per reclutare**: la rampa
di lancio (`fase98_policy_commissione.py:75`) regala i primi 90 giorni a ogni host nuovo.
⛔ **E serve una prenotazione da ~774 € perché un credito da 50 € valga 50 €** (a regime:
`0,0675 × netto ≥ 5.225`).

⛔ **Intanto l'email promette il valore NOMINALE.** `fase86_email.py:262` → *«🎁 In più hai un
**Credito Viaggio di %s** per la prossima prenotazione»*, riempito con `credito_cents` a
`fase86_email.py:677` e `fase83_server.py:6899`. **Nessuna riga, in nessuna lingua, dice che
l'importo può ridursi o azzerarsi.**
> 💡 La guardia di margine in sé è **giusta**: esiste perché non regaliamo mai sotto costo
> («mai in perdita»). Il difetto non è il tetto: è che **il numero promesso e il numero
> pagabile sono due numeri diversi e solo uno dei due viene detto al cliente.** È la stessa
> forma di B1 — un valore mostrato che la cassa non onora.

### 🔴 B10 — IL CREDITO È UN TITOLO AL PORTATORE
*(misurato il 2026-08-23.)* Il token si conia con il campo email **vuoto**
(`fase83_server.py:7096` → `"email": ""`). E chi lo riscatta —
`fase59_concierge.py:462-503` — controlla firma, tipo, scadenza, uso singolo, valuta e
margine: **l'email non la guarda mai.**

**Chiunque abbia il token lo spende.** Non è un'ipotesi: lo dichiara già
`fase167_credito_single_use.py:7` — *«il token è condivisibile»*.

Cosa regge e cosa no:
- ✅ **Uso singolo**: chiuso il 2026-07-16 (`fase167`), identificato dalla firma HMAC
  (`fase59_concierge.py:474`), consumato alla **finalizzazione** e non al preventivo
  (`fase83_server.py:7059`), così il browsing non lo brucia.
- ✅ **Scadenza**: 365 giorni (`fase83_server.py:7098`).
- ✅ **Vincolato alla valuta**: su annuncio in valuta diversa sconta 0
  (`fase59_concierge.py:491-493`).
- ⚠️ **Ma il controllo di uso singolo è FAIL-OPEN**: se il registro dei crediti si guasta,
  `fase59_concierge.py:476-481` lascia passare lo sconto lo stesso. È dichiarato apposta (un
  guasto non deve bloccare una prenotazione legittima) — però in quella finestra il credito
  **torna riusabile**.
- 🔴 **Nessun legame con la persona.** Il campo per farlo **esiste già nel token** ed è vuoto:
  non manca la struttura, manca chi la riempie e chi la legge.

> ⛔ **DECISIONE DEL FONDATORE, non tecnica** (come B4): un credito al portatore può essere
> una scelta commerciale («regalalo a un amico») o un buco. Oggi non è né l'una né l'altra:
> **è un comportamento che nessuno ha deciso.** Nessuna pagina lo promette, nessun documento
> lo vieta, nessun test lo prova.

### 🛡️ E NESSUNA GUARDIA SORVEGLIA L'ANTI-RIMPIANTO — è il motivo per cui B8, B9 e B10 esistono

⛔ **Questa non è una quarta voce: è la spiegazione delle tre sopra.** `test_trasparenza_costi.py`
sorveglia la tariffa tecnica e la rampa delle commissioni — ancorando i testi pubblici alle
costanti vere del motore, così che cambiare una tariffa senza aggiornare le pagine diventi
rosso lo stesso giorno. **Sull'Anti-Rimpianto non esiste niente di equivalente.**

Nessun attrezzo controlla, oggi:
- che il badge di `index.html` dica quello che il codice fa;
- che il valore **promesso** nell'email coincida con quello **riscattabile**;
- che il credito sia legato a chi l'ha ricevuto;
- che esista una pagina in cui le regole del credito siano scritte.

> 💡 **La lezione, ed è la stessa di B1 e delle pagine che dichiarano una tariffa tecnica più
> bassa di quella che il motore addebita:** i tre difetti non sono
> stati trovati da uno strumento, sono stati trovati **leggendo**. Dove uno strumento guarda,
> i difetti si vedono il giorno che nascono; dove non guarda nessuno, invecchiano in silenzio
> finché non li legge una persona. **Prima di riparare B8/B9/B10 va scritta la guardia**,
> altrimenti si riparano tre testi e il quarto nascerà uguale.

### 🟠 B11 — I REGALI SI SOMMANO: IL SALDO NEGATIVO È CHIUSO, IL «NESSUNO SOMMA» NO

> ✅ **RIPARATO IL 2026-08-23 (idea C del fondatore, autorizzata).** Il saldo per
> prenotazione non può più andare negativo: la somma dei due regali è tagliata alla
> commissione. **Declassato da 🔴 a 🟠 — non è chiuso**, perché la riparazione toglie
> *questo* incrocio, non la causa: **continua a non esistere un posto che somma.**
>
> **Cosa è stato fatto, e sono DUE righe, non una.** `fase83_server._commissione_regalabile`
> sottrae dalla commissione lo sconto già finanziato all'ospite, ed è usata **in tutti e due**
> i punti che regalano: `fase83_server.py:5910` (conferma immediata, senza pagamento online)
> e `fase83_server.py:8170` (webhook Stripe). ⛔ **Il secondo punto l'ho trovato leggendo, non
> ricordando**: ripararne uno solo avrebbe lasciato il difetto vivo sull'altra strada, e
> nessun collaudo se ne sarebbe accorto.
>
> **La guardia:** `test_regali_non_superano_la_commissione.py`, 5 collaudi, **vista rossa
> prima** su tutt'e due i cammini (`3000 not less than or equal to 1200`), e il secondo
> cammino provato **iniettando il guasto con l'editor** e ripristinando con **sha256
> identico** (`8e525d20…` prima e dopo). Sta su **chi chiama**, non su
> `_applica_credito_host`: quel metodo faceva esattamente ciò che gli si chiedeva, era il
> numero che riceveva a essere sbagliato (regola ferrea 11). E asserisce un **effetto** — i
> centesimi davvero consumati dal registro — non l'assenza di eccezioni, perché
> `_conferma_pagamento` isola i guasti in un `except` e un collaudo che si accontentasse di
> «non ha sollevato» sarebbe verde anche col flusso morto alla prima riga (S7).
>
> **Il pavimento, dopo:** peggio su tutta la banda **+0,02** invece di **−23,31**. Su 300,00 a
> regime: **+9,87** su carta europea, **+4,94** su internazionale.
>
> 🔴 **COSA RESTA APERTO, ed è la parte che conta:**
> 1. **Nessuno somma ancora.** Il tetto vive nei due punti che regalano oggi. Il giorno che
>    qualcuno collega `fase137` (fedeltà ospite), `fase78` (rimborso money-back) o i crediti
>    di `fase109`, la somma torna fuori controllo — è l'**idea A** del fondatore, stimata
>    5-8 giorni, e si sovrappone a B6 e B7.
> 2. **Il referral non si autofinanzia nei primi 90 giorni**: con la commissione a zero
>    l'invitato non produce niente e noi paghiamo il premio lo stesso. Serve **quanta
>    commissione ha prodotto**, non **quante prenotazioni ha fatto** (`fase81:58`) — è
>    l'**idea B**, 2-3 giorni, ed è una decisione economica, non la riparazione di un difetto.
> 3. **Il conio senza freno** della rotta pubblica della lista d'attesa resta (vedi in fondo).
>    Adesso è innocuo per prenotazione, non per numero di token in giro.
> 4. **Il pavimento è sottile:** +0,02 su una prenotazione da 1,00. Regge solo finché la
>    tariffa tecnica sta sopra il costo Stripe. Se un giorno scendesse sotto, tutto questo
>    torna negativo **in silenzio**, e nessuna guardia lo direbbe.

*(misurato il 2026-08-23, per ordine del fondatore: «voglio il conto totale di quello che
regaliamo». Nessuno l'aveva mai sommato. Quello che segue è com'era **prima** della
riparazione: si legge per capire perché la guardia esiste.)*

**Sei cose regalano, e ognuna ha una guardia che protegge SE STESSA. Nessuna guarda le altre.**

| # | Cosa | Quanto | Chi paga | Dove |
|---|---|---|---|---|
| 1 | Rampa di lancio: primi 90 giorni a commissione zero | tutta la commissione | **noi** | `fase98_policy_commissione.py:75-78` |
| 2 | Credito Anti-Rimpianto | metà della penale, tetto 5000 unità minori, 365 gg | **noi** | `fase83_server.py:7089`, `:7098` |
| 3 | Credito benvenuto lista d'attesa | 500 unità minori, 180 gg | **noi** | `fase158_domanda.py:22-23` |
| 4 | Viral: benvenuto al nuovo host | 1000 cents | **noi** | `fase81_bootstrap_casavip.py:56` |
| 5 | Viral: premio a chi invita (3ª prenotazione pagata) | 4000 cents | **noi** | `fase81_bootstrap_casavip.py:57`, `fase83_server.py:8294` |
| 6 | Sconto soggiorno lungo · sconto non rimborsabile | li sceglie l'host | **l'host** | `fase59_concierge.py:294-311` |

⛔ **IL PUNTO DI ROTTURA STA IN UNA RIGA SOLA: `fase83_server.py:8170`.**
```python
self._applica_credito_host(rif, hid_pag, dj.get("commissione_cents", 0))
```
Passa la commissione **LORDA**. Ma da quella stessa commissione abbiamo **già** finanziato lo
sconto dell'ospite (`fase59_concierge.py:503`). I due crediti attingono allo stesso pozzo e
**nessuno dei due sa dell'altro**: la guardia di margine del concierge protegge il credito
dell'ospite, il tetto di `usa_credito` protegge quello dell'host, e la somma non la controlla
nessuno.

**IL CASO PEGGIORE, prodotto dalle formule vere** (ospite col credito pieno + host con
benvenuto e premio, prenotazione da 300,00, tassa di soggiorno zero):

| età host | carta europea | carta internazionale |
|---|---|---|
| promo (primi 90 gg) | **+10,50** | **+5,25** |
| dal 4º mese a un anno | **−1,92** | **−6,96** |
| a regime | **−8,13** | **−13,06** |

⛔ **E il peggio non è a 300.** Cercata al centesimo, la perdita è una **banda**, non una
soglia: da **45,00** a **970,00** di prenotazione, col fondo a **−23,31 su una da 500,00**
(carta internazionale, host a regime). Sopra e sotto quella banda il saldo torna positivo.

> 💡 **La cosa contro-intuitiva, ed è quella da ricordare:** durante la promo **NON si perde**.
> Con la commissione a zero il pozzo è vuoto, e tutti e due i crediti valgono zero
> (`fase59_concierge.py:503` e `fase83_server.py:8249`). **La rampa ci sta proteggendo per
> caso.** Il buco si apre il giorno che il primo host esce dai 90 giorni — cioè fra tre mesi
> dal primo host vero, non oggi.

**Controprova, stesso giro senza i due crediti:** +10,50 (promo) e +40,50 (regime) su carta
europea. Il difetto è **tutto** nella somma, non nelle singole regole.

**E ci sono quattro promesse costruite e mai collegate** (regola #23, «costruito ≠ collegato»):
`fase109_referral_host` ha una rotta admin che assegna un bonus a scaglioni, ma **quei crediti
non si spendono da nessuna parte** — è un debito che nessuno può riscuotere;
`fase137_fedelta_guest`, `fase78_sleep_guarantee` (rimborso money-back) e `fase71_commitment`
sono costruiti e **non cablati**. Oggi non costano niente. Il giorno che qualcuno li collega
entrano nella stessa somma che nessuno controlla.

⚠️ **E un punto di conio senza freno**: `POST /api/domanda` è **pubblico, senza
autenticazione**, ed emette un credito firmato **a ogni chiamata** — `registra` fa
`ON CONFLICT DO UPDATE` e torna `True` anche sul doppione (`fase158_domanda.py:109-114`),
mentre il token esce comunque (`fase83_server.py:7195`) con un `nonce` nuovo, quindi per
`fase167` è un credito **diverso**. Stessa email, quanti token vuole. Il danno per singola
prenotazione resta limitato (un token per preventivo, più il tetto di margine), ma **il numero
di token in giro non ha tetto**.

> ⛔ **NON È UN TETTO CHE MANCA: È CHE NESSUNO SOMMA.** Aggiungere un limite a ciascun regalo
> non chiude niente — ognuno ha già il suo. Serve **un posto solo** che, prima di versare,
> guardi quanto è uscito in totale su quella prenotazione. Finché non c'è, ogni regalo nuovo
> allarga la banda senza che nessuno se ne accorga.

---

# C) DOPO L'APERTURA — tutto il resto

### 🗺️ LA MAPPA DEI 39 PEZZI — i 15 «solo unitari» che restano
*(misurata il 2026-08-23 sul commit `4144f40`. **Non è un elenco di lavori urgenti**: è
l'inventario di dove una tecnica esiste in casa e non è ancora puntata addosso. I tre casi che
bloccano l'apertura sono già in sezione B; il pezzo che non esiste ha un blocco suo qui sotto.)*

⛔ **«Solo unitario» non vuol dire rotto.** Vuol dire: il test esiste, è verde, e prova il pezzo
con **gli esempi che abbiamo scelto noi**. La tecnica accanto è quella che quel pezzo
richiederebbe per come si rompe — e non c'è.

**Percorso cliente**

| Pezzo | Modulo | Tecnica che manca | Perché proprio quella |
|---|---|---|---|
| Ricerca | `fase26_ricerca` · `fase121_geo_ricerca` | **07 · proprietà** | una ricerca sbaglia sui casi che non ci vengono in mente |
| Mappa e dintorni | `fase166_geocoder` · `fase175_poi_osm` | **04 · oracolo** | una coordinata sbagliata è formalmente valida |
| Pagamento con carta | `fase85_pagamenti_stripe` | **03 · replay** | lo stesso webhook due volte non deve addebitare due volte |
| Carta rifiutata | `fase183_carta_offsession` | **05 · caos** | il rifiuto arriva quando il resto è già in moto |
| Voucher | `fase59_concierge` · `fase83_server` | **10 · fuzzing** | un codice che vale soldi è la prima cosa che si prova a forzare |
| PIN d'ingresso | `fase59_codice_pin` | **10 · fuzzing** | è una serratura: va attaccata, non solo usata |
| Promemoria | `fase152_notifiche_prenotazione` | **02 · seed** | dipende tutto dall'orologio, e l'orologio finto ha già ingannato cinque volte |
| Deposito cauzionale | `fase149_deposito_cauzionale` | **04 · oracolo** | trattenere e restituire sono due conti che devono chiudere |
| Valuta e conversione | `fase99_multicurrency` | **11 · metamorfico** | convertire e riconvertire deve tornare al punto di partenza |

**Percorso host**

| Pezzo | Modulo | Tecnica che manca | Perché proprio quella |
|---|---|---|---|
| Identità e KYC | `fase143_kyc_host` · `fase105_identity_gate` | **05 · caos** | il fornitore d'identità è un terzo che può morire a metà |
| Pubblicazione annuncio | `fase141_onboarding_wizard` | **10 · fuzzing** | è dove un estraneo carica file e testo |
| Escrow e garanzia | `fase160_escrow_garanzia` | **08 · model-based** | trattenuto → liberato → liquidato è una macchina a stati |
| Split fra co-host | `fase133_split_quote_uguali` · `fase65_split_payment` | **11 · metamorfico** | la divisione intera non si distribuisce, ed è lo stesso caso in cui il metamorfico ha già trovato un errore |
| iCal bidirezionale | `fase82_ical_sync` · `fase135_ical_bidirezionale` | **05 · caos** | è l'unico pezzo che scrive nell'inventario **da solo** |

**Trasversale**

| Pezzo | Modulo | Tecnica che manca | Perché proprio quella |
|---|---|---|---|
| Backup e ripristino | `fase38_backup` | **04 · oracolo** | ⚠️ le guardie sul ripristino **si spengono in blocco su Windows** (`openssl` fuori dal PATH): girano solo in CI. E le copie stanno **nello stesso volume dei dati veri** |

💡 **Cosa dice la mappa guardata tutta insieme:** il collo di bottiglia non è la profondità, è
la **larghezza**. Le 11 tecniche funzionano tutte, ma **z3, model-based e metamorfico sono
accesi su un modulo ciascuno**, il fuzzing su tre, il caos su tre, la mutazione su **21 su
151**. La domanda giusta non è «quale tecnica ci manca»: è «a quali pezzi non è ancora puntata
addosso».

⛔ **Limite dichiarato di questa mappa (D18 punto 3):** «la tecnica è applicata» è misurata sui
**segni**, non sul senso — concorrenza = il file usa i thread; proprietà = c'è `@given`;
mutazione = il modulo è nel catalogo. Un file può usare i thread e non provare nessuna gara
vera, e la mappa non lo distingue.

### 🟠 B1 — I DUE PREZZI, COM'È FINITA *(era in sezione B, declassato e spostato qui il 2026-08-23)*

> **B1 non blocca più l'apertura: la bugia non può nascere (specchio cablato) e le due già
> scritte sono riparate. Restano due cose PRIMA DEL PRIMO HOST VERO: il pezzo 3 (una casella
> prezzo sola nel pannello, invece di due quasi identiche) e il comando che ricalcola tutti gli
> annunci in una volta.**
> *(fondatore, 2026-08-23.)*

**Cos'era.** Il pannello host aveva due caselle prezzo (`p_prezzo` → vetrina, `d_prezzo` →
cassa) che nessuno collegava: il sito mostrava un prezzo e la cassa ne addebitava un altro.
Rischio pubblicità ingannevole.

> ⚠️ **NESSUN OSPITE HA MAI PAGATO IL PREZZO SBAGLIATO.** *(precisazione del fondatore,
> 2026-08-22.)* I due annunci coinvolti, `filippine-makati` e `filippine-makati-2`, erano
> **annunci di PROVA del fondatore**: in produzione ci sono **0 host firmati e 0 annunci veri**.
> ⛔ **Il difetto però era vero:** due caselle quasi identiche in due schermate diverse, tutte e
> due chiamate «Prezzo/notte», tutte e due con `value="95"` di partenza. **Un host vero
> sbaglierebbe uguale.** Il difetto stava nel pannello, non in chi lo compila — ed è la ragione
> per cui il **pezzo 3 resta**.

> *Misurato il 2026-08-22:* `deploy/host.html:378` («Prezzo/notte che vede l'ospite») scriveva
> `prezzo_notte_cents`; `deploy/host.html:425` («Prezzo/notte») scriveva `prezzo_netto_cents`,
> e i due numeri non comparivano insieme in **nessun punto del codice**. Dove va ciascuno:
> · `prezzo_notte_cents` → pagina dell'annuncio, **Google** (`"price"` in JSON-LD), anteprima
>   sui social, feed RSS, schede dei risultati, filtri e ordinamento per prezzo, mappa;
> · `prezzo_netto_cents` → **quello che si paga davvero**: `fase59_concierge.py:283` somma
>   notte per notte questo, e solo questo.

**🔑 DECISO IL 2026-08-22 (scelta B del fondatore): «il numero visto dev'essere il numero
pagato».** Con le date scelte, la scheda mostra il prezzo **di quelle date**, preso dal
calendario; senza date, «da X», dove X è la notte prenotabile più economica.

**✅ PEZZO 1 — la guardia, che non c'era.** `collaudi/prezzi_coerenti.py` (sola lettura,
`mode=ro`) più le guardie in `test_prezzo_vetrina_e_cassa.py`. È **nata rossa** sui dati veri,
che è l'unica prova che stesse guardando la cosa giusta.
> ⛔ **La trappola gliel'hanno insegnata i dati veri, non la fantasia:** `filippine-makati`
> aveva una notte a 100 cents datata **16/08, già passata**. Un controllo che guardasse tutti i
> giorni troverebbe minimo 100, direbbe «coincide» e **assolverebbe il difetto** con un giorno
> che nessuno può più prenotare. Lo impedisce `test_LA_NOTTE_PASSATA_NON_ASSOLVE`; stesso
> trattamento per le notti chiuse, piene e a prezzo zero.

**✅ PEZZO 2a — la vetrina DERIVA il prezzo dal calendario.** `alloggi.prezzo_notte_cents` non è
più un numero indipendente: `fase57_vetrina.rispecchia_prezzo()` lo ricalcola dalla notte
**prenotabile** più economica dell'inventario. Ricerca, filtri, Google e mappa leggono la stessa
colonna di prima — ma quella colonna non può più mentire.
> **Dove è agganciato, e perché lì.** L'avviso parte dal **confine dei dati**
> (`fase58_channel_manager`), non dai pulsanti del pannello: i posti che scrivono l'inventario
> sono **cinque**, e agganciarlo a quelli visibili avrebbe lasciato scoperto il più pericoloso —
> l'**iCal, che scrive da solo**. I due versi si cablano in `fase81_bootstrap_casavip`, l'unico
> punto in cui esistono tutt'e due, e il nome entra nel rendiconto di composizione
> (`specchio-prezzo(58->57)`): costruito e non collegato non esiste (regola #23).
> Se non c'è niente di prenotabile **non inventa un prezzo**: lascia la vetrina com'è e torna
> `None`. La coppia leggi-minimo → scrivi-vetrina tocca due archivi e non sta in una sola
> transazione: un `threading.Lock` la rende atomica.
>
> **Provato il 2026-08-23** — commit `4144f40`, unito in `master` con `a35f1e9` (PR #96,
> `merged: true` **riletto dall'API**):
> ```
> test_prezzo_vetrina_e_cassa.py ..... 37 test OK
> batteria completa (con le modifiche dentro) ..... 5980 test OK, banco dei soldi OK
> CI su Linux ..... 16 job su 16, 0 rossi
> ```

**✅ DEPLOYATO E PROVATO SUI DATI VERI IL 2026-08-23.** Paracadute `:prec` ri-agganciato
all'immagine viva **prima** del build e verificato per contenuto; deploy `a8007d6 -> b797d46`
chiuso con uscita 0 in **35 secondi**; `money_path_pronto: True`, `avvisi: []`, e
**`specchio-prezzo(58->57)` nel rendiconto d'avvio in produzione**. L'immagine viva contiene
esattamente il codice di `b797d46`, verificato confrontando l'impronta dei suoi **152 file** con
la stessa impronta ricostruita dall'albero di git: `538b419096a5cf21…` da tutt'e due le strade.
`collaudi/verifica_produzione.py`: **190 controlli, 0 violazioni**.
> **La riga d'arrivo, misurata dall'oracolo indipendente sui dati veri:**
> ```
> prima:  2 annunci pubblicati · 2 dicono il falso   (uscita 1)
> dopo:   2 annunci pubblicati · 0 dicono il falso   (uscita 0)
> ```
> ⚠️ **Fra «prima» e «dopo» non c'è il deploy: c'è il RICALCOLO.** Il deploy da solo aveva
> lasciato l'oracolo rosso — ed è il motivo per cui esiste la voce qui sotto.

**RESTA DA FARE — pezzo 3: il pannello ha una casella sola** *(tocca la produzione)*: prezzo
base, più un'eccezione per certi giorni dichiarata come tale e già riempita col prezzo base.
Toglie la causa invece di inseguire l'effetto.
> 🔑 **Rimandato per decisione del fondatore, 2026-08-23: «il pezzo 3 lo lasciamo».** Non è
> stato dimenticato e non è stato chiuso: il 2a toglie l'**effetto** (la vetrina non può più
> dire un numero che la cassa non addebita), il 3 toglierebbe la **causa** (due caselle quasi
> identiche in due schermate). Con 0 host firmati è la finestra in cui costa meno rifarlo.

### 🔁 IL COMANDO CHE RICALCOLA TUTTI GLI ANNUNCI IN UNA VOLTA — da fare prima del primo host vero

> **Uno specchio impedisce alla bugia di nascere, non ripara quelle già scritte. Serve un
> comando che ricalcoli TUTTI gli annunci pubblicati in una volta. Con 2 annunci basta farlo a
> mano; con 500 serve il comando. Da fare prima del primo host vero.**
> *(fondatore, 2026-08-23.)*

**Com'è venuto fuori, misurato il 2026-08-23 subito dopo il deploy.** Lo specchio era in
produzione e **cablato** (`specchio-prezzo(58->57)` nel rendiconto d'avvio), eppure l'oracolo
sui dati veri diceva ancora **`2 annunci pubblicati · 2 dicono il falso`**: in archivio i due
annunci avevano ancora `prezzo_notte_cents = 100` contro una notte prenotabile da **9000**.
Lo specchio si accende **quando qualcuno scrive** — alla pubblicazione (`fase57_vetrina.py:611`)
e dopo ogni scrittura dell'inventario (`fase58_channel_manager.py:255`) — e dal deploy in poi
nessuno aveva scritto.

⛔ **Un deploy non è una migrazione dei dati.** Qui erano due annunci di prova e nessun ospite
ha mai pagato; con 500 annunci veri, dopo quel deploy **starebbero mentendo tutti e 500** — e la
mappa dei 39 pezzi avrebbe detto «coperto», perché il codice giusto c'era.

✅ **Ricalcolo fatto a mano il 2026-08-23** (autorizzato dal fondatore), con copia di sicurezza
del catalogo presa prima e verificata per sha256:
```
PRIMA  filippine-makati 100 cents · filippine-makati-2 100 cents
DOPO   filippine-makati 9000      · filippine-makati-2 9000        (2 su 2 cambiati)
oracolo sui dati veri -> 2 annunci pubblicati · 0 dicono il falso · uscita 0
```
> 💡 **Tre trappole trovate scrivendo quel ricalcolo a mano**, e il comando dovrà evitarle tutte:
> `docker exec` **non eredita l'ambiente** del processo vivo; `ConfigCasaVIP` **non legge
> l'ambiente** (lo fa `main_casavip.main()`, righe 92-95), quindi chiamare `crea_sistema()` senza
> configurazione costruisce un sistema **spento su `:memory:`** e stamperebbe un successo che non
> ha toccato niente — **il verde peggiore**. Il ricalcolo si è fermato da solo due volte grazie a
> due guardie scritte prima («non tocco niente»): il comando definitivo deve portarsele dietro.

### ⚖️ DECISIONE DEL FONDATORE ANCORA DA PRENDERE — il cambio data

> **Il cambio data non esiste come funzione. Non è un difetto di collaudo: è una scelta di
> prodotto mai presa. Oggi l'ospite può solo cancellare e riprenotare. Decidere se serve prima
> di aprire.**

*Misurato il 2026-08-23:* cercato in tutti i 151 moduli, l'unico riscontro è in
`test_fase56_gateway_tavoli` — il **vecchio impianto dei ristoranti**, non il prodotto. Non
esiste rotta, non esiste modulo, non esiste test. Conseguenza concreta per chi prenota: chi
deve spostare il soggiorno **cancella e riprenota al prezzo del giorno**, con la politica di
cancellazione che scatta.
⛔ Non è un lavoro in coda: è una domanda. Finché non ha risposta non va in nessuna lista.

### La sorveglianza sui soldi (il lavoro più grosso che resta)
**140 punti su 246 non sono sorvegliati.** Misurato il 2026-08-22 coi test giusti, modulo per
modulo:
```
fase85_pagamenti_stripe    60 provati ·  17 uccisi ·  43 SOPRAVVISSUTI
fase131_payout_dashboard   62 provati ·  19 uccisi ·  43 SOPRAVVISSUTI
fase65_split_payment       59 provati ·  40 uccisi ·  19 SOPRAVVISSUTI
fase101_stripe_connect     50 provati ·  16 uccisi ·  29 SOPRAVVISSUTI (+5 non determinabili)
fase87_stripe_webhook      15 provati ·   9 uccisi ·   6 SOPRAVVISSUTI
```
Il prodotto **funziona**: quello che manca è la rete che se ne accorge quando si rompe. Sono
**test da scrivere**, non prodotto da rifare.

### Il piano dei soldi — lo legge `collaudi/piano_dei_soldi.py`

> ⚠️ **QUESTE TRE SEZIONI NON SONO PROSA: SONO L'INGRESSO DI UN ATTREZZO.**
> `collaudi/piano_dei_soldi.py` — il guardiano che **ferma il commit** — cerca qui dentro tre
> frasi esatte e le legge con espressioni regolari. Riscrivendo questo file il 2026-08-22 le
> avevo tolte e il guardiano è andato in errore.
> ⛔ **E questo è il difetto, non la cura:** un attrezzo che sorveglia i soldi non deve
> leggere frasi in italiano scritte a mano. **Farlo misurare dalla macchina è il primo
> lavoro del giorno dopo** — vedi la voce qui sotto.

**Moduli dei SOLDI GIÀ passati dal giudice — 11:**
`fase119_calendario_prezzi` (17/17, 2026-08-13) · `fase133_split_quote_uguali` (15/22, zero
sopravvissuti sul codice VIVO) · `fase59_concierge` (114 punti, 72 uccisi) ·
`fase160_escrow_garanzia` · `fase100_dac7` · `fase188_paga_struttura` ·
`fase167_credito_single_use` (11/11, 2026-08-11) · `fase66_tassa_soggiorno` (24/24,
2026-08-12) · `fase98_policy_commissione` (18/18) · `fase147_tassa_comunale` (29/29) ·
`fase111_cancellazione` (11/13, i 2 sopravvissuti **non** dichiarati equivalenti).

**Moduli dei SOLDI CHE RESTANO — 6, per 360 punti.**
*(⛔ punti **rimisurati col censimento il 2026-08-22**: erano 303 e nessuno aveva toccato quel
codice — a cambiare è stato il generatore. È il motivo per cui una tabella di numeri va
rifatta, non ricopiata.)*

| modulo | punti | lo nominano | blocco |
|---|---|---|---|
| `fase162_pagamenti_pendenti` | 114 | 14 | 4 |
| `fase131_payout_dashboard` | 62 | 12 | 4 |
| `fase85_pagamenti_stripe` | 60 | 79 | 5 |
| `fase65_split_payment` | 59 | 4 | 3 |
| `fase101_stripe_connect` | 50 | 7 | 3 |
| `fase87_stripe_webhook` | 15 | 59 | 5 |

⚠️ **Cinque di questi sei sono stati GIUDICATI il 2026-08-22** (tutti tranne `fase162`): 246
punti provati, **101 uccisi, 140 sopravvissuti**. Restano in questa tabella perché **giudicato
non vuol dire fatto** (D26): finché i sopravvissuti non sono zero, il lavoro è aperto.

⛔ **FUORI DALL'ELENCO PERCHÉ SONO CODICE MORTO** (`raggiungibilita.py`):
`fase43_commissione` (31) · `fase44_prezzo` (25) · `fase35_pagamenti` (25) = **81 punti che NON
vanno fatti**. Erano in tabella e mandavano a lavorare sul nulla.

### 🔴 PRIMO LAVORO DI DOMANI — il guardiano dei soldi deve MISURARE, non leggere
`collaudi/piano_dei_soldi.py` ricava lo stato dei moduli **da frasi in italiano** dentro questo
documento (tre espressioni regolari su prosa scritta a mano). È **l'ultimo posto dove è rimasta
la malattia del 22 agosto**, ed è proprio quello che sorveglia i soldi. Deve leggere
`collaudi/piano.py` e il censimento. Stimato: **due o tre ore**, e ogni giudizio va rivisto
nelle due direzioni perché è il guardiano che ferma il commit.

### Il Blocco 1 — le caselle che restano
`python collaudi/scheda.py --blocco 1`. Tre sono **già soddisfatte** e aspettano solo un
attrezzo che le registri (le prove z3 girano: 35 test, 0 saltati · le relazioni metamorfiche
esistono: `test_property_soldi.py`, 12 verdi · gli invarianti girano in produzione: 3 agganci
in `fase83_server.py`). Restano **gli orologi di prova Stripe**, che non esistono: servono a
vedere scadere hold, payout e penale senza aspettare giorni veri.

### Il Giudice non sa sommare i giri
Cinque giri separati non scrivono la scheda, perché ognuno copre un modulo su cinque. Finché
non impara ad accumulare, la casella della mutazione resta vuota anche a lavoro fatto.
Mezz'ora di lavoro.

### 🔴 UN TIMEOUT ESCE COME `[FAIL]`, E UN «NON LO SO» TRAVESTITO DA «È ROTTO» FA PERDERE UN'ORA
*(misurato il 2026-08-23, giro completo della batteria: avvio 12:54:07, fine 13:56:53, `RIEPILOGO: 24 OK · 2 FALLITI · 1 saltati`, uscita 1.)*

Le **due fasi fallite sono cadute sul proprio tetto di tempo**, non su una prova che ha detto no:
```
[FAIL] 3. Mutazione                                        (900s)  <- tetto 900  (batteria.py:145)
[FAIL] 6c. Multi-vettore (rete+pannelli+tamper+finanza)    (700s)  <- tetto 700  (batteria.py:150)
   [X] 3. Mutazione -> TIMEOUT
   [X] 6c. Multi-vettore -> TIMEOUT
```
⛔ **La prova che è il tetto e non il prodotto**: lo **stesso giorno**, nel giro precedente ucciso
da fuori a 55 minuti, la fase 3 sullo **stesso codice e sulla stessa macchina** aveva chiuso
`[OK  ] 3. Mutazione (653s)`. **247 secondi in più e diventa rossa.**

### 🎯 E POI L'ABBIAMO MISURATO: LA FASE 3 VARIA DEL 27% DA SOLA
*(prova fatta il 2026-08-23 alle 16:38-17:03, per ordine del fondatore: la fase 3 **due volte di
fila**, partenza pulita, **niente toccato in mezzo**.)*

```
                       GIRO 1        GIRO 2
durata                 858s          625s          <- scarto -27,2%
mutanti provati        60            60
uccisi / sopravvissuti 60 / 0        60 / 0
uscita                 0             0
sha256 dei 12 bersagli tutti identici (nessun mutante lasciato, in nessuno dei due)
traccia dopo           pulita        pulita
```

⛔ **Stesso identico lavoro, 233 secondi di differenza.** Con le quattro misure che abbiamo —
**653s · >900s · 858s · 625s** — questa fase gira fra i **10 e i 15 minuti** senza che cambi
niente. Quindi:

🎯 **IL TETTO DI 900s STA DENTRO LA VARIABILITÀ NATURALE DELLA FASE: non misura il prodotto,
tira a sorte.** Il `[FAIL]` del pomeriggio non era un segnale, era il lato sbagliato di una
moneta. ⛔ E questo **non autorizza ad alzarlo**: autorizza a smettere di chiamarlo `[FAIL]`.

❌ **Le due spiegazioni comode sono cadute tutt'e due, e con la misura in mano:**
· **il recupero non c'entra** — nessuno dei due giri ne ha fatto uno, e differiscono lo stesso;
· **il calore non c'entra**, e in direzione **opposta**: il giro 1 è partito su una macchina
appena uscita da 5 minuti di carico su tutti e 16 i thread ed è il **più lento**; il giro 2 è
partito dopo altri 14 minuti di carico ininterrotto ed è il **più veloce**.
> **La prova del calore, fatta a parte lo stesso giorno.** Sotto carico su tutti i core la CPU
> scende da **145% a 107%** della frequenza base in 5 minuti (−26%, la ventola singola non
> tiene): **è vero e va saputo**. Ma su lavoro a **un processo solo** — cioè il nostro — lo
> stesso compito a freddo e subito dopo il carico costa **1,808s contro 1,813s: +0,3%**. E nei
> due giri veri della batteria la **fase 1** (30 minuti di suite) è passata da 1775s a 1802s,
> **+1,5%**: se fosse la macchina, sarebbero rallentate tutte le fasi, non una.
> ⚠️ Il primo tentativo di questa prova usava un'unità di lavoro da **19 millisecondi** e ha
> stampato «ripresa +404%», che è impossibile: a quella scala misurava su quale core Windows
> ti mette (**6 veloci e 4 lenti**), non la frequenza. Buttato e rifatto con un'unità da 1,8s.

✅ **E una cosa che non cercavamo:** quando la fase arriva in fondo, arriva **60 uccisi su 60,
zero sopravvissuti, uscita 0**. Il rosso del pomeriggio non nascondeva nessun difetto.

⚠️ **Resta senza risposta il *perché* vari del 27%**: 233 secondi su 60 mutanti sono ~4 secondi
a mutante, e il sospetto è l'avvio dei processi più l'antivirus che ispeziona ogni python nuovo.
**Non è misurato**, quindi resta un sospetto e non un fatto.

Il difetto **non è che sfora**: è che **`[FAIL]` dice due cose diverse con la stessa parola.**
Un tetto scaduto è un **NON ESEGUITO** — non sappiamo cosa avrebbe detto quella fase — ma esce
identico a una prova che ha trovato un guasto. La batteria ha già la forma giusta per dirlo:
`[~]` con il motivo scritto, come fa la fase 9 saltata. Le due fasi scadute vanno in quella
colonna, con **quanto mancava** accanto.

✅ **E il giudice esterno l'ha confermato lo stesso giorno**: nella CI della PR #96, su Linux, il
job **`mutazione` è verde**. Stesso codice, macchina diversa, nessun tetto sforato — il rosso
locale era il **cronometro**, non il prodotto. È esattamente ciò per cui la regola ferrea 8 dice
che il verde locale è un indizio: qui è servito **al contrario**, per assolvere un rosso locale.

⛔ **E il tetto non si alza per far tornare il verde** — lo dice la batteria stessa quando
recupera: *«Il tetto NON e' stato alzato: guarda perche' ha sforato.»* Alzarlo è la cura che
nasconde la domanda; la domanda è **perché la stessa fase ha preso 247s in più**.

⚠️ **Costo già pagato, e non è teorico**: il giro ucciso aveva lasciato **`fase83_server.py`
MUTATO** sul disco. L'ha ripristinato la batteria all'avvio successivo, da sola e alzando
l'allarme — controllato dopo il giro, in produzione **nessun mutante rimasto** (le uniche
differenze di contenuto sono i 5 file del lavoro in corso; altri 10 file risultano toccati ma
sono **byte per byte identici a git**). Ma quella rete di recupero è **una casella sola, non
rientrante**: ha salvato questo colpo perché i giri erano in fila. Due giri insieme e non salva
più niente.

⚠️ **E quei 10 file restano sporchi in `git status` per un motivo che non è il contenuto:
l'attrezzo di mutazione li riscrive con i fine-riga cambiati.** Misurato il 2026-08-23:
```
fase83_server.py     (toccato dalla mutazione)  CR=0     LF=11217
fase59_concierge.py  (non toccato)              CR=675   LF=675
```
`git diff` non mostra niente perché normalizza, ma `git status` li segna `M` per sempre. Il
danno non è il carattere: è che **dieci file di produzione risultano modificati a ogni giro**, e
in quel rumore un mutante vero rimasto lì in mezzo non si distingue da un fine-riga.

### 🔴 DUE MACCHINE MISURANO LO STESSO LAVORO, E GIÀ NON SONO D'ACCORDO
*(trovato il 2026-08-22 mentre si cercava dove fossero «gli 11 test presi da AWS».)*

Due delle **6 caselle del Blocco 1** (`collaudi/piano.py`) e due dei **5 LAVORI OBBLIGATORI**
(`collaudi/regole_avvio.py`, `LAVORI_IN_SOSPESO`) sono **lo stesso lavoro scritto in due file**:

| il lavoro | in `piano.py` | in `regole_avvio.py` |
|---|---|---|
| orologi di prova Stripe | casella 3 | lavoro 3 |
| metamorfici sull'aritmetica dei soldi | casella 4 | lavoro 4 |

⛔ **E sul secondo si contraddicono già**, misurato lo stesso giorno:
```
python collaudi/regole_avvio.py       -> ⚠️ META' — trovato: test_property_soldi.py,
                                          test_fase119_calendario_prezzi.py
python collaudi/scheda.py --blocco 1  -> ☐ mai misurata: nessun attrezzo ha ancora
                                          scritto questa casella
```
Due macchine, la stessa domanda, **due risposte**. Non è la malattia delle sette liste — questi
elenchi hanno **scopi diversi e legittimi** — ma è **due misuratori dello stesso fatto**, che è
il modo in cui quella malattia comincia. La cura non è cancellare un elenco: è che **uno solo
misuri**, e l'altro vada a leggere da lui.

⚠️ **Da non confondere, e la confusione è già costata una sessione il 2026-08-17.** Le **11
tecniche di verifica** stanno in `REGISTRO_INGEGNERIA.md` fra `TECNICHE-INIZIO` e
`TECNICHE-FINE`: dichiarate 11, **contate 11**, e sono **nostre — AWS non c'entra**, lo dice il
documento in maiuscolo. Un terzo elenco ancora sono i **14 «attrezzi obbligatori»** di
`piano.py`, dove `gare` e `concorrenza` sono **la stessa tecnica con due nomi**.

### 63 moduli costruiti e mai collegati
`python collaudi/raggiungibilita.py` → 88 raggiungibili su 151. Trentaquattro sono il vecchio
impianto (Mango) e vanno solo dichiarati morti. Gli altri sono roba costruita e mai accesa:
lista dei desideri, chatbot, notifiche sul telefono, traduzione recensioni.
⚠️ Fra questi c'è **`fase15_idempotency`**, che serve a non addebitare due volte la stessa
carta: costruito, non collegato.

### 🔴 IL PARACADUTE LO AGGANCIA UNA PERSONA, E QUATTRO VOLTE LO HA AGGANCIATO STORTO
Il paracadute `:prec` lo aggancia una persona a mano ed è stato agganciato all'immagine
sbagliata **4 volte in 4 giorni** (stasera era giusto, ma **per caso**). Va fatto dallo script
di deploy: legge l'immagine viva, ci aggancia `:prec`, verifica che coincida, e **se non
coincide SI FERMA invece di deployare**.

> **La prova che stasera era giusto, e come si rifà** — misurata il 2026-08-22 sul *contenuto*,
> non sulla data (la data ingannava: l'immagine viva risultava costruita ore prima del commit):
> ```
> casavip-app:latest -> fase83_server.py sha256 db50cd07fe1bb95b  = 28c35c6 (master)
> casavip-app:prec   -> fase83_server.py sha256 a925e5fc2fd9503a  = 4e31d32 (il precedente)
> ```
> ⛔ **Un paracadute agganciato all'immagine sbagliata è peggio di nessun paracadute**: ci si
> salta convinti di tornare all'ultimo stato buono. Ed è l'obbligo che si è rotto più volte di
> ogni altro in questo progetto — la prova che un obbligo affidato alla memoria si rompe, e
> uno affidato a un attrezzo no.

### Cose minori, con la loro prova
- **DMARC è `p=none`**: la firma della posta c'è ma non blocca chi ti imita. Va alzato a
  `quarantine` in due passi, mai a `reject` in uno solo.
- **Il percorso del bunker fa perdere la chiave**: «Rimborsa» chiede lo sblocco, lo sblocco
  porta dentro il bunker dove quell'operazione non esiste, e tornando indietro il campo è
  vuoto. Non verificabile da un comando: va provato cliccando.
- **Facebook**: l'applicazione Meta è bloccata da loro. Il lavoro automatico è spento nel
  crontab. Può sbloccarla **solo il fondatore**, su `developers.facebook.com`.
- **La chiavetta fisica** è ferma al 13 agosto (121 commit indietro). Per decisione del
  fondatore la copia fisica si fa **alla fine**, quando la macchina è dichiarata sicura.

---

# 🧭 PASSAGGIO DI CONSEGNE — 2026-08-24 notte

## 📍 DOVE SIAMO — misurato adesso, non ricordato

| Posto | Valore | Come si ricontrolla |
|---|---|---|
| **Computer** | `04f2ecd`, ramo `tetto-regali-2026-08-24` | `git rev-parse --short HEAD` |
| **GitHub** (`origin/master`) | `8d1f233` | `git ls-remote origin refs/heads/master` |
| **VPS** (`git HEAD`) | `8d1f233` | `ssh … 'cd /var/www/bookinvip && git rev-parse --short HEAD'` |
| **Immagine viva** | `sha256:80f21d8…` (codice di **`b797d46`**) | `docker inspect --format='{{.Image}}' casavip_app` |

🔴 **E QUI C'È UNA COSA NUOVA, che ieri non c'era.** Fino a ieri avevo toccato **solo `.md`**,
che nell'immagine non entrano: «immagine indietro» era normale e dichiarato. **Da stanotte no.**
`fase83_server.py` è cambiato: l'immagine viva **non contiene la riparazione**, e per portarcela
serve un **deploy vero con rebuild** (D17, paracadute `:prec` ri-agganciato **prima** del build e
verificato per contenuto).

> 🛑 **IL DEPLOY È RIMANDATO A DOMANI PER DECISIONE DEL FONDATORE (2026-08-24 notte):**
> *«il deploy lo facciamo domani, non stasera: tocca il codice e voglio la testa fresca».*
> ⛔ Non è una dimenticanza e non va «recuperato» da chi legge: è una scelta. Il difetto che
> resta in produzione un giorno in più è **B11**, e in produzione ci sono **0 host firmati e 0
> annunci veri** — quindi il costo dell'attesa è zero.

## ✅ COS'È SUCCESSO — quattro difetti scritti, uno riparato

**Unita in `master`: PR #101** (`8d1f233`) — B8, B9, B10, B11 in sezione B. Solo documenti.
**Verificata UNITA dall'API**, non da un documento: `merged: True`, `merged_at 2026-08-23 20:57`.

**Aperta e NON unita: PR #102** (`04f2ecd`) — la riparazione di B11 (idea C).
```
https://github.com/edilmax/Core_Auto/pull/102     open · merged: False
CI al momento della scrittura: 15 job · 10 successo · 1 saltato · 4 IN CORSO · 0 falliti
```
⛔ **«4 in corso» non è «verde»**: la tabella si rilegge dall'API prima di unire (regola ferrea 8).

**La riparazione, in una riga:** `fase83_server._commissione_regalabile()` sottrae dalla
commissione lo sconto già finanziato all'ospite, **nei due punti** che regalano
(`fase83_server.py:5910` e `:8170`). Il saldo per prenotazione non può più andare negativo:
peggio **+0,02** invece di **−23,31**.

**Guardia:** `test_regali_non_superano_la_commissione.py`, 5 collaudi, **vista rossa prima** su
tutt'e due i cammini; il secondo provato iniettando il guasto **con l'editor** e ripristinando
con **sha256 identico** (`8e525d20…`).

## 🧾 LE MISURE DI STANOTTE, col comando che le ha prodotte

```
python -m unittest discover -s . -p "test_*.py"        (da PowerShell)
Ran 5980 tests in 2286.486s
OK (skipped=4)
CODICE USCITA: 0          <- letto DAL FILE, senza tubi (regola ferrea 7)

python collaudi/audit_millimetrico.py
VERDETTO: 0 DISCREPANZE — i 5 documenti rispecchiano il motore al millimetro   exit 0

caricatore: 5985 raccolti · 5980 eseguiti
scarto 5: le guardie openssl, che PowerShell non ha (D23 punto 3)
```

## 📋 COSA RESTA — dieci voci in sezione B, e l'ordine è tuo

**Domani, per prima cosa:** rileggere la CI della **#102** dall'API, unirla, **poi il deploy con
rebuild** (D17). È l'unico lavoro che ha già tutto pronto e aspetta solo una testa riposata.

**Bloccano l'apertura:** B2 chiavi provvisorie · B3 rimborso mai provato con soldi veri ·
B4 la commissione sul rimborso pieno *(tua decisione)* · B5 `fase59` mai giudicato ·
B6 nessun oracolo sul payout · B7 riconciliazione contro se stessa · B8 la homepage dice il
falso in 8 lingue · B9 il credito vale zero per gli host in promo · B10 credito al portatore
*(tua decisione)* · **B11 🟠** saldo chiuso, **«nessuno somma» aperto**.

**Tre decisioni tue, e sono legate:** B4, B10 e l'**idea A** di B11 (il posto unico che somma,
5-8 giorni). Finché nessuno somma, ogni scelta sui crediti si fa alla cieca.

## ⚠️ COSA NON È COMMITTATO

**Questo blocco di consegne è scritto sul disco ma NON è committato.** Serve un «procedi al
commit» — e siccome tocca un `.md`, prima serve la **suite intera** un'altra volta (regola
ferrea 6, nessuna eccezione per i documenti).

## 🩹 GLI SBAGLI DI STANOTTE — due, e tutti e due presi da una guardia scritta prima

1. **Ho aggiornato il numero dei TEST e non quello dei FILE di test.** La suite è uscita **1**.
   L'ha preso `test_L_AUDIT_MILLIMETRICO_VIENE_ESEGUITO_DAVVERO` (`atteso=405, trovato=404`).
2. **E l'ho cercato nel posto sbagliato:** ho riparato `RIPRENDI_QUI.md` dando per scontato che
   fosse quella la riga, e l'audit è rimasto rosso. Il numero lo legge da **`README.md`**
   (`collaudi/audit_millimetrico.py:47`). È la **S2** — indovinare invece di leggere — e stavolta
   l'ho fatta *mentre riparavo un'altra svista dello stesso tipo*.

> 💡 **La lezione di stanotte è una sola, e vale più della riparazione:** il difetto di B11 non
> era il tetto sbagliato. Era che **la stessa regola sui soldi viveva in due punti di chiamata**,
> e ripararne uno solo l'avrebbe lasciata viva sull'altro **senza che nessun collaudo se ne
> accorgesse**. Il secondo punto è saltato fuori da un `grep`, non dalla memoria.

---

# 🧭 PASSAGGIO DI CONSEGNE — 2026-08-23 sera

## 📍 DOVE SIAMO — quattro numeri, misurati stasera

| Posto | Valore | Come si ricontrolla |
|---|---|---|
| **GitHub** (`origin/master`) | `d11cab5` | `git ls-remote origin refs/heads/master` |
| **VPS** (`git HEAD`) | `d11cab5` | `ssh … 'cd /var/www/bookinvip && git rev-parse HEAD'` |
| **Immagine viva** | codice di **`b797d46`** | l'impronta dei suoi 152 file = quella ricostruita da git |
| **Computer** | `ceac080`, ramo `consegne-2026-08-22` | albero identico a master (`620f3d92…`) |

⚠️ **L'immagine viva è a `b797d46` e NON è un ritardo:** `d11cab5` aggiunge solo questo
documento, che nell'immagine non entra. `DEPLOY.md` lo dice: modifiche ai soli `.md` → `git
pull`, **niente rebuild**. Il sito non è ripartito: `casavip_app` è su da ore, healthy.

⛔ **Questi numeri invecchiano. Il primo gesto di domani è rimisurarli, non rileggerli qui.**

## ✅ COS'È SUCCESSO OGGI — B1 chiuso, e provato sui dati veri

**La vetrina non mente più.** Oracolo indipendente sui dati **veri** di produzione:
```
prima:  2 annunci pubblicati · 2 dicono il falso   (uscita 1)
dopo:   2 annunci pubblicati · 0 dicono il falso   (uscita 0)
```
`filippine-makati` e `filippine-makati-2`: da **100** a **9000 cents**, cioè la notte
prenotabile più economica. Il numero visto è il numero pagato.

⛔ **E la cosa da ricordare non è il verde: è che fra «prima» e «dopo» NON c'è il deploy, c'è
il RICALCOLO.** Dopo il deploy lo specchio era già cablato (`specchio-prezzo(58->57)` nel
rendiconto d'avvio) e l'oracolo era **ancora rosso 2 su 2**. **Un deploy non è una migrazione
dei dati.** Con 500 annunci veri starebbero mentendo tutti e 500 — ed è per questo che il
**comando di ricalcolo** è in sezione C, prima del primo host vero.

Il resto della giornata, in breve: quattro richieste unite (**#96** lo specchio del prezzo,
**#97** la mappa dei 39 pezzi, **#98** la misura sulla fase 3, **#99** la chiusura di B1), tutte
con **16 job su 16 verdi**; deploy `a8007d6 → b797d46` in **35 secondi**, paracadute
ri-agganciato **prima** del build e verificato per contenuto; `verifica_produzione.py` **190
controlli, 0 violazioni**.

## 📋 COSA RESTA

**Bloccano l'apertura (sezione B, sei voci):** B2 chiavi provvisorie · B3 rimborso mai provato
con soldi veri · B4 la commissione sul rimborso pieno *(decisione tua)* · **B5** `fase59_concierge`
mai giudicato dalla mutazione · **B6** nessun oracolo sul payout · **B7** la riconciliazione
chiude contro se stessa. Stima onesta per gli ultimi tre: **B5 3-5 giorni · B6 2-3 · B7 4-7**.

**Prima del primo host vero (sezione C):** il **pezzo 3** (una casella prezzo sola nel pannello
invece di due quasi identiche) e il **comando che ricalcola tutti gli annunci in una volta**.

**Una domanda aperta, non un lavoro:** il **cambio data** non esiste come funzione. Decisione
del fondatore, da prendere prima di aprire.

## 🌅 IL PRIMO LAVORO DI DOMANI

⛔ **Prima di tutto: rimisurare.** `git rev-parse --short HEAD` · `git status --porcelain` ·
`git ls-remote origin refs/heads/master` · lo stesso sul VPS · `python collaudi/regole_avvio.py`
· `python collaudi/piano.py` e `python collaudi/scheda.py --blocco 1`.

Poi: **B5 — `fase59_concierge` sotto mutazione.** È il primo dei tre nell'ordine che hai dato, è
il modulo che **calcola il prezzo del soggiorno**, e si sovrappone alla casella della mutazione
del Blocco 1: un lavoro solo che ne chiude due.
> ⚠️ **B5 vuole la macchina tutta per sé.** La traccia della mutazione è **una casella sola** in
> `%TEMP%`, e il gancio `pre-commit` la legge: mentre gira un giro di mutazione **nessun altro
> può committare**. Con un giro completo da 4 ore va saputo prima, non scoperto alla fine.
> 💡 Se preferisci partire da **B6** (l'oracolo del payout) è più contenuto e non blocca la
> macchina: si può fare accanto a B5 in un worktree separato. L'ordine resta tuo.

## 🩹 GLI SBAGLI DI OGGI — otto, e sette sono due sbagli soli

Scritti perché non si ripetano, non per contrizione. **Nessuno è arrivato in produzione**: li ha
fermati tutti o una guardia o un controllo, e questo è il punto.

**Famiglia 1 — ho inventato un nome invece di leggerlo (è la S2, tre volte in un giorno).**
1. Sonda negativa su `/api/admin/stato`: **indirizzo inventato**, risponde 404, e un 404 come
   prova di sicurezza vale zero (D17). Rifatta con `collaudi/verifica_produzione.py`.
2. Colonna `pubblicato` in una query SQL: **non esiste**, la colonna è `stato`. Letto lo schema.
3. Attributo `catalogo` dato per buono senza guardare: quello era giusto, ma non lo sapevo.

**Famiglia 2 — ho misurato con lo strumento sbagliato (è la S3/S15, tre volte).**
4. Prova del calore con unità di lavoro da **19 millisecondi**: ha stampato «ripresa **+404%**»,
   che è impossibile. A quella scala misurava su quale core Windows ti mette (**6 veloci e 4
   lenti**), non la frequenza. Rifatta con un'unità da 1,8s, **provata in piccolo prima**.
5. Impronte immagine-contro-git confrontando **561 file da git** contro i **152** che
   l'immagine contiene: zero riscontri su tutt'e due. Il Dockerfile lo diceva («i test NON
   entrano»).
6. Un **solo file** per inchiodare un commit: `fase83_server.py` è identico in **13 commit di
   fila**. Serve l'impronta di tutti i 152.

**Famiglia 3 — le due che hanno funzionato come dovevano.**
7. `crea_sistema()` senza configurazione costruisce un sistema **spento su `:memory:`**: avrebbe
   stampato un successo **senza toccare niente**. L'ha fermato una guardia scritta prima
   («MISURA NON VALIDA, non tocco niente»), due volte di fila.
8. Riga `CONSEGNE AGGIORNATE A:` lasciata indietro **due volte**: l'ha beccata il **pre-volo**
   (controllo 2 rosso), non io.

> 💡 **La lezione unica dietro tutti e otto:** ogni volta che ho preso un nome o un numero
> **dalla memoria invece che da un comando**, ho sbagliato. Ogni volta che l'ho preso da un
> `ls`, un `grep`, uno schema o un contatore, no. E le uniche due volte in cui uno sbaglio
> **non è costato niente** sono quelle in cui c'era una guardia scritta **prima**.

---

# 🧭 PASSAGGIO DI CONSEGNE — 2026-08-22 sera

**DA DOVE SI RIPARTE DOMANI, in quest'ordine.** Non serve leggere altro: la prima riga di
questo file dice già il comando che produce la lista.

**1. Il guardiano dei soldi deve MISURARE, non leggere.** `collaudi/piano_dei_soldi.py` ricava
lo stato dei moduli da **tre frasi in italiano** dentro questo documento (tre espressioni
regolari su prosa scritta a mano). È l'ultimo posto dove è rimasta la malattia del 22 agosto,
ed è proprio quello che sorveglia i soldi. **Due o tre ore**, e ogni giudizio va rivisto nelle
due direzioni perché è il guardiano che ferma il commit.

**2. Poi la sezione B**, che ha quattro voci e una sola blocca davvero: **i due prezzi che non
si parlano** (`p_prezzo` → vetrina, `d_prezzo` → cassa, nessuna guardia).

**COSA È SUCCESSO OGGI, in tre righe.** Il fondatore ricordava «5 fasi, il Blocco 1 era
finito»; lo strumento rispondeva «0 su 6». **Nessuno dei due sbagliava: contavano cose
diverse**, e c'erano due liste con lo stesso nome. Da lì: una lista sola, la guardia che lo
impedisce, e questo file da 10.178 righe a 250.

**IL NUMERO CHE CONTA, e prima di oggi non esisteva:** 246 punti del percorso del denaro
giudicati coi test giusti → **101 uccisi, 140 SOPRAVVISSUTI**. Il prodotto funziona (un euro
vero è tornato indietro); quello che manca è **la rete che se ne accorge quando si rompe**.
Sono test da scrivere, non prodotto da rifare.

**⚠️ TRE COSE CHE HO SBAGLIATO OGGI, scritte perché non si ripetano.**
- **Ho lanciato la suite da Git Bash due volte** (sbaglio S11/D23): da lì `openssl` c'è e da
  PowerShell no, quindi il giro non misura la stessa macchina. Costo: 28 minuti. Una guardia
  esisteva già e mi ha preso — `test_la_suite_non_gira_da_GIT_BASH`.
- **Ho misurato `openssl` lanciando PowerShell da dentro Bash**, e ha ereditato il PATH di
  Bash: risposta «PRESENTE», falsa. Dalla shell vera è **ASSENTE**. La stessa domanda dà due
  risposte a seconda di chi la fa.
- **Ho scritto il numero della suite prendendolo dall'output** (`Ran 5938`) invece che dal
  caricatore (**5943**). Sono due cose diverse: la differenza sono le 5 guardie messe da parte
  senza `openssl`. È la D22, e la guardia mi ha preso.

💡 Tutte e tre le volte **mi ha fermato una macchina, non la mia attenzione.** È l'unico
motivo per cui i numeri di questo progetto valgono qualcosa.

---

> ⛔ **COME SI USA QUESTO FILE.** Una voce si toglie **quando è fatta**, non si archivia e non
> si barra: resta in `REGISTRO_INGEGNERIA.md` col racconto di come è andata. Una voce nuova
> entra solo con **la misura che la dimostra**, e con il comando che l'ha prodotta accanto —
> altrimenti fra due settimane nessuno saprà più se è ancora vera. È esattamente così che
> siamo arrivati a sette liste.
