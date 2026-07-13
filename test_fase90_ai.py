"""
Test wiring AI nei contenuti marketing (fase90): il testo dei post viene RISCRITTO dall'AI
(pool a rotazione fase164) quando disponibile, con FALLBACK SICURO al deterministico se
l'AI è giù/quota/vuota/troppo lunga. Senza pool -> comportamento storico invariato.
"""
import unittest

from fase90_marketing import GeneratoreContenuti, crea_motore_marketing


class _PoolOK:
    def __init__(self, testo):
        self.t = testo
        self.chiamate = 0

    def genera(self, r):
        self.chiamate += 1
        return {"ok": True, "provider": "groq", "risultato": self.t}


class _PoolKO:
    def genera(self, r):
        return {"ok": False, "motivo": "tutti_esauriti"}


class _PoolBoom:
    def genera(self, r):
        raise RuntimeError("giu")


class TestGeneratoreAI(unittest.TestCase):
    def test_usa_ai_quando_ok(self):
        p = _PoolOK("Vieni su BookinVIP! 🏠")
        g = GeneratoreContenuti(pool_testo=p)
        post = g.crea("host", "it")
        self.assertIn("Vieni su BookinVIP", post.testo)
        self.assertTrue(post.testo.endswith(g._link("host")))   # link sempre appeso da noi
        self.assertGreaterEqual(p.chiamate, 1)

    def test_fallback_se_ai_ko(self):
        det = GeneratoreContenuti().crea("host", "it").testo
        post = GeneratoreContenuti(pool_testo=_PoolKO()).crea("host", "it")
        self.assertEqual(post.testo, det)                        # identico al deterministico

    def test_fallback_se_ai_esplode(self):
        det = GeneratoreContenuti().crea("guest", "en").testo
        post = GeneratoreContenuti(pool_testo=_PoolBoom()).crea("guest", "en")
        self.assertEqual(post.testo, det)

    def test_ai_vuoto_o_troppo_lungo_fallback(self):
        det = GeneratoreContenuti().crea("host", "it").testo
        self.assertEqual(GeneratoreContenuti(pool_testo=_PoolOK("")).crea("host", "it").testo, det)
        self.assertEqual(
            GeneratoreContenuti(pool_testo=_PoolOK("x" * 700)).crea("host", "it").testo, det)

    def test_toglie_virgolette(self):
        post = GeneratoreContenuti(pool_testo=_PoolOK('"Post tra virgolette 🎉"')).crea("host", "it")
        self.assertTrue(post.testo.startswith("Post tra virgolette"))   # virgolette rimosse

    def test_senza_pool_invariato(self):
        self.assertIsNotNone(GeneratoreContenuti().crea("host", "it"))

    def test_motore_accetta_pool(self):
        m = crea_motore_marketing(pool_testo=_PoolOK("Ciao dall'AI di BookinVIP 🚀"))
        posts = m._gen.campagna_completa(["it"])
        self.assertTrue(posts and all("Ciao dall'AI di BookinVIP" in p.testo for p in posts))


if __name__ == "__main__":
    unittest.main()
