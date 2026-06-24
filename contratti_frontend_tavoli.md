> 🔄 Aggiornato 2026-06-24 · **BookinVIP** · suite **1740 test** (0 regressioni) · moduli `faseNN`→151 · infra VPS Aruba 89.46.65.6 ATTIVO · fonte di verità: **STATO_FINALE.md**

# Contratti JSON — Frontend ↔ Backend Tavoli VIP (Fase 56)

Riferimento: `fase56_gateway_tavoli.py`. **Regola tassativa:** ogni importo viaggia in
**centesimi interi** (`*_cents: int`). Float, bool e stringhe numeriche (`"1000"`,
`"10.50"`) sono **rifiutate**. I tassi viaggiano in **basis-point interi** (`*_bps`).
`valuta` è solo un'etichetta. Auth via header `X-Client-Key` (cliente enterprise).

---

## 1. POST `/tavoli/prenota` — crea prenotazione tavolo

### Header
```
X-Client-Key: KEY-AAA
Content-Type: application/json
```

### Richiesta (UI → backend)
```json
{
  "chiave_conversione": "ORD-2026-0001",
  "tavolo_id": "VIP-12",
  "check_in": "2026-07-01",
  "check_out": "2026-07-03",
  "email": "ospite@example.com",
  "prezzo_guest_cents": 20000,
  "incasso_mango_cents": 600,
  "ospite_nome": "Mario Rossi",
  "ospite_telefono": "+39 333 1234567"
}
```

Campi:

| Campo | Tipo | Obbligatorio | Note |
|---|---|---|---|
| `chiave_conversione` | string | sì | chiave idempotenza (namespacata per locale lato server) |
| `tavolo_id` | string | sì | id del tavolo/risorsa VIP |
| `check_in` / `check_out` | string `YYYY-MM-DD` | sì | `check_in < check_out` |
| `email` | string | sì | deve contenere `@` |
| `prezzo_guest_cents` | int | sì | centesimi interi, `> 0`, `<= 100000000` |
| `incasso_mango_cents` | int | sì | centesimi interi, `>= 0`, `<= prezzo_guest_cents` |
| `ospite_nome` | string | no | default `""` |
| `ospite_telefono` | string | no | default `""` |

### Risposta — 201 Created (agganciata)
```json
{
  "stato": "agganciata",
  "locale": "Club Alfa",
  "tavolo_id": "VIP-12",
  "prezzo_guest_cents": 20000,
  "incasso_mango_cents": 600,
  "valuta": "EUR",
  "idempotente": false,
  "prenotazione_id": 7,
  "pagamento_id": 1007,
  "payment_url": "https://pay.core/1007"
}
```

### Risposta — replay idempotente (stesso `chiave_conversione`)
```json
{
  "stato": "agganciata",
  "locale": "Club Alfa",
  "tavolo_id": "VIP-12",
  "prezzo_guest_cents": 20000,
  "incasso_mango_cents": 600,
  "valuta": "EUR",
  "idempotente": true,
  "prenotazione_id": 7,
  "pagamento_id": 1007,
  "payment_url": "https://pay.core/1007"
}
```

### Risposte di errore

| HTTP | Corpo | Causa |
|---|---|---|
| 400 | `{"errore":"invalid_payload","dettaglio":"denaro_non_intero:prezzo_guest_cents"}` | contratto non valido (vedi codici §3) |
| 401 | `{"errore":"unauthorized"}` | `X-Client-Key` assente/errata |
| 409 | `{"stato":"non_disponibile","errore":"non_disponibile", ...}` | tavolo non disponibile sulle date |
| 422 | `{"stato":"importi_non_validi","errore":"importi_non_validi", ...}` | importi/date rifiutati dal money-path |
| 429 | `{"errore":"quota_superata"}` | quota token globale esaurita |
| 503 | `{"errore":"service_disabled"}` | sistema in default-off |
| 503 | `{"errore":"service_paused"}` | health-guard ha messo in pausa il funnel |

Esempio 400 (denaro float mascherato — **rifiutato**):
```json
// richiesta NON valida
{ "...": "...", "prezzo_guest_cents": 200.0 }
// risposta
{ "errore": "invalid_payload", "dettaglio": "denaro_non_intero:prezzo_guest_cents" }
```

Esempio 409:
```json
{
  "stato": "non_disponibile",
  "locale": "Club Alfa",
  "tavolo_id": "VIP-12",
  "prezzo_guest_cents": 20000,
  "incasso_mango_cents": 600,
  "valuta": "EUR",
  "idempotente": false,
  "errore": "non_disponibile"
}
```

---

## 2. GET `/tavoli/metriche` — osservabilità funnel

### Header
```
X-Client-Key: KEY-AAA
```

### Risposta — 200 OK
```json
{
  "cicli_totali": 1280,
  "cicli_ok": 1240,
  "conversioni_tentate": 900,
  "conversioni_riuscite": 612,
  "conversion_rate_bps": 6800,
  "circuito": "chiuso"
}
```

Note:
- `conversion_rate_bps` = tasso in **basis-point interi** (6800 = 68,00%). Zero float.
- `circuito` ∈ `{"chiuso","aperto","semiaperto"}` (stato health-guard).

### Errori
| HTTP | Corpo |
|---|---|
| 401 | `{"errore":"unauthorized"}` |
| 503 | `{"errore":"service_unavailable"}` |

---

## 3. Codici `dettaglio` di validazione (HTTP 400)

```
payload_non_oggetto
campo_mancante:<campo>
campo_non_stringa:<campo>
campo_vuoto:<campo>
campo_troppo_lungo:<campo>
email_non_valida
data_non_valida:check_in | data_non_valida:check_out
date_incoerenti
denaro_non_intero:<campo>      // float, stringa o bool al posto di int
denaro_negativo:<campo>
denaro_oltre_tetto:<campo>     // > 100000000 cents
incasso_oltre_prezzo
prezzo_nullo
```

---

## 4. Regole per l'Architetto Frontend

1. Inviare il denaro **solo come intero in centesimi**. Es. €200,00 → `20000`. Mai
   `200.0`, mai `"200.00"`, mai `"20000"`.
2. `incasso_mango_cents <= prezzo_guest_cents` sempre.
3. Riusare lo **stesso `chiave_conversione`** per retry della stessa prenotazione →
   risposta `idempotente: true`, nessuna doppia prenotazione.
4. `payment_url` è il link di pagamento da aprire/redirigere alla conferma.
5. Trattare 429/503 come **ritentabili** (backoff); 400/422 come **errori di input**
   (non ritentare senza correggere il payload).
