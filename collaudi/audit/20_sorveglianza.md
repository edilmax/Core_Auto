# B19 — PASSAGGIO 18 · CHI SI ACCORGE, CHI GRIDA, CHI LEGGE

> **Referto di misura, non lista di cose da fare.** Sola lettura: nessun file di prodotto
> toccato (i 3 file modificati da altre sessioni sono stati solo LETTI), nessuna riparazione,
> nessuna suite, nessun commit, nessun giro sul VPS, nessuna chiamata di rete, nessun heredoc.
>
> Misurato il **2026-08-26**, ramo `master`, `HEAD = 663eab3`.
>
> ⛔ **Perché il numero è 20 e non 16:** `collaudi/audit/16_ambiente_vps.md` **esiste già**
> (passaggio 16, fatto il 2026-08-25 su `cb45c80`), e il **18 è assegnato a un'altra sessione
> che sta lavorando adesso**. Scrivere un secondo `16_*.md` o `18_*.md` avrebbe creato due
> passaggi con la stessa chiave — è esattamente lo sbaglio della «chiave che non porta il suo
> ambito» già pagato due volte. Ho preso il primo numero libero: **20**.
>
> Perimetro: **ogni meccanismo che si accorge che qualcosa non va**, il canale con cui lo dice,
> e la persona che lo legge davvero.

---

## RISULTATO IN UNA RIGA

**8 sorveglianti vivi**, disposti su **3 anelli** (dentro il processo · sul VPS · fuori dal
VPS) — ed è una catena costruita bene, con i suoi limiti **dichiarati per iscritto nel codice**.
I difetti misurati sono **3, e sono tutti sul lato del DESTINATARIO, non del rilevatore**:
l'allarme sui soldi viaggia sul canale più fragile, **non esiste un posto dove GUARDARE** (si
può solo aspettare di essere chiamati), e **5 cose che i passaggi precedenti hanno misurato non
sono sorvegliate da nessuno.**

---

# 1. GLI OTTO SORVEGLIANTI — cosa guardano, ogni quanto, come gridano

### Anello 1 — dentro il processo

| # | Chi | Cosa guarda | Ogni quanto | Come grida |
|---|---|---|---|---|
| 1 | **Guardiano dei soldi** `fase186_guardiano.py` | 7 controlli: riconciliazione Stripe · escrow bloccato 48h · bonifico fermo 7gg · payout orfano · soldi su prenotazione rimborsata · cambio valuta fermo 26h · marca temporale ferma 48h | **24 h** (`fase83_server.py:11146`) | `logger.critical` + **email** |
| 2 | **Guasti isolati** `fase186:266` | gli `ERROR` di `app.log` nelle ultime **24 h** | insieme a (1) | come sopra |
| 3 | **Sweeper hold** `fase83_server.py:10431` | hold scaduti · **stanze fantasma** (1h) · penali senza Nota di Debito | ogni giro | ripara da sé, non grida |
| 4 | **Battito (dead man's switch)** `fase178_watchdog.py:121` | scrive un file **solo se il giro (1) è arrivato in fondo** | 24 h | non grida: **si fa contare** |

### Anello 2 — sul VPS, fuori dal processo

| # | Chi | Cosa guarda | Ogni quanto | Come grida |
|---|---|---|---|---|
| 5 | **`deploy/watchdog.sh`** | uptime · catena hash del giornale · **freschezza dei backup (8h)** · disco · db presenti · **età del battito (25h)** | **10 minuti** (cron, `DEPLOY.md:441`) | **Telegram** + `/data/watchdog.log` |

### Anello 3 — fuori dal VPS

| # | Chi | Cosa guarda | Ogni quanto | Come grida |
|---|---|---|---|---|
| 6 | **Sentinella esterna** `.github/workflows/sentinella.yml` | `GET /api/health` da fuori: il sito risponde **e** il campo `guardiano` dice `ok` | **~15 min** (`cron: 7,22,37,52`) | lavoro **rosso** → email di GitHub |
| 7 | **CI** `.github/workflows/ci.yml` | la suite su ogni richiesta di unione | a ogni push | il cancello blocca l'unione |
| 8 | **CodeQL** `.github/workflows/codeql.yml` | analisi statica di sicurezza | a ogni push | allarmi nel repository |

**Fuori perimetro** (guardano il *codice*, non la produzione, e girano sul PC): i ganci di git
`prima_di_lanciare.py` / `prima_di_dire_fatto.py` / `guardia_commit.py`, `batteria.py`,
`occhio_del_fondatore.py`, `sentinella_ci.py`.

---

# 2. ✅ QUELLO CHE È FATTO BENE — e va detto prima dei difetti

**Il battito è un vero dead man's switch, e sa distinguere «tutto bene» da «io ero spento».**
Il commento a `fase83_server.py:11130-11136` spiega la differenza che quasi nessuno fa:

> *«Prima un Guardiano morto in silenzio era indistinguibile da un Guardiano che non trova
> niente: i log tacevano in tutti e due i casi, e il silenzio somiglia alla pace.»*

Il battito viene lasciato **in fondo** e **solo se il giro è arrivato fin lì**; se `scansiona`
esplode, l'`except` prende il controllo e il battito **non** viene lasciato → dopo 25 h
(`fase178_watchdog.py:45`) il watchdog grida.

**Il battito esce da una porta HTTP, apposta perché lo legga chi è fuori.**
`_stato_battito_guardiano` (`fase83_server.py:3360`) risponde `ok` · `muto` · `sconosciuto` su
`/api/health`, con due regole scritte e giuste:

- **non tocca mai `status`**: un Guardiano muto non è un sito giù, e far credere il contrario
  spegnerebbe un sito sano dentro i monitoraggi;
- **se non è misurabile dice `sconosciuto`, mai `ok`**: *«dichiarare sano cio' che non si e'
  guardato»*.

**La terza testa è fuori da casa, ed è consapevole di essere l'ultimo anello.**
`sentinella.yml` dichiara in intestazione i propri limiti — che GitHub può ritardare i lavori
programmati (per questo i minuti sono dispari: 7/22/37/52, «il rimedio noto, non una
superstizione»), che GitHub stessa cade, che i lavori si disattivano dopo 60 giorni di
inattività, e soprattutto:

> *«Chi guarda GitHub? Nessuno. Una catena di sorveglianti ha SEMPRE un ultimo anello
> scoperto: il mestiere e' renderlo il piu' affidabile possibile e DICHIARARLO, non fingere
> che non ci sia»*

E ha già chiuso il difetto giusto: la seconda testa «da lanciare a mano dal PC del fondatore»
è stata sostituita, perché *«A mano vuol dire mai»*.

**L'anti-spam c'è**: il watchdog avvisa solo quando lo **stato cambia**, o ogni `REMINDER_H=6`
ore se resta rotto (`deploy/watchdog.sh:15,32`). E le soglie del Guardiano sono larghe di
proposito (`fase186_guardiano.py:36`).

---

# 3. I TRE DIFETTI — tutti sul destinatario, nessuno sul rilevatore

## 3.1 🔴 L'allarme sui SOLDI viaggia sul canale che fallisce in silenzio

`fase83_server.py:11119-11124`:

```
prov = getattr(sistema, "email_provider", None)
if prov is not None and dest:
    _thg.Thread(target=prov.invia, args=(dest, "BookinVIP - ALLARME Guardiano: ...",
                riassunto_html(rep)), daemon=True).start()
```

Thread demone, **valore di ritorno scartato**. E il passaggio 15 ha misurato cosa c'è
dall'altra parte: `fase86_email.py` prova **2 volte**, poi restituisce `False` e scrive
`logger.warning` (`fase86:78`). Il quale **non lo vede nessuno**, perché il sorvegliante dei
guasti isolati guarda **solo gli `ERROR`** (`fase186_guardiano.py:275`).

Messo in fila, il giro si chiude su se stesso:

```
il Guardiano trova un buco nei soldi
   -> lo dice per email
      -> l'email non parte (SMTP giù, casella piena, dominio in blacklist)
         -> il fallimento è un WARNING
            -> il controllo dei guasti isolati legge solo gli ERROR
               -> nessuno sa né del buco nei soldi né dell'email persa.
```

⚠️ **Il confronto che rende il difetto evidente:** il watchdog dell'**infrastruttura** (il
meno grave dei due) grida su **Telegram**, che è un canale con conferma di consegna. Il
Guardiano dei **soldi** (il più grave) grida per **email**. E anche la sentinella esterna
grida via email (di GitHub). **Due allarmi su tre dipendono dalla posta**, e l'unico che non
ne dipende è quello che sorveglia le cose meno gravi.

💡 Il rimedio esiste già nel repository e non serve costruirlo: il watchdog manda su Telegram
riusando il bot del progetto (`deploy/watchdog.sh:48-53`), e il server ha già il codice per
parlare a Telegram (`fase83_server.py:9782`).

## 3.2 🟠 Non esiste un posto dove GUARDARE: si può solo aspettare di essere chiamati

`GET /api/bunker/guardiano` esiste, è vivo e restituisce il referto completo
(`fase83_server.py:3391-3401`). Misurato chi lo interroga:

```
grep -rln "bunker/guardiano" *.py *.html deploy/ collaudi/
  -> collaudi/giro_banco.py     (un collaudo)
  -> fase83_server.py           (chi lo espone)
  -> test_guardiano.py, test_happy_admin.py, test_rotte_ostile.py, test_avvio_e_ripristino.py
  -> deploy/ : NESSUN RISULTATO
```

**Nessuna delle 15 schede della Sala di controllo apre quella porta.** È la conferma
indipendente del difetto già contato dal passaggio 9 (voce 🔵), e qui se ne misura la
conseguenza operativa: il fondatore **non ha modo di chiedere «com'è messa adesso?»**. Può solo
ricevere — e solo se l'email arriva (3.1).

La differenza pratica fra le due cose è tutta qui:

| | oggi | se ci fosse la scheda |
|---|---|---|
| «è successo qualcosa stanotte?» | aspetta un'email | apre la pagina |
| «è tutto a posto adesso?» | **non è rispondibile** | apre la pagina |
| «l'allarme di ieri è rientrato?» | **non è rispondibile** | apre la pagina |

## 3.3 🟠 Cinque cose che i passaggi precedenti hanno misurato, e che nessuno sorveglia

| Cosa | Chi l'ha misurata | Perché nessuno la vede |
|---|---|---|
| **payout `in_transito` fermo** (soldi partiti e mai arrivati) | passaggio 13 | `_payout_anomali` (`fase186:141`) controlla la data **solo** per `maturato`; `in_transito` entra nell'allarme **solo se l'host non esiste più** (`:133`) |
| **email non partite** (voucher, PIN, ricevute, reset password) | passaggio 15 | `logger.warning` → fuori dal filtro `ERROR` |
| **avvisi all'host falliti su tutti i canali** (la richiesta scade in 24 h) | passaggio 15 | `avvisa()` conta i `falliti` e il chiamante scarta il risultato (`fase83:5610`) |
| **coordinate = indirizzo di casa pubblicato** | passaggio 11 | nessun controllo confronta ciò che si pubblica con ciò che si è promesso |
| **il diritto di recensione emesso con due orologi diversi** | passaggio 17 | nessun controllo confronta i due `non_prima_ts` |

E il numero che li tiene insieme: **in `fase83_server.py` ci sono 130 `logger.warning` e 99
`logger.error`.** Il sorvegliante ne guarda **99 su 229 — il 43%.** La scelta è motivata e la
motivazione è buona (*«i warning riguardano anche cose innocue, una miniatura non salvata»*),
ma **il livello del log è diventato il confine della sorveglianza**, e nessuno ha riguardato
chi stava da che parte quando quel confine è stato tracciato.

---

# 4. 🔑 LA FORMA DI FAMIGLIA

**Questa piattaforma sa accorgersi delle cose meglio di quanto sappia dirle.**

Sui **rilevatori** il lavoro è maturo e in tre casi supera lo standard: il battito distingue
il silenzio-sano dal silenzio-morto; la salute dice `sconosciuto` invece di mentire `ok`; la
terza testa vive fuori da casa e dichiara di essere l'ultimo anello. Non ho trovato **un solo
rilevatore rotto**.

Sui **destinatari** il lavoro non c'è: l'allarme più grave usa il canale più fragile, il suo
fallimento cade nella metà del registro che nessuno legge, e **non esiste una superficie da
interrogare** — l'unico modo di sapere come stanno le cose è che qualcuno te lo dica.

Detto in una riga: **il prodotto ha otto sensori e nessun cruscotto.**

💡 E il corollario, che è lo stesso di altri sei passaggi in una forma nuova: qui non manca il
sorvegliante — `/api/bunker/guardiano` è **costruito, vivo e risponde**. Manca **il filo fra
lui e gli occhi di chi decide**. Regola #23, «COSTRUITO ≠ COLLEGATO», **sesta comparsa in otto
passaggi**. Con una differenza che vale la pena notare: nelle cinque comparse precedenti il
pezzo scollegato era dentro il prodotto; qui il pezzo scollegato **è il prodotto e il suo
padrone.**

---

## ⚠️ LE MISURE CHE DA QUI NON POSSO FARE — comandi da incollare sul VPS

Se la catena stia davvero girando lo dicono solo il server e GitHub. Sola lettura:

```
# A) il battito e' vivo? (la domanda che riassume tutto l'anello 1)
curl -s https://bookinvip.com/api/health
docker exec casavip_app sh -c "ls -la /data/guardiano_ultimo_giro 2>/dev/null; date -u"

# B) il watchdog gira davvero ogni 10 minuti, e cosa ha detto
crontab -l | grep watchdog
docker exec casavip_app sh -c "tail -30 /data/watchdog.log 2>/dev/null"

# C) il Guardiano ha trovato qualcosa negli ultimi giri? (l'unica traccia è il registro)
docker exec casavip_app sh -c "grep 'GUARDIANO' /data/app.log | tail -20"

# D) il verdetto adesso, senza aspettare il giro delle 24h (puro: nessun invio, nessuna scrittura)
docker exec casavip_app python3 -c "import sys;sys.path.insert(0,'/app');from fase186_guardiano import scansiona;import main_casavip" 2>&1 | head -3
#    (se l'import del sistema non e' banale, la strada garantita e' la porta HTTP col Bunker:)
#    GET https://bookinvip.com/api/bunker/guardiano   con X-Bunker-Session

# E) l'allarme via email e' mai partito, o e' sempre fallito?
docker exec casavip_app sh -c "grep -c 'ALLARME Guardiano' /data/app.log; grep -c 'Email: invio fallito' /data/app.log"
```

⛔ Nota su (E): se il secondo numero è **> 0**, il difetto 3.1 non è teorico ed è **già
successo**. Se entrambi sono **0**, non è una prova di salute: `app.log` è un rotante da
5 file × 5 MB, e la storia più vecchia non esiste più.

---

## ✅ VERIFICATO E SCARTATO

1. **Un riavvio non salta il giro del Guardiano**: `_tick_guardiano` esegue `scansiona()`
   **prima** dello `sleep(86400)` (`fase83_server.py:11101-11146`). Un deploy quotidiano lo fa
   girare **più** spesso, non meno. Era il primo sospetto e non regge.
2. **Il thread del Guardiano non muore su un'eccezione**: l'`except` è **dentro** il `while`
   (`:11143`, *«thread TENUTO VIVO»*), e il battito non viene lasciato → il watchdog se ne
   accorge.
3. **Il battito non può mentire per un errore di scrittura**: se `segna_battito_guardiano`
   fallisce, l'errore è `logger.error` (visibile al filtro) e il battito **non** viene lasciato —
   *«sbaglia dalla parte giusta»* (`:11141`).
4. **La sentinella esterna non è cieca sul Guardiano**: legge il campo `guardiano` da
   `/api/health` e grida anche se il campo **sparisce** (`sentinella.yml:46-60`), non solo se
   dice `muto`.
5. **`/api/health` non mente sul database**: il commento a `fase83_server.py:3373` cita il
   difetto già chiuso (`/api/health/db` «saltava i percorsi vuoti e continuava a dire ok»).
6. **I backup hanno un controllo di freschezza** (8 h, `deploy/watchdog.sh:33`) — quindi un
   backup che smette di girare **si vede**. ⚠️ Resta vero il rischio già in memoria: vivono
   nello **stesso volume** dei dati.
7. **Il watchdog non fa spam**: allerta al cambio di stato o ogni 6 h.
8. **Nessun sorvegliante scrive sui dati**: `scansiona()` è dichiarata **pura**
   (`fase186_guardiano.py:31`), il watchdog è read-only, la sentinella fa una GET.
