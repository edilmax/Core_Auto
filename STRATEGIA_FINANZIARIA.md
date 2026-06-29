# 💰 STRATEGIA FINANZIARIA — Valute, cambi, commissioni, tasse (zero perdite)

> Aggiornato 2026-06-30 · come NON perdere soldi sui cambi/commissioni, restando onesti. Codice: `fase99` (multi-valuta), `fase59` (Like-for-Like), `fase66/57` (tasse). Fonte: `STATO_FINALE.md`.

## 1. Il problema (dove i dilettanti perdono)
Quando un ospite paga in valuta estera:
- **Stripe/banca applica una fee di conversione (~1-2%) + lo spread sul tasso.**
- Se NOI convertiamo (incassiamo in EUR ma addebitiamo in USD), quella fee **la paghiamo noi** → mangia la nostra commissione (5-15%) → su una prenotazione possiamo andare **in perdita**.

## 2. Il "giochetto occulto" dei colossi (DCC)
Booking/Agoda usano la **Dynamic Currency Conversion**: offrono all'ospite di pagare nella SUA valuta a un tasso **peggiore del reale** (markup occulto **3-5%**) e si tengono lo spread. È profittevole per loro ma è una **fee nascosta** → l'opposto del nostro brand "0% ospite, prezzo pulito".

## 3. La nostra strategia: **LIKE-FOR-LIKE** (la mossa da professionista)
**Regola d'oro: si addebita SEMPRE nella valuta dell'host. Nessuna conversione forzata da parte nostra.**
- L'host prezza in **X** (es. USD) → l'ospite paga **X** → l'host incassa **X** → la nostra commissione è in **X**.
- **Stripe NON converte** (valuta di addebito = valuta di accredito) → **fee di cambio = €0 per noi**.
- La conversione la fa **la banca dell'ospite** (~1-2% Visa/MC), in modo **trasparente** (l'ospite la vede sul suo estratto conto), **NON noi**.
- Cablato in `fase59._valuta_alloggio`: il preventivo esce nella valuta dell'annuncio. Denaro tipizzato per valuta (`fase99.Denaro`): mischiare USD/EUR per errore è **vietato dal codice**.

**Risultato: ZERO rischio cambio per noi, e siamo più economici del 3-5% rispetto al DCC dei colossi.** È sia tutela (no perdite) sia marketing (onestà).

## 4. Se un giorno offriamo la conversione sul sito (opzionale)
Solo in modo **TRASPARENTE** (`fase99.converti`): mostriamo il **tasso mid reale** (da fonte iniettata, es. Open Exchange Rates) + un **markup ESPLICITO e basso (≤1%)** dichiarato come NOSTRA fee. **Mai occulto.** Default: meglio NON convertire (Like-for-Like).

## 5. La nostra commissione è blindata
La commissione (5%/15%) è **sempre nella valuta dell'addebito** → non viene mai convertita → **non può essere erosa dal cambio**. Copre: Stripe (~2,9%+0,25) + tasse forfettario + buffer. Senza fee di cambio a carico nostro, il margine resta positivo (vedi `bookinvip-architettura-finanziaria`).

## 6. Stripe (operativo, quando live)
- **Stripe Connect**: ogni host è un conto collegato che **accredita nella SUA valuta**; presentiamo l'addebito nella stessa valuta → **nessuna fee FX di Stripe**.
- L'ospite paga con carta estera → la fee di cambio è tra lui e la SUA banca (foreign transaction fee), non nostra.
- La nostra `application_fee` (commissione) viene presa nella valuta dell'addebito.

## 7. Tassa di soggiorno — dichiarazione + verifica (anti-gonfiamento)
- L'**host DICHIARA** la regola della sua città (per-persona/notte + cap + %) → **è la sua obbligazione legale**: se sbaglia, **paga lui** (non noi).
- Il sistema calcola la tassa **dal tasso dichiarato × dati della prenotazione che controlliamo NOI** (notti × ospiti dalle date firmate) → l'host **non può gonfiare** l'importo a piacere: è sempre `tariffa_dichiarata × notti × ospiti`, deterministico e verificabile.
- Città senza regola → tassa **0** (mai inventare → impossibile sovrattassare).
- È **pass-through alla città** (non è nostro ricavo né dell'host): voce separata, visibile **prima** dell'acquisto.

## 8. La regola in una riga
> **Addebita nella valuta dell'host (Like-for-Like), non convertire mai (niente DCC occulto), prendi la commissione nella stessa valuta, e la tassa calcolala dal tasso dichiarato dall'host × i dati che controlli tu.** → Zero perdite, zero inganni, più economici dei colossi.

## 9. Cosa resta (operativo)
- [ ] Su Stripe live: configurare Connect con accredito per-host nella valuta dell'host.
- [ ] (Opzionale) display indicativo nella valuta dell'ospite con `fase99.converti` (mid + ≤1% esplicito), gated da una fonte tassi.
- [ ] Confermare col commercialista il trattamento IVA/forfettario delle commissioni in valuta estera (cambio alla data fattura).
