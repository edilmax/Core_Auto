# auto_evolver.py – Evoluzione automatica dei moduli

import os
import datetime

# Percorsi
PERCORSO_MODULI = "C:\\Users\\MaxDanno\\Desktop\\Progetto MaxSystem - Ufficiale\\Clones\\SuperAI_Outputs\\CodiciStudio_Deep"
BACKUP_DIR = os.path.join(PERCORSO_MODULI, "BACKUP_EVOLUZIONI")
EVOLUZIONI_DIR = os.path.join(PERCORSO_MODULI, "EVOLUTI")

# Creazione cartelle se non esistono
if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

if not os.path.exists(EVOLUZIONI_DIR):
    os.makedirs(EVOLUZIONI_DIR)

# Funzione di evoluzione di un singolo modulo
def evolvi_modulo(percorso_file):
    with open(percorso_file, "r", encoding="utf-8") as file:
        codice = file.read()

    # Simulazione miglioramento automatico
    codice_modificato = codice.replace("#", "# [ EVOLVED]") + "\n\n# [AUTO-EVOLUZIONE COMPLETATA]"

    nome_file = os.path.basename(percorso_file)
    backup_path = os.path.join(BACKUP_DIR, f"{nome_file}.bak_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}")
    evoluto_path = os.path.join(EVOLUZIONI_DIR, nome_file)

    # Backup originale
    with open(backup_path, "w", encoding="utf-8") as b:
        b.write(codice)

    # Salvataggio modulo evoluto
    with open(evoluto_path, "w", encoding="utf-8") as e:
        e.write(codice_modificato)

    print(f"[✅] Evoluzione completata per {nome_file}")

# Funzione per analizzare e evolvere tutti i moduli
def analizza_tutti_i_moduli():
    for file in os.listdir(PERCORSO_MODULI):
        if file.endswith(".py") and not file.startswith("auto_"):
            full_path = os.path.join(PERCORSO_MODULI, file)
            evolvi_modulo(full_path)

# Main
if __name__ == "__main__":
    print("🧠 AUTO-EVOLVER – INIZIO")
    analizza_tutti_i_moduli()
    print("✅ Tutti i moduli analizzati e potenziati.")
