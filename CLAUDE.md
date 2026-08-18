# ⛔⛔ IL BLOCCO — 6 DIVIETI ASSOLUTI (vengono PRIMA di tutto, anche della Regola Zero)

Dettati dal fondatore il **2026-08-03**, dopo una sessione in cui ho interpretato come
autorizzazione frasi che non lo erano, ho usato `sed` per una patch, e ho risposto con
riassunti dove servivano i dati grezzi. **Non sono consigli: sono divieti.** Si leggono
**PRIMA** di iniziare qualunque operazione, e **si rileggono DOPO averla finita**.

**B1. NON COMMITTARE MAI finché il fondatore non ha detto esplicitamente «procedi al
commit».** «Aspetta» non è un via. «Ok» non è un via. «Poi commit push» non è un via.
Solo **«procedi al commit»** è un via.
*Si verifica:* nel registro della sessione, prima di ogni `git commit` compare quella frase
esatta scritta dal fondatore. Se non c'è, quel commit non doveva esistere.

**B2. NON USARE MAI `sed`, heredoc o sostituzioni testuali per modificare un file.** Si usa
**sempre** l'editor. È la D9, elevata a divieto assoluto perché ha già fatto danno tre volte
in due giorni: due file di strumenti resi illeggibili e una riparazione che **non è stata
applicata affatto** (i backslash mangiati, la stringa di sostituzione diventata identica a
quella da sostituire).
*Si verifica:* nel registro della sessione nessun `sed -i`, nessuno script con `.replace()`
su un file del progetto. Unica eccezione ammessa: byte non scrivibili in un messaggio, e
allora si costruiscono per **valore numerico** e si mostra il conteggio dei byte cambiati
prima e dopo.

**B3. NON RIASSUMERE MAI al posto dei dati grezzi.** Se il fondatore dice «mostrami», si
mostrano **il comando eseguito e l'output copiato dal terminale**. Nessuna tabella. Nessun
riepilogo. Nessuna parafrasi.
*Si verifica:* ogni risposta a un «mostrami» contiene la riga di comando e l'uscita
letterale. Una tabella al posto dell'output è una violazione, anche se i numeri sono giusti.

**B4. NON TOCCARE MAI codice di produzione senza il via scritto.** «Ripara» non è un via.
«Sistemale» non è un via. «Ok» non è un via. Solo **«autorizzato»** è un via. (Per
`collaudi/` — strumentazione di collaudo, non produzione — il fondatore ha stabilito il
2026-08-03 che questo divieto non vale allo stesso modo: vale D20.)
*Si verifica:* per ogni riga cambiata in un `fase*.py` o in `main_casavip.py`, nel registro
della sessione compare la parola «autorizzato» scritta dal fondatore **prima** della modifica.

**B5. NON PROCEDERE MAI al passo successivo se il precedente non è verificato.** Se vengono
chieste quattro cose e se ne mostrano tre, ci si ferma. Mai «procedo con quello che ho».
*Si verifica:* per ogni sequenza richiesta, ogni passo ha il suo esito mostrato prima che
inizi il successivo; se un esito manca o non è quello specificato, la sequenza si interrompe
lì e lo si dice.

**B6. NON DICHIARARE MAI equivalente un mutante per comodità.** O c'è una **dimostrazione
formale** (z3, prova esaustiva sugli ingressi, o percorsi che portano allo stesso stato
osservabile e verificabile), o quel mutante **resta sopravvissuto**.
*Si verifica:* ogni voce di `EQUIVALENTI_DICHIARATI` porta la dimostrazione scritta; nessuna
ha come motivazione «non è raggiungibile» o «non è osservabile» senza prova.

## ⛔ COSA FARE SE SI VIOLA UNO DI QUESTI SEI
Rispondere **esattamente** così, e poi fermarsi:

> «REGOLA VIOLATA: [nome]. MI SONO FERMATO. Aspetto istruzioni.»

Poi si aspetta. **Non si agisce. Non si committa. Non si ripara. Non si riassume.**

## ⛔ QUANDO SI RILEGGE QUESTO BLOCCO
**PRIMA** di iniziare qualunque operazione, e **DOPO** averla finita — così la fine di un
lavoro non diventa l'inizio di una violazione. Lo stampa da solo `collaudi/regole_avvio.py`
a ogni avvio di sessione; a fine lavoro va rieseguito.

---

# 🩹 IL CATALOGO DEGLI SBAGLI — si rilegge PRIMA di dire «fatto»

> **Ordine del fondatore, 2026-08-08:** *«bisogna scrivere tutti gli sbagli per non
> ripeterli più, così la nuova chat la obbligo a leggere e rileggere e non capitano più».*
>
> **Perché sta qui e non in un file nuovo.** Un elenco che nessuno rilegge non protegge
> niente; `CLAUDE.md` si carica a **ogni** sessione, e i file nuovi sono vietati (REGOLA
> ZERO 3). **Non sono nuovi obblighi**: sono quelli che già ci sono, visti dal lato in cui
> si rompono. Ognuno è uno sbaglio **fatto davvero**, con la data, come si è visto, e la
> riga che lo impedisce.

**S1. HO CONFRONTATO DUE COSE VUOTE E HO SCRITTO «UGUALI».** *(2026-08-08)* Un controllo
sulle impronte di `fase186_guardiano_stati.py` — nome che avevo **inventato** — ha stampato
`UGUALI` confrontando due stringhe vuote.
*Si impedisce così:* un confronto che riceve il **vuoto** non dice «uguali», dice **«misura
non valida»** e si ferma. Il vuoto non è un valore: è l'assenza di misura.

**S2. HO INVENTATO NOMI INVECE DI LEGGERLI.** *(2026-08-08, due volte in un'ora:
`fase186_guardiano_stati.py`, `fase98_prezzi.py`)*
*Si impedisce così:* un nome di file, funzione o rotta si prende da un `ls`/`grep`, **mai
dalla memoria**; e un controllo che non trova il bersaglio è **ROSSO**, non muto.

**S3. HO CERCATO IL COLPEVOLE NEL CODICE MENTRE MENTIVA LO STRUMENTO.** *(2026-08-08)* Una
diagnosi intera spesa su un `except` innocente: il difetto vero era che il banco di prova
scriveva i database in un posto che moriva con lui.
*Si impedisce così:* **quando una misura è assurda, il primo sospetto va allo strumento, non
al codice.** Un ramo `except` è un sospetto comodo perché si vede; uno strumento che misura
la macchina sbagliata non si vede — ed è per questo che costa di più.

**S4. HO CHIAMATO «VARIABILI» QUELLO CHE ERANO RIGHE.** *(2026-08-08)* «125 contro 88» mi ha
mandato a caccia di 37 variabili che non esistevano: erano doppioni della stessa.
*Si impedisce così:* un numero dichiara **cosa conta** — righe o nomi distinti, raccolti o
eseguiti — altrimenti non è un numero, è un'impressione con le cifre.

**S5. HO SCELTO L'ATTREZZO PIÙ ELEGANTE SENZA GUARDARE CHI LEGGE.** *(2026-08-08)* Una nota
di credito al posto della riga di rimborso: più corretta in astratto, e avrebbe fatto finire
la **stessa** cancellazione nel report fiscale solo se la faceva l'host.
*Si impedisce così:* **prima di scegliere l'attrezzo, si guarda CHI LEGGE il registro.**
Un'imprecisione uniforme è meglio di una correttezza a macchie.

**S6. HO SCRITTO UNA GUARDIA CHE UN COMMENTO POTEVA SODDISFARE.** *(2026-08-08)* Contava
`tipo="rimborso"` ovunque nel sorgente, commenti compresi: cancellando una chiamata vera il
conto restava buono e la guardia taceva.
*Si impedisce così:* una guardia che conta nel sorgente conta solo le righe **eseguibili**,
e la si vede rossa **togliendo la cosa vera**, non una a caso.

**S7. HO SCRITTO UN CONTROLLO CHE DAVA OK QUANDO LA PREMESSA MANCAVA.** *(2026-08-08)*
«controversia OK» anche quando la controversia non era stata nemmeno aperta.
*Si impedisce così:* se manca la premessa il controllo **non è verde: è NON ESEGUITO**, e
finisce in un elenco che si legge in fondo al rapporto.

**S8. HO LANCIATO UN LAVORO DA 70 MINUTI CON UN GUINZAGLIO DA 10.** *(2026-08-08)* La suite
è stata uccisa a metà e il file troncato somigliava a un esito.
*Si impedisce così:* un lavoro lungo si **stacca** dallo strumento che lo lancia e **si
scrive da solo il codice d'uscita in fondo al file**. Senza quella riga finale, quel file
non è un esito e non si commenta.

**S9. HO RISPOSTO CON TANTE CAUTELE CHE NON SI CAPIVA SE ERA FATTO.** *(2026-08-08)* Il
fondatore ha dovuto chiedere tre volte «risolto?», e una volta «rispondi solo sì o no».
*Si impedisce così:* **prima la risposta, poi i dettagli.** Una cautela che nasconde la
risposta non è prudenza: è disinformazione gentile.

**S10. HO LASCIATO IL DOCUMENTO A DICHIARARE IL FALSO.** *(2026-08-08)* Il blocco di consegne
diceva «NON COMMITTATO» mentre il lavoro era già unito **e** in produzione.
*Si impedisce così:* il documento si aggiorna **nello stesso momento** in cui cambia la
macchina — non «dopo», perché il «dopo» è dove si perde.

**S11. HO MISURATO NELL'AMBIENTE SBAGLIATO E MI SAREBBE RISULTATO UN MISTERO.** *(2026-08-10)*
La suite raccoglieva 5490 test e ne eseguiva 5485: cinque spariti. Ho cercato la causa
(`openssl` nel PATH) **da Bash, dove c'è** — mentre la suite era partita **da PowerShell, dove
non c'è**. Bash e PowerShell su questa macchina hanno **PATH diversi**: la stessa domanda dà
due risposte opposte.
*Si impedisce così:* **la verifica si fa nella stessa shell che ha eseguito la cosa.** Se il
comando è partito da PowerShell, si controlla da PowerShell. È D23 punto 3 vista dal lato in
cui si rompe: l'ambiente non è il contorno della misura, **è parte della misura**.

**S12. HO INVENTATO IL NOME DI UNA VARIABILE D'AMBIENTE.** *(2026-08-10)* Ho lanciato il banco
degli host con `$env:BANCO_PORTA="8081"`, convinto che esistesse. **Non esiste**: la porta è
cablata a `giro_banco.py:35`. Risultato: il banco ha interrogato una porta vuota e ha stampato
**21 rossi finti**, che per un istante sembravano un disastro. È la S2 (mai inventare nomi)
sopravvissuta a due giorni di distanza, in una forma nuova: non un file, una **variabile**.
*Si impedisce così:* prima di passare una variabile d'ambiente a uno strumento, `grep` del suo
nome **dentro quello strumento**. Se non c'è, quella variabile non fa niente — e il silenzio
non te lo dice.

**S13. HO DATO PER SCONTATO CHE UN FILE FOSSE IN GIT.** *(2026-08-10)* Ho versionato lo
schedario dell'attrezzo che confronta le tariffe, e ho verificato «a occhio» che comparisse.
Non compariva: la riga `*.txt` del `.gitignore` lo escludeva **in silenzio**. Sarebbe finito in
CI **senza schedario**, cioè rosso per finta a ogni giro — e il rimedio sembrava già applicato.
*Si impedisce così:* «l'ho aggiunto a git» si dimostra con **`git add --dry-run <file>`** o con
`git status --porcelain`, mai leggendo il `.gitignore` e concludendo. Un'esclusione può stare
in una riga scritta mesi prima, per tutt'altro motivo.

**S14. HO SCRITTO IL NUMERO DEI TEST DOPO LA SUITE INVECE CHE PRIMA.** *(2026-08-10, due volte
in un giorno; tre in tutto)* La guardia D22 pretende che `RIPRENDI_QUI.md` dichiari quanti test
esistono. Aggiungerne uno la fa diventare rossa — e siccome la correzione tocca un `.md`, la
regola ferrea 6 obbliga a **rifare la suite intera per una cifra**. Costo: **tre ore** su codice
che non era cambiato.
*Si impedisce così:* il conteggio **non dipende dall'esecuzione**, lo dà il caricatore da fermo
in due secondi. Si misura e si scrive **PRIMA** di lanciare:
`python -c "import unittest; print(unittest.TestLoader().discover('.', pattern='test_*.py').countTestCases())"`
Vale **anche quando non ti pare di aver aggiunto test**: rinominarne uno basta a spostare il conto.

**S15. HO CREDUTO AL VERDETTO DI UNO STRUMENTO SENZA GUARDARE CON CHE MODELLO CONTAVA.**
*(2026-08-10)* L'attrezzo dei conti ha stampato **«la tariffa tecnica NON copre Stripe A NESSUN
IMPORTO»**: stavo per riferire una perdita. Non era vero. L'attrezzo dichiarava da sé, due righe
sopra, «percentuale SECCA, nessuna quota fissa» e «zero transazioni vere»: **era lui a essere
rimasto indietro**, e confrontava il costo con un prezzo che non pratichiamo più.
*Si impedisce così:* prima di riferire il verdetto di uno strumento, si leggono **le premesse
che stampa su di sé**. Le aveva scritte in chiaro. È la S3 («quando la misura è assurda, sospetta
lo strumento») estesa al caso peggiore: **una misura non assurda, solo sbagliata**.

**S16. HO MODIFICATO UN TEST E MI SONO PORTATO VIA DUE RIGHE DI QUELLO PRIMA.** *(2026-08-10)*
Inserendo un metodo nuovo ho ancorato la modifica a righe che **non erano la fine** del metodo
precedente: due asserzioni sono finite dentro il mio, e il test è esploso con `NameError` su una
variabile che non poteva esistere lì.
*Si impedisce così:* prima di inserire un metodo si **legge fino alla riga vuota che chiude** il
precedente. Un `NameError` su una variabile di un altro test non è mai un difetto del prodotto:
è una modifica che ha tagliato dove non doveva.

**S17. HO SCRITTO IL VECCHIO NUMERO NEI COMMENTI CHE SPIEGAVANO IL NUOVO.** *(2026-08-10, sei
volte)* Mentre riparavo file che dichiaravano una tariffa superata, ho lasciato la cifra vecchia
nei **miei** commenti nuovi, nei nomi dei test e perfino nel commento della riga che serve a
impedire le cifre scritte a mano.
*Si impedisce così:* la regola l'ha dettata il fondatore ed è più forte di «aggiorna il
commento»: **un commento non nomina la cifra.** Si scrive «la tariffa tecnica», non «il 5%». Un
commento che non nomina il numero **non può diventare falso** — e un nome di test nemmeno.

**S18. HO LANCIATO LA SUITE E POI HO CONTINUATO A TOCCARE I FILE CHE STAVA LEGGENDO.**
*(2026-08-18)* Suite partita, e mentre girava ho modificato `.github/workflows/ci.yml` — che
`test_pipeline_ci.py` **legge**. Quel giro non diceva più niente su nessuna versione: né su
quella di prima né su quella di dopo. L'ho buttato e rifatto **da fermo**: un'ora persa.
E l'ho ripetuto in forma diversa più tardi, aprendo lavoro nuovo mentre un giro girava.
*Si impedisce così:* la regola ferrea 4 esisteva già; quello che mancava era l'**ordine dei
gesti**. Prima si finisce **tutto** — codice **e documenti** — poi si lancia, poi non si tocca
niente. Se durante il giro salta fuori qualcosa da cambiare, **il giro si butta subito** invece
di sperare che non c'entri: un giro che ha letto file cambiati a metà **non è un esito**.

**S19. LO SCOPO L'HO DICHIARATO DOPO, E ME L'HA DETTO UNA MACCHINA.** *(2026-08-18)* Ho aperto
e modificato cinque file senza aver dichiarato niente: nella traccia c'era ancora lo scopo
**della sessione del giorno prima**. Non me ne sono accorto io — mi ha fermato
`collaudi/prima_di_dire_fatto.py` al momento del commit, controllo 9.
*Si impedisce così:* `python collaudi/prima_di_lanciare.py --scopo <file...>` **prima di aprire
il primo file**, e si ri-dichiara ogni volta che lo scopo si allarga, scrivendo il perché
(regola ferrea 15). Costa quattro secondi. 💡 E la lezione vera è un'altra: **la regola ha
funzionato perché è agganciata a un attrezzo**. Affidata alla mia buona volontà si era rotta,
come si rompe sempre (D22).

> ⚠️ **E il più testardo di tutti, che non è mio ma del progetto:** il paracadute `:prec`
> agganciato all'immagine sbagliata — **quattro volte in quattro giorni** (2026-08-05, -07,
> -08 e -08 sera). Non lo prende la buona volontà: lo prende **D17 punto [1b]**, che lo
> ri-aggancia e si ferma se non coincide. È la prova che un obbligo affidato alla memoria
> si rompe di nuovo, e uno affidato a un attrezzo no.

---

# ⛔ REGOLA ZERO — LEGGERE PRIMA DI TOCCARE QUALSIASI COSA (vale per OGNI IA e OGNI persona)

**Questa regola viene prima di tutte le altre.** Vale per Claude e per qualunque altro modello
o collaboratore che apra una sessione su questo progetto.

**1. Le UNICHE fonti di verità sono i 5 documenti ufficiali nella cartella principale:**

| File | Contenuto |
|---|---|
| `README.md` | com'è fatta la macchina OGGI: struttura, motore, **tariffe**, **consensi**, regole |
| `REGISTRO_INGEGNERIA.md` | ogni modulo: cosa fa, se è acceso o spento, come si accende |
| `RIPRENDI_QUI.md` | stato vivo: a che punto siamo |
| `DEPLOY.md` | procedura di messa online |
| `CLAUDE.md` | questo file: le regole |

Va letto **almeno `README.md` + `RIPRENDI_QUI.md`** prima di proporre o scrivere qualsiasi cosa.

**2. `_archivio/` NON si segue MAI.** Contiene documenti storici con cifre e piani **superati**
(vecchie commissioni 15%/12%/25%, strategie abbandonate, stack legacy Mango/Tavola VIP). Si può
leggere per capire il passato, **mai** per decidere il presente. In caso di conflitto vince
sempre il documento ufficiale.

**3. ⛔ È VIETATO CREARE NUOVI FILE `.md`.** Niente nuovi documenti di strategia, niente report
duplicati, niente note storiche sparse, niente `RIASSUNTO_*.md` o `ANALISI_*.md`. Qualunque
aggiornamento **modifica uno dei 5 file ufficiali**. Se sembra servire un file nuovo, la
risposta giusta è quasi sempre una **sezione in più** in `README.md` o una **riga in più** in
`REGISTRO_INGEGNERIA.md`.

**4. I numeri non si inventano e non si ricordano a memoria: si verificano nel codice.**
Verità corrente (se cambia nel codice, va aggiornata anche nel `README.md`, e una guardia
automatica fa fallire la suite se i due divergono):
- commissione host: **0%** primi 90 giorni · **8%** fino a 1 anno · **10%** a regime
  (marketplace) · **5%** sempre sul link diretto · **0%** a carico dell'ospite;
- **tariffa tecnica 5% + 0,25 € SEMPRE dovuta dall'host** — **7% + 0,25 €** se l'annuncio è
  prezzato in valuta diversa dall'euro (il gateway deve convertire) — anche a commissione 0%.
  ⛔ Era «3%, margine piattaforma zero»: **misurato sotto costo il 2026-08-09**
  (`collaudi/conti_stripe.py`). Stripe prende percentuale **+ 0,25 € fissi**, e **+2%** sul
  cambio; e il **bonifico all'host** costa altri **0,25% + 0,10 €**. Il margine ora **non è
  zero e non si dichiara zero**: dipende dalla carta e dall'importo, e il contratto lo dice;
- registrazione e ri-accettazione: **3 spunte obbligatorie** (Contratto · clausole vessatorie
  artt. 1341-1342 c.c. · Privacy GDPR), pulsante bloccato lato browser **e** rifiuto `422` lato
  server, con prova firmata **HMAC-SHA256** (versione, impronta del testo, IP, dispositivo, ora).

**5. Prima di ogni deploy: suite INTERA verde**, poi si salva nei **3 posti**
(computer → GitHub → VPS). Ogni bug corretto lascia un test-guardia **rosso sul codice vecchio**.

---

# ⚙️ REGOLA FERREA DI OPERATIVITÀ E PRECISIONE

> ## 📌 GLI OBBLIGHI SONO **106**, E SI DIVIDONO IN DUE FAMIGLIE DIVERSE
> **Contati dai file il 2026-08-13, non a memoria** (`python collaudi/regole_avvio.py` li
> ricontrolla a ogni sessione e **grida** se questi numeri non tornano):
>
> ### 🔬 LE **44** DELLA RICERCA — pagate ~4 milioni di token, 77 agenti, 2026-07-30
> Sono l'unica famiglia con **fonte esterna** (studio, benchmark, incidente documentato),
> **prova** e **come si verifica**. Sono nate perché i collaudi davano tutto verde e poi
> uscivano le sorprese: **44 su 44 dicono come si controllano**, ed è ciò che le distingue
> da un buon proposito.
> · **15** sono qui sotto (si ricaricano a OGNI sessione, valgono a ogni lavoro);
> · **29** stanno nell'appendice di `REGISTRO_INGEGNERIA.md`, con prova e fonte per esteso.
> Più le **24 uccise** dai revisori ostili **col motivo**: dicono cosa NON vale la pena rifare.
>
> ### 🧭 GLI ALTRI **62** — nati dai NOSTRI danni
> **IL BLOCCO (6 divieti assoluti, in cima a questo file)** · Regola zero (**5**) ·
> **26 direttive del fondatore** · modi di rompersi (**11**) ·
> collaudi (**10**) · direttiva finale (**4**). Non hanno uno studio dietro: hanno una
> **cicatrice**. Valgono uguale, e da oggi **portano anch'essi il «si verifica così»**.
>
> ### ⚠️ TRE VOLTE HO SBAGLIATO IL CONTO, E OGNI VOLTA ERA LO STESSO ERRORE
> **2026-07-31**: dissi «le 14» e violai la 15 — che quel giorno stava solo nell'appendice.
> **2026-08-01, mattina**: dissi 74, ma 61 punti stavano **solo nella memoria di sessione**,
> che **non viaggia col progetto**: su un altro computer, o in CI, non esistevano.
> **2026-08-01, sera**: mescolai le due famiglie in un unico numero — e mescolare fa perdere
> di vista proprio ciò che è stato pagato.
> **Rimedio definitivo:** le direttive del fondatore sono **entrate nel repository** (D1-D26
> qui sotto), ogni regola dice **come si verifica**, e lo strumento d'avvio conta tutto e
> **segnala chi non dice come si controlla**. Una regola che non si può controllare non è
> una regola: è un desiderio.
>
> ### 📖 L'APPENDICE VA LETTA **PRIMA** DI INIZIARE, QUANDO:
> · collaudi o tocchi la **mutazione** · modifichi **codice esistente** ·
> · la sessione è **lunga o riassunta** · stai per dire **«fatto»**
>
> ⚠️ Le 29 non sono qui per una ragione tecnica precisa: `CLAUDE.md` si carica a **ogni**
> sessione, e allungarlo **peggiora** l'attenzione invece di migliorarla («context rot»).
> Un regolamento che nessuno tiene in testa non protegge nulla.

Dettata dal fondatore il **2026-07-30**, dopo una giornata in cui **tre strumenti diversi ci hanno
rassicurato mentre erano guasti**. Ogni riga qui sotto nasce da un fatto accaduto, non da una
teoria: dove c'è un esempio, è successo davvero.

**1. PRECISIONE CHIRURGICA E MINIMA INVASIVITÀ.** Si ripara **solo** lo stretto necessario —
idealmente **una riga**. Vietati: codice superfluo, funzioni non chieste, classi helper, `if`/`try`
ridondanti, file temporanei, commenti spazzatura, dipendenze nuove.
*Il fix «paganti al check-in» è costato 3 righe; riscrivere il modulo sarebbe stato un errore.*
**Si verifica:** `git diff --numstat` sul commit — righe di produzione aggiunte sotto la soglia dichiarata, e **zero** file/moduli/dipendenze nuovi non dichiarati.

**2. ZERO TOLLERANZA PER IL VERDE FINTO.** Nessun test, guardia o controllo vale finché non è stato
**visto fallire** sul guasto vero e poi visto passare, con **ripristino byte-identico (sha256)**.
Vietate le guardie e le frasi **ornamentali**, che rassicurano senza controllare nulla.
*Tre casi in un giorno: una guardia che **pretendeva** il comando che spegne il sito; un log che
scriveva «blocco temporaneo, riprovo» mentre l'app era murata; una mia prova rossa che non
riscriveva il file e passava «senza vedere niente».*
**Si verifica:** per ogni guardia nuova, nella sessione esistono i tre pezzi — il guasto
iniettato, l'esito **rosso** letto diretto, e l'impronta **sha256 identica** dopo il ripristino.
Se manca anche uno solo, quella guardia non vale ancora.

**3. ALLINEAMENTO TOTALE DELLE FONTI DI VERITÀ.** Ogni modifica reale sulla macchina (pacchetti
rimossi, pin, configurazione) va **subito** riflessa nei documenti, con la verità **verificata sul
campo**. È **vietato** scrivere nei 5 documenti un'affermazione non provata sulla macchina — anche
se «suona giusta» o se l'ha suggerita qualcun altro.
*`DEPLOY.md` prescriveva un comando rotto: la nota giusta stava solo in una memoria di sessione.
Costo: un minuto di sito irraggiungibile.*
**Si verifica:** ogni affermazione nei 5 documenti ha, nella sessione, il comando che l'ha misurata sulla macchina — altrimenti è un'opinione scritta in un posto ufficiale.

**4. MANI IN TASCA DURANTE I CICLI.** Mentre una suite o un deploy sono in corso sono
**intoccabili i file del progetto e la macchina che esegue i test**. Vietato: modificare file,
lanciare una seconda suite, fare trasferimenti pesanti. **Ammesso**: lavoro in **sola lettura su
altre macchine**. Il divieto non è formale: modificare i file sotto test produce **rossi finti**.
*Già successo tre volte in un giorno. Misurato: la stessa suite passa da 23 a 27 minuti se la
macchina lavora in parallelo.*
**Si verifica:** nessun file del progetto ha data di modifica compresa fra l'inizio e la fine dell'ultimo ciclo (suite o deploy).

**5. PULIZIA RADICALE DELLA POLVERE — MA SOLO DOPO LA PROVA.** Nessun residuo obsoleto deve
sopravvivere: vecchi backup, script morti, comandi deprecati. Se un comando è pericoloso va
**sradicato alla radice** (rimosso **e** bloccato, es. pin apt a priorità negativa) e **va
verificato che il blocco funzioni davvero**, non solo installato.
⚠️ **Si distrugge solo dopo aver dimostrato che nulla di vivo lo usa**: collegamenti del compose,
cron, unità systemd, script, e file presenti **solo** lì.
*Una pulizia «ovvia» cancellò `certbot/`: il sito rispondeva, ma il rinnovo del certificato era
morto **in silenzio**, e si sarebbe scoperto sessanta giorni dopo.*
**Si verifica:** prima di ogni cancellazione compare la simulazione (`apt -s`, elenco dell'archivio, `git diff`) e la ricerca dei riferimenti vivi; dopo, la prova che il blocco funziona davvero.

**6. SUITE INTERA ANCHE PER UNA VIRGOLA IN UN `.md`.** Nessuna eccezione, nemmeno per la
documentazione. Eseguire «solo i test che sembrano attinenti» non è consentito.
*Corretto un documento, eseguite tre guardie invece di tutte: la CI è andata rossa, perché un test
**leggeva** quel documento.*
**Si verifica:** l'ultima esecuzione prima del commit è `unittest discover` **completo**, non un elenco di moduli scelti.

**7. IL CODICE D'USCITA SI LEGGE DIRETTO, MAI ATTRAVERSO UN TUBO.** `comando | tail` restituisce
l'esito di `tail`, non del comando.
*Un `EXIT=0` su una suite che stampava `FAILED`.*
**Si verifica:** nel registro della sessione non esiste un `$?` letto dopo un `|`; dove serve un tubo si usa `${PIPESTATUS[0]}`.

**8. LA CI SU LINUX È IL GIUDICE; IL VERDE LOCALE È UN INDIZIO.** Un verde sul computer non
autorizza né tranquillità né deploy. Dopo ogni push si **guarda la tabella**.
*Ha colto due volte ciò che il verde locale non vedeva, per differenze fra sistemi operativi.*
**Si verifica:** dopo ogni push compare la tabella dei job con il verdetto del `gate`, letto dall'API — non «immagino sia verde».

**9. L'OSSERVABILE DEBOLE È UN DIFETTO.** Quando si registra il fallimento di un servizio esterno
si scrivono **codice, sottocodice e messaggio**, mai il solo stato HTTP.
*Per due giorni «400 Bad Request» ha reso indistinguibili un blocco temporaneo e un'applicazione
bloccata: due situazioni con rimedi opposti.*
**Si verifica:** ogni `logger` su un servizio esterno contiene codice, sottocodice e messaggio; un log col solo stato HTTP è un difetto aperto.

**10. UN FALSO ALLARME È UN DIFETTO QUANTO UN ALLARME MANCATO.** Insegna a ignorare i segnali. Ogni
allarme si prova nelle **due direzioni**: **tace** quando tutto è a posto, **grida** quando serve.
*Un allarme nuovo gridava su un impianto appena installato; l'ha colto un test esistente.*
**Si verifica:** per ogni allarme esistono DUE prove — una che lo fa gridare, una che pretende il suo silenzio a macchina sana.

**11. IL DIFETTO È SPESSO IN CHI CHIAMA, NON NEL PEZZO CHE MOSTRA IL SINTOMO.** Prima di toccare un
modulo che «sembra sbagliato», si guarda **chi lo usa**. È anche il modo di tenere il diff minimo.
*Il modulo del check-in era corretto: sbagliava chi gli passava il numero.*
**Si verifica:** prima di modificare un modulo compare il `grep` dei suoi chiamanti; se il difetto è a monte, il diff tocca il chiamante e non il modulo.

**12. PRIMA DI DISTRUGGERE O SOSTITUIRE, GUARDARE COSA C'È. E MAI `|| true`.** Ogni comando
distruttivo passa da una **simulazione** (`apt -s`, elenco del contenuto dell'archivio, `git diff`).
`|| true` è vietato: nasconde i fallimenti.
*Un comando suggerito cancellava un percorso «alla cieca» che su molte macchine è il collegamento
alla versione **buona**.*
**Si verifica:** nessun `|| true` introdotto nel diff (salvo passi di sola diagnosi o pulizia, dichiarati), e ogni comando distruttivo ha la sua simulazione nel registro.

**13. DATE E NOMI NON SONO PROVE: SI GUARDA IL CONTENUTO.** Un archivio si verifica **aprendolo**:
la correzione è dentro? il commit citato è quello giusto? l'impronta **sha256** coincide con
l'originale? **Un backup non verificato leggibile non è un backup.**
*La cartella della chiavetta portava la data di oggi e conteneva codice vecchio.*

**14. LE CHIAVI NON SI CHIEDONO E NON SI STAMPANO.** Se il fondatore offre password, codici o
telefoni, si rifiuta con gentilezza e si trova un'altra strada. Le diagnosi che toccano servizi
esterni sono **in sola lettura**, non pubblicano nulla e **mascherano i segreti** nell'output.
*La diagnosi di Facebook ha letto il gettone dal file dei segreti senza mostrarlo mai.*
**Si verifica:** `grep -rE 'sk_live_[A-Za-z0-9]{20,}'` sul registro della sessione deve essere **vuoto**, e nessuna risposta contiene password o codici in chiaro.

**15. SCOPO DICHIARATO PRIMA, VERIFICATO DOPO — E L'ELENCO SI AGGIORNA, NON SI SFORA.**
Prima di aprire il primo file si scrive **quali file si toccheranno**. Se durante il lavoro ne
serve uno **fuori elenco**: ci si **ferma**, si aggiorna la riga dichiarando **perché**, e solo
allora si procede. Vietati nello stesso intervento, anche se «migliorano»: rinomine,
riformattazioni, correzioni di passaggio, «già che c'ero».
*Successo il 2026-07-31: avevo dichiarato due file, ne ho toccati quattro. Il lavoro in più era
buono — due guardie cresciute — ma nessuno l'aveva autorizzato, e uno scopo che si allarga da
solo è il canale principale delle regressioni. Il fondatore se n'è accorto prima di me.*
**Si verifica dopo:** `git status` deve contenere **esattamente** i file dichiarati.

---

# 🧭 LE 26 DIRETTIVE DEL FONDATORE — nate dai NOSTRI danni, non da uno studio

> **Perché stanno qui e non solo in memoria.** Fino al 2026-08-01 vivevano nella memoria di
> sessione: **non viaggiavano col progetto**. Su un altro computer, o dentro la CI, non
> esistevano — quindi «per sempre» significava «finché dura quella memoria». Ora stanno nel
> repository, si caricano a ogni sessione e viaggiano con la chiavetta.
>
> **Non sono le 44 della ricerca**, e la differenza va detta: le 44 hanno una **fonte esterna**
> (studio, benchmark, incidente documentato); queste hanno una **cicatrice nostra**. Valgono
> uguale, ma per una ragione diversa — e ognuna porta **come si verifica**, che è l'unica cosa
> che separa una regola da un desiderio.
>
> Il dettaglio (il *perché* e il *com'è successo*) resta nella memoria di sessione: qui c'è
> l'ordine e il modo di controllarlo, perché questo file si carica sempre e allungarlo peggiora
> l'attenzione.

**D1. CHIRURGIA SU RICHIESTA ESPLICITA, ZERO-BLOAT.** Si ripara la riga sbagliata; niente
wrapper, classi helper, file nuovi, dipendenze. *Si verifica:* righe di produzione aggiunte nel
commit vicine a zero, e `git status` senza file nuovi non dichiarati.

**D2. LA BATTERIA DI COLLAUDI VALE PER TUTTO, SEMPRE.** Nessun lavoro esce senza i collaudi
strategici. *Si verifica:* prima di ogni push esiste l'esito della **suite INTERA** con codice
d'uscita letto diretto.

**D3. I 4 LIVELLI, IN ORDINE.** Happy-path → CI/copertura/regressione → avversariale/mutazione →
audit mission-critical. *Si verifica:* non si passa a un livello se il precedente non ha un
esito verde registrato.

**D4. ANTI-VERDI-FINTI: CONTRATTO → CONFINI → INVARIANTI → ASSERZIONI ESATTE.** Pochi test
forti, un difetto per test, asserzioni sull'esito **e** sull'effetto. *Si verifica:* ogni
guardia nuova è stata **vista rossa** sul guasto vero, con ripristino **byte-identico sha256**.

**D5. CONSIGLIO DEL MODELLO PRIMA DI INIZIARE.** Si dice quale modello ed effort servono; se
quello attivo è sbagliato **ci si ferma**. *Si verifica:* la riga «🧭 Metti: /model … /effort …»
compare prima del primo comando del lavoro.

**D6. LE CHIAVI NON SI CHIEDONO E NON SI STAMPANO.** *Si verifica:* nel registro della sessione
nessun valore di `sk_live`, password o codice; le diagnosi sui servizi esterni mascherano.

**D7. TRE POSTI SEMPRE ALLINEATI, IL SERVER MAI INDIETRO.** *Si verifica:* `git rev-parse`
su computer, GitHub e VPS danno **lo stesso valore** (e la chiavetta lo dichiara nella guida).

**D8. NIENTE SEGNAPOSTO: FLUSSI VERI, POI SI PULISCE.** *Si verifica:* nessun `esempio`,
`test@test`, `TODO` o valore finto nei percorsi che l'utente attraversa.

**D9. MAI HEREDOC PER LE PATCH — SI USA `Write`.** Gli heredoc mangiano gli escape e infilano
byte invisibili. *Si verifica:* nessun `<<'PY'` nei comandi che modificano file del repo, e
nessun byte < 32 (esclusi tab/a-capo) nei file toccati. *Mi ha tradito **tre volte** il 2026-08-01.*

**D10. INVENTARIO PRIMA DI COSTRUIRE.** Esistono già ~151 moduli: prima si cerca. *Si verifica:*
prima di un modulo nuovo compare un `grep`/censimento che dimostra che non c'è già.

**D11. SI SPIEGA IN MODO COMPRENSIBILE.** Il fondatore non è tecnico: niente gergo non spiegato.
*Si verifica:* ogni termine tecnico nella risposta è accompagnato da cosa significa in pratica.

**D12. LE SCELTE TECNICHE LE DECIDIAMO NOI.** Se due IA divergono su una scelta tecnica si
discute e si decide; al fondatore si chiede solo di **segreti, soldi veri e strategia**.
*Si verifica:* le domande poste riguardano solo quelle tre categorie.

**D13. UN COMPARTIMENTO ALLA VOLTA, COL VOSTRO VIA.** *Si verifica:* nessun secondo blocco di
lavoro inizia prima di un «vai» esplicito.

**D14. ISPETTORE LOCALE PRIMA DELLA VERIFICA MIRATA.** «Controlla tutto» = si passa lo
strumento locale, poi si guardano solo i sospetti. *Si verifica:* l'analisi di massa è stata
fatta da uno script, non leggendo file a mano.

**D15. LA CACCIA AGLI ERRORI SI RILANCIA SPESSO.** Mutazione, fuzzing, concorrenza, accessibilità.
*Si verifica:* l'ultima esecuzione della batteria è registrata con la sua data e il suo esito.

**D16. AUTONOMIA CON TUTTI PROTETTI, E NOI MAI IN PERDITA.** Si decide da soli, proteggendo
ospite, host e piattaforma. *Si verifica:* ogni scelta che tocca denaro dichiara chi ci perde
se va storta.

**D17. DEPLOY COL PROTOCOLLO A RISCHIO ZERO.** Punto di ritorno + salvataggio **verificato
leggibile** + **`docker compose` v2** + verifica funzionale **nelle due direzioni**.

⛔ **`docker compose` (DUE PAROLE) è la v2. `docker-compose` col trattino è la v1 e BUTTA GIÙ
nginx**, cioè il sito. Sul VPS la v1 è stata disinstallata e **bloccata apposta**, con un
segnaposto che lo spiega a chi la digita (`DEPLOY.md` §1). ⚠️ Il *file* si chiama
`docker-compose.casavip.yml` **col** trattino: quello è il suo nome, non il comando. Vederli
insieme nella stessa riga è normale.

⛔ **L'immagine `:prec` va RI-AGGANCIATA a quella che gira DAVVERO, prima dello scambio.** Il
2026-08-07 puntava a un'immagine di **cinque giorni prima** mentre il sito ne serviva una di 16
ore: un paracadute agganciato all'immagine sbagliata è peggio di nessun paracadute, perché ci si
salta convinti di tornare all'ultimo stato buono.

⛔ **La sonda negativa deve usare un indirizzo CHE ESISTE.** `/admin` risponde **404** — «questa
pagina non c'è», non «sei bloccato» — quindi come prova di sicurezza vale zero. Gli indirizzi
veri, misurati: `/api/admin/*` → **401**, `/api/bunker/*` → **403**. Li interroga già
`collaudi/verifica_produzione.py`: si usa quello, non si inventano percorsi.

*Si verifica:* esistono il file `PRE_DEPLOY_*.commit`, l'immagine `:prec` **ri-agganciata**
all'immagine viva, la prova di lettura del backup, e le sonde positive **e** negative dopo lo
scambio, ognuna su un indirizzo che risponde diverso da 404.

**D18. UNO STRUMENTO CHE MISURA DEVE AVERE UN CONTROLLO MECCANICO CHE GLI IMPEDISCA DI
BARARE.** Detta dal fondatore il 2026-08-01, dopo che il giudice della mutazione ha stampato
«42 mutanti su 42 uccisi» mentre un test era **rosso sul codice sano**: se i test falliscono
comunque, falliscono anche con ogni guasto dentro, e ogni mutante risulta «ucciso». Il
punteggio pieno era aria. *«La prossima volta la domanda non sarà "ha barato?" ma "ha un
controllo meccanico che impedisce di barare?"»* — cioè si passa dal **comportamento** alla
**struttura**: «ha barato?» si chiede dopo, «può barare?» si chiede prima.

⚠️ Onestà sui limiti: un controllo meccanico **non rende l'imbroglio impossibile, lo rende
rumoroso**. Non impedisce allo strumento di sbagliare — impedisce che lo sbaglio passi per un
risultato. È tutta lì la differenza fra `42 su 42` (che sembrava un successo) e `BASE ROSSA` +
uscita 1.

Quattro condizioni, tutte obbligatorie per ogni strumento che **misura** (giudici, guardiani,
contatori, rapporti):
1. **Misura prima se stesso.** Deve provare di essere in condizione di misurare, PRIMA di
   misurare. Un metro storto va scoperto dal metro, non dal muro.
2. **Provato nelle DUE direzioni.** Grida col guasto dentro **e** tace a macchina sana. Un
   allarme provato in un verso solo potrebbe gridare sempre — e un allarme sempre acceso
   viene spento.
3. **Dichiara cosa NON ha esaminato.** Tetti, esclusioni, salti: sempre scritti. Un taglio
   silenzioso fa sembrare «coperto» ciò che non è stato nemmeno guardato.
4. **Il controllo è a sua volta sotto guardia.** Se qualcuno lo toglie, qualcosa diventa rosso
   **lo stesso giorno**; altrimenti fra sei mesi sparisce in una «semplificazione».

*Si verifica:* per ogni strumento di misura del progetto esiste (a) un controllo delle proprie
precondizioni che **ferma** il giro invece di stampare un numero, (b) una prova che lo ha visto
ROSSO su un guasto vero e VERDE a macchina sana, (c) un elenco dichiarato di ciò che è rimasto
fuori, e (d) una guardia nella suite che fallisce se il controllo (a) viene rimosso.

**D19. UNA DIFESA DEVE POTER ESSERE MESSA ALLA PROVA SENZA ASPETTARE IL DISASTRO CHE LA
GIUSTIFICA.** Detta dal fondatore il 2026-08-02, dopo la campagna su `fase179_rate_limit`.

Il codice difensivo — un `if` che non scatta mai, un `try` per un caso «impossibile», un secondo
controllo dopo il primo — ha una proprietà scomoda: **è indistinguibile da codice morto**. Sembra
sicurezza, ma nessuno sa se funziona, perché per definizione non viene mai eseguito. E il giorno
che serve è il giorno in cui la prima difesa ha già ceduto: il momento peggiore per scoprire che
la seconda era rotta.

Il caso che l'ha generata: due mutanti sopravvivevano perché quei controlli sono **irraggiungibili
finché `fallito` si comporta bene**. Dichiararli «equivalenti» sarebbe stato tecnicamente
difendibile e comodo — e avrebbe significato scrivere nero su bianco *«non guardate più lì»* su un
pezzo di codice il cui unico scopo è reggere quando tutto il resto ha ceduto.

Tre divieti che ne discendono:
1. **Non si dichiara equivalente un mutante solo perché «oggi non si raggiunge».** Oggi non si
   raggiunge *per merito di un'altra funzione*: è una conclusione con una premessa, non una
   proprietà. Il giorno che quella premessa cade, la dichiarazione resta e la cecità pure.
2. **Non si assume che un controllo funzioni perché «è lì per sicurezza».** Metà del codice
   difensivo che abbiamo aperto in questi giorni era rotto proprio perché nessuno l'aveva mai
   eseguito.
3. **Non si aspetta l'incidente per sapere se la rete regge.** Lo stato «impossibile» si
   costruisce a mano, adesso, quando costa tre righe.

*Si verifica:* per ogni ramo difensivo (secondo controllo, `except` per un caso che «non capita»,
guardia di ridondanza) esiste una prova che **inietta a mano lo stato impossibile** ed esegue quel
ramo **da solo**, dimostrando che regge; e nell'elenco degli equivalenti dichiarati nessuna voce ha
come motivazione «non è raggiungibile» — solo dimostrazioni sul comportamento (z3, prova esaustiva,
o percorsi che portano allo stesso stato osservabile).

**D20. UN DIFETTO VIVO NON SI RIPARA SUBITO: PRIMA LA GUARDIA, VISTA ROSSA.** Detta dal fondatore
il 2026-08-03. «Difetto vivo» = un errore vero nel codice che gira in produzione, non un mutante.

**L'ordine è obbligatorio, e sono tre passi:**
1. **si scrive la guardia** che descrive il comportamento corretto;
2. **la si esegue e la si vede ROSSA** sul codice di produzione, con l'errore letto per intero;
3. **solo allora** si ripara, e la si rivede **verde**.

*Perché l'ordine non è un formalismo.* Una prova scritta **dopo** la riparazione può passare per
il motivo sbagliato: magari non attraversa nemmeno il punto guasto, e nessuno se ne accorge perché
è verde. Il rosso **prima** è l'unica dimostrazione che quella prova **veda proprio quel difetto**.
È il «verde finto» applicato al momento in cui nasce la guardia.

*E la seconda metà, che è quella che dura.* Una riparazione senza guardia è una riga cambiata di
cui fra sei mesi qualcuno chiederà «perché è scritta così?», e la risposta più comoda sarà
«semplifichiamo». **La guardia è la memoria del difetto**: se qualcuno riscrive quella riga com'era,
diventa rossa lo stesso giorno. Senza, domani nessuno sa che c'era — e torna.

*In più (non obbligatorio ma vale):* dopo la riparazione, rimettere dentro il difetto vero e
rivedere il rosso una seconda volta. La prima volta prova che la guardia **becca** il difetto; la
seconda che **resta capace di beccarlo** dopo che il codice è cambiato.

*Si verifica:* per ogni difetto vivo, nel registro della sessione esistono nell'ordine (a) la
guardia scritta, (b) la sua esecuzione **rossa** con il messaggio d'errore riportato per intero,
(c) il diff della riparazione, (d) la stessa guardia **verde**. Se il rosso non c'è, o arriva dopo
il diff, quella riparazione non è provata — e va rifatta nell'ordine giusto.
*Successo davvero il 2026-08-02, due volte: la porta del bunker che rispondeva 500 a un codice
accentato, e il guardiano che dichiarava sano un libro dei soldi corrotto. In tutti e due i casi il
difetto è stato SCOPERTO dalla guardia diventata rossa, non cercato a mano.*

**D21. AL 50% DEL CONTESTO SI SALVA TUTTO, SI ALLINEA TUTTO E SI RICOMINCIA DA CAPO.** Soglia
**fissata dal fondatore** il 2026-08-06: è una scelta di budget, non una misura. Il motivo è che oltre
metà contesto l'IA **non smette di rispondere** — continua **con lo stesso tono sicuro**, mettendoci
dentro numeri mai misurati. Il fenomeno è documentato nell'appendice di `REGISTRO_INGEGNERIA.md`,
ricerca «sessioni lunghe», regole **#1** (la compattazione è amnesia) · **#5** (*Context Rot*: si
degrada al crescere dell'input) · **#7** (arXiv 2505.06120: **-39%** dal singolo turno al
multi-turno) · **#21** (una sessione un compito, `/clear` dopo due correzioni — il suo «si verifica»
nomina già la finestra «oltre metà piena»). Il degrado è **continuo**: il 50% non è un gradino, è
dove ci fermiamo noi.

**Cosa si fa a metà, in quest'ordine:** (1) si **smette di aprire lavoro nuovo**; (2) **suite intera**
verde, codice d'uscita letto diretto; (3) ciò che si è imparato si scrive **in `RIPRENDI_QUI.md`**,
con la riga di changelog in `REGISTRO_INGEGNERIA.md` (direttiva finale 4) e **mai un file nuovo**
(REGOLA ZERO 3) — ⛔ il blocco `## SESSIONE DERAGLIATA <data>` della #7 è **un'altra cosa** e non si
riusa qui: quello serve a una sessione impantanata, questo è un passaggio di consegne sano;
(4) **dopo il via** — B1 «procedi al commit», B4 «autorizzato» — il lavoro va in **tutti i
posti**: computer → GitHub (ramo + richiesta di unione: `master` è chiuso dal cancello) → VPS (D17) →
chiavetta; **senza il via non si committa, non si tocca produzione, non si deploya**: si prepara, si
chiede e si aspetta, e il lavoro resta sul computer; (5) **`/clear`**, e si riparte con un prompt che
dice **dove guardare e cosa verificare**, mai «ricorda che».

*Chi dice che siamo a metà.* L'unica fonte che fa fede è la **barra del fondatore** («% context
used», si legge col comando `/context`). La stima dell'IA **non fa fede** — è lo strumento che questa
regola stessa dichiara inaffidabile — e può solo **anticipare** il punto, mai spostarlo più in là;
quando la usa, la dichiara come stima e mostra il numero da cui la ricava.

⛔ **«AL 50% **O PRIMA**» — e il «prima» è un INNESCO MECCANICO, non una sensazione.** Aggiunto dal
fondatore il **2026-08-07**, dopo una sessione in cui l'IA ha segnalato tre volte «siamo oltre metà»
e ha continuato lo stesso, perché aspettava un numero che non poteva leggere. *«Perché sia tu, sia
le precedenti, sia quelle future non lo rispettano? Da soli non riuscite?»* — no: una regola
appoggiata a un numero che l'IA non vede è appoggiata alla buona volontà, e **un obbligo affidato
alla buona volontà si rompe di nuovo** (D22). Quindi il blocco di consegne si scrive **anche** —
senza aspettare nessuna percentuale — **ogni volta che si chiude un blocco di lavoro**, cioè quando
si arriva a «commit fatto + posti allineati» e **prima di aprire qualunque cosa nuova**. È un evento
che si vede, capita 2-3 volte al giorno, e non richiede di misurare niente.
*Successo davvero il 2026-08-07:* tre blocchi chiusi in una giornata (riparazione del cancello ·
deploy · chiavetta) e **zero** blocchi di consegne scritti, perché li si aspettava dalla
percentuale. Il costo non è teorico: `RIPRENDI_QUI.md` è rimasto per ore a dichiarare il server
indietro e GitHub guasto, quando erano entrambe cose già risolte.

*Se si deve comunque proseguire oltre:* da lì in poi **nessuna affermazione senza la misura nello
stesso messaggio**. Niente numeri a memoria, nessun «ho verificato» senza sotto il comando e l'uscita.

*Si verifica:* il blocco di allineamento esiste **fuori** dalla conversazione (in `RIPRENDI_QUI.md`) e
riporta: la **percentuale letta** quando è stato scritto, `git status`, l'esito della **suite intera**
col codice d'uscita, l'impronta (`sha`) del lavoro e i posti in cui si trova, e la richiesta esplicita
del via. **Violazione** = si è **superato** il 50% senza che quel blocco esista, **oppure** il blocco
riporta una percentuale **maggiore di 50**. Sotto il 50% non c'è niente da scrivere e niente da
violare.
*Limite dichiarato (D18 punto 3):* questa direttiva **non ha una guardia meccanica**, e non può
averla — nessun test può leggere la percentuale di contesto di una sessione. Le guardie in
`test_pipeline_ci.py` dimostrano che il **testo** della regola esiste nel repository, non che sia
stata applicata. L'unica cosa che la fa scattare davvero è chi legge la barra.

**D22. UN NUMERO SI SCRIVE SOLO CON LA MISURA CHE LO REGGE — E DOVE SI PUÒ, CON UNA GUARDIA.** Non
ripete REGOLA ZERO 4 («i numeri non si ricordano a memoria») né REGOLA FERREA 3 («vietato scrivere
un'affermazione non provata»): **le affila**, aggiungendo le due cose che a quelle mancavano — il
**commit** accanto alla cifra, e la **guardia** dove una macchina può ricontrollare. Dettata dal
fondatore il **2026-08-06**, dopo aver perso tempo su `Ran 5429`: un totale **calcolato a mente**
(5427 + 2 invece di + 7) è finito in `RIPRENDI_QUI.md` come se fosse stato misurato, e la sessione
dopo ha dovuto fermare tutto per capire da dove venissero cinque test che nessuno aveva aggiunto.
Ogni cifra che descrive lo **stato attuale** della macchina — test, moduli, punti di mutazione,
obblighi — porta con sé, sulla stessa riga o in quella sotto, **il comando che l'ha prodotta** e **il
commit su cui è stata misurata**. Un numero ottenuto sommandone altri **non è misurato**: o si rifà la
misura, o non si scrive. E dove una macchina può ricontrollare, la prosa non basta: si mette una
**guardia**, perché un obbligo affidato alla buona volontà si rompe di nuovo.

*Si verifica:* `test_IL_NUMERO_DELLA_SUITE_DICHIARATO_E_QUELLO_VERO` confronta la cifra dichiarata in
`RIPRENDI_QUI.md` col conteggio reale del caricatore di test; e `collaudi/regole_avvio.py` confronta
**tutti e tre** i numeri che `CLAUDE.md` dichiara su se stesso (totale · «gli altri» · direttive) col
conteggio rifatto dai file, non con quello che ricorda chi scrive.
⚠️ **Una guardia sul conteggio conta, non giudica** (appendice #14, fonte Inozemtseva): duplicare
200 test la soddisferebbe alla perfezione. Il numero dice quanto è stato **eseguito**, mai quanto è
stato **coperto**: quello lo dice solo la larghezza di mutazione.

**D23. IL COMANDO E L'AMBIENTE CON CUI GUARDI FANNO PARTE DELLA MISURA.** Dettata dal fondatore il
**2026-08-07**, dopo una giornata in cui il codice era sano e a mentire sono stati **gli strumenti
con cui lo guardavo**.

Un controllo può essere **spento dal modo in cui lo esegui**, e il risultato non è rosso: è
**verde**. È il verde peggiore di tutti, perché non ha guardato niente. Quattro modi, tutti visti
in un giorno solo:

1. **Un tubo che si mangia l'esito.** `comando | filtro` restituisce l'esito del *filtro*. È già la
   regola ferrea 7, ed è successo lo stesso: quindi la regola da sola non basta. Si scrive l'uscita
   su **file** e si legge il codice d'uscita **diretto**.
2. **Un `2>$null` che nasconde il motivo.** Uno script è fallito e l'errore era stato zittito da me:
   restava solo «uscita 1», cioè un guasto senza nome.
3. **Un ambiente monco che spegne le guardie in silenzio.** Senza `openssl` nel PATH, le **cinque
   guardie sul ripristino dei backup** si mettono da parte in blocco — e `unittest` registra **UN
   solo salto**, **senza il nome della classe**, e non conta quei test nel totale `Ran`. Cinque
   controlli spariti e nessuno che lo dica.
4. **Una sonda su un indirizzo che non esiste.** `/admin` → **404** usato come prova che l'area
   riservata è chiusa: un controllo che *non può* fallire, cioè un ornamento.

*Si verifica:* per ogni controllo che dichiara un esito, nella sessione compaiono (a) il **comando
esatto**, (b) l'**ambiente** in cui è girato (interprete, dipendenze, e il `PATH` quando conta),
(c) il **codice d'uscita letto senza tubi**, e (d) per le sonde, la prova che l'indirizzo
interrogato **risponde qualcosa di diverso da 404**. E un numero che cala senza spiegazione — test
**raccolti** contro test **eseguiti** — non si arrotonda e non si sceglie il più comodo: si insegue
finché non ha un nome.

**D24. LE REGOLE E LA BATTERIA SI RILEGGONO PRIMA E DOPO OGNI OPERAZIONE — E «I TEST»
COMPRENDONO QUELLI ESTERNI.** Dettata dal fondatore il **2026-08-12**: *«leggere prima e dopo
tutte le regole e i test e quelli esterni prima e dopo ogni operazione»*.

**Non ripete l'obbligo di rileggere IL BLOCCO** (quello riguarda i sei divieti): lo **estende**
alla **batteria dei 10 collaudi** e a **quelli esterni** — il giudice non-nostro e la CI su
Linux. La differenza non è formale: è la differenza fra «non ho violato un divieto» e «ho
dimostrato che funziona».

*Com'è nata, e non è un'ipotesi.* Quel giorno avevo scritto «guardia scritta e provata nelle
due direzioni» avendo passato i livelli ① e ② e **zero** dei dieci collaudi, col giudice
esterno e la CI mai sfiorati. Il fondatore ha chiesto se li avessi letti. Rileggendo **le 44
dell'appendice** sono venuti fuori **cinque** buchi, e il più grave era che il guardiano
appena scritto **non era collegato al gancio del commit**: girava solo dentro un ciclo da 25
minuti, quindi un piano contraddittorio si poteva salvare e lo si scopriva mezz'ora dopo. È la
regola **#23** («COSTRUITO ≠ COLLEGATO») e nessun divieto lo avrebbe mai fatto emergere.

⛔ **E non è affidata alla buona volontà, perché così si rompe di nuovo** (è la lezione di
D22 e del paracadute `:prec`, sbagliato quattro volte in quattro giorni). I sei divieti li
stampano già `regole_avvio.py` all'avvio e `prima_di_dire_fatto.py` al commit; da oggi il
pre-fatto stampa **anche la batteria**, leggendo la tabella dei 10 collaudi **da questo file**
invece di ricopiarla — una copia potrebbe dire il falso il giorno che la tabella cambia, ed è
esattamente il difetto che questa direttiva nasce per impedire.

*Si verifica:* prima di ogni «fatto», nel registro della sessione compare per **ognuno** dei
dieci collaudi l'esito **oppure il motivo dichiarato** per cui non si applica — un collaudo
senza esito e senza motivo non è un successo, è **NON ESEGUITO** (sbaglio S7). E per «quelli
esterni» compaiono le due cose che il computer da solo non può dare: l'esito di uno strumento
**non nostro** (collaudo 7) e la **tabella dei job della CI** letta dall'API (regola ferrea 8),
mai «immagino sia verde». La guardia meccanica è
`test_IL_PRE_FATTO_RILEGGE_ANCHE_LA_BATTERIA` in `test_pipeline_ci.py`.

**D25. PRIMA SI LEGGE COME L'HA GIÀ RISOLTO IL MONDO — FONTI VERE, PIÙ DI UNA, E POI SI FA
QUELLO CHE DICONO.** Dettata dal fondatore il **2026-08-13**: *«fai prima una ricerca
ingegneristica online, fonti vere verificate e aggiornate, leggi, e dopo fai quello che si
dice. Non ti fermare solo a una ricerca, falle approfondite, e vale per tutti i lavori e
anche futuri, così non si sbaglia più e non si va a caso. 0 bugie e imbrogli. Io lo scopro.»*

*Com'è nata, e non è un'ipotesi.* Quel giorno avevo progettato da solo l'attrezzo che trova i
test che scadono, e ci avevo messo dentro **tre difetti**: lo scarto d'orologio applicato due
volte (chiesti 200 giorni, ottenuti 400), l'orologio di **SQLite** non spostato, e i
**processi figli** che vedono l'ora vera. Non erano difetti geniali: sono i **tre classici
noti** del *clock mocking*, scritti nella documentazione delle librerie che esistono apposta.
Dieci minuti di lettura avrebbero risparmiato tre falsi allarmi — e un attrezzo che accusa
innocenti **viene spento**, cioè il lavoro si autodistrugge.

⛔ **I TRE CONFINI, perché senza si creano contraddizioni con regole già scritte** (trovate
prima di scrivere questa, non dopo):
1. **Non contraddice REGOLA ZERO 1.** Le fonti esterne dicono **come si fa bene una cosa**; i
   5 documenti ufficiali dicono **com'è fatta la NOSTRA macchina oggi**. Sono due piani
   diversi: ⛔ nessun articolo di internet è mai fonte di verità su una nostra tariffa, un
   nostro modulo o un nostro numero — quelli si verificano nel codice.
2. **Non autorizza NIENTE di nuovo.** Se la fonte dice «usa la libreria X», questa direttiva
   **non basta** a installarla: D1 e la regola ferrea 1 vietano dipendenze, file e riscritture
   non chiesti. Si riporta cosa dice la fonte e **si chiede**. *Successo subito: le fonti
   consigliano `freezegun`/`time-machine`, che qui non si possono aggiungere da soli.*
3. **Completa D10, non la sostituisce.** D10 guarda **dentro casa** (esiste già da noi?);
   questa guarda **fuori** (come l'ha risolto chi c'è già passato). Si fanno tutt'e due, in
   quest'ordine: prima fuori per il metodo, poi dentro per non ricostruire.

*Si verifica:* per ogni scelta tecnica non banale, nel registro della sessione compaiono
**almeno due ricerche distinte** con le **fonti citate per nome e anno**, e accanto alla
scelta è scritto **cosa dice la fonte** — oppure la frase esplicita «non ho letto niente, sto
ragionando», che è ammessa ma va detta. Le fonti per esteso vanno **nell'appendice di
`REGISTRO_INGEGNERIA.md`**, non qui: questo file si carica a ogni sessione e allungarlo
peggiora l'attenzione. ⚠️ **Limite dichiarato (D18 punto 3):** nessuna guardia meccanica può
sapere se ho letto davvero; questa direttiva è verificabile solo **leggendo il registro**, ed
è per questo che «0 bugie» è la parte che il fondatore ha detto per ultima.

**D26. UN MODULO NON È «FATTO» FINCHÉ NON HA SUPERATO L'ESAME — e a dirlo dev'essere una
macchina, non una parola scritta a mano.** Dettata dal fondatore il **2026-08-14**, dopo aver
chiesto: *«quindi non c'è modo di finire mai una fase, se i controlli vengono fatti a metà?»*

*La causa non erano i controlli a metà: era la PAROLA.* Nel piano dei soldi «FATTO» significava
*«questo modulo è passato sotto il Giudice»*, non *«ha superato l'esame»* — due cose diverse
nella stessa colonna. Così `fase59_concierge` risultava chiuso mentre aveva **42 punti
scoperti**, 39 dei quali su codice che la produzione esegue a ogni preventivo e ogni
prenotazione.

**Un modulo è FATTO quando valgono TUTTE queste, non alcune:**
1. i **punti** dichiarati coincidono col censimento **rifatto adesso** (su `fase59` il documento
   diceva 112, il vero era 114);
2. i punti **scoperti sono ZERO**. È l'unico esito che non peggiora guardandolo meglio: più
   sorveglianti possono solo **alzare** gli uccisi, mai abbassarli — quindi «tutti uccisi» regge,
   mentre un punteggio parziale cambia a seconda di quanti occhi hai acceso (`fase59`: 45 uccisi
   con 5 sorveglianti, **72** con 22, sugli stessi identici punti);
3. le **rinunce** del generatore sono dichiarate una per una: un punto che nessuno sa rompere non
   è un punto sicuro, è un punto **mai guardato**;
4. il giro porta **data, commit e l'elenco dei sorveglianti usati**: un punteggio senza l'elenco
   degli occhi accesi non è confrontabile con nessun altro, e sembra migliore o peggiore del vero;
5. i **dieci collaudi** hanno l'esito **oppure** il motivo dichiarato (D24).

⛔ **E la parte che separa questa direttiva da un buon proposito.** Non basta scriverlo qui. Il
guardiano `collaudi/piano_dei_soldi.py` oggi controlla soltanto che i tre documenti **dicano la
stessa cosa**, e lo dichiara da sé a ogni giro: *«non dice se un modulo dichiarato FATTO lo sia
DAVVERO»*. Quel limite era scritto nero su bianco e nessuno lo leggeva come un lavoro da fare.
Finché il guardiano non **pretende la prova**, questa direttiva è affidata alla buona volontà —
e la buona volontà qui si è rotta ogni volta (D22, e il paracadute `:prec` sbagliato quattro
volte in quattro giorni).

*Si verifica:* per ogni modulo dichiarato FATTO nel piano dei soldi esiste, nel registro, il giro
del Giudice con **data · commit · punti · uccisi · scoperti · rinunce · sorveglianti usati**; e il
guardiano diventa ROSSO se un «FATTO» non ha la sua prova. Un modulo che è solo passato sotto il
Giudice si scrive **«giudicato»**, mai «fatto».

---

# 🔟 REGOLA DEI 10 COLLAUDI — come si dimostra che una cosa funziona

**Perché esiste.** Il 2026-07-21, in una sola giornata, **sette difetti veri** sono passati
sotto una suite completamente verde: due database che vivevano in RAM (recensioni perse a
ogni riavvio, un credito rispendibile), tre pagine ed email che reclutavano host senza
dichiarare il 3%, il giro della marca temporale legato per sbaglio all'email, e lo
scaglione dell'8% che nessun test avrebbe difeso se fosse diventato 10%.

Nessuno di questi era un caso. Erano tutti la stessa cosa:

> **Un test verde non dice «funziona». Dice «non ho visto niente».**
> Finché non sai *cosa quel test è capace di vedere*, il verde non vale nulla.

E la conseguenza operativa, che è la regola più importante di tutte:

> ### ⚠️ NESSUN VERDE VALE FINCHÉ NON È STATO VISTO ROSSO.
> Una guardia che non è mai fallita davanti al guasto che dovrebbe vedere **non è una
> guardia**: è un ornamento. Il 2026-07-21 tre verifiche di sicurezza su nginx sono
> risultate incapaci di fallire — tre volte di fila, per lo stesso errore di fondo
> («la stringa c'è da qualche parte» invece di «la protezione c'è su ogni porta»).

**Ripetere non basta.** Eseguire venti volte un test che non può fallire produce venti
finti verdi. La ripetizione misura la **stabilità**; non misura la **copertura**. Sono due
assi diversi: prima si guadagna la copertura, poi si ripete per la stabilità.

## GLI 11 MODI DI ROMPERSI (incontrati sul campo, non teorici)

Ogni cosa costruita va passata su questa lista chiedendo, per ognuna:
**«se si rompesse così, chi se ne accorgerebbe?»** Se la risposta è «nessuno», manca una
guardia — anche se tutto è verde.

| # | Modo di rompersi | Caso reale |
|---|---|---|
| 1 | **Dati effimeri** — funziona, ma scrive dove i dati muoiono | recensioni e crediti in RAM |
| 2 | **Cablaggio mancante** — il pezzo è perfetto e non è collegato | promo 0% mai applicata |
| 3 | **Testi che mentono** — il codice fa X, la pagina promette Y | «10%» senza il 3% |
| 4 | **Controllo che non controlla** — la guardia non può fallire | `server_tokens` su due blocchi |
| 5 | **Dipendenza nascosta** — funziona solo se c'è altro | la marca legata a SMTP |
| 6 | **Il terzo che cambia** — un servizio esterno smette o cambia | una TSA che perde la qualifica |
| 7 | **Il tempo che passa** — scadenze, rampe, rinnovi | certificato, scaglioni per anzianità |
| 8 | **Ambiente diverso** — locale ≠ produzione | `:memory:` nei test, file in prod |
| 9 | **Rifattorizzazione** — il cuore cambia, le guardie restano sul vecchio | `stato_scaglione` senza le guardie di `commissione_bps_lancio` |
| 10 | **Dato assurdo** — il formato è giusto, il **numero** non ha senso | `¥1.800.000 a notte` (prezzo ×100 su valuta senza decimali) |
| 11 | **Lingua congelata** — la pagina ha 8 lingue ma il testo non è sostituibile | privacy e termini leggibili **solo in italiano** |

> I modi **10 e 11 non li ha trovati nessun test: li ha trovati il fondatore guardando
> il sito.** È la lezione più cara della giornata, e vale come regola a sé:
>
> ### 👁️ I test provano che il codice fa quello che dice. Nessuno chiedeva *cosa vede una persona*.
>
> Da qui i due strumenti che colmano il buco: `collaudi/plausibilita.py` («questo numero
> ha senso nel mondo vero?», girato anche sui **dati veri di produzione**) e
> `collaudi/occhio_del_fondatore.py` («chi apre questa pagina, cosa legge?»).
> Entrambi guardano il **prodotto**, non il codice.

## I 10 COLLAUDI, IN QUEST'ORDINE

Ognuno ha uno **scopo diverso**: non sono dieci ripetizioni, sono dieci **punti di vista**.
Nessuno di essi da solo basta; è la loro **diversità** che copre i 9 modi di rompersi.

| # | Collaudo | Cosa cerca | Copre |
|---|---|---|---|
| 1 | **Guardia rossa sul vecchio** | il bug corretto non può tornare | 9 |
| 2 | **Cablaggio, anello per anello** | il pezzo è collegato fino a ciò che l'utente vede | 2 |
| 3 | **Avvio reale + persistenza** | `main_casavip.py` eseguito davvero; nessun `:memory:`; i dati sopravvivono al deploy | 1, 8 |
| 4 | **Neuroni** | il compartimento attraversato a livelli annidati, fino ai casi terminali | tutti |
| 5 | **Oracolo indipendente** | un secondo calcolo, scritto separatamente, ricalcola da zero e confronta | 9 |
| 6 | **Fuzzing, concorrenza, estremi** | input assurdi, gare, troncamenti, valori limite | 4 |
| 7 | **Giudice esterno** | uno strumento **non nostro** conferma (OpenSSL, `curl` sul sito vero) | 6 |
| 8 | **Audit dei testi** | ogni cifra e promessa pubblica confrontata col motore | 3 |
| 9 | **Caccia ai finti verdi** | test saltati, senza asserzioni, guardie costanti, baseline compiacenti | 4 |
| 10 | **🧬 MUTAZIONE — per ultimo** | si rompe il motore di proposito: **i test se ne accorgono?** | 4, 9 |

**La mutazione va per ultima** perché è l'unica che giudica **i test**, non il codice: ha
senso solo quando gli altri nove sono già verdi. Un mutante che sopravvive è la prova
matematica che lì non c'è protezione, per quanto verde sia tutto il resto.

## COME SI ESEGUE

```bash
python collaudi/protocollo.py               # i 10 in ordine, mutazione per ultima
python collaudi/protocollo.py --giri=10     # 10 ripetizioni: stabilità
python collaudi/mutazione_prodotto.py       # solo il giudizio finale
python collaudi/caccia_finti_verdi.py       # solo la caccia ai finti verdi
```

**Ripetizioni**: minimo **5** per ogni cosa; **10** per ciò che tocca **soldi**, **prove
legali** o **sicurezza**. Un solo rosso su N giri = si analizza, si corregge e si
**riparte da zero**: l'instabilità è essa stessa un difetto.

**Non si dichiara «fatto»** finché il protocollo non è verde **e** ogni guardia nuova è
stata **vista rossa** almeno una volta sul codice guasto.

---

# DIRETTIVA OPERATIVA FINALE E SUPREMA

**1. RIVALUTAZIONE GLOBALE E PILOTA AUTOMATICO**
Lavora in totale autonomia. Raggruppa l'uso degli strumenti in blocchi massicci ed esegui letture, analisi e test da solo. Non fermarti in continuazione per chiedere permessi per ogni singolo step: procedi spedito fino al report finale. Applica una RIVALUTAZIONE GLOBALE a tutto il progetto esistente (tutte le fasi costruite finora) alla luce di queste regole, scovando i punti deboli.

**2. IL CICLO ITERATIVO E I 10 TEST**
Non accettare mai la prima soluzione. Componi, testa, distruggi, ricomponi. Crea obbligatoriamente 3 o 4 varianti diverse per ogni singolo pezzo. IL CODICE DEVE ESSERE INSERITO E TESTATO RIPETUTAMENTE, ALMENO 10 VOLTE! Devi scovare i bug e distruggerli.

**3. [PRIORITÀ ASSOLUTA E SUPREMA]**
SOTTOPONI LE VARIANTI A UN BENCHMARK SOTTO CARICO ESTREMO. IL CODICE CHE INTEGRERAI NEL NUCLEO (SIA NUOVO CHE VECCHIO) DEVE ESSERE RIGOROSAMENTE E UNICAMENTE LA **VINCITRICE DEL BENCHMARK**, QUELLA CHE SOPRAVVIVE A TUTTI I 10 TEST. NESSUN COMPROMESSO.

**4. [REGISTRO D'INGEGNERIA — OBBLIGATORIO]**
Ogni volta che crei o modifichi una funzione/modulo, AGGIORNA `REGISTRO_INGEGNERIA.md` (creazione · scopo · logica · dipendenze/env · STATO acceso/spento · come si attiva) **E la sezione "DA FARE / PROSSIMI PASSI"** (togli ciò che hai completato, aggiungi ciò che resta): così "cosa è fatto" e "cosa manca" stanno SEMPRE insieme e aggiornati. Niente resta "costruito e dimenticato": se una cosa è costruita ma NON attivata, va scritta nella sezione "COSTRUITO ma SPENTO" con come accenderla. Regola del fondatore: questo va fatto a OGNI completamento, da CHIUNQUE tocchi il codice — **incluso il collaudatore (Fable 5)**: anche ogni bug corretto in collaudo va scritto nel registro (cosa era rotto, come l'hai sistemato, test aggiunto). Non si perde la logica di NULLA. Il test `test_registro_ingegneria.py` è la guardia auto-applicante (una nuova `faseNN_*.py` non registrata fa fallire la suite). Il collaudatore (Fable 5) legge il registro per sapere cosa esiste e cosa testare.
