"""
Test Fase 80 - Sentinel (FIM + canary + catena integrita').

Copre: hash_file, istantanea+verifica (integro/modificato/aggiunto/rimosso), canary
violato (critico), notifica isolata, aggiorna_baseline, catena hash append-only
(integra / tamper su evento / tamper su entry_hash / cancellazione record), robustezza.
"""
import os
import shutil
import sqlite3
import tempfile
import unittest

from fase80_sentinel import (
    CatenaIntegrita, ReportIntegrita, Sentinel, crea_catena, hash_file,
)


def _scrivi(path, contenuto):
    with open(path, "w", encoding="utf-8") as f:
        f.write(contenuto)


class TestHashFile(unittest.TestCase):
    def test_hash_e_mancante(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "a.txt")
            _scrivi(p, "ciao")
            self.assertEqual(len(hash_file(p)), 64)
            self.assertIsNone(hash_file(os.path.join(d, "non-esiste")))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestSentinelFIM(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        for n in ("a.py", "b.py", "c.py"):
            _scrivi(os.path.join(self.d, n), "# " + n)
        self.s = Sentinel(cartella=self.d, estensioni=(".py",))
        self.s.istantanea()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_integro(self):
        self.assertTrue(self.s.verifica().integro)

    def test_modificato(self):
        _scrivi(os.path.join(self.d, "a.py"), "# HACKED")
        r = self.s.verifica()
        self.assertFalse(r.integro)
        self.assertEqual([os.path.basename(p) for p in r.modificati], ["a.py"])

    def test_aggiunto(self):
        _scrivi(os.path.join(self.d, "backdoor.py"), "evil")
        r = self.s.verifica()
        self.assertIn("backdoor.py", [os.path.basename(p) for p in r.aggiunti])

    def test_rimosso(self):
        os.remove(os.path.join(self.d, "b.py"))
        r = self.s.verifica()
        self.assertEqual([os.path.basename(p) for p in r.rimossi], ["b.py"])

    def test_estensione_ignorata(self):
        _scrivi(os.path.join(self.d, "note.txt"), "x")   # non .py
        self.assertTrue(self.s.verifica().integro)

    def test_aggiorna_baseline(self):
        _scrivi(os.path.join(self.d, "a.py"), "# modifica legittima")
        self.assertFalse(self.s.verifica().integro)
        self.s.aggiorna_baseline()
        self.assertTrue(self.s.verifica().integro)


class TestCanary(unittest.TestCase):
    def test_canary_violato(self):
        d = tempfile.mkdtemp()
        try:
            canary = os.path.join(d, ".env.fake")
            _scrivi(canary, "AWS_SECRET=esca")
            _scrivi(os.path.join(d, "vero.py"), "ok")
            s = Sentinel(cartella=d, canary=[canary])
            s.istantanea()
            self.assertTrue(s.verifica().integro)
            # l'hacker apre/modifica il file esca
            _scrivi(canary, "AWS_SECRET=esca\n# letto")
            r = s.verifica()
            self.assertFalse(r.integro)
            self.assertTrue(r.critico)
            self.assertEqual([os.path.basename(p) for p in r.canary_violati],
                             [".env.fake"])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_canary_rimosso(self):
        d = tempfile.mkdtemp()
        try:
            canary = os.path.join(d, "password_admin.pdf")
            _scrivi(canary, "esca")
            s = Sentinel(canary=[canary], percorsi=[])
            s.istantanea()
            os.remove(canary)
            self.assertTrue(s.verifica().critico)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestNotifica(unittest.TestCase):
    def test_notifica_isolata(self):
        d = tempfile.mkdtemp()
        try:
            _scrivi(os.path.join(d, "a.py"), "x")
            ricevute = []
            s = Sentinel(cartella=d, notificatore=ricevute.append)
            s.istantanea()
            _scrivi(os.path.join(d, "a.py"), "HACKED")
            s.verifica()
            self.assertEqual(len(ricevute), 1)
            self.assertEqual(ricevute[0]["tipo"], "integrita_violata")

            def boom(_):
                raise RuntimeError("canale giu'")
            s2 = Sentinel(cartella=d, notificatore=boom)
            s2.istantanea()
            _scrivi(os.path.join(d, "a.py"), "ANCORA")
            self.assertFalse(s2.verifica().integro)   # non crasha
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestCatena(unittest.TestCase):
    def test_append_e_verifica(self):
        c = crea_catena()
        c.append("evento1")
        c.append("evento2")
        c.append("evento3")
        self.assertEqual(c.conteggio(), 3)
        self.assertTrue(c.verifica_catena()["integro"])

    def test_catena_vuota_integra(self):
        self.assertTrue(crea_catena().verifica_catena()["integro"])

    def test_tamper_su_evento(self):
        path = os.path.join(tempfile.mkdtemp(), "cat.db")
        try:
            c = crea_catena(path)
            c.append("a")
            c.append("b")
            c.append("c")
            # manomissione diretta del log (come farebbe un hacker)
            con = sqlite3.connect(path)
            con.execute("UPDATE catena SET evento='MANOMESSO' WHERE seq=2")
            con.commit()
            con.close()
            v = c.verifica_catena()
            self.assertFalse(v["integro"])
            self.assertEqual(v["rotta_a"], 2)
        finally:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    def test_tamper_su_entry_hash(self):
        path = os.path.join(tempfile.mkdtemp(), "cat.db")
        try:
            c = crea_catena(path)
            c.append("a")
            c.append("b")
            con = sqlite3.connect(path)
            con.execute("UPDATE catena SET entry_hash='deadbeef' WHERE seq=1")
            con.commit()
            con.close()
            self.assertFalse(c.verifica_catena()["integro"])
        finally:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    def test_cancellazione_record_rompe_catena(self):
        path = os.path.join(tempfile.mkdtemp(), "cat.db")
        try:
            c = crea_catena(path)
            c.append("a")
            c.append("b")
            c.append("c")
            con = sqlite3.connect(path)
            con.execute("DELETE FROM catena WHERE seq=2")   # cancella un anello
            con.commit()
            con.close()
            self.assertFalse(c.verifica_catena()["integro"])
        finally:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)


class TestRobustezza(unittest.TestCase):
    def test_mai_solleva(self):
        for bad in (None, 123):
            self.assertIsNone(hash_file(bad))
        s = Sentinel(percorsi=["/non/esiste/x.py"])
        s.istantanea()
        try:
            s.verifica()
        except Exception as e:  # pragma: no cover
            self.fail(f"verifica ha sollevato: {e}")


if __name__ == "__main__":
    unittest.main()
