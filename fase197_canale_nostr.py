"""
CORE_AUTO - Fase 197: Canale NOSTR (adapter di pubblicazione, gated da .env). GRATIS, ZERO-ACCOUNT.

Nostr e' un protocollo social DECENTRALIZZATO: nessun account da registrare, nessuna azienda che
ti puo' bannare — l'identita' e' una COPPIA DI CHIAVI che ci si genera da soli. Si pubblica una
"nota" (evento kind=1) FIRMATA e la si manda ai relay via WebSocket; chiunque segua la nostra
chiave pubblica la vede. Perfetto per la strategia "non dipendere dai colossi".

Due ostacoli, entrambi risolti in STDLIB PURA (il progetto non aggiunge dipendenze):
  1. FIRMA: Nostr usa Schnorr su secp256k1 (BIP340). Implementata qui fedele al riferimento BIP340
     (pubkey_gen/schnorr_sign/schnorr_verify) → validata contro i vettori ufficiali in test.
  2. TRASPORTO: i relay parlano WebSocket. Client WS minimale (RFC 6455) su socket+ssl, SOLO invio
     di un frame di testo mascherato (i client DEVONO mascherare). I/O GATED e BLINDATO.

GATED: senza NOSTR_PRIVATE_KEY (hex 32 byte) + NOSTR_RELAYS -> canale assente. `sender` iniettabile
-> test senza rete. BLINDATO: qualunque errore -> False (mai rompe il flusso marketing).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Callable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from fase90_marketing import CanalePubblicazione, Post

logger = logging.getLogger("core_auto.canale_nostr")

# ── BIP340 Schnorr su secp256k1 (riferimento fedele, dominio pubblico) ──────────────
_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G: Tuple[int, int] = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)

_Punto = Optional[Tuple[int, int]]


def _tagged_hash(tag: str, msg: bytes) -> bytes:
    th = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(th + th + msg).digest()


def _point_add(P1: _Punto, P2: _Punto) -> _Punto:
    if P1 is None:
        return P2
    if P2 is None:
        return P1
    if P1[0] == P2[0] and P1[1] != P2[1]:
        return None
    if P1 == P2:
        lam = (3 * P1[0] * P1[0] * pow(2 * P1[1], _P - 2, _P)) % _P
    else:
        lam = ((P2[1] - P1[1]) * pow(P2[0] - P1[0], _P - 2, _P)) % _P
    x3 = (lam * lam - P1[0] - P2[0]) % _P
    return (x3, (lam * (P1[0] - x3) - P1[1]) % _P)


def _point_mul(P: _Punto, k: int) -> _Punto:
    R: _Punto = None
    for i in range(256):
        if (k >> i) & 1:
            R = _point_add(R, P)
        P = _point_add(P, P)
    return R


def _int_b(x_: int) -> bytes:
    return x_.to_bytes(32, "big")


def _b_int(b: bytes) -> int:
    return int.from_bytes(b, "big")


def _has_even_y(P: _Punto) -> bool:
    return P is not None and P[1] % 2 == 0


def _lift_x(x_: int) -> _Punto:
    if x_ >= _P:
        return None
    y_sq = (pow(x_, 3, _P) + 7) % _P
    y_ = pow(y_sq, (_P + 1) // 4, _P)
    if pow(y_, 2, _P) != y_sq:
        return None
    return (x_, y_ if y_ % 2 == 0 else _P - y_)


def pubkey_xonly(seckey: bytes) -> bytes:
    """Chiave pubblica x-only (32 byte) dalla privata (32 byte). BIP340."""
    d0 = _b_int(seckey)
    if not (1 <= d0 <= _N - 1):
        raise ValueError("seckey fuori range")
    P = _point_mul(_G, d0)
    assert P is not None
    return _int_b(P[0])


def schnorr_sign(msg32: bytes, seckey: bytes, aux_rand: bytes) -> bytes:
    """Firma Schnorr BIP340 su un messaggio di 32 byte. Ritorna 64 byte (R||s)."""
    d0 = _b_int(seckey)
    if not (1 <= d0 <= _N - 1):
        raise ValueError("seckey fuori range")
    P = _point_mul(_G, d0)
    assert P is not None
    d = d0 if _has_even_y(P) else _N - d0
    t = _int_b(d ^ _b_int(_tagged_hash("BIP0340/aux", aux_rand)))
    k0 = _b_int(_tagged_hash("BIP0340/nonce", t + _int_b(P[0]) + msg32)) % _N
    if k0 == 0:
        raise RuntimeError("k0 == 0 (probabilita' trascurabile)")
    R = _point_mul(_G, k0)
    assert R is not None
    k = k0 if _has_even_y(R) else _N - k0
    e = _b_int(_tagged_hash("BIP0340/challenge",
                            _int_b(R[0]) + _int_b(P[0]) + msg32)) % _N
    return _int_b(R[0]) + _int_b((k + e * d) % _N)


def schnorr_verify(msg32: bytes, pubkey: bytes, sig: bytes) -> bool:
    """Verifica BIP340 (usata dai test e come autocontrollo). True se valida."""
    if len(pubkey) != 32 or len(sig) != 64:
        return False
    P = _lift_x(_b_int(pubkey))
    if P is None:
        return False
    r = _b_int(sig[0:32])
    s = _b_int(sig[32:64])
    if r >= _P or s >= _N:
        return False
    e = _b_int(_tagged_hash("BIP0340/challenge", sig[0:32] + pubkey + msg32)) % _N
    R = _point_add(_point_mul(_G, s), _point_mul(P, _N - e))
    return R is not None and _has_even_y(R) and R[0] == r


# ── Evento Nostr (kind=1, nota di testo) ────────────────────────────────────────────
def serializza_evento(pubkey_hex: str, created_at: int, kind: int,
                      tags: Sequence[Sequence[str]], content: str) -> str:
    """Serializzazione CANONICA Nostr per l'id: JSON compatto (niente spazi), UTF-8, dell'array
    [0, pubkey, created_at, kind, tags, content]. `separators` senza spazi = forma canonica."""
    return json.dumps([0, pubkey_hex, int(created_at), int(kind),
                       [list(t) for t in tags], content],
                      separators=(",", ":"), ensure_ascii=False)


def crea_evento_nota(content: str, seckey: bytes, *, created_at: int,
                     tags: Optional[Sequence[Sequence[str]]] = None,
                     aux_rand: Optional[bytes] = None) -> dict:
    """Costruisce un evento Nostr kind=1 FIRMATO: {id, pubkey, created_at, kind, tags, content, sig}.
    id = sha256(serializzazione canonica); sig = schnorr_sign(id, seckey)."""
    tags = list(tags or [])
    pub = pubkey_xonly(seckey)
    pub_hex = pub.hex()
    ser = serializza_evento(pub_hex, created_at, 1, tags, content)
    eid = hashlib.sha256(ser.encode("utf-8")).digest()
    sig = schnorr_sign(eid, seckey, aux_rand if aux_rand is not None else os.urandom(32))
    return {"id": eid.hex(), "pubkey": pub_hex, "created_at": int(created_at),
            "kind": 1, "tags": tags, "content": content, "sig": sig.hex()}


# ── Trasporto: client WebSocket minimale (RFC 6455), solo invio ─────────────────────
def _invia_ws_reale(relay_url: str, messaggio: str) -> bool:  # pragma: no cover
    """Apre una WS verso il relay, invia UN frame di testo mascherato (["EVENT", evento]), chiude.
    Best-effort e BLINDATO: qualunque problema -> False. Nessuna dipendenza esterna."""
    import base64
    import socket
    import ssl
    import struct
    try:
        u = urlsplit(relay_url)
        if u.scheme not in ("ws", "wss") or not u.hostname:
            return False
        porta = u.port or (443 if u.scheme == "wss" else 80)
        percorso = (u.path or "/") + (("?" + u.query) if u.query else "")
        sock = socket.create_connection((u.hostname, porta), timeout=10)
        if u.scheme == "wss":
            ctx = ssl.create_default_context()
            # ⛔ QUESTA RIGA NON RENDE IL CANALE PIU' SICURO: LO RENDE DIMOSTRABILE.
            # `create_default_context()` verifica gia' il certificato e rifiuta i protocolli
            # vecchi, ma CodeQL non puo' dedurlo e apre `py/insecure-protocol` -- l'unico
            # allarme GRAVE del repository, aperto dal 2026-08-14. Una difesa ha due
            # destinatari, il programma e chi sorveglia: la forma riconosciuta si aggiunge
            # ACCANTO a quella vera, mai al posto (sostituirla indebolirebbe).
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            sock = ctx.wrap_socket(sock, server_hostname=u.hostname)
        chiave = base64.b64encode(os.urandom(16)).decode()
        handshake = (
            "GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n"
            % (percorso, u.hostname, chiave))
        sock.sendall(handshake.encode())
        risposta = sock.recv(4096)
        if b" 101" not in risposta.split(b"\r\n", 1)[0]:
            sock.close()
            return False
        payload = messaggio.encode("utf-8")
        frame = bytearray([0x81])                      # FIN + opcode testo
        maschera = os.urandom(4)
        ln = len(payload)
        if ln < 126:
            frame.append(0x80 | ln)
        elif ln < 65536:
            frame.append(0x80 | 126)
            frame += struct.pack(">H", ln)
        else:
            frame.append(0x80 | 127)
            frame += struct.pack(">Q", ln)
        frame += maschera
        frame += bytes(bb ^ maschera[i % 4] for i, bb in enumerate(payload))
        sock.sendall(frame)
        try:                                            # leggo l'OK del relay (best-effort)
            sock.settimeout(5)
            sock.recv(4096)
        except Exception:
            pass
        sock.close()
        return True
    except Exception:
        logger.warning("Nostr invio WS fallito (ISOLATO)", exc_info=True)
        return False


class CanaleNostr(CanalePubblicazione):
    """Pubblica una nota Nostr firmata sui relay configurati. GRATIS, ZERO-ACCOUNT. GATED dalla
    chiave privata. `sender(relay_url, messaggio)->bool` e `clock()->int` iniettabili (test)."""
    nome = "nostr"

    def __init__(self, seckey_hex: str, relays: Sequence[str], *,
                 sender: Optional[Callable[[str, str], bool]] = None,
                 clock: Optional[Callable[[], int]] = None) -> None:
        self._seckey_hex = (seckey_hex or "").strip().lower()
        self._relays: List[str] = [r.strip() for r in (relays or ()) if r and r.strip()]
        self._sender = sender or _invia_ws_reale
        self._clock = clock

    def _seckey(self) -> Optional[bytes]:
        try:
            b = bytes.fromhex(self._seckey_hex)
            return b if len(b) == 32 else None
        except Exception:
            return None

    def _configurato(self) -> bool:
        return self._seckey() is not None and bool(self._relays)

    def _ora(self) -> int:
        if self._clock is not None:
            return int(self._clock())
        import time
        return int(time.time())

    def pubblica(self, post: Post) -> bool:
        if not (self._configurato() and isinstance(post, Post)):
            return False
        try:
            sk = self._seckey()
            assert sk is not None
            testo = post.testo or ""
            if post.link:
                testo = (testo + "\n\n" + post.link).strip()
            if not testo:
                return False
            evento = crea_evento_nota(testo, sk, created_at=self._ora())
            messaggio = json.dumps(["EVENT", evento], separators=(",", ":"),
                                   ensure_ascii=False)
            inviati = 0
            for relay in self._relays:
                try:
                    if self._sender(relay, messaggio):
                        inviati += 1
                except Exception:
                    logger.warning("Nostr relay KO (ISOLATO): %s", relay, exc_info=True)
            return inviati > 0                          # pubblicato se almeno un relay ha accettato
        except Exception:
            logger.warning("Nostr pubblica fallita (ISOLATA)", exc_info=True)
            return False


def crea_canale_nostr_da_env(env: Optional[dict] = None, *,
                             fetch: Any = None) -> Optional[CanaleNostr]:
    """Gated: NOSTR_PRIVATE_KEY (hex 32 byte) + NOSTR_RELAYS (lista separata da virgole) -> canale.
    `fetch` (dal wiring comune fase91) e' usato come `sender` se fornito (test)."""
    e = env if env is not None else os.environ
    sk = (e.get("NOSTR_PRIVATE_KEY") or "").strip()
    relays_raw = (e.get("NOSTR_RELAYS") or "").strip()
    if not sk or not relays_raw:
        return None
    relays = [r.strip() for r in relays_raw.split(",") if r.strip()]
    if not relays:
        return None
    return CanaleNostr(sk, relays, sender=fetch)
