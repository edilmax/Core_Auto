"""Test collaudo — i thread di fondo non devono poter morire in silenzio.

FRAGILITA' trovata in collaudo 2026-07-15 (NON un bug attivo): `_tick_hold` chiamava
`sweep_hold_una_passata` SENZA try/except nel ciclo, mentre gli altri due tick di fondo
(`_tick_garanzia`, `_tick_promemoria`) ce l'hanno. Oggi regge perche' la funzione si protegge
da sola, ma e' un'asimmetria pericolosa: se un domani una modifica solleva fuori dai try
interni, il thread (daemon: nessuno lo riavvia) MUORE IN SILENZIO -> gli hold non scadono piu'
-> le stanze restano bloccate PER SEMPRE mentre il sito sembra funzionare.

E' il guasto peggiore possibile per il money-path: invisibile. Nessun errore, nessun 500,
nessun alert: semplicemente le date non si liberano mai piu'.
"""
from __future__ import annotations

import re
import unittest

import fase83_server


class TestThreadSopravvivenza(unittest.TestCase):

    def setUp(self):
        with open(fase83_server.__file__, encoding="utf-8") as f:
            self.src = f.read()

    def _corpo_tick(self, nome):
        m = re.search(r"def %s\(\):(.+?)\n        _th" % nome, self.src, re.S)
        if m is None:                       # ultimo tick del blocco: prendi fino allo start()
            m = re.search(r"def %s\(\):(.+?)start\(\)" % nome, self.src, re.S)
        self.assertIsNotNone(m, "tick %s non trovato: struttura cambiata" % nome)
        return m.group(1)

    def test_ogni_tick_ha_try_nel_ciclo(self):
        """Un'eccezione non catturata dentro `while True` uccide il thread per sempre."""
        for nome in ("_tick_garanzia", "_tick_hold", "_tick_promemoria"):
            corpo = self._corpo_tick(nome)
            self.assertIn("while True:", corpo, "%s: non e' un ciclo?" % nome)
            self.assertIn("try:", corpo,
                          "%s: nessun try nel ciclo -> il thread puo' morire in silenzio" % nome)
            self.assertIn("except Exception", corpo,
                          "%s: deve catturare qualsiasi eccezione, non solo alcune" % nome)

    def test_lo_sweep_hold_e_isolato(self):
        """Il giro puo' fallire, ma il thread deve restare vivo per il giro dopo."""
        corpo = self._corpo_tick("_tick_hold")
        i_try, i_sleep = corpo.index("try:"), corpo.index("sleep(120)")
        self.assertLess(i_try, i_sleep, "il try deve avvolgere la passata, non lo sleep")
        self.assertIn("sweep_hold_una_passata", corpo)
        self.assertNotIn("raise", corpo, "_tick_hold non deve ri-sollevare: ucciderebbe il thread")

    def test_lo_sweep_si_protegge_anche_da_solo(self):
        """Difesa in profondita': la funzione NON deve dipendere dal try del chiamante."""
        m = re.search(r"def sweep_hold_una_passata\(.*?\n(?=\ndef |\nclass )", self.src, re.S)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(m.group(0).count("try:"), 2,
                                "sweep_hold_una_passata deve isolare i propri errori")


if __name__ == "__main__":
    unittest.main()
