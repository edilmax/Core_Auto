"""L'ESAME DELLA CASELLA «relazioni metamorfiche» DEL BLOCCO 4 (PREZZI, COMMISSIONI E TASSE).

    python collaudi/esame_prezzi.py                 esegue le relazioni sul MOTORE VERO e MOSTRA
    python collaudi/esame_prezzi.py --scrivi        ...e SCRIVE nella scheda (anche un rosso, col motivo)
    python collaudi/esame_prezzi.py --casi N        N casi generati per relazione (di serie 300)
    python collaudi/esame_prezzi.py --seme S        seme di Hypothesis (di serie 0: riproducibile)
    python collaudi/esame_prezzi.py --con-guasto    storce il motore (un centesimo in piu' sul doppio
                                                    delle notti): deve gridare, e NON scrive mai
    python collaudi/esame_prezzi.py --autoprova     si vede gridare e tacere su un motore finto,
                                                    senza toccare quello vero (D18 punto 2)

⛔ IL TESTO DELLA CASELLA NON SI RICOPIA: si legge da `collaudi/piano.py` (Blocco 4, «finito_quando»)
   cercando la sottostringa stabile «relazioni metamorfiche reggono»: una e una sola.

IL MOTORE VERO (D10, misurato il 2026-09-07 con `grep` dei chiamanti): il prezzo che l'ospite paga
lo calcola SOLO `fase59_concierge.ProtocolloConcierge.quota` (netto per notte dall'inventario, sconto
soggiorno lungo dal catalogo, sconto «non rimborsabile», commissione all'host, credito fondatore,
tassa, tariffa tecnica); `fase44_prezzo` e `fase45_pricing` sono del vecchio stack e nessun modulo di
produzione li importa (`grep -rln fase44_prezzo|fase45_pricing` -> solo fase45 stesso). Qui il
concierge e' quello VERO, con un inventario e un catalogo in memoria che rispondono solo «prezzo a
notte», «valuta», «sconto lungo», «politica»; le tariffe (PAGAMENTO_BPS, PAGAMENTO_FISSO_CENTS,
COMMISSIONE_BPS) si LEGGONO da `main_casavip.py`, mai ricopiate (S17, D22). Il credito entra con un
gettone firmato dalla STESSA firma del concierge, come in produzione. La TASSA del preventivo la
calcola `fase66_tassa_soggiorno.calcola_tassa` (chiamata da `fase81_bootstrap_casavip._tassa_alloggio`;
`fase147` e' il registro comunale, non il preventivo): le relazioni sulla tassa girano su quella
funzione VERA.

LE RELAZIONI (D25: T.Y. Chen, S.C. Cheung, S.M. Yiu, «Metamorphic Testing: A New Approach for
Generating Next Test Cases», HKUST-CS98-01, 1998 — una relazione lega due esecuzioni imparentate,
non un valore atteso; Segura, Fraser, Sanchez, Ruiz-Cortes, «A Survey on Metamorphic Testing»,
IEEE TSE 42(9), 2016 — relazioni additive/moltiplicative/inclusive e la loro forza nel trovare
difetti dove un oracolo non c'e'). I casi li genera Hypothesis (seme fisso: riproducibile), il
denominatore e' relazioni x casi:

  R1  «raddoppiare le notti raddoppia il listino» — MOLTIPLICATIVA: con lo stesso prezzo a notte,
      2n notti danno ESATTAMENTE 2x `prezzo_listino_cents` (la parte del prezzo che dipende solo
      dalle notti, prima di sconti e tariffe). Vale nella stessa fascia di sconto (n e 2n entrambi
      sotto 7, o entrambi fra 7 e 27).
  R1b la QUOTA FISSA della tariffa tecnica NON raddoppia: `costo_pagamento - floor(totale*bps/10000)`
      vale sempre PAGAMENTO_FISSO_CENTS, a 1 notte come a 60 (e' per transazione, non per notte).
  R2  «gli sconti seguono l'ordine DICHIARATO, e l'inverso sposta al massimo un centesimo» — il
      motore applica PRIMA lo sconto soggiorno lungo e POI il -12% «non rimborsabile»
      (fase59:294-315), ognuno con la sua divisione intera. Due misure: (a) il `prezzo_guest_cents`
      e' ESATTAMENTE quello dell'ordine dichiarato, ricalcolato qui coi tassi che il motore stesso
      dichiara; (b) l'ordine inverso ne dista al massimo 1 centesimo.
      ⛔ STORIA (7/9 -> 29/9): la casella diceva «l'ordine degli sconti non cambia il totale», e
      l'esame l'ha misurata FALSA sul motore vero (26 notti da 1,00 EUR, sconto 28,02%: 16,48
      contro 16,47). Non era un difetto: con due divisioni intere l'ordine sposta i centesimi.
      Decisione del fondatore il 29/9 («autorizzato fai la cosa giusta»): si riscrive la casella
      invece del motore. Il limite di 1 centesimo e' DIMOSTRATO, non scelto: in un ordine qualsiasi
      il risultato sta in [g, g+2) con g = L(1-a)(1-b) esatto (l'errore di ogni divisione intera e'
      in [0,1), e il primo arriva ridotto di (1-b)), quindi due interi in quell'intervallo
      distano al massimo 1. Un difetto vero -- uno sconto calcolato sul prezzo sbagliato, un tasso
      diverso, un ordine scambiato -- rompe la (a).
  R3  CONSERVAZIONE (invariante, non metamorfica, ma costa zero): `totale = guest + tassa` e
      `guest = listino - sconto_lungo - sconto_non_rimborsabile - sconto_credito`.
  R4  MONOTONIA: a notti uguali, un prezzo a notte piu' alto non fa pagare di meno l'ospite ne'
      incassare di piu' l'host per notte in meno.
  R5  «la COMMISSIONE tocca solo l'host»: la stessa quota con due commissioni diverse (0, 5, 8,
      10%) da' listino, sconti, prezzo dell'ospite, tassa, totale e costo carta IDENTICI; il netto
      dell'host cambia esattamente della differenza di commissione. (Senza credito: il margine del
      credito dipende dalla commissione per costruzione, fase59:506-509.)
  R6  «il prezzo a notte RADDOPPIATO»: stesse notti, prezzo 2p invece di p. Il listino raddoppia
      ESATTO; ogni sconto raddoppia entro 1 centesimo (una divisione intera su un valore doppio);
      il prezzo dell'ospite sta fra 2g-2 e 2g+1. Il margine e' DIMOSTRATO sull'aritmetica:
      sconto lungo s2-2s in {0,1} -> netto n2 = 2n-e1; -12% nr2-2nr in {-1,0,1}; quindi
      g2-2g = -e1-(nr2-2nr) in [-2,1].
  R7  «il CREDITO viene per ULTIMO e non lo paga l'host»: la stessa quota con e senza gettone di
      credito. Listino, sconti, prezzo netto, commissione e tassa IDENTICI (il credito entra dopo
      tutto, fase59:331); lo sconto non supera il credito ne' la nostra commissione; il prezzo
      dell'ospite scende esattamente dello sconto; il netto dell'host NON scende (il costo carta,
      suo, scende col totale). ⛔ Premessa: i casi hanno prezzi da cui la commissione lascia
      margine; se il credito non entra (sconto 0) la relazione non prova niente e dice ROSSO (S7).
  R8  TASSA: «un ospite ESENTE in piu' non cambia la tassa» (ospiti+1 ed esenti+1).
  R9  TASSA: «raddoppiare gli ospiti PAGANTI raddoppia la componente fissa» ESATTO (moltiplicazione
      intera, nessuna divisione) e lascia identica quella percentuale.
  R10 TASSA: «raddoppiare le notti raddoppia la componente fissa» ESATTO, DENTRO i tetti dichiarati
      (notti tassabili e tetto per persona non raggiunti: e' la loro funzione rompere la
      proporzione, ed e' giusto); la percentuale, a imponibile uguale, resta identica.

⛔ D18: precondizioni (la casella esiste una sola; il motore vero si costruisce; le tariffe si leggono
   da main_casavip; il -12% dichiarato dal motore su 100 EUR e' misurato, non creduto; la tassa vera
   si importa); --autoprova nelle due direzioni su un motore FINTO e una tassa FINTA che sbagliano
   apposta, una relazione alla volta; NON_GUARDA; guardia in `test_pipeline_ci.TestLEsameDeiPrezzi
   NonPuoBARARE`.
"""
import io
import os
import re
import sys

QUI =os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
for _p in (RADICE, QUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import scheda  # noqa: E402
from piano import BLOCCHI  # noqa: E402

BLOCCO = 4
MARCA = "relazioni metamorfiche reggono"
COMANDO = "python collaudi/esame_prezzi.py --scrivi"
CASI_DI_SERIE = 300
SLUG = "casa-esame-prezzi"
CI = "2026-10-01"
# L'«adesso» del preventivo sotto esame: il 1 gennaio 2026, PRIMA dell'arrivo (dal lotto D del
# 2026-10-10 il passato non si vende). La data non entra in nessuna relazione: e' la cornice.
ADESSO = 1767225600
# Le commissioni fra cui R5 sceglie: zero (rampa di lancio), link diretto, scaglione, regime.
# Non sono le NOSTRE tariffe ricopiate (quelle le decide fase98): sono ingressi di prova, e la
# relazione deve reggere per QUALUNQUE commissione.
COMMISSIONI_DI_PROVA = (0, 500, 800, 1000)

NON_GUARDA = (
    "la TASSA dentro il preventivo: le relazioni R8-R10 girano su `fase66.calcola_tassa`, la "
    "funzione che il preventivo chiama; il COLLEGAMENTO fase81 -> fase66 (`_tassa_alloggio`, la "
    "regola letta dal catalogo) non passa da qui, e nel preventivo sotto esame la tassa e' 0",
    "la valuta ESTERA: relazioni gia' in test_property_soldi (MR3) e nei dedicati; qui il motore "
    "gira in EUR",
    "il credito USA E GETTA (fase167): qui il concierge non ha l'archivio dei crediti spesi, quindi "
    "R7 prova l'ordine e chi paga, non che un credito non si spenda due volte",
    "il calendario dei prezzi variabili (fase119): qui ogni notte ha lo STESSO prezzo, perche' R1 "
    "ha senso solo cosi'; con prezzi diversi per notte la «parte fissa» e' la somma, non il doppio",
    "i rimborsi, gli split e la «paga in struttura»: hanno le loro relazioni in test_property_soldi "
    "(MR5-MR12)",
    "che la scelta «prima lo sconto lungo, poi il -12%» sia quella GIUSTA per il cliente: qui si "
    "misura che il motore segua l'ordine dichiarato e che l'inverso sposti al massimo 1 centesimo",
    "la commissione VERA per anzianita' e fonte (fase98, collegata da fase81): R5 usa commissioni "
    "di prova e prova che, qualunque sia, tocchi solo l'host",
)


# --------------------------------------------------------------------------------------
# 1. IL MOTORE VERO, con inventario e catalogo in memoria
# --------------------------------------------------------------------------------------
def default_di_produzione(nome):
    """Il valore PREDEFINITO che gira in produzione, letto da main_casavip.py (mai ricopiato)."""
    with io.open(os.path.join(RADICE, "main_casavip.py"), encoding="utf-8", errors="replace") as f:
        src = f.read()
    m = re.search(nome + r'["\']\s*,\s*["\'](\d+)["\']', src)
    if not m:
        raise ValueError("non trovo %s in main_casavip.py: non sono in condizione di misurare" % nome)
    return int(m.group(1))


class _Inv:
    def __init__(self, notte_cents):
        self.notte = int(notte_cents)

    def disponibile(self, a, ci, co):
        return True

    def stato_giorno(self, a, g):
        return {"prezzo_netto_cents": self.notte}


class _Cat:
    def __init__(self, sconto_settimana_bps=0, sconto_mese_bps=0, politica="flessibile"):
        self.ss, self.sm, self.pol = int(sconto_settimana_bps), int(sconto_mese_bps), politica

    def dettaglio(self, slug):
        return {"slug": slug, "valuta": "EUR", "stato": "pubblicato"}

    def sconto_lungo_di(self, slug):
        return (self.ss, self.sm)

    def politica_cancellazione_di(self, slug):
        return self.pol


def _co(notti):
    import datetime
    d = datetime.date.fromisoformat(CI) + datetime.timedelta(days=int(notti))
    return d.isoformat()


def motore_vero(notte_cents, *, notti, sconto_settimana_bps=0, sconto_mese_bps=0,
                non_rimborsabile=False, tariffe=None, commissione_bps=None, credito_cents=0):
    """UNA quota del concierge VERO: torna il dizionario firmato (il corpo della risposta).
    `commissione_bps` sostituisce quella delle tariffe (R5); `credito_cents` > 0 presenta un
    gettone di credito fondatore firmato dalla stessa firma del concierge (R7)."""
    from fase59_concierge import FirmaQuote, ProtocolloConcierge
    t = tariffe or tariffe_di_produzione()
    c_bps = t["commissione_bps"] if commissione_bps is None else int(commissione_bps)
    firma = FirmaQuote(b"e" * 32)
    p = ProtocolloConcierge(
        _Inv(notte_cents), firma,
        catalogo=_Cat(sconto_settimana_bps, sconto_mese_bps,
                      "non_rimborsabile" if non_rimborsabile else "flessibile"),
        commissione=lambda netto: netto * c_bps // 10000,
        psp_bps=t["psp_bps"], psp_fisso_cents=t["psp_fisso"], orologio=lambda: ADESSO)
    richiesta = {"alloggio_id": SLUG, "check_in": CI, "check_out": _co(notti), "party": 2}
    if credito_cents:
        richiesta["credito_token"] = firma.codifica({
            "tipo": "credito_fondatore", "credito_cents": int(credito_cents), "valuta": "EUR",
            "exp": ADESSO + 3600})
    r = p.quota(richiesta)
    if r.status != 200:
        raise ValueError("quota non riuscita: %s %s" % (r.status, r.corpo))
    return dict(r.corpo)


def tariffe_di_produzione():
    return {"psp_bps": default_di_produzione("PAGAMENTO_BPS"),
            "psp_fisso": default_di_produzione("PAGAMENTO_FISSO_CENTS"),
            "commissione_bps": default_di_produzione("COMMISSIONE_BPS")}


def tassa_vera(regola, *, notti, ospiti, imponibile, esenti=0):
    """La tassa del preventivo: `fase66.calcola_tassa` VERA. `regola` e' un dizionario coi campi
    di `RegolaTassa`; si torna (tassa, componente fissa, componente percentuale)."""
    from fase66_tassa_soggiorno import RegolaTassa, calcola_tassa
    c = calcola_tassa(RegolaTassa(**regola), notti=notti, ospiti=ospiti,
                      imponibile_cents=imponibile, esenti=esenti)
    return c.tassa_cents, c.componente_fissa_cents, c.componente_percentuale_cents


# --------------------------------------------------------------------------------------
# 2. LE RELAZIONI (pure: ricevono un `motore(notte, notti=..., ...)` e una `tassa(...)` e
#    rendono un esito)
# --------------------------------------------------------------------------------------
def _tasso_nr_dichiarato(motore):
    """Il -12% «non rimborsabile» non si copia: si LEGGE da cio' che il motore fa su 1 notte da
    100 EUR senza sconto lungo (sconto_nr / listino, in bps)."""
    q = motore(10000, notti=1, non_rimborsabile=True)
    return int(q["sconto_non_rimborsabile_cents"]) * 10000 // int(q["prezzo_listino_cents"])


def relazioni(motore, tariffe, *, casi=CASI_DI_SERIE, seme=0, tassa=None):
    """Esegue R1-R10 con Hypothesis. Torna [(nome, casi_eseguiti, contro_esempi)]."""
    from hypothesis import given, settings, strategies as st, HealthCheck, seed
    tassa = tassa or tassa_vera
    fisso, bps = tariffe["psp_fisso"], tariffe["psp_bps"]
    nr_bps = _tasso_nr_dichiarato(motore)
    S = settings(max_examples=casi, deadline=None, database=None,
                 suppress_health_check=list(HealthCheck), derandomize=False)
    # da 1 EUR a notte fino al tetto del motore (fase59.MAX_CENTS su 60 notti): un preventivo oltre
    # il tetto risponde 422 «prezzo_fuori_banda» per contratto, e non e' cio' che si misura qui
    try:
        from fase59_concierge import MAX_CENTS
    except Exception:
        MAX_CENTS = 100_000_000
    P = st.integers(min_value=100, max_value=MAX_CENTS // 60)
    esiti = []

    def corri(nome, corpo):
        contati = {"n": 0}
        contro = []

        def prova(**kw):
            contati["n"] += 1
            errore = corpo(**kw)
            if errore:
                contro.append("%s -> %s" % (kw, errore))
                raise AssertionError(errore)
        try:
            seed(seme)(S(given(**corpo.strategie)(prova)))()
        except AssertionError:
            pass
        esiti.append((nome, contati["n"], contro[:3]))

    # R1 — 2n notti = 2x listino (stessa fascia di sconto)
    def r1(p, n, fascia, sl):
        nn = n if fascia == "corta" else n + 7   # corta: n,2n in 1..3 ; media: n,2n in 7..13
        q1 = motore(p, notti=nn, sconto_settimana_bps=sl)
        q2 = motore(p, notti=2 * nn, sconto_settimana_bps=sl)
        if int(q2["prezzo_listino_cents"]) != 2 * int(q1["prezzo_listino_cents"]):
            return "listino(%d notti)=%d, listino(%d)=%d" % (nn, q1["prezzo_listino_cents"],
                                                              2 * nn, q2["prezzo_listino_cents"])
        return ""
    r1.strategie = dict(p=P, n=st.integers(min_value=1, max_value=3),
                        fascia=st.sampled_from(["corta", "media"]),
                        sl=st.integers(min_value=0, max_value=3000))
    corri("R1 raddoppiare le notti raddoppia il listino", r1)

    # R1b — la quota fissa della tariffa tecnica NON scala con le notti
    def r1b(p, n):
        q = motore(p, notti=n)
        tot = int(q["totale_cents"])
        variabile = tot * bps // 10000
        if int(q["costo_pagamento_cents"]) - variabile != fisso:
            return "costo_pagamento=%d, parte variabile=%d, fisso atteso=%d" % (
                q["costo_pagamento_cents"], variabile, fisso)
        return ""
    r1b.strategie = dict(p=P, n=st.integers(min_value=1, max_value=60))
    corri("R1b la quota fissa della tariffa tecnica non raddoppia", r1b)

    # R2 — l'ordine DICHIARATO (lungo, poi -12%) esatto; l'inverso a non piu' di 1 centesimo
    def r2(p, n, sl):
        q = motore(p, notti=n, sconto_settimana_bps=sl, non_rimborsabile=True)
        L = int(q["prezzo_listino_cents"])
        g = int(q["prezzo_guest_cents"])
        dopo_lungo = L - L * sl // 10000
        dichiarato = dopo_lungo - dopo_lungo * nr_bps // 10000
        dopo_nr = L - L * nr_bps // 10000
        inverso = dopo_nr - dopo_nr * sl // 10000
        if g != dichiarato:
            return "motore = %d, ordine dichiarato (lungo %d bps poi -%d bps) = %d; listino %d" % (
                g, sl, nr_bps, dichiarato, L)
        if abs(g - inverso) > 1:
            return "motore = %d, ordine inverso = %d: distano %d centesimi (al massimo 1)" % (
                g, inverso, abs(g - inverso))
        return ""
    r2.strategie = dict(p=P, n=st.integers(min_value=7, max_value=27),
                        sl=st.integers(min_value=1, max_value=3000))
    corri("R2 gli sconti seguono l'ordine dichiarato, l'inverso sposta al massimo 1 centesimo", r2)

    # R3 — conservazione
    def r3(p, n, sl, nr):
        q = motore(p, notti=n, sconto_settimana_bps=sl, non_rimborsabile=nr)
        if int(q["totale_cents"]) != int(q["prezzo_guest_cents"]) + int(q["tassa_soggiorno_cents"]):
            return "totale %d != guest %d + tassa %d" % (q["totale_cents"], q["prezzo_guest_cents"],
                                                        q["tassa_soggiorno_cents"])
        atteso = (int(q["prezzo_listino_cents"]) - int(q["sconto_soggiorno_lungo_cents"])
                  - int(q["sconto_non_rimborsabile_cents"]) - int(q["sconto_credito_cents"]))
        if int(q["prezzo_guest_cents"]) != atteso:
            return "guest %d != listino - sconti = %d" % (q["prezzo_guest_cents"], atteso)
        return ""
    r3.strategie = dict(p=P, n=st.integers(min_value=1, max_value=40),
                        sl=st.integers(min_value=0, max_value=3000), nr=st.booleans())
    corri("R3 conservazione: totale = guest + tassa, guest = listino - sconti", r3)

    # R4 — monotonia nel prezzo a notte
    def r4(p1, p2, n):
        lo, hi = min(p1, p2), max(p1, p2)
        a, b = motore(lo, notti=n), motore(hi, notti=n)
        if int(a["prezzo_guest_cents"]) > int(b["prezzo_guest_cents"]):
            return "guest(%d)=%d > guest(%d)=%d" % (lo, a["prezzo_guest_cents"], hi, b["prezzo_guest_cents"])
        if int(a["netto_host_cents"]) > int(b["netto_host_cents"]):
            return "host(%d)=%d > host(%d)=%d" % (lo, a["netto_host_cents"], hi, b["netto_host_cents"])
        return ""
    r4.strategie = dict(p1=P, p2=P, n=st.integers(min_value=1, max_value=30))
    corri("R4 monotonia: un prezzo a notte piu' alto non costa meno", r4)

    # R5 — la commissione tocca solo l'host
    def r5(p, n, sl, nr, c1, c2):
        a = motore(p, notti=n, sconto_settimana_bps=sl, non_rimborsabile=nr, commissione_bps=c1)
        b = motore(p, notti=n, sconto_settimana_bps=sl, non_rimborsabile=nr, commissione_bps=c2)
        for campo in ("prezzo_listino_cents", "sconto_soggiorno_lungo_cents",
                      "sconto_non_rimborsabile_cents", "prezzo_guest_cents",
                      "tassa_soggiorno_cents", "totale_cents", "costo_pagamento_cents"):
            if int(a[campo]) != int(b[campo]):
                return "%s cambia con la commissione (%d bps: %d, %d bps: %d)" % (
                    campo, c1, a[campo], c2, b[campo])
        d_host = int(a["netto_host_cents"]) - int(b["netto_host_cents"])
        d_comm = int(b["commissione_cents"]) - int(a["commissione_cents"])
        if d_host != d_comm:
            return "l'host cambia di %d, la commissione di %d (%d -> %d bps)" % (d_host, d_comm, c1, c2)
        return ""
    r5.strategie = dict(p=P, n=st.integers(min_value=1, max_value=30),
                        sl=st.integers(min_value=0, max_value=3000), nr=st.booleans(),
                        c1=st.sampled_from(COMMISSIONI_DI_PROVA),
                        c2=st.sampled_from(COMMISSIONI_DI_PROVA))
    corri("R5 la commissione tocca solo l'host", r5)

    # R6 — il prezzo a notte raddoppiato
    def r6(p, n, sl, nr):
        a = motore(p, notti=n, sconto_settimana_bps=sl, non_rimborsabile=nr)
        b = motore(2 * p, notti=n, sconto_settimana_bps=sl, non_rimborsabile=nr)
        if int(b["prezzo_listino_cents"]) != 2 * int(a["prezzo_listino_cents"]):
            return "listino(2p)=%d, 2 x listino(p)=%d" % (b["prezzo_listino_cents"],
                                                          2 * int(a["prezzo_listino_cents"]))
        for campo in ("sconto_soggiorno_lungo_cents", "sconto_non_rimborsabile_cents"):
            d = int(b[campo]) - 2 * int(a[campo])
            if not -1 <= d <= 1:
                return "%s(2p) - 2 x %s(p) = %d (al massimo 1 centesimo)" % (campo, campo, d)
        d = int(b["prezzo_guest_cents"]) - 2 * int(a["prezzo_guest_cents"])
        if not -2 <= d <= 1:
            return "guest(2p) - 2 x guest(p) = %d (atteso fra -2 e +1)" % d
        return ""
    r6.strategie = dict(p=st.integers(min_value=100, max_value=MAX_CENTS // 120),
                        n=st.integers(min_value=1, max_value=27),
                        sl=st.integers(min_value=0, max_value=3000), nr=st.booleans())
    corri("R6 il prezzo a notte raddoppiato raddoppia il listino, il resto entro gli arrotondamenti", r6)

    # R7 — il credito viene per ultimo e non lo paga l'host
    def r7(p, n, nr, cr):
        a = motore(p, notti=n, non_rimborsabile=nr)
        b = motore(p, notti=n, non_rimborsabile=nr, credito_cents=cr)
        for campo in ("prezzo_listino_cents", "sconto_soggiorno_lungo_cents",
                      "sconto_non_rimborsabile_cents", "prezzo_netto_cents", "commissione_cents",
                      "tassa_soggiorno_cents"):
            if int(a[campo]) != int(b[campo]):
                return "%s cambia col credito: %d -> %d" % (campo, a[campo], b[campo])
        sc = int(b["sconto_credito_cents"])
        if sc <= 0:
            return "il credito non e' entrato (sconto 0): la relazione non prova niente"
        if sc > cr or sc > int(b["commissione_cents"]):
            return "sconto %d oltre il credito %d o la commissione %d" % (
                sc, cr, b["commissione_cents"])
        if int(b["prezzo_guest_cents"]) != int(a["prezzo_guest_cents"]) - sc:
            return "guest %d -> %d, ma lo sconto e' %d" % (a["prezzo_guest_cents"],
                                                         b["prezzo_guest_cents"], sc)
        if int(b["netto_host_cents"]) < int(a["netto_host_cents"]):
            return "l'host scende col credito: %d -> %d" % (a["netto_host_cents"], b["netto_host_cents"])
        return ""
    # da 100 EUR a notte: con prezzi piccoli la commissione non lascia margine sopra il costo
    # della carta e il credito non entra (e' la guardia «mai in perdita» di fase59:506-509)
    r7.strategie = dict(p=st.integers(min_value=10000, max_value=MAX_CENTS // 60),
                        n=st.integers(min_value=1, max_value=30), nr=st.booleans(),
                        cr=st.integers(min_value=1, max_value=20000))
    corri("R7 il credito viene per ultimo e non lo paga l'host", r7)

    # le regole di tassa fra cui scelgono R8-R10: per persona per notte, percentuale, tetti
    PPN = st.integers(min_value=0, max_value=1000)
    PERC = st.integers(min_value=0, max_value=1000)
    IMP = st.integers(min_value=0, max_value=10_000_000)

    # R8 — un ospite esente in piu' non cambia la tassa
    def r8(ppn, perc, maxn, tetto, notti, ospiti, esenti, imp):
        reg = dict(per_persona_notte_cents=ppn, percentuale_bps=perc, max_notti_tassabili=maxn,
                   tetto_per_persona_soggiorno_cents=tetto)
        t1 = tassa(reg, notti=notti, ospiti=ospiti, imponibile=imp, esenti=esenti)[0]
        t2 = tassa(reg, notti=notti, ospiti=ospiti + 1, imponibile=imp, esenti=esenti + 1)[0]
        if t1 != t2:
            return "tassa %d con %d ospiti/%d esenti, %d con uno esente in piu'" % (t1, ospiti, esenti, t2)
        return ""
    r8.strategie = dict(ppn=PPN, perc=PERC, maxn=st.one_of(st.none(), st.integers(1, 30)),
                        tetto=st.one_of(st.none(), st.integers(0, 20000)),
                        notti=st.integers(1, 60), ospiti=st.integers(0, 8),
                        esenti=st.integers(0, 4), imp=IMP)
    corri("R8 un ospite esente in piu' non cambia la tassa", r8)

    # R9 — il doppio degli ospiti paganti: componente fissa esatta x2, percentuale identica
    def r9(ppn, perc, maxn, tetto, notti, ospiti, imp):
        reg = dict(per_persona_notte_cents=ppn, percentuale_bps=perc, max_notti_tassabili=maxn,
                   tetto_per_persona_soggiorno_cents=tetto)
        _t1, f1, p1 = tassa(reg, notti=notti, ospiti=ospiti, imponibile=imp)
        _t2, f2, p2 = tassa(reg, notti=notti, ospiti=2 * ospiti, imponibile=imp)
        if f2 != 2 * f1 or p2 != p1:
            return "fissa %d -> %d (atteso %d), percentuale %d -> %d" % (f1, f2, 2 * f1, p1, p2)
        return ""
    r9.strategie = dict(ppn=PPN, perc=PERC, maxn=st.one_of(st.none(), st.integers(1, 30)),
                        tetto=st.one_of(st.none(), st.integers(0, 20000)),
                        notti=st.integers(1, 60), ospiti=st.integers(1, 8), imp=IMP)
    corri("R9 il doppio degli ospiti paganti raddoppia la componente fissa della tassa", r9)

    # R10 — il doppio delle notti, DENTRO i tetti: componente fissa esatta x2, percentuale identica
    def r10(ppn, perc, notti, ospiti, imp, con_tetti):
        # i tetti, quando ci sono, stanno SOPRA il doppio: la proporzione vale solo li' sotto
        maxn = 2 * notti if con_tetti else None
        tetto = ppn * 2 * notti if con_tetti else None
        reg = dict(per_persona_notte_cents=ppn, percentuale_bps=perc, max_notti_tassabili=maxn,
                   tetto_per_persona_soggiorno_cents=tetto)
        _t1, f1, p1 = tassa(reg, notti=notti, ospiti=ospiti, imponibile=imp)
        _t2, f2, p2 = tassa(reg, notti=2 * notti, ospiti=ospiti, imponibile=imp)
        if f2 != 2 * f1 or p2 != p1:
            return "fissa %d -> %d (atteso %d), percentuale %d -> %d" % (f1, f2, 2 * f1, p1, p2)
        return ""
    r10.strategie = dict(ppn=PPN, perc=PERC, notti=st.integers(1, 30), ospiti=st.integers(1, 8),
                         imp=IMP, con_tetti=st.booleans())
    corri("R10 il doppio delle notti raddoppia la componente fissa della tassa (dentro i tetti)", r10)
    return esiti


def giudica(esiti):
    """(verde, passi, motivi, denominatore): ogni relazione e' un passo; il denominatore e' la
    somma dei casi ESEGUITI (relazioni x casi)."""
    passi, den = [], 0
    for nome, n, contro in esiti:
        den += n
        passi.append((nome + " (%d casi)" % n, n > 0 and not contro,
                      ("; ".join(contro)[:300]) if contro else ("" if n > 0 else "ZERO casi eseguiti")))
    motivi = ["%s (%s)" % (n_, d) if d else n_ for n_, ok, d in passi if not ok]
    return not motivi, passi, motivi, den


def condizione():
    blocco = [b for b in BLOCCHI if b["ordine"] == BLOCCO]
    cond = blocco[0]["finito_quando"] if len(blocco) == 1 else ()
    trovate = [c for c in cond if MARCA in str(c)]
    if len(trovate) != 1:
        raise ValueError("il Blocco %d ha %d caselle con «%s», ne serve una sola" % (BLOCCO, len(trovate), MARCA))
    return trovate[0]


# --------------------------------------------------------------------------------------
# 3. MISURA PRIMA SE STESSO (D18 punto 1)
# --------------------------------------------------------------------------------------
def precondizioni():
    fuori = []
    try:
        fuori.append(("la casella esiste nel piano, una sola", True, " ".join(str(condizione()).split())[:70]))
    except Exception as e:
        fuori.append(("la casella esiste nel piano, una sola", False, "%s: %s" % (type(e).__name__, e)))
    try:
        impronta = scheda.impronta_del_blocco(BLOCCO)
        fuori.append(("il blocco ha un'impronta", bool(impronta), impronta or "il piano non si legge"))
    except Exception as e:
        fuori.append(("il blocco ha un'impronta", False, str(e)))
    try:
        t = tariffe_di_produzione()
        fuori.append(("le tariffe si leggono da main_casavip.py", True,
                      "bps=%d fisso=%d commissione=%d" % (t["psp_bps"], t["psp_fisso"], t["commissione_bps"])))
    except Exception as e:
        fuori.append(("le tariffe si leggono da main_casavip.py", False, str(e)))
        return False, fuori
    try:
        q = motore_vero(10000, notti=1)
        fuori.append(("il motore VERO (fase59.quota) risponde 200 su 1 notte da 100 EUR", True,
                      "guest=%s totale=%s costo_pagamento=%s" % (q["prezzo_guest_cents"], q["totale_cents"],
                                                                 q["costo_pagamento_cents"])))
        nr = _tasso_nr_dichiarato(lambda *a, **k: motore_vero(*a, **k))
        fuori.append(("il motore dichiara un tasso «non rimborsabile» misurabile (bps > 0)", nr > 0, "%d bps" % nr))
        qc = motore_vero(10000, notti=1, credito_cents=100)
        fuori.append(("il gettone di credito ENTRA nel motore vero (sconto > 0 su 100 EUR)",
                      int(qc["sconto_credito_cents"]) > 0, "sconto %s" % qc["sconto_credito_cents"]))
    except Exception as e:
        fuori.append(("il motore VERO (fase59.quota) risponde 200 su 1 notte da 100 EUR", False,
                      "%s: %s" % (type(e).__name__, e)))
    try:
        t, f, p = tassa_vera(dict(per_persona_notte_cents=200, percentuale_bps=0), notti=2, ospiti=2,
                             imponibile=0)
        fuori.append(("la tassa VERA (fase66.calcola_tassa) risponde: 2 EUR x 2 notti x 2 ospiti",
                      t == f == 800 and p == 0, "tassa=%d fissa=%d percentuale=%d" % (t, f, p)))
    except Exception as e:
        fuori.append(("la tassa VERA (fase66.calcola_tassa) risponde", False, "%s: %s" % (type(e).__name__, e)))
    try:
        import hypothesis  # noqa: F401
        fuori.append(("hypothesis e' installata", True, hypothesis.__version__))
    except Exception as e:
        fuori.append(("hypothesis e' installata", False, str(e)))
    return all(ok for _, ok, _ in fuori), fuori


# --------------------------------------------------------------------------------------
# 4. L'AUTOPROVA (D18 punto 2): un motore e una tassa FINTI, sani e storti, senza toccare i veri
# --------------------------------------------------------------------------------------
def motore_finto(guasto=None, tariffe=None):
    """Un motore in miniatura con la STESSA aritmetica dichiarata da fase59 (netto = prezzo x notti,
    sconto lungo, -12% nr, commissione, credito per ultimo, tariffa tecnica). `guasto` lo storce
    apposta."""
    t = tariffe or {"psp_bps": 500, "psp_fisso": 25, "commissione_bps": 1000}

    def m(notte, *, notti, sconto_settimana_bps=0, sconto_mese_bps=0, non_rimborsabile=False,
          commissione_bps=None, credito_cents=0):
        c_bps = t["commissione_bps"] if commissione_bps is None else commissione_bps
        listino = notte * notti
        if guasto == "doppio_piu_uno" and notti >= 2:
            listino += 1
        if guasto == "ordine_inverso":
            # PRIMA il -12%, POI lo sconto lungo: e' l'ordine che R2 confronta col motore
            nr = listino * 1200 // 10000 if non_rimborsabile else 0
            dopo_nr = listino - nr
            sl = dopo_nr * sconto_settimana_bps // 10000 if notti >= 7 else 0
            netto = dopo_nr - sl
        else:
            sl = listino * sconto_settimana_bps // 10000 if notti >= 7 else 0
            netto = listino - sl
            if guasto == "nr_fisso":
                nr = 500 if non_rimborsabile else 0     # 5 EUR fissi invece del -12%
            else:
                nr = netto * 1200 // 10000 if non_rimborsabile else 0
            if guasto == "prezzo_alto_costa_meno" and notte % 2 == 1:
                nr += netto - 1                 # i prezzi dispari costano UN centesimo: non monotono
            netto -= nr
        comm = netto * c_bps // 10000
        margine = max(0, comm - (netto * 325 // 10000 + 225))
        sc = min(credito_cents, margine) if credito_cents else 0
        guest = netto - sc
        tot = guest + (comm if guasto == "commissione_all_ospite" else 0)
        costo = tot * t["psp_bps"] // 10000 + t["psp_fisso"]
        if guasto == "fisso_per_notte":
            costo += t["psp_fisso"] * (notti - 1)
        host = netto - comm - costo
        if guasto == "credito_a_carico_host":
            host -= sc
        if guasto == "sconto_a_meta":
            nr = nr // 2
        return {"prezzo_listino_cents": listino, "sconto_soggiorno_lungo_cents": sl,
                "sconto_non_rimborsabile_cents": nr, "sconto_credito_cents": sc,
                "prezzo_netto_cents": netto, "commissione_cents": comm,
                "prezzo_guest_cents": guest, "tassa_soggiorno_cents": 0, "totale_cents": tot,
                "costo_pagamento_cents": costo, "netto_host_cents": host}
    return m


def tassa_finta(guasto=None):
    """Una tassa in miniatura con la STESSA aritmetica dichiarata da fase66 (per persona per notte,
    tetto notti, tetto per persona, esenti, percentuale). `guasto` la storce apposta."""
    def t(regola, *, notti, ospiti, imponibile, esenti=0):
        maxn = regola.get("max_notti_tassabili")
        tetto = regola.get("tetto_per_persona_soggiorno_cents")
        notti_t = min(notti, maxn) if maxn is not None else notti
        paganti = ospiti if guasto == "esente_paga" else max(0, ospiti - esenti)
        if guasto == "famiglia_massimo_5":
            paganti = min(paganti, 5)
        per_persona = regola.get("per_persona_notte_cents", 0) * notti_t
        if guasto == "centesimo_a_settimana":
            per_persona += notti_t // 7
        if tetto is not None:
            per_persona = min(per_persona, tetto)
        fissa = per_persona * paganti
        perc = regola.get("percentuale_bps", 0) * imponibile // 10000
        return fissa + perc, fissa, perc
    return t


# (nome, guasto del motore, guasto della tassa, relazioni che DEVONO essere rosse: vuoto = verde)
# Ogni relazione ha il SUO guasto, che la fa gridare da sola o insieme a quelle che quel guasto
# rompe per davvero -- e il motore sano deve tacere su tutte e dieci.
CASI_AUTOPROVA = (
    ("motore e tassa finti SANI (aritmetica di fase59 e fase66)", None, None, set()),
    ("motore che sconta PRIMA il -12% (ordine inverso)", "ordine_inverso", None, {"R2"}),
    ("un centesimo in piu' sul doppio delle notti", "doppio_piu_uno", None, {"R1", "R6"}),
    ("la quota fissa addebitata PER NOTTE", "fisso_per_notte", None, {"R1b"}),
    # (e R2: quel motore DICHIARA un -6% e ne applica -12%, e R2 legge il tasso da cio' che il
    #  motore dichiara -- visto al primo giro dell'autoprova, 29/9: e' la R2 che fa il suo lavoro)
    ("il -12% dimezzato dopo il calcolo (conservazione rotta)", "sconto_a_meta", None, {"R2", "R3"}),
    # (e R7: a un centesimo la commissione e' zero, il credito non entra e R7 lo denuncia)
    ("un prezzo dispari che costa un centesimo (non monotono)", "prezzo_alto_costa_meno", None,
     {"R2", "R4", "R6", "R7"}),
    ("la commissione aggiunta al totale dell'ospite", "commissione_all_ospite", None, {"R3", "R5"}),
    ("il -12% sostituito da 5 EUR fissi", "nr_fisso", None, {"R2", "R6"}),
    ("il credito tolto anche all'host", "credito_a_carico_host", None, {"R7"}),
    ("l'ospite esente che paga lo stesso", None, "esente_paga", {"R8"}),
    ("i paganti contati al massimo fino a 5", None, "famiglia_massimo_5", {"R9"}),
    ("un centesimo in piu' ogni sette notti di tassa", None, "centesimo_a_settimana", {"R10"}),
)


def autoprova(casi_per_relazione=60, seme=1):
    t = {"psp_bps": 500, "psp_fisso": 25, "commissione_bps": 1000}
    righe, riuscita = [], True
    for nome, guasto, guasto_tassa, rosse_attese in CASI_AUTOPROVA:
        esiti = relazioni(motore_finto(guasto, t), t, casi=casi_per_relazione, seme=seme,
                          tassa=tassa_finta(guasto_tassa))
        verde, passi, motivi, den = giudica(esiti)
        rosse = set(m.split(" ")[0] for m in motivi)
        ok = (rosse == rosse_attese)
        riuscita = riuscita and ok
        righe.append("   %-58s -> rosse %-12s (attese %-12s) den %d%s" % (
            nome, ",".join(sorted(rosse)) or "-", ",".join(sorted(rosse_attese)) or "-", den,
            "" if ok else "   ⛔ NON E' QUELLO CHE DOVEVA DIRE: %s" % "; ".join(motivi)[:200]))
    return riuscita, righe


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    os.chdir(RADICE)
    casi = int(argv[argv.index("--casi") + 1]) if "--casi" in argv else CASI_DI_SERIE
    seme = int(argv[argv.index("--seme") + 1]) if "--seme" in argv else 0
    print("=" * 86)
    print("🧾 ESAME DEL BLOCCO 4 — casella «%s» (motore VERO fase59.quota, %d casi per relazione, seme %d)"
          % (MARCA, casi, seme))
    print("=" * 86)
    if "--autoprova" in argv:
        print("🔁 AUTOPROVA — le relazioni si vedono gridare e tacere su un motore FINTO (D18 punto 2)")
        riuscita, righe = autoprova()
        for r in righe:
            print(r)
        print("VERDETTO: %s" % ("✅ l'esame grida sui motori storti e tace su quello sano"
                                if riuscita else "⛔ L'ESAME NON E' AFFIDABILE"))
        return 0 if riuscita else 1
    if "--con-guasto" in argv and "--scrivi" in argv:
        print("⛔ FERMO: `--con-guasto` non scrive. Registrare un motore storto apposta e' barare.")
        return 2
    tutte_ok, righe = precondizioni()
    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    for nome, ok, motivo in righe:
        print("  %-9s %-72s %s" % ("OK" if ok else "⛔ NO", nome, motivo))
    if not tutte_ok:
        print("VERDETTO: ⛔ FERMO — una precondizione non regge: NON misuro e NON scrivo.")
        return 2
    tariffe = tariffe_di_produzione()
    motore = motore_vero
    if "--con-guasto" in argv:
        print("⚠️  PASSATA COL GUASTO DENTRO: il motore vero, piu' un centesimo sul doppio delle notti")
        vero = motore_vero

        def motore(notte, **kw):
            q = vero(notte, **kw)
            if kw.get("notti", 1) >= 2:
                q["prezzo_listino_cents"] = int(q["prezzo_listino_cents"]) + 1
            return q
    esiti = relazioni(lambda *a, **k: motore(*a, tariffe=tariffe, **k) if motore is motore_vero
                      else motore(*a, **k), tariffe, casi=casi, seme=seme)
    verde, passi, motivi, den = giudica(esiti)
    print("")
    for nome, ok, dettaglio in passi:
        print("  %s  %s%s" % ("OK  " if ok else "ROSSO", nome, ("  -> " + dettaglio) if dettaglio else ""))
    print("")
    print("VERDETTO: %s — %d relazioni su %d, denominatore %d (relazioni x casi)"
          % ("✅ VERDE" if verde else "⛔ ROSSO", sum(1 for _n, ok, _d in passi if ok), len(passi), den))
    if motivi:
        print("   perche': %s" % "; ".join(motivi)[:600])
    if "--scrivi" in argv:
        riga = scheda.registra(condizione(), esito=verde, denominatore=den, comando=COMANDO,
                               ordine=BLOCCO, motivo="; ".join(motivi)[:900] or None)
        print("  SCRITTA nella scheda: blocco %d · esito %s · denominatore %d · impronta %s"
              % (riga["blocco"], riga["esito"], riga["denominatore"], riga["impronta"]))
    else:
        print("(non ho scritto niente: aggiungi --scrivi per registrare nella scheda)")
    print("-" * 86)
    print("⛔ COSA QUESTO ESAME NON HA ESAMINATO (D18 punto 3)")
    for r in NON_GUARDA:
        print("   · %s" % r)
    print("=" * 86)
    return 0 if verde else 1


if __name__ == "__main__":
    sys.exit(main())
