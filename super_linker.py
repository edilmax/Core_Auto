# super_linker.py – Collegamento neurale supremo tra moduli

import os
import importlib.util
import datetime

MODULI_DIR = "C:\\Users\\MaxDanno\\Desktop\\Progetto MaxSystem - Ufficiale\\Clones\\SuperAI_Outputs\\Core_Auto"
LOG_PATH = os.path.join(MODULI_DIR, "log_linker.txt")
PIANI_GENERATI = os.path.join(MODULI_DIR, "PIANI_GENERATI")

if not os.path.exists(PIANI_GENERATI):
    os.makedirs(PIANI_GENERATI)

def log(msg):
    timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} {msg}\n")
    print(msg)

def carica_modulo(path):
    try:
        nome = os.path.basename(path).replace(".py", "")
        spec = importlib.util.spec_from_file_location(nome, path)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return nome, True
    except Exception as e:
        log(f"[❌] Errore in {path}: {e}")
        return path, False

def collega_moduli():
    log("🧠 INIZIO COLLEGAMENTO NEURALE DEI MODULI...")
    moduli = [f for f in os.listdir(MODULI_DIR) if f.endswith(".py") and f != "super_linker.py"]
    totali = len(moduli)
    riusciti = 0

    for m in moduli:
        path = os.path.join(MODULI_DIR, m)
        nome, ok = carica_modulo(path)
        if ok:
            log(f"[✅] Collegato: {nome}")
            riusciti += 1
        else:
            log(f"[❌] Fallito: {nome}")

    log(f"[ℹ️] Moduli totali: {totali} | Collegati: {riusciti}")
    return riusciti

def salva_piano_finale():
    file = os.path.join(PIANI_GENERATI, f"piano_fusione_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    with open(file, "w", encoding="utf-8") as f:
        f.write("🧠 COLLEGAMENTO NEURALE COMPLETO\n")
        f.write("Moduli connessi tra loro per attivazione sinergica.\n")
        f.write(f"Data: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    log(f"[✅] Piano salvato in: {file}")

if __name__ == "__main__":
    log("🧠 SUPER LINKER – AVVIO")
    tot = collega_moduli()
    salva_piano_finale()
    log("✅ SUPER LINKER COMPLETATO.")
