"""
CORE_AUTO - Entrypoint Casa VIP (accensione unica eseguibile).

Mette online la macchina: legge la config dall'ambiente, accende il SistemaCasaVIP
(fase81, che cabla vetrina+inventario+concierge+MCP), e avvia il server HTTP (fase83)
che espone le API e serve il frontend (deploy/index.html, deploy/host.html).

Uso:
    CASAVIP_SEGRETO=<64hex>  HOST_KEY=<chiave>  PORTA=8080  python main_casavip.py

Genera un segreto:  python -c "import secrets; print(secrets.token_hex(32))"
"""
from __future__ import annotations

import logging
import os

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import servi


# Segnaposto di `.env.casavip.example`. Quel file sta su GitHub: usarli sul serio
# equivale a pubblicare la chiave di firma e la chiave admin. Guardia:
# test_avvio_e_ripristino.TestFailClosed (e il gemello che li riconferma nell'esempio).
SEGNAPOSTO_PUBBLICI = ("cambiami_64_caratteri_hex", "cambiami_chiave_host",
                       "cambiami_chiave_admin")


def _segreto() -> bytes:
    """Chiave HMAC del prodotto: firma voucher, gettoni host, cookie di sessione, crediti.

    FAIL-CLOSED (difetto chiuso 2026-07-29): un valore impostato ma DEBOLE non si
    aggiusta in silenzio, si rifiuta. Prima `CASAVIP_SEGRETO=x` (refuso, variabile
    troncata) diventava `b"x000000000000000"` — una chiave indovinabile, cioe' la
    piattaforma spalancata senza un solo errore nei log. Assente resta lecito (comodita'
    di sviluppo) ma il ripiego e' CASUALE e dichiarato, mai una costante.
    """
    raw = os.environ.get("CASAVIP_SEGRETO", "").strip()
    if raw:
        if raw in SEGNAPOSTO_PUBBLICI:
            logging.critical(
                "RIFIUTO DI PARTIRE: CASAVIP_SEGRETO e' ancora il segnaposto di "
                ".env.casavip.example, che e' PUBBLICO su GitHub: chiunque potrebbe "
                "firmare voucher e sessioni. Generane uno vero: "
                "python -c \"import secrets; print(secrets.token_hex(32))\"")
            raise SystemExit(2)
        try:
            b = bytes.fromhex(raw)
        except ValueError:
            b = raw.encode("utf-8")[:64]        # non e' esadecimale: vale come frase segreta
        if len(b) >= 16:
            return b
        logging.critical(
            "RIFIUTO DI PARTIRE: CASAVIP_SEGRETO troppo corto (%d byte, ne servono >=16). "
            "Una chiave corta o riempita di zeri e' INDOVINABILE, e con quella si firmano "
            "voucher, gettoni host, cookie di sessione e crediti. Generane uno vero: "
            "python -c \"import secrets; print(secrets.token_hex(32))\"", len(b))
        raise SystemExit(2)
    import secrets
    b = secrets.token_bytes(32)
    logging.warning("CASAVIP_SEGRETO non impostato: uso un segreto EFFIMERO (solo dev)")
    return b


def _configura_logging() -> None:  # pragma: no cover
    """Log su STDOUT (per `docker logs`) + su FILE nel volume dati, che SOPRAVVIVE al
    deploy rm-first (i log del container invece si perdono a ogni ricreazione: era il
    fantasma 'la scatola nera bruciata dal deploy'). File rotante 5x5MB in DATA_DIR."""
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(logging.StreamHandler())            # stdout -> docker logs
    root.handlers[-1].setFormatter(fmt)
    try:
        from logging.handlers import RotatingFileHandler
        data_dir = os.environ.get("DATA_DIR") or os.path.dirname(
            os.environ.get("DB_FINANZA", "data/finanza.db")) or "data"
        os.makedirs(data_dir, exist_ok=True)
        fh = RotatingFileHandler(os.path.join(data_dir, "app.log"),
                                 maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
        logging.getLogger("core_auto").info("log persistente attivo: %s/app.log", data_dir)
    except Exception:
        logging.getLogger("core_auto").warning("log su file non attivato (ISOLATO)",
                                               exc_info=True)


def main() -> None:  # pragma: no cover
    _configura_logging()
    config = ConfigCasaVIP(
        abilitato=True,
        segreto_hmac=_segreto(),
        db_catalogo=os.environ.get("DB_CATALOGO", "data/catalogo.db"),
        db_inventario=os.environ.get("DB_INVENTARIO", "data/inventario.db"),
        db_registro_host=os.environ.get("DB_REGISTRO_HOST", "data/registro_host.db"),
        db_viral=os.environ.get("DB_VIRAL", "data/viral.db"),
        db_coda=os.environ.get("DB_CODA", "data/coda.db"),
        db_split=os.environ.get("DB_SPLIT", "data/split.db"),
        db_messaggi=os.environ.get("DB_MESSAGGI", "data/messaggi.db"),
        db_domanda=os.environ.get("DB_DOMANDA", "data/domanda.db"),
        db_partner=os.environ.get("DB_PARTNER", "data/partner.db"),
        db_deposito=os.environ.get("DB_DEPOSITO", "data/deposito.db"),
        db_garanzia=os.environ.get("DB_GARANZIA", "data/garanzia.db"),
        db_pendenti=os.environ.get("DB_PENDENTI", "data/pendenti.db"),
        db_tassa_comunale=os.environ.get("DB_TASSA_COMUNALE", "data/tassa_comunale.db"),
        db_payout=os.environ.get("DB_PAYOUT", "data/payout.db"),
        db_admin_accounts=os.environ.get("DB_ADMIN_ACCOUNTS", "data/admin_accounts.db"),
        db_accettazioni=os.environ.get("DB_ACCETTAZIONI", "data/accettazioni.db"),
        # DIFETTO CHIUSO 2026-07-21: questi due NON venivano passati -> restavano
        # a ":memory:" anche in PRODUZIONE. Le recensioni sparivano a ogni riavvio e
        # il registro dei crediti gia' spesi pure (= un credito rispendibile dopo un
        # deploy, cioe' denaro vero). Guardia: test_db_persistenti.py.
        db_recensioni=os.environ.get("DB_RECENSIONI", "data/recensioni.db"),
        db_credito_usati=os.environ.get("DB_CREDITO_USATI", "data/credito_usati.db"),
        db_marche=os.environ.get("DB_MARCHE", "data/marche.db"),
        db_geocache=os.environ.get("DB_GEOCACHE", "data/geocache.db"),
        db_checkin=os.environ.get("DB_CHECKIN", "data/checkin.db"),
        db_finanza=os.environ.get("DB_FINANZA", "data/finanza.db"),
        db_kyc=os.environ.get("DB_KYC", "data/kyc.db"),
        bunker_totp_secret=os.environ.get("BUNKER_TOTP_SECRET", ""),
        bunker_password=os.environ.get("BUNKER_PASSWORD", ""),
        bunker_recovery=os.environ.get("BUNKER_RECOVERY", ""),
        # geocoding città->coordinate (mappa): ON in prod (Nominatim gratis+cache), OFF nei test
        con_geocoding=os.environ.get("GEOCODING", "true").lower() in ("1", "true", "yes", "si"),
        # provider POI OSM (fase175) per il motore SEO: ON in prod (Overpass gratis+cache), OFF nei test
        con_poi=os.environ.get("POI_OSM", "true").lower() in ("1", "true", "yes", "si"),
        db_poicache=os.environ.get("DB_POICACHE", "data/poicache.db"),
        file_referral=os.environ.get("FILE_REFERRAL", "data/referral.json"),
        valuta=os.environ.get("VALUTA", "EUR"),
        commissione_bps=int(os.environ.get("COMMISSIONE_BPS", "1000")),  # 10% a regime (marketplace)
        # rampa di lancio (land-grab): nuovi host 0% per ~3 mesi -> 8% fino a 1 anno -> 10% a regime
        promo_lancio_attiva=os.environ.get("PROMO_LANCIO", "true").lower() in ("1", "true", "yes", "si"),
        # COSTO CARTA a carico host: deve COPRIRE Stripe, che prende percentuale + QUOTA
        # FISSA (0,25 EUR) e in piu' il 2% se deve CONVERTIRE la valuta. Il 3% secco di
        # prima era sotto costo: sotto 16,66 EUR con qualunque carta, e a QUALUNQUE importo
        # con una carta non europea (3,15%). Misura e conti: `collaudi/conti_stripe.py`.
        # Il conto Stripe e' italiano e tiene solo euro (misurato il 2026-08-09), quindi un
        # annuncio prezzato in altra valuta viene convertito per forza -> tariffa maggiorata.
        # 5% (euro) e 7% (valuta estera) + 0,25 EUR fissi. Scelti dal fondatore il 2026-08-10
        # con l'ordine di stare LARGHI DI UN PUNTO sul costo, e il motivo e' solido: il costo
        # Stripe DIPENDE DALLA NAZIONE DELLA CARTA, e al momento del preventivo non sappiamo
        # con che carta paghera' l'ospite. Il margine copre proprio quel non-sapere.
        # Costo VERO misurato sull'API (120 addebiti in modalita' prova): carta extra-UE
        # 3,25% + 0,25 EUR; +2% se Stripe deve convertire (conto italiano, tiene solo euro).
        #   euro   -> 5% contro 3,25% = 1,75 punti di margine
        #   estera -> 7% contro 5,25% = 1,75 punti di margine
        # ⛔ Serve soprattutto NEI PRIMI 90 GIORNI: li' la commissione e' 0% e questa tariffa
        # e' l'UNICA cosa che paga Stripe. Se scende, in promozione si perde su ogni incasso.
        # ⛔ Questi tre numeri sono SALDATI a `fase98_policy_commissione` (B1, 2026-08-29):
        # li' vive la fonte unica che leggono l'email di reclutamento, i testi legali e il
        # gateway del paga-in-struttura. Restano scritti qui perche' `main_casavip.py` e' la
        # dichiarazione di cio' che parte in produzione, e otto strumenti la leggono di li'.
        # Se divergono, `test_IL_RIPIEGO_DI_MAIN_E_SALDATO_ALLA_FONTE_UNICA` va rossa.
        psp_bps=int(os.environ.get("PAGAMENTO_BPS", "500")),
        psp_bps_valuta_estera=int(os.environ.get("PAGAMENTO_BPS_ESTERA", "700")),
        psp_fisso_cents=int(os.environ.get("PAGAMENTO_FISSO_CENTS", "25")),
        stripe_secret_key=os.environ.get("STRIPE_SECRET_KEY", ""),
        stripe_success_url=os.environ.get("STRIPE_SUCCESS_URL", ""),
        stripe_cancel_url=os.environ.get("STRIPE_CANCEL_URL", ""),
        stripe_webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
        smtp_host=os.environ.get("SMTP_HOST", ""),
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
        smtp_user=os.environ.get("SMTP_USER", ""),
        smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        email_mittente=os.environ.get("EMAIL_MITTENTE", ""),
        email_alert=os.environ.get("ALERT_EMAIL", ""),   # Guardiano fase186; vuoto->mittente
        whatsapp_token=os.environ.get("WHATSAPP_TOKEN", ""),
        whatsapp_phone_id=os.environ.get("WHATSAPP_PHONE_ID", ""),
        oxr_app_id=os.environ.get("OXR_APP_ID", ""),
        con_mcp=True,
        con_sentinel=os.environ.get("SENTINEL", "").lower() in ("1", "true", "yes"),
        cartella_sentinel=os.environ.get("SENTINEL_DIR") or ".",
    )
    # ── FAIL-CLOSED sugli archivi IN RAM (difetto chiuso 2026-07-29, revisione ostile) ──
    # Il gemello travestito del percorso vuoto: `DB_FINANZA=:memory:` (il valore che i
    # test usano ovunque, quindi il primo candidato a finire in un `.env` per
    # copia-incolla). La guardia sui percorsi VUOTI (piu' sotto) lo lasciava passare
    # perche' la stringa non e' vuota, il ciclo delle cartelle qui sotto lo salta di
    # proposito, e la sonda `/api/health/db` SALTA ANCHE i ":memory:" -> il prodotto
    # partiva, nessun file nasceva su disco e la sonda rispondeva "ok" senza nemmeno
    # NOMINARE l'archivio scomparso. E' il modo di rompersi n.1 (dati effimeri), gia'
    # pagato due volte: recensioni e crediti in RAM, cioe' un credito rispendibile dopo
    # ogni deploy. In produzione un archivio in memoria non serve MAI.
    # Sta PRIMA della creazione delle cartelle di proposito: un percorso malato non deve
    # arrivare a `os.makedirs` (che su un valore come " :memory: " esplode con una traccia
    # illeggibile invece del motivo). Guardia: test_avvio_ostile.py.
    _in_ram = [c for c in sorted(vars(ConfigCasaVIP()))
               if c.startswith("db_")
               and str(getattr(config, c, "") or "").strip() == ":memory:"]
    if _in_ram:
        logging.critical(
            "RIFIUTO DI PARTIRE: archivio IN MEMORIA per %s. ':memory:' vive dentro il "
            "processo: i dati (giornale contabile, prove d'accettazione, crediti gia' "
            "spesi) sparirebbero a ogni riavvio senza un errore, e /api/health/db non "
            "nominerebbe nemmeno l'archivio. Dai un percorso vero (es. /data/<nome>.db).",
            ", ".join("DB_" + c[3:].upper() for c in _in_ram))
        raise SystemExit(2)
    # La cartella va creata per OGNI file, non per una lista scelta a mano: un percorso
    # dimenticato qui fa fallire l'apertura del database al primo avvio su una macchina
    # nuova. Si ricava dalla configurazione, cosi' non si puo' piu' dimenticare nessuno.
    _percorsi = [getattr(config, c) for c in sorted(vars(ConfigCasaVIP()))
                 if c.startswith("db_")] + [config.file_referral]
    for p in _percorsi:
        if not p or p == ":memory:":
            continue
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
    # ── FAIL-CLOSED sulle chiavi d'accesso (mina disinnescata, collaudo 2026-07-15) ──
    # `RouterHTTP._auth_host` ha un ramo comodo per lo sviluppo: `if self._host_key is None:
    # return True` (passa chiunque). In piu' gli endpoint host ripiegano su `query['host_id']`
    # quando non c'e' un token. Combinati, se HOST_KEY sparisce dall'ambiente (server nuovo,
    # typo, reset del .env) l'API host diventa APERTA A TUTTI: `/api/host/payout?host_id=<tizio>`
    # restituirebbe payout, prenotazioni e dati personali di QUALSIASI host. E' un default
    # fail-OPEN: il guasto silenzioso e' peggio del sito giu'. Qui, al confine del deploy,
    # si fallisce CHIUSO: meglio non partire che partire spalancati.
    # (I test non passano da qui: usano crea_router() direttamente, quindi restano invariati.)
    _mancanti = [n for n in ("HOST_KEY", "ADMIN_KEY") if not os.environ.get(n, "").strip()]
    if _mancanti:
        logging.critical(
            "RIFIUTO DI PARTIRE: manca %s. Senza, l'API host/admin sarebbe aperta a chiunque "
            "(es. /api/host/payout?host_id=<altrui>). Impostale in .env.casavip e riavvia.",
            " e ".join(_mancanti))
        raise SystemExit(2)
    # Stessa mina, ma travestita: la chiave C'E' ed e' il SEGNAPOSTO dell'esempio, che sta
    # su GitHub. Un sito "protetto" da una password stampata sul giornale e' un sito aperto.
    _pubbliche = [n for n in ("HOST_KEY", "ADMIN_KEY")
                  if os.environ.get(n, "").strip() in SEGNAPOSTO_PUBBLICI]
    if _pubbliche:
        logging.critical(
            "RIFIUTO DI PARTIRE: %s ha ancora il valore segnaposto di .env.casavip.example, "
            "che e' PUBBLICO su GitHub: equivale a non avere nessuna chiave. "
            "Genera le chiavi vere con: sh deploy/genera_segreti.sh", " e ".join(_pubbliche))
        raise SystemExit(2)
    # ── FAIL-CLOSED sui percorsi degli archivi (difetto chiuso 2026-07-29) ──────────
    # Una variabile PRESENTE ma VUOTA (`DB_FINANZA=` in un .env modificato a mano) arriva
    # fino a `sqlite3.connect("")`, che apre un database TEMPORANEO cancellato alla
    # chiusura della connessione. Siccome ogni chiamata apre la sua connessione, l'archivio
    # sparisce tra una riga e l'altra ("no such table: libro_giornale") e la sonda
    # /api/health/db, che SALTA i percorsi vuoti, continua a rispondere "ok": perdita di
    # prove contabili in perfetto silenzio. Qui si fallisce chiuso, con il nome del colpevole.
    _vuoti = [c for c in sorted(vars(ConfigCasaVIP()))
              if c.startswith("db_") and not str(getattr(config, c, "") or "").strip()]
    if _vuoti:
        logging.critical(
            "RIFIUTO DI PARTIRE: percorso di archivio VUOTO per %s. Un percorso vuoto apre "
            "un database temporaneo che si cancella da solo: i dati (giornale contabile, "
            "prove d'accettazione, payout) sparirebbero senza un errore. Dai un percorso "
            "vero (es. /data/<nome>.db) oppure togli del tutto la variabile per usare il "
            "valore di serie.", ", ".join("DB_" + c[3:].upper() for c in _vuoti))
        raise SystemExit(2)

    sistema = crea_sistema(config)
    logging.info("Composizione: %s", sistema.report)
    servi(sistema,
          host=os.environ.get("HOST", "127.0.0.1"),
          porta=int(os.environ.get("PORTA", "8080")),
          cartella_statica=os.environ.get("STATIC_DIR", "deploy"),
          host_key=os.environ.get("HOST_KEY") or None,
          base_url=os.environ.get("BASE_URL", "").rstrip("/"),
          admin_key=os.environ.get("ADMIN_KEY") or None)


if __name__ == "__main__":  # pragma: no cover
    main()
