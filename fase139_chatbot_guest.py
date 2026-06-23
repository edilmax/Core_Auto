"""
CORE_AUTO - Fase 139: Chatbot AI assistenza guest pre-prenotazione.

Router d'intento DETERMINISTICO sopra i dati reali: i FATTI (prezzo, disponibilità) vengono
SEMPRE dal CORE (concierge fase59 = quote firmate; catalogo fase57), MAI inventati dall'IA
(regola d'oro: il denaro non si delega all'IA). L'LLM è OPZIONALE/iniettato e serve solo a
rifrasare le risposte a domande libere — non tocca numeri/prezzi. Senza LLM funziona
identico (fallback canned). Multilingua leggero (IT/EN). BLINDATO: errore → risposta neutra.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("core_auto.chatbot_guest")

_INTENTI: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("prezzo", ("prezzo", "costo", "quanto costa", "price", "cost", "how much")),
    ("disponibilita", ("disponibil", "libero", "available", "free", "vacancy")),
    ("servizi", ("servizi", "wifi", "piscina", "parcheggio", "amenities", "pool", "parking")),
    ("posizione", ("dove", "posizione", "indirizzo", "where", "location", "address")),
    ("checkin", ("check-in", "checkin", "orario", "arrivo", "arrival", "key", "chiavi")),
    ("animali", ("animali", "cane", "gatto", "pet", "dog", "cat")),
    ("cancellazione", ("cancell", "rimborso", "refund", "cancel")),
    ("saluto", ("ciao", "salve", "buongiorno", "hello", "hi")),
)


def classifica_intento(testo: Any) -> str:
    if not isinstance(testo, str) or not testo.strip():
        return "fallback"
    t = testo.lower()
    for intento, chiavi in _INTENTI:
        if any(k in t for k in chiavi):
            return intento
    return "fallback"


class ChatbotGuest:
    def __init__(self, catalogo: Any = None, concierge: Any = None, *,
                 llm: Optional[Callable[[str], str]] = None, lingua: str = "it") -> None:
        self._cat = catalogo
        self._con = concierge
        self._llm = llm
        self._lng = lingua

    def _dett(self, slug: str) -> Dict[str, Any]:
        try:
            d = self._cat.dettaglio(slug) if self._cat else None
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def rispondi(self, slug: str, testo: str, *,
                 contesto: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        intento = classifica_intento(testo)
        ctx = contesto or {}
        it = self._lng == "it"
        try:
            if intento == "prezzo":
                return self._prezzo(slug, ctx, it)
            if intento == "disponibilita":
                return self._disponibilita(slug, ctx, it)
            if intento == "servizi":
                d = self._dett(slug)
                serv = d.get("servizi") or d.get("amenities") or []
                txt = (("Servizi: " if it else "Amenities: ") + ", ".join(map(str, serv))) \
                    if serv else ("Nessun servizio elencato." if it else "No amenities listed.")
                return self._out(intento, txt, "catalogo")
            if intento == "posizione":
                d = self._dett(slug)
                citta = d.get("citta") or d.get("city") or ""
                return self._out(intento, (("Si trova a " if it else "Located in ") + str(citta))
                                 if citta else ("Posizione non disponibile." if it else
                                                "Location unavailable."), "catalogo")
            if intento == "checkin":
                return self._out(intento, "Check-in dalle 15:00, check-out entro le 11:00. "
                                 "Self check-in con smart-pass." if it else
                                 "Check-in from 3pm, check-out by 11am. Self check-in.", "policy")
            if intento == "animali":
                d = self._dett(slug)
                pet = "pet" in [str(s).lower() for s in (d.get("servizi") or [])]
                return self._out(intento, ("Animali ammessi." if pet else
                                 "Animali non ammessi salvo accordo con l'host.") if it else
                                 ("Pets allowed." if pet else "Pets not allowed."), "catalogo")
            if intento == "cancellazione":
                return self._out(intento, "La politica di cancellazione e il rimborso sono "
                                 "mostrati al checkout (vedi fase111)." if it else
                                 "Cancellation policy shown at checkout.", "policy")
            if intento == "saluto":
                return self._out(intento, "Ciao! Come posso aiutarti con questo alloggio?"
                                 if it else "Hi! How can I help with this place?", "canned")
            return self._fallback(testo, it)
        except Exception:
            logger.warning("rispondi fallita (ISOLATA)", exc_info=True)
            return self._out("fallback", "Riprova più tardi." if it else "Try again later.",
                             "errore")

    def _prezzo(self, slug: str, ctx: Dict[str, Any], it: bool) -> Dict[str, Any]:
        ci, co = ctx.get("check_in"), ctx.get("check_out")
        if not (ci and co):
            return self._out("prezzo", "Indica le date (check-in e check-out) per il prezzo."
                             if it else "Tell me your dates for a price.", "richiesta_dati")
        if self._con is None:
            return self._out("prezzo", "Prezzo non disponibile ora." if it else
                             "Price unavailable.", "nessun_concierge")
        r = self._con.quota({"alloggio_id": slug, "check_in": ci, "check_out": co,
                             "party": ctx.get("party", 1)})
        corpo = getattr(r, "corpo", {})
        if getattr(r, "status", 0) == 200 and isinstance(corpo, dict):
            cents = int(corpo.get("prezzo_guest_cents", 0))
            val = corpo.get("valuta", "EUR")
            # PREZZO DAL CORE (firmato), mai inventato dall'IA
            txt = ("Totale %d.%02d %s (preventivo firmato)." if it else
                   "Total %d.%02d %s (signed quote).") % (cents // 100, cents % 100, val)
            return {"intento": "prezzo", "risposta": txt, "fonte": "concierge",
                    "quote_token": corpo.get("quote_token"),
                    "prezzo_guest_cents": cents}
        return self._out("prezzo", "Non disponibile per quelle date." if it else
                         "Not available for those dates.", "concierge")

    def _disponibilita(self, slug: str, ctx: Dict[str, Any], it: bool) -> Dict[str, Any]:
        ci, co = ctx.get("check_in"), ctx.get("check_out")
        if not (ci and co and self._con is not None):
            return self._out("disponibilita", "Indica le date." if it else "Tell me the dates.",
                             "richiesta_dati")
        r = self._con.quota({"alloggio_id": slug, "check_in": ci, "check_out": co})
        ok = getattr(r, "status", 0) == 200
        return self._out("disponibilita", ("Disponibile! " if ok else "Non disponibile per "
                         "quelle date.") if it else ("Available!" if ok else "Not available."),
                         "concierge")

    def _fallback(self, testo: str, it: bool) -> Dict[str, Any]:
        if self._llm is not None:
            try:
                risp = self._llm(testo)
                if isinstance(risp, str) and risp.strip():
                    return self._out("fallback", risp.strip(), "llm")
            except Exception:
                logger.warning("llm fallito (ISOLATO)", exc_info=True)
        return self._out("fallback", "Posso aiutarti su prezzo, disponibilità, servizi, "
                         "posizione e check-in." if it else
                         "I can help with price, availability, amenities, location, check-in.",
                         "canned")

    @staticmethod
    def _out(intento: str, risposta: str, fonte: str) -> Dict[str, Any]:
        return {"intento": intento, "risposta": risposta, "fonte": fonte}


def crea_chatbot_guest(catalogo: Any = None, concierge: Any = None, *,
                       llm: Any = None, lingua: str = "it") -> ChatbotGuest:
    return ChatbotGuest(catalogo, concierge, llm=llm, lingua=lingua)
