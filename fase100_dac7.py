"""
CORE_AUTO - Fase 100: DAC7 gate (Modulo 6). GATED EU (attivo=False default), soglie
configurabili (mai hardcoded come verità: l'utente conferma col commercialista).

Soglia legale EU: 30 prenotazioni O 2000€/anno. Gate di sicurezza a 28/1800€: l'annuncio
viene sospeso e i payout bloccati finché l'host non fornisce i dati fiscali (poi inoltrati
a KYC/KYB es. Stripe Express). Contatore durevole per-host (file JSON atomico). BLINDATO.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict

logger = logging.getLogger("core_auto.dac7")


@dataclass(frozen=True)
class ConfigDAC7:
    attivo: bool = False                # gated: default OFF (jurisdiction)
    soglia_pren: int = 30               # soglia legale EU
    soglia_ricavi_cents: int = 200000   # 2000€
    margine_pren: int = 28              # gate di sicurezza
    margine_ricavi_cents: int = 180000  # 1800€


@dataclass(frozen=True)
class ReportDAC7:
    prenotazioni: int
    ricavi_cents: int
    dati_forniti: bool
    deve_segnalare: bool
    gate_attivo: bool
    sospendi_annuncio: bool
    blocca_payout: bool


def valuta_dac7(prenotazioni: int, ricavi_cents: int, dati_forniti: bool,
                cfg: ConfigDAC7 = ConfigDAC7()) -> ReportDAC7:
    p = max(0, int(prenotazioni)) if isinstance(prenotazioni, int) else 0
    r = max(0, int(ricavi_cents)) if isinstance(ricavi_cents, int) else 0
    df = bool(dati_forniti)
    legale = p >= cfg.soglia_pren or r >= cfg.soglia_ricavi_cents
    sicurezza = p >= cfg.margine_pren or r >= cfg.margine_ricavi_cents
    gate = bool(cfg.attivo and sicurezza and not df)
    return ReportDAC7(p, r, df, legale, gate, gate, gate)


class RegistroDAC7:
    """Contatore durevole per-host (file JSON atomico). Isolato: errore -> stato vuoto."""

    def __init__(self, percorso: str = "", cfg: ConfigDAC7 = ConfigDAC7()) -> None:
        self._p = percorso
        self._cfg = cfg
        self._mem: Dict[str, Dict[str, Any]] = {}

    def _leggi(self) -> Dict[str, Dict[str, Any]]:
        if not self._p:
            return self._mem
        try:
            with open(self._p, encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _scrivi(self, d: Dict[str, Dict[str, Any]]) -> None:
        if not self._p:
            self._mem = d
            return
        try:
            dn = os.path.dirname(self._p) or "."
            fd, tmp = tempfile.mkstemp(dir=dn, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(d, f)
                os.replace(tmp, self._p)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
        except Exception:
            logger.warning("RegistroDAC7._scrivi fallita (ISOLATA)", exc_info=True)

    def _rec(self, d: Dict[str, Dict[str, Any]], h: str) -> Dict[str, Any]:
        return d.get(h) or {"pren": 0, "ricavi": 0, "dati": False}

    def registra_prenotazione(self, host_id: str, importo_cents: int) -> None:
        d = self._leggi()
        rec = self._rec(d, str(host_id))
        rec["pren"] = int(rec["pren"]) + 1
        rec["ricavi"] = int(rec["ricavi"]) + max(0, int(importo_cents))
        d[str(host_id)] = rec
        self._scrivi(d)

    def imposta_dati_fiscali(self, host_id: str) -> None:
        d = self._leggi()
        rec = self._rec(d, str(host_id))
        rec["dati"] = True
        d[str(host_id)] = rec
        self._scrivi(d)

    def stato(self, host_id: str) -> ReportDAC7:
        rec = self._rec(self._leggi(), str(host_id))
        return valuta_dac7(rec["pren"], rec["ricavi"], rec["dati"], self._cfg)

    def visibile(self, host_id: str) -> bool:
        return not self.stato(host_id).sospendi_annuncio

    def payout_consentito(self, host_id: str) -> bool:
        return not self.stato(host_id).blocca_payout


def crea_registro_dac7(percorso: str = "", *, cfg: ConfigDAC7 = ConfigDAC7()) -> RegistroDAC7:
    return RegistroDAC7(percorso, cfg)
