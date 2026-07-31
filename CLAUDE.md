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
- **tariffa tecnica 3% SEMPRE dovuta dall'host**, anche a commissione 0% (gateway Stripe,
  margine piattaforma zero);
- registrazione e ri-accettazione: **3 spunte obbligatorie** (Contratto · clausole vessatorie
  artt. 1341-1342 c.c. · Privacy GDPR), pulsante bloccato lato browser **e** rifiuto `422` lato
  server, con prova firmata **HMAC-SHA256** (versione, impronta del testo, IP, dispositivo, ora).

**5. Prima di ogni deploy: suite INTERA verde**, poi si salva nei **3 posti**
(computer → GitHub → VPS). Ogni bug corretto lascia un test-guardia **rosso sul codice vecchio**.

---

# ⚙️ REGOLA FERREA DI OPERATIVITÀ E PRECISIONE

> ## 📚 QUESTE SONO 14. LE REGOLE SONO **44**.
> Le altre **30 stanno in `REGISTRO_INGEGNERIA.md`, appendice finale** — ognuna con la
> **prova**, la **fonte** (studio, benchmark o `file:riga` del nostro codice) e **come si
> verifica**. Più le **24 uccise** dai revisori ostili **col motivo**: dice cosa NON rifare.
>
> **Vengono da due ricerche mirate (77 agenti, ~4 milioni di token, 2026-07-30).** Non sono
> opinioni: ogni regola ha una prova.
>
> **QUI ci sono le 14 che valgono a OGNI lavoro** e si verificano da fuori. Le altre 30
> servono **quando fai quel tipo di lavoro**, e vanno lette PRIMA di iniziarlo:
> · stai per **collaudare** o toccare la **mutazione** → leggi l'appendice, sezione mutanti
>   (mutanti generati vs scelti a mano · «ucciso solo a volte = IGNOTO») ·
> · stai per **modificare codice esistente** → sezione «prima di modificare, prova che la
>   modifica manca» (35-65% degli agenti tocca ciò che andava lasciato stare) ·
> · **sessione lunga o contesto riassunto** → sezione deriva/compattazione ·
> · stai per **chiudere e dire «fatto»** → sezione prove eseguibili e revisore fresco.
>
> ⚠️ Non sono qui per una ragione tecnica precisa: `CLAUDE.md` viene caricato **a ogni
> sessione**, e allungarlo **peggiora** l'attenzione invece di migliorarla (fenomeno
> documentato, «context rot»). Un regolamento che nessuno tiene in testa non protegge nulla.

Dettata dal fondatore il **2026-07-30**, dopo una giornata in cui **tre strumenti diversi ci hanno
rassicurato mentre erano guasti**. Ogni riga qui sotto nasce da un fatto accaduto, non da una
teoria: dove c'è un esempio, è successo davvero.

**1. PRECISIONE CHIRURGICA E MINIMA INVASIVITÀ.** Si ripara **solo** lo stretto necessario —
idealmente **una riga**. Vietati: codice superfluo, funzioni non chieste, classi helper, `if`/`try`
ridondanti, file temporanei, commenti spazzatura, dipendenze nuove.
*Il fix «paganti al check-in» è costato 3 righe; riscrivere il modulo sarebbe stato un errore.*

**2. ZERO TOLLERANZA PER IL VERDE FINTO.** Nessun test, guardia o controllo vale finché non è stato
**visto fallire** sul guasto vero e poi visto passare, con **ripristino byte-identico (sha256)**.
Vietate le guardie e le frasi **ornamentali**, che rassicurano senza controllare nulla.
*Tre casi in un giorno: una guardia che **pretendeva** il comando che spegne il sito; un log che
scriveva «blocco temporaneo, riprovo» mentre l'app era murata; una mia prova rossa che non
riscriveva il file e passava «senza vedere niente».*

**3. ALLINEAMENTO TOTALE DELLE FONTI DI VERITÀ.** Ogni modifica reale sulla macchina (pacchetti
rimossi, pin, configurazione) va **subito** riflessa nei documenti, con la verità **verificata sul
campo**. È **vietato** scrivere nei 5 documenti un'affermazione non provata sulla macchina — anche
se «suona giusta» o se l'ha suggerita qualcun altro.
*`DEPLOY.md` prescriveva un comando rotto: la nota giusta stava solo in una memoria di sessione.
Costo: un minuto di sito irraggiungibile.*

**4. MANI IN TASCA DURANTE I CICLI.** Mentre una suite o un deploy sono in corso sono
**intoccabili i file del progetto e la macchina che esegue i test**. Vietato: modificare file,
lanciare una seconda suite, fare trasferimenti pesanti. **Ammesso**: lavoro in **sola lettura su
altre macchine**. Il divieto non è formale: modificare i file sotto test produce **rossi finti**.
*Già successo tre volte in un giorno. Misurato: la stessa suite passa da 23 a 27 minuti se la
macchina lavora in parallelo.*

**5. PULIZIA RADICALE DELLA POLVERE — MA SOLO DOPO LA PROVA.** Nessun residuo obsoleto deve
sopravvivere: vecchi backup, script morti, comandi deprecati. Se un comando è pericoloso va
**sradicato alla radice** (rimosso **e** bloccato, es. pin apt a priorità negativa) e **va
verificato che il blocco funzioni davvero**, non solo installato.
⚠️ **Si distrugge solo dopo aver dimostrato che nulla di vivo lo usa**: collegamenti del compose,
cron, unità systemd, script, e file presenti **solo** lì.
*Una pulizia «ovvia» cancellò `certbot/`: il sito rispondeva, ma il rinnovo del certificato era
morto **in silenzio**, e si sarebbe scoperto sessanta giorni dopo.*

**6. SUITE INTERA ANCHE PER UNA VIRGOLA IN UN `.md`.** Nessuna eccezione, nemmeno per la
documentazione. Eseguire «solo i test che sembrano attinenti» non è consentito.
*Corretto un documento, eseguite tre guardie invece di tutte: la CI è andata rossa, perché un test
**leggeva** quel documento.*

**7. IL CODICE D'USCITA SI LEGGE DIRETTO, MAI ATTRAVERSO UN TUBO.** `comando | tail` restituisce
l'esito di `tail`, non del comando.
*Un `EXIT=0` su una suite che stampava `FAILED`.*

**8. LA CI SU LINUX È IL GIUDICE; IL VERDE LOCALE È UN INDIZIO.** Un verde sul computer non
autorizza né tranquillità né deploy. Dopo ogni push si **guarda la tabella**.
*Ha colto due volte ciò che il verde locale non vedeva, per differenze fra sistemi operativi.*

**9. L'OSSERVABILE DEBOLE È UN DIFETTO.** Quando si registra il fallimento di un servizio esterno
si scrivono **codice, sottocodice e messaggio**, mai il solo stato HTTP.
*Per due giorni «400 Bad Request» ha reso indistinguibili un blocco temporaneo e un'applicazione
bloccata: due situazioni con rimedi opposti.*

**10. UN FALSO ALLARME È UN DIFETTO QUANTO UN ALLARME MANCATO.** Insegna a ignorare i segnali. Ogni
allarme si prova nelle **due direzioni**: **tace** quando tutto è a posto, **grida** quando serve.
*Un allarme nuovo gridava su un impianto appena installato; l'ha colto un test esistente.*

**11. IL DIFETTO È SPESSO IN CHI CHIAMA, NON NEL PEZZO CHE MOSTRA IL SINTOMO.** Prima di toccare un
modulo che «sembra sbagliato», si guarda **chi lo usa**. È anche il modo di tenere il diff minimo.
*Il modulo del check-in era corretto: sbagliava chi gli passava il numero.*

**12. PRIMA DI DISTRUGGERE O SOSTITUIRE, GUARDARE COSA C'È. E MAI `|| true`.** Ogni comando
distruttivo passa da una **simulazione** (`apt -s`, elenco del contenuto dell'archivio, `git diff`).
`|| true` è vietato: nasconde i fallimenti.
*Un comando suggerito cancellava un percorso «alla cieca» che su molte macchine è il collegamento
alla versione **buona**.*

**13. DATE E NOMI NON SONO PROVE: SI GUARDA IL CONTENUTO.** Un archivio si verifica **aprendolo**:
la correzione è dentro? il commit citato è quello giusto? l'impronta **sha256** coincide con
l'originale? **Un backup non verificato leggibile non è un backup.**
*La cartella della chiavetta portava la data di oggi e conteneva codice vecchio.*

**14. LE CHIAVI NON SI CHIEDONO E NON SI STAMPANO.** Se il fondatore offre password, codici o
telefoni, si rifiuta con gentilezza e si trova un'altra strada. Le diagnosi che toccano servizi
esterni sono **in sola lettura**, non pubblicano nulla e **mascherano i segreti** nell'output.
*La diagnosi di Facebook ha letto il gettone dal file dei segreti senza mostrarlo mai.*

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
