# 🔴 RIPRENDI QUI — punto di ripristino deploy (aggiornato 2026-07-10)

> Se ci si interrompe (riavvio PC, ecc.), si riparte da questo file. Tutto il codice è su GitHub
> (`edilmax/Core_Auto`, branch `master`, ultimo commit **ec8f1b6**). **Niente è perso.**

## ✅ VERITÀ FONDAMENTALE: il codice e il server FUNZIONANO
Verificato più volte sul VPS:
- `curl -sS -X POST http://localhost/api/domanda -H 'Content-Type: application/json' -d '{"email":"a@b.com","citta":"pavia"}'` → **`{"ok": true, ...}`** (la lista d'attesa registra le email).
- `curl -s http://localhost/ | grep -i inserisci` → mostra il codice NUOVO (`'Inserisci la tua email.'`), quindi **il server serve la versione aggiornata**.

**Il problema NON è mai stato il codice.** Erano problemi di **deploy/infrastruttura** e di **cache del browser**.

## 🧩 I VERI PROBLEMI TROVATI E RISOLTI (perché "prima andava e adesso no" per 10 giorni)
1. **`docker-compose` v1 rifiutava il compose** per la chiave `name: casavip` (solo v2) → ogni `up --build` falliva in silenzio, restava il container vecchio. → FIX: `version: "2.4"` (commit af5d0cb).
2. **`.dockerignore` escludeva `deploy/`** → la build falliva a `COPY deploy ./deploy`. → FIX: rimosso `deploy/` dal .dockerignore (commit c9f2fd5).
3. **`docker-compose v1.29.2` bug `KeyError: 'ContainerConfig'`** nel RI-creare container con volumi. → WORKAROUND: rimuovere TUTTI i container e poi `up` (li crea da zero). Comando:
   `docker ps -aq --filter name=casavip | xargs -r docker rm -f`
4. **Processo Python FANTASMA sull'host** (`PID 41091`, `127.0.0.1:8080`) con codice vecchio, avviato a mano fuori Docker → ogni `curl 127.0.0.1:8080` colpiva LUI, non il container. Il vero test è via nginx: `curl http://localhost/...` (porta 80). → DA FARE: `kill 41091` (poi verifica con `ss -ltnp | grep :8080`).
5. **Service worker (PWA) serviva la index.html vecchia dalla cache** → il browser mostrava messaggi obsoleti. → FIX: `sw.js` reso "kill-switch" senza reload (commit ec8f1b6), `index.html` non registra più SW + validazione email permissiva (basta `@`, decide il server).

## ⛔ ULTIMO OSTACOLO (dove eravamo bloccati)
Il **browser del fondatore** ha ancora attivo il **vecchio service worker** (quello che risponde `{"errore":"offline"}` quando la fetch fallisce → in pagina appare "Errore server: offline") e la **index.html vecchia in cache**. Il SERVER è giusto; è solo il browser che tiene la roba vecchia.

## ▶️ COSA FARE PER FINIRE (in ordine, quando si riprende)
1. **VPS — assicura deploy aggiornato + pulisci il fantasma:**
   ```bash
   cd /var/www/bookinvip
   git fetch origin && git reset --hard origin/master
   kill 41091 2>/dev/null; docker ps -aq --filter name=casavip | xargs -r docker rm -f
   docker-compose -f docker-compose.casavip.yml up -d --build
   ```
   (se `kill 41091` dà "no such process", trova il nuovo PID con `ss -ltnp | grep :8080` e killa quello)
2. **VPS — conferma che funziona (deve dare `{"ok": true...}`):**
   ```bash
   curl -sS -X POST http://localhost/api/domanda -H 'Content-Type: application/json' -d '{"email":"a@b.com","citta":"roma"}'; echo
   ```
3. **BROWSER — sblocca la cache (UNA volta):** apri il sito in **INCOGNITO** → scrivi email → "Avvisami" → deve uscire il **✅ verde**. Sul browser normale: F12 → Application → Clear site data (oppure telefono: impostazioni sito → Cancella dati).
4. Se in incognito appare ANCORA "offline": la fetch `/api/domanda` dal browser fallisce → controllare che nginx instradi `/api/` verso l'app anche per il dominio pubblico (non solo `localhost`). Vedi `deploy/nginx.casavip.conf` (già corretto: `location /` → `proxy_pass http://casavip_app` su `app:8080`).

## 📌 NOTE
- Comando aggiornamento VPS d'ora in poi: `cd /var/www/bookinvip && git pull && docker-compose -f docker-compose.casavip.yml up -d --build` (se dà `KeyError ContainerConfig`, prima `docker ps -aq --filter name=casavip | xargs -r docker rm -f`).
- Consiglio permanente: installare `docker compose` v2 (elimina i bug di v1.29.2):
  `sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 -o /usr/local/bin/docker-compose && sudo chmod +x /usr/local/bin/docker-compose && hash -r`
- Fonte di verità funzionalità: `STATO_FINALE.md`. Cose da fare prodotto: `COSE_DA_FARE.md`.
