# [ EVOLVED] Ricombinatore_Genetico_Codice.py - Combina codice da Database_Bianco e Database_Nero

import random
import os
from datetime import datetime

cartella = os.path.dirname(os.path.abspath(__file__))
db_bianco = os.path.join(cartella, "Database_Bianco.txt")
db_nero = os.path.join(cartella, "Database_Nero.txt")

try:
            with open(db_bianco, "r", encoding="utf-8") as f1:
                blocchi_bianchi = [r.strip() for r in f1.readlines() if r.strip()]
                    with open(db_nero, "r", encoding="utf-8") as f2:
                    blocchi_neri = [r.strip() for r in f2.readlines() if r.strip()]

                            if not blocchi_bianchi or not blocchi_neri:
                        raise ValueError("Uno dei database  vuoto.")

                    codice_finale = []
                    for _ in range(10):  # [ EVOLVED] numero righe generate
                        parte1 = random.choice(blocchi_bianchi)
                        parte2 = random.choice(blocchi_neri)
                        codice_finale.append(f"{parte1} {parte2}")

                    nome_file = f"ricombinato_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py"
                    path_out = os.path.join(cartella, nome_file)
                                    with open(path_out, "w", encoding="utf-8") as out:
                            out.write("\n".join(codice_finale))

                        print(f"[] Codice ricombinato salvato in: {nome_file}")

                                        except Exception as e:
                            print(f"[ERRORE] {e}")


                        # [AUTO-EVOLUZIONE COMPLETATA]