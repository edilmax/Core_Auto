> 🔄 Aggiornato 2026-06-29 · **BookinVIP** · suite **1850 test** (0 regressioni) · moduli `faseNN`→160 · infra VPS Aruba 89.46.65.6 ATTIVO · fonte di verità: **STATO_FINALE.md**

# LIBRO OPERATIVO TOTALE: CORE_AUTO (Fase 56)

> ⚠️ **DOCUMENTO STORICO / NON ATTUALE.** Le cartelle citate (AI_Recombined, Guardian_Module,
> Quantum_Security_Engine) **non esistono** nel prodotto attuale. BookinVIP è server stdlib
> (`main_casavip.py` → `fase83_server`), moduli `faseNN` 57→158. Stato reale: **`STATO_FINALE.md`**.

## 1. VISIONE D'INSIEME (Architettura)
- .github/workflows/: Automazione sicurezza e test (CI/CD).
- AI_Recombined/: Il cervello logico. Gestisce le decisioni e i calcoli finanziari basati su centesimi interi (cents) per evitare errori di arrotondamento.
- Guardian_Module/: Il sistema di difesa attivo. Monitora costantemente i flussi in ingresso e blocca intrusioni o dati non conformi.
- Quantum_Security_Engine/: La cassaforte. Gestisce le firme digitali (X-Client-Key) e l'autenticazione per ogni comunicazione esterna.
- deploy/: Il quadro comandi. Contiene le configurazioni Docker, Nginx e le impostazioni per l'avvio dell'infrastruttura sul server.

## 2. MANUALE DI INTERVENTO (Operatività Pratica)
- Se il sistema è bloccato: Controlla i log in /Guardian_Module. È lì che il sistema registra perché ha chiuso le porte o rifiutato una connessione.
- Se devi cambiare una regola (prezzi/contratti): Intervieni solo in /AI_Recombined, dove risiede la logica di calcolo.
- Se devi collegare servizi esterni (Social/API): Usa le chiavi crittografiche salvate in /Quantum_Security_Engine.
- Se devi cambiare dominio o server: Modifica i parametri di rete e le variabili d'ambiente in /deploy.

## 3. PIANO D'AZIONE (Test Privato)
1. Non andare online subito. Crea una cartella esterna denominata 'TEST_DATI'.
2. Inserisci i tuoi file JSON di test all'interno di questa cartella.
3. Il sistema (Gateway) leggerà i file e li elaborerà in locale come se fossero reali.
4. Quando tutto è perfetto, usa i comandi in /deploy per puntare il dominio al server, ma utilizza una regola firewall per accettare solo il tuo indirizzo IP (Whitelist).

## 4. INTEGRITÀ E BACKUP
- Codice sorgente: https://github.com/edilmax/Core_Auto
- Backup fisico: Copia l'intera cartella 'Core_Auto' su chiavetta USB ogni settimana.
- Stato: Fase 56 (Sigillata).
