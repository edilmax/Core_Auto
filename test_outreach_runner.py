"""Test del runner OPERATIVO acquisizione host: lead OSM (fetch finto) -> gate giurisdizioni
-> DRY-RUN (anteprima, non spedisce) / LIVE (spedisce) / opt-out rispettato. Niente rete."""
import unittest

from outreach_runner import costruisci_runner, esegui_outreach


def _stub_osm(*emails):
    els = [{"type": "node", "tags": {"name": "Hotel", "contact:email": e}} for e in emails]
    return lambda q: {"elements": els}


def _runner(fetch, giurisdizioni=("US",)):
    return costruisci_runner(optout_file=None, giurisdizioni=list(giurisdizioni),
                             link_optout="https://bookinvip.com/stop", fetch=fetch)


class TestOutreachRunner(unittest.TestCase):
    def test_dry_run_trova_e_NON_invia(self):
        rep = esegui_outreach(_runner(_stub_osm("a@inn.us")), paese="US")
        self.assertEqual(rep["modalita"], "DRY-RUN")
        self.assertEqual(rep["trovati"], 1)
        self.assertEqual(rep["inviati"], 1)                 # "inviati" = anteprima nel dry-run
        self.assertIn("a@inn.us", rep["anteprima_destinatari"])

    def test_giurisdizione_ue_bloccata(self):
        rep = esegui_outreach(_runner(_stub_osm("a@inn.fr")), paese="FR")
        self.assertEqual(rep["inviati"], 0)
        self.assertGreaterEqual(rep["bloccati"], 1)

    def test_opt_out_rispettato(self):
        runner = _runner(_stub_osm("stop@inn.us"))
        runner[1].opt_out("stop@inn.us")                    # motore = runner[1]
        rep = esegui_outreach(runner, paese="US")
        self.assertEqual(rep["inviati"], 0)
        self.assertEqual(rep["motivi"].get("opt_out"), 1)

    def test_live_richiede_provider_altrimenti_dry(self):
        # senza SMTP, invia_live=True degrada a DRY-RUN (non spedisce a vuoto)
        rep = esegui_outreach(_runner(_stub_osm("a@inn.us")), paese="US", invia_live=True)
        self.assertEqual(rep["modalita"], "DRY-RUN")

    def test_live_con_provider_finto_spedisce(self):
        # con un "provider" email finto (adattato), LIVE spedisce davvero al sender
        spediti = []

        class EP:
            def invia(self, dest, ogg, corpo):
                spediti.append(dest); return True
        from fase95_outreach_email import adatta_invio_email
        fonte, motore, _ = _runner(_stub_osm("a@inn.us"))
        rep = esegui_outreach((fonte, motore, adatta_invio_email(EP())),
                              paese="US", invia_live=True)
        self.assertEqual(rep["modalita"], "LIVE")
        self.assertEqual(spediti, ["a@inn.us"])


if __name__ == "__main__":
    unittest.main()
