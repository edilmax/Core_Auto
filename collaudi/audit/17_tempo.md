# B19 — PASSAGGIO 17 · IL TEMPO: OROLOGI, FUSI, SCADENZE

> **Referto di misura, non lista di cose da fare.** Sola lettura: nessun file di prodotto
> toccato (i 3 file modificati da altre sessioni sono stati solo LETTI), nessuna riparazione,
> nessuna suite, nessun commit, nessun giro sul VPS, nessuna chiamata di rete, nessun heredoc.
>
> Misurato il **2026-08-26**, ramo `master`, `HEAD = 663eab3`.
>
> Perimetro: **ogni finestra temporale che decide qualcosa** (una stanza, dei soldi, un
> diritto) e **ogni orologio da cui il prodotto legge l'ora**.

---

## RISULTATO IN UNA RIGA

**23 scadenze vive** lette da **6 orologi diversi**. Il lavoro sui fusi **è stato fatto ed è
buono** (`fase187_fuso_orario.py` esiste, è collegato, e le due finestre che toccano il
cliente — escrow e diritto di recensione — sono ancorate all'ora **del posto**). Restano
**3 divergenze misurate**: una finestra dichiarata due volte con due valori diversi (**120 s
contro 1.800 s**), un diritto **emesso due volte con due orologi diversi**, e **14 moduli che
scrivono l'ora senza dire quale fuso sia**.

---

# 1. LE 23 SCADENZE — valore, fonte, orologio

### Il giro dei soldi

| Finestra | Valore | Fonte | Orologio |
|---|---|---|---|
| Hold della stanza (prenotazione online) | **120 s** | `fase162_pagamenti_pendenti.py:23` | `time.time()` epoch |
| Sessione di pagamento Stripe | **1.800 s** (min 1800, max 86100) | `fase85_pagamenti_stripe.py:86-87` | Stripe |
| Richiesta da approvare (host) | **86.400 s** (24 h) | `fase83_server.py:5580` | `time.time()` |
| Hold dopo l'approvazione | **86.100 s** (23 h 55) | `fase83_server.py:929` `HOLD_APPROVAZIONE_SEC` | `time.time()` |
| Escrow: auto-rilascio all'host | **24 h dal check-in** | `fase160_escrow_garanzia.py:22` | ⭐ **ora LOCALE dell'alloggio** |
| Ripensamento (rimborso pieno) | **172.800 s** (48 h vere) | `fase83_server.py:472` | `time.time()` sull'istante **firmato nel voucher** |
| Purga dei pendenti 'scaduto' | **93.600 s** (26 h) | `fase162_pagamenti_pendenti.py:549` | `time.time()` |
| Diritto di recensione | dalla **mezzanotte del check-out** | `fase83_server.py:5488` | ⭐ **ora LOCALE dell'alloggio** |
| Convenzione ora di check-in | **15:00** | `fase83_server.py:349` `ORA_CHECKIN_LOCALE` | ora locale |

### I sorveglianti (`fase186_guardiano.py:47-54`)

| Controllo | Soglia |
|---|---|
| Escrow scaduto e non rilasciato | **48 h** |
| Bonifico `maturato` fermo | **7 giorni** |
| Stanza fantasma (notte occupata senza pendente) | **1 h** |
| Riconciliazione con Stripe | **30 giorni** |
| Marca temporale ferma | **48 h** |
| Guasti isolati (`ERROR` nel registro) | **24 h** |
| Cambio valuta fermo | **26 h** |

### Le credenziali

| Cosa | Durata | Fonte |
|---|---|---|
| Gettone host | **30 giorni** | `fase88_registro_host.py:41` |
| Gettone operatore admin | **8 h** | `fase83_server.py:2474` |
| Cookie di pagina admin / host | **12 h** | `fase83_server.py:9583` |
| Cookie di pagina Bunker | **15 min** | `fase83_server.py:9583` |
| **Gettone voucher** | ⛔ **nessuna scadenza** | (passaggio 11, voce 3) |
| **Gettone iCal** | ⛔ **nessuna scadenza** | (passaggio 11, voce 9) |

### Le altre

Pulizia foto orfane **7 giorni** (`fase83_server.py:2228`) · rampa commissioni **90 giorni /
1 anno** (`fase98_policy_commissione.py`) · backup ogni **6 h**, ne restano **14** = **84 h**
di storia (`deploy/backup_casavip.sh:6,20`).

---

# 2. I SEI OROLOGI

| # | Chiamata | Cosa restituisce | Dove | Quanti moduli |
|---|---|---|---|---|
| 1 | `time.time()` | secondi epoch, **senza fuso per costruzione** | tutto il giro dei soldi | ✅ il posto giusto |
| 2 | `datetime.datetime.now().isoformat(timespec="seconds")` | testo **senza marcatore di fuso** | i `ts` scritti negli archivi | **14 moduli** |
| 3 | `datetime.date.today()` | la data **del processo** | gate di pagina, tick giornalieri | **9 punti in `fase83`** |
| 4 | `datetime.utcnow()` | UTC esplicito | export fiscali, DAC7, dossier legale | 6 punti |
| 5 | `time.gmtime()` | UTC esplicito | anno fiscale, `fase177:544` | 1 |
| 6 | `fase187_fuso_orario` | **istante nell'ora del posto** | escrow, recensione, pass serratura | ⭐ 4 punti |

**In produzione i primi tre coincidono con UTC** perché il contenitore è in UTC — misurato dal
passaggio 16 e dichiarato in `fase186_guardiano.py:302`: *«Le date sono nell'ora del
container, che in produzione e' UTC»*. **Sulla macchina di uno sviluppatore no.**

---

# 3. IL LAVORO SUI FUSI — quello che C'È, e va detto per primo

`fase187_fuso_orario.py` esiste, è collegato e fa la cosa giusta. La sua intestazione descrive
il difetto che ha chiuso:

> *«diritto di recensione, pass della serratura, finestra di cancellazione) usava il fuso del
> SERVER, e l'alloggio NON aveva un fuso nel modello dati»*

Misurato oggi:

- l'alloggio **ha** il suo fuso IANA: colonna `fuso` (`fase57_vetrina.py:448`), dedotta al
  salvataggio da città+paese (`fase57:350`) e **ri-dedotta a ogni avvio** per le righe vecchie
  (`fase57:487-494`, idempotente, tocca solo `fuso=''`);
- l'**escrow** parte dalle 15:00 **locali del posto** (`fase83_server.py:5876` →
  `_istante_checkin(ci, self._fuso_alloggio(allog))`);
- il **diritto di recensione** parte dalla mezzanotte **locale del posto**
  (`fase83_server.py:5488` → `_mezzanotte_checkout(co, fuso)`), col commento che spiega
  perché: *«"dopo" e' l'ora del posto — non del server, che per un giapponese cambia giorno
  alle 09:00»*;
- dove il fuso manca, il ripiego è **prudente e dichiarato**
  (`_istante_checkin_prudente`, `fase83_server.py:352`: *«mai una finestra piu' stretta del
  giusto»*);
- il **ripensamento 48 h** non conta più i giorni di calendario ma i **secondi**, dall'istante
  **firmato nel gettone** (`fase83_server.py:475-495`), e il commento misura il difetto vecchio:
  *«La finestra reale andava da 48 a 72 ore secondo l'ora della prenotazione»*.

**Questo è il modello.** Le tre divergenze qui sotto sono i punti che non ci sono ancora
arrivati.

---

# 4. LE TRE DIVERGENZE MISURATE

## 4.1 🔴 La stessa finestra vale 120 secondi da una parte e 1.800 dall'altra

```
fase162_pagamenti_pendenti.py:23   HOLD_SECONDI_DEFAULT = 120     # la STANZA si libera
fase85_pagamenti_stripe.py:86      scade_sec = 1800               # la PAGINA di pagamento vale
```

L'ospite riceve una pagina di pagamento Stripe che vive **30 minuti**. La stanza che sta
pagando è sua per **2 minuti**. Fra il minuto 3 e il minuto 30 la pagina funziona ancora e la
stanza **non è più prenotata**.

Non è un baratro — il percorso del pagamento tardivo è costruito e l'ho verificato nel
passaggio 13: `conferma` accetta anche da `scaduto`, ri-blocca con chiave fresca
(`fase83_server.py:8112`), e se la stanza è stata presa nel frattempo marca il rimborso e
scrive la riga nel giornale (`:8123-8140`). **Nessun soldo si perde.** Ma:

- il commento a `fase162:23` dichiara l'intenzione — *«urgenza tipo Agoda: chi paga prima se
  la prende»* — e **2 minuti non sono l'urgenza di Agoda, sono meno del tempo di digitare i
  dati di una carta con la doppia autenticazione**;
- il valore 1.800 è il **minimo consentito da Stripe** (`fase85:87`, `max(1800, ...)`):
  **non si può stringere la pagina fino a 120 s.** Le due finestre non possono coincidere: o
  la stanza sale, o restano disallineate per costruzione.

Effetto misurabile sul cliente: **paga, e riceve una mail che dice «le date sono di nuovo
libere, riprova»** (`_email_recupero_hold`, `fase83_server.py:10461`) — oppure il rimborso.

## 4.2 🟠 Lo stesso diritto emesso due volte, con due orologi diversi

Il diritto di recensione nasce **due volte**, e le due nascite non usano lo stesso orologio:

```
fase83_server.py:5488   nbf = _mezzanotte_checkout(co, self._fuso_alloggio(allog))
                        -> mezzanotte LOCALE del posto           (alla prenotazione)

fase83_server.py:1411   nbf = int(_dtv.datetime.combine(co_data, _dtv.time.min).timestamp())
                        -> mezzanotte del PROCESSO che sta girando  (dalla pagina recensione)
```

E il cancello che decide se mostrare il modulo usa un terzo criterio, la **data del server**:

```
fase83_server.py:1405   if _dtv.date.today() < co_data or cancellata:   -> "dopo il soggiorno"
fase83_server.py:1137   if _dtv.date.today() >= _co_data and not _cancellata:   (pagina voucher)
```

Per un alloggio a Tokyo (UTC+9) il giorno del check-out comincia **9 ore prima** che in UTC:
alle 08:00 ora di Tokyo il server è ancora al giorno prima, e all'ospite la pagina risponde
*«potrai recensire dopo il soggiorno»* mentre il gettone che ha in mano dice già di sì.
Per Honolulu (UTC−10) succede il contrario.

**La funzione giusta esiste ed è a tre righe di distanza.** `_mezzanotte_checkout(co, fuso)` è
usata in un punto e non nell'altro.

## 4.3 🟡 Quattordici moduli scrivono l'ora senza dire quale sia

`datetime.datetime.now().isoformat(timespec="seconds")` produce `2026-08-26T14:03:11` —
**senza `Z`, senza `+00:00`, senza niente**. È la forma con cui vengono scritti i `ts` di:

```
fase57_vetrina.py:545,681,697      fase58_channel_manager.py:211,323,632,702
fase63_recensioni.py:169           fase65_split_payment.py:158
fase67_coda_intelligente.py:201    fase70_turnover.py:139
fase76_viral_loop.py:136           fase79_dichiarazione.py:119,165
fase80_sentinel.py:204             fase62_predictive_noshow.py:119
fase52_persistenza_metriche.py:157 fase38_backup.py:68
```

In produzione sono UTC. Ma:

- **il pannello li mostra così come sono** a un host che può essere a Tokyo o a Città del
  Messico: un'ora nuda letta come ora locale sbaglia di ore;
- **il codice che sa che va dichiarato esiste già**, e sa anche perché — `fase83_server.py:3543`,
  nel dossier legale: *«l'ora DEVE dichiarare il fuso: in un fascicolo legale un orario nudo
  e' contestabile ("che fuso era?"). E' UTC: si scrive.»* Quel `Z` c'è **negli export legali e
  fiscali** (6 punti) e **non c'è in nessuno dei 14 archivi**;
- ⚠️ una di quelle righe è `fase163_accettazioni` — la **prova firmata** dell'accettazione del
  contratto, che porta data, ora e IP. (Il suo `ts` passa da un altro percorso, ma il fascicolo
  legale la ripubblica con `Z` a `fase83:3543`: le due forme convivono.)

---

# 5. 🔑 LA FORMA DI FAMIGLIA

**Il tempo, qui, è stato riparato una decisione alla volta — e ogni riparazione ha lasciato
in piedi il gemello che non era stato chiesto.**

Sono tre riparazioni vere, documentate, con il difetto vecchio scritto accanto:

| Riparazione | Il gemello rimasto indietro |
|---|---|
| il ripensamento passa da «giorni di calendario» a **secondi da un istante firmato** (`:475`) | i gate di pagina restano a `date.today()` (`:1137`, `:1405`) |
| la recensione parte dalla **mezzanotte locale del posto** (`:5488`) | la stessa pagina la ri-emette dalla **mezzanotte del processo** (`:1411`) |
| l'escrow parte dal **check-in locale** (`:5876`) | l'hold della stanza resta un numero fisso globale (`fase162:23`) |

E la firma comune: **la riparazione entra dove il valore viene FIRMATO in un gettone, e non
entra dove il valore viene RICALCOLATO al volo.** Nei tre casi il dato corretto viaggia già
dentro il token (`prenotato_ts`, `non_prima_ts`, `sblocco_auto_ts`): chi lo legge dal token è
giusto, chi lo ricalcola dalla data del server è sbagliato.

💡 Il corollario: **queste tre voci non si riparano scrivendo codice nuovo — il codice giusto
esiste in tutti e tre i casi, nello stesso file.** Si riparano togliendo il ricalcolo e
leggendo il gettone. È la quinta comparsa della regola #23 in sette passaggi, in una forma
nuova: qui la fonte unica non è una costante, **è un istante già firmato**.

---

## ⚠️ LE MISURE CHE DA QUI NON POSSO FARE — comandi da incollare sul VPS

Da qui non posso sapere **con che ora sta girando la macchina vera**, e tutte e tre le
divergenze cambiano forma se il contenitore non è in UTC. Sola lettura:

```
# A) il fuso del contenitore, dell'host e di Python (le tre cose che devono coincidere)
docker exec casavip_app sh -c "date -u; date; cat /etc/timezone 2>/dev/null; echo \$TZ"
docker exec casavip_app python3 -c "import time,datetime;print('now   ',datetime.datetime.now().isoformat());print('utcnow',datetime.datetime.utcnow().isoformat());print('tzname',time.tzname,'altzone',time.altzone)"

# B) quanti alloggi hanno davvero il fuso (se 0, ovunque vale il ripiego prudente)
docker exec casavip_app python3 -c "import sqlite3;c=sqlite3.connect('file:/data/catalogo.db?mode=ro',uri=True);print('con_fuso',c.execute(\"SELECT COUNT(*) FROM alloggi WHERE fuso<>''\").fetchone()[0]);print('senza_fuso',c.execute(\"SELECT COUNT(*) FROM alloggi WHERE fuso=''\").fetchone()[0]);print(c.execute('SELECT slug,citta,paese,fuso FROM alloggi LIMIT 20').fetchall())"

# C) quante prenotazioni sono davvero scadute nei 2 minuti (la divergenza 4.1 e' gia' successa?)
docker exec casavip_app python3 -c "import sqlite3;c=sqlite3.connect('file:/data/pendenti.db?mode=ro',uri=True);print(dict(c.execute('SELECT stato,COUNT(*) FROM pendenti GROUP BY stato').fetchall()));print('scadenza-creazione:',c.execute('SELECT riferimento,scadenza_ts-creato_ts FROM pendenti LIMIT 20').fetchall())"

# D) l'orologio di SQLite contro quello di Python (la trappola nota: sono due orologi)
docker exec casavip_app python3 -c "import sqlite3,time;c=sqlite3.connect(':memory:');a=c.execute(\"SELECT strftime('%s','now')\").fetchone()[0];b=int(time.time());print('sqlite',a,'python',b,'scarto_s',int(a)-b)"
```

⛔ Nota su (D): è la trappola già pagata (memoria «le cinque trappole dell'orologio finto»).
Nel codice vivo **nessun archivio usa `CURRENT_TIMESTAMP` o `datetime('now')`** — l'unica
occorrenza è in `fase34_prenotazioni.py:111` (modulo morto) e in `fase23_datastore.py:164`
(mai raggiunto). Il comando serve solo a confermare che i due orologi coincidono sul server.

---

## ✅ VERIFICATO E SCARTATO

1. **Nessun archivio vivo legge l'ora dal database**: zero `CURRENT_TIMESTAMP` e zero
   `datetime('now')` fuori dai due moduli morti. La trappola nota è chiusa.
2. **Ogni store accetta un orologio iniettabile** (`orologio=`/`_now`): è ciò che rende
   verificabili le scadenze senza aspettare, e spiega perché `freezegun` qui non serve.
3. **Il ripensamento non è manomettibile dal browser**: l'istante sta nel gettone firmato
   (`fase83_server.py:485`).
4. **I gettoni vecchi non perdono un diritto già comunicato**: se manca `prenotato_ts` si
   ricade sul conteggio a giorni, che è **più largo** (`fase83_server.py:496-503`). È la scelta
   giusta, ed è scritta.
5. **Le soglie del Guardiano sono larghe di proposito** e il file lo dichiara
   (`fase186_guardiano.py:36-38`): *«un allarme che grida per un ritardo normale e' un allarme
   che si impara a ignorare»*.
6. **Il backup non dipende dal fuso**: il nome del file usa `date +%Y%m%d-%H%M%S` del
   contenitore e la rotazione è per **ordine di modifica** (`ls -1t`), non per data nel nome.
7. **Le 24 h della richiesta e le 23 h 55 dell'hold post-approvazione non sono una divergenza**:
   `86100 < 86400` di proposito, così la sessione Stripe scade **prima** che la stanza si
   liberi. È allineamento corretto, non un errore di 5 minuti.
