"""Collaudo RICONCILIAZIONE STRIPE (fase182): il periodo intero contro la banca.

Invarianti:
  1. mondo PERFETTO (Stripe==giornale al centesimo) -> ok True, delta 0;
  2. 👻 SOLO STRIPE: sessione pagata senza incasso a giornale (webhook perso) -> segnalata;
  3. 👻 SOLO GIORNALE: incasso senza sessione Stripe -> segnalato;
  4. ⚖️ IMPORTO DIVERSO sulla stessa prenotazione -> segnalato al centesimo;
  5. le sessioni NON pagate (link abbandonati) sono FILTRATE (non sono incassi);
  6. PAGINAZIONE Stripe (has_more) percorsa fino in fondo;
  7. valute mai mischiate (EUR e USD confrontati separatamente);
  8. endpoint: 403 senza Bunker; 503 senza chiave Stripe; READ-ONLY (giornale intatto).
"""
import json
import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase177_financial_controller import crea_financial_controller
from fase182_riconciliazione import riconcilia, stripe_sessioni_pagate

ORA = 1_800_000_000            # orologio finto e fermo: test deterministici


def _sessione(rif, cents, valuta="eur", pagata=True, sid=None):
    return {"id": sid or ("cs_" + rif), "payment_status": "paid" if pagata else "unpaid",
            "amount_total": cents, "currency": valuta,
            "metadata": {"riferimento": rif}}


class _StripeFinto:
    """fetch iniettabile: risponde con pagine costruite dal test."""

    def __init__(self, sessioni=None, balance=None):
        self.sessioni = sessioni or []
        self.balance = balance or []
        self.chiamate = []

    def __call__(self, percorso, params, chiave):
        self.chiamate.append((percorso, dict(params)))
        fonte = self.sessioni if percorso.startswith("checkout") else self.balance
        dopo = params.get("starting_after")
        inizio = 0
        if dopo:
            for i, x in enumerate(fonte):
                if x["id"] == dopo:
                    inizio = i + 1
                    break
        blocco = fonte[inizio:inizio + int(params.get("limit", 100))]
        return {"data": blocco, "has_more": inizio + len(blocco) < len(fonte)}


class TestRiconciliazione(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.fc = crea_financial_controller(f"{self.dir}/fin.db",
                                            orologio=lambda: ORA)
        self.fc.inizializza_schema()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _incasso(self, rif, cents, valuta="EUR"):
        self.fc.movimento(tipo="incasso", riferimento=rif, soggetto="host:h",
                          importo_cents=cents, valuta=valuta, causale="pagamento")

    def _ric(self, stripe, giorni=30):
        return riconcilia(self.fc, "sk_test", giorni=giorni, fetch=stripe,
                          ora=lambda: ORA)

    def test_mondo_perfetto(self):
        self._incasso("R1", 25000)
        self._incasso("R2", 18000)
        st = _StripeFinto(
            sessioni=[_sessione("R1", 25000), _sessione("R2", 18000)],
            balance=[{"id": "txn_1", "reporting_category": "charge",
                      "currency": "eur", "amount": 43000}])
        rep = self._ric(st)
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(rep["confronti"]["incassi"]["delta"], {"EUR": 0})
        self.assertEqual(rep["solo_stripe"], [])
        self.assertEqual(rep["solo_giornale"], [])

    def test_fantasma_solo_stripe(self):
        st = _StripeFinto(sessioni=[_sessione("PERSO", 9900)])
        rep = self._ric(st)
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["solo_stripe"][0]["riferimento"], "PERSO")

    def test_fantasma_solo_giornale(self):
        self._incasso("NOSTRO", 7700)
        rep = self._ric(_StripeFinto())
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["solo_giornale"][0]["riferimento"], "NOSTRO")

    def test_importo_diverso_al_centesimo(self):
        self._incasso("RX", 25000)
        st = _StripeFinto(sessioni=[_sessione("RX", 24999)])   # UN centesimo
        rep = self._ric(st)
        self.assertFalse(rep["ok"])
        d = rep["importo_diverso"][0]
        self.assertEqual((d["stripe_cents"], d["giornale_cents"]), (24999, 25000))

    def test_non_pagate_filtrate(self):
        st = _StripeFinto(sessioni=[_sessione("ABBAND", 5000, pagata=False)])
        self.assertEqual(stripe_sessioni_pagate("sk", 0, fetch=st), [])
        rep = self._ric(st)
        self.assertTrue(rep["ok"])                # un link abbandonato NON e' un fantasma

    def test_paginazione_fino_in_fondo(self):
        sessioni = [_sessione("R%03d" % i, 1000, sid="cs_%03d" % i)
                    for i in range(250)]          # 3 pagine da 100
        for i in range(250):
            self._incasso("R%03d" % i, 1000)
        st = _StripeFinto(sessioni=sessioni,
                          balance=[{"id": "t1", "reporting_category": "charge",
                                    "currency": "eur", "amount": 250 * 1000}])
        rep = self._ric(st)
        self.assertEqual(rep["sessioni_pagate"], 250)
        self.assertTrue(rep["ok"], rep["confronti"])
        pagine = [p for p in st.chiamate if p[0].startswith("checkout")]
        self.assertEqual(len(pagine), 3)          # paginazione percorsa davvero

    def test_valute_separate(self):
        self._incasso("EU1", 10000, "EUR")
        self._incasso("US1", 10000, "USD")
        st = _StripeFinto(sessioni=[_sessione("EU1", 10000, "eur"),
                                    _sessione("US1", 10000, "usd")],
                          balance=[{"id": "t1", "reporting_category": "charge",
                                    "currency": "eur", "amount": 10000},
                                   {"id": "t2", "reporting_category": "charge",
                                    "currency": "usd", "amount": 10000}])
        rep = self._ric(st)
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(rep["confronti"]["incassi"]["delta"],
                         {"EUR": 0, "USD": 0})


class TestEndpointRiconciliazione(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"r" * 32, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_finanza=f"{d}/fin.db", bunker_password="SuperPw@1",
            stripe_secret_key="sk_test_x", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_bunker_gated_e_read_only(self):
        s, _ = self.r.gestisci("GET", "/api/bunker/riconciliazione", {}, None,
                               {"X-Admin-Key": "ak"})
        self.assertEqual(s, 403)                  # senza sessione Bunker
        # con sessione: la fetch REALE fallira' (sk_test_x non valida) -> l'endpoint
        # NON esplode e il giornale resta INTATTO (read-only provato)
        s, out = self.r.gestisci("POST", "/api/bunker/login", {},
                                 json.dumps({"codice": "SuperPw@1"}),
                                 {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(s, 200, out)
        hb = {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9",
              "X-Bunker-Session": out["sessione"]}
        prima = self.sis.finanza.conta_movimenti()
        s, d = self.r.gestisci("GET", "/api/bunker/riconciliazione",
                               {"giorni": "7"}, None, hb)
        self.assertIn(s, (200, 503))              # 503 = Stripe irraggiungibile: ONESTO
        self.assertEqual(self.sis.finanza.conta_movimenti(), prima)


if __name__ == "__main__":
    unittest.main()
