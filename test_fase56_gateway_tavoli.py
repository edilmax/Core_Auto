"""
Test del Gateway Tavoli VIP (fase56). Validazione blindata dei contratti JSON (denaro
SOLO centesimi interi, zero float/stringhe/bool), auth enterprise separata + isolamento
per-tenant, integrazione col Bootstrap (fase55), risposte senza float, metriche in bps.
"""
import unittest

from fase55_bootstrap import ConfigMango, costruisci
from fase49_ponte_booking import EsitoConversione
from fase56_gateway_tavoli import (
    RegistroEnterprise, ClienteEnterprise, RichiestaTavolo, RispostaTavoli,
    valida_richiesta_tavolo, GatewayTavoli, crea_gateway_tavoli)


# ─────────────────────────────────────────────────────────────────────────────
# Stub Ponte (money-path): cattura i dati e ritorna un esito configurabile
# ─────────────────────────────────────────────────────────────────────────────
class StubPonte:
    def __init__(self, esito=None):
        self.visti = []
        self._esito = esito or EsitoConversione(
            True, "agganciata", prenotazione_id=7, pagamento_id=1007,
            payment_url="https://pay.core/1007")
    def aggancia(self, dati):
        self.visti.append(dati)
        return self._esito


def _payload(**kw):
    base = dict(chiave_conversione="c1", tavolo_id="VIP-12",
                check_in="2026-07-01", check_out="2026-07-03", email="g@x.it",
                prezzo_guest_cents=20000, incasso_mango_cents=600)
    base.update(kw)
    return base


def _registro():
    return RegistroEnterprise.da_dict({
        "KEY-AAA": ("locale_alfa", "Club Alfa"),
        "KEY-BBB": ("locale_beta", "Club Beta")})


def _sistema(ponte, *, abilitato=True):
    return costruisci(ConfigMango(abilitato=abilitato, intervallo_s=0), ponte=ponte)


def _no_float(o):
    """True se NESSUN float compare nel payload (ricorsivo)."""
    if isinstance(o, float):
        return False
    if isinstance(o, dict):
        return all(_no_float(v) for v in o.values())
    if isinstance(o, (list, tuple)):
        return all(_no_float(v) for v in o)
    return True


# ─────────────────────────────────────────────────────────────────────────────
class TestValidazionePayload(unittest.TestCase):
    def test_valido(self):
        ok, code, req = valida_richiesta_tavolo(_payload())
        self.assertTrue(ok, code)
        self.assertIsInstance(req, RichiestaTavolo)
        self.assertEqual(req.prezzo_guest_cents, 20000)
        self.assertIsInstance(req.prezzo_guest_cents, int)

    def test_payload_non_oggetto(self):
        for bad in (None, [], "x", 5):
            ok, code, _ = valida_richiesta_tavolo(bad)
            self.assertFalse(ok)
            self.assertEqual(code, "payload_non_oggetto")

    def test_campi_stringa_mancanti(self):
        for nome in ("chiave_conversione", "tavolo_id", "check_in", "check_out", "email"):
            p = _payload(); del p[nome]
            ok, code, _ = valida_richiesta_tavolo(p)
            self.assertFalse(ok)
            self.assertEqual(code, f"campo_mancante:{nome}")

    def test_campo_non_stringa(self):
        ok, code, _ = valida_richiesta_tavolo(_payload(tavolo_id=123))
        self.assertEqual(code, "campo_non_stringa:tavolo_id")

    def test_campo_vuoto(self):
        ok, code, _ = valida_richiesta_tavolo(_payload(email="   "))
        self.assertEqual(code, "campo_vuoto:email")

    def test_email_non_valida(self):
        ok, code, _ = valida_richiesta_tavolo(_payload(email="nonemail"))
        self.assertEqual(code, "email_non_valida")

    def test_date_non_valide(self):
        self.assertEqual(valida_richiesta_tavolo(_payload(check_in="2026-13-01"))[1],
                         "data_non_valida:check_in")
        self.assertEqual(valida_richiesta_tavolo(_payload(check_out="ieri"))[1],
                         "data_non_valida:check_out")

    def test_date_incoerenti(self):
        ok, code, _ = valida_richiesta_tavolo(
            _payload(check_in="2026-07-05", check_out="2026-07-03"))
        self.assertEqual(code, "date_incoerenti")

    # --- DENARO: solo int cents, zero float/stringhe/bool mascherati ---
    def test_denaro_float_rifiutato(self):
        ok, code, _ = valida_richiesta_tavolo(_payload(prezzo_guest_cents=200.0))
        self.assertFalse(ok)
        self.assertEqual(code, "denaro_non_intero:prezzo_guest_cents")

    def test_denaro_stringa_rifiutata(self):
        ok, code, _ = valida_richiesta_tavolo(_payload(prezzo_guest_cents="20000"))
        self.assertEqual(code, "denaro_non_intero:prezzo_guest_cents")

    def test_denaro_stringa_decimale_rifiutata(self):
        ok, code, _ = valida_richiesta_tavolo(_payload(incasso_mango_cents="6.00"))
        self.assertEqual(code, "denaro_non_intero:incasso_mango_cents")

    def test_denaro_bool_rifiutato(self):
        ok, code, _ = valida_richiesta_tavolo(_payload(prezzo_guest_cents=True))
        self.assertEqual(code, "denaro_non_intero:prezzo_guest_cents")

    def test_denaro_negativo(self):
        ok, code, _ = valida_richiesta_tavolo(_payload(incasso_mango_cents=-1))
        self.assertEqual(code, "denaro_negativo:incasso_mango_cents")

    def test_denaro_oltre_tetto(self):
        ok, code, _ = valida_richiesta_tavolo(_payload(prezzo_guest_cents=10**12))
        self.assertEqual(code, "denaro_oltre_tetto:prezzo_guest_cents")

    def test_incasso_oltre_prezzo(self):
        ok, code, _ = valida_richiesta_tavolo(
            _payload(prezzo_guest_cents=1000, incasso_mango_cents=2000))
        self.assertEqual(code, "incasso_oltre_prezzo")

    def test_prezzo_nullo(self):
        ok, code, _ = valida_richiesta_tavolo(
            _payload(prezzo_guest_cents=0, incasso_mango_cents=0))
        self.assertEqual(code, "prezzo_nullo")

    def test_opzionale_non_stringa(self):
        ok, code, _ = valida_richiesta_tavolo(_payload(ospite_nome=42))
        self.assertEqual(code, "campo_non_stringa:ospite_nome")


class TestAuthEnterprise(unittest.TestCase):
    def test_chiave_errata_401(self):
        g = crea_gateway_tavoli(_registro(), _sistema(StubPonte()))
        r = g.processa_prenotazione("KEY-XXX", _payload())
        self.assertEqual(r.status, 401)

    def test_clienti_separati(self):
        reg = _registro()
        self.assertEqual(reg.autentica("KEY-AAA").client_id, "locale_alfa")
        self.assertEqual(reg.autentica("KEY-BBB").client_id, "locale_beta")
        self.assertIsNone(reg.autentica(""))

    def test_isolamento_tenant_chiave_namespacata(self):
        ponte = StubPonte()
        g = crea_gateway_tavoli(_registro(), _sistema(ponte))
        g.processa_prenotazione("KEY-AAA", _payload(chiave_conversione="ORD-1"))
        g.processa_prenotazione("KEY-BBB", _payload(chiave_conversione="ORD-1"))
        chiavi = [d.chiave_conversione for d in ponte.visti]
        self.assertIn("locale_alfa:ORD-1", chiavi)
        self.assertIn("locale_beta:ORD-1", chiavi)
        self.assertNotEqual(chiavi[0], chiavi[1])      # nessuna collisione cross-locale


class TestFlussoPrenotazione(unittest.TestCase):
    def test_201_agganciata_e_corpo(self):
        g = crea_gateway_tavoli(_registro(), _sistema(StubPonte()))
        r = g.processa_prenotazione("KEY-AAA", _payload())
        self.assertEqual(r.status, 201)
        self.assertEqual(r.corpo["stato"], "agganciata")
        self.assertEqual(r.corpo["prenotazione_id"], 7)
        self.assertEqual(r.corpo["prezzo_guest_cents"], 20000)
        self.assertEqual(r.corpo["valuta"], "EUR")

    def test_payload_invalido_400(self):
        g = crea_gateway_tavoli(_registro(), _sistema(StubPonte()))
        r = g.processa_prenotazione("KEY-AAA", _payload(prezzo_guest_cents=200.0))
        self.assertEqual(r.status, 400)
        self.assertEqual(r.corpo["dettaglio"], "denaro_non_intero:prezzo_guest_cents")

    def test_non_disponibile_409(self):
        ponte = StubPonte(EsitoConversione(False, "non_disponibile"))
        g = crea_gateway_tavoli(_registro(), _sistema(ponte))
        r = g.processa_prenotazione("KEY-AAA", _payload())
        self.assertEqual(r.status, 409)

    def test_importi_non_validi_422(self):
        ponte = StubPonte(EsitoConversione(False, "importi_non_validi"))
        g = crea_gateway_tavoli(_registro(), _sistema(ponte))
        r = g.processa_prenotazione("KEY-AAA", _payload())
        self.assertEqual(r.status, 422)

    def test_sistema_spento_503(self):
        g = crea_gateway_tavoli(_registro(), costruisci(ConfigMango(abilitato=False)))
        r = g.processa_prenotazione("KEY-AAA", _payload())
        self.assertEqual(r.status, 503)
        self.assertEqual(r.corpo["errore"], "service_disabled")

    def test_circuito_in_pausa_503(self):
        sistema = _sistema(StubPonte())
        sistema.circuito.forza_apertura()              # health-guard mette in pausa
        g = crea_gateway_tavoli(_registro(), sistema)
        r = g.processa_prenotazione("KEY-AAA", _payload())
        self.assertEqual(r.status, 503)
        self.assertEqual(r.corpo["errore"], "service_paused")

    def test_idempotenza_replay(self):
        # stesso ponte reale-like: il SistemaMango persiste; due richieste stessa chiave
        g = crea_gateway_tavoli(_registro(), _sistema(StubPonte()))
        r1 = g.processa_prenotazione("KEY-AAA", _payload(chiave_conversione="ORD-9"))
        r2 = g.processa_prenotazione("KEY-AAA", _payload(chiave_conversione="ORD-9"))
        self.assertEqual(r1.status, 201)
        self.assertEqual(r2.status, 201)


class TestZeroFloat(unittest.TestCase):
    def test_risposta_prenotazione_senza_float(self):
        g = crea_gateway_tavoli(_registro(), _sistema(StubPonte()))
        r = g.processa_prenotazione("KEY-AAA", _payload())
        self.assertTrue(_no_float(r.corpo), r.corpo)

    def test_metriche_senza_float_e_bps(self):
        g = crea_gateway_tavoli(_registro(), _sistema(StubPonte()))
        g.processa_prenotazione("KEY-AAA", _payload())
        r = g.processa_metriche("KEY-AAA")
        self.assertEqual(r.status, 200)
        self.assertTrue(_no_float(r.corpo), r.corpo)
        self.assertIsInstance(r.corpo["conversion_rate_bps"], int)
        self.assertIsInstance(r.corpo["conversioni_riuscite"], int)

    def test_metriche_401_senza_chiave(self):
        g = crea_gateway_tavoli(_registro(), _sistema(StubPonte()))
        self.assertEqual(g.processa_metriche("KEY-XXX").status, 401)


class TestNonSollevaMai(unittest.TestCase):
    def test_eccezione_interna_isolata_503(self):
        class SistemaRotto:
            class config: abilitato = True
            class circuito:
                @staticmethod
                def consenti(): return True
            scheduler = None                            # -> AttributeError dentro _instrada
        g = GatewayTavoli(_registro(), SistemaRotto())
        r = g.processa_prenotazione("KEY-AAA", _payload())
        self.assertEqual(r.status, 503)
        self.assertEqual(r.corpo["errore"], "service_unavailable")


if __name__ == "__main__":
    unittest.main()
