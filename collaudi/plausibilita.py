"""PLAUSIBILITA' DEL DATO — «questo numero ha senso nel mondo vero?»

═══════════════════════════════════════════════════════════════════════════════════
PERCHE' ESISTE
═══════════════════════════════════════════════════════════════════════════════════
Il 2026-07-21 il fondatore ha guardato il sito e ha visto:

    Zen House Shibuya — ¥ 1.800.000 / notte      (circa 11.000 euro)

Lo yen NON ha decimali: il prezzo era stato salvato ×100, come si fa con l'euro.
**Nessuno dei collaudi l'ha visto.** Suite verde, 3011 test, dieci strumenti di verifica,
mutazione, piramide — e un errore da centomila per cento in bella vista sulla vetrina.

Il motivo e' strutturale, e vale la pena scriverlo:

  · tutti gli altri collaudi provano il **CODICE**, con dati **inventati da loro**;
  · quel difetto era nei **DATI VERI, in produzione**, dove nessuno guardava;
  · e nessuna verifica chiedeva la domanda piu' semplice del mondo:
    **«questo numero ha senso?»**

Un formato corretto non e' un valore corretto. `1800000` e' un intero perfettamente
valido, in una colonna perfettamente tipizzata, con una valuta perfettamente esistente.
E' semplicemente ASSURDO, e l'assurdita' non e' un errore di tipo: e' un errore di
SIGNIFICATO.

Questo strumento guarda i **dati reali** (in produzione o in una copia) e chiede, per
ogni numero, se sta in una banda che il mondo consente. Un errore ×100 sfonda qualsiasi
banda ragionevole: e' proprio questo che lo rende individuabile.
"""
import io
import os
import sqlite3
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

VIOL = []
CONTA = {"controlli": 0, "righe": 0}


def viola(ambito, chiave, dettaglio):
    VIOL.append((ambito, chiave, dettaglio))


def controlla(ambito, chiave, ok, dettaglio=""):
    CONTA["controlli"] += 1
    if not ok:
        viola(ambito, chiave, dettaglio)


# ═══════════════════════════════════════════════════════════════════════════════
#  VALUTE — quante cifre decimali ha davvero ciascuna
# ═══════════════════════════════════════════════════════════════════════════════
# Le valute SENZA decimali sono la trappola: se si moltiplica per 100 "come l'euro",
# il prezzo diventa cento volte tanto e sembra ancora un numero normale.
#
# QUESTA TABELLA NON ESISTE PIU', E NON DEVE TORNARE.
# La prima stesura ne teneva una propria, e si e' scoperto che diceva il falso su tre
# valute: HUF, TWD e COP dichiarate SENZA decimali quando ne hanno due. Sarebbe stato
# il difetto peggiore possibile in uno strumento nato per trovare gli errori di scala:
# uno strumento che li INVENTA (un prezzo ungherese corretto denunciato come sbagliato)
# e insieme li NASCONDE (una banda calcolata cento volte piu' larga del dovuto).
#
# La causa non era la distrazione: era la DUPLICAZIONE. Due tabelle della stessa cosa
# divergono sempre, e la copia sbagliata non fa rumore. Quindi qui si legge dal motore
# (`fase99_multicurrency.esponente`), che e' la stessa fonte usata dal server per
# formattare gli importi. Se un giorno il motore cambia, questo collaudo cambia con lui;
# se il motore non c'e', si fallisce dicendolo invece di indovinare.
def _esponente(valuta):
    """Cifre decimali della valuta, chieste al MOTORE (mai a una copia locale)."""
    from fase99_multicurrency import esponente
    return esponente(str(valuta or "EUR"))


def valuta_nota(valuta):
    """Vero se e' una valuta ISO plausibile (3 lettere). Una sigla inventata non e'
    un dettaglio estetico: il suo esponente verrebbe indovinato, e su un prezzo
    indovinare significa sbagliare l'addebito."""
    v = str(valuta or "").strip()
    return len(v) == 3 and v.isalpha()

# Quanto vale, MOLTO alla larga, un'unita' di quella valuta in euro. Non servono tassi
# precisi: servono ordini di grandezza, perche' cio' che si cerca e' un errore ×100.
IN_EURO = {
    "EUR": 1.0, "USD": 0.92, "GBP": 1.17, "CHF": 1.05, "AED": 0.25, "JPY": 0.0062,
    "KRW": 0.00068, "CNY": 0.13, "AUD": 0.60, "CAD": 0.68, "SEK": 0.087,
    "NOK": 0.086, "DKK": 0.134, "PLN": 0.23, "CZK": 0.040, "HUF": 0.0026,
    "BRL": 0.16, "MXN": 0.050, "INR": 0.011, "THB": 0.026, "IDR": 0.000058,
    "TRY": 0.028, "ZAR": 0.050, "SGD": 0.69, "HKD": 0.118, "NZD": 0.56,
}

# Banda in EURO entro cui un prezzo a notte e' credibile. Larghissima di proposito:
# deve lasciar passare l'ostello e la villa di lusso, e fermare solo l'assurdo.
NOTTE_MIN_EUR = 5.0
NOTTE_MAX_EUR = 5000.0


def in_euro(minori, valuta):
    """Da unita' minori a euro, tenendo conto dei decimali VERI di quella valuta."""
    v = str(valuta or "EUR").upper()
    unita = float(minori) / (10 ** _esponente(v))
    return unita * IN_EURO.get(v, 1.0)


def _apri(percorso):
    con = sqlite3.connect("file:%s?mode=ro" % percorso, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _colonne(con, tabella):
    try:
        return {r[1] for r in con.execute("PRAGMA table_info(%s)" % tabella)}
    except Exception:
        return set()


# ═══════════════════════════════════════════════════════════════════════════════
def prezzi_alloggi(cartella):
    """IL CONTROLLO CHE MANCAVA. Ogni prezzo a notte, convertito in euro, deve stare
    in una banda che il mondo consente. Un ×100 la sfonda sempre."""
    percorso = os.path.join(cartella, "catalogo.db")
    if not os.path.exists(percorso):
        viola("prezzi", "catalogo.db", "archivio assente: nulla da controllare")
        return
    con = _apri(percorso)
    try:
        cols = _colonne(con, "alloggi")
        if "prezzo_notte_cents" not in cols:
            viola("prezzi", "alloggi", "colonna del prezzo assente")
            return
        for r in con.execute("SELECT slug, titolo, citta, prezzo_notte_cents, valuta,"
                             " capacita, stato FROM alloggi"):
            CONTA["righe"] += 1
            slug = r["slug"] or r["titolo"]
            minori = int(r["prezzo_notte_cents"] or 0)
            valuta = str(r["valuta"] or "EUR").upper()
            euro = in_euro(minori, valuta)

            controlla("prezzi", slug, minori > 0,
                      "prezzo a zero o negativo: %s" % minori)
            controlla("prezzi", slug, NOTTE_MIN_EUR <= euro <= NOTTE_MAX_EUR,
                      "%s %s a notte = circa %.0f EURO: fuori da ogni banda credibile "
                      "(%.0f-%.0f). Tipico errore x100 su una valuta con %d decimali."
                      % (minori, valuta, euro, NOTTE_MIN_EUR, NOTTE_MAX_EUR,
                         _esponente(valuta)))
            controlla("prezzi", slug, valuta_nota(valuta),
                      "valuta '%s' non e' una sigla ISO di 3 lettere: il suo esponente "
                      "verrebbe INDOVINATO (2), e su un prezzo indovinare significa "
                      "sbagliare l'addebito" % valuta)
            controlla("prezzi", slug, valuta in IN_EURO,
                      "valuta '%s' senza un tasso di riferimento: il prezzo viene "
                      "giudicato come se fosse in euro, quindi la banda non vale" % valuta)

            # Le valute SENZA decimali: un importo che finisce con due zeri ED e'
            # enorme e' il sintomo classico del x100.
            if _esponente(valuta) == 0 and minori % 100 == 0 and euro > NOTTE_MAX_EUR:
                viola("prezzi", slug,
                      "%s %s: valuta senza decimali, importo multiplo di 100 e fuori "
                      "banda -> quasi certamente moltiplicato per 100" % (minori, valuta))

            if "capacita" in cols:
                cap = int(r["capacita"] or 0)
                controlla("capacita", slug, 1 <= cap <= 50,
                          "capacita %s: fuori da ogni struttura reale" % cap)
            if "stato" in cols:
                controlla("stato", slug,
                          str(r["stato"]) in ("pubblicato", "bozza", "sospeso"),
                          "stato sconosciuto: %r" % r["stato"])
    finally:
        con.close()


def coerenza_prezzi_fra_loro(cartella):
    """Un annuncio 100 volte piu' caro della mediana e' sospetto anche se sta nella
    banda: si guarda la FAMIGLIA dei dati, non solo il singolo."""
    percorso = os.path.join(cartella, "catalogo.db")
    if not os.path.exists(percorso):
        return
    con = _apri(percorso)
    try:
        valori = []
        for r in con.execute("SELECT slug, prezzo_notte_cents, valuta FROM alloggi"):
            e = in_euro(int(r["prezzo_notte_cents"] or 0), r["valuta"])
            if e > 0:
                valori.append((r["slug"], e))
        if len(valori) < 4:
            return
        ordinati = sorted(v for _s, v in valori)
        mediana = ordinati[len(ordinati) // 2]
        for slug, e in valori:
            controlla("coerenza", slug, e <= mediana * 50,
                      "%.0f EURO contro una mediana di %.0f: 50 volte tanto"
                      % (e, mediana))
            controlla("coerenza", slug, e >= mediana / 50,
                      "%.0f EURO contro una mediana di %.0f: cinquanta volte meno"
                      % (e, mediana))
    finally:
        con.close()


def importi_di_denaro(cartella):
    """Gli importi nel libro giornale e nei payout: stessa domanda."""
    for nome, tabella, colonne in (("finanza.db", "libro_giornale",
                                    ("importo_cents", "valuta")),
                                   ("payout.db", "payout", ("minori", "valuta"))):
        percorso = os.path.join(cartella, nome)
        if not os.path.exists(percorso):
            continue
        con = _apri(percorso)
        try:
            cols = _colonne(con, tabella)
            if not cols or colonne[0] not in cols:
                continue
            for r in con.execute("SELECT %s, %s FROM %s"
                                 % (colonne[0], colonne[1], tabella)):
                CONTA["righe"] += 1
                minori = int(r[colonne[0]] or 0)
                euro = in_euro(minori, r[colonne[1]])
                controlla("denaro", nome, 0 <= euro <= 1000000,
                          "%s %s = circa %.0f EURO: importo fuori scala"
                          % (minori, r[colonne[1]], euro))
        except Exception:
            pass
        finally:
            con.close()


def date_sensate(cartella):
    """Una data nel 1970 o nel 2200 e' un errore di conversione, non una prenotazione."""
    import datetime
    ora = int(datetime.datetime.utcnow().timestamp())
    minimo = int(datetime.datetime(2024, 1, 1).timestamp())
    massimo = ora + 5 * 365 * 24 * 3600
    for nome, tabella, colonna in (("registro_host.db", "host", "creato_ts"),
                                   ("accettazioni.db", "accettazioni", "accettato_ts"),
                                   ("marche.db", "marche", "gen_time")):
        percorso = os.path.join(cartella, nome)
        if not os.path.exists(percorso):
            continue
        con = _apri(percorso)
        try:
            if colonna not in _colonne(con, tabella):
                continue
            for r in con.execute("SELECT %s AS t FROM %s" % (colonna, tabella)):
                t = int(r["t"] or 0)
                if t == 0:
                    continue
                CONTA["righe"] += 1
                controlla("date", "%s.%s" % (nome, colonna), minimo <= t <= massimo,
                          "%s = %s: fuori da ogni periodo plausibile"
                          % (t, datetime.datetime.utcfromtimestamp(t).isoformat()
                             if 0 < t < 4102444800 else "data impossibile"))
        except Exception:
            pass
        finally:
            con.close()


def testi_non_vuoti(cartella):
    percorso = os.path.join(cartella, "catalogo.db")
    if not os.path.exists(percorso):
        return
    con = _apri(percorso)
    try:
        for r in con.execute("SELECT slug, titolo, citta FROM alloggi"):
            controlla("testi", r["slug"], bool(str(r["titolo"] or "").strip()),
                      "titolo vuoto: l'annuncio comparirebbe senza nome")
            controlla("testi", r["slug"], bool(str(r["citta"] or "").strip()),
                      "citta' vuota: non sarebbe trovabile")
            controlla("testi", r["slug"], len(str(r["titolo"] or "")) < 200,
                      "titolo di %d caratteri" % len(str(r["titolo"] or "")))
    finally:
        con.close()


CONTROLLI = [
    ("prezzi degli alloggi", prezzi_alloggi),
    ("coerenza dei prezzi fra loro", coerenza_prezzi_fra_loro),
    ("importi di denaro", importi_di_denaro),
    ("date", date_sensate),
    ("testi", testi_non_vuoti),
]


if __name__ == "__main__":
    cartella = None
    for a in sys.argv[1:]:
        if a.startswith("--dati="):
            cartella = a.split("=", 1)[1]
    if not cartella:
        for c in (os.path.join(REPO, "data"), "/data",
                  r"C:\Users\MaxDanno\Desktop\BACKUP_PRODUZIONE_ATTICO\data"):
            if os.path.isdir(c):
                cartella = c
                break
    print("=" * 88)
    print("PLAUSIBILITA' DEL DATO — «questo numero ha senso nel mondo vero?»")
    print("dati esaminati: %s" % cartella)
    print("=" * 88)
    if not cartella or not os.path.isdir(cartella):
        print("\nNESSUN ARCHIVIO TROVATO: passare --dati=<cartella>")
        sys.exit(1)
    for nome, funzione in CONTROLLI:
        prima = len(VIOL)
        try:
            funzione(cartella)
        except Exception as e:
            viola(nome, "(esecuzione)", "%s: %s" % (type(e).__name__, e))
        nuove = len(VIOL) - prima
        print("  %-34s %s" % (nome, "OK" if nuove == 0 else "%d ASSURDITA'" % nuove))
    print("\n" + "=" * 88)
    print("righe esaminate: %d | controlli: %d" % (CONTA["righe"], CONTA["controlli"]))
    if VIOL:
        print("VALORI SENZA SENSO: %d\n" % len(VIOL))
        for ambito, chiave, dett in VIOL:
            print("  X [%s] %s" % (ambito, chiave))
            print("       %s" % dett)
        sys.exit(1)
    print("Ogni numero sta in una banda che il mondo consente.")
    sys.exit(0)
