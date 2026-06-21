"""
CORE_AUTO - Fase 69: Trasparenza Commissionale (la matematica che converte l'host).

I colossi nascondono la matematica: l'host non sa quanto perde, il guest non sa quanto
paga di commissione. E' la loro arma (dark pattern). La nostra arma e' l'opposto:
mostrare TUTTO in centesimi, in chiaro. All'host: "Con Booking incassi 8200, con noi
9500: guadagni 1300 in piu'." Al guest: "Alloggio 10000 + nostra commissione 500 +
tassa 600, tutto visibile" (invece del prezzo opaco dell'OTA).

L'INVARIANTE ONESTO (il cuore): il SURPLUS liberato disintermediando l'OTA
  surplus = commissione_OTA - (nostra_commissione + PSP)
si distribuisce ESATTAMENTE tra guadagno-extra-host e risparmio-guest:
  guadagno_extra_host + risparmio_guest == surplus    (sempre, al centesimo)
Niente centesimo sparisce. E' la prova matematica che non c'e' trucco: il valore che
l'OTA tratteneva torna agli unici due che contano, host e guest.

Questo modulo NON muove denaro e NON ricalcola lo split (lo fa fase45): e' il LAYER di
PRESENTAZIONE/CONFRONTO. Compone con fase43 (commissione), fase45 (split a 3 vie),
fase66 (tassa). Denaro: centesimi interi, zero float.

VINCITRICE DEL BENCHMARK (4 modi di comunicare il valore):
  V3 'prospetto completo in centesimi (host netto noi vs OTA + guest paga in chiaro +
  surplus con invariante verificabile)'. Trasparenza totale, deterministica, e
  l'invariante e' una PROVA che il conto torna. Le altre perdono: V1 'nascondere la
  matematica' = nessuna fiducia, zero differenziazione; V2 'solo "5% commissione"' =
  l'host non vede l'impatto in euro; V4 'percentuali float' = drift, sembra impreciso.

SOPRAVVIVENZA TOTALE: calcolo PURO e deterministico; input invalidi -> prospetto a zero
(fail-closed, mai un'eccezione); benchmark OTA configurabile (nessun valore hardcoded
imposto); zero dipendenze.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("core_auto.trasparenza")

MAX_CENTS = 1_000_000_00

# Benchmark commissioni OTA in basis-point (configurabile; default indicativi pubblici).
OTA_BENCHMARK_BPS: Dict[str, int] = {
    "booking": 1800,     # ~15-18%
    "airbnb": 1500,
    "expedia": 2000,     # ~18-25%
    "agoda": 1800,
    "tripadvisor": 1500,
}


def _intero_nn(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _bps(v: Any) -> int:
    return v if (isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 10000) else 0


@dataclass(frozen=True)
class PoliticaConfronto:
    commissione_ota_bps: int = 1800     # quanto trattiene l'OTA
    commissione_nostra_bps: int = 500   # quanto tratteniamo noi (Rana Inversa)
    psp_bps: int = 0                    # fee del payment provider (pass-through esplicito)


@dataclass(frozen=True)
class Confronto:
    prezzo_riferimento_cents: int
    # scenario OTA
    commissione_ota_cents: int
    host_netto_ota_cents: int
    # scenario nostro
    imponibile_nostro_cents: int
    commissione_nostra_cents: int
    psp_cents: int
    host_netto_nostro_cents: int
    # headline
    guadagno_extra_host_cents: int      # quanto l'host incassa in PIU' con noi
    risparmio_guest_cents: int          # sconto passato al guest
    surplus_disintermediazione_cents: int
    # cosa pagano i guest (in chiaro)
    guest_paga_nostro_cents: int
    guest_paga_ota_cents: int
    tassa_soggiorno_cents: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "prezzo_riferimento_cents": self.prezzo_riferimento_cents,
            "scenario_ota": {
                "commissione_cents": self.commissione_ota_cents,
                "host_netto_cents": self.host_netto_ota_cents,
                "guest_paga_cents": self.guest_paga_ota_cents,
            },
            "scenario_nostro": {
                "imponibile_cents": self.imponibile_nostro_cents,
                "commissione_cents": self.commissione_nostra_cents,
                "psp_cents": self.psp_cents,
                "host_netto_cents": self.host_netto_nostro_cents,
                "guest_paga_cents": self.guest_paga_nostro_cents,
            },
            "guadagno_extra_host_cents": self.guadagno_extra_host_cents,
            "risparmio_guest_cents": self.risparmio_guest_cents,
            "surplus_disintermediazione_cents": self.surplus_disintermediazione_cents,
            "tassa_soggiorno_cents": self.tassa_soggiorno_cents,
            "money_unit": "cents_integer",
        }


def confronta(prezzo_riferimento_cents: int, *,
              politica: Optional[PoliticaConfronto] = None,
              sconto_guest_cents: int = 0,
              tassa_soggiorno_cents: int = 0) -> Confronto:
    """Prospetto trasparente noi-vs-OTA. BLINDATO: input invalidi -> prospetto a zero.
    `sconto_guest_cents`: surplus passato al guest (es. dallo split fase45; default 0 ->
    l'host tiene tutto il surplus)."""
    pol = politica or PoliticaConfronto()
    P = prezzo_riferimento_cents
    if not (_intero_nn(P) and 0 < P <= MAX_CENTS):
        return Confronto(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    sconto = sconto_guest_cents if (_intero_nn(sconto_guest_cents)
                                    and sconto_guest_cents <= P) else 0
    tassa = tassa_soggiorno_cents if _intero_nn(tassa_soggiorno_cents) else 0

    # scenario OTA: il guest paga P, l'OTA trattiene la sua commissione su P
    comm_ota = (P * _bps(pol.commissione_ota_bps)) // 10000
    host_netto_ota = P - comm_ota

    # scenario nostro: imponibile = P - sconto al guest
    imponibile = P - sconto
    comm_nostra = (imponibile * _bps(pol.commissione_nostra_bps)) // 10000
    psp = (imponibile * _bps(pol.psp_bps)) // 10000
    host_netto_nostro = imponibile - comm_nostra - psp

    guadagno_extra = host_netto_nostro - host_netto_ota
    surplus = comm_ota - comm_nostra - psp
    # INVARIANTE (per costruzione): guadagno_extra + sconto == surplus

    guest_paga_nostro = imponibile + tassa
    guest_paga_ota = P + tassa

    return Confronto(
        prezzo_riferimento_cents=P,
        commissione_ota_cents=comm_ota, host_netto_ota_cents=host_netto_ota,
        imponibile_nostro_cents=imponibile, commissione_nostra_cents=comm_nostra,
        psp_cents=psp, host_netto_nostro_cents=host_netto_nostro,
        guadagno_extra_host_cents=guadagno_extra, risparmio_guest_cents=sconto,
        surplus_disintermediazione_cents=surplus,
        guest_paga_nostro_cents=guest_paga_nostro, guest_paga_ota_cents=guest_paga_ota,
        tassa_soggiorno_cents=tassa)


def confronta_piattaforma(prezzo_riferimento_cents: int, piattaforma: str, *,
                          commissione_nostra_bps: int = 500,
                          sconto_guest_cents: int = 0,
                          tassa_soggiorno_cents: int = 0) -> Confronto:
    """Confronto usando il benchmark di una piattaforma nota (booking/airbnb/...).
    Piattaforma sconosciuta -> usa il default della PoliticaConfronto."""
    ota_bps = OTA_BENCHMARK_BPS.get(str(piattaforma).strip().lower(),
                                    PoliticaConfronto().commissione_ota_bps)
    return confronta(prezzo_riferimento_cents,
                     politica=PoliticaConfronto(commissione_ota_bps=ota_bps,
                                                commissione_nostra_bps=commissione_nostra_bps),
                     sconto_guest_cents=sconto_guest_cents,
                     tassa_soggiorno_cents=tassa_soggiorno_cents)
