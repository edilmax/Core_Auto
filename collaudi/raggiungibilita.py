"""QUALI MODULI LA PRODUZIONE ACCENDE DAVVERO — sola lettura.

A COSA SERVE, e cosa vede che nessun altro vede. L'appendice 23 («COSTRUITO ≠ COLLEGATO»)
ha una guardia che conta gli IMPORTATORI di ogni `fase*.py`: se sono zero, il modulo e'
orfano. Ma quella guardia **non puo' vedere un grappolo di moduli morti che si importano a
vicenda**: ognuno ha i suoi importatori, quindi passano tutti.

⛔ IL NUMERO NON STA SCRITTO QUI, E NON DEVE. Lo produce questo strumento quando lo si
lancia. Fino al 2026-08-17 in questa intestazione c'era una cifra («63 morti su 151»)
misurata il 9 agosto: e' finita in SETTE punti dei documenti ufficiali, uno dei quali la
usava come ISTRUZIONE per scegliere su cosa lavorare. Era **sbagliata**, e nessuno poteva
accorgersene perche' era prosa. Regola che ne esce, e vale oltre questo file: *un numero che
descrive lo stato della macchina non si scrive, si PRODUCE quando lo si legge.*

⛔⛔ SI PARTE DA TUTTI GLI INGRESSI, NON DA UNO — ed e' il difetto riparato il 2026-08-17.
Fino a quel giorno il cammino partiva dal solo `main_casavip.py`, mentre gli ingressi sono
piu' d'uno. Guardia: `test_pipeline_ci.TestLaRaggiungibilitaNONPuoGuardareUnIngressoSOLO`,
vista rossa prima.

⛔⛔ MA «INGRESSO» NON VUOL DIRE «FILE CHE STA SUL DISCO» — correzione del 2026-08-18, e la
prima versione di questa riparazione ci era cascata dentro. Il 17 agosto fu aggiunto anche
`app.py`, descritto come «un file da cui la macchina si accende davvero»: la produzione non
lo contiene nemmeno (nessuna delle due immagini lo copia, e dentro il container che gira sul
server non esiste). Era l'unico ingresso che raggiungeva quattro moduli, fra cui
`fase17_money` e `fase15_idempotency`, e per colpa sua il conto dei morti diceva 59 invece
di 63: due moduli che muovono denaro risultavano ACCESI grazie a un file spento.
💡 **Un ingresso e' un file che l'artefatto di produzione CONTIENE E AVVIA.** Adesso
l'elenco qui sotto non ci si puo' discostare: la guardia lo confronta con le `COPY` e il
`CMD` del Dockerfile, che e' l'unica autorita' su cosa viene spedito.

BIAS DICHIARATO (D18 punto 3), ed e' voluto: **GENEROSO**. Conta un import ovunque compaia
nel file — anche dentro una funzione (import pigro) e anche dentro un `try/except`. Quindi
puo' dichiarare VIVO qualcosa che di fatto non parte mai; ma se dice **MORTO, e' morto
davvero**. E' il verso giusto in cui sbagliare: meglio non accorgersi di un cadavere che
seppellire un vivo. ⚠️ E fino al 2026-08-17 quella promessa era FALSA: partendo da un
ingresso solo, quattro vivi venivano seppelliti. Un attrezzo che promette di sbagliare in un
verso e sbaglia nell'altro e' peggio di un attrezzo senza promesse (sbaglio S15).

⛔ COSA NON FA: non esegue niente, non risolve gli import dinamici costruiti a stringa
(`importlib.import_module(nome)` con `nome` calcolato), non guarda i file statici. Un modulo
raggiunto SOLO cosi' risulterebbe morto a torto: prima di dichiarare morto qualcosa si
guarda anche con `grep`.
⛔ E NON DISTINGUE «MORTO» DA «SPENTO». Un modulo puo' essere finito, corretto e in attesa di
un gettone (`fase193_canale_mastodon`, `fase189_price_alerts`...): da qui e' indistinguibile
da un rudere. Chi ha quel fatto e' `REGISTRO_INGEGNERIA.md`, che per ogni modulo dichiara
STATO e come si accende. Non si cancella niente a scatola chiusa.

USO:   python collaudi/raggiungibilita.py
"""
import os
import re
import sys

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ⛔ GLI INGRESSI SONO PIU' DI UNO. Si dichiarano qui, in chiaro, perche' una guardia possa
# pretenderli e perche' il giorno che ne nasce un terzo si veda cosa manca. Sono i file da
# cui la macchina si accende davvero: il processo di produzione (`main_casavip.py`, che e' il
# `CMD` dell'immagine) e il server delle rotte (`fase83_server.py`), che ne importa a decine
# per conto suo.
#
# ⛔⛔ QUI DENTRO C'ERA ANCHE `app.py`, ED ERA UNA BUGIA — tolto il 2026-08-18, misurando
# invece di leggere il commento che lo dichiarava «un file da cui la macchina si accende
# davvero». La produzione non lo contiene nemmeno:
#     Dockerfile.casavip -> COPY main_casavip.py ./ | COPY fase*.py ./ | COPY deploy ./deploy
#     Dockerfile (generico) -> le stesse tre COPY, stesso CMD
#     docker exec casavip_app ls app.py  ->  No such file or directory
#     l'altro prodotto (tavolavip) parte da `fase36_booking_api`, non da qui
# Non e' un dettaglio di forma: `app.py` era l'UNICO ingresso che raggiungeva quattro moduli
# (`fase13_protocollo_finale`, `fase15_idempotency`, `fase17_money`, `fase23_datastore`), e
# per quella riga il conto dei morti diceva 59 invece di 63. Cioe' due moduli che si chiamano
# `money` e `idempotency` risultavano ACCESI grazie a un file che non gira per nessuno --
# esattamente il contrario del bias generoso che questo strumento promette.
# 💡 La regola che ne esce: **un ingresso non e' un file che sta sul disco, e' un file che
# l'artefatto di produzione contiene e avvia.** La guardia
# `test_pipeline_ci.TestLaRaggiungibilitaNONPuoGuardareUnIngressoSOLO` non si fida piu' di
# questo elenco: lo confronta con le `COPY` e il `CMD` del Dockerfile, e diventa rossa se
# qui dentro compare un file che l'immagine non spedisce.
INGRESSI = ("main_casavip.py",)

# ⛔⛔ E PERCHE' UNO SOLO, dopo che il 2026-08-17 la lezione era «non partire da uno solo»?
# Perche' quella lezione era giusta e la sua applicazione no. Misurato il 2026-08-18:
#     da main_casavip.py da solo : 88 moduli
#     da main + fase83_server    : 88 moduli   -> fase83_server AGGIUNGE ZERO
#     fase83_server e' raggiunto da main? True
# `fase83_server` non era un ingresso: era un modulo gia' raggiunto, elencato due volte. E
# `app.py` non era un ingresso affatto (non lo spedisce nessuna immagine). Restava una sola
# cosa vera: **il file che l'immagine AVVIA**, cioe' il `CMD` del Dockerfile.
# 💡 Il criterio «un file spedito» sembrava stretto e non lo era: il Dockerfile copia
# `fase*.py`, quindi avrebbe accettato come ingresso **151 moduli su 152** -- bastava
# aggiungerne uno per gonfiare i vivi senza che nessuna guardia gridasse. L'ha visto una
# revisione indipendente, non io. Il criterio giusto e' l'unico che non si puo' allargare:
# gli ingressi sono ESATTAMENTE i moduli nominati dal `CMD`, e la guardia
# `test_GLI_INGRESSI_SONO_ESATTAMENTE_QUELLO_CHE_L_IMMAGINE_AVVIA` pretende l'uguaglianza,
# non l'inclusione.

# Il Dockerfile che costruisce l'immagine VERA di produzione: e' lui l'autorita' su cosa
# viene spedito, non un elenco scritto a mano (la guardia lo legge da qui).
DOCKERFILE_PRODUZIONE = "Dockerfile.casavip"

# Nome storico, tenuto perche' qualcuno potrebbe passarlo a mano a `cammina(partenza=...)`.
PARTENZA = INGRESSI[0]

# 'import faseNN_x' oppure 'from faseNN_x import ...'
RIF = re.compile(r"\b(?:from|import)\s+(fase\d+[A-Za-z0-9_]*)")

# ⛔⛔ E CHI CARICA UN MODULO SCRIVENDONE IL NOME — cecita' riparata il 2026-09-09.
# `RIF` qui sopra vede la parola `import`; non vede questo, che pero' e' un import a tutti
# gli effetti (`fase91_canali_social.py`, righe 144-148, modulo che la produzione ESEGUE):
#     for mod, fn, nome in (("fase193_canale_mastodon", ...), ("fase194_canale_bluesky", ...),
#                           ("fase195_canale_reddit", ...), ("fase197_canale_nostr", ...)):
#         c = getattr(__import__(mod), fn)(e, fetch=fetch)
# Quei quattro finivano fra i MORTI pur essendo gia' cablati (dormono solo perche' manca il
# gettone nel `.env`), e il conto diceva 63 invece di 59.
# ⚠️ NON e' un limite: e' una PROMESSA ROTTA. Il file dichiarava il buco in una riga di
# docstring e due paragrafi sopra prometteva «se dice MORTO, e' morto davvero». Le due cose
# non stanno insieme, e la seconda e' quella su cui la gente agisce: chi legge «morto»
# CANCELLA. E' lo sbaglio S15 nella forma che l'intestazione stessa aveva gia' nominato --
# «un attrezzo che promette di sbagliare in un verso e sbaglia nell'altro».
# 💡 PERCHE' SI GUARDA IL FILE E NON L'ARGOMENTO DELLA CHIAMATA. Il nome non sta dentro
# `__import__(...)`: sta in una tupla qualche riga sopra, e l'argomento e' una variabile.
# Seguire la variabile vorrebbe dire eseguire il codice; questo strumento non esegue niente.
# Quindi la regola e' quella generosa, e vale SOLO nei file che caricano per nome: in un file
# che carica per nome, ogni nome di modulo nostro scritto in una stringa conta come import.
# Cosi' il bias resta quello dichiarato -- puo' dire VIVO qualcosa che non parte mai, mai il
# contrario. ⚠️ Il perimetro NON e' supposto, e' misurato (2026-09-09):
#     grep -rn "__import__\|importlib.import_module" --include="fase*.py" .
# -> UN solo punto in tutto il repository carica un NOSTRO modulo per nome; gli altri
# caricano `time` e `calendar`, cioe' libreria di sistema. Guardia:
# `test_pipeline_ci.TestUnModuloCaricatoPerNOMENonPuoRisultareMORTO`, vista rossa prima.
RIF_CARICA_PER_NOME = re.compile(r"(?:__import__|importlib\.import_module)\s*\(")
RIF_NOME_IN_STRINGA = re.compile(r"[\"'](fase\d+[A-Za-z0-9_]*)[\"']")
# L'argomento della chiamata, quando E' una stringa scritta li' (caso facile e frequente).
RIF_ARGOMENTO_LETTERALE = re.compile(
    r"(?:__import__|importlib\.import_module)\s*\(\s*[\"']([A-Za-z0-9_.]+)[\"']")


class NessunIngresso(RuntimeError):
    """Nessuno degli ingressi dichiarati esiste: non e' un risultato, e' l'assenza di misura.

    ⛔ Senza questa eccezione il cammino partirebbe dal vuoto e dichiarerebbe MORTI **tutti**
    i moduli del progetto, stampando un numero enorme con l'aria di un risultato. E' lo
    sbaglio S1 (*«ho confrontato due cose vuote e ho scritto UGUALI»*): il vuoto non e' un
    valore, e' l'assenza di misura -- e uno strumento che misura si ferma invece di stampare.
    """


def _testo(percorso):
    try:
        with open(percorso, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def moduli_citati(percorso):
    testo = _testo(percorso)
    if testo is None:
        return set()
    citati = set(RIF.findall(testo))
    # In un file che carica per nome, ogni nome di modulo nostro scritto in una stringa
    # conta come import: e' il bias generoso applicato dove serve (vedi RIF_CARICA_PER_NOME).
    if RIF_CARICA_PER_NOME.search(testo):
        citati |= set(RIF_NOME_IN_STRINGA.findall(testo))
    return citati


def caricamenti_per_nome(radice=RADICE):
    """(risolti, non_risolti): dove qualcuno carica un modulo scrivendone il NOME.

    ⛔ ESISTE PERCHE' UN LIMITE SCRITTO IN PROSA NON E' UNA MISURA (D18 punto 3). Fino al
    2026-09-09 questo file dichiarava «non risolve gli import dinamici costruiti a stringa»
    in una riga di docstring: vera, invisibile, e smentita due paragrafi sopra dalla promessa
    «se dice MORTO, e' morto davvero». Adesso i punti si CONTANO e si ELENCANO.

    `risolti`     -> {file: [nostri moduli caricati per nome da quel file]}
    `non_risolti` -> righe leggibili «file:riga argomento» per le chiamate il cui argomento
                     NON e' una stringa scritta li'. Non sono un guasto: sono i punti in cui
                     il nome e' stato dedotto dalle stringhe del file invece che letto dalla
                     chiamata, e il giorno che qualcuno costruisce un nome a pezzi
                     (`"fase" + str(n)`) quel punto compare qui invece di sparire in silenzio.
    """
    risolti, non_risolti = {}, []
    nomi = [n for n in sorted(os.listdir(radice))
            if re.fullmatch(r"fase\d+[A-Za-z0-9_]*\.py", n)] + list(INGRESSI)
    # ⛔ SOLO I MODULI CHE ESISTONO DAVVERO (S2: i nomi si leggono dal disco, non si
    # riconoscono a forma). Senza questo filtro il rapporto stampava `fase83_server ->
    # fase1`, che non e' un modulo ma una stringa qualunque che somiglia a un nome: il
    # cammino la scartava comunque (`& tutti`), ma il RAPPORTO diceva una cosa falsa -- ed
    # e' il rapporto quello che legge una persona.
    esistenti = {n[:-3] for n in nomi if n.endswith(".py")}
    for nome in nomi:
        testo = _testo(os.path.join(radice, nome))
        if testo is None or not RIF_CARICA_PER_NOME.search(testo):
            continue
        nostri = sorted(set(RIF_NOME_IN_STRINGA.findall(testo)) & esistenti)
        if nostri:
            risolti[nome[:-3] if nome.endswith(".py") else nome] = nostri
        for numero, riga in enumerate(testo.splitlines(), 1):
            if not RIF_CARICA_PER_NOME.search(riga):
                continue
            if RIF_ARGOMENTO_LETTERALE.search(riga):
                continue          # il nome sta nella chiamata: letto, non dedotto
            non_risolti.append(
                "%s:%d  %s  -> argomento calcolato; nomi dedotti dalle stringhe del file: %s"
                % (nome, numero, riga.strip()[:70], nostri or "NESSUNO"))
    return risolti, non_risolti


def ingressi_veri(radice=RADICE):
    """Gli ingressi DICHIARATI che esistono davvero sul disco (S2: i nomi si leggono)."""
    return tuple(n for n in INGRESSI if os.path.isfile(os.path.join(radice, n)))


def cammina(radice=RADICE, partenza=None):
    """(vivi, morti, tutti): i moduli raggiungibili dai punti di accensione, e gli altri.

    `partenza=None` (di serie) vuol dire **tutti** gli ingressi che esistono. Passarne uno
    solo serve alle guardie, per chiedere «cosa raggiunge QUESTO ingresso?» — non e' il modo
    di misurare i morti, ed e' esattamente l'errore che si faceva prima.
    """
    tutti = {n[:-3] for n in os.listdir(radice)
             if re.fullmatch(r"fase\d+[A-Za-z0-9_]*\.py", n)}
    punti = (partenza,) if partenza else ingressi_veri(radice)
    if not punti:
        raise NessunIngresso(
            "nessuno degli ingressi dichiarati esiste in %s (cercati: %s): senza un punto di "
            "partenza questo strumento non puo' dire chi e' vivo, e dichiarare morti tutti i "
            "moduli sarebbe un numero, non una misura" % (radice, ", ".join(INGRESSI)))
    vivi = set()
    for punto in punti:
        # ⛔ L'INGRESSO STESSO E' VIVO — PER DEFINIZIONE, NON PER FORTUNA. Trovato da una
        # revisione indipendente il 2026-08-18, poche ore dopo che questo file era stato
        # «riparato»: il cammino partiva DAGLI IMPORT del punto di partenza e non contava
        # mai il punto di partenza. Finche' gli ingressi erano `main_casavip.py` (che non e'
        # un `fase*.py`, quindi fuori dall'universo misurato) il caso non si poneva. Da
        # quando fra gli ingressi c'e' `fase83_server.py`, lo strumento poteva dichiarare
        # MORTO il proprio ingresso dichiarato -- e sbagliare di nuovo nel verso brutto,
        # rompendo la stessa promessa («se dice MORTO, e' morto davvero») che questo file
        # aveva appena finito di ristabilire.
        # ⚠️ Misurato allora: `fase83_server` risultava vivo **soltanto perche' qualcosa
        # dentro la sua chiusura lo re-importa**; `fase36_booking_api` e `fase17_money`, usati
        # come partenza, risultavano morti di se' stessi. Un invariante che regge per
        # coincidenza non e' un invariante.
        vivi.update({punto[:-3]} & tutti)
        da_visitare = [m for m in moduli_citati(os.path.join(radice, punto)) & tutti
                       if m not in vivi]
        vivi.update(da_visitare)
        while da_visitare:
            m = da_visitare.pop()
            for nuovo in moduli_citati(os.path.join(radice, m + ".py")) & tutti:
                if nuovo not in vivi:
                    vivi.add(nuovo)
                    da_visitare.append(nuovo)
    return vivi, tutti - vivi, tutti


def main():
    try:
        vivi, morti, tutti = cammina()
    except NessunIngresso as errore:
        print("⛔ MISURA NON VALIDA — %s" % errore)
        return 1
    usati = ingressi_veri()
    print("=" * 78)
    print("RAGGIUNGIBILITA' DAI PUNTI DI ACCENSIONE DELLA PRODUZIONE")
    print("  partenza: %s" % ", ".join(usati))
    print("  -> import transitivi, bias GENEROSO (se dice MORTO, e' morto)")
    # ⛔ IL DENOMINATORE SI DICHIARA. Un ingresso dichiarato e assente cambierebbe il numero
    # senza che nessuno lo veda: qui si vede.
    assenti = [n for n in INGRESSI if n not in usati]
    if assenti:
        print("  ⚠️  ingressi dichiarati che sul disco NON ci sono: %s" % ", ".join(assenti))
    print("=" * 78)
    print("  moduli fase*.py sul disco ............ %d" % len(tutti))
    print("  RAGGIUNGIBILI dalla produzione ....... %d" % len(vivi))
    print("  NON raggiungibili (codice morto) ..... %d" % len(morti))
    print()
    print("  I NON RAGGIUNGIBILI, in ordine:")
    for m in sorted(morti):
        print("     ", m)
    print()
    risolti, non_risolti = caricamenti_per_nome()
    print("  CARICATI PER NOME (`__import__` / `import_module`), contati come vivi:")
    if risolti:
        for chi in sorted(risolti):
            print("      %s -> %s" % (chi, ", ".join(risolti[chi])))
    else:
        print("      nessuno")
    if non_risolti:
        print("  ⚠️  chiamate il cui ARGOMENTO non e' scritto li' (nome dedotto dal file):")
        for riga in non_risolti:
            print("      %s" % riga)
    print()
    print("  ⚠️  Un modulo morto NON e' un difetto: puo' essere roba costruita e mai")
    print("      collegata, o finita e in attesa di un gettone (SPENTA, non morta -- la")
    print("      differenza la sa REGISTRO_INGEGNERIA.md, non questo strumento). Diventa")
    print("      un problema quando qualcuno lo collauda credendo di collaudare il")
    print("      prodotto, o quando DOVEVA essere acceso (es. adempimenti di legge).")
    print("      Si guarda l'elenco, non si cancella niente a scatola chiusa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
