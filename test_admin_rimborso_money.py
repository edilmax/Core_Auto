"""
COERENZA denaro del RIMBORSO ADMIN (bug provato 2026-07-16).

Il bottone "Rimborsa" del pannello admin (`/api/admin/rimborso`) liberava SOLO le date, ma —
a differenza della cancellazione ospite/host — NON metteva in sicurezza i soldi: l'host restava
'maturato' e l'escrow si auto-rilasciava a 24h -> PAGAVAMO L'HOST mentre rimborsavamo l'ospite
= PERDITA PIENA. Fix: il rimborso admin trattiene il payout, chiude l'escrow, invalida il
pendente (riferimento = idem_key[:24]). Qui si prova che dopo il rimborso l'host NON viene pagato.
"""
import json
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_ar"


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://t/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


class TestAdminRimborsoMoney(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db",
            commissione_bps=1000, psp_bps=0, stripe_secret_key="sk",
            stripe_webhook_secret=WH, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@ar.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.tok, self.hid = c["token"], c["host_id"]
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "Casa", "citta": "Roma", "prezzo_notte_cents": 50000,
                "capacita": 4, "politica_cancellazione": "flessibile"}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": "2026-09-01", "a": "2026-09-30",
                "unita_totali": 1, "prezzo_netto_cents": 50000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _maturato(self):
        return self.sys.payout.riepilogo(self.hid).get("EUR", {}).get("maturato", 0)

    def test_rimborso_admin_non_paga_l_host(self):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": "2026-09-05",
                       "check_out": "2026-09-08", "party": 2})
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ar.it"})
        rif = b["riferimento"]
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        self.assertGreater(self._maturato(), 0, "setup: la prenotazione dev'essere pagata")
        # l'admin recupera l'idem_key come nel pannello, poi rimborsa
        s, adm = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Key": "ak"})
        idem = adm["prenotazioni"][0]["idem_key"]
        s, res = self.g("POST", "/api/admin/rimborso",
                        {"alloggio_id": "casa", "check_in": "2026-09-05",
                         "check_out": "2026-09-08", "idem_key": idem}, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, res)
        # DOPO il rimborso: l'host non incassa piu' e l'escrow non si auto-rilascia
        self.assertEqual(self._maturato(), 0, "REGRESSIONE: payout host non trattenuto -> doppia perdita")
        self.assertEqual(self.sys.garanzia.stato(rif).get("stato"), "annullato",
                         "REGRESSIONE: escrow ancora aperto -> si auto-rilascia all'host")
        self.assertEqual(self.sys.pagamenti_pendenti.info(rif).get("stato"), "rimborsato")
        # l'auto-rilascio a 24h NON deve pagare l'host
        ril = self.sys.garanzia.auto_rilascia(ora_ts=int(time.time()) + 10**9, dettagli=True)
        self.assertEqual(ril, [], "REGRESSIONE: l'host viene pagato su prenotazione rimborsata")

    def test_se_un_passo_di_sicurezza_FALLISCE_la_risposta_NON_dice_fatto(self):
        """IL RIMBORSO NON PUO' DICHIARARE COSE CHE NON SONO AVVENUTE.

        `_admin_rimborso` esegue i passi che impediscono la PERDITA PIENA -- trattenere il
        payout, stornare la tassa, REVOCARE il check-in, chiudere l'escrow, invalidare il
        pendente -- e ognuno e' isolato in un `except` che scrive solo nel log. Poi la
        funzione ritornava INCONDIZIONATAMENTE 200 con la nota «payout trattenuto ed escrow
        chiuso»: una frase che poteva essere FALSA.

        Il pezzo che nessun altro copre e' la SERRATURA: se la revoca del check-in fallisce,
        lo smart-pass resta valido su una prenotazione rimborsata -> la porta si apre a un
        ospite che ha gia' riavuto i soldi. Il Guardiano (fase186) sorveglia bonifici ed
        escrow, non le serrature: qui non arriva.

        VISTO ROSSO sul codice vecchio: rispondeva 200 «rimborsato ... payout trattenuto ed
        escrow chiuso» senza una parola sui due passi esplosi.
        """
        class _Rotto:
            def __getattr__(self, nome):
                def _boom(*a, **k):
                    raise RuntimeError("componente guasto: %s" % nome)
                return _boom

        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": "2026-09-20",
                       "check_out": "2026-09-22", "party": 2})
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ar.it"})
        rif = b["riferimento"]
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        s, adm = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Key": "ak"})
        idem = [p for p in adm["prenotazioni"] if p.get("check_in") == "2026-09-20"][0]["idem_key"]

        # ROMPO due passi: la serratura e il payout. Il rilascio delle date resta sano.
        self.sys.checkin = _Rotto()
        self.sys.payout = _Rotto()

        s, res = self.g("POST", "/api/admin/rimborso",
                        {"alloggio_id": "casa", "check_in": "2026-09-20",
                         "check_out": "2026-09-22", "idem_key": idem}, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, "le date sono state liberate davvero: %r" % (res,))
        falliti = res.get("passi_falliti") or []
        self.assertIn("checkin_revocato", falliti,
                      "la revoca della serratura e' esplosa e la risposta tace: %r" % (res,))
        self.assertIn("payout_trattenuto", falliti,
                      "il payout non e' stato trattenuto e la risposta tace: %r" % (res,))
        self.assertNotIn("payout trattenuto", (res.get("nota") or "").lower(),
                         "la nota dichiara un passo NON avvenuto: %r" % (res,))

    def test_quando_va_tutto_bene_NON_inventa_fallimenti(self):
        """Prova di rimozione: la lista dei falliti dev'essere vuota sul percorso sano,
        altrimenti la nuova segnalazione sarebbe un falso allarme (difetto quanto il buco)."""
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": "2026-09-25",
                       "check_out": "2026-09-27", "party": 2})
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ar.it"})
        s, adm = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Key": "ak"})
        idem = [p for p in adm["prenotazioni"] if p.get("check_in") == "2026-09-25"][0]["idem_key"]
        s, res = self.g("POST", "/api/admin/rimborso",
                        {"alloggio_id": "casa", "check_in": "2026-09-25",
                         "check_out": "2026-09-27", "idem_key": idem}, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, res)
        self.assertEqual(res.get("passi_falliti"), [],
                         "grida su un rimborso perfettamente riuscito: %r" % (res,))

    def test_rimborso_admin_idempotente(self):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": "2026-09-15",
                       "check_out": "2026-09-17", "party": 2})
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ar.it"})
        s, adm = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Key": "ak"})
        idem = adm["prenotazioni"][0]["idem_key"]
        body = {"alloggio_id": "casa", "check_in": "2026-09-15",
                "check_out": "2026-09-17", "idem_key": idem}
        s1, _ = self.g("POST", "/api/admin/rimborso", body, {"X-Admin-Key": "ak"})
        s2, r2 = self.g("POST", "/api/admin/rimborso", body, {"X-Admin-Key": "ak"})
        self.assertEqual((s1, s2), (200, 200), "il rimborso ripetuto non deve fallire")
        self.assertTrue(r2.get("idempotente"))


CHIAMATE = []


def _fetch_registrante(url, body, headers):
    """Finto Stripe che REGISTRA cosa gli e' stato chiesto: senza questo non si puo'
    distinguere «ho rimborsato» da «ho scritto rimborsato nel database»."""
    import secrets
    CHIAMATE.append({"url": url,
                     "body": (body or b"").decode("utf-8", "replace"),
                     "headers": dict(headers or {})})
    if "/refunds" in url:
        return {"id": "re_" + secrets.token_hex(4), "status": "succeeded",
                "amount": 1, "object": "refund"}
    return {"url": "https://t/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


class TestIlRimborsoARRIVADavveroAllOspite(unittest.TestCase):
    """⛔ IL BUCO PIU' GRAVE RIMASTO SUL PRODOTTO: I SOLDI NON TORNAVANO INDIETRO DA SOLI.

    `_admin_rimborso` faceva tutto tranne la cosa che il suo nome promette: liberava le date,
    tratteneva il payout, stornava la tassa, revocava lo smart-pass, chiudeva l'escrow,
    marcava il pendente e scriveva la riga a giornale -- e poi rispondeva, testualmente,
    *«il rimborso va eseguito A MANO dal pannello admin»*. `grep v1/refunds` su tutto il
    progetto dava **zero**: nessuno ha mai chiesto a Stripe di restituire un euro.

    Per l'ospite la differenza non e' tecnica: il database diceva «rimborsato» e sul suo conto
    non arrivava niente finche' una persona non se ne ricordava. Ed e' l'unico difetto del
    progetto che non si ripara con una correzione: si ripara con un bonifico.

    ⛔ PERCHE' QUESTE GUARDIE GUARDANO LA CHIAMATA E NON IL DATABASE. Lo stato 'rimborsato'
    era gia' verde PRIMA di questa riparazione: un collaudo che controlla lo stato sarebbe
    stato verde su una macchina che non restituiva un centesimo. L'unica prova che i soldi
    partono e' **cosa arriva a Stripe** -- percio' il finto provider REGISTRA le chiamate.
    """

    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fetch_registrante)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        del CHIAMATE[:]
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db",
            commissione_bps=1000, psp_bps=0, stripe_secret_key="sk",
            stripe_webhook_secret=WH, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@rb.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.tok, self.hid = c["token"], c["host_id"]
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "Casa", "citta": "Roma", "prezzo_notte_cents": 50000,
                "capacita": 4, "politica_cancellazione": "flessibile"}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": "2026-09-01", "a": "2026-09-30",
                "unita_totali": 1, "prezzo_netto_cents": 50000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _prenota_e_paga(self, ci, co, pi_id="pi_test_ospite"):
        """Prenotazione pagata davvero, col webhook che porta il payment_intent (mode=payment:
        la documentazione Stripe lo dichiara presente sulla Checkout Session)."""
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@rb.it"})
        rif = b["riferimento"]
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": "cs_test_1", "payment_intent": pi_id,
                                             "metadata": {"riferimento": rif}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        s, adm = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Key": "ak"})
        idem = [p for p in adm["prenotazioni"] if p.get("check_in") == ci][0]["idem_key"]
        return rif, idem

    @staticmethod
    def _rimborsi():
        return [c for c in CHIAMATE if "/refunds" in c["url"]]

    def _totale_ospite(self, rif):
        rec = self.sys.pagamenti_pendenti.info(rif) or {}
        dj = json.loads(rec.get("corpo_json") or "{}")
        return int(dj.get("totale_cents", 0) or dj.get("prezzo_guest_cents", 0) or 0)

    def test_I_SOLDI_PARTONO_DAVVERO_VERSO_L_OSPITE(self):
        """La guardia che mancava: non «lo stato dice rimborsato», ma «a Stripe e' arrivata la
        richiesta di restituire i soldi», con l'importo giusto e sul pagamento giusto."""
        rif, idem = self._prenota_e_paga("2026-09-05", "2026-09-08")
        atteso = self._totale_ospite(rif)
        self.assertGreater(atteso, 0, "setup: il totale ospite dev'essere noto")
        s, res = self.g("POST", "/api/admin/rimborso",
                        {"alloggio_id": "casa", "check_in": "2026-09-05",
                         "check_out": "2026-09-08", "idem_key": idem}, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, res)
        rimborsi = self._rimborsi()
        self.assertEqual(len(rimborsi), 1,
                         "a Stripe NON e' arrivata nessuna richiesta di rimborso: il database "
                         "dice 'rimborsato' e sul conto dell'ospite non arriva niente. "
                         "Chiamate viste: %r" % [c["url"] for c in CHIAMATE])
        corpo = rimborsi[0]["body"]
        self.assertIn("payment_intent=pi_test_ospite", corpo,
                      "il rimborso non e' agganciato al pagamento vero: %r" % corpo)
        self.assertIn("amount=%d" % atteso, corpo,
                      "importo rimborsato diverso dal totale pagato dall'ospite "
                      "(atteso %d): %r" % (atteso, corpo))

    def test_LA_CHIAVE_DI_IDEMPOTENZA_C_E_ED_E_STABILE(self):
        """Senza `Idempotency-Key` un ritentativo di rete rimborsa DUE volte: e' il rovescio
        esatto del doppio pagamento, e i soldi escono da noi."""
        rif, idem = self._prenota_e_paga("2026-09-10", "2026-09-12")
        self.g("POST", "/api/admin/rimborso",
               {"alloggio_id": "casa", "check_in": "2026-09-10",
                "check_out": "2026-09-12", "idem_key": idem}, {"X-Admin-Key": "ak"})
        rimborsi = self._rimborsi()
        self.assertEqual(len(rimborsi), 1, "nessun rimborso inviato")
        intest = {k.lower(): v for k, v in rimborsi[0]["headers"].items()}
        chiave = intest.get("idempotency-key", "")
        self.assertTrue(chiave,
                        "il rimborso parte SENZA chiave di idempotenza: un ritentativo di rete "
                        "restituisce i soldi due volte. Intestazioni: %r" % (intest,))
        self.assertIn(rif, chiave,
                      "la chiave non e' legata alla prenotazione (%r): due rimborsi diversi "
                      "potrebbero condividerla, oppure lo stesso rimborso cambiarla a ogni "
                      "tentativo -- in tutti e due i casi non protegge" % chiave)

    def test_SE_UN_PASSO_DI_SICUREZZA_FALLISCE_I_SOLDI_NON_PARTONO(self):
        """⛔ LA REGOLA DEL DENARO (D16): se non siamo riusciti a trattenere il payout, l'host
        potrebbe essere gia' stato pagato. Rimborsare li' significa pagare DUE VOLTE la stessa
        prenotazione, e la seconda la paghiamo noi. Nel dubbio i soldi NON partono da soli: si
        grida e decide una persona."""
        class _Rotto:
            def __getattr__(self, nome):
                def _boom(*a, **k):
                    raise RuntimeError("componente guasto: %s" % nome)
                return _boom

        rif, idem = self._prenota_e_paga("2026-09-20", "2026-09-22")
        self.sys.payout = _Rotto()
        s, res = self.g("POST", "/api/admin/rimborso",
                        {"alloggio_id": "casa", "check_in": "2026-09-20",
                         "check_out": "2026-09-22", "idem_key": idem}, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, res)
        self.assertIn("payout_trattenuto", res.get("passi_falliti") or [],
                      "setup: il passo doveva fallire")
        self.assertEqual(self._rimborsi(), [],
                         "i soldi sono partiti mentre il payout NON era trattenuto: l'host "
                         "puo' essere gia' stato pagato -> paghiamo due volte la stessa "
                         "prenotazione, e la seconda la paghiamo noi")

    def test_RIMBORSO_RIPETUTO_NON_RESTITUISCE_DUE_VOLTE(self):
        """Doppio clic dell'operatore. Lo stato e' gia' 'rimborsato': non deve partire una
        seconda richiesta."""
        rif, idem = self._prenota_e_paga("2026-09-15", "2026-09-17")
        corpo = {"alloggio_id": "casa", "check_in": "2026-09-15",
                 "check_out": "2026-09-17", "idem_key": idem}
        self.g("POST", "/api/admin/rimborso", corpo, {"X-Admin-Key": "ak"})
        self.g("POST", "/api/admin/rimborso", corpo, {"X-Admin-Key": "ak"})
        self.assertEqual(len(self._rimborsi()), 1,
                         "due richieste di rimborso per la stessa prenotazione: l'ospite "
                         "riceve il doppio e la differenza la mettiamo noi")

    def test_SENZA_IL_PAGAMENTO_NON_INVENTA_UN_RIMBORSO(self):
        """Prenotazione mai pagata (nessun webhook, nessun payment_intent): non c'e' niente da
        restituire. Deve NON chiamare Stripe e NON dichiarare un rimborso avvenuto (S7: se
        manca la premessa il controllo non e' verde, e' non eseguito)."""
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": "2026-09-25",
                       "check_out": "2026-09-27", "party": 2})
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@rb.it"})
        s, adm = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Key": "ak"})
        idem = [p for p in adm["prenotazioni"] if p.get("check_in") == "2026-09-25"][0]["idem_key"]
        s, res = self.g("POST", "/api/admin/rimborso",
                        {"alloggio_id": "casa", "check_in": "2026-09-25",
                         "check_out": "2026-09-27", "idem_key": idem}, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, res)
        self.assertEqual(self._rimborsi(), [],
                         "ha chiesto a Stripe di rimborsare una prenotazione mai pagata")


if __name__ == "__main__":
    unittest.main(verbosity=2)
