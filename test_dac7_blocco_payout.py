"""Collaudo INCREMENTO 6 — GOVERNANCE PAGAMENTI (DAC7 enforcement, blocco payout).

Il transfer automatico all'host viene FERMATO ("hold" DERIVATO: payout resta 'maturato',
mai perso, nessuno stato nuovo) SOLO se l'host è REPORTABILE per legge (>=30 pren O
>=2000 EUR/anno, anno corrente o precedente) E i dati fiscali sono incompleti.
Invarianti:
  1. host sopra soglia + dati mancanti -> transfer NON parte, payout resta 'maturato',
     nessuna riga payout_host nel giornale, log PAYOUT_HOLD_TRIGGERED;
  2. host SOTTO soglia (dati mancanti) -> paga normalmente (nessun obbligo, nessun blocco);
  3. host sopra soglia CON dati completi -> paga normalmente;
  4. SBLOCCO AUTOMATICO: l'host completa i dati dal pannello -> i payout in hold RIPARTONO
     subito (payout_riprovati>0, transfer eseguito, 'in_transito', payout_host nel giornale);
  5. GET /api/host/dac7_stato -> l'host VEDE l'avviso (bloccati + quanto è fermo + mancanti);
  6. conformità Bunker espone payout_fermi_cents per gli urgenti;
  7. kill-switch DAC7_BLOCCO_PAYOUT=0 -> mai bloccato;
  8. FAIL-OPEN: motore finanza assente -> mai bloccato (soldi dovuti > leva di conformità).
"""
import hashlib
import hmac
import json
import os
import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

SEG = b"h" * 32
HK = {"X-Host-Key": "hk"}
WHSEC = "whsec_test"
CI, CO = "2027-08-10", "2027-08-12"          # 2 notti x 100 EUR = 200 EUR (sotto soglia)


class _ConnectContatore:
    """Connect finto che CONTA i transfer (per provare che il blocco NON lo chiama)."""
    def __init__(self, tid="tr_OK"):
        self.tid = tid
        self.chiamate = []

    def trasferisci(self, acct, importo, valuta, rif):
        self.chiamate.append((acct, int(importo), valuta, str(rif)))
        return self.tid


class TestBloccoPayoutDAC7(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db", db_domanda=f"{d}/dom.db",
            db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_tassa_comunale=f"{d}/tc.db", db_finanza=f"{d}/fin.db",
            file_referral=f"{d}/ref.json",
            commissione_bps=1500, stripe_webhook_secret=WHSEC, bunker_password="SuperPw@1"))
        self.sis.concierge._link = lambda dati: "https://pay/" + str(dati.get("riferimento", ""))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        es = self.sis.registro_host.registra("dac7@collaudo.invalid", "password12",
                                             accetta_termini=True)
        self.hid = es.host_id
        self.sis.registro_host.imposta_stripe_account(self.hid, "acct_TEST")
        self.connect = _ConnectContatore()
        self.sis.connect = self.connect
        self.g("POST", "/api/host/pubblica", {"host_id": self.hid, "slug": "casa",
               "titolo": "C", "citta": "Roma", "descrizione": "x",
               "prezzo_notte_cents": 10000, "capacita": 2, "servizi": [], "immagini": []}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa",
               "da": "2027-08-01", "a": "2027-08-31", "unita_totali": 5,
               "prezzo_netto_cents": 10000}, HK)
        os.environ.pop("DAC7_BLOCCO_PAYOUT", None)

    def tearDown(self):
        os.environ.pop("DAC7_BLOCCO_PAYOUT", None)
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

    def _sopra_soglia(self):
        """Porta l'host SOPRA la soglia DAC7 (>= 2000 EUR nell'anno corrente) iniettando
        incassi nel giornale (stessa verità che usa aggrega_dac7)."""
        for i in range(3):
            self.sis.finanza.movimento(tipo="incasso", riferimento="VOL%d" % i,
                                       soggetto="host:" + self.hid, importo_cents=100000,
                                       valuta="EUR", causale="volume")

    def _dati_completi(self):
        return {"codice_fiscale": "RSSMRA80A01H501U", "indirizzo_fiscale": "Via Roma 1",
                "paese": "IT", "iban": "IT60X0542811101000000123456",
                "tipo_soggetto": "individuo"}

    def _token(self):
        s, c = self.g("POST", "/api/host/login",
                      {"email": "dac7@collaudo.invalid", "password": "password12"})
        self.assertEqual(s, 200)
        return {"X-Host-Token": c["token"]}

    # ── 1) sopra soglia + incompleto = HOLD ────────────────────────────────────
    def test_bloccato_sopra_soglia_incompleto(self):
        self._sopra_soglia()
        rif = self._prenota_paga()
        netto = self.sis.payout.riepilogo(self.hid)["EUR"]["maturato"]
        self.assertGreater(netto, 0)
        self.r._trasferisci_all_host(rif, netto)
        self.assertEqual(self.connect.chiamate, [])          # transfer MAI chiamato
        self.assertEqual(self.sis.payout.stato_di(rif), "maturato")   # parcheggiato, non perso
        tipi = [m["tipo"] for m in self.sis.finanza.movimenti(rif)]
        self.assertNotIn("payout_host", tipi)                # nessun bonifico nel giornale
        self.assertNotIn("payout_manuale", tipi)             # e non e' un "fallito": e' un hold

    # ── 2) sotto soglia = paga normalmente anche senza dati ────────────────────
    def test_sotto_soglia_paga_normale(self):
        rif = self._prenota_paga()                           # ~200 EUR: nessun obbligo DAC7
        netto = self.sis.payout.riepilogo(self.hid)["EUR"]["maturato"]
        self.r._trasferisci_all_host(rif, netto)
        self.assertEqual(len(self.connect.chiamate), 1)      # bonifico partito
        self.assertEqual(self.sis.payout.stato_di(rif), "in_transito")

    # ── 3) sopra soglia + dati completi = paga normalmente ─────────────────────
    def test_sopra_soglia_completo_paga(self):
        self._sopra_soglia()
        self.sis.registro_host.imposta_dati_fiscali(self.hid, self._dati_completi())
        rif = self._prenota_paga()
        netto = self.sis.payout.riepilogo(self.hid)["EUR"]["maturato"]
        self.r._trasferisci_all_host(rif, netto)
        self.assertEqual(len(self.connect.chiamate), 1)      # in regola: nessun blocco

    # ── 4) SBLOCCO AUTOMATICO al completamento dei dati ────────────────────────
    def test_sblocco_automatico_quando_completa(self):
        self._sopra_soglia()
        rif = self._prenota_paga()
        netto = self.sis.payout.riepilogo(self.hid)["EUR"]["maturato"]
        self.r._trasferisci_all_host(rif, netto)             # -> hold
        self.assertEqual(self.connect.chiamate, [])
        tok = self._token()
        s, c = self.r.gestisci("POST", "/api/host/dati_fiscali", {},
                               json.dumps(self._dati_completi()), tok)
        self.assertEqual(s, 200, c)
        self.assertEqual(c["mancanti"], [])
        self.assertGreaterEqual(c["payout_riprovati"], 1)    # ritentati subito
        self.assertEqual(len(self.connect.chiamate), 1)      # bonifico PARTITO da solo
        self.assertEqual(self.sis.payout.stato_di(rif), "in_transito")
        tipi = [m["tipo"] for m in self.sis.finanza.movimenti(rif)]
        self.assertIn("payout_host", tipi)                   # scatola nera: bonifico registrato
        self.assertTrue(self.sis.finanza.verifica_catena()["ok"])

    # ── 5) l'host VEDE l'avviso nel pannello ───────────────────────────────────
    def test_host_vede_avviso_hold(self):
        self._sopra_soglia()
        rif = self._prenota_paga()
        s, d = self.r.gestisci("GET", "/api/host/dac7_stato", {}, None, self._token())
        self.assertEqual(s, 200, d)
        self.assertTrue(d["payout_bloccati"])
        self.assertGreater(d["payout_fermi_cents"], 0)       # vede QUANTO e' fermo
        self.assertIn("codice_fiscale/partita_iva", d["mancanti"])
        # dopo il completamento l'avviso sparisce
        self.r.gestisci("POST", "/api/host/dati_fiscali", {},
                        json.dumps(self._dati_completi()), self._token())
        s, d = self.r.gestisci("GET", "/api/host/dac7_stato", {}, None, self._token())
        self.assertFalse(d["payout_bloccati"])
        self.assertEqual(d["mancanti"], [])

    # ── 6) il Bunker vede i payout fermi degli urgenti ─────────────────────────
    def test_bunker_vede_payout_fermi(self):
        self._sopra_soglia()
        self._prenota_paga()
        s, out = self.r.gestisci("POST", "/api/bunker/login", {},
                                 json.dumps({"codice": "SuperPw@1"}),
                                 {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(s, 200, out)
        hb = {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9",
              "X-Bunker-Session": out["sessione"]}
        anno = time.gmtime().tm_year
        s, d = self.r.gestisci("GET", "/api/bunker/dac7_conformita",
                               {"anno": str(anno)}, None, hb)
        self.assertEqual(s, 200, d)
        riga = {h["host_id"]: h for h in d["host"]}[self.hid]
        self.assertTrue(riga["urgente"])
        self.assertGreater(riga["payout_fermi_cents"], 0)

    # ── 7) kill-switch d'emergenza ─────────────────────────────────────────────
    def test_killswitch(self):
        self._sopra_soglia()
        rif = self._prenota_paga()
        os.environ["DAC7_BLOCCO_PAYOUT"] = "0"
        netto = self.sis.payout.riepilogo(self.hid)["EUR"]["maturato"]
        self.r._trasferisci_all_host(rif, netto)
        self.assertEqual(len(self.connect.chiamate), 1)      # gate spento: paga

    # ── 8) FAIL-OPEN: motore finanza rotto/assente -> mai congelare i bonifici ─
    def test_fail_open_senza_finanza(self):
        self._sopra_soglia()
        rif = self._prenota_paga()
        vero_fc = self.sis.finanza
        try:
            self.sis.finanza = None                          # "motore contabile giu'"
            netto = self.sis.payout.riepilogo(self.hid)["EUR"]["maturato"]
            self.r._trasferisci_all_host(rif, netto)
            self.assertEqual(len(self.connect.chiamate), 1)  # il bonifico DOVUTO parte
        finally:
            self.sis.finanza = vero_fc


if __name__ == "__main__":
    unittest.main()
