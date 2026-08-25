# B19 — PASSAGGIO 11 · CHI PUÒ VEDERE LA ROBA DI CHI

> **Referto di misura, non lista di cose da fare.** Sola lettura: nessun file di prodotto è
> stato toccato, nessuna riparazione fatta, nessuna suite eseguita, nessun commit, nessuna
> chiamata all'API, nessun giro sul VPS, nessun server avviato, nessuna richiesta HTTP fatta
> al sito vero.
>
> Misurato il **2026-08-25**, ramo `master`, `HEAD = 3ceb4c5`, **sull'albero di lavoro**, che
> NON coincide con `HEAD`: `git status --porcelain` dà 10 file modificati non committati
> (`RIPRENDI_QUI.md`, `collaudi/batteria.py`, `deploy/contratto-host.html`, `deploy/host.html`,
> `fase163_accettazioni.py`, `fase57_vetrina.py`, `fase58_channel_manager.py`,
> `fase81_bootstrap_casavip.py`, `fase83_server.py`, `test_pipeline_ci.py`) più due file non
> tracciati (`METODO_v3.md`, `collaudi/guardia_contratto_firmato.py`). **Non sono miei: erano
> già lì.** `git diff --stat` dice che il contenuto cambiato è **+104/−30 righe su 7 file**
> (gli altri 3 hanno solo il fine-riga cambiato: `git diff` non produce alcun blocco).
> Il lavoro in corso riguarda il **gate di registrazione e la prova del contratto firmato**
> (il difetto 9·2), e sfiora fase83 in 4 punti (`pagina_login_gate`, `_host_registrazione`,
> `servi`): **nessuno dei 4 tocca una guardia d'accesso.**
>
> ⛔ **I numeri di riga di questo referto sono quelli dei file COME STANNO SUL DISCO ADESSO.**
> Chi rilegge su `HEAD` pulito trova lo stesso codice spostato fino a ~15 righe più in su.
>
> Perimetro, come lo definisce il passaggio: **per ogni dato che appartiene a qualcuno —
> un host, un ospite, un operatore — chi altro riesce a leggerlo o a scriverlo.** Ho preso
> come «qualcuno» le sei identità che il codice sa distinguere e ho misurato ogni rotta
> contro ognuna.

---

## RISULTATO IN UNA RIGA

**12 punti in cui qualcuno vede o tocca la roba di un altro** — 🔴 **4 gravi** · 🟠 **5 medi**
· 🟡 **3 minori** — su **146 rotte** (128 del router + 18 servite direttamente dall'handler)
e **6 identità**, più **18 sospetti verificati e scartati** (scritti apposta perché non si
riaprano) e **2 conferme indipendenti** di difetti già contati dai passaggi 2 e 9, **segnalate
e NON risommate**.

---

## COME L'HO MISURATO — gli attrezzi, e cosa ognuno NON vede

**Attrezzo 1 — mappa rotta → guardia (AST + testo).** Uno scanner in `scratchpad` legge
`fase83_server.py` con `ast`, ricostruisce le **129 funzioni-gestore**, le aggancia alle righe
di smistamento (`if metodo == "..." and path == "..."`) e per ognuna cerca: quale guardia
chiama, e da dove prende l'identità (`query.get(...)` / `dati.get(...)`). Risultato, che è il
denominatore di tutto il referto:

| Guardia dichiarata dal gestore | Quanti gestori |
|---|---|
| `_bunker_auth` (sessione Bunker + IP) | 21 |
| `_auth_admin` | 22 (+2 col gate di pagina) |
| `_auth_host` **+** `_host_id_da_token` | 29 |
| `_auth_host` **da solo** | 14 |
| solo cookie di pagina (`_gate_*`) | 3 |
| solo gettone firmato (`firma.decodifica`) | 2 + 1 |
| **NESSUNA** (pubbliche per progetto) | **35** |

⛔ **Cosa NON vede questo attrezzo:** le 18 rotte che non passano dal router (`/`, `/api/health*`,
`/host/azione`, `/uploads/`, `/ical/…`, le sitemap, `/stop`, `/api/bunker/marca.tsr`, …). Le ho
prese con un `grep` indipendente (`path == "` → 144 stringhe distinte contro le 128 del router)
e **lette a mano una per una**: è così che sono entrate nel perimetro `/uploads/` (voce 11) e
`/host/azione` (scartata, sano).

**Attrezzo 2 — lettura riga per riga.** I **13** punti che chiamano `_verifica_proprieta`, i
**13** che scrivono `_host_id_da_token(headers) or query.get("host_id")`, e tutte le funzioni
di guardia (`_auth_host`, `_auth_admin`, `_ruolo_operatore`, `_puo_azione`, `_bunker_auth`,
`_bunker_ok_o_field`, `_verifica_proprieta`, `_gate_valida`, `verifica_token`, `decodifica`)
aperte e lette per intero. È l'attrezzo che ha trovato tutte e 4 le voci gravi: **nessuna di
esse è «una guardia che manca», sono tutte guardie CHE CI SONO e che concedono quando non
riescono a decidere.**

**Attrezzo 3 — il confronto fra ciò che il prodotto PROMETTE e ciò che pubblica.** I dizionari
di `deploy/host.html` e i commenti del codice, letti contro il JSON che l'API restituisce
davvero. È l'attrezzo che ha trovato la voce n. 1, che nessuna lettura del solo codice
d'accesso avrebbe visto: lì **non c'è nessun controllo mancante — c'è un dato che non doveva
uscire e che esce da una porta legittima.**

---

## 🔑 LA FORMA DI FAMIGLIA — e non è quella che mi aspettavo

Cercavo rotte senza guardia. **Le rotte senza guardia ci sono (35) e sono tutte pubbliche per
progetto: catalogo, mappa, preventivo, webhook.** Il difetto sta altrove.

**Ogni guardia d'accesso di questa piattaforma è scritta nella forma «NEGA se riesco a
dimostrare che è di un altro», mai nella forma «CONCEDI solo se riesco a dimostrare che è
tuo».** Le due frasi coincidono finché la dimostrazione riesce. Quando la lettura di proprietà
non riesce — chiave assente, eccezione sul database, campo vuoto, proprietario `None` — la
prima concede e la seconda nega.

Le ho contate: **9 rami che concedono quando non sanno.**

| # | Dove | La riga | In produzione? |
|---|---|---|---|
| 1 | `_auth_host` | `if self._host_key is None: return True` (`fase83:2222`) | ❌ chiuso |
| 2 | `_auth_admin` | `if self._admin_key is None: return True` (`:2461`) | ❌ chiuso |
| 3 | `_ruolo_operatore` | chiave assente → `return "admin"` (`:2513`) | ❌ chiuso |
| 4 | `_verifica_proprieta` | nessun gettone host → `return True` (`:9950`) | ✅ **VIVO** |
| 5 | `_verifica_proprieta` | eccezione sulla lettura → `return True` (`:9955`) | ✅ **VIVO** |
| 6 | `_verifica_proprieta` | proprietario `None` → `return True` (`:9956`) | ✅ **VIVO** |
| 7 | `_puo_azione` | `except Exception: return True` (`:2542`) | ✅ **VIVO** |
| 8 | `_bunker_ok_o_field` | Bunker non configurato → `return True` (`:3101`) | ❌ chiuso |
| 9 | `_host_cancella` | `host_id` memorizzato vuoto → controllo saltato (`:6337`) | ✅ **VIVO** |

**4 su 9 sono chiusi, e sono chiusi dall'AMBIENTE, non dal codice**: `HOST_KEY` e `ADMIN_KEY`
sono presenti nel contenitore vivo e il Bunker è configurato — misurato dal **passaggio 16**,
righe 151 e 288 di `collaudi/audit/16_ambiente_vps.md`; e `main_casavip.py:206-224` si rifiuta
di partire senza quelle due chiavi. **Restano vivi 5.**

💡 Il corollario, che è la cosa da ricordare di questo passaggio: **la tenuta dell'isolamento
di questa piattaforma dipende oggi da variabili d'ambiente e dal fatto che una `SELECT` non
sollevi.** Non è una porta aperta: è una porta che si apre da sola quando qualcosa va storto,
e va storto proprio nei momenti in cui nessuno guarda.

---

# 🔴 LE QUATTRO GRAVI

## 1. 🔴 L'indirizzo di casa dell'host è pubblico, e al posto suo il prodotto pubblica il numero che lo identifica meglio

**Cosa promette il prodotto.** `deploy/host.html:366`, sotto il campo *«Indirizzo (via e
numero)»*: **«— per la posizione PRECISA sulla mappa. Resta privato: l'ospite vede la zona,
l'indirizzo esatto solo dopo la prenotazione»**. La stessa frase è scritta **due volte nel
codice come commento**: `fase57_vetrina.py:126` — `indirizzo: str = ""  # via+civico (PRIVATO:
solo per geocodifica precisa, mai pubblico)` — e `fase83_server.py:559`, sul JSON-LD:
*«geo: coordinate di ZONA (gia' pubbliche nella mappa; MAI l'indirizzo)»*. Tre affermazioni,
tre file, stessa convinzione. E `fase57:1127`, dentro il costruttore della scheda pubblica,
la ripete una quarta volta: `"lat_micro": a["lat_micro"],   # zona (già pubblica in card/mappa); MAI l'indirizzo`.

**Cosa succede davvero.** `fase83_server.py:9126-9134`, `_geocodifica_se_serve`:

```
# con INDIRIZZO -> geocodifica sempre da lì (fonte PRECISA, anche in modifica);
...
coord = gc.geocodifica(citta, indirizzo=indir, paese=...)
...
dati["lat_micro"], dati["lon_micro"] = int(coord[0]), int(coord[1])
```

Quelle coordinate sono **il geocode dell'indirizzo civico**, non della città: il codice lo
dichiara da sé («fonte PRECISA»). E se l'host non scrive l'indirizzo, il pannello gli offre
di meglio — `deploy/host.html:370`: **«apri la mappa e trascina il segnaposto sul portone»**.

Quello stesso numero esce, senza nessuna modifica, da **tre porte pubbliche**:

- `GET /api/catalogo/<slug>` → `fase57:1127-1128` (`lat_micro`, `lon_micro` interi);
- `GET /api/mappa` → `fase83:5040`, GeoJSON, `[lon/1_000_000, lat/1_000_000]`, **fino a 500 pin
  per chiamata** (`:5025`), senza autenticazione;
- la **pagina indicizzabile dell'annuncio**, dentro il JSON-LD `GeoCoordinates` di
  `fase83:568-569`, stampata con **sei decimali** (`"%s%d.%06d"`): è il campo che i motori di
  ricerca leggono, salvano e ripubblicano.

**Nessuno arrotonda, nessuno sfoca, in nessun punto.** Misurato:
`grep -rn "jitter|offusc|sfoca|arrotonda|approssim"` su `fase57_vetrina.py`,
`fase121_geo_ricerca.py`, `fase166_geocoder.py` e `fase83_server.py` → **0 occorrenze
pertinenti** (le 2 righe che escono parlano d'altro: fusi orari e orari di check-in).

**E l'altra metà della promessa non esiste nemmeno.** «l'indirizzo esatto **solo dopo** la
prenotazione» dice che dopo la prenotazione l'ospite lo riceve. Non lo riceve: la colonna
`indirizzo` è letta da **una sola funzione in tutto il prodotto** (`_geocodifica_se_serve`) più
la scheda del proprietario; **0 email, 0 voucher, 0 pagine** la stampano. Quindi la stringa
resta davvero privata — mentre il numero che la rappresenta è pubblico. **La promessa è falsa
nelle due direzioni opposte.**

⚠️ **La frase esiste in 2 dizionari su 8** (`h_indirizzo`: solo `it` e `en`, `grep -c` = 2) —
gli altri 6 ripiegano sull'inglese (`deploy/host.html:512`, difetto già contato dal passaggio
6): **quindi ogni host la legge lo stesso.**

**Chi vede la roba di chi:** chiunque, senza registrarsi, senza prenotare, con una GET.
La casa di ogni host che ha scritto un indirizzo o trascinato il segnaposto.

> 🔗 Conferma indipendente del passaggio 2 («promesse senza codice»), **ma questa promessa lì
> non c'era**: è nuova, e la conto qui.

---

## 2. 🔴 `_verifica_proprieta` è l'unico muro fra un host e gli annunci degli altri, e ha tre modi di cadere

`fase83_server.py:9945-9956`, per intero:

```
def _verifica_proprieta(self, headers, slug) -> bool:
    hid = self._host_id_da_token(headers)
    if not hid:
        return True                      # (a)
    try:
        owner = self._sys.catalogo.host_di_alloggio(slug)
    except Exception:
        return True                      # (b)
    return owner is None or owner == hid  # (c)
```

È chiamata da **13 punti** (`grep -c "_verifica_proprieta(headers"` → 13), e sono i 13 gesti
che un host fa sul suo annuncio: pubblicare/modificare (`:8963`), leggere la scheda completa
(`:9966`), **eliminarlo** (`:10144`), aprire e chiudere le date (`:9331`, `:9359`), i prezzi di
calendario (`:9634`), il calendario (`:10281`), il feed iCal (`:10341`, `:9695`), il report SEO
(`:9054`), le metriche (`:9387`), l'export contabile (`:9452`), lo stato (`:10009`).

- **(a)** vale «chi non ha un gettone host può tutto»: è il back-office con `X-Host-Key`, ed è
  voluto — ma vedi la voce 5.
- **(b)** è il ramo che pesa: **se la lettura del proprietario solleva** (database occupato, WAL
  in attesa, file bloccato), la funzione **concede**. Un errore d'infrastruttura non fa fallire
  l'operazione: le dà il permesso.
- **(c)** `owner is None` → concede. Un annuncio il cui proprietario non si trova (host
  cancellato, riga vecchia, slug orfano) è **modificabile ed eliminabile da qualunque host
  registrato** che ne conosca lo slug — e gli slug sono pubblici, stanno nella sitemap.

**Cosa NON è questo difetto.** Non è «una rotta si è dimenticata il controllo»: le ho aperte
tutte e 13, **nessuna se n'è dimenticato**, e le rotte con parametro `alloggio`/`slug` che non
lo chiamano non esistono. È la funzione stessa a essere permissiva.

**Il metro di paragone sta 4.000 righe più su, nello stesso file.** `_decidi_richiesta`
(`:5682-5697`) fa la stessa domanda e la fa nel modo giusto, con il commento che spiega perché:
ri-deriva il proprietario vero dall'alloggio, e **se non è confermabile NEGA**. Quel commento
si intitola *«OWNERSHIP FAIL-CLOSED (audit resilienza comp.2 - IDOR)»*. La conoscenza c'è, è
scritta, ed è applicata in un punto solo.

---

## 3. 🔴 Il gettone del voucher non scade mai e non si può revocare — e apre sette porte

`_voucher_valido` (`fase83:6542-6546`) è tutto qui: decodifica il gettone e controlla che
`tipo == "voucher"`. E `decodifica` (`fase59_concierge.py:122-135`) **verifica la firma HMAC e
nient'altro**: non c'è un controllo di scadenza, perché nel gettone **non c'è una scadenza**
(payload completo a `fase83:5458-5470`: `riferimento`, `alloggio_id`, `lang`, `party`,
`check_in`, `check_out`, prezzo, valuta, smart-pass, tassa, saldo in loco — **nessun `exp`**).

Quella stringa, che vive nell'email di conferma dell'ospite, autorizza da sola:

1. **leggere** tutta la conversazione con l'host (`/api/voucher/messaggi`, `:2391`);
2. **scriverci** (`/api/voucher/messaggio`, `:2376`);
3. **caricare foto** nel fascicolo della controversia (`/api/voucher/prova`, `:2401`);
4. **scrivere i dati anagrafici degli ospiti** del check-in (`/api/checkin/pre_registra`, `:6548`);
5. **creare e pagare** il conto diviso (`/api/split/crea`, `/api/split/paga`);
6. **annullare la prenotazione** (`/api/concierge/cancella`);
7. **aprire la ricevuta** con i dati fiscali (`pagina_ricevuta_html`, `:1283`) e la pagina
   recensione (`:1364`).

**Il meccanismo per farlo scadere esiste ed è usato ovunque tranne qui.** Misurato nello stesso
codice: il gettone host ha `exp` **e** ricontrolla lo stato dell'account a ogni richiesta
(`fase88_registro_host.py:417-436` → sospendere un host lo butta fuori all'istante); il gettone
operatore ha `exp` 8h (`fase83:2474-2506`); i cookie di pagina 12h/15min (`_GATE_TTL`, `:9583`);
**e persino il link «Approva/Rifiuta» che arriva all'host per messaggio controlla `exp`**
(`_azione_richiesta`, `:5658`).

**Chi vede la roba di chi:** chiunque abbia mai avuto quel link. Una casella di posta condivisa
in famiglia, un'email inoltrata all'amico con cui si divide il conto, un telefono rivenduto, un
archivio di posta esportato, un backup. Per sempre, e **senza nessun modo di chiuderla** che
non sia cambiare il segreto HMAC di tutta la piattaforma — che invaliderebbe insieme tutti i
voucher, tutti i preventivi firmati e tutti i feed iCal.

---

## 4. 🔴 `_host_cancella` ha ancora il controllo VECCHIO che il suo gemello ha già riparato

`fase83_server.py:6336-6338`:

```
host_id = self._host_id_da_token(headers) or dati.get("host_id")
if rec.get("host_id") and host_id and rec["host_id"] != host_id:
    return 403, {"errore": "non_tua"}
```

Tre condizioni in **and**: il controllo scatta solo se *tutte e tre* sono vere. **Se
`rec["host_id"]` è vuoto, il 403 non arriva mai.**

**E si riempie di vuoti da solo.** `_registra_richiesta` (`:5568-5573`) e il gemello a `:5812`
scrivono il proprietario così:

```
host, comune = "", ""
try:
    host = self._sys.catalogo.host_di_alloggio(allog) or ""
    ...
except Exception:
    pass
```

Qualunque errore in quella lettura — o un alloggio sospeso/cancellato nel frattempo — lascia
`host = ""`, e la prenotazione nasce **senza proprietario registrato**. Da quel momento è
cancellabile da chiunque abbia un gettone host valido e conosca il riferimento.

**Cosa succede se qualcuno lo fa:** l'ospite viene rimborsato al 100%, le date si liberano, la
penale del 15% viene addebitata — e `:6405` la addebita a `host_id or rec.get("host_id")`,
cioè **a chi ha premuto**, non al proprietario. Quindi non è un furto: è un **annullamento a
sorpresa della prenotazione di un altro**, con l'ospite che si ritrova senza stanza e l'host
vero che perde l'incasso senza aver fatto niente.

**Perché la chiamo grave anche se è condizionata.** Le condizioni sono due (essere un host
registrato; conoscere il riferimento a 24 caratteri, che non è indovinabile — è la coda di un
HMAC, `fase59:534`). Ma la riparazione **esiste già in questo stesso file, 700 righe sopra**,
scritta apposta per questo identico errore e con il commento che lo racconta
(`:5682-5689`: *«Prima: con host_id vuoto il check era SALTATO -> qualsiasi host
approvava/rifiutava una richiesta ALTRUI»*). **Il gemello è stato riparato e questo no.**

---

# 🟠 LE CINQUE MEDIE

## 5. 🟠 `HOST_KEY` è una stringa sola che vale «tutti gli host», e non lascia traccia di chi era

`_auth_host` (`:2217-2225`) accetta due cose: il gettone personale dell'host, **oppure** la
chiave condivisa `X-Host-Key`. Con la chiave:

- `_host_id_da_token` torna `None` → **tutti e 13** i punti scritti
  `self._host_id_da_token(headers) or query.get("host_id")` prendono l'identità **dal parametro
  della richiesta**. Basta scrivere `?host_id=<chiunque>` per leggere: payout e debiti aperti
  (`:6494`), prenotazioni (`:9833`), annunci (`:9935`), prove del contratto firmato (`:8557`),
  credito referral (`:8766`), richieste da approvare (`:5620`), link diretti (`:9477`) — e per
  **scrivere** i dati fiscali (`POST /api/host/dati_fiscali`);
- `_verifica_proprieta` torna `True` sempre (ramo (a) della voce 2) → tutti e 13 i gesti sugli
  annunci altrui.

È il back-office, ed è voluto. Le due cose che non vanno:

- **non c'è un'identità dietro la chiave.** Un solo segreto in `HOST_KEY`, nessun operatore,
  nessun ruolo. La riga di registro che resta dice l'IP e basta. Confronto interno: il lato
  admin **ha** gli operatori con ruolo, revoca istantanea e token per persona (`fase192`,
  `_ruolo_operatore` rilegge il ruolo dal database a ogni richiesta). Il lato host no;
- **è viva adesso**: `HOST_KEY` è **PRESENTE** nel contenitore in produzione (passaggio 16,
  riga 288). Quindi questo non è un ramo dormiente: è un potere che esiste oggi.

## 6. 🟠 Un host può scrivere nella chat di una prenotazione altrui — e così facendo ACCECA l'host vero

`_msg_invia` (`:8841-8857`) prende `prenotazione_id` **e** `guest_id` dal corpo della richiesta
e **non verifica che quella prenotazione sia sua**. Passa a `fase113.invia`, che controlla solo
che il mittente sia uno dei due identificativi *che gli sono stati appena passati*
(`fase113_messaggistica.py:121-122`): una tautologia, non un controllo.

L'effetto interessante non è il messaggio inserito. È `fase113.thread` (`:180-194`):

```
for m, t, ts, h, g in rows:
    if richiedente not in (h, g):
        return []                             # estraneo: niente accesso
```

**Il `return []` butta via l'INTERA conversazione**, comprese le righe già raccolte. Quindi una
sola riga estranea nel filo fa sparire dal pannello dell'host vero **tutta la sua chat con
l'ospite** — mentre l'ospite continua a vederla (l'identificativo dell'ospite è la costante
`"ospite"` per tutti, `:2353`, quindi per lui il filo resta leggibile) e vede in mezzo il
messaggio dell'estraneo.

Serve conoscere il riferimento a 24 caratteri (vedi voce 7 per un modo di ottenerlo).
⚠️ Nota accanto: `_voucher_chat_ctx` (`:2360-2363`) ripiega su `hid = "host"` se la lettura del
proprietario solleva — un errore di database in quel momento scrive nel filo una riga con
proprietario `"host"`, e **quel filo diventa illeggibile all'host vero, per sempre**. È il ramo
(b) della voce 2 in un'altra forma.

## 7. 🟠 `/api/split/stato` è pubblica e regala il riferimento interno della prenotazione

`_split_stato` (`:7780-7787`): nessuna guardia. Con un `conto_id` restituisce
`prenotazione_id`, `alloggio_id`, l'elenco dei partecipanti e chi ha pagato quanto
(`fase65_split_payment.py:247-269`).

Il `conto_id` è casuale a 16 cifre esadecimali (`secrets.token_hex(8)`, `fase65:157`) —
**non enumerabile** — ma è fatto per essere condiviso: è il numero che gli amici si passano per
pagare la loro quota. Chi lo riceve ottiene **il `riferimento` interno della prenotazione di
un altro**.

Questa è **l'unica rotta pubblica del prodotto che consegna un `riferimento`**, e il
`riferimento` è esattamente la chiave che serve alla voce 6 e alla voce 4. La catena la
segnalo, **non l'ho provata**: non ho fatto nessuna chiamata.

> ✅ Verificato e scartato accanto: `/api/split/crea` e `/api/split/paga` **sono chiusi**
> (voucher firmato obbligatorio, `:7723` e `:7757-7768`), e il commento del 2026-08-20 racconta
> che erano pubblici. La lettura è rimasta indietro rispetto alle due scritture.

## 8. 🟠 Il ruolo `supporto` legge tutto, e la lettura di una conversazione privata non lascia traccia

`fase192_admin_accounts.py:24-26` riserva **6 azioni** al ruolo `admin`:
`rimborso`, `storno_penale`, `cancella_attivita`, `alloggio_stato`, `controversia_risolvi`,
`blocco_globale`. Misurato: `_puo_azione` è chiamato in **6 punti** (`:2988`, `:3021`, `:4348`,
`:4376`, `:4734`, `:4824` — 6 chiamate per **5 azioni distinte**, `rimborso` due volte);
**`blocco_globale` non è
agganciato a nessuna rotta.** Non è un buco — quella rotta è dietro il Bunker
(`_bunker_blocco_globale_imposta`) — ma **l'elenco dichiarato e l'elenco applicato non
coincidono**, e chi legge `AZIONI_SOLO_ADMIN` crede di leggere l'elenco applicato.

**Quello che `supporto` può fare senza nessun ulteriore controllo è tutto ciò che si legge:**
`/api/admin/search` (host per email e nome, prenotazioni per email dell'ospite),
`/api/admin/prenotazioni`, `/api/admin/verifiche/dettaglio` (IBAN e codice fiscale mascherati,
prove del contratto), `/api/admin/audit`, e **`/api/admin/messaggi`: la conversazione intera
fra un ospite e un host, comprese le foto delle controversie.**

E qui c'è l'asimmetria che conta: **`_admin_messaggi` (`:2450-2458`) non scrive nessuna riga di
registro.** Scaricare il fascicolo di un host lascia una riga
(`ADMIN_ACTION | ... Download fascicolo`, `:2910`); aprire il dettaglio di un host lascia una
riga (`:2870`); fare una ricerca lascia una riga (`:2669`). **Leggere la corrispondenza privata
di un cliente non ne lascia nessuna.**

Accanto: `_puo_azione` (`:2536-2543`) fa `except Exception: return True` — se il modulo dei
ruoli non si importa, ogni ruolo può ogni cosa (ramo 7 della tabella di famiglia).

## 9. 🟠 Il gettone iCal non scade, non si revoca, non si ruota

`_ical_link` (`:9686-9703`) firma `{"k": "ical", "slug": slug}` — **niente scadenza, niente
host, niente contatore di versione** — e la docstring lo dice: *«Firmato (contiene lo slug),
senza scadenza»*. `_ical_export` (`:9705-9711`) verifica firma e chiave e serve il feed a
chiunque, senza autenticazione (è servito da `/ical/<token>.ics`, `:10881`).

Il feed dice **quali date sono occupate** in quell'annuncio, aggiornato in tempo reale. Chi ha
avuto quell'URL una volta lo legge per sempre: un channel manager scollegato, un socio uscito,
un'agenzia licenziata, un vecchio annuncio su un portale terzo che nessuno ha tolto. **Non
esiste una rotta che invalidi un gettone iCal** (cercata: 0).

---

# 🟡 LE TRE MINORI

## 10. 🟡 `Access-Control-Allow-Origin: *` su ogni risposta — e cosa vuol dire davvero

`Handler._cors` (`:10563-10567`) mette `*` su **tutte** le risposte, comprese `/uploads/` e
tutte le API. Lo scrivo come minore e con la conseguenza esatta, perché questo è un allarme
che si racconta spesso più grosso di com'è:

- **non c'è `Access-Control-Allow-Credentials`**, quindi il browser non manda i cookie di
  pagina a un sito terzo: le pagine riservate non si leggono da fuori;
- l'autenticazione delle API è un'**intestazione** (`X-Host-Token`, `X-Admin-Key`…), non un
  cookie: un sito ostile non ce l'ha e non può fabbricarla;
- **quello che un sito qualunque PUÒ leggere è tutto ciò che non chiede credenziali**: il
  catalogo, la mappa con le coordinate della voce 1, `/api/split/stato` della voce 7, e ogni
  foto caricata.

## 11. 🟡 Le foto stanno su un URL pubblico che vale un anno, comprese le prove delle controversie

`_serve_upload` (`:10599-10621`) serve qualunque file di `UPLOAD_DIR` **senza autenticazione**,
con `Cache-Control: public, max-age=31536000`. Nessuna regola di nginx ci mette qualcosa davanti
(letto `deploy/nginx.casavip.ssl.conf`: c'è l'eccezione a 8 MB per `/api/host/upload_foto`
(`:81`), niente auth su `/uploads/`).

Per le foto degli annunci è giusto. Ma nello stesso posto finisce **la foto che l'ospite carica
come prova in una controversia** (`_voucher_prova`, `:2427` → `_salva_foto_raw` → stessa
cartella): la fotografia di una stanza sporca, o di un danno, o di quello che c'era dentro casa.
Diventa un URL permanente, non autenticato, **che i proxy e le CDN sono autorizzati a
conservare per un anno**, e resta valido anche dopo che la controversia è chiusa.

Il nome è casuale (`secrets.token_hex(16)`, 32 cifre esadecimali): **non è enumerabile**, ed è
il motivo per cui è minore e non media. È un permesso-che-è-un-indirizzo, e come tutti quelli
di questo referto non ha una scadenza.

> ✅ **Verificato e scartato la parte peggiore**: la pulizia degli orfani **è agganciata** e gira
> (`_pulizia_uploads_se_ora` chiamata da `:11077`), quindi dopo una cancellazione GDPR — che
> cancella le righe di chat (`fase156_erasure.py:210-211`) — il file resta orfano e viene
> rimosso dopo 7 giorni. Non «per sempre»: per una settimana.

## 12. 🟡 I dati della prenotazione escono verso Telegram, LINE e WeChat, e nessun testo lo dice

`_tg_reply`, `imposta_telegram_chat` (`:9812`), il token LINE (`:400-427`) e il webhook WeChat
sono i canali con cui l'host riceve l'avviso di prenotazione **coi tasti Approva/Rifiuta**:
quindi il riferimento e le date di soggiorno di un ospite transitano su server di terzi.
È una scelta di prodotto legittima. Il fatto misurato è che **non compare in nessuno dei testi
che l'ospite legge**: `grep -ci "telegram|wechat|line notify"` su `fase185_testi_legali.py`
→ **0**, e su `deploy/privacy.html` → **0**.

> 🔗 Confine col passaggio 2 (le promesse) e con l'informativa privacy: segnalato, non contato
> due volte.

---

## ✅ DICIOTTO SOSPETTI VERIFICATI E SCARTATI — scritti perché non si riaprano

1. **La scheda pubblica NON perde dati pur facendo `SELECT *`.** `dettaglio` (`fase57:985`)
   legge tutte le colonne, ma `_dettaglio_json` (`:1118-1148`) ne stampa **20 nominate una per
   una**: `indirizzo` e `host_id` non ci sono. È una lista bianca, e regge.
2. **I tre rami «aperto in sviluppo» sono chiusi in produzione**: `main_casavip.py:206-224` si
   rifiuta di partire senza `HOST_KEY`/`ADMIN_KEY`, e il passaggio 16 le ha misurate presenti.
3. **`_bunker_ok_o_field` non concede**: il Bunker è configurato (passaggio 16, §5).
4. **Nessuna delle 13 rotte con `slug`/`alloggio` si è dimenticata `_verifica_proprieta`.**
   Aperte una per una.
5. **Un host connesso non può nominare un altro `host_id`**: tutti e 13 i punti scrivono
   `_host_id_da_token(headers) or query.get(...)` — **il gettone viene prima**, sempre.
6. **Gli export pesanti non sono dietro l'admin, sono dietro il Bunker**: estratto contabile,
   dossier legale, report DAC7, fascicolo host, token `.tsr` della marca temporale
   (`puo_esportare`/`puo_dac7`/`scarica_marca`, `:3452`, `:3457`, `:4104`).
7. **Il gettone host è fatto bene**: `exp` controllato **e** stato dell'account riletto dal
   database a ogni richiesta (`fase88:417-436`) → sospendere un host lo butta fuori subito.
8. **Il link «un tocco» Approva/Rifiuta controlla la scadenza** (`:5658`).
9. **Il webhook Telegram controlla il segreto** (`:9793-9798`), presente in produzione.
10. **`/api/mcp` è senza autenticazione ma non espone roba di nessuno**: 6 strumenti
    (`fase60_mcp_server.py:53-120`) = cerca, preventivo, prenota, dettaglio, lingue, confronto
    OTA. Tutta superficie pubblica.
11. **`_decidi_richiesta` è fail-closed** e ri-deriva il proprietario (`:5690-5697`): è il
    modello giusto, ed è la prova che la voce 4 è una svista e non una scelta.
12. **L'export CSV dell'host non contiene dati dell'ospite**: 9 colonne
    (`genera_csv_prenotazioni`, `:900-901`), nessuna personale. L'host **non vede mai l'email
    dell'ospite** dal pannello.
13. **La chat nega agli estranei** (`fase113:191-192`) — è il lato buono della voce 6.
14. **Il cookie di pagina firma solo il LIVELLO, mai l'identità** — e va bene: le pagine che
    serve sono gusci vuoti, i dati arrivano dall'API con l'intestazione (`_servi_gated`,
    `:10660-10679`).
15. **Nessuna traversata di percorso**: `_serve_upload` usa `percorso_statico_sicuro`
    (basename) e `_foto_elimina` usa `commonpath` contro la cartella assoluta (`:9299-9302`);
    nginx respinge `../`, `%2e%2e`, `%00` con 403 (`nginx.casavip.ssl.conf:74`).
16. **La sessione Bunker è legata all'IP** e ogni negazione è registrata come CRITICA
    (`:3073-3088`).
17. **La chiave admin ha il buttafuori per IP** con confronto a tempo costante e azzeramento
    sul successo (`_auth_con_rate`, `:2545-2572`).
18. **L'operatore admin ha revoca istantanea**: il ruolo è riletto dal database a ogni
    richiesta, non preso dal token (`:2530-2533`).

---

## ⚠️ QUELLO CHE QUESTO PASSAGGIO NON HA MISURATO

- **Niente è stato provato in esecuzione.** Zero richieste HTTP, zero server avviati, zero
  chiamate all'API, nessun giro sul VPS. Tutto è letto dal codice. Le due catene che ho
  descritto (voce 7 → voce 6, e voce 4) **sono ragionamenti su codice letto, non exploit
  dimostrati**: chi le riparerà dovrebbe prima riprodurle su un banco.
- **Il database vero non è stato guardato.** Quante prenotazioni abbiano `host_id=""` (voce 4)
  e quanti annunci abbiano `owner=None` (voce 2) **non lo so**: sono due `SELECT COUNT(*)` sul
  VPS, e sono la differenza fra «latente» e «aperto». **Sono le due misure che chiederei per
  prime.**
- **La precisione vera del geocode** (voce 1) dipende da Nominatim: il *formato* è a
  microgradi (≈ 0,11 m), la *precisione* è quella del punto che il servizio restituisce per un
  civico, cioè l'edificio. Non l'ho verificata su un indirizzo vero.
- **Il permesso dei file su disco** (chi legge `data/` e le copie di sicurezza sul server) è
  fuori da questa lettura: è una domanda sul VPS, non sul codice.
- **`app.py`, `assistente_gestionale.py` e i 59 moduli mai raggiunti** non sono nel perimetro:
  se un giorno vengono collegati, questo referto non parla di loro.

---

## 📎 DOVE STANNO GLI ATTREZZI

Gli scanner sono nella cartella temporanea di sessione (`scratchpad/scan_rotte.py`,
`scratchpad/dump.py`), **non nel repository**: sono attrezzi di misura di questo passaggio, e
questo passaggio non aggiunge file al prodotto. La tabella completa
«rotta → gestore → guardia → parametro d'identità» (129 righe) si riproduce lanciando
`scan_rotte.py` dalla radice del progetto.
