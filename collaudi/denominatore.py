"""IL DENOMINATORE DELLA MACCHINA — «cosa sto dimenticando?» diventa un NUMERO.

PERCHE' ESISTE. Ogni altro collaudo risponde alla domanda *«cio' che ho provato, funziona?»*.
Nessuno risponde a quella che il fondatore fa davvero: *«e tutto quello che dimentico?»*.
Finche' non c'e' un totale, «li abbiamo provati tutti?» e' una domanda a cui puo' rispondere
solo la memoria di qualcuno -- e la memoria qui ha gia' perso per otto giorni due attrezzi
scritti, finiti e mai portati dentro (`DA_METTERE_IN_collaudi`, 11 -> 19 agosto 2026).

Due strade indipendenti hanno chiesto la stessa cosa, ed e' per questo che esiste:
  · la nostra regola «ogni guardia dichiara il DENOMINATORE» (un numero senza il suo totale
    non e' una misura: 40 uccisi su 40 e 40 su 400 si scrivono uguali e valgono diverso);
  · la ricerca esterna di Anthropic sugli agenti a lungo termine, che chiede *«un elenco
    strutturato di tutte le funzioni richieste, leggibile da una macchina, ognuna marcata
    NON FUNZIONANTE finche' non e' provata -- per impedire di dichiarare finito troppo
    presto»* (anthropic.com/engineering/effective-harnesses-for-long-running-agents).

COSA CONTA, e ogni totale lo PRODUCE la macchina (D22: un numero non si scrive, si produce):
  ROTTE    le porte HTTP dichiarate dal router          <- fase83_server.py
  PAGINE   le pagine pubbliche servite dal sito          <- deploy/*.html
  EMAIL    i messaggi che la macchina sa spedire         <- fase86_email.py, `corpo_*_html`
  LINGUE   le lingue dichiarate supportate               <- fase61_localizzazione.py

Per ognuna dice se un collaudo la ATTRAVERSA, e stampa quante NON sono attraversate.

⛔ IL LIMITE, DICHIARATO PRIMA DEI NUMERI (D18 punto 3). «Attraversata» qui vuol dire
   **nominata** da un file di collaudo, non **eseguita**. E' lo stesso limite di
   `collaudi/piano.py`, e non e' un dettaglio: un modulo puo' essere nominato e morto al 94%
   dentro (misurato su fase133). Questo attrezzo dice **dove NON stiamo guardando di sicuro**;
   non promette che il resto sia guardato bene. Il numero di sinistra e' un tetto, non un voto.

USCITA: 0 se ha potuto misurare, 1 se **non** ha potuto (un totale a zero non e' «tutto
coperto»: e' assenza di misura, ed e' lo sbaglio S1). I punti non attraversati NON fanno
rosso: sono il lavoro che resta, e devono poter calare senza che nessuno spenga l'attrezzo.
"""
import io
import os
import re
import sys

try:  # Windows: la console cp1252 non regge i caratteri larghi -> uscita tollerante
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leggi(percorso):
    with io.open(percorso, encoding="utf-8", errors="replace") as f:
        return f.read()


def testi_dei_collaudi():
    """TUTTO cio' che collauda: i `test_*.py` della radice E gli attrezzi di `collaudi/`,
    compresi quelli col browser (`.js`). ⛔ Fermarsi ai `test_*.py` avrebbe dichiarato
    scoperto cio' che guarda il browser vero -- e il browser e' l'unica cosa che tocca le
    210 righe che girano dal cliente."""
    pezzi = {}
    for nome in sorted(os.listdir(REPO)):
        if nome.startswith("test_") and nome.endswith(".py"):
            pezzi[nome] = _leggi(os.path.join(REPO, nome))
    cartella = os.path.join(REPO, "collaudi")
    for nome in sorted(os.listdir(cartella)):
        if nome.endswith((".py", ".js")) and nome != os.path.basename(__file__):
            pezzi["collaudi/" + nome] = _leggi(os.path.join(cartella, nome))
    return pezzi


# ── I QUATTRO TOTALI, ognuno letto dalla macchina ────────────────────────────────────────
def rotte():
    """Le porte HTTP che il router dichiara. Stesse tre forme di `mappa_scoperta.py`: se il
    router cambia modo di dichiararle, i due attrezzi restano d'accordo o litigano insieme."""
    s = _leggi(os.path.join(REPO, "fase83_server.py"))
    return sorted(set(re.findall(r'path == "(/[^"]+)"', s))
                  | set(re.findall(r'path\.startswith\("(/[^"]+)"\)', s))
                  | set(re.findall(r'u\.path == "(/[^"]+)"', s)))


def pagine():
    """Le pagine pubbliche: i file che il sito serve davvero, non quelli di archivio."""
    cartella = os.path.join(REPO, "deploy")
    return sorted(n for n in os.listdir(cartella) if n.endswith(".html"))


def email():
    """I messaggi che la macchina sa spedire: una funzione `corpo_<qualcosa>_html` per tipo.
    E' il posto giusto dove contarli perche' e' l'unico da cui passano tutti."""
    s = _leggi(os.path.join(REPO, "fase86_email.py"))
    return sorted(set(re.findall(r"^def (corpo_\w+_html)\(", s, re.M)))


def lingue():
    """Le lingue DICHIARATE supportate, lette dalla tupla del modulo, non da un documento."""
    s = _leggi(os.path.join(REPO, "fase61_localizzazione.py"))
    m = re.search(r"LINGUE_SUPPORTATE\s*=\s*\(([^)]*)\)", s)
    return sorted(re.findall(r'"([a-z]{2})"', m.group(1))) if m else []


def attraversa(voce, testi, forme=None):
    """Un collaudo attraversa una voce se ne contiene una delle FORME FORTI.

    ⛔ LA PRIMA VERSIONE CERCAVA IL NOME NUDO, E DICEVA «0 SCOPERTE» SU TUTTE E QUATTRO LE
    FAMIGLIE (19 agosto 2026, misurato). Non era una buona notizia: era un criterio che non
    poteva fallire -- il modo di rompersi n. 4, dentro l'attrezzo che dovrebbe scoprirlo.
    Una lingua «it» compare in centinaia di righe che non provano niente sulle lingue.
    Le forme forti chiedono la prova d'USO: una rotta fra virgolette (cioe' chiamata, non
    citata in un commento), una funzione con la parentesi aperta (cioe' ESEGUITA).
    """
    for testo in testi.values():
        for forma in (forme or [voce]):
            if forma in testo:
                return True
    return False


def _virgolette(v):
    return ['"%s"' % v, "'%s'" % v]


def _virgolette_o_prefisso(v):
    """Per le ROTTE: virgoletta APERTA e poi la rotta, senza pretendere quella di chiusura.

    ⛔ NASCE DA TRE INNOCENTI ACCUSATI, 19 agosto 2026. Con le virgolette chiuse questo
    attrezzo dichiarava scoperte `/sitemap-host-`, `/stop` e `/host/azione` -- che sono
    dichiarate nel router con `startswith`, cioe' sono PREFISSI: i collaudi le chiamano col
    percorso intero (`"/sitemap-host-1.xml"`), quindi la forma chiusa non le trovava mai.
    Erano provate da sette file. Uno strumento che accusa innocenti viene spento, e allora
    non protegge piu' niente: e' la stessa ragione per cui il cercatore di gergo, il 18
    agosto, ha imparato a togliere i confronti prima di giudicare.
    """
    return ['"%s' % v, "'%s" % v]


FAMIGLIE = (
    # una rotta vale se compare dopo una virgoletta: e' la forma con cui la si chiama davvero
    ("ROTTE  ", "porte HTTP dichiarate dal router", rotte, _virgolette_o_prefisso),
    ("PAGINE ", "pagine pubbliche servite dal sito", pagine, _virgolette),
    # un messaggio vale se la sua funzione viene CHIAMATA, non solo nominata
    ("EMAIL  ", "messaggi che la macchina sa spedire", email, lambda e: ["%s(" % e]),
    # una lingua vale se e' passata come lingua a qualcosa, non se il codice compare e basta
    ("LINGUE ", "lingue dichiarate supportate", lingue,
     lambda l: ['lingua="%s"' % l, "lingua='%s'" % l, 'lingua = "%s"' % l,
                '"%s")' % l, "'%s')" % l]),
)


def coppie_messaggio_lingua(testi):
    """LA MISURA PIU' AFFILATA: ogni messaggio in ogni lingua.

    Un'email puo' essere provata benissimo **in italiano** e non essere mai stata generata in
    giapponese: e' il modo di rompersi n. 11 (lingua congelata), quello che nessun test aveva
    trovato e che vide il fondatore guardando il sito. Qui la coppia conta come attraversata
    solo se **la stessa riga** di un collaudo genera quel messaggio in quella lingua: cosi'
    non basta che il file parli di entrambe le cose in punti diversi.
    """
    messaggi, codici = email(), lingue()
    coperte = set()
    for testo in testi.values():
        # ⛔ IL CICLO VALE QUANTO LE OTTO RIGHE SCRITTE A MANO, e riconoscerlo non e' una
        #    comodita': senza, questo attrezzo premierebbe chi copia-incolla ottanta righe e
        #    dichiarerebbe scoperto chi scrive `for lingua in LINGUE_SUPPORTATE`, che e' il
        #    modo giusto. Un contatore che spinge a scrivere codice peggiore verrebbe
        #    ignorato, e un attrezzo ignorato non protegge niente.
        gira_su_tutte = "in LINGUE_SUPPORTATE" in testo
        for riga in testo.splitlines():
            presenti = [m for m in messaggi if "%s(" % m in riga]
            if not presenti:
                continue
            if gira_su_tutte:
                for m in presenti:
                    for codice in codici:
                        coperte.add((m, codice))
                continue
            for codice in codici:
                if ('"%s"' % codice) in riga or ("'%s'" % codice) in riga:
                    for m in presenti:
                        coperte.add((m, codice))
    tutte = [(m, c) for m in messaggi for c in codici]
    return tutte, sorted(set(tutte) - coperte)


def misura():
    """Restituisce, per famiglia: (totale, attraversate, elenco delle NON attraversate)."""
    testi = testi_dei_collaudi()
    fuori = {}
    for etichetta, _perche, elenca, forme in FAMIGLIE:
        voci = elenca()
        scoperte = [v for v in voci if not attraversa(v, testi, forme(v))]
        fuori[etichetta.strip()] = (len(voci), len(voci) - len(scoperte), scoperte)
    return fuori, len(testi)


if __name__ == "__main__":
    misure, quanti_collaudi = misura()
    print("=" * 86)
    print("IL DENOMINATORE — quante cose esistono, e quante NON le guarda nessuno")
    print("=" * 86)
    print("  file di collaudo esaminati: %d  (test_*.py della radice + collaudi/*.py e *.js)"
          % quanti_collaudi)
    print("  ⛔ «attraversata» = NOMINATA da un collaudo, non ESEGUITA: il numero di sinistra")
    print("     e' un tetto, non un voto (stesso limite dichiarato da collaudi/piano.py).")
    print("-" * 86)
    print("  %-8s %8s %8s %8s   %s" % ("famiglia", "totale", "viste", "SCOPERTE", "cosa conta"))
    vuote = []
    scoperte_totali = 0
    for etichetta, perche, _elenca, _forme in FAMIGLIE:
        totale, viste, scoperte = misure[etichetta.strip()]
        scoperte_totali += len(scoperte)
        if totale == 0:
            vuote.append(etichetta.strip())
        print("  %-8s %8d %8d %8d   %s" % (etichetta, totale, viste, len(scoperte), perche))
    for etichetta, _perche, _elenca, _forme in FAMIGLIE:
        _totale, _viste, scoperte = misure[etichetta.strip()]
        if scoperte:
            print("\n%s — le %d che NESSUN collaudo nomina:" % (etichetta.strip(),
                                                                len(scoperte)))
            for v in scoperte:
                print("    · %s" % v)
    # ── la misura affilata: messaggio × lingua ────────────────────────────────────────
    tutte, mancanti = coppie_messaggio_lingua(testi_dei_collaudi())
    print("\n" + "-" * 86)
    print("  MESSAGGIO x LINGUA — ogni email in ogni lingua (modo di rompersi n. 11)")
    print("  %-8s %8d %8d %8d   generate da un collaudo (stessa riga, o dentro un ciclo "
          "su tutte le lingue)"
          % ("COPPIE ", len(tutte), len(tutte) - len(mancanti), len(mancanti)))
    if mancanti:
        per_messaggio = {}
        for m, c in mancanti:
            per_messaggio.setdefault(m, []).append(c)
        for m in sorted(per_messaggio):
            print("    · %-32s mai generata in: %s"
                  % (m, " ".join(sorted(per_messaggio[m]))))
    scoperte_totali += len(mancanti)

    print("\n" + "=" * 86)
    print("SCOPERTE IN TUTTO: %d — e questo e' il numero che deve CALARE." % scoperte_totali)
    print("=" * 86)
    if vuote:
        # ⛔ UN TOTALE A ZERO NON E' «TUTTO COPERTO»: E' ASSENZA DI MISURA (sbaglio S1).
        # Se domani qualcuno rinomina `corpo_*_html` o sposta le pagine, questo attrezzo
        # troverebbe zero voci e stamperebbe «0 scoperte» -- il verde peggiore di tutti.
        # Meglio fermarsi e dirlo.
        print("⛔ NON HO POTUTO MISURARE: totale a ZERO per %s. Il vuoto non e' un risultato,"
              % ", ".join(vuote))
        print("   e' assenza di misura: vai a vedere se e' cambiato il posto da cui si conta.")
        sys.exit(1)
    sys.exit(0)
