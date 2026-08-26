# B19 — LE DECISIONI CHE ASPETTANO IL FONDATORE

> **Referto di misura, non una lista di lavori** (REGOLA ZERO 3). Qui non c'è niente da fare:
> ci sono **domande**, le **risposte possibili**, e **quanto costa ognuna misurato adesso**.
> Quando una di queste domande ha una risposta, il lavoro che ne nasce si scrive in
> `RIPRENDI_QUI.md`, non qui.
>
> **Costruito il 2026-08-26 in SOLA LETTURA su `HEAD = 663eab3`** (albero di lavoro: tre
> `fase*.py` modificati da altre due sessioni — `fase57_vetrina.py`, `fase58_channel_manager.py`,
> `fase81_bootstrap_casavip.py` — **letti, mai toccati**; più `collaudi/audit/15_dipendenze_esterne.md`
> non tracciato, di un'altra sessione). Nessun `fase*.py` toccato, nessuna suite, nessun commit.
>
> ⛔ **Io non scelgo e non consiglio.** Dove una risposta mi sembrava ovvia, l'ho scritta come
> opzione insieme alle altre e ho messo accanto il numero, non l'opinione.
>
> ⛔ **Le percentuali non sono scritte per esteso di proposito.** `collaudi/audit_coerenza_tariffe.py`
> conta come «cifra nuova» ogni percentuale accanto a una parola di costo: scriverle qui manderebbe
> rossa la CI del prossimo giro. Le cifre vere stanno nei referti e nel codice, con `file:riga`.
>
> ⚠️ **Il nome del file.** `0_piano_riparazioni.md` aveva prenotato il numero 19 per un altro
> referto (`19_testi_a_runtime.md`, i testi composti a runtime). Questo file è **un'altra cosa** e
> non lo sostituisce: quel passaggio resta da fare e il suo file avrà il suo nome.

---

## Come si legge una scheda

Ogni decisione ha sempre gli stessi cinque campi, in quest'ordine:

1. **La domanda** — una riga sola, in italiano.
2. **Le opzioni** — due o tre, una riga ciascuna. Sono tutte legittime: se una fosse
   sbagliata non sarebbe una decisione, sarebbe una riparazione.
3. **Cosa cambia nel codice** — file e punti **contati oggi**, col comando che li ha contati.
   Dove non ho potuto contare, c'è scritto «non misurato» e il comando per misurarlo.
4. **Cosa è irreversibile** — cosa non si può più tornare indietro dopo aver scelto. Dove non
   c'è niente di irreversibile, è scritto.
5. **Cosa serve sapere** — l'informazione che oggi non abbiamo e che cambia la risposta.

**«Punto»** = una riga di codice o di testo che va cambiata. **«File»** = un file da aprire.
Un file aperto due volte conta come un file, ma ogni sua riga conta come un punto.

---

## Il quadro in una pagina

| # | La domanda, in una riga | Blocca | C'è qualcosa di irreversibile? |
|---|---|---|---|
| **D1** | Quale dei due motori di invito vive? | l'invito fra host | no |
| **D2** | In quanti al massimo si divide un conto? | il conto diviso | no |
| **D3** | La «classe fondatrice» esiste o si toglie dai testi? | 2 pagine pubbliche | sì, se qualcuno l'ha letta |
| **D4** | Quanto vale il Credito Fondatore promesso a chi lascia l'email? | la lista d'attesa | sì, i token già emessi |
| **D5** | La cauzione si accende o si toglie? | **un pagamento vero** | sì, i soldi trattenuti |
| **D6** | Il contratto host fuori Italia: legge, foro, lingue | il **secondo** paese | sì, le firme già raccolte |
| **D7** | Su «paga in struttura» vale la tariffa del contratto o quella del gateway? | **è acceso adesso** | sì, gli addebiti già fatti |
| **D8** | La tabella dei concorrenti: quale fonte è la buona? | il confronto pubblico | no |
| **D9** | I 63 moduli mai raggiunti: si accendono, si tolgono o restano? | un quarto del codice | sì, se si cancella |
| **D10** | «Host Verificato+» e i bonifici prioritari: si costruiscono o si tolgono? | il pannello host | no |
| **D11** | La schermata dei bonifici si costruisce o si cambiano i testi? | **un pagamento vero** | no |
| **D12** | «Alloggi certificati»: si costruisce la certificazione o si toglie la frase? | la homepage | no |
| **E1** | Sul rimborso pieno, chi paga il costo della carta? | il rimborso | sì, i rimborsi già fatti |
| **E2** | Il Credito Viaggio è al portatore o è di chi l'ha ricevuto? | il credito | sì, i token già in giro |
| **E3** | Cosa siamo, fiscalmente, quando incassiamo per l'host? | il commercialista | sì, le fatture già emesse |
| **E4** | Il cambio data serve o no? | niente oggi | no |
| **E5** | Esiste un tetto unico a quanto regaliamo su una prenotazione? | i regali sommati | no |
| **E6** | Le prenotazioni cancellate e non ancora rimborsate: si correggono nel giornale? | il giornale | sì, le scritture passate |
| **E7** | Il canale diretto segue la rampa di lancio o no? | il prezzo per l'host | sì, le prenotazioni già fatte |
| **E8** | I quattro moduli che l'artefatto spedito non raggiunge: quale delle tre uscite? | due moduli dei soldi | sì, se si cancella |
| **E9** | I quattro controlli inerti di `fase59`: si tolgono o restano? | il motore dei prezzi | no |

⚠️ **Quattro toccano soldi di qualcuno che sta già usando il prodotto**: **D5**, **D7**, **D11**
e **E2**. Le altre possono aspettare senza che nessuno ci perda un euro.

---

# PARTE 1 — LE DODICI DEL PIANO DELLE RIPARAZIONI

Sono le dodici di `collaudi/audit/0_piano_riparazioni.md`, sezione «LE DODICI CHE NON SONO
RIPARAZIONI». Qui ognuna ha, in più, **le opzioni e il costo misurato**.

---

## D1 — Quale dei due motori di invito vive?

**La domanda:** oggi esistono due meccanismi diversi per invitare un host, con premi diversi e
lo **stesso identico link**: quale dei due resta?

**Le opzioni:**
- **A — vive il motore vecchio** (`fase76_viral_loop`): quello che il pannello host usa già oggi.
- **B — vive il motore nuovo** (`fase109_referral_host`): quello con lo schedario su file e la
  rotta di qualifica, che **nessuna pagina chiama**.
- **C — vivono tutti e due**, ma con **due link diversi e distinguibili**.

**Cosa cambia nel codice (contato oggi su `663eab3`):**

| | motore A (`fase76`) | motore B (`fase109`) |
|---|---|---|
| righe del modulo | **313** | **118** |
| cablaggio | `fase81_bootstrap_casavip.py:356-361` | `fase81_bootstrap_casavip.py:504-506` |
| rotte nel server | **1** (`fase83_server.py:2041` → `:8759`) | **3** (`:2011`, `:2015`, `:2017` → `:8798`, `:8812`, `:8826`, ~43 righe) |
| chi lo chiama davvero | `deploy/host.html:852` | **nessuna pagina** (`grep "host/invito" deploy/` → 0) |
| il link che produce | `fase83_server.py:8778` | `fase83_server.py:8809` — **identico** |
| file di test che lo nominano | **6** | **2** |

- **Opzione A** → si tolgono **3 file** di prodotto (`fase81`, `fase83`, `fase109`) e **2 file di
  test**: 3 righe di cablaggio + 3 righe di dispatch + 3 gestori (~43 righe) + 118 righe di modulo.
- **Opzione B** → si toccano **4 file** di prodotto: il consumo alla registrazione
  (`fase83_server.py:8709-8720`, oggi riconosce **solo** i codici di A), `deploy/host.html:852`,
  il cablaggio di A (`fase81:356-361`) e i due punti del server che qualificano e scalano
  (`fase83_server.py:8274-8320` e `:8322-8340`). **6 file di test** da rileggere.
- **Opzione C** → **non misurabile finché non si dice come si distinguono i due codici**: oggi
  i due link sono la stessa stringa prodotta in due punti, e nessun formato li separa.

*Comando: `grep -rn "fase109\|referral_host" --include=*.py --include=*.html . | grep -v "^./test_"`
e `grep -n "host/referral\|host/invito\|codice_referral" fase83_server.py`.*

**Cosa è irreversibile:** **niente**, oggi. Nessun invito è mai stato pagato in produzione
(vedi PARTE 4, il comando che lo verifica).

**Cosa serve sapere:** **quanto vogliamo pagare chi porta un host, e a quale evento.** I due
motori non discordano su un dettaglio tecnico: discordano su **quando** scatta il premio (alla
prima prenotazione o alla terza) e su **quanto vale**. È una scelta di marketing, e finché non è
presa il codice non può che avere due risposte.

---

## D2 — In quanti al massimo si divide un conto?

**La domanda:** l'anteprima del conto diviso accetta mille partecipanti e la creazione ne
rifiuta più di cinquanta: quale dei due numeri è quello giusto?

**Le opzioni:**
- **A — vale il numero basso** (`fase65_split_payment.py:45`, `MAX_PARTECIPANTI = 50`): l'anteprima
  si abbassa e smette di promettere un conto che non si può creare.
- **B — vale il numero alto** (`fase133_split_quote_uguali.py:32`, `MAX_PARTECIPANTI = 1000`): la
  creazione si alza.
- **C — restano due numeri diversi**, ma l'anteprima **dice** che sopra il tetto della creazione
  il conto non si potrà completare.

**Cosa cambia nel codice (contato oggi):**
- **Opzione A** → **1 file, 1 punto**: `fase133_split_quote_uguali.py:32`. Il tetto è già usato
  in un punto solo dentro il modulo (`:45`), e il modulo è 163 righe.
- **Opzione B** → **1 file, 2 punti**: `fase65_split_payment.py:45` e il controllo che lo applica
  a `:141`. ⚠️ Alzare qui significa accettare **mille righe di partecipanti** in una transazione:
  il commento di `fase133:16` dichiara che il tetto alto esiste per **non** doverne fare mille.
- **Opzione C** → **2 file, 2 punti**: il testo dell'anteprima in `deploy/index.html:668` (unica
  pagina che chiama `/api/split/preview`) più la risposta del server.

*Comando: `grep -n "MAX_PARTECIPANTI" fase133_split_quote_uguali.py fase65_split_payment.py` ·
`grep -rn "split/preview\|split/crea" deploy/`.*

**Cosa è irreversibile:** niente. È un numero, e nessun conto diviso è mai stato creato in
produzione (vedi PARTE 4).

**Cosa serve sapere:** **quanti sono davvero, al massimo, quelli che dividono un soggiorno.**
Nessuno l'ha mai misurato perché non è mai successo. Il commento nel codice dice «un gruppo vero
sta in decine»: è un'ipotesi scritta da noi, non un dato.

---

## D3 — La «classe fondatrice» esiste o si toglie dai testi?

**La domanda:** due pagine pubbliche promettono una «classe fondatrice» con tariffa bloccata, e
**nessuna riga di codice la applica**: si costruisce o si toglie la frase?

**Le opzioni:**
- **A — si costruisce**: il primo blocco di host paga sempre la stessa tariffa, per sempre.
- **B — si toglie la frase** dalle pagine e dai due canali di reclutamento.
- **C — si riscrive la frase** in modo che dica quello che il codice fa già (la rampa di lancio,
  che è **temporale**, non ordinale).

**Cosa cambia nel codice (contato oggi):**
- **La promessa vive in 4 file, 28 occorrenze**: `deploy/diventa-host.html`,
  `deploy/kit-marketing.html`, `fase200_campagna_persuasiva.py`, `fase89_jurisdiction_outreach.py`
  (`grep -rio "classe fondatrice\|founding" deploy/ fase*.py | wc -l` → **28**).
- **Il codice che la applicherebbe esiste e non lo chiama nessuno**: `fase98_policy_commissione.py:149`
  (`e_fondatore`) ha **zero chiamanti di produzione** — compare solo in `test_fase98_policy_commissione.py`
  (6 righe). La soglia accanto, `SOGLIA_FONDATORI` a `fase98:31`, si dichiara da sé **«(legacy)»**
  e dice che «la strategia ora è a rampa temporale».
- **Opzione A** → **almeno 3 file**: la funzione esiste già, ma va **collegata** a chi decide la
  commissione (`fase98:60` `commissione_bps_fonte`, cablata in `fase81_bootstrap_casavip.py:274`),
  e va deciso cosa succede all'host numero 1001. **Punti non misurabili** finché non si dice
  *cosa* resta bloccato (la commissione, la tariffa tecnica, o tutte e due).
- **Opzione B** → **4 file, 28 punti**, in 8 lingue dove le pagine sono tradotte.
- **Opzione C** → gli stessi 4 file e 28 punti di B, con testo diverso.

**Cosa è irreversibile:** **sì, se qualcuno l'ha già letta.** La frase è online in questo momento
su pagine indicizzabili. Chi si è registrato leggendola può sostenere di aver accettato quella
promessa. Oggi il numero di host firmati è **0** secondo `RIPRENDI_QUI.md` (non rimisurato qui:
comando in PARTE 4): se è ancora 0, togliere non costa niente.

**Cosa serve sapere:** **se «classe fondatrice» è una promessa o uno slogan.** Se è una promessa,
va scritta anche nel contratto (che oggi non la nomina: `grep -i fondatric fase163_accettazioni.py`
→ 0); se è uno slogan, non può stare accanto a una tariffa.

---

## D4 — Quanto vale il Credito Fondatore promesso a chi lascia l'email?

**La domanda:** a chi lascia l'email nella lista d'attesa promettiamo un «Credito Fondatore di
benvenuto»: quanto vale davvero, e cosa gli diciamo?

**Le opzioni:**
- **A — si dice il vero**: il credito vale al massimo quanto la nostra commissione può assorbire,
  e su un host in promozione **vale zero**. Si scrive nel testo.
- **B — si garantisce il valore**: il credito vale sempre la cifra promessa, e la differenza la
  paghiamo noi anche quando la commissione è zero.
- **C — non si conia** quando non può valere niente, e non si promette.

**Cosa cambia nel codice (contato oggi):**
- **La promessa vive in 2 chiavi del dizionario del server, in 8 lingue ciascuna**:
  `fase83_server.py:187` (`empty_lascia`) e `fase83_server.py:241` (`wl_msg_tpl`) — **8 lingue
  contate riga per riga**, non a memoria.
- **Il credito si conia** a `fase158_domanda.py:154-163`, valore `CREDITO_FONDATORE_CENTS`
  a `fase158_domanda.py:22`; le due rotte che lo emettono sono `fase83_server.py:7203` e `:7309`.
- **Il pavimento che lo annulla** è a `fase59_concierge.py:501-504`: il credito viene tagliato a
  `margine_disponibile = max(0, commissione − costo)`. Con la commissione a zero, il margine è
  zero. **Un lettore solo, un punto solo.**
- **Opzione A** → **1 file, 2 punti** (le due chiavi), per **8 lingue** = **16 punti di testo**.
- **Opzione B** → **1 file, 1 punto** (`fase59_concierge.py:503`), ⛔ ma **rompe la regola «mai in
  perdita»**: pagheremmo il credito avendo incassato zero di commissione. È una decisione
  commerciale, non una riparazione.
- **Opzione C** → **1 file, 1 punto** (`fase158_domanda.py:154`), ⚠️ **ma non è calcolabile**: al
  momento in cui si conia non si sa su quale host verrà speso, e il valore dipende da quello.

**Cosa è irreversibile:** **sì, i token già emessi.** La rotta che conia è **pubblica e senza
autenticazione** (`fase83_server.py:7195` area, `POST /api/domanda`) e ogni chiamata produce un
token firmato nuovo. I token già in giro durano quanto la loro scadenza e non si possono
richiamare uno per uno. Quanti ne siano stati emessi in produzione **non l'ho misurato**: comando
in PARTE 4.

**Cosa serve sapere:** **se la lista d'attesa serve ancora.** Se la si spegne, la domanda decade;
se resta accesa, ogni email nuova aggiunge un token con lo stesso difetto.

---

## D5 — La cauzione si accende o si toglie?

**La domanda:** il deposito cauzionale è costruito, collegato all'avvio, e **nessuno lo chiama**:
si accende o si toglie?

**Le opzioni:**
- **A — si accende**: si aggancia al giro della prenotazione e si collegano davvero il blocco e
  lo sblocco sulla carta.
- **B — si toglie** il modulo e il suo cablaggio.
- **C — resta spento**, dichiarato come spento, e si scrive come si accende.

**Cosa cambia nel codice (contato oggi):**
- Il modulo è **183 righe, 16 funzioni** (`fase149_deposito_cauzionale.py`), ed è **collegato
  all'avvio**: `fase81_bootstrap_casavip.py:379-386` lo costruisce e mette
  `deposito_cauzionale(149)` nel rendiconto dei componenti.
- **Il server non lo nomina mai**: `grep -ic cauzion fase83_server.py` → **0**. Idem
  `deploy/host.html`, `deploy/index.html`, `deploy/admin.html` → **0, 0, 0**.
- 🔴 **E c'è un fatto misurato che cambia la domanda:** il modulo viene costruito **senza i due
  agganci al gestore dei pagamenti** — `fase81_bootstrap_casavip.py:384` chiama
  `crea_deposito_cauzionale(cfg.db_deposito)`, quindi `capture=None` e `release=None`
  (`fase149:176-183`). Conseguenza letta nel codice: `autorizza()` (`fase149:71-87`) **scrive solo
  una riga nel database e non chiede niente alla carta**, e `rilascia()` (`fase149:131-145`)
  **scrive `stato='rilasciato'` e risponde «fatto» anche con `release` assente**.
- **Opzione A** → **almeno 3 file**: `fase149` (i due agganci), `fase101_stripe_connect.py` o
  `fase85_pagamenti_stripe.py` (chi sa parlare con la carta: oggi **nessuna delle due espone un
  blocco/sblocco**, `grep -n "capture\|hold" fase85_pagamenti_stripe.py fase101_stripe_connect.py`
  → 0 righe di blocco carta), e `fase83_server.py` (il punto della prenotazione). **Punti non
  misurabili**: il pezzo che manca non esiste ancora, quindi non si può contarlo.
- **Opzione B** → **2 file, 8 punti**: 183 righe di modulo + 8 righe di cablaggio in `fase81`
  (`:86`, `:379-386`).
- **Opzione C** → **1 file, 1 riga** nel registro d'ingegneria + il testo che dice che è spento.
  ⚠️ Ma resta il fatto che oggi **è costruito, acceso all'avvio e capace di dire «rilasciato»**
  a chi glielo chiede.

**Cosa è irreversibile:** **sì, se si accende.** Un blocco sulla carta di un ospite è denaro suo
tenuto fermo. Se lo blocchiamo e lo sblocco non funziona, i soldi restano fermi e lo scopre lui.

**Cosa serve sapere:** **se gli host vogliono la cauzione.** Non l'ha mai chiesta nessuno, perché
non c'è nessun host. E: **il nostro conto sa fare un blocco su carta e tenerlo per giorni?** Non
misurato: è una domanda al gestore dei pagamenti, non al codice.

---

## D6 — Il contratto host fuori Italia: legge, foro, lingue

**La domanda:** il contratto host esiste in due lingue, con legge italiana e foro della nostra
sede, e cita istituzioni italiane: cosa firma un host che non è in Italia?

**Le opzioni:**
- **A — un contratto solo, italiano, per tutti**: si traduce nelle altre lingue ma restano legge
  e foro italiani.
- **B — un contratto per paese**: legge, foro e riferimenti locali cambiano col paese dell'host.
- **C — si recluta un paese alla volta**, e il contratto di quel paese si scrive quando quel
  paese si apre.

**Cosa cambia nel codice (contato oggi):**
- Il contratto è in `fase163_accettazioni.py` (**674 righe**), **2 lingue** (`CONTRATTO_HOST` a
  `:280-283`: solo `it` e `en`), **32 articoli**, versione `2026-08-10` (`:30`).
- **Dimensione misurata del testo**: italiano **1.364 parole / 135 righe**; inglese **1.185
  parole / 108 righe** (contate leggendo i due blocchi di testo del file).
- **Legge e foro** stanno in **2 punti**: ART. 14 italiano (`:155-157`) e inglese (`:267-269`),
  tutti e due «legge italiana · foro della nostra sede».
- **Riferimenti solo italiani dentro il contratto**: `CIN` **2 righe**, `SCIA` **2**, `cedolare`
  **1**, `artt. 1341-1342` **3**.
- **Il resto dei testi legali parla già 8 lingue**: `fase185_testi_legali.py:35`
  (`LINGUE = ("it","en","es","fr","de","pt","ja","zh")`). **Il contratto è l'unico rimasto a due.**
- **Opzione A** → **1 file**, e **circa 8.200 parole di traduzione legale** (1.364 × 6 lingue
  mancanti), più il meccanismo che sceglie la lingua. Nessuna logica nuova.
- **Opzione B** → **1 file** più una tabella per paese che **oggi non esiste**: `grep` per una
  tabella paese→legge nei moduli dei soldi → **nessuna**; l'unica tabella per nazione è del
  marketing (`fase154_giurisdizioni_marketing.py`, che ha **zero chiamanti**). **Punti non
  misurabili**: dipende da quanti paesi.
- **Opzione C** → **0 punti oggi**. È la strada già scelta il 2026-08-24 («aprire un paese alla
  volta»), e questa domanda ne è il seguito: **quale paese, e quando.**

**Cosa è irreversibile:** **sì, le firme già raccolte.** Cambiare il testo alza la versione, cambia
l'impronta del documento, e **tutti gli host che avevano firmato devono ri-accettare**. Oggi, se
il numero di host firmati è 0, costa zero: comando per verificarlo in PARTE 4.

**Cosa serve sapere:** **quale paese apriamo per secondo.** Il costo di B dipende interamente da
quello, e nessuna delle due opzioni si può dimensionare senza. E: **cosa dice un avvocato** su un
foro italiano imposto a un host straniero (`METODO_v4.md` PARTE 19.1: le condizioni le legge un
avvocato, non una macchina).

---

## D7 — Su «paga in struttura» vale la tariffa del contratto o quella del gateway?

**La domanda:** l'host che accetta «paga in struttura» paga una copertura carta che **il contratto
che ha firmato non prevede**: quale delle due cifre vale?

⛔ **È la più urgente delle dodici, e non per gravità: perché è ACCESA.** Il passaggio 16 ha
misurato che in produzione `PAGA_STRUTTURA_ATTIVO` vale `1`. Ogni ospite che sceglie «paga in
struttura» oggi passa da qui.

**Le opzioni:**
- **A — vale il contratto**: il gateway smette di usare la sua cifra e usa quella della fonte unica.
- **B — vale il gateway**: il contratto si aggiorna e dichiara la copertura carta di questo caso.
- **C — si spegne «paga in struttura»** finché non si decide.

**Cosa cambia nel codice (contato oggi):**
- Il modulo è `fase188_paga_struttura.py` (**137 righe**). Le sue costanti stanno in **5 righe**:
  `:37` (quota a notte all'ospite), `:41`, `:42`, `:43`, `:51` (la copertura carta che assorbe
  l'host).
- **Il ripiego che nessuno passa**: `calcola()` ha `psp_bps` con un valore di serie a
  `fase188:64`, riletto a `:87`. **I due punti che la chiamano non glielo passano mai** —
  `fase83_server.py:5348-5350` e `fase83_server.py:7543-7546`: verificato aprendo le due righe.
  Quindi vale il valore di serie, non la fonte unica di `main_casavip.py:150-152`.
- **La garanzia che si disattiva da sola**: `_gw()` a `fase188:95-100` sceglie il massimo fra
  copertura Stripe e tariffa tecnica; con il valore di serie il secondo ramo **non scatta mai**.
- **Il contratto dice un'altra cifra**: ART. 6-BIS, `fase163_accettazioni.py:88` (italiano) e
  `:216` (inglese).
- **Opzione A** → **2 file, 4 punti**: i due punti di chiamata in `fase83_server.py` passano il
  valore della fonte unica, e i due ripieghi di `fase188` (`:64`, `:87`) spariscono.
- **Opzione B** → **2 file**: `fase163_accettazioni.py` (**2 lingue**) e `fase185_testi_legali.py`
  (**8 lingue**), più la versione del contratto alzata a `fase163:30` e la **ri-accettazione di
  tutti gli host**.
- **Opzione C** → **0 file**: una variabile d'ambiente sul VPS (`PAGA_STRUTTURA_ATTIVO=0`) e il
  riavvio del contenitore. ⚠️ Nessun codice cambia, quindi **nessuna suite** — ma è produzione.

**Cosa è irreversibile:** **sì, gli addebiti già fatti.** Ogni anticipo già incassato con la cifra
del gateway è un addebito che il contratto non prevedeva. Quanti siano **non l'ho misurato**:
comando in PARTE 4.

**Cosa serve sapere:** **se qualcuno ha già usato «paga in struttura» in produzione.** Se sono
zero, tutte e tre le opzioni costano uguale e la scelta è libera; se non sono zero, l'opzione B
diventa una sanatoria e va guardata da un avvocato.

---

## D8 — La tabella dei concorrenti: quale fonte è la buona?

**La domanda:** il motore che mostra il confronto all'host e la pagina pubblica danno numeri
diversi per le stesse aziende: quale delle due fonti vale?

> ⚠️ **Attenzione: questa domanda ha già una risposta parziale, del 2026-08-24.** Il fondatore ha
> deciso **«togliere tutti i nomi dei concorrenti e mettere "i grandi portali"»** (scritto in
> `RIPRENDI_QUI.md`, sezione B16). Se quella decisione vale ancora, **D8 decade**: senza nomi non
> c'è più niente da far coincidere. Resta però una cosa che quella decisione **non nominava**, ed
> è misurata qui sotto.

**Le opzioni:**
- **A — si applica la decisione del 24/08 anche al motore**: via i nomi da tutto, testi e codice.
- **B — vale il motore** (`fase69_trasparenza.py:43-49`) e la pagina si allinea a lui.
- **C — vale la pagina** e il motore si allinea a lei.

**Cosa cambia nel codice (contato oggi, nome per nome e riga per riga):**

| file | righe con un nome di concorrente | di cui **comparative** (portano una cifra o una parola di costo) |
|---|---|---|
| `deploy/commissioni.html` | 17 | **17** |
| `deploy/kit-marketing.html` | 11 | **11** |
| `deploy/diventa-host.html` | 9 | **8** |
| `deploy/host.html` | 15 | **9** |
| `deploy/index.html` | 2 | **0** |
| `fase89_jurisdiction_outreach.py` | 8 | **8** |
| **totale** | **62** | **53** |

🔑 **E qui c'è il fatto che la decisione del 24/08 non nominava: 9 righe su 62 NON sono
comparative, sono funzionali.** In `deploy/host.html` i nomi compaiono anche dove servono a far
funzionare una cosa — l'importazione degli annunci (`:331`, `:335`, dove `<option value="booking">`
è un **valore che il codice legge**) e il calendario condiviso (`:445`, `:454`). Toglierli lì
**rompe una funzione**; lasciarli lì è coerente con la decisione, perché non è un confronto di
prezzi. **La decisione va detta su 53 righe, non su 62.**

- **Opzione A** → **6 file, 53 punti** (le comparative), in 8 lingue dove le pagine sono tradotte.
  ⛔ Le 9 funzionali si lasciano, e va detto esplicitamente.
- **Opzione B** → **5 file** di pagine, **53 punti** di testo, e i numeri li detta
  `fase69_trasparenza.py:43-49` (**5 aziende**).
- **Opzione C** → **1 file, 5 punti** (`fase69_trasparenza.py:44-48`), ⚠️ ma la pagina non cita
  **nessuna fonte** (`deploy/commissioni.html:66` dice «Fonti: pagine ufficiali e portali di
  settore» senza nominarne una).

**Cosa è irreversibile:** niente nel codice. Fuori dal codice: una pagina indicizzata resta nella
memoria dei motori di ricerca per un po', anche dopo la modifica.

**Cosa serve sapere:** **se vogliamo continuare a confrontarci per nome.** Un confronto di prezzi
con aziende nominate, su pagine pubbliche, in 8 lingue e **senza una fonte citata**, è una
questione legale prima che tecnica.

---

## D9 — I moduli mai raggiunti: si accendono, si tolgono o restano?

**La domanda:** un quarto del codice di produzione non è raggiungibile da ciò che la macchina
avvia: si accende, si toglie, o si dichiara spento?

**Le opzioni** (sono le tre uscite della DO-178C, e non ce ne sono altre):
- **A — serve e si collauda**: si collega e si sorveglia.
- **B — è spento e si dice come si accende**: resta dov'è, con una riga che lo dichiara.
- **C — è codice estraneo e si toglie**: sparisce dal repository.

⛔ **Non è una risposta sola per tutti: sono 63 risposte.** Un modulo alla volta.

**Cosa cambia nel codice (misurato adesso, non ricordato):**

```
python collaudi/raggiungibilita.py      (partenza: main_casavip.py)
  moduli fase*.py sul disco ............ 151
  RAGGIUNGIBILI dalla produzione ....... 88
  NON raggiungibili .................... 63
```

- **Dimensione dei 63**: **12.609 righe**, **192 funzioni di modulo**, **624 metodi di classe**,
  **209 classi**. Sul totale dei `fase*.py` (**50.696 righe**) sono il **24,9 per cento**.
  *(Contate con `wc -l`, `grep -cE "^def "`, `grep -cE "^    def "`, `grep -cE "^class "`.)*
- **Massa di collaudo appesa a quei moduli**: **82 file di test su 406** ne nominano almeno uno
  (151 coppie modulo × file di test). Scegliere **C** su un modulo significa guardare anche i suoi
  test.
- ⚠️ **Il numero è 63, non 59.** Il referto del passaggio 4 (2026-08-24) diceva **59 moduli /
  12.055 righe / 651 funzioni**. La differenza non è un errore di nessuno dei due: **si conta a
  partire da ingressi diversi**. Oggi `collaudi/raggiungibilita.py:79` dichiara
  `INGRESSI = ("main_casavip.py",)`, cioè esattamente ciò che l'immagine avvia
  (`Dockerfile.casavip:42`). **Il numero da usare per decidere è quello prodotto adesso, non
  quello ricopiato** — ed è il motivo per cui questo campo porta il comando accanto.
- **Opzione A** → non misurabile in blocco: dipende da quale modulo.
- **Opzione B** → **1 riga per modulo** in `REGISTRO_INGEGNERIA.md`. Costo del codice: **zero**.
- **Opzione C** → **12.609 righe** in gioco, a lotti. Il piano delle riparazioni le conta come
  **3 giri di suite** (D4, D5, D6 di quel piano).

**Cosa è irreversibile:** **sì, se si sceglie C.** Un modulo cancellato torna solo dalla storia di
git, e con lui torna il motivo per cui era stato scritto — che di solito non è scritto da nessuna
parte. ⛔ La regola già scritta: *«non si cancella niente prima di aver dimostrato che nulla di
vivo lo usa»* (`collaudi/piano.py`, blocco 10).

**Cosa serve sapere:** **quali di quei 63 erano un obbligo e non una scelta.** Dentro l'elenco ci
sono `fase103_reverse_charge`, `fase151_alloggiati_web`, `fase15_idempotency`, `fase17_money`:
i primi due sono adempimenti, gli ultimi due muovono denaro. Per quelli la domanda non è «serve?»
ma «**da quando doveva essere acceso?**» — ed è la stessa domanda di **E8**.

---

## D10 — «Host Verificato+» e i bonifici prioritari: si costruiscono o si tolgono?

**La domanda:** al momento di chiedere all'host un dato di pagamento gli offriamo un badge e dei
bonifici prioritari che **non esistono**: si costruiscono o si toglie la frase?

**Le opzioni:**
- **A — si costruiscono tutti e due.**
- **B — si toglie la frase** e si chiede il dato dicendo a cosa serve davvero.
- **C — si costruisce solo il badge** (che è una etichetta) e si toglie la promessa sui bonifici
  (che è un ordine di pagamento).

**Cosa cambia nel codice (contato oggi):**
- **La promessa vive in 3 file, 7 occorrenze** per il badge (`grep -rnoF "Verificato+"` →
  `deploy/host.html`, `fase183_carta_offsession.py`, `fase83_server.py`) e **3 occorrenze** per i
  bonifici prioritari (`deploy/host.html`, `fase183_carta_offsession.py`).
- **Il badge esiste solo dentro il pannello dell'host stesso**: nessun altro lo vede — quindi oggi
  non è un segnale per l'ospite, è un'etichetta che l'host mostra a se stesso.
- **I bonifici escono in ordine di data**, non di priorità: `fase131_payout_dashboard.py`, ordine
  `ORDER BY ts` (misurato dal passaggio 9).
- **Opzione A** → **almeno 2 file** e un criterio di priorità che **oggi non esiste**: punti non
  misurabili finché non si dice **chi passa avanti e perché**.
- **Opzione B** → **3 file, 10 punti**, in 8 lingue dove il pannello è tradotto.
- **Opzione C** → **2 file** per togliere la parte sui bonifici (**3 punti**), zero per il badge.

**Cosa è irreversibile:** niente.

**Cosa serve sapere:** **cosa vogliamo davvero in cambio di quel dato.** La frase esiste perché
serviva una ragione per chiederlo: se la ragione vera è un'altra (conformità fiscale), si può
dire quella, e allora non serve costruire niente.

---

## D11 — La schermata dei bonifici si costruisce o si cambiano i testi?

**La domanda:** tre testi in 8 lingue mandano il fondatore a una «dashboard payout» per pagare
gli host a mano, e quella schermata non esiste: si costruisce o si cambiano i testi?

⛔ **È una delle due che bloccano un pagamento vero.** Il gesto che fa uscire i soldi verso l'host
non ha né schermo né porta.

**Le opzioni:**
- **A — si costruisce la schermata**: una pagina e una porta che elenchino chi è in attesa.
- **B — si cambiano i tre testi** e si dice come si paga davvero (a mano, fuori dal prodotto).
- **C — si costruisce solo la porta** (senza pagina), e si usa dalla riga di comando.

**Cosa cambia nel codice (contato oggi):**
- **Il metodo che risponderebbe esiste e nessuno lo chiama**: `fase131_payout_dashboard.py:332`
  `da_pagare(host_id, valuta)` — cercato in tutto il progetto: **zero chiamanti di produzione**
  (compare in 12 file di test e in 6 commenti, mai in una riga eseguita del prodotto).
- **Le rotte che parlano di bonifici sono UNA**: `fase83_server.py:2067`, `GET /api/host/payout`,
  che serve **all'host** per vedere i propri. Nessuna rotta per il fondatore.
- **I testi che promettono la schermata**: **3 file, 14 occorrenze** (`deploy/bunker.html`,
  `deploy/guida-operativa.html`, `deploy/host.html`).
- **Opzione A** → **3 file, 3 punti nuovi** (una rotta nel server, una scheda in `deploy/bunker.html`,
  la chiamata) più i **14 punti** di testo da rendere veri. Il calcolo **c'è già**.
- **Opzione B** → **3 file, 14 punti**, in 8 lingue.
- **Opzione C** → **1 file, 2 punti** (dispatch + gestore in `fase83_server.py`), e i 14 testi
  restano falsi finché non si toccano.

**Cosa è irreversibile:** niente nel codice. Fuori dal codice: un host che aspetta un bonifico e
non lo riceve se ne accorge da solo.

**Cosa serve sapere:** **come paghiamo gli host che non hanno collegato il gestore dei pagamenti.**
Oggi quel caso ritorna in silenzio (`fase83_server.py:6191-6192`, difetto B17) e non lascia
traccia. Finché non si decide **chi** fa quel bonifico e **con cosa**, non si può sapere se serve
una schermata o basta un elenco.

---

## D12 — «Alloggi certificati»: si costruisce la certificazione o si toglie la frase?

**La domanda:** la prima riga della homepage promette alloggi certificati, e nessuna
certificazione esiste: si costruisce o si toglie?

**Le opzioni:**
- **A — si costruisce una certificazione vera**: un controllo, un criterio, un elenco di chi
  l'ha passato.
- **B — si toglie la parola.**
- **C — si sostituisce** con qualcosa che il codice fa già (per esempio la verifica dell'identità
  dell'host, che esiste).

**Cosa cambia nel codice (contato oggi):**
- **La frase vive in 2 punti**, ed è la stessa: `fase83_server.py:168` (chiave `hero_sub`,
  **8 lingue contate riga per riga**) e `deploy/index.html:170` (la versione statica italiana).
  Più una terza comparsa nella descrizione per gli assistenti automatici, `fase83_server.py:814`.
- ⚠️ **La stessa riga porta altre due promesse**: «paghi il prezzo pulito» e «cancellazione
  gratuita». La seconda è anch'essa segnata dal passaggio 2 come promessa senza codice.
  **Chi apre quella riga le tocca tutte e tre.**
- **Opzione A** → **non misurabile**: non esiste nessun modulo di certificazione
  (`grep -ril "certificazione alloggi"` → 0). Va inventato il criterio prima del codice.
- **Opzione B** → **2 file, 9 punti** (8 lingue + la riga statica), più 1 punto a `:814`.
- **Opzione C** → gli stessi 2 file e 9 punti, con parole diverse.

**Cosa è irreversibile:** niente.

**Cosa serve sapere:** **cosa intendevamo per «certificati».** Se era «abbiamo verificato chi è
l'host», quella cosa esiste e basta chiamarla col suo nome; se era «abbiamo visto la casa», non
esiste e non esisterà presto.

---

# PARTE 2 — LE ALTRE DECISIONI APERTE, TROVATE FUORI DALLE DODICI

Ognuna di queste è **segnata da qualche parte come «decide il fondatore»**, con la data e il
posto dove sta scritto. Non le ho inventate io.

---

## E1 — Sul rimborso pieno, chi paga il costo della carta?

*(`RIPRENDI_QUI.md`, voce B4. `METODO_v4.md` PARTE 3.8 le chiama A, B, C e dice che vanno scritte
nelle condizioni.)*

**La domanda:** quando rimborsiamo tutto all'ospite, il costo che il gestore dei pagamenti non ci
restituisce lo paghiamo noi, l'host, o lo tratteniamo?

**Le opzioni:**
- **A — lo paghiamo noi**: l'ospite riceve tutto, la perdita è nostra. È quello che il codice fa
  oggi.
- **B — lo tratteniamo** e lo dichiariamo nelle condizioni prima che l'ospite prenoti.
- **C — lo paghiamo noi dentro la finestra di ripensamento e lo tratteniamo fuori.**

**Cosa cambia nel codice (contato oggi):**
- `fase111_cancellazione.py` è **84 righe**; la funzione è `calcola_rimborso` a `:39`, e ha **un
  solo chiamante di produzione**: `fase83_server.py:6742-6743`.
- **Opzione A** → **0 punti**: è già così.
- **Opzione B** → **1 file, 1 funzione**, più il testo nelle condizioni: `fase163_accettazioni.py`
  (2 lingue) e `fase185_testi_legali.py` (8 lingue).
- **Opzione C** → **1 file, 1 funzione** (il parametro `entro_ripensamento` **esiste già**:
  `grep -n entro_ripensamento fase111_cancellazione.py`), più gli stessi testi di B.

**Cosa è irreversibile:** i rimborsi già fatti restano come sono. Ne risulta **uno** in
produzione (1 euro, 2026-08-16).

**Cosa serve sapere:** **quanto ci costerà davvero.** Oggi non c'è nessun volume: la cifra per
rimborso si sa (è il costo del gestore), il numero di rimborsi al mese no.
⛔ **E un vincolo che non è una scelta:** dentro la finestra di ripensamento il rimborso pieno
copre un obbligo di legge e **non si tocca** (già deciso, `bookinvip-ripensamento-48-ore`).

---

## E2 — Il Credito Viaggio è al portatore o è di chi l'ha ricevuto?

*(`RIPRENDI_QUI.md`, voce B10: «decisione del fondatore, non tecnica».)*

**La domanda:** chi ha in mano il codice del credito lo spende, chiunque sia: è una scelta
commerciale («regalalo a un amico») o un buco?

**Le opzioni:**
- **A — è al portatore, e lo diciamo**: si scrive nelle regole che il credito si può girare.
- **B — è della persona**: chi lo riscatta deve essere chi l'ha ricevuto.
- **C — è al portatore ma con un tetto** di quante volte si può girare.

**Cosa cambia nel codice (contato oggi, ed è più piccolo di quanto sembra):**
- **Chi legge il credito è UNO SOLO**: `fase59_concierge.py:460-504`. Controlla firma, tipo,
  scadenza, uso singolo, valuta e margine. **L'email non la guarda mai** (letto riga per riga).
- **Chi lo conia sono DUE, e si comportano in modo diverso**:
  · `fase83_server.py:7103` (il credito dopo una cancellazione) scrive `"email": ""` — **il campo
    c'è ed è vuoto**;
  · `fase158_domanda.py:163` (il credito della lista d'attesa) scrive **l'email vera**, in
    minuscolo.
  🔑 **Quindi metà dei crediti porta già il nome del proprietario, e nessuno lo legge.**
- **Opzione A** → **0 punti di codice**, più il testo delle regole (che **non esiste**: la parola
  «rimpianto» compare **una volta sola** in tutte le pagine, dentro un badge).
- **Opzione B** → **2 file, 2 punti**: chi legge (`fase59_concierge.py`, un controllo in più) e
  chi conia a `fase83_server.py:7103` (riempire il campo). ⚠️ **Ma cambia un comportamento**: chi
  cancella e poi prenota con un'altra email perde il credito.
- **Opzione C** → **non misurabile**: contare i passaggi di mano richiede un registro che oggi
  non c'è.

**Cosa è irreversibile:** **sì, i token già in giro.** Sono firmati e validi fino a scadenza:
qualunque regola nuova vale per quelli coniati dopo. Quanti ne esistano in produzione **non l'ho
misurato**: comando in PARTE 4.

**Cosa serve sapere:** **se il credito è un regalo o un risarcimento.** Se è un risarcimento
(«ti è andata male, tieni»), essere al portatore è un buco; se è un regalo, è una funzione.

---

## E3 — Cosa siamo, fiscalmente, quando incassiamo per l'host?

*(`RIPRENDI_QUI.md`, voce B12: «non è un lavoro tecnico e non va riparato da chi legge».)*

**La domanda:** i soldi dell'ospite entrano sul nostro conto e restano lì per giorni: fiscalmente
sono nostri o dell'host?

**Le opzioni:**
- **A — siamo intermediari con rappresentanza**: si scrive nel contratto che incassiamo **in nome
  e per conto** dell'host, e la contabilità di oggi resta com'è.
- **B — siamo noi il venditore verso l'ospite**: cambia cosa fatturiamo e a chi.
- **C — cambia il flusso**: i soldi vanno diretti sul conto dell'host e a noi resta solo la
  commissione.

**Cosa cambia nel codice (contato oggi):**
- **Il flusso vero, verificato aprendo i file**: l'incasso nasce senza spartizione all'origine
  (`fase85_pagamenti_stripe.py`: nessun `transfer_data` né `application_fee` nel checkout —
  `grep -n "transfer_data\|application_fee" fase85_pagamenti_stripe.py` → **1 sola riga, ed è un
  commento**, `:134`), e il bonifico all'host parte dopo, separato.
- 🔴 **Il ramo che farebbe l'opzione C esiste ed è morto**: `fase101_stripe_connect.py:26-49`
  (`costruisci_params`, con `transfer_data[destination]` a `:47`) e la classe
  `ProviderStripeConnect` a `:52` sono usati **solo** da `fase104_gateway_asia.py`, che è **fra i
  63 moduli non raggiungibili**. La fabbrica `crea_provider_connect` a `:253-258` restituisce
  **l'altra** classe (`ProviderConnect`). **Verificato riga per riga oggi.**
- ⛔ **E in cima a quel file c'è scritta la giustificazione fiscale del progetto**
  (`fase101_stripe_connect.py:4-6`), che descrive **il ramo morto**, cioè un flusso che non usiamo.
- **Opzione A** → **2 file** di testo: `fase163_accettazioni.py` (2 lingue) e
  `fase185_testi_legali.py` (8 lingue). Zero logica.
- **Opzione B** → tocca la ricevuta (`fase83_server.py:274-299`, **8 lingue**, che oggi dichiara
  di **non** essere una fattura e non nomina l'host come venditore) e un modulo di fatturazione
  che **non esiste** (`grep -ril "fattura\|invoice"` fra i moduli: nessuno emette documenti
  fiscali al cliente). **Punti non misurabili.**
- **Opzione C** → **2 file**: `fase101_stripe_connect.py:253-258` (la fabbrica) e
  `fase85_pagamenti_stripe.py` (il checkout). ⚠️ Cambia **dove stanno i soldi** durante il
  soggiorno, quindi cambia anche l'escrow.

**Cosa è irreversibile:** **sì, tutto ciò che è già stato dichiarato.** E il contratto: se cambia,
gli host ri-firmano.

**Cosa serve sapere:** **la risposta scritta di un commercialista.** Le tre righe da mettergli
davanti sono già misurate in `RIPRENDI_QUI.md` (B12); `METODO_v4.md` PARTE 19.2 elenca le cinque
domande. ⛔ **Nessuna macchina può rispondere a questa, e nemmeno io.**

---

## E4 — Il cambio data serve o no?

*(`RIPRENDI_QUI.md`: «decisione del fondatore ancora da prendere».)*

**La domanda:** chi ha prenotato e deve spostare le date oggi può solo cancellare e riprenotare al
prezzo del giorno: va bene così?

**Le opzioni:**
- **A — va bene così**, e lo si scrive chiaramente prima di prenotare.
- **B — si costruisce lo spostamento**, con le sue regole (chi paga la differenza, entro quando).
- **C — si costruisce solo dentro la finestra di ripensamento**, dove il rimborso è già pieno.

**Cosa cambia nel codice (contato oggi):**
- **Non esiste niente da modificare**: cercato in tutti i moduli e nelle pagine, `cambio data`,
  `cambia data`, `reschedul` → **zero riscontri nel prodotto**. Non c'è rotta, non c'è modulo,
  non c'è test.
- **Opzione A** → **testo**: dove si spiega la cancellazione (`fase111_cancellazione.py` non ha
  testi; i testi stanno in `fase185_testi_legali.py`, 8 lingue, e nel pannello).
- **Opzione B** → **codice nuovo**: tocca il calendario (liberare le vecchie date e bloccare le
  nuove nella stessa transazione), il prezzo e il pagamento della differenza. **Non misurabile**:
  è un pezzo che non c'è.
- **Opzione C** → più piccolo di B, perché dentro le 48 ore non ci sono soldi da spostare.

**Cosa è irreversibile:** niente.

**Cosa serve sapere:** **quanti lo chiederanno.** Zero clienti, zero dati. È l'unica decisione di
questo elenco che si può rimandare **senza costo**, ed è scritto anche in `RIPRENDI_QUI.md`:
«non è un lavoro in coda: è una domanda».

---

## E5 — Esiste un tetto unico a quanto regaliamo su una prenotazione?

*(`RIPRENDI_QUI.md`, voce B11, punto 1 rimasto aperto: «idea A del fondatore».)*

**La domanda:** sei cose regalano soldi sulla stessa prenotazione e nessuna sa delle altre: si
costruisce un posto solo che le somma, o si continua a metterci un tetto per volta?

**Le opzioni:**
- **A — un posto solo che somma**, consultato prima di ogni regalo.
- **B — si continua col tetto per regalo**, come oggi, e si accetta che il giorno che si collega
  un regalo nuovo la somma torni fuori controllo.
- **C — si congelano i regali non ancora collegati** (nessuno nuovo finché non c'è il posto che
  somma).

**Cosa cambia nel codice (contato oggi):**
- **La riparazione del 2026-08-23 è dentro e regge**: `_commissione_regalabile`
  (`fase83_server.py:8247`) è usata in **tutti e due** i punti che regalano oggi —
  `fase83_server.py:5918` e `:8178`. Verificato oggi: due chiamanti, nessun terzo.
- **I regali costruiti e non collegati sono quattro**, e due sono fra i 63 moduli non
  raggiungibili: `fase137_fedelta_guest` (**non raggiungibile**), `fase71_commitment`
  (**non raggiungibile**), `fase78_sleep_guarantee` e `fase109_referral_host` (raggiungibili ma
  senza chiamanti, passaggio 4).
- **Opzione A** → **1 file nuovo o 1 funzione nuova** più **2 punti** da farci passare (i due
  chiamanti di sopra) e **4 punti** il giorno che si collegano gli altri quattro regali.
  ⚠️ In `RIPRENDI_QUI.md` è stimata **5-8 giorni**: è una **stima**, non una misura, ed è scritto.
- **Opzione B** → **0 punti oggi.**
- **Opzione C** → **0 punti di codice**: è una regola su cosa non si collega.

**Cosa è irreversibile:** niente.

**Cosa serve sapere:** **se collegheremo davvero quei quattro regali.** Se la risposta è «non
adesso», l'opzione B costa zero e non fa danno; se è «sì», B diventa il modo in cui il buco si
riapre.

---

## E6 — Le prenotazioni cancellate e non ancora rimborsate: si correggono nel giornale?

*(`REGISTRO_INGEGNERIA.md`, riga 5994: «RESTA DA DECIDERE (fondatore)».)*

**La domanda:** il giornale contabile continua a segnare come dovuti all'host i soldi di una
prenotazione cancellata finché qualcuno non esegue il rimborso: si corregge o si lascia?

**Le opzioni:**
- **A — si lascia**: lo scostamento si chiude da sé quando il rimborso viene eseguito.
- **B — si corregge subito**, con tipi di movimento nuovi.
- **C — si lascia, ma si sorveglia**: un allarme se lo scostamento resta aperto oltre un tempo.

**Cosa cambia nel codice (contato oggi):**
- I tipi di movimento sono una tabella sola: `fase177_financial_controller.py:62-103`
  (**circa 20 tipi**, ognuno una coppia di conti).
- **Opzione A** → **0 punti**.
- **Opzione B** → **1 file** (`fase177_financial_controller.py`) più **gli export fiscali**, che
  la nota del registro dichiara «certificati»: cambiare i tipi di movimento cambia cosa ci
  finisce dentro. **Punti non misurabili** senza sapere quali export sono già stati consegnati a
  qualcuno.
- **Opzione C** → **1 file**: il guardiano dei soldi (`fase186_guardiano.py`), che oggi guarda
  solo i bonifici maturati.

**Cosa è irreversibile:** **sì, le scritture passate.** Il giornale è immutabile per costruzione:
un errore si corregge **aggiungendo** una riga, mai cambiandone una. Quindi qualunque cosa si
scelga, il passato resta scritto com'è.

**Cosa serve sapere:** **cosa dice il commercialista di uno scostamento aperto.** È la stessa
conversazione di **E3** e si può fare nella stessa mezz'ora.

---

## E7 — Il canale diretto segue la rampa di lancio o no?

*(`REGISTRO_INGEGNERIA.md`, riga 7818: «REPERTO da decidere (business, non bug)».)*

**La domanda:** una prenotazione che l'host porta da solo costa a lui **sempre la stessa cifra**,
anche nei primi novanta giorni in cui una prenotazione portata da noi non costa niente: è voluto?

**Le opzioni:**
- **A — è voluto**, e resta così: il canale diretto ha la sua tariffa fissa.
- **B — il diretto segue la rampa** come il marketplace.
- **C — il diretto ha una rampa sua**, diversa.

**Cosa cambia nel codice (contato oggi):**
- **Il punto è uno solo, e l'ho aperto**: `fase98_policy_commissione.py:60-70`
  (`commissione_bps_fonte`): se la fonte è «diretto» **ritorna la costante e basta**; per tutto il
  resto passa dalla rampa (`commissione_bps_per_host`). È **viva**, non morta: la chiama
  `fase81_bootstrap_casavip.py:274`.
- **Il costo di cambiare la cifra è già stato misurato**, dal referto 14 (2026-08-26):
  **104 punti in 10 file**, di cui **87 coppie (chiave, lingua) su 21 chiavi distinte in 5 file**,
  più `fase83_server.py:9496`. *(Per confronto, lo stesso referto misura che cambiare la penale
  costa 22 punti in 7 file: questo è lo stesso lavoro moltiplicato per cinque.)*
- **Opzione A** → **0 punti** di codice; ⚠️ ma i testi devono dirlo, e alcuni oggi non lo dicono.
- **Opzione B** → **1 punto di logica** (`fase98:67-68`) più i **104 punti di testo** già contati.
- **Opzione C** → **1 funzione nuova** in `fase98` più gli stessi 104 punti di testo.

**Cosa è irreversibile:** **sì, le prenotazioni già fatte.** La commissione applicata a una
prenotazione è già scritta nel giornale e non si riscrive.

**Cosa serve sapere:** **cosa vogliamo che l'host faccia.** Se il canale diretto deve essere quello
conveniente, oggi il codice dice l'opposto nei primi mesi. È una scelta di strategia, e nessun
collaudo la può prendere.

---

## E8 — I quattro moduli che l'artefatto spedito non raggiunge: quale delle tre uscite?

*(Memoria di progetto `bookinvip-ingresso-e-cio-che-avvia`, 2026-08-18: «APERTO, decisione del
fondatore, NON archiviare».)*

**La domanda:** quattro moduli — e due si chiamano `money` e `idempotency` — non sono raggiungibili
da ciò che il contenitore avvia: si accendono, si dichiarano spenti, o si tolgono?

**Le opzioni** (le stesse tre di **D9**, ma su quattro nomi precisi):
- **A — si accendono**: si collegano a `main_casavip.py`.
- **B — si dichiarano spenti** con la riga che dice come si accendono.
- **C — si tolgono.**

**Cosa cambia nel codice (misurato adesso):**
- I quattro sono `fase13_protocollo_finale`, `fase15_idempotency`, `fase17_money`,
  `fase23_datastore`. **Verificati adesso nell'elenco dei 63 non raggiungibili.**
- `Dockerfile.casavip:25-27` copia `main_casavip.py`, tutti i `fase*.py` e `deploy/`;
  `:42` avvia `python main_casavip.py`. `collaudi/raggiungibilita.py:79` parte da lì, e solo da lì.
- **`app.py` esiste sul disco (931 righe) e non entra in nessuna immagine**: il Dockerfile non lo
  copia (verificato oggi: `COPY` nomina `main_casavip.py`, `fase*.py`, `deploy`).
- 🔑 **Il punto che rende questa diversa da D9**: `fase17_money` e `fase15_idempotency` sono i due
  moduli che il piano dei blocchi mette **dentro il Blocco 1, SOLDI E PAGAMENTI**
  (`collaudi/piano.py`, blocco 1). Cioè: **fanno parte del blocco che stiamo collaudando, e non
  sono raggiungibili da ciò che gira.**
- **Opzione A** → **1 file** (`main_casavip.py` o `fase81_bootstrap_casavip.py`) e **4 righe di
  import**. ⚠️ Ma accendere un modulo dei soldi significa **collaudarlo**, e il costo vero è quello.
- **Opzione B** → **4 righe** in `REGISTRO_INGEGNERIA.md`.
- **Opzione C** → 4 moduli, più `app.py`. **Righe in gioco misurate oggi**: `app.py` **931 righe**;
  i quattro moduli stanno dentro le 12.609 righe contate in D9.

**Cosa è irreversibile:** **sì, se si sceglie C.**

**Cosa serve sapere:** **se `fase17_money` e `fase15_idempotency` dovevano essere accesi.**
Se sì, non è una decisione: è un difetto, e va trattato come tale. Se no, il loro nome mente e
va cambiato o vanno tolti. **Nessuno dei due si può decidere leggendo il codice**: va guardato
cosa fanno rispetto a quello che la produzione fa già senza di loro.

---

## E9 — I quattro controlli inerti di `fase59`: si tolgono o restano?

*(`RIPRENDI_QUI.md`, voce B13: «non toccato per decisione del fondatore».)*

**La domanda:** quattro controlli nel motore che calcola ogni prezzo non cambiano mai niente:
si tolgono o restano?

**Le opzioni:**
- **A — si tolgono**: è la terza uscita della DO-178C, il codice estraneo si toglie.
- **B — restano**, e restano dichiarati come equivalenti nello schedario.
- **C — si tolgono più tardi**, insieme ad altro lavoro sullo stesso file.

**Cosa cambia nel codice (verificato oggi aprendo le righe):**
- Sono **4 punti in 1 file**: `fase59_concierge.py:318`, `:320`, `:338`, `:494`. Letti oggi:
  · `:318` `if not _intero(comm) or comm < 0: comm = 0` — assegna 0 a chi vale già 0;
  · `:320` `if comm > netto: comm = netto` — riassegna `netto` a chi vale già `netto`;
  · `:338` `tassa = t if (_intero(t) and t >= 0) else 0` — i due rami danno lo stesso 0;
  · `:494` `cr = cr if (_intero(cr) and cr > 0) else 0` — i due rami danno lo stesso 0.
- **Opzione A** → **1 file, 4 punti**, più **4 voci da togliere** dallo schedario degli
  equivalenti in `collaudi/mutazione_prodotto.py` (che decadrebbero comunque da sole: la loro
  impronta non troverebbe più il codice).
- **Opzione B** → **0 punti.**
- **Opzione C** → **0 punti oggi**; il costo è che chi legge quel file fra sei mesi ritrova quattro
  righe che sembrano proteggere qualcosa.

**Cosa è irreversibile:** niente. ⛔ Ma è il motore che calcola **ogni** prezzo: serve
«autorizzato» (divieto B4), e la regola D20 pretende la guardia **vista rossa prima**.

**Cosa serve sapere:** niente di esterno. Questa è l'unica decisione dell'elenco che si può
prendere **con le sole informazioni che ci sono già**: le quattro dimostrazioni esistono e sono
nello schedario con la loro impronta.

---

# PARTE 3 — LE DECISIONI GIÀ PRESE, CHE SEMBRANO ANCORA APERTE

⛔ **Questa parte esiste per un motivo preciso:** cinque volte in tre settimane una sessione ha
riaperto una cosa già decisa e ha lavorato per rifarla. Qui ci sono le decisioni **prese**, con
la data, così domattina non entrano nella pila da decidere.

| Cosa | Deciso il | Cosa fu deciso |
|---|---|---|
| I nomi dei concorrenti | 2026-08-24 | si tolgono e si scrive «i grandi portali» — vedi **D8**, che ne è il seguito sul motore |
| Il rimborso automatico | 2026-08-16 | **non** parte da solo: lista e pulsante. «Prima si guadagna la fiducia, poi si toglie il dito» |
| La finestra di ripensamento | ricerca legale chiusa | non si tocca: copre obblighi di legge |
| I paesi | 2026-08-24 | si apre **un paese alla volta**, non il mondo |
| Le chiavi provvisorie | 2026-08-22 | si cambiano **tutte insieme** l'ultimo giorno, non una alla volta |
| Il prezzo, quale vale | 2026-08-22 | «il numero visto dev'essere il numero pagato» |
| La casella prezzo unica nel pannello | 2026-08-23 | **rimandata**, non annullata: «il pezzo 3 lo lasciamo», da fare prima del primo host vero |
| Il percorso del denaro | 2026-08-22 | la mutazione si misura sui **cinque** moduli che un euro attraversa, non su tutti e 24 |
| I lavori sui testi | 2026-08-24 | si fanno **in un giro solo**, non uno alla volta |

---

# PARTE 4 — QUELLO CHE NON HO POTUTO MISURARE, E IL COMANDO PER MISURARLO

Sei numeri cambiano il peso di sei decisioni, e stanno **sul VPS**, non qui. Non li ho misurati:
questa sessione è in sola lettura sul computer, e ogni comando qui sotto è **di sola lettura**
anche sul server.

**1 · Quanti host hanno firmato il contratto** *(pesa su D3, D6, D7)*
```
ssh root@76.13.44.167 'docker exec casavip_app python -c "import sqlite3;print(sqlite3.connect(\"data/accettazioni.db\").execute(\"select count(*) from accettazioni\").fetchone()[0])"'
```

**2 · Quanti annunci pubblicati veri, e di quanti host** *(pesa su D3, D6)*
```
ssh root@76.13.44.167 'docker exec casavip_app python -c "import sqlite3;c=sqlite3.connect(\"data/vetrina.db\");print(c.execute(\"select count(*) from alloggi\").fetchone())"'
```
⚠️ Il nome del database e della tabella vanno verificati prima: `ls /data` dentro il contenitore.

**3 · Quante prenotazioni «paga in struttura» sono già state incassate** *(pesa su D7 — la più
urgente, perché è accesa)*
```
ssh root@76.13.44.167 'docker exec casavip_app printenv PAGA_STRUTTURA_ATTIVO'
ssh root@76.13.44.167 'docker logs casavip_app 2>&1 | grep -c "anticipo_paga_struttura"'
```

**4 · Quanti Crediti Fondatore sono stati emessi dalla lista d'attesa** *(pesa su D4, E2)*
```
ssh root@76.13.44.167 'docker exec casavip_app python -c "import sqlite3;print(sqlite3.connect(\"data/domanda.db\").execute(\"select count(*) from domanda\").fetchone()[0])"'
```

**5 · Quanti inviti fra host sono stati generati o pagati** *(pesa su D1)*
```
ssh root@76.13.44.167 'docker exec casavip_app python -c "import sqlite3;print(sqlite3.connect(\"data/viral.db\").execute(\"select count(*) from referral\").fetchone()[0])"'
```

**6 · Quanti bonifici sono in attesa e da quanto** *(pesa su D11)*
```
ssh root@76.13.44.167 'docker exec casavip_app python -c "import sqlite3;c=sqlite3.connect(\"data/payout.db\");print(list(c.execute(\"select stato,count(*) from payout group by stato\")))"'
```

⛔ **I nomi dei file di database vanno letti, non ricordati** (sbaglio S2): prima di ognuno,
`ssh root@76.13.44.167 'docker exec casavip_app ls -la data/'`. Se un nome non c'è, il comando va
corretto — **non il risultato**.

---

# PARTE 5 — IL METODO, E DOVE NON ARRIVA

**Come ho trovato le decisioni.** Tre setacci, non uno:
1. le **dodici** dichiarate in `collaudi/audit/0_piano_riparazioni.md`, sezione «LE DODICI CHE NON
   SONO RIPARAZIONI»;
2. una ricerca per **marcatore** su tutti i documenti e i referti — «decisione del fondatore»,
   «da decidere», «non è una riparazione», «solo il fondatore», «⚖️» — che ha aggiunto **E1, E2,
   E3, E4, E5, E9** da `RIPRENDI_QUI.md` ed **E6, E7** da `REGISTRO_INGEGNERIA.md`;
3. le memorie di progetto marcate **APERTO**, che hanno aggiunto **E8**.

**Come ho misurato.** Ogni numero di questo file viene da un comando eseguito oggi su `663eab3`,
e il comando è scritto accanto quando non è ovvio. Dove non ho potuto contare, c'è scritto
**«non misurabile»** con il motivo, oppure **«non misurato»** con il comando in PARTE 4.

## Cosa questo referto non ha guardato

1. **Non ho riverificato i nove referti voce per voce.** Li prendo per buoni: ognuno porta i suoi
   `file:riga`. Dove li ho aperti (D1, D5, D7, E2, E3, E9) l'ho scritto, e in **tutti** i casi
   aperti il fatto era confermato.
2. **Non ho misurato il costo in tempo di nessuna opzione.** Ho contato **file e punti**, che è una
   misura; quanto ci vuole a scriverli non lo è, e inventarlo sarebbe la D22 violata.
3. **Non ho guardato l'ambiente del VPS** se non attraverso `collaudi/audit/16_ambiente_vps.md`,
   che l'ha misurato il 2026-08-25 su `cb45c80`. Da allora ci sono stati due commit: se una
   variabile è cambiata, **D7** e **D9** cambiano peso.
4. **Tre `fase*.py` erano modificati da altre sessioni** mentre misuravo (`fase57_vetrina.py`,
   `fase58_channel_manager.py`, `fase81_bootstrap_casavip.py`). Li ho **letti e mai toccati**, ma
   i numeri di riga che li riguardano — soprattutto il cablaggio in `fase81` citato in **D1**,
   **D5** ed **E5** — possono spostarsi di qualche riga quando quelle sessioni finiscono.
   ⛔ Si rileggono prima di lavorarci: **il nome del punto regge, il numero di riga no.**
5. **Non ho contato le decisioni dentro i referti 10-20 che non esistono ancora** (undici
   passaggi di audit sono ancora da fare, elencati in `0_piano_riparazioni.md`). Quasi certamente
   ne produrranno altre: questo elenco è **completo su ciò che è stato scritto**, non su ciò che
   c'è.
6. **Non ho scelto e non ho consigliato**, ed è la parte che vale: se domattina una di queste
   schede sembra avere una risposta ovvia, quella è **la risposta del fondatore**, non la mia
   che si è travestita da misura.
