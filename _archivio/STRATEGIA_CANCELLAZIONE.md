# 🛡️ Strategia Cancellazione BookinVIP — "vincere sui colossi" (2026-07-10)

Sistema di cancellazione progettato per **tutelare tutti** (host, cliente, e BookinVIP **mai in
perdita**), blindato legalmente **a livello mondiale** e con leve psicologiche etiche.

## 1. I 4 livelli (l'host sceglie, proporzionati = legali ovunque)
| Politica | 100% | 50% | 0% | Prezzo |
|---|---|---|---|---|
| **Flessibile** | fino a 24h prima (≥1 giorno) | ultime 24h | — | pieno |
| **Moderata** | fino a 5 giorni prima | 5gg → 24h | ultime 24h | pieno |
| **Rigida** | fino a 30 giorni prima | 30 → 7 giorni | < 7 giorni | pieno |
| **Non rimborsabile** | — | — | sempre | **−12%** (roadmap) |

Soglie allineate ad Airbnb (Flexible 24h / Moderate 5gg / Firm 30gg) e Vrbo. Codice: `fase111_cancellazione.py` (`POLITICHE`).

## 2. Dove SUPERIAMO i colossi
- 🕐 **Ripensamento 48h**: ogni prenotazione con arrivo ≥72h è annullabile al **100%** entro 48h
  dall'acquisto, *qualunque* politica. Airbnb ne dà 24h. Codice: `entro_ripensamento` in
  `calcola_rimborso` + calcolo in `_cancella_prenotazione` (usa `prenotato_data` nel voucher).
- 💚 **Anti-Rimpianto**: la penale trattenuta torna come **Credito Viaggio** (50% della penale,
  firmato, riscattabile). Il cliente non "perde" mai davvero → nessun colosso lo fa.
- 🧾 **Prezzo pulito** (0% commissioni ospite, tassa soggiorno sempre rimborsata).
- 🔍 **In ricerca**: badge **"✔ Cancellazione gratuita"** + filtro `solo_gratuita` (flessibile/moderata).

## 3. Scudi legali (progettato sullo standard più severo, valido nel mondo)
- **USA — FTC "Junk Fees Rule"** (in vigore 12/05/2025): obbligo di **prezzo totale tutto-incluso**.
  Noi già conformi (prezzo pulito). Multe evitate: fino a $51.744/violazione.
- **USA California — SB 644** (01/07/2024): 24h di cancellazione gratuita per prenotazioni ≥72h
  prima. Il nostro **ripensamento 48h** la copre e supera.
- **Brasile — art. 49 CDC**: diritto di pentimento 7gg online. Coperto dal ripensamento + credito.
- **Giappone**: online escluso dal cooling-off, ma obbligo di **policy chiara** → i 4 livelli sono espliciti.
- **UE — Dir. 2011/83 art. 16(l) + CGUE C-96/21**: nessun recesso obbligatorio per alloggi datati →
  il "non rimborsabile" è **legale**. **Dir. 93/13 (clausole vessatorie) + UK CRA 2015**: penali
  devono essere **proporzionate**; se la stanza è rivenduta l'host non può tenere tutto → il nostro
  **credito anti-rimpianto** neutralizza la contestazione (il cliente non perde, riceve valore).
- **Dark pattern (UE Digital Fairness Act, multe 5-10% fatturato; FTC "click-to-cancel", Amazon
  $2,5 mld)**: **vietato** falsa urgenza/scarsità e cancellazione difficile. Da noi: **niente**
  countdown finti; cancellazione **self-service** in un gesto (già così). Persuasione **etica**.

## 4. "Noi mai in perdita" (invarianti di denaro)
- `rimborso_cents ≤ pagato` **sempre** (fail-closed, testato: `test_mai_piu_del_pagato`).
- Non anticipiamo mai denaro: solo instradamento + **escrow** (`fase160`). Host pagato dopo la finestra.
- La penale: host tiene la sua quota proporzionale (`garanzia.chiudi_proporzionale`), noi la commissione;
  il credito anti-rimpianto è **ricavo futuro** (sconto su una NUOVA prenotazione), non un'uscita.

## 5. Psicologia (etica) per parte
- **Cliente**: avversione alla perdita → "non perdi mai i soldi" (credito); badge "cancellazione
  gratuita" abbassa la paura d'impegno (leva #1 di Booking); prezzo trasparente = fiducia.
- **Host**: controllo (sceglie la politica) + incasso garantito sul non-rimborsabile + penale contro i no-show.
- **BookinVIP**: i soldi restano nell'ecosistema (credito), commissione protetta, zero multe (conformi).

## 6. Roadmap (prossimo step)
- **Sconto −12% sul "Non rimborsabile"** dentro il preventivo firmato (`_concierge_quote` /
  concierge.quota): richiede modifica al livello di firma del quote_token per restare coerente e
  onesto (niente sconto finto = niente dark pattern). Non ancora attivato.
- Penalità/ranking per host che cancellano; clausola **forza maggiore** (rimborso pieno) esplicita.

Fonti principali: FTC Junk Fees Rule (ftc.gov), California SB 644, EUR-Lex Dir. 2011/83 art.16 /
CGUE C-96/21, UK Consumer Rights Act 2015, Brasile CDC art.49, EU Digital Fairness Act.
