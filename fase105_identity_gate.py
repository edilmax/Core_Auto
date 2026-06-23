"""
CORE_AUTO - Fase 105: W3C Identity Gate (Verifiable Credentials firmate, GRATIS).

Firma crittograficamente (HMAC, riusa fase59.FirmaQuote — zero costo, zero dipendenze) gli
ANNUNCI host e le RECENSIONI guest in formato stile W3C Verifiable Credential. Un annuncio o
una recensione è "fidato" solo se porta una VC valida: qualsiasi manomissione rompe la firma
→ truffe azzerate (annunci falsi/clonati e recensioni-fake non verificate vengono rifiutati).
PURO/deterministico, orologio iniettabile (scadenza), BLINDATO (input invalido → None/False).
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Callable, Dict, Optional

from fase59_concierge import FirmaQuote

CONTEXT = "https://www.w3.org/2018/credentials/v1"
TIPO_ANNUNCIO = "AnnuncioHostCredential"
TIPO_RECENSIONE = "RecensioneGuestCredential"


def _hash(*parti: Any) -> str:
    h = hashlib.sha256()
    for p in parti:
        h.update(("%s|" % ("" if p is None else p)).encode("utf-8"))
    return h.hexdigest()


class GateIdentita:
    """Emette e verifica Verifiable Credential firmate per annunci e recensioni."""

    def __init__(self, segreto: bytes, *, ttl_sec: int = 31536000,
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._firma = FirmaQuote(segreto)
        self._ttl = max(60, int(ttl_sec))
        self._now = orologio or (lambda: int(time.time()))

    def _emetti(self, tipo: str, subject: Dict[str, Any]) -> str:
        vc = {"@context": CONTEXT, "type": ["VerifiableCredential", tipo],
              "issuer": "did:bookinvip", "iat": self._now(),
              "exp": self._now() + self._ttl, "credentialSubject": subject}
        return self._firma.codifica(vc)

    def _verifica(self, tipo: str, token: Any) -> Optional[Dict[str, Any]]:
        vc = self._firma.decodifica(token) if isinstance(token, str) else None
        if not isinstance(vc, dict):
            return None
        if not (isinstance(vc.get("type"), list) and tipo in vc["type"]):
            return None
        exp = vc.get("exp")
        if not isinstance(exp, int) or exp < self._now():
            return None
        sub = vc.get("credentialSubject")
        return sub if isinstance(sub, dict) else None

    # ── Annuncio host ────────────────────────────────────────────────────────
    def emetti_annuncio(self, host_id: str, slug: str, titolo: str,
                        citta: str) -> Optional[str]:
        if not (host_id and slug):
            return None
        return self._emetti(TIPO_ANNUNCIO, {
            "host_id": str(host_id), "slug": str(slug),
            "hash": _hash(host_id, slug, titolo, citta)})

    def verifica_annuncio(self, token: Any, *, slug: str, titolo: str,
                          citta: str) -> bool:
        sub = self._verifica(TIPO_ANNUNCIO, token)
        if sub is None or sub.get("slug") != str(slug):
            return False
        return sub.get("hash") == _hash(sub.get("host_id"), slug, titolo, citta)

    # ── Recensione guest (proof-of-stay) ─────────────────────────────────────
    def emetti_recensione(self, prenotazione_id: str, alloggio_slug: str,
                          voto: int, testo: str) -> Optional[str]:
        if not (prenotazione_id and isinstance(voto, int) and 1 <= voto <= 5):
            return None
        return self._emetti(TIPO_RECENSIONE, {
            "prenotazione_id": str(prenotazione_id), "slug": str(alloggio_slug),
            "voto": voto, "hash": _hash(prenotazione_id, alloggio_slug, voto, testo)})

    def verifica_recensione(self, token: Any, *, prenotazione_id: str,
                            alloggio_slug: str, voto: int, testo: str) -> bool:
        sub = self._verifica(TIPO_RECENSIONE, token)
        if sub is None or sub.get("prenotazione_id") != str(prenotazione_id):
            return False
        return sub.get("hash") == _hash(prenotazione_id, alloggio_slug, voto, testo)


def crea_gate_identita(segreto: bytes, *, ttl_sec: int = 31536000,
                       orologio: Any = None) -> GateIdentita:
    return GateIdentita(segreto, ttl_sec=ttl_sec, orologio=orologio)
