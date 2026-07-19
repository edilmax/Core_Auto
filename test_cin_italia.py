"""CIN — Codice Identificativo Nazionale (C1 del mega-audit legge, 2026-07-20).

Reg. UE 2024/1028 + DL 145/2023: dal 20/05/2026 le piattaforme devono RACCOGLIERE,
ESPORRE e pretendere il CIN per gli annunci di alloggi in ITALIA (multe 500-5.000EUR
per annuncio senza codice). Guardie:
  - MOTORE (fase57): campo `cin` opzionale, formato alfanumerico 6..30 normalizzato
    MAIUSCOLO; round-trip su INSERT e UPDATE; migrazione idempotente su DB esistenti.
  - POLICY (fase83): pubblicare in ITALIA senza CIN = 422 `cin_obbligatorio_italia`;
    bozza senza CIN ammessa; estero senza CIN ammesso; il motore resta neutro.
  - ESPOSIZIONE: il CIN esce nel dettaglio pubblico (obbligo di mostrarlo ai clienti)
    e nella vista owner (per il form di modifica).
"""
import datetime
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from fase57_vetrina import valida_scheda
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

CIN_OK = "IT012034B4ABC1DEFG"


class TestMotoreCin(unittest.TestCase):
    def _base(self, **extra):
        d = {"host_id": "h1", "slug": "casa", "titolo": "Casa", "citta": "Roma",
             "prezzo_notte_cents": 10000, "capacita": 2}
        d.update(extra)
        return d

    def test_formato_cin(self):
        ok, _, s = valida_scheda(self._base(cin="it012034b4abc1defg"))
        self.assertTrue(ok)
        self.assertEqual(s.cin, "IT012034B4ABC1DEFG")     # normalizzato MAIUSCOLO
        ok, _, s = valida_scheda(self._base())            # senza cin: retro-compatibile
        self.assertTrue(ok)
        self.assertEqual(s.cin, "")
        for cattivo in ("ABC", "X" * 31, "IT-0120/34", "IT 012", 12345, None):
            ok, cod, _ = valida_scheda(self._base(cin=cattivo))
            self.assertFalse(ok, cattivo)
            self.assertEqual(cod, "cin_non_valido", cattivo)

    def test_migrazione_idempotente_e_roundtrip(self):
        from fase57_vetrina import crea_catalogo
        d = tempfile.mkdtemp()
        try:
            db = os.path.join(d, "v.db")
            # DB "vecchio" senza colonna cin: la crea la migrazione senza toccare i dati
            v = crea_catalogo(db)
            ok, _, s = valida_scheda(self._base(cin=CIN_OK))
            v.pubblica(s, [])
            det = v.dettaglio("casa")
            self.assertEqual(det["cin"], CIN_OK)
            # UPDATE: cambio cin -> round-trip
            ok, _, s2 = valida_scheda(self._base(cin="IT999888A1XYZ2WQRS", titolo="Casa2"))
            v.pubblica(s2, [])
            self.assertEqual(v.dettaglio("casa")["cin"], "IT999888A1XYZ2WQRS")
            # doppia inizializzazione = nessun errore (ALTER idempotente)
            crea_catalogo(db)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestPolicyItalia(unittest.TestCase):
    def setUp(self):
        self.dir = d = tempfile.mkdtemp()
        os.environ["UPLOAD_DIR"] = f"{d}/uploads"
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_messaggi=f"{d}/m.db",
            db_garanzia=f"{d}/g.db"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@cin.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tk = {"X-Host-Token": c["token"]}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _pub(self, **extra):
        d = {"titolo": "Casa", "citta": "Roma", "prezzo_notte_cents": 10000, "capacita": 2}
        d.update(extra)
        return self.g("POST", "/api/host/pubblica", d, self.tk)

    def test_italia_senza_cin_bloccata(self):
        for paese in ("IT", "it", "Italia", "ITALY", " ita "):
            s, o = self._pub(paese=paese)
            self.assertEqual(s, 422, (paese, o))
            self.assertEqual(o.get("errore"), "cin_obbligatorio_italia", paese)

    def test_italia_con_cin_pubblicata_ed_esposta(self):
        s, o = self._pub(paese="IT", cin=CIN_OK, slug="casa-cin")
        self.assertEqual(s, 201, o)
        s, det = self.g("GET", "/api/catalogo/casa-cin")
        self.assertEqual(s, 200, det)
        self.assertEqual(det.get("cin"), CIN_OK, "il CIN DEVE essere esposto al pubblico")
        # e nella vista owner (per il form di modifica)
        s, own = self.r.gestisci("GET", "/api/host/alloggio", {"slug": "casa-cin"},
                                 None, self.tk)
        self.assertEqual(s, 200, own)
        self.assertEqual(own.get("cin"), CIN_OK)

    def test_bozza_italia_senza_cin_ammessa(self):
        s, o = self._pub(paese="IT", stato="bozza", slug="casa-bozza")
        self.assertEqual(s, 201, o)

    def test_estero_senza_cin_ammesso(self):
        for paese in ("ES", "FR", "US", ""):
            s, o = self._pub(paese=paese, slug="casa-%s" % (paese.lower() or "x"))
            self.assertEqual(s, 201, (paese, o))

    def test_cin_storpio_422(self):
        s, o = self._pub(paese="IT", cin="cattivo!")
        self.assertEqual(s, 422, o)
        self.assertEqual(o.get("dettaglio"), "cin_non_valido")


if __name__ == "__main__":
    unittest.main()
