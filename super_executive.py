# super_executive.py  Direttore Supremo MaxSystem
import subprocess
import os
import time

MODULI_DA_ESEGUIRE = [
    r"C:\Users\MaxDanno\Desktop\Progetto MaxSystem - Ufficiale\Clones\SuperAI_Outputs\Core_Auto\auto_evolver.py",
    r"C:\Users\MaxDanno\Desktop\Progetto MaxSystem - Ufficiale\Clones\SuperAI_Outputs\Core_Auto\auto_pianificatore.py",
    r"C:\Users\MaxDanno\Desktop\Progetto MaxSystem - Ufficiale\Clones\SuperAI_Outputs\Core_Auto\super_linker.py",
    r"C:\Users\MaxDanno\Desktop\Progetto MaxSystem - Ufficiale\Clones\SuperAI_Outputs\CodiciStudio_Deep\interprete_comandi_liberi.py",
    r"C:\Users\MaxDanno\Desktop\Progetto MaxSystem - Ufficiale\Clones\SuperAI_Outputs\CodiciStudio_Deep\super_ai_creator.py",
    r"C:\Users\MaxDanno\Desktop\Progetto MaxSystem - Ufficiale\Clones\SuperAI_Outputs\CodiciStudio_Deep\pilotaggio_totale.py",
    r"C:\Users\MaxDanno\Desktop\Progetto MaxSystem - Ufficiale\Clones\SuperAI_Outputs\CodiciStudio_Deep\darknet_scanner.py",
    r"C:\Users\MaxDanno\Desktop\Progetto MaxSystem - Ufficiale\Clones\SuperAI_Outputs\CodiciStudio_Deep\memoria_permanente.py"
]

def esegui_modulo(percorso):
            if os.path.exists(percorso):
                nome_file = os.path.basename(percorso)
                print(f"[] Avvio modulo: {nome_file}")
                subprocess.run(["python", percorso])
                    else:
                    print(f"[] Modulo non trovato: {percorso}")

                        def main():
                    print(" SUPER EXECUTIVE  DIRETTORE SUPREMO ATTIVO")
                                    for modulo in MODULI_DA_ESEGUIRE:
                            esegui_modulo(modulo)
                            time.sleep(1)

                        print(" Tutti i moduli principali sono stati eseguiti.")
                        input(" Premi INVIO per terminare.")

                                        if __name__ == "__main__":
                            main()