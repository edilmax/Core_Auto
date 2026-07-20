"""
COERENZA della trasparenza commissionale (fase69 via /api/trasparenza).

BUG provato 2026-07-16: la trasparenza — "l'arma che converte l'host" — mostrava un 10% FISSO,
ignorando sia la commissione configurata sia la rampa di lancio. Due incoerenze:
  - COMMISSIONE_BPS=1500 (15%) -> mostrava 10% (SOTTO-stima: l'host crede di tenere di piu').
  - promo di lancio attiva + host nuovo (paga 0%) -> mostrava 10% (undercuta la strategia 0%).
Fix: la commissione mostrata riflette quella REALE (config, o rampa per l'host loggato).
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256


def _sistema(bps, promo):
    d = tempfile.mkdtemp()
    s = crea_sistema(ConfigCasaVIP(
        abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
        db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
        db_accettazioni=f"{d}/a.db", commissione_bps=bps, promo_lancio_attiva=promo))
    return d, s, crea_router(s, host_key="hk", base_url="https://bookinvip.com")


def _comm_mostrata(r, headers=None):
    s, c = r.gestisci("GET", "/api/trasparenza",
                      {"prezzo_cents": "10000", "ota": "booking"}, None, headers or {})
    return s, c["scenario_nostro"]["commissione_cents"]


class TestTrasparenzaCoerente(unittest.TestCase):
    def test_riflette_la_config(self):
        # COMMISSIONE_BPS=15% (promo off) -> la trasparenza deve dire 15% su 10000 = 1500
        d, s, r = _sistema(1500, False)
        try:
            st, comm = _comm_mostrata(r)
            self.assertEqual(st, 200)
            self.assertEqual(comm, 1500, "trasparenza sotto/ sovra-stima vs la commissione configurata")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_default_10_percento(self):
        # nessuna regressione: default 10% promo off -> 1000
        d, s, r = _sistema(1000, False)
        try:
            _, comm = _comm_mostrata(r)
            self.assertEqual(comm, 1000)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_rampa_lancio_host_nuovo_zero(self):
        # promo attiva + host NUOVO (anzianita' 0 -> rampa 0%) -> la trasparenza deve dire 0
        d, s, r = _sistema(1000, True)
        try:
            st, c = r.gestisci("POST", "/api/host/registrazione", {}, json.dumps({
                "email": "h@x.it", "password": "password1", "accetta_termini": True,
                "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                "versione": CONTRATTO_HOST_VERSIONE}), {})
            self.assertEqual(st, 201, c)
            tok = c["token"]
            _, comm = _comm_mostrata(r, {"X-Host-Token": tok})
            self.assertEqual(comm, 0, "in lancio l'host paga 0% ma la trasparenza mostrava 10%")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_promo_generico_senza_host_regime(self):
        # promo attiva, nessun host loggato -> tariffa a regime della rampa (10%), non config
        d, s, r = _sistema(1500, True)
        try:
            _, comm = _comm_mostrata(r)
            self.assertEqual(comm, 1000, "generico in promo = regime rampa 10% (config ignorata dalla rampa)")
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
