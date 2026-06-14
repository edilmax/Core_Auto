# CORE_AUTO

Marketplace finanziario (escrow + split payment) con API REST Flask, hardening di
sicurezza (audit Red Team) e garanzie di **idempotenza exactly-once** sulle
operazioni mutanti.

> Convenzioni: identificatori in inglese, commenti/log/documentazione in italiano.
> Runtime: **Python 3.9**. Test con `unittest` (pytest non installato).

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

{"prenotazione_id": 1, "importo_totale": 100, "commissione_tavola": 10, "quota_partner": 90}
```

### Route protette da `@idempotent`

| Route | Metodo |
|-------|--------|
| `/api/v1/escrow/create` | POST |
| `/api/v1/escrow/<id>/release` | POST |
| `/api/v1/escrow/<id>/refund` | POST |
| `/api/v1/payments/split` | POST |

> L'header è **opzionale**: se assente, la route procede normalmente (nessuna
> idempotenza). Le route `GET` non sono interessate.

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

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `DB_PATH` | `/tmp/marketplace.db` | DB usato da app e idempotenza (`Config.DB_PATH`). |
| `CORE_AUTO_DB` | `core_auto.db` | DB di default del manager se istanziato senza path. |
| `IDEMPOTENCY_TTL_HOURS` | `24` | validità della risposta in cache. |
| `IDEMPOTENCY_LOCK_TIMEOUT_MIN` | `5` | soglia oltre cui un lock è "morto". |
| `IDEMPOTENCY_ACQUIRE_RETRIES` | `3` | tentativi su `SQLITE_BUSY` in `acquire()`. |
| `IDEMPOTENCY_ACQUIRE_BACKOFF` | `0.05` | base (s) del backoff lineare. |
| `IDEMPOTENCY_MAINTENANCE_INTERVAL` | `300` | intervallo (s) della manutenzione runtime. |

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
