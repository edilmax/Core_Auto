# 🏛️ BookinVIP — come è fatta la macchina (documento ufficiale)

> **Questo file è la porta d'ingresso al progetto.** Descrive la macchina **com'è OGGI**
> (aggiornato **2026-07-21**). Se un'informazione qui contraddice un documento più vecchio,
> **vale questa**. I documenti storici stanno in `_archivio/` e **non vanno seguiti**.
>
> **I 5 documenti ufficiali — gli UNICI da leggere e aggiornare:**
>
> | File | A cosa serve |
> |---|---|
> | `README.md` | **questo**: cos'è la macchina, struttura, motore, tariffe, consensi |
> | `REGISTRO_INGEGNERIA.md` | registro di **ogni modulo**: cosa fa, se è acceso o spento, come si accende |
> | `RIPRENDI_QUI.md` | **stato vivo**: a che punto siamo, cosa è stato fatto per ultimo |
> | `DEPLOY.md` | come si mette online (procedura operativa) |
> | `CLAUDE.md` | regole ferree per chi (umano o IA) mette le mani sul progetto |
>
> ⛔ **Non si creano altri file `.md`.** Ogni aggiornamento modifica uno di questi cinque.
>
> 📕 **Dal 2026-10-13 questo file è anche IL LIBRO DI BOOKINVIP** (decisione del fondatore):
> in fondo, dopo il §9, un capitolo per ognuno dei 10 blocchi di `collaudi/piano.py`, nello
> stesso ordine, e il **Registro delle decisioni**. Ogni regola porta il `file:riga` del
> codice da cui è stata letta. Se il libro e il codice dicono cose diverse, **ha ragione il
> codice** e il libro va corretto.

---

## 1. Cos'è

Marketplace **globale** di alloggi. L'ospite cerca, prenota e paga con carta e riceve un
voucher; l'host pubblica, riceve le prenotazioni e incassa in automatico. Il vantaggio
competitivo è il **take-rate più basso del mercato**, reso possibile dall'automazione totale.

- **Dominio**: `bookinvip.com` · **Server**: VPS Hostinger `76.13.44.167`
- **Repository**: `edilmax/Core_Auto`, branch `master`
- **Stato**: pre-lancio, aperto agli host. **Stripe è LIVE**: muove denaro vero.

## 2. Le regole non negoziabili del codice

1. **Python stdlib puro** (`http.server` dietro nginx). **Zero dipendenze esterne**, niente Flask.
2. **I soldi sono sempre interi in centesimi** (`*_cents`). Mai `float`.
3. **Un modulo = un file `faseNN_nome.py`.** Il `Dockerfile.casavip` copia **solo**
   `main_casavip.py`, `fase*.py` e `deploy/`: un file con altro nome **non arriva in produzione**.
4. **Il router non solleva mai**: ogni eccezione è isolata e diventa una risposta d'errore.
5. **Ogni modifica va scritta in `REGISTRO_INGEGNERIA.md`** (lo impone anche un test).

## 3. Struttura delle cartelle

```
Core_Auto/
├── main_casavip.py             avvio del prodotto: legge le variabili d'ambiente e compone il sistema
├── fase*.py                    154 moduli del motore (uno per funzione — indice in REGISTRO_INGEGNERIA.md)
├── test_*.py                   438 file di test (la suite INTERA deve essere verde prima di ogni deploy)
├── deploy/                     ciò che vede il browser: 14 pagine + app.js + configurazioni nginx
│   ├── index.html              vetrina, ricerca, mappa, checkout (ospite)
│   ├── host.html               pannello host: pubblica, calendario, incassi, consensi
│   ├── admin.html              pannello operativo ("Field")
│   ├── bunker.html             super-admin con secondo fattore ("Bunker")
│   ├── commissioni.html · termini.html · privacy.html · contratto-host.html   pagine legali/tariffe
│   └── app.js                  fonte unica: escape, valute, lingua, rete, scudo anti-doppio-clic
├── data/                       database SQLite (in produzione è un volume Docker; mai nel repo)
├── collaudi/                   strumenti d'officina: collaudi profondi e audit (NON entrano nell'immagine)
├── legale/                     materiali di supporto
├── contatti/                   ⛔ SOLO in locale, esclusa da `.gitignore`: sono elenchi di
│                               persone vere e questo repository è PUBBLICO
├── _archivio/                  SOLO memoria storica: cifre e piani SUPERATI, da non seguire
├── Dockerfile.casavip          immagine del prodotto
└── docker-compose.casavip.yml  servizi in produzione: app · nginx · backup
```

> ⚠️ Nella cartella esistono anche `app.py`, `Dockerfile`, `docker-compose.yml` e i moduli
> `fase13`–`fase56`: appartengono al **vecchio stack "Mango / Tavola VIP"**, non al prodotto.
> Il prodotto vivo parte **solo** da `main_casavip.py`.

## 4. Il motore, dalla ricerca al bonifico

1. **Ricerca e preventivo** (`fase57` vetrina · `fase58` inventario · `fase59` concierge) — il
   preventivo è **firmato HMAC**: il prezzo non è manipolabile dal browser.
2. **Prenotazione** — le date si bloccano **atomicamente** (niente doppie prenotazioni) e nasce
   un **hold**: chi paga per primo se la prende (`fase162`).
3. **Pagamento** (`fase85` Stripe · `fase87` webhook firmato) — alla conferma nascono voucher,
   PIN di check-in, ledger della tassa di soggiorno e riga payout.
4. **Escrow** (`fase160`) — la quota dell'host resta ferma fino al "tutto ok" dell'ospite o al
   rilascio automatico dopo 24 ore.
5. **Bonifico** (`fase101` Stripe Connect) — al rilascio la quota parte **da sola** verso il
   conto dell'host; senza conto collegato resta un bonifico manuale tracciato. Prima di ogni
   bonifico si chiede a Stripe se c'è già; se Stripe non risponde (timeout, errore 5xx) l'esito
   è **sconosciuto**, non «fallito»: non diventa mai un bonifico manuale, perché pagarlo a mano
   vorrebbe dire pagare l'host due volte (deciso il 19/10/2026, Pilastro zero).
6. **Contabilità** (`fase177`) — libro giornale **append-only** con catena di hash: ogni riga è
   firmata e una manomissione si vede. Da qui escono estratti certificati e report **DAC7**.

## 5. 💶 Tariffe — la verità (questa e nessun'altra)

I valori vivi stanno nel codice; qui sono descritti. Se cambiano lì **vanno cambiati anche qui**:
una guardia automatica confronta questi testi con le costanti del motore e **fa fallire la suite**
se divergono.

### Commissione di piattaforma — a carico dell'host (l'ospite paga sempre **0%**)

| Quando | Prenotazioni dal **marketplace** | Dal **link diretto** dell'host |
|---|---|---|
| primi **90 giorni** dalla registrazione | **0%** | **5%** |
| fino a **1 anno** | **8%** | **5%** |
| oltre 1 anno (regime) | **10%** | **5%** |

Rampa in `fase98.commissione_bps_lancio`, accesa dalla variabile `PROMO_LANCIO`
(**attiva in produzione**). Il regime segue `COMMISSIONE_BPS` (default `1000` = 10%).

### 🔴 Tariffa tecnica 5% + 0,25 € — SEMPRE dovuta (7% se l'annuncio non è in euro)

Oltre alla commissione, l'host paga **sempre** una **tariffa tecnica del 5% + 0,25 €**
per transazione (`PAGAMENTO_BPS=500`, `PAGAMENTO_FISSO_CENTS=25`), a copertura dei costi di
**incasso** e di **pagamento**. Sugli annunci prezzati in **valuta diversa dall'euro** è del
**7% + 0,25 €** (`PAGAMENTO_BPS_ESTERA=700`), perché il gateway deve **convertire**.

**Perché 5 e non 4** (scelta del fondatore, 2026-08-10): il costo Stripe **dipende dalla
nazione della carta** (1,5% europea standard → 3,25% extra-UE), e al momento del preventivo
**non sappiamo con che carta pagherà l'ospite**. Il 5% copre la peggiore con **1,75 punti**
di margine, non la media. È il margine che assorbe quel non-sapere.
**Si applica in OGNI periodo, anche quando la commissione è 0%.**

**Perché 7 e non 5 sulla valuta estera — il ragionamento è «5 + 2»**, e il 2 è la
conversione. Il conto Stripe è **italiano e tiene solo euro** (misurato il 2026-08-09 sul
conto vero: `country IT`, `default_currency eur`), quindi un annuncio prezzato in dollari o
sterline **deve** essere convertito e Stripe aggiunge **+2%**, che torna come **voce
separata** nella commissione. Il conto:

| | costo Stripe misurato | tariffa tecnica | margine |
|---|---|---|---|
| annuncio in **euro** | 3,25% + 0,25 € | **5% + 0,25 €** | **1,75 punti** |
| annuncio in **altra valuta** | 3,25% + 2% = 5,25% + 0,25 € | **7% + 0,25 €** | **1,75 punti** |

Il 7 non è una cifra scelta a caso: è ciò che tiene **lo stesso identico margine nei due
casi**. Lasciando 5% anche fuori euro si andrebbe a **−0,25 punti**, cioè **sotto costo**.
⚠️ Serve soprattutto **nei primi 90 giorni**: lì la commissione è **0%** e questa tariffa è
l'**unica** cosa che paga Stripe.

⚠️ **Perché non è più 3% secco** (misurato il 2026-08-09, `collaudi/conti_stripe.py`): Stripe
non prende una percentuale pura, prende **percentuale + 0,25 € a transazione**, e **+2%** se
deve convertire la valuta. Col 3% eravamo **sotto costo** sotto i 16,66 € con qualunque carta,
e **a qualunque importo** con una carta non europea (**3,25%**, misurato sull'API vera: il
listino diceva 3,15%). In più il **bonifico all'host**
costa a sua volta (**0,25% + 0,10 €**, più **2 €/mese** per host attivo) e non era coperto da
nulla. Nei primi 90 giorni, con commissione 0%, quella perdita non la assorbiva nessuno.

Non è più un puro transito: **a seconda della carta e dell'importo il costo reale può essere
inferiore o superiore alla tariffa.** Il contratto lo dice con queste parole (ART. 6-BIS): la
vecchia frase «non consegue alcun margine» non sarebbe più vera e **è stata tolta**.

```
prezzo_ospite = netto_host + commissione + tariffa_tecnica     ← identità sempre vera
netto_host    = prezzo − commissione − (totale × 5% + 25c)     ← 7% se valuta ≠ EUR
```

Esempio su **100 €**, host appena registrato, marketplace: commissione **0 €** + tariffa tecnica
**5,25 €** → **l'host incassa 94,75 €**. A regime: 10 € + 5,25 € → **l'host incassa 84,75 €**.
Sul **link diretto**: 5 € + 5,25 € → **l'host incassa 89,75 €** (è il «5 + 5» del fondatore:
5% di commissione più 5% di spese, cioè **10% tutto compreso** su ciò che porta lui).

Guardia: `test_fase59_costo_pagamento.test_la_tariffa_tecnica_copre_la_carta_PEGGIORE_a_OGNI_importo`
legge i valori **da `main_casavip.py`** e diventa rossa se qualcuno li riabbassa sotto il costo.

Dov'è dichiarato al pubblico: riquadro "Promozione Lancio" nel pannello host,
`deploy/commissioni.html`, `deploy/termini.html` §5 e **ART. 6-BIS del Contratto Host**.

## 6. ⚖️ Tutela legale — le 3 spunte bloccanti

Alla registrazione — e alla **ri-accettazione**, quando il contratto cambia — servono
**tre consensi separati**:

1. **Contratto Host**
2. **Approvazione specifica delle clausole vessatorie** (artt. 1341-1342 c.c.: trattenute e
   compensazioni, penali, manleva, limitazione di responsabilità, foro competente)
3. **Informativa Privacy / GDPR**

**Lato browser**: il pulsante resta **grigio e non cliccabile** finché non sono spuntate tutte e
tre; se si tenta comunque, compare un avviso esplicito.
**Lato server** (la difesa vera): se ne manca anche una → **`422 consensi_mancanti`** con
l'elenco di quelle mancanti e **l'account non viene creato**. Vale anche quando il campo è del
tutto assente, non solo quando è `false`.

**La prova archiviata** (`fase163`, tabella `accettazioni`): **due righe** per registrazione —
contratto (con il flag delle clausole vessatorie) e **privacy come documento separato** — ognuna
con **versione · impronta SHA-256 del testo · IP · dispositivo · data e ora**, sigillata con
**HMAC-SHA256**. Se qualcuno modifica una riga nel database la firma non torna più: la
manomissione è dimostrabile (`integra: false`).

**🪪 Terza riga: l'identità legata alla firma.** Se l'host ha fatto la verifica documentale con
**Stripe Identity** (documento e selfie custoditi da Stripe, **mai** da noi), viene scritta una
riga `identita_stripe` che lega la **sessione di verifica** (`vs_…`) al **testo esatto** del
contratto, con un'impronta ricalcolabile da chiunque. È ciò che trasforma *«qualcuno da questo
IP ha accettato»* in *«la persona con documento verificato da un terzo indipendente ha
accettato»*. Viene scritta alla firma se la verifica c'è già, oppure **quando la verifica si
completa dopo**. Il riferimento entra **dentro** la firma HMAC: alterarlo la invalida.

**⚖️ L'ora certificata da un'Autorità QUALIFICATA europea.** Le firme qui sopra sono **nostre**,
fatte con **il nostro orologio**: da sole non tolgono l'obiezione *«i registri e l'ora ve li siete
scritti voi»*. Per questo ogni giorno lo stato dei registri viene ridotto a un'impronta e **datato
da un prestatore iscritto nella lista di fiducia europea** (**ACCV** Spagna e **QuoVadis EU**;
**Izenpe** e **Stato belga** di riserva), secondo lo standard **RFC 3161**.

Per le marche **qualificate** l'**art. 41 del Regolamento (UE) 910/2014 (eIDAS)** stabilisce la
**presunzione legale** di esattezza della data e dell'ora e di integrità dei dati: in giudizio
**non tocca a noi provare che l'ora è giusta — tocca a chi contesta provare il contrario**.

La qualifica **non si assume, si legge**: dentro ogni token c'è la dichiarazione ETSI
`0.4.0.19422.1.1` che il prestatore appone sotto vigilanza dell'organismo nazionale, e ogni marca
viene archiviata con il proprio esito. All'Autorità va **solo l'impronta**, mai i dati. Il file
`.tsr` si scarica dal Bunker e si verifica **senza di noi**, con `openssl ts -verify`. Se nessun
prestatore qualificato risponde si ripiega su una TSA ordinaria **etichettando la marca come non
qualificata**; con `MARCA_SOLO_QUALIFICATA=1` il ripiego è vietato.

**Ri-accettazione**: quando cambia la versione del contratto, al login compare da sola la
schermata dedicata (`GET /api/host/contratto_stato` · `POST /api/host/riaccetta`). Le prove
vecchie **restano** in archivio: servono a dimostrare cosa valeva in quel momento.

## 7. Sicurezza in breve

Gatekeeper sulle pagine riservate (senza sessione → redirect al login) · super-admin **Bunker**
con secondo fattore (TOTP o password) e sessione di 15 minuti legata all'IP · escape
centralizzato in `app.js` (niente XSS) · upload con whitelist di tipo e nome casuale · una foto
la cancella solo l'host che l'ha caricata, e le prove che l'ospite carica in chat nessun host ·
CSP e HSTS attivi · blocco dei bonifici per host non conformi **DAC7** · backup automatici ogni
6 ore più copia cifrata fuori dal server.

## 8. Variabili d'ambiente principali

I valori veri vivono **solo** in `/var/www/bookinvip/.env.casavip` sul VPS (mai nel repo).

| Variabile | Cosa governa |
|---|---|
| `COMMISSIONE_BPS` | commissione a regime (default `1000` = 10%) |
| `PAGAMENTO_BPS` | **tariffa tecnica** su annunci in euro (default `500` = 5%) |
| `PAGAMENTO_BPS_ESTERA` | tariffa tecnica su annunci in **altra valuta** (default `700` = 7%: il gateway converte) |
| `PAGAMENTO_FISSO_CENTS` | quota **fissa** per transazione (default `25` = 0,25 €: Stripe la prende sempre) |
| `PROMO_LANCIO` | accende la rampa 0→8→10% (default `true`) |
| `MARCA_TEMPORALE` · `TSA_URL` · `MARCA_SOLO_QUALIFICATA` | ora certificata da un'Autorità **qualificata** europea (default acceso; prestatore sostituibile) |
| `STRIPE_SECRET_KEY` · `STRIPE_WEBHOOK_SECRET` | pagamenti (in produzione sono chiavi **LIVE**) |
| `HOST_KEY` · `ADMIN_KEY` · `BUNKER_PASSWORD` | accessi ai pannelli |
| `DB_*` | percorsi dei database nel volume `/data` |
| `SMTP_*` | invio email (voucher, avvisi, ricevute) |

## 9. Come si lavora

```bash
# la suite INTERA deve essere verde prima di ogni deploy (Windows, Python 3.9)
python -m unittest discover -s . -p "test_*.py"
```

### Oltre la suite: i collaudi profondi (`collaudi/`)

La suite prova il codice **con se stesso**. In `collaudi/` stanno gli strumenti che lo provano
**da fuori**, e che hanno trovato difetti che la suite non poteva vedere:

| Strumento | Cosa fa |
|---|---|
| `collaudo_neuroni_marca.py` | attraversa la marca temporale su 7 livelli, dal protocollo binario alla qualifica europea |
| `super_collaudo_marca.py` | usa **OpenSSL come giudice esterno** e confronta le due implementazioni nei due sensi |
| `collaudo_neuroni_legale.py` | consensi, identità, scaglioni, prove, dossier, permessi, concorrenza |
| `collaudo_finale_totale.py` · `collaudo_rampa_totale.py` | i soldi, con oracoli indipendenti che ricalcolano tutto da zero |
| `audit_coerenza_tariffe.py` | ogni percentuale scritta in **ogni file** confrontata col motore (con baseline: rosso su ogni cifra nuova) |
| `audit_millimetrico.py` | i 5 documenti ufficiali contro il motore, riga per riga |
| `verifica_produzione.py` | il **sito vero** interrogato dall'esterno, in sola lettura |
| `campagna_totale.py` | ripete ogni collaudo **5 volte** e pretende che sia **stabile**, non solo verde |
| `sonda_qtsp.py` | interroga i prestatori europei e verifica quali dichiarano davvero marche qualificate |

**E dal 2026-08-18 c'è una famiglia in più: quelli che aprono un BROWSER VERO.** Servono
perché `deploy/app.js` sono 210 righe che girano **nel computer del cliente**, e fino a quel
giorno non le eseguiva nessuno: i collaudi in Python parlano col server, non aprono una
pagina. Girano **a ogni commit** dentro la CI (job `browser`), e il browser **non entra
nell'immagine di produzione**.

| Strumento (col browser) | Cosa fa |
|---|---|
| `a11y_static.js` | accessibilità WCAG 2.1 A+AA sulle pagine pubbliche; **blocca** su una violazione grave |
| `clickthrough_pannelli.js` | entra nei **3 pannelli** (host, admin, super-admin) su PC e Mobile e clicca ogni bottone non distruttivo, contando errori JavaScript e risposte HTTP sbagliate |
| `percorso_ospite_host.js` | **il percorso in due atti**: ① un ospite prenota e l'**host lo vede comparire** nel suo pannello — l'unico collaudo che attraversa il confine fra due persone; ② col gateway muto il prodotto **deve rifiutare**, cioè *nessun voucher senza incasso* |
| `test_visivo.js` · `test_visivo_ruoli.js` | resa grafica del checkout e dei ruoli su desktop e mobile, in più lingue (avvio manuale) |

⛔ **Cosa NON provano, dichiarato**: il **pagamento** vero. Servirebbe una chiave Stripe
dentro il giro automatico, e questo repository è **pubblico** (lo è perché serve a CodeQL).

```bash
python collaudi/campagna_totale.py        # tutto, 5 ripetizioni ciascuno
python collaudi/verifica_produzione.py --giri=5
```

Non si chiamano `test_*.py` di proposito: la suite non deve raccoglierli (interrogano la rete
vera e durano minuti). Il `Dockerfile.casavip` non li copia: restano strumenti d'officina.

**Una modifica alla volta.** Ogni bug corretto lascia un **test-guardia** che è **rosso sul
codice vecchio e verde sul nuovo**. A lavoro finito si salva **in tutti e tre i posti**:
computer → GitHub → VPS. La procedura di deploy è in `DEPLOY.md`.

---

# 📕 IL LIBRO DI BOOKINVIP

> **Come si legge.** Ogni capitolo dice **cosa fa** la macchina, **perché**, **come**, le
> **regole decise** (con data e chi) e **cosa NON fa o NON è provato**. Accanto a ogni regola
> c'è il `file:riga` da cui è stata letta, il 2026-10-13, sul commit `74ca4da`. Quando il
> codice cambia i numeri di riga si spostano: se non tornano, si cerca il nome della funzione.
>
> Capitoli scritti: **1 su 10**. Gli altri seguono l'ordine dei blocchi di `collaudi/piano.py`.
>
> **Il PDF** si stampa da questo file con un comando solo: `python collaudi/stampa_libro.py`
> (scrive `IL LIBRO DI BOOKINVIP.pdf` sul Desktop, con commit e data in copertina). Se il
> README ha modifiche non ancora salvate in un commit, il file si chiama «… - PROVA.pdf».

## Capitolo 1 — SOLDI E PAGAMENTI

### 1.1 In una frase

L'ospite paga con la carta e i soldi dell'host restano **fermi in garanzia**. Da quando
l'ospite **arriva** ha **24 ore** per dire «tutto ok» oppure «c'è un problema». Se dice «tutto
ok», o se le 24 ore passano senza problemi, i soldi partono **da soli** verso l'host: dopo le
24 ore l'ospite **non può più bloccarli**. Se qualcosa va storto (una cancellazione, un
problema, una contestazione della banca) decide una regola scritta nel codice, **in centesimi
interi**. *(Regola ridetta dal fondatore il 2026-10-13: vedi D-10. Il codice la rispetta solo in
parte: vedi (ad) nel §1.10.)*

### 1.2 Il viaggio dei soldi, passo per passo

**Prima un esempio: la storia di Anna e Luca.** Anna prenota la casa di Luca per sabato, fra
10 giorni. Costa **100 €**.
1. **Anna paga.** Mancano più di 6 giorni, quindi i 100 € restano solo **fermi sulla sua
   carta**: la banca non li toglie ancora.
2. **Passano 48 ore** e Anna non ha cancellato: adesso i 100 € si prendono davvero.
3. I soldi vanno in una **cassaforte** (la garanzia). Dentro ci sono **94,75 €** per Luca; il
   resto (5,25 €) è la tariffa tecnica. Luca è nei primi 90 giorni, quindi niente commissione
   (i conti sono quelli del §5).
4. **Sabato alle 15 Anna arriva.** Da lì ha 24 ore. Se preme «tutto ok», Luca riceve i suoi
   soldi **subito**. Se non preme niente, **domenica alle 15** (al massimo un'ora dopo) li riceve
   da solo. Se preme «c'è un problema», i soldi restano nella cassaforte e **decide una persona**.
5. Se Luca ha collegato Stripe, i soldi gli arrivano **da soli**; se no, glieli mandiamo **a mano**.

Gli stessi passi, con il punto del codice dove stanno:

| # | Cosa succede | Dove sta nel codice |
|---|---|---|
| 1 | L'ospite prenota: le date si bloccano e la stanza resta sua per **30 minuti**, quanto resta aperta la pagina di pagamento di Stripe | `fase162_pagamenti_pendenti.py:32` |
| 2 | **Arrivo fra 6 giorni o più**: i soldi vengono solo **bloccati sulla carta**, non presi. Si prendono davvero alla fine delle 48 ore di ripensamento | `fase85_pagamenti_stripe.py:48`, `:62-73`, `:170-174`; fine delle 48 ore `fase83_server.py:9734` |
| 3 | **Arrivo fra meno di 6 giorni**: i soldi si prendono subito | `fase85_pagamenti_stripe.py:73` |
| 4 | Il blocco vale solo coi metodi che lo reggono: carta (con dentro Apple Pay e Google Pay), Link, Klarna, Amazon Pay, Satispay | `fase85_pagamenti_stripe.py:59` |
| 5 | Pagato: si apre la **garanzia** con la quota dell'host (il suo netto più la tassa di soggiorno, che poi gira lui al Comune) | `fase83_server.py:6741`, `:6771` |
| 6 | La garanzia si sblocca da sola **24 ore dopo l'arrivo**; l'arrivo si conta alle **15:00 ora del posto**. La data d'arrivo vale solo se è scritta AAAA-MM-GG, uguale sul PC e sul server: fino al 2026-10-19 il Python del server accettava anche «20260905» e «2026-W36-6» (DATE-311) | `fase160_escrow_garanzia.py:22`, `:90`; `fase83_server.py:573`; la data `fase83_server.py:_istante_checkin_prudente` |
| 7 | **Solo nelle 24 ore dall'arrivo** l'ospite può premere **«tutto ok»** (soldi subito all'host) o **«segnala un problema»** (soldi fermi, decide una persona): prima la risposta è «non ancora arrivato», dopo «finestra chiusa». Se l'alloggio non ha un fuso orario, la finestra si apre al primo arrivo possibile del giorno d'arrivo, così l'ospite non perde ore. Il giro che sblocca le garanzie scadute passa **ogni ora** | `fase83_server.py:7700`, `:7717`, `:13581`; la finestra `fase83_server.py:3096` |
| 8 | Il **bonifico** all'host parte da solo, con Stripe Connect | `fase83_server.py:7128` |

Il bonifico **non parte** — e la quota resta scritta come «da pagare», mai persa — quando:
- è acceso l'interruttore d'emergenza che ferma tutti i movimenti (`fase83_server.py:7140`);
- i soldi dell'ospite sono ancora solo bloccati sulla carta, non presi (`fase83_server.py:7173`);
- la ritenuta fiscale non è stata fatta, o mancano i dati fiscali DAC7 (`fase83_server.py:7181`, spiegato in `fase83_server.py:7134-7138`);
- l'host **non ha collegato Stripe**: allora il bonifico si fa **a mano** (`fase83_server.py:7184`);
- è già partito una volta (guardia contro il doppio pagamento).

Prima di pagare, i debiti aperti dell'host vengono scalati dal bonifico (`fase83_server.py:7201`).

### 1.3 Le 4 politiche di cancellazione (le sceglie l'host)

Lette da `fase111_cancellazione.py:25-28`. «Giorni» vuol dire: data d'arrivo meno la data di
oggi **nel fuso dell'alloggio** (`fase83_server.py:7832`). Sono giorni di calendario, non ore.

Nella tabella, i numeri sono **i giorni che mancano all'arrivo** (0 = il giorno stesso dell'arrivo):

| Politica | Rimborso pieno | Rimborso a metà | Nessun rimborso |
|---|---|---|---|
| **Flessibile** | 1 giorno o più | 0 giorni | — |
| **Moderata** | 5 giorni o più | da 1 a 4 giorni | 0 giorni |
| **Rigida** | 30 giorni o più | da 7 a 29 giorni | da 0 a 6 giorni |
| **Non rimborsabile** | — | — | sempre |

Una guardia confronta questa tabella col codice e diventa rossa se non coincidono
(`test_trasparenza_costi.TestIlLibroDiceLeRegoleDelMotore`).

Regole che valgono per tutte e quattro:
- la **pulizia** si rende sempre per intero: senza soggiorno non è stata fatta (`fase111_cancellazione.py:73-77`);
- la **tassa di soggiorno** si rende sempre per intero (`fase83_server.py:8036`);
- la politica si legge dal **voucher firmato**, mai da quello che manda il browser (`fase83_server.py:7869`);
- non si rende mai più di quanto pagato, e un dato strano dà rimborso zero, mai di più (`fase111_cancellazione.py:63`);
- la parte trattenuta si divide: all'host la sua quota in proporzione, a noi commissione e tariffa tecnica in proporzione (`fase83_server.py:8001`; contratto dell'host, ART. 6-TER, `fase163_accettazioni.py:129-135`);
- dal voucher **non si cancella** un soggiorno già iniziato, né una prenotazione la cui garanzia è già stata divisa: risposta `409` (`fase83_server.py:7851-7865`). Dopo l'arrivo si usa «segnala un problema»;
- con una **controversia aperta** (la segnalazione dell'ospite o la contestazione della banca) non cancellano né l'ospite né l'host: risposta `409 controversia_aperta`, decide l'arbitro o la banca (`fase83_server.py:3078`, `:7866-7867`, `:7395-7396`);
- se una parte dei soldi è già uscita verso l'host, il rimborso si **taglia** a quello che c'è ancora in cassa (`fase83_server.py:7969`);
- il rimborso all'ospite **non parte da solo**: compare in una lista del pannello e una persona preme il pulsante (`GET /api/admin/rimborsi_dovuti` → `POST /api/admin/rimborsa_dovuto`; `fase83_server.py:7787`, `:2470-2472`).

### 1.4 Le 48 ore di ripensamento

Se l'ospite cancella **entro 48 ore vere** (172.800 secondi) dalla prenotazione e mancano
**almeno 3 giorni** all'arrivo, riprende **tutto**, qualunque sia la politica
(`fase83_server.py:621`, `:631`, `:7886`; `fase111_cancellazione.py:67-69`).
Se i soldi erano solo bloccati sulla carta (arrivo a 6 giorni o più), il blocco si **annulla**:
nessuno paga niente, nemmeno Stripe (`fase83_server.py:9836`).
L'ospite lo legge nei Termini (`fase185_testi_legali.py:181-182`).

### 1.5 Quando cancella l'host

L'ospite riprende **tutto**. L'host paga una **penale del 15%** dell'importo
(`PENALE_HOST_BPS = 1500`, `fase83_server.py:1080`; la funzione è `_host_cancella`, `:7347`),
tolta dai suoi incassi futuri o scritta come debito (`fase185_testi_legali.py:175-178`).

### 1.6 Il Credito Viaggio («anti-rimpianto»)

Quando l'ospite perde dei soldi per una penale, **metà della penale** torna come Credito
Viaggio: al massimo **50 €** (5.000 centesimi, nella valuta della prenotazione), vale
**365 giorni**, si usa **una volta sola** (`fase83_server.py:8372`, `:8380`;
`fase167_credito_single_use.py:140`). Non sono soldi: è uno sconto su una prenotazione futura,
e al riscatto non può superare il nostro margine su quella prenotazione
(`fase59_concierge.py:535-536`).

### 1.7 Paga in struttura — ACCESO in produzione

Misurato il 2026-10-13 sul server: `PAGA_STRUTTURA_ATTIVO=1`.
L'ospite sceglie se pagare **online** (prezzo pulito, soldi in garanzia) o **in struttura**.
In struttura, online paga solo un **anticipo**: la nostra commissione, un servizio di
**1,50 € a notte** a suo carico e la copertura della carta. Il resto lo dà all'host di persona
(`fase188_paga_struttura.py:4-31`, `:41`).
- Cancellazione normale: l'anticipo **non si rende**, tranne nelle 48 ore (`fase83_server.py:7878-7882`).
- Cancellazione a **meno di 24 ore** dall'arrivo (ore vere, dalle 15:00 del posto): si addebita la **prima notte** sulla carta salvata (`fase83_server.py:8137`, `:8144`).
- Il saldo pagato in struttura non passa da noi: se c'è un problema, **non possiamo renderlo**.
- Il **rimborso dal pannello dell'admin** restituisce **solo l'anticipo**, cioè quello che è passato da Stripe; anche il debito scritto nel giornale è l'anticipo. Il saldo pagato di persona è fra ospite e host (`_admin_rimborso`, `fase83_server.py:5206-5207`; D-13).

### 1.8 Chi paga Stripe e il cambio

- La **tariffa tecnica** la paga l'host e copre Stripe e il cambio di valuta: è spiegata nel §5, e lì una guardia diventa rossa se il testo e il codice non coincidono.
- Su un pagamento preso e poi rimborsato, Stripe **non restituisce** il suo costo. Misurato sul conto vero: addebito 1,00 €, costo 0,27 €; dopo il rimborso il costo restituito è 0 (`REGISTRO_INGEGNERIA.md:7199-7204`). Il contratto dell'host lo dice: quel costo «non torna a nessuna delle parti» (`fase163_accettazioni.py:133-135`).
- Per questo, quando l'arrivo è lontano, i soldi si **bloccano** invece di prenderli (§1.2, punto 2): annullare un blocco non costa niente a nessuno.

### 1.9 Le contestazioni: la nostra e quella della banca

- **«Segnala un problema»** (l'ospite, entro 24 ore dall'arrivo) o un disaccordo in chat: la garanzia diventa «contestata» e il bonifico si ferma (`fase83_server.py:7717`, `:12958`). Prima dell'arrivo e dopo le 24 ore il pulsante risponde di no (§1.2, punto 7).
- Finché la controversia è aperta, **né l'ospite né l'host possono cancellare** (`409 controversia_aperta`): i soldi li decide l'arbitro (`fase83_server.py:3078`).
- Decide l'**arbitro**, cioè un admin entrato nel Bunker (il ruolo «supporto» non può): sceglie quanto rendere all'ospite, il resto va all'host (`fase83_server.py:5639`, `:5690`, `:5711`). Anche qui il rimborso vero si fa dal pulsante del pannello.
- **Contestazione della banca** (chargeback): Stripe toglie i soldi dal nostro saldo; la garanzia si ferma, il bonifico non ancora partito viene trattenuto e un allarme lo dice (`fase83_server.py:9479`, `:9520`, `:9543`). Finché la contestazione è aperta Stripe **non permette** rimborsi fuori dalla sua procedura: per questo nessuno cancella e **nemmeno l'arbitro decide** (`409 decide_la_banca`). Quando la banca ha chiuso la contestazione (si guarda sul pannello di Stripe), l'arbitro decide dicendolo apposta (`la_banca_ha_deciso`), così i soldi non restano fermi per sempre (`fase83_server.py:5670-5672`).

### 1.10 Cosa NON funziona ancora, e cosa NON è provato

Misurato, non ricordato. Il dettaglio di ognuno sta in `RIPRENDI_QUI.md`.
- **F1, F2 e (ad) sono riparati nel codice il 2026-10-14** (§1.2 punto 7 e §1.9; guardie `test_fase83_server.TestUnaControversiaApertaFermaISoldi`, viste rosse prima). Restano **non coperti**: il rimborso dell'admin dal pannello durante una controversia, e l'host che cancella dopo l'arrivo.
- **(ai)** Le pagine non spiegano i quattro rifiuti nuovi (`non_ancora_arrivato`, `finestra_chiusa`, `controversia_aperta`, `decide_la_banca`): chi preme troppo presto legge solo «Operazione non riuscita». E il pulsante «la banca ha deciso» c'è solo nell'API, non nel pannello.
- **(aa)** Il menu dell'host dice «Gratuita fino a **24h** prima» (`deploy/host.html:381`), ma il motore conta **giorni di calendario** (`fase83_server.py:7832`): chi cancella alle 23 del giorno prima riprende tutto.
- **(ab)** Nello stesso prodotto ci sono **due penali diverse**: online metà del totale (§1.3), in struttura la prima notte (§1.7).
- **(aj)** Le Filippine (Manila, Cebu) non sono nella tabella dei fusi orari (`fase187_fuso_orario.py:65-77`): lì il pass della serratura, le recensioni e la cancellazione usano l'ora prudente, non quella del posto. I due pulsanti no: si aprono al primo arrivo possibile (§1.2, punto 7).
- **B9** — al riscatto il Credito Viaggio non supera il nostro margine: con un host nei primi 90 giorni (commissione zero) vale **zero**, mentre l'email all'ospite annuncia la cifra piena, fino a 50 € (`fase59_concierge.py:535-536`).
- **B10** — il Credito Viaggio è **al portatore**: non porta l'email di nessuno (`fase83_server.py:8378`), quindi chi ha il codice lo spende.
- Il **contratto dell'host** non nomina le 48 ore (ART. 6-TER, `fase163_accettazioni.py:129-135`): chi sceglie «non rimborsabile» rende comunque tutto nelle 48 ore, e il contratto non glielo dice. I Termini dell'ospite invece lo dicono.
- **Paga in struttura**: per l'ospite che **non si presenta e non cancella** non c'è penale, perché manca chi la faccia partire.
- **Non guardato**: il primo bonifico vero legato al suo pagamento (`source_transaction`) sul pannello di Stripe. I pagamenti veri non girano nella CI (§9).
- **Non guardato (DATE-311, 2026-10-19)**: riparate le due letture della data d'arrivo in `fase83_server.py`, ma nel codice di produzione ci sono altre letture di date con `fromisoformat` (48 righe in tutto, contate col grep il 2026-10-19), fra cui `fase187_fuso_orario.py:121` che calcola l'arrivo quando l'alloggio ha un fuso: sul Python del server possono accettare le stesse forme strane. Da cercare una per una.

## 📜 Registro delle decisioni

> Il metodo è quello di Michael Nygard, *Documenting Architecture Decisions* (2011): una voce
> per ogni decisione importante. Una decisione cambiata **non si cancella**: si scrive
> «SOSTITUITA DA» e resta qui, così nessuno la scambia per una regola valida e nessuno la
> deve riscoprire.

**D-01 · 2026-07-10 · Le regole di cancellazione** — ✅ VALIDA
- *Chi:* il fondatore (la ricordava il 2026-10-13, quando è stata ritrovata).
- *Decisione:* 4 politiche scelte dall'host; soglie come Airbnb (24 ore, 5 giorni, 30 giorni); rimborso pieno → metà → niente; 48 ore di ripensamento per tutti; metà della penale torna come Credito Viaggio.
- *Perché:* penali proporzionate sono legali ovunque; il ripensamento e il credito ci mettono sopra ai colossi.
- *Stato:* lo sconto per il «non rimborsabile» scritto lì non è mai stato acceso. Le 48 ore sono precisate dalla D-06.
- *Fonte:* il documento del 10/07, tolto dalla cartella il 2026-10-13 perché questo capitolo lo sostituisce: si rilegge con `git show 74ca4da:_archivio/STRATEGIA_CANCELLAZIONE.md`; nel codice `fase111_cancellazione.py:25-28`.

**D-02 · 2026-07-22 · Paga in struttura** — ✅ VALIDA, accesa in produzione
- *Chi:* il fondatore, dopo l'analisi dei colossi.
- *Decisione:* due modi di pagare; in struttura l'ospite paga 1,50 € a notte in più e online solo un anticipo.
- *Fonte:* `fase188_paga_struttura.py:4-31`.

**D-03 · 2026-07-23 · Paga in struttura: la penale è la prima notte** — ✅ VALIDA (vedi domanda (ab))
- *Chi:* il fondatore («regola DECISA dal fondatore»).
- *Decisione:* cancellazione normale = si tiene solo l'anticipo; a meno di 24 ore dall'arrivo si addebita la prima notte.
- *Fonte:* `REGISTRO_INGEGNERIA.md:14231`; nel codice `fase83_server.py:8137`, `:8144`.

**D-04 · 2026-08-10 · Tariffa tecnica 5% + 0,25 € (7% + 0,25 € fuori euro)** — ✅ VALIDA
- *Chi:* il fondatore.
- *Perché:* la tariffa di prima era sotto costo, misurato il 2026-08-09 sul conto vero.
- *Fonte:* §5 di questo file, sorvegliato da una guardia.

**D-05 · 2026-08-16 · I rimborsi all'ospite si fanno a mano, dal pannello** — ✅ VALIDA
- *Chi:* il fondatore: «se la macchina sbaglia ci rimetto conti, fiducia, credibilità».
- *Decisione:* la lista dei rimborsi dovuti si calcola da sola; il pulsante lo preme una persona. L'automatico si accende dopo, quando la lista avrà funzionato molte volte di fila.
- *Fonte:* `fase83_server.py:7787`.

**D-06 · 2026-08-20 · «Entro 48 ore cambi idea e non paga nessuno. Dopo, valgono le regole dell'host.»** — ✅ VALIDA
- *Chi:* il fondatore con Claude («decisa col fondatore»).
- *Decisione:* i soldi non si prendono subito; se l'ospite cambia idea nelle 48 ore il blocco si annulla e nessuno paga, nemmeno Stripe.
- *Stato:* fatto con il blocco sulla carta, ma solo per gli arrivi a 6 giorni o più (`fase85_pagamenti_stripe.py:48`). Sotto i 6 giorni si prende e si rimborsa, e il costo di Stripe si perde (§1.8).
- *Fonte:* la frase è in `git show 9adb0ee:RIPRENDI_QUI.md`, riga 128; la ricerca legale in `REGISTRO_INGEGNERIA.md:7192`.

**D-07 · 2026-09-14 · La stanza resta ferma 30 minuti** — ✅ VALIDA
- *Chi:* il fondatore («la cosa giusta»).
- *Decisione:* la stanza resta ferma almeno quanto la pagina di pagamento di Stripe, così nessuno paga una stanza già liberata.
- *Fonte:* `fase162_pagamenti_pendenti.py:26-32`.

**D-08 · 2026-10-03 · Il blocco su ogni metodo che lo regge** — ✅ VALIDA
- *Chi:* il fondatore («autorizzato»), dopo aver pagato con Link ed essere stato addebitato subito.
- *Decisione:* nelle 48 ore la cancellazione dev'essere immediata con ogni metodo di pagamento; la cassa propone solo i metodi che reggono il blocco.
- *Fonte:* `fase85_pagamenti_stripe.py:50-59`.

**D-09 · 2026-10-11 · I due freni sulla cancellazione** — ✅ VALIDA
- *Chi:* il fondatore («autorizzato»).
- *Decisione:* non si cancella una prenotazione la cui garanzia è già stata divisa, né un soggiorno già iniziato.
- *Fonte:* `fase83_server.py:7851-7865`.

**D-10 · ridetta il 2026-10-13 · 24 ore dall'arrivo, poi l'host incassa** — ✅ VALIDA, rispettata dal codice dal 2026-10-14
- *Chi:* il fondatore: «da quando arriva [...] 24 ore per dire se va bene o se ci sono problemi. Dopo le 24 ore non può fare più niente e l'host incassa i soldi».
- *Decisione:* la finestra per «tutto ok» o «c'è un problema» comincia all'arrivo e dura 24 ore; dopo, i soldi sono dell'host.
- *Fonte:* le parole del fondatore in quella sessione; nel codice la finestra è `fase160_escrow_garanzia.py:22` e i due pulsanti la rispettano da `fase83_server.py:3096`. La data della decisione originale non è stata trovata.

**D-11 · 2026-07-11 · Paga in struttura, il primo progetto** — ⛔ SOSTITUITA DA D-02 e D-03
- *Chi:* proposta scritta l'11/07; le scelte erano lasciate al fondatore («decisione fondatore»).
- *Cosa diceva:* niente pagamento online, solo la carta a garanzia; penale per chi non si presenta o cancella tardi = la politica dell'alloggio; una «tariffa Sicuro» di circa il 5% a carico dell'ospite.
- *Perché è sostituita:* il 22/07 e il 23/07 si è scelto un anticipo online (commissione, 1,50 € a notte, copertura della carta) e la prima notte come penale. Resta valida un'idea non ancora fatta: per chi non si presenta senza cancellare manca chi faccia partire la penale (§1.10).
- *Fonte:* tolto dalla cartella il 2026-10-13; si rilegge con `git show 74ca4da:_archivio/STRATEGIA_PAGA_IN_STRUTTURA.md`.

**D-12 · 2026-10-14 · Il blocco sulla carta dura fino a 7 giorni, non 48 ore** — ✅ VALIDA, non ancora nel codice (oggi 48 ore: §1.2, punto 2)
- *Chi:* il fondatore: «su stripe dobbiamo sfruttare i 7 giorni».
- *Decisione:* i soldi restano solo bloccati fin quasi alla scadenza del blocco normale di Stripe, non solo per le 48 ore di ripensamento. Oltre i 7 giorni non si va: servirebbe il blocco esteso, che Stripe concede solo a certe condizioni (prezzi IC+, per gli alloggi fino a 30 giorni, non con Link).
- *Perché:* una cancellazione gratuita con i soldi ancora bloccati non costa niente a nessuno; dopo l'incasso, la commissione di Stripe non torna più (§1.8).
- *Da sapere prima di farla:* la durata del blocco va verificata metodo per metodo (Link, Klarna, Amazon Pay, Satispay possono essere diversi dalla carta); fra le 48 ore e il settimo giorno una cancellazione può avere una penale, e allora si incassa solo quella e il resto si sblocca.
- *Fonte:* docs.stripe.com/payments/extended-authorization (letta il 2026-10-14): «the default authorization validity period is 7 days for online payments».

**D-13 · 2026-10-18 · Paga in struttura: il rimborso restituisce solo l'anticipo** — ✅ VALIDA, nel codice dal 2026-10-18
- *Chi:* il fondatore: «incassiamo solo la commissione se paga in struttura», poi «autorizzato».
- *Decisione:* quando l'admin rimborsa una prenotazione pagata in struttura, a Stripe si chiede di restituire l'anticipo, non il totale del soggiorno. Il saldo pagato di persona non passa da noi.
- *Perché:* il pulsante chiedeva il totale; Stripe non restituisce più di quanto ha incassato, quindi il rimborso falliva per intero (all'ospite non tornava nemmeno l'anticipo) e il giornale scriveva un debito mai incassato. Trovato da una verifica esterna (Google AI Studio) e confermato leggendo il codice.
- *Fonte:* `fase83_server.py:5206-5207`; guardia `test_admin_rimborso_money.TestLaListaDeiRimborsiDovuti.test_IL_RIMBORSO_ADMIN_DI_UNA_PAGA_IN_STRUTTURA_RESTITUISCE_L_ANTICIPO`, vista rossa prima della riparazione.

### Domande aperte — le decide il fondatore (soldi e strategia)

- **(aa)** 24 ore o giorni di calendario? Si corregge la scritta del menu o il motore?
- **(ab)** Una penale sola (la prima notte per tutti, come fanno Airbnb e Booking) o le due di oggi?
- **(r)** Il Credito Viaggio: oggi vale zero con gli host nei primi 90 giorni (B9) ed è al portatore (B10). Come deve funzionare?
- **Le 48 ore**: uguali in tutto il mondo o legate al luogo dell'alloggio? La ricerca del 2026-08-20 dice: troppe per l'Europa, il doppio di quanto chiede la California, forse poche per il Brasile (`REGISTRO_INGEGNERIA.md:7192`).
- **Il contratto dell'host** deve nominare le 48 ore? Cambiarlo prima che firmino host veri costa poco; dopo, vorrà dire farlo riaccettare a ognuno.
