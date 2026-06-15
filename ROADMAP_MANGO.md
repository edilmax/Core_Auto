# Roadmap di riattivazione — Modulo "Mango" (Agente Social / Advertising)

> Piano d'azione per innestare il cervello esterno (ricerca social, outreach,
> advertising, gestione esterna) SOPRA Tavola VIP, **senza toccare** il motore
> prenotazioni/pagamenti. Metodo: spike → benchmark → test → integra solo la
> vincitrice → gate di regressione (oggi **492 test**). Un mattone = un commit.

---

## 0. Correzione del presupposto (stato reale)

Le **fasi 24-33 NON sono parcheggiate: sono costruite, testate e committate.** Sono
il **cervello conversazionale** gia' pronto e riusabile:

| Gia' costruito (riusabile per Mango) | Cosa da' |
|---|---|
| fase25 `ResilientBrain`, fase40 `AnthropicLLMProvider` | LLM reale isolato (timeout/circuit/cache) |
| fase30 `ClientLLM`, fase32 `GovernatoreToken` | budget token per-richiesta + **quota/costo GLOBALE** |
| fase31 `AgenteConversazionale`, fase33 memoria durevole | conversazione multi-turno cross-worker |
| fase26 `MotoreRicercaProtetto` (`RicercaProvider` ABC) | motore ricerca (oggi sul DB **interno** `candidati`) |
| fase27 `GeneratoreProposte` | offerte commerciali in **centesimi** |
| fase24 `ChannelAdapter`, fase39 WhatsApp | canali in **uscita** (+ Outbox at-least-once) |
| fase28 `GatewayAgente`, fase29 backpressure | auth per-cliente + sopravvivenza al carico |

Quello che e' **davvero parcheggiato = "MANGO"** (lo strato commerciale): l'unico
artefatto e' lo spike `_spike_commissione_bench.py` (la **"Rana Inversa"**, vincitrice
Variante D multifattore+cricchetto, mai integrata). Il resto (Esploratore social/web,
Analista pricing, Venditore outreach, Advertising) e' stato **progettato** (war plan v2)
ma non costruito.

> ⚠️ **Conflitto di numerazione**: il war plan v2 proponeva `fase34_commissione`,
> `fase35_pricing`, ecc., ma quei numeri ora sono di Tavola VIP (booking/pagamenti).
> I mattoni Mango usano numeri NUOVI: **fase43+**.

**Conseguenza sulla stima**: ~50-60% dell'infrastruttura agente esiste gia'. Resta
da costruire ~40% (fonti esterne reali, pricing, inbound social, outreach, advertising,
ponte sicuro).

---

## 1. Stima

**~7 incrementi architetturali** (≈ 7-9 sessioni col ritmo attuale; i due "larghi"
— Esploratore e Advertising — valgono per ~2). Come per Stripe/WhatsApp, alcuni
mattoni sono **buildabili+testabili in sandbox con stub**, ma l'**accensione live**
e' gated da credenziali/API esterne (Meta/Instagram, metasearch, ad platform).

| | Sandbox (codice+test) | Live (richiede credenziali) |
|---|---|---|
| M1 Rana Inversa | ✅ completo | — |
| M2 Esploratore | ✅ con stub | API partner / metasearch |
| M3 Pricing | ✅ completo | — |
| M4 Inbound social | ✅ con stub | webhook Meta/Instagram |
| M5 Venditore | ✅ con stub | numeri/account social |
| M6 Advertising | ✅ con stub | ad platform + posting |
| M7 Ponte→booking | ✅ completo | — |

---

## 2. Roadmap esatta (i mattoni, in ordine)

- **M1 — `fase43_commissione.py` (Rana Inversa).** Integra lo spike vincitore
  (scaglioni discendenti + cricchetto, in centesimi, estende fase17). Spike gia'
  fatto → benchmark→modulo→test. *Cuore finanziario di Mango.* Sandbox-completo.

- **M2 — `fase44_esploratore.py` (Esploratore compliant).** Nuovo `RicercaProvider`
  su **fonti esterne LECITE** (API partner ufficiali, metasearch, listing pubblici,
  iCal fornito dall'host) — **niente evasione anti-bot**. Costruisce un DB
  "property intelligence" + pain-score. Benchmark a varianti di fonte; stub in test.

- **M3 — `fase45_pricing.py` (Analista).** Pricing dinamico a 3-vie (gap commissione
  spartito host/guest/Mango) che alimenta `fase27` proposte; denaro in centesimi via
  fase17. Sandbox-completo.

- **M4 — `fase46_inbound.py` (Ingestione social).** Ricevitore webhook inbound
  (WhatsApp/Instagram) con **dedup idempotente** dei duplicati at-least-once +
  **verifica firma** + normalizzazione. Chiude il gap inbound (l'outbound e' gia'
  blindato). Stub firmato in test.

- **M5 — `fase47_outreach.py` (Venditore).** Orchestratore di sequenze: cabla
  `AgenteConversazionale`(31) + `ChannelAdapter`(24) + Outbox(16) + `GovernatoreToken`(32)
  → outreach **B2B consensato** (GDPR, opt-out). Per lo piu' wiring di pezzi esistenti.

- **M6 — `fase48_advertising.py` (Advertising).** Generazione contenuti/annunci via
  LLM (denaro mai dall'IA), gestione campagne, scheduling. Capacita' NUOVA; posting
  reale gated da ad platform. Benchmark a varianti di strategia contenuti.

- **M7 — `fase49_ponte_booking.py` (Aggancio sicuro).** Quando una conversazione
  converte, l'agente crea prenotazione+link **riusando il pattern di fase40**
  (`MotorePrenotazioni.crea` + `ServizioPagamenti`), unico touchpoint col denaro.

---

## 3. Come innestare SENZA toccare/rompere il motore booking

Protocollo d'isolamento (la garanzia che il motore prenotazioni/pagamenti resta intatto):

1. **Moduli nuovi `fase43+`**, import **lazy**, **default-off** (feature-flag).
   fase34-36 (booking/pagamenti) **non importano** Mango: il motore non sa che esiste.
2. **Un solo touchpoint col denaro**: la stessa interfaccia pubblica
   `MotorePrenotazioni.crea` + `ServizioPagamenti.crea_link_pagamento` che fase40
   gia' usa **in sicurezza** (denaro dal SISTEMA, mai dall'IA). Mango propone; il
   nucleo decide e incassa.
3. **Astrazioni, non modifiche**: nuove fonti = `RicercaProvider`; nuovi canali =
   `ChannelAdapter`/`Notificatore`; nuovo LLM = `LLMProvider`. Zero patch al nucleo.
4. **Gate di regressione** ad ogni mattone: i **492 test** (incluso tutto il booking)
   devono restare verdi → il motore e' immobile per costruzione.
5. **Compliance-first**: fonti lecite, outreach consensato (GDPR/opt-out), claim
   veritieri, niente scraping evasivo. (E' cio' che rende Mango difendibile.)
6. **Costo sotto controllo**: il `GovernatoreToken`(32) protegge gia' la spesa LLM
   globale sotto "centinaia di chat".

> In una riga: Mango e' un **satellite** che osserva, cerca e propone; tocca il denaro
> solo attraverso la stessa porta sicura gia' collaudata. Il motore booking non cambia.
