"""Collaudo STORNO PENALE (5ª distruttiva, Bunker-gated).

Correzione = NOTA CONTRARIA, mai modifica: la NC storna la ND, il debito si azzera,
l'eventuale già-riscosso torna in da_pagare (bonifico MANUALE). Giornale immutabile.
Invarianti:
  1. storno di ND con debito APERTO -> NC emessa (storno_di=ND), ND 'stornata',
     debito 'stornato' (residuo 0), catena hash intatta;
  2. il debito stornato NON viene MAI più riscosso dai payout futuri;
  3. storno di ND GIÀ RISCOSSA (in parte) -> il riscosso torna come riga 'maturato'
     `stornoND-<ND>` (da_pagare, PK fissa = zero doppi accrediti);
  4. IDEMPOTENTE: secondo storno -> gia_stornata, nessuna seconda NC/restituzione;
  5. endpoint: 401 senza chiave admin; 403 senza sessione Bunker; 422 senza motivo;
     404 su nota inesistente; 200 con doppio cancello;
  6. NC/ND restano visibili nella scheda Audit (fase181) con gli stati giusti.
"""
import datetime
import json
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE
from fase181_audit_console import componi

AK = {"X-Admin-Key": "ak"}


class _BaseStorno(unittest.TestCase):
    """Sistema, host e helper comuni (nessuna prova qui: le classi figlie le portano)."""

    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(
            lambda u, b, h: {"id": u.rsplit("/", 1)[-1], "payment_status": "paid"}
            if not b and "/checkout/sessions/" in u
            else {"url": "https://checkout.stripe.test/cs", "id": "cs_1"})

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"P" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db",
            db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db", db_garanzia=f"{d}/g.db",
            db_finanza=f"{d}/fin.db", bunker_password="SuperPw@1",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_x", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@storno.it", "password": "password1",
                       "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.hid, self.tok = c["host_id"], c["token"]
        self.fc = self.sis.finanza
        self.pd = self.sis.payout
        oggi = datetime.date.today()
        for slug in ("casa-s1", "casa-s2"):
            self.g("POST", "/api/host/pubblica",
                   {"slug": slug, "titolo": "Casa " + slug, "citta": "Roma",
                    "prezzo_notte_cents": 10000, "capacita": 2},
                   {"X-Host-Token": self.tok})
            self.g("POST", "/api/host/disponibilita_range",
                   {"alloggio_id": slug, "da": oggi.isoformat(),
                    "a": (oggi + datetime.timedelta(days=60)).isoformat(),
                    "unita_totali": 1, "prezzo_netto_cents": 10000},
                   {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None,
                               h or {})

    def _book_paga(self, slug, giorni=30):
        oggi = datetime.date.today()
        ci = (oggi + datetime.timedelta(days=giorni)).isoformat()
        co = (oggi + datetime.timedelta(days=giorni + 2)).isoformat()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": slug, "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@storno.it"})
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"id": "cs_" + b["riferimento"], "metadata":
                                                  {"riferimento": b["riferimento"]}}}})
        sig = firma_di_test(payload, "whsec_x", int(time.time()))
        self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                        {"Stripe-Signature": sig})
        return b["riferimento"]

    def _nd_con_debito(self):
        """ND con debito APERTO pieno (unica prenotazione cancellata: zero offset)."""
        rif = self._book_paga("casa-s2", giorni=40)
        s, _ = self.g("POST", "/api/host/cancella", {"riferimento": rif},
                      {"X-Host-Token": self.tok})
        self.assertEqual(s, 200)
        nd = self.fc.note_per_riferimento(rif)[0]
        self.assertEqual(nd["tipo"], "debito")
        return nd

    def _sessione_bunker(self):
        s, out = self.g("POST", "/api/bunker/login", {"codice": "SuperPw@1"},
                        {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(s, 200, out)
        return {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9",
                "X-Bunker-Session": out["sessione"]}

    def _debito(self, nota_id):
        trovati = [d for d in self.fc.debiti_host(self.hid) if d["debito_id"] == nota_id]
        self.assertEqual(len(trovati), 1, "debito di %s: %r" % (nota_id, trovati))
        return trovati[0]

    def _nc_di(self, nd):
        """Le note di credito che stornano la ND `nd`."""
        return [n for n in self.fc.note_per_riferimento(nd["riferimento"])
                if n.get("storno_di") == nd["nota_id"]]


class TestStornoPenale(_BaseStorno):
    # ── 1) storno con debito aperto: NC + ND stornata + debito azzerato ───────
    def test_storno_con_debito_aperto(self):
        nd = self._nd_con_debito()
        out = self.fc.storna_penale(nota_id=nd["nota_id"], motivo="errore operatore",
                                    payout=self.pd)
        self.assertIsNotNone(out)
        self.assertFalse(out["gia_stornata"])
        nc = self.fc.nota(out["nc_id"])
        self.assertEqual(nc["tipo"], "credito")
        self.assertEqual(nc["storno_di"], nd["nota_id"])          # legame contrario
        self.assertEqual(nc["importo_cents"], nd["importo_cents"])
        self.assertEqual(self.fc.nota(nd["nota_id"])["stato"], "stornata")
        deb = [d for d in self.fc.debiti_host(self.hid) if d["debito_id"] == nd["nota_id"]][0]
        self.assertEqual((deb["stato"], deb["residuo_cents"]), ("stornato", 0))
        self.assertEqual(out["riscosso_cents"], 0)                # nulla era stato preso
        self.assertTrue(self.fc.verifica_catena()["ok"])

    # ── 2) il debito stornato NON si riscuote mai piu' ────────────────────────
    def test_debito_stornato_mai_piu_riscosso(self):
        nd = self._nd_con_debito()
        self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        self.pd.registra_maturato("NUOVO1", self.hid, 20000, "EUR")
        ris = self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
        self.assertEqual(ris["riscossi_cents"], 0)                # niente da riscuotere
        self.assertEqual(self.pd.info("NUOVO1")["minori"], 20000)  # payout INTATTO

    # ── 3) storno di penale GIA' riscossa: il riscosso torna in da_pagare ─────
    def test_storno_restituisce_il_riscosso(self):
        nd = self._nd_con_debito()
        # la riscossione consuma il debito da un payout nuovo
        self.pd.registra_maturato("ALTRA", self.hid, 50000, "EUR")
        ris = self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
        riscosso = ris["riscossi_cents"]
        self.assertEqual(riscosso, nd["importo_cents"])           # debito saldato per intero
        out = self.fc.storna_penale(nota_id=nd["nota_id"], motivo="penale ingiusta",
                                    payout=self.pd)
        self.assertEqual(out["riscosso_cents"], riscosso)
        self.assertEqual(out["restituito_in_da_pagare"], riscosso)
        riga = self.pd.info("stornoND-" + nd["nota_id"])
        self.assertEqual((riga["stato"], riga["minori"]), ("maturato", riscosso))
        self.assertTrue(self.fc.verifica_catena()["ok"])

    # ── 4) idempotente ────────────────────────────────────────────────────────
    def test_idempotente(self):
        nd = self._nd_con_debito()
        self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        n_note = len(self.fc.note_per_riferimento(nd["riferimento"]))
        out2 = self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        self.assertTrue(out2["gia_stornata"])
        self.assertEqual(len(self.fc.note_per_riferimento(nd["riferimento"])), n_note)

    # ── 5) endpoint: doppio cancello + validazioni ────────────────────────────
    def test_endpoint_doppio_cancello(self):
        nd = self._nd_con_debito()
        corpo = {"nota_id": nd["nota_id"], "motivo": "errore"}
        s, _ = self.g("POST", "/api/admin/storno_penale", corpo, {})
        self.assertEqual(s, 401)                                  # niente chiave admin
        s, c = self.g("POST", "/api/admin/storno_penale", corpo, AK)
        self.assertEqual(s, 403)                                  # niente Bunker
        self.assertEqual(c["errore"], "bunker_richiesto")
        hb = self._sessione_bunker()
        s, c = self.g("POST", "/api/admin/storno_penale",
                      {"nota_id": nd["nota_id"], "motivo": ""}, hb)
        self.assertEqual(s, 422)                                  # motivo OBBLIGATORIO
        s, c = self.g("POST", "/api/admin/storno_penale",
                      {"nota_id": "ND-2099-999999", "motivo": "x"}, hb)
        self.assertEqual(s, 404)
        s, c = self.g("POST", "/api/admin/storno_penale", corpo, hb)
        self.assertEqual(s, 200, c)
        self.assertTrue(c["nc_id"].startswith("NC-"))

    # ── 6) la scheda Audit mostra ND stornata + NC ────────────────────────────
    def test_audit_mostra_lo_storno(self):
        nd = self._nd_con_debito()
        self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        sc = componi(self.sis, nd["riferimento"])
        stati = {n["nota_id"]: n["stato"] for n in sc["note"]}
        self.assertEqual(stati[nd["nota_id"]], "stornata")
        self.assertIn("emessa", [n["stato"] for n in sc["note"]
                                 if n["nota_id"].startswith("NC-")])


class TestStornoPenaleGareECrash(_BaseStorno):
    """DB1 + DB2 + DB6 (rilievi degli agenti ECC, 7/11/2026): lo storno della penale contro la
    riscossione in corsa, contro un processo che muore a meta' e contro il doppio clic.
    Ogni prova costruisce A MANO l'ordine dei passi che in produzione dipende dal caso (D19)."""

    def _nd_riscossa(self):
        """ND gia' riscossa per intero da un payout nuovo (debito 'saldato')."""
        nd = self._nd_con_debito()
        self.pd.registra_maturato("ALTRA", self.hid, 50000, "EUR")
        ris = self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
        self.assertEqual(ris["riscossi_cents"], nd["importo_cents"])
        return nd

    # ── DB1: lo storno dall'admin gira SOTTO il lucchetto dei bonifici ────────
    def test_DB1_storno_admin_tiene_il_lucchetto_dei_bonifici(self):
        """Senza `_BONIFICI_LOCK` un bonifico in corso (che riscuote i debiti) si mescola allo
        storno: il debito stornato torna 'saldato'/'aperto' e la quota presa non si restituisce."""
        import threading
        import fase83_server as srv
        nd = self._nd_con_debito()
        vero = self.fc.storna_penale
        libero = []

        def prova_a_prenderlo():
            # il lucchetto e' rientrante: lo si lascia nello STESSO filo che l'ha preso,
            # altrimenti resta tenuto da un filo morto e blocca tutte le prove dopo
            preso = srv._BONIFICI_LOCK.acquire(blocking=False)
            libero.append(preso)
            if preso:
                srv._BONIFICI_LOCK.release()

        def da_un_altro_filo():
            t = threading.Thread(target=prova_a_prenderlo)
            t.start()
            t.join(5)

        def spia(**kw):
            # un ALTRO filo prova a prendere il lucchetto mentre lo storno lavora
            da_un_altro_filo()
            return vero(**kw)

        # PREMESSA (S7, /code-review 8/11): prima della richiesta il lucchetto e' LIBERO,
        # altrimenti un «non preso» dopo direbbe niente su chi lo tiene
        da_un_altro_filo()
        self.assertEqual(libero, [True], "premessa mancante: _BONIFICI_LOCK gia' tenuto")
        libero.clear()
        self.fc.storna_penale = spia
        try:
            s, c = self.g("POST", "/api/admin/storno_penale",
                          {"nota_id": nd["nota_id"], "motivo": "errore"},
                          self._sessione_bunker())
        finally:
            del self.fc.storna_penale
        self.assertEqual(s, 200, c)
        self.assertEqual(libero, [False],
                         "lo storno della penale e' girato SENZA _BONIFICI_LOCK: un bonifico "
                         "in corso poteva riscuotere lo stesso debito nello stesso momento")

    # ── DB1: una riscossione gia' partita non RIAPRE un debito stornato ───────
    def test_DB1_riscossione_in_corsa_non_resuscita_il_debito_stornato(self):
        """riscuoti_debiti legge i debiti 'aperto' una volta sola; se nel mezzo arriva lo storno,
        la sua scrittura finale non deve sovrascrivere 'stornato' (difesa anche fra processi)."""
        nd = self._nd_con_debito()
        self.pd.registra_maturato("NUOVO1", self.hid, 50000, "EUR")
        vero = self.pd.elenca
        fatto = []

        def elenca_con_storno(*a, **kw):
            if not fatto:                    # lo storno arriva DOPO la lettura dei debiti
                fatto.append(1)
                self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
            return vero(*a, **kw)

        self.pd.elenca = elenca_con_storno
        try:
            ris = self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
        finally:
            del self.pd.elenca
        self.assertEqual(fatto, [1])
        # e il conto che torna non mente (silent-failure-hunter, 8/11): uno stornato non e'
        # ne' aperto ne' saldato
        self.assertEqual((ris["riscossi_cents"], ris["debiti_saldati"], ris["debiti_aperti"]),
                         (0, 0, 0), ris)
        # i SOLDI prima degli stati (tdd-guide, 8/11): lo storno ha gia' contato il riscosso,
        # quindi una quota presa adesso non tornerebbe piu' all'host
        self.assertEqual(self.pd.info("NUOVO1")["minori"], 50000)
        self.assertEqual(self._debito(nd["nota_id"])["stato"], "stornato")
        self.assertEqual(self.fc.nota(nd["nota_id"])["stato"], "stornata")

    # ── DB1: la penale riasserita DOPO lo storno non riprende soldi ───────────
    def test_DB1_processa_penale_dopo_lo_storno_non_riprende_soldi(self):
        """processa_penale richiamato sullo stesso riferimento dopo lo storno: su una ND gia'
        stornata non deve compensare nessun payout. Lo stato e' costruito A MANO (D19): oggi lo
        sweeper `_riprendi_cancellazione_host` non ci arriva, perche' `_penale_finita` vede la riga
        del debito; questa prova regge il giorno che quella premessa cade."""
        nd = self._nd_con_debito()
        self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        self.pd.registra_maturato("NUOVO2", self.hid, 50000, "EUR")
        esito = self.fc.processa_penale(riferimento=nd["riferimento"], host_id=self.hid,
                                        penale_cents=nd["importo_cents"], valuta="EUR",
                                        payout=self.pd)
        self.assertEqual(self.pd.info("NUOVO2")["minori"], 50000)   # payout INTATTO
        # dice che e' STORNATA, non «chiusa con residuo 0» (silent-failure-hunter, 8/11)
        self.assertIs(esito.get("stornata"), True, esito)
        self.assertEqual(self._debito(nd["nota_id"])["stato"], "stornato")
        self.assertEqual(self.fc.nota(nd["nota_id"])["stato"], "stornata")

    # ── DB2: la restituzione fallita si ritenta al secondo storno ─────────────
    def test_DB2_restituzione_fallita_si_ritenta(self):
        nd = self._nd_riscossa()
        self.pd.registra_maturato = lambda *a, **kw: False     # archivio dei bonifici giu'
        try:
            out1 = self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        finally:
            del self.pd.registra_maturato
        self.assertEqual(out1["restituito_in_da_pagare"], 0)
        self.assertIsNone(self.pd.info("stornoND-" + nd["nota_id"]))   # premessa: non restituito
        out2 = self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        self.assertEqual(out2["restituito_in_da_pagare"], nd["importo_cents"], out2)
        riga = self.pd.info("stornoND-" + nd["nota_id"])
        self.assertEqual((riga["stato"], riga["minori"]), ("maturato", nd["importo_cents"]))
        self.assertEqual(len(self._nc_di(nd)), 1)              # una sola NC anche ritentando

    # ── DB2: lo storno A META' non si annuncia al pannello come fatto ─────────
    def test_DB2_storno_a_meta_il_pannello_non_legge_fatto(self):
        """Restituzione mancata: il pannello non deve ricevere un 200 «fatto» (e la traccia del
        gesto deve dirlo), altrimenti nessuno ripete lo storno (silent-failure-hunter, 8/11)."""
        nd = self._nd_riscossa()
        self.pd.registra_maturato = lambda *a, **kw: False     # archivio dei bonifici giu'
        try:
            with self.assertLogs("core_auto.server", level="WARNING") as reg:
                s, c = self.g("POST", "/api/admin/storno_penale",
                              {"nota_id": nd["nota_id"], "motivo": "errore"},
                              self._sessione_bunker())
        finally:
            del self.pd.registra_maturato
        self.assertNotEqual(s, 200, c)
        self.assertEqual(c.get("errore"), "storno_a_meta", c)
        self.assertEqual((c.get("riscosso_cents"), c.get("restituito_in_da_pagare")),
                         (nd["importo_cents"], 0), c)
        traccia = [r for r in reg.output if "ADMIN_ACTION" in r]
        self.assertEqual(len(traccia), 1, reg.output)
        self.assertIn("A META'", traccia[0])

    # ── DB2: storno A META' -- nessuno riprende la penale nel frattempo ───────
    def test_DB2_storno_a_meta_nessuno_riprende_la_penale(self):
        """Nota di credito emessa, restituzione mancata: finche' lo storno non si completa, ne'
        lo sweeper (processa_penale) ne' i bonifici (riscuoti_debiti) devono compensare il
        resto della penale (tdd-guide, buco A). Penale riscossa SOLO IN PARTE, cosi' c'e'
        davvero un resto che si potrebbe riprendere."""
        nd = self._nd_con_debito()
        self.pd.registra_maturato("POCO", self.hid, 1000, "EUR")
        self.assertEqual(self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
                         ["riscossi_cents"], 1000)                # resto aperto: importo - 1000
        self.pd.registra_maturato = lambda *a, **kw: False     # archivio dei bonifici giu'
        try:
            out = self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        finally:
            del self.pd.registra_maturato
        # PREMESSA (S7): lo storno e' davvero rimasto A META' -- nota di credito emessa, i 1000
        # riscossi NON restituiti. Senza questo, il verde sotto non direbbe niente.
        self.assertEqual((out["riscosso_cents"], out["restituito_in_da_pagare"]), (1000, 0), out)
        self.assertIsNone(self.pd.info("stornoND-" + nd["nota_id"]))
        self.assertEqual(len(self._nc_di(nd)), 1)
        self.pd.registra_maturato("NUOVO4", self.hid, 50000, "EUR")
        self.fc.processa_penale(riferimento=nd["riferimento"], host_id=self.hid,
                                penale_cents=nd["importo_cents"], valuta="EUR",
                                payout=self.pd)
        self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
        self.assertEqual(self.pd.info("NUOVO4")["minori"], 50000)   # payout INTATTO
        self.assertEqual(self._debito(nd["nota_id"])["stato"], "stornato")

    # ── DB2: processo che muore fra la nota e il debito ───────────────────────
    def test_DB2_crash_fra_nota_e_debito_si_ripara_ritentando(self):
        """Se lo storno muore dopo la nota e prima del debito, il debito resta 'aperto' e i
        bonifici dopo lo riscuotono su una ND stornata: ritentare deve chiudere il debito."""
        nd = self._nd_con_debito()

        def muore(*a, **kw):
            raise RuntimeError("processo morto a meta'")

        self.fc._debito_scrivi = muore
        try:
            # che lo storno sollevi o risponda None (503 onesto), qui non conta: conta che
            # dopo si possa ritentare e chiudere tutto (/code-review 8/11)
            try:
                self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
            except RuntimeError:
                pass
        finally:
            del self.fc._debito_scrivi
        self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        self.assertEqual(len(self._nc_di(nd)), 1)              # una sola NC anche ritentando
        self.pd.registra_maturato("NUOVO3", self.hid, 50000, "EUR")
        ris = self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
        self.assertEqual(ris["riscossi_cents"], 0)
        self.assertEqual(self.pd.info("NUOVO3")["minori"], 50000)   # payout INTATTO
        self.assertEqual(self._debito(nd["nota_id"])["stato"], "stornato")
        self.assertEqual(self.fc.nota(nd["nota_id"])["stato"], "stornata")

    # ── DB6: doppio clic intrecciato = UNA sola nota di credito ───────────────
    def test_DB6_doppio_clic_intrecciato_una_sola_nota_di_credito(self):
        """Il secondo clic arriva fra la riga di giornale del primo e la sua nota: trova la
        riga 'idempotente' ma nessuna nota, e prima della riparazione ne emetteva una seconda."""
        nd = self._nd_con_debito()
        vero = self.fc.registra
        intreccio = []

        def registra_e_secondo_clic(**kw):
            mv = vero(**kw)
            if kw.get("evento_id") == "storno-nota:%s" % nd["nota_id"] and not intreccio:
                intreccio.append(1)
                self.fc.storna_penale(nota_id=nd["nota_id"], motivo="clic 2", payout=self.pd)
            return mv

        self.fc.registra = registra_e_secondo_clic
        try:
            self.fc.storna_penale(nota_id=nd["nota_id"], motivo="clic 1", payout=self.pd)
        finally:
            del self.fc.registra
        self.assertEqual(intreccio, [1])
        ncs = self._nc_di(nd)
        self.assertEqual(len(ncs), 1, [n["nota_id"] for n in ncs])
        self.assertTrue(self.fc.verifica_catena()["ok"])


class _RigheDelRegistro:
    """Raccoglie le righe di un registro (Python 3.9: niente assertNoLogs)."""

    def __init__(self, nome):
        import logging
        self.righe = []
        self._log = logging.getLogger(nome)
        outer = self

        class _H(logging.Handler):
            def emit(self, rec):
                outer.righe.append((rec.levelno, rec.getMessage()))

        self._h = _H(level=logging.DEBUG)

    def __enter__(self):
        self._log.addHandler(self._h)
        return self

    def __exit__(self, *a):
        self._log.removeHandler(self._h)

    def errori(self):
        import logging
        return [m for liv, m in self.righe if liv >= logging.ERROR]


class TestStornoPenaleOgniRigaHaLaSuaProva(_BaseStorno):
    """pr-test-analyzer (8/11): cinque righe della riparazione che nessuna prova difendeva -- un
    mutante ci sarebbe sopravvissuto. Ogni prova costruisce A MANO lo stato che le raggiunge (D19)."""

    def test_un_debito_stornato_non_si_riscrive(self):
        nd = self._nd_con_debito()
        self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        self.fc._debito_scrivi(nd["nota_id"], self.hid, nd["riferimento"], 500, "EUR", "aperto")
        d = self._debito(nd["nota_id"])
        self.assertEqual((d["stato"], d["residuo_cents"]), ("stornato", 0))

    def test_storno_che_arriva_DURANTE_processa_penale(self):
        """Lo storno entra mentre processa_penale sta leggendo i payout: niente compensazione,
        e la ND resta 'stornata' (la sua scrittura finale non la riporta a 'emessa')."""
        self.pd.registra_maturato("NUOVO5", self.hid, 50000, "EUR")
        vero = self.pd.elenca
        fatto = []

        def elenca_con_storno(*a, **kw):
            if not fatto:
                fatto.append(1)
                nd_ = self.fc.note_per_riferimento("R-DURANTE")[0]
                self.fc.storna_penale(nota_id=nd_["nota_id"], motivo="x", payout=self.pd)
            return vero(*a, **kw)

        self.pd.elenca = elenca_con_storno
        try:
            esito = self.fc.processa_penale(riferimento="R-DURANTE", host_id=self.hid,
                                            penale_cents=3000, valuta="EUR", payout=self.pd)
        finally:
            del self.pd.elenca
        self.assertEqual(fatto, [1])
        nid = esito["nota_id"]
        self.assertEqual(self.pd.info("NUOVO5")["minori"], 50000)   # payout INTATTO
        self.assertEqual(self.fc.nota(nid)["stato"], "stornata")
        self.assertEqual(self._debito(nid)["stato"], "stornato")

    def test_storno_che_arriva_fra_la_compensazione_e_il_saldato(self):
        """riscuoti_debiti ha appena compensato l'ultima quota; lo storno entra prima che scriva
        'saldato': la ND resta 'stornata' e la quota appena presa torna all'host."""
        nd = self._nd_con_debito()
        self.pd.registra_maturato("NUOVO6", self.hid, 50000, "EUR")
        vero = self.pd.imposta_importo
        fatto = []

        def imposta_poi_storno(*a, **kw):
            ok = vero(*a, **kw)
            if not fatto:
                fatto.append(1)
                self.out = self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x",
                                                 payout=self.pd)
            return ok

        self.pd.imposta_importo = imposta_poi_storno
        try:
            self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
        finally:
            del self.pd.imposta_importo
        self.assertEqual(fatto, [1])
        self.assertEqual(self.fc.nota(nd["nota_id"])["stato"], "stornata")
        self.assertEqual(self._debito(nd["nota_id"])["stato"], "stornato")
        self.assertEqual(self.out["restituito_in_da_pagare"], nd["importo_cents"], self.out)

    def test_il_riscosso_si_legge_DOPO_la_nota_di_credito(self):
        """Una compensazione che entra fra l'inizio dello storno e la sua nota di credito va
        contata e restituita: il riscosso si legge dal giornale DOPO la NC."""
        nd = self._nd_con_debito()
        self.pd.registra_maturato("NUOVO7", self.hid, 50000, "EUR")
        vero = self.fc.emetti_nota
        fatto = []

        def compensa_poi_emetti(**kw):
            if kw.get("tipo") == "credito" and not fatto:
                fatto.append(1)
                self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
            return vero(**kw)

        self.fc.emetti_nota = compensa_poi_emetti
        try:
            out = self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        finally:
            del self.fc.emetti_nota
        self.assertEqual(fatto, [1])
        self.assertEqual(self.pd.info("NUOVO7")["minori"], 50000 - nd["importo_cents"])  # preso
        self.assertEqual((out["riscosso_cents"], out["restituito_in_da_pagare"]),
                         (nd["importo_cents"], nd["importo_cents"]), out)        # e restituito

    def test_lo_storno_a_meta_grida_ERROR_e_quello_sano_no(self):
        """Il Guardiano legge solo gli ERROR: lo storno a meta' deve esserlo, quello riuscito no
        (un allarme si prova nei due versi, regola ferrea 10)."""
        nd = self._nd_riscossa_qui()
        self.pd.registra_maturato = lambda *a, **kw: False
        try:
            with _RigheDelRegistro("core_auto.financial_controller") as reg:
                self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        finally:
            del self.pd.registra_maturato
        self.assertTrue(any("restituzione_mancata" in m for m in reg.errori()), reg.righe)
        with _RigheDelRegistro("core_auto.financial_controller") as reg2:
            out = self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        self.assertFalse(out["a_meta"], out)
        self.assertEqual(reg2.errori(), [])

    def test_R2_il_segnale_illeggibile_non_lascia_il_debito_col_residuo_vecchio(self):
        """/code-review 8/11: il controllo «storno partito» esplode a meta' giro, dopo che una
        riga e' gia' stata compensata. Il debito deve scendere comunque, o al giro dopo si
        riscuote di nuovo la stessa somma su altri bonifici; e l'errore deve vedersi."""
        nd = self._nd_con_debito()
        self.assertGreater(nd["importo_cents"], 200)            # premessa: il debito non si chiude
        self.pd.registra_maturato("PRIMA", self.hid, 100, "EUR")
        self.pd.registra_maturato("SECONDA", self.hid, 100, "EUR")
        vero = self.fc.esiste_evento
        chiamate = []

        def esplode_alla_seconda(*a):
            if not str(a[0]).startswith(("storno-nota:", "ND-")):
                return vero(*a)
            chiamate.append(1)
            if len(chiamate) >= 2:
                raise RuntimeError("database is locked")
            return False

        self.fc.esiste_evento = esplode_alla_seconda
        self.fc._storno_partito = esplode_alla_seconda          # il nome del segnale riparato
        try:
            with _RigheDelRegistro("core_auto.financial_controller") as reg:
                ris = self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
        finally:
            del self.fc.esiste_evento
            del self.fc._storno_partito
        self.assertEqual(ris["riscossi_cents"], 100, ris)
        self.assertEqual(self._debito(nd["nota_id"])["residuo_cents"], nd["importo_cents"] - 100)
        self.assertTrue(reg.errori(), reg.righe)

    def test_R3_nota_di_credito_mai_nata_la_penale_si_continua_a_riscuotere(self):
        """/code-review 8/11: la riga di giornale dello storno si scrive prima della nota. Se la
        nota fallisce lo storno NON e' avvenuto: la penale resta da riscuotere; e ripetendo lo
        storno quanto riscosso nel frattempo torna all'host."""
        nd = self._nd_con_debito()
        self.pd.registra_maturato("DOPO", self.hid, 100, "EUR")

        def guasto(*a, **kw):
            raise RuntimeError("database is locked")

        self.fc._prossimo_nota_id = guasto
        try:
            out = self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        finally:
            del self.fc._prossimo_nota_id
        self.assertIsNone(out)                                  # premessa: la nota non e' nata
        self.assertEqual(self._nc_di(nd), [])
        self.assertEqual(self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
                         ["riscossi_cents"], 100)
        self.assertEqual(self._debito(nd["nota_id"])["residuo_cents"], nd["importo_cents"] - 100)
        out2 = self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        self.assertEqual((out2["riscosso_cents"], out2["restituito_in_da_pagare"]), (100, 100), out2)
        self.assertEqual(len(self._nc_di(nd)), 1)

    def test_R10_lo_storno_a_meta_non_si_registra_come_stornato(self):
        """Nota del ricontrollo 8/11: la riga PENALE_STORNATA dice che e' finita; a meta' non va
        scritta, a storno completo si'."""
        nd = self._nd_riscossa_qui()
        self.pd.registra_maturato = lambda *a, **kw: False
        try:
            with _RigheDelRegistro("core_auto.financial_controller") as reg:
                self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        finally:
            del self.pd.registra_maturato
        self.assertFalse([m for _, m in reg.righe if "PENALE_STORNATA" in m], reg.righe)
        with _RigheDelRegistro("core_auto.financial_controller") as reg2:
            self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        self.assertEqual(len([m for _, m in reg2.righe if "PENALE_STORNATA" in m]), 1, reg2.righe)

    def test_R5_il_pannello_dice_di_ripetere_lo_storno_a_meta(self):
        """/code-review 8/11: con storno_a_meta il pannello mostrava un errore generico: deve dire
        di ripetere lo storno e quanto non e' tornato, in tutte le lingue del pannello."""
        import os
        import re
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy", "admin.html"),
                  encoding="utf-8") as f:
            html = f.read()
        self.assertRegex(html, r"errore==='storno_a_meta'\)\{[^\n]*au_storno_meta[^\n]*riscosso_cents")
        self.assertEqual(len(re.findall(r'au_storno_meta:"[^"]+"', html)), 8)

    def _nd_riscossa_qui(self):
        nd = self._nd_con_debito()
        self.pd.registra_maturato("ALTRA", self.hid, 50000, "EUR")
        self.assertEqual(self.fc.riscuoti_debiti(host_id=self.hid, payout=self.pd)
                         ["riscossi_cents"], nd["importo_cents"])
        return nd


class _CartaCheConta:
    """Carta finta dell'host: conta gli addebiti e li fa riuscire."""

    def __init__(self):
        self.addebiti = []

    def addebita(self, **kw):
        self.addebiti.append(kw)
        return {"stato": "riuscito", "pi": "pi_finto"}


class TestStornoPenaleControLaCarta(_BaseStorno):
    """DB5 + i due buchi trovati da database-reviewer e python-reviewer (8/11): il giro che
    addebita la carta dell'host (Scatto 3, oggi SPENTO con SCATTO3_ATTIVO) non deve prendere una
    penale gia' in storno, e non deve girare fuori dal lucchetto dei bonifici."""

    def test_DB5_la_carta_non_paga_una_penale_gia_in_storno(self):
        """Il giro carta legge i debiti 'aperto' una volta sola; se nel mezzo arriva lo storno,
        l'addebito non deve partire: quei soldi nessuno li restituirebbe (lo storno conta come
        riscosso solo le compensazioni, non gli addebiti sulla carta)."""
        nd = self._nd_con_debito()
        carta = _CartaCheConta()
        vero = self.fc.debiti_host
        fatto = []

        def debiti_poi_storno(*a, **kw):
            letti = vero(*a, **kw)
            if not fatto:                    # lo storno arriva DOPO la lettura dei debiti
                fatto.append(1)
                self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
            return letti

        self.fc.debiti_host = debiti_poi_storno
        try:
            self.fc.riscuoti_da_carta(host_id=self.hid, provider_carta=carta,
                                      customer="cus_x", payment_method="pm_x")
        finally:
            del self.fc.debiti_host
        self.assertEqual(fatto, [1])
        self.assertEqual(carta.addebiti, [], "addebitata la carta per una penale stornata")
        self.assertEqual(self.fc.nota(nd["nota_id"])["stato"], "stornata")

    def test_DB5_nota_stornata_non_torna_saldata(self):
        nd = self._nd_con_debito()
        self.fc.storna_penale(nota_id=nd["nota_id"], motivo="x", payout=self.pd)
        self.fc._segna_nota_saldata(nd["nota_id"])
        self.assertEqual(self.fc.nota(nd["nota_id"])["stato"], "stornata")

    def test_DB5_il_giro_carta_tiene_il_lucchetto_dei_bonifici(self):
        import os
        import threading
        import fase83_server as srv
        self._nd_con_debito()
        libero = []

        def prova_a_prenderlo():
            preso = srv._BONIFICI_LOCK.acquire(blocking=False)
            libero.append(preso)
            if preso:
                srv._BONIFICI_LOCK.release()

        def da_un_altro_filo():
            t = threading.Thread(target=prova_a_prenderlo)
            t.start()
            t.join(5)

        def spia(**kw):
            da_un_altro_filo()
            return {"incassati_cents": 0, "debiti_saldati": 0}

        da_un_altro_filo()
        self.assertEqual(libero, [True], "premessa mancante: _BONIFICI_LOCK gia' tenuto")
        libero.clear()
        reg = self.sis.registro_host
        vecchia_carta = getattr(self.sis, "carta", None)
        vecchio_env = os.environ.get("SCATTO3_ATTIVO")
        self.fc.riscuoti_da_carta = spia
        reg.info_host = lambda hid: {"stripe_customer_id": "cus_x",
                                     "stripe_payment_method": "pm_x"}
        self.sis.carta = _CartaCheConta()
        os.environ["SCATTO3_ATTIVO"] = "1"
        try:
            esito = self.r.riscuoti_debiti_carta()
        finally:
            del self.fc.riscuoti_da_carta
            del reg.info_host
            self.sis.carta = vecchia_carta
            if vecchio_env is None:
                os.environ.pop("SCATTO3_ATTIVO", None)
            else:
                os.environ["SCATTO3_ATTIVO"] = vecchio_env
        self.assertEqual(esito.get("host"), 1, esito)           # premessa: il giro e' girato
        self.assertEqual(libero, [False],
                         "il giro carta addebita SENZA _BONIFICI_LOCK: lo storno della stessa "
                         "penale puo' passargli in mezzo")


class TestFB4LoStornoRestituisceLaPenaleAddebitataSullaCarta(_BaseStorno):
    """FB4 (revisione Fable, 10/11): penale incassata sulla carta dell'host (Scatto 3), poi
    stornata dall'admin: il riscosso deve tornare in da_pagare come per le compensazioni
    (`stornoND-<ND>`). Prima `storna_penale` leggeva solo `penale_offset`: «riscosso 0», ND
    'stornata', e i soldi presi dalla carta non tornavano piu'."""

    def test_FB4_penale_incassata_sulla_carta_poi_stornata_torna_in_da_pagare(self):
        nd = self._nd_con_debito()
        carta = _CartaCheConta()
        esito = self.fc.riscuoti_da_carta(host_id=self.hid, provider_carta=carta,
                                          customer="cus_x", payment_method="pm_x")
        # premesse: la carta e' stata addebitata davvero e il giornale lo sa
        self.assertEqual(esito["incassati_cents"], nd["importo_cents"], "PREMESSA: %r" % (esito,))
        self.assertEqual(len(carta.addebiti), 1, "PREMESSA: un addebito sulla carta")
        self.assertTrue(any(m.get("tipo") == "penale_incassata"
                            for m in self.fc.movimenti(nd["riferimento"])),
                        "PREMESSA: riga 'penale_incassata' nel giornale")
        self.assertEqual(self._debito(nd["nota_id"])["stato"], "saldato", "PREMESSA: saldato")

        out = self.fc.storna_penale(nota_id=nd["nota_id"], motivo="penale ingiusta",
                                    payout=self.pd)
        self.assertIsNotNone(out)
        self.assertFalse(out["gia_stornata"])
        self.assertEqual(out["riscosso_cents"], nd["importo_cents"],
                         "PENALE PRESA DALLA CARTA E MAI RESTITUITA: lo storno dice riscosso %r "
                         "mentre il giornale ha 'penale_incassata' di %d; la ND passa a 'stornata' "
                         "e il secondo storno risponde gia_stornata"
                         % (out["riscosso_cents"], nd["importo_cents"]))
        self.assertEqual(out["restituito_in_da_pagare"], nd["importo_cents"], out)
        riga = self.pd.info("stornoND-" + nd["nota_id"])
        self.assertIsNotNone(riga, "nessuna riga 'stornoND-<ND>' in da_pagare: l'host non rivede "
                                   "i soldi presi dalla sua carta")
        self.assertEqual((riga["stato"], riga["minori"]), ("maturato", nd["importo_cents"]))
        self.assertTrue(self.fc.verifica_catena()["ok"])

    def test_FB4_variante_processa_penale_ripetuto_dopo_la_carta_non_fa_pagare_due_volte(self):
        """VARIANTE di FB4 (variant-analysis 10/11): `processa_penale` si dichiara IDEMPOTENTE
        per riferimento e ricalcola il residuo dal giornale. Contava solo le compensazioni: dopo
        un addebito sulla carta, una ripetizione rivedeva il debito intero e lo compensava sul
        bonifico successivo dell'host -> la stessa penale pagata due volte."""
        nd = self._nd_con_debito()
        self.fc.riscuoti_da_carta(host_id=self.hid, provider_carta=_CartaCheConta(),
                                  customer="cus_x", payment_method="pm_x")
        self.assertEqual(self._debito(nd["nota_id"])["stato"], "saldato", "PREMESSA")
        self.pd.registra_maturato("ALTRA", self.hid, 50000, "EUR")
        out = self.fc.processa_penale(riferimento=nd["riferimento"], host_id=self.hid,
                                      penale_cents=nd["importo_cents"], valuta="EUR",
                                      payout=self.pd)
        self.assertIsNotNone(out)
        self.assertEqual(self.pd.info("ALTRA")["minori"], 50000,
                         "PENALE PAGATA DUE VOLTE: gia' presa dalla carta e ricompensata sul "
                         "bonifico successivo dell'host (%r)" % (out,))
        self.assertEqual(out["residuo_cents"], 0, out)
        self.assertEqual(self._debito(nd["nota_id"])["stato"], "saldato")

    def test_FB4_controllo_la_carta_di_UN_ALTRA_nota_non_si_restituisce(self):
        """Prova di controllo: una penale presa dalla carta per un'altra nota (stesso
        riferimento) non e' «riscosso» di questa."""
        nd = self._nd_con_debito()
        self.fc.registra(evento_id="carta:ND-altra:999", tipo="penale_incassata",
                         riferimento=nd["riferimento"], soggetto="host:" + self.hid,
                         conto_dare="cassa_piattaforma", conto_avere="crediti_vs_host",
                         importo_cents=999, valuta="EUR", causale="altra nota",
                         emittente="prova")
        out = self.fc.storna_penale(nota_id=nd["nota_id"], motivo="ingiusta", payout=self.pd)
        self.assertEqual(out["riscosso_cents"], 0, out)
        self.assertIsNone(self.pd.info("stornoND-" + nd["nota_id"]))


if __name__ == "__main__":
    unittest.main()
