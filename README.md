# 🏛️ BookinVIP — come è fatta la macchina (documento ufficiale)

> **Questo file è la porta d'ingresso al progetto.** Descrive la macchina **com'è OGGI**
> (aggiornato **2026-07-20**). Se un'informazione qui contraddice un documento più vecchio,
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
├── fase*.py                    133 moduli del motore (uno per funzione — indice in REGISTRO_INGEGNERIA.md)
├── test_*.py                   294 file di test (la suite INTERA deve essere verde prima di ogni deploy)
├── deploy/                     ciò che vede il browser: 13 pagine + app.js + configurazioni nginx
│   ├── index.html              vetrina, ricerca, mappa, checkout (ospite)
│   ├── host.html               pannello host: pubblica, calendario, incassi, consensi
│   ├── admin.html              pannello operativo ("Field")
│   ├── bunker.html             super-admin con secondo fattore ("Bunker")
│   ├── commissioni.html · termini.html · privacy.html · contratto-host.html   pagine legali/tariffe
│   └── app.js                  fonte unica: escape, valute, lingua, rete, scudo anti-doppio-clic
├── data/                       database SQLite (in produzione è un volume Docker; mai nel repo)
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
| `STRIPE_SECRET_KEY` · `STRIPE_WEBHOOK_SECRET` | pagamenti (in produzione sono chiavi **LIVE**) |
| `HOST_KEY` · `ADMIN_KEY` · `BUNKER_PASSWORD` | accessi ai pannelli |
| `DB_*` | percorsi dei database nel volume `/data` |
| `SMTP_*` | invio email (voucher, avvisi, ricevute) |

## 9. Come si lavora

```bash
# la suite INTERA deve essere verde prima di ogni deploy (Windows, Python 3.9)
python -m unittest discover -s . -p "test_*.py"
```

**Una modifica alla volta.** Ogni bug corretto lascia un **test-guardia** che è **rosso sul
codice vecchio e verde sul nuovo**. A lavoro finito si salva **in tutti e tre i posti**:
computer → GitHub → VPS. La procedura di deploy è in `DEPLOY.md`.
