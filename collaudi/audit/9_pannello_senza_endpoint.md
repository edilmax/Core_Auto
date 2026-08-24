# B19 — PASSAGGIO 9 · TUTTO QUELLO CHE IL FONDATORE VEDE NEL PANNELLO E CHE NON CORRISPONDE A UN ENDPOINT VERO

> **Referto di misura, non lista di cose da fare.** Sola lettura: nessun file di prodotto è
> stato toccato, nessuna riparazione fatta, nessuna suite eseguita, nessun commit, nessuna
> chiamata all'API, nessun giro sul VPS, nessun server avviato.
> Misurato il **2026-08-25**, su `HEAD = 584f0e9`, ramo `master`
> (`git status --porcelain`: modificati `CLAUDE.md`, `RIPRENDI_QUI.md`, `deploy/index.html`
> + la cartella non tracciata `collaudi/audit/`; **nessun `fase*.py` toccato, nessun file
> sotto `deploy/` toccato da me**).
>
> Perimetro, come lo definisce il passaggio: **ogni bottone, link e istruzione dei pannelli
> (`admin.html`, `bunker.html`, `host.html`) confrontato con le rotte che il server espone
> davvero.** Ho aggiunto due cose al perimetro, e lo dichiaro: **le pagine di ingresso
> costruite dal server in Python** (`pagina_login_gate`, `fase83_server.py:1540-1700` — è lì
> che l'host si registra davvero, non in `host.html`) e **`deploy/guida-operativa.html`**, che
> non è un pannello ma è *l'istruzione operativa che il fondatore segue*: escluderla avrebbe
> lasciato fuori metà della voce n. 1.

---

## RISULTATO IN UNA RIGA

**10 punti in cui il pannello promette una porta chiusa** — 🔴 **3 gravi** · 🟠 **6 medi** ·
🟡 **1 minore** — più **14 rotte vive che nessun pannello apre** (contate a parte, sezione
🔵), **15 sospetti verificati e scartati** (scritti apposta perché non si riaprano) e **3
conferme indipendenti** di difetti già contati dai passaggi 2, 6 e 8, **segnalate e NON
risommate**.

---

## 🔑 LA FORMA DI FAMIGLIA — e non è quella che mi aspettavo

Cercavo bottoni scollegati. **Non ce n'è uno.** Il cablaggio meccanico dei tre pannelli è
pulito su quattro sonde indipendenti, tutte a zero:

| sonda deterministica | denominatore | difetti |
|---|---|---|
| ogni `onclick`/`onchange` chiama una funzione che esiste | **97 bottoni + 13 link** | **0** |
| ogni campo JSON che il pannello legge, il codice Python lo produce | **~1.900 accessi `d.campo`** | **0** |
| ogni chiave che il pannello invia, il codice la nomina | tutti i `JSON.stringify` + querystring | **0** |
| il metodo HTTP del pannello combacia con quello della rotta | **89 chiamate** | **0** |

E poi:

> ### ⛔ **Dove il pannello CHIAMA, torna tutto. Dove il pannello RACCONTA, non torna niente.**
> Tutte e 10 le voci di questo referto stanno in un **testo**: un'intestazione, una riga di
> aiuto, un'istruzione. **Il motivo è misurabile, non filosofico:** le chiamate sono coperte
> da una guardia (i collaudi le percorrono, un endpoint sbagliato dà 404 e il test cade), i
> **testi non li confronta nessuno con il codice**. È la stessa forma del passaggio 6 («il
> confine della traduzione completa coincide col confine di dove arriva una guardia»), vista
> da un'altra faccia.

⚠️ **E le tre voci gravi non sono tre errori scollegati: sono tre punti in cui il testo
descrive un pezzo di macchina che non è mai stato costruito** — la schermata dei bonifici,
il documento che l'host firma, la cancellazione completa. In tutti e tre il pannello è
l'unico posto dove quella cosa esiste.

---

## DENOMINATORE DICHIARATO

| grandezza | numero | come è stata misurata |
|---|---|---|
| pannelli letti riga per riga | **3** | `admin.html` 812 righe · `bunker.html` 675 · `host.html` 1.612 = **3.099 righe** |
| pagine di ingresso generate in Python | **1** | `pagina_login_gate` (admin/host/bunker), `fase83_server.py:1540-1700` |
| pagina di istruzioni aggiunta al perimetro | **1** | `deploy/guida-operativa.html` (8 lingue) |
| **rotte** esposte dal server vero | **164**, di cui **135** `/api/…` | scanner di sessione sul `_instrada` + `do_GET`/`do_POST` di `fase83_server.py` (`==`, `in ()`, `startswith`, `u.path`) |
| sezioni visibili nei tre pannelli | **53** | `admin` 9 (5 `<h2>` + 4 blocchi con titolo in linea) · `bunker` 15 · `host` 29 |
| bottoni / link | **97 / 13** | conteggio sui tre file |
| endpoint distinti chiamati dai pannelli | **89** | `admin` 21 · `bunker` 20 · `host` 48 |
| **voci di dizionario italiane lette una per una** | **671** | `admin` 152 · `bunker` 203 · `host` 316 — tutte e tre in **8 lingue** |
| tabelle di produzione con una colonna host | **8** | scanner AST/regex su tutti i `CREATE TABLE` dei `fase*.py` (56 tabelle censite) |
| punti del server che guardano il kill-switch | **5** | `grep _transazioni_bloccate` in `fase83_server.py` |

### Gli attrezzi, e perché ce ne sono voluti sette

1. **Inventario delle rotte** (scanner di sessione): il server **non è Flask**, è un
   `BaseHTTPRequestHandler` con una catena di `if` (`fase83_server.py:1902-2185`) più il
   dispatch statico in `do_GET` (`:10716-11014`). Un `grep @app.route` qui trova **10 rotte
   morte** in `fase13`/`fase36` e **zero** di quelle vere: l'inventario va costruito sulle
   quattro forme (`path ==`, `path in ()`, `path.startswith`, `u.path ==`). **164 rotte.**
2. **Diff chiamate → rotte** per ognuno dei tre pannelli, con **il metodo HTTP**.
3. **Sonda sui bottoni**: ogni gestore inline, ogni `id` usato dal JS contro ogni `id`
   presente nell'HTML.
4. **Sonda sui campi**: ogni `d.campo` letto dai pannelli contro ogni stringa dei 152 moduli
   di produzione.
5. **Sonda sull'invio**: ogni chiave spedita in un `JSON.stringify` o in querystring.
6. **Sonda inversa** (rotte orfane): le 135 rotte `/api` contro **tutte** le pagine —
   statiche *e* generate in Python.
7. **Lettura a mano delle 671 voci di dizionario**, una per una, con la domanda: *questa
   frase descrive qualcosa che il codice fa?* È l'unico attrezzo che ha trovato qualcosa —
   **10 voci su 10**.

⛔ **Nessun numero di questo referto viene dall'esecuzione del codice.** Sono tutti **letti**
dai file.

---

# 🔴 LE TRE GRAVI

## 1. **La «dashboard payout» non esiste** — e ci mandano TRE testi, in 8 lingue su 8

Il gesto che fa uscire i soldi verso l'host è istruito in tre punti diversi. Nessuno dei tre
porta da qualche parte.

| dove | testo (italiano) | lingue |
|---|---|---|
| `deploy/bunker.html:119` (`conf_p`, dizionari alle righe **214-221**) | «…si sbloccano da soli appena completano i dati dal pannello. **Per pagare comunque a mano: dashboard payout, come sempre.**» | **8/8** — misurato: `it,en,es,fr,de,pt,ja,zh` contengono tutte il rimando |
| `deploy/guida-operativa.html:96` (`c5_1`, dizionari alle righe **126-133**) | «Apri il **pannello host** o il tuo cruscotto: la **dashboard payout** ti dice, **per ogni host**, quanto ha **maturato**.» | **8/8** — verificato chiave per chiave |
| `deploy/host.html` (`sc_p`, riga 503) | «Senza collegamento, il pagamento arriva con **bonifico manuale**.» — è la promessa fatta **all'host** | **8/8** |

**Cosa c'è davvero:**

- Su **135 rotte `/api`** l'unica che contiene la parola `payout` è **`/api/host/payout`**
  (`fase83_server.py:2059`), ed è **host-auth**: risponde all'host per sé stesso, mai al
  fondatore, mai «per ogni host».
- **Nessuna sezione** dei tre pannelli elenca i bonifici dovuti: `admin.html` ha 9 sezioni
  (annunci, ricerca, verifiche, bunker, marketing, rimborsi-da-eseguire, controversie,
  cancellazione, come-funziona) e la parola `payout` compare solo dentro la scheda di
  **audit di UNA prenotazione** (`admin.html:465,480`).
- `fase131_payout_dashboard.py` esiste, ma **`da_pagare()` a `:332` non ha un solo
  chiamante** — misurato dal **passaggio 4**, riconfermato qui con lo scanner delle rotte:
  nessuna rotta lo espone.
- Il più vicino è `/api/bunker/dac7_conformita`, che mostra `payout_fermi_cents` **solo per
  gli host “urgenti”** (`deploy/bunker.html:342-344`: `h.urgente && h.payout_fermi_cents>0`)
  — cioè solo quelli sopra soglia DAC7 e con dati mancanti.

**Perché è la voce che pesa di più.** Il **passaggio 3** ha misurato che *nessuno scrive mai
lo stato `pagato`*. Il **passaggio 4** ha misurato che *la funzione che direbbe quanto pagare
non la chiama nessuno*. Qui si chiude il cerchio: **anche lo schermo da cui si farebbe non
c'è**, e tre testi in otto lingue dicono al fondatore di aprirlo. E c'è un quarto rimando,
dentro il codice: `fase83_server.py:2974` — lo storno di una penale rimette il riscosso «in
`da_pagare` per bonifico **MANUALE**».

> ⚖️ **Quale delle due:** il testo è sbagliato **oppure** manca la schermata — e la scelta è
> del fondatore. Ma **finché non c'è nessuna delle due**, l'host senza Stripe collegato
> (`fase83_server.py:6301-6305`, l'aggravante di **B17**) non ha nessun percorso per essere
> pagato che qualcuno possa eseguire.

---

## 2. **Al gate di registrazione, la casella «Accetto il Contratto Host» apre i TERMINI DI SERVIZIO**

- **La riga:** `fase83_server.py:1617` →
  `'<input type="checkbox" id="c1"> Accetto il <a href="/termini.html" …>Contratto Host</a>'`
- **`/termini.html` non è il contratto.** `deploy/termini.html:31` dichiara `const DOC =
  'termini'` e carica il testo da `/api/legale/documento` (rotta `fase83_server.py:1923`,
  motore `fase185_testi_legali`). Il **Contratto Host** è un altro documento, con un'altra
  rotta (`/api/legale/contratto-host`, `:1925`) e un'altra pagina
  (`deploy/contratto-host.html`).
- **E la prova firmata registra il documento giusto, quello NON mostrato.** La stessa pagina,
  a `:1606-1607`, importa `CONTRATTO_HOST_VERSIONE` e `doc_sha256()` da
  `fase163_accettazioni` e li spedisce nella registrazione (`:1631-1634`,
  `doc_sha256:'%s',versione:'%s'`). Risultato: **la prova HMAC dice che l'host ha accettato
  l'impronta del Contratto Host; il link che ha davanti gli mostra i Termini.**
- **Non è un caso di poco conto:** il commento a `:1601-1605` dice che la registrazione
  avviene **QUI** e non più in `host.html` («il form dentro host.html gated era
  IRRAGGIUNGIBILE»). Quindi questa è **la pagina su cui gli host veri si registrano**.
- **Come si vede che è un errore e non una scelta:** `deploy/host.html:97` e `:136` linkano
  `/contratto-host.html` — il documento giusto. Due pagine dello stesso prodotto, due link
  diversi sotto la stessa etichetta.

⚠️ Il difetto delle **lingue** di quel link è già contato dal **passaggio 6** (il server
ripiega su `en`, la pagina su `it`, `host.html` linka senza `?lang=`). **Qui il difetto è
un altro: è il documento sbagliato, in tutte le lingue.**

---

## 3. **«Cancella attività host — da OGNI archivio, e verifica che non resti nulla»: gli archivi sono 5, e il pannello stampa «tutti 0»**

- **Il testo:** `deploy/admin.html` (`del_p`, riga 201) — «Rimuove un host e **TUTTI** i suoi
  dati da **ogni archivio** (annunci, inventario, messaggi, referral, account) **e verifica
  che non resti nulla da nessuna parte**. Irreversibile.» Più l'esito che il pannello stampa:
  `verif_res` = «**Verifica residui (tutti 0)**» e `canc_ok` = «✅ **Cancellato OVUNQUE**».
- **Cosa cancella davvero** (`fase156_erasure.py:206-215`, chiamata da
  `fase83_server.py:4352-4353`): **5 archivi** — `inventario`, `alloggi`, `messaggi`,
  `referral`, `host`.
- **Cosa verifica** (`:218-232`): **gli stessi 5**. E `rep["ok"]` (`:235`) è `True` se quei
  cinque sono a zero — `all(v == 0 for v in residui.values())`. Il pannello mostra `ok` e
  scrive «Cancellato OVUNQUE».
- **Cosa resta.** Scanner sui `CREATE TABLE` di tutti i `fase*.py`: **8 tabelle** hanno una
  colonna host. Cinque le tocca l'erasure; **sei no** (una è la stessa `messaggi`, già
  contata):

  | tabella | file:riga | cosa contiene |
  |---|---|---|
  | `payout` | `fase131_payout_dashboard.py:78` | quanto ha maturato / in transito / trattenuto |
  | `kyc` | `fase143_kyc_host.py:61` | stato ed estremi della verifica d'identità |
  | `accettazioni` | `fase163_accettazioni.py:417` | **IP, dispositivo, data/ora, firma HMAC** dei consensi |
  | `pendenti` | `fase162_pagamenti_pendenti.py:61` | i pagamenti della sua struttura |
  | `debiti` | `fase177_financial_controller.py:175` | note di debito aperte |
  | `wizard` | `fase141_onboarding_wizard.py:90` | lo stato dell'onboarding |

- ⚖️ **Quale delle due.** Diverse di queste tabelle **si conservano a ragione**: le
  accettazioni sono la prova legale del consenso, il giornale dei soldi non si buca (e infatti
  `obblighi_pendenti`, `fase156:46-135`, **blocca** la cancellazione se ci sono payout dovuti
  o escrow aperti — legge **più** archivi di quanti ne cancelli). **Il difetto non è che
  restino: è che il pannello dica «da nessuna parte» e stampi «tutti 0» a un fondatore che
  sta rispondendo a una richiesta GDPR.** La riparazione onesta è una riga di testo che
  distingue *cancellato* da *conservato per obbligo di legge* — non un DELETE in più.

---

# 🟠 LE SEI MEDIE

## 4. Il kill-switch dice «congela **tutti** i movimenti di denaro»: tre gestori non lo guardano

- **Il testo:** `deploy/bunker.html:64` (`ks_p`, riga 214) — «**Congela subito tutti i
  movimenti di denaro.** Il sito resta navigabile. Solo in emergenza.»
- **La guardia esiste in 5 punti** (`_transazioni_bloccate`, `fase83_server.py:5173-5181`):
  `_book` `:5188` · `_admin_rimborso` `:4370` · `_admin_rimborsa_dovuto` `:4728` ·
  `_trasferisci_all_host` `:6173` (il bonifico all'host allo sblocco escrow) ·
  `_forse_penale_struttura` `:6943`.
- **Manca in tre gestori che muovono o scrivono soldi** (sonda di sessione: confini di ogni
  metodo della classe + ricerca della guardia dentro il corpo):

  | gestore | file:riga | cosa fa senza guardia |
  |---|---|---|
  | `riscuoti_debiti_carta` | `fase83_server.py:7916-7948` | **addebito off-session vero sulla carta dell'host** (`fc.riscuoti_da_carta`, `:7941`) — 🔒 oggi dormiente: `SCATTO3_ATTIVO` default `"0"` (`:7921`) |
  | `_split_paga` | `:7734-7770` | scrive «pagato» nel motore dei conti divisi (`eng.registra_pagamento`, `:7763`) |
  | `_admin_storno_penale` | `:2971-3003` | emette la nota di credito e rimette il riscosso in `da_pagare` (`:2994`) |

- 💡 **Il punto:** il kill-switch è l'unico comando d'emergenza del prodotto. Il primo dei tre
  è quello che conta: **il giorno in cui il fondatore accende `SCATTO3_ATTIVO`, il freeze
  smette di essere «tutti»** — e nessuno se ne accorgerà, perché il testo continuerà a dirlo.

## 5. «Aggiungendo una carta ottieni il badge **Host Verificato+** e **bonifici prioritari**»: nessuna delle due cose esiste

- **Il testo:** `deploy/host.html:263` (`ca_p`, riga 503).
- **Il badge:** l'unico posto dove compare è **il pannello dell'host stesso**
  (`deploy/host.html:1380`: `'✓ Carta collegata — Host Verificato+'`) e due **docstring**
  (`fase183_carta_offsession.py:13-14`, `fase83_server.py:7872`). Cercato in tutta la
  produzione: **zero** occorrenze in `fase57_vetrina.py`, nel catalogo, nella scheda pubblica
  o in qualunque risposta che un ospite riceva. **Nessun ospite vedrà mai quel badge**: è una
  frase che l'host legge a se stesso.
- **I bonifici prioritari:** `fase131_payout_dashboard.py:273` e `:298` — le due sole query di
  estrazione — ordinano `ORDER BY ts, prenotazione_id`. **Nessuna riga del prodotto guarda la
  carta per decidere l'ordine dei pagamenti.**
- ⚠️ E la carta salvata serve a una cosa sola (`ca_p`: «saldare una penale che i tuoi incassi
  futuri non coprono»), che oggi è **dormiente**: `SCATTO3_ATTIVO=0` (voce 4). Quindi il
  pannello chiede un dato di pagamento in cambio di **due benefici inesistenti** e di **un
  uso spento**.

## 6. «Il resto va da solo (prenotazioni, pagamenti, **marketing**)»: il marketing automatico è spento di serie

- **Il testo:** `deploy/admin.html:120` (`how3`, riga 201) — la riga «come funziona», la prima
  che il fondatore legge entrando.
- **Il codice:** l'auto-pubblicazione delle campagne parte **solo** se `CAMPAGNA_AUTO_GIORNI`
  è valorizzata (`fase83_server.py:10512-10526`, `fase94_scheduler_campagna`), e in
  `.env.casavip.example:92` è **vuota**. Non esiste nessun `_tick_` di marketing: i sei tick
  del server (`:11047`, `:11083`, `:11134`, `:11155`, `:11182`, `:11227`) sono garanzia,
  guardiano, hold, promemoria, invito-recensione, marca temporale.
- Nello stesso pannello, tre righe sotto, c'è il bottone **«📣 Pubblica campagna»**
  (`admin.html:167`): cioè l'unico modo di pubblicare è **a mano, da lì**.
- ⚠️ **NON MISURATO:** il valore di `CAMPAGNA_AUTO_GIORNI` sul VPS. Nel codice il default è
  «spento».

## 7. Il pannello marketing promette «post **multilingua**» e offre **5 lingue su 8**

- **Le caselle:** `deploy/admin.html:161-165` — `it`, `en`, `es`, `fr`, `de`. **Mancano
  `pt`, `ja`, `zh`**: dal pannello quelle tre lingue non si possono nemmeno chiedere.
- **Il testo accanto** (`mk_p`, riga 201): «Genera post **multilingua** + immagini promo».
- **Perché è una voce nuova e non un doppione del passaggio 6:** il passaggio 6 ha misurato il
  **motore** (`fase90_marketing.py:272` scarta `ja/pt/zh` in silenzio, mentre `:141` prova che
  le 8 erano sotto gli occhi). Qui il difetto è **prima**: è la casella che non esiste nel
  pannello. Sono due difetti che si nascondono a vicenda — riparato il motore, il pannello
  continuerebbe a offrire cinque lingue; riparato il pannello, tre lingue verrebbero scartate
  in silenzio dal motore.

## 8. «Dati personali: visibili solo da qui, mai nel pannello operativo» — si scaricano dal pannello operativo

- **Il testo:** `deploy/bunker.html:170` (`pl_p`, riga 214) — «Dati personali: **visibili solo
  da qui**, mai nel pannello operativo.»
- **Il bottone:** `deploy/admin.html:587` (`ky_fasc`, «Fascicolo») chiama
  `/api/admin/verifiche/fascicolo`.
- **Cosa restituisce** (`fase83_server.py:2880-2924`): `codice_fiscale`, `partita_iva`,
  `indirizzo_fiscale`, `paese`, **`iban`**, `data_nascita`, telefono, `stripe_account_id` e
  **`contratto_prove`** (che è proprio l'elenco con **IP** e dispositivo di cui il bunker dice
  «solo da qui»).
- **Il cancello è vero ma condizionato:** `_bunker_ok_o_field` (`:3082-3095`) — «Bunker NON
  configurato → **True**: l'enforcement è INATTIVO». Cioè: **se il super-admin non è
  configurato, il fascicolo completo esce con la sola chiave admin**, dal pannello operativo,
  esattamente come dice di non fare la frase del bunker.
- ⚠️ **NON MISURATO:** se il Bunker sia configurato sul VPS. Con Bunker configurato la frase
  resta comunque imprecisa (il dato **esce da admin.html**, non «solo da qui»); senza Bunker
  configurato è falsa e basta.

## 9. «Paga in struttura»: nello stesso pannello, «l'ospite paga sempre il prezzo pulito, 0%» e «l'ospite paga una piccola fee»

- **L'interruttore:** `deploy/host.html:396`, `id="p_paga_struttura"`, **acceso di serie**
  (`checked`, e a `:1218` `d.paga_in_struttura!==false` → default ON), etichetta
  `l_paga_str`/`h_paga_str` (riga 503): «— l'ospite paga di persona all'arrivo… **Incassi
  uguale; l'ospite paga una piccola fee di servizio.** Consigliato attivo.»
- **Le altre due frasi dello stesso pannello:** `h_prezzo_osp` → «**L'ospite paga 0%**» ·
  `co_n` → «**L'ospite paga sempre il prezzo pulito, 0% a suo carico**».
- **Cosa fa l'endpoint che quell'interruttore accende** (`fase188_paga_struttura.py`, chiamato
  da `fase83_server.py:5213` → `_forse_paga_struttura` `:5309`):
  - `:37` `FEE_PER_NOTTE_CENTS = 150` → **+1,50 € a notte a carico OSPITE** (`:88`, `fee`);
  - `:80` `gateway_cents` → **copertura carta assorbita dall'HOST** (0,55 € + 3,25%, +2% in
    valuta estera), quindi `host_incassa = prezzo − commissione − gateway` (`:81`).
- 🔴 **Il flag è cablato bene** (`fase57_vetrina.py:143,356-357,467,558-590,1143` — colonna,
  default, scrittura, lettura): non è un interruttore finto. **Il difetto è che le due frasi
  non possono essere vere insieme**, e quella che l'host legge quando accende
  l'interruttore («incassi uguale») è la meno vera delle due.
- ⚠️ Il conflitto **fase188 (3,25% + 0,55) contro il contratto firmato (5% + 0,25)** è già
  contato dal **passaggio 8**: qui non lo risommo. Questa voce è un'altra: **il pannello
  contro se stesso, sulla stessa schermata**.

---

# 🟡 LA MINORE

## 10. «La Sala di controllo (**/bunker**)» — quell'indirizzo è un 404

- **Il testo:** `deploy/admin.html:110` (`bk_p`, riga 201) — «La password super-admin apre la
  **Sala di controllo (/bunker)** e arma per 15 minuti le operazioni delicate.»
- **Le rotte vere:** `/bunker.html` (servita gated, `fase83_server.py:11011-11012`) e
  `/entra-bunker` (`:11002`). **`/bunker` non esiste**: l'unico ripiego «senza estensione» è
  per `/grazie` e `/annullato` (`:11007-11010`); tutto il resto cade su `_statico(u.path)`
  (`:11014`) → `deploy/bunker` non è un file → 404.
- Il **bottone** invece è giusto (`admin.html:241`, `location.href='/bunker.html'`): sbaglia
  solo l'indirizzo stampato, cioè quello che uno digita a mano o incolla in una chat.

---

# 🔵 LE PORTE APERTE CHE NESSUN PANNELLO APRE — **contate a parte (14)**

Sonda inversa: le **135 rotte `/api`** contro **tutte** le pagine (statiche *e* generate in
Python). 27 grezze; tolte 8 di infrastruttura (`/api/health/*` ×4, i due webhook Stripe e
Telegram, `/api/mcp`, `/api/concierge/manifest`) e 5 falsi positivi (le tre `garanzia/*` le
chiama la pagina voucher costruita a `fase83_server.py:1030`; `richieste/approva|rifiuta`
sono concatenate in `host.html:688`), **restano 14**:

| rotta | server | chi la chiama oggi |
|---|---|---|
| **`/api/bunker/guardiano`** | `:2157` | **solo `collaudi/giro_banco.py:522`** |
| **`/api/bunker/invarianti`** | `:2155` | **solo `collaudi/gare_estreme.py:339`, `multivettore.py:255`** |
| **`/api/bunker/stato`** | `:2127` | **solo `collaudi/giro_banco.py:521`, `verifica_produzione.py:127`** |
| **`/api/admin/diagnosi`** | `:2123` | **solo `collaudi/verifica_produzione.py:132`** |
| `/api/admin/partner` | `:1933` | nessuno — *già contato dal passaggio 2* |
| `/api/host/accettazioni` | `:2081` | nessuno |
| `/api/host/invito` · `/invito/qualifica` · `/invito/registra` | `:2003,:2009,:2007` | nessuno — è il **secondo motore referral**, *già contato dal passaggio 8* |
| `/api/split/crea` · `/split/paga` · `/split/stato` | `:1991,:1993,:1995` | nessuno: `index.html` chiama **solo** `/api/split/preview` → **si può fare l'anteprima di un conto diviso, non crearlo** |
| `/api/tassa` | `:1989` | nessuno |
| `/api/lingue` | `:1919` | nessuno |

> 🔴 **Le prime quattro sono l'immagine speculare della voce 1, ed è la cosa più strana di
> tutto il passaggio.** Il **guardiano degli stati impossibili** e gli **invarianti (i
> teoremi sui soldi)** hanno una rotta viva, autenticata, funzionante — e **l'unico posto del
> mondo da cui vengono interrogati è la cartella dei collaudi**. La Sala di controllo, che ha
> 15 schede per integrità, DAC7, riconciliazione, marche temporali e log, **non ha una scheda
> per il guardiano**. Il fondatore vede il battito solo se legge `/api/health` a mano.
> ⛔ Non è la classe che questo passaggio doveva contare (pannello → endpoint mancante):
> è l'inverso. **Per questo sta qui sotto e non è sommata alle 10.**

---

# ✅ I 15 SOSPETTI VERIFICATI E SCARTATI

Scritti perché nessuno li riapra.

1. **Bottoni scollegati: zero.** 97 bottoni, 13 link, ogni `onclick` chiama una funzione che
   esiste. I 3 «`conScudo` non definita» sono `BV.conScudo` (`deploy/app.js:204`), i 7 «id
   mancanti» sono prefissi di id generati (`chat_`, `eur_`, `pct_`, `rdmsg_`, `dl_`…).
2. **Campi JSON letti e mai prodotti: zero.** Gli unici 5 residui sono API del browser
   (`.blob`, `.onclick`, `.onload`, `.unregister`) e `_http`, che è aggiunto da
   `app.js:123`.
3. **Chiavi inviate e ignote al codice: zero**, su tutti e tre i pannelli.
4. **Discordanze di metodo HTTP: zero** su 89 chiamate. I 2 candidati sono falsi positivi
   (`host.html:688` concatena `approva|rifiuta`; `host.html:1386` passa `{method:'POST'}`
   dentro `getJson`, che lo inoltra — `app.js:117-119`).
5. **«I bonifici dell'host verranno FERMATI finché non ripristini»** (`admin` `ky_rev_mot`):
   **vero** — `fase83_server.py:6061-6071`, e solo `revocato` blocca (il non-verificato no,
   come dice il commento).
6. **«I bonifici in sospeso stanno partendo»** dopo il salvataggio dei dati fiscali
   (`host` `fx_sbloccati`): **vero** — `:3144` `payout_riprovati`, gemello di `:2969` per la
   ri-verifica.
7. **«Il numero arriva dalla stessa funzione che addebita»** (`bunker` `sc_p`): **vero** —
   `:3864` importa `fase98_policy_commissione.stato_scaglione`.
8. **«Riscossione automatica sui prossimi bonifici»** (`bunker` `js_risc_auto`): **vero** —
   `fase177.riscuoti_debiti` chiamata nel flusso payout a `:6198-6200`.
9. **«Ogni giorno i registri vengono datati da un'Autorità»** (`bunker` `mt_p`): **vero** —
   `_tick_marca_temporale` `:11227-11242` (gira ogni ora, marca una volta al giorno).
10. **Referral dell'host (€10 al nuovo, €40 alla 3ª prenotazione)**: **vero e coerente con
    l'endpoint che il pannello chiama** — `fase81_bootstrap_casavip.py:56-58` e `:360`,
    qualifica a `fase83_server.py:8321-8329`. *(Il conflitto fra i **due** motori referral
    resta quello contato dal passaggio 8.)*
11. **Telegram coi tasti Approva/Rifiuta** (`host` `tg_p`): **vero** — link firmati
    (`:5581-5599`) e rotta `/host/azione` (`:10878`).
12. **«Hai 24h: oltre, la stanza si libera da sola»** (`host` `req_p`): **vero** —
    `scadenza_ts = now + 86400` (`:5573`) e `_tick_hold` ogni 120 s (`:11134-11147`).
13. **Penale host del 15%** (`host` `hc_p`): **vera** — `PENALE_HOST_BPS = 1500` (`:924`),
    applicata a `:6371`.
14. **«Foto e disponibilità entrano da soli»** (`host` `imp_p`): **vero** —
    `fase77_portability.py:116,138,195,311` e il server passa **anche** `rehost`
    (`:9172`), quindi le foto vengono ri-ospitate da noi e non restano sulla CDN del
    concorrente.
15. **Le 53 sezioni dei tre pannelli hanno tutte un endpoint che le riempie**, compresa la
    scheda «🩺 Stato del sistema» del bunker, che non ha una rotta propria ma legge
    `diagnosi` dentro la risposta di `/api/bunker/integrita` (`:4265`, motore
    `fase178_watchdog.py:239-253`).

### E tre conferme indipendenti, **segnalate e non risommate**
- `/api/admin/partner` senza pannello → **passaggio 2**.
- `ct_h` del bunker dice **«3%»** in 7 lingue e **«5% + 0,25 €»** in italiano
  (`deploy/bunker.html`, dizionari `:215-221` contro `:214`) → **passaggio 6**.
- Le 148 chiavi di `host.html` che restano in inglese nelle 6 lingue non-europee →
  **passaggio 6**.

---

# ⛔ COSA È RIMASTO FUORI (D18 punto 3)

1. **Le pagine pubbliche non sono state lette riga per riga.** `index.html`,
   `diventa-host.html`, `commissioni.html`, `partner.html`, `kit-marketing.html`,
   `contratto-host.html`, `privacy.html`, `termini.html`, `grazie.html`, `annullato.html`
   sono entrate solo nella **sonda sulle rotte** (link e chiamate), non nella lettura
   semantica. Il passaggio parla di **pannelli**; ma `index.html` è la pagina che vede
   l'ospite, e lì la stessa specie di difetto è **non misurata**. *(Un indizio già in mano:
   `/api/split/crea` non lo chiama nessuno.)*
2. **Le 7 lingue non italiane dei pannelli** sono state contate solo dove serviva alla voce
   (`conf_p` 8/8, `c5_1` 8/8, `ct_h`). **Le altre 668 voci × 7 lingue non sono state lette
   una per una**: il passaggio 6 le ha già passate al setaccio delle chiavi, non del
   significato.
3. **L'ambiente del VPS NON è stato misurato**, e cinque variabili cambiano quattro voci di
   questo referto: `PAGA_STRUTTURA_ATTIVO` (voce 9), `CAMPAGNA_AUTO_GIORNI` e
   `CAMPAGNA_LINGUE` (voci 6 e 7), `SCATTO3_ATTIVO` (voci 4 e 5), e **se il Bunker è
   configurato** (voce 8).
4. **Niente è stato eseguito.** Nessun server avviato, nessuna chiamata HTTP, nessuna
   risposta vera osservata: **tutto è letto dal codice**. Una rotta che esiste nel `_instrada`
   e solleva sempre risulterebbe qui come «c'è».
5. **La sonda sulle chiavi inviate dice «il codice la nomina», non «il gestore giusto la
   legge».** Una chiave spedita a `/api/host/pubblica` e letta solo da un altro modulo
   passerebbe la sonda. I 9 punti dove contava li ho aperti a mano; gli altri no.
6. **`app.py` e le 10 rotte Flask di `fase13`/`fase36` sono fuori perimetro**: non sono
   raggiungibili dall'ingresso di produzione (`main_casavip.py` → `fase81` → `fase83.servi`).
   È lo stesso confine del passaggio 4.
7. **I `<script>` inline dei pannelli non sono stati analizzati come programma**, solo come
   testo: una funzione definita e mai chiamata dentro `host.html` (1.612 righe) non compare in
   questo referto.

---

## 📌 NOTA DI METODO (regola B2)

Sette script di sonda scritti per questo passaggio stanno nella cartella temporanea di
sessione, **non** in `collaudi/`: sono attrezzi usa-e-getta, e questo passaggio è una misura,
non un lavoro. Nessun file del progetto è stato modificato per produrre questo referto.
