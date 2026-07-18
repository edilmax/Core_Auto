"""Collaudo ARCHIVIAZIONE LOGICA di 'Le mie prenotazioni' (pulizia UX, punto del fondatore).

L'endpoint GET /api/host/prenotazioni ora separa la VISTA senza toccare i dati:
  - vista attiva  = prenotazioni vive (archiviata=False), etichette attiva/futura/confermata;
  - archivio      = rimborsate + cancellate (archiviata=True), distinte per motivo.
Invarianti difesi:
  1. una prenotazione rimborsata dall'admin -> archiviata=True, stato 'rimborsata';
  2. una cancellata dall'host -> archiviata=True, stato 'cancellata';
  3. una prenotazione viva futura -> archiviata=False, stato 'futura';
  4. la vista predefinita (archiviata=False) NON contiene rimborsate ne' cancellate;
  5. NESSUN DELETE fisico: i movimenti restano nel DB (elenco_prenotazioni li vede ancora,
     e la somma vista+archivio = tutte le prenotazioni) -> l'audit e' integro;
  6. ogni riga porta il flag 'archiviata' (booleano) su cui il frontend fa lo split.
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

    def _prenotazioni(self):
        s, d = self.g("GET", "/api/host/prenotazioni", None, HK, {"host_id": "demo"})
        self.assertEqual(s, 200)
        return d["prenotazioni"]

    def test_archiviazione_logica_completa(self):
        vive = [self._prenota_paga() for _ in range(2)]
        rimb = self._prenota_paga()
        canc = self._prenota_paga()

        # admin RIMBORSA una (serve la sua idem_key per rilasciare lo STESSO blocco)
        idem = self.sis.pagamenti_pendenti.info(rimb)["idem_key"]
        s, _ = self.g("POST", "/api/admin/rimborso", {"alloggio_id": "hotel",
                      "check_in": CI, "check_out": CO, "idem_key": idem}, AK)
        self.assertEqual(s, 200)
        # host CANCELLA un'altra
        s, _ = self.g("POST", "/api/host/cancella", {"riferimento": canc, "host_id": "demo"}, HK)
        self.assertEqual(s, 200)

        pren = self._prenotazioni()
        # ogni riga ha il flag 'archiviata'
        self.assertTrue(all("archiviata" in p for p in pren), "manca il flag archiviata")

        attive = [p for p in pren if not p["archiviata"]]
        archivio = [p for p in pren if p["archiviata"]]

        # (4) la vista predefinita NON contiene rimborsate ne' cancellate
        stati_attivi = {p["stato"] for p in attive}
        self.assertEqual(stati_attivi & {"rimborsata", "cancellata"}, set(),
                         f"vista attiva sporca di annullate: {stati_attivi}")
        # (3) le vive future sono etichettate 'futura'
        self.assertTrue(attive, "nessuna prenotazione attiva")
        self.assertEqual({p["stato"] for p in attive}, {"futura"},
                         "le prenotazioni vive nel futuro devono essere 'futura'")

        # (1)+(2) l'archivio contiene ESATTAMENTE la rimborsata e la cancellata, distinte
        per_stato = {}
        for p in archivio:
            per_stato.setdefault(p["stato"], 0)
            per_stato[p["stato"]] += 1
        self.assertEqual(per_stato, {"rimborsata": 1, "cancellata": 1},
                         f"archivio atteso 1 rimborsata + 1 cancellata, trovato {per_stato}")

        # (5) NESSUN DELETE fisico: vista + archivio = tutte le 4 prenotazioni, e i movimenti
        # grezzi esistono ancora nel magazzino (audit integro)
        self.assertEqual(len(attive) + len(archivio), 4)
        grezze = self.sis.inventario.elenco_prenotazioni(alloggio_id="hotel", limit=500)
        self.assertEqual(len(grezze), 4, "un movimento e' SPARITO: ci sarebbe stato un DELETE")
        self.assertEqual(sum(1 for x in grezze if x["rimborsato"]), 2,
                         "le 2 archiviate devono risultare rilasciate, le 2 vive no")

    def test_default_vuoto_e_flag_sempre_presente(self):
        # nessuna prenotazione -> lista vuota, nessun crash
        self.assertEqual(self._prenotazioni(), [])
        # una sola viva -> attiva, archiviata False
        self._prenota_paga()
        pren = self._prenotazioni()
        self.assertEqual(len(pren), 1)
        self.assertFalse(pren[0]["archiviata"])


if __name__ == "__main__":
    unittest.main()
