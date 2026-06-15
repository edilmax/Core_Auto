"""
CORE_AUTO - Fase 28 / BLOCCO 2: API Gateway (estensione Blueprint /api/v1).

Punto d'ingresso UNICO che espone il loop dell'agente (social -> cervello ->
offerta) come API protetta: autenticazione PER-CLIENTE, validazione blindata del
payload, traduzione della richiesta in evento interno per l'Agente. Input
malevoli o fuori formato -> errori STANDARDIZZATI, senza MAI far filtrare
eccezioni verso il nucleo.

`valida_messaggio` = **Variante C**, vincitrice di un benchmark a 3 varianti
(naive / .get / blindato) su una batteria ostile: 0 eccezioni trapelate (vs 7 e
4), oversize/DoS rifiutato, malevoli respinti con codice standardizzato.

Isola: il core del gateway (ClientRegistry, validatore, GatewayAgente) NON
dipende da Flask (testabile a sé); la registrazione della route usa import lazy.
"""
from __future__ import annotations

import hmac
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("core_auto.gateway")

LIMITE_TESTO = int(os.environ.get("GATEWAY_MAX_TEXT", "4000"))
LIMITE_CAMPO = int(os.environ.get("GATEWAY_MAX_FIELD", "256"))


@dataclass(frozen=True)
class RichiestaMessaggio:
    channel: str
    recipient: str
    text: str
    localita: str = ""
    budget_max: float = 0.0


@dataclass
class RispostaGateway:
    status: int
    corpo: Dict[str, Any]


class ClientRegistry:
    """Autenticazione per-cliente: api_key -> client_id (confronto timing-safe)."""

    def __init__(self, chiavi: Optional[Dict[str, str]] = None) -> None:
        self._chiavi = dict(chiavi or {})

    @classmethod
    def from_env(cls, var: str = "GATEWAY_CLIENTS") -> "ClientRegistry":
        """Carica da env 'k1:client1,k2:client2'."""
        chiavi: Dict[str, str] = {}
        for coppia in os.environ.get(var, "").split(","):
            coppia = coppia.strip()
            if ":" in coppia:
                k, cid = coppia.split(":", 1)
                if k.strip() and cid.strip():
                    chiavi[k.strip()] = cid.strip()
        return cls(chiavi)

    def autentica(self, api_key: Any) -> Optional[str]:
        """Ritorna il client_id se la chiave e' valida, altrimenti None.
        Scorre TUTTE le chiavi con compare_digest (no early-exit timing leak)."""
        api_key = str(api_key or "")
        trovato: Optional[str] = None
        for k, cid in self._chiavi.items():
            if hmac.compare_digest(api_key, k):
                trovato = cid
        return trovato


def valida_messaggio(data: Any) -> Tuple[bool, str, Optional[RichiestaMessaggio]]:
    """Validatore BLINDATO (Variante C): non solleva MAI, ritorna
    (ok, codice_errore, richiesta). Guardie: payload e' oggetto; campi presenti,
    stringa, non vuoti, entro i limiti; opzionali localita/budget tipizzati."""
    if not isinstance(data, dict):
        return False, "payload_non_oggetto", None
    campi: Dict[str, str] = {}
    for nome in ("channel", "recipient", "text"):
        v = data.get(nome)
        if v is None:
            return False, f"campo_mancante:{nome}", None
        if not isinstance(v, str):
            return False, f"campo_non_stringa:{nome}", None
        v = v.strip()
        if not v:
            return False, f"campo_vuoto:{nome}", None
        limite = LIMITE_TESTO if nome == "text" else LIMITE_CAMPO
        if len(v) > limite:
            return False, f"campo_troppo_lungo:{nome}", None
        campi[nome] = v
    localita = data.get("localita", "")
    if not isinstance(localita, str):
        return False, "localita_non_stringa", None
    budget = data.get("budget_max", 0)
    if isinstance(budget, bool) or not isinstance(budget, (int, float)):
        return False, "budget_non_numerico", None
    if budget < 0:
        return False, "budget_negativo", None
    return True, "", RichiestaMessaggio(
        channel=campi["channel"], recipient=campi["recipient"], text=campi["text"],
        localita=localita.strip()[:LIMITE_CAMPO], budget_max=float(budget))


class GatewayAgente:
    """Orchestratore del gateway: auth -> validazione -> evento interno per
    l'Agente -> risposta standardizzata. `processa` non solleva MAI."""

    def __init__(self, clients: ClientRegistry, agente: Any, motore: Any = None,
                 generatore: Any = None, publisher: Any = None) -> None:
        self._clients = clients
        self._agente = agente
        self._motore = motore
        self._generatore = generatore
        self._publisher = publisher

    def processa(self, api_key: Any, data: Any) -> RispostaGateway:
        client = self._clients.autentica(api_key)
        if client is None:
            return RispostaGateway(401, {"error": "unauthorized"})
        ok, codice, ric = valida_messaggio(data)
        if not ok:
            return RispostaGateway(400, {"error": "invalid_payload", "dettaglio": codice})
        try:
            return RispostaGateway(200, self._gestisci(client, ric))
        except Exception:
            # Cintura di sicurezza finale: nessuna eccezione filtra verso il nucleo.
            logger.error("Gateway: eccezione interna ISOLATA (-> 503)", exc_info=True)
            return RispostaGateway(503, {"error": "service_unavailable"})

    def _gestisci(self, client: str, ric: RichiestaMessaggio) -> Dict[str, Any]:
        from fase25_brain import Intento  # import lazy (isolamento tra moduli)
        intento = self._agente.analizza_intento(ric.text)
        if (intento == Intento.RICERCA_ALLOGGIO
                and self._motore is not None and self._generatore is not None):
            from fase26_ricerca import CriteriRicerca
            from fase27_proposte import componi_offerta
            offerta = componi_offerta(
                self._motore, self._generatore,
                CriteriRicerca(ric.localita, ric.budget_max))
            risposta = offerta.testo
        else:
            risposta = self._agente.genera_risposta(ric.text).testo
        accodato = False
        if self._publisher is not None:
            from fase24_channels import pubblica_messaggio
            pubblica_messaggio(self._publisher, ric.channel, ric.recipient, risposta)
            accodato = True
        return {"client": client, "intento": intento.value,
                "risposta": risposta, "accodato": accodato}


def registra_gateway(target: Any, gateway: GatewayAgente,
                     path: str = "/agent/message") -> None:
    """Registra POST <path> su un Blueprint/app Flask, delegando al gateway.
    Auth per-cliente via header `X-Client-Key`. Body non-JSON -> 400 (validatore)."""
    from flask import request, jsonify

    @target.route(path, methods=["POST"], endpoint="gateway_agent_message")
    def _agent_message() -> Any:
        api_key = request.headers.get("X-Client-Key", "")
        data = request.get_json(silent=True)
        r = gateway.processa(api_key, data)
        return jsonify(r.corpo), r.status
