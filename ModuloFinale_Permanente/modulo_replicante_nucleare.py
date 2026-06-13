# modulo_replicante_nucleare.py  Nucleo Replicante MaxSystem
import os
import shutil
import datetime

FOLDER_TARGET = "SuperAI_Outputs"
REPLICA_DIR = "REPLICHE_GENERATE"
if not os.path.exists(REPLICA_DIR):
        os.makedirs(REPLICA_DIR)
    
        def replica_file(percorso_file):
                if not os.path.exists(percorso_file):
                        print(f"[] File non trovato: {percorso_file}")
                    return
            
                    nome = os.path.basename(percorso_file)
                    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                    nuovo_nome = f"replica_{timestamp}_{nome}"
                    destinazione = os.path.join(REPLICA_DIR, nuovo_nome)
                    shutil.copy2(percorso_file, destinazione)
                    print(f"[] Replica salvata: {destinazione}")
            
                    def avvia_replicazione():
                            print(" MODULO REPLICANTE  MAXSYSTEM")
                            for root, _, files in os.walk(FOLDER_TARGET):
                                    for file in files:
                                            if file.endswith(".py") and "replica" not in file:
                                                    percorso_completo = os.path.join(root, file)
                                                    replica_file(percorso_completo)
                                                    print(" Replicazione completa.")
                            
                                                    if __name__ == "__main__":
                                                            avvia_replicazione()