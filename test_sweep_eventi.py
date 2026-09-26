"""CASELLA 9 del BLOCCO SOLDI: un'elaborazione fallita di un evento Stripe NON sparisce.

L'evento resta «non elaborato» nell'archivio (fase204), viene RITENTATO DA NOI dallo
sweeper `deploy/cron_sweep_eventi.py` — che ridelivera' il corpo salvato rifirmandolo
col nostro secret, ripercorrendo l'intero gestore: pagamento E identita' (KYC) — e
dopo un'ora di tentativi diventa un'ANOMALIA DEL GUARDIANO con email.

⛔ GUARDIE NASCUTE PRIMA dello strumento (D20): questa classe e' stata eseguita quando
di `deploy/cron_sweep_eventi.py` non esisteva niente, ed era ROSSA (import mancante).
Le due direzioni (ferrea 10): l'evento rimasto indietro viene ritentato E risolto; una
batteria di eventi a posto NON manda email (un allarme che grida sul normale viene spento).
"""
import hashlib
import hmac
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

SEG = b"h" * 32
HK = {"X-Host-Key": "hk"}
WHSEC = "whsec_sweep"


class ProviderFinto:
    def impronta_carta(self, pi):
        return ""

    def rimborsa(self, pi, importo, chiave):
        return {"ok": True, "id": "re_test"}


def evento_conferma(evt_id, rif, pi, sessione=None):
    return json.dumps({"id": evt_id, "type": "checkout.session.completed",
                       "data": {"object": {"metadata": {"riferimento": rif},
                                           "id": sessione or ("cs_" + pi[3:]),
                                           "payment_intent": pi}}})


class BancoSweep(unittest.TestCase):
    """Sistema vero con archivio vero: lo sweeper viene chiamato col sistema iniettato."""

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db",
            db_domanda=f"{d}/dom.db", db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db",
            db_tassa_comunale=f"{d}/tc.db", db_eventi_stripe=f"{d}/evt.db",
            db_finanza=f"{d}/fin.db", file_referral=f"{d}/ref.json",
            commissione_bps=1500, stripe_webhook_secret=WHSEC))
        self.sis.concierge._link = lambda dati: "https://pay/" + str(dati.get("riferimento", ""))
        self.sis.stripe = ProviderFinto()
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "casa", "titolo": "C",
               "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
               "servizi": [], "immagini": [], "tassa_pp_notte_cents": 200}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa", "da": "2027-02-01",
               "a": "2027-03-31", "unita_totali": 2, "prezzo_netto_cents": 10000}, HK)
        self.email = []

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _firma(self, payload):
        ts = str(int(time.time()))
        mac = hmac.new(WHSEC.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
        return "t=%s,v1=%s" % (ts, mac)

    def _consegna(self, evt_id, rif, pi, sessione=None):
        corpo = evento_conferma(evt_id, rif, pi, sessione)
        return self.r.gestisci("POST", "/api/payments/webhook", {}, corpo,
                               {"Stripe-Signature": self._firma(corpo)})

    def _prenota(self, ci, co, email="o@x.it"):
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book", {"quote_token": q["quote_token"],
                                                      "email": email})
        return b["riferimento"]

    def _sweep(self, router=None):
        from deploy.cron_sweep_eventi import main
        env = {"STRIPE_WEBHOOK_SECRET": WHSEC,
               "DB_EVENTI_STRIPE": f"{self.dir}/evt.db",
               "ALERT_EMAIL": "guardiano@bookinvip.com"}
        return main(env, self._send, ora=time.time, sistema=self.sis, router=router or self.r)

    def _invecchia(self, evt_id, secondi):
        """L'evento e' arrivato `secondi` fa: il ricevuto_ts va indietro (l'orologio
        dell'archivio e' quello vero, come in produzione)."""
        import sqlite3
        con = sqlite3.connect(f"{self.dir}/evt.db")
        with con:
            con.execute("UPDATE eventi_stripe SET ricevuto_ts=? WHERE evt_id=?",
                        (int(time.time()) - secondi, evt_id))
        con.close()

    def _send(self, dest, oggetto, corpo):
        self.email.append({"dest": dest, "oggetto": oggetto, "corpo": corpo})
        return True


class TestLoSweeperRitenta(BancoSweep):

    def test_un_evento_rimasto_indietro_viene_RILAVORATO_e_risolto(self):
        """Il caso della casella 9: Stripe consegnato, il nostro gestore morto prima della
        conferma. L'evento sta nell'archivio «da_elaborare», la prenotazione e' pagata ma
        non confermata. Lo sweeper ridelivera' il corpo salvato: la conferma avviene e
        l'evento esce dai pendenti."""
        rif = self._prenota("2027-02-10", "2027-02-12")
        corpo = evento_conferma("evt_perso", rif, "pi_A")
        # la consegna NON arriva (il nostro gestore muore prima di elaborare): l'evento
        # resta solo nell'archivio, segnato da... nessuno. Lo salva lo sweeper? No: lo
        # salva il gestore PRIMA di elaborare — qui si simula che il salvataggio abbia
        # avuto successo e l'elaborazione no (crash dopo il salvataggio).
        self.assertTrue(self.sis.eventi_stripe.salva(
            "evt_perso", tipo="checkout.session.completed", corpo_json=corpo,
            oggetto_id="cs_A"))
        # la consegna arriva, il salvataggio riesce, poi il gestore MUORE prima di
        # elaborare: quando lo sweeper guarda, l'evento ha gia' dieci minuti.
        self._invecchia("evt_perso", 600)
        self.assertEqual(self.sis.pagamenti_pendenti.info(rif)["stato"], "in_attesa",
                         "PREMESSA NON VALIDA: la prenotazione non deve essere confermata")

        uscita = self._sweep()

        self.assertEqual(uscita, 0, "il giro con un evento risolto e' un giro a posto")
        self.assertEqual(self.sis.pagamenti_pendenti.info(rif)["stato"], "pagato",
                         "L'EVENTO PERSO E' RESTATO PERSO: lo sweeper non lo ha ritentato, "
                         "o lo ha ritentato e la conferma non e' avvenuta")
        self.assertTrue(self.sis.eventi_stripe.elaborato("evt_perso"),
                        "l'evento ritentato con successo non e' segnato elaborato")
        self.assertEqual(self.email, [],
                         "nessuna anomalia (l'evento e' giovane e ora risolto): la mail "
                         "non parte — un allarme che grida sul normale viene spento")

    def test_anni_dopo_un_ora_di_tentativi_e_ANOMALIA_del_guardiano_con_email(self):
        """L'altra direzione: un evento che supera un'ora di tentativi ancora indietro
        diventa un'anomalia del Guardiano CON EMAIL (ferrea 10: l'anomalia grida). Qui
        il gestore e' avvolto per rispondere 500: la ridelivery fallisce, il tentativo
        si conta, e l'evento (vecchio di un'ora e mezza) diventa anomalia."""
        rif = self._prenota("2027-02-10", "2027-02-12")
        corpo = evento_conferma("evt_morto", rif, "pi_A")
        self.assertTrue(self.sis.eventi_stripe.salva(
            "evt_morto", tipo="checkout.session.completed", corpo_json=corpo,
            oggetto_id="cs_A"))
        # il ricevuto_ts e' vecchio di un'ora e mezza: la soglia dell'anomalia e' passata
        self._invecchia("evt_morto", 5400)
        vero_gestore = self.r._webhook_stripe_registrato

        def gestore_morto(body, headers):
            return 500, {"errore": "il gestore e' giu' (simulato)"}
        self.r._webhook_stripe_registrato = gestore_morto
        try:
            uscita = self._sweep()
        finally:
            self.r._webhook_stripe_registrato = vero_gestore

        self.assertEqual(uscita, 1, "un'anomalia aperta non e' un giro a posto")
        self.assertTrue(self.email, "l'anomalia del Guardiano DEVE mandare l'email")
        self.assertIn("URGENTE", self.email[0]["oggetto"],
                      "l'anomalia va gridata nell'oggetto: %r" % (self.email[0],))
        self.assertEqual(
            [e for e in self.sis.eventi_stripe.pendenti(piu_vecchi_di_sec=0, limite=10)
             if e["evt_id"] == "evt_morto"][0]["tentativi"], 1,
            "il tentativo fallito va CONTATO nell'archivio")

    def test_il_ramo_KYC_viene_ritentato_anch_esso(self):
        """«Anche sul ramo dell'identita' (KYC), non solo su quello del pagamento»: lo
        sweeper ridelivera' QUALUNQUE evento pendente, identita' compresa. L'ESITO della
        sessione di un host inesistente e' rifiutato dallo stato-machine del KYC (e va
        bene cosi'): quello che la casella chiede e' che il TENTATIVO arrivi a quel ramo."""
        corpo = json.dumps({"id": "evt_kyc", "type": "identity.verification_session.completed",
                            "data": {"object": {"status": "verified",
                                                "metadata": {"host_id": "h_inesistente"}}}})
        self.assertTrue(self.sis.eventi_stripe.salva(
            "evt_kyc", tipo="identity.verification_session.completed", corpo_json=corpo,
            oggetto_id="vs_demo"))
        self._invecchia("evt_kyc", 600)
        consegnati = []
        vero_gestore = self.r._webhook_stripe_registrato

        def registra(body, headers):
            consegnati.append(json.loads(body).get("id", ""))
            return vero_gestore(body, headers)
        self.r._webhook_stripe_registrato = registra
        try:
            uscita = self._sweep()
        finally:
            self.r._webhook_stripe_registrato = vero_gestore

        self.assertEqual(uscita, 0, "niente anomalie sotto l'ora: %r" % (self.email,))
        self.assertIn("evt_kyc", consegnati,
                      "l'evento di identita' NON e' stato ritentato: il ramo KYC e' "
                      "restato fuori dallo sweeper. Consegnati: %r" % (consegnati,))


class TestLoSweeperNonPUOBARARE(unittest.TestCase):
    """D18: lo strumento prova prima se stesso, e in mancanza di config NON ESEGUITO (S7)."""

    def test_senza_config_NON_ESEGUITO_niente_email_niente_crash(self):
        from deploy.cron_sweep_eventi import main
        email = []
        uscita = main({"STRIPE_WEBHOOK_SECRET": "", "DB_EVENTI_STRIPE": "",
                       "ALERT_EMAIL": ""}, lambda *a: email.append(a) or True)
        self.assertEqual(uscita, 2, "senza config il giro e' NON ESEGUITO, non ok")
        self.assertEqual(email, [], "senza config non si manda niente")

    def test_lo_script_DA_SOLO_da_cartella_qualunque(self):
        """D23: lo script lanciato da cron gira da solo (sys.path = /app/deploy) — la
        guardia lo lancia con la cwd di UN'ALTRA cartella e pretende il codice 2 di
        config mancante, che prova che i moduli fase sono importabili e il main gira."""
        import os
        radice = os.path.dirname(os.path.abspath(__file__))
        ambiente = {"PATH": "", "SystemRoot": os.environ.get("SystemRoot", ""),
                    "SYSTEMDRIVE": os.environ.get("SYSTEMDRIVE", "")}
        prova = subprocess.run(
            [sys.executable, os.path.join(radice, "deploy", "cron_sweep_eventi.py")],
            cwd=tempfile.mkdtemp(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=120, env=ambiente)              # nessuna config: NON ESEGUITO (S7)
        testo = prova.stdout.decode("utf-8", "replace")
        self.assertEqual(prova.returncode, 2,
                         "lo script da solo non risponde NON ESEGUITO: %s" % testo[-400:])
        self.assertIn("NON ESEGUITO", testo)


if __name__ == "__main__":
    unittest.main()
