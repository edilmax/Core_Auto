"""
Test CONTRATTO pannelli<->macchina: ogni endpoint che i pannelli (index/host/admin) chiamano
DEVE esistere nel backend. Un pannello che chiama una rotta fantasma = figuraccia online.
Verifica che ogni rotta sia REGISTRATA (risposta != 404 'rotta_non_trovata'); auth/param
mancanti danno 401/400/422 (= rotta esiste, ok). Guard anti-drift se si rinomina una rotta.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

SEG = b"p" * 32
HK = {"X-Host-Key": "hk"}
AK = {"X-Admin-Key": "ak"}

# (pannello, metodo, path, headers) -- gli endpoint REALI estratti da deploy/*.html
ENDPOINT = [
    # index.html (ospite)
    ("index", "GET", "/api/catalogo", {}),
    ("index", "GET", "/api/catalogo/casa", {}),
    ("index", "POST", "/api/concierge/quote", {}),
    ("index", "POST", "/api/concierge/book", {}),
    ("index", "GET", "/api/i18n", {}),
    ("index", "POST", "/api/recensioni", {}),
    # host.html (pannello host)
    ("host", "POST", "/api/host/registrazione", {}),
    ("host", "POST", "/api/host/login", {}),
    ("host", "GET", "/api/host/alloggi", HK),
    ("host", "GET", "/api/host/calendario", HK),
    ("host", "POST", "/api/host/disponibilita", HK),
    ("host", "POST", "/api/host/disponibilita_range", HK),
    ("host", "POST", "/api/host/ical", HK),
    ("host", "GET", "/api/host/link_diretto", HK),
    ("host", "GET", "/api/host/metriche", HK),
    ("host", "GET", "/api/host/prezzo_suggerito", HK),
    ("host", "POST", "/api/host/pubblica", HK),
    ("host", "GET", "/api/host/referral", HK),
    ("host", "POST", "/api/host/stato", HK),
    ("host", "GET", "/api/host/export", HK),
    ("host", "POST", "/api/messaggi", HK),
    ("host", "GET", "/api/messaggi", HK),
    ("host", "GET", "/api/trasparenza", {}),
    # admin.html (pannello admin)
    ("admin", "GET", "/api/admin/prenotazioni", AK),
    ("admin", "POST", "/api/admin/rimborso", AK),
    ("admin", "POST", "/api/marketing/campagna", AK),
    ("admin", "POST", "/api/admin/cancella_attivita", AK),
    # voucher / cold-start / escrow garanzia (chiamati da pagine pubbliche)
    ("index", "POST", "/api/domanda", {}),
    ("index", "GET", "/api/domanda/conta", {}),
    ("voucher", "POST", "/api/concierge/cancella", {}),
    ("voucher", "POST", "/api/garanzia/conferma", {}),
    ("voucher", "POST", "/api/garanzia/contesta", {}),
    ("admin", "GET", "/api/garanzia/stato", AK),
    ("host", "GET", "/api/host/link_diretto", HK),
    ("host", "GET", "/api/host/richieste", HK),
    ("host", "POST", "/api/host/richieste/approva", HK),
    ("host", "POST", "/api/host/richieste/rifiuta", HK),
]


class TestPannelliContratto(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        d = cls.dir
        cls.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db",
            db_messaggi=f"{d}/m.db", file_referral=f"{d}/ref.json", commissione_bps=1500))
        cls.r = crea_router(cls.sis, host_key="hk", admin_key="ak",
                            base_url="https://bookinvip.com")
        # un alloggio pubblicato cosi' /api/catalogo/casa esiste davvero
        cls.r.gestisci("POST", "/api/host/pubblica", {}, json.dumps({
            "host_id": "demo", "slug": "casa", "titolo": "Casa", "citta": "Roma",
            "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
            "servizi": [], "immagini": []}), HK)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_ogni_endpoint_dei_pannelli_esiste(self):
        mancanti = []
        for pannello, metodo, path, hdr in ENDPOINT:
            st, corpo = self.r.gestisci(metodo, path, {}, "{}", hdr)
            corpo = corpo if isinstance(corpo, dict) else {}
            fantasma = (st == 404 and corpo.get("errore") == "rotta_non_trovata")
            if fantasma:
                mancanti.append("%s -> %s %s" % (pannello, metodo, path))
        self.assertEqual(mancanti, [], "rotte chiamate dai pannelli ma INESISTENTI: %s" % mancanti)


if __name__ == "__main__":
    unittest.main()
