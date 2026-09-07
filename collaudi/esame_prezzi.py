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
soggiorno lungo dal catalogo, sconto «non rimborsabile», commissione all'host, tassa, tariffa
tecnica); `fase44_prezzo` e `fase45_pricing` sono del vecchio stack e nessun modulo di produzione li
importa (`grep -rln fase44_prezzo|fase45_pricing` -> solo fase45 stesso). Qui il concierge e' quello
VERO, con un inventario e un catalogo in memoria che rispondono solo «prezzo a notte», «valuta»,
«sconto lungo», «politica»; le tariffe (PAGAMENTO_BPS, PAGAMENTO_FISSO_CENTS, COMMISSIONE_BPS) si
LEGGONO da `main_casavip.py`, mai ricopiate (S17, D22).

LE RELAZIONI (D25: T.Y. Chen, S.C. Cheung, S.M. Yiu, «Metamorphic Testing: A New Approach for
Generating Next Test Cases», HKUST-CS98-01, 1998 — una relazione lega due esecuzioni imparentate,
non un valore atteso; Segura, Fraser, Sanchez, Ruiz-Cortes, «A Survey on Metamorphic Testing»,
IEEE TSE 42(9), 2016 — relazioni additive/moltiplicative/inclusive e la loro forza nel trovare
difetti dove un oracolo non c'e'). I casi li genera Hypothesis (seme fisso: riproducibile), il
denominatore e' relazioni x casi:

  R1  «raddoppiare le notti raddoppia la parte fissa» — MOLTIPLICATIVA: con lo stesso prezzo a notte,
      2n notti danno ESATTAMENTE 2x `prezzo_listino_cents` (la parte del prezzo che dipende solo
      dalle notti, prima di sconti e tariffe). Vale nella stessa fascia di sconto (n e 2n entrambi
      sotto 7, o entrambi fra 7 e 27).
  R1b la QUOTA FISSA della tariffa tecnica NON raddoppia: `costo_pagamento - floor(totale*bps/10000)`
      vale sempre PAGAMENTO_FISSO_CENTS, a 1 notte come a 60 (e' per transazione, non per notte).
  R2  «l'ordine degli sconti non cambia il totale» — il motore applica PRIMA lo sconto soggiorno
      lungo e POI il -12% «non rimborsabile» (fase59:296-312). Si misura se l'ordine inverso
      (prima -12%, poi lo sconto lungo), calcolato coi TASSI CHE IL MOTORE STESSO DICHIARA nelle
      sue uscite, da' lo stesso `prezzo_guest_cents`. ⚠️ Con la divisione intera i due ordini
      POSSONO differire di un centesimo: se succede, questo esame lo CONTA e lo scrive; non e' la
      relazione a essere sbagliata, e' cio' che il motore fa davvero, e lo decide il fondatore.
  R3  CONSERVAZIONE (invariante, non metamorfica, ma costa zero): `totale = guest + tassa` e
      `guest = listino - sconto_lungo - sconto_non_rimborsabile`.
  R4  MONOTONIA: a notti uguali, un prezzo a notte piu' alto non fa pagare di meno l'ospite ne'
      incassare di piu' l'host per notte in meno.

⛔ D18: precondizioni (la casella esiste una sola; il motore vero si costruisce; le tariffe si leggono
   da main_casavip; il -12% dichiarato dal motore su 100 EUR e' misurato, non creduto); --autoprova
   nelle due direzioni su un motore FINTO che sbaglia apposta; NON_GUARDA; guardia in
   `test_esame_prezzi.py`.
"""
import io
import os
import re
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
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

NON_GUARDA = (
    "la TASSA di soggiorno: il motore la chiede a una regola dell'host (`tassa_alloggio`); qui e' 0, "
    "perche' provarla vorrebbe dire provare uno stub scritto da me (la copre test_fase66/147)",
    "il CREDITO fondatore e la valuta ESTERA: relazioni gia' in test_property_soldi (MR3) e nei "
    "dedicati; qui il motore gira in EUR senza credito",
    "il calendario dei prezzi variabili (fase119): qui ogni notte ha lo STESSO prezzo, perche' R1 "
    "ha senso solo cosi'; con prezzi diversi per notte la «parte fissa» e' la somma, non il doppio",
    "i rimborsi, gli split e la «paga in struttura»: hanno le loro relazioni in test_property_soldi "
    "(MR5-MR12)",
    "che la scelta «prima lo sconto lungo, poi il -12%» sia quella GIUSTA: qui si misura solo se "
    "l'ordine inverso cambia i centesimi",
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
                non_rimborsabile=False, tariffe=None):
    """UNA quota del concierge VERO: torna il dizionario firmato (il corpo della risposta)."""
    from fase59_concierge import FirmaQuote, ProtocolloConcierge
    t = tariffe or tariffe_di_produzione()
    p = ProtocolloConcierge(
        _Inv(notte_cents), FirmaQuote(b"e" * 32),
        catalogo=_Cat(sconto_settimana_bps, sconto_mese_bps,
                      "non_rimborsabile" if non_rimborsabile else "flessibile"),
        commissione=lambda netto: netto * t["commissione_bps"] // 10000,
        psp_bps=t["psp_bps"], psp_fisso_cents=t["psp_fisso"])
    r = p.quota({"alloggio_id": SLUG, "check_in": CI, "check_out": _co(notti), "party": 2})
    if r.status != 200:
        raise ValueError("quota non riuscita: %s %s" % (r.status, r.corpo))
    return dict(r.corpo)


def tariffe_di_produzione():
    return {"psp_bps": default_di_produzione("PAGAMENTO_BPS"),
            "psp_fisso": default_di_produzione("PAGAMENTO_FISSO_CENTS"),
            "commissione_bps": default_di_produzione("COMMISSIONE_BPS")}


# --------------------------------------------------------------------------------------
# 2. LE RELAZIONI (pure: ricevono un `motore(notte, notti=..., ...)` e rendono un esito)
# --------------------------------------------------------------------------------------
def _tasso_nr_dichiarato(motore):
    """Il -12% «non rimborsabile» non si copia: si LEGGE da cio' che il motore fa su 1 notte da
    100 EUR senza sconto lungo (sconto_nr / listino, in bps)."""
    q = motore(10000, notti=1, non_rimborsabile=True)
    return int(q["sconto_non_rimborsabile_cents"]) * 10000 // int(q["prezzo_listino_cents"])


def relazioni(motore, tariffe, *, casi=CASI_DI_SERIE, seme=0):
    """Esegue R1, R1b, R2, R3, R4 con Hypothesis. Torna [(nome, casi_eseguiti, contro_esempi)]."""
    from hypothesis import given, settings, strategies as st, HealthCheck, seed
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

    # R2 — l'ordine degli sconti: motore (lungo poi -12%) contro l'ordine inverso
    def r2(p, n, sl):
        q = motore(p, notti=n, sconto_settimana_bps=sl, non_rimborsabile=True)
        L = int(q["prezzo_listino_cents"])
        dopo_nr = L - L * nr_bps // 10000
        inverso = dopo_nr - dopo_nr * sl // 10000
        if int(q["prezzo_guest_cents"]) != inverso:
            return "motore (lungo %d bps poi -%d bps) = %d; ordine inverso = %d; listino %d" % (
                sl, nr_bps, q["prezzo_guest_cents"], inverso, L)
        return ""
    r2.strategie = dict(p=P, n=st.integers(min_value=7, max_value=27),
                        sl=st.integers(min_value=1, max_value=3000))
    corri("R2 l'ordine degli sconti non cambia il totale", r2)

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
    except Exception as e:
        fuori.append(("il motore VERO (fase59.quota) risponde 200 su 1 notte da 100 EUR", False,
                      "%s: %s" % (type(e).__name__, e)))
    try:
        import hypothesis  # noqa: F401
        fuori.append(("hypothesis e' installata", True, hypothesis.__version__))
    except Exception as e:
        fuori.append(("hypothesis e' installata", False, str(e)))
    return all(ok for _, ok, _ in fuori), fuori


# --------------------------------------------------------------------------------------
# 4. L'AUTOPROVA (D18 punto 2): un motore FINTO, sano e storto, senza toccare quello vero
# --------------------------------------------------------------------------------------
def motore_finto(guasto=None, tariffe=None):
    """Un motore in miniatura con la STESSA aritmetica dichiarata da fase59 (netto = prezzo x notti,
    sconto lungo, -12% nr, commissione, tariffa tecnica). `guasto` lo storce apposta."""
    t = tariffe or {"psp_bps": 500, "psp_fisso": 25, "commissione_bps": 1000}

    def m(notte, *, notti, sconto_settimana_bps=0, sconto_mese_bps=0, non_rimborsabile=False):
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
            nr = netto * 1200 // 10000 if non_rimborsabile else 0
            if guasto == "prezzo_alto_costa_meno" and notte % 2 == 1:
                nr += netto - 1                 # i prezzi dispari costano UN centesimo: non monotono
            netto -= nr
        comm = netto * t["commissione_bps"] // 10000
        tot = netto
        costo = tot * t["psp_bps"] // 10000 + t["psp_fisso"]
        if guasto == "fisso_per_notte":
            costo += t["psp_fisso"] * (notti - 1)
        if guasto == "sconto_a_meta":
            nr = nr // 2
        return {"prezzo_listino_cents": listino, "sconto_soggiorno_lungo_cents": sl,
                "sconto_non_rimborsabile_cents": nr, "sconto_credito_cents": 0,
                "prezzo_guest_cents": netto, "tassa_soggiorno_cents": 0, "totale_cents": tot,
                "costo_pagamento_cents": costo, "netto_host_cents": netto - comm - costo}
    return m


def autoprova():
    t = {"psp_bps": 500, "psp_fisso": 25, "commissione_bps": 1000}
    # (nome, guasto, relazioni che DEVONO essere rosse: insieme vuoto = tutto verde)
    # ⛔ Il motore finto «SANO» copia l'aritmetica di fase59 (lungo, POI -12%, divisione intera):
    #    R2 e' ROSSA anche su di lui, perche' con la divisione intera l'ordine cambia i centesimi.
    #    Non e' l'attrezzo a sbagliare: e' cio' che quell'aritmetica fa. La direzione VERDE di R2
    #    la mostra il motore «ordine inverso» (sconta PRIMA il -12%): li' R2 tace.
    casi = (("motore finto SANO (aritmetica di fase59)", None, {"R2"}),
            ("motore che sconta PRIMA il -12% (ordine inverso)", "ordine_inverso", set()),
            ("un centesimo in piu' sul doppio delle notti", "doppio_piu_uno", {"R1", "R2"}),
            ("la quota fissa addebitata PER NOTTE", "fisso_per_notte", {"R1b", "R2"}),
            ("il -12% dimezzato dopo il calcolo (conservazione rotta)", "sconto_a_meta", {"R3", "R2"}),
            ("un prezzo dispari che costa un centesimo (non monotono)", "prezzo_alto_costa_meno", {"R4", "R2"}))
    righe, riuscita = [], True
    for nome, guasto, rosse_attese in casi:
        esiti = relazioni(motore_finto(guasto, t), t, casi=60, seme=1)
        verde, passi, motivi, den = giudica(esiti)
        rosse = set(m.split(" ")[0] for m in motivi)
        ok = (rosse == rosse_attese)
        riuscita = riuscita and ok
        righe.append("   %-52s -> rosse %-16s (attese %-16s) den %d%s" % (
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
