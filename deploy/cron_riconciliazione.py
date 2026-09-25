"""CRON RICONCILIAZIONE NOTTURNA (T3, ordine del fondatore con «autorizzato»).

Chiama fase182.riconcilia (READ-ONLY: mai una scrittura, da noi ne' su Stripe) sul
periodo di GIORNI=2, manda UNA email SEMPRE — anche a tutto ok, perche' la mail che
NON arriva e' lei l'allarme — con URGENTE nell'oggetto quando ci sono fantasmi o il
giro e' parziale. Alla fine lascia il BATTITO (fase178.segna_battito_riconciliazione,
nella cartella dei dati): se il cron muore il battito invecchia e il watchdog urla
«riconciliazione_muto». Scrive infine /data/riconciliazione_notte.log (riga JSON a giro).

SUL VPS il cron di root lancia (la riga e' nel crontab di root):
  17 2 * * * docker exec casavip_app python3 /app/deploy/cron_riconciliazione.py >> /data/riconciliazione_cron.log 2>&1
(ore 02:17 UTC: fuori dalle ore piene del backup, dentro la notte del server).

CODICI D'USCITA: 0 = giro completo, nessun fantasma, email inviata;
1 = giro completo MA con fantasmi/parziale/email non partita (URGENTE gia' mandata);
2 = giro IMPOSSIBILE (config mancante o eccezione: NON ESEGUITO non e' un successo, S7).
"""
import json
import os
import sys
import time

GIORNI = 2
LOG = "/data/riconciliazione_notte.log"


def main(env, send, ora=time.time, fetch=None):
    chiave = (env.get("STRIPE_SECRET_KEY") or "").strip()
    db = (env.get("DB_FINANZA") or "").strip()
    destinatario = (env.get("ALERT_EMAIL") or env.get("EMAIL_MITTENTE") or "").strip()
    mancano = [n for n, v in (("STRIPE_SECRET_KEY", chiave), ("DB_FINANZA", db),
                              ("ALERT_EMAIL|EMAIL_MITTENTE", destinatario)) if not v]
    if mancano:
        print("NON ESEGUITO: variabili d'ambiente mancanti: %s (S7)" % ", ".join(mancano))
        return 2
    try:
        from fase177_financial_controller import crea_financial_controller
        from fase182_riconciliazione import riconcilia
        fc = crea_financial_controller(db)
        rep = riconcilia(fc, chiave, giorni=GIORNI, ora=ora, fetch=fetch)
    except Exception as e:
        print("NON ESEGUITO: la riconciliazione e' esplosa prima del report: %s: %s"
              % (type(e).__name__, e))
        return 2

    fantasmi = (len(rep.get("solo_stripe") or []) + len(rep.get("solo_giornale") or [])
                + len(rep.get("importo_diverso") or []))
    parziale = bool(rep.get("parziale"))
    urgente = bool(fantasmi or parziale)
    prefisso = "URGENTE - " if urgente else ""
    oggetto = ("%sRiconciliazione notturna BookinVIP: %s (%d notti guardate)"
               % (prefisso, "TUTTO QUADRA" if rep.get("ok") and not urgente
                  else "%d anomalia/e da guardare" % max(1, fantasmi), GIORNI))
    corpo = _corpo(rep, fantasmi, parziale)
    inviata = send(destinatario, oggetto, corpo)

    ts = int(ora())
    # BATTITO: stessa cartella dei dati del Guardiano (la cartella di DB_FINANZA), stessa
    # meccanica di fase178 — e senza una cartella vera NON si scrive niente (un battito
    # finto rassicura: e' peggio di nessun battito).
    dir_dati = os.path.dirname(db) if os.path.dirname(db) else "."
    try:
        from fase178_watchdog import segna_battito_riconciliazione
        segna_battito_riconciliazione(dir_dati, ora=ts)
    except Exception:
        pass                                   # il giro e' fatto: il battito non lo blocca
    riga = {"ts": ts, "ok": bool(rep.get("ok")), "fantasmi": fantasmi,
            "parziale": parziale, "email_inviata": bool(inviata),
            "solo_stripe": len(rep.get("solo_stripe") or []),
            "solo_giornale": len(rep.get("solo_giornale") or []),
            "importo_diverso": len(rep.get("importo_diverso") or [])}
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(riga, ensure_ascii=True) + "\n")
    except OSError:
        pass
    print("RICONCILIAZIONE_NOTTE | ok=%s fantasmi=%d parziale=%s email=%s"
          % (rep.get("ok"), fantasmi, parziale, inviata))
    return 0 if (rep.get("ok") and not urgente and inviata) else 1


def _corpo(rep, fantasmi, parziale):
    righe = ["<h3>Riconciliazione notturna BookinVIP (Stripe vs giornale)</h3>"]
    if not fantasmi and not parziale and rep.get("ok"):
        righe.append("<p>Tutto quadra: nessun fantasma, totali coincidenti al centesimo.</p>")
    else:
        righe.append("<p><b>Guardare:</b> %d anomalia/e%s.</p>"
                     % (max(1, fantasmi),
                        " — giro PARZIALE (tetto pagine: il verdetto copre una parte sola)"
                        if parziale else ""))
        for campo, titolo in (("solo_stripe", "Solo Stripe (pagato, il giornale non lo sa)"),
                              ("solo_giornale", "Solo giornale (dichiara incassato, Stripe no)"),
                              ("importo_diverso", "Stesso riferimento, importo diverso")):
            for v in rep.get(campo) or []:
                righe.append("<p>- %s: %s (%s) - %s</p>"
                             % (titolo, v.get("riferimento") or v.get("id", "?"),
                                v.get("valuta", ""), v.get("nota", "")))
    righe.append("<p style='color:#888'>Giro di solo lettura. La mail manca = allarme "
                 "(il battito invecchia e il watchdog urla).</p>")
    return "\n".join(righe)


if __name__ == "__main__":
    def _send_reale(dest, oggetto, corpo):
        from fase86_email import ProviderEmail
        p = ProviderEmail(os.environ.get("SMTP_HOST", ""),
                          int(os.environ.get("SMTP_PORT", "587") or 587),
                          os.environ.get("SMTP_USER", ""),
                          os.environ.get("SMTP_PASSWORD", ""),
                          os.environ.get("EMAIL_MITTENTE", ""))
        return p.invia(dest, oggetto, corpo)
    sys.exit(main(os.environ, _send_reale))
