"""Test politica di cancellazione scelta dall'HOST per alloggio (modello Booking) + sicurezza:
la politica è BLOCCATA nel voucher firmato, la cancellazione la usa (NON quella passata
dall'ospite furbo) + Credito Viaggio anti-rimpianto sulla penale.

Date RELATIVE a oggi (niente 'bombe a tempo'). Il RIPENSAMENTO 48h (arrivo >=72h + annullo
entro 2 giorni) dà 100% a prescindere dalla politica; per testare la PENALE si usa un arrivo
imminente (<3 giorni) fuori dal ripensamento."""
import datetime
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

SEG = b"p" * 32
HK = {"X-Host-Key": "hk"}


class TestPoliticaCancellazione(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.oggi = datetime.date.today()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db",
            db_messaggi=f"{d}/m.db", db_domanda=f"{d}/dom.db", file_referral=f"{d}/ref.json",
            commissione_bps=1500))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, body=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {},
                               json.dumps(body) if body is not None else None, h or {})

    def _d(self, giorni):
        return (self.oggi + datetime.timedelta(days=giorni)).isoformat()

    def _pubblica(self, politica):
        self.g("POST", "/api/host/pubblica", {
            "host_id": "demo", "slug": "casa", "titolo": "Casa", "citta": "Roma",
            "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
            "servizi": [], "immagini": [], "politica_cancellazione": politica}, HK)
        self.g("POST", "/api/host/disponibilita_range", {
            "alloggio_id": "casa", "da": self.oggi.isoformat(), "a": self._d(60),
            "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)

    def test_host_sceglie_e_ospite_la_vede(self):
        self._pubblica("rigida")
        _, c = self.g("GET", "/api/catalogo/casa")
        self.assertEqual(c["politica_cancellazione"], "rigida")
        self.assertEqual(self.sis.catalogo.politica_cancellazione_di("casa"), "rigida")

    def test_politica_invalida_default_flessibile(self):
        self._pubblica("inventata_xyz")
        self.assertEqual(self.sis.catalogo.politica_cancellazione_di("casa"), "flessibile")

    def test_ANTIFURBATA_ospite_non_puo_scegliersi_la_politica(self):
        self._pubblica("rigida")                                  # host: RIGIDA
        _, q = self.g("POST", "/api/concierge/quote", {
            "alloggio_id": "casa", "check_in": self._d(9), "check_out": self._d(11),
            "party": 1})                                          # arrivo +9gg
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "o@x.it"})
        # l'ospite prova a barare passando 'flessibile' nella richiesta di cancellazione
        _, c = self.g("POST", "/api/concierge/cancella",
                      {"voucher_token": b["voucher_token"], "politica": "flessibile"})
        self.assertEqual(c["politica"], "rigida")                 # ha VINTO quella dell'host
        # annullo immediato con arrivo +9gg -> RIPENSAMENTO 48h -> 100% (e non ci si guadagna
        # a mentire: la politica resta 'rigida', il 100% viene dal ripensamento universale)
        self.assertTrue(c["ripensamento"])
        self.assertEqual(c["rimborso_cents"], 20000)
        self.assertEqual(c["trattenuto_cents"], 0)

    def test_credito_viaggio_anti_rimpianto_sulla_penale(self):
        # Fuori dal ripensamento (arrivo imminente +1gg): scatta la PENALE -> parte torna in credito.
        self._pubblica("moderata")                                # moderata: a +1gg -> 50%
        _, q = self.g("POST", "/api/concierge/quote", {
            "alloggio_id": "casa", "check_in": self._d(1), "check_out": self._d(3),
            "party": 1})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "o@x.it"})
        _, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertFalse(c["ripensamento"])                       # arrivo <3gg -> niente ripensamento
        self.assertEqual(c["trattenuto_cents"], 10000)            # 50% di 20000
        self.assertEqual(c["credito_viaggio_cents"], 5000)        # 50% della penale torna in credito
        self.assertTrue(c["credito_viaggio_token"])               # token firmato, riscattabile

    def test_catalogo_badge_cancellazione_gratuita(self):
        # in RICERCA: flessibile/moderata -> badge "cancellazione gratuita" (leva di conversione)
        self._pubblica("flessibile")
        _, c = self.g("GET", "/api/catalogo", q={"citta": "Roma"})
        cards = [r for r in c.get("risultati", []) if r.get("slug") == "casa"]
        self.assertTrue(cards)
        self.assertEqual(cards[0]["politica_cancellazione"], "flessibile")
        self.assertTrue(cards[0]["cancellazione_gratuita"])

    def test_filtro_solo_gratuita_esclude_rigida(self):
        self._pubblica("rigida")                                   # non è "gratuita"
        _, tutti = self.g("GET", "/api/catalogo", q={"citta": "Roma"})
        self.assertTrue([r for r in tutti.get("risultati", []) if r.get("slug") == "casa"])
        _, solo = self.g("GET", "/api/catalogo", q={"citta": "Roma", "solo_gratuita": "1"})
        self.assertEqual([r for r in solo.get("risultati", []) if r.get("slug") == "casa"], [])

    def test_non_rimborsabile_sconto_12_onesto_nel_preventivo(self):
        # sconto -12% VERO dentro il preventivo firmato (finanziato dall'host), non un finto sconto
        self._pubblica("non_rimborsabile")
        _, q = self.g("POST", "/api/concierge/quote", {
            "alloggio_id": "casa", "check_in": self._d(10), "check_out": self._d(12), "party": 1})
        self.assertEqual(q["prezzo_listino_cents"], 20000)              # 2 notti x 10000
        self.assertEqual(q["sconto_non_rimborsabile_cents"], 2400)     # -12%
        self.assertEqual(q["prezzo_guest_cents"], 17600)              # l'ospite paga meno DAVVERO

    def test_mappa_domanda_e_prova_sociale(self):
        # motore cold-start: la lista d'attesa aggregata per città ("N cercano già a X")
        self.g("POST", "/api/domanda", {"email": "a@x.com", "citta": "Roma"})
        self.g("POST", "/api/domanda", {"email": "b@x.com", "citta": "Roma"})
        self.g("POST", "/api/domanda", {"email": "c@x.com", "citta": "Milano"})
        _, m = self.g("GET", "/api/domanda/citta")
        d = {r["citta"]: r["richieste"] for r in m["citta"]}
        self.assertEqual(d.get("roma"), 2)
        self.assertEqual(d.get("milano"), 1)
        _, cc = self.g("GET", "/api/domanda/conta", q={"citta": "Roma"})
        self.assertEqual(cc["richieste"], 2)

    def test_allarme_domanda_oltre_soglia(self):
        import os
        os.environ["DOMANDA_SOGLIA"] = "2"
        try:
            self.g("POST", "/api/domanda", {"email": "a@x.com", "citta": "Roma"})
            self.g("POST", "/api/domanda", {"email": "b@x.com", "citta": "Roma"})   # raggiunge 2
            self.g("POST", "/api/domanda", {"email": "c@x.com", "citta": "Milano"})  # 1
            _, m = self.g("GET", "/api/domanda/citta")
            self.assertEqual(m["soglia"], 2)
            d = {r["citta"]: r["oltre_soglia"] for r in m["citta"]}
            self.assertTrue(d.get("roma"))       # 2 >= soglia -> evidenziata
            self.assertFalse(d.get("milano"))    # 1 < soglia
        finally:
            os.environ.pop("DOMANDA_SOGLIA", None)

    def test_flessibile_nessuno_sconto_non_rimborsabile(self):
        self._pubblica("flessibile")
        _, q = self.g("POST", "/api/concierge/quote", {
            "alloggio_id": "casa", "check_in": self._d(10), "check_out": self._d(12), "party": 1})
        self.assertEqual(q["sconto_non_rimborsabile_cents"], 0)
        self.assertEqual(q["prezzo_guest_cents"], 20000)


if __name__ == "__main__":
    unittest.main()
