"""L'ESAME DELLA CASELLA 2 DEL BLOCCO 7 (HOST: PANNELLO E OPERATIVITA') — il pannello e i SUOI soldi.

    python collaudi/esame_pannello_soldi.py                misura e MOSTRA (tutto in-process, Stripe finto)
    python collaudi/esame_pannello_soldi.py --scrivi       misura e SCRIVE nella scheda (anche un rosso,
                                                           col suo motivo)
    python collaudi/esame_pannello_soldi.py --con-guasto   un hold MAI pagato viene marcato 'maturato' nel
                                                           mastro (un guadagno fantasma): deve gridare, NON
                                                           scrive
    python collaudi/esame_pannello_soldi.py --autoprova    il giudizio sui passi, nelle due direzioni

⛔ IL TESTO DELLA CASELLA NON SI RICOPIA: si legge da `collaudi/piano.py` (e' la chiave della scheda).

COSA VUOL DIRE «DICE LA VERITA' SUI SUOI SOLDI», dichiarato (D18) — decisione della chat A il 2026-09-07
col mandato di B («un attrezzo che confronta le cifre che /api/host/* mostra con quelle del payout e della
garanzia lette dagli archivi»), scritta in consegna e rovesciabile. Le cifre di denaro che il pannello host
mostra vengono da DUE rotte (censimento su fase83: `_host_payout` e `_host_metriche`; `_host_prenotazioni`
non porta cifre):
  MASTRO     `/api/host/payout` risponde `payout.riepilogo(host)` (fase131) + i debiti aperti: ogni numero
             che mostra deve essere la SOMMA di righe del mastro, e solo di righe di QUELL'host;
  COERENZA   ogni riga del mastro deve concordare con lo stato della prenotazione (fase162) e con la
             cassaforte (fase160): un hold non pagato e' 'in_attesa', una pagata e' 'maturato' con lo
             stesso importo della garanzia aperta (= netto host + tassa, `_da_versare_host`), una
             rimborsata e' 'trattenuto' (stato voluto: «l'host non vede piu' un incasso che non arrivera'»);
  FANTASMI   la voce 'maturato' e' fatta SOLO di prenotazioni pagate: nessun hold non pagato e nessuna
             rimborsata dentro;
  STIMA      `/api/host/metriche` risponde `revenue_cents`: per non essere un «saldo stimato» non deve
             crescere per un hold MAI pagato e deve calare quando una pagata viene rimborsata. E' il passo
             che oggi puo' essere ROSSO: il calendario (fase58) somma unita' occupate x prezzo, e un hold
             occupa le notti prima di pagare. Se e' rosso resta rosso: e' il rilievo, non si aggira;
  PORTE      senza credenziali il pannello dei soldi risponde 401; con il token di A e `?host_id=B` si
             vedono i soldi di A (il token vince sulla query).

Il sistema e' quello VERO (fase81 `crea_sistema` + fase83 `crea_router`), su cartella temporanea, con
Stripe sostituito (fetch finto) e webhook firmato di prova: le prenotazioni passano dalle rotte
(/api/concierge/quote -> book -> /api/payments/webhook -> /api/concierge/cancella), mai dagli archivi.
Denominatore = passi eseguiti. Ogni situazione deve avere almeno un passo: una situazione non misurata e'
ROSSA, non «non pervenuta» (sbaglio S7).

⛔ D18: `precondizioni()` ferma il giro; `--autoprova` e `--con-guasto`; `NON_GUARDA`; guardia
   `test_pipeline_ci.TestLEsameDelPannelloSoldiNonPuoBARARE`.
⛔ AMBIENTE INTATTO (lezione della CI del 2026-09-07): il banco imposta `UPLOAD_DIR` e sostituisce il
   fetch di Stripe sulla classe; qui si salvano PRIMA e si rimettono DOPO, sempre (`finally`).
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time

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

BLOCCO = 7
MARCA = "verita' sui suoi soldi"
COMANDO = "python collaudi/esame_pannello_soldi.py --scrivi"
SITUAZIONI = ("mastro", "coerenza", "fantasmi", "stima", "porte")
STATI_PAGATI = ("maturato", "in_transito", "pagato")
PASSWORD_DI_PROVA = "password1"          # solo per il banco locale: nessun conto vero
PASSI = []

NON_GUARDA = (
    "la PAGINA (deploy/host.html): qui si misurano le risposte delle rotte JSON, non cio' che il "
    "browser disegna ne' le etichette delle otto lingue (e' l'occhio del fondatore / esame dei testi)",
    "il bonifico vero (Stripe Connect: 'in_transito' -> 'pagato'): il banco ha Stripe sostituito, quindi "
    "il mastro si ferma a 'maturato'; l'uscita vera e' la casella del blocco SOLDI",
    "i debiti dell'host (penali compensate alla fonte, fase177): la rotta li somma e qui si pretende solo "
    "che a scenario pulito siano zero; il loro calcolo e' del Financial Controller",
    "piu' valute: lo scenario e' tutto in EUR, il raggruppamento per valuta di `riepilogo` non e' provato "
    "su una seconda valuta",
    "l'aritmetica di netto, commissione e tassa (quanto SPETTA all'host): e' il blocco SOLDI e "
    "l'oracolo del payout; qui si pretende solo che mastro e cassaforte dicano LO STESSO numero",
    "le altre caselle del blocco 7: non le tocca",
)


class Orologio(object):
    def __init__(self, ts):
        self.ts = int(ts)

    def __call__(self):
        return self.ts


def passo(situazione, nome, ok, dettaglio=""):
    PASSI.append((situazione, nome, bool(ok), dettaglio))
    print("  %s  [%s] %s%s" % ("OK  " if ok else "ROSSO", situazione, nome,
                                ("  -> " + dettaglio) if dettaglio else ""))
    return bool(ok)


# --------------------------------------------------------------------------------------
# IL GIUDIZIO (puro)
# --------------------------------------------------------------------------------------
def giudica(passi, situazioni=SITUAZIONI):
    motivi = []
    for s in situazioni:
        suoi = [p for p in passi if p[0] == s]
        if not suoi:
            motivi.append("situazione «%s» NON misurata" % s)
            continue
        for _s, nome, ok, dettaglio in suoi:
            if not ok:
                motivi.append("[%s] %s%s" % (s, nome, (" (%s)" % dettaglio) if dettaglio else ""))
    fuori = [p for p in passi if p[0] not in situazioni]
    if fuori:
        motivi.append("passi fuori dalle situazioni: %d" % len(fuori))
    return (not motivi), motivi, len(passi)


def riepilogo_dal_mastro(percorso_db, host_id):
    """Il SECONDO conto: le righe del mastro lette con SQL, sommate per valuta e stato."""
    con = sqlite3.connect(percorso_db, timeout=30)
    try:
        out = {}
        for valuta, stato, tot in con.execute(
                "SELECT valuta, stato, SUM(minori) FROM payout WHERE host_id=? GROUP BY valuta, stato",
                (str(host_id),)):
            out.setdefault(valuta, {})[stato] = int(tot or 0)
        return out
    finally:
        con.close()


def righe_del_mastro(percorso_db, host_id=None):
    con = sqlite3.connect(percorso_db, timeout=30)
    try:
        sql = "SELECT prenotazione_id, host_id, minori, valuta, stato FROM payout"
        args = ()
        if host_id is not None:
            sql += " WHERE host_id=?"
            args = (str(host_id),)
        return [dict(zip(("prenotazione_id", "host_id", "minori", "valuta", "stato"), r))
                for r in con.execute(sql, args)]
    finally:
        con.close()


# --------------------------------------------------------------------------------------
# LA CASELLA (per testo) E LE PRECONDIZIONI (D18 punto 1)
# --------------------------------------------------------------------------------------
def condizione():
    blocco = [b for b in BLOCCHI if b["ordine"] == BLOCCO]
    cond = blocco[0]["finito_quando"] if len(blocco) == 1 else ()
    trovate = [c for c in cond if MARCA in str(c)]
    if len(trovate) != 1:
        raise RuntimeError("nel blocco %d trovo %d caselle con «%s»: ne serve UNA"
                           % (BLOCCO, len(trovate), MARCA))
    return trovate[0]


def precondizioni():
    fuori = []
    try:
        testo = " ".join(str(condizione()).split())
        fuori.append(("la casella esiste nel piano, una sola, e parla dei soldi dell'host",
                      "saldo stimato" in testo, testo[:80]))
    except Exception as e:
        fuori.append(("la casella esiste nel piano, una sola", False, "%s: %s" % (type(e).__name__, e)))
    try:
        impronta = scheda.impronta_del_blocco(BLOCCO)
        fuori.append(("il blocco ha un'impronta", bool(impronta), impronta or "il piano non si legge"))
    except Exception as e:
        fuori.append(("il blocco ha un'impronta", False, str(e)))
    try:
        from collaudi.gare_estreme import _host_pubblica, _quote, _sistema  # noqa: F401
        from collaudi.multivettore import _g, _router  # noqa: F401
        from fase131_payout_dashboard import PayoutDashboard  # noqa: F401
        from fase160_escrow_garanzia import FINESTRA_ORE_DEFAULT  # noqa: F401
        from fase87_stripe_webhook import firma_di_test  # noqa: F401
        fuori.append(("il banco, il mastro (fase131), la cassaforte (fase160) e il webhook si importano",
                      True, ""))
    except Exception as e:
        fuori.append(("il banco, il mastro, la cassaforte e il webhook si importano", False,
                      "%s: %s" % (type(e).__name__, e)))
    return all(ok for _, ok, _ in fuori), fuori


# --------------------------------------------------------------------------------------
# IL BANCO: sistema vero, Stripe finto, DUE host, ambiente rimesso a posto
# --------------------------------------------------------------------------------------
class Banco(object):

    def __init__(self, d):
        from collaudi.gare_estreme import _sistema
        from collaudi.multivettore import _g, _router
        from fase131_payout_dashboard import crea_payout_dashboard
        from fase162_pagamenti_pendenti import crea_pagamenti_pendenti
        self.d = d
        self.sis = _sistema(d)
        self.orologio = Orologio(time.time())
        self.sis.pagamenti_pendenti = crea_pagamenti_pendenti(d + "/p.db", orologio=self.orologio)
        # il mastro SU FILE (il banco lo tiene in RAM): cosi' il secondo conto lo legge con SQL
        self.db_payout = d + "/payout.db"
        self.sis.payout = crea_payout_dashboard(self.db_payout)
        self.sis.payout.inizializza_schema()             # lo fa il bootstrap, non la fabbrica
        self.router = _router(self.sis)
        self.g = _g(self.router)
        self.tk_a, self.host_a = self.registra_host("host-a@esame.it")
        self.tk_b, self.host_b = self.registra_host("host-b@esame.it")

    def registra_host(self, email):
        from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
        s, c = self.g("POST", "/api/host/registrazione", {
            "email": email, "password": PASSWORD_DI_PROVA, "accetta_termini": True,
            "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
            "versione": CONTRATTO_HOST_VERSIONE})
        c = c if isinstance(c, dict) else {}
        if s != 201 or not c.get("token"):
            raise RuntimeError("registrazione host %s fallita: %s %s" % (email, s, c))
        return {"X-Host-Token": c["token"]}, c.get("host_id", "")

    def alloggio(self, tk, slug, unita, da, a):
        from collaudi.gare_estreme import _host_pubblica
        return _host_pubblica(self.g, tk, slug, unita, 10000, da, a)

    def prenota(self, slug, ci, co):
        from collaudi.gare_estreme import _quote
        tok = _quote(self.g, slug, ci, co)
        if not tok:
            return None, None
        s, b = self.g("POST", "/api/concierge/book", {"quote_token": tok, "email": "ospite@esame.it"})
        if s != 201:
            return None, None
        return b["riferimento"], b["voucher_token"]

    def webhook(self, rif):
        from fase87_stripe_webhook import firma_di_test
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        return self.router.gestisci("POST", "/api/payments/webhook", {}, pl,
                                    {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})

    def stato(self, rif):
        return (self.sis.pagamenti_pendenti.info(rif) or {}).get("stato")

    def corpo(self, rif):
        try:
            return json.loads((self.sis.pagamenti_pendenti.info(rif) or {}).get("corpo_json") or "{}")
        except Exception:
            return {}

    def pagata(self, slug, ci, co):
        rif, vt = self.prenota(slug, ci, co)
        if rif:
            self.webhook(rif)
        return rif, vt

    def pannello_payout(self, tk, query=None):
        return self.router.gestisci("GET", "/api/host/payout", query or {}, None, tk)

    def revenue(self, tk):
        s, m = self.g("GET", "/api/host/metriche", None, tk)
        return (m or {}).get("revenue_cents") if s == 200 else None

    def garanzia(self, rif):
        return self.sis.garanzia.stato(rif)


def _ambiente_salvato():
    import fase85_pagamenti_stripe as stripe_mod
    return (os.environ.get("UPLOAD_DIR"), vars(stripe_mod.ProviderStripe).get("_fetch_reale"))


def _ambiente_ripristinato(salvato):
    import fase85_pagamenti_stripe as stripe_mod
    upload, fetch = salvato
    if upload is None:
        os.environ.pop("UPLOAD_DIR", None)
    else:
        os.environ["UPLOAD_DIR"] = upload
    if fetch is None:
        if "_fetch_reale" in vars(stripe_mod.ProviderStripe):
            delattr(stripe_mod.ProviderStripe, "_fetch_reale")
    else:
        stripe_mod.ProviderStripe._fetch_reale = fetch


# --------------------------------------------------------------------------------------
# LO SCENARIO E LE MISURE
# --------------------------------------------------------------------------------------
def scenario(b, con_guasto=False):
    """Host A: una pagata, una pagata poi rimborsata dall'ospite, un hold mai pagato.
    Host B: una pagata. Ritorna i riferimenti per situazione."""
    slug_a = b.alloggio(b.tk_a, "casa-a", 3, "2027-06-01", "2027-06-30")
    slug_b = b.alloggio(b.tk_b, "casa-b", 1, "2027-06-01", "2027-06-30")
    rev_zero = b.revenue(b.tk_a)
    pagata, _ = b.pagata(slug_a, "2027-06-05", "2027-06-07")
    rimborsata, vt = b.pagata(slug_a, "2027-06-10", "2027-06-12")
    rev_due_pagate = b.revenue(b.tk_a)
    s_canc, _ = b.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
    rev_dopo_rimborso = b.revenue(b.tk_a)
    hold, _ = b.prenota(slug_a, "2027-06-20", "2027-06-22")
    rev_con_hold = b.revenue(b.tk_a)
    pagata_b, _ = b.pagata(slug_b, "2027-06-05", "2027-06-07")
    if con_guasto and hold:
        b.sis.payout.aggiorna_stato(hold, "maturato")          # IL GUASTO: un guadagno fantasma
    return {"pagata": pagata, "rimborsata": rimborsata, "hold": hold, "pagata_b": pagata_b,
            "s_canc": s_canc, "revenue": (rev_zero, rev_due_pagate, rev_dopo_rimborso, rev_con_hold)}


def misura_mastro(b, sc):
    print("\n--- MASTRO: la rotta mostra la somma delle righe del mastro, e solo le SUE ---")
    passo("mastro", "lo scenario e' in piedi: pagata, rimborsata (cancellazione 200), hold e la pagata di B",
          all([sc["pagata"], sc["rimborsata"], sc["hold"], sc["pagata_b"]]) and sc["s_canc"] == 200
          and b.stato(sc["pagata"]) == "pagato" and b.stato(sc["rimborsata"]) == "rimborsato"
          and b.stato(sc["hold"]) == "in_attesa",
          "stati: %s %s %s canc=%s" % (b.stato(sc["pagata"]), b.stato(sc["rimborsata"]), b.stato(sc["hold"]),
                                       sc["s_canc"]))
    for etichetta, tk, host in (("A", b.tk_a, b.host_a), ("B", b.tk_b, b.host_b)):
        s, corpo = b.pannello_payout(tk)
        rotta = (corpo or {}).get("payout") if s == 200 else None
        secondo = riepilogo_dal_mastro(b.db_payout, host)
        passo("mastro", "host %s: `/api/host/payout` == somma SQL delle righe del mastro dell'host" % etichetta,
              s == 200 and rotta == secondo, "rotta=%r mastro=%r" % (rotta, secondo))
        passo("mastro", "host %s: i debiti aperti sono zero a scenario pulito" % etichetta,
              s == 200 and (corpo or {}).get("debiti_aperti_cents") == {},
              "debiti=%r" % ((corpo or {}).get("debiti_aperti_cents"),))
    tutte = righe_del_mastro(b.db_payout)
    di_a = righe_del_mastro(b.db_payout, b.host_a)
    di_b = righe_del_mastro(b.db_payout, b.host_b)
    passo("mastro", "ogni riga del mastro appartiene ad A o a B, nessuna a nessuno",
          len(tutte) == len(di_a) + len(di_b) and len(di_b) == 1, "tutte=%d A=%d B=%d" % (len(tutte), len(di_a), len(di_b)))


def misura_coerenza(b, sc):
    print("\n--- COERENZA: ogni riga del mastro concorda con lo stato (fase162) e con la cassaforte (fase160) ---")
    attesi = {"in_attesa": ("in_attesa",), "pagato": STATI_PAGATI, "rimborsato": ("trattenuto",)}
    righe = righe_del_mastro(b.db_payout, b.host_a)
    passo("coerenza", "l'host A ha esattamente tre righe nel mastro (pagata, rimborsata, hold)", len(righe) == 3,
          "righe=%r" % ([(r["prenotazione_id"][:8], r["stato"]) for r in righe],))
    for r in righe:
        st = b.stato(r["prenotazione_id"])
        passo("coerenza", "prenotazione %s: stato '%s' -> voce del mastro fra %r" % (r["prenotazione_id"][:8], st, attesi.get(st)),
              st in attesi and r["stato"] in attesi[st], "mastro dice '%s'" % r["stato"])
    for nome in ("pagata", "hold"):
        rif = sc[nome]
        corpo = b.corpo(rif)
        dovuto = int(corpo.get("netto_host_cents") or 0) + int(corpo.get("tassa_soggiorno_cents") or 0)
        riga = [r for r in righe if r["prenotazione_id"] == rif]
        gar = b.garanzia(rif) or {}
        passo("coerenza", "%s: mastro == cassaforte == netto host + tassa del corpo" % nome,
              len(riga) == 1 and riga[0]["minori"] == dovuto == int(gar.get("importo_host_cents") or -1) > 0,
              "mastro=%r cassaforte=%r corpo=%d" % (riga[0]["minori"] if riga else None, gar.get("importo_host_cents"), dovuto))
    passo("coerenza", "la pagata ha la cassaforte 'in_garanzia' e la rimborsata no",
          (b.garanzia(sc["pagata"]) or {}).get("stato") == "in_garanzia"
          and (b.garanzia(sc["rimborsata"]) or {}).get("stato") != "in_garanzia",
          "pagata=%r rimborsata=%r" % ((b.garanzia(sc["pagata"]) or {}).get("stato"),
                                       (b.garanzia(sc["rimborsata"]) or {}).get("stato")))


def misura_fantasmi(b, sc):
    print("\n--- FANTASMI: la voce 'maturato' e' fatta SOLO di prenotazioni pagate ---")
    righe = righe_del_mastro(b.db_payout, b.host_a)
    maturate = [r for r in righe if r["stato"] in STATI_PAGATI]
    non_pagate = [r["prenotazione_id"][:8] for r in maturate if b.stato(r["prenotazione_id"]) != "pagato"]
    passo("fantasmi", "nessuna riga 'maturato' di A e' un hold non pagato o una rimborsata", not non_pagate,
          "fantasmi=%r" % (non_pagate,))
    s, corpo = b.pannello_payout(b.tk_a)
    voce = ((corpo or {}).get("payout") or {}).get("EUR", {})
    somma_pagate = sum(int(b.corpo(r["prenotazione_id"]).get("netto_host_cents") or 0)
                       + int(b.corpo(r["prenotazione_id"]).get("tassa_soggiorno_cents") or 0)
                       for r in righe if b.stato(r["prenotazione_id"]) == "pagato")
    mostrato = sum(int(voce.get(k) or 0) for k in STATI_PAGATI)
    passo("fantasmi", "il 'maturato' che il pannello mostra == somma dei netti delle sole PAGATE",
          s == 200 and mostrato == somma_pagate > 0, "pannello=%d pagate=%d" % (mostrato, somma_pagate))
    passo("fantasmi", "l'hold non pagato compare SOLO come 'in_attesa' (mai come guadagno)",
          int(voce.get("in_attesa") or 0) == sum(r["minori"] for r in righe if r["prenotazione_id"] == sc["hold"]) > 0,
          "in_attesa=%r" % (voce.get("in_attesa"),))


def misura_stima(b, sc):
    print("\n--- STIMA: `revenue_cents` di /api/host/metriche non deve essere un saldo stimato ---")
    zero, due, dopo, con_hold = sc["revenue"]
    passo("stima", "revenue parte da zero e cresce con due prenotazioni pagate",
          zero == 0 and isinstance(due, int) and due > 0, "zero=%r due=%r" % (zero, due))
    passo("stima", "revenue CALA quando una pagata viene rimborsata (le notti tornano libere)",
          isinstance(dopo, int) and isinstance(due, int) and dopo < due, "due=%r dopo=%r" % (due, dopo))
    passo("stima", "revenue NON cresce per un hold MAI pagato (altrimenti e' un saldo stimato)",
          isinstance(con_hold, int) and isinstance(dopo, int) and con_hold == dopo,
          "prima dell'hold=%r con l'hold=%r" % (dopo, con_hold))


def misura_porte(b, sc):
    print("\n--- PORTE: senza credenziali 401; il token vince sulla query ---")
    s, _ = b.pannello_payout({})
    passo("porte", "senza token `/api/host/payout` risponde 401", s == 401, "http=%s" % s)
    s, corpo = b.pannello_payout(b.tk_a, {"host_id": b.host_b})
    rotta = (corpo or {}).get("payout") if s == 200 else None
    passo("porte", "col token di A e `?host_id=B` si vedono i soldi di A, non di B",
          s == 200 and rotta == riepilogo_dal_mastro(b.db_payout, b.host_a)
          and rotta != riepilogo_dal_mastro(b.db_payout, b.host_b), "rotta=%r" % (rotta,))


# --------------------------------------------------------------------------------------
def passi_finti(rossi=(), senza=()):
    fuori = []
    for s in SITUAZIONI:
        if s in senza:
            continue
        for i in range(2):
            fuori.append((s, "passo %d" % i, not (s in rossi and i == 1), ""))
    return fuori


def autoprova():
    casi = [("tutte le situazioni verdi", passi_finti(), True)]
    for s in SITUAZIONI:
        casi.append(("un passo rosso in «%s»" % s, passi_finti(rossi=(s,)), False))
        casi.append(("«%s» non misurata" % s, passi_finti(senza=(s,)), False))
    casi.append(("nessun passo", [], False))
    casi.append(("un passo fuori dalle situazioni", passi_finti() + [("altro", "x", True, "")], False))
    righe, riuscita = [], True
    for nome, passi, atteso in casi:
        verde, motivi, den = giudica(passi)
        ok = verde == atteso
        riuscita = riuscita and ok
        righe.append("   %-36s -> %-6s (atteso %-6s) denominatore %d%s"
                     % (nome, "VERDE" if verde else "ROSSO", "VERDE" if atteso else "ROSSO", den,
                        "" if ok else "   ⛔ NON E' QUELLO CHE DOVEVA DIRE: %s" % "; ".join(motivi)))
    return riuscita, righe


def _stampa_non_guarda():
    print("-" * 86)
    print("⛔ COSA QUESTO ESAME NON HA ESAMINATO (D18 punto 3)")
    for r in NON_GUARDA:
        print("   · %s" % r)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    os.chdir(RADICE)
    del PASSI[:]
    print("=" * 86)
    print("🧾 ESAME DEL BLOCCO 7 — casella 2: il pannello host e la verita' sui suoi soldi")
    print("=" * 86)

    if "--autoprova" in argv:
        print("🔁 AUTOPROVA — il giudizio si vede gridare e tacere su passi costruiti (D18 punto 2)")
        riuscita, righe = autoprova()
        for r in righe:
            print(r)
        _stampa_non_guarda()
        print("=" * 86)
        print("VERDETTO: %s" % ("✅ il giudizio grida sui passi rossi e tace sui verdi" if riuscita
                                else "⛔ IL GIUDIZIO NON E' AFFIDABILE"))
        return 0 if riuscita else 1

    con_guasto = "--con-guasto" in argv
    if con_guasto and "--scrivi" in argv:
        print("⛔ FERMO: `--con-guasto` non scrive. Serve a vedere l'esame gridare; registrare quel")
        print("   rosso metterebbe nella scheda un guadagno fantasma apposta.")
        return 2

    tutte_ok, righe = precondizioni()
    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    for nome, ok, motivo in righe:
        print("  %-9s %-76s %s" % ("OK" if ok else "⛔ NO", nome, motivo))
    if not tutte_ok:
        print("VERDETTO: ⛔ FERMO — una precondizione non regge, quindi NON misuro e NON scrivo.")
        _stampa_non_guarda()
        return 2
    if con_guasto:
        print("⚠️  PASSATA COL GUASTO DENTRO: l'hold mai pagato e' marcato 'maturato' nel mastro")

    salvato = _ambiente_salvato()
    d = tempfile.mkdtemp()
    try:
        try:
            b = Banco(d)
            sc = scenario(b, con_guasto)
        except Exception as e:                           # noqa: BLE001 - un banco rotto e' un rosso
            passo("mastro", "il banco o lo scenario e' ESPLOSO", False, "%s: %s" % (type(e).__name__, e))
            sc = None
        if sc is not None:
            for situazione, f in (("mastro", misura_mastro), ("coerenza", misura_coerenza),
                                  ("fantasmi", misura_fantasmi), ("stima", misura_stima),
                                  ("porte", misura_porte)):
                try:
                    f(b, sc)
                except Exception as e:                   # noqa: BLE001 - una misura rotta e' un rosso
                    passo(situazione, "la misura e' ESPLOSA", False, "%s: %s" % (type(e).__name__, e))
    finally:
        shutil.rmtree(d, ignore_errors=True)
        _ambiente_ripristinato(salvato)

    verde, motivi, denominatore = giudica(PASSI)
    print("")
    print("VERDETTO: %s — passi %d, rossi %d, denominatore %d"
          % ("✅ VERDE" if verde else "⛔ ROSSO", len(PASSI), sum(1 for p in PASSI if not p[2]), denominatore))
    for m in motivi:
        print("   perche': %s" % m)

    if "--scrivi" in argv:
        print("")
        print("SCRITTURA NELLA SCHEDA")
        riga = scheda.registra(condizione(), esito=verde, denominatore=denominatore,
                               comando=COMANDO, ordine=BLOCCO, motivo="; ".join(motivi) or None)
        print("  scritta: blocco %d · esito %s · denominatore %d · impronta %s · motivo: %s"
              % (riga["blocco"], riga["esito"], riga["denominatore"], riga["impronta"], riga.get("motivo") or "-"))
    else:
        print("")
        print("(non ho scritto niente: aggiungi --scrivi per registrare nella scheda)")
    _stampa_non_guarda()
    print("=" * 86)
    return 0 if verde else 1


if __name__ == "__main__":
    sys.exit(main())
