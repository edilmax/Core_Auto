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
    # ⛔ DOVE STANNO I DATABASE E' UNA COSA CHE IL BANCO DEVE POTER DIRE A CHI LO GIUDICA.
    # Fino al 2026-08-20 questa cartella era temporanea e senza nome, e `collaudi/giro_banco.py`
    # cercava i database solo in `/data` e `/app/data`, cioe' dentro il contenitore: su
    # qualunque macchina senza Docker CINQUE controlli sui soldi finivano «NON ESEGUITI» con
    # scritto accanto «il database sta in /data» -- una motivazione falsa, perche' il problema
    # era che il giudice cercava dove il giudicato non aveva mai scritto. Con `BANCO_DATI` la
    # cartella ha un nome che i due processi si scambiano, e quei controlli si MISURANO.
    d = os.environ.get("BANCO_DATI") or tempfile.mkdtemp(prefix="visivo_")
    os.makedirs(d, exist_ok=True)
    print("BANCO_DATI: %s" % d, flush=True)
    sistema = crea_sistema(ConfigCasaVIP(
        abilitato=True, segreto_hmac=b"V" * 32, con_registrazione_host=True,
        db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
        db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db",
        # ⛔ I NOMI DI QUESTI DUE NON SONO LIBERI: `giro_banco.db(nome)` apre `nome + ".db"`,
        # quindi `payout.db` e `finanza.db`. Con `pay.db` il file c'era e non lo trovava nessuno.
        db_payout=f"{d}/payout.db",
        # ⛔ ERA `:memory:` PER OMISSIONE, ed e' il difetto piu' grosso dei due: il libro
        # giornale del banco viveva nella RAM del server e moriva con lui. I quattro controlli
        # contabili non erano «saltati per colpa di Docker»: non avevano niente da leggere,
        # da nessuna parte. E' il modo di rompersi n. 1 (dati effimeri) dentro lo strumento
        # che esiste per scoprirlo.
        db_finanza=f"{d}/finanza.db",
        db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db",
        # la password del super-admin viene dall'ambiente, cosi' chi giudica il banco puo'
        # usare LA STESSA senza ricopiarla in un secondo posto (una copia resta indietro il
        # giorno che cambia); il valore di prima resta come ripiego dichiarato.
        bunker_password=os.environ.get("BUNKER_PASSWORD", "SuperPw@1"),
        commissione_bps=1000,
        # ⛔ PILOTABILI DALL'AMBIENTE (2026-08-10), con gli stessi valori di prima come
        # ripiego: erano incisi qui dentro, e `collaudi/giro_banco.py` — che parla con
        # QUESTO server e legge le chiavi dal PROPRIO ambiente — non riusciva a far pagare
        # nemmeno una prenotazione: chiave finta -> nessun link -> la macchina si rifiuta
        # (fail-safe giusto). Il giro finiva "0 pagate" e misurava la configurazione del
        # banco invece del prodotto. E con `psp_bps=0` la tariffa tecnica non veniva
        # nemmeno esercitata.
        psp_bps=int(os.environ.get("PAGAMENTO_BPS", "0") or 0),
        psp_bps_valuta_estera=int(os.environ.get("PAGAMENTO_BPS_ESTERA", "0") or 0),
        psp_fisso_cents=int(os.environ.get("PAGAMENTO_FISSO_CENTS", "0") or 0),
        stripe_secret_key=os.environ.get("STRIPE_SECRET_KEY", "sk_test_visivo"),
        stripe_webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", "whsec_v"),
        stripe_success_url="http://localhost/ok",
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
