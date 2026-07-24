"""GUARDIA — generazione VIDEO con AI gratis (fase196): video corto (HF, gated/robusto) +
storyboard video lungo (usa i pool AI, ripiego mai-vuoto). Vista ROSSA: senza HF_TOKEN il video
corto non esiste; il fetch che non torna bytes -> nessun video (None), mai un crash."""
import unittest

from fase196_video_ai import (AdattatoreVideoCortoHF, GeneratoreStoryboard,
                              crea_video_ai_da_env)


class _PoolStub:
    """Pool AI finto: torna un risultato prevedibile per ogni prompt."""
    def __init__(self, prefix):
        self.prefix = prefix
        self.chiamate = 0
    def genera(self, prompt):
        self.chiamate += 1
        return {"risultato": self.prefix + str(self.chiamate)}


class TestVideoCorto(unittest.TestCase):
    def test_gated_senza_token(self):
        self.assertIsNone(crea_video_ai_da_env({})["corto"])

    def test_genera_bytes_con_token(self):
        visti = {}
        def f(url, *, metodo="GET", intestazioni=None, corpo=None, timeout=30.0):
            visti["url"] = url; visti["auth"] = (intestazioni or {}).get("Authorization")
            return 200, b"\x00\x00\x00\x18ftypmp4video-bytes"
        a = AdattatoreVideoCortoHF("HF", fetch=f)
        out = a.genera_video("Attico a Roma vista Colosseo")
        self.assertIsInstance(out, (bytes, bytearray))
        self.assertIn("api-inference.huggingface.co", visti["url"])
        self.assertIn("Bearer HF", visti["auth"])

    def test_model_loading_o_json_niente_video(self):
        # 503 con JSON (modello in caricamento) -> None, non crash
        a = AdattatoreVideoCortoHF("HF", fetch=lambda *a, **k: (503, {"error": "loading"}))
        self.assertIsNone(a.genera_video("x"))
        # errore di rete -> None
        def boom(*a, **k): raise RuntimeError("giu")
        self.assertIsNone(AdattatoreVideoCortoHF("HF", fetch=boom).genera_video("x"))

    def test_prompt_vuoto_niente_video(self):
        self.assertIsNone(AdattatoreVideoCortoHF("HF", fetch=lambda *a, **k: (200, b"x")).genera_video(""))


class TestStoryboard(unittest.TestCase):
    def test_scene_con_narrazione_e_immagine(self):
        sb = GeneratoreStoryboard(_PoolStub("narr-"), _PoolStub("http://img/"))
        r = sb.genera(titolo="Attico Roma", citta="Roma", n_scene=5)
        self.assertEqual(len(r["scene"]), 5)
        for s in r["scene"]:
            self.assertTrue(s["narrazione"], "ogni scena deve avere una narrazione")
            self.assertTrue(s["immagine_url"].startswith("http://img/"))
        self.assertEqual(r["durata_stimata_sec"], 30)

    def test_ripiego_senza_pool_mai_vuoto(self):
        # senza pool AI: narrazione deterministica (mai vuota), immagine vuota, nessun crash
        sb = GeneratoreStoryboard(None, None)
        r = sb.genera(titolo="Casa Mare", n_scene=3)
        self.assertEqual(len(r["scene"]), 3)
        for s in r["scene"]:
            self.assertTrue(s["narrazione"], "il ripiego non deve mai lasciare una scena senza testo")

    def test_n_scene_limitato(self):
        sb = GeneratoreStoryboard(None, None)
        self.assertEqual(len(sb.genera(titolo="x", n_scene=99)["scene"]), 10)   # cap 10
        self.assertEqual(len(sb.genera(titolo="x", n_scene=1)["scene"]), 3)     # min 3


class TestFactory(unittest.TestCase):
    def test_storyboard_sempre_presente(self):
        strumenti = crea_video_ai_da_env({}, pool_testo=_PoolStub("t"), pool_immagine=_PoolStub("i"))
        self.assertIsNotNone(strumenti["storyboard"])
        self.assertIsNone(strumenti["corto"])       # dormiente senza HF_TOKEN

    def test_corto_acceso_con_token(self):
        self.assertIsNotNone(crea_video_ai_da_env({"HF_TOKEN": "T"}, fetch=lambda *a, **k: (200, b"v"))["corto"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
