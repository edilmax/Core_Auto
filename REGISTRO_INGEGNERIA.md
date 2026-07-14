# 📒 REGISTRO D'INGEGNERIA — BookinVIP

> **REGOLA DI PROCESSO (obbligatoria, da veri ingegneri).**
> Ogni volta che si **crea o modifica** una funzione/modulo, si aggiorna QUESTO file:
> **creazione · scopo · logica · cosa usa (dipendenze/env) · STATO (acceso/spento) · come si attiva.**
> Così **non si perde nulla** e il collaudatore (Fable 5) sa cosa esiste e cosa testare.
> Niente resta "costruito e dimenticato". Se una cosa è costruita ma spenta → va scritta nella
> tabella "COSTRUITO ma SPENTO" con **come accenderla**.
>
> Aggiornato: 2026-07-14. Vedi anche le memory `bookinvip-*` (dettagli per area) e
> `_MAPPA_PROGETTO.md`. La verità di runtime è sempre il codice: verifica prima di asserire.

---

## 1) 🟢 ACCESO e LIVE in produzione (il prodotto reale, stack "CasaVIP", fase57+)
Money-path completo (prenota → hold/pagamento → escrow → payout), pannelli, marketing.

| Area | Fasi | Note |
|---|---|---|
| Catalogo/vetrina + ricerca + **mappa** | 57, 121, 166 | geocoder ON (`GEOCODING=true`) |
| Inventario realtime (anti-overbooking) | 58, 62, 67, 70 | |
| Concierge (preventivo firmato) + prezzo/commissione | 59, 43, 44, 98, 69, 125 | rampa lancio 0→8→10% |
| Pagamenti Stripe + webhook + hold pendenti | 85, 87, 162 | **Stripe LIVE (soldi veri)** |
| Escrow garanzia + **Connect (bonifici auto)** | 160, 101 | **Connect VERIFICATO ATTIVO** su Stripe live (2026-07-14). Modello: charge alla piattaforma + transfer separato all'host al rilascio 24h (solo la commissione è ricavo). Manca solo che l'host prema "Collega Stripe" |
| Payout dashboard | 131 | |
| Multi-valuta like-for-like | 99 | OXR spento (stima "≈ tua moneta" off) |
| Cancellazioni + tassa soggiorno | 111, 66, 147 | |
| Registro host + contratto firmato + erasure | 88, 163, 156 | |
| Avvisi prenotazione multi-canale + approva-da-messaggio | 152 | email+Telegram+WeChat+LINE |
| Smart-pass / self check-in + recensioni verificate | 64, 63 | |
| Import da Booking/Airbnb (GDPR) + iCal (import+**export**) | 77, 82, 135 | export .ics attivato: l'host incolla l'URL su Booking/Airbnb → anti-overbooking |
| Marketing + canali + scheduler + AI testo (Groq) | 90, 91, 94, 165, 164 | Telegram+**Facebook** LIVE; testi scritti da Groq |
| SEO inbound (224 pagine) + domanda/waitlist | 97, 158, 161 | |
| Localizzazione 8 lingue | 61 | |
| Split-payment CALCOLATORE (checkout) | 133, 65 | mostra "€X a testa"; pagamento reale-diviso NON attivo (parcheggiato) |
| **Sconti soggiorni lunghi** (settimana/mese, li offre l'host) | 57, 59 | ≥7 notti → sconto settimana; ≥28 → mese (prevale); si impila col non-rimborsabile; identità conti intatta |
| **Ordinamento "consigliati"** (i migliori in cima, come i colossi) | 83 `_punteggio_consigliato` | default se l'ospite non chiede un ordine; segnali: foto/recensioni/cancellazione gratuita/servizi; puro/deterministico; ordine esplicito recente/prezzo NON riordinato |
| **Date flessibili** (± giorni, come i colossi) | 58 `prima_finestra` + 83 | checkbox "± 3 giorni": trova la prima finestra libera di N notti in [ci-flex, co+flex]; card mostra 📅 finestra trovata |
| Filtro **Ospiti** (capacità) nella ricerca | index.html→83 (`capacita_min`) | fix: il campo "Ospiti" ora filtra davvero (prima non veniva inviato); backend già lo supportava |
| MCP server + trasparenza + digital twin + sensory + guardian + sentinel | 60, 69, 72, 74, 75, 80 | |
| Viral loop + referral + dichiarazione + no-show + sleep-guarantee + turnover | 76, 109, 79, 62, 78, 70 | |
| Contratto locazione PDF | 145 | |
| **Metriche host avanzate** | 115 | `GET /api/host/metriche_avanzate` (KPI fase115 sulle prenotazioni reali dell'host) |
| **Test sotto carico** | test_carico_concorrente | 40 ricerche simultanee + GARA 30 clienti/1 stanza → 1 solo vincitore (anti-overbooking sotto stress) |
| **❤ Preferiti (wishlist senza login)** | index.html (localStorage) | cuoricino sulle card + bottone '❤ N' che filtra; zero backend, zero attrito (i colossi li chiudono dietro account) |
| **💌 Recupero prenotazione fallita** | 83 `_email_recupero_hold` (sweeper) | hold scaduto senza pagamento → UNA email onesta 'date di nuovo libere, riprova' (transazionale, no spam) |
| **Calendario prezzi host** (base + dinamico suggerito) | 119 (+106) | `GET /api/host/calendario_prezzi`; card calendario pulsante "💶 Prezzi" (griglia giorno-per-giorno, ↑/↓ vs base) |
| **Calendario MULTI-alloggio** (vista d'insieme) | 83 `_host_calendario_tutti` | `GET /api/host/calendario_tutti`; pulsante "🏘️ Tutti gli alloggi" → griglia righe=alloggi × colonne=giorni colorati (verde/rosso/arancione/grigio): con 10 alloggi vedi subito QUALE è occupato in che data |
| **Check-in digitale** (pre-registrazione ospiti → sblocco) | 127 (+64) | COMPLETO: endpoint + FORM sulla pagina voucher (l'ospite registra gli ospiti online prima dell'arrivo); completato → ✓ verde sul voucher |

## 2) 🟡 COSTRUITO ma SPENTO — come si ACCENDE (i "buchi" che Fable ha trovato)
Codice pronto e (per lo più) testato, ma non attivo. **Priorità del fondatore in grassetto.**

| Fase | Cosa | Come si attiva | Serve |
|---|---|---|---|
| **149** | **Deposito cauzionale** (pre-autorizzazione carta, hold senza addebito) | cablare in `_finalizza_prenotazione` + Stripe pre-auth; card host per importo | "fiducia visibile", con Stripe |
| **143** | **KYC host** (verifica identità, handoff a provider, no PII sui ns server) | scegliere provider (Stripe Identity/Veriff) + chiave; mostrare badge "Host verificato ✓" | credibilità |
| 100 | DAC7 (report fiscale venditori EU) | `attivo=True` quando si superano le soglie/obblighi | conformità EU a volumi |
| 103 | Reverse-charge (adempimento IVA UE) | `attivo=True` + dati fiscali | conformità EU |
| 104 | Gateway Asia (Alipay + WeChat Pay) | credenziali PSP asiatico | mercato asiatico |
| 105 | Identity Gate (Verifiable Credentials W3C, gratis) | wiring + UI | alternativa/estensione KYC |
| 107 | Auto-traduzione ANNUNCI (gratis, come fase61) | agganciare a pubblicazione/dettaglio | annunci multilingua |
| 129 | Auto-traduzione RECENSIONI | serve endpoint di traduzione esterno (LibreTranslate/env) — senza, non produce valore | recensioni multilingua |
| 117 | Wishlist / preferiti guest | rotta + UI (serve login guest, oggi assente) | conversione |
| 123 | Web Push guest (VAPID, gratis) | generare chiavi VAPID + service worker | retention |
| 137 | Fedeltà guest (punti→sconti) | wiring + UI (serve identità guest) | fidelizzazione |
| 139 | Chatbot AI assistenza guest | agganciare a Pool AI (164/165) + UI | supporto |
| 141 | Onboarding wizard host guidato | NON prioritario: il pannello ha già la guida 3-passi live (sarebbe un doppione) | attivazione host |
| 151 | Export "Alloggiati Web" (Questura IT) | PREREQUISITO: estendere il form check-in (data nascita/sesso/comune, dati che la Questura esige) poi collegare `genera_file` | obbligo legge IT |
| 154 | DB giurisdizioni marketing | usato da outreach (95/89) quando si fa outreach | compliance |
| 92 | Canale X/Twitter | `X_*` token nel .env (a pagamento) | marketing |
| 93 | Canale TikTok | `TIKTOK_ACCESS_TOKEN` (OAuth) **+ video** | marketing video |
| 96 | Lead discovery da OpenStreetMap | usato da outreach host | acquisizione |
| 102 | Motore autonomo vendi+incassa | orchestrazione avanzata | automazione totale |
| — | **Split-payment REALE** (link per amico, all-or-nothing) | PARCHEGGIATO dal fondatore ("ci complichiamo la vita") | vedi memory handoff |
| — | **Video AI multilingua** (YouTube/Reels/TikTok) | pool 164/165 pronto; serve generazione video (ffmpeg o AI a pagamento) | marketing video |
| — | **Instagram/WhatsApp** | bloccati lato Meta (App Review / numero WhatsApp Manager) | canali |
| — | **OXR** (cambio valuta stima ospite) | `OXR_APP_ID` gratis nel .env | UX prezzo |

## 📋 PIANO "MACCHINA COMPLETA" (2026-07-14, ordine del fondatore: tutto attivo, gratis, autonomo)
**Logica di selezione:** attivo SOLO ciò che è gratis+autonomo+valore vero (no teatro). Dai colossi prendo ciò che manca e sfrutto i loro errori (spam remarketing → email onesta; preferiti dietro login → preferiti senza login).
1. ❤ **Preferiti (wishlist)** client-side su index.html — i colossi la chiudono dietro login; noi zero-attrito (localStorage), gratis, zero backend. [fase117 resta libreria per la futura versione con account]
2. 🏛️ **fase151 Alloggiati Web** (obbligo di legge IT): export file Questura per l'host — SINERGIA col check-in digitale appena completato (nomi+documenti già raccolti). Endpoint host + pulsante.
3. 💌 **Recupero prenotazione fallita** (errore dei colossi = spam; noi 1 email onesta): quando un hold di pagamento SCADE senza incasso, il cliente riceve UNA email "le date sono di nuovo libere, riprova" (transazionale, non marketing).
**ESITO (stesso giorno):** 1✅ Preferiti ❤ live (cuoricino su card + bottone '❤ N' filtro, localStorage, zero attrito); 2⛔ Alloggiati Web SKIP onesto (il check-in raccoglie nome+documento, la Questura vuole data nascita/sesso/comune → schedine vuote = teatro; riattivare quando il form check-in verrà esteso); 3✅ Recupero prenotazione fallita live (sweeper hold scaduto → `_email_recupero_hold`: UNA email transazionale col link, 'Nessun addebito', mai promemoria). Suite 2139, 0 errori.
4. ⛔ SKIP motivati: 123 web-push (richiede crypto EC non-stdlib = violerebbe zero-dipendenze), 107/129 traduzioni (serve servizio esterno), 105 VC (nessun ecosistema), 102 (ridondante con scheduler), 141 (doppione guida). Predisposizione futura: restano librerie pronte nel repo, documentate qui.

## 🛡️ PIANO BRAND-SAFETY + REDESIGN "Designer 2.0" (2026-07-14)
**Problema:** dominio bookinvip.com vs marchi "Booking.com"/"BookVIP" → rischio contestazione per CONFUSIONE. **Logica difensiva (riduzione rischio, non consulenza legale):** "booking" è termine GENERICO (USPTO v. Booking.com, 2020: protezione stretta) → ciò che conta è NON somigliare visivamente. Il nostro blu #1e3c72 era pericolosamente vicino al blu Booking (#003580).
**Mosse:** 1) Brand visibile = **"Bookin VIP"** (staccato, ≠ dominio) con VIP dominante; 2) **palette nuova verde profondo + oro** (lusso/fiducia/VIP; nessun colosso travel la usa: Booking blu, Airbnb corallo, Agoda viola-rosso, Expedia blu/giallo, TripAdvisor verde acceso ≠ nostro verde scuro elegante); 3) logo/icona wordmark UNICI (niente "B" in scatola blu); 4) micro-guide semplici in testa ai pannelli (admin+host) — "con noi ti semplifichiamo la vita". **Consiglio al fondatore (quando vuole):** registrare il marchio FIGURATIVO "Bookin VIP" a EUIPO (~850€) = protezione vera.
**ESITO:** vedi commit — palette+logo+titoli+guide applicati su index/host/admin/manifest; suite verde.

## 2-bis) ⏳ DA FARE / PROSSIMI PASSI (aggiornare a OGNI completamento)
Regola: ogni volta che si completa qualcosa, aggiornare questa lista (togliere il fatto,
aggiungere ciò che resta). Così "cosa è fatto" e "cosa manca" stanno sempre insieme.

**Prerequisiti del FONDATORE (sbloccano funzioni già pronte):**
- Stripe Connect: **niente da fare** (già attivo); serve solo che gli host premano "Collega Stripe".
- **Instagram**: App Review Meta + IG business collegato alla Pagina + `instagram_content_publish`.
- **WhatsApp**: registrare il numero 3515754072 nel WhatsApp Manager (Cloud API) → phone_id.
- **TikTok**: access token OAuth (+ i video). **X**: token a pagamento.
- **OXR_APP_ID** (gratis, openexchangerates) → accende la stima "≈ nella tua moneta" all'ospite.
- **Deposito cauzionale reale**: decidere pre-autorizzazione Stripe (SetupIntent/manual capture) → poi cablo fase149.
- **KYC "Host verificato"**: scegliere provider (Stripe Identity/Veriff) + chiave → poi cablo fase143.
- **Contratto host**: revisione legale prima di volumi seri (Stripe è LIVE, soldi veri).

**Lavori tecnici (fattibili da me, senza prerequisiti):**
- Rifiniture/fix reali a caccia di buchi (come il filtro Ospiti).
- Recupero preventivi abbandonati (utile appena c'è traffico; usa email esistente).
- Accendere funzioni gratis senza dipendenze: auto-traduzione annunci/recensioni (107/129),
  calendario prezzi host (119), web push (123, genera chiavi VAPID).
- Import (fase77): far arrivare anche l'indirizzo/coordinate precise.
- Mappa: pin trascinabile per l'host (precisione al civico anche senza digitare l'indirizzo).
- Split-payment REALE (link per amico, all-or-nothing) — PARCHEGGIATO dal fondatore.
- Video AI multilingua (pool 164/165 pronto; manca la generazione video).

## 3) 🔵 LIBRERIE / INTERNI (non "si accendono": li usano altri moduli)
17 money, 15 idempotency, 16 outbox, 23 datastore, 73 firma-agile, 133/65 split (calcolo),
164 pool-ai (usato da 165), 154 giurisdizioni (usato da 95). Non hanno un interruttore proprio.

## 4) ⚪ LEGACY — vecchio stack "Mango / Tavola VIP" (NON nel prodotto CasaVIP)
fase13, 24–56 (Tavola VIP MVP: fase34–42 prenotazioni ristorante; Mango funnel fase43–55;
cervello IA fase25–33). Superati dallo stack CasaVIP (fase57+). NON deployati, NON toccare
per il prodotto attuale; utili solo come miniera di codice. Vedi [[bookinvip-file-mappa]].

---

## 5) 📋 INVENTARIO COMPLETO (auto-generato — tutte le fasi, scopo + agganci)
`bootstrap` = importato in fase81 (composition root) · `+router` = usato in fase83 (server) ·
`—` = né bootstrap né router (libreria interna, o LEGACY, o SPENTO). NB: `—` **non** significa
sempre "morto": molti sono librerie usate da altri moduli.

| Fase | Modulo | Agganci | Scopo |
|---:|---|---|---|
| 13 | `fase13_protocollo_finale.py` | — | ╔══════════════════════════════════════════════════════════════════════════════╗ |
| 15 | `fase15_idempotency.py` | — | Idempotency Manager (Production Ready). |
| 16 | `fase16_outbox.py` | — | Outbox Publisher & Dispatcher (Production Ready). |
| 17 | `fase17_money.py` | — | Money (importi in centesimi interi, zero float). |
| 23 | `fase23_datastore.py` | — | CORE_AUTO - Fase 23 / BLOCCO 1: Datastore abstraction (seam Postgres-ready). |
| 24 | `fase24_channels.py` | — | CORE_AUTO - Fase 24 / BLOCCO 4: Tentacoli Social (Channel Adapters). |
| 25 | `fase25_brain.py` | — | CORE_AUTO - Fase 25 / BLOCCO 3: Il Cervello (Agente IA). |
| 26 | `fase26_ricerca.py` | — | CORE_AUTO - Fase 26 / BLOCCO 3.1: Motore di ricerca alloggi PROTETTO. |
| 27 | `fase27_proposte.py` | — | CORE_AUTO - Fase 27 / BLOCCO 3.2: Generatore di proposte commerciali. |
| 28 | `fase28_gateway.py` | — | CORE_AUTO - Fase 28 / BLOCCO 2: API Gateway (estensione Blueprint /api/v1). |
| 29 | `fase29_backpressure.py` | — | Backpressure & Code di Priorita' (potenziamento motore interno). |
| 30 | `fase30_llm.py` | — | CORE_AUTO - Fase 30 / BLOCCO 4: Client LLM reale (Token Budget + Compressione). |
| 31 | `fase31_conversazione.py` | — | CORE_AUTO - Fase 31 / BLOCCO 3: Cablaggio del Cervello budget-aware (multi-turno). |
| 32 | `fase32_governatore.py` | — | CORE_AUTO - Fase 32 / BLOCCO 3: Governatore globale dei token (quota/costo LLM). |
| 33 | `fase33_persistenza.py` | — | CORE_AUTO - Fase 33 / BLOCCO 3: Stato conversazionale DUREVOLE e cross-worker. |
| 34 | `fase34_prenotazioni.py` | — | CORE_AUTO / Tavola VIP MVP - Fase 34: Motore Prenotazioni (overlap + atomica). |
| 35 | `fase35_pagamenti.py` | — | CORE_AUTO / Tavola VIP MVP - Fase 35: Pagamenti (PSP reale, link + webhook). |
| 36 | `fase36_booking_api.py` | — | CORE_AUTO / Tavola VIP MVP - Fase 36: API HTTP delle prenotazioni. |
| 37 | `fase37_notifiche.py` | — | CORE_AUTO / Tavola VIP - Fase 37: Notifiche (consegna voucher post-pagamento). |
| 38 | `fase38_backup.py` | — | CORE_AUTO / Tavola VIP - Fase 38: Backup automatico del DB (snapshot + retention). |
| 39 | `fase39_whatsapp.py` | — | CORE_AUTO / Tavola VIP - Fase 39: Canale WhatsApp (Meta Cloud API). |
| 40 | `fase40_agente_booking.py` | — | CORE_AUTO / Tavola VIP - Fase 40: Agente IA reale agganciato al booking. |
| 41 | `fase41_admin_panel.py` | — | CORE_AUTO / Tavola VIP - Fase 41: Pannello Admin Web (ponte di comando operativo). |
| 42 | `fase42_observability.py` | — | CORE_AUTO / Tavola VIP - Fase 42: Observability (log JSON + metriche). |
| 43 | `fase43_commissione.py` | — | Motore commissionale del Core (prima pietra del Fractal Bridge). |
| 44 | `fase44_prezzo.py` | — | Motore del PREZZO del Core (M2, gemello di fase43). |
| 45 | `fase45_pricing.py` | — | Motore delle PROPOSTE del Core (M3) - lo split a 3 vie. |
| 46 | `fase46_esploratore.py` | — | Esploratore del Core (M4) - property intelligence + pain-score. |
| 47 | `fase47_venditore.py` | — | Venditore del Core (M5) - orchestratore di outreach. |
| 48 | `fase48_advertising.py` | — | Advertising del Core (M6) - campagne + allocazione budget. |
| 49 | `fase49_ponte_booking.py` | — | Ponte verso il Booking (M7) - l'aggancio sicuro. |
| 50 | `fase50_orchestratore.py` | — | Orchestratore Mango (capstone end-to-end). |
| 51 | `fase51_scheduler.py` | — | Scheduler/Runner del funnel Mango. |
| 52 | `fase52_persistenza_metriche.py` | — | Persistenza durevole + metriche del funnel Mango. |
| 53 | `fase53_healthguard.py` | — | Health-guard / Circuit del funnel Mango (self-governance). |
| 54 | `fase54_loop.py` | — | Loop/Daemon runner del funnel Mango (il pezzo connettivo). |
| 55 | `fase55_bootstrap.py` | — | Bootstrap / Composition-root del funnel Mango. |
| 56 | `fase56_gateway_tavoli.py` | — | Gateway Tavoli VIP - Contratti JSON + integrazione Gateway. |
| 57 | `fase57_vetrina.py` | boot+router | Vetrina / Catalogo pubblico (lo storefront che mancava). |
| 58 | `fase58_channel_manager.py` | boot | Channel Manager / Inventario host in TEMPO REALE (anti-overbooking). |
| 59 | `fase59_concierge.py` | boot+router | Protocollo Concierge AI (booking AGENT-DISCOVERABLE). |
| 60 | `fase60_mcp_server.py` | boot | MCP Server (Model Context Protocol) per l'hospitality. |
| 61 | `fase61_localizzazione.py` | +router | Localizzazione (i18n) a COSTO ZERO - la Torre di Babele polverizzata. |
| 62 | `fase62_predictive_noshow.py` | boot | Predictive No-Show + Overbooking CONTROLLATO (yield a costo zero). |
| 63 | `fase63_recensioni.py` | boot | Recensioni VERIFICATE (anti-fake) - fiducia a prova di crittografia. |
| 64 | `fase64_smartpass.py` | boot | Smart-Pass d'ingresso / self check-in (la chiave digitale). |
| 65 | `fase65_split_payment.py` | boot | Split-payment di gruppo (dividere il costo di un soggiorno). |
| 66 | `fase66_tassa_soggiorno.py` | boot | Tassa di soggiorno automatica (jurisdiction-agnostic). |
| 67 | `fase67_coda_intelligente.py` | boot | Coda Intelligente + Cancellazione Garantita (riempire i buchi). |
| 68 | `fase68_niche_profiler.py` | — | Niche Profiler (niche stacking) - servire i mercati invisibili. |
| 69 | `fase69_trasparenza.py` | +router | Trasparenza Commissionale (la matematica che converte l'host). |
| 70 | `fase70_turnover.py` | boot | Automated Turnover (coordinamento pulizie check-out -> check-in). |
| 71 | `fase71_commitment.py` | — | Commitment Engine (l'antidoto alla cancellazione-come-arma). |
| 72 | `fase72_digital_twin.py` | boot | Digital Twin dell'alloggio (telemetria + manutenzione predittiva). |
| 73 | `fase73_firma_agile.py` | — | Firma Agile (crypto-agility + anti-downgrade + firma ibrida). |
| 74 | `fase74_sensory_engine.py` | boot | Sensory Engine (Sensory Score) - un nuovo linguaggio per l'alloggio. |
| 75 | `fase75_guardian_engine.py` | boot | Guardian Engine (rilevamento pericoli + risposta automatica). |
| 76 | `fase76_viral_loop.py` | boot | Viral Loop Engine (crescita virale a costo ZERO, anti-frode). |
| 77 | `fase77_portability.py` | +router | Portability Import Engine (il "virus legale" anti-OTA). |
| 78 | `fase78_sleep_guarantee.py` | boot | Sleep-as-a-Service (garanzia di sonno money-back). |
| 79 | `fase79_dichiarazione.py` | boot | Dichiarazione Vincolante (il notaio, non la polizia). |
| 80 | `fase80_sentinel.py` | boot | Sentinel (FIM + canary + catena integrita') - difende la cartella. |
| 81 | `fase81_bootstrap_casavip.py` | — | Bootstrap Casa VIP (composition root del lodging stack). |
| 82 | `fase82_ical_sync.py` | +router | iCal Sync (la portabilita' REALE, non quella gonfiata). |
| 83 | `fase83_server.py` | — | Server HTTP (la COLLA che fa uscire la Ferrari dal garage). |
| 85 | `fase85_pagamenti_stripe.py` | boot | Provider Pagamento Stripe (l'ultimo pezzo del money-path). |
| 86 | `fase86_email.py` | boot+router | Provider Email (voucher all'ospite via SMTP). |
| 87 | `fase87_stripe_webhook.py` | +router | Webhook Stripe (l'altra meta' del money-path: conferma pagamento). |
| 88 | `fase88_registro_host.py` | boot | Registro Host self-service (l'host si iscrive e si carica DA SOLO). |
| 89 | `fase89_jurisdiction_outreach.py` | — | Jurisdiction B2B Radar & Outreach (acquisizione host, SOLO dove è lecito). |
| 90 | `fase90_marketing.py` | boot | Marketing & Growth Engine 360° (autonomo, gratis al cuore, API-ready). |
| 91 | `fase91_canali_social.py` | boot | Canali social reali (adapter di pubblicazione, gated da .env). |
| 92 | `fase92_canale_x.py` | — | Canale X/Twitter (adapter di pubblicazione, gated da .env). |
| 93 | `fase93_canale_tiktok.py` | — | Canale TikTok (adapter di pubblicazione, gated da .env). |
| 94 | `fase94_scheduler_campagna.py` | +router | Scheduler auto-pubblicazione campagna marketing. |
| 95 | `fase95_outreach_email.py` | +router | Outreach durevole — opt-out persistente + invio email reale. |
| 96 | `fase96_fonte_osm.py` | — | Lead discovery MONDIALE da DATI PUBBLICI APERTI (OpenStreetMap). |
| 97 | `fase97_inbound_seo.py` | +router | Inbound SEO/AEO — "essere la risposta" (acquisizione SENZA tetto). |
| 98 | `fase98_policy_commissione.py` | boot+router | Policy commissione (RAMPA DI LANCIO per anzianità + split asimmetrico 2%/8%). |
| 99 | `fase99_multicurrency.py` | boot | Multi-Currency Like-for-Like Ledger (Moduli 1-2 dello studio). |
| 100 | `fase100_dac7.py` | — | DAC7 gate (Modulo 6). GATED EU (attivo=False default), soglie |
| 101 | `fase101_stripe_connect.py` | boot | Stripe Connect split-all'origine (Modulo 3 - tutela forfettario). |
| 102 | `fase102_motore_autonomo.py` | — | Motore autonomo vendi+incassa (Regola 3). |
| 103 | `fase103_reverse_charge.py` | — | Adempimento reverse-charge (Modulo 5). GATED (attivo=False default), |
| 104 | `fase104_gateway_asia.py` | — | Gateway Asia (Alipay + WeChat Pay) + adattatore Weibo. |
| 105 | `fase105_identity_gate.py` | — | W3C Identity Gate (Verifiable Credentials firmate, GRATIS). |
| 106 | `fase106_dynamic_pricing.py` | +router | Dynamic pricing (motore prezzi domanda + stagionalità). |
| 107 | `fase107_traduzione_annunci.py` | — | i18n auto-traduzione annunci (GRATIS, coerente con fase61). |
| 109 | `fase109_referral_host.py` | boot | Referral host-porta-host (bonus crediti non-cashabili). |
| 111 | `fase111_cancellazione.py` | +router | Cancellazione flessibile + rimborso automatico. |
| 113 | `fase113_messaggistica.py` | boot | Messaggistica host-guest in-app (thread per prenotazione). |
| 115 | `fase115_dashboard_metriche.py` | — | Dashboard host metriche avanzate (KPI deterministici). |
| 117 | `fase117_wishlist.py` | — | Wishlist / preferiti guest. |
| 119 | `fase119_calendario_prezzi.py` | — | Calendario prezzi visuale host. |
| 121 | `fase121_geo_ricerca.py` | +router | Mappa interattiva alloggi + geo-ricerca. |
| 123 | `fase123_web_push.py` | — | Notifiche Web Push guest (Web Push API + VAPID, GATED, gratis). |
| 125 | `fase125_confronto_guest.py` | +router | Confronto OTA risparmio GUEST (prezzo finale lato ospite). |
| 127 | `fase127_checkin_digitale.py` | — | Check-in digitale guest (pre-registrazione + sblocco verificabile). |
| 129 | `fase129_traduzione_recensioni.py` | — | Traduzione recensioni guest multilingua (gratis, coerente fase61/107). |
| 131 | `fase131_payout_dashboard.py` | boot | Host payout dashboard (tracciamento incassi/payout per valuta). |
| 133 | `fase133_split_quote_uguali.py` | +router | Split-payment di gruppo a quote uguali (conservazione esatta). |
| 135 | `fase135_ical_bidirezionale.py` | — | Sincronizzazione iCal BIDIREZIONALE. |
| 137 | `fase137_fedelta_guest.py` | — | Programma fedeltà guest (punti per soggiorni → sconti). |
| 139 | `fase139_chatbot_guest.py` | — | Chatbot AI assistenza guest pre-prenotazione. |
| 141 | `fase141_onboarding_wizard.py` | — | Host onboarding wizard guidato (macchina a stati deterministica). |
| 143 | `fase143_kyc_host.py` | — | Verifica identità host KYC (handoff a provider, no PII sui ns server). |
| 145 | `fase145_contratto_pdf.py` | +router | Contratto di locazione breve PDF precompilato (zero dipendenze). |
| 147 | `fase147_tassa_comunale.py` | boot | Tassa di soggiorno comunale automatica (registro + ledger riscossioni). |
| 149 | `fase149_deposito_cauzionale.py` | — | Deposito cauzionale pre-autorizzazione (hold, no addebito). |
| 151 | `fase151_alloggiati_web.py` | — | Export "Alloggiati Web" (Questura / Polizia di Stato). |
| 152 | `fase152_notifiche_prenotazione.py` | boot+router | Fase 152 - Notifiche di prenotazione all'HOST (chiude il buco: oggi solo l'OSPITE riceve |
| 154 | `fase154_giurisdizioni_marketing.py` | — | Database GIURISDIZIONI MARKETING mondiale (compliance per nazione). |
| 156 | `fase156_erasure.py` | +router | CANCELLAZIONE TOTALE di un host/attivita' + VERIFICA "da pertutto". |
| 158 | `fase158_domanda.py` | boot+router | DOMANDA / lista d'attesa + Credito Fondatore (cold-start). |
| 160 | `fase160_escrow_garanzia.py` | boot | ESCROW DI GARANZIA (i soldi all'host solo se la struttura corrisponde). |
| 161 | `fase161_domanda_allarme.py` | +router | CORE_AUTO - Allarme domanda: quando le persone in attesa in una città superano una SOGLIA, |
| 162 | `fase162_pagamenti_pendenti.py` | boot | Pagamenti PENDENTI (hold prima del pagamento) — chiude il buco logico |
| 163 | `fase163_accettazioni.py` | boot+router | fase163 — CONTRATTO HOST + REGISTRO D'ACCETTAZIONE a prova di manomissione. |
| 164 | `fase164_pool_ai.py` | — | Pool AI a rotazione con failover ("una funziona sempre"). |
| 165 | `fase165_adattatori_esterni.py` | boot | Adattatori esterni gated (provider AI a rotazione + upload YouTube). |
| 166 | `fase166_geocoder.py` | boot | Geocoder (indirizzo/città -> coordinate) per la mappa nella ricerca. |
