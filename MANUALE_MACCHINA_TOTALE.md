# MANUALE DELLA MACCHINA — CORE_AUTO (Fase 56)

> Documento unico e completo: **come è fatta la macchina**, **cosa contiene in ogni
> particolare**, **come e dove intervenire**, **cosa serve per accenderla** e il
> **manuale d'uso per arrivare al business**. Linguaggio chiaro, ma ogni riga
> corrisponde al codice reale del progetto.
>
> Stato: 56 fasi costruite · ~57 suite di test (tutte verdi) · denaro **sempre in
> centesimi interi** (zero float) · Python 3.9 · test con `unittest`.

---

## INDICE

1. [Cos'è questa macchina (in una pagina)](#1-cosè-questa-macchina-in-una-pagina)
2. [I tre motori e la regola d'oro](#2-i-tre-motori-e-la-regola-doro)
3. [Mappa delle cartelle — dove sta cosa](#3-mappa-delle-cartelle--dove-sta-cosa)
4. [Anatomia completa — tutte le fasi, in dettaglio](#4-anatomia-completa--tutte-le-fasi-in-dettaglio)
   - 4.1 [Fondamenta riusabili (la cassaforte)](#41-fondamenta-riusabili-la-cassaforte)
   - 4.2 [Cervello conversazionale (fasi 24–33)](#42-cervello-conversazionale-fasi-2433)
   - 4.3 [Prodotto Tavola VIP — prenotazioni + pagamenti (fasi 34–42)](#43-prodotto-tavola-vip--prenotazioni--pagamenti-fasi-3442)
   - 4.4 [Satellite commerciale Mango (fasi 43–49)](#44-satellite-commerciale-mango-fasi-4349)
   - 4.5 [Il funnel autonomo Mango (fasi 50–55)](#45-il-funnel-autonomo-mango-fasi-5055)
   - 4.6 [Gateway Tavoli VIP — il ponte col frontend (fase 56)](#46-gateway-tavoli-vip--il-ponte-col-frontend-fase-56)
5. [Il flusso del denaro — dalla richiesta all'incasso](#5-il-flusso-del-denaro--dalla-richiesta-allincasso)
6. [Come intervenire in OGNI punto (mappa pratica)](#6-come-intervenire-in-ogni-punto-mappa-pratica)
7. [Cosa serve per accendere tutto (chiavi e dipendenze)](#7-cosa-serve-per-accendere-tutto-chiavi-e-dipendenze)
8. [Manuale d'uso — dal test privato al business vincente](#8-manuale-duso--dal-test-privato-al-business-vincente)
9. [Quando si rompe — diagnosi e dove guardare](#9-quando-si-rompe--diagnosi-e-dove-guardare)
10. [Manutenzione, backup e integrità](#10-manutenzione-backup-e-integrità)
11. [Glossario](#11-glossario)

---

## 1. Cos'è questa macchina (in una pagina)

CORE_AUTO è una **startup chiavi-in-mano** per vendere prenotazioni saltando le
grandi OTA (Booking, ecc.) e tenendo per sé la commissione che oggi regalano a loro.

In pratica fa tre cose:

1. **Incassa prenotazioni reali** con pagamento Stripe, in modo blindato (zero errori
   sui soldi, zero doppie prenotazioni dello stesso tavolo/alloggio).
2. **Parla coi clienti** via chat (WhatsApp/Instagram/Telegram) tramite un agente IA
   che capisce la richiesta e propone l'offerta giusta — ma **i prezzi li calcola
   sempre il sistema, mai l'IA**.
3. **Va a caccia di host** (proprietari) mostrando loro quanto perdono con le OTA, li
   contatta in modo legale e li porta dentro: è il "satellite" **Mango**.

La filosofia (scritta nella direttiva del progetto): per ogni pezzo si fanno 3-4
varianti, si stressano sotto carico estremo, e **si tiene solo la vincitrice**. Per
questo ogni modulo dice nei commenti "Vincitrice del benchmark".

---

## 2. I tre motori e la regola d'oro

La macchina ha **tre motori separati** che non si rompono a vicenda:

| Motore | File principale | A cosa serve |
|---|---|---|
| **A — La Fortezza** (`CORE_AUTO`) | `app.py` + `assistente_gestionale.py` | Il marketplace originale: escrow/split, audit immutabile, sicurezza HMAC. È la base. |
| **B — Tavola VIP** (il prodotto) | `fase36_booking_api.py` | Le prenotazioni con pagamento Stripe. **È quello che vendi.** |
| **C — Mango** (il satellite) | `fase55_bootstrap.py` | Trova host, li contatta, propone, e quando convertono aggancia una prenotazione vera. |

**La regola d'oro (contratto d'isolamento).** Ogni pezzo nuovo è un modulo `faseNN_*.py`
a sé stante che rispetta 5 regole:
1. **Import pigro (lazy)**: il cuore non carica il modulo all'avvio.
2. **Interruttore (feature-flag), spento di default**: se spento, il sistema si
   comporta esattamente come prima → aggiungere roba nuova **non può rompere** il vecchio.
3. **Compartimento stagno (fail-closed)**: se un pezzo esplode, **degrada** (si spegne
   da solo), non propaga l'errore.
4. **Astrazioni sostituibili**: provider intercambiabili (stub finto nei test, reale in
   produzione) per IA, pagamenti, notifiche, database.
5. **Test dedicati verdi + zero regressioni** sull'intera suite.

> Conseguenza pratica: **puoi aggiungere un fronte nuovo senza toccare il nucleo.**

---

## 3. Mappa delle cartelle — dove sta cosa

| Cartella / file | Cosa contiene | Quando ci entri |
|---|---|---|
| `fase17_money.py` … `fase56_*.py` | **Il software vero**: ogni "mattone" è un file numerato. | Per cambiare una regola di business. |
| `test_*.py` | Le prove automatiche di ogni mattone (~57 suite). | Per verificare che tutto regga. |
| `app.py`, `assistente_gestionale.py` | Motore A (la Fortezza originale). | Raramente. |
| `.env` | **I segreti veri** (chiavi Stripe, password, ecc.). Git-ignorato. | Per configurare prima del lancio. |
| `.env.example` | Modello con i nomi delle chiavi (senza valori veri). | Per sapere cosa va compilato. |
| `deploy/` | Configurazioni del server: Nginx, SSL, backup, smoke-test. | Per pubblicare online. |
| `Dockerfile`, `docker-compose*.yml` | Le ricette per accendere i container. | Per avviare/deployare. |
| `.github/workflows/ci.yml` | Test automatici a ogni modifica (CI). | Automatico, non lo tocchi. |
| `ARCHITETTURA.md` | Radiografia tecnica dettagliata di Tavola VIP. | Per i dettagli ingegneristici. |
| `MASTERPLAN.md` | La bussola: dove si va e stato mattone-per-mattone. | Per capire la roadmap. |
| `ROADMAP_MANGO.md` | Piano del satellite commerciale Mango. | Per capire Mango. |
| `DEPLOY.md` | Guida operativa al deploy (comandi pronti). | Quando pubblichi. |
| `contratti_frontend_tavoli.md` | I contratti JSON per il sito/app frontend. | Per chi costruisce la UI. |
| `Quantum_Security_Engine/`, `Guardian_Module/`, `AI_Recombined/` | **Esperimenti vecchi (legacy)**, NON collegati al prodotto. | Mai (storico). |

> ⚠️ Nota importante: nei vecchi appunti queste tre ultime cartelle erano descritte
> come "cassaforte", "poliziotto", ecc. In realtà **il prodotto vivo non le usa**: la
> sicurezza vera sta dentro i moduli `faseNN_*.py` (HMAC, auth per-cliente, firme
> webhook). Sono residui di esperimenti precedenti.

---

## 4. Anatomia completa — tutte le fasi, in dettaglio

Ogni mattone è un file. Qui c'è **cosa è stato inserito**, in ordine.

### 4.1 Fondamenta riusabili (la cassaforte)

| Fase | File | Cosa fa |
|---|---|---|
| 15 | `fase15` (idempotency) | Garantisce **una sola** esecuzione di un'azione anche se arriva due volte ("exactly-once" in ingresso). |
| 16 | `fase16_outbox.py` | **Outbox**: ogni messaggio in uscita viene consegnato almeno una volta (retry, code di priorità, DLQ). |
| 17 | `fase17_money.py` | **Il denaro**: solo centesimi interi. `parse_cent`, `valida_split`, `applica_percentuale`. **Mai float.** |
| 23 | `fase23_datastore.py` | Astrazione del database: oggi SQLite, pronto per PostgreSQL senza riscrivere il codice. |
| 24 | `fase24_channels.py` | I **canali social** in uscita (adapter + registro + Telegram reale). |
| 29 | `fase29_backpressure.py` | **Backpressure**: sotto picco estremo la coda resta limitata e i task critici sono protetti al 100%. |

### 4.2 Cervello conversazionale (fasi 24–33)

Questa è l'IA che parla coi clienti. È **già pronta e testata**, riusabile da Tavola
VIP e da Mango.

| Fase | File | Cosa fa |
|---|---|---|
| 25 | `fase25_brain.py` | `ResilientBrain`: l'IA con timeout, circuit-breaker, cache e **isolamento totale** (se l'IA cade, niente crash). |
| 26 | `fase26_ricerca.py` | Motore di ricerca alloggi protetto (cache + breaker). |
| 27 | `fase27_proposte.py` | Genera proposte commerciali. **Le commissioni le calcola il sistema in centesimi, mai l'IA.** |
| 28 | `fase28_gateway.py` | **API Gateway**: autenticazione per-cliente (`X-Client-Key`) timing-safe, validazione blindata. |
| 30 | `fase30_llm.py` | Client LLM reale: **budget token spietato** (mai sforare la finestra) + compressione del contesto. |
| 31 | `fase31_conversazione.py` | Memoria multi-turno per chat (l'agente ricorda la conversazione). |
| 32 | `fase32_governatore.py` | **Governatore globale di token/quota**: tetto di spesa LLM condiviso su tutte le chat → la spesa non sfora mai. |
| 33 | `fase33_persistenza.py` | Memoria conversazionale **durevole e cross-worker** (sopravvive a riavvii e a più worker). |

### 4.3 Prodotto Tavola VIP — prenotazioni + pagamenti (fasi 34–42)

**È il cuore che incassa.** Servito da `fase36_booking_api:crea_app_da_env()`.

| Fase | File | Cosa fa |
|---|---|---|
| 34 | `fase34_prenotazioni.py` | **Il cuore**: `MotorePrenotazioni`. Disponibilità via overlap; `crea()` **atomica** (anti doppia-prenotazione); scadenza hold non pagati; workflow rimborso; emissione voucher. |
| 35 | `fase35_pagamenti.py` | **Stripe**: link di checkout, webhook **firmato** (una notifica falsa non conferma nulla), rimborsi. |
| 36 | `fase36_booking_api.py` | **Le rotte HTTP** (`/api/v1`): crea prenotazione → 201 + `payment_url`; stato; cancella; rimborso; webhook; `/health`. |
| 37 | `fase37_notifiche.py` | Invio voucher con **retry + fallback** multi-canale (WhatsApp → email). |
| 38 | `fase38_backup.py` | Backup DB consistente + retention con tetto di spazio. |
| 39 | `fase39_whatsapp.py` | Notifiche via WhatsApp (Meta Cloud API). |
| 40 | `fase40_agente_booking.py` | **L'agente IA che prenota**: chat → intento → JSON validato → prenotazione + link. Denaro dal sistema. |
| 41 | `fase41_admin_panel.py` | **Pannello web** (Basic auth + CSRF): vedi prenotazioni, calendario, **approva rimborsi**. |
| 42 | `fase42_observability.py` | **Log in JSON** + metriche Prometheus (`/metrics`). |

### 4.4 Satellite commerciale Mango (fasi 43–49)

Lo strato che porta nuovi host e converte. **Mango propone; il nucleo booking decide
e incassa.** Tocca il denaro solo attraverso la stessa porta sicura della fase 40.

| Fase | File | Cosa fa |
|---|---|---|
| 43 | `fase43_commissione.py` | **Motore commissionale** iniettabile: `PoliticaRanaInversa` (Pioniere a tempo + **cricchetto** che non risale mai) per Mango, `PoliticaQuotaFissa` per Tavola Privé. PSP pass-through esplicito. |
| 44 | `fase44_prezzo.py` | **Motore del prezzo** "Host-Authoritative": il prezzo è la **tariffa dell'host** (dal suo PMS), con floor e Price Circuit Breaker. L'OTA è solo un confronto informativo, **mai** input del prezzo. |
| 45 | `fase45_pricing.py` | **Split a 3 vie**: il surplus liberato lasciando l'OTA è ripartito tra guest (sconto), host (margine) e Mango (sostenibilità). Conservazione esatta al centesimo. |
| 46 | `fase46_esploratore.py` | **Property intelligence**: ingerisce da fonti **lecite** (API partner, metasearch, sito host, iCal), calcola la **perdita annua con l'OTA** e un **pain-score** per ordinare i lead più caldi. |
| 47 | `fase47_venditore.py` | **Outreach** consensato (GDPR/opt-out), con cadenza anti-spam, dedup e backpressure. Pianifica chi contattare, non invia direttamente. |
| 48 | `fase48_advertising.py` | **Campagne**: budget calcolato dal core in centesimi, contenuti generati via IA (che non tocca il denaro), allocazione proporzionale con floor. |
| 49 | `fase49_ponte_booking.py` | **Il ponte**: quando una chat converte, crea prenotazione + link **riusando la porta di fase40**. Unico touchpoint col denaro di Mango. Idempotente (zero prenotazioni doppie). |

### 4.5 Il funnel autonomo Mango (fasi 50–55)

Qui Mango diventa una macchina che gira **da sola**.

| Fase | File | Cosa fa |
|---|---|---|
| 50 | `fase50_orchestratore.py` | Cabla i 7 mattoni in **una pipeline**: esplora → outreach → advertising → conversione/ponte. Ogni stadio è isolato (se uno cade, gli altri proseguono, con report). |
| 51 | `fase51_scheduler.py` | Fa girare l'orchestratore **in modo ricorrente** su una coda di lavori, protetto dalla quota token globale (quota negata → ciclo differito, mai sforato). |
| 52 | `fase52_persistenza_metriche.py` | Salva ogni ciclo su **SQLite durevole** + aggrega le **metriche** (conversion rate, guasti per stadio). |
| 53 | `fase53_healthguard.py` | **Self-governance**: legge le metriche, e se il funnel degenera **apre un circuito** che lo mette in pausa; lo riapre da solo quando guarisce. |
| 54 | `fase54_loop.py` | Il **daemon**: a ogni tick consulta il circuito (gate), fa girare lo scheduler, ri-alimenta le metriche. Cadenza stabile (fixed-rate no-burst). |
| 55 | `fase55_bootstrap.py` | **Punto unico di accensione**: da una `ConfigMango` assembla tutto lo stack e restituisce un `SistemaMango` pronto, con report di cosa è attivo e cosa manca. |

### 4.6 Gateway Tavoli VIP — il ponte col frontend (fase 56)

| Fase | File | Cosa fa |
|---|---|---|
| 56 | `fase56_gateway_tavoli.py` | **Il ponte frontend↔backend**: contratti JSON per ricevere prenotazioni dalla UI e rispondere. Denaro **solo in centesimi interi** (`*_cents: int`); float, bool e stringhe numeriche **rifiutati**. Clienti **enterprise** separati per locale (isolamento per-tenant). Money-path unico = il Ponte (fase49). |

---

## 5. Il flusso del denaro — dalla richiesta all'incasso

**A) Prenotazione diretta + pagamento**
1. Arriva `POST /api/v1/reservations` con header `X-Booking-Key`.
2. Validazione: importi via `parse_cent` (un float viene **rifiutato**).
3. Creazione **atomica**: re-check overlap (anti doppia prenotazione) → INSERT
   prenotazione (`in_attesa_pagamento`) + split + escrow (`bloccato`).
4. Si genera il link Stripe Checkout (importo in **cents**) → **201 + `payment_url`**.
5. Il cliente paga. Stripe chiama `POST /api/v1/payments/webhook` (con **firma**).
6. Verifica firma → conferma → emissione voucher → notifica (WhatsApp → email).

**B) Prenotazione via chat (agente IA)**
Chat → l'IA estrae l'intento e i dati → il **sistema calcola il denaro** → crea
prenotazione → link di pagamento. Se l'IA è giù: errore isolato, **nessuna**
prenotazione fantasma.

**C) Rimborso (autorizzato dall'admin)**
Richiesta rimborso → stato `rimborso_richiesto` → l'admin approva sul pannello (fase41)
→ refund Stripe **fuori dal lock** → tavolo liberato. **Il denaro si muove solo con
approvazione admin.**

---

## 6. Come intervenire in OGNI punto (mappa pratica)

| Se devi… | Vai in… | Nota |
|---|---|---|
| Cambiare **prezzi / commissioni** | `fase43_commissione.py` (commissione), `fase44_prezzo.py` (prezzo), `fase45_pricing.py` (split 3 vie) | Solo lì sta la matematica. Mai toccare i soldi nel frontend. |
| Cambiare la **logica di prenotazione** | `fase34_prenotazioni.py` | È il cuore atomico: cambia con cautela e rilancia i test. |
| Cambiare **pagamenti / rimborsi** | `fase35_pagamenti.py` | Stripe e webhook firmati. |
| Aggiungere/cambiare **rotte HTTP** | `fase36_booking_api.py` | Le API pubbliche di Tavola VIP. |
| Cambiare i **messaggi al cliente** | `fase37_notifiche.py`, `fase39_whatsapp.py` | Voucher, canali, fallback. |
| Cambiare il **comportamento dell'IA** | `fase40_agente_booking.py` (booking), `fase25/30/31` (cervello) | Il denaro non passa mai dall'IA. |
| Gestire **rimborsi a mano** | Pannello admin: `fase41_admin_panel.py` | Apri `/admin`, autentica, approva/rifiuta. |
| Vedere **log e metriche** | `fase42_observability.py` → endpoint `/metrics` | Esponi `/metrics` solo alla rete interna. |
| Cambiare **chi contattare e come** (host) | `fase47_venditore.py` | Regole GDPR/cadenza/dedup. |
| Cambiare le **campagne pubblicitarie** | `fase48_advertising.py` | Budget dal core, contenuti dall'IA. |
| Accendere/spegnere **Mango** | `fase55_bootstrap.py` + variabili `MANGO_*` nel `.env` | Default-OFF: di base Mango è spento. |
| Cambiare i **contratti col sito** (frontend) | `fase56_gateway_tavoli.py` + `contratti_frontend_tavoli.md` | Importi solo in `*_cents` interi. |
| Cambiare **configurazione/segreti** | `.env` | Mai nel codice, mai su Git. |
| Cambiare **dominio / SSL / server** | `deploy/nginx*.conf` + `docker-compose*.yml` + `DEPLOY.md` | Vedi sezione 8. |
| Capire **perché si è bloccato** | Sezione 9 + i log dei moduli | Spesso è un circuito/health-guard che ha protetto il sistema. |

---

## 7. Cosa serve per accendere tutto (chiavi e dipendenze)

Tutto si configura nel file **`.env`** (copia da `.env.example`). Genera i segreti con:
`python -c "import secrets; print(secrets.token_hex(32))"`.

**Obbligatorie per il prodotto (Tavola VIP):**
- `STRIPE_API_KEY` — chiave segreta Stripe (`sk_test_...` in prova, `sk_live_...` dal vivo).
- `STRIPE_WEBHOOK_SECRET` — firma webhook (Dashboard Stripe → Developers → Webhooks).
- `BOOKING_API_KEY` — header `X-Booking-Key` per creare prenotazioni.
- `BOOKING_ADMIN_KEY` — header `X-Admin-Key` per approvare/rifiutare rimborsi.
- `BOOKING_SUCCESS_URL` / `BOOKING_CANCEL_URL` — dove torna il cliente dopo il pagamento.
- `ADMIN_PANEL_USER` / `ADMIN_PANEL_PASSWORD` — accesso al pannello admin.

**Per la Fortezza (motore A), in produzione:** `HMAC_SECRET`, `API_KEY`,
`BEARER_TOKEN`, `ADMIN_TOKEN`, `POSTGRES_PASSWORD`. Se restano ai valori `cambiami_*`,
**l'app non parte** (fail-fast voluto).

**Per i canali / IA (opzionali, attivano funzioni live):**
- Chiave LLM (Anthropic) per l'agente IA reale.
- Credenziali WhatsApp Business / Instagram Graph per i social.
- `TELEGRAM_*` per Telegram.

**Per Mango (default-OFF):** variabili `MANGO_ORCHESTRATORE`, `MANGO_SCHEDULER`,
`MANGO_LOOP`, `CORE_PONTE_BOOKING`, ecc. — finché non le accendi, Mango non gira.

**Dipendenze software:** alcune librerie (Stripe, Anthropic, WhatsApp, Playwright,
geopy, icalendar) sono caricate **lazy**: se mancano, il pezzo **degrada** invece di
crashare. Per il deploy serve **Docker + Docker Compose v2**; per l'HTTPS un **dominio**.

---

## 8. Manuale d'uso — dal test privato al business vincente

### Passo 0 — Verifica che la macchina sia sana (in locale)
```
python -m unittest discover -p "test_*.py"
```
Tutte verdi = la macchina è integra. (Nota: su questo PC il comando è `python`, **non**
`python3`.)

### Passo 1 — Test privato, senza esporre nulla online
1. Tieni Stripe in modalità **test** (`sk_test_...`): paghi con carte finte, zero soldi veri.
2. Avvia il prodotto in locale:
   ```
   gunicorn -b 0.0.0.0:8001 "fase36_booking_api:crea_app_da_env()"
   ```
3. Prova le API con prenotazioni di test (crea → ricevi `payment_url` → simula il pagamento).
4. Apri il pannello admin (`fase41`) per vedere prenotazioni e provare i rimborsi.

### Passo 2 — Smoke test (controllo rapido che tutto risponda)
```
BASE_URL=http://127.0.0.1 BOOKING_API_KEY=<la_tua> bash deploy/smoke_tavolavip.sh
```
Controlla: health, create+link, overlap 409, webhook con firma errata 400, cancel.

### Passo 3 — Deploy invisibile (online ma solo per te)
1. Compila il `.env` con i segreti veri (vedi sezione 7).
2. Avvia lo stack dedicato:
   ```
   docker compose -f docker-compose.tavolavip.yml up -d --build
   docker compose -f docker-compose.tavolavip.yml ps   # colonna health
   ```
3. **Whitelist firewall**: apri l'accesso solo al **tuo IP** finché non sei pronto al pubblico.

### Passo 4 — Go-live pubblico (HTTPS + dominio)
1. Punta un dominio (record A) all'IP del server.
2. Metti il dominio in `deploy/nginx.tavolavip.ssl.conf`, ottieni i certificati Let's
   Encrypt, avvia `docker-compose.tavolavip.ssl.yml` (vedi `DEPLOY.md` per i comandi esatti).
3. Passa Stripe a **live** (`sk_live_...`) e aggiorna l'URL del webhook a
   `https://<tuodominio>/api/v1/payments/webhook`.
4. Attiva il **backup automatico** (cron ogni 6 ore, vedi `DEPLOY.md`).

### Passo 5 — Accendi il motore commerciale (Mango) quando vuoi crescere
Mango è **spento di default**. Quando hai host e canali pronti:
1. Attiva i flag `MANGO_*` e `CORE_PONTE_BOOKING` nel `.env`.
2. Fornisci le credenziali dei canali social e la chiave LLM.
3. Mango inizierà a esplorare host, contattarli (in modo legale), proporre e — quando
   convertono — agganciare prenotazioni reali tramite la stessa porta sicura.

### La strategia "business vincente" (in breve)
- **Arma 1 — Commissione "Rana Inversa"**: tariffe più basse delle OTA, con il
  **Pioniere bloccato a vita** (cricchetto che non risale) → gli host non se ne vanno più.
- **Arma 2 — Escape Analysis**: mostri all'host quanto ha **perso in 12 mesi** con l'OTA.
- **Arma 3 — Prezzo dell'host (Host-Authoritative)**: il prezzo è il suo, non quello
  dell'OTA → legale, deterministico, difendibile.
- **Arma 4 — Split a 3 vie**: il risparmio sulla commissione lo dividi tra guest, host
  e te → tutti hanno un incentivo a restare (flywheel).

> Direttiva strategica registrata: il modello è **jurisdiction-agnostic** (nessuna
> regola IVA/EU hardcoded; la tassa passa da una variabile, default 0) per poter
> spostare la base fiscale dove conviene.

---

## 9. Quando si rompe — diagnosi e dove guardare

| Sintomo | Dove guardare | Causa probabile |
|---|---|---|
| Il sistema è "fermo" | I log + il circuito (`fase53_healthguard.py`) | **Non è un bug**: l'health-guard ha messo in pausa il funnel perché degradava. Si riapre da solo. |
| Pagamento incassato ma tavolo già preso | log `Conferma su tavolo gia' occupato ... da RIMBORSARE` (fase34) | Conflitto raro → va rimborsato. |
| Webhook ignorato | log `firma webhook non valida` (fase35) | Firma errata / `STRIPE_WEBHOOK_SECRET` sbagliato. |
| Voucher non arrivato | log `Notifica voucher fallita (ignorata)` (fase35/37/39) | Canale giù — non blocca l'incasso. |
| L'agente non prenota | log `Brain: provider ha sollevato (-> fallback)` (fase25) | IA giù/lenta → fallback, nessuna prenotazione fantasma. |
| Refund non parte | log `rimborso fallito` (fase35) | Errore Stripe lato refund. |
| App non parte in produzione | Avvio | Segreti `cambiami_*` non sostituiti (fail-fast voluto). |

**Dove sono i log:** tutti su stdout (con `configura_logging_json` diventano JSON
interrogabili). In Docker: `docker compose -f docker-compose.tavolavip.yml logs -f booking`.

---

## 10. Manutenzione, backup e integrità

- **Database**: SQLite su volume persistente, modalità WAL. Lo schema si crea da solo
  al boot (idempotente).
- **Backup**: `deploy/backup_tavolavip.sh` (cron) → snapshot consistente + retention con
  tetto di spazio. Ripristino con `fase38_backup.ripristina(...)`.
- **Backup fisico** (extra): copia l'intera cartella `Core_Auto` su USB/cloud ogni settimana.
- **Verifica integrità**:
  1. Suite test: `python -m unittest discover -p "test_*.py"`.
  2. CI automatica su GitHub a ogni push/PR (Python 3.9 e 3.11).
  3. `PRAGMA integrity_check` sul DB.
- **Espandere senza rompere**: nuovo fronte = nuovo `faseNN_*.py` + suo test,
  **default-off**, import lazy → la suite resta verde per costruzione. Nuovo provider =
  implementi l'ABC esistente, zero patch al nucleo.
- **Codice sorgente**: https://github.com/edilmax/Core_Auto

---

## 11. Glossario

- **OTA**: Online Travel Agency (Booking, Expedia…) — gli intermediari da scavalcare.
- **Escrow**: i fondi restano "bloccati" finché non si decide se incassare o rimborsare.
- **Split**: la divisione di un pagamento tra le parti (host, piattaforma, ecc.).
- **Idempotente / idempotenza**: ripetere un'azione non produce effetti doppi.
- **Fail-closed / fail-fast**: in caso di dubbio o segreto mancante, il sistema si
  **ferma in sicurezza** invece di fare danni.
- **Circuit breaker / circuito**: interruttore automatico che stacca un pezzo malato e
  lo riattacca quando guarisce.
- **Backpressure**: meccanismo che, sotto troppo carico, protegge i compiti critici e
  scarta/differisce il resto.
- **Webhook**: una chiamata che un servizio esterno (Stripe) fa al tuo server per
  avvisarti di un evento (es. "pagamento completato").
- **Voucher**: la conferma/buono emesso al cliente dopo il pagamento.
- **PMS / channel manager**: il gestionale dell'host che fissa le tariffe.
- **Lead / pain-score**: un host potenziale e il punteggio che dice quanto è "caldo".
- **Feature-flag**: un interruttore (in `.env`) che accende/spegne una funzione.
- **Centesimi interi (cents)**: tutti i soldi sono numeri interi di centesimi, **mai**
  numeri con la virgola (float) → zero errori di arrotondamento.

---

*Fine del manuale. Stato del sistema: Fase 56 (Sigillata).*
