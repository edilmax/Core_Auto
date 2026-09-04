"""L'ESAME DELLA CASELLA 2 DEL BLOCCO PRENOTAZIONI — «il blocco atomico regge sotto gara
(misurato: 10 giri x 24 agenti, 1 conferma)».

    python collaudi/esame_gare.py                     10 giri x 24 agenti (i numeri li legge dalla
                                                      casella), misura e MOSTRA
    python collaudi/esame_gare.py --scrivi            misura e SCRIVE nella scheda (anche un rosso)
    python collaudi/esame_gare.py --giri 2 --agenti 6 prova in piccolo (NON scrive: i numeri della
                                                      casella sono la misura)
    python collaudi/esame_gare.py --con-guasto        il blocco NON e' atomico (controlla, aspetta,
                                                      scrive): deve gridare, NON scrive mai
    python collaudi/esame_gare.py --autoprova         il giudizio sui passi, nelle due direzioni

COSA MISURA. Un alloggio con UNA unita'. A ogni giro N agenti (24) chiedono N preventivi DISTINTI
(chiavi idempotenti diverse) sulle stesse notti e prenotano TUTTI NELLO STESSO ISTANTE (barriera di
thread): deve passare ESATTAMENTE UNA prenotazione (201) e le altre N-1 devono essere rifiutate in
modo controllato (409/422); poi il giudice indipendente — l'auditor `fase202` sugli archivi dello
scenario — non deve vedere una notte con `unita_occupate > unita_totali` ne' due pagate sovrapposte
(I1). Dieci giri su notti diverse, cosi' un giro non aiuta il successivo.

PERCHE' IL GIUDICE E' ESTERNO ALLA GARA: contare i 201 dice cosa ha RISPOSTO il server; l'inventario
dice cosa ha SCRITTO. Sono due cose diverse (una risposta 409 con la notte scalata lo stesso e' il
caso peggiore), e la casella chiede la seconda.

⛔ I NUMERI 10 E 24 NON SONO SCRITTI QUI: si leggono dal testo della casella (`piano.py`), che e' la
   chiave della scheda. `--giri`/`--agenti` piu' piccoli servono a provare in piccolo e NON scrivono.
⛔ D18: `precondizioni()` ferma il giro; `--autoprova` e `--con-guasto`; `NON_GUARDA`; guardia
   `test_pipeline_ci.TestLEsameDelleGareNonPuoBARARE`.
"""
import datetime
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
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

BLOCCO = 2
INDICE_CASELLA = 1
COMANDO = "python collaudi/esame_gare.py --scrivi"
PASSI = []

NON_GUARDA = (
    "processi diversi su macchine diverse: qui gli agenti sono thread nello stesso processo e "
    "l'archivio e' un solo file sqlite; in produzione c'e' un solo processo per sito, quindi e' "
    "la stessa forma, ma non e' una prova su piu' repliche",
    "la gara fra una cancellazione e una nuova prenotazione, o fra un blocco-data dell'host e un "
    "ospite: le prova `collaudi/gare_estreme.py` (A3, A4), non questa casella",
    "le notti sono scelte diverse per ogni giro: un giro non prova che l'unita' liberata da un "
    "rifiuto resti libera (quello e' il rilascio, provato altrove)",
    "le altre tre caselle del blocco: non le tocca",
)


def numeri_della_casella(testo):
    """(giri, agenti) letti dal testo della casella. None se il testo non li dice."""
    m = re.search(r"(\d+)\s*giri\s*x\s*(\d+)\s*agenti", " ".join(str(testo).split()))
    return (int(m.group(1)), int(m.group(2))) if m else None


def passo(giro, nome, ok, dettaglio=""):
    PASSI.append((giro, nome, bool(ok), dettaglio))
    print("  %s  [giro %s] %s%s" % ("OK  " if ok else "ROSSO", giro, nome,
                                     ("  -> " + dettaglio) if dettaglio else ""))
    return bool(ok)


def giudica(passi, giri_attesi):
    """Verde SOLO se ci sono `giri_attesi` giri, ognuno con almeno un passo, e nessun rosso."""
    motivi = []
    visti = sorted(set(p[0] for p in passi if isinstance(p[0], int)))
    if len(visti) < giri_attesi:
        motivi.append("giri misurati %d su %d" % (len(visti), giri_attesi))
    for g, nome, ok, dettaglio in passi:
        if not ok:
            motivi.append("[giro %s] %s%s" % (g, nome, (" (%s)" % dettaglio) if dettaglio else ""))
    return (not motivi), motivi, len(passi)


def precondizioni():
    fuori = []
    try:
        blocco = [b for b in BLOCCHI if b["ordine"] == BLOCCO]
        cond = blocco[0]["finito_quando"] if len(blocco) == 1 else ()
        testo = str(cond[INDICE_CASELLA]) if len(cond) > INDICE_CASELLA else ""
        numeri = numeri_della_casella(testo)
        fuori.append(("la casella esiste nel piano e dice quanti giri e quanti agenti", bool(numeri),
                      "giri=%s agenti=%s" % numeri if numeri else "il testo non dice «N giri x M agenti»"))
    except Exception as e:
        fuori.append(("la casella esiste nel piano", False, "%s: %s" % (type(e).__name__, e)))
    try:
        impronta = scheda.impronta_del_blocco(BLOCCO)
        fuori.append(("il blocco ha un'impronta", bool(impronta), impronta or "il piano non si legge"))
    except Exception as e:
        fuori.append(("il blocco ha un'impronta", False, str(e)))
    try:
        from fase58_channel_manager import EsitoPrenotazione  # noqa: F401
        from fase202_invarianti_archivi import scansiona_archivi  # noqa: F401
        from collaudi.gare_estreme import _host_pubblica, _quote, _sistema  # noqa: F401
        fuori.append(("inventario, auditor e banco delle gare si importano", True, "fase58, fase202, gare_estreme"))
    except Exception as e:
        fuori.append(("inventario, auditor e banco delle gare si importano", False, str(e)))
    return all(ok for _, ok, _ in fuori), fuori


# --------------------------------------------------------------------------------------
class Banco(object):

    def __init__(self, d):
        from collaudi.gare_estreme import _sistema
        from collaudi.multivettore import _g, _host, _router
        self.d = d
        self.sis = _sistema(d)
        self.router = _router(self.sis)
        self.g = _g(self.router)
        self.tk = _host(self.g)
        oggi = datetime.date.today()
        from collaudi.gare_estreme import _host_pubblica
        self.slug = _host_pubblica(self.g, self.tk, "gara-una", 1, 20000, oggi.isoformat(),
                                   (oggi + datetime.timedelta(days=60)).isoformat())
        self.oggi = oggi

    def notti_del_giro(self, giro):
        ci = self.oggi + datetime.timedelta(days=3 + 2 * giro)
        return ci.isoformat(), (ci + datetime.timedelta(days=1)).isoformat()


def blocco_NON_atomico(inv):
    """IL GUASTO: un `blocca` che controlla, aspetta, e poi scrive -- senza transazione. E' la forma
    che il blocco vero (`BEGIN IMMEDIATE` + ricontrollo) esiste per impedire."""
    from fase58_channel_manager import EsitoPrenotazione, notti

    def rotto(alloggio_id, check_in, check_out, *, idem_key, origine="centrale"):
        elenco = notti(check_in, check_out)
        if elenco is None:
            return EsitoPrenotazione(False, "date_non_valide")
        con = inv._apri()
        try:
            for g in elenco:
                row = con.execute("SELECT unita_totali, unita_occupate FROM inventario "
                                  "WHERE alloggio_id=? AND giorno=?", (str(alloggio_id), g)).fetchone()
                if row is None or row["unita_occupate"] >= row["unita_totali"]:
                    return EsitoPrenotazione(False, "pieno", notti=len(elenco))
            time.sleep(0.02)                               # la finestra fra controllo e scrittura
            for g in elenco:
                con.execute("UPDATE inventario SET unita_occupate = unita_occupate + 1 "
                            "WHERE alloggio_id=? AND giorno=?", (str(alloggio_id), g))
            con.commit()
            return EsitoPrenotazione(True, "", notti=len(elenco))
        finally:
            con.close()
    return rotto


def gara(b, giro, agenti):
    from collaudi.gare_estreme import _quote
    from fase202_invarianti_archivi import scansiona_archivi
    ci, co = b.notti_del_giro(giro)
    tokens = [_quote(b.g, b.slug, ci, co) for _ in range(agenti)]
    passo(giro, "%d preventivi distinti sulle stesse notti %s..%s" % (agenti, ci, co),
          all(tokens) and len(set(tokens)) == agenti, "ottenuti=%d" % sum(1 for t in tokens if t))
    barriera = threading.Barrier(agenti)
    esiti, lock = [], threading.Lock()

    def corri(tok, i):
        barriera.wait()
        s, corpo = b.g("POST", "/api/concierge/book", {"quote_token": tok, "email": "g%d@x.it" % i})
        with lock:
            esiti.append(s)
    fili = [threading.Thread(target=corri, args=(tokens[i], i)) for i in range(agenti)]
    for f in fili:
        f.start()
    for f in fili:
        f.join()
    conferme = sum(1 for s in esiti if s == 201)
    rifiuti = sum(1 for s in esiti if s in (409, 422))
    passo(giro, "%d agenti scattano insieme: ESATTAMENTE 1 conferma" % agenti, conferme == 1,
          "conferme=%d" % conferme)
    passo(giro, "e gli altri %d sono rifiutati in modo controllato (409/422)" % (agenti - 1),
          rifiuti == agenti - 1, "rifiuti=%d altri=%r" % (rifiuti, sorted(set(esiti) - {201, 409, 422})))
    r = scansiona_archivi(b.d, ora=lambda: int(time.time()))
    passo(giro, "il giudice esterno (auditor I1 sugli archivi) non vede notti sovraprenotate",
          "I1" in r["verificati"] and "I1" not in r["violazioni"], "violazioni=%r" % (r["violazioni"],))
    con = sqlite3.connect(b.d + "/i.db", timeout=30)
    try:
        occ = con.execute("SELECT unita_occupate, unita_totali FROM inventario WHERE alloggio_id=? AND giorno=?",
                          (b.slug, ci)).fetchone()
    finally:
        con.close()
    passo(giro, "e la notte contesa ha occupate == 1 su 1", bool(occ) and tuple(occ) == (1, 1), "riga=%r" % (occ,))
    return conferme


def passi_finti(giri=10, rossi=()):
    fuori = []
    for g in range(giri):
        for i in range(3):
            fuori.append((g, "passo %d" % i, not (g in rossi and i == 1), ""))
    return fuori


def autoprova():
    casi = (("dieci giri tutti verdi", passi_finti(10), 10, True),
            ("un rosso nel giro 4", passi_finti(10, rossi=(4,)), 10, False),
            ("solo nove giri", passi_finti(9), 10, False),
            ("nessun passo", [], 10, False))
    righe, riuscita = [], True
    for nome, passi, giri, atteso in casi:
        verde, motivi, den = giudica(passi, giri)
        ok = verde == atteso
        riuscita = riuscita and ok
        righe.append("   %-28s -> %-6s (atteso %-6s) denominatore %d%s"
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
    print("🧾 ESAME DEL BLOCCO PRENOTAZIONI — casella 2: il blocco atomico regge sotto gara")
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

    tutte_ok, righe = precondizioni()
    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    for nome, ok, motivo in righe:
        print("  %-9s %-62s %s" % ("OK" if ok else "⛔ NO", nome, motivo))
    if not tutte_ok:
        print("VERDETTO: ⛔ FERMO — una precondizione non regge, quindi NON misuro e NON scrivo.")
        _stampa_non_guarda()
        return 2

    condizioni = [bl for bl in BLOCCHI if bl["ordine"] == BLOCCO][0]["finito_quando"]
    giri_casella, agenti_casella = numeri_della_casella(condizioni[INDICE_CASELLA])
    giri = int(argv[argv.index("--giri") + 1]) if "--giri" in argv else giri_casella
    agenti = int(argv[argv.index("--agenti") + 1]) if "--agenti" in argv else agenti_casella
    con_guasto = "--con-guasto" in argv
    in_piccolo = giri < giri_casella or agenti < agenti_casella
    if "--scrivi" in argv and (con_guasto or in_piccolo):
        # ⛔ Un `if`, non un commento: la misura di un blocco rotto apposta, o di una gara piu'
        #    piccola di quella scritta nella casella, non e' la casella.
        print("⛔ FERMO: `--con-guasto` e una gara piu' piccola di «%d giri x %d agenti» non scrivono."
              % (giri_casella, agenti_casella))
        return 2
    if con_guasto:
        print("⚠️  PASSATA COL GUASTO DENTRO: il blocco dell'inventario NON e' atomico (controlla, aspetta, scrive)")
    print("GARA: %d giri x %d agenti (la casella dice %d x %d)" % (giri, agenti, giri_casella, agenti_casella))

    d = tempfile.mkdtemp()
    conferme_totali = 0
    try:
        b = Banco(d)
        if con_guasto:
            b.sis.inventario.blocca = blocco_NON_atomico(b.sis.inventario)
        for giro in range(giri):
            try:
                conferme_totali += gara(b, giro, agenti)
            except Exception as e:                       # noqa: BLE001 - un giro rotto e' un rosso
                passo(giro, "il giro e' ESPLOSO", False, "%s: %s" % (type(e).__name__, e))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    passo("tutti", "%d giri x %d agenti: %d conferme in tutto, una per giro" % (giri, agenti, conferme_totali),
          conferme_totali == giri)

    verde, motivi, denominatore = giudica(PASSI, giri)
    print("")
    print("VERDETTO: %s — passi %d, rossi %d, denominatore %d"
          % ("✅ VERDE" if verde else "⛔ ROSSO", len(PASSI), sum(1 for p in PASSI if not p[2]), denominatore))
    for m in motivi:
        print("   perche': %s" % m)

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
