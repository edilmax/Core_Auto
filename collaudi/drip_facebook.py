# -*- coding: utf-8 -*-
"""DRIP FACEBOOK — pubblica su Facebook UN video alla volta, lentamente, finche' la coda e' vuota.

Perche': Facebook applica un blocco anti-spam (OAuthException code 368) dopo ~15 video caricati
di fila da una pagina nuova. Non e' un errore nostro: e' una protezione della piattaforma che si
scioglie da sola col tempo. La cura professionale non e' insistere, e' il GOCCIOLAMENTO: pochi
post l'ora, ogni giorno, finche' il magazzino e' pubblicato.

Uso (cron sul VPS, ogni 30 min):
    cd /var/www/bookinvip && python3 collaudi/drip_facebook.py
Stato durevole in /root/drip_facebook.json: {"fatte": [slug, ...]}.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import giro_video as G
import pubblica_video as P

STATO = "/root/drip_facebook.json"
PER_GIRO = 1                      # un video per esecuzione: il ritmo che Facebook tollera


def _stato():
    try:
        with open(STATO, encoding="utf-8") as f:
            d = json.load(f)
            return set(d.get("fatte", []))
    except Exception:
        return set()


def _salva(fatte):
    with open(STATO, "w", encoding="utf-8") as f:
        json.dump({"fatte": sorted(fatte)}, f)


def main():
    os.chdir("/var/www/bookinvip")
    fatte = _stato()
    coda = [t for t in G.TAPPE
            if t[0] not in fatte and os.path.exists("/tmp/bv_%s.mp4" % t[0].replace("-", ""))]
    if not coda:
        print("[drip] coda vuota: niente da pubblicare")
        return
    print("[drip] in coda: %d" % len(coda), flush=True)
    for slug, citta, lingua, _voce in coda[:PER_GIRO]:
        path = "/tmp/bv_%s.mp4" % slug.replace("-", "")
        r = P.facebook(path, G._caption(lingua, citta, slug, "facebook"))
        print("[drip] %s -> %s" % (slug, r), flush=True)
        if str(r).startswith("OK"):
            fatte.add(slug)
            _salva(fatte)
        else:
            # blocco ancora attivo: non insistere, si riprova al prossimo giro
            print("[drip] blocco ancora attivo, riprovo al prossimo giro", flush=True)
            break
        time.sleep(5)


if __name__ == "__main__":
    main()
