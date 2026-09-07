"""Test Fase 143 - KYC host. SQLite :memory:, provider iniettato: nessuna rete."""
import sqlite3
import threading
import unittest

from fase143_kyc_host import (KYCHost, crea_kyc_host, stripe_identity_crea,
                              stripe_identity_stato)


def kyc(provider=lambda h: "sess_" + h):
    k = crea_kyc_host(":memory:", avvia_sessione=provider)
    k.inizializza_schema()
    return k


class TestKYC(unittest.TestCase):
    def test_flusso_verificato(self):
        k = kyc()
        self.assertEqual(k.stato("h1"), "non_avviata")
        r = k.avvia("h1")
        self.assertTrue(r["ok"])
        self.assertEqual(r["session_ref"], "sess_h1")
        self.assertEqual(k.stato("h1"), "in_corso")
        self.assertFalse(k.verificato("h1"))
        self.assertTrue(k.conferma("h1", "verificato"))
        self.assertTrue(k.verificato("h1"))

    def test_respinto_e_ritenta(self):
        k = kyc()
        k.avvia("h1")
        self.assertTrue(k.conferma("h1", "respinto"))
        self.assertEqual(k.stato("h1"), "respinto")
        self.assertTrue(k.avvia("h1"))                     # respinto -> in_corso di nuovo

    def test_gated_senza_provider(self):
        k = crea_kyc_host(":memory:")
        k.inizializza_schema()
        self.assertFalse(k.avvia("h1")["ok"])

    def test_transizione_illegale(self):
        k = kyc()
        self.assertFalse(k.conferma("h1", "verificato"))   # non_avviata->verificato no
        self.assertFalse(k.conferma("h1", "boh"))

    def test_verificato_terminale(self):
        k = kyc()
        k.avvia("h1")
        k.conferma("h1", "verificato")
        self.assertFalse(k.conferma("h1", "respinto"))     # verificato è terminale

    def test_provider_solleva_isolato(self):
        def boom(h):
            raise RuntimeError("stripe giu")
        k = crea_kyc_host(":memory:", avvia_sessione=boom)
        k.inizializza_schema()
        self.assertFalse(k.avvia("h1")["ok"])

    def test_provider_ref_vuoto(self):
        k = crea_kyc_host(":memory:", avvia_sessione=lambda h: None)
        k.inizializza_schema()
        self.assertFalse(k.avvia("h1")["ok"])


class _ConnRotta:
    """Lascia creare lo schema e poi esplode su ogni altra query (D19: i rami «ISOLATO»
    eseguiti davvero)."""
    def __init__(self, con):
        object.__setattr__(self, "_con", con)
        object.__setattr__(self, "rotta", False)

    def execute(self, sql, *a):
        if self.rotta and "CREATE TABLE" not in sql and "PRAGMA" not in sql:
            raise sqlite3.OperationalError("disco in fiamme")
        return self._con.execute(sql, *a)

    def close(self):
        pass

    def __enter__(self):
        return self._con.__enter__()

    def __exit__(self, *a):
        return self._con.__exit__(*a)

    def __getattr__(self, n):
        return getattr(self._con, n)


def _kyc_rompibile():
    con = _ConnRotta(sqlite3.connect(":memory:", check_same_thread=False))
    k = KYCHost(lambda: con, avvia_sessione=lambda h: "sess_" + h)
    k.inizializza_schema()
    return k, con


class TestIDiciassetteSopravvissutiDellaNotte(unittest.TestCase):
    """Una guardia per ognuno dei 17 punti trovati scoperti dal Giudice la notte del
    2026-09-06 (giudice_notte_blocco3_2.log), vista ROSSA col mutante iniettato con l'editor."""

    LOG = "core_auto.kyc_host"

    def _traccia(self, reg, frase, tipo=sqlite3.OperationalError):
        rec = [r for r in reg.records if frase in r.getMessage()]
        self.assertEqual(len(rec), 1, [r.getMessage() for r in reg.records])
        self.assertIsInstance(rec[0].exc_info, tuple, "exc_info=True: la traccia c'e', non un False")
        self.assertIs(rec[0].exc_info[0], tipo)

    def test_riga89_riferimento_col_disco_rotto_dice_non_disponibile_e_lascia_la_traccia(self):
        k, con = _kyc_rompibile()
        con.rotta = True
        with self.assertLogs(self.LOG, level="WARNING") as reg:
            self.assertEqual(k.riferimento("h1"), {"stato": "non_disponibile", "session_ref": "", "ts": None})
        self._traccia(reg, "riferimento KYC fallito")

    def test_riga99_senza_host_o_senza_provider_non_si_avvia_e_il_provider_non_viene_chiamato(self):
        chiamate = []

        def provider(h):
            chiamate.append(h)
            return "sess_" + h
        k = kyc(provider)
        self.assertEqual(k.avvia(""), {"ok": False, "errore": "provider_non_configurato"})
        self.assertEqual(k.avvia(None), {"ok": False, "errore": "provider_non_configurato"})
        self.assertEqual(chiamate, [], "con un host vuoto il provider NON si chiama")
        k2 = crea_kyc_host(":memory:")
        k2.inizializza_schema()
        self.assertEqual(k2.avvia("h1"), {"ok": False, "errore": "provider_non_configurato"})
        self.assertTrue(k.avvia("h1")["ok"], "host e provider: si avvia")

    def test_riga104_il_provider_che_esplode_lascia_la_traccia_e_non_avvia(self):
        def boom(h):
            raise RuntimeError("provider giu'")
        k = kyc(boom)
        with self.assertLogs(self.LOG, level="WARNING") as reg:
            self.assertEqual(k.avvia("h1"), {"ok": False, "errore": "sessione_non_creata"})
        self._traccia(reg, "avvio sessione KYC fallito", RuntimeError)
        self.assertEqual(k.stato("h1"), "non_avviata")

    def test_riga109_una_transizione_non_valida_risponde_ok_False_e_lo_stato_corrente(self):
        k = kyc()
        k.avvia("h1")
        self.assertTrue(k.conferma("h1", "verificato"))
        esito = k.avvia("h1")                      # da 'verificato' non si riparte
        self.assertIs(esito["ok"], False)
        self.assertEqual(esito["errore"], "transizione_non_valida")
        self.assertEqual(esito["stato"], "verificato")

    def test_riga122_123_registra_avvio_vuole_host_E_riferimento(self):
        k = kyc()
        self.assertIs(k.registra_avvio("", "vs_1"), False)
        self.assertIs(k.registra_avvio("h1", ""), False)
        self.assertIs(k.registra_avvio(None, None), False)
        self.assertEqual(k.stato("h1"), "non_avviata", "niente scritto")
        self.assertTrue(k.registra_avvio("h1", "vs_1"))
        self.assertEqual(k.sessione("h1"), "vs_1")

    def test_riga138_uno_stato_inventato_non_transita_e_non_scrive(self):
        k = kyc()
        k.avvia("h1")
        self.assertIs(k._transita("h1", "stato_inventato", None), False)
        self.assertEqual(k.stato("h1"), "in_corso")
        self.assertIs(k.conferma("h1", "stato_inventato"), False)

    def test_riga159_160_la_transizione_col_disco_rotto_risponde_False_e_lascia_la_traccia(self):
        k, con = _kyc_rompibile()
        con.rotta = True
        with self.assertLogs(self.LOG, level="WARNING") as reg:
            self.assertIs(k.registra_avvio("h1", "vs_1"), False)
        self._traccia(reg, "transizione KYC fallita")

    def test_riga172_stripe_identity_crea_vuole_chiave_E_host_testuale_non_vuoto(self):
        chiamate = []

        def fetch(percorso, dati, chiave):
            chiamate.append((percorso, dati, chiave))
            return {"id": "vs_1", "url": "https://verify.stripe.test/vs_1"}
        self.assertIsNone(stripe_identity_crea("", "h1", "https://x/r", fetch=fetch))
        self.assertIsNone(stripe_identity_crea("sk_test_x", None, "https://x/r", fetch=fetch))
        self.assertIsNone(stripe_identity_crea("sk_test_x", "", "https://x/r", fetch=fetch))
        self.assertIsNone(stripe_identity_crea("sk_test_x", 123, "https://x/r", fetch=fetch))
        self.assertEqual(chiamate, [], "senza chiave o senza host non si chiama Stripe")
        self.assertEqual(stripe_identity_crea("sk_test_x", "h1", "https://x/r", fetch=fetch),
                         {"id": "vs_1", "url": "https://verify.stripe.test/vs_1"})
        self.assertEqual(len(chiamate), 1)

    def test_riga175_il_return_url_assente_viaggia_come_stringa_vuota(self):
        visti = []

        def fetch(percorso, dati, chiave):
            visti.append(dict(dati))
            return {"id": "vs_1", "url": "https://u"}
        stripe_identity_crea("sk_test_x", "h1", None, fetch=fetch)
        stripe_identity_crea("sk_test_x", "h1", "https://x/r", fetch=fetch)
        self.assertEqual(visti[0]["return_url"], "")
        self.assertEqual(visti[1]["return_url"], "https://x/r")
        self.assertEqual(visti[0]["metadata[host_id]"], "h1")
        self.assertEqual(visti[0]["type"], "document")

    def test_riga189_servono_id_E_url_per_avere_una_sessione(self):
        self.assertIsNone(stripe_identity_crea("sk_test_x", "h1", "", fetch=lambda *a: {"id": "vs_1"}))
        self.assertIsNone(stripe_identity_crea("sk_test_x", "h1", "", fetch=lambda *a: {"url": "https://u"}))
        self.assertIsNone(stripe_identity_crea("sk_test_x", "h1", "", fetch=lambda *a: {}))
        self.assertEqual(stripe_identity_crea("sk_test_x", "h1", "", fetch=lambda *a: {"id": "vs_1", "url": "https://u"}),
                         {"id": "vs_1", "url": "https://u"})

    def test_riga194_stripe_che_esplode_lascia_la_traccia_e_niente_sessione(self):
        def fetch(*a):
            raise RuntimeError("stripe giu'")
        with self.assertLogs(self.LOG, level="WARNING") as reg:
            self.assertIsNone(stripe_identity_crea("sk_test_x", "h1", "", fetch=fetch))
        self._traccia(reg, "creazione sessione fallita", RuntimeError)

    def test_riga203_lo_stato_si_chiede_solo_con_chiave_E_un_id_vs_(self):
        chiamate = []

        def fetch(percorso, dati, chiave):
            chiamate.append(percorso)
            return {"status": "verified"}
        self.assertIsNone(stripe_identity_stato("", "vs_1", fetch=fetch))
        self.assertIsNone(stripe_identity_stato("sk_test_x", "cs_1", fetch=fetch))
        self.assertIsNone(stripe_identity_stato("sk_test_x", None, fetch=fetch))
        self.assertIsNone(stripe_identity_stato("sk_test_x", "", fetch=fetch))
        self.assertEqual(chiamate, [], "niente chiamata senza chiave o senza un vs_")
        self.assertEqual(stripe_identity_stato("sk_test_x", "vs_1", fetch=fetch), "verified")
        self.assertEqual(chiamate, ["identity/verification_sessions/vs_1"])
        self.assertIsNone(stripe_identity_stato("sk_test_x", "vs_1", fetch=lambda *a: {"status": ""}))

    def test_riga224_il_kyc_in_memoria_si_usa_anche_da_un_altro_thread(self):
        k = kyc()
        esiti = {}

        def lavoro():
            try:
                esiti["esito"] = k.avvia("h1")
            except Exception as e:
                esiti["errore"] = "%s: %s" % (type(e).__name__, e)
        t = threading.Thread(target=lavoro)
        t.start()
        t.join(10)
        self.assertNotIn("errore", esiti, esiti.get("errore"))
        self.assertTrue(esiti["esito"]["ok"], esiti)
        self.assertEqual(k.stato("h1"), "in_corso")


if __name__ == "__main__":
    unittest.main()
