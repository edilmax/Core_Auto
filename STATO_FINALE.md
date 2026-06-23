# STATO FINALE — Dove siamo e cosa manca per FINIRE BookinVIP

> Punto di ripristino. Se si interrompe, riparti da qui. Aggiornato: 2026-06-23.
> Suite: ~1419 test, zero regressioni (baseline errori=48 = live PG/Playwright).

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

## 🔧 DA FINIRE (codice)
1. [ME] Pannelli AUTOMATICI: admin/host auto-load (niente click "Carica"); chiave salvata + auto-refresh.
2. [AGENTE] Adapter **X/Twitter** (fase92, gated, pattern fase91) + test.
3. [AGENTE] Adapter **TikTok** (fase93, gated, pattern fase91) + test.
4. [AGENTE] **Pulizia** ~150 file `ricombinato_*.py` + super_ai_creator/linker (spazzatura).
5. [AGENTE] **Docs** aggiornati (COSA_FA, GUIDA_USO) con commissione 15%, marketing, canali, outreach.
6. [ME] Wiring nuovi adapter in `crea_canali_da_env` (fase91) + bump roadmap test.
7. [ME] **Scheduler** auto-pubblicazione campagna ogni N giorni.
8. [ME] Outreach: invio email reale (fase86) + opt-out DUREVOLE + endpoint admin.

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
