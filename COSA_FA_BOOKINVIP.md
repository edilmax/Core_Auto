# BookinVIP — Cosa fa la macchina (tutte le funzioni)

> Spiegazione completa e onesta. Diviso in: **A) cosa fa OGGI** (acceso nel prodotto
> live), **B) motori pronti** (costruiti e testati, da collegare alla UI), **C) principi**.
> Software: 93 fasi, 1429 test verdi, zero dipendenze esterne, su github.com/edilmax/Core_Auto.
>
> **Commissione: 15%** (configurabile via `COMMISSIONE_BPS`, default live 1500 = 15% —
> sotto il 18–25% delle OTA). Strategia: 15% per i primi 1000 alloggi iscritti.

## In una frase
BookinVIP è una **piattaforma di prenotazione alloggi** (come Booking/Airbnb) ma
**automatica e a costo zero di personale**: l'ospite cerca e prenota, paga con Stripe,
riceve un voucher che è anche la chiave d'ingresso; l'host gestisce tutto da un pannello;
gli agenti IA possono prenotare da soli. Il tutto firmato crittograficamente, multilingua,
con denaro sempre in centesimi interi (zero errori di arrotondamento).

---

# A) COSA FA OGGI (acceso e funzionante)

## 1. Per l'OSPITE (pagina `/` — la vetrina)
- **Cerca** alloggi per città, date, ospiti, **prezzo massimo**, **servizi** (wifi,
  piscina, parcheggio…).
- Vede le **schede con foto**, prezzo per notte, **stelle delle recensioni verificate**,
  e se è **disponibile** in quelle date (disponibilità reale, non finta).
- Apre il **dettaglio**: galleria foto, descrizione, servizi, recensioni verificate, e il
  **preventivo firmato** (alloggio + commissione, totale).
- **Prenota** inserendo l'email → riceve la conferma e un link al **voucher**.
- **Multilingua**: tutta l'interfaccia in IT/EN/ES/FR/DE (cambio lingua istantaneo).
- **App installabile (PWA)**: si aggiunge alla schermata Home del telefono, funziona
  anche offline (lo "scheletro").

## 2. Il pagamento (Stripe) — *attivo quando metti la chiave*
- Alla prenotazione il sistema crea un **link di pagamento Stripe** reale (il prezzo è
  firmato dal sistema, l'ospite non può modificarlo).
- Quando l'ospite paga, Stripe avvisa via **webhook**: il sistema **verifica la firma**
  (anti-truffa) e conferma il pagamento.

## 3. Il voucher + chiave d'ingresso (`/voucher/<codice>`)
- A prenotazione confermata, l'ospite riceve un **voucher firmato** (non falsificabile),
  stampabile e multilingua, con i dettagli del soggiorno.
- Il voucher **incorpora lo smart-pass**: un codice valido **solo** nella finestra del
  soggiorno (check-in 15:00 → check-out 11:00), verificabile **offline** da una serratura
  smart → **self check-in, zero reception**.

## 4. L'email di conferma — *attiva quando metti l'SMTP*
- A prenotazione confermata, l'ospite riceve un'**email** con la conferma e il link al
  voucher (invio automatico, isolato: se l'email cade, la prenotazione resta valida).

## 5. Le recensioni verificate
- **Solo chi ha davvero pagato e soggiornato** può recensire (il sistema emette un
  "diritto di recensione" firmato alla prenotazione). → **recensioni false impossibili.**
- Le ★ compaiono nelle schede, nel dettaglio, e nei **risultati Google** (dati strutturati).

## 6. Per l'HOST (pagina `/host.html`)
- **Pubblica un alloggio** (titolo, città, prezzo, capacità, servizi, **foto**).
- **I miei alloggi**: elenco con **sospendi / ripubblica** (controllo totale).
- **Disponibilità**: imposta un singolo giorno, oppure **apri un intero periodo** in un colpo.
- **Importa il calendario iCal** da Airbnb/Booking/Vrbo → le date già occupate si bloccano
  da sole (**anti-overbooking cross-canale**, la migrazione reale e legale).
- **Calendario** colorato: vedi a colpo d'occhio i giorni liberi/pieni/chiusi.
- **Dashboard**: revenue, % occupazione, n° prenotazioni, rating.
- **Export CSV** delle prenotazioni (per la contabilità).
- **Trasparenza vs OTA**: *"con Booking incassi €82, con noi €95 → +€13 a notte"*.

## 7. Per l'ADMIN (pagina `/admin.html`)
- **Elenco prenotazioni AUTOMATICO**: la chiave admin è ricordata nel browser, le
  prenotazioni si caricano **da sole** all'apertura e si aggiornano ogni 60s (nessun
  click "carica").
- **Rimborsa**: libera le date (cancellazione). Il rimborso del denaro su Stripe si
  esegue quando Stripe è collegato.
- **📣 Pubblica campagna marketing** (un bottone): genera post multilingua + immagini
  promo (card SVG) e li pubblica sui canali configurati nel server (vedi §11).

## 11. Marketing & canali social — *attivi quando metti le chiavi*
- **Motore marketing 360°**: genera post (host/ospite/referral) in 5 lingue + immagini
  promo SVG + calendario editoriale, e li manda anche via email.
- **Canali di pubblicazione** (adapter "gated", si accendono dal `.env`):
  **Telegram** (gratis), **Facebook + Instagram** (Meta Graph), **X/Twitter** (OAuth1,
  API a pagamento), **TikTok** (video-first). Senza chiavi i post si **generano** ma non
  si pubblicano (zero errori).
- **Tassa di soggiorno** (`/api/tassa`) e **split-payment di gruppo**
  (`/api/split/crea|paga|stato`): calcolo per città (default 0, jurisdiction-agnostic) e
  divisione del costo tra più ospiti con conservazione esatta al centesimo — **già esposti
  come API**.

## 12. Outreach B2B compliant (acquisizione host — opt-in)
- Motore **"Jurisdiction Radar & Outreach"**: contatta host/strutture **solo dove è
  legale** (allow-list fail-closed, UE esclusa di default), **solo dati pubblici di
  aziende**, con email "Prima Emilia" multilingua e **opt-out obbligatorio**. **Niente
  scraping, niente proxy, niente aggiramento blocchi** (illegale e autodistruttivo).

## 8. Per gli AGENTI IA (`/api/mcp`) — il futuro 2026-2030
- BookinVIP espone un **server MCP** (Model Context Protocol): qualsiasi agente IA
  (Claude, ChatGPT, Cursor…) si collega **senza integrazione custom** e usa 6 strumenti:
  cerca, dettaglio, preventivo, prenota, lingue, confronto-OTA.
- **Loro pagano il loro LLM, non noi.** Il prezzo è firmato dal sistema, l'agente non può
  manometterlo. È acquisizione clienti a costo zero nell'era degli agenti.

## 9. SEO / farsi trovare gratis
- Ogni alloggio ha una **pagina crawlabile** (`/alloggio/<slug>`) con dati strutturati
  Schema.org → compare su Google con **stelle e prezzo** (rich results).
- **sitemap.xml** + **robots.txt** generati automaticamente.

## 10. Sicurezza (sempre attiva)
- **Denaro in centesimi interi** ovunque (mai float → zero errori di arrotondamento).
- **Firme HMAC** su preventivi, voucher, recensioni, referral, smart-pass.
- **Anti-overbooking atomico**: impossibile vendere due volte la stessa notte (provato
  con decine di prenotazioni simultanee).
- **Fail-closed**: nel dubbio il sistema nega, non inventa.
- **Sentinel** (opzionale): sorveglia i file del codice (modifiche = allarme).

---

# B) MOTORI PRONTI (costruiti e testati, da collegare alla UI)

Questi esistono come moduli testati ma **non sono ancora esposti nell'interfaccia** — si
attivano collegandoli quando servono:

| Motore | Cosa fa |
|---|---|
| **Tassa di soggiorno** | Calcolo per città (jurisdiction-agnostic, default 0). ✅ **Ora con API** `/api/tassa` (§11). |
| **Split-payment di gruppo** | Più ospiti dividono il costo, ognuno la sua quota (esatta al centesimo). ✅ **Ora con API** `/api/split/*` (§11). |
| **Coda intelligente** | Lista d'attesa con deposito: se si libera, prenoti; se no, voucher maggiorato. |
| **Predictive no-show** | Stima i mancati arrivi e consiglia overbooking controllato (conservativo). |
| **Commitment engine** | Deposito anti-cancellazione + cleaning fee trasparente + scudo anti-chargeback. |
| **Dichiarazione vincolante** | L'host dichiara ("no allergeni"…); se falso, l'escrow paga l'ospite (penale a carico host). |
| **Niche stacking** | Filtri di nicchia (pet/solo/nomad/accessibilità) con pricing dedicato. |
| **Sensory / Sleep score** | Punteggio sensoriale (silenzio/aria/luce) e garanzia sonno ("dormi 8h o rimborso"). |
| **Digital twin** | Telemetria dell'alloggio + manutenzione predittiva (rileva guasti prima). |
| **Guardian engine** | Rileva water leak/fuoco/muffa e produce il piano d'azione automatico. |
| **Automated turnover** | Coordina le pulizie tra check-out e check-in (gate "agibile"). |
| **Viral loop** | Crescita a costo zero: crediti referral non-cashabili (anti-frode). |
| **Crypto-agility** | La firma può evolvere (HMAC → schemi futuri) senza rompere nulla. |

## Il "satellite" Mango (acquisizione B2B autonoma — modulo separato)
Esiste un intero **funnel automatico** (fasi 43–55) che esplora host potenziali, calcola
quanto perdono con le OTA ("in 12 mesi hai perso €X"), li contatta in modo consensato
(GDPR), e quando convertono crea la prenotazione. Gira da solo con governo dei costi LLM
e auto-spegnimento se qualcosa si rompe. **È costruito e testato, ma spento di default**
(non collegato al prodotto BookinVIP live).

## Il marketplace originale (la "fortezza")
Sotto c'è anche il motore finanziario originale (escrow, split payment, audit immutabile,
HMAC, rate-limit) e il prodotto "Tavola VIP" (prenotazioni con Stripe, pannello admin
Flask). Sono le **fondamenta storiche**, testate; il prodotto BookinVIP è la loro
evoluzione "alloggi".

---

# C) PRINCIPI TRASVERSALI (il DNA della macchina)
1. **Zero spese di software**: gira su pura libreria standard Python, nessuna dipendenza
   a pagamento. L'unica fee reale è quella di Stripe per transazione.
2. **Zero personale**: tutto automatico (prenotazione, voucher, check-in, recensioni,
   notifiche, backup).
3. **Denaro a prova di bomba**: centesimi interi, firme HMAC, "il prezzo non lo decide
   mai l'IA".
4. **Multilingua** per costruzione (clienti e host).
5. **Isolamento**: ogni modulo è a sé; se un pezzo cade, il resto vive.
6. **Testato fino in fondo**: 1429 test verdi, zero regressioni, ogni funzione verificata
   anche "live" sul server reale.
7. **Pronto all'accensione**: pagamenti, email e webhook sono "gated" — il sistema gira
   identico senza credenziali, e si accende mettendo le chiavi nel `.env`, **zero modifiche
   al codice**.

---

## In sintesi
**Oggi**: una piattaforma di alloggi completa e funzionante (vetrina, prenotazione,
pagamento, voucher+chiave, email, recensioni verificate, pannello host con dashboard, admin
rimborsi, SEO, app installabile, MCP per agenti), pronta ad andare online su bookinvip.com.
**In più**: una valigia di "motori" avanzati e un funnel di acquisizione autonomo, già
costruiti e testati, da accendere quando vorrai crescere.
