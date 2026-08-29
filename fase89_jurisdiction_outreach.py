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
    """La tariffa tecnica VERA, presa dalla FONTE UNICA e mai riscritta qui.

    ⛔ RIPARATO IL 2026-08-29 (giro B1). Questa funzione aveva un ripiego SUO -- 400, cioe'
    il 4% -- e la sua stessa docstring giurava di prenderlo da `main_casavip.py`, che dice
    500. Il commento scritto per impedire l'errore era la cosa che lo nascondeva: chi
    passava di qui leggeva «lo prendo da main» e non andava a controllare.
    E non era teoria. `collaudi/audit/16_ambiente_vps.md` ha misurato il 2026-08-25 che in
    produzione `PAGAMENTO_BPS` NON e' impostata: valeva il ripiego. Quindi queste email --
    che vanno a host VERI -- promettevano una tariffa che la cassa non pratica."""
    from fase98_policy_commissione import tariffa_tecnica_bps
    return tariffa_tecnica_bps()


def _tecnica_estera_bps() -> int:
    """La tariffa sugli annunci prezzati fuori euro: piu' alta perche' il gateway deve
    CONVERTIRE, e la conversione la paga chi incassa. Stessa fonte unica."""
    from fase98_policy_commissione import tariffa_tecnica_bps
    return tariffa_tecnica_bps(valuta_estera=True)


# Lingue che scrivono i decimali con la VIRGOLA. Le altre usano il punto.
# ⛔ Scriverlo sempre con la virgola sarebbe stato il difetto che l'audit ha gia' trovato
# altrove: una convenzione decimale sola applicata al mondo intero.
_DECIMALE_VIRGOLA = ("it", "es", "fr", "de", "pt")


def _tecnica_fisso(lang: Any = "it") -> str:
    """La quota FISSA per transazione, scritta come la legge una persona in QUELLA lingua.

    Il gateway la prende a ogni pagamento, su qualunque importo: tacerla faceva sembrare
    la tariffa una percentuale pura, e su una prenotazione piccola quella differenza si
    vede. Stessa fonte unica: qui non c'e' nessun numero scritto a mano."""
    from fase98_policy_commissione import tariffa_tecnica_fisso_cents
    c = tariffa_tecnica_fisso_cents()
    sep = "," if str(lang or "it").lower()[:2] in _DECIMALE_VIRGOLA else "."
    return "%d%s%02d" % (c // 100, sep, c % 100)


# TRASPARENZA (2026-07-21). Queste email vanno a HOST VERI. Prima promettevano una
# percentuale DERIVATA dai concorrenti (min(colossi) - 5%), cioe' un numero che il nostro
# motore NON applica, e tacevano la tariffa tecnica sempre dovuta: la stessa mancanza
# chiusa sulle pagine e sull'email di benvenuto. Ora {pct} e' la cifra DEI COLOSSI (solo
# confronto), le NOSTRE cifre arrivano da fase98 e il {tecnica}% e' dichiarato apertamente.
_TEMPLATE = {
    "en": ('Lower commission for your property — join Prima Emilia',
           'Hello {nome},\n\nWe are a new company in the hospitality booking sector. Our commission is {promo}% for your first {giorni} days, then {fase1}%, then {regime}% — against the {pct}% and more of the major platforms. Only {diretto}% on bookings from your own clients, and the guest always pays 0%.\n\nOne thing we tell you before you sign, not after. For your first {giorni} days our commission is zero, and it is not a launch discount: behind this platform, for now, there is us, and nobody is paying us in these months — that is the work we are not charging you for. The only thing you pay is taking the card payment: {tecnica}% + €{fisso} per transaction. It covers collecting the money and the transfer that sends it to you; depending on the card and the amount, sometimes it costs us more and sometimes less. If you price in a currency other than the euro it becomes {estera}% + €{fisso}, because there Stripe also has to convert the money. Our commission arrives when you grow.\n\nWould you like to join and collaborate with us in our founding class, Prima Emilia?\n\nJust reply to this email.\n\n— BookinVIP\n\nTo stop receiving these messages: {optout}\n'),
    "es": ('Comisión más baja para tu alojamiento — únete a Prima Emilia',
           'Hola {nome},\n\nSomos una nueva empresa del sector de reservas. Nuestra comisión es del {promo}% durante tus primeros {giorni} días, luego {fase1}%, luego {regime}% — frente al {pct}% o más de las grandes plataformas. Solo {diretto}% en las reservas de tus propios clientes, y el huésped siempre paga 0%.\n\nUna cosa te la decimos antes de firmar, no después. Durante tus primeros {giorni} días nuestra comisión es cero, y no es un descuento de lanzamiento: detrás de esta plataforma, por ahora, estamos nosotros, y en estos meses no nos paga nadie — es ese trabajo el que no te estamos cobrando. Lo único que pagas es cobrar con la tarjeta: {tecnica}% + {fisso} € por transacción. Cubre el cobro y la transferencia que te envía el dinero; según la tarjeta y el importe, a veces nos cuesta más y a veces menos. Si pones el precio en una moneda distinta del euro sube a {estera}% + {fisso} €, porque ahí Stripe también tiene que cambiar el dinero. Nuestra comisión llega cuando creces tú.\n\n¿Quieres unirte y colaborar con nosotros en nuestra clase fundadora, Prima Emilia?\n\nResponde a este correo.\n\n— BookinVIP\n\nPara dejar de recibir estos mensajes: {optout}\n'),
    "pt": ('Comissão mais baixa para o seu alojamento — junte-se à Prima Emilia',
           'Olá {nome},\n\nSomos uma nova empresa no setor de reservas. A nossa comissão é de {promo}% nos seus primeiros {giorni} dias, depois {fase1}%, depois {regime}% — face aos {pct}% ou mais das grandes plataformas. Apenas {diretto}% nas reservas dos seus próprios clientes, e o hóspede paga sempre 0%.\n\nUma coisa dizemos-lhe antes de assinar, não depois. Nos seus primeiros {giorni} dias a nossa comissão é zero, e não é um desconto de lançamento: por trás desta plataforma, por agora, estamos nós, e nestes meses ninguém nos paga — é esse trabalho que não lhe estamos a cobrar. A única coisa que paga é receber com o cartão: {tecnica}% + {fisso} € por transação. Cobre a cobrança e a transferência que lhe envia o dinheiro; consoante o cartão e o valor, às vezes custa-nos mais e às vezes menos. Se definir o preço numa moeda diferente do euro sobe para {estera}% + {fisso} €, porque aí a Stripe também tem de converter o dinheiro. A nossa comissão chega quando o senhor crescer.\n\nQuer participar e colaborar connosco na nossa classe fundadora, Prima Emilia?\n\nResponda a este email.\n\n— BookinVIP\n\nPara não receber mais estas mensagens: {optout}\n'),
    "fr": ('Commission plus basse pour votre hébergement — rejoignez Prima Emilia',
           "Bonjour {nome},\n\nNous sommes une nouvelle société du secteur des réservations. Notre commission est de {promo}% pendant vos {giorni} premiers jours, puis {fase1}%, puis {regime}% — face aux {pct}% et plus des grandes plateformes. Seulement {diretto}% sur les réservations de vos propres clients, et le voyageur paie toujours 0%.\n\nUne chose, nous vous la disons avant la signature, pas après. Pendant vos {giorni} premiers jours notre commission est de zéro, et ce n'est pas une remise de lancement : derrière cette plateforme, pour l'instant, il y a nous, et pendant ces mois personne ne nous paie — c'est ce travail que nous ne vous facturons pas. La seule chose que vous payez, c'est l'encaissement par carte : {tecnica}% + {fisso} € par transaction. Cela couvre l'encaissement et le virement qui vous envoie l'argent ; selon la carte et le montant, cela nous coûte parfois plus et parfois moins. Si vous fixez le prix dans une devise autre que l'euro, cela passe à {estera}% + {fisso} €, car là Stripe doit aussi convertir l'argent. Notre commission arrive quand vous grandissez.\n\nSouhaitez-vous nous rejoindre dans notre classe fondatrice, Prima Emilia ?\n\nRépondez à cet email.\n\n— BookinVIP\n\nPour ne plus recevoir ces messages : {optout}\n"),
    "de": ('Niedrigere Provision für Ihre Unterkunft — Prima Emilia',
           'Hallo {nome},\n\nWir sind ein neues Unternehmen im Buchungssektor. Unsere Provision beträgt {promo}% in Ihren ersten {giorni} Tagen, dann {fase1}%, dann {regime}% — gegenüber {pct}% und mehr bei den großen Plattformen. Nur {diretto}% bei Buchungen Ihrer eigenen Kunden, und der Gast zahlt immer 0%.\n\nEines sagen wir Ihnen vor der Unterschrift, nicht danach. In Ihren ersten {giorni} Tagen beträgt unsere Provision null, und das ist kein Einführungsrabatt: hinter dieser Plattform stehen vorerst wir, und in diesen Monaten bezahlt uns niemand — genau diese Arbeit stellen wir Ihnen nicht in Rechnung. Das Einzige, was Sie zahlen, ist der Kartenempfang: {tecnica}% + {fisso} € pro Transaktion. Das deckt den Einzug und die Überweisung, die Ihnen das Geld schickt; je nach Karte und Betrag kostet es uns mal mehr und mal weniger. Wenn Sie in einer anderen Währung als dem Euro auszeichnen, steigt es auf {estera}% + {fisso} €, weil Stripe dort zusätzlich umrechnen muss. Unsere Provision kommt, wenn Sie wachsen.\n\nMöchten Sie unserer Gründerklasse Prima Emilia beitreten?\n\nAntworten Sie einfach auf diese E-Mail.\n\n— BookinVIP\n\nZum Abbestellen: {optout}\n'),
    "it": ('Commissione più bassa per la tua struttura — entra in Prima Emilia',
           "Ciao {nome},\n\nSiamo una nuova società del settore prenotazioni. La nostra commissione è {promo}% per i tuoi primi {giorni} giorni, poi {fase1}%, poi {regime}% — contro il {pct}% e oltre dei colossi. Solo {diretto}% sulle prenotazioni dei tuoi clienti, e l'ospite paga sempre 0%.\n\nUna cosa te la diciamo prima della firma, non dopo. Nei primi {giorni} giorni la nostra commissione è zero, e non è uno sconto di lancio: dietro questa piattaforma per adesso ci siamo noi, e in questi mesi non ci paga nessuno — è quel lavoro che non ti stiamo facendo pagare. L'unica cosa che paghi è incassare con la carta: {tecnica}% + {fisso} € per transazione. Copre l'incasso e il bonifico che ti manda i soldi; secondo la carta e l'importo a volte ci costa di più e a volte di meno. Se prezzi in una valuta diversa dall'euro sale a {estera}% + {fisso} €, perché lì Stripe deve anche cambiare i soldi. La nostra commissione arriva quando cresci tu.\n\nVuoi partecipare e collaborare con noi nella nostra classe fondatrice, Prima Emilia?\n\nRispondi a questa email.\n\n— BookinVIP\n\nPer non ricevere più questi messaggi: {optout}\n"),
}


# ── PRIMA ROMA: reclutamento host di Roma, 8 lingue SINCRONIZZATE con la web app ──────────
# Le stesse lingue del sito/email (it/en/es/fr/de/pt/ja/zh, fase86.LINGUE): l'host che entra
# nella web app sceglie una lingua (viaggia nel gettone) e il messaggio esce nella STESSA.
# Ripiego su INGLESE, mai italiano. Oggetto E corpo formattati con le cifre REALI di fase98.
_TEMPLATE_ROMA = {
    "it": ("A Roma pubblichi gratis: {promo}% di commissione per {giorni} giorni",
           "Ciao {nome},\n\nsto aprendo a Roma una nuova piattaforma di prenotazioni, BookinVIP, e sto scegliendo a mano i primi host della città.\n\nPerché conviene entrare adesso:\n• {promo}% di commissione per i primi {giorni} giorni — pubblichi gratis e tieni tutto.\n• Poi {fase1}% fino al primo anno, poi {regime}% a regime, contro il {pct}% e oltre di Booking e Airbnb.\n• Il tuo ospite paga sempre 0%: vede un prezzo pulito, e il tuo annuncio è più competitivo del loro.\n• Sulle prenotazioni dei tuoi clienti diretti solo {diretto}%.\n\nUna cosa te la dico prima della firma, non dopo. Nei primi {giorni} giorni la mia commissione è zero, e non è uno sconto di lancio: dietro questa piattaforma per adesso ci sono io, e in questi mesi non mi paga nessuno — è quel lavoro che non ti sto facendo pagare. L'unica cosa che paghi è incassare con la carta: {tecnica}% + {fisso} € per transazione. Copre l'incasso e il bonifico che ti manda i soldi; secondo la carta e l'importo a volte mi costa di più e a volte di meno. Se prezzi in una valuta diversa dall'euro sale a {estera}% + {fisso} €, perché lì Stripe deve anche cambiare i soldi. La mia commissione arriva quando cresci tu.\n\nIn cambio hai una piattaforma che lavora per te: calendario anti-doppia-prenotazione, pagamenti sicuri, deposito cauzionale, recensioni, sito in 13 lingue, tutto automatico. Cerco poche persone per la classe fondatrice di Roma: chi entra adesso resta il primo.\n\nRispondi a questa email e ti apro io l'account, passo passo. Bastano dieci minuti e le foto del tuo alloggio.\n\n— BookinVIP\n\nPer non ricevere più questi messaggi: {optout}\n"),
    "en": ("Publish free in Rome: {promo}% commission for {giorni} days",
           "Hi {nome},\n\nI'm launching a new booking platform in Rome, BookinVIP, and I'm hand-picking the city's first hosts.\n\nWhy it pays to join now:\n• {promo}% commission for the first {giorni} days — you publish for free and keep everything.\n• Then {fase1}% up to the first year, then {regime}% after that, against the {pct}% and more charged by Booking and Airbnb.\n• Your guest always pays 0%: they see a clean price, so your listing is more competitive than theirs.\n• On bookings from your own direct clients, only {diretto}%.\n\nOne thing I tell you before you sign, not after. For your first {giorni} days my commission is zero, and it is not a launch discount: behind this platform, for now, there is me, and nobody is paying me in these months — that is the work I am not charging you for. The only thing you pay is taking the card payment: {tecnica}% + €{fisso} per transaction. It covers collecting the money and the transfer that sends it to you; depending on the card and the amount, sometimes it costs me more and sometimes less. If you price in a currency other than the euro it becomes {estera}% + €{fisso}, because there Stripe also has to convert the money. My commission arrives when you grow.\n\nIn return you get a platform that works for you: anti-double-booking calendar, secure payments, security deposit, reviews, a site in 13 languages, all automated. I'm looking for a few people for Rome's founding class: whoever joins now stays first.\n\nJust reply to this email and I'll open your account and walk you through it. It takes ten minutes and photos of your place.\n\n— BookinVIP\n\nTo stop receiving these messages: {optout}\n"),
    "es": ("Publica gratis en Roma: {promo}% de comisión durante {giorni} días",
           "Hola {nome},\n\nestoy lanzando en Roma una nueva plataforma de reservas, BookinVIP, y estoy eligiendo a mano los primeros anfitriones de la ciudad.\n\nPor qué conviene entrar ahora:\n• {promo}% de comisión durante los primeros {giorni} días — publicas gratis y te quedas con todo.\n• Luego {fase1}% hasta el primer año, después {regime}%, frente al {pct}% o más de Booking y Airbnb.\n• Tu huésped siempre paga 0%: ve un precio limpio, así que tu anuncio es más competitivo que el de ellos.\n• En las reservas de tus propios clientes directos, solo {diretto}%.\n\nUna cosa te la digo antes de firmar, no después. Durante tus primeros {giorni} días mi comisión es cero, y no es un descuento de lanzamiento: detrás de esta plataforma, por ahora, estoy yo, y en estos meses no me paga nadie — es ese trabajo el que no te estoy cobrando. Lo único que pagas es cobrar con la tarjeta: {tecnica}% + {fisso} € por transacción. Cubre el cobro y la transferencia que te envía el dinero; según la tarjeta y el importe, a veces me cuesta más y a veces menos. Si pones el precio en una moneda distinta del euro sube a {estera}% + {fisso} €, porque ahí Stripe también tiene que cambiar el dinero. Mi comisión llega cuando creces tú.\n\nA cambio tienes una plataforma que trabaja para ti: calendario anti-sobreventa, pagos seguros, depósito, reseñas, sitio en 13 idiomas, todo automático. Busco pocas personas para la clase fundadora de Roma: quien entra ahora se queda primero.\n\nResponde a este correo y te abro yo la cuenta, paso a paso. Bastan diez minutos y las fotos de tu alojamiento.\n\n— BookinVIP\n\nPara dejar de recibir estos mensajes: {optout}\n"),
    "fr": ("Publiez gratuitement à Rome : {promo}% de commission pendant {giorni} jours",
           "Bonjour {nome},\n\nje lance à Rome une nouvelle plateforme de réservations, BookinVIP, et je choisis à la main les premiers hôtes de la ville.\n\nPourquoi entrer maintenant :\n• {promo}% de commission pendant les {giorni} premiers jours — vous publiez gratuitement et gardez tout.\n• Ensuite {fase1}% jusqu'à la première année, puis {regime}%, face aux {pct}% et plus de Booking et Airbnb.\n• Votre voyageur paie toujours 0% : il voit un prix net, votre annonce est donc plus compétitive que la leur.\n• Sur les réservations de vos propres clients directs, seulement {diretto}%.\n\nUne chose, je vous la dis avant la signature, pas après. Pendant vos {giorni} premiers jours ma commission est de zéro, et ce n'est pas une remise de lancement : derrière cette plateforme, pour l'instant, il y a moi, et pendant ces mois personne ne me paie — c'est ce travail que je ne vous facture pas. La seule chose que vous payez, c'est l'encaissement par carte : {tecnica}% + {fisso} € par transaction. Cela couvre l'encaissement et le virement qui vous envoie l'argent ; selon la carte et le montant, cela me coûte parfois plus et parfois moins. Si vous fixez le prix dans une devise autre que l'euro, cela passe à {estera}% + {fisso} €, car là Stripe doit aussi convertir l'argent. Ma commission arrive quand vous grandissez.\n\nEn échange, une plateforme qui travaille pour vous : calendrier anti-surréservation, paiements sécurisés, caution, avis, site en 13 langues, tout automatique. Je cherche quelques personnes pour la classe fondatrice de Rome : qui entre maintenant reste le premier.\n\nRépondez à cet e-mail et j'ouvre votre compte, étape par étape. Il faut dix minutes et les photos de votre logement.\n\n— BookinVIP\n\nPour ne plus recevoir ces messages : {optout}\n"),
    "de": ("In Rom kostenlos inserieren: {promo}% Provision für {giorni} Tage",
           "Hallo {nome},\n\nich starte in Rom eine neue Buchungsplattform, BookinVIP, und wähle die ersten Gastgeber der Stadt persönlich aus.\n\nWarum sich der Einstieg jetzt lohnt:\n• {promo}% Provision in den ersten {giorni} Tagen — Sie inserieren kostenlos und behalten alles.\n• Danach {fase1}% bis zum ersten Jahr, dann {regime}%, gegenüber {pct}% und mehr bei Booking und Airbnb.\n• Ihr Gast zahlt immer 0%: Er sieht einen sauberen Preis, Ihr Inserat ist also wettbewerbsfähiger als deren.\n• Auf Buchungen Ihrer eigenen Direktkunden nur {diretto}%.\n\nEines sage ich Ihnen vor der Unterschrift, nicht danach. In Ihren ersten {giorni} Tagen beträgt meine Provision null, und das ist kein Einführungsrabatt: hinter dieser Plattform stehe vorerst ich, und in diesen Monaten bezahlt mich niemand — genau diese Arbeit stelle ich Ihnen nicht in Rechnung. Das Einzige, was Sie zahlen, ist der Kartenempfang: {tecnica}% + {fisso} € pro Transaktion. Das deckt den Einzug und die Überweisung, die Ihnen das Geld schickt; je nach Karte und Betrag kostet es mich mal mehr und mal weniger. Wenn Sie in einer anderen Währung als dem Euro auszeichnen, steigt es auf {estera}% + {fisso} €, weil Stripe dort zusätzlich umrechnen muss. Meine Provision kommt, wenn Sie wachsen.\n\nIm Gegenzug eine Plattform, die für Sie arbeitet: Kalender gegen Doppelbuchungen, sichere Zahlungen, Kaution, Bewertungen, Website in 13 Sprachen, alles automatisch. Ich suche wenige Personen für die Gründerklasse Roms: Wer jetzt einsteigt, bleibt der Erste.\n\nAntworten Sie einfach auf diese E-Mail, und ich richte Ihr Konto ein, Schritt für Schritt. Es dauert zehn Minuten und die Fotos Ihrer Unterkunft.\n\n— BookinVIP\n\nZum Abbestellen dieser Nachrichten: {optout}\n"),
    "pt": ("Publique grátis em Roma: {promo}% de comissão durante {giorni} dias",
           "Olá {nome},\n\nestou a lançar em Roma uma nova plataforma de reservas, BookinVIP, e estou a escolher à mão os primeiros anfitriões da cidade.\n\nPorque compensa entrar agora:\n• {promo}% de comissão nos primeiros {giorni} dias — publica de graça e fica com tudo.\n• Depois {fase1}% até ao primeiro ano, depois {regime}%, face aos {pct}% ou mais da Booking e Airbnb.\n• O seu hóspede paga sempre 0%: vê um preço limpo, por isso o seu anúncio é mais competitivo do que o deles.\n• Nas reservas dos seus próprios clientes diretos, apenas {diretto}%.\n\nUma coisa digo-lhe antes de assinar, não depois. Nos seus primeiros {giorni} dias a minha comissão é zero, e não é um desconto de lançamento: por trás desta plataforma, por agora, estou eu, e nestes meses ninguém me paga — é esse trabalho que não lhe estou a cobrar. A única coisa que paga é receber com o cartão: {tecnica}% + {fisso} € por transação. Cobre a cobrança e a transferência que lhe envia o dinheiro; consoante o cartão e o valor, às vezes custa-me mais e às vezes menos. Se definir o preço numa moeda diferente do euro sobe para {estera}% + {fisso} €, porque aí a Stripe também tem de converter o dinheiro. A minha comissão chega quando o senhor crescer.\n\nEm troca, uma plataforma que trabalha por si: calendário anti-sobre-reserva, pagamentos seguros, caução, avaliações, site em 13 línguas, tudo automático. Procuro poucas pessoas para a classe fundadora de Roma: quem entra agora fica em primeiro.\n\nResponda a este email e eu abro-lhe a conta, passo a passo. Bastam dez minutos e as fotos do seu alojamento.\n\n— BookinVIP\n\nPara deixar de receber estas mensagens: {optout}\n"),
    "ja": ("ローマで無料掲載：最初の{giorni}日間は手数料{promo}%",
           "{nome} 様\n\nローマで新しい予約プラットフォーム BookinVIP を立ち上げており、街で最初のホストを一人ずつお選びしています。\n\n今参加する理由：\n・最初の{giorni}日間は手数料{promo}% — 無料で掲載でき、売上はすべてお客様のものです。\n・その後は1年目まで{fase1}%、以降は{regime}% — Booking や Airbnb の{pct}%以上に対して。\n・ゲストの手数料は常に0%：明朗な価格が表示されるため、あなたの掲載は他社より競争力があります。\n・あなたご自身の直接のお客様の予約は{diretto}%のみ。\n\n署名の後ではなく、先にお伝えします。最初の{giorni}日間、私の手数料はゼロです。これは開始キャンペーンではありません。このプラットフォームの裏側には今のところ私がいて、この数か月、誰も私に報酬を払っていません — その仕事の分を、あなたに請求していないということです。お支払いいただくのは、カードで代金を受け取るための費用だけです：1件につき {tecnica}% + {fisso}ユーロ。これは入金と、あなたにお金を送る振込の費用をまかないます。カードの種類と金額によって、私の負担は多くなることも少なくなることもあります。ユーロ以外の通貨で価格を設定される場合は {estera}% + {fisso}ユーロ になります。そこでは Stripe が両替も行うためです。私の手数料は、あなたが大きくなってから届きます。\n\nその代わり、あなたのために働くプラットフォームを：ダブルブッキング防止カレンダー、安全な決済、保証金、レビュー、13言語のサイト、すべて自動です。ローマの創設メンバーを少人数だけ探しています：今参加する方が最初のホストになります。\n\nこのメールにご返信ください。アカウントの開設を一つずつご案内します。10分とお部屋の写真があれば十分です。\n\n— BookinVIP\n\n配信停止：{optout}\n"),
    "zh": ("在罗马免费发布：前{giorni}天佣金{promo}%",
           "{nome} 您好，\n\n我正在罗马推出一个全新的预订平台 BookinVIP，并亲自挑选这座城市的首批房东。\n\n现在加入的理由：\n· 前{giorni}天佣金{promo}% — 免费发布，收入全归您。\n· 之后到第一年为{fase1}%，此后为{regime}% — 相比 Booking 和 Airbnb 的{pct}%甚至更高。\n· 您的房客始终支付0%佣金：他们看到的是干净的价格，因此您的房源比他们更有竞争力。\n· 您自己直接客户的预订仅收{diretto}%。\n\n有一点我在您签约之前就说明，而不是之后。前 {giorni} 天我的佣金为零，这不是开业折扣：这个平台背后目前是我一个人，这几个月没有人付我工资 — 我没有向您收取的，正是这份工作。您唯一需要付的，是用信用卡收款的成本：每笔 {tecnica}% + {fisso} 欧元。它覆盖收款以及把钱转给您的转账；根据卡种和金额，我的成本有时更高，有时更低。如果您用欧元以外的货币定价，则为 {estera}% + {fisso} 欧元，因为那时 Stripe 还需要兑换货币。我的佣金要等您做大之后才会到来。\n\n作为回报，您将获得一个为您工作的平台：防重复预订日历、安全支付、押金、评价、13种语言的网站，全部自动化。我只为罗马的创始成员寻找少数几位：现在加入的人将成为第一批。\n\n请回复此邮件，我会一步步为您开通账户。只需十分钟和您房源的照片。\n\n— BookinVIP\n\n退订这些邮件：{optout}\n"),
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
        diretto=_pct(BPS_DIRETTO), tecnica=_pct(_tecnica_bps()),
        estera=_pct(_tecnica_estera_bps()), fisso=_tecnica_fisso(lng))
    return lng, oggetto, testo


def componi_email_prima_roma(contatto: Contatto, nostra_bps: int, *,
                             link_opt_out: str, lingua: Optional[str] = None
                             ) -> Optional[Tuple[str, str, str]]:
    """Reclutamento host di ROMA in 8 lingue SINCRONIZZATE con la web app (it/en/es/fr/de/pt/
    ja/zh; ripiego EN, mai IT). `lingua` = la lingua scelta dall'host quando entra nella web app
    (viaggia nel gettone, fase86): passala qui e oggetto+corpo escono nella STESSA lingua.
    Ritorna (lingua, oggetto, corpo) con le cifre REALI di fase98, oppure None se manca l'opt-out
    (obbligatorio) o l'email non è valida.
    NB legale: l'invio AUTOMATICO resta soggetto al jurisdiction-gate del motore (UE esclusa di
    default). Questa variante è per l'outreach CALDO (host che hanno già scelto la lingua nella
    web app / contatti opt-in) e per l'invio MANUALE."""
    if not _email_valida(getattr(contatto, "email", None)):
        return None
    if not (isinstance(link_opt_out, str) and link_opt_out.strip()):
        return None                                  # opt-out OBBLIGATORIO
    lng = lingua or LINGUA_PER_PAESE.get(str(getattr(contatto, "paese", "")).upper(), "en")
    if lng not in _TEMPLATE_ROMA:
        lng = "en"                                   # sincronizzato col ripiego della web app
    oggetto, corpo = _TEMPLATE_ROMA[lng]
    # ripiego SENZA nome: un VOCATIVO, non la parola di saluto (senno' esce "Hi Hello," / "Ciao ,").
    nome = contatto.nome or {"it": "host", "en": "there", "es": "anfitrión", "fr": "hôte",
                             "de": "Gastgeber", "pt": "anfitrião", "ja": "ホスト",
                             "zh": "房东"}.get(lng, "there")
    from fase98_policy_commissione import (BPS_DIRETTO, LANCIO_BPS_FASE1,
                                           LANCIO_BPS_REGIME, LANCIO_GIORNI_GRATIS)
    val = dict(
        nome=nome, optout=link_opt_out.strip(),
        pct=_pct(_intero_bps(nostra_bps) + 500),      # la cifra DEI COLOSSI
        promo="0", giorni=LANCIO_GIORNI_GRATIS,
        fase1=_pct(LANCIO_BPS_FASE1), regime=_pct(LANCIO_BPS_REGIME),
        diretto=_pct(BPS_DIRETTO), tecnica=_pct(_tecnica_bps()),
        estera=_pct(_tecnica_estera_bps()), fisso=_tecnica_fisso(lng))
    return lng, oggetto.format(**val), corpo.format(**val)


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
