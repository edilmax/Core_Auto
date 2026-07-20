"""CONSENSI BLINDATI — 3 spunte obbligatorie + prova firmata + ri-accettazione (2026-07-20).

Cosa era rotto (provato prima del fix):
  - una sola casella copriva Contratto E Privacy (GDPR vuole consensi SPECIFICI e distinti);
  - le clausole vessatorie (artt. 1341-1342 c.c.) erano controllate SOLO dal browser: una
    registrazione via API con `accetta_clausole:false` creava l'account con vessatorie=0 →
    trattenute (art.6), penali (7-8), manleva (9), foro (14) NON opponibili a quell'host;
  - alzare la versione del contratto non obbligava nessuno a ri-accettare (art. 13 disatteso).

Guardie di questo compartimento:
  - SERVER (la difesa vera): manca UNA spunta qualsiasi → 422 `consensi_mancanti` e
    NESSUN account creato (rifiuto a monte).
  - PROVA: due righe firmate HMAC-SHA256 (contratto CON vessatorie + privacy come documento
    SEPARATO), ognuna con versione, impronta del testo, IP, dispositivo, data/ora.
  - RETROCOMPATIBILITA': la stringa firmata NON e' cambiata → le prove gia' archiviate
    restano `integra` (nessun falso allarme di manomissione).
  - RI-ACCETTAZIONE: se la versione corrente non e' accettata → `deve_riaccettare` true;
    l'endpoint pretende di nuovo le 3 spunte e scrive prove nuove (le vecchie restano).
  - INTERFACCIA: 3 caselle distinte e tasto DISABILITATO finche' non sono tutte spuntate.
"""
import json
import os
import re
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import (CONTRATTO_HOST_VERSIONE, DOCUMENTO_HOST, DOCUMENTO_PRIVACY,
                                  PRIVACY_VERSIONE, crea_registro_accettazioni, doc_sha256,
                                  privacy_sha256)

BASE = os.path.dirname(os.path.abspath(__file__))
HDR = {"X-Forwarded-For": "203.0.113.9", "User-Agent": "Firefox/prova"}


class BaseConsensi(unittest.TestCase):
    def setUp(self):
        self.dir = d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db"))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")

    def _reg(self, extra=None, headers=None):
        body = {"email": "h@cons.local", "password": "password1",
                "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True}
        body.update(extra or {})
        return self.r.gestisci("POST", "/api/host/registrazione", {}, json.dumps(body),
                               headers if headers is not None else HDR)


class TestServerRifiutaAMonte(BaseConsensi):
    def test_manca_una_spunta_qualsiasi_422_e_nessun_account(self):
        for chiave in ("accetta_termini", "accetta_clausole", "accetta_privacy"):
            with self.subTest(chiave=chiave):
                s, d = self._reg({chiave: False, "email": "no_%s@cons.local" % chiave})
                self.assertEqual(s, 422, d)
                self.assertEqual(d.get("errore"), "consensi_mancanti")
                self.assertIn(chiave, d.get("mancanti", []))
                self.assertNotIn("token", d)          # nessun account creato
                self.assertNotIn("accettazione", d)

    def test_spunta_assente_del_tutto_equivale_a_rifiuto(self):
        """Chi chiama l'API senza il campo (non solo con false) viene comunque respinto."""
        body = {"email": "muto@cons.local", "password": "password1",
                "accetta_termini": True, "accetta_clausole": True}      # privacy assente
        s, d = self.r.gestisci("POST", "/api/host/registrazione", {}, json.dumps(body), HDR)
        self.assertEqual(s, 422, d)
        self.assertIn("accetta_privacy", d.get("mancanti", []))

    def test_con_tutte_e_tre_l_account_nasce(self):
        s, d = self._reg()
        self.assertEqual(s, 201, d)
        self.assertTrue(d.get("accettazione", {}).get("registrata"))
        self.assertTrue(d["accettazione"]["vessatorie"])
        self.assertTrue(d["accettazione"]["privacy_registrata"])


class TestProvaFirmata(BaseConsensi):
    def test_due_prove_distinte_complete_e_integre(self):
        s, d = self._reg()
        self.assertEqual(s, 201, d)
        hid = d["host_id"]
        righe = self.sis.accettazioni.elenco(hid)
        self.assertEqual(len(righe), 2, "attese 2 prove: contratto + privacy")
        per_doc = {r["documento"]: r for r in righe}
        self.assertIn(DOCUMENTO_HOST, per_doc)
        self.assertIn(DOCUMENTO_PRIVACY, per_doc, "consenso privacy NON registrato a parte")
        c = per_doc[DOCUMENTO_HOST]
        self.assertTrue(c["integra"])                       # firma HMAC valida
        self.assertTrue(c["vessatorie"])                    # artt. 1341-1342 approvate
        self.assertEqual(c["versione"], CONTRATTO_HOST_VERSIONE)
        self.assertEqual(c["doc_sha256"], doc_sha256())     # impronta del testo esatto
        self.assertEqual(c["ip"], "203.0.113.9")            # IP reale (dietro nginx)
        self.assertEqual(c["user_agent"], "Firefox/prova")  # dispositivo
        self.assertGreater(c["accettato_ts"], 0)            # data e ora
        p = per_doc[DOCUMENTO_PRIVACY]
        self.assertTrue(p["integra"])
        self.assertEqual(p["versione"], PRIVACY_VERSIONE)
        self.assertEqual(p["doc_sha256"], privacy_sha256())
        self.assertEqual(p["ip"], "203.0.113.9")

    def test_manomissione_riga_smascherata(self):
        """Se qualcuno cambia una riga nel DB, la firma non torna: integra=False."""
        s, d = self._reg()
        hid = d["host_id"]
        import sqlite3
        con = sqlite3.connect(f"{self.dir}/a.db")
        try:
            con.execute("UPDATE accettazioni SET ip='1.2.3.4' WHERE host_id=? AND documento=?",
                        (hid, DOCUMENTO_HOST))
            con.commit()
        finally:
            con.close()
        c = [r for r in self.sis.accettazioni.elenco(hid)
             if r["documento"] == DOCUMENTO_HOST][0]
        self.assertFalse(c["integra"], "manomissione NON rilevata dalla firma")

    def test_prove_vecchie_restano_integre(self):
        """La stringa firmata non e' cambiata: una prova scritta 'alla vecchia maniera'
        (solo contratto, nessuna privacy) resta valida -> niente falsi allarmi sulle
        prove gia' in archivio."""
        reg = crea_registro_accettazioni(f"{self.dir}/vecchio.db", b"S" * 32)
        r = reg.registra("h_vecchio", ip="9.9.9.9", user_agent="UA", vessatorie=True)
        self.assertTrue(r["ok"])
        righe = reg.elenco("h_vecchio")
        self.assertEqual(len(righe), 1)
        self.assertTrue(righe[0]["integra"])


class TestRiaccettazione(BaseConsensi):
    def _host(self):
        s, d = self._reg()
        self.assertEqual(s, 201, d)
        return d["host_id"], {"X-Host-Token": d["token"], **HDR}

    def test_appena_registrato_non_deve_riaccettare(self):
        _hid, tk = self._host()
        s, st = self.r.gestisci("GET", "/api/host/contratto_stato", {}, None, tk)
        self.assertEqual(s, 200, st)
        self.assertFalse(st["deve_riaccettare"])
        self.assertTrue(st["contratto_corrente"] and st["clausole_vessatorie"]
                        and st["privacy_corrente"])

    def test_versione_vecchia_obbliga_a_riaccettare(self):
        hid, tk = self._host()
        import sqlite3
        con = sqlite3.connect(f"{self.dir}/a.db")      # simulo prove della versione passata
        try:
            con.execute("DELETE FROM accettazioni WHERE host_id=?", (hid,))
            con.commit()
        finally:
            con.close()
        self.sis.accettazioni.registra(hid, versione="2026-01-01", ip="1.1.1.1",
                                       user_agent="UA", vessatorie=True)
        s, st = self.r.gestisci("GET", "/api/host/contratto_stato", {}, None, tk)
        self.assertTrue(st["deve_riaccettare"], "contratto vecchio: doveva chiedere di ri-accettare")
        self.assertEqual(st["versione_accettata"], "2026-01-01")
        self.assertEqual(st["versione_corrente"], CONTRATTO_HOST_VERSIONE)
        # ri-accetto: servono di nuovo TUTTE E TRE le spunte
        s, o = self.r.gestisci("POST", "/api/host/riaccetta", {},
                               json.dumps({"accetta_termini": True, "accetta_clausole": True}), tk)
        self.assertEqual(s, 422, o)
        self.assertIn("accetta_privacy", o.get("mancanti", []))
        s, o = self.r.gestisci("POST", "/api/host/riaccetta", {},
                               json.dumps({"accetta_termini": True, "accetta_clausole": True,
                                           "accetta_privacy": True, "doc_sha256": doc_sha256()}), tk)
        self.assertEqual(s, 200, o)
        self.assertTrue(o["ok"])
        s, st2 = self.r.gestisci("GET", "/api/host/contratto_stato", {}, None, tk)
        self.assertFalse(st2["deve_riaccettare"], "dopo la ri-accettazione doveva essere in regola")
        # la prova VECCHIA resta in archivio (append-only: si prova cosa valeva quando)
        versioni = [r["versione"] for r in self.sis.accettazioni.elenco(hid, DOCUMENTO_HOST)]
        self.assertIn("2026-01-01", versioni)
        self.assertIn(CONTRATTO_HOST_VERSIONE, versioni)

    def test_riaccetta_senza_login_401(self):
        s, o = self.r.gestisci("POST", "/api/host/riaccetta", {},
                               json.dumps({"accetta_termini": True, "accetta_clausole": True,
                                           "accetta_privacy": True}), {})
        self.assertEqual(s, 401, o)

    def test_riaccetta_con_hash_vecchio_409(self):
        _hid, tk = self._host()
        s, o = self.r.gestisci("POST", "/api/host/riaccetta", {},
                               json.dumps({"accetta_termini": True, "accetta_clausole": True,
                                           "accetta_privacy": True, "doc_sha256": "deadbeef"}), tk)
        self.assertEqual(s, 409, o)
        self.assertEqual(o.get("errore"), "contratto_aggiornato")


class TestInterfaccia(unittest.TestCase):
    """Il browser deve mostrare 3 caselle e tenere il tasto GRIGIO finche' mancano."""

    def setUp(self):
        with open(os.path.join(BASE, "deploy", "host.html"), encoding="utf-8") as f:
            self.html = f.read()

    def test_tre_caselle_distinte(self):
        for cid in ("au_terms", "au_clausole", "au_privacy"):
            self.assertIn('id="%s"' % cid, self.html, "casella %s assente" % cid)
        # e le stesse tre nella schermata di ri-accettazione
        for cid in ("ra_terms", "ra_clausole", "ra_privacy"):
            self.assertIn('id="%s"' % cid, self.html, "casella %s assente (ri-accettazione)" % cid)
        self.assertIn("1341-1342", self.html)          # richiamo normativo esplicito
        self.assertIn("GDPR", self.html)

    def test_tasti_nascono_disabilitati_e_grigi(self):
        for bid in ("btnRegister", "btnRiaccetta"):
            m = re.search(r'id="%s"[^>]*>' % bid, self.html)
            self.assertIsNotNone(m, "tasto %s non trovato" % bid)
            self.assertIn("disabled", m.group(0), "%s non nasce disabilitato" % bid)
        # stile visibile del blocco (grigio + cursore "vietato")
        self.assertIn("button[disabled]", self.html)
        self.assertIn("not-allowed", self.html)

    def test_logica_abilitazione_e_avviso(self):
        self.assertIn("AU_CONSENSI = ['au_terms','au_clausole','au_privacy']", self.html)
        self.assertIn("RA_CONSENSI = ['ra_terms','ra_clausole','ra_privacy']", self.html)
        self.assertIn("aggiornaTastoRegistra", self.html)
        self.assertIn("aggiornaTastoRiaccetta", self.html)
        self.assertEqual(self.html.count('dev_consensi:"'), 2, "avviso mancante in it/en")
        # cintura+bretelle: anche forzando il tasto, l'invio si ferma
        self.assertIn("if(consensiMancanti().length)", self.html)
        # e il payload porta la terza spunta
        self.assertIn("accetta_privacy:true", self.html)


if __name__ == "__main__":
    unittest.main()
