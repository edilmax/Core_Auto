"""GUARDIA — il totale addebitato e' ESATTAMENTE la somma di quello che si mostra.

LA DOMANDA DEL FONDATORE (2026-07-21):
«la somma totale (prezzo alloggio + commissioni + tassa) deve coincidere al centesimo con
l'importo inviato a Stripe, senza errori di 1 centesimo o 1 yen per arrotondamento».

DOVE NASCONO GLI SCARTI, e perche' proprio qui.
Un preventivo non e' un numero: e' una decina di voci, e quasi tutte passano da una
percentuale — sconto soggiorno lungo, sconto non-rimborsabile, commissione, tariffa
tecnica, tassa di soggiorno per persona/notte. Ogni percentuale su interi obbliga a
scegliere dove cade il resto della divisione. Se due voci arrotondano ognuna per conto
proprio e poi si sommano, il totale puo' staccarsi di 1 dalla somma delle parti: e' il
classico "manca un centesimo" — invisibile su una prenotazione, sistematico su mille, e
in una direzione sola (o ci rimettiamo noi, o ci rimette l'host).

Su una valuta SENZA decimali il difetto e' piu' grande di cento volte: lo scarto minimo
non e' un centesimo di euro ma **un intero yen**.

COSA SI PRETENDE, e su una GRIGLIA di casi, non su un esempio fortunato:
  1. `totale_cents` == soggiorno + tassa, esatto;
  2. il prezzo ospite == listino meno TUTTI gli sconti dichiarati, esatto;
  3. il denaro si conserva: netto host + nostra commissione + costo carta == prezzo;
  4. cio' che arriva a Stripe == `totale_cents`, esatto, senza ricalcoli per strada;
  5. nessuna voce negativa, mai (uno sconto piu' grande del prezzo e' un regalo).
Tutto ripetuto in EUR (2 decimali) e in JPY (0), con importi scelti apposta perche' le
divisioni non tornino tonde.
"""

import json
import shutil
import tempfile
import unittest
import urllib.parse

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

CHIAMATE = []


def _fake_fetch(url, body, headers):
    import secrets
    CHIAMATE.append(body)
    return {"url": "https://t/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


def _importo_a_stripe():
    if not CHIAMATE:
        return None
    corpo = CHIAMATE[-1]
    if isinstance(corpo, bytes):
        corpo = corpo.decode("utf-8", "replace")
    p = dict(urllib.parse.parse_qsl(str(corpo)))
    v = p.get("line_items[0][price_data][unit_amount]")
    return int(v) if v is not None else None


# prezzi scelti perche' le percentuali NON diano numeri tondi
CASI = [
    # (valuta, prezzo/notte, tassa per persona-notte, notti, ospiti)
    ("EUR", 13337, 137, 3, 2),
    ("EUR", 9999, 0, 7, 3),      # 7 notti: scatta lo sconto settimanale
    ("EUR", 4567, 199, 8, 1),
    ("EUR", 100, 1, 2, 1),       # importi minimi: dove l'arrotondamento pesa di piu'
    ("JPY", 13337, 137, 3, 2),   # yen: lo scarto minimo e' 1 YEN intero
    ("JPY", 9999, 0, 7, 3),
    ("JPY", 18000, 200, 5, 2),
]


class TestIlTotaleTornaAlCentESIMO(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def _giro(self, valuta, prezzo, tassa, notti, ospiti):
        del CHIAMATE[:]
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        sistema = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"A" * 32, con_registrazione_host=True,
            db_catalogo="%s/c.db" % d, db_inventario="%s/i.db" % d,
            db_registro_host="%s/r.db" % d, db_accettazioni="%s/acc.db" % d,
            db_pendenti="%s/p.db" % d, db_payout="%s/pay.db" % d,
            db_garanzia="%s/g.db" % d, db_tassa_comunale="%s/t.db" % d,
            commissione_bps=1000, psp_bps=300, stripe_secret_key="sk"))
        r = crea_router(sistema, host_key="hk", admin_key="ak",
                        base_url="https://bookinvip.com")

        def g(m, p, b=None, h=None):
            return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

        st, c = g("POST", "/api/host/registrazione",
                  {"email": "h@arr.it", "password": "password1",
                   "accetta_termini": True, "accetta_clausole": True,
                   "accetta_privacy": True, "doc_sha256": doc_sha256(),
                   "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(st, 201, c)
        tok = c["token"]
        st, c = g("POST", "/api/host/pubblica",
                  {"slug": "a1", "titolo": "A", "citta": "Roma", "valuta": valuta,
                   "prezzo_notte_cents": prezzo, "capacita": 4,
                   "politica_cancellazione": "flessibile",
                   "tassa_soggiorno_cents": tassa,
                   "sconto_settimana_pct": 10, "sconto_mese_pct": 25},
                  {"X-Host-Token": tok})
        self.assertIn(st, (200, 201), c)
        g("POST", "/api/host/disponibilita_range",
          {"alloggio_id": "a1", "da": "2026-09-01", "a": "2026-09-30",
           "unita_totali": 1, "prezzo_netto_cents": prezzo}, {"X-Host-Token": tok})
        ci = "2026-09-05"
        co = "2026-09-%02d" % (5 + notti)
        st, q = g("POST", "/api/concierge/quote",
                  {"alloggio_id": "a1", "check_in": ci, "check_out": co,
                   "party": ospiti})
        self.assertEqual(st, 200, q)
        return g, q

    def _n(self, q, chiave):
        v = q.get(chiave, 0)
        return v if isinstance(v, int) and not isinstance(v, bool) else 0

    def test_il_totale_e_la_somma_delle_voci_mostrate(self):
        for valuta, prezzo, tassa, notti, ospiti in CASI:
            with self.subTest(valuta=valuta, prezzo=prezzo, notti=notti):
                _g, q = self._giro(valuta, prezzo, tassa, notti, ospiti)
                soggiorno = self._n(q, "prezzo_guest_cents")
                imposta = self._n(q, "tassa_soggiorno_cents")
                totale = self._n(q, "totale_cents") or soggiorno
                self.assertEqual(
                    totale, soggiorno + imposta,
                    "il totale non e' la somma delle voci: %d != %d + %d (scarto %d)"
                    % (totale, soggiorno, imposta, totale - soggiorno - imposta))

    def test_gli_sconti_tornano_esatti_sul_listino(self):
        for valuta, prezzo, tassa, notti, ospiti in CASI:
            with self.subTest(valuta=valuta, notti=notti):
                _g, q = self._giro(valuta, prezzo, tassa, notti, ospiti)
                listino = self._n(q, "prezzo_listino_cents")
                if not listino:
                    continue
                sconti = (self._n(q, "sconto_soggiorno_lungo_cents")
                          + self._n(q, "sconto_non_rimborsabile_cents")
                          + self._n(q, "sconto_credito_cents"))
                self.assertEqual(
                    self._n(q, "prezzo_guest_cents"), listino - sconti,
                    "listino %d meno sconti %d non fa il prezzo mostrato %d"
                    % (listino, sconti, self._n(q, "prezzo_guest_cents")))

    def test_il_denaro_si_conserva_fra_host_noi_e_carta(self):
        for valuta, prezzo, tassa, notti, ospiti in CASI:
            with self.subTest(valuta=valuta, notti=notti):
                _g, q = self._giro(valuta, prezzo, tassa, notti, ospiti)
                guest = self._n(q, "prezzo_guest_cents")
                netto = self._n(q, "netto_host_cents")
                comm = self._n(q, "commissione_cents")
                carta = self._n(q, "costo_pagamento_cents")
                self.assertEqual(
                    netto + comm + carta, guest,
                    "denaro creato o perso: host %d + noi %d + carta %d = %d, ma "
                    "l'ospite paga %d per il soggiorno (scarto %d)"
                    % (netto, comm, carta, netto + comm + carta, guest,
                       netto + comm + carta - guest))

    def test_a_stripe_arriva_ESATTAMENTE_il_totale(self):
        for valuta, prezzo, tassa, notti, ospiti in CASI:
            with self.subTest(valuta=valuta, notti=notti):
                g, q = self._giro(valuta, prezzo, tassa, notti, ospiti)
                atteso = self._n(q, "totale_cents") or self._n(q, "prezzo_guest_cents")
                st, b = g("POST", "/api/concierge/book",
                          {"quote_token": q["quote_token"], "email": "c@arr.it"})
                self.assertIn(st, (200, 201), b)
                addebitato = _importo_a_stripe()
                self.assertIsNotNone(addebitato, "nessuna chiamata a Stripe")
                self.assertEqual(
                    addebitato, atteso,
                    "mostrato %d, addebitato %d: scarto di %d %s per arrotondamento"
                    % (atteso, addebitato, addebitato - atteso, valuta))

    def test_nessuna_voce_e_negativa(self):
        """Uno sconto piu' grande del prezzo non e' uno sconto: e' un regalo."""
        for valuta, prezzo, tassa, notti, ospiti in CASI:
            with self.subTest(valuta=valuta, notti=notti):
                _g, q = self._giro(valuta, prezzo, tassa, notti, ospiti)
                for chiave in ("prezzo_guest_cents", "netto_host_cents",
                               "commissione_cents", "tassa_soggiorno_cents",
                               "totale_cents", "costo_pagamento_cents"):
                    self.assertGreaterEqual(self._n(q, chiave), 0,
                                            "%s negativo: %s" % (chiave, q.get(chiave)))

    def test_lo_yen_non_ha_MAI_frazioni(self):
        """Su una valuta senza decimali ogni voce dev'essere un intero di yen: una
        frazione qui vorrebbe dire che da qualche parte si e' diviso per cento."""
        for valuta, prezzo, tassa, notti, ospiti in CASI:
            if valuta != "JPY":
                continue
            with self.subTest(notti=notti):
                _g, q = self._giro(valuta, prezzo, tassa, notti, ospiti)
                for chiave, v in q.items():
                    if chiave.endswith("_cents"):
                        self.assertIsInstance(v, int, "%s non e' intero: %r" % (chiave, v))


if __name__ == "__main__":
    unittest.main(verbosity=2)
