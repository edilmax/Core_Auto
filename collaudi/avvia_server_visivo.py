"""
Launcher LOCALE per il collaudo VISIVO (Playwright). NON e' produzione: monta un sistema con
DB temporanei, PAGA_STRUTTURA_ATTIVO=1, pubblica un annuncio a Roma che ACCETTA "paga in
struttura" con disponibilita', e serve il sito reale (deploy/) + API su una porta locale.
Cosi' il browser headless puo' percorrere Home -> ricerca -> checkout e vedere il box/radio.

Uso:  python collaudi/avvia_server_visivo.py [porta]      (default 8099)
Si ferma da solo dopo VISIVO_TTL secondi (default 900) per non restare appeso.
"""
import datetime
import json
import os
import sys
import tempfile
import threading

# gate acceso: la vetrina paga-in-struttura deve apparire nel checkout
os.environ["PAGA_STRUTTURA_ATTIVO"] = "1"
os.environ.setdefault("HOST_KEY", "hk")
os.environ.setdefault("ADMIN_KEY", "ak")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema           # noqa: E402
from fase83_server import crea_router, servi                               # noqa: E402
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256       # noqa: E402


def _prepara(porta):
    d = tempfile.mkdtemp(prefix="visivo_")
    sistema = crea_sistema(ConfigCasaVIP(
        abilitato=True, segreto_hmac=b"V" * 32, con_registrazione_host=True,
        db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
        db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
        db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db",
        bunker_password="SuperPw@1",   # accende il SUPER-ADMIN (bunker) per il collaudo dei 3 ruoli
        commissione_bps=1000, psp_bps=0, stripe_secret_key="sk_test_visivo",
        stripe_webhook_secret="whsec_v", stripe_success_url="http://localhost/ok",
        stripe_cancel_url="http://localhost/no"))
    r = crea_router(sistema, host_key="hk", admin_key="ak",
                    base_url="http://127.0.0.1:%d" % porta)

    def g(m, p, b=None, h=None):
        return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    _, c = g("POST", "/api/host/registrazione",
             {"email": "host@visivo.it", "password": "password1", "accetta_termini": True,
              "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
              "versione": CONTRATTO_HOST_VERSIONE})
    tok = c["token"]
    # annuncio a Roma con coordinate (per la ricerca) + accetta paga in struttura (default ON)
    g("POST", "/api/host/pubblica",
      {"slug": "attico-roma-visivo", "titolo": "Attico Vista Colosseo", "citta": "Roma",
       "paese": "IT", "cin": "IT058091C2X5V0ABCD", "prezzo_notte_cents": 18000, "capacita": 4,
       "lat_micro": 41902782, "lon_micro": 12496366, "camere": 2, "bagni": 1,
       "servizi": ["wifi", "aria_condizionata", "cucina"],
       "politica_cancellazione": "flessibile"}, {"X-Host-Token": tok})
    oggi = datetime.date.today()
    g("POST", "/api/host/disponibilita_range",
      {"alloggio_id": "attico-roma-visivo", "da": oggi.isoformat(),
       "a": (oggi + datetime.timedelta(days=120)).isoformat(),
       "unita_totali": 3, "prezzo_netto_cents": 18000}, {"X-Host-Token": tok})
    return sistema


def main():
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    sistema = _prepara(porta)
    ttl = int(os.environ.get("VISIVO_TTL", "900"))
    # auto-stop: non restare appeso oltre il TTL
    threading.Timer(ttl, lambda: os._exit(0)).start()
    print("SERVER VISIVO pronto su http://127.0.0.1:%d (TTL %ds) - annuncio: Roma" % (porta, ttl),
          flush=True)
    servi(sistema, host="127.0.0.1", porta=porta, cartella_statica="deploy",
          host_key="hk", admin_key="ak", base_url="http://127.0.0.1:%d" % porta)


if __name__ == "__main__":
    main()
