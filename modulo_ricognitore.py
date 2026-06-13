# modulo_ricognitore.py  Ricognitore Estremo MaxSystem
import requests
from bs4 import BeautifulSoup
import re
import time

RISORSE = [
    "https://github.com/trending",
    "https://pypi.org/",
    "https://www.programmableweb.com/category/all/apis",
    "https://awesomeopensource.com/projects/hacking",
    "https://www.exploit-db.com/"
]

def cerca_api_librerie(html):
        risultati = []
            try:
                soup = BeautifulSoup(html, "html.parser")
                link_tags = soup.find_all("a", href=True)
                        for tag in link_tags:
                        href = tag['href']
                                    if any(chiave in href.lower() for chiave in ["api", "library", "lib", "sdk", ".py", "tool", "github"]):
                                risultati.append(href)
                                    except Exception as e:
                            risultati.append(f"[Errore parsing] {e}")
                        return risultati

                                        def analizza_risorse():
                            print(" MODULO RICOGNITORE  AVVIO")
                                                    for url in RISORSE:
                                    print(f"[] Scansione: {url}")
                                                                try:
                                            response = requests.get(url, timeout=10)
                                            risultati = cerca_api_librerie(response.text)
                                                                            if risultati:
                                                    print(f"[] Trovati {len(risultati)} risultati:")
                                                                                        for r in risultati[:10]:
                                                            print("   -", r)
                                                                                            else:
                                                            print("[] Nessun risultato utile.")
                                                                                                except Exception as e:
                                                            print(f"[] Errore su {url}: {e}")
                                                        time.sleep(1)

                                                                                                if __name__ == "__main__":
                                                        analizza_risorse()