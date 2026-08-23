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
CONSEGNE AGGIORNATE A: a8007d6

SUITE ATTUALE: Ran 5980 test
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
| **La macchina è sorvegliata** | 151 moduli · 404 file di test · **5.980 test** · 0 moduli che nessun test nomina |

---

# B) COSA MANCA PER APRIRE AL PUBBLICO — quattro cose, non una di più

### 🔴 B1 — I DUE PREZZI CHE NON SI PARLANO
Il pannello host ha due caselle prezzo (`p_prezzo` → vetrina, `d_prezzo` → cassa) che nessuno
collega. Il sito mostra un prezzo e la cassa ne addebita un altro.
**BLOCCA L'APERTURA: rischio pubblicità ingannevole.**

> ⚠️ **NESSUN OSPITE HA MAI PAGATO IL PREZZO SBAGLIATO — e va letto prima del resto.**
> *(precisazione del fondatore, 2026-08-22.)* I due annunci che compaiono qui sotto,
> `filippine-makati` e `filippine-makati-2`, sono **annunci di PROVA del fondatore**, non
> host veri: in produzione ci sono **0 host firmati e 0 annunci veri**. E il rimborso di
> 1 € del 16 agosto è partito **dal pannello admin**, non dal lato cliente.
> ⛔ **Il difetto però è vero, ed è per questo che resta qui e blocca:** sono due caselle
> quasi identiche in due schermate diverse, tutte e due chiamate «Prezzo/notte», tutte e
> due che partono da `value="95"`. **Un host vero sbaglierebbe uguale.** Il difetto sta nel
> pannello, non in chi lo compila.

> *Misurato il 2026-08-22:* `deploy/host.html:378` («Prezzo/notte che vede l'ospite») scrive
> `prezzo_notte_cents`; `deploy/host.html:425` («Prezzo/notte») scrive `prezzo_netto_cents`,
> e i due numeri non compaiono insieme in **nessun punto del codice**. Dove va ciascuno:
> · `prezzo_notte_cents` → pagina dell'annuncio, **Google** (`"price"` in JSON-LD), anteprima
>   sui social, feed RSS, schede dei risultati, filtri e ordinamento per prezzo, mappa;
> · `prezzo_netto_cents` → **quello che si paga davvero**: `fase59_concierge.py:283` somma
>   notte per notte questo, e solo questo.

**🔑 DECISO IL 2026-08-22 (scelta B del fondatore): «il numero visto dev'essere il numero
pagato».** Con le date scelte, la scheda mostra il prezzo **di quelle date**, preso dal
calendario; senza date, «da X», dove X è la notte prenotabile più economica.

**✅ PEZZO 1 FATTO — la guardia esiste, e non c'era.** `collaudi/prezzi_coerenti.py` (sola
lettura, `mode=ro`) più 19 guardie in `test_prezzo_vetrina_e_cassa.py`. È **nata rossa** sui
dati veri, che è l'unica prova che stia guardando la cosa giusta:
> ```
> docker exec -i casavip_app python3 - --cartella /data --oggi 2026-08-22 < collaudi/prezzi_coerenti.py
> ROSSO filippine-makati · ROSSO filippine-makati-2 · 2 annunci su 2 dicono il falso · esce 1
> ```
> ⛔ **La trappola gliel'hanno insegnata i dati veri, non la fantasia:** `filippine-makati`
> ha una notte a 100 cents datata **16/08, già passata**. Un controllo che guardasse tutti i
> giorni troverebbe minimo 100, direbbe «coincide» e **assolverebbe il difetto** con un
> giorno che nessuno può più prenotare. Lo impedisce `test_LA_NOTTE_PASSATA_NON_ASSOLVE`;
> stesso trattamento per le notti chiuse, piene e a prezzo zero.

**RESTA DA FARE, in quest'ordine:**
- **Pezzo 2 — la vetrina DERIVA il prezzo dal calendario** *(tocca la produzione)*.
  `alloggi.prezzo_notte_cents` smette di essere un numero indipendente e si ricalcola da solo
  quando l'host salva la disponibilità. Ricerca, filtri, Google e mappa continuano a leggere
  la stessa colonna di prima — ma quella colonna non può più mentire.
- **Pezzo 3 — il pannello ha una casella sola** *(tocca la produzione)*: prezzo base, più
  un'eccezione per certi giorni dichiarata come tale e già riempita col prezzo base.
  Toglie la causa invece di inseguire l'effetto.

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

---

# C) DOPO L'APERTURA — tutto il resto

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

Il difetto **non è che sfora**: è che **`[FAIL]` dice due cose diverse con la stessa parola.**
Un tetto scaduto è un **NON ESEGUITO** — non sappiamo cosa avrebbe detto quella fase — ma esce
identico a una prova che ha trovato un guasto. La batteria ha già la forma giusta per dirlo:
`[~]` con il motivo scritto, come fa la fase 9 saltata. Le due fasi scadute vanno in quella
colonna, con **quanto mancava** accanto.

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
