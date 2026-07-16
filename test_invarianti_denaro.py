"""
INVARIANTI del denaro (coerenza "quello che diciamo == quello che fa la macchina").

Non scenari scelti a mano: input CASUALI (prezzi da 1 cent a €2500, 4 politiche, notti brevi/
lunghe, ospiti, crediti) contro il preventivo REALE (fase59 via router). Su OGNI preventivo
valido devono valere, SEMPRE, questi invarianti — se anche uno solo salta, e' un bug:

  I1 CONSERVAZIONE:  totale_cents == netto_host + (commissione - sconto_credito) + tassa + costo_pagamento
                     (nessun centesimo creato o perso lungo la pila sconti/tassa/costo carta)
  I2 0% OSPITE:      prezzo_guest_cents == totale_cents - tassa_soggiorno_cents
                     (l'ospite paga il pulito + la tassa pass-through, nessuna fee occulta)
  I3 MAI IN PERDITA: commissione_cents - sconto_credito_cents >= 0  (la nostra presa non va negativa)
  I4 NIENTE NEGATIVI: ogni voce denaro >= 0
  I5 CENTS INTERI:   ogni voce denaro e' int (money_unit = cents_integer, zero float)
"""
import datetime
import json
import random
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

_POLITICHE = ("flessibile", "moderata", "rigida", "non_rimborsabile")
_PREZZI = (1, 50, 999, 10000, 50000, 250000)
_VOCI = ("totale_cents", "netto_host_cents", "commissione_cents", "sconto_credito_cents",
         "tassa_soggiorno_cents", "costo_pagamento_cents", "prezzo_guest_cents")


class TestInvariantiDenaro(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db", db_credito_usati=f"{d}/cu.db",
            commissione_bps=1000, psp_bps=300))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@inv.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        self.listings = []
        for i in range(8):
            slug, prezzo = f"casa{i}", random.Random(i).choice(_PREZZI)
            pol = _POLITICHE[i % len(_POLITICHE)]
            self.g("POST", "/api/host/pubblica",
                   {"slug": slug, "titolo": f"C{i}", "citta": "Roma",
                    "prezzo_notte_cents": prezzo, "capacita": 8,
                    "politica_cancellazione": pol}, {"X-Host-Token": self.tok})
            self.g("POST", "/api/host/disponibilita_range",
                   {"alloggio_id": slug, "da": "2026-09-01", "a": "2027-02-28",
                    "unita_totali": 6, "prezzo_netto_cents": prezzo}, {"X-Host-Token": self.tok})
            self.listings.append(slug)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, metodo, path, body=None, headers=None):
        return self.r.gestisci(metodo, path, {},
                               json.dumps(body) if body is not None else None, headers or {})

    def _credito(self, rnd):
        import time
        return self.sys.firma.codifica({
            "tipo": "credito_fondatore", "email": "x@x.it", "citta": "roma",
            "credito_cents": rnd.choice([100, 500, 5000]),
            "exp": int(time.time()) + 30 * 86400, "nonce": str(rnd.random())})

    def test_invarianti_su_input_casuali(self):
        rnd = random.Random(2026)
        base = datetime.date(2026, 9, 1)
        validi = 0
        for _ in range(250):
            slug = rnd.choice(self.listings)
            off, notti = rnd.randint(0, 120), rnd.choice([1, 2, 3, 7, 14, 28, 40])
            ci = (base + datetime.timedelta(days=off)).isoformat()
            co = (base + datetime.timedelta(days=off + notti)).isoformat()
            body = {"alloggio_id": slug, "check_in": ci, "check_out": co,
                    "party": rnd.randint(1, 8)}
            if rnd.random() < 0.4:
                body["credito_token"] = self._credito(rnd)
            s, q = self.g("POST", "/api/concierge/quote", body)
            if s != 200:
                continue
            validi += 1
            v = {k: q[k] for k in _VOCI}
            ctx = f"{slug} {ci}->{co} party={body['party']} {v}"
            # I5 cents interi
            for k in _VOCI:
                self.assertIsInstance(v[k], int, f"I5 non-int {k}: {ctx}")
                self.assertNotIsInstance(v[k], bool, f"I5 bool {k}: {ctx}")
            # I1 conservazione
            self.assertEqual(
                v["totale_cents"],
                v["netto_host_cents"] + (v["commissione_cents"] - v["sconto_credito_cents"])
                + v["tassa_soggiorno_cents"] + v["costo_pagamento_cents"],
                f"I1 conservazione rotta: {ctx}")
            # I2 0% ospite
            self.assertEqual(v["prezzo_guest_cents"], v["totale_cents"] - v["tassa_soggiorno_cents"],
                             f"I2 fee occulta all'ospite: {ctx}")
            # I3 mai in perdita
            self.assertGreaterEqual(v["commissione_cents"] - v["sconto_credito_cents"], 0,
                                    f"I3 nostra presa negativa: {ctx}")
            # I4 niente negativi
            self.assertGreaterEqual(min(v.values()), 0, f"I4 voce negativa: {ctx}")
        self.assertGreater(validi, 100, "troppi pochi preventivi validi: setup rotto?")


if __name__ == "__main__":
    unittest.main(verbosity=2)
