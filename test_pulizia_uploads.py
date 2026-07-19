# -*- coding: utf-8 -*-
"""PULIZIA UPLOADS ORFANI (audit "10 moduli" 2026-07-19) — la scopa e' UTILE ma
soprattutto non deve MAI fare danni: qui si prova (a) la selettivita' (cancella SOLO
orfani vecchi; i file citati da annunci o chat e i file freschi NON si toccano),
(b) il fail-closed (censimento in errore -> zero cancellazioni), (c) il paracadute
(troppi 'orfani' = censimento sospetto -> annulla), (d) il kill-switch, (e) il
gancio 24h del tick."""
import datetime
import os
import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
import json


class TestPuliziaUploads(unittest.TestCase):
    def setUp(self):
        self.dir = d = tempfile.mkdtemp()
        self.updir = os.path.join(d, "uploads")
        os.makedirs(self.updir)
        os.environ["UPLOAD_DIR"] = self.updir
        os.environ.pop("PULIZIA_UPLOADS", None)
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=":memory:", db_inventario=":memory:", db_registro_host=":memory:",
            db_accettazioni=":memory:", db_messaggi=":memory:",
            commissione_bps=1500, psp_bps=300))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://b.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@pu.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]

    def tearDown(self):
        os.environ.pop("PULIZIA_UPLOADS", None)
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _file(self, nome, *, giorni_fa=0):
        p = os.path.join(self.updir, nome)
        with open(p, "wb") as f:
            f.write(b"\x89PNGx")
        if giorni_fa:
            vecchio = time.time() - giorni_fa * 86400
            os.utime(p, (vecchio, vecchio))
        return p

    def test_selettiva_cancella_solo_orfani_vecchi(self):
        self._file("orfano_vecchio.png", giorni_fa=8)
        self._file("orfano_fresco.png")
        self._file("ref_cat.png", giorni_fa=8)
        self._file("ref_chat.png", giorni_fa=8)
        s, c = self.g("POST", "/api/host/pubblica",
                      {"slug": "casa-pulizia", "titolo": "Casa", "citta": "Roma",
                       "prezzo_notte_cents": 10000, "capacita": 2,
                       "immagini": ["/uploads/ref_cat.png"]},
                      {"X-Host-Token": self.tok})
        self.assertIn(s, (200, 201), c)
        self.assertTrue(self.sis.messaggistica.invia(
            "rif-pulizia", "h1", "ospite", "ospite",
            "PROVA FOTO: /uploads/ref_chat.png"))
        rep = self.r.pulizia_uploads_orfani()
        self.assertEqual(rep.get("rimossi"), 1, rep)
        restanti = sorted(os.listdir(self.updir))
        self.assertEqual(restanti, ["orfano_fresco.png", "ref_cat.png", "ref_chat.png"],
                         "cancellato un file SBAGLIATO: %r" % restanti)

    def test_censimento_rotto_zero_cancellazioni(self):
        self._file("orfano_vecchio.png", giorni_fa=8)
        vero = self.sis.catalogo.nomi_uploads
        self.sis.catalogo.nomi_uploads = lambda: (_ for _ in ()).throw(RuntimeError("db giu"))
        try:
            rep = self.r.pulizia_uploads_orfani()
        finally:
            self.sis.catalogo.nomi_uploads = vero
        self.assertEqual(rep.get("saltata"), "censimento_in_errore", rep)
        self.assertEqual(os.listdir(self.updir), ["orfano_vecchio.png"],
                         "fail-closed violato: ha cancellato con censimento rotto")

    def test_paracadute_troppi_orfani(self):
        for i in range(12):
            self._file("orf%02d.png" % i, giorni_fa=8)
        rep = self.r.pulizia_uploads_orfani()
        self.assertEqual(rep.get("saltata"), "paracadute", rep)
        self.assertEqual(len(os.listdir(self.updir)), 12,
                         "paracadute violato: ha cancellato in massa")

    def test_kill_switch(self):
        self._file("orfano_vecchio.png", giorni_fa=8)
        os.environ["PULIZIA_UPLOADS"] = "0"
        rep = self.r.pulizia_uploads_orfani()
        self.assertEqual(rep.get("saltata"), "kill_switch", rep)
        self.assertEqual(os.listdir(self.updir), ["orfano_vecchio.png"])

    def test_gancio_24h(self):
        primo = self.r._pulizia_uploads_se_ora()
        self.assertIsInstance(primo, dict, "la prima corsa deve eseguire")
        self.assertIsNone(self.r._pulizia_uploads_se_ora(),
                          "entro 24h NON deve rieseguire")


if __name__ == "__main__":
    unittest.main(verbosity=2)
