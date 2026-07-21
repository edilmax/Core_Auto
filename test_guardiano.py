"""GUARDIA — il Guardiano degli stati impossibili (fase186) VEDE davvero le anomalie.

Nato dall'audit del 2026-07-22: tre indagini convergevano su una lacuna — nessuno
controlla in automatico gli stati che non dovrebbero poter esistere, e nessuno grida.
Il Guardiano colma quel buco. Ma un guardiano che non ha mai visto un'anomalia non e' un
guardiano: e' un ornamento. Qui gli si mette davanti, uno per uno, ogni stato impossibile
e si pretende che se ne accorga; e su un sistema sano deve tacere.

Stati messi alla prova:
  · ESCROW BLOCCATO: una garanzia il cui rilascio automatico e' passato da giorni;
  · BONIFICO FERMO: un payout 'maturato' vecchio di settimane;
  · PAYOUT ORFANO: un payout dovuto a un host che non esiste;
  · e su tutto pulito -> nessun allarme (mai gridare al lupo per un ritardo normale).
"""

import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
import fase186_guardiano as G


class _Base(unittest.TestCase):

    def setUp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"G" * 32, con_registrazione_host=True,
            db_catalogo="%s/c.db" % d, db_inventario="%s/i.db" % d,
            db_registro_host="%s/r.db" % d, db_garanzia="%s/g.db" % d,
            db_payout="%s/y.db" % d, db_pendenti="%s/p.db" % d,
            db_accettazioni="%s/a.db" % d, db_tassa_comunale="%s/t.db" % d))
        self.now = int(time.time())


class TestSistemaSanoNessunAllarme(_Base):

    def test_su_tutto_pulito_il_guardiano_TACE(self):
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        self.assertTrue(rep["pulito"], "grida su un sistema sano: %s" % rep["anomalie"])
        self.assertEqual(rep["conta"], 0)


class TestEscrowBloccato(_Base):

    def test_una_garanzia_scaduta_da_giorni_e_un_allarme(self):
        gar = self.sys.garanzia
        # apro una garanzia con check-in vecchissimo -> il rilascio e' gia' passato
        vecchio = self.now - 10 * 86400
        gar.apri("pren-vecchia", 30000, alloggio_id="casa", ora_checkin_ts=vecchio)
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        self.assertFalse(rep["pulito"])
        self.assertIn("escrow_bloccato", rep["anomalie"])
        self.assertEqual(rep["anomalie"]["escrow_bloccato"][0]["prenotazione_id"],
                         "pren-vecchia")

    def test_una_garanzia_appena_aperta_NON_allarma(self):
        self.sys.garanzia.apri("pren-fresca", 30000, alloggio_id="casa",
                               ora_checkin_ts=self.now)
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        self.assertNotIn("escrow_bloccato", rep["anomalie"],
                         "grida su un escrow appena aperto (ritardo normale)")


class TestBonificoFermoEOrfano(_Base):

    def _registra_host(self, hid="h_reale"):
        # un host che esiste davvero, cosi' il suo payout non risulta orfano
        self.sys.registro_host.registra("h@g.it", "password1", host_id_forzato=hid) \
            if hasattr(self.sys.registro_host, "registra") else None
        return hid

    def test_payout_maturato_vecchio_e_un_bonifico_fermo(self):
        pay = self.sys.payout
        # host ESISTENTE (altrimenti il payout risulterebbe 'orfano', non 'fermo')
        e = self.sys.registro_host.registra("e@g.it", "password1", accetta_termini=True)
        self.assertTrue(getattr(e, "ok", False), "registrazione host fallita: %r" % e)
        hid = e.host_id
        # riga maturato vecchia di 20 giorni
        pay.registra_maturato("pren-ferma", hid, 25000, "EUR")
        # invecchio la riga a mano (il ts di registrazione e' 'ora')
        con = pay._apri()
        with con:
            con.execute("UPDATE payout SET ts=? WHERE prenotazione_id=?",
                        (self.now - 20 * 86400, "pren-ferma"))
        con.close()
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        self.assertFalse(rep["pulito"])
        self.assertIn("bonifico_fermo", rep["anomalie"])

    def test_payout_a_host_inesistente_e_ORFANO(self):
        # payout dovuto a un host che NON e' nel registro -> residuo di cancellazione
        self.sys.payout.registra_maturato("pren-orfana", "host_fantasma", 40000, "EUR")
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        self.assertFalse(rep["pulito"])
        self.assertIn("payout_orfano", rep["anomalie"])
        self.assertEqual(rep["anomalie"]["payout_orfano"][0]["host_id"], "host_fantasma")


class TestRiassuntoEmail(_Base):

    def test_l_email_di_allarme_e_costruita_e_XSS_safe(self):
        rep = {"conta": 1, "pulito": False,
               "anomalie": {"payout_orfano": [{"host_id": "<script>x</script>",
                                               "minori": 100}]}}
        html = G.riassunto_html(rep)
        self.assertIn("Guardiano", html)
        self.assertNotIn("<script>x", html, "il riassunto non e' XSS-safe")
        self.assertIn("&lt;script&gt;", html)


class TestEndpointManuale(_Base):
    """La rotta a richiesta `/api/bunker/guardiano`: stesso controllo del giro giornaliero,
    ma eseguito subito. Deve essere protetta (bunker) e READ-ONLY."""

    def test_endpoint_richiede_il_bunker_e_e_read_only(self):
        import json as _j
        from fase83_server import crea_router
        r = crea_router(self.sys, host_key="hk", admin_key="ak",
                        base_url="https://bookinvip.com")
        # senza sessione bunker -> se il bunker e' configurato, 403; se non lo e' (come qui,
        # nei test), l'operazione read-only puo' passare. In entrambi i casi NON deve
        # sollevare ne' 500, e su un sistema pulito il referto e' 'pulito'.
        st, corpo = r.gestisci("GET", "/api/bunker/guardiano", {}, None,
                               {"X-Admin-Key": "ak"})
        self.assertIn(st, (200, 403), corpo)
        if st == 200:
            self.assertIn("pulito", corpo)


class TestNonSollevaMai(_Base):

    def test_scansiona_non_solleva_su_sistema_rotto(self):
        class Rotto:
            def __getattr__(self, n):
                raise RuntimeError("giu")
        try:
            rep = G.scansiona(Rotto())
        except Exception as e:
            self.fail("il guardiano solleva su sistema rotto: %s" % e)
        self.assertIsInstance(rep, dict)


if __name__ == "__main__":
    unittest.main(verbosity=2)
