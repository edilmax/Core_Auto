"""LEGAME IDENTITÀ VERIFICATA ↔ FIRMA DEL CONTRATTO (2026-07-21).

Perche' esiste: prima la prova diceva *"qualcuno, da questo IP, alle 18:12 UTC, ha accettato
la versione X"*. NON diceva CHI. In causa la difesa piu' facile era "non ero io, qualcuno ha
usato il mio computer". Ora, se l'host ha fatto la verifica documentale con Stripe Identity
(documento + selfie, custoditi da Stripe, MAI da noi), il registro scrive una riga firmata
`identita_stripe` che lega la SESSIONE di verifica (`vs_...`) al TESTO ESATTO del contratto.

Guardie di questo compartimento:
  - LEGAME: riga scritta alla firma se la verifica c'e' gia'; scritta DOPO se l'host si
    verifica in seguito (nessuno resta senza prova completa).
  - VERIFICABILE: l'impronta del legame si RICALCOLA dai due dati (sessione + contratto):
    non e' un'asserzione nostra, chiunque puo' rifarla.
  - FIRMATO: la riga porta il riferimento DENTRO la firma HMAC -> cambiarlo la invalida.
  - RETROCOMPATIBILITA': le prove SENZA riferimento (tutte quelle gia' archiviate) restano
    integre — la stringa firmata cambia solo quando il riferimento c'e'.
  - IDEMPOTENZA: ri-login / retry del webhook non creano doppioni.
  - NIENTE INVENZIONI: host non verificato -> nessuna riga, nessun legame dichiarato.
  - VISIBILITA': la riga compare in /api/bunker/prove_legali e nel dossier legale.
"""
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import (CONTRATTO_HOST_VERSIONE, DOCUMENTO_HOST, DOCUMENTO_IDENTITA,
                                  crea_registro_accettazioni, doc_sha256, impronta_identita)

PW = "SuperPw@1"
AK = {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9", "User-Agent": "Firefox"}
VS = "vs_test_1234567890"


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://x/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


class TestRegistroLegame(unittest.TestCase):
    """Il motore del legame, senza server: firma, verificabilita', idempotenza."""

    def setUp(self):
        self.dir = d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        self.db = f"{d}/acc.db"
        self.reg = crea_registro_accettazioni(self.db, b"S" * 32)

    def test_legame_scritto_firmato_e_verificabile(self):
        self.reg.registra("h1", ip="203.0.113.9", user_agent="UA", vessatorie=True)
        out = self.reg.lega_identita("h1", VS, "verificato", ip="203.0.113.9", user_agent="UA")
        self.assertTrue(out["ok"], out)
        riga = [r for r in self.reg.elenco("h1")
                if r["documento"] == DOCUMENTO_IDENTITA][0]
        self.assertEqual(riga["riferimento"], VS)
        self.assertEqual(riga["versione"], CONTRATTO_HOST_VERSIONE)
        self.assertTrue(riga["integra"], "la riga del legame non e' firmata correttamente")
        # l'impronta LEGA sessione + testo del contratto, ed e' ricalcolabile da chiunque
        self.assertEqual(riga["doc_sha256"], impronta_identita(VS, doc_sha256()))
        self.assertNotEqual(riga["doc_sha256"], impronta_identita("vs_altro", doc_sha256()))

    def test_manomettere_il_riferimento_invalida_la_firma(self):
        """Il riferimento e' DENTRO la firma: cambiarlo nel DB si vede."""
        self.reg.lega_identita("h1", VS, "verificato")
        con = sqlite3.connect(self.db)
        try:
            con.execute("UPDATE accettazioni SET riferimento='vs_falso' WHERE documento=?",
                        (DOCUMENTO_IDENTITA,))
            con.commit()
        finally:
            con.close()
        riga = [r for r in self.reg.elenco("h1") if r["documento"] == DOCUMENTO_IDENTITA][0]
        self.assertFalse(riga["integra"], "riferimento alterato NON rilevato")

    def test_prove_senza_riferimento_restano_integre(self):
        """RETROCOMPATIBILITA': le prove gia' archiviate (senza riferimento) non devono
        risultare manomesse dopo l'aggiunta del campo alla firma."""
        r = self.reg.registra("h_vecchio", ip="9.9.9.9", user_agent="UA", vessatorie=True)
        self.assertTrue(r["ok"])
        righe = self.reg.elenco("h_vecchio")
        self.assertEqual(len(righe), 1)
        self.assertTrue(righe[0]["integra"], "una prova senza riferimento risulta manomessa!")
        self.assertEqual(righe[0]["riferimento"], "")

    def test_idempotenza(self):
        for _ in range(5):
            self.reg.lega_identita("h1", VS, "verificato")
        righe = [r for r in self.reg.elenco("h1") if r["documento"] == DOCUMENTO_IDENTITA]
        self.assertEqual(len(righe), 1, "legame duplicato a ogni chiamata")

    def test_sessione_diversa_scrive_un_nuovo_legame(self):
        """Se l'host rifa' la verifica con una sessione nuova, si registra anche quella
        (append-only: lo storico resta)."""
        self.reg.lega_identita("h1", VS, "verificato")
        self.reg.lega_identita("h1", "vs_secondo", "verificato")
        righe = [r for r in self.reg.elenco("h1") if r["documento"] == DOCUMENTO_IDENTITA]
        self.assertEqual(len(righe), 2)

    def test_niente_sessione_niente_legame(self):
        for cattivo in ("", None, "   "):
            out = self.reg.lega_identita("h1", cattivo, "verificato")
            self.assertFalse(out["ok"], "legame scritto senza sessione: %r" % (cattivo,))
        self.assertEqual([r for r in self.reg.elenco("h1")
                          if r["documento"] == DOCUMENTO_IDENTITA], [])

    def test_identita_legata_dichiara_il_vero(self):
        st = self.reg.identita_legata("h1")
        self.assertFalse(st["legata"])
        self.reg.lega_identita("h1", VS, "verificato")
        st = self.reg.identita_legata("h1")
        self.assertTrue(st["legata"] and st["verificabile"] and st["integra"])
        self.assertEqual(st["session_ref"], VS)


class TestFlussoServer(unittest.TestCase):
    """Il legame nel flusso reale: alla firma e quando la verifica arriva DOPO."""

    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        self.dir = d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        os.environ["UPLOAD_DIR"] = f"{d}/uploads"
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_kyc=f"{d}/k.db",
            db_finanza=f"{d}/f.db", bunker_password=PW,
            commissione_bps=1000, psp_bps=300, promo_lancio_attiva=True))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {},
                               json.dumps(b) if b is not None else None, h or AK)

    def bunker(self):
        s, o = self.g("POST", "/api/bunker/login", {"codice": PW})
        self.assertEqual(s, 200, o)
        d = dict(AK)
        d["X-Bunker-Session"] = o["sessione"]
        return d

    def registra_host(self, email="h@id.local"):
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": email, "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        return c["host_id"], c

    def test_senza_verifica_nessun_legame_dichiarato(self):
        """Host che non si e' verificato: niente riga identita', niente promesse."""
        hid, c = self.registra_host()
        self.assertFalse(c["accettazione"]["identita_legata"])
        prove = self.sis.accettazioni.elenco(hid)
        self.assertEqual([p for p in prove if p["documento"] == DOCUMENTO_IDENTITA], [])
        self.assertFalse(self.sis.accettazioni.identita_legata(hid)["legata"])

    def test_verifica_gia_fatta_legame_scritto_alla_firma(self):
        # simulo un host che si e' verificato PRIMA di firmare (sessione gia' nel registro KYC)
        self.sis.kyc.registra_avvio("h_pre", VS)
        self.sis.kyc.conferma("h_pre", "verificato")
        acc = self.sis.accettazioni
        ok = self.r._lega_identita_se_possibile(acc, "h_pre", ip="203.0.113.9", ua="Firefox")
        self.assertTrue(ok)
        st = acc.identita_legata("h_pre")
        self.assertTrue(st["legata"] and st["verificabile"])
        self.assertEqual(st["session_ref"], VS)

    def test_verifica_completata_DOPO_la_firma(self):
        """Il caso più comune: prima firma, poi si verifica. La prova si completa lo stesso."""
        hid, c = self.registra_host()
        self.assertFalse(c["accettazione"]["identita_legata"])
        self.sis.kyc.registra_avvio(hid, VS)
        self.sis.kyc.conferma(hid, "verificato")
        self.assertTrue(self.r._lega_identita_se_possibile(self.sis.accettazioni, hid))
        st = self.sis.accettazioni.identita_legata(hid)
        self.assertTrue(st["legata"] and st["integra"] and st["verificabile"])

    def test_legame_visibile_nel_bunker(self):
        hid, _c = self.registra_host()
        self.sis.kyc.registra_avvio(hid, VS)
        self.sis.kyc.conferma(hid, "verificato")
        self.r._lega_identita_se_possibile(self.sis.accettazioni, hid)
        s, d = self.g("GET", "/api/bunker/prove_legali", None, self.bunker())
        self.assertEqual(s, 200, d)
        riga = [p for p in d["prove"] if p["documento"] == DOCUMENTO_IDENTITA]
        self.assertEqual(len(riga), 1, "il legame identità non compare nel Bunker")
        self.assertEqual(riga[0]["riferimento"], VS)
        self.assertTrue(riga[0]["integra"])
        self.assertEqual(len(riga[0]["firma_hmac_sha256"]), 64)
        self.assertTrue(d["integrita_ok"])

    def test_legame_nel_dossier_legale(self):
        hid, _c = self.registra_host()
        self.sis.kyc.registra_avvio(hid, VS)
        self.sis.kyc.conferma(hid, "verificato")
        self.r._lega_identita_se_possibile(self.sis.accettazioni, hid)
        bk = self.bunker()
        s, d = self.g("GET", "/api/bunker/export_legale", None, bk, {"formato": "json"})
        self.assertEqual(s, 200, d)
        dati = json.loads(d["contenuto"].split("\n# FINE DOSSIER")[0])
        h = dati["host"][0]
        self.assertEqual(h["identita_verificata"], "SI")
        self.assertEqual(h["identita_sessione_stripe"], VS)
        self.assertEqual(h["identita_legame_verificabile"], "SI")
        self.assertEqual(h["identita_stato_kyc"], "verificato")
        self.assertTrue(h["identita_legata_utc"].endswith("UTC"))
        # e nel CSV
        s, d = self.g("GET", "/api/bunker/export_legale", None, bk, {"formato": "csv"})
        self.assertIn("identita_sessione_stripe", d["contenuto"])
        self.assertIn(VS, d["contenuto"])
        self.assertTrue(d["certificato"])

    def test_dossier_dichiara_NO_se_non_verificato(self):
        self.registra_host()
        s, d = self.g("GET", "/api/bunker/export_legale", None, self.bunker(),
                      {"formato": "json"})
        dati = json.loads(d["contenuto"].split("\n# FINE DOSSIER")[0])
        h = dati["host"][0]
        self.assertEqual(h["identita_verificata"], "NO")
        self.assertEqual(h["identita_sessione_stripe"], "")

    def test_contratto_e_privacy_restano_integri(self):
        """Il legame non deve toccare le altre due prove."""
        hid, _c = self.registra_host()
        self.sis.kyc.registra_avvio(hid, VS)
        self.sis.kyc.conferma(hid, "verificato")
        self.r._lega_identita_se_possibile(self.sis.accettazioni, hid)
        prove = self.sis.accettazioni.elenco(hid)
        self.assertEqual(len(prove), 3)                     # contratto + privacy + identita
        self.assertTrue(all(p["integra"] for p in prove))
        c = [p for p in prove if p["documento"] == DOCUMENTO_HOST][0]
        self.assertEqual(c["riferimento"], "")              # invariato
        self.assertTrue(c["vessatorie"])


if __name__ == "__main__":
    unittest.main()
