# B19 — PASSAGGIO 12 · DOVE FINISCONO I DATI PERSONALI, ARCHIVIO PER ARCHIVIO

> **Referto di misura, non lista di cose da fare.** Sola lettura: nessun file di prodotto
> toccato, nessuna riparazione, nessuna suite, nessun commit, nessun giro sul VPS, nessun
> server avviato. Le uniche chiamate di rete sono **3 GET pubbliche** già fatte nel passaggio
> 11 (`/api/catalogo`, `/api/mappa`) e qui non ripetute.
>
> Misurato il **2026-08-25**, ramo `master`, `HEAD = 3ceb4c5`, **sull'albero di lavoro**
> (10 file modificati non committati, non miei; nessuno dei quali tocca un archivio o la
> cancellazione — `git diff --stat`: `fase163_accettazioni.py` +26 sul gate di registrazione,
> `fase83_server.py` +32 su login/registrazione, il resto `.md`/`.html`/test).
> Numeri di riga = **file come stanno sul disco adesso**.

---

## I DUE NUMERI

```
ARCHIVI CHE CONTENGONO DATI PERSONALI ............................. 48
   di cui tabelle SQLite in database vivi ......................... 33  (in 24 database)
   di cui archivi fuori dal database (file, log, cache, backup) ....  7
   di cui servizi esterni a cui i dati ESCONO ......................  8

ARCHIVI CHE LA CANCELLAZIONE TOCCA DAVVERO ........................  6
   = 4 chiamate di DELETE, che coprono 6 tabelle
   file toccati: 0 · backup toccati: 0 · servizi esterni toccati: 0
```

**6 su 48 = 12,5%.** E i 6 sono tutti nella prima categoria: **la cancellazione non esce mai
dal database.**

### Le 4 chiamate, con la riga che le esegue

| # | Riga che cancella | Metodo | Tabelle svuotate |
|---|---|---|---|
| 1 | `fase156_erasure.py:207` | `inv.cancella_alloggio(slug)` per ogni slug | `inventario`, `movimenti` (`fase58_channel_manager.py:172`) |
| 2 | `fase156_erasure.py:209` | `cat.cancella_alloggi_host(host_id)` | `alloggi`, `alloggio_immagini` (`fase57_vetrina.py:809`) |
| 3 | `fase156_erasure.py:211` | `msg.cancella_messaggi_host(host_id)` | `messaggi` (`fase113_messaggistica.py:95`) |
| 4 | `fase156_erasure.py:215` | `reg.cancella_host(host_id)` | `host` (`fase88_registro_host.py:636`) |

### ⛔ E la quinta chiamata non esiste

`fase156_erasure.py:213` scrive `rep["cancellati"]["referral"] = _safe(viral.cancella_host, ...)`
ed è protetta da `hasattr(viral, "cancella_host")`. **Quel metodo non esiste.**
`ViralLoopEngine` (`fase76_viral_loop.py:60`) espone 8 metodi pubblici
(`inizializza_schema`, `genera_codice`, `registra_referee`, `qualifica_referee`,
`credito_disponibile`, `usa_credito`, `_accredita`, `_apri`): **né `cancella_host` né
`conta_host`.** (Il `__getattr__` che c'è nel file sta su `_ConnCondivisa`, riga 288 — un'altra
classe.)

Conseguenza misurata, in tre passi:

1. `hasattr` → `False`, la riga 213 **non viene mai eseguita**: le tre tabelle del referral
   restano piene;
2. la verifica gemella a `fase156:225-226` è guardata dallo stesso `hasattr` su `conta_host` →
   `residui["referral"]` **non viene mai scritto**;
3. quindi `rep["ok"] = all(v == 0 for v in residui.values())` (`:236`) calcola il verdetto su
   **4 archivi**, e `rep["verificato_archivi"]` (`:237`) ne elenca **4** — mentre la docstring
   del modulo dichiara *«rimuove un host e TUTTI i suoi dati da OGNI archivio … e poi
   RI-CONTROLLA ogni archivio»* e il pannello stampa **«Verifica residui (tutti 0)»**
   (difetto già contato dal passaggio 9, voce 3: **qui se ne misura la causa**).

**Il referral non è «non cancellato»: è un archivio che il rapporto di cancellazione non
sa nemmeno di avere saltato.**

---

## GLI ARCHIVI NON TOCCATI DALLA CANCELLAZIONE — uno per riga

### Tabelle di database vivi (27)

```
fase76_viral_loop.py:88          referral_codici     host_id, codice invito
fase76_viral_loop.py:95          referral_eventi     host_id referente e referee
fase76_viral_loop.py:103         crediti             utente, credito residuo
fase88_registro_host.py:142      host_impronte       HMAC di email/telefono/CF/P.IVA/CIN  [tenuta APPOSTA]
fase162_pagamenti_pendenti.py:61 pendenti            EMAIL OSPITE + corpo_json dell'intera prenotazione + quote_token
fase127_checkin_digitale.py:87   checkin             ospiti_json: nome e documento di OGNI ospite
fase163_accettazioni.py:443      accettazioni        host_id, documento, VERSIONE, INDIRIZZO IP, firma HMAC
fase143_kyc_host.py:61           kyc                 host_id, session_ref di Stripe Identity
fase131_payout_dashboard.py:78   payout              host_id, importi dovuti, valuta, stato
fase177_financial_controller.py:135 libro_giornale   riferimento, soggetto ("ospite:<rif>", host)
fase177_financial_controller.py:161 note             riferimento, soggetto delle note di debito
fase177_financial_controller.py:175 debiti           host_id, residuo dovuto
fase160_escrow_garanzia.py:64    garanzia            prenotazione_id, MOTIVO in testo libero dell'ospite
fase149_deposito_cauzionale.py:65 cauzione           prenotazione, importo autorizzato
fase65_split_payment.py:100      conti               prenotazione_id, alloggio_id
fase65_split_payment.py:109      quote               partecipante_id (nomi/email degli amici)
fase67_coda_intelligente.py:130  coda                ospite_id, deposito, finestra
fase67_coda_intelligente.py:142  liberazioni         alloggio_id
fase63_recensioni.py:119         recensioni          testo libero dell'ospite, voto, slug
fase147_tassa_comunale.py:80     tassa_riscossione   riferimento, comune, importo riscosso
fase158_domanda.py:86            domanda             email di chi ha chiesto una città
fase201_partner.py:100           partner             nome, email, tipo del candidato partner
fase192_admin_accounts.py:71     admin_account       email operatore, salt+hash, ruolo
fase167_credito_single_use.py:72 crediti_usati       riferimento del credito speso
fase184_marca_temporale.py:561   marche              impronta dei documenti marcati
fase166_geocoder.py:81           geocache            "via roma 1|milano|it" -> coordinate  [INDIRIZZO IN CHIARO]
fase166_geocoder.py:86           quartiere_cache     coordinate -> quartiere
```

### Fuori dal database (7)

```
main_casavip.py:79               data/app.log         IP, host_id, termini di ricerca, riferimenti; 5 file x 5MB rotanti
docker-compose.casavip.yml:38    /data/uploads/       foto annunci + FOTO-PROVA delle controversie dell'ospite
main_casavip.py:129              data/referral.json   referral host-porta-host (FILE_REFERRAL, su /data in produzione)
fase83_server.py:11003           .outreach_optout.json email di chi ha chiesto "stop"  [tenuto APPOSTA]
deploy/backup_casavip.sh:20      /data/backup/*.db.gz  copia di OGNI .db, ogni 6h, RETENTION=14 -> 84 ore di storia
deploy/backup_casavip.sh:6       (nessun VACUUM in tutto il prodotto: grep VACUUM -> 0)  pagine liberate + -wal
docker-compose.casavip.yml:89    log del container (docker logs), fuori da app.log e fuori da ogni rotazione
```

### Servizi esterni a cui i dati sono già usciti (8)

```
fase101_stripe_connect.py:19     Stripe                pagamenti, conto Connect, Identity, Customer, PaymentMethod
fase166_geocoder.py:5            Nominatim / OSM       riceve l'INDIRIZZO CIVICO COMPLETO dell'host
fase175_poi_osm.py:2             Overpass / OSM        riceve le coordinate dell'alloggio
fase83_server.py:9782            Telegram              chat_id dell'host + avvisi con riferimento e date
fase152_notifiche_prenotazione.py:86 LINE Notify       stesso contenuto, host asiatici
fase83_server.py:412             WeChat Work           stesso contenuto, host cinesi
fase37_notifiche.py:111          SMTP (provider posta) ogni email: voucher, ricevuta, reset password
fase83_server.py:568             motori di ricerca     pagina annuncio con GeoCoordinates a 6 decimali
```

---

## 🔑 LA FORMA DI FAMIGLIA — sì, ce n'è una, ed è duplice

### (a) La cancellazione ha la forma di un HOST. L'OSPITE non ha nessuna porta.

Misurato: in tutto il prodotto esiste **una sola funzione di cancellazione**,
`cancella_attivita_host` (`fase156_erasure.py:136`), e prende un `host_id`.
`grep -rn "cancella_ospite|cancella_guest|oblio"` sui `.py` di produzione → **0 funzioni** che
prendano un ospite.

Ma i dati dell'ospite stanno in **12 delle 33 tabelle**: `pendenti` (la sua email e l'intera
prenotazione in JSON), `checkin` (nome e documento di ogni persona che dorme lì), `messaggi`,
`recensioni` (testo libero), `garanzia` (il motivo della contestazione, scritto da lui),
`conti`+`quote` (gli amici con cui divide), `coda`, `domanda` (l'email di chi ha solo chiesto
una città), `crediti`, `crediti_usati`, `libro_giornale`.

E `fase185_testi_legali.py:1122` gli promette, in 8 lingue: *«At any time you may request:
access to your data, rectification, **erasure**, restriction…»*.
**Non esiste una riga di codice che possa eseguire quella promessa per un ospite.**
Oggi si farebbe a mano, database per database, senza un attrezzo e senza una verifica.

### (b) Il censimento della cancellazione è l'elenco dei METODI che esistono, non degli ARCHIVI che esistono.

`fase156` è scritta apposta per essere «resiliente» — lo dice la sua intestazione:
*«opera solo sugli store presenti che espongono i metodi (getattr) -> aggiungere un nuovo
store in futuro non richiede toccare questo file»*.

Quella frase è vera al contrario di come si legge: **un archivio nuovo non richiede di toccare
questo file perché questo file non lo cancellerà mai.** `getattr`/`hasattr` trasforma
«il metodo non c'è» in «questo passo non serve», in silenzio, e la **verifica usa lo stesso
`hasattr`**: quindi l'archivio saltato è anche l'archivio non verificato, e `ok=True` esce
lo stesso.

Il conto lo dimostra: dei **23 moduli-archivio vivi**, **5 espongono un metodo di
cancellazione** (`fase57`, `fase58`, `fase88`, `fase113`, `fase162`) e **18 no**. Dei 5, la
cancellazione ne chiama **4**: `fase162.cancellate_host` **esiste e nessuno la chiama** —
è la tabella con l'email dell'ospite.

💡 Il corollario: **queste 42 voci non si riparano scrivendo una funzione di cancellazione
nuova. Si riparano rendendo IMPOSSIBILE che un archivio non venga contato** — un censimento
che parte dall'elenco dei database, non dall'elenco dei metodi. Finché il denominatore lo
decide `hasattr`, ogni archivio aggiunto in futuro nasce già fuori dalla cancellazione, e il
rapporto continuerà a dire «tutti 0».

### (c) E anche dove cancella, i byte restano

`grep -rn "VACUUM"` su tutto il prodotto → **0 occorrenze**. Un `DELETE` in SQLite libera le
pagine ma non le restituisce al file: le righe cancellate **restano leggibili dentro il `.db`**
finché quelle pagine non vengono riscritte. E ogni 6 ore `backup_casavip.sh:20` copia il file
intero — **14 copie conservate**, cioè **84 ore** in cui l'host cancellato esiste ancora, in
`/data/backup/`, nello stesso volume dei dati vivi.

---

## ⚠️ LE MISURE CHE DA QUI NON POSSO FARE — comandi da incollare tu sul VPS

Tutto il referto sopra è **misurato sul codice**. Quanto pesi davvero, in righe, lo dice solo
il database vivo. Tre comandi, **sola lettura** (`mode=ro`), nessuna scrittura, nessun riavvio:

```
# A) quante righe di dati personali ci sono davvero, archivio per archivio
docker exec casavip_app python3 -c "import sqlite3,glob,os;T={'catalogo.db':['alloggi','alloggio_immagini'],'inventario.db':['inventario','movimenti'],'registro_host.db':['host','host_impronte'],'viral.db':['referral_codici','referral_eventi','crediti'],'messaggi.db':['messaggi'],'domanda.db':['domanda'],'partner.db':['partner'],'deposito.db':['cauzione'],'garanzia.db':['garanzia'],'pendenti.db':['pendenti'],'tassa_comunale.db':['tassa_riscossione'],'payout.db':['payout'],'admin_accounts.db':['admin_account'],'accettazioni.db':['accettazioni'],'recensioni.db':['recensioni'],'credito_usati.db':['crediti_usati'],'marche.db':['marche'],'geocache.db':['geocache','quartiere_cache'],'checkin.db':['checkin'],'finanza.db':['libro_giornale','note','debiti'],'kyc.db':['kyc'],'split.db':['conti','quote'],'coda.db':['coda','liberazioni']};d='/data';tot=0
for f,ts in T.items():
    p=os.path.join(d,f)
    if not os.path.exists(p): print(f,'ASSENTE'); continue
    c=sqlite3.connect('file:'+p+'?mode=ro',uri=True)
    for t in ts:
        try:n=c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]
        except Exception as e:n='ERR'
        print('%-22s %-18s %s'%(f,t,n));tot+= n if isinstance(n,int) else 0
    c.close()
print('TOTALE_RIGHE',tot)"

# B) quanto pesa cio' che la cancellazione non tocca: backup, log, foto
docker exec casavip_app sh -c "ls -1 /data/backup/*.db.gz 2>/dev/null | wc -l; du -sh /data/backup /data/uploads /data/app.log 2>/dev/null; ls -1 /data/uploads | wc -l; ls -1 /data/*.db | wc -l"

# C) l'indirizzo in chiaro nella cache del geocoder (quante chiavi contengono un civico)
docker exec casavip_app python3 -c "import sqlite3;c=sqlite3.connect('file:/data/geocache.db?mode=ro',uri=True);r=c.execute('SELECT chiave FROM geocache').fetchall();print('chiavi',len(r));print('con_civico',sum(1 for (k,) in r if k.count('|')>=2))"
```

Aggiungo l'unica cosa che questi comandi **non** possono dirti e che dipende da te: **quanti
dati sono già usciti verso gli 8 servizi esterni non lo sa nessun archivio nostro.** Per Stripe
c'è la sua console; per Nominatim e Overpass no: gli indirizzi che gli abbiamo mandato sono
usciti e basta.

---

## ✅ VERIFICATO E SCARTATO

1. **`tassa_regola`** (`fase147_tassa_comunale.py:78`) e **`poicache`** (`fase175_poi_osm.py:87`) **non contano
   come archivi personali**: la prima ha regole di comuni, la seconda ha una chiave arrotondata
   a ~100 m (`fase175:93`, `round(lat_micro, -3)`) che non identifica un civico. Dichiarato
   come scelta, non come svista: se si contassero, gli archivi sarebbero 50 e i toccati sempre 6.
2. **`host_impronte` e `.outreach_optout.json` sono NON toccati apposta**, ed è giusto: le
   impronte sono HMAC irreversibili contro il riciclo della promozione (`fase88:126-142`), la
   lista opt-out è la lista di soppressione — cancellarla rimetterebbe in circolo chi ha detto
   stop. Contati fra i 42, ma marcati.
3. **`fase177` dichiara «ZERO PII (solo id pseudonimi)»** (`fase177:16`) e regge: nel giornale
   ci sono `riferimento` e `soggetto` (`"ospite:<rif>"`), nessuna email, nessun nome. Resta un
   archivio personale ai fini GDPR (pseudonimo ≠ anonimo), ed è per questo che l'ho contato.
4. **Gli export non sono un archivio**: estratto contabile, dossier legale e DAC7 sono
   **generatori in streaming** (`genera_estratto_csv`, `fase83:3461`) — nessun file
   temporaneo, nessuna copia su disco. Il dato personale esce sul socket e non resta.
5. **Le foto orfane hanno una pulizia agganciata e viva** (`fase83:2228` → chiamata da
   `fase83:11077`, ogni 24h, file più vecchi di 7 giorni e non citati da nessuna fonte).
6. **La cancellazione non parte a cuor leggero**: `obblighi_pendenti` (`fase156:46`) blocca su
   prenotazioni attive, payout dovuto, escrow aperto e sospesi, e se un controllo non si può
   fare lo segna come `_incerti` invece di ignorarlo. È il pezzo meglio scritto del modulo.
7. **La forzatura lascia traccia**: `logger.critical("ERASURE FORZATA…")` a `fase156:168`, con
   la sanificazione dell'a-capo nella forma che CodeQL riconosce.
