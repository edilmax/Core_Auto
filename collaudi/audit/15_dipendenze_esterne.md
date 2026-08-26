# B19 — PASSAGGIO 15 · LE DIPENDENZE ESTERNE QUANDO CADONO

> **Referto di misura, non lista di cose da fare.** Sola lettura: nessun file di prodotto
> toccato (i 3 file modificati nell'albero da altre sessioni sono stati solo LETTI), nessuna
> riparazione, nessuna suite, nessun commit, nessun giro sul VPS, nessuna chiamata di rete,
> nessun heredoc.
>
> Misurato il **2026-08-26**, ramo `master`, `HEAD = 663eab3`.
> `git status --porcelain`: `fase57_vetrina.py`, `fase58_channel_manager.py`,
> `fase81_bootstrap_casavip.py` (di altri giri, non miei).
>
> Perimetro: **ogni punto in cui il prodotto esce dalla propria macchina** — HTTP verso terzi e
> SMTP — e, per ognuno, cosa succede al cliente, ai soldi e alla traccia quando quel servizio
> non risponde.

---

## RISULTATO IN UNA RIGA

**11 dipendenze esterne vive.** Su ognuna il guasto è *isolato* (nessuna fa cadere il server):
**4 hanno una rete di sicurezza completa** (fail-safe + traccia durevole + sorvegliante),
**4 degradano in modo onesto e dichiarato**, **3 perdono il messaggio in silenzio**.
E il difetto di forma che le lega: **il sorvegliante dei guasti isolati legge solo gli `ERROR`,
e tutte e 3 le perdite silenziose si registrano come `WARNING`.**

---

## LA TABELLA — 11 dipendenze, cosa succede quando cade

| # | Servizio | Dove esce | Attesa | Ritenta? | Cosa succede al cliente | Traccia durevole | Sorvegliato? |
|---|---|---|---|---|---|---|---|
| 1 | **Stripe Checkout** (link di pagamento) | `fase85_pagamenti_stripe.py:350` | 15 s | no | **la prenotazione viene RIFIUTATA con 503 e la stanza rilasciata** | — (non serve: niente è successo) | ✅ riconciliazione |
| 2 | **Stripe webhook** (in entrata) | `fase83_server.py:8044` | — | **sì, Stripe ritenta per giorni** | nulla: il CAS sana al retry | pendenti | ✅ riconciliazione |
| 3 | **Stripe Connect** (bonifico host) | `fase101_stripe_connect.py:241` | 15 s | no | l'host non è pagato adesso | ✅ giornale `payout_manuale` | ✅ payout fermo 7 gg |
| 4 | **Stripe Refund** | `fase85_pagamenti_stripe.py:117` | 15 s | no | il rimborso resta da fare | ✅ la lista si ricalcola e richiede a Stripe | ✅ riconciliazione |
| 5 | **Stripe Identity** (KYC) | `fase143_kyc_host.py` | 30 s | no | verifica non parte, riprovabile | kyc | — |
| 6 | **SMTP** (tutte le email) | `fase86_email.py:98/103` | 10 s | **sì: 2 tentativi, pausa 1,5 s** | **non riceve l'email. Punto.** | ❌ **nessuna** | ❌ solo WARNING |
| 7 | **Telegram** | `fase83_server.py:9782` | — | no | l'host non riceve l'avviso | ❌ nessuna | ❌ |
| 8 | **LINE Notify** | `fase152_notifiche_prenotazione.py:86` | 10 s | no | idem | ❌ nessuna | ❌ |
| 9 | **WeChat Work** | `fase83_server.py:412` (validazione) | — | no | idem | ❌ nessuna | ❌ |
| 10 | **Nominatim / OSM** (geocoder) | `fase166_geocoder.py` | 12 s / 30 s | no | l'annuncio non compare sulla mappa | cache (anche dei "non trovato") | — |
| 11 | **Overpass / OSM** (POI) | `fase175_poi_osm.py` | 20 s / 30 s | no | landing senza punti d'interesse | cache | — |
| + | **TSA marca temporale** | `fase184_marca_temporale.py` | 30 s | no | nessuno: è interno | marche | ✅ `_marca_temporale_ferma` |
| + | **Cambio valuta (OXR)** | `fase99_multicurrency.py:264` | `TIMEOUT_SEC` | no | prezzi convertiti col cambio vecchio | cache | ✅ `_cambio_valuta_fermo` |

Misurato: **27 moduli** contengono `urlopen` o `smtplib.SMTP(`; di questi **9 sono raggiungibili
dalla produzione** (presenti in `fase81_bootstrap_casavip.py`), più `fase99` e `fase169`
richiamati dal server. Gli altri 16 sono i canali social e i motori dormienti (X, TikTok,
Mastodon, Nostr, gateway Asia, outbox), fuori dal perimetro perché non raggiunti.

---

# ✅ LE QUATTRO CHE SONO FATTE BENE

## 1. Stripe giù non regala soggiorni — ed è una riparazione, non un caso

`fase59_concierge.py:566-575`:

```
if self._link is not None and not payment_url:
    self._inv.rilascia(alloggio, ci, co, idem_key=idem)   # stanza subito vendibile
    logger.error("PRENOTAZIONE RIFIUTATA: gateway di pagamento irraggiungibile ...")
    return RispostaConcierge(503, {"errore": "pagamento_non_disponibile", "riprova": True})
```

Il commento sopra racconta il difetto che c'era: *«Camera fuori mercato + ospite con voucher
valido + incasso zero + zero traccia»*. Da notare la scelta del livello: **`logger.error`, non
warning** — quindi questo caso **lo vede** il sorvegliante dei guasti isolati.

## 2. Il bonifico che non parte lascia una riga scritta

`fase83_server.py:6285-6290`: se `connect.trasferisci` torna vuoto, non si perde nulla —
riga `payout_manuale` nel giornale immutabile, `logger.error`, e il payout resta `maturato`,
che è lo stato che il Guardiano sorveglia (7 giorni, `fase186_guardiano.py:141`).
⚠️ Il limite di questa rete l'ha già misurato il passaggio 13: fra il transfer riuscito e la
scrittura della prova ci sono tre scritture separate.

## 3. Il webhook perso si sana da solo

Stripe ritenta per giorni; il ramo `stato == "pagato"` (`fase83_server.py:8054-8064`)
ri-asserisce i passi idempotenti. È il pattern #32, scritto e funzionante.

## 4. Due servizi esterni hanno un cane da guardia dedicato

`_cambio_valuta_fermo` (`fase186_guardiano.py:205`) e `_marca_temporale_ferma` (`:226`).
Sono gli unici due servizi esterni con un controllo **a nome proprio** dentro il Guardiano.

---

# ⚪ LE QUATTRO CHE DEGRADANO IN MODO ONESTO

**Nominatim** e **Overpass** (10, 11): cache-first, **e cache-ano anche il "non trovato"**
(`fase166_geocoder.py:106-111`) per non martellare il servizio. Guasto → l'annuncio resta
senza coordinate: non compare sulla mappa, ma **si vende lo stesso**. Nessun soldo coinvolto.
⚠️ Nota che incrocia il passaggio 11: quando invece **rispondono**, quelle coordinate sono il
civico dell'host.

**Cambio valuta** e **marca temporale**: continuano col dato vecchio e hanno il loro allarme.

---

# ❌ LE TRE CHE PERDONO IL MESSAGGIO IN SILENZIO

## 5. L'email: 2 tentativi, poi il messaggio non esiste più

`fase86_email.py:74-85` fa **2 tentativi** con pausa 1,5 s (`:46`, `tentativi=2`,
`pausa_s=1.5`) — meglio di niente. Ma dopo il secondo:

```
return False
```

E quel `False` **non lo guarda nessuno**. Ogni invio del prodotto passa da
`_email_bg` (`fase83_server.py:6086-6095`) o da un `threading.Thread(...).start()` diretto
(`fase83_server.py:5537-5541`, l'email del voucher): **thread demone, valore di ritorno
scartato, nessuna coda, nessun secondo giro più tardi.**

Cosa si perde davvero, in ordine di gravità:
- **il voucher e il PIN di check-in** dell'ospite (`fase83_server.py:5537`);
- **la conferma di pagamento** (`_email_pagamento_confermato`);
- **il link di reimpostazione password** dell'host;
- **l'email di recupero hold** («le date sono libere, riprova»);
- **la ricevuta**;
- ⛔ **l'allarme del Guardiano stesso**: il referto giornaliero esce per email. Se l'SMTP è
  giù, l'allarme che dice «qualcosa non va» è la prima cosa che non arriva.

⛔ **E c'è un modulo che risolverebbe esattamente questo, ed è morto:**
`fase16_outbox.py` (pattern outbox: scrivi il messaggio in archivio, spediscilo dopo,
ritenta). `grep` su `fase81_bootstrap_casavip.py` e `main_casavip.py` → **0 occorrenze**.
È costruito e non collegato: regola #23, quarta comparsa in cinque passaggi.

## 6-7-8. Telegram, LINE, WeChat: i falliti si contano e poi si buttano

`fase152_notifiche_prenotazione.py:161-175`:

```
def avvisa(self, contatti, oggetto, testo) -> Dict[str, int]:
    inviati = falliti = 0
    ...
    return {"inviati": inviati, "falliti": falliti}
```

Il numero dei falliti **viene calcolato con cura e restituito**. E il chiamante,
`_avvisa_host_richiesta` (`fase83_server.py:5610`), lo scarta:

```
notif.avvisa(contatti, ogg, testo)      # nessun assegnamento, nessun controllo
```

**Perché conta.** È il canale con cui l'host scopre di avere **una richiesta di prenotazione
da approvare entro 24 ore** (`fase83_server.py:5607`: *«Hai 24 ore»*). Se tutti i canali
falliscono — e l'email è uno dei canali, quindi lo stesso SMTP di sopra — allora:

1. l'host non sa niente;
2. nessuno riprova;
3. **la stanza resta bloccata** fino alla scadenza (`scadenza_ts = ora + 86400`,
   `fase83_server.py:5580`);
4. dopo 24 h lo sweeper la scade, libera le date e manda all'ospite l'email «riprova» — **che
   parte dallo stesso SMTP**;
5. nel registro resta un `warning`.

**Nessuno dei cinque passi produce una riga che qualcuno legga.**

---

# 🔑 LA FORMA DI FAMIGLIA

**Il prodotto ha un sorvegliante dei guasti isolati, ed è fatto bene — ma guarda solo metà del
registro, e le tre perdite silenziose stanno esattamente nell'altra metà.**

`_guasti_isolati` (`fase186_guardiano.py:266-311`) è nato per la domanda giusta, e la sua
docstring la formula meglio di come la formulerei io:

> *«Nel solo `fase83_server.py` ci sono ~165 punti in cui un errore viene ingoiato di proposito
> … e finisce SOLO in `app.log`. In tutto il progetto quel file ha UN lettore: un pannello
> manuale dietro doppia chiave, ultime 300 righe di un rotante da 5MB.»*

E poi, alla riga 275, la regola che decide cosa vede:

> *«Guarda SOLO gli ERROR, mai i warning: i warning sono ~131 e riguardano anche cose innocue
> (una miniatura non salvata)»*

Misurato oggi in `fase83_server.py`: **130 `logger.warning`, 99 `logger.error`, 7
`logger.critical`**. La scelta è ragionevole — un allarme che grida per una miniatura è un
allarme che si impara a ignorare. **Ma il livello è diventato il filtro, e nessuno ha
riguardato chi stava da che parte.** Il risultato, misurato caso per caso:

| Evento | Livello | Lo vede il Guardiano? |
|---|---|---|
| Stripe giù → prenotazione rifiutata | `logger.error` (`fase59:572`) | ✅ sì |
| bonifico Connect fallito | `logger.error` (`fase83:6285`) | ✅ sì |
| **email non partita dopo 2 tentativi** | `logger.warning` (`fase86:78`) | ❌ **no** |
| **avviso all'host fallito su tutti i canali** | `logger.warning` (`fase152:174`) | ❌ **no** |
| **`_email_bg` non parte affatto** | `logger.warning` (`fase83:6095`) | ❌ **no** |

💡 **Il corollario:** i tre guasti che *non lasciano nessuna traccia durevole nei dati* sono
anche i tre che *non entrano nel registro sorvegliato*. Non è una coincidenza: sono le stesse
tre cose considerate «non gravi» quando si è scelto il livello del log. **La gravità di un
messaggio perso non sta nel messaggio — sta in cosa il destinatario non farà.** Un avviso di
prenotazione perso costa una prenotazione; un voucher perso costa un ospite davanti a una
porta chiusa.

E lo si può dire con un numero: **su 11 dipendenze, 4 hanno una traccia durevole nei dati, 7
no; di queste 7, le 4 che non muovono soldi degradano visibilmente (mappa, POI, cambio,
marca), e le 3 che parlano con una PERSONA sono le uniche che spariscono senza che nessuno lo
sappia.**

---

## ⚠️ LE MISURE CHE DA QUI NON POSSO FARE — comandi da incollare sul VPS

Se le tre perdite silenziose siano già successe lo dice solo `app.log`. Sola lettura:

```
# A) quante email/avvisi sono falliti davvero, e quando
docker exec casavip_app sh -c "grep -c 'Email: invio fallito' /data/app.log; grep -c 'canale notifica host fallito' /data/app.log; grep -c 'email background fallita' /data/app.log; grep -c 'PRENOTAZIONE RIFIUTATA: gateway' /data/app.log"

# B) il rapporto ERROR/WARNING vero nel registro vivo (quanto vede il Guardiano)
docker exec casavip_app sh -c "grep -c ' ERROR ' /data/app.log; grep -c ' WARNING ' /data/app.log; ls -la /data/app.log*"

# C) le ultime 20 righe di guasto isolato, per capire QUALI servizi cadono
docker exec casavip_app sh -c "grep -E 'ISOLAT|fallit' /data/app.log | tail -20"

# D) il verdetto che il Guardiano dà adesso (puro, nessun invio, nessuna scrittura)
docker exec casavip_app python3 -c "import json,main_casavip" 2>/dev/null; docker exec casavip_app curl -s localhost:8080/api/health
```

⛔ Nota su (A): se il conteggio è **0** non vuol dire «non è mai successo». `app.log` è un
rotante da 5 file × 5 MB: sopra quella soglia la storia più vecchia **non esiste più**, e
nessuna delle tre perdite silenziose ha lasciato una riga altrove.

---

## ✅ VERIFICATO E SCARTATO

1. **Nessuna dipendenza esterna può far cadere il server**: tutte e 11 sono dentro un
   `try/except` che ritorna un valore, e i timeout sono impostati ovunque (10-30 s). Zero
   chiamate senza timeout — controllato modulo per modulo.
2. **Nessuna chiamata di rete sta dentro una transazione di database**: le scritture usano
   `BEGIN IMMEDIATE` e chiudono prima; il transfer Stripe è fuori (è la crepa del passaggio 13,
   ma non è un lock tenuto sulla rete).
3. **L'email ha una difesa contro l'header-injection** al punto giusto — un solo passaggio
   obbligato per tutti i provider (`fase86_email.py:65-73`).
4. **Il geocoder cache-a anche i fallimenti**, quindi un Nominatim giù non diventa un
   martellamento (`fase166:106-111`).
5. **`fase37_notifiche.py` non è in produzione** (0 occorrenze in `fase81`): il provider vivo
   è `fase86_email.py`. La sua frase *«il router ritenta/ripiega»* (`fase37:121`) descrive un
   comportamento che nel modulo vivo esiste davvero (2 tentativi) — ma nel modulo dove è
   scritta non c'è.
6. **Il kill-switch globale non è un guasto esterno**: blocca i bonifici lasciando il payout
   `maturato` (`fase83:6181`), stato sorvegliato. Corretto.
