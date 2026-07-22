"""GUARDIA — convertitore valuta OXR (fase99 ProviderTassi): cache NON-BLOCCANTE e display-only.

Accendere il convertitore («≈ nella tua moneta») senza cache sarebbe un autogol: il provider
vecchio contattava Open Exchange Rates a OGNI preventivo cross-valuta (timeout 15s, nessuna
cache) → bloccava le richieste e bruciava il piano gratuito (~1000 chiamate/mese). Questa
guardia prova che ora:

  1. GATED: senza chiave OXR non si contatta MAI la rete (tasso None).
  2. Matematica del cross-rate corretta (via USD, base del piano free).
  3. CACHE: finché è fresca, N preventivi = 1 sola chiamata a OXR.
  4. NON BLOCCA: con la cache ancora vuota, `tasso()` torna subito (non aspetta il fetch).
  5. TTL + stale-while-revalidate: scaduta la cache, serve i tassi VECCHI all'istante e
     rinfresca in SFONDO.
  6. FAIL-SAFE: se OXR è giù, i tassi vecchi restano (mai un errore all'utente).
  7. `scalda()` riempie la cache in sfondo (usato allo startup).

Le prove 3 e 4 sono ROSSE sul provider vecchio (che rifaceva fetch a ogni chiamata).
ZERO rete: il fetch è iniettato; l'orologio è iniettato → TTL deterministico.
"""

import threading
import time
import unittest
from decimal import Decimal

from fase99_multicurrency import ProviderTassi, crea_provider_tassi

RATES = {"USD": 1.0, "EUR": 0.90, "JPY": 150.0, "GBP": 0.80}


def _fetch(rates=RATES, contatore=None):
    def f(url):
        if contatore is not None:
            contatore[0] += 1
        return {"rates": dict(rates)}
    return f


class TestGatingEMatematica(unittest.TestCase):

    def test_senza_chiave_non_contatta_mai_la_rete(self):
        c = [0]
        p = ProviderTassi("", fetch=_fetch(contatore=c))
        self.assertIsNone(p.tasso("EUR", "JPY"))
        self.assertFalse(p.aggiorna())
        p.scalda()
        time.sleep(0.1)
        self.assertEqual(c[0], 0, "senza chiave OXR non deve MAI essere contattato")

    def test_cross_rate_via_usd(self):
        p = ProviderTassi("k", fetch=_fetch())
        self.assertTrue(p.aggiorna())
        self.assertEqual(p.tasso("EUR", "JPY"), Decimal("150.0") / Decimal("0.90"))
        self.assertEqual(p.tasso("USD", "EUR"), Decimal("0.90"))
        self.assertEqual(p.tasso("JPY", "USD"), Decimal(1) / Decimal("150.0"))
        self.assertEqual(p.tasso("EUR", "EUR"), Decimal(1))     # stessa valuta = 1
        self.assertIsNone(p.tasso("EUR", "XXX"))                # valuta ignota = None (mai crash)


class TestCacheNonBloccante(unittest.TestCase):

    def test_cache_fresca_una_sola_chiamata(self):
        c = [0]
        p = ProviderTassi("k", fetch=_fetch(contatore=c))
        self.assertTrue(p.aggiorna())                # 1 sola chiamata
        for _ in range(50):
            p.tasso("EUR", "USD")                    # tutti dalla cache
        self.assertEqual(c[0], 1, "la cache fresca NON deve rifare fetch (era 51 col vecchio)")

    def test_tasso_non_blocca_con_cache_vuota(self):
        # fetch LENTO: se tasso() aspettasse il fetch, ci metterebbe >2s. Deve tornare SUBITO.
        def _lento(url):
            time.sleep(2)
            return {"rates": RATES}
        p = ProviderTassi("k", fetch=_lento)
        t0 = time.time()
        r = p.tasso("EUR", "USD")
        dt = time.time() - t0
        self.assertIsNone(r, "cache vuota -> None (la stima non compare per QUEL preventivo)")
        self.assertLess(dt, 0.5, "tasso() NON deve bloccare la richiesta sul fetch lento")

    def test_scalda_riempie_la_cache_in_sfondo(self):
        c = [0]
        p = ProviderTassi("k", fetch=_fetch(contatore=c))
        p.scalda()                                   # non blocca; scarica in sfondo
        for _ in range(60):                          # aspetta max 3s che il thread finisca
            if p._fresco():
                break
            time.sleep(0.05)
        self.assertTrue(p._fresco(), "scalda() deve riempire la cache in sfondo")
        self.assertEqual(p.tasso("USD", "GBP"), Decimal("0.80"))

    def test_un_solo_scarico_alla_volta(self):
        # molte chiamate scalda() concorrenti -> UN solo fetch in volo (lock)
        c = [0]
        def _lento(url):
            time.sleep(0.4)
            c[0] += 1
            return {"rates": RATES}
        p = ProviderTassi("k", fetch=_lento)
        for _ in range(10):
            p.scalda()
        time.sleep(1.0)
        self.assertEqual(c[0], 1, "scalda() concorrenti non devono moltiplicare i fetch")


class TestTTLeFailSafe(unittest.TestCase):

    def test_ttl_scaduto_serve_stale_e_rinfresca_in_sfondo(self):
        clock = [1000.0]
        c = [0]
        p = ProviderTassi("k", fetch=_fetch(contatore=c),
                          orologio=lambda: clock[0], ttl_sec=3600)
        self.assertTrue(p.aggiorna())                # cache @ t=1000 (1 fetch)
        self.assertTrue(p._fresco())
        clock[0] = 1000 + 3601                       # oltre il TTL
        self.assertFalse(p._fresco())
        r = p.tasso("USD", "EUR")                    # stale: ritorna SUBITO il vecchio (EUR per 1 USD)
        self.assertEqual(r, Decimal("0.90"))
        for _ in range(60):                          # e rinfresca in sfondo
            if c[0] >= 2:
                break
            time.sleep(0.05)
        self.assertGreaterEqual(c[0], 2, "cache scaduta deve rinfrescare in sfondo")

    def test_oxr_giu_preserva_i_tassi_vecchi(self):
        modo = {"rompi": False}
        def f(url):
            if modo["rompi"]:
                raise RuntimeError("OXR irraggiungibile")
            return {"rates": RATES}
        p = ProviderTassi("k", fetch=f)
        self.assertTrue(p.aggiorna())                # cache buona
        modo["rompi"] = True
        self.assertFalse(p.aggiorna())               # fetch fallisce...
        self.assertEqual(p.tasso("USD", "EUR"), Decimal("0.90"),
                         "OXR giu' -> i tassi vecchi restano (fail-safe), mai None a sorpresa")

    def test_fetch_malformato_non_rompe(self):
        for cattivo in ({}, {"rates": None}, {"rates": {}}, {"altro": 1}, None, "boh"):
            p = ProviderTassi("k", fetch=lambda url, v=cattivo: v)
            self.assertFalse(p.aggiorna())
            self.assertIsNone(p.tasso("EUR", "USD"))  # nessun crash, nessun tasso


class TestFabbrica(unittest.TestCase):

    def test_crea_provider_passa_i_parametri(self):
        p = crea_provider_tassi("k", fetch=_fetch(), orologio=lambda: 5.0, ttl_sec=10)
        self.assertIsInstance(p, ProviderTassi)
        self.assertTrue(p.aggiorna())
        self.assertEqual(p.tasso("USD", "JPY"), Decimal("150.0"))

    def test_chiave_vuota_e_none_gestite(self):
        for k in ("", None):
            p = crea_provider_tassi(k, fetch=_fetch())
            self.assertIsNone(p.tasso("EUR", "USD"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
