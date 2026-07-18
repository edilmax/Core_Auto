"""
CORE_AUTO - Fase 180: BUNKER (super-admin) — autenticazione a 2 fattori + sessione.

Separazione dei privilegi "Bunker & Field": il FIELD (chiave admin) vede e assiste;
il BUNKER decide e distrugge (rimborsi, cancellazioni, integrita' sistema). Per entrare
nel Bunker non basta la chiave admin: serve un SECONDO fattore (TOTP, Google Authenticator)
e si ottiene una SESSIONE firmata a scadenza stretta (15 min) LEGATA ALL'IP.

Tutto in STDLIB (zero dipendenze, come il resto del progetto — niente Flask/pyotp):
  - TOTP RFC 6238 (HMAC-SHA1, 6 cifre, 30s, finestra +-1 per il drift dell'orologio);
  - sessione = token HMAC firmato (riusa FirmaQuote fase59): payload {k, exp, ip, nonce};
  - BREAK-GLASS: se perdi l'authenticator, un codice d'emergenza da env fa entrare LO
    STESSO (loggato in modo CRITICO): mai chiudersi fuori dal proprio sistema dei soldi.

PURO/testabile (orologio iniettabile). Nessuno stato su disco: il segreto TOTP e' in env
(BUNKER_TOTP_SECRET, sul VPS, mai in git), la sessione e' stateless e auto-scadente.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from typing import Any, Callable, Dict, Optional

DURATA_SESSIONE_SEC = 15 * 60      # scadenza stringente (policy fondatore)
_PASSO = 30                        # step TOTP standard (Google Authenticator)
_CIFRE = 6


# ── TOTP (RFC 6238), stdlib pura ────────────────────────────────────────────
def genera_segreto() -> str:
    """Nuovo segreto TOTP base32 (160 bit) da dare UNA volta al super-admin."""
    import os
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def otpauth_uri(segreto: str, *, account: str = "super-admin",
                issuer: str = "BookinVIP") -> str:
    """URI otpauth:// da scansionare con Google Authenticator (o da rendere in QR)."""
    from urllib.parse import quote
    label = quote("%s:%s" % (issuer, account))
    return ("otpauth://totp/%s?secret=%s&issuer=%s&algorithm=SHA1&digits=%d&period=%d"
            % (label, segreto, quote(issuer), _CIFRE, _PASSO))


def _codice_at(segreto: str, contatore: int) -> str:
    key = base64.b32decode(segreto.strip().upper() + "=" * (-len(segreto.strip()) % 8))
    mac = hmac.new(key, struct.pack(">Q", contatore), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    val = struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF
    return str(val % (10 ** _CIFRE)).zfill(_CIFRE)


def verifica_totp(segreto: str, codice: Any, *, ora: Optional[float] = None,
                  finestra: int = 1) -> bool:
    """True se `codice` e' valido ora (con drift +-`finestra` passi da 30s). Confronto
    a tempo costante su ogni candidato -> niente timing oracle."""
    if not (isinstance(segreto, str) and segreto and isinstance(codice, str)):
        return False
    c = codice.strip()
    if len(c) != _CIFRE or not c.isdigit():
        return False
    t = int((ora if ora is not None else time.time()) // _PASSO)
    valido = False
    for d in range(-finestra, finestra + 1):
        try:
            atteso = _codice_at(segreto, t + d)
        except Exception:
            return False
        if hmac.compare_digest(atteso, c):
            valido = True         # NON break: confronto tutti i candidati (tempo costante)
    return valido


class Bunker:
    """Guardiano del super-admin: verifica 2FA e rilascia/valida la sessione blindata."""

    def __init__(self, firma: Any, *, totp_secret: str = "", password: str = "",
                 break_glass: str = "",
                 orologio: Optional[Callable[[], float]] = None) -> None:
        self._firma = firma                  # FirmaQuote (fase59): sign/verify HMAC
        self._totp = (totp_secret or "").strip()
        self._password = (password or "").strip()   # 2° fattore "qualcosa che SAI" (super-admin pw)
        self._break = (break_glass or "").strip()   # codice d'emergenza (loggato CRITICO)
        self._now = orologio or time.time
        self._revocati = {}                  # nonce -> exp: LOGOUT server-side (denylist)

    @property
    def configurato(self) -> bool:
        return bool(self._firma) and bool(self._totp or self._password or self._break)

    def verifica_secondo_fattore(self, codice: Any) -> str:
        """Ritorna il 2° fattore riconosciuto: 'totp' (telefono) | 'password' (super-admin
        pw) | 'break_glass' (emergenza, loggato CRITICO) | '' (fallito). Confronto a tempo
        costante. Onesta': totp = 2FA vera (qualcosa che HAI); password/break_glass = 2°
        segreto (qualcosa che SAI) -> muro doppio, non 2FA piena finche' non usi il telefono."""
        c = codice.strip() if isinstance(codice, str) else ""
        if verifica_totp(self._totp, c, ora=self._now()):
            return "totp"
        if self._password and c and hmac.compare_digest(c, self._password):
            return "password"
        if self._break and c and hmac.compare_digest(c, self._break):
            return "break_glass"
        return ""

    def crea_sessione(self, ip: str) -> Optional[str]:
        """Token di sessione firmato, auto-scadente (15 min), LEGATO all'IP."""
        if self._firma is None:
            return None
        ora = int(self._now())
        payload = {"k": "bunker", "exp": ora + DURATA_SESSIONE_SEC,
                   "ip": str(ip or ""), "iat": ora,
                   "nonce": hashlib.sha256(("%s|%d" % (ip, ora)).encode()).hexdigest()[:16]}
        try:
            return self._firma.codifica(payload)
        except Exception:
            return None

    def valida_sessione(self, token: Any, ip: str) -> Dict[str, Any]:
        """{'ok':bool, 'motivo':...}. Sessione valida = firma intatta + k=='bunker' +
        non scaduta + IP COINCIDENTE (un token rubato e riusato da un altro IP e' negato)."""
        if self._firma is None:
            return {"ok": False, "motivo": "bunker_non_configurato"}
        dati = self._firma.decodifica(token) if token else None
        if not isinstance(dati, dict) or dati.get("k") != "bunker":
            return {"ok": False, "motivo": "sessione_assente_o_manomessa"}
        if int(dati.get("exp", 0)) <= int(self._now()):
            return {"ok": False, "motivo": "sessione_scaduta"}
        if str(dati.get("ip", "")) != str(ip or ""):
            return {"ok": False, "motivo": "ip_non_coincidente"}
        if dati.get("nonce") in self._revocati:      # LOGOUT server-side: sessione revocata
            return {"ok": False, "motivo": "sessione_revocata"}
        return {"ok": True, "iat": dati.get("iat"), "exp": dati.get("exp")}

    def revoca(self, token: Any) -> bool:
        """LOGOUT SERVER-SIDE: mette il nonce della sessione nella denylist -> quel token
        NON e' piu' valido, subito, su ogni worker (non solo cancellato dal browser). La
        denylist si auto-pulisce (i nonce scaduti si buttano: la sessione dura 15 min)."""
        if self._firma is None:
            return False
        dati = self._firma.decodifica(token) if token else None
        if not isinstance(dati, dict) or dati.get("k") != "bunker" or not dati.get("nonce"):
            return False
        ora = int(self._now())
        # housekeeping: via i revocati gia' scaduti
        for n in [n for n, e in self._revocati.items() if e <= ora]:
            self._revocati.pop(n, None)
        self._revocati[dati["nonce"]] = int(dati.get("exp", ora + DURATA_SESSIONE_SEC))
        return True


def crea_bunker(firma: Any, *, totp_secret: str = "", password: str = "",
                break_glass: str = "", orologio: Any = None) -> Bunker:
    return Bunker(firma, totp_secret=totp_secret, password=password,
                  break_glass=break_glass, orologio=orologio)


if __name__ == "__main__":   # pragma: no cover — helper di enrollment per il fondatore
    import sys
    seg = sys.argv[1] if len(sys.argv) > 1 else genera_segreto()
    print("BUNKER_TOTP_SECRET=%s" % seg)
    print("Scansiona questo con Google Authenticator:")
    print(otpauth_uri(seg))
