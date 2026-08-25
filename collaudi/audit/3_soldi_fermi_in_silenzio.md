# B19 — PASSAGGIO 3 · I PUNTI DOVE I SOLDI SI FERMANO IN SILENZIO

> **Referto di misura, non lista di cose da fare.** Sola lettura: nessun file di prodotto è
> stato toccato, nessuna suite eseguita, nessun commit.
> Misurato il **2026-08-24**, su `HEAD = 584f0e9` (`git status`: modificati `CLAUDE.md`,
> `RIPRENDI_QUI.md`, `deploy/index.html`; nessun `fase*.py` toccato).
> Perimetro: **il silenzio, non il fallimento.** Ogni `return` anticipato, `except` che ingoia
> o ramo che salta un movimento di denaro **senza scrivere niente** — né log, né giornale,
> né email. Il modello è `fase83_server.py:6191-6192` (B17).

---

## DENOMINATORE DICHIARATO

**Ciò che il codice contiene** (`Dockerfile.casavip:25-26,42` → `main_casavip.py` + `fase*.py`
+ `deploy/`): **152 moduli di produzione** (`main_casavip.py` + 151 `fase*.py`), letti tutti da
uno scanner AST scritto per questo passaggio (in sola lettura, nella cartella temporanea di
sessione, **non** in repository).

Lo scanner ha estratto **534 candidati** in **61 file**: **251 `except` senza traccia** e
**283 `return` di ramo senza traccia**, dentro funzioni che nominano denaro. Di questi ho
**letto a mano** le funzioni dei percorsi che muovono davvero soldi — bonifico all'host,
conferma di pagamento, webhook, rimborso, giornale immutabile, cauzione, escrow, crediti,
guardiano — per un totale di **~60 funzioni** in **16 moduli**:
`fase83_server.py` (11.245 righe), `fase101_stripe_connect.py`, `fase131_payout_dashboard.py`,
`fase177_financial_controller.py`, `fase162_pagamenti_pendenti.py`, `fase149_deposito_cauzionale.py`,
`fase160_escrow_garanzia.py`, `fase167_credito_single_use.py`, `fase186_guardiano.py`,
`fase87_stripe_webhook.py`, `fase86_email.py`, `fase16_outbox.py`, `fase65_split_payment.py`,
`fase100_dac7.py`, `fase137_fedelta_guest.py`, `fase133_split_quote_uguali.py`.

**Risultato: 22 punti muti confermati leggendo il codice**, più **7 sospetti verificati e
scartati** (elencati in fondo: non sono difetti, e dirlo serve a non riaprirli).

---

## I TRE MECCANISMI CHE PRODUCONO TUTTO IL RESTO

⛔ **(1) IL GUARDIANO GUARDA SOLO IL REGISTRO. CIÒ CHE NON CI ENTRA È INVISIBILE PER SEMPRE.**
`fase186_guardiano.py:119-143` trova i bonifici fermi leggendo `payout.tutti()`. Quindi il
silenzio di B17 è **limitato a 7 giorni** (`fase186_guardiano.py:48`, `GIORNI_PAYOUT_FERMO = 7`):
il payout resta `maturato`, il guardiano lo vede, manda l'email d'allarme. **Ma ogni `return`
muto che avviene PRIMA che la riga di registro esista è fuori dalla portata di qualunque
guardia**, e lì il silenzio non ha scadenza. Sono S4, S6, S14, S15, S16.

⛔ **(2) LA MACCHINA A STATI DEL BONIFICO HA UNO STATO FINALE CHE NON SCRIVE NESSUNO.**
`fase131_payout_dashboard.py:18` dichiara cinque stati. `grep aggiorna_stato(` su tutti i
`fase*.py` dà **6 occorrenze** (`fase131:150` è la definizione; `fase83_server.py:6256, 6446,
6629, 7973` sono i chiamanti): scrivono `in_transito`, `trattenuto`, `maturato`. **`pagato` non
lo scrive nessuno.** E il guardiano cerca i fermi **solo** fra i `maturato`
(`fase186_guardiano.py:141`). Quindi `in_attesa`, `trattenuto` e `in_transito` sono tre stanze
senza sorveglianza. Sono S2 e S7.

⛔ **(3) IL CASO GUASTO GRIDA, IL CASO ASSENTE TACE — è la frase di B17, e vale in tutta la
macchina.** Dove Stripe risponde male, si scrive (`fase101_stripe_connect.py:176-179`,
`fase83_server.py:6277-6284`). Dove Stripe **non viene nemmeno chiamato**, o dove un modulo è
spento, o dove un dato manca, si esce muti. Sono S1, S3, S5, S8, S10, S11.

---

## 🔴 GRAVI — 8

### S1 — OGNI EVENTO STRIPE CHE NON SIA UN PAGAMENTO RIESCE A ENTRARE E SPARIRE SENZA UNA RIGA

- **Dove:** `fase83_server.py:7781-7839`, rotta `/api/payments/webhook`
  (`fase83_server.py:1985`; è **l'unico** webhook Stripe del progetto).
- **Cosa fa:** dopo la verifica della firma, il corpo gestisce due famiglie —
  `checkout.session.completed` (`:7791`) e `identity.verification_session.*` (`:7821`). Tutto il
  resto cade sull'ultima riga: `return 200, {"ricevuto": True, "tipo": tipo}`
  (`fase83_server.py:7839`) — **nessun log, nessun giornale, nessun conteggio.**
- **Perché è denaro fermo:** `payout.failed`, `transfer.failed`, `charge.refunded`,
  `charge.dispute.created`, `payment_intent.payment_failed`, `account.updated` sono **eventi che
  dicono che i soldi non sono andati dove dovevano**. Rispondere `200` significa dire a Stripe
  «ricevuto e gestito»: **non ritenta più**. L'evento è consumato e non esiste da nessuna parte.
- ⛔ **E il caso peggiore è `payout.failed`:** è l'unico modo che abbiamo di sapere che il
  bonifico all'host, partito da noi, **non è arrivato sul suo conto**.

### S2 — `in_transito` È UNO STATO TERMINALE DI FATTO, E NESSUNA GUARDIA LO CONTROLLA

- **Dove:** `fase131_payout_dashboard.py:18-25` (stati e transizioni) ·
  `fase83_server.py:6256` (unico punto che scrive `in_transito`) · `fase186_guardiano.py:141`.
- **Misura fatta adesso:** `grep -rn 'aggiorna_stato(' --include=fase*.py` → 6 righe, **zero**
  con `"pagato"`.
- **Cosa succede:** `connect.trasferisci` ha restituito un `tr_...` → scriviamo `in_transito` e
  la riga resta lì **per sempre**. Il guardiano cerca i fermi solo fra i `maturato`
  (`:141`), quindi un `in_transito` di sei mesi non fa scattare niente. L'unico controllo che
  tocca `in_transito` è quello degli **orfani** (`fase186_guardiano.py:132-140`), che scatta solo
  se l'host **non esiste più**.
- **Perché è denaro fermo:** un `transfer` Stripe riuscito sposta il denaro sul saldo
  dell'account connesso; **il bonifico verso la banca dell'host è un passo successivo che può
  fallire** (conto chiuso, IBAN sbagliato, verifica scaduta). Quel fallimento arriva come
  `payout.failed` → e finisce in S1. Risultato: **nel nostro registro il bonifico è "partito",
  nella realtà non è mai arrivato, e non c'è una riga in nessun posto.**

### S3 — L'UNICO SBLOCCO DI B17 È ANCHE L'UNICO SENZA RIPROVA

- **Dove:** `fase83_server.py:6301-6305` (`_host_stripe_link`).
- **Il confronto è la misura:** gli altri due motivi di hold **ritentano da soli**
  — dati fiscali completati → `fase83_server.py:3134` (`for r in pd.elenca(hid, stato="maturato")`)
  e verifica ripristinata → `fase83_server.py:2958`, tutt'e due con
  `logger.warning("PAYOUT_HOLD_RELEASED ...")`. **Quando l'host collega Stripe** — cioè
  esattamente la causa di B17 — `imposta_stripe_account` scrive l'account (`:6305`) e la funzione
  ritorna il link: **nessun ciclo sui `maturato`, nessuna riprova.**
- **E non c'è la seconda strada:** `grep account.updated` su tutti i `fase*.py` → **zero**.
  L'unico altro momento che potrebbe accorgersene (il webhook) non lo guarda (S1).
- **Conseguenza:** l'host che collega Stripe dopo la prima prenotazione **non viene pagato
  per quella prenotazione** finché non passano i 7 giorni del guardiano — e solo se qualcuno
  legge l'email d'allarme. Il codice a `:6193` gli dirà per sempre «già partito? no» ma nessuno
  richiama la funzione.

### S4 — SE `corpo_json` NON SI LEGGE, IL PAGAMENTO NON ENTRA NEL LIBRO E NON LO DICE NESSUNO

- **Dove:** `fase83_server.py:7976-7980` (`except Exception: dj = {}`, **muto**) e la guardia
  `if totale > 0:` a `:7983`, dentro `_riasserisci_incasso`.
- **Cosa fa:** con `dj = {}` il totale vale 0, quindi **saltano insieme** la riga `incasso`
  (`:7985`), la riga `commissione` (`:7998`) e la chiamata a `_costo_gateway_dal_gestore`
  (`:8011`). L'`except` esterno a `:8018` non scatta, perché **non c'è nessuna eccezione**.
- **Perché fa male più delle altre:** questa funzione è la **scatola nera dell'incasso**, e il
  suo commento a `:7965` dice che esiste proprio per sanare i crash. Qui l'ospite ha pagato,
  Stripe ha confermato, la prenotazione risulta `pagato` (il CAS a `:8035` è già avvenuto) e
  **il libro non ha una sola riga**. Il guardiano non può vedere ciò che non è stato scritto.

### S5 — IL BLOCCO D'EMERGENZA È MUTO IN UN PUNTO SU CINQUE, E PROPRIO SUL BONIFICO

- **Dove:** `fase83_server.py:6173-6174`, dentro `_trasferisci_all_host`.
- **Il confronto è la misura.** `_transazioni_bloccate()` è usato in 5 punti
  (`fase83_server.py:4370, 4728, 5188, 6173, 6943`). Quattro **si fanno sentire**: `_book`,
  `_admin_rimborso` e il rimborso Stripe rispondono `503 {"errore": "transazioni_sospese"}`;
  `_forse_penale_struttura` (`:6944`) torna `{"applicata": False, "motivo": "blocco_globale"}`.
  **Il quinto — il bonifico all'host — fa `return` e basta.**
- **E il commento promette una cosa che il codice non fa:** `:6174` dice *«riparte a freeze
  off»*. Non esiste nessun punto che, allo spegnimento del blocco globale, ricicli i `maturato`:
  gli unici due cicli di riprova sono `fase83_server.py:2958` e `:3134`, agganciati alla verifica
  host e ai dati fiscali. **Al disgelo non riparte niente da solo.**

### S6 — SE NON SI SA CHI È L'HOST, IL BONIFICO NON NASCE NEMMENO

- **Dove:** `fase83_server.py:5893-5899`, dentro `_registra_payout`.
- **Cosa fa:** `host = self._sys.catalogo.host_di_alloggio(allog)` è avvolto in
  `except Exception: host = ""` (`:5895-5896`, **muto**), e subito dopo
  `if not host: return` (`:5899`, **muto**).
- **Perché è la peggiore della famiglia:** le altre lasciano un payout `maturato` che il
  guardiano trova dopo 7 giorni. **Questa non lascia niente**: la riga di payout non viene mai
  creata, quindi `pd.elenca()`, `da_pagare()`, `_payout_anomali` e la dashboard dell'host
  **non hanno nulla da mostrare**. L'ospite paga, il libro registra l'incasso, e non esiste da
  nessuna parte l'informazione che a qualcuno dobbiamo dei soldi.

### S7 — DUE STATI DEL BONIFICO NON LI GUARDA NESSUNO, E CI SI FINISCE IN SILENZIO

- **Dove:** `fase131_payout_dashboard.py:150-165` (`aggiorna_stato`) · `fase83_server.py:7973`
  (il chiamante) · `fase186_guardiano.py:63` (`_STATI_PAYOUT_VERSO_HOST = ("maturato",
  "in_transito")`) e `:141` (il fermo, solo `maturato`).
- **Come ci si finisce:** `pd.aggiorna_stato(rif, "maturato")` a `:7973` **ignora il valore di
  ritorno**, e `aggiorna_stato` torna `False` **senza log** in due casi (`fase131:152` stato non
  ammesso, `fase131:159` riga assente o transizione non prevista). Se la riga era rimasta
  `in_attesa`, resta `in_attesa`.
- **Cosa non guarda nessuno:** `in_attesa` non compare in **nessun** controllo del guardiano.
  `trattenuto` (soldi fermati da un arbitro, `fase83_server.py:6446, 6629`) nemmeno: non esiste
  un controllo di «trattenuto da troppo tempo».
- ⛔ **È la stessa lezione già pagata con `exc_info=False`** ([bookinvip-verde-finto-exc-info]):
  la domanda non è «la chiamata è tornata?», è «è tornata **la cosa giusta**?».

### S8 — IL WEBHOOK CHE RIFIUTA UN PAGAMENTO NON LASCIA UNA RIGA

- **Dove:** `fase83_server.py:7784-7785` (`if not secret: return 503,
  {"errore": "webhook_non_configurato"}`) e `:7789-7790` (`if not ok: return 400,
  {"errore": "firma_non_valida"}`). **Nessun `logger` in nessuno dei due rami.**
- **E il modulo a valle è muto per costruzione:** `fase87_stripe_webhook.py` torna `False` in
  sei punti (`:44, 51, 55, 58, 62, 78`) senza mai scrivere una riga — legittimo per una funzione
  pura di verifica firma, **a patto che sia il chiamante a parlare**. Non lo fa.
- **Perché è denaro fermo:** se `STRIPE_WEBHOOK_SECRET` manca o non corrisponde più (rotazione
  della chiave, deploy con la variabile persa — ⚠️ e sul VPS **le variabili d'ambiente vincono
  sul codice**, [bookinvip-tariffa-tecnica-5-7]), **ogni singola conferma di pagamento viene
  rifiutata**. L'ospite paga su Stripe, la prenotazione resta `in_attesa`, lo sweeper la scade e
  libera le date, e **nei nostri log non c'è una riga che dica perché**. Stripe ritenta per
  giorni e poi smette.

---

## 🟠 MEDI — 11

### S9 — LA CAUZIONE SI DICHIARA LIBERATA SENZA GUARDARE SE IL PSP L'HA LIBERATA

- **Dove:** `fase149_deposito_cauzionale.py:141-146` (`rilascia`).
- **Cosa fa:** `self._safe(self._release, r[0])` — **il valore di ritorno non viene guardato**;
  subito dopo l'`UPDATE ... SET stato='rilasciato'` e `return True`. Se `self._release` è `None`
  (PSP non configurato) non si chiama proprio niente e il record dice comunque `rilasciato`.
- **E il ramo d'errore è muto:** `except Exception: ... return False` (`:147-152`) — **nessun
  log** (il gemello in `cattura_danno`, `:122-127`, ce l'ha: `logger.warning`).
- **Perché è denaro fermo:** è denaro **dell'ospite**, bloccato sulla sua carta. Noi diciamo di
  averglielo liberato.

### S10 — IL DANNO NON SI CATTURA E NON SI SCRIVE PERCHÉ

- **Dove:** `fase149_deposito_cauzionale.py:109-111`.
- **Cosa fa:** `if self._capture is None or not self._safe(self._capture, psp_ref, danno):` →
  `ROLLBACK` + `return False`. Il **secondo** ramo lascia una traccia (`_safe` scrive
  `logger.warning("PSP call fallita (ISOLATA)")`, `:168-173`); il **primo** — PSP assente — no:
  la valutazione corta non arriva mai a `_safe`. L'host chiede il danno, riceve `False`, e da
  nessuna parte è scritto che il motivo era «non abbiamo il PSP».

### S11 — TUTTE LE EMAIL SUI SOLDI SONO SPARA-E-DIMENTICA

- **Dove:** `fase83_server.py:6078-6087` (`_email_bg`).
- **Cosa fa:** `if prov is None or not (isinstance(dest, str) and "@" in dest): return`
  (`:6081-6082`, **muto**), poi `threading.Thread(target=prov.invia, ...).start()` (`:6084`) —
  **il thread non ha `try`, e il valore di ritorno non lo legge nessuno**.
- **E il provider può dire di no in silenzio:** `fase86_email.py:76` fa
  `return bool(self._send(...))`: un `False` **pulito** non passa da nessun `logger` (solo
  l'eccezione lo fa, `:77-79`). Il provider stesso può non esistere affatto:
  `crea_provider_email` torna `None` senza host SMTP (`fase86_email.py:114-120`).
- **Cosa passa di lì:** «il bonifico è partito» all'host (`fase83_server.py:6266-6272`), «il
  pagamento è confermato» all'ospite (`:8159`), la cancellazione col rimborso (`:6899`).
  **La terza delle tre tracce di B17 — l'email — non è mai verificabile.**
- ⚠️ **Non misurato in questo passaggio:** se in produzione l'host SMTP sia configurato.
  Questo referto legge il codice, non il VPS.

### S12 — IL CREDITO ANTI-RIMPIANTO PUÒ EVAPORARE SENZA UNA RIGA

- **Dove:** `fase83_server.py:7080-7101` (`_credito_anti_rimpianto`).
- **Cosa fa:** `if firma is None or cv <= 0: return 0, ""` (`:7090-7091`, muto) e
  `except Exception: return 0, ""` (`:7100-7101`, **muto**).
- **Cosa vede l'ospite:** il chiamante a `:6897` passa il risultato in `_email_cancellazione` e
  nella risposta (`:6917`): con `cv_cents = 0` la frase *«Hai un Credito Viaggio per la prossima
  prenotazione»* semplicemente **non compare** (`:6931`). Nessuno saprà mai che gli spettava.
- ⛔ **È la famiglia di B8/B9/B10: sull'Anti-Rimpianto non guarda nessuna guardia.**

### S13 — I MOTIVI PER CUI LA PENALE NON SCATTA LI LEGGE SOLO CHI CANCELLA

- **Dove:** `fase83_server.py:6931-6960` (`_forse_penale_struttura`), chiamata da `:6906`.
- **Cosa fa:** torna `{"applicata": False, "motivo": ...}` con quattro motivi diversi
  (`non_attivo` a `:6942`, `blocco_globale` a `:6944`, `non_tardiva` a `:6956`,
  `prezzo_assente` a `:6958`). Il chiamante lo mette **solo** dentro la risposta HTTP
  (`penale_struttura`, `:6909`): **nessun log, nessun giornale, nessun contatore.**
- **Perché conta adesso:** ⚠️ `PAGA_STRUTTURA_ATTIVO=1` è **acceso in produzione**
  ([bookinvip-cartelle-e-continuita]). Una penale che non scatta è denaro nostro che non
  incassiamo, e l'unica persona che legge il motivo è **l'ospite che sta cancellando**.

### S14 — LA SCATOLA NERA RIFIUTA LA RIGA E NON LO DICE

- **Dove:** `fase83_server.py:5921-5928` (`_giornale`).
- **Cosa fa:** `if fc is None: return` (`:5923-5924`, muto: modulo finanza spento) e
  `if not (isinstance(importo_cents, int) ... and importo_cents > 0): return` (`:5925-5928`,
  muto). L'`except` finale (`:5967`) scrive solo se **solleva** qualcosa.
- **Dove diventa concreto:** i chiamanti che passano un importo ricavato da `corpo_json`
  con doppio ripiego a 0 — `fase83_server.py:8081-8087` e `:8127-8133` (le due righe di
  «rimborso dovuto») — con un `dj` vuoto passano `importo_cents=0`. Il commento a `:8071` dice
  esattamente cosa si perde: *«senza questa riga il cliente non entra nella lista dei rimborsi
  dovuti»*. **La guardia che protegge il libro è anche il punto che cancella l'unica traccia.**

### S15 — IL GIORNALE IMMUTABILE SCARTA IN SILENZIO CIÒ CHE NON GLI TORNA

- **Dove:** `fase177_financial_controller.py:204-207` (`registra`) e `:252-254` (`movimento`).
- **Cosa fa:** `registra` torna `None` senza log se manca l'`evento_id`, se il `tipo` non è in
  `TIPI_GIORNALE`, se il soggetto è vuoto, se l'importo è ≤ 0 o se la valuta non ha 3 lettere.
  `movimento` torna `None` senza log se il `tipo` non ha una coppia di conti.
  Il ramo d'errore vero, invece, **parla** (`logger.error("giornale: registrazione fallita")`,
  `:237`): di nuovo, il guasto grida e l'input rifiutato tace.
- **Misura fatta adesso** (`ast.literal_eval` sulle due tabelle): `TIPI_GIORNALE` ha **17** voci,
  `_CONTI_MOVIMENTO` ne ha **10**; **7 tipi** (`nota_credito`, `nota_debito`, `penale_offset`,
  `penale_incassata`, `storno`, `debt_on`, `debt_off`) passerebbero da `movimento()` **e
  verrebbero scartati muti**. ✅ **Oggi nessun chiamante lo fa** (le 16 chiamate a
  `_giornale(tipo=` / `.movimento(` usano solo tipi presenti in entrambe): **è una trappola
  latente, non un difetto attivo** — ma è esattamente la forma di
  [bookinvip-chiave-porta-ambito], e diventa vera il giorno che qualcuno scrive la riga.

### S16 — UN RIMBORSO DISPOSTO DALL'ADMIN PUÒ NON LASCIARE LA RIGA, E `_falliti` NON SE NE ACCORGE

- **Dove:** `fase83_server.py:4420-4432` (`_admin_rimborso`).
- **Cosa fa:** `except Exception: dj = {}` (`:4423-4424`, **muto**) → `tot = 0` (`:4425`) →
  la guardia `if tot > 0:` (`:4429`) **salta la riga di giornale**. E il meccanismo che esiste
  proprio per dichiarare i passi mancati — `_falliti` (`:4399`, `:4436`) — **non viene
  alimentato in questo ramo**: la risposta all'admin dirà che è andato tutto bene.
- **Conseguenza:** la lista «rimborsi dovuti» nasce dal giornale (`fase83_server.py:4655`).
  Senza quella riga, **l'ospite non compare da nessuna parte**.

### S17 — IL GUARDIANO TRADISCE TRE VOLTE IL PRINCIPIO CHE DICHIARA LUI STESSO

- **Il principio, scritto nel modulo:** `fase186_guardiano.py:112-114` — *«NIENTE except qui: un
  archivio guasto tornava [] = "nessun escrow bloccato", cioè una BUGIA travestita da controllo
  pulito»*.
- **Le tre violazioni dello stesso modulo:**
  1. `:126-127` — `if pay is None or not hasattr(pay, "tutti"): return {"bonifico_fermo": [],
     "payout_orfano": []}`. Senza il modulo payout, il guardiano dichiara **zero anomalie sui
     bonifici** invece di dichiararsi cieco.
  2. `:138-139` — `except Exception: pass` attorno a `reg.esiste_host(...)`: un errore di lettura
     del registro host **non produce un orfano e non lascia traccia**.
  3. `:163-164` — `except Exception: return None` in `_stato_rimborso`: un pendente illeggibile
     vale «prenotazione non rimborsata», cioè **nessun allarme** sul controllo che il modulo
     stesso definisce *«LA PERDITA PIENA»* (`:145-151`).
- ⛔ È il caso peggiore per classe: **un punto cieco dentro lo strumento che serve a non averne.**

### S18 — DUE SCRITTURE DEL WEBHOOK POSSONO RIMPIAZZARE IL RECORD CON UN RECORD VUOTO

- **Dove:** `fase162_pagamenti_pendenti.py:165-177` (`salva_stripe_session`) e `:214-226`
  (`salva_costo_gateway`).
- **Cosa fa:** `except Exception: dj = {}` (`:169`, `:218`, **muti**) — e anche
  `if not isinstance(dj, dict): dj = {}` (`:167`, `:216`) — **poi** esegue
  `UPDATE pendenti SET corpo_json=?` con quel `dj`. Se il vecchio corpo non si legge, il record
  viene **riscritto con le sole chiavi nuove**: spariscono `totale_cents`, `host_id`,
  `netto_host_cents`, `voucher_token`, `valuta`.
- **Perché è grave la combinazione:** `salva_stripe_session` è chiamata dal webhook a
  `fase83_server.py:7813`, **prima** di `_conferma_pagamento` (`:7819`). Un record svuotato lì
  produce esattamente S4 e S14 a valle, in cascata, tutto muto.
- ⚠️ **Onestà sulla misura:** il `corpo_json` lo scriviamo noi con `json.dumps`
  (`fase83_server.py:5779-5800`), quindi **non ho dimostrato un innesco reale**. Quello che è
  misurato è che, **se** l'innesco avviene, non resta nessuna traccia e il danno si propaga.

### S19 — UNA PRENOTAZIONE ILLEGGIBILE ESCE DAL CONFRONTO CON STRIPE E NON LO DICE

- **Dove:** `fase83_server.py:4673-4676` (`_admin_rimborsi_dovuti`),
  `except Exception: continue`.
- **Cosa fa:** è il ciclo che scopre **la divergenza nell'altro senso** — Stripe ha restituito
  soldi su una prenotazione che per noi è viva (`:4662-4663`, e l'allarme a `:4693`). Un record
  il cui `corpo_json` non si legge **viene saltato** senza entrare né negli `allarmi` né nei
  `motivi` (`:4657-4660`), che sono il canale previsto per dire «non ho potuto controllare».

---

## 🟡 MINORI — 3

### S20 — L'AUTO-RILASCIO DELL'ESCROW DECIDE IN SILENZIO IN TUTT'E DUE I VERSI

- **Dove:** `fase160_escrow_garanzia.py:210-220`.
- `except Exception: salta = False` (`:212-213`): se la lettura «questa è già stata rimborsata?»
  fallisce, **si paga l'host** su una prenotazione potenzialmente già rimborsata — è la
  «PERDITA PIENA» che `fase186_guardiano.py:145` insegue a valle — e **non resta una riga**.
- Il verso opposto: quando `salta` è vero, l'escrow viene chiuso `'annullato'` con
  `host_riceve_cents=0` (`:215-219`), **senza log e senza giornale**. Denaro che l'host si
  aspettava, azzerato in silenzio (giusto nel merito, muto nella forma).

### S21 — LO SWEEPER SI SPEGNE DA SOLO SENZA DIRLO

- **Dove:** `fase83_server.py:10429-10431` — `if pp is None or inv is None: return`, **muto**:
  se manca uno dei due moduli, la passata che scade gli hold, libera le date e toglie i payout
  fantasma **non gira, e nessuno lo sa**. · `:10451-10454` — `pulisci_vecchi()` avvolto in
  `except Exception: pass`, l'**unico** `except` muto di tutta la funzione (gli altri tre a
  `:10448`, `:10465`, `:10486` scrivono).

### S22 — LA REGISTRAZIONE DELL'HOLD HA DUE PORTE MUTE PRIMA DI QUALSIASI SCRITTURA

- **Dove:** `fase83_server.py:5754-5758` — `if not corpo.get("payment_url"): return` e
  `if pp is None or not ref: return`, tutt'e due **mute**.
- **Il contrasto è dentro la stessa funzione:** il ramo d'errore a `:5810-5817` è stato portato
  da `warning` a **`error`** il 2026-08-08 proprio perché *«se questa scrittura fallisce, la
  prenotazione prosegue e l'ospite paga, ma il record del pendente NON ESISTE»*. Le due porte in
  cima producono lo stesso effetto — nessun pendente — e non dicono niente.

---

## ✅ VERIFICATI E SCARTATI — 7 (non sono difetti: dirlo serve a non riaprirli)

1. **`fase101_stripe_connect.trasferisci` che torna `None`** (`:231`, `:234`) **non è muto a
   livello di sistema**: il chiamante lo tratta come fallimento e scrive `logger.error("BONIFICO
   MANUALE RICHIESTO...")` **più** una riga `payout_manuale` nel giornale
   (`fase83_server.py:6274-6284`). È il caso che B17 cita come «quello che grida».
2. **`fase167_credito_single_use.consuma`**: l'`except sqlite3.Error: pass` a `:119` è dentro il
   `ROLLBACK`, e la funzione **rilancia** (`raise`, `:122`). Il chiamante
   `fase83_server._consuma_credito` scrive `logger.error` e torna `"errore"` (`:7062-7065`).
3. **`fase65_split_payment`**: i due `except sqlite3.Error: pass` (`:190`, `:240`) sono dentro il
   `ROLLBACK` e la funzione **rilancia** (`:192`, `:242`).
4. **`fase100_dac7._scrivi`** (`:76-78`): `if not self._p: self._mem = d; return` **non perde
   niente** — è la modalità in memoria dichiarata dal costruttore.
5. **`fase16_outbox`** è il **contro-esempio fatto bene**, ed è la prova che in questo progetto
   la forma giusta esiste già: `logger.critical` per un topic senza handler (`:480`) e
   `logger.critical("DLQ: ...")` all'esaurimento dei tentativi (`:527`).
6. **Gli hold del bonifico parlano**: DAC7 (`fase83_server.py:6243-6249`) e verifica revocata
   (`:6227-6233`) scrivono tutt'e due `PAYOUT_HOLD_TRIGGERED` in formato leggibile.
   **Il difetto non è la famiglia degli hold: è la famiglia dei gate di configurazione.**
7. **Le sette strade del rimborso scrivono tutte nel giornale** (`fase83_server.py:4430`,
   `4883`, `6423`, `6874`, `8081`, `8127`, `8221`), e lo storno passa da un punto solo
   (`_giornale`, `:5946-5964`). Il buco non è lì: è nella **guardia sull'importo** (S14, S16).

**Fuori produzione (letti, non contati):** `fase133_split_quote_uguali` (`paga` `:134` e `stato`
`:153` hanno `except` muti, ma di quel modulo la produzione importa **solo** `riparti_uguale`,
`fase83_server.py:7443`) e `fase137_fedelta_guest` (`accredita` `:99-101` torna 0 in silenzio;
`grep fase137` fuori dal file stesso → **zero importatori**).

---

## ⛔ COSA È RIMASTO FUORI (dichiarato, non tagliato in silenzio)

1. **Niente suite, niente commit, niente esecuzione.** Nessun difetto è stato **riprodotto a
   runtime**: tutte le 22 voci sono lette dal codice. Dove non ho potuto dimostrare l'innesco
   l'ho scritto (S18).
2. **Niente misurato sul VPS.** Se in produzione siano davvero impostati `STRIPE_WEBHOOK_SECRET`
   (S8) e l'host SMTP (S11) **non è stato guardato**: questo passaggio legge il codice.
3. **Il limite dello scanner.** Riconosce solo due forme: `except` il cui corpo non contiene
   log/`raise`, e `return` di valore falso **direttamente sotto un `if`**. **Non vede**:
   `continue`/`break` muti dentro i cicli, `pass` fuori dagli `except`, i `return` dentro
   `try`/`with`/`for` non annidati in un `if`, gli operatori ternari, i valori di ritorno
   **ignorati dal chiamante** (S7, S9 e S17 li ho trovati **leggendo**, non con l'attrezzo).
4. **Ho letto ~60 funzioni su 534 candidati.** I restanti ~470 stanno in moduli che non muovono
   denaro (SEO, vetrina, concierge, channel manager, geocoder): **non sono stati letti uno per
   uno**. I primi tre per numero di candidati non money sono `fase58_channel_manager` (18),
   `fase57_vetrina` (14), `fase59_concierge` (10).
5. **`deploy/*.js` e `deploy/*.html` non sono stati guardati.** Un pagamento può fermarsi anche
   nel browser; questo passaggio si è fermato al server.
6. **Non ho contato i punti muti nei collaudi** (`collaudi/`, `test_*.py`): il perimetro è la
   produzione.
7. **Fuori perimetro per definizione, ma visto per strada** (il criterio è **il silenzio**, non
   il rischio): se il `POST` a Stripe va in timeout **dopo** che il transfer è stato creato,
   `_post` torna `None` (`fase101_stripe_connect.py:179`) e noi scriviamo `payout_manuale` nel
   giornale (`fase83_server.py:6280`) → il fondatore paga a mano **un bonifico già partito**.
   Non è un difetto di silenzio — quello **grida** — ma è un doppio pagamento, e non risulta
   scritto da nessuna parte. **Lo lascio qui perché non venga perso, non perché appartenga a
   questo referto.**

---

## RIEPILOGO

| | | |
|---|---|---|
| Moduli di produzione esaminati dallo scanner | **152** | `main_casavip.py` + 151 `fase*.py` |
| Candidati grezzi | **534** | 251 `except` muti + 283 `return` muti, in 61 file |
| Funzioni lette a mano | **~60** | in 16 moduli dei soldi |
| **Punti muti confermati** | **22** | 🔴 8 · 🟠 11 · 🟡 3 |
| Sospetti verificati e scartati | **7** | + 2 moduli fuori produzione |

**La frase da portare via:** il guardiano vede solo ciò che è già scritto nel registro. Le otto
voci gravi sono tutte, senza eccezione, punti in cui il registro **non viene scritto** — o viene
scritto e poi **nessuno lo rilegge più** (`in_transito`). B17 non è un caso isolato: è la forma
di famiglia di **otto** casi, e in cinque di questi il silenzio **non ha una scadenza**.
