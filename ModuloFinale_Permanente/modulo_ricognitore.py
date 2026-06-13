# modulo_ricognitore.py  Ricognitore Universale MaxSystem
import requests
from bs4 import BeautifulSoup
import datetime
import os

LINKS_ANALISI = [
    "https://pypi.org/",
    "https://github.com/",
    "https://huggingface.co/",
    "https://rapidapi.com/",
    "https://ai.google/tools/",
    "https://paperswithcode.com/",
    "https://www.exploit-db.com/",
    "https://0day.today/"
]

CARTELLA_SALVATAGGI = "RICOGNIZIONE_DATI"
if not os.path.exists(CARTELLA_SALVATAGGI):
        os.makedirs(CARTELLA_SALVATAGGI)
    
    def estrai_titolo(url):
            try:
                    risposta = requests.get(url, timeout=10)
                    soup = BeautifulSoup(risposta.text, "html.parser")
                    titolo = soup.title.string if soup.title else "Titolo non trovato"
                    return titolo.strip()
                except Exception as e:
                        return f"Errore: {str(e)}"
                
                def salva_risultati():
                        now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        path_file = os.path.join(CARTELLA_SALVATAGGI, f"ricognizione_output_{now}.txt")
                        with open(path_file, "w", encoding="utf-8") as f:
                                for link in LINKS_ANALISI:
                                        titolo = estrai_titolo(link)
                                        f.write(f"[] {link}  {titolo}\n")
                                        print(f"[] {link}  {titolo}")
                                print(f"[] Risultati salvati in {path_file}")
                            
                            def main():
                                    print(" MODULO RICOGNITORE  AVVIO")
                                    salva_risultati()
                                
                                if __name__ == "__main__":
                                        main()