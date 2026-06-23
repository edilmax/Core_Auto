"""
CORE_AUTO - Fase 99: Multi-Currency Like-for-Like Ledger (Moduli 1-2 dello studio).

Elimina il "segreto valutario" dei colossi (DCC: markup occulto 3-5% sul cambio) con una
contabilità multi-valuta ONESTA:
  - **Denaro tipizzato per valuta** (`Denaro`): importo in UNITÀ MINORI intere (mai float) +
    codice ISO. Le operazioni tra valute DIVERSE sono VIETATE (sollevano) → impossibile
    mischiare USD ed EUR per errore. Esponente corretto per valuta (JPY 0, BHD 3, default 2).
  - **Like-for-Like** (`ripartisci_pagamento`): un alloggio prezzato in USD → ospite paga
    USD, host incassa USD, nostra commissione USD. NESSUNA conversione forzata: zero rischio
    cambio per noi, il costo cambio (se l'ospite usa carta estera) lo gestisce la SUA banca
    (~1-2% Visa/MC) invece del 5% di Agoda. Riusa lo split 3%/12% di fase98.
  - **Conversione TRASPARENTE** (`converti`, anti-DCC): se offriamo il cambio sul sito,
    mostriamo il tasso MID reale (iniettato da una fonte, es. Open Exchange Rates) + un
    markup ESPLICITO e ridotto (default 1%) come NOSTRA fee dichiarata. Niente occulto.

PURO/deterministico: il tasso è iniettato (test senza rete). `ProviderTassi` gated da app_id
(fonte reale opzionale). Aritmetica in interi/Decimal HALF_UP; mai float per il denaro.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Callable, Dict, Optional

import fase98_policy_commissione as policy

# Valute con esponente diverso da 2 (unità minori). Default = 2.
_ESP0 = {"JPY", "KRW", "VND", "CLP", "ISK", "XAF", "XOF", "PYG", "UGX", "RWF",
         "GNF", "KMF", "DJF", "VUV", "XPF", "BIF"}
_ESP3 = {"BHD", "KWD", "OMR", "TND", "JOD", "IQD", "LYD"}


def esponente(valuta: str) -> int:
    """Cifre decimali (unità minori) della valuta. JPY→0, BHD→3, resto→2."""
    v = str(valuta).strip().upper()
    return 0 if v in _ESP0 else 3 if v in _ESP3 else 2


def _valuta_valida(v: Any) -> bool:
    return isinstance(v, str) and len(v.strip()) == 3 and v.strip().isalpha()


@dataclass(frozen=True)
class Denaro:
    """Importo in UNITÀ MINORI intere + valuta ISO. Immutabile, valuta-sicuro."""
    minori: int
    valuta: str

    def __post_init__(self) -> None:
        if isinstance(self.minori, bool) or not isinstance(self.minori, int):
            raise TypeError("minori deve essere int (unità minori), non float")
        if not _valuta_valida(self.valuta):
            raise ValueError("valuta ISO non valida: %r" % (self.valuta,))
        object.__setattr__(self, "valuta", self.valuta.strip().upper())

    def _stessa(self, altro: "Denaro") -> None:
        if not isinstance(altro, Denaro) or altro.valuta != self.valuta:
            raise ValueError("operazione tra valute diverse vietata (%s vs %s)"
                             % (self.valuta, getattr(altro, "valuta", "?")))

    def somma(self, altro: "Denaro") -> "Denaro":
        self._stessa(altro)
        return Denaro(self.minori + altro.minori, self.valuta)

    def sottrai(self, altro: "Denaro") -> "Denaro":
        self._stessa(altro)
        return Denaro(self.minori - altro.minori, self.valuta)

    def scala_bps(self, bps: int) -> "Denaro":
        """Frazione in basis-point (floor, mai negativa). Stessa valuta."""
        return Denaro(policy.commissione_cents(self.minori, bps), self.valuta)

    def maggiore(self) -> Decimal:
        """Importo in unità MAGGIORI (es. euro) come Decimal esatto."""
        return Decimal(self.minori) / (Decimal(10) ** esponente(self.valuta))

    def formatta(self) -> str:
        exp = esponente(self.valuta)
        if exp == 0:
            return "%d %s" % (self.minori, self.valuta)
        s = str(abs(self.minori)).rjust(exp + 1, "0")
        seg = "-" if self.minori < 0 else ""
        return "%s%s.%s %s" % (seg, s[:-exp], s[-exp:], self.valuta)


def denaro_da_maggiore(importo: Any, valuta: str) -> Denaro:
    """Costruisce Denaro da un importo in unità MAGGIORI (stringa/Decimal, es. '100.00').
    HALF_UP all'esponente della valuta. Float rifiutato (precisione)."""
    if isinstance(importo, float):
        raise TypeError("usa stringa/Decimal per il denaro, non float")
    try:
        d = Decimal(str(importo))
    except (InvalidOperation, ValueError):
        raise ValueError("importo non numerico: %r" % (importo,))
    exp = esponente(valuta)
    minori = int((d * (Decimal(10) ** exp)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return Denaro(minori, valuta)


def ripartisci_pagamento(prezzo: Denaro, *, host_bps: int = policy.HOST_BPS,
                         guest_bps: int = policy.GUEST_BPS) -> Dict[str, Denaro]:
    """LIKE-FOR-LIKE: lo split 3%/12% di fase98 applicato NELLA VALUTA dell'annuncio.
    Tutti i Denaro tornano nella stessa valuta del prezzo (nessuna conversione)."""
    if not isinstance(prezzo, Denaro):
        raise TypeError("prezzo deve essere Denaro")
    r = policy.ripartisci_host_guest(prezzo.minori, host_bps=host_bps, guest_bps=guest_bps)
    v = prezzo.valuta
    return {k: Denaro(r[k], v) for k in
            ("prezzo", "host_fee", "guest_fee", "nostra_commissione",
             "netto_host", "totale_ospite")}


def converti(importo: Denaro, valuta_dest: str, tasso_mid: Any, *,
             markup_bps: int = 100) -> Dict[str, Any]:
    """Conversione TRASPARENTE (anti-DCC). `tasso_mid` = unità MAGGIORI di destinazione per
    1 unità MAGGIORE di origine (mid-market reale, iniettato). Applica un markup ESPLICITO
    (default 1%) come nostra fee dichiarata. Ritorna mid, importo cliente e il nostro markup
    — tutto visibile (l'opposto del 3-5% occulto dei colossi)."""
    if not isinstance(importo, Denaro):
        raise TypeError("importo deve essere Denaro")
    if not _valuta_valida(valuta_dest):
        raise ValueError("valuta_dest non valida")
    try:
        tasso = Decimal(str(tasso_mid))
    except (InvalidOperation, ValueError):
        raise ValueError("tasso_mid non numerico")
    if tasso <= 0:
        raise ValueError("tasso_mid deve essere > 0")
    mk = max(0, policy._intero(markup_bps, 0))
    dest = str(valuta_dest).strip().upper()
    exp_d = esponente(dest)
    mid_major = importo.maggiore() * tasso
    cliente_major = mid_major * (Decimal(10000 + mk) / Decimal(10000))
    fattore = Decimal(10) ** exp_d
    mid_minori = int((mid_major * fattore).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    cliente_minori = int((cliente_major * fattore).quantize(Decimal(1),
                                                            rounding=ROUND_HALF_UP))
    mid_d = Denaro(mid_minori, dest)
    cliente_d = Denaro(cliente_minori, dest)
    return {
        "origine": importo,
        "tasso_mid": str(tasso),
        "markup_bps": mk,
        "destinazione_mid": mid_d,            # quanto vale al tasso reale
        "destinazione_cliente": cliente_d,    # quanto paga il cliente (mid + nostro markup)
        "nostro_markup": cliente_d.sottrai(mid_d),   # la NOSTRA fee, esplicita
    }


class ProviderTassi:
    """Tassi mid-market da fonte REALE (Open Exchange Rates free tier). GATED da app_id:
    senza chiave → tasso None. `fetch(url)->dict` iniettabile (test senza rete). Isolato."""
    URL = "https://openexchangerates.org/api/latest.json?app_id=%s"

    def __init__(self, app_id: str, *,
                 fetch: Optional[Callable[[str], Dict[str, Any]]] = None) -> None:
        self._app = app_id or ""
        self._fetch = fetch or self._fetch_reale

    def tasso(self, origine: str, dest: str) -> Optional[Decimal]:
        """Cross-rate dest per 1 origine. OXR free tier ha base USD → si calcola via USD."""
        if not self._app:
            return None
        try:
            data = self._fetch(self.URL % self._app)
            rates = data.get("rates") if isinstance(data, dict) else None
            if not isinstance(rates, dict):
                return None
            o = str(origine).upper()
            d = str(dest).upper()
            ro = Decimal(str(rates[o])) if o != "USD" else Decimal(1)
            rd = Decimal(str(rates[d])) if d != "USD" else Decimal(1)
            if ro <= 0:
                return None
            return rd / ro
        except Exception:
            return None

    def _fetch_reale(self, url: str) -> Dict[str, Any]:  # pragma: no cover
        import json
        import urllib.request
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read())


def crea_provider_tassi(app_id: Optional[str], *, fetch: Any = None) -> ProviderTassi:
    return ProviderTassi(app_id or "", fetch=fetch)
