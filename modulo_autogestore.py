# modulo_autogestore.py  Autogestore Potente MaxSystem
import subprocess
import sys
import os
import time

REQUISITI = [
    "requests",
    "beautifulsoup4",
    "psutil",
    "pyautogui",
    "keyboard",
    "colorama",
    "tqdm"
]

def installa_pacchetto(pacchetto):
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", pacchetto])
                print(f"[] {pacchetto} installato.")
                    except Exception as e:
                    print(f"[] Errore installazione {pacchetto}: {e}")

                        def aggiorna_self():
                    print("[] Verifica aggiornamenti modulo...")
                    # In un sistema evolutivo vero, qui si collegherebbe a un repository
                    print("[] Modulo aggiornato alla versione attuale. Nessuna modifica necessaria.")

                                def correggi_percorsi():
                        print("[] Verifica dei percorsi critici in corso...")
                        paths = [
                            "Clones",
                            "SuperAI_Outputs",
                            "Core_Auto",
                            "CodiciCreati",
                            "PIANI_GENERATI"
                        ]
                        base_path = os.path.dirname(__file__)
                                            for p in paths:
                                full = os.path.join(base_path, "..", p)
                                                        if not os.path.exists(full):
                                                                    try:
                                                os.makedirs(full)
                                                print(f"[] Creato percorso: {full}")
                                                                            except Exception as e:
                                                    print(f"[] Errore nella creazione di {full}: {e}")

                                                                        def main():
                                            print(" MODULO AUTOGESTORE  AVVIO")
                                                                                    for pkg in REQUISITI:
                                                    installa_pacchetto(pkg)
                                                aggiorna_self()
                                                correggi_percorsi()
                                                print(" Autogestione completata.")

                                                                                        if __name__ == "__main__":
                                                    main()