# ✅ COSE DA FARE — BookinVIP (così non dimentico)

> Aggiornato 2026-06-29 · suite 1875 test (0 errori) · stato reale: `STATO_FINALE.md`. Spunta man mano.

## ✅ CHIUSI ORA (buchi logici di integrità)
- [x] **Hold prima del pagamento** (`fase162`): con Stripe il book va `in_attesa_pagamento`, il
  webhook conferma (`pagato`), e uno **sweeper libera le stanze non pagate** entro 20 min. Niente
  più prenotazioni fantasma che bloccano la stanza. (Senza Stripe resta confermata subito.)
- [x] **Ledger tassa** (`fase147` cablato): al pagamento confermato la tassa incassata è registrata
  per comune (rendicontazione alla città). `totale_riscosso(comune)`.

## 🔴 1. DA FARE TU (non è codice — serve per andare ONLINE)
- [ ] **VPS Hostinger (Docker)**: `cd /opt/bookinvip && git pull && docker compose -f docker-compose.casavip.yml up -d --build` (ogni volta che aggiorniamo da GitHub). Reload solo-nginx: `docker compose -f docker-compose.casavip.yml exec nginx nginx -s reload`.
- [ ] **`.env.casavip` sul server** (mai su Git):
  - [ ] `STRIPE_SECRET_KEY` LIVE — **RUOTARE** la chiave esposta in chat (era compromessa, prefisso doppiato).
  - [ ] `STRIPE_WEBHOOK_SECRET`, `STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL`.
  - [ ] `SMTP_HOST/PORT/USER/PASSWORD` + `EMAIL_MITTENTE=info@bookinvip.com` (email host + voucher).
  - [ ] `BASE_URL=https://bookinvip.com`.
  - [ ] (Asia/avvisi) `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID` (opzionali).
- [ ] **DNS + HTTPS**: record A su bookinvip.com → IP VPS; Let's Encrypt (vedi `DEPLOY.md`).
- [ ] **Sicurezza**: cambiare password VPS (era compromessa); revocare/rigenerare token Facebook esposto.
- [ ] **Commercialista**: confermare P.IVA/regime forfettario, ATECO, coefficiente, soglia €85k.

## 🟠 2. DA CABLARE (codice già pronto + testato, manca solo l'aggancio alla UI/endpoint)
Pattern: endpoint `fase83` + handler + pannello + test.
- [x] ~~**`confronto_guest` (fase125)** in vetrina~~ ✅ FATTO: il preventivo mostra "Su un OTA pagheresti
  ~€X · risparmi €Y" (badge verde). Server `_concierge_quote` arricchisce la quote (isolato/fail-safe),
  base = soggiorno pulito, DCC se valuta ospite diversa. Test nel quote.
- [x] ~~**payout dashboard (fase131)**~~ ✅ FATTO: card "💰 I tuoi incassi" nel pannello host
  (`GET /api/host/payout`), riepilogo per valuta/stato (maturato/in-transito/pagato/trattenuto).
  Il book registra il `netto_host` come 'maturato'; la cancellazione lo porta a 'trattenuto'.
  Cablato in `fase81` (`db_payout`). Payout vero gated (Stripe Connect). Test 2.
- [ ] **alloggiati_web (fase151)** — invio schedine Questura (obbligo host IT).
- [x] ~~tassa di soggiorno nel checkout~~ ✅ FATTO: l'host dichiara la regola della sua città
  sull'annuncio, il preventivo la calcola PRECISA e la mostra separata + totale PRIMA dell'acquisto
  (default 0 = mai inventare). Resta `fase147` (ledger riscossioni/rendicontazione) da cablare.
- [ ] **deposito_cauzionale (fase149)**.
- [x] ~~**contratto_pdf (fase145)** scaricabile~~ ✅ FATTO: `POST /api/contratto` decodifica il
  voucher FIRMATO (prezzo/date non manomettibili) → PDF stdlib (IT/EN) in base64; bottone
  "📑 Contratto PDF" alla conferma prenotazione. Test 2.
- [ ] **checkin_digitale (fase127)** (pre-registrazione ospiti + documenti).
- [ ] **KYC host (fase143)** + onboarding wizard (fase141).
- [x] ~~geo_ricerca (121)~~ ✅ FATTO: **"Vicino a me"** in vetrina — il cliente condivide la
  posizione (browser) → il CORE calcola bbox + distanza haversine reale (`fase121`), filtra al
  raggio e ordina per vicinanza (card con "a X km"). Coord fuori Terra → ricerca normale. Test 4.
- [x] ~~split a quote uguali (133)~~ ✅ FATTO ("Dividi tra amici" nel preventivo).
- [ ] **Richiedono prima una scelta/infrastruttura (non semplice cablaggio):** dashboard metriche (115,
  serve uno store prenotazioni-per-host) · wishlist (117)/fedeltà (137)/web_push (123) (serve identità
  guest / subscription) · traduzione annunci-recensioni (107/129, no-op senza backend LibreTranslate;
  per filosofia la fa l'agente del guest) · chatbot (139, LLM gated) · calendario_prezzi (119, valutare
  sovrapposizione con inventario fase58) · deposito_cauzionale (149, cattura gated PSP + campo su fase57).

## 🟡 3. STRATEGIA TRUST da completare (abbiamo i pezzi)
- [ ] **Migrazione 1-clic dai colossi** in onboarding (iCal `fase82/135` reso prominente).
- [ ] **Policy conflitto overbooking** multi-piattaforma (prima-prenotazione-vince + rimborso + Credito Viaggio + ricollocamento + punteggio affidabilità host).
- [ ] **Gate documenti**: annuncio non prenotabile / payout bloccato finché i documenti non sono verificati (`fase143/79/151`).

## 🟢 4. MARKETING / PRODOTTO (vedi `STRATEGIA_MARKETING.md`)
- [ ] **5 primi host a mano** (rete/zona) — il passo che sblocca tutto.
- [ ] Tradurre hero/home in 5 lingue (ora IT; i18n ospite parziale).
- [ ] Foto reale nell'hero (ora grafica vettoriale).
- [ ] Attivare canali social @bookinvip + primo contenuto.
- [ ] Lanciare outreach: `python outreach_runner.py --paese US --limit 50` (anteprima) → `--invia`.

## ✔️ GIÀ FATTO (per memoria)
0% ospite · commissione 5%/15% per-fonte · cancellazione modello Booking + Anti-Rimpianto · **escrow di garanzia** (auto-rilascio schedulato) · avvisi host email/WhatsApp/LINE/WeChat · Credito Fondatore (cold-start) · outreach legale 27 paesi (DB giurisdizioni) · cancella-tutto+verifica (oblio) · home con logo · fix lingua (sw.js rete-prima) · 1875 test verdi.
