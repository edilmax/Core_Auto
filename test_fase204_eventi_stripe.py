"""Test dedicato di fase204 (l'archivio degli eventi Stripe), nato il 23/11 con
`corpi_del_fatto`: la lettura con cui l'arbitro sa COME la banca ha chiuso una contestazione
(TLA+ 22/11). Le altre letture dell'archivio hanno le loro prove in `test_webhook_dedup_fatto`
e `test_webhook_evento_archiviato`; qui c'e' il test che il giudice delle mutazioni accende per
primo (`collaudi/mutazione_prodotto.py`: «test_» + nome del modulo)."""
import sqlite3
import unittest

from fase204_eventi_stripe import ArchivioEventiStripe, crea_archivio_eventi


class TestICorpiDelFatto(unittest.TestCase):
    def setUp(self):
        self.ora = {"t": 100}
        self.a = crea_archivio_eventi(":memory:", orologio=lambda: self.ora["t"])
        self.a.inizializza_schema()

    def _salva(self, evt, tipo, oggetto, corpo, t):
        self.ora["t"] = t
        self.assertTrue(self.a.salva(evt, tipo=tipo, corpo_json=corpo, oggetto_id=oggetto))

    def test_tutti_i_corpi_del_fatto_dal_piu_vecchio_e_solo_quelli(self):
        self._salva("evt_b", "charge.dispute.closed", "dp_1", '{"n": 2}', 200)
        self._salva("evt_a", "charge.dispute.closed", "dp_1", '{"n": 1}', 100)
        self._salva("evt_c", "charge.dispute.created", "dp_1", '{"altro": "tipo"}', 50)
        self._salva("evt_d", "charge.dispute.closed", "dp_2", '{"altra": "contestazione"}', 50)
        self.assertEqual(['{"n": 1}', '{"n": 2}'],
                         self.a.corpi_del_fatto(tipo="charge.dispute.closed", oggetto_id="dp_1"))

    def test_a_parita_di_ora_decide_l_identificativo(self):
        self._salva("evt_z", "charge.dispute.closed", "dp_1", "z", 100)
        self._salva("evt_y", "charge.dispute.closed", "dp_1", "y", 100)
        self.assertEqual(["y", "z"],
                         self.a.corpi_del_fatto(tipo="charge.dispute.closed", oggetto_id="dp_1"))

    def test_conta_anche_un_evento_non_ancora_elaborato(self):
        # la firma lo ha gia' giudicato prima del salvataggio: COME ha chiuso la banca vale
        # anche se la risposta 2xx non e' stata ancora segnata
        self._salva("evt_1", "charge.dispute.closed", "dp_1", "corpo", 100)
        self.assertFalse(self.a.elaborato("evt_1"))
        self.assertEqual(["corpo"],
                         self.a.corpi_del_fatto(tipo="charge.dispute.closed", oggetto_id="dp_1"))

    def test_nessun_evento_lista_vuota(self):
        self.assertEqual([], self.a.corpi_del_fatto(tipo="charge.dispute.closed",
                                                    oggetto_id="dp_mai_visto"))

    def test_oggetto_vuoto_o_non_stringa_lista_vuota(self):
        self._salva("evt_1", "charge.dispute.closed", "", "senza oggetto", 100)
        for oggetto in ("", "   ", None, 7):
            with self.subTest(oggetto=oggetto):
                self.assertEqual([], self.a.corpi_del_fatto(tipo="charge.dispute.closed",
                                                            oggetto_id=oggetto))

    def test_un_guasto_dell_archivio_non_diventa_lista_vuota(self):
        # [] direbbe «nessun avviso» e l'arbitro deciderebbe; il guasto deve arrivare a chi chiama
        def rotto():
            raise sqlite3.OperationalError("database is locked")
        a = ArchivioEventiStripe(rotto)
        with self.assertRaises(sqlite3.OperationalError):
            a.corpi_del_fatto(tipo="charge.dispute.closed", oggetto_id="dp_1")


if __name__ == "__main__":
    unittest.main()
