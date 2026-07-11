"""Contratto host + registro d'accettazione FIRMATO (prova legale a prova di manomissione).
Copre: unita' del registro (firma/tamper/versione), il documento (hash stabile, lingue) e
l'integrazione via HTTP (serve contratto, registrazione salva la prova, endpoint accettazioni)."""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from fase163_accettazioni import (
    CONTRATTO_HOST, CONTRATTO_HOST_VERSIONE, RegistroAccettazioni,
    crea_registro_accettazioni, doc_sha256, documento_corrente)
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

SEG = b"z" * 32


class TestRegistroUnita(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.reg = crea_registro_accettazioni(f"{self.dir}/acc.db", SEG)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_registra_ed_elenco(self):
        r = self.reg.registra("h_1", ip="1.2.3.4", user_agent="UA", vessatorie=True)
        self.assertTrue(r["ok"])
        el = self.reg.elenco("h_1")
        self.assertEqual(len(el), 1)
        self.assertTrue(el[0]["integra"])            # firma valida
        self.assertTrue(el[0]["vessatorie"])
        self.assertEqual(el[0]["ip"], "1.2.3.4")
        self.assertEqual(el[0]["versione"], CONTRATTO_HOST_VERSIONE)
        self.assertEqual(el[0]["doc_sha256"], doc_sha256())

    def test_host_id_mancante(self):
        self.assertFalse(self.reg.registra("")["ok"])
        self.assertEqual(self.reg.elenco(""), [])

    def test_append_only_nessun_metodo_di_modifica(self):
        # il registro NON espone update/delete: e' append-only per costruzione (prova legale)
        for vietato in ("aggiorna", "modifica", "cancella", "elimina", "update", "delete"):
            self.assertFalse(hasattr(self.reg, vietato), vietato)

    def test_tamper_riga_alterata_e_rilevato(self):
        self.reg.registra("h_x", ip="9.9.9.9", vessatorie=True)
        # un attaccante altera il DB: cambia vessatorie 1->0 per negare l'approvazione
        con = sqlite3.connect(f"{self.dir}/acc.db")
        with con:
            con.execute("UPDATE accettazioni SET vessatorie=0 WHERE host_id='h_x'")
        con.close()
        el = self.reg.elenco("h_x")
        self.assertEqual(len(el), 1)
        self.assertFalse(el[0]["integra"])           # MANOMISSIONE rilevata (firma non torna)

    def test_tamper_ip_alterato_e_rilevato(self):
        self.reg.registra("h_y", ip="1.1.1.1")
        con = sqlite3.connect(f"{self.dir}/acc.db")
        with con:
            con.execute("UPDATE accettazioni SET ip='6.6.6.6' WHERE host_id='h_y'")
        con.close()
        self.assertFalse(self.reg.elenco("h_y")[0]["integra"])

    def test_segreto_diverso_non_convalida(self):
        self.reg.registra("h_z")
        altro = RegistroAccettazioni(f"{self.dir}/acc.db", b"a" * 32)
        self.assertFalse(altro.elenco("h_z")[0]["integra"])   # firma con altro segreto -> KO

    def test_ha_accettato_corrente(self):
        self.assertFalse(self.reg.ha_accettato_corrente("h_v"))
        self.reg.registra("h_v", vessatorie=True)
        self.assertTrue(self.reg.ha_accettato_corrente("h_v"))

    def test_versione_vecchia_non_conta_come_corrente(self):
        self.reg.registra("h_old", versione="1.0")
        self.assertFalse(self.reg.ha_accettato_corrente("h_old"))
        self.assertEqual(self.reg.elenco("h_old")[0]["versione"], "1.0")

    def test_piu_accettazioni_ordinate(self):
        self.reg.registra("h_m", lang="it")
        self.reg.registra("h_m", lang="en")
        el = self.reg.elenco("h_m")
        self.assertEqual([x["lang"] for x in el], ["it", "en"])
        self.assertEqual(self.reg.conta(), 2)


class TestDocumento(unittest.TestCase):
    def test_hash_stabile_e_indipendente_dalla_lingua(self):
        self.assertEqual(doc_sha256(), doc_sha256())
        self.assertEqual(len(doc_sha256()), 64)
        self.assertEqual(documento_corrente("it")["doc_sha256"],
                         documento_corrente("en")["doc_sha256"])   # stesso doc vincolante

    def test_lingue_e_fallback(self):
        self.assertEqual(documento_corrente("en")["lang"], "en")
        self.assertEqual(documento_corrente("zz")["lang"], "it")   # ignota -> fa fede l'italiano
        self.assertIn("MANLEVA", documento_corrente("it")["testo"])
        self.assertIn("INDEMNIFICATION", documento_corrente("en")["testo"])

    def test_testo_contiene_le_tutele_chiave(self):
        it = CONTRATTO_HOST["it"]
        for atteso in ("CIN", "tassa/imposta di soggiorno", "DISINTERMEDIAZIONE",
                       "MANLEVA", "LIMITAZIONE DI RESPONSABILITA'", "1341-1342"):
            self.assertIn(atteso, it, atteso)


class TestIntegrazioneHTTP(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db",
            db_messaggi=f"{d}/m.db", db_accettazioni=f"{d}/acc.db",
            file_referral=f"{d}/ref.json", con_registrazione_host=True))
        self.r = crea_router(self.sis, host_key="hk")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _reg(self, body, headers=None):
        return self.r.gestisci("POST", "/api/host/registrazione", {},
                               json.dumps(body), headers or {})

    def test_serve_contratto(self):
        s, d = self.r.gestisci("GET", "/api/legale/contratto-host", {"lang": "en"}, None, {})
        self.assertEqual(s, 200)
        self.assertEqual(d["documento"], "contratto_host")
        self.assertEqual(d["doc_sha256"], doc_sha256())
        self.assertIn("HOST AGREEMENT", d["testo"])

    def test_registrazione_salva_prova_firmata(self):
        s, d = self._reg(
            {"email": "a@b.com", "password": "password1", "accetta_termini": True,
             "accetta_clausole": True, "lang": "it"},
            {"X-Forwarded-For": "203.0.113.9, 10.0.0.1", "User-Agent": "Firefox"})
        self.assertEqual(s, 201)
        self.assertTrue(d["accettazione"]["registrata"])
        self.assertTrue(d["accettazione"]["vessatorie"])
        # la prova e' recuperabile e INTEGRA, con IP (primo hop) e UA catturati
        tok = d["token"]
        s2, d2 = self.r.gestisci("GET", "/api/host/accettazioni", {}, None,
                                 {"X-Host-Token": tok})
        self.assertEqual(s2, 200)
        self.assertEqual(len(d2["accettazioni"]), 1)
        acc = d2["accettazioni"][0]
        self.assertTrue(acc["integra"])
        self.assertTrue(acc["vessatorie"])
        self.assertEqual(acc["ip"], "203.0.113.9")
        self.assertEqual(acc["user_agent"], "Firefox")

    def test_registrazione_senza_clausole_registra_vessatorie_false(self):
        s, d = self._reg({"email": "c@d.com", "password": "password1",
                          "accetta_termini": True, "accetta_clausole": False})
        self.assertEqual(s, 201)
        self.assertFalse(d["accettazione"]["vessatorie"])

    def test_senza_accetta_termini_niente_account_ne_prova(self):
        s, d = self._reg({"email": "e@f.com", "password": "password1",
                          "accetta_termini": False})
        self.assertEqual(s, 422)
        self.assertNotIn("accettazione", d)

    def test_anti_manomissione_hash_sbagliato_409(self):
        s, d = self._reg({"email": "g@h.com", "password": "password1",
                          "accetta_termini": True, "accetta_clausole": True,
                          "doc_sha256": "deadbeef"})
        self.assertEqual(s, 409)
        self.assertEqual(d["errore"], "contratto_aggiornato")
        self.assertEqual(d["doc_sha256"], doc_sha256())

    def test_hash_corretto_passa(self):
        s, _ = self._reg({"email": "i@j.com", "password": "password1",
                          "accetta_termini": True, "accetta_clausole": True,
                          "doc_sha256": doc_sha256()})
        self.assertEqual(s, 201)

    def test_accettazioni_richiede_auth(self):
        s, _ = self.r.gestisci("GET", "/api/host/accettazioni", {}, None, {})
        self.assertEqual(s, 401)


if __name__ == "__main__":
    unittest.main()
