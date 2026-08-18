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


class NessunIngresso(RuntimeError):
    """Nessuno degli ingressi dichiarati esiste: non e' un risultato, e' l'assenza di misura.

    ⛔ Senza questa eccezione il cammino partirebbe dal vuoto e dichiarerebbe MORTI **tutti**
    i moduli del progetto, stampando un numero enorme con l'aria di un risultato. E' lo
    sbaglio S1 (*«ho confrontato due cose vuote e ho scritto UGUALI»*): il vuoto non e' un
    valore, e' l'assenza di misura -- e uno strumento che misura si ferma invece di stampare.
    """


def moduli_citati(percorso):
    try:
        with open(percorso, "r", encoding="utf-8", errors="replace") as f:
            testo = f.read()
    except OSError:
        return set()
    return set(RIF.findall(testo))


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
    print("  ⚠️  Un modulo morto NON e' un difetto: puo' essere roba costruita e mai")
    print("      collegata, o finita e in attesa di un gettone (SPENTA, non morta -- la")
    print("      differenza la sa REGISTRO_INGEGNERIA.md, non questo strumento). Diventa")
    print("      un problema quando qualcuno lo collauda credendo di collaudare il")
    print("      prodotto, o quando DOVEVA essere acceso (es. adempimenti di legge).")
    print("      Si guarda l'elenco, non si cancella niente a scatola chiusa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
