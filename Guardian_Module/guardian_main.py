# guardian_main.py  Modulo Guardian MAXSYSTEM
import time
import os
import platform

def esegui_controlli_sicurezza():
        print(" GUARDIAN MODULE  SICUREZZA ATTIVA")
        print("[] Verifica integrit moduli critici...")
        moduli = [
            "auto_evolver.py", "auto_pianificatore.py", "modulo_autogestore.py",
            "modulo_ricognitore.py", "modulo_reattivo.py", "modulo_difensivo.py",
            "super_executive.py"
        ]
        base = os.path.dirname(__file__)
        for modulo in moduli:
                path = os.path.join(base, "..", modulo)
                if os.path.exists(path):
                        print(f"[] Trovato: {modulo}")
                    else:
                            print(f"[] MANCANTE: {modulo}")
                
                    print("[] Analisi sistema operativo:")
                    print(f" Sistema: {platform.system()}  Versione: {platform.version()}")
                
                    print("[] Guardian completato.\n")
                
                if __name__ == "__main__":
                        esegui_controlli_sicurezza()