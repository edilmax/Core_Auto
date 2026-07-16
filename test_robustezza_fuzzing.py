"""
INDISTRUTTIBILITA': nessun endpoint deve CADERE su input malformato/ostile.

Bombarda ogni rotta /api con JSON rotto, tipi sbagliati, numeri enormi, injection, campi
mancanti, header falsi. Invarianti (devono valere SEMPRE):
  - ZERO eccezioni non gestite (il router non solleva MAI: un input sbagliato non manda giu'
    il worker).
  - ZERO risposte 500 (errore interno): un input ostile si respinge con 4xx (o 503 se un
    sottosistema e' davvero indisponibile), MAI con un crash.
Una macchina indistruttibile dice "no" con grazia, non si schianta.
"""
import json
import os
import re
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

_BIG = "9" * 400
_INJ = "<img src=x onerror=alert(1)>';DROP TABLE h;--"
_BODIES = [
    None, "", "non json{{{", "null", "[]", "12345", '{"a":',
    json.dumps({"x": _BIG}),
    json.dumps({"prezzo_cents": _BIG, "n": _BIG, "party": _BIG, "voto": _BIG}),
    json.dumps({"email": 123, "password": [], "slug": {}, "quote_token": 9, "voucher_token": None}),
    json.dumps({"totale_cents": -1, "n": -5, "check_in": "nondata", "check_out": "x", "party": -9}),
    json.dumps({"alloggio_id": _INJ, "citta": _INJ, "titolo": _INJ, "testo": _INJ, "ical": _INJ}),
    json.dumps([1, 2, 3]), json.dumps("stringa"),
]
_QUERIES = [
    {}, {"prezzo_cents": "abc"}, {"prezzo_cents": _BIG},
    {"alloggio": _INJ, "slug": _INJ, "citta": _INJ},
    {"lat_micro": "nan", "lon_micro": "inf", "raggio_km": _BIG},
    {"n": _BIG, "party": _BIG, "check_in": "x", "check_out": "y"}, {"e": _INJ},
]
_HEADERS = [{}, {"X-Host-Token": "rotto.non.firmato"}, {"X-Admin-Key": "xxx"},
            {"Stripe-Signature": "t=1,v1=deadbeef"}]


class TestRobustezzaFuzzing(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db", db_credito_usati=f"{d}/cu.db",
            db_messaggi=f"{d}/m.db", db_domanda=f"{d}/dom.db",
            stripe_webhook_secret="whsec_fuzz"))   # cosi' il webhook fa 400 (non 503) su firma rotta
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        qui = os.path.dirname(os.path.abspath(__file__))
        src = open(os.path.join(qui, "fase83_server.py"), encoding="utf-8").read()
        self.rotte = sorted(set(re.findall(r'"(/api/[a-z_/]+)"', src)))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_nessun_endpoint_cade_su_input_ostile(self):
        self.assertGreater(len(self.rotte), 50, "estrazione rotte fallita")
        eccezioni, cinquecento = [], []
        chiamate = 0
        for path in self.rotte:
            for metodo in ("GET", "POST"):
                for q in _QUERIES:
                    for b in _BODIES:
                        for h in _HEADERS:
                            chiamate += 1
                            try:
                                st, _ = self.r.gestisci(metodo, path, q, b, h)
                            except Exception as e:  # noqa: BLE001 — e' proprio cio' che cerchiamo
                                eccezioni.append((metodo, path, type(e).__name__, str(e)[:80],
                                                  str(b)[:40]))
                                continue
                            if isinstance(st, int) and st == 500:
                                cinquecento.append((metodo, path, str(b)[:40], str(q)[:40]))
        self.assertEqual(eccezioni, [],
                         "il router ha SOLLEVATO su input ostile (worker giu'): %s"
                         % eccezioni[:10])
        self.assertEqual(cinquecento, [],
                         "endpoint con 500 (crash interno) su input ostile: %s"
                         % cinquecento[:10])


if __name__ == "__main__":
    unittest.main(verbosity=2)
