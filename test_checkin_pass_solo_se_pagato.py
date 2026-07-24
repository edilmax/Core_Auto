"""
REGOLA AUREA (Flow 3 micro-stepping): NESSUN check-in / pass DEFINITIVO senza pagamento
CONFERMATO.

Il check-in digitale (`/api/checkin/pre_registra`) porta `completato=True`, e `completato`
ABILITA il pass della porta (fase127 CheckinDigitale.sblocca). Prima la guardia bloccava SOLO
'rimborsato'/'cancellata_host' e AMMETTEVA 'in_attesa'/'scaduto' ("pagamento in volo"): un
ospite che NON paga poteva quindi completare il check-in e — con serratura smart vera —
ottenere lo sblocco = soggiorno GRATIS. (Modo di rompersi #2: cablaggio soldi->porta mancante.)

Ora: pendente presente e NON 'pagato' -> check-in RIFIUTATO (409 pagamento_non_confermato);
appena 'pagato' (webhook, pochi secondi) -> AMMESSO. Chi paga davvero e' 'pagato' ben prima
dell'arrivo, quindi zero attrito per l'ospite legittimo.

Rosso sul vecchio (ammetteva 'in_attesa'). Controllo POSITIVO incluso (paga -> 200 + door
pass abilitato) per non essere una guardia blocca-tutto (compiacente).
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase57_vetrina import SchedaAlloggio


class TestCheckinPassSoloSePagato(unittest.TestCase):
    def setUp(self):
        d = self.d = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_checkin=f"{d}/ck.db", db_pendenti=f"{d}/p.db"))
        self.assertIsNotNone(self.sys.checkin, "checkin deve essere attivo (smart pass on)")
        self.assertIsNotNone(self.sys.pagamenti_pendenti, "serve il registro pendenti")
        self.r = crea_router(self.sys)
        self.sys.catalogo.pubblica(SchedaAlloggio(
            host_id="h1", slug="casa", titolo="Casa", citta="Roma",
            prezzo_notte_cents=10000, capacita=4))
        for g in ("2026-09-01", "2026-09-02"):
            self.sys.inventario.imposta_disponibilita("casa", g, unita_totali=1,
                                                      prezzo_netto_cents=10000)
        self.voucher, self.rif = self._prenota()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, {})

    def _prenota(self):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": "2026-09-01",
                       "check_out": "2026-09-02", "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "g@x.it"})
        self.assertEqual(s, 201, b)
        self.assertTrue(b.get("voucher_token") and b.get("riferimento"), b)
        return b["voucher_token"], b["riferimento"]

    def _pre_registra(self):
        return self.g("POST", "/api/checkin/pre_registra",
                      {"voucher_token": self.voucher,
                       "ospiti": [{"nome": "Mario Rossi", "documento": "AB1234567"}]})

    def _pendente(self, stato):
        """Porta il pendente del rif allo stato voluto (book qui non lo crea: no Stripe).
        'scaduto' non e' uno stato INIZIALE: si raggiunge da 'in_attesa' via scadi()."""
        pp = self.sys.pagamenti_pendenti
        pp.registra(self.rif, alloggio_id="casa", check_in="2026-09-01",
                    check_out="2026-09-02", stato="in_attesa")
        if stato == "scaduto":
            pp.scadi(self.rif)                                       # hold spirato, mai pagato
        self.assertEqual(pp.info(self.rif)["stato"], stato)

    def _completato(self):
        s, st = self.g("GET", "/api/checkin/stato", q={"voucher_token": self.voucher})
        self.assertEqual(s, 200, st)
        return bool(st.get("completato"))

    # --- IN ATTESA: check-in RIFIUTATO (rosso sul vecchio, che ammetteva in_attesa) ---
    def test_in_attesa_niente_checkin(self):
        self._pendente("in_attesa")
        s, out = self._pre_registra()
        self.assertEqual(s, 409, ("check-in su prenotazione NON pagata!", out))
        self.assertEqual(out.get("errore"), "pagamento_non_confermato", out)
        self.assertFalse(self._completato(), "completato=True senza pagamento: pass abilitato a scrocco")

    # --- SCADUTO (hold spirato, mai pagato): idem, RIFIUTATO ---
    def test_scaduto_niente_checkin(self):
        self._pendente("scaduto")
        s, out = self._pre_registra()
        self.assertEqual(s, 409, ("check-in su hold scaduto non pagato!", out))
        self.assertFalse(self._completato())

    # --- CONTROLLO POSITIVO: pagato -> check-in AMMESSO + door pass abilitato ---
    def test_pagato_checkin_ok(self):
        self._pendente("in_attesa")
        self.sys.pagamenti_pendenti.conferma(self.rif)               # webhook: -> pagato
        self.assertEqual(self.sys.pagamenti_pendenti.info(self.rif)["stato"], "pagato")
        s, out = self._pre_registra()
        self.assertEqual(s, 200, ("pagato ma check-in negato: guardia troppo severa", out))
        self.assertTrue(out.get("ok"), out)
        self.assertTrue(self._completato(), "pagato: il door pass deve essere abilitato")


if __name__ == "__main__":
    unittest.main(verbosity=2)
