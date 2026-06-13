# Database_Nero.py  Salva codice critico, hacker, deep, senza filtri
import os

cartella = os.path.dirname(os.path.abspath(__file__))
output_file = os.path.join(cartella, "Database_Nero.txt")

with open(output_file, "w", encoding="utf-8") as out:
    for f in os.listdir(cartella):
        if f.endswith(".py") and ("nero" in f.lower() or "black" in f.lower() or "deep" in f.lower()):
            with open(os.path.join(cartella, f), "r", encoding="utf-8", errors="ignore") as src:
                out.write(f"\n\n# ========== FILE: {f} ==========\n")
                out.write(src.read())

print(f"[] Codici deep salvati in: {output_file}")
