# attivatore_totale_automatico.py  MaxSystem FINAL CORE
import subprocess
import os
import datetime

MODULI = [
    "modulo_autogestore.py",
    "modulo_ricognitore.py",
    "modulo_reattivo.py",
    "modulo_difensivo.py",
    "modulo_generator.py",
    "modulo_replicante_nucleare.py",
    "omega_fusione_finale.py"
]

LOG_DIR = "LOGS_ATTIVAZIONE"
if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    
    def avvia_modulo(file):
            path = os.path.join(os.getcwd(), file)
            if os.path.exists(path):
                    try:
                            subprocess.run(["python", path], check=True)
                            return f"[] Avviato: {file}"
                        except Exception as e:
                                return f"[] Errore in {file}: {e}"
                        else:
                                return f"[] Modulo mancante: {file}"
                        
                        def avvia_tutti():
                                print(" ATTIVATORE TOTALE  MAXSYSTEM")
                                log = []
                                for modulo in MODULI:
                                        risultato = avvia_modulo(modulo)
                                        print(risultato)
                                        log.append(risultato)
                                
                                    nome_log = f"log_attivazione_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                                    with open(os.path.join(LOG_DIR, nome_log), "w", encoding="utf-8") as f:
                                            f.write("\n".join(log))
                                        print(f" Log salvato in: {LOG_DIR}/{nome_log}")
                                    
                                    if __name__ == "__main__":
                                            avvia_tutti()