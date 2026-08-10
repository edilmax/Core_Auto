"""
CORE_AUTO - Fase 200: MOTORE CAMPAGNA PERSUASIVA A ROTAZIONE.

Per ogni pubblicazione genera un CONTENUTO (didascalia + immagine) applicando una LEVA di persuasione
diversa a rotazione (i 7 principi di Cialdini, mappati su BookinVIP dalla campagna «Classe Fondatrice
di Roma»). Cosi' i post escono sempre diversi, belli e STUDIATI, mai due volte uguali.

  - TESTO (didascalia): via AI INIETTABILE `genera_testo(prompt) -> str|None` (Groq in prod, stub nei
    test). RIPIEGO MAI-VUOTO: se l'AI non risponde, usa una didascalia pre-scritta per quella leva ->
    il contenuto non e' MAI vuoto.
  - IMMAGINE: URL Pollinations con modello `flux` (alta qualita', NITIDO) — SENZA chiave, sempre attivo.
  - ROTAZIONE DUREVOLE: lo stato (indice della leva) sopravvive ai riavvii (file JSON iniettabile);
    ogni `genera()` avanza alla leva successiva, cosi' gira tutta la ruota senza ripetere.

GENERA sempre (per l'anteprima/preview); la PUBBLICAZIONE la fa il chiamante sui canali gia' accesi
(fase91: Facebook/Telegram/Mastodon/Nostr). BLINDATO: nessuna funzione solleva; input assurdo -> ripiego.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

logger = logging.getLogger("core_auto.campagna_persuasiva")

POLLINATIONS = "https://image.pollinations.ai/prompt/"

# ── Le 7 leve di Cialdini mappate su BookinVIP (campagna «Classe Fondatrice di Roma») ──────────
# istruzione = cosa deve fare l'AI; soggetto = spunto per l'immagine; ripiego = didascalia se l'AI tace.
ANGOLI: List[Dict[str, str]] = [
    {"chiave": "reciprocita", "nome": "Reciprocità",
     "istruzione": "Leva RECIPROCITÀ: diamo per primi. L'host pubblica GRATIS e tiene tutto (0% di "
                   "commissione per 90 giorni). Invita un host di {citta} a entrare, tono caldo.",
     "soggetto": "cozy warm apartment interior in {citta} Italy, golden key on a wooden table, "
                 "welcoming, premium, golden hour light",
     "ripiego": "A {citta} pubblichi GRATIS e tieni tutto: 0% di commissione per 90 giorni. Ti apro "
                "io l'account, bastano 10 minuti. bookinvip.com"},
    {"chiave": "unita", "nome": "Unità",
     "istruzione": "Leva UNITÀ/appartenenza: la «Classe Fondatrice di {citta}». Non «un utente», ma "
                   "uno dei primi, dei nostri. Fai sentire l'host parte di qualcosa.",
     "soggetto": "elegant {citta} rooftops at golden hour, warm inviting exclusive atmosphere, emerald and gold",
     "ripiego": "Entra nella Classe Fondatrice di {citta}. Chi entra adesso resta il primo. bookinvip.com"},
    {"chiave": "scarsita", "nome": "Scarsità",
     "istruzione": "Leva SCARSITÀ: sto scegliendo A MANO i primi host di {citta}, pochi posti. Crea "
                   "urgenza onesta (non finta), invito ad agire ora.",
     "soggetto": "luxury apartment building facade in {citta} at sunset, exclusive, few golden windows lit, elegant",
     "ripiego": "Sto scegliendo a mano i primi host di {citta}. Pochi posti nella Classe Fondatrice — "
                "se hai un alloggio, scrivimi ora. bookinvip.com"},
    {"chiave": "riprova_sociale", "nome": "Riprova sociale",
     "istruzione": "Leva RIPROVA SOCIALE: altri host si stanno già unendo a {citta}. Rassicura chi è "
                   "indeciso mostrando che non è solo. Tono positivo.",
     "soggetto": "welcoming host greeting a guest at the door of a {citta} apartment, warm smile, hospitality",
     "ripiego": "Gli host di {citta} si stanno unendo a BookinVIP. Unisciti ai primi: 0% per 90 giorni, "
                "l'ospite paga 0%. bookinvip.com"},
    {"chiave": "autorita", "nome": "Autorità (trasparenza)",
     "istruzione": "Leva AUTORITÀ tramite TRASPARENZA RADICALE: diciamo il costo PRIMA della firma. "
                   "C'è una tariffa tecnica del 5% + 0,25 € a prenotazione, che copre il costo di "
                   "incassare e di bonificare. L'onestà come forza. «Senza sorprese.»",
     "soggetto": "clean elegant modern interior in {citta}, transparent glass, natural light, honest premium feel",
     "ripiego": "Ti diciamo il costo PRIMA, non dopo: tariffa tecnica 5% + 0,25 € a prenotazione, che "
                "copre incasso e bonifico. L'ospite paga 0%. Basta sorprese. bookinvip.com"},
    {"chiave": "simpatia", "nome": "Simpatia",
     "istruzione": "Leva SIMPATIA: parla come una persona vera, non un'azienda. Il fondatore che "
                   "accompagna l'host di persona, nella sua lingua. Caldo, umano, diretto.",
     "soggetto": "friendly person working on a laptop in a bright {citta} cafe, warm human, approachable",
     "ripiego": "Niente call center: ti apro io l'account e ti accompagno passo passo. Bastano 10 minuti "
                "e le foto del tuo alloggio a {citta}. Scrivimi. bookinvip.com"},
    {"chiave": "coerenza", "nome": "Coerenza",
     "istruzione": "Leva COERENZA/impegno: un piccolo primo passo. «Bastano 10 minuti e le foto.» Un sì "
                   "piccolo e facile che apre la porta.",
     "soggetto": "smartphone showing a simple booking listing being created, hands, cozy {citta} apartment background",
     "ripiego": "Il primo passo è piccolo: 10 minuti e le foto del tuo alloggio a {citta}. Al resto "
                "pensiamo noi. bookinvip.com"},
]

# ── GLOBALE ──────────────────────────────────────────────────────────────────────────────────
# Destinazioni TOP per il reclutamento host: densità in PARALLELO su poche città ad alto traffico
# (non una sola, non tutte le 230). Sottoinsieme delle più visitate al mondo dove ha senso partire.
CITTA_TOP = ("Roma", "Barcelona", "Lisbon", "Paris", "London", "Amsterdam", "Berlin",
             "New York", "Miami", "Dubai", "Bangkok", "Tokyo", "Istanbul")

# L'indice durevole gira su questo PERIODO = minimo comune multiplo(leve, città): così avanzano
# INDIPENDENTI (leva = i%7, città = i%13) e copre TUTTE le combinazioni città×leva prima di ripetere.
_PERIODO = len(ANGOLI) * len(CITTA_TOP) // math.gcd(len(ANGOLI), len(CITTA_TOP))

# Lingua consigliata per città (parlare la lingua del posto). Ripiego: inglese, MAI italiano fuori Italia.
LINGUA_CITTA = {
    "Roma": "it", "Milano": "it", "Firenze": "it", "Venezia": "it", "Napoli": "it",
    "Barcelona": "es", "Madrid": "es", "Mexico City": "es", "Buenos Aires": "es",
    "Paris": "fr", "Lisbon": "pt", "Berlin": "de", "Amsterdam": "en", "London": "en",
    "New York": "en", "Miami": "en", "Dubai": "en", "Bangkok": "en", "Tokyo": "ja",
    "Istanbul": "en",
}
NOME_LINGUA = {"it": "italiano", "en": "inglese", "es": "spagnolo", "fr": "francese",
               "de": "tedesco", "pt": "portoghese", "ja": "giapponese", "zh": "cinese"}

# Ordine di lingua scritto NELLA LINGUA STESSA: è il modo più affidabile per far obbedire il modello
# (un'istruzione italiana annegata in un prompt italiano viene ignorata → esce italiano ovunque). Va
# messo in cima E in fondo al prompt (il modello pesa molto l'ultima riga).
_ORDINE_LINGUA = {
    "it": "Scrivi la didascalia esclusivamente in italiano.",
    "en": "Write the caption exclusively in English. Do not use any Italian.",
    "es": "Escribe la descripción exclusivamente en español. No uses italiano.",
    "fr": "Écris la légende exclusivement en français. N'utilise pas d'italien.",
    "de": "Schreibe die Bildunterschrift ausschließlich auf Deutsch. Kein Italienisch.",
    "pt": "Escreve a legenda exclusivamente em português. Não uses italiano.",
    "ja": "キャプションは必ず日本語だけで書いてください。イタリア語は使わないでください。",
    "zh": "请只用中文写这段文案，不要使用意大利语。",
}

# Ripiego in INGLESE (universale) per le citta' non italiane quando l'AI e' spenta (mai italiano fuori Italia).
RIPIEGO_EN = {
    "reciprocita": "Publish your place in {citta} on BookinVIP: 0% commission for your first 90 days, "
                   "only a technical fee of 5% + EUR 0.25. Message me to start. bookinvip.com",
    "unita": "Join the founding class of hosts in {citta}. 0% commission for 90 days, guests pay 0% fee. "
             "Message me: bookinvip.com",
    "scarsita": "I'm hand-picking the first hosts in {citta} — few spots. 0% commission for 90 days. "
                "Message me to join BookinVIP. bookinvip.com",
    "riprova_sociale": "Hosts in {citta} are joining BookinVIP. 0% commission for 90 days, guests pay 0% "
                       "fee. Be among the first: bookinvip.com",
    "autorita": "We tell you the cost before you sign: a technical fee of 5% + EUR 0.25 per booking, "
                "covering collection and payout. Guests pay 0%. No surprises. bookinvip.com",
    "simpatia": "No call center: I set up your account and guide you myself. Ten minutes and the photos "
                "of your place in {citta}. bookinvip.com",
    "coerenza": "The first step is small: ten minutes and the photos of your place in {citta}. We handle "
                "the rest. bookinvip.com",
}


def _riempi(testo: str, citta: str) -> str:
    try:
        return str(testo).replace("{citta}", str(citta or "Roma"))
    except Exception:
        return str(testo)


# Parole ITALIANE inequivocabili (discriminano da spagnolo/portoghese/francese, lingue-sorelle):
#  - pubblic*  = doppia-b, solo italiano (es: publica, pt: publicar, fr: publier — mai due b)
#  - alloggi*  = solo italiano (es: alojamiento, pt: alojamento, fr: logement)
#  - giorni / scrivimi / il tuo / commission[ei] (con la vocale finale) = solo italiano
_SPIA_ITALIANO = re.compile(
    r"(pubblic\w*|alloggi\w*|\bgiorni\b|\bscrivimi\b|\bil tuo\b|\bcommission[ei]\b)", re.IGNORECASE)


def _contaminato_italiano(testo: str, lingua: str) -> bool:
    """True se la lingua target NON è italiano ma il testo contiene parole ITALIANE inequivocabili.
    Regola d'oro del progetto: mai italiano fuori Italia. Usato per scartare le didascalie contaminate."""
    if lingua == "it":
        return False
    return bool(_SPIA_ITALIANO.search(testo or ""))


# Pulizia di SICUREZZA della didascalia: GARANTISCE niente emoji e niente premesse/spiegazioni,
# a prescindere da cosa scrive il modello (il fondatore non vuole emoji; il modello a volte sbroda).
_EMOJI = re.compile(
    "[🀀-🫿"    # emoji, simboli e pittogrammi
    "☀-➿"     # simboli vari + dingbats
    "🇦-🇿"     # bandiere
    "⬀-⯿"     # simboli e frecce emoji
    "︀-️"     # selettori di variazione
    "Ⓜ⃣]", flags=re.UNICODE)
_PREAMBOLO = re.compile(
    r"^\s*(ecco\b[^:\n]{0,60}:|didascalia\s*:|caption\s*:|post\s*:|testo\s*:)\s*", re.IGNORECASE)


def pulisci_didascalia(testo: Any) -> str:
    """Toglie emoji, virgolette attorno al testo e premesse tipo «Ecco una didascalia:». Non solleva."""
    try:
        t = str(testo or "").strip()
        t = _PREAMBOLO.sub("", t).strip()
        t = _EMOJI.sub("", t)
        t = re.sub(r"(\s*#\w+)+\s*$", "", t)           # hashtag finali PRIMA (il copy pro non li usa)
        t = t.strip(" \t\"«»'“”")                      # poi virgolette/spazi attorno (anche non appaiate)
        t = re.sub(r"[ \t]{2,}", " ", t)
        t = re.sub(r" +([,.;:!?])", r"\1", t)          # spazio prima della punteggiatura (emoji tolte)
        return re.sub(r"\n{3,}", "\n\n", t).strip()
    except Exception:
        return str(testo or "").strip()


def url_immagine(soggetto: str, *, larghezza: int = 1280, altezza: int = 720, seme: int = 0) -> str:
    """URL Pollinations con modello flux (NITIDO, alta qualita'), keyless. Deterministico."""
    prompt = "%s, sharp focus, ultra detailed, high resolution, professional photography, 4k" % (
        str(soggetto or "elegant apartment")[:380])
    return "%s%s?width=%d&height=%d&nologo=true&model=flux&enhance=true&seed=%d" % (
        POLLINATIONS, quote(prompt), int(larghezza), int(altezza), int(seme) % 1000000)


class GeneratoreCampagna:
    """Genera contenuti persuasivi a rotazione. `genera_testo`: Callable[[str], str|None] (AI iniettabile;
    None o ripiego stringa vuota -> usa la didascalia di ripiego). `stato_path`: file JSON durevole per
    la rotazione ("" = solo memoria, per i test). Non solleva mai."""

    def __init__(self, genera_testo: Optional[Callable[[str], Optional[str]]] = None, *,
                 citta: str = "Roma", stato_path: str = "",
                 larghezza: int = 1280, altezza: int = 720) -> None:
        self._ai = genera_testo if callable(genera_testo) else None
        self._citta = citta or "Roma"
        self._stato_path = str(stato_path or "")
        self._w = int(larghezza)
        self._h = int(altezza)
        self._i_mem = 0

    # ── rotazione durevole ────────────────────────────────────────────────────
    def _leggi_indice(self) -> int:
        if not self._stato_path:
            return self._i_mem
        try:
            with open(self._stato_path, encoding="utf-8") as f:
                return int(json.load(f).get("i", 0)) % _PERIODO
        except Exception:
            return 0

    def _scrivi_indice(self, i: int) -> None:
        i = int(i) % _PERIODO
        if not self._stato_path:
            self._i_mem = i
            return
        try:
            with open(self._stato_path, "w", encoding="utf-8") as f:
                json.dump({"i": i}, f)
        except Exception:
            self._i_mem = i
            logger.warning("campagna: stato rotazione non scrivibile (uso memoria)", exc_info=True)

    def _angolo_per_chiave(self, chiave: Any) -> Optional[Dict[str, str]]:
        for a in ANGOLI:
            if a["chiave"] == chiave:
                return a
        return None

    # ── il prompt per l'AI (didascalia persuasiva) ─────────────────────────────
    @staticmethod
    def _prompt_ai(angolo: Dict[str, str], citta: str, lingua: str = "it") -> str:
        lang = NOME_LINGUA.get(lingua, "inglese")
        ordine = _ORDINE_LINGUA.get(lingua, _ORDINE_LINGUA["en"])
        # Anti-contaminazione: le istruzioni sono in italiano; senza questo il modello ripeteva parole
        # italiane ("Pubblica…") anche scrivendo in un'altra lingua (bug reale visto su Lisbona/Parigi).
        anti_it = ("" if lingua == "it" else
                   " Le istruzioni qui sopra sono in italiano SOLO per te: la didascalia non deve "
                   "contenere NESSUNA parola italiana — traduci tutto in %s, comprese le prime parole." % lang)
        corpo = (
            # LINGUA in cima, nella lingua stessa (forte)
            (ordine + "\n\n") +
            "Sei un copywriter pubblicitario esperto (scuola Ogilvy) che scrive per BookinVIP, una nuova "
            "piattaforma di prenotazioni di alloggi che parte a %s. Fatti reali e SPECIFICI da usare: "
            "l'host pubblica gratis con 0%% di commissione per i primi 90 giorni (poi 8%%, poi 10%%); "
            "l'ospite paga sempre 0%% di fee; c'e' una tariffa tecnica del 5%% + 0,25 EUR a prenotazione, "
            "dichiarata PRIMA della firma (copre incasso e bonifico). Promessa del brand: «Il tuo viaggio, "
            "senza sorprese».\n\n"
            "Scrivi UNA sola didascalia da social per invitare un HOST di %s a pubblicare il suo "
            "alloggio, applicando questa leva psicologica:\n%s\n\n"
            "Regole di copywriting, rispettale TUTTE:\n"
            "- Massimo 280 caratteri.\n"
            "- La prima frase e' un aggancio che promette un beneficio concreto.\n"
            "- SPECIFICO e concreto: usa i numeri veri (0%%, 90 giorni, 5%% + 0,25 EUR), mai vago.\n"
            "- UN solo beneficio e UN solo invito all'azione chiaro (es. «scrivimi» oppure «bookinvip.com»).\n"
            "- Linguaggio semplice e onesto: niente frasi furbe, niente superlativi gonfiati, niente promesse false.\n"
            "- NIENTE emoji. NIENTE hashtag. NIENTE virgolette attorno al testo.\n"
            "- NON premettere spiegazioni o introduzioni (vietato iniziare con «Ecco una didascalia» o simili): "
            "scrivi SOLTANTO il testo del post, nient'altro.\n\n"
            % (citta, citta, _riempi(angolo["istruzione"], citta))
        )
        # LINGUA ripetuta in fondo (posizione più pesante per il modello) + anti-contaminazione
        return corpo + ("IMPORTANTE — la lingua della didascalia: %s Il testo finale deve essere "
                        "interamente in %s.%s" % (ordine, lang, anti_it))

    def genera(self, *, angolo_chiave: Optional[str] = None,
               citta: Optional[str] = None, lingua: Optional[str] = None,
               seme: int = 0) -> Dict[str, Any]:
        """Genera un contenuto. Se `angolo_chiave` e' dato usa quella leva (senza avanzare la rotazione);
        altrimenti prende la leva successiva e avanza. `lingua` (default 'it') decide la lingua della
        didascalia AI E del ripiego (it→ripiego italiano, altro→RIPIEGO_EN inglese). Ritorna:
        {leva, chiave, didascalia, immagine, da_ai(bool), citta, lingua}. Non solleva."""
        citta = citta or self._citta
        lingua = lingua or "it"
        avanza = angolo_chiave is None
        if angolo_chiave is not None:
            ang = self._angolo_per_chiave(angolo_chiave) or ANGOLI[0]
        else:
            i = self._leggi_indice()
            ang = ANGOLI[i % len(ANGOLI)]

        # 1) didascalia via AI, con ripiego mai-vuoto (nella lingua giusta).
        #    Rete di sicurezza LINGUA: fuori Italia la didascalia non deve contenere italiano; se il
        #    modello contamina (portoghese/italiano quasi gemelli), scarto e riprovo una volta, poi ripiego.
        ripiego = ang["ripiego"] if lingua == "it" else RIPIEGO_EN.get(ang["chiave"], ang["ripiego"])
        didascalia = ""
        da_ai = False
        if self._ai is not None:
            for tentativo in range(2):
                try:
                    testo = self._ai(self._prompt_ai(ang, citta, lingua))
                except Exception:
                    logger.warning("campagna: AI testo fallita (uso ripiego)", exc_info=True)
                    break
                pulito = pulisci_didascalia(testo) if isinstance(testo, str) else ""
                if pulito and not _contaminato_italiano(pulito, lingua):
                    didascalia = pulito[:600]
                    da_ai = True
                    break
                logger.info("campagna: didascalia scartata (vuota/italiano fuori Italia), tentativo %d",
                            tentativo + 1)
        if not didascalia:
            didascalia = pulisci_didascalia(_riempi(ripiego, citta))

        # 2) immagine flux (keyless), soggetto della leva; il seme varia per non ripetere la stessa
        immagine = url_immagine(_riempi(ang["soggetto"], citta), larghezza=self._w,
                                altezza=self._h, seme=seme or (self._leggi_indice() + 1) * 7)

        if avanza:
            self._scrivi_indice(self._leggi_indice() + 1)

        return {"leva": ang["nome"], "chiave": ang["chiave"], "didascalia": didascalia,
                "immagine": immagine, "da_ai": da_ai, "citta": citta, "lingua": lingua}

    def genera_globale(self, *, seme: int = 0) -> Dict[str, Any]:
        """Come genera(), ma sceglie la CITTA' dal giro delle destinazioni top del mondo (CITTA_TOP)
        e la LINGUA locale di quella citta' (LINGUA_CITTA). 13 citta' e 7 leve sono coprimi: la
        rotazione durevole copre tutte le 91 combinazioni citta×leva prima di ripetersi. Non solleva."""
        i = self._leggi_indice()
        citta = CITTA_TOP[i % len(CITTA_TOP)]
        lingua = LINGUA_CITTA.get(citta, "en")
        return self.genera(citta=citta, lingua=lingua, seme=seme)

    def genera_giro_completo(self, *, citta: Optional[str] = None,
                             lingua: Optional[str] = None) -> List[Dict[str, Any]]:
        """Un esempio per OGNI leva (per l'anteprima). Non tocca lo stato di rotazione."""
        return [self.genera(angolo_chiave=a["chiave"], citta=citta, lingua=lingua, seme=(idx + 1) * 13)
                for idx, a in enumerate(ANGOLI)]


def crea_generatore_campagna(genera_testo: Optional[Callable[[str], Optional[str]]] = None, *,
                             citta: str = "Roma", stato_path: str = "") -> GeneratoreCampagna:
    return GeneratoreCampagna(genera_testo, citta=citta, stato_path=stato_path)
