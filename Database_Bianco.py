# Database_Bianco.py  Salva codice considerato positivo o didattico

import os

cartella = os.path.dirname(os.path.abspath(__file__))
output_file = os.path.join(cartella, "Database_Bianco.txt")

with open(output_file, "w", encoding="utf-8") as out:
    for f in os.listdir(cartella):
        if f.endswith(".py") and "nero" not in f.lower() and "black" not in f.lower():
            with open(os.path.join(cartella, f), "r", encoding="utf-8", errors="ignore") as src:
                out.write(f"\n\n# ========== FILE: {f} ==========\n")
                out.write(src.read())

print(f"[] Codici positivi salvati in: {output_file}")
