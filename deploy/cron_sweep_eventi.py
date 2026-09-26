"""CRON SWEEP EVENTI (casella 9 del blocco SOLDI, 2026-09-25): un'elaborazione fallita
di un evento Stripe NON sparisce.

L'archivio (fase204) segna gli eventi ricevuti: quelli che RESTANO «da_elaborare» sono
un lavoro rimasto indietro che nessuno riprendeva — finora. Questo sweeper:
  1. legge gli eventi pendenti piu' vecchi di RITARDO_SEC (fuori dalla corsia del vivo);
  2. li RIDELIVERA' al gestore INTERO: il corpo salvato viene rifirmato col webhook
     secret nostro (l'archivio custodisce corpi GIA' VERIFICATI all'ingresso) e passato
     a `_webhook_stripe_registrato`, l'unico punto d'uscita che segna «elaborato» su 2xx.
     Ripercorre TUTTI i rami: pagamento E identita' (KYC), come la casella chiede;
  3. un tentativo fallito conta con `segna_tentativo` (l'archivio lo espone da sempre);
  4. un evento vecchio piu' di ANOMALIA_SEC (un'ora) ancora indietro e' UN'ANOMALIA DEL
     GUARDIANO: email con URGENTE nell'oggetto. Scrive /data/sweep_eventi.log (JSON).

SUL VPS il cron di root lancia (riga nel crontab di root, ogni 15 minuti):
  */15 * * * * docker exec casavip_app python3 /app/deploy/cron_sweep_eventi.py >> /data/sweep_cron.log 2>&1

CODICI D'USCITA: 0 = nessun pendente o tutti riprocessati, nessuna anomalia;
1 = ANOMALIA: eventi oltre la soglia ancora indietro (email gia' mandata);
2 = giro IMPOSSIBILE (config mancante o eccezione: NON ESEGUITO non e' un successo, S7).
"""
import json
import os
import sys
import time

# LANCIATO DA CRON lo script gira DA SOLO: sys.path[0] e' la cartella dello script
# (/app/deploy), NON la radice — i moduli fase non sono importabili senza questa riga.
# Lezione D23 del cron della riconciliazione: l'ambiente e' parte della misura.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RITARDO_SEC = 300          # un evento giovane puo' stare ancora in corsa: non si tocca
ANOMALIA_SEC = 3600        # la soglia della casella: un'ora di tentativi = anomalia
LOG = "/data/sweep_eventi.log"


def _sistema_da_env(env):
    """Il sistema vero, dallo stesso ambiente del container (stessa mappa di main_casavip
    per i percorsi dei dati). Nel giro di prova il sistema arriva INIETTATO e questo non
    gira mai: i banchi non devono dipendere dall'ambiente della macchina che li esegue."""
    from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
    raw = (env.get("CASAVIP_SEGRETO") or "").strip()
    if raw:
        try:
            segreto = bytes.fromhex(raw)
        except ValueError:
            segreto = raw.encode("utf-8")[:64]
        if len(segreto) < 16:
            segreto = segreto.ljust(32, b"0")
    else:
        import secrets
        segreto = secrets.token_bytes(32)
    d = env.get("DATA_DIR") or "data"
    cfg = ConfigCasaVIP(
        abilitato=True, segreto_hmac=segreto,
        db_catalogo=env.get("DB_CATALOGO", f"{d}/catalogo.db"),
        db_inventario=env.get("DB_INVENTARIO", f"{d}/inventario.db"),
        db_registro_host=env.get("DB_REGISTRO_HOST", f"{d}/registro_host.db"),
        db_viral=env.get("DB_VIRAL", f"{d}/viral.db"),
        db_messaggi=env.get("DB_MESSAGGI", f"{d}/messaggi.db"),
        db_domanda=env.get("DB_DOMANDA", f"{d}/domanda.db"),
        db_garanzia=env.get("DB_GARANZIA", f"{d}/garanzia.db"),
        db_pendenti=env.get("DB_PENDENTI", f"{d}/pendenti.db"),
        db_eventi_stripe=env.get("DB_EVENTI_STRIPE", f"{d}/eventi_stripe.db"),
        db_tassa_comunale=env.get("DB_TASSA_COMUNALE", f"{d}/tassa_comunale.db"),
        db_finanza=env.get("DB_FINANZA", f"{d}/finanza.db"),
        db_payout=env.get("DB_PAYOUT", f"{d}/payout.db"),
        db_accettazioni=env.get("DB_ACCETTAZIONI", f"{d}/accettazioni.db"),
        stripe_webhook_secret=env.get("STRIPE_WEBHOOK_SECRET", ""),
        stripe_secret_key=env.get("STRIPE_SECRET_KEY", ""))
    return crea_sistema(cfg)


def main(env, send, ora=time.time, sistema=None, router=None):
    """Torna 0/1/2. `sistema` e `router` sono iniettabili per i banchi di prova
    (default: dal env, come il cron li costruisce in produzione)."""
    segreto = (env.get("STRIPE_WEBHOOK_SECRET") or "").strip()
    db_eventi = (env.get("DB_EVENTI_STRIPE") or "").strip()
    destinatario = (env.get("ALERT_EMAIL") or env.get("EMAIL_MITTENTE") or "").strip()
    mancano = [n for n, v in (("STRIPE_WEBHOOK_SECRET", segreto),
                              ("DB_EVENTI_STRIPE", db_eventi),
                              ("ALERT_EMAIL|EMAIL_MITTENTE", destinatario)) if not v]
    if mancano:
        print("NON ESEGUITO: variabili d'ambiente mancanti: %s (S7)" % ", ".join(mancano))
        return 2
    try:
        if sistema is None:
            sistema = _sistema_da_env(env)
        if router is None:
            from fase83_server import crea_router
            router = crea_router(sistema, host_key=(env.get("HOST_KEY") or "hk"),
                                 admin_key=(env.get("ADMIN_KEY") or "ak"),
                                 base_url="https://bookinvip.com")
        archivio = getattr(sistema, "eventi_stripe", None)
        if archivio is None:
            print("NON ESEGUITO: il sistema non ha l'archivio degli eventi (fase204)")
            return 2
        from fase87_stripe_webhook import firma_di_test
    except Exception as e:
        print("NON ESEGUITO: il sistema non si compone: %s: %s"
              % (type(e).__name__, e))
        return 2

    adesso = int(ora())
    pendenti = archivio.pendenti(piu_vecchi_di_sec=RITARDO_SEC, limite=200)
    risolti, falliti = [], []
    for ev in pendenti:
        corpo = archivio.corpo(ev["evt_id"])
        if not corpo:
            falliti.append((ev, "corpo_assente"))
            try:
                archivio.segna_tentativo(ev["evt_id"])
            except Exception:
                pass
            continue
        # RIDELIVERY: il corpo e' quello ARRIVATO (verificato all'ingresso), rifirmato
        # adesso col nostro secret — e' noi che vouchiamo per l'archivio, non Stripe.
        # ⛔ La firma porta il tempo di CHI VERIFICA (il gestore, orologio vero):
        # l'orologio iniettato serve a scegliere gli eventi e misurare l'eta'.
        intestazione = {"Stripe-Signature": firma_di_test(corpo, segreto, int(time.time()))}
        try:
            stato, _ = router._webhook_stripe_registrato(corpo, intestazione)
            stato = int(stato)
        except Exception:
            stato = 500
        if 200 <= stato < 300 and archivio.elaborato(ev["evt_id"]):
            risolti.append(ev["evt_id"])
        else:
            falliti.append((ev, "stato_%s" % stato))
            try:
                archivio.segna_tentativo(ev["evt_id"])
            except Exception:
                pass

    anomalie = [e for e in archivio.pendenti(piu_vecchi_di_sec=ANOMALIA_SEC, limite=200)]
    inviata = True
    if anomalie:
        oggetto = ("URGENTE - Anomalia Guardiano BookinVIP: %d evento/i Stripe rimasti "
                   "indietro oltre un'ora" % len(anomalie))
        righe = ["<h3>Eventi Stripe non elaborati oltre la soglia di un'ora</h3>"]
        for e in anomalie:
            eta_min = max(0, (adesso - int(e.get("ricevuto_ts") or adesso)) // 60)
            righe.append("<p>- %s | tipo=%s | tentativi=%d | eta=%d min</p>"
                         % (e["evt_id"], e.get("tipo") or "?",
                            int(e.get("tentativi") or 0), eta_min))
        righe.append("<p style='color:#888'>Lo sweeper li ha rideliverati e sono rimasti "
                     "indietro: guardare il registro del server prima di intervenire.</p>")
        inviata = send(destinatario, oggetto, "\n".join(righe))
    riga = {"ts": adesso, "pendenti": len(pendenti), "risolti": len(risolti),
            "falliti": len(falliti), "anomalie": len(anomalie), "email_inviata": bool(inviata)}
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(riga, ensure_ascii=True) + "\n")
    except OSError:
        pass
    print("SWEEP_EVENTI | pendenti=%d risolti=%d falliti=%d anomalie=%d email=%s"
          % (len(pendenti), len(risolti), len(falliti), len(anomalie), inviata))
    if anomalie:
        return 1
    return 0


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
