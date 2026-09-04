"""L'ESAME DELLA CASELLA 1 DEL BLOCCO PRENOTAZIONI — «la macchina a stati copre cancellazioni,
modifiche, no-show e sovra-affitto».

    python collaudi/esame_prenotazioni.py                misura e MOSTRA (tutto in-process, Stripe finto)
    python collaudi/esame_prenotazioni.py --scrivi       misura e SCRIVE nella scheda (anche un rosso,
                                                         col suo motivo)
    python collaudi/esame_prenotazioni.py --con-guasto   la cancellazione dell'ospite NON marca il
                                                         rimborso (il guasto): deve gridare, NON scrive
    python collaudi/esame_prenotazioni.py --autoprova    il giudizio sui passi, nelle due direzioni

⛔ IL TESTO DELLA CASELLA NON SI RICOPIA: si legge da `collaudi/piano.py` (e' la chiave).

COSA VUOL DIRE «COPRE», dichiarato (D18) — una decisione presa dalla chat B il 2026-09-05 col mandato
del fondatore («vai avanti con il prossimo blocco che dice piano.py»), scritta nel registro e
rovesciabile: la macchina a stati (`fase199.STATI_PRENOTAZIONE` / `EVENTI_PRENOTAZIONE`, lo specchio
dei CAS di `fase162`) COPRE una situazione quando
  (a) i suoi teoremi Z3 sono DIMOSTRATI e il modello COINCIDE col codice vero (la guardia
      `test_fase199_transizioni`, eseguita qui, non riletta);
  (b) lo stato di una prenotazione lo scrive SOLO `fase162` con gli eventi del modello (censimento sul
      sorgente: nessun `UPDATE/INSERT pendenti` fuori da fase162, e i letterali `SET stato='...'` di
      fase162 stanno tutti fra gli stati del modello);
  (c) uno SCENARIO guidato dalle rotte vere (quote -> book -> webhook -> ...) finisce nello stato che
      il modello prescrive, e l'inventario resta coerente (I1 dell'auditor `fase202` sugli archivi
      dello scenario).
Le quattro situazioni, misurate nel prodotto prima di scrivere l'esame:
  CANCELLAZIONI   ospite -> evento `marca_da_rimborsare` ('rimborsato'); host -> `marca_cancellata_host`
                  ('cancellata_host'); in entrambi i casi le notti tornano libere.
  MODIFICHE       nel prodotto NON esiste una rotta che cambi le date o lo stato di una prenotazione
                  esistente (censimento su fase83: nessuna funzione «modific*» che tocchi i pendenti;
                  lo stack vecchio fase34/36 non e' importato dalla produzione): modificare = cancellare
                  e riprenotare, e le due mosse sono entrambe nel modello. Lo scenario le fa.
  NO-SHOW         non e' una transizione: l'ospite che non si presenta lascia la prenotazione 'pagato',
                  la garanzia matura a check-in + 24 h e l'host viene pagato; la penale (solo «paga in
                  struttura», `_forse_penale_struttura`) e la statistica (`fase62`) vivono FUORI dalla
                  macchina e non toccano i pendenti (censimento). Lo scenario lo prova.
  SOVRA-AFFITTO   e' uno stato IMPOSSIBILE, non uno stato: lo impedisce l'inventario atomico (`fase58`)
                  e la regola del modello «`conferma` solo da in_attesa/scaduto» col re-blocco: un
                  pagamento tardivo su una stanza presa da un altro finisce 'rimborsato'. Lo scenario
                  lo fa (una unita', due ospiti, l'hold che scade sull'orologio NOSTRO) e l'auditor
                  I1 giudica l'inventario alla fine.

⛔ D18: `precondizioni()` ferma il giro; `--autoprova` e `--con-guasto`; `NON_GUARDA`; guardia
   `test_pipeline_ci.TestLEsameDellePrenotazioniNonPuoBARARE`.
"""
import ast
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest

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

BLOCCO = 2
INDICE_CASELLA = 0
COMANDO = "python collaudi/esame_prenotazioni.py --scrivi"
SITUAZIONI = ("modello", "cancellazioni", "modifiche", "no_show", "sovra_affitto")
PASSI = []

NON_GUARDA = (
    "se il MODELLO sia quello giusto per il dominio: qui si misura che il modello e' dimostrato, che "
    "coincide col codice e che le quattro situazioni ci passano dentro; se una situazione nuova "
    "nascesse nel prodotto (una rotta di modifica), il censimento la vedrebbe come stato scritto "
    "fuori dal modello SOLO se scrive i pendenti: una rotta che cambiasse le date senza toccare lo "
    "stato non e' una transizione e questo esame non la giudica",
    "la penale del no-show «paga in struttura» (addebito sulla carta, gated da PAGA_STRUTTURA_ATTIVO) "
    "e la statistica di fase62: stanno fuori dalla macchina a stati per costruzione, e qui si misura "
    "solo che NON toccano i pendenti",
    "la gara vera (due prenotazioni nello stesso istante): e' la casella 2 del blocco, non questa",
    "Stripe: la rete e' sostituita (provider vero, fetch finto); i soldi che tornano sono la casella 2 "
    "del blocco SOLDI",
    "le altre tre caselle del blocco: non le tocca",
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


# --------------------------------------------------------------------------------------
# CENSIMENTI SUL SORGENTE (il denominatore non e' un elenco a mano)
# --------------------------------------------------------------------------------------
def _sorgente(nome):
    with io.open(os.path.join(RADICE, nome), encoding="utf-8", errors="replace") as f:
        return f.read()


def scrittori_dello_stato_fuori_da_fase162():
    """I file `fase*.py` (tranne fase162) che scrivono la tabella `pendenti` con SQL."""
    fuori = []
    for nome in sorted(os.listdir(RADICE)):
        if not (nome.startswith("fase") and nome.endswith(".py")) or nome.startswith("fase162"):
            continue
        if re.search(r"(UPDATE|INSERT\s+(OR\s+\w+\s+)?INTO)\s+pendenti\b", _sorgente(nome)):
            fuori.append(nome)
    return fuori


def stati_scritti_da_fase162():
    """I letterali `SET stato='...'` di fase162: il codice vero non deve conoscere stati suoi."""
    return sorted(set(re.findall(r"SET stato='([a-z_]+)'", _sorgente("fase162_pagamenti_pendenti.py"))))


def rotte_di_modifica_in_fase83():
    """Le funzioni di fase83 col nome «modific*» che toccano i pendenti (albero sintattico)."""
    albero = ast.parse(_sorgente("fase83_server.py"))
    fuori = []
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.FunctionDef) and "modific" in nodo.name.lower():
            testo = ast.unparse(nodo) if hasattr(ast, "unparse") else ""
            if "pendenti" in testo or "check_in" in testo:
                fuori.append(nodo.name)
    return fuori


def fase62_tocca_i_pendenti():
    return bool(re.search(r"pendenti|fase162", _sorgente("fase62_predictive_noshow.py")))


# --------------------------------------------------------------------------------------
# MISURA PRIMA SE STESSO (D18 punto 1)
# --------------------------------------------------------------------------------------
def precondizioni():
    fuori = []
    try:
        blocco = [b for b in BLOCCHI if b["ordine"] == BLOCCO]
        cond = blocco[0]["finito_quando"] if len(blocco) == 1 else ()
        testo = " ".join(str(cond[INDICE_CASELLA]).split()) if len(cond) > INDICE_CASELLA else ""
        fuori.append(("la casella esiste nel piano e parla della macchina a stati",
                      "macchina a stati" in testo, testo[:80] or "manca la prima casella"))
    except Exception as e:
        fuori.append(("la casella esiste nel piano", False, "%s: %s" % (type(e).__name__, e)))
    try:
        impronta = scheda.impronta_del_blocco(BLOCCO)
        fuori.append(("il blocco ha un'impronta", bool(impronta), impronta or "il piano non si legge"))
    except Exception as e:
        fuori.append(("il blocco ha un'impronta", False, str(e)))
    try:
        import z3
        fuori.append(("z3 e' importabile (i teoremi si dimostrano qui, non si rileggono)", True,
                      z3.get_version_string()))
    except Exception as e:
        fuori.append(("z3 e' importabile (i teoremi si dimostrano qui, non si rileggono)", False, str(e)))
    try:
        from fase199_invarianti import EVENTI_PRENOTAZIONE, STATI_PRENOTAZIONE
        from fase83_server import sweep_hold_una_passata  # noqa: F401
        from fase202_invarianti_archivi import scansiona_archivi  # noqa: F401
        fuori.append(("il modello, lo sweeper e l'auditor si importano", True,
                      "%d stati, %d eventi" % (len(STATI_PRENOTAZIONE), len(EVENTI_PRENOTAZIONE))))
    except Exception as e:
        fuori.append(("il modello, lo sweeper e l'auditor si importano", False, str(e)))
    return all(ok for _, ok, _ in fuori), fuori


# --------------------------------------------------------------------------------------
# IL BANCO: sistema vero, Stripe finto, orologio NOSTRO sui pendenti
# --------------------------------------------------------------------------------------
class Banco(object):

    def __init__(self, d):
        from collaudi.gare_estreme import _sistema
        from collaudi.multivettore import _g, _host, _router
        from fase162_pagamenti_pendenti import crea_pagamenti_pendenti
        self.d = d
        self.sis = _sistema(d)
        self.orologio = Orologio(time.time())
        self.sis.pagamenti_pendenti = crea_pagamenti_pendenti(d + "/p.db", orologio=self.orologio)
        self.router = _router(self.sis)
        self.g = _g(self.router)
        self.tk = _host(self.g)

    def alloggio(self, slug, unita, da, a):
        from collaudi.gare_estreme import _host_pubblica
        return _host_pubblica(self.g, self.tk, slug, unita, 10000, da, a)

    def prenota(self, slug, ci, co):
        from collaudi.gare_estreme import _quote
        tok = _quote(self.g, slug, ci, co)
        if not tok:
            return None, None
        s, b = self.g("POST", "/api/concierge/book", {"quote_token": tok, "email": "o@x.it"})
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

    def pagata(self, slug, ci, co):
        rif, vt = self.prenota(slug, ci, co)
        if rif:
            self.webhook(rif)
        return rif, vt


# --------------------------------------------------------------------------------------
# LE MISURE
# --------------------------------------------------------------------------------------
def misura_modello():
    print("\n--- MODELLO: teoremi Z3, concordanza col codice vero, chi scrive lo stato ---")
    from fase199_invarianti import STATI_PRENOTAZIONE, dimostra_transizioni
    from test_fase199_transizioni import TEOREMI_ATTESI
    ris = dimostra_transizioni()
    for t in TEOREMI_ATTESI:
        passo("modello", "teorema %s" % t, ris.get(t) == "DIMOSTRATO", str(ris.get(t))[:60])
    flusso = io.StringIO()
    suite = unittest.TestLoader().loadTestsFromName("test_fase199_transizioni")
    esito = unittest.TextTestRunner(stream=flusso, verbosity=0).run(suite)
    passo("modello", "la guardia di concordanza modello<->codice vero e' verde (%d collaudi)" % esito.testsRun,
          esito.wasSuccessful() and esito.testsRun > 0,
          "rossi=%d errori=%d" % (len(esito.failures), len(esito.errors)))
    fuori = scrittori_dello_stato_fuori_da_fase162()
    passo("modello", "nessun modulo fuori da fase162 scrive la tabella dei pendenti", not fuori, repr(fuori))
    scritti = stati_scritti_da_fase162()
    ignoti = [s for s in scritti if s not in STATI_PRENOTAZIONE]
    passo("modello", "gli stati che fase162 scrive stanno tutti nel modello", bool(scritti) and not ignoti,
          "scritti=%s ignoti=%s" % (scritti, ignoti))


def misura_cancellazioni(b, con_guasto=False):
    print("\n--- CANCELLAZIONI: ospite -> 'rimborsato', host -> 'cancellata_host', notti libere ---")
    slug = b.alloggio("casa-canc", 2, "2027-06-01", "2027-06-30")
    rif, vt = b.pagata(slug, "2027-06-05", "2027-06-07")
    passo("cancellazioni", "una prenotazione pagata dalle rotte vere", b.stato(rif) == "pagato",
          "stato=%s" % b.stato(rif))
    if con_guasto:
        b.sis.pagamenti_pendenti.marca_da_rimborsare = lambda *a, **k: False   # IL GUASTO
    s, c = b.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
    passo("cancellazioni", "l'ospite cancella: la rotta risponde 200 e il modello dice 'rimborsato'",
          s == 200 and b.stato(rif) == "rimborsato", "stato=%s http=%s" % (b.stato(rif), s))
    passo("cancellazioni", "e le notti tornano libere",
          b.sis.inventario.disponibile(slug, "2027-06-05", "2027-06-07") is True)
    rif2, _vt2 = b.pagata(slug, "2027-06-10", "2027-06-12")
    s, c = b.g("POST", "/api/host/cancella", {"riferimento": rif2}, b.tk)
    passo("cancellazioni", "l'host cancella: la rotta risponde 200 e il modello dice 'cancellata_host'",
          s == 200 and b.stato(rif2) == "cancellata_host", "stato=%s http=%s" % (b.stato(rif2), s))
    passo("cancellazioni", "e le notti tornano libere",
          b.sis.inventario.disponibile(slug, "2027-06-10", "2027-06-12") is True)


def misura_modifiche(b):
    print("\n--- MODIFICHE: nessuna rotta cambia una prenotazione; modificare = cancellare e riprenotare ---")
    rotte = rotte_di_modifica_in_fase83()
    passo("modifiche", "nessuna funzione «modific*» di fase83 tocca pendenti o date (censimento AST)",
          not rotte, repr(rotte))
    slug = b.alloggio("casa-mod", 1, "2027-07-01", "2027-07-31")
    rif, vt = b.pagata(slug, "2027-07-05", "2027-07-07")
    s, _ = b.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
    rif2, _ = b.pagata(slug, "2027-07-06", "2027-07-08")
    passo("modifiche", "cancellare e riprenotare date diverse: la vecchia 'rimborsato', la nuova 'pagato'",
          s == 200 and b.stato(rif) == "rimborsato" and b.stato(rif2) == "pagato",
          "vecchia=%s nuova=%s" % (b.stato(rif), b.stato(rif2)))
    passo("modifiche", "le notti della vecchia sono libere e quelle della nuova occupate",
          b.sis.inventario.disponibile(slug, "2027-07-05", "2027-07-06") is True
          and b.sis.inventario.disponibile(slug, "2027-07-06", "2027-07-08") is not True)


def misura_no_show(b):
    print("\n--- NO-SHOW: la prenotazione resta 'pagato', la garanzia matura, l'host e' pagato ---")
    passo("no_show", "fase62 (statistica dei no-show) non tocca i pendenti (censimento)",
          not fase62_tocca_i_pendenti())
    slug = b.alloggio("casa-noshow", 1, "2027-08-01", "2027-08-31")
    rif, _vt = b.pagata(slug, "2027-08-05", "2027-08-07")
    aperta = [g for g in b.sis.garanzia.aperte() if g.get("prenotazione_id") == rif]
    passo("no_show", "la garanzia e' aperta con lo sblocco a check-in + 24 h", bool(aperta),
          "sblocco_auto_ts=%s" % (aperta[0].get("sblocco_auto_ts") if aperta else None))
    ril = b.sis.garanzia.auto_rilascia(ora_ts=int(aperta[0]["sblocco_auto_ts"]) + 60 if aperta else 10 ** 10,
                                       dettagli=True) or []
    passo("no_show", "nessuno si presenta e nessuno contesta: allo sblocco la garanzia va all'host",
          any(r.get("prenotazione_id") == rif for r in ril), "rilasciate=%r" % (ril,))
    passo("no_show", "e la prenotazione RESTA 'pagato': il no-show non e' una transizione del modello",
          b.stato(rif) == "pagato", "stato=%s" % b.stato(rif))


def misura_sovra_affitto(b):
    print("\n--- SOVRA-AFFITTO: una unita', due ospiti, l'hold che scade sull'orologio NOSTRO ---")
    from fase83_server import sweep_hold_una_passata
    from fase202_invarianti_archivi import scansiona_archivi
    slug = b.alloggio("casa-una", 1, "2027-09-01", "2027-09-30")
    rif_a, _ = b.prenota(slug, "2027-09-05", "2027-09-07")
    passo("sovra_affitto", "il primo ospite tiene la stanza con un hold 'in_attesa'", b.stato(rif_a) == "in_attesa")
    rif_b, _ = b.prenota(slug, "2027-09-05", "2027-09-07")
    passo("sovra_affitto", "il secondo ospite NON puo' prenotare le stesse notti (inventario atomico)",
          rif_b is None, "seconda prenotazione=%r" % (rif_b,))
    b.orologio.ts += 3600
    sweep_hold_una_passata(b.sis, b.router)
    passo("sovra_affitto", "l'hold scade (evento `scadi`) e la stanza torna libera",
          b.stato(rif_a) == "scaduto" and b.sis.inventario.disponibile(slug, "2027-09-05", "2027-09-07") is True,
          "stato=%s" % b.stato(rif_a))
    rif_b, _ = b.prenota(slug, "2027-09-05", "2027-09-07")
    passo("sovra_affitto", "adesso il secondo ospite la prende", rif_b is not None and b.stato(rif_b) == "in_attesa")
    b.webhook(rif_a)
    passo("sovra_affitto", "il pagamento TARDIVO del primo non puo' ribloccare: il modello lo manda a 'rimborsato'",
          b.stato(rif_a) == "rimborsato" and b.stato(rif_b) == "in_attesa",
          "primo=%s secondo=%s" % (b.stato(rif_a), b.stato(rif_b)))
    r = scansiona_archivi(b.d, ora=lambda: int(time.time()))
    passo("sovra_affitto", "l'auditor I1 sugli archivi dello scenario non vede notti sovraprenotate",
          "I1" in r["verificati"] and "I1" not in r["violazioni"], "violazioni=%r" % (r["violazioni"],))


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
    print("🧾 ESAME DEL BLOCCO PRENOTAZIONI — casella 1: la macchina a stati copre le quattro situazioni")
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
        print("   rosso metterebbe nella scheda una macchina rotta apposta.")
        return 2

    tutte_ok, righe = precondizioni()
    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    for nome, ok, motivo in righe:
        print("  %-9s %-66s %s" % ("OK" if ok else "⛔ NO", nome, motivo))
    if not tutte_ok:
        print("VERDETTO: ⛔ FERMO — una precondizione non regge, quindi NON misuro e NON scrivo.")
        _stampa_non_guarda()
        return 2
    if con_guasto:
        print("⚠️  PASSATA COL GUASTO DENTRO: la cancellazione dell'ospite NON marca il rimborso")

    d = tempfile.mkdtemp()
    try:
        b = Banco(d)
        for situazione, f in (("modello", misura_modello),
                              ("cancellazioni", lambda: misura_cancellazioni(b, con_guasto)),
                              ("modifiche", lambda: misura_modifiche(b)),
                              ("no_show", lambda: misura_no_show(b)),
                              ("sovra_affitto", lambda: misura_sovra_affitto(b))):
            try:
                f()
            except Exception as e:                       # noqa: BLE001 - una situazione rotta e' un rosso
                passo(situazione, "la misura e' ESPLOSA", False, "%s: %s" % (type(e).__name__, e))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    verde, motivi, denominatore = giudica(PASSI)
    print("")
    print("VERDETTO: %s — passi %d, rossi %d, denominatore %d"
          % ("✅ VERDE" if verde else "⛔ ROSSO", len(PASSI), sum(1 for p in PASSI if not p[2]), denominatore))
    for m in motivi:
        print("   perche': %s" % m)

    condizioni = [bl for bl in BLOCCHI if bl["ordine"] == BLOCCO][0]["finito_quando"]
    if "--scrivi" in argv:
        print("")
        print("SCRITTURA NELLA SCHEDA")
        riga = scheda.registra(condizioni[INDICE_CASELLA], esito=verde, denominatore=denominatore,
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
