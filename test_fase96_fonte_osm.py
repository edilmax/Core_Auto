"""Test Fase 96 - Lead discovery OSM. fetch STUB: nessuna rete, deterministico.
Integra col motore outreach compliant (fase89/95): il gate giurisdizioni resta sovrano."""
import unittest

from fase89_jurisdiction_outreach import MotoreRadarOutreach
from fase95_outreach_email import MotoreOutreachDurevole, StoreOptOutMemoria
from fase96_fonte_osm import (FonteOpenStreetMap, _query_overpass, crea_fonte_osm)


def _osm(*emails):
    """Costruisce una risposta Overpass finta con questi elementi (email pubblica)."""
    els = []
    for e in emails:
        if e is None:
            els.append({"type": "node", "tags": {"name": "Senza Email"}})
        else:
            els.append({"type": "node", "tags": {"name": "Hotel " + e[:3],
                                                  "contact:email": e}})
    return {"elements": els}


class TestFonteOSM(unittest.TestCase):
    def test_mappa_email_pubbliche(self):
        f = FonteOpenStreetMap(fetch=lambda q: _osm("a@hotel.us", "b@inn.us"))
        c = f.cerca(paese="US")
        self.assertEqual(len(c), 2)
        self.assertTrue(all(x.contatto_pubblico_business for x in c))
        self.assertEqual(c[0].fonte, "openstreetmap")
        self.assertEqual(c[0].base_legale, "OSM_public_contact")

    def test_salta_senza_email(self):
        f = FonteOpenStreetMap(fetch=lambda q: _osm("a@hotel.us", None, "bademail"))
        self.assertEqual(len(f.cerca(paese="US")), 1)       # solo l'email valida

    def test_dedup_email(self):
        f = FonteOpenStreetMap(fetch=lambda q: _osm("Dup@Hotel.us", "dup@hotel.us"))
        self.assertEqual(len(f.cerca(paese="US")), 1)       # normalizzata + dedotta

    def test_campo_email_alternativo(self):
        f = FonteOpenStreetMap(fetch=lambda q: {"elements": [
            {"tags": {"name": "B&B", "email": "x@bb.us"}}]})
        c = f.cerca(paese="US")
        self.assertEqual(c[0].email, "x@bb.us")

    def test_paese_vuoto_lista_vuota(self):
        f = FonteOpenStreetMap(fetch=lambda q: _osm("a@hotel.us"))
        self.assertEqual(f.cerca(paese=""), [])

    def test_isolato_overpass_giu(self):
        def boom(q):
            raise RuntimeError("overpass timeout")
        self.assertEqual(FonteOpenStreetMap(fetch=boom).cerca(paese="US"), [])

    def test_query_contiene_paese_e_tipi(self):
        q = _query_overpass("jp", 50)
        self.assertIn('"ISO3166-1"="JP"', q)
        self.assertIn("hotel", q)
        self.assertIn("guest_house", q)

    def test_limit_rispettato(self):
        visto = {}
        f = FonteOpenStreetMap(fetch=lambda q: visto.update(q=q) or _osm("a@hotel.us"),
                               max_per_chiamata=10)
        f.cerca(paese="US", limit=999)                      # cap a 10
        self.assertIn("out tags 10;", visto["q"])

    def test_factory(self):
        f = crea_fonte_osm(fetch=lambda q: _osm("a@hotel.us"))
        self.assertIsInstance(f, FonteOpenStreetMap)

    def test_integrazione_outreach_gate_giurisdizioni(self):
        """OSM scopre ovunque, ma il gate fase89 contatta SOLO dove permesso."""
        f = FonteOpenStreetMap(fetch=lambda q: _osm("host@hotel.us", "host2@inn.us"))
        # USA permesso → invii > 0
        m_us = MotoreRadarOutreach(giurisdizioni_permesse=["US"])
        inviate = []
        rep = m_us.esegui(f, paese="US", concorrenti_bps=[2500],
                          invia=lambda *a: inviate.append(a) or True)
        self.assertEqual(rep["inviati"], 2)
        # Giurisdizione NON in allow-list → zero invii (fail-closed)
        m_block = MotoreRadarOutreach(giurisdizioni_permesse=["US"])
        rep2 = m_block.esegui(
            FonteOpenStreetMap(fetch=lambda q: _osm("h@hotel.fr")),
            paese="FR", concorrenti_bps=[2500], invia=lambda *a: True)
        self.assertEqual(rep2["inviati"], 0)
        self.assertEqual(rep2["bloccati"], 1)

    def test_integrazione_optout_durevole(self):
        """Un host disiscritto non viene mai più contattato (anche da lead OSM nuovi)."""
        store = StoreOptOutMemoria(["host@hotel.us"])
        m = MotoreOutreachDurevole(store, giurisdizioni_permesse=["US"])
        f = FonteOpenStreetMap(fetch=lambda q: _osm("host@hotel.us", "nuovo@inn.us"))
        rep = m.esegui(f, paese="US", concorrenti_bps=[2500], invia=lambda *a: True)
        self.assertEqual(rep["inviati"], 1)                 # solo il nuovo
        self.assertEqual(rep["motivi"].get("opt_out"), 1)


if __name__ == "__main__":
    unittest.main()
