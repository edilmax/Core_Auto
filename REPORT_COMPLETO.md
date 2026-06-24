> 🔄 Aggiornato 2026-06-24 · **BookinVIP** · suite **1740 test** (0 regressioni) · moduli `faseNN`→151 · infra VPS Aruba 89.46.65.6 ATTIVO · fonte di verità: **STATO_FINALE.md**

# REPORT COMPLETO — Cosa c'è davvero nella cartella Core_Auto

> Audit onesto e completo (2026-06-23). Esaminati: 69 moduli `fase*.py` (17.161 righe),
> 89 file di test (15.223 righe), 14 documenti, cartella `deploy/`, infrastruttura.
> Obiettivo: capire cosa fa REALMENTE ogni cosa, i parametri scelti, cosa è collegato.

## 0. Riepilogo in 5 righe
- Il codice serio = **69 moduli `fase*.py` + 89 test**, tutti documentati e testati.
- Sono cresciuti **4 "mondi" diversi** nel tempo (vedi §2): fondamenta, ristoranti, funnel
  acquisizione, e il prodotto attuale **BookinVIP (alloggi)**.
- Del totale, **solo 17 moduli sono collegati al prodotto live**; ~52 sono **costruiti e
  testati ma NON collegati** (non persi: da ricucire).
- C'è **~150 file `ricombinato_*.py` = SPAZZATURA** (output di un vecchio generatore, giu 2025).
- **BUG trovato**: la commissione mostrata (5%) ≠ quella incassata (0%). Va sistemata.

---

## 1. Inventario della cartella
| Tipo | Quantità | Note |
|---|---|---|
| Moduli `fase*.py` | 69 (17.161 righe) | il sistema vero, documentato + testato |
| Test `test_*.py` | 89 (15.223 righe) | 1740 test, zero regressioni |
| `ricombinato_*.py` | ~150 | **SPAZZATURA** (vecchio generatore automatico, giu 2025) — da cancellare |
| `super_ai_creator.py`, `super_linker.py` | 2 | vecchi strumenti generatori — non usati dal prodotto |
| `app.py`, `assistente_gestionale.py` | 2 | vecchio core "Tavola VIP" (Flask + motore ricerca) |
| Documenti `.md` | 14 | masterplan, guide, report, legale |
| `deploy/` | 15 file | vetrina, host, admin, voucher, PWA, nginx, Docker |

---

## 2. I 4 "MONDI" nel codice (importante da capire)
Il progetto ha accumulato 4 stack diversi. **Solo il D è il prodotto attuale.**

### A) Fondamenta CORE_AUTO (fase 13–33) — il motore profondo
Cassaforte transazionale + cervello IA. **Tutto costruito e testato, NON collegato a BookinVIP.**
- `17` money (centesimi interi), `15` idempotency, `16` outbox, `23` datastore (PG-ready)
- `24` canali social (Telegram ok, WhatsApp/IG da credenziali), `25` cervello/AgenteIA,
  `26` ricerca, `27` proposte, `28` gateway, `29` backpressure
- `30` client LLM, `31` conversazione multi-turno, `32` governatore costi LLM, `33` memoria durevole
- **➡️ QUI sta l'agente conversazionale social che cercavi.** È reale, ma usa un LLM (costo)
  ed è cablato al vecchio motore ristoranti, non agli alloggi.

### B) Tavola VIP — booking ristoranti (fase 34–42) — prodotto VECCHIO
Lo stack "prenota un tavolo". **Costruito/testato, superato dal lodging.**
- `34` prenotazioni, `35` pagamenti (PSP+webhook), `36` API booking, `37` notifiche/voucher,
  `38` backup, `39` WhatsApp, `40` agente booking IA, `41` pannello admin, `42` observability

### C) Funnel Mango — acquisizione B2B autonoma (fase 43–56) — SPENTO
La macchina che cerca host, calcola quanto perdono, li contatta, converte. **Spenta di default.**
- `43` commissione, `44` prezzo, `45` split a 3 vie, `46` esploratore (pain-score),
  `47` venditore/outreach, `48` advertising, `49` ponte booking, `50` orchestratore,
  `51` scheduler, `52` persistenza+metriche, `53` health-guard, `54` loop, `55` bootstrap,
  `56` gateway tavoli
- **➡️ Contattare host a freddo: limite legale + ban (vedi memoria strategia).**

### D) BookinVIP — il PRODOTTO ATTUALE (alloggi, fase 57–88) ✅ LIVE
- `57` vetrina, `58` inventario realtime anti-overbooking, `59` concierge prezzo-firmato,
  `60` MCP (agenti IA), `61` i18n 5 lingue, `62` no-show*, `63` recensioni verificate,
  `64` smart-pass check-in, `65` split-payment gruppo*, `66` tassa soggiorno*, `67` coda*,
  `68` niche*, `69` trasparenza vs OTA, `70` turnover*, `71` commitment*, `72` digital twin*,
  `73` firma agile, `74` sensory*, `75` guardian*, `76` viral loop, `77` portability*,
  `78` sleep guarantee*, `79` dichiarazione vincolante*, `80` sentinel, `81` bootstrap,
  `82` iCal sync, `83` server HTTP, `85` Stripe, `86` email, `87` webhook Stripe, `88` registro host
- `*` = **costruito e testato ma NON collegato all'interfaccia** (i "geniali" da ricucire).

---

## 3. Cosa è COLLEGATO al prodotto live vs no
**Collegati (17)**: 57, 58, 59, 60, 61, 63, 64, 69, 76, 80, 81, 82, 83, 85, 86, 87, 88.
→ vetrina, inventario, concierge, MCP, lingue, recensioni, smart-pass, trasparenza, viral,
sentinel, bootstrap, iCal, server, Stripe, email, webhook, registro host self-service.

**Costruiti ma NON collegati (~52)** — i due gruppi che valgono:
- **Motori "geniali" del lodging (14)**: 62 no-show, 65 split-payment, 66 tassa, 67 coda,
  68 niche, 70 turnover, 71 commitment, 72 digital-twin, 73 firma-agile, 74 sensory,
  75 guardian, 77 portability, 78 sleep, 79 dichiarazione. **➡️ Da cablare = lavoro reale.**
- **Agente IA social (BLOCCO 3+4)**: 24–33. **➡️ Il tuo "agente sulle chat" è qui.**

---

## 4. PARAMETRI SCELTI (i numeri che governano i soldi)
| Cosa | Dove | Valore attuale | Note |
|---|---|---|---|
| **Commissione mostrata** (vetrina/host) | fase69 | **5%** (500 bps) | quella della calcolatrice "vs Booking" |
| **Commissione INCASSATA** (concierge) | fase59/81 | **0%** ⚠️ | NON cablata → **BUG: mostrato≠incassato** |
| Commissione OTA (confronto) | fase69 | 18% (1800 bps) | benchmark Booking indicativo |
| Fee PSP (Stripe) | fase69 | 0 (pass-through) | configurabile |
| Credito referral | fase76 | **€50** a testa (5000 cents) | referente + nuovo host |
| Validità credito | fase76 | 365 giorni | non-cashabile |
| Check-in / Check-out | fase64 | **15:00 / 11:00** | orari dello smart-pass |
| Tassa di soggiorno | fase66 | **0** (default) | jurisdiction-agnostic, da impostare per città |
| Token host (login) | fase88 | 30 giorni, PBKDF2 200k | sicurezza self-service |

**⚠️ Decisione tua in sospeso: la percentuale di commissione.** Oggi è incoerente (0 incassato,
5% mostrato). Va resa UN parametro e impostata al valore che decidi (3/5/15/20%).

---

## 5. Documenti presenti
- **MASTERPLAN.md** = la VISIONE originale (agente IA su chat social, 5 blocchi). **Il tuo file.**
- ARCHITETTURA.md, ROADMAP_MANGO.md, MANUALE_MACCHINA_TOTALE.md, LIBRO_OPERATIVO_TOTALE.md = design storico
- COSA_FA_BOOKINVIP.md, GUIDA_USO.md, GUIDA_DEPLOY.md, LISTA_GO_LIVE.md, DEPLOY_CASAVIP.md = operativi
- legale/ (privacy + termini, bozze)

---

## 6. Pulizia consigliata (igiene del progetto)
- **Cancellare i ~150 `ricombinato_*.py`** + `super_ai_creator.py` + `super_linker.py`: spazzatura
  che confonde (non importati da nessun modulo del prodotto). Riduce la cartella del ~70% dei file.

---

## 7. Verdetto onesto
1. Il prodotto **BookinVIP è reale, completo e testato** sul nucleo (prenota→paga→voucher→
   check-in→recensione, + self-service host + viral loop).
2. **Le "funzioni geniali" NON sono perse**: 14 motori del lodging + l'intero agente IA social
   sono costruiti e testati, solo **da ricucire** all'interfaccia.
3. C'è **un bug commissione** (incassato 0 ≠ mostrato 5%) e una **decisione tua** sulla %.
4. C'è **spazzatura da rimuovere** (~150 file).
5. La strada per "più potente dei colossi" = **cablare i 14 motori + l'agente social** (Telegram
   gratis subito), non riscrivere. È lavoro di integrazione, non di invenzione.
