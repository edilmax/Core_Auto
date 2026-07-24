"""
CORE_AUTO - Fase 196: Generazione VIDEO con AI GRATIS (dormiente, gated). Per la crescita autonoma.

Due strumenti, tutti stdlib (solo HTTP) + `fetch`/pool INIETTABILI (test senza rete/chiavi):
  - VIDEO CORTO (reel): HuggingFace Inference text-to-video (free tier) -> BYTES video, pronti per
    l'upload YouTube (fase165) o social. GATED da HF_TOKEN (senza -> None). Isolato (errore->None;
    429/model-loading -> None: il chiamante riprova piu' tardi).
  - VIDEO LUNGO (tour narrato): STORYBOARD generato dal pool AI gia' esistente — script + N scene,
    ognuna con narrazione (testo-AI: Groq/Gemini) e un'immagine (Pollinations, GRATIS senza chiave).
    Ritorna un piano strutturato pronto per un renderer/TTS (nessun ffmpeg in produzione: la
    macchina genera il CONTENUTO gratis, l'assemblaggio lo fa un renderer esterno/worker).

NB: la generazione video AI davvero-gratis e' scarsa/lenta (HF free tier a code); qui si mettono
i BINARI pronti, si accendono col token, e restano dormienti a costo zero finche' non servono.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from fase165_adattatori_esterni import _fetch_reale, _norm

logger = logging.getLogger("core_auto.video_ai")

_Fetch = Callable[..., Tuple[int, Any]]


class AdattatoreVideoCortoHF:
    """Video CORTO via HuggingFace Inference (text-to-video). GRATIS (free tier). GATED da HF_TOKEN.
    Ritorna i BYTES del video (mp4/webm) o None. Isolato: qualunque errore -> None."""
    BASE = "https://api-inference.huggingface.co/models/"

    def __init__(self, hf_token: str, *, modello: str = "ali-vilab/text-to-video-ms-1.7b",
                 fetch: Optional[_Fetch] = None) -> None:
        self._tok = hf_token or ""
        self._modello = modello or "ali-vilab/text-to-video-ms-1.7b"
        self._fetch = fetch or _fetch_reale

    def _configurato(self) -> bool:
        return bool(self._tok)

    def genera_video(self, richiesta: Any) -> Optional[bytes]:
        if not self._configurato():
            return None
        prompt, _, _ = _norm(richiesta)
        if not prompt:
            return None
        try:
            import json as _j
            corpo = _j.dumps({"inputs": prompt[:500]}).encode("utf-8")
            st, obj = self._fetch(self.BASE + self._modello, metodo="POST", corpo=corpo,
                                  intestazioni={"Authorization": "Bearer " + self._tok,
                                                "Content-Type": "application/json"})
            if st == 200 and isinstance(obj, (bytes, bytearray)) and obj:
                return bytes(obj)                 # binario video pronto
            # 503 = modello in caricamento, 429 = coda/quota: nessun video ORA (si riprova dopo)
            return None
        except Exception:
            logger.warning("HF video corto fallito (ISOLATO)", exc_info=True)
            return None


class GeneratoreStoryboard:
    """VIDEO LUNGO (tour narrato) come STORYBOARD: script + scene (narrazione + immagine). Usa i
    pool AI gia' esistenti (testo: Groq/Gemini; immagine: Pollinations GRATIS). Nessun binario:
    ritorna il PIANO, pronto per TTS + renderer esterno. Robusto: se il testo-AI non c'e', usa un
    ripiego deterministico dai dati dell'annuncio (mai vuoto)."""

    def __init__(self, pool_testo: Any = None, pool_immagine: Any = None) -> None:
        self._testo = pool_testo
        self._img = pool_immagine

    def _genera_testo(self, prompt: str) -> Optional[str]:
        try:
            if self._testo is None:
                return None
            r = self._testo.genera(prompt)
            return (r.get("risultato") if isinstance(r, dict) else r) or None
        except Exception:
            return None

    def _immagine(self, prompt: str) -> Optional[str]:
        try:
            if self._img is None:
                return None
            r = self._img.genera(prompt)
            return (r.get("risultato") if isinstance(r, dict) else r) or None
        except Exception:
            return None

    def genera(self, *, titolo: str, citta: str = "", punti: Optional[List[str]] = None,
               lingua: str = "it", n_scene: int = 5) -> Dict[str, Any]:
        titolo = str(titolo or "Alloggio")[:120]
        punti = [str(p) for p in (punti or []) if str(p).strip()][:12]
        n = max(3, min(10, int(n_scene) if isinstance(n_scene, int) else 5))
        scene: List[Dict[str, Any]] = []
        for i in range(n):
            tema = punti[i] if i < len(punti) else (
                {0: "esterno e vista", 1: "soggiorno", 2: "camera",
                 3: "cucina", 4: "dintorni e attrazioni"}.get(i, "dettagli"))
            narr = self._genera_testo(
                "Scrivi 1-2 frasi in %s, calde e concrete, per la scena '%s' di un tour video "
                "dell'alloggio '%s'%s. Solo la frase." % (lingua, tema, titolo,
                                                          (" a " + citta) if citta else ""))
            if not narr:
                narr = "%s — %s." % (titolo, tema)     # ripiego deterministico, mai vuoto
            img = self._immagine("%s, %s, %s, fotografia realistica, luce naturale"
                                 % (titolo, tema, citta)) or ""
            scene.append({"n": i + 1, "tema": tema, "narrazione": narr.strip()[:280],
                          "immagine_url": img})
        return {"titolo": titolo, "citta": citta, "lingua": lingua,
                "scene": scene, "durata_stimata_sec": len(scene) * 6,
                "pronto_per": "TTS + renderer (assemblaggio esterno)"}


def crea_video_ai_da_env(env: Optional[Dict[str, str]] = None, *, fetch: Any = None,
                         pool_testo: Any = None, pool_immagine: Any = None) -> Dict[str, Any]:
    """Costruisce gli strumenti video: 'corto' (HF, gated) + 'storyboard' (sempre disponibile
    usando i pool AI iniettati). Dormiente: senza HF_TOKEN il 'corto' e' None."""
    import os
    e = env if env is not None else os.environ
    corto = None
    if e.get("HF_TOKEN"):
        corto = AdattatoreVideoCortoHF(e["HF_TOKEN"],
                                       modello=e.get("HF_VIDEO_MODELLO",
                                                     "ali-vilab/text-to-video-ms-1.7b"),
                                       fetch=fetch)
    return {"corto": corto, "storyboard": GeneratoreStoryboard(pool_testo, pool_immagine)}
