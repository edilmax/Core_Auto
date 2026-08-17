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


# ─────────────────────────────────────────────────────────────────────────────
# LA LISTA DEI RIMBORSI DOVUTI — le guardie del progetto in 6 punti (2026-08-16)
# ─────────────────────────────────────────────────────────────────────────────

import threading

STRIPE_FINTO = {"rimborsi_per_pi": {}, "per_chiave": {}, "esplode": False,
                "barriera_rimborso": None}
CHIAMATE_LISTA = []
_SERRATURA_FINTO_STRIPE = threading.Lock()


# ── L'ORACOLO INDIPENDENTE (collaudo 5) ─────────────────────────────────────────
# ⛔ Scritto QUI a mano dalla politica PUBBLICA (100% / 50% / 0% a scaglioni di giorni),
# NON importato da `fase111`: importarlo non sarebbe un secondo calcolo, sarebbe lo stesso
# calcolo chiamato due volte -- e due volte lo stesso errore da' lo stesso risultato.
# Anche l'aritmetica e' scritta diversa apposta: `fase111` lavora in bps (x/10000), qui in
# percento (x/100). Se un giorno una delle due divergesse, il confronto lo direbbe.
POLITICHE_ORACOLO = {
    "flessibile": ((1, 100), (0, 50)),
    "moderata": ((5, 100), (1, 50), (0, 0)),
    "rigida": ((30, 100), (7, 50), (0, 0)),
}


def _oracolo_rimborso(pagato_cents, giorni_all_arrivo, politica, entro_ripensamento):
    """SECONDO CALCOLO, scritto separatamente, che ricalcola da zero quanto spetta.

    Serve a rispondere a una domanda che nessun altro collaudo fa: *«e se fosse il MOTORE a
    sbagliare?»*. Tutti gli altri test confrontano il prodotto con se stesso; questo lo
    confronta con un conto fatto da un'altra parte."""
    if pagato_cents <= 0:
        return 0
    # La finestra di ripensamento vince su qualunque politica dell'host, ma non su un
    # soggiorno ormai imminente (arrivo sotto i 3 giorni).
    if entro_ripensamento and giorni_all_arrivo >= 3:
        return pagato_cents
    for soglia, percento in POLITICHE_ORACOLO[politica]:
        if giorni_all_arrivo >= soglia:
            return pagato_cents * percento // 100
    return 0


def _fetch_stripe_con_memoria(url, body, headers):
    """Finto Stripe che sa rispondere anche alla DOMANDA «esiste gia' un rimborso su questo
    pagamento?», e che RICORDA i rimborsi creati.

    Senza la lettura, «la verita' la dice Stripe» (punto 2) non e' collaudabile: un finto
    provider che risponde solo alle scritture costringerebbe la lista a fidarsi del nostro
    database, cioe' esattamente il difetto del 16 agosto (database 'rimborsato', Stripe zero).
    E senza la MEMORIA non si potrebbe distinguere «la riga sparisce perche' e' stata
    rimborsata» da «la riga sparisce perche' l'abbiamo tolta noi»."""
    import secrets
    from urllib.parse import urlparse, parse_qs
    CHIAMATE_LISTA.append({"url": url, "body": (body or b"").decode("utf-8", "replace"),
                           "headers": dict(headers or {})})
    if STRIPE_FINTO["esplode"]:
        raise RuntimeError("Stripe irraggiungibile: rete assente")
    if "/refunds" in url and not body:
        # LETTURA — GET /v1/refunds?payment_intent=pi_...
        pi = (parse_qs(urlparse(url).query).get("payment_intent") or [""])[0]
        return {"object": "list",
                "data": list(STRIPE_FINTO["rimborsi_per_pi"].get(pi, []))}
    if "/refunds" in url:
        # SCRITTURA — POST /v1/refunds
        # ⛔ QUI IL FINTO STRIPE DEDUPLICA SULL'`Idempotency-Key`, come quello vero: senza
        # questo comportamento il collaudo sulla concorrenza direbbe «due rimborsi partiti»
        # e accuserebbe un innocente. La documentazione (docs.stripe.com/api/idempotent_
        # requests) e' esplicita: richieste successive con la stessa chiave tornano lo STESSO
        # risultato. ⚠️ E dichiara anche il limite: l'esito viene salvato solo DOPO che
        # l'esecuzione e' iniziata, quindi due richieste davvero simultanee possono
        # confliggere ed essere ritentabili -- non e' una rete perfetta, e' una rete.
        campi = parse_qs(body.decode("utf-8"))
        pi = (campi.get("payment_intent") or [""])[0]
        chiave = {k.lower(): v for k, v in (headers or {}).items()}.get("idempotency-key", "")
        # ⛔ IL CANCELLETTO CHE FORZA LA GARA VERA. Senza, i due fili non si incontrano mai:
        # il primo finisce tutto il giro (chiedi a Stripe -> rimborsa) prima che il secondo
        # arrivi, il secondo vede «gia' rimborsato» e non chiama nemmeno. Il collaudo passava
        # perche' la gara NON AVVENIVA, non perche' la protezione reggeva -- e infatti il
        # Giudice della mutazione l'ha smascherato: la chiave resa instabile sopravviveva.
        # Qui i due fili si aspettano DENTRO la creazione del rimborso, cioe' tutti e due
        # hanno gia' chiesto «esiste?» e si sono sentiti dire di no. E' la finestra vera.
        barriera = STRIPE_FINTO.get("barriera_rimborso")
        if barriera is not None:
            try:
                barriera.wait()
            except Exception:
                pass
        with _SERRATURA_FINTO_STRIPE:
            if chiave and chiave in STRIPE_FINTO["per_chiave"]:
                return dict(STRIPE_FINTO["per_chiave"][chiave])
            rid = "re_" + secrets.token_hex(4)
            risposta = {"id": rid, "status": "succeeded", "object": "refund"}
            if chiave:
                STRIPE_FINTO["per_chiave"][chiave] = risposta
            STRIPE_FINTO["rimborsi_per_pi"].setdefault(pi, []).append(
                {"id": rid, "status": "succeeded",
                 "amount": int((campi.get("amount") or ["0"])[0] or 0)})
        return dict(risposta)
    return {"url": "https://t/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


class TestLaListaDeiRimborsiDovuti(unittest.TestCase):
    """🔴🔴 IL DIFETTO PIU' GRAVE APERTO: LA CANCELLAZIONE DELL'OSPITE NON RESTITUISCE I SOLDI.

    Il 2026-08-16 e' stata riparata UNA delle due strade che portano a un rimborso: quella del
    pannello admin. L'altra -- l'ospite che cancella da solo -- calcola il dovuto secondo la
    politica (fase111), LIBERA le date, risponde «cancellata», e i soldi restano fermi finche'
    una persona non entra nel pannello e li manda a mano. Misurato: `grep "\\.rimborsa("` in
    produzione da' UN SOLO punto, dentro `_admin_rimborso`.

    ⛔ PERCHE' IL COLLAUDO SU SOLDI VERI NON POTEVA VEDERLO: il rimborso di prova e' stato
    fatto DAL PANNELLO, cioe' sull'unica strada che funzionava. La lezione e' nel registro:
    non basta «questa strada funziona?», serve «QUANTE strade portano qui?».

    🗣️ DECISIONE DEL FONDATORE: all'inizio il rimborso si fa A MANO, con una lista nel
    pannello e un pulsante. NON automatico -- *«se la macchina sbaglia ci rimetto conti,
    fiducia, credibilita'»*. L'automatico si accende dopo: prima si guadagna la fiducia.

    ⛔ E IL PEZZO CHE REGGE TUTTO IL RESTO: **la lista non si scrive, si CALCOLA.** Se la
    cancellazione INSERISSE una riga in una coda, il fallimento di quel passo (errore,
    riavvio, blocco) farebbe sparire la riga e nessuno lo saprebbe mai: il cliente aspetta per
    sempre. Invece la lista e' una DOMANDA rifatta a ogni apertura -- *«quali prenotazioni
    pagate e poi cancellate non hanno ancora un rimborso su Stripe?»* -- e una riga non puo'
    mancare, perche' nessuno deve ricordarsi di scriverla.

    Queste guardie sono state scritte PRIMA della riparazione (D20) e viste rosse.
    """

    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fetch_stripe_con_memoria)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        del CHIAMATE_LISTA[:]
        STRIPE_FINTO["rimborsi_per_pi"] = {}
        STRIPE_FINTO["per_chiave"] = {}
        STRIPE_FINTO["esplode"] = False
        STRIPE_FINTO["barriera_rimborso"] = None
        self.dir = tempfile.mkdtemp()
        d = self.dir
        # ⛔ `db_finanza` NON e' un dettaglio del banco: il giornale immutabile e' la sola
        # fonte che non perde una riga (i pendenti li cancella `pulisci_vecchi` a 26 ore).
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db", db_finanza=f"{d}/fin.db",
            commissione_bps=1000, psp_bps=0, stripe_secret_key="sk",
            stripe_webhook_secret=WH, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@ld.it", "password": "password1", "accetta_termini": True,
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

    # ── attrezzi ────────────────────────────────────────────────────────────
    def _prenota_e_paga(self, ci, co, pi_id):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ld.it"})
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": "cs_" + pi_id, "payment_intent": pi_id,
                                             "metadata": {"riferimento": b["riferimento"]}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        return b["riferimento"], b["voucher_token"]

    def _cancella_da_ospite(self, ci, co, pi_id):
        """La strada che NON restituisce i soldi: `POST /api/concierge/cancella`."""
        rif, vt = self._prenota_e_paga(ci, co, pi_id)
        s, canc = self.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
        self.assertEqual(s, 200, "setup: la cancellazione ospite deve riuscire: %r" % (canc,))
        return rif, canc

    def _lista(self):
        s, corpo = self.g("GET", "/api/admin/rimborsi_dovuti", None, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, "la lista dei rimborsi dovuti non risponde: %r" % (corpo,))
        return corpo

    @staticmethod
    def _riga(corpo, rif):
        for r in (corpo.get("rimborsi") or []):
            if r.get("riferimento") == rif:
                return r
        return None

    def _paga_tardi_su_stanza_rubata(self, ci, co, pi_id):
        """STRADA 5: il cliente prenota, l'attesa scade, un ALTRO si prende la stanza, e solo
        dopo arriva il suo pagamento. Il re-blocco fallisce -- ed e' GIUSTO che fallisca, e'
        il sistema anti-doppia-prenotazione che fa il suo dovere -- ma il cliente resta con i
        soldi fuori e senza stanza."""
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ld.it"})
        self.assertEqual(s, 201, b)
        rif = b["riferimento"]
        pp = self.sys.pagamenti_pendenti
        rec = pp.info(rif)
        self.assertIsNotNone(rec, "setup: il pendente deve esistere")
        # lo sweeper: attesa scaduta -> 'scaduto', e le date tornano libere
        pp.scadi(rif)
        self.sys.inventario.rilascia("casa", ci, co,
                                     idem_key=(rec.get("idem_key") or ("hold_" + rif)))
        # un altro cliente si prende la stanza, e ne ha pieno diritto
        ladro = self.sys.inventario.blocca("casa", ci, co, idem_key="veloce_" + rif)
        self.assertTrue(getattr(ladro, "ok", False),
                        "setup: dopo il rilascio la stanza doveva essere libera")
        # ...e solo ADESSO arriva il pagamento del primo
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": "cs_" + pi_id, "payment_intent": pi_id,
                                             "metadata": {"riferimento": rif}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        self.assertEqual(pp.info(rif)["stato"], "rimborsato",
                         "setup: stanza presa da altri -> il pagatore tardivo va rimborsato")
        return rif

    # ── LE STRADE CHE NON ARRIVANO IN LISTA ─────────────────────────────────
    # Contate il 2026-08-17 su ordine del fondatore («conta tutti i percorsi, senza fare lo
    # sbaglio che vedevate solo uno e ignoravate il resto»): SETTE strade portano a «il
    # cliente ha dei soldi da riavere», TRE ci arrivano. Queste sono le altre.
    def test_STRADA_5_PAGAMENTO_TARDIVO_SU_STANZA_GIA_PRESA_FINISCE_NELLA_LISTA(self):
        """⛔ Il sistema anti-doppia-prenotazione FUNZIONA, e non e' quello il difetto: e'
        proprio perche' si rifiuta di dare la stessa stanza due volte che il cliente resta
        pagante e senza stanza. Il sovra-affitto e' evitato, il RIMBORSO e' quello che avanza.

        Oggi quel punto marca il pendente e scrive `logger.error("RIMBORSARE: ...")` -- ma NON
        scrive nel giornale immutabile, e la lista dei rimborsi dovuti nasce dal giornale.
        Quel cliente non compare da nessuna parte: nessuno gli restituira' i soldi, perche'
        nessuno sa che aspetta. Un registro che qualcuno deve RICORDARSI di leggere non e'
        una coda di lavoro.

        VISTO ROSSO sul codice di produzione: la riga in lista non c'e'."""
        rif = self._paga_tardi_su_stanza_rubata("2026-09-18", "2026-09-20", "pi_tardivo_1")
        pagato = self._totale_ospite(rif)
        self.assertGreater(pagato, 0, "setup: il cliente deve aver pagato qualcosa")
        riga = self._riga(self._lista(), rif)
        self.assertIsNotNone(
            riga, "ha PAGATO, non ha la stanza, e non compare fra chi aspetta un rimborso")
        self.assertEqual(riga.get("dovuto_cents"), pagato,
                         "non ha avuto NIENTE in cambio: gli spetta tutto quello che ha "
                         "pagato, non una parte. Riga: %r" % (riga,))
        self.assertTrue(riga.get("bottone"),
                        "la riga c'e' ma non si puo' premere: %r" % (riga,))

    def test_STRADA_7_PAGAMENTO_SU_PRENOTAZIONE_NON_CONFERMABILE_FINISCE_NELLA_LISTA(self):
        """⛔ LA PIU' SILENZIOSA DELLE QUATTRO. Il cliente cancella PRIMA di pagare -- quindi
        non gli spetta niente, e infatti nel giornale non finisce nessuna riga -- ma il suo
        link di pagamento e' ancora vivo e il pagamento arriva lo stesso. Adesso i soldi sono
        da noi e la prenotazione non c'e' piu': non si puo' confermare (e giustamente non si
        conferma), quindi gli spetta tutto indietro.

        Oggi quel punto scrive SOLO `logger.error("RIMBORSARE: ...")` e torna: niente
        marchio, niente giornale, niente lista. E' l'unica delle sette che non lascia nemmeno
        un segno nel database -- l'unica traccia e' una riga di registro.

        VISTO ROSSO sul codice di produzione: la riga in lista non c'e'."""
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": "2026-09-22",
                       "check_out": "2026-09-24", "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ld.it"})
        self.assertEqual(s, 201, b)
        rif, vt = b["riferimento"], b["voucher_token"]
        # cancella PRIMA di pagare: non ha versato niente, non gli spetta niente
        s, canc = self.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
        self.assertEqual(s, 200, canc)
        self.assertIsNone(self._riga(self._lista(), rif),
                          "setup: senza aver pagato non deve esserci nessun rimborso dovuto")
        # ...ma il link di pagamento era ancora vivo, e il pagamento arriva lo stesso
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": "cs_tardi7", "payment_intent": "pi_tardi7",
                                             "metadata": {"riferimento": rif}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        riga = self._riga(self._lista(), rif)
        self.assertIsNotNone(
            riga, "i soldi sono arrivati su una prenotazione che non esiste piu', e chi li ha "
                  "versati non compare fra chi aspetta un rimborso: l'unica traccia e' una "
                  "riga di registro che qualcuno deve ricordarsi di leggere")
        self.assertGreater(riga.get("dovuto_cents", 0), 0,
                           "gli spetta indietro tutto quello che e' arrivato: %r" % (riga,))

    def test_STRADA_6_ANTICIPO_TARDIVO_SU_STANZA_GIA_PRESA_FINISCE_NELLA_LISTA(self):
        """⛔ COME LA 5, MA CON UNA CIFRA DIVERSA -- ed e' la cifra il punto. Nella «paga in
        struttura» online arriva SOLO l'anticipo: il saldo lo incassa l'host di persona.
        Restituire il totale renderebbe denaro che non abbiamo mai ricevuto, cioe' una
        perdita nostra su un disguido che non e' colpa di nessuno.

        VISTO ROSSO sul codice di produzione: la riga in lista non c'e'."""
        import os
        prec = os.environ.get("PAGA_STRUTTURA_ATTIVO")
        os.environ["PAGA_STRUTTURA_ATTIVO"] = "1"
        try:
            ci, co = "2026-09-25", "2026-09-27"
            s, q = self.g("POST", "/api/concierge/quote",
                          {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
            self.assertEqual(s, 200, q)
            s, b = self.g("POST", "/api/concierge/book",
                          {"quote_token": q["quote_token"], "email": "cli@ld.it",
                           "modo_pagamento": "in_struttura"})
            self.assertEqual(s, 201, b)
            self.assertEqual(b.get("modo_pagamento"), "in_struttura",
                             "setup: doveva essere una prenotazione in struttura: %r" % (b,))
            anticipo = int(b["anticipo_online_cents"])
            self.assertGreater(anticipo, 0, "setup: l'anticipo dev'essere > 0")
            self.assertLess(anticipo, int(q["totale_cents"]),
                            "setup: l'anticipo dev'essere MENO del totale, altrimenti la "
                            "prova non distingue le due cifre e non prova niente")
            rif = b["riferimento"]
            pp = self.sys.pagamenti_pendenti
            rec = pp.info(rif)
            self.assertIsNotNone(rec, "setup: il pendente deve esistere")
            pp.scadi(rif)
            self.sys.inventario.rilascia("casa", ci, co,
                                         idem_key=(rec.get("idem_key") or ("hold_" + rif)))
            ladro = self.sys.inventario.blocca("casa", ci, co, idem_key="veloce_ps_" + rif)
            self.assertTrue(getattr(ladro, "ok", False),
                            "setup: dopo il rilascio la stanza doveva essere libera")
            pl = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"id": "cs_ps", "payment_intent": "pi_ps",
                                                 "metadata": {"riferimento": rif}}}})
            self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                            {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
            riga = self._riga(self._lista(), rif)
            self.assertIsNotNone(
                riga, "ha versato l'anticipo, non ha la stanza, e non compare fra chi aspetta "
                      "un rimborso")
            self.assertEqual(
                riga.get("dovuto_cents"), anticipo,
                "l'importo non e' l'anticipo: restituire il totale rende denaro mai incassato "
                "online -- il saldo lo avrebbe preso l'host di persona. Riga: %r" % (riga,))
        finally:
            if prec is None:
                os.environ.pop("PAGA_STRUTTURA_ATTIVO", None)
            else:
                os.environ["PAGA_STRUTTURA_ATTIVO"] = prec

    def test_STRADA_4_CONTROVERSIA_RISOLTA_FINISCE_NELLA_LISTA(self):
        """⛔ LA QUARTA STRADA, e l'unica diversa dalle altre tre: qui il soggiorno C'E' STATO.
        L'arbitro decide che all'ospite spetta indietro una parte della somma in garanzia, la
        risposta dice «esegui il rimborso Stripe di questo importo (manuale, controllato)» --
        e li' finisce. Nessuna riga nel giornale, quindi nessuna riga nella lista: quel
        cliente esiste solo nella memoria di chi ha arbitrato quel giorno.

        ⚠️ LIMITE DICHIARATO (D18 punto 3): la riga compare, il PULSANTE no, e non e' un
        difetto di questa riparazione. Il freno «date liberate» pretende una prenotazione
        chiusa, e qui le date sono legittimamente occupate perche' l'ospite ha davvero
        soggiornato. Rendere premibile questa riga significa allentare DUE freni sui soldi --
        le date, e «l'host e' gia' stato pagato», che nello split parziale scatta di proposito
        perche' la quota host parte subito. E' una decisione separata: qui si chiude la
        cecita', non si tocca un freno.

        VISTO ROSSO sul codice di produzione: la riga in lista non c'e'."""
        rif, vt = self._prenota_e_paga("2026-09-28", "2026-09-30", "pi_controversia")
        s, c = self.g("POST", "/api/garanzia/contesta", {"voucher_token": vt})
        self.assertEqual(s, 200, "setup: la contestazione deve riuscire: %r" % (c,))
        s, out = self.g("POST", "/api/admin/controversia/risolvi",
                        {"riferimento": rif, "percentuale_ospite": 100},
                        {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, "setup: l'arbitrato deve riuscire: %r" % (out,))
        dovuto = int(out.get("rimborso_cliente_cents") or 0)
        self.assertGreater(dovuto, 0,
                           "setup: al 100%% all'ospite deve spettare qualcosa: %r" % (out,))
        riga = self._riga(self._lista(), rif)
        self.assertIsNotNone(
            riga, "l'arbitro ha deciso che gli spettano dei soldi, e quel cliente non compare "
                  "fra chi aspetta: la decisione vive solo nella risposta HTTP di quel momento")
        self.assertEqual(riga.get("dovuto_cents"), dovuto,
                         "l'importo in lista non e' quello deciso dall'arbitro: %r" % (riga,))

    def test_LA_VALUTA_NEL_GIORNALE_E_QUELLA_VERA_NON_SEMPRE_EURO(self):
        """⛔ QUESTO BUCO L'HA TROVATO LA MUTAZIONE, NON IO — ed e' il motivo per cui esiste.

        Le quattro strade riparate il 2026-08-17 scrivono `valuta=_dj.get("valuta") or "EUR"`,
        e TUTTE le guardie che avevo scritto erano in euro. Nove mutanti sono sopravvissuti
        perche' nessun collaudo costruiva una prenotazione in valuta straniera. Il piu' grave
        (`or` -> `and`) trasforma `"USD" and "EUR"` in **"EUR"**: una prenotazione in dollari
        finirebbe nel giornale contabile come una riga in euro, e i due importi non sono
        confrontabili. Un altro (`is not` -> `is`) svuota il record e ottiene lo stesso danno.

        ⚠️ E non e' un caso di laboratorio: il nostro regolamento prevede annunci non-euro
        PER PROGETTO (tariffa tecnica 7% + 0,25 in valuta diversa dall'euro), e il giornale
        dichiara di non sommare mai valute diverse.

        💡 Un buco di mutazione si chiude scrivendo il test che manca, non cambiando il codice:
        cambiare il codice per far tacere un mutante significa scrivere «non guardate piu' li'»
        su una riga che tocca i soldi."""
        s, _ = self.g("POST", "/api/host/pubblica",
                      {"slug": "casa-usd", "titolo": "Casa USD", "citta": "Roma",
                       "prezzo_notte_cents": 50000, "capacita": 4, "valuta": "USD",
                       "politica_cancellazione": "flessibile"}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 201, "setup: l'annuncio in USD non e' stato pubblicato")
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa-usd", "da": "2026-10-01", "a": "2026-10-31",
                "unita_totali": 1, "prezzo_netto_cents": 50000}, {"X-Host-Token": self.tok})

        def valute(rif):
            return [m.get("valuta") for m in self.sys.finanza.movimenti(str(rif))
                    if (m.get("tipo") or "") == "rimborso"]

        def paga(rif, pi_id):
            pl = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"id": "cs_" + pi_id, "payment_intent": pi_id,
                                                 "metadata": {"riferimento": rif}}}})
            self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                            {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})

        def prenota(ci, co):
            s, q = self.g("POST", "/api/concierge/quote",
                          {"alloggio_id": "casa-usd", "check_in": ci, "check_out": co,
                           "party": 2})
            self.assertEqual(s, 200, q)
            self.assertEqual(q.get("valuta"), "USD",
                             "setup: il preventivo non e' in dollari, la prova non prova "
                             "niente: %r" % (q,))
            s, b = self.g("POST", "/api/concierge/book",
                          {"quote_token": q["quote_token"], "email": "cli@usd.it"})
            self.assertEqual(s, 201, b)
            return b["riferimento"], b["voucher_token"]

        # ── STRADA 5: pagamento tardivo su stanza ripresa, in dollari ──
        ci, co = "2026-10-04", "2026-10-06"
        rif5, _ = prenota(ci, co)
        pp = self.sys.pagamenti_pendenti
        rec = pp.info(rif5)
        pp.scadi(rif5)
        self.sys.inventario.rilascia("casa-usd", ci, co,
                                     idem_key=(rec.get("idem_key") or ("hold_" + rif5)))
        ladro = self.sys.inventario.blocca("casa-usd", ci, co, idem_key="veloce_usd")
        self.assertTrue(getattr(ladro, "ok", False), "setup: la stanza doveva essere libera")
        paga(rif5, "pi_usd_5")
        self.assertEqual(valute(rif5), ["USD"],
                         "STRADA 5: il giornale ha segnato la valuta sbagliata su una "
                         "prenotazione in dollari: %r" % (valute(rif5),))

        # ── STRADA 7: pagamento su prenotazione non confermabile, in dollari ──
        rif7, vt7 = prenota("2026-10-10", "2026-10-12")
        s, _ = self.g("POST", "/api/concierge/cancella", {"voucher_token": vt7})
        self.assertEqual(s, 200)
        self.assertEqual(valute(rif7), [],
                         "setup: senza aver pagato non deve esistere nessun rimborso")
        paga(rif7, "pi_usd_7")
        self.assertEqual(valute(rif7), ["USD"],
                         "STRADA 7: valuta sbagliata nel giornale: %r" % (valute(rif7),))

        # ── STRADA 4: controversia risolta, in dollari ──
        rif4, vt4 = prenota("2026-10-16", "2026-10-18")
        paga(rif4, "pi_usd_4")
        s, cst = self.g("POST", "/api/garanzia/contesta", {"voucher_token": vt4})
        self.assertEqual(s, 200, "setup: contestazione non aperta: %r" % (cst,))
        s, out = self.g("POST", "/api/admin/controversia/risolvi",
                        {"riferimento": rif4, "percentuale_ospite": 100},
                        {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, "setup: arbitrato fallito: %r" % (out,))
        self.assertEqual(valute(rif4), ["USD"],
                         "STRADA 4 (controversia): valuta sbagliata nel giornale: %r"
                         % (valute(rif4),))

        # ── STRADA 6: anticipo «paga in struttura», in dollari ──
        # ⛔ Questa mancava nel primo giro e un mutante e' sopravvissuto proprio qui: la
        # valuta della strada 6 non era sorvegliata da nessuno.
        import os as _os
        prec = _os.environ.get("PAGA_STRUTTURA_ATTIVO")
        _os.environ["PAGA_STRUTTURA_ATTIVO"] = "1"
        try:
            ci6, co6 = "2026-10-22", "2026-10-24"
            s, q6 = self.g("POST", "/api/concierge/quote",
                           {"alloggio_id": "casa-usd", "check_in": ci6, "check_out": co6,
                            "party": 2})
            self.assertEqual(s, 200, q6)
            s, b6 = self.g("POST", "/api/concierge/book",
                           {"quote_token": q6["quote_token"], "email": "cli@usd.it",
                            "modo_pagamento": "in_struttura"})
            self.assertEqual(s, 201, b6)
            self.assertEqual(b6.get("modo_pagamento"), "in_struttura",
                             "setup: doveva essere in struttura: %r" % (b6,))
            rif6 = b6["riferimento"]
            rec6 = pp.info(rif6)
            pp.scadi(rif6)
            self.sys.inventario.rilascia("casa-usd", ci6, co6,
                                         idem_key=(rec6.get("idem_key") or ("hold_" + rif6)))
            l6 = self.sys.inventario.blocca("casa-usd", ci6, co6, idem_key="veloce_usd_6")
            self.assertTrue(getattr(l6, "ok", False), "setup: stanza doveva essere libera")
            paga(rif6, "pi_usd_6")
            self.assertEqual(valute(rif6), ["USD"],
                             "STRADA 6 (anticipo in struttura): valuta sbagliata nel "
                             "giornale: %r" % (valute(rif6),))
        finally:
            if prec is None:
                _os.environ.pop("PAGA_STRUTTURA_ATTIVO", None)
            else:
                _os.environ["PAGA_STRUTTURA_ATTIVO"] = prec

    def test_UN_RECORD_SENZA_totale_cents_NON_PERDE_L_IMPORTO(self):
        """⛔ ANCHE QUESTO L'HA TROVATO LA MUTAZIONE, e nasce da D19.

        Le righe nuove scrivono `int(_dj.get("totale_cents", 0) or
        _dj.get("prezzo_guest_cents", 0) or 0)`: un ripiego per i record che portano solo
        `prezzo_guest_cents`. Due mutanti sono sopravvissuti proprio su quel ripiego, perche'
        nessun collaudo costruiva un record fatto cosi' -- e un ramo difensivo che nessuno
        esegue e' indistinguibile da codice morto (D19). Il giorno che serve e' il giorno in
        cui il primo campo manca: il momento peggiore per scoprire che il secondo era rotto.

        Lo stato si costruisce A MANO, adesso, che costa tre righe: si toglie `totale_cents`
        dal record e si lascia `prezzo_guest_cents`. Se il ripiego non regge, il giornale
        registra ZERO e quel cliente non compare fra chi aspetta i suoi soldi."""
        import os as _os
        import sqlite3 as _sq
        ci, co = "2026-09-06", "2026-09-08"
        rif, _vt = self._prenota_e_paga_senza_pagare(ci, co)
        pp = self.sys.pagamenti_pendenti
        rec = pp.info(rif)
        dj = json.loads(rec.get("corpo_json") or "{}")
        atteso = int(dj.get("totale_cents") or 0)
        self.assertGreater(atteso, 0, "setup: il record deve avere un totale da spostare")
        dj["prezzo_guest_cents"] = atteso          # resta SOLO questo
        dj.pop("totale_cents", None)               # il primo campo NON c'e' piu'
        con = _sq.connect(_os.path.join(self.dir, "p.db"))
        with con:
            con.execute("UPDATE pendenti SET corpo_json=? WHERE riferimento=?",
                        (json.dumps(dj), rif))
        con.close()
        self.assertIsNone(json.loads(pp.info(rif)["corpo_json"]).get("totale_cents"),
                          "setup: `totale_cents` doveva essere sparito dal record")
        # ── e adesso la strada 5: pagamento tardivo su stanza ripresa ──
        pp.scadi(rif)
        self.sys.inventario.rilascia("casa", ci, co,
                                     idem_key=(rec.get("idem_key") or ("hold_" + rif)))
        ladro = self.sys.inventario.blocca("casa", ci, co, idem_key="veloce_legacy")
        self.assertTrue(getattr(ladro, "ok", False), "setup: stanza doveva essere libera")
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": "cs_legacy", "payment_intent": "pi_legacy",
                                             "metadata": {"riferimento": rif}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        importi = [int(m.get("importo_cents") or 0)
                   for m in self.sys.finanza.movimenti(str(rif))
                   if (m.get("tipo") or "") == "rimborso"]
        self.assertEqual(importi, [atteso],
                         "STRADA 5: senza `totale_cents` il ripiego su `prezzo_guest_cents` "
                         "non regge: il giornale ha registrato %r invece di %d, e quel cliente "
                         "non compare fra chi aspetta i suoi soldi" % (importi, atteso))

        # ── LA STESSA COSA SULLA STRADA 7, e non e' pignoleria ──
        # ⛔ Il primo giro di questa guardia copriva solo la strada 5, e la mutazione ha
        # lasciato VIVO il mutante gemello sulla strada 7: la stessa riga, in un percorso che
        # avevo dimenticato. Due righe identiche non sono una guardia sola: ognuna va
        # attraversata dal suo percorso, o una delle due resta cieca.
        ci7, co7 = "2026-09-11", "2026-09-13"
        rif7, vt7 = self._prenota_e_paga_senza_pagare(ci7, co7)
        rec7 = pp.info(rif7)
        dj7 = json.loads(rec7.get("corpo_json") or "{}")
        atteso7 = int(dj7.get("totale_cents") or 0)
        self.assertGreater(atteso7, 0, "setup: serve un totale da spostare")
        dj7["prezzo_guest_cents"] = atteso7
        dj7.pop("totale_cents", None)
        con = _sq.connect(_os.path.join(self.dir, "p.db"))
        with con:
            con.execute("UPDATE pendenti SET corpo_json=? WHERE riferimento=?",
                        (json.dumps(dj7), rif7))
        con.close()
        # cancella PRIMA di pagare -> la prenotazione non e' piu' confermabile...
        s, canc = self.g("POST", "/api/concierge/cancella", {"voucher_token": vt7})
        self.assertEqual(s, 200, canc)
        # ...e il pagamento arriva comunque, perche' il link era ancora vivo
        pl7 = json.dumps({"type": "checkout.session.completed",
                          "data": {"object": {"id": "cs_legacy7",
                                              "payment_intent": "pi_legacy7",
                                              "metadata": {"riferimento": rif7}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl7,
                        {"Stripe-Signature": firma_di_test(pl7, WH, int(time.time()))})
        importi7 = [int(m.get("importo_cents") or 0)
                    for m in self.sys.finanza.movimenti(str(rif7))
                    if (m.get("tipo") or "") == "rimborso"]
        self.assertEqual(importi7, [atteso7],
                         "STRADA 7: senza `totale_cents` il ripiego non regge e i soldi "
                         "arrivati su una prenotazione che non esiste piu' non vengono "
                         "reclamati da nessuno: registrato %r invece di %d"
                         % (importi7, atteso7))

    def _prenota_e_paga_senza_pagare(self, ci, co):
        """Prenota e NON paga: serve a costruire stati che il pagamento chiuderebbe."""
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ld.it"})
        self.assertEqual(s, 201, b)
        return b["riferimento"], b["voucher_token"]

    # ── PUNTO 1: la lista si CALCOLA ────────────────────────────────────────
    def test_LA_CANCELLAZIONE_DELL_OSPITE_FINISCE_NELLA_LISTA(self):
        """⛔ LA GUARDIA DEL DIFETTO. Un cliente vero paga, cancella, e oggi i suoi soldi
        restano fermi senza che da nessuna parte esista l'elenco di chi aspetta.

        VISTO ROSSO sul codice di produzione: la rotta non esiste (404), cioe' la lista non
        c'e' -- ed e' peggio di una lista sbagliata, perche' non c'e' nemmeno il posto dove
        guardare per accorgersene."""
        rif, canc = self._cancella_da_ospite("2026-09-05", "2026-09-08", "pi_ospite_1")
        self.assertGreater(canc.get("rimborso_cents", 0), 0,
                           "setup: la politica flessibile deve rendere qualcosa: %r" % (canc,))
        riga = self._riga(self._lista(), rif)
        self.assertIsNotNone(
            riga, "la prenotazione e' stata PAGATA, poi CANCELLATA dall'ospite, e i soldi non "
                  "sono partiti: deve comparire nella lista di chi aspetta. Non c'e'.")
        # L'importo e' quello CALCOLATO dalla politica, non il totale pagato: `fase111`
        # decide quanto spetta, e la lista non puo' ne' arrotondare ne' generalizzare.
        self.assertEqual(riga.get("dovuto_cents"), canc["rimborso_cents"],
                         "l'importo in lista non e' quello che la politica ha calcolato alla "
                         "cancellazione (%d): %r" % (canc["rimborso_cents"], riga))

    def test_LA_RIGA_NON_PUO_MANCARE_ANCHE_SE_IL_PENDENTE_E_STATO_PURGATO(self):
        """⛔ IL PUNTO 1 NELLA SUA FORMA PIU' DURA: la riga si regge sul GIORNALE IMMUTABILE
        (fase177), che non si purga mai, e non sulla tabella dei pendenti.

        ⚠️ Dal 2026-08-17 la pulizia di routine NON tocca piu' lo stato 'rimborsato' (con
        quel record se ne andava lo `stripe_pi`, cioe' il pulsante). Ma il pendente puo'
        sparire lo stesso -- rimozione diretta, perdita, ripristino parziale -- e in quel
        caso la riga deve restare visibile lo stesso, dicendo cosa manca. Qui il record
        viene tolto di proposito."""
        rif, _ = self._cancella_da_ospite("2026-09-10", "2026-09-12", "pi_ospite_2")
        self.assertIsNotNone(self._riga(self._lista(), rif), "setup: la riga dev'esserci prima")
        self.assertTrue(self.sys.pagamenti_pendenti.rimuovi(rif),
                        "setup: il pendente doveva esistere per poterlo togliere")
        self.assertIsNone(self.sys.pagamenti_pendenti.info(rif), "setup: pendente ancora vivo")
        riga = self._riga(self._lista(), rif)
        self.assertIsNotNone(
            riga, "la riga e' SPARITA con la purga dei pendenti: chi aspetta da piu' di 26 ore "
                  "esce dalla lista e non lo scopre nessuno. La lista non puo' reggersi su una "
                  "tabella che si cancella da sola.")
        self.assertFalse(riga.get("bottone"),
                         "senza il pendente non si conosce piu' il `pi_`: il bottone NON deve "
                         "esserci (punto 3), altrimenti si preme su un rimborso alla cieca")
        self.assertIn("payment_intent", riga.get("manca") or [],
                      "la riga non dichiara COSA manca: l'operatore non sa perche' non puo' "
                      "premere, e un dato mancante taciuto e' un finto verde")

    def test_LA_PURGA_NON_PUO_PORTARE_VIA_CHI_DEVE_RICEVERE_SOLDI(self):
        """⛔ IL PULSANTE NON PUO' SPARIRE PERCHE' SIAMO STATI NOI A BUTTARE VIA IL DATO.

        Il collaudo qui sopra prova la cosa giusta -- senza `pi_` il bottone non c'e',
        altrimenti sarebbe un rimborso alla cieca -- ma la sua PREMESSA era sbagliata, e la
        differenza sono i soldi di una persona vera. `pulisci_vecchi` non conta le ore dalla
        CANCELLAZIONE: le conta da `creato_ts`, che si scrive alla PRENOTAZIONE e non si
        aggiorna mai (fase162:119 e fase162:512). Quindi chi prenota il 1 settembre e cancella
        il 20 non aspetta 26 ore: perde il pulsante alla PRIMA pulizia utile.

        Qui la pulizia passa 27 ore dopo la PRENOTAZIONE -- cioe', nel mondo vero, un minuto
        dopo la cancellazione. Il record di chi deve ancora ricevere soldi deve essere ancora
        li'. Lo stato gemello `cancellata_host` non viene purgato affatto dalla stessa riga
        SQL: sono due stati di chiusura trattati in modo diverso, e quello che si rompe e'
        l'incoerente.

        ⛔ Non chiede di mostrare il bottone senza `pi_` (quel freno resta): chiede di non
        DISTRUGGERE il `pi_` di chi aspetta.

        VISTO ROSSO sul codice di produzione: il pendente viene cancellato, `pi_` si perde,
        `manca` contiene `payment_intent` e la riga resta in lista senza bottone -- per
        sempre, su ogni cancellazione avvenuta piu' di un giorno dopo la prenotazione."""
        ora_prenotazione = int(time.time())
        rif, canc = self._cancella_da_ospite("2026-09-14", "2026-09-16", "pi_ospite_purga")
        self.assertGreater(canc.get("rimborso_cents", 0), 0,
                           "setup: la politica flessibile deve rendere qualcosa: %r" % (canc,))
        prima = self._riga(self._lista(), rif)
        self.assertIsNotNone(prima, "setup: la riga deve esserci prima della pulizia")
        self.assertTrue(prima.get("bottone"),
                        "setup: prima della pulizia il bottone c'e': %r" % (prima,))
        # `fase83_server.py:9992` chiama `pulisci_vecchi()` senza argomenti: orologio vero e
        # soglia di 26 ore misurata su `creato_ts`. Qui si riproduce quel passaggio.
        self.sys.pagamenti_pendenti.pulisci_vecchi(ora_ts=ora_prenotazione + 27 * 3600)
        self.assertIsNotNone(
            self.sys.pagamenti_pendenti.info(rif),
            "la pulizia di routine ha portato via il record di una prenotazione che deve "
            "ancora restituire dei soldi: con lui se ne va il `pi_`, e quel rimborso non si "
            "puo' piu' eseguire dal pannello. Lo stato 'cancellata_host' non viene purgato: "
            "'rimborsato' non puo' essere trattato in modo diverso")
        riga = self._riga(self._lista(), rif)
        self.assertIsNotNone(riga, "la riga e' sparita dalla lista dopo la pulizia")
        self.assertNotIn("payment_intent", riga.get("manca") or [],
                         "il `pi_` e' stato perso da una pulizia di routine: %r" % (riga,))
        self.assertTrue(
            riga.get("bottone"),
            "il bottone non c'e' piu' dopo una pulizia di routine: il rimborso A MANO che il "
            "fondatore ha chiesto diventa impossibile dal pannello proprio nel caso NORMALE "
            "(si cancella giorni dopo aver prenotato). Riga: %r" % (riga,))

    # ── PUNTO 2: la verita' la dice Stripe ──────────────────────────────────
    def test_LA_VERITA_LA_DICE_STRIPE_NON_IL_NOSTRO_DATABASE(self):
        """Punto 2. Il nostro stato dice 'rimborsato' da sempre -- lo diceva anche il 16
        agosto, quando su Stripe non c'era un centesimo. Quindi la lista NON guarda il nostro
        stato: chiede a Stripe se su quel `pi_` esiste un `re_`."""
        rif, _ = self._cancella_da_ospite("2026-09-14", "2026-09-16", "pi_ospite_3")
        self.assertIsNotNone(self._riga(self._lista(), rif),
                             "setup: senza rimborso su Stripe la riga dev'esserci")
        letture = [c for c in CHIAMATE_LISTA if "/refunds" in c["url"] and not c["body"]]
        self.assertTrue(letture,
                        "la lista non ha MAI chiesto a Stripe se il rimborso esiste: si sta "
                        "fidando del nostro database, che il 16 agosto diceva 'rimborsato' su "
                        "un conto dove non era arrivato niente. Chiamate: %r"
                        % [c["url"] for c in CHIAMATE_LISTA])
        self.assertTrue(any("pi_ospite_3" in c["url"] for c in letture),
                        "ha interrogato Stripe, ma non sul pagamento di questa prenotazione")

    def test_SE_STRIPE_HA_GIA_RIMBORSATO_LA_RIGA_NON_C_E_PIU(self):
        """L'altra meta' del punto 2: un rimborso fatto a mano dal pannello Stripe non deve
        restare in lista, o l'operatore lo rifa' e l'ospite riceve il doppio."""
        rif, _ = self._cancella_da_ospite("2026-09-18", "2026-09-20", "pi_ospite_4")
        self.assertIsNotNone(self._riga(self._lista(), rif), "setup")
        STRIPE_FINTO["rimborsi_per_pi"]["pi_ospite_4"] = [
            {"id": "re_fatto_a_mano", "status": "succeeded", "amount": 999999}]
        self.assertIsNone(
            self._riga(self._lista(), rif),
            "Stripe dice che i soldi sono gia' tornati indietro e la riga resta in lista: "
            "l'operatore preme di nuovo e l'ospite viene rimborsato DUE volte")

    def test_ALLARME_SE_STRIPE_HA_RIMBORSATO_E_NOI_NON_NE_SAPPIAMO_NULLA(self):
        """⛔ «Vale NEI DUE SENSI»: se Stripe ha rimborsato una prenotazione che per noi non e'
        nemmeno cancellata, i conti sono divergenti e nessuno se ne accorgerebbe. Sparire in
        silenzio dalla lista NON basta: dev'essere un allarme."""
        rif, _ = self._prenota_e_paga("2026-09-22", "2026-09-24", "pi_ospite_5")
        STRIPE_FINTO["rimborsi_per_pi"]["pi_ospite_5"] = [
            {"id": "re_misterioso", "status": "succeeded", "amount": 30000}]
        corpo = self._lista()
        allarmi = corpo.get("allarmi") or []
        self.assertTrue(
            any(a.get("riferimento") == rif for a in allarmi),
            "Stripe ha restituito i soldi di una prenotazione che per noi e' viva e pagata, e "
            "la lista tace: e' una divergenza sui conti che non ha nessuno che la guardi. "
            "Allarmi visti: %r" % (allarmi,))

    # ── PUNTO 3: prima di cliccare si vede tutto ────────────────────────────
    def test_PRIMA_DI_CLICCARE_SI_VEDE_TUTTO(self):
        """Punto 3: pagato · dovuto secondo la politica · da quanto aspetta · date liberate? ·
        passi di sicurezza riusciti? Sono le cinque cose che rendono la decisione una
        decisione e non un clic."""
        rif, _ = self._cancella_da_ospite("2026-09-26", "2026-09-28", "pi_ospite_6")
        riga = self._riga(self._lista(), rif)
        self.assertIsNotNone(riga, "setup")
        for campo in ("pagato_cents", "dovuto_cents", "attesa_ore",
                      "date_liberate", "passi_sicurezza_ok"):
            self.assertIn(campo, riga,
                          "manca «%s»: si chiede all'operatore di premere un bottone sui soldi "
                          "di una persona senza dirgli tutto. Riga: %r" % (campo, riga))
        self.assertTrue(riga.get("bottone"),
                        "tutti i dati ci sono e il bottone non c'e': %r" % (riga,))

    def test_SE_MANCA_UN_DATO_IL_BOTTONE_NON_C_E(self):
        """⛔ «Se manca uno di questi il bottone NON c'e'» -- non «c'e' ma sconsigliato»: un
        bottone premibile quando non si deve, prima o poi si preme.

        Qui manca il `payment_intent` (prenotazione pagata fuori da Stripe o webhook senza
        `pi_`): non si puo' rimborsare niente, e il bottone non deve esistere."""
        rif, vt = self._prenota_e_paga("2026-09-02", "2026-09-04", "")
        s, canc = self.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
        self.assertEqual(s, 200, canc)
        riga = self._riga(self._lista(), rif)
        self.assertIsNotNone(
            riga, "senza `pi_` la riga sparisce del tutto: quei soldi non li reclama piu' "
                  "nessuno. Deve restare visibile, con scritto cosa manca")
        self.assertFalse(riga.get("bottone"),
                         "il bottone c'e' su una riga senza pagamento identificabile: "
                         "premerlo non restituisce niente e fa credere il contrario: %r" % (riga,))
        self.assertTrue(riga.get("manca"),
                        "non dichiara cosa manca: l'operatore vede un bottone spento e non sa "
                        "cosa fare -- e quello che non si sa fare non si fa")

    def _totale_ospite(self, rif):
        rec = self.sys.pagamenti_pendenti.info(rif) or {}
        dj = json.loads(rec.get("corpo_json") or "{}")
        return int(dj.get("totale_cents", 0) or dj.get("prezzo_guest_cents", 0) or 0)

    @staticmethod
    def _rimborsi_inviati():
        return [c for c in CHIAMATE_LISTA if "/refunds" in c["url"] and c["body"]]

    # ── PUNTO 4: i quattro freni sul denaro ─────────────────────────────────
    # ⛔ I DUE QUI SOTTO NON LI HO SCRITTI PERCHE' MI SONO VENUTI IN MENTE: li ha trovati
    # LA MUTAZIONE. Spegnendo il freno 1 e il freno 3 i test restavano VERDI — 3 giri su 3
    # ognuno — cioe' due dei quattro freni sui soldi non erano sorvegliati da nessuno,
    # perche' nessun collaudo costruiva mai lo stato in cui quel freno serve.
    # Un buco di mutazione si chiude scrivendo il test che manca, non cambiando il codice.
    def test_FRENO_1_UNA_RIGA_CHE_CHIEDE_PIU_DEL_PAGATO_NON_HA_IL_BOTTONE(self):
        """L'ingresso che distingue il codice sano dal guasto, MISURATO e non dichiarato (B6):
        una prenotazione incassata X, il cui giornale dichiara dovuto 10 volte X.

        Come ci si arriva nel mondo vero: un errore nel calcolo della politica, o una tassa
        contata due volte. Il freno non serve quando i conti tornano — serve **quel** giorno,
        ed e' l'unico giorno in cui nessuno lo sta guardando."""
        rif, vt = self._prenota_e_paga("2026-09-04", "2026-09-06", "pi_ospite_14")
        pagato = self._totale_ospite(rif)
        self.assertGreater(pagato, 0, "setup: il totale incassato dev'essere noto")
        # `evento_id` vale 'rimborso:<rif>' ed e' IDEMPOTENTE: questa riga scritta PRIMA
        # vince sulla cancellazione che segue, che trovera' l'evento gia' presente.
        self.sys.finanza.movimento(tipo="rimborso", riferimento=rif,
                                   soggetto="ospite:" + rif, importo_cents=pagato * 10,
                                   valuta="EUR", causale="prova: dovuto maggiore del pagato")
        s, canc = self.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
        self.assertEqual(s, 200, canc)
        riga = self._riga(self._lista(), rif)
        self.assertIsNotNone(riga, "setup: la riga dev'essere in lista")
        self.assertGreater(riga["dovuto_cents"], riga["pagato_cents"],
                           "setup: il giornale doveva dichiarare piu' dell'incassato: %r" % (riga,))
        self.assertIn("dovuto_maggiore_del_pagato", riga.get("manca") or [],
                      "la lista propone di restituire piu' di quanto l'ospite ha versato e "
                      "non lo dichiara: %r" % (riga,))
        self.assertFalse(riga.get("bottone"),
                         "il bottone e' premibile su una riga che farebbe uscire dalla cassa "
                         "piu' di quanto e' entrato: la differenza la mettiamo noi (D16)")
        s, res = self.g("POST", "/api/admin/rimborsa_dovuto",
                        {"riferimento": rif}, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 409, "il pulsante doveva rifiutare: %r" % (res,))
        self.assertEqual(self._rimborsi_inviati(), [],
                         "sono partiti soldi per un importo maggiore dell'incassato")

    def test_FRENO_3_SE_IL_BONIFICO_ALL_HOST_E_GIA_PARTITO_NON_SI_RIMBORSA(self):
        """L'ingresso che distingue: il payout di quella prenotazione e' in stato `pagato`.

        ⛔ E' la PERDITA PIENA che D16 vieta: l'host ha gia' incassato, e se restituiamo
        anche all'ospite la stessa prenotazione e' stata pagata DUE volte — la seconda con
        soldi nostri. Il percorso e' quello vero (`trattenuto -> in_transito -> pagato`), non
        una scrittura a mano nel database: le transizioni sono quelle che il modulo consente."""
        rif, _ = self._cancella_da_ospite("2026-09-08", "2026-09-10", "pi_ospite_15")
        self.assertTrue(self.sys.payout.aggiorna_stato(rif, "in_transito"), "setup")
        self.assertTrue(self.sys.payout.aggiorna_stato(rif, "pagato"), "setup")
        self.assertEqual(self.sys.payout.stato_di(rif), "pagato",
                         "setup: il bonifico all'host doveva risultare gia' partito")
        riga = self._riga(self._lista(), rif)
        self.assertIsNotNone(riga, "setup: la riga dev'essere in lista")
        self.assertIn("payout_gia_pagato", riga.get("manca") or [],
                      "l'host e' gia' stato pagato e la lista non lo dichiara: %r" % (riga,))
        self.assertFalse(riga.get("passi_sicurezza_ok"),
                         "dice che i soldi sono in sicurezza mentre sono gia' usciti: %r" % (riga,))
        self.assertFalse(riga.get("bottone"),
                         "il bottone e' premibile: un clic e la stessa prenotazione e' pagata "
                         "due volte, la seconda a carico nostro")
        s, res = self.g("POST", "/api/admin/rimborsa_dovuto",
                        {"riferimento": rif}, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 409, "il pulsante doveva rifiutare: %r" % (res,))
        self.assertEqual(self._rimborsi_inviati(), [],
                         "PERDITA PIENA: rimborsato l'ospite su una prenotazione il cui "
                         "bonifico all'host era gia' partito")

    def test_FRENO_MAI_PIU_DI_QUANTO_HA_PAGATO(self):
        """Freno 1 (aritmetico, non un'opinione). Il dovuto non puo' superare l'incassato: se
        succede e' un difetto del calcolo, e va fermato PRIMA di diventare un bonifico."""
        rif, _ = self._cancella_da_ospite("2026-09-06", "2026-09-09", "pi_ospite_7")
        riga = self._riga(self._lista(), rif)
        self.assertIsNotNone(riga, "setup")
        self.assertLessEqual(
            riga["dovuto_cents"], riga["pagato_cents"],
            "la lista propone di restituire piu' di quanto l'ospite ha versato: la differenza "
            "la mettiamo noi (D16, mai in perdita)")

    def test_FRENO_IL_PULSANTE_PREMUTO_DUE_VOLTE_NON_RIMBORSA_DUE_VOLTE(self):
        """Freno 2: chiave d'idempotenza stabile. Rete che cade o doppio clic non raddoppiano.
        E dopo il primo clic la riga esce dalla lista perche' STRIPE la conferma, non perche'
        l'abbiamo tolta noi (il finto provider ricorda i rimborsi creati)."""
        rif, _ = self._cancella_da_ospite("2026-09-11", "2026-09-13", "pi_ospite_8")
        riga = self._riga(self._lista(), rif)
        self.assertIsNotNone(riga, "setup")
        for _ in range(2):
            s, res = self.g("POST", "/api/admin/rimborsa_dovuto",
                            {"riferimento": rif}, {"X-Admin-Key": "ak"})
            self.assertEqual(s, 200, "il pulsante della lista non risponde: %r" % (res,))
        creazioni = [c for c in CHIAMATE_LISTA if "/refunds" in c["url"] and c["body"]]
        self.assertEqual(len(creazioni), 1,
                         "due richieste di rimborso per la stessa prenotazione: l'ospite "
                         "riceve il doppio e la differenza la mettiamo noi. Viste: %r"
                         % [c["body"] for c in creazioni])
        chiave = {k.lower(): v for k, v in creazioni[0]["headers"].items()}.get("idempotency-key", "")
        self.assertIn(rif, chiave,
                      "la chiave d'idempotenza non e' legata alla prenotazione (%r): non "
                      "protegge da un ritentativo di rete" % (chiave,))
        self.assertIsNone(self._riga(self._lista(), rif),
                          "rimborsato e ancora in lista: l'operatore lo rifara'")

    def test_FRENO_NON_SI_RIMBORSA_SE_I_PASSI_DI_SICUREZZA_NON_SONO_RIUSCITI(self):
        """Freno 3 (D16). Se il payout all'host e' gia' partito, rimborsare significa pagare
        DUE volte la stessa prenotazione, e la seconda la paghiamo noi. Nel dubbio i soldi non
        partono da soli: si grida e decide una persona."""
        class _Rotto:
            def __getattr__(self, nome):
                def _boom(*a, **k):
                    raise RuntimeError("componente guasto: %s" % nome)
                return _boom

        rif, _ = self._cancella_da_ospite("2026-09-16", "2026-09-18", "pi_ospite_9")
        self.sys.payout = _Rotto()
        riga = self._riga(self._lista(), rif)
        self.assertIsNotNone(riga, "setup")
        s, res = self.g("POST", "/api/admin/rimborsa_dovuto",
                        {"riferimento": rif}, {"X-Admin-Key": "ak"})
        creazioni = [c for c in CHIAMATE_LISTA if "/refunds" in c["url"] and c["body"]]
        self.assertEqual(creazioni, [],
                         "i soldi sono partiti mentre il payout non era in sicurezza: "
                         "rischio di pagare due volte la stessa prenotazione")

    def test_FRENO_L_IMPORTO_NON_SI_SCRIVE_A_MANO(self):
        """Freno 4: la cifra la calcola `fase111` e l'operatore la conferma. Un importo
        arrivato dalla richiesta e' una cifra scritta a mano su soldi veri."""
        rif, canc = self._cancella_da_ospite("2026-09-21", "2026-09-23", "pi_ospite_10")
        s, res = self.g("POST", "/api/admin/rimborsa_dovuto",
                        {"riferimento": rif, "importo_cents": 999999}, {"X-Admin-Key": "ak"})
        creazioni = [c for c in CHIAMATE_LISTA if "/refunds" in c["url"] and c["body"]]
        self.assertEqual(len(creazioni), 1, "nessun rimborso inviato: %r" % (res,))
        self.assertNotIn("amount=999999", creazioni[0]["body"],
                         "ha rimborsato la cifra arrivata dalla RICHIESTA: chiunque possa "
                         "chiamare la rotta sceglie quanto far uscire dalla cassa")

    # ── PUNTO 5: il tempo diventa visibile ──────────────────────────────────
    def test_IL_TEMPO_E_VISIBILE_E_IL_CONTO_STA_IN_CIMA(self):
        """Punto 5. In UE i rimborsi hanno un termine di legge: una coda senza scadenza non e'
        una coda, e' un cassetto."""
        rif, _ = self._cancella_da_ospite("2026-09-24", "2026-09-26", "pi_ospite_11")
        corpo = self._lista()
        self.assertEqual(corpo.get("in_attesa"), len(corpo.get("rimborsi") or []),
                         "il numero in cima non coincide con le righe: %r" % (corpo,))
        self.assertGreaterEqual(corpo["in_attesa"], 1)
        riga = self._riga(corpo, rif)
        self.assertIsInstance(riga.get("attesa_ore"), int,
                              "non si sa da quanto quella persona aspetta: %r" % (riga,))

    # ── PUNTO 6: lo strumento controlla se stesso (D18 condizione 1) ────────
    def test_SE_NON_PUO_INTERROGARE_STRIPE_NON_DICE_LISTA_VUOTA(self):
        """⛔ LISTA VUOTA = «niente da fare». LISTA NON CARICATA = «non lo so». Confonderle e'
        il modo esatto in cui un cassiere si convince che la cassa e' a posto.

        Qui Stripe non risponde: la lista NON deve presentarsi come vuota e in ordine."""
        rif, _ = self._cancella_da_ospite("2026-09-27", "2026-09-29", "pi_ospite_12")
        STRIPE_FINTO["esplode"] = True
        corpo = self._lista()
        self.assertIs(corpo.get("controllabile"), False,
                      "Stripe e' irraggiungibile e la lista si dichiara attendibile lo stesso: "
                      "%r" % (corpo,))
        self.assertTrue(corpo.get("motivo_non_controllabile"),
                        "dice «non controllabile» senza dire perche': un osservabile debole e' "
                        "un difetto (regola ferrea 9)")
        for riga in (corpo.get("rimborsi") or []):
            self.assertFalse(riga.get("bottone"),
                             "offre il bottone senza aver potuto verificare su Stripe se il "
                             "rimborso e' gia' stato fatto: si rischia il doppio rimborso")

    def test_SENZA_IL_GIORNALE_NON_INVENTA_UNA_LISTA_VUOTA(self):
        """Stessa regola, guasto diverso: se il giornale immutabile e' spento la domanda non
        si puo' nemmeno porre. Deve dirlo, non rispondere «zero»."""
        self.sys.finanza = None
        corpo = self._lista()
        self.assertIs(corpo.get("controllabile"), False,
                      "il giornale e' spento e la lista risponde «nessun rimborso dovuto»: "
                      "e' un silenzio che sembra una buona notizia. %r" % (corpo,))

    # ── prova di rimozione: e se NON c'e' niente da rimborsare? ─────────────
    def test_A_MACCHINA_SANA_LA_LISTA_TACE(self):
        """Regola ferrea 10: un falso allarme e' un difetto quanto un allarme mancato. Una
        prenotazione pagata e MAI cancellata non deve comparire; una cancellata e MAI pagata
        nemmeno (non c'e' niente da restituire)."""
        self._prenota_e_paga("2026-09-03", "2026-09-05", "pi_sano_1")
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": "2026-09-07",
                       "check_out": "2026-09-09", "party": 2})
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ld.it"})
        self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        corpo = self._lista()
        self.assertIs(corpo.get("controllabile"), True, corpo)
        self.assertEqual(corpo.get("rimborsi"), [],
                         "grida su prenotazioni che non hanno nulla da restituire: un allarme "
                         "che grida sempre viene spento. %r" % (corpo,))

    def test_UN_RIFERIMENTO_OSTILE_NON_PUO_SCRIVERE_NEL_REGISTRO(self):
        """⛔ TROVATO DA CODEQL SULLA RICHIESTA DI UNIONE #59 (14 allarmi, 7 gravi), non da
        noi: `riferimento` arriva dal corpo della richiesta e finisce nel registro.

        Perche' qui e' peggio che altrove: **il Guardiano (fase186) legge gli ERROR del
        registro ogni giorno** — e' cosi' che un guasto sui soldi diventa visibile entro 24
        ore. Chi puo' infilare un a-capo dentro un riferimento puo' scrivere righe di allarme
        FALSE nel posto dove guardiamo per sapere se e' tutto a posto: puo' inventare un
        rimborso che non c'e' stato, o annegare quello vero.

        ⚠️ ONESTA' SUL RISCHIO: non ho dimostrato che oggi sia sfruttabile davvero (con un
        riferimento inventato il giornale non trova niente e la rotta esce 404 senza
        scrivere). Ma «oggi non si raggiunge» e' una conclusione **con una premessa**, non una
        proprieta' — e la premessa e' il comportamento di un'altra funzione (D19). Il giorno
        che cade, la cecita' resta. Qui si chiude come proprieta': un riferimento che non ha
        la forma di un riferimento non entra, e quindi non puo' finire da nessuna parte.

        Un riferimento vero e' `hmac-sha256:e9a39409f6d8` — 24 caratteri, misurato su 300
        generati: alfabeto `[0-9a-f:-]`. Niente spazi, niente a-capo, niente byte di controllo.
        """
        import logging as _lg

        class _Cattura(_lg.Handler):
            def __init__(self):
                _lg.Handler.__init__(self)
                self.righe = []

            def emit(self, record):
                try:
                    self.righe.append(record.getMessage())
                except Exception:
                    self.righe.append(str(record.msg))

        class _GiornaleRotto:
            def __getattr__(self, nome):
                def _boom(*a, **k):
                    raise RuntimeError("giornale guasto")
                return _boom

        ostile = ("hmac-sha256:aaaaaaaaaaaa\n"
                  "2026-08-16 03:00:00 ERROR core_auto.server RIMBORSO ESEGUITO "
                  "rif=vittima importo=9999999 stripe=re_falso")
        # Forzo il ramo che SCRIVE davvero nel registro: senza, la prova non attraversa
        # il punto guasto e sarebbe verde per il motivo sbagliato.
        self.sys.finanza = _GiornaleRotto()
        cattura = _Cattura()
        radice = _lg.getLogger("core_auto")
        radice.addHandler(cattura)
        try:
            s, res = self.g("POST", "/api/admin/rimborsa_dovuto",
                            {"riferimento": ostile}, {"X-Admin-Key": "ak"})
        finally:
            radice.removeHandler(cattura)
        self.assertEqual(s, 422,
                         "un riferimento con un a-capo dentro non e' un riferimento: va "
                         "rifiutato al confine, non trascinato dentro. Risposta: %r" % (res,))
        scritte = "\n".join(cattura.righe)
        self.assertNotIn("RIMBORSO ESEGUITO", scritte,
                         "il registro contiene una riga di allarme FABBRICATA da chi ha "
                         "chiamato la rotta: il Guardiano legge di qui. Scritte: %r"
                         % (cattura.righe,))
        for riga in cattura.righe:
            self.assertNotIn("\n", riga,
                             "una riga del registro contiene un a-capo scelto da FUORI: da "
                             "li' in poi chi legge il registro vede due righe dove ce n'era "
                             "una, e la seconda l'ha scritta un estraneo. Riga: %r" % (riga,))

    def test_LA_SCHEDA_NON_SCRIVE_NEL_REGISTRO_QUELLO_CHE_LE_DANNO(self):
        """⛔ LA DIFESA NON DEVE DIPENDERE DA CHI CHIAMA (D19).

        Il controllo al confine (`_admin_rimborsa_dovuto` rifiuta 422) e' giusto e resta, ma
        rende sicura **quella rotta**, non la funzione: `_rimborso_dovuto_scheda` e' chiamata
        anche dalla lista, e domani da qualcun altro. Se la garanzia «nel registro non finisce
        un a-capo scelto da fuori» vive solo nel chiamante, il giorno che nasce un secondo
        chiamante la garanzia sparisce **senza che nessuno tocchi questa funzione**.

        Qui la funzione viene chiamata DIRETTAMENTE, scavalcando la rotta: e' il modo di
        provare che regge da sola. E' anche cio' che CodeQL continuava a segnalare dopo la
        prima riparazione -- aveva ragione lui.
        """
        import logging as _lg

        class _Cattura(_lg.Handler):
            def __init__(self):
                _lg.Handler.__init__(self)
                self.righe = []

            def emit(self, record):
                try:
                    self.righe.append(record.getMessage())
                except Exception:
                    self.righe.append(str(record.msg))

        class _GiornaleRotto:
            def __getattr__(self, nome):
                def _boom(*a, **k):
                    raise RuntimeError("giornale guasto")
                return _boom

        ostile = ("hmac-sha256:bbbbbbbbbbbb\n"
                  "2026-08-17 04:00:00 ERROR core_auto.server RIMBORSO ESEGUITO "
                  "rif=vittima importo=8888888 stripe=re_inventato")
        self.sys.finanza = _GiornaleRotto()
        cattura = _Cattura()
        radice = _lg.getLogger("core_auto")
        radice.addHandler(cattura)
        try:
            self.r._rimborso_dovuto_scheda(ostile)     # chiamata DIRETTA, senza la rotta
        finally:
            radice.removeHandler(cattura)
        self.assertTrue(cattura.righe,
                        "setup: doveva scrivere qualcosa nel registro, altrimenti la prova "
                        "non attraversa il punto guasto ed e' verde per il motivo sbagliato")
        for riga in cattura.righe:
            self.assertNotIn("\n", riga,
                             "una riga del registro contiene un a-capo arrivato da fuori: chi "
                             "legge il registro vede due righe dove ce n'era una, e la seconda "
                             "l'ha scritta un estraneo. Riga: %r" % (riga,))
            self.assertNotIn("RIMBORSO ESEGUITO", riga,
                             "riga di allarme FABBRICATA da chi ha passato il riferimento: il "
                             "Guardiano legge di qui per sapere se e' tutto a posto. %r" % (riga,))

    def test_UN_RIFERIMENTO_VERO_NON_VIENE_RIFIUTATO(self):
        """Prova di rimozione (regola ferrea 10): il controllo nuovo deve TACERE sui
        riferimenti veri, o e' un falso allarme che blocca rimborsi legittimi — e un allarme
        che grida sempre viene spento."""
        rif, _ = self._cancella_da_ospite("2026-09-19", "2026-09-21", "pi_ospite_13")
        self.assertRegex(rif, r"^[A-Za-z0-9:_.-]{1,64}$",
                         "setup: il riferimento vero non passa nemmeno la forma attesa")
        s, res = self.g("POST", "/api/admin/rimborsa_dovuto",
                        {"riferimento": rif}, {"X-Admin-Key": "ak"})
        self.assertNotEqual(s, 422,
                           "un riferimento VERO viene rifiutato come malformato: %r" % (res,))

    # ── COLLAUDO 5: L'ORACOLO INDIPENDENTE ──────────────────────────────────
    def test_ORACOLO_INDIPENDENTE_L_IMPORTO_IN_LISTA_RICALCOLATO_DA_ZERO(self):
        """⛔ LA DOMANDA CHE NESSUN ALTRO COLLAUDO FA: **e se fosse il motore a sbagliare?**

        Tutti gli altri test confrontano il prodotto con se stesso: chiedono al sistema
        quanto spetta e poi verificano che la lista mostri quel numero. Se `fase111`
        sbagliasse, sbaglierebbero **insieme** e resterebbero verdi.

        Qui il conto lo rifa' `_oracolo_rimborso`, scritto a mano dalla politica pubblica,
        senza importare `fase111` e con un'aritmetica scritta diversa apposta (percento
        invece di bps). Se i due divergono, uno dei due ha torto -- ed e' il momento di
        scoprirlo, non quando lo scopre un ospite.

        ⚠️ Date RELATIVE a oggi, mai cablate: una data fissa in un collaudo e' una bomba a
        tempo che esplode il giorno che nessuno se lo aspetta."""
        import datetime as _dt
        oggi = _dt.date.today()

        def _g(n):
            return (oggi + _dt.timedelta(days=n)).isoformat()

        # Quattro casi scelti per attraversare TUTTI i rami: le tre percentuali della
        # politica (100/50/0) e la finestra di ripensamento, che vince su tutte.
        casi = [
            ("flex", "flessibile", 2, "arrivo fra 2 giorni: la flessibile rende tutto"),
            ("mod", "moderata", 2, "arrivo fra 2 giorni: la moderata rende meta'"),
            ("rig", "rigida", 2, "arrivo fra 2 giorni: la rigida non rende niente"),
            ("rip", "rigida", 40, "arrivo lontano: il ripensamento vince sulla rigida"),
        ]
        for slug, politica, fra, _perche in casi:
            self.g("POST", "/api/host/pubblica",
                   {"slug": slug, "titolo": "Casa " + slug, "citta": "Roma",
                    "prezzo_notte_cents": 50000, "capacita": 4,
                    "politica_cancellazione": politica}, {"X-Host-Token": self.tok})
            self.g("POST", "/api/host/disponibilita_range",
                   {"alloggio_id": slug, "da": _g(0), "a": _g(60),
                    "unita_totali": 1, "prezzo_netto_cents": 50000},
                   {"X-Host-Token": self.tok})

        provati = 0
        for i, (slug, politica, fra, perche) in enumerate(casi):
            ci, co = _g(fra), _g(fra + 2)
            s, q = self.g("POST", "/api/concierge/quote",
                          {"alloggio_id": slug, "check_in": ci, "check_out": co, "party": 2})
            self.assertEqual(s, 200, "setup %s: %r" % (slug, q))
            s, b = self.g("POST", "/api/concierge/book",
                          {"quote_token": q["quote_token"], "email": "cli@or.it"})
            self.assertEqual(s, 201, "setup %s: %r" % (slug, b))
            rif, vt = b["riferimento"], b["voucher_token"]
            pl = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"id": "cs_or%d" % i,
                                                 "payment_intent": "pi_oracolo_%d" % i,
                                                 "metadata": {"riferimento": rif}}}})
            self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                            {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
            pagato = self._totale_ospite(rif)
            self.assertGreater(pagato, 0, "setup %s: incasso ignoto" % slug)
            s, canc = self.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
            self.assertEqual(s, 200, "setup %s: %r" % (slug, canc))

            atteso = _oracolo_rimborso(pagato, fra, politica, entro_ripensamento=True)
            riga = self._riga(self._lista(), rif)
            if atteso == 0:
                self.assertIsNone(
                    riga, "%s (%s): l'oracolo dice che non spetta NIENTE, e la lista "
                          "propone comunque un rimborso: %r" % (slug, perche, riga))
                provati += 1
                continue
            self.assertIsNotNone(riga, "%s (%s): l'oracolo dice che spettano %d cents e la "
                                       "riga non c'e'" % (slug, perche, atteso))
            self.assertEqual(
                riga["dovuto_cents"], atteso,
                "%s (%s): DUE CONTI DIVERSI sulla stessa cancellazione. Il motore dice %d, "
                "il secondo calcolo dice %d su %d pagati a %d giorni dall'arrivo con "
                "politica '%s'. Uno dei due ha torto."
                % (slug, perche, riga["dovuto_cents"], atteso, pagato, fra, politica))
            provati += 1
        self.assertEqual(provati, len(casi),
                         "setup: non tutti i casi sono stati attraversati")

    # ── COLLAUDO 6: LA CONCORRENZA VERA ─────────────────────────────────────
    def test_DUE_OPERATORI_NELLO_STESSO_ISTANTE_NON_RIMBORSANO_DUE_VOLTE(self):
        """⛔ NON e' il doppio clic (gia' provato altrove): sono DUE PERSONE, due richieste
        davvero simultanee, che nessun controllo «guarda-poi-agisci» puo' separare.

        Il buco c'e' ed e' onesto dirlo: fra il momento in cui chiediamo a Stripe «esiste
        gia' un rimborso?» e il momento in cui glielo chiediamo di fare, passa del tempo.
        Due richieste possono attraversare quella finestra insieme, e **il nostro codice da
        solo non le separa**. Cio' che le separa e' l'`Idempotency-Key` STABILE: e' la nostra
        meta' del contratto, e questa prova verifica proprio quella.

        🔎 Ricerca (D25, docs.stripe.com/api/idempotent_requests): richieste successive con
        la stessa chiave tornano lo stesso risultato. ⚠️ Limite dichiarato dalla stessa
        fonte: l'esito idempotente viene salvato solo DOPO che l'esecuzione e' iniziata,
        quindi due richieste *davvero* simultanee possono confliggere ed essere ritentabili.
        Non e' una rete perfetta -- ma senza una chiave stabile non ci sarebbe rete affatto,
        e sarebbero due rimborsi veri."""
        rif, _ = self._cancella_da_ospite("2026-09-29", "2026-09-30", "pi_concorrenza")
        riga = self._riga(self._lista(), rif)
        self.assertIsNotNone(riga, "setup: la riga dev'essere pronta")
        self.assertTrue(riga.get("bottone"), "setup: %r" % (riga,))
        dovuto = riga["dovuto_cents"]

        # Due cancelletti, e servono tutti e due. Il primo fa PARTIRE i fili insieme; il
        # secondo (dentro il finto Stripe) li fa incontrare DENTRO la creazione del rimborso.
        # Solo il secondo produce la gara vera: senza, il primo filo finisce tutto il giro
        # prima che il secondo cominci, e il collaudo diventa un doppio clic lento.
        STRIPE_FINTO["barriera_rimborso"] = threading.Barrier(2, timeout=30)
        cancelletto = threading.Barrier(2)
        esiti = []

        def _premi():
            cancelletto.wait()          # partono nello STESSO istante, non uno dopo l'altro
            try:
                esiti.append(self.g("POST", "/api/admin/rimborsa_dovuto",
                                    {"riferimento": rif}, {"X-Admin-Key": "ak"}))
            except Exception as exc:     # pragma: no cover
                esiti.append(("eccezione", repr(exc)))

        fili = [threading.Thread(target=_premi) for _ in range(2)]
        for f in fili:
            f.start()
        for f in fili:
            f.join(timeout=60)
        self.assertEqual(len(esiti), 2, "setup: entrambe le richieste devono aver risposto")

        creazioni = self._rimborsi_inviati()
        chiavi = {({k.lower(): v for k, v in c["headers"].items()}).get("idempotency-key", "")
                  for c in creazioni}
        # (a) LA NOSTRA META' DEL CONTRATTO: una chiave sola, stabile, legata alla
        #     prenotazione. Se ne generassimo una per richiesta, Stripe non potrebbe
        #     proteggerci e sarebbero DUE rimborsi veri sul conto dell'ospite.
        self.assertEqual(len(chiavi), 1,
                         "le due richieste portano chiavi d'idempotenza DIVERSE (%r): Stripe "
                         "le vede come due rimborsi distinti e l'ospite riceve il doppio"
                         % (chiavi,))
        self.assertIn(rif, list(chiavi)[0],
                      "la chiave non e' legata alla prenotazione: %r" % (chiavi,))
        # (b) L'EFFETTO: un solo rimborso ESISTE, e vale quanto dovuto -- non il doppio.
        creati = STRIPE_FINTO["rimborsi_per_pi"].get("pi_concorrenza", [])
        self.assertEqual(len(creati), 1,
                         "sul pagamento dell'ospite risultano %d rimborsi: due operatori "
                         "nello stesso istante gli hanno restituito i soldi due volte. %r"
                         % (len(creati), creati))
        self.assertEqual(creati[0]["amount"], dovuto,
                         "l'importo restituito non e' quello dovuto: %r" % (creati,))
        # (c) E la riga esce dalla lista, una volta sola.
        self.assertIsNone(self._riga(self._lista(), rif),
                          "rimborsato e ancora in lista")

    def test_LA_LISTA_E_CHIUSA_A_CHI_NON_E_ADMIN(self):
        """La lista dice chi ha pagato quanto e chi aspetta dei soldi: e' un elenco di dati
        personali e finanziari. Senza chiave si risponde 401, non la lista."""
        s, _ = self.g("GET", "/api/admin/rimborsi_dovuti", None, {})
        self.assertEqual(s, 401, "la lista dei rimborsi e' aperta a chiunque")
        s, _ = self.g("POST", "/api/admin/rimborsa_dovuto", {"riferimento": "x"}, {})
        self.assertEqual(s, 401, "chiunque puo' far uscire soldi dalla cassa")


class TestIlPannelloEDAVVEROCollegato(unittest.TestCase):
    """⛔ COSTRUITO ≠ COLLEGATO. Una rotta perfetta che nessuna pagina chiama e' il modo di
    rompersi numero 2 («il pezzo e' perfetto e non e' collegato»): la lista esisterebbe, i
    collaudi sarebbero verdi, e nel pannello non comparirebbe niente. E' successo davvero al
    guardiano del piano dei soldi, che girava solo dentro la suite da 25 minuti.

    Guardie STATICHE sul file che l'operatore apre davvero."""

    @classmethod
    def setUpClass(cls):
        import io as _io
        import os as _os
        percorso = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                 "deploy", "admin.html")
        with _io.open(percorso, encoding="utf-8") as f:
            cls.HTML = f.read()

    def test_la_cifra_della_controversia_si_scrive_in_EURO_non_solo_in_PERCENTO(self):
        """⛔ ORDINE DEL FONDATORE, 2026-08-17: *«le controversie io devo scegliere la cifra da
        dare a uno e all'altro»*.

        Il pannello accettava **solo una percentuale intera** (`admin.html`, campo `pct_`), e
        la cifra la calcolava lui: `Math.round(importo * pct / 100)`. Con 347,50 € in garanzia
        NON ESISTE una percentuale intera che dia 200,00 € — quindi l'importo che l'arbitro ha
        deciso, e che deve poter dichiarare, **non era scrivibile**. Non e' una comodita': su
        una decisione arbitrale la cifra e' il contenuto della decisione.

        💡 Il motore accettava GIA' la cifra esatta (`rimborso_ospite_cents`, e il suo ramo
        viene PRIMA di quello della percentuale): mancava solo il campo nel pannello. Ed e' la
        regola 23 in forma nuova — **costruito ≠ raggiungibile**: una possibilita' che il
        motore offre e che nessuna interfaccia espone, per chi la usa non esiste.

        ⚠️ Il limite superiore lo impone il SERVER (`min(rimborso, importo)`), non il browser:
        il campo aiuta, non protegge.

        VISTO ROSSO sul pannello di produzione: nessun campo in euro, e la richiesta partiva
        sempre e solo con `percentuale_ospite`."""
        self.assertIn(
            "rimborso_ospite_cents", self.HTML,
            "il pannello non manda MAI la cifra esatta: si puo' scrivere solo una percentuale, "
            "quindi l'importo deciso dall'arbitro resta non dichiarabile")
        self.assertIn(
            "eur_${i}", self.HTML,
            "manca il campo in EURO accanto a quello in percento: la cifra da dare all'ospite "
            "non si puo' scrivere")
        self.assertIn(
            "ctr_host", self.HTML,
            "il pannello non mostra quanto resta all'host: l'arbitro decide due cifre e ne "
            "vede una sola")

    def test_il_pannello_chiama_le_due_rotte(self):
        self.assertIn("/api/admin/rimborsi_dovuti", self.HTML,
                      "il pannello non chiede MAI la lista: la rotta esiste e non la vede nessuno")
        self.assertIn("/api/admin/rimborsa_dovuto", self.HTML,
                      "non c'e' il pulsante che restituisce i soldi")

    def test_il_numero_di_chi_aspetta_si_vede_senza_premere_niente(self):
        """Punto 5. Una coda che bisogna ricordarsi di caricare e' una coda che qualcuno
        dimentichera'."""
        self.assertIn("caricaRimborsiDovuti()", self.HTML)
        blocco = self.HTML.split("DOMContentLoaded", 1)
        self.assertEqual(len(blocco), 2, "manca l'aggancio all'apertura della pagina")
        self.assertIn("caricaRimborsiDovuti", blocco[1][:400],
                      "la lista si carica solo premendo un tasto: chi non lo preme non sa "
                      "che c'e' una persona che aspetta i suoi soldi")

    def test_il_tasto_e_protetto_dal_doppio_clic(self):
        """Su un tasto che muove denaro il doppio clic non e' un fastidio: e' un secondo
        rimborso."""
        import re as _re
        m = _re.search(r"scudoTasti\(\[(.*?)\]\)", self.HTML, _re.S)
        self.assertIsNotNone(m, "manca la chiamata scudoTasti")
        self.assertIn("btnRimborsiDovuti", m.group(1))
        self.assertIn("conScudo(this,()=>eseguiRimborsoDovuto(", self.HTML,
                      "il pulsante di ogni riga non ha lo scudo anti-doppio-clic")

    def test_NON_CONTROLLABILE_non_si_disegna_come_NESSUN_RIMBORSO(self):
        """⛔ La guardia che conta davvero sull'interfaccia: «non ho potuto controllare» e
        «non c'e' niente da fare» devono APPARIRE DIVERSI. Se il pannello disegnasse il primo
        caso come il secondo, tutto il lavoro del server servirebbe a niente -- l'operatore
        leggerebbe comunque «tutto a posto»."""
        self.assertIn("controllabile===false", self.HTML,
                      "il pannello non guarda nemmeno se la lista era controllabile")
        self.assertIn("rd_nonso", self.HTML, "manca il messaggio «non ho potuto controllare»")
        # il ramo «nessuno aspetta» dev'essere subordinato a controllabile !== false
        self.assertIn("((d.controllabile===false) ? '' : "
                      "'<div style=\"color:var(--testo-tenue)\">'+T('rd_nessuno')", self.HTML,
                      "quando la lista non e' controllabile il pannello scrive lo stesso "
                      "«nessuno sta aspettando»: e' un silenzio che sembra una buona notizia")

    def test_la_divergenza_coi_conti_di_stripe_si_vede(self):
        self.assertIn("rd_divergenza", self.HTML,
                      "gli allarmi «Stripe ha rimborsato e noi non lo sappiamo» non compaiono")


if __name__ == "__main__":
    unittest.main(verbosity=2)
