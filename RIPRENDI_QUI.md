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

## 📍 DOVE SIAMO — 2026-08-28 mattina, misurato dai QUATTRO posti

```
computer            5d6e0b3   <- git rev-parse --short master, da PowerShell vera
GitHub master       5d6e0b3   <- git ls-remote --heads origin master
                                 5d6e0b307279e24d22da6c06f846d2edd834b9b3
albero              pulito    <- git status --porcelain, uscita vuota
CARICATORE          6042      <- misurato PRIMA di qualunque giro (S14), da PowerShell,
                                 DOPO l'unione di tutte e tre le corsie. EXIT=0
VPS (git sul disco) efe35b5   <- ssh in sola lettura, misurato adesso, non ricordato
IMMAGINE VIVA       sha256:8def0ea3d9f2b0c1ab74385bf45f6bd152105b03ac87f1bdd02e06bf198b2676
                              <- docker inspect --format='{{.Image}}' casavip_app
IN PRODUZIONE       curl https://bookinvip.com/api/health -> HTTP 200 in 0,523 s
                    {"status": "ok", "money_unit": "cents_integer",
                     "guardiano": "ok", "email_ko": 0}
                    curl https://bookinvip.com/           -> HTTP 200 in 0,432 s
```

⛔ **IL VPS È INDIETRO DI NOVE UNIONI E VENTISEI COMMIT, E QUESTA VOLTA NON È UNO SCARTO
INNOCUO.** Misurato, non dedotto:
```
git rev-list --count efe35b5..master           -> 26
git rev-list --count --merges efe35b5..master  ->  9
```

Fino al 26 agosto la frase che giustificava lo scarto era «sono stati uniti solo documenti,
nessun codice è cambiato». **Da quel momento non è più vera, e va detto per esteso** — questo
è il diff fra ciò che il browser serve adesso e ciò che c'è nel repository:

```
git diff --stat efe35b5..master -- deploy/
  deploy/app.js      | 11 +++++++++--
  deploy/index.html  | 12 ++++++++++++

git diff --stat efe35b5..master -- 'fase*.py' main_casavip.py
  fase162_pagamenti_pendenti.py | 46 ++++++++++++++++++++++--------
  fase182_riconciliazione.py    | 44 ++++++++++++++++++++++-----------
  fase99_multicurrency.py       | 10 +++++++++-
```

🔴 **La riga che pesa più di tutte è `fase99_multicurrency.py`:** è la riparazione di ISK e
UGX, due valute che Stripe vuole a **due** decimali e che noi trattavamo a **zero** — cioè su
un annuncio in corone islandesi si incassava **un centesimo del dovuto**. Quella riparazione è
nel repository e **non è in produzione**. Non è un rischio teorico: è un difetto sui soldi già
capito, già provato e ancora vivo per chi apre il sito.

⛔ **E `git pull` sul server NON basta.** `deploy/` non è montato: entra nell'immagine con
`COPY` (`STATIC_DIR=/app/deploy`). Finché non si **ricostruisce l'immagine**, il disco del
server può essere aggiornato e il browser continuare a servire il vecchio. È la trappola del
2026-08-07, ed è il motivo per cui i posti sono **quattro** e non tre.

### 🌙 LA NOTTE FRA IL 27 E IL 28 AGOSTO — tre corsie, tre unioni, tutte con CI verde

> **Scritto il 2026-08-28 dalla corsia che coordina, e sostituisce il blocco della corsia B
> del 27 sera.** Quel blocco descriveva due commit non ancora uniti, tre file non committati e
> `master` a `604991e`: **niente di tutto ciò esiste più.** È unito, l'albero è pulito,
> `master` è a `5d6e0b3`. Un blocco che descrive uno stato morto non è storia: è una trappola
> per chi lo legge domani (sbaglio **S10**). L'unica cosa di quel blocco ancora viva — la
> seconda copia della whitelist in `fase83_server.py:8196` — sta dove deve stare, nella voce
> **B21** in sezione C, e non serve ripeterla qui.

| unione | commit | corsia | cosa ha chiuso |
|---|---|---|---|
| **#121** | `c5783ff` → `58d20cb` | **B** | il job `money-smoke` era **cieco sul teorema dei soldi** |
| **#122** | `aaf9b59` → `8131bc7` | **A** | **PARTE 12 «LA PORTA»**: 34 caselle misurate, non più vuote |
| **#123** | `1adc67e` + `8354e10` → `5d6e0b3` | **C** | due difetti sui soldi: riconciliazione e ISK/UGX |

#### 🔵 #121 — il job che porta il nome «money» saltava le prove sui soldi, in silenzio

`money-smoke` installava solo `hypothesis` (`ci.yml:108`) ed eseguiva `test_property_soldi`,
che contiene **due prove z3** protette da `self.skipTest` se z3 manca
(`test_property_soldi.py:230-234`). Il teorema «nessun centesimo si crea o si perde» **si
saltava senza dirlo**, e il job restava verde.

E la guardia che avrebbe dovuto accorgersene **non poteva, per costruzione**:
`_job_esegue_le_prove_z3` riconosceva un job solo se conteneva `discover`, `$(` o
`test_fase199` — un **elenco di nomi scritto a mano**. Il suo stesso docstring affermava il
falso: «money-smoke non tocca fase199: obbligarlo a installare z3 sarebbe spreco». Vero su
`fase199`, e irrilevante, perché le prove z3 stanno in **tre** file.

⚠️ **RIDIMENSIONAMENTO, e va tenuto perché è la parte onesta:** il teorema **era comunque
dimostrato in CI**, da `full-suite` e `copertura`, che z3 lo installano. **Non c'era un buco
nei soldi: c'era un buco nella guardia.** Raccontarlo al contrario sarebbe più drammatico e
falso.

Riparato con **D20** rispettato, rosso letto **prima**:
```
rosso:  AssertionError: Lists differ: [] != ['money-smoke']   EXIT=1
fix:    ci.yml:108   pip install hypothesis  ->  pip install hypothesis z3-solver
verde:  Ran 5, OK, EXIT=0
```

🔑 **E la parte che vale più della riparazione:** il criterio nuovo **non nomina più i job a
mano, li DERIVA dall'albero sintattico**. Un modulo «porta prove z3» se (a) importa z3, oppure
(b) nomina una funzione di produzione che importa z3. Il ramo (b) chiude la catena
test→produzione→z3 **prima** che qualcuno la apra: oggi è vuoto, ed è dichiarato vuoto.
E la trappola **S6** (una guardia che un commento può soddisfare) è esclusa **per
costruzione**: `test_pipeline_ci.py:1551` contiene la **stringa** `"import z3"` dentro
un'asserzione, e una stringa non è un nodo `Import`.

⚠️ **Limite dichiarato dalla corsia B stessa** (D18 punto 3): il criterio guarda **un solo
salto**. Una catena più lunga non la vede. Oggi il ramo indiretto è vuoto (misurato) e
allargarlo costerebbe falsi allarmi: è un buco **noto**, non nascosto.

#### 🟢 #122 — PARTE 12 «LA PORTA» non è più una lista di caselle vuote

34 caselle, ognuna con l'esito **e il comando che lo dimostra**. Ricontate dalla corsia che
coordina il 2026-08-28 — non riferite dalla corsia A, ricontate:
```
sed -n '499,666p' collaudi/METODO_v4.md | grep -o "\[SI'\]"          | wc -l  -> 13
sed -n '499,666p' collaudi/METODO_v4.md | grep -o "\[NO\]"           | wc -l  -> 10
sed -n '499,666p' collaudi/METODO_v4.md | grep -o "\[NON MISURATO\]" | wc -l  -> 11
                                                                      totale  -> 34
```

⭐ **La consegna più scomoda della corsia A non è una casella: su 13 [SI'], DODICI non sono
mai state viste rosse.** Non è la qualità di una casella, è la qualità di **tutte le altre**.
Un [SI'] appoggiato a una guardia che non ha mai fallito davanti al guasto che dovrebbe vedere
è esattamente il **verde finto** della regola ferrea 2 — scritto dentro un documento ufficiale,
dove pesa di più.

#### 🔴 #123 — due difetti sui soldi, e il primo era vivo

**(a) La riconciliazione accusava prenotazioni SANE.** `_pagina` ha un tetto di 20 pagine e
scrive `logger.warning(… "risultato PARZIALE, indicato nel report")`. **Nel report non c'è**:
il dizionario di `riconcilia()` ha nove chiavi e **nessuna dichiara la parzialità**.

⛔ **La direzione è MISURATA, non dedotta** — scenario costruito dalla corsia C:
```
sessioni Stripe 2100 · lette 2000 · incassi a giornale 100
  ->  ok=False · solo_giornale mostrati 50 (veri 100) · delta EUR -100.000
```
**Cento prenotazioni in regola accusate, e un ammanco INVENTATO di 1.000,00 EUR.** Con quel
referto il Guardiano dei soldi **manda l'email d'allarme**.

⛔ **E QUI VA CORRETTA UNA FRASE SCRITTA DALLA CORSIA CHE COORDINA, non dalla corsia C.**
La voce **B7** diceva «il rapporto dichiara ok/fantasmi come se avesse guardato tutto», cioè
descriveva un **falso ok**. È il contrario: `ok` non diventa **mai** falsamente positivo — è un
**falso allarme**. La corsia C aveva ragione dal primo referto. La differenza non è una
sfumatura: «tace quando dovrebbe gridare» e «grida quando dovrebbe tacere» hanno **rimedi
opposti**, e un falso allarme insegna a ignorare i segnali (regola ferrea 10).

**Secondo difetto, sovrapposto:** gli elenchi sono tagliati a 50 (`solo_stripe[:50]` e simili)
ma `fantasmi` e `ok` sono calcolati **prima** del taglio. Quindi il taglio **non falsa il
verdetto: nasconde la grandezza.** Chi legge vede 50 dove i veri sono 100.

**(b) ISK e UGX trattate a zero decimali.** Stripe le vuole a **due**: su un annuncio in corone
islandesi si incassava **un centesimo del dovuto**.
✅ Verificato che **nessun dato reale** in ISK o UGX esiste nei 25 archivi veri (186 righe in
tutto): **non è stato perso nessun soldo davvero.**
⛔ **Ma la riparazione NON è online** — vedi il riquadro in cima.

#### ⭐ LA LEZIONE PIÙ NUOVA DELLA NOTTE, e nasce da un giro di suite buttato dopo 2h19m

> **«Un NON ESEGUITO non si sostituisce con una misura presa nello stesso posto che lo rende
> non eseguibile.»** *(corsia C, 2026-08-28)*

Il pre-volo dava `NON ESEGUITO` sul controllo 4 («l'ambiente è quello dichiarato») perché
vedeva `MSYSTEM=MINGW64`. La corsia C ha considerato quel non-eseguito un falso allarme del
proprio ambiente e l'ha **scavalcato misurando a mano la cosa che il controllo protegge**:
`openssl` c'è o no? Ha misurato «c'è in tutt'e due le shell» e ha lanciato.

⛔ Ma quella misura girava in un `powershell.exe` **lanciato da Git Bash**, che eredita
`MSYSTEM` **e il PATH**. Non era PowerShell: era **Git Bash travestito**. Da una PowerShell
ripulita (`Remove-Item Env:MSYSTEM` + PATH ricostruito dal registro) `openssl` **non c'è**.
Il giro è morto dopo **2h19m** su quattro guardie, e la prima lo dichiarava da sé:
```
AssertionError: 'MINGW64' is not false : SUITE LANCIATA DALLA SHELL SBAGLIATA …
⛔ Il risultato di questa suite NON vale. Rilanciala da PowerShell.
```

💡 **Cosa aggiunge a S11**, che già diceva «la verifica si fa nella stessa shell che ha
eseguito la cosa»: che **lanciare un'altra shell da dentro la prima NON cambia ambiente**. Le
variabili si ereditano. Chi crede di aver «rilanciato dall'altra shell» sta misurando **la
stessa di prima**. La corsia A l'aveva trovato in forma indipendente qualche ora prima, e il
rimedio è identico: togliere `MSYSTEM` e ricostruire il PATH dal registro.

⛔ **E VA CORRETTA UN'ALTRA FRASE DELLA CORSIA CHE COORDINA.** Aveva definito la divergenza fra
A e C «due misure opposte sulla stessa macchina, D23 nella sua forma più pura». **Falso.** Era
**una misura buona (A) e una contaminata (C)**. Se fosse rimasta scritta così, questo documento
avrebbe insegnato una lezione sbagliata. **L'ha segnalato la corsia C sulla propria misura**,
non chi l'aveva scritta.

✅ **E la guardia ha funzionato:** `test_la_suite_non_gira_da_GIT_BASH` ha **rifiutato** il giro
e ha spiegato perché. È un allarme che ha gridato quando serviva — la metà della regola ferrea
10 che di solito non si vede mai.

#### 🧭 COME SI SONO COORDINATE LE QUATTRO SESSIONI, e perché va scritto

⛔ **`CLAUDE.md` B1 NON È STATO TOCCATO e non va toccato.** Descrive la procedura normale, che
torna a valere tale e quale. Riscriverlo per una notte lo indebolirebbe per sempre — e quel
divieto è nato proprio da una sessione in cui una frase era stata presa per un'autorizzazione.
Qui si scrive **cosa è successo**, perché chi legge fra un mese troverà commit senza la frase
canonica accanto e deve poter **capire** invece di sospettare una violazione.

Il fondatore ha delegato l'autorizzazione **alla corsia che coordina**. Le sue parole, copiate
e non parafrasate, refusi compresi, ognuna col posto in cui è stata scritta:

- nella sessione che **coordina**: *«ECCEZIONE AUTORIZZA TU FINO ALLA FINE DEL LAVORO DI TUTTE
  LE CHAT, GESTISCI TU CON CONTROLLI RIGOROSI … AUTORIZZO TUTTO COMMIT E TUTTO QUELLO CHE SERVE
  PER FINIRE»*, poi *«NON FARMELO SCRIVERE PIU AUTORIZZI TU FINO ALLA FINE SEI AUTORIZZATO»*;
- nella sessione della corsia **B**: *«LE AURIZZAZIONI TE LE DA LA CHAT CHE CORDINA LO
  AUTORIZZATA IO»*;
- nella sessione della corsia **C**: *«CETTALE LO AUTORIZZATA IO»*;
- nella sessione della corsia **A**: *«ECCEZIONE DA ADESSO TI AUTORIZZA LA CHAT CHE CORDINA E
  AUTORIZZATA»*.

⚠️ **E la cosa che rende onesto il resoconto, segnalata dalla corsia B:** la parola «ECCEZIONE»
e il limite «fino alla fine del lavoro di tutte le chat» compaiono **solo** nella sessione che
coordina. Le corsie B e C hanno visto una delega **senza limite dichiarato**. Chi legge deve
poter distinguere ciò che ogni corsia ha davvero visto da ciò che sapeva solo il coordinamento.

⚠️ **E le tre corsie hanno RIFIUTATO l'autorizzazione riferita** finché non c'era una riga del
fondatore nel **loro** registro — A due volte, B una, C una. La corsia A è arrivata a leggere la
propria trascrizione su disco e a catalogare ogni occorrenza: «sei divieti, zero
autorizzazioni». **È il comportamento giusto, e va scritto**: è la prova che la delega non è
diventata un aggiramento. Se una corsia smette di poter dire di no, la delega **è** un
aggiramento.

🔑 **La forma che ha retto**, e serve a chi coordinerà domani: quando si chiede a una corsia se
ha l'autorizzazione, le si chiede **dove guardare**, mai le si dice che ce l'ha. La frase esatta
è *«io non ti sto autorizzando, ti sto dicendo dove guardare»* — è l'unica forma in cui quella
domanda non diventa **essa stessa** l'autorizzazione.

---

## ⚖️ LE DUE DECISIONI CHE ASPETTANO IL FONDATORE — dalla notte del 27-28 agosto

> **Sono due, e sono le cose più importanti uscite da quella notte.** Non le mette in questa
> sezione uno strumento: le ha indicate la corsia A alla fine del censimento di PARTE 12, e
> reggono alla verifica. **Dove vanno — prima di aprire (sezione B) o dopo (sezione C) — lo
> decide il fondatore**, perché sono scelte che toccano soldi e rischio, non scelte tecniche
> (D12). Qui c'è la misura, non la decisione.

### 1️⃣ 🔴 LA RICONCILIAZIONE NOTTURNA NON ESISTE — e non è un modulo da scrivere, è un filo da attaccare

**Cosa c'è oggi**, misurato:
```
grep -rn "riconcil" deploy/ .github/ docker-compose.casavip.yml
  ->  un solo riscontro: deploy/bunker.html:641 chiama /api/bunker/riconciliazione
```
Gira **solo se qualcuno schiaccia un pulsante nel bunker**. Nessun lavoro notturno, nessuna
mail — né quando trova un guaio, né quando è tutto a posto.

**Perché è la prima di tutte, e non una delle dieci.** Le altre nove caselle `[NO]` di PARTE 12
sono buchi in **un** meccanismo. Questa è **la rete che prende ciò che sfugge a tutti gli
altri**. Oggi il percorso del pagamento ha **quattro modi diversi di perdere un incasso, e
nessuno lascia traccia** — tutti e quattro misurati leggendo il codice, non supposti:

| # | il buco | dove si vede |
|---|---|---|
| 1 | il webhook **elabora in linea**, non differisce | `fase83_server.py:7914-7972` — firma, poi `_conferma_pagamento(rif)` subito, poi 200 |
| 2 | **non salva l'evento grezzo**: se l'elaborazione muore, l'evento è perso | stesso punto: non esiste elaborazione differita |
| 3 | **non richiede mai l'oggetto all'API**: legge `mode`, `metadata`, `status` dal payload | `grep -rn "retrieve" --include=*.py .` fuori dai test → **nessuna riga** |
| 4 | **nessuna tabella di eventi visti**: Stripe ritenta per 72 ore e non sappiamo se l'abbiamo già visto | `grep -rn "event_id\|eventi_visti"` → nessun archivio di eventi |

La riconciliazione notturna è **l'unica cosa che il giorno dopo direbbe «Stripe dice 400, il
mio libro ne conosce 380»**. Senza, quei 20 euro li scopre **un cliente che protesta, oppure
nessuno**.

⛔ **E il codice esiste già ed è provato.** `fase182_riconciliazione.py` funziona — è in sola
lettura, è acceso dalla chiave, `test_riconciliazione` è verde, e stanotte è stato pure
riparato (il falso allarme sul giro troncato). **Manca chi la chiama ogni notte e chi manda la
mail.** Non è un modulo da scrivere: è un filo da attaccare.

⚠️ **E una cosa da decidere insieme, trovata per strada e non riparata:** un giro **troncato**
continua a emettere un verdetto. Il progetto ha già la risposta giusta e sta in
`fase186_guardiano.py:74`, il marcatore **`NON_ESEGUITO`**, nato il 2026-08-15 per lo stesso
identico motivo. Un giro che non ha finito di guardare non dovrebbe dire né `ok` né allarme:
dovrebbe dire **che non ha finito di guardare** (è lo sbaglio **S7**). Tocca produzione: serve
«**autorizzato**».

### 2️⃣ 🔴 `gitleaks` È INUTILIZZABILE E IL REPOSITORY È PUBBLICO — l'unico danno IRREVERSIBILE

La casella di PARTE 12 «nessuna chiave nel codice che arriva al browser» è rimasta
**`[NON MISURATO]`** perché lo strumento che dovrebbe misurarla **non è utilizzabile**.

**Perché è diverso da tutti gli altri buchi aperti.** Ogni altra voce di questo file descrive
qualcosa che, il giorno che si rompe, **si ripara**. Un segreto finito in un repository
pubblico **non si ripara: si revoca** — e nel frattempo **è già stato letto**. È l'unico punto
di PARTE 12 il cui danno è **irreversibile**, ed è per questo che sta accanto alla
riconciliazione e non in fondo all'elenco.

⛔ **E c'è un difetto vero che lo rende peggiore, trovato dalla corsia A:**
`collaudi/cricchetto_statico.py` esce **`2`** sia per un errore d'uso di `argparse`, sia
quando `gitleaks` è inutilizzabile. **Due significati opposti sullo stesso codice d'uscita** —
uno è «hai scritto male il comando», l'altro è «la guardia sui segreti non sta guardando». Chi
legge un `2` non ha modo di sapere quale dei due è, e quello grave è indistinguibile da quello
innocuo. È la forma peggiore di **osservabile debole** (regola ferrea 9) perché non è un log
povero: è un **verdetto ambiguo**.

⚠️ **Quello che NON è stato misurato, e va detto** (D18 punto 3): *perché* gitleaks sia
inutilizzabile su questa macchina non è stato diagnosticato. Qui c'è il fatto, non la causa.

---

⛔ **I POSTI SONO QUATTRO, NON TRE, E IL QUARTO E' QUELLO CHE MENTE.** Alle 11:55 del
2026-08-26 i tre `git rev-parse` dicevano tutti `a8b68a0` e sarebbe stato vero scrivere
«allineati» — mentre il sito **serviva ancora `3ceb4c5`**. Il `git pull` aggiorna il disco;
il contenitore continua a girare l'immagine con cui e' partito. `deploy/` **non e' montato**
(entra nell'immagine con `COPY`, `STATIC_DIR=/app/deploy`), quindi nemmeno le pagine
cambiano. E' la trappola del **2026-08-07**, ed e' tornata: si vede solo col quarto comando,
`docker inspect --format '{{.Image}}' casavip_app`.

---

## ✅ CHIUSO: «LE EMAIL PERSE IN SILENZIO» — in produzione da `d7f60c7`

**Il difetto**, misurato nei referti `collaudi/audit/15_dipendenze_esterne.md` (sez. «LE TRE
CHE PERDONO IL MESSAGGIO IN SILENZIO») e `20_sorveglianza.md` (sez. 3.1 e 3.3):
`ProviderEmail.invia()` restituiva un bool onesto e **nessuno lo leggeva**. Ogni invio
partiva come thread demone col valore di ritorno scartato. Con l'SMTP giu' sparivano il
voucher e il PIN di check-in dell'ospite, la conferma di pagamento, il link di reset
password, la ricevuta — e **l'allarme del Guardiano dei soldi**, che esce per email. E il
pezzo che rendeva tutto invisibile invece che solo grave: quei fallimenti finivano in
`logger.warning`, mentre `fase186_guardiano.py:275` guarda **solo gli `ERROR`**. Non solo si
perdevano: **non li contava nessuno**.

**Cos'e' entrato**, in `fase83_server.py`:
- `_invia_tracciato(prov, dest, oggetto, html, template, riferimento)` — il punto obbligato
  che **legge** il bool. Su `False`: `logger.error` + contatore. Non solleva mai (gira dentro
  un thread demone). ⛔ Non registra mai il destinatario: e' un dato personale (referto 12);
- e' il `target` di **tutti e sette** i thread di invio (erano 5539, 6092, 8594, 8689, 10085,
  10126, 11122);
- i tre cancelli **5505 / 8586 / 8685** avevano un `if ... email_provider is not None`
  **senza `else`**: col provider spento il ramo veniva saltato e non restava traccia di
  niente. Ora c'e' il ramo, e guarda che l'email fosse **DOVUTA** (indirizzo valido, gettone
  presente, account creato): lamentarsi quando non c'era niente da mandare sarebbe un falso
  allarme;
- **`email_ko` su `/api/health`**, accanto a `guardiano`. Stessa ragione: da fuori il volume
  Docker non si vede, una sentinella puo' solo fare una richiesta HTTP. ⛔ Non tocca `status`:
  un'email persa non e' un sito giu'.

🔑 **LA LEZIONE, ed e' costata un giro di suite intero.** La prima riparazione usava
`logger.error` **anche** per «provider spento», e la suite l'ha bocciata:
`test_cancellazione_money.test_una_cancellazione_RIUSCITA_non_scrive_errori` pretende **zero
`ERROR` sul percorso SANO** e ne trovava uno per **ogni prenotazione**. Aveva ragione (regola
ferrea 10). Le due cose sono diverse e adesso lo dicono:

| | cos'e' | dove finisce | chi lo legge |
|---|---|---|---|
| `invia()` risponde NO | un **EVENTO**, raro | `logger.error` | il Guardiano, entro 24 h |
| provider **SPENTO** | uno **STATO** di configurazione, permanente | `logger.warning` **+ il conteggio** | `email_ko` su `/api/health`, dalla sentinella esterna |

Contare sempre e gridare una volta sola: contare senza registrare non dice **quale** email
manca; gridare a ogni prenotazione trasforma il rosso in rumore, e un rosso che diventa
rumore viene spento — che e' il modo in cui si perde una sorveglianza.

**Le guardie: `test_email_tracciata.py`, 16, scritte PRIMA e viste ROSSE** (D20). Sul codice
di allora: `Ran 15 -- FAILED (failures=7, errors=7)`, cioe' 14 su 15. La quindicesima era
verde apposta (il reset password **non** si lamenta per un'email che non doveva partire) e
doveva restare verde. La sedicesima e' nata **dopo**, dal rosso qui sopra, e vive accanto al
codice che ha corretto.

⚠️ **COSA NON FA, dichiarato** (D18 punto 3): non ritenta e non mette in coda — un'email persa
resta persa, ma da adesso qualcuno lo sa entro 24 ore; il contatore vive **nel processo**, un
riavvio lo azzera («da quando sono in piedi», non «da sempre»); **nessuna riga nel libro
giornale**, ed e' voluto — quello e' partita doppia, `fase177:205` pretende `imp > 0` e un
`tipo` fra quelli ammessi, e un'email fallita non ha un importo (scelta 1 del fondatore).

💡 **Il valore che conta:** `email_ko` in produzione e' **0**, ed e' il numero giusto — il
provider e' configurato e nessuna email risulta non consegnata da quando il processo e' in
piedi. **Se comincia a salire, non e' il contatore che sbaglia: e' l'SMTP.**

---

**Il deploy delle 17:06 del 2026-08-26, autorizzato a voce, passo per passo:**

| passo | esito misurato |
|---|---|
| 1. paracadute `:prec` agganciato **prima** del build | `d6b2eefd...` == immagine viva: **i due sha256 coincidono** |
| 2. `docker compose ... build app` | nuova immagine `8def0ea3...`, **diversa** da `:prec` |
| 3-4. `stop app backup` -> `rm -f app backup` -> `up -d` | fuori servizio **dalle 17:06:00Z alle 17:06:28Z = 28 s** |
| 5. `docker inspect` | immagine viva == `casavip-app:latest` == `8def0ea3...`, `running health=healthy` |
| 6. il sito risponde | `HTTP 200 in 0,496 s` |
| 7. il campo nuovo e' davvero SERVITO | `/api/health` -> `"email_ko":0` |

⚠️ **LA CI E' STATA IN AVARIA, e il doppione che ne e' nato va saputo leggere.** Actions e'
andata in `major_outage` alle 15:11Z: la richiesta **113**, aperta alle 16:22, non ha fatto
partire **niente** — zero `check_suites`, zero run in coda, e anche la sentinella programmata
si e' fermata (l'ultima delle 16:03, poi il buco). Non si e' unito niente al buio: **il
giudice e' la tabella dei job letta dall'API**, e il verde locale e' un indizio (ferrea 8).
Chiudendo e riaprendo la richiesta la CI e' ripartita alle 16:37 — e poi l'evento originale,
rimasto in coda durante l'avaria, e' arrivato **in ritardo** e ne ha lanciata una **seconda**
alle 16:49. Sulla stessa impronta risultano cosi' **31 check-run e due run**:

```
id=32989458333  BookinVIP CI  cancelled   creata 16:37:46   <- annullata dalla concorrenza
id=32990638411  BookinVIP CI  success     creata 16:49:53   <- 14 job: 13 success + zap skipped
```

⛔ La prima risulta `cancelled` e il suo `gate` `failure`, **e non e' un rosso del codice**:
l'ha annullata `cancel-in-progress: true` quando e' partita la seconda, e il `gate` e' caduto
solo perche' due dei suoi `needs` erano stati annullati. Si giudica **la run**, job per job,
non la somma delle due: sommandole si legge «3 non verdi» su un lavoro che e' verde.

⚠️ **`/host.html` non si controlla con `curl` da fuori**: risponde **302 -> /entra-host**, e'
un cancello. Il primo confronto «prima/dopo» fatto su quella pagina misurava **zero contro
zero**, cioe' niente: la redirezione non consegna mai il file. Il controllo che vale su una
pagina protetta e' il `sha256` **dentro il contenitore**, non il `grep` sull'HTTP.

✅ **Il paracadute ADESSO e' agganciato bene**: `casavip-app:prec` = `d6b2eefd...`, l'ultima
immagine buona **prima** di questo deploy. Il 26/08 alle 12:00, prima del deploy precedente,
puntava invece a `80f21d84...`, cioe' **un'immagine che non girava da giorni** — saltare col
paracadute avrebbe riportato a uno stato che non era l'ultimo buono. Si riaggancia a **ogni**
deploy, **prima** del build, e si verifica che i due sha256 coincidano.

**I commit precedenti, e come ci si e' arrivati:**

Unito con la richiesta **113**, riletta dall'API dopo l'unione (non la risposta del merge):
`merged=True · merge_commit_sha=d7f60c705264426ddd890431b7794b2deb067673 · state=closed ·
merged_at=2026-08-26 17:05:12`.

Prima ancora, la richiesta **112** (`1e9c5a4`, consegne) e la **111** (`a8b68a0`, consegne).
E la **110** (`ce3cfe8`):

Unito con la richiesta **110**, riletta dall'API dopo l'unione (non la risposta del merge):
`merged=True · merge_commit_sha=ce3cfe82ab6915d4e5d5dc1794dd2d480cdffc52 · state=closed ·
merged_at=2026-08-26 09:50:19`.
CI: **16 job, 0 in corso, 15 `success`**; l'unico non-success e' `zap`, **saltato per
costruzione** (`.github/workflows/ci.yml` lo fa girare solo su `schedule` o
`workflow_dispatch`, mai su una richiesta di unione).

**Chiuso in quel commit — i cinque strumenti di analisi statica sono ACCESI:**

`ruff` · `bandit` · `gitleaks` · `pip-audit` · `semgrep` girano nella CI dentro il job
**`qualita`**, che e' gia' bloccante e gia' dentro il gate. Nessuna riga di produzione e'
stata toccata per farli tacere: solo configurazione, workflow, e un attrezzo nuovo.

- **Il meccanismo e' il CRICCHETTO** (`collaudi/cricchetto_statico.py`). Le **1.258**
  segnalazioni di oggi sono congelate in `collaudi/baseline/*.json` e **non bloccano**;
  blocca tutto cio' che compare **in piu'**. Il numero puo' solo scendere. La chiave della
  fotografia e' **(file, regola) -> quante volte**, mai il numero di riga: un commento in
  piu' sposta le righe e una fotografia appesa alla riga diventerebbe rossa senza motivo.
  ⛔ **La fotografia si rifa' per DIMINUIRE il debito, mai per assorbire un rilievo appena
  creato**: e' la sola regola che tiene in piedi il meccanismo.
- **Visto rosso in due modi**, non solo in verde: `--autoprova` inietta una segnalazione
  finta e il confronto la vede (uscita 1); provato anche con un guasto vero (un import
  inutilizzato in un file nuovo) -> `+1 ...|F401`, uscita 1; tolto il file, verde da solo.
- **Le fotografie combaciano su Windows e su Linux**: nel job `qualita` di questa unione il
  log stampa `686 / 548 / 8 / 10 / 6`, gli stessi numeri misurati sul computer, e nessuna
  riga di punti ciechi. Non e' un verde muto: i numeri si leggono nel log.
- **Tre cose vere trovate misurando** (dettaglio in `collaudi/audit/18_strumenti.md`):
  1. `pip-audit` nella CI misurava **se stesso** — senza `-r` guardava l'ambiente del job
     (ruff, mypy, bandit), non il prodotto: 136 falle «dell'ambiente» contro **10** vere in
     `requirements.txt`. Ora usa `-r requirements.txt`.
  2. `semgrep` col timeout di serie (5 s) andava in **timeout su 12 regole** proprio sui
     file piu' grossi, `fase83_server.py` compreso: stampava «4 rilievi» mentre due non li
     aveva mai cercati. A 120 s ne escono **6**, i due nascosti entrambi in produzione
     (guardati uno per uno: falsi positivi). Il cricchetto ora **dichiara ogni timeout**.
  3. `gitleaks`: `dir` da **35** rilievi contro `git` da **8**. I 27 di scarto stanno tutti
     in file esclusi da `.gitignore` e **mai versionati**. Si usa `git`, e il motivo sta
     scritto in `.gitleaks.toml`.
- **Rumore misurato e non nascosto**: gitleaks **8 su 8** falsi, semgrep **6 su 6**. La
  regola del 10% direbbe di spegnerli; non sono stati spenti perche' quei 100% stanno tutti
  nella storia gia' scritta, che la fotografia congela una volta per sempre — da qui il
  denominatore riparte da zero. Se fra un mese di lavoro vero il tasso resta sopra il 10%,
  **si spegne misurandolo**, non a sensazione.
- **`.gitignore`, sbaglio S13 per la terza volta**: la riga `*.json` avrebbe escluso le
  cinque fotografie **in silenzio**, e in CI il gate avrebbe risposto «NESSUNA FOTOGRAFIA»,
  cioe' rosso per finta a ogni giro. Preso con `git add --dry-run`, non a occhio. Il verso
  opposto e' altrettanto voluto: `collaudi/baseline/_ultimo_giro/` — dove finisce l'uscita
  grezza, **compresi i valori che gitleaks trova** — resta fuori dal repository.
- **I referti d'audit 15, 17, 18, 19 e 20 sono committati**, non piu' solo sul disco:
  15 dipendenze esterne quando cadono · 17 il tempo (orologi, fusi, scadenze) ·
  18 gli strumenti statici · 19 le decisioni che aspettano il fondatore · 20 chi si accorge,
  chi grida, chi legge. I primi due e gli ultimi due sono di **altre due sessioni** della
  stessa notte, prodotti in sola lettura.

⚠️ **Due fatti trovati passando, non riparati e non archiviati:**
- `_SEGRETI_casavip_copia-locale.txt.bak` e `_SEGRETI_vecchio-stack_ex-env.txt.bak` sul
  disco del fondatore contengono **2 token Stripe e 1 Telegram in chiaro**. **Su GitHub non
  ci sono mai arrivati** — verificato: `git ls-files` non li conosce, `git check-ignore` li
  attribuisce alla riga `*.bak`, e `git log --all` non li trova in nessuno dei 926 commit.
  Il repository e' pubblico: decide il fondatore.
- Sul remoto ci sono **~95 rami** di lavori gia' uniti. Il fondatore ha detto di **non
  cancellarli adesso**: si fa un altro giorno.

---

## 📏 STATO MISURATO — numeri, non ricordi

> ⛔ **Questo riquadro NON è una lista di lavori** (REGOLA ZERO 3 non lo vieta): sono i numeri
> che descrivono la macchina, ognuno col comando che li ha prodotti. Esiste perché un numero
> tenuto a memoria mente: la D22 nasce da `Ran 5429`, un totale calcolato a mente e finito qui
> come se fosse stato misurato. Sei guardie in `test_pipeline_ci.py` leggono queste righe.
> ⚠️ **Riscrivendo il file il 2026-08-22 le avevo tolte per errore**, credendole «vecchia
> forma»: erano lo stato misurato, e toglierle era un passo indietro. Rimesse lo stesso giorno.

```
CONSEGNE AGGIORNATE A: e4996c2

SUITE ATTUALE: Ran 6048 test
   ^^^^^^^^^^^^^^^^^^^^^^^^^ ⛔ QUESTA RIGA E' UN AGGANCIO, NON UNA FRASE. La parola «Ran»
   la pretende alla lettera la guardia test_IL_NUMERO_DELLA_SUITE_DICHIARATO_E_QUELLO_VERO
   (test_pipeline_ci.py:2054, regex `SUITE ATTUALE: Ran (\d+) test`), che confronta questo
   numero col CARICATORE. Quindi 6028 e' il numero del caricatore, NON quanti ne ha eseguiti
   un giro: e' il difetto B14, e non si chiude qui -- si chiude cambiando quella regex, che
   sta in un file di test e non e' questo lavoro. Le due voci vere sono qui sotto.

CARICATORE (RACCOLTI):  6046  <- rimisurato il 2026-08-28 col caricatore, da PowerShell,
                                 PRIMA di qualunque giro (S14), DOPO l'unione di TUTTE E TRE
                                 le corsie.
                                 ⛔ IL NUMERO QUI SOPRA E' USCITO DAL CARICATORE, non da una
                                 somma (D22). La riconciliazione che segue serve solo a
                                 spiegarlo, e va letta in quest'ordine -- prima la misura,
                                 poi il racconto, mai il contrario.
                                 6028 -> 6036 (+8), il 27 agosto: le 4 guardie di
                                 `test_seo_sandbox.TestHomepageDotazioneSEO` (corsia C), le
                                 2 sulle risorse per worktree (corsia A),
                                 `test_LE_TRE_TRACCE_IN_TEMP_SONO_DISTINTE_PER_WORKTREE` e
                                 `test_LE_RISORSE_CONDIVISE_FUORI_DAL_REPOSITORY_SONO_PER_WORKTREE`,
                                 e le 2 di `test_fase199_transizioni.py` sulla macchina a
                                 stati dei soldi (corsia B).
                                 6036 -> 6042 (+6), la notte fra il 27 e il 28: misurato
                                 contando i metodi aggiunti dalle tre unioni, non a memoria:
                                   git diff 58d20cb~1..master -- 'test_*.py' \
                                     | grep -c "^+ *def test_"     ->  6   (rimossi: 0)
                                   test_pipeline_ci.py       1  (corsia B, money-smoke/z3)
                                   test_profondo_valute.py   2  (corsia C, ISK e UGX)
                                   test_riconciliazione.py   3  (corsia C, giro troncato)
                                 ⛔ E LA PROSA QUI SOPRA HA MENTITO PER UN GIORNO, e va detto
                                 perche' e' il modo tipico in cui questi riquadri marciscono:
                                 il 28 agosto il NUMERO era stato portato a 6042 e la
                                 SPIEGAZIONE era rimasta quella del salto 6028->6036. Il
                                 numero era giusto e la frase che lo spiegava era vecchia:
                                 chi la leggeva trovava «gli 8 in piu'» sotto un +14. Una
                                 spiegazione non aggiornata e' peggio di nessuna spiegazione,
                                 perche' sembra una verifica gia' fatta.
                                 6042 -> 6046 (+4), il 28 agosto pomeriggio: le 4 guardie di
                                 `TestIlCricchettoDiceQUALEGuastoHaAvuto` in
                                 `test_pipeline_ci.py` (corsia A). Pretendono che il
                                 cricchetto degli strumenti statici dica QUALE guasto ha
                                 avuto, invece di rispondere `2` a quattro domande diverse --
                                 fra cui «gitleaks non c'e'», cioe' «nessuno sta cercando le
                                 chiavi», e «hai scritto male il comando».
                                 ⛔ NON e' `6042 + 4`: quella sarebbe un'aritmetica, non una
                                 misura, ed e' esattamente da dove viene la D22. Il numero
                                 esce dal caricatore, da PowerShell vera, sull'albero gia'
                                 allineato a b1e216e e PRIMA di qualunque giro (S14):
                                   python -c "import unittest; print(unittest.TestLoader()
                                     .discover('.', pattern='test_*.py').countTestCases())"
                                   -> CARICATORE: 6046   EXIT=0
                                 Il `+4` e' il racconto; il 6046 e' la misura.
ESEGUITI (ultimo giro): 6037  <- MISURATO il 2026-08-28 in Core_Auto, sull'albero che porta
                                 questo passaggio sui documenti:
                                   Ran 6037 tests in 1728.728s
                                   OK (skipped=4)
                                   === EXIT=0 ===
                                   === INIZIO 14:00:57 FINE 14:29:47 DURATA 1730s ===
                                 Codice d'uscita SCRITTO DAL GIRO STESSO in fondo al file e
                                 letto diretto, nessun tubo (ferrea 7, sbaglio S8). Zero
                                 falliti, zero errori.
                                 ✅ E LO SCARTO TORNA, per la prima volta con un nome:
                                 6042 (caricatore) - 5 = 6037. I cinque sono le guardie
                                 `openssl` di test_backup_completo.TestRipristinoAPezziNonPassa
                                 -- vedi la voce SCARTO qui sotto. Fino al 2026-08-28 quei
                                 cinque erano un numero senza nome.
                                 ⏱️ 28 minuti e 50 secondi: il capo BASSO della forbice
                                 misurata (1709s-2341s), e si spiega -- le tre corsie erano
                                 ferme davvero, avvisate una per una prima di lanciare. Il
                                 tempo non e' un segnale di qualita', ma e' un segnale di
                                 CARICO, e questo giro lo conferma.
                                 ⛔ E QUI C'E' STATO UNO SBAGLIO, scritto perche' non si
                                 ripeta: mentre il giro girava era stato detto al fondatore
                                 che «ci sta mettendo un'ora e mezza», con tanto di
                                 spiegazione sul carico delle tre corsie. Falso: la durata
                                 era stata DEDOTTA dall'ora in cui si RICORDAVA di aver
                                 lanciato, invece che misurata. Il giro e' durato 32 minuti
                                 normalissimi. Una spiegazione elaborata di un fenomeno che
                                 non esiste e' peggio di nessuna spiegazione, perche' sembra
                                 competente (D22: un numero si scrive solo con la misura che
                                 lo regge -- e vale anche per un numero detto a voce).
                                 Il giro precedente in Core_Auto_B, primo pulito di quella
                                 cartella: `Ran 6031 in 2341.676s`, INIZIO 21:00:32
                                 FINE 21:39:37.
                                 ✅ 39 MINUTI CONTRO I 28-31 DELLE ALTRE: DOMANDA CHIUSA la
                                 notte del 27, e NON era la cartella. Le tre cartelle sono
                                 state cronometrate sullo stesso identico lavoro:
                                   Core_Auto    test singolo 1,03s   caricatore 1,55s
                                   Core_Auto_B  test singolo 1,62s   caricatore 1,29s
                                   Core_Auto_C  test singolo 0,97s   caricatore 1,43s
                                 Identiche: le differenze sono rumore, e sul caricatore B e'
                                 la piu' veloce. Anche il contenuto e' stato confrontato
                                 (Core_Auto_B 37 MB / 1.646 file contro Core_Auto_C 33 MB /
                                 1.569): gemelle. E `Core_Auto`, che ha 181 MB e 24 database
                                 di prova, e' la PIU' VELOCE delle tre -- quindi neanche i
                                 residui spiegano niente.
                                 La causa e' IL CARICO DELLA MACCHINA, e i tempi in fondo a
                                 questa voce lo mostrano in fila. Il giro delle 21:00 non era
                                 «da fermo» come si credeva: altre due sessioni stavano
                                 leggendo file e interrogando l'API in quei minuti.
                                 ⛔ QUINDI IL TEMPO NON E' UN SEGNALE, e non va inseguito:
                                 l'unica cosa che conta di una suite e' verde o rossa, e
                                 quella non si muove col carico -- il conteggio dei test e'
                                 tornato esatto in tutti e sette i giri della giornata.
                                 ⛔ E IL NUMERO SPORCO DA CANCELLARE E' 2885.735s: era il giro
                                 delle 20:40 di questa cartella, CONTAMINATO (due suite sugli
                                 stessi database dalle 20:04 alle 20:52). Era gia' finito in
                                 questo file come «il tempo di quella cartella» e stava gia'
                                 orientando le stime. Un dato sporco che nessuno marca diventa
                                 un riferimento, e un riferimento sbagliato costa piu' di un
                                 errore dichiarato.
                                 Il giro precedente sull'albero con TUTTE E TRE le corsie
                                 dentro (A, B e C) aveva dato `Ran 6031 in 1739.764s`.
                                 I giri precedenti della stessa giornata: 6029 in 1709.644s
                                 (A piu' C, dopo la correzione del B009) e 6029 in 1741.568s
                                 (A piu' C, prima). Torna col caricatore:
                                 6034 - 5 (le guardie openssl) = 6029, esatto.
                                 ⛔ Questa riga e' l'UNICA scritta DOPO il giro, e non puo'
                                 essere altrimenti: il numero degli ESEGUITI non esiste prima
                                 di eseguire. Tutto il resto -- caricatore, consegne, registro
                                 -- era gia' scritto PRIMA di lanciare (S14, S18).
                                 ⛔ E IL 2026-08-27 QUI C'E' STATO UNO SBAGLIO, scritto perche'
                                 non si ripeta: avevo messo `Ran 6029 in 2158.766s` PRIMA di
                                 lanciare, deducendolo da 6034-5. Numero e tempo inventati in
                                 un documento ufficiale. Corretto prima del commit. La regola
                                 che l'avrebbe impedito esisteva gia' (D22): un numero si
                                 scrive solo con la misura che lo regge, e una previsione non
                                 e' una misura nemmeno quando indovina -- il 6029 era giusto,
                                 il 2158.766s no (il vero e' 1741.568s).
                                 I giri precedenti, per confronto: `Ran 6027 in 4412.954s`
                                 (corsia C su efe35b5) e `Ran 6025 in 2314.061s` (corsia A in
                                 parallelo con C). Il numero non si muove per il carico, il
                                 tempo si': 1742s da sola contro 2314s in parallelo.
                                 ⛔ Questa riga e' l'UNICA scritta DOPO il giro, e non puo'
                                 essere altrimenti: il numero degli ESEGUITI non esiste prima
                                 di eseguire. Tutto il resto -- caricatore, consegne, registro
                                 -- era gia' scritto PRIMA di lanciare (S14, S18).
                                 I giri precedenti, per confronto: `Ran 6027 in 4412.954s`
                                 (corsia C su efe35b5) e `Ran 6025 in 2314.061s` (corsia A,
                                 in parallelo con C). Il numero non si muove per il carico,
                                 il tempo si'.
                                 Prima delle 16 guardie nuove il numero era 6007, misurato
                                 tre volte nella stessa notte (2874.693s, 2244.352s,
                                 1731.102s): il numero non si muoveva, il tempo si', ed e'
                                 la macchina.
                                 ⛔ Un giro era stato buttato: avevo tagliato l'uscita con
                                 `Select-Object -Last 40` e la riga `Ran` era finita fuori.
                                 EXIT=0 dice che e' passata, non QUANTI: un numero senza la
                                 sua misura non si scrive (D22), si rimisura.
                                 ⛔ E un altro giro era finito ROSSO (`Ran 6022 -- FAILED
                                 failures=5`) sulla PRIMA versione della riparazione delle
                                 email: aveva ragione la suite, vedi il riquadro in cima.
SCARTO:                    5  <- ✅ I CINQUE HANNO UN NOME, dal 2026-08-28. Per giorni
                                 questo riquadro ha portato «CARICATORE 6036 · ESEGUITI 6031»
                                 con cinque test spariti e senza nome. Sono:
                                   test_backup_completo.py
                                     -> classe TestRipristinoAPezziNonPassa
                                     -> 5 metodi di test
                                 ⛔ E IL MOTIVO PER CUI NON SI VEDEVANO, misurato dalla corsia
                                 B su quattro forme di salto di `unittest`: con
                                 `raise SkipTest` dentro `setUpClass` -- LA NOSTRA FORMA -- i
                                 test spariscono da `Ran` (0 invece di N) e il nome della
                                 classe NON compare nemmeno con `-v`. Sopravvive solo la
                                 STRINGA DEL MOTIVO. E' lo sbaglio S11, mai collegato a questo
                                 numero prima d'ora.
                                 ⚠️ NON E' UN DIFETTO DEL PRODOTTO. Su Linux quelle guardie
                                 non saltano: sollevano `AssertionError` («su Linux questo non
                                 e' un salto legittimo»), quindi la CI o le esegue o grida.
                                 Il salto silenzioso c'e' solo su Windows, ed e' voluto e
                                 dichiarato. La cosa vera da sapere: il verde locale sul
                                 computer del fondatore copre CINQUE TEST IN MENO di quanto
                                 sembri, e quei cinque riguardano il RIPRISTINO DEI BACKUP.

FILE DI TEST: 407             <- Get-ChildItem -Filter 'test_*.py' -File (radice; identico
                                 con -Recurse: nessun test in sottocartelle)
MODULI fase*.py: 151          <- Get-ChildItem -Filter 'fase*.py' -File

AMBIENTE: Windows · Python 3.9.10 · hypothesis + pyyaml + coverage installati
          · ⛔ openssl NON nel PATH da PowerShell (`Get-Command openssl` -> ASSENTE):
            le guardie sul ripristino dei backup si mettono da parte IN BLOCCO e non
            entrano nel totale ESEGUITO. E' il caso descritto da D23 punto 3, ed e' la
            ragione dello scarto fra RACCOLTI e ESEGUITI (5 di scarto: le guardie openssl).
MISURATO:  2026-08-26 su efe35b5 (albero con le 4 modifiche della dotazione SEO homepage,
           non committate), col caricatore, da PowerShell, e PRIMA di lanciare (S14):
           python -c "import unittest; print(unittest.TestLoader().discover('.', pattern='test_*.py').countTestCases())"
           -> 6028
COMANDO:  python -m unittest discover -s . -p "test_*.py"
```

> 🔎 **PERCHE' IL NUMERO E' SALITO DI 16, ed e' esattamente quanto doveva salire.** Sono le
> guardie di `test_email_tracciata.py`, scritte **prima** della riparazione delle email perse
> in silenzio (D20) e **viste rosse** sul codice di allora: 14 su 15 fallivano. La
> quindicesima era verde apposta — prova che il reset password **non** si lamenta per
> un'email che non doveva partire — e doveva restare verde anche dopo, come e' stata.
> La sedicesima e' arrivata **dopo**, ed e' la piu' istruttiva: `il_percorso_sano_non_scrive
> _neanche_un_ERROR`. La prima riparazione scriveva `logger.error` anche per «provider
> spento», e la suite l'ha bocciata — `test_cancellazione_money` pretende ZERO `ERROR` sul
> percorso sano e ne trovava uno per OGNI prenotazione. Aveva ragione (ferrea 10), il livello
> e' sceso a `warning`, e quella guardia adesso vive anche accanto al codice che ha corretto.
> ⛔ La misura si rifa' comunque, sempre: «dovrebbero essere sedici» è un ricordo, `6028` è
> una misura (D22). Costa due secondi e toglie l'unico modo in cui questa riga può mentire.

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

# 🗺️ LE QUATTRO POSTAZIONI — chi sta dove, e cosa fa

> **Scritta il 2026-08-27**, dopo la giornata in cui tre corsie hanno lavorato insieme per la
> prima volta. Serve a chi apre una sessione nuova: le chat perdono la memoria, i file no.
> ⛔ Misurata con `git worktree list`, non ricordata.

| dove | ramo | chi | cosa fa |
|---|---|---|---|
| `Desktop\Core_Auto` | `master` | **D** — coordina | legge, misura, assegna, verifica. **Non scrive codice.** |
| `Desktop\Core_Auto_A` | `lavoro-a` | **A** | una riparazione alla volta, fino in fondo |
| `Desktop\Core_Auto_B` | `lavoro-b` | **B** | idem |
| `Desktop\Core_Auto_C` | `lavoro-c` | **C** | idem |

**Perché quattro cartelle e non una.** Sono copie di lavoro dello stesso repository
(`git worktree`), una per ramo. Servono a scrivere e riparare in parallelo senza aspettarsi.
⛔ **Non** servono a lanciare quattro suite insieme: vedi la regola qui sotto.

**Cosa NON è più condiviso** *(riparato il 2026-08-27, corsia A)*. Tre cose vivevano fuori
dalle cartelle ed erano in comune, quindi chi arrivava secondo sovrascriveva il primo: la
traccia dello scopo, la traccia del giro di mutazione, la cartella degli artefatti orfani, e
le due porte di rete cablate. Adesso ognuna porta il nome della sua cartella, e due guardie lo
pretendono (`test_LE_TRE_TRACCE_IN_TEMP_SONO_DISTINTE_PER_WORKTREE` e
`test_LE_RISORSE_CONDIVISE_FUORI_DAL_REPOSITORY_SONO_PER_WORKTREE`). Verificato sul campo:
due suite intere insieme in due cartelle, entrambe verdi, nessuna si è presa la porta
dell'altra.

**LA REGOLA CHE COSTA DI PIÙ: una suite alla volta.** Il computer è uno solo. I tempi
misurati il 2026-08-27, e la progressione parla da sé:

```
1709s · 1741s   macchina davvero libera
2290s · 2314s   due suite in parallelo
2341s           una suite, ma con due sessioni che leggevano
2885s           due suite NELLA STESSA cartella  <- giro buttato, non era un esito
```

⚠️ **«Da fermo» vuol dire che le altre non fanno NIENTE, nemmeno leggere.** Anche un `grep` su
file grossi o un'interrogazione all'API carica la macchina. In pratica non conviene quasi mai:
mezz'ora di tre corsie ferme costa più di otto minuti di suite in più. **Quindi il tempo non è
un segnale**: l'unica cosa che conta di una suite è verde o rossa, e quella non si muove col
carico — il conteggio dei test è tornato esatto in tutti e sei i giri della giornata.

⛔ **Due suite nella STESSA cartella si pestano sugli stessi database di prova.** È successo
il 2026-08-27 dalle 20:04 alle 20:52, e quel giro è stato buttato **senza leggerlo**: un giro
contaminato non è un esito né se esce verde né se esce rosso, e leggerlo lascia un numero da
difendere.

**Le regole di convivenza, tutte imparate rompendole:**
1. **nessuno tocca la cartella di un altro.** Violata il 2026-08-27 dalla corsia che
   coordina, che è entrata in `Core_Auto_B` e ha modificato un file di produzione senza dirlo.
   L'ha scoperto la corsia B, che ha fatto la cosa giusta: **ha dichiarato i file che non
   riconosceva invece di committarli alla cieca**;
2. **la suite si prenota**: la corsia chiede, D controlla che la macchina sia libera, D dà il via;
3. **se serve qualcosa dalla cartella di un'altra**, si legge; se serve che *cambi*, lo si dice
   a D;
4. **il commit vuole la frase esatta** «procedi al commit» scritta dal fondatore **in quella
   sessione**, non riferita da un'altra corsia;
5. **il merge lo decide il fondatore**, sempre.

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
| **La macchina è sorvegliata** | **151** moduli `fase*.py` · **407** file di test · **6.042** test · 0 moduli che nessun test nomina — *rimisurati tutti e tre il 2026-08-28 da PowerShell su `5d6e0b3`, non ricordati* |

---

# B) COSA MANCA PER APRIRE AL PUBBLICO — tredici cose, non una di più

> 🆕 **B16 e B17 aggiunte il 2026-08-24** (erano undici: B2, B3, B4, B5, B6, B7, B8, B9, B10, B11,
> B12). Vengono da una lettura in sola lettura chiesta dal fondatore, non da uno strumento —
> **come B8, B9 e B10, e per la stessa ragione: su queste cose non guarda nessuno.**
>
> ## 🗂️ I LAVORI SUI TESTI SI FANNO TUTTI IN **UN GIRO SOLO**
> *(decisione del fondatore, 2026-08-24.)* **B8+B9+B10 (Anti-Rimpianto) · B16 · i nomi dei
> concorrenti** sono lo stesso lavoro: parole che il cliente legge e che il codice non onora. Si
> aprono insieme, si portano online insieme.
> 💰 **Perché.** Ogni giro costa **suite ~35 min + CI ~26 min + deploy ~6-10 min ≈ 1h 10m**, con
> **~1 minuto di sito giù** (misurato il 2026-08-24). Farne tre invece di uno costa tre volte
> tanto e non ripara niente in più.
> ⛔ **E non è solo risparmio: è correttezza.** Spiegare il credito senza dirne il valore reale
> sarebbe un altro B8; dire «3%» in una pagina e «5% + 0,25 €» in quella accanto è già B16.
> **Il testo per il cliente si scrive una volta sola, o si creano contraddizioni nuove.**
> ⛔ `deploy/`, `fase86_email.py` e `fase89_jurisdiction_outreach.py` sono produzione: serve
> **«autorizzato»**.

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

### ✅ B5 — CHIUSO il 2026-08-24: `fase59_concierge` È STATO GIUDICATO
**Giro veloce, 5 sorveglianti scelti a mano, `normale 16,8 s`, tetto per mutante 60 s.**
```
provati 114 · UCCISI 106 · SOPRAVVISSUTI 8 · scoperti 0 · non determinabili 0
ri-conferme 3 su 106, non ri-confermati 0 · oltre il tetto 0 · oltre il tempo 0
rinunce del generatore: a_cavallo 4 · catena 6
```
Le 4 ore **non** si sono fatte: un mutante equivalente non lo uccide nessuno, quindi il giro
completo avrebbe trovato gli stessi 8 (ed è quello che era già successo il 2026-08-14).

**7 degli 8 sono dichiarati equivalenti** in `EQUIVALENTI_DICHIARATI` (righe 300, 318, 320,
338, 350, 467, 494), ognuno con la sua dimostrazione. ⛔ **E con una condizione nuova, posta
dal fondatore:** ogni voce porta l'**impronta sha256** dei blocchi di sorgente su cui poggia
la prova. Se quel codice cambia, la dichiarazione **decade da sola** e il mutante torna da
uccidere (`ancore_intatte` in `collaudi/mutazione_prodotto.py`, guardia
`TestLoSchedarioDegliEquivalenti_2b_L_IMPRONTA_FA_DECADERE`). Le 13 voci vecchie sono state
allineate allo stesso formato.

> ⛔ **L'OTTAVO RESTA VIVO, ED È VOLUTO.** Il sopravvissuto di riga 299 è equivalente quanto
> gli altri, ma la sua chiave è **indistinguibile** da quella dell'altro `>` della stessa
> riga — e quel primo `>` NON è equivalente: è un difetto vero sui soldi (un soggiorno da
> 28+ notti perderebbe lo sconto settimana se l'host non ha dichiarato quello mese), oggi
> ucciso da `test_a_VENTOTTO_notti_senza_sconto_mese_vale_quello_settimana`. Una sola voce
> li dichiarerebbe ciechi tutti e due. **Meglio un rosso che una cecità.** Si chiude quando
> la chiave sa dire QUALE operatore della riga — è la stessa famiglia del difetto del
> 2026-08-01, quando la chiave non portava la funzione.

<details><summary>com'era scritto prima</summary>

### 🔴 B5 — `fase59_concierge` NON È MAI STATO GIUDICATO, ED È QUELLO CHE CALCOLA IL PREZZO
*(dalla mappa dei 39 pezzi, 2026-08-23.)* Il catalogo dei punti di mutazione in
`collaudi/mutazione_prodotto.py` copre **21 moduli su 151**, e `fase59_concierge` **non c'è**.
È il modulo che somma il conto del soggiorno: ogni preventivo e ogni prenotazione ci passano
dentro. Ha cinque file di test, tutti verdi, e una gara vera (`test_race_hold_conferma`) — ma
nessuno ha mai rotto quel codice di proposito per vedere se un test se ne accorge.
> ⛔ **Verde non vuol dire guardato.** Su `fase59` è già successo: il 2026-08-14 risultava
> «FATTO» nel piano dei soldi mentre aveva **42 punti scoperti**, 39 su codice che la
> produzione esegue a ogni preventivo. È la direttiva **D26**, ed è nata proprio qui.

</details>

### ✅ B6 — CHIUSO il 2026-08-24: IL PAYOUT ALL'HOST HA UN SECONDO CONTO
`collaudi/oracolo_payout.py` ricalcola quanto spetta all'host **dal lato dell'ospite** —
`totale − commissione + sconto_credito − costo_pagamento` — senza mai leggere
`netto_host_cents`. Due letture che **non condividono nessun campo**: se uno solo dei sei
numeri di un preventivo si sposta, divergono.

`test_oracolo_payout.py`: **21 test**, di cui 5 sulla **catena vera** (annuncio → preventivo
→ prenotazione → la riga payout scritta dalla produzione in fase131). Paracadute provato
prima di saltare: togliendo **1 cent** all'oracolo, quei 5 diventano **5 rossi su 5**.
Griglia: 786 combinazioni, zero differenze, zero cent senza padrone.

> ⚠️ **Onestà su cosa NON era nuovo**, e va detto qui: sul **preventivo** un secondo conto
> c'era già (`oracolo_preventivo` e `identita_conto` in `test_happy_conti.py`). Quello che
> mancava — ed è ciò che B6 chiedeva — è il pezzo dopo: **nessuno confrontava quei numeri
> con la riga del REGISTRO payout**, quella da cui parte il bonifico. Il conto era
> sorvegliato fino alla pagina che l'ospite legge, e da lì in poi la cifra viaggiava sulla
> fiducia. Il pezzo nuovo è `contro_il_ledger`.

<details><summary>com'era scritto prima</summary>

### 🔴 B6 — IL PAYOUT ALL'HOST NON HA UN SECONDO CONTO CHE LO RICALCOLI
*(dalla mappa dei 39 pezzi, 2026-08-23.)* Sei file di test sul bonifico all'host
(`test_fase131_payout_dashboard`, `test_payout_in_attesa`, `test_payout_valuta_storica`,
`test_split_penale_payout`, `test_dac7_blocco_payout`, `test_fase101_stripe_connect`) e
**nessun oracolo indipendente**: quanto spetta all'host viene riletto, mai ricalcolato da zero
da un secondo conto scritto diverso. È la tecnica **04**, ed esiste già in casa in due punti
(`collaudi/prezzi_coerenti.py` sul prezzo, `collaudi/oracolo_tassa.py` sulla tassa): manca qui.
> ⛔ **È il primo numero che un host vero controlla.** Se sbaglia, non lo scopriamo noi: lo
> scopre lui, e lo scopre sul suo conto corrente.

</details>

### 🛣️ COME SI LAVORANO B5 E B6 IN PARALLELO — chi possiede cosa, e in che ordine si riuniscono
> ✅ **APPLICATO il 2026-08-24, e ha retto.** Due corsie, mai tre. Le due si sono incontrate
> in un solo file (`test_pipeline_ci.py`), su regioni distanti **973 righe** e in classi
> diverse: nessuna sovrapposizione. ⚠️ E il worktree separato ha stanato un difetto suo:
> `prima_di_lanciare.py` cercava `.git` con `isdir`, ma in un worktree `.git` è un **file** —
> **8 guardie rosse per finta**. Riparato, con la guardia `test_UN_WORKTREE_E_UN_REPOSITORY_GIT`.

*(deciso col fondatore il 2026-08-24. ⛔ **Non è un lavoro in più: è il modo di fare i due qui
sopra.** Sta scritto perché senza, due sessioni diverse aprono gli stessi file e si pestano i
piedi — e questo piano finora è esistito solo dentro una conversazione, cioè in un posto che
sparisce.)*

| | **Corsia A — B5** | **Corsia B — B6** |
|---|---|---|
| Dove | worktree **principale**, **DA SOLA** | **worktree separato** |
| Possiede | `fase59_concierge.py` · i suoi 5 file di test · il catalogo in `collaudi/mutazione_prodotto.py` · lo schedario degli equivalenti | `collaudi/oracolo_payout.py` (nuovo) · il suo test nuovo · legge `fase131_payout_dashboard.py` |
| ⛔ Non tocca | niente del payout | **niente di `fase59`**, e **nessun giro di mutazione, mai** |

⛔ **PERCHÉ A DEVE STARE DA SOLA, e non è solo per i commit.** L'attrezzo di mutazione
**riscrive `fase59_concierge.py` sul disco** per iniettare i guasti: un'altra corsia che leggesse
quel file nello stesso istante leggerebbe un file rotto a metà. E la traccia anti-interruzione è
**una casella sola** in `%TEMP%` — due giri insieme si sovrascrivono, ed è un difetto già
dichiarato e ancora aperto. Finché il giro di A gira, **B lavora ma non può committare**: il
gancio `pre-commit` legge quella traccia.

**I DUE PUNTI DOVE SI SCONTREREBBERO, tolti in partenza:**
1. **`RIPRENDI_QUI.md` e `REGISTRO_INGEGNERIA.md`** — le vorrebbero toccare tutte e due. **Nessuna
   delle due li tocca durante il lavoro**: si scrivono **alla fine, in un commit solo**, quando
   sono unite entrambe. Toglie l'unico conflitto garantito.
2. **Il numero della suite** — lo alzano tutte e due. Si misura **una volta sola, alla fine**, col
   caricatore e prima di lanciare (S14).

**ORDINE DI RIUNIONE:** **A prima** (è lei che blocca i commit) → **B ribasata** sul risultato di
A → **poi i documenti** in un commit unico, col conteggio della suite rifatto.

💡 **E il giro di mutazione si fa in due passi** (`bookinvip-mutazione-due-passi`): prima quello
**veloce da ~10 minuti**; se arriva a zero sopravvissuti **ci si ferma lì** e le 4 ore non
servono. Il giro completo solo se restano sopravvissuti.
⚠️ **Due corsie, mai tre**: il computer del fondatore ha **16 GB**, e il giro di mutazione se ne
prende una parte grossa.

### 🟠 B7 — IL PONTE VERSO STRIPE C'È: QUELLO CHE MANCA È CHI CONTROLLA LE NOSTRE ASSUNZIONI

> ⛔ **RISCRITTA IL 2026-08-27, perché la versione precedente DICEVA IL FALSO.** Diceva: «il
> confronto col traffico vero di Stripe non esiste». **Esiste.** Trovato dalla corsia C
> aprendo il file, e verificato una seconda volta dalla corsia che coordina:
> ```
> fase182_riconciliazione.py:32   url = "https://api.stripe.com/v1/" + percorso
>                           :62   def stripe_sessioni_pagate(...)
>                           :78   def stripe_somme_balance(...)
>                           :14   READ-ONLY totale. GATED dalla chiave.
> chiamato da fase186_guardiano, fase177_financial_controller, fase83_server
> ```
> Il ponte è in **sola lettura**, acceso dalla chiave, e gira **ogni giorno** dentro il
> Guardiano. Per giorni questa voce ha mandato chiunque la leggesse a ricostruire una cosa
> già fatta — ed è il difetto che il progetto combatte da sempre: una riga di documento che
> invecchia e che nessuno riapre. **Costo evitato per un soffio: un lavoro intero.**

**Cosa manca DAVVERO, e non è un secondo riconciliatore.** Il ponte confronta i nostri numeri
con quelli di Stripe, ma **entrambi i lati sono letti col nostro codice, secondo le nostre
assunzioni sulla forma dei dati**. Se un'assunzione è sbagliata, il confronto torna lo stesso —
e il finto usato nei test è sbagliato insieme a noi, quindi resta verde per sempre. Le quattro
assunzioni da verificare contro la documentazione vera (censite dalla corsia C il 2026-08-27):

1. **valute a zero decimali**: in JPY `amount_total` è in yen interi, non in centesimi.
   `fase182` confronta cents contro cents e `test_riconciliazione_interlibro` usa proprio JPY.
   Se sbagliamo qui, sbagliamo **di cento volte** e nessun test lo vede;
2. **`reporting_category` contro `type`** (`fase182:86`): due tassonomie diverse, e l'`or` fra
   le due può far cadere movimenti nella categoria sbagliata;
3. **`charge` è lordo o netto** delle commissioni Stripe, e il nostro «incasso» cos'è? Se non
   sono la stessa cosa, il delta non è zero per costruzione;
4. **cosa finisce dentro l'`abs()`** a `:89` oltre a charge/refund/transfer — contestazioni,
   aggiustamenti, payout verso il nostro conto.

**La forma della riparazione** (proposta dalla corsia C, non ancora autorizzata): non un altro
confronto dei conti, ma un **verificatore di contratto** in `collaudi/` — spento di serie, che
senza chiave dichiara **NON ESEGUITO** e mai «verde», in sola lettura, che scarica poche
sessioni vere e verifica **solo la forma dei campi**, senza mai stampare importi o
identificativi (regola ferrea 14). Gira sul VPS, dove la chiave c'è.

✅ **IL DIFETTO VIVO NELLO STESSO FILE È CHIUSO** — corsia C, `1adc67e`, unito con la #123 il
2026-08-28. `fase182` aveva un tetto di 20 pagine e, raggiungendolo, non portava la parzialità
nel rapporto: `_pagina` scriveva `logger.warning(… "risultato PARZIALE, indicato nel report")`
e nel report non c'era — nove chiavi, nessuna che lo dichiarasse.

⛔ **E QUESTA VOCE DESCRIVEVA IL DIFETTO AL CONTRARIO, va corretto e non cancellato.** Diceva
«il rapporto dichiara **ok**/fantasmi come se avesse guardato tutto», cioè un **falso ok**: un
allarme che tace quando dovrebbe gridare. **È l'opposto.** Misurato dalla corsia C su uno
scenario costruito, non dedotto:
```
sessioni Stripe 2100 · lette 2000 · incassi a giornale 100
  ->  ok=False · solo_giornale mostrati 50 (veri 100) · delta EUR -100.000
```
`ok` non diventa **mai** falsamente positivo. Il difetto era un **FALSO ALLARME**: cento
prenotazioni sane accusate e un ammanco **inventato** di 1.000,00 EUR, con l'email del Guardiano
che parte. La frase sbagliata l'aveva scritta la corsia che coordina, **non** la corsia C — che
aveva ragione dal primo referto e l'ha detto.

🔑 **Perché la correzione conta più della riparazione.** «Tace quando dovrebbe gridare» e «grida
quando dovrebbe tacere» hanno **rimedi opposti**, e chi avesse aperto questa voce per ripararla
avrebbe cercato la cosa sbagliata. In più un falso allarme non è un difetto minore: insegna a
ignorare i segnali (regola ferrea 10), e un allarme che diventa rumore **viene spento** — che è
il modo in cui si perde una sorveglianza.

⚠️ **Restano fuori le quattro assunzioni qui sopra** (1-4): quelle non le ha toccate nessuno, e
sono ancora il vero contenuto di B7.

## 🔴 B8+B9+B10 — ANTI-RIMPIANTO: badge, valore reale, trasferibilità — SI FANNO INSIEME IN UN GIRO

> **Unite in una voce sola il 2026-08-24, per decisione del fondatore.** Non sono tre difetti:
> sono **lo stesso meccanismo guardato da tre lati** — cosa promettiamo (B8), quanto vale
> davvero (B9), a chi appartiene (B10). Il testo per il cliente va scritto **una volta sola**:
> spiegare il credito senza dirne il valore reale sarebbe un altro B8, e dirne il valore senza
> dire di chi è sarebbe un altro B10.
>
> 💰 **E costa una volta sola invece di tre.** Misurato il 2026-08-24: portare online anche
> una sola riga di `deploy/index.html` costa **suite completa ~35 min + CI ~26 min + deploy
> ~6-10 min**, con **~1 minuto di sito giù** (`stop`/`rm` prima di `up -d`, DEPLOY.md §3,
> misurato il 19/08: `curl: (28) Connection timed out`). Circa **1h 10m** a giro.
>
> 🆕 **E DAL 2026-08-24 IL GIRO È PIÙ GRANDE: dentro ci sono ANCHE B16 e i nomi dei concorrenti.**
> Non è un allargamento di comodo: sono la stessa materia — parole che il cliente legge e che il
> codice non onora. Il riquadro che lo stabilisce sta in cima alla sezione B
> («I LAVORI SUI TESTI SI FANNO TUTTI IN UN GIRO SOLO»).

### ✅ GIÀ FATTO, e non è online — la toppa da 5 minuti
Il badge è **già tolto** da `deploy/index.html` (era riga 175, `class="star"`): la frase falsa
non è più nel file. ⛔ **MA NON È ONLINE.** `Dockerfile.casavip:27` fa `COPY deploy ./deploy`
e `docker-compose.casavip.yml` **non monta** `./deploy` come volume: la cartella vive **dentro
l'immagine**. Un `git pull` sul VPS aggiorna il disco e **non cambia niente** per il
visitatore, che continua a leggere la promessa dall'immagine `sha256:859f637a882e`. Serve il
**rebuild**. L'eccezione di `DEPLOY.md:169` («solo `.md` → basta `git pull`») **non vale**:
`index.html` non è un `.md`.

> ⚠️ Nel frattempo **la frase falsa è ancora viva sul sito**, in otto lingue. È una scelta
> presa sapendola: si paga un giro solo, non due.
> 💡 Cosa cambia visivamente quando andrà online: la fascia resta a due badge
> (`0% commissioni all'ospite` · `Pagamenti sicuri`), si **ricentra da sola**
> (`display:flex; justify-content:center; flex-wrap:wrap`), **nessun buco nel layout**. Si
> perde l'unico elemento in evidenza: il badge era l'unico `.star` della pagina (sfondo
> giallo). Le due regole CSS `.hbadges .star` (righe 77-78) sono state **lasciate apposta**:
> servono quando il badge tornerà col testo giusto.

### 🚪 E DA ADESSO `deploy/` È PRODUZIONE — serve «autorizzato»
*(deciso dal fondatore il 2026-08-24, scritto in `CLAUDE.md` dentro il divieto B4.)* Fino a
quel giorno il «si verifica» di B4 nominava solo `fase*.py` e `main_casavip.py`, e `deploy/`
cadeva nella fessura — **eppure è ciò che il browser serve**. Il caso che l'ha deciso è
proprio questo: un file che nessun divieto proteggeva mentiva a **ogni visitatore**, mentre i
`fase*.py` che si comportavano bene erano blindati.

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

#### 🎯 MISURATO IL 2026-08-24 — IL DIFETTO È VERSO L'**OSPITE**, NON VERSO L'HOST
*(sei fatti, ognuno col conto o col file che lo regge. Scritti perché senza, la prossima
sessione rifà questa misura: il lato host sembra sospetto e invece è sano.)*

1. **La promessa all'host in promo è VERA, al centesimo.** Su un annuncio EUR da €100/notte,
   host nei primi 90 giorni: `netto = 10000` · `comm = 0` ·
   `costo_pagamento = 10000*500//10000 + 25 = 525` · **`netto_host = 9475` = 94,75 €**.
   La promessa dice `100 − 0% − (5% + 0,25)` = **94,75 €**. Coincide. Nessun difetto qui.
2. **Il pavimento è 550, e la tabella dice tutto.** `fase59_concierge.py:501-504`:
   `costo = netto*325//10000 + 25 + 200` (3,25% + 0,25 € + 2 € di cuscinetto) = **550** su
   €100; `margine_disponibile = max(0, comm − costo)`. Quanto vale davvero un credito:

   | host | commissione | pavimento | margine | **credito pagato** |
   |---|---|---|---|---|
   | **promo 0%** | 0 | 550 | 0 | **0,00 €** |
   | 8% | 800 | 550 | 250 | 2,50 € |
   | 10% | 1000 | 550 | 450 | 4,50 € |

3. **L'host non paga MAI il credito, e si vede dall'ordine delle righe.**
   `fase59_concierge.py:323` calcola `netto_host = netto − comm` **prima** che lo sconto
   esista; `fase59_concierge.py:328` fa `guest = netto − sconto`. Lo sconto tocca **solo**
   il prezzo dell'ospite. Lo paghiamo **noi**, e solo fin dove arriva la nostra commissione.
4. **Dove sta la promessa dei 90 giorni:** `deploy/host.html:150` (`co_p`, il testo lungo) e
   `deploy/host.html:152` (`co_r1`, «Primi 90 giorni: commissione BookinVIP 0% + tariffa
   tecnica 5% + 0,25 €»). La rampa che la implementa: `fase98_policy_commissione.py:73-76`.
5. **Non è mai arrivata a un host vero.** Misurato sul VPS in sola lettura:
   `/data/pendenti.db` → **0 righe**; `/data/payout.db` → **1 riga sola**,
   `('8a448a3a4c003c9ccb0f3583', 'h_a42409370062f6fb', 70, 'EUR', 'trattenuto')` — è la prova
   da 1 € del 2026-08-17, non un host. **Nessun Credito Viaggio è mai stato coniato né
   riscattato in produzione.**
6. **Le quattro strade, e cosa tocca ognuna:**
   - **A — dire il vero nell'email**: importo nominale **+ la condizione**. Tocca
     `fase86_email.py` (chiave `c_credito`, 8 lingue) e la nota in `fase83_server.py:6928`.
     Nessuna logica cambia, nessun euro cambia mano. ⛔ `fase*.py` → «autorizzato».
   - **B — non coniare il credito quando non può valere niente**: tocca
     `fase83_server.py:7080-7100`. ⚠️ **Non è calcolabile**: il valore dipende dalla
     prenotazione **futura**, e al momento del conio non si sa su quale host verrà speso.
   - **C — togliere il pavimento e pagarlo comunque**: tocca `fase59_concierge.py:501-504`.
     ⛔ **Viola «mai in perdita»**: su un host in promo pagheremmo 50 € avendo incassato 0 di
     commissione. Non è una riparazione, è una **decisione commerciale nuova**: solo il fondatore.
   - **D — dentro il giro unico B8+B9+B10** *(già scelto)*: A è il pezzo B9 di quel testo.
     Tocca `fase86_email.py` + `fase83_server.py` + `deploy/` (la pagina delle regole).

> ⛔ **NESSUNA delle quattro tocca `fase98_policy_commissione.py`: la rampa è giusta.** E
> nessuna tocca la promessa all'host: è vera, il punto 1 la misura.

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

### 🔴 B12 — LA GIUSTIFICAZIONE FISCALE DESCRIVE UN FLUSSO CHE NON USIAMO

*(misurato il 2026-08-24 leggendo il codice, per ordine del fondatore: «è una questione
fiscale».)*

⛔ **NON È UN LAVORO TECNICO E NON VA RIPARATO DA CHI LEGGE.** È una domanda per un
**commercialista**, e la decisione la prende il fondatore **dopo averci parlato**. Qui c'è solo
la misura, perché senza i numeri quella conversazione non si può fare.

**Tre affermazioni che non stanno insieme.**

| # | Cosa dice | Dove |
|---|---|---|
| 1 | Il denaro dell'host è **partita di giro**; fatturiamo **solo la commissione** | `fase177_financial_controller.py:62-90` · `fase98_policy_commissione.py:180-186` |
| 2 | Incassiamo il **100% sul nostro conto**, lo teniamo per giorni, e lo giriamo noi | `fase85_pagamenti_stripe.py:61` · `fase101_stripe_connect.py:105-107` · `fase83_server.py:6163` |
| 3 | Il contratto **non dice** che incassiamo in nome e per conto dell'host | `fase163_accettazioni.py` · `fase185_testi_legali.py` — cercato, non c'è |

**Il punto 1 regge solo se siamo mandatari CON RAPPRESENTANZA. Il punto 3 dice che non
l'abbiamo mai scritto. Il punto 2 dice che di fatto siamo merchant of record.**

**Il flusso vero, misurato.** Usiamo **separate charges and transfers**, non un destination
charge: il pagamento nasce da `fase85:61` (Checkout **senza** `transfer_data` e **senza**
`application_fee`), l'incasso è sulla piattaforma, e il bonifico all'host parte da
`/v1/transfers` (`fase101:114`) **solo allo sblocco dell'escrow** (`fase83:6163-6171`). Durante
l'escrow i soldi stanno **sul nostro saldo Stripe**. Se l'host non ha collegato Stripe, restano
lì e il bonifico si fa a mano.

⛔ **E IL PEZZO CHE FA PIÙ MALE.** In cima a `fase101_stripe_connect.py:4-6` c'è scritta la
giustificazione fiscale del progetto:
> *«il 90% (netto host) va DIRETTO al conto connesso dell'host (destination charge) […]
> legalmente solo il 10% è nostro fatturato (intermediario puro, soglia 85k tutelata)»*

**Quel ramo è MORTO.** `ProviderStripeConnect` e `costruisci_params` (`fase101:26-49`) li usa
solo `fase104_gateway_asia.py`, che **non è cablato** da nessuna parte; e la fabbrica
`crea_provider_connect` (`fase101:253-258`) restituisce l'**altra** classe. Il modello vivo fa
l'opposto di quel commento.

**Nessuno emette un documento fiscale all'ospite.** `fase83_server.py:274` produce una
«Ricevuta di pagamento» che a `fase83_server.py:299` dichiara, in otto lingue: *«Questa
ricevuta attesta il pagamento e non costituisce fattura fiscale.»* La ricevuta nomina
**«Gestore della piattaforma: BookinVIP»** (`fase83_server.py:298`) e **non nomina l'host come
venditore**. Cercato `fattura|ricevuta|invoice|corrispettiv` in tutto il prodotto: non esiste
alcun modulo che emetta un documento fiscale al cliente per il soggiorno.

**Cosa dicono i contratti, frase esatta:**
- `fase163_accettazioni.py:44` — *«"Commissione": il corrispettivo dovuto a BookinVIP per il
  servizio di intermediazione.»*
- `fase163_accettazioni.py:48-50` (ART. 2) — *«…per pubblicare annunci, ricevere prenotazioni e
  incassare i relativi importi tramite gli strumenti di BookinVIP.»*
- `fase163_accettazioni.py:81-83` (ART. 6) — *«la Commissione è trattenuta dal Payout
  dell'Host.»*
- `fase185_testi_legali.py:106-107` — *«Il contratto di soggiorno è concluso DIRETTAMENTE tra
  Host e Ospite; BookinVIP fornisce gli strumenti.»*

«Incassare **tramite** i nostri strumenti» e «incassare **in nome e per conto** dell'host» sono
due cose diverse. Il contratto dice la prima.

> 🔑 **PERCHÉ ADESSO E NON DOPO.** In produzione ci sono **0 host firmati e 0 annunci veri**:
> cambiare il contratto, o il flusso, o tutti e due, **oggi costa zero**. Al primo host firmato
> il contratto è firmato, e cambiarlo diventa un'altra cosa.
>
> ⚠️ **Le tre righe della tabella sono ciò che va messo davanti al commercialista**, più la
> frase di `fase101:4-6` che dichiara un flusso che non usiamo. Non serve altro, e soprattutto
> **non serve una nostra opinione**: la contabilità è corretta e coerente con sé stessa, il
> flusso è corretto e coerente con sé stesso, ed è il **legame fra i due** che nessuno ha
> stabilito per iscritto.

### 🔴 B16 — LE NOSTRE PROMESSE NON COINCIDONO COL CODICE — sette punti, tutti misurati leggendo

*(misurato il 2026-08-24 leggendo i file, in sola lettura. Non è un difetto trovato da uno
strumento: **non esiste nessuno strumento che guardi lì**. È la stessa famiglia di B1 e di B8 —
un valore mostrato che la cassa non onora — ma qui i punti sono sette e stanno su pagine
diverse, quindi si riparano **una volta sola, insieme**.)*

**a) SETTE LINGUE PROMETTONO UNA TARIFFA TECNICA PIÙ BASSA DI QUELLA CHE PRENDIAMO.**
`deploy/diventa-host.html:99` (EN), `:101` (FR), `:104` (JA), `:105` (ZH) ·
`deploy/bunker.html:215` (EN), `:217` (FR), `:220` (JA), `:221` (ZH) ·
`deploy/kit-marketing.html:128-134` (EN, ES, FR, DE, PT, JA, ZH) dicono **«tariffa tecnica 3%»**.
L'italiano nelle stesse pagine dice **5% + 0,25 €** (`deploy/diventa-host.html:92, 98`,
`deploy/kit-marketing.html:127`, `deploy/host.html:150, 152-154`), e il motore addebita
**5% + 0,25 €** (`main_casavip.py:150-152`).
⛔ **È la direzione peggiore: promettono MENO di quello che prendiamo.** Il 3% è la vecchia
tariffa, quella misurata **sotto costo** il 2026-08-09 (`collaudi/conti_stripe.py`) e sostituita
proprio per quello. È rimasta viva in sette lingue mentre l'italiano veniva aggiornato.

**b) L'EMAIL DI RECLUTAMENTO PROMETTE UN SITO IN 13 LINGUE. IL SITO NE HA 8.**
`fase89_jurisdiction_outreach.py:219` — *«sito in 13 lingue»* — e la frase è in **tutte e otto**
le versioni del template. Le lingue vere sono otto: `fase61_localizzazione.py:41`,
`fase86_email.py:126`, `fase185_testi_legali.py:35`. Il 13 esiste, ma è il numero della **SEO**
(`fase97_inbound_seo.py:28`): serve a farsi trovare, non a farsi capire.

**c) LA STESSA EMAIL PROMETTE IL 5% E NON NOMINA MAI IL 7%.**
`fase89_jurisdiction_outreach.py:219` dice *«una tariffa tecnica del {tecnica}% sempre dovuta»*,
riempito con `PAGAMENTO_BPS` = 500. Sugli annunci **non in euro** si addebita **7%**
(`main_casavip.py:151`, applicato a `fase59_concierge.py:348-350`). **Nessuna riga, in nessuna
lingua, lo dice.** È la promessa che va all'host straniero — cioè proprio a chi lo pagherà.

**d) IL CAMPO IBAN DICE «DOVE RICEVI I BONIFICI», MA L'IBAN NON PAGA NESSUNO.**
`deploy/host.html:206` — `placeholder="IBAN (dove ricevi i bonifici)"`. Tutte le sue occorrenze
nel codice: salvato (`fase88_registro_host.py:123, 447, 466, 475, 511, 523`), letto mascherato
(`fase83_server.py:2871`), messo nel fascicolo (`:2909`), esportato in CSV (`:3269, 3314`),
controllato come **presente/assente** per DAC7 (`:3104`). **Zero chiamate di pagamento**, e
nessuna validazione di formato né di paese. È un dato di conformità fiscale che il pannello
presenta come un metodo di incasso.

**e) «SENZA IL COLLEGAMENTO IL PAGAMENTO ARRIVA CON BONIFICO MANUALE»: quel bonifico non è una
funzione.** `deploy/host.html:503` (IT) e nelle altre 7 lingue (`:504-510`). Il bonifico manuale
non esiste in nessun modulo. Cosa succede davvero sta in **B17**.

**f) «DASHBOARD PAYOUT, COME SEMPRE»: quella dashboard non esiste.**
`deploy/bunker.html:119` e le traduzioni a `:214-221` dicono al fondatore, in 8 lingue, di pagare
a mano dalla dashboard payout. Non c'è nessuna pagina in `deploy/` e nessun endpoint
amministratore: l'unico è `/api/host/payout` (`fase83_server.py:2059`), che serve **all'host**
per vedere i propri.

**g) LE PERCENTUALI DEI CONCORRENTI NON COINCIDONO NEMMENO FRA LORO.**
La tabella pubblica dice Booking **«10–25% (media 15%)»** (`deploy/commissioni.html:58`) e Airbnb
**15,5%** (`:57`); il motore che fa il confronto all'host usa Booking **18%** e Airbnb **15%**
(`fase69_trasparenza.py:44-49`). Due numeri diversi per la stessa azienda, nella stessa
applicazione. E **nessuna delle percentuali attribuite a terzi ha una fonte citata**: la nota a
`deploy/commissioni.html:66` dice *«Fonti: pagine ufficiali e portali di settore»* senza nominarne
nessuna.

> ⚖️ **DECISIONE DEL FONDATORE (2026-08-24): TOGLIERE TUTTI I NOMI DEI CONCORRENTI E METTERE
> «i grandi portali».** Vale ovunque compaiano: `deploy/commissioni.html` (righe 9, 56-64, 66, 79,
> 84, 96-103) · `deploy/diventa-host.html` (63, 75, 98-105) · `deploy/host.html` (189, 331-335,
> 413, 445, 454, 503-510, 1248) · `deploy/kit-marketing.html` (49, 61, 69, 81, 84, 127-134) ·
> `fase89_jurisdiction_outreach.py:219`. **Non è una riparazione tecnica: è una scelta.** Toglie in
> un colpo il rischio di affermazioni comparative sui prezzi di aziende nominate, su pagine
> indicizzabili, in 8 lingue, **senza una sola fonte citata** — e fa decadere il punto (g), perché
> senza nomi non c'è più niente da far coincidere.
> ⛔ `deploy/` è produzione (divieto B4, esteso il 2026-08-24): serve **«autorizzato»**.

### 🔴 B17 — SE L'HOST NON COLLEGA STRIPE I SOLDI RESTANO FERMI E NESSUNO LO SA

*(misurato il 2026-08-24 leggendo il codice.)*

`fase83_server.py:6191-6192`, dentro `_trasferisci_all_host`:

```python
acct = (info or {}).get("stripe_account_id", "")
if not acct:
    return                  # host non collegato -> bonifico manuale
```

**Ritorna in silenzio.** Nessun log, nessuna riga nel giornale, nessuna email, nessun avviso. Il
payout resta `maturato` nel registro e lì si ferma, per sempre, senza che nessuno lo sappia.

⛔ **E il confronto è la parte che fa male: il caso GUASTO grida.** Quando Stripe c'è ma il
trasferimento fallisce, `fase83_server.py:6275-6282` scrive
`logger.error("BONIFICO MANUALE RICHIESTO: transfer Connect fallito...")` **e** una riga
`payout_manuale` nel giornale immutabile. **L'assenza è più silenziosa del guasto.** Il difetto
non è che manchi la strada manuale: è che l'unico caso in cui l'host non verrà mai pagato è anche
l'unico che non lascia traccia.

⛔ **E il fondatore non ha modo di sapere chi sta aspettando.**
`fase131_payout_dashboard.py:332` `da_pagare(host_id, valuta)` **non è chiamata da nessuna parte**:
zero chiamanti in tutto il progetto. È il metodo che `fase177_financial_controller.py:1048` e
`deploy/bunker.html:119` danno per esistente e in uso.

**Non esiste nessun bonifico nostro, in nessun modulo.** La strada automatica passa **sempre e solo**
da Stripe: `fase83_server.py:6253` → `fase101_stripe_connect.py:226-243`. Non c'è una seconda strada,
e il pannello ne promette una (**B16 punto e**).

---

# C) DOPO L'APERTURA — tutto il resto

`collaudi/METODO_v4.md` è la guida di riferimento per la verifica. PARTE 12 = la porta prima di
aprire ai clienti. PARTE 13 = registro delle famiglie chiuse, si aggiorna a ogni famiglia
chiusa. PARTE 15 = cosa fanno i grandi.

## 🆕 B24-B30 — SETTE COSE TROVATE LA NOTTE DEL 27-28 AGOSTO E NON RIPARATE

> **Nessuna di queste è stata inventata: sono uscite mentre le tre corsie lavoravano ad altro,
> ognuna col comando che la misura.** Stanno tutte in sezione C perché nessuna impedisce di
> aprire al pubblico. ⛔ Ma **B24 e B25 riguardano gli STRUMENTI che ci dicono se il resto
> funziona**, e uno strumento che mente costa più di un difetto: un difetto lo trovi, uno
> strumento guasto ti convince che non ci sia niente da trovare.

### 🟠 B24 — NESSUNO PUÒ SAPERE DALL'ESTERNO SE UN TEST IN CI È GIRATO O È STATO SALTATO

*(corsia B, 2026-08-28. **È la cosa che la corsia B indica come la più utile da fare dopo**, e
regge alla verifica.)*

Un job verde **non distingue** «ho eseguito 6042 test» da «ne ho saltati 300 in silenzio». E
oggi non c'è modo di guardare dentro, misurato:
```
/actions/jobs/{id}/logs      -> HTTP 401
/actions/runs/{id}/artifacts -> l'elenco si legge, il download -> 401
check-runs                   -> output.summary VUOTO su tutti e quattro i job
```
(`ci.yml:137-142` descrive lo stesso muro come 403.) E il salto stesso è **anonimo**:
`unittest` con `SkipTest` in `setUpClass` **non nomina niente, nemmeno con `-v`** — l'unica
identificazione che sopravvive è la **stringa del motivo**, quindi due classi che saltano per
lo stesso motivo sono indistinguibili in qualunque registro, **per sempre**.

💡 **La riparazione è piccola e chiude tutt'e due i lati:** stampare i test **saltati** nel
riepilogo della run, **con nome e motivo**, come già si fa coi caduti in `full-suite`. Poche
righe in `ci.yml`, leggibile **senza permessi speciali**. È l'unica cosa che rende verificabile
dall'esterno se le prove più forti che abbiamo sono girate davvero — e vale più del `-v`.

### 🟠 B25 — QUATTRO ALLARMI `failure` SU JOB VERDI, E SONO TUTTI FINTI

*(corsia B, 2026-08-28, su `8436dac`)*

Su quella impronta: **13 annotazioni su job VERDI, quattro col livello `failure`**. Tutte e
quattro sono guardie che **dimostrano di saper gridare**, non guasti:
- `finto_modulo.py` e `finto_fase_soldi.py` **non esistono nel repository**: sono finti
  costruiti in cartelle temporanee dai test (`test_pipeline_ci.py:3083`, `:7760`, `:9517`);
- «EQUIVALENZA DECADUTA … impronta `000…0`» viene da `test_pipeline_ci.py:4321`, che rompe
  apposta l'impronta e **la rimette alla 4327**.

⛔ **Il difetto vero non è nei test: è in chi legge.** Chi apre la pagina della CI vede testo
rosso su lavori verdi e **non ha modo di distinguere** «l'allarme ha provato che sa gridare» da
«l'allarme ha gridato davvero». La corsia B — lettrice attenta — ci è cascata in dieci minuti.
La prossima persona **li ignorerà tutti, compreso quello vero**: è la regola ferrea 10 (un
falso allarme è un difetto quanto un allarme mancato) applicata al pannello della CI invece che
al codice. Proposta, non lavoro deciso: fare in modo che le annotazioni emesse **dentro un test
negativo** non finiscano nel flusso della CI.

### 🟠 B26 — `ispettore_statico.py` STAMPA RILIEVI «ALTA» ED ESCE 0: È UN VERBALE, NON UN CANCELLO

*(corsia A, 2026-08-28)*
```
python ispettore_statico.py                          ->  EXIT=0  con 3 rilievi ALTA money-float
grep -rn "ispettore_statico" --include=test_*.py .   ->  nessuna corrispondenza
```
Uno strumento che stampa rilievi **ALTA** ed esce **0**, e **nessun test che lo interroghi**:
quei rilievi possono restare per sempre senza che niente diventi rosso. È la regola **#23**,
**COSTRUITO ≠ COLLEGATO**.

⚠️ **Ridimensionamento onesto:** i tre rilievi (`assistente_gestionale.py:1986` e `:2034`,
`fase26_ricerca.py:111`) **non sono sul percorso di pagamento** — `main_casavip.py` e
`fase83_server.py` non nominano quei moduli.

⛔ **E lo strumento ha un secondo difetto, che spiega il primo:** decide se un file «è di soldi»
cercando `cents|centesimi|payout|importo` in **qualunque riga**. Così l'assistente gestionale
(che cerca host, non incassa) entra nel perimetro del denaro. **Il perimetro è largo e impreciso
in tutt'e due le direzioni**: fa entrare chi non c'entra e non garantisce di prendere chi
c'entra. Decidere: o si aggancia a un cancello, **o si dichiara per iscritto che è solo un
verbale** — le due cose vanno bene, quella che non va bene è lasciarlo ambiguo.

### 🟠 B27 — `collaudi/METODO_v4.md` PUÒ MARCIRE E NON SE NE ACCORGE NESSUNO

*(corsia A, 2026-08-28)*

`collaudi/METODO_v4.md` **non è letto da nessun `.py`**. Nessuna guardia lo protegge. Il
censimento di PARTE 12 appena unito — 34 caselle con l'esito e il comando — **può marcire in
silenzio**: il giorno che un `[SI']` smette di essere vero, non se ne accorge nessuno.

💡 È lo stesso difetto che questo progetto combatte da sempre, e che ha già una risposta nota:
**un obbligo affidato alla memoria si rompe, uno affidato a un attrezzo no** (D22). Qui
l'attrezzo non c'è.

### 🟠 B28 — `legale/TERMINI_SERVIZIO.md` NON È SERVITO DA NESSUNA ROTTA, E HA ANCORA UN SEGNAPOSTO

*(corsia A, 2026-08-28)*

Il segnaposto `[Specificare percentuale/modello…]` (`legale/TERMINI_SERVIZIO.md:40`) **non mente
ai visitatori**, perché quel file **nessuno lo serve** — verificato. Ma è il file che finirebbe
in mano all'avvocato, ed è **l'unico posto in cui le condizioni esistono come DOCUMENTO** invece
che come stringa dentro un modulo.

🔗 Si lega alla casella `[NO]` di PARTE 12 «scelta A/B/C sulle commissioni nel rimborso, scritta
nelle condizioni»: la scelta **è già fatta nel codice ed è la B** — `storno_commissione`
restituisce la nostra commissione sul rimborso totale, quella del gestore resta a noi
(`fase177_financial_controller.py:58` e `:342`). **Non è scritta da nessuna parte che il cliente
possa leggere.**

### 🟢 B29 — UN LOG DI SUITE **OK** CONTIENE 3540 RIGHE CHE INIZIANO PER `ERROR:` O `FAIL:`

*(corsia A, 2026-08-28)*

Sono stampe dei test che **esercitano i rami d'errore**: è corretto che ci siano. Ma chiunque
scriva un controllo automatico che cerca `^ERROR:` nel log **concluderà che la suite è a
pezzi** mentre il giro è verde. Non è un difetto oggi: è una **trappola già armata** per il
primo che automatizzerà la lettura dei log — e sarà convincente, perché 3540 è un numero che
sembra una catastrofe.

### 🔵 B30 — DOMANDA APERTA, NON UNA DIAGNOSI: il job `mutazione` importa z3 senza installarlo?

*(corsia B, 2026-08-28, dichiarata come domanda e non come referto)*

Il job `mutazione` **non installa niente** («stdlib pura»). Le due voci del catalogo su
`dimostra_formalmente` sono equivalenti **già dimostrati, con impronta**: non servono z3 al
giro. ⛔ **Non è stato verificato se `collaudi/mutazione_prodotto.py` importi z3 altrove.** Se
lo facesse, quel job girerebbe **senza la libreria, in silenzio** — cioè esattamente il difetto
che la #121 ha appena chiuso su `money-smoke`, in un altro job.

**Costa un `grep`.** È qui perché una domanda aperta dichiarata vale più di una diagnosi
inventata, ed è la stessa forma di buco appena pagata una volta.

---

### 🟠 B21 — LA WHITELIST DEGLI STATI CONFERMABILI: METÀ CHIUSA, RESTA `fase83_server.py:8196`

> ✅ **CHIUSA LA METÀ PIÙ GRANDE il 2026-08-27 dalla corsia B** (in `master` con la richiesta
> di unione #119). `fase162_pagamenti_pendenti.py` adesso **deriva** gli stati ammessi da
> `fase199_invarianti.transizioni_prenotazione()` invece di scriverli a mano in quattro punti.
> Verificato a **comportamento invariato**, stato per stato: nessuno tolto, nessuno aggiunto.
>
> ⛔ **E la corsia B ha trovato una cosa che questo referto non aveva visto: due di quelle
> quattro liste erano scritte AL CONTRARIO** — `stato NOT IN (...)`, cioè una blacklist. Una
> blacklist **ammette di default ogni stato nuovo**: bastava aggiungere uno stato al dominio
> perché rimborso e cancellazione-host lo accettassero come sorgente legale, **senza che
> nessun test diventasse rosso**. È un difetto peggiore della copia: la copia resta ferma,
> questa si allargava da sola.
>
> **RESTA APERTA la seconda copia**, `fase83_server.py:8196`, nel percorso del webhook Stripe.
> Non è un difetto vivo — oggi dice la stessa cosa del modello — ma è una regola scritta a
> mano che il modello non conosce. Tocca codice di produzione: **aspetta «autorizzato»**.

*(misurato il 2026-08-27 su `a77651a`, aprendo le righe una per una)*

La regola «un pagamento si può confermare SOLO da `in_attesa` o `scaduto`» esiste **due volte**,
scritta a mano, in due file diversi:

```
fase162_pagamenti_pendenti.py:324   if r["stato"] not in ("in_attesa", "scaduto"):
fase83_server.py:8196               if stato not in ("in_attesa", "scaduto"):   <- percorso del webhook Stripe
```

Il modello vero sta altrove ed è **derivato**, non scritto a mano: `fase199_invarianti.py:331`,
`transizioni_prenotazione()`, che costruisce la tabella `{stato: {successori}}` **dagli eventi**
— la sua docstring dice «una sola fonte di verità nel modello».

⛔ **Nessuno dei due punti la usa.** Misurato:
- `grep -n "fase199\|transizioni_prenotazione" fase162_pagamenti_pendenti.py` → **vuoto**: quel
  modulo non importa fase199 in nessuna forma;
- `grep -n "fase199\|transizioni_prenotazione" fase83_server.py` → fase199 c'è, ma **solo** per
  `scansiona_db` (`:3528`) e per `i3_prova_prima_del_commit` / `i4_denaro_non_negativo`
  (`:5500`). **`transizioni_prenotazione` non compare mai.**

**Perché è un difetto e non uno stile.** Se domani il modello degli stati cambia — un evento
nuovo, uno stato che diventa confermabile — `fase199` lo sa e queste due righe no. Non si
rompe niente: **restano indietro in silenzio**, che è il modo peggiore. È la stessa forma che
la docstring di `_commissione_regalabile` chiama per nome: *«la stessa regola scritta a mano in
due posti è il modo in cui un difetto sopravvive alla propria riparazione»*.

⚠️ **Una rettifica, misurata: l'aggancio in `fase162` NON esiste ancora.** Questa voce nasce
dall'idea di fare in `fase83:8196` «come si sta facendo in `fase162`» — ma oggi `fase162` la
whitelist **ce l'ha scritta a mano** a `:324` esattamente come `fase83`, e non è fra i file
modificati nell'albero di lavoro. Quindi i posti da agganciare sono **due, non uno**, e
`fase162` non è il modello da copiare: è il primo dei due da riparare.

⛔ **Il punto che nessun mutante tocca.** `test_fase162_hold_pagamento.py:130` dichiara che il
generatore di mutanti **rinuncia** su `not in` (9 punti su quel modulo): quel cancello non è
coperto dalla mutazione, e la sua unica difesa è la guardia scritta a mano a `:437`. Una
seconda copia della stessa regola in `fase83` **non ha nemmeno quella**.

---

### 🟢 B23 — 47.000 CARTELLE TEMPORANEE MAI RIMOSSE, TRE MESI E MEZZO DI RESIDUI

*(trovato dalla corsia B il 2026-08-27, guardando dove nessuno guardava)*

In `TEMP` ci sono circa **47.000 cartelle `tmp*`**, la più vecchia di tre mesi e mezzo fa, per
un totale stimato di **~1,4 GB**. Sono residui: qualcosa le crea a ogni giro e non le toglie.

⚠️ **NON è la causa dei giri lenti**, e l'ipotesi è già stata smontata dalla corsia B con un
argomento che regge: `TEMP` è **una sola per tutta la macchina**, quindi rallenterebbe tutte e
quattro le cartelle allo stesso modo — invece i tempi diversi si spiegano col carico (vedi la
mappa delle postazioni in cima). Resta un difetto di pulizia, non di velocità.

✅ **MISURATO IL 2026-08-28 DALLA CORSIA B, e il bersaglio che questa voce indicava era
SBAGLIATO.** Campione pseudocasuale, dichiarato:
```
TOTALE cartelle in TEMP ...... 48.878
iniziano per tmp ............. 47.100
forma esatta di mkdtemp ...... 47.099   (^tmp[a-z0-9_]{8}$)
residuo di altra forma ....... 1        (tmp.DjLQiQsZ7g, non nostra)
campione ..................... 300 cartelle · 210 VUOTE · 254 file · 0 nomi estranei
```
**Sono nostre.** ⛔ Ma **non** vengono da `collaudi/batteria.py`: il prefisso
`batteria_banco_` fa **7 cartelle**, non 47.000. Lo diceva questa voce stessa («se il prefisso
dominante non è quello, il bersaglio era sbagliato») e la misura l'ha confermato. Vengono dai
`mkdtemp()` senza prefisso, sparsi ovunque:
```
grep -rn "mkdtemp" --include=*.py .                    ->  469 occorrenze in 260 file
file che usano mkdtemp e non nominano MAI rmtree       ->   26  (verifica indipendente)
```
⛔ **I 26 sono un MINIMO, non il totale**: «nomina `rmtree`» non vuol dire «pulisce sempre» —
un `rmtree` dentro un ramo che non si percorre non pulisce niente. Il numero vero dei
colpevoli è ≥ 26, e non si conosce.

⛔ **LA CANCELLAZIONE NON È STATA FATTA, ed è la scelta giusta.** È un'operazione distruttiva
su 47.000 cartelle: serve un via del fondatore **e la macchina ferma** (nessuna suite, nessun
giro di mutazione aperto). Vale la regola ferrea 5: prima si dimostra che nulla di vivo le usa.

⛔ **Non cancellare niente prima di aver guardato cosa c'è e chi lo usa** (regola ferrea 5):
una cartella temporanea può essere il biglietto di un giro di mutazione aperto, cioè l'unica
copia sana di un file di produzione mutato.

---

### ✅ B22 — CHIUSA il 2026-08-27 dalla corsia B — LE DOCSTRING CHE CITAVANO «la riga 263»

Tre punti di `test_fase162_hold_pagamento.py` descrivevano una riga che si era spostata di 61
posizioni. **Riparata nel modo giusto: non aggiornando il numero, togliendolo.** Adesso le
docstring nominano *il cancello di `conferma`*, non le sue coordinate — un riferimento che
porta una cifra prima o poi mente (S17). Chiusa anche la terza occorrenza, quella nel **nome
del test**, che era la più costosa perché la citavano gli schedari della mutazione.

*(il referto originale, per la storia: misurato il 2026-08-27 su `a77651a` con
`grep -nEi "riga ?263|riga263" test_fase162_hold_pagamento.py`)*

```
test_fase162_hold_pagamento.py:130   ... Fra questi ultimi c'e' la riga 263,
test_fase162_hold_pagamento.py:435   # ── LA RIGA 263: IL CANCELLO CHE LO STRUMENTO NON SA ROMPERE ──
test_fase162_hold_pagamento.py:437   def test_riga263_il_cancello_degli_stati_confermabili_e_CHIUSO(self):
```

La riga che descrivono oggi è la **324** (`fase162_pagamenti_pendenti.py:324`): la prosa è
indietro di **61 righe**, e il **nome del test** porta il numero vecchio insieme a lei.

⚠️ **I punti sono tre, non due, e i numeri non sono quelli a mente.** Cercandoli si trovano a
`:130`, `:435` e `:437` — non a `:131` e `:440`. È esattamente il motivo per cui questa voce
esiste: **un numero di riga dentro la prosa invecchia da solo**, e nessuna guardia se ne
accorge perché il test resta verde.

💡 **La forma che chiude la famiglia, non l'esemplare** (METODO, regola sopra tutte): un
commento **non nomina il numero di riga**, come già non nomina la cifra della tariffa (S17). Si
scrive «il cancello degli stati confermabili», non «la riga 263» — così non può diventare
falso. ⛔ Il nome del test è la parte che costa: rinominarlo tocca anche gli schedari della
mutazione che lo citano, e va guardato prima (`grep -rn "riga263"`).

⚠️ **Da non confondere:** `test_promo_lancio_e2e.py:429` cita anch'esso «riga 263», ma parla di
un'altra cosa (`fase186._guasti_isolati`, che guarda solo gli ERROR). **Non è la stessa riga** e
non fa parte di questa voce.

---

### ✅ B20 — CHIUSO il 2026-08-25 — LA GUARDIA DEGLI ELENCHI CERCAVA `TODO` COME SOTTOSTRINGA E INCIAMPAVA SULLA PAROLA «METODO»

*(misurato il 2026-08-25: ha mandato rossa la CI della richiesta di unione 106 — tre job,
`full-suite`, `full-suite-311` e `copertura`, tutti sullo stesso test.)*

`test_pipeline_ci.py:9672` (`TestUnaSolaListaDiCoseDaFare`) vieta che un elenco di lavori
nasca fuori da `RIPRENDI_QUI.md` e `collaudi/piano.py`. Cerca sei aperture — `DA FARE`,
`PROSSIMI PASSI`, `RIPARTI DA QUI`, `COSA MANCA`, `TODO`, `FIXME` — **come sottostringa, in
maiuscolo, dentro i titoli** (`:9695`, `re.match(r"^#{1,6}\s", ...)`).

🔴 **In italiano `METODO` contiene `TODO`.** Quindi qualunque titolo che contenga «metodo»
viene accusato di aprire un elenco di lavori. È successo su due titoli che dichiaravano i
**limiti di una misura**, cioè l'opposto di una lista di cose da fare:

```
collaudi/audit/2_promesse_funzionali.md:245  ## 3. LIMITI DEL METODO — dichiarati
collaudi/audit/9_pannello_senza_endpoint.md:444  ## 📌 NOTA DI METODO (regola B2)
```

**Prima riparato rinominando i due titoli** (`METODO` → `MODO DI LAVORARE`): la CI tornava
verde, ma il difetto restava nella guardia e sarebbe ripartito al primo titolo italiano che
contiene quella parola. Infatti è ripartito: il 2026-08-25 il documento del metodo (oggi
`collaudi/METODO_v4.md`), messo per prova nella radice, è stato accusato dal suo stesso titolo
di riga 1 — e spostarlo in `collaudi/` non è servito, perché la guardia cammina su **tutto**
l'albero e salta solo sette cartelle (`:9680-9685`), fra cui `collaudi/` **non** c'è.
⛔ E la radice non era comunque la sua casa: `test_trasparenza_costi.py:248`
(`test_radice_solo_cinque_documenti_ufficiali`) pretende che in radice stiano **solo i cinque
documenti ufficiali**, e quella regola **non si tocca**. La guida sta in `collaudi/`.

✅ **Riparato nella guardia, che è dove stava il difetto** (`test_pipeline_ci.py:9690-9698`):
le sei aperture si cercano come **parole intere** (`re.search(r"\b" + re.escape(a) + r"\b")`),
non più come sottostringa. `\b` è più **stretto** della sottostringa: può solo togliere accuse,
mai aggiungerne — nessun file prima pulito diventa colpevole. Provata nelle due direzioni prima
di saltare: iniettato un file con `# TO`+`DO` da solo → **ROSSA** (`PROVA_B20_paracadute.md:1`,
`FAILED (failures=1)`); tolto il guasto, con la guida del metodo nell'albero → **VERDE**
(`Ran 1 test`, `OK`). Più dieci casi sul metodo: `# TO`+`DO`, `# DA `+`FARE`, `# COSA `+`MANCA`
e `## FIX`+`ME` restano accusati; `# METODO`, `## Il metodo chirurgico` e `# METODOLOGIA`
passano. ⛔ **Nessuna meta-guardia da aggiornare**: cercata (`grep` su `_apre_un_elenco` in
tutti i `.py`), non esiste — la prova della guardia vive solo qui.

> ⚠️ **E accanto c'è un secondo punto cieco, misurato lo stesso giorno sulla stessa CI.**
> `collaudi/audit_coerenza_tariffe.py` ha chiesto di esaminare **18 cifre nuove**: erano
> **tutte e 18 citazioni** che i referti fanno *per denunciarle*, nessuna una pretesa nuova
> del prodotto. Ma **17 su 18 sono cifre che l'audit non vede nella loro fonte vera**: nel
> suo elenco di anomalie non compaiono `deploy/bunker.html`, `deploy/diventa-host.html`,
> `deploy/kit-marketing.html:128-134` né `fase89_jurisdiction_outreach.py` — cioè **i quattro
> posti dove i passaggi 1, 6 e 8 hanno trovato il «3%» e il «4%»**. Una sola delle 18 (il 2%
> di `fase98_policy_commissione.py:34-35`) coincide con un'anomalia già iscritta. 🔑 **Il
> «3%» è sopravvissuto in 7 lingue anche perché la guardia che doveva vederlo non guarda
> lì**: sono righe di dizionario i18n lunghe migliaia di caratteri, dove decine di
> percentuali stanno sulla stessa riga. Le 18 sono state iscritte in
> `collaudi/baseline_tariffe.txt` (66 → 84) **dopo averle lette una per una**.

### 🔵 B19 — AUDIT COMPLETO DELLE INCONGRUENZE — nove passaggi, **uno per chat**

*(deciso dal fondatore il 2026-08-24, dopo che tre letture in sola lettura in una sola sessione
hanno prodotto B16, B17 e B18.)*

⛔ **PERCHÉ ESISTE, e non è «facciamo un controllo generale».** B16, B17 e B18 non li ha trovati
uno strumento: li ha trovati **una persona che leggeva**. Dove uno strumento guarda, i difetti si
vedono il giorno che nascono; dove non guarda nessuno, invecchiano in silenzio. Questi nove
passaggi sono **le nove direzioni in cui nessuno ha mai guardato**, e ognuno è del tipo che ha
già prodotto un difetto vero in questa giornata.

> 🔑 **LA REGOLA CHE FA FUNZIONARE TUTTO: UN PASSAGGIO = UNA CHAT NUOVA, DA SOLO.**
> Non due insieme, non «già che ci sono». Il motivo è misurato, non teorico: è la **D21** — oltre
> metà contesto l'IA non smette di rispondere, continua **con lo stesso tono sicuro** mettendoci
> dentro numeri mai misurati. Un audit che produce numeri inventati è **peggio di nessun audit**,
> perché quei numeri finiscono nei documenti e ci restano.
> **Si chiede così:** «*B19 passaggio N, sola lettura, scrivi il risultato in
> `collaudi/audit/<nome>.md`*». Poi `/clear`, e il passaggio dopo.

> 📄 **IL RISULTATO VA IN UN FILE, NON A SCHERMO — e questa non è una preferenza.**
> A schermo un elenco di 200 righe è illeggibile, non si può rileggere fra un mese, e **occupa il
> contesto proprio mentre serve per misurare**. Ogni passaggio scrive in **`collaudi/audit/`**,
> una riga per incongruenza, con **file:riga · cosa dice · cosa fa il codice · la lingua**.
> ⛔ La cartella **non esiste ancora**: la crea il primo passaggio. Sta sotto `collaudi/`, che è
> strumentazione di collaudo e non produzione (vale D20, non serve «autorizzato»).
> ⛔ **E i file di `collaudi/audit/` NON sono liste di cose da fare** (REGOLA ZERO 3): sono
> **referti di misura**. Quello che ne esce e va fatto si scrive **qui**, come voce nuova.

| # | Passaggio | File del referto |
|---|---|---|
| 1 | **Tutte le percentuali e i numeri promessi nei testi contro i valori veri nel codice, in tutte e 8 le lingue** | `collaudi/audit/1_numeri_promessi.md` |
| 2 | **Tutte le promesse funzionali nei testi contro cosa il codice fa davvero** | `collaudi/audit/2_promesse_funzionali.md` |
| 3 | **Tutti i punti dove i soldi possono fermarsi in silenzio, come B17** | `collaudi/audit/3_soldi_fermi_in_silenzio.md` |
| 4 | **Tutte le funzioni scritte e mai chiamate da nessuno** | `collaudi/audit/4_mai_chiamate.md` |
| 5 | **Tutte le regole cablate su un solo paese** | `collaudi/audit/5_regole_un_solo_paese.md` |
| 6 | **Tutti i testi che esistono in italiano e non nelle altre 7 lingue, o viceversa** | `collaudi/audit/6_lingue_mancanti.md` |
| 7 | **Tutti i valori scritti a mano nel codice che dovrebbero stare in un posto solo** | `collaudi/audit/7_valori_sparsi.md` |
| 8 | **Tutti i punti dove due file dicono numeri diversi per la stessa cosa** | `collaudi/audit/8_numeri_discordi.md` |
| 9 | **Tutto quello che il fondatore vede nel pannello e che non corrisponde a un endpoint vero** | `collaudi/audit/9_pannello_senza_endpoint.md` |

✅ **PASSAGGIO 1 FATTO (2026-08-24, su `584f0e9`): 15 incongruenze** in `collaudi/audit/1_numeri_promessi.md`. Le tre che pesano: l'**email di reclutamento promette 4%** mentre il motore prende 5% + 0,25 € (ripiego `fase89:189` = 400 contro `main_casavip.py:150` = 500, e in produzione `PAGAMENTO_BPS` è **assente**) · `deploy/diventa-host.html` dice **«3%» in tutte e 8 le lingue, italiano compreso** (`:60`, `:98-105`) — quindi **B16 punto (a) va corretto: sono 8 lingue, non 7** · la guardia `collaudi/audit_coerenza_tariffe.py` **esenta 40 righe-dizionario su 40** e i test chiedono *«c'è la cifra giusta?»* invece di *«manca quella sbagliata?»*.

✅ **PASSAGGIO 2 FATTO (2026-08-24, su `584f0e9`): 15 promesse senza codice** in `collaudi/audit/2_promesse_funzionali.md`, su 364 stringhe italiane esaminate. Le tre che pesano: **«Alloggi certificati»** in cima alla homepage in 8 lingue e **nessuna certificazione esiste** · **«classe fondatrice · tariffa bloccata»** senza una riga di codice (misurato: host n.1 e n.5000 pagano identico, e la tariffa **sale** 0→8→10%) · **«il cliente viene rimborsato al 100%»** detto al presente mentre nessun rimborso parte da solo (il manuale è una **decisione**, `fase83:4611`: il difetto è la promessa che non lo dice). Dentro anche il **Credito Fondatore promesso in homepage che vale 0,00 €** con ogni host nei primi 90 giorni, e le **candidature partner** che finiscono dove **nessun pannello guarda**.

✅ **PASSAGGIO 3 FATTO (2026-08-24, su `584f0e9`): 22 punti muti** in `collaudi/audit/3_soldi_fermi_in_silenzio.md` — 🔴 8 gravi · 🟠 11 medi · 🟡 3 minori, su **152 moduli di produzione** passati a uno scanner AST (534 candidati grezzi) e **~60 funzioni lette a mano** in 16 moduli dei soldi; più **7 sospetti verificati e scartati**, scritti apposta perché non si riaprano. Le tre che pesano: **il webhook risponde `200` a ogni evento che non sia un pagamento** (`fase83_server.py:7839`) — quindi `payout.failed` entra, dice che il bonifico all'host **non è arrivato**, e sparisce senza una riga · **nessuno scrive mai lo stato `pagato`** (misurato: `grep aggiorna_stato(` → 6 righe, zero con `"pagato"`), e il guardiano cerca i bonifici fermi **solo** fra i `maturato` (`fase186_guardiano.py:141`), quindi `in_attesa`, `trattenuto` e `in_transito` sono tre stanze senza sorveglianza · **collegare Stripe è l'unico sblocco senza riprova** (`fase83_server.py:6301-6305`, mentre dati fiscali `:3134` e verifica `:2958` ritentano da soli): è l'aggravante di **B17**. 🔑 La forma di famiglia: **il guardiano vede solo ciò che è già scritto nel registro** — le 8 voci gravi sono tutte punti in cui il registro **non viene scritto**, o viene scritto e **nessuno lo rilegge più**, e in 5 di esse il silenzio **non ha scadenza**.

✅ **PASSAGGIO 4 FATTO (2026-08-24, su `584f0e9`): 112 funzioni mai chiamate** in `collaudi/audit/4_mai_chiamate.md` — 🔴 22 gravi · 🟠 68 medie · 🟡 16 minori · 🔵 6 rotte Flask, su **2.092 definizioni** in **152 moduli** passate a uno scanner AST e a una **controprova testuale indipendente** (10 discordanze su 254, tutte e 10 aperte a mano e tutte e 10 in docstring); **5 falsi positivi tolti** (li chiama `BaseHTTPRequestHandler`, non noi) e **34 funzioni lette riga per riga** (34 conferme su 34). Le tre che pesano: **`fase199_invarianti.py:146` `guardia_prenotazione()`** — la guardia pre-scrittura che solleva su I1/I2/I3 non la chiama nessuno, e il server importa **due invarianti su quattro** (`fase83_server.py:5375`), quindi **la doppia conferma sulla stessa unità non è controllata prima di scrivere** · **la cauzione ha un archivio durevole che resterà sempre vuoto** (`fase149:72` `autorizza()`, unico scrittore della tabella, zero chiamanti; `grep -ic cauzion` su `fase83_server.py` = **0**) · **`fase98:149` `e_fondatore()` e `fase98:182` `fattura_startup_cents()`** senza un chiamante: la classe fondatrice non viene applicata da nessuna riga (conferma dal codice di quanto il passaggio 2 aveva misurato sui testi) e **il consumo della soglia 85k non lo calcola nessuno**. 🔑 La forma di famiglia: **costruito e collegato ≠ chiamato** — coda, turnover, digital twin e deposito cauzionale nascono in `fase81_bootstrap_casavip.py:533-535` e `:383-386` e l'unico ingresso non li nomina mai (`turnover`/`twin`/`cauzion` → **0 occorrenze** in 11.245 righe di server). ⚫ E accanto ai 112: **59 moduli interi mai raggiunti** da `main_casavip.py` = **12.055 righe, 651 funzioni, il 23,7% del codice di produzione** (dentro ci sono `fase17_money`, `fase15_idempotency`, `fase103_reverse_charge`, `fase151_alloggiati_web`).

✅ **PASSAGGIO 5 FATTO (2026-08-24, su `584f0e9`): 17 regole di un paese solo applicate senza guardare il paese** in `collaudi/audit/5_regole_un_solo_paese.md` — 🔴 6 gravi · 🟠 8 medie · 🟡 3 minori, trovate con **due setacci indipendenti** (24 marcatori grep sui 152 moduli, aperti riga per riga; più un setaccio sui **punti di decisione**, che è quello che ha stanato i difetti che *non nominano nessun paese*) e col grafo di raggiungibilità (**59 moduli mai raggiunti**, riprodotti oggi con uno scanner nuovo: coincide col passaggio 4). Più **5 moduli morti** a tema paese, **11 sospetti verificati e scartati** e **4 voci al confine col passaggio 6**, segnalate e non contate. 🔑 La forma di famiglia: **in tutto il server c'è UN SOLO punto che guarda il paese** (`fase83_server.py:8975`, il CIN) — su 95 righe che nominano `paese`, quelle che decidono qualcosa sono **una** nel server e cinque in moduli mai raggiunti. Le tre che pesano: **il campo `paese` dell'annuncio si azzera da solo** — è testo libero non obbligatorio (`fase57_vetrina.py:252-254`) e l'UPDATE lo sovrascrive con `""` (`fase57_vetrina.py:575-576`) mentre `valuta` e `stato` hanno la loro guardia (`fase83_server.py:8870`, `:8899`) e **`_blinda_paese` non esiste**: chi risalva dal pannello un annuncio il cui paese non è uno dei **15 codici della tendina** (`deploy/host.html:355-364`, `:1203`, `:1066`) perde il paese, e con esso l'obbligo del CIN da 500-5.000 € a annuncio · **il gate di giurisdizione DAC7 esiste e l'unico punto che blocca i soldi non lo consulta** (`fase100_dac7.py:23` `attivo=False`, ma `fase83_server.py:6053` legge `deve_segnalare`, cioè `legale` a `fase100_dac7.py:46`, che `attivo` non lo guarda) — ⚠️ **questo corregge B18 punto 3: il modulo è spento, il blocco payout no**, e la soglia è in euro su una somma che mescola le valute (`fase177_financial_controller.py:409-470`, zero occorrenze di `valuta`) · **la quota fissa della tariffa tecnica è un numero in EURO sommato alle unità minori di qualunque valuta** (`main_casavip.py:152` → `fase59_concierge.py:350`; `fase59:501-502`; `fase188_paga_struttura.py:41-42`, che a `:36` dichiara da sé il denominatore sbagliato), mentre i testi legali in **8 lingue** promettono «EUR 0,25» (`fase185_testi_legali.py:133,207,281,357,433,508,567,609`). ⛔ Dentro anche: **l'autorità privacy scelta per LINGUA e non per paese** (5 risposte diverse: en→Garante italiano, es→AEPD, fr→CNIL, pt→CNPD, de/ja/zh→nessuna) · le **clausole vessatorie ex artt. 1341-1342 c.c. bloccanti per registrarsi in tutto il mondo** · il gate outreach cablato su **`("US",)`** (`fase89_jurisdiction_outreach.py:37`) mentre il database mondiale che risponderebbe (`fase154_giurisdizioni_marketing.py`) ha **zero chiamanti**. ✅ Riconfermati in modo indipendente **B18 punti 1, 2 e 3**; e **verificati e scartati**: il CIN è agganciato bene al paese, la tassa di soggiorno è davvero jurisdiction-agnostic, nessuna ritenuta/cedolare esiste, date tutte ISO 8601, nessun CAP/ZIP, nessun formato telefono nazionale, SCA trattata come esito generico, cookie solo tecnici, il ripensamento 48h è uniforme **apposta**.

✅ **PASSAGGIO 6 FATTO (2026-08-25, su `584f0e9`): 19 scompagnamenti di lingua** in `collaudi/audit/6_lingue_mancanti.md` — 🔴 7 gravi · 🟠 8 medi · 🟡 4 minori, su **8.428 coppie (lingua, chiave)** confrontate una per una in **26 dizionari** di 12 moduli Python, 13 pagine HTML e `deploy/app.js`, con quattro sonde deterministiche (chiavi mancanti · lingue assenti · **segnaposto** · **numeri dentro lo stesso slot**); più **11 sospetti verificati e scartati**. 🔑 La forma di famiglia: **il confine fra traduzione completa e traduzione a metà coincide esattamente con il confine di dove arriva una guardia** — dove si misura (dizionario del server 165×8, email 62×8, legali 8/8 con lo stesso numero di articoli, `app.js` 42×8) non c'è **un** buco; dove non si misura — i **due pannelli** — **239 chiavi su 468 esistono solo in italiano e inglese**. Le tre che pesano: **il pannello host è per il 47% in inglese** in de/es/fr/pt/ja/zh (`deploy/host.html:502`, 148 chiavi su 316, **146 rese davvero a schermo**, ripiego inglese a `:512`) e dentro ci sono **tutte e 7 le chiavi di commissione e tariffa tecnica**, l'avviso «penale del **15%**» (`hc_conferma`) e **l'approvazione specifica delle clausole ex artt. 1341-1342 c.c.** (`clausole_appr`) · **la tariffa tecnica dice «3%» in 7 lingue e «5% + 0,25 €» in italiano in DUE posti nuovi**: la sala di controllo (`deploy/bunker.html:213` `ct_h`) e il kit di reclutamento (`deploy/kit-marketing.html:118` `box2`/`msg1`/`msg2`/`msg3`, dove le 7 lingue aggiungono anche *«su quella riga non guadagniamo nulla»*, **falso** con 5% + 0,25 €) — quindi il canale di reclutamento dice oggi **tre cifre diverse** (4% email · 3% kit in 7 lingue · 5%+0,25 kit in italiano) · **il contratto ripiega su due lingue diverse a seconda di chi risponde**: il server sull'**inglese** (`fase163_accettazioni.py:345-355`), la pagina sull'**italiano** (`deploy/contratto-host.html:46-48`), e `deploy/host.html:97`/`:136` linkano il contratto **senza `?lang=`** mentre `:976` lo chiede all'API **con** la lingua → **la prova firmata registra una lingua, l'host ne ha letta un'altra**. ⚠️ E la guardia che dovrebbe vederlo è verde: `collaudi/occhio_del_fondatore.py` promuove `host.html` **773/776** perché conta i **marcatori** nell'HTML e **non apre nemmeno un dizionario** (zero codici lingua in tutto il file); l'unico test sulle pagine di `deploy/` (`test_profondo_lingue.py:534-546`) copre **`grazie.html` e `annullato.html`** — 5 chiavi l'una — e verifica solo che il **blocco** della lingua esista, mai che le chiavi combacino: **5.798 delle 5.830 coppie HTML sono fuori da ogni denominatore**. Dentro anche: **la pagina che Google indicizza per ogni annuncio del mondo è congelata** (`fase83_server.py:672` `lang="it"`, «Prezzo… / notte», «Prenota su BookinVIP», e i servizi stampati come **codici grezzi** senza passare da `ETICHETTE_SERVIZI`, che esiste in 8 lingue a `fase61:78-89`) · `deploy/host.html` è **l'unica pagina con 22 `placeholder=` e 0 marcatori** di traduzione · il **motore marketing parla 5 lingue su 8** e a `fase90_marketing.py:272` **scarta ja/pt/zh in silenzio** (mentre `:141` prova che le 8 erano sotto gli occhi), col commento di `fase83_server.py:10521` che dice «default del motore (**tutte**)» · **l'imbuto SEO promette 13 lingue** (`fase97_inbound_seo.py:28`) che il prodotto non sa servire (8). ✅ Riconfermati e **contati qui** i tre punti che il passaggio 5 aveva segnalato e non contato; ✅ **verde pieno** su una sola cosa, e va detto: **0 segnaposto scompagnati su 8.428 coppie**.

✅ **PASSAGGIO 7 FATTO (2026-08-25, su `584f0e9`): 20 valori sparsi** in `collaudi/audit/7_valori_sparsi.md` — 🔴 6 gravi · 🟠 11 medi · 🟡 3 minori, su **152 moduli di produzione** (50.915 righe) passati a uno scanner AST che ha censito **5.119 letterali numerici** (281 distinti) e **24.175 letterali stringa** (8.993 distinti), di cui **86 numeri** e **1.134 stringhe** presenti in ≥2 file; più **6 sospetti verificati e scartati** e **3 voci al confine col passaggio 8**, segnalate e non contate. 🔑 La forma di famiglia, e non era quella attesa: **l'unico posto quasi sempre ESISTE GIÀ** — su 20 voci, in **17** la fonte unica è scritta, commentata e funzionante (`ConfigCasaVIP` per i soldi, `fase98` per la rampa, `fase99.esponente()` per le valute, `fase61.LINGUE_SUPPORTATE` per le lingue, `BV.money` in `deploy/app.js`). **Il difetto non è l'assenza della fonte: è che la fonte non è quella che la produzione raggiunge**, e si rompe in tre modi contati (**2** fonti complete in moduli mai raggiunti · **13** fonti vive che i consumatori riscrivono invece di chiedere · **5** fonti vive la cui guardia copre solo una parte). Le tre che pesano: **la tariffa tecnica ha quattro ripieghi scritti a mano in quattro file con tre valori diversi** (`main_casavip.py:150-152` = 500/700/25 · `fase185:71,75-76` che rilegge `PAGAMENTO_BPS` da sé · `fase185:83-84` = 5/7/«0,25» nel ramo `except` · `fase89:189` = 400 · **`fase188:64` e `:87` = 300, che nessuno aveva contato**), e quel 300 **disattiva una garanzia scritta nel file**: `_gw()` a `fase188:98-100` non fa mai scattare il ramo `per_psp` perché 3% è sempre minore di 3,25% + 0,55, mentre col valore vero (500) scatterebbe sopra un anticipo di **31,43 €** · **la ricetta di apertura di SQLite è copiata 62 volte nei moduli vivi** e la copia completa sta in `fase23_datastore.py:146-152`, **mai raggiunta dalla produzione** · **`deploy/app.js` si dichiara «FONTE UNICA» a `:1` e 4 pagine riscrivono a mano la formattazione del denaro 37 volte**. 💡 Il corollario: **queste 20 voci non si riparano scrivendo una costante — la costante c'è. Si riparano COLLEGANDO** (regola #23 «COSTRUITO ≠ COLLEGATO», alla seconda comparsa in tre passaggi).

✅ **PASSAGGIO 8 FATTO (2026-08-25, su `584f0e9`): 17 coppie discordi** in `collaudi/audit/8_numeri_discordi.md` — 🔴 6 gravi · 🟠 9 medie · 🟡 2 minori, su **169 file di produzione** (152 `.py` + 14 pagine + `app.js`/`sw.js`/`manifest.json`) **più le 28 configurazioni di deploy**, perimetro che ho aggiunto perché `nginx.conf` e `docker-compose.yml` decidono numeri che il prodotto subisce — ed è proprio lì che è nata la voce più grave. Quattro attrezzi: scanner per concetto (16 famiglie di parole chiave → **13.417** occorrenze numeriche indicizzate), scanner AST delle costanti per **nome** (3 nomi e 2 campi discordi su ~1.100), grafo di raggiungibilità (**93 vivi / 59 mai raggiunti**, che riproduce i passaggi 4, 5 e 7) e **41 punti letti a mano**; più **13 sospetti verificati e scartati** e **3 conferme indipendenti** di difetti già contati dai passaggi 1 e 6, non risommate. 🔑 La forma di famiglia: **cercavo «il numero vecchio rimasto in un posto» e ne ho trovato uno solo** — le altre 16 sono **9 casi in cui il numero e la sua ETICHETTA vivono in file diversi** e **7 in cui due motori vivi rispondono alla stessa domanda con numeri diversi**. Le tre che pesano: **`deploy/commissioni.html` si contraddice a schermo in tutte e 8 le lingue** — il riquadro dice `€84,75` (`:75`, e quadra: 100 − 10 − 5,25) mentre il paragrafo accanto dice `€87` (`:96-103`, i numeri del vecchio 3%), e l'applicatore a `:108` fa `el.textContent = d[k]` **sempre, anche in italiano**, quindi la riga statica giusta viene sovrascritta da quella sbagliata a ogni caricamento · **due motori di referral vivi con premi e soglie diversi** — €40 alla 3ª prenotazione (`fase81:56-58` via `fase76`, cablato a `:356-361`) contro €10/€15/€20 alla 1ª (`fase109:23,85`, cablato a `:504-506`), entrambi con rotta viva (`/api/host/referral` e `/api/host/invito`) e **lo stesso identico link `?ref=`**, ma la registrazione (`fase83:8695-8705`) riconosce solo i codici del primo → chi ha invitato non prende niente, in silenzio · **la prova fotografica dell'ospite muore a ~700 KB** mentre app e testo in 8 lingue dicono 5 MB (`fase83:2327`, `:288`): `/api/voucher/prova` cade sotto `client_max_body_size 1m` (`nginx.casavip.ssl.conf:43`) perché l'eccezione a **8m** esiste solo per `/api/host/upload_foto` (`:80-83`) — ed è la prova su cui si decide **a chi vanno i soldi in garanzia**. Dentro anche: **su «paga in struttura» l'host paga 3,25% + 0,55 € (`fase188:41-43`) mentre il contratto che ha firmato dice 5% + 0,25 € (`fase163:215-221`)**, e la docstring di `fase188:18-19` nomina proprio la cifra del contratto · **la tabella dei concorrenti discorda su cinque portali su cinque** fra `fase69:44-48` (che il pannello host mostra via `/api/trasparenza`) e `deploy/commissioni.html:57-63` (TripAdvisor: **15% contro ~3%**) · **`/api/split/preview` accetta 1000 partecipanti e `/api/split/crea` ne rifiuta più di 50** (`fase133:32` contro `fase65:45`). ⚠️ **Due voci dipendono dall'ambiente del VPS, che NON ho misurato**: `PAGAMENTO_BPS` (decide se l'email che dice 4% concorda col motore che addebita 5%) e `PAGA_STRUTTURA_ATTIVO` (nel codice il default è `"0"`, `fase83:5320`). 💡 E il corollario scomodo: **dieci di queste diciassette non si riparano cambiando un numero** — prima va deciso **quale dei due motori vive** (referral, split, benchmark OTA, gateway paga-in-struttura), e quella è una decisione del fondatore, non una correzione.

✅ **PASSAGGIO 9 FATTO (2026-08-25, su `584f0e9`): 10 porte chiuse promesse dal pannello** in `collaudi/audit/9_pannello_senza_endpoint.md` — 🔴 3 gravi · 🟠 6 medie · 🟡 1 minore, più **14 rotte vive che nessun pannello apre** (contate a parte), **15 sospetti verificati e scartati** e **3 conferme** dei passaggi 2, 6 e 8 non risommate. Perimetro: i 3 pannelli (**3.099 righe**, 53 sezioni, 97 bottoni, **671 voci di dizionario italiane lette una per una**, 8 lingue), **più** la pagina di ingresso costruita in Python (`fase83_server.py:1540-1700`, dove l'host si registra davvero) e `deploy/guida-operativa.html`; contro le **164 rotte** del server, ricostruite con uno scanner perché `@app.route` qui trova **10 rotte morte e zero di quelle vere**. 🔑 La forma di famiglia, e non era quella attesa: **dove il pannello CHIAMA torna tutto — 0 bottoni scollegati su 97, 0 campi, 0 chiavi, 0 metodi sbagliati su 89 chiamate — e tutte e 10 le voci stanno in un TESTO**, perché le chiamate hanno una guardia (un endpoint sbagliato dà 404 e il collaudo cade) e i testi non li confronta nessuno col codice. Le tre che pesano: **la «dashboard payout» non esiste e ci mandano TRE testi in 8 lingue su 8** (`deploy/bunker.html:119` · `deploy/guida-operativa.html:96` · `host.html` `sc_p` «arriva con bonifico manuale») — su 135 rotte l'unica con `payout` è `/api/host/payout`, **host-auth**, e `fase131:332 da_pagare()` non ha chiamanti (passaggio 4): **il gesto che fa uscire i soldi verso l'host non ha né schermo né endpoint** · **al gate di registrazione la casella «Accetto il Contratto Host» apre i TERMINI** (`fase83_server.py:1617` linka `/termini.html`, che a `deploy/termini.html:31` dichiara `DOC='termini'`) mentre la registrazione spedisce il `doc_sha256` **del contratto** preso da `fase163` (`:1606-1607`, `:1631-1634`): **la prova firmata registra un documento che l'host non ha visto**, e `host.html:97`/`:136` linkano invece quello giusto · **«Cancella attività host — da OGNI archivio, e verifica che non resti nulla»** (`admin.html` `del_p`) ne cancella e verifica **5** (`fase156_erasure.py:206-215`, `:218-232`) mentre l'host resta in **payout, kyc, accettazioni (IP e firma), pendenti, debiti, wizard** — e il pannello stampa «Verifica residui (**tutti 0**)» a chi sta rispondendo a una richiesta GDPR. Dentro anche: **il kill-switch dice «tutti i movimenti» e tre gestori non lo guardano** (`riscuoti_debiti_carta:7916` addebita carte off-session, oggi dormiente per `SCATTO3_ATTIVO=0`) · **badge «Host Verificato+» e «bonifici prioritari» non esistono** (il badge sta solo nel pannello dell'host stesso, i payout escono `ORDER BY ts`) · **il pannello marketing offre 5 lingue su 8** (difetto *a monte* di quello che il passaggio 6 aveva misurato nel motore). 🔵 E l'immagine speculare: **`/api/bunker/guardiano`, `/api/bunker/invarianti`, `/api/bunker/stato` e `/api/admin/diagnosi` sono vive e le interroga SOLO la cartella `collaudi/`** — la Sala di controllo ha 15 schede e **nessuna per il guardiano dei soldi**. ⚠️ **NON misurato: l'ambiente del VPS** — 5 variabili (`PAGA_STRUTTURA_ATTIVO`, `CAMPAGNA_AUTO_GIORNI`, `CAMPAGNA_LINGUE`, `SCATTO3_ATTIVO`, Bunker configurato) cambiano 4 delle 10 voci.

✅ **PASSAGGIO 16 FATTO (2026-08-25, su `cb45c80`): l'ambiente del VPS contro i default del codice** in `collaudi/audit/16_ambiente_vps.md` — **9 voci dei nove referti cambiano forma**. Sola lettura anche sul VPS (solo `git rev-parse`, `docker ps/inspect`, `grep`, `cat`, `curl`, `ls`, `date`: nessuna variabile cambiata, nessun riavvio, nessun deploy), e **zero valori segreti stampati** — il filtro gira **sul server** e fa uscire solo `<PRESENTE, N byte>`. Misurato: **132 variabili lette dal codice** contro **87 righe di ambiente** nel contenitore vivo → **24** lette dal codice vivo e **assenti** (vince il default), **57** presenti (vince l'ambiente), **4** lette solo da moduli spenti, **12** impostate che **nessuna riga legge**. 🔴 **Tre voci passano da «dipende dall'ambiente» a CONFERMATE**: `PAGAMENTO_BPS` è **ASSENTE**, quindi i tre ripieghi divergono davvero e l'email di reclutamento discorda dal motore **adesso** (passaggio 1 N1 · passaggio 8 voce 2 · giro B1) · **`PAGA_STRUTTURA_ATTIVO=1`**, quindi 8·6 e 9·9 **non sono latenti** · `DAC7_BLOCCO_PAYOUT` assente → default **`1`**: **il blocco dei bonifici è ACCESO mentre `fase100_dac7.attivo=False`** (5·4 nella forma peggiore). 🔄 **Una si ribalta**: `CAMPAGNA_AUTO_GIORNI=3` e `CAMPAGNA_LINGUE=it,en` — il marketing automatico **non è spento** (gira ogni 3 giorni) ed esce in **2 lingue su 8**, quindi la voce 9·6 è **vera nel codice e falsa in produzione**, e 6·13/6·14 peggiorano. 🟢 **Una decade**: il Bunker **è configurato**, quindi il ramo «fascicolo con la sola chiave admin» di 9·8 non si applica (⚠️ ma `BUNKER_RECOVERY` è **assente**: nessuna via di rientro). ✅ **Quattro restano latenti per MISURA e non per ipotesi** (`SCATTO3_ATTIVO` assente → il buco del kill-switch B4 e la carta 9·5 restano chiusi). 🟠 **E quattro cose che nessun altro passaggio poteva vedere**: **quattro segreti vivi che nessuna riga legge** (`STRIPE_LIVE_SECRET_KEY`, `STRIPE_LIVE_PUBLIC_KEY`, `META_APP_SECRET`, `TIKTOK_CLIENT_SECRET`) · **l'identità fiscale sta nell'ambiente e il codice la scrive a mano in 3 posti** (`fase185:52`, `fase83:1349`, `deploy/index.html:247`) — il passaggio 7 al contrario · **Mastodon e Nostr configurati e spenti** (letti solo da moduli mai raggiunti), mentre `X_ENABLED` e `ALIPAY_WECHAT_CONNECT_SPLIT` **non esistono in nessun file** · `SMTP_PORT=465` contro il default `587`. ✅ **Sano e misurato adesso**: VPS `cb45c80` = computer = GitHub, `casavip_app` **Up 24h (healthy)**, `https://bookinvip.com/` **HTTP 200 in 0,025 s**, `/api/health` → `"guardiano": "ok"`, battito del guardiano **19,1 minuti fa**, e **`OXR_APP_ID` è impostata** (era un lavoro aperto in memoria: è fatto). ⚠️ Due attrezzi indipendenti, e **il secondo ha corretto il primo su 7 nomi su 87** (righe `os.environ` spezzate su due righe).

📋 **E il piano delle riparazioni è in `collaudi/audit/0_piano_riparazioni.md`**: le **247 voci** dei nove referti raggruppate in **19 giri** (per file, non per tema) più **12 decisioni che non sono riparazioni**, ordinate mettendo per primi i giri dove **un cliente vero può farsi male**. Costo misurato: **19 × (26 min di suite + 11,9 min di CI) = 12 ore di sola verifica**. ⛔ Non è una lista di lavori parallela a questa: quando una sua riga diventa un lavoro, **quel lavoro si scrive qui**.

**Cosa cerca ognuno, detto in modo che non si possa fraintendere:**

1. **I NUMERI.** Ogni cifra che una pagina, un'email o un contratto mostra al cliente, confrontata
   con la costante che la produce. Il difetto tipo l'ha già dato: **«3%» in sette lingue contro
   `5% + 0,25 €` nel motore** (B16 punto a). ⛔ Le 8 lingue si guardano **tutte**: il difetto stava
   nelle sette che nessuno rilegge, non nell'italiano.
2. **LE PROMESSE.** Non i numeri: i **verbi**. «i soldi tornano», «ricevi i bonifici», «arriva con
   bonifico manuale», «sito in 13 lingue». Per ognuna: **esiste il codice che la mantiene?** Ha già
   dato B8, B16 punti b/d/e.
3. **I SOLDI CHE SI FERMANO ZITTI.** Ogni `return` anticipato, `except` che ingoia, o ramo che
   salta un pagamento **senza scrivere niente** — né log, né giornale, né email. Il modello è
   `fase83_server.py:6191-6192` (B17). ⛔ Il criterio è **il silenzio**, non il fallimento: un
   guasto che grida è già sorvegliato.
4. **LE FUNZIONI MAI CHIAMATE.** Metodi definiti e senza un solo chiamante fuori da sé e dai test.
   Ha già dato `fase131_payout_dashboard.py:332` `da_pagare()`, che **due file danno per in uso**.
   ⛔ Attenzione a chi è chiamato **per nome dinamico** (rotte, `getattr`): quello non è morto.
5. **LE REGOLE DI UN PAESE SOLO.** Costanti, formati e obblighi che valgono solo per l'Italia o
   solo per l'UE, e il punto dove si decide se applicarli. ⛔ **Averle non è il difetto**: il CIN è
   agganciato bene al paese (`fase83_server.py:8973-8976`). Il difetto è **applicarle senza
   guardare il paese**, o **chiedere un dato che altrove non esiste** (l'IBAN, B18 punto 3).
6. **LE LINGUE SCOMPAGNATE.** Chiavi di traduzione presenti in una lingua e assenti in un'altra,
   in `deploy/*.html` e nei dizionari `fase*.py`. ⚠️ E il caso più insidioso non è la chiave
   mancante: è la chiave **presente con il contenuto vecchio** (di nuovo B16 punto a). Il contratto
   host è il caso limite: esiste in **due** lingue sole (`fase163_accettazioni.py:281-282`).
7. **I VALORI SPARSI.** Lo stesso numero scritto a mano in più posti. È già costato: la tariffa
   tecnica viveva in **sei** posti, il prodotto era giusto ed **era cieca la sorveglianza**.
   ⛔ Il referto dice **dove dovrebbe stare l'unico posto**, non solo dove sono le copie.
8. **I NUMERI DISCORDI.** Due file che dicono cose diverse della stessa cosa. Ha già dato
   `deploy/commissioni.html:58` (Booking 15%) contro `fase69_trasparenza.py:45` (18%). ⚠️ Non
   confondere «discordi» con «diversi a ragione»: 5% e 7% sono due casi veri, non un conflitto —
   il referto deve dire **quale delle due**.
9. **IL PANNELLO CHE PROMETTE PORTE CHIUSE.** Ogni bottone, link e istruzione nei pannelli
   (`admin.html`, `bunker.html`, `host.html`) confrontato con le rotte che il server espone
   davvero. Ha già dato **«dashboard payout, come sempre»** in 8 lingue per una dashboard che non
   esiste (`deploy/bunker.html:119`, B16 punto f).

> ⛔ **REGOLE PER TUTTI E NOVE, senza eccezioni.**
> · **SOLA LETTURA.** Nessuna riparazione per strada, nemmeno «una riga». Trovato un difetto: **si
>   scrive e si va avanti** — fermarsi a ripararlo è il meccanismo che ha prodotto il 6,5% di
>   prodotto in tre settimane.
> · **NESSUNA SUITE, NESSUN COMMIT** durante un passaggio: sono misure, non lavori.
> · **OGNI RIGA DEL REFERTO PORTA `file:riga`** e come è stata trovata (D22). Una riga senza la
>   sua misura è un ricordo.
> · **SI DICHIARA COSA È RIMASTO FUORI** (D18 punto 3): tetti, cartelle saltate, casi non
>   guardati. Un taglio silenzioso fa sembrare «coperto» ciò che nessuno ha visto.
> · **QUANDO IL PASSAGGIO FINISCE**, il referto esiste su disco e qui si aggiunge **una riga sola**
>   che dice quante incongruenze ha trovato e dove sta il file.

⚠️ **QUESTO AUDIT NON RIPARA NIENTE, E NON DEVE.** Produce nove referti. Le riparazioni diventano
voci nuove in sezione B o C, si mettono in fila, e **quelle sui testi entrano tutte nel giro unico**
già stabilito in cima alla sezione B.

### 🟠 B18 — HOST FUORI ITALIA: SI PUÒ PUBBLICARE, NON SI PUÒ PAGARE

*(misurato il 2026-08-24 leggendo il codice, in sola lettura. Sta in sezione C e non in B perché
non blocca l'apertura: **blocca il secondo paese**, non il primo.)*

Il motore è più globale di quanto sembri: la tassa di soggiorno è **jurisdiction-agnostic** con
default ZERO (`fase66_tassa_soggiorno.py:1-30`, registro per comune a `fase147_tassa_comunale.py:79`,
ignoto → 0 a `:124`), **non esiste nessuna ritenuta del 21%** né altra regola fiscale italiana
applicata ai conti (cercato in tutti i moduli: zero occorrenze di `ritenuta`/`cedolare` come
calcolo), e l'unica regola italiana cablata — il **CIN** — è agganciata correttamente al paese
(`fase83_server.py:8973-8976`, scatta solo se `paese` ∈ IT/ITA/ITALIA/ITALY).

**Quello che manca sta tutto a valle della pubblicazione:**

1. 🔴 **Il paese è dichiarato e poi buttato via proprio dove serve.** L'host lo scrive nei dati
   fiscali (`fase88_registro_host.py:447`, letto a `fase83_server.py:3104`). Quando apriamo il suo
   conto, `fase83_server.py:6302` chiama `crea_account(email)` e
   `fase101_stripe_connect.py:181-190` invia **solo `type=standard` e l'email**: **`country` non
   parte mai.** Il dato c'è già: va solo passato.
2. 🔴 **Il contratto esiste in due lingue sole**, `it` e `en` (`fase163_accettazioni.py:281-282`),
   con **legge italiana e foro della nostra sede** (`:155-157` IT, `:267` EN), e cita **CIN, SCIA,
   cedolare secca, Comune** — istituzioni che a un host fuori Italia non dicono niente.
3. 🟠 **L'IBAN è obbligatorio nei dati fiscali e non è mai validato** (`fase83_server.py:3104`;
   nessun controllo di formato né di paese in nessun modulo). Vietnam e Filippine **non usano
   l'IBAN**. Non blocca subito: ferma il pagamento solo sopra la soglia DAC7
   (`fase83_server.py:6045-6054`), e DAC7 è spento di serie (`fase100_dac7.py:24`).
4. 🟠 **Gli costa il 7% invece del 5%** sugli annunci non in euro (`main_casavip.py:151`,
   `fase59_concierge.py:348-350`), perché il nostro conto è italiano e tiene solo euro
   (`fase188_paga_struttura.py:45-47`). È corretto per i nostri conti — ed è **il doppio di quello
   che l'email gli ha promesso** (B16 punto c).
5. ⚠️ **Non sappiamo, e non è scritto da nessuna parte, dove Stripe Connect operi davvero.** Non
   esiste **nessuna tabella per paese sui soldi**: l'unica per nazione riguarda il marketing
   (`fase154_giurisdizioni_marketing.py`), non i pagamenti.

> ⚖️ **DECISIONE DEL FONDATORE (2026-08-24): APRIRE UN PAESE ALLA VOLTA, NON IL MONDO.** Il
> prodotto non si blocca per diventare globale: si aggiunge un paese quando quel paese ha le sue
> quattro cose — Stripe che paga lì, il contratto nella sua lingua con la sua legge, il dato
> bancario giusto (non per forza IBAN), e la tariffa detta com'è. ⛔ Finché non è così, quel paese
> non si recluta.

### 🟠 B21 — L'HREFLANG DELLA HOMEPAGE: UNA DECISIONE DA PRENDERE (D16), NON UN LAVORO DA FARE
*(2026-08-26, aperto insieme alla dotazione SEO della homepage.)* La homepage ha ora
description, canonical assoluto self-referente e le quattro `og:` — e **non** ha hreflang, per
scelta del fondatore. Le tre misure che tengono aperta la decisione:

```
python -c "import fase97_inbound_seo as f; print(len(f.locali_hreflang()))"   -> 25
grep -n "SUPP *=" deploy/index.html    -> 277:const SUPP = ['it','en','es','fr','de','pt','ja','zh']   (8)
grep -n "BV.linguaIniziale" -A 6 deploy/app.js   -> 97: legge localStorage e navigator.languages, MAI location.search
```

**Il nodo:** l'hreflang ha senso solo se ogni locale ha un **URL distinto**. La homepage non
onora `?lang=`, quindi oggi `https://bookinvip.com/?lang=de` servirebbe **la stessa identica
pagina** di `/` — 25 URL, un contenuto solo: duplicato, cioè peggio del niente che c'era prima.

**Le due strade, e costano cose diverse:**
- **(a) onorare `?lang=`** — si tocca `deploy/app.js` (`BV.linguaIniziale` legge anche
  `location.search`) e `deploy/index.html` (25 `<link rel="alternate">` + x-default). Entrambi
  sono `deploy/`, cioè **produzione**: serve «autorizzato». E resta uno scarto da sanare: la
  homepage parla **8** lingue, `locali_hreflang()` ne dichiara **25**. Un hreflang che promette
  una lingua che il selettore non ha è la stessa famiglia di B8.
- **(b) restare a un URL solo** — niente hreflang sulla homepage, e si scrive **perché**, così
  fra sei mesi nessuno lo rimette per abitudine. Costo zero, targeting per-paese perso.

⚠️ **Contrasto trovato per strada, da chiudere con la decisione:** fase97 dichiara **tre** cifre
diverse sulle proprie lingue — docstring riga 17 «Multilingua (**5 lingue**)», `LINGUE` riga 28
= **13**, testo **pubblico** `llms_txt()` riga 750 (servito su `/llms.txt`) «230+ città in **13
lingue**» — mentre `locali_hreflang()` ne produce **25** e la homepage ne serve **8**. Cinque,
tredici, venticinque, otto: quattro numeri per la stessa domanda. Nessuno è stato toccato.

### 🟠 B15 — `--scopo` MEMORIZZA I FILE MA NON IL **PERCHÉ**, E ACCETTA OPZIONI CHE NON ESISTONO
*(2026-08-24.)* La regola ferrea 15 pretende due cose: **quali** file si toccheranno e, se
l'elenco si allarga, **perché**. `collaudi/prima_di_lanciare.py --scopo` sa memorizzare solo
la prima. `scrivi_scopo` (riga 518-528) scrive un'intestazione col commit e poi **l'elenco dei
file, e basta**: non c'è nessun campo dove mettere la motivazione. La metà della regola che
spiega *perché* si è allargato lo scopo non ha un posto dove vivere, quindi muore con la
sessione.

⛔ **E il secondo pezzo è peggio del primo: le opzioni inesistenti passano in silenzio.**
`prima_di_lanciare.py:655-656` fa `scopo = argv[argv.index("--scopo") + 1:]`, cioè prende
**tutto** ciò che segue come nomi di file. Lanciando `--scopo <file> --perche "<testo>"` —
un'opzione che **non esiste** — lo strumento non protesta: si mette in elenco anche
`--perche` e la frase intera, come se fossero due file.

> 🔴 **È già successo, oggi, sul commit `ab52d0d`** (unito in `584f0e9`): la traccia
> conteneva **10 voci invece di 8**. Non ha prodotto falsi rossi — il controllo 9 del
> pre-fatto verifica che i file *toccati* stiano **dentro** l'elenco, e voci in più non lo
> fanno fallire — ma quel commit è passato con una dichiarazione sporca, e nessuno se ne
> sarebbe accorto. È la famiglia degli sbagli **S2/S12**: inventare un nome invece di
> leggerlo, e uno strumento che tace invece di gridare.

**Da estendere**, e sono due lavori distinti: (a) un posto dove scrivere il perché (una riga
`# perche: …` nella traccia, letta e ristampata dal pre-fatto); (b) `--scopo` deve **rifiutare**
un argomento che comincia con `--` invece di prenderlo per un file.

#### 📌 IL PERCHÉ DEI TRE FILE NON COMMITTATI DI OGGI — scritto qui perché la traccia non può tenerlo
`CLAUDE.md` · `RIPRENDI_QUI.md` · `deploy/index.html` restano **non committati** sul disco.
**Lavoro parziale su B8+B9+B10 (Anti-Rimpianto): deciso il 2026-08-24 di portarli via nel giro
unico invece di pagare due volte suite e CI** (~35 min di suite + ~26 min di CI + ~6-10 min di
deploy a giro). Lo scopo è dichiarato sulla traccia in `%TEMP%`, ma quella tiene solo i tre
nomi: la ragione è questa riga.

### 🟠 B14 — L'ETICHETTA «Ran» DEL RIQUADRO PORTA IL NUMERO SBAGLIATO
*(2026-08-24.)* Il riquadro STATO MISURATO scrive `SUITE ATTUALE: Ran 6012 test`, ma **6012 è
il numero del caricatore**: il giro vero ne esegue **6007** (i 5 di scarto sono le guardie
`openssl`, già spiegate due righe sotto). La guardia confronta col caricatore, quindi è verde
e resta verde: è **l'etichetta** a dire una cosa per un'altra, ed era già così prima
(`Ran 5985` con 5938 eseguiti). Si corregge al prossimo giro che tocca i `.md` — da sola
costerebbe una suite intera per una parola (regola ferrea 6).

> 🟡 **2026-08-24, secondo passaggio: METÀ FATTA, e la metà che manca NON è una parola.**
> Il riquadro ora porta **due voci separate e misurate** — `CARICATORE (RACCOLTI): 6012` e
> `ESEGUITI (ultimo giro): 6007` — più `SCARTO: 5`, e dice a chiare lettere che la riga
> `SUITE ATTUALE: Ran 6012 test` è **un aggancio per la guardia**, non un'affermazione su
> quanti test siano stati eseguiti. Chi legge non può più sbagliarsi.
>
> ⛔ **Ma la riga con la parola «Ran» è ancora lì, e deve restarci.** La pretende alla lettera
> `test_pipeline_ci.py:2054` (`SUITE ATTUALE: Ran (\d+) test`) e la ri-pretende la meta-guardia
> a `:5636` e `:5652`, che inietta un conteggio sbagliato su quella stessa forma per verificare
> che la guardia se ne accorga. **Toglierla o rinominarla manda rossa la CI.**
>
> 🔑 **Quindi B14 non si chiude in un `.md`: si chiude cambiando quella regex** perché legga
> un'etichetta onesta (es. `CARICATORE (RACCOLTI): N`), **e insieme a lei la meta-guardia che
> la mette alla prova** — altrimenti la prova inietta su una forma che non esiste più e diventa
> un ornamento. È lavoro su file di test, non su un documento: **va chiesto a parte**, e da solo
> costerebbe una suite intera (regola ferrea 6). Resta 🟠, e adesso si sa esattamente cosa
> costa: due punti in un file, non una parola in un altro.

### 🟠 B13 — I QUATTRO CLAMP DIFENSIVI DI `fase59` SONO CODICE CHE NON FA NIENTE
*(dal giro di mutazione del 2026-08-24, B5.)* Le righe **318, 320, 338, 494** di
`fase59_concierge.py` sono controlli il cui confine **non è osservabile**: dimostrato, e le
dimostrazioni stanno nello schedario degli equivalenti con la loro impronta.

> `if not _intero(comm) or comm < 0: comm = 0`   → a `comm == 0` assegna 0 a chi vale già 0
> `if comm > netto: comm = netto`                → a `comm == netto` riassegna `netto`
> `tassa = t if (_intero(t) and t >= 0) else 0`  → a `t == 0` i due rami danno lo stesso 0
> `cr = cr if (_intero(cr) and cr > 0) else 0`   → a `cr == 0` i due rami danno lo stesso 0

**È la terza uscita della DO-178C**: non manca un test e non manca un requisito — il codice è
estraneo e va tolto. È la strada già scelta il 2026-08-12 sulla tassa, con l'oracolo prudente
a fare da testimone (`collaudi/oracolo_tassa.py`).

⛔ **È il motore che calcola OGNI prezzo: serve «autorizzato».** Non toccato il 2026-08-24 per
decisione del fondatore. Se si toglie, le quattro voci dello schedario vanno tolte con lui — e
decadrebbero comunque da sole, perché la loro impronta non troverebbe più il codice.

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
- 2026-08-24, passaggio 5 di B19: regola B2 violata, cinque correzioni al referto fatte con
  heredoc invece che con l'editor. Il risultato è corretto, il file non è troncato. Segnato
  per memoria.

---

# 🧭 PASSAGGIO DI CONSEGNE — 2026-08-24 notte

## 📍 DOVE SIAMO — misurato adesso, non ricordato

| Posto | Valore | Come si ricontrolla |
|---|---|---|
| **Computer** | `df5951a`, ramo `master` | `git rev-parse --short HEAD` |
| **GitHub** (`origin/master`) | `df5951a` | `git ls-remote origin refs/heads/master` |
| **VPS** (`git HEAD`) | `df5951a` | `ssh … 'cd /var/www/bookinvip && git rev-parse --short HEAD'` |
| **Immagine viva** | `sha256:859f637a…` = codice di **`df5951a`** | `docker inspect --format='{{.Image}}' casavip_app` |

✅ **TUTTI E QUATTRO ALLINEATI.** È la prima volta dopo tre giorni.

> ✅ **IL DEPLOY È STATO FATTO — 2026-08-24, 00:15-00:17.** Era stato rimandato di qualche ora
> per decisione del fondatore (*«tocca il codice e voglio la testa fresca»*), e si è fatto
> subito dopo, un passo alla volta col suo OK fra uno e l'altro.
>
> ⛔ **E IL PARACADUTE ERA AGGANCIATO ALL'IMMAGINE SBAGLIATA — la quinta volta.**
> Prima del passo 1: `:prec` → `sha256:6bb0933f`, immagine viva → `sha256:80f21d84`. **Due cose
> diverse.** Se il deploy fosse andato male, saltare col paracadute ci avrebbe riportati a
> un'immagine di giorni prima, **non** all'ultimo stato buono. Non l'ha evitato la memoria:
> l'ha evitato il fatto che `DEPLOY.md` §[1b] lo prescrive e la verifica **confronta l'Id**.
>
> **La prova che la riparazione è viva, misurata sul CONTENUTO e non sulla data:**
> ```
> sha256 di fase83_server.py dentro il contenitore : 8e525d20f0fb56d8
> sha256 dello stesso file ricostruito da git      : 8e525d20f0fb56d8
> `_commissione_regalabile` nel contenitore        : 3 volte  (prima: 0)
> ```
> **Numeri del deploy:** finestra senza sito **29 secondi**, totale **40 secondi**, catena con
> esito 0. Log d'avvio: **0** righe con traceback o critical.
> **Dopo:** `verifica_produzione.py` **190 controlli, 0 violazioni** · `https://bookinvip.com/`
> **HTTP 200 in 0,564 s** misurato dal computer del fondatore, non dal server.
> **Il ritorno indietro è pronto:** `:prec` → `sha256:80f21d84`, cioè l'immagine di prima.
> ⚠️ Il certificato è valido ancora **30 giorni** (rinnovo automatico, ma il numero è questo).

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
