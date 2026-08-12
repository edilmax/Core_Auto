"""
CORE_AUTO - Fase 66: Tassa di soggiorno automatica (jurisdiction-agnostic).

Gli alloggi nel mondo devono riscuotere una tassa di soggiorno (city tax / tourist tax)
che varia per ogni citta': importo per-persona-per-notte, percentuale, tetto notti,
esenzioni (bambini). Un sistema GLOBALE non puo' hardcodare le regole italiane/UE: la
direttiva del progetto e' esplicita -> mai IVA/regole EU hardcoded, tassa via parametro
con default ZERO. Una giurisdizione sconosciuta NON paga una tassa inventata da noi.

La tassa e' una VOCE SEPARATA e VISIBILE (come la PSP-fee in fase43): pass-through verso
l'autorita', NON margine dell'host, NON nostra commissione. Cosi' il prezzo netto host e
il nostro incasso restano misurabili, e il guest vede chiaramente cosa paga e a chi.

Modello (copre i casi reali nel mondo), tutto in CENTESIMI INTERI:
  tassa = componente_fissa + componente_percentuale
    componente_fissa = ospiti_tassabili * min(per_persona_notte*notti_tassabili, tetto)
    componente_percentuale = percentuale_bps * imponibile_cents // 10000
  con notti_tassabili = min(notti, max_notti_tassabili) [cap notti, comune: es. 7]
       ospiti_tassabili = max(0, ospiti - esenti) [esenzioni: bambini, ecc.]
       tetto = tetto_per_persona_soggiorno_cents (alcune citta' cappano per persona).

VINCITRICE DEL BENCHMARK (4 modelli):
  V3 'regola INIETTABILE (per-persona-notte + % + cap-notti + esenti + tetto), default
  ZERO per giurisdizione ignota, interi'. Copre i modelli reali, e' configurabile per
  citta' senza toccare il codice, e non inventa MAI una tassa dove non la conosce. Le
  altre perdono: V1 'hardcode IT/EU' viola jurisdiction-agnostic ed e' errato altrove;
  V2 'solo percentuale' non modella la per-persona-per-notte (la forma piu' comune);
  V4 'percentuali float' introduce drift sui centesimi.

SOPRAVVIVENZA TOTALE: calcolo PURO e deterministico; validazione fail-closed (input non
interi/negativi -> tassa 0, mai un'eccezione); zero dipendenze; zero float.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("core_auto.tassa_soggiorno")

MAX_CENTS = 1_000_000_00


def _intero_nn(v: Any) -> bool:
    """Intero non-negativo (no bool, no float)."""
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


_VALUTA_OK = re.compile(r"^[A-Z]{3}$")


def _regola_malformata(regola: "RegolaTassa") -> bool:
    """⛔ «INVALIDO» NON E' «ASSENTE», e confonderli faceva pagare di PIU' (2026-08-12).

    I due campi `Optional` (`max_notti_tassabili`, `tetto_per_persona_soggiorno_cents`) sono
    dei TETTI: quando ci sono, l'ospite paga di meno. Il codice li leggeva con un semplice
    «e' un intero non-negativo? no -> non applicarlo», cioe' trattava un valore SBAGLIATO
    esattamente come un valore ASSENTE. Ma per un tetto «assente» non vuol dire «niente
    tassa»: vuol dire **«nessuno sconto»**. Risultato: un meno battuto per sbaglio in
    configurazione (`-1` invece di `7`) non spegneva la tassa, TOGLIEVA IL TETTO.

    MISURATO, non dedotto: `per_persona_notte=350, cap=-1, 30 notti, 2 ospiti` dava
    **21000 cents** invece dei 4900 del cap valido -- 161,00 EUR in piu' a carico dell'ospite.

    Qui la distinzione e' esplicita: `None` = assente (legittimo, nessun cap), qualunque
    altra cosa non-intera-non-negativa = **regola malformata** -> il chiamante va a tassa 0.
    E' la stessa risposta che il modulo da' gia' a una giurisdizione sconosciuta: quando non
    si sa leggere una regola non si inventa una tassa.

    ⛔ COSA NON GUARDA (D18 punto 3): non giudica la `valuta` -- quella e' solo un'etichetta
    sul percorso dei soldi (la valuta dell'addebito la decide `fase59` dall'annuncio) e
    renderla causa di malformazione azzererebbe tasse vere per una stringa storta nel
    database. La valuta viene invece validata dove NASCE dal testo, in `da_env`.
    """
    for campo in ("per_persona_notte_cents", "percentuale_bps"):
        if not _intero_nn(getattr(regola, campo, None)):
            return True
    for campo in ("max_notti_tassabili", "tetto_per_persona_soggiorno_cents"):
        valore = getattr(regola, campo, None)
        if valore is not None and not _intero_nn(valore):
            return True
    return False


@dataclass(frozen=True)
class RegolaTassa:
    """Regola di una giurisdizione. Default = tutto 0 -> tassa 0 (jurisdiction-agnostic)."""
    per_persona_notte_cents: int = 0
    percentuale_bps: int = 0                       # su imponibile (prezzo)
    max_notti_tassabili: Optional[int] = None      # None = nessun cap
    tetto_per_persona_soggiorno_cents: Optional[int] = None
    valuta: str = "EUR"                            # solo etichetta


REGOLA_ZERO = RegolaTassa()


@dataclass(frozen=True)
class CalcoloTassa:
    tassa_cents: int
    componente_fissa_cents: int
    componente_percentuale_cents: int
    notti_tassabili: int
    ospiti_tassabili: int
    valuta: str = "EUR"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tassa_cents": self.tassa_cents,
            "componente_fissa_cents": self.componente_fissa_cents,
            "componente_percentuale_cents": self.componente_percentuale_cents,
            "notti_tassabili": self.notti_tassabili,
            "ospiti_tassabili": self.ospiti_tassabili,
            "valuta": self.valuta,
            "money_unit": "cents_integer",
        }


def calcola_tassa(regola: RegolaTassa, *, notti: int, ospiti: int,
                  imponibile_cents: int = 0, esenti: int = 0) -> CalcoloTassa:
    """Calcola la tassa di soggiorno. BLINDATO: input invalidi -> tassa 0 (fail-closed)."""
    if not isinstance(regola, RegolaTassa):
        regola = REGOLA_ZERO
    if not (_intero_nn(notti) and _intero_nn(ospiti)):
        return CalcoloTassa(0, 0, 0, 0, 0, getattr(regola, "valuta", "EUR"))
    if _regola_malformata(regola):
        # regola che non si sa leggere = nessuna regola. Mai inventare una tassa.
        return CalcoloTassa(0, 0, 0, 0, 0, getattr(regola, "valuta", "EUR"))
    imponibile = imponibile_cents if _intero_nn(imponibile_cents) else 0
    esenti = esenti if _intero_nn(esenti) else 0

    # ⛔ QUI SOTTO NON C'E' NESSUN CONTROLLO SUI TIPI, ED E' UNA SCELTA MISURATA (2026-08-12).
    # Dopo `_regola_malformata` ogni campo della regola e' gia' un intero non-negativo (o
    # `None` dove `None` e' legittimo): i `_intero_nn(...)` che stavano qui erano rami che
    # NON POSSONO essere falsi, cioe' codice morto travestito da prudenza (D19). E i
    # `... > 0` erano scorciatoie inutili: con 0 l'aritmetica da' 0 da sola.
    #
    # Non e' una pulizia estetica: quei rami erano **11 punti che il Giudice della mutazione
    # segnalava come NON SORVEGLIATI** e che nessun collaudo poteva uccidere, perche' non
    # cambiavano nessun risultato osservabile. Toglierli e' l'unico modo onesto di chiuderli:
    # l'alternativa era dichiararli equivalenti, e B6 lo vieta senza dimostrazione.
    #
    # LA DIMOSTRAZIONE C'E', ed e' una MISURA: le due versioni (con e senza questi controlli)
    # sono state fatte girare fianco a fianco su **90.400 combinazioni** -- tutta la griglia
    # degli ingressi ammessi piu' 400 casi con valori sporchi (`-1`, `7.5`, `True`, `"7"`,
    # `None`) in ogni posizione. Risultato: **zero differenze e zero eccezioni sollevate**.
    # Il contratto «mai un'eccezione» regge perche' la precondizione viene PRIMA.
    notti_tass = min(notti, regola.max_notti_tassabili) \
        if regola.max_notti_tassabili is not None else notti
    ospiti_tass = max(0, ospiti - esenti)

    per_persona = regola.per_persona_notte_cents * notti_tass
    tetto = regola.tetto_per_persona_soggiorno_cents
    if tetto is not None:
        per_persona = min(per_persona, tetto)
    fissa = per_persona * ospiti_tass

    perc = (regola.percentuale_bps * imponibile) // 10000   # intero, no float

    tassa = fissa + perc
    if tassa > MAX_CENTS:
        # ⛔ CINTURA ANTI-ABUSO, MA SENZA ROMPERE IL BILANCIO (riparato 2026-08-12).
        # Prima qui si tagliava SOLO il totale a MAX_CENTS lasciando intatte le due
        # componenti: da quel momento `tassa != fissa + percentuale` e chi riconcilia
        # (il giornale di fase177, il breakdown di fase69) trovava un buco. Misurato:
        # totale 100000000 contro componenti per 400000010.
        # Si va a ZERO, non a MAX_CENTS: una tassa di soggiorno da un milione di euro non
        # esiste in nessuna citta' del mondo -- e' una configurazione rotta, e per una
        # configurazione rotta questo modulo ha gia' la sua risposta: non inventare una
        # tassa. Tagliare a MAX_CENTS avrebbe voluto dire addebitarlo davvero all'ospite.
        logger.error("tassa oltre il tetto (%d > %d): configurazione rotta, tassa 0",
                     tassa, MAX_CENTS)
        return CalcoloTassa(0, 0, 0, notti_tass, ospiti_tass, regola.valuta)
    return CalcoloTassa(tassa, fissa, perc, notti_tass, ospiti_tass, regola.valuta)


# ─────────────────────────────────────────────────────────────────────────────
# Registro delle regole per giurisdizione (citta'/locale)
# ─────────────────────────────────────────────────────────────────────────────
class RegistroTasse:
    """giurisdizione -> RegolaTassa. Giurisdizione ignota -> REGOLA_ZERO (tassa 0)."""

    def __init__(self, regole: Optional[Dict[str, RegolaTassa]] = None, *,
                 default: RegolaTassa = REGOLA_ZERO) -> None:
        self._regole = dict(regole or {})
        self._default = default

    def regola(self, giurisdizione: Any) -> RegolaTassa:
        if not isinstance(giurisdizione, str):
            return self._default
        return self._regole.get(giurisdizione.strip().lower(), self._default)

    def calcola(self, giurisdizione: Any, *, notti: int, ospiti: int,
                imponibile_cents: int = 0, esenti: int = 0) -> CalcoloTassa:
        return calcola_tassa(self.regola(giurisdizione), notti=notti, ospiti=ospiti,
                             imponibile_cents=imponibile_cents, esenti=esenti)

    @classmethod
    def da_env(cls, var: str = "TASSE_SOGGIORNO") -> "RegistroTasse":
        """Carica 'citta=ppn:maxnotti:percbps[:VALUTA],...' (ppn = per-persona-notte cents;
        maxnotti vuoto = nessun cap; VALUTA opzionale, 3 lettere, default EUR).
        Es: 'roma=350:10:0,amsterdam=0::700,londra=200::0:GBP'.

        ⛔ UNA RIGA MALFORMATA SI SCARTA, NON SI AGGIUSTA (riparato 2026-08-12). Prima un
        `maxnotti` negativo veniva "aggiustato" a `None`, cioe' a NESSUN cap: `roma=350:-1:0`
        tassava tutte le 30 notti (21000 cents) invece delle 7 di `roma=350:7:0` (4900). Un
        meno battuto per sbaglio faceva pagare di piu' all'ospite, in silenzio. Adesso quella
        citta' esce dal registro e ricade sul default (tassa 0): le altre citta' della stessa
        riga restano valide, perche' scartare il rotto non deve spegnere il buono.

        ⚠️ LIMITE DICHIARATO (D18 punto 3): da qui NON si configura
        `tetto_per_persona_soggiorno_cents`, che resta raggiungibile solo costruendo la
        `RegolaTassa` a mano (come fa `fase57.regola_tassa_di` dal database dell'annuncio).
        E' un formato piu' povero del modello, e dirlo e' meglio che lasciarlo scoprire.
        """
        import os
        regole: Dict[str, RegolaTassa] = {}
        for riga in os.environ.get(var, "").split(","):
            riga = riga.strip()
            if "=" not in riga:
                continue
            citta, spec = riga.split("=", 1)
            parti = (spec.split(":") + ["", "", "", ""])[:4]
            try:
                ppn = int(parti[0]) if parti[0].strip() else 0
                maxn = int(parti[1]) if parti[1].strip() else None
                perc = int(parti[2]) if parti[2].strip() else 0
            except (ValueError, TypeError):
                continue
            valuta = parti[3].strip().upper() or "EUR"
            if ppn < 0 or perc < 0 or (maxn is not None and maxn < 0):
                logger.warning("regola tassa scartata (valore negativo): %r", riga)
                continue
            if not _VALUTA_OK.match(valuta):
                logger.warning("regola tassa scartata (valuta non valida): %r", riga)
                continue
            if citta.strip():
                regole[citta.strip().lower()] = RegolaTassa(
                    per_persona_notte_cents=ppn,
                    max_notti_tassabili=maxn,
                    percentuale_bps=perc,
                    valuta=valuta)
        return cls(regole)


def crea_registro_tasse(regole: Optional[Dict[str, RegolaTassa]] = None) -> RegistroTasse:
    return RegistroTasse(regole)
