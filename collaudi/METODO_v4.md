# METODO — Guida definitiva per controllare il software

Versione 4. Sostituisce le versioni 1, 2 e 3.
Questa è la guida da cui si riparte ogni volta.
Un file solo. Non ne esistono altri.

---

## COME SI USA

Non si legge tutta. Si apre alla parte che serve.

- **Software nuovo** → PARTE 16, poi PARTE 2 e PARTE 3, prima di scrivere il resto
- **Software già fatto** → PARTE 10 (audit), poi PARTE 11 (classificare)
- **Non so se i miei test valgono qualcosa** → PARTE 18.1. È la prima cosa da fare.
- **Voglio i nomi degli strumenti** → PARTE 17. Sono tutti gratis.
- **Prima di aprire ai clienti** → PARTE 12. Quella è la porta.
- **Le carte che il codice non copre** → PARTE 19
- **Quando trovo un difetto** → PARTE 11, e poi chiudo la famiglia

**La regola sopra tutte le altre:**

> Quando trovo un difetto, non riparo l'esemplare.
> Chiudo la **famiglia**, con un controllo meccanico che gira per sempre.

**La seconda regola:**

> Non punto a "non sbaglia mai". Punto a "qualunque cosa sbagli, lo so entro 24 ore".

La prima non esiste per nessuno. Nemmeno per Stripe, che scrive nella propria documentazione che a volte un evento si perde e non è recuperabile. La seconda è raggiungibile da una persona sola, ed è quella che usano tutti.

---

# PARTE 1 — I NUMERI CHE MI RICORDO

Misure fatte da altri, non opinioni.

| Cosa | Numero |
|---|---|
| Difetti nuovi creati riparando difetti vecchi (media) | 7% |
| Lo stesso, su codice complicato o da principiante | fino al 25%, casi estremi 75% |
| Difetti trovati da chi collauda il proprio codice | mai oltre il 35% |
| Difetti trovati da collaudatori addestrati con strumenti | fino al 65% |
| Ispezioni formali del codice | oltre il 65% |
| Studio comparativo — strumenti automatici | 76% |
| Studio comparativo — revisione umana | 20% |
| Studio comparativo — i test | 4% |
| Combinazione ispezioni + analisi statica + collaudo | oltre il 95% |
| Costo di una riga certificata per l'aeronautica (Livello A) | circa 100 dollari |
| Costo di una riga dimostrata matematicamente (seL4) | circa 350 dollari |
| Sforzo di verifica formale al crescere del sistema | cresce col **quadrato** |
| Imparare TLA+ da zero e ottenere risultati utili (Amazon) | 2-3 settimane |

**Cosa mi dicono davvero:**

1. Se riparo 200 difetti a mano, ne creo tra i 14 e i 50 nuovi.
2. I test da soli non superano un terzo. **Aggiungerne non alza il tetto.** Serve uno strato diverso.
3. Ogni tecnica vede una famiglia diversa. Per questo "ne escono sempre altri".
4. La verifica matematica completa è fuori portata. **La versione leggera no.**

---

# PARTE 2 — I NOVE STRATI

Ogni strato prende una famiglia diversa. Nessuno sostituisce gli altri.

| # | Strato | Cosa prende | Costo |
|---|---|---|---|
| 1 | Vincoli e tipi | Ciò che non deve essere rappresentabile | basso |
| 2 | Analisi statica | Errori di codice, chiavi esposte, codice morto | bassissimo |
| 3 | Test | Casi noti, regressioni | già fatto |
| 4 | Proprietà e invarianti | Famiglie intere, non casi | medio |
| 5 | Modello di riferimento | Calcoli sbagliati | medio |
| 6 | Simulazione | Concorrenza, ordine, corse | medio |
| 7 | Verifica mentre gira | Ciò che è già uscito | medio |
| 8 | Riconciliazione | Ciò che nessuno strato ha visto | alto valore |
| 9 | Revisione umana indipendente | Ciò che non ho mai pensato | si compra |

**Se ho solo lo strato 3, ho un terzo della copertura possibile.** Questo è il punto di partenza di quasi tutti.

---

# PARTE 3 — I SOLDI

La parte più lunga, perché è quella dove sbagliare fa danno vero.

## 3.1 — Come si scrive il denaro

**Mai numeri con la virgola in memoria.** Il computer lavora in base 2, i soldi sono in base 10. `0.1 + 0.2` non fa `0.3`. Su migliaia di operazioni gli errori si sommano e diventano soldi veri.

- [ ] Ogni importo è un **numero intero in unità minime** (centesimi)
- [ ] 100,00 € si scrive `10000`
- [ ] Ai bordi (schermo, API, fatture) converto; dentro mai
- [ ] Rifiuto gli importi con troppe cifre decimali per la valuta, **non li arrotondo di nascosto**

**L'arrotondamento.** Il computer di suo arrotonda "al pari": 2,5 → 2. La contabilità arrotonda per eccesso: 2,5 → 3. Se non lo dico esplicitamente, il computer fa il suo.

- [ ] La regola di arrotondamento è scritta in un posto solo, ed è la regola contabile
- [ ] Non arrotondo due volte (arrotondare un già arrotondato sposta il risultato)

**La divisione — il difetto più subdolo.** Dividere 10 centesimi in tre parti dà 3,33. Tre volte 3 fa 9. **Manca un centesimo.** Ripetuto mille volte, sono dieci euro spariti dal nulla.

La regola contabile:

> Do a tutti la parte intera, poi distribuisco il resto un centesimo alla volta finché il resto è zero.

- [ ] La divisione dei soldi passa da una funzione sola, che restituisce parti che **sommano esattamente** al totale
- [ ] Un test che prova mille divisioni a caso e verifica che la somma torni sempre

## 3.2 — Partita doppia e registro immutabile

Il cuore. Se sbaglio qui, tutto il resto è inutile.

- [ ] Nessuna tabella di saldi che sovrascrivo
- [ ] Ogni movimento è una riga nuova; le righe non si modificano mai
- [ ] Ogni addebito ha un accredito corrispondente
- [ ] Somma addebiti = somma accrediti. Sempre.
- [ ] Un errore si corregge **aggiungendo** una riga di rettifica
- [ ] Il saldo si **calcola**, non si conserva
- [ ] Nessun movimento di denaro esiste senza una riga nel registro

**L'ultima riga è la più importante.** Si chiama *completezza*, e rende impossibile per costruzione il difetto "i soldi si fermano e nessuno lo sa".

Non è teoria: Uber ci ha messo 2 anni e 40 ingegneri a passarci; Airbnb 4 anni; Stripe lo usa dentro. **Chi comincia senza, ci torna dopo pagando cento volte tanto.**

I conti minimi da avere: *Incassi da ospiti*, *Debito verso host*, *Ricavi commissioni*, *Commissioni fornitore*, *Rimborsi*, *Dispute*.

## 3.3 — Idempotenza

Il caso che uccide: mando l'addebito, la connessione cade prima della risposta. Ha funzionato? Non lo so.

**In uscita** (io chiamo Stripe):
- [ ] Ogni chiamata che muove soldi porta una chiave di idempotenza
- [ ] La chiave si salva **prima** della chiamata, mai dopo
- [ ] Vincolo unico nel database sulla chiave

Nota tecnica: Stripe conserva il risultato della prima chiamata per quella chiave — **compreso un errore 500** — e lo rigioca per 24 ore. Dopo 24 ore la chiave decade.

**In entrata** (Stripe chiama me):
- [ ] Deduplicazione sull'identificativo dell'evento (`evt_...`)
- [ ] La memoria della deduplicazione dura **almeno quanto la finestra di ritentativi**

**Attenzione a questo dettaglio, è una trappola classica:** Stripe ritenta per 72 ore. Se la mia memoria di deduplicazione dura 24 ore, un ritentativo del terzo giorno passa come evento nuovo e viene elaborato due volte. **La memoria deve durare almeno 3 giorni.**

## 3.4 — Webhook

Tre verità da tenere in testa, tutte dichiarate da Stripe:

1. **Consegna almeno una volta.** Lo stesso evento può arrivare più volte.
2. **Nessuna garanzia di ordine.** Un evento più recente può arrivare prima di uno più vecchio.
3. **Ritentativi per 72 ore**, con attese crescenti: subito, 5 minuti, 30 minuti, 2 ore, 5 ore, 10 ore, 24 ore… circa 15-18 tentativi. Dopo 3 giorni l'evento è perso per sempre.

La struttura giusta del gestore, in quest'ordine:

- [ ] **1.** Verifica la firma sul corpo **grezzo** della richiesta
      *(se un pezzo di codice trasforma il corpo in JSON prima della verifica, la firma non torna mai)*
- [ ] **2.** Salva l'evento grezzo con il suo identificativo
- [ ] **3.** Rispondi 200 **subito** (limite: 30 secondi, ma punta a meno di uno)
- [ ] **4.** Elabora dopo, separatamente, con deduplicazione

E la regola che quasi tutti sbagliano:

- [ ] **Se l'elaborazione fallisce, NON rispondere 200.** Fai fallire, così Stripe ritenta.

Rispondere 200 significa dire "ricevuto, tutto a posto, non riprovare". Stripe ci crede e butta via l'evento. **Rispondere sempre 200 è il modo esatto in cui i soldi spariscono in silenzio.**

Ultimo pezzo, quello che chiude il cerchio:

- [ ] **Non elaborare mai il contenuto del webhook come verità.** Prendi l'identificativo e **richiedi l'oggetto all'API.** Così l'ordine di arrivo non conta più: leggi sempre lo stato attuale, non quello di quando l'evento è partito.

## 3.5 — Il paracadute: gli eventi che si perdono

Stripe scrive nella propria documentazione che in casi rari può fallire nella generazione dell'evento. In quel caso l'evento è **irrecuperabile**: non viene consegnato, non appare nel cruscotto, non appare nell'elenco eventi.

La loro soluzione ufficiale è: **interroga l'API e riallineati.**

Questo dimostra il punto di partenza di tutta la guida. **Il webhook perfetto non basta, perché a volte il webhook non esiste.**

- [ ] Un processo che, ogni notte, chiede a Stripe l'elenco delle operazioni del giorno e lo confronta con il mio database
- [ ] Tutto ciò che c'è da una parte e non dall'altra diventa un'eccezione

Questo processo è il punto 3.7 e vale più di tutto il resto della PARTE 3.

## 3.6 — Casella d'uscita transazionale

Il nome del difetto: **doppia scrittura**. Salvo nel database e poi faccio un'altra cosa (mando una mail, chiamo Stripe, aggiorno il calendario). Se il sistema cade in mezzo, la prima è fatta e la seconda no. Per sempre.

La soluzione:

- [ ] Nella **stessa transazione** in cui salvo il fatto, scrivo in una tabella "cose da fare"
- [ ] Un processo separato legge quella tabella e le fa
- [ ] Se fallisce, ritenta con attese crescenti
- [ ] Dopo N tentativi la riga passa nella **tabella dei morti**, e mi arriva un allarme
- [ ] Una riga morta non blocca le successive

**Con SQLite è una tabella in più.** Non serve altro.

Questo strato da solo chiude tutta la famiglia "operazioni che si fermano zitte".

## 3.7 — Riconciliazione

Lo strato più forte che esiste. È il motivo per cui "lo so entro 24 ore" è raggiungibile.

**Due vie**: il mio registro contro i dati di Stripe. Conferma che Stripe è d'accordo con me.
**Tre vie**: il mio registro contro Stripe contro l'**estratto conto bancario**. Conferma che i soldi sono davvero arrivati.

La differenza è tutta: la due vie conferma che il fornitore riconosce l'operazione, ma **non conferma che i fondi siano arrivati in banca**. La tre vie distingue la certezza dell'incasso dalla supposizione.

Per collegare un solo versamento Stripe servono quattro identificativi legati fra loro: `charge_id`, `payment_intent_id`, `balance_transaction_id`, `payout_id`. **Vanno salvati tutti e quattro.** Se ne salvo solo uno, la riconciliazione diventa impossibile dopo.

### Le categorie di eccezione

Ogni disallineamento va classificato, non guardato a occhio:

| Categoria | Cosa vuol dire | Cosa faccio |
|---|---|---|
| Differenza di tempo | L'operazione c'è ma non è ancora regolata | Si chiude da sola entro 24-72 ore |
| Variazione di cambio | Importo diverso per il cambio | Si chiude da sola sotto la tolleranza |
| Differenza di commissione | Stripe ha trattenuto una cifra diversa dall'attesa | Da guardare |
| **Accredito bancario mancante** | Stripe dice pagato, la banca no | **Allarme immediato** |
| **Operazione sconosciuta** | C'è da una parte e non esiste dall'altra | **Allarme immediato** |

Le ultime due sono le uniche che richiedono di svegliarsi.

### I numeri da tenere

- [ ] **Tasso di riconciliazione automatica**: sopra il 95%. Sotto, la logica di abbinamento è debole, non serve lavorare di più.
- [ ] **Età delle eccezioni aperte**: un'eccezione aperta da più di 24-48 ore non è un fastidio, **è un guasto di processo**.
- [ ] **Tempo medio di chiusura**: da misurare come si misura l'uptime.

Una eccezione aperta è, di fatto, un pezzo dei miei numeri di cui non mi posso fidare.

### Cosa serve davvero, per uno solo

Un processo notturno che:
1. Scarica le operazioni Stripe del giorno
2. Le confronta con il registro
3. Classifica le differenze
4. Manda **una mail sola**, con le eccezioni divise per categoria
5. Se ci sono accrediti mancanti o operazioni sconosciute, la mail ha "URGENTE" nell'oggetto

Se una mattina non arriva la mail, **anche quello è un allarme.**

## 3.8 — Commissioni e rimborsi

Regola che cambia i conti, e va decisa una volta:

**La commissione che il fornitore trattiene sull'incasso NON viene restituita quando rimborsi.** La commissione di elaborazione, quella di Connect, quella di cambio: nessuna torna indietro. Il cliente riceve il 100%, ma io ho già perso la commissione.

Quindi **ogni rimborso è una perdita secca** pari alla commissione originale.

Secondo pezzo, per chi fa marketplace:

**La commissione di piattaforma non si rimborsa da sola.** Se rimborso l'addebito e non rimborso esplicitamente la mia commissione, la piattaforma se la tiene e **il costo se lo mangia l'host.** Serve una chiamata separata per restituirla, e si può restituire anche solo in parte.

Le tre scelte possibili, da mettere per iscritto nelle condizioni:

- **A** — La piatta­forma si mangia tutto (commissione fornitore + propria). Più gentile, costa a me.
- **B** — La piattaforma restituisce la propria commissione ma non quella del fornitore, che resta a carico di chi ha deciso il rimborso.
- **C** — Nessuna commissione torna. Il rimborso è netto della commissione. Va scritto molto chiaramente all'ospite, o diventa una contestazione.

- [ ] Ho scelto A, B o C: ______
- [ ] È scritto nelle condizioni, nella stessa fonte unica da cui legge il codice
- [ ] Il registro contabile ha una riga apposta per la commissione persa

## 3.9 — Dispute

Con le forme di addebito indirette, la piattaforma viene addebitata dell'importo conteso **e della penale**, dal proprio saldo. Recuperare i soldi dall'host è una operazione separata, che può fallire se l'host non ha saldo.

- [ ] So dal mio codice, per ogni prenotazione, chi paga se arriva una disputa
- [ ] C'è una riga di registro per l'importo conteso e una per la penale
- [ ] Se il saldo dell'host va sotto zero, lo so subito

---

# PARTE 4 — CALENDARIO E DISPONIBILITÀ

Il difetto specifico di questo mestiere. Due ospiti, stessa casa, stesse date, entrambi confermati.

## 4.1 — Dentro il mio sistema

- [ ] **Vincolo nel database** che rende impossibile la sovrapposizione. Non un controllo nel codice: un vincolo.
- [ ] Il controllo di disponibilità e la scrittura stanno nella **stessa transazione**. Mai "guardo, poi scrivo".
- [ ] Le date si bloccano **subito**, allo stato "in corso", non alla conferma del pagamento. Il blocco scade da solo se il pagamento non arriva.
- [ ] Il pestaggio del simulatore (PARTE 9) prova cinquanta prenotazioni insieme sulla stessa casa

Il punto 3 è quello che chiude la finestra di corsa. Senza, fra il "sto pagando" e il "ho pagato" ci sono venti secondi in cui chiunque può prenotare le stesse date.

## 4.2 — Verso l'esterno

Se un giorno collego Airbnb o Booking, questo diventa il rischio numero uno.

Il calendario condiviso via file iCal **non è in tempo reale**: si aggiorna a intervalli che vanno da 30 minuti a 3 ore, in certi casi 24 ore. Airbnb conferma subito, ma l'altra piattaforma non vede il blocco per 30-90 minuti. **In quella finestra, la doppia prenotazione è normale, non è un difetto.**

- [ ] So che il collegamento via file è una finestra di rischio, non una soluzione
- [ ] Ogni sincronizzazione è registrata con l'ora esatta — serve come prova se una piattaforma mi contesta
- [ ] Ho una procedura scritta per quando succede (chi si sposta, chi paga)

## 4.3 — Date e orari

Famiglia di difetti sottovalutata:

- [ ] Le date di arrivo e partenza hanno un **fuso orario esplicito**, quello della casa, non quello del server
- [ ] Il cambio ora legale non sposta le notti (una notte non è "24 ore")
- [ ] Le notti si contano fra due date, non fra due momenti
- [ ] Un test con una prenotazione a cavallo del cambio ora legale e uno a cavallo di Capodanno

---

# PARTE 5 — DATI E PRIVACY

## 5.1 — Cancellazione completa

Il difetto tipico: la cancellazione tocca gli archivi principali e dimentica registri, cache, esportazioni, backup.

La posta in gioco: fino a 20 milioni di euro o il 4% del fatturato globale.

**Strada A — cascata con conferma** (più semplice, consigliata):

- [ ] Elenco scritto di **tutti** i posti dove finiscono dati personali
- [ ] La cancellazione manda una richiesta a ognuno
- [ ] **Ognuno risponde confermando.** Se uno non conferma, la cancellazione risulta incompleta e diventa un errore visibile.
- [ ] Un test che conta i posti confermati e li confronta con l'elenco

Il numero di archivi nell'elenco e il numero di conferme **devono essere lo stesso numero**. Questo è un test, non una speranza.

**Strada B — distruzione della chiave.** Non cerco i dati: li cifro e distruggo la chiave. Il dato resta ma diventa rumore illeggibile.

È riconosciuta esplicitamente come cancellazione valida dal Comitato europeo per la protezione dei dati, dall'autorità britannica e da quella francese, a tre condizioni: algoritmo forte, distruzione irreversibile (nessuna copia di riserva), e distruzione dimostrabile.

Trappola: **serve una chiave diversa per ogni persona.** Con una chiave sola per tutti, distruggerla renderebbe illeggibili i dati di tutti.

La strada B è l'unica che risolve anche i backup. La strada A lascia quel buco aperto.

## 5.2 — Altre righe

- [ ] So elencare, senza pensarci, tutti i posti dove finiscono dati personali
- [ ] So dire per ogni archivio quanto a lungo tengo i dati e perché
- [ ] L'esportazione dei propri dati funziona quanto la cancellazione

---

# PARTE 6 — PROMESSE E CODICE

La causa non è la disattenzione. È la **duplicazione**: lo stesso numero esiste in dodici posti.

## 6.1 — Una sola fonte

- [ ] Un file solo con tutti i numeri e gli impegni, scritti una volta
- [ ] Il codice legge da lì
- [ ] Un controllo cerca nel codice i numeri fissi che dovrebbero venire dalla fonte
- [ ] I testi ricevono il numero dentro; traducono le parole, **mai le cifre**
- [ ] Un controllo verifica che nessun testo tradotto contenga cifre
- [ ] Le prove leggono dalla stessa fonte
- [ ] Le condizioni contrattuali leggono dalla stessa fonte

## 6.2 — Tracciabilità nei due versi

Quello che l'aeronautica ha reso obbligatorio per legge. Costa poco.

- [ ] **Ogni promessa punta ad almeno un pezzo di codice.** Se no: rosso.
- [ ] **Ogni funzione pubblica punta ad almeno una promessa.** Se no: le do una promessa o **la cancello**.

Due test, un secondo di esecuzione, due famiglie chiuse per sempre.

## 6.3 — Lingue

- [ ] Ogni chiave esiste in tutte le lingue. Se ne manca una: rosso.
- [ ] Nessuna cifra dentro le traduzioni
- [ ] Nessun testo lasciato nella lingua di partenza dentro le altre
- [ ] Le stesse relazioni della PARTE 7 girano su ogni lingua e devono dare lo stesso numero

---

# PARTE 7 — PROPRIETÀ CHE SI SORVEGLIANO DA SOLE

## La regola

Un **test** dice: "con questo dentro, deve uscire questo". Copre un caso.
Una **proprietà** dice: "comunque vada, questo deve essere vero". Copre una famiglia.

**Il segreto: non nominare mai un valore preciso.**

## 7.1 — Invarianti (girano su tutto lo stato)

- [ ] Somma addebiti = somma accrediti
- [ ] Incassato = versato + commissioni + rimborsi + trattenuto
- [ ] Nessun saldo host negativo senza una disputa che lo spieghi
- [ ] Ogni pagamento ha esattamente un movimento nel registro
- [ ] Nessuna sovrapposizione di date sulla stessa casa
- [ ] Calendario bloccato = prenotazioni confermate, né un giorno in più né uno in meno
- [ ] Nessuna prenotazione pagata senza stato finale
- [ ] Ogni riga visibile al suo proprietario e a nessun altro
- [ ] Nessun annuncio prenotabile se l'host non può ricevere denaro
- [ ] Ogni rimborso ha una prenotazione annullata e un calendario liberato

## 7.2 — Relazioni fra due esecuzioni

Legami veri senza sapere il risultato giusto di nessuna delle due.

- [ ] Aggiungo una notte → il prezzo non scende
- [ ] Stessa prenotazione in 8 lingue → stesso identico numero
- [ ] Faccio e disfo → tutto torna com'era
- [ ] Cambio l'ordine di due operazioni indipendenti → stesso risultato
- [ ] Rimborso totale → il saldo torna al valore di partenza
- [ ] Cambio valuta e torno indietro → stesso importo
- [ ] Divido una commissione fra N parti → le parti sommano al totale, per ogni N

**Poche relazioni ben diverse fra loro battono venti relazioni simili.**

## 7.3 — Modello di riferimento eseguibile

Il metodo usato da Amazon su un componente di S3 da 40.000 righe. Ha impedito a 16 problemi di arrivare in produzione, ed è stato esteso da persone non esperte.

- [ ] Seconda versione della regola, **stupida e ovviamente giusta**, venti righe
- [ ] Nello **stesso linguaggio** del codice vero, dentro i test
- [ ] Mille casi a caso su tutte e due, confronto
- [ ] Se divergono, il caso viene stampato

Da fare su: calcolo prezzo, divisione commissioni, calcolo saldi.

## 7.4 — Mentre gira

- [ ] Le invarianti della 7.1 girano ogni ora sui dati veri
- [ ] Allarme quando una salta
- [ ] Riconciliazione notturna (PARTE 3.7)

---

# PARTE 8 — TROVARE IN AUTOMATICO

- [ ] **Analisi statica** su tutto, ad ogni modifica
- [ ] **Golden test**: 200 casi salvati e confrontati
- [ ] **Rilevamento codice morto** — a blocchi, con la suite verde in mezzo, perché "mai chiamata" a volte è falso
- [ ] **Scansione segreti** — nessuna chiave nel codice, soprattutto quello che arriva al browser
- [ ] **Scansione dipendenze** — nessuna libreria con falle note
- [ ] **Fuzzing** sui punti dove entrano dati da fuori
- [ ] **Tipi rigorosi** in modo severo
- [ ] **Tetto alla complessità** per funzione
- [ ] **Mutation testing** — vedi PARTE 18.1

I nomi degli strumenti, tutti gratis, stanno nella PARTE 17.

Limite onesto sul fuzzing: un progetto seguito per sette anni aveva ancora falle gravi, perché copriva il 19% del codice. **Ogni tecnica automatica vale quanto la parte di codice che raggiunge.**

---

# PARTE 9 — IL SIMULATORE

- [ ] **Posta finta** in locale
- [ ] **Pagamenti finti** (modalità prova o finto server)
- [ ] **Popolamento**: un comando crea N utenti, N case, N prenotazioni
- [ ] **Il seme**: un numero che comanda tutta la casualità
- [ ] **Il pestaggio**: cinquanta operazioni insieme sulla stessa casa
- [ ] **I controllori** della PARTE 7.1 girano dopo

**La cosa preziosa non sono le mille operazioni. Sono i controllori.** Senza, mille operazioni danno mille "ok" e non so niente.

**Sul seme:** senza, quando uno su mille va storto, ho visto il fantasma e non lo riprendo più.

---

# PARTE 10 — L'AUDIT

Le direzioni da guardare. Ognuna è una lettura in sola lettura del codice, e produce un elenco.

1. Numeri promessi nei testi contro numeri nel codice
2. Promesse senza codice dietro
3. Punti dove un'operazione può fermarsi in silenzio
4. Funzioni mai chiamate e codice mai raggiunto
5. Regole di un solo paese applicate senza guardare il paese
6. Scompagnamenti fra le lingue
7. Valori scritti a mano in più posti
8. Punti dove due file dicono cose diverse
9. Porte promesse che non esistono
10. Differenze fra ambiente di prova e produzione
11. Chi può vedere la roba di chi
12. Dove finiscono i dati personali, archivio per archivio
13. Cosa succede se cade a metà (ogni operazione a due passi)
14. Ogni numero con la virgola che tocca soldi
15. Ogni data senza fuso orario

---

# PARTE 11 — IMPARARE DAI DIFETTI

Per ogni difetto non registro solo cos'era. Registro **cosa lo ha fatto uscire allo scoperto**.

Costa meno di 3 minuti a difetto. Alla fine ho la mappa di dove sono cieco — misurata, non indovinata.

| # | Cosa era | Cosa lo ha fatto uscire | Che controllo l'avrebbe preso | Famiglia chiusa? |
|---|---|---|---|---|
| | | | | |

Poi conto per famiglia. **La famiglia con più difetti è quella dove mi manca uno strato.**

---

# PARTE 12 — LA PORTA

Prima di prendere soldi veri di sconosciuti. Nessuna percentuale: tutte sì o no.

**Soldi**
- [ ] Nessun numero con la virgola tocca il denaro
- [ ] La divisione delle commissioni somma sempre al totale
- [ ] Partita doppia attiva, addebiti = accrediti
- [ ] Chiavi di idempotenza con vincolo unico
- [ ] Deduplicazione webhook che dura almeno 3 giorni
- [ ] Il gestore webhook fa firma → salva → 200 → elabora dopo
- [ ] L'elaborazione fallita **non** risponde 200
- [ ] Lo stato si legge dall'API, non dal contenuto dell'evento
- [ ] Casella d'uscita con tabella dei morti e allarme
- [ ] Riconciliazione notturna con mail, anche quando è tutto a posto
- [ ] Scelta A/B/C sulle commissioni nel rimborso, scritta nelle condizioni
- [ ] Un giro completo con soldi veri miei, rimborso compreso

**Calendario**
- [ ] Vincolo di non sovrapposizione nel database
- [ ] Blocco date allo stato "in corso", con scadenza
- [ ] Cinquanta prenotazioni insieme sulla stessa casa: nessuna doppia

**Accessi**
- [ ] Prove "non puoi vedere la roba di un altro": ___ su ___
- [ ] Nessuna chiave nel codice che arriva al browser
- [ ] Il prezzo si decide sul server: lo cambio nella pagina e il sistema rifiuta

**Dati**
- [ ] Numero archivi nell'elenco = numero conferme di cancellazione
- [ ] Esportazione dati funzionante

**Coerenza**
- [ ] Una sola fonte per numeri e promesse
- [ ] Tracciabilità nei due versi, entrambe verdi
- [ ] Tutte le lingue complete, nessuna cifra tradotta

**Robustezza**
- [ ] Punteggio del mutation testing sul codice dei soldi: ___ %
- [ ] Analisi statica verde su ogni modifica, senza avvisi ignorati
- [ ] Nessuna libreria con falle note
- [ ] Ogni funzione nuova ha un interruttore che la spegne in dieci secondi
- [ ] Prova con guasto: ammazzo il sistema a metà di un pagamento e guardo cosa resta a metà

**Il mondo reale**
- [ ] Tutti i percorsi provati a mano: ___ su ___
- [ ] Ripristino del backup provato davvero, cronometrato
- [ ] **Un umano che fa audit di mestiere ha guardato dove entrano i soldi**
- [ ] Il commercialista ha scritto nero su bianco cosa sono, fiscalmente
- [ ] Le condizioni per host e per ospite le ha lette un avvocato
- [ ] La busta chiusa esiste ed è fuori dal mio computer (PARTE 19.4)

L'unica riga che non posso spuntare da solo è quella dell'umano. **È anche la più importante.**

---

# PARTE 13 — REGISTRO DELLE FAMIGLIE CHIUSE

La parte viva. Cresce e mi segue da un software all'altro.

| Famiglia | Nome pubblico | Controllo che la chiude | Dove gira | Dal |
|---|---|---|---|---|
| Numeri promessi diversi dal codice | — | Fonte unica + controllo numeri fissi | test | |
| Testi scompagnati fra lingue | — | Le cifre non si traducono | test | |
| Promesse senza codice | requirements traceability | Tracciabilità alto→basso | test | |
| Funzioni mai chiamate | dead code detection | Tracciabilità basso→alto | test | |
| Soldi fermi che nessuno vede | transactional outbox | Casella d'uscita + coda dei morti | produzione | |
| Operazione che fallisce sempre | dead letter queue | Tabella dei morti + allarme | produzione | |
| Evento doppio o perso | webhook idempotency | Deduplicazione ≥ 3 giorni | produzione | |
| Doppio addebito | idempotency key | Chiave + vincolo unico | database | |
| Conti che non tornano | double-entry ledger | Partita doppia | database | |
| Ciò che nessuno strato ha visto | reconciliation | Riconciliazione notturna | produzione | |
| Centesimi che spariscono | penny allocation | Divisione con resto distribuito | test | |
| Doppia prenotazione | overbooking race | Vincolo unico + transazione | database | |
| Cancellazione incompleta | cascading deletion | Cascata con conferma | test | |
| Test che non prendono niente | mutation testing | Mutanti sopravvissuti = 0 sui soldi | test | |
| Stato cambiato di nascosto | explicit state machine | Tabella delle transizioni permesse | codice | |
| Guasto che non so riprodurre | deterministic simulation | Il seme + orologio finto | test | |
| Chiave finita nel codice | secret scanning | Scansione ad ogni modifica | test | |
| Libreria con falle note | dependency scanning | Scansione ad ogni modifica | test | |
| | | | | |

**Una famiglia chiusa non si riapre.** Se torna, il controllo era debole: lo rinforzo, non ne aggiungo un altro.

Le parole nella colonna "nome pubblico" sono la mia chiave di ricerca. Ognuna ha dietro vent'anni di aziende che ci hanno sbattuto la testa.

---

# PARTE 14 — QUELLO CHE NON SI PUÒ AUTOMATIZZARE

Da rileggere ogni volta che sembra di poter arrivare al 100%.

**1. Se la regola è giusta.**
Tutto questo verifica che il codice faccia quello che ho detto. Niente verifica che io abbia detto bene. Una commissione sbagliata nella regola, applicata alla lettera dal codice: tutti i controlli passano felici.

**2. Quello che non ho mai scritto.**
Il controllo di sicurezza che non esiste non ha un test che fallisce. Non c'è niente da far fallire.

**3. La revisione indipendente.**
Chi ha scritto una cosa non vede il proprio errore. Non è bravura, è come è fatta la testa. **Si compra, non si automatizza.**

**4. Quello che gli strumenti non raggiungono.**
Il 19% di copertura in sette anni.

**5. Il fornitore che sbaglia.**
Anche Stripe perde eventi e lo scrive. **Per questo esiste la riconciliazione.**

---

## LA COSA DA PORTARSI VIA

I test restano dentro il software che ho fatto. **Questo documento viene con me.**

È l'unico patrimonio che si accumula da un progetto al successivo. Ogni famiglia nuova che chiudo va nella PARTE 13. Il software numero due parte da dove è finito il numero uno.

---

# PARTE 15 — COSA FANNO DAVVERO I PIÙ GRANDI

Non quello che dicono nelle pubblicità. Quello che pubblicano nei propri documenti tecnici.

## La scoperta che vale più di tutte

**Nessuno di loro dichiara di prevenire tutti i difetti.**

Guarda come sono costruiti i loro sistemi: sono tutti costruiti **intorno ai guasti già successi**, non intorno alla loro assenza.

- Amazon: la lista di controllo prima del lancio nasce distillando gli incidenti passati
- Google: la regola sui test dice "se ci tenevi, dovevi metterci un test" — cioè è nata dai difetti sfuggiti
- Netflix: rompe apposta i propri sistemi in produzione
- Microsoft: il proprio processo di sicurezza nasce da una crisi, nel 2002, ed è obbligatorio dal 2004

**Il più potente sistema di qualità software del mondo è un anello chiuso che parte dai guasti.** Non un muro che li impedisce.

Questo è il permesso di smettere di inseguire la perfezione, e la mappa di cosa inseguire invece.

## 15.1 — Amazon: i due meccanismi

**COE — Correzione degli Errori.**

È un meccanismo ad anello chiuso di analisi dopo l'incidente, applicato a **ogni evento di rilievo, anche quando il cliente non si è accorto di niente**.

Non è un semplice resoconto: la differenza dichiarata è che **il centro sono le azioni correttive, non la descrizione del guasto**.

Il metodo dentro è i "cinque perché", preso da Toyota. E c'è una riga che vale da sola tutta la parte:

> Se vedi "errore umano" come causa radice, probabilmente sta indicando una **mancanza di controlli o di meccanismi a prova di errore**. Quindi devi sempre chiedere perché l'umano ha potuto sbagliare.

Traduzione: **"ho sbagliato io" non è mai una causa radice.** È il segnale che manca un vincolo.

**ORR — Revisione di Prontezza Operativa.**

Una lista di controllo da superare prima di mandare in produzione. Fatta di raccomandazioni di architettura, processo operativo, gestione degli eventi e qualità del rilascio.

Il punto chiave dichiarato: **l'ORR non serve solo a seguire le buone pratiche, serve a impedire il ripetersi di eventi già visti.** Ed è alimentata direttamente dal COE.

E l'anello si chiude qui: il modulo del COE contiene la domanda *"qualche raccomandazione della lista avrebbe ridotto o evitato l'impatto di questo evento?"*.

Consiglio pratico che danno loro: **alla prima versione, non più di trenta voci.**

**Cosa prendo io:** la mia PARTE 12 è la mia ORR. La mia PARTE 11 è il mio COE. E dopo ogni guasto mi chiedo: *quale riga della PARTE 12 mancava?* Se nessuna, ne aggiungo una.

## 15.2 — Google: due regole e un numero

**La regola del test.** "Se ci tenevi, dovevi metterci un test." Se un cambiamento non collegato rompe una cosa a cui tenevi e nessun test se ne accorge, **la colpa non è del cambiamento**: è del test mancante.

**La regola sui guasti.** Dichiarata così: invece di aspettare un guasto, si scrivono prove automatiche che **simulano i guasti comuni** — errori iniettati, chiamate remote che falliscono, ritardi.

**Il numero che nessuno cita e che è il più utile di tutti.**

Google ha misurato che gli strumenti di analisi con un tasso di falsi allarmi **sopra il 10% venivano regolarmente ignorati o disattivati** dagli sviluppatori. Per questo hanno imposto quella soglia come condizione per far girare uno strumento in produzione.

**Questa è la regola più importante per me, e riguarda i miei allarmi.**

Se il mio allarme notturno suona per cose che non contano, in tre settimane smetto di leggerlo. E il giorno in cui suona per davvero, non lo guardo. **Un allarme rumoroso è peggio di nessun allarme**, perché mi dà la sensazione di essere coperto.

Regola mia, da oggi: **un allarme che suona a vuoto va aggiustato entro la settimana, o spento.**

## 15.3 — Microsoft: obbligatorio, non consigliato

Il loro processo di sicurezza è **politica aziendale obbligatoria dal 2004**, e tutti i gruppi di sviluppo devono seguirlo. Cinque fasi: requisiti, progetto, realizzazione, verifica, rilascio.

Il pezzo trasferibile è la **modellazione delle minacce**: prima di scrivere, si disegna come scorrono i dati, si guarda ogni pezzo dagli occhi di chi vuole entrare, e si scrive per ogni minaccia il controllo che la ferma e cosa si fa se il controllo cede.

Fatto con un foglio e una matita, funziona anche per una persona sola. È l'equivalente software della FMEA che si fa negli impianti.

## 15.4 — NASA / JPL: le dieci regole

Del 2006, di Gerard Holzmann, laboratorio per il software affidabile del JPL. Scritte per il C, ma il senso vale ovunque. Le cinque che valgono per me:

1. **Ogni ciclo ha un tetto massimo fisso.** Niente che possa girare all'infinito.
2. **Nessuna funzione più lunga di un foglio stampato** — circa 60 righe.
3. **Almeno due asserzioni per funzione, in media.** Servono a controllare condizioni che non dovrebbero mai accadere nella vita reale. Devono essere senza effetti collaterali.
4. **Ogni chiamante controlla il valore restituito. Ogni funzione controlla i parametri che riceve.**
5. **Compilare con tutti gli avvisi attivi, e sistemarli tutti prima di rilasciare.**

La regola 3 è quella che mi cambia il lavoro. Non è un test: è una frase dentro il codice che dice *"a questo punto questo deve essere vero"*, e che fa esplodere il programma se non lo è. **Nel codice dei soldi, due per funzione.**

Holzmann le difende così: sembrano severe, ma sono come le cinture di sicurezza — all'inizio scomode, poi diventano naturali e non usarle diventa impensabile.

## 15.5 — Meta: i numeri sulla resa degli strumenti

Sono i numeri più concreti pubblicati da chiunque su quanto rendono gli strumenti automatici.

- Il loro analizzatore di sicurezza gira su **100 milioni di righe in meno di 30 minuti**, ha portato a migliaia di correzioni, e **batte qualunque altro metodo di rilevamento** che usano per quel tipo di falle.
- L'analizzatore generale elabora una modifica **in 15 minuti in media**, e gira su ogni modifica.
- Il loro sistema di prove automatiche ha **il 75% di segnalazioni utili** che finiscono in correzioni. Un tasso altissimo per uno strumento automatico.
- Per le corse fra processi paralleli il tasso di correzione scende al 50%: più basso, ma gli sviluppatori dicono di apprezzarlo lo stesso **perché quegli errori sono difficilissimi da trovare a mano**.

**Cosa prendo:** l'analisi statica non è un di più. È lo strumento con la resa più alta che esista, e quelli che ne hanno di più al mondo la fanno girare su ogni singola modifica.

## 15.6 — Netflix: l'ipotesi di stato stabile

Il contributo vero non è "rompere le cose a caso". È la struttura dell'esperimento:

1. **Definisci lo stato stabile**: una misura visibile dall'esterno che dice "sta funzionando". Per loro sono i flussi video al secondo. Per un negozio, gli acquisti completati al minuto.
2. **Fai l'ipotesi** che quella misura resti uguale anche mentre rompi qualcosa.
3. **Rompi** qualcosa di realistico.
4. **Guarda** se la misura ha tenuto.

E la pratica che quasi nessuno copia: **fanno l'analisi anche sui quasi-incidenti** — le cose che potevano fare danno e non l'hanno fatto, perché qualcosa le ha fermate o perché era notte.

**Per me:** il mio stato stabile è *prenotazioni completate senza intervento manuale*. E i miei 247 sono tutti quasi-incidenti. Vanno trattati come incidenti veri, perché è solo il caso — zero clienti — che li ha resi innocui.

## 15.7 — Sui cinque perché

Google, sull'analisi senza colpe: la catena dei perché, se la lasci andare da sola, **finisce sempre su una persona**. Qualcuno ha scelto una configurazione, qualcuno ha approvato, qualcuno non ha visto in revisione.

La regola: **la catena si ferma sui sistemi, non sulle persone.**

Quando lavoro da solo questa regola diventa vitale, perché la persona alla fine della catena sono sempre io. Se la risposta è "ho sbagliato io", non ho finito di scavare. La domanda successiva è: **cosa mi ha permesso di sbagliare, e che vincolo lo rende impossibile la prossima volta?**

## 15.8 — Il riassunto dei giganti, in sei righe

Tolti i nomi e le dimensioni, tutti fanno le stesse sei cose:

1. **Un anello chiuso dai guasti alla lista di controllo** (Amazon)
2. **Analisi statica su ogni modifica** (Meta, Google, Microsoft)
3. **Asserzioni dentro il codice**, non solo test fuori (NASA)
4. **Guasti simulati apposta**, non aspettati (Netflix, Google)
5. **Una lista obbligatoria prima del rilascio** (Amazon, Microsoft)
6. **Strumenti che non fanno rumore**, o vengono ignorati (Google, soglia del 10%)

**Cinque su sei le può fare una persona sola, oggi, gratis.** La sesta è una regola di disciplina.

Quello che non posso avere è la scala: migliaia di ingegneri, revisione indipendente, riunioni operative settimanali con il vertice dell'azienda. **Ma il metodo non è la scala. Il metodo è l'anello chiuso.**

---

# PARTE 16 — RENDERE IMPOSSIBILE

La famiglia più forte di tutte. Non trova il difetto: fa in modo che non si possa scrivere.

In fabbrica si chiama **poka-yoke**: il connettore che entra solo nel verso giusto.

**Un vincolo vale più di cento test.** Il test controlla dopo. Il vincolo impedisce prima.

## 16.1 — Macchina a stati esplicita

Serve dove una cosa passa per fasi: una prenotazione, un pagamento, un rimborso.

- [ ] Gli stati sono elencati in un posto solo
- [ ] Le transizioni permesse sono una tabella
- [ ] Tutto quello che non è in tabella non succede
- [ ] Nessun pezzo di codice cambia lo stato scrivendo direttamente

Il difetto che chiude: una prenotazione che finisce in uno stato che non doveva esistere, e nessuno sa come ci è arrivata.

## 16.2 — Vincoli veri nel database

- [ ] Chiavi uniche dove due cose non possono coesistere
- [ ] Controlli sui valori: niente importi negativi, niente date rovesciate
- [ ] Chiavi esterne vere
- [ ] Transazioni sulle operazioni che devono andare tutte o nessuna

## 16.3 — Tipi rigorosi e tetto alla complessità

- [ ] Controllo dei tipi attivo in modo severo su tutto
- [ ] Nessuna eccezione lasciata aperta "per dopo"
- [ ] Soglia massima di complessità per funzione, decisa e scritta
- [ ] Sopra la soglia il controllo diventa rosso e devo spezzare la funzione

**Perché il tetto conta:** il tasso di difetti creati riparando va dall'1% al 25% a seconda di quanto è complicato il codice. Non posso diventare esperto in tre mesi. **Posso tenere il codice semplice.** È l'unica leva che ho su quel numero.

## 16.4 — Limitare il danno

Non impedisce i difetti. Impedisce che mi rovinino. Per chi lavora da solo vale quanto tutto il resto, perché **non ho nessuno che mi copre alle tre di notte.**

- [ ] Ogni funzione nuova dietro un interruttore che posso spegnere in dieci secondi
- [ ] Rilascio graduale: prima a pochi, poi a tutti
- [ ] Ripristino del backup **provato davvero**, non solo fatto. Una volta al mese, cronometrato.
- [ ] Prova con guasto: ammazzo il sistema a metà di un'operazione e guardo cosa resta a metà
- [ ] So dire, senza pensarci, cosa faccio se stanotte salta tutto

---

# PARTE 17 — GLI STRUMENTI, CON I NOMI

Tutti gratis. Tutti su Windows. Tutti dentro la CI che ho già.

Girano su **ogni modifica**, non una volta ogni tanto. È questo che li rende utili.

| Cosa fa | Strumento | Nota |
|---|---|---|
| Errori e codice sporco | `ruff` | velocissimo, si mette in un minuto |
| Tipi | `mypy` oppure `pyright` | partire permissivo, stringere piano |
| Falle di sicurezza | `bandit` | pensato per Python |
| Regole mie, scritte a parole | `semgrep` | qui scrivo i miei controlli su misura |
| Funzioni mai chiamate | `vulture` | a blocchi, con la suite verde in mezzo |
| Tetto alla complessità | `radon` | dà il numero, poi decido la soglia |
| Chiavi finite nel codice | `gitleaks` | guarda anche la storia del repo |
| Librerie con falle note | `pip-audit` | |
| Proprietà, non casi | `hypothesis` | genera lui i casi e prova a rompere le regole |
| Pestaggio delle porte web | `schemathesis` | |
| Fuzzing | `atheris` | dove entrano dati da fuori |
| Mutation testing | `mutmut` oppure `cosmic-ray` | vedi PARTE 18.1 |
| Il modello matematico | `TLA+` | vedi PARTE 18.3 |
| Riconciliazione notturna | un lavoro pianificato + una mail | vedi PARTE 3.7 |

**La regola di Google sul rumore vale su tutti** (PARTE 15.2): uno strumento che suona a vuoto sopra il 10% delle volte viene ignorato. Se succede, lo aggiusto entro la settimana o lo spengo.

---

# PARTE 18 — I TRE STRATI SOPRA

Quello che esiste al mondo oltre a tutto il resto di questa guida. In ordine di resa per una persona sola.

## 18.1 — Mutation testing: chi controlla i controllori

**Il problema che risolve:** posso avere seimila test e non sapere se servono. Un test che resta verde anche quando il codice è rotto vale zero. E non c'è modo di accorgersene guardandolo.

**Come funziona:** lo strumento rompe apposta il mio codice, un pezzetto alla volta. Cambia un `+` in `-`, un `>` in `>=`, toglie una riga. Poi rilancia i test.

- Se i test diventano rossi → il mutante è morto. **Buono.**
- Se i test restano verdi → il mutante è **sopravvissuto**. Quel pezzo di codice non è coperto da niente.

**Il numero che ne esce** è la percentuale di mutanti uccisi. È la vera misura della forza dei miei test. La copertura dice quali righe sono state toccate; questo dice se qualcuno se ne sarebbe accorto.

- [ ] Girato almeno una volta su tutto
- [ ] Girato su **ogni modifica** del codice dei soldi
- [ ] Sui soldi punto a **zero mutanti sopravvissuti**. Altrove, al numero migliore che riesco.
- [ ] Ogni mutante sopravvissuto o diventa un test nuovo, o è codice da cancellare

**È lento.** Sulla suite intera può volerci molto. Si fa girare solo sui file che contano — i soldi — e di notte.

Questo è lo strato che manca a quasi tutti, ed è quello che dice se il resto della guida sta funzionando davvero.

## 18.2 — Simulazione deterministica

**Il problema che risolve:** i guasti che appaiono una volta su mille e non si riprendono più. Il fantasma.

Nasce dal fatto che ogni esecuzione è diversa: l'orologio, l'ordine in cui succedono le cose, il caso, la rete. Cambia uno di quelli e il guasto sparisce.

**L'idea:** si rendono finti tutti quelli. Orologio finto, caso comandato da un seme, ordine deciso dal simulatore. Poi si inietta apposta ogni guasto possibile: la connessione cade, il disco si riempie, la risposta arriva tardi, arriva due volte, non arriva.

Se qualcosa si rompe, **si rilancia lo stesso seme e si rompe di nuovo, identico.**

È nata in FoundationDB e in Amazon intorno al 2010. Oggi la usano TigerBeetle, RisingWave, CockroachDB.

**L'onestà:** funziona bene se il sistema è stato pensato così dall'inizio. Aggiungerla dopo a un sistema già in produzione è difficile, e chi la vende lo scrive.

**Cosa prendo io, oggi:** il seme ce l'ho già nella PARTE 9. Il passo successivo è finto orologio e guasti iniettati sul giro dei soldi. Non il simulatore completo.

- [ ] Orologio finto, così posso far passare 24 ore in un secondo
- [ ] Guasti iniettati sul giro dei soldi: connessione caduta, risposta doppia, risposta tardiva
- [ ] Ogni guasto trovato si riprende con il suo seme e diventa un test fisso

## 18.3 — Verifica matematica leggera

**Il problema che risolve:** i test provano i casi che mi vengono in mente. La verifica matematica prova **tutti i percorsi possibili**, compresi quelli a cui non ho pensato.

Non si verifica il codice: si scrive un **modello**, cioè il disegno del sistema in poche righe. Poi una macchina esplora tutte le combinazioni e stampa il percorso esatto che rompe la regola.

Amazon lo ha usato su un componente di S3 di 40.000 righe: ha fermato 16 problemi prima della produzione, ed è stato esteso da persone che non erano esperte. Si impara in 2-3 settimane.

**Dove serve a me:** il giro dei soldi con le sue fasi. Ospite paga → check-in → attesa → conferma o disputa → soldi all'host. Quello è il posto giusto, e nessun altro.

- [ ] Il giro dei soldi scritto come modello
- [ ] Le regole che non devono mai rompersi, scritte accanto
- [ ] Il modello girato, e il percorso che rompe stampato

**Attenzione a un limite vero:** il modello dimostra che il **disegno** è giusto. Non dimostra che il codice sia uguale al disegno. Sono due cose diverse. Vale lo stesso, perché gli errori di disegno sono quelli che i test non trovano mai.

## 18.4 — Il quinto strato, che non è uno strumento

**La revisione umana indipendente.** Chi ha scritto una cosa non vede il proprio errore. Non è questione di bravura, è come è fatta la testa.

**Questo si compra, non si automatizza.** Poche giornate, mirate solo dove entrano i soldi.

Nella PARTE 12 è l'unica riga che non posso spuntare da solo. È anche la più importante.

---

# PARTE 19 — QUELLO CHE NON È SOFTWARE

Il codice risponde alla domanda *"il sistema fa quello che ho detto?"*.
Non risponde alla domanda *"quello che ho detto è permesso?"*.

Sono due cose separate. Un sistema che funziona perfettamente può lo stesso portare una multa o una causa. Questa parte è quel buco.

**Avvertenza:** io non sono avvocato né commercialista. Queste righe non sono risposte. Sono le **domande da portare** a chi di dovere.

## 19.1 — Le carte

- [ ] Condizioni per l'**host**, lette da un avvocato
- [ ] Condizioni per l'**ospite**, lette da un avvocato
- [ ] Informativa privacy e trattamento dati
- [ ] Le stesse condizioni scritte nella fonte unica da cui legge il codice (PARTE 6.1)

## 19.2 — Il fisco e i soldi che passano da me

Le domande da fare al commercialista, per iscritto:

- [ ] Che cosa sono, fiscalmente, i soldi che tengo per conto di altri prima di girarli all'host?
- [ ] Che cosa sono le mie commissioni, e come si fatturano?
- [ ] Cambia qualcosa fra il 5% diretto e il 15% marketplace?
- [ ] Che documento va emesso, a chi, e quando?
- [ ] Il regime che ho oggi regge questa attività, o va cambiato?

- [ ] Ho la risposta **scritta**, non a voce

## 19.3 — Gli obblighi dell'annuncio

- [ ] Il codice identificativo dell'immobile è obbligatorio e il sistema lo pretende
- [ ] Se manca, l'annuncio non va online. Non è un avviso: è un blocco.
- [ ] So chi risponde se un host mette un dato falso: lui, io, o tutti e due

## 19.4 — La busta chiusa

**La domanda:** se io sparisco per due settimane, chi entra?

Il sistema è online, i soldi degli ospiti sono in mezzo, e tutto quello che serve è nella mia testa e sul mio computer.

- [ ] Dove stanno le chiavi e le password, scritto
- [ ] Come si spegne tutto, scritto in modo che lo capisca un altro
- [ ] Chi chiamare
- [ ] Il tutto **fuori dal mio computer**, in un posto che una persona di fiducia può raggiungere

## 19.5 — L'assicurazione

- [ ] Polizza di responsabilità civile professionale
- [ ] So cosa copre e cosa non copre

---

# CHIUSURA — IL BERSAGLIO

Non punto a "non sbaglia mai". Quello non esiste per nessuno, e questa guida lo dimostra parte per parte.

Punto a due cose, e sono raggiungibili tutte e due:

> **Uno.** Qualunque cosa sbagli, lo so entro 24 ore.
> **Due.** Ogni difetto che trovo chiude una famiglia intera, e quella famiglia non si riapre.

Il giorno in cui la PARTE 12 è tutta spuntata con misure vere, il lavoro non è perfetto. È **finito**. È una parola diversa, e vale di più.

---

*Versione 4 — ultimo aggiornamento: ___________*
