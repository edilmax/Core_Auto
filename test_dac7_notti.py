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


def _banda(oggi):
    """Le date dei DUE soggiorni di prova, ancorate a `oggi` e mai cablate.

    Ritorna (check_in, check_out, check_in_2, check_out_2). Il secondo soggiorno e'
    quello che verra' cancellato: dura cinque notti, cosi' il totale PRIMA della
    cancellazione (sette) e' distinguibile da quello DOPO (due), e l'asserzione che
    pretende l'assenza delle sette notti ha qualcosa da distinguere invece di essere
    vera per caso.

    ⛔ TUTTE le notti devono cadere nell'anno CORRENTE, ed e' l'unico vincolo che conta.
    Il volume che rende l'host DICHIARABILE lo scrive il giornale, che si data da se'
    (`movimento()` non accetta un istante) e viene attribuito all'anno dell'incasso:
    percio' sta sempre nell'anno corrente. Una notte che cade nell'anno dopo non puo'
    comparire nel report chiesto qui, e il test marcirebbe da solo.
    Finche' l'ultima notte ci sta dentro si guarda AVANTI come sempre; nelle ultime
    settimane dell'anno, quando non ci sta piu', si guarda INDIETRO della stessa
    distanza. Un soggiorno gia' avvenuto attraversa lo stesso money-path -- preventivo,
    prenotazione, webhook, cancellazione con rimborso e nota di debito: misurato il
    2026-09-02 a orologio spostato, non supposto.
    """
    def _quattro(inizio):
        return (inizio, inizio + dt.timedelta(days=2),
                inizio + dt.timedelta(days=10), inizio + dt.timedelta(days=15))

    date = _quattro(oggi + dt.timedelta(days=20))
    # l'ultima notte e' il giorno prima del secondo check-out: si ricava dalle date
    # appena calcolate, cosi' nessun numero scritto due volte puo' diventare falso.
    if (date[3] - dt.timedelta(days=1)).year != oggi.year:
        date = _quattro(oggi - dt.timedelta(days=36))
    return date


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
        _ci, _co, _ci2, _co2 = _banda(dt.date.today())
        self.ci, self.co = _ci.isoformat(), _co.isoformat()
        self.ci2, self.co2 = _ci2.isoformat(), _co2.isoformat()
        self.anno = int(self.ci[:4])
        # NIENTE SALTO A FINE DICEMBRE, e quella decisione resta giusta: un test che si
        # spegne da solo per qualche settimana all'anno su un obbligo fiscale compare nel
        # rapporto come «skipped» e non protegge piu' niente.
        # ⛔ MA LA MOTIVAZIONE CHE STAVA SCRITTA QUI ERA FALSA, e va detta perche' e' la
        # ragione per cui il difetto e' rimasto. Diceva che il salto «copriva un problema
        # che non c'era», visto che le asserzioni interrogano gia' l'anno DELLA
        # PRENOTAZIONE. Il problema c'era, ed e' esattamente quello: l'anno della
        # prenotazione e' l'anno in cui stanno le NOTTI, ma il volume che rende l'host
        # dichiarabile lo data il giornale, cioe' l'anno CORRENTE. Quando i due anni si
        # separano il report non puo' mostrare le notti in nessuno dei due.
        # Misurato il 2026-09-02 a orologio spostato: ROSSO dall'11 al 31 dicembre, e
        # MUTO -- verde senza verificare niente -- dal 28 novembre al 10 dicembre.
        # La risposta non e' il salto: e' `_banda`, che i due anni non li separa mai.
        g = lambda m, p, b: self.r.gestisci(m, p, {}, json.dumps(b), hk)
        g("POST", "/api/host/pubblica", {"host_id": self.hid, "slug": "casa", "titolo": "Villa",
          "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
          "servizi": [], "immagini": []})
        # la finestra copre la banda ANCHE quando guarda indietro, altrimenti a dicembre
        # il preventivo non troverebbe le date e il rosso sarebbe dell'apparecchio
        g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa",
          "da": min(_ci, dt.date.today() + dt.timedelta(days=1)).isoformat(),
          "a": max(_co2, dt.date.today() + dt.timedelta(days=60)).isoformat(),
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
        rif2 = self._prenota_paga(self.ci2, self.co2)
        s, _ = self.r.gestisci("POST", "/api/host/cancella", {},
                               json.dumps({"riferimento": rif2, "host_id": self.hid}),
                               {"X-Host-Key": "hk"})
        self.assertEqual(s, 200)
        csv_txt = "".join(self.r.genera_dac7_csv(anno=self.anno, ip="t"))
        self.assertIn("Villa (Roma) - 2 notti/1 pren", csv_txt)  # SOLO le 2 valide
        self.assertNotIn("7 notti", csv_txt)


class TestLaBandaDelleProve(unittest.TestCase):
    """La guardia della riparazione: le date di prova qui sopra non devono marcire.

    ⛔ IL DIFETTO CHE IMPEDISCE, misurato e non ipotizzato. `finanza.movimento()` non
    accetta un istante (il giornale e' hash-incatenato e si data da se'), e
    `aggrega_dac7` attribuisce all'anno dell'INCASSO: il volume che rende l'host
    DICHIARABILE finisce percio' sempre nell'anno CORRENTE. Se una notte di prova cade
    nell'anno dopo, il report chiesto per l'anno del check-in non puo' mostrarla, e
    succede in DUE modi diversi, tutti e due letti nell'uscita vera:
      · soggiorno a cavallo del capodanno -> le notti si dividono fra i due anni
        (l'invariante 2, quella che `test_cavallo_anno_si_divide` pretende), e nell'anno
        chiesto ne resta una sola: «Villa (Roma) - 1 notti/1 pren»;
      · soggiorno tutto nell'anno dopo -> in quell'anno l'host non ha volume, quindi non
        e' dichiarabile e la sua riga non esiste affatto: «# host_reportabili,0».

    ⛔ E SI PROVA SU TUTTI I GIORNI DELL'ANNO, NON SU OGGI. Una guardia che puo' fallire
    soltanto in tre settimane di dicembre resta spenta per undici mesi, ed e' proprio la
    forma del difetto che stiamo chiudendo: lo stato scomodo si costruisce adesso, non si
    aspetta il giorno in cui capita da solo (D19).
    """

    def test_LE_NOTTI_DI_PROVA_STANNO_NELL_ANNO_CHE_IL_GIORNALE_DATA(self):
        for anno in (2026, 2027, 2028):                      # 2028 e' bisestile
            giorno, fine = dt.date(anno, 1, 1), dt.date(anno, 12, 31)
            while giorno <= fine:
                ci, co, ci2, co2 = _banda(giorno)
                notti = ([ci + dt.timedelta(days=i) for i in range((co - ci).days)] +
                         [ci2 + dt.timedelta(days=i) for i in range((co2 - ci2).days)])
                fuori = [n.isoformat() for n in notti if n.year != giorno.year]
                self.assertEqual(
                    fuori, [],
                    "con oggi=%s il report viene chiesto per l'anno %d, ma queste notti "
                    "cadono in un altro anno: %s. Il volume che rende l'host "
                    "dichiarabile lo data il giornale, quindi sta SEMPRE nell'anno "
                    "corrente: una notte fuori da quell'anno non puo' comparire nel "
                    "report." % (giorno.isoformat(), giorno.year, fuori))
                # i due soggiorni non si sovrappongono e il secondo pesa davvero:
                # senza questo, «7 notti prima / 2 dopo» smetterebbe di distinguere
                # qualcosa e l'asserzione che le esclude sarebbe vera per caso (S7).
                self.assertGreaterEqual(ci2, co, "i due soggiorni si sovrappongono")
                self.assertGreater((co2 - ci2).days, 0, "il secondo soggiorno e' vuoto")
                giorno += dt.timedelta(days=1)


if __name__ == "__main__":
    unittest.main()
