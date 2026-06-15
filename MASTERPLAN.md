# CORE_AUTO — MASTERPLAN (North Star)

> Documento-bussola. Definisce **dove stiamo andando** e **come ci costruiamo**.
> Va aggiornato a ogni mattone completato.

## La visione

Un **Agente IA** che gestisce **centinaia di chat social in simultanea** —
ricerca alloggi, comprende l'intento del cliente, genera proposte commerciali
esatte e muove denaro reale tramite un core transazionale blindato.

Tre proprietà non negoziabili per ogni riga di codice:
1. **Resiliente al massimo carico** (centinaia di conversazioni concorrenti).
2. **Fail-safe / compartimenti stagni**: se un pezzo salta, il resto vive.
3. **Correttezza del denaro a prova di bomba** (zero ambiguità, zero float).

## Architettura a compartimenti stagni (5 blocchi)

```
STARTUP CHIAVI IN MANO
├── [BLOCCO 1] CORE TRANSAZIONALE & DATASTORE  (La Cassaforte)
├── [BLOCCO 2] INTERFACCIA VISIVA              (L'Abitacolo: web, mobile, API gateway)
├── [BLOCCO 3] IL CERVELLO                      (IA conversazionale: LLM, ricerca, proposte)
├── [BLOCCO 4] I TENTACOLI SOCIAL              (Adapter WhatsApp/Instagram/Telegram)
└── [BLOCCO 5] INFRASTRUTTURA & DEPLOY         (Docker, Nginx, SSL, fail-safe)
```

## Il contratto di isolamento (ogni blocco è un'isola)

Ogni blocco/mattone DEVE rispettare:
1. **Modulo proprio** (`faseNN_*.py`), zero dipendenze incrociate tra blocchi.
2. **Import lazy** dal core; il core non importa il blocco al boot.
3. **Feature-flag** (`env`): spento ⇒ comportamento attuale identico.
4. **Best-effort / fail-closed**: avvolto in `try/except`; se esplode, degrada,
   non propaga un 500. Eccezione: il layer di persistenza (Cassaforte) è
   fondazionale e può essere una dipendenza diretta.
5. **Suite di test dedicata**, verde in isolamento **+ zero regressioni**.

## Il metodo di costruzione (estremo, non negoziabile)

> **Spike isolato → test paranoico sul singolo componente → solo dopo integri.**

- Prima una *prova* piccola e usa-e-getta (`_spike_*.py`/`_verifica_*.py`) che
  dimostra il meccanismo (idealmente in modo **deterministico**, es. `Barrier`).
- Poi i test formali dedicati.
- Poi il **gate di regressione**: la suite completa deve restare verde.
- Solo allora si integra e si committa (un mattone = un commit chiaro).

## Stato attuale (aggiornato: 2026-06-15)

**Fondamenta già blindate (suite: 173 test verdi):**
- Core marketplace escrow/split, audit immutabile, dashboard/report.
- Sicurezza: HMAC fortress, nonce cross-worker, rate-limit, circuit breaker,
  audit Red Team (3 gruppi) + hardening Fasi 18–22.
- **Denaro in centesimi interi** end-to-end (zero float) — Fase 17.
- **Idempotenza exactly-once** (in entrata) + **Outbox at-least-once** (in uscita),
  dispatch **concorrente**, anti-SSRF con validazione peer al connect, correlation-id.
- Self-healing watchdog + manutenzione su 3 livelli.

### Roadmap per blocco (stato mattone per mattone)

**BLOCCO 1 — Cassaforte** *(in corso)*
- [x] 1.1 Seam `Datastore` Postgres-ready (`fase23_datastore.py`) — SQLite completo,
      Postgres skeleton (psycopg2 presente; manca server), dialetto astratto.
- [x] 1.2 Outbox adotta il Datastore (connessioni centralizzate, 29 test immobili).
- [x] 1.3 Dialetto SQL/schema portabile **sull'Outbox**: `autoincrement_pk`
      (AUTOINCREMENT→BIGSERIAL), `now_expr` (datetime('now')→now()), `sql()`
      (placeholder ?→%s), `insert_returning_id` (lastrowid→RETURNING id), tutto
      via Datastore; `DB_BACKEND` seleziona il backend. 29 test Outbox immobili +
      2 test portabilità PG hermetici.
- [x] 1.3b **idempotency (fase15)** parla il dialetto Datastore: `_conn`→
      `raw_connection`, `_acquire_once` via `ds.transaction()`+`upsert_ignore_sql`+
      `ds.execute`, schema con `now_expr`. 29 test immobili + 2 portabilità PG.
- [ ] 1.3c **core (assistente_gestionale)** — DEDICATO, da fare con **PG live**.
      Motivo (evidenza nel codice): trigger SQLite-only dell'audit immutabile
      (`trg_audit_prevent_*`) → richiedono riscrittura plpgsql NON testabile senza
      PG; ~12 connessioni ad-hoc (no factory unico) con isolation/row_factory
      diversi dal datastore; 315 `execute/connect` + 51 costrutti dialetto. Port
      "alla cieca" = rischio prod inaccettabile. Sotto-passi:
      1.3c.1 unificare le connessioni del core dietro il Datastore (con un backend
      SQLite a config compatibile col core: default-isolation, no Row);
      1.3c.2 portare schema+query dei manager finanziari al dialetto;
      1.3c.3 trigger audit immutabile in versione PG (plpgsql) — validare su PG.
- [~] 1.4 Postgres **live** + pool. Harness di validazione PRONTO: isola
      `docker-compose.postgres.yml` + `test_postgres_live.py` (round-trip dialetto
      reale: insert_returning_id/upsert/rollback) che si **auto-salta** se PG
      spento (181 sempre verdi). Manca solo: avviare docker (`./pg.ps1 up`) e
      lanciare `./pg.ps1 test`. Pool connessioni: da fare dopo la validazione.
- [ ] 1.5 Migrazione dati SQLite→Postgres + cutover a rischio zero.

**BLOCCO 4 — Tentacoli social** *(fondamenta posate)*
- [x] 4.0 `fase24_channels.py`: `ChannelAdapter` (ABC) + `ChannelRegistry`
      (routing per canale, fail-safe: ignoto/solleva → False → retry/DLQ) +
      `StubChannelAdapter` + integrazione Outbox (`collega_a_outbox`,
      `pubblica_messaggio`, topic `channel_send`, delivery-id stabile). 12 test
      (routing, fail-safe, end-to-end Outbox→canale, DLQ, concorrenza).
- [x] 4.1 `TelegramAdapter` reale (via Config.TELEGRAM_*); no-op se non configurato.
- [ ] 4.2 Adapter WhatsApp (richiede credenziali Business API) — solo l'impl. di
      `send()`; struttura/registry/Outbox già pronti.
- [ ] 4.3 Adapter Instagram (richiede credenziali Graph API) — idem.
> Gli adapter sono I/O isolati: passano per l'Outbox (retry/DLQ/idempotency in
> uscita già pronti). Se un social cade, core e resto continuano (fail-safe).

**BLOCCO 3 — Cervello IA**
- [ ] 3.0 Interfaccia `LLMProvider` (ABC) + provider stub deterministico testabile.
- [ ] 3.1 Motore intento + ricerca alloggi (riusa l'engine TavolaVIP esistente).
- [ ] 3.2 Generatore proposte (commissione già su Decimal nel preventivo).

**BLOCCO 2 — Interfaccia visiva**
- [ ] 2.0 API Gateway (estensione del Blueprint `/api/v1` + auth per-cliente).
- [ ] 2.1 Web app (React/Vue) — stack separato, richiede toolchain frontend.
- [ ] 2.2 App mobile / push notifications.

**BLOCCO 5 — Infrastruttura & deploy**
- [x] 5.0a Isola **Postgres di sviluppo** (`docker-compose.postgres.yml` + `pg.ps1`):
      servizio separato, volume dedicato persistente, up/down con un comando,
      nessun impatto sulla sandbox. Validata strutturalmente (4 test).
- [ ] 5.0b Dockerfile dell'app + compose completo (app + postgres + nginx).
- [ ] 5.1 Nginx + domini + SSL (Let's Encrypt).
- [ ] 5.2 Fail-safe orchestration (health/readiness/liveness split).

### Dipendenze esterne (da fornire per l'integrazione "live")
Server PostgreSQL · credenziali WhatsApp Business / Instagram Graph · chiave LLM
· toolchain frontend · host con Docker/Nginx. Finché assenti, costruiamo
**codice + cuciture testabili**; l'accensione live avviene quando l'ambiente c'è.

## Vincoli tecnici permanenti
- Runtime **Python 3.9** (niente `@dataclass(slots=True)`).
- Test con **`unittest`** (pytest non installato).
- Identificatori in inglese, commenti/doc in italiano.
- Denaro **sempre** in centesimi interi / Decimal — mai float.
