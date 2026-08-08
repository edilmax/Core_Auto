"""Test Fase 101 - Stripe Connect split-all'origine. fetch STUB: nessuna rete."""
import unittest

from fase101_stripe_connect import (ProviderStripeConnect, costruisci_params,
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
            def __getattr__(self, nome):        # qualunque accesso esplode
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


if __name__ == "__main__":
    unittest.main()
