# B19 — PASSAGGIO 14 · DOVE VIVE IL NUMERO DELLA COMMISSIONE

> **Referto di misura, non lista di cose da fare.** Sola lettura: nessun file di prodotto
> toccato (**i 10 file già modificati nell'albero di lavoro sono stati solo LETTI**), nessuna
> riparazione, nessuna suite, nessun commit, nessun giro sul VPS, nessuna chiamata di rete,
> nessun heredoc.
>
> Misurato il **2026-08-25**, ramo `master`, `HEAD = 3ceb4c5`, sull'albero di lavoro.
> Numeri di riga = **file come stanno sul disco adesso**.

---

## ⛔ PRIMA DI TUTTO: IL 15 NON È LA COMMISSIONE

La domanda dice «15 o 0.15 come commissione». **Misurato: in questo prodotto il 15% non è una
commissione.** È la **penale che l'host paga se annulla una prenotazione già pagata**
(`PENALE_HOST_BPS = 1500`, `fase83_server.py:924`, usata a `:6379`).

Le commissioni vere sono altre tre, e nessuna è 15:

| Numero | Cos'è | Fonte |
|---|---|---|
| **10%** | commissione marketplace a regime | `COMMISSIONE_BPS` in `main_casavip.py`, default `"1000"` |
| **0 → 8 → 10%** | rampa di lancio (90gg / 1 anno / regime) | `fase98_policy_commissione.py` (`LANCIO_BPS_FASE1/REGIME`) |
| **5%** | canale **diretto** dell'host | **`fase98_policy_commissione.py:37` `BPS_DIRETTO = 500`** |
| *(5% + 0,25 €)* | tariffa **tecnica**, non è commissione | `PAGAMENTO_BPS` |

⚠️ **E c'è un 15% che SI SPACCIA per commissione**, ed è un difetto nuovo:
`fase97_inbound_seo.py:613` e `:740` dichiarano `commissione_bps: int = 1500` come **valore
predefinito** del generatore delle landing di città e di `llms.txt` — cioè **15%**, contro il
10% vero. Oggi non esce: entrambi i chiamanti passano il valore giusto
(`fase83_server.py:10928` e `:10954`, da `bps = COMMISSIONE_BPS` letto a `:10912`). È una
trappola armata: **una chiamata senza quell'argomento pubblica «15%» su 2.990 landing**, e i
test lo fanno già (`test_fase97_inbound_seo.py:39`, `:55`, `:60` chiamano senza `commissione_bps`).

Il resto del referto misura **i due numeri che il fondatore ha chiesto**: il **15** (penale) e
il **5 diretto**.

---

# 1. OGNI PUNTO DOVE COMPARE IL 15 — file e riga

### ✅ La fonte, e i 12 punti che la LEGGONO

```
fase83_server.py:924               PENALE_HOST_BPS = 1500                     <== LA FONTE
fase83_server.py:6379              commissione_cents(guest, PENALE_HOST_BPS)  (il calcolo vero)
fase185_testi_legali.py:89-90      _penale() importa PENALE_HOST_BPS // 100
fase185_testi_legali.py:643        PENALE=_penale()  ->  interpola {PENALE} in:
fase185_testi_legali.py:150          contratto  it
fase185_testi_legali.py:222          contratto  en
fase185_testi_legali.py:298          contratto  es
fase185_testi_legali.py:374          contratto  fr
fase185_testi_legali.py:450          contratto  de
fase185_testi_legali.py:524          contratto  pt
fase185_testi_legali.py:573          contratto  ja
fase185_testi_legali.py:615          contratto  zh
deploy/contratto-host.html:61       non contiene il numero: lo chiede all'API (fonte unica)
```

### ❌ I punti che lo SCRIVONO A MANO

```
fase177_financial_controller.py:667  causale="penale 15% cancellazione host"   <== NEL GIORNALE
fase185_testi_legali.py:92           return 15            (ripiego dell'except)
deploy/guida-operativa.html:87       <li data-i18n="c4_2"> ...host paga il 15% di penale
deploy/guida-operativa.html:126      c4_2  it   ...host paga il 15% di penale
deploy/guida-operativa.html:127      c4_2  en   ...host pays a 15% penalty
deploy/guida-operativa.html:128      c4_2  es   ...el anfitrión paga un 15% de penalización
deploy/guida-operativa.html:129      c4_2  fr   ...l'hôte paie 15% de pénalité
deploy/guida-operativa.html:130      c4_2  de   ...Gastgeber zahlt 15% Strafgebühr
deploy/guida-operativa.html:131      c4_2  pt   ...anfitrião paga 15% de multa
deploy/guida-operativa.html:132      c4_2  ja   ...ホストは15%のペナルティを支払う
deploy/guida-operativa.html:133      c4_2  zh   ...房东支付 15% 违约金
deploy/host.html:189                 <p data-i18n="hc_p"> ...una penale del 15%
deploy/host.html:503                 hc_p         it   ...una penale del 15%
deploy/host.html:503                 hc_conferma  it   ...pagherai una penale del 15%.
deploy/host.html:504                 hc_p         en   ...a 15% penalty
deploy/host.html:504                 hc_conferma  en   ...you will pay a 15% penalty.
```

### ⚪ I 6 punti dove il 15 è in un commento o in una docstring (diventano bugie, non guasti)

```
fase83_server.py:6345   commento: "la differenza (netto - penale 15%)"
fase83_server.py:6376   commento: "PENALE host = 15% del valore prenotazione"
fase83_server.py:6385   commento: "'rimborsato' con penale 15% registrata"
fase177_financial_controller.py:21    docstring: "la penale 15% si compensa dai..."
fase177_financial_controller.py:652   commento: "emette la ND 15%"
fase183_carta_offsession.py:5         docstring: "i debiti dell'host (penale 15% quando...)"
```

### ⚫ I 15 che NON sono la penale (esclusi dal conteggio, dichiarati)

`fase106_dynamic_pricing.py:26` (weekend +15%) · `fase109_referral_host.py:23` (scaglione
referral) · `fase125_confronto_guest.py:17` (markup OTA) · `fase67_coda_intelligente.py:79-80`
(sconto coda) · `fase71_commitment.py:60` (voucher 115%) · `fase69_trasparenza.py:45,48` e
`deploy/commissioni.html` righe 58-62 e chiavi `bk_*/ab_*/ex_*/vr_*/ta_*/hw_*` (commissioni
**dei concorrenti**) · `fase171:89`, `fase175:30` (raggio POI 1500 m) · `deploy/admin.html:201`
e `:202` («Bunker attivo **15 min**»).

---

# 2. OGNI PUNTO DOVE COMPARE IL 5 DIRETTO

### ✅ La fonte, e i 5 punti che la LEGGONO

```
fase98_policy_commissione.py:37    BPS_DIRETTO = 500                          <== LA FONTE
fase98_policy_commissione.py:68    return ... bps_diretto  (la decisione vera, per 'fonte')
fase185_testi_legali.py:62,79      importa BPS_DIRETTO -> "diretto": BPS_DIRETTO // 100
fase89_jurisdiction_outreach.py:249,256   diretto=_pct(BPS_DIRETTO)
fase89_jurisdiction_outreach.py:283,290   diretto=_pct(BPS_DIRETTO)
fase83_server.py:3590              "commissione_diretto_pct": st["bps_diretto"] / 100
fase83_server.py:3913              "bps_diretto": st["bps_diretto"]
```

### ❌ I punti che lo SCRIVONO A MANO — **104 in 10 file**

**Il più grave, perché è un numero eseguibile e non un testo:**

```
fase83_server.py:9496   "commissione_bps": 500, "commissione": "5%"
                        (dentro _host_link_diretto: la risposta che l'host LEGGE nel pannello
                         quando genera il suo link. Non importa fase98, non lo consulta.)
```

**17 occorrenze fuori dai dizionari** (HTML statico, contratto, commenti, costanti):

```
deploy/commissioni.html:47    hero_p inline
deploy/commissioni.html:56    riga della tabella "NOI": 5% diretto
deploy/commissioni.html:83    cta inline
deploy/commissioni.html:84    cta inline
deploy/diventa-host.html:60   c1 inline
deploy/host.html:155          co_r4 inline: commissione 5% + tariffa tecnica 5% + 0,25 €
deploy/host.html:182          dir_h inline: "Il tuo link prenotazione diretta — solo 5%"
deploy/index.html:769         commento JS: ?fonte=diretto applica il 5%
deploy/kit-marketing.html:88  "• 5% soltanto sulle prenotazioni dei TUOI clienti diretti"
deploy/kit-marketing.html:110 after2 inline
fase163_accettazioni.py:101   CONTRATTO it: "(b) ... link diretto dell'Host: Commissione 5%"
fase163_accettazioni.py:227   CONTRATTO en: "(b) ... direct link: Commission 5%"
fase81_bootstrap_casavip.py:248  commento
fase83_server.py:3861            docstring
fase83_server.py:9473            docstring
fase98_policy_commissione.py:37  commento accanto alla costante
fase98_policy_commissione.py:65  docstring
```

**87 coppie (chiave, lingua) dentro i dizionari i18n**, su **21 chiavi distinte** in 5 file —
il dettaglio per chiave è nella sezione 5.

---

# 3. FONTE UNICA O NUMERO SCRITTO A MANO? — la risposta è: **tutte e due**

**Per tutti e due i numeri la fonte unica ESISTE.** E per tutti e due, **la stragrande
maggioranza delle comparse non la legge.** La prova sta nel rapporto:

| Numero | Fonte | Punti che DERIVANO | Punti scritti A MANO | Rapporto |
|---|---|---|---|---|
| **15** (penale) | `fase83_server.py:924` | **12** (di cui 8 lingue del contratto) | **16** + 6 commenti | 1 : 1,8 |
| **5** (diretto) | `fase98_policy_commissione.py:37` | **5** | **104** in 10 file | **1 : 21** |

💡 **La forma è quella già misurata dal passaggio 7, e questa è la sua terza comparsa:**
*il difetto non è l'assenza della fonte, è che la fonte non è quella che la superficie
raggiunge.* Qui si vede con una nitidezza che il passaggio 7 non aveva: **lo stesso numero, lo
stesso giorno, ha un canale FATTO BENE e un canale FATTO A MANO, e passano a due centimetri
l'uno dall'altro.**

Il caso da tenere come modello e il suo gemello sbagliato, fianco a fianco:

```
✅ fase185_testi_legali.py:89  -> _penale() -> {PENALE} -> il CONTRATTO in 8 lingue.
                                 Cambio la costante, il contratto cambia in 8 lingue. Da solo.

❌ deploy/guida-operativa.html -> "15%" battuto a mano in 8 lingue, chiave c4_2.
                                 Cambio la costante, la guida continua a dire 15%. In 8 lingue.
```

E il caso peggiore in assoluto, perché è **irreversibile**:

```
❌ fase177_financial_controller.py:667
   causale="penale 15% cancellazione host"
```

Quella stringa finisce nella **causale della Nota di Debito**, dentro il **libro giornale
immutabile** (`fase177`, catena di hash, nessun UPDATE possibile). Se domani la penale diventa
13%, ogni nuova nota continuerà a dichiarare «penale 15%» mentre addebita il 13% — e **le note
già emesse non si possono correggere per costruzione**.

---

# 4. SE CAMBI 15 → 13: **7 file, 22 punti**

```
1. fase83_server.py                 :924  la costante (+ 3 commenti: :6345, :6376, :6385)
2. fase177_financial_controller.py  :667  causale nel giornale (+ 2 commenti: :21, :652)
3. fase185_testi_legali.py          :92   il ripiego `return 15`
4. deploy/guida-operativa.html      :87 + :126,:127,:128,:129,:130,:131,:132,:133   (9 punti, 8 lingue)
5. deploy/host.html                 :189 + :503 (x2) + :504 (x2)                    (5 punti, 2 lingue)
6. fase183_carta_offsession.py      :5    docstring
7. collaudi/baseline_tariffe.txt    :61   l'impronta di fase83_server.py cambia -> la guardia
                                          delle tariffe si accende e la riga va ri-approvata
```

**Cosa NON va toccato, ed è la parte buona:**

- **il contratto in 8 lingue**: si aggiorna da solo (`fase185` interpola `{PENALE}`);
- **`deploy/contratto-host.html`**: non contiene il numero, lo chiede all'API;
- **i test**: `grep -rln "PENALE_HOST_BPS" test_*.py` → **4 file**
  (`test_admin_host_stesso_istante.py`, `test_copertura_critica.py`, `test_guida_operativa.py`,
  `test_testi_legali.py`) e **tutti leggono la costante**, nessuno scrive `15` a mano
  (`test_testi_legali.py:102`: `assertIn("%d%%" % (PENALE_HOST_BPS // 100), ...)`).
  **Zero test da modificare.**

⛔ **E una cosa non si può toccare affatto:** le Note di Debito già scritte nel giornale
diranno «penale 15%» per sempre. Non è un file: è una decisione già presa.

Per confronto, **se cambiassi il 5 diretto** servirebbero **10 file e 104 punti** in 8 lingue,
più `fase83_server.py:9496`. È lo stesso lavoro moltiplicato per cinque.

---

# 5. IL NUMERO DENTRO I TESTI TRADOTTI — dove, e in quante lingue

### Il 15 (penale)

| Dove | Chiave | Lingue | Come |
|---|---|---|---|
| `fase185_testi_legali.py:150-615` | contratto, art. cancellazioni | **8/8** | ✅ **interpolato** `{PENALE}` |
| `deploy/guida-operativa.html:126-133` | `c4_2` | **8/8** | ❌ **battuto a mano, otto volte** |
| `deploy/host.html:503-504` | `hc_p`, `hc_conferma` | **2/8** (it, en) | ❌ a mano; le altre 6 lingue **ripiegano sull'inglese** (`deploy/host.html:512`, difetto già contato dal passaggio 6) |

Quindi: **la stessa penale è scritta a mano in 10 lingue-testo diverse** (8 nella guida + 2 nel
pannello) e derivata correttamente in 8 (il contratto). L'host la legge in tre posti, e solo in
uno dei tre il numero segue davvero il codice.

### Il 5 diretto — 87 coppie (chiave, lingua) su 21 chiavi

```
deploy/commissioni.html   hero_p         8 lingue   it en es fr de pt ja zh
deploy/commissioni.html   us_host        8 lingue
deploy/commissioni.html   sim_p          8 lingue
deploy/commissioni.html   cta_h          8 lingue
deploy/commissioni.html   cta_p          8 lingue
deploy/diventa-host.html  c1_p           8 lingue
deploy/diventa-host.html  c1_t           8 lingue
deploy/host.html          dir_h          8 lingue
deploy/host.html          h_prezzo_osp   8 lingue
deploy/host.html          dir_p          8 lingue
deploy/host.html          co_r4          2 lingue (it, en)
deploy/host.html          co_p           1 lingua  (it)
deploy/kit-marketing.html after2         7 lingue
deploy/kit-marketing.html box1, msg2     ja, de
fase86_email.py           corpo benvenuto host   it en de ja pt zh
fase163_accettazioni.py   CONTRATTO      2 lingue (it, en)  <- il contratto FIRMATO
```

⚠️ **Due cose che questo elenco fa vedere e che vanno dette:**

1. **Il contratto host esiste in 8 lingue in `fase185` e in 2 in `fase163`.** Il 5% del canale
   diretto sta nel testo di `fase163` (`:101` it, `:227` en) — quello che l'host **firma**.
   È la conferma indipendente del difetto già contato dal passaggio 6 (*«il contratto esiste in
   due lingue sole»*): qui si misura **quale numero** ci sta dentro. **Non lo risommo.**
2. **Il conteggio per lingua non è uniforme** (8, 7, 2, 1). Le quattro chiavi che il primo giro
   dava a 5-6 lingue (`cta_h`, `cta_p`, `c1_t`, `dir_p`) le ho **ricontate a mano una per una**
   e sono **8 su 8**: era il filtro testuale a perderle, non la traduzione a mancare. Le uniche
   davvero parziali sono `co_r4` (2 lingue) e `co_p` (1), nel pannello host — coerente col
   passaggio 6.

---

## 🔎 IL METODO, E DOVE NON ARRIVA

Attrezzo: uno scanner in `scratchpad` che apre ogni riga di `deploy/*.html` e `fase*.py`,
estrae le coppie `chiave: "valore"` (anche con apici singoli e backtick), attribuisce la lingua
all'ultimo marcatore `xx:{` che precede la coppia **sulla stessa riga**, e tiene solo i valori
che contengono la percentuale cercata **in una frase che nomina il canale/la penale**
(filtro su `dirett|diret|direct|direkt|直接|您的|seus|tuoi` e su
`penal|multa|Strafgeb|pénalit|違約|违约`).

⛔ **I due limiti, dichiarati:**

1. **L'attribuzione della lingua sbaglia se un dizionario è spezzato su più righe.** Nei
   pannelli misurati ogni lingua sta su una riga sola, quindi qui regge — ma è il motivo per
   cui i conteggi «5 lingue su 8» vanno letti come **«almeno 5»**, non come «esattamente 5».
2. **Il filtro è testuale**: una frase che dice «5%» senza nominare il canale diretto non entra.
   Il caso noto è proprio `fase83_server.py:9496`, che l'ho trovato **a mano** e non col
   filtro. Possono essercene altri della stessa forma: **il 104 è un pavimento, non un tetto.**

Prima misura fatta e poi corretta, per onestà: il primo giro usava `\b5%` e **perdeva
giapponese e cinese** (in `に5%` non c'è un confine di parola Unicode). Rifatto con
`(?<![0-9])5\s*%`: da 56 a 104 occorrenze. **Il numero giusto è il secondo.**

---

## ✅ VERIFICATO E SCARTATO

1. **`deploy/contratto-host.html` non contiene nessuna percentuale**: la chiede all'API
   (`:61`, `/api/legale/contratto-host?lang=`). È il modello giusto per una pagina.
2. **Nessun test da aggiornare** per un cambio della penale: tutti e 4 leggono la costante.
3. **Il default 1500 di `fase97` oggi non esce**: entrambi i chiamanti di produzione passano
   `commissione_bps=bps` (`fase83:10928`, `:10954`). È armato, non sparato.
4. **`fase185` ha già una guardia sui suoi ripieghi**: il commento a `:68-70` cita
   `test_trasparenza_costi.test_i_ripieghi_di_fase185_combaciano_con_main` — nata dal difetto
   gemello sulla tariffa tecnica (4% contro 5%). **Quella guardia copre i ripieghi di fase185,
   non i testi degli HTML.**
5. **`collaudi/audit_coerenza_tariffe.py` esiste e legge `COMMISSIONE_BPS` da `main_casavip.py`**
   (`:41`) confrontandolo con i documenti. Non è nella batteria: si lancia a mano.
6. **I 15% dei concorrenti** (`fase69_trasparenza.py`, `deploy/commissioni.html`) **non sono un
   difetto qui**: sono dati di mercato. Che discordino fra loro è il difetto 8·«tabella dei
   concorrenti», già contato dal passaggio 8. Non risommato.
