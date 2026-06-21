"""
CORE_AUTO - Fase 68: Niche Profiler (niche stacking) - servire i mercati invisibili.

I colossi fanno "tutto per tutti = niente per nessuno". Ci sono mercati ENORMI che
nessuno serve bene, perche' per loro sono solo una checkbox:
  - Pet-friendly (~$5B, 70% famiglie USA con animali): non solo "sì/no", ma taglia del
    cane, kit pet, giardino recintato, supplemento pet trasparente;
  - Solo traveler (~$549B, 84% donne): le OTA puniscono col "supplemento singola"; noi
    NO supplemento + zona sicura;
  - Digital nomad: cercano il MESE, non la notte; scrivania, WiFi veloce, tariffa mensile;
  - Accessibility (1 mld di persone): filtri GRANULARI veri (ingresso senza gradini,
    doccia accessibile, allarme visivo), NESSUN supplemento (e' un diritto, non un extra);
  - Family, micro-adventure weekend, ecc.

L'arma e' il NICHE STACKING: un alloggio con UNA sola maschera di attributi puo'
soddisfare N nicchie insieme -> piu' prenotazioni, e (via Rana Inversa fase43) piu'
nicchie = commissione minima -> incentivo a essere specifici. Tutto a costo zero.

QUESTO MODULO NON TOCCA fase57: e' una LIBRERIA additiva che COMPONE con la vetrina
(stessa logica bitmask gia' collaudata in fase57). Il denaro (supplementi/sconti) e'
calcolato dal CORE in centesimi interi.

VINCITRICE DEL BENCHMARK (4 modi di modellare le nicchie):
  V3 'bitmask di attributi + profili nominati componibili + pricing iniettabile'. Una
  maschera intera serve N nicchie (stacking), ricercabile come AND intero, data-driven
  (nuove nicchie senza toccare il codice). Le altre perdono: V1 'tag testo libero' =
  incoerente, non ricercabile; V2 'colonna booleana per nicchia' = esplosione di schema,
  rigido; V4 'matching ML/embedding' = overkill, non-deterministico, a costo.

SOPRAVVIVENZA TOTALE: funzioni PURE e deterministiche; attributi/profili ignoti
ignorati (fail-safe); pricing fail-closed su input invalidi; denaro intero, no float;
accessibilita' SENZA supplemento per costruzione. Zero dipendenze.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

logger = logging.getLogger("core_auto.niche_profiler")

MAX_CENTS = 1_000_000_00


def _intero_nn(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


# ─────────────────────────────────────────────────────────────────────────────
# Vocabolario attributi nicchia (bitmask; aggiungere SOLO in coda, mai riusare un bit)
# ─────────────────────────────────────────────────────────────────────────────
_ATTR_LISTA = [
    # pet
    "pet_friendly", "pet_cane_piccolo", "pet_cane_grande", "pet_gatto", "pet_kit",
    "giardino_recintato",
    # solo
    "solo_friendly", "no_supplemento_singola", "zona_sicura",
    # nomad
    "nomad_friendly", "scrivania", "wifi_veloce", "zona_silenziosa", "cucina_attrezzata",
    # accessibility
    "acc_ingresso_senza_gradini", "acc_porta_larga", "acc_doccia_accessibile",
    "acc_maniglioni", "acc_allarme_visivo", "acc_animale_assistenza",
    # family
    "fam_culla", "fam_seggiolone", "fam_camere_comunicanti",
    # micro-adventure
    "weekend", "tema_wellness", "tema_natura", "tema_gastronomia", "tema_avventura",
]
ATTRIBUTI: Dict[str, int] = {nome: 1 << i for i, nome in enumerate(_ATTR_LISTA)}

# Profili nominati = insieme di attributi RICHIESTI (AND).
PROFILI: Dict[str, Tuple[str, ...]] = {
    "pet_cane_grande": ("pet_friendly", "pet_cane_grande"),
    "pet_cane_piccolo": ("pet_friendly", "pet_cane_piccolo"),
    "pet_gatto": ("pet_friendly", "pet_gatto"),
    "solo": ("solo_friendly", "no_supplemento_singola"),
    "nomad": ("nomad_friendly", "scrivania", "wifi_veloce"),
    "accessibile_sedia_rotelle": ("acc_ingresso_senza_gradini", "acc_porta_larga",
                                   "acc_doccia_accessibile"),
    "accessibile_ipovedenti": ("acc_allarme_visivo",),
    "family": ("fam_culla", "fam_seggiolone"),
    "weekend_wellness": ("weekend", "tema_wellness"),
    "weekend_natura": ("weekend", "tema_natura"),
}

# Profili che, per principio, NON ammettono supplemento (diritto, non extra).
PROFILI_SENZA_SUPPLEMENTO = ("accessibile_sedia_rotelle", "accessibile_ipovedenti")


def maschera_nicchia(attributi: Sequence[str]) -> int:
    """Codici attributo -> bitmask. Ignoti IGNORATI (fail-safe)."""
    if not isinstance(attributi, (list, tuple, set, frozenset)):
        return 0
    m = 0
    for a in attributi:
        bit = ATTRIBUTI.get(str(a).strip().lower())
        if bit:
            m |= bit
    return m


def _maschera_profilo(nome: str) -> int:
    return maschera_nicchia(PROFILI.get(nome, ()))


def soddisfa(maschera: int, profilo: str) -> bool:
    """L'alloggio (maschera) soddisfa il profilo richiesto? (AND intero indicizzabile)."""
    if not isinstance(maschera, int) or isinstance(maschera, bool) or maschera < 0:
        return False
    req = _maschera_profilo(profilo)
    return req != 0 and (maschera & req) == req


def nicchie_soddisfatte(maschera: int) -> List[str]:
    """Tutte le nicchie servite da questa maschera = NICHE STACKING."""
    return [nome for nome in PROFILI if soddisfa(maschera, nome)]


def attributi_da_maschera(maschera: int) -> List[str]:
    if not isinstance(maschera, int) or isinstance(maschera, bool) or maschera < 0:
        return []
    return [nome for nome, bit in ATTRIBUTI.items() if maschera & bit]


# ─────────────────────────────────────────────────────────────────────────────
# Pricing per nicchia (denaro dal CORE, centesimi interi)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PoliticaNicchia:
    pet_notte_cents: int = 0            # supplemento pet per notte (0 = gratis)
    sconto_settimanale_bps: int = 0    # >= soglia_settimana notti
    sconto_mensile_bps: int = 0        # >= soglia_mese notti (nomad)
    soglia_settimana: int = 7
    soglia_mese: int = 28
    sconto_solo_bps: int = 0           # tariffa solo (no supplemento singola = sconto)


@dataclass(frozen=True)
class CalcoloNicchia:
    base_cents: int
    sconto_lungo_cents: int
    sconto_solo_cents: int
    supplemento_pet_cents: int
    totale_cents: int
    notti: int
    fascia: str                        # 'notte' | 'settimana' | 'mese'

    def as_dict(self) -> Dict[str, Any]:
        return {
            "base_cents": self.base_cents,
            "sconto_lungo_cents": self.sconto_lungo_cents,
            "sconto_solo_cents": self.sconto_solo_cents,
            "supplemento_pet_cents": self.supplemento_pet_cents,
            "totale_cents": self.totale_cents,
            "notti": self.notti, "fascia": self.fascia,
            "money_unit": "cents_integer",
        }


def calcola_prezzo_nicchia(prezzo_notte_cents: int, notti: int, *,
                           politica: PoliticaNicchia, con_pet: bool = False,
                           solo: bool = False) -> CalcoloNicchia:
    """Prezzo soggiorno con sconti lungo-soggiorno (nomad), supplemento pet trasparente
    e tariffa solo. BLINDATO: input invalidi -> base 0 (fail-closed)."""
    if not (_intero_nn(prezzo_notte_cents) and _intero_nn(notti)) or notti == 0 \
            or prezzo_notte_cents == 0:
        return CalcoloNicchia(0, 0, 0, 0, 0, notti if _intero_nn(notti) else 0, "notte")
    base = prezzo_notte_cents * notti

    if notti >= politica.soglia_mese and _intero_nn(politica.sconto_mensile_bps):
        bps, fascia = politica.sconto_mensile_bps, "mese"
    elif notti >= politica.soglia_settimana and _intero_nn(politica.sconto_settimanale_bps):
        bps, fascia = politica.sconto_settimanale_bps, "settimana"
    else:
        bps, fascia = 0, "notte"
    sconto_lungo = (base * bps) // 10000 if bps > 0 else 0

    sconto_solo = 0
    if solo and _intero_nn(politica.sconto_solo_bps) and politica.sconto_solo_bps > 0:
        sconto_solo = (base * politica.sconto_solo_bps) // 10000

    supplemento_pet = 0
    if con_pet and _intero_nn(politica.pet_notte_cents) and politica.pet_notte_cents > 0:
        supplemento_pet = politica.pet_notte_cents * notti

    totale = base - sconto_lungo - sconto_solo + supplemento_pet
    if totale < 1:
        totale = 1                      # mai sotto-zero
    if totale > MAX_CENTS:
        totale = MAX_CENTS
    return CalcoloNicchia(base, sconto_lungo, sconto_solo, supplemento_pet, totale,
                          notti, fascia)


def ammette_supplemento(profili: Sequence[str]) -> bool:
    """False se tra le nicchie c'e' una accessibilita' (nessun supplemento ammesso)."""
    return not any(p in PROFILI_SENZA_SUPPLEMENTO for p in (profili or ()))


# ─────────────────────────────────────────────────────────────────────────────
# Vista nicchie di un alloggio (per la vetrina/MCP)
# ─────────────────────────────────────────────────────────────────────────────
def profilo_alloggio(attributi: Sequence[str]) -> Dict[str, Any]:
    """Riepilogo machine-clean delle nicchie servite (per il frontend/agente)."""
    mask = maschera_nicchia(attributi)
    nicchie = nicchie_soddisfatte(mask)
    return {
        "maschera": mask,
        "attributi": attributi_da_maschera(mask),
        "nicchie": nicchie,
        "n_nicchie": len(nicchie),                 # piu' alto = piu' stacking
        "supplementi_ammessi": ammette_supplemento(nicchie),
    }
