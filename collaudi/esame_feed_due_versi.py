"""L'ESAME DELLA CASELLA 5 DEL BLOCCO PRENOTAZIONI — «il feed esterno vale nei DUE VERSI».

    python collaudi/esame_feed_due_versi.py              misura e MOSTRA
    python collaudi/esame_feed_due_versi.py --scrivi     misura e SCRIVE nella scheda (anche un rosso)
    python collaudi/esame_feed_due_versi.py --autoprova  il giudizio sui passi, nelle due direzioni

⛔ QUESTA CASELLA CHIEDE CINQUE COSE, NON UNA, e il testo e' preso da `piano.py`, mai ricopiato:
  1. RIAPERTURA  una notte chiusa da un feed si riapre quando sparisce da QUEL feed (e da
     nessun altro), **con lo stato di prima**;
  2. MANO DELL'HOST  ...e solo se l'host non l'ha toccata nel frattempo;
  3. ORIGINE  i blocchi esterni sono **oggetti con un'origine**, non sovrascritture dell'inventario;
  4. ECO  il nostro calendario riesportato dall'OTA non chiude le nostre notti;
  5. DA N A ZERO  un feed che passa da N eventi a zero non riapre niente **e diventa un'anomalia**.

COME MISURA: banco vero, non finto. Un `ChannelManager` (fase58) su SQLite in memoria, il parser
e il sincronizzatore VERI (`fase82.sincronizza`), e per l'eco il nostro esportatore VERO
(`fase135.genera_ical`). Le date sono **relative a oggi** (mai cablate: una data fissa e' una
bomba a tempo, e questo progetto ne ha gia' pagate).

⚠️ UN PASSO ROSSO QUI NON E' UN GUASTO DELL'ESAME: e' la macchina che non fa (ancora) quella
cosa. `--scrivi` registra anche il rosso, di proposito: una casella ROSSA con il motivo vale
piu' di una casella «mai misurata», perche' dice DOVE guardare.

⛔ D18: `precondizioni()` ferma il giro prima di misurare; `--autoprova` prova il giudizio nelle
   due direzioni; `NON_GUARDA` dichiara cosa resta fuori.
"""
import datetime
import inspect
import os
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

BLOCCO = 2
INDICE_CASELLA = 4
COMANDO = "python collaudi/esame_feed_due_versi.py --scrivi"
PASSI = []
SEZIONI_ATTESE = ("riapertura", "mano dell'host", "origine", "eco", "da N a zero")

ALLOGGIO = "esame-due-versi"
UNITA_PRIMA = 2
PREZZO_PRIMA = 12000

NON_GUARDA = (
    "la rete vera e il tempo vero: qui non si scarica nessun feed e non si aspetta nessun "
    "orologio -- il ritardo e la rilettura periodica sono la casella 3, gia' misurata da "
    "`esame_ical.py`, e questo esame non la tocca",
    "se le OTA vere si comportino come i feed che gli passo: i .ics sono fabbricati qui, "
    "conformi a RFC5545 con VALUE=DATE e DTEND esclusivo. Un'OTA che sbaglia il proprio feed "
    "e' un caso che vedra' il primo host vero",
    "le altre quattro caselle del blocco: non le tocca",
    "quanto sia GRAVE ogni buco: dice se la macchina fa quella cosa, non quanto costa non farla",
)


# ----------------------------------------------------------------------------------
#  L'IMPALCATURA (stessa forma degli altri esami del blocco)
# ----------------------------------------------------------------------------------

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
    """Il metro prima del muro (D18 punto 1): posso misurare, adesso, questa casella?"""
    fuori = []
    try:
        blocco = [b for b in BLOCCHI if b["ordine"] == BLOCCO]
        cond = blocco[0]["finito_quando"] if len(blocco) == 1 else ()
        testo = str(cond[INDICE_CASELLA]) if len(cond) > INDICE_CASELLA else ""
        ok = ("feed" in testo) and ("due versi" in testo) and ("anomalia" in testo)
        fuori.append(("la casella esiste nel piano e parla del feed nei due versi", ok,
                      " ".join(testo.split())[:70] + ("..." if len(testo) > 70 else "")))
    except Exception as e:
        fuori.append(("la casella esiste nel piano", False, "%s: %s" % (type(e).__name__, e)))
    try:
        impronta = scheda.impronta_del_blocco(BLOCCO)
        fuori.append(("il blocco ha un'impronta", bool(impronta),
                      impronta or "il piano non si legge"))
    except Exception as e:
        fuori.append(("il blocco ha un'impronta", False, str(e)))
    try:
        from fase58_channel_manager import crea_channel_manager  # noqa: F401
        from fase82_ical_sync import sincronizza  # noqa: F401
        from fase135_ical_bidirezionale import PRODID, genera_ical  # noqa: F401
        fuori.append(("inventario, sincronizzatore ed esportatore si importano", True,
                      "fase58 (crea_channel_manager), fase82 (sincronizza), fase135 (genera_ical)"))
    except Exception as e:
        fuori.append(("inventario, sincronizzatore ed esportatore si importano", False, str(e)))
    return all(ok for _, ok, _ in fuori), fuori


# ----------------------------------------------------------------------------------
#  IL BANCO
# ----------------------------------------------------------------------------------

def giorni(quanti=6, fra=30):
    """Giorni ISO consecutivi a partire da oggi+`fra`. ⛔ MAI date cablate: una data fissa
    diventa passata da sola, e allora il banco misura un'altra cosa senza dirlo."""
    base = datetime.date.today() + datetime.timedelta(days=fra)
    return [(base + datetime.timedelta(days=i)).isoformat() for i in range(quanti)]


def ics(*periodi, **kw):
    """Un .ics con un VEVENT per periodo (check_in, check_out), DTEND esclusivo."""
    prodid = kw.get("prodid", "-//OTA-Finta//Calendario//EN")
    righe = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:" + prodid, "CALSCALE:GREGORIAN"]
    for n, (ci, co) in enumerate(periodi):
        righe += ["BEGIN:VEVENT",
                  "UID:evento-%d@ota-finta" % n,
                  "DTSTAMP:20260101T000000Z",
                  "DTSTART;VALUE=DATE:" + ci.replace("-", ""),
                  "DTEND;VALUE=DATE:" + co.replace("-", ""),
                  "SUMMARY:Occupato",
                  "END:VEVENT"]
    righe.append("END:VCALENDAR")
    return "\r\n".join(righe) + "\r\n"


def banco(g):
    """Un inventario vero con lo STATO DI PRIMA scritto su tutti i giorni del banco."""
    from fase58_channel_manager import crea_channel_manager
    cm = crea_channel_manager(":memory:")
    cm.inizializza_schema()
    for giorno in g:
        cm.imposta_disponibilita(ALLOGGIO, giorno,
                                 unita_totali=UNITA_PRIMA,
                                 prezzo_netto_cents=PREZZO_PRIMA)
    return cm


def chiuso(cm, giorno):
    r = cm.stato_giorno(ALLOGGIO, giorno) or {}
    return int(r.get("unita_totali", -1)) == 0


def stato(cm, giorno):
    r = cm.stato_giorno(ALLOGGIO, giorno) or {}
    return (r.get("unita_totali"), r.get("prezzo_netto_cents"))


# ----------------------------------------------------------------------------------
#  L'ESAME — cinque sezioni, una per ogni cosa che la casella chiede
# ----------------------------------------------------------------------------------

def esame():
    from fase82_ical_sync import sincronizza
    from fase135_ical_bidirezionale import PRODID, genera_ical

    g = giorni(6)
    lontano = giorni(2, fra=200)          # un evento che resta, per non cadere nel caso «zero»

    # ── 1. RIAPERTURA ──────────────────────────────────────────────────────────────
    cm = banco(g)
    prima = stato(cm, g[0])
    sincronizza(cm, ALLOGGIO, ics((g[0], g[2]), (lontano[0], lontano[1])))
    if not passo("riapertura", "il feed chiude davvero la notte (premessa)", chiuso(cm, g[0]),
                 "stato dopo la prima lettura: %s" % (stato(cm, g[0]),)):
        return                                     # senza la premessa il resto non e' misurabile
    sincronizza(cm, ALLOGGIO, ics((lontano[0], lontano[1])))
    dopo = stato(cm, g[0])
    riaperta = not chiuso(cm, g[0])
    passo("riapertura", "la notte si RIAPRE quando l'evento sparisce da quel feed", riaperta,
          "prima %s, dopo la sparizione %s" % (prima, dopo))
    passo("riapertura", "e torna con lo STATO DI PRIMA (unita' e prezzo)", dopo == prima,
          "atteso %s, trovato %s" % (prima, dopo))

    # ── 2. MANO DELL'HOST ──────────────────────────────────────────────────────────
    if not riaperta:
        passo("mano dell'host", "la notte toccata dall'host non viene riaperta dal feed", False,
              "NON ESEGUITO: manca la premessa (nessuna notte si riapre, vedi sopra). Un "
              "controllo senza premessa non e' verde, e' non eseguito (S7)")
    else:
        cm2 = banco(g)
        sincronizza(cm2, ALLOGGIO, ics((g[0], g[1]), (lontano[0], lontano[1])))
        cm2.imposta_disponibilita(ALLOGGIO, g[0], unita_totali=1, prezzo_netto_cents=9900)
        mano = stato(cm2, g[0])
        sincronizza(cm2, ALLOGGIO, ics((lontano[0], lontano[1])))
        passo("mano dell'host", "la notte toccata dall'host resta come l'ha lasciata lui",
              stato(cm2, g[0]) == mano,
              "l'host aveva messo %s, adesso %s" % (mano, stato(cm2, g[0])))

    # ── 2-bis. «...E DA NESSUN ALTRO» ──────────────────────────────────────────────
    # La meta' della prima riga che si dimentica sempre: con DUE calendari sulla stessa
    # notte, il primo che molla NON deve riaprirla. E' il caso che vende due volte la
    # stessa notte, e non si vede mai con un feed solo.
    cmd = banco(g)
    sincronizza(cmd, ALLOGGIO, ics((g[0], g[1])), feed_id="airbnb")
    sincronizza(cmd, ALLOGGIO, ics((g[0], g[1])), feed_id="booking")
    sincronizza(cmd, ALLOGGIO, ics((lontano[0], lontano[1])), feed_id="airbnb")
    passo("riapertura", "due feed sulla stessa notte: se ne sparisce UNO la notte resta chiusa",
          chiuso(cmd, g[0]), "airbnb ha mollato, booking no -> %s" % (stato(cmd, g[0]),))
    sincronizza(cmd, ALLOGGIO, ics((lontano[0], lontano[1])), feed_id="booking")
    passo("riapertura", "quando molla anche l'ULTIMO, la notte torna com'era",
          stato(cmd, g[0]) == (UNITA_PRIMA, PREZZO_PRIMA),
          "atteso %s, trovato %s" % ((UNITA_PRIMA, PREZZO_PRIMA), stato(cmd, g[0])))

    # ── 3. ORIGINE ─────────────────────────────────────────────────────────────────
    # ⛔ QUESTE DUE SONDE SONO STATE RISCRITTE IL 2026-09-07, e il motivo va detto perche'
    # e' un modo di sbagliare, non un dettaglio. La prima stesura chiedeva se la RIGA
    # dell'inventario avesse una colonna con l'origine, e se il prezzo dell'host fosse
    # ancora scritto LI'. Erano domande cucite addosso a UNA implementazione immaginata,
    # non alla condizione. La condizione chiede che il blocco esterno sia un oggetto con
    # un'origine e che lo stato dell'host non vada perduto: DOVE siano scritti non la
    # riguarda. Una sonda che pretende un posto preciso boccia anche una riparazione
    # giusta -- ed e' il modo in cui un collaudo comincia a difendere se' stesso invece
    # del prodotto.
    parametri = list(inspect.signature(sincronizza).parameters)
    puo_dirlo = any(p not in ("inventario", "alloggio_id", "ical_testo") for p in parametri)
    passo("origine", "il sincronizzatore sa DA QUALE feed sta bloccando", puo_dirlo,
          "firma: sincronizza(%s) -- senza un'identita' del feed, «sparisce da QUEL feed» "
          "non e' nemmeno esprimibile" % ", ".join(parametri))
    cm3 = banco(g)
    sincronizza(cm3, ALLOGGIO, ics((g[0], g[1])), feed_id="airbnb")
    chiudono = cm3.chi_chiude(ALLOGGIO, g[0]) if hasattr(cm3, "chi_chiude") else []
    passo("origine", "la macchina sa CHI tiene chiusa quella notte", chiudono == ["airbnb"],
          "risposta: %r" % (chiudono,))
    salvato = (cm3.stato_prima_del_blocco(ALLOGGIO, g[0])
               if hasattr(cm3, "stato_prima_del_blocco") else None)
    tenuto = bool(salvato) and salvato.get("prezzo_netto_cents") == PREZZO_PRIMA \
        and salvato.get("unita_totali") == UNITA_PRIMA
    passo("origine", "lo stato dell'host NON e' perduto mentre la notte e' chiusa", tenuto,
          "messo da parte: %r -- se sparisse, la riapertura sarebbe impossibile per "
          "costruzione, non «non implementata»" % (salvato,))

    # ── 4. ECO ─────────────────────────────────────────────────────────────────────
    # Il feed che l'OTA ci ripropone e' il NOSTRO, generato dal NOSTRO esportatore.
    cm4 = banco(g)
    nostro = genera_ical([{"slug": ALLOGGIO, "check_in": g[3], "check_out": g[5],
                           "uid": "prenotazione-nostra"}])
    passo("eco", "il nostro feed si riconosce da fuori (porta il nostro PRODID)",
          PRODID in nostro, "PRODID atteso: %s" % PRODID)
    # ⛔ IL LEGAME FRA I DUE MODULI E' CONTROLLATO, NON SPERATO. `fase82` non puo'
    # importare `fase135` (sarebbe un anello: e' fase135 a importare fase82), quindi
    # tiene una marca sua. Se qualcuno rinomina il PRODID dell'esportatore, il filtro
    # dell'eco smette di riconoscerci **in silenzio** -- e il silenzio qui vuol dire che
    # ricominciamo a chiuderci le notti da soli. Questa e' la riga che lo impedisce.
    try:
        from fase82_ical_sync import MARCA_NOSTRA
    except ImportError:
        MARCA_NOSTRA = None
    passo("eco", "la marca che riconosce l'eco e il PRODID dell'esportatore combaciano",
          bool(MARCA_NOSTRA) and MARCA_NOSTRA in PRODID,
          "fase82.MARCA_NOSTRA=%r dentro fase135.PRODID=%r" % (MARCA_NOSTRA, PRODID))
    sincronizza(cm4, ALLOGGIO, nostro)
    passo("eco", "il nostro calendario riesportato NON chiude le nostre notti",
          not chiuso(cm4, g[3]),
          "notte %s dopo aver letto il NOSTRO stesso feed: %s" % (g[3], stato(cm4, g[3])))

    # ── 5. DA N A ZERO ─────────────────────────────────────────────────────────────
    cm5 = banco(g)
    sincronizza(cm5, ALLOGGIO, ics((g[0], g[1]), (g[2], g[3])))
    chiuse_prima = [x for x in g if chiuso(cm5, x)]
    esito = sincronizza(cm5, ALLOGGIO, ics())          # feed VUOTO: zero eventi
    chiuse_dopo = [x for x in g if chiuso(cm5, x)]
    passo("da N a zero", "un feed vuoto non riapre niente", chiuse_dopo == chiuse_prima,
          "chiuse prima %d, dopo %d. ⚠️ Questo passo, DA SOLO, non distingue «ha riconosciuto "
          "l'anomalia» da «non riapre mai niente»: fino al 2026-09-07 era verde per il secondo "
          "motivo. E' il passo qui sotto a separare i due casi -- per questo sono due"
          % (len(chiuse_prima), len(chiuse_dopo)))
    # ⛔ Si guarda il VALORE, non il nome del campo: una chiave `anomalia` che contiene la
    # stringa vuota e' esattamente il verde finto di `exc_info=False` -- «c'e' qualcosa»
    # invece di «c'e' LA cosa». La domanda e' se qualcuno a valle puo' ACCORGERSENE.
    detto = str(esito.get("anomalia", "")) if isinstance(esito, dict) else ""
    passo("da N a zero", "il passaggio da N eventi a ZERO diventa un'anomalia", bool(detto),
          "quello che il sincronizzatore dice: %s" % (detto or "NIENTE -- nessuno puo' "
          "accorgersene a valle. Risultato intero: %s" % (esito,)))


# ----------------------------------------------------------------------------------
#  LE PROVE DELL'ESAME SU SE STESSO (D18 punto 2)
# ----------------------------------------------------------------------------------

def passi_finti(rossi=()):
    return [(s, "finto", s not in rossi, "") for s in SEZIONI_ATTESE]


def autoprova():
    print("AUTOPROVA — il giudizio, nelle due direzioni")
    ok, motivi, quanti = giudica(passi_finti())
    a = passo("autoprova", "a passi tutti verdi il giudizio dice VERDE", ok and not motivi,
              "passi %d, motivi %d" % (quanti, len(motivi)))
    ok2, motivi2, _ = giudica(passi_finti(rossi=("eco",)))
    b = passo("autoprova", "un solo passo rosso lo fa diventare ROSSO", (not ok2) and motivi2,
              "; ".join(motivi2)[:90])
    ok3, motivi3, _ = giudica([(s, "finto", True, "") for s in SEZIONI_ATTESE[:-1]])
    c = passo("autoprova", "una sezione MAI misurata non passa per verde",
              (not ok3) and any("mai misurata" in m for m in motivi3),
              "; ".join(motivi3)[:90])
    return a and b and c


def _stampa_non_guarda():
    print("-" * 86)
    print("⛔ COSA QUESTO ESAME NON HA ESAMINATO (D18 punto 3)")
    for r in NON_GUARDA:
        print("   · " + r)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    print("=" * 86)
    print("🔁 ESAME — IL FEED ESTERNO VALE NEI DUE VERSI  (blocco %d, casella %d)"
          % (BLOCCO, INDICE_CASELLA + 1))
    print("=" * 86)

    if "--autoprova" in argv:
        return 0 if autoprova() else 1

    ok, fuori = precondizioni()
    print("PRECONDIZIONI (il metro prima del muro)")
    for nome, esito, dettaglio in fuori:
        print("  %s  %s  -> %s" % ("OK  " if esito else "ROSSO", nome, dettaglio))
    if not ok:
        print("\n⛔ FERMO: non sono in condizione di misurare. Non scrivo niente.")
        return 2

    print("\nMISURA")
    esame()

    verde, motivi, denominatore = giudica(PASSI)
    print("-" * 86)
    print("VERDETTO: %s   (%d passi esaminati)"
          % ("✅ VERDE" if verde else "🔴 ROSSA", denominatore))
    for m in motivi:
        print("   · " + m)
    _stampa_non_guarda()

    if "--scrivi" in argv:
        condizioni = [b for b in BLOCCHI if b["ordine"] == BLOCCO][0]["finito_quando"]
        riga = scheda.registra(condizioni[INDICE_CASELLA], esito=verde,
                               denominatore=denominatore, comando=COMANDO, ordine=BLOCCO)
        print("\nSCRITTA NELLA SCHEDA: blocco %d · esito %s · denominatore %d · impronta %s"
              % (riga["blocco"], riga["esito"], riga["denominatore"], riga["impronta"]))
    else:
        print("\n(non ho scritto niente: aggiungi --scrivi per registrare nella scheda)")
    return 0 if verde else 1


if __name__ == "__main__":
    sys.exit(main())
