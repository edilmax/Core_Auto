import requests
from bs4 import BeautifulSoup
import time
import os
import datetime
import socks
import socket

# [ EVOLVED] Configura proxy Tor
socks.set_default_proxy(socks.SOCKS5, "127.0.0.1", 9050)
socket.socket = socks.socksocket

# [ EVOLVED] Lista URL dark web (puoi aggiungerne altri)
target_urls = [
    "http://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion",
    "http://dreadyqxjvokvxvq.onion",
    "http://tuu66pzbitxz3efp.onion",
]

# [ EVOLVED] Percorso salvataggio
base_dir = "darknet_archive"
os.makedirs(base_dir + "/codici", exist_ok=True)
os.makedirs(base_dir + "/html", exist_ok=True)
os.makedirs(base_dir + "/logs", exist_ok=True)

def salva_file(nome, contenuto, subfolder):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"{base_dir}/{subfolder}/{nome}_{timestamp}.txt"
    with open(path, "w", encoding="utf-8", errors="ignore") as f:
        f.write(contenuto)

def analizza_pagina(url):
    try:
        print(f"[] Connessione a: {url}")
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=20)
        
        if response.status_code == 200:
            html = response.text
            salva_file("pagina_raw", html, "html")

            soup = BeautifulSoup(html, "html.parser")
            pre = soup.find_all("pre")
            code_blocks = soup.find_all("code")

            tutto = "\n\n".join([x.get_text() for x in pre + code_blocks])
            
            if tutto:
                salva_file("codice_estratto", tutto, "codici")
                print(f"[] Codice salvato da: {url}")
            else:
                print(f"[] Nessun codice trovato in: {url}")
        else:
            print(f"[] Errore {response.status_code} su: {url}")
    
    except Exception as e:
        print(f"[] Fallito {url}: {str(e)}")

# [ EVOLVED] Avvio scansione
if __name__ == "__main__":
    print(" Darknet Scanner attivo.")
    for url in target_urls:
        analizza_pagina(url)
        time.sleep(3)
    print(" Scansione completata.")
    input("Premi INVIO per chiudere.")

# [AUTO-EVOLUZIONE COMPLETATA]
