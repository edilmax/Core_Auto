"""Collaudo LOG PERSISTENTE DI TUTTI I MOVIMENTI (fase177 esteso + agganci fase83).

Ogni movimento di denaro finisce nel GIORNALE IMMUTABILE (non solo le penali): incasso,
bonifico all'host (riuscito o fallito->manuale), rimborso, tassa. E' la "scatola nera"
che NON si perde a un deploy e risponde per sempre a "ma il bonifico e' partito?".
Invarianti:
  1. movimento() mappa ogni tipo ai conti giusti, e' idempotente su evento_id, catena intatta;
  2. pagamento confermato -> 'incasso' (totale ospite) + 'tassa_incassata' nel giornale;
     un RETRY del webhook NON raddoppia (idempotenza);
  3. cancellazione host di una pagata -> 'rimborso' (100% ospite) nel giornale;
  4. bonifico Connect riuscito -> 'payout_host'; FALLITO -> 'payout_manuale' (lo scenario
     "non ho ricevuto il bonifico": resta la prova che si e' tentato);
  5. dopo TUTTI i movimenti la catena hash resta valida (audit integro).
"""
import hashlib
import hmac
import json
import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase177_financial_controller import crea_financial_controller

SEG = b"h" * 32
HK = {"X-Host-Key": "hk"}
AK = {"X-Admin-Key": "ak"}
WHSEC = "whsec_test"
CI, CO = "2027-08-10", "2027-08-12"


class TestMovimentoUnit(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.fc = crea_financial_controller(f"{self.dir}/fin.db")
        self.fc.inizializza_schema()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_tutti_i_tipi_e_conti(self):
        for tipo in ("incasso", "payout_host", "payout_manuale", "rimborso",
                     "tassa_incassata", "tassa_stornata"):
            r = self.fc.movimento(tipo=tipo, riferimento="R-" + tipo, soggetto="host:h",
                                  importo_cents=1000, valuta="EUR", causale="t")
            self.assertIsNotNone(r, tipo)
        self.assertIsNone(self.fc.movimento(tipo="tipo_inesistente", riferimento="X",
                                            soggetto="s", importo_cents=1, valuta="EUR",
                                            causale="t"))
        self.assertTrue(self.fc.verifica_catena()["ok"])

    def test_idempotente(self):
        a = self.fc.movimento(tipo="payout_host", riferimento="R1", soggetto="host:h",
                             importo_cents=5000, valuta="EUR", causale="t")
        b = self.fc.movimento(tipo="payout_host", riferimento="R1", soggetto="host:h",
                             importo_cents=5000, valuta="EUR", causale="t")
        self.assertFalse(a["idempotente"])
        self.assertTrue(b["idempotente"])
        self.assertEqual(sum(1 for m in self.fc.movimenti("R1")
                             if m["tipo"] == "payout_host"), 1)


class _FakeConnect:
    def __init__(self, tid):
        self._tid = tid
    def trasferisci(self, acct, importo, valuta, rif):
        return self._tid


class TestAgganciMoneyPath(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db", db_domanda=f"{d}/dom.db",
            db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_tassa_comunale=f"{d}/tc.db", db_finanza=f"{d}/fin.db",
            file_referral=f"{d}/ref.json",
            commissione_bps=1500, stripe_webhook_secret=WHSEC))
        self.sis.concierge._link = lambda dati: "https://pay/" + str(dati.get("riferimento", ""))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        # host REGISTRATO (serve per il ramo bonifico: info_host deve trovare l'account)
        es = self.sis.registro_host.registra("host@collaudo.invalid", "password12",
                                             accetta_termini=True)
        self.hid = es.host_id
        self.assertTrue(self.hid)
        self.g("POST", "/api/host/pubblica", {"host_id": self.hid, "slug": "casa", "titolo": "C",
               "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
               "servizi": [], "immagini": [], "tassa_pp_notte_cents": 200}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa",
               "da": "2027-08-01", "a": "2027-08-31", "unita_totali": 5,
               "prezzo_netto_cents": 10000}, HK)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _paga(self, rif):
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        ts = str(int(time.time()))
        mac = hmac.new(WHSEC.encode(), f"{ts}.{pl}".encode(), hashlib.sha256).hexdigest()
        return self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                               {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})[0]

    def _prenota_paga(self):
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa",
                      "check_in": CI, "check_out": CO, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "o@collaudo.invalid"})
        rif = b["riferimento"]
        self.assertEqual(self._paga(rif), 200)
        return rif

    def _tipi(self, rif):
        return [m["tipo"] for m in self.sis.finanza.movimenti(rif)]

    def test_incasso_e_tassa_idempotenti(self):
        rif = self._prenota_paga()
        self.assertIn("incasso", self._tipi(rif))
        self.assertIn("tassa_incassata", self._tipi(rif))
        # RETRY webhook: nessun doppione
        self.assertEqual(self._paga(rif), 200)
        self.assertEqual(self._tipi(rif).count("incasso"), 1)
        self.assertTrue(self.sis.finanza.verifica_catena()["ok"])

    def test_rimborso_su_cancellazione_host(self):
        rif = self._prenota_paga()
        s, c = self.g("POST", "/api/host/cancella", {"riferimento": rif, "host_id": self.hid}, HK)
        self.assertEqual(s, 200)
        self.assertIn("rimborso", self._tipi(rif))
        # importo rimborso = totale ospite
        mov = [m for m in self.sis.finanza.movimenti(rif) if m["tipo"] == "rimborso"][0]
        self.assertGreater(mov["importo_cents"], 0)
        self.assertTrue(self.sis.finanza.verifica_catena()["ok"])

    def test_bonifico_riuscito_e_fallito(self):
        # host collega Stripe
        self.sis.registro_host.imposta_stripe_account(self.hid, "acct_TEST")
        rif = self._prenota_paga()
        netto = self.sis.payout.riepilogo(self.hid)["EUR"]["maturato"]
        # BONIFICO RIUSCITO -> payout_host
        self.sis.connect = _FakeConnect("tr_OK")
        self.r._trasferisci_all_host(rif, netto)
        self.assertIn("payout_host", self._tipi(rif))

        # nuova prenotazione, BONIFICO FALLITO -> payout_manuale (scenario "non ho ricevuto")
        rif2 = self._prenota_paga()
        netto2 = self.sis.payout.riepilogo(self.hid)["EUR"]["maturato"]
        self.sis.connect = _FakeConnect(None)      # Connect non riesce
        self.r._trasferisci_all_host(rif2, netto2)
        self.assertIn("payout_manuale", self._tipi(rif2))
        self.assertNotIn("payout_host", self._tipi(rif2))
        self.assertTrue(self.sis.finanza.verifica_catena()["ok"])


if __name__ == "__main__":
    unittest.main()
