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

STRIPE_FINTO = {"rimborsi_per_pi": {}, "esplode": False}
CHIAMATE_LISTA = []


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
        campi = parse_qs(body.decode("utf-8"))
        pi = (campi.get("payment_intent") or [""])[0]
        rid = "re_" + secrets.token_hex(4)
        STRIPE_FINTO["rimborsi_per_pi"].setdefault(pi, []).append(
            {"id": rid, "status": "succeeded",
             "amount": int((campi.get("amount") or ["0"])[0] or 0)})
        return {"id": rid, "status": "succeeded", "object": "refund"}
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
        STRIPE_FINTO["esplode"] = False
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
        """⛔ IL PUNTO 1 NELLA SUA FORMA PIU' DURA, e nasce da una misura fatta oggi:
        `fase162.pulisci_vecchi()` CANCELLA i record in stato 'rimborsato' piu' vecchi di 26
        ore. Una lista costruita sui pendenti perderebbe la riga di chi aspetta da piu' di un
        giorno -- cioe' proprio chi ha aspettato di piu'.

        La lista si regge quindi sul GIORNALE IMMUTABILE (fase177), che non si purga mai.
        Qui il record pendente viene purgato di proposito: la riga deve restare."""
        rif, _ = self._cancella_da_ospite("2026-09-10", "2026-09-12", "pi_ospite_2")
        self.assertIsNotNone(self._riga(self._lista(), rif), "setup: la riga dev'esserci prima")
        # 26 ore dopo: l'housekeeping passa e porta via il pendente
        rimossi = self.sys.pagamenti_pendenti.pulisci_vecchi(
            ora_ts=int(time.time()) + 200000)
        self.assertGreaterEqual(rimossi, 1, "setup: la purga doveva rimuovere il pendente")
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

    # ── PUNTO 4: i quattro freni sul denaro ─────────────────────────────────
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
