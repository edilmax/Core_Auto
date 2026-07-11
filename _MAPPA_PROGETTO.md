# 🗺️ MAPPA DEL PROGETTO — cosa è vero, cosa è vecchio (2026-07-11)

> Creato per fare ordine SENZA perdere nulla. Qui c'è scritto cosa è ogni file.
> **Nessuna password è scritta qui** (solo i nomi delle variabili e dove stanno i valori veri).

## ✅ PULIZIA FATTA il 2026-07-11 (nulla perso)
- I 2 file segreti confusi sul Desktop sono stati **rinominati in backup chiari** (finiscono in `.bak`, quindi restano privati, NON su GitHub):
  - `.env` → **`_SEGRETI_vecchio-stack_ex-env.txt.bak`** (contiene i segreti del vecchio impianto: token Telegram, password Gmail, chiavi Booking/Stripe vecchie)
  - `.env.casavip` → **`_SEGRETI_casavip_copia-locale.txt.bak`** (P.IVA, IBAN, Stripe LIVE — già tutti sul server)
- 13 file `.md` doppioni/vecchi spostati in **`_archivio/`** (recuperabili quando vuoi).
- ⚠️ **NON rimossi** `docker-compose.yml`, `.env.example`, `requirements.txt`, `deploy/nginx.conf`: sono legati alla **CI automatica** (`.github/workflows/ci.yml`) e a un prodotto gemello **TavolaVIP** ancora vivo → rimuoverli romperebbe test/CI. Lavoro separato, da fare con calma.
- Suite test: **verde** dopo la pulizia.

---

## 1. FILE ENV (configurazione + segreti) — LA COSA PIÙ DELICATA

Ci sono **due famiglie** mescolate. Solo UNA è quella che gira sul sito.

### 🟢 VERA — quella che fa funzionare il sito (BookinVIP)
| File | Dove | Cos'è |
|---|---|---|
| **`.env.casavip`** (SUL SERVER, `/var/www/bookinvip/.env.casavip`) | Server Hostinger | ⭐ **QUESTO è quello che gira davvero.** Contiene: CASAVIP_SEGRETO, ADMIN_KEY, HOST_KEY, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, SMTP_*, PAGAMENTO_BPS. **Modificare QUI per cambiare la produzione.** |
| `.env.casavip.example` | Desktop (nel repo git) | Modello/template con tutti i nomi delle variabili possibili. Nessun segreto vero. Si tiene. |
| `docker-compose.casavip.yml` | Desktop + server | Il file che avvia il sito. Usa `.env.casavip`. Si tiene. |

### 🟡 REFERENCE — dati aziendali del founder (Desktop `.env.casavip`, 12 righe)
**⚠️ NON è quello che gira (quello vero è sul server), MA contiene DATI UNICI da non perdere:**
- `PARTITA_IVA_STARTUP` → la tua P.IVA (valore reale presente)
- `STARTUP_PAYOUT_IBAN` → il tuo IBAN per gli incassi (valore reale presente)
- `REGIME_FISCALE`, `EMAIL_MITTENTE`, `LETSENCRYPT_EMAIL`
- `STRIPE_LIVE_PUBLIC_KEY`, `STRIPE_LIVE_SECRET_KEY` (chiavi Stripe LIVE)
- `X_ENABLED`, `ALIPAY_WECHAT_CONNECT_SPLIT`
→ ✅ **VERIFICATO 2026-07-11: questi dati (P.IVA, IBAN, Stripe LIVE) sono GIÀ TUTTI sul server**
  (produzione = superset). Quindi il file locale è **ridondante**: cancellarlo NON perde nulla.
  Suggerimento comunque: annota P.IVA e IBAN anche in un posto tuo (foglio/note) per comodità.

### 🔴 VECCHIA — impianto generico "Core_Auto" (NON usato dal sito)
| File | Cos'è | Contiene segreti reali? |
|---|---|---|
| `.env` (Desktop, 30 righe) | Vecchia config dell'impianto generico Postgres/Flask + agente social "Mango" | ⚠️ **SÌ**: GMAIL_USER + GMAIL_APP_PASSWORD, SMTP_*, STRIPE_API_KEY, BOOKING_API_KEY/ADMIN_KEY, **TELEGRAM_BOT_TOKEN**, EMAIL_* |
| `.env.example` | Modello del vecchio impianto (POSTGRES_*, FLASK_ENV, ANTHROPIC_API_KEY, WHATSAPP_*, ADMIN_PANEL_*) | No (solo template) |
| `docker-compose.yml` | Vecchio stack Postgres/Flask, MAI deployato | — |

**Nota:** il vecchio `.env` ha un **token Telegram** e una **password Gmail** reali. Prima di cancellarlo, decidi se il social "Mango"/Telegram serve ancora (vedi sez. 3).

---

## 2. FILE .md (documenti) — 24 nel progetto, tanti doppioni

### 🟢 ATTUALI — recenti, da tenere
- `CLAUDE.md` — istruzioni operative per l'assistente (NON toccare)
- `STRATEGIA_VINCENTE.md`, `STRATEGIA_CRESCITA.md`, `STRATEGIA_CANCELLAZIONE.md`,
  `STRATEGIA_PAGA_IN_STRUTTURA.md`, `STRATEGIA_TASSE_CAMBIO.md` — strategie 2026-07 (aggiornate di recente)
- `RIPRENDI_QUI.md` — stato attuale (aggiornato 2026-07-10)
- `legale/PRIVACY_POLICY.md`, `legale/TERMINI_SERVIZIO.md` — **servite sul sito** (non toccare)

### 🟡 DOPPIONI / vecchi — candidati a essere archiviati (dal 2026-06-30, superati)
- **Guide deploy (3 doppioni):** `DEPLOY.md` (vecchio stack), `DEPLOY_CASAVIP.md`, `GUIDA_DEPLOY.md`
  → la procedura vera è già nella memoria dell'assistente + funzionante
- **Stato/report (doppioni):** `REPORT_COMPLETO.md`, `STATO_FINALE.md`, `COSE_DA_FARE.md`, `LISTA_GO_LIVE.md`
- **Manuali grandi (vecchi):** `MANUALE_MACCHINA_TOTALE.md`, `LIBRO_OPERATIVO_TOTALE.md`, `MASTERPLAN.md`, `ARCHITETTURA.md`, `README.md`, `COSA_FA_BOOKINVIP.md`, `GUIDA_USO.md`
- **Vecchie strategie/roadmap:** `STRATEGIA_FINANZIARIA.md`, `STRATEGIA_MARKETING.md`, `ROADMAP_MANGO.md`

> ⚠️ Prima di cancellare i .md: controllare se dentro c'è qualche numero/decisione unica non
> presente altrove. Meglio SPOSTARLI in una cartella `_archivio/` che cancellarli.

---

## 3. TELEGRAM + SOCIAL — cosa sono nel progetto
Nel codice c'è un sistema di **marketing automatico** (moduli fase90/91) che può pubblicare su
**Telegram, X/Twitter, TikTok, Instagram/Facebook (Meta), WeChat/Weibo**. È il vecchio "Mango".
- **Stato:** è codice REALE ma **OPZIONALE e SPENTO** (parte solo se metti i token nell'env di produzione, che oggi NON ci sono → non fa nulla).
- **Decisione:** se vuoi il marketing automatico social, si accende impostando i token. Altrimenti
  i riferimenti Telegram/social negli env si possono ignorare/togliere senza rompere il sito.

---

## 4. REGOLA D'ORO per non sbagliare
- **Per cambiare il sito** → si modifica SOLO `.env.casavip` **sul server** (Hostinger), poi si ricrea il container.
- I file env **sul Desktop** sono copie/promemoria: **NON influenzano il sito** (il sito usa quello sul server).
- Nessun file `.env` con segreti è su GitHub (solo i `.example`): ✅ verificato, i segreti non sono pubblici.
