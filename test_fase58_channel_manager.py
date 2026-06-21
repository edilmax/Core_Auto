"""
Test Fase 58 - Channel Manager / Inventario host in tempo reale (anti-overbooking).

Copre: set disponibilita' + fail-closed, lettura disponibile() (firma provider vetrina),
blocco atomico, idempotenza (replay), rifiuti (pieno/chiuso/min_notti/giorno assente),
multi-notte all-or-nothing, rilascio idempotente, ingest esterno (anti-overbooking
cross-canale), parser comandi blindato, comandi applicati, notifica isolata, e lo
STRESS concorrente: N thread sulla STESSA notte da 1 unita' -> esattamente 1 vince
(zero doppie vendite), ripetuto 10x.
"""
import os
import shutil
import tempfile
import threading
import unittest

from fase58_channel_manager import (
    ChannelManager, EsitoPrenotazione, crea_channel_manager, interpreta_comando,
    notti,
)


def _cm():
    return crea_channel_manager()


def _carica(cm, alloggio="a", giorni=("2026-07-01", "2026-07-02", "2026-07-03"),
            unita=1, prezzo=10000, chiuso=False, min_notti=1):
    for g in giorni:
        assert cm.imposta_disponibilita(alloggio, g, unita_totali=unita,
                                        prezzo_netto_cents=prezzo, chiuso=chiuso,
                                        min_notti=min_notti)


class TestNotti(unittest.TestCase):
    def test_semiaperto(self):
        self.assertEqual(notti("2026-07-01", "2026-07-03"),
                         ["2026-07-01", "2026-07-02"])

    def test_invalide(self):
        self.assertIsNone(notti("2026-07-03", "2026-07-01"))
        self.assertIsNone(notti("x", "y"))
        self.assertIsNone(notti("2026-07-01", "2026-07-01"))


class TestDisponibilita(unittest.TestCase):
    def setUp(self):
        self.cm = _cm()

    def test_set_e_stato(self):
        self.assertTrue(self.cm.imposta_disponibilita("a", "2026-07-01",
                        unita_totali=3, prezzo_netto_cents=12000))
        s = self.cm.stato_giorno("a", "2026-07-01")
        self.assertEqual(s["unita_totali"], 3)
        self.assertEqual(s["prezzo_netto_cents"], 12000)

    def test_prezzo_float_rifiutato(self):
        self.assertFalse(self.cm.imposta_disponibilita("a", "2026-07-01",
                         unita_totali=1, prezzo_netto_cents=120.0))

    def test_unita_negativa_rifiutata(self):
        self.assertFalse(self.cm.imposta_disponibilita("a", "2026-07-01",
                         unita_totali=-1, prezzo_netto_cents=100))

    def test_data_invalida_rifiutata(self):
        self.assertFalse(self.cm.imposta_disponibilita("a", "non-data",
                         unita_totali=1, prezzo_netto_cents=100))

    def test_non_scende_sotto_occupato(self):
        _carica(self.cm, unita=2)
        self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        # 1 occupato quel giorno -> non posso impostare totali=0
        self.assertFalse(self.cm.imposta_disponibilita("a", "2026-07-01",
                         unita_totali=0, prezzo_netto_cents=100))

    def test_disponibile_provider(self):
        _carica(self.cm, unita=1)
        self.assertTrue(self.cm.disponibile("a", "2026-07-01", "2026-07-03"))
        self.assertIsNone(self.cm.disponibile("a", "bad", "bad"))
        # giorno non caricato -> non disponibile (fail-closed)
        self.assertFalse(self.cm.disponibile("a", "2026-07-01", "2026-07-10"))


class TestBlocco(unittest.TestCase):
    def setUp(self):
        self.cm = _cm()
        _carica(self.cm, unita=1)

    def test_blocco_ok_scala(self):
        e = self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertTrue(e.ok)
        self.assertEqual(self.cm.stato_giorno("a", "2026-07-01")["unita_occupate"], 1)
        self.assertFalse(self.cm.disponibile("a", "2026-07-01", "2026-07-02"))

    def test_idempotenza_replay(self):
        e1 = self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        e2 = self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertTrue(e1.ok and e2.ok)
        self.assertTrue(e2.idempotente)
        # NON scala due volte
        self.assertEqual(self.cm.stato_giorno("a", "2026-07-01")["unita_occupate"], 1)

    def test_rifiuto_pieno(self):
        self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        e = self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k2")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "pieno")

    def test_rifiuto_chiuso(self):
        self.cm.applica_comando("CHIUDI a 2026-07-01")
        e = self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "chiuso")

    def test_rifiuto_min_notti(self):
        cm = _cm()
        _carica(cm, unita=1, min_notti=2)
        e = cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")  # 1 notte
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "min_notti")

    def test_rifiuto_giorno_non_caricato(self):
        e = self.cm.blocca("a", "2026-08-01", "2026-08-02", idem_key="k1")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "giorno_non_caricato")

    def test_date_non_valide(self):
        e = self.cm.blocca("a", "2026-07-03", "2026-07-01", idem_key="k1")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "date_non_valide")

    def test_idem_key_mancante(self):
        e = self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="")
        self.assertFalse(e.ok)

    def test_multinotte_all_or_nothing(self):
        cm = _cm()
        # notte 1 libera, notte 2 piena
        cm.imposta_disponibilita("a", "2026-07-01", unita_totali=1, prezzo_netto_cents=100)
        cm.imposta_disponibilita("a", "2026-07-02", unita_totali=1, prezzo_netto_cents=100)
        cm.blocca("a", "2026-07-02", "2026-07-03", idem_key="occupa2")  # riempi notte 2
        e = cm.blocca("a", "2026-07-01", "2026-07-03", idem_key="k1")   # spana 1+2
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "pieno")
        # notte 1 NON deve essere stata scalata (atomicita')
        self.assertEqual(cm.stato_giorno("a", "2026-07-01")["unita_occupate"], 0)


class TestRilascioEsterno(unittest.TestCase):
    def setUp(self):
        self.cm = _cm()
        _carica(self.cm, unita=1)

    def test_rilascio_libera(self):
        self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        e = self.cm.rilascia("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertTrue(e.ok)
        self.assertEqual(self.cm.stato_giorno("a", "2026-07-01")["unita_occupate"], 0)
        self.assertTrue(self.cm.disponibile("a", "2026-07-01", "2026-07-02"))

    def test_rilascio_idempotente(self):
        self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.cm.rilascia("a", "2026-07-01", "2026-07-02", idem_key="k1")
        e = self.cm.rilascia("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertTrue(e.idempotente)
        self.assertEqual(self.cm.stato_giorno("a", "2026-07-01")["unita_occupate"], 0)

    def test_rilascio_senza_blocco(self):
        e = self.cm.rilascia("a", "2026-07-01", "2026-07-02", idem_key="mai")
        self.assertFalse(e.ok)
        self.assertEqual(e.motivo, "blocco_inesistente")

    def test_evento_esterno_anti_overbooking(self):
        # una prenotazione da un'altra OTA consuma l'unica unita' -> la nostra rifiuta
        e_ext = self.cm.registra_evento_esterno("a", "2026-07-01", "2026-07-02",
                                                idem_key="BK123", fonte="booking")
        self.assertTrue(e_ext.ok)
        e_noi = self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="nostra")
        self.assertFalse(e_noi.ok)
        self.assertEqual(e_noi.motivo, "pieno")

    def test_evento_esterno_idempotente(self):
        self.cm.registra_evento_esterno("a", "2026-07-01", "2026-07-02",
                                        idem_key="BK1", fonte="booking")
        e = self.cm.registra_evento_esterno("a", "2026-07-01", "2026-07-02",
                                            idem_key="BK1", fonte="booking")
        self.assertTrue(e.idempotente)
        self.assertEqual(self.cm.stato_giorno("a", "2026-07-01")["unita_occupate"], 1)


class TestComandi(unittest.TestCase):
    def setUp(self):
        self.cm = _cm()

    def test_parser_valido(self):
        c = interpreta_comando("CHIUDI casa 2026-07-01")
        self.assertEqual((c.azione, c.alloggio_id, c.giorno), ("chiudi", "casa", "2026-07-01"))
        d = interpreta_comando("DISPO casa 2026-07-01 5")
        self.assertEqual((d.azione, d.valore), ("dispo", 5))

    def test_parser_robusto(self):
        for bad in (None, 123, "", "CHIUDI", "DISPO casa 2026-07-01 abc",
                    "CHIUDI casa data-storta", "PIPPO casa 2026-07-01"):
            self.assertIsNone(interpreta_comando(bad))

    def test_applica_dispo_e_prezzo(self):
        self.assertTrue(self.cm.applica_comando("DISPO a 2026-07-01 4").ok)
        self.assertTrue(self.cm.applica_comando("PREZZO a 2026-07-01 13000").ok)
        s = self.cm.stato_giorno("a", "2026-07-01")
        self.assertEqual((s["unita_totali"], s["prezzo_netto_cents"]), (4, 13000))

    def test_applica_chiudi_apri(self):
        _carica(self.cm, unita=1, giorni=("2026-07-01",))
        self.assertTrue(self.cm.applica_comando("CHIUDI a 2026-07-01").ok)
        self.assertFalse(self.cm.disponibile("a", "2026-07-01", "2026-07-02"))
        self.assertTrue(self.cm.applica_comando("APRI a 2026-07-01").ok)
        self.assertTrue(self.cm.disponibile("a", "2026-07-01", "2026-07-02"))

    def test_comando_ignoto(self):
        e = self.cm.applica_comando("BLABLA")
        self.assertFalse(e.ok)
        self.assertEqual(e.azione, "ignoto")


class TestNotifica(unittest.TestCase):
    def test_notifica_su_nuovo_blocco(self):
        ricevute = []
        cm = crea_channel_manager(notificatore=ricevute.append)
        _carica(cm, unita=1)
        cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertEqual(len(ricevute), 1)
        self.assertEqual(ricevute[0]["tipo"], "nuova_prenotazione")
        # replay: NESSUNA nuova notifica
        cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertEqual(len(ricevute), 1)

    def test_notifica_isolata_se_solleva(self):
        def boom(_):
            raise RuntimeError("canale giu'")
        cm = crea_channel_manager(notificatore=boom)
        _carica(cm, unita=1)
        e = cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="k1")
        self.assertTrue(e.ok)  # la prenotazione resta valida nonostante la notifica giu'


class TestStressOverbooking(unittest.TestCase):
    def test_nessuna_doppia_vendita_10x(self):
        """10 ripetizioni: 1 unita', 24 thread prenotano la STESSA notte -> 1 solo ok."""
        for rip in range(10):
            d = tempfile.mkdtemp()
            try:
                path = os.path.join(d, f"cm{rip}.db")
                cm = crea_channel_manager(path)
                cm.imposta_disponibilita("a", "2026-07-01", unita_totali=1,
                                         prezzo_netto_cents=10000)
                esiti = []
                lock = threading.Lock()

                def prenota(i):
                    e = cm.blocca("a", "2026-07-01", "2026-07-02", idem_key=f"key-{i}")
                    with lock:
                        esiti.append(e)

                th = [threading.Thread(target=prenota, args=(i,)) for i in range(24)]
                for t in th:
                    t.start()
                for t in th:
                    t.join()

                ok = [e for e in esiti if e.ok]
                self.assertEqual(len(ok), 1, f"rip {rip}: attesi 1 ok, trovati {len(ok)}")
                self.assertEqual(cm.stato_giorno("a", "2026-07-01")["unita_occupate"], 1)
                self.assertTrue(all(e.motivo == "pieno" for e in esiti if not e.ok))
            finally:
                shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
