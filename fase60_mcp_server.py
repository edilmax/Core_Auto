"""
CORE_AUTO - Fase 60: MCP Server (Model Context Protocol) per l'hospitality.

PRIMATO DI MERCATO: nessuna piattaforma di prenotazioni espone un server MCP. MCP e'
lo standard (JSON-RPC 2.0) con cui gli AGENTI IA (Claude, Cursor, IDE, desktop app)
scoprono e usano strumenti esterni. Esponendolo, QUALSIASI agente MCP-compatibile si
collega al nostro sistema SENZA integrazione custom, legge i tool auto-descritti
(inputSchema), e prenota. E' acquisizione clienti a costo zero nell'era degli agenti:
loro espongono HTML pieno di dark-pattern (ostile alle macchine), noi un protocollo
macchina pulito e standard.

REGOLA D'ORO ereditata da fase59: il DENARO non si delega MAI all'IA. Il tool
`ottieni_preventivo` restituisce un prezzo FIRMATO HMAC dal CORE; `prenota` esige quel
token: l'agente puo' solo echeggiarlo, ogni manomissione rompe la firma -> rifiuto.
Il server e' un GUSCIO sottile sopra ProtocolloConcierge (fase59) -> nessuna logica di
denaro duplicata, un solo money-path.

VINCITRICE DEL BENCHMARK (4 modi di farsi usare dagli agenti, 10 stress):
  V3 'MCP standard JSON-RPC 2.0 con tool auto-descritti'. Un solo protocollo, e OGNI
  agente MCP si collega senza integrazione per-vendor; gli schemi guidano l'agente.
  Le altre perdono: V1 'scraping HTML' fragile e ostile alle macchine; V2 'JSON API
  ad-hoc' richiede integrazione manuale per ogni agente; V4 'function-calling
  proprietario' e' legato al singolo vendor LLM (MCP e' cross-vendor).

SOPRAVVIVENZA TOTALE: il dispatcher NON solleva MAI (eccezione interna -> errore
JSON-RPC -32603); richieste malformate -> -32600/-32700; metodo ignoto -> -32601; le
notifiche (senza id) non producono risposta. Stateless: nessuno stato di sessione da
potare -> scala cross-worker. Zero dipendenze esterne (solo stdlib + fase59).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("core_auto.mcp")

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "core_auto.hospitality"
SERVER_VERSION = "1.0"

# Codici di errore JSON-RPC 2.0
ERR_PARSE = -32700
ERR_INVALID_REQUEST = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602
ERR_INTERNAL = -32603


# ─────────────────────────────────────────────────────────────────────────────
# Definizione dei tool (auto-descritti per l'agente)
# ─────────────────────────────────────────────────────────────────────────────
def _schema_tools() -> List[Dict[str, Any]]:
    return [
        {
            "name": "cerca_alloggi",
            "description": ("Cerca alloggi/tavoli disponibili. Importi in centesimi "
                            "interi. Ritorna schede machine-clean (niente HTML)."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "citta": {"type": "string"},
                    "prezzo_max_cents": {"type": "integer",
                                         "description": "tetto prezzo in centesimi interi"},
                    "capacita_min": {"type": "integer"},
                    "servizi": {"type": "array", "items": {"type": "string"}},
                    "check_in": {"type": "string", "description": "YYYY-MM-DD"},
                    "check_out": {"type": "string", "description": "YYYY-MM-DD"},
                },
            },
        },
        {
            "name": "ottieni_preventivo",
            "description": ("Preventivo FERMO e FIRMATO dal sistema (HMAC). Il prezzo "
                            "e' deciso dal CORE: l'agente non puo' alterarlo. Ritorna "
                            "quote_token da passare a 'prenota'."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "alloggio_id": {"type": "string"},
                    "check_in": {"type": "string", "description": "YYYY-MM-DD"},
                    "check_out": {"type": "string", "description": "YYYY-MM-DD"},
                    "party": {"type": "integer", "minimum": 1},
                },
                "required": ["alloggio_id", "check_in", "check_out"],
            },
        },
        {
            "name": "prenota",
            "description": ("Conferma la prenotazione passando il quote_token firmato. "
                            "Atomica e idempotente: ripetere lo stesso token non "
                            "prenota due volte."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "quote_token": {"type": "string"},
                    "email": {"type": "string"},
                    "ospite_nome": {"type": "string"},
                    "ospite_telefono": {"type": "string"},
                },
                "required": ["quote_token", "email"],
            },
        },
        {
            "name": "dettaglio_alloggio",
            "description": ("Scheda completa di un alloggio (descrizione, servizi, "
                            "immagini, prezzo in centesimi). Read-only."),
            "inputSchema": {
                "type": "object",
                "properties": {"alloggio_id": {"type": "string"}},
                "required": ["alloggio_id"],
            },
        },
        {
            "name": "lingue",
            "description": "Lingue supportate per localizzare l'offerta. Read-only.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "confronto_ota",
            "description": ("Confronto trasparente noi-vs-OTA in centesimi interi: "
                            "quanto incassa l'host con noi vs Booking/Airbnb/Expedia. "
                            "Read-only, utile per convincere un host."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "prezzo_cents": {"type": "integer", "minimum": 1},
                    "ota": {"type": "string", "description": "booking|airbnb|expedia"},
                },
                "required": ["prezzo_cents"],
            },
        },
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Server MCP (transport-agnostico: processa un messaggio JSON-RPC e ritorna la risposta)
# ─────────────────────────────────────────────────────────────────────────────
class ServerMCP:
    """Guscio MCP sopra ProtocolloConcierge (fase59). `processa(msg)` e' PURO
    (nessun I/O): prende un messaggio JSON-RPC 2.0 (dict) e ritorna il dict di
    risposta, o None per le notifiche. `servi_stdio()` e' il loop reale (lazy)."""

    def __init__(self, protocollo: Any, *, server_name: str = SERVER_NAME,
                 server_version: str = SERVER_VERSION) -> None:
        self._proto = protocollo
        self._name = server_name
        self._version = server_version
        # registro tool: nome -> handler(arguments) -> RispostaConcierge-like
        self._tool: Dict[str, Callable[[Dict[str, Any]], Any]] = {
            "cerca_alloggi": lambda a: self._proto.scopri(a),
            "ottieni_preventivo": lambda a: self._proto.quota(a),
            "prenota": lambda a: self._proto.prenota(a),
            "dettaglio_alloggio": lambda a: self._proto.dettaglio(a),
            "lingue": lambda a: self._proto.lingue(a),
            "confronto_ota": lambda a: self._proto.confronto(a),
        }

    # ── dispatcher JSON-RPC ────────────────────────────────────────────────────
    def processa(self, msg: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return self._errore(None, ERR_INVALID_REQUEST, "richiesta non valida")
        metodo = msg.get("method")
        mid = msg.get("id")
        e_notifica = "id" not in msg
        if not isinstance(metodo, str):
            return None if e_notifica else self._errore(mid, ERR_INVALID_REQUEST,
                                                        "method mancante")
        try:
            if metodo == "initialize":
                return self._risultato(mid, self._initialize())
            if metodo in ("notifications/initialized", "initialized"):
                return None                      # notifica: nessuna risposta
            if metodo == "ping":
                return self._risultato(mid, {})
            if metodo == "tools/list":
                return self._risultato(mid, {"tools": _schema_tools()})
            if metodo == "tools/call":
                return self._tools_call(mid, msg.get("params"))
            if e_notifica:
                return None
            return self._errore(mid, ERR_METHOD_NOT_FOUND, f"metodo ignoto: {metodo}")
        except Exception:
            logger.error("MCP: eccezione ISOLATA nel dispatcher", exc_info=True)
            if e_notifica:
                return None
            return self._errore(mid, ERR_INTERNAL, "errore interno")

    def gestisci_raw(self, raw: Any) -> Optional[str]:
        """Variante stringa->stringa per i transport testuali (stdio/HTTP body)."""
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return json.dumps(self._errore(None, ERR_PARSE, "JSON non valido"))
        risposta = self.processa(msg)
        return None if risposta is None else json.dumps(risposta, ensure_ascii=False)

    def _initialize(self) -> Dict[str, Any]:
        manifest = {}
        try:
            manifest = self._proto.manifest()
        except Exception:
            logger.warning("MCP: manifest concierge non disponibile", exc_info=True)
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": self._name, "version": self._version},
            "instructions": ("Booking agent-discoverable. Denaro in centesimi interi; "
                             "il prezzo e' firmato dal sistema e non e' modificabile "
                             "dall'agente."),
            "_concierge": manifest,
        }

    def _tools_call(self, mid: Any, params: Any) -> Dict[str, Any]:
        if not isinstance(params, dict):
            return self._errore(mid, ERR_INVALID_PARAMS, "params non valido")
        nome = params.get("name")
        argomenti = params.get("arguments", {})
        if not isinstance(argomenti, dict):
            argomenti = {}
        handler = self._tool.get(nome) if isinstance(nome, str) else None
        if handler is None:
            return self._errore(mid, ERR_INVALID_PARAMS, f"tool ignoto: {nome}")
        risposta = handler(argomenti)            # ProtocolloConcierge non solleva mai
        status = int(getattr(risposta, "status", 200))
        corpo = getattr(risposta, "corpo", {}) or {}
        testo = json.dumps(corpo, ensure_ascii=False)
        return self._risultato(mid, {
            "content": [{"type": "text", "text": testo}],
            "structuredContent": corpo,
            "isError": status >= 400,
        })

    # ── helper risposta JSON-RPC ───────────────────────────────────────────────
    @staticmethod
    def _risultato(mid: Any, result: Dict[str, Any]) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    @staticmethod
    def _errore(mid: Any, codice: int, messaggio: str) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": codice, "message": messaggio}}

    # ── transport stdio reale (lazy; non usato nei test) ───────────────────────
    def servi_stdio(self) -> None:                # pragma: no cover
        import sys
        for riga in sys.stdin:
            riga = riga.strip()
            if not riga:
                continue
            out = self.gestisci_raw(riga)
            if out is not None:
                sys.stdout.write(out + "\n")
                sys.stdout.flush()


def crea_server_mcp(protocollo: Any, **kw: Any) -> ServerMCP:
    return ServerMCP(protocollo, **kw)
