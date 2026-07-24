"""
CORE_AUTO - Fase 191: KILL-SWITCH GLOBALE d'emergenza (freeze dei movimenti di denaro).

Un UNICO interruttore che CONGELA all'istante tutti i movimenti di denaro — nuove prenotazioni
(`_book`), rimborsi (`_admin_rimborso`), bonifici all'host (`_trasferisci_all_host`), addebiti
carta (penale) — lasciando il sito NAVIGABILE (ricerca, pagine, letture). Nasce come assicurazione:
davanti a un incidente (bug che muove soldi sbagliati, sospetto di frode, gateway impazzito) si
ferma TUTTO con un gesto, poi si indaga con calma.

DORMIENTE di default: senza attivazione non ha alcun effetto. Due leve, indipendenti:
  · ENV `BLOCCO_GLOBALE=1`  → blocco a LIVELLO SERVER, autorevole, non spegnibile a caldo
    (sopravvive a tutto; si toglie solo cambiando la env e riavviando). E' la rete di sicurezza.
  · FILE-FLAG (toggle a CALDO dal super-admin/bunker) → blocco a runtime SENZA riavvio, con
    motivo + chi + quando registrati nel file (per l'audit). Si accende/spegne dal pannello.

Attivo = env OPPURE file. FAIL-OPEN sul file: se il flag non e' leggibile (glitch FS transitorio)
NON si blocca — meglio non congelare l'attivita' per un errore passeggero; la env resta comunque
autorevole e non dipende dal file. Stdlib puro, isolato (mai solleva), idempotente.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Dict, Optional


class BloccoGlobale:
    def __init__(self, percorso_flag: str, *, env_var: str = "BLOCCO_GLOBALE",
                 orologio: Optional[Callable[[], int]] = None) -> None:
        self._path = percorso_flag
        self._env = env_var
        self._now = orologio or (lambda: int(time.time()))

    def _env_on(self) -> bool:
        return os.environ.get(self._env, "0") == "1"

    def _file_on(self) -> bool:
        try:
            return bool(self._path) and os.path.exists(self._path)
        except Exception:
            return False          # FAIL-OPEN: un glitch FS non deve congelare i soldi

    def attivo(self) -> bool:
        """True se il freeze e' in vigore (env autorevole OPPURE flag a runtime)."""
        return self._env_on() or self._file_on()

    def imposta(self, attivo: Any, *, motivo: str = "", chi: str = "") -> bool:
        """Accende/spegne il flag a runtime (file). L'ENV non si tocca da qui (autorevole).
        Idempotente. Isolato: qualunque errore -> False, stato invariato."""
        try:
            if attivo:
                tmp = self._path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"attivo": True, "motivo": str(motivo)[:200],
                               "chi": str(chi)[:60], "ts": int(self._now())}, f)
                os.replace(tmp, self._path)            # scrittura atomica
            elif self._path and os.path.exists(self._path):
                os.remove(self._path)
            return True
        except Exception:
            return False

    def stato(self) -> Dict[str, Any]:
        """READ-ONLY: com'e' messo l'interruttore (per il pannello super-admin e le sonde)."""
        info = None
        try:
            if self._path and os.path.exists(self._path):
                with open(self._path, encoding="utf-8") as f:
                    info = json.load(f)
        except Exception:
            info = None
        return {"attivo": self.attivo(), "env": self._env_on(),
                "runtime": bool(info), "dettaglio": info}


def crea_blocco_globale(percorso_flag: str, *, env_var: str = "BLOCCO_GLOBALE",
                        orologio: Any = None) -> BloccoGlobale:
    return BloccoGlobale(percorso_flag, env_var=env_var, orologio=orologio)
