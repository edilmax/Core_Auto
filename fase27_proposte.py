"""
CORE_AUTO - Fase 27 / BLOCCO 3.2: Generatore di proposte commerciali.

Trasforma le proposte trovate dal motore di ricerca (Fase 26) in OFFERTE
commerciali pronte all'invio, calcolando le commissioni con **precisione
decimale assoluta** (centesimi interi via Fase 17 — il denaro non passa MAI per
float, e i conti non vengono MAI delegati all'IA).

Strategia = **Variante C**, vincitrice di un benchmark a 3 varianti
(IA-only / template / template+rifinitura-IA): i NUMERI sono sempre
deterministici (consegna corretta al 100% anche con IA giu' o inaffidabile),
mentre l'IA aggiunge solo una rifinitura testuale OPZIONALE che degrada al
template. La IA-only e' risultata pericolosa (numeri sbagliati 1/3 + crash se giu').

Isola (North Star): qualunque problema del generatore -> una cortese NOTA DI
ATTESA, mai un crash. Modulo a sé (proposte gestite per duck-typing).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, List, Optional

from fase17_money import euro_to_cents, applica_percentuale, cents_to_str

logger = logging.getLogger("core_auto.proposte")

COMMISSIONE_DEFAULT = Decimal("0.10")  # 10%
NOTA_ATTESA = ("Grazie per il tuo interesse! Sto preparando una proposta su "
               "misura per te, ti rispondo a brevissimo.")


@dataclass(frozen=True)
class VoceOfferta:
    """Una riga d'offerta, tutti gli importi in CENTESIMI interi (esatti)."""
    titolo: str
    localita: str
    prezzo_cent: int
    commissione_cent: int
    totale_cliente_cent: int


@dataclass
class RisultatoOfferta:
    testo: str
    ok: bool
    esito: str  # "completa" | "completa_ai" | "fallback_attesa"
    voci: List[VoceOfferta]


class GeneratoreProposte:
    """Genera offerte commerciali con commissioni a precisione decimale assoluta.

    I numeri sono SEMPRE deterministici (Variante C); l'`agente` opzionale
    aggiunge solo una rifinitura introduttiva che degrada al template se l'IA
    non e' affidabile. `genera` non solleva MAI."""

    def __init__(self, commissione: Decimal = COMMISSIONE_DEFAULT,
                 agente: Any = None) -> None:
        self._commissione = Decimal(commissione)
        self._agente = agente

    def genera(self, proposte: List[Any]) -> RisultatoOfferta:
        try:
            voci = [self._voce(p) for p in proposte]
            corpo = self._formatta(voci)
            testo, esito = corpo, "completa"
            if self._agente is not None:
                intro = self._intro_ai()
                if intro:
                    testo = intro.rstrip() + "\n\n" + corpo
                    esito = "completa_ai"
            return RisultatoOfferta(testo, True, esito, voci)
        except Exception:
            logger.error("Generatore offerte fallito (-> nota di attesa)", exc_info=True)
            return RisultatoOfferta(NOTA_ATTESA, False, "fallback_attesa", [])

    def _voce(self, p: Any) -> VoceOfferta:
        prezzo_cent = euro_to_cents(p.prezzo)            # float listing -> centesimi (Decimal)
        commissione_cent = applica_percentuale(prezzo_cent, self._commissione)
        return VoceOfferta(
            titolo=str(getattr(p, "titolo", "")),
            localita=str(getattr(p, "localita", "")),
            prezzo_cent=prezzo_cent,
            commissione_cent=commissione_cent,
            totale_cliente_cent=prezzo_cent + commissione_cent)

    def _formatta(self, voci: List[VoceOfferta]) -> str:
        if not voci:
            return "Al momento non ho proposte disponibili per i tuoi criteri."
        perc = format((self._commissione * 100).normalize(), "f")
        righe = ["Ecco la tua proposta personalizzata:"]
        for i, v in enumerate(voci, 1):
            righe.append(f"{i}. {v.titolo} ({v.localita})")
            righe.append(
                f"   Prezzo: {cents_to_str(v.prezzo_cent)} EUR | "
                f"Servizio ({perc}%): {cents_to_str(v.commissione_cent)} EUR | "
                f"Totale: {cents_to_str(v.totale_cliente_cent)} EUR")
        righe.append("\nRispondi a questo messaggio per confermare. "
                     "Resto a tua disposizione!")
        return "\n".join(righe)

    def _intro_ai(self) -> Optional[str]:
        """Rifinitura IA opzionale: ritorna un'introduzione solo se l'agente ha
        prodotto una risposta affidabile, altrimenti None (si usa il template)."""
        try:
            r = self._agente.genera_risposta(
                "Scrivi un'introduzione commerciale breve, cordiale e "
                "professionale per una proposta di alloggi (max 1 frase).")
            return r.testo if getattr(r, "ok", False) else None
        except Exception:
            logger.warning("Rifinitura IA non disponibile (uso template)")
            return None


def componi_offerta(motore: Any, generatore: GeneratoreProposte,
                    criteri: Any) -> RisultatoOfferta:
    """Pipeline isolata: ricerca PROTETTA -> generazione offerta. Entrambi gli
    anelli sono fail-safe, quindi non puo' mai crashare: al peggio una nota di
    attesa (generatore) su proposte vuote (motore giu')."""
    ris = motore.cerca(criteri)
    return generatore.genera(ris.proposte)
