# 🌍 TASSE MONDIALI + CAMBIO VALUTA — chi paga cosa (2026-07-10)

> Regola d'oro: **BookinVIP è un INTERMEDIARIO.** Le tasse sul SOGGIORNO e il CAMBIO VALUTA
> **non gravano su di noi**: sono pass-through o a carico di ospite/host. Noi paghiamo tasse **solo
> sulla nostra commissione**. Aggiungiamo **zero markup sul cambio** (l'opposto degli OTA). → mai in perdita.

## 1. Chi porta il peso (matrice) — GIÀ implementato nel codice
| Voce | Chi la paga | Come la gestiamo | Fase |
|---|---|---|---|
| **Tassa di soggiorno / lodging tax** | **OSPITE** (pass-through all'autorità) | voce SEPARATA e visibile prima dell'acquisto; mai nostro margine né dell'host; default **ZERO** per giurisdizioni sconosciute (mai inventare una tassa) | `fase66` |
| **Cambio valuta (FX)** | **la BANCA dell'ospite** | si addebita nella valuta dell'HOST (like-for-like); all'ospite mostriamo l'importo indicativo a **tasso MID senza ricarico**; converte la sua banca → **noi zero rischio cambio, zero markup** | `fase59` |
| **IVA/GST sulla NOSTRA commissione** | **NOI** (solo sul nostro incasso) | Italia forfettario = **IVA esente**; reverse-charge sui servizi esteri (Stripe IE) = a nostro carico | `fase103` |
| **Imposta sul reddito dell'HOST** | **HOST** (è il suo reddito) | noi **riportiamo** (DAC7 UE); l'host dichiara e paga | `fase100` (DAC7) |
| **Commissione pagamento (Stripe)** | noi 3 mesi (investimento) → poi **HOST** | 0% all'ospite; vedi `STRATEGIA_CRESCITA.md` | `fase59`/deploy |
| **Ritenute alla fonte (alcuni Paesi)** | **HOST** (trattenuta sul payout dove obbligatorio) | dedotte dal payout host dove la legge lo impone | roadmap |

## 2. Obblighi mondiali della PIATTAFORMA (compliance, non costi nostri)
- 🇺🇸 **Marketplace Facilitator (USA)**: **30+ Stati** obbligano i marketplace STR a **incassare e VERSARE** la
  lodging tax dall'ospite (novità 2026: Illinois, Louisiana, Maryland, Indiana, Iowa…). → quando lanciamo negli
  USA, in quegli Stati **noi incassiamo dall'ospite e versiamo allo Stato** (registrazione per-Stato; `fase66`
  già calcola l'importo). È **pass-through** (soldi dell'ospite), non un nostro costo.
- 🇪🇺 **DAC7**: le piattaforme UE devono **riportare** i redditi degli host al fisco (annuale). Coperto da
  `fase100`. Regimi analoghi in **Australia/NZ/Canada** (nazionali) → da aggiungere all'espansione.
- 🇪🇺 **IVA OSS / GST** sulla nostra commissione: quando usciamo dal forfettario / trasferiamo la sede, potremmo
  dover registrare **VAT-OSS** (UE) o GST locale **sulla commissione** → sempre solo sul NOSTRO incasso.

## 3. Perché così NON perdiamo mai (e siamo onesti)
- Non tocchiamo mai i soldi delle tasse sul soggiorno: le calcoliamo, le mostriamo, le giriamo. Se uno Stato ci
  obbliga a versarle, sono comunque **soldi dell'ospite** che transitano (pass-through), non nostro margine.
- **Nessun markup sul cambio**: gli OTA guadagnano nascondendo uno spread FX; noi no → più fiducia, e **zero
  rischio valutario** perché addebitiamo nella valuta dell'host.
- Paghiamo tasse **solo sulla commissione** che incassiamo davvero → nessun onere a sorpresa.

## 4. Gap / roadmap (da attivare all'espansione, col commercialista/tax advisor)
1. **Remittance USA** (marketplace facilitator): registrazione + versamento lodging tax per-Stato dove
   lanciamo (o via servizio tipo Avalara MyLodgeTax). `fase66` calcola già; serve il processo di versamento.
2. **VAT-OSS / GST sulla commissione** dopo il forfettario / trasferimento sede.
3. **Reporting** oltre DAC7: Australia/NZ/Canada quando ci sono host lì.
4. **Ritenute alla fonte** sui payout dove obbligatorie (dedotte all'host).

**Da confermare** ogni obbligo col commercialista/tax advisor PRIMA di lanciare in ciascun Paese.

**Fonti:** [Avalara – marketplace facilitator STR 2026](https://www.avalara.com/mylodgetax/en/blog/2025/11/more-states-require-short-term-rental-marketplaces-like-airbnb-and-vrbo-to-collect-lodging-taxes.html) · [Avalara – state-by-state marketplace facilitator](https://www.avalara.com/us/en/learn/guides/state-by-state-guide-to-marketplace-facilitator-laws.html) · [DAC7 overview (Fonoa)](https://www.fonoa.com/resources/blog/dac7overview)
