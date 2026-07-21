"""Collaudo GIORNI-AFFITTO PER IMMOBILE nel report DAC7 (ultimo requisito UE).

La verità viene dal money-path (fase162): SOLO prenotazioni PAGATE, notti attribuite
all'anno del SOGGIORNO (un soggiorno a cavallo d'anno si divide fra i due anni).
Invarianti:
  1. prenotazione pagata dentro l'anno -> notti contate per alloggio;
  2. soggiorno A CAVALLO d'anno -> notti divise (dicembre al vecchio, gennaio al nuovo);
  3. rimborsata/cancellata NON conta (non è locazione); in_attesa NON conta;
  4. riga con data MALFORMATA -> saltata, il report non si rompe mai;
  5. input invalidi (host vuoto, anno assurdo) -> {} senza eccezioni;
  6. INTEGRAZIONE report: colonna notti_anno + dettaglio "titolo (città) - N notti/M pren";
     l'annuncio CANCELLATO con notti locate resta dichiarato (onestà fiscale).
"""
import datetime as dt
import hashlib
import hmac
import json
import shutil
import sqlite3
import tempfile
import time
import unittest

from fase162_pagamenti_pendenti import crea_pagamenti_pendenti


class TestNottiPerAlloggio(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.pp = crea_pagamenti_pendenti(f"{self.dir}/p.db")
        self.pp.inizializza_schema()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _pagata(self, rif, alloggio, ci, co, host="h1"):
        self.pp.registra(rif, alloggio_id=alloggio, check_in=ci, check_out=co,
                         idem_key="k" + rif, host_id=host)
        self.assertIsNotNone(self.pp.conferma(rif))          # in_attesa -> pagato

    def test_notti_dentro_anno(self):
        self._pagata("R1", "casa", "2026-08-10", "2026-08-12")   # 2 notti
        self._pagata("R2", "casa", "2026-09-01", "2026-09-04")   # 3 notti
        self._pagata("R3", "baita", "2026-12-01", "2026-12-02")  # 1 notte
        n = self.pp.notti_per_alloggio("h1", 2026)
        self.assertEqual(n["casa"], {"notti": 5, "pren": 2})
        self.assertEqual(n["baita"], {"notti": 1, "pren": 1})

    def test_cavallo_anno_si_divide(self):
        self._pagata("RX", "casa", "2026-12-30", "2027-01-02")   # 3 notti totali
        self.assertEqual(self.pp.notti_per_alloggio("h1", 2026)["casa"],
                         {"notti": 2, "pren": 1})                # 30 e 31 dicembre
        self.assertEqual(self.pp.notti_per_alloggio("h1", 2027)["casa"],
                         {"notti": 1, "pren": 1})                # 1 gennaio
        self.assertEqual(self.pp.notti_per_alloggio("h1", 2025), {})

    def test_solo_pagate_contano(self):
        self._pagata("RP", "casa", "2026-08-10", "2026-08-12")
        # rimborsata: pagata poi marcata da rimborsare -> esclusa
        self._pagata("RR", "casa", "2026-08-20", "2026-08-25")
        self.assertTrue(self.pp.marca_da_rimborsare("RR"))
        # cancellata dall'host: esclusa
        self._pagata("RC", "casa", "2026-09-10", "2026-09-15")
        self.assertTrue(self.pp.marca_cancellata_host("RC"))
        # mai pagata (in_attesa): esclusa
        self.pp.registra("RA", alloggio_id="casa", check_in="2026-10-01",
                         check_out="2026-10-05", idem_key="kRA", host_id="h1")
        self.assertEqual(self.pp.notti_per_alloggio("h1", 2026)["casa"],
                         {"notti": 2, "pren": 1})                # solo RP

    def test_data_malformata_non_rompe(self):
        self._pagata("ROK", "casa", "2026-08-10", "2026-08-12")
        # riga corrotta simulata (legacy/bug): infilata direttamente nel DB
        con = sqlite3.connect(f"{self.dir}/p.db")
        con.execute("INSERT INTO pendenti (riferimento, alloggio_id, check_in, check_out, "
                    "idem_key, stato, host_id, scadenza_ts, creato_ts) "
                    "VALUES ('RBAD','casa','garbage','peggio','kb','pagato','h1',0,0)")
        con.commit()
        con.close()
        self.assertEqual(self.pp.notti_per_alloggio("h1", 2026)["casa"],
                         {"notti": 2, "pren": 1})                # la rotta è saltata

    def test_input_invalidi(self):
        self.assertEqual(self.pp.notti_per_alloggio("", 2026), {})
        self.assertEqual(self.pp.notti_per_alloggio("h1", "duemila"), {})
        self.assertEqual(self.pp.notti_per_alloggio("h1", True), {})
        self.assertEqual(self.pp.notti_per_alloggio("h1", 999999), {})
        self.assertEqual(self.pp.notti_per_alloggio("sconosciuto", 2026), {})


class TestReportConNotti(unittest.TestCase):
    """Integrazione: il report DAC7 mostra notti_anno + dettaglio per immobile,
    con una prenotazione VERA pagata via webhook (money-path completo)."""

    WHSEC = "whsec_test"

    def setUp(self):
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase83_server import crea_router
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"h" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db", db_domanda=f"{d}/dom.db",
            db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_tassa_comunale=f"{d}/tc.db", db_finanza=f"{d}/fin.db",
            file_referral=f"{d}/ref.json",
            commissione_bps=1500, stripe_webhook_secret=self.WHSEC,
            bunker_password="SuperPw@1"))
        self.sis.concierge._link = lambda dati: "https://pay/" + str(dati.get("riferimento", ""))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        self.hid = self.sis.registro_host.registra("notti@collaudo.invalid", "password12",
                                                   accetta_termini=True).host_id
        hk = {"X-Host-Key": "hk"}
        # soggiorno FUTURO ma dentro l'anno corrente (oggi+20 .. oggi+22 = 2 notti)
        self.ci = (dt.date.today() + dt.timedelta(days=20)).isoformat()
        self.co = (dt.date.today() + dt.timedelta(days=22)).isoformat()
        self.anno = int(self.ci[:4])
        # NIENTE SALTO A FINE DICEMBRE. Prima, se `oggi+20` finiva nell'anno dopo, il
        # test si spegneva da solo — cioe' per una ventina di giorni all'anno la
        # verifica sul conteggio DAC7 (un obbligo fiscale) semplicemente non girava, e
        # nel rapporto compariva come «skipped». Non serviva: le asserzioni qui sotto
        # interrogano gia' `genera_dac7_csv(anno=self.anno)`, cioe' l'anno DELLA
        # PRENOTAZIONE, non quello corrente. Il salto copriva un problema che non c'era.
        g = lambda m, p, b: self.r.gestisci(m, p, {}, json.dumps(b), hk)
        g("POST", "/api/host/pubblica", {"host_id": self.hid, "slug": "casa", "titolo": "Villa",
          "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
          "servizi": [], "immagini": []})
        g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa",
          "da": (dt.date.today() + dt.timedelta(days=1)).isoformat(),
          "a": (dt.date.today() + dt.timedelta(days=60)).isoformat(),
          "unita_totali": 5, "prezzo_netto_cents": 10000})
        # sopra soglia DAC7 nell'anno corrente (incassi nel giornale)
        for i in range(3):
            self.sis.finanza.movimento(tipo="incasso", riferimento="V%d" % i,
                                       soggetto="host:" + self.hid, importo_cents=100000,
                                       valuta="EUR", causale="volume")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _prenota_paga(self, ci, co):
        _, q = self.r.gestisci("POST", "/api/concierge/quote", {},
                               json.dumps({"alloggio_id": "casa", "check_in": ci,
                                           "check_out": co, "party": 2}), {})
        _, b = self.r.gestisci("POST", "/api/concierge/book", {},
                               json.dumps({"quote_token": q["quote_token"],
                                           "email": "o@collaudo.invalid"}), {})
        rif = b["riferimento"]
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        ts = str(int(time.time()))
        mac = hmac.new(self.WHSEC.encode(), f"{ts}.{pl}".encode(), hashlib.sha256).hexdigest()
        s, _ = self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                               {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})
        self.assertEqual(s, 200)
        return rif

    def test_report_mostra_notti_per_immobile(self):
        self._prenota_paga(self.ci, self.co)                     # 2 notti pagate
        csv_txt = "".join(self.r.genera_dac7_csv(anno=self.anno, ip="t"))
        self.assertIn("notti_anno", csv_txt)                     # colonna nel header
        self.assertIn("Villa (Roma) - 2 notti/1 pren", csv_txt)  # dettaglio per immobile
        self.assertIn("# FINE REPORT DAC7 - INTEGRITÀ:", csv_txt)

    def test_rimborsata_non_conta_nel_report(self):
        self._prenota_paga(self.ci, self.co)                     # 2 notti valide
        # seconda prenotazione pagata poi CANCELLATA dall'host -> rimborso: notti escluse
        ci2 = (dt.date.today() + dt.timedelta(days=30)).isoformat()
        co2 = (dt.date.today() + dt.timedelta(days=35)).isoformat()
        rif2 = self._prenota_paga(ci2, co2)
        s, _ = self.r.gestisci("POST", "/api/host/cancella", {},
                               json.dumps({"riferimento": rif2, "host_id": self.hid}),
                               {"X-Host-Key": "hk"})
        self.assertEqual(s, 200)
        csv_txt = "".join(self.r.genera_dac7_csv(anno=self.anno, ip="t"))
        self.assertIn("Villa (Roma) - 2 notti/1 pren", csv_txt)  # SOLO le 2 valide
        self.assertNotIn("7 notti", csv_txt)


if __name__ == "__main__":
    unittest.main()
