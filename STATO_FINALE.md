# STATO FINALE — Dove siamo e cosa manca per FINIRE BookinVIP

> Punto di ripristino. Se si interrompe, riparti da qui. Aggiornato: 2026-06-23.
> Suite: **1449 test**, zero regressioni (baseline errori=48 = live PG/Playwright).
> **Tutti gli item di CODICE [ME]/[AGENTE] sono CHIUSI.** Resta solo il "DA FARE TU" (chiavi/deploy).

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

## 🔑 DA FARE TU (gated, fuori dal codice)
- `.env.casavip` sul server: `STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET`, `SMTP_*`,
  `META_PAGE_ID`/`META_PAGE_TOKEN`(+IG), `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`.
- **Rigenera il token Facebook** (quello incollato in chat è compromesso).
- DNS bookinvip.com -> VPS + `docker compose -f docker-compose.casavip.yml up -d` + HTTPS.

## Regole codice (per tutti gli agenti)
Python 3.9, `unittest` (no pytest), ZERO dipendenze terze (solo stdlib), docstring italiano +
identificatori inglese, denaro in CENTESIMI interi, moduli isolati `faseNN_*.py` + test dedicato,
gated da env, `fetch` iniettabile (test senza rete), blindato (mai solleva), NON committare (commit
li fa l'orchestratore), NON toccare file condivisi (fase81/fase83/roadmap), eseguire SOLO il proprio test.
