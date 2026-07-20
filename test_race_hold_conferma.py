"""
Collaudo GARA sweeper <-> conferma pagamento ("hold scaduto MENTRE l'ospite paga").

BUG (trovato in FASE 1 caccia-bug, 2026-07-15): lo sweeper liberava le date PRIMA
del CAS 'scaduto', e `conferma` scriveva 'pagato' senza guardare lo stato (decisione
presa su una lettura vecchia). Interleaving fatale: webhook legge 'in_attesa' ->
sweeper libera le date e manda l'email "riprova" -> conferma scrive 'pagato' =
cliente PAGATO con date LIBERATE (doppia prenotazione possibile).

FIX blindato qui:
- fase162.conferma = CAS atomico (BEGIN IMMEDIATE) solo da in_attesa/scaduto,
  ritorna lo stato PRECEDENTE (il ramo si decide DOPO l'acquisizione);
- sweeper (fase83.sweep_hold_una_passata) = CAS-first: date/garanzia/payout/email
  SOLO se `scadi` riesce; se il pagamento ha vinto, non tocca niente.
"""
import json
import shutil
import tempfile
import threading
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, sweep_hold_una_passata
from fase162_pagamenti_pendenti import crea_pagamenti_pendenti
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

CI, CO = "2026-09-01", "2026-09-02"


class TestCasFase162(unittest.TestCase):
    def setUp(self):
        # DB su FILE come in produzione: ogni chiamata apre la SUA connessione ->
        # la semantica CAS multi-thread è quella vera (il ':memory:' condiviso
        # mescola le transazioni dei thread sulla stessa connessione).
        self.dir = tempfile.mkdtemp()
        self.pp = crea_pagamenti_pendenti(f"{self.dir}/p.db")
        self.pp.inizializza_schema()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _nuovo(self, rif="R1"):
        self.pp.registra(rif, alloggio_id="casa", check_in=CI, check_out=CO,
                         idem_key="hold_" + rif, scadenza_ts=int(time.time()) - 10)

    def test_conferma_ritorna_stato_precedente(self):
        self._nuovo()
        r = self.pp.conferma("R1")
        self.assertEqual(r["stato"], "in_attesa", "deve ritornare lo stato PRIMA del CAS")
        self.assertEqual(self.pp.info("R1")["stato"], "pagato")
        r2 = self.pp.conferma("R1")                      # webhook duplicato
        self.assertEqual(r2["stato"], "pagato", "duplicato riconoscibile dal chiamante")
        self.assertEqual(self.pp.info("R1")["stato"], "pagato")

    def test_conferma_non_tocca_stati_non_confermabili(self):
        self._nuovo("R2")
        self.pp.marca_cancellata_host("R2")
        r = self.pp.conferma("R2")
        self.assertEqual(r["stato"], "cancellata_host")
        self.assertEqual(self.pp.info("R2")["stato"], "cancellata_host",
                         "pagamento su cancellata NON deve diventare 'pagato'")

    def test_scadi_perde_contro_conferma(self):
        self._nuovo("R3")
        self.pp.conferma("R3")
        self.assertFalse(self.pp.scadi("R3"), "record pagato: lo sweeper non lo possiede")

    def test_martello_concorrente_un_solo_vincitore(self):
        # 60 giri: conferma e scadi SIMULTANEI sullo stesso record. Invariante:
        # scadi True <=> la conferma ha visto 'scaduto' (e quindi sa di dover ri-bloccare).
        for i in range(60):
            rif = "G%d" % i
            self._nuovo(rif)
            esiti = {}
            b = threading.Barrier(2)

            def paga():
                b.wait()
                esiti["prev"] = (self.pp.conferma(rif) or {}).get("stato")

            def scade():
                b.wait()
                esiti["scadi"] = self.pp.scadi(rif)

            t1, t2 = threading.Thread(target=paga), threading.Thread(target=scade)
            t1.start(); t2.start(); t1.join(); t2.join()
            if esiti["scadi"]:
                self.assertEqual(esiti["prev"], "scaduto",
                                 "giro %d: sweeper ha vinto -> la conferma DEVE saperlo" % i)
            else:
                self.assertEqual(esiti["prev"], "in_attesa",
                                 "giro %d: conferma ha vinto -> scadi deve fallire" % i)
            self.assertEqual(self.pp.info(rif)["stato"], "pagato",
                             "in entrambi i casi il pagamento vince alla fine (re-block a parte)")


class _PPTrappola:
    """Wrapper: il pagamento arriva ESATTAMENTE tra lo snapshot dello sweeper
    (scaduti) e la sua azione — l'interleaving reale, reso deterministico."""

    def __init__(self, vero, al_snapshot):
        self._vero = vero
        self._al_snapshot = al_snapshot

    def scaduti(self, **kw):
        righe = self._vero.scaduti(**kw)
        if righe:
            self._al_snapshot()
        return righe

    def __getattr__(self, nome):
        return getattr(self._vero, nome)


class TestGaraSweeperConferma(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/a.db"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@race.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.tok = c["token"]
        s, r = self.g("POST", "/api/host/pubblica",
                      {"slug": "casa-race", "titolo": "Race", "citta": "Roma",
                       "prezzo_notte_cents": 9000, "capacita": 2}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 201, r)
        for gio in (CI, CO):
            self.g("POST", "/api/host/disponibilita",
                   {"alloggio_id": "casa-race", "giorno": gio, "unita_totali": 1,
                    "prezzo_netto_cents": 9000}, {"X-Host-Token": self.tok})
        self.pp = crea_pagamenti_pendenti(":memory:")
        self.pp.inizializza_schema()
        self.sys.pagamenti_pendenti = self.pp
        # niente email vere: registro solo le chiamate al recupero
        self.recuperi = []
        self.r._email_recupero_hold = lambda rec: self.recuperi.append(rec["riferimento"])

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, metodo, path, body=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None, headers or {})

    def _hold_scaduto(self, rif):
        """Stanza bloccata + record hold con scadenza già passata (non pagato in tempo)."""
        e = self.sys.inventario.blocca("casa-race", CI, CO, idem_key="hold_" + rif)
        self.assertTrue(e.ok, getattr(e, "errore", ""))
        self.pp.registra(rif, alloggio_id="casa-race", check_in=CI, check_out=CO,
                         idem_key="hold_" + rif, scadenza_ts=int(time.time()) - 10)

    def _date_libere(self):
        e = self.sys.inventario.blocca("casa-race", CI, CO, idem_key="sonda_" + str(time.time()))
        if e.ok:   # la sonda ha preso la stanza: era libera -> la rilascio subito
            self.sys.inventario.rilascia("casa-race", CI, CO,
                                         idem_key=e.idem_key if hasattr(e, "idem_key") else "")
            return True
        return False

    def test_pagamento_durante_lo_sweep_non_perde_la_stanza(self):
        # IL CASO DEL BUG: il webhook arriva tra lo snapshot dello sweeper e la sua azione.
        self._hold_scaduto("RACE1")
        trappola = _PPTrappola(self.pp, lambda: self.r._conferma_pagamento("RACE1"))
        self.sys.pagamenti_pendenti = trappola
        sweep_hold_una_passata(self.sys, self.r)
        self.sys.pagamenti_pendenti = self.pp
        self.assertEqual(self.pp.info("RACE1")["stato"], "pagato")
        sonda = self.sys.inventario.blocca("casa-race", CI, CO, idem_key="ladro")
        self.assertFalse(sonda.ok,
                         "BUG: date liberate su prenotazione PAGATA (doppia prenotazione!)")
        self.assertEqual(self.recuperi, [],
                         "niente email 'riprova' a chi ha appena pagato")

    def test_sweep_normale_libera_e_avvisa(self):
        # senza pagamento: lo sweep deve liberare le date, marcare 'scaduto', avvisare.
        self._hold_scaduto("RACE2")
        sweep_hold_una_passata(self.sys, self.r)
        self.assertEqual(self.pp.info("RACE2")["stato"], "scaduto")
        self.assertTrue(self._date_libere(), "date non liberate dallo sweep")
        self.assertEqual(self.recuperi, ["RACE2"], "email di recupero: una e una sola")

    def test_pagamento_tardivo_dopo_sweep_riblocca(self):
        # sweep completo (date libere), POI arriva il pagamento: re-block riuscito -> pagato.
        self._hold_scaduto("RACE3")
        sweep_hold_una_passata(self.sys, self.r)
        self.assertEqual(self.pp.info("RACE3")["stato"], "scaduto")
        self.r._conferma_pagamento("RACE3")
        self.assertEqual(self.pp.info("RACE3")["stato"], "pagato")
        sonda = self.sys.inventario.blocca("casa-race", CI, CO, idem_key="ladro2")
        self.assertFalse(sonda.ok, "il pagamento tardivo deve ri-bloccare le date")

    def test_pagamento_tardivo_su_stanza_rubata_rimborso(self):
        # sweep libera; un ALTRO cliente prende la stanza; poi arriva il pagamento tardivo:
        # niente conferma, marcato da rimborsare (mai soldi-senza-stanza).
        self._hold_scaduto("RACE4")
        sweep_hold_una_passata(self.sys, self.r)
        ladro = self.sys.inventario.blocca("casa-race", CI, CO, idem_key="cliente_veloce")
        self.assertTrue(ladro.ok)
        self.r._conferma_pagamento("RACE4")
        self.assertEqual(self.pp.info("RACE4")["stato"], "rimborsato",
                         "stanza presa da altri -> il pagatore tardivo va rimborsato")


if __name__ == "__main__":
    unittest.main(verbosity=2)
