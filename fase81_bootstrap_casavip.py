"""
CORE_AUTO - Fase 81: Bootstrap Casa VIP (composition root del lodging stack).

Cosa mancava per VINCERE (verdetto onesto): non altre feature - ne abbiamo piu' dei
colossi in molte nicchie. Mancava la COLLA. I moduli alloggi (vetrina 57, inventario
realtime 58, concierge AI 59, MCP 60, ...) erano isole isolate e default-off: nessun
punto UNICO che li accende e li cabla in UN sistema deployabile. Questo modulo e' quel
punto - come fase55 fece per il funnel Mango, qui per lo stack ALLOGGI.

Da una ConfigCasaVIP assembla e CABLA:
  inventario(58)  ──(disponibile)──►  catalogo/vetrina(57)
        │                                    │
        └──────────►  concierge(59, prezzo firmato HMAC)  ──►  server MCP(60)
e restituisce un SistemaCasaVIP pronto, con un REPORT di composizione (cosa e' attivo,
cosa manca e perche'). Il cablaggio chiave: la disponibilita' mostrata in vetrina E'
quella reale dell'inventario (fase58) -> un solo punto di verita', niente overbooking.

VINCITRICE DEL BENCHMARK (3 strategie di accensione, come fase55):
  V3 'validata-con-report'. Costruisce ogni configurazione COERENTE e degrada con avvisi
  espliciti sui pezzi assenti; fail-closed (BootstrapError) SOLO sull'incoerenza attiva
  (sistema acceso ma senza segreto per firmare i prezzi = money-path rotto). Le altre
  perdono: V1 'eager-fail-fast' esplode anche su opzionali assenti a sistema SPENTO; V2
  'silent-partial' costruisce in silenzio un sistema rotto.

SOPRAVVIVENZA TOTALE: default-OFF (ConfigCasaVIP.abilitato=False -> nessun componente,
il money-path resta separato e opt-in); config validata (fail-closed su segreto debole);
componenti opzionali (MCP/sentinel) saltati con avviso, non con un crash. I moduli
restano quelli gia' testati (zero logica nuova di denaro qui). Zero dipendenze esterne.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("core_auto.bootstrap_casavip")


class BootstrapError(Exception):
    """Incoerenza di configurazione ATTIVA (sistema acceso ma non assemblabile)."""


@dataclass(frozen=True)
class ConfigCasaVIP:
    abilitato: bool = False
    segreto_hmac: bytes = b""
    db_catalogo: str = ":memory:"
    db_inventario: str = ":memory:"
    valuta: str = "EUR"
    commissione_bps: int = 1000         # commissione CORE marketplace in basis-point: 10% a regime
    promo_lancio_attiva: bool = False   # rampa di lancio 0%->8%->10% per anzianità host (land-grab; attivare al go-live)
    psp_bps: int = 0                    # costo carta a carico HOST (bps); default 0, la PROD lo mette a 300 (3%) via main
    # Referral host-porta-host: premio al referente SOLO dopo che l'invitato produce (mai in perdita)
    referral_benvenuto_cents: int = 1000        # €10 di benvenuto al nuovo host all'iscrizione
    referral_premio_cents: int = 4000           # €40 al referente quando l'invitato si qualifica
    referral_soglia_prenotazioni: int = 3       # l'invitato si qualifica dopo 3 prenotazioni pagate
    stripe_secret_key: str = ""        # gated: se vuoto, niente link di pagamento
    stripe_success_url: str = ""
    stripe_cancel_url: str = ""
    stripe_webhook_secret: str = ""    # gated: per verificare i webhook di Stripe
    smtp_host: str = ""                 # gated: se vuoto, niente email
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_mittente: str = ""
    email_alert: str = ""               # dove il Guardiano (fase186) grida se trova uno stato
                                        # impossibile; vuoto -> ripiega su email_mittente
    whatsapp_token: str = ""            # gated: avvisi prenotazione all'host via WhatsApp
    whatsapp_phone_id: str = ""         # gated: id numero mittente WhatsApp Cloud API
    oxr_app_id: str = ""                # gated: Open Exchange Rates (display indicativo valuta ospite)
    con_mcp: bool = True
    con_recensioni: bool = True
    con_smartpass: bool = True
    con_registrazione_host: bool = True
    con_viral: bool = True
    db_recensioni: str = ":memory:"
    db_registro_host: str = ":memory:"
    db_viral: str = ":memory:"
    db_coda: str = ":memory:"          # coda intelligente (fase67): DEPOSITI -> in prod va su FILE
    db_split: str = ":memory:"         # split di gruppo (fase65): rotte VIVE -> in prod va su FILE
    db_messaggi: str = ":memory:"
    db_domanda: str = ":memory:"       # lista d'attesa + credito fondatore (anti-vuoto)
    db_garanzia: str = ":memory:"      # escrow di garanzia (soldi all'host solo se conforme)
    db_pendenti: str = ":memory:"      # pagamenti in attesa (hold prima del pagamento)
    db_tassa_comunale: str = ":memory:"  # ledger riscossioni tassa di soggiorno (rendicontazione)
    db_payout: str = ":memory:"        # dashboard payout host (incassi attesi per valuta/stato)
    db_finanza: str = ":memory:"       # financial controller (fase177): giornale+note+debiti
    db_kyc: str = ":memory:"           # esiti verifica identita' host (fase143, MAI documenti)
    db_accettazioni: str = ":memory:"  # registro firmato accettazioni contratto host (prova legale)
    db_marche: str = ":memory:"        # marche temporali RFC 3161 (fase184): ora certificata da un terzo
    db_geocache: str = ":memory:"      # cache geocoding città->coordinate (mappa nella ricerca)
    db_checkin: str = ":memory:"       # check-in digitale (pre-registrazione ospiti + sblocco)
    db_credito_usati: str = ":memory:"  # registro SINGLE-USE crediti (fase167): un credito si spende UNA volta
    con_geocoding: bool = False        # ON in prod: geocodifica alla pubblicazione (default OFF: test)
    bunker_totp_secret: str = ""       # 2FA super-admin (fase180): segreto TOTP base32 (env, mai in git)
    bunker_password: str = ""          # password super-admin (2° fattore "qualcosa che sai")
    bunker_recovery: str = ""          # break-glass super-admin: codice d'emergenza se si perde l'authenticator
    con_poi: bool = False              # provider POI OSM (fase175) per il motore SEO (default OFF: test/rete)
    db_poicache: str = ":memory:"      # cache POI vicini per-annuncio (Overpass around+cache)
    file_referral: str = ""            # path JSON referral host-porta-host (vuoto = in RAM)
    file_blocco_globale: str = ""      # path flag kill-switch (vuoto = derivato da db_payout o solo-env)
    con_sentinel: bool = False
    cartella_sentinel: Optional[str] = None


@dataclass
class SistemaCasaVIP:
    config: ConfigCasaVIP
    report: Dict[str, Any]
    catalogo: Any = None
    inventario: Any = None
    concierge: Any = None
    mcp: Any = None
    sentinel: Any = None
    recensioni: Any = None
    emettitore_recensioni: Any = None
    firma: Any = None
    emettitore_pass: Any = None
    email_provider: Any = None
    registro_host: Any = None
    viral: Any = None
    tasse: Any = None
    sensory: Any = None
    sleep: Any = None
    split: Any = None
    coda: Any = None
    turnover: Any = None
    digital_twin: Any = None
    guardian: Any = None
    dichiarazione: Any = None
    noshow: Any = None
    marketing: Any = None
    messaggistica: Any = None
    referral: Any = None
    notificatore_prenotazione: Any = None
    domanda: Any = None
    garanzia: Any = None
    pagamenti_pendenti: Any = None
    tassa_comunale: Any = None
    payout: Any = None
    accettazioni: Any = None
    marche: Any = None      # ArchivioMarche (fase184): token RFC 3161 dell'ora certificata
    stripe: Any = None      # ProviderStripe (fase85) o None: per rigenerare link (su-richiesta)
    connect: Any = None     # ProviderConnect (fase101) o None: bonifici automatici agli host
    geocoder: Any = None    # Geocoder (fase166): città->coordinate per la mappa
    poi_provider: Any = None  # ProviderPOI (fase175): luoghi notevoli vicini, per il motore SEO
    checkin: Any = None     # CheckinDigitale (fase127): pre-registrazione ospiti + sblocco
    credito_usati: Any = None  # RegistroCreditiUsati (fase167): single-use del Credito Fondatore/Viaggio
    finanza: Any = None     # FinancialController (fase177): giornale immutabile + note + offset penali
    kyc: Any = None         # KYCHost (fase143): esiti verifica identita' (provider, no-PII)
    bunker: Any = None      # Bunker (fase180): super-admin 2FA TOTP + sessione blindata 15 min
    carta: Any = None       # ProviderCarta (fase183, Scatto ③): carta host off-session (gated)
    tassi: Any = None       # ProviderTassi (fase99): cambio valuta indicativo; None se OXR spento
    blocco_globale: Any = None  # BloccoGlobale (fase191): kill-switch d'emergenza dei movimenti soldi

    @property
    def attivo(self) -> bool:
        return bool(self.report.get("abilitato"))

    @property
    def money_path_pronto(self) -> bool:
        """Il prezzo puo' essere firmato e instradato? (concierge presente)."""
        return self.concierge is not None


def crea_sistema(config: Optional[ConfigCasaVIP] = None) -> SistemaCasaVIP:
    """Composition root. Default-OFF: a config spenta non costruisce nulla."""
    cfg = config or ConfigCasaVIP()
    componenti: List[str] = []
    avvisi: List[str] = []

    if not cfg.abilitato:
        return SistemaCasaVIP(cfg, {"abilitato": False, "componenti": [],
                                    "avvisi": ["sistema spento (default-off)"]})

    # incoerenza ATTIVA: acceso ma senza segreto -> il money-path (firma prezzo) e' rotto
    if not isinstance(cfg.segreto_hmac, (bytes, bytearray)) or len(cfg.segreto_hmac) < 16:
        raise BootstrapError("segreto_hmac assente/troppo corto (>=16 byte): il prezzo "
                             "del concierge non sarebbe firmabile")

    # 1) inventario realtime (sorgente di verita' della disponibilita')
    from fase58_channel_manager import crea_channel_manager
    inventario = crea_channel_manager(cfg.db_inventario)
    componenti.append("inventario(58)")

    # 2) vetrina, CABLATA sulla disponibilita' reale dell'inventario
    from fase57_vetrina import crea_catalogo
    catalogo = crea_catalogo(cfg.db_catalogo, disponibilita=inventario.disponibile)
    componenti.append("vetrina(57)<-inventario")

    # 3) concierge: prezzo firmato HMAC, sopra catalogo+inventario
    from fase59_concierge import FirmaQuote, crea_protocollo
    firma = FirmaQuote(bytes(cfg.segreto_hmac))      # firma di sistema (voucher, ecc.)
    # pagamento Stripe (GATED da chiave): senza chiave -> link None (come oggi)
    link_pagamento = None
    from fase85_pagamenti_stripe import crea_provider_stripe
    provider = crea_provider_stripe(cfg.stripe_secret_key, cfg.stripe_success_url,
                                    cfg.stripe_cancel_url, valuta=cfg.valuta.lower())
    if provider is not None:
        link_pagamento = provider.crea_link
        componenti.append("stripe(85)")
    else:
        avvisi.append("Stripe non configurato -> nessun link di pagamento (gated)")
    # Connect (fase101): bonifici AUTOMATICI agli host allo sblocco escrow (gated stessa chiave)
    from fase101_stripe_connect import crea_provider_connect
    _connect = crea_provider_connect(cfg.stripe_secret_key)
    if _connect is not None:
        componenti.append("connect(101)")
    # SCATTO ③ (fase183): provider carta off-session, gated stessa chiave Stripe. Il PROVIDER
    # esiste (per il salvataggio carta), ma l'ADDEBITO automatico e' gated a parte da
    # SCATTO3_ATTIVO nel server -> dormiente finche' il fondatore non attiva e testa.
    try:
        from fase183_carta_offsession import crea_provider_carta
        _carta = crea_provider_carta(cfg.stripe_secret_key)
    except Exception:
        _carta = None
    if _carta is not None:
        componenti.append("carta_offsession(183)")
    _bps = cfg.commissione_bps if isinstance(cfg.commissione_bps, int) and \
        0 <= cfg.commissione_bps <= 10000 else 1000   # fallback 10% (regime), mai 0 per errore
    _ctx_host: Dict[str, Any] = {}    # holder late-bound: registro_host nasce piu' sotto

    def _comm_alloggio(netto: int, slug: str, fonte: str = "marketplace") -> int:
        # per-fonte: 'diretto' (cliente dell'host) -> 5%; 'marketplace' -> 10% a regime
        # (rampa di lancio per anzianita' host quando promo_lancio_attiva: 0% -> 8% -> 10%).
        try:
            from fase98_policy_commissione import (commissione_bps_fonte, commissione_cents,
                                                   stato_scaglione)
            numero = 0
            bps_mkt = _bps                       # default 10% regime (fail-safe se anzianita' ignota)
            reg = _ctx_host.get("reg")
            if reg is not None and catalogo is not None:
                # FIX 2026-07-20 (rampa di lancio MAI applicata): il proprietario si chiede
                # con `host_di_alloggio()`. Prima si leggeva da `dettaglio(slug)["host_id"]`,
                # ma il dettaglio PUBBLICO non espone l'host (dato privato, by design) -> hid
                # era SEMPRE None -> si saltava la rampa e si ripiegava sul 10% a regime:
                # la promo "0% primi 90 giorni" non ha mai avuto effetto su una prenotazione
                # vera. La formula era giusta, non le arrivava il dato.
                hid = catalogo.host_di_alloggio(slug)
                if hid:
                    numero = reg.numero_host(hid)
                    if getattr(cfg, "promo_lancio_attiva", False):   # rampa lancio per anzianità
                        # FONTE UNICA (fase98.stato_scaglione): la stessa funzione che usa
                        # la vetrina e il pannello super-admin -> il numero ADDEBITATO e il
                        # numero MOSTRATO non possono divergere. La rampa finisce sulla
                        # commissione CONFIGURATA (non su un 10% fisso) e non la supera mai.
                        bps_mkt = stato_scaglione(
                            reg.giorni_da_registrazione(hid),
                            promo_attiva=True, bps_regime_config=_bps)["bps"]
            bps = commissione_bps_fonte(fonte, numero, bps_marketplace=bps_mkt)
            return commissione_cents(netto, bps)
        except Exception:
            pass
        return max(0, netto * _bps // 10000)

    def _tassa_alloggio(slug, *, notti, ospiti, imponibile):
        # tassa di soggiorno dichiarata dall'host per la sua citta'; ignota -> 0 (mai inventare)
        try:
            from fase66_tassa_soggiorno import calcola_tassa
            regola = catalogo.regola_tassa_di(slug) if catalogo is not None else None
            if regola is None:
                return 0
            return calcola_tassa(regola, notti=notti, ospiti=ospiti,
                                 imponibile_cents=imponibile).tassa_cents
        except Exception:
            return 0

    _tasso = None
    _tassi = None
    if cfg.oxr_app_id:
        try:
            from fase99_multicurrency import crea_provider_tassi
            _tassi = crea_provider_tassi(cfg.oxr_app_id)
            _tassi.scalda()                              # scalda la cache tassi in SFONDO (non blocca il boot)
            _tasso = lambda da, a: _tassi.tasso(da, a)   # noqa: E731
            componenti.append("cambio_indicativo(99)")
        except Exception:
            _tasso = None
            _tassi = None

    # SINGLE-USE del Credito Fondatore/Viaggio (fase167): un credito si spende UNA volta sola.
    # Iniettato nel concierge (check al preventivo) e consumato dal server alla finalizzazione.
    from fase167_credito_single_use import crea_registro_crediti_usati
    credito_usati = crea_registro_crediti_usati(cfg.db_credito_usati)
    credito_usati.inizializza_schema()
    componenti.append("credito_single_use(167)")

    concierge = crea_protocollo(inventario, bytes(cfg.segreto_hmac), catalogo=catalogo,
                                valuta=cfg.valuta, link_pagamento=link_pagamento,
                                commissione=lambda netto: max(0, netto * _bps // 10000),
                                commissione_alloggio=_comm_alloggio,
                                tassa_alloggio=_tassa_alloggio, tasso_cambio=_tasso,
                                psp_bps=cfg.psp_bps, credito_store=credito_usati)
    componenti.append("concierge(59)")

    # 3c) smart-pass per il self check-in (incluso nel voucher)
    emettitore_pass = None
    if cfg.con_smartpass:
        from fase64_smartpass import EmettitorePass
        emettitore_pass = EmettitorePass(firma)
        componenti.append("smartpass(64)")
    # 3c-bis) CHECK-IN DIGITALE (pre-registrazione ospiti -> sblocco smart-pass) — fase127
    checkin = None
    if emettitore_pass is not None:
        from fase127_checkin_digitale import crea_checkin_digitale
        checkin = crea_checkin_digitale(cfg.db_checkin, emettitore_pass)
        checkin.inizializza_schema()
        componenti.append("checkin_digitale(127)")

    # 3e) registro host self-service (l'host si iscrive e si carica DA SOLO)
    registro_host = None
    if cfg.con_registrazione_host:
        from fase88_registro_host import crea_registro_host
        registro_host = crea_registro_host(cfg.db_registro_host, bytes(cfg.segreto_hmac))
        _ctx_host["reg"] = registro_host        # attiva il resolver host-aware del concierge
        componenti.append("registro_host(88)")

    # 3f) viral loop: un host iscritto ne porta altri (referral, crediti non-cashabili)
    viral = None
    if cfg.con_viral:
        from fase76_viral_loop import crea_viral_loop
        # signup: €10 al NUOVO host (referee), €0 al referente (che prende €40 alla QUALIFICA)
        viral = crea_viral_loop(cfg.db_viral, bytes(cfg.segreto_hmac),
                                credito_referente_cents=0,
                                credito_referee_cents=cfg.referral_benvenuto_cents)
        componenti.append("viral(76)")

    # 3f-bis) messaggistica host-guest (thread per prenotazione, mascheramento PII)
    from fase113_messaggistica import crea_messaggistica
    messaggistica = crea_messaggistica(cfg.db_messaggi)
    messaggistica.inizializza_schema()
    componenti.append("messaggistica(113)")

    from fase158_domanda import crea_gestore_domanda
    domanda = crea_gestore_domanda(cfg.db_domanda, firma=firma)
    domanda.inizializza_schema()
    componenti.append("domanda/waitlist(158)")

    from fase160_escrow_garanzia import crea_escrow_garanzia
    garanzia = crea_escrow_garanzia(cfg.db_garanzia)
    garanzia.inizializza_schema()
    componenti.append("escrow_garanzia(160)")

    from fase162_pagamenti_pendenti import crea_pagamenti_pendenti
    pagamenti_pendenti = crea_pagamenti_pendenti(cfg.db_pendenti)
    pagamenti_pendenti.inizializza_schema()
    componenti.append("pagamenti_pendenti(162)")

    from fase147_tassa_comunale import crea_tassa_comunale
    tassa_comunale = crea_tassa_comunale(cfg.db_tassa_comunale)
    tassa_comunale.inizializza_schema()
    componenti.append("ledger_tassa(147)")

    from fase131_payout_dashboard import crea_payout_dashboard
    payout = crea_payout_dashboard(cfg.db_payout)

    # KILL-SWITCH GLOBALE (fase191): DORMIENTE. Flag durevole accanto ai dati (o solo-env se in RAM).
    import os as _os_bg
    from fase191_blocco_globale import crea_blocco_globale
    _flag_bg = cfg.file_blocco_globale or (
        _os_bg.path.join(_os_bg.path.dirname(cfg.db_payout) or ".", "blocco_globale.flag")
        if cfg.db_payout not in ("", ":memory:") else "")
    blocco_globale = crea_blocco_globale(_flag_bg)
    payout.inizializza_schema()
    componenti.append("payout_dashboard(131)")

    # 3f-sexies) FINANCIAL CONTROLLER (fase177): giornale immutabile + note + offset
    # penali. ISOLATO: se non parte, il sistema vive (la penale resta annotata nel
    # pendente e la riasserzione dello sweeper la registra appena il modulo torna).
    finanza = None
    try:
        from fase177_financial_controller import crea_financial_controller
        finanza = crea_financial_controller(cfg.db_finanza)
        finanza.inizializza_schema()
        componenti.append("financial_controller(177)")
    except Exception:
        # nato a meta' = NON nato: mai un controller senza schema cablato al
        # money-path (503 a raffica sulle cancellazioni)
        finanza = None
        logger.warning("financial controller NON attivo (ISOLATO)", exc_info=True)

    # 3f-octies) KYC HOST (fase143): registro degli ESITI di verifica identita' (mai
    # documenti: identificazione elettronica via provider, DSA art.30). ISOLATO.
    kyc = None
    try:
        from fase143_kyc_host import crea_kyc_host
        kyc = crea_kyc_host(cfg.db_kyc)
        kyc.inizializza_schema()
        componenti.append("kyc_host(143)")
    except Exception:
        kyc = None
        logger.warning("kyc host NON attivo (ISOLATO)", exc_info=True)

    # 3f-septies) BUNKER super-admin (fase180): 2FA TOTP + sessione blindata. GATED da
    # bunker_totp_secret/recovery (env in prod). Se spento, gli endpoint /bunker
    # rispondono "non configurato" (mai un crash), e le distruttive restano come oggi
    # finche' l'Enforcement (incremento 3) non le sposta dietro il bunker.
    bunker = None
    try:
        from fase180_bunker import crea_bunker
        bunker = crea_bunker(firma, totp_secret=cfg.bunker_totp_secret,
                             password=cfg.bunker_password,
                             break_glass=cfg.bunker_recovery)
        if bunker.configurato:
            componenti.append("bunker(180)")
    except Exception:
        bunker = None
        logger.warning("bunker NON attivo (ISOLATO)", exc_info=True)

    # 3f-quinquies) GEOCODER (città->coordinate, gratis via Nominatim + cache): per la mappa.
    # GATED da con_geocoding (default OFF: i test non toccano la rete). ON in prod.
    geocoder = None
    if cfg.con_geocoding:
        from fase166_geocoder import crea_geocoder
        geocoder = crea_geocoder(cfg.db_geocache)
        componenti.append("geocoder(166)")

    # 3f-quinquies-bis) PROVIDER POI (fase175): luoghi notevoli vicini all'annuncio da OSM,
    # per arricchire il MOTORE SEO (fase173/171). GATED da con_poi (default OFF: rete). ON in prod.
    poi_provider = None
    if cfg.con_poi:
        from fase175_poi_osm import crea_provider_poi
        poi_provider = crea_provider_poi(cfg.db_poicache)
        componenti.append("poi_osm(175)")

    # 3f-quater) registro FIRMATO delle accettazioni del contratto host (prova legale opponibile)
    from fase163_accettazioni import crea_registro_accettazioni
    accettazioni = crea_registro_accettazioni(cfg.db_accettazioni, bytes(cfg.segreto_hmac))
    componenti.append("accettazioni(163)")

    # 3f-quinquies) MARCA TEMPORALE (fase184): l'ora dei registri certificata da un TERZO.
    # Le firme HMAC sono NOSTRE, quindi l'ora la dichiariamo noi; una marca RFC 3161 la
    # fa attestare da un'Autorita' esterna. Isolata e mai bloccante: se non parte, il
    # resto della macchina prosegue identico.
    marche = None
    from fase184_marca_temporale import attivo as marca_attiva
    if marca_attiva():
        from fase184_marca_temporale import crea_archivio_marche
        marche = crea_archivio_marche(cfg.db_marche)
        if marche is not None:
            componenti.append("marca_temporale(184)")
        else:
            avvisi.append("marca temporale: archivio non apribile (proseguo senza)")

    # 3f-ter) referral host-porta-host (codice firmato + bonus crediti non-cashabili)
    from fase109_referral_host import crea_referral_host
    referral = crea_referral_host(bytes(cfg.segreto_hmac), cfg.file_referral)
    componenti.append("referral_host(109)")

    # 3g) motori stateless cablati (calcolatori puri, default sicuri)
    from fase66_tassa_soggiorno import RegistroTasse
    from fase74_sensory_engine import crea_sensory_engine
    from fase78_sleep_guarantee import crea_sleep_guarantee
    tasse = RegistroTasse.da_env()       # città->regola da env TASSE_SOGGIORNO (default 0)
    sensory = crea_sensory_engine()
    sleep = crea_sleep_guarantee()
    componenti.append("motori(66,74,78)")

    # 3h) motori con stato (factory dedicate); niche/commitment/portability = librerie pure
    from fase65_split_payment import crea_gestore_split
    from fase67_coda_intelligente import crea_gestore_coda
    from fase70_turnover import crea_gestore_turnover
    from fase72_digital_twin import crea_digital_twin
    from fase75_guardian_engine import crea_guardian
    from fase62_predictive_noshow import crea_gestore_noshow
    from fase79_dichiarazione import crea_dichiarazione
    # lo split ha rotte VIVE (/api/split/*) e il server prod e' MULTI-THREAD
    # (ThreadingHTTPServer): con ":memory:" la connessione condivisa collide
    # sotto pagamenti simultanei (bug #36: 538/960 in 503) e i conti spariscono
    # al riavvio -> in prod DEVE stare su file (env DB_SPLIT)
    split = crea_gestore_split(cfg.db_split)
    # la coda custodisce DEPOSITI (denaro): il percorso e' configurabile perche'
    # all'accensione DEVE stare su file (":memory:" = depositi persi al riavvio
    # + connessione condivisa fragile fra thread, stessa classe artefatto fase76)
    coda = crea_gestore_coda(cfg.db_coda)
    turnover = crea_gestore_turnover(":memory:")
    digital_twin = crea_digital_twin(":memory:")
    guardian = crea_guardian()
    dichiarazione = crea_dichiarazione(":memory:")
    noshow = crea_gestore_noshow(":memory:")
    componenti.append("motori(62,65,67,70,72,75,79)")

    # 3d) email del voucher (GATED da SMTP): senza host -> nessuna email (come oggi)
    from fase86_email import crea_provider_email
    email_provider = crea_provider_email(cfg.smtp_host, cfg.smtp_port, cfg.smtp_user,
                                         cfg.smtp_password, cfg.email_mittente)
    if email_provider is not None:
        componenti.append("email(86)")
    else:
        avvisi.append("SMTP non configurato -> nessuna email voucher (gated)")

    # 3e) notifiche prenotazione all'HOST (email sempre se SMTP c'e'; WhatsApp/Telegram se gated)
    from fase152_notifiche_prenotazione import crea_notificatore_prenotazione
    import os as _os152
    notificatore_prenotazione = crea_notificatore_prenotazione(
        email_provider=email_provider,
        whatsapp_token=cfg.whatsapp_token, whatsapp_phone_id=cfg.whatsapp_phone_id,
        telegram_bot_token=_os152.environ.get("TELEGRAM_BOT_TOKEN", ""))
    if notificatore_prenotazione.attivo():
        componenti.append("avvisi_host(152)")
    else:
        avvisi.append("nessun canale avviso host -> l'host non riceve notifiche prenotazione")

    # 3i) marketing 360 + canali social reali (GATED da env: senza chiavi, nessun canale).
    #     Testi scritti dall'AI a rotazione (Groq/Gemini, fase164/165) se le chiavi ci sono,
    #     con fallback SICURO al deterministico. Pool inerte senza chiavi.
    from fase90_marketing import crea_motore_marketing
    from fase91_canali_social import crea_canali_da_env
    import os as _os
    try:
        from fase165_adattatori_esterni import crea_pool_testo_da_env
        _pool_testo = crea_pool_testo_da_env(
            _os.environ, percorso_stato=_os.environ.get("POOL_AI_STATO") or None)
    except Exception:
        _pool_testo = None
    marketing = crea_motore_marketing(canali=crea_canali_da_env(),
                                      email_provider=email_provider, pool_testo=_pool_testo)
    componenti.append("marketing(90,91)")

    # 3b) recensioni verificate (opzionale): registro + emettitore del diritto
    recensioni = None
    emettitore = None
    if cfg.con_recensioni:
        from fase59_concierge import FirmaQuote
        from fase63_recensioni import EmettitoreDiritto, crea_registro_recensioni
        recensioni = crea_registro_recensioni(cfg.db_recensioni, bytes(cfg.segreto_hmac))
        emettitore = EmettitoreDiritto(FirmaQuote(bytes(cfg.segreto_hmac)))
        componenti.append("recensioni(63)")

    # 4) server MCP (opzionale)
    mcp = None
    if cfg.con_mcp:
        from fase60_mcp_server import crea_server_mcp
        mcp = crea_server_mcp(concierge)
        componenti.append("mcp(60)")
    else:
        avvisi.append("mcp disattivato (con_mcp=False)")

    # 5) sentinel FIM (opzionale, difesa cartella)
    sentinel = None
    if cfg.con_sentinel:
        if cfg.cartella_sentinel:
            from fase80_sentinel import Sentinel
            sentinel = Sentinel(cartella=cfg.cartella_sentinel, estensioni=(".py",))
            sentinel.istantanea()
            componenti.append("sentinel(80)")
        else:
            avvisi.append("sentinel richiesto ma cartella_sentinel assente -> saltato")

    report = {"abilitato": True, "componenti": componenti, "avvisi": avvisi,
              "money_path_pronto": True, "valuta": cfg.valuta}
    return SistemaCasaVIP(cfg, report, catalogo=catalogo, inventario=inventario,
                          concierge=concierge, mcp=mcp, sentinel=sentinel,
                          recensioni=recensioni, emettitore_recensioni=emettitore,
                          firma=firma, emettitore_pass=emettitore_pass,
                          email_provider=email_provider, registro_host=registro_host,
                          viral=viral, tasse=tasse, sensory=sensory, sleep=sleep,
                          split=split, coda=coda, turnover=turnover,
                          digital_twin=digital_twin, guardian=guardian,
                          dichiarazione=dichiarazione, noshow=noshow, marketing=marketing,
                          messaggistica=messaggistica, referral=referral,
                          notificatore_prenotazione=notificatore_prenotazione,
                          domanda=domanda, garanzia=garanzia,
                          pagamenti_pendenti=pagamenti_pendenti, tassa_comunale=tassa_comunale,
                          payout=payout, accettazioni=accettazioni, marche=marche, stripe=provider,
                          connect=_connect, carta=_carta, geocoder=geocoder, checkin=checkin,
                          poi_provider=poi_provider, credito_usati=credito_usati,
                          finanza=finanza, bunker=bunker, kyc=kyc, tassi=_tassi,
                          blocco_globale=blocco_globale)
