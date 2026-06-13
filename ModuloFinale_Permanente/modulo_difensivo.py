# modulo_difensivo.py  Difensore Auto-Riparatore MaxSystem
import os
import traceback
import datetime

LOG_DIR = "Log_Difensivi"
if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    
    def proteggi(funzione, *args, **kwargs):
            try:
                    funzione(*args, **kwargs)
                    print("[] Modulo eseguito correttamente.")
                except Exception as e:
                        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                        log_file = os.path.join(LOG_DIR, f"crash_{timestamp}.log")
                        with open(log_file, "w", encoding="utf-8") as f:
                                f.write(" ERRORE ESEGUITO:\n")
                                f.write(traceback.format_exc())
                            print(f"[] Errore gestito. Log salvato in: {log_file}")
                    
                    # Esempio di test difensivo (rimuovibile)
                    if __name__ == "__main__":
                            print(" MODULO DIFENSIVO ATTIVO  MAXSYSTEM")
                        
                            def test_error():
                                    print(" Simulazione errore...")
                                    raise ValueError("Errore di test simulato.")
                            
                                proteggi(test_error)