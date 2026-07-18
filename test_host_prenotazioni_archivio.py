"""Collaudo ARCHIVIAZIONE LOGICA di 'Le mie prenotazioni' (contratto PAGINATO server-side).

Dal 2026-07-18 l'endpoint GET /api/host/prenotazioni accetta `vista` (attive|archivio),
`page` e `limit`: il DATABASE taglia la pagina, al client viaggia solo il sottoinsieme.
Invarianti difesi qui (la paginazione fine e' in test_prenotazioni_paginazione):
  1. una prenotazione rimborsata dall'admin -> vista archivio, stato 'rimborsata';
  2. una cancellata dall'host -> vista archivio, stato 'cancellata' (distinta);
  3. una prenotazione viva futura -> vista attive, stato 'futura';
  4. la vista predefinita (attive) NON contiene mai rimborsate/cancellate;
  5. NESSUN DELETE fisico: attive+archivio == tutte, e i movimenti grezzi restano
     nel magazzino (audit integro);
  6. i contatori (totale_attive/totale_archivio) dicono la verita'.
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

SEG = b"h" * 32
HK = {"X-Host-Key": "hk"}
AK = {"X-Admin-Key": "ak"}
WHSEC = "whsec_test"
CI, CO = "2027-09-10", "2027-09-12"      # soggiorno nel FUTURO -> etichetta 'futura'


class TestArchivioPrenotazioni(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db", db_domanda=f"{d}/dom.db",
            db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_tassa_comunale=f"{d}/tc.db", file_referral=f"{d}/ref.json",
            commissione_bps=1500, stripe_webhook_secret=WHSEC))
        self.sis.concierge._link = lambda dati: "https://pay/" + str(dati.get("riferimento", ""))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "hotel",
               "titolo": "H", "citta": "Roma", "descrizione": "x",
               "prezzo_notte_cents": 10000, "capacita": 2, "servizi": [], "immagini": [],
               "tassa_pp_notte_cents": 200}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "hotel",
               "da": "2027-09-01", "a": "2027-09-30", "unita_totali": 10,
               "prezzo_netto_cents": 10000}, HK)
        self._seq = 0

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _prenota_paga(self):
        self._seq += 1
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "hotel",
                      "check_in": CI, "check_out": CO, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": f"o{self._seq}@collaudo.invalid"})
        rif = b["riferimento"]
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": rif}}}})
        ts = str(int(time.time()))
        mac = hmac.new(WHSEC.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
        s, _ = self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})
        self.assertEqual(s, 200)
        return rif

    def _vista(self, vista, page=1, limit=50):
        s, d = self.g("GET", "/api/host/prenotazioni", None, HK,
                      {"host_id": "demo", "vista": vista, "page": str(page),
                       "limit": str(limit)})
        self.assertEqual(s, 200)
        return d

    def test_archiviazione_logica_completa(self):
        [self._prenota_paga() for _ in range(2)]
        rimb = self._prenota_paga()
        canc = self._prenota_paga()

        idem = self.sis.pagamenti_pendenti.info(rimb)["idem_key"]
        s, _ = self.g("POST", "/api/admin/rimborso", {"alloggio_id": "hotel",
                      "check_in": CI, "check_out": CO, "idem_key": idem}, AK)
        self.assertEqual(s, 200)
        s, _ = self.g("POST", "/api/host/cancella", {"riferimento": canc, "host_id": "demo"}, HK)
        self.assertEqual(s, 200)

        att = self._vista("attive")
        arch = self._vista("archivio")
        attive, archivio = att["prenotazioni"], arch["prenotazioni"]

        # (4) la vista predefinita non contiene annullate
        self.assertEqual({p["stato"] for p in attive} & {"rimborsata", "cancellata"}, set())
        self.assertTrue(all(not p["archiviata"] for p in attive))
        # (3) vive future -> 'futura'
        self.assertEqual({p["stato"] for p in attive}, {"futura"})
        # (1)+(2) archivio: esattamente 1 rimborsata + 1 cancellata, distinte
        per_stato = {}
        for p in archivio:
            per_stato[p["stato"]] = per_stato.get(p["stato"], 0) + 1
        self.assertEqual(per_stato, {"rimborsata": 1, "cancellata": 1})
        self.assertTrue(all(p["archiviata"] for p in archivio))
        # (6) contatori veritieri, uguali su entrambe le viste
        for d in (att, arch):
            self.assertEqual(d["totale_attive"], 2)
            self.assertEqual(d["totale_archivio"], 2)
        self.assertEqual(att["totale"], 2)
        self.assertEqual(arch["totale"], 2)
        # (5) NESSUN DELETE: attive+archivio == tutte, movimenti grezzi intatti
        self.assertEqual(len(attive) + len(archivio), 4)
        grezze = self.sis.inventario.elenco_prenotazioni(alloggio_id="hotel", limit=500)
        self.assertEqual(len(grezze), 4, "un movimento e' SPARITO: ci sarebbe stato un DELETE")
        self.assertEqual(sum(1 for x in grezze if x["rimborsato"]), 2)

    def test_default_vuoto_e_contratto(self):
        d = self._vista("attive")
        self.assertEqual(d["prenotazioni"], [])
        self.assertEqual(d["totale"], 0)
        self.assertEqual(d["pagine"], 1)
        self._prenota_paga()
        d = self._vista("attive")
        self.assertEqual(len(d["prenotazioni"]), 1)
        self.assertFalse(d["prenotazioni"][0]["archiviata"])
        self.assertEqual(d["vista"], "attive")


if __name__ == "__main__":
    unittest.main()
