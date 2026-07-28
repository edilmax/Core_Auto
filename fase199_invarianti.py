"""
CORE_AUTO - Fase 199: MOTORE DEGLI INVARIANTI FORMALI — le leggi che NON devono MAI essere violate.

Un invariante è una verità matematica sullo stato del sistema. Qui li codifichiamo come funzioni
PURE e verificabili, così possono servire a tre scopi:
  (a) GUARDIA pre-commit  — `guardia_prenotazione` blocca un'operazione PRIMA che tocchi il DB se
      creerebbe una violazione (es. doppia conferma sovrapposta);
  (b) AUDITOR continuo    — `scansiona_db` legge i DB reali e GRIDA se trova una violazione (oracolo
      indipendente, come il guardiano fase186: non ripara, denuncia);
  (c) PROVA formale       — le funzioni pure sono verificate da test property-based (Hypothesis):
      migliaia di stati generati a caso, un oracolo indipendente ricalcola → dimostrazione empirica.

INVARIANTI (dal dominio + richiesti dal fondatore):
  I1  NO DOPPIA CONFERMA: due prenotazioni OCCUPANTI non si sovrappongono sulla stessa unità.
  I2  BILANCIO PAGAMENTI: la somma dei pagamenti non supera MAI il dovuto; se saldato, la eguaglia
      (nessun pagamento negativo, nessun overpay — l'importo lo detta il ledger).
  I3  PROVA PRIMA DEL COMMIT: nessuna prenotazione confermata senza prova firmata (quote_token HMAC
      + consenso registrato). [NB: la macchina NON conserva PII documentale (KYC delegato) → l'analogo
      di "cifratura PII applicata" qui è "prova firmata presente".]
  I4  DENARO MAI NEGATIVO: nessun importo (incasso, payout, credito, cauzione) è negativo.
  I5  ESCROW COERENTE: una garanzia 'rilasciato'/'trattenuto' esige un esito che lo giustifica.

Puro, stdlib, deterministico. Intervalli date = semiaperti [check_in, check_out).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

# Stati che OCCUPANO davvero il calendario (una conferma e oltre). Tentativi/annullati NON occupano.
STATI_OCCUPANTI = frozenset({"confermata", "pagato", "maturato", "in_transito",
                             "checkin", "checkout", "completata"})
# Stati in cui la prenotazione è "confermata" e quindi ESIGE una prova firmata.
STATI_CONFERMATI = STATI_OCCUPANTI
# Stati in cui il soggiorno e' SALDATO: la somma pagata deve corrispondere ESATTAMENTE al dovuto.
STATI_SALDATI = frozenset({"pagato", "maturato", "in_transito", "completata"})


class ViolazioneInvariante(Exception):
    """Sollevata dalla guardia pre-commit: l'operazione violerebbe un invariante → NON procede."""

    def __init__(self, codice: str, dettaglio: str) -> None:
        super().__init__("%s: %s" % (codice, dettaglio))
        self.codice = codice
        self.dettaglio = dettaglio


# ── NUCLEI PURI DELLE REGOLE ────────────────────────────────────────────────────────
# Scritti con & | (non and/or) perche' la STESSA espressione valga sia sui bool di Python
# sia sulle espressioni simboliche di Z3. Cosi' `dimostra_formalmente` non ri-scrive a mano
# le formule (che sarebbe un ornamento: si dimostrerebbe la copia, non il codice) ma dimostra
# ESATTAMENTE il predicato che gira in produzione. Rompere un nucleo => la prova cade.
def _sovrappone_expr(ci1: Any, co1: Any, ci2: Any, co2: Any) -> Any:
    """Nucleo di I1: due intervalli semiaperti [ci,co) condividono almeno una notte?"""
    return (ci1 < co2) & (ci2 < co1)


def _i2_viola_expr(somma: Any, dovuto: Any, saldato: Any) -> Any:
    """Nucleo di I2: il conto e' fuori norma? (pagato piu' del dovuto, oppure saldato ma non esatto)."""
    return (somma > dovuto) | (saldato & (somma != dovuto))


def _i3_viola_expr(confermata: Any, prova_firmata: Any) -> Any:
    """Nucleo di I3: prenotazione CONFERMATA senza prova firmata?"""
    return confermata & (prova_firmata == False)   # noqa: E712 - '== False' vale anche su Z3


def _sovrappone(ci1: Any, co1: Any, ci2: Any, co2: Any) -> bool:
    """Due intervalli semiaperti [ci,co) si sovrappongono? (confini che si toccano = OK, non overlap)."""
    return bool(_sovrappone_expr(ci1, co1, ci2, co2))


# ── I1: nessuna doppia conferma sovrapposta sulla stessa unità ──────────────────────
def i1_doppia_conferma(prenotazioni: Sequence[Dict[str, Any]]) -> List[Tuple[Any, Any, Any]]:
    """Ritorna le coppie (unità, rifA, rifB) che si sovrappongono fra prenotazioni OCCUPANTI.
    Lista vuota = invariante rispettato."""
    conf = [p for p in prenotazioni if p.get("stato") in STATI_OCCUPANTI]
    per_unita: Dict[Any, List[Dict[str, Any]]] = {}
    for p in conf:
        per_unita.setdefault(p.get("unita", p.get("alloggio_id")), []).append(p)
    viol: List[Tuple[Any, Any, Any]] = []
    for unita, ps in per_unita.items():
        ps = sorted(ps, key=lambda p: (str(p.get("check_in")), str(p.get("check_out"))))
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                if _sovrappone(ps[i].get("check_in"), ps[i].get("check_out"),
                               ps[j].get("check_in"), ps[j].get("check_out")):
                    viol.append((unita, ps[i].get("rif"), ps[j].get("rif")))
    return viol


# ── I2: bilancio dei pagamenti (nessun overpay, nessun negativo; se saldato, esatto) ─
def i2_bilancio_pagamenti(prenotazioni: Sequence[Dict[str, Any]]) -> List[Tuple[Any, str]]:
    """Per ogni prenotazione: pagamenti >= 0, somma <= dovuto; se stato saldato, somma == dovuto."""
    viol: List[Tuple[Any, str]] = []
    for p in prenotazioni:
        rif = p.get("rif")
        dovuto = p.get("totale_dovuto_cents", 0)
        pagamenti = p.get("pagamenti_cents", []) or []
        if any((not isinstance(x, int)) or isinstance(x, bool) or x < 0 for x in pagamenti):
            viol.append((rif, "pagamento negativo o non intero"))
            continue
        s = sum(pagamenti)
        if not isinstance(dovuto, int) or isinstance(dovuto, bool) or dovuto < 0:
            viol.append((rif, "totale dovuto negativo/non intero"))
            continue
        saldato = p.get("stato") in STATI_SALDATI
        if _i2_viola_expr(s, dovuto, saldato):          # <- il nucleo dimostrato con Z3
            viol.append((rif, "OVERPAY: pagato %d > dovuto %d" % (s, dovuto) if s > dovuto
                         else "saldato ma somma %d != dovuto %d" % (s, dovuto)))
    return viol


# ── I3: nessuna conferma senza prova firmata ────────────────────────────────────────
def i3_prova_prima_del_commit(prenotazioni: Sequence[Dict[str, Any]]) -> List[Any]:
    """Ritorna i riferimenti delle prenotazioni CONFERMATE senza prova firmata (quote_token/consenso)."""
    return [p.get("rif") for p in prenotazioni
            if _i3_viola_expr(p.get("stato") in STATI_CONFERMATI,   # <- il nucleo dimostrato con Z3
                              bool(p.get("prova_firmata")))]


# ── I4: nessun importo negativo ─────────────────────────────────────────────────────
def i4_denaro_non_negativo(importi: Dict[str, Any]) -> List[Tuple[str, Any]]:
    """`importi`: mappa nome->valore(cents). Ritorna i nomi con valore negativo."""
    return [(k, v) for k, v in (importi or {}).items()
            if isinstance(v, int) and not isinstance(v, bool) and v < 0]


# ── I5: escrow coerente col suo esito ───────────────────────────────────────────────
def i5_escrow_coerente(garanzie: Sequence[Dict[str, Any]]) -> List[Tuple[Any, str]]:
    """Una garanzia 'rilasciato' esige una prenotazione conclusa (checkout/completata/cancellata/
    rimborsata); 'trattenuto' esige un esito che lo giustifica (contestata/danno)."""
    ok_rilascio = {"checkout", "completata", "cancellata", "cancellata_host", "rimborsata"}
    ok_trattenuto = {"contestata", "danno", "trattenuto"}
    viol: List[Tuple[Any, str]] = []
    for g in garanzie:
        st = g.get("stato_garanzia")
        esito = g.get("esito_prenotazione")
        if st == "rilasciato" and esito not in ok_rilascio:
            viol.append((g.get("rif"), "garanzia rilasciata senza esito valido: %r" % esito))
        if st == "trattenuto" and esito not in ok_trattenuto:
            viol.append((g.get("rif"), "garanzia trattenuta senza giustificazione: %r" % esito))
    return viol


# ── GUARDIA pre-commit: blocca PRIMA di scrivere ────────────────────────────────────
def guardia_prenotazione(nuova: Dict[str, Any],
                         esistenti: Sequence[Dict[str, Any]]) -> None:
    """Da chiamare PRIMA di confermare/scrivere una prenotazione: se creerebbe una violazione
    (I1/I2/I3) solleva ViolazioneInvariante → l'operazione NON tocca il DB. Idempotente e puro."""
    if nuova.get("stato") in STATI_OCCUPANTI:
        v = i1_doppia_conferma(list(esistenti) + [nuova])
        if v:
            raise ViolazioneInvariante("I1_DOPPIA_CONFERMA",
                                       "sovrapposizione su unità %r" % (v[0][0],))
    v2 = i2_bilancio_pagamenti([nuova])
    if v2:
        raise ViolazioneInvariante("I2_BILANCIO", v2[0][1])
    v3 = i3_prova_prima_del_commit([nuova])
    if v3:
        raise ViolazioneInvariante("I3_PROVA", "conferma senza prova firmata: %r" % v3[0])


def verifica_stato(prenotazioni: Sequence[Dict[str, Any]] = (),
                   garanzie: Sequence[Dict[str, Any]] = (),
                   importi: Optional[Dict[str, Any]] = None) -> Dict[str, List[Any]]:
    """Verifica TUTTI gli invarianti su uno stato astratto. Ritorna {codice: [violazioni]} (vuoto = OK)."""
    out = {
        "I1_DOPPIA_CONFERMA": i1_doppia_conferma(prenotazioni),
        "I2_BILANCIO": i2_bilancio_pagamenti(prenotazioni),
        "I3_PROVA": i3_prova_prima_del_commit(prenotazioni),
        "I4_NEGATIVO": i4_denaro_non_negativo(importi or {}),
        "I5_ESCROW": i5_escrow_coerente(garanzie),
    }
    return {k: v for k, v in out.items() if v}


def scansiona_db(percorso_dir: str) -> Dict[str, Any]:
    """AUDITOR: legge i DB reali (best-effort, schema-tollerante) e verifica gli invarianti.
    Non solleva mai (come il guardiano): ritorna un rapporto {violazioni, letti}. GRIDA nei log."""
    import glob
    import logging
    import os
    import sqlite3
    logger = logging.getLogger("core_auto.invarianti")
    prenotazioni: List[Dict[str, Any]] = []
    letti = 0
    for f in glob.glob(os.path.join(percorso_dir, "*.db")):
        try:
            # timeout=30 (standard, bug #36): l'auditor gira CONTRO i DB vivi di produzione,
            # in concorrenza col sito -> sotto contesa ASPETTA il turno, mai 'database is locked'.
            con = sqlite3.connect(f, timeout=30)
            tab = [t[0] for t in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
            for t in tab:
                cols = [c[1] for c in con.execute("PRAGMA table_info(%s)" % t)]
                if "check_in" in cols and "check_out" in cols and "stato" in cols:
                    uni = "alloggio_id" if "alloggio_id" in cols else (
                        "unita" if "unita" in cols else None)
                    q = "SELECT stato, check_in, check_out%s FROM %s" % (
                        (", " + uni) if uni else "", t)
                    for r in con.execute(q):
                        prenotazioni.append({"stato": r[0], "check_in": r[1], "check_out": r[2],
                                             "unita": r[3] if uni else t, "rif": None,
                                             "prova_firmata": True})
                        letti += 1
            con.close()
        except Exception:
            logger.warning("invarianti: DB illeggibile (ISOLATO): %s", f, exc_info=True)
    viol = {"I1_DOPPIA_CONFERMA": i1_doppia_conferma(prenotazioni)}
    viol = {k: v for k, v in viol.items() if v}
    if viol:
        logger.error("INVARIANTI VIOLATI in produzione: %r", {k: len(v) for k, v in viol.items()})
    return {"violazioni": viol, "prenotazioni_lette": letti}


# ── DIMOSTRAZIONE FORMALE (Z3/SMT): non "tanti casi" ma TUTTI gli infiniti casi (∀) ──
def dimostra_formalmente() -> Dict[str, str]:
    """Prova matematica UNIVERSALE degli invarianti critici con Z3: per OGNI intero (non un campione),
    cerca un controesempio; UNSAT = teorema DIMOSTRATO. Copre: Zero-Double-Booking, Atomicità
    Finanziaria, Isolamento PII. Ritorna {invariante: 'DIMOSTRATO'|'CONTROESEMPIO...'|'z3 assente'}."""
    try:
        import z3
    except Exception:
        return {"disponibile": "z3 assente"}

    def _teorema(nome, vincoli, tesi):
        """Prova che (vincoli ⟹ tesi) per OGNI intero: cerca un controesempio (vincoli ∧ ¬tesi)."""
        s = z3.Solver()
        s.add(vincoli)
        s.add(z3.Not(tesi))
        esito = s.check()
        return (nome, "DIMOSTRATO" if esito == z3.unsat
                else ("CONTROESEMPIO %s" % s.model() if esito == z3.sat else "INDETERMINATO"))

    ris: Dict[str, str] = {}

    # ATTENZIONE (lezione del 2026-07-28): questi teoremi NON ri-scrivono le formule a mano.
    # Chiamano i NUCLEI VERI usati dai checker (_sovrappone_expr / _i2_viola_expr /
    # _i3_viola_expr) e li confrontano con una specifica scritta in modo INDIPENDENTE.
    # Prima lo facevano con copie inline: rompendo il codice di produzione la "dimostrazione"
    # restava verde (I2 era addirittura una tautologia, A∧B ⟹ B). Un teorema che non puo'
    # cadere non e' una prova: e' un ornamento.

    # I1 — ZERO DOUBLE-BOOKING: il predicato di sovrapposizione DI PRODUZIONE è ESATTAMENTE
    # "gli intervalli semiaperti condividono una notte" (max(inizio) < min(fine)):
    # nessun overlap sfugge (completezza) e nessuno è inventato (correttezza).
    a1, a2, b1, b2 = z3.Ints("a1 a2 b1 b2")
    mx = z3.If(a1 > b1, a1, b1)
    mn = z3.If(a2 < b2, a2, b2)
    predicato_guardia = _sovrappone_expr(a1, a2, b1, b2)   # ← il codice VERO, non una copia
    condivide_notte = mx < mn                              # ← specifica indipendente
    nome, esito = _teorema("I1_zero_double_booking",
                           z3.And(a1 < a2, b1 < b2),       # intervalli validi
                           predicato_guardia == condivide_notte)
    ris[nome] = esito

    # I2 — ATOMICITÀ FINANZIARIA: la regola VERA segnala violazione esattamente quando il conto
    # NON è sano, dove "sano" è definito a parte: mai pagato più del dovuto e, se saldato,
    # somma == dovuto al centesimo. Se la regola smettesse di vedere un overpay (o ne inventasse
    # uno), l'equivalenza cadrebbe e Z3 stamperebbe il controesempio.
    S, D = z3.Ints("S D")                                  # S = somma pagamenti, D = dovuto
    saldato = z3.Bool("saldato")
    viola_vera = _i2_viola_expr(S, D, saldato)             # ← il codice VERO
    sano = z3.And(S <= D, z3.Implies(saldato, S == D))     # ← specifica indipendente
    nome, esito = _teorema("I2_atomicita_finanziaria",
                           z3.And(S >= 0, D >= 0),
                           viola_vera == z3.Not(sano))
    ris[nome] = esito

    # I3 — ISOLAMENTO PII / PROVA-PRIMA-DEL-COMMIT: la regola VERA blocca esattamente le
    # prenotazioni confermate senza prova firmata; e ciò che passa, se è confermato, la prova
    # ce l'ha per forza (nessuna conferma può sfuggire al controllo).
    confermata, prova = z3.Bools("confermata prova")
    bloccato = _i3_viola_expr(confermata, prova)           # ← il codice VERO
    nome, esito = _teorema("I3_isolamento_pii",
                           z3.BoolVal(True),
                           z3.And(bloccato == z3.And(confermata, z3.Not(prova)),
                                  z3.Implies(z3.And(confermata, z3.Not(bloccato)), prova)))
    ris[nome] = esito
    return ris


# ═════════════════════════════════════════════════════════════════════════════════════
# MACCHINE A STATI DEL DOMINIO — modelli formali + teoremi Z3 sulle TRANSIZIONI.
#
# Il modello NON è un disegno a mano: è lo SPECCHIO dei guardi CAS reali, e la concordanza
# modello<->codice vero è essa stessa una guardia (test_fase199_transizioni pilota il DB
# REALE su TUTTI gli stati x TUTTI gli eventi e pretende la stessa relazione):
#   - PRENOTAZIONE: fase162_pagamenti_pendenti — le 4 scritture di stato sono tutte CAS SQL
#     (`conferma` solo da in_attesa/scaduto; `scadi` solo da in_attesa/in_attesa_host;
#     `marca_da_rimborsare`/`marca_cancellata_host` mai da un record già chiuso);
#   - PAYOUT: fase131_payout_dashboard._TRANSIZIONI — tabella esplicita, letta DIRETTAMENTE
#     dalla produzione dentro `dimostra_transizioni` (non una copia: se la tabella cambia,
#     i teoremi si ri-verificano su quella nuova);
#   - ESCROW: fase160_escrow_garanzia — le formule di split sono riscritte QUI una volta sola
#     in forma "selettore" (`se`), usabile sia con if concreti (concordanza col codice vero)
#     sia con z3.If (dimostrazione universale ∀ intero, non campionata).
# ═════════════════════════════════════════════════════════════════════════════════════

# ── PRENOTAZIONE (fase162): eventi = (nome, stati sorgente ammessi, stato target) ────
# Specchio ESATTO delle whitelist CAS SQL. `registra` crea in_attesa/in_attesa_host;
# le rimozioni (rimuovi/pulisci_vecchi) escono dalla macchina, non sono transizioni.
STATI_PRENOTAZIONE = ("in_attesa", "in_attesa_host", "scaduto", "pagato",
                      "rimborsato", "cancellata_host")
EVENTI_PRENOTAZIONE = (
    # webhook Stripe "pagamento riuscito": SOLO da hold vivo o scaduto (pagamento tardivo)
    ("conferma", ("in_attesa", "scaduto"), "pagato"),
    # sweeper: l'hold/richiesta non pagata scade
    ("scadi", ("in_attesa", "in_attesa_host"), "scaduto"),
    # rimborso: MAI retrocede un record già chiuso (cancellata_host/rimborsato)
    ("marca_da_rimborsare", ("in_attesa", "in_attesa_host", "scaduto", "pagato"),
     "rimborsato"),
    # cancellazione host con penale: idem, mai da un record già chiuso
    ("marca_cancellata_host", ("in_attesa", "in_attesa_host", "scaduto", "pagato"),
     "cancellata_host"),
)
# Stati terminali NEGATIVI: da qui NESSUN cammino deve mai portare a 'pagato'.
TERMINALI_NEGATIVI_PRENOTAZIONE = ("rimborsato", "cancellata_host")
# Rango di pipeline: ogni transizione legale deve SALIRE (aciclicità dimostrata con Z3).
RANGO_PRENOTAZIONE = {"in_attesa": 0, "in_attesa_host": 0, "scaduto": 1, "pagato": 2,
                      "rimborsato": 3, "cancellata_host": 3}

# ── PAYOUT (fase131): rango di pipeline. in_transito e trattenuto sono lo STESSO passo
# (bonifico in corso / bonifico sospeso da hold DAC7-disputa): la coppia hold è l'UNICO
# movimento laterale ammesso; tutto il resto deve salire. ────────────────────────────
RANGO_PAYOUT = {"in_attesa": 0, "maturato": 1, "in_transito": 2, "trattenuto": 2,
                "pagato": 3}
COPPIA_HOLD_PAYOUT = ("in_transito", "trattenuto")


def transizioni_prenotazione() -> Dict[str, set]:
    """La relazione di transizione {stato: {successori}} DERIVATA dagli eventi (una sola
    fonte di verità nel modello). Auto-anelli esclusi (un CAS verso lo stesso stato è no-op)."""
    tab: Dict[str, set] = {s: set() for s in STATI_PRENOTAZIONE}
    for _nome, sorgenti, target in EVENTI_PRENOTAZIONE:
        for s in sorgenti:
            if s != target:
                tab[s].add(target)
    return tab


def _se_concreto(cond: Any, a: Any, b: Any) -> Any:
    return a if cond else b


def formula_split_risolvi(importo: Any, richiesto: Any, se: Any = _se_concreto) -> Tuple[Any, Any]:
    """SPECCHIO di fase160.risolvi (interi): rimb = min(_cent(richiesto), importo);
    host = importo - rimb. Ritorna (host, rimborso). Con se=z3.If diventa simbolica."""
    rimb = se(richiesto >= 0, richiesto, 0)        # _cent: i negativi diventano 0
    rimb = se(rimb <= importo, rimb, importo)      # min(., importo): il clamp
    return importo - rimb, rimb


def formula_split_proporzionale(importo: Any, host_chiesto: Any,
                                se: Any = _se_concreto) -> Tuple[Any, Any]:
    """SPECCHIO di fase160.chiudi_proporzionale (interi): host = max(0, min(_cent(x), importo));
    rimborso = importo - host. Ritorna (host, rimborso)."""
    h = se(host_chiesto >= 0, host_chiesto, 0)     # _cent
    h = se(h <= importo, h, importo)               # min(., importo)
    h = se(h >= 0, h, 0)                           # max(0, .) — fedele al codice, riga per riga
    return h, importo - h


def dimostra_transizioni() -> Dict[str, str]:
    """TEOREMI Z3 sulle TRANSIZIONI DI STATO del dominio (UNSAT del controesempio = teorema):

    PRENOTAZIONE (modello = specchio dei CAS fase162, concordanza collaudata sul DB vero):
      - PREN_terminale_assorbente     : da rimborsato/cancellata_host NESSUNA transizione esce;
      - PREN_mai_pagato_da_terminale  : nessun CAMMINO (qualsiasi lunghezza: bound n-1 passi
                                        con stutter = raggiungibilità completa su n stati)
                                        porta da un terminale negativo a 'pagato';
      - PREN_pagato_solo_da_pagabili  : 'pagato' si raggiunge SOLO da in_attesa/scaduto;
      - PREN_monotona_senza_cicli     : ogni transizione SALE di rango (⇒ grafo aciclico).
    PAYOUT (tabella _TRANSIZIONI letta DIRETTAMENTE dalla produzione fase131):
      - PAY_pagato_assorbente         : da 'pagato' (soldi partiti e arrivati) non si esce;
      - PAY_mai_ritorno_in_coda       : nulla rientra in 'in_attesa'; 'maturato' solo da 'in_attesa';
      - PAY_monotono_mai_indietro     : il rango di pipeline non scende MAI;
      - PAY_cicli_solo_coppia_hold    : ogni movimento a rango costante è dentro la coppia
                                        hold {in_transito,trattenuto} (sospensione/ripresa del
                                        bonifico) ⇒ ogni ciclo legale è confinato lì.
    ESCROW (formula-selettore, la STESSA eseguita concreta contro fase160 nel collaudo):
      - ESC_risolvi_conservazione_clamp / ESC_proporzionale_conservazione_clamp:
        ∀ importo≥1, ∀ richiesto intero (anche negativo/abnorme): host+rimborso == importo
        ESATTO e 0 ≤ rimborso ≤ importo, 0 ≤ host ≤ importo (clamp DIMOSTRATO, non campionato).
    IDEMPOTENZA (webhook/eventi consegnati DUE volte):
      - IDEM_eventi_prenotazione / IDEM_eventi_payout: ogni evento CAS applicato 2 volte
        lascia lo stato del secondo giro identico al primo (upd∘upd == upd, ∀ stato);
      - IDEM_webhook_pagamento: il webhook composto (conferma prenotazione + payout maturato
        + tassa + riga payout INSERT-OR-IGNORE con importo) applicato 2 volte è = 1 volta,
        importo compreso (il replay NON riscrive mai `minori`).

    Ritorna {teorema: 'DIMOSTRATO' | 'CONTROESEMPIO ...' | 'INDETERMINATO' |
    'STATO_NON_MODELLATO: ...'} oppure {'disponibile': 'z3 assente'}."""
    try:
        import z3
    except Exception:
        return {"disponibile": "z3 assente"}
    from fase131_payout_dashboard import _TRANSIZIONI as TAB_PAYOUT

    ris: Dict[str, str] = {}

    def _teorema(nome: str, vincoli: Any, tesi: Any) -> None:
        s = z3.Solver()
        s.add(vincoli)
        s.add(z3.Not(tesi))
        esito = s.check()
        ris[nome] = ("DIMOSTRATO" if esito == z3.unsat
                     else ("CONTROESEMPIO %s" % s.model() if esito == z3.sat
                           else "INDETERMINATO"))

    def _macchina(tabella: Dict[str, Any]) -> Tuple[List[str], Dict[str, int], Any, Any]:
        """Codifica una tabella {stato: {successori}} come relazione Z3 su interi."""
        stati = sorted(set(tabella) | {t for v in tabella.values() for t in v})
        idx = {n: i for i, n in enumerate(stati)}
        archi = sorted((idx[a], idx[b]) for a, v in tabella.items() for b in v)

        def T(u: Any, v: Any) -> Any:
            if not archi:
                return z3.BoolVal(False)
            return z3.Or([z3.And(u == a, v == b) for a, b in archi])

        def dom(u: Any) -> Any:
            return z3.And(u >= 0, u < len(stati))
        return stati, idx, T, dom

    def _rango(u: Any, idx: Dict[str, int], ranghi: Dict[str, int]) -> Any:
        e: Any = z3.IntVal(-10 ** 6)
        for nome, i in idx.items():
            e = z3.If(u == i, z3.IntVal(ranghi[nome]), e)
        return e

    def _idem_eventi(nome_teorema: str, eventi: Any, idx: Dict[str, int], dom: Any) -> None:
        """Ogni evento CAS (sorgenti S -> target t): upd(s)=If(s∈S,t,s); upd∘upd == upd ∀s."""
        difetti = []
        for nome_ev, sorgenti, target in eventi:
            srcs = [idx[x] for x in sorgenti]
            t = idx[target]
            sv = z3.Int("idem_%s_%s" % (nome_teorema, nome_ev))

            def upd(u: Any) -> Any:
                return z3.If(z3.Or([u == i for i in srcs]), t, u)
            slv = z3.Solver()
            slv.add(dom(sv))
            slv.add(z3.Not(upd(upd(sv)) == upd(sv)))
            e = slv.check()
            if e != z3.unsat:
                difetti.append("%s: %s" % (
                    nome_ev, "CONTROESEMPIO %s" % slv.model() if e == z3.sat else "INDETERMINATO"))
        ris[nome_teorema] = "DIMOSTRATO" if not difetti else "; ".join(difetti)

    # ── PRENOTAZIONE ────────────────────────────────────────────────────────────────
    tab_pren = transizioni_prenotazione()
    stati_p, idx_p, T_p, dom_p = _macchina(tab_pren)
    s1, s2 = z3.Ints("s1 s2")
    term = [idx_p[t] for t in TERMINALI_NEGATIVI_PRENOTAZIONE]
    _teorema("PREN_terminale_assorbente",
             z3.And(dom_p(s1), dom_p(s2), T_p(s1, s2)),
             z3.And([s1 != t for t in term]))
    # cammino di n-1 passi CON STUTTER (fermarsi è ammesso): su n stati copre OGNI
    # raggiungibilità (un cammino semplice non ripete stati -> lunghezza < n). Quindi il
    # teorema vale per cammini di QUALSIASI lunghezza, non solo per il singolo passo.
    n = len(stati_p)
    passi = [z3.Int("q%d" % i) for i in range(n)]
    vinc = [dom_p(q) for q in passi]
    vinc.append(z3.Or([passi[0] == t for t in term]))
    for i in range(n - 1):
        vinc.append(z3.Or(passi[i + 1] == passi[i], T_p(passi[i], passi[i + 1])))
    _teorema("PREN_mai_pagato_da_terminale",
             z3.And(vinc), passi[-1] != idx_p["pagato"])
    _teorema("PREN_pagato_solo_da_pagabili",
             z3.And(dom_p(s1), dom_p(s2), T_p(s1, s2), s2 == idx_p["pagato"]),
             z3.Or(s1 == idx_p["in_attesa"], s1 == idx_p["scaduto"]))
    _teorema("PREN_monotona_senza_cicli",
             z3.And(dom_p(s1), dom_p(s2), T_p(s1, s2)),
             _rango(s2, idx_p, RANGO_PRENOTAZIONE) > _rango(s1, idx_p, RANGO_PRENOTAZIONE))

    # ── PAYOUT (tabella di produzione) ──────────────────────────────────────────────
    stati_y, idx_y, T_y, dom_y = _macchina(TAB_PAYOUT)
    nomi_pay = ("PAY_pagato_assorbente", "PAY_mai_ritorno_in_coda",
                "PAY_monotono_mai_indietro", "PAY_cicli_solo_coppia_hold")
    mancanti = sorted(set(stati_y) - set(RANGO_PAYOUT))
    attesi_pay = {"in_attesa", "maturato", "in_transito", "trattenuto", "pagato"}
    if mancanti or not attesi_pay.issubset(stati_y):
        # la macchina di produzione è cambiata e il modello non la copre più: si GRIDA
        # (mai un finto DIMOSTRATO su una macchina diversa da quella modellata)
        msg = "STATO_NON_MODELLATO: nuovi=%r attesi_mancanti=%r" % (
            mancanti, sorted(attesi_pay - set(stati_y)))
        for nm in nomi_pay:
            ris[nm] = msg
    else:
        u1, u2 = z3.Ints("u1 u2")
        _teorema("PAY_pagato_assorbente",
                 z3.And(dom_y(u1), dom_y(u2), T_y(u1, u2)),
                 u1 != idx_y["pagato"])
        _teorema("PAY_mai_ritorno_in_coda",
                 z3.And(dom_y(u1), dom_y(u2), T_y(u1, u2)),
                 z3.And(u2 != idx_y["in_attesa"],
                        z3.Implies(u2 == idx_y["maturato"], u1 == idx_y["in_attesa"])))
        _teorema("PAY_monotono_mai_indietro",
                 z3.And(dom_y(u1), dom_y(u2), T_y(u1, u2)),
                 _rango(u2, idx_y, RANGO_PAYOUT) >= _rango(u1, idx_y, RANGO_PAYOUT))
        hold = [idx_y[h] for h in COPPIA_HOLD_PAYOUT]
        _teorema("PAY_cicli_solo_coppia_hold",
                 z3.And(dom_y(u1), dom_y(u2), T_y(u1, u2),
                        _rango(u1, idx_y, RANGO_PAYOUT) == _rango(u2, idx_y, RANGO_PAYOUT)),
                 z3.And(z3.Or([u1 == h for h in hold]),
                        z3.Or([u2 == h for h in hold]), u1 != u2))

    # ── ESCROW: conservazione + clamp, ∀ intero (anche negativo/abnorme) ────────────
    imp, x = z3.Ints("imp x")

    def zse(c: Any, a: Any, b: Any) -> Any:
        return z3.If(c, a, b)
    host_r, rimb_r = formula_split_risolvi(imp, x, se=zse)
    _teorema("ESC_risolvi_conservazione_clamp",
             imp >= 1,
             z3.And(host_r + rimb_r == imp, rimb_r >= 0, rimb_r <= imp,
                    host_r >= 0, host_r <= imp))
    host_p, rimb_p = formula_split_proporzionale(imp, x, se=zse)
    _teorema("ESC_proporzionale_conservazione_clamp",
             imp >= 1,
             z3.And(host_p + rimb_p == imp, rimb_p >= 0, rimb_p <= imp,
                    host_p >= 0, host_p <= imp))

    # ── IDEMPOTENZA: stesso evento consegnato DUE volte = UNA volta ─────────────────
    _idem_eventi("IDEM_eventi_prenotazione", EVENTI_PRENOTAZIONE, idx_p, dom_p)
    eventi_payout = []
    for target in sorted({t for v in TAB_PAYOUT.values() for t in v}):
        sorgenti = tuple(sorted(s for s, v in TAB_PAYOUT.items() if target in v))
        eventi_payout.append(("verso_" + target, sorgenti, target))
    _idem_eventi("IDEM_eventi_payout", eventi_payout, idx_y, dom_y)

    # webhook COMPOSTO "pagamento riuscito" (fase83._dopo_pagamento): conferma prenotazione
    # (CAS fase162) + riga payout INSERT-OR-IGNORE con importo (fase131.registra_maturato)
    # + payout in_attesa->maturato (tabella di produzione) + tassa nel ledger (set, no-op
    # al replay). Stato composto: (stato_pren, stato_payout, tassa, riga_presente, minori).
    if "maturato" in idx_y and not mancanti:
        sp, sy, minori, nuovo = z3.Ints("sp sy minori nuovo")
        presente, tassa = z3.Bools("presente tassa")
        conf_srcs = [idx_p[s] for s in EVENTI_PRENOTAZIONE[0][1]]
        mat_srcs = [idx_y[s] for s, v in TAB_PAYOUT.items() if "maturato" in v]

        def fw(a_sp: Any, a_sy: Any, a_tassa: Any, a_pres: Any, a_min: Any) -> Tuple[Any, ...]:
            b_sp = z3.If(z3.Or([a_sp == i for i in conf_srcs]), idx_p["pagato"], a_sp)
            b_min = z3.If(a_pres, a_min, nuovo)      # INSERT OR IGNORE: replay NON riscrive
            b_sy = (z3.If(z3.Or([a_sy == i for i in mat_srcs]), idx_y["maturato"], a_sy)
                    if mat_srcs else a_sy)
            return b_sp, b_sy, z3.BoolVal(True), z3.BoolVal(True), b_min
        una = fw(sp, sy, tassa, presente, minori)
        due = fw(*una)
        _teorema("IDEM_webhook_pagamento",
                 z3.And(dom_p(sp), dom_y(sy), minori >= 0, nuovo >= 0),
                 z3.And(una[0] == due[0], una[1] == due[1], una[2] == due[2],
                        una[3] == due[3], una[4] == due[4]))
    else:
        ris["IDEM_webhook_pagamento"] = "STATO_NON_MODELLATO: 'maturato' assente dalla tabella payout"
    return ris
