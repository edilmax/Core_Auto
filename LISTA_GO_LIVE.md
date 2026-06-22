# BookinVIP — Lista per andare LIVE

Tutto ciò che serve procurare. Il **software è gratis e pronto** (1365 test, tag
v1.0-bookinvip). Qui sotto solo le cose che dipendono da te.

## 1. DOMINIO  ✅ (lo hai: bookinvip.com)
- [ ] Possiedi `bookinvip.com` presso un registrar (Namecheck/GoDaddy/Aruba…). ~€10/anno.
- [ ] Punterai un **record A** all'IP del VPS (si fa al passo deploy).

## 2. SERVER (VPS) — ~€5/mese
- [ ] Un VPS piccolo basta (l'app è stdlib, leggerissima): **1–2 GB RAM**.
      Esempi: Hetzner (~€4), Contabo, DigitalOcean (~€6).
- [ ] Con **Docker + Docker Compose** installati.
- Costo: ~€4–6/mese. **Unica spesa fissa reale.**

## 3. EMAIL — quante e quali
Serve **1 casella professionale** sul dominio (per inviare i voucher e ricevere
contatti). Con una casella + alias copri tutto.
- [ ] **1 mailbox reale** su `@bookinvip.com` (Google Workspace ~€5/mese, **Zoho Mail
      gratis** fino a pochi utenti, o quella inclusa col dominio).
- Indirizzi consigliati (bastano alias sulla stessa casella):
  - [ ] `no-reply@bookinvip.com` → **mittente automatico dei voucher** (va in EMAIL_MITTENTE)
  - [ ] `info@bookinvip.com` (o `hello@`) → contatto pubblico / supporto
  - [ ] `admin@bookinvip.com` → tuo, per avvisi/gestione
- Dal provider email prendi: **SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD**
  → li metti nel `.env` e le email partono da sole.
- **Quante servono davvero: 1** (mailbox) + 2-3 alias gratuiti. Costo: **€0–5/mese**.

## 4. PAGAMENTI (Stripe) — il pezzo del denaro
- [ ] Crea un account **Stripe** (gratis: stripe.com).
- Per attivarlo Stripe chiede (verifica identità business):
  - [ ] Dati anagrafici / ragione sociale
  - [ ] Indirizzo
  - [ ] **IBAN** del conto su cui Stripe ti versa l'incassato  ← **questo è il tuo IBAN**
  - [ ] Spesso: **Partita IVA** / codice fiscale (vedi punto 6)
  - [ ] Un documento d'identità
- Da Stripe prendi e metti nel `.env`:
  - [ ] **STRIPE_SECRET_KEY** (`sk_live_...`)
  - [ ] **STRIPE_WEBHOOK_SECRET** (`whsec_...`) → creando un webhook verso
        `https://bookinvip.com/api/payments/webhook` (evento `checkout.session.completed`)
- **Costo Stripe**: ~**1.4% + €0.25** per carta europea (è l'unica commissione reale;
  il "zero spese" vale per il nostro software, non per la fee del circuito pagamenti).

### ⚠️ Nota importante sui soldi (onesta)
Oggi l'incasso va sul **TUO** account Stripe (sul TUO IBAN). Il sistema **calcola** la
quota dell'host (split a 3 vie), ma **non la versa in automatico** all'host: in V1 paghi
tu l'host (bonifico) o, più avanti, si attiva **Stripe Connect** (ogni host registra il
**proprio IBAN** e Stripe paga lui direttamente). Per partire: basta il TUO IBAN.

## 5. SSL / HTTPS — GRATIS
- [ ] Let's Encrypt via certbot (già nel deploy). **€0.** Solo da attivare.

## 6. LEGALE / FISCALE — necessario per incassare sul serio
- [ ] **Partita IVA** / forma giuridica (per usare Stripe come business e fatturare).
      Consiglio: parlane con un commercialista (regime, sede fiscale — ricorda la
      direttiva jurisdiction-agnostic: la tassa è un parametro, default 0).
- [ ] **Privacy Policy** + **Termini di Servizio** (GDPR: tratti dati di ospiti e host).
- [ ] **Cookie/Storage policy** (l'app usa poco storage locale; serve comunque la nota).
- [ ] (Per gli host) eventuale registrazione ospiti / tassa di soggiorno = responsabilità
      dell'host; il sistema la calcola, ma l'obbligo è suo.

## 7. SOCIAL  ✅ (fatti)
- [x] YouTube `@bookinvip` · Instagram `bookinvip` · TikTok `@bookinvip` · X `@bookinvip`
- [ ] Cambia la password che avevi condiviso in chat (è da considerare compromessa).

---

## RIEPILOGO COSTI (per partire)
| Voce | Costo | Obbligatorio? |
|---|---|---|
| Dominio bookinvip.com | ~€10/anno | sì (lo hai) |
| VPS | ~€5/mese | sì |
| Email professionale | €0–5/mese | sì (1 casella) |
| Stripe | €0 + 1.4%+€0.25/transazione | sì (per incassare) |
| SSL | €0 | sì |
| Partita IVA / legale | variabile (commercialista) | sì (per operare) |
| Social | €0 | fatto |

**Spesa fissa minima: ~€5–10/mese** (VPS + email). Il resto è per-transazione (Stripe).

## ORDINE CONSIGLIATO (cosa fare prima)
1. VPS + DNS (`bookinvip.com` → IP).
2. `docker compose -f docker-compose.casavip.yml up -d --build` + certbot (HTTPS).
3. Email professionale → metti `SMTP_*` nel `.env.casavip`.
4. Stripe (IBAN + identità) → metti `STRIPE_SECRET_KEY` + crea webhook → `STRIPE_WEBHOOK_SECRET`.
5. Partita IVA + privacy/termini (in parallelo, col commercialista).
6. Test reale: una prenotazione di prova con carta test Stripe, poi live.
