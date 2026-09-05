"""L'ESAME DELLA CASELLA 3 DEL BLOCCO PRENOTAZIONI — «iCal ha una difesa dal RITARDO 15 min-2 ore
(oggi: zero, e' la finestra delle prenotazioni fantasma)».

    python collaudi/esame_ical.py                misura e MOSTRA
    python collaudi/esame_ical.py --scrivi       misura e SCRIVE nella scheda (anche un rosso)
    python collaudi/esame_ical.py --con-guasto   la rilettura prima della conferma e' SPENTA:
                                                 deve gridare, NON scrive mai
    python collaudi/esame_ical.py --autoprova    il giudizio sui passi, nelle due direzioni

COSA MISURA, dalle rotte VERE (fase83) con un'OTA FINTA: un alloggio con una unita', l'host salva
l'URL del suo calendario Airbnb/Booking (POST /api/host/ical con `url`). Poi l'OTA finta occupa
notti NUOVE fra una lettura e l'altra, e si guarda cosa fa la macchina:
  · SALVATAGGIO: la prima lettura blocca subito le notti dell'OTA e scrive la riga di registro;
  · TICK: dopo 15 minuti (orologio iniettato) il giro periodico rilegge e blocca le notti nuove;
  · CONFERMA: l'OTA occupa altre notti e NESSUN tick e' passato -- la vetrina le da' ancora libere
    (il preventivo passa) -- ma al momento di PRENOTARE la macchina rilegge il feed (l'ultimo
    tentativo ha piu' di 60 s) e la prenotazione viene RIFIUTATA: la finestra fantasma e' chiusa;
  · FAIL-OPEN: se l'OTA non risponde, la prenotazione su notti libere passa lo stesso e il
    registro dice `esito=errore` (dichiarato: mai perdere una prenotazione per un'OTA giu');
  · FEED ROTTO: quattro letture fallite di fila (un'ora) diventano un'anomalia del Guardiano;
  · REGISTRO: ogni lettura ha la sua riga con l'ORA ESATTA (METODO §4.2) e MAI l'URL intero.
⛔ D18: `precondizioni()` ferma il giro; `--autoprova` e `--con-guasto`; `NON_GUARDA`; guardia
   `test_pipeline_ci.TestLEsameDellICalNonPuoBARARE`.
"""
import datetime
import logging
import os
import shutil
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

BLOCCO = 2
INDICE_CASELLA = 2
COMANDO = "python collaudi/esame_ical.py --scrivi"
PASSI = []
SEZIONI_ATTESE = ("salvataggio", "tick", "conferma", "fail-open", "feed rotto", "registro")
URL = "https://www.airbnb.com/calendar/ical/999999.ics?s=segretoDellEsame"
SEGRETO = "segretoDellEsame"

NON_GUARDA = (
    "la rete VERA: l'OTA e' finta (gancio `RETE` di fase203) e il tempo e' iniettato (gancio "
    "`OROLOGIO`); il percorso urllib su https lo provera' il primo host vero, e la sua riga nel "
    "registro del server sara' la prova",
    "il ritardo con cui le OTA leggono il NOSTRO feed (1-3 ore, non governabile da qui): questa "
    "casella chiude la finestra nel verso nostro, prima di ogni nostra conferma; nel verso loro "
    "la chiude la mano dell'host, che il messaggio di prenotazione (fase152) avvisa di BLOCCARE "
    "subito le date sull'OTA quando un calendario esterno e' collegato -- il gesto dell'host non "
    "lo prova nessun esame",
    "le altre tre caselle del blocco: non le tocca",
)


def passo(sezione, nome, ok, dettaglio=""):
    PASSI.append((sezione, nome, bool(ok), dettaglio))
    print("  %s  [%s] %s%s" % ("OK  " if ok else "ROSSO", sezione, nome,
                                ("  -> " + dettaglio) if dettaglio else ""))
    return bool(ok)


def giudica(passi, sezioni_attese=SEZIONI_ATTESE):
    """Verde SOLO se ogni sezione attesa ha almeno un passo e nessun passo e' rosso."""
    motivi = []
    viste = set(p[0] for p in passi)
    for s in sezioni_attese:
        if s not in viste:
            motivi.append("sezione «%s» mai misurata" % s)
    for s, nome, ok, dettaglio in passi:
        if not ok:
            motivi.append("[%s] %s%s" % (s, nome, (" (%s)" % dettaglio) if dettaglio else ""))
    return (not motivi), motivi, len(passi)


def precondizioni():
    fuori = []
    try:
        blocco = [b for b in BLOCCHI if b["ordine"] == BLOCCO]
        cond = blocco[0]["finito_quando"] if len(blocco) == 1 else ()
        testo = str(cond[INDICE_CASELLA]) if len(cond) > INDICE_CASELLA else ""
        ok = "iCal" in testo and "RITARDO" in testo
        fuori.append(("la casella esiste nel piano e parla della difesa dal RITARDO iCal", ok,
                      " ".join(testo.split())[:70] + ("..." if len(testo) > 70 else "")))
    except Exception as e:
        fuori.append(("la casella esiste nel piano", False, "%s: %s" % (type(e).__name__, e)))
    try:
        impronta = scheda.impronta_del_blocco(BLOCCO)
        fuori.append(("il blocco ha un'impronta", bool(impronta), impronta or "il piano non si legge"))
    except Exception as e:
        fuori.append(("il blocco ha un'impronta", False, str(e)))
    try:
        import fase203_ical_orologio as m
        from fase82_ical_sync import sincronizza  # noqa: F401
        from collaudi.gare_estreme import _host_pubblica, _quote, _sistema  # noqa: F401
        from collaudi.multivettore import _g, _host, _router  # noqa: F401
        ganci = hasattr(m, "OROLOGIO") and hasattr(m, "RETE") and hasattr(m, "prima_di_confermare")
        fuori.append(("l'orologio dell'iCal, il parser e il banco si importano, coi ganci", ganci,
                      "fase203 (OROLOGIO, RETE, prima_di_confermare), fase82, gare_estreme, multivettore"))
    except Exception as e:
        fuori.append(("l'orologio dell'iCal, il parser e il banco si importano", False, str(e)))
    return all(ok for _, ok, _ in fuori), fuori


def ics(*periodi):
    righe = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//OTA finta//EN"]
    for ci, co in periodi:
        righe += ["BEGIN:VEVENT", "DTSTART;VALUE=DATE:" + ci.replace("-", ""),
                  "DTEND;VALUE=DATE:" + co.replace("-", ""), "SUMMARY:Reserved", "END:VEVENT"]
    righe.append("END:VCALENDAR")
    return "\r\n".join(righe) + "\r\n"


class OtaFinta(object):
    """L'OTA: serve il calendario che le si dice; puo' essere «giu'»."""

    def __init__(self):
        self.testo = ics()
        self.giu = False
        self.chiamate = []

    def fetch(self, url, timeout):
        self.chiamate.append((url, timeout))
        if self.giu:
            raise TimeoutError("l'OTA non risponde: " + url)
        return self.testo


class Registro(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.righe = []

    def emit(self, record):
        try:
            self.righe.append((record.levelname, record.getMessage()))
        except Exception:
            pass


class Banco(object):
    def __init__(self, d):
        from collaudi.gare_estreme import _host_pubblica, _sistema
        from collaudi.multivettore import _g, _host, _router
        self.d = d
        self.sis = _sistema(d)
        self.router = _router(self.sis)
        self.g = _g(self.router)
        self.tk = _host(self.g)
        oggi = datetime.date.today()
        self.oggi = oggi
        self.slug = _host_pubblica(self.g, self.tk, "ical-una", 1, 20000, oggi.isoformat(),
                                   (oggi + datetime.timedelta(days=60)).isoformat())

    def notti(self, da_giorni, quante=2):
        ci = self.oggi + datetime.timedelta(days=da_giorni)
        return ci.isoformat(), (ci + datetime.timedelta(days=quante)).isoformat()

    def totali(self, giorno):
        s = self.sis.inventario.stato_giorno(self.slug, giorno)
        return s["unita_totali"] if isinstance(s, dict) else None

    def prenota(self, ci, co, email):
        from collaudi.gare_estreme import _quote
        tok = _quote(self.g, self.slug, ci, co)
        if not tok:
            return None, None
        s, corpo = self.g("POST", "/api/concierge/book", {"quote_token": tok, "email": email})
        return s, corpo


def esame(b, m, ota, registro, orologio, con_guasto=False):
    N1, N2, N3, N4 = b.notti(10), b.notti(20), b.notti(30), b.notti(40)

    # ── SALVATAGGIO ───────────────────────────────────────────────────────────────────
    ota.testo = ics(N1)
    s, corpo = b.g("POST", "/api/host/ical", {"alloggio_id": b.slug, "url": URL}, b.tk)
    passo("salvataggio", "l'host salva l'URL del feed (POST /api/host/ical con url) -> 200", s == 200,
          "status=%s corpo=%r" % (s, corpo))
    letture = (corpo or {}).get("letture") if isinstance(corpo, dict) else None
    passo("salvataggio", "il feed e' salvato UNA volta e letto subito",
          isinstance(corpo, dict) and corpo.get("feed_salvati") == 1 and bool(letture)
          and letture[0].get("esito") == "ok" and letture[0].get("giorni_bloccati") == 2,
          "letture=%r" % (letture,))
    passo("salvataggio", "le notti dell'OTA %s..%s sono bloccate (unita_totali=0)" % N1,
          b.totali(N1[0]) == 0, "unita_totali=%r" % b.totali(N1[0]))
    passo("salvataggio", "un secondo salvataggio dello stesso URL non raddoppia il feed",
          b.g("POST", "/api/host/ical", {"alloggio_id": b.slug, "url": URL}, b.tk)[1].get("feed_salvati") == 1)
    passo("salvataggio", "un URL non https viene rifiutato (422)",
          b.g("POST", "/api/host/ical", {"alloggio_id": b.slug, "url": "http://x.y/1.ics"}, b.tk)[0] == 422)
    passo("salvataggio", "un alloggio non testuale viene rifiutato (422), non passa al controllo di proprieta'",
          b.g("POST", "/api/host/ical", {"alloggio_id": 123, "url": URL}, b.tk)[0] == 422)

    # ── TICK ──────────────────────────────────────────────────────────────────────────
    ota.testo = ics(N1, N2)
    orologio[0] += m.RILETTURA_SEC
    c = m.giro_periodico(b.sis)
    passo("tick", "dopo 15 minuti il giro periodico rilegge il feed", c.get("letti") == 1, "conteggio=%r" % (c,))
    passo("tick", "e blocca le notti NUOVE %s..%s dell'OTA" % N2, b.totali(N2[0]) == 0,
          "unita_totali=%r" % b.totali(N2[0]))
    c2 = m.giro_periodico(b.sis)
    passo("tick", "un secondo giro nello stesso minuto NON tocca la rete (recente)",
          c2.get("recenti") == 1 and c2.get("letti") == 0, "conteggio=%r" % (c2,))

    # ── CONFERMA: la finestra fantasma ────────────────────────────────────────────────
    ota.testo = ics(N1, N2, N3)                      # l'OTA vende N3 ADESSO, nessun tick passa
    da_vetrina = b.sis.inventario.disponibile(b.slug, N3[0], N3[1])
    passo("conferma", "l'OTA ha appena venduto %s..%s e la nostra vetrina le da' ancora LIBERE" % N3,
          da_vetrina is True, "disponibile=%r (questa e' la finestra fantasma)" % (da_vetrina,))
    orologio[0] += m.RILETTURA_CONFERMA_SEC + 1
    prima = len(ota.chiamate)
    s, corpo = b.prenota(N3[0], N3[1], "fantasma@x.it")
    passo("conferma", "al momento di PRENOTARE la macchina rilegge il feed dell'OTA",
          len(ota.chiamate) == prima + 1, "chiamate all'OTA: prima=%d dopo=%d" % (prima, len(ota.chiamate)))
    passo("conferma", "e la prenotazione sulle notti appena vendute viene RIFIUTATA (409/422)",
          s in (409, 422), "status=%s corpo=%r" % (s, corpo))
    passo("conferma", "le notti %s..%s sono ora bloccate anche da noi" % N3, b.totali(N3[0]) == 0,
          "unita_totali=%r" % b.totali(N3[0]))
    s_ok, corpo_ok = b.prenota(N4[0], N4[1], "vero@x.it")
    passo("conferma", "e una prenotazione su notti davvero libere %s..%s passa (201)" % N4, s_ok == 201,
          "status=%s" % s_ok)
    prima = len(ota.chiamate)
    b.prenota(b.notti(50)[0], b.notti(50)[1], "subito@x.it")
    passo("conferma", "una seconda conferma entro 60 s NON rilegge (l'ultimo tentativo e' recente)",
          len(ota.chiamate) == prima, "chiamate=%d" % (len(ota.chiamate) - prima))

    # ── FAIL-OPEN ─────────────────────────────────────────────────────────────────────
    ota.giu = True
    orologio[0] += m.RILETTURA_CONFERMA_SEC + 1
    N5 = b.notti(54)
    s, corpo = b.prenota(N5[0], N5[1], "coraggioso@x.it")
    passo("fail-open", "l'OTA e' giu': la prenotazione su notti libere passa lo stesso (201)", s == 201,
          "status=%s" % s)
    passo("fail-open", "e il registro dice esito=errore per quella rilettura",
          any("esito=errore" in r and "motivo=conferma" in r for _, r in registro.righe))

    # ── FEED ROTTO ────────────────────────────────────────────────────────────────────
    for _ in range(m.ERRORI_PER_ALLARME):
        orologio[0] += m.RILETTURA_SEC
        m.giro_periodico(b.sis)
    rotti = m.anomalie(b.sis)
    passo("feed rotto", "%d letture fallite di fila (un'ora) sono un'anomalia del Guardiano" % m.ERRORI_PER_ALLARME,
          len(rotti) == 1 and b.slug in rotti[0], "anomalie=%r" % (rotti,))
    rap = m.con_feed_rotti({"pulito": True, "conta": 0, "anomalie": {}}, b.sis)
    passo("feed rotto", "e il rapporto del Guardiano non e' piu' pulito",
          rap.get("pulito") is False and rap.get("conta") == 1, "rapporto=%r" % (rap,))
    passo("feed rotto", "il registro grida «%s»" % m.MARCA_ROTTO,
          any(m.MARCA_ROTTO in r and lv == "CRITICAL" for lv, r in registro.righe))
    ota.giu = False
    orologio[0] += m.RILETTURA_SEC
    m.giro_periodico(b.sis)
    passo("feed rotto", "una lettura buona spegne l'anomalia", m.anomalie(b.sis) == [])

    # ── REGISTRO ──────────────────────────────────────────────────────────────────────
    righe_sync = [r for _, r in registro.righe if r.startswith(m.MARCA + " |")]
    ore = [r.split(" | ")[1] for r in righe_sync if len(r.split(" | ")) > 2]
    ben_formate = [o for o in ore if len(o) == 19 and o[4] == "-" and o[10] == "T"]
    passo("registro", "ogni lettura ha la sua riga «%s» con l'ORA ESATTA" % m.MARCA,
          len(righe_sync) >= 8 and len(ben_formate) == len(righe_sync),
          "righe=%d ben formate=%d" % (len(righe_sync), len(ben_formate)))
    passo("registro", "e nessuna riga porta l'URL intero (il segreto del feed)",
          not any(SEGRETO in r for _, r in registro.righe))
    passo("registro", "le righe distinguono i motivi: salvataggio, tick, conferma",
          all(any("motivo=%s" % mo in r for r in righe_sync) for mo in ("salvataggio", "tick", "conferma")))


def passi_finti(rossi=()):
    fuori = []
    for s in SEZIONI_ATTESE:
        for i in range(2):
            fuori.append((s, "passo %d" % i, not (s in rossi and i == 1), ""))
    return fuori


def autoprova():
    casi = (("tutte le sezioni verdi", passi_finti(), True),
            ("un rosso nella conferma", passi_finti(rossi=("conferma",)), False),
            ("manca la sezione del registro", [p for p in passi_finti() if p[0] != "registro"], False),
            ("nessun passo", [], False))
    righe, riuscita = [], True
    for nome, passi, atteso in casi:
        verde, motivi, den = giudica(passi)
        ok = verde == atteso
        riuscita = riuscita and ok
        righe.append("   %-30s -> %-6s (atteso %-6s) denominatore %d%s"
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
    print("🧾 ESAME DEL BLOCCO PRENOTAZIONI — casella 3: la difesa dal RITARDO dell'iCal")
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

    con_guasto = "--con-guasto" in argv
    if "--scrivi" in argv and con_guasto:
        print("⛔ FERMO: `--con-guasto` non scrive: la misura di una difesa spenta apposta non e' la casella.")
        return 2
    if con_guasto:
        print("⚠️  PASSATA COL GUASTO DENTRO: la rilettura PRIMA DELLA CONFERMA e' spenta")

    import fase203_ical_orologio as m
    condizioni = [bl for bl in BLOCCHI if bl["ordine"] == BLOCCO][0]["finito_quando"]
    ota = OtaFinta()
    registro = Registro()
    lg = logging.getLogger("core_auto.ical_orologio")
    livello_prima = lg.level
    lg.addHandler(registro)
    lg.setLevel(logging.INFO)
    orologio = [int(time.time())]
    vecchi = (m.OROLOGIO, m.RETE, m.prima_di_confermare)
    m.OROLOGIO, m.RETE = (lambda: orologio[0]), ota.fetch
    if con_guasto:
        m.prima_di_confermare = lambda *a, **k: []
    d = tempfile.mkdtemp()
    try:
        b = Banco(d)
        esame(b, m, ota, registro, orologio, con_guasto=con_guasto)
    except Exception as e:                       # noqa: BLE001 - un esame esploso e' un rosso
        passo("esame", "l'esame e' ESPLOSO", False, "%s: %s" % (type(e).__name__, e))
    finally:
        m.OROLOGIO, m.RETE, m.prima_di_confermare = vecchi
        lg.removeHandler(registro)
        lg.setLevel(livello_prima)
        shutil.rmtree(d, ignore_errors=True)

    verde, motivi, denominatore = giudica(PASSI)
    print("")
    print("VERDETTO: %s — passi %d, rossi %d, denominatore %d"
          % ("✅ VERDE" if verde else "⛔ ROSSO", len(PASSI), sum(1 for p in PASSI if not p[2]), denominatore))
    for mo in motivi:
        print("   perche': %s" % mo)

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
