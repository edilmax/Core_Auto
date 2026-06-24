> 🔄 Aggiornato 2026-06-24 · **BookinVIP** · suite **1740 test** (failures=0) · moduli `faseNN` 13→151 · infra VPS Aruba 89.46.65.6 ATTIVO · fonte di verità: **STATO_FINALE.md**

# REPORT COMPLETO — Stato reale di Core_Auto (verità assoluta)

> Audit onesto, allineato al codice in questo momento. Quello che leggi qui è ciò che ESISTE
> ed è TESTATO, distinguendo sempre "cablato nel prodotto live" da "modulo testato da cablare".

## 0. Riepilogo in 6 righe
- Codice serio = **110 moduli `fase*.py` (13→151) + 131 file di test**; **1740 test, failures=0**
  (i **48 "errors" sono PREESISTENTI** = test che richiedono Postgres/Playwright/credenziali live,
  non regressioni; verificato col baseline).
- Prodotto attuale = **BookinVIP (alloggi)**, brand definitivo, dominio **bookinvip.com**,
  email ufficiale **info@bookinvip.com**.
- **Commissione 15% BLINDATA e cablata** (il vecchio bug "0% incassato ≠ 5% mostrato" è RISOLTO).
- **Spazzatura RIMOSSA** (~1.2 GB di artefatti esperimenti + ~150 `ricombinato_*` già eliminati).
- **Infrastruttura PRONTA**: Docker stdlib + HTTPS Let's Encrypt + rete isolata + autoheal;
  VPS Aruba attivo, DNS agganciato. Manca solo: caricare via SSH e lanciare il container.

---

## 1. Inventario reale della cartella
| Tipo | Quantità | Note |
|---|---|---|
| Moduli `fase*.py` | **110** (13→151) | il sistema vero, ognuno documentato + testato |
| Test `test_*.py` | **131** | **1740 test**, failures=0, errors=48 preesistenti |
| Documenti `.md` | 15 | report, guide, manuali, masterplan, legale |
| `deploy/` | vetrina, host, admin, voucher, PWA, nginx (HTTP+SSL), Docker, init-LE, backup |
| `legale/` | privacy policy + termini di servizio |
| `app.py`, `gunicorn.conf.py`, `assistente_gestionale.py` | core legacy Flask/ricerca (tenuti: coperti da test) |
| Spazzatura | **0** | rimossa il 2026-06-24 (AI_Recombined ~1.2GB, Quantum_*, forensic, ecc.) |

---

## 2. I 4 "MONDI" nel codice
### A) Fondamenta CORE_AUTO (fase 13–33) + marketplace fortress (app.py)
Cassaforte transazionale (money centesimi-interi, idempotency, outbox, datastore PG-ready) +
cervello IA conversazionale (client LLM, multi-turno, governatore costi, memoria durevole) +
canali social. **Testato; non cablato a BookinVIP** (l'agente social usa un LLM a pagamento).

### B) Tavola VIP — booking ristoranti (fase 34–42)
Stack "prenota un tavolo" (prenotazioni, pagamenti PSP+webhook, notifiche, backup, admin Flask).
**Superato dal lodging; testato.** I 48 errors preesistenti vengono in gran parte da qui (Flask/PG).

### C) Funnel Mango — acquisizione B2B autonoma (fase 43–56)
Esplora host, calcola le perdite OTA, contatta, converte. **Spento di default**, testato.

### D) BookinVIP — PRODOTTO ATTUALE (alloggi, fase 57–151) ✅
Il prodotto vivo + tutta l'evoluzione recente. Dettaglio in §3.

---

## 3. BookinVIP — cosa c'è (fase 57–151)
**Core prodotto (cablato in fase81/fase83 → live):** 57 vetrina · 58 inventario realtime
anti-overbooking · 59 concierge prezzo-firmato (host-aware) · 60 MCP agenti IA · 61 i18n 5 lingue ·
63 recensioni verificate · 64 smart-pass/self check-in · 69 trasparenza vs OTA · 76 viral loop ·
80 sentinel · 81 bootstrap/composition-root · 82 iCal · 83 server HTTP+frontend.

**Money-path (gated da env):** 85 Stripe link · 86 email voucher · 87 webhook Stripe ·
101 Stripe Connect split-all'origine (85% host / 15% noi, `on_behalf_of`) · 99 multi-currency
like-for-like anti-DCC · 104 gateway Asia Alipay/WeChat.

**14 motori "geniali" — CABLATI nel sistema (fase81):** 62 no-show, 65 split-payment,
66 tassa soggiorno, 67 coda, 70 turnover, 72 digital-twin, 74 sensory, 75 guardian, 78 sleep,
79 dichiarazione (+ 68 niche, 71 commitment, 77 portability = librerie pure). Endpoint live:
`/api/tassa`, `/api/split/*`.

**Architettura fiscale/commissioni (configurabile, da confermare col commercialista):**
98 policy commissione (primi-1000-host + split 3% host/12% ospite = 15%) · 100 DAC7 gate ·
103 reverse-charge (autofattura TD17/18 + F24) · 147 tassa comunale · 151 Alloggiati Web Questura.

**Acquisizione host (legale, gratis):** 89 outreach compliant (gate giurisdizioni + opt-out) ·
96 lead discovery mondiale da OpenStreetMap (no proxy/scraping) · 97 inbound SEO/AEO
(`/affitta/<città>`, `llms.txt`, sitemap) · 90/91/92/93 marketing + canali Telegram/Meta/X/TikTok ·
94 scheduler campagna · 95 outreach durevole + `/stop` · 109 referral host-porta-host.

**Operatività host/guest (moduli testati, alcuni via endpoint, altri da cablare alla UI):**
73 firma agile · 105 W3C identity gate · 106 dynamic pricing · 107 i18n traduzione annunci ·
111 cancellazione/rimborso · 113 messaggistica · 115 dashboard metriche · 117 wishlist ·
119 calendario prezzi · 121 geo-ricerca/mappa · 123 web push · 125 confronto OTA guest ·
127 check-in digitale · 129 traduzione recensioni · 131 payout dashboard · 133 split quote uguali ·
135 iCal bidirezionale · 137 fedeltà guest · 139 chatbot pre-prenotazione (prezzo sempre dal CORE) ·
141 onboarding wizard · 143 KYC host · 145 contratto PDF · 149 deposito cauzionale.

> Onestà: il **core + money-path + 14 motori** sono cablati nel sistema (fase81). I moduli
> operativi 105→151 sono **costruiti e testati**; parte è esposta via endpoint/server, parte è
> da agganciare al frontend (lavoro di integrazione, non d'invenzione).

---

## 4. PARAMETRI che governano i soldi (valori reali ORA)
| Cosa | Dove | Valore | Note |
|---|---|---|---|
| **Commissione CORE** | fase81/59/98 | **15%** (1500 bps) BLINDATO | default + env `COMMISSIONE_BPS`; primi-1000-host |
| Split asimmetrico | fase98 | host **3%** + ospite **12%** = 15% | conservazione esatta cents |
| Stripe Connect | fase101 | destination charge, `on_behalf_of` | 85% host, application_fee 15% |
| Commissione OTA (confronto) | fase69 | 15% nostra vs ~18–25% OTA | benchmark |
| Denaro | ovunque | **centesimi interi per valuta** | mai float (fase99) |
| Tassa soggiorno | fase66/147 | **0** default, per-comune | jurisdiction-agnostic |
| Check-in/out | fase64 | 15:00 / 11:00 | smart-pass |
| Token host | fase88 | 30 gg, PBKDF2 200k | self-service + contatore primi-1000 |

---

## 5. Infrastruttura & lancio (stato reale)
- **Docker**: `Dockerfile`(= casavip) python:3.11-slim, **zero dipendenze** (stdlib), non-root,
  TUTTI i dati durevoli su volume `/data`, healthcheck `/api/health`.
- **HTTPS**: `docker-compose.casavip.ssl.yml` + `init-letsencrypt.sh` (1 comando, auto-renew),
  app dietro nginx su rete docker **isolated**, **autoheal** reale, backup ogni 6h.
- **VPS Aruba O2A4** (4GB, Docker) **ATTIVO** — IP **89.46.65.6**; **DNS Hostinger** record A
  agganciato (TTL 14400); **.env.casavip** compilato (P.IVA 11795700969, IBAN, Stripe live) —
  git-ignored, segreti MAI nel repo.
- **PROSSIMO PASSO**: caricare la cartella via **SSH** + `./deploy/init-letsencrypt.sh` +
  `docker compose -f docker-compose.casavip.ssl.yml up -d --build`.

---

## 6. Verdetto onesto
1. **BookinVIP è reale, completo e testato** sul nucleo (cerca→prenota→paga→voucher→check-in→
   recensione) + self-service host + money-path Stripe Connect multivaluta.
2. **Architettura finanziaria/fiscale** costruita e testata (split 3/12, multi-currency anti-DCC,
   DAC7, reverse-charge, tassa comunale, Alloggiati Web) — numeri fiscali da confermare col commercialista.
3. **Acquisizione legale** pronta (lead OSM + inbound SEO/AEO + outreach compliant).
4. **Il vecchio bug commissione è RISOLTO**; la spazzatura è RIMOSSA; i doc sono allineati.
5. Cosa resta = **non-codice**: SSH+deploy del container, conferma fiscale, **ruotare la Stripe
   secret key** (transitata in chat), e l'integrazione UI dei moduli operativi 105→151.
