"""
Test Fase 34 / Tavola VIP - Motore Prenotazioni (overlap + atomica).

Cuore della correttezza: la guardia ANTI-DOPPIA-PRENOTAZIONE (overlap a intervalli
semi-aperti) su tutti i casi limite, l'atomicita' della create (prenotazione +
split + escrow), il denaro esatto in centesimi, l'annullamento che libera il
tavolo, la conferma pagamento idempotente, e la mutua esclusione sotto concorrenza.
"""
import os
import sqlite3
import tempfile
import threading
import unittest

from fase34_prenotazioni import (MotorePrenotazioni, RichiestaPrenotazione,
                                 EsitoPrenotazione)


def _richiesta(ci, co, alloggio="tavolo-1", totale=10000, commissione=1000):
    return RichiestaPrenotazione(
        alloggio_id=alloggio, ospite_nome="Mario", ospite_email="m@x.it",
        check_in=ci, check_out=co, importo_totale_cents=totale,
        commissione_cents=commissione)


class _Base(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.motore = MotorePrenotazioni(lambda: sqlite3.connect(self.path, timeout=30))
        self.motore.inizializza_schema()
    def tearDown(self):
        for ext in ("", "-wal", "-shm", "-journal"):
            try:
                os.remove(self.path + ext)
            except OSError:
                pass
    def _conta(self, tabella):
        c = sqlite3.connect(self.path)
        try:
            return c.execute(f"SELECT COUNT(*) FROM {tabella}").fetchone()[0]
        finally:
            c.close()


class TestCreaEDenaro(_Base):
    def test_crea_ok_scrive_split_ed_escrow(self):
        e = self.motore.crea(_richiesta("2026-08-10", "2026-08-15"))
        self.assertTrue(e.ok)
        self.assertEqual(e.motivo, "creata")
        self.assertEqual(e.stato, "in_attesa_pagamento")
        self.assertEqual(self._conta("prenotazioni"), 1)
        self.assertEqual(self._conta("pagamenti_split"), 1)
        self.assertEqual(self._conta("escrow_fondi"), 1)

    def test_split_quadra_in_centesimi(self):
        self.motore.crea(_richiesta("2026-08-10", "2026-08-15",
                                    totale=15050, commissione=1505))
        c = sqlite3.connect(self.path)
        row = c.execute("SELECT importo_totale, commissione_tavola, quota_partner "
                        "FROM pagamenti_split").fetchone()
        c.close()
        self.assertEqual(row[0], 15050)
        self.assertEqual(row[1] + row[2], row[0])  # quadra

    def test_date_non_valide(self):
        self.assertEqual(self.motore.crea(_richiesta("2026-08-15", "2026-08-10")).motivo,
                         "date_non_valide")
        self.assertEqual(self.motore.crea(_richiesta("2026-08-10", "2026-08-10")).motivo,
                         "date_non_valide")  # zero notti
        self.assertEqual(self.motore.crea(_richiesta("non-data", "2026-08-10")).motivo,
                         "date_non_valide")

    def test_importi_non_validi(self):
        # commissione > totale -> quota_partner negativa -> rifiutato, nessuna scrittura
        e = self.motore.crea(_richiesta("2026-08-10", "2026-08-12",
                                        totale=1000, commissione=2000))
        self.assertEqual(e.motivo, "importi_non_validi")
        self.assertEqual(self._conta("prenotazioni"), 0)


class TestOverlap(_Base):
    """La guardia anti-doppia-prenotazione su tutti i casi limite."""
    def setUp(self):
        super().setUp()
        self.assertTrue(self.motore.crea(_richiesta("2026-08-10", "2026-08-15")).ok)

    def _prova(self, ci, co):
        return self.motore.crea(_richiesta(ci, co))

    def test_sovrapposizione_parziale_sinistra(self):
        self.assertEqual(self._prova("2026-08-08", "2026-08-12").motivo, "non_disponibile")

    def test_sovrapposizione_parziale_destra(self):
        self.assertEqual(self._prova("2026-08-13", "2026-08-18").motivo, "non_disponibile")

    def test_contenuta(self):
        self.assertEqual(self._prova("2026-08-11", "2026-08-13").motivo, "non_disponibile")

    def test_identica(self):
        self.assertEqual(self._prova("2026-08-10", "2026-08-15").motivo, "non_disponibile")

    def test_contenitore(self):
        self.assertEqual(self._prova("2026-08-09", "2026-08-16").motivo, "non_disponibile")

    def test_turnover_stesso_giorno_prima_e_dopo_ok(self):
        # check-out 10 -> nuovo check-in 10 NON e' conflitto (intervallo semi-aperto)
        self.assertTrue(self._prova("2026-08-05", "2026-08-10").ok)   # finisce dove inizia
        self.assertTrue(self._prova("2026-08-15", "2026-08-20").ok)   # inizia dove finisce

    def test_altro_tavolo_non_in_conflitto(self):
        e = self.motore.crea(_richiesta("2026-08-10", "2026-08-15", alloggio="tavolo-2"))
        self.assertTrue(e.ok)

    def test_annullata_libera_il_tavolo(self):
        # annullo la prenotazione esistente -> ora le stesse date sono libere
        pren = sqlite3.connect(self.path).execute(
            "SELECT id FROM prenotazioni LIMIT 1").fetchone()[0]
        self.assertTrue(self.motore.annulla(pren))
        self.assertTrue(self._prova("2026-08-10", "2026-08-15").ok)


class TestConfermaEAnnulla(_Base):
    def test_conferma_pagamento_idempotente(self):
        e = self.motore.crea(_richiesta("2026-08-10", "2026-08-12"))
        pren1 = self.motore.conferma_pagamento(e.pagamento_id)
        pren2 = self.motore.conferma_pagamento(e.pagamento_id)  # ripetuta
        self.assertEqual(pren1, e.prenotazione_id)
        self.assertEqual(pren2, e.prenotazione_id)
        st = self.motore.stato(e.prenotazione_id)
        self.assertEqual(st["stato"], "pagata")
        self.assertEqual(st["status"], "paid")

    def test_conferma_pagamento_inesistente(self):
        self.assertIsNone(self.motore.conferma_pagamento(99999))

    def test_pagata_resta_bloccante(self):
        e = self.motore.crea(_richiesta("2026-08-10", "2026-08-12"))
        self.motore.conferma_pagamento(e.pagamento_id)
        # stesse date, ora 'pagata' -> ancora non disponibile
        self.assertEqual(self.motore.crea(_richiesta("2026-08-10", "2026-08-12")).motivo,
                         "non_disponibile")

    def test_annulla_solo_in_attesa(self):
        e = self.motore.crea(_richiesta("2026-08-10", "2026-08-12"))
        self.motore.conferma_pagamento(e.pagamento_id)  # ora 'pagata'
        self.assertFalse(self.motore.annulla(e.prenotazione_id))  # non annullabile


class TestScadenzaHold(_Base):
    """Un hold non pagato libera il tavolo dopo il TTL (niente blocco a vita)."""
    def _invecchia(self, pren_id, iso="2000-01-01T00:00:00"):
        c = sqlite3.connect(self.path)
        c.execute("UPDATE prenotazioni SET data_creazione=? WHERE id=?", (iso, pren_id))
        c.commit(); c.close()

    def test_hold_scaduto_non_blocca(self):
        e = self.motore.crea(_richiesta("2027-01-10", "2027-01-15"))
        self.assertEqual(self.motore.crea(_richiesta("2027-01-10", "2027-01-15")).motivo,
                         "non_disponibile")          # hold fresco: blocca
        self._invecchia(e.prenotazione_id)
        self.assertTrue(self.motore.crea(_richiesta("2027-01-10", "2027-01-15")).ok)  # scaduto: libero

    def test_libera_hold_scaduti(self):
        e = self.motore.crea(_richiesta("2027-02-10", "2027-02-12"))
        self._invecchia(e.prenotazione_id)
        self.assertEqual(self.motore.libera_hold_scaduti(), 1)
        self.assertEqual(self.motore.stato(e.prenotazione_id)["stato"], "scaduta")
        self.assertEqual(self.motore.libera_hold_scaduti(), 0)  # idempotente

    def test_pagato_non_scade(self):
        e = self.motore.crea(_richiesta("2027-03-10", "2027-03-12"))
        self.motore.conferma_pagamento(e.pagamento_id)
        self._invecchia(e.prenotazione_id)
        self.assertEqual(self.motore.libera_hold_scaduti(), 0)   # i pagati non scadono
        self.assertEqual(self.motore.crea(_richiesta("2027-03-10", "2027-03-12")).motivo,
                         "non_disponibile")

    def test_conferma_hold_scaduto_ma_libero(self):
        e = self.motore.crea(_richiesta("2027-04-10", "2027-04-12"))
        self._invecchia(e.prenotazione_id)              # scaduto ma slot ancora libero
        self.assertEqual(self.motore.conferma_pagamento(e.pagamento_id), e.prenotazione_id)
        self.assertEqual(self.motore.stato(e.prenotazione_id)["stato"], "pagata")

    def test_conferma_su_conflitto_ritorna_none(self):
        a = self.motore.crea(_richiesta("2027-05-10", "2027-05-12"))
        self._invecchia(a.prenotazione_id)
        b = self.motore.crea(_richiesta("2027-05-10", "2027-05-12"))  # slot libero -> ok
        self.assertTrue(b.ok)
        self.motore.conferma_pagamento(b.pagamento_id)               # B paga e blocca
        self.assertIsNone(self.motore.conferma_pagamento(a.pagamento_id))  # A in conflitto


class TestConcorrenza(_Base):
    def test_doppia_prenotazione_stesso_tavolo_solo_una_passa(self):
        risultati = []
        def prova():
            risultati.append(self.motore.crea(_richiesta("2026-08-10", "2026-08-15")).ok)
        ts = [threading.Thread(target=prova) for _ in range(12)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertEqual(sum(1 for x in risultati if x), 1)   # ESATTAMENTE una
        self.assertEqual(self._conta("prenotazioni"), 1)


if __name__ == "__main__":
    unittest.main()
