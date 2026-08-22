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

SUITE ATTUALE: Ran 5943 test
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
| **La macchina è sorvegliata** | 151 moduli · 403 file di test · **5.942 test** · 0 moduli che nessun test nomina |

---

# B) COSA MANCA PER APRIRE AL PUBBLICO — quattro cose, non una di più

### 🔴 B1 — I DUE PREZZI CHE NON SI PARLANO
Il pannello host ha due caselle prezzo (`p_prezzo` → vetrina, `d_prezzo` → cassa) che nessuno
collega. Il sito mostra un prezzo e la cassa ne addebita un altro. Nessuna guardia esiste.
**BLOCCA L'APERTURA: rischio pubblicità ingannevole.**

> *Misurato il 2026-08-22:* `deploy/host.html:378` («Prezzo/notte che vede l'ospite») scrive
> `prezzo_notte_cents`; `deploy/host.html:425` («Prezzo/notte») scrive `prezzo_netto_cents`.
> Sui dati veri: vetrina **100 centesimi**, inventario **9000**. Non è un errore di chi
> inserisce: sono due caselle in due schermate, ed è il pannello a indurre lo sbaglio.
> Il prezzo va anche a Google (`"price"` nella scheda pubblica).

### 🔴 B2 — LA CHIAVE DEL PANNELLO AMMINISTRATORE È CORTA
`ADMIN_KEY` = **11 caratteri**, misurata nel contenitore che gira. Tutte le altre sono lunghe
(`HOST_KEY` 64 · `CASAVIP_SEGRETO` 64 · `STRIPE_WEBHOOK_SECRET` 38 · `BUNKER_PASSWORD` 23).
È l'unica corta, ed è quella che apre il pannello **da cui si fanno i rimborsi**.

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
