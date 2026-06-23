"""
Test anti-drift di ROADMAP_MANGO.md: il piano di riattivazione di Mango deve
esistere, coprire i 7 mattoni (fase43..fase49), il protocollo d'isolamento e il
fatto chiave che il motore booking NON viene toccato.
"""
import os
import unittest


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestRoadmapMango(unittest.TestCase):
    def setUp(self):
        self.doc = _read("ROADMAP_MANGO.md")

    def test_sette_mattoni(self):
        for n in range(43, 50):                      # fase43..fase49
            self.assertIn("fase{}".format(n), self.doc, "manca fase%d" % n)

    def test_protocollo_isolamento(self):
        for c in ("default-off", "lazy", "gate di regressione", "denaro dal SISTEMA",
                  "RicercaProvider", "492"):
            self.assertIn(c, self.doc, c)

    def test_correzione_presupposto(self):
        # deve chiarire che 24-33 sono gia' costruite e che Mango riusa l'esistente
        for c in ("Rana Inversa", "compliant", "non importano"):
            self.assertIn(c, self.doc, c)

    def _esiste(self, n):
        return any(f.startswith("fase{}_".format(n)) and f.endswith(".py")
                   for f in os.listdir("."))

    def test_mattoni_core_costruiti(self):
        # M1-M7: commissione, prezzo, split, esploratore, venditore, advertising,
        # ponte booking: fase43-49 (tutti i 7 mattoni Mango ora costruiti).
        for n in (43, 44, 45, 46, 47, 48, 49):
            self.assertTrue(self._esiste(n), "fase%d mancante" % n)

    def test_i_numeri_mango_futuri_sono_liberi(self):
        # mattoni a fase49; 50=orchestratore; 51=scheduler; 52=persistenza+metriche;
        # 53=health-guard; 54=loop; 55=bootstrap; 56=gateway tavoli;
        # 57=vetrina/catalogo pubblico (storefront);
        # 58=channel manager/inventario host tempo reale;
        # 59=protocollo concierge AI (agent-discoverable);
        # 60=MCP server (Model Context Protocol);
        # 61=localizzazione i18n a costo zero;
        # 62=predictive no-show + overbooking controllato;
        # 63=recensioni verificate (anti-fake);
        # 64=smart-pass d'ingresso/self check-in;
        # 65=split-payment di gruppo;
        # 66=tassa di soggiorno jurisdiction-agnostic;
        # 67=coda intelligente + cancellazione garantita;
        # 68=niche profiler (niche stacking);
        # 69=trasparenza commissionale (noi vs OTA);
        # 70=automated turnover (pulizie check-out->check-in);
        # 71=commitment engine (anti-cancellazione+cleaning+chargeback);
        # 72=digital twin (telemetria+manutenzione predittiva);
        # 73=firma agile (crypto-agility+anti-downgrade);
        # 74=sensory engine (sensory score);
        # 75=guardian engine (rilevamento pericoli+risposta);
        # 76=viral loop engine (crediti non-cashabili);
        # 77=portability import (GDPR/DMA data-portability);
        # 78=sleep guarantee (sleep-as-a-service money-back);
        # 79=dichiarazione vincolante (host dichiara, escrow paga);
        # 80=sentinel FIM+canary+catena integrita';
        # 81=bootstrap casa vip (composition root lodging);
        # 82=ical sync (portabilita' reale cross-canale);
        # 83=server HTTP (API + frontend, fase81+fase61);
        # 84=LIBERO (coordinatore multi-agente valutato e SCARTATO);
        # 85=provider pagamento Stripe (money-path);
        # 86=provider email voucher SMTP (gated);
        # 87=webhook Stripe (verifica firma + conferma pagamento);
        # 88=registro host self-service (registrazione/login/token firmato);
        # 89=jurisdiction B2B radar & outreach (gate giurisdizioni + email Prima Emilia). Blocco 90+ libero.
        for n in range(90, 93):
            self.assertFalse(self._esiste(n), "fase%d gia' occupata: rinumerare" % n)


if __name__ == "__main__":
    unittest.main()
