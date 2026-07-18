"""Collaudo PERMESSI IN CONTEMPORANEA (punto 2): admin e host nello STESSO istante.

Il Layer-1 Dual-Persona copre gli ANNUNCI (sospendi/pubblica, IDOR, ultima parola).
Qui si colpisce dove non si era ancora sparato: admin e host che agiscono nello
stesso istante sulle stesse PRENOTAZIONI e sugli stessi SOLDI.

Tre scenari, invarianti fisici (non dichiarati):
  A. admin RIMBORSA ∥ host CANCELLA la stessa prenotazione PAGATA (x30, barrier):
     - mai 5xx; per ogni prenotazione ALMENO una delle due decisioni vince;
     - stato finale SOLO 'rimborsato' o 'cancellata_host' (mai 'pagato' residuo);
     - stanze liberate exactly-once: libere == 30 ESATTE (ri-prenotate a mano);
     - SOLDI IN SICUREZZA comunque finisca la gara: ledger tassa citta' == 0
       (stornata una volta sola), payout da_pagare == 0, e l'auto-rilascio escrow
       a +10 giorni NON bonifica NESSUNO (lista vuota = nessun host pagato su
       prenotazioni cancellate);
     - COERENZA PENALE: la penale 15% esiste SOLO se ha vinto l'host
       (stato 'cancellata_host'); una prenotazione chiusa dall'admin
       ('rimborsato') NON deve portare penale all'host.
  B. admin SOSPENDE l'annuncio ∥ 10 ospiti prenotano nello stesso istante:
     - mai 5xx; a bocce ferme prenotare e' IMPOSSIBILE (sospeso = sospeso);
     - alla ripubblicazione le unita' libere sono ESATTAMENTE 10 - (prenotazioni
       entrate durante la gara): nessuna unita' persa, nessuna inventata.
  C. DOPPIO CLICK sulla stessa decisione (2 admin-rimborso ∥ e 2 host-cancella ∥):
     - effetti exactly-once (tassa 0, penale al massimo una volta, stanza una volta);
     - il perdente riceve un esito onesto (409/200), mai un secondo effetto.
"""
import hashlib
import hmac
import json
import shutil
import tempfile
import threading
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, PENALE_HOST_BPS
from fase98_policy_commissione import commissione_cents

SEG = b"h" * 32
HK = {"X-Host-Key": "hk"}
AK = {"X-Admin-Key": "ak"}
WHSEC = "whsec_test"
CHECK_IN, CHECK_OUT = "2027-04-10", "2027-04-12"


class TestAdminHostStessoIstante(unittest.TestCase):
    def _sistema(self, unita):
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
               "da": "2027-04-01", "a": "2027-04-30", "unita_totali": unita,
               "prezzo_netto_cents": 10000}, HK)
        self._seq = 0

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    # ── attrezzi ────────────────────────────────────────────────────────────
    def _book(self):
        self._seq += 1
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "hotel",
                      "check_in": CHECK_IN, "check_out": CHECK_OUT, "party": 2})
        if not isinstance(q, dict) or not q.get("quote_token"):
            return None
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"],
                       "email": f"o{self._seq}@collaudo.invalid"})
        if s not in (200, 201) or not isinstance(b, dict):
            return None
        return b.get("riferimento")

    def _paga(self, rif):
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": rif}}}})
        ts = str(int(time.time()))
        mac = hmac.new(WHSEC.encode(), f"{ts}.{payload}".encode(),
                       hashlib.sha256).hexdigest()
        s, _ = self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})
        return s

    def _prenotazioni_pagate(self, n):
        rifs = []
        for _ in range(n):
            rif = self._book()
            self.assertIsNotNone(rif, "prenotazione iniziale fallita")
            self.assertEqual(self._paga(rif), 200)
            self.assertEqual(self.sis.pagamenti_pendenti.info(rif)["stato"], "pagato")
            rifs.append(rif)
        return rifs

    def _libere_contate_a_mano(self, tetto):
        conta = 0
        while conta < tetto and self._book():
            conta += 1
        return conta

    def _corpo(self, rif):
        rec = self.sis.pagamenti_pendenti.info(rif) or {}
        try:
            return rec.get("stato", "SPARITO"), json.loads(rec.get("corpo_json") or "{}")
        except Exception:
            return rec.get("stato", "SPARITO"), {}

    def _controlli_soldi_zero(self, msg):
        """Comunque sia finita la gara, NESSUNO deve poter incassare su cancellate:
        tassa citta' a 0, niente da_pagare, e il giro-bonifici a +10 giorni paga NESSUNO."""
        self.assertEqual(self.sis.tassa_comunale.totale_riscosso("Roma"), 0,
                         msg + ": tassa citta' deve tornare a 0 (stornata una volta sola)")
        self.assertEqual(self.sis.payout.da_pagare("demo", "EUR"), 0,
                         msg + ": nessun payout pagabile su prenotazioni cancellate")
        futuro = int(time.time()) + 10 * 24 * 3600
        bonifici = self.sis.garanzia.auto_rilascia(ora_ts=futuro, dettagli=True)
        self.assertEqual(bonifici, [],
                         msg + ": il giro-bonifici NON deve pagare nessuno, invece: %r" % (bonifici,))

    # ── scenario A: admin rimborsa ∥ host cancella (stessa prenotazione) ───
    def test_admin_rimborsa_mentre_host_cancella(self):
        N = 30
        self._sistema(unita=N)
        rifs = self._prenotazioni_pagate(N)
        pp = self.sis.pagamenti_pendenti
        via = threading.Barrier(2 * N)
        esiti, lock, errori = {}, threading.Lock(), []

        def admin(rif, idem):
            try:
                via.wait()
                s, _ = self.g("POST", "/api/admin/rimborso",
                              {"alloggio_id": "hotel", "check_in": CHECK_IN,
                               "check_out": CHECK_OUT, "idem_key": idem}, AK)
                with lock:
                    esiti[("A", rif)] = s
            except Exception as e:
                errori.append(repr(e))

        def host(rif):
            try:
                via.wait()
                s, _ = self.g("POST", "/api/host/cancella",
                              {"riferimento": rif, "host_id": "demo"}, HK)
                with lock:
                    esiti[("H", rif)] = s
            except Exception as e:
                errori.append(repr(e))

        ths = []
        for rif in rifs:
            idem = (pp.info(rif) or {}).get("idem_key") or ""
            ths.append(threading.Thread(target=admin, args=(rif, idem)))
            ths.append(threading.Thread(target=host, args=(rif,)))
        for t in ths:
            t.start()
        for t in ths:
            t.join(timeout=180)
        self.assertEqual(errori, [])
        for rif in rifs:
            sa, sh = esiti.get(("A", rif)), esiti.get(("H", rif))
            self.assertLess(sa, 500, f"{rif}: admin mai 5xx (avuto {sa})")
            self.assertLess(sh, 500, f"{rif}: host mai 5xx (avuto {sh})")
            self.assertTrue(sa == 200 or sh == 200,
                            f"{rif}: almeno UNA decisione deve vincere (admin={sa}, host={sh})")
            stato, corpo = self._corpo(rif)
            self.assertIn(stato, ("rimborsato", "cancellata_host"),
                          f"{rif}: stato finale illegale '{stato}'")
            penale = int(corpo.get("penale_host_cents", 0) or 0)
            if stato == "rimborsato":
                self.assertEqual(penale, 0,
                                 f"{rif}: chiusa dall'ADMIN ma penale host registrata "
                                 f"({penale} cents) = multa ingiusta sotto gara")
            else:
                attesa = commissione_cents(int(corpo.get("totale_cents", 0))
                                           or int(corpo.get("prezzo_guest_cents", 0)),
                                           PENALE_HOST_BPS)
                self.assertEqual(penale, attesa,
                                 f"{rif}: penale registrata {penale} != attesa {attesa}")
        libere = self._libere_contate_a_mano(N + 3)
        self.assertEqual(libere, N,
                         f"stanze liberate exactly-once: attese {N}, trovate {libere}")
        self._controlli_soldi_zero("scenario A")

    # ── scenario B: admin sospende ∥ 10 ospiti prenotano ───────────────────
    def test_admin_sospende_mentre_ospiti_prenotano(self):
        N = 10
        self._sistema(unita=N)
        via = threading.Barrier(N + 1)
        riusciti, lock, errori = [], threading.Lock(), []

        def ospite(i):
            try:
                via.wait()
                rif = self._book_thread(i)
                if rif:
                    with lock:
                        riusciti.append(rif)
            except Exception as e:
                errori.append(repr(e))

        def admin_sospende():
            try:
                via.wait()
                s, _ = self.g("POST", "/api/admin/alloggio_stato",
                              {"slug": "hotel", "stato": "sospeso"}, AK)
                self.assertIn(s, (200, 422))
            except Exception as e:
                errori.append(repr(e))

        ths = [threading.Thread(target=ospite, args=(i,)) for i in range(N)]
        ths.append(threading.Thread(target=admin_sospende))
        for t in ths:
            t.start()
        for t in ths:
            t.join(timeout=120)
        self.assertEqual(errori, [])
        # a bocce ferme: l'annuncio e' sospeso, prenotare DEVE essere impossibile
        self.assertIsNone(self._book_thread(999),
                          "annuncio SOSPESO ancora prenotabile dopo la gara")
        # ripubblico: le unita' libere devono essere ESATTAMENTE N - entrate in gara
        s, _ = self.g("POST", "/api/admin/alloggio_stato",
                      {"slug": "hotel", "stato": "pubblicato"}, AK)
        self.assertEqual(s, 200)
        attese = N - len(riusciti)
        libere = self._libere_contate_a_mano(N + 3)
        self.assertEqual(libere, attese,
                         f"unita' libere dopo ripubblicazione: attese {attese} "
                         f"(10 - {len(riusciti)} entrate in gara), trovate {libere}")

    def _book_thread(self, i):
        """Come _book ma con progressivo esplicito (thread-safe sull'email)."""
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "hotel",
                      "check_in": CHECK_IN, "check_out": CHECK_OUT, "party": 2})
        if not isinstance(q, dict) or not q.get("quote_token"):
            return None
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"],
                       "email": f"t{i}@collaudo.invalid"})
        if s not in (200, 201) or not isinstance(b, dict):
            return None
        return b.get("riferimento")

    # ── scenario C: doppio click sulla stessa decisione ────────────────────
    def test_doppio_click_stessa_decisione(self):
        N = 15
        self._sistema(unita=2 * N)
        rifs_admin = self._prenotazioni_pagate(N)
        rifs_host = self._prenotazioni_pagate(N)
        pp = self.sis.pagamenti_pendenti
        via = threading.Barrier(4 * N)
        errori = []

        def admin(idem):
            try:
                via.wait()
                s, _ = self.g("POST", "/api/admin/rimborso",
                              {"alloggio_id": "hotel", "check_in": CHECK_IN,
                               "check_out": CHECK_OUT, "idem_key": idem}, AK)
                assert s < 500
            except Exception as e:
                errori.append(repr(e))

        def host(rif):
            try:
                via.wait()
                s, _ = self.g("POST", "/api/host/cancella",
                              {"riferimento": rif, "host_id": "demo"}, HK)
                assert s < 500
            except Exception as e:
                errori.append(repr(e))

        ths = []
        for rif in rifs_admin:
            idem = (pp.info(rif) or {}).get("idem_key") or ""
            ths += [threading.Thread(target=admin, args=(idem,)),
                    threading.Thread(target=admin, args=(idem,))]
        for rif in rifs_host:
            ths += [threading.Thread(target=host, args=(rif,)),
                    threading.Thread(target=host, args=(rif,))]
        for t in ths:
            t.start()
        for t in ths:
            t.join(timeout=180)
        self.assertEqual(errori, [])
        for rif in rifs_admin:
            stato, corpo = self._corpo(rif)
            self.assertEqual(stato, "rimborsato", f"{rif}: doppio rimborso admin")
            self.assertEqual(int(corpo.get("penale_host_cents", 0) or 0), 0)
        for rif in rifs_host:
            stato, corpo = self._corpo(rif)
            self.assertEqual(stato, "cancellata_host", f"{rif}: doppio cancella host")
            attesa = commissione_cents(int(corpo.get("totale_cents", 0))
                                       or int(corpo.get("prezzo_guest_cents", 0)),
                                       PENALE_HOST_BPS)
            self.assertEqual(int(corpo.get("penale_host_cents", 0) or 0), attesa,
                             f"{rif}: la penale deve esserci UNA volta esatta")
        libere = self._libere_contate_a_mano(2 * N + 3)
        self.assertEqual(libere, 2 * N,
                         "doppio click: ogni stanza liberata UNA volta sola "
                         f"(attese {2*N}, trovate {libere})")
        self._controlli_soldi_zero("scenario C")


if __name__ == "__main__":
    unittest.main()
