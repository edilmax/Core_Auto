# B19 — IL PIANO DELLE RIPARAZIONI · una sola lista, costruita leggendo i nove referti

> **Referto di misura, non una lista di lavori parallela.** ⛔ Questo file **non sostituisce
> `RIPRENDI_QUI.md`** (REGOLA ZERO 3): è il **raggruppamento** delle voci già scritte nei nove
> referti, ordinato per chi si fa male per primo. Quando una riga di qui diventa un lavoro,
> quel lavoro si scrive **là**, non qui.
>
> Costruito il **2026-08-25** in **sola lettura**, su `HEAD = cb45c80` (i nove referti uniti su
> `master` con la richiesta 106). Nessuna riparazione fatta, nessun `fase*.py` toccato, nessuna
> suite eseguita, nessun commit. **Questo file resta NON committato.**
>
> ⛔ **Le percentuali non sono scritte per esteso di proposito.** `collaudi/audit_coerenza_tariffe.py`
> conta come «cifra nuova» ogni percentuale che compare accanto a una parola di costo: scriverle
> qui manderebbe rossa la CI del prossimo giro per un documento che non le pretende. Le cifre
> vere stanno nei nove referti, che le portano con `file:riga`.

---

## RISULTATO IN UNA RIGA

**247 voci** nei nove referti si raggruppano in **19 giri di riparazione** più **12 decisioni
che non sono riparazioni**. Costo misurato: **19 giri × (26 min di suite + 11,9 min di CI)** =
**circa 12 ore di sola verifica**, senza contare il tempo di scrittura del codice.

---

## ⛔ RIMISURATO CONTRO IL CODICE IL **2026-08-28** — leggere questo PRIMA di aprire un giro

> **Perché esiste questo blocco.** Questo piano è stato costruito il **2026-08-25 in sola
> lettura**, e da allora il codice è andato avanti. Il 28 agosto una sessione ha preso il primo
> giro di questa lista e stava per ripararlo: **era già stato fatto due giorni prima.** Un piano
> è un **artefatto**; il codice è il **meccanismo**. Quando i due dicono cose diverse, **vince il
> codice**, e questa lista va rimisurata prima di spenderci sopra un'ora.

**16 giri sondati su 19, uno per uno, contro il codice di `e4996c2`. Uno solo era chiuso.**

| giro | esito della rimisura | la prova, misurata |
|---|---|---|
| **A1** | ✅ **CHIUSO** 26/08 | `guardia_contratto_firmato.py` → `VERDE · EXIT=0` |
| **A3** | 🔴 aperto | tre tetti diversi sull'upload in due configurazioni `nginx` |
| **A4** | 🔴 aperto | zero occorrenze di «conservato»/«per legge» in `fase156_erasure.py` |
| **A5** | 🔴 aperto | `data.get("paese","")` seguito da `UPDATE … paese=?` incondizionato |
| **A2** | 🔴 aperto | in `fase131_payout_dashboard.py` lo stato `pagato` è **terminale e nessuno ci entra** |
| **B1** | 🔴 **aperto E VIVO IN PRODUZIONE** ⬇️ | vedi il riquadro qui sotto |
| **B2** | 🔴 aperto | `fase188_paga_struttura.py`: `GATEWAY_BPS` e `GATEWAY_FISSO_CENTS` ancora discordi dal contratto |
| **B4** | 🔴 aperto | `_transazioni_bloccate` compare **0 volte** nei tre gestori nominati |
| **C1** | 🔴 aperto | «certificat…» in `index.html` e `bunker.html`, «cancellazione gratuita» in `index.html`, «zero attese» in `diventa-host.html` |
| **C4** | 🔴 aperto | il pannello marketing offre **5** caselle lingua su 8 (`pt ja zh` non ci sono) |
| **C5** | 🔴 aperto | «in Italia, il Garante» compare **anche nella versione inglese** della privacy |
| **D2** | 🔴 aperto | **44** moduli aprono il database per conto loro invece di usare `fase23_datastore` |
| **D1** | 🟡 **in parte chiuso** | `f7faa5b` ha chiuso B20 (`TODO` come sottostringa) e ha escluso `collaudi/audit` da `audit_coerenza_tariffe.py` (riga `ESCLUDI_PERCORSI`). Il resto del giro è aperto |
| **D3** | 🔴 aperto | nessuna rotta `/bunker` senza estensione nel server |

⛔ **NON rimisurati, e non si scrivono come chiusi:** **B3** · **C2** · **C3** · **D4-D6**.

### 🔴 IL PRIMO LAVORO ADESSO È **B1**, e il motivo è che è già falso verso una persona vera

```
main_casavip.py                       os.environ.get("PAGAMENTO_BPS", "500")
fase185_testi_legali.py               os.environ.get("PAGAMENTO_BPS", "500")
fase89_jurisdiction_outreach.py       os.environ.get("PAGAMENTO_BPS", "400")   <- l'EMAIL agli host
```

e il moltiplicatore sta nel referto **16** di questa stessa cartella, l'unico passaggio che è
andato a guardare la macchina vera: **`PAGAMENTO_BPS` non è impostata in produzione**, quindi
valgono i ripieghi del codice — **e divergono**. L'email di reclutamento promette la cifra del
suo ripiego, il motore addebita quella del suo.

⇒ È l'unico difetto aperto che ha la proprietà per cui A1 stava in cima: **il costo cresce col
tempo.** Ogni host reclutato da adesso è un host a cui è stato scritto un prezzo che non
pratichiamo. E la riparazione è la più pulita del piano — la fonte unica **esiste già**
(`ConfigCasaVIP`): non si scrive una costante, **si cancellano i ripieghi**.

⚠️ **E il numero che conta non è 247.** Le voci del passaggio 4 (112 funzioni mai chiamate) e
quelle del passaggio 7 (20 valori sparsi, di cui 17 con la fonte unica **già scritta**) **non si
riparano scrivendo codice nuovo**: si riparano **collegando** ciò che esiste, o **togliendo** ciò
che non serve. È la regola #23, «COSTRUITO ≠ COLLEGATO», alla terza comparsa.

---

## COME SONO STATI FATTI I GRUPPI

Due voci stanno nello stesso giro **solo se toccano gli stessi file**: è l'unico criterio che
riduce davvero il numero di suite da lanciare, perché **una suite costa uguale per una riga o per
cinquanta**. Il raggruppamento è stato costruito con uno scanner di sessione che, per ogni voce
dei nove referti, ha raccolto **tutti i percorsi di file che la voce nomina** (247 voci → 214 file
distinti). I file più ricorrenti, misurati:

```
71  fase83_server.py        29  deploy/host.html       21  main_casavip.py
15  fase185_testi_legali    12  fase163_accettazioni   10  fase89_jurisdiction_outreach
10  deploy/bunker.html      10  deploy/index.html       9  deploy/diventa-host.html
 9  deploy/commissioni.html  9  deploy/admin.html       9  fase81_bootstrap_casavip.py
```

⛔ **`fase83_server.py` compare in 71 voci su 247.** È il collo di bottiglia del piano: qualunque
ordine si scelga, quel file va aperto in almeno **sette** giri diversi. Raggrupparlo tutto in uno
solo sarebbe peggio — un giro che tocca 11.245 righe in una volta è irreversibile se va storto.

**Costo di un giro, misurato oggi e non ricordato:**

| voce | numero | come è stato misurato |
|---|---|---|
| suite locale | **~26 min** | dichiarato in `RIPRENDI_QUI.md`, non rimisurato qui (la suite non si è lanciata) |
| CI da capo a fondo | **11,9 min** | API GitHub sui 16 job del commit `5eb129c`, `started_at` → `completed_at` |
| job più lento | **11,8 min** | `copertura`; poi `full-suite` 11,1 · `full-suite-311` 9,9 · `mutazione` 4,4 |
| test eseguiti per giro | **6.012** | `Ran 6012 tests in 604.707s` nel log di `full-suite` |

---

# 🩸 FASCIA A — QUI UN CLIENTE VERO PUÒ FARSI MALE

## GIRO A1 — La firma che registra un documento diverso da quello mostrato
### ✅ **FATTO il 2026-08-26** — commit `f7faa5b`, richiesta di unione **#108**

> ⛔ **E per due giorni nessuno lo sapeva.** La riparazione è entrata in `master` il 26 agosto e
> **nessun documento è stato aggiornato**: `grep -c "A1" RIPRENDI_QUI.md` → **0**, e questa riga
> qui sotto ha continuato a dire «è la più grave di tutto l'audit, ogni host che si registra da
> oggi fabbrica una prova falsa». Il 28 agosto quella frase è stata letta da una sessione, messa
> in cima a un passaggio di consegne come **unica cosa urgente**, e si era a un passo dal
> riparare una cosa già riparata. È lo **sbaglio S10** di `CLAUDE.md`: *il documento si aggiorna
> nello stesso momento in cui cambia la macchina — non «dopo», perché il «dopo» è dove si perde.*
>
> **Come è stato verificato il 2026-08-28** (tre prove, tre lati diversi):
> 1. **il codice** — etichetta, link e impronta escono tutti e tre da `fase163_accettazioni`
>    (`etichetta_contratto`, `link_contratto`, `lingua_contratto_servita`); il link scritto a
>    mano a `/termini.html` non c'è più;
> 2. **il commit** — `git log -1 -S "etichetta_contratto" -- fase83_server.py` → `f7faa5b`;
>    copre tutte e cinque le voci, comprese le due sulle lingue e il ripiego opposto fra server
>    e pagina. Suite verde quel giorno: `Ran 6007 tests — OK — EXIT=0`;
> 3. **la guardia che quella riparazione si è lasciata dietro**, eseguita di nuovo:
>    `python collaudi/guardia_contratto_firmato.py` → `caselle d'accettazione trovate: 3
>    (attese 3) · VERDE: etichetta, link e documento firmato coincidono · EXIT=0`.
>
> **Resta aperta solo la voce 🟡 minore** (referto 1 · N12): le cifre del contratto scritte a
> mano invece che dalla fonte, e il contratto in due lingue sole. Il referto stesso dice «le
> cifre **giuste**, ma scritte a mano»: è un rischio di manutenzione, **non** una prova falsa.

**5 voci** · 🔴 era la più grave di tutto l'audit — *testo originale del 2026-08-25 qui sotto,
conservato perché dice perché aveva la precedenza*

| voce | referto |
|---|---|
| Il gate di registrazione mostra i Termini sotto l'etichetta «Contratto Host» | 9 · voce 2 |
| La prova firmata registra l'impronta del contratto, non del documento letto | 9 · voce 2 |
| Il contratto esiste in due lingue sole, col ripiego opposto fra server e pagina | 6 · voce 5 |
| Il link al contratto perde la lingua in due punti su tre | 6 · voce 6 |
| Il contratto host ha le cifre scritte a mano invece che dalla fonte | 1 · N12 |

- **File:** `fase83_server.py` (1617, 1606-1607, 1631-1634), `fase163_accettazioni.py`,
  `deploy/contratto-host.html`, `deploy/host.html`
- **Serve «autorizzato»:** **SÌ** — `fase*.py` e `deploy/` (B4)
- **Giri di suite:** **1**
- ⚠️ **Perché è prima di tutto:** è l'unico difetto dell'audit che produce **una prova legale
  falsa**. Ogni host che si registra da oggi ne fabbrica una. Con **0 host firmati in produzione**
  costa zero ripararlo; con il primo host vero diventa una firma da rifare.

## GIRO A2 — I soldi che si fermano senza lasciare una riga
**17 voci** (8 gravi + 9 medie/minori del passaggio 3)

- **File:** `fase83_server.py` (S1, S3, S4, S5, S6, S11-S14, S16, S19, S21, S22),
  `fase87_stripe_webhook.py` (S8), `fase131_payout_dashboard.py` + `fase186_guardiano.py`
  (S2, S7), `fase162_pagamenti_pendenti.py` (S18), `fase177_financial_controller.py` (S15)
- **Serve «autorizzato»:** **SÌ**
- **Giri di suite:** **2** — è il file più grande del prodotto e le voci stanno in sette funzioni
  diverse; farlo in un colpo solo rende impossibile capire quale riga ha rotto cosa
- 🔑 **La forma comune, già misurata dal referto 3:** in 5 voci su 8 gravi **il silenzio non ha
  scadenza** — nessuno riproverà, nessuno se ne accorgerà, e il guardiano vede solo ciò che è già
  scritto nel registro.

## GIRO A3 — La prova fotografica dell'ospite muore prima di arrivare
**2 voci**

| voce | referto |
|---|---|
| `/api/voucher/prova` cade sotto il tetto di `nginx`, mentre app e testo promettono 5 MB | 8 · voce 5 |
| Due configurazioni `nginx` per lo stesso sito, con due tetti diversi sull'upload | 8 · voce 15 |

- **File:** `deploy/nginx.casavip.ssl.conf` (43, 80-83), `deploy/nginx.host-vps.conf`,
  `docker-compose.casavip.yml`, `fase83_server.py` (2327, 288)
- **Serve «autorizzato»:** **SÌ** (`deploy/` è produzione dal 2026-08-24)
- **Giri di suite:** **1** — ⚠️ **ma la suite non lo prova**: `nginx` non gira nei collaudi. Questa
  voce si verifica **solo con un deploy vero e una foto vera**, seguendo `DEPLOY.md`.
- ⚠️ **Perché è in fascia A:** è la prova su cui si decide **a chi vanno i soldi in garanzia**.
  L'ospite carica, vede fallire, e non sa perché.

## GIRO A4 — La cancellazione GDPR dichiara «non resta nulla» e guarda cinque archivi
**1 voce** · 🔴

- **File:** `fase156_erasure.py` (206-215, 218-232), `deploy/admin.html` (`del_p`, `verif_res`)
- **Serve «autorizzato»:** **SÌ**
- **Giri di suite:** **1**
- 💡 **La riparazione onesta non è un DELETE in più**: sei archivi trattengono i dati **per
  obbligo di legge** (prove di consenso, giornale dei soldi). È il **testo** che deve distinguere
  *cancellato* da *conservato per legge*, e il rapporto che deve dire quali archivi ha guardato.

## GIRO A5 — Il paese sparisce e porta via l'obbligo di legge
**5 voci**

| voce | referto |
|---|---|
| Il campo `paese` dell'annuncio si azzera da solo, e con lui l'obbligo del CIN | 5 · voce 1 |
| Il pannello host conosce 15 paesi; il prodotto dice di essere mondiale | 5 · voce 2 |
| L'IBAN è obbligatorio per tutti e blocca il bonifico senza guardare il paese | 5 · voce 3 |
| A Stripe non diciamo mai in che paese sta l'host, e il dato ce l'abbiamo già | 5 · voce 6 |
| `paese` fiscale: due vocabolari diversi nello stesso pannello, nessuno validato | 5 · voce 13 |

- **File:** `fase57_vetrina.py` (252-254, 575-576), `fase83_server.py` (8870, 8899, 8975),
  `deploy/host.html` (355-364, 1066, 1203), `fase101_stripe_connect.py` (181-190),
  `fase88_registro_host.py` (447)
- **Serve «autorizzato»:** **SÌ**
- **Giri di suite:** **1**
- ⚠️ Il CIN italiano vale **da 500 a 5.000 € di sanzione per annuncio**: chi risalva dal pannello
  un annuncio con un paese fuori tendina perde il paese, e con esso il controllo.

---

# 💸 FASCIA B — QUI PERDIAMO SOLDI NOI

## GIRO B1 — La tariffa tecnica ha quattro ripieghi scritti a mano in quattro file
**6 voci**

| voce | referto |
|---|---|
| Quattro ripieghi in quattro file, con tre valori diversi | 7 · voce 1 |
| L'email di reclutamento e il motore leggono la stessa variabile con default diversi | 8 · voce 2 · 1 · N1 |
| La docstring che doveva impedirlo dice il falso | 1 · N2 |
| `diventa-host.html` si contraddice nella stessa pagina, nella stessa lingua | 8 · voce 3 |
| La quota fissa è un numero in euro sommato alle unità minori di qualunque valuta | 5 · voce 5 |

- **File:** `main_casavip.py` (150-152), `fase89_jurisdiction_outreach.py` (189, 219),
  `fase188_paga_struttura.py` (64, 87), `fase185_testi_legali.py` (71, 75-76, 83-84),
  `fase81_bootstrap_casavip.py` (52-54), `fase99_multicurrency.py`
- **Serve «autorizzato»:** **SÌ**
- **Giri di suite:** **1**
- 💡 La fonte unica **esiste già** (`ConfigCasaVIP`): qui non si scrive una costante, si
  **cancellano tre ripieghi** e si fa leggere quella.

## GIRO B2 — Il gateway di «paga in struttura» disattiva una garanzia scritta nel suo stesso file
**3 voci**

- **File:** `fase188_paga_struttura.py` (41-43, 64, 87, 98-100), `fase163_accettazioni.py`
  (215-221), `deploy/host.html` (396, `h_paga_str`)
- **Serve «autorizzato»:** **SÌ**
- **Giri di suite:** **1**
- 🔴 **Una parte è una decisione, non una riparazione:** vedi **D7** in fondo. Il codice e il
  contratto firmato dicono due cose diverse su chi paga cosa, e nessuno dei due è «sbagliato»
  finché il fondatore non sceglie.

## GIRO B3 — DAC7: il gate di giurisdizione esiste e chi blocca i soldi non lo consulta
**2 voci**

| voce | referto |
|---|---|
| Il modulo è spento, il blocco payout no — e la soglia mescola le valute | 5 · voce 4 |
| Il gate di sicurezza e quello che blocca davvero hanno due soglie diverse | 8 · voce 14 |

- **File:** `fase100_dac7.py` (23-24, 46), `fase83_server.py` (6045-6054),
  `fase177_financial_controller.py` (409-470)
- **Serve «autorizzato»:** **SÌ** · **Giri di suite:** **1**

## GIRO B4 — Il kill-switch d'emergenza non copre tre gestori
**2 voci**

- **File:** `fase83_server.py` (5173-5181, 7916-7948, 7734-7770, 2971-3003)
- **Serve «autorizzato»:** **SÌ** · **Giri di suite:** **1**
- ⚠️ Oggi il più pericoloso dei tre è **dormiente per una variabile d'ambiente**. Il giorno in cui
  quella variabile si accende, il freeze smette di essere «tutti» **e nessuno lo saprà**.

---

# 📝 FASCIA C — I TESTI

## GIRO C1 — IL GIRO UNICO DEI TESTI PUBBLICI
**29 voci** — è il giro già previsto in cima alla sezione B di `RIPRENDI_QUI.md`

Raccoglie tutte le voci dei passaggi 1, 2, 8 e 9 che si riparano **cambiando una frase**:
promesse senza codice (`alloggi certificati`, `cancellazione gratuita`, `zero attese`, `il
sistema alza il prezzo da solo`, `i bonifici stanno partendo`, `anti-rimpianto`), le cifre
sbagliate nelle pagine pubbliche in 7 od 8 lingue, la pagina delle commissioni che si contraddice
a schermo, i quattro intervalli diversi su quanto prendono i concorrenti, i tre testi che mandano
a una schermata che non esiste.

- **File:** `deploy/index.html`, `deploy/diventa-host.html`, `deploy/commissioni.html`,
  `deploy/kit-marketing.html`, `deploy/bunker.html`, `deploy/host.html`, `deploy/admin.html`,
  `deploy/guida-operativa.html`, `fase185_testi_legali.py`, `fase69_trasparenza.py`,
  `fase125_confronto_guest.py`, `fase89_jurisdiction_outreach.py`
- **Serve «autorizzato»:** **SÌ** — `deploy/` è produzione (B4, deciso il 2026-08-24 proprio per
  un badge di questa specie)
- **Giri di suite:** **2** — 12 file, 8 lingue ciascuno: farlo in un colpo rende la revisione
  impossibile
- ⛔ **Da fare in un giro solo, non uno alla volta:** ogni cifra vive in più pagine, e ripararne
  una per volta ha già prodotto lo stato attuale (tre cifre diverse nello stesso canale di
  reclutamento).

## GIRO C2 — I due pannelli sono metà in inglese in sei lingue su otto
**4 voci** — 239 chiavi su 468 esistono solo in italiano e inglese

- **File:** `deploy/host.html` (502, 512), `deploy/admin.html` (200), `deploy/app.js`
- **Serve «autorizzato»:** **SÌ** · **Giri di suite:** **1**
- Dentro ci sono **tutte le chiavi di commissione e tariffa**, l'avviso della penale di
  cancellazione e **l'approvazione specifica delle clausole ex artt. 1341-1342 c.c.**

## GIRO C3 — La pagina che Google indicizza per ogni annuncio del mondo è congelata in italiano
**4 voci**

- **File:** `fase83_server.py` (672, 725, 1542, 1685), `fase61_localizzazione.py` (78-89),
  `fase173_motore_seo.py`, `fase111_cancellazione.py`
- **Serve «autorizzato»:** **SÌ** · **Giri di suite:** **1**

## GIRO C4 — I motori che parlano meno lingue del prodotto
**5 voci**

- **File:** `fase90_marketing.py` (37, 272), `fase97_inbound_seo.py` (28),
  `fase89_jurisdiction_outreach.py` (40, 197, 248), `deploy/admin.html` (161-165),
  `fase83_server.py` (10521), `fase61_localizzazione.py` (67-73)
- **Serve «autorizzato»:** **SÌ** · **Giri di suite:** **1**

## GIRO C5 — I testi legali applicati per lingua invece che per paese
**4 voci**

- **File:** `fase185_testi_legali.py`, `fase99_multicurrency.py`, `fase83_server.py`,
  `deploy/host.html`, `fase86_email.py`, `fase145_contratto_pdf.py`
- **Serve «autorizzato»:** **SÌ** · **Giri di suite:** **1**
- Dentro: l'autorità privacy scelta per lingua (**cinque risposte diverse**), due convenzioni
  decimali opposte applicate al mondo intero, l'identità fiscale italiana scritta a mano nella
  ricevuta di ogni paese.

---

# 🧰 FASCIA D — IL RESTO

## GIRO D1 — Le guardie che guardano dove il difetto non c'è
**7 voci** + le due scoperte del 2026-08-25

- **File:** `collaudi/audit_coerenza_tariffe.py`, `collaudi/occhio_del_fondatore.py`,
  `test_profondo_lingue.py` (534-546), `test_trasparenza_costi.py` (59-63),
  `test_pipeline_ci.py` (9672)
- **Serve «autorizzato»:** **NO** — `collaudi/` è strumentazione (D20); i `test_*.py` non sono
  produzione. ⚠️ **Ma vanno chiesti a parte** (regola ferrea 6): toccare una guardia e la
  meta-guardia che la prova è un lavoro suo.
- **Giri di suite:** **1**
- Dentro: la guardia ufficiale delle tariffe **cieca al 100% sulle pagine tradotte**; la domanda
  sbagliata («c'è la cifra giusta?» invece di «c'è quella sbagliata?»); `occhio_del_fondatore.py`
  che promuove `host.html` **773/776 senza aprire un dizionario**; l'unica guardia sulle pagine di
  `deploy/` che copre 2 file su 14; **`TODO` cercato come sottostringa** che inciampa su «metodo»
  (B20); **il punto cieco sulle righe di dizionario lunghe**, che è il motivo per cui la cifra
  sbagliata è sopravvissuta in sette lingue.
- 🔑 **Questo giro è quello che rende inutile rifare l'audit fra tre mesi.**

## GIRO D2 — Le fonti uniche che esistono e nessuno chiama
**20 voci** (tutto il passaggio 7)

- **File:** `fase23_datastore.py` (146-152) + i 62 moduli che si riscrivono la connessione,
  `deploy/app.js` (`BV.money`) + le 4 pagine che riscrivono a mano la formattazione del denaro,
  `fase61_localizzazione.py` (`LINGUE_SUPPORTATE`) + le 4 tuple copiate, `fase99_multicurrency.py`
- **Serve «autorizzato»:** **SÌ** · **Giri di suite:** **2** (62 punti di innesto non si toccano
  in un colpo solo: **si prova in piccolo prima**, su 5)
- 💡 In **17 voci su 20 la fonte unica è già scritta e funzionante**: il difetto è che la
  produzione non la raggiunge.

## GIRO D3 — Le voci minori sparse
**10 voci**

- 12 punti d'interesse scaricati e 6 usati · il ripiego del fuso che copre 18 paesi · la soglia
  del forfettario italiano dentro il motore dei prezzi · la chiave della tassa di soggiorno senza
  paese · la politica di cancellazione di default che non è nessuna delle quattro esistenti · il
  tariffario morto che convive con quello vivo nello stesso file · le candidature partner che
  nessun pannello guarda · l'indirizzo `/bunker` che è un 404
- **File:** `fase175_poi_osm.py`, `fase187_fuso_orario.py`, `fase98_policy_commissione.py`,
  `fase147_tassa_comunale.py`, `fase111_cancellazione.py`, `fase99_multicurrency.py`,
  `deploy/admin.html`, `fase83_server.py`
- **Serve «autorizzato»:** **SÌ** · **Giri di suite:** **1**

## GIRO D4, D5, D6 — Le 112 funzioni mai chiamate, a lotti
**112 voci + 59 moduli interi mai raggiunti (12.055 righe, 651 funzioni)**

- **Serve «autorizzato»:** **SÌ** · **Giri di suite:** **3**, un lotto per giro
- ⛔ **Non è un giro di riparazione finché non c'è la decisione D9.** Per ogni funzione le uscite
  sono **tre** (manca un test · manca un **requisito** · il codice è **estraneo e va tolto**), e
  sceglierle è del fondatore. Il piano le conta perché costano comunque tre suite.

---

# ⏱️ IL TOTALE

| fascia | giri |
|---|---|
| 🩸 A — un cliente si fa male | **6** (A1 1 · A2 2 · A3 1 · A4 1 · A5 1) |
| 💸 B — perdiamo soldi | **4** |
| 📝 C — i testi | **6** (C1 2 · C2 1 · C3 1 · C4 1 · C5 1) |
| 🧰 D — il resto | **3** + **3** (le funzioni mai chiamate, a lotti) |
| **TOTALE** | **19 giri** |

**19 giri × (26 min di suite + 11,9 min di CI) = 720 minuti = 12 ore esatte di sola verifica.**

⚠️ **E questo è il pavimento, non la stima.** Non contiene: il tempo di scrivere il codice, il
pre-volo, il tempo di leggere il rosso quando arriva, né i giri **ripetuti** perché la suite ha
trovato qualcosa. Misurato oggi su un giro fatto di soli documenti: **due giri di CI**, perché il
primo è andato rosso. Se succedesse su un terzo dei giri, il totale reale è **circa 16 ore**.

💡 **La leva vera non è correre di più: è che 19 giri su 19 spendono 26 minuti per una suite che
ne esegue 6.012 di test ogni volta.** Il costo del piano è dominato dalla **larghezza della
verifica**, non dal numero delle riparazioni — ed è esattamente ciò che dice la riga d'arrivo
per i soldi: *«il collo di bottiglia non è il METODO, è la LARGHEZZA»*.

---

# ✋ LE DODICI CHE NON SONO RIPARAZIONI — decide il fondatore, non il codice

Nessuna di queste si può «riparare»: hanno due risposte entrambe legittime, e finché non se ne
sceglie una qualunque modifica sarebbe una decisione presa di nascosto.

| # | La domanda | Voci coinvolte | Cosa costa non deciderla |
|---|---|---|---|
| **D1** | **Quale motore referral vive?** Due sono accesi, con premi e soglie diversi, sullo **stesso** link d'invito | 8·4 · 1·N6 · 2·P12 · 6·8 | Chi invita non prende niente, **in silenzio** |
| **D2** | **Quale motore split vive?** L'anteprima accetta 1000 persone, la creazione ne rifiuta più di 50 | 8·11 | L'ospite compone un conto che non può creare |
| **D3** | **La «classe fondatrice · tariffa bloccata» esiste o si toglie dai testi?** Nessuna riga la applica, e la tariffa sale | 2·P3 · 4 (`fase98.e_fondatore`) | Una promessa pubblica in 8 lingue senza codice |
| **D4** | **Quanto vale davvero il «Credito Fondatore»** promesso in homepage? Oggi vale zero con ogni host nei primi 90 giorni | 2·P9 | Un regalo annunciato e non consegnato |
| **D5** | **La cauzione si accende o si toglie?** Ha un archivio durevole, un unico scrittore, e zero chiamanti | 3·S9 · 3·S10 · 4 (`fase149`) | Un deposito che si dichiara liberato senza chiedere al PSP |
| **D6** | **Il contratto host fuori Italia**: legge, foro, lingue, clausole ex artt. 1341-1342 c.c. obbligatorie ovunque | 5·9 · 5·10 · B18 | Blocca il **secondo paese**, non il primo |
| **D7** | **Su «paga in struttura», quale tariffa vale**: quella del contratto firmato o quella del gateway? | 8·6 · 9·9 | L'host paga una cifra che il contratto non prevede |
| **D8** | **La tabella dei concorrenti: quale fonte è la buona?** Motore e pagina discordano su cinque portali su cinque | 8·7 · 8·10 · 1·N9 | Un confronto pubblico che non regge una verifica |
| **D9** | **I 59 moduli mai raggiunti e le 112 funzioni: si accendono, si tolgono o restano?** | tutto il passaggio 4 | Il 23,7% del codice di produzione in uno stato ignoto |
| **D10** | **Il badge «Host Verificato+» e i bonifici prioritari si costruiscono o si tolgono dal testo?** | 9·5 · 2·P8 | Si chiede un dato di pagamento in cambio di due cose inesistenti |
| **D11** | **La schermata dei bonifici si costruisce, o si cambiano i tre testi che ci mandano?** | 9·1 · 2·P10 · 2·P11 | Il gesto che paga l'host non ha né schermo né endpoint |
| **D12** | **«Alloggi certificati»: si costruisce la certificazione o si toglie la frase?** | 2·P1 | È in cima alla homepage, in 8 lingue |

⚠️ **D11 e D5 sono le due che bloccano un pagamento vero.** Le altre dieci possono aspettare
l'apertura; queste due no, perché riguardano soldi già incassati da qualcuno.

---

# 🔭 GLI ALTRI PASSAGGI DI AUDIT — dal 10 in avanti

Costruiti leggendo le sezioni **«cosa è rimasto fuori»** di tutti e nove i referti: ognuno di
questi è una direzione che i nove passaggi hanno **dichiarato di non aver guardato**.

| # | Cosa cerca | File del referto | Da quale «rimasto fuori» nasce |
|---|---|---|---|
| **10** | **I verbi dei documenti legali** in 8 lingue: diritti dell'interessato, tempi di risposta, cancellazione dei dati — le cifre sono state guardate, le **promesse** no | `collaudi/audit/10_verbi_legali.md` | 2 · punto 3 |
| **11** | **Le pagine pubbliche lette riga per riga** come sono stati letti i pannelli: `index.html` è ciò che vede l'ospite, e lì la stessa specie di difetto non è misurata | `collaudi/audit/11_pagine_pubbliche.md` | 9 · punto 1 · 2 · punto 5 |
| **12** | **I soldi che si fermano zitti NEL BROWSER**: il passaggio 3 si è fermato al server, ma un pagamento può morire anche in `deploy/*.js` | `collaudi/audit/12_soldi_fermi_nel_browser.md` | 3 · punto 5 |
| **13** | **I numeri e i silenzi dentro le guardie**: `collaudi/` e i 406 `test_*.py` non sono mai stati setacciati — ed è già successo che fosse **un file di test** a dichiarare il falso | `collaudi/audit/13_dentro_le_guardie.md` | 3 · punto 6 · 7 · punto 2 · 8 · punto 3 |
| **14** | **Le classi mai istanziate**: il passaggio 4 ha contato solo le **funzioni**; una classe morta i cui metodi si chiamano fra loro non compare in nessun referto | `collaudi/audit/14_classi_mai_istanziate.md` | 4 · punto 5 |
| **15** | **Dentro i 59 moduli mai raggiunti**: 12.055 righe guardate finora solo di riflesso, per tema | `collaudi/audit/15_dentro_i_moduli_spenti.md` | 4 · punto 1 · 5 · punto 1 · 7 · punto 3 · 8 · punto 4 |
| **16** ✅ **FATTO 2026-08-25** | **L'ambiente del VPS contro i default del codice** — misurato: **9 voci cambiano forma davvero** (3 confermate, 1 ribaltata, 1 decaduta, 4 latenti per misura). Le tre che pesano: `PAGAMENTO_BPS` **assente** (i ripieghi divergono adesso) · `PAGA_STRUTTURA_ATTIVO=1` · `DAC7_BLOCCO_PAYOUT` assente → blocco bonifici **acceso** | `collaudi/audit/16_ambiente_vps.md` | **tutti e nove**, esplicitamente |
| **17** | **La qualità delle traduzioni**: il passaggio 6 misura se la traduzione **esiste** e se porta gli stessi numeri, **non** se è scritta bene. Serve un madrelingua, non uno scanner | `collaudi/audit/17_qualita_traduzioni.md` | 6 · punto 1 |
| **18** | **I numeri muti dentro il corpo delle funzioni**: senza nome e senza parola chiave accanto, non li copre **nessuno** dei due scanner del passaggio 8 | `collaudi/audit/18_numeri_muti.md` | 8 · punto 6 |
| **19** | **I testi composti a runtime**: le `f-string` e tutto ciò che è assemblato da variabili è saltato dal confronto fra lingue | `collaudi/audit/19_testi_a_runtime.md` | 6 · punto 3 |
| **20** | **Il JavaScript morto nei pannelli**: gli `<script>` inline sono stati letti come **testo**, mai analizzati come programma — 1.612 righe nel solo `host.html` | `collaudi/audit/20_javascript_nei_pannelli.md` | 9 · punto 7 |

⛔ **Vale la stessa regola dei primi nove: UN PASSAGGIO = UNA CHAT NUOVA, DA SOLO**, e il
risultato va in un file, non a schermo.

🔑 **E fra questi undici ce n'è uno che non è come gli altri: il numero 16.** Non è una direzione
nuova, è **la verifica di quello che i nove referti hanno già scritto**. Nove referti su nove
dichiarano di aver letto i default del codice e **non** l'ambiente vero: finché quel passaggio non
è fatto, almeno nove voci di questo piano potrebbero essere più gravi — o non esistere affatto.

---

## ⛔ COSA QUESTO PIANO NON HA FATTO

1. **Non ha riaperto i nove referti voce per voce per riverificarne i fatti.** Li prende per
   buoni: sono stati misurati uno per uno nei rispettivi passaggi, ognuno con `file:riga`.
2. **I raggruppamenti sono per FILE, non per rischio tecnico.** Due voci nello stesso file possono
   comunque richiedere due giri se una tocca il percorso dei soldi; dove l'ho previsto l'ho
   scritto (A2, C1, D2).
3. **Il conto dei giri non è una stima di lavoro**: è il numero di **verifiche complete** da
   pagare. Quanto costi scrivere ogni riparazione non è stato misurato e non va inventato.
4. **Le 247 voci non sono tutte distinte.** Le conferme incrociate fra passaggi sono state
   segnalate nei referti e **non risommate** lì; qui compaiono una volta sola nel gruppo che le
   ripara, ma il totale 247 le conta come le contano i nove referti.
5. **Nessun `fase*.py` aperto per questo file, nessuna suite, nessun comando di scrittura sul
   prodotto.** L'unica cosa scritta è questo documento, che **resta fuori dal commit**.
