"""
Test Fase 40 / Tavola VIP - Agente IA reale agganciato al booking.

Copre: AnthropicLLMProvider (client iniettato, modello corretto, fail-closed senza
chiave) e l'AgenteBooking (Variante C): prenotazione completa -> link Stripe;
incompleta -> chiarimento (niente prenotazione); intento non-prenotazione -> info;
JSON spazzatura -> info; IA giu' -> errore isolato; overlap -> non_disponibile;
e il DENARO calcolato dal SISTEMA (mai dall'IA).
"""
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

from fase40_agente_booking import (AnthropicLLMProvider, AgenteBooking,
                                   RispostaBooking)
from fase25_brain import StubLLMProvider, LLMProvider
from fase34_prenotazioni import MotorePrenotazioni
from fase35_pagamenti import StubPagamentoProvider, ServizioPagamenti


class _Failing(LLMProvider):
    def genera(self, p):
        raise RuntimeError("IA giu'")


def _fake_client(testo):
    """Finto client Anthropic: registra le chiamate, ritorna un blocco di testo."""
    chiamate = []
    def create(**kw):
        chiamate.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=testo)])
    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return client, chiamate


class TestAnthropicProvider(unittest.TestCase):
    def test_genera_usa_client_e_modello(self):
        client, chiamate = _fake_client('{"intento":"domanda"}')
        p = AnthropicLLMProvider(client=client)
        out = p.genera("ciao")
        self.assertEqual(out, '{"intento":"domanda"}')
        self.assertEqual(chiamate[0]["model"], "claude-opus-4-8")  # default corretto
        self.assertEqual(chiamate[0]["messages"][0]["content"], "ciao")

    def test_modello_override_env(self):
        client, chiamate = _fake_client("x")
        AnthropicLLMProvider(client=client, model="claude-sonnet-4-6").genera("y")
        self.assertEqual(chiamate[0]["model"], "claude-sonnet-4-6")

    def test_fail_closed_senza_chiave(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        with self.assertRaises(RuntimeError):
            AnthropicLLMProvider(api_key="").genera("ciao")  # niente client, niente chiave


class _BaseAgente(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.motore = MotorePrenotazioni(lambda: sqlite3.connect(self.path, timeout=30))
        self.motore.inizializza_schema()
        self.servizio = ServizioPagamenti(self.motore, StubPagamentoProvider(segreto="s"))

    def tearDown(self):
        for ext in ("", "-wal", "-shm", "-journal"):
            try:
                os.remove(self.path + ext)
            except OSError:
                pass

    def _agente(self, provider):
        ag = AgenteBooking(provider, self.motore, self.servizio,
                           prezzo_notte_cents=10000, commissione_bps=1000)
        self.addCleanup(ag.stop)
        return ag

    def _json(self, s):
        return self._agente(StubLLMProvider(risposta=s))


class TestAgenteBooking(_BaseAgente):
    def test_prenotazione_completa_genera_link(self):
        ag = self._json('{"intento":"prenotazione","alloggio":"VIP-12",'
                        '"check_in":"2026-08-10","check_out":"2026-08-12","email":"m@x.it"}')
        r = ag.gestisci_chat("prenota VIP-12 dal 10 al 12 agosto")
        self.assertEqual(r.azione, "prenotata")
        self.assertTrue(r.payment_url)
        self.assertIsNotNone(r.prenotazione_id)
        st = self.motore.stato(r.prenotazione_id)
        self.assertEqual(st["stato"], "in_attesa_pagamento")

    def test_denaro_calcolato_dal_sistema(self):
        ag = self._json('{"intento":"prenotazione","alloggio":"VIP-1",'
                        '"check_in":"2026-09-01","check_out":"2026-09-04"}')  # 3 notti
        r = ag.gestisci_chat("x")
        c = sqlite3.connect(self.path)
        row = c.execute("SELECT importo_totale, commissione_tavola, quota_partner "
                        "FROM pagamenti_split").fetchone()
        c.close()
        self.assertEqual(row[0], 30000)            # 3 notti * 10000
        self.assertEqual(row[1], 3000)             # 10% di 30000
        self.assertEqual(row[1] + row[2], row[0])  # split quadra

    def test_incompleta_chiede_chiarimento(self):
        ag = self._json('{"intento":"prenotazione","alloggio":"VIP-12",'
                        '"check_in":"2026-08-10"}')   # manca check_out
        r = ag.gestisci_chat("prenota VIP-12 il 10 agosto")
        self.assertEqual(r.azione, "chiarimento")
        self.assertEqual(self.motore.num_sessioni() if hasattr(self.motore, "num_sessioni") else 0, 0)
        c = sqlite3.connect(self.path)
        n = c.execute("SELECT COUNT(*) FROM prenotazioni").fetchone()[0]
        c.close()
        self.assertEqual(n, 0)                     # NESSUNA prenotazione

    def test_intento_domanda_info(self):
        ag = self._json('{"intento":"domanda"}')
        self.assertEqual(ag.gestisci_chat("che orari fate?").azione, "info")

    def test_json_spazzatura_info(self):
        ag = self._json("non sono json, sono testo libero")
        self.assertEqual(ag.gestisci_chat("asdf").azione, "info")

    def test_ia_giu_isolata_errore(self):
        ag = self._agente(_Failing())
        r = ag.gestisci_chat("prenota qualcosa")
        self.assertEqual(r.azione, "errore")       # nessun crash, nessuna prenotazione

    def test_overlap_non_disponibile(self):
        js = ('{"intento":"prenotazione","alloggio":"VIP-9",'
              '"check_in":"2026-10-01","check_out":"2026-10-05"}')
        self.assertEqual(self._json(js).gestisci_chat("x").azione, "prenotata")
        self.assertEqual(self._json(js).gestisci_chat("x").azione, "non_disponibile")


if __name__ == "__main__":
    unittest.main()
