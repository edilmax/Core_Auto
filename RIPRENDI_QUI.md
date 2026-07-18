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
> **PROSSIMO COMPARTIMENTO (attende VAI)**: ③ Clean Code / Technical Debt (funzioni con troppe
>   responsabilità o troppa indentazione → modulari e testabili in isolamento). Passo-2 opzionale
>   del comp.1: batchare anche il calendario (fase58). Regole ferme invariate (salvare ovunque, mai
>   email vera, deploy rm-first, suite intera prima del deploy). REGOLE FERME: dopo OGNI operazione finita salvare ovunque
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
