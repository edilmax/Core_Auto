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
