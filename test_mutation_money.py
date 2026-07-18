# -*- coding: utf-8 -*-
"""SISTEMA ⑨ — MUTATION TESTING mirato sul MONEY-PATH.

I test verdi dicono "il codice fa cio' che mi aspetto". Il mutation testing chiede
l'altra meta': "se ROMPO di proposito una riga critica dei soldi, c'e' un test che se
ne accorge?". Un mutante che SOPRAVVIVE = una riga di denaro NON coperta = falla.

Metodo (chirurgico, non a tappeto per non bruciare token/tempo): per ogni mutante
prendo UNA riga del money-path, la storpio con una modifica plausibile-ma-sbagliata
(split escrow invertito, whitelist stato allentata, filtro tombstone tolto, sconto
girato, clamp del rimborso rimosso...), e lancio SOLO i test-killer designati. Il
mutante e' "ucciso" se almeno un killer diventa ROSSO; se resta verde, e' un BUCO.
Ogni mutante ripristina il file (anche se il killer va in errore): niente residui.

Idempotente e sicuro: opera su una COPIA in memoria del sorgente e la riscrive; alla
fine il file torna byte-identico (verificato con hash).
"""
import hashlib
import os
import subprocess
import sys
import unittest

RADICE = os.path.dirname(os.path.abspath(__file__))

# (etichetta, file, testo_da_trovare, testo_mutato, [moduli-killer])
MUTANTI = [
    ("escrow: split host/ospite INVERTITO",
     "fase160_escrow_garanzia.py",
     "host=imp - rimb, rimborso=rimb",
     "host=rimb, rimborso=imp - rimb",
     ["test_fase160_escrow_garanzia"]),

    ("hold: whitelist stato ALLENTATA (accetta qualsiasi stato)",
     "fase162_pagamenti_pendenti.py",
     'if r["stato"] not in ("in_attesa", "scaduto"):',
     'if r["stato"] not in ("in_attesa", "scaduto", "pagato", "cancellato", "rimborsato"):',
     ["test_race_hold_conferma", "test_cancellazione_money"]),

    ("concierge: netto host = netto + comm invece di - comm (host gonfiato)",
     "fase59_concierge.py",
     "netto_host = netto - comm",
     "netto_host = netto + comm",
     ["test_conservazione_denaro"]),

    ("rimborso: clamp min() sull'importo RIMOSSO (rimborso > escrow)",
     "fase160_escrow_garanzia.py",
     "rimb = min(_cent(rimborso_ospite_cents), imp)",
     "rimb = _cent(rimborso_ospite_cents)",
     ["test_fase160_escrow_garanzia"]),
]


def _hash(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _lancia(moduli):
    """True se ALMENO un test fallisce/errore (mutante ucciso)."""
    r = subprocess.run([sys.executable, "-m", "unittest"] + moduli,
                       cwd=RADICE, capture_output=True, text=True, timeout=300)
    return r.returncode != 0


class TestMutationMoney(unittest.TestCase):
    def test_ogni_mutante_viene_ucciso(self):
        sopravvissuti = []
        for etichetta, nomefile, trova, muta, killer in MUTANTI:
            percorso = os.path.join(RADICE, nomefile)
            # I/O BINARIO: preserva i byte esatti (i fine-riga LF/CRLF non devono
            # cambiare, o il ripristino sporcherebbe il file e falserebbe il test)
            with open(percorso, "rb") as f:
                originale = f.read()
            btrova, bmuta = trova.encode("utf-8"), muta.encode("utf-8")
            self.assertEqual(originale.count(btrova), 1,
                             "%s: ancora mutazione non UNICA in %s (%d)"
                             % (etichetta, nomefile, originale.count(btrova)))
            h0 = _hash(percorso)
            ucciso = False
            try:
                with open(percorso, "wb") as f:
                    f.write(originale.replace(btrova, bmuta, 1))
                ucciso = _lancia(killer)
            finally:
                with open(percorso, "wb") as f:
                    f.write(originale)
            self.assertEqual(_hash(percorso), h0,
                             "%s: file NON ripristinato!" % nomefile)
            print(("UCCISO  " if ucciso else "SOPRAV. ") + etichetta
                  + "  [killer: " + ", ".join(killer) + "]")
            if not ucciso:
                sopravvissuti.append(etichetta)
        self.assertEqual(sopravvissuti, [],
                         "MUTANTI SOPRAVVISSUTI (money-path scoperto): "
                         + "; ".join(sopravvissuti))


if __name__ == "__main__":
    unittest.main(verbosity=2)
