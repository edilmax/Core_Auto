"""
Test del Ponte verso il Booking (fase49, M7). Aggancio sicuro conversione->booking:
default-off, denaro dal Core (mai dall'IA), fail-closed importi, single touchpoint,
idempotenza esattamente-una-volta sotto carico concorrente (at-least-once), zero
link orfani, input corrotti, fuzzing.
"""
import os
import random
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from fase49_ponte_booking import (
    DatiConversione, EsitoConversione, PonteBooking, PonteBookingError,
    crea_ponte_booking)


# ─────────────────────────────────────────────────────────────────────────────
# Stub del nucleo booking + servizio pagamenti (stessa interfaccia di fase40)
# ─────────────────────────────────────────────────────────────────────────────
class _Esito:
    def __init__(self, ok, motivo="", prenotazione_id=None, pagamento_id=None):
        self.ok = ok
        self.motivo = motivo
        self.prenotazione_id = prenotazione_id
        self.pagamento_id = pagamento_id


class _Link:
    def __init__(self, url):
        self.url = url


class StubMotore:
    """Simula `MotorePrenotazioni`: overlap atomico (1 sola prenotazione per
    alloggio+date), conteggia le create REALI e registra le richieste ricevute."""
    def __init__(self, esito_forzato=None):
        self.creazioni = 0
        self.richieste = []
        self._occupati = set()
        self._lock = threading.Lock()
        self._next = 0
        self._forzato = esito_forzato

    def crea(self, r):
        with self._lock:
            self.creazioni += 1
            self.richieste.append(r)
            if self._forzato is not None:
                return self._forzato
            chiave = (r.alloggio_id, r.check_in, r.check_out)
            if chiave in self._occupati:
                return _Esito(False, "non_disponibile")
            self._occupati.add(chiave)
            self._next += 1
            i = self._next
            return _Esito(True, "creata", prenotazione_id=i, pagamento_id=1000 + i)


class StubServizio:
    def __init__(self):
        self.link_emessi = 0
        self.importi = []
        self._lock = threading.Lock()

    def crea_link_pagamento(self, *, pagamento_id, importo_cents, email):
        with self._lock:
            self.link_emessi += 1
            self.importi.append(importo_cents)
        return _Link(f"https://pay.core/{pagamento_id}")


def _dati(chiave="conv-1", alloggio="VIP-12", imp=20000, comm=600, **kw):
    base = dict(chiave_conversione=chiave, alloggio_id=alloggio,
                check_in="2026-07-01", check_out="2026-07-03",
                email="ospite@x.it", prezzo_guest_cents=imp, incasso_mango_cents=comm)
    base.update(kw)
    return DatiConversione(**base)


class _Proposta:
    def __init__(self, g, m):
        self.prezzo_guest_cents = g
        self.incasso_mango_cents = m


# ─────────────────────────────────────────────────────────────────────────────
class TestAggancioBase(unittest.TestCase):
    def setUp(self):
        self.m, self.s = StubMotore(), StubServizio()
        self.p = crea_ponte_booking(self.m, self.s, abilitato=True)

    def test_aggancio_felice(self):
        e = self.p.aggancia(_dati())
        self.assertTrue(e.ok)
        self.assertEqual(e.azione, "agganciata")
        self.assertEqual(e.prenotazione_id, 1)
        self.assertEqual(e.pagamento_id, 1001)
        self.assertEqual(e.payment_url, "https://pay.core/1001")
        self.assertEqual(self.s.link_emessi, 1)

    def test_denaro_dal_core_non_dall_ia(self):
        # importo e commissione passano IDENTICI dal Core al motore (nessun ricalcolo)
        self.p.aggancia(_dati(imp=33333, comm=4444))
        r = self.m.richieste[0]
        self.assertEqual(r.importo_totale_cents, 33333)
        self.assertEqual(r.commissione_cents, 4444)
        self.assertEqual(self.s.importi[0], 33333)   # link sull'importo guest

    def test_costruzione_da_proposta(self):
        d = DatiConversione.da_proposta(
            _Proposta(25000, 1500), chiave_conversione="c9", alloggio_id="VIP-9",
            check_in="2026-08-01", check_out="2026-08-04", email="g@x.it")
        e = self.p.aggancia(d)
        self.assertTrue(e.ok)
        self.assertEqual(self.m.richieste[0].importo_totale_cents, 25000)
        self.assertEqual(self.m.richieste[0].commissione_cents, 1500)


class TestDefaultOff(unittest.TestCase):
    def test_default_off_non_tocca_il_booking(self):
        m, s = StubMotore(), StubServizio()
        p = crea_ponte_booking(m, s, abilitato=False)
        e = p.aggancia(_dati())
        self.assertFalse(e.ok)
        self.assertEqual(e.azione, "disattivato")
        self.assertEqual(m.creazioni, 0)        # il nucleo non viene MAI chiamato
        self.assertEqual(s.link_emessi, 0)

    def test_env_flag_accende(self):
        m, s = StubMotore(), StubServizio()
        os.environ["CORE_PONTE_BOOKING"] = "1"
        try:
            p = crea_ponte_booking(m, s)        # abilitato=None -> legge env
            self.assertTrue(p.abilitato)
            self.assertTrue(p.aggancia(_dati()).ok)
        finally:
            del os.environ["CORE_PONTE_BOOKING"]

    def test_env_assente_default_off(self):
        os.environ.pop("CORE_PONTE_BOOKING", None)
        p = crea_ponte_booking(StubMotore(), StubServizio())
        self.assertFalse(p.abilitato)


class TestFailClosed(unittest.TestCase):
    def setUp(self):
        self.m, self.s = StubMotore(), StubServizio()
        self.p = crea_ponte_booking(self.m, self.s, abilitato=True)

    def test_commissione_oltre_importo_blocca(self):
        e = self.p.aggancia(_dati(imp=1000, comm=2000))
        self.assertFalse(e.ok)
        self.assertEqual(e.azione, "importi_non_validi")
        self.assertEqual(self.m.creazioni, 0)
        self.assertEqual(self.s.link_emessi, 0)   # nessun link orfano

    def test_importo_zero_blocca(self):
        e = self.p.aggancia(_dati(imp=0, comm=0))
        self.assertFalse(e.ok)
        self.assertEqual(e.azione, "importi_non_validi")

    def test_dati_mancanti_bloccano(self):
        for kw in (dict(alloggio=""), dict(check_in=""), dict(check_out=""),
                   dict(email="")):
            e = self.p.aggancia(_dati(**kw))
            self.assertFalse(e.ok)
            self.assertEqual(e.azione, "dati_non_validi")
        self.assertEqual(self.m.creazioni, 0)

    def test_non_disponibile_nessun_link(self):
        self.p.aggancia(_dati(chiave="c1"))                       # occupa
        e = self.p.aggancia(_dati(chiave="c2"))                   # stesso alloggio+date
        self.assertFalse(e.ok)
        self.assertEqual(e.azione, "non_disponibile")
        self.assertEqual(self.s.link_emessi, 1)                   # solo il primo

    def test_motore_date_non_valide(self):
        m = StubMotore(esito_forzato=_Esito(False, "date_non_valide"))
        p = crea_ponte_booking(m, StubServizio(), abilitato=True)
        self.assertEqual(p.aggancia(_dati()).azione, "date_non_valide")

    def test_motore_errore_generico(self):
        m = StubMotore(esito_forzato=_Esito(False, "boom_sconosciuto"))
        p = crea_ponte_booking(m, StubServizio(), abilitato=True)
        self.assertEqual(p.aggancia(_dati()).azione, "errore")


class TestInputCorrotti(unittest.TestCase):
    def test_centesimi_negativi(self):
        with self.assertRaises(ValueError):
            _dati(imp=-1)
        with self.assertRaises(ValueError):
            _dati(comm=-5)

    def test_centesimi_bool_rifiutati(self):
        with self.assertRaises(ValueError):
            _dati(imp=True)

    def test_chiave_vuota(self):
        with self.assertRaises(ValueError):
            _dati(chiave="")

    def test_motore_o_servizio_none(self):
        with self.assertRaises(PonteBookingError):
            PonteBooking(None, StubServizio(), abilitato=True)
        with self.assertRaises(PonteBookingError):
            PonteBooking(StubMotore(), None, abilitato=True)


class TestIdempotenza(unittest.TestCase):
    def setUp(self):
        self.m, self.s = StubMotore(), StubServizio()
        self.p = crea_ponte_booking(self.m, self.s, abilitato=True)

    def test_replay_sequenziale_una_sola_prenotazione(self):
        e1 = self.p.aggancia(_dati(chiave="c1"))
        e2 = self.p.aggancia(_dati(chiave="c1"))
        self.assertTrue(e1.ok and e2.ok)
        self.assertFalse(e1.idempotente)
        self.assertTrue(e2.idempotente)          # secondo = replay dalla cache
        self.assertEqual(e1.prenotazione_id, e2.prenotazione_id)
        self.assertEqual(self.m.creazioni, 1)    # UNA sola create reale
        self.assertEqual(self.s.link_emessi, 1)  # UN solo link

    def test_chiavi_diverse_prenotazioni_diverse(self):
        e1 = self.p.aggancia(_dati(chiave="a", alloggio="VIP-1"))
        e2 = self.p.aggancia(_dati(chiave="b", alloggio="VIP-2"))
        self.assertNotEqual(e1.prenotazione_id, e2.prenotazione_id)
        self.assertEqual(self.m.creazioni, 2)

    def test_fallimento_non_cachato_ritentabile(self):
        # primo tentativo fallisce per importi -> non in cache -> ritentabile
        self.assertFalse(self.p.aggancia(_dati(chiave="c1", imp=10, comm=99)).ok)
        e = self.p.aggancia(_dati(chiave="c1", imp=20000, comm=600))
        self.assertTrue(e.ok)
        self.assertEqual(self.m.creazioni, 1)


class TestConcorrenza(unittest.TestCase):
    def test_at_least_once_esattamente_una_prenotazione(self):
        """64 worker agganciano la STESSA conversione in parallelo: deve risultare
        UNA sola prenotazione, UN solo link, e tutti gli esiti ok coerenti."""
        for _ in range(10):                       # ripetuto: scova le race rare
            m, s = StubMotore(), StubServizio()
            p = crea_ponte_booking(m, s, abilitato=True)
            with ThreadPoolExecutor(max_workers=64) as ex:
                esiti = list(ex.map(lambda _i: p.aggancia(_dati(chiave="c")), range(64)))
            ok = [e for e in esiti if e.ok]
            self.assertEqual(len(ok), 64)         # tutti ok (1 vero + 63 replay)
            ids = {e.prenotazione_id for e in ok}
            urls = {e.payment_url for e in ok}
            self.assertEqual(len(ids), 1)         # una sola prenotazione
            self.assertEqual(len(urls), 1)
            self.assertEqual(m.creazioni, 1)      # una sola create reale
            self.assertEqual(s.link_emessi, 1)    # nessun link orfano/doppio

    def test_molte_chiavi_distinte_in_parallelo(self):
        m, s = StubMotore(), StubServizio()
        p = crea_ponte_booking(m, s, abilitato=True)
        n = 200
        with ThreadPoolExecutor(max_workers=64) as ex:
            esiti = list(ex.map(
                lambda k: p.aggancia(_dati(chiave=f"c{k}", alloggio=f"VIP-{k}")),
                range(n)))
        self.assertTrue(all(e.ok for e in esiti))
        self.assertEqual(m.creazioni, n)
        self.assertEqual(s.link_emessi, n)
        self.assertEqual(len({e.prenotazione_id for e in esiti}), n)


class TestFuzzing(unittest.TestCase):
    def test_fuzz_invarianti(self):
        rnd = random.Random(49)
        for _ in range(5000):
            m, s = StubMotore(), StubServizio()
            p = crea_ponte_booking(m, s, abilitato=True)
            imp = rnd.randint(0, 1_000_000)
            comm = rnd.randint(0, 1_000_000)
            e = p.aggancia(_dati(imp=imp, comm=comm))
            if imp > 0 and comm <= imp:
                self.assertTrue(e.ok)
                self.assertEqual(s.link_emessi, 1)
                self.assertEqual(s.importi[0], imp)        # link sempre sull'importo guest
            else:
                self.assertFalse(e.ok)                     # fail-closed
                self.assertEqual(e.azione, "importi_non_validi")
                self.assertEqual(m.creazioni, 0)
                self.assertEqual(s.link_emessi, 0)         # mai un link orfano


if __name__ == "__main__":
    unittest.main()
