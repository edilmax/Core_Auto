"""
CORE_AUTO - Fase 87: Webhook Stripe (l'altra meta' del money-path: conferma pagamento).

fase85 crea il link di pagamento; ma come sappiamo che l'ospite HA pagato? Stripe chiama
un WEBHOOK al nostro server. La falla classica (e grave): non verificare la FIRMA del
webhook -> chiunque puo' fingere un "pagamento avvenuto". Questo modulo chiude la falla:
verifica la firma Stripe (HMAC-SHA256, stdlib, zero dipendenze) PRIMA di credere a
qualunque evento. E' GATED dal webhook secret: senza, il sistema non accetta webhook.

Stripe firma cosi': header `Stripe-Signature: t=<ts>,v1=<hmac>` dove hmac =
HMAC-SHA256(secret, "<ts>.<payload_grezzo>"). Verifichiamo ricalcolando e confrontando in
tempo costante (compare_digest), e rifiutiamo i timestamp troppo vecchi (anti-replay).

VINCITRICE DEL BENCHMARK (4 modi di gestire i webhook):
  V3 'verifica firma HMAC + tolleranza timestamp, su payload GREZZO'. Sicuro (no spoof,
  no replay), zero dipendenze. Le altre perdono: V1 'fidarsi del body senza firma' =
  chiunque conferma pagamenti finti; V2 'verifica sul JSON ri-serializzato' = la firma
  non combacia (va verificata sui byte grezzi); V4 'libreria stripe' = dipendenza in piu'.

SOPRAVVIVENZA TOTALE: `verifica_firma_stripe`/`gestisci_webhook` non sollevano MAI
(input invalido -> False/None); compare_digest (no timing leak); orologio iniettabile
(test deterministici). Denaro/azioni reali delegate a valle; qui solo la VERITA' del
"ha pagato".
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Optional, Tuple

logger = logging.getLogger("core_auto.stripe_webhook")


def verifica_firma_stripe(payload: Any, header: Any, secret: Any, *,
                          tolleranza_sec: int = 300,
                          ora: Optional[int] = None) -> bool:
    """Verifica la firma di un webhook Stripe. BLINDATO: non solleva mai, ritorna bool.
    `payload` DEVE essere il body GREZZO (string), non il JSON ri-serializzato."""
    if not (isinstance(payload, str) and isinstance(header, str)
            and isinstance(secret, str) and secret):
        return False
    try:
        parti = {}
        for seg in header.split(","):
            if "=" in seg:
                k, v = seg.split("=", 1)
                parti[k.strip()] = v.strip()
    except Exception:
        return False
    t, v1 = parti.get("t"), parti.get("v1")
    if not (t and v1):
        return False
    try:
        ts = int(t)
    except (ValueError, TypeError):
        return False
    adesso = ora if (isinstance(ora, int) and not isinstance(ora, bool)) else int(time.time())
    if abs(adesso - ts) > max(0, tolleranza_sec):
        return False                                   # anti-replay
    atteso = hmac.new(secret.encode("utf-8"), (t + "." + payload).encode("utf-8"),
                      hashlib.sha256).hexdigest()
    return hmac.compare_digest(v1, atteso)


def gestisci_webhook(payload: Any, header: Any, secret: Any, *,
                     tolleranza_sec: int = 300, ora: Optional[int] = None
                     ) -> Tuple[bool, str, Optional[dict]]:
    """Verifica + parse. Ritorna (firma_ok, tipo_evento, dati). Se firma non valida ->
    (False, '', None) e NESSUN evento viene creduto."""
    if not verifica_firma_stripe(payload, header, secret, tolleranza_sec=tolleranza_sec,
                                 ora=ora):
        return False, "", None
    try:
        ev = json.loads(payload)
    except (ValueError, TypeError):
        return False, "", None
    if not isinstance(ev, dict):
        return False, "", None
    dati = ev.get("data")
    return True, str(ev.get("type", "")), dati if isinstance(dati, dict) else None


def firma_di_test(payload: str, secret: str, ts: int) -> str:
    """Costruisce un header Stripe-Signature valido (per i test / strumenti interni)."""
    mac = hmac.new(secret.encode("utf-8"), (str(ts) + "." + payload).encode("utf-8"),
                   hashlib.sha256).hexdigest()
    return "t=%d,v1=%s" % (ts, mac)
