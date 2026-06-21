"""
Test Fase 63 - Recensioni verificate (anti-fake).

Copre: emissione diritto + invio verificato, rifiuto senza token / token manomesso /
scaduto, voto fuori range, dedup (una per prenotazione), riepilogo (media in centesimi
interi + distribuzione), elenco con testo taggato lingua, robustezza, e stress 10x.
"""
import base64
import json
import os
import shutil
import tempfile
import threading
import unittest

from fase59_concierge import FirmaQuote
from fase63_recensioni import (
    EmettitoreDiritto, EsitoRecensione, RegistroRecensioni,
    crea_registro_recensioni,
)

SEGRETO = b"0123456789abcdef0123456789abcdef"


def _setup(clock=None):
    reg = crea_registro_recensioni(":memory:", SEGRETO, orologio=clock)
    em = EmettitoreDiritto(FirmaQuote(SEGRETO), orologio=clock)
    return reg, em


class TestInvio(unittest.TestCase):
    def test_emetti_e_invia_verificata(self):
        reg, em = _setup()
        token = em.emetti("p1", "casa")
        e = reg.invia(token, 5, "Bellissimo soggiorno", "it")
        self.assertTrue(e.ok)
        self.assertTrue(e.verificata)
        self.assertEqual(reg.riepilogo("casa")["conteggio"], 1)

    def test_senza_token_valido_rifiutata(self):
        reg, _ = _setup()
        e = reg.invia("token.inventato", 5, "falsa")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "diritto_non_valido")

    def test_token_manomesso(self):
        reg, em = _setup()
        token = em.emetti("p1", "casa")
        b64, sig = token.split(".")
        payload = json.loads(base64.urlsafe_b64decode(b64))
        payload["alloggio_id"] = "casa-rivale"      # prova a dirottare la recensione
        b64f = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode()
        e = reg.invia(b64f + "." + sig, 1, "sabotaggio")
        self.assertFalse(e.ok)                       # firma rotta

    def test_voto_fuori_range(self):
        reg, em = _setup()
        token = em.emetti("p1", "casa")
        for voto in (0, 6, 5.0, True, "5"):
            e = reg.invia(em.emetti("p%s" % voto, "casa"), voto)
            self.assertFalse(e.ok)
            self.assertEqual(e.motivo, "voto_non_valido")

    def test_dedup_una_per_prenotazione(self):
        reg, em = _setup()
        token = em.emetti("p1", "casa")
        self.assertTrue(reg.invia(token, 5, "prima").ok)
        e2 = reg.invia(token, 1, "seconda")
        self.assertFalse(e2.ok)
        self.assertEqual(e2.motivo, "gia_recensita")
        self.assertEqual(reg.riepilogo("casa")["conteggio"], 1)

    def test_scaduta(self):
        t = {"v": 1000}
        reg, em = _setup(clock=lambda: t["v"])
        token = em.emetti("p1", "casa")             # exp = 1000 + 90gg
        t["v"] = 1000 + 91 * 86400
        e = reg.invia(token, 5, "tardiva")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "diritto_scaduto")

    def test_testo_troppo_lungo(self):
        reg, em = _setup()
        e = reg.invia(em.emetti("p1", "casa"), 4, "x" * 5000)
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "testo_non_valido")


class TestRiepilogo(unittest.TestCase):
    def test_media_e_distribuzione(self):
        reg, em = _setup()
        for i, voto in enumerate((5, 4, 3, 5)):
            reg.invia(em.emetti("p%d" % i, "casa"), voto)
        rip = reg.riepilogo("casa")
        self.assertEqual(rip["conteggio"], 4)
        # (5+4+3+5)=17, media 4.25 -> 425 centesimi (intero, zero float)
        self.assertEqual(rip["media_centesimi"], 425)
        self.assertIsInstance(rip["media_centesimi"], int)
        self.assertEqual(rip["distribuzione"][5], 2)
        self.assertEqual(rip["distribuzione"][1], 0)

    def test_riepilogo_vuoto(self):
        reg, _ = _setup()
        rip = reg.riepilogo("mai")
        self.assertEqual(rip["conteggio"], 0)
        self.assertEqual(rip["media_centesimi"], 0)

    def test_elenco_testo_taggato(self):
        reg, em = _setup()
        reg.invia(em.emetti("p1", "casa"), 5, "Splendido", "it")
        elenco = reg.elenco("casa")
        self.assertEqual(elenco[0]["testo"], {"text": "Splendido", "lang": "it"})
        self.assertEqual(elenco[0]["voto"], 5)

    def test_isolamento_per_alloggio(self):
        reg, em = _setup()
        reg.invia(em.emetti("p1", "casa-a"), 5)
        reg.invia(em.emetti("p2", "casa-b"), 1)
        self.assertEqual(reg.riepilogo("casa-a")["media_centesimi"], 500)
        self.assertEqual(reg.riepilogo("casa-b")["media_centesimi"], 100)


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        reg, _ = _setup()
        for bad in (None, 123, [], "", "a.b"):
            try:
                reg.invia(bad, bad)
                reg.riepilogo(bad)
                reg.elenco(bad)
            except Exception as e:  # pragma: no cover
                self.fail(f"sollevato su {bad!r}: {e}")


class TestStress(unittest.TestCase):
    def test_invii_concorrenti_10x(self):
        for rip in range(10):
            d = tempfile.mkdtemp()
            try:
                path = os.path.join(d, f"r{rip}.db")
                reg = crea_registro_recensioni(path, SEGRETO)
                em = EmettitoreDiritto(FirmaQuote(SEGRETO))
                errori = []
                lock = threading.Lock()

                def worker(i):
                    try:
                        e = reg.invia(em.emetti("p%d" % i, "casa"), (i % 5) + 1, "ok")
                        with lock:
                            errori.append(e.ok)
                    except Exception as ex:  # pragma: no cover
                        with lock:
                            errori.append(ex)

                th = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
                for t in th:
                    t.start()
                for t in th:
                    t.join()
                self.assertTrue(all(x is True for x in errori))
                self.assertEqual(reg.riepilogo("casa")["conteggio"], 30)
            finally:
                shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
