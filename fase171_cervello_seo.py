"""
CORE_AUTO - Fase 171: CERVELLO SEO/AEO "Fact-Ledger" (registro dei fatti citabili).

VINCITRICE del benchmark a 4 varianti (2026-07-17, fan-out di design + verifica avversariale):
"Fact-Ledger AEO", con 3 innesti dalle rivali:
  - ancora-BITMASK (da "Contesa-Inversa"): un servizio conta SOLO se il suo codice e' nei
    `servizi` STRUTTURATI della scheda (fase57.SERVIZI); citarlo nel testo senza il codice = 0
    (anti-stuffing). + anti-spoof geo: pin manuale che dista >2km dal geocode dell'indirizzo
    -> coordinate declassate e fatti-POI azzerati (lo spoof COSTA punti, non li regala).
  - matematica INTERA per-mille (da "CPGQ"): niente float nel calcolo; invariante ESATTO
    sum(gap.punti_persi_milli) == 100000 - punteggio_milli -> il punteggio e' interamente
    spiegabile, ogni millesimo perso e' attribuito a un gap.
  - onesta' cold-start (da "Query-Lattice"): la vincibilita' e' una PRIORITA' RELATIVA, mai
    una promessa di volume/posizione; nessuna query-testa (ogni query emessa ha >=2 vincoli
    fattuali); con coorte piccola si usano prior CONSERVATIVI.

IDEA: la pagina non e' "testo da rankare" ma un LEDGER di fatti atomici estraibili. Ogni fatto
(prezzo, distanza-da-POI in metri, quartiere, tassa di soggiorno, amenita') e' una potenziale
RISPOSTA a una domanda. Un answer-engine cita chi risponde con un valore specifico e
VERIFICABILE: citabilita' fatto = peso x specificita' x verificabilita' x distintivita' x
presenza x emissione-markup. I pesi piu' alti vanno ai fatti PUBBLICI non falsificabili
(distanza-POI calcolata dalle coordinate, tassa fase147, quartiere dal geocoder fase166):
non si sale mentendo, si sale arricchendo. Punteggio, query vincibili e gap escono dallo
STESSO ledger -> coerenti per costruzione (chiudere un gap muove punteggio E query in modo
esatto e ricalcolabile).

FAIRNESS DI POSIZIONE: il massimo raggiungibile (MAXREF) e' calcolato per LA posizione della
pagina: una zona senza POI/tassa non e' penalizzata (quegli slot non entrano nel massimo).

PURO e DETERMINISTICO: nessun I/O, nessun now()/random; input iniettati (scheda-dict + ctx
pubblico + coorte + markup emesso); iterazioni in ordine fisso; tie-break totali. Denaro
SEMPRE in cents interi. Trigonometria evitata: distanza equirettangolare con tabella coseni
per-mille intera (deterministica byte-a-byte su ogni piattaforma).
"""
from __future__ import annotations

from math import isqrt
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ── classificazione amenita' (tutti e 12 i codici fase57.SERVIZI) ────────────────
AMENITA_ALTA = ("piscina", "vista_mare", "animali_ammessi", "parcheggio",
                "aria_condizionata", "parcheggio_disabili", "cucina")
AMENITA_COMMODITY = ("wifi", "riscaldamento", "lavatrice", "colazione", "check_in_24h")
_AMENITA_TUTTE = AMENITA_ALTA + AMENITA_COMMODITY

POLITICHE_NOTE = ("flessibile", "moderata", "rigida", "non_rimborsabile")

# ── pesi Wcat in DECIPUNTI (x10: commodity=2.5 -> 25) ───────────────────────────
_W10_BASE = {
    "prezzo_notte": 100, "coordinate": 80, "quartiere": 70, "capacita": 60,
    "tassa_soggiorno": 60, "rating_verificato": 60, "politica": 50, "foto": 40,
    "camere": 30, "bagni": 30, "sconti": 30, "narrativa": 30,
    "prenotazione_immediata": 20,
}
_W10_POI = 90
_W10_AMENITA = {c: 50 for c in AMENITA_ALTA}
_W10_AMENITA.update({c: 25 for c in AMENITA_COMMODITY})

# S = specificita' per-mille (numerico-con-unita' > enumerato > booleano)
_S_NUM, _S_ENUM, _S_BOOL = 1350, 1150, 1000
# V = verificabilita' per-mille (pubblico non falsificabile > strutturato-host > claim-host)
_V_PUBLIC, _V_VERIFIED, _V_CLAIM = 1000, 750, 500
# Un fatto markup-eligible presente ma NON emesso in JSON-LD vale il 55% (spinge all'emissione,
# che e' auto-fixabile lato nostro: la sola-prosa resta cappata, come da design vincitore).
_EMISSIONE_SENZA_MARKUP = 550

# slot con rappresentazione schema.org emettibile dal publisher (gate estraibilita')
_MARKUP_ELIGIBLE = frozenset(
    {"prezzo_notte", "capacita", "camere", "bagni", "coordinate", "rating_verificato",
     "foto"} | {"amenita:" + c for c in _AMENITA_TUTTE})

# prior di share (per-mille) quando la coorte e' piccola (<8): quanto e' COMUNE lo slot
# la' fuori. Conservativi: non assumiamo di essere unici solo perche' siamo pochi.
_PRIOR_SHARE = {
    "wifi": 900, "riscaldamento": 800, "cucina": 700, "aria_condizionata": 600,
    "lavatrice": 600, "parcheggio": 500, "colazione": 400, "check_in_24h": 300,
    "piscina": 150, "animali_ammessi": 150, "vista_mare": 120, "parcheggio_disabili": 80,
    "quartiere": 200, "poi": 80, "tassa_soggiorno": 300, "rating_verificato": 250,
    "prezzo_notte": 500, "capacita": 500, "camere": 500, "bagni": 500, "politica": 400,
    "sconti": 300, "narrativa": 400, "coordinate": 500, "foto": 500,
    "prenotazione_immediata": 400,
}
_PRIOR_DEFAULT = 500
_COORTE_MIN = 8                    # sotto questa soglia la coorte e' cieca -> prior

# categorie POI notevoli (dal ctx pubblico OSM) con peso d'ordinamento
_POI_NOTABILI = {"attraction": 9, "museum": 8, "monument": 8, "beach": 9, "park": 6,
                 "station": 9, "subway": 8, "university": 5, "hospital": 4, "stadium": 6}
_POI_RAGGIO_M = 1500
_MAX_POI = 6
_SPOOF_SOGLIA_M = 2000

# vincibilita' query: f_len per numero di vincoli k (1 - 0.8^k, per-mille)
_F_LEN = {2: 360, 3: 488, 4: 590, 5: 672}
# f_ans (anello debole): numerico-PUBLIC > numerico-verificato/enumerato > claim booleano
_F_ANS_NUM_PUBLIC, _F_ANS_MEDIO, _F_ANS_CLAIM = 1000, 850, 650
_VINC_MIN = 25                     # sotto: la query non si emette (onesta')
_VINC_CITAZIONE = 60               # da qui in su: pronta per FAQ/llms.txt
_MAX_QUERY_PER_LINGUA = 40

LINGUE_QUERY = ("it", "en")

# tabella coseni per-mille per grado di latitudine 0..90 (interi, deterministica ovunque)
_COS_PERMILLE = (
    1000, 1000, 999, 999, 998, 996, 995, 993, 990, 988, 985, 982, 978, 974, 970,
    966, 961, 956, 951, 946, 940, 934, 927, 921, 914, 906, 899, 891, 883, 875,
    866, 857, 848, 839, 829, 819, 809, 799, 788, 777, 766, 755, 743, 731, 719,
    707, 695, 682, 669, 656, 643, 629, 616, 602, 588, 574, 559, 545, 530, 515,
    500, 485, 469, 454, 438, 423, 407, 391, 375, 358, 342, 326, 309, 292, 276,
    259, 242, 225, 208, 191, 174, 156, 139, 122, 105, 87, 70, 52, 35, 17, 0)
_METRI_PER_GRADO = 111319


def distanza_metri(lat1_micro: int, lon1_micro: int,
                   lat2_micro: int, lon2_micro: int) -> int:
    """Distanza approssimata in METRI INTERI fra due punti in microgradi (equirettangolare
    con coseno per-mille da tabella: deterministica byte-a-byte, errore <0.5% sotto i 2km)."""
    # abs PRIMA della divisione (floor su negativi darebbe asimmetria d(A,B)!=d(B,A));
    # coseno del punto MEDIO (simmetrico per costruzione).
    lat_deg = min(90, (abs(int(lat1_micro)) + abs(int(lat2_micro))) // 2 // 1_000_000)
    cos_pm = _COS_PERMILLE[lat_deg]
    dlat_m = abs(int(lat1_micro) - int(lat2_micro)) * _METRI_PER_GRADO // 1_000_000
    dlon_m = (abs(int(lon1_micro) - int(lon2_micro)) * _METRI_PER_GRADO * cos_pm
              // 1_000_000_000)
    return isqrt(dlat_m * dlat_m + dlon_m * dlon_m)


def _radice_n(x: int, n: int) -> int:
    """Radice n-esima intera (floor) via Newton. x>=0, n>=1."""
    if x < 0 or n < 1:
        return 0
    if x in (0, 1) or n == 1:
        return x
    r = int(round(x ** (1.0 / n)))          # seed float, poi CORREZIONE intera esatta
    while r > 0 and r ** n > x:
        r -= 1
    while (r + 1) ** n <= x:
        r += 1
    return r


def _u_distintivita(share_permille: int) -> int:
    """U in [700,1600]: piu' lo slot e' RARO la' fuori, piu' il fatto distingue."""
    s = max(0, min(1000, int(share_permille)))
    return max(700, min(1600, 700 + (1000 - s) * 900 // 1000))


def _share_slot(slot: str, coorte: Optional[Dict[str, Any]]) -> int:
    """Share per-mille dello slot nella coorte-citta'; prior conservativo se coorte cieca."""
    chiave = slot.split(":", 1)[1] if slot.startswith("amenita:") else slot
    if slot.startswith("poi:"):
        chiave = "poi"
    if coorte and isinstance(coorte.get("n_citta"), int) and coorte["n_citta"] >= _COORTE_MIN:
        hanno = coorte.get("hanno") or {}
        n = coorte["n_citta"]
        c = hanno.get(chiave, hanno.get(slot, 0))
        c = c if isinstance(c, int) and c >= 0 else 0
        return min(1000, c * 1000 // n)
    return _PRIOR_SHARE.get(chiave, _PRIOR_DEFAULT)


def _tipo_alloggio(scheda: Dict[str, Any]) -> str:
    """Tipo derivato dai FATTI camere/capacita' (precedenza fissa: villa>casa>monolocale)."""
    cap = scheda.get("capacita") if isinstance(scheda.get("capacita"), int) else 0
    cam = scheda.get("camere") if isinstance(scheda.get("camere"), int) else 0
    if cap >= 8:
        return "villa"
    if cam >= 4:
        return "casa"
    if cam <= 1 and 0 < cap <= 2:
        return "monolocale"
    return "appartamento"


_TIPO_EN = {"villa": "villa", "casa": "house", "monolocale": "studio",
            "appartamento": "apartment"}
_AMENITA_LABEL = {
    "wifi": ("wifi", "wifi"), "parcheggio": ("parcheggio", "parking"),
    "piscina": ("piscina", "pool"), "aria_condizionata": ("aria condizionata",
                                                          "air conditioning"),
    "cucina": ("cucina", "kitchen"), "lavatrice": ("lavatrice", "washing machine"),
    "animali_ammessi": ("animali ammessi", "pets allowed"),
    "colazione": ("colazione", "breakfast"), "vista_mare": ("vista mare", "sea view"),
    "parcheggio_disabili": ("parcheggio disabili", "accessible parking"),
    "check_in_24h": ("check-in 24h", "24h check-in"),
    "riscaldamento": ("riscaldamento", "heating"),
}


# ─────────────────────────────────────────────────────────────────────────────
# LEDGER
# ─────────────────────────────────────────────────────────────────────────────

def _geo_ok(scheda: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[bool, bool, int]:
    """(coords_presenti, spoof, dist_m). Spoof = pin manuale che dista >2km dal geocode
    dell'indirizzo (fase166): i fatti geo non si comprano spostando il pin."""
    lat, lon = scheda.get("lat_micro"), scheda.get("lon_micro")
    presenti = isinstance(lat, int) and isinstance(lon, int)
    if not presenti:
        return False, False, 0
    geoc = ctx.get("geocode_micro")
    if (scheda.get("pin_manuale") and isinstance(geoc, (tuple, list)) and len(geoc) == 2
            and isinstance(geoc[0], int) and isinstance(geoc[1], int)):
        d = distanza_metri(lat, lon, geoc[0], geoc[1])
        if d > _SPOOF_SOGLIA_M:
            return True, True, d
    return True, False, 0


def _poi_notabili(scheda: Dict[str, Any], ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """POI pubblici notevoli entro il raggio, ordinati (peso desc, distanza asc, nome asc),
    top 6. Richiedono coordinate della scheda: senza, nessun fatto-POI."""
    lat, lon = scheda.get("lat_micro"), scheda.get("lon_micro")
    if not (isinstance(lat, int) and isinstance(lon, int)):
        return []
    out = []
    for p in (ctx.get("poi") or ()):
        if not isinstance(p, dict):
            continue
        nome, cat = p.get("nome"), p.get("cat")
        pl, po = p.get("lat_micro"), p.get("lon_micro")
        if not (isinstance(nome, str) and nome and cat in _POI_NOTABILI
                and isinstance(pl, int) and isinstance(po, int)):
            continue
        d = distanza_metri(lat, lon, pl, po)
        if d <= _POI_RAGGIO_M:
            out.append({"nome": nome, "cat": cat, "dist_m": d})
    out.sort(key=lambda p: (-_POI_NOTABILI[p["cat"]], p["dist_m"], p["nome"]))
    return out[:_MAX_POI]


def _presenza_narrativa(scheda: Dict[str, Any], quartiere: Optional[str],
                        poi: Sequence[Dict[str, Any]]) -> int:
    """Descrizione: 300+ char CON menzione locale (quartiere/POI)=1000; 300+=600;
    120+=300; sotto=0. FAIRNESS: se la zona NON offre entita' locali menzionabili
    (nessun quartiere/POI nel ctx), il requisito 'menzione locale' non si applica
    (300+ = 1000): il massimo resta raggiungibile ovunque. Ripetere il testo non
    aggiunge nulla (soglie, non densita')."""
    d = scheda.get("descrizione")
    if not isinstance(d, str):
        return 0
    t = d.strip()
    if len(t) < 120:
        return 0
    if len(t) < 300:
        return 300
    locali = [quartiere] if quartiere else []
    locali += [p["nome"] for p in poi]
    if not locali:
        return 1000                          # zona senza entita' locali: niente penalita'
    basso = t.casefold()
    for nome in locali:
        if nome and nome.casefold() in basso:
            return 1000
    return 600


def _costruisci_ledger(scheda: Dict[str, Any], ctx: Dict[str, Any],
                       coorte: Optional[Dict[str, Any]],
                       markup_emesso: frozenset) -> List[Dict[str, Any]]:
    """Il LEDGER: per ogni slot ACHIEVABILE per questa scheda/posizione, il fatto con
    presenza, S/V/U, emissione e citabilita' (cit) + massimo raggiungibile (cit_max)."""
    fatti: List[Dict[str, Any]] = []
    coords_ok, spoof, dist_spoof = _geo_ok(scheda, ctx)
    quartiere = ctx.get("quartiere") if isinstance(ctx.get("quartiere"), str) else None
    if not coords_ok:
        quartiere = None                     # il quartiere DERIVA dalle coordinate:
                                             # senza pin non esiste (ctx incoerente ignorato)
    poi = [] if spoof else _poi_notabili(scheda, ctx)
    if spoof:
        quartiere = None                     # quartiere dal geocoder non piu' affidabile

    def aggiungi(slot: str, cat: str, w10: int, s: int, v: int, presenza: int,
                 *, v_max: Optional[int] = None, valore: Any = None) -> None:
        u = _u_distintivita(_share_slot(slot, coorte))
        eligible = slot in _MARKUP_ELIGIBLE
        emesso = slot in markup_emesso
        emiss = 1000 if (not eligible or emesso) else _EMISSIONE_SENZA_MARKUP
        pres = max(0, min(1000, int(presenza)))
        vmax = v if v_max is None else v_max
        cit = w10 * s * v * u * pres * emiss // 10 ** 12
        cit_max = w10 * s * vmax * u * 1000 * 1000 // 10 ** 12
        fatti.append({"slot": slot, "categoria": cat, "presenza": pres, "s": s, "v": v,
                      "u": u, "eligible": eligible, "emesso": emesso, "valore": valore,
                      "cit": cit, "cit_max": cit_max})

    # ── base (sempre achievabili) ──
    prezzo = scheda.get("prezzo_notte_cents")
    prezzo_ok = isinstance(prezzo, int) and not isinstance(prezzo, bool) and prezzo > 0
    aggiungi("prezzo_notte", "fatti_base", _W10_BASE["prezzo_notte"], _S_NUM, _V_VERIFIED,
             1000 if prezzo_ok else 0, valore=prezzo if prezzo_ok else None)
    for slot in ("capacita", "camere", "bagni"):
        val = scheda.get(slot)
        ok = isinstance(val, int) and not isinstance(val, bool) and val >= 1
        aggiungi(slot, "fatti_base", _W10_BASE[slot], _S_NUM, _V_VERIFIED,
                 1000 if ok else 0, valore=val if ok else None)
    pol = scheda.get("politica_cancellazione")
    aggiungi("politica", "fatti_base", _W10_BASE["politica"], _S_ENUM, _V_CLAIM,
             1000 if pol in POLITICHE_NOTE else 0, valore=pol)
    aggiungi("prenotazione_immediata", "fatti_base", _W10_BASE["prenotazione_immediata"],
             _S_ENUM, _V_CLAIM,
             1000 if scheda.get("modalita_prenotazione") == "immediata" else 0)
    sw = scheda.get("sconto_settimana_bps")
    sm = scheda.get("sconto_mese_bps")
    ha_sconti = any(isinstance(x, int) and not isinstance(x, bool) and x > 0
                    for x in (sw, sm))
    aggiungi("sconti", "fatti_base", _W10_BASE["sconti"], _S_NUM, _V_CLAIM,
             1000 if ha_sconti else 0)
    nfoto = scheda.get("foto")
    nfoto = nfoto if isinstance(nfoto, int) and not isinstance(nfoto, bool) and nfoto > 0 else 0
    aggiungi("foto", "fatti_base", _W10_BASE["foto"], _S_BOOL, _V_VERIFIED,
             min(nfoto, 8) * 1000 // 8, valore=nfoto)
    aggiungi("narrativa", "fatti_base", _W10_BASE["narrativa"], _S_BOOL, _V_CLAIM,
             _presenza_narrativa(scheda, quartiere, poi))

    # ── amenita': ancora-BITMASK (solo codici strutturati; testo senza codice = 0) ──
    dichiarate = {s for s in (scheda.get("servizi") or ()) if s in _AMENITA_TUTTE}
    for cod in _AMENITA_TUTTE:               # ordine fisso -> deterministico
        aggiungi("amenita:" + cod, "amenita", _W10_AMENITA[cod], _S_BOOL, _V_CLAIM,
                 1000 if cod in dichiarate else 0, valore=cod)

    # ── geo (coordinate sempre achievabili; quartiere/POI solo se il ctx li da') ──
    v_coord = _V_CLAIM if spoof else _V_VERIFIED
    aggiungi("coordinate", "geo", _W10_BASE["coordinate"], _S_NUM, v_coord,
             1000 if coords_ok else 0, v_max=_V_VERIFIED,
             valore={"spoof_dist_m": dist_spoof} if spoof else None)
    if quartiere is not None or (spoof and isinstance(ctx.get("quartiere"), str)):
        aggiungi("quartiere", "geo", _W10_BASE["quartiere"], _S_ENUM, _V_PUBLIC,
                 0 if spoof else 1000, valore=quartiere)
    poi_ctx_esistono = bool(ctx.get("poi"))
    if spoof and poi_ctx_esistono:
        # i POI esistono ma lo spoof li azzera: restano nel massimo -> lo spoof COSTA
        for i in range(min(_MAX_POI, len([p for p in ctx["poi"]
                                          if isinstance(p, dict)
                                          and p.get("cat") in _POI_NOTABILI]))):
            aggiungi("poi:%d" % i, "geo", _W10_POI, _S_NUM, _V_PUBLIC, 0)
    else:
        for i, p in enumerate(poi):
            aggiungi("poi:%d" % i, "geo", _W10_POI, _S_NUM, _V_PUBLIC, 1000,
                     valore=p)
    tassa = ctx.get("comune_tassa")
    if isinstance(tassa, dict):
        aggiungi("tassa_soggiorno", "geo", _W10_BASE["tassa_soggiorno"], _S_NUM,
                 _V_PUBLIC, 1000, valore=tassa)

    # ── fiducia nel tempo ──
    rec = ctx.get("reviews")
    n_rec = rec.get("n") if isinstance(rec, dict) and isinstance(rec.get("n"), int) else 0
    aggiungi("rating_verificato", "fiducia", _W10_BASE["rating_verificato"], _S_NUM,
             _V_PUBLIC, 1000 if n_rec >= 1 else 0,
             valore=rec if n_rec >= 1 else None)
    return fatti


# ─────────────────────────────────────────────────────────────────────────────
# QUERY VINCIBILI (dai fatti presenti; mai teste; k>=2 vincoli fattuali)
# ─────────────────────────────────────────────────────────────────────────────

def _f_ans_fatto(f: Dict[str, Any]) -> int:
    if f["s"] == _S_NUM and f["v"] == _V_PUBLIC:
        return _F_ANS_NUM_PUBLIC
    if f["s"] in (_S_NUM, _S_ENUM) and f["v"] >= _V_VERIFIED:
        return _F_ANS_MEDIO
    if f["s"] == _S_ENUM:
        return _F_ANS_MEDIO
    return _F_ANS_CLAIM


_SLOT_IMBALLAGGIO = frozenset({"camere", "capacita"})


def _vincibilita(vincoli: List[Dict[str, Any]], f_head: int,
                 coorte: Optional[Dict[str, Any]]) -> int:
    """0-100 da f_len(k) x f_dist(rarita') x f_ans(anello debole) x f_head, con
    AMMORBIDIMENTO GEOMETRICO (radice quadrata del prodotto): il prodotto secco di
    4 fattori <=1 comprime tutto in basso e rende le bande irraggiungibili; la radice
    conserva l'ORDINAMENTO (monotona) e distribuisce i valori sull'intera scala.
    La rarita' (f_dist) si misura sui QUALIFICATORI della query: camere/capacita sono
    imballaggio presente in ogni query col tipo, non cio' che la distingue."""
    k = min(5, len(vincoli))
    if k < 2:
        return 0
    f_len = _F_LEN[k]
    qualificatori = [f for f in vincoli if f["slot"] not in _SLOT_IMBALLAGGIO]
    base_dist = qualificatori or vincoli
    prod = 1
    for f in base_dist:
        share = _share_slot(f["slot"], coorte)
        prod *= 500 + 500 * (1000 - share) // 1000
    f_dist = _radice_n(prod, len(base_dist))
    f_ans = min(_f_ans_fatto(f) for f in vincoli)
    pm4 = f_len * f_dist * f_ans * f_head          # <= 10^12: esatto in int
    return max(0, min(100, isqrt(pm4) // 10_000))


def _genera_query(scheda: Dict[str, Any], fatti: List[Dict[str, Any]],
                  coorte: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    per_slot = {f["slot"]: f for f in fatti}

    def pres(slot: str) -> bool:
        f = per_slot.get(slot)
        return bool(f and f["presenza"] >= 1000)

    citta = scheda.get("citta") if isinstance(scheda.get("citta"), str) else ""
    if not citta:
        return []
    tipo_it = _tipo_alloggio(scheda)
    tipo_en = _TIPO_EN[tipo_it]
    tipo_f = [per_slot["camere"], per_slot["capacita"]]
    tipo_ok = pres("camere") and pres("capacita")
    quart_f = per_slot.get("quartiere")
    quartiere = (quart_f or {}).get("valore")
    out: List[Dict[str, Any]] = []

    def emetti(testo_it: str, testo_en: str, vincoli: List[Dict[str, Any]],
               f_head: int) -> None:
        # dedup per slot (ordine di inserzione stabile): k conta fatti DISTINTI
        vincoli = list({f["slot"]: f for f in vincoli}.values())
        v = _vincibilita(vincoli, f_head, coorte)
        if v < _VINC_MIN:
            return
        slots = sorted({f["slot"] for f in vincoli})
        for lingua, testo in (("it", testo_it), ("en", testo_en)):
            out.append({"lingua": lingua, "testo": testo, "vincibilita": v,
                        "k": len(vincoli), "fatti": slots,
                        "bucket": ("vincibile_ora" if v >= _VINC_CITAZIONE else
                                   "contendibile" if v >= 40 else "aspirazionale"),
                        "citazione_pronta": v >= _VINC_CITAZIONE})

    # T1 amenita' singola (per ogni amenita' dichiarata; alta pesa di piu' nel head)
    if tipo_ok:
        for cod in _AMENITA_TUTTE:
            f = per_slot["amenita:" + cod]
            if f["presenza"] < 1000:
                continue
            it, en = _AMENITA_LABEL[cod]
            head = 650 if cod in AMENITA_ALTA else 550
            emetti("%s con %s a %s" % (tipo_it, it, citta),
                   "%s with %s in %s" % (tipo_en, en, citta),
                   tipo_f + [f], head)
        # T2 combo di 2 amenita' ALTA (le 3 piu' rare dichiarate -> max 3 coppie)
        alte = [c for c in AMENITA_ALTA if pres("amenita:" + c)]
        alte.sort(key=lambda c: (_share_slot("amenita:" + c, coorte), c))
        alte = alte[:3]
        for i in range(len(alte)):
            for j in range(i + 1, len(alte)):
                a, b = alte[i], alte[j]
                emetti("%s con %s e %s a %s" % (tipo_it, _AMENITA_LABEL[a][0],
                                                _AMENITA_LABEL[b][0], citta),
                       "%s with %s and %s in %s" % (tipo_en, _AMENITA_LABEL[a][1],
                                                    _AMENITA_LABEL[b][1], citta),
                       tipo_f + [per_slot["amenita:" + a], per_slot["amenita:" + b]],
                       1000)
        # T3 capacita'
        cap = scheda.get("capacita")
        emetti("%s per %d persone a %s" % (tipo_it, cap, citta),
               "%s for %d guests in %s" % (tipo_en, cap, citta),
               tipo_f + [per_slot["capacita"]], 550)
        # T4 prezzo (arrotondato SU alla decina: onesto, mai sotto il vero)
        if pres("prezzo_notte"):
            euro = scheda["prezzo_notte_cents"] // 100
            arr = ((euro + 9) // 10) * 10
            emetti("%s a %s sotto %d euro a notte" % (tipo_it, citta, arr),
                   "%s in %s under %d euro per night" % (tipo_en, citta, arr),
                   tipo_f + [per_slot["prezzo_notte"]], 550)
        # T5 policy flessibile
        if pres("politica") and scheda.get("politica_cancellazione") == "flessibile":
            emetti("%s a %s con cancellazione gratuita" % (tipo_it, citta),
                   "%s in %s with free cancellation" % (tipo_en, citta),
                   tipo_f + [per_slot["politica"]], 550)
        # T6 quartiere
        if quart_f is not None and quart_f["presenza"] >= 1000 and quartiere:
            emetti("%s in zona %s a %s" % (tipo_it, quartiere, citta),
                   "%s in the %s area, %s" % (tipo_en, quartiere, citta),
                   tipo_f + [quart_f], 700)
            if pres("amenita:animali_ammessi"):
                emetti("dove dormire con il cane in zona %s a %s" % (quartiere, citta),
                       "pet friendly stay in %s, %s" % (quartiere, citta),
                       [quart_f, per_slot["amenita:animali_ammessi"]], 900)
    # T7 POI (fatti pubblici: la risposta e' la DISTANZA in metri)
    for f in fatti:
        if not f["slot"].startswith("poi:") or f["presenza"] < 1000:
            continue
        p = f["valore"]
        if tipo_ok:
            emetti("%s vicino a %s a %s" % (tipo_it, p["nome"], citta),
                   "%s near %s in %s" % (tipo_en, p["nome"], citta),
                   tipo_f + [f], 900)
            minuti = max(1, p["dist_m"] // 80)
            emetti("dormire a %d minuti a piedi da %s" % (minuti, p["nome"]),
                   "stay %d minutes walk from %s" % (minuti, p["nome"]),
                   [f, per_slot["coordinate"]], 900)
    # T8 tassa di soggiorno (evergreen fattuale: importo + giurisdizione)
    tf = per_slot.get("tassa_soggiorno")
    if tf is not None and tf["presenza"] >= 1000 and pres("coordinate"):
        emetti("quanto e' la tassa di soggiorno a %s" % citta,
               "how much is the tourist tax in %s" % citta,
               [tf, per_slot["coordinate"]], 900)

    # dedup + ordinamento totale + tetto per lingua
    visti = set()
    dedup = []
    for q in out:
        chiave = (q["lingua"], q["testo"])
        if chiave in visti:
            continue
        visti.add(chiave)
        dedup.append(q)
    dedup.sort(key=lambda q: (-q["vincibilita"], q["lingua"], q["testo"]))
    per_lingua: Dict[str, int] = {}
    finali = []
    for q in dedup:
        per_lingua[q["lingua"]] = per_lingua.get(q["lingua"], 0) + 1
        if per_lingua[q["lingua"]] <= _MAX_QUERY_PER_LINGUA:
            finali.append(q)
    return finali


# ─────────────────────────────────────────────────────────────────────────────
# GAP (partizione ESATTA del punteggio perso + azioni white-hat)
# ─────────────────────────────────────────────────────────────────────────────

_AZIONI = {
    "prezzo_notte": ("host", "imposta il prezzo a notte"),
    "capacita": ("host", "indica quante persone puo' ospitare"),
    "camere": ("host", "indica il numero di camere"),
    "bagni": ("host", "indica il numero di bagni"),
    "politica": ("host", "scegli una politica di cancellazione"),
    "prenotazione_immediata": ("host_condizionale",
                               "SE vuoi, attiva la prenotazione immediata"),
    "sconti": ("host_condizionale",
               "SE li offri, dichiara sconti settimana/mese"),
    "foto": ("host", "carica almeno 8 foto"),
    "narrativa": ("host", "scrivi una descrizione di 300+ caratteri che citi il "
                          "quartiere o un luogo vicino"),
    "coordinate": ("host", "imposta il pin sulla mappa (sblocca i fatti di zona)"),
    "quartiere": ("sistema", "risolvi il quartiere dal geocoder"),
    "tassa_soggiorno": ("sistema", "configura la tassa comunale (fase147)"),
    "rating_verificato": ("tempo", "arrivera' con le prime recensioni verificate"),
}


def _gap_ledger(fatti: List[Dict[str, Any]], punteggio_milli: int,
                scheda: Dict[str, Any], ctx: Dict[str, Any],
                coorte: Optional[Dict[str, Any]],
                markup_emesso: frozenset) -> List[Dict[str, Any]]:
    """Ogni slot sotto il massimo -> un gap. La somma dei punti_persi_milli e' ESATTAMENTE
    100000 - punteggio_milli (ripartizione largest-remainder deterministica)."""
    deficit = [(f, f["cit_max"] - f["cit"]) for f in fatti if f["cit_max"] > f["cit"]]
    totale_d = sum(d for _f, d in deficit)
    da_ripartire = 100_000 - punteggio_milli
    gap: List[Dict[str, Any]] = []
    if totale_d > 0 and da_ripartire > 0:
        base = []
        for f, d in deficit:
            q_int = da_ripartire * d // totale_d
            resto = da_ripartire * d % totale_d
            base.append([f, d, q_int, resto])
        mancano = da_ripartire - sum(b[2] for b in base)
        base.sort(key=lambda b: (-b[3], b[0]["slot"]))
        for i in range(mancano):
            base[i % len(base)][2] += 1
        for f, _d, milli, _r in base:
            slot = f["slot"]
            if slot.startswith("amenita:"):
                cod = slot.split(":", 1)[1]
                if f["presenza"] >= 1000:
                    tipo, az = "sistema", ("emetti amenityFeature '%s' nel JSON-LD" % cod)
                else:
                    tipo, az = "host_condizionale", (
                        "SE il tuo alloggio ha davvero '%s', dichiaralo (e mostralo "
                        "in foto)" % _AMENITA_LABEL[cod][0])
            elif slot.startswith("poi:"):
                tipo, az = "host", "conferma l'indirizzo: la posizione non aggancia i luoghi vicini"
            elif f["eligible"] and f["presenza"] >= 1000 and not f["emesso"]:
                tipo, az = "sistema", "emetti '%s' nel JSON-LD della pagina" % slot
            elif slot == "coordinate" and f["presenza"] >= 1000 and f["v"] == _V_CLAIM:
                d_sp = (f.get("valore") or {}).get("spoof_dist_m", 0)
                tipo, az = "host", ("conferma l'indirizzo: il pin dista %dm dal "
                                    "geocode dell'indirizzo" % d_sp)
            else:
                tipo, az = _AZIONI.get(slot, ("host", "completa il dato '%s'" % slot))
            gap.append({"slot": slot, "tipo": tipo, "azione": az,
                        "condizionale": tipo == "host_condizionale",
                        "punti_persi_milli": milli, "punti_persi": milli // 1000})
    # delta_query: quante query NUOVE sbloccherebbe portare lo slot a presente+emesso
    base_q = {(q["lingua"], q["testo"])
              for q in _genera_query(scheda, fatti, coorte)}
    for g in gap:
        g["delta_query"] = _conta_sbloccate(g["slot"], scheda, ctx, coorte,
                                            markup_emesso, base_q)
    gap.sort(key=lambda g: (-(g["punti_persi_milli"] + 2000 * g["delta_query"]),
                            g["slot"]))
    # gap informativi (0 punti, non nella partizione): opportunita' fuori dal massimo
    if not isinstance(ctx.get("comune_tassa"), dict):
        gap.append({"slot": "tassa_soggiorno", "tipo": "sistema",
                    "azione": "configura la tassa comunale (fase147): sblocca la "
                              "risposta evergreen 'quanto e' la tassa di soggiorno'",
                    "condizionale": False, "punti_persi_milli": 0, "punti_persi": 0,
                    "delta_query": 0})
    return gap


def _conta_sbloccate(slot: str, scheda: Dict[str, Any], ctx: Dict[str, Any],
                     coorte: Optional[Dict[str, Any]], markup_emesso: frozenset,
                     base_q: set) -> int:
    """Ri-esegue la generazione con lo slot IPOTETICAMENTE colmato (scenario esatto,
    nessuna stima): quante query nuove appaiono."""
    s2 = dict(scheda)
    if slot.startswith("amenita:"):
        cod = slot.split(":", 1)[1]
        servizi = list(s2.get("servizi") or ())
        if cod not in servizi:
            servizi.append(cod)
        s2["servizi"] = tuple(servizi)
    elif slot == "coordinate" and not isinstance(s2.get("lat_micro"), int):
        return 0                    # senza ctx-POI noti l'upside non e' quantificabile
    elif slot == "politica":
        s2["politica_cancellazione"] = "flessibile"
    elif slot == "prezzo_notte" and not s2.get("prezzo_notte_cents"):
        return 0
    elif slot in ("capacita", "camere", "bagni"):
        if not (isinstance(s2.get(slot), int) and s2.get(slot)):
            s2[slot] = 1 if slot != "capacita" else 2
    fatti2 = _costruisci_ledger(s2, ctx, coorte, markup_emesso | {slot})
    nuove = {(q["lingua"], q["testo"]) for q in _genera_query(s2, fatti2, coorte)}
    return len(nuove - base_q)


# ─────────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────────

def valuta_annuncio(scheda: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None,
                    coorte: Optional[Dict[str, Any]] = None,
                    markup_emesso: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """IL CERVELLO. Input: scheda-dict (campi fase57), ctx pubblico iniettato
    {poi:[{nome,cat,lat_micro,lon_micro}], quartiere:str|None, comune_tassa:dict|None,
    reviews:{n,...}|None, geocode_micro:(lat,lon)|None}, coorte {n_citta, hanno:{slot:n}},
    markup_emesso = slot gia' serviti in JSON-LD dalla pagina.
    Output: {punteggio 0-100, punteggio_milli, sotto_punteggi, fatti, query, gap}.
    PURO, deterministico, BLINDATO (input rotto -> valutazione degradata, mai eccezione)."""
    try:
        if not isinstance(scheda, dict):
            scheda = {}
        ctx = ctx if isinstance(ctx, dict) else {}
        coorte = coorte if isinstance(coorte, dict) else None
        emessi = frozenset(s for s in (markup_emesso or ()) if isinstance(s, str))
        fatti = _costruisci_ledger(scheda, ctx, coorte, emessi)
        raw = sum(f["cit"] for f in fatti)
        maxref = sum(f["cit_max"] for f in fatti)
        punteggio_milli = 100_000 * raw // maxref if maxref > 0 else 0
        query = _genera_query(scheda, fatti, coorte)
        gap = _gap_ledger(fatti, punteggio_milli, scheda, ctx, coorte, emessi)

        sotto: Dict[str, int] = {}
        for cat in ("fatti_base", "geo", "amenita", "fiducia"):
            fs = [f for f in fatti if f["categoria"] == cat]
            mx = sum(f["cit_max"] for f in fs)
            sotto[cat] = 100 * sum(f["cit"] for f in fs) // mx if mx > 0 else 100
        eligibili = [f for f in fatti if f["eligible"] and f["presenza"] > 0]
        sotto["estraibilita"] = (100 * sum(1 for f in eligibili if f["emesso"])
                                 // len(eligibili)) if eligibili else 100

        return {"punteggio": punteggio_milli // 1000,
                "punteggio_milli": punteggio_milli,
                "sotto_punteggi": sotto,
                "fatti": fatti, "query": query, "gap": gap,
                "citazioni_pronte": [q for q in query if q["citazione_pronta"]]}
    except Exception:
        return {"punteggio": 0, "punteggio_milli": 0, "sotto_punteggi": {},
                "fatti": [], "query": [], "gap": [], "citazioni_pronte": [],
                "errore": "valutazione_degradata"}
