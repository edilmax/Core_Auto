> 🔄 Aggiornato 2026-06-29 · **BookinVIP** · suite **1875 test** (0 regressioni) · moduli `faseNN`→162 · infra VPS Aruba 89.46.65.6 ATTIVO · fonte di verità: **STATO_FINALE.md**

# CORE_AUTO

Marketplace finanziario (escrow + split payment) con API REST Flask, hardening di
sicurezza (audit Red Team) e garanzie di **idempotenza exactly-once** sulle
operazioni mutanti.

> Convenzioni: identificatori in inglese, commenti/log/documentazione in italiano.
> Runtime: **Python 3.9**. Test con `unittest` (pytest non installato).

## Indice

- [Struttura](#struttura)
- [Avvio e test](#avvio-e-test)
- [Variabili d'ambiente](#variabili-dambiente)
  - [Segreti — obbligatori in produzione](#segreti--obbligatori-in-produzione)
  - [Applicazione e database](#applicazione-e-database)
  - [Sicurezza e reverse proxy](#sicurezza-e-reverse-proxy)
  - [Idempotenza (Fase 15)](#idempotenza-fase-15)
  - [Gunicorn e runtime](#gunicorn-e-runtime-gunicornconfpy)
  - [Watchdog, alerting e feature flag](#watchdog-alerting-e-feature-flag)
  - [Email e ricerca esterna](#email-e-ricerca-esterna-assistente_gestionalepy)
- [Sicurezza — Audit Red Team](#sicurezza--audit-red-team)
  - [Gruppo 1 — CRITICAL](#gruppo-1--critical-3961c48)
  - [Gruppo 2 — HIGH](#gruppo-2--high-b38acc7)
  - [Gruppo 3 — MEDIUM](#gruppo-3--medium-70743b8)
  - [Hardening incrementale (Fasi 18–22)](#hardening-incrementale-fasi-1822)
- [Fase 15 — Idempotency Manager](#fase-15--idempotency-manager-exactly-once)
  - [Uso lato client](#uso-lato-client)
  - [Architettura](#architettura)
  - [Manutenzione (su 3 livelli)](#manutenzione-su-3-livelli)
  - [API del manager](#api-del-manager-per-integrazioni)
  - [Test](#test)

## Struttura

| File | Ruolo |
|------|-------|
| `assistente_gestionale.py` | Core monolitico: `DatabaseCandidati` (schema SQLite WAL), manager escrow/pagamenti/audit/dashboard/report. |
| `fase13_protocollo_finale.py` | `Config`, `SecurityManager` (HMAC + nonce), `RateLimiter`, `DBCircuitBreaker`, `SelfHealingManager`. |
| `fase15_idempotency.py` | **`IdempotencyManager`** (vedi sotto). |
| `app.py` | App-factory Flask, Blueprint `/api/v1`, decoratori `fortress`/`with_circuit_breaker`/`idempotent`, route escrow/payments/health/audit. |
| `gunicorn.conf.py` | Config Gunicorn + hook di lifecycle integrati col `SelfHealingManager`. |

## Avvio e test

```bash
# Test (suite core + Fase 15)
python -m unittest test_assistente_gestionale test_fase6_onboarding \
  test_fase7_brokeraggio test_fase8_feedback test_fase9_notifiche \
  test_fase10_dashboard test_fase11_report test_fase12_audit
python -m unittest test_fase15_idempotency

# Produzione
gunicorn -c gunicorn.conf.py "app:create_app()"
```

In produzione (`FLASK_ENV=production`) sono **obbligatori** `HMAC_SECRET`,
`API_KEY`, `BEARER_TOKEN` (fail-fast all'avvio se mancanti).

## Variabili d'ambiente

Riferimento completo delle variabili lette dal codice (le costanti non
configurabili come `RATE_LIMIT_IP`, `NONCE_TTL`, `CB_*` non sono incluse).

### Segreti — obbligatori in produzione

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `HMAC_SECRET` | *generato effimero* | Chiave per la firma HMAC delle richieste `fortress`. |
| `API_KEY` | *generato effimero* | Auth read-only via header `X-API-Key`. |
| `BEARER_TOKEN` | *generato effimero* | Auth read-only via `Authorization: Bearer`. |
| `ADMIN_TOKEN` | *generato effimero* | Privilegio (header `X-Admin-Token`) richiesto per **muovere fondi** (escrow release/refund). |

> ⚠️ I valori generati sono **diversi per ogni processo**: con più worker (o in
> produzione) vanno impostati esplicitamente, altrimenti le firme non combaciano
> tra worker. In `FLASK_ENV=production` l'avvio fallisce se mancano.

### Applicazione e database

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `DB_PATH` | `data/marketplace.db` | DB principale (`Config.DB_PATH`), usato anche da idempotenza/outbox. **Non** usare `/tmp` (volatile): un warning viene loggato se il path è in area temporanea. |
| `CORE_AUTO_DB` | `core_auto.db` | DB di default del manager idempotenza se istanziato senza path. |
| `FLASK_ENV` | *(vuoto)* | `production` abilita il fail-fast sui segreti e il controllo XFF privato. |
| `PORT` | `8000` | Porta (`app.run` di sviluppo). |
| `MAX_BODY_BYTES` | `1048576` | Limite dimensione body (oltre → `413`). |

### Sicurezza e reverse proxy

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `TRUSTED_PROXIES` | `127.0.0.1,::1` | Proxy fidati da cui accettare `X-Forwarded-For`. |
| `XFF_MODE` | `first` | Quale elemento dell'XFF usare (`first`/`last`). |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | IP da cui Gunicorn accetta gli header forwarded. |
| `TIMESTAMP_WINDOW` | `60` | Finestra anti-replay del timestamp (s). |

### Idempotenza (Fase 15)

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `IDEMPOTENCY_TTL_HOURS` | `24` | Validità della risposta in cache. |
| `IDEMPOTENCY_LOCK_TIMEOUT_MIN` | `5` | Soglia oltre cui un lock è "morto". |
| `IDEMPOTENCY_ACQUIRE_RETRIES` | `3` | Tentativi su `SQLITE_BUSY` in `acquire()`. |
| `IDEMPOTENCY_ACQUIRE_BACKOFF` | `0.05` | Base (s) del backoff lineare. |
| `IDEMPOTENCY_MAINTENANCE_INTERVAL` | `300` | Intervallo (s) della manutenzione runtime. |

### Gunicorn e runtime (`gunicorn.conf.py`)

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `BIND` | `0.0.0.0:8000` | Indirizzo di bind (o `PORT` se impostata). |
| `WEB_CONCURRENCY` | `cpu*2+1` | Numero di worker. |
| `WORKER_CLASS` | `sync` | Tipo di worker (`gthread` con `THREADS`). |
| `THREADS` | `4` | Thread per worker (solo con `gthread`, commentato). |
| `TIMEOUT` | `30` | Timeout worker (s). |
| `GRACEFUL_TIMEOUT` | `60` | Drain dei worker allo shutdown (s). |
| `KEEPALIVE` | `5` | Keep-alive connessioni (s). |
| `MAX_REQUESTS` | `1000` | Richieste per worker prima del riciclo. |
| `MAX_REQUESTS_JITTER` | `100` | Jitter sul riciclo worker. |
| `LOGLEVEL` | `info` | Livello di log. |
| `MASTER_MEM_WARNING_MB` | `400` | Soglia RSS master per il warning. |
| `WORKER_FAILURE_THRESHOLD` | `5` | Worker falliti prima dell'alert. |
| `GUNICORN_USER` / `GUNICORN_GROUP` | *(commentati)* | Utente/gruppo di esecuzione. |
| `SSL_CERTFILE` / `SSL_KEYFILE` | *(commentati)* | TLS diretto (di norma terminato dal proxy). |

### Watchdog, alerting e feature flag

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | *(vuoto)* | Alert del `SelfHealingManager` via Telegram. |
| `WEBHOOK_URL` | *(vuoto)* | Alert via webhook generico. |
| `AUDIT_ENABLED` | `true` | Abilita il logging d'audit. |
| `DEEPSEEK_INDEXING` | `true` | Abilita l'indicizzazione DeepSeek. |
| `OUTBOX_DLQ_ALERT_THRESHOLD` | `10` | Soglia profondità DLQ oltre cui scatta l'alert. |
| `OUTBOX_DLQ_ALERT_INTERVAL_S` | `3600` | Intervallo (s) di throttling dell'alert DLQ. |

### Email e ricerca esterna (`assistente_gestionale.py`)

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `GMAIL_USER` / `GMAIL_APP_PASSWORD` | *(vuoto)* | Invio email via Gmail. |
| `GMAIL_SMTP_HOST` / `GMAIL_SMTP_PORT` | `smtp.gmail.com` / `465` | Host/porta SMTP Gmail. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` | *(vuoto)* | SMTP generico. |
| `SMTP_FROM` / `NOTIFICA_EMAIL` | *(vuoto)* | Mittente / destinatario delle notifiche. |
| `BRAVE_API_KEY` | *(vuoto)* | Motore di ricerca Brave. |
| `SERPAPI_KEY` | *(vuoto)* | Motore di ricerca SerpAPI. |

---

# Sicurezza — Audit Red Team

È stato eseguito un audit di sicurezza in stile Red Team con remediation
suddivisa per severità in tre gruppi, tutti implementati, testati e committati.
Dopo ogni gruppo la suite core (89 test) è rimasta verde.

## Gruppo 1 — CRITICAL (`3961c48`)

| ID | Vulnerabilità | Remediation |
|----|---------------|-------------|
| **C1** | Nonce anti-replay in memoria per-processo → replay tra worker Gunicorn | Nonce store su SQLite condiviso (tabella `nonce_usati`), inserimento atomico sulla PK cross-worker |
| **C2** | Bypass del rate-limit tramite spoofing di `X-Forwarded-For` | `forwarded_allow_ips="127.0.0.1"`; `_client_ip()` si fida dell'XFF solo da proxy fidati (`TRUSTED_PROXIES`, `XFF_MODE`) |
| **C3** | Memory-leak del `RateLimiter` (crescita illimitata per IP) | `OrderedDict` + pruning lazy + tetto massimo voci (100000) |

## Gruppo 2 — HIGH (`b38acc7`)

| ID | Vulnerabilità | Remediation |
|----|---------------|-------------|
| **H1** | Il circuit breaker contava *qualsiasi* eccezione come guasto DB → DoS del breaker | Apre solo su errori DB infrastrutturali (`busy`/`locked`/`timeout`); errori client → 400, infra → 503, altro → 500 |
| **H2** | Firma HMAC per concatenazione senza delimitatori (collisioni) + query string non firmata | Canonicalizzazione con **length-prefix** (`_canonical_string`) e firma su `full_path` |
| **H3** | Nessun limite sul body → DoS | `MAX_CONTENT_LENGTH` (1 MiB, env `MAX_BODY_BYTES`) + handler `413` |
| **H4** | SQLite poco resiliente sotto concorrenza | `_apri()` con `busy_timeout`, WAL, `synchronous=NORMAL`, `foreign_keys=ON`, `wal_autocheckpoint` |
| **K1** | Confronto firma non timing-safe | Confermato uso di `hmac.compare_digest` |
| **K2** | Possibile race nelle transizioni escrow | Confermate atomiche: `UPDATE ... WHERE id=? AND stato=?` (rowcount), nessun read-then-update |

## Gruppo 3 — MEDIUM (`70743b8`)

| ID | Vulnerabilità | Remediation |
|----|---------------|-------------|
| **M1** | `worker_abort` non raggiungeva il monitor → alert di timeout mai inviati | Monitor globale di modulo (`_MONITOR`) accessibile dal worker |
| **M2** | Finestra timestamp anti-replay troppo larga (±5 min) | `Config.TIMESTAMP_WINDOW` ridotta a **60 s** |
| **M3** | `/health/system` anonimo → information disclosure | Protetta con `@fortress_readonly`; `/health` resta pubblica e minimale |
| **M4** | Nessun fail-fast sui segreti mancanti in produzione | `create_app()` solleva `RuntimeError` se `FLASK_ENV=production` e mancano `HMAC_SECRET`/`API_KEY`/`BEARER_TOKEN` |
| **K3** | Log injection via header non fidati | `_sanitize_log()` neutralizza CR/LF e tronca a 200 caratteri (applicato all'User-Agent) |
| **K4** | Header di sicurezza assenti | `after_request`: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Cache-Control: no-store` |
| **K5** | Drain dei worker troppo breve | `graceful_timeout` portato a 60 s |

## Hardening incrementale (Fasi 18–22)

| Fase | Intervento | Beneficio |
|------|-----------|-----------|
| **18** | `@require_admin` su release/refund (`X-Admin-Token`) + replay idempotente che preserva `Location` + header `Referrer-Policy`/`Permissions-Policy`/CSP/HSTS | Separazione dei privilegi sui fondi; correttezza API; superficie d'attacco ridotta |
| **19** | Correlation-ID per richiesta (da `X-Request-ID` sanitizzato o generato) nei log e in `X-Correlation-ID` | Tracciabilità end-to-end |
| **20** | Chiusura SSRF DNS-rebinding: validazione dell'IP **reale del peer al connect** sui webhook | Niente bypass via rebinding tra check e fetch |
| **21** | `Idempotency-Key` stabile in uscita sui webhook (`outbox-<id>`, costante sui retry) | Consegne at-least-once deduplicabili dai partner |
| **22** | Dispatch Outbox **concorrente** (`OUTBOX_CONCURRENCY`, default 4) con thread pool | Niente head-of-line blocking: gli handler lenti non bloccano gli altri |

---

# Fase 15 — Idempotency Manager (exactly-once)

Garantisce che un'operazione mutante (creazione escrow, sblocco, rimborso,
pagamento split) venga eseguita **una sola volta** anche in caso di retry del
client, doppio invio o crash a metà richiesta, tramite una **Idempotency-Key**
fornita dal client e un locking pessimistico su SQLite.

## Uso lato client

Inviare l'header `Idempotency-Key` (oltre agli header di autenticazione
`fortress`) sulle route mutanti. Ritentare la **stessa** richiesta con la
**stessa** key restituisce la risposta originale senza rieseguire l'operazione.

```http
POST /api/v1/payments/split
Idempotency-Key: 9f1c...          # scelta dal client, univoca per operazione
X-Request-ID:  ...                # header fortress (HMAC)
X-Timestamp:   ...
X-Nonce:       ...
X-Body-Hash:   ...
X-Signature:   ...
Content-Type:  application/json

{"prenotazione_id": 1, "importo_totale": 10000, "commissione_tavola": 1000, "quota_partner": 9000}
```

> **Importi in centesimi interi (Fase 17).** Tutti gli importi monetari viaggiano
> come **centesimi interi** (es. `10000` = €100,00); i **float sono rifiutati con
> `400`**. Deve valere l'invariante `commissione_tavola + quota_partner ==
> importo_totale`, altrimenti `400`. Internamente non si usa mai la virgola
> mobile per il denaro (storage `INTEGER`, presentazione via `Decimal`). Nota:
> i prezzi dei listing scrapati e il preventivo commerciale restano informativi
> e fuori da questo contratto.

### Route protette da `@idempotent`

| Route | Metodo | Privilegio |
|-------|--------|-----------|
| `/api/v1/escrow/create` | POST | autenticato (`fortress`) |
| `/api/v1/escrow/<id>/release` | POST | **admin** (`X-Admin-Token`) — Fase 18 |
| `/api/v1/escrow/<id>/refund` | POST | **admin** (`X-Admin-Token`) — Fase 18 |
| `/api/v1/payments/split` | POST | autenticato (`fortress`) |

> L'header `Idempotency-Key` è **opzionale**: se assente, la route procede
> normalmente (nessuna idempotenza). Le route `GET` non sono interessate.
>
> **Separazione dei privilegi (Fase 18):** le operazioni che *muovono denaro*
> (`release`/`refund`) richiedono, oltre all'autenticazione `fortress`, l'header
> `X-Admin-Token` valido (confronto timing-safe); altrimenti **403**. Un
> credenziale partner/cliente può creare escrow/pagamenti ma **non** rilasciare
> o rimborsare fondi.

### Esiti e risposte HTTP

| Situazione | HTTP | Note |
|-----------|------|------|
| Prima richiesta | esito normale della route | risposta memorizzata (se status `< 500`) |
| Retry identico (key + body uguali) | risposta originale | header **`Idempotent-Replay: true`** |
| Richiesta ancora in corso (altro worker) | **409** `request_in_progress` | + `Retry-After` |
| Stessa key, **body diverso** | **422** `idempotency_key_reused` | difesa anti-abuso (fingerprint) |
| Errore server `5xx` o eccezione | l'errore stesso | il lock viene **rilasciato** → retry possibile |

## Architettura

`acquire()` è un **wrapper difensivo** che ritenta `_acquire_once()` solo sui
`SQLITE_BUSY`/`locked` transitori (backoff lineare); la logica vera è in
`_acquire_once()`, eseguita in un'unica transazione **`BEGIN IMMEDIATE`** (un
solo writer in WAL → sequenza leggi-decidi-scrivi atomica). Quattro esiti:

- **`ACQUISITO`** → il chiamante ha il lock (riceve un `token`): esegue e poi `store()`.
- **`IN_CORSO`** → un altro worker sta eseguendo (lock fresco) → 409 + Retry-After.
- **`IN_CACHE`** → risposta già pronta e non scaduta → replay.
- **`CONFLITTO`** → stessa key con fingerprint del body diverso → 422.

Garanzie chiave:
- **Niente doppia esecuzione**: lo "steal" di un lock scaduto e le ri-acquisizioni
  usano `UPDATE` condizionali (compare-and-swap su `rowcount`).
- **`store()`/`release()` scoped per token**: un worker il cui lock è stato rubato
  per timeout non può sovrascrivere la risposta del worker subentrato.
- **TTL applicato in lettura**: una cache scaduta viene ri-acquisita, mai
  restituita stale.
- **Fingerprint** SHA-256 incrementale (no materializzazione del body),
  confronto timing-safe.

### Tabella `idempotency_keys`

Creata automaticamente da `_init_schema()` (PRAGMA allineati al resto del
progetto: WAL, `busy_timeout`, `synchronous=NORMAL`, `foreign_keys=ON`), con
indice parziale sui lock e indice su `expires_at`.

| Colonna | Descrizione |
|---------|-------------|
| `idempotency_key` (PK) | la key del client |
| `request_fingerprint` | hash di `method + full_path + body` |
| `locked_by`, `locked_at` | token e istante del lock attivo (NULL = libero) |
| `expires_at` | scadenza TTL della voce |
| `response_status`, `response_body`, `response_headers` | risposta memorizzata |
| `correlation_id`, `created_at` | tracciamento |

## Manutenzione (su 3 livelli)

1. **Per-richiesta**: retry su `SQLITE_BUSY` + recupero dei lock morti scaduti
   durante `acquire()`.
2. **Runtime**: `SelfHealingManager._monitor_loop` richiama periodicamente
   `sweep()` (lock morti) + `purge_expired()` (cache scadute), in modo throttled.
3. **Boot/Shutdown**: gli hook Gunicorn `on_starting` (recupero stato orfano da
   un crash precedente) e `on_exit` (housekeeping) eseguono la stessa manutenzione.

> Nota di sicurezza: alla morte di un worker **non** vengono liberati i suoi lock
> per-PID. Un'operazione potrebbe aver già prodotto effetti sul DB prima del
> crash; liberare subito il lock causerebbe doppia esecuzione. Si usa solo lo
> `sweep()` time-based (margine `IDEMPOTENCY_LOCK_TIMEOUT_MIN`).

## Configurazione (variabili d'ambiente)

Vedi la sezione [Idempotenza (Fase 15)](#idempotenza-fase-15) nel riferimento
completo delle variabili d'ambiente (`IDEMPOTENCY_*`, `DB_PATH`, `CORE_AUTO_DB`).

## API del manager (per integrazioni)

```python
mgr = IdempotencyManager(db_path)            # singleton thread-safe
fp  = mgr.fingerprint(method, full_path, body)
res = mgr.acquire(key, fp, correlation_id)   # -> RisultatoIdempotenza
# res.esito in EsitoAcquisizione; se ACQUISITO -> res.token
mgr.store(key, res.token, status, body, headers)   # salva + rilascia (token-scoped)
mgr.release(key, res.token)                  # rilascio senza salvare
mgr.sweep()                                  # libera i lock morti
mgr.purge_expired()                          # elimina le cache scadute
```

## Test

`python -m unittest test_fase15_idempotency` — 21 test: manager (acquisizione,
conflitto, replay, token-scoping, **concorrenza 20 thread → exactly-once**,
sweep, TTL, purge, retry) e integrazione end-to-end con `fortress` (HMAC reale)
su `/payments/split` (replay 400, conflitto 422, 401 senza header).
