"""
Test E2E INTEGRAZIONE "chi manda / chi riceve": simula i canali di scambio del sistema con
mittenti e destinatari, SENZA rete (fetch/send/canali iniettati). Copre acquisizione host
(lead -> gate giurisdizioni -> email -> opt-out), messaggistica bidirezionale + PII, email
transazionale resiliente (timeout SMTP non blocca la prenotazione), webhook Stripe firmato,
dispatch campagna marketing.
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

SEG = b"i" * 32
HK = {"X-Host-Key": "hk"}


def _stub_osm(*emails):
    els = [{"type": "node", "tags": {"name": "Hotel", "contact:email": e}} for e in emails]
    return lambda q: {"elements": els}


class CaptureEmail:
    def __init__(self, esplodi=False):
        self.inviate = []
        self._boom = esplodi

    def invia(self, dest, oggetto, corpo_html):
        if self._boom:
            raise TimeoutError("SMTP timeout")
        self.inviate.append((dest, oggetto, corpo_html))
        return True


class CaptureChannel:
    nome = "stub"

    def __init__(self):
        self.posts = []

    def pubblica(self, post):
        self.posts.append(post)
        return True


# ───────────────────────── 1) ACQUISIZIONE HOST (outreach) ─────────────────────
class TestAcquisizioneOutreach(unittest.TestCase):
    def setUp(self):
        from fase96_fonte_osm import FonteOpenStreetMap
        from fase95_outreach_email import crea_motore_outreach_durevole
        self.fonte = FonteOpenStreetMap(fetch=_stub_osm("host@inn.us"))
        self.motore = crea_motore_outreach_durevole(giurisdizioni_permesse=["US"],
                                                    link_opt_out="https://bookinvip.com/stop")

    def _esegui(self, paese):
        sent = []
        rep = self.motore.esegui(self.fonte, paese=paese, concorrenti_bps=[2500],
                                 invia=lambda e, o, c, l: sent.append((e, o, c)) or True)
        return rep, sent

    def test_invia_solo_dove_lecito_e_compone_email(self):
        rep, sent = self._esegui("US")                      # US permesso
        self.assertEqual(rep["inviati"], 1)
        self.assertEqual(len(sent), 1)
        corpo = sent[0][2]
        self.assertIn("Prima Emilia", corpo)                # email di acquisizione
        self.assertIn("bookinvip.com/stop", corpo)          # opt-out obbligatorio

    def test_giurisdizione_non_permessa_bloccata(self):
        rep, sent = self._esegui("FR")                      # UE: NON inviare
        self.assertEqual(rep["inviati"], 0)
        self.assertEqual(len(sent), 0)
        self.assertGreaterEqual(rep["bloccati"], 1)

    def test_opt_out_sovrano(self):
        self.motore.opt_out("host@inn.us")
        rep, sent = self._esegui("US")
        self.assertEqual(rep["inviati"], 0)
        self.assertEqual(rep["motivi"].get("opt_out"), 1)


# ───────────────────────── 2) MESSAGGISTICA bidirezionale ──────────────────────
class TestMessaggisticaRoundtrip(unittest.TestCase):
    def test_host_e_guest_si_scrivono_pii_mascherata(self):
        from fase113_messaggistica import crea_messaggistica
        m = crea_messaggistica(":memory:")
        m.inizializza_schema()
        self.assertTrue(m.invia("P1", "host1", "guest1", "host1", "Benvenuto!"))
        self.assertTrue(m.invia("P1", "host1", "guest1", "guest1",
                                "ok, il mio numero e' 333 1234567"))
        th = m.thread("P1", "host1")
        self.assertEqual(len(th), 2)                        # entrambi i lati nel thread
        self.assertEqual(th[0]["mittente"], "host1")
        self.assertEqual(th[1]["mittente"], "guest1")
        self.assertIn("[contatto rimosso]", th[1]["testo"]) # PII oscurata


# ───────────── 3) EMAIL TRANSAZIONALE: invia, riceve, resiliente ───────────────
class TestEmailTransazionale(unittest.TestCase):
    def _sistema(self, email_provider):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db",
            db_messaggi=f"{d}/m.db", file_referral=f"{d}/ref.json", commissione_bps=1500))
        sis.email_provider = email_provider                 # inietto il provider (sender)
        r = crea_router(sis, host_key="hk", base_url="https://bookinvip.com")
        r.gestisci("POST", "/api/host/pubblica", {}, json.dumps({
            "host_id": "demo", "slug": "casa", "titolo": "Casa", "citta": "Roma",
            "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
            "servizi": [], "immagini": []}), HK)
        r.gestisci("POST", "/api/host/disponibilita_range", {}, json.dumps({
            "alloggio_id": "casa", "da": "2026-07-01", "a": "2026-07-31",
            "unita_totali": 1, "prezzo_netto_cents": 10000}), HK)
        return r

    def _prenota(self, r, ci, co):
        _, q = r.gestisci("POST", "/api/concierge/quote", {}, json.dumps({
            "alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 1}), {})
        return r.gestisci("POST", "/api/concierge/book", {}, json.dumps({
            "quote_token": q["quote_token"], "email": "ospite@x.it"}), {})

    def test_email_inviata_al_guest_su_prenotazione(self):
        cap = CaptureEmail()
        s, _ = self._prenota(self._sistema(cap), "2026-07-05", "2026-07-07")
        self.assertEqual(s, 201)
        self.assertEqual(len(cap.inviate), 1)               # email ricevuta dall'ospite
        self.assertEqual(cap.inviate[0][0], "ospite@x.it")

    def test_smtp_timeout_NON_blocca_la_prenotazione(self):
        # requisito: se l'SMTP va in timeout, la transazione finanziaria NON si blocca
        s, b = self._prenota(self._sistema(CaptureEmail(esplodi=True)),
                             "2026-07-08", "2026-07-10")
        self.assertEqual(s, 201)                            # prenotazione confermata lo stesso
        self.assertEqual(b["stato"], "confermata")


# ───────────────────── 4) WEBHOOK STRIPE: Stripe manda, noi riceviamo ──────────
class TestWebhookStripe(unittest.TestCase):
    SECRET = "whsec_test_segreto"

    def _router(self, con_secret=True):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db",
            db_messaggi=f"{d}/m.db", file_referral=f"{d}/ref.json",
            stripe_webhook_secret=self.SECRET if con_secret else ""))
        return crea_router(sis, host_key="hk")

    def _firma(self, payload):
        ts = str(int(time.time()))
        mac = hmac.new(self.SECRET.encode(), f"{ts}.{payload}".encode(),
                       hashlib.sha256).hexdigest()
        return "t=%s,v1=%s" % (ts, mac)

    def test_webhook_firma_valida_confermato(self):
        r = self._router()
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": "R1"}}}})
        s, _ = r.gestisci("POST", "/api/payments/webhook", {}, payload,
                          {"Stripe-Signature": self._firma(payload)})
        self.assertEqual(s, 200)

    def test_webhook_firma_falsa_rifiutato(self):
        r = self._router()
        payload = json.dumps({"type": "checkout.session.completed", "data": {}})
        s, _ = r.gestisci("POST", "/api/payments/webhook", {}, payload,
                          {"Stripe-Signature": "t=1,v1=deadbeef"})
        self.assertEqual(s, 400)

    def test_webhook_gated_senza_secret(self):
        s, _ = self._router(con_secret=False).gestisci(
            "POST", "/api/payments/webhook", {}, "{}", {"Stripe-Signature": "x"})
        self.assertEqual(s, 503)


# ───────────────────── 5) MARKETING: dispatch sui canali (chi manda) ───────────
class TestMarketingDispatch(unittest.TestCase):
    def test_campagna_pubblica_sui_canali(self):
        from fase90_marketing import crea_motore_marketing
        ch = CaptureChannel()
        motore = crea_motore_marketing(canali={"stub": ch})
        rep = motore.esegui_campagna(["it"])
        self.assertGreater(rep["post_generati"], 0)
        self.assertGreater(rep["pubblicati"], 0)            # pubblicati sul canale
        self.assertTrue(ch.posts)                           # il canale ha ricevuto i post


if __name__ == "__main__":
    unittest.main()
