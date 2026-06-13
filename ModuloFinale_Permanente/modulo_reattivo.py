# modulo_reattivo.py  Interprete Reattivo MaxSystem
import os
import datetime

CARTELLA_OUTPUT = "CodiciCreati_Reattivi"
if not os.path.exists(CARTELLA_OUTPUT):
        os.makedirs(CARTELLA_OUTPUT)
    
    def genera_script_base(comando):
            comando = comando.lower()
            now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            nome_file = f"reattivo_{now}.py"
            percorso = os.path.join(CARTELLA_OUTPUT, nome_file)
        
            # Dizionario comandi riconosciuti
            comandi_predefiniti = {
                "sniffer": (
                    "import scapy.all as scapy\n"
                    "scapy.sniff(count=10, prn=lambda x: x.summary())"
                ),
                "server web": (
                    "from http.server import HTTPServer, SimpleHTTPRequestHandler\n"
                    "PORT = 8080\n"
                    "server = HTTPServer(('0.0.0.0', PORT), SimpleHTTPRequestHandler)\n"
                    "print(f'Server attivo su http://localhost:{PORT}')\n"
                    "server.serve_forever()"
                ),
                "monitor traffico": (
                    "import psutil\n"
                    "print('Download:', psutil.net_io_counters().bytes_recv)\n"
                    "print('Upload:', psutil.net_io_counters().bytes_sent)"
                ),
            }
        
            codice = comandi_predefiniti.get(comando, f"# [] Comando non identificato, ma modulo reattivo risponder con una proposta adattiva.\nprint('Comando ricevuto: {comando}')")
        
            with open(percorso, "w", encoding="utf-8") as f:
                    f.write(codice)
            
                print(f"[] Script generato: {percorso}")
            
            def main():
                    print(" MODULO REATTIVO  ATTIVO")
                    while True:
                            comando = input(" Scrivi il tuo comando o problema: ")
                            if comando.lower() in ["exit", "chiudi", "stop"]:
                                    break
                                genera_script_base(comando)
                        
                        if __name__ == "__main__":
                                main()