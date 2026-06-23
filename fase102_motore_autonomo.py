"""
CORE_AUTO - Fase 102: Motore autonomo vendi+incassa (Regola 3).

Orchestratore che unisce concierge (59, prezzo firmato) + inventario realtime (58, blocco
atomico via prenota) + Stripe Connect split-all'origine (101) + split di gruppo opzionale
(65). Una richiesta (anche dall'agente IA social) → preventivo → prenotazione → link di
pagamento con split. Tutto iniettato/duck-typed → test senza rete. ISOLATO: errore → ok=False.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger("core_auto.motore_autonomo")


class MotoreVendita:
    def __init__(self, concierge: Any, *, pagamento: Any = None,
                 risolvi_account: Optional[Callable[[str], Optional[str]]] = None,
                 split_fn: Optional[Callable[[int, Sequence[str]], Any]] = None) -> None:
        self._c = concierge
        self._pay = pagamento
        self._acct = risolvi_account
        self._split = split_fn

    def vendi(self, richiesta: Dict[str, Any], email: str, *,
              partecipanti: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        try:
            q = self._c.quota(richiesta)
            if getattr(q, "status", 0) != 200:
                return {"ok": False, "fase": "quota", "errore": getattr(q, "corpo", None)}
            qc = q.corpo
            token = qc["quote_token"]
            b = self._c.prenota({"quote_token": token, "email": email})
            if getattr(b, "status", 0) != 200:
                return {"ok": False, "fase": "prenota", "errore": getattr(b, "corpo", None)}
            out: Dict[str, Any] = {
                "ok": True, "quote_token": token, "prenotazione": b.corpo,
                "prezzo_guest_cents": qc["prezzo_guest_cents"],
                "commissione_cents": qc["commissione_cents"],
                "payment_url": None, "split_gruppo": None,
            }
            if self._pay is not None:
                acct = self._acct(richiesta.get("alloggio_id")) if self._acct else None
                if acct:
                    out["payment_url"] = self._pay.crea_link({
                        "prezzo_guest_cents": qc["prezzo_guest_cents"],
                        "commissione_cents": qc["commissione_cents"],
                        "host_account": acct, "valuta": qc.get("valuta", "eur"),
                        "riferimento": token[:16]})
            if partecipanti and self._split is not None:
                try:
                    out["split_gruppo"] = self._split(qc["prezzo_guest_cents"],
                                                      list(partecipanti))
                except Exception:
                    logger.warning("split gruppo fallito (ISOLATO)", exc_info=True)
            return out
        except Exception:
            logger.error("vendi: eccezione ISOLATA", exc_info=True)
            return {"ok": False, "fase": "interno", "errore": "service_unavailable"}


def crea_motore_vendita(concierge: Any, *, pagamento: Any = None,
                        risolvi_account: Any = None,
                        split_fn: Any = None) -> MotoreVendita:
    return MotoreVendita(concierge, pagamento=pagamento,
                         risolvi_account=risolvi_account, split_fn=split_fn)
