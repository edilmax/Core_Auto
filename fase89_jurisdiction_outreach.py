"""
CORE_AUTO - Fase 89: Jurisdiction B2B Radar & Outreach (acquisizione host, SOLO dove è lecito).

Obiettivo: trovare contatti business di albergatori/osti da FONTI LECITE e contattarli con
l'offerta "Prima Emilia" (commissione = 5% sotto i colossi) SOLO nei mercati dove il
cold-email B2B è legale, nella lingua del destinatario.

CONFINI CABLATI (non aggirabili dal codice):
  - NESSUNO scraping/evasione qui. La ricerca passa per `FonteContatti` (abstraction): le
    implementazioni REALI devono usare fonti LECITE — API ufficiali (es. Google Places, a
    pagamento, nel rispetto dei ToS) o directory B2B con contatti business PUBBLICI. Questo
    modulo ne fornisce solo uno STUB in-memory (zero rete) per i test.
  - JURISDICTION GATE fail-closed: si contatta SOLO chi sta in una giurisdizione che
    l'operatore ha ESPLICITAMENTE abilitato come "B2B cold-email legale" (default minimale,
    UE esclusa). La legalità di ogni paese è responsabilità dell'operatore: il gate la fa
    rispettare, non la indovina.
  - SOLO contatti BUSINESS PUBBLICI. OPT-OUT sovrano (chi rifiuta non è MAI più contattato).
  - Email onesta + lingua del destinatario + riga di disiscrizione obbligatoria.

Commissione nell'email = `commissione_sotto_concorrenza`: min(colossi) − margine (default 5%),
con floor/cap. Autonomo, deterministico, cents/bps interi.

BLINDATO: nessuna funzione solleva; input invalido -> escluso/0; sender e fonte iniettabili
(test deterministici, niente rete). Vincitrice del benchmark: gate-first + fonte-astratta +
opt-out durevole (vs scraper-di-massa = illegale/ban; vs invio-cieco = viola le giurisdizioni).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("core_auto.jurisdiction_outreach")

# Giurisdizioni dove il cold-email B2B è generalmente ammesso (con opt-out): l'operatore
# le abilita SOTTO la propria responsabilità legale. Default minimale; UE/UK esclusi.
ALLOW_LIST_DEFAULT = ("US",)

# Paese ISO -> lingua dell'email (estendibile).
LINGUA_PER_PAESE = {
    "US": "en", "GB": "en", "IE": "en", "AU": "en", "CA": "en",
    "ES": "es", "MX": "es", "AR": "es", "CO": "es", "CL": "es", "PE": "es",
    "BR": "pt", "PT": "pt", "FR": "fr", "DE": "de", "AT": "de", "IT": "it",
}


def _bps_valido(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 10000


def commissione_sotto_concorrenza(concorrenti_bps: Any, *, margine_bps: int = 500,
                                  floor_bps: int = 300, cap_bps: int = 2000,
                                  default_bps: int = 1000) -> int:
    """La NOSTRA commissione = min(colossi) − margine, dentro [floor, cap]. Se non ci sono
    benchmark validi -> default. Tutto in basis-point interi (mai float)."""
    validi = []
    if isinstance(concorrenti_bps, dict):
        validi = [v for v in concorrenti_bps.values() if _bps_valido(v)]
    elif isinstance(concorrenti_bps, (list, tuple)):
        validi = [v for v in concorrenti_bps if _bps_valido(v)]
    if not validi:
        base = default_bps
    else:
        base = min(validi) - max(0, int(margine_bps))
    return max(int(floor_bps), min(int(cap_bps), base))


@dataclass(frozen=True)
class Contatto:
    nome: str
    email: str
    paese: str                       # ISO-2 (es. 'US')
    contatto_pubblico_business: bool = False
    base_legale: str = ""            # es. 'B2B_contatto_pubblico'
    fonte: str = ""                  # da quale fonte lecita proviene
    settore: str = "hospitality"


class FonteContatti:
    """Abstraction su una fonte LECITA. Le impl reali = API ufficiali / directory pubbliche.
    NIENTE scraping/evasione. `cerca` non deve mai sollevare."""
    def cerca(self, *, paese: str, settore: str = "hospitality",
              limit: int = 50) -> List[Contatto]:
        raise NotImplementedError


class FonteStub(FonteContatti):
    """Fonte in-memory per i test (zero rete). Rappresenta ciò che una fonte lecita
    restituirebbe già normalizzato (contatti business pubblici)."""
    def __init__(self, contatti: Sequence[Contatto]) -> None:
        self._c = list(contatti)

    def cerca(self, *, paese: str, settore: str = "hospitality",
              limit: int = 50) -> List[Contatto]:
        p = str(paese).upper()
        out = [c for c in self._c if c.paese.upper() == p and c.settore == settore]
        return out[:max(0, int(limit))] if isinstance(limit, int) else out


def _email_valida(v: Any) -> bool:
    return isinstance(v, str) and v.count("@") == 1 and "." in v.split("@")[-1]


class FonteAPIUfficiale(FonteContatti):
    """Fonte REALE su un'API ufficiale/directory B2B (lecita, ToS-rispettosi). GATED dalla
    chiave: senza endpoint+key non fa nessuna chiamata. `fetch(url) -> dict` iniettabile
    (test senza rete). NON scrapa: interroga UN endpoint ufficiale che l'operatore configura.
    Mappa SOLO record con email business e flag 'pubblico' (contatto pubblicato dall'attività
    per essere contattata); gli altri sono scartati."""

    def __init__(self, endpoint: str, api_key: str, *,
                 fetch: Optional[Callable[[str], Dict[str, Any]]] = None,
                 max_per_chiamata: int = 200) -> None:
        self._endpoint = endpoint or ""
        self._key = api_key or ""
        self._fetch = fetch or self._fetch_reale
        self._cap = max_per_chiamata if isinstance(max_per_chiamata, int) else 200

    def cerca(self, *, paese: str, settore: str = "hospitality",
              limit: int = 50) -> List[Contatto]:
        if not (self._endpoint and self._key):
            return []                                  # gated: nessuna fonte configurata
        try:
            from urllib.parse import urlencode
            n = min(int(limit) if isinstance(limit, int) else 50, self._cap)
            q = urlencode({"country": str(paese).upper(), "sector": settore,
                           "limit": n, "key": self._key})
            url = self._endpoint + ("&" if "?" in self._endpoint else "?") + q
            data = self._fetch(url)
        except Exception:
            logger.warning("FonteAPIUfficiale.cerca fallita (ISOLATA -> [])", exc_info=True)
            return []
        return self._mappa(data, paese)

    @staticmethod
    def _mappa(data: Any, paese: str) -> List[Contatto]:
        records = data.get("results") if isinstance(data, dict) else None
        out: List[Contatto] = []
        for r in (records or []):
            if not isinstance(r, dict):
                continue
            email = r.get("email") or r.get("business_email")
            if not _email_valida(email):
                continue                               # serve un'email
            pub = bool(r.get("is_public_business") or r.get("public"))
            if not pub:
                continue                               # solo contatti business PUBBLICI
            out.append(Contatto(
                nome=str(r.get("name", "")), email=email,
                paese=str(r.get("country", paese)).upper(),
                contatto_pubblico_business=pub,
                base_legale="B2B_contatto_pubblico" if pub else "",
                fonte=str(r.get("source", "api_ufficiale")),
                settore=str(r.get("sector", "hospitality"))))
        return out

    @staticmethod
    def _fetch_reale(url: str) -> Dict[str, Any]:  # pragma: no cover
        import json
        import urllib.request
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())


def crea_fonte_api(endpoint: Optional[str], api_key: Optional[str], *,
                   fetch: Any = None) -> FonteAPIUfficiale:
    """Factory. Se endpoint/key mancano, la fonte è 'spenta' (cerca -> [])."""
    return FonteAPIUfficiale(endpoint or "", api_key or "", fetch=fetch)


# ── Email "Prima Emilia" localizzata ─────────────────────────────────────────
def _pct(bps: int) -> str:
    return "%d" % (bps // 100) if bps % 100 == 0 else "%d.%d" % (bps // 100, (bps % 100) // 10)

def _intero_bps(v: Any) -> int:
    try:
        return max(0, int(v))
    except Exception:
        return 0


def _tecnica_bps() -> int:
    """La tariffa tecnica VERA: dall'ambiente in produzione, altrimenti il default 300
    (3%) dichiarato in main_casavip.py. Mai una cifra scritta a mano qui."""
    import os
    return _intero_bps(os.environ.get("PAGAMENTO_BPS", "300")) or 300


# TRASPARENZA (2026-07-21). Queste email vanno a HOST VERI. Prima promettevano una
# percentuale DERIVATA dai concorrenti (min(colossi) - 5%), cioe' un numero che il nostro
# motore NON applica, e tacevano la tariffa tecnica sempre dovuta: la stessa mancanza
# chiusa sulle pagine e sull'email di benvenuto. Ora {pct} e' la cifra DEI COLOSSI (solo
# confronto), le NOSTRE cifre arrivano da fase98 e il {tecnica}% e' dichiarato apertamente.
_TEMPLATE = {
    "en": ('Lower commission for your property — join Prima Emilia',
           'Hello {nome},\n\nWe are a new company in the hospitality booking sector. Our commission is {promo}% for your first {giorni} days, then {fase1}%, then {regime}% — against the {pct}% and more of the major platforms. Only {diretto}% on bookings from your own clients, and the guest always pays 0%.\n\nOne thing is always due, including during the {promo}% period: a {tecnica}% technical fee covering the card cost. We earn nothing on it, and we prefer telling you now rather than after you sign.\n\nWould you like to join and collaborate with us in our founding class, Prima Emilia?\n\nJust reply to this email.\n\n— BookinVIP\n\nTo stop receiving these messages: {optout}\n'),
    "es": ('Comisión más baja para tu alojamiento — únete a Prima Emilia',
           'Hola {nome},\n\nSomos una nueva empresa del sector de reservas. Nuestra comisión es del {promo}% durante tus primeros {giorni} días, luego {fase1}%, luego {regime}% — frente al {pct}% o más de las grandes plataformas. Solo {diretto}% en las reservas de tus propios clientes, y el huésped siempre paga 0%.\n\nUna cosa se debe siempre, también durante el {promo}%: una tarifa técnica del {tecnica}% que cubre el coste de la tarjeta. No ganamos nada con ella y preferimos decírtelo ahora, no después de firmar.\n\n¿Quieres unirte y colaborar con nosotros en nuestra clase fundadora, Prima Emilia?\n\nResponde a este correo.\n\n— BookinVIP\n\nPara dejar de recibir estos mensajes: {optout}\n'),
    "pt": ('Comissão mais baixa para o seu alojamento — junte-se à Prima Emilia',
           'Olá {nome},\n\nSomos uma nova empresa no setor de reservas. A nossa comissão é de {promo}% nos seus primeiros {giorni} dias, depois {fase1}%, depois {regime}% — face aos {pct}% ou mais das grandes plataformas. Apenas {diretto}% nas reservas dos seus próprios clientes, e o hóspede paga sempre 0%.\n\nUma coisa é sempre devida, mesmo durante os {promo}%: uma taxa técnica de {tecnica}% que cobre o custo do cartão. Não ganhamos nada com ela e preferimos dizê-lo já, não depois de assinar.\n\nQuer participar e colaborar connosco na nossa classe fundadora, Prima Emilia?\n\nResponda a este email.\n\n— BookinVIP\n\nPara não receber mais estas mensagens: {optout}\n'),
    "fr": ('Commission plus basse pour votre hébergement — rejoignez Prima Emilia',
           "Bonjour {nome},\n\nNous sommes une nouvelle société du secteur des réservations. Notre commission est de {promo}% pendant vos {giorni} premiers jours, puis {fase1}%, puis {regime}% — face aux {pct}% et plus des grandes plateformes. Seulement {diretto}% sur les réservations de vos propres clients, et le voyageur paie toujours 0%.\n\nUne chose reste toujours due, même pendant le {promo}% : des frais techniques de {tecnica}% qui couvrent le coût de la carte. Nous n'y gagnons rien et nous préférons vous le dire maintenant, pas après signature.\n\nSouhaitez-vous nous rejoindre dans notre classe fondatrice, Prima Emilia ?\n\nRépondez à cet email.\n\n— BookinVIP\n\nPour ne plus recevoir ces messages : {optout}\n"),
    "de": ('Niedrigere Provision für Ihre Unterkunft — Prima Emilia',
           'Hallo {nome},\n\nWir sind ein neues Unternehmen im Buchungssektor. Unsere Provision beträgt {promo}% in Ihren ersten {giorni} Tagen, dann {fase1}%, dann {regime}% — gegenüber {pct}% und mehr bei den großen Plattformen. Nur {diretto}% bei Buchungen Ihrer eigenen Kunden, und der Gast zahlt immer 0%.\n\nEines ist immer fällig, auch während der {promo}%: eine technische Gebühr von {tecnica}%, die die Kartenkosten deckt. Daran verdienen wir nichts, und wir sagen es Ihnen lieber jetzt als nach der Unterschrift.\n\nMöchten Sie unserer Gründerklasse Prima Emilia beitreten?\n\nAntworten Sie einfach auf diese E-Mail.\n\n— BookinVIP\n\nZum Abbestellen: {optout}\n'),
    "it": ('Commissione più bassa per la tua struttura — entra in Prima Emilia',
           "Ciao {nome},\n\nSiamo una nuova società del settore prenotazioni. La nostra commissione è {promo}% per i tuoi primi {giorni} giorni, poi {fase1}%, poi {regime}% — contro il {pct}% e oltre dei colossi. Solo {diretto}% sulle prenotazioni dei tuoi clienti, e l'ospite paga sempre 0%.\n\nUna cosa è sempre dovuta, anche durante lo {promo}%: una tariffa tecnica del {tecnica}% che copre il costo della carta. Su quella non guadagniamo nulla, e preferiamo dirtelo adesso invece che dopo la firma.\n\nVuoi partecipare e collaborare con noi nella nostra classe fondatrice, Prima Emilia?\n\nRispondi a questa email.\n\n— BookinVIP\n\nPer non ricevere più questi messaggi: {optout}\n"),
}


def componi_email_prima_emilia(contatto: Contatto, nostra_bps: int, *,
                               link_opt_out: str, lingua: Optional[str] = None
                               ) -> Optional[Tuple[str, str, str]]:
    """Ritorna (lingua, oggetto, corpo) nella lingua del destinatario. None se manca
    l'opt-out (obbligatorio) o l'email non è valida."""
    if not _email_valida(getattr(contatto, "email", None)):
        return None
    if not (isinstance(link_opt_out, str) and link_opt_out.strip()):
        return None                                  # opt-out OBBLIGATORIO
    lng = lingua or LINGUA_PER_PAESE.get(str(contatto.paese).upper(), "en")
    oggetto, corpo = _TEMPLATE.get(lng, _TEMPLATE["en"])
    nome = contatto.nome or {"en": "Hello", "es": "Hola", "it": "Gentile struttura"}.get(lng, "Hello")
    from fase98_policy_commissione import (BPS_DIRETTO, LANCIO_BPS_FASE1,
                                           LANCIO_BPS_REGIME, LANCIO_GIORNI_GRATIS)
    testo = corpo.format(
        nome=nome, optout=link_opt_out.strip(),
        pct=_pct(_intero_bps(nostra_bps) + 500),      # la cifra DEI COLOSSI
        promo="0", giorni=LANCIO_GIORNI_GRATIS,
        fase1=_pct(LANCIO_BPS_FASE1), regime=_pct(LANCIO_BPS_REGIME),
        diretto=_pct(BPS_DIRETTO), tecnica=_pct(_tecnica_bps()))
    return lng, oggetto, testo


# ── Motore: gate + composizione + invio (sender iniettato) ───────────────────
class MotoreRadarOutreach:
    def __init__(self, *, giurisdizioni_permesse: Sequence[str] = ALLOW_LIST_DEFAULT,
                 link_opt_out: str = "https://bookinvip.com/stop") -> None:
        self._permesse = {str(g).upper() for g in (giurisdizioni_permesse or ()) if str(g)}
        self._optout = set()                         # email soppresse (sovrane)
        self._link_optout = link_opt_out

    def opt_out(self, email: str) -> None:
        if isinstance(email, str) and email:
            self._optout.add(email.strip().lower())

    def consentito(self, c: Contatto) -> Tuple[bool, str]:
        """IL GATE, fail-closed."""
        if not isinstance(c, Contatto) or not _email_valida(c.email):
            return False, "contatto_non_valido"
        if c.email.strip().lower() in self._optout:
            return False, "opt_out"                  # vince su tutto
        if str(c.paese).upper() not in self._permesse:
            return False, "giurisdizione_non_permessa"
        if not c.contatto_pubblico_business:
            return False, "non_contatto_pubblico"
        return True, ""

    def esegui(self, fonte: FonteContatti, *, paese: str, concorrenti_bps: Any,
               invia: Callable[[str, str, str, str], bool],
               settore: str = "hospitality", limit: int = 50) -> Dict[str, Any]:
        """Cerca (fonte lecita) -> gate -> compone email localizzata -> invia (sender
        iniettato). Ritorna un report con conteggi e motivi. Best-effort, mai solleva."""
        nostra_bps = commissione_sotto_concorrenza(concorrenti_bps)
        rep: Dict[str, Any] = {"nostra_commissione_bps": nostra_bps, "trovati": 0,
                               "inviati": 0, "bloccati": 0, "motivi": {}}
        try:
            contatti = fonte.cerca(paese=paese, settore=settore, limit=limit)
        except Exception:
            logger.warning("fonte.cerca fallita (ISOLATA)", exc_info=True)
            return rep
        for c in (contatti or []):
            rep["trovati"] += 1
            ok, motivo = self.consentito(c)
            if not ok:
                rep["bloccati"] += 1
                rep["motivi"][motivo] = rep["motivi"].get(motivo, 0) + 1
                continue
            comp = componi_email_prima_emilia(c, nostra_bps, link_opt_out=self._link_optout)
            if comp is None:
                rep["bloccati"] += 1
                rep["motivi"]["email_non_componibile"] = rep["motivi"].get(
                    "email_non_componibile", 0) + 1
                continue
            lng, oggetto, corpo = comp
            try:
                if invia(c.email, oggetto, corpo, lng):
                    rep["inviati"] += 1
            except Exception:
                logger.warning("invio fallito (ISOLATO)", exc_info=True)
        return rep
