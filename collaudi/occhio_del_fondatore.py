"""L'OCCHIO DEL FONDATORE — guardare le pagine come le guarda una persona.

PERCHE' ESISTE.
Due difetti veri, in due giorni, li ha trovati **il fondatore guardando il sito**, non i
3011 test:

  · `Zen House Shibuya` a **¥1.800.000 a notte** (lo yen non ha decimali: prezzo ×100);
  · **«clicco termini e lo leggo solo italiano»**, e lo stesso per la privacy.

Hanno una cosa in comune, ed e' la ragione per cui nessun collaudo li vedeva: erano
difetti di **cio' che si vede**, non di cio' che si esegue. I test provano che il codice
fa quello che dice. Nessuno chiedeva: **«una persona che apre questa pagina, cosa legge?»**

COSA MISURA, e perche' proprio questo.
Le pagine si traducono nel browser sostituendo il testo solo dentro gli elementi
**marcati**. I marcatori sono DUE, perche' due pagine sono nate in momenti diversi:
`data-t` (index) e `data-i18n` (host, admin, commissioni, diventa-host), piu' le varianti
per segnaposto e suggerimenti. Riconoscerne uno solo produrrebbe rossi falsi: e' successo
alla prima stesura di questo strumento, e va ricordato.
Ne segue una cosa netta, che si puo' contare:

    ogni parola visibile FUORI da un elemento marcato resta in ITALIANO
    per sempre, in tutte e otto le lingue, qualunque cosa scelga l'utente.

Quindi non serve la rete e non serve un browser: la percentuale di testo che un giapponese
leggera' in italiano e' **gia' scritta nell'HTML**, e si calcola. E' la stessa cosa che ha
visto il fondatore cliccando "termini", espressa in un numero.

COSA NON FA.
Non giudica la QUALITA' della traduzione (per quello serve un umano che parli la lingua):
giudica se la traduzione **puo' avvenire**. Una pagina al 100% congelata non ha bisogno di
un madrelingua per essere bocciata.
"""
import io
import os
import re
import sys
from html.parser import HTMLParser

# Windows: la console cp1252 non regge le emoji del report e l'audit moriva a meta'
# (UnicodeEncodeError su 👏). Uno strumento di collaudo non deve MAI cadere per un carattere:
# si forza l'uscita in UTF-8 tollerante, cosi' il verdetto arriva sempre in fondo.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

QUI = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(QUI)
PAGINE = os.path.join(REPO, "deploy")

# I DUE meccanismi di traduzione vivi nel sito. Chi ne aggiunge un terzo deve
# aggiungerlo qui, altrimenti questo strumento dara' per congelate pagine tradotte.
MARCATORI = ("data-t", "data-i18n")

# Sotto questa soglia di copertura la pagina si considera bocciata: un utente straniero
# leggerebbe piu' italiano che lingua propria.
SOGLIA = 60.0

# Testo che NON e' prosa da tradurre: marchio, sigle, simboli, numeri.
NON_PROSA = re.compile(
    r"^(bookinvip|casavip|vip|ok|id|url|api|iva|p\.iva|cin|sha|hmac|gdpr|dac7|"
    r"eur|usd|gbp|jpy|stripe|google|facebook|instagram|email|e-mail|http|https|"
    r"[0-9%€$£¥.,:;/\\|+\-–—()\[\]{}<>*#@_'\"…«»§°&]+)$", re.I)


class Lettore(HTMLParser):
    """Estrae il testo VISIBILE e segna quale e' traducibile e quale no."""

    def __init__(self):
        HTMLParser.__init__(self)
        self.pila = []              # profondita' -> dentro un elemento marcato?
        self.muto = 0               # dentro <script>/<style>: non si vede
        self.tradotto = []          # frammenti coperti da data-t
        self.congelato = []         # frammenti che restano in italiano
        self.attributi_scoperti = []
        self.marcati = 0

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag in ("script", "style"):
            self.muto += 1
            return
        marcato = any(a in d for a in MARCATORI)
        if marcato:
            self.marcati += 1
        # segnaposto e suggerimenti visibili: coperti solo se hanno il proprio marcatore
        for att, marcatori in (("placeholder", ("data-tph", "data-i18n-ph")),
                               ("title", ("data-ttitle", "data-i18n-title")),
                               ("alt", ("data-talt", "data-i18n-alt"))):
            if (d.get(att) and not any(m in d for m in marcatori)
                    and not _e_rumore(d[att])):
                self.attributi_scoperti.append("%s=\"%s\"" % (att, d[att][:60]))
        if tag not in ("br", "hr", "img", "input", "meta", "link", "source"):
            self.pila.append(marcato or (bool(self.pila) and self.pila[-1]))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.muto = max(0, self.muto - 1)
            return
        if self.pila:
            self.pila.pop()

    def handle_data(self, testo):
        if self.muto:
            return
        pulito = testo.strip()
        if not pulito or _e_rumore(pulito):
            return
        dentro = bool(self.pila) and self.pila[-1]
        (self.tradotto if dentro else self.congelato).append(pulito)


DOMINIO = re.compile(r"^[a-z0-9-]+\.[a-z]{2,}$", re.I)


def _e_prosa(parola):
    """Una parola da tradurre: minuscola, lunga, non un dominio, non una sigla.

    IL DISCRIMINE E' LA MINUSCOLA, e non e' un dettaglio. «New York», «Cape Town»,
    «Tokyo» sono NOMI PROPRI: restano uguali in ogni lingua e contarli come testo non
    tradotto gonfiava il verdetto (index.html risultava al 51% quando le frasi vere
    ferme erano quattro). Una frase da tradurre contiene sempre almeno una parola
    minuscola: articoli, verbi, preposizioni. «pubblica il tuo alloggio ora» si',
    «Buenos Aires» no.
    """
    nudo = re.sub(r"[^A-Za-zÀ-ÿ]", "", parola)
    if len(nudo) < 3 or NON_PROSA.match(parola) or DOMINIO.match(parola):
        return False
    return nudo[:1].islower()


def _e_rumore(t):
    """Vero se non e' prosa che un utente debba leggere tradotta."""
    return not any(_e_prosa(p) for p in re.split(r"\s+", t.strip()) if p)


def _parole(frammenti):
    """Conta solo le parole che una traduzione dovrebbe cambiare davvero."""
    n = 0
    for f in frammenti:
        n += sum(1 for p in re.split(r"\s+", f) if _e_prosa(p))
    return n


def esamina(percorso):
    with io.open(percorso, encoding="utf-8", errors="replace") as f:
        html = f.read()
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    lettore = Lettore()
    try:
        lettore.feed(html)
    except Exception:
        pass
    viste = _parole(lettore.tradotto)
    ferme = _parole(lettore.congelato)
    totale = viste + ferme
    copertura = (100.0 * viste / totale) if totale else 100.0
    return {
        "parole": totale,
        "tradotte": viste,
        "congelate": ferme,
        "copertura": copertura,
        "marcati": lettore.marcati,
        "esempi": lettore.congelato,
        "attributi": lettore.attributi_scoperti,
    }


def _peggiori(esempi, quanti=3):
    ordinati = sorted(set(esempi), key=lambda s: -_parole([s]))
    return [re.sub(r"\s+", " ", s)[:88] for s in ordinati[:quanti]]


def main():
    dettaglio = "--dettaglio" in sys.argv
    pagine = sorted(f for f in os.listdir(PAGINE) if f.endswith(".html"))
    print("=" * 92)
    print("L'OCCHIO DEL FONDATORE — «una persona che apre questa pagina, cosa legge?»")
    print("=" * 92)
    print("Le pagine si traducono solo dentro gli elementi marcati (%s)."
          % " / ".join(MARCATORI))
    print("Quello che sta fuori resta ITALIANO in tutte e 8 le lingue, per sempre.\n")
    print("  %-24s %7s %9s %9s   %s" % ("pagina", "parole", "tradotte", "FERME", "esito"))
    print("  " + "-" * 88)

    bocciate, parziali, parole_ferme = [], [], 0
    for p in pagine:
        r = esamina(os.path.join(PAGINE, p))
        parole_ferme += r["congelate"]
        # ATTENZIONE: qui la prima stesura scartava le pagine sotto le 15 parole come
        # "troppo poco testo". Era lo stesso errore gia' pagato altrove — ASSENZA NON E'
        # CONFORMITA'. `grazie.html` ha 14 parole, e' ferma allo 0%, e la legge OGNI
        # ospite che paga: e' il caso peggiore, non un caso trascurabile. Si scarta solo
        # cio' che statico non ha davvero testo (gusci riempiti dal server).
        if r["parole"] < 3:
            esito = "-- guscio: il testo arriva dal server"
        elif r["copertura"] >= 99.0:
            esito = "OK"
        elif r["copertura"] < SOGLIA:
            esito = "X  BOCCIATA (%.0f%% tradotta)" % r["copertura"]
            bocciate.append((p, r))
        else:
            esito = "!  parziale (%.0f%% tradotta)" % r["copertura"]
            parziali.append((p, r))
        print("  %-24s %7d %9d %9d   %s"
              % (p, r["parole"], r["tradotte"], r["congelate"], esito))

    print("\n" + "=" * 92)
    if bocciate:
        print("PAGINE CHE UNO STRANIERO LEGGE IN ITALIANO")
        print("=" * 92)
        for p, r in bocciate:
            print("\n  X %s — %d parole ferme su %d (%.0f%% tradotta, %d marcatori)"
                  % (p, r["congelate"], r["parole"], r["copertura"], r["marcati"]))
            for e in _peggiori(r["esempi"], 3 if not dettaglio else 12):
                print("        « %s »" % e)
    if parziali and dettaglio:
        print("\nPARZIALI — la pagina si traduce, ma qualche pezzo resta indietro")
        for p, r in parziali:
            print("\n  ! %s — %d parole ferme" % (p, r["congelate"]))
            for e in _peggiori(r["esempi"], 8):
                print("        « %s »" % e)

    print("\n" + "=" * 92)
    print("parole visibili che restano in italiano su TUTTO il sito: %d" % parole_ferme)
    if bocciate:
        print("pagine bocciate: %d  ->  %s"
              % (len(bocciate), ", ".join(p for p, _ in bocciate)))
        print("\nNon e' un dettaglio estetico: privacy e termini hanno valore legale, e")
        print("un consenso che l'utente non puo' leggere nella sua lingua vale poco.")
        return 1
    print("Nessuna pagina lascia lo straniero a leggere italiano.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
