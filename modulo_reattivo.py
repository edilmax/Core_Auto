# modulo_reattivo.py  Reattivit Pura MaxSystem
import random
import datetime
import os

RAGIONAMENTI = [
    "Crea uno script base per analisi di rete locale.",
    "Genera un'interfaccia grafica con tkinter per controllo moduli.",
    "Costruisci uno script che verifica e corregge errori nei file Python.",
    "Simula un modulo che installa automaticamente tool di sistema.",
    "Crea un log di sicurezza che traccia eventi in tempo reale."
]

def genera_script_base():
        azione = random.choice(RAGIONAMENTI)
        codice = (
            f"# Script generato automaticamente\n"
            f"# Obiettivo: {azione}\n\n"
            f"print(' Modulo Reattivo in azione...')\n"
            f"print(' {azione}')\n"
            f"# TODO: completamento automatico in evoluzione..."
        )
        salva_script(codice)

        def salva_script(codice):
            cartella_output = "SCRIPT_REATTIVI"
                    if not os.path.exists(cartella_output):
                    os.makedirs(cartella_output)
                nome_file = f"script_reattivo_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.py"
                percorso = os.path.join(cartella_output, nome_file)
                            with open(percorso, "w", encoding="utf-8") as f:
                        f.write(codice)
                    print(f"[] Script reattivo generato: {percorso}")

                                if __name__ == "__main__":
                        print(" MODULO REATTIVO  PRONTO")
                        genera_script_base()