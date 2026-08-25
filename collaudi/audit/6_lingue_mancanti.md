# B19 — PASSAGGIO 6 · TUTTI I TESTI CHE ESISTONO IN ITALIANO E NON NELLE ALTRE 7 LINGUE, O VICEVERSA

> **Referto di misura, non lista di cose da fare.** Sola lettura: nessun file di prodotto è
> stato toccato, nessuna riparazione fatta, nessuna suite eseguita, nessun commit.
> Misurato il **2026-08-25**, su `HEAD = 584f0e9` (`git status --porcelain`: modificati
> `CLAUDE.md`, `RIPRENDI_QUI.md`, `deploy/index.html` + la cartella non tracciata
> `collaudi/audit/`; **nessun `fase*.py` toccato, nessun file sotto `deploy/` toccato**).
>
> Perimetro, come lo definisce il passaggio: **chiavi di traduzione presenti in una lingua e
> assenti in un'altra, in `deploy/*.html` e nei dizionari `fase*.py`.**
> ⚠️ E il caso più insidioso non è la chiave mancante: è la chiave **presente con il contenuto
> vecchio**. Per quello ho usato due sonde deterministiche in più (segnaposto e numeri), non
> l'occhio.

---

## RISULTATO IN UNA RIGA

**19 scompagnamenti di lingua** — 🔴 **7 gravi** · 🟠 **8 medi** · 🟡 **4 minori** — su
**8.428 coppie (lingua, chiave)** confrontate una per una in **26 dizionari** di **12 moduli
Python**, **13 pagine HTML** e `deploy/app.js`. Più **11 sospetti verificati e scartati**,
scritti apposta perché non si riaprano.

🔑 **La forma di famiglia, e non è «mancano delle traduzioni».**
Il prodotto ha **due qualità di traduzione, e il confine passa esattamente dove nessuno
guarda**. Dove una guardia misura — il dizionario del server (`ETICHETTE_UI`, 165 chiavi × 8),
le email (62 × 8), i testi legali (2 documenti × 8, stesso numero di articoli), `app.js`
(42 × 8) — **la copertura è 8 lingue su 8, senza un buco**. Dove nessuna guardia guarda — i
**due pannelli**, quello dell'host e quello dell'admin — **239 chiavi su 468 esistono solo in
italiano e inglese**. Non è distrazione: è la mappa esatta di dove arriva la sorveglianza.
E la sorveglianza c'è, ma misura **la cosa accanto**: `collaudi/occhio_del_fondatore.py`
promuove `host.html` con **773 parole tradotte su 776** perché conta i **marcatori** nell'HTML
e **non apre nemmeno un dizionario** (misurato: zero occorrenze di un codice lingua in tutto
il file).

Le tre che pesano:

- **Il pannello dell'host è per il 47% in inglese** per un host tedesco, spagnolo, francese,
  portoghese, giapponese o cinese (`deploy/host.html:502`, **148 chiavi su 316** assenti in
  quelle sei lingue, **146 delle quali finiscono davvero sullo schermo**). Dentro quelle 148
  ci sono **tutte e 7 le chiavi che spiegano la commissione e la tariffa tecnica**, l'avviso
  che annullare costa **una penale del 15%**, e la spunta di **approvazione specifica delle
  clausole vessatorie ex artt. 1341-1342 c.c.**
- **La tariffa tecnica dice «3%» in 7 lingue e «5% + 0,25 €» in italiano** — di nuovo, e in
  **due posti nuovi** rispetto a B16/passaggio 1: la **sala di controllo del fondatore**
  (`deploy/bunker.html:213`, chiave `ct_h`) e il **kit con cui si reclutano gli host**
  (`deploy/kit-marketing.html:118`, chiavi `box2`, `msg1`, `msg2`, `msg3`). Nel kit le 7
  lingue non sbagliano solo la cifra: aggiungono *«su quella riga non guadagniamo nulla»*,
  che con 5% + 0,25 € **non è vero**.
- **Il contratto ripiega su due lingue diverse a seconda di chi risponde.** Il server è stato
  riparato per ripiegare sull'**inglese** (`fase163_accettazioni.py:345-355`, con il commento
  che spiega perché l'italiano era sbagliato); la **pagina** ripiega ancora sull'**italiano**
  (`deploy/contratto-host.html:46-48`). E `deploy/host.html:97` e `:136` linkano il contratto
  **senza `?lang=`**, mentre `:976` lo chiede all'API **con** la lingua: la prova firmata
  registra una lingua, l'host ne ha letta un'altra.

---

## DENOMINATORE DICHIARATO

Le 8 lingue del prodotto: `it en es fr de pt ja zh` (`fase61_localizzazione.py:41`).

| grandezza | numero | come è stata misurata |
|---|---|---|
| file `.py` di produzione letti (root, esclusi `test_*`) | **158** | `os.listdir` + filtro; ⚠️ i passaggi 3/4/5 usano **152** (`main_casavip` + 151 `fase*.py`): i 6 in più sono `app.py`, `assistente_gestionale.py`, `collaudo_livello7_e2e.py`, `gunicorn.conf.py`, `ispettore_statico.py`, `outreach_runner.py` |
| dizionari multilingua trovati nei `.py` | **272** (in **12** moduli) | scanner AST di sessione: ogni `ast.Dict` le cui chiavi sono per >60% codici lingua, più la forma `chiave -> {lingua: testo}` |
| coppie (lingua, chiave) confrontate nei `.py` | **2.262** | somma delle chiavi interne per lingua |
| file `.html` in `deploy/` letti | **14** | `ls deploy/*.html` |
| dizionari multilingua trovati negli `.html` | **14** (in **13** file) | parser JS a stati scritto per la sessione (bilanciamento graffe + stringhe, **niente `eval`**) |
| coppie (lingua, chiave) confrontate negli `.html` | **5.830** | idem |
| dizionari e coppie in `deploy/app.js` | **2** / **336** | idem (`BV.ERR_FRASI` 4×8, `BV.ERR_AUTH` 38×8) |
| **totale coppie confrontate** | **8.428** | 2.262 + 5.830 + 336 |
| moduli raggiungibili da `main_casavip.py` | **89** su 152 | grafo import AST, scanner di sessione |

⚠️ **Discordanza dichiarata e non risolta.** Il mio grafo dà **63** moduli mai raggiunti su
152; i passaggi 4 e 5 dicono **59**. Non ho riconciliato i 4 di differenza: non è il tema di
questo passaggio, ma **quel numero non va riusato finché non è rimisurato**.

### I quattro attrezzi, e cosa cerca ognuno

1. **Chiavi mancanti** — per ogni dizionario, l'unione delle chiavi di tutte le lingue meno le
   chiavi di ciascuna. Trova il buco.
2. **Lingue assenti** — dizionari che non hanno proprio il blocco di una lingua.
3. **Segnaposto scompagnati** — `{noi}`, `{ota}`, `{alloggio}` presenti in una lingua e persi in
   un'altra. **Risultato: 0 su 8.428.** È l'unico verde pieno del passaggio, e va detto.
4. **Numeri discordi nello stesso slot** — tutte le cifre e percentuali estratte dal testo di
   ogni lingua per la stessa chiave, confrontate fra loro. È l'attrezzo che ha stanato il
   «3%», che nessuna delle prime tre sonde avrebbe visto (la chiave **c'è**, in tutte e 8).
   Ha prodotto **60 candidati** (27 nei `.py`, 33 negli `.html`): **8 veri**, 52 falsi
   positivi, tutti aperti a mano e tutti spiegati nella sezione «verificati e scartati».

---

## 🔴 GRAVI (7)

### 1. `deploy/host.html:502` — il pannello dell'host è metà in inglese in 6 lingue su 8

| lingua | chiavi definite |
|---|---|
| `it` | **316** |
| `en` | **316** |
| `de` `es` `fr` `pt` `ja` `zh` | **168** ciascuna — **le stesse 148 mancanti, identiche in tutte e sei** |

Il ripiego è dichiarato nei dati a `deploy/host.html:512` (`TR._fallback = {'*':'en'}`,
risolutore `BV.t` in `deploy/app.js:52`): quindi **non si rompe niente e non si vede un
codice** — un host tedesco legge **inglese** su 148 etichette su 316 e italiano su nessuna.
È il difetto che non grida.

**Le 148 non sono decorazione.** Misurato: **146 su 148** finiscono davvero sullo schermo
(78 marcate `data-i18n*` nell'HTML, 67 chiamate da `T('...')`, `aggiornato_ok` e
`pubblicato_ok` dal ternario a `:1084`); le **2** che restano (`dev_clausole`, `foto_rimossa`)
non le usa nessuno — vedi il punto 18. I gruppi più grossi:

| gruppo | n. | cosa è |
|---|---|---|
| `co_*` | **7** | **tutta la spiegazione di commissione e tariffa tecnica** — `co_h` «Promozione Lancio: 0% Commissioni», `co_p` «…una tariffa tecnica del 5% + 0,25 € a prenotazione…», `co_r1..r4`, `co_n` «La tariffa tecnica è sempre attiva, in ogni periodo…» |
| `hc_*` | **8** | annullamento — dentro c'è `hc_conferma`: **«Il cliente sarà rimborsato al 100% e pagherai una penale del 15%.»** |
| `fx_*` | **11** | **dati fiscali (obbligo di legge)** — `fx_h` «Dati fiscali (obbligo di legge)» |
| `pw_*` | **11** | cambio e recupero password |
| `imp_*` | **10** | importazione calendario |
| `kx_*` | **8** | verifica identità (KYC) |
| `seo_*` | **8** | assistente SEO |
| `l_*` / `h_*` | **14** | etichette e aiuti del modulo annuncio — dentro `l_paese`, `h_valuta`, `l_cin`, `h_cin` |
| `sta_*` | **6** | statistiche |
| `dev_*` | **5** | avvisi bloccanti — dentro `dev_cin` «Per un alloggio in Italia serve il CIN (obbligo di legge)…» |
| `privacy_*` + `clausole_appr` | **3** | **il consenso privacy e l'approvazione specifica ex artt. 1341-1342 c.c.** |
| altri 21 gruppi | **57** | pin, calendario, cancellazione, telegram, guida, ricerca, sessione… |

⛔ **Il punto che pesa di più**: `clausole_appr`, `privacy_pre`, `privacy_post`. Sono il testo
della spunta che rende il contratto **opponibile**. Un host giapponese o tedesco spunta una
casella il cui testo, per lui, è in inglese — mentre il contratto che quella casella approva è
in italiano (punto 5).

### 2. `deploy/admin.html:200` — il pannello admin è per il 60% in inglese in 6 lingue su 8

`it` **152** · `en` **152** · `de` `es` `fr` `pt` `ja` `zh` **61 ciascuna** (le stesse 91
mancanti). Ripiego inglese a `deploy/admin.html:213`. Misurato: **89 su 91** sono rese davvero
(35 marcate, 52 da `T('...')`, 2 dal ternario a `:572`).

I gruppi: `ky_*` **26** (Verifiche & Legale: approva/revoca/fascicolo), `al_*` **15** (tutti
gli annunci, incluso `al_delhost` «Seleziona per cancellare»), `ctr_*` **13**
(**Controversie da risolvere**, incluso `ctr_pct` «% al cliente:» e `ctr_risolvi`), `au_*`
**12** (audit e storno), `bk_*` **10** (**Bunker — operazioni super-admin**), `sr_*` **6**,
`st_*` **3**, `p_*` **3**, `f_*` **2**, `b_logout` **1**.

### 3. `deploy/bunker.html:213` chiave `ct_h` — «3%» in 7 lingue, «5% + 0,25 €» in italiano

```
it  "🧾 Tariffa tecnica Stripe (5% + 0,25 €) e perdite"
en  "🧾 Stripe technical fee (3%) and losses"
de  "🧾 Technische Stripe-Gebühr (3%) und Verluste"
zh  "🧾 Stripe技术费（3%）与损失"      (idem es, fr, pt, ja)
```

È la **sala di controllo del fondatore**. La chiave c'è in tutte e 8 le lingue: nessuna sonda
di completezza la vede. La vede solo il confronto dei numeri **dentro** lo stesso slot.
⚠️ Questo **estende B16 punto (a) e il passaggio 1**: il «3%» non stava solo in
`deploy/diventa-host.html`, sta anche qui e nel punto 4.

### 4. `deploy/kit-marketing.html:118` chiavi `box2`, `msg1`, `msg2`, `msg3` — il kit di reclutamento promette 3% in 7 lingue

`box2` è l'avviso che dice *«dillo sempre, anche quando non te lo chiedono»*:

```
it   "…una tariffa tecnica del 5% + 0,25 € a prenotazione, in ogni periodo — anche
      durante lo 0%. Sugli annunci prezzati in valuta diversa dall'euro è 7% + 0,25 €,
      perché il circuito deve convertire. Copre il costo di incassare dall'ospite e di
      bonificare all'host (Stripe)."
en   "…a fixed 3% technical fee on the transaction amount, in every period — even during
      the 0%. It covers the card cost (Stripe): on that line we earn nothing."
```

Due difetti in una riga, e il secondo è peggiore del primo:
1. la cifra è **3%** contro **5% + 0,25 €** (e le 7 lingue **non nominano affatto** il 7% in
   valuta estera, che l'italiano dichiara);
2. le 7 lingue aggiungono **«on that line we earn nothing»** / «an dieser Stelle verdienen wir
   nichts» / «这一项我们不赚一分钱». Con 5% + 0,25 € **quella riga è il margine**, non un
   pareggio: l'italiano infatti non lo dice.

`msg1`, `msg2`, `msg3` sono i **messaggi pronti da copiare e mandare a un host**: stessa
frattura (`it` 5% + 0,25 €, le altre 7 «3% technical fee»).
⛔ **Sommato al passaggio 1**, il canale di reclutamento dice oggi **tre cifre diverse**: 4%
nell'email (`fase89:189` ripiego a 400 bps), 3% nel kit in 7 lingue, 5% + 0,25 € nel kit in
italiano.

### 5. `deploy/contratto-host.html:30-33` e `:46-48` — due lingue, e il ripiego opposto a quello del server

Il contratto esiste in **2 lingue su 8** (`fase163_accettazioni.py:280-282`, `it` ed `en`) —
già misurato da **B18 punto 2**. La cosa nuova è che **la riparazione vive su un lato solo**:

- **server**: `fase163_accettazioni.py:345-355` `lingua_contratto_servita()` ripiega
  sull'**inglese**, con il commento che spiega perché l'italiano era sbagliato
  («un host tedesco, francese, spagnolo, portoghese, giapponese o cinese apriva il documento
  che deve firmare e lo leggeva in italiano»);
- **pagina**: `deploy/contratto-host.html:46-48`
  `return (u==='en'||u==='it')?u:(b==='en'?'en':'it');` — qualunque browser che non sia `en`
  ottiene **`it`**. E `<html lang="it">` a `:2`, fisso.

Quindi il comportamento che `fase163` è stato scritto per impedire **accade ancora**, perché è
la pagina a scegliere la lingua da chiedere. Il selettore offre **2 bottoni** (`:31-32`) dove
tutte le altre 11 pagine offrono **8 opzioni**.

### 6. `deploy/host.html:97` e `:136` — il link al contratto perde la lingua; `:976` la porta

Nella **stessa pagina**, lo stesso documento viene raggiunto in due modi:

```
:97   <a href="/contratto-host.html" ...>Contratto Host</a>     ← senza ?lang=
:136  <a href="/contratto-host.html" ...>Contratto Host</a>     ← senza ?lang=
:976  doc = await getJson('/api/legale/contratto-host?lang='+LANG);   ← con la lingua
```

`:976` serve a prendere **versione e impronta vive del contratto per salvarle come prova
d'accettazione**. Quindi: la prova firmata registra `lang=LANG` (per un host `de` il server
serve `en` e registra `en`), mentre il testo che l'host ha **davvero letto** cliccando `:97`
è, per il punto 5, **italiano**. **La prova dice una lingua, l'occhio ne ha vista un'altra.**

### 7. `fase83_server.py:672` `pagina_alloggio_html` — la pagina che Google indicizza per ogni annuncio del mondo è congelata in italiano

Delle **7 pagine HTML che il server genera**, **4 sono localizzate** e **3 sono `lang="it"`
fisso**:

| riga | funzione | lingua |
|---|---|---|
| `:1242` | `pagina_voucher_html` | `lang="%s"` ✅ |
| `:1332` | `pagina_ricevuta_html` | `lang="%s"` ✅ |
| `:1460` | `pagina_recensione_html` | `lang="%s"` ✅ |
| `:1490` | `pagina_voucher_non_valido_html` | `lang="%s"` ✅ |
| **`:672`** | **`pagina_alloggio_html`** | **`lang="it"`** 🔴 |
| `:1542` | `pagina_azione_html` | `lang="it"` (punto 16) |
| `:1685` | `pagina_login_gate` | `lang="it"` (punto 16) |

`pagina_alloggio_html` (`:606`) **non ha nemmeno il parametro `lingua`** nella firma, mentre le
quattro localizzate ce l'hanno. È la pagina server-rendered crawlabile con JSON-LD — quella che
un ospite di qualunque paese apre arrivando da Google. Dentro, in italiano fisso:

- `:679` `"<p>Prezzo: %s %s / notte</p>"`;
- `:681` `"<a href=\"/?slug=%s\">Prenota su BookinVIP</a>"`;
- `:642` `"<h2 id=\"faq\">Domande frequenti</h2>"`;
- `:624` `servizi = "".join("<li>%s</li>" % e(str(s)) ...)` — stampa il **codice grezzo**
  (`wifi`, `aria_condizionata`), **senza passare da `ETICHETTE_SERVIZI`**, che esiste a
  `fase61_localizzazione.py:78-89` **in tutte e 8 le lingue**. Il dizionario c'è, questa pagina
  non lo apre: è uno scompagnamento fra un dizionario completo e il posto che dovrebbe usarlo.

---

## 🟠 MEDI (8)

### 8. `deploy/host.html:502` chiave `ref_p` — due promesse di referral diverse a seconda della lingua

```
it  "…il nuovo host riceve subito €10 di benvenuto, e tu ricevi €40 di credito quando lui
     riceve le sue prime 3 prenotazioni. (Credito usabile sulle tue commissioni.)"
en  "…the new host gets €10 welcome right away, and you get €40 credit once they receive
     their first 3 bookings."
es  "Comparte tu enlace: cuando un anfitrión se registra, ambos recibís un crédito."
de/fr/pt/ja/zh  idem: «un credito», senza cifre e senza condizione.
```

È l'**unica** chiave, su 5.830 coppie HTML, la cui traduzione è fuori scala in lunghezza
(sonda: rapporto `len(lingua)/len(it)` fuori dall'intervallo 0,55–1,9 sulle lingue latine —
`it` 183 caratteri, `es` 78, `pt` 78, `fr` 84, `de` 88). La versione corta è la **vecchia**:
i sei sono rimasti indietro di una revisione, e la revisione aveva aggiunto **due importi e una
condizione**.

### 9. `deploy/host.html` — 22 `placeholder=`, **0** marcatori di traduzione

| pagina | `placeholder=` | marcatori (`data-i18n-ph` / `data-tph`) |
|---|---|---|
| **`host.html`** | **22** | **0** |
| `admin.html` | 7 | 6 |
| `bunker.html` | 6 | 8 |
| `index.html` | 4 | 3 |
| le altre 10 | 0 | 0 |

`host.html` è **l'unica pagina del sito che ha suggerimenti nei campi e nessun modo di
tradurli**. Almeno 12 dei 22 sono prosa italiana, non esempi neutri:
`"Codice fiscale / TIN del tuo Paese (es. IT: CF, DE: Steuer-ID, US: SSN)"`,
`"Partita IVA / VAT (se ce l'hai)"`, `"Indirizzo fiscale (via, città)"`,
`"IBAN (dove ricevi i bonifici)"`, `"Paese (es. IT)"`,
`"Riferimento prenotazione (es. a5d6...)"`, `"Luminoso appartamento nel cuore di Roma, a 5
minuti dal Colosseo..."`, `"Casa a Roma"`, `"chiave host"`, `"Rispondi..."`, `"es. REF123"`,
`"B&B Il Sole"`.
✅ Riconferma indipendente del punto 3 già segnalato **e non contato** dal passaggio 5.

### 10. `collaudi/occhio_del_fondatore.py` — verde pieno sopra 239 chiavi mancanti

Eseguito oggi (sola lettura), dà:

```
  admin.html    191 parole   191 tradotte   0 FERME   OK
  host.html     776 parole   773 tradotte   3 FERME   OK
  parole visibili che restano in italiano su TUTTO il sito: 10
  Nessuna pagina lascia lo straniero a leggere italiano.
```

Il verdetto è **corretto per quello che misura** e **cieco per quello che serve**: lo strumento
conta se un testo sta **dentro un elemento marcato**, cioè se la traduzione **può avvenire**.
Non guarda se la traduzione **c'è**. Misurato: nel file ci sono **zero occorrenze** di un
codice lingua (`grep -n "'de'\|\"de\"\|dizionar"` → 0 righe utili; le uniche due occorrenze di
«lingue» sono nel testo stampato a `:23` e `:189`).
🔑 È la stessa forma di [bookinvip-mutante-lasciato-in-produzione]: **ogni guardia deve
dichiarare il suo denominatore**. Questa dice «Nessuna pagina lascia lo straniero a leggere
italiano» — vero — mentre lo lascia a leggere **inglese** su 239 etichette.

### 11. `test_profondo_lingue.py:534-546` — l'unica guardia sulle pagine di `deploy/` copre 2 file su 14, e non confronta le chiavi

`test_profondo_lingue.py` è una guardia seria: il suo invariante **I1** («ogni etichetta esiste
in tutte e 8 le lingue») è verificato su `SRV.ETICHETTE_UI` (`:233`), su servizi e stati
(`:238`), sulle email (`:243`). Tutti dizionari **Python**, e infatti lì la copertura è piena.

Sulle pagine servite, l'unico test è
`test_grazie_e_annullato_hanno_le_8_lingue_e_ripiegano_su_inglese` (`:534`), e:

- copre **`grazie.html` e `annullato.html`** — le due pagine più piccole del sito, **5 chiavi
  l'una**;
- verifica solo che il **blocco** `lg:{` esista (`assertRegex(sorgente, r"\b%s\s*:\s*\{" % lg)`,
  `:542`), **mai che le chiavi dentro combacino**.

`host.html`, `admin.html`, `bunker.html`, `commissioni.html`, `diventa-host.html`,
`guida-operativa.html`, `kit-marketing.html`, `partner.html` — cioè **5.798 delle 5.830 coppie
HTML** — sono fuori dal denominatore di ogni guardia. Cercato in tutti i 406 `test_*.py`:
nessuno apre il dizionario `TR` di `host.html` o `admin.html`.

### 12. `fase61_localizzazione.py:67-73` — la notifica di cancellazione all'host esiste in 5 lingue su 8

`NOTIFICHE["nuova_prenotazione"]` (`:58-66`) ha tutte e 8 le lingue.
`NOTIFICHE["cancellazione"]` (`:67-73`) ne ha **5**: mancano **`pt`, `ja`, `zh`**.
Ripiego a `:130-133` (`_scegli` → `self._default` → `"en"`). Modulo **raggiunto** dalla
produzione. Quindi un host brasiliano, giapponese o cinese riceve **l'arrivo di una
prenotazione nella sua lingua e la cancellazione in inglese**.
✅ Riconferma indipendente del punto 4 già segnalato **e non contato** dal passaggio 5.

### 13. `fase90_marketing.py:37` — il motore marketing parla 5 lingue su 8, e scarta le altre in silenzio

```
:37   LINGUE = ("it", "en", "es", "fr", "de")          ← 5
:83   _TESTI        host/guest/referral × 5 lingue     ← mancano pt, ja, zh
:127  _TITOLO_CARD  host/guest/referral × 5 lingue     ← idem
:141  _LINGUE_NOME  8 lingue                           ← l'unico dizionario completo del file
```

Tre cose, in fila:
- `:141` prova che **la lista delle 8 lingue era sotto gli occhi** di chi ha scritto il file:
  `_LINGUE_NOME` serve solo a dire all'IA in che lingua riscrivere, e ce le ha tutte e 8.
- `:272` `esegui_campagna` fa `lng = [l for l in lingue if l in LINGUE] or list(LINGUE)`:
  chiedere una campagna in giapponese **non dà errore e non dà un post** — la lingua sparisce.
  **Taglio silenzioso.**
- `:138` `_lng()` ripiega su **`"it"`**, non su `en` come tutto il resto del prodotto.
- `fase94_scheduler_campagna.py:29` importa proprio quel `LINGUE` e lo usa come default del
  `tick` (`:99`, `:114`); il server lo avvia a `fase83_server.py:10515` se
  `CAMPAGNA_AUTO_GIORNI` è impostata.

### 14. `fase83_server.py:10521` — il commento dice «tutte», il codice significa 5 su 8

```python
# lingue dei post (CAMPAGNA_LINGUE="it,en"); vuoto -> default del motore (tutte).
```

Il «default del motore» è `fase90_marketing.py:37`, cioè **5 lingue su 8**. Chi legge questa
riga per decidere se impostare `CAMPAGNA_LINGUE` conclude che non serve. È un numero scritto in
un commento che **ha smesso di essere vero** quando il prodotto è passato da 5 a 8 lingue.

### 15. `fase97_inbound_seo.py:28` — il prodotto parla 8 lingue, l'imbuto SEO ne promette 13

```
fase61_localizzazione.py:41  LINGUE_SUPPORTATE = ("en","it","es","fr","de","pt","ja","zh")   ← 8
fase97_inbound_seo.py:28     LINGUE = (... 8 ..., "ru", "id", "th", "vi", "ko")               ← 13
```

Le 5 in più (`ru`, `id`, `th`, `vi`, `ko`) hanno **testi completi** (`_T` a `:257`, `_FAQ` a
`:441`, `TERRITORIO_DEFAULT` a `:46`) e **finiscono negli hreflang** che il sito dichiara a
Google (`:580-582` `locali_hreflang()`, emessi a `:659-665`). Ma **nessuna pagina del prodotto
sa servirle**: i selettori di lingua hanno 8 opzioni, `BV.linguaIniziale` (`deploy/app.js:97`)
ripiega su `en`. Un visitatore coreano viene attirato da una landing in coreano e al primo clic
trova l'inglese. È lo scompagnamento nella direzione «o viceversa»: presente in un posto,
assente in un altro.

### 16. `fase89_jurisdiction_outreach.py:197`, `:248`, `:40` — l'outreach generico è indietro di una revisione rispetto a quello di Roma

Due funzioni di reclutamento, due qualità:

| dizionario | riga | lingue |
|---|---|---|
| `_TEMPLATE_ROMA` (campagna Roma) | `:217` | **8 su 8**, con vocativo a `:279-282` in 8 lingue |
| `_TEMPLATE` (outreach per giurisdizione) | `:197` | **6 su 8** — mancano `ja`, `zh` |
| vocativo del generico | `:248` | **3** — `{"en":"Hello","es":"Hola","it":"Gentile struttura"}` |
| `LINGUA_PER_PAESE` | `:40-44` | 16 paesi → **6 lingue** (mai `ja`, mai `zh`) |

Conseguenze misurate: `:246` fa `_TEMPLATE.get(lng, _TEMPLATE["en"])` → chiamando con
`lingua="ja"` esce **inglese, in silenzio**; `:248` `.get(lng, "Hello")` → un host **tedesco
senza nome** riceve un'email tedesca che comincia con **«Hello»**. E `LINGUA_PER_PAESE` non
copre JP/CN/TW/HK/KR/TH/VN: tutti in inglese per costruzione.
La versione Roma dimostra che il modo giusto era già scritto **nello stesso file**.

---

## 🟡 MINORI (4)

### 17. `fase83_server.py:1542` e `:1685` — due pagine di servizio congelate in italiano

`pagina_azione_html` (`:1510`, l'esito della decisione dell'host su una richiesta) e
`pagina_login_gate` (`:1561`, la porta di accesso) sono `lang="it"` con testi solo italiani
(`:1538-1540`: «Link non valido», «Non riusciamo a leggere questo link.», «Apri il pannello
host per gestire le tue prenotazioni.»), mentre le pagine sorelle di voucher e ricevuta sono
localizzate. Minori perché sono pagine di transito, non di decisione.
✅ Riconferma indipendente del punto 2 già segnalato **e non contato** dal passaggio 5.

### 18. `fase83_server.py:725` — il feed RSS dichiara `<language>it</language>` per tutti gli annunci del mondo

`feed_rss_xml` (`:694`) emette `"<language>it</language>"` fisso (`:725`) su un feed che
contiene gli annunci di **qualunque città** e che esiste apposta per la sindacazione
automatica. Gli aggregatori usano quel campo per filtrare.

### 19. 13 chiavi tradotte e mai referenziate da nessuno

Criterio deterministico, non a occhio: una chiave presente in **N** lingue e citata
**esattamente N volte** in tutto il file non è referenziata da nessuna parte. Controllato anche
`deploy/app.js` (0 occorrenze per tutte e 13).

| file | chiave | lingue | nota |
|---|---|---|---|
| `host.html:502` | `accetto_e`, `dev_terms`, `host_id`, `l_slug`, `m_slug_l`, `no_req`, `req_h`, `req_p` | **8** | tradotte in tutte e 8 e usate da nessuno |
| `host.html:502` | `dev_clausole`, `foto_rimossa` | 2 (`it`,`en`) | |
| `admin.html:200` | `err_rete` | **8** | |
| `admin.html:200` | `bk_ok`, `ctr_conferma` | 2 (`it`,`en`) | |

🔑 Il contrasto è il punto: **8 chiavi che nessuno legge sono tradotte in 8 lingue**, mentre
**146 che finiscono a schermo ne hanno 2**. Il lavoro di traduzione c'è stato; non è stato
guidato da chi decide cosa si vede.

### 20. Due dizionari a 5 lingue in moduli mai raggiunti dalla produzione

- `fase129_traduzione_recensioni.py:17-23` `_SPIE` — 5 lingue (`it en es fr de`). È
  l'euristica che **rileva la lingua di una recensione**: una recensione in `pt`, `ja` o `zh`
  non trova nessuna spia, `rileva_lingua` (`:26-32`) restituisce il default `"en"`, e a `:51-55`
  la recensione viene poi «tradotta» **dall'inglese**. Modulo **NON raggiunto** da
  `main_casavip.py`.
- `assistente_gestionale.py:570` `TERMINI` — 5 lingue. Modulo **NON raggiunto**.

*(numerati 17-20 perché il punto 19 raccoglie due file: il conto delle incongruenze resta 19.)*

---

## ✅ VERIFICATI E SCARTATI (11) — scritti apposta perché non si riaprano

1. **`fase185_testi_legali.py:98` e `:703`** — i due documenti legali (termini e privacy)
   esistono in **8 lingue su 8**, con lo **stesso numero di titoli numerati** in ognuna
   (12 e 10 rispettivamente). `ja` e `zh` sono più corti in caratteri (1.773 e 1.262 contro
   3.924 dell'italiano): è **densità del CJK**, non testo mancante — la struttura combacia.
2. **`fase86_email.py:137`** — 62 slot × 8 lingue, **nessuna chiave mancante**, nessun
   segnaposto perso. È la guardia I1 di `test_profondo_lingue.py:243` che lo tiene in piedi.
3. **`fase83_server.py:116` `ETICHETTE_UI`** — 165 chiavi × 8, nessun buco. Guardia a
   `test_profondo_lingue.py:233`.
4. **`fase198_blog.py` (`:28,34,60,158`) e `fase200_campagna_persuasiva.py` (`:98,104`)** —
   8 lingue piene, chiavi allineate.
5. **`deploy/app.js:143` `BV.ERR_FRASI` e `:162` `BV.ERR_AUTH`** — 4×8 e 38×8, nessun buco.
6. **`fase97_inbound_seo.py:41` `REGIONI_HREFLANG` senza `it` e `ja`** — **è voluto e
   dichiarato** a `:37-40`: «it/ja restano solo-lingua (mercato unico dominante)». Non è un
   buco: è targeting geografico.
7. **`annullato.html` e `grazie.html` senza selettore di lingua** — scelta deliberata,
   spiegata nel commento a `annullato.html:35-37`: si segue `localStorage 'lang'`, cioè la
   scelta già fatta sul sito. Dizionari completi (5 chiavi × 8) e ripiego inglese a `:57`.
8. **`privacy.html` / `termini.html` con `<select id="lang">` vuoto** — riempito da JS con le
   **8** lingue (`privacy.html:34-38`, `:110-114`). Il corpo del documento arriva dal motore.
9. **I 27 «numeri discordi» dei `.py`** — **tutti falsi positivi**. Il grosso è il giapponese
   che scrive con una cifra ciò che le lingue latine scrivono a parole (`"1人あたり"` = «a
   testa», `"1泊単位"` = «a notte», `"3ステップ"` = «in 3 passi» dove l'inglese scrive
   «Three steps»); poi il cinese `"房客0手续费"` = «0% commissioni all'ospite» senza il segno
   `%`; poi `regola_garanzia` (`fase83_server.py:151`) dove `fr`/`de`/`ja` dicono «24 ore» una
   volta sola e poi «passato quel termine» invece di ripetere il numero. Stesso significato.
10. **Separatore decimale e spazio prima del `%`** — `en` `"0.25"` contro `"0,25"`, `fr`/`de`
    `"50 %"` e `"2 000"` contro `"50%"` e `"2.000"`: convenzioni tipografiche corrette, non
    numeri diversi.
11. **`commissioni.html:95` `ab_host` («15,5%» / «15.5%») e `ab_note`** — stessa cifra, stesso
    anno; solo separatore e formato data.

---

## ⛔ COSA È RIMASTO FUORI (D18 punto 3)

Un taglio silenzioso fa sembrare «coperto» ciò che nessuno ha visto. Ecco i tagli, dichiarati:

1. **Non ho giudicato la QUALITÀ di una sola traduzione.** Nessun madrelingua ha letto una
   riga. Questo referto misura se la traduzione **esiste** e se dice **gli stessi numeri e gli
   stessi segnaposto**: non se è scritta bene, e nemmeno se è corretta. Una frase tedesca
   sbagliata ma presente e coerente nei numeri qui risulta **verde**.
2. **Non ho eseguito il sito.** Nessun browser, nessuna chiamata all'API, nessun giro sul VPS.
   L'unica cosa eseguita è `collaudi/occhio_del_fondatore.py`, che è di sola lettura e non
   tocca niente. Tutte le catene descritte (il ripiego inglese, il contratto in italiano, la
   prova firmata) sono **ricostruite dal codice, non riprodotte**: chi le riparerà deve prima
   riprodurle.
3. **Gli slot costruiti a runtime non sono nel denominatore.** Il confronto testuale prende
   solo stringhe **letterali** (costanti e concatenazioni di costanti): le `f-string` e tutto
   ciò che è assemblato da variabili è **saltato**. Se una traduzione viene composta a runtime
   con una cifra diversa, questo passaggio non la vede.
4. **`collaudi/` e i 406 `test_*.py` non sono stati setacciati per dizionari.** Ho aperto solo
   `occhio_del_fondatore.py` e `test_profondo_lingue.py`, perché sono le due guardie che
   dichiarano di misurare le lingue. Se un'altra guardia dà per completo un dizionario che non
   lo è, questo referto non lo sa.
5. **I moduli non raggiunti sono stati contati, non letti per intero.** Per
   `fase129_traduzione_recensioni.py` e `assistente_gestionale.py` ho letto le funzioni
   interessate; degli altri so solo che i loro dizionari sono completi.
6. **La discordanza 63 contro 59 moduli non raggiunti non è risolta** (vedi Denominatore).
   Non è il tema di questo passaggio; **quel numero va rimisurato prima di riusarlo**.
7. **«Chiave mai referenziata» vale sul file più `deploy/app.js`.** Non ho cercato usi da
   `sw.js`, da un altro `.html`, né dal server. Le 13 del punto 19 sono quindi «mai
   referenziate **lì**», che per una chiave `TR` locale è la cosa che conta, ma non è una
   prova universale.
8. **Non ho misurato quanti host o annunci stranieri esistano.** Le voci gravi 1, 2, 5 e 6
   descrivono **cosa fa il codice**, non quante persone l'hanno già subito. Con **0 host
   firmati in produzione** (stato noto) sono tutte **latenti** — ed è la finestra in cui
   costano zero.
9. **Non ho aperto il VPS.** `CAMPAGNA_LINGUE` e `CAMPAGNA_AUTO_GIORNI` citati al punto 13-14
   sono letti dal codice (`fase83_server.py:10512`, `:10521`), **non** da ciò che gira adesso:
   sul VPS le variabili d'ambiente **vincono sul codice**.
10. **Il file `deploy/index.html` è modificato nell'albero di lavoro** rispetto a `584f0e9`.
    Le misure su quel file sono state fatte sulla **versione sul disco**, non su quella del
    commit.
11. **Non ho riparato niente**, come prescrive B19.
