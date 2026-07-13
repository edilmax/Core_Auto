"""
CORE_AUTO - Fase 164: Pool AI a rotazione con failover ("una funziona sempre").

Idea del fondatore: molte API AI (testo/immagini/video) sono GRATIS per un tempo/quota
limitati. Le sfruttiamo TUTTE a rotazione: si usa un provider finché regge; quando finisce
la quota o va in errore si passa IN AUTOMATICO al successivo -> il servizio non si ferma
mai e resta gratis. Se uno si riprende (cooldown finito / quota giornaliera azzerata a
mezzanotte UTC) rientra nel giro.

PURO/testabile: i provider sono adapter INIETTATI (`chiama(richiesta)->risultato`); quelli
reali (gated da chiave) si agganciano sopra, stub nei test. Stato DUREVOLE (file JSON
atomico temp+rename) con quote giornaliere + cooldown a backoff; orologio iniettabile.
BLINDATO: non solleva MAI (errore isolato -> si prova il prossimo); pool vuoto -> ok=False;
tutti esauriti -> ok=False con il dettaglio dei tentativi.

Strategie:
  - 'failover' (default, l'idea del fondatore): resta sul provider CORRENTE finché regge,
    poi scala al successivo -> "spreme" una quota gratis prima di passare all'altra.
  - 'round_robin': parte ogni volta dal successivo -> distribuisce il carico.

VINCITRICE DEL BENCHMARK (4 strategie di resilienza):
  V3 'failover sticky + cooldown a backoff + quota giornaliera + stato durevole atomico'.
  Le altre perdono: V1 'solo il primo provider' (si ferma quando finisce la quota);
  V2 'random ad ogni chiamata' (sbatte su provider morti, spreca tentativi);
  V4 'round-robin senza cooldown' (ritenta subito i falliti -> lentezza e rate-limit).
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("core_auto.pool_ai")


class QuotaEsaurita(Exception):
    """Il provider ha finito la quota gratis (giornaliera/trial): cooldown lungo."""


class ErroreProvider(Exception):
    """Errore transitorio del provider (rete/5xx): cooldown breve a backoff."""


def _intero_pos(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


@dataclass
class ProviderAI:
    """Un provider AI aggancabile al pool. `chiama(richiesta)->risultato` (adapter reale
    gated da chiave, stub nei test). `quota_giorno`: max chiamate/giorno (0 = illimitata)."""
    nome: str
    chiama: Callable[[Any], Any]
    quota_giorno: int = 0


class PoolAI:
    def __init__(self, providers: List[ProviderAI], *,
                 percorso_stato: Optional[str] = None, strategia: str = "failover",
                 cooldown_base_sec: int = 300, cooldown_quota_sec: int = 86400,
                 cooldown_max_sec: int = 21600,
                 orologio: Optional[Callable[[], float]] = None) -> None:
        # tiene solo i provider validi (nome + callable) mantenendo l'ordine
        self._prov: List[ProviderAI] = [
            p for p in (providers or [])
            if isinstance(p, ProviderAI) and p.nome and callable(p.chiama)]
        self._strategia = strategia if strategia in ("failover", "round_robin") else "failover"
        self._cd_base = max(1, int(cooldown_base_sec))
        self._cd_quota = max(1, int(cooldown_quota_sec))
        self._cd_max = max(self._cd_base, int(cooldown_max_sec))
        self._path = percorso_stato
        self._now = orologio or time.time
        self._stato = self._carica()

    # ── stato durevole (atomico) ────────────────────────────────────────────
    def _default(self) -> Dict[str, Any]:
        return {"giorno": "", "cursore": 0, "prov": {}}

    def _carica(self) -> Dict[str, Any]:
        if not self._path or not os.path.exists(self._path):
            return self._default()
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                return self._default()
            d.setdefault("giorno", "")
            d.setdefault("cursore", 0)
            d.setdefault("prov", {})
            if not isinstance(d["prov"], dict):
                d["prov"] = {}
            return d
        except Exception:
            logger.warning("pool_ai: stato illeggibile -> riparto pulito", exc_info=True)
            return self._default()

    def _salva(self) -> None:
        if not self._path:
            return
        try:
            d = os.path.dirname(self._path) or "."
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".pool_ai_", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._stato, f, ensure_ascii=False)
                os.replace(tmp, self._path)          # atomico
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
        except Exception:
            logger.warning("pool_ai: salvataggio stato fallito (ISOLATO)", exc_info=True)

    # ── helper stato per-provider ─────────────────────────────────────────────
    def _oggi(self) -> str:
        return datetime.datetime.utcfromtimestamp(self._now()).strftime("%Y-%m-%d")

    def _reset_giornaliero(self) -> None:
        oggi = self._oggi()
        if self._stato.get("giorno") != oggi:
            self._stato["giorno"] = oggi
            for s in self._stato["prov"].values():
                s["usi"] = 0                          # azzera le quote a mezzanotte UTC
        # assicura una riga per ogni provider
        for p in self._prov:
            self._stato["prov"].setdefault(
                p.nome, {"usi": 0, "cooldown_fino": 0, "fallimenti": 0})

    def _disponibile(self, p: ProviderAI, ora: float) -> bool:
        s = self._stato["prov"].get(p.nome, {})
        if ora < s.get("cooldown_fino", 0):
            return False                              # in cooldown
        if _intero_pos(p.quota_giorno) and s.get("usi", 0) >= p.quota_giorno:
            return False                              # quota giornaliera raggiunta
        return True

    def _penalizza(self, nome: str, ora: float, *, quota: bool) -> None:
        s = self._stato["prov"].setdefault(
            nome, {"usi": 0, "cooldown_fino": 0, "fallimenti": 0})
        if quota:
            s["cooldown_fino"] = ora + self._cd_quota   # quota finita: pausa lunga
        else:
            s["fallimenti"] = int(s.get("fallimenti", 0)) + 1
            durata = min(self._cd_max, self._cd_base * (2 ** (s["fallimenti"] - 1)))
            s["cooldown_fino"] = ora + durata           # backoff esponenziale, con tetto

    def _ordine(self) -> List[int]:
        n = len(self._prov)
        cur = int(self._stato.get("cursore", 0)) % n if n else 0
        return [(cur + i) % n for i in range(n)]

    # ── API principale ────────────────────────────────────────────────────────
    def genera(self, richiesta: Any) -> Dict[str, Any]:
        """Prova i provider (secondo la strategia) finché uno risponde. Ritorna
        {ok, provider, risultato, tentati} oppure {ok:False, motivo, tentati}."""
        if not self._prov:
            return {"ok": False, "motivo": "nessun_provider", "tentati": []}
        self._reset_giornaliero()
        ora = self._now()
        tentati: List[str] = []
        risposta: Dict[str, Any] = {"ok": False, "motivo": "tutti_esauriti"}
        for idx in self._ordine():
            p = self._prov[idx]
            if not self._disponibile(p, ora):
                continue
            tentati.append(p.nome)
            try:
                ris = p.chiama(richiesta)
            except QuotaEsaurita:
                self._penalizza(p.nome, ora, quota=True)
                continue
            except Exception:
                logger.warning("pool_ai: provider '%s' errore (ISOLATO) -> prossimo",
                               p.nome, exc_info=True)
                self._penalizza(p.nome, ora, quota=False)
                continue
            if ris is None:                            # adapter senza risultato = fallimento
                self._penalizza(p.nome, ora, quota=False)
                continue
            # SUCCESSO
            s = self._stato["prov"][p.nome]
            s["usi"] = int(s.get("usi", 0)) + 1
            s["fallimenti"] = 0
            # failover: resta su questo (cursore = idx). round_robin: parti dal prossimo.
            self._stato["cursore"] = (idx + 1) % len(self._prov) \
                if self._strategia == "round_robin" else idx
            risposta = {"ok": True, "provider": p.nome, "risultato": ris}
            break
        risposta["tentati"] = tentati
        self._salva()
        return risposta

    def stato(self) -> Dict[str, Any]:
        """Diagnostica (per pannello admin): per ogni provider usi/quota/cooldown residuo."""
        self._reset_giornaliero()
        ora = self._now()
        out = []
        for p in self._prov:
            s = self._stato["prov"].get(p.nome, {})
            cd = max(0, int(s.get("cooldown_fino", 0) - ora))
            out.append({"nome": p.nome, "usi_oggi": int(s.get("usi", 0)),
                        "quota_giorno": p.quota_giorno,
                        "cooldown_residuo_sec": cd,
                        "disponibile": self._disponibile(p, ora)})
        return {"giorno": self._stato.get("giorno", ""), "strategia": self._strategia,
                "provider": out}


def crea_pool_ai(providers: List[ProviderAI], **kw: Any) -> PoolAI:
    return PoolAI(providers, **kw)
