> 🔄 Aggiornato 2026-06-29 · **BookinVIP** · suite **1851 test** (0 regressioni) · moduli `faseNN`→160 · infra VPS Aruba 89.46.65.6 ATTIVO · fonte di verità: **STATO_FINALE.md**

# Tavola VIP — Radiografia tecnica del sistema

> Mappa completa del software. Aggiornare quando si aggiunge/cambia un mattone.
> Prodotto = **Tavola VIP** (prenotazioni "Tavoli VIP" con pagamento Stripe),
> costruito sopra i mattoni riusabili di CORE_AUTO. Runtime **Python 3.9**, test
> con **unittest** (487 verdi), denaro **sempre in centesimi interi** (zero float).

---

## 0. La regola che governa tutto (contratto d'isolamento)

Ogni mattone e' un **modulo `faseNN_*.py` a se'**, con:
1. import **lazy** dal core (il core non importa il mattone al boot);
2. **feature-flag** / default-off (spento ⇒ comportamento attuale identico);
3. **fail-closed / isolamento** (se un pezzo esplode, degrada, non propaga un 500);
4. **astrazione + stub** (provider sostituibile: stub deterministico nei test,
   reale in prod) — `LLMProvider`, `PagamentoProvider`, `Notificatore`, `Datastore`;
5. **suite di test dedicata** verde + **zero regressioni** sulla suite intera.

Conseguenza pratica: si **aggiunge** un fronte nuovo senza toccare il nucleo.

---

## 1. Anatomia del repository

### 1a. I due "cervelli applicativi" (NON confonderli)
- **`app.py`** = la *fortezza* CORE_AUTO originale (marketplace escrow/split,
  HMAC, rate-limit, idempotency, audit). Serve `assistente_gestionale.py`.
- **Tavola VIP** = il prodotto nuovo, app **standalone** servita da
  `fase36_booking_api:crea_app_da_env()` (e dal pannello
  `fase41_admin_panel:crea_app_admin_da_env()`). E' questo che stiamo costruendo.

### 1b. Mattoni di base riusati dal prodotto
| File | Cosa fornisce |
|---|---|
| `fase17_money.py` | denaro in **centesimi interi**: `parse_cent`, `valida_split`, `applica_percentuale`, `euro_to_cents`. **Il denaro non e' MAI float.** |
| `fase23_datastore.py` | astrazione `Datastore` (SQLite oggi, Postgres-ready). |
| `fase25_brain.py` | `LLMProvider` (ABC) + `ResilientBrain` (timeout/circuit-breaker/cache/**isolamento totale**). |
| `fase16_outbox.py`, `fase24_channels.py` | consegna at-least-once + adapter social (riusati dalle notifiche/agente). |

### 1c. Lo stack del prodotto — come si intrecciano le fasi 34→42
```
        (chat cliente)            (HTTP diretto / agente / PR)
   fase40 AgenteBooking ───────────────┐
   (Claude → intento → JSON)            │
                                        ▼
   fase36 booking_api  ──►  fase34 MotorePrenotazioni  ──►  SQLite (tavolavip.db)
   (rotte HTTP, auth)        (overlap + transazione atomica         ▲  ▲  ▲
        │                     prenotazione+split+escrow)            │  │  │
        ▼                                 │                  prenotazioni│ │
   fase35 ServizioPagamenti ◄─────────────┘                  pagamenti_split│
   (PagamentoProvider: Stripe/Stub;                          escrow_fondi  │
    link checkout, webhook firmato, refund)                  voucher_prenotazioni
        │ (al pagamento confermato)
        ▼
   fase37 ServizioNotifiche ──► RouterNotifiche (retry + FALLBACK)
        │                         ├─ fase39 WhatsAppNotificatore (Cloud API)
        │                         └─ EmailNotificatore (SMTP)
        ▼
   (voucher consegnato al cliente)

   fase41 AdminPanel (web, Basic+CSRF) ──► approva/rifiuta rimborsi, annulla
   fase42 Observability ──► log JSON + metriche /metrics (strumenta l'app booking)
   fase38 backup.py ──► snapshot SQLite consistente + retention (cron)
```

| Fase | File | Ruolo nel prodotto | Test |
|---|---|---|---|
| **34** | `fase34_prenotazioni.py` | **Cuore**: `MotorePrenotazioni`. Disponibilita' via **overlap** a intervalli semi-aperti; `crea()` **atomica** (BEGIN IMMEDIATE, re-check anti-TOCTOU); scadenza **hold** non pagati; workflow **rimborso** (richiedi/completa/rifiuta); `emetti_voucher`; `elenco` (dashboard). Schema autonomo (`inizializza_schema`). | test_fase34 |
| **35** | `fase35_pagamenti.py` | `PagamentoProvider` (ABC) → `StripeProvider` (lazy) + `StubPagamentoProvider` (webhook HMAC); `ServizioPagamenti`: link checkout, `gestisci_webhook` (firma → conferma → voucher → notifica), `approva_rimborso` (refund Stripe **fuori dal lock** + `completa_rimborso`). | test_fase35 |
| **36** | `fase36_booking_api.py` | **Rotte HTTP** (`/api/v1`): `POST /reservations` (X-Booking-Key) → 201+`payment_url`; `GET /reservations/<id>`; cancel; **refund-request** (booking) / **refund-approve/reject** (X-Admin-Key); `POST /payments/webhook` (firma PSP); `/health`. `crea_app_da_env()` cabla tutto da env + observability. | test_fase36 |
| **37** | `fase37_notifiche.py` | `Notificatore` (ABC) + `EmailNotificatore` (SMTP) + `RouterNotifiche` (**retry + fallback multi-canale**, isolato) + `ServizioNotifiche` (consegna voucher). | test_fase37 |
| **38** | `fase38_backup.py` | Backup DB: **Online Backup API** (snapshot consistente) + retention **size-cap** + gzip; `ripristina`; entrypoint cron. | test_fase38 |
| **39** | `fase39_whatsapp.py` | `WhatsAppNotificatore` (Meta **Cloud API**, lazy, template) innestato nel router; factory completa email+WhatsApp. | test_fase39 |
| **40** | `fase40_agente_booking.py` | `AnthropicLLMProvider` (SDK reale, lazy, chiave solo da env) + `AgenteBooking`: **chat → intento → JSON validato → prenotazione + link**. Denaro **dal sistema, mai dall'IA**. | test_fase40 |
| **41** | `fase41_admin_panel.py` | **Pannello web** server-rendered: **Basic auth timing-safe + CSRF**, fail-closed; dashboard prenotazioni/calendario + **approva rimborsi** (aggancia fase35). | test_fase41 |
| **42** | `fase42_observability.py` | **Log JSON** (`FormatterJSON`) + **metriche** thread-safe (`RegistroMetriche`) → `/metrics` Prometheus; `strumenta_app`. | test_fase42 |

### 1d. Infra & deploy (cartella `deploy/` + radice)
- `Dockerfile` (multi-stage, non-root) — immagine condivisa.
- `docker-compose.tavolavip.yml` / `.ssl.yml` — stack `nginx → booking` (+ TLS).
- `deploy/nginx.tavolavip.conf` / `.ssl.conf` — reverse proxy; **`/metrics` negato dall'esterno**.
- `deploy/smoke_tavolavip.sh` — smoke post-deploy; `deploy/backup_tavolavip.sh` — cron backup.
- `.github/workflows/ci.yml` — CI (Python 3.9+3.11) ad ogni push/PR.
- `.env` (**gitignored**, segreti) · `.env.example` (placeholder) · `DEPLOY.md` · `MASTERPLAN.md` · `CLAUDE.md`.

> NB residui legacy NON collegati al prodotto: `super_ai_creator.py`, `super_linker.py`,
> `Guardian_Module/`, `Quantum_Security_Engine/`, `AI_Recombined/` (vecchi esperimenti).

---

## 2. Flusso dei dati — dalla richiesta all'incasso

### A) Prenotazione diretta + pagamento
1. **Ingresso**: `POST /api/v1/reservations` con header `X-Booking-Key` (fase36).
2. **Validazione**: campi + importi via `parse_cent` (float rifiutato).
3. **Creazione ATOMICA** (`MotorePrenotazioni.crea`, fase34): `BEGIN IMMEDIATE` →
   **re-check overlap** (anti doppia-prenotazione) → INSERT `prenotazioni`
   (`in_attesa_pagamento`) + `pagamenti_split` (`valida_split`) + `escrow_fondi`
   (`bloccato`) → COMMIT.
4. **Link**: `ServizioPagamenti.crea_link_pagamento` → Stripe Checkout Session
   (importo in **cents**, `pagamento_id` in metadata) → **201 + `payment_url`**.
5. **Pagamento**: il cliente paga su Stripe. Stripe chiama
   `POST /api/v1/payments/webhook` (**firma** `Stripe-Signature`).
6. **Conferma** (`gestisci_webhook`): verifica firma → `conferma_pagamento`
   (re-check disponibilita' escludi-self, stato → `pagata`, salva ref PSP) →
   `emetti_voucher` → `ServizioNotifiche.invia_voucher` (**WhatsApp → email**,
   isolato). Escrow resta `bloccato` (sblocco/rimborso = decisione successiva).

### B) Prenotazione via chat (agente IA)
`AgenteBooking.gestisci_chat` → `ResilientBrain(AnthropicLLMProvider).genera`
→ estrae JSON {intento, alloggio, date, contatti} → valida → se completo:
**denaro calcolato dal sistema** → `motore.crea` → `crea_link_pagamento` →
risposta col link. Incompleto ⇒ chiede; IA giu' ⇒ errore isolato, niente prenotazione.

### C) Rimborso (gated da admin)
`POST /refund-request` (booking) → stato `rimborso_richiesto` (tavolo ancora
occupato). Admin sul **pannello** (fase41) o via `X-Admin-Key` →
`approva_rimborso`: **refund Stripe FUORI dal lock** → `completa_rimborso`
(escrow `rimborsato`, pagamento `refunded`, prenotazione `rimborsata`, tavolo libero).

---

## 3. Strategia di fail-safe — dove guardare quando si rompe

### Garanzie d'isolamento (per design)
- Notifica giu' ⇒ **non** rompe la conferma del pagamento (best-effort isolato).
- IA giu'/lenta ⇒ `ResilientBrain` → fallback, **nessuna** prenotazione fantasma.
- Webhook con firma errata ⇒ **nessun** cambio di stato (403/400).
- Denaro: si muove **solo** con approvazione admin in stato valido.
- Segreto mancante ⇒ **fail-closed** (Stripe/Anthropic/pannello → errore chiaro/503).

### Logger (tutti su stdout; con `configura_logging_json` diventano JSON)
`core_auto.prenotazioni` · `core_auto.pagamenti` · `core_auto.booking_api` ·
`core_auto.notifiche` · `core_auto.whatsapp` · `core_auto.agente_booking` ·
`core_auto.admin_panel` · `core_auto.observability` · `core_auto.brain`.

### Punti di log CRITICI da cercare
| Sintomo | Log da cercare | Modulo |
|---|---|---|
| Pagamento incassato ma tavolo gia' preso | `Conferma su tavolo gia' occupato ... da RIMBORSARE` | fase34 |
| Webhook ignorato | `firma webhook non valida` / esito `non_valido` | fase35 |
| Voucher non arrivato | `Notifica voucher fallita (ignorata)` / `invio fallito` | fase35/37/39 |
| Agente non prenota | `Brain: provider ha sollevato (-> fallback)` | fase25 |
| Refund non parte | `rimborso fallito` / esito `refund_psp_fallito` | fase35 |

### File/superfici da controllare
1. **Log applicazione**: `docker compose -f docker-compose.tavolavip.yml logs -f booking` (JSON).
2. **`/metrics`** (rete interna): contatori errori + latenze HTTP.
3. **DB**: `data/tavolavip.db` (`PRAGMA integrity_check`); stati delle prenotazioni.
4. **nginx**: log del reverse proxy (TLS, rate-limit, 4xx/5xx).
5. **Stripe Dashboard**: eventi webhook (consegnati/falliti), refund.

---

## 4. Manutenzione

### Gestione del database
- **Dov'e'**: SQLite su volume persistente (`/data/tavolavip.db`), modalita' **WAL**.
- **Schema**: creato da `MotorePrenotazioni.inizializza_schema()` (idempotente):
  `prenotazioni`, `pagamenti_split` (cents), `escrow_fondi`, `voucher_prenotazioni`.
- **Backup**: `deploy/backup_tavolavip.sh` (cron) → snapshot **consistente** + retention
  size-cap. **Ripristino**: `fase38_backup.ripristina(<gz>, <db>)`.
- **Housekeeping**: `MotorePrenotazioni.libera_hold_scaduti()` libera gli hold non pagati
  (la disponibilita' li ignora gia' anche senza job).
- **Cutover Postgres** (mattone #9, da fare): il `Datastore` (fase23) e' gia' PG-ready.

### Verifica d'integrita'
1. **Suite test**: `python -m unittest discover -p "test_*.py"` → atteso **487 OK** (3 skip PG).
2. **CI**: gira da sola su GitHub ad ogni push/PR (Python 3.9 e 3.11).
3. **Smoke live**: `BASE_URL=... BOOKING_API_KEY=... bash deploy/smoke_tavolavip.sh`
   (health, create+link, overlap 409, webhook firma errata 400, cancel).
4. **Integrita' DB**: `PRAGMA integrity_check`.

### Espandere senza creare conflitti
- **Nuovo fronte** = nuovo modulo `faseNN_*.py` + suo `test_faseNN_*.py`,
  **default-off**, import lazy → la suite resta verde **per costruzione**.
- **Nuovo provider** (es. altro PSP, altro LLM, SMS): implementa l'ABC esistente
  (`PagamentoProvider`/`LLMProvider`/`Notificatore`) e registralo — **nessuna**
  modifica al nucleo.
- **Metodo**: spike → benchmark sotto carico → test → integra **solo la vincitrice**
  → gate di regressione. Un mattone = un commit isolato.
- **Segreti**: solo in `.env` (gitignored); placeholder in `.env.example`; mai nel codice.
