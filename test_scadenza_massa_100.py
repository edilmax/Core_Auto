"""Collaudo INTEGRITA' PROFONDA: 100 prenotazioni che scadono nello STESSO istante.

Invariante da difendere (punto 1 del collaudo finale): quando gli hold non pagati
scadono TUTTI insieme, le stanze si liberano SEMPRE — nessuna resta bloccata per
sempre, nessuna viene liberata due volte (il doppio-rilascio gonfierebbe la
capacita' = overbooking), e chi paga sul filo del traguardo tiene la stanza.

Tre prove sullo STESSO scenario (1 alloggio x 100 unita', 100 hold sulle stesse notti):
  1. sweep singolo            -> 100 su 100 tornano libere, ne' una di piu' ne' una di meno;
  2. sciame di 8 spazzini     -> rilascio exactly-once anche sotto gara tra sweeper;
  3. pagamenti VS spazzino    -> ogni prenotazione finisce in UNO solo dei destini legali
                                 (pagata+stanza occupata | scaduta+stanza libera |
                                 rimborsata+stanza libera), mai 'in_attesa' per sempre,
                                 e le stanze libere sono ESATTAMENTE 100 - pagate.

Il conteggio delle stanze libere e' fisico, non dichiarato: si ri-prenota davvero
finche' il motore dice basta (la 101ª deve SEMPRE fallire = capacita' mai gonfiata)."""
import hashlib
import hmac
import json
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, sweep_hold_una_passata

SEG = b"h" * 32
HK = {"X-Host-Key": "hk"}
WHSEC = "whsec_test"
N = 100
CHECK_IN, CHECK_OUT = "2027-03-10", "2027-03-12"


class TestScadenzaMassa(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.db_pendenti = f"{d}/p.db"
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db", db_domanda=f"{d}/dom.db",
            db_garanzia=f"{d}/g.db", db_pendenti=self.db_pendenti,
            db_tassa_comunale=f"{d}/tc.db", file_referral=f"{d}/ref.json",
            commissione_bps=1500, stripe_webhook_secret=WHSEC))
        # Stripe "configurato" finto -> attiva il percorso HOLD (in_attesa_pagamento)
        self.sis.concierge._link = lambda dati: "https://pay/" + str(dati.get("riferimento", ""))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "hotel",
               "titolo": "H", "citta": "Roma", "descrizione": "x",
               "prezzo_notte_cents": 10000, "capacita": 2, "servizi": [], "immagini": [],
               "tassa_pp_notte_cents": 200}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "hotel",
               "da": "2027-03-01", "a": "2027-03-31", "unita_totali": N,
               "prezzo_netto_cents": 10000}, HK)
        self._seq = 0

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    # ── attrezzi ────────────────────────────────────────────────────────────
    def _book(self):
        """Una prenotazione VERA via API (quote+book). Ritorna il riferimento o None."""
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

    def _cento_hold(self):
        rifs = [self._book() for _ in range(N)]
        rifs = [r for r in rifs if r]
        self.assertEqual(len(rifs), N, "le 100 prenotazioni iniziali devono riuscire tutte")
        self.assertEqual(len(set(rifs)), N, "riferimenti tutti distinti")
        return rifs

    def _scadenza_simultanea(self):
        """Tutti gli hold in_attesa scadono nello STESSO istante (retrodata la sola
        scadenza_ts; creato_ts resta vero, cosi' l'housekeeping 26h non li tocca)."""
        con = sqlite3.connect(self.db_pendenti)
        try:
            with con:
                cur = con.execute(
                    "UPDATE pendenti SET scadenza_ts=1 WHERE stato='in_attesa'")
            return cur.rowcount
        finally:
            con.close()

    def _paga(self, rif):
        """Webhook Stripe firmato (checkout.session.completed). Ritorna lo status HTTP."""
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": rif}}}})
        ts = str(int(time.time()))
        mac = hmac.new(WHSEC.encode(), f"{ts}.{payload}".encode(),
                       hashlib.sha256).hexdigest()
        s, _ = self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})
        return s

    def _stanze_libere_contate_a_mano(self, tetto=N + 5):
        """Conta le unita' libere PRENOTANDO davvero finche' il motore dice basta.
        E' la prova fisica: se un rilascio e' andato perso una stanza resta bloccata
        (conta < atteso); se un rilascio e' doppio la capacita' si gonfia (conta > atteso)."""
        conta = 0
        while conta < tetto and self._book():
            conta += 1
        return conta

    def _stati(self, rifs):
        pp = self.sis.pagamenti_pendenti
        out = {}
        for rif in rifs:
            rec = pp.info(rif)
            out[rif] = rec["stato"] if rec else "SPARITO"
        return out

    # ── prova 1: sweep singolo, 100 scadenze simultanee ─────────────────────
    def test_sweep_libera_tutte_e_100(self):
        rifs = self._cento_hold()
        self.assertEqual(self._scadenza_simultanea(), N)
        sweep_hold_una_passata(self.sis, self.r)
        stati = self._stati(rifs)
        self.assertEqual([s for s in stati.values() if s != "scaduto"], [],
                         f"tutte 'scaduto', trovato: {stati}")
        libere = self._stanze_libere_contate_a_mano()
        self.assertEqual(libere, N, "dopo lo sweep le stanze libere devono essere "
                                    f"ESATTAMENTE {N} (trovate {libere})")

    # ── prova 2: sciame di 8 spazzini in gara sugli stessi 100 record ──────
    def test_otto_spazzini_concorrenti_rilascio_exactly_once(self):
        rifs = self._cento_hold()
        self.assertEqual(self._scadenza_simultanea(), N)
        n_thread = 8
        via = threading.Barrier(n_thread)
        errori = []

        def spazzino():
            try:
                via.wait()
                sweep_hold_una_passata(self.sis, self.r)
            except Exception as e:      # lo sweep non deve MAI esplodere
                errori.append(repr(e))

        ths = [threading.Thread(target=spazzino) for _ in range(n_thread)]
        for t in ths:
            t.start()
        for t in ths:
            t.join(timeout=120)
        self.assertEqual(errori, [])
        stati = self._stati(rifs)
        self.assertEqual([s for s in stati.values() if s != "scaduto"], [],
                         f"tutte 'scaduto', trovato: {stati}")
        libere = self._stanze_libere_contate_a_mano()
        self.assertEqual(libere, N, "8 spazzini in gara: rilascio exactly-once, "
                                    f"libere attese {N}, trovate {libere}")

    # ── prova 3: pagamenti sul filo VS spazzino ─────────────────────────────
    def test_gara_pagamenti_contro_spazzino(self):
        rifs = self._cento_hold()
        self.assertEqual(self._scadenza_simultanea(), N)
        paganti = rifs[::2]                       # 50 clienti pagano sul filo
        n_sweeper = 4
        via = threading.Barrier(n_sweeper + len(paganti))
        errori, esiti_webhook = [], {}

        def spazzino():
            try:
                via.wait()
                sweep_hold_una_passata(self.sis, self.r)
            except Exception as e:
                errori.append(repr(e))

        def cliente(rif):
            try:
                via.wait()
                esiti_webhook[rif] = self._paga(rif)
            except Exception as e:
                errori.append(repr(e))

        ths = ([threading.Thread(target=spazzino) for _ in range(n_sweeper)]
               + [threading.Thread(target=cliente, args=(rif,)) for rif in paganti])
        for t in ths:
            t.start()
        for t in ths:
            t.join(timeout=180)
        self.assertEqual(errori, [])
        self.assertEqual({s for s in esiti_webhook.values()}, {200},
                         "il webhook risponde SEMPRE 200 (Stripe non deve ritentare)")
        stati = self._stati(rifs)
        illegali = {r: s for r, s in stati.items()
                    if s not in ("pagato", "scaduto", "rimborsato")}
        self.assertEqual(illegali, {}, "destini legali: pagato|scaduto|rimborsato "
                                       f"(mai in_attesa per sempre): {illegali}")
        # chi NON ha pagato non puo' che essere 'scaduto'
        non_paganti = set(rifs) - set(paganti)
        self.assertEqual({stati[r] for r in non_paganti}, {"scaduto"})
        pagate = sum(1 for s in stati.values() if s == "pagato")
        libere = self._stanze_libere_contate_a_mano()
        self.assertEqual(libere, N - pagate,
                         f"conservazione stanze: libere({libere}) deve essere "
                         f"{N}-pagate({pagate}); stati={sorted(stati.values())}")


if __name__ == "__main__":
    unittest.main()
