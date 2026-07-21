"""GUARDIA — il rimborso legacy e' CHIUSO e il motore legacy resta scollegato.

L'audit del 2026-07-22 (doppio-addebito) ha trovato che l'unico rimborso Stripe **senza
chiave di idempotenza** in tutto il codice era `StripeProvider.rimborsa` (fase35, motore
legacy 'Tavola VIP'): due chiamate concorrenti avrebbero potuto emettere **due rimborsi
veri**. Non era cablato nel prodotto vivo — ma «non cablato oggi» non e' una difesa: basta
un import di troppo domani. Quindi si e' fatto due cose:

  1. `rimborsa` non emette piu' alcun rimborso e non tocca Stripe (CHIUSO);
  2. si sorveglia che il motore legacy (fase34/35/36/41/49) **non venga mai importato** dal
     percorso vivo (main → bootstrap → server), cosi' non puo' rientrare in silenzio.

I rimborsi veri passano solo dal percorso centrale (fase111 calcolo + fase177 giornale),
che e' idempotente e allineato al motore.
"""

import io
import os
import re
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))

# I moduli del vecchio stack 'Tavola VIP', che non devono toccare il prodotto vivo.
LEGACY = ("fase34_prenotazioni", "fase35_pagamenti", "fase36_booking_api",
          "fase41_admin_panel", "fase49_ponte_booking")

# I file che formano il percorso VIVO (cio' che main avvia davvero).
PERCORSO_VIVO = ("main_casavip.py", "fase81_bootstrap_casavip.py", "fase83_server.py")


def _leggi(nome):
    with io.open(os.path.join(QUI, nome), encoding="utf-8") as f:
        return f.read()


class TestRimborsoLegacyChiuso(unittest.TestCase):

    def test_rimborsa_non_emette_piu_nulla(self):
        from fase35_pagamenti import StripeProvider, EsitoRimborso
        p = StripeProvider(api_key="sk_test_x")
        esito = p.rimborsa("pi_123", 10000)
        self.assertIsInstance(esito, EsitoRimborso)
        self.assertFalse(esito.ok,
                         "il rimborso legacy emette ancora un rimborso: doveva essere chiuso")

    def test_rimborsa_non_tocca_nemmeno_la_SDK_stripe(self):
        """Deve rifiutare PRIMA di chiamare `_stripe()`: la SDK esterna non e' installata
        (prodotto a zero dipendenze), quindi se la toccasse esploderebbe. Rifiutare senza
        toccarla e' la prova che il percorso e' davvero inerte."""
        from fase35_pagamenti import StripeProvider
        p = StripeProvider(api_key="sk_test_x")

        def _boom():
            raise AssertionError("rimborsa ha chiamato _stripe(): NON e' chiuso")

        p._stripe = _boom
        esito = p.rimborsa("pi_123", 10000)     # non deve sollevare
        self.assertFalse(esito.ok)

    def test_il_codice_e_marcato_CHIUSO(self):
        """Non basta che sia inerte: deve dirlo, o qualcuno lo 'ripristina' pensando sia
        un bug."""
        src = _leggi("fase35_pagamenti.py")
        self.assertIn("CHIUSO", src)
        self.assertNotIn("stripe.Refund.create", src,
                         "la chiamata di rimborso non-idempotente e' ancora nel codice")


class TestMotoreLegacyNonCablato(unittest.TestCase):
    """Il motore legacy non deve rientrare nel prodotto vivo da nessuna porta."""

    def test_il_percorso_vivo_non_importa_il_legacy(self):
        colpevoli = []
        for nome in PERCORSO_VIVO:
            src = _leggi(nome)
            # tolgo commenti e stringhe grezze per non inciampare in una citazione
            righe_codice = [r for r in src.splitlines()
                            if not r.lstrip().startswith("#")]
            corpo = "\n".join(righe_codice)
            for mod in LEGACY:
                if re.search(r"\bimport\s+%s\b" % mod, corpo) or \
                   re.search(r"\bfrom\s+%s\b" % mod, corpo):
                    colpevoli.append("%s importa %s" % (nome, mod))
        self.assertEqual(
            colpevoli, [],
            "il motore legacy 'Tavola VIP' e' rientrato nel percorso vivo: e' proprio la "
            "porta da cui il rimborso non-idempotente potrebbe tornare a muovere soldi.\n"
            "  - " + "\n  - ".join(colpevoli))

    def test_il_controllo_riconoscerebbe_un_import_legacy(self):
        """La regola madre applicata al criterio stesso."""
        finto = "from fase35_pagamenti import StripeProvider\n"
        self.assertTrue(re.search(r"\bfrom\s+fase35_pagamenti\b", finto),
                        "il criterio non riconosce piu' un import del legacy")


if __name__ == "__main__":
    unittest.main(verbosity=2)
