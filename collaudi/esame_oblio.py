# -*- coding: utf-8 -*-
"""🗑️ L'ESAME DELL'OBLIO — il giro intero di «cancellami», con il denominatore.

PERCHE' ESISTE, e non e' teoria. `fase156_erasure.cancella_attivita_host` dichiara nella
sua stessa docstring di cancellare l'host «da OGNI archivio del sistema e verifica». I
residui che ricontrolla sono CINQUE, nominati a mano dentro quel file (annunci,
inventario, messaggi, referral, anagrafica), e il rapporto dice `ok=True` guardando solo
quelli. Il server di produzione ne conta **ventisette**. Quindi oggi `ok=True` significa
«non e' rimasto niente nei cinque che so guardare», non «non e' rimasto niente» — e le
due frasi si scrivono uguale.

⛔ E il file DICHIARA di essere resiliente: opera solo sugli archivi che espongono i
metodi giusti, cosi' «aggiungere un archivio nuovo non richiede toccare questo file».
Letta dal lato in cui morde: **un archivio nuovo viene saltato in silenzio**, e il
rapporto resta `ok=True`. E' la famiglia 20.3 del METODO (la misura che invecchia): una
lista scritta a mano non invecchia con un errore, invecchia col silenzio.

📐 **QUESTO E' UN GIRO INTERO, famiglia 20.1 del METODO v4**, e ne segue le due regole:
  · il criterio non e' «nessun errore»: e' che **ogni anello lasci una traccia
    osservabile**, e la traccia si prende in DUE TEMPI — PRIMA il dato c'e', DOPO non
    c'e'. Un archivio che non conteneva niente non dimostra niente sulla cancellazione;
  · **il denominatore si dichiara**: «N archivi su M», mai «funziona».

🔑 **E IL DENOMINATORE NON LO SCRIVE UNA PERSONA.** Gli archivi si contano come li conta
la produzione (`fase202.leggi_archivi`: i file `*.db` della cartella dati), e la presenza
del dato si cerca **in ogni tabella e in ogni colonna di testo di ogni archivio**, non in
un elenco di archivi che qualcuno si e' ricordato di nominare. Cosi' un archivio nato
domani entra nel conto da solo, e il giorno che resta sporco questo esame diventa rosso.

⛔ LE QUATTRO CONDIZIONI D18, perche' questo e' uno strumento che MISURA:
  1. **misura prima se stesso**: se dopo aver costruito il banco il dato della persona non
     si trova in NESSUN archivio, la premessa manca e l'esame si ferma ROSSO dicendolo —
     non «cancellato bene» (sbaglio S1: il vuoto non e' un valore; sbaglio S7: senza
     premessa il controllo e' NON ESEGUITO, mai verde);
  2. **provato nelle DUE direzioni**: con `--guasto salta-oblio` il giro NON cancella, e
     l'esame deve gridare. Se resta verde, questo esame non guarda niente;
  3. **dichiara cosa NON ha esaminato**: in fondo, sempre, a ogni giro;
  4. **e' sotto guardia**: ⚠️ LIMITE DICHIARATO OGGI — questa quarta condizione NON e'
     ancora soddisfatta: nessun test della suite fallisce se questo file sparisce. Lo si
     scrive invece di tacerlo, perche' un limite dichiarato e' un attrezzo di scoperta e
     un limite taciuto e' un buco.

⚠️ E UNA COSA CHE QUESTO ESAME NON PUO' DECIDERE. Per molti archivi la domanda «si
cancella o si conserva?» mette il diritto all'oblio contro obblighi fiscali e DAC7: le due
regole si contraddicono sullo stesso dato. Questo esame dice **dove il dato e' rimasto**;
NON dice se doveva restare. Quella riga la scrive una persona, e la guarda un avvocato.

COME SI USA
    python collaudi/esame_oblio.py
    python collaudi/esame_oblio.py --guasto salta-oblio     <- deve diventare ROSSO
Uscita 0 = il giro e' intero.  Uscita 1 = fermo, e sotto c'e' scritto dove.
"""
import argparse
import glob
import json
import os
import shutil
import sqlite3
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

QUI = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(QUI)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

# Identificatori della persona di prova. ⛔ NIENTE CIFRE DI FILA: `fase113.maschera_pii`
# scambia una sequenza lunga di numeri per un telefono e la sostituisce, il dato non
# arriverebbe mai nell'archivio dei messaggi e la premessa cadrebbe senza dirlo. Misurato
# il 2026-09-12: e' cosi' che un test stava per passare a vuoto.
EMAIL = "oblio.prova@esempio-oblio.test"
TELEFONO = "+39 OBLIOPROVA"
RAGIONE = "OBLIOPROVA SRL"


def _righe_di_testo(percorso):
    """Ogni valore di testo di ogni tabella dell'archivio, con la tabella da cui viene.
    ⛔ Si legge da `sqlite_master`, non da un elenco di tabelle: una tabella nuova entra
    nel conto da sola. Un archivio illeggibile NON diventa «pulito»: diventa CIECO."""
    fuori, cieco = [], None
    try:
        con = sqlite3.connect("file:%s?mode=ro" % percorso.replace("?", "%3f"), uri=True)
        con.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        return [], str(e)
    try:
        tabelle = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for t in tabelle:
            try:
                for r in con.execute('SELECT * FROM "%s"' % t.replace('"', '""')):  # noqa: S608
                    for chiave in r.keys():
                        v = r[chiave]
                        if isinstance(v, str) and v:
                            fuori.append((t, chiave, v))
            except sqlite3.Error:
                cieco = "tabella %s illeggibile" % t
    except sqlite3.Error as e:
        cieco = str(e)
    finally:
        con.close()
    return fuori, cieco


def _dove_compare(dir_dati, aghi):
    """{archivio: [«tabella.colonna», ...]} per ogni archivio in cui compare un ago.
    Ritorna anche gli archivi CIECHI: un archivio che non si legge non e' un archivio
    pulito, ed e' la differenza fra «non c'e'» e «non l'ho visto»."""
    trovati, ciechi = {}, []
    for percorso in sorted(glob.glob(os.path.join(dir_dati, "*.db"))):
        nome = os.path.basename(percorso)
        righe, cieco = _righe_di_testo(percorso)
        if cieco:
            ciechi.append("%s (%s)" % (nome, cieco))
        posti = sorted({"%s.%s" % (t, c) for t, c, v in righe
                        if any(a in v for a in aghi)})
        if posti:
            trovati[nome] = posti
    return trovati, ciechi


def _nei_byte(dir_dati, aghi):
    """Gli archivi in cui l'ago si rilegge dai BYTE del file. Un `DELETE` di SQLite marca
    lo spazio come riutilizzabile e lascia il contenuto nelle pagine libere: la riga non
    si interroga piu' e il testo si legge ancora con un editor esadecimale."""
    fuori = []
    for percorso in sorted(glob.glob(os.path.join(dir_dati, "*.db*"))):
        try:
            with open(percorso, "rb") as f:
                crudo = f.read()
        except OSError:
            continue
        if any(a.encode("utf-8") in crudo for a in aghi):
            fuori.append(os.path.basename(percorso))
    return fuori


def _banco(dir_dati):
    """Il giro che una persona fa davvero: si iscrive, pubblica, scrive in chat. Si passa
    dalle ROTTE, non dalle funzioni: un anello provato chiamando la funzione dimostra che
    la funzione funziona, non che la catena esiste."""
    from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
    from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
    from fase83_server import crea_router
    import dataclasses
    campi = {f.name: os.path.join(dir_dati, f.name[3:] + ".db")
             for f in dataclasses.fields(ConfigCasaVIP) if f.name.startswith("db_")}
    sis = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"S" * 32,
                                     con_registrazione_host=True, commissione_bps=1500,
                                     psp_bps=300, **campi))
    router = crea_router(sis, host_key="hk", base_url="https://b.com")

    def chiama(metodo, path, corpo=None, intestazioni=None):
        return router.gestisci(metodo, path, {},
                               json.dumps(corpo) if corpo is not None else None,
                               intestazioni or {})

    stato, corpo = chiama("POST", "/api/host/registrazione",
                          {"email": EMAIL, "password": "passwordlunga1",
                           "ragione_sociale": RAGIONE, "telefono": TELEFONO,
                           "accetta_termini": True, "accetta_clausole": True,
                           "accetta_privacy": True, "doc_sha256": doc_sha256(),
                           "versione": CONTRATTO_HOST_VERSIONE})
    if stato != 201:
        return None, None, None, "la registrazione dell'host e' fallita: %s %s" % (stato, corpo)
    token = corpo.get("token")
    host_id = corpo.get("host_id") or ""
    stato, corpo = chiama("POST", "/api/host/pubblica",
                          {"slug": "casa-oblio", "titolo": "Casa " + RAGIONE,
                           "citta": "Roma", "prezzo_notte_cents": 10000, "capacita": 2},
                          {"X-Host-Token": token})
    if stato not in (200, 201):
        return None, None, None, "la pubblicazione e' fallita: %s %s" % (stato, corpo)
    msg = getattr(sis, "messaggistica", None)
    if msg is not None:
        msg.invia("rif-oblio", host_id, "ospite", host_id,
                  "scrivo dalla chat, sono " + RAGIONE)
    return sis, router, host_id, None


def principale(argomenti=None):
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("--guasto", default="", help="salta-oblio: prova che l'esame sa gridare")
    args = p.parse_args(argomenti)

    dir_dati = tempfile.mkdtemp(prefix="esame_oblio_")
    rossi, note = [], []
    try:
        sis, router, host_id, errore = _banco(dir_dati)
        if errore:
            print("⛔ PREMESSA MANCANTE: %s" % errore)
            print("   Senza il banco non si misura niente: NON ESEGUITO, mai verde.")
            return 1
        aghi = [a for a in (EMAIL, TELEFONO, RAGIONE, host_id) if a]

        archivi = sorted(os.path.basename(x)
                         for x in glob.glob(os.path.join(dir_dati, "*.db")))
        prima, ciechi_prima = _dove_compare(dir_dati, aghi)
        byte_prima = _nei_byte(dir_dati, aghi)

        print("=" * 78)
        print("🗑️  L'ESAME DELL'OBLIO — il giro intero, col denominatore")
        print("=" * 78)
        print("  archivi del sistema (contati dai file, come fa la produzione): %d" % len(archivi))
        print("  archivi in cui il dato della persona COMPARE, prima:           %d" % len(prima))
        for nome in sorted(prima):
            print("      · %-28s %s" % (nome, ", ".join(prima[nome])[:80]))
        if ciechi_prima:
            print("  ⚠️  archivi CIECHI (non letti, quindi non giudicati): %s" % ciechi_prima)

        # D18 punto 1 — la premessa. Se il dato non c'e' da nessuna parte, il banco non ha
        # costruito lo stato e qualunque «cancellato» sarebbe vero per il motivo sbagliato.
        if not prima:
            print()
            print("⛔ PREMESSA MANCANTE: il dato della persona non compare in NESSUN archivio.")
            print("   Non si sta misurando una cancellazione: non c'e' niente da cancellare.")
            return 1
        # ⛔ E LA SECONDA PREMESSA, che e' quella che si dimentica: se il dato non era nei
        # BYTE nemmeno prima, allora «non e' nei byte dopo» non dimostra niente — sarebbe
        # assente prima e assente dopo, cioe' un verde che non ha guardato. E' lo stesso
        # buco che il 2026-09-12 ha quasi fatto passare a vuoto una guardia sui byte.
        if not byte_prima:
            print()
            print("⛔ PREMESSA MANCANTE: il dato non si leggeva nei byte di nessun archivio")
            print("   nemmeno PRIMA della cancellazione. La misura sui byte non varrebbe.")
            return 1
        print("  archivi in cui il dato si legge nei BYTE, prima:               %d"
              % len(byte_prima))

        if args.guasto == "salta-oblio":
            print("\n  ⚠️  GUASTO INIETTATO: l'oblio NON viene eseguito (prova nelle due direzioni)")
            rapporto = {"ok": False, "verificato_archivi": [], "guasto": True}
        else:
            from fase156_erasure import cancella_attivita_host
            rapporto = cancella_attivita_host(sis, host_id, forza=True)

        dopo, ciechi_dopo = _dove_compare(dir_dati, aghi)
        byte_dopo = _nei_byte(dir_dati, aghi)
        verificati = list(rapporto.get("verificato_archivi") or [])

        print()
        print("  l'oblio dichiara ok:                %s" % rapporto.get("ok"))
        print("  archivi che l'oblio RICONTROLLA:    %d  (%s)"
              % (len(verificati), ", ".join(verificati) or "nessuno"))
        print("  archivi ancora SPORCHI dopo:        %d su %d" % (len(dopo), len(archivi)))
        for nome in sorted(dopo):
            print("      · %-28s %s" % (nome, ", ".join(dopo[nome])[:80]))
        print("  archivi in cui il dato si rilegge dai BYTE: %d  (%s)"
              % (len(byte_dopo), ", ".join(byte_dopo) or "nessuno"))

        # ── gli anelli, ognuno una DIFFERENZA fra prima e dopo ──────────────────────
        print()
        print("  ANELLI DEL GIRO (ognuno una differenza fra prima e dopo):")
        non_dichiarati = dict(rapporto.get("sporchi_non_dichiarati") or {})
        trattenuti = dict(rapporto.get("trattenuti_per_legge") or {})
        # Un archivio ancora sporco che l'oblio NON ha nemmeno visto e' peggio di uno
        # dichiarato: si misura la differenza fra i due, non la loro somma.
        invisibili = sorted(set(dopo) - set(rapporto.get("archivi_sporchi") or {}))
        anelli = []
        anelli.append(("il dato c'era", bool(prima),
                       "%d archivi lo contenevano" % len(prima)))
        anelli.append(("l'oblio dichiara di aver finito", bool(rapporto.get("ok")),
                       "ok=%s" % rapporto.get("ok")))
        # ⛔ Qui la scansione DEVE essere stata eseguita, e la pretesa sta qui e non dentro
        # `fase156`: li' un sistema in memoria (i banchi) non puo' scansionare, e legarci
        # l'esito produceva nove rossi falsi. Qui gli archivi sono file veri: se la
        # scansione non e' partita, questo giro non ha guardato gli archivi — e un giro che
        # non guarda non e' un giro verde.
        anelli.append(("la scansione degli archivi VERI e' stata eseguita",
                       not rapporto.get("scansione_non_eseguita"),
                       str(rapporto.get("scansione_non_eseguita") or "eseguita")))
        anelli.append(("nessun archivio resta sporco SENZA una dichiarazione",
                       not non_dichiarati,
                       "%d non dichiarati: %s" % (len(non_dichiarati),
                                                  ", ".join(sorted(non_dichiarati)) or "-")))
        anelli.append(("ogni TABELLA trattenuta porta il suo perche' scritto",
                       all(str(m).strip()
                           for motivi in trattenuti.values() for m in motivi.values()),
                       "trattenute: %s" % (", ".join(sorted(
                           t for motivi in trattenuti.values() for t in motivi)) or "-")))
        anelli.append(("l'oblio VEDE tutti gli archivi ancora sporchi", not invisibili,
                       "invisibili al suo controllo: %s" % (", ".join(invisibili) or "nessuno")))
        anelli.append(("l'oblio RICONTROLLA ogni archivio che conteneva il dato",
                       len(verificati) >= len(prima),
                       "ricontrolla %d, contenevano %d" % (len(verificati), len(prima))))
        # ⛔ I BYTE SI GUARDANO SOLO DOVE IL DATO DOVEVA SPARIRE. In un archivio trattenuto
        # per legge il dato c'e' ancora nelle righe, quindi trovarlo nei byte non e' un
        # residuo: e' il dato stesso. Cercarlo li' sarebbe un ROSSO FALSO — e un falso
        # allarme e' un difetto quanto un allarme mancato (regola ferrea 10). Trovato cosi',
        # al primo giro dopo la riparazione: l'esame accusava `accettazioni.db`.
        byte_da_pulire = [f for f in byte_dopo
                          if not any(f.startswith(n.rsplit(".db", 1)[0])
                                     for n in trattenuti)]
        anelli.append(("il dato non si rilegge dai byte degli archivi da PULIRE",
                       not byte_da_pulire,
                       "%d file lo contengono ancora: %s  (esclusi i trattenuti: %s)"
                       % (len(byte_da_pulire), ", ".join(byte_da_pulire) or "-",
                          ", ".join(sorted(trattenuti)) or "-")))
        anelli.append(("nessun archivio cieco", not (ciechi_prima or ciechi_dopo),
                       "ciechi: %d" % len(set(ciechi_prima) | set(ciechi_dopo))))
        for nome, esito, dettaglio in anelli:
            print("   %s  %-52s %s" % ("OK   " if esito else "ROSSO", nome, dettaglio))
            if not esito:
                rossi.append(nome)

        print()
        print("-" * 78)
        print("⛔ COSA QUESTO ESAME NON HA ESAMINATO (D18 punto 3)")
        print("   · SE un dato DOVEVA restare: per fisco e DAC7 alcuni archivi vanno")
        print("     conservati per legge, e l'obbligo si contraddice col diritto all'oblio.")
        print("     Qui si dice DOVE e' rimasto, mai se e' giusto che ci sia.")
        print("   · gli archivi che il banco non riempie: un archivio vuoto non puo'")
        print("     dimostrare niente sulla cancellazione, e infatti non e' contato fra")
        print("     quelli che «contenevano il dato».")
        print("   · i dati fuori dagli archivi: file caricati, registri, copie di")
        print("     salvataggio e la casella di posta. Nessuno di questi e' un file .db.")
        print("   · la QUARTA condizione D18: nessun test della suite fallisce se questo")
        print("     file sparisce. Dichiarato, non risolto.")
        print("-" * 78)
        if rossi:
            print("VERDETTO: ⛔ ROSSO — anelli %d, rossi %d, denominatore %d"
                  % (len(anelli), len(rossi), len(anelli)))
            return 1
        print("VERDETTO: ✅ VERDE — anelli %d su %d" % (len(anelli), len(anelli)))
        return 0
    finally:
        shutil.rmtree(dir_dati, ignore_errors=True)
        for riga in note:
            print(riga)


if __name__ == "__main__":
    sys.exit(principale())
