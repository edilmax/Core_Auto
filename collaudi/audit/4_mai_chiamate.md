# B19 — PASSAGGIO 4 · LE FUNZIONI SCRITTE E MAI CHIAMATE DA NESSUNO

> **Referto di misura, non lista di cose da fare.** Sola lettura: nessun file di prodotto è
> stato toccato, nessuna riparazione fatta, nessuna suite eseguita, nessun commit.
> Misurato il **2026-08-24**, su `HEAD = 584f0e9` (`git status --porcelain`: modificati
> `CLAUDE.md`, `RIPRENDI_QUI.md`, `deploy/index.html` + la cartella non tracciata
> `collaudi/audit/`; **nessun `fase*.py` toccato**).
> Perimetro: **metodi e funzioni definiti nel codice di produzione e senza un solo chiamante**
> fuori da sé e dai collaudi. Il modello è `fase131_payout_dashboard.py:332` `da_pagare()`,
> che due file danno per in uso — ed è confermato qui sotto.

---

## DENOMINATORE DICHIARATO

**Ciò che il codice di produzione contiene** (`Dockerfile.casavip:25-27`: `COPY main_casavip.py`,
`COPY fase*.py`, `COPY deploy`; `CMD python main_casavip.py`):

| grandezza | numero | come è stata misurata |
|---|---|---|
| moduli di produzione | **152** | `main_casavip.py` + 151 `fase*.py` |
| righe di produzione | **50.915** | conteggio righe sui 152 file |
| funzioni/metodi definiti (esclusi i `__dunder__`) | **2.092** | AST, `FunctionDef` + `AsyncFunctionDef` |
| definizioni con **zero riferimenti eseguibili** in produzione | **254** | AST: zero `Name` e zero `Attribute` con quel nome in tutti i 152 moduli |
| di queste, in moduli **vivi** (raggiungibili da `main_casavip.py`) | **117** | grafo degli import, import dinamici da stringa compresi |
| di queste, in moduli **mai raggiunti** | **137** | idem |
| **falsi positivi tolti a mano** (chiamati dal framework) | **5** | `do_HEAD`, `do_OPTIONS`, `do_POST`, `log_message`, `redirect_request` in `fase83_server.py`: li chiama `BaseHTTPRequestHandler`/`urllib`, non il nostro codice |
| **RISULTATO — mai chiamate, in moduli vivi** | **112** | 117 − 5 |
| di queste, **mai nominate nemmeno nei collaudi** | **84** | ricerca del nome in tutto `collaudi/` e `collaudo/` |

⛔ **Il numero grosso però non è 112.** Sopra ci sono **59 moduli interi mai raggiunti** da
`main_casavip.py`: **12.055 righe** (il **23,7%** di tutto il codice di produzione) e **651
funzioni** che, chiamate o no fra di loro, in produzione **non partono mai**. Sono la Sezione D.

### Come è stata fatta la misura, e con due attrezzi diversi

1. **Attrezzo 1 (AST).** Scanner Python scritto per questo passaggio (in sola lettura, nella
   cartella temporanea di sessione, **non** in repository): parsa i 152 moduli, raccoglie ogni
   `def`, e conta per ogni nome quante volte compare come `Name` o `Attribute` in **tutto** il
   codice di produzione. Zero = nessun chiamante sintattico.
2. **Attrezzo 2 (testo, indipendente dall'AST).** Controprova con espressione regolare: cerca la
   **forma di chiamata** `nome(` / `.nome(` in tutte le 50.915 righe, togliendo la riga della
   `def` e i commenti. Serve a non fidarsi di un solo strumento (regola della batteria: *un
   collaudo non usa mai l'attrezzo vero*).
   **Esito: 10 discordanze su 254, tutte e 10 aperte a mano e tutte e 10 in docstring** (es.
   `fase78_sleep_guarantee.py:15` nomina `paga(` dentro la descrizione del modulo,
   `fase147_tassa_comunale.py:7` nomina `visibile(`). **Zero chiamanti veri trovati dal secondo
   attrezzo e persi dal primo.**
3. **Dispatch dinamico**, come chiede la regola del passaggio: per ognuno dei 254 candidati è
   stato cercato il nome anche **dentro le stringhe** di produzione (`getattr`, tabelle di rotte,
   `importlib`) e dentro `deploy/*.html|js|json`. Le rotte HTTP vere di questo prodotto **non**
   passano da nome dinamico: `fase83_server.py` le smista con `if metodo == ... and path == ...`
   e chiama il metodo per nome scritto, quindi un metodo-rotta chiamato compare sempre nell'AST.

---

## LA FORMA DI FAMIGLIA — tre meccanismi producono quasi tutto

⛔ **(1) COSTRUITO E COLLEGATO NON VUOL DIRE CHIAMATO.** Quattro motori vengono **costruiti
all'avvio** e appesi al sistema in `fase81_bootstrap_casavip.py:533-535` e `:383-386` — coda
intelligente, turnover, digital twin, deposito cauzionale — e poi **l'unico ingresso del prodotto
non li nomina mai**. Misurato con `grep -ic` su `fase83_server.py` (11.245 righe):
`turnover` → **0 occorrenze**, `twin` → **0**, `cauzion` → **0**, `coda` → 6 occorrenze **tutte in
prosa** (righe 3523, 4513, 6657, 8121, 8360, 9292). È la regola #23 «COSTRUITO ≠ COLLEGATO»
misurata da fuori: qui il collegamento c'è, manca la **chiamata**.

⛔ **(2) LA SECONDA COPIA È QUELLA CHE MUORE — e nessuno se ne accorge.** Dove la stessa cosa è
scritta due volte, il prodotto ne usa una e l'altra resta lì, identica di aspetto e morta di
fatto: `commissione_bps_lancio` contro `stato_scaglione` (rampa commissioni),
`crea_provider_stripe_connect` contro `crea_provider_connect` (conto Stripe dell'host),
`KYCHost.avvia` contro `stripe_identity_crea` + `registra_avvio`, `storna_nota` contro
`storna_penale`/`storna_prenotazione`, `guardia_prenotazione` contro l'import diretto di
`i3_prova_prima_del_commit`. **Chi legge il codice per capire cosa succede può leggere la copia
sbagliata**: è esattamente il modo in cui `da_pagare` è finito descritto come vivo in due file.

⛔ **(3) IL PRODOTTO GIRA SU STDLIB PURA, MA IN CASA C'È UNA SECONDA APPLICAZIONE FLASK.**
`Dockerfile.casavip:1-3` dichiara «PURA STDLIB Python (zero dipendenze): nessuna installazione di
pacchetti». `requirements.txt:1` chiede `flask==3.0.0`, che **nell'immagine non viene mai
installato**. In produzione ci sono **29 rotte decorate `@app.route`/`@target.route`** e **7
funzioni `registra_*` che le installerebbero**: di queste 7, **5 non hanno un solo chiamante** e le
2 restanti (`registra_gateway`, `registra_rotte`, `registra_pannello`, `registra_metriche`) sono
chiamate **solo da moduli a loro volta mai raggiunti**. È la Sezione E.

---

## 🔴 GRAVI — 22 · toccano soldi, tasse o guardie

| dove | funzione | righe | stato |
|---|---|---|---|
| `fase199_invarianti.py:146` | `guardia_prenotazione()` | 15 | mai nominata |

**La guardia pre-scrittura degli invarianti non è la guardia installata.** Il docstring dice
«*Da chiamare PRIMA di confermare/scrivere una prenotazione: se creerebbe una violazione
(I1/I2/I3) solleva `ViolazioneInvariante` → l'operazione NON tocca il DB*». Nessuno la chiama. Il
server, a `fase83_server.py:5375`, importa **due invarianti su quattro**:
`i3_prova_prima_del_commit` e `i4_denaro_non_negativo`. Quindi **I1 (doppia conferma =
sovrapposizione sulla stessa unità) e I2 (bilancio dei pagamenti) non sono controllati prima di
scrivere.** Il commento a `:5369` annuncia «BLOCCO pre-commit su violazione MATEMATICA»: il blocco
c'è, ma su metà degli invarianti che la funzione morta avrebbe controllato.

| dove | funzione | righe | stato |
|---|---|---|---|
| `fase149_deposito_cauzionale.py:72` | `DepositoCauzionale.autorizza()` | 18 | mai nominata |
| `fase149_deposito_cauzionale.py:95` | `DepositoCauzionale.cattura_danno()` | 36 | collaudi: 1 |

**La cauzione ha un archivio durevole e non ci entrerà mai una riga.** Il bootstrap la collega
apposta (`fase81_bootstrap_casavip.py:379-386`, commento: «*era COSTRUITO ma non raggiungibile…
Qui viene collegato al sistema con archivio DUREVOLE (custodisce hold su carte = denaro)*») e
chiama `inizializza_schema()`. Ma **nessuno chiama `autorizza`**, che è l'unica funzione che
scrive nella tabella `cauzione`. Il commento del bootstrap dichiara scoperto solo il passaggio al
PSP («*`capture`/`release` restano NON iniettati*»): la misura dice che manca un pezzo prima,
cioè **l'autorizzazione stessa**. Tabella creata a ogni avvio, sempre vuota.

| dove | funzione | righe | stato |
|---|---|---|---|
| `fase98_policy_commissione.py:149` | `e_fondatore()` | 3 | mai nominata |
| `fase98_policy_commissione.py:80` | `commissione_bps_lancio()` | 20 | collaudi: 1 |
| `fase98_policy_commissione.py:182` | `fattura_startup_cents()` | 7 | mai nominata |

**Il «Credito Fondatore» non ha un chiamante, e la soglia fiscale non la calcola nessuno.**
`e_fondatore(numero_host)` — l'unica funzione che risponde «questo host è nella classe
fondatrice?» — **non è chiamata da nessuna parte.** È la controprova, dal lato del codice, di
quello che il **passaggio 2** aveva misurato dal lato dei testi (host n.1 e n.5000 pagano
identico). `commissione_bps_lancio` è la rampa 0% → 8% → 10%: è **la copia morta**, perché il
prodotto passa da `stato_scaglione` (`fase83_server.py:3551, 3864, 7350`), che ricalcola la stessa
rampa. `fattura_startup_cents` è dichiarata «*MODULO 3 (tutela forfettario): serve a calcolare il
consumo della soglia 85k*»: **nessuno la chiama, quindi il consumo della soglia degli 85.000 € non
è calcolato da nessuna parte.**

| dove | funzione | righe | stato |
|---|---|---|---|
| `fase99_multicurrency.py:116` | `converti()` | 35 | mai nominata |
| `fase99_multicurrency.py:103` | `ripartisci_pagamento()` | 11 | mai nominata |
| `fase99_multicurrency.py:89` | `denaro_da_maggiore()` | 12 | mai nominata |
| `fase99_multicurrency.py:72` | `Denaro.scala_bps()` | 3 | mai nominata |

**Del motore multivaluta il prodotto usa il tipo di dato, non le regole.** Di `fase99` sono vivi
solo `Denaro` e `esponente` (importati in `fase83_server.py:528, 7559`, `fase77:36`,
`fase59:425`, `fase86:557`, `fase119`, `fase139`, `fase145`, `fase173`). Le **quattro funzioni che
decidono i soldi** — conversione anti-DCC, ripartizione Like-for-Like, arrotondamento in bps —
non sono chiamate da nessuno. Il modulo si dichiara «Like-for-Like (`ripartisci_pagamento`)» a
`fase99:9` e «Conversione TRASPARENTE (`converti`, anti-DCC)» a `:13`: **due promesse di modulo
senza chiamante.**

| dove | funzione | righe | stato |
|---|---|---|---|
| `fase100_dac7.py:109` | `RegistroDAC7.registra_prenotazione()` | 7 | mai nominata |
| `fase100_dac7.py:131` | `RegistroDAC7.payout_consentito()` | 2 | mai nominata |
| `fase100_dac7.py:128` | `RegistroDAC7.visibile()` | 2 | collaudi: 9 |
| `fase100_dac7.py:135` | `crea_registro_dac7()` | 2 | mai nominata |

**Il contatore DAC7 non viene mai incrementato.** Il server usa **solo** la funzione pura
`valuta_dac7` (`fase83_server.py:3185, 3260, 6049`), mai la classe `RegistroDAC7`, che non viene
nemmeno costruita (`crea_registro_dac7` senza chiamanti). Quindi `registra_prenotazione`, che è
**l'unico scrittore** dei contatori «prenotazioni» e «ricavi» per host, non gira: chi decide se
bloccare un payout per DAC7 legge numeri che **quel registro non ha mai scritto**.

| dove | funzione | righe | stato |
|---|---|---|---|
| `fase147_tassa_comunale.py:96` | `TassaComunale.imposta_regola()` | 14 | mai nominata |
| `fase147_tassa_comunale.py:184` | `TassaComunale.totale_riscosso()` | 8 | mai nominata |

**Nessuno può inserire la regola di un comune, e nessuno legge quanto è stato riscosso.**
`imposta_regola` è l'unico ingresso del registro per comune. Non è chiamata: il registro resta
vuoto, e il ripiego documentato in B18 («comune ignoto → 0», `fase147:124`) diventa **la regola
generale, non l'eccezione**. `totale_riscosso` è l'unica lettura aggregata della tassa incassata:
nessuno la chiama, quindi non esiste un punto dove si veda quanto si deve ai comuni.

| dove | funzione | righe | stato |
|---|---|---|---|
| `fase177_financial_controller.py:585` | `FinancialController.storna_nota()` | 26 | mai nominata |
| `fase65_split_payment.py:273` | `GestoreSplit.ridistribuisci_mancante()` | 14 | mai nominata |
| `fase131_payout_dashboard.py:332` | `PayoutDashboard.da_pagare()` | 3 | collaudi: 1 |

`storna_nota` è **il terzo storno** del sistema, e l'unico morto: il prodotto usa `storna_penale`
(`fase83_server.py:2994`) e `storna_prenotazione` (`:5947`). Chi legge «storno» nel controller
finanziario può leggere la funzione che non gira.
`ridistribuisci_mancante` è la regola che rimette in gioco la quota di chi, in un pagamento
diviso, non ha pagato: mai chiamata.
`da_pagare` è **l'esempio con cui è nato questo passaggio**, e la misura lo conferma: zero
chiamanti nel prodotto, **11 menzioni in prosa** che lo danno per vivo
(`fase131:53, 88, 315`, `fase177:1048, 1050, 1058, 1094, 1102`, `fase83_server.py:2974, 4854,
6236, 6623, 6820`). Fra queste, `fase177:1048` descrive il passo 3 dello storno penale come
«*riga payout 'maturato' visibile in `da_pagare` per il bonifico MANUALE del fondatore*»: la riga
di payout viene scritta davvero, ma **la funzione che la mostrerebbe non la chiama nessuno**.

| dove | funzione | righe | stato |
|---|---|---|---|
| `fase101_stripe_connect.py:95` | `crea_provider_stripe_connect()` | 7 | mai nominata |

**Due fabbriche per lo stesso conto Stripe dell'host, e quella viva è l'altra.** Il prodotto usa
`crea_provider_connect` (`fase101:253`, chiamata da `fase81_bootstrap_casavip.py:229`). Conta
perché **B18 punto 1** dice che `country` non viene mai passato quando apriamo il conto: la
riparazione va fatta sul ramo vivo, e la fabbrica morta è il posto dove è facile farla per sbaglio.

| dove | funzione | righe | stato |
|---|---|---|---|
| `fase81_bootstrap_casavip.py:169` | `SistemaCasaVIP.money_path_pronto` (`@property`) | 3 | collaudi: 1 |

**La proprietà che risponde «il percorso dei soldi è pronto?» non la legge nessuno — e quello che
si legge davvero è una costante.** La proprietà calcola `self.concierge is not None`. Nessuno la
legge. Quello che il prodotto espone e che i collaudi controllano
(`test_avvio_main.py:87`, `test_deploy_config.py:155`) è **la chiave del dizionario**
`report["money_path_pronto"]`, scritta a `fase81_bootstrap_casavip.py:609` come **`True`
letterale**, senza guardare niente. È la forma «*«non è nullo» non è una guardia*» applicata a un
verde: la risposta è sempre sì perché è scritta a mano.

| dove | funzione | righe | stato |
|---|---|---|---|
| `fase83_server.py:385` | `_istante_fine_tutela()` | 12 | mai nominata |

**Il confine delle 24 ore di tutela è calcolato da una funzione che nessuno chiama.** Sta dentro
il file vivo, accanto alla sua gemella (che invece è usata a `:443`), con il docstring «*L'istante
entro cui la tutela deve valere per CHIUNQUE: le 24 ore contate dall'ultimo check-in possibile al
mondo*». Il ripensamento è già una decisione presa (48 ore, e in UE non dobbiamo niente): il fatto
qui misurato è che **il codice che calcola quel confine non entra in nessuna decisione**.

---

## 🟠 MEDI — 68 · funzionalità costruite, collegate, e mai chiamate

### I quattro motori accesi all'avvio che il server non nomina mai

`fase81_bootstrap_casavip.py:533-535` costruisce coda, turnover e digital twin; `:383-386` il
deposito cauzionale (già sopra fra i gravi). ⚠️ Due dei tre nascono su `":memory:"`
(`fase81:534-535`): anche se qualcuno li chiamasse, **perderebbero tutto a ogni riavvio**.

| dove | funzione | righe | stato |
|---|---|---|---|
| `fase67_coda_intelligente.py:192` | `GestoreCoda.iscrivi()` | 35 | mai nominata |
| `fase67_coda_intelligente.py:285` | `GestoreCoda.libera()` | 33 | collaudi: 14 |
| `fase67_coda_intelligente.py:404` | `GestoreCoda.converti_voucher()` | 26 | mai nominata |
| `fase67_coda_intelligente.py:257` | `GestoreCoda.rinuncia()` | 26 | collaudi: 4 |
| `fase67_coda_intelligente.py:431` | `GestoreCoda.stato_coda()` | 16 | mai nominata |
| `fase67_coda_intelligente.py:379` | `GestoreCoda.scadi_offerte()` | 16 | mai nominata |
| `fase67_coda_intelligente.py:152` | `GestoreCoda.registra_liberazione()` | 15 | mai nominata |
| `fase67_coda_intelligente.py:181` | `GestoreCoda.valuta_iscrizione()` | 9 | mai nominata |
| `fase67_coda_intelligente.py:396` | `GestoreCoda.prezzo_esclusivo()` | 7 | mai nominata |

**9 metodi pubblici su 13** della classe. ⚠️ `fase81:81` avverte che la coda «*custodisce DEPOSITI
(denaro): in prod va su FILE*»: nessun deposito ci entrerà, perché `iscrivi` — l'unico che li
prende — non ha chiamanti.

| dove | funzione | righe | stato |
|---|---|---|---|
| `fase70_turnover.py:123` | `GestoreTurnover.crea_turnover()` | 44 | mai nominata |
| `fase70_turnover.py:175` | `GestoreTurnover.completa()` | 31 | collaudi: 6 |
| `fase70_turnover.py:267` | `GestoreTurnover.segnala_ritardi()` | 17 | mai nominata |
| `fase70_turnover.py:237` | `GestoreTurnover.agibile()` | 14 | mai nominata |
| `fase70_turnover.py:285` | `GestoreTurnover.stato_turnover()` | 8 | mai nominata |
| `fase70_turnover.py:169` | `GestoreTurnover.assegna()` | 5 | collaudi: 5 |
| `fase72_digital_twin.py:157` | `DigitalTwin.predici_guasti()` | 32 | mai nominata |
| `fase72_digital_twin.py:220` | `DigitalTwin.report_soggiorno()` | 21 | mai nominata |
| `fase72_digital_twin.py:111` | `DigitalTwin.registra_lettura()` | 19 | mai nominata |
| `fase72_digital_twin.py:205` | `DigitalTwin.pronto_per_arrivo()` | 14 | mai nominata |

**6 metodi su 8** (turnover) e **4 su 7** (digital twin), con `grep -ic turnover` e `grep -ic twin`
su `fase83_server.py` = **0 e 0**.

### Motori del soggiorno e del prezzo, costruiti e mai interrogati

| dove | funzione | righe | stato |
|---|---|---|---|
| `fase62_predictive_noshow.py:110` | `StoricoPresenze.registra_esito()` | 30 | mai nominata |
| `fase62_predictive_noshow.py:203` | `GestoreNoShow.piano_compensazione()` | 27 | mai nominata |
| `fase62_predictive_noshow.py:186` | `GestoreNoShow.applica_a_inventario()` | 16 | mai nominata |
| `fase78_sleep_guarantee.py:88` | `SleepGuaranteeEngine.valuta_garanzia()` | 16 | mai nominata |
| `fase79_dichiarazione.py:109` | `DichiarazioneEngine.dichiara()` | 23 | collaudi: 78 |
| `fase79_dichiarazione.py:133` | `DichiarazioneEngine.ritira()` | 9 | mai nominata |
| `fase79_dichiarazione.py:143` | `DichiarazioneEngine.dichiarazioni_attive()` | 10 | mai nominata |
| `fase161_domanda_allarme.py:64` | `AllarmeDomanda.in_allarme()` | 2 | mai nominata |
| `fase127_checkin_digitale.py:174` | `CheckinDigitale.sblocca()` | 10 | collaudi: 4 |
| `fase113_messaggistica.py:201` | `Messaggistica.segna_letti()` | 15 | mai nominata |

⚠️ `DichiarazioneEngine.dichiara()` è **il metodo principale** del motore dichiarazioni: **78
menzioni nei collaudi, zero chiamanti in produzione.** È il caso peggiore per una batteria: il
collaudo verde misura una funzione che il prodotto non esegue mai.
⚠️ `CheckinDigitale.sblocca()` è la funzione che **apre la serratura**: nessun chiamante.
⚠️ `Messaggistica.segna_letti()`: i messaggi non vengono mai segnati come letti.

### Divisione del conto, calendari, geo, iCal, KYC, blog

| dove | funzione | righe | stato |
|---|---|---|---|
| `fase133_split_quote_uguali.py:95` | `SplitQuoteUguali.crea_gruppo()` | 30 | mai nominata |
| `fase133_split_quote_uguali.py:126` | `SplitQuoteUguali.paga()` | 12 | collaudi: 66 |
| `fase133_split_quote_uguali.py:159` | `crea_split_quote()` | 5 | collaudi: 1 |
| `fase121_geo_ricerca.py:53` | `cerca_vicini()` | 19 | mai nominata |
| `fase121_geo_ricerca.py:74` | `cluster_griglia()` | 17 | mai nominata |
| `fase121_geo_ricerca.py:93` | `geojson()` | 14 | mai nominata |
| `fase119_calendario_prezzi.py:131` | `calendario_html()` | 15 | mai nominata |
| `fase135_ical_bidirezionale.py:72` | `SyncBidirezionale.importa()` | 6 | collaudi: 17 |
| `fase135_ical_bidirezionale.py:69` | `SyncBidirezionale.esporta()` | 2 | collaudi: 1 |
| `fase135_ical_bidirezionale.py:80` | `crea_sync_bidirezionale()` | 2 | mai nominata |
| `fase143_kyc_host.py:97` | `KYCHost.avvia()` | 15 | collaudi: 5 |
| `fase143_kyc_host.py:76` | `KYCHost.verificato()` | 2 | collaudi: 21 |
| `fase198_blog.py:407` | `url_blog()` | 8 | mai nominata |
| `fase77_portability.py:234` | `importa()` | 85 | collaudi: 17 |
| `fase187_fuso_orario.py:106` | `normalizza()` | 6 | collaudi: 1 |

⚠️ `fase133`: del modulo è viva **solo** la funzione pura `riparti_uguale`
(`fase83_server.py:7443`); **la classe con lo stato non viene mai costruita**. Conferma
indipendente di quanto era già stato misurato («~9 righe vive su 142»).
⚠️ `fase135`: **classe intera morta, 2 metodi su 2.** Il sincronismo iCal bidirezionale non parte.
⚠️ `KYCHost.avvia` è la copia morta: il server fa la stessa cosa a mano con
`stripe_identity_crea` + `kyc.registra_avvio` (`fase83_server.py:2745-2751`). `verificato()` è
l'unico modo pulito per chiedere «questo host è verificato?»: il server confronta la stringa
in linea (`fase83_server.py:2743`, `:2775`).

### Vetrina, canali, notifiche, marketing, dimostrazioni formali

| dove | funzione | righe | stato |
|---|---|---|---|
| `fase199_invarianti.py:364` | `dimostra_transizioni()` | **194** | mai nominata |
| `fase199_invarianti.py:217` | `dimostra_formalmente()` | 64 | collaudi: 3 |
| `fase199_invarianti.py:163` | `verifica_stato()` | 12 | collaudi: 2 |
| `fase57_vetrina.py:943` | `CatalogoVetrina.slug_lastmod_pubblicati()` | 18 | mai nominata |
| `fase57_vetrina.py:962` | `CatalogoVetrina.citta_pubblicate()` | 17 | mai nominata |
| `fase57_vetrina.py:996` | `CatalogoVetrina.tutti_alloggi()` | 16 | mai nominata |
| `fase58_channel_manager.py:788` | `ChannelManager.applica_comando()` | 21 | mai nominata |
| `fase58_channel_manager.py:779` | `ChannelManager.registra_evento_esterno()` | 7 | mai nominata |
| `fase89_jurisdiction_outreach.py:260` | `componi_email_prima_roma()` | 32 | mai nominata |
| `fase89_jurisdiction_outreach.py:166` | `crea_fonte_api()` | 4 | mai nominata |
| `fase90_marketing.py:281` | `MotoreMarketing.invia_email_campagna()` | 15 | mai nominata |
| `fase91_canali_social.py:95` | `CanaleMetaGraph.pubblica_instagram()` | 18 | mai nominata |
| `fase95_outreach_email.py:127` | `adatta_invio_email()` | 15 | mai nominata |
| `fase95_outreach_email.py:144` | `crea_motore_outreach_durevole()` | 8 | mai nominata |
| `fase64_smartpass.py:164` | `costruisci_pass_wallet()` | 14 | mai nominata |
| `fase64_smartpass.py:180` | `crea_emettitore_pass()` | 2 | mai nominata |
| `fase64_smartpass.py:184` | `crea_verificatore_pass()` | 2 | mai nominata |
| `fase61_localizzazione.py:181` | `crea_notificatore_localizzato()` | 21 | mai nominata |
| `fase61_localizzazione.py:174` | `tagga_contenuto()` | 5 | mai nominata |
| `fase177_financial_controller.py:506` | `FinancialController.esporta_tutti()` | 17 | collaudi: 1 |
| `fase177_financial_controller.py:482` | `FinancialController.conta_movimenti()` | 7 | mai nominata |
| `fase80_sentinel.py:272` | `crea_catena()` | 5 | mai nominata |
| `fase80_sentinel.py:153` | `Sentinel.aggiorna_baseline()` | 3 | mai nominata |
| `fase60_mcp_server.py:245` | `ServerMCP.servi_stdio()` | 10 | mai nominata |

⚠️ `dimostra_transizioni()` sono **194 righe di dimostrazione** che **nessuno esegue, nemmeno un
collaudo**. `componi_email_prima_roma()` è l'email per il primo host di Roma — il prossimo passo
di business dichiarato — e non ha chiamanti. `esporta_tutti()` è l'estratto contabile certificato
per il Centro Fiscale.

---

## 🟡 MINORI — 16 · involucri sottili e fabbriche di connettori spenti

| dove | funzione | righe | perché è minore |
|---|---|---|---|
| `fase163_accettazioni.py:358` | `testo_contratto()` | 2 | involucro: il server serve il contratto con `documento_corrente()` (`fase83_server.py:8436`), che fa la stessa cosa in linea (`fase163:369-381`) — **il ripiego sull'inglese resta attivo** |
| `fase163_accettazioni.py:341` | `hash_di()` | 2 | involucro su `doc_sha256`/`privacy_sha256`, entrambi usati direttamente |
| `fase95_outreach_email.py:79` | `StoreOptOut.contiene()` | 2 | duplicato d'interfaccia |
| `fase95_outreach_email.py:97` | `StoreOptOutMemoria.contiene()` | 2 | duplicato d'interfaccia |
| `fase87_stripe_webhook.py:86` | `firma_di_test()` | 5 | **aiuto di collaudo spedito dentro l'immagine di produzione** (28 usi nei collaudi, 0 nel prodotto) |
| `fase197_canale_nostr.py:122` | `schnorr_verify()` | 14 | si firma, non si verifica mai |
| `fase106_dynamic_pricing.py:95` | `crea_politica_prezzo()` | 2 | fabbrica mai invocata |
| `fase111_cancellazione.py:82` | `crea_politica_cancellazione()` | 3 | fabbrica mai invocata |
| `fase66_tassa_soggiorno.py:247` | `crea_registro_tasse()` | 2 | fabbrica mai invocata |
| `fase165_adattatori_esterni.py:256` | `crea_pool_immagine_da_env()` | 10 | connettore dormiente |
| `fase165_adattatori_esterni.py:268` | `crea_youtube_da_env()` | 11 | connettore dormiente |
| `fase193_canale_mastodon.py:71` | `crea_canale_mastodon_da_env()` | 7 | connettore dormiente |
| `fase194_canale_bluesky.py:82` | `crea_canale_bluesky_da_env()` | 7 | connettore dormiente |
| `fase195_canale_reddit.py:86` | `crea_canale_reddit_da_env()` | 11 | connettore dormiente |
| `fase197_canale_nostr.py:281` | `crea_canale_nostr_da_env()` | 13 | connettore dormiente |
| `fase74_sensory_engine.py:110` | `SensoryEngine.badge()` | 6 | il badge lo compone il front-end |

⚠️ Le sei fabbriche `crea_*_da_env` sono la forma «*si accende con la variabile d'ambiente*»:
**nessuna variabile le accende, perché nessuno le chiama.**

---

## 🔵 SEZIONE E — 6 funzioni di un'applicazione Flask che nell'immagine non esiste

| dove | funzione | righe | stato |
|---|---|---|---|
| `fase57_vetrina.py:1205` | `registra_vetrina()` | 35 | mai nominata |
| `fase57_vetrina.py:1212` | `_lista()` (`@target.route "/catalogo"`) | 21 | mai nominata |
| `fase59_concierge.py:654` | `registra_concierge()` | 22 | mai nominata |
| `fase59_concierge.py:659` | `_manifest()` (`@target.route`) | 2 | mai nominata |
| `fase59_concierge.py:663` | `_search()` (`@target.route`) | 3 | mai nominata |
| `fase59_concierge.py:668` | `_quote()` (`@target.route`) | 3 | collaudi: 19 |

`registra_vetrina` installerebbe `GET /catalogo` e `GET /catalogo/<slug>`; `registra_concierge`
installerebbe manifest, ricerca e preventivo. Nessuna delle due ha un chiamante — misurato con
`grep` su tutti i `.py` di produzione: **0 riferimenti fuori dalla propria `def`.** Fanno
`from flask import …` (`fase57:1209`, `fase59:656`), e Flask **non è installato nell'immagine**
(`Dockerfile.casavip:1-3, 25-27`: nessun `pip install`). Le altre 5 funzioni `registra_*`
(`fase28:165`, `fase36:30`, `fase41:64`, `fase42:194`, `fase56:297`) stanno tutte in moduli della
Sezione D, cioè in moduli che non partono comunque.

---

## ⚫ SEZIONE D — 59 moduli interi mai raggiunti: 12.055 righe, 651 funzioni

Grafo degli import a partire da `main_casavip.py` (import statici + import dinamici scritti come
stringa). **93 moduli su 152 sono raggiungibili; 59 no.** Dentro quei 59 ci sono **651
definizioni**: chiamate o no fra di loro, **in produzione non ne parte nessuna**. Sono il
**23,7% di tutto il codice di produzione**.

⛔ **Attenzione a come si legge questo numero.** *Spento ≠ morto*: alcuni di questi moduli sono
spenti da una variabile d'ambiente o appartengono al vecchio impianto (Tavola VIP / agente
booking) e potrebbero essere riaccesi. La misura dice **una cosa sola e precisa**: oggi, con
l'ingresso `main_casavip.py` dichiarato dal `Dockerfile`, non c'è nessuna catena di import che li
raggiunga. ⛔ **Non usare questo elenco per decidere cosa cancellare senza rimisurare.**

I 20 più grossi (righe · funzioni):

| modulo | righe | funzioni |
|---|---|---|
| `fase13_protocollo_finale.py` | 973 | 45 |
| `fase16_outbox.py` | 696 | 36 |
| `fase34_prenotazioni.py` | 438 | 17 |
| `fase15_idempotency.py` | 437 | 15 |
| `fase43_commissione.py` | 370 | 26 |
| `fase200_campagna_persuasiva.py` | 350 | 12 |
| `fase56_gateway_tavoli.py` | 312 | 14 |
| `fase30_llm.py` | 282 | 15 |
| `fase35_pagamenti.py` | 280 | 18 |
| `fase52_persistenza_metriche.py` | 245 | 12 |
| `fase23_datastore.py` | 241 | 30 |
| `fase42_observability.py` | 232 | 17 |
| `fase25_brain.py` | 232 | 13 |
| `fase189_price_alerts.py` | 224 | 18 |
| `fase68_niche_profiler.py` | 212 | 10 |
| `fase33_persistenza.py` | 211 | 9 |
| `fase53_healthguard.py` | 200 | 14 |
| `fase49_ponte_booking.py` | 199 | 8 |
| `fase37_notifiche.py` | 197 | 10 |
| `fase26_ricerca.py` | 197 | 7 |

Gli altri 39: `fase190_rate_parity` (185) · `fase71_commitment` (185) · `fase139_chatbot_guest`
(183) · `fase36_booking_api` (182) · `fase40_agente_booking` (181) · `fase28_gateway` (176) ·
`fase41_admin_panel` (174) · `fase55_bootstrap` (174) · `fase154_giurisdizioni_marketing` (170) ·
`fase137_fedelta_guest` (169) · `fase24_channels` (163) · `fase54_loop` (160) ·
`fase141_onboarding_wizard` (158) · `fase31_conversazione` (158) · `fase73_firma_agile` (157) ·
`fase46_esploratore` (155) · `fase51_scheduler` (155) · `fase123_web_push` (153) ·
`fase38_backup` (151) · `fase29_backpressure` (149) · `fase44_prezzo` (147) ·
`fase48_advertising` (146) · `fase32_governatore` (138) · `fase50_orchestratore` (136) ·
`fase45_pricing` (133) · `fase47_venditore` (132) · `fase104_gateway_asia` (129) ·
`fase117_wishlist` (128) · `fase196_video_ai` (128) · `fase27_proposte` (123) ·
`fase103_reverse_charge` (120) · `fase96_fonte_osm` (111) · `fase17_money` (104) ·
`fase39_whatsapp` (102) · `fase107_traduzione_annunci` (94) · `fase105_identity_gate` (92) ·
`fase151_alloggiati_web` (86) · `fase129_traduzione_recensioni` (73) ·
`fase102_motore_autonomo` (67).

🔴 **Le tre voci di questo elenco che pesano più delle altre**, perché il loro nome dice che
riguardano soldi o obblighi: **`fase17_money`** (104 righe) e **`fase15_idempotency`** (437) —
già noti come «risultavano ACCESI» per una riga sbagliata, e qui misurati **spenti** — e
**`fase103_reverse_charge`** (120 righe, IVA da versare in reverse charge).
Insieme a loro: **`fase137_fedelta_guest`** (crediti fedeltà dell'ospite: `accredita` e
`riscatta` sono denaro), **`fase190_rate_parity`**, **`fase154_giurisdizioni_marketing`**
(l'unica tabella per nazione che abbiamo, citata in B18 punto 5) e **`fase151_alloggiati_web`**
(obbligo di legge italiano: comunicazione alloggiati alla Questura).

---

## COSA È RIMASTO FUORI DA QUESTA MISURA (D18 punto 3)

1. **Non ho contato le funzioni morte *dentro* i 59 moduli irraggiungibili.** Lì il criterio
   «zero chiamanti» perde senso (si chiamano fra loro in un impianto che non parte): ho dato il
   totale delle definizioni (651) e le righe, non l'elenco funzione per funzione. Le 137
   definizioni con zero riferimenti anche *interni* sono nel file di lavoro, non qui.
2. **Non ho verificato se i 93 moduli «raggiungibili» partano davvero.** Molti sono raggiunti da
   un `import` **dentro una funzione** (`fase83_server.py` ne fa decine): se quella funzione non
   gira mai, il modulo è vivo sul grafo e morto nei fatti. **Il numero 93 è un massimo, non una
   misura di ciò che gira.**
3. **Non ho letto a mano tutte e 112 le funzioni.** Ne ho aperte e verificate riga per riga
   **34**: `guardia_prenotazione`, `autorizza`, `cattura_danno`, `storna_nota`,
   `ridistribuisci_mancante`, `da_pagare`, `e_fondatore`, `commissione_bps_lancio`,
   `fattura_startup_cents`, le 4 di `fase99`, le 4 di `fase100`, `imposta_regola`,
   `totale_riscosso`, `crea_provider_stripe_connect`, `money_path_pronto`,
   `_istante_fine_tutela`, `KYCHost.avvia`, `KYCHost.verificato`, `crea_gruppo`, `paga`,
   `testo_contratto`, `hash_di`, `registra_vetrina`, `registra_concierge`, `servi_stdio`,
   `scadi_offerte`, `libera`, `completa`, `crea_app_da_env`, `motori`.
   Le altre 78 poggiano sui due attrezzi automatici (AST + controprova testuale), che sulle 34
   verificate hanno avuto **ragione 34 volte su 34**.
4. **Non ho guardato i file `.js` di `deploy/`** come possibili chiamanti *di codice Python*: non
   possono esserlo. Sono stati usati solo per capire se un nome è atteso dal front-end.
5. **Non ho contato le classi mai istanziate**, solo le funzioni mai chiamate. Una classe morta
   con metodi che si chiamano fra loro **non compare in questo referto** (è il caso di
   `SplitQuoteUguali`, emerso solo perché 2 dei suoi 4 metodi pubblici sono senza chiamanti).
   È una **direzione di misura scoperta**, e vale la pena aprirla a parte.
6. **Non ho controllato i decoratori come chiamanti indiretti** oltre a `@property`,
   `@classmethod`, `@abstractmethod`, `@contextmanager` e `@*.route`, che sono gli unici presenti
   fra i candidati.
7. **Nessuna riparazione, nessuna suite, nessun commit**: le voci da riparare vanno scritte in
   `RIPRENDI_QUI.md`, non qui.

---

## RIEPILOGO

| | numero |
|---|---|
| definizioni esaminate | **2.092** in 152 moduli |
| **mai chiamate in moduli vivi** | **112** |
| — 🔴 gravi (soldi, tasse, guardie) | **22** |
| — 🟠 medie (funzionalità costruita e mai chiamata) | **68** |
| — 🟡 minori (involucri, fabbriche spente) | **16** |
| — 🔵 rotte Flask di un'app che non è nell'immagine | **6** |
| falsi positivi tolti (chiamati dal framework) | **5** |
| moduli interi mai raggiunti | **59** (12.055 righe, 651 funzioni, **23,7%** del codice) |
