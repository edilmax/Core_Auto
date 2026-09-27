"""CASELLA 10 del BLOCCO SOLDI: lo stato di un pagamento si rilegge dall'API di Stripe,
non dal contenuto dell'evento.

La guida di Stripe per la consegna dopo il Checkout (docs.stripe.com/checkout/fulfillment,
letta il 2026-09-27) prescrive la funzione di consegna cosi': riceve l'ID della sessione,
la RECUPERA DALL'API, controlla `payment_status` e consegna solo se il pagamento c'e'; e va
chiamata sia su `checkout.session.completed` sia su `checkout.session.async_payment_succeeded`,
perche' con i metodi a conferma differita la sessione si chiude PRIMA che i soldi arrivino.
Sul nostro conto e' acceso Pix (letto dalla configurazione dei metodi il 2026-09-27): chi paga
con Pix chiude il Checkout e ha poi fino a 4 ore per trasferire i fondi.

Il gestore di oggi conferma la stanza su `checkout.session.completed` senza chiedere niente a
Stripe, e ignora `async_payment_succeeded`. Quindi:
  · una sessione chiusa SENZA pagamento conferma la stanza (soldi mai arrivati, host pagato);
  · il pagamento arrivato dopo non conferma niente, se l'ordine degli eventi si inverte.

⛔ LE GUARDIE NASCONO PRIMA della riparazione (D20) e vanno VISTE ROSSE sul codice di oggi.
Stripe finto al bordo: la rilettura passa dal fornitore (`sis.stripe`), come gia' fa
l'impronta della carta per il Lock.
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

SEG = b"r" * 32
HK = {"X-Host-Key": "hk"}
WHSEC = "whsec_test"


class StripeCheRisponde:
    """Stripe finto al bordo. `stati` e' cio' che l'API direbbe della sessione; una sessione
    che non c'e' nella mappa vuol dire «rilettura non riuscita» (rete, 5xx, timeout)."""

    def __init__(self):
        self.stati = {}
        self.letture = []
        self.rimborsi = []

    def stato_sessione(self, cs_id):
        self.letture.append(cs_id)
        return self.stati.get(cs_id, "")

    def impronta_carta(self, pi):
        return ""

    def rimborsa(self, pi, importo, chiave):
        self.rimborsi.append((pi, importo, chiave))
        return {"ok": True, "id": "re_test"}


class TestLoStatoSiRileggeDallAPI(unittest.TestCase):
    """e2e di prova: rotte vere, webhook firmato, Stripe finto al bordo."""

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
        self.stripe = StripeCheRisponde()
        self.sis.stripe = self.stripe
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "casa", "titolo": "C",
               "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
               "servizi": [], "immagini": [], "tassa_pp_notte_cents": 200}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa", "da": "2027-04-01",
               "a": "2027-05-31", "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _prenota(self, ci, co, email="o@x.it"):
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book", {"quote_token": q["quote_token"],
                                                      "email": email})
        return b["riferimento"]

    def _evento(self, evt_id, tipo, rif, cs, pi, stato_nell_evento="paid"):
        """Il corpo dice SEMPRE `paid` di proposito: la guardia prova che non gli si crede."""
        payload = json.dumps({"id": evt_id, "type": tipo,
                              "data": {"object": {"id": cs, "payment_intent": pi,
                                                  "payment_status": stato_nell_evento,
                                                  "metadata": {"riferimento": rif}}}})
        ts = str(int(time.time()))
        mac = hmac.new(WHSEC.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
        return self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})

    def stato(self, rif):
        return self.sis.pagamenti_pendenti.info(rif)["stato"]

    def incassi(self, rif):
        return [m for m in self.sis.finanza.movimenti(rif) if m.get("tipo") == "incasso"]

    # ------------------------------------------------------------------ il rosso vero

    def test_SESSIONE_CHIUSA_SENZA_SOLDI_NON_CONFERMA_LA_STANZA(self):
        """Pix: il Checkout si chiude, i soldi non ci sono ancora. L'evento dice `paid`
        (e' il falso piu' comodo), l'API dice `unpaid`: vince l'API. Risposta 2xx perche'
        l'evento e' gestito -- il pagamento, se arriva, porta un evento suo."""
        rif = self._prenota("2027-04-10", "2027-04-12")
        self.stripe.stati["cs_pix1"] = "unpaid"
        s, c = self._evento("evt_c1", "checkout.session.completed", rif, "cs_pix1", "pi_pix1")
        self.assertEqual(s, 200, "una sessione in attesa di pagamento e' un evento gestito: %r"
                         % (c,))
        self.assertNotEqual(self.stato(rif), "pagato",
                            "LA STANZA E' STATA CONFERMATA SENZA SOLDI: il gestore ha creduto "
                            "all'evento invece di rileggere la sessione dall'API")
        self.assertEqual(self.incassi(rif), [],
                         "il giornale registra un incasso che Stripe dice non avvenuto: %r"
                         % (self.incassi(rif),))
        self.assertIn("cs_pix1", self.stripe.letture,
                      "la sessione non e' stata riletta dall'API con il suo identificativo")

    def test_RILETTURA_FALLITA_NON_CONFERMA_E_CHIEDE_IL_RITENTATIVO(self):
        """Se Stripe non risponde non si sa se i soldi ci sono: non si conferma niente e si
        risponde NON-2xx, cosi' Stripe ritenta (e l'evento resta «da elaborare» per lo
        sweeper). Confermare «tanto l'evento dice paid» e' la stessa fiducia di prima."""
        rif = self._prenota("2027-04-14", "2027-04-16")
        # cs_giu NON e' nella mappa: la rilettura non riesce
        s, c = self._evento("evt_c2", "checkout.session.completed", rif, "cs_giu", "pi_giu")
        self.assertFalse(200 <= s < 300,
                         "RILETTURA FALLITA E RISPOSTA 2xx: Stripe non ritentera' mai piu' "
                         "(%r %r)" % (s, c))
        self.assertNotEqual(self.stato(rif), "pagato",
                            "confermato senza sapere se i soldi ci sono")
        self.assertFalse(self.sis.eventi_stripe.elaborato("evt_c2"),
                         "l'evento risulta elaborato: lo sweeper non lo ritentera'")

    def test_IL_PAGAMENTO_ARRIVATO_DOPO_CONFERMA(self):
        """La sequenza di Pix vera: sessione chiusa senza soldi, poi
        `checkout.session.async_payment_succeeded` quando i soldi arrivano. Il secondo
        evento conferma, dopo aver riletto la sessione, e l'incasso e' UNO."""
        rif = self._prenota("2027-04-18", "2027-04-20")
        self.stripe.stati["cs_pix2"] = "unpaid"
        self._evento("evt_c3", "checkout.session.completed", rif, "cs_pix2", "pi_pix2")
        self.assertNotEqual(self.stato(rif), "pagato",
                            "PREMESSA: la sessione senza soldi non conferma")
        self.stripe.stati["cs_pix2"] = "paid"
        s, c = self._evento("evt_a3", "checkout.session.async_payment_succeeded", rif,
                            "cs_pix2", "pi_pix2")
        self.assertEqual(s, 200, "%r" % (c,))
        self.assertEqual(self.stato(rif), "pagato",
                         "IL PAGAMENTO ARRIVATO DOPO NON CONFERMA LA STANZA: "
                         "`async_payment_succeeded` non viene gestito")
        self.assertEqual(len(self.incassi(rif)), 1, "%r" % (self.incassi(rif),))

    def test_L_ORDINE_DEGLI_EVENTI_NON_CONTA(self):
        """Stripe non garantisce l'ordine (docs.stripe.com/webhooks, «Ordine degli
        eventi»). Se `async_payment_succeeded` arriva PRIMA di `completed`, conferma lui;
        il `completed` che arriva dopo non raddoppia l'incasso."""
        rif = self._prenota("2027-04-22", "2027-04-24")
        self.stripe.stati["cs_inv"] = "paid"
        s1, c1 = self._evento("evt_a4", "checkout.session.async_payment_succeeded", rif,
                              "cs_inv", "pi_inv")
        self.assertEqual(s1, 200, "%r" % (c1,))
        self.assertEqual(self.stato(rif), "pagato",
                         "l'evento del pagamento arrivato per primo non conferma")
        s2, c2 = self._evento("evt_c4", "checkout.session.completed", rif, "cs_inv", "pi_inv")
        self.assertEqual(s2, 200, "%r" % (c2,))
        self.assertEqual(len(self.incassi(rif)), 1,
                         "due eventi dello stesso pagamento hanno fatto DUE incassi: %r"
                         % (self.incassi(rif),))

    def test_EVENTO_SENZA_SESSIONE_NON_CONFERMA_E_NON_FA_RITENTARE(self):
        """Un `checkout.session.completed` senza l'identificativo della sessione: Stripe non
        lo manda mai, e senza identificativo non c'e' niente da rileggere. Quindi non si
        conferma NIENTE. Ma non si fa nemmeno ritentare: un evento malformato resta
        malformato per tre giorni, e lo sweeper dopo un'ora griderebbe un'anomalia che non
        c'e' (ferrea 10). Stessa scelta gia' presa per l'evento senza `cs_` (fase83)."""
        rif = self._prenota("2027-04-30", "2027-05-02")
        payload = json.dumps({"id": "evt_senza", "type": "checkout.session.completed",
                              "data": {"object": {"payment_status": "paid",
                                                  "metadata": {"riferimento": rif}}}})
        ts = str(int(time.time()))
        mac = hmac.new(WHSEC.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
        s, c = self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})
        self.assertTrue(200 <= s < 300,
                        "un evento malformato fatto ritentare per tre giorni: %r %r" % (s, c))
        self.assertNotEqual(self.stato(rif), "pagato",
                            "confermato un pagamento che non si puo' rileggere")
        self.assertEqual(self.incassi(rif), [])
        # (che col fornitore VERO non parta nessuna chiamata a Stripe per un identificativo
        # vuoto lo prova `test_fase85_pagamenti_stripe.TestLaRiletturaDelloStato`)
        self.assertTrue(self.sis.eventi_stripe.elaborato("evt_senza"),
                        "l'evento resta «da elaborare»: lo sweeper lo ritenterebbe")

    # ------------------------------------------------------ tace a macchina sana (ferrea 10)

    def test_PAGAMENTO_CON_CARTA_CONFERMA_COME_SEMPRE(self):
        """La carta: la sessione si chiude pagata, l'API lo conferma, la stanza e' presa.
        Questa strada non deve cambiare, ed e' quella di quasi tutti."""
        rif = self._prenota("2027-04-26", "2027-04-28")
        self.stripe.stati["cs_carta"] = "paid"
        s, c = self._evento("evt_c5", "checkout.session.completed", rif, "cs_carta", "pi_carta")
        self.assertEqual(s, 200, "%r" % (c,))
        self.assertEqual(self.stato(rif), "pagato")
        self.assertEqual(len(self.incassi(rif)), 1)


if __name__ == "__main__":
    unittest.main()
