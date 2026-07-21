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
├── fase*.py                    134 moduli del motore (uno per funzione — indice in REGISTRO_INGEGNERIA.md)
├── test_*.py                   304 file di test (la suite INTERA deve essere verde prima di ogni deploy)
├── deploy/                     ciò che vede il browser: 13 pagine + app.js + configurazioni nginx
│   ├── index.html              vetrina, ricerca, mappa, checkout (ospite)
│   ├── host.html               pannello host: pubblica, calendario, incassi, consensi
│   ├── admin.html              pannello operativo ("Field")
│   ├── bunker.html             super-admin con secondo fattore ("Bunker")
│   ├── commissioni.html · termini.html · privacy.html · contratto-host.html   pagine legali/tariffe
│   └── app.js                  fonte unica: escape, valute, lingua, rete, scudo anti-doppio-clic
├── data/                       database SQLite (in produzione è un volume Docker; mai nel repo)
├── collaudi/                   strumenti d'officina: collaudi profondi e audit (NON entrano nell'immagine)
├── legale/ · contatti/         materiali di supporto
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
   conto dell'host; senza conto collegato resta un bonifico manuale tracciato.
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

### 🔴 Tariffa tecnica 3% — SEMPRE dovuta

Oltre alla commissione, l'host paga **sempre** una **tariffa tecnica fissa del 3%**
dell'importo della transazione (`PAGAMENTO_BPS=300`), a copertura del gateway di pagamento
(**Stripe**). **Si applica in OGNI periodo, anche quando la commissione è 0%.** Su questa riga
la piattaforma **non guadagna nulla** (puro transito) ma **non ci rimette mai**.

```
prezzo_ospite = netto_host + commissione + tariffa_tecnica     ← identità sempre vera
netto_host    = prezzo − commissione − (totale × 3%)
```

Esempio su **100 €**, host appena registrato, marketplace: commissione **0 €** + tariffa tecnica
**3 €** → **l'host incassa 97 €**. A regime: 10 € + 3 € → **l'host incassa 87 €**.

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
centralizzato in `app.js` (niente XSS) · upload con whitelist di tipo e nome casuale ·
CSP e HSTS attivi · blocco dei bonifici per host non conformi **DAC7** · backup automatici ogni
6 ore più copia cifrata fuori dal server.

## 8. Variabili d'ambiente principali

I valori veri vivono **solo** in `/var/www/bookinvip/.env.casavip` sul VPS (mai nel repo).

| Variabile | Cosa governa |
|---|---|
| `COMMISSIONE_BPS` | commissione a regime (default `1000` = 10%) |
| `PAGAMENTO_BPS` | **tariffa tecnica** (default `300` = 3%) |
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

```bash
python collaudi/campagna_totale.py        # tutto, 5 ripetizioni ciascuno
python collaudi/verifica_produzione.py --giri=5
```

Non si chiamano `test_*.py` di proposito: la suite non deve raccoglierli (interrogano la rete
vera e durano minuti). Il `Dockerfile.casavip` non li copia: restano strumenti d'officina.

**Una modifica alla volta.** Ogni bug corretto lascia un **test-guardia** che è **rosso sul
codice vecchio e verde sul nuovo**. A lavoro finito si salva **in tutti e tre i posti**:
computer → GitHub → VPS. La procedura di deploy è in `DEPLOY.md`.
