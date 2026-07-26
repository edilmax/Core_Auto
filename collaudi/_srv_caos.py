"""Mini-launcher per il collaudo CAOS: avvia un VERO server su una cartella DATI FISSA
(env CAOS_DIR) e porta (env CAOS_PORT), cosi' si puo' SIGKILL-are il processo e RIAVVIARLO
sugli STESSI dati per provare il recupero senza righe parziali/fantasma. Non e' un test in
se': lo pilota collaudi/caos.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PAGA_STRUTTURA_ATTIVO"] = "1"

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema   # noqa: E402
from fase83_server import servi                                     # noqa: E402

d = os.environ["CAOS_DIR"]
porta = int(os.environ.get("CAOS_PORT", "8097"))
os.environ.setdefault("UPLOAD_DIR", d + "/uploads")

sistema = crea_sistema(ConfigCasaVIP(
    abilitato=True, segreto_hmac=b"C" * 32, con_registrazione_host=True,
    db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
    db_accettazioni=d + "/a.db", db_pendenti=d + "/p.db", db_messaggi=d + "/m.db",
    db_garanzia=d + "/g.db", db_recensioni=d + "/rec.db", db_payout=d + "/pay.db",
    db_finanza=d + "/fin.db",
    commissione_bps=1500, psp_bps=300, stripe_secret_key="sk",
    stripe_webhook_secret="whsec_x", stripe_success_url="https://x/ok",
    stripe_cancel_url="https://x/no"))

servi(sistema, host="127.0.0.1", porta=porta, cartella_statica="deploy",
      host_key="hk", admin_key="ak", base_url="http://127.0.0.1:%d" % porta)
