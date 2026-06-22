# BookinVIP — Guida d'uso spiegata facile facile

Questa guida ti spiega **come usare ogni cosa** e **come accendere tutte le funzioni**,
passo dopo passo, senza dare niente per scontato. Tienila aperta mentre provi.

---

## ⭐ 3 COSE DA SAPERE PRIMA (importantissime)

### 1) I prezzi si scrivono in CENTESIMI (non in euro!)
Il sistema lavora in centesimi per non sbagliare mai un arrotondamento.
- Vuoi **€95**? scrivi **9500**
- Vuoi **€120**? scrivi **12000**
- Vuoi **€9,50**? scrivi **950**

👉 Regola del bambino: **"aggiungi due zeri".** €95 → 95 + "00" → **9500**.

### 2) Ci sono 3 "parole d'ordine" (chiavi)
Stanno nel file `.env.casavip` sul server. Servono a far entrare solo te.
- **CASAVIP_SEGRETO** = il cuore segreto del sistema (lo generi una volta, non lo tocchi più).
- **HOST_KEY** = la password del **pannello host** (per pubblicare alloggi).
- **ADMIN_KEY** = la password del **pannello admin** (per i rimborsi).

### 3) Le 3 pagine
- `https://bookinvip.com/` → la **vetrina** (quello che vede il cliente)
- `https://bookinvip.com/host.html` → il **pannello host** (tu che gestisci le case)
- `https://bookinvip.com/admin.html` → il **pannello admin** (rimborsi)

---

# PARTE 1 — USARE IL PANNELLO HOST (gestire le case)

Apri `https://bookinvip.com/host.html`.
In alto c'è il campo **"chiave host"**: scrivici la tua **HOST_KEY**. (Va messa una volta;
serve per ogni operazione qui dentro.) Puoi anche scegliere la **lingua** in alto.

## 1.1 Pubblicare una casa  📋
Trova il riquadro **"Pubblica alloggio"** e riempi:
- **Host ID**: un nome per te come proprietario (es. `host1`). Usa sempre lo stesso per
  ritrovare le tue case in "I miei alloggi".
- **Slug**: il nome-codice della casa nell'indirizzo web (es. `casa-roma`). Solo lettere
  minuscole e trattini, senza spazi.
- **Titolo**: il nome bello (es. `Casa a Roma con terrazza`).
- **Citta**: es. `Roma`.
- **Prezzo/notte (cent)**: in **centesimi** (€95 → **9500**).
- **Capacita**: quante persone dormono (es. `4`).
- **Servizi (csv)**: separati da virgola (es. `wifi,piscina,parcheggio`).
- **Foto (URL, una per riga)**: incolla i link delle foto, una per riga.
  (Le foto devono già stare online da qualche parte; qui metti solo l'indirizzo.)

Premi **Pubblica**. Comparirà un messaggio verde = fatto. La casa è online.

## 1.2 Aprire le date disponibili  📅
Una casa pubblicata non si può ancora prenotare finché non dici **quando è libera**.
Due modi:

**A) Tanti giorni in un colpo (consigliato)** → riquadro **"Apri un periodo"**:
- **Slug**: la casa (es. `casa-roma`)
- **Unita**: quante stanze/unità uguali hai (di solito `1`)
- **Da** / **A**: il periodo (es. dal 1 settembre al 1 ottobre)
- **Prezzo/notte (cent)**: in centesimi
Premi **Apri periodo**. Tutte quelle notti diventano prenotabili.

**B) Un solo giorno** → riquadro **"Disponibilita"**: stessi campi ma per un giorno solo.
Serve per ritoccare un giorno specifico (es. cambiare prezzo o chiuderlo).

## 1.3 Importare il calendario da Airbnb/Booking  🔁
Se la casa è già su Airbnb/Booking, prendi il loro **link iCal** (loro lo chiamano
"esporta calendario"), apri quel link, copia tutto il testo (comincia con
`BEGIN:VCALENDAR`) e incollalo nel riquadro **"Importa calendario iCal"**, poi premi
**Importa e sincronizza**. Le date già occupate altrove si bloccano qui → **niente doppie
prenotazioni**.

## 1.4 Vedere il calendario a colori  🗓️
Riquadro **"Calendario disponibilita"**: metti lo Slug e le date, premi **Vedi**.
- 🟢 verde = libero · 🔴 rosso = prenotato · ⬜ grigio = chiuso · ▫️ bianco = non aperto.
Passa il mouse su un giorno per vedere il prezzo.

## 1.5 Vedere quanto guadagni (Dashboard)  📊
Riquadro **"Dashboard"**: (opzionale) metti lo Slug, premi **Carica metriche**. Vedi:
- **Revenue** (incassato), **Occupazione %**, **Prenotazioni**, **Rating** (stelle).
Il bottone **"Esporta CSV prenotazioni"** scarica un file per la contabilità (lo apri con Excel).

## 1.6 I miei alloggi (sospendi / ripubblica)  🏠
Riquadro **"I miei alloggi"**: metti il tuo **Host ID** (lo stesso di quando pubblichi),
premi **Carica**. Vedi tutte le tue case. Per ognuna puoi:
- **Sospendi** → sparisce dalla vetrina (ma resta tua).
- **Pubblica** → la rimetti online.

## 1.7 Trasparenza vs Booking  💰
Riquadro **"Quanto guadagni in più"**: metti un prezzo e scegli l'OTA → ti dice quanto
incasseresti con loro vs con BookinVIP. (Serve per convincere altri host.)

---

# PARTE 2 — COSA VEDE E FA IL CLIENTE (la vetrina)

Apri `https://bookinvip.com/`.
1. In alto sceglie la **lingua**.
2. Cerca per **città**, **date** (check-in / check-out), **ospiti**, e può filtrare per
   **prezzo massimo** e **servizi**.
3. Vede le **schede con foto, prezzo, stelle**. Clicca una scheda → si apre il **dettaglio**
   (galleria foto, descrizione, recensioni, e il **preventivo** col totale).
4. Mette la sua **email** e preme **Prenota**.
5. Compare la conferma con il link **📄 Voucher**.

---

# PARTE 3 — IL VOUCHER E IL CHECK-IN

Dopo aver prenotato, il cliente apre il link **Voucher** (`/voucher/...`):
- È la **conferma** (riferimento, date, totale).
- Contiene il **codice di self check-in**: lo mostra alla serratura smart il giorno
  dell'arrivo (vale dalle 15:00 del check-in alle 11:00 del check-out). **Entra da solo,
  niente reception.**

Se hai acceso l'email (Parte 5), il cliente riceve tutto questo anche **via email**.

---

# PARTE 4 — IL PANNELLO ADMIN (rimborsi)

Apri `https://bookinvip.com/admin.html`. Metti la tua **ADMIN_KEY**, premi **Carica
prenotazioni**. Vedi tutte le prenotazioni.
- Premi **Rimborsa** su una prenotazione → le date si **liberano** (la prenotazione viene
  annullata). Se Stripe è acceso, il rimborso dei soldi parte di conseguenza.

---

# PARTE 5 — ACCENDERE LE FUNZIONI (Stripe, Email, ecc.)

Tutte queste si accendono **scrivendo le chiavi nel file `.env.casavip`** sul server e
riavviando. **Non si tocca il codice.** Dopo ogni modifica al file, dai questo comando:
```
docker compose -f docker-compose.casavip.yml up -d
```

## 5.1 Accendere i PAGAMENTI (Stripe)
Nel `.env.casavip` scrivi (le prendi dal sito di Stripe):
```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_SUCCESS_URL=https://bookinvip.com/grazie
STRIPE_CANCEL_URL=https://bookinvip.com/annullato
```
**Cosa cambia:** ora ogni prenotazione crea un **link di pagamento vero**; quando il
cliente paga, il sistema lo **conferma da solo** (controllando la firma di Stripe).
👉 Su Stripe ricordati di creare il "Webhook" verso
`https://bookinvip.com/api/payments/webhook` (evento `checkout.session.completed`).

## 5.2 Accendere le EMAIL (voucher all'ospite)
Nel `.env.casavip` scrivi i dati del tuo provider email:
```
SMTP_HOST=smtp.tuoprovider.com
SMTP_PORT=587
SMTP_USER=no-reply@bookinvip.com
SMTP_PASSWORD=la-password-della-casella
EMAIL_MITTENTE=no-reply@bookinvip.com
```
**Cosa cambia:** a ogni prenotazione confermata, l'ospite riceve **l'email** col voucher.
(Se l'email cade, la prenotazione resta valida lo stesso.)

## 5.3 Accendere la GUARDIA del codice (Sentinel) — opzionale
Nel `.env.casavip`:
```
SENTINEL=1
```
**Cosa cambia:** il sistema sorveglia i propri file: se qualcuno li modifica, lo segnala.

## 5.4 Le chiavi delle pagine
Sempre nel `.env.casavip`:
```
HOST_KEY=una-password-lunga-per-te
ADMIN_KEY=un-altra-password-per-i-rimborsi
BASE_URL=https://bookinvip.com
```
> Se lasci HOST_KEY o ADMIN_KEY **vuote**, i pannelli restano **aperti** (va bene solo per
> fare prove sul tuo computer, **mai** online). Online: mettile sempre, lunghe e diverse.

---

# PARTE 6 — IL GIRO COMPLETO (prova che funzioni tutto)

1. **Host**: pubblichi una casa + apri un periodo di date.
2. **Cliente** (vetrina): cerchi, prenoti con un'email, paghi con la **carta di test
   Stripe** `4242 4242 4242 4242` (scadenza futura, CVC qualsiasi).
3. Arriva l'**email** col **voucher** (se hai acceso l'SMTP).
4. **Admin**: vedi la prenotazione nell'elenco.
5. (Per provare) **Rimborsa** → la data torna libera.

Se questi 5 passi vanno, **tutto funziona**.

---

# PARTE 7 — SE QUALCOSA NON VA

- **"Non riesco a pubblicare / errore prezzo"** → hai scritto il prezzo in euro invece che
  in centesimi? €95 va scritto **9500**.
- **"Non vedo la casa nella vetrina"** → l'hai **pubblicata** ma hai anche **aperto le
  date**? Senza date disponibili non compare come prenotabile. Controlla anche di non
  averla **sospesa** in "I miei alloggi".
- **"Il pannello dice non autorizzato"** → la **chiave** (host/admin) è sbagliata o vuota.
- **"Il pagamento non parte"** → manca `STRIPE_SECRET_KEY` nel `.env` (vedi 5.1).
- **"Non arriva l'email"** → mancano i dati `SMTP_*` nel `.env` (vedi 5.2).
- **Vedere cosa succede sul server** → `docker compose -f docker-compose.casavip.yml logs -f`

---

## Riassunto in 1 minuto
- I prezzi si scrivono in **centesimi** (€95 = 9500).
- **Host** = `/host.html` con la **HOST_KEY**: pubblica → apri le date → e sei prenotabile.
- **Cliente** = `/` : cerca → prenota → voucher.
- **Admin** = `/admin.html` con la **ADMIN_KEY**: rimborsi.
- Le funzioni extra (pagamenti, email) si **accendono scrivendo le chiavi nel `.env`** e
  riavviando — niente codice.

Buon lavoro! 🥭
