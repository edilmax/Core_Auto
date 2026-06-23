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
    commissione_bps: int = 500          # commissione CORE in basis-point (500=5%); = mostrata
    stripe_secret_key: str = ""        # gated: se vuoto, niente link di pagamento
    stripe_success_url: str = ""
    stripe_cancel_url: str = ""
    stripe_webhook_secret: str = ""    # gated: per verificare i webhook di Stripe
    smtp_host: str = ""                 # gated: se vuoto, niente email
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_mittente: str = ""
    con_mcp: bool = True
    con_recensioni: bool = True
    con_smartpass: bool = True
    con_registrazione_host: bool = True
    con_viral: bool = True
    db_recensioni: str = ":memory:"
    db_registro_host: str = ":memory:"
    db_viral: str = ":memory:"
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
    _bps = cfg.commissione_bps if isinstance(cfg.commissione_bps, int) and \
        0 <= cfg.commissione_bps <= 10000 else 500
    concierge = crea_protocollo(inventario, bytes(cfg.segreto_hmac), catalogo=catalogo,
                                valuta=cfg.valuta, link_pagamento=link_pagamento,
                                commissione=lambda netto: max(0, netto * _bps // 10000))
    componenti.append("concierge(59)")

    # 3c) smart-pass per il self check-in (incluso nel voucher)
    emettitore_pass = None
    if cfg.con_smartpass:
        from fase64_smartpass import EmettitorePass
        emettitore_pass = EmettitorePass(firma)
        componenti.append("smartpass(64)")

    # 3e) registro host self-service (l'host si iscrive e si carica DA SOLO)
    registro_host = None
    if cfg.con_registrazione_host:
        from fase88_registro_host import crea_registro_host
        registro_host = crea_registro_host(cfg.db_registro_host, bytes(cfg.segreto_hmac))
        componenti.append("registro_host(88)")

    # 3f) viral loop: un host iscritto ne porta altri (referral, crediti non-cashabili)
    viral = None
    if cfg.con_viral:
        from fase76_viral_loop import crea_viral_loop
        viral = crea_viral_loop(cfg.db_viral, bytes(cfg.segreto_hmac))
        componenti.append("viral(76)")

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
    split = crea_gestore_split(":memory:")
    coda = crea_gestore_coda(":memory:")
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
                          dichiarazione=dichiarazione, noshow=noshow)
