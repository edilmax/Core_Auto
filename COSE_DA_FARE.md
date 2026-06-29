# ✅ COSE DA FARE — BookinVIP (così non dimentico)

> Aggiornato 2026-06-29 · suite 1851 test (0 errori) · stato reale: `STATO_FINALE.md`. Spunta man mano.

## 🔴 1. DA FARE TU (non è codice — serve per andare ONLINE)
- [ ] **VPS**: `cd /var/www/bookinvip && git pull && systemctl restart bookinvip` (ogni volta che aggiorniamo).
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
- [ ] **`confronto_guest` (fase125)** in vetrina → "risparmi €X vs Booking" (più conversioni). ⭐ consigliato primo.
- [ ] **payout dashboard (fase131)** nel pannello host (incassi/payout per valuta).
- [ ] **alloggiati_web (fase151)** — invio schedine Questura (obbligo host IT).
- [ ] **tassa_comunale (fase147)** nel checkout.
- [ ] **deposito_cauzionale (fase149)**.
- [ ] **contratto_pdf (fase145)** scaricabile.
- [ ] **checkin_digitale (fase127)** (pre-registrazione ospiti + documenti).
- [ ] **KYC host (fase143)** + onboarding wizard (fase141).
- [ ] calendario_prezzi (119), geo_ricerca (121), wishlist (117), fedeltà (137), chatbot (139), web_push (123), traduzione annunci/recensioni (107/129), dashboard metriche (115), split a quote uguali (133).

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
0% ospite · commissione 5%/15% per-fonte · cancellazione modello Booking + Anti-Rimpianto · **escrow di garanzia** (auto-rilascio schedulato) · avvisi host email/WhatsApp/LINE/WeChat · Credito Fondatore (cold-start) · outreach legale 27 paesi (DB giurisdizioni) · cancella-tutto+verifica (oblio) · home con logo · fix lingua (sw.js rete-prima) · 1851 test verdi.
