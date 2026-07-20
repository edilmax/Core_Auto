"""RAMPA DI LANCIO end-to-end (BUG 2026-07-20: la promo 0% non e' MAI stata applicata).

Cosa era rotto (provato con una prenotazione vera, non a lettura):
  `fase81._comm_alloggio` chiedeva il proprietario a `catalogo.dettaglio(slug)["host_id"]`,
  ma il dettaglio PUBBLICO non espone l'host (dato privato, by design) -> `hid` era SEMPRE
  None -> il ramo della rampa non veniva mai eseguito -> si ripiegava sul 10% a regime.
  Quindi: host registrato OGGI, promo ACCESA -> pagava 10% invece di 0%.

Perche' nessuna guardia lo prendeva:
  - `test_promo_lancio` prova la FORMULA da sola (commissione_bps_lancio(0)==0): verde.
  - `test_trasparenza_coerenza` prova la PAGINA trasparenza, che risolve l'host dal TOKEN
    (strada diversa): verde. Risultato: la piattaforma MOSTRAVA 0% e ADDEBITAVA 10%.
  Mancava la prova sul percorso vero: quote -> commissione applicata.

Guardie di questo compartimento (ROSSE sul codice vecchio):
  - MACRO: prenotazione reale a piu' eta' dell'host -> 0% / 8% / 10% agli scaglioni esatti.
  - CONTRADDIZIONE: cio' che la trasparenza MOSTRA == cio' che il preventivo ADDEBITA.
  - CANALE DIRETTO: 5% a qualunque eta' (la rampa non lo tocca).
  - INVARIANTE SOLDI: ospite == host + commissione + tariffa tecnica, a ogni eta'.
  - FAIL-SAFE: promo spenta o proprietario ignoto -> 10% a regime (mai 0% per errore).
"""
import datetime
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

PSP_BPS = 300          # 3% tariffa tecnica, come in produzione
PREZZO = 10000         # 100.00 EUR / notte


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://x/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


class BasePromo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def _sistema(self, promo=True, bps=1000):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        os.environ["UPLOAD_DIR"] = f"{d}/uploads"
        self.db_reg = f"{d}/r.db"
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=self.db_reg,
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_messaggi=f"{d}/m.db",
            db_garanzia=f"{d}/g.db", db_recensioni=f"{d}/rec.db",
            commissione_bps=bps, psp_bps=PSP_BPS, promo_lancio_attiva=promo,
            stripe_secret_key="sk", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")
        return sis, r

    def _g(self, r, m, p, b=None, h=None):
        return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _host_con_alloggio(self, r, email="h@promo.local", slug="casa"):
        s, c = self._g(r, "POST", "/api/host/registrazione",
                       {"email": email, "password": "password1", "accetta_termini": True,
                        "accetta_clausole": True, "doc_sha256": doc_sha256(),
                        "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        tk = {"X-Host-Token": c["token"]}
        oggi = datetime.date.today()
        s, o = self._g(r, "POST", "/api/host/pubblica",
                       {"slug": slug, "titolo": "Casa promo", "citta": "Roma",
                        "prezzo_notte_cents": PREZZO, "capacita": 4}, tk)
        self.assertEqual(s, 201, o)
        self._g(r, "POST", "/api/host/disponibilita_range",
                {"alloggio_id": slug, "da": oggi.isoformat(),
                 "a": (oggi + datetime.timedelta(days=20)).isoformat(),
                 "unita_totali": 5, "prezzo_netto_cents": PREZZO}, tk)
        return c["host_id"], tk

    def _invecchia(self, host_id, giorni):
        """Sposta indietro la data di registrazione: simula un host di N giorni."""
        import time
        con = sqlite3.connect(self.db_reg)
        try:
            con.execute("UPDATE host SET creato_ts=? WHERE host_id=?",
                        (int(time.time()) - giorni * 86400 - 60, str(host_id)))
            con.commit()
        finally:
            con.close()

    def _quote(self, r, fonte="marketplace", slug="casa", giorni_avanti=3):
        oggi = datetime.date.today()
        ci = (oggi + datetime.timedelta(days=giorni_avanti)).isoformat()
        co = (oggi + datetime.timedelta(days=giorni_avanti + 1)).isoformat()
        s, q = self._g(r, "POST", "/api/concierge/quote",
                       {"alloggio_id": slug, "check_in": ci, "check_out": co,
                        "party": 2, "fonte": fonte})
        self.assertEqual(s, 200, q)
        return q


class TestRampaSuPrenotazioneVera(BasePromo):
    """MACRO: la commissione DAVVERO applicata a una prenotazione, per eta' dell'host."""

    def test_scaglioni_esatti_end_to_end(self):
        sis, r = self._sistema(promo=True)
        hid, _tk = self._host_con_alloggio(r)
        attesi = [(0, 0), (1, 0), (45, 0), (89, 0),          # primi 90 giorni -> 0%
                  (90, 800), (200, 800), (364, 800),          # fino a 1 anno -> 8%
                  (365, 1000), (500, 1000), (2000, 1000)]     # oltre -> 10% a regime
        for giorni, bps in attesi:
            self._invecchia(hid, giorni)
            q = self._quote(r)
            atteso_cents = PREZZO * bps // 10000
            self.assertEqual(q["commissione_cents"], atteso_cents,
                             "host di %d giorni: attesa commissione %d bps (%d cent), "
                             "ottenuti %d cent" % (giorni, bps, atteso_cents,
                                                   q["commissione_cents"]))

    def test_promo_giorno_zero_azzera_davvero_la_commissione(self):
        """Il caso che era ROTTO: host di oggi -> 0 di commissione, resta solo il 3%."""
        sis, r = self._sistema(promo=True)
        hid, _tk = self._host_con_alloggio(r)
        self._invecchia(hid, 0)
        q = self._quote(r)
        self.assertEqual(q["commissione_cents"], 0, "la promo 0% non e' stata applicata!")
        self.assertEqual(q["costo_pagamento_cents"], PREZZO * PSP_BPS // 10000)
        # l'host tiene tutto MENO la sola tariffa tecnica
        self.assertEqual(q["netto_host_cents"], PREZZO - (PREZZO * PSP_BPS // 10000))

    def test_invariante_soldi_a_ogni_eta(self):
        """ospite == host + commissione + tariffa tecnica, sempre, a ogni scaglione."""
        sis, r = self._sistema(promo=True)
        hid, _tk = self._host_con_alloggio(r)
        for giorni in (0, 89, 90, 364, 365, 900):
            self._invecchia(hid, giorni)
            for fonte in ("marketplace", "diretto"):
                q = self._quote(r, fonte=fonte)
                self.assertEqual(
                    q["prezzo_guest_cents"],
                    q["netto_host_cents"] + q["commissione_cents"] + q["costo_pagamento_cents"],
                    "identita' rotta a %d giorni sul canale %s" % (giorni, fonte))
                self.assertGreaterEqual(q["netto_host_cents"], 0)
                self.assertGreater(q["costo_pagamento_cents"], 0,
                                   "tariffa tecnica sparita a %d giorni (%s)" % (giorni, fonte))


class TestCanaleDiretto(BasePromo):
    def test_diretto_sempre_5_percento_piu_3(self):
        """Il canale diretto non e' toccato dalla rampa: 5% + 3% = 8% a qualunque eta'."""
        sis, r = self._sistema(promo=True)
        hid, _tk = self._host_con_alloggio(r)
        for giorni in (0, 89, 90, 365, 1000):
            self._invecchia(hid, giorni)
            q = self._quote(r, fonte="diretto")
            self.assertEqual(q["commissione_cents"], PREZZO * 500 // 10000,
                             "diretto a %d giorni: dovrebbe essere 5%%" % giorni)
            self.assertEqual(q["costo_pagamento_cents"], PREZZO * PSP_BPS // 10000)
            self.assertEqual(q["netto_host_cents"], PREZZO - 500 - 300)   # 92.00 su 100.00


class TestNienteContraddizione(BasePromo):
    """La piattaforma MOSTRAVA 0% e ADDEBITAVA 10%: le due strade devono coincidere."""

    def test_trasparenza_mostrata_uguale_a_quella_addebitata(self):
        sis, r = self._sistema(promo=True)
        hid, tk = self._host_con_alloggio(r)
        for giorni in (0, 45, 90, 365):
            self._invecchia(hid, giorni)
            s, c = r.gestisci("GET", "/api/trasparenza",
                              {"prezzo_cents": str(PREZZO), "ota": "booking"}, None, tk)
            self.assertEqual(s, 200, c)
            mostrata = c["scenario_nostro"]["commissione_cents"]
            addebitata = self._quote(r)["commissione_cents"]
            self.assertEqual(mostrata, addebitata,
                             "a %d giorni la trasparenza mostra %d ma il preventivo addebita "
                             "%d: la piattaforma promette una cosa e ne fa un'altra"
                             % (giorni, mostrata, addebitata))


class TestFailSafe(BasePromo):
    def test_promo_spenta_sempre_regime(self):
        sis, r = self._sistema(promo=False)
        hid, _tk = self._host_con_alloggio(r)
        for giorni in (0, 45, 400):
            self._invecchia(hid, giorni)
            self.assertEqual(self._quote(r)["commissione_cents"], PREZZO * 1000 // 10000,
                             "promo SPENTA: deve restare il 10% a regime")

    def test_commissione_configurata_diversa_rispettata(self):
        """Con promo spenta e COMMISSIONE_BPS=15%, si applica il 15% (nessun 10% fisso)."""
        sis, r = self._sistema(promo=False, bps=1500)
        self._host_con_alloggio(r)
        self.assertEqual(self._quote(r)["commissione_cents"], PREZZO * 1500 // 10000)

    def test_rampa_finisce_sulla_commissione_configurata(self):
        """2° FIX 2026-07-20: la rampa terminava su un 10% FISSO ignorando COMMISSIONE_BPS.
        Con promo ON e config 15%, un host oltre l'anno pagava 10% -> impostazione ignorata
        in silenzio (ricavo perso). Ora la rampa finisce sul regime CONFIGURATO e la fase
        intermedia non lo supera mai (monotonia garantita)."""
        sis, r = self._sistema(promo=True, bps=1500)
        hid, _tk = self._host_con_alloggio(r)
        for giorni, bps in ((0, 0), (89, 0), (90, 800), (364, 800), (365, 1500), (900, 1500)):
            self._invecchia(hid, giorni)
            self.assertEqual(self._quote(r)["commissione_cents"], PREZZO * bps // 10000,
                             "promo+config 15%%: a %d giorni attesi %d bps" % (giorni, bps))
        # regime PIU' BASSO della fase intermedia: la rampa non deve mai superare il regime
        sis2, r2 = self._sistema(promo=True, bps=500)
        hid2, _tk2 = self._host_con_alloggio(r2, email="basso@promo.local", slug="casa2")
        for giorni in (90, 364, 365, 900):
            self._invecchia(hid2, giorni)
            self.assertLessEqual(self._quote(r2, slug="casa2")["commissione_cents"],
                                 PREZZO * 500 // 10000,
                                 "a %d giorni la rampa supera il regime configurato" % giorni)

    def test_host_ignoto_non_regala_lo_zero(self):
        """Se il proprietario non e' risolvibile, si ripiega sul regime: mai 0% per errore."""
        sis, r = self._sistema(promo=True)
        hid, tk = self._host_con_alloggio(r)
        self._invecchia(hid, 0)
        # rimuovo l'host dal registro: l'anzianita' diventa ignota
        con = sqlite3.connect(self.db_reg)
        try:
            con.execute("DELETE FROM host WHERE host_id=?", (hid,))
            con.commit()
        finally:
            con.close()
        q = self._quote(r)
        self.assertEqual(q["commissione_cents"], PREZZO * 1000 // 10000,
                         "host ignoto: deve valere il regime 10%, non lo 0% della promo")


if __name__ == "__main__":
    unittest.main()
