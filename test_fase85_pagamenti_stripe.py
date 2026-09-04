"""
Test Fase 85 - Provider Pagamento Stripe.

Copre: creazione link (con fetch STUB, niente chiamata reale), request ben formata
(unit_amount in cents, auth Bearer, mode payment, metadata), no-url -> None, fetch che
solleva -> None (isolato), cents invalidi -> None, factory gated (no chiave -> None).
E le guardie di `TestIBuchiDelGiudice` (2026-09-04): rimborsa, rimborsi_di, commissione_effettiva
e i ripieghi di crea_link/crea_link_anticipo, nate dai 49 mutanti sopravvissuti al giro col solo
test dedicato.
"""
import unittest

from fase85_pagamenti_stripe import (
    ADDEBITI_URL, MOVIMENTI_URL, PAGAMENTI_URL, RIMBORSI_URL, ProviderStripe,
    crea_provider_stripe,
)


class FetchSpy:
    """Cattura la richiesta e ritorna una risposta finta (no Stripe reale)."""
    def __init__(self, risposta=None, solleva=False):
        self.url = None
        self.body = None
        self.headers = None
        self._risp = risposta if risposta is not None else {"url": "https://checkout.stripe.com/c/sess_123"}
        self._solleva = solleva

    def __call__(self, url, body, headers):
        if self._solleva:
            raise RuntimeError("stripe giu'")
        self.url, self.body, self.headers = url, body.decode(), headers
        return self._risp


DATI = {"prezzo_guest_cents": 9500, "riferimento": "ABC123", "email": "g@x.it"}


class TestProvider(unittest.TestCase):
    def test_crea_link(self):
        spy = FetchSpy()
        p = ProviderStripe("sk_test_x", "https://ok", "https://ko", fetch=spy)
        url = p.crea_link(DATI)
        self.assertEqual(url, "https://checkout.stripe.com/c/sess_123")

    def test_request_ben_formata(self):
        spy = FetchSpy()
        ProviderStripe("sk_test_xyz", "https://ok", "https://ko", fetch=spy).crea_link(DATI)
        self.assertIn("api.stripe.com", spy.url)
        self.assertEqual(spy.headers["Authorization"], "Bearer sk_test_xyz")
        self.assertIn("unit_amount%5D=9500", spy.body)       # cents interi (chiave Stripe)
        self.assertIn("mode=payment", spy.body)
        self.assertIn("ABC123", spy.body)                    # riferimento nei metadata
        self.assertIn("customer_email", spy.body)

    def test_no_url_in_risposta(self):
        p = ProviderStripe("sk", "o", "k", fetch=FetchSpy(risposta={"error": "x"}))
        self.assertIsNone(p.crea_link(DATI))

    def test_fetch_solleva_isolato(self):
        p = ProviderStripe("sk", "o", "k", fetch=FetchSpy(solleva=True))
        self.assertIsNone(p.crea_link(DATI))                 # None, non crash

    def test_cents_invalidi(self):
        spy = FetchSpy()
        p = ProviderStripe("sk", "o", "k", fetch=spy)
        for bad in ({"prezzo_guest_cents": 0}, {"prezzo_guest_cents": -5},
                    {"prezzo_guest_cents": 95.0}, {}, None):
            self.assertIsNone(p.crea_link(bad))

    def test_valuta(self):
        spy = FetchSpy()
        ProviderStripe("sk", "o", "k", valuta="USD", fetch=spy).crea_link(DATI)
        self.assertIn("currency%5D=usd", spy.body)


ANT = {"anticipo_cents": 3312, "saldo_cents": 26838, "totale_cents": 30000,
       "riferimento": "PS777", "email": "g@x.it", "valuta": "EUR"}


class TestAnticipoPagaStruttura(unittest.TestCase):
    """PAGA IN STRUTTURA: la Checkout Session addebita SOLO l'anticipo e salva la carta."""

    def test_ritorna_url(self):
        spy = FetchSpy()
        p = ProviderStripe("sk_test_x", "https://ok", "https://ko", fetch=spy)
        self.assertEqual(p.crea_link_anticipo(ANT), "https://checkout.stripe.com/c/sess_123")

    def test_addebita_ANTICIPO_non_il_totale(self):
        # il difetto da temere: addebitare il totale (300) invece dell'anticipo (33,12).
        spy = FetchSpy()
        ProviderStripe("sk", "o", "k", fetch=spy).crea_link_anticipo(ANT)
        self.assertIn("unit_amount%5D=3312", spy.body)          # anticipo, in cents
        self.assertNotIn("unit_amount%5D=30000", spy.body)      # MAI il totale
        self.assertNotIn("26838", spy.body.split("metadata")[0]) # il saldo non e' un line item

    def test_salva_la_carta_e_marca_in_struttura(self):
        spy = FetchSpy()
        ProviderStripe("sk", "o", "k", fetch=spy).crea_link_anticipo(ANT)
        self.assertIn("setup_future_usage%5D=off_session", spy.body)  # carta salvata
        self.assertIn("customer_creation=always", spy.body)
        self.assertIn("mode=payment", spy.body)
        self.assertIn("in_struttura", spy.body)                 # metadata[modo]
        self.assertIn("saldo_cents%5D=26838", spy.body)         # saldo nei metadata (per il webhook)
        self.assertIn("PS777", spy.body)                        # riferimento

    def test_anticipo_invalido_none(self):
        spy = FetchSpy()
        p = ProviderStripe("sk", "o", "k", fetch=spy)
        for bad in ({"anticipo_cents": 0}, {"anticipo_cents": -5},
                    {"anticipo_cents": 33.1}, {"anticipo_cents": True}, {}, None):
            self.assertIsNone(p.crea_link_anticipo(bad))

    def test_fetch_solleva_isolato(self):
        p = ProviderStripe("sk", "o", "k", fetch=FetchSpy(solleva=True))
        self.assertIsNone(p.crea_link_anticipo(ANT))            # None, non crash

    def test_saldo_zero_ok(self):
        # prezzo minuscolo: anticipo == totale, saldo 0 -> paga tutto online, valido
        spy = FetchSpy()
        u = ProviderStripe("sk", "o", "k", fetch=spy).crea_link_anticipo(
            {"anticipo_cents": 500, "saldo_cents": 0, "riferimento": "R", "valuta": "EUR"})
        self.assertEqual(u, "https://checkout.stripe.com/c/sess_123")
        self.assertIn("saldo_cents%5D=0", spy.body)


class TestFactoryGated(unittest.TestCase):
    def test_senza_chiave_none(self):
        self.assertIsNone(crea_provider_stripe(None))
        self.assertIsNone(crea_provider_stripe(""))
        self.assertIsNone(crea_provider_stripe("   "))

    def test_con_chiave(self):
        spy = FetchSpy()
        p = crea_provider_stripe("sk_live_x", "https://ok", "https://ko", fetch=spy)
        self.assertIsNotNone(p)
        self.assertEqual(p.crea_link(DATI), "https://checkout.stripe.com/c/sess_123")


class FetchFinto:
    """Uno Stripe finto per le funzioni che LEGGONO o RIMBORSANO: risponde per prefisso di URL e
    registra ogni chiamata (url, body, headers). Diverso da FetchSpy: qui `body` puo' essere None
    (le letture sono GET) e in uno stesso flusso arrivano piu' risposte (le tre tappe della
    commissione). Senza risposta per quell'URL ritorna {}: «Stripe ha risposto qualcosa che non
    so leggere», mai un'eccezione nascosta."""

    def __init__(self, risposte=None, solleva=None):
        self.risposte = risposte or {}
        self.solleva = solleva
        self.chiamate = []

    def __call__(self, url, body, headers):
        self.chiamate.append((url, body, headers))
        if self.solleva is not None:
            raise self.solleva
        for prefisso, risposta in self.risposte.items():
            if url.startswith(prefisso):
                return risposta
        return {}


def _p(fetch):
    return ProviderStripe("sk_test_k", "https://ok/grazie", "https://ko/annulla", fetch=fetch)


class TestIBuchiDelGiudice(unittest.TestCase):
    """Guardie nate dai 49 mutanti SOPRAVVISSUTI al giro del Giudice del 2026-09-04 col solo test
    dedicato (60 punti: 11 uccisi). Il test dedicato non toccava `rimborsa`, `rimborsi_di` e
    `commissione_effettiva` -- le funzioni che fanno uscire o contano denaro vero -- ne' i ripieghi
    di `crea_link`/`crea_link_anticipo`. Ogni guardia porta nel nome le righe dei mutanti, e' stata
    vista ROSSA contro di loro prima che verde (D20) e difende un contratto scritto nel modulo.
    Il solo mutante non ucciso (riga 293, `>=` -> `>` sul saldo) e' equivalente per costruzione:
    l'unico ingresso su cui i due operatori differiscono e' saldo == 0, e li' i due rami valgono
    entrambi 0. Va nello schedario con la prova, non qui."""

    def test_riga92_93_98_103_il_link_porta_le_URL_date_il_nome_col_riferimento_e_l_email_solo_se_vera(self):
        spy = FetchSpy()
        _p(spy).crea_link(dict(DATI, email="senza-chiocciola"))
        self.assertIn("success_url=https%3A%2F%2Fok%2Fgrazie", spy.body)       # 92: la URL data, non il ripiego
        self.assertIn("cancel_url=https%3A%2F%2Fko%2Fannulla", spy.body)        # 93
        self.assertIn("name%5D=BookinVIP+ABC123", spy.body)                     # 98: il riferimento nel nome
        self.assertNotIn("customer_email", spy.body)                            # 103: senza @ niente email
        spy2 = FetchSpy()
        ProviderStripe("sk", "", "", fetch=spy2).crea_link(dict(DATI, riferimento="", email=None))
        self.assertIn("success_url=https%3A%2F%2Fbookinvip.com%2Fgrazie.html", spy2.body)   # 92: il ripiego
        self.assertIn("cancel_url=https%3A%2F%2Fbookinvip.com%2Fannullato.html", spy2.body)  # 93
        self.assertIn("name%5D=BookinVIP+prenotazione", spy2.body)              # 98: il ripiego del nome
        self.assertNotIn("customer_email", spy2.body)                           # 103: None non esplode

    def test_riga111_335_una_risposta_con_url_vuota_o_non_stringa_vale_None_non_un_link_finto(self):
        for risposta in ({"url": ""}, {"url": 123}, {"url": None}, {"url": ["x"]}):
            with self.subTest(risposta=risposta):
                self.assertIsNone(_p(FetchSpy(risposta=risposta)).crea_link(DATI))
                self.assertIsNone(_p(FetchSpy(risposta=risposta)).crea_link_anticipo(ANT))

    def test_riga114_169_218_273_338_quando_Stripe_esplode_il_log_porta_L_ECCEZIONE_non_solo_la_frase(self):
        # `exc_info=False` non e' None: la guardia pretende la tupla (tipo, eccezione, traceback)
        # con dentro l'eccezione vera. Senza, un rimborso fallito lascia nel log una frase e basta.
        p = _p(FetchFinto(solleva=RuntimeError("stripe giu'")))
        casi = [
            ("crea_link", (DATI,), None, "WARNING"),
            ("crea_link_anticipo", (ANT,), None, "WARNING"),
            ("rimborsa", ("pi_1", 100, "k-1"),
             {"ok": False, "id": "", "motivo": "RuntimeError: stripe giu'"}, "ERROR"),
            ("rimborsi_di", ("pi_1",),
             {"ok": False, "rimborsi": [], "rimborsato_cents": 0, "motivo": "RuntimeError: stripe giu'"},
             "ERROR"),
            ("commissione_effettiva", ("pi_1",),
             {"ok": False, "fee_cents": 0, "netto_cents": 0, "valuta": "",
              "motivo": "RuntimeError: stripe giu'"}, "ERROR"),
        ]
        for nome, args, atteso, livello in casi:
            with self.subTest(metodo=nome):
                with self.assertLogs("core_auto.pagamenti_stripe", level=livello) as reg:
                    self.assertEqual(getattr(p, nome)(*args), atteso)
                rec = reg.records[-1]
                self.assertEqual(rec.levelname, livello)
                self.assertIsInstance(rec.exc_info, tuple,
                                      "%s: exc_info=%r (False non e' un traceback)" % (nome, rec.exc_info))
                self.assertIsInstance(rec.exc_info[1], RuntimeError)

    def test_riga141_146_rimborsa_rifiuta_senza_chiamare_Stripe_pagamento_importo_o_chiave_non_validi(self):
        f = FetchFinto({RIMBORSI_URL: {"id": "re_mai", "status": "succeeded"}})
        p = _p(f)
        casi = [
            (("ch_123", 100, "k-1"), "payment_intent_assente"),     # 141: non e' un pi_
            ((None, 100, "k-1"), "payment_intent_assente"),         # 141: None non esplode
            (("pi_1", 0, "k-1"), "importo_non_valido"),             # 144
            (("pi_1", True, "k-1"), "importo_non_valido"),
            (("pi_1", 100, "   "), "chiave_idempotenza_assente"),   # 145: spazi non sono una chiave
            (("pi_1", 100, None), "chiave_idempotenza_assente"),    # 145: None non esplode
        ]
        for args, motivo in casi:
            with self.subTest(args=args):
                self.assertEqual(p.rimborsa(*args), {"ok": False, "id": "", "motivo": motivo})
        self.assertEqual(f.chiamate, [], "un rimborso rifiutato non deve toccare Stripe")

    def test_riga160_165_rimborsa_dice_ok_solo_su_un_re_vero_e_riporta_lo_stato_di_Stripe(self):
        f = FetchFinto({RIMBORSI_URL: {"id": "re_1", "status": "pending"}})
        self.assertEqual(_p(f).rimborsa("pi_1", 2500, " chiave-77 "),
                         {"ok": True, "id": "re_1", "motivo": "pending"})          # 161, 162
        url, body, headers = f.chiamate[0]
        self.assertEqual(url, RIMBORSI_URL)
        self.assertEqual(headers["Idempotency-Key"], "chiave-77")
        self.assertIn("payment_intent=pi_1", body.decode())
        self.assertIn("amount=2500", body.decode())
        f2 = FetchFinto({RIMBORSI_URL: {"id": "re_2"}})
        self.assertEqual(_p(f2).rimborsa("pi_1", 2500, "k"),
                         {"ok": True, "id": "re_2", "motivo": "creato"})           # 162: senza status
        for risposta in ({"id": "xx_1"}, {"id": None}, {"error": "no"}, "stringa", None):
            with self.subTest(risposta=risposta):
                esito = _p(FetchFinto({RIMBORSI_URL: risposta})).rimborsa("pi_1", 2500, "k")
                self.assertIs(esito["ok"], False)                                   # 165
                self.assertEqual(esito["id"], "")
                self.assertTrue(esito["motivo"].startswith("risposta_inattesa"), esito)   # 160

    def test_riga199_215_rimborsi_di_conta_solo_i_rimborsi_VIVI_e_distingue_non_lo_so_da_zero(self):
        f = FetchFinto({RIMBORSI_URL: {"data": [
            {"id": "re_a", "status": "succeeded", "amount": 700},
            {"id": "re_b", "status": "pending", "amount": 300},
            {"id": "re_c", "status": "failed", "amount": 9999},      # non e' uscito niente
            {"id": "re_d", "status": "canceled", "amount": 9999},
            "spazzatura",                                          # 213: non e' un dict, si salta
            {"id": "re_e", "status": "requires_action"},           # 215: senza amount vale 0
        ]}})
        esito = _p(f).rimborsi_di("pi_1")
        self.assertIs(esito["ok"], True)                                             # 214
        self.assertEqual([r["id"] for r in esito["rimborsi"]], ["re_a", "re_b", "re_e"])   # 213
        self.assertEqual(esito["rimborsato_cents"], 1000)                            # 215
        self.assertEqual(esito["motivo"], "")
        url, body, _headers = f.chiamate[0]
        self.assertIsNone(body, "leggere i rimborsi e' una GET: senza corpo")
        self.assertIn("payment_intent=pi_1", url)
        self.assertIn("limit=100", url)
        # «non lo so» non e' «zero»: 199/200 pagamento non valido, 207/210 risposta che non e' un elenco
        f2 = FetchFinto({RIMBORSI_URL: {"data": [{"status": "succeeded", "amount": 5}]}})
        for pi in ("ch_1", "", None, 42):
            with self.subTest(pi=pi):
                self.assertEqual(_p(f2).rimborsi_di(pi),
                                 {"ok": False, "rimborsi": [], "rimborsato_cents": 0,
                                  "motivo": "payment_intent_assente"})
        self.assertEqual(f2.chiamate, [])
        for risposta in ({"data": "x"}, {"data": None}, {"error": "x"}, [], "str", None):
            with self.subTest(risposta=risposta):
                esito = _p(FetchFinto({RIMBORSI_URL: risposta})).rimborsi_di("pi_1")
                self.assertIs(esito["ok"], False)
                self.assertEqual((esito["rimborsi"], esito["rimborsato_cents"]), ([], 0))
                self.assertTrue(esito["motivo"].startswith("risposta_inattesa"), esito)

    def test_riga248_273_commissione_effettiva_segue_le_tre_tappe_e_dice_non_lo_so_quando_manca_un_anello(self):
        f = FetchFinto({PAGAMENTI_URL + "/pi_1": {"status": "succeeded", "latest_charge": "ch_1"},
                        ADDEBITI_URL + "/ch_1": {"balance_transaction": "txn_1"},
                        MOVIMENTI_URL + "/txn_1": {"fee": 27, "net": 73, "currency": "eur"}})
        self.assertEqual(_p(f).commissione_effettiva("pi_1"),
                         {"ok": True, "fee_cents": 27, "netto_cents": 73, "valuta": "EUR", "motivo": ""})
        self.assertEqual([u for u, _b, _h in f.chiamate],
                         [PAGAMENTI_URL + "/pi_1", ADDEBITI_URL + "/ch_1", MOVIMENTI_URL + "/txn_1"])
        self.assertTrue(all(b is None for _u, b, _h in f.chiamate), "sono tre LETTURE: nessun corpo")
        vuoto = {"ok": False, "fee_cents": 0, "netto_cents": 0, "valuta": ""}
        for pi in ("ch_1", "", None, 42):                                                       # 248, 249
            with self.subTest(pi=pi):
                self.assertEqual(_p(f).commissione_effettiva(pi), dict(vuoto, motivo="payment_intent_assente"))
        # 254, 259: un pagamento senza addebito dice lo STATO del pagamento, non «commissione zero»
        f2 = FetchFinto({PAGAMENTI_URL + "/pi_2": {"status": "requires_payment_method"}})
        esito = _p(f2).commissione_effettiva("pi_2")
        self.assertEqual(dict(esito, motivo=""), dict(vuoto, motivo=""))
        self.assertIn("requires_payment_method", esito["motivo"])
        # 266: un movimento senza `fee` non e' «commissione zero»: e' una risposta che non so leggere
        for bt in ({"net": 73, "currency": "eur"}, None, "str", []):
            with self.subTest(bt=bt):
                f3 = FetchFinto({PAGAMENTI_URL + "/pi_1": {"latest_charge": "ch_1"},
                                 ADDEBITI_URL + "/ch_1": {"balance_transaction": "txn_1"},
                                 MOVIMENTI_URL + "/txn_1": bt})
                esito = _p(f3).commissione_effettiva("pi_1")
                self.assertEqual(dict(esito, motivo=""), dict(vuoto, motivo=""))
                self.assertTrue(esito["motivo"].startswith("risposta_inattesa"), esito)
        # 261: un addebito senza balance_transaction
        f4 = FetchFinto({PAGAMENTI_URL + "/pi_1": {"latest_charge": "ch_1"}, ADDEBITI_URL + "/ch_1": {}})
        esito = _p(f4).commissione_effettiva("pi_1")
        self.assertIs(esito["ok"], False)
        self.assertIn("balance_transaction", esito["motivo"])

    def test_riga292_296_313_319_327_l_anticipo_ripulisce_saldo_valuta_URL_nome_ed_email(self):
        # 292: un saldo che non e' un intero non negativo vale 0, e non fa esplodere il link
        for saldo in (None, "26838", 2.5, -1, True):
            with self.subTest(saldo=saldo):
                spy = FetchSpy()
                url = _p(spy).crea_link_anticipo(dict(ANT, saldo_cents=saldo))
                self.assertEqual(url, "https://checkout.stripe.com/c/sess_123")
                self.assertIn("saldo_cents%5D=0", spy.body)
        # 296: valuta vuota o assente -> quella del provider, e None non esplode
        for valuta in ("", "   ", None):
            with self.subTest(valuta=valuta):
                spy = FetchSpy()
                d = dict(ANT)
                d["valuta"] = valuta
                self.assertIsNotNone(ProviderStripe("sk", "o", "k", valuta="GBP", fetch=spy).crea_link_anticipo(d))
                self.assertIn("currency%5D=gbp", spy.body)
        # 313, 314, 319, 327: le URL date, il nome col riferimento, l'email solo se vera
        spy = FetchSpy()
        _p(spy).crea_link_anticipo(dict(ANT, email="g@x.it"))
        self.assertIn("success_url=https%3A%2F%2Fok%2Fgrazie", spy.body)
        self.assertIn("cancel_url=https%3A%2F%2Fko%2Fannulla", spy.body)
        self.assertIn("name%5D=BookinVIP+anticipo+PS777", spy.body)
        self.assertIn("customer_email=g%40x.it", spy.body)
        spy2 = FetchSpy()
        ProviderStripe("sk", "", "", fetch=spy2).crea_link_anticipo(
            dict(ANT, riferimento="", email="senza-chiocciola"))
        self.assertIn("success_url=https%3A%2F%2Fbookinvip.com%2Fgrazie.html", spy2.body)
        self.assertIn("cancel_url=https%3A%2F%2Fbookinvip.com%2Fannullato.html", spy2.body)
        self.assertIn("name%5D=BookinVIP+anticipo+prenotazione", spy2.body)
        self.assertNotIn("customer_email", spy2.body)


if __name__ == "__main__":
    unittest.main()
