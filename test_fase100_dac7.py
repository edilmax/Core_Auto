"""Test Fase 100 - DAC7 gate. Puro + durevole; nessuna rete."""
import os
import tempfile
import unittest

from fase100_dac7 import (ConfigDAC7, RegistroDAC7, ReportDAC7, crea_registro_dac7,
                          valuta_dac7)

ON = ConfigDAC7(attivo=True)


class TestValuta(unittest.TestCase):
    def test_gated_off_nessuna_azione(self):
        r = valuta_dac7(100, 999999, False)            # default attivo=False
        self.assertFalse(r.sospendi_annuncio)
        self.assertFalse(r.blocca_payout)

    def test_sotto_soglia_ok(self):
        r = valuta_dac7(5, 50000, False, ON)
        self.assertFalse(r.gate_attivo)
        self.assertFalse(r.deve_segnalare)

    def test_gate_sicurezza_prenotazioni(self):
        r = valuta_dac7(28, 0, False, ON)
        self.assertTrue(r.gate_attivo)
        self.assertTrue(r.sospendi_annuncio)
        self.assertTrue(r.blocca_payout)

    def test_gate_sicurezza_ricavi(self):
        self.assertTrue(valuta_dac7(1, 180000, False, ON).blocca_payout)

    def test_dati_forniti_sblocca(self):
        r = valuta_dac7(40, 300000, True, ON)
        self.assertFalse(r.sospendi_annuncio)
        self.assertTrue(r.deve_segnalare)              # obbligo di report resta

    def test_soglia_legale_segnalazione(self):
        self.assertTrue(valuta_dac7(30, 0, True, ON).deve_segnalare)
        self.assertTrue(valuta_dac7(0, 200000, True, ON).deve_segnalare)

    def test_input_invalido_failsafe(self):
        r = valuta_dac7("x", None, "y", ON)
        self.assertEqual(r.prenotazioni, 0)
        self.assertEqual(r.ricavi_cents, 0)


class TestRegistro(unittest.TestCase):
    def test_conteggio_e_gate_memoria(self):
        reg = crea_registro_dac7(cfg=ON)
        for _ in range(28):
            reg.registra_prenotazione("h1", 1000)
        self.assertFalse(reg.visibile("h1"))
        self.assertFalse(reg.payout_consentito("h1"))
        reg.imposta_dati_fiscali("h1")
        self.assertTrue(reg.visibile("h1"))
        self.assertTrue(reg.payout_consentito("h1"))

    def test_durevole_file_atomico(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "dac7.json")
        r1 = RegistroDAC7(p, ON)
        for _ in range(28):
            r1.registra_prenotazione("h2", 1000)
        self.assertFalse(RegistroDAC7(p, ON).visibile("h2"))   # ricaricato
        os.remove(p)
        os.rmdir(d)

    def test_host_sconosciuto_ok(self):
        self.assertTrue(crea_registro_dac7(cfg=ON).visibile("ignoto"))


class TestArchivioMalformatoNonEsplode(unittest.TestCase):
    """DIFETTI PROVATI VIVI il 2026-07-31 sul codice di allora, eseguendo, non deducendo:

      · archivio JSON valido ma NON un oggetto (`[1, 2, 3]` — riparazione a mano, versione
        vecchia, troncamento): `_leggi` lo restituiva tale e quale e la prima `.get(...)`
        usciva come `AttributeError: 'list' object has no attribute 'get'`;
      · record senza il campo `pren` -> `KeyError: 'pren'` da `registra_prenotazione`;
      · record con `"pren": "tanti"` -> `ValueError: invalid literal for int()`.

    Chi esplodeva erano i due SCRITTORI (`registra_prenotazione`, `imposta_dati_fiscali`), non
    i lettori: `valuta_dac7` filtrava gia' i tipi. E' il registro DAC7, cioe' un adempimento
    fiscale: un'eccezione qui ferma la registrazione di una prenotazione VERA.
    """

    def _reg(self, contenuto):
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        p = os.path.join(d, "dac7.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write(contenuto)
        return p

    def test_json_valido_ma_non_oggetto_si_degrada_a_vuoto(self):
        p = self._reg("[1, 2, 3]")
        st = RegistroDAC7(p).stato("h1")
        self.assertEqual((st.prenotazioni, st.ricavi_cents), (0, 0))

    def test_record_senza_campi_si_puo_ancora_SCRIVERE(self):
        p = self._reg('{"h1": {"ricavi": 500}}')
        RegistroDAC7(p).registra_prenotazione("h1", 1000)
        st = RegistroDAC7(p).stato("h1")
        self.assertEqual(st.prenotazioni, 1)

    def test_campo_di_tipo_sbagliato_ripiega_sul_neutro(self):
        p = self._reg('{"h1": {"pren": "tanti", "ricavi": null, "dati": false}}')
        RegistroDAC7(p).registra_prenotazione("h1", 1000)
        st = RegistroDAC7(p).stato("h1")
        self.assertEqual((st.prenotazioni, st.ricavi_cents), (1, 1000))

    def test_un_conteggio_NEGATIVO_non_sopravvive(self):
        """Un numero negativo di prenotazioni abbasserebbe la soglia DAC7: si azzera."""
        p = self._reg('{"h1": {"pren": -5, "ricavi": -900, "dati": false}}')
        st = RegistroDAC7(p).stato("h1")
        self.assertEqual((st.prenotazioni, st.ricavi_cents), (0, 0))

    def test_il_booleano_non_passa_per_un_numero(self):
        """In Python `True` E' un intero: senza il controllo esplicito, `"pren": true`
        varrebbe 1 prenotazione nata dal nulla."""
        p = self._reg('{"h1": {"pren": true, "ricavi": 0, "dati": false}}')
        st = RegistroDAC7(p).stato("h1")
        self.assertEqual(st.prenotazioni, 0)

    def test_un_archivio_SANO_non_viene_toccato(self):
        """L'altra direzione: la normalizzazione non deve riscrivere i dati buoni."""
        p = self._reg('{"h1": {"pren": 7, "ricavi": 123456, "dati": true}}')
        st = RegistroDAC7(p).stato("h1")
        self.assertEqual((st.prenotazioni, st.ricavi_cents, st.dati_forniti),
                         (7, 123456, True))


if __name__ == "__main__":
    unittest.main()
