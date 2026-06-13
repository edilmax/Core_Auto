# quantum_protector.py  Quantum Security Engine (BETA)
import hashlib
import os

def calcola_hash(file_path):
        try:
                with open(file_path, "rb") as f:
                        contenuto = f.read()
                        return hashlib.sha512(contenuto).hexdigest()
                except Exception as e:
                        return f"Errore: {e}"
                
                def verifica_integrita_cartella(cartella):
                        print(" QUANTUM SECURITY ENGINE  VERIFICA INTEGRIT")
                        for root, dirs, files in os.walk(cartella):
                                for file in files:
                                        full_path = os.path.join(root, file)
                                        hashfile = calcola_hash(full_path)
                                        print(f"{file}  SHA512: {hashfile[:64]}...")
                            
                            if __name__ == "__main__":
                                    cartella_target = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
                                    verifica_integrita_cartella(cartella_target)