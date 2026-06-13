# modulo_generator.py  Interprete finale MAXSYSTEM
import os
import datetime

#  Percorso assoluto accanto a questo script
CARTELLA_OUTPUT = os.path.join(os.path.dirname(__file__), "CodiciCreati_Finali")
if not os.path.exists(CARTELLA_OUTPUT):
        os.makedirs(CARTELLA_OUTPUT)
    
    def crea_script(comando):
            comando = comando.lower()
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        
            if "server web" in comando:
                    codice = (
                        "from http.server import SimpleHTTPRequestHandler, HTTPServer\n"
                        "PORT = 8080\n"
                        "server = HTTPServer(('0.0.0.0', PORT), SimpleHTTPRequestHandler)\n"
                        "print(f'Server attivo su http://localhost:{PORT}')\n"
                        "server.serve_forever()\n"
                    )
                elif "sniffer" in comando or "traffico web" in comando:
                        codice = (
                            "import scapy.all as scapy\n"
                            "def sniffa(pacchetti=10):\n"
                            "    scapy.sniff(count=pacchetti, prn=lambda x: x.show())\n"
                            "sniffa()\n"
                        )
                    elif "posizione di mio figlio" in comando or "posizione telefono" in comando:
                            codice = (
                                "#  Simulazione: tracciamento reale richiede API ufficiali e consensi\n"
                                "print(' Localizzazione non consentita senza autorizzazione.')\n"
                            )
                        else:
                                codice = (
                                    "# Comando non riconosciuto\n"
                                    "print(' Comando non supportato. Aggiungi nuove funzioni nel modulo_generator.')"
                                )
                        
                            nome_file = f"script_{timestamp}.py"
                            path_completo = os.path.join(CARTELLA_OUTPUT, nome_file)
                            with open(path_completo, "w", encoding="utf-8") as f:
                                    f.write(codice)
                            
                                print(f"[] Script generato: {path_completo}")
                            
                            if __name__ == "__main__":
                                    print(" MODULO GENERATOR  MAXSYSTEM")
                                    while True:
                                            cmd = input(" Scrivi il tuo comando: ")
                                            if cmd.lower() in ["exit", "esci", "chiudi"]:
                                                    break
                                                crea_script(cmd)