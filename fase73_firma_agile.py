"""
CORE_AUTO - Fase 73: Firma Agile (crypto-agility + anti-downgrade + firma ibrida).

Il "protocollo eterno": le firme (quote fase59, recensioni fase63, smart-pass fase64)
oggi usano HMAC-SHA256. Onesta' tecnica: HMAC-SHA256 e' GIA' resistente al quantum
(simmetrico; Grover lo dimezza a ~128 bit, sicuro). Quindi NON serve correre dietro al
"post-quantum" per l'HMAC. Il valore reale e concreto, costruibile e testabile OGGI, e':

  1. CRYPTO-AGILITY: l'algoritmo di firma e' un PARAMETRO, non un hardcode. Si aggiunge
     un nuovo schema (es. uno asimmetrico, per far verificare gli agenti TERZI senza dar
     loro il nostro segreto; o un ML-DSA quando servira') registrandolo, SENZA rompere il
     protocollo. Ogni token porta il tag dell'algoritmo: `b64payload.alg:sig[+alg2:sig2]`.
  2. ANTI-DOWNGRADE / ALGORITHM-CONFUSION: la falla classica (JWT `alg:none`, o forzare
     un algoritmo piu' debole). Il verificatore accetta SOLO algoritmi nella allowlist e
     pretende che TUTTI i `richiesti` siano presenti e validi -> un token degradato e'
     rifiutato.
  3. FIRMA IBRIDA multi-algoritmo: un token puo' portare PIU' firme (es. hmac + uno
     schema futuro) che devono verificare TUTTE -> defense-in-depth durante una
     transizione (raccomandazione NIST).

VINCITRICE DEL BENCHMARK (4 modi di firmare a prova di futuro):
  V3 'algoritmo taggato + allowlist + richiesti + multi-firma'. Agile (swap senza
  rotture), sicuro (no downgrade/confusion), ibrido (transizione graduale). Le altre
  perdono: V1 'HMAC hardcoded' = nessuna agilita', nessuna firma asimmetrica per terzi;
  V2 'alg nel token senza allowlist' = vulnerabile a confusion/`alg:none`; V4 'rotazione
  big-bang' = rompe i token vecchi e i verificatori non aggiornati.

SOPRAVVIVENZA TOTALE: decodifica BLINDATA che non solleva mai (alg ignoto/none/duplicato/
firma errata/payload manomesso -> None); algoritmi duck-typed e ISOLATI (un verifier che
solleva -> rifiuto, non crash); deterministica. Zero dipendenze (HMAC da stdlib; schemi
aggiuntivi iniettabili).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("core_auto.firma_agile")


# ─────────────────────────────────────────────────────────────────────────────
# Interfaccia algoritmo (duck-typed): nome / firma(bytes)->str / verifica(bytes,str)->bool
# ─────────────────────────────────────────────────────────────────────────────
class AlgoritmoHMAC:
    """HMAC-SHA256 (stdlib). Algoritmo di default, simmetrico, gia' quantum-resistant."""

    def __init__(self, segreto: bytes, nome: str = "hmac-sha256") -> None:
        if not isinstance(segreto, (bytes, bytearray)) or len(segreto) < 16:
            raise ValueError("segreto HMAC troppo corto (>=16 byte)")
        self._segreto = bytes(segreto)
        self.nome = nome

    def firma(self, msg: bytes) -> str:
        return hmac.new(self._segreto, msg, hashlib.sha256).hexdigest()

    def verifica(self, msg: bytes, sig: str) -> bool:
        if not isinstance(sig, str):
            return False
        return hmac.compare_digest(sig, self.firma(msg))


def _valido_nome(nome: Any) -> bool:
    return isinstance(nome, str) and bool(nome) and ":" not in nome and "+" not in nome \
        and "." not in nome


# ─────────────────────────────────────────────────────────────────────────────
# Firma Agile
# ─────────────────────────────────────────────────────────────────────────────
class FirmaAgile:
    """Firma/verifica crypto-agile. `algoritmi`: oggetti con nome/firma/verifica.
    `richiesti`: nomi che DEVONO essere presenti e validi (default = tutti). `consentiti`:
    allowlist accettata in verifica (default = i nomi degli algoritmi forniti)."""

    def __init__(self, algoritmi: Sequence[Any], *,
                 richiesti: Optional[Sequence[str]] = None,
                 consentiti: Optional[Sequence[str]] = None) -> None:
        self._alg: Dict[str, Any] = {}
        for a in algoritmi:
            nome = getattr(a, "nome", None)
            if not _valido_nome(nome):
                raise ValueError(f"algoritmo con nome non valido: {nome!r}")
            self._alg[nome] = a
        if not self._alg:
            raise ValueError("serve almeno un algoritmo")
        self._richiesti = set(richiesti) if richiesti is not None else set(self._alg)
        self._consentiti = set(consentiti) if consentiti is not None else set(self._alg)
        # i richiesti devono essere noti e consentiti
        if not self._richiesti <= set(self._alg) or not self._richiesti <= self._consentiti:
            raise ValueError("richiesti non coerenti con algoritmi/consentiti")

    def codifica(self, dati: Dict[str, Any]) -> str:
        raw = json.dumps(dati, separators=(",", ":"), sort_keys=True).encode("utf-8")
        b64 = base64.urlsafe_b64encode(raw).decode("ascii")
        msg = b64.encode("ascii")
        # firma con TUTTI gli algoritmi configurati, in ordine deterministico
        parti = [f"{nome}:{self._alg[nome].firma(msg)}" for nome in sorted(self._alg)]
        return b64 + "." + "+".join(parti)

    def decodifica(self, token: Any) -> Optional[Dict[str, Any]]:
        """Verifica anti-downgrade e ritorna il payload, o None. NON solleva mai."""
        if not isinstance(token, str) or token.count(".") != 1:
            return None
        b64, algsigs = token.split(".")
        if not b64 or not algsigs:
            return None
        present: Dict[str, str] = {}
        for seg in algsigs.split("+"):
            if seg.count(":") != 1:
                return None
            nome, sig = seg.split(":")
            if not nome or not sig or nome in present:        # vuoto o duplicato
                return None
            present[nome] = sig
        # allowlist: ogni alg presente dev'essere consentito E noto (no confusion/none)
        for nome in present:
            if nome not in self._consentiti or nome not in self._alg:
                return None
        # anti-downgrade: tutti i richiesti devono essere presenti
        if not self._richiesti <= set(present):
            return None
        # verifica OGNI firma presente (isolata)
        msg = b64.encode("ascii")
        for nome, sig in present.items():
            try:
                if not self._alg[nome].verifica(msg, sig):
                    return None
            except Exception:
                logger.warning("verifica algoritmo %s ha sollevato (-> rifiuto)", nome,
                               exc_info=True)
                return None
        try:
            raw = base64.urlsafe_b64decode(b64.encode("ascii"))
            dati = json.loads(raw.decode("utf-8"))
            return dati if isinstance(dati, dict) else None
        except (ValueError, TypeError, json.JSONDecodeError):
            return None

    @property
    def algoritmi(self) -> List[str]:
        return sorted(self._alg)


def firma_solo_hmac(segreto: bytes, nome: str = "hmac-sha256") -> FirmaAgile:
    """Caso comune: una sola firma HMAC (compatibile col ruolo di fase59.FirmaQuote)."""
    return FirmaAgile([AlgoritmoHMAC(segreto, nome)])


def firma_ibrida(segreto: bytes, algoritmo_extra: Any, *,
                 nome_hmac: str = "hmac-sha256") -> FirmaAgile:
    """Ibrida: HMAC + un secondo algoritmo (es. asimmetrico/PQC iniettato), entrambi
    RICHIESTI -> defense-in-depth durante la transizione."""
    return FirmaAgile([AlgoritmoHMAC(segreto, nome_hmac), algoritmo_extra])
