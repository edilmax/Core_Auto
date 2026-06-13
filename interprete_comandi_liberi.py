#!/usr/bin/env python3
import subprocess
import sys
import re

def get_wifi_passwords():
    """Ottiene tutte le password WiFi salvate su Windows """
    try:
        result = subprocess.run(
            ['netsh', 'wlan', 'show', 'profiles'],
            capture_output=True,
            text=True,
            check=True
        )
        
        profiles = [
            line.split(':')[1].strip() 
            for line in result.stdout.split('\n') 
            if 'Tutti i profili utente' in line
        ]
        
        passwords = {}
        for profile in profiles:
            try:
                result = subprocess.run(
                    ['netsh', 'wlan', 'show', 'profile', profile, 'key=clear'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                key_line = [
                    line.split(':')[1].strip()
                    for line in result.stdout.split('\n')
                    if 'Contenuto chiave' in line
                ]
                passwords[profile] = key_line[0] if key_line else "Password non disponibile"
            except subprocess.CalledProcessError:
                passwords[profile] = "Errore nel recupero"
        
        return passwords
    
    except Exception as e:
        return {"Errore": str(e)}

def main():
    print("""
    ██████╗ ██╗   ██╗██████╗  ██████╗ ██████╗  ██████╗ 
    ██╔═══██╗╚██╗ ██╔╝██╔══██╗██╔═══██╗██╔══██╗██╔════╝ 
    ██║   ██║ ╚████╔╝ ██████╔╝██║   ██║██████╔╝██║  ███╗
    ██║   ██║  ╚██╔╝  ██╔══██╗██║   ██║██╔══██╗██║   ██║
    ╚██████╔╝   ██║   ██║  ██║╚██████╔╝██║  ██║╚██████╔╝
    ╚═════╝    ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ 
    """)
    print("CYBORG WiFi Password Extractor - ULTIMATE EDITION\n")
    
    while True:
        try:
            user_input = input("CYBORG-WIFI> ").strip().lower()
            
            # Controlla qualsiasi combinazione di "password" e "wifi"
            if ('password' in user_input and 'wifi' in user_input) or ('password' in user_input and 'wi-fi' in user_input):
                print("\n[EVOLVED] Creato da SuperAI - Comando originale:", user_input)
                print("\n=== RETI WiFi TROVATE ===")
                
                passwords = get_wifi_passwords()
                
                if "Errore" in passwords:
                    print("\n❌ Errore:", passwords["Errore"])
                elif not passwords:
                    print("\n🔍 Nessuna rete WiFi trovata")
                else:
                    for network, password in passwords.items():
                        print(f"\n📶 Nome rete: {network}")
                        print(f"🔑 Password: {password}")
                
                print("\n=== FINE ELENCO ===\n")
            
            elif user_input in ('exit', 'quit', 'chiudi'):
                print("\n[EVOLVED] Chiusura in corso...")
                break
                
            else:
                print(f"""
[EVOLVED] Creato da SuperAI - Comando originale: {user_input}

[EVOLVED] Comando non riconosciuto.
print('Modulo da aggiornare.')""")
                
        except KeyboardInterrupt:
            print("\n[EVOLVED] Interruzione manuale")
            break

if __name__ == "__main__":
    # Verifica che sia Windows
    if not sys.platform == 'win32':
        print("⚠️ Questo script funziona solo su Windows")
        sys.exit(1)
    
    # Verifica che sia eseguito come amministratore
    try:
        subprocess.run(['net', 'session'], capture_output=True, check=True)
    except subprocess.CalledProcessError:
        print("⚠️ Per favore esegui come amministratore!")
        sys.exit(1)
    
    main()