# -*- coding: utf-8 -*-
"""Guardia SPOT VIDEO nelle landing città (fase97): gated, embed completo, XSS-safe.
Visto ROSSO: senza l'escape '</' nel JSON-LD il payload '</script>' evade lo script tag."""
import json
import os
import re
import tempfile
import unittest

from fase97_inbound_seo import genera_landing_host, video_locale


class TestVideoLanding(unittest.TestCase):

    def test_senza_video_la_pagina_e_identica_e_pulita(self):
        # GATED: la feature spenta non cambia UN byte (i default equivalgono a non passare nulla)
        prima = genera_landing_host("Roma", base_url="https://x.it")
        con_default = genera_landing_host("Roma", base_url="https://x.it",
                                          video_url="", video_poster="", video_data="")
        self.assertEqual(prima, con_default)
        self.assertNotIn("<video", prima)
        self.assertNotIn("og:video", prima)
        self.assertNotIn("VideoObject", prima)

    def test_con_video_embed_completo(self):
        p = genera_landing_host("Roma", base_url="https://x.it",
                                video_url="https://x.it/video/roma.mp4",
                                video_poster="https://x.it/video/roma.jpg",
                                video_data="2026-07-27")
        self.assertIn('property="og:video" content="https://x.it/video/roma.mp4"', p)
        self.assertIn('property="og:image" content="https://x.it/video/roma.jpg"', p)
        self.assertIn('<video src="https://x.it/video/roma.mp4"', p)
        self.assertIn('poster="https://x.it/video/roma.jpg"', p)
        blocchi = re.findall(r'<script type="application/ld\+json">(.*?)</script>', p, re.S)
        vo = [json.loads(b.replace("<\\/", "</")) for b in blocchi if '"VideoObject"' in b]
        self.assertEqual(len(vo), 1)
        self.assertEqual(vo[0]["contentUrl"], "https://x.it/video/roma.mp4")
        self.assertEqual(vo[0]["thumbnailUrl"], "https://x.it/video/roma.jpg")
        self.assertEqual(vo[0]["uploadDate"], "2026-07-27")
        self.assertTrue(vo[0]["name"] and vo[0]["description"])

    def test_senza_poster_niente_og_image_ne_poster(self):
        p = genera_landing_host("Roma", base_url="https://x.it",
                                video_url="https://x.it/video/roma.mp4")
        self.assertIn("og:video", p)
        self.assertNotIn("og:image", p)
        self.assertNotIn("poster=", p)
        self.assertNotIn("thumbnailUrl", p)

    def test_xss_url_ostile_neutralizzata_in_html_e_json(self):
        # nell'HTML l'apice/quote è escapato; nel JSON-LD '</script>' NON deve evadere lo script
        p = genera_landing_host("Roma", base_url="https://x.it",
                                video_url='https://x.it/a.mp4"></script><script>alert(1)</script>')
        self.assertNotIn("<script>alert(1)</script>", p)

    def test_video_locale_gated_e_rileva(self):
        os.environ.pop("VIDEO_DIR", None)
        self.assertIsNone(video_locale("roma"))                 # spenta di default
        with tempfile.TemporaryDirectory() as d:
            os.environ["VIDEO_DIR"] = d
            try:
                self.assertIsNone(video_locale("roma"))         # accesa ma senza file
                with open(os.path.join(d, "roma.mp4"), "wb") as f:
                    f.write(b"0" * 10)
                url, poster, data = video_locale("roma")
                self.assertEqual(url, "/video/roma.mp4")
                self.assertEqual(poster, "")                    # niente poster -> stringa vuota
                self.assertRegex(data, r"^\d{4}-\d{2}-\d{2}$")
                with open(os.path.join(d, "roma.jpg"), "wb") as f:
                    f.write(b"0")
                self.assertEqual(video_locale("roma")[1], "/video/roma.jpg")
                self.assertIsNone(video_locale("parigi"))       # altra città senza file
            finally:
                os.environ.pop("VIDEO_DIR", None)


if __name__ == "__main__":
    unittest.main()
