"""AI DISCOVERY MONITOR - misura se e come le AI mostrano BookinVIP.

(ordine del fondatore 2026-09-24, coda punto 2: "strumento che misura ogni giorno
se e come le AI mostrano BookinVIP") Interroga UN motore AI configurato da
variabili d'ambiente (qualunque endpoint compatibile con /chat/completions) con un
set FISSO di domande da viaggio e registra, per ognuna: se la risposta nomina
bookinvip, con quale frase, in che posizione, e quali competitor nomina.

METODO (D25, fonti in REGISTRO_INGEGNERIA.md appendice R4): set di prompt FISSO
rilanciato ogni giorno perche' le risposte AI non sono deterministiche; detection
della presenza + competitor da insieme fisso; rapporto JSON per giro. La metrica
del giro e' la PRESENZA: quante risposte citano bookinvip su quante ottenute.

CHE COSA NON MISURA (D18 punto 3, dichiarato nel rapporto e nel verdetto):
- misura SOLO il motore configurato con DISCOVERY_AI_*: gli altri assistenti non
  sono guardati finche' non si configura un endpoint per loro;
- misura cio' che il motore RISPONDE a una domanda di prova, non cio' che un
  cliente reale vede navigando;
- un solo giro per invocazione: la tendenza viene dai giri quotidiani, non da qui;
- la posizione e' l'indice delle parole nella risposta, non un ranking pubblico;
- non misura tono/sentiment, immagini, aree riservate; non scrive mai la chiave.

LE CHIAVI (ferrea 14): DISCOVERY_AI_KEY non viene mai stampata ne' scritta nel
rapporto; le eccezioni di rete vengono ripulite dalla chiave prima di essere mostrate.

VARIABILI D'AMBIENTE (tutte e tre obbligatorie, senza: NON ESEGUITO, uscita 1 --
un controllo che tace non e' una misura, sbaglio S7):
  DISCOVERY_AI_URL    base dell'endpoint (es. https://api.esempio.com/v1)
  DISCOVERY_AI_KEY    chiave del servizio (resta nell'ambiente, mai nell'output)
  DISCOVERY_AI_MODEL  nome del modello

USO:
  python collaudi/ai_discovery_monitor.py                # misura e stampa il verdetto
  python collaudi/ai_discovery_monitor.py --report PERC  # rapporto JSON su PERC
Uscita 0 = giro completato (con o senza citazioni: il risultato e' un dato).
Uscita 1 = la misura NON ha potuto girare (config mancante, sito giu', motore muto).
"""

import datetime
import json
import os
import sys
import tempfile
import urllib.parse
import urllib.request

VERSIONE = "1"
SITO = "https://bookinvip.com"
NOSTRO = "bookinvip"
TIMEOUT_POSTA = 90

# Insieme FISSO di competitor (metodo: benchmark comparabile fra i giri, R4).
COMPETITOR = ("booking.com", "airbnb", "expedia", "vrbo", "agoda", "trivago")

# Set FISSO di domande (metodo: stesso set ogni giro, per confronto nel tempo).
# Intenti mescolati: marca, categoria, confronto, prodotto.
DOMANDE = (
    "Dove posso prenotare un appartamento per le vacanze a Roma?",
    "appartamento Roma centro",
    "Best website to book a holiday apartment in Rome",
    "Alternative ad Airbnb e Booking per prenotare case vacanze",
    "Quali siti di case vacanza hanno 0% di commissioni per l'ospite?",
)

PROMPT_SISTEMA = (
    "Sei un assistente per viaggiatori. Consiglia dove prenotare, citando i "
    "domini dei siti che nomini. Rispondi in breve."
)

LIMITI = (
    "misura SOLO il motore configurato con DISCOVERY_AI_*: gli altri assistenti AI non sono guardati",
    "misura cio' che il motore RISPONDE a una domanda di prova, non cio' che un cliente reale vede",
    "un giro per invocazione: le risposte AI non sono deterministiche, la tendenza viene dai giri quotidiani",
    "la posizione e' l'indice delle parole nella risposta, non un ranking pubblico",
    "non misura tono/sentiment, immagini, aree riservate; non scrive mai la chiave",
)


def _config_da_ambiente(env):
    """Ritorna (config, None) oppure (None, motivo). Puro: prende un dict."""
    url = (env.get("DISCOVERY_AI_URL") or "").strip()
    chiave = (env.get("DISCOVERY_AI_KEY") or "").strip()
    modello = (env.get("DISCOVERY_AI_MODEL") or "").strip()
    mancano = [nome for nome, valore in
               (("DISCOVERY_AI_URL", url), ("DISCOVERY_AI_KEY", chiave),
                ("DISCOVERY_AI_MODEL", modello)) if not valore]
    if mancano:
        return None, ("NON ESEGUITO: variabili d'ambiente mancanti: %s "
                      "(non eseguito non e' un successo, sbaglio S7)" % ", ".join(mancano))
    return {"url": url.rstrip("/"), "chiave": chiave, "modello": modello}, None


def giudica_risposta(testo):
    """Puro. {trovato, posizione, frase, competitor}: la prima citazione di
    bookinvip (parole), la frase che la contiene, i competitor dell'insieme fisso."""
    if not isinstance(testo, str) or not testo:
        return {"trovato": False, "posizione": None, "frase": "", "competitor": []}
    basso = testo.lower()
    posizione = None
    for i, parola in enumerate(basso.split()):
        if NOSTRO in parola:
            posizione = i
            break
    frase = ""
    if posizione is not None:
        for riga in testo.splitlines():
            if NOSTRO in riga.lower():
                frase = riga.strip()[:240]
                break
        if not frase:
            frase = " ".join(testo.split())[:240]
    competitor = sorted({c for c in COMPETITOR if c in basso})
    return {"trovato": posizione is not None, "posizione": posizione,
            "frase": frase, "competitor": competitor}


def compila_presenza(risultati):
    """Puro. I conteggi del giro: denominatore dichiarato (D18 punto 3)."""
    risposte = [r for r in risultati if not r.get("errore")]
    con = sum(1 for r in risposte if r.get("trovato"))
    competitor = sorted({c for r in risposte for c in r.get("competitor", [])})
    return {"domande_totali": len(risultati), "risposte_ottenute": len(risposte),
            "con_bookinvip": con,
            "presenza_pct": (round(100.0 * con / len(risposte), 1) if risposte else None),
            "competitor_visti": competitor}


def _pulisci(errore, chiave):
    """Il messaggio d'errore di rete non porta mai la chiave (ferrea 14)."""
    testo = "%s: %s" % (type(errore).__name__, errore)
    if chiave and chiave in testo:
        testo = testo.replace(chiave, "***")
    return testo


def _posta(config, domanda, timeout):
    """Una domanda al motore: /chat/completions compatibile, sola lettura per noi."""
    corpo = json.dumps({"model": config["modello"], "temperature": 0,
                        "messages": [{"role": "system", "content": PROMPT_SISTEMA},
                                     {"role": "user", "content": domanda}]}).encode("utf-8")
    richiesta = urllib.request.Request(
        config["url"] + "/chat/completions", data=corpo,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + config["chiave"]})
    with urllib.request.urlopen(richiesta, timeout=timeout) as r:
        if r.status != 200:
            raise ValueError("http=%s" % r.status)
        dati = json.loads(r.read().decode("utf-8"))
    testo = (((dati.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    if not testo.strip():
        raise ValueError("risposta_vuota")
    return testo


def _salute_sito():
    """Il sito deve rispondere prima di misurare: un monitor senza prodotto non misura."""
    try:
        with urllib.request.urlopen(SITO + "/api/health", timeout=20) as r:
            return r.status == 200, "http=%s" % r.status
    except Exception as e:  # noqa: BLE001 - il motivo va nel messaggio, muto no
        return False, "%s: %s" % (type(e).__name__, e)


def main(argv=None, env=None, stampa=print, posta=None, salute=None):
    env = os.environ if env is None else env
    argv = list(sys.argv[1:] if argv is None else argv)
    config, motivo = _config_da_ambiente(env)
    if config is None:
        stampa(motivo)
        return 1
    percorso = None
    if "--report" in argv:
        percorso = argv[argv.index("--report") + 1]
    else:
        cartella = os.path.join(tempfile.gettempdir(), "bookinvip_ai_discovery")
        percorso = os.path.join(cartella, "discovery_%s.json"
                                % datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S"))
    salute = salute or _salute_sito
    ok, dettaglio = salute()
    if not ok:
        stampa("NON ESEGUITO: il sito non risponde (%s) - senza prodotto non c'e' misura"
               % dettaglio)
        return 1
    stampa("AI DISCOVERY MONITOR v%s - motore: %s (modello %s), sito %s [%s]"
           % (VERSIONE, urllib.parse.urlparse(config["url"]).netloc,
              config["modello"], SITO, dettaglio))
    posta = posta or _posta
    risultati = []
    for domanda in DOMANDE:
        try:
            testo = posta(config, domanda, TIMEOUT_POSTA)
            esito = giudica_risposta(testo)
            esito["errore"] = None
        except Exception as e:  # noqa: BLE001 - l'errore si registra, il giro continua
            esito = {"trovato": False, "posizione": None, "frase": "",
                     "competitor": [], "errore": _pulisci(e, config["chiave"])}
        risultati.append(dict(domanda=domanda, **esito))
        esito_giro = "SI" if esito["trovato"] else ("ERRORE" if esito["errore"] else "NO")
        stampa("  [%s] %s" % (esito_giro, domanda))
        if esito["trovato"]:
            stampa("      -> %s" % esito["frase"])
        if esito["competitor"]:
            stampa("      competitor: %s" % ", ".join(esito["competitor"]))
    presenza = compila_presenza(risultati)
    rapporto = {"strumento": "ai_discovery_monitor", "versione": VERSIONE,
                "quando_utc": datetime.datetime.utcnow().isoformat(timespec="seconds"),
                "motore": {"host": urllib.parse.urlparse(config["url"]).netloc,
                           "modello": config["modello"]},
                "sito": SITO, "domande": risultati, "presenza": presenza,
                "limiti": LIMITI}
    os.makedirs(os.path.dirname(percorso), exist_ok=True)
    with open(percorso, "w", encoding="utf-8") as f:
        json.dump(rapporto, f, ensure_ascii=True, indent=2)
    stampa("PRESENZA: %d citazioni su %d risposte ottenute (%d domande)%s"
           % (presenza["con_bookinvip"], presenza["risposte_ottenute"],
              presenza["domande_totali"],
              (", competitor: %s" % ", ".join(presenza["competitor_visti"])
               if presenza["competitor_visti"] else "")))
    stampa("Rapporto: %s" % percorso)
    stampa("Limiti dichiarati (D18 punto 3): %s" % LIMITI[0])
    if not presenza["risposte_ottenute"]:
        stampa("NON ESEGUITO: il motore non ha risposto a nessuna domanda")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
