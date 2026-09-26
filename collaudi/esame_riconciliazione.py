"""L'ESAME DELLA CASELLA 11 DEL BLOCCO SOLDI — la riconciliazione col registro di Stripe
«gira OGNI notte e manda una mail anche quando e' tutto a posto, con URGENTE nell'oggetto
se c'e' un accredito mancante o un'operazione sconosciuta» (T3, cron attivo dal 25/9).

    python collaudi/esame_riconciliazione.py --da-file F                misura e mostra
    python collaudi/esame_riconciliazione.py --da-file F --scrivi       ... e scrive
    python collaudi/esame_riconciliazione.py --autoprova                letture FINTE col
                                                   guasto dentro: grida e poi tace (D18.2)

LE LETTURE (chiave: valore, una per riga — prese SUL VPS in sola lettura, come per
esame_deploy; il file resta fuori dal repository):
  CRON_RIGA: la riga del crontab di root che lancia il giro notturno
  ULTIMO_GIRO: l'ultima riga JSON di /data/riconciliazione_notte.log
  BATTITO_ETA_SEC: l'eta' in secondi del battito (mtime di riconciliazione_ultimo_giro)
  DATA_LETTURA: il timbro UTC delle letture (per misurare la freschezza SENZA orologi in gioco)
  CONFIG_PRESENTE: elenco delle variabili presenti nel .env (ALERT_EMAIL, SMTP_*, ...)
Le GUARDIE del comportamento (mail SEMPRE, URGENTE coi fantasmi, battito anche con email
ko) si ESEGUONO qui dentro: sono test_riconciliazione_notturna (Stripe finto al bordo).

⛔ D18: precondizioni, autoprova nelle due direzioni, NON_GUARDA, guardia in test_pipeline
   (il cron SUL VPS si verifica a mano con `crontab -l`: e' dichiarato, non tace).
"""
import io
import json
import os
import re
import sys
import unittest
from datetime import datetime, timezone

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
for _p in (RADICE, QUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from piano import BLOCCHI  # noqa: E402
import scheda  # noqa: E402

BLOCCO_SOLDI = 1
INDICE = 10
SEGNALO = ("ogni notte", "mail")
COMANDO = "python collaudi/esame_riconciliazione.py --da-file <letture> --scrivi"
GUARDIE = ("test_riconciliazione_notturna",)
ATTESI = {"CRON_RIGA", "ULTIMO_GIRO", "BATTITO_ETA_SEC", "DATA_LETTURA", "CONFIG_PRESENTE"}
NON_GUARDA = (
    "il contenuto dell'email vero e il provider SMTP non si interrogano: il comportamento "
    "(mail sempre, URGENTE, battito) e' provato dalle guardie con email finta",
    "la TRE VIE (l'estratto bancario) non esiste ancora: qui si misura la DUE VIE "
    "(giornale vs Stripe), che e' cio' che fase182 fa",
    "il giro PARZIALE per tetto di pagine non ha guardia dedicata: condivide il ramo "
    "URGENTE dei fantasmi, dichiarato in fase182",
)


def testo_casella():
    condizioni = BLOCCHI[BLOCCO_SOLDI - 1]["finito_quando"]
    testo = " ".join(str(condizioni[INDICE]).split())
    if not all(s.lower() in testo.lower() for s in SEGNALO):
        raise ValueError("la casella %d non dice piu' %r: il piano e' cambiato (S2)"
                         % (INDICE, SEGNALO))
    return testo


def leggi_letture(percorso):
    letture = {}
    with io.open(percorso, encoding="utf-8", errors="replace") as f:
        for riga in f:
            if ":" in riga and not riga.startswith("#"):
                k, v = riga.split(":", 1)
                letture[k.strip()] = v.strip()
    mancano = ATTESI - set(letture)
    if mancano:
        raise ValueError("letture incomplete: manca %s" % ", ".join(sorted(mancano)))
    return letture


def letture_finte():
    """Letture SANE per l'autoprova: non sono il VPS e lo dichiarano."""
    ora = datetime.now(timezone.utc)
    return {
        "CRON_RIGA": "17 2 * * * docker exec casavip_app python3 /app/deploy/"
                     "cron_riconciliazione.py >> /data/riconciliazione_cron.log 2>&1",
        "ULTIMO_GIRO": json.dumps({"ts": int(ora.timestamp()) - 3600, "ok": True,
                                   "fantasmi": 0, "parziale": False, "email_inviata": True}),
        "BATTITO_ETA_SEC": str(3600),
        "DATA_LETTURA": ora.isoformat(),
        "CONFIG_PRESENTE": "ALERT_EMAIL, SMTP_HOST, SMTP_PASSWORD, STRIPE_SECRET_KEY, "
                           "DB_FINANZA",
    }


def _quando(iso):
    q = datetime.fromisoformat(str(iso).strip().replace("Z", "+00:00"))
    return q if q.tzinfo else q.replace(tzinfo=timezone.utc)


def misura(letture, ora=None):
    """Le condizioni della casella, una per una: (tutte_ok, righe)."""
    ora = ora or datetime.now(timezone.utc)
    righe = []

    cron = letture.get("CRON_RIGA", "")
    cron_ok = bool(re.match(r"^\d{1,2}\s+\d{1,2}\s+\*\s+\*\s+\*\s+docker exec\s+\S+"
                            r"\s+python3\s+/app/deploy/cron_riconciliazione\.py", cron))
    righe.append(("il cron di root lancia il giro OGNI notte", cron_ok,
                  cron[:80] if cron_ok else "riga assente o senza il programma giornaliero"))

    try:
        giro = json.loads(letture.get("ULTIMO_GIRO", "{}"))
    except ValueError:
        giro = {}
    try:
        eta_letture = (ora - _quando(letture["DATA_LETTURA"])).total_seconds()
    except Exception:
        eta_letture = 0
    try:
        eta_giro = eta_letture + (ora - datetime.fromtimestamp(
            int(giro.get("ts") or 0), timezone.utc)).total_seconds()
    except (ValueError, OSError, OverflowError):
        eta_giro = None
    fresco = eta_giro is not None and eta_giro < 30 * 3600
    giro_ok = bool(giro.get("ok")) and not bool(giro.get("fantasmi")) \
        and not bool(giro.get("parziale")) and fresco
    righe.append(("l'ultimo giro notturno e' completo e fresco (mail compresa)", giro_ok,
                  "ok=%s fantasmi=%s parziale=%s eta_giro=%.0f s"
                  % (giro.get("ok"), giro.get("fantasmi"), giro.get("parziale"),
                     eta_giro if eta_giro is not None else -1)))

    mail_ok = bool(giro.get("email_inviata"))
    righe.append(("la mail e' partita ANCHE a tutto ok (la mail che non arriva e' "
                  "lei l'allarme)", mail_ok, "email_inviata=%s" % giro.get("email_inviata")))

    try:
        battito_ok = 0 <= int(letture.get("BATTITO_ETA_SEC", "999999")) < 25 * 3600
    except ValueError:
        battito_ok = False
    righe.append(("il battito e' fresco (sotto le 25 ore del guardiano)", battito_ok,
                  "eta=%s s" % letture.get("BATTITO_ETA_SEC")))

    config = letture.get("CONFIG_PRESENTE", "")
    config_ok = all(v in config for v in ("ALERT_EMAIL", "SMTP_HOST", "STRIPE_SECRET_KEY",
                                          "DB_FINANZA"))
    righe.append(("la config del giro notturno esiste sul VPS", config_ok, config))

    guardie_verdi = True
    dettaglio = []
    for nome in GUARDIE:
        suite = unittest.TestLoader().loadTestsFromName(nome)
        flusso = io.StringIO()
        esito = unittest.TextTestRunner(stream=flusso, verbosity=0).run(suite)
        guardie_verdi = guardie_verdi and esito.wasSuccessful()
        dettaglio.append("%s: %s (%d rossi)"
                         % (nome, "VERDE" if esito.wasSuccessful() else "ROSSA",
                            len(esito.failures) + len(esito.errors)))
    righe.append(("il comportamento (mail sempre, URGENTE, battito) e' sorvegliato",
                  guardie_verdi, "; ".join(dettaglio)))

    return all(ok for _, ok, _ in righe), righe


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    da_file = argv[argv.index("--da-file") + 1] if "--da-file" in argv else None
    scrivi = "--scrivi" in argv
    print("=" * 86)
    print("🧾 ESAME RICONCILIAZIONE — casella 11 del blocco SOLDI (T3: il giro notturno)")
    print("=" * 86)
    try:
        testo = testo_casella()
    except Exception as e:
        print("ROSSO %s" % e)
        return 2
    if da_file:
        try:
            letture = leggi_letture(da_file)
        except Exception as e:
            print("ROSSO le letture non si leggono: %s" % e)
            return 2
        vere = True
    else:
        letture = letture_finte()
        vere = False
        letture["CRON_RIGA"] = ""
        print("(letture FINTE dell'autoprova, col cron SPENTO dentro: non e' il VPS)")
    tutte_ok, righe = misura(letture)
    for nome, ok, dettaglio in righe:
        print("  %-6s %-62s %s" % ("OK" if ok else "ROSSO", nome, dettaglio))
    print("  · NON GUARDA: " + " | ".join(NON_GUARDA))
    if "--autoprova" in argv:
        letture_sane = letture_finte()
        sane_ok, _ = misura(letture_sane)
        print("  AUTOPROVA: grida col cron spento=%s · tace a macchina sana=%s"
              % (not tutte_ok, sane_ok))
        if not ((not tutte_ok) and sane_ok):
            return 1
        print("VERDETTO: ✅ l'esame grida col guasto e tace a macchina sana")
        return 0
    if not vere:
        print("VERDETTO: ⛔ letture FINTE: la casella NON si scrive mai da letture finte")
        return 1
    print("CASCELLA: «%s» -> %s" % (testo[:70], "VERDE" if tutte_ok else "ROSSA"))
    if scrivi:
        scheda.registra(testo, esito=tutte_ok, denominatore=len(righe), comando=COMANDO,
                        ordine=BLOCCO_SOLDI,
                        motivo="" if tutte_ok else "; ".join(
                            n for n, ok, _ in righe if not ok))
        print("  🗂️  casella scritta")
    print("VERDETTO: %s" % ("✅ VERDE" if tutte_ok else "⛔ ROSSA"))
    return 0 if tutte_ok else 1


if __name__ == "__main__":
    sys.exit(main())
