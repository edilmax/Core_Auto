"""
Guardia UI pannelli (statica, zero browser): ogni helper JS USATO in una pagina
deve essere DEFINITO nella stessa pagina (le pagine deploy/*.html sono
self-contained: un solo <script> inline, nessun include condiviso).

Bug #34 (provato staticamente): host.html chiamava money() — definita SOLO in
admin.html/index.html (copia-incolla cross-pagina) — dentro il handler del
bottone "💶 Prezzi": ReferenceError alla prima cella con prezzo, calendario
prezzi MORTO nel browser mentre la suite era verde (gap #1: niente E2E).
"""
import os
import re
import unittest

BASE = os.path.dirname(os.path.abspath(__file__))
PAGINE = ("host.html", "index.html", "admin.html")
HELPERS = ("money", "fmt", "valExp", "valSym", "toCents")


def _testo(pagina):
    with open(os.path.join(BASE, "deploy", pagina), encoding="utf-8") as f:
        return f.read()


class TestHelperDefinitiPerPagina(unittest.TestCase):
    def test_helper_usati_sono_definiti_nella_stessa_pagina(self):
        for pagina in PAGINE:
            t = _testo(pagina)
            for nome in HELPERS:
                tutti = len(re.findall(r"(?<![\w.$])%s\(" % nome, t))
                defs = len(re.findall(r"function\s+%s\(" % nome, t)) + \
                    len(re.findall(r"(?:const|let|var)\s+%s\s*=" % nome, t))
                chiamate = tutti - len(re.findall(r"function\s+%s\(" % nome, t))
                if chiamate > 0:
                    self.assertGreater(
                        defs, 0,
                        "%s: %s() usato %d volte ma MAI definito in pagina "
                        "(classe bug #34)" % (pagina, nome, chiamate))

    def test_host_niente_money(self):
        """host.html usa fmt() (sua, per-valuta): money() non deve riapparire."""
        self.assertNotIn("money(", _testo("host.html"))

    def test_host_calendario_prezzi_gestisce_chiuso(self):
        """La vista prezzi colora anche lo stato 'chiuso' (emesso da fase119).

        2026-07-18 (semaforo universale): il controllo per-stringa `c.stato==='chiuso'`
        e' stato sostituito dalla mappa UNICA `SEMAFORO`, che DEVE coprire il dialetto
        di fase119 (prenotato/venduto/chiuso) e la vista prezzi DEVE usarla."""
        t = _testo("host.html")
        i = t.index("const SEMAFORO")
        mappa = t[i:i + 220]
        for stato in ("chiuso:", "prenotato:", "venduto:"):
            self.assertIn(stato, mappa, "SEMAFORO non copre lo stato %s" % stato)
        # la vista prezzi consulta la mappa (non piu' if per-stringa)
        self.assertIn("SEMAFORO[c.stato]", t)


if __name__ == "__main__":
    unittest.main(verbosity=2)
