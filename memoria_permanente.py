import os
from datetime import datetime

BASE_DIR = os.path.dirname(__file__)
LOG_FOLDER = os.path.join(BASE_DIR, "MemoriaLog")
os.makedirs(LOG_FOLDER, exist_ok=True)

def salva_evento(origine, comando, risposta):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        nome_file = f"log_{timestamp}.txt"
        percorso_file = os.path.join(LOG_FOLDER, nome_file)

            with open(percorso_file, 'w', encoding='utf-8') as f:
                f.write(f" Timestamp: {timestamp}\n")
                f.write(f" Origine: {origine}\n")
                f.write(f" Comando: {comando}\n")
                f.write(f" Risposta: {risposta}\n")

            print(f"[] Evento salvato in {nome_file}")

                def salva_massivo(lista_eventi):
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                nome_file = f"sessione_{timestamp}.txt"
                percorso_file = os.path.join(LOG_FOLDER, nome_file)

                            with open(percorso_file, 'w', encoding='utf-8') as f:
                                        for ev in lista_eventi:
                                f.write(f"--- Evento ---\n")
                                f.write(f" {ev['timestamp']}\n")
                                f.write(f" Origine: {ev['origine']}\n")
                                f.write(f" Comando: {ev['comando']}\n")
                                f.write(f" Risposta: {ev['risposta']}\n\n")

                        print(f"[] Sessione salvata in {nome_file}")


                    # [AUTO-EVOLUZIONE COMPLETATA]