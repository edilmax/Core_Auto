# 🧪 STATO COLLAUDO — sessione 2026-07-16 (Fable 5)

> ✅ **DEPLOYATO IN PRODUZIONE il 2026-07-16 sera su "pusha" del fondatore** (commit `0f3fb56`,
> 28 fix del giorno inclusi): procedura rm-first, container `app`+`backup` **healthy**, verificato
> vivo (homepage 200 cert ok, `/api/domanda` ok:true, `/api/health` 200, host.html nuovo con
> colonna PIN). Suite 2303 verde al momento del deploy. GitHub allineato (`origin/master`).

**AGGIORNAMENTO (2ª parte sessione, metodo libro sui rami su-richiesta e contestazione): +5 bug VERI
(16-20), tutti con prova dal vivo + fix + test + commit:**
16. `8617e14` decisione approva/rifiuta richiesta NON atomica → approva+rifiuta simultanei = prenotazione
    confermata su date liberate (OVERBOOKING + cliente invitato a pagare stanza inesistente); fix CAS
    `rimuovi_se_stato` (fase162) nei due rami di `_decidi_richiesta`.
17. email esito richiesta: rifiuto = SILENZIO al cliente; scadenza 24h = email-bugia "pagamento non
    riuscito"; fix `_email_esito_richiesta` (onesta, "nessun addebito") + smistamento nello sweep.
18. split parziale controversia: ledger payout restava PIENO → `da_pagare` gonfiato = il bonifico
    manuale pagava all'host anche la quota rimborsata all'ospite; fix `fase131.imposta_importo`.
19. cancellazione con PENALE: quota-penale dell'host decisa dall'escrow ma payout 'trattenuto' pieno e
    NESSUN bonifico mai → l'host non riceveva ciò che gli spetta; fix: escrow chiuso PRIMA, ledger
    riallineato alla quota + transfer (prima di `marca_da_rimborsare`).
20. gara contesta↔auto-rilascio 24h: SELECT in autocommit + UPDATE senza guardia → 'contestato'
    sovrascritto e HOST PAGATO con disputa aperta (3/300 nella sonda); fix CAS per riga in
    `fase160.auto_rilascia`.
21. disputa aperta ma payout 'maturato' → `da_pagare` includeva il conteso (bonifico manuale avrebbe
    pagato l'host con l'arbitro al lavoro); fix: contesta → payout 'trattenuto', risolvi parziale →
    record ricostruito con la quota (`fase131.info`+`registra_maturato`).
22. pagamento tardivo: garanzia restava 'annullato' (escrow morto: conferma/contesta 409, auto-rilascio
    mai, host mai auto-pagato); fix: revive CAS solo-da-annullato in `fase160.apri`.
STADIO FINALE FATTO: fuzzer "1000 menti" esteso (approva/rifiuta/risolvi/expire+sweeper, Connect
finto, +4 invarianti sui bonifici) — **10 seed × 1000 menti = ZERO violazioni**.

**3ª parte (stessa sessione), altri rami del libro — +7 difetti chiusi, suite 2303 verde:**
23. check-in accettato su prenotazione CANCELLATA (ospiti fantasma + sblocco porta futuro) → 409.
24. PIN/codice check-in invisibili nel pannello host (solo nell'email) → /api/host/prenotazioni
    porta codice+pin (rif estratto anche da idem 'reblock:'), colonna in host.html.
25. recensione "verificata" su CANCELLATA dopo la purga 26h (guardia falliva-aperta, classe #95)
    → segnale durevole dal flag `rimborsato` dei movimenti inventario.
26.-27. chiave SBAGLIATA `rilasciato` (fase58 espone `rimborsato`): pannello host mostrava
    "Confermata" anche le rimborsate + le rimborsate bloccavano per sempre alloggio_elimina.
28. referral: soglia `==` esatta → gara webhook (3ª+4ª pagate insieme) = premio €40 perso PER
    SEMPRE → `>=` (il dedup dello store garantisce già l'una-volta-sola).
**4ª parte (sera, dopo il deploy — "testare ancora più a fondo"):**
29. multi-valuta: CREDITO senza valuta → €5 scontavano ¥500 e un Credito Viaggio nato da penale in
    valuta debole si spendeva come €50 su annunci EUR (leak farmabile) → il credito porta la SUA
    valuta (fase158 EUR, anti-rimpianto = valuta della prenotazione, legacy = EUR) e sconta SOLO
    annunci nella stessa valuta. NON ancora deployato (serve nuovo "pusha").
RAMI VERIFICATI SENZA DIFETTI: iCal a fondo (ostile/tetti/import-su-prenotato/roundtrip
cross-canale/2000 eventi in 1s — tutto vivo); attore Telegram (9 test dedicati verdi).
STADIO FINALE ripassato sul codice nuovo: 10 seed × 1000 menti = ZERO violazioni. Suite 2307.
IL LIBRO È COMPLETO: tutti i rami degli attori tracciati (ospite, host, admin, macchina, email,
telegram) + intrecci. 5ª/6ª parte: martello "1000 cose" sui preventivi (988 caotici, 7 invarianti
al centesimo, 0 violazioni → guardia test_quote_coerenza) + MCP fase60 bombardato (0 difetti:
prezzo==concierge, no leak, token manomesso rifiutato, prenota idempotente, dispatcher mai-crash).
Wishlist/fedeltà/deposito/coda/chatbot139 = SPENTI (non cablati: si collaudano quando si accendono).
PROSSIMO: (a) secondo deploy (fix #29 + guardie) al prossimo "pusha"; (b) nuova strategia del
fondatore "gradini G1-G2-G3 + comando di bombardamento" fornito da lui round per round.

**15 bug VERI chiusi** (prova end-to-end + test permanente + commit), tra cui a **perdita reale di denaro**:
rimborso admin che pagava ANCHE l'host, addebito Stripe sempre in EUR su annunci non-EUR, Credito
Fondatore riusabile all'infinito, cancellazione che coniava crediti, ledger tassa che sovra-contava i
rimborsati; + **IDOR/data-leak host** (metriche/export-CSV/calendario di annunci altrui o intera
piattaforma), recensioni finte senza pagare, annuncio sospeso ancora prenotabile, metriche host a €0,
trasparenza commissione fissa, export iCal cross-canale monco, record prenotazione incompleto. Dettaglio
completo (cosa era rotto, come, il fix, il test) in **`REGISTRO_INGEGNERIA.md`** (sezione 1).

**Due strumenti nuovi e permanenti nella suite:**
- 🧠 **`test_menti_invarianti.py`** — fuzzer "1000 menti" (idea del fondatore): agenti-mente con logiche
  diverse eseguono sequenze casuali sulla macchina reale; verifica invarianti globali (no overbooking,
  no doppio-payout, host mai pagato su rimborsati, escrow/tassa/conservazione, single-use credito).
- 🛡️ **`test_robustezza_fuzzing.py`** + **`test_concorrenza_denaro.py`** — nessun endpoint cade su input
  ostile; money-path race-safe sotto carico.

**Metodo "libro" (in corso)**: si tracciano i VIAGGI reali degli attori pagina-per-pagina, leggendo ogni
elemento visibile + tutti i componenti del motore dietro, e si SIMULA per verificare che ogni cosa VIVA e
passi le tappe giuste. GIÀ verificati vivi: ospite (ricerca→dettaglio→prenota→voucher), host
(registra→pubblica→incassa→approva), admin (arbitro/split/sospendi/cancella), spina del denaro
(Stripe→webhook→escrow→Connect), cancellazione→rimborso→storno. **Ripresa**: altri rami (su-richiesta,
contestazione→arbitro, pagamento tardivo). Vedi memory `core-auto-2026-07-16-collaudo`.

---

# ✅ RISOLTO — il sito è ONLINE con HTTPS (aggiornato 2026-07-10)

> `https://bookinvip.com` e `https://www.bookinvip.com` funzionano con il **lucchetto verde** 🔒.
> La lista d'attesa registra le email anche in HTTPS. Il certificato si **rinnova da solo**.

## 🎯 QUAL ERA IL VERO PROBLEMA (dopo giorni di caccia)
Il codice, il server e i dati erano SEMPRE stati a posto. Il vero problema era **uno solo**:
- Il sito girava **solo in HTTP (porta 80)**; la **porta 443 (HTTPS) era spenta** → i browser, che oggi
  pretendono l'HTTPS, non si connettevano e mostravano "errore" (e il vecchio service worker in cache
  faceva apparire "offline").
- **NON era**: né il codice, né la cache, né "Aruba vs Hostinger". I vecchi documenti che parlavano di
  **Aruba 89.46.65.6 erano SBAGLIATI**: quello è un server-fantasma con un Flask morto. Il dominio punta
  al **VPS Hostinger `76.13.44.167`** (`srv1781683.hstgr.cloud`), dove gira davvero l'app.

Perché l'HTTPS non era mai partito: (1) sul VPS c'è solo `docker-compose` **v1.29.2**, ma il file SSL e
lo script `init-letsencrypt.sh` usano i comandi della **v2** (`docker compose`) → davano errore; (2) il
certificato Let's Encrypt esisteva già in `/etc/letsencrypt` ma il file SSL lo cercava in `certbot/conf`.

## 🔧 COSA È STATO FATTO (2026-07-10, direttamente sul VPS)
1. In `docker-compose.casavip.yml`, servizio **nginx**, ora attivi (prima commentati):
   - `- "443:443"`
   - conf: `./deploy/nginx.casavip.ssl.conf:/etc/nginx/conf.d/default.conf:ro`
   - `- /etc/letsencrypt:/etc/letsencrypt:ro`   (il certificato vero)
   - `- ./certbot/www:/var/www/certbot:ro`      (per la sfida di rinnovo)
   - Backup del file originale: `docker-compose.casavip.yml.bak.*` nella stessa cartella.
2. Rinnovo automatico corretto per funzionare con nginx-in-Docker: in
   `/etc/letsencrypt/renewal/bookinvip.com.conf` cambiato `authenticator = nginx` → **`webroot`**
   (webroot = `/var/www/bookinvip/certbot/www`) + `renew_hook = docker exec casavip_nginx nginx -s reload`.
   Collaudato con `certbot renew --dry-run` → **success**. `certbot.timer` è enabled+active.

## ▶️ COME AGGIORNARE IL SITO D'ORA IN POI (procedura SICURA — pattern "rm-first")
Dalla cartella del VPS `/var/www/bookinvip`:
```bash
git pull
docker-compose -f docker-compose.casavip.yml build app
docker-compose -f docker-compose.casavip.yml stop app backup
docker-compose -f docker-compose.casavip.yml rm -f app backup
docker-compose -f docker-compose.casavip.yml up -d
```
> ⚠️ **Se cambia la CONFIG NGINX** (`deploy/nginx.casavip*.conf`) NON basta `git pull` +
> `nginx -s reload`: **fallisce in silenzio**. Docker monta quel file come **singolo file, per
> inode**; `git pull` non lo modifica, lo **sostituisce** (nuovo inode) → il container resta
> agganciato al file VECCHIO. Serve **ricreare il container**:
> ```bash
> docker rm -f casavip_nginx && docker-compose -f docker-compose.casavip.yml up -d
> ```
> (Scoperto il 2026-07-15 aggiungendo la CSP: `nginx -t` diceva OK, il reload pure, ma dentro il
> container la direttiva non c'era. Verificare sempre col container, non col file sul VPS.)
>
> **Perché così:** il `build app` è OBBLIGATORIO se cambia il codice o `deploy/` (il frontend è COPIato
> dentro l'immagine: senza build, il sito resta quello vecchio). Lo `stop`+`rm -f` PRIMA dell'`up`
> evita il bug `KeyError: ContainerConfig` di `docker-compose` v1.29.2 (crasha quando RI-crea container
> con volumi). Solo documentazione cambiata → basta `git pull`.
> ✅ **Verificato 2026-07-15**: la config HTTPS (443 + `nginx.casavip.ssl.conf` + `/etc/letsencrypt` +
> `certbot/www`) è **committata su GitHub** e il VPS non ha modifiche locali (`git diff` vuoto) →
> l'infrastruttura è riproducibile. *(La vecchia nota "l'HTTPS vive solo nel working tree del VPS,
> `git reset --hard` lo cancella" era vera a luglio ma ora è SUPERATA.)*
> A lungo termine resta consigliato installare `docker compose` v2 (elimina i bug di v1.29.2).

## 📌 CONTROLLI RAPIDI (dal proprio PC)
```bash
curl -sS -o /dev/null -w "HTTP %{http_code} cert=%{ssl_verify_result}\n" https://bookinvip.com/   # atteso: HTTP 200 cert=0
curl -sS -X POST https://bookinvip.com/api/domanda -H 'Content-Type: application/json' -d '{"email":"a@b.com","citta":"roma"}'  # atteso: {"ok": true,...}
```

## 🧹 COSE MINORI (non urgenti)
- ~~Container `casavip_backup` risulta **unhealthy**~~ → ✅ **RISOLTO 2026-07-15** (commit `52a6888`):
  il container ereditava l'healthcheck dell'immagine app (porta 8080, dove non gira nessun server).
  Ora ha un healthcheck VERO: ultimo backup in `/data/backup/*.gz` più fresco di 7 ore.
  In prod risulta **healthy**; se torna rosso, i backup sono DAVVERO fermi (non ignorare).
- Server **fantasma Aruba `89.46.65.6`** (Flask/Werkzeug morto): non c'entra col sito. Se lo si paga, si
  può dismettere; se non lo si controlla, ignorarlo.

## 🔑 ACCESSO
- VPS: `ssh root@76.13.44.167` (Hostinger, Ubuntu 24.04). La chiave pubblica `edilmax` (id_ed25519) è
  installata in `/root/.ssh/authorized_keys`. Fallback sempre disponibile: **hPanel Hostinger → VPS →
  Terminale del browser** (root, senza password).
- Fonte di verità funzionalità: `STATO_FINALE.md`. Cose da fare prodotto: `COSE_DA_FARE.md`.
