"""
CORE_AUTO - Fase 103: Adempimento reverse-charge (Modulo 5). GATED (attivo=False default),
aliquota/regole CONFIGURABILI (l'utente conferma col commercialista, mai hardcoded come
verità). Fatture estere (Stripe IE, AWS) → autofattura TD17 (servizi) / TD18 (beni intra-UE),
IVA 22% non detraibile, versamento F24 entro il 16 del mese successivo. PURO + registro
durevole. BLINDATO: input invalido → None/no-op.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("core_auto.reverse_charge")


@dataclass(frozen=True)
class ConfigReverseCharge:
    attivo: bool = False
    aliquota_bps: int = 2200       # IVA 22% (configurabile)


def _intero_pos(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def scadenza_f24(data_fattura: str) -> Optional[str]:
    """16 del mese SUCCESSIVO alla fattura. 'YYYY-MM-DD' -> 'YYYY-MM-16'."""
    try:
        a, m, _ = str(data_fattura).split("-")
        anno, mese = int(a), int(m)
        if not (1 <= mese <= 12):
            return None
        mese += 1
        if mese > 12:
            mese, anno = 1, anno + 1
        return "%04d-%02d-16" % (anno, mese)
    except Exception:
        return None


def calcola_autofattura(imponibile_cents: int, data_fattura: str, *,
                        servizio: bool = True,
                        cfg: ConfigReverseCharge = ConfigReverseCharge()
                        ) -> Optional[Dict[str, Any]]:
    """Autofattura reverse-charge: IVA da versare + tipo documento + scadenza F24.
    None se gated-off o imponibile invalido."""
    if not cfg.attivo or not _intero_pos(imponibile_cents):
        return None
    aliquota = max(0, min(10000, int(cfg.aliquota_bps)))
    iva = imponibile_cents * aliquota // 10000
    return {
        "tipo_documento": "TD17" if servizio else "TD18",
        "imponibile_cents": imponibile_cents,
        "aliquota_bps": aliquota,
        "iva_cents": iva,                 # non detraibile in forfettario: costo puro
        "scadenza_f24": scadenza_f24(data_fattura),
    }


class RegistroReverseCharge:
    """Registro durevole (file JSON atomico) delle autofatture e dell'IVA da versare."""

    def __init__(self, percorso: str = "", cfg: ConfigReverseCharge = ConfigReverseCharge()):
        self._p = percorso
        self._cfg = cfg
        self._mem: List[Dict[str, Any]] = []

    def _leggi(self) -> List[Dict[str, Any]]:
        if not self._p:
            return self._mem
        try:
            with open(self._p, encoding="utf-8") as f:
                return json.load(f) or []
        except Exception:
            return []

    def _scrivi(self, lista: List[Dict[str, Any]]) -> None:
        if not self._p:
            self._mem = lista
            return
        try:
            dn = os.path.dirname(self._p) or "."
            fd, tmp = tempfile.mkstemp(dir=dn, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(lista, f)
                os.replace(tmp, self._p)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
        except Exception:
            logger.warning("RegistroReverseCharge._scrivi fallita (ISOLATA)", exc_info=True)

    def registra(self, fornitore: str, imponibile_cents: int, data_fattura: str, *,
                 servizio: bool = True) -> Optional[Dict[str, Any]]:
        af = calcola_autofattura(imponibile_cents, data_fattura, servizio=servizio,
                                 cfg=self._cfg)
        if af is None:
            return None
        af["fornitore"] = str(fornitore)
        af["data_fattura"] = str(data_fattura)
        lista = self._leggi()
        lista.append(af)
        self._scrivi(lista)
        return af

    def iva_da_versare_cents(self, scadenza_f24_data: str) -> int:
        """Totale IVA da versare con una data scadenza F24 (per il modello F24)."""
        return sum(int(x.get("iva_cents", 0)) for x in self._leggi()
                   if x.get("scadenza_f24") == scadenza_f24_data)


def crea_registro_reverse_charge(percorso: str = "", *,
                                 cfg: ConfigReverseCharge = ConfigReverseCharge()
                                 ) -> RegistroReverseCharge:
    return RegistroReverseCharge(percorso, cfg)
