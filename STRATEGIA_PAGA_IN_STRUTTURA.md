# 🏨 PAGA IN STRUTTURA + garanzia carta (2026-07-11)

> Leva di **fiducia** per chi non ci conosce ancora: *"pago quando arrivo → solo se il posto è
> vero, non perdo nulla se non esiste"*. Abbatte la barriera #1 di una piattaforma nuova (cold-start),
> proteggendo l'host (garanzia carta contro i no-show) e **noi mai in perdita**.

## 1. Come funziona (design)
Al momento della prenotazione il cliente sceglie **"Paga in struttura"**:
- **NON paga online adesso.** Registra una **carta come GARANZIA** (Stripe *SetupIntent*, carta-su-file,
  **non addebitata**).
- **All'arrivo paga l'host** direttamente (contanti/carta/POS dell'host) il prezzo pulito.
- La carta è la garanzia: se **no-show** (non si presenta) o **cancellazione tardiva**, addebitiamo la
  **penale** (= la politica di cancellazione dell'alloggio, `fase111`) sulla carta salvata.

## 2. Come fanno i colossi (Booking) — verificato
- **Garanzia/prepagamento** = di norma pari alla penale di cancellazione (carta a garanzia).
- **No-show**: l'host segna "no-show" (finestra: da mezzanotte del check-in fino a 48h dopo il
  check-out) → si addebita la penale sulla carta.
- **Commissione sul no-show**: la piattaforma prende commissione **anche sulle penali incassate**
  (non se la penale è annullata). → così anche i no-show ci pagano.

## 3. Chi porta il peso (e noi mai in perdita)
| Scenario | Cliente | Host | Noi (BookinVIP) |
|---|---|---|---|
| Soggiorno regolare | paga in struttura (prezzo pulito) | incassa in struttura | commissione (vedi sotto) |
| **No-show / cancellazione tardiva** | penale addebitata sulla **carta a garanzia** | riceve la sua quota di penale | **commissione sulla penale** (come Booking) |
| Struttura inesistente / non conforme | **non paga nulla** (non ha pagato online) | — | — → fiducia massima per il cliente |

**La nostra commissione (mai in perdita):** su "paga in struttura" l'host incassa in loco, quindi la
nostra commissione va **garantita**. Opzioni (decisione fondatore):
- **(A) consigliata** — commissione **pre-autorizzata sulla carta a garanzia** e catturata a soggiorno
  avvenuto (o sulla penale in caso di no-show) → certa, zero anticipo nostro.
- (B) addebito diretto all'host della sola commissione (SEPA/carta host on-file).
In entrambe: **non anticipiamo mai denaro**; la carta-garanzia copre no-show e la nostra presa.

## 4. Psicologia (la vera leva)
- **Cliente diffidente** → "pago sul posto, rischio zero": converte chi NON prenoterebbe mai pagando
  in anticipo su un sito sconosciuto. È il grimaldello del cold-start.
- **Host** → protetto dai no-show (penale garantita dalla carta), incassa in loco (liquidità subito).
- **Noi** → commissione garantita dalla carta, zero rischio, e acquisiamo clienti che i colossi non
  convertirebbero (loro spingono il prepagato).
- Etico: nessun addebito a sorpresa — la garanzia e la penale sono **mostrate chiaramente prima** di prenotare.

## 5. Aggiornare la logica ovunque (coerenza)
- **Preventivo/prenotazione** (`fase59`): aggiungere `modalita_pagamento` = `online` | `in_struttura`.
- **Voucher**: memorizzare la modalità + il SetupIntent id (garanzia).
- **Cancellazione/no-show** (`fase111` + endpoint): la penale su "in_struttura" si addebita alla carta;
  aggiungere l'azione host **"segna no-show"** (finestra check-in → +48h) che scatena l'addebito penale.
- **Escrow** (`fase160`): per "online" resta com'è; per "in_struttura" l'host incassa in loco, la carta
  copre solo penale + nostra commissione.
- **Pannello host**: stato "in_struttura", pulsante "segna no-show", incasso atteso in loco.
- **Ricerca/scheda**: badge "✔ Paga in struttura" (come "cancellazione gratuita") → altra leva di conversione.

## 6. Attivazione (gated a Stripe)
Il salvataggio carta (SetupIntent) e l'addebito no-show (PaymentIntent) richiedono **Stripe live**
(oggi gated). Da fare: SetupIntent al booking, PaymentIntent sulla penale/commissione, webhook.
Il MODELLO e la LOGICA (modalità, penale = `fase111`, finestra no-show, chi paga) si costruiscono
ora e si accendono con Stripe. Vedi anche `STRATEGIA_CANCELLAZIONE.md` (penali) e `STRATEGIA_TASSE_CAMBIO.md`.

**Fonti:** [Booking – no-show](https://partner.booking.com/en-us/help/reservations/overbookings-no-shows/reporting-guest-no-shows-your-property) · [Booking – Smart Pay-at-Property](https://partner.booking.com/en-us/help/policies-payments/payment-products/smart-pay-at-property)
