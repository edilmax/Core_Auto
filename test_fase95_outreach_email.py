"""Test Fase 95 - Outreach durevole. Store iniettato, niente rete, deterministico."""
import os
import tempfile
import unittest

from fase89_jurisdiction_outreach import Contatto, FonteStub
from fase95_outreach_email import (MotoreOutreachDurevole, StoreOptOut,
                                   StoreOptOutMemoria, adatta_invio_email,
                                   crea_motore_outreach_durevole)

C_US = Contatto(nome="Hotel Sun", email="info@hotelsun.com", paese="US",
                contatto_pubblico_business=True, base_legale="B2B_contatto_pubblico")


class ProviderFinto:
    def __init__(self, ok=True):
        self.inviate = []
        self._ok = ok

    def invia(self, dest, oggetto, corpo):
        self.inviate.append((dest, oggetto, corpo))
        return self._ok


class TestStoreOptOut(unittest.TestCase):
    def test_aggiungi_contiene_durevole(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "oo.json")
        s = StoreOptOut(p)
        self.assertFalse(s.contiene("a@b.com"))
        s.aggiungi("A@B.com")
        self.assertTrue(s.contiene("a@b.com"))                 # normalizzato
        self.assertTrue(StoreOptOut(p).contiene("a@b.com"))    # ricaricato da disco
        os.remove(p)
        os.rmdir(d)

    def test_idempotente_e_vuoto_ignorato(self):
        s = StoreOptOutMemoria()
        self.assertTrue(s.aggiungi("x@y.com"))
        self.assertTrue(s.aggiungi("x@y.com"))                 # due volte = ok
        self.assertFalse(s.aggiungi(""))
        self.assertEqual(s.tutti(), ["x@y.com"])

    def test_lettura_file_assente_vuoto(self):
        self.assertEqual(StoreOptOut("/percorso/che/non/esiste.json").tutti(), [])


class TestMotoreOutreachDurevole(unittest.TestCase):
    def test_optout_persiste_tra_riavvii(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "oo.json")
        m1 = MotoreOutreachDurevole(StoreOptOut(p), giurisdizioni_permesse=["US"])
        m1.opt_out("info@hotelsun.com")
        # "riavvio": nuovo motore, stesso file -> l'opt-out è ancora attivo
        m2 = MotoreOutreachDurevole(StoreOptOut(p), giurisdizioni_permesse=["US"])
        ok, motivo = m2.consentito(C_US)
        self.assertFalse(ok)
        self.assertEqual(motivo, "opt_out")
        os.remove(p)
        os.rmdir(d)

    def test_preload_da_store(self):
        store = StoreOptOutMemoria(["info@hotelsun.com"])
        m = MotoreOutreachDurevole(store, giurisdizioni_permesse=["US"])
        ok, motivo = m.consentito(C_US)
        self.assertFalse(ok)
        self.assertEqual(motivo, "opt_out")

    def test_invio_reale_e_optout_bloccano(self):
        store = StoreOptOutMemoria()
        m = MotoreOutreachDurevole(store, giurisdizioni_permesse=["US"])
        prov = ProviderFinto()
        invia = adatta_invio_email(prov)
        rep = m.esegui(FonteStub([C_US]), paese="US", concorrenti_bps=[2500],
                       invia=invia)
        self.assertEqual(rep["inviati"], 1)
        self.assertEqual(len(prov.inviate), 1)
        # ora si disiscrive -> seconda campagna: zero invii
        m.opt_out("info@hotelsun.com")
        rep2 = m.esegui(FonteStub([C_US]), paese="US", concorrenti_bps=[2500],
                        invia=invia)
        self.assertEqual(rep2["inviati"], 0)
        self.assertEqual(rep2["motivi"].get("opt_out"), 1)


class TestAdattatoreEmail(unittest.TestCase):
    def test_gated_senza_provider(self):
        self.assertFalse(adatta_invio_email(None)("a@b.com", "o", "c", "en"))

    def test_email_invalida_false(self):
        self.assertFalse(adatta_invio_email(ProviderFinto())("nonvalida", "o", "c", "en"))

    def test_isolato_provider_esplode(self):
        class Boom:
            def invia(self, *a):
                raise RuntimeError("smtp giu")
        self.assertFalse(adatta_invio_email(Boom())("a@b.com", "o", "c", "en"))

    def test_factory_durevole(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "oo.json")
        m = crea_motore_outreach_durevole(percorso_optout=p, giurisdizioni_permesse=["US"])
        m.opt_out("x@y.com")
        self.assertTrue(StoreOptOut(p).contiene("x@y.com"))
        os.remove(p)
        os.rmdir(d)


if __name__ == "__main__":
    unittest.main()
