"""GUARDIA — non si cancella un host che ha soldi o persone in ballo.

IL BUCO (audit del 2026-07-22, la lacuna piu' grave sull'integrita' fra i 21 archivi).
Il "tasto cancella tutto" di un host (`fase156_erasure.cancella_attivita_host`, il diritto
all'oblio) cancellava **sempre**, senza guardare se quell'host:
  · avesse una prenotazione ATTIVA (un ospite che ha pagato e sta per arrivare) →
    lasciato **senza stanza**;
  · avesse un PAYOUT DOVUTO (soldi che gli dobbiamo ancora bonificare) → **bonifico
    orfano**, verso un host che non esiste piu';
  · avesse un ESCROW APERTO (soldi di un ospite ancora in custodia) → **riga orfana**.

E la cancellazione di un ALLOGGIO da parte dell'host controllava solo le prenotazioni
FUTURE, non l'escrow ancora aperto su un soggiorno gia' passato (in attesa del rilascio,
o contestato).

Nessun soldo veniva perso subito, ma i nostri archivi restavano a raccontare cose
impossibili — un bonifico dovuto a nessuno, dei soldi in custodia per un alloggio che non
c'e'. Su un sistema di pagamenti, questi "stati impossibili" sono la radice dei disastri
che si scoprono mesi dopo.

COSA SI PRETENDE
  1. un host con prenotazione attiva / payout dovuto / escrow aperto / sospeso NON si
     cancella (409, con il motivo e i numeri);
  2. un host DAVVERO pulito si cancella (nessun blocco inventato);
  3. `forza=True` esiste per l'obbligo legale inderogabile, ma **registra** cosa c'era;
  4. un alloggio con escrow ancora aperto non si elimina, anche se il soggiorno e' passato.
"""

import json
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://t/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


class _Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"C" * 32, con_registrazione_host=True,
            db_catalogo="%s/c.db" % d, db_inventario="%s/i.db" % d,
            db_registro_host="%s/r.db" % d, db_accettazioni="%s/a.db" % d,
            db_pendenti="%s/p.db" % d, db_payout="%s/y.db" % d,
            db_garanzia="%s/g.db" % d, db_tassa_comunale="%s/t.db" % d,
            commissione_bps=1000, psp_bps=300, stripe_secret_key="sk"))
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        st, c = self.g("POST", "/api/host/registrazione",
                       {"email": "h@c.it", "password": "password1",
                        "accetta_termini": True, "accetta_clausole": True,
                        "accetta_privacy": True, "doc_sha256": doc_sha256(),
                        "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(st, 201, c)
        self.tok, self.hid = c["token"], c["host_id"]
        st, c = self.g("POST", "/api/host/pubblica",
                       {"slug": "casa", "titolo": "Casa", "citta": "Roma",
                        "prezzo_notte_cents": 20000, "valuta": "EUR", "capacita": 4,
                        "politica_cancellazione": "flessibile"},
                       {"X-Host-Token": self.tok})
        self.assertIn(st, (200, 201), c)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _apri_disponibilita(self, da, a):
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": da, "a": a, "unita_totali": 1,
                "prezzo_netto_cents": 20000}, {"X-Host-Token": self.tok})

    def _prenota_e_paga(self, ci, co):
        self._apri_disponibilita("2026-08-01", "2026-12-31")
        st, q = self.g("POST", "/api/concierge/quote",
                       {"alloggio_id": "casa", "check_in": ci, "check_out": co,
                        "party": 2})
        self.assertEqual(st, 200, q)
        st, b = self.g("POST", "/api/concierge/book",
                       {"quote_token": q["quote_token"], "email": "o@c.it"})
        self.assertIn(st, (200, 201), b)
        return b

    def _cancella_host(self, forza=False):
        corpo = {"host_id": self.hid}
        if forza:
            corpo["forza"] = True
        return self.g("POST", "/api/admin/cancella_attivita", corpo, {"X-Admin-Key": "ak"})


class TestObblighiPendenti(_Base):
    """La funzione pura, provata caso per caso."""

    def _obblighi(self):
        from fase156_erasure import obblighi_pendenti
        return obblighi_pendenti(self.sys, self.hid)

    def test_host_appena_registrato_e_pulito(self):
        o = self._obblighi()
        # nessun motivo di blocco (ignoriamo il campo diagnostico _incerti)
        veri = {k: v for k, v in o.items() if not k.startswith("_")}
        self.assertEqual(veri, {}, "un host senza attivita' risulta con obblighi: %s" % o)

    def test_prenotazione_futura_e_un_obbligo(self):
        self._prenota_e_paga("2026-09-05", "2026-09-08")
        self.assertIn("prenotazioni_attive", self._obblighi())

    def test_payout_dovuto_e_un_obbligo(self):
        """Dopo una prenotazione pagata l'host ha un payout 'maturato' = soldi in ballo."""
        self._prenota_e_paga("2026-09-05", "2026-09-08")
        o = self._obblighi()
        self.assertTrue("payout_dovuto" in o or "escrow_aperto" in o,
                        "una prenotazione pagata non risulta come soldo in ballo: %s" % o)


class TestNonSiCancellaConSoldiInBallo(_Base):

    def test_host_con_prenotazione_NON_si_cancella(self):
        self._prenota_e_paga("2026-09-05", "2026-09-08")
        st, rep = self._cancella_host()
        self.assertEqual(st, 409,
                         "un host con una prenotazione pagata e' stato CANCELLATO: %s" % rep)
        self.assertEqual(rep.get("errore"), "obblighi_pendenti")
        self.assertIn("obblighi", rep)

    def test_host_davvero_pulito_SI_cancella(self):
        st, rep = self._cancella_host()
        self.assertEqual(st, 200, "un host pulito non si riesce a cancellare: %s" % rep)
        self.assertTrue(rep.get("ok"))

    def test_forza_cancella_ma_registra_cosa_cera(self):
        self._prenota_e_paga("2026-09-05", "2026-09-08")
        st, rep = self._cancella_host(forza=True)
        self.assertIn("forzato_nonostante", rep,
                      "la cancellazione forzata non registra cosa c'era in ballo: %s" % rep)


class TestAlloggioConEscrowNonSiElimina(_Base):

    def test_escrow_aperto_blocca_l_eliminazione_anche_senza_prenotazioni_future(self):
        # un soggiorno PASSATO puo' avere l'escrow ancora aperto (in attesa del rilascio
        # o contestato). Non si puo' prenotare nel passato dal flusso HTTP, quindi si apre
        # l'escrow direttamente: l'alloggio non ha prenotazioni future, eppure custodisce
        # ancora dei soldi -> l'eliminazione deve rifiutare.
        self.sys.garanzia.apri("pren-passata-1", 18000, alloggio_id="casa")
        self.assertEqual(self.sys.garanzia.aperte_per_alloggio("casa"), 1)
        st, rep = self.g("POST", "/api/host/alloggio_elimina", {"slug": "casa"},
                         {"X-Host-Token": self.tok})
        self.assertEqual(st, 409,
                         "alloggio eliminato mentre l'escrow e' ancora aperto: %s" % rep)
        self.assertEqual(rep.get("errore"), "escrow_aperto")

    def test_il_metodo_garanzia_conta_gli_aperti(self):
        self.sys.garanzia.apri("pren-x", 18000, alloggio_id="casa")
        g = self.sys.garanzia
        self.assertGreaterEqual(g.aperte_per_alloggio("casa"), 1)
        self.assertEqual(g.aperte_per_alloggio("inesistente"), 0)
        self.assertEqual(g.aperte_per_alloggio(None), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
