"""
CORE_AUTO - Fase 90: Marketing & Growth Engine 360° (autonomo, gratis al cuore, API-ready).

Risposta alla domanda "cosa ci rende sempre forti, gratis e autonomi": un motore che
PRODUCE da solo tutto il materiale di acquisizione (post social multi-lingua, immagini
promo generate da codice in SVG, email di campagna), lo PIANIFICA (calendario editoriale
deterministico) e lo PUBBLICA su più canali tramite un dispatcher iniettabile.

Cosa è GRATIS e autonomo (cuore, sempre attivo):
  - generazione contenuti (post + hashtag + call-to-action) in 5 lingue, deterministica
    (zero LLM, zero costo);
  - immagini promo 1080x1080 generate in SVG dal codice (niente designer, niente tool);
  - calendario editoriale (cosa pubblicare, quando, su quale canale);
  - invio email di campagna (riusa fase86 SMTP, gated).

Cosa è GATED (si accende con credenziali, ToS-rispettosi, NIENTE fake-engagement/bot):
  - pubblicazione su Instagram/Facebook/X = API ufficiali (token dell'operatore);
  - Telegram = gratis (Bot API) -> canale autonomo subito.

I canali sono un'abstraction `CanalePubblicazione`: il motore NON conosce le API, le
inietti tu. Nei test si usa uno stub (zero rete). Denaro in centesimi interi.

VINCITRICE DEL BENCHMARK (4 modi di fare growth): V3 'generatore deterministico + SVG da
codice + dispatcher astratto gated'. Le altre perdono: V1 'tool/designer a pagamento' =
costo; V2 'LLM per ogni post' = costo+nondeterminismo; V4 'bot di engagement falso' =
ban + illegale. BLINDATO: niente solleva; input invalido -> degrada; canali isolati.
"""
from __future__ import annotations

import html
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("core_auto.marketing")

LINGUE = ("it", "en", "es", "fr", "de")


# ── Immagine promo generata da CODICE (SVG, zero costo, zero tool) ────────────
def genera_card_svg(titolo: str, sottotitolo: str = "", *, tag: str = "@bookinvip",
                    lato: int = 1080) -> str:
    """Card quadrata 1080x1080 (formato Instagram) generata dal codice. XSS-safe."""
    e = html.escape
    lato = lato if isinstance(lato, int) and 320 <= lato <= 4096 else 1080
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#1e3c72"/><stop offset="1" stop-color="#2a5298"/>'
        '</linearGradient></defs>'
        '<rect width="%d" height="%d" fill="url(#g)"/>'
        '<text x="60" y="120" fill="#ffffff" font-family="sans-serif" '
        'font-size="48" font-weight="700">BookinVIP</text>'
        '<text x="60" y="%d" fill="#ffffff" font-family="sans-serif" '
        'font-size="76" font-weight="800">%s</text>'
        '<text x="60" y="%d" fill="#dce6ff" font-family="sans-serif" '
        'font-size="44">%s</text>'
        '<text x="60" y="%d" fill="#a9c0ff" font-family="sans-serif" '
        'font-size="40">%s</text></svg>'
    ) % (lato, lato, lato, lato, lato, lato,
         lato // 2, e(str(titolo)[:60]),
         lato // 2 + 90, e(str(sottotitolo)[:80]),
         lato - 80, e(str(tag)))


# ── Contenuto di un post ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class Post:
    tema: str
    lingua: str
    testo: str
    hashtag: Tuple[str, ...]
    link: str
    immagine_svg: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"tema": self.tema, "lingua": self.lingua, "testo": self.testo,
                "hashtag": list(self.hashtag), "link": self.link,
                "ha_immagine": bool(self.immagine_svg)}


_TESTI = {
    "host": {
        "it": "Affitti casa o stanze? Con le grandi OTA regali fino al 20% di commissione. "
              "Con BookinVIP tieni di più: prenotazioni dirette, pagamenti e check-in "
              "automatici. Scopri quanto guadagni in più 👇",
        "en": "Renting a place? Big OTAs take up to 20% commission. With BookinVIP you keep "
              "more: direct bookings, automatic payments and check-in. See how much more "
              "you earn 👇",
        "es": "¿Alquilas tu alojamiento? Las grandes OTA se llevan hasta el 20%. Con "
              "BookinVIP ganas más: reservas directas, pagos y check-in automáticos 👇",
        "fr": "Vous louez un logement ? Les grandes OTA prennent jusqu'à 20%. Avec "
              "BookinVIP vous gardez plus : réservations directes, paiements et check-in "
              "automatiques 👇",
        "de": "Sie vermieten? Große OTAs nehmen bis zu 20% Provision. Mit BookinVIP behalten "
              "Sie mehr: Direktbuchungen, automatische Zahlungen und Check-in 👇",
    },
    "guest": {
        "it": "Cerchi un alloggio? Prenota diretto su BookinVIP: prezzo chiaro, voucher "
              "istantaneo e check-in con un codice. Niente sorprese 👇",
        "en": "Looking for a stay? Book direct on BookinVIP: clear price, instant voucher "
              "and self check-in with a code. No surprises 👇",
        "es": "¿Buscas alojamiento? Reserva directo en BookinVIP: precio claro, voucher "
              "instantáneo y check-in con un código 👇",
        "fr": "Vous cherchez un logement ? Réservez en direct sur BookinVIP : prix clair, "
              "voucher instantané et check-in avec un code 👇",
        "de": "Auf der Suche nach einer Unterkunft? Direkt auf BookinVIP buchen: klarer "
              "Preis, sofortiger Gutschein und Self-Check-in mit Code 👇",
    },
    "referral": {
        "it": "Inviti un altro host su BookinVIP? Ricevete entrambi un credito. La rete "
              "cresce, le commissioni restano basse 👇",
        "en": "Invite another host to BookinVIP and you both get a credit. The network "
              "grows, commissions stay low 👇",
        "es": "Invita a otro anfitrión a BookinVIP y ambos recibís un crédito 👇",
        "fr": "Invitez un autre hôte sur BookinVIP : vous recevez tous les deux un crédit 👇",
        "de": "Lade einen anderen Gastgeber zu BookinVIP ein – ihr bekommt beide ein "
              "Guthaben 👇",
    },
}
_HASHTAG = {
    "host": ("#hosting", "#affittibrevi", "#shortrental", "#bookinvip", "#nocommissioni"),
    "guest": ("#viaggi", "#travel", "#vacanze", "#bookinvip", "#prenotadiretto"),
    "referral": ("#bookinvip", "#referral", "#host", "#community"),
}
_TITOLO_CARD = {
    "host": {"it": "Tieni di più.", "en": "Keep more.", "es": "Gana más.",
             "fr": "Gardez plus.", "de": "Mehr behalten."},
    "guest": {"it": "Prenota diretto.", "en": "Book direct.", "es": "Reserva directo.",
              "fr": "Réservez direct.", "de": "Direkt buchen."},
    "referral": {"it": "Invita & guadagna.", "en": "Invite & earn.",
                 "es": "Invita y gana.", "fr": "Invitez & gagnez.", "de": "Einladen."},
}


def _lng(l: Any) -> str:
    return l if l in LINGUE else "it"


_LINGUE_NOME = {"it": "italiano", "en": "English", "es": "español", "fr": "français",
                "de": "Deutsch", "pt": "português", "ja": "日本語", "zh": "中文"}


class GeneratoreContenuti:
    """Produce i Post (testo + hashtag + immagine SVG). Il testo è deterministico e gratuito;
    se è iniettato un `pool_testo` (AI a rotazione fase164), il testo viene RISCRITTO in modo
    più accattivante con FALLBACK SICURO al deterministico (AI giù/quota -> testo di base)."""

    def __init__(self, base_url: str = "https://bookinvip.com", *, pool_testo: Any = None) -> None:
        self._base = (base_url or "").rstrip("/")
        self._pool = pool_testo

    def _link(self, tema: str) -> str:
        return self._base + ("/diventa-host.html" if tema in ("host", "referral") else "/")

    def _ai_testo(self, base: str, lng: str) -> str:
        """Riscrive il testo base via AI (pool). Isolato: qualunque problema -> testo base."""
        if self._pool is None:
            return base
        nome = _LINGUE_NOME.get(lng, lng)
        prompt = ("Riscrivi questo come UN solo post social breve e accattivante in %s, "
                  "massimo 40 parole, con 1 emoji, fedele ai fatti, SENZA link, SENZA hashtag, "
                  "SENZA elenchi e SENZA virgolette. Testo base: %s" % (nome, base))
        try:
            out = self._pool.genera({"prompt": prompt, "max_token": 160})
            if isinstance(out, dict) and out.get("ok"):
                t = str(out.get("risultato") or "").strip().strip('"').strip("«»").strip()
                if 10 <= len(t) <= 600:
                    return t
        except Exception:
            pass
        return base

    def crea(self, tema: str, lingua: str = "it", *, sottotitolo: str = "") -> Optional[Post]:
        if tema not in _TESTI:
            return None
        lng = _lng(lingua)
        link = self._link(tema)
        testo = self._ai_testo(_TESTI[tema][lng], lng) + "\n" + link
        sub = sottotitolo or {"host": "0% sorprese · commissione bassa",
                              "guest": "Voucher + check-in con un codice",
                              "referral": "Credito per te e per chi inviti"}[tema]
        card = genera_card_svg(_TITOLO_CARD[tema][lng], sub)
        return Post(tema, lng, testo, _HASHTAG[tema], link, card)

    def campagna_completa(self, lingue: Sequence[str] = LINGUE) -> List[Post]:
        out: List[Post] = []
        for tema in ("host", "guest", "referral"):
            for l in lingue:
                p = self.crea(tema, l)
                if p:
                    out.append(p)
        return out


# ── Calendario editoriale deterministico ─────────────────────────────────────
def calendario_editoriale(post: Sequence[Post], canali: Sequence[str], *,
                          partenza: str = "2026-01-01", cadenza_giorni: int = 1
                          ) -> List[Dict[str, Any]]:
    """Pianifica: assegna a ogni post una data e un canale, a rotazione. Deterministico."""
    import datetime
    try:
        d0 = datetime.date.fromisoformat(partenza)
    except (ValueError, TypeError):
        d0 = datetime.date(2026, 1, 1)
    cad = cadenza_giorni if isinstance(cadenza_giorni, int) and cadenza_giorni > 0 else 1
    canali = [c for c in canali if c] or ["telegram"]
    piano = []
    for i, p in enumerate(post):
        giorno = d0 + datetime.timedelta(days=(i // len(canali)) * cad)
        piano.append({"data": giorno.isoformat(), "canale": canali[i % len(canali)],
                      "tema": p.tema, "lingua": p.lingua, "post": p})
    return piano


# ── Pubblicazione multi-canale (abstraction; impl reali = API ufficiali) ──────
class CanalePubblicazione:
    """Un canale social. Le impl reali usano API UFFICIALI (token operatore, ToS).
    `pubblica` non deve sollevare."""
    nome = "abstract"

    def pubblica(self, post: Post) -> bool:
        raise NotImplementedError


class CanaleStub(CanalePubblicazione):
    nome = "stub"

    def __init__(self) -> None:
        self.pubblicati: List[Post] = []

    def pubblica(self, post: Post) -> bool:
        self.pubblicati.append(post)
        return True


class MotoreMarketing:
    """Orchestratore: genera -> pianifica -> pubblica (canali iniettati) + email (fase86)."""

    def __init__(self, generatore: GeneratoreContenuti,
                 canali: Optional[Dict[str, CanalePubblicazione]] = None,
                 *, email_provider: Any = None) -> None:
        self._gen = generatore
        self._canali = canali or {}
        self._email = email_provider

    def pubblica_piano(self, piano: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        rep = {"totale": 0, "pubblicati": 0, "saltati": 0, "per_canale": {}}
        for voce in piano:
            rep["totale"] += 1
            canale = self._canali.get(voce.get("canale"))
            post = voce.get("post")
            if canale is None or not isinstance(post, Post):
                rep["saltati"] += 1
                continue
            try:
                ok = canale.pubblica(post)
            except Exception:
                logger.warning("canale.pubblica fallita (ISOLATA)", exc_info=True)
                ok = False
            if ok:
                rep["pubblicati"] += 1
                rep["per_canale"][canale.nome] = rep["per_canale"].get(canale.nome, 0) + 1
            else:
                rep["saltati"] += 1
        return rep

    def esegui_campagna(self, lingue: Sequence[str] = LINGUE, *,
                        partenza: str = "2026-01-01") -> Dict[str, Any]:
        """Genera la campagna completa -> pianifica -> pubblica sui canali configurati."""
        lng = [l for l in lingue if l in LINGUE] or list(LINGUE)
        post = self._gen.campagna_completa(lng)
        piano = calendario_editoriale(post, list(self._canali.keys()) or ["telegram"],
                                      partenza=partenza)
        rep = self.pubblica_piano(piano)
        rep["post_generati"] = len(post)
        rep["canali_configurati"] = list(self._canali.keys())
        return rep

    def invia_email_campagna(self, destinatari: Sequence[str], oggetto: str,
                             post: Post) -> int:
        """Manda il post come email (gated: senza email_provider, 0)."""
        if self._email is None or not isinstance(post, Post):
            return 0
        corpo = "<div style='font-family:sans-serif'>%s</div>" % html.escape(
            post.testo).replace("\n", "<br>")
        n = 0
        for d in destinatari:
            try:
                if self._email.invia(d, oggetto, corpo):
                    n += 1
            except Exception:
                logger.warning("email campagna fallita (ISOLATA)", exc_info=True)
        return n


def crea_motore_marketing(base_url: str = "https://bookinvip.com", *,
                          canali: Optional[Dict[str, CanalePubblicazione]] = None,
                          email_provider: Any = None,
                          pool_testo: Any = None) -> MotoreMarketing:
    return MotoreMarketing(GeneratoreContenuti(base_url, pool_testo=pool_testo), canali or {},
                           email_provider=email_provider)
