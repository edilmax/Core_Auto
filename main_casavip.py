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


def _segreto() -> bytes:
    raw = os.environ.get("CASAVIP_SEGRETO", "")
    if raw:
        try:
            b = bytes.fromhex(raw)
            if len(b) >= 16:
                return b
        except ValueError:
            return raw.encode("utf-8")[:64].ljust(16, b"0")
    import secrets
    b = secrets.token_bytes(32)
    logging.warning("CASAVIP_SEGRETO non impostato: uso un segreto EFFIMERO (solo dev)")
    return b


def main() -> None:  # pragma: no cover
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = ConfigCasaVIP(
        abilitato=True,
        segreto_hmac=_segreto(),
        db_catalogo=os.environ.get("DB_CATALOGO", "data/catalogo.db"),
        db_inventario=os.environ.get("DB_INVENTARIO", "data/inventario.db"),
        db_registro_host=os.environ.get("DB_REGISTRO_HOST", "data/registro_host.db"),
        db_viral=os.environ.get("DB_VIRAL", "data/viral.db"),
        db_messaggi=os.environ.get("DB_MESSAGGI", "data/messaggi.db"),
        db_domanda=os.environ.get("DB_DOMANDA", "data/domanda.db"),
        db_garanzia=os.environ.get("DB_GARANZIA", "data/garanzia.db"),
        db_pendenti=os.environ.get("DB_PENDENTI", "data/pendenti.db"),
        db_tassa_comunale=os.environ.get("DB_TASSA_COMUNALE", "data/tassa_comunale.db"),
        db_payout=os.environ.get("DB_PAYOUT", "data/payout.db"),
        db_accettazioni=os.environ.get("DB_ACCETTAZIONI", "data/accettazioni.db"),
        db_geocache=os.environ.get("DB_GEOCACHE", "data/geocache.db"),
        db_checkin=os.environ.get("DB_CHECKIN", "data/checkin.db"),
        # geocoding città->coordinate (mappa): ON in prod (Nominatim gratis+cache), OFF nei test
        con_geocoding=os.environ.get("GEOCODING", "true").lower() in ("1", "true", "yes", "si"),
        file_referral=os.environ.get("FILE_REFERRAL", "data/referral.json"),
        valuta=os.environ.get("VALUTA", "EUR"),
        commissione_bps=int(os.environ.get("COMMISSIONE_BPS", "1000")),  # 10% a regime (marketplace)
        # rampa di lancio (land-grab): nuovi host 0% per ~3 mesi -> 8% fino a 1 anno -> 10% a regime
        promo_lancio_attiva=os.environ.get("PROMO_LANCIO", "true").lower() in ("1", "true", "yes", "si"),
        # costo carta a carico host (copre Stripe -> noi mai in perdita); 300 bps = 3% (come Vrbo)
        psp_bps=int(os.environ.get("PAGAMENTO_BPS", "300")),
        stripe_secret_key=os.environ.get("STRIPE_SECRET_KEY", ""),
        stripe_success_url=os.environ.get("STRIPE_SUCCESS_URL", ""),
        stripe_cancel_url=os.environ.get("STRIPE_CANCEL_URL", ""),
        stripe_webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
        smtp_host=os.environ.get("SMTP_HOST", ""),
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
        smtp_user=os.environ.get("SMTP_USER", ""),
        smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        email_mittente=os.environ.get("EMAIL_MITTENTE", ""),
        whatsapp_token=os.environ.get("WHATSAPP_TOKEN", ""),
        whatsapp_phone_id=os.environ.get("WHATSAPP_PHONE_ID", ""),
        oxr_app_id=os.environ.get("OXR_APP_ID", ""),
        con_mcp=True,
        con_sentinel=os.environ.get("SENTINEL", "").lower() in ("1", "true", "yes"),
        cartella_sentinel=os.environ.get("SENTINEL_DIR") or ".",
    )
    for p in (config.db_catalogo, config.db_inventario, config.db_registro_host,
              config.db_viral, config.db_messaggi, config.db_domanda, config.db_garanzia,
              config.db_pendenti, config.db_tassa_comunale, config.db_payout,
              config.file_referral):
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
    _mancanti = [n for n in ("HOST_KEY", "ADMIN_KEY") if not os.environ.get(n)]
    if _mancanti:
        logging.critical(
            "RIFIUTO DI PARTIRE: manca %s. Senza, l'API host/admin sarebbe aperta a chiunque "
            "(es. /api/host/payout?host_id=<altrui>). Impostale in .env.casavip e riavvia.",
            " e ".join(_mancanti))
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
