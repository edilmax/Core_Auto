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

> ## 📌 GLI OBBLIGHI SONO **100**, E SI DIVIDONO IN DUE FAMIGLIE DIVERSE
> **Contati dai file il 2026-08-01, non a memoria** (`python collaudi/regole_avvio.py` li
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
> ### 🧭 GLI ALTRI **56** — nati dai NOSTRI danni
> **IL BLOCCO (6 divieti assoluti, in cima a questo file)** · Regola zero (**5**) ·
> **20 direttive del fondatore** · modi di rompersi (**11**) ·
> collaudi (**10**) · direttiva finale (**4**). Non hanno uno studio dietro: hanno una
> **cicatrice**. Valgono uguale, e da oggi **portano anch'essi il «si verifica così»**.
>
> ### ⚠️ TRE VOLTE HO SBAGLIATO IL CONTO, E OGNI VOLTA ERA LO STESSO ERRORE
> **2026-07-31**: dissi «le 14» e violai la 15 — che quel giorno stava solo nell'appendice.
> **2026-08-01, mattina**: dissi 74, ma 61 punti stavano **solo nella memoria di sessione**,
> che **non viaggia col progetto**: su un altro computer, o in CI, non esistevano.
> **2026-08-01, sera**: mescolai le due famiglie in un unico numero — e mescolare fa perdere
> di vista proprio ciò che è stato pagato.
> **Rimedio definitivo:** le direttive del fondatore sono **entrate nel repository** (D1-D17
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

# 🧭 LE 20 DIRETTIVE DEL FONDATORE — nate dai NOSTRI danni, non da uno studio

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
leggibile** + `docker compose` v2 + verifica funzionale **nelle due direzioni**. *Si verifica:*
esistono il file `PRE_DEPLOY_*.commit`, l'immagine `:prec`, la prova di lettura del backup e le
sonde positive **e** negative dopo lo scambio.

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
