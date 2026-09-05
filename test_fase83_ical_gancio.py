"""
Test del GANCIO della difesa iCal in fase83 (2026-09-05, «autorizzato» del fondatore).

Le tre cose che il gancio in `fase83._book` e in `fase83._host_ical` deve fare, provate dalle
ROTTE VERE col banco dell'esame (`collaudi/esame_ical.py`): sul codice sano l'esame e' VERDE
(la prenotazione fantasma viene rifiutata: se il gancio smette di rileggere, qui e' rosso);
una rilettura che ESPLODE non ferma la prenotazione (fail-open dichiarato) e l'errore nel
registro porta la traccia vera; un alloggio non testuale nel salvataggio del feed e' un 422,
non un giro nel controllo di proprieta'.

E' l'occhio che il Giudice della mutazione usa sulle righe cambiate di `fase83_server.py`
(`--killer test_fase83_ical_gancio`): piccolo apposta, cosi' costa secondi per mutante.
"""
import contextlib
import importlib.util
import io
import os
import shutil
import tempfile
import unittest

import fase83_server  # noqa: F401 - e' il modulo sotto esame: il Giudice lo vede cosi'
import fase203_ical_orologio as m

QUI = os.path.dirname(os.path.abspath(__file__))


def _esame():
    spec = importlib.util.spec_from_file_location(
        "_esame_ical_gancio", os.path.join(QUI, "collaudi", "esame_ical.py"))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class TestIlGancioDellaDifesaICal(unittest.TestCase):

    def test_sul_codice_sano_l_esame_e_VERDE(self):
        """L'ALTRA DIREZIONE (ferrea 10): a macchina sana l'esame tace. Se il gancio di `_book`
        smette di rileggere il feed prima della conferma, la prenotazione fantasma passa e
        qui e' rosso."""
        esame = _esame()
        uscita = io.StringIO()
        with contextlib.redirect_stdout(uscita):
            codice = esame.main([])
        self.assertEqual(codice, 0, uscita.getvalue()[-1200:])
        self.assertFalse([p for p in esame.PASSI if not p[2]])

    def test_se_la_rilettura_esplode_la_prenotazione_passa_lo_stesso_e_resta_la_traccia(self):
        """ISOLAMENTO del gancio (fail-open, dichiarato): una rilettura che solleva non ferma
        la prenotazione, e l'errore nel registro porta LA COSA, del tipo giusto."""
        esame = _esame()
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        b = esame.Banco(d)
        vecchio = m.prima_di_confermare

        def esplode(*a, **k):
            raise RuntimeError("archivio dei feed in fiamme")
        m.prima_di_confermare = esplode
        try:
            ci, co = b.notti(12)
            with self.assertLogs("core_auto.server", level="ERROR") as registro:
                s, corpo = b.prenota(ci, co, "coraggioso@x.it")
        finally:
            m.prima_di_confermare = vecchio
        self.assertEqual(s, 201, corpo)
        errori = [r for r in registro.records
                  if "rilettura prima della conferma" in r.getMessage()]
        self.assertTrue(errori, [r.getMessage() for r in registro.records])
        self.assertIsInstance(errori[0].exc_info, tuple)
        self.assertIs(errori[0].exc_info[0], RuntimeError)

    def test_un_alloggio_non_testuale_nel_salvataggio_del_feed_e_un_422(self):
        """`isinstance(alloggio, str) AND alloggio`: con `or` un numero passerebbe al controllo
        di proprieta' invece di essere rifiutato subito."""
        esame = _esame()
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        b = esame.Banco(d)
        # Il motivo conta quanto lo stato: con `or` un 123 passerebbe la validazione e verrebbe
        # rifiutato DOPO dall'archivio (422 `url_non_valido`), un "" dal controllo di proprieta'.
        s, corpo = b.g("POST", "/api/host/ical", {"alloggio_id": 123, "url": esame.URL}, b.tk)
        self.assertEqual((s, (corpo or {}).get("errore")), (422, "campi_non_validi"), corpo)
        s2, corpo2 = b.g("POST", "/api/host/ical", {"alloggio_id": "", "url": esame.URL}, b.tk)
        self.assertEqual((s2, (corpo2 or {}).get("errore")), (422, "campi_non_validi"), corpo2)


if __name__ == "__main__":
    unittest.main()
