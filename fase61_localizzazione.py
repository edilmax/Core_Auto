"""
CORE_AUTO - Fase 61: Localizzazione (i18n) a COSTO ZERO - la Torre di Babele polverizzata.

Il prodotto vende in tutto il mondo: in che lingua parla il software? Le OTA hanno
dipartimenti pachidermici per localizzare l'interfaccia in 40 lingue. Noi no, perche'
l'architettura risolve il 90% del problema GRATIS:
  - il NUCLEO non parla lingue: date ISO 8601, denaro in centesimi interi, disponibilita'
    booleana, servizi come CODICI (wifi/piscina), non come parole (fasi 57/58);
  - il PATH AGENTE (concierge fase59 + MCP fase60) restituisce dati strutturati: l'IA
    del cliente (Claude/ChatGPT) traduce l'offerta nella sua lingua -> il costo della
    traduzione lo paga OpenAI/Anthropic, non noi.

Resta UN solo perimetro umano: le notifiche all'HOST (WhatsApp/Telegram), che in fase58
erano hardcoded in italiano. Questo modulo lo chiude a costo zero:
  1. la lingua dell'host si DEDUCE dal prefisso internazionale del telefono (+39->it,
     +44->en, +81->ja...) o si imposta esplicitamente; fallback alla lingua di default;
  2. i testi escono da un DIZIONARIO PRECOMPILATO (nessuna chiamata esterna, O(1));
  3. le etichette dei servizi (codici language-neutral) sono rese in N lingue per la UI;
  4. i testi LIBERI dell'host (descrizioni) NON si traducono al volo (costerebbe denaro
     + dipendenza): si passano TAGGATI con la lingua d'origine -> l'agente del cliente
     traduce. Scelta vincente: costo zero, deterministica, nessun servizio esterno.

VINCITRICE DEL BENCHMARK (4 strategie i18n, criterio costo+latenza+offline):
  V3 'dizionario precompilato + deduzione da prefisso + pass-through taggato'. Zero
  costo, zero latenza, funziona offline, deterministico. Le altre perdono:
    - V1 'traduzione live via API' = costo per messaggio + dipendenza + latenza + punto
      di guasto; V2 'file .po/.mo gestiti a mano' = burocrazia da software-house anni 2000;
    - V4 'tutto in inglese' = host non-anglofono spaesato (l'host e' il perimetro umano).

SOPRAVVIVENZA TOTALE: nessuna funzione solleva mai; lingua/codice ignoti -> fallback
(fail-safe), mai un KeyError; reso deterministico e idempotente. Zero dipendenze.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger("core_auto.localizzazione")

LINGUA_DEFAULT = "en"   # lingua franca globale del prodotto
LINGUE_SUPPORTATE = ("en", "it", "es", "fr", "de", "pt", "ja", "zh")

# Prefisso internazionale di chiamata -> lingua (match longest-prefix).
PREFISSI_LINGUA: Dict[str, str] = {
    "+1": "en", "+44": "en", "+61": "en", "+353": "en", "+64": "en",
    "+39": "it",
    "+34": "es", "+52": "es", "+54": "es", "+57": "es", "+51": "es",
    "+33": "fr", "+32": "fr",
    "+49": "de", "+43": "de", "+41": "de",
    "+55": "pt", "+351": "pt",
    "+81": "ja",
    "+86": "zh", "+886": "zh", "+852": "zh",
}

# Notifiche host: tipo -> lingua -> template ({alloggio},{ci},{co},{origine}).
NOTIFICHE: Dict[str, Dict[str, str]] = {
    "nuova_prenotazione": {
        "en": "New booking: {alloggio} from {ci} to {co} (source: {origine}).",
        "it": "Nuova prenotazione: {alloggio} dal {ci} al {co} (fonte: {origine}).",
        "es": "Nueva reserva: {alloggio} del {ci} al {co} (origen: {origine}).",
        "fr": "Nouvelle reservation : {alloggio} du {ci} au {co} (source : {origine}).",
        "de": "Neue Buchung: {alloggio} vom {ci} bis {co} (Quelle: {origine}).",
        "pt": "Nova reserva: {alloggio} de {ci} a {co} (origem: {origine}).",
        "ja": "新しい予約: {alloggio} {ci}〜{co}（経路: {origine}）。",
        "zh": "新预订：{alloggio} {ci} 至 {co}（来源：{origine}）。",
    },
    "cancellazione": {
        "en": "Booking cancelled: {alloggio} {ci}-{co}.",
        "it": "Prenotazione annullata: {alloggio} {ci}-{co}.",
        "es": "Reserva cancelada: {alloggio} {ci}-{co}.",
        "fr": "Reservation annulee : {alloggio} {ci}-{co}.",
        "de": "Buchung storniert: {alloggio} {ci}-{co}.",
    },
}

# Etichette servizi (codici fase57) -> lingua -> testo.
ETICHETTE_SERVIZI: Dict[str, Dict[str, str]] = {
    "wifi": {"en": "WiFi", "it": "Wi-Fi", "es": "Wifi", "fr": "Wifi", "de": "WLAN", "pt": "Wi-Fi", "ja": "Wi-Fi", "zh": "无线网络"},
    "parcheggio": {"en": "Parking", "it": "Parcheggio", "es": "Aparcamiento", "fr": "Parking", "de": "Parkplatz", "pt": "Estacionamento", "ja": "駐車場", "zh": "停车场"},
    "piscina": {"en": "Pool", "it": "Piscina", "es": "Piscina", "fr": "Piscine", "de": "Pool", "pt": "Piscina", "ja": "プール", "zh": "游泳池"},
    "aria_condizionata": {"en": "Air conditioning", "it": "Aria condizionata", "es": "Aire acondicionado", "fr": "Climatisation", "de": "Klimaanlage", "pt": "Ar-condicionado", "ja": "エアコン", "zh": "空调"},
    "cucina": {"en": "Kitchen", "it": "Cucina", "es": "Cocina", "fr": "Cuisine", "de": "Küche", "pt": "Cozinha", "ja": "キッチン", "zh": "厨房"},
    "lavatrice": {"en": "Washing machine", "it": "Lavatrice", "es": "Lavadora", "fr": "Lave-linge", "de": "Waschmaschine", "pt": "Máquina de lavar", "ja": "洗濯機", "zh": "洗衣机"},
    "animali_ammessi": {"en": "Pets allowed", "it": "Animali ammessi", "es": "Se admiten mascotas", "fr": "Animaux acceptés", "de": "Haustiere erlaubt", "pt": "Animais permitidos", "ja": "ペット可", "zh": "允许携带宠物"},
    "colazione": {"en": "Breakfast", "it": "Colazione", "es": "Desayuno", "fr": "Petit-déjeuner", "de": "Frühstück", "pt": "Café da manhã", "ja": "朝食", "zh": "早餐"},
    "vista_mare": {"en": "Sea view", "it": "Vista mare", "es": "Vistas al mar", "fr": "Vue mer", "de": "Meerblick", "pt": "Vista para o mar", "ja": "オーシャンビュー", "zh": "海景"},
    "parcheggio_disabili": {"en": "Accessible parking", "it": "Parcheggio disabili", "es": "Aparcamiento accesible", "fr": "Parking handicapé", "de": "Behindertenparkplatz", "pt": "Estacionamento acessível", "ja": "バリアフリー駐車場", "zh": "无障碍停车位"},
    "check_in_24h": {"en": "24h check-in", "it": "Check-in 24h", "es": "Check-in 24h", "fr": "Check-in 24h", "de": "24h Check-in", "pt": "Check-in 24h", "ja": "24時間チェックイン", "zh": "24小时入住"},
    "riscaldamento": {"en": "Heating", "it": "Riscaldamento", "es": "Calefacción", "fr": "Chauffage", "de": "Heizung", "pt": "Aquecimento", "ja": "暖房", "zh": "暖气"},
}

# Stati (prenotazione/disponibilita') -> lingua -> testo.
ETICHETTE_STATI: Dict[str, Dict[str, str]] = {
    "confermata": {"en": "Confirmed", "it": "Confermata", "es": "Confirmada", "fr": "Confirmée", "de": "Bestätigt", "pt": "Confirmada", "ja": "確定", "zh": "已确认"},
    "rifiutata": {"en": "Rejected", "it": "Rifiutata", "es": "Rechazada", "fr": "Refusée", "de": "Abgelehnt", "pt": "Recusada", "ja": "拒否", "zh": "已拒绝"},
    "pieno": {"en": "Sold out", "it": "Pieno", "es": "Completo", "fr": "Complet", "de": "Ausgebucht", "pt": "Esgotado", "ja": "満室", "zh": "已订满"},
    "chiuso": {"en": "Closed", "it": "Chiuso", "es": "Cerrado", "fr": "Fermé", "de": "Geschlossen", "pt": "Fechado", "ja": "受付停止", "zh": "已关闭"},
}


def lingua_da_telefono(telefono: Any, default: str = LINGUA_DEFAULT) -> str:
    """Deduce la lingua dal prefisso internazionale (longest-prefix). Fail-safe."""
    if not isinstance(telefono, str):
        return default
    tel = telefono.strip().replace(" ", "").replace("-", "")
    if not tel.startswith("+"):
        return default
    migliore = ""
    risultato = default
    for prefisso, lingua in PREFISSI_LINGUA.items():
        if tel.startswith(prefisso) and len(prefisso) > len(migliore):
            migliore, risultato = prefisso, lingua
    return risultato


class Localizzatore:
    """Rende notifiche/etichette in lingua, da dizionari precompilati. Mai solleva."""

    def __init__(self, default: str = LINGUA_DEFAULT) -> None:
        self._default = default if default in LINGUE_SUPPORTATE else LINGUA_DEFAULT

    def risolvi_lingua(self, *, esplicita: Optional[str] = None,
                       telefono: Any = None) -> str:
        if isinstance(esplicita, str) and esplicita in LINGUE_SUPPORTATE:
            return esplicita
        if telefono is not None:
            return lingua_da_telefono(telefono, self._default)
        return self._default

    def _scegli(self, tabella: Dict[str, str], lingua: str) -> Optional[str]:
        if lingua in tabella:
            return tabella[lingua]
        return tabella.get(self._default) or tabella.get("en")

    def notifica(self, tipo: str, lingua: str, **campi: Any) -> str:
        tabella = NOTIFICHE.get(tipo)
        template = self._scegli(tabella, lingua) if tabella else None
        if template is None:
            # fallback generico (nessun template per quel tipo)
            return "{}: {} {}-{}".format(
                tipo, campi.get("alloggio", "?"), campi.get("ci", "?"),
                campi.get("co", "?"))
        try:
            return template.format(
                alloggio=campi.get("alloggio", "?"), ci=campi.get("ci", "?"),
                co=campi.get("co", "?"), origine=campi.get("origine", "?"))
        except (KeyError, IndexError, ValueError):
            return template

    def localizza_notifica(self, payload: Dict[str, Any], lingua: str) -> str:
        """Rende il testo da un payload-notifica stile fase58 (tipo/alloggio_id/date)."""
        if not isinstance(payload, dict):
            return ""
        return self.notifica(
            str(payload.get("tipo", "nuova_prenotazione")), lingua,
            alloggio=payload.get("alloggio_id", "?"),
            ci=payload.get("check_in", "?"), co=payload.get("check_out", "?"),
            origine=payload.get("origine", "?"))

    def servizio(self, codice: Any, lingua: str) -> str:
        tabella = ETICHETTE_SERVIZI.get(str(codice))
        return self._scegli(tabella, lingua) if tabella else str(codice)

    def servizi(self, codici: Any, lingua: str) -> List[str]:
        if not isinstance(codici, (list, tuple, set, frozenset)):
            return []
        return [self.servizio(c, lingua) for c in codici]

    def stato(self, codice: Any, lingua: str) -> str:
        tabella = ETICHETTE_STATI.get(str(codice))
        return self._scegli(tabella, lingua) if tabella else str(codice)


def tagga_contenuto(testo: Any, lingua_origine: str) -> Dict[str, Any]:
    """Marca un testo libero (es. descrizione host) con la sua lingua d'origine, cosi'
    l'agente del cliente sa DA QUALE lingua tradurre (pass-through, costo zero)."""
    lingua = lingua_origine if lingua_origine in LINGUE_SUPPORTATE else LINGUA_DEFAULT
    return {"text": testo if isinstance(testo, str) else "", "lang": lingua}


def crea_notificatore_localizzato(
        invio: Callable[[Dict[str, Any]], None],
        risolvi_lingua: Union[str, Callable[[Dict[str, Any]], str]],
        *, localizzatore: Optional[Localizzatore] = None
) -> Callable[[Dict[str, Any]], None]:
    """Avvolge un invio grezzo (es. WhatsApp) ri-rendendo il testo nella lingua dell'host.
    Drop-in come `notificatore` di fase58 ChannelManager. `risolvi_lingua` puo' essere una
    lingua fissa o una funzione del payload (es. dedotta dal telefono dell'host)."""
    loc = localizzatore or Localizzatore()

    def _invia(payload: Dict[str, Any]) -> None:
        if callable(risolvi_lingua):
            lingua = risolvi_lingua(payload)
        else:
            lingua = risolvi_lingua
        if not isinstance(lingua, str) or lingua not in LINGUE_SUPPORTATE:
            lingua = loc.risolvi_lingua()
        testo = loc.localizza_notifica(payload, lingua)
        invio({**payload, "testo": testo, "lingua": lingua})

    return _invia
