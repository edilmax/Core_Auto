# STATO FINALE — Dove siamo e cosa manca per FINIRE BookinVIP

> Punto di ripristino. Se si interrompe, riparti da qui. Aggiornato: 2026-06-24.
> Suite: **1740 test superati** con successo, zero regressioni (baseline errori=48 = live
> PG/Playwright). Include lo scudo fiscale reverse-charge (fase103), i gateway QR asiatici
> Alipay/WeChat (fase104) e il modulo Alloggiati Web Questura (fase151).
> Manutenzione 2026-06-24: spazzatura rimossa (~1.2GB artefatti esperimenti), email ufficiale
> unica = **info@bookinvip.com**, doc allineati (vedi REPORT_COMPLETO.md). 110 moduli fase 13→151.
> **CODICE CHIUSO + DEPLOY HTTPS PRONTO + ACQUISIZIONE + ARCHITETTURA FINANZIARIA.** Resta
> solo il "DA FARE TU": VPS + DNS + chiavi .env + numeri fiscali col commercialista + deploy.

## ✅ ACQUISIZIONE (fase96-97)
- fase96 lead discovery MONDIALE da dati aperti OpenStreetMap/Overpass (gratis, no proxy,
  innesto in outreach compliant 89/95); fase97 inbound SEO/AEO (landing /affitta/<città> +
  FAQ JSON-LD + /llms.txt + /sitemap-host.xml, 5 lingue, XSS-safe).

## ✅ ARCHITETTURA FINANZIARIA (fase98-102 — piano M1-M6/R1-R3 completo)
- fase98 policy commissione: primi-1000-host (fase88 +numero_host/conta_host) + split
  asimmetrico 3%host/12%ospite=15% + fattura_startup_cents (tutela forfettario).
- fase99 multi-currency like-for-like ledger: Denaro tipizzato per valuta (no mix),
  conversione trasparente anti-DCC (markup esplicito), ProviderTassi OXR gated.
- fase100 DAC7 gate (gated EU default-off, 28pren/1800€ → sospendi+blocca payout, durevole).
- fase101 Stripe Connect split-all'origine (destination charge: 85% al conto host,
  application_fee = nostra 15%) — gated.
- fase102 motore autonomo vendi+incassa (orchestra concierge59+inventario58+pagamento101+
  split65, duck-typed, isolato).
- concierge host-aware (fase59 commissione_alloggio cablata in fase81); 15% BLINDATO nei
  default (fase81/69).
- fase103 reverse-charge M5 (autofattura TD17/TD18 + IVA configurabile + scadenza F24 +
  registro durevole, gated).
- fase104 gateway Asia (Alipay/WeChat Pay sullo split 15% Stripe Connect + canale Weibo, gated).
- fase105 W3C identity gate (Verifiable Credential firmate HMAC per annunci host + recensioni
  guest, anti-truffa, gratis).
- fase106 dynamic pricing (occupazione/domanda + stagionalità + weekend + last-minute/anticipo,
  bps interi, floor/cap, puro).
- fase107 i18n auto-traduzione annunci (default pass-through fase61 + backend LibreTranslate
  gratuito iniettabile + cache, isolato).
- fase109 referral host-porta-host (codice firmato + bonus crediti non-cashabili a scaglioni,
  anti-frode, durevole).
- fase111 cancellazione flessibile + rimborso automatico (scaglioni giorni→bps, fee pulizia
  sempre resa, puro cents).
- fase113 messaggistica host-guest in-app (thread per prenotazione, solo partecipanti,
  mascheramento PII, SQLite durevole).
- fase115 dashboard host metriche avanzate (revenue/occupazione/ADR/RevPAR/lead-time/
  cancellazione/rating, puro cents-bps).
- fase117 wishlist/preferiti guest (liste nominate per slug, idempotente, SQLite durevole).
- fase119 calendario prezzi visuale host (griglia stato + prezzo base + prezzo dinamico
  fase106, provider iniettato, HTML XSS-safe).
- fase121 mappa interattiva + geo-ricerca (microgradi interi, bbox+haversine+cluster+GeoJSON,
  puro).
- fase123 notifiche web push guest (subscription durevoli SQLite + invio VAPID gated,
  fetch/firma iniettabili).
- fase125 confronto OTA risparmio guest (prezzo finale ospite OTA markup+fee+DCC vs noi,
  puro cents/bps).
- fase127 check-in digitale guest (pre-registrazione ospiti+documenti validati, sblocco
  smart-pass fase64 solo se completato, SQLite durevole).
- fase129 traduzione recensioni multilingua (riusa fase107 pass-through+LibreTranslate gated
  + rileva-lingua euristica + conserva originale).
- fase131 host payout dashboard (tracciamento incassi per valuta, stati maturato→in_transito→
  pagato/trattenuto, SQLite durevole).
- fase133 split-payment gruppo a quote uguali (largest-remainder conservazione esatta +
  pagamenti/completamento durevoli).
- fase135 iCal sync bidirezionale (export feed .ics DTEND-esclusivo RFC5545 + import fase82,
  roundtrip, puro).
- fase137 programma fedeltà guest (punti per soggiorno + livelli bronze/silver/gold/platinum
  + riscatto sconto, idempotente, SQLite durevole).
- fase139 chatbot AI assistenza guest pre-prenotazione (router intento deterministico, prezzo
  SEMPRE dal concierge mai dall'IA, LLM opzionale solo fallback).
- fase141 host onboarding wizard guidato (macchina a stati passi+validazione+gate pubblicazione
  fail-closed, % completamento, SQLite durevole).
- fase143 verifica identità host KYC (handoff provider esterno, no PII sui ns server,
  transizioni validate, gate payout, SQLite durevole).
- fase145 contratto locazione PDF precompilato (PDF 1.4 stdlib zero-dipendenze, xref corretti,
  IT/EN, cents interi, deterministico).
- fase147 tassa soggiorno comunale automatica (registro regole per-comune + calcolo + ledger
  riscossioni rendicontazione, comune-ignoto→0, SQLite durevole).
- fase149 deposito cauzionale pre-autorizzazione (hold no-addebito, cattura danno≤autorizzato
  + rilascio resto, conservazione esatta, PSP capture/release gated, SQLite durevole).
- fase151 export Alloggiati Web Questura (file larghezza-fissa 168char IT-gated, schedine
  ospiti, capo-con-documento, ASCII uppercase, deterministico).

## ✅ FATTO (prodotto funzionante)
- Prodotto BookinVIP (alloggi): vetrina(57), inventario realtime(58), concierge prezzo-firmato(59),
  MCP(60), i18n 5 lingue(61), recensioni verificate(63), smart-pass/self check-in(64),
  trasparenza vs OTA(69), iCal(82), server(83), sentinel(80).
- Money-path: Stripe link(85) + webhook(87) + email voucher(86) — GATED da env.
- Host self-service: registrazione/login/token(88) + viral loop referral(76) + pagina /diventa-host.
- **Commissione 15% LIVE** (env COMMISSIONE_BPS=1500) + auto -5% sui colossi (fase89).
- 14 motori geniali CABLATI nel sistema; endpoint live: tassa(/api/tassa) + split-payment(/api/split/*).
- Outreach compliance-first(89): FonteAPIUfficiale gated + gate giurisdizioni + email Prima Emilia.
- Marketing 360(90): post multilingua + immagini SVG + calendario; canali(91) Telegram+Meta;
  endpoint POST /api/marketing/campagna + bottone "Pubblica campagna" nel pannello admin.

## ✅ DEPLOY — STACK PRONTO (codice/infra fatti)
- **Docker**: `Dockerfile.casavip` (python:3.11-slim, ZERO dipendenze=pura stdlib, non-root
  uid 10001, healthcheck urllib). TUTTI i dati durevoli su volume `/data`: catalogo,
  inventario, registro_host, viral, campagna_stato, **outreach_optout** (fix redeploy-loss,
  commit 44d6167). Verificato LIVE: entrypoint avvia, composizione completa, /api/health→200.
- **HTTPS PRONTO** (commit 53c0fd7): `docker-compose.casavip.ssl.yml` (app+nginx-443+
  **certbot auto-renew 12h**+backup) + `deploy/nginx.casavip.ssl.conf` (80→443, ACME, HSTS,
  rate-limit, WAF-lite) + `deploy/init-letsencrypt.sh` (bootstrap 1-comando, risolve
  uovo-e-gallina, STAGING per test). `.gitattributes` forza LF (no 'bad interpreter ^M').
  Compose SOLO-HTTP `docker-compose.casavip.yml` resta per test locali.

## ✅ DA FINIRE (codice) — TUTTO CHIUSO
1. [x] Pannello admin AUTOMATICO: chiave in localStorage, auto-load all'apertura + ogni 60s,
   bottone "🔄 Aggiorna" (host.html già auto-load via token). → commit d29f86f.
2. [x] Adapter **X/Twitter** (fase92, OAuth1 stdlib, gated) + 5 test. → commit a317dad.
3. [x] Adapter **TikTok** (fase93, video-first, gated) + 5 test. → commit a317dad.
4. [x] **Pulizia**: 94 file `ricombinato_*` + super_ai_creator/linker rimossi. → commit a317dad.
5. [x] **Docs** (COSA_FA, GUIDA_USO) con commissione 15%, tassa/split API, marketing, canali,
   outreach, admin automatico. → commit d29f86f.
6. [x] Wiring fase92/93 in `crea_canali_da_env` + bump roadmap test. → a317dad/d29f86f.
7. [x] **Scheduler** auto-pubblicazione campagna ogni N giorni (fase94, gated
   CAMPAGNA_AUTO_GIORNI, stato-file atomico no-burst) + 10 test. → commit d29f86f.
8. [x] Outreach: invio email reale (adatta_invio_email→fase86) + opt-out DUREVOLE
   (fase95, file atomico) + endpoint pubblico **/stop** + 10 test. → commit a4ea73e.

## 📌 GO-TO-MARKET — REALTÀ 2026 (critica Kimi integrata)
L'importazione host avviene via **iCal sincronizzato standard (fase82/135, bidirezionale)**,
NON via API chiuse di Booking/Airbnb (host inventory API invite-only/inesistenti). È l'unico
canale reale, legale e universale: l'host incolla il link iCal e le date si bloccano cross-canale.
Sicurezza deploy: app blindata dietro nginx su rete docker **isolated** (nessuna porta su host)
+ **autoheal** reale (riavvio container unhealthy).

## 🟢 INFRASTRUTTURA — COMPLETATA
- **VPS Aruba O2A4** (4GB RAM, Docker) **ATTIVO** — IP **89.46.65.6**.
- **DNS**: record **A** su Hostinger **agganciato** (TTL 14400).
- **.env.casavip** compilato (P.IVA, IBAN, chiavi Stripe Live) — git-ignored, segreti NON nel repo.
  ⚠️ ruotare la Stripe secret key (esposta in chat) + correggere prefisso doppio `pk_live_pk_live`/`sk_live_sk_live`.
- **PROSSIMO PASSO ASSOLUTO (al rientro):** caricare la cartella sul server via **SSH** e
  **lanciare il container Docker** (`./deploy/init-letsencrypt.sh` poi
  `docker compose -f docker-compose.casavip.ssl.yml up -d --build`).

## 🏛️ QUADRO DEFINITIVO BookinVIP
> Numeri fiscali/societari = da confermare col commercialista; qui registrati come quadro di lancio.

- **P.IVA 11795700969** in periodo di prova → **locazione occasionale, max 4 case**; se
  funziona, sblocco **ATECO 62.01.00** (software) **/ 79.90.19** (servizi turistici).
- **Stripe Connect Destination Charge (fase101)** con **`on_behalf_of`** per pagamenti
  esteri/asiatici **multivaluta in centesimi (fase99)** — 85% al conto host, application_fee
  = nostro 15%; valuta dell'annuncio, niente conversione forzata (anti-DCC).
- **Gate mercati a 150 listings** con **isteresi 0.85** (anti-flapping accensione/spegnimento).
- **Watchdog iCal 24h** (fase82/135, sync cross-canale) + **geo-rebalance attivo** (fase121).

### ✉️ Email Killer (Loss Aversion) + PDF in lingua (fase89)
**Oggetto:** "Stai regalando il 25% a Booking — riprenditelo (Prima Emilia)"
**Corpo:**
"Ciao {nome}, ogni prenotazione dei TUOI clienti (repeat, Instagram, passaparola) su Booking
ti costa fino al 25%: su {fatturato} sono **€{perdita}/anno** che regali. Con BookinVIP paghi
**15%**, hai sito di prenotazione + pagamento + voucher + check-in automatico, e tieni i tuoi
clienti. Nessuna esclusiva: sincronizzi il calendario iCal e li gestisci ovunque. Entri nella
classe fondatrice **Prima Emilia** (15% bloccato a vita). In allegato il PDF con il calcolo
nella tua lingua. Rispondi a questa email. — BookinVIP · Per non ricevere più: {optout}"
(Localizzata 5 lingue via fase89; PDF allegato generato da codice, calcolo perdita in cents.)

### 🎬 Script video "I traumi del 2026" (host)
1) HOOK <2s: "Hai perso €4.200 quest'anno. E non te ne sei accorto." 2) TRAUMA: overbooking,
recensione ingiusta, commissione 25%, reception alle 2 di notte. 3) SVOLTA: "C'è chi affitta
le stesse case e ne tiene il 10% in più." 4) PROVA: schermata calcolo +€/notte, voucher,
self check-in. 5) CTA unica: "BookinVIP — riprenditi i tuoi clienti." Formato 9:16, 15–30s,
sottotitoli burned-in, taglio 1.5–2.5s, loop-friendly.

## ⚙️ PARAMETRI DI LANCIO (config + contenuti)
> Nota onesta: i flag sotto sono **proposti/da cablare** (il runtime NON li legge ancora);
> qui registrati come parametri definitivi del lancio. Lo "stack psicologico" e i parametri
> video sono **linee-guida di contenuto**, non config consumata dal codice.

**.env.casavip (parametri di lancio):**
```
GATED_MARKETS_THRESHOLD=150      # soglia mercati gated (host attivi per accendere un mercato)
GATED_MARKETS_HYSTERESIS=0.85    # isteresi anti-flapping accensione/spegnimento mercato
ICAL_WATCHDOG_ENABLED=true       # watchdog sync iCal (fase82/135) cross-canale
GEO_REBALANCE_ENABLED=true       # ribilanciamento geo dei lead/offerta (fase121)
```

**Email killer — stack psicologico (Loss Aversion):** leva primaria = la PERDITA già in
corso, non il guadagno. Sequenza: 1) quantifica la perdita ("stai regalando il 25% a Booking
= €X/anno sui TUOI clienti"); 2) ancora al concreto già posseduto (repeat/Instagram/passaparola);
3) reversibilità a costo zero ("la riprendi gratis, niente esclusiva, iCal sincronizzato");
4) urgenza non-finta (classe fondatrice Prima Emilia, 15% bloccato); 5) opt-out sovrano.

**Parametri montaggio video 2026:** vertical 9:16, hook < 2s, durata 15–30s, sottotitoli
burned-in, taglio ogni 1.5–2.5s, 1 sola CTA finale, audio-trend con testo on-screen
indipendente dall'audio, safe-margins 14%, loop-friendly.

## 🔑 DA FARE TU (gated, fuori dal codice — l'unica cosa rimasta)
1. **VPS + DNS**: record A di `bookinvip.com` E `www.bookinvip.com` → IP del VPS; porte 80/443 aperte.
2. **Segreti** in `.env.casavip` (da `.env.casavip.example`): `CASAVIP_SEGRETO` (genera con
   `python -c "import secrets;print(secrets.token_hex(32))"`), `HOST_KEY`, `ADMIN_KEY`,
   `BASE_URL=https://bookinvip.com`; gated: `STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET`, `SMTP_*`,
   `META_PAGE_ID`/`META_PAGE_TOKEN`(+IG), `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`, opz. `X_*`/`TIKTOK_*`.
3. **Rigenera il token Facebook** (quello incollato in chat è compromesso — revocalo prima di usarlo).
4. **Go-live HTTPS** (un comando, vedi DEPLOY_CASAVIP.md §4):
   `chmod +x deploy/init-letsencrypt.sh && ./deploy/init-letsencrypt.sh`
   poi `docker compose -f docker-compose.casavip.ssl.yml up -d --build`.
   (Suggerito: prima `STAGING=1` per provare, poi `STAGING=0` per il cert vero.)
5. **Go-to-market**: primi host (il software è pronto; il valore ora è acquisizione, non codice).

## Regole codice (per tutti gli agenti)
Python 3.9, `unittest` (no pytest), ZERO dipendenze terze (solo stdlib), docstring italiano +
identificatori inglese, denaro in CENTESIMI interi, moduli isolati `faseNN_*.py` + test dedicato,
gated da env, `fetch` iniettabile (test senza rete), blindato (mai solleva), NON committare (commit
li fa l'orchestratore), NON toccare file condivisi (fase81/fase83/roadmap), eseguire SOLO il proprio test.
