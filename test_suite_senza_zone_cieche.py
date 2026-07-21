"""GUARDIA SULLA SUITE STESSA — nessun test puo' essere invisibile.

Un test che non gira e' peggio di un test che manca: quello che manca lo sai, quello che
non gira ti dice verde. Qui si sorvegliano i modi in cui un test sparisce **senza che
nessuno lo tolga**, cercando il PATTERN nel codice invece dei singoli casi — cosi' si
chiude la classe, non l'esemplare.

I MODI, tutti incontrati sul campo in questo progetto:

1. CLASSI DEFINITE DOPO `unittest.main()`.
   `unittest.main()` gira nel momento in cui l'interprete ci arriva: tutto quello che sta
   piu' in basso nel file **non e' ancora stato definito**, quindi non viene raccolto.
   Sotto `unittest discover` il modulo viene importato per intero e i test girano; ma chi
   lancia `python test_x.py` per controllare il suo lavoro vede un verde che non copre
   quelle classi. Trovato in tre file veri: `test_trasparenza_costi` (5 test di
   trasparenza sui costi), `test_geocoder_mappa` (3 classi) e `test_marca_temporale_server`
   (la prova che il giro giornaliero della marca e' indipendente).

2. TEST SENZA NESSUNA ASSERZIONE.
   Passano sempre. A volte e' voluto («non deve sollevare»), ma allora va detto con
   un'asserzione esplicita, altrimenti il giorno che la funzione smette di sollevare e
   torna un errore come valore il test resta verde.

3. TEST CHE SI SALTANO DA SOLI SU UNA CONDIZIONE INTERNA.
   `skipTest` dentro il corpo, deciso da qualcosa che il test stesso osserva, e' il modo
   piu' silenzioso di perdere un controllo: sparisce dal rapporto come «skipped» e nessuno
   lo legge piu'. E' successo davvero: quando il testo dei termini e' uscito dall'HTML per
   andare nel motore, la verifica della tariffa del 3% si e' auto-assolta e il controllo e'
   evaporato senza un solo rosso. Un salto per l'AMBIENTE (Postgres assente, Node assente)
   e' legittimo: dipende da fuori, non da cio' che si sta verificando.
"""

import ast
import io
import os
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))

# Salti legittimi: dipendono dall'AMBIENTE, non da cio' che il test dovrebbe verificare.
SALTI_AMBIENTALI = ("postgres", "node", "database_url", "rete", "network",
                    "non installato", "non raggiungibile", "legacy", "flask")


def _file_di_test():
    return sorted(n for n in os.listdir(QUI)
                  if n.startswith("test_") and n.endswith(".py"))


def _albero(nome):
    with io.open(os.path.join(QUI, nome), encoding="utf-8") as f:
        return ast.parse(f.read()), f


class TestNessunTestEInvisibile(unittest.TestCase):

    def test_nessuna_classe_dopo_unittest_main(self):
        colpevoli = []
        for nome in _file_di_test():
            try:
                with io.open(os.path.join(QUI, nome), encoding="utf-8") as f:
                    albero = ast.parse(f.read())
            except SyntaxError:
                continue
            riga_main = None
            for n in albero.body:
                if isinstance(n, ast.If) and "__main__" in ast.dump(n.test):
                    riga_main = n.lineno
            if riga_main is None:
                continue
            nascoste = [n.name for n in albero.body
                        if isinstance(n, ast.ClassDef) and n.lineno > riga_main]
            if nascoste:
                colpevoli.append("%s: unittest.main() a riga %d nasconde %s"
                                 % (nome, riga_main, nascoste))
        self.assertEqual(
            colpevoli, [],
            "Queste classi non girano se lanci il file da solo: `unittest.main()` sta "
            "sopra di loro e le esegue prima che esistano. Sposta il blocco "
            "`if __name__ == \"__main__\"` in fondo al file.\n  - "
            + "\n  - ".join(colpevoli))

    def test_il_controllo_riconoscerebbe_il_difetto(self):
        """Se il criterio smettesse di funzionare, questa guardia diventerebbe un
        ornamento senza che nessuno se ne accorga."""
        finto = ('import unittest\n'
                 'class A(unittest.TestCase):\n    def test_x(self): pass\n'
                 'if __name__ == "__main__":\n    unittest.main()\n'
                 'class B(unittest.TestCase):\n    def test_y(self): pass\n')
        albero = ast.parse(finto)
        riga_main = [n.lineno for n in albero.body
                     if isinstance(n, ast.If) and "__main__" in ast.dump(n.test)][0]
        nascoste = [n.name for n in albero.body
                    if isinstance(n, ast.ClassDef) and n.lineno > riga_main]
        self.assertEqual(nascoste, ["B"],
                         "il criterio non riconosce piu' una classe nascosta")


class TestNessunTestSiAssolveDaSolo(unittest.TestCase):

    def test_gli_skip_interni_sono_solo_per_l_ambiente(self):
        """Un `skipTest` deciso da cio' che il test dovrebbe verificare e' un controllo
        che si spegne da solo. Uno deciso dall'ambiente e' legittimo."""
        sospetti = []
        for nome in _file_di_test():
            if nome == os.path.basename(__file__):
                continue
            try:
                with io.open(os.path.join(QUI, nome), encoding="utf-8") as f:
                    testo = f.read()
                albero = ast.parse(testo)
            except SyntaxError:
                continue
            righe = testo.splitlines()
            for n in ast.walk(albero):
                if not (isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "skipTest"):
                    continue
                riga = righe[n.lineno - 1] if n.lineno <= len(righe) else ""
                motivo = riga.lower()
                if any(a in motivo for a in SALTI_AMBIENTALI):
                    continue
                sospetti.append("%s:%d  %s" % (nome, n.lineno, riga.strip()[:74]))
        self.assertEqual(
            sospetti, [],
            "Questi test si assolvono da soli per una condizione che riguarda cio' che "
            "dovrebbero verificare: spariscono dal rapporto come «skipped» e nessuno li "
            "legge piu'. Asserisci in ENTRAMBI i rami invece di saltare.\n  - "
            + "\n  - ".join(sospetti))


class TestOgniTestVerificaQualcosa(unittest.TestCase):

    # metodi che verificano l'ASSENZA di eccezione chiamando e basta: ammessi solo se
    # lo dicono in modo esplicito nel nome o nel commento
    CHIAMATE_DI_ASSERZIONE = ("assert", "fail", "assertRaises", "subTest")

    def test_nessun_metodo_di_test_e_completamente_muto(self):
        muti = []
        for nome in _file_di_test():
            try:
                with io.open(os.path.join(QUI, nome), encoding="utf-8") as f:
                    testo = f.read()
                albero = ast.parse(testo)
            except SyntaxError:
                continue
            for cls in [n for n in ast.walk(albero) if isinstance(n, ast.ClassDef)]:
                for fn in [n for n in cls.body
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and n.name.startswith("test")]:
                    corpo = ast.dump(fn)
                    if any(a in corpo for a in self.CHIAMATE_DI_ASSERZIONE):
                        continue
                    if "Raise" in corpo or "With" in corpo:
                        continue
                    # Un test puo' asserire dentro una funzione di appoggio
                    # (`self._verifica_identita(...)`): cercare "assert" solo nel suo
                    # corpo produceva DICIASSETTE falsi rossi. Un falso rosso insegna a
                    # ignorare lo strumento, e allora il rosso vero non lo guarda piu'
                    # nessuno. Qui resta muto solo cio' che non chiama NEMMENO un metodo
                    # dell'oggetto di test: quello non puo' verificare niente.
                    # Un test puo' verificare dentro una funzione di appoggio: sia un
                    # metodo dell'oggetto (`self._verifica_identita(...)`) sia una
                    # funzione di modulo che SOLLEVA (`_no_float(...)` alza
                    # AssertionError su un float). Cercare "assert" solo nel corpo dava
                    # diciassette falsi rossi, e un falso rosso insegna a ignorare lo
                    # strumento. Resta muto solo cio' che non chiama proprio NULLA:
                    # quello non puo' verificare niente in nessun modo.
                    if any(isinstance(x, ast.Call) for x in ast.walk(fn)):
                        continue
                    muti.append("%s: %s.%s" % (nome, cls.name, fn.name))
        self.assertEqual(
            muti, [],
            "Questi test non verificano nulla: passano sempre.\n  - " + "\n  - ".join(muti))


if __name__ == "__main__":
    unittest.main(verbosity=2)
