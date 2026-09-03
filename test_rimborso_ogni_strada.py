"""CASELLA 2 del Blocco 1 (SOLDI) — «i soldi tornano DAVVERO all'ospite da OGNI strada».

LA PAROLA CHE COMANDA E' **OGNI**, e una casella che dice «ogni» non si spunta provando le
strade che qualcuno si e' ricordato di provare: si spunta **contando il denominatore** e
dimostrando che nessuna strada e' rimasta fuori. Questo file produce quel denominatore con
una macchina, invece di affidarlo a chi si ricorda di aggiornare un elenco.

⛔ **IL DENOMINATORE NON ME LO SONO INVENTATO: sta scritto in produzione.** `_giornale` in
`fase83_server.py` dichiara: *«Le strade che portano a un rimborso sono SETTE, e questo
progetto le ha gia' dimenticate due volte -- il 2026-08-16 ne era stata riparata una sola su
due, il 2026-08-17 ne mancavano quattro su sette»*. Qui il numero **si rimisura** a ogni giro:
una dichiarazione in un commento invecchia, un conteggio no.

⚠️ **PERCHE' `ast` E NON UN `grep`.** Cercare `tipo="rimborso"` come TESTO conta anche i
commenti — e in `fase83_server.py` ce n'e' uno che nomina quella stringa proprio per spiegare
le strade. Sarebbe **otto** invece di sette: lo sbaglio **S6** del progetto («una guardia che
un commento poteva soddisfare»), e lo stesso difetto che il 2026-09-02 e' stato trovato dentro
`collaudi/caccia_finti_verdi.py:66`. Qui si guarda l'**albero sintattico**: i commenti non ci
sono, e non possono ingannare il conteggio.

COSA SORVEGLIA, in due direzioni diverse:
  [A] il **denominatore**: quante strade scrivono un rimborso nel libro dei soldi, e che siano
      tutte **censite** qui sotto. Se qualcuno ne aggiunge un'ottava senza dichiararla, questa
      guardia diventa rossa **il giorno stesso** -- che e' l'unico modo di non dimenticarne una
      per la terza volta.
  [B] la **chiave contabile** di ognuna. Tre strade su sette condividono `rimborso:<rif>`, e la
      scrittura e' idempotente: **la prima che arriva vince**. Il censimento le dichiara una per
      una; se ne compare una quarta, o se una cambia chiave, la guardia cade.

⛔ COSA QUESTO FILE **NON** DIMOSTRA (D18 punto 3) — e va detto, perche' e' meta' della casella:
  · non dimostra che i soldi **arrivino** all'ospite: dimostra che ogni strada e' **censita** e
    che il libro dei soldi sa di doverli. «Promettono» e «pagano» sono due numeri diversi e
    vanno tenuti separati anche nel denominatore finale;
  · la collisione a tre e' qui **dichiarata**, non riparata: ripararla tocca `fase83_server.py`,
    che e' produzione, e la parola per farlo non e' stata chiesta. La prova del danno vero (due
    strade, importi diversi, il libro che dichiara il primo) e' stata misurata a parte e portata
    al coordinamento come difetto dimostrato, che e' il modo in cui si chiede quella parola.
"""
import ast
import os
import unittest

RADICE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(RADICE, "fase83_server.py")

# ⛔ IL CENSIMENTO: una riga per strada, con la CAUSALE (che la identifica in modo leggibile)
# e la CHIAVE contabile. `None` = la chiave non e' passata, quindi vale il default di
# `fase177`, che e' «<tipo>:<riferimento>» -> «rimborso:<rif>».
# Si aggiorna A MANO, di proposito: e' la dichiarazione di chi sa. La macchina la confronta
# col codice e grida se divergono, cosi' nessuna delle due puo' invecchiare in silenzio.
STRADE_CENSITE = {
    "rimborso disposto da admin": None,
    "rimborso deciso dall'arbitro (controversia risolta)": "rimborso_controversia:",
    "rimborso 100% per cancellazione host": None,
    "rimborso dovuto per cancellazione ospite": None,
    "rimborso dovuto: pagamento su prenotazione non confermabile (stato %s)":
        "rimborso_non_confermabile:",
    "rimborso dovuto: pagamento tardivo su stanza presa": "rimborso_tardivo:",
    "rimborso dovuto: anticipo su stanza già presa": "rimborso_anticipo_tardivo:",
}

# Le strade che condividono la chiave di default, DICHIARATE una per una. Sono tre, e la
# scrittura e' idempotente sull'evento: chi arriva prima scrive, gli altri due sono no-op.
# ⚠️ Non e' una proprieta' innocua -- e' il difetto misurato il 2026-09-02 -- ma qui si
# dichiara lo stato, non lo si assolve: vedi il limite dichiarato in cima al file.
CHIAVE_CONDIVISA_DICHIARATA = {
    "rimborso disposto da admin",
    "rimborso 100% per cancellazione host",
    "rimborso dovuto per cancellazione ospite",
}


def _prima_stringa(nodo):
    """Il valore letterale di un nodo, se e' una stringa; per una concatenazione `"a" + x`
    restituisce il pezzo letterale di sinistra (le chiavi sono scritte cosi'). None se non
    c'e' nessun letterale da leggere."""
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    # QUALSIASI operatore binario, non solo `+`: le causali sono scritte anche come
    # `"...(stato %s)" % stato`, che e' un `Mod`. Guardare solo l'addizione faceva tornare
    # None su una strada su sette -- e l'ha scoperto la prova della PREMESSA qui sotto, non
    # una rilettura: e' il motivo per cui quella prova esiste.
    if isinstance(nodo, ast.BinOp):
        return _prima_stringa(nodo.left)
    if isinstance(nodo, ast.JoinedStr):                     # f-string
        for pezzo in nodo.values:
            if isinstance(pezzo, ast.Constant) and isinstance(pezzo.value, str):
                return pezzo.value
    return None


def chiamate_al_giornale():
    """Ogni chiamata a `_giornale(tipo="rimborso", ...)`, come **LISTA**, piu' quelle in cui
    il `tipo` non si riesce a leggere.

    ⛔ **LISTA E NON DIZIONARIO, e la differenza e' un difetto vero — trovato dalla corsia A
    il 2026-09-03 e riprodotto qui prima di ripararlo.** La versione precedente faceva
    `trovate[causale] = chiave`: due strade con la **stessa causale** collassavano in una, e il
    conteggio non cambiava. Misurato sulla copia: strada in piu' con causale gia' esistente ->
    **7 prima, 7 dopo, invisibile**. E non era teorico: in questo stesso codice le stringhe si
    ripetono (tre strade condividono la chiave), quindi due causali uguali sono uno scenario
    normale, non un caso limite. ⇒ La guardia scritta per non dimenticarne una per la terza
    volta non l'avrebbe vista.
    ⚠️ **`tipo` NON LEGGIBILE E' UN ROSSO, NON UN «non e' un rimborso».** Se qualcuno scrive
    `tipo=_TIPO` (una costante), `_prima_stringa` torna `None`: prima si concludeva «non e' un
    rimborso» e la strada spariva. «Non riesco a leggerlo» e «non e' quello che cerco» sono due
    cose diverse, e confonderle e' lo sbaglio S7.
    ⚠️ E il nome si legge da `.attr` **e** da `.id`: una chiamata scritta senza `self.` non
    deve poter sfuggire solo per la forma con cui e' scritta."""
    with open(SERVER, "r", encoding="utf-8") as f:
        albero = ast.parse(f.read(), filename=SERVER)
    rimborsi, non_leggibili = [], []
    for nodo in ast.walk(albero):
        if not isinstance(nodo, ast.Call):
            continue
        nome = getattr(nodo.func, "attr", None) or getattr(nodo.func, "id", None)
        if nome != "_giornale":
            continue
        argomenti = {k.arg: k.value for k in nodo.keywords if k.arg}
        if "tipo" not in argomenti:
            continue
        tipo = _prima_stringa(argomenti["tipo"])
        if tipo is None:
            non_leggibili.append(getattr(nodo, "lineno", -1))
            continue
        if tipo != "rimborso":
            continue
        causale = _prima_stringa(argomenti.get("causale"))
        chiave = _prima_stringa(argomenti["evento_id"]) if "evento_id" in argomenti else None
        rimborsi.append((causale, chiave))
    return rimborsi, non_leggibili


def strade_dal_codice():
    """{causale: chiave}. Dice **QUALE** strada; il conteggio di **QUANTE** lo da'
    `chiamate_al_giornale()`, e servono tutti e due: questo collassa i doppioni per
    costruzione, quello no."""
    rimborsi, _ = chiamate_al_giornale()
    return dict(rimborsi)


class TestOgniStradaDelRimborsoECensita(unittest.TestCase):

    def test_il_conteggio_delle_strade_lo_fa_una_macchina_e_non_un_commento(self):
        """PREMESSA di tutto il resto: l'attrezzo deve saper leggere il codice.

        Se `strade_dal_codice()` tornasse vuoto per un cambio di struttura, ogni altra prova
        di questo file passerebbe **per assenza** — verde senza aver guardato niente (S7)."""
        strade = strade_dal_codice()
        self.assertGreater(
            len(strade), 0,
            "PREMESSA NON VALIDA: nessuna chiamata `_giornale(tipo=\"rimborso\")` trovata "
            "nell'albero sintattico di fase83_server.py. O il metodo e' stato rinominato, o "
            "l'attrezzo non sa piu' leggere il codice: in entrambi i casi le prove qui sotto "
            "sarebbero verdi per assenza, e non vanno credute.")
        self.assertNotIn(
            None, strade,
            "una strada scrive un rimborso senza `causale` letterale: non e' identificabile, "
            "e una strada che non si sa nominare non si sa nemmeno provare.")

    def test_QUANTE_strade_ci_sono_si_conta_sulle_CHIAMATE_non_sulle_causali(self):
        """⛔ IL DENOMINATORE SI CONTA SUI NODI, NON SULLE VOCI DI UN DIZIONARIO.

        Difetto trovato dalla **corsia A** il 2026-09-03 e riprodotto qui prima di ripararlo:
        indicizzando per causale, una strada in piu' con una causale **gia' esistente** era
        **invisibile** (7 prima, 7 dopo). E non e' un caso limite — in questo codice le
        stringhe si ripetono davvero.
        Qui si contano le **chiamate**: due strade con la stessa causale fanno **due**."""
        rimborsi, non_leggibili = chiamate_al_giornale()
        self.assertEqual(
            non_leggibili, [],
            "⛔ UNA CHIAMATA SCRIVE NEL GIORNALE CON UN `tipo` CHE NON SI RIESCE A LEGGERE "
            "(righe %r): probabilmente e' una costante o una variabile. Non si puo' concludere "
            "«allora non e' un rimborso» — «non riesco a leggerlo» e «non lo e'» sono due cose "
            "diverse (S7). Finche' non e' leggibile, il denominatore non e' affidabile."
            % (non_leggibili,))
        self.assertEqual(
            len(rimborsi), len(STRADE_CENSITE),
            "IL NUMERO DI STRADE NON COINCIDE COL CENSIMENTO: %d chiamate che scrivono un "
            "rimborso, %d censite. ⚠️ Se le due liste dei NOMI tornano ma i CONTI no, vuol "
            "dire che due strade condividono la causale — e allora il censimento per nome "
            "sta guardando una strada sola dove ce ne sono due.\n  chiamate: %r"
            % (len(rimborsi), len(STRADE_CENSITE), rimborsi))

    def test_LA_PREMESSA_NASCOSTA_le_causali_sono_DISTINTE(self):
        """⛔ La premessa su cui poggia tutto il censimento per nome, finora **implicita**.

        `STRADE_CENSITE` e' un dizionario indicizzato sulla causale: funziona **solo se** le
        causali identificano una strada sola. Nessuno lo controllava — e una premessa non
        dichiarata e' esattamente il posto in cui un attrezzo smette di misurare senza che
        niente diventi rosso. Se un domani due strade condividono la causale, questa cade e
        dice cosa fare, invece di lasciare il denominatore sbagliato in silenzio."""
        rimborsi, _ = chiamate_al_giornale()
        causali = [c for c, _k in rimborsi]
        doppie = sorted({c for c in causali if causali.count(c) > 1})
        self.assertEqual(
            doppie, [],
            "DUE STRADE CONDIVIDONO LA CAUSALE %r. Il censimento per nome le vede come UNA, "
            "quindi da qui in poi «7 su 7» non vuol piu' dire quello che sembra. Rimedio: "
            "dare a ognuna una causale sua (e' anche cio' che le distingue nel libro dei "
            "soldi per chi legge), oppure censirle per riga invece che per nome." % (doppie,))

    def test_NESSUNA_STRADA_NUOVA_SFUGGE_AL_CENSIMENTO(self):
        """⛔ È la guardia che impedisce di dimenticarne una per la TERZA volta.

        Il progetto le ha gia' perse due volte (una su due il 2026-08-16, quattro su sette il
        2026-08-17). Un elenco scritto a mano si rompe; un elenco confrontato col codice a ogni
        giro no."""
        nel_codice = set(strade_dal_codice())
        censite = set(STRADE_CENSITE)
        nuove = nel_codice - censite
        sparite = censite - nel_codice
        self.assertEqual(
            nuove, set(),
            "STRADA NUOVA NON CENSITA: qualcuno ha aggiunto un modo di rimborsare e non l'ha "
            "dichiarato qui. Finche' non e' nel censimento nessuno sa se i soldi tornano "
            "davvero da li': aggiungila a STRADE_CENSITE con la sua chiave contabile, e "
            "provala fino ai soldi. Strade nuove: %r" % (sorted(nuove),))
        self.assertEqual(
            sparite, set(),
            "STRADA SPARITA DAL CODICE ma ancora censita: %r. Se e' stata rimossa davvero, "
            "toglila da qui; se e' stata solo rinominata, il censimento sta sorvegliando un "
            "nome che non esiste piu' -- cioe' non sorveglia niente." % (sorted(sparite),))

    def test_la_chiave_contabile_di_ogni_strada_e_quella_dichiarata(self):
        """Ogni strada deve avere la chiave che il censimento le attribuisce.

        Cambiare la chiave di una strada cambia **se** la sua riga entra nel libro dei soldi
        quando ce n'e' gia' una per la stessa prenotazione: non e' un dettaglio di forma."""
        nel_codice = strade_dal_codice()
        for causale, chiave_attesa in STRADE_CENSITE.items():
            with self.subTest(strada=causale):
                self.assertIn(causale, nel_codice,
                              "strada censita ma non trovata nel codice: %r" % causale)
                self.assertEqual(
                    nel_codice[causale], chiave_attesa,
                    "la strada %r ha cambiato chiave contabile: censita %r, trovata %r. "
                    "Se il cambio e' voluto aggiorna il censimento; se non lo e', qualcuno "
                    "ha appena spostato una riga di denaro in un altro secchio."
                    % (causale, chiave_attesa, nel_codice[causale]))

    def test_LE_STRADE_CHE_CONDIVIDONO_LA_CHIAVE_SONO_ESATTAMENTE_QUELLE_DICHIARATE(self):
        """⛔ Tre strade su sette scrivono con la chiave di default `rimborso:<rif>`, e la
        scrittura e' idempotente: **la prima che arriva vince**, le altre due sono no-op.

        Non e' un dettaglio contabile. Le tre scrivono importi DIVERSI per costruzione — la
        cancellazione ospite scrive il dovuto al netto della penale, il rimborso admin scrive
        il totale — quindi se su una stessa prenotazione ne passa piu' d'una, il libro dei
        soldi dichiara la PRIMA, non quella che ha davvero mosso il denaro.
        ⚠️ Qui lo stato viene **dichiarato**, non assolto: ripararlo tocca produzione. Questa
        guardia serve perche' il gruppo non cresca in silenzio — una QUARTA strada che
        finisse sulla stessa chiave allargherebbe il difetto senza che niente diventi rosso."""
        nel_codice = strade_dal_codice()
        condividono = {c for c, k in nel_codice.items() if k is None}
        self.assertEqual(
            condividono, CHIAVE_CONDIVISA_DICHIARATA,
            "l'insieme delle strade che condividono la chiave contabile `rimborso:<rif>` e' "
            "cambiato.\n  dichiarate: %r\n  trovate   : %r\n"
            "Se ne e' comparsa una nuova, il difetto della prima-che-vince si e' allargato a "
            "una strada in piu' e va misurato prima di dichiararlo accettabile. Se una e' "
            "stata riparata (ha una chiave propria), TOGLILA da qui: e' una buona notizia che "
            "va scritta." % (sorted(CHIAVE_CONDIVISA_DICHIARATA), sorted(condividono)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
