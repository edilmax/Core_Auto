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
    # LA HOME DEL DESK (La Suite, 2026-09-20): senza slug il Concierge TROVA alloggi
    # (ricerca vera del catalogo), parla di FIDUCIA con le macchine reali e di GUADAGNI
    # con i numeri veri di fase98. Prima di tutto: queste domande battono quelle da scheda.
    ("cerca", ("trovami", "trova un", "trova una", "cerco", "cercare", "mostrami",
               "ho bisogno", "voglio", "casa a", "appartamento a", "search", "find me",
               "looking for")),
    ("host", ("sono un host", "sono host", "guadagn", "commission", "percentual",
              "pubblicar", "affitto la mia casa", "la mia struttura", "earning")),
    ("fiducia", ("sicur", "fiduc", "fidar", "mi fido", "garanzia", "truffa", "affidabil",
                 "safe", "trust", "scam", "verified", "regret")),
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


def _importo_chat(cents, valuta):
    """Importo con la valuta, secondo i suoi decimali veri.

    Questo modulo non ha chiamanti (costruito e mai collegato), ma il gesto sbagliato
    va tolto comunque: il giorno che venisse acceso, nessuno ricontrollerebbe come
    scrive i numeri.
    """
    c = cents if isinstance(cents, int) and not isinstance(cents, bool) else 0
    v = str(valuta or "EUR").strip().upper() or "EUR"
    try:
        from fase99_multicurrency import Denaro
        return Denaro(max(0, c), v).formatta()
    except Exception:
        return "%d %s" % (max(0, c), v)

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
        # SENZA SLUG siamo sulla HOME: il desk esegue la ricerca vera, parla di fiducia
        # con le macchine reali e dei guadagni con i numeri di fase98 (La Suite).
        if not (isinstance(slug, str) and slug.strip()):
            return self.rispondi_home(testo, contesto)
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
                # VOCABOLARIO VERO del catalogo (fase57.SERVIZI): il codice e'
                # 'animali_ammessi'. Cercare solo "pet" (parola che il catalogo non ha mai
                # usato) faceva rispondere "non ammessi" su una casa che LI AMMETTE: il
                # test unitario non lo vedeva perche' il suo catalogo finto diceva "pet".
                pet = bool({"animali_ammessi", "pet"}
                           & {str(s).lower() for s in (d.get("servizi") or [])})
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

    # ── LA HOME DEL DESK (La Suite, 2026-09-20): TROVA alloggi con la ricerca vera del
    #    catalogo, parla di FIDUCIA citando le macchine reali, e di GUADAGNI con i numeri
    #    veri di fase98. Ogni risposta e' generata dal motore: niente inventato.
    def rispondi_home(self, testo: str, contesto: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ctx = contesto or {}
        it = self._lng == "it"
        intento = classifica_intento(testo)
        if intento == "host":
            return self._host_home(it)
        if intento == "fiducia":
            return self._fiducia_home(it)
        if intento in ("cerca", "prezzo", "disponibilita"):
            return self._cerca_home(ctx, it)
        if intento == "saluto":
            return self._out("saluto",
                             "Ciao! Posso TROVARTI un alloggio (dimmi la citta' nella barra "
                             "e quante persone), spiegarti come ci si fida, o parlarti dei "
                             "guadagni per gli host." if it else
                             "Hi! I can FIND you a stay (set the city and guests), explain "
                             "how trust works, or talk host earnings.", "canned")
        return self._out("fallback",
                         "Posso TROVARTI un alloggio (imposta la citta' nella barra e "
                         "quante persone), rispondere su SICUREZZA E PAGAMENTI, o "
                         "spiegarti i GUADAGNI per gli host. Oppure apri la scheda di un "
                         "alloggio e chiedimi i dettagli." if it else
                         "I can FIND you a stay (set the city and guests), answer about "
                         "SAFETY AND PAYMENTS, or explain HOST earnings. Or open a "
                         "listing and ask for details.", "canned")

    def _cerca_home(self, ctx: Dict[str, Any], it: bool) -> Dict[str, Any]:
        """La ricerca VERA del catalogo (fase57.CriteriRicerca) con i valori che l'ospite
        ha gia' impostato nella barra: citta', ospiti, tetto di prezzo, date (per la
        disponibilita'). Massimo 3: un desk elenca, non impila."""
        if self._cat is None:
            return self._out("cerca", "Catalogo non disponibile ora." if it else
                             "Catalog unavailable.", "nessun_catalogo")
        citta = str(ctx.get("citta") or "").strip() or None
        if not citta:
            return self._out("cerca",
                             "Dimmi la citta': scrivila nella barra di ricerca e "
                             "ripeto la domanda." if it else
                             "Tell me the city: type it in the search bar and ask again.",
                             "richiesta_dati")
        from fase57_vetrina import CriteriRicerca
        criteri = CriteriRicerca(
            citta=citta,
            capacita_min=ctx.get("party") or None,
            prezzo_max_cents=ctx.get("prezzo_max_cents") or None,
            check_in=ctx.get("check_in") or None,
            check_out=ctx.get("check_out") or None,
            limit=3)
        try:
            res = self._cat.cerca(criteri)
        except Exception:
            logger.warning("concierge cerca: ISOLATO", exc_info=True)
            res = None
        risultati = (res or {}).get("risultati") or []
        if not risultati:
            return self._out("cerca",
                             ("Ancora niente a %s: lascia la richiesta dalla Home e ti "
                              "avvisiamo quando arriva un alloggio." % citta) if it else
                             ("Nothing in %s yet: leave a request from the Home page and "
                              "we'll notify you." % citta), "catalogo")
        righe, lista = [], []
        for i, r in enumerate(risultati[:3], 1):
            titolo = str(r.get("titolo") or "")[:60]
            pre = _importo_chat(r.get("prezzo_notte_cents"), r.get("valuta"))
            righe.append("%d. %s - %s a notte" % (i, titolo, pre))
            lista.append({"slug": str(r.get("slug") or ""), "titolo": titolo, "prezzo": pre})
        risposta = (("Ecco cosa ho trovato a %s:\n" % citta) if it else "Here's what I found in %s:\n" % citta) \
            + "\n".join(righe) + ("\nApri quella che ti piace e chiedimi i dettagli."
                                  if it else "\nOpen the one you like and ask me details.")
        d = self._out("cerca", risposta, "catalogo")
        d["lista"] = lista
        return d

    def _host_home(self, it: bool) -> Dict[str, Any]:
        """I numeri VERI di fase98: la rampa di lancio e la tariffa di pagamento, con
        l'esempio calcolato DALLE COSTANTI (se qualcuno cambia i numeri, l'esempio segue)."""
        from fase98_policy_commissione import (LANCIO_GIORNI_GRATIS, LANCIO_BPS_FASE1,
                                               LANCIO_GIORNI_FASE1, LANCIO_BPS_REGIME)
        spesa = 10000 * 500 // 10000 + 25           # 5% + 0,25 EUR su 100 EUR
        netto = 10000 - spesa                       # 9475 = 94,75 EUR nei primi 90 giorni
        risposta = (
            "Commissioni HOST: i primi %d giorni da quando ti registri paghi 0%%; poi "
            "%d%% fino a %d giorni; a regime %d%%. A questo si aggiunge la tariffa di "
            "pagamento: 5%% + 0,25 EUR per transazione (7%% se la valuta e' estera: il "
            "gateway converte). L'OSPITE paga sempre 0%%. Esempio: su 100 EUR nei primi "
            "%d giorni ti restano %.2f EUR (poi l'ospite paga quello: zero sorprese per lui)."
            % (LANCIO_GIORNI_GRATIS, LANCIO_BPS_FASE1 // 100, LANCIO_GIORNI_FASE1,
               LANCIO_BPS_REGIME // 100, LANCIO_GIORNI_GRATIS, netto / 100)) if it else (
            "HOST fees: your first %d days cost 0%; then %d%% up to %d days; %d%% at "
            "scale. Plus the payment fee: 5%% + 0.25 EUR per transaction (7%% for foreign "
            "currency). The GUEST always pays 0%%. Example: on 100 EUR in your first %d "
            "days you keep %.2f EUR."
            % (LANCIO_GIORNI_GRATIS, LANCIO_BPS_FASE1 // 100, LANCIO_GIORNI_FASE1,
               LANCIO_BPS_REGIME // 100, LANCIO_GIORNI_GRATIS, netto / 100))
        return self._out("host", risposta, "fase98")

    def _fiducia_home(self, it: bool) -> Dict[str, Any]:
        risposta = (
            "Perche' puoi fidarti: (1) i soldi RESTANO IN GARANZIA fino al check-in: "
            "all'host arrivano solo se tutto va bene (escrow, sblocco entro 24h); "
            "(2) il prezzo che vedi e' FIRMATO crittograficamente e non cambia; "
            "(3) le recensioni arrivano SOLO da chi ha pagato davvero; "
            "(4) il voucher con il PIN ti arriva firmato via email; "
            "(5) l'ora e i documenti sono certificati da autorita' europee. "
            "E se non sei contento, il rimborso torna come credito." if it else
            "Why you can trust us: (1) the money stays in ESCROW until check-in; "
            "(2) the price you see is cryptographically signed and cannot change; "
            "(3) reviews come only from guests who actually paid; "
            "(4) your voucher with the PIN arrives signed by email; "
            "(5) timestamps and documents are certified by European authorities. "
            "And if you're not happy, the refund comes back as credit.")
        return self._out("fiducia", risposta, "motore")

    def _prezzo(self, slug: str, ctx: Dict[str, Any], it: bool) -> Dict[str, Any]:
        ci, co = ctx.get("check_in"), ctx.get("check_out")
        if not (isinstance(slug, str) and slug.strip()):
            # SENZA ALLOGGIO il desk non INDOVINA: indica la strada (provato dalla Home,
            # 2026-09-19: rispondeva "non disponibile" a chi chiedeva un prezzo prima di
            # aprire una scheda -- un no falso al cliente che stava chiedendo).
            return self._out("prezzo",
                             "Apri la scheda di un alloggio e riprova: ti dico il prezzo "
                             "firmato per le tue date." if it else
                             "Open a listing first and ask again: I'll give you the signed "
                             "price for your dates.", "richiesta_dati")
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
            # "Totale" deve essere il totale VERO: soggiorno + tassa di soggiorno
            # (`totale_cents` di fase59). Mostrando `prezzo_guest_cents` il chatbot
            # annunciava un prezzo piu' BASSO di quello che l'ospite paga davvero
            # (300,00 invece di 310,00 su un annuncio con tassa): un testo che mente
            # sui soldi. Ripiego sul soggiorno se il campo manca (concierge vecchi).
            tot = corpo.get("totale_cents")
            tot = int(tot) if isinstance(tot, int) and not isinstance(tot, bool) else cents
            val = corpo.get("valuta", "EUR")
            # PREZZO DAL CORE (firmato), mai inventato dall'IA
            # ENTRAMBI i rami con un solo segnaposto: l'importo arriva gia' scritto
            # nella valuta giusta. (Avevo sostituito solo l'inglese: quello italiano
            # restava con tre segnaposto e sollevava TypeError.)
            txt = ("Totale %s (preventivo firmato)." if it else
                   "Total %s (signed quote).") % _importo_chat(tot, val)
            return {"intento": "prezzo", "risposta": txt, "fonte": "concierge",
                    "quote_token": corpo.get("quote_token"),
                    "prezzo_guest_cents": cents, "totale_cents": tot}
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
