# modulo_terminale_unificato.py  Terminale Unificato MaxSystem
import os
import datetime
import subprocess

STORIA_COMANDI = "storico_comandi.txt"
MODULI_DISPONIBILI = {
    "generator": "modulo_generator.py",
    "reattivo": "modulo_reattivo.py",
    "creator": "super_ai_creator.py",
    "interprete": "interprete_comandi_liberi.py"
}

def salva_storia(comando):
        with open(STORIA_COMANDI, "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now()} - {comando}\n")
        
        def instrada_comando(comando):
                if "crea" in comando or "script" in comando:
                        modulo = MODULI_DISPONIBILI["generator"]
                    elif "analizza" in comando or "problema" in comando:
                            modulo = MODULI_DISPONIBILI["reattivo"]
                        elif "comando libero" in comando or "interpreta" in comando:
                                modulo = MODULI_DISPONIBILI["interprete"]
                            else:
                                    modulo = MODULI_DISPONIBILI["creator"]
                            
                                percorso = os.path.join(os.getcwd(), modulo)
                                if os.path.exists(percorso):
                                        print(f"[] Avvio modulo: {modulo}")
                                        subprocess.run(["python", percorso])
                                    else:
                                            print(f"[] Modulo non trovato: {modulo}")
                                    
                                    def terminale():
                                            print(" TERMINALE UNIFICATO  MAXSYSTEM")
                                            while True:
                                                    cmd = input(" Comando: ")
                                                    if cmd.lower() in ["exit", "chiudi", "stop"]:
                                                            print("[] Terminale chiuso.")
                                                            break
                                                        salva_storia(cmd)
                                                        instrada_comando(cmd)
                                                
                                                if __name__ == "__main__":
                                                        terminale()