# 🧪 STATO COLLAUDO — sessione 2026-07-16/17/18 (Fable 5)

> 🧭 **PUNTO DI RIPARTENZA per la CHAT SUCCESSIVA (cambio account, 2026-07-18)** — Riprendi da QUI.
> **Contesto**: stiamo eseguendo i "10 sistemi ingegneristici" richiesti dal fondatore + il
> "protocollo frontend zero-difetti a compartimenti stagni". FATTI finora: ① ispettore statico 76k
> righe (0 bug) · ② bombardamento 10.000 menti (0 violazioni) · ③ mega-sim 1000×10.000 (verde) ·
> ④ guardie concorrenza · ⑤ frontend a neuroni Host+Admin (.btn-riga, 21 catch muti curati, 2
> neuroni morti) · ⑥ frontend Ospite (8 catch + fix backup fase38) · 🚦 SEMAFORO universale stati
> (3 colori identici host+ospite, fix verde-ambiguo prezzi) · 🧱 ISOLAMENTO multi-host provato a
> simulazione (0 interferenze host↔host, 10 giri + concorrente) · 🖱️ SCUDO anti-doppio-clic su
> tutti i tasti-azione delle 3 pagine + esiti ✅/❌ sempre visibili su Approva/Rifiuta (host) e
> Sospendi/Pubblica (admin) — compartimento 1 del NUOVO collaudo qualità frontend (2026-07-18,
> metodo del fondatore: UN COMPARTIMENTO ALLA VOLTA, ogni passo col suo VAI) · 🕸️ GESTIONE
> ERRORI "zero difetti" (compartimento 2, 2026-07-18): timeout 15s su OGNI chiamata delle 3
> pagine, falsi-vuoti sbarrati (guasto ≠ "non hai nulla"), frasi gentili 8 lingue, paracadute
> login/registrazione — PROVATA con harness CAOS (test_caos_rete: Node esegue il VERO JS delle
> pagine in un DOM finto e lo bombarda: latenze infinite, 500/502/503-HTML, JSON corrotti,
> array/null/stringhe ostili) · 📦 APP.JS FONTE UNICA (compartimento 3, 2026-07-18):
> `deploy/app.js` con namespace `BV.*` = escape+valute+lingua+rete+frasi+scudo in UN posto,
> pagine con alias, copie locali VIETATE da guardia; escape sigillato al 100% (galleria
> modale, badge servizi, tabella alloggi, onclick admin) e mezze-misure vietate per sempre.
> · 🧹 ⑤ PULIZIE CENSITE + ④ NIENTE PROMPT lato ospite (2026-07-18, mandato "macchina
> perfetta"): service worker allineato (disinstalla ovunque), date default VIVE
> (BV.dataISO, mai piu' fisse), capacità ||1, CSS hover admin, pagine minori con timeout,
> e PRENOTA/PREVENTIVO con campo email in pagina (prompt() bloccato nei browser in-app
> = prenotazioni perse da Instagram/FB; i confirm() di host/admin restano di proposito).
> · 🚀 **LIVELLO 7 FATTO — VIAGGIO E2E DAL VIVO: VERDE 10/10** (2026-07-18): host reale →
> pubblica → l'ospite trova/quota (conti al cent) → prenota (link Stripe LIVE nato, non
> pagato) → hold in_trattativa sul calendario → PULIZIA TOMBALE residui tutti 0
> (script riusabile: collaudo_livello7_e2e.py).
> **Tutto committato, pushato, deployato e ALLINEATO** (Desktop=GitHub=VPS). Suite verde
> (vedi ultima riga REGISTRO).
> · ⑧⑨⑩ **ULTIMI 3 SISTEMI FATTI** (2026-07-18): ⑧ benchmark carico SQLite (30 thread×30s,
> 0 lock/0 overbooking, p95 in soglia); ⑨ mutation testing money-path (4/4 mutanti uccisi;
> ha SCOVATO un buco vero: clamp rimborso escrow senza test → ora coperto); ⑩ audit
> accessibilità WCAG (aria-label sui bottoni-icona, aria-live sulle regioni di stato, close
> da tastiera). **I 10 SISTEMI INGEGNERISTICI SONO COMPLETI.**
> · ⚡ **AUDIT RESILIENZA avviato (2026-07-18)** — protocollo UN COMPARTIMENTO ALLA VOLTA col VAI:
>   ✅ **Comp.1 Performance FATTO**: vista calendario multi-alloggio era N+1 (1 conn+query
>   sui pendenti per alloggio) → `fase162.attivi_multi` batch → **20 connessioni → 1** (O(N)→O(1)),
>   zero regressione visiva (giorni in_trattativa identici). Test: test_perf_calendario_tutti.
>   ✅ **Comp.2 Security/IDOR FATTO**: approva/rifiuta richiesta era fail-OPEN sull'ownership
>   (con host_id memorizzato vuoto, chiunque decideva richieste altrui) → fix fail-CLOSED che
>   ri-deriva il proprietario dall'alloggio. Test: test_idor_richieste (rosso sul vecchio, verde
>   sul fix). Esito audit: altri 13 endpoint sensibili già gatati, unico buco era questo.
>   ✅ **Comp.3 Clean Code FATTO**: `_catalogo` (108 righe, 4 responsabilità) aveva la matematica
>   date-flessibili inline con `except: _n=0` che disattivava la feature in silenzio → estratta
>   `finestra_flessibile` pura e testabile (test_finestra_flessibile, 8 casi bordo). Comportamento
>   invariato, fallimento silenzioso eliminato. **AUDIT DI RESILIENZA COMPLETO (3/3).**
> · 🧨 **COLLAUDO FINALE punto 1 FATTO (2026-07-18, Fable 5)**: 100 prenotazioni che scadono nello
>   STESSO istante (1 alloggio × 100 unità) → 3 prove (sweep singolo; 8 spazzini concorrenti;
>   50 pagamenti-sul-filo ∥ 4 spazzini) ×10 giri = 0 falliti; stanze SEMPRE liberate exactly-once
>   (contate ri-prenotandole fisicamente), libere==100−pagate, mai 'in_attesa' per sempre.
>   NESSUN bug nel motore (test permanente: test_scadenza_massa_100). PERÒ la prima suite INTERA
>   ha svelato 🧿: 2 guardie XSS di test_slug_sicurezza erano ROSSE dal commit `125d6f7`
>   ("app.js fonte unica" 18/07 13:59, `function esc(` sostituita da `const esc = BV.esc`):
>   contraddicevano la guardia anti-duplicazione di test_app_js → i claim "suite intera verde"
>   dei 7 commit successivi erano SBAGLIATI per quei 2 test. Guardie modernizzate senza perdere
>   severità (aggancio fonte-unica in pagina + 5 entità in app.js). **Suite 2520 verde (3 skip)**.
>   Nessun rischio XSS reale in prod. Dettaglio: righe 🧨/🧿 nel REGISTRO sez.1.
> **COLLAUDO FINALE (3 punti, VAI-gated)**: ✅ punto 1 integrità scadenze di massa — FATTO ·
>   ✅ **punto 2 permessi in contemporanea — FATTO (2026-07-18)**: 3 scenari (admin-rimborsa∥
>   host-cancella ×30; sospendi∥10-prenotano; doppio-click) ×10 giri = 0 falliti, MA prima
>   **2 BUG VERI trovati e fixati**: ⚖️ "multa fantasma" (gara admin∥host o anche solo retry
>   webhook post-cancellazione-host → stato 'rimborsato' CON penale 15% registrata; fix
>   CAS-FIRST su marca_cancellata_host + marca_da_rimborsare condizionata, mai retrocedere
>   una cancellata_host) e 🔐 revoca check-in MUTA sotto gara (connessione condivisa
>   `:memory:` senza lucchetto → BEGIN-dentro-BEGIN → smart-pass vivo su cancellata; fix
>   lucchetto in fase127; prod non esposta: usa file) + 🧪 **terzo reperto dalla suite**: il
>   mutation-test (⑨) avvelenava la __pycache__ (mutante a taglia identica ripristinato nello
>   stesso secondo = bytecode mutato "valido" → 17 falsi-rossi sul percorso prezzi con sorgente
>   giusto e git pulito; fix `_butta_pyc` a ogni scrittura). Dettaglio: righe ⚖️/🔐/🧪 REGISTRO sez.1.
>   Test permanente: test_admin_host_stesso_istante (invarianti fisici: stanze ricontate,
>   tassa 0, da_pagare 0, giro-bonifici futuro paga nessuno, penale ⇔ cancellata_host) ·
>   ✅ **punto 3 input non validi — FATTO (2026-07-18)**: ~1.500 colpi con chiavi valide su
>   9 rotte di scrittura (ogni campo × ogni veleno: None/negativi/enormi/emoji/4000-char/
>   mancante/body-vuoto + date impossibili) → **1 BUG VERO fixato**: ☠️ `immagini`=None/numero/
>   bool su /api/host/pubblica = 500 (enumerate su non-iterabile; stringa = immagini-spazzatura
>   per carattere) → ora solo list/tuple. Prove fisiche: mai 5xx, quote mai ≤0, catalogo senza
>   veleni, range invertito non prenotabile, flusso sano vivo DOPO la tempesta. Test permanente:
>   test_input_invalidi_ogni_casella. **🏁 COLLAUDO FINALE 3/3 COMPLETO (0 errori residui).**
> · 🏭 **REFACTORING INDUSTRIALE "Le mie prenotazioni" (2026-07-18, direttiva "niente tamponi")**:
>   paginazione SERVER-SIDE vera (fase58 `elenco_prenotazioni_pagina`+`conta_prenotazioni`+indice
>   `ix_movimenti_blocchi`; endpoint `vista`/`page`/`limit`, taglio e COUNT dal DB) — **PERF misurata
>   su 300 prenotazioni: 161 query→5, 50.8KB→1.8KB (28×), 167.8ms→6.4ms (26×)** · UX UNIFICATA:
>   card Richieste eliminata, richieste=STATO del flusso (righe gialle in cima, Approva/Rifiuta+
>   scudo+countdown) ed ESCLUSE in SQL dalla lista (prima comparivano DOPPIE: doppione
>   pre-esistente scovato dal test) · etichetta onesta "Scaduta" in archivio · i18n MODULARE
>   (`BV.t` fonte unica + `TR._fallback` nei dati; card tradotta in TUTTE le 8 lingue).
>   Test permanenti: test_prenotazioni_paginazione (pagine esatte, mai una riga in più) +
>   test_host_prenotazioni_archivio + CAOS aggiornato. Checkpoint intermedio: `e84c633`.
>   Dettaglio: riga 🗂️ REGISTRO sez.1.
> · 🏛️ **FINANCIAL CONTROLLER Scatto ① FATTO (2026-07-18, blueprint approvato)**: fase177 =
>   LIBRO GIORNALE append-only (trigger anti-UPDATE/DELETE nel DB + catena hash che denuncia
>   manomissioni alla riga esatta + idempotenza evento_id + zero PII) · NOTE ND/NC numerate e
>   vincolate, storno mai modifica · OFFSET penale 15% dai payout maturati (stessa valuta, FIFO,
>   mai autocompensazione; residuo → debito aperto) · atomicità: 200 di cancellazione SOLO con
>   ND nel giornale; crash → riasserzione sweeper dal giornale (replay-fix beccato dal test) ·
>   gara admin∥host: zero ND spurie · env prod DB_FINANZA=/data/finanza.db (messa PRIMA del
>   deploy). test_financial_controller (11). **Scatti ②③ SPENTI, attendono VAI**: ② Debt Status
>   (blocco host a debito + auto-offset sui payout futuri) · ③ addebito carta off-session
>   (serve decisione SetupIntent + onboarding carta host). Dettaglio: riga 🏛️ REGISTRO sez.1.
> · 🏰 **BUNKER & FIELD (separazione privilegi) — 2026-07-18/19, LIVE `fe3d444`**: architettura
>   super-admin professionale. **FIELD** (`/admin`, chiave admin) = operativo, ora PAGINATO
>   (20/pagina + filtri id/host/stato server-side, audit ricerche, cieco al Bunker). **BUNKER**
>   (fase180, `/api/bunker/*`) = super-admin con 2° fattore: **TOTP RFC 6238** (telefono) o
>   **password super-admin** (`BUNKER_PASSWORD`) o break-glass; sessione firmata **15 min legata
>   all'IP**; audit CRITICO di ogni tentativo su app.log. **Password IMPOSTATE sul VPS**
>   (`.env.casavip`, mai in git): `ADMIN_KEY` (Field) + `BUNKER_PASSWORD` (Bunker). Provato dal
>   vivo: pw sbagliata→403, admin+pw giusta→200+sessione, Field 20/pagina. **Incrementi Bunker
>   RESTANO (attendono VAI)**: ③ spostare le 4 distruttive (alloggio_stato/rimborso/controversia-
>   risolvi/cancella-attivita) DIETRO la sessione Bunker; ④ sala controllo piena (log/hash/integrità).
>   Prima ancora ✅ rate-limit login LIVE (5/min per IP, 429+audit). Onestà: password = doppio muro,
>   non 2FA piena finché non si attiva il telefono (QR pronto su richiesta). Dettaglio: righe
>   🏰/🗄️/🚪 REGISTRO sez.1. ✅ i 2 test flaky sono RISOLTI 2026-07-19 — dietro c'era un bug vero, riga 🚥 REGISTRO sez.1
>   (test_ical_export era mina-data già fixata prima).
>   · ✅ **Incremento ③ ENFORCEMENT FATTO+LIVE `988e963` (2026-07-19)**: le 4 distruttive
>   (alloggio_stato/rimborso/controversia-risolvi/cancella_attivita) ora richiedono la SESSIONE
>   BUNKER (X-Bunker-Session) oltre alla chiave admin → senza: 403 `bunker_richiesto` (CRITICO+IP);
>   gate ATTIVO solo se Bunker configurato (anti-lockout). admin.html: box "Sblocca super-admin"
>   (password→sessione 15min) + bunkerHdr sulle 4 azioni. Provato LIVE: 403 senza / 422 con (slug
>   finto, 0 dati toccati). test_bunker_enforcement. **RESTA solo Incremento ④** (sala controllo
>   piena: log/hash-chain/integrità sotto /bunker) — il Bunker già mostra `GET /api/bunker/stato`
>   (diagnosi read-only). Password prod impostate in `.env.casavip`: `ADMIN_KEY` + `BUNKER_PASSWORD`.
> · ✅ **UX HARDENING + CENTRO FISCALE streaming — LIVE `49001d4` (2026-07-19)**: (a) occhiello
>   👁 mostra/nascondi su OGNI input password (app.js `BV.occhielli`, host/admin/bunker) + LOGOUT
>   ovunque (admin aggiunto) + logout SERVER-SIDE del Bunker (`Bunker.revoca` + POST /api/bunker/logout,
>   denylist nonce → token morto subito). (b) **Estratto contabile CERTIFICATO in STREAMING** (Incr.4.1,
>   d'accordo con kimi k3): `stream_giornale` generatore lazy (zero RAM) + `genera_estratto_csv` streamma
>   il CSV col hash on-the-fly + footer obbligatorio `# FINE ESTRATTO - INTEGRITÀ VERIFICATA: <hash>`
>   (o `# NON CHIUSO / CORROTTO` se rotto/interrotto) + audit `EXPORT_FISCALE_STREAM_COMPLETED`; handler
>   `do_GET` streamma sul socket; scaricabile da bunker.html (💼 Centro Fiscale). Provato LIVE (403 gated,
>   footer, audit). Nota onesta: zero-RAM è a livello app; nginx può bufferizzare file giganti (refinement:
>   `proxy_buffering off`). **PROSSIMI Centro Fiscale (servono dati fiscali — P.IVA/IBAN già in .env.casavip)**:
>   ~~DAC7~~ ✅ FATTO (riga sotto), tassa per Comune, commissioni+IVA, fatture numerate, riconciliazione Stripe.
>   Dettaglio: righe 💼/🧰/🎛️/🔐/🗄️/🏰/🚪 REGISTRO sez.1 + [[bookinvip-bunker-field]].
> · 🇪🇺 **DAC7 COMPLIANCE (Incremento 5) — FATTO `871c4eb` (2026-07-19)**: obbligo UE 2021/514
>   (segnalare al Fisco gli host ≥30 pren O ≥€2000/anno). ① host fornisce i dati fiscali
>   (`POST /api/host/dati_fiscali`, colonne+migrazione fase88); ② `fase177.aggrega_dac7(anno)`
>   dal giornale immutabile (lordo=incasso−tassa, commissioni=lordo−netto, per TRIMESTRE);
>   ③ conformità Bunker (`/api/bunker/dac7_conformita`: "urgente"=reportabile MA incompleto);
>   ④ report certificato STREAMING (`/api/bunker/dac7_report`: solo reportabili, dati fiscali+
>   Q1-4+immobili, footer `# FINE REPORT DAC7 - INTEGRITÀ: <hash>`, audit DAC7_REPORT_GENERATED,
>   gated 403, zero file su disco); riusa fase100.valuta_dac7 per la soglia. bunker.html: 2 pannelli
>   (Conformità + Genera report, anno selezionabile). test_dac7 (4). Suite 2601 verde al momento
>   del commit. PROSSIMI opzionali: blocco payout non-conformi, giorni-affitto per immobile.
> · 🚪 **GATEKEEPER SERVER-SIDE (fortezza a porta chiusa) — FATTO (2026-07-19)**: la STRUTTURA
>   di admin/bunker/host.html non viene più servita ai non autenticati (prima: 200 a chiunque =
>   ricognizione gratis; ora: **302 → `/entra-admin|host|bunker`**, form-only server-rendered,
>   noindex, no-store). VERITÀ: denaro/dati erano GIÀ protetti (API a token, invariata → niente
>   CSRF dal cookie); questo chiude l'information leakage. Cookie `bv_<ruolo>` firmato HMAC
>   stateless (livello|scadenza|nonce|firma), HttpOnly+Secure(X-Forwarded-Proto)+SameSite=Lax,
>   TTL 12h (bunker 15min); emesso dai login (nuovo `POST /api/admin/login` riusa la chiave
>   admin), cancellato dai logout (`/api/gate/logout`); dashboard servite con
>   `Cache-Control: no-store` (post-logout niente cache/back). Ponte zero-churn: le pagine
>   login salvano la credenziale dove le dashboard già la cercano. KILL-SWITCH `PAGE_GATE=0`.
>   test_gatekeeper (11, VERO server HTTP). **Suite 2612 verde (3 skip).** NB dopo il deploy:
>   tutti rifanno login UNA volta (il cookie nasce solo dal login).
> · 💰 **GOVERNANCE PAGAMENTI (Incremento 6, spec kimi) — blocco payout DAC7**: cancello
>   HARD-CODED in `_trasferisci_all_host` (unica via del transfer automatico): host REPORTABILE
>   (≥30 pren O ≥€2000, anno corrente o precedente) E dati fiscali incompleti → il bonifico NON
>   parte, **HOLD DERIVATO** (payout resta 'maturato' = visibile/mai perso; NO stato 'trattenuto'
>   che è delle controversie, NO righe giornale: nulla si è mosso) · **SBLOCCO AUTOMATICO**: al
>   `POST /api/host/dati_fiscali` completo i maturato vengono ritentati subito (payout_riprovati)
>   · host VEDE l'avviso: card "🇪🇺 Dati fiscali" NUOVA in host.html (prima l'endpoint non aveva
>   UI!) con banner rosso via `GET /api/host/dac7_stato` (quanto è fermo) · Bunker: 💰 €fermi
>   sugli urgenti in conformità · audit `PAYOUT_HOLD_TRIGGERED/RELEASED` formato kimi · FAIL-OPEN
>   (bug del controllo → si paga: denaro dovuto) · kill-switch `DAC7_BLOCCO_PAYOUT=0` ·
>   test_dac7_blocco_payout (8/8).
> · 🧭 **FIX NAVIGAZIONE POST-LOGIN BUNKER (kimi)**: "Sblocca" in admin.html ora salva la
>   sessione in sessionStorage CONDIVISO e fa redirect a /bunker.html (cookie gatekeeper appena
>   emesso → porta aperta, sala già loggata); tornando al Field le 4 distruttive restano armate
>   nei 15 min (sessione condivisa). Le distruttive NON si spostano nel bunker (Incremento ③
>   deliberato: spostarle avrebbe rotto i rimborsi). Guardie pagine 80/80 verdi.
> · 🌙 **GIORNI-AFFITTO PER IMMOBILE nel report DAC7 (chiusura requisiti UE)**: fase162
>   `notti_per_alloggio(host, anno)` — SOLO prenotazioni PAGATE, notti attribuite all'anno del
>   SOGGIORNO (cavallo d'anno DIVISO: dicembre al vecchio, gennaio al nuovo), data malformata
>   saltata; report: colonna `notti_anno` + immobili "titolo (città) - N notti/M pren", annunci
>   cancellati con notti restano dichiarati. test_dac7_notti (7). **DAC7 COMPLETO su tutti i
>   requisiti UE.**
> · 💳 **SCATTO ② DEBT STATUS + FIX OVERPAY (dal "continua" del fondatore)**: (1) i debiti
>   'aperto' ora si RISCUOTONO DA SOLI alla fonte sui payout futuri (fase177.riscuoti_debiti,
>   stesso schema evento_id di ①, FIFO, stessa valuta, giornale-prima) PRIMA di ogni bonifico;
>   nota/debito → 'saldato', log DEBT_COLLECTED; (2) **FIX OVERPAY pre-esistente scovato**: la
>   conferma ospite passava l'importo dalla garanzia → dopo un offset ① il bonifico partiva
>   PIENO (host pagato 2 volte della quota compensata) → ora UNA SOLA VERITÀ: l'importo lo
>   detta il ledger payout (row assente→0 bonifico; ridotta→residuo). Ordine choke-point:
>   anti-doppio → riscossione → riallineo → gate DAC7 → transfer. Trasparenza: host vede
>   debiti_aperti_cents in /api/host/payout, Bunker n°+totale in /integrita (pill 💳).
>   DECISIONE: niente sospensione host a debito (le prenotazioni future SONO il veicolo di
>   rimborso). test_debt_status (7) + 42 money-path riverificati. RESTANO: Scatto ③ carta
>   off-session (gated SetupIntent), storno penale Bunker-gated, Audit Console.
> · 🔎 **RICERCA OPERATIVA unificata (Incremento 7, kimi)**: barra UNICA in cima all'admin —
>   annunci (slug/titolo/città/ID, anche sospesi), host (id/email/nome), prenotazioni
>   (riferimento a prefisso / email ospite) — live+Enter+AJAX, paginata, integrata coi filtri
>   dell'Incr.2 (click→riempie e ricarica). SICUREZZA a whitelist: mai CF/P.IVA/IBAN/hash/log
>   nella risposta (test dedicato); wildcard neutralizzate; ID numerico corto ammesso; audit
>   di ogni ricerca. `GET /api/admin/search` + cerca_* nei 3 store (57/88/162).
>   test_admin_search (8). NOTA onesta al fondatore: i filtri annunci c'erano già (Incr.2);
>   il pezzo NUOVO è host-per-nome + prenotazioni + barra unica.
> · 🔬 **FINANCIAL AUDIT CONSOLE (fase181, "VAI Audit Console")**: lo Spotlight contabile —
>   nella barra admin il bottone 🔬 (o su ogni prenotazione trovata): incolli QUALSIASI id
>   (riferimento/BVIP-XXXX-XXXX/ND-NC/host) → scheda unica dei libri (162+131+160+177) con
>   SEMAFORO 4 stati (🟢 coerente · 🔴 mismatch col perché · 🟡 Stripe non verificabile ora,
>   timeout 2s · ⚪ n/a onesto, non degrada) + SHADOW-CHECK Stripe (il webhook ORA salva il
>   cs_ → prerequisito FATTO; contraddizione = rosso). READ-ONLY provato (zero righe nuove),
>   whitelist (mai corpo_json/CF/IBAN). `GET /api/admin/audit`. test_audit_console (7).
> · ↩️ **STORNO PENALE (5ª distruttiva, "VAI storno penale")**: `fase177.storna_penale` — NC
>   contraria (storno_di, evento_id fisso → idempotente), ND→'stornata', debito→'stornato'
>   (mai più riscosso, provato), riscosso RESTITUITO in da_pagare `stornoND-<ND>` (bonifico
>   MANUALE: le correzioni le firma un umano). `POST /api/admin/storno_penale` col doppio
>   cancello (admin+Bunker, motivo OBBLIGATORIO). UI: ↩️ nella card Audit sulle ND.
>   test_storno_penale (6). Con questo il Financial Controller ha TUTTO tranne Scatto ③
>   (carta off-session: attende decisione SetupIntent del fondatore).
> · 🛡️ **KYC DASHBOARD "Verifiche & Legale" (Incremento 10)**: PRIMA cosa nel pannello admin —
>   contatori ✅⚠️⛔ + ricerca dedicata + stato composito dei documenti che DAVVERO custodiamo
>   (📜 contratto fase163 con prove ts/IP/hash · 💶 fiscale DAC7 · 💳 Stripe · 🛡️ verifica manuale).
>   DECISIONE LEGALE (fonti DSA art.30): MAI carte d'identità da noi — identificazione
>   elettronica via provider soddisfa la legge; privati non-trader fuori perimetro. Azioni:
>   Dettaglio (IBAN/CF MASCHERATI), Approva/Revoca/Ripristina (Bunker, motivo obbligatorio),
>   Fascicolo legale JSON (Bunker, dati pieni). REVOCA = HOLD bonifici (stesso hold derivato
>   DAC7); RIPRISTINO = ripartono da soli. Audit ADMIN_ACTION formato kimi.
>   test_verifiche_host (5).
> · 🪪 **STRIPE IDENTITY (Incremento 11, "DOPPIA SICUREZZA")**: verifica documentale AUTOMATICA
>   ~190 Paesi, flusso HOSTED (documento telefono→Stripe, MAI da noi; da noi solo esiti fase143
>   montata nel boot). GATED da `STRIPE_IDENTITY_KEY` (segnaposto GIÀ sul VPS, vuoto: si accende
>   mettendo la chiave, zero deploy) + `DB_KYC=/data/kyc.db` già sul VPS. Host: bottone "Verifica
>   identità con Stripe"; admin: colonna 🪪; esiti via webhook firmato + sync 2s. **SOVRANITÀ**:
>   la revoca manuale ferma i bonifici anche se Stripe dice OK. test_stripe_identity (7).
>   Etichette fiscali host rese MONDIALI (CF/TIN, IVA/VAT).
> · 🪪 **STRIPE IDENTITY ACCESO IN PRODUZIONE** (fondatore ha attivato sul dashboard →
>   "ATTIVATO" → sequenza automatica): chiave=sk_live scritta, container ricreati, **E2E LIVE
>   col flusso VERO** (host usa-e-getta → URL hosted live verify.stripe.com → sessione
>   cancellata zero-costi → cancellazione tombale Bunker residui 0). Bottone 🪪 VIVO per gli host.
> · 🔄 **RICONCILIAZIONE STRIPE (Incremento 12, ultimo fantasma pre-mortem)**: fase182 —
>   sessioni PAGATE Stripe (match metadata[riferimento]) vs 'incasso' giornale al centesimo
>   + totali charge/refund/transfer vs giornale; fantasmi segnalati (solo_stripe = webhook
>   perso!, solo_giornale, importo_diverso); non-pagate filtrate; paginazione con tetto;
>   READ-ONLY provato; Bunker-gated (`GET /api/bunker/riconciliazione`) + pannello 🔄 in
>   bunker.html. fase177: somme_periodo/incassi_periodo. test_riconciliazione (8).
>   **PRE-MORTEM COMPLETO: tutti i fantasmi del 2026-07-18 chiusi** (backup offsite ✓
>   log persistenti ✓ allarmi ✓ rate-limit ✓ re-sync Stripe ✓). Restano SOLO decisioni
>   fondatore: Scatto③ SetupIntent, passphrase offsite, TOTP telefono, 2° server, token social.
> · 🚥 **SEMAFORO CHE NON MENTE (2026-07-19, mandato aperto "inizia da dove vuoi")**: dietro il
>   test "ballerino" c'era un BUG VERO — /api/voucher/prova diceva "✓ caricata" anche quando la
>   bolla in chat NON veniva scritta (DB occupato): prova INVISIBILE all'arbitro in controversia
>   + foto orfana su disco. Fix: esito verificato, file ripulito, 503 onesto, messaggi veri in
>   pagina voucher (429/5xx). Test irrobustiti: join onesto 90s (raffica), benchmark a soglie
>   doppie (strette solo a giro manuale BENCH_*/BENCH_STRICT=1; invarianti duri sempre). Guardie
>   rosse-sul-vecchio → verdi; 10 giri × 2 moduli sotto carico vero (15 bruciatori/16 core) =
>   0 falliti. Suite **2678 verde**. Dettaglio: riga 🚥 REGISTRO sez.1.
> · 🔟 **AUDIT "10 MODULI" A MASSIMA SEVERITÀ (2026-07-19, mandato "ricontrolla anche i verdi")**:
>   ispettore locale su 77 moduli vivi + ogni sospetto letto a mano. FIX VERI: ① timeout=30
>   su 29 store SQLite (il default 5s sotto contesa = False silenziosi, la classe del bug
>   prova-foto) + guardia permanente; ② CSV fiscali anti formula-injection (=+-@ → testo,
>   hash certificazione intatto); ③ email anti header-injection (a-capo nel Subject/dest.
>   respinti al choke-point); ④ voce nei silenzi money (payout/tassa/FC/check-in loggano);
>   ⑤ SCOPA uploads orfani (>7gg non citati da annunci/chat; fail-closed, paracadute 50%,
>   kill-switch PULIZIA_UPLOADS=0, 1×/24h nel tick). VERDI RI-GUADAGNATI con prove: WAL
>   ovunque, rete tutta con timeout, globali=costanti, money già a ricalcolo incrociato.
>   PROVE: suite **2690 verde** + bombardamento pieno 10×1000 RIESEGUITO = ZERO violazioni
>   (159s). Riga 🔟 REGISTRO sez.1.
> · 🔗 **RICONCILIAZIONE INTER-LIBRO (2026-07-19, mandato "cambia metodo, neuroni profondi")**:
>   metodo ORTOGONALE — un oracolo indipendente ricalcola da zero e confronta i 4 libri
>   TRA LORO (giornale/payout/escrow/tassa/pendenti/inventario), cosa che nessun test faceva.
>   Guida prenotazioni reali (quote→book→webhook + replay/rimborsi/gare paga∥cancella) in
>   5 VALUTE (EUR/USD/JPY/GBP/CHF). Invarianti: identità record, incasso==totale, idempotenza,
>   payout==netto, tassa per comune, quadratura PER VALUTA, rimborsata→payout non pieno,
>   inventario↔denaro (mai "soldi senza stanza"/overbooking), catena hash. Esito: 10 seed ×
>   200 pren × 5 valute = ZERO divergenze + guardia permanente (test_riconciliazione_interlibro).
>   +auto-riparazione crash #32 provata con fault-injection. 1 reperto = nel MIO harness
>   (endpoint cancella sbagliato mascherava il rimborso), corretto. ONESTÀ: nessun bug
>   contabile nel prodotto; il valore è la PROVA che i libri riconciliano + la guardia.
>   Riga 🔗 REGISTRO sez.1.
> · 🧮 **BUG FISCALE DAC7 FIXATO (2026-07-19, VAI del fondatore) — trovato col TEST DIFFERENZIALE**:
>   metodo nuovo = reimplemento la commissione da zero e la confronto col prodotto (fase59
>   prenotazione vs fase177 aggrega_dac7 = commissione dichiarata al Fisco). BUG: aggrega_dac7
>   leggeva il netto host solo dai bonifici COMPLETATI → host reportabile col payout in HOLD
>   (dati fiscali mancanti/verifica revocata) → netto=0 → commissioni=LORDO pieno. Dichiaravamo
>   al Fisco €5.130 invece di €780 (+558%) + reddito host sottostimato. Non lo vedeva nessun
>   metodo perché la conservazione è strutturale (riconciliazione sempre verde) e i test DAC7
>   usavano payout completati. FIX: la commissione netta (comm+costo−credito) si registra a
>   giornale al PAGAMENTO (idempotente); aggrega_dac7 fa netto=lordo−commissione (retrocompat
>   storico). Provato: ora €780 esatto, catena integra, 67 test finanziari verdi, 0 regressioni.
>   Riga 🧮 REGISTRO sez.1.
> · 👻 **CACCIA FANTASMI TERMINALE (2026-07-19, metodo deep-seek "ogni ramo fino alla fine")**:
>   ogni prenotazione guidata fino allo stato di riposo (6 rami: conferma/auto-rilascio/arbitro
>   100%/arbitro parziale/cancellazione/hold scaduto) con tutti gli orologi fatti scattare, poi
>   oracolo terminale: niente escrow in limbo, niente payout fantasma, niente doppio incasso,
>   commissione a giornale coerente, quadratura per valuta, catena integra. 8 seed × 180 pren
>   (1.440 rami, 3 valute) = ZERO fantasmi. Guardia permanente: test_fantasmi_terminali (~13s).
>   Lezione (2ª del giorno): VALIDA L'ORACOLO — 350 falsi fantasmi dal mio orologio corto.
>   Riga 👻 REGISTRO sez.1.
> · ♟️ **MODEL-CHECKING ESAUSTIVO (2026-07-19, metodo "prova non campione")**: enumerate TUTTE
>   le 14.641 permutazioni di 11 eventi a profondità 4 su mondo minimo (1 alloggio×1 unità, 2
>   prenotazioni rivali A/B) = 0 violazioni su O1..O9 (mai overbooking/soldi-senza-stanza/stato
>   illegale/resurrezione-assorbenti/doppio-incasso/catena rotta). Copertura CONFERMA l'oracolo:
>   BOTH_BOOKED=1620 (gara esercitata), BOTH_PAID=0 (impossibile). Guardia permanente:
>   test_sequenze_avverse (12 sequenze curate) + test_fantasmi_terminali.
> · 🔒 **CASSAFORTE CHIUSA (2026-07-19)**: TOTP Bunker ATTIVO+verificato dal vivo (segreto sul VPS,
>   additivo: password resta valida) + backup offsite cifrato con passphrase del fondatore.
> · 💳 **SCATTO ③ CARTA OFF-SESSION COSTRUITO ma DORMIENTE (2026-07-19, opzione 1 fondatore+kimi)**:
>   fase183 (carta hosted mode=setup + addebito PaymentIntent off_session, fetch-iniettabile) +
>   fase177.riscuoti_da_carta (addebito-prima-poi-giornale, idem, backoff) + fase88 colonne carta
>   + fase83 (webhook salva-carta, endpoint host, sweep gated) + host.html bottone. DOPPIO GATE:
>   chiave Stripe (salvataggio) + SCATTO3_ATTIVO=1 (addebito). test_scatto3_carta (11). **RESTA
>   fondatore**: mettere SCATTO3_ATTIVO=1 sul VPS + test con carta vera. Riga 💳/♟️ REGISTRO sez.1.
> · 🎨 **HERO "MOTORI" + BANDIERINE SVG (2026-07-19, homepage)**: nuovo hero verde con sfumature
>   leggere + barra dei MOTORI (Soggiorni attivo · Affitti brevi/Ville VIP/Business = "presto") +
>   selettore lingua con bandierine SVG (le emoji si vedevano come lettere su Windows). select#lang
>   nascosto+sincronizzato (logica i18n invariata). Dizionario motori × 8 lingue in fase83. Regola
>   ANTI-OTA rispettata (verde+oro, mai blu Booking). Riga 🎨 REGISTRO. **IDEA MULTI-MOTORE del
>   fondatore (DA COSTRUIRE, decisa)**: NON 5 cartelle duplicate ma UN codebase in 5 istanze
>   (5 DB + 5 sottodomini + hub centrale coi link) — motori separati (host/admin/super-admin propri)
>   con codice unico. Partenza: centro + Affitti brevi, un motore alla volta. Vedi [[bookinvip-motori-multi]].
>   RIFINITURA design (deploy 7282ee8, iterata col fondatore): motori SOTTO il verde a tab
>   SOTTOLINEATE (active verde+sottolineatura oro), titolo "Il tuo viaggio, senza sorprese" su UNA
>   riga con "senza sorprese" in oro (hero_titolo/hero_titolo2), hero riquadrato compatto,
>   sfumature leggere. Regola: iterare i visual con anteprima Artifact prima del deploy.
> · ✉️ **C3 EMAIL DI CICLO + RICEVUTA (2026-07-20, chiuso il lavoro interrotto della notte
>   "macchina completa")**: prima il cliente pagava/cancellava/contestava nel SILENZIO. Ora:
>   conferma pagamento con importo+link voucher (UNA sola anche se Stripe ri-manda il webhook,
>   provato), cancellazione col rimborso nero su bianco, esito controversia all'ospite, avviso
>   all'host quando la sua quota parte (Connect), invito a recensire post check-out (sweep
>   orario, finestra 14gg anti-spam, una volta per soggiorno; il form coi sotto-voti è già sul
>   voucher). + 🧾 RICEVUTA stampabile `/ricevuta/<token>` (token voucher firmato, SOLO pagate,
>   P.IVA reale, nota onesta "non è fattura fiscale") con bottone nel voucher solo se pagata —
>   il lavoro interrotto aveva la pagina ma NON rotta né bottone: aggiunti. Email best-effort
>   in thread: mai bloccare i soldi. test_email_ciclo (9 × 10 giri) + 134 regressione.
>   Riga C3 REGISTRO sez.1.
> · ⭐ **PAGINA DI SOLA VALUTAZIONE /recensione/ (2026-07-20, dopo prova dal vivo col fondatore)**:
>   il fondatore ha provato la demo e ha (giustamente) obiettato che il voto era dentro il
>   VOUCHER pieno (cancella/prezzo/check-in) — "deve essere solo la votazione, come Booking".
>   Aggiunta `pagina_recensione_html` + rotta `GET /recensione/<token>`: pagina pulita col SOLO
>   form voto (generale + categorie), stesso token/motore/endpoint del voucher. L'email invito
>   post-soggiorno ora punta a /recensione/ (non al voucher). **VINCOLO RISPETTATO: voucher e
>   motore fase63 NON toccati, tutto additivo.** test_pagina_recensione (7 × 10 giri) + voucher/C3
>   ancora verdi. Demo locale su porta 8899 (script scratchpad/demo_votazioni.py; launcher
>   Desktop/APRI-DEMO-VOTAZIONI.html → pagina pulita). NB date "23→19" nella demo = scorciatoia
>   (check_out forzato a ieri per sbloccare il form), NON un bug del prodotto.
> · 🚨 **IL GIRO DELLA MARCA PARTIVA SOLO CON SMTP (2026-07-21) — CHIUSO**: scoperto
>   **avviando `main_casavip.py` per davvero** (nessun test lo esegue). Il ciclo era finito
>   dentro il blocco delle email → senza SMTP le prove non venivano più datate, in silenzio.
>   Ricollocato al primo livello, dipende solo dal proprio archivio. **Riprovato dal vivo:
>   marca vera da DigiCert senza email configurata.** Guardia strutturale (5).
>   **Lezione: avviare il programma vero è un collaudo a sé — `main_casavip.py` è l'unico
>   file che la suite non esegue mai.**
> · 🚨 **ANCHE LE EMAIL TACEVANO IL 3% (2026-07-21) — CHIUSO**: l'email di **benvenuto**
>   (la prima cosa che un host legge) diceva «10% dal marketplace» — mentre nei primi 90
>   giorni paga **0%** — e «nessun costo fisso», senza il 3%. L'email di **reclutamento**
>   (fase89, 6 lingue, dormiente ma lanciabile) prometteva una percentuale **calcolata dai
>   concorrenti**, cioè un numero che il motore NON applica. Entrambe riscritte con le
>   cifre di `fase98`. Guardie nuove provate rosse sul vecchio; il test che pretendeva
>   «15%» è stato invertito. **Filo comune: era stato sistemato ciò che si GUARDA, non ciò
>   che si MANDA.**
> · 🚨 **TRE PAGINE RECLUTAVANO HOST SENZA DIRE IL 3% (2026-07-21) — CHIUSO**: la Strada A
>   aveva sistemato pannello/commissioni/termini/contratto ma **non le pagine con cui si
>   trovano gli host**. `kit-marketing.html` vendeva «**10%** la nostra commissione» e
>   «gratis»; `diventa-host.html` prometteva «zero commissioni nascoste» **in 8 lingue** —
>   mai un accenno al 3%. Riscritte con la verità (che vende meglio: **0% per 90 giorni**),
>   3% dichiarato ovunque, guardia `TestPagineCheReclutanoHost` **provata rossa sul vecchio**.
>   **Erano sfuggite perché l'audit cercava «OTA» senza confini di parola e la trovava dentro
>   «pren-OTA-zione»: ogni riga con "prenotazione" veniva saltata.** Corretto + baseline di 41
>   righe già giudicate legittime → da ora rosso su qualsiasi cifra nuova.
> · 🚨 **DUE DATABASE VIVEVANO IN MEMORIA IN PRODUZIONE (2026-07-21) — CHIUSI**: costruendo
>   la guardia sui percorsi per la marca temporale è saltato fuori che `DB_RECENSIONI` e
>   `DB_CREDITO_USATI` **non venivano passati** da `main_casavip.py` → restavano `:memory:`
>   anche in produzione (verificato sul server: nessun file, eppure il motore risultava
>   acceso). Conseguenze reali: **ogni recensione spariva al riavvio** e **un credito già
>   speso tornava rispendibile dopo un deploy** (denaro vero). Chiusi con 2 righe in `main`
>   + 7 dichiarazioni nel compose + guardia `test_db_persistenti` (7). La creazione delle
>   cartelle ora si ricava da TUTTI i campi `db_*`, non da una lista scritta a mano.
>   **Lezione: i test erano verdi perché usano `:memory:` di proposito — solo il confronto
>   con la configurazione di PRODUZIONE poteva scoprirlo.**
> · 🔴 **DA FARE CON IL FONDATORE — CAMBIARE `ADMIN_KEY`**: la chiave che apre il
>   pannello amministratore (dove si fanno **i rimborsi**) è lunga **11 caratteri** e
>   comincia con una parola riconoscibile, su un sistema con Stripe LIVE. Esiste già il
>   blocco per tentativi ripetuti dallo stesso collegamento, quindi **non è urgente ma va
>   fatto**: è un estintore scaduto, non un incendio. Serve il fondatore presente perché
>   **la nuova chiave deve salvarla lui** (altrimenti resta fuori dal proprio pannello).
>   Procedura completa e a parole semplici in `REGISTRO_INGEGNERIA.md`, sezione
>   «DA FARE / PROSSIMI PASSI».
>
> · 🕐 **AUDIT FUSI ORARI + INPUT + TEST CIECHI (2026-07-22)**: le date **viste** dal
>   cliente erano salve (testo, mai convertite; il browser non usa `toISOString`), ma
>   **ogni calcolo sul tempo usava il fuso del server** — e in produzione non c'è nessuna
>   `TZ`. La finestra per contestare dava **12 ore invece di 24 a Honolulu** e 18 a New
>   York, su soldi già pagati → ancorata al fuso più a ovest, ora nessuno scende sotto le
>   24. Le **«48 ore» di ripensamento erano giorni di calendario** (duravano fra 48 e 72
>   ore secondo l'ora in cui prenotavi) → ora sono **172.800 secondi veri** nel gettone
>   firmato. ⚠️ La prima versione della correzione **peggiorava il male** (Tokyo a 19 ore):
>   l'ha vista la guardia, non io. L'alloggio **non ha ancora un fuso orario** nel modello
>   dati: quando ci sarà, l'approssimazione va sostituita dall'ora locale vera.
>   Input: email dell'ospite non normalizzata · email validata **prima** del trim (uno
>   spazio incollato = «credenziali non valide» a chi ha la password giusta) · alloggio
>   chiamato col suo **slug** anche nel contratto PDF · `Łukasz` → `?ukasz`. Tutti chiusi.
>   Test ciechi: **8**, fra cui `test_dac7_notti` che **si spegneva venti giorni all'anno**
>   su un obbligo fiscale. Guardia nuova sul PATTERN: `test_suite_senza_zone_cieche`.
>   🔴 **DA FARE TU**: `ADMIN_KEY` è di 11 caratteri con una parola riconoscibile davanti —
>   protegge i rimborsi su Stripe LIVE. Cambiala con 32+ caratteri casuali.
>
> · 💱 **AUDIT VALUTA (2026-07-21) — 8 DIFETTI CHIUSI**: l'**addebito era giusto** (browser
>   e motore concordano su ogni valuta, Stripe riceve l'intero con la valuta dell'annuncio)
>   ma **il racconto dell'addebito era falso**: otto punti dividevano per cento a mano,
>   sempre. Un ospite giapponese che paga **¥54.000** leggeva **540.00 JPY** nell'email di
>   conferma, nel **voucher**, nella **ricevuta**, nel **contratto PDF che si firma** e
>   perfino nel **JSON-LD che finisce nei risultati Google**. Causa: `fase99.Denaro.formatta()`
>   era già corretto e **nessuno lo chiamava** — la solita duplicazione. Corretti tutti;
>   `fase57` ora accetta solo sigle ISO di 3 lettere (prima passava `"EURO"`, `"BITCOIN"`).
>   Guardie: `test_importi_scritti` (10, sorveglia il **gesto** — ha trovato 5 punti dopo
>   che ne avevo corretti 3), `test_valute_coerenti` (10, browser=motore),
>   `test_valuta_end_to_end` (13, uno yen vero seguito anello per anello).
>   ⚠️ Trovato anche un difetto **nel mio collaudo**: `plausibilita.py` teneva una terza
>   tabella e dava **HUF/TWD/COP senza decimali** (ne hanno due) → ora legge dal motore.
>
> · 🔴 **PROSSIMO LAVORO — LE EMAIL PARLANO UNA LINGUA SOLA**: `fase86_email.py` ha
>   **10 corpi di email e 9 non sanno in che lingua parlare** (voucher, pagamento
>   confermato, rimborso, invito a recensire, esito controversia, bonifico host, reset
>   password, benvenuto host, promemoria check-in). **È peggio delle pagine**: su una
>   pagina la lingua si cambia, su un'email no. **L'ostacolo non è tradurre: la lingua
>   non viene MAI SALVATA** — il browser prenota con `{quote_token, email}` e basta
>   (`index.html:689`), `registro_host` non ha la colonna, esiste solo in
>   `accettazioni.lang`. Eppure il **link** del voucher porta già `?lang=`: **la pagina
>   del voucher è tradotta, l'email che la annuncia no.** Ordine: browser manda la
>   lingua → la prenotazione la salva → `fase86_email` in 8 lingue.
>
> · 👁️ **LE VERIFICHE DEL PRODOTTO (2026-07-21 notte)** — la lezione piu' cara della
>   giornata: **i due difetti peggiori li ha trovati il FONDATORE guardando il sito**,
>   non i 3011 test. Radice comune: tutti i collaudi provavano il **codice** con **dati
>   inventati da loro**, e nessuno chiedeva *«cosa vede una persona?»*. Due strumenti
>   nuovi guardano il **prodotto finito**:
>   **`collaudi/plausibilita.py`** — «questo numero ha senso nel mondo vero?»: bande
>   credibili, esponenti delle valute (JPY/KRW a **0 decimali**, KWD/BHD a 3), coerenza
>   col resto del listino. Girato sui **dati VERI di produzione** (128 righe, 227
>   controlli, 0 violazioni) e **provato rosso** sul caso reale: riconosce il ¥1.800.000
>   tre volte e ne **nomina la causa** («moltiplicato per cento»).
>   **`collaudi/occhio_del_fondatore.py`** — «chi apre questa pagina, cosa **legge**?»:
>   conta le parole visibili che restano in italiano in tutte e 8 le lingue (tutto cio'
>   che sta fuori dai marcatori `data-t`/`data-i18n` non viene mai sostituito).
>   Debito misurato: **1808 parole** → **1034** dopo il lavoro di stanotte.
>   La piramide passa da **9 a 11 modi di rompersi** (`dato assurdo`, `lingua congelata`)
>   e la copertura degli archivi non si giudica piu' cercando un nome nei test: **si
>   prova** (si aggiunge un archivio finto e si pretende che la suite cada).
>
> · 🌍 **LINGUE — FATTO STANOTTE**: **TERMINI in tutte e 8 le lingue** (mancavano
>   es/fr/de/pt/ja/zh) + **ROTTA `GET /api/legale/documento`** + **gusci** `termini.html`
>   e `privacy.html`: prima il modulo `fase185` era completo ma **scollegato**, e il sito
>   mostrava le vecchie pagine statiche solo in italiano. **749 parole congelate → 2.**
>   Provato che **tutte e 8 le lingue portano le STESSE percentuali** (0/3/5/8/10/15),
>   lette dal motore e mai scritte a mano. Fatte anche **`grazie.html` e
>   `annullato.html`** (le legge OGNI ospite che paga): erano it+en decisi dal browser,
>   ora 8 lingue e **rispettano la lingua gia' scelta sul sito**; lingua ignota → inglese.
>   ⚠️ **DA SAPERE**: la vecchia `termini.html` conteneva un avviso **«BOZZA NON
>   VINCOLANTE»** mentre la piattaforma incassa davvero. Il guscio nuovo mostra il testo
>   ufficiale di `fase185` (lo stesso su cui si firma l'accettazione), quindi **quell'avviso
>   non c'e' piu'**: e' la scelta coerente, ma **va fatto validare da un avvocato**.
>   **RESTA DA FARE, in quest'ordine**: `kit-marketing` (386) · `bunker` (306) ·
>   `guida-operativa` (280) · `admin` (27) · `index` (24 parole, fra cui **«pubblica il
>   tuo alloggio ora»**, un richiamo per host) · `commissioni` (2) · `host` (3).
>
> · 🚨 **FINTI VERDI TROVATI E CHIUSI STANOTTE** (tutti provati rossi dopo la correzione):
>   `test_testi_legali` **si saltava da solo** («la pagina non parla di commissioni»):
>   appena il testo e' uscito dall'HTML per andare nel motore, il controllo del **3%** e'
>   evaporato in silenzio → spostato sul documento vero, in **tutte e 8 le lingue** ·
>   la guardia del cablaggio si accontentava di **un commento** che descriveva la
>   chiamata (con `fetch` spento e commento intatto restava verde) · `occhio_del_fondatore`
>   assolveva le pagine sotto le 15 parole come «troppo poco testo», e cosi' **`grazie.html`
>   (14 parole, 0% tradotta, la legge ogni ospite che paga)** passava: **ASSENZA NON E'
>   CONFORMITA'**, di nuovo · la piramide dava **12 archivi scoperti** che erano invece
>   coperti (rosso falso: cercava il nome, non la sorveglianza).
>
> · 🛡️ **IL SISTEMA CHE SORVEGLIA SE STESSO (2026-07-21, `d819765`)**: non piu' solo
>   test, ma un'architettura di verifica. **`collaudi/piramide.py`**: 6 livelli
>   (fondamenta → unita' → cablaggio → sistema → realta' → meta), ognuno regge quello
>   sopra, e se un modo di rompersi resta **senza guardiani** esce ROSSO.
>   **`collaudi/capitolato.py`** (idea del fondatore): si dichiarano le PROPRIETA' e la
>   macchina controlla **ogni elemento contro ognuna** — cosi' «quello che adesso non mi
>   viene in mente» non dipende piu' dalla memoria di nessuno.
>   **`collaudi/logiche.py`**: i ragionamenti a catena seguiti **anello per anello**
>   (308 anelli) — chi lo legge capisce come funziona la macchina senza ricordarselo.
>   **`collaudi/mutazione_prodotto.py`**: si rompe il motore di proposito e si pretende
>   che i test se ne accorgano (**10 mutanti su 10 uccisi**).
>   **`collaudi/mappa_scoperta.py`**: cosa non e' guardato da NESSUNO (138 rotte, 134
>   moduli → **zero zone cieche**). **`collaudi/caccia_finti_verdi.py`**: test saltati,
>   senza asserzioni, guardie che non possono fallire.
>   ⚖️ **REGOLA DEI 10 COLLAUDI in `CLAUDE.md`**, con i 9 modi di rompersi incontrati sul
>   campo e la regola madre: **NESSUN VERDE VALE FINCHE' NON E' STATO VISTO ROSSO**.
>
> · 🚨 **DIFETTI VERI TROVATI DAGLI STRUMENTI NUOVI (tutti chiusi)**: **13 test di
>   SICUREZZA non giravano** (classe legata a `pyyaml` assente: corazza nginx, HTTPS,
>   segreti, generazione chiavi) → riscritti senza dipendenze, da 4 a 21 · **3 guardie
>   nginx NON POTEVANO FALLIRE** («la stringa c'e'» invece di «la protezione c'e' su OGNI
>   porta») · un mio test **si saltava da solo** · la baseline dell'audit **si
>   auto-approvava** · l'audit **si leggeva addosso** il proprio rapporto · la
>   **MUTAZIONE** ha scoperto che lo scaglione **8% non era difeso da nessuno** (10% al
>   posto di 8% = +2% su ogni prenotazione, e la suite restava verde) · 2 rotte mai
>   nominate da un test · l'ora del dossier legale non dichiarava il fuso.
>
> · 💶 **BUG SUI SOLDI TROVATO DAL FONDATORE GUARDANDO IL SITO**: `Zen House Shibuya`
>   mostrava **¥1.800.000 a notte** (≈€11.000). Lo **yen non ha decimali**: il prezzo era
>   stato salvato ×100. **Il motore era SANO** (provato: un host giapponese che pubblica
>   ¥18.000 salva `18000`) — era solo il dato dimostrativo, **corretto in produzione**.
>   ⚠️ **LEZIONE APERTA**: nessun collaudo guarda se **il numero ha senso**. Serve una
>   classe nuova: **plausibilita' semantica del dato** (un ×100 sfonda qualsiasi banda
>   ragionevole). Vale anche per capacita', distanze, date, percentuali.
>
> · 🌍 **LINGUE — LAVORO APERTO, priorita' del fondatore**: 8 pagine pubbliche erano
>   **solo in italiano**, fra cui **privacy** (obbligo GDPR) e **termini** (contrattuali).
>   Il capitolato non le vedeva perche' **saltava le pagine senza dizionario**: il caso
>   peggiore trattato come "non applicabile" → chiuso, **ASSENZA NON E' CONFORMITA'**.
>   **FATTO**: `fase185_testi_legali.py` con **PRIVACY in tutte e 8 le lingue** complete
>   (it/en/es/fr/de/pt/ja/zh), versione + impronta SHA-256, **lingue realmente fornite**
>   (non solo dichiarate) e clausola **«fa fede l'italiano»**; percentuali da `fase98` e
>   penale da `fase83`, mai scritte a mano. Guardia `test_testi_legali` (15).
>   **DA FARE, in quest'ordine**: (1) **TERMINI nelle 6 lingue mancanti** (ci sono solo
>   it/en) · (2) **rotta API + gusci** per termini/privacy (il sito mostra ancora le
>   vecchie pagine: il modulo esiste ma **non e' collegato**) · (3) `grazie.html` +
>   `annullato.html` (~170 parole, le vede **ogni ospite che paga**) · (4) `commissioni`
>   + `contratto-host` · (5) `host.html`: ha 8 lingue ma **158 voci vuote** in
>   es/fr/de/pt/ja/zh · (6) `admin` + `bunker` — il fondatore si e' corretto:
>   «mettiamo tutte le lingue per coerenza», **nessuna pagina e' esente**.
>
> · 💱 **VALUTE**: regola confermata — l'host prezza nella **sua** valuta e l'ospite
>   **paga quella**; si converte solo la **VISUALIZZAZIONE** (se si convertisse
>   l'addebito, il cambio fra prenotazione e incasso farebbe perdere qualcuno).
>   Il **convertitore ESISTE GIA'** (`fase99`) ed e' **SPENTO**: manca `OXR_APP_ID` sul
>   VPS. **Non e' un lavoro, e' un interruttore** — serve una chiave del fondatore.
>
> · ⚖️ **MARCA QUALIFICATA EUROPEA ATTIVA (2026-07-21, eIDAS art. 42)**: non più una
>   marca "qualunque" — le chiediamo a **prestatori della lista di fiducia europea**
>   (**ACCV** Spagna e **QuoVadis EU** come prime scelte, **Izenpe** e **Stato belga**
>   di riserva). L'**art. 41 eIDAS** dà alla marca qualificata la **presunzione legale**
>   di esattezza di data e ora: **l'onere della prova si rovescia** sulla controparte.
>   La qualifica **si legge dentro il token** (dichiarazione ETSI `0.4.0.19422.1.1`), non
>   si assume: se un prestatore la perdesse, la marca dopo risulterebbe subito non
>   qualificata. **Provata dal vivo**: marca ACCV reale, `openssl ts -verify` → OK.
>   Se nessun qualificato risponde si ripiega **etichettando onestamente** la marca come
>   non qualificata (`MARCA_SOLO_QUALIFICATA=1` vieta anche quello). Guardie:
>   `test_marca_qualificata` (14) + `test_qualifica_catena` (11, **anello per anello**
>   fino al dossier) + livello **N7** nel collaudo a neuroni.
> · ⏱️ **MARCA TEMPORALE RFC 3161 (2026-07-21, l'ultimo tassello)**: le nostre firme le
>   facciamo noi, con il nostro orologio → restava l'obiezione *"l'ora ve la siete scritta
>   voi"*. Ora ogni giorno i registri (accettazioni + giornale) si riducono a **un'impronta**
>   che viene **datata da un'Autorità esterna** (DigiCert/Sectigo/Entrust, con ricambio).
>   ASN.1/DER **scritto a mano** → zero dipendenze. Alla TSA va **solo l'impronta**: nessun
>   dato esce. Il `.tsr` si scarica dal Bunker e si verifica **senza di noi** con
>   `openssl ts -verify` (**provato dal vivo**: token DigiCert → *Verification: OK*; documento
>   con un carattere cambiato → *message imprint mismatch*). Sette TSA provate, tre promosse:
>   Apple/FreeTSA/Izenpe **scartate** perché la loro radice non sta nelle CA standard.
>   Guardie: `test_fase184_marca_temporale` (65) + `test_marca_temporale_server` (18).
>   Kill-switch `MARCA_TEMPORALE=0`. **Per una marca formalmente QUALIFICATA (eIDAS art. 42)
>   basta mettere in `TSA_URL` l'indirizzo di un ente della lista europea: zero codice.**
> · 🪪 **IDENTITÀ LEGATA ALLA FIRMA (2026-07-21, super-tutela)**: prima la prova non diceva CHI
>   aveva firmato (difesa facile: "non ero io"). Ora, se l'host è verificato con Stripe Identity,
>   il registro scrive una **terza riga firmata** `identita_stripe` che lega la **sessione di
>   verifica** (`vs_...`) al **testo esatto** del contratto, con impronta **ricalcolabile da
>   chiunque**. Il riferimento è DENTRO la firma HMAC (alterarlo la invalida) ma entra solo
>   quando c'è → **le prove già archiviate restano integre**. Scritta alla firma o **quando la
>   verifica arriva dopo**. Visibile nel Bunker e nel dossier (6 colonne). Guardia
>   `test_identita_contratto` (14). PROSSIMO possibile: **marca temporale qualificata** via
>   provider REST (chiude l'obiezione "i registri li avete scritti voi") — valutato, non fatto.
> · 🏰 **SALA CONTROLLO SUPER-ADMIN (2026-07-21)**: dall'audit "il super-admin è cieco" →
>   4 rotte nuove tutte Bunker-gated: `scaglioni_host` (a che tariffa sta ogni host, giorni al
>   prossimo scatto e DATA del cambio), `prove_legali` (IP · ora UTC · versione · impronta ·
>   firma HMAC-SHA256 · flag integra, con conteggio manomesse), `costi_tecnici` (3% coperto vs
>   PERSO sui rimborsi: Stripe non restituisce la sua fetta) e `export_legale` (**dossier
>   certificato** CSV/JSON con anagrafica+scaglione+prove+prospetto tecnico, chiuso da impronta
>   SHA-256). **FONTE UNICA `fase98.stato_scaglione`**: motore e vetrina ora usano la stessa
>   funzione → divergenza impossibile (prima fase81 seguiva COMMISSIONE_BPS e fase83 no).
>   **Field messo in sicurezza**: `/api/admin/verifiche/dettaglio` non espone più IP/impronta
>   senza secondo fattore. 3 sezioni nuove in bunker.html. Guardia `test_bunker_scaglioni_prove`
>   (18). NB: dossier in CSV/JSON, **non PDF** (servirebbe una libreria esterna = viola zero-dipendenze).
> · 📚 **RIASSETTO DOCUMENTALE + BONIFICA VPS (2026-07-20)**: radice blindata a **5 file
>   ufficiali** (README · REGISTRO · RIPRENDI_QUI · DEPLOY · CLAUDE), gli altri 9 in `_archivio/`
>   (23 doc storici + LEGGIMI che avvisa "cifre superate"). **README riscritto da zero** (quello
>   vecchio parlava di Flask/Aruba/1875 test) e **DEPLOY.md riscritto**: documentava il vecchio
>   stack e la procedura `docker compose up -d` che **su questa macchina FALLISCE** — chi lo
>   seguiva rompeva il deploy. **CLAUDE.md: REGOLA ZERO** (solo i 5 file ufficiali, `_archivio`
>   mai da seguire, ⛔ vietato creare nuovi `.md`, numeri da verificare nel codice). Audit
>   millimetrico dei 5 documenti vs motore: **0 discrepanze**. Sul VPS rimossi i **19 file
>   orfani** (backup in `/root/orfani-backup-20260720`). ⚠️ **INCIDENTE risolto**: `git clean`
>   ha cancellato anche `certbot/` (bind-mount del rinnovo HTTPS) → `certbot renew` falliva =
>   bomba a orologeria a ~60 giorni. Ricreata + `docker rm -f casavip_nginx` (trappola inode) →
>   **"all simulated renewals succeeded"**. LEZIONE: su VPS mai `git clean` senza escludere i
>   bind-mount vivi del compose.
> · 🔎 **AUDIT COERENZA A TAPPETO (2026-07-20, pre-rilascio)**: ispettore che legge le tariffe VERE
>   dal codice e scansiona **1.346 file** cercando cifre non allineate. **Pagine utente: ZERO
>   anomalie.** Trovati e corretti 3 refusi nei documenti vivi: STRATEGIA_VINCENTE diceva ancora
>   "Noi oggi 15%", STRATEGIA_CRESCITA diceva "nei primi 3 mesi paghiamo NOI Stripe" (contraddiceva
>   Strada A: il 3% è SEMPRE dell'host) e promo "OFF" (in prod è ON), REGISTRO/fase98 presentavano
>   il modello legacy "2%/8%" come vigente → marcato LEGACY. `_archivio/` (10 doc storici con cifre
>   vecchie) NON va in produzione → aggiunto banner LEGGIMI-ARCHIVIO. Guardia STRUTTURALE permanente
>   `TestNessunaCifraOrfana`: ri-scansiona deploy/*.html a ogni suite → cifra orfana = suite rossa.
> · ⚖️ **CONSENSI BLINDATI (2026-07-20, audit legale)**: prima UNA casella copriva Contratto+Privacy
>   (GDPR vuole consensi distinti) e le clausole vessatorie erano controllate SOLO dal browser —
>   **provato**: via API `accetta_clausole:false` → account creato con vessatorie=0 = trattenute/
>   penali/foro NON opponibili. Ora: **3 caselle** (Contratto · artt.1341-1342 · Privacy GDPR),
>   **tasto grigio e non cliccabile** finché non sono spuntate tutte, e il **server rifiuta a monte**
>   (422 `consensi_mancanti`, nessun account). La privacy è registrata come **documento separato**
>   (riga nuova, non colonna nuova → le 114 prove già archiviate restano `integra`). Aggiunta la
>   **RI-ACCETTAZIONE** (art.13): `GET /api/host/contratto_stato` + `POST /api/host/riaccetta` +
>   card gialla che compare da sola al login quando il contratto cambia (append-only: le prove
>   vecchie restano). Guardia `test_consensi_blindati` (13); aggiornati 84 payload in 74 test.
> · 🚨 **BUG GRAVE: LA PROMO 0% NON ERA MAI STATA APPLICATA — FIXATA (2026-07-20)**. Trovato
>   mentre il fondatore chiedeva di verificare il link diretto: il motore addebitava **10% dal
>   primo giorno** invece dello 0% dei primi 90gg. Causa (1 riga, fase81): il proprietario si
>   leggeva da `dettaglio(slug)["host_id"]` ma il dettaglio pubblico NON espone l'host → hid
>   sempre None → rampa saltata → fail-safe 10%. Fix: `catalogo.host_di_alloggio(slug)`. Peggio:
>   `/api/trasparenza` (strada diversa) MOSTRAVA 0% → **promettevamo 0% e addebitavamo 10%**.
>   Nessuna guardia lo prendeva: una testava la formula da sola, l'altra la pagina — mancava il
>   percorso vero (quote→commissione). +2° fix: la rampa terminava su 10% FISSO ignorando
>   `COMMISSIONE_BPS` (impostazione ignorata = ricavo perso) → ora finisce sul regime configurato.
>   Guardia permanente `test_promo_lancio_e2e` (9, ROSSA sul vecchio) + collaudo multi-metodo
>   (560 combinazioni differenziali, 480 richieste concorrenti, catena soldi a 0%, fuzz) = 0 violazioni.
> · 💶 **TRASPARENZA COSTI HOST "Strada A" (2026-07-20)**: audit read-only del modulo pagamenti →
>   il codice era GIUSTO (costo carta 3% dedotto dal netto host, `PAGAMENTO_BPS` default 300, non
>   impostato sul VPS) ma i TESTI non lo dicevano: con la promo lancio ATTIVA (0% primi 90gg / 8% /
>   10%) l'host a 0% credeva di "tenere tutto" e invece il 3% gli veniva dedotto. Scelta fondatore:
>   allineare i TESTI, **mai le formule**. Fatto: card "🎉 Promozione Lancio 0%" in cima al pannello
>   host coi 4 scaglioni espliciti (0/8/10% + diretto 5%, sempre **+3% tariffa tecnica**), corretti
>   `h_prezzo_osp`/`dir_p` in TUTTE le 8 lingue, **ART. 6-BIS** nel contratto IT+EN ("SEMPRE dovuta"),
>   **versione contratto 2026-07-11 → 2026-07-20** (gli host ri-accettano: indolore ora, 0 host reali),
>   §5 dei termini pubblici riscritto. Guardia ANTI-DERIVA `test_trasparenza_costi` (11): le % dei
>   testi sono ancorate alle costanti del codice → cambiare una tariffa senza aggiornare i testi
>   fa diventare la suite ROSSA. ⚠️ REPERTO aperto (business): il "diretto" resta 5% anche durante
>   la promo → nei primi 90gg il diretto (8% totale) costa PIÙ del marketplace (3% totale); i testi
>   lo dichiarano onestamente, invertirlo sarebbe una modifica di logica. Riga TRASPARENZA REGISTRO sez.1.
> **PROSSIMI PASSI**: nessuno obbligato. Idee aperte (attendono VAI): passo-2 del comp.1 (batchare
>   anche il calendario, fase58); estrazione dei rami geo/consigliati di `_catalogo`; sblocchi
>   Meta/TikTok/OXR (prerequisiti del fondatore, sez.2-bis). Regole ferme invariate (salvare
>   ovunque, mai email vera, deploy rm-first, suite intera prima del deploy). REGOLE FERME: dopo OGNI operazione finita salvare ovunque
> (commit+push+VPS+REGISTRO); mai email vera del fondatore nei test; deploy rm-first; suite intera
> prima di ogni deploy. Dettaglio di ogni voce: righe in REGISTRO_INGEGNERIA.md sez.1 (piu' recenti in alto).


> 🏔️ **2026-07-18 — MEGA-SIM RECORD 1000 HOST × 10.000 CLIENTI: VERDE.** "Un anno di vita" a
> scala 10× il precedente (SIM_HOST=1000 SIM_CLI=10000, 30min): 2185 confermate, 1287 contestate,
> 901 cancellate, 901 scadute, 1220 su-richiesta, 100 controversie arbitrate — tutti gli invarianti
> tenuti (0 overbooking SQL, conti al cent su ogni quote, escrow esatto, gara 100→1 vincitore).
>
> 💥 **2026-07-18 — BOMBARDAMENTO PIENO "10.000 MENTI" RIESEGUITO: ZERO VIOLAZIONI.**
> 10 seed × 1000 agenti (fuzzer permanente test_menti_invarianti a scala massima) in 246.6s
> sul codice corrente (`8f4322c`): nessun overbooking, nessun doppio-payout, conti/escrow/tassa
> esatti, single-use crediti tenuto. + guardie concorrenza (17 test: gare sui soldi, calendario,
> fuzzing input ostili) verdi in 23.9s. I `401 Stripe` nei log del fuzzer = chiave FINTA respinta
> e ISOLATA per design (prova che il guasto del fornitore non rompe mai il flusso). Stesso giorno:
> ispezione statica TOTALE del progetto (76k righe, `ispettore_statico.py`) → 0 bug nuovi.

> 🧠 **2026-07-17 sera — MOTORE SEO AUTONOMO (l'arma proprietaria) COSTRUITO + DEPLOYATO (deploy #6).**
> "Appena uno pubblica, in automatico fa quello che va fatto." Due pezzi, metodo del fondatore
> (potenza dichiarata prima). **CERVELLO `fase171_cervello_seo.py`** (vincitrice benchmark 4 varianti
> + verifica avversariale): la pagina = registro di FATTI CITABILI; `valuta_annuncio()` → punteggio
> 0-100 + query long-tail VINCIBILI (mai teste, k≥2) + gap azionabili white-hat, tutti dallo stesso
> ledger. Pesi ai fatti PUBBLICI non falsificabili (distanza-POI, tassa, quartiere); ancora-BITMASK
> anti-stuffing; anti-spoof geo; matematica INTERA (invariante Σgap==100−punteggio); fairness di
> posizione; puro/deterministico; 4 bug uccisi dal sandbox. **ORCHESTRATORE `fase173_motore_seo.py`**:
> hook in `_host_pubblica` (ISOLATO, non rompe mai il publish) → contesto pubblico da provider
> iniettabili (tassa147 cablata) → specchio del JSON-LD reale (anti-deriva) → cervello → ping IndexNow
> (gated). + `jsonld_alloggio` esteso (geo/image/bagni, no-float). + rotta `GET /api/host/seo_report`
> (auth+proprietà). **VERIFICATO LIVE**: home 200, /api/domanda ok:true, /api/health 200, seo_report
> senza auth→401. Container healthy, boot pulito. **Desktop=GitHub=VPS=`c24e10b`**, suite **2428 verde**.
> **2026-07-17 (deploy #7): PROVIDER POI-OSM `fase175` ACCESO** — arricchisce il geo del cervello coi
> luoghi notevoli vicini all'annuncio (Overpass around:1500m, fetch iniettabile + cache SQLite, blindato).
> Cablato via `con_poi` (fase81) + env `POI_OSM=true`/`DB_POICACHE=/data/poicache.db` (sul VPS PRIMA del
> deploy). In prod risulta `poi_osm(175)` nella composizione, boot pulito, verificato live. VPS=GitHub=
> Desktop=`c64cdb8`, suite **2438 verde**. Rimosso uno stub orfano fase175_arricchitore_osm.py.
> **2026-07-17 (deploy #8): FAQ AEO da FATTI REALI ACCESE** — ogni pagina alloggio genera FAQ dai
> fatti del ledger (prezzo, distanza-POI in metri, tassa, capacità...) → FAQPage JSON-LD (rich result +
> estraibile dagli AI) + `<details>` visibili e coerenti. È il ponte AEO (farsi citare da ChatGPT/
> Perplexity). fase173.genera_faq, white-hat (solo fatti presenti), innestato in pagina_alloggio_html
> (isolato). Live 7 FAQ (prezzo 120.00, POI 13m, tassa 3.50) visibili+strutturate. VPS=GitHub=Desktop=
> `4811b23`, suite **2442 verde**, container healthy.
> 🚦 **2026-07-18 (deploy #14): SEMAFORO UNIVERSALE** — direttiva fondatore: 3 colori identici
> ovunque (verde=libero, arancione=in trattativa, rosso=occupato/chiuso). Fixato il verde-ambiguo
> del calendario prezzi (usava il verde-libero per "prezzo ↑"), mappa SEMAFORO unica sui 2 dialetti
> del motore (58/119), classi condivise host+index, legenda a 3. Griglia "tutta verde" verificata
> NON-bug sul DB live (0 prenotazioni/hold pre-lancio: è la verità). PROSSIMO: Livello 7 E2E live.
> 🎨 **2026-07-18 (deploy #13): FRONTEND ZERO-DIFETTI giro 2 (Web App Ospite)** — mappa a neuroni
> pulita (58 id, 12 rotte vive, 32 link tutti esistenti, z-index sano), 8 catch muti curati; +
> trovato per strada un difetto VERO nel backup legacy fase38 (stesso tick = sovrascrittura muta)
> corretto con suffisso anti-collisione. Suite 2455 stabile.
> 🎨 **2026-07-18 (deploy #12): FRONTEND ZERO-DIFETTI giro 1 (Host+Admin)** — protocollo del
> fondatore "a neuroni": mappa sinaptica pulita (0 fili rotti, 0 rotte morte, i18n pari), poi
> `.btn-riga` (fine dei bottoni enormi nelle tabelle), 21 catch muti → console.warn, 2 campi
> fantasma rimossi, calendario verificato sano. Guardie permanenti in test_host_ux. PROSSIMO
> del protocollo: Web App Ospite (index.html) con metodo d'ispezione DIVERSO, poi altri giri.
> ✅ **2026-07-18 (deploy #11): QUARTIERE AUTOMATICO ACCESO** (fase166 reverse-geocode + quartiere_fn
> nel motore SEO: pin → nome quartiere → 70 punti geo + query "in zona X"; cache ~100m, no env nuove).
> L'arco SEO 171→173→175→166 è ora COMPLETO: niente più "da accendere" nel motore SEO.
> ✅ **2026-07-18 (deploy #10): UI RAPPORTO SEO nel pannello host ACCESA** (card 📈 negli Strumenti
> avanzati: punteggio /100, cosa migliorare, ricerche vincibili — riga 📈 nel REGISTRO) + 2 test
> flaky legacy fase15 resi deterministici (suite 2446, 0 errori, stabile 15/15).
> ✅ **2026-07-18 (deploy #9): INDEXNOW ACCESO** — chiave in `.env.casavip` (VPS, prima del ricreate),
> key-file 200, primo submit reale 236 URL → scoperto+fixato 403 per User-Agent mancante (classe
> Groq/fase165) → ri-submit **200 OK**. Ping automatico a ogni publish ora attivo. Dettaglio: riga 📡 REGISTRO.

> 🌍 **2026-07-17 — ARCO SEO GLOBALE (195 nazioni, multi-motore) COSTRUITO + DEPLOYATO (deploy #5).**
> Otto pezzi in sequenza, ognuno con sandbox/guardia permanente, suite intera verde, commit+push+VPS:
> (1) **semantica HTML5** landmark `<main>/<section>` (fase97); (2) **`<lastmod>`** in ENTRAMBE le
> sitemap (per-scheda reale via `fase57.slug_lastmod_pubblicati` + costante template); (3) **algoritmo
> maglia small-world** per i link interni (`fase97.maglia_link_interni`: fortemente connesso, diametro
> 4 su 28 nodi, grado k=6 → niente link-farm) + **BreadcrumbList** + **`test_seo_sandbox.py`** (crawl
> simulato multi-invariante); (4) **registro città data-driven + gate anti-doorway** (`registro_citta`
> = seed ∪ inventario reale; città fuori dal registro → 404: la superficie cresce SOLO dove c'è valore,
> mai scaled-content); (5) **hreflang lingua+PAESE** (`REGIONI_HREFLANG`, 20 locali BCP-47, URL distinti
> self-canonical reciproci + x-default + og:locale); (6) **sitemap-index + sharding** (`sitemap_index`,
> `shard_citta` sotto il tetto 50k, rotte `/sitemap-index.xml` + `/sitemap-host-<i>.xml`, robots→indice);
> (7) **IndexNow** (`fase169_indexnow.py`, gated `INDEXNOW_KEY`, ping Bing/Yandex/Seznam/Naver, rotta
> `/{key}.txt`); (8) **conditional GET** ETag→304 + Cache-Control su tutte le rotte crawlabili
> (`fase83._testo_seo`) + **header/footer** semantici. **VERIFICATO LIVE**: home 200 cert ok,
> /api/domanda ok:true, /sitemap-index.xml 200, /affitta/roma con ETag+Cache e **304** su If-None-Match,
> robots→sitemap-index, /affitta/roma?lang=es-MX → `html lang="es-MX"`. Container **healthy**, boot pulito
> (`money_path_pronto:True, avvisi:[]`). **Desktop = GitHub = VPS = `409fa49`.** Suite **2393 verde** (3
> skip PG). Onestà: nessun algoritmo garantisce il "primo posto" — questo massimizza il potenziale
> TECNICO dentro le policy Google (white-hat) ed è a prova di penalizzazione. Dettaglio: righe SEO nel
> REGISTRO. ~~DA ACCENDERE: IndexNow submit~~ → ✅ ACCESO 2026-07-18 (deploy #9, vedi sopra).

> ✅ **DEPLOYATO IN PRODUZIONE il 2026-07-16 sera su "pusha" del fondatore** (commit `0f3fb56`,
> 28 fix del giorno inclusi): procedura rm-first, container `app`+`backup` **healthy**, verificato
> vivo (homepage 200 cert ok, `/api/domanda` ok:true, `/api/health` 200, host.html nuovo con
> colonna PIN). Suite 2303 verde al momento del deploy.
>
> ⚡ **2026-07-17 — CAMPAGNA "10.000 MENTI" (bombardamento CONCORRENTE, pilota automatico).**
> 11 bersagli bombardati con thread simultanei sullo stesso record (non più agenti sequenziali):
> money-spine (400 voucher × 10.000 thread), chat/prove-controversia, su-richiesta (2700 thread),
> referral/credito (double-spend), check-in, recensioni, MCP, split-payment, **calendario-prezzi,
> registrazione-host, ledger-tassa**. **2 BUG VERI trovati e corretti**: **#30** cancellazione non
> revocava il check-in → smart-pass valido su prenotazione cancellata (fix tombstone `revocato=1`);
> **#31** ledger tassa sovra-contava i rimborsati sotto race pay∥cancel → rischio di versare al
> Comune tassa già restituita (fix tombstone `stornato=1` + storna incondizionato, commit `f0c0324`).
> Pattern: i bug di concorrenza sul money-path sono TOCTOU cross-tabella → soluzione = tombstone
> permanente + BEGIN IMMEDIATE. Tutto il resto: 0 violazioni.
>
> **+ #32 (ragionamento "che test mancano" col fondatore)**: CRASH a metà webhook pagamento — se il
> handler muore dopo il CAS 'pagato' ma prima dei passi derivati, il retry di Stripe usciva subito →
> **tassa persa dal ledger + payout bloccato 'in_attesa' per sempre**. Fix: `_riasserisci_incasso`
> (tassa+payout idempotenti) chiamato anche sul ramo retry 'pagato'; il retry SANA lo stato (commit
> `60b1d1e`). Investigato anche il fuso orario: prod = UTC deterministico → limitazione nota
> media-bassa (fix giusto = fuso per-alloggio, feature, NON nelle 48h).
>
> ✅ **DEPLOY LIVE #3 FATTO** (2026-07-17 su "pusha", VPS `ffba36a`→`e9aaeaf`): fix **#31 (tassa)** +
> **#32 (crash-recovery)** ora in PRODUZIONE. Procedura rm-first, 3 container **healthy**, log avvio
> puliti (money_path_pronto:True, avvisi:[], ledger_tassa(147)+checkin(127) caricati), verificato vivo
> (homepage 200 cert ok, /api/health 200, /api/domanda ok:true). **VPS = GitHub = `e9aaeaf`: TUTTO
> ALLINEATO, niente in sospeso per il deploy.** Suite 2332 verde. (3 deploy live totali della sessione.)
>
> ✅ **DEPLOY LIVE #4 (2026-07-17 mattina)**: revisione modulo Calendario Prezzi / Vista Multi-Alloggio →
> **BUG #33** (fase119: giorno PIENO mostrato "libero" + CHIUSO ignorato — deriva di contratto: il provider
> reale espone `unita_occupate`, il finto dei test usava `venduto`) e **BUG #34** (host.html: bottone
> "💶 Prezzi" MORTO da sempre in prod — `money()` inesistente nella pagina, ReferenceError; + escape titolo
> nella vista multi-alloggio) corretti + `fase58.stato_range` vincitrice benchmark 3 varianti (vista
> 362ms→1.7ms; **2.4s→21ms sotto scrittura tariffe concorrente multi-dispositivo**) + occupazione REALE
> del range nel prezzo dinamico (prima fissa 5000 bps = fattore fase106 inerte). Suite verde 2 giri,
> commit `7a00f58`, **Desktop=GitHub=VPS allineati**, container healthy, fix verificato nella pagina
> SERVITA (money( assente, fmt/escH presenti). Dettaglio: REGISTRO_INGEGNERIA.md righe 📅/🖱️.
>
> ✅ **ROUND #35+CODA+SPLIT (2026-07-17 pomeriggio, 3 commit + 2 deploy)**: (1) bombardamento vista
> multi-alloggio → **BUG #35** (notte VENDUTA nascosta da 'chiuso') fixato, priorità venduta-vince-su-
> chiusa, 10 seed × 2.700 richieste = 0 violazioni (`1768fea`, LIVE). (2) Coda fase67 bombardata (10
> seed = 0 violazioni) + `db_coda` configurabile (`b38d6d1`). (3) Split di gruppo → **BUG #36** (rotte
> VIVE su `:memory:` condiviso = 538/960 pagamenti simultanei in 503 + conti PERSI al riavvio) fixato:
> `db_split`/`DB_SPLIT` su file + timeout 30s fase65/67 → 503=0. ⚠️ **INCIDENTE**: primo deploy split in
> crash-loop (~3 min down: env DB_SPLIT/DB_CODA mancanti sul VPS → `unable to open database file`);
> riparato (env su `/data/*.db` nel volume) e blindato (factory creano il genitore mancante; regola:
> nuova env di store denaro va sul VPS PRIMA del deploy). Verificato live: health 200, /api/domanda
> ok:true. Dettaglio: REGISTRO righe 🏘️/🎫/💸.
>
> 🔑 **CHIAVE STRIPE (dove sta)**: la chiave LIVE (`sk_live_`) + webhook secret sono in `.env.casavip`
> **SOLO sul VPS** (`/var/www/bookinvip/.env.casavip`), attivi nel container. NON in git (gitignore
> esclude i `.env` = giusto, repo pubblico); in locale solo i `.example` con segnaposto vuoti. Se il
> VPS muore, la chiave si ri-ottiene da **dashboard.stripe.com → Developers → API keys** (non è
> perdita: il codice insostituibile è su GitHub).
>
> 🎯 **GAP RIMANENTI (servono al fondatore)**: (1) Stripe VERO test-mode (tutto gira con Stripe finto);
> (2) frontend browser E2E (Playwright); (3) carico sostenuto (soffitto SQLite / Postgres).

**AGGIORNAMENTO (2ª parte sessione, metodo libro sui rami su-richiesta e contestazione): +5 bug VERI
(16-20), tutti con prova dal vivo + fix + test + commit:**
16. `8617e14` decisione approva/rifiuta richiesta NON atomica → approva+rifiuta simultanei = prenotazione
    confermata su date liberate (OVERBOOKING + cliente invitato a pagare stanza inesistente); fix CAS
    `rimuovi_se_stato` (fase162) nei due rami di `_decidi_richiesta`.
17. email esito richiesta: rifiuto = SILENZIO al cliente; scadenza 24h = email-bugia "pagamento non
    riuscito"; fix `_email_esito_richiesta` (onesta, "nessun addebito") + smistamento nello sweep.
18. split parziale controversia: ledger payout restava PIENO → `da_pagare` gonfiato = il bonifico
    manuale pagava all'host anche la quota rimborsata all'ospite; fix `fase131.imposta_importo`.
19. cancellazione con PENALE: quota-penale dell'host decisa dall'escrow ma payout 'trattenuto' pieno e
    NESSUN bonifico mai → l'host non riceveva ciò che gli spetta; fix: escrow chiuso PRIMA, ledger
    riallineato alla quota + transfer (prima di `marca_da_rimborsare`).
20. gara contesta↔auto-rilascio 24h: SELECT in autocommit + UPDATE senza guardia → 'contestato'
    sovrascritto e HOST PAGATO con disputa aperta (3/300 nella sonda); fix CAS per riga in
    `fase160.auto_rilascia`.
21. disputa aperta ma payout 'maturato' → `da_pagare` includeva il conteso (bonifico manuale avrebbe
    pagato l'host con l'arbitro al lavoro); fix: contesta → payout 'trattenuto', risolvi parziale →
    record ricostruito con la quota (`fase131.info`+`registra_maturato`).
22. pagamento tardivo: garanzia restava 'annullato' (escrow morto: conferma/contesta 409, auto-rilascio
    mai, host mai auto-pagato); fix: revive CAS solo-da-annullato in `fase160.apri`.
STADIO FINALE FATTO: fuzzer "1000 menti" esteso (approva/rifiuta/risolvi/expire+sweeper, Connect
finto, +4 invarianti sui bonifici) — **10 seed × 1000 menti = ZERO violazioni**.

**3ª parte (stessa sessione), altri rami del libro — +7 difetti chiusi, suite 2303 verde:**
23. check-in accettato su prenotazione CANCELLATA (ospiti fantasma + sblocco porta futuro) → 409.
24. PIN/codice check-in invisibili nel pannello host (solo nell'email) → /api/host/prenotazioni
    porta codice+pin (rif estratto anche da idem 'reblock:'), colonna in host.html.
25. recensione "verificata" su CANCELLATA dopo la purga 26h (guardia falliva-aperta, classe #95)
    → segnale durevole dal flag `rimborsato` dei movimenti inventario.
26.-27. chiave SBAGLIATA `rilasciato` (fase58 espone `rimborsato`): pannello host mostrava
    "Confermata" anche le rimborsate + le rimborsate bloccavano per sempre alloggio_elimina.
28. referral: soglia `==` esatta → gara webhook (3ª+4ª pagate insieme) = premio €40 perso PER
    SEMPRE → `>=` (il dedup dello store garantisce già l'una-volta-sola).
**4ª parte (sera, dopo il deploy — "testare ancora più a fondo"):**
29. multi-valuta: CREDITO senza valuta → €5 scontavano ¥500 e un Credito Viaggio nato da penale in
    valuta debole si spendeva come €50 su annunci EUR (leak farmabile) → il credito porta la SUA
    valuta (fase158 EUR, anti-rimpianto = valuta della prenotazione, legacy = EUR) e sconta SOLO
    annunci nella stessa valuta. NON ancora deployato (serve nuovo "pusha").
RAMI VERIFICATI SENZA DIFETTI: iCal a fondo (ostile/tetti/import-su-prenotato/roundtrip
cross-canale/2000 eventi in 1s — tutto vivo); attore Telegram (9 test dedicati verdi).
STADIO FINALE ripassato sul codice nuovo: 10 seed × 1000 menti = ZERO violazioni. Suite 2307.
IL LIBRO È COMPLETO: tutti i rami degli attori tracciati (ospite, host, admin, macchina, email,
telegram) + intrecci. 5ª/6ª parte: martello "1000 cose" sui preventivi (988 caotici, 7 invarianti
al centesimo, 0 violazioni → guardia test_quote_coerenza) + MCP fase60 bombardato (0 difetti:
prezzo==concierge, no leak, token manomesso rifiutato, prenota idempotente, dispatcher mai-crash).
Wishlist/fedeltà/deposito/coda/chatbot139 = SPENTI (non cablati: si collaudano quando si accendono).
PROSSIMO: (a) secondo deploy (fix #29 + guardie) al prossimo "pusha"; (b) nuova strategia del
fondatore "gradini G1-G2-G3 + comando di bombardamento" fornito da lui round per round.

**15 bug VERI chiusi** (prova end-to-end + test permanente + commit), tra cui a **perdita reale di denaro**:
rimborso admin che pagava ANCHE l'host, addebito Stripe sempre in EUR su annunci non-EUR, Credito
Fondatore riusabile all'infinito, cancellazione che coniava crediti, ledger tassa che sovra-contava i
rimborsati; + **IDOR/data-leak host** (metriche/export-CSV/calendario di annunci altrui o intera
piattaforma), recensioni finte senza pagare, annuncio sospeso ancora prenotabile, metriche host a €0,
trasparenza commissione fissa, export iCal cross-canale monco, record prenotazione incompleto. Dettaglio
completo (cosa era rotto, come, il fix, il test) in **`REGISTRO_INGEGNERIA.md`** (sezione 1).

**Due strumenti nuovi e permanenti nella suite:**
- 🧠 **`test_menti_invarianti.py`** — fuzzer "1000 menti" (idea del fondatore): agenti-mente con logiche
  diverse eseguono sequenze casuali sulla macchina reale; verifica invarianti globali (no overbooking,
  no doppio-payout, host mai pagato su rimborsati, escrow/tassa/conservazione, single-use credito).
- 🛡️ **`test_robustezza_fuzzing.py`** + **`test_concorrenza_denaro.py`** — nessun endpoint cade su input
  ostile; money-path race-safe sotto carico.

**Metodo "libro" (in corso)**: si tracciano i VIAGGI reali degli attori pagina-per-pagina, leggendo ogni
elemento visibile + tutti i componenti del motore dietro, e si SIMULA per verificare che ogni cosa VIVA e
passi le tappe giuste. GIÀ verificati vivi: ospite (ricerca→dettaglio→prenota→voucher), host
(registra→pubblica→incassa→approva), admin (arbitro/split/sospendi/cancella), spina del denaro
(Stripe→webhook→escrow→Connect), cancellazione→rimborso→storno. **Ripresa**: altri rami (su-richiesta,
contestazione→arbitro, pagamento tardivo). Vedi memory `core-auto-2026-07-16-collaudo`.

---

# ✅ RISOLTO — il sito è ONLINE con HTTPS (aggiornato 2026-07-10)

> `https://bookinvip.com` e `https://www.bookinvip.com` funzionano con il **lucchetto verde** 🔒.
> La lista d'attesa registra le email anche in HTTPS. Il certificato si **rinnova da solo**.

## 🎯 QUAL ERA IL VERO PROBLEMA (dopo giorni di caccia)
Il codice, il server e i dati erano SEMPRE stati a posto. Il vero problema era **uno solo**:
- Il sito girava **solo in HTTP (porta 80)**; la **porta 443 (HTTPS) era spenta** → i browser, che oggi
  pretendono l'HTTPS, non si connettevano e mostravano "errore" (e il vecchio service worker in cache
  faceva apparire "offline").
- **NON era**: né il codice, né la cache, né "Aruba vs Hostinger". I vecchi documenti che parlavano di
  **Aruba 89.46.65.6 erano SBAGLIATI**: quello è un server-fantasma con un Flask morto. Il dominio punta
  al **VPS Hostinger `76.13.44.167`** (`srv1781683.hstgr.cloud`), dove gira davvero l'app.

Perché l'HTTPS non era mai partito: (1) sul VPS c'è solo `docker-compose` **v1.29.2**, ma il file SSL e
lo script `init-letsencrypt.sh` usano i comandi della **v2** (`docker compose`) → davano errore; (2) il
certificato Let's Encrypt esisteva già in `/etc/letsencrypt` ma il file SSL lo cercava in `certbot/conf`.

## 🔧 COSA È STATO FATTO (2026-07-10, direttamente sul VPS)
1. In `docker-compose.casavip.yml`, servizio **nginx**, ora attivi (prima commentati):
   - `- "443:443"`
   - conf: `./deploy/nginx.casavip.ssl.conf:/etc/nginx/conf.d/default.conf:ro`
   - `- /etc/letsencrypt:/etc/letsencrypt:ro`   (il certificato vero)
   - `- ./certbot/www:/var/www/certbot:ro`      (per la sfida di rinnovo)
   - Backup del file originale: `docker-compose.casavip.yml.bak.*` nella stessa cartella.
2. Rinnovo automatico corretto per funzionare con nginx-in-Docker: in
   `/etc/letsencrypt/renewal/bookinvip.com.conf` cambiato `authenticator = nginx` → **`webroot`**
   (webroot = `/var/www/bookinvip/certbot/www`) + `renew_hook = docker exec casavip_nginx nginx -s reload`.
   Collaudato con `certbot renew --dry-run` → **success**. `certbot.timer` è enabled+active.

## 💾 BACKUP OFFSITE + RESTORE DA ZERO (contro il data-loss catastrofico) — 2026-07-18
> **Perché**: i backup di bordo (container `casavip_backup`, ogni 6h, 14 per DB) vivono sul
> disco del VPS. Se il disco muore / ransomware / cancello il volume: dati E backup spariscono
> insieme. Difesa: una copia **CIFRATA fuori macchina**, tirata dal PC (mai il VPS che spinge).
> **Scoperto quel giorno**: il backup aveva una LISTA FISSA e NON salvava `finanza.db` (il
> giornale contabile) + checkin/coda/split/geocache/poicache → ora fa **glob `*.db`** (salva
> tutto, sempre). Guardia: `test_backup_completo.py`.

### 1) FARE una copia offsite (dal PC, quando vuoi — ideale: ogni sera)
```bash
cd ~/Desktop/Core_Auto
BV_PASS='UNA-PASSPHRASE-LUNGA-E-SEGRETA' bash deploy/pull_offsite.sh
# -> crea ~/bookinvip-offsite/bookinvip-<data>.tar.gz.enc  (AES-256, verificato coi checksum)
```
> La **passphrase** è l'unica cosa che NON deve stare nel repo né sul VPS: scrivila dove tieni
> le password. Senza, la copia non si può decifrare (è il punto: nemmeno un ladro può).
> Requisiti PC: `ssh`, `openssl`, `tar` (rsync NON serve: c'è il ripiego tar-su-ssh).

### 2) RESTORE DA ZERO (server nuovo, disco morto — procedura idiota-proof)
**A. Ricostruisci i dati dalla copia offsite (sul PC):**
```bash
cd ~/Desktop/Core_Auto
BV_PASS='LA-STESSA-PASSPHRASE' bash deploy/restore_offsite.sh ~/bookinvip-offsite/bookinvip-<data>.tar.gz.enc ~/RESTORE
# verifica OGNI db (PRAGMA integrity_check) + la CATENA HASH del giornale.
# Se dice "GIORNALE MANOMESSO" o "RESTORE con N problemi": NON usare, prova un pacchetto più vecchio.
# Se dice "RESTORE OK": in ~/RESTORE hai tutti i .db pronti.
```
**B. Rimetti in piedi il server (su un VPS Ubuntu pulito):**
```bash
# 1. installa docker + docker-compose (v1.29.2) e git
apt update && apt install -y docker.io docker-compose git
# 2. prendi il codice (è su GitHub, mai perso)
git clone https://github.com/edilmax/Core_Auto.git /var/www/bookinvip && cd /var/www/bookinvip
# 3. ricrea il file dei segreti .env.casavip (chiavi Stripe da dashboard.stripe.com, vedi sotto)
#    e le env DB_* (DB_FINANZA=/data/finanza.db, DB_CHECKIN=..., ecc. — vedi main_casavip.py)
# 4. crea il volume dati e COPIA DENTRO i .db restaurati
docker volume create bookinvip_casavip_data
VOL=$(docker volume inspect --format '{{.Mountpoint}}' bookinvip_casavip_data)
scp ~/RESTORE/*.db root@<nuovo-vps>:$VOL/      # dal PC; oppure cp se già sul server
# 5. avvia (HTTPS: serve /etc/letsencrypt — rigenera con certbot se il dominio punta qui)
docker-compose -f docker-compose.casavip.yml build app
docker-compose -f docker-compose.casavip.yml up -d
# 6. verifica: curl -sS -o /dev/null -w "%{http_code}\n" https://bookinvip.com/api/health  -> 200
```
> **Obiettivo < 1 ora**: i passi 1-2 sono ~10 min, il 4 (copia dati) è secondi (i DB sono piccoli).
> Il collo di bottiglia vero è il DNS/certificato HTTPS. **Esercitazione fatta 2026-07-18**: pull
> reale (172 archivi, 51 checksum ok) + restore su ambiente isolato (17 DB integri) + prova col
> dente (giornale manomesso → beccato a `seq=2`, restore rifiutato). ⚠️ **DA fare col fondatore**:
> provare i passi B su un VPS di staging vero, cronometro alla mano (bus-factor: che funzioni
> anche per un tecnico che non conosce il progetto).

## 🧯 ZERO-KNOWLEDGE — per un tecnico che NON ha mai visto questo progetto
> Leggi questo se devi rimettere in piedi BookinVIP e non sai nulla del codice.
> **Cos'è**: un sito (Python stdlib dietro nginx, in Docker) su UN server Hostinger
> `76.13.44.167`, dominio `bookinvip.com`. I dati sono **file SQLite** in un volume Docker.
> Il codice è su GitHub (`edilmax/Core_Auto`, mai perso). I dati stanno **solo** nel volume
> + nelle **copie offsite cifrate** sul PC del proprietario.

### (a) DOVE stanno i dati — percorsi esatti (scoperta automatica di OGNI .db)
- Nel server, volume Docker montato come `/data` dentro i container. Sul disco del VPS:
  `/var/lib/docker/volumes/bookinvip_casavip_data/_data/`
  (trovalo sempre con: `docker volume inspect --format '{{.Mountpoint}}' bookinvip_casavip_data`)
- Lì dentro: **tutti i `*.db`** (17: catalogo, inventario, registro_host, accettazioni, payout,
  **finanza** = giornale contabile, garanzia, pendenti, tassa_comunale, viral, messaggi, domanda,
  checkin, coda, split, geocache, poicache) + la cartella `backup/` (snapshot .db.gz + .sha256).
  Il backup li scopre da solo (`*.db`): non c'è una lista da aggiornare.

### (b) DECIFRARE una copia offsite (sul PC)
```bash
# le copie sono ~/bookinvip-offsite/bookinvip-<data>.tar.gz.enc (AES-256).
# serve SOLO la passphrase scelta a suo tempo (NON è nel repo né sul server: chiedila al proprietario).
BV_PASS='LA-PASSPHRASE' bash deploy/restore_offsite.sh ~/bookinvip-offsite/bookinvip-<data>.tar.gz.enc ~/RESTORE
# -> verifica ogni checksum + PRAGMA integrity_check + CATENA HASH del giornale.
#    Se dice "GIORNALE MANOMESSO"/"RESTORE con N problemi" -> usa un pacchetto più vecchio.
#    Se dice "RESTORE OK" -> in ~/RESTORE ci sono tutti i .db pronti.
# (decrypt "a mano" senza lo script, se serve:)
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -in <pacchetto>.enc -out backup.tar.gz -pass env:BV_PASS
```

### (c) RIPRISTINO CRONOMETRATO (server nuovo Ubuntu, obiettivo < 1 ora)
```bash
# [~10 min] 1. strumenti
apt update && apt install -y docker.io docker-compose git python3
# [~2 min]  2. codice (da GitHub, mai perso)
git clone https://github.com/edilmax/Core_Auto.git /var/www/bookinvip && cd /var/www/bookinvip
# [~3 min]  3. segreti: ricrea /var/www/bookinvip/.env.casavip (chiavi Stripe da dashboard.stripe.com;
#            TELEGRAM_BOT_TOKEN/CHAT_ID; e le env DB_* -> vedi main_casavip.py). Vedi anche la sez. 🔑 ACCESSO.
# [~1 min]  4. volume + dati restaurati (dal punto b, dal PC):
docker volume create bookinvip_casavip_data
VOL=$(docker volume inspect --format '{{.Mountpoint}}' bookinvip_casavip_data)
scp ~/RESTORE/*.db root@<NUOVO-VPS>:$VOL/            # copia i 17 .db nel volume
# [~15 min] 5. HTTPS: punta il DNS di bookinvip.com al nuovo IP, poi certbot (vedi sez. RISOLTO HTTPS)
# [~5 min]  6. avvia
docker-compose -f docker-compose.casavip.yml build app
docker-compose -f docker-compose.casavip.yml up -d
# 7. VERIFICA: curl -sS -o /dev/null -w "%{http_code}\n" https://bookinvip.com/api/health   # -> 200
#    e la catena del giornale: python3 fase178_watchdog.py --dati $VOL --backup $VOL/backup --uptime skip
```
> Collo di bottiglia reale = DNS+certificato (passo 5). ⚠️ **DA fare col fondatore**: provarlo davvero
> su uno staging, cronometro alla mano (bus-factor: che funzioni per un estraneo, non solo sulla carta).

## 🩺 WATCHDOG (sistema nervoso) — installazione e uso
> Sorveglia salute e AVVISA su Telegram. Read-only, non tocca dati. **Due teste** (l'allarme non muore col server):
```bash
# SUL VPS (auto-diagnosi: catena hash + backup fresco + disco + uptime) — cron ogni 10 min:
( crontab -l 2>/dev/null; echo "*/10 * * * * cd /var/www/bookinvip && sh deploy/watchdog.sh >/dev/null 2>&1" ) | crontab -
# DAL PC (l'unico che vede "il server è morto") — quando il PC è acceso, o via Task Scheduler:
REMOTO=1 bash deploy/watchdog.sh    # legge Telegram da deploy/.watchdog.env (gitignored)
```
> Log persistente in `/data/watchdog.log`. Diagnosi on-demand: `GET /api/admin/diagnosi` (admin-key).
> Consigliato in più (gratis, 2 min): un uptime-monitor esterno (es. UptimeRobot) su `/api/health`.

## ▶️ COME AGGIORNARE IL SITO D'ORA IN POI (procedura SICURA — pattern "rm-first")
Dalla cartella del VPS `/var/www/bookinvip`:
```bash
git pull
docker-compose -f docker-compose.casavip.yml build app
docker-compose -f docker-compose.casavip.yml stop app backup
docker-compose -f docker-compose.casavip.yml rm -f app backup
docker-compose -f docker-compose.casavip.yml up -d
```
> ⚠️ **Se cambia la CONFIG NGINX** (`deploy/nginx.casavip*.conf`) NON basta `git pull` +
> `nginx -s reload`: **fallisce in silenzio**. Docker monta quel file come **singolo file, per
> inode**; `git pull` non lo modifica, lo **sostituisce** (nuovo inode) → il container resta
> agganciato al file VECCHIO. Serve **ricreare il container**:
> ```bash
> docker rm -f casavip_nginx && docker-compose -f docker-compose.casavip.yml up -d
> ```
> (Scoperto il 2026-07-15 aggiungendo la CSP: `nginx -t` diceva OK, il reload pure, ma dentro il
> container la direttiva non c'era. Verificare sempre col container, non col file sul VPS.)
>
> **Perché così:** il `build app` è OBBLIGATORIO se cambia il codice o `deploy/` (il frontend è COPIato
> dentro l'immagine: senza build, il sito resta quello vecchio). Lo `stop`+`rm -f` PRIMA dell'`up`
> evita il bug `KeyError: ContainerConfig` di `docker-compose` v1.29.2 (crasha quando RI-crea container
> con volumi). Solo documentazione cambiata → basta `git pull`.
> ✅ **Verificato 2026-07-15**: la config HTTPS (443 + `nginx.casavip.ssl.conf` + `/etc/letsencrypt` +
> `certbot/www`) è **committata su GitHub** e il VPS non ha modifiche locali (`git diff` vuoto) →
> l'infrastruttura è riproducibile. *(La vecchia nota "l'HTTPS vive solo nel working tree del VPS,
> `git reset --hard` lo cancella" era vera a luglio ma ora è SUPERATA.)*
> A lungo termine resta consigliato installare `docker compose` v2 (elimina i bug di v1.29.2).

## 📌 CONTROLLI RAPIDI (dal proprio PC)
```bash
curl -sS -o /dev/null -w "HTTP %{http_code} cert=%{ssl_verify_result}\n" https://bookinvip.com/   # atteso: HTTP 200 cert=0
curl -sS -X POST https://bookinvip.com/api/domanda -H 'Content-Type: application/json' -d '{"email":"a@b.com","citta":"roma"}'  # atteso: {"ok": true,...}
```

## 🧹 COSE MINORI (non urgenti)
- ~~Container `casavip_backup` risulta **unhealthy**~~ → ✅ **RISOLTO 2026-07-15** (commit `52a6888`):
  il container ereditava l'healthcheck dell'immagine app (porta 8080, dove non gira nessun server).
  Ora ha un healthcheck VERO: ultimo backup in `/data/backup/*.gz` più fresco di 7 ore.
  In prod risulta **healthy**; se torna rosso, i backup sono DAVVERO fermi (non ignorare).
- Server **fantasma Aruba `89.46.65.6`** (Flask/Werkzeug morto): non c'entra col sito. Se lo si paga, si
  può dismettere; se non lo si controlla, ignorarlo.

## 🔑 ACCESSO
- VPS: `ssh root@76.13.44.167` (Hostinger, Ubuntu 24.04). La chiave pubblica `edilmax` (id_ed25519) è
  installata in `/root/.ssh/authorized_keys`. Fallback sempre disponibile: **hPanel Hostinger → VPS →
  Terminale del browser** (root, senza password).
- Fonte di verità funzionalità: `STATO_FINALE.md`. Cose da fare prodotto: `COSE_DA_FARE.md`.
