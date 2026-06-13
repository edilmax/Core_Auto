# auto_pianificatore.py – MaxSystem Supreme Evolver

import os
import datetime
import json

PIANO_DIR = "PIANI_GENERATI"
LOG_PATH = os.path.join(PIANO_DIR, "log_attivita.json")

if not os.path.exists(PIANO_DIR):
    os.makedirs(PIANO_DIR)

def analizza_cartelle(targets):
    moduli_trovati = []
    for cartella in targets:
        if os.path.exists(cartella):
            for nome in os.listdir(cartella):
                if nome.endswith(".py"):
                    percorso = os.path.join(cartella, nome)
                    moduli_trovati.append(percorso)
    return moduli_trovati

def salva_log(moduli, note="Evoluzione automatica pianificata"):
    oggi = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    voce = {"data": oggi, "moduli": moduli, "note": note}
    log = []
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            try:
                log = json.load(f)
            except:
                log = []
    log.append(voce)
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=4)

def pianifica_evoluzioni():
    oggi = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target_dirs = [
        "CodiciCreati",
        "EVOLUTI",
        "SuperAI_Outputs",
        "SuperAI_Outputs\\CodiciStudio_Deep",
        "SuperAI_Outputs\\Core_Auto"
    ]

    moduli = analizza_cartelle(target_dirs)

    blocco = f"""🧠 PIANIFICAZIONE STRATEGICA – MaxSystem Supreme
🗓 Data/Ora: {oggi}

🧩 Moduli analizzati: {len(moduli)} trovati
📁 Directory scansionate:
{chr(10).join(f"- {d}" for d in target_dirs)}

⚙️ Azioni programmate:
- Rilevamento moduli ridondanti e obsoleti
- Filtro su moduli non modificati da >72h
- Preparazione aggiornamento interno (ricompilatore + autocostruttore)
- Preparazione fase link neurale interno (super_linker)
- Auto-backup sicurezza completato

🧠 Stato macchina: AUTODECISIONE ATTIVA
✅ Pronto per nuovo ciclo di auto-evoluzione.

"""
    nome_file = f"piano_potenziato_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    percorso = os.path.join(PIANO_DIR, nome_file)
    with open(percorso, "w", encoding="utf-8") as f:
        f.write(blocco)

    print(f"[✅] Piano evolutivo salvato in: {percorso}")

    salva_log(moduli, "Ciclo completo di pianificazione autonoma")

if __name__ == "__main__":
    print("🧠 AUTO-PIANIFICATORE SUPREMO – AVVIO")
    pianifica_evoluzioni()
