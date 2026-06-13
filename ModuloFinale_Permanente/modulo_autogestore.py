# modulo_autogestore.py  Modulo Autogestore MAXSYSTEM
import subprocess
import sys
import os
import pkg_resources
import time

LIBRERIE_RICHIESTE = ["requests", "beautifulsoup4", "openai", "pyyaml", "psutil"]

def installa_libreria(nome):
        try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", nome])
                print(f"[] Modulo installato: {nome}")
            except Exception as e:
                    print(f"[] Errore installazione {nome}: {e}")
            
            def controlla_e_installa():
                    print("[] Controllo dipendenze...")
                    installate = {pkg.key for pkg in pkg_resources.working_set}
                    for lib in LIBRERIE_RICHIESTE:
                            if lib.lower() not in installate:
                                    print(f"[] {lib} mancante  installazione in corso...")
                                    installa_libreria(lib)
                                else:
                                        print(f"[] {lib} OK")
                            
                            def aggiorna_script():
                                    print("[] Controllo aggiornamenti script...")
                                    # In futuro: download da repo privata o server sicuro
                                    print("[] Sistema aggiornato localmente. (fittizio per ora)")
                                
                                def main():
                                        print(" MODULO AUTOGESTORE  MAXSYSTEM")
                                        controlla_e_installa()
                                        aggiorna_script()
                                        print("[] Autogestione completata.")
                                        time.sleep(1)
                                    
                                    if __name__ == "__main__":
                                            main()