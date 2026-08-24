# B19 — PASSAGGIO 5 · TUTTE LE REGOLE CABLATE SU UN SOLO PAESE

> **Referto di misura, non lista di cose da fare.** Sola lettura: nessun file di prodotto è
> stato toccato, nessuna riparazione fatta, nessuna suite eseguita, nessun commit.
> Misurato il **2026-08-24**, su `HEAD = 584f0e9` (`git status --porcelain`: modificati
> `CLAUDE.md`, `RIPRENDI_QUI.md`, `deploy/index.html` + la cartella non tracciata
> `collaudi/audit/`; **nessun `fase*.py` toccato, nessun file sotto `deploy/` toccato**).
>
> Perimetro, come lo definisce il passaggio: **costanti, formati e obblighi che valgono solo
> per l'Italia o solo per l'UE, e il punto dove si decide se applicarli.**
> ⛔ **Averli non è il difetto.** Il CIN è agganciato bene al paese
> (`fase83_server.py:8974-8976`) ed è qui sotto fra i **verificati e scartati**.
> Il difetto è **applicarli senza guardare il paese**, o **chiedere un dato che altrove non
> esiste** (l'IBAN, B18 punto 3).

---

## RISULTATO IN UNA RIGA

**17 regole di un paese solo applicate senza guardare il paese** — 🔴 **6 gravi** · 🟠 **8 medie**
· 🟡 **3 minori** — più **5 moduli morti** a tema paese, **11 sospetti verificati e scartati**
(scritti apposta perché non si riaprano) e **4 voci al confine col passaggio 6**, segnalate e
**non contate**.

🔑 **La forma di famiglia.** Il prodotto ha **un solo punto in tutto il server che guarda il
paese**: `fase83_server.py:8975` (il CIN). Misurato: su **95 righe** che nominano `paese` nei
152 moduli di produzione, quelle che **decidono** qualcosa in base al suo valore sono **una**
nel server e **cinque** in moduli mai raggiunti dalla produzione. Tutto il resto — IBAN, DAC7,
clausole del codice civile italiano, quota fissa in euro, autorità privacy — **si applica a
chiunque**. E il campo su cui poggia quell'unico gate è **testo libero, non obbligatorio e non
protetto in aggiornamento**: si azzera da solo.

---

## DENOMINATORE DICHIARATO

Cosa contiene la produzione (`Dockerfile.casavip:25-27`: `COPY main_casavip.py`, `COPY fase*.py`,
`COPY deploy`; `CMD python main_casavip.py`):

| grandezza | numero | come è stata misurata |
|---|---|---|
| moduli di produzione | **152** | `main_casavip.py` + 151 `fase*.py` |
| righe di produzione (solo `.py`) | **50.915** | `cat fase*.py main_casavip.py \| wc -l` |
| pagine servite | **14** | `ls deploy/*.html \| wc -l` |
| moduli **raggiungibili** da `main_casavip.py` | **93** | grafo degli import (AST + import dinamici da stringa), script di sessione |
| moduli **mai raggiunti** | **59** | idem — **riproduce esattamente il numero del passaggio 4**, con uno scanner scritto oggi e indipendente |
| righe che nominano `paese` in produzione | **95** | `grep -rIn "paese" fase*.py main_casavip.py` |
| di queste, che **decidono** in base al valore (`if`/`==`/`in (...)`/`.upper`) | **17** | filtro su quelle 95 |
| di queste, in **moduli vivi** | **12** | incrocio col grafo |
| di queste, nel **server** (l'unico ingresso) | **1** | `fase83_server.py:8975` |

### Come sono state cercate le regole di paese, e con due attrezzi diversi

1. **Setaccio per marcatore** (`grep -rIn` sui 152 moduli, conteggio per marcatore). I 24
   marcatori provati e i loro conteggi grezzi:
   `codice fiscale` **20** · `partita IVA/P.IVA` **28** · `CIN` **13** · `SCIA` **4** ·
   `cedolare` **1** · `IBAN` **27** · `IVA/VAT` **32** · `CAP/codice postale` **1** (ed è
   `RETENTION SIZE-CAP`, non un codice postale) · `provincia` **0** · `comune` **58** ·
   `ISTAT` **0** · `prefisso/+39` **32** · `Europe/Rome|CET|CEST` **22** · `it_IT` **0** ·
   `DAC7` **108** · `reverse charge` **4** · `GDPR` **27** · `PEC` **0** · `SDI/fattura
   elettronica` **5** · `ATECO` **0** · `Alloggiati/questura` **6** · `tassa di soggiorno`
   **55** · `EUR/euro/€` **314** · `\bIT\b` **20**.
   Ogni marcatore con conteggio > 0 è stato **aperto riga per riga**, non contato e basta.
2. **Setaccio per punto di decisione** (indipendente dal primo): tutte le righe che nominano
   `paese`, `giurisdizione`, `jurisdiction`, `valuta` **e** contengono un confronto, filtrate a
   mano. Serve a trovare le regole che **non nominano nessun paese** ma ne applicano una lo
   stesso — ed è così che sono uscite la quota fissa in euro (n. 5) e la chiave della tassa
   senza paese (n. 8), che il primo setaccio non poteva vedere.
3. **Grafo di raggiungibilità** (AST + import dinamici da stringa) per dire, di ogni difetto, se
   sta in un modulo **vivo** o in uno dei **59 mai raggiunti** — senza questo, metà del referto
   sarebbe allarme su codice che non parte.

---

## 🔴 GRAVI (6)

### 1. Il campo `paese` dell'annuncio si azzera da solo — e con lui sparisce l'unico obbligo di legge del prodotto

`paese` non è obbligatorio, non è normalizzato, non è confrontato con nessuna lista, e — a
differenza di `valuta` e `stato` — **non è protetto quando l'annuncio viene aggiornato**.

- `fase57_vetrina.py:252-254` — l'unica validazione è *«è una stringa? è più corta del
  limite?»*. `""` passa. `"Repubblica Italiana"` passa. `"it "` passa.
- `fase57_vetrina.py:575-576` — l'UPDATE scrive `paese=?` con quello che è arrivato: **un
  salvataggio che non manda il campo lo sovrascrive con `""`**.
- `fase83_server.py:8959` e `:8965` — sulla stessa richiesta girano `_blinda_valuta`
  (`:8870`) e `_blinda_stato` (`:8899`), **scritti apposta contro questo identico modo di
  rompersi**: il commento a `:8955` dice *«un annuncio in yen tornava in euro in silenzio a
  ogni modifica»*. **`_blinda_paese` non esiste** (`grep -n "_blinda_" fase83_server.py` → 3
  occorrenze: `valuta`, `stato`, e le loro due chiamate).
- `fase83_server.py:8974-8976` — il gate del CIN è `scheda.paese.strip().upper() in ("IT",
  "ITA", "ITALIA", "ITALY")`. Insieme di quattro valori, campo libero: **`""` non ci sta
  dentro**, quindi l'obbligo non scatta.

**La via percorribile dal pannello vero, non ipotetica:** `deploy/host.html:1203` fa
`p_paese.value = d.paese`. Se il valore salvato non è **esattamente** uno dei 15 codici della
tendina (`deploy/host.html:355-364`) — per esempio `"ITALIA"`, o un annuncio creato via API — il
`<select>` va a `selectedIndex = -1`, cioè `value === ""`; poi `deploy/host.html:1066` salva
`paese: ""`. **Un host italiano che riapre e risalva la sua scheda perde il paese, e il suo
annuncio smette di richiedere il CIN.**

Il costo lo dichiara il codice stesso a `fase83_server.py:8970-8972`: *«Reg. UE 2024/1028 +
DL 145/2023, vincolante per le piattaforme dal 20/05/2026 … multe 500-5.000 EUR per annuncio
senza»*.

### 2. Il pannello host conosce 15 paesi; il prodotto dice di essere mondiale

`deploy/host.html:355-364` — la tendina del paese ha **16 opzioni**, misurate:
`IT, ES, FR, DE, PT, GB, US, JP, CN, AE, GR, HR, CH, AT, NL` e **`XX` = «—»**.
Un host in **Brasile, Vietnam, Thailandia, Messico, Australia, Canada, India, Marocco…** non ha
il proprio paese: può solo scegliere «—». Il server invece accetta testo libero
(`fase57_vetrina.py:252`), quindi **il pannello è più stretto del motore** e non c'è nessun
punto in cui la differenza venga dichiarata.

Conseguenza diretta e misurabile: l'unico gate di paese del prodotto (n. 1) e il fuso orario
dedotto (`fase187_fuso_orario.py:65`, 33 chiavi = **18 paesi distinti**) lavorano su un valore
che, per la maggior parte del mondo, vale `XX`.

### 3. L'IBAN è obbligatorio per tutti, e blocca il bonifico, senza mai guardare il paese

`fase83_server.py:3099-3105` — `_dac7_mancanti` chiede sempre e comunque:
`codice_fiscale` **o** `partita_iva`, poi **`indirizzo_fiscale`, `paese`, `iban`**. Nessuna
delle tre è condizionata al paese, e **`paese` è chiesto solo per essere non-vuoto: il suo
valore non viene mai letto per decidere**.
`fase83_server.py:6045-6054` — l'esito blocca il payout sopra soglia.
`deploy/host.html:206` — nel modulo c'è un solo campo, `IBAN (dove ricevi i bonifici)`, senza
alternativa.

**Vietnam, Filippine, USA, Canada, Australia, Giappone non usano l'IBAN.** Riconferma
indipendente di **B18 punto 3**, con l'aggravante misurata qui: il campo che permetterebbe di
saltare la richiesta (`paese`) è **nella stessa funzione, sulla riga sopra**.

### 4. DAC7: il gate di giurisdizione esiste, e l'unico punto che fa enforcement non lo consulta

`fase100_dac7.py:23` — `attivo: bool = False   # gated: default OFF (jurisdiction)`. È il
freno di giurisdizione, ed è tirato.
`fase100_dac7.py:46-48` — `legale = p >= 30 or r >= 200000` **non dipende da `cfg.attivo`**;
solo `gate` (riga 48) lo legge.
`fase83_server.py:6049-6053` — l'enforcement chiama
`valuta_dac7(int(a["n"]), int(a["lordo"]), True).deve_segnalare`, cioè **legge `legale`, non
`gate`**, e per giunta passa `dati_forniti=True` fisso. Risultato: **il freno di giurisdizione
non tocca l'unico punto che blocca i soldi.** Stessa forma a `fase83_server.py:3194` e `:3282`
(cruscotto e report).

⚠️ **Questo corregge in parte B18 punto 3**, che dava DAC7 per *«spento di serie
(`fase100_dac7.py:24`)»*: il modulo è spento, **il blocco payout no**.

**E la soglia è in euro su una somma che euro non è.** `fase177_financial_controller.py:409-470`
(`aggrega_dac7`) somma `importo_cents` riga per riga dal giornale: **zero occorrenze di
`valuta`** in tutta la funzione (verificato: `sed -n '409,470p' … | grep -n valuta` → nessuna
riga), mentre `stream_giornale` la restituisce eccome (`:499`, la colonna c'è nel `SELECT`).
Quindi yen, dong e centesimi di euro si sommano nella stessa cifra, e quella cifra viene
confrontata con **200000 = 2.000 €** (`fase100_dac7.py:25`). Il momento in cui a un host si
blocca il bonifico dipende dalla valuta del suo annuncio.

`RegistroDAC7`/`crea_registro_dac7` — l'oggetto che **userebbe** `cfg` — non ha **nessun
chiamante** in produzione (`grep -rIn "RegistroDAC7\|crea_registro_dac7" fase*.py
main_casavip.py` → solo `fase100` stesso).

### 5. La quota fissa della tariffa tecnica è un numero in EURO applicato alle unità minori di qualunque valuta

Il motore lavora in unità minori della valuta **dell'annuncio** e sa benissimo che l'esponente
cambia (`fase99_multicurrency.py:30-33`: JPY/KRW/VND/CLP… = 0 decimali, BHD/KWD/OMR… = 3). La
quota fissa, però, è scritta una volta in euro e sommata così com'è:

- `main_casavip.py:152` → `psp_fisso_cents = 25`, usato a `fase59_concierge.py:350`:
  `costo_pagamento = (totale * _psp) // 10000 + self._psp_fisso`. `totale` è nella valuta
  dell'annuncio. Su un annuncio in **JPY** quei 25 sono **¥25**; su uno in **VND**, **25
  đồng**; su uno in **KWD** (3 decimali), **0,025 KWD**.
- `fase59_concierge.py:501-502` — il pavimento del credito: `costo = netto * _bps // 10000 +
  25 + 200`. Stessi due numeri in euro, stessa valuta sbagliata.
- `fase188_paga_struttura.py:41-42` — `GATEWAY_MINIMO_CENTS = 50`, `GATEWAY_FISSO_CENTS = 55`,
  e **il commento a `:36` lo dichiara da sé**: *«Soglie (unita' minori intere della valuta
  dell'alloggio)»*, mentre `:39-42` spiega che quei numeri vengono da *«0.25 Stripe + 0.30 di
  sicurezza»*, cioè da euro.

⛔ E i **testi legali in tutte e 8 le lingue promettono la cifra in EURO**:
`fase185_testi_legali.py:133` (it), `:207` (en), `:281` (es), `:357` (fr), `:433` (de), `:508`
(pt), `:567` (ja), `:609` (zh) dicono *«più {FISSO} EUR per transazione»*. Su un annuncio in
yen il documento dice **0,25 EUR** e il motore addebita **25 JPY**. Non sono la stessa cosa in
nessun cambio.

⚠️ Il *tasso* invece è gestito bene: `fase59_concierge.py:350` e `fase188:93` alzano la
percentuale quando la valuta dell'annuncio non è la nostra. **Il difetto è solo nella parte
fissa** — che è esattamente quella che non si può convertire con una percentuale.

### 6. A Stripe non diciamo mai in che paese sta l'host — e il dato ce l'abbiamo già

`fase101_stripe_connect.py:181-190` — `crea_account()` manda `{"type": "standard"}` più, se
c'è, l'email. **`country` non parte mai.**
`fase83_server.py:6302` — è l'unica chiamata: `connect.crea_account(info.get("email", ""))`.
`info` è il dict di `fase88_registro_host.py:447` e **contiene già `paese`** (letto due righe
prima, a `fase83_server.py:6299`, e usato a `:3104` per dire che manca).

Riconferma indipendente di **B18 punto 1**. Senza `country`, Stripe apre il conto connesso nel
paese della piattaforma: il nostro, cioè l'Italia.

---

## 🟠 MEDI (8)

### 7. L'autorità privacy la scegliamo per LINGUA, non per PAESE — e sono cinque risposte diverse

`fase185_testi_legali.py`, clausola «diritto di reclamo», misurata riga per riga in tutte e 8 le
versioni:

| lingua | riga | autorità indicata |
|---|---|---|
| it | `:1050-1051` | «in Italia, il **Garante**» |
| en | `:1126-1127` | «**in Italy**, the Garante» |
| es | `:1204-1205` | «en España, la **AEPD**» |
| fr | `:1284-1285` | «en France, la **CNIL**» |
| pt | `:845-846` | «em Portugal, a **CNPD**» |
| de | `:766-767` | «einer Aufsichtsbehörde» — **nessuna nominata** |
| ja | `:914` | 監督機関 — **nessuna nominata** |
| zh | `:975` | 监管机关 — **nessuna nominata** |

Tre trattamenti opposti nello stesso documento: *l'autorità del titolare* (it, en),
*l'autorità del paese che parla quella lingua* (es, fr, pt), *nessuna* (de, ja, zh).
**Parlare spagnolo non vuol dire stare in Spagna**: un host messicano viene mandato all'AEPD;
uno brasiliano alla CNPD portoghese, mentre in Brasile l'autorità è l'ANPD e la legge è la
LGPD, non il GDPR. E l'informativa si dichiara resa *«ai sensi degli artt. 13-14 del Reg. (UE)
2016/679»* anche in giapponese (`:865`) e cinese (`:933`).

### 8. La chiave della tassa di soggiorno non porta il paese: è il nome nudo della città

`fase83_server.py:5563` e `:5763` — `comune = d.get("citta", "")`. Il paese non entra.
`fase147_tassa_comunale.py:93` — `_norm` = `strip().lower()`, e quella stringa è la
**PRIMARY KEY** di `tassa_regola` (`:78-79`).
`fase83_server.py:7970` — la riscossione si registra con quella stessa chiave.
`fase83_server.py:8015` — il movimento contabile porta `soggetto = "comune:" + citta`.
`fase83_server.py:7696` — la rotta pubblica `/api/tassa` fa
`giur = query.get("giurisdizione") or query.get("citta") or ""`: **se non gliela dai, la
giurisdizione È la città**.

Una regola messa su `roma` vale per Roma (IT), Roma (Texas) e Roma (Queensland). È la terza
occorrenza della stessa famiglia già pagata due volte — la chiave che non porta il suo ambito
(equivalenti 01/08: mancava la funzione; scheda 21/08: mancava il blocco).
⚠️ Oggi è **latente**: nessun host ha ancora dichiarato una tassa, quindi la tabella è vuota e
tutto vale `REGOLA_ZERO` (`fase147_tassa_comunale.py:20`). **È latente finché nessuno scrive.**

Da notare il contrasto, nello stesso prodotto: il geocoder la chiave la fa **giusta** —
`fase166_geocoder.py:93-95` mette indirizzo, città **e paese**.

### 9. Le clausole vessatorie del codice civile italiano sono obbligatorie per registrarsi, ovunque nel mondo

`fase163_accettazioni.py:160-165` (it) e `:271-276` (en) — ART. 15, approvazione specifica
**ex artt. 1341-1342 c.c.**, e la versione inglese lo dice esplicitamente: *«under Italian Civil
Code arts. 1341-1342»*.
`deploy/host.html:503` — la casella è **bloccante**: `dev_clausole: "Devi approvare le clausole
vessatorie (seconda casella) per registrarti."` e `dev_consensi: "…devi spuntare tutte e tre le
caselle…"`.

È una formalità che esiste **solo nell'ordinamento italiano** (serve a rendere opponibili certe
clausole in un contratto per adesione) e viene chiesta come condizione d'ingresso a un host
giapponese, americano o brasiliano, senza nessun controllo sul paese.

### 10. Il contratto host: due lingue, legge italiana, foro della nostra sede, istituzioni italiane

`fase163_accettazioni.py:281-283` — `CONTRATTO_HOST` ha **due chiavi**: `it`, `en`.
`fase163_accettazioni.py:156-158` (it) e `:267-269` (en) — legge italiana e **foro esclusivo
della sede di BookinVIP**.
`fase163_accettazioni.py:58` e `:191` — il contratto cita **CIN** e **SCIA**; `:69` cita
**IVA** e **cedolare secca**; `:72` cita **DAC7**.
`fase163_accettazioni.py:362-367` — l'impronta che **fa fede** è sempre quella del testo
**italiano**, qualunque lingua sia stata mostrata.

Riconferma indipendente di **B18 punto 2**. ✅ Da segnalare che il ripiego è fatto bene:
`fase163_accettazioni.py:345-356` manda all'**inglese** e non all'italiano, e lo dichiara.

### 11. Il pannello presenta i dati fiscali come un obbligo europeo, a chiunque

`deploy/host.html:198-200`:

- il titolo porta la bandiera **🇪🇺** e dice *«Dati fiscali (obbligo di legge)»*;
- il sottotitolo dice *«**La legge europea (DAC7)** ci obbliga a comunicare al Fisco i dati
  degli host sopra soglia»*.

Nessuna condizione sul paese. A un host statunitense, giapponese o vietnamita — a cui la DAC7
**non si applica** — chiediamo i dati dichiarando come motivo una legge che non lo riguarda; e
al punto 3 quella richiesta gli blocca anche il bonifico.

### 12. Due convenzioni decimali opposte, ognuna applicata a tutto il mondo

- `fase185_testi_legali.py:81` — `"fisso": "%d,%02d" % (fisso // 100, fisso % 100)` produce
  **`0,25`** con la **virgola**, e finisce dentro i testi legali di tutte e 8 le lingue (righe
  `:133 :207 :281 :357 :433 :508 :567 :609`). Un host inglese, giapponese o cinese legge
  **«EUR 0,25»**. Stesso valore scritto a mano anche nel ripiego, `fase185_testi_legali.py:84`.
- `fase99_multicurrency.py:86` — `formatta()` produce **`1234.50 EUR`**, col **punto** e senza
  separatore delle migliaia, ed è la fonte usata dal server (`fase83_server.py:514-528`), dalle
  email (`fase86_email.py:544-557`), dal contratto PDF (`fase145_contratto_pdf.py:18`) e dal
  motore SEO (`fase173_motore_seo.py:159-170`). Un host o un ospite italiano, tedesco, francese,
  spagnolo o portoghese legge il prezzo con la convenzione anglosassone.

Nessuna delle due guarda la lingua o il paese di chi legge, e **fra loro si contraddicono**.

### 13. `paese` fiscale: due vocabolari diversi nello stesso pannello, nessuno dei due validato

- `fase88_registro_host.py:476-487` — `imposta_dati_fiscali` accetta qualunque stringa non
  vuota, la tronca a **200 caratteri** e la scrive. Nessuna lista ISO, nessuna
  normalizzazione, nessun `upper()`.
- `deploy/host.html:205` — `<input id="fx_paese" placeholder="Paese (es. IT)" maxlength="2">`:
  qui il paese è **testo libero di 2 caratteri**.
- `deploy/host.html:355-364` — venti righe più in là, il paese **dell'annuncio** è una
  **tendina chiusa di 15 valori**.

Due campi che si chiamano `paese` nello stesso pannello, con due vocabolari diversi, e
**nessuno dei due parla con l'altro**: il paese fiscale dell'host non tocca mai il paese del
suo annuncio, e viceversa.

### 14. Il gate outreach è cablato su un paese solo — e il database mondiale che risponderebbe non lo chiama nessuno

`fase89_jurisdiction_outreach.py:37` — `ALLOW_LIST_DEFAULT = ("US",)`.
`fase89_jurisdiction_outreach.py:312-313` — il gate è **fail-closed**: paese non in lista →
`giurisdizione_non_permessa`.
`fase95_outreach_email.py:110` e `:145` — la versione durevole **eredita lo stesso default**.
Quindi, così com'è configurato, il motore di reclutamento è acceso **solo per gli Stati Uniti**,
mentre il prossimo passo di business dichiarato è **il primo host vero a Roma**.

⛔ E il modulo che codifica il regime per **nazione** — `fase154_giurisdizioni_marketing.py`,
che al suo `:3-12` dice *«BookinVIP è MONDIALE, non europeo … fail-closed, paese sconosciuto →
regime più restrittivo»* — ha **zero chiamanti** (`grep -rIn "fase154" fase*.py
main_casavip.py` escludendo se stesso → **nessuna riga**) ed è fra i 59 mai raggiunti.
✅ **Latente**, non attivo: `MotoreRadarOutreach` e `MotoreOutreachDurevole` **non vengono
istanziati da nessuna parte in produzione** (verificato con lo stesso `grep`). Il difetto è che
la scelta «un solo paese» è il **default** che il primo chiamante erediterà.

---

## 🟡 MINORI (3)

### 15. La soglia dei 85.000 € del forfettario italiano è dentro il motore dei prezzi

`fase98_policy_commissione.py:184-186` — *«MODULO 3 (tutela forfettario): SOLO la nostra
commissione è fatturato della startup … Serve a calcolare il consumo della **soglia 85k**»*.
È un regime fiscale **italiano** che spiega la politica di commissione applicata a tutti.
La funzione che lo calcolerebbe, `fatturato_startup_cents`, **non ha chiamanti** (già misurato
nel passaggio 4).

### 16. L'identità fiscale italiana scritta a mano dentro la ricevuta, in tutte le lingue

`fase83_server.py:1349` — dentro la ricevuta di pagamento, testo fisso e non tradotto:
`"Edil Max di Foti Massimo — P.IVA 11795700969 — Via Paletro 11, 20821 Meda (MB) — …"`.
La ricevuta è localizzata in 8 lingue (`:1299`, via `_lingua_pagina` a `:314`), **tranne questa riga**, che
usa la sigla italiana «P.IVA» anche per chi non sa cosa sia.
⚠️ Lo stesso dato esiste già **in un posto solo e riusabile**, `fase185_testi_legali.py:50-55`
(`GESTORE`), col commento *«UNA sola volta, riusati in tutte le lingue»*: qui non è stato usato.
(Il *dove-dovrebbe-stare* è materia del passaggio 7; qui conta che è una stringa di un paese
solo servita a tutti.)

### 17. Il ripiego del fuso per paese copre 18 paesi

`fase187_fuso_orario.py:65-77` — `_PAESE_FUSO` ha **33 chiavi** (alias compresi) = **18 paesi
distinti**; `_CITTA_FUSO` (`:32-61`) ha **67 città**. Fuori da lì `fuso_da_luogo` torna `""`
(`:99`) e i calcoli ricadono sull'approssimazione prudente.
✅ **Non è un difetto di correttezza** — è dichiarato, il ripiego è prudente e i paesi
multi-fuso sono **esclusi apposta** (`:63-64`). È qui perché è una **copertura per paese** che
va riletta quando si apre il secondo paese: un host in Brasile, Vietnam o Messico non ottiene
mai un fuso dedotto.

---

## ⚫ CODICE A TEMA PAESE CHE NON PARTE MAI (5 moduli, tutti fra i 59 mai raggiunti)

| modulo | cosa contiene | stato |
|---|---|---|
| `fase151_alloggiati_web.py:1-8` | schedine **Alloggiati Web** per la Questura: record a 168 char, date `GG/MM/AAAA` | `attivo=False` **e** modulo mai raggiunto |
| `fase103_reverse_charge.py:1-6`, `:23` | autofattura **TD17/TD18**, **IVA 22%**, versamento **F24** | `attivo=False` **e** mai raggiunto |
| `fase154_giurisdizioni_marketing.py:1-12` | il **database mondiale** dei regimi per nazione (CAN-SPAM vs GDPR/ePrivacy), fail-closed | mai raggiunto, **zero chiamanti** — vedi n. 14 |
| `fase104_gateway_asia.py:1-7` | Alipay + WeChat Pay | mai raggiunto |
| `fase200_campagna_persuasiva.py:38` | prompt immagine: `"…interior in {citta} **Italy**…"` per **qualunque** città | mai raggiunto |

⛔ Contati a parte di proposito: non sono regole applicate a nessuno, e metterli nella lista
principale gonfierebbe il numero.

---

## ✅ SOSPETTI VERIFICATI E SCARTATI (11) — scritti perché non si riaprano

1. **Il CIN è agganciato bene.** `fase83_server.py:8974-8976`: scatta solo con `paese ∈ (IT,
   ITA, ITALIA, ITALY)` **e** solo su `stato == "pubblicato"` (la bozza si salva). Il motore
   `fase57_vetrina.py:255-263` valida **solo il formato** e si dichiara neutro per
   giurisdizione. Corretto. *(Il difetto n. 1 non è il gate: è il campo su cui poggia.)*
2. **La tassa di soggiorno è davvero jurisdiction-agnostic.** `fase66_tassa_soggiorno.py:1-30`
   (default **zero** per giurisdizione ignota, dichiarato), `fase57_vetrina.py:722-743`
   (`regola_tassa_di` → `REGOLA_ZERO` se l'host non ha dichiarato niente),
   `fase81_bootstrap_casavip.py:288-297` (*«ignota → 0, mai inventare»*). Nessuna regola
   IT/UE cablata.
3. **Non esiste nessuna ritenuta né cedolare calcolata.** Cercate in tutti i 152 moduli: le
   uniche occorrenze sono **testo di contratto** (`fase163_accettazioni.py:72`, `:202`, `:272`).
   Zero righe di calcolo. Riconferma indipendente di B18.
4. **Nessun formato di data nazionale.** 13 `strftime` in tutta la produzione, **tutti**
   `%Y-%m-%d` o `%Y-%m-%dT…Z` (ISO 8601). Zero `%d/%m/%Y`, zero `%m/%d/%Y`.
5. **Nessuna validazione di CAP/ZIP.** L'unica occorrenza di `CAP` è
   `fase38_backup.py:11` (`RETENTION SIZE-CAP`). L'indirizzo fiscale è **un campo libero
   unico** (`fase88_registro_host.py:475`): funziona in qualunque paese.
6. **Nessun formato di telefono nazionale imposto.** `fase61_localizzazione.py:44-56`: il
   prefisso serve **solo** a dedurre la lingua, con `longest-prefix` e ripiego `en`
   (`:102-113`, `LINGUA_DEFAULT = "en"` a `:40`). Un numero senza `+` non viene rifiutato:
   torna il default.
7. **La SCA (PSD2, regola UE) è trattata come esito generico, non come regola di paese.**
   `fase183_carta_offsession.py:132` la modella come stato `richiede_azione` restituito dal
   PSP, `fase177_financial_controller.py:1001` lo registra. Nessun `if paese in UE`. Corretto:
   è il PSP a sapere quando serve.
8. **I cookie sono solo tecnici di sessione** (`bv_host`, `bv_bunker`, `bv_admin`:
   `fase83_server.py:3063`, `:3810`, `:8601`). Nessun cookie di tracciamento in tutta la
   produzione → **nessun banner di consenso dovuto**. Da non «riparare» aggiungendone uno.
9. **Il ripensamento 48 ore è uniforme APPOSTA.** `fase83_server.py:470-490`: 172.800 secondi
   veri, dall'istante firmato nel gettone, per chiunque. Il commento cita California SB 644 e
   l'art. 49 brasiliano proprio per dire che si copre **il caso più largo** invece di
   distinguere per paese. È la decisione del fondatore. **Non è un difetto e non si
   ridiscute.**
10. **Il campo CIN si nasconde correttamente anche al caricamento.** `deploy/host.html:1572`
    definisce l'handler e `:1573` **lo chiama subito**; `:1205` lo richiama dopo aver caricato
    un annuncio. Sembrava il classico difetto «l'handler c'è ma non parte al load»: **non lo
    è**. *(La via che rompe le cose è un'altra ed è al punto 1: il valore non nella lista.)*
11. **Il geocoder mette il paese nella chiave** (`fase166_geocoder.py:93-95`). È l'esatto
    contrario del punto 8, nello stesso prodotto: prova che la chiave giusta si sa fare.

---

## ↔️ AL CONFINE COL PASSAGGIO 6 — segnalate qui, **non contate** qui

Sono difetti di **lingua**, non di **paese**: li conterà il passaggio 6, e vanno scritti adesso
solo perché escono dalla stessa lettura e non si perdano.

1. `fase83_server.py:672` — la pagina pubblica **indicizzabile** di **ogni annuncio del mondo**
   esce con `<html lang="it">`, l'intestazione «Prezzo: … / notte» e «Domande frequenti» in
   italiano, e le FAQ da `fase173_motore_seo.py:174-176` (etichette servizi in italiano, con
   il commento *«per le FAQ della pagina, che e' lang=it»*). È l'unica pagina che Google indicizza
   per un annuncio, e per un alloggio a Tokyo o a Lisbona è **in italiano dichiarato**.
2. `fase83_server.py:1542` (pagina di esito della decisione host) e `:1685` (pagina di reset
   password) — `lang="it"` e testi solo in italiano, mentre voucher (`:1242`) e ricevuta
   (`:1332`) sono localizzati.
3. `deploy/host.html:202-206` — i placeholder del modulo fiscale sono in italiano e **non
   esiste alcun meccanismo per tradurli**: `grep -c "data-i18n-ph\|placeholder-i18n"
   deploy/host.html` → **0**.
4. `fase61_localizzazione.py:67-74` — la notifica `cancellazione` esiste in **5 lingue su 8**
   (mancano `pt`, `ja`, `zh`), mentre `nuova_prenotazione` (`:57-66`) le ha tutte e 8.

---

## ⛔ COSA È RIMASTO FUORI (D18 punto 3)

Un taglio silenzioso fa sembrare «coperto» ciò che nessuno ha visto. Ecco i tagli, dichiarati:

1. **I 59 moduli mai raggiunti sono stati guardati solo per il tema paese**, non riga per riga.
   Sono **12.055 righe**: dentro possono esserci altre regole di un paese solo che non hanno
   colpito nessuno dei 24 marcatori. Quello che ho trovato sta nella tabella dei 5.
2. **`collaudi/` non è stato esaminato.** Il perimetro del passaggio è la produzione. Se una
   guardia dà per buona una regola italiana, questo referto non lo sa.
3. **Non ho misurato nessun cambio valutario.** Dove dico che 25 unità minori di JPY o VND
   «non sono 0,25 €» affermo la **struttura** (numero in euro sommato a unità minori di
   un'altra valuta, senza applicare l'esponente di `fase99`), non un valore in euro: il tasso
   di cambio **non è stato misurato qui** e non va citato come se lo fosse.
4. **Non ho eseguito niente.** Nessun test, nessuna suite, nessuna chiamata all'API, nessun
   giro sul VPS. Tutto è **letto**. Le due vie percorribili descritte (l'azzeramento di `paese`
   al punto 1 e il blocco payout senza IBAN al punto 3) sono ricostruite dal codice, **non
   riprodotte**: chi vorrà ripararle deve prima riprodurle.
5. **Le 8 lingue sono state confrontate solo dove il difetto era di paese** (autorità privacy,
   quota fissa, testi DAC7). Il confronto completo lingua per lingua è **il passaggio 6**.
6. **Le pagine `deploy/*.html` sono state setacciate per marcatore, non lette per intero.**
   Sono 14 file; quelle aperte davvero sono `host.html` (per intero nelle parti fiscali,
   annuncio e JS) e i marcatori su tutte le altre.
7. **Non ho aperto il VPS.** Le variabili d'ambiente lì **vincono sul codice** (già pagato con
   la tariffa tecnica): i valori citati — `PAGAMENTO_FISSO_CENTS=25`, `DAC7_BLOCCO_PAYOUT=1`,
   `VALUTA=EUR` — sono i **default del codice** (`main_casavip.py:130,152`,
   `fase83_server.py:6036`), **non** ciò che gira in produzione adesso.
8. **Non ho contato quante prenotazioni o annunci esistano** in produzione, quindi le
   valutazioni di «latente» (punti 8 e 14) valgono per quello che dice il codice, non per una
   misura sul database vero.
