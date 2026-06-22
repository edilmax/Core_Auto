"""
CORE_AUTO - Entrypoint Casa VIP (accensione unica eseguibile).

Mette online la macchina: legge la config dall'ambiente, accende il SistemaCasaVIP
(fase81, che cabla vetrina+inventario+concierge+MCP), e avvia il server HTTP (fase83)
che espone le API e serve il frontend (deploy/index.html, deploy/host.html).

Uso:
    CASAVIP_SEGRETO=<64hex>  HOST_KEY=<chiave>  PORTA=8080  python main_casavip.py

Genera un segreto:  python -c "import secrets; print(secrets.token_hex(32))"
"""
from __future__ import annotations

import logging
import os

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import servi


def _segreto() -> bytes:
    raw = os.environ.get("CASAVIP_SEGRETO", "")
    if raw:
        try:
            b = bytes.fromhex(raw)
            if len(b) >= 16:
                return b
        except ValueError:
            return raw.encode("utf-8")[:64].ljust(16, b"0")
    import secrets
    b = secrets.token_bytes(32)
    logging.warning("CASAVIP_SEGRETO non impostato: uso un segreto EFFIMERO (solo dev)")
    return b


def main() -> None:  # pragma: no cover
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = ConfigCasaVIP(
        abilitato=True,
        segreto_hmac=_segreto(),
        db_catalogo=os.environ.get("DB_CATALOGO", "data/catalogo.db"),
        db_inventario=os.environ.get("DB_INVENTARIO", "data/inventario.db"),
        valuta=os.environ.get("VALUTA", "EUR"),
        con_mcp=True,
        con_sentinel=os.environ.get("SENTINEL", "").lower() in ("1", "true", "yes"),
        cartella_sentinel=os.environ.get("SENTINEL_DIR") or ".",
    )
    for p in (config.db_catalogo, config.db_inventario):
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
    sistema = crea_sistema(config)
    logging.info("Composizione: %s", sistema.report)
    servi(sistema,
          host=os.environ.get("HOST", "127.0.0.1"),
          porta=int(os.environ.get("PORTA", "8080")),
          cartella_statica=os.environ.get("STATIC_DIR", "deploy"),
          host_key=os.environ.get("HOST_KEY") or None)


if __name__ == "__main__":  # pragma: no cover
    main()
