# 18 — GLI STRUMENTI DI ANALISI STATICA, ACCESI

> Referto della sessione del **2026-08-26**, su `663eab3`.
> Mandato: accendere cinque strumenti gratuiti nella CI, misurare, **congelare lo
> storico perche' il vecchio non blocchi**, e configurare perche' **da qui in avanti
> ogni modifica nuova debba restare pulita**.
> Vincolo rispettato alla lettera: **nessuna riga di codice di produzione e' stata
> toccata per far tacere uno strumento.** Nessun `fase*.py`, niente in `deploy/`,
> nessun test esistente. Solo file di configurazione, il workflow, e un attrezzo nuovo.

---

## IL MECCANISMO, IN QUATTRO RIGHE

Accendere questi cinque strumenti su un codice gia' scritto produce **1.258
segnalazioni**. Farle bloccare subito significa CI rossa ogni giorno per debito
vecchio, e nel giro di una settimana nessuno guarda piu' il rosso: e' il danno
peggiore possibile. Lasciarle informative significa che nessuno legge il log.

La terza strada e' il **cricchetto**: si fotografa lo stato di oggi, si dichiara che
quello **non** blocca, e si blocca su tutto cio' che compare **in piu'**. Il numero
puo' solo scendere.

```
python collaudi/cricchetto_statico.py tutti          <- il giudizio (blocca sul nuovo)
python collaudi/cricchetto_statico.py ruff --azzera  <- rifa' la fotografia
```

**La chiave della fotografia e' `(file, regola) -> quante volte`**, non il numero di
riga: aggiungere un commento sposta tutte le righe e una fotografia appesa alla riga
diventerebbe rossa senza motivo. Non e' nemmeno il totale: togliere un rilievo da un
file e aggiungerne uno in un altro lascerebbe il totale identico e farebbe passare il
difetto. Unica eccezione dichiarata: `gitleaks` sulla **storia** usa la sua impronta
nativa (commit + file + regola + riga), perche' un commit gia' scritto non si muove.

**VISTO ROSSO.** Il cricchetto e' stato provato in entrambi i versi, non solo in
verde: `--autoprova` inietta una segnalazione finta e il confronto la vede (uscita 1);
e con un file guasto per davvero (`collaudi/zz_prova_cricchetto.py`, un `import os`
inutilizzato) ha detto `+1 collaudi/zz_prova_cricchetto.py|F401` ed e' uscito 1.
Tolto il file, e' tornato verde da solo.

---

## IL QUADRO IN UNA TABELLA

| # | strumento | versione | segnalazioni | gravi | dove blocca |
|---|---|---|---|---|---|
| 1 | ruff | 0.15.22 | **686** | 0 nella lista stretta | gate stretto + cricchetto |
| 2 | bandit | 1.8.6 | **548** | **0 HIGH** (90 MEDIUM, 458 LOW) | gate HIGH + cricchetto |
| 3 | gitleaks | 8.30.1 | **8** (storia) | 0 veri | cricchetto |
| 4 | pip-audit | 2.9.0 | **10** falle in 6 pacchetti | 0 in produzione | cricchetto |
| 5 | semgrep | 1.136.0 | **6** | 0 veri | cricchetto |
| | **totale congelato** | | **1.258** | | |

Tutte e cinque le fotografie stanno in `collaudi/baseline/*.json` e **viaggiano col
progetto** (vedi la sezione sulla trappola del `.gitignore`, in fondo).

---

## 1 — RUFF

**Misura.** 686 segnalazioni, 25 regole distinte, 234 file, 333 chiavi
`(file, regola)`. Le prime cinque famiglie: `F401` import inutilizzato (177),
`E702` piu' istruzioni su una riga (125), `B023` funzione che usa la variabile del
ciclo (90), `E701` (47), `E402` import non in cima (43).

**Gravi.** Zero. Le regole da "bug certo" o "buco di sicurezza certo" (`E9`, `F63`,
`F7`, `F82`, `S102` exec, `S301` pickle, `S307` eval, `S324` hash debole, `S506`
yaml.load, `S602/S604/S605/S609` shell, `S612`, `S701`) valgono **0 rilievi** sul
prodotto vivo: e' il gate stretto che c'era gia' e che continua a bloccare.

**Configurato.** `ruff.toml` esisteva gia' ed e' **rimasto identico**: le sue regole,
i suoi `ignore` e le loro motivazioni erano gia' scritti e non c'era motivo di
toccarli. Il pezzo nuovo e' il cricchetto: `collaudi/baseline/ruff.json` congela le
686, e `collaudi/cricchetto_statico.py ruff` blocca sulla 687-esima. Il job
`lint-severo` resta informativo com'era: serve a decidere cosa promuovere.

**Rumore.** Non misurabile come falso allarme: `F401`, `E702`, `E402` sono
osservazioni vere su codice vero. Non sono difetti, sono debito di stile — ed e'
esattamente per questo che stanno nella fotografia invece che nel gate.

---

## 2 — BANDIT

**Misura.** 548 segnalazioni, 18 regole, 207 file (escludendo `collaudi/`,
`_archivio/`, `app.py`, `data/`, `deploy/` come gia' faceva la CI).
Per gravita': **0 HIGH**, 90 MEDIUM, 458 LOW.
Le prime famiglie: `B106` password passata come argomento (134), `B101` `assert`
(118), `B110` `try/except/pass` (66), `B311` random non crittografico (50),
`B608` SQL costruito a stringa (41), `B603` subprocess (36).

**Gravi.** Zero HIGH — il gate `--severity-level high --confidence-level high` che
c'era gia' resta verde, ed e' un verde vero, non un verde per assenza di scansione.

**Configurato.** Nessun file di configurazione nuovo, di proposito: le esclusioni
erano gia' scritte nella riga di comando della CI e duplicarle in un `bandit.yaml`
avrebbe creato **due posti che possono contraddirsi**. Il cricchetto
(`collaudi/baseline/bandit.json`) congela le 548 e blocca sulla 549-esima. Nel job
`lint-severo` e' stato aggiunto il quadro completo per gravita', report-only, perche'
oggi il log mostrava solo i HIGH — cioe' niente.

**Rumore.** `B101` (118 `assert`) e `B106` (134) sono in gran parte convenzioni di
collaudo, non difetti. Come sopra: stanno nella fotografia, non nel gate.

---

## 3 — GITLEAKS

**Misura — e qui c'e' una cosa vera da leggere due volte.**

```
gitleaks dir .   -> 35 rilievi   (il disco: tutto quello che c'e' nella cartella)
gitleaks git .   ->  8 rilievi   (926 commit: quello che GitHub ha davvero)
```

I **27 di scarto** stanno tutti in file **esclusi da `.gitignore` e mai versionati**.
Fra questi, sul disco del fondatore e **in chiaro**:

| file (NON versionato) | cosa contiene |
|---|---|
| `_SEGRETI_casavip_copia-locale.txt.bak` | 1 token di accesso **Stripe** |
| `_SEGRETI_vecchio-stack_ex-env.txt.bak` | 1 token **Stripe**, 1 token **Telegram**, 2 chiavi generiche |

⚠️ **Su GitHub non ci sono mai arrivati** — verificato: `git check-ignore` conferma
che li esclude la riga `*.bak` del `.gitignore`, e la scansione della storia non li
trova in nessuno dei 926 commit. Ma sono in chiaro su un disco, e il repository e'
**pubblico**. Non e' un lavoro di questa sessione e non e' stato toccato niente:
e' un fatto misurato, e decide il fondatore.

**Gravi (sulla storia).** Zero veri. Tutti e 8 i rilievi sono `generic-api-key` in
file di test, e tutti e 8 sono valori finti di collaudo:
`chiavecollaudoesterni0123456789a`, `chiavecollaudoaltro0123456789ab`,
`s3greto-di-collaudo`, `idem_2f7c9a11`, `qt_firmato_123`, `aBc12345token`.

**Configurato.** File nuovo `.gitleaks.toml`: si parte dalle regole predefinite
(oltre 150 fornitori: Stripe, AWS, GitHub, Telegram...) e si aggiunge una sola
allowlist di **percorsi gia' esclusi da `.gitignore`** — serve solo ad allineare chi
lancia `gitleaks dir` a mano con cio' che la CI giudica davvero. **Nessuna allowlist
tocca il codice di prodotto.** La CI scarica il binario a versione inchiodata
(v8.30.1) e ne **verifica lo sha256** prima di eseguirlo, e fa il checkout con
`fetch-depth: 0` — senza, avrebbe scandito 1 commit su 926 e detto "pulito".
Fotografia in `collaudi/baseline/gitleaks.json`: **contiene solo le impronte, mai i
valori trovati.**

**RUMORE: 8 su 8 = 100%.** La regola del 10% (PARTE 17 del `METODO_v4`) direbbe di
spegnerlo. **Non e' stato spento, e il motivo e' questo:** quei 100% sono tutti nella
storia gia' scritta, che la fotografia congela una volta per sempre. Da qui in avanti
il denominatore riparte da zero, e il primo rilievo nuovo sara' l'unico rilievo — su
un repository pubblico dove una chiave vera, una volta spinta, e' pubblicata per
sempre. **Se dopo un mese di lavoro vero il tasso restasse sopra il 10%, si spegne:
misurandolo, non a sensazione.**

---

## 4 — PIP-AUDIT

**Misura — il numero che c'era prima non parlava di noi.**

```
pip-audit            -> 136 falle in 31 pacchetti   <- l'ambiente in cui gira
pip-audit -r requirements.txt -> 10 falle in 6 pacchetti   <- il prodotto
```

Nella CI `pip-audit` girava **senza `-r`**, cioe' guardava l'ambiente del job —
che contiene `ruff`, `mypy` e `bandit`, gli **attrezzi**, non il prodotto. Il primo
numero e' rumore per definizione: parla di `torch`, `scapy`, `aiohttp`, roba
installata su questo PC e che in produzione non esiste.

Le 10 vere: `flask` (1), `gunicorn` (2), `python-dotenv` (1), `requests` (3),
`urllib3` (2), `click` (1).

**Gravi.** Zero **in produzione**, e questo va detto con precisione: il `Dockerfile`
di produzione **non installa `requirements.txt`**. L'immagine gira su **pura stdlib**
(`COPY main_casavip.py`, `COPY fase*.py`, `COPY deploy`), quindi nessuno di quei sei
pacchetti e' dentro il container che serve i clienti. Quelle 10 falle vivono nello
stack Flask legacy e negli strumenti di collaudo.

**Configurato.** Il passo report-only della CI ora usa `-r requirements.txt` (prima
misurava se stesso). Il gate vero e' il cricchetto:
`collaudi/baseline/pip-audit.json` congela le 10 e blocca sull'undicesima —
cioe' su una falla **nuova** o su una dipendenza **nuova**. Non e' stata cambiata
nemmeno una versione in `requirements.txt`: alzarle e' una modifica alla produzione
e non era autorizzata.

**Rumore.** 0 falsi. Le 10 sono falle vere in librerie vere; e' l'**impatto** a
essere nullo, non la segnalazione.
⚠️ **Limite dichiarato:** `pip-audit -r` risolve le dipendenze transitive al momento
in cui gira, e i cataloghi delle falle si aggiornano. Quindi questo e' l'unico dei
cinque che puo' accendersi **senza che nessuno abbia toccato il codice** — ma quando
succede e' un segnale vero (una falla pubblicata stanotte), non un guasto.

---

## 5 — SEMGREP

**Misura.** 6 segnalazioni, 5 chiavi, con il pacchetto curato `p/python`.
Ma il numero interessante e' un altro:

```
timeout di serie (5 s)   -> 4 rilievi  +  12 regole andate in TIMEOUT
timeout a 120 s          -> 6 rilievi  +   0 timeout
```

Le 12 regole in timeout **non avevano guardato** `fase83_server.py`,
`test_pipeline_ci.py` e `assistente_gestionale.py` — i file piu' grossi, cioe' il
server di produzione. Erano punti ciechi silenziosi: lo strumento stampava "4" e
sembrava pulito. Alzando il tetto sono comparsi i **due rilievi nascosti, entrambi in
`fase83_server.py`**. Il cricchetto ora **dichiara ogni timeout a schermo**: una
regola che non ha guardato un file non e' un'assoluzione.

**Gravi.** Zero veri, guardati uno per uno:

| rilievo | dove | verdetto |
|---|---|---|
| `insecure-hash-algorithm-sha1` | `fase83_server.py:779` | falso: e' l'impronta ETag per la cache HTTP, gia' scritta `usedforsecurity=False` con il commento accanto |
| `python-logger-credential-disclosure` | `fase83_server.py:4115` | falso: la riga registra `marca_id` e l'IP, **non** il token — semgrep si e' fermato alla parola «token» nel testo |
| `avoid_app_run_with_bad_host` | `fase13_protocollo_finale.py:973` | benigno: `app.run(host='0.0.0.0')` dentro `if __name__ == '__main__'`, avvio a mano, non la produzione |
| `insecure-hash-algorithm-sha1/md5` (3) | `collaudi/` | benigno: attrezzi d'officina, impronte non crittografiche |

**Configurato.** Pacchetto `p/python` dal registro, `--timeout 120`, `--metrics off`,
le stesse esclusioni degli altri. Fotografia in `collaudi/baseline/semgrep.json`.
⛔ **Il pacchetto NON e' stato copiato dentro il repository**, di proposito: quelle
regole hanno una licenza propria. ⚠️ **Conseguenza dichiarata:** le regole si
aggiornano da remoto, quindi un giorno puo' comparire un rilievo nuovo senza che il
codice sia cambiato. Il cricchetto lo mostrera' come «NUOVO»: e' un segnale vero (una
regola nuova ha visto una cosa vecchia), si legge e si rifa' la fotografia.

**Rumore.** 6 su 6 sono falsi o benigni = **100%**, ma su un denominatore di 6.
Come per gitleaks: sono tutti nella fotografia, il denominatore riparte da zero, e la
misura vera si fa fra un mese sul lavoro nuovo.
⚠️ **Costo:** ~13 minuti da solo su questo PC (632 file). Il tetto del job `qualita`
e' stato alzato da 15 a 45 minuti, perche' un job ucciso dal tetto e' indistinguibile
da un guasto.

---

## COSA E' CAMBIATO NEI FILE (l'elenco completo)

| file | stato | cosa |
|---|---|---|
| `collaudi/cricchetto_statico.py` | **nuovo** | il motore: cinque lettori, un giudizio solo |
| `collaudi/baseline/ruff.json` | **nuovo** | 686 congelate |
| `collaudi/baseline/bandit.json` | **nuovo** | 548 congelate |
| `collaudi/baseline/gitleaks.json` | **nuovo** | 8 impronte (nessun segreto dentro) |
| `collaudi/baseline/pip-audit.json` | **nuovo** | 10 falle congelate |
| `collaudi/baseline/semgrep.json` | **nuovo** | 6 congelate |
| `.gitleaks.toml` | **nuovo** | regole predefinite + allowlist dei soli percorsi gia' ignorati |
| `.github/workflows/ci.yml` | modificato | `fetch-depth: 0`, versioni inchiodate, 2 passi nuovi nel job `qualita`, `pip-audit -r`, quadro bandit in `lint-severo`, tetto 15 -> 45 min |
| `.gitignore` | modificato | eccezione per `collaudi/baseline/*.json`, esclusione di `_ultimo_giro/` |
| `ruff.toml` | **non toccato** | era gia' giusto |
| qualunque `fase*.py`, `deploy/`, `test_*.py` | **non toccati** | come da mandato |

---

## LA TRAPPOLA DEL `.gitignore` — S13, per la terza volta

`.gitignore:25` contiene `*.json`. Senza un'eccezione, le cinque fotografie
**sarebbero rimaste su questo computer in silenzio** e in CI il gate avrebbe risposto
«NESSUNA FOTOGRAFIA» — cioe' rosso per finta, a ogni giro. E' lo stesso sbaglio che
aveva gia' fatto sparire `collaudi/bombe_a_tempo.json` e `collaudi/baseline_tariffe.txt`.

Preso **con `git add --dry-run`, non a occhio**:

```
add 'collaudi/baseline/bandit.json'
add 'collaudi/baseline/gitleaks.json'
add 'collaudi/baseline/pip-audit.json'
add 'collaudi/baseline/ruff.json'
add 'collaudi/baseline/semgrep.json'
```

E il verso opposto: `collaudi/baseline/_ultimo_giro/` — dove finisce l'uscita grezza
degli strumenti, **compresi i valori che gitleaks ha trovato** — resta escluso.
`git check-ignore -v` lo conferma riga per riga.

---

## PERCHE' I CINQUE PASSI STANNO DENTRO IL JOB `qualita` E NON IN UN JOB LORO

Non e' una scorciatoia, e' un vincolo che il repository stesso impone.
`test_pipeline_ci.py:962` contiene la lista dei job bloccanti **scritta a mano**, e
`test_i_needs_del_gate_sono_esattamente_i_bloccanti` pretende che combaci con i
`needs` del gate. Un job nuovo avrebbe richiesto di modificare quel test — e il
mandato di questa sessione vieta di toccare i test esistenti. Mettendo i passi dentro
un job gia' bloccante e gia' dentro il gate, il risultato e' identico e non si tocca
niente.

Due dettagli fini, per chi tocchera' questo file dopo:
`test_ruff_stretto_blocca_e_la_sua_lista_e_a_cricchetto` pretende **un solo** passo
del job `qualita` che contenga `--select`, e `COMANDI_CHE_DEVONO_BLOCCARE` pretende
**una sola** occorrenza di `bandit -r .`. I passi nuovi non contengono ne' l'una ne'
l'altra stringa: il giudizio passa dal comando `python collaudi/cricchetto_statico.py`.

---

## VERIFICHE FATTE, CON L'ESITO

| verifica | esito |
|---|---|
| `ruff check collaudi/cricchetto_statico.py` | pulito |
| byte di controllo invisibili nel file nuovo | nessuno |
| `ci.yml` si legge come YAML e i 10 passi del job `qualita` sono al loro posto | sì |
| `python -m unittest test_pipeline_ci` (da **PowerShell**, S14) | **Ran 290 — OK** |
| cricchetto visto **rosso** con segnalazione iniettata | uscita 1 |
| cricchetto visto **rosso** con un guasto vero (`F401`) | uscita 1 |
| cricchetto verde dopo aver tolto il guasto | uscita 0 |
| `git add --dry-run` sulle fotografie | 5 su 5 entrano |
| cricchetto `tutti` da capo a fondo, coi cinque strumenti veri | **5 su 5 verdi, uscita 0** |
| caricatore rimisurato PRIMA del giro (S14) | **RACCOLTI: 6012** — identico a `RIPRENDI_QUI.md` |
| **suite intera da PowerShell, una volta sola** | **`Ran 6007 tests in 1731.102s — OK (skipped=4)`, EXIT=0** |

Il numero eseguito (6007) e lo scarto dal caricatore (5, le guardie `openssl` che
PowerShell non ha) sono **identici** all'ultimo giro dichiarato: gli strumenti nuovi
non hanno spostato niente nella suite.

⚠️ **Un giro da Git Bash e' stato buttato**: 4 fallimenti, tutti perche' la suite
rifiuta MSYS (`MSYSTEM=MINGW64`, sbaglio S11 — da li' `openssl` c'e', da PowerShell
no). Rilanciato da PowerShell: 290 su 290. E' la stessa trappola gia' scritta in
memoria, e ci sono ricascato: vale la pena rileggerla prima, non dopo.

---

## QUELLO CHE HO INCONTRATO E NON HO TOCCATO

Scritto qui e lasciato dov'era, come da mandato («se qualcosa ti blocca, scrivilo e
vai avanti»). Nessuna di queste e' opera di questa sessione.

1. **I due `_SEGRETI_*.txt.bak` sul disco** con token Stripe e Telegram in chiaro.
   Non sono su GitHub (verificato sui 926 commit). Decide il fondatore.
2. **Tre file di produzione risultano modificati nell'albero** — `fase57_vetrina.py`,
   `fase58_channel_manager.py`, `fase81_bootstrap_casavip.py` — da altre sessioni.
   Non sono stati toccati qui e non entrano in nessuna misura di questo referto.
3. **Un avviso di equivalenza decaduta** compare girando `test_pipeline_ci`:
   `fase184_marca_temporale.py:136`, impronta dichiarata tutta a zeri contro quella
   calcolata. E' un avviso, non un fallimento, ed e' precedente a questa sessione.
4. **`pip-audit` sull'ambiente locale** riporta 136 falle in 31 pacchetti (torch,
   scapy, aiohttp...): e' il PC, non il prodotto. Ignorabile, ma spiega perche' il
   numero della CI di prima era senza senso.
5. **La produzione non installa `requirements.txt`.** Vale la pena saperlo: le uniche
   dipendenze che contano per il container sono zero, e il valore di `pip-audit` qui
   sta nel proteggere gli strumenti e lo stack legacy, non l'immagine.

---

## ⛔ NON COMMESSO, NON SPINTO, VPS FERMO

Come da mandato: **nessun commit, nessun push, nessuna richiesta di unione, nessun
`git pull` sul server.** L'albero e' modificato e basta. Il commit lo autorizza il
fondatore a voce.
