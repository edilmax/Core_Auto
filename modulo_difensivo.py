# modulo_difensivo.py  Protezione Totale MaxSystem
import os
import traceback
import datetime

LOG_DIR = "LOG_PROTEZIONE"
if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

        def proteggi(funzione, nome_modulo):
                    try:
                    print(f"[] Protezione attiva: {nome_modulo}")
                    funzione()
                            except Exception as e:
                        log_errore(nome_modulo, e)
                        print(f"[] Errore gestito in {nome_modulo}: {e}")

                                def log_errore(modulo, eccezione):
                        nome_file = f"errore_{modulo}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
                        percorso = os.path.join(LOG_DIR, nome_file)
                                            with open(percorso, "w", encoding="utf-8") as f:
                                f.write(f"Modulo: {modulo}\n")
                                f.write(f"Errore: {str(eccezione)}\n")
                                f.write("StackTrace:\n")
                                f.write(traceback.format_exc())
                            print(f"[] Log salvato: {percorso}")

                        # ESEMPIO USO
                                                def esempio_modulo_pericoloso():
                                print("Esecuzione modulo critico...")
                                raise ValueError("Simulazione errore grave.")

                                                        if __name__ == "__main__":
                                    print(" MODULO DIFENSIVO ATTIVO  MONITORAGGIO")
                                    proteggi(esempio_modulo_pericoloso, "ModuloEsempio")