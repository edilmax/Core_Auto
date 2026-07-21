"""GUARDIA — dove finisce chi ha appena pagato deve ESISTERE.

IL DIFETTO CHE HA FATTO NASCERE QUESTA GUARDIA (2026-07-21).
Le due strade di pagamento vive scrivevano in chiaro un indirizzo di ripiego, usato
quando la configurazione non ne fornisce uno. Tutti e quattro portavano a pagine
**inesistenti**:

    fase85_pagamenti_stripe.py   ->  /ok          404
                                     /ko          404
    fase101_stripe_connect.py    ->  /grazie      404   (mancava il `.html`)
                                     /annullato   404

Le pagine vere sono `grazie.html` e `annullato.html`.

**Perche' nessuno se n'era accorto.** In produzione `STRIPE_SUCCESS_URL` e
`STRIPE_CANCEL_URL` sono impostate, quindi il ripiego non entra mai in gioco: il giro
funziona **per configurazione, non per costruzione**. Basta un deploy senza quelle due
variabili — un `.env` rigenerato, una macchina nuova, un errore di battitura — e ogni
cliente che paga viene rimandato su una pagina che non esiste **subito dopo l'addebito**.
Con Stripe in modalita' LIVE quelli sono soldi veri gia' prelevati, e un cliente senza
conferma a schermo e' il caso da manuale della contestazione sulla carta.

Nessun collaudo poteva vederlo: guardavano cosa fa il codice, non **dove porta un
indirizzo**. E' la stessa famiglia dei difetti che il fondatore ha trovato a occhio.

COSA PRETENDE.
Ogni indirizzo del nostro dominio scritto in chiaro nel codice del pagamento deve
corrispondere a un file che esiste davvero in `deploy/`.
"""

import io
import os
import re
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
PAGINE = os.path.join(QUI, "deploy")

# I moduli che possono rimandare un utente da qualche parte dopo un pagamento.
MODULI_PAGAMENTO = ("fase85_pagamenti_stripe.py", "fase101_stripe_connect.py")

# Percorsi serviti dal programma, non da un file in deploy/ (non sono pagine statiche).
SERVITI_DAL_SERVER = ("/api/", "/ricevuta/", "/recensione/", "/annuncio/", "/entra-")


def _leggi(nome):
    with io.open(os.path.join(QUI, nome), encoding="utf-8") as f:
        return f.read()


def _indirizzi_nostri(testo):
    """Ogni URL bookinvip.com scritto in chiaro, col suo percorso."""
    return re.findall(r"https://bookinvip\.com(/[A-Za-z0-9._/-]*)", testo)


class TestIndirizziDiRitorno(unittest.TestCase):

    def test_ci_sono_indirizzi_da_controllare(self):
        trovati = []
        for modulo in MODULI_PAGAMENTO:
            trovati += _indirizzi_nostri(_leggi(modulo))
        self.assertGreaterEqual(len(trovati), 4,
                                "non trovo piu' gli indirizzi di ripiego: la guardia "
                                "starebbe controllando il vuoto")

    def test_ogni_ripiego_porta_a_una_pagina_che_esiste(self):
        morti = []
        for modulo in MODULI_PAGAMENTO:
            for percorso in _indirizzi_nostri(_leggi(modulo)):
                if percorso in ("/", "") or percorso.startswith(SERVITI_DAL_SERVER):
                    continue
                nome = percorso.lstrip("/")
                if not os.path.exists(os.path.join(PAGINE, nome)):
                    morti.append("%s -> https://bookinvip.com%s" % (modulo, percorso))
        self.assertEqual(
            morti, [],
            "Questi indirizzi porterebbero chi ha appena PAGATO su una pagina che non "
            "esiste (404). In produzione oggi non si vede perche' STRIPE_SUCCESS_URL e "
            "STRIPE_CANCEL_URL sono impostate: il giro regge per configurazione, non "
            "per costruzione.\n  - " + "\n  - ".join(morti))

    def test_il_ripiego_e_proprio_la_pagina_di_esito(self):
        """Non basta che esista: dev'essere la pagina giusta per quell'esito."""
        for modulo in MODULI_PAGAMENTO:
            testo = _leggi(modulo)
            ok = re.search(r"success_url[^\n]*bookinvip\.com(/[A-Za-z0-9._-]*)", testo)
            ko = re.search(r"cancel_url[^\n]*bookinvip\.com(/[A-Za-z0-9._-]*)", testo)
            self.assertIsNotNone(ok, "%s: nessun ripiego per il pagamento riuscito" % modulo)
            self.assertIsNotNone(ko, "%s: nessun ripiego per il pagamento annullato" % modulo)
            self.assertEqual(ok.group(1), "/grazie.html",
                             "%s manda chi ha pagato su %s" % (modulo, ok.group(1)))
            self.assertEqual(ko.group(1), "/annullato.html",
                             "%s manda chi ha annullato su %s" % (modulo, ko.group(1)))

    def test_le_due_pagine_di_esito_esistono_davvero(self):
        for nome in ("grazie.html", "annullato.html"):
            self.assertTrue(os.path.exists(os.path.join(PAGINE, nome)),
                            "manca la pagina di esito %s: i ripieghi punterebbero nel "
                            "vuoto" % nome)


if __name__ == "__main__":
    unittest.main(verbosity=2)
