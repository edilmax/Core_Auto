"""Guardie a specchio del LOCK 1-CARTA=1-SCONTO (ordine del fondatore, via esplicito).

La carta che ha gia' pagato una prenotazione col Credito Fondatore non ne ottiene un
ALTRO, anche con email diverse. Le guardie girano sulle ROTTE VERE (publish, quote,
book, webhook firmato) con Stripe finto SOLO al bordo del provider: e2e di prova,
zero rete. Due direzioni (ferrea 10): il primo credito di una carta si conferma, la
STESSA carta con un credito diverso vede il RIMBORSO PIENO e la prenotazione rifiutata.
La serratura email+citta' (PR #213) resta il primo muro: qui si chiude il buco della
carta riusata (le guardie di test_fase158_serratura continuano a girare nella suite).
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
from fase167_credito_single_use import crea_registro_crediti_usati

SEG = b"h" * 32
HK = {"X-Host-Key": "hk"}
WHSEC = "whsec_test"


class ProviderFinto:
    """Stripe finto al bordo: l'impronta e' una mappa, il rimborso si registra."""

    def __init__(self, impronte=None, alza=False):
        self.impronte = impronte or {}
        self.alza = alza
        self.rimborsi = []
        self.letture = 0

    def impronta_carta(self, pi):
        self.letture += 1
        if self.alza:
            raise OSError("Stripe API giu' (finta)")
        return self.impronte.get(pi, "")

    def rimborsa(self, pi, importo, chiave):
        self.rimborsi.append((pi, importo, chiave))
        return {"ok": True, "id": "re_test", "motivo": "succeeded"}


class TestLockSulWebhook(unittest.TestCase):
    """e2e di prova: rotte vere, webhook firmato, Stripe finto al bordo."""

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db",
            db_domanda=f"{d}/dom.db", db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db",
            db_tassa_comunale=f"{d}/tc.db", db_eventi_stripe=f"{d}/evt.db",
            file_referral=f"{d}/ref.json", commissione_bps=1500, stripe_webhook_secret=WHSEC))
        # Come nel fixture di test_fase162: il LINK di pagamento si finge a livello
        # concierge, cosi' il book registra il pendente (l'hold) come in produzione.
        self.sis.concierge._link = lambda dati: "https://pay/" + str(dati.get("riferimento", ""))
        self.sis.stripe = ProviderFinto()
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "casa", "titolo": "C",
               "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
               "servizi": [], "immagini": [], "tassa_pp_notte_cents": 200}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa", "da": "2027-02-01",
               "a": "2027-03-31", "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _credito(self, nome):
        return self.sis.firma.codifica({
            "tipo": "credito_fondatore", "email": "", "citta": "",
            "credito_cents": 500, "valuta": "EUR",
            "exp": int(time.time()) + 365 * 86400, "nonce": nome.encode().hex()})

    def _prenota(self, ci, co, token=None, email="o@x.it"):
        corpo = {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2}
        if token:
            corpo["credito_token"] = token
        _, q = self.g("POST", "/api/concierge/quote", corpo)
        _, b = self.g("POST", "/api/concierge/book", {"quote_token": q["quote_token"],
                                                      "email": email})
        return b["riferimento"]

    def _webhook(self, evt_id, rif, pi):
        payload = json.dumps({"id": evt_id, "type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": rif},
                                                  "id": "cs_" + pi[3:],
                                                  "payment_intent": pi}}})
        ts = str(int(time.time()))
        mac = hmac.new(WHSEC.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
        return self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})

    def _impronte(self, **mappa):
        self.sis.stripe.impronte = mappa

    def test_il_primo_credito_di_una_carta_si_conferma(self):
        rif = self._prenota("2027-02-10", "2027-02-12", self._credito("uno"))
        rec = self.sis.pagamenti_pendenti.info(rif)
        self.assertTrue(json.loads(rec["corpo_json"]).get("credito_id"),
                        "misura non valida: la prenotazione non porta il credito")
        self._impronte(pi_A="FP-1")
        s, c = self._webhook("evt_1", rif, "pi_A")
        self.assertEqual(s, 200)
        self.assertEqual(self.sis.pagamenti_pendenti.info(rif)["stato"], "pagato")
        self.assertEqual(self.sis.stripe.rimborsi, [])

    def test_la_stessa_carta_con_un_altro_credito_vede_rimborso_pieno_e_rifiuto(self):
        rif_a = self._prenota("2027-02-10", "2027-02-12", self._credito("uno"))
        rif_b = self._prenota("2027-02-15", "2027-02-17", self._credito("due"),
                              email="altra@x.it")
        self._impronte(pi_A="FP-1", pi_B="FP-1")
        s, _ = self._webhook("evt_a", rif_a, "pi_A")
        self.assertEqual(s, 200)
        self.assertEqual(self.sis.pagamenti_pendenti.info(rif_a)["stato"], "pagato")
        with self.assertLogs("core_auto.server", level="CRITICAL") as log:
            s, c = self._webhook("evt_b", rif_b, "pi_B")
        self.assertEqual(s, 200)
        self.assertEqual(c.get("lock_carta"), "credito_negato")
        rec_b = self.sis.pagamenti_pendenti.info(rif_b)
        self.assertEqual(rec_b["stato"], "rimborsato")
        self.assertEqual(len(self.sis.stripe.rimborsi), 1)
        pi, importo, chiave = self.sis.stripe.rimborsi[0]
        self.assertEqual(pi, "pi_B")
        self.assertTrue(importo > 0)
        self.assertEqual(chiave, "lock-carta:" + rif_b)

    def test_il_replay_dello_stesso_webhook_non_rimborsa_due_volte(self):
        rif_a = self._prenota("2027-02-10", "2027-02-12", self._credito("uno"))
        rif_b = self._prenota("2027-02-15", "2027-02-17", self._credito("due"))
        self._impronte(pi_A="FP-1", pi_B="FP-1")
        self._webhook("evt_a", rif_a, "pi_A")
        self._webhook("evt_b", rif_b, "pi_B")
        s, c = self._webhook("evt_b", rif_b, "pi_B")   # STESSO evento, ritentato
        self.assertEqual(c.get("duplicato"), True)
        self.assertEqual(len(self.sis.stripe.rimborsi), 1)
        s, c = self._webhook("evt_b2", rif_b, "pi_B")  # NUOVO evento, stesso book
        self.assertEqual(c.get("lock_carta"), "credito_negato")
        # Il rimborso ripetuto porta la STESSA chiave di idempotenza: Stripe non
        # restituisce i soldi due volte anche se il webhook arriva per giorni.
        self.assertEqual(len({k for _, _, k in self.sis.stripe.rimborsi}), 1)

    def test_una_prenotazione_senza_credito_non_tocca_il_lock(self):
        rif = self._prenota("2027-02-10", "2027-02-12")
        self._impronte(pi_C="FP-1")
        s, c = self._webhook("evt_c", rif, "pi_C")
        self.assertEqual(s, 200)
        self.assertEqual(self.sis.pagamenti_pendenti.info(rif)["stato"], "pagato")
        self.assertEqual(self.sis.stripe.letture, 0)
        self.assertEqual(self.sis.stripe.rimborsi, [])

    def test_impronta_non_ottenibile_fail_open_dichiarato(self):
        rif = self._prenota("2027-02-10", "2027-02-12", self._credito("uno"))
        self.sis.stripe.alza = True
        with self.assertLogs("core_auto.server", level="WARNING") as log:
            s, c = self._webhook("evt_d", rif, "pi_D")
        self.assertEqual(s, 200)
        self.assertNotIn("lock_carta", c)
        self.assertEqual(self.sis.pagamenti_pendenti.info(rif)["stato"], "pagato")
        self.assertTrue(any("LOCK CARTA" in r for r in log.output),
                        "il fail-open va DICHIARATO nel registro, non tace")


class TestLegaCartaSpeculare(unittest.TestCase):
    """Il registro: stessa semantica di `consuma`, nelle due direzioni."""

    def setUp(self):
        self.reg = crea_registro_crediti_usati(":memory:")
        self.reg.inizializza_schema()

    def test_impronta_vuota_non_scrive_niente(self):
        self.assertEqual(self.reg.lega_carta("", "cred1", "R1"), "nuovo")
        self.assertEqual(self.reg.lega_carta(None, "cred1", "R1"), "nuovo")

    def test_credito_vuoto_non_scrive_niente(self):
        self.assertEqual(self.reg.lega_carta("FP-1", "", "R1"), "nuovo")
        self.assertEqual(self.reg.lega_carta("FP-1", None, "R1"), "nuovo")

    def test_primo_stesso_diverso(self):
        self.assertEqual(self.reg.lega_carta("FP-1", "cred1", "R1"), "nuovo")
        self.assertEqual(self.reg.lega_carta("FP-1", "cred1", "R1"), "stesso")
        # stessa carta, credito DIVERSO: abuso
        self.assertEqual(self.reg.lega_carta("FP-1", "cred2", "R2"), "diverso")
        # stessa carta, STESSO credito ma prenotazione DIVERSA: non e' un replay
        self.assertEqual(self.reg.lega_carta("FP-1", "cred1", "R2"), "diverso")

    def test_riferimento_vuoto_mai_stesso(self):
        self.assertEqual(self.reg.lega_carta("FP-1", "cred1", ""), "nuovo")
        self.assertEqual(self.reg.lega_carta("FP-1", "cred1", ""), "diverso")

    def test_carte_diverse_non_si_intralciano(self):
        self.assertEqual(self.reg.lega_carta("FP-1", "cred1", "R1"), "nuovo")
        self.assertEqual(self.reg.lega_carta("FP-2", "cred1", "R2"), "nuovo")


if __name__ == "__main__":
    unittest.main()
