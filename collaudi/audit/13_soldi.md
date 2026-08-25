# B19 — PASSAGGIO 13 · IL GIRO DEI SOLDI: GLI STATI DI UNA PRENOTAZIONE

> **Referto di misura, non lista di cose da fare.** Sola lettura: nessun file di prodotto
> toccato (**nessuno dei 10 file già modificati nell'albero di lavoro è stato scritto: li ho
> solo LETTI**), nessuna riparazione, nessuna suite, nessun commit, nessun giro sul VPS,
> nessun server avviato, nessuna chiamata di rete.
>
> Misurato il **2026-08-25**, ramo `master`, `HEAD = 3ceb4c5`, sull'albero di lavoro.
> Numeri di riga = **file come stanno sul disco adesso**.
>
> Perimetro: dal `POST /api/concierge/book` fino al bonifico sul conto dell'host, comprese
> le tre uscite laterali (scadenza, rimborso, cancellazione host).

---

# 1. GLI STATI — quanti sono e da dove si leggono

**Una prenotazione non ha UNO stato. Ne ha CINQUE, in cinque archivi diversi**, ognuno con un
vocabolario suo. Non esiste una colonna, una tabella o una funzione che dica «questa
prenotazione è a che punto».

| # | Archivio | Colonna | Stati possibili | Dichiarati a |
|---|---|---|---|---|
| A | `pendenti.db` / `pendenti` | `stato` | `in_attesa` · `in_attesa_host` · `scaduto` · `pagato` · `rimborsato` · `cancellata_host` | **nessuna costante**: 6 letterali sparsi nelle query (`fase162_pagamenti_pendenti.py:68,107,324,421,439,467`) |
| B | `payout.db` / `payout` | `stato` | `in_attesa` · `maturato` · `in_transito` · `pagato` · `trattenuto` | **`fase131_payout_dashboard.py:18`** (`STATI`, tupla esplicita) |
| C | `garanzia.db` / `garanzia` | `stato` | `in_garanzia` · `contestato` · `rilasciato` · `risolto` · `annullato` | **`fase160_escrow_garanzia.py:14`** (docstring) — nessuna costante |
| D | `inventario.db` / `inventario` | *(nessuna colonna di stato)* | la notte è **bloccata** o **libera**, per `idem_key` | `fase58_channel_manager.py:622` (`blocca`) e `:693` (`rilascia`) |
| E | `checkin.db` / `checkin` | `completato`, `revocato` | `0/0` · `1/0` (fatto) · `0/1` (revocato = pietra tombale) | `fase127_checkin_digitale.py:120` e `:163` |

**Il sesto posto è un modello che il prodotto non usa:** `fase199_invarianti.py:303-321`
dichiara `STATI_PRENOTAZIONE` (gli stessi 6 di A), `EVENTI_PRENOTAZIONE` (4 transizioni con le
sorgenti ammesse), `TERMINALI_NEGATIVI_PRENOTAZIONE` e `RANGO_PRENOTAZIONE`, e
`transizioni_prenotazione()` (`:331`) ne deriva la relazione completa.
**Misurato: i suoi unici chiamanti sono in `test_fase199_transizioni.py`** — `grep -rn
"transizioni_prenotazione"` fuori da fase199 → **7 righe, tutte nel file di test, zero in
produzione.**

⛔ Nota che vale per tutto il resto del referto: `fase34_prenotazioni.py` contiene una
**seconda macchina a stati completa** (tabelle `prenotazioni` + `escrow_fondi`, stati
`pagata`/`annullata`, `fase34:253,272,293,312,362,365`). **Non è raggiungibile**: non compare
in `fase81_bootstrap_casavip.py`. È il modulo morto n. 1 fra quelli censiti dal passaggio 4;
qui lo dichiaro e lo escludo dal conteggio.

---

# 2. QUALI PASSAGGI SONO PERMESSI — e chi lo decide

**Non c'è un posto solo. Ci sono TRE discipline diverse, una per archivio, più un quarto
archivio senza nessuna disciplina.**

### B — `payout`: tabella dichiarata, guardia unica ✅

`fase131_payout_dashboard.py:19-24`:

```
_TRANSIZIONI = {
    "in_attesa":   {"maturato", "trattenuto"},
    "maturato":    {"in_transito", "trattenuto"},
    "in_transito": {"pagato", "trattenuto"},
    "trattenuto":  {"in_transito"},
    "pagato":      set(),
}
```

Applicata in **un solo punto**, `aggiorna_stato` (`:150`), che rifiuta sia lo stato ignoto
(`:151`) sia la transizione illegale (`:158`). **È l'unico archivio del giro dei soldi fatto
come si deve.**

⛔ **E ha uno stato irraggiungibile.** `pagato` è il traguardo — «i soldi sono sul conto
dell'host» — e **nessuno lo scrive**: le chiamate a `aggiorna_stato` in produzione sono
**4** e passano `"in_transito"` (`fase83_server.py:6264`), `"trattenuto"` (`:6454`, `:6637`),
`"maturato"` (`:7981`). `grep -rn 'aggiorna_stato(.*"pagato"'` → **0**.
Conseguenza misurata: `in_transito` è **uno stato senza uscita**, e il Guardiano non lo
sorveglia — `fase186_guardiano.py:141` cerca i fermi **solo** fra i `maturato`
(`if stato == "maturato" and ts < soglia`), mentre `in_transito` finisce nell'allarme solo se
l'host è sparito (`:133`). **Un bonifico che parte e non arriva mai non ha nessuno che lo
cerchi.**

### C — `garanzia`: cancello unico, regola passata a mano ⚠️

Tutte le mutazioni passano da `_muta(pren_id, attesi, nuovo, …)` (`fase160:116`), che fa
`BEGIN IMMEDIATE`, rilegge lo stato e rifiuta se non è in `attesi` (`:126-127`). Buono. Ma
**`attesi` è un argomento**, non una tabella: la regola vive nei 5 chiamanti —
`:142` (`in_garanzia`→`rilasciato`), `:148` (`in_garanzia`→`contestato`),
`:154` (`in_garanzia|contestato`→`annullato`), `:165` (`in_garanzia`→`risolto`),
`:177` (`contestato`→`risolto`). Due punti la aggirano del tutto e scrivono l'`UPDATE` da sé:
`:217` e `:222` (dentro `auto_rilascia`, con CAS proprio) e `:108` (il *revive* da
`annullato`).

### A — `pendenti`: nessuna tabella, la regola è dentro le `WHERE` ❌

Le 6 transizioni della prenotazione **non sono dichiarate da nessuna parte nel modulo**: ogni
metodo porta la sua condizione in SQL.

| Metodo | Riga | Regola scritta |
|---|---|---|
| `conferma` | `:324` + `:328` | whitelist `("in_attesa","scaduto")`, riletta e poi CAS |
| `scadi` | `:420` | whitelist `IN ('in_attesa','in_attesa_host')` |
| `marca_da_rimborsare` | `:439` | **blacklist** `NOT IN ('cancellata_host','rimborsato')` |
| `marca_cancellata_host` | `:467` | **blacklist** `NOT IN ('cancellata_host','rimborsato')` |
| `rimuovi_se_stato` | `:403` | uguaglianza esatta passata dal chiamante |
| `rimuovi` | `:385` | **nessuna** (DELETE incondizionato) |

Oggi whitelist e blacklist coincidono: 6 stati − 2 vietati = i 4 che `fase199:311-315`
elenca. **Ma sono due regole diverse scritte in due posti diversi**, e divergono al primo
stato nuovo: il codice lo ammetterebbe da solo, il modello no.
✅ `rimuovi` (l'unica scrittura senza guardia) **non ha chiamanti in produzione**:
`grep -rn "pp\.rimuovi(\|pendenti\.rimuovi("` fuori dai test → **0**.

### D — `inventario`: non c'è nessuna disciplina, e va bene così

`blocca`/`rilascia` non sono transizioni ma un lucchetto idempotente per `idem_key`. La regola
di sicurezza sta altrove: **la chiave fresca `"reblock:<rif>"`** per il pagamento tardivo
(`fase83_server.py:8112`), perché riusare la chiave già rilasciata dava un `ok` finto.

### E chi controlla la COERENZA fra A, B, C, D, E?

`fase199` sa farlo (`i5_escrow_coerente` `:129`, `verifica_stato` `:163`, `scansiona_db`
`:177`) e in produzione è raggiungibile **solo come ispezione a richiesta**, dal Bunker:
`GET /api/bunker/invarianti` → `_bunker_invarianti` (`fase83_server.py:3405`, importa
`scansiona_db` a `:3411`). **È un auditore, non una guardia: non sta sulla strada di nessuna
scrittura.** L'unica guardia sulla strada è a `fase83_server.py:5377-5406` e importa **due
invarianti su cinque** (`i3_prova_prima_del_commit`, `i4_denaro_non_negativo`, riga `:5383`),
con `except → fail-open` dichiarato a `:5406`.

---

# 3. OGNI PUNTO CHE CAMBIA LO STATO — uno per riga

### Le 24 scritture primitive (dove il byte cambia)

```
fase162_pagamenti_pendenti.py:118   INSERT pendenti          -> in_attesa | in_attesa_host
fase162_pagamenti_pendenti.py:328   UPDATE pendenti  CAS     -> pagato        (da in_attesa|scaduto)
fase162_pagamenti_pendenti.py:385   DELETE pendenti          -> (record sparito)  [0 chiamanti]
fase162_pagamenti_pendenti.py:403   DELETE pendenti  CAS     -> (record sparito)  se stato == X
fase162_pagamenti_pendenti.py:420   UPDATE pendenti  CAS     -> scaduto
fase162_pagamenti_pendenti.py:439   UPDATE pendenti  CAS     -> rimborsato
fase162_pagamenti_pendenti.py:467   UPDATE pendenti  CAS     -> cancellata_host (+ penale nel corpo_json)
fase162_pagamenti_pendenti.py:569   DELETE pendenti          -> housekeeping: 'scaduto' piu' vecchi di 26h
fase160_escrow_garanzia.py:97       INSERT garanzia          -> in_garanzia
fase160_escrow_garanzia.py:108      UPDATE garanzia  CAS     -> in_garanzia    (revive, solo da annullato)
fase160_escrow_garanzia.py:128      UPDATE garanzia  (_muta) -> rilasciato|contestato|annullato|risolto
fase160_escrow_garanzia.py:217      UPDATE garanzia  CAS     -> annullato      (auto_rilascia, rimborsata)
fase160_escrow_garanzia.py:222      UPDATE garanzia  CAS     -> rilasciato     (auto_rilascia, 24h)
fase131_payout_dashboard.py:103     INSERT OR IGNORE payout  -> maturato
fase131_payout_dashboard.py:124     INSERT OR IGNORE payout  -> in_attesa
fase131_payout_dashboard.py:141     DELETE payout            -> (riga sparita)
fase131_payout_dashboard.py:160     UPDATE payout            -> secondo _TRANSIZIONI
fase58_channel_manager.py:622       blocca                   -> notti occupate (idem_key)
fase58_channel_manager.py:693       rilascia                 -> notti libere  (idem_key)
fase127_checkin_digitale.py:120     INSERT OR REPLACE checkin-> completato=1
fase127_checkin_digitale.py:163     INSERT ... ON CONFLICT   -> completato=0, revocato=1 (tombstone)
fase149_deposito_cauzionale.py:116  UPDATE cauzione          -> catturato
fase149_deposito_cauzionale.py:143  UPDATE cauzione          -> rilasciato
fase177_financial_controller.py:627 UPSERT debiti            -> stato del debito host
```

### I 28 punti che le invocano (dove la decisione viene presa)

```
fase83_server.py:5550   _apri_garanzia            -> garanzia in_garanzia          (book)
fase83_server.py:5551   _registra_payout          -> payout in_attesa|maturato     (book)
fase83_server.py:5552   _registra_hold            -> pendenti in_attesa            (book)
fase83_server.py:5576   pp.registra               -> pendenti in_attesa_host       (su richiesta)
fase83_server.py:5734   pp.rimuovi_se_stato       -> record via                    (rifiuto richiesta)
fase83_server.py:5748   pp.rimuovi_se_stato       -> record via                    (approva richiesta)
fase83_server.py:5751   inventario.rilascia       -> notti libere                  (rifiuto)
fase83_server.py:5812   pp.registra               -> pendenti in_attesa            (hold online)
fase83_server.py:5914   pd.registra_in_attesa     -> payout in_attesa
fase83_server.py:5916   pd.registra_maturato      -> payout maturato               (conferma immediata)
fase83_server.py:6264   pd.aggiorna_stato         -> payout in_transito            (bonifico partito)
fase83_server.py:6388   pp.marca_cancellata_host  -> pendenti cancellata_host  CAS (host annulla)
fase83_server.py:6414   inventario.rilascia       -> notti libere                  (host annulla)
fase83_server.py:6420   pd.rimuovi                -> payout via                    (host annulla)
fase83_server.py:6422   _revoca_checkin           -> checkin revocato              (host annulla)
fase83_server.py:6426   gz.annulla                -> garanzia annullato            (host annulla)
fase83_server.py:6454   pd.aggiorna_stato         -> payout trattenuto             (DAC7/disputa)
fase83_server.py:6614   g.conferma_ospite         -> garanzia rilasciato           (ospite: tutto ok)
fase83_server.py:6628   g.contesta                -> garanzia contestato           (ospite: disputa)
fase83_server.py:6637   pd.aggiorna_stato         -> payout trattenuto             (disputa aperta)
fase83_server.py:6746   inventario.rilascia       -> notti libere                  (cancellazione ospite)
fase83_server.py:6783   gz.chiudi_proporzionale   -> garanzia risolto              (cancellazione parziale)
fase83_server.py:6849   pp.marca_da_rimborsare    -> pendenti rimborsato
fase83_server.py:7981   pd.aggiorna_stato         -> payout maturato               (riasserzione incasso)
fase83_server.py:8044   pp.conferma               -> pendenti pagato           CAS (WEBHOOK STRIPE)
fase83_server.py:8113   inv.blocca                -> notti occupate                (pagamento tardivo)
fase83_server.py:8123   pp.marca_da_rimborsare    -> pendenti rimborsato           (stanza gia' presa)
fase83_server.py:8159   pd.registra_maturato      -> payout maturato               (re-block riuscito)
fase83_server.py:8206   inv.blocca                -> notti occupate                (secondo ramo)
fase83_server.py:8218   pp.marca_da_rimborsare    -> pendenti rimborsato
fase83_server.py:4389   inventario.rilascia       -> notti libere                  (rimborso admin)
fase83_server.py:4410   _revoca_checkin           -> checkin revocato              (rimborso admin)
fase83_server.py:4426   pp.marca_da_rimborsare    -> pendenti rimborsato           (rimborso admin)
fase83_server.py:4848   g.risolvi                 -> garanzia risolto              (arbitrato)
fase83_server.py:4858   pd.rimuovi                -> payout via                    (arbitrato: all'ospite)
fase83_server.py:4873   pd.rimuovi                -> payout via                    (arbitrato: parziale)
fase83_server.py:4874   pd.registra_maturato      -> payout maturato               (arbitrato: quota host)
fase83_server.py:10448  pp.scadi                  -> pendenti scaduto          CAS (SWEEPER)
fase83_server.py:10450  inv.rilascia              -> notti libere                  (sweeper)
fase83_server.py:10453  gz.annulla                -> garanzia annullato            (sweeper)
fase83_server.py:10459  _pd.rimuovi               -> payout via                    (sweeper)
fase83_server.py:10466  pp.pulisci_vecchi         -> record 'scaduto' vecchi via   (sweeper)
fase83_server.py:10475  inv.libera_orfani         -> notti libere                  (stanze fantasma)
fase83_server.py:11067  gz.auto_rilascia          -> garanzia rilasciato           (TICK 24h)
fase83_server.py:11068  _trasferisci_all_host     -> Stripe + payout in_transito   (TICK 24h)
```

---

# 4. SE IL SISTEMA MUORE A META'

Il risultato onesto: **questa parte è la meglio costruita di tutto il prodotto misurato finora.**
Il metodo è dichiarato e applicato ovunque: **prima si ACQUISISCE la decisione con un CAS, poi
si fanno gli effetti; se il CAS non si vince non si tocca niente.** Le conseguenze, sequenza
per sequenza:

| Sequenza | Se muore fra i passi | Cosa resta | Chi lo ripara |
|---|---|---|---|
| **Prenotazione** (`blocca`→garanzia→payout→`pendenti`) | notti bloccate, **nessun pendente** | «stanza fantasma»: lo sweeper non la vede, non c'è record da scadere | ✅ `inv.libera_orfani(pp.idem_keys(), grazia 1h)` — `fase83:10475` |
| **Webhook pagamento** (CAS `pagato`→tassa→payout→email) | `pagato` scritto, derivati mancanti | payout resta `in_attesa`, tassa non registrata | ✅ Stripe ritenta per giorni e il ramo `stato == "pagato"` **ri-asserisce** i passi idempotenti (`fase83:8054-8064`, «BUG #32»). Credito e referral **non** si ri-asseriscono: **si perde il bonus di quella prenotazione**, per scelta dichiarata |
| **Sweeper hold** (CAS `scaduto`→rilascia→garanzia→payout→email) | `scaduto` scritto, notti **ancora bloccate** | lato sicuro: zero overbooking | ✅ il pagamento tardivo ri-blocca idempotente; la nota è scritta in `fase83:10438-10440` |
| **Cancellazione host** (CAS→giornale→rilascia→payout→tassa→checkin→garanzia) | penale nel `corpo_json`, **nessuna Nota di Debito** | l'host non è addebitato | ✅ riasserzione penali nello sweeper, `fase83:10481-10505` (idempotente su `esiste_evento("penale:"+rif)`) |
| **Tick 24h** (`auto_rilascia` commit → `_trasferisci_all_host`) | garanzia `rilasciato`, **soldi mai partiti** | `auto_rilascia` non lo ripesca più (prende solo `in_garanzia`) | ⚠️ **rete indiretta**: il payout resta `maturato` e il Guardiano lo segnala **dopo 7 giorni** (`fase186:141`, `GIORNI_PAYOUT_FERMO = 7`). Nessun ritentativo automatico |
| **Bonifico** (`connect.trasferisci` → `aggiorna_stato` → `_giornale`) | **soldi partiti**, payout ancora `maturato`, **nessuna riga nel giornale** | il Guardiano dirà «bonifico fermo» su un bonifico già fatto | ⚠️ **la protezione è di Stripe, non nostra**: `idem_key="transfer_<riferimento>"` (`fase101_stripe_connect.py:241`). La guardia locale anti-doppio (`fase83:6200`, `pd.stato_di in ("in_transito","pagato")`) legge **proprio il valore che non è stato scritto** |
| **Escrow** (`_muta` unica UPDATE in transazione) | nulla a metà | `BEGIN IMMEDIATE` + una sola scrittura | ✅ atomico per costruzione |

### Le due crepe vere, e sono la stessa crepa

1. **Fra «i soldi sono usciti» e «l'abbiamo scritto» ci sono tre scritture separate**
   (`fase83:6259` transfer → `:6264` stato → `:6269` giornale) e **nessuna transazione le
   tiene insieme**. Il fatto irreversibile avviene per primo, la prova per ultima.
2. **`in_transito` non ha uscita né sorveglianza**: nessuno scrive `pagato`
   (0 chiamate) e il Guardiano non ha una soglia per `in_transito` (`fase186:141`).
   Quindi il giro dei soldi **non ha un finale**: l'ultimo stato che il prodotto sa scrivere è
   «partito», mai «arrivato».

---

# 5. LA FORMA DI FAMIGLIA

**La macchina a stati di questa prenotazione esiste, è scritta, ed è persino DIMOSTRATA con
Z3 — e nessuna riga di produzione la consulta.**

- `fase199_invarianti.py:305-316` dichiara i 4 eventi con le sorgenti ammesse;
- `:331` ne deriva la relazione completa; `:364` `dimostra_transizioni()` prova con Z3 che è
  aciclica, che i rangi salgono e che da `rimborsato`/`cancellata_host` **nessun cammino
  torna a `pagato`**;
- `grep` dei chiamanti fuori da fase199: **7 righe, tutte in `test_fase199_transizioni.py`,
  zero in produzione.**

La regola che il prodotto **esegue davvero** vive altrove e in tre dialetti: una tabella
(`fase131:19`), un argomento passato a mano (`fase160:116`), sei clausole `WHERE` (`fase162`).
E il modello è **uno specchio copiato a mano** — lo dichiara da sé: *«SPECCHIO di
fase160.risolvi»* (`fase199:347`). Uno specchio non è un vincolo: se domani qualcuno allarga
una `WHERE`, il teorema resta verde e continua a dimostrare una macchina che non è più quella
del prodotto.

💡 **Il corollario, ed è lo stesso di altri tre passaggi (regola #23, «COSTRUITO ≠
COLLEGATO»):** qui non manca la macchina a stati. Manca **il filo** fra la macchina a stati e
le 24 righe che scrivono. Finché ogni scrittura porta la sua regola addosso, la coerenza del
giro dei soldi è una proprietà che va **ri-dimostrata a mano ogni volta che si tocca una
query** — e nessuno se ne accorgerà, perché i teoremi passeranno lo stesso.

---

## ⚠️ LE MISURE CHE DA QUI NON POSSO FARE — comandi da incollare tu sul VPS

Tutto il referto è misurato sul codice. Se gli stati **veri** siano coerenti fra loro, e se
esistano già le due crepe qui sopra, lo dice solo il database vivo. Sola lettura (`mode=ro`),
nessuna scrittura, nessun riavvio:

```
# A) la distribuzione degli stati nei tre archivi + i payout fermi
docker exec casavip_app python3 -c "import sqlite3
for f,t in (('pendenti','pendenti'),('payout','payout'),('garanzia','garanzia')):
    c=sqlite3.connect('file:/data/%s.db?mode=ro'%f,uri=True)
    print(f.upper(),dict(c.execute('SELECT stato,COUNT(*) FROM '+t+' GROUP BY stato').fetchall()));c.close()"

# B) le due crepe: payout 'in_transito' senza riga di giornale, e 'maturato' vecchi
docker exec casavip_app python3 -c "import sqlite3,time
p=sqlite3.connect('file:/data/payout.db?mode=ro',uri=True)
g=sqlite3.connect('file:/data/finanza.db?mode=ro',uri=True)
try: pagati={r[0] for r in g.execute(\"SELECT riferimento FROM libro_giornale WHERE tipo='payout_host'\")}
except Exception as e: pagati=set(); print('giornale illeggibile',e)
ora=int(time.time())
for rif,st,ts in p.execute('SELECT prenotazione_id,stato,ts FROM payout'):
    if st=='in_transito' and rif not in pagati: print('IN_TRANSITO SENZA GIORNALE',rif)
    if st=='maturato' and ora-int(ts or 0)>7*86400: print('MATURATO FERMO %dgg'%((ora-ts)//86400),rif)"

# C) l'incoerenza fra archivi: escrow 'rilasciato' con payout ancora 'maturato'
docker exec casavip_app python3 -c "import sqlite3
g=sqlite3.connect('file:/data/garanzia.db?mode=ro',uri=True)
p=sqlite3.connect('file:/data/payout.db?mode=ro',uri=True)
st={r[0]:r[1] for r in p.execute('SELECT prenotazione_id,stato FROM payout')}
for rif,s in g.execute(\"SELECT prenotazione_id,stato FROM garanzia WHERE stato IN ('rilasciato','risolto')\"):
    if st.get(rif)=='maturato': print('ESCROW CHIUSO MA BONIFICO FERMO',rif)"

# D) il verdetto che il prodotto sa gia' dare da solo (auditore fase199, dal Bunker)
#    -> GET /api/bunker/invarianti  con la sessione Bunker; oppure, dal container:
docker exec casavip_app python3 -c "from fase199_invarianti import scansiona_db;import json;print(json.dumps(scansiona_db('/data'),indent=1)[:2000])"
```

---

## ✅ VERIFICATO E SCARTATO

1. **Il CAS c'è davvero e viene prima degli effetti** in tutte e 5 le sequenze che muovono
   soldi. Non è una dichiarazione: è nel codice, con il commento che racconta il bug che l'ha
   causato (`fase83:8040-8044`, `:10432-10440`, `:6380-6386`).
2. **`rimuovi` di `fase162:385` (DELETE senza guardia) non ha chiamanti in produzione.**
3. **Il pagamento tardivo non può rubare la stanza**: chiave `reblock:` fresca (`:8112`) e, se
   la stanza è presa, `marca_da_rimborsare` + riga di rimborso nel giornale (`:8123-8140`).
4. **Il rimborso e la cancellazione-host non retrocedono un record chiuso**: entrambe le
   `WHERE` escludono `cancellata_host` e `rimborsato` (`fase162:439`, `:467`) — è la proprietà
   che `fase199` dimostra con Z3, e qui il codice la rispetta.
5. **L'escrow non si riapre da uno stato deciso**: il *revive* è un CAS `WHERE stato='annullato'`
   (`fase160:110`) e i decisi non si toccano (commento `:104-105`).
6. **`auto_rilascia` fa il CAS per riga**, non si fida della `SELECT` fatta prima
   (`fase160:198-223`): un `contestato` arrivato nel frattempo non viene rilasciato.
7. **Il kill-switch globale e gli hold DAC7/verifica non perdono i soldi**: tutti e tre
   ritornano lasciando il payout `maturato` (`fase83:6181`, `:6234`, `:6243`), che è lo stato
   sorvegliato.
8. **Il bonifico non parte due volte** finché vale l'Idempotency-Key di Stripe
   (`fase101:241`) — ma vedi la crepa n. 2: la guardia **locale** non regge da sola.
