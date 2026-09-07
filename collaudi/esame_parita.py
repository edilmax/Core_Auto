"""L'ESAME DELLA CASELLA «costa SEMPRE meno che sulle OTA, e l'host non puo' mentire sul prezzo» (Blocco 4).

    python collaudi/esame_parita.py                 misura cio' che il codice sa misurare e MOSTRA
    python collaudi/esame_parita.py --scrivi        ...e SCRIVE nella scheda (un rosso, col suo motivo,
                                                    finche' la casella resta NON MISURABILE)
    python collaudi/esame_parita.py --casi N        casi generati per relazione (di serie 300)
    python collaudi/esame_parita.py --con-guasto    storce il confronto (l'OTA costa MENO): deve
                                                    gridare, e NON scrive mai
    python collaudi/esame_parita.py --autoprova     si vede gridare e tacere su moduli finti (D18 punto 2)

⛔ IL TESTO DELLA CASELLA NON SI RICOPIA: si legge da `collaudi/piano.py` (Blocco 4) cercando la
   sottostringa stabile «costa SEMPRE meno»: una e una sola.

⛔ IL RILIEVO, PRIMA DI TUTTO (D10, misurato il 2026-09-07 con `grep`): LA CASELLA NON E' MISURABILE
   DAL CODICE, e questo esame lo DICHIARA invece di dare un verde.
   1. «da noi costa SEMPRE meno che sulle OTA»: il solo «prezzo OTA» che il codice conosce e' quello
      di `fase125_confronto_guest.confronta_guest`, che NON legge nessuna OTA: applica al NOSTRO prezzo
      un markup fisso (15% host + 14% guest fee + 4% DCC, `PoliticaConfrontoGuest`). E' una STIMA, e
      per costruzione da' sempre un totale OTA >= al nostro: la relazione «costa meno» non puo' essere
      falsa e quindi non misura niente sul mondo. L'unico posto in cui un prezzo OTA VERO entra nel
      sistema e' la segnalazione dell'ospite in `fase190_rate_parity.segnala` — e fase190 e' DORMIENTE:
      `grep -n "rate_parity\\|fase190" fase81_bootstrap_casavip.py fase83_server.py main_casavip.py` -> 0
      righe (nessuna rotta lo chiama, nessun ranking lo legge).
   2. «l'host non puo' mentire sul prezzo»: l'host NON dichiara nessun prezzo OTA da nessuna parte (la
      quota non ha un campo per questo), quindi non c'e' una bugia possibile da rilevare; la clausola
      contrattuale di parita' che fase190 presuppone NON sta nel contratto host:
      `grep -i parit fase163_accettazioni.py deploy/*.html` -> 0 righe.
   La memoria del progetto lo diceva gia' («il confronto e' acceso ma e' una stima; la leva vera e'
   il contratto»): qui diventa una misura, con la guardia che la tiene ferma.

COSA QUESTO ESAME MISURA LO STESSO (quello che il codice sa fare, con Hypothesis; denominatore = casi):
  P1  il confronto mostrato all'ospite (fase125) non e' mai a NOSTRO sfavore e non nasconde una fee:
      `nostro_totale == netto` (0% ospite), `ota_totale >= nostro_totale`, `risparmio = ota - nostro`,
      `0 <= risparmio_bps < 10000`, e con valuta diversa l'OTA costa di piu', mai di meno;
  P2  `fase190.e_violazione` e' giusta ai confini: nostro <= OTA*(1+2%) -> nessuna violazione, un
      centesimo sopra -> violazione; ingressi non validi -> mai violazione;
  P3  il gestore fase190 (in memoria): una segnalazione con OTA piu' basso oltre tolleranza nasce
      «aperto», una infondata nasce «respinto»; l'annuncio con una violazione verificata perde il badge
      e la penalita' scatta, chi non ne ha prende il bonus; il punteggio non scende mai sotto 0;
  P4  la MISURABILITA': fase190 e' cablato in produzione? il contratto host nomina la parita'? la quota
      porta un prezzo OTA osservato? Tre NO oggi -> la casella resta ROSSA con motivo «NON MISURABILE».

⛔ D18: precondizioni; --autoprova su moduli finti (sani e storti); NON_GUARDA; --con-guasto non scrive;
   guardia `TestLEsameDellaParitaNonPuoBARARE` in test_pipeline_ci.py.
"""
import io
import os
import re
import sqlite3
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
MARCA = "costa SEMPRE meno"
COMANDO = "python collaudi/esame_parita.py --scrivi"
CASI_DI_SERIE = 300
FILE_CABLAGGIO = ("fase81_bootstrap_casavip.py", "fase83_server.py", "main_casavip.py")
FILE_CONTRATTO = ("fase163_accettazioni.py",)

NON_GUARDA = (
    "il prezzo VERO sulle OTA: nessun modulo lo legge (fase125 lo stima con percentuali fisse), quindi "
    "questo esame non puo' dire se da noi costa meno DAVVERO; puo' solo dire che il confronto mostrato "
    "non mente contro di noi e che la macchina che raccoglierebbe i prezzi veri (fase190) e' dormiente",
    "il ranking: `punteggio_visibilita` e' un segnale puro che nessun motore di ricerca legge oggi "
    "(fase173 non lo importa)",
    "le percentuali di fase125 (15%, 14%, 4%): sono ipotesi sul mercato scritte nel codice, non misure; "
    "qui si prova l'aritmetica, non la loro verita'",
    "le pagine pubbliche che promettono «meno che su Booking»: le confronta audit_millimetrico/occhio_del_fondatore",
)


# --------------------------------------------------------------------------------------
# 1. LE RELAZIONI (pure: ricevono i moduli, rendono [(nome, casi, contro_esempi)])
# --------------------------------------------------------------------------------------
def relazioni(confronta, e_violazione, punteggio, crea_gestore, *, casi=CASI_DI_SERIE, seme=0):
    from hypothesis import given, settings, strategies as st, HealthCheck, seed
    S = settings(max_examples=casi, deadline=None, database=None, suppress_health_check=list(HealthCheck))
    N = st.integers(min_value=1, max_value=50_000_000)
    esiti = []

    def corri(nome, corpo):
        contati, contro = {"n": 0}, []

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

    def p1(netto, estera):
        c = confronta(netto, valuta_diversa=estera)
        if c["nostro_totale_cents"] != netto:
            return "nostro_totale %d != netto %d: c'e' una fee nascosta all'ospite" % (c["nostro_totale_cents"], netto)
        if c["ota_totale_cents"] < c["nostro_totale_cents"]:
            return "il confronto dice che l'OTA costa MENO: %d < %d" % (c["ota_totale_cents"], c["nostro_totale_cents"])
        if c["risparmio_guest_cents"] != c["ota_totale_cents"] - c["nostro_totale_cents"]:
            return "risparmio %d != ota - nostro %d" % (c["risparmio_guest_cents"],
                                                        c["ota_totale_cents"] - c["nostro_totale_cents"])
        if not (0 <= c["risparmio_bps"] < 10000):
            return "risparmio_bps fuori banda: %d" % c["risparmio_bps"]
        if estera:
            e = confronta(netto, valuta_diversa=False)
            if c["ota_totale_cents"] < e["ota_totale_cents"]:
                return "con valuta diversa l'OTA costa MENO (%d < %d)" % (c["ota_totale_cents"], e["ota_totale_cents"])
        return ""
    p1.strategie = dict(netto=N, estera=st.booleans())
    corri("P1 il confronto mostrato all'ospite non mente contro di noi", p1)

    def p2(ota, delta):
        soglia = ota + ota * 200 // 10000
        if e_violazione(soglia, ota):
            return "nostro=%d (= OTA+2%%) segnato come violazione" % soglia
        if not e_violazione(soglia + 1, ota):
            return "nostro=%d (OTA+2%% + 1 cent) NON segnato" % (soglia + 1)
        if e_violazione(max(0, ota - delta), ota):
            return "nostro sotto l'OTA (%d < %d) segnato come violazione" % (max(0, ota - delta), ota)
        if e_violazione(None, ota) or e_violazione(ota + 10**9, 0) or e_violazione(ota, -5):
            return "un ingresso non valido ha dato violazione"
        return ""
    p2.strategie = dict(ota=N, delta=st.integers(min_value=0, max_value=50_000_000))
    corri("P2 e_violazione: giusta ai confini (tolleranza 2%), mai su ingressi non validi", p2)

    def p3(nostro, sotto, base):
        g = crea_gestore()
        ota_basso = max(1, nostro - nostro * sotto // 10000)            # sotto = quanto l'OTA e' piu' basso, in bps
        rid = g.segnala(alloggio_slug="casa", ota_nome="ota", ota_prezzo_cents=ota_basso, nostro_prezzo_cents=nostro)
        if rid is None:
            return "segnalazione valida rifiutata"
        attesa = "aperto" if e_violazione(nostro, ota_basso) else "respinto"
        stato = [r for r in g.segnalazioni() if r["id"] == rid][0]["stato"]
        if stato != attesa:
            return "segnalazione nata '%s', attesa '%s' (nostro=%d ota=%d)" % (stato, attesa, nostro, ota_basso)
        s0 = g.stato_parita("casa")
        if attesa == "respinto" and not s0["badge_vip"]:
            return "una segnalazione infondata toglie il badge"
        if attesa == "aperto":
            if s0["badge_vip"]:
                return "una violazione aperta lascia il badge"
            g.risolvi(rid, "verificato")
            s1 = g.stato_parita("casa")
            # la penalita' deve portare SOTTO la base (non solo sotto «base + bonus»)
            if not s1["penalita"] or (base > 0 and punteggio(base, s1) >= base):
                return "una violazione verificata non penalizza il ranking (base %d -> %d)" % (base, punteggio(base, s1))
        if punteggio(base, g.stato_parita("casa")) < 0:
            return "punteggio sotto zero"
        if g.segnala(alloggio_slug="casa", ota_nome="ota", ota_prezzo_cents=0, nostro_prezzo_cents=nostro) is not None:
            return "una segnalazione con OTA a 0 e' stata accettata"
        return ""
    p3.strategie = dict(nostro=N, sotto=st.integers(min_value=0, max_value=5000),
                        base=st.integers(min_value=0, max_value=100))
    corri("P3 fase190: la segnalazione nasce giusta, la violazione verificata penalizza, mai sotto zero", p3)
    return esiti


def misurabilita(radice=RADICE):
    """P4: i tre fatti che renderebbero la casella misurabile, letti dai file (con `grep`, non a memoria)."""
    def conta(files, pattern):
        n = 0
        for f in files:
            try:
                with io.open(os.path.join(radice, f), encoding="utf-8", errors="replace") as h:
                    n += len(re.findall(pattern, h.read(), flags=re.IGNORECASE))
            except OSError:
                pass
        return n
    cablato = conta(FILE_CABLAGGIO, r"rate_parity|fase190")
    clausola = conta(FILE_CONTRATTO, r"parit[aà]")
    try:
        with io.open(os.path.join(radice, "fase59_concierge.py"), encoding="utf-8", errors="replace") as h:
            quota_ota = len(re.findall(r"ota_prezzo|prezzo_ota", h.read()))
    except OSError:
        quota_ota = 0
    return [("fase190 (segnalazioni di prezzo piu' basso) e' cablato in produzione", cablato > 0,
             "%d riferimenti in %s" % (cablato, ", ".join(FILE_CABLAGGIO))),
            ("il contratto host nomina la parita' tariffaria", clausola > 0,
             "%d occorrenze di «parita'» in %s" % (clausola, ", ".join(FILE_CONTRATTO))),
            ("la quota porta un prezzo OTA osservato o dichiarato (non stimato)", quota_ota > 0,
             "%d campi ota_prezzo/prezzo_ota in fase59_concierge.py" % quota_ota)]


def giudica(esiti, misure):
    """(verde, passi, motivi, denominatore). La casella e' verde SOLO se le relazioni reggono E la
    misurabilita' c'e': con tre NO su tre e' ROSSA per «NON MISURABILE», non per un guasto."""
    passi, den = [], 0
    for nome, n, contro in esiti:
        den += n
        passi.append((nome + " (%d casi)" % n, n > 0 and not contro,
                      ("; ".join(contro)[:300]) if contro else ("" if n > 0 else "ZERO casi")))
    for nome, ok, dett in misure:
        passi.append(("P4 " + nome, ok, dett))
    motivi = ["%s (%s)" % (n_, d) if d else n_ for n_, ok, d in passi if not ok]
    if any(not ok for n_, ok, _d in passi if n_.startswith("P4")):
        motivi.append("NON MISURABILE: il codice non conosce nessun prezzo OTA vero e l'host non ne dichiara "
                      "uno; fase125 e' una stima a percentuali fisse")
    return not motivi, passi, motivi, den


def condizione():
    blocco = [b for b in BLOCCHI if b["ordine"] == BLOCCO]
    cond = blocco[0]["finito_quando"] if len(blocco) == 1 else ()
    trovate = [c for c in cond if MARCA in str(c)]
    if len(trovate) != 1:
        raise ValueError("il Blocco %d ha %d caselle con «%s», ne serve una sola" % (BLOCCO, len(trovate), MARCA))
    return trovate[0]


def moduli_veri():
    from fase125_confronto_guest import confronta_guest
    from fase190_rate_parity import (GestoreRateParity, _ConnCondivisa, e_violazione,
                                     punteggio_visibilita)

    def gestore_in_memoria():
        # ⛔ DIFETTO LATENTE TROVATO IL 2026-09-07 (scritto, non riparato): la fabbrica
        # `crea_gestore_rate_parity(":memory:")` apre una connessione NUOVA a ogni chiamata, e in
        # memoria ogni connessione e' un archivio vuoto -> «no such table: parity_reports» alla
        # prima segnalazione. Il modulo ha gia' `_ConnCondivisa` per questo caso, ma la fabbrica
        # non lo usa (fase190:183-185). Qui si usa l'involucro del modulo, direttamente.
        con = sqlite3.connect(":memory:", check_same_thread=False)
        return GestoreRateParity(lambda: _ConnCondivisa(con))
    return confronta_guest, e_violazione, punteggio_visibilita, gestore_in_memoria


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
        c, v, p, g = moduli_veri()
        r = c(10000)
        fuori.append(("fase125 e fase190 si importano e rispondono", isinstance(r, dict) and "ota_totale_cents" in r,
                      "confronta_guest(10000) -> ota %s, nostro %s" % (r.get("ota_totale_cents"), r.get("nostro_totale_cents"))))
        g().segnala(alloggio_slug="x", ota_nome="o", ota_prezzo_cents=1, nostro_prezzo_cents=1)
    except Exception as e:
        fuori.append(("fase125 e fase190 si importano e rispondono", False, "%s: %s" % (type(e).__name__, e)))
    try:
        import hypothesis  # noqa: F401
        fuori.append(("hypothesis e' installata", True, hypothesis.__version__))
    except Exception as e:
        fuori.append(("hypothesis e' installata", False, str(e)))
    return all(ok for _, ok, _ in fuori), fuori


# --------------------------------------------------------------------------------------
# 2. L'AUTOPROVA (D18 punto 2): moduli finti, sani e storti
# --------------------------------------------------------------------------------------
def moduli_finti(guasto=None):
    def confronta(netto, *, valuta_diversa=False):
        ota = netto + netto * 1500 // 10000
        ota += ota * 1400 // 10000
        if valuta_diversa:
            ota += ota * 400 // 10000
        nostro = netto
        if guasto == "fee_nascosta":
            nostro = netto + 1
        if guasto == "ota_costa_meno":
            ota = netto - 1 if netto > 1 else 0
        risp = max(0, ota - nostro)
        return {"ota_totale_cents": ota, "nostro_totale_cents": nostro, "risparmio_guest_cents": risp,
                "risparmio_bps": risp * 10000 // ota if ota else 0}

    def e_viol(n, o, *, tolleranza_bps=200):
        try:
            n, o = int(n), int(o)
        except (TypeError, ValueError):
            return False
        if isinstance(n, bool) or n < 0 or o <= 0:
            return False
        soglia = o + o * tolleranza_bps // 10000
        return n >= soglia if guasto == "confine_sbagliato" else n > soglia

    def punteggio(base, stato):
        b = int(base)
        if stato.get("violazioni_verificate", 0) > 0 and guasto != "niente_penalita":
            b -= 40
        elif stato.get("badge_vip"):
            b += 15
        return max(0, b)

    class _G:
        def __init__(self):
            self.r = []

        def segnala(self, *, alloggio_slug, ota_nome, ota_prezzo_cents, nostro_prezzo_cents, **k):
            if ota_prezzo_cents <= 0:
                return None
            st = "aperto" if e_viol(nostro_prezzo_cents, ota_prezzo_cents) else "respinto"
            self.r.append({"id": len(self.r) + 1, "stato": st})
            return len(self.r)

        def risolvi(self, rid, esito):
            self.r[rid - 1]["stato"] = esito
            return True

        def segnalazioni(self):
            return list(self.r)

        def stato_parita(self, slug):
            ap = sum(1 for x in self.r if x["stato"] == "aperto")
            ve = sum(1 for x in self.r if x["stato"] == "verificato")
            return {"violazioni_aperte": ap, "violazioni_verificate": ve,
                    "badge_vip": ap == 0 and ve == 0, "penalita": ve > 0}
    return confronta, e_viol, punteggio, _G


def autoprova():
    misure_si = [("a", True, ""), ("b", True, ""), ("c", True, "")]
    misure_no = [("a", False, "0"), ("b", False, "0"), ("c", False, "0")]
    casi = (("moduli finti SANI + misurabilita' SI'", None, misure_si, set()),
            ("moduli finti SANI + misurabilita' NO (tre NO)", None, misure_no, {"P4", "NON"}),
            ("una fee nascosta all'ospite", "fee_nascosta", misure_si, {"P1"}),
            ("il confronto dice che l'OTA costa meno", "ota_costa_meno", misure_si, {"P1"}),
            ("la violazione scatta gia' sul confine (>=)", "confine_sbagliato", misure_si, {"P2"}),
            ("la violazione verificata non penalizza", "niente_penalita", misure_si, {"P3"}))
    righe, riuscita = [], True
    for nome, guasto, misure, rosse_attese in casi:
        c, v, p, g = moduli_finti(guasto)
        verde, passi, motivi, den = giudica(relazioni(c, v, p, g, casi=40, seme=1), misure)
        rosse = set(m.split(" ")[0] for m in motivi)
        ok = (rosse == rosse_attese)
        riuscita = riuscita and ok
        righe.append("   %-48s -> rosse %-10s (attese %-10s) den %d%s" % (
            nome, ",".join(sorted(rosse)) or "-", ",".join(sorted(rosse_attese)) or "-", den,
            "" if ok else "   ⛔ NON E' QUELLO CHE DOVEVA DIRE: %s" % "; ".join(motivi)[:200]))
    return riuscita, righe


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    os.chdir(RADICE)
    casi = int(argv[argv.index("--casi") + 1]) if "--casi" in argv else CASI_DI_SERIE
    print("=" * 86)
    print("🧾 ESAME DEL BLOCCO 4 — casella «%s ...» (fase125 + fase190, %d casi per relazione)" % (MARCA, casi))
    print("=" * 86)
    if "--autoprova" in argv:
        print("🔁 AUTOPROVA — l'esame si vede gridare e tacere su moduli finti (D18 punto 2)")
        riuscita, righe = autoprova()
        for r in righe:
            print(r)
        print("VERDETTO: %s" % ("✅ l'esame grida sui moduli storti e tace su quelli sani"
                                if riuscita else "⛔ L'ESAME NON E' AFFIDABILE"))
        return 0 if riuscita else 1
    if "--con-guasto" in argv and "--scrivi" in argv:
        print("⛔ FERMO: `--con-guasto` non scrive.")
        return 2
    tutte_ok, righe = precondizioni()
    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    for nome, ok, motivo in righe:
        print("  %-9s %-62s %s" % ("OK" if ok else "⛔ NO", nome, motivo))
    if not tutte_ok:
        print("VERDETTO: ⛔ FERMO — una precondizione non regge: NON misuro e NON scrivo.")
        return 2
    c, v, p, g = moduli_veri()
    if "--con-guasto" in argv:
        print("⚠️  PASSATA COL GUASTO DENTRO: il confronto dice che l'OTA costa un centesimo MENO di noi")
        vero = c

        def c(netto, **kw):
            r = dict(vero(netto, **kw))
            r["ota_totale_cents"] = r["nostro_totale_cents"] - 1
            return r
    esiti = relazioni(c, v, p, g, casi=casi)
    verde, passi, motivi, den = giudica(esiti, misurabilita())
    print("")
    for nome, ok, dettaglio in passi:
        print("  %s  %s%s" % ("OK  " if ok else "ROSSO", nome, ("  -> " + dettaglio[:300]) if dettaglio else ""))
    print("")
    print("VERDETTO: %s — %d passi su %d, denominatore %d (casi generati)"
          % ("✅ VERDE" if verde else "⛔ ROSSO", sum(1 for _n, ok, _d in passi if ok), len(passi), den))
    if motivi:
        print("   perche': %s" % "; ".join(motivi)[:700])
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
