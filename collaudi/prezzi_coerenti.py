"""LA VETRINA E LA CASSA DEVONO DIRE LO STESSO NUMERO.

⛔ IL DIFETTO CHE QUESTO ATTREZZO SORVEGLIA (B1), misurato il 2026-08-22 sui dati VERI:

      VETRINA  (catalogo.db . alloggi . prezzo_notte_cents)   <- casella p_prezzo
         filippine-makati            100 cents  [pubblicato]
         filippine-makati-2          100 cents  [pubblicato]
      CASSA    (inventario.db . inventario . prezzo_netto_cents) <- casella d_prezzo
         filippine-makati           9000 cents x 30 giorni futuri
         filippine-makati-2         9000 cents x 30 giorni futuri

    Il sito diceva 1,00 EURO a notte e la cassa ne addebitava 90,00: NOVANTA VOLTE.
    Non e' un caso limite -- erano gli unici due annunci pubblicati.

💡 PERCHE' NESSUNO SE N'ERA ACCORTO. Sono due numeri in due archivi diversi, scritti da
   due schermate diverse del pannello host, e nel codice non esisteva UN SOLO punto in cui
   comparissero insieme. Un difetto invisibile non perche' nascosto, ma perche' nessuno
   aveva mai messo i due numeri sulla stessa riga.

⛔ DOVE VA CIASCUNO -- e' la ragione per cui questo difetto e' grave:
   · `prezzo_notte_cents` e' cio' che vede IL MONDO: pagina dell'annuncio, scheda per
     GOOGLE (`"price"` in JSON-LD), anteprima sui social, feed RSS, schede dei risultati,
     filtri e ordinamento per prezzo, mappa.
   · `prezzo_netto_cents` e' cio' che PAGA L'OSPITE: `fase59_concierge.py:283` somma
     notte per notte questo, e SOLO questo.

🔑 LA REGOLA CHE QUESTO ATTREZZO FA RISPETTARE, e da dove viene.
   Decisione del fondatore del 2026-08-22 (scelta B): «il numero visto dev'essere il
   numero pagato». Senza date scelte, la vetrina puo' dire solo «da X a notte», e quella
   X dev'essere la NOTTE PRENOTABILE PIU' ECONOMICA. Se la vetrina dice meno, attira con
   un prezzo che non esiste; se dice di piu', spaventa con un prezzo che non esiste.

⛔ NON SCRIVE MAI NIENTE. Gli archivi si aprono con `mode=ro`: sqlite rifiuta ogni
   scrittura a livello di driver, non per buona volonta' di chi ha scritto il codice.

USO:
    python collaudi/prezzi_coerenti.py                  # cartella /data (dentro il contenitore)
    python collaudi/prezzi_coerenti.py --cartella data  # una cartella qualunque
    python collaudi/prezzi_coerenti.py --oggi 2026-08-22

Esce 1 se anche UN SOLO annuncio pubblicato dice il falso, 0 se sono tutti onesti.
"""

import argparse
import datetime
import os
import sqlite3
import sys


# ── IL GIUDIZIO: PURO, cosi' si puo' provare nelle DUE direzioni senza archivi ──────────
# ⛔ `oggi` ENTRA COME ARGOMENTO e non si legge dall'orologio qui dentro. E' la lezione
#    delle cinque trappole dell'orologio finto: una funzione che chiama `date.today()`
#    da sola non e' provabile su uno scenario datato, e SQLite ha per giunta un orologio
#    suo che `freezegun` non copre. Qui il tempo e' un ingresso, non un effetto.

def notti_prenotabili(giorni, oggi):
    """Le notti che un ospite puo' DAVVERO comprare, da oggi in avanti.

    `giorni`: righe della tabella `inventario` come dizionari.
    Ritorna [(giorno, prezzo_netto_cents), ...] ordinate per giorno.

    ⛔ IL FILTRO SUL PASSATO NON E' PEDANTERIA, ed e' la trappola vera: il 2026-08-22
       `filippine-makati` aveva UNA notte a 100 cents datata 2026-08-16 (passata) e 30
       notti future a 9000. Un controllo che guardasse TUTTI i giorni troverebbe minimo
       100, coinciderebbe con la vetrina e direbbe "coerente" -- assolvendo il difetto
       con un giorno che nessuno puo' piu' prenotare.
    """
    fuori = []
    for g in giorni or ():
        giorno = str(g.get("giorno", ""))
        if giorno < str(oggi):
            continue                                   # gia' passata: non si compra
        if int(g.get("chiuso", 0) or 0):
            continue                                   # l'host l'ha chiusa
        libere = int(g.get("unita_totali", 0) or 0) - int(g.get("unita_occupate", 0) or 0)
        if libere <= 0:
            continue                                   # tutto occupato
        prezzo = g.get("prezzo_netto_cents")
        if not isinstance(prezzo, int) or isinstance(prezzo, bool) or prezzo <= 0:
            continue                                   # fase59 risponde non_quotabile
        fuori.append((giorno, prezzo))
    return sorted(fuori)


def giudica(prezzo_vetrina_cents, notti):
    """I motivi per cui la vetrina dice il falso. Lista VUOTA = la vetrina e' onesta.

    `notti` sono gia' quelle prenotabili (vedi `notti_prenotabili`).

    ⛔ Ritorna MOTIVI, non un booleano: un `False` non dice all'host cosa riparare, e
       questo attrezzo deve poter essere letto da chi non ha scritto il codice.
    """
    motivi = []
    if not isinstance(prezzo_vetrina_cents, int) or isinstance(prezzo_vetrina_cents, bool) \
            or prezzo_vetrina_cents <= 0:
        motivi.append("la vetrina non ha un prezzo valido (%r): l'annuncio e' pubblicato "
                      "con una cifra che non si puo' nemmeno mostrare"
                      % (prezzo_vetrina_cents,))
        return motivi
    if not notti:
        motivi.append("in vetrina a %d cents, ma NESSUNA notte prenotabile: chi prova a "
                      "prenotare riceve 422 non_quotabile. La vetrina promette una cosa "
                      "che la cassa non sa vendere" % prezzo_vetrina_cents)
        return motivi
    prezzi = sorted(p for _g, p in notti)
    minimo = prezzi[0]
    if prezzo_vetrina_cents < minimo:
        motivi.append("ATTIRA PIU' BASSO: la vetrina dice %d cents, ma la notte "
                      "prenotabile piu' economica ne costa %d (%.1f volte tanto). "
                      "E' il numero che finisce su Google e nei risultati di ricerca"
                      % (prezzo_vetrina_cents, minimo,
                         float(minimo) / float(prezzo_vetrina_cents)))
    elif prezzo_vetrina_cents > minimo:
        motivi.append("SPAVENTA PIU' ALTO: la vetrina dice %d cents, ma la notte "
                      "prenotabile piu' economica ne costa %d: l'ospite scarta un "
                      "annuncio che poteva permettersi"
                      % (prezzo_vetrina_cents, minimo))
    return motivi


def notti_a_prezzi_diversi(notti):
    """(minimo, massimo) se le notti prenotabili NON costano tutte uguale, altrimenti None.

    ⚠️ NON e' una bugia, ed e' per questo che sta in una funzione a parte: e' la ragione
       per cui la vetrina non puo' cavarsela con UN numero. Con la scelta B del fondatore
       la scheda deve mostrare il prezzo DELLE DATE CHIESTE; senza date, «da <minimo>».
    """
    if not notti:
        return None
    prezzi = sorted(p for _g, p in notti)
    return (prezzi[0], prezzi[-1]) if prezzi[0] != prezzi[-1] else None


# ── LA LETTURA DEGLI ARCHIVI VERI (sola lettura, mai una scrittura) ─────────────────────

def _leggi(percorso, query, parametri=()):
    con = sqlite3.connect("file:%s?mode=ro" % percorso, uri=True)
    try:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(query, parametri).fetchall()]
    finally:
        con.close()


def esamina(cartella, oggi):
    """Un esito per ogni annuncio PUBBLICATO. Non tocca gli annunci in bozza: quelli
    nessuno li vede, quindi non possono mentire a nessuno."""
    cat = os.path.join(cartella, "catalogo.db")
    inv = os.path.join(cartella, "inventario.db")
    for p in (cat, inv):
        if not os.path.exists(p):
            raise IOError("archivio assente: %s" % p)
    annunci = _leggi(cat, "SELECT slug, prezzo_notte_cents, valuta, stato FROM alloggi "
                          "WHERE stato='pubblicato' ORDER BY slug")
    esiti = []
    for a in annunci:
        giorni = _leggi(inv, "SELECT giorno, unita_totali, unita_occupate, "
                             "prezzo_netto_cents, chiuso FROM inventario "
                             "WHERE alloggio_id=?", (a["slug"],))
        notti = notti_prenotabili(giorni, oggi)
        esiti.append({
            "slug": a["slug"],
            "valuta": a["valuta"],
            "vetrina": a["prezzo_notte_cents"],
            "notti": len(notti),
            "motivi": giudica(a["prezzo_notte_cents"], notti),
            "variabili": notti_a_prezzi_diversi(notti),
        })
    return esiti


NON_CONTROLLO = [
    "non guarda la PAGINA: legge gli archivi. Se la pagina mostrasse un terzo numero "
    "ancora diverso, questo attrezzo direbbe lo stesso che tutto va bene",
    "non giudica se il prezzo e' CREDIBILE (1 cent a notte, 90.000 EURO a notte): "
    "quello lo fa collaudi/plausibilita.py, che pero' guarda solo il catalogo",
    "legge i giorni come sono ADESSO: l'host puo' cambiarli un minuto dopo, e questo "
    "e' un difetto del PRODOTTO che si chiude col pezzo 2, non un difetto di questa misura",
    "il soggiorno MINIMO (`min_notti`) non entra nel giudizio: una notte puo' risultare "
    "prenotabile da sola e non esserlo davvero perche' l'host chiede almeno 3 notti. "
    "Il minimo qui e' quindi una stima OTTIMISTA: la cassa puo' solo costare di piu'",
    "la valuta di visualizzazione non entra: si confrontano due numeri nella STESSA "
    "valuta dell'host, com'e' l'addebito (like-for-like)",
]


def main(argv=None):
    ap = argparse.ArgumentParser(description="La vetrina e la cassa dicono lo stesso numero?")
    ap.add_argument("--cartella", default="/data",
                    help="dove stanno catalogo.db e inventario.db (default: /data)")
    ap.add_argument("--oggi", default=None,
                    help="data di riferimento AAAA-MM-GG (default: oggi)")
    a = ap.parse_args(argv)
    oggi = a.oggi or datetime.date.today().isoformat()

    print("=" * 78)
    print("🏷️  LA VETRINA E LA CASSA DICONO LO STESSO NUMERO?")
    print("=" * 78)
    print("  cartella: %s   ·   giorno di riferimento: %s" % (a.cartella, oggi))
    print("  ⛔ Il numero visto dev'essere il numero pagato. Senza date scelte la vetrina")
    print("     puo' dire solo «da X», e X e' la notte prenotabile piu' economica.")
    print("-" * 78)

    try:
        esiti = esamina(a.cartella, oggi)
    except IOError as e:
        print("  MISURA NON VALIDA: %s" % e)
        print("  ⛔ Un archivio assente non e' un verde: e' l'assenza di misura.")
        return 2

    if not esiti:
        print("  MISURA NON VALIDA: nessun annuncio PUBBLICATO da esaminare.")
        print("  ⛔ Zero righe non e' un verde: non c'era niente da giudicare.")
        return 2

    bugiardi = 0
    for e in esiti:
        if e["motivi"]:
            bugiardi += 1
            print("  ROSSO  %s   (%s, %d notti prenotabili)"
                  % (e["slug"], e["valuta"], e["notti"]))
            for m in e["motivi"]:
                print("         %s" % m)
        else:
            print("  OK     %s   vetrina %d cents = notte piu' economica  (%d notti)"
                  % (e["slug"], e["vetrina"], e["notti"]))
        if e["variabili"]:
            mn, mx = e["variabili"]
            print("         nota: le notti costano da %d a %d cents. Un numero solo non "
                  "puo' dirle tutte:" % (mn, mx))
            print("               con le date scelte la scheda deve mostrare QUELLE date.")

    print("-" * 78)
    print("⛔ COSA QUESTO CONTROLLO NON ESAMINA (D18 punto 3)")
    for r in NON_CONTROLLO:
        print("   ⚠ %s" % r)
    print("-" * 78)
    print("DENOMINATORE: %d annunci pubblicati · %d dicono il falso"
          % (len(esiti), bugiardi))
    print("=" * 78)
    return 1 if bugiardi else 0


if __name__ == "__main__":       # pragma: no cover
    sys.exit(main())
