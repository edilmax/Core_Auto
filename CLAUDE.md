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

# DIRETTIVA OPERATIVA FINALE E SUPREMA

**1. RIVALUTAZIONE GLOBALE E PILOTA AUTOMATICO**
Lavora in totale autonomia. Raggruppa l'uso degli strumenti in blocchi massicci ed esegui letture, analisi e test da solo. Non fermarti in continuazione per chiedere permessi per ogni singolo step: procedi spedito fino al report finale. Applica una RIVALUTAZIONE GLOBALE a tutto il progetto esistente (tutte le fasi costruite finora) alla luce di queste regole, scovando i punti deboli.

**2. IL CICLO ITERATIVO E I 10 TEST**
Non accettare mai la prima soluzione. Componi, testa, distruggi, ricomponi. Crea obbligatoriamente 3 o 4 varianti diverse per ogni singolo pezzo. IL CODICE DEVE ESSERE INSERITO E TESTATO RIPETUTAMENTE, ALMENO 10 VOLTE! Devi scovare i bug e distruggerli.

**3. [PRIORITÀ ASSOLUTA E SUPREMA]**
SOTTOPONI LE VARIANTI A UN BENCHMARK SOTTO CARICO ESTREMO. IL CODICE CHE INTEGRERAI NEL NUCLEO (SIA NUOVO CHE VECCHIO) DEVE ESSERE RIGOROSAMENTE E UNICAMENTE LA **VINCITRICE DEL BENCHMARK**, QUELLA CHE SOPRAVVIVE A TUTTI I 10 TEST. NESSUN COMPROMESSO.

**4. [REGISTRO D'INGEGNERIA — OBBLIGATORIO]**
Ogni volta che crei o modifichi una funzione/modulo, AGGIORNA `REGISTRO_INGEGNERIA.md` (creazione · scopo · logica · dipendenze/env · STATO acceso/spento · come si attiva) **E la sezione "DA FARE / PROSSIMI PASSI"** (togli ciò che hai completato, aggiungi ciò che resta): così "cosa è fatto" e "cosa manca" stanno SEMPRE insieme e aggiornati. Niente resta "costruito e dimenticato": se una cosa è costruita ma NON attivata, va scritta nella sezione "COSTRUITO ma SPENTO" con come accenderla. Regola del fondatore: questo va fatto a OGNI completamento, da CHIUNQUE tocchi il codice — **incluso il collaudatore (Fable 5)**: anche ogni bug corretto in collaudo va scritto nel registro (cosa era rotto, come l'hai sistemato, test aggiunto). Non si perde la logica di NULLA. Il test `test_registro_ingegneria.py` è la guardia auto-applicante (una nuova `faseNN_*.py` non registrata fa fallire la suite). Il collaudatore (Fable 5) legge il registro per sapere cosa esiste e cosa testare.
