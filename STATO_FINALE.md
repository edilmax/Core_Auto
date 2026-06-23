# STATO FINALE — Dove siamo e cosa manca per FINIRE BookinVIP

> Punto di ripristino. Se si interrompe, riparti da qui. Aggiornato: 2026-06-23.
> Suite: **1635 test**, zero regressioni (baseline errori=48 = live PG/Playwright).
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
