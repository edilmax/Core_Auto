"""
CORE_AUTO - Fase 173: MOTORE SEO AUTONOMO (orchestratore-su-publish del cervello fase171).

"Appena uno pubblica, in automatico lui fa quello che va fatto" (direttiva del fondatore):
a ogni pubblicazione REALE di un annuncio, questo orchestratore:
  1. INGERISCE il dettaglio reale dell'annuncio (fase57.dettaglio: campi + immagini);
  2. ARRICCHISCE col contesto pubblico DISPONIBILE (tassa comunale fase147 oggi; POI/quartiere
     OSM e geocode quando i provider verranno cablati: tutti INIETTABILI e opzionali);
  3. specchia il MARKUP realmente emesso dalla pagina (fase83.jsonld_alloggio) nel ledger;
  4. chiama il CERVELLO fase171 (punteggio + query vincibili + gap azionabili);
  5. NOTIFICA i motori non-Google via IndexNow fase169 (GATED da env, inerte senza chiave);
  6. espone il rapporto all'host (rotta /api/host/seo_report in fase83).

BLINDATO: la valutazione NON deve MAI rompere il flusso di pubblicazione (ogni passo
isolato, errore -> degradazione, mai eccezione verso il chiamante). Nessun dato finto:
lavora SOLO su annunci reali + dati pubblici. Provider iniettabili -> testabile al 100%.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

from fase171_cervello_seo import valuta_annuncio

logger = logging.getLogger("core_auto.motore_seo")


def markup_pagina(dettaglio: Dict[str, Any],
                  recensioni: Optional[Dict[str, Any]] = None) -> List[str]:
    """SPECCHIO di fase83.jsonld_alloggio: quali slot del ledger la pagina alloggio emette
    DAVVERO in JSON-LD. Se la pagina cambia, il test di coerenza (test_fase173) fallisce:
    lo specchio non puo' derivare (lezione bug #33: i finti replicano il contratto REALE)."""
    if not isinstance(dettaglio, dict):
        return []
    emessi = ["prezzo_notte", "capacita", "camere", "bagni"]      # offers/occupancy/rooms/bath
    for cod in (dettaglio.get("servizi") or ()):
        if isinstance(cod, str):
            emessi.append("amenita:" + cod)                        # amenityFeature
    if isinstance(dettaglio.get("lat_micro"), int) and isinstance(
            dettaglio.get("lon_micro"), int):
        emessi.append("coordinate")                                # geo
    if dettaglio.get("immagini"):
        emessi.append("foto")                                      # image[]
    if isinstance(recensioni, dict) and recensioni.get("conteggio", 0) > 0:
        emessi.append("rating_verificato")                         # aggregateRating
    return emessi


def _scheda_da_dettaglio(dettaglio: Dict[str, Any]) -> Dict[str, Any]:
    """Adatta il dettaglio fase57 al contratto del cervello (foto = numero immagini)."""
    s = dict(dettaglio)
    s["foto"] = len(dettaglio.get("immagini") or ())
    return s


class MotoreSEO:
    """Orchestratore puro-di-composizione: tutti i provider sono CALLABLE iniettati e
    opzionali; un provider assente o rotto degrada il contesto, mai il flusso."""

    def __init__(self, *,
                 tassa_regola_fn: Optional[Callable[[str], Any]] = None,
                 poi_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
                 quartiere_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
                 geocode_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
                 recensioni_fn: Optional[Callable[[str], Any]] = None,
                 coorte_fn: Optional[Callable[[str, str], Any]] = None,
                 indexnow: Any = None,
                 cervello: Callable[..., Dict[str, Any]] = valuta_annuncio) -> None:
        self._tassa = tassa_regola_fn
        self._poi = poi_fn
        self._quartiere = quartiere_fn
        self._geocode = geocode_fn
        self._recensioni = recensioni_fn
        self._coorte = coorte_fn
        self._indexnow = indexnow
        self._cervello = cervello

    def _prova(self, fn: Optional[Callable], *argomenti: Any) -> Any:
        if fn is None:
            return None
        try:
            return fn(*argomenti)
        except Exception:
            logger.warning("provider contesto SEO fallito (ISOLATO)", exc_info=True)
            return None

    def contesto(self, dettaglio: Dict[str, Any]) -> Dict[str, Any]:
        """Contesto pubblico dai provider DISPONIBILI. La tassa entra solo se la regola
        e' davvero configurata (una regola tutta-zero = comune non configurato)."""
        ctx: Dict[str, Any] = {}
        regola = self._prova(self._tassa, dettaglio.get("citta") or "")
        if isinstance(regola, dict) and any(
                isinstance(v, int) and not isinstance(v, bool) and v > 0
                for v in regola.values()):
            ctx["comune_tassa"] = regola
        poi = self._prova(self._poi, dettaglio)
        if isinstance(poi, (list, tuple)):
            ctx["poi"] = list(poi)
        quartiere = self._prova(self._quartiere, dettaglio)
        if isinstance(quartiere, str) and quartiere:
            ctx["quartiere"] = quartiere
        geoc = self._prova(self._geocode, dettaglio)
        if (isinstance(geoc, (tuple, list)) and len(geoc) == 2
                and all(isinstance(x, int) for x in geoc)):
            ctx["geocode_micro"] = (geoc[0], geoc[1])
        rec = self._prova(self._recensioni, dettaglio.get("slug") or "")
        if isinstance(rec, dict) and rec.get("conteggio", 0) > 0:
            ctx["reviews"] = {"n": int(rec["conteggio"])}
        return ctx

    def valuta(self, dettaglio: Dict[str, Any]) -> Dict[str, Any]:
        """Rapporto completo del cervello su un annuncio REALE (mai solleva)."""
        try:
            rec = self._prova(self._recensioni, dettaglio.get("slug") or "")
            coorte = self._prova(self._coorte, dettaglio.get("citta") or "",
                                 dettaglio.get("slug") or "")
            return self._cervello(_scheda_da_dettaglio(dettaglio),
                                  self.contesto(dettaglio),
                                  coorte if isinstance(coorte, dict) else None,
                                  markup_pagina(dettaglio, rec if isinstance(rec, dict)
                                                else None))
        except Exception:
            logger.warning("valutazione SEO fallita (ISOLATA)", exc_info=True)
            return {"punteggio": 0, "punteggio_milli": 0, "sotto_punteggi": {},
                    "fatti": [], "query": [], "gap": [], "citazioni_pronte": [],
                    "errore": "valutazione_degradata"}

    def su_pubblicazione(self, dettaglio: Dict[str, Any],
                         base_url: str = "") -> Dict[str, Any]:
        """Il gancio del publish: valuta + ping IndexNow (annuncio + landing citta').
        MAI solleva: un errore qui NON deve toccare la pubblicazione dell'host."""
        try:
            rapporto = self.valuta(dettaglio)
            esito_ping: Dict[str, Any] = {"inviato": False, "motivo": "disattivo"}
            if self._indexnow is not None and getattr(self._indexnow, "attivo", False):
                base = (base_url or "").rstrip("/")
                url = []
                slug = dettaglio.get("slug")
                if base and isinstance(slug, str) and slug:
                    url.append(base + "/alloggio/" + slug)
                citta = dettaglio.get("citta")
                if base and isinstance(citta, str) and citta:
                    from fase97_inbound_seo import slug_citta
                    sc = slug_citta(citta)
                    if sc:
                        url.append(base + "/affitta/" + sc)
                if url:
                    esito_ping = self._indexnow.submit(url)
            logger.info("SEO su publish: slug=%s punteggio=%s indexnow=%s",
                        dettaglio.get("slug"), rapporto.get("punteggio"),
                        esito_ping.get("inviato"))
            return {"valutazione": rapporto, "indexnow": esito_ping}
        except Exception:
            logger.warning("motore SEO su_pubblicazione fallito (ISOLATO)", exc_info=True)
            return {"valutazione": {"punteggio": 0, "errore": "degradato"},
                    "indexnow": {"inviato": False, "motivo": "errore"}}


def rapporto_host(rapporto: Dict[str, Any], *, max_query: int = 15) -> Dict[str, Any]:
    """Vista per il PANNELLO host: niente ledger grezzo, solo cio' che l'host puo' usare."""
    query = [{"testo": q["testo"], "lingua": q["lingua"],
              "vincibilita": q["vincibilita"], "bucket": q["bucket"]}
             for q in (rapporto.get("query") or [])[:max_query]]
    gap = [{"azione": g["azione"], "tipo": g["tipo"],
            "punti": g["punti_persi_milli"], "query_sbloccate": g["delta_query"]}
           for g in (rapporto.get("gap") or []) if g.get("tipo") != "sistema"]
    return {"punteggio": rapporto.get("punteggio", 0),
            "sotto_punteggi": rapporto.get("sotto_punteggi", {}),
            "query_vincibili": query, "cosa_migliorare": gap,
            "citazioni_pronte": len(rapporto.get("citazioni_pronte") or [])}


def crea_motore_da_sistema(sistema: Any) -> MotoreSEO:
    """Factory dal composition-root: cabla i provider GIA' esistenti nel sistema
    (tassa fase147, IndexNow fase169 da env). POI/quartiere/geocode arriveranno coi
    rispettivi provider; il cervello e' fair anche senza (MAXREF per-posizione)."""
    tassa = getattr(sistema, "tassa_comunale", None)
    tassa_fn = (lambda comune: tassa.regola(comune)) if tassa is not None else None
    # provider POI (fase175): arricchisce il geo del cervello coi luoghi notevoli vicini.
    # Presente solo se il sistema lo cabla (con_poi); altrimenti None = cervello fair senza.
    poi = getattr(sistema, "poi_provider", None)
    poi_fn = (lambda dettaglio: poi.vicini(dettaglio)) if poi is not None else None
    try:
        from fase169_indexnow import crea_indexnow
        inow = crea_indexnow()
    except Exception:
        inow = None
    return MotoreSEO(tassa_regola_fn=tassa_fn, poi_fn=poi_fn, indexnow=inow)
