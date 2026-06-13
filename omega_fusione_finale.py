# omega_fusione_finale.py  Fusione Suprema dei Moduli OMEGA
import subprocess
import os
import time

BASE = r"C:\Users\MaxDanno\Desktop\Progetto MaxSystem - Ufficiale\Clones\SuperAI_Outputs\Core_Auto\ModuloFinale_Permanente"

MODULI_OMEGA = [
    "modulo_autogestore.py",
    "modulo_ricognitore.py",
    "modulo_reattivo.py",
    "modulo_difensivo.py"
]

def esegui(nome_file):
        path = os.path.join(BASE, nome_file)
            if os.path.exists(path):
                print(f"[] Eseguo: {nome_file}")
                subprocess.run(["python", path])
                    else:
                    print(f"[] Modulo mancante: {nome_file}")

                        def main():
                    print(" ATTIVAZIONE COMPLETA  MODALIT OMEGA")
                                    for modulo in MODULI_OMEGA:
                            esegui(modulo)
                            time.sleep(1)

                        print(" MaxSystem OMEGA  ora AUTO-PROTETTO, AUTO-EVOLUTIVO e SUPREMO.")

                                        if __name__ == "__main__":
                            main()