"""Test Fase 101 - Stripe Connect split-all'origine. fetch STUB: nessuna rete.
E le guardie di `TestIBuchiDelGiudice` (2026-09-04): trasferisci, stato_account, link_onboarding,
crea_account, `_intero_pos` e i ripieghi dei params, nate dai 37 mutanti sopravvissuti al giro
col solo test dedicato."""
import unittest
import urllib.parse

from fase101_stripe_connect import (STRIPE_URL, ProviderConnect, ProviderStripeConnect,
                                    _intero_pos, costruisci_params,
                                    crea_provider_stripe_connect)

DATI = {"prezzo_guest_cents": 11200, "commissione_cents": 1500,
        "host_account": "acct_123", "riferimento": "REF1", "valuta": "usd"}


class TestParams(unittest.TestCase):
    def test_destination_e_fee(self):
        p = costruisci_params(11200, 1500, "acct_123", valuta="usd")
        self.assertEqual(p["payment_intent_data[transfer_data][destination]"], "acct_123")
        self.assertEqual(p["payment_intent_data[application_fee_amount]"], "1500")
        self.assertEqual(p["line_items[0][price_data][unit_amount]"], "11200")
        self.assertEqual(p["line_items[0][price_data][currency]"], "usd")

    def test_invalidi(self):
        self.assertIsNone(costruisci_params(0, 100, "acct_1"))
        self.assertIsNone(costruisci_params(1000, 100, ""))         # no host
        self.assertIsNone(costruisci_params(1000, 1000, "acct_1"))  # fee >= lordo
        self.assertIsNone(costruisci_params(1000, -1, "acct_1"))


class TestProvider(unittest.TestCase):
    def test_crea_link_ok(self):
        visti = {}
        p = ProviderStripeConnect("sk_test", fetch=lambda u, b, h:
                                  visti.update(body=b, head=h) or {"url": "https://pay/x"})
        self.assertEqual(p.crea_link(DATI), "https://pay/x")
        self.assertIn(b"acct_123", visti["body"])
        self.assertEqual(visti["head"]["Authorization"], "Bearer sk_test")

    def test_gated_senza_key(self):
        self.assertIsNone(crea_provider_stripe_connect(None))
        self.assertIsNone(ProviderStripeConnect("").crea_link(DATI))

    def test_isolato(self):
        def boom(*a):
            raise RuntimeError("stripe giu")
        self.assertIsNone(ProviderStripeConnect("sk", fetch=boom).crea_link(DATI))

    def test_factory(self):
        self.assertIsNotNone(crea_provider_stripe_connect("sk", fetch=lambda *a: {}))


class TestQuandoStripeRIFIUTA_SiDEVESapereIlPERCHE(unittest.TestCase):
    """⛔ UN FALLIMENTO SUI SOLDI NON PUO' ESSERE UN WARNING SENZA MOTIVO.

    Trovato sul campo il 2026-08-08. Il fondatore preme «Collega Stripe» nel pannello
    host e vede `stripe_non_disponibile`. Nei registri c'era solo:

        WARNING Connect POST https://api.stripe.com/v1/accounts fallita (ISOLATA)

    Stripe invece aveva risposto con una frase chiarissima, nel CORPO della risposta:
    «You must complete your platform profile to use Connect and create live connected
    accounts.» Cioe' ci stava dicendo esattamente cosa fare, e `_post` buttava via il
    corpo con un `except Exception` generico.

    Due difetti in uno, entrambi gia' scritti nelle regole del progetto:
      · REGOLA FERREA 9 -- l'osservabile debole: di un servizio esterno si scrivono
        CODICE e MESSAGGIO, mai il solo «fallita»;
      · e il livello WARNING, che `fase186:263` dichiara di NON leggere -> il Guardiano
        non se ne accorge. E' identico al difetto chiuso il 2026-08-07 su `fase88`:
        «un messaggio che nessuno legge e' un pass scritto piu' lungo».

    Costo misurato del non averlo: QUINDICI MINUTI per ritrovare una frase che era gia'
    li', scritta, dal primo tentativo. Per un host vero il costo e' che se ne va.
    """

    def _fetch_che_rifiuta(self, corpo):
        import io
        import urllib.error

        def f(url, body, headers):
            raise urllib.error.HTTPError(
                url, 400, "Bad Request", {}, io.BytesIO(corpo.encode()))
        return f

    def test_il_MESSAGGIO_di_stripe_finisce_nei_registri(self):
        from fase101_stripe_connect import ProviderConnect
        corpo = ('{"error": {"type": "invalid_request_error", "code": "platform_incomplete",'
                 ' "message": "You must complete your platform profile to use Connect."}}')
        p = ProviderConnect("sk_test_x", fetch=self._fetch_che_rifiuta(corpo))
        with self.assertLogs("core_auto.stripe_connect", level="INFO") as reg:
            self.assertIsNone(p.crea_account("h@x.it"))
        testo = "\n".join(reg.output)
        self.assertIn("complete your platform profile", testo,
                      "il messaggio di Stripe non finisce nei registri: resta «fallita», "
                      "che non dice a nessuno cosa fare. E' la regola ferrea 9 -- "
                      "l'osservabile debole e' un difetto.\nRegistrato: %s" % testo)
        self.assertIn("invalid_request_error", testo,
                      "manca il TIPO dell'errore di Stripe: codice e messaggio si "
                      "scrivono sempre, mai il solo esito")

    def test_e_l_allarme_e_un_ERROR_non_un_warning(self):
        """Il Guardiano legge SOLO gli ERROR (fase186:263, dichiarato).

        Un fallimento che impedisce a un host di essere pagato non puo' finire in un
        livello che nessuno sorveglia: sarebbe un difetto invisibile per costruzione.
        """
        from fase101_stripe_connect import ProviderConnect
        p = ProviderConnect("sk_test_x", fetch=self._fetch_che_rifiuta('{"error": {}}'))
        with self.assertLogs("core_auto.stripe_connect", level="INFO") as reg:
            self.assertIsNone(p.crea_account("h@x.it"))
        livelli = [r.levelname for r in reg.records]
        self.assertIn("ERROR", livelli,
                      "il fallimento e' registrato come %r: il Guardiano legge solo gli "
                      "ERROR, quindi cosi' non lo vede nessuno" % livelli)

    def test_un_ECCEZIONE_OSTILE_non_rompe_l_isolamento(self):
        """⛔ LA MEMORIA DI UN DIFETTO CHE HO INTRODOTTO IO, il 2026-08-08.

        La prima stesura di questa riparazione faceva `getattr(e, "read", None)` FUORI
        dal `try`. Sembra innocuo, ma `getattr` con un valore di ripiego sopprime solo
        `AttributeError`: se l'oggetto dell'eccezione ha un `__getattr__` che solleva
        altro -- e un `HTTPError` con `fp` chiuso solleva `KeyError: 'file'` -- allora
        **la diagnostica esplode mentre sta gestendo un'eccezione**, e l'errore esce da
        `_post`.

        Non e' teoria: l'ha preso `test_stripe_500_sul_transfer_non_solleva`, e a
        cascata la prova che il bonifico da fare a mano resti tracciato. Cioe' un
        guasto di Stripe avrebbe potuto far **perdere la traccia dei soldi dovuti a un
        host** -- proprio per aver aggiunto un messaggio piu' bello nei registri.

        UNA DIAGNOSTICA CHE PUO' SOLLEVARE E' PEGGIO DI NESSUNA DIAGNOSTICA.
        """
        from fase101_stripe_connect import ProviderConnect

        class _EccezioneOstile(Exception):
            def __getattr__(self, nome):
                # ⛔ I DUNDER DEVONO COMPORTARSI NORMALMENTE. La prima stesura sollevava
                #    KeyError per QUALUNQUE attributo, dunder compresi: piu' ostile della
                #    realta'. Su Python 3.11 il modulo `logging` accede a `e.__notes__`
                #    mentre formatta l'eccezione (PEP 678) -> `KeyError: '__notes__'`, e
                #    la prova falliva in CI restando VERDE in locale su 3.9.
                #    Modo di rompersi n.8: ambiente diverso. L'ha preso la CI, non io.
                #    Un `HTTPError` con `fp` chiuso -- il caso VERO che si sta imitando --
                #    esplode su `read`/`code`, non sui dunder.
                if nome.startswith("__"):
                    raise AttributeError(nome)
                raise KeyError(nome)

        def f(url, body, headers):
            raise _EccezioneOstile("stripe strano")

        p = ProviderConnect("sk_test_x", fetch=f)
        with self.assertLogs("core_auto.stripe_connect", level="INFO"):
            esito = p.crea_account("h@x.it")    # NON deve sollevare
        self.assertIsNone(esito,
                          "un'eccezione con __getattr__ ostile ha fatto uscire l'errore "
                          "da _post: l'isolamento e' rotto, e con esso la garanzia che "
                          "un guasto di Stripe non porti via i soldi di nessuno")

    def test_ma_resta_ISOLATO_il_sito_non_cade(self):
        """L'altra direzione, obbligatoria: gridare non deve diventare esplodere.

        Stripe che rifiuta e' un problema di Stripe: deve lasciare una traccia forte e
        restituire None, MAI far cadere la richiesta dell'utente.
        """
        from fase101_stripe_connect import ProviderConnect
        p = ProviderConnect("sk_test_x", fetch=self._fetch_che_rifiuta('{"error": {}}'))
        with self.assertLogs("core_auto.stripe_connect", level="INFO"):
            esito = p.crea_account("h@x.it")
        self.assertIsNone(esito, "deve restituire None, non sollevare")


class PostFinto:
    """Stripe finto per i POST del Connect: risponde per prefisso di URL e registra ogni chiamata
    (url, body, headers). Senza risposta per quell'URL ritorna {}."""

    def __init__(self, risposte=None):
        self.risposte = risposte or {}
        self.chiamate = []

    def __call__(self, url, body, headers):
        self.chiamate.append((url, body, headers))
        for prefisso, r in self.risposte.items():
            if url.startswith(prefisso):
                return r
        return {}


def _decodifica(body):
    # keep_blank_values: un `transfer_group=` vuoto e' un valore, non un'assenza
    return dict(urllib.parse.parse_qsl(body.decode(), keep_blank_values=True))


class TestIBuchiDelGiudice(unittest.TestCase):
    """Guardie nate dai 37 mutanti SOPRAVVISSUTI al giro del Giudice del 2026-09-04 col solo test
    dedicato (50 punti: 13 uccisi). Il dedicato copriva bene il registro degli errori e quasi
    niente di `trasferisci` (il bonifico all'host), `stato_account`, `link_onboarding`,
    `crea_account` e dei ripieghi dei params. Ogni guardia porta nel nome le righe dei mutanti,
    e' stata vista ROSSA contro di loro prima che verde (D20) e difende un contratto scritto nel
    modulo. Nessun mutante e' stato dichiarato equivalente (B6)."""

    def test_riga23_36_intero_positivo_stretto_e_commissione_zero_ammessa(self):
        # 23: `_intero_pos` vuole un int vero, non bool, > 0. Col mutante (and -> or) una stringa fa
        # esplodere il confronto e un float o un bool passano; col `>=` passa lo zero.
        for v, atteso in ((1, True), (11200, True), (0, False), (-1, False), (True, False),
                          (False, False), (2.5, False), ("100", False), (None, False)):
            with self.subTest(v=v):
                self.assertIs(_intero_pos(v), atteso)
        for prezzo in (0, True, 2.5, "100", None):
            with self.subTest(prezzo=prezzo):
                self.assertIsNone(costruisci_params(prezzo, 0, "acct_1"))
        # 36: commissione ZERO e' lecita (fee < 0 -> None, fee >= lordo -> None: lo zero sta in mezzo)
        p = costruisci_params(1000, 0, "acct_1")
        self.assertIsNotNone(p)
        self.assertEqual(p["payment_intent_data[application_fee_amount]"], "0")

    def test_riga40_48_i_params_portano_le_URL_date_il_nome_e_il_riferimento(self):
        p = costruisci_params(11200, 1500, "acct_123", riferimento="REF1",
                              success_url="https://ok/g", cancel_url="https://ko/a")
        self.assertEqual(p["success_url"], "https://ok/g")                                      # 40
        self.assertEqual(p["cancel_url"], "https://ko/a")                                       # 41
        self.assertEqual(p["line_items[0][price_data][product_data][name]"], "BookinVIP REF1")  # 43
        self.assertEqual(p["client_reference_id"], "REF1")                                     # 48
        q = costruisci_params(11200, 1500, "acct_123")
        self.assertEqual(q["success_url"], "https://bookinvip.com/grazie.html")
        self.assertEqual(q["cancel_url"], "https://bookinvip.com/annullato.html")
        self.assertEqual(q["line_items[0][price_data][product_data][name]"], "BookinVIP ")
        self.assertEqual(q["client_reference_id"], "")

    def test_riga62_68_84_il_provider_split_usa_la_sua_valuta_tace_senza_chiave_e_logga_l_eccezione(self):
        spy = PostFinto({STRIPE_URL: {"url": "https://pay/x"}})
        dati = dict(DATI)
        del dati["valuta"]
        self.assertEqual(ProviderStripeConnect("sk", valuta="usd", fetch=spy).crea_link(dati),
                         "https://pay/x")
        self.assertEqual(_decodifica(spy.chiamate[0][1])["line_items[0][price_data][currency]"], "usd")  # 62
        spy2 = PostFinto({STRIPE_URL: {"url": "https://pay/x"}})
        self.assertIsNone(ProviderStripeConnect("", fetch=spy2).crea_link(DATI))                # 68
        self.assertEqual(spy2.chiamate, [], "senza chiave non si parla con Stripe")

        def boom(*a):
            raise RuntimeError("stripe giu")

        with self.assertLogs("core_auto.stripe_connect", level="WARNING") as reg:               # 84
            self.assertIsNone(ProviderStripeConnect("sk", fetch=boom).crea_link(DATI))
        rec = reg.records[-1]
        self.assertIsInstance(rec.exc_info, tuple, "exc_info=%r (False non e' un traceback)" % (rec.exc_info,))
        self.assertIsInstance(rec.exc_info[1], RuntimeError)

    def test_riga177_178_il_registro_porta_anche_il_CODICE_di_Stripe_e_il_traceback(self):
        import io
        import urllib.error
        corpo = ('{"error": {"type": "invalid_request_error", "code": "platform_incomplete",'
                 ' "message": "You must complete your platform profile."}}')

        def f(url, body, headers):
            raise urllib.error.HTTPError(url, 400, "Bad Request", {}, io.BytesIO(corpo.encode()))

        with self.assertLogs("core_auto.stripe_connect", level="ERROR") as reg:
            self.assertIsNone(ProviderConnect("sk_test_x", fetch=f).crea_account("h@x.it"))
        self.assertIn("platform_incomplete", "\n".join(reg.output))                             # 177: il codice
        rec = reg.records[-1]
        self.assertIsInstance(rec.exc_info, tuple, "exc_info=%r (False non e' un traceback)" % (rec.exc_info,))  # 178
        self.assertIsInstance(rec.exc_info[1], urllib.error.HTTPError)

    def test_riga186_l_email_va_a_Stripe_solo_se_e_una_stringa_con_la_chiocciola(self):
        for email, attesa in (("h@x.it", "h@x.it"), ("senza", None), ("", None), (None, None), (123, None)):
            with self.subTest(email=email):
                spy = PostFinto({ProviderConnect.ACCOUNTS: {"id": "acct_9"}})
                self.assertEqual(ProviderConnect("sk", fetch=spy).crea_account(email), "acct_9")
                self.assertEqual(_decodifica(spy.chiamate[0][1]).get("email"), attesa)

    def test_riga195_202_link_onboarding_esige_chiave_e_account_e_accetta_solo_URL_http(self):
        risposta = {ProviderConnect.LINKS: {"url": "https://connect.stripe.com/setup/x"}}
        spy = PostFinto(risposta)
        self.assertEqual(ProviderConnect("sk", fetch=spy).link_onboarding("acct_1", "https://ok/r", "https://ok/f"),
                         "https://connect.stripe.com/setup/x")
        d = _decodifica(spy.chiamate[0][1])
        self.assertEqual((d["account"], d["type"]), ("acct_1", "account_onboarding"))
        self.assertEqual(d["return_url"], "https://ok/r")                                       # 199
        self.assertEqual(d["refresh_url"], "https://ok/f")                                      # 200
        spy2 = PostFinto(risposta)
        ProviderConnect("sk", fetch=spy2).link_onboarding("acct_1", "https://ok/r")
        self.assertEqual(_decodifica(spy2.chiamate[0][1])["refresh_url"], "https://ok/r")       # 200: ripiega sul return
        spy3 = PostFinto(risposta)
        ProviderConnect("sk", fetch=spy3).link_onboarding("acct_1", "")
        d3 = _decodifica(spy3.chiamate[0][1])
        self.assertEqual((d3["return_url"], d3["refresh_url"]), ("https://bookinvip.com/host.html",) * 2)
        for chiave, account in (("", "acct_1"), ("sk", ""), ("sk", None), ("sk", 123), ("sk", b"acct_1")):  # 195
            with self.subTest(chiave=chiave, account=account):
                spy4 = PostFinto(risposta)
                self.assertIsNone(ProviderConnect(chiave, fetch=spy4).link_onboarding(account, "https://ok/r"))
                self.assertEqual(spy4.chiamate, [])
        for url in ("javascript:alert(1)", "", None, 123):                                        # 202
            with self.subTest(url=url):
                p = ProviderConnect("sk", fetch=PostFinto({ProviderConnect.LINKS: {"url": url}}))
                self.assertIsNone(p.link_onboarding("acct_1", "https://ok/r"))

    def test_riga206_217_stato_account_dice_pronto_solo_con_payouts_enabled_e_mai_True_per_sbaglio(self):
        visti = []

        def get_ok(url, headers):
            visti.append((url, headers))
            return {"payouts_enabled": True, "details_submitted": True}

        p = ProviderConnect("sk", fetch_get=get_ok)                                               # 122
        self.assertEqual(p.stato_account("acct_1"), {"pronto": True, "dettagli_inviati": True})
        self.assertEqual(visti[0], (ProviderConnect.ACCOUNTS + "/acct_1", {"Authorization": "Bearer sk"}))
        p_no = ProviderConnect("sk", fetch_get=lambda u, h: {"payouts_enabled": False, "details_submitted": True})
        self.assertEqual(p_no.stato_account("acct_1"), {"pronto": False, "dettagli_inviati": True})
        for chiave, account in (("", "acct_1"), ("sk", ""), ("sk", None), ("sk", 123), ("sk", b"acct_1")):  # 206, 207
            with self.subTest(chiave=chiave, account=account):
                chiamate = []
                p2 = ProviderConnect(chiave, fetch_get=lambda u, h: chiamate.append(u) or {"payouts_enabled": True})
                self.assertEqual(p2.stato_account(account), {"pronto": False})
                self.assertEqual(chiamate, [])
        for r in ("str", None, [], 42):                                                            # 212
            with self.subTest(r=r):
                self.assertEqual(ProviderConnect("sk", fetch_get=lambda u, h, r=r: r).stato_account("acct_1"),
                                 {"pronto": False})

        def boom(url, headers):
            raise RuntimeError("stripe giu")

        with self.assertLogs("core_auto.stripe_connect", level="WARNING") as reg:                 # 216, 217
            self.assertEqual(ProviderConnect("sk", fetch_get=boom).stato_account("acct_1"), {"pronto": False})
        rec = reg.records[-1]
        self.assertIsInstance(rec.exc_info, tuple, "exc_info=%r (False non e' un traceback)" % (rec.exc_info,))
        self.assertIsInstance(rec.exc_info[1], RuntimeError)

    def test_riga230_243_trasferisci_bonifica_solo_a_un_acct_con_importo_intero_positivo_e_chiave_idempotente(self):
        spy = PostFinto({ProviderConnect.TRANSFERS: {"id": "tr_1"}})
        self.assertEqual(ProviderConnect("sk", fetch=spy).trasferisci("acct_1", 8700, "USD", "R1"), "tr_1")
        url, body, headers = spy.chiamate[0]
        d = _decodifica(body)
        self.assertEqual(url, ProviderConnect.TRANSFERS)
        self.assertEqual((d["amount"], d["destination"]), ("8700", "acct_1"))
        self.assertEqual(d["currency"], "usd")                                                  # 237
        self.assertEqual(d["transfer_group"], "R1")                                              # 239
        self.assertEqual(d["metadata[riferimento]"], "R1")                                       # 240
        self.assertEqual(headers["Idempotency-Key"], "transfer_R1")                              # 241
        spy2 = PostFinto({ProviderConnect.TRANSFERS: {"id": "tr_2"}})
        ProviderConnect("sk", fetch=spy2).trasferisci("acct_1", 100, "", "")
        d2 = _decodifica(spy2.chiamate[0][1])
        self.assertEqual((d2["currency"], d2["transfer_group"], d2["metadata[riferimento]"]), ("eur", "", ""))
        self.assertEqual(spy2.chiamate[0][2]["Idempotency-Key"], "transfer_acct_1")             # 241: senza riferimento, l'account
        for chiave, account, importo in (("", "acct_1", 100), ("sk", "cus_1", 100), ("sk", None, 100),   # 230
                                         ("sk", 123, 100), ("sk", "acct_1", 0), ("sk", "acct_1", -5),   # 232, 233
                                         ("sk", "acct_1", True), ("sk", "acct_1", 2.5),
                                         ("sk", "acct_1", "100"), ("sk", "acct_1", None)):
            with self.subTest(chiave=chiave, account=account, importo=importo):
                spy3 = PostFinto({ProviderConnect.TRANSFERS: {"id": "tr_mai"}})
                self.assertIsNone(ProviderConnect(chiave, fetch=spy3).trasferisci(account, importo, "eur", "R"))
                self.assertEqual(spy3.chiamate, [], "un bonifico rifiutato non deve toccare Stripe")
        for risposta in ({"id": "xx_1"}, {"id": None}, {}, None, "str"):                          # 243
            with self.subTest(risposta=risposta):
                p = ProviderConnect("sk", fetch=PostFinto({ProviderConnect.TRANSFERS: risposta}))
                self.assertIsNone(p.trasferisci("acct_1", 100, "eur", "R"))


if __name__ == "__main__":
    unittest.main()
