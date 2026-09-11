"""Promemoria post-check-in al cliente: dopo il check-in di una prenotazione PAGATA, il
cliente riceve 'tutto ok? / segnala un problema entro 24h'. Inviato UNA volta sola."""
import io
import os
import shutil
import sqlite3
import tempfile
import types
import unittest

from fase162_pagamenti_pendenti import crea_pagamenti_pendenti
from fase86_email import corpo_promemoria_checkin_html


class TestPromemoria(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.pp = crea_pagamenti_pendenti(os.path.join(self.dir, "p.db"))
        self.pp.inizializza_schema()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _prenota_pagata(self, ref, ci, email="cliente@x.it"):
        self.pp.registra(ref, alloggio_id="casa", check_in=ci, check_out="2026-12-31",
                         email=email, corpo_json='{"voucher_token":"vt.sig","titolo":"Casa Bella"}')
        self.pp.conferma(ref)     # -> 'pagato'

    def test_promemoria_solo_dopo_checkin(self):
        self._prenota_pagata("R1", "2026-01-10")           # check-in passato
        self._prenota_pagata("R2", "2099-01-01")           # check-in futuro
        da = self.pp.da_promemoriare(oggi="2026-06-01")
        refs = [r["riferimento"] for r in da]
        self.assertIn("R1", refs)                          # check-in arrivato
        self.assertNotIn("R2", refs)                       # troppo presto

    def test_inviato_una_volta_sola(self):
        self._prenota_pagata("R3", "2026-01-10")
        self.assertEqual(len(self.pp.da_promemoriare(oggi="2026-06-01")), 1)
        self.pp.segna_promemoria("R3")
        self.assertEqual(self.pp.da_promemoriare(oggi="2026-06-01"), [])   # non riappare

    def test_solo_pagate_con_email(self):
        # 'in_attesa' (non pagata) non riceve il promemoria
        self.pp.registra("R4", alloggio_id="casa", check_in="2026-01-10", check_out="2026-01-12",
                         email="a@b.it")
        self.assertEqual(self.pp.da_promemoriare(oggi="2026-06-01"), [])
        # pagata ma senza email -> niente promemoria
        self.pp.registra("R5", alloggio_id="casa", check_in="2026-01-10", check_out="2026-01-12")
        self.pp.conferma("R5")
        self.assertNotIn("R5", [r["riferimento"] for r in self.pp.da_promemoriare(oggi="2026-06-01")])

    def test_email_template_valido(self):
        html = corpo_promemoria_checkin_html("Casa Bella", "https://bookinvip.com/voucher/vt.sig", lingua="it")
        self.assertIn("Casa Bella", html)
        self.assertIn("24 ore", html)
        self.assertIn("Segnala un problema", html)
        self.assertIn("https://bookinvip.com/voucher/vt.sig", html)
        # XSS-safe
        h2 = corpo_promemoria_checkin_html("<script>x</script>", "")
        self.assertNotIn("<script>x", h2)


class TestIlPromemoriaArrivaDopoLArrivoENonSiPerde(unittest.TestCase):
    """⛔ D20, DUE DIFETTI VIVI sul giro che scrive al cliente «tutto ok? / segnala un problema
    entro 24 ore» (trovati l'11 settembre percorrendo la catena delle controversie). Misurati
    PRIMA di scrivere questa guardia:

    1. **Partiva PRIMA dell'arrivo.** Il giro sceglieva `check_in <= date.today()` (contenitore
       in UTC): dalla mezzanotte UTC del giorno del check-in. Con `_istante_checkin` su un check-in
       del 20/09: 13 ore prima dell'arrivo a Roma, 7 a Manila, 22 a Los Angeles, 27 senza fuso.
       Il testo dice «speriamo che il soggiorno stia andando bene» a chi non e' ancora entrato, e
       quando il cliente scopre un problema nessuno gli ricorda che puo' segnalarlo.
    2. **Un invio fallito risultava fatto.** `invia()` dice False senza sollevare, e il giro
       segnava il promemoria lo stesso: nessun ritentativo, e dopo 24 ore i soldi all'host in
       silenzio.

    ⛔ Questa guardia ESEGUE la passata vera (`fase83_server.promemoria_una_passata`) con un
    orologio iniettato, un archivio vero (`fase162`) e un provider finto che dice si', no o
    solleva. Non cerca parole nel sorgente: le soddisferebbe un commento (sbaglio S6).
    ⛔ E l'arrivo lo chiede alla STESSA funzione della garanzia (`_istante_checkin`): se la
    garanzia e il promemoria tornassero a usare due orologi diversi, la prima prova diventa rossa.
    """

    CI = "2026-09-20"
    FUSI = ("Europe/Rome", "Asia/Manila", "America/Los_Angeles", "Pacific/Kiritimati", "")

    class _Posta(object):
        """Il provider finto: ricorda cosa gli si chiede, e risponde si', no o solleva."""

        def __init__(self, esito=True):
            self.esito = esito
            self.inviate = []

        def invia(self, destinatario, oggetto, corpo_html):
            self.inviate.append((destinatario, oggetto))
            if isinstance(self.esito, Exception):
                raise self.esito
            return self.esito

    class _Router(object):
        """Il router finto: SOLO i due metodi che la passata usa. Che quelli veri esistano
        ancora lo pretende `test_PREMESSA_...` qui sotto."""

        def __init__(self, fuso):
            self.fuso = fuso

        def _fuso_alloggio(self, slug):
            return self.fuso

        def _lang_da_voucher(self, vt):
            return "it"

    def setUp(self):
        import fase83_server
        self.s = fase83_server
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _banco(self, nome, fuso="Europe/Rome", esito=True):
        pp = crea_pagamenti_pendenti(os.path.join(self.dir, nome + ".db"))
        pp.inizializza_schema()
        pp.registra("R-" + nome, alloggio_id="casa", check_in=self.CI, check_out="2026-09-25",
                    email="cliente@x.it",
                    corpo_json='{"voucher_token":"vt.sig","titolo":"Casa Bella"}')
        pp.conferma("R-" + nome)
        posta = self._Posta(esito)
        sistema = types.SimpleNamespace(pagamenti_pendenti=pp, email_provider=posta,
                                        config=types.SimpleNamespace(base_url="https://x"))
        return pp, posta, sistema, self._Router(fuso)

    @staticmethod
    def _in_coda(pp):
        """Le righe NON ancora segnate (con una data lontana, cosi' il filtro non nasconde niente)."""
        return [r["riferimento"] for r in pp.da_promemoriare(oggi="2099-01-01")]

    def _errori_durante(self, fare):
        """Esegue `fare()` e rende le righe di livello ERROR scritte dal server nel frattempo."""
        import logging
        righe = []

        class _Presa(logging.Handler):
            def emit(self, record):
                righe.append(record.getMessage())

        presa = _Presa(level=logging.ERROR)
        log = logging.getLogger("core_auto.server")
        log.addHandler(presa)
        try:
            fare()
        finally:
            log.removeHandler(presa)
        return righe

    def test_NON_PARTE_PRIMA_DELL_ARRIVO_IN_NESSUN_FUSO(self):
        for i, fuso in enumerate(self.FUSI):
            with self.subTest(fuso=fuso or "(fuso ignoto)"):
                nome = "fuso%d" % i
                pp, posta, sistema, router = self._banco(nome, fuso)
                arrivo = self.s._istante_checkin(self.CI, fuso)
                self.s.promemoria_una_passata(sistema, router, ora_ts=arrivo - 60)
                self.assertEqual(posta.inviate, [],
                                 "il promemoria e' partito PRIMA dell'arrivo (fuso %s): il cliente "
                                 "legge «com'e' andata?» quando non e' ancora entrato"
                                 % (fuso or "ignoto"))
                self.assertIn("R-" + nome, self._in_coda(pp),
                              "la riga e' stata segnata prima dell'arrivo: il promemoria non "
                              "partirebbe piu'")
                self.s.promemoria_una_passata(sistema, router, ora_ts=arrivo + 60)
                self.assertEqual(len(posta.inviate), 1,
                                 "passato l'arrivo il promemoria NON e' partito (fuso %s)"
                                 % (fuso or "ignoto"))
                self.assertNotIn("R-" + nome, self._in_coda(pp))

    def test_UN_INVIO_FALLITO_NON_RISULTA_FATTO_E_SI_RITENTA(self):
        pp, posta, sistema, router = self._banco("fallito", esito=False)
        arrivo = self.s._istante_checkin(self.CI, "Europe/Rome")
        self.s.promemoria_una_passata(sistema, router, ora_ts=arrivo + 60)
        self.assertEqual(len(posta.inviate), 1, "non ha nemmeno provato a spedire")
        self.assertIn("R-fallito", self._in_coda(pp),
                      "il provider ha detto NO e la riga risulta inviata: il cliente non riceve "
                      "niente e nessuno ritenta")
        posta.esito = True
        self.s.promemoria_una_passata(sistema, router, ora_ts=arrivo + 3660)
        self.assertEqual(len(posta.inviate), 2, "al giro dopo non ha ritentato")
        self.assertNotIn("R-fallito", self._in_coda(pp))

    def test_UN_ECCEZIONE_DEL_PROVIDER_NON_RISULTA_FATTA(self):
        pp, posta, sistema, router = self._banco("eccezione", esito=OSError("smtp giu'"))
        arrivo = self.s._istante_checkin(self.CI, "Europe/Rome")
        self.s.promemoria_una_passata(sistema, router, ora_ts=arrivo + 60)
        self.assertEqual(len(posta.inviate), 1, "non ha nemmeno provato a spedire")
        self.assertIn("R-eccezione", self._in_coda(pp),
                      "un'eccezione del provider e' stata segnata come invio riuscito")

    def test_A_FINESTRA_CHIUSA_SI_SMETTE_E_RESTA_SCRITTO(self):
        pp, posta, sistema, router = self._banco("chiusa", esito=False)
        arrivo = self.s._istante_checkin(self.CI, "Europe/Rome")
        errori = self._errori_durante(
            lambda: self.s.promemoria_una_passata(sistema, router, ora_ts=arrivo + 25 * 3600))
        self.assertEqual(posta.inviate, [],
                         "a finestra chiusa ha spedito «segnala entro 24 ore» quando le 24 ore "
                         "sono finite")
        self.assertNotIn("R-chiusa", self._in_coda(pp),
                         "a finestra chiusa la riga resta in coda: riproverebbe per sempre e "
                         "ruberebbe il posto ai clienti arrivati oggi")
        self.assertTrue(any("R-chiusa" in r for r in errori),
                        "il promemoria e' andato perso senza una riga d'ERRORE che lo dica: %r"
                        % errori)

    def test_PARTE_UNA_VOLTA_SOLA(self):
        pp, posta, sistema, router = self._banco("una", esito=True)
        arrivo = self.s._istante_checkin(self.CI, "Europe/Rome")
        for giro in range(3):
            self.s.promemoria_una_passata(sistema, router, ora_ts=arrivo + 60 + giro * 3600)
        self.assertEqual(len(posta.inviate), 1, "il promemoria e' partito piu' di una volta")

    def test_PREMESSA_IL_GIRO_DEL_SERVER_CHIAMA_QUESTA_PASSATA(self):
        """Se il thread del server tenesse una SUA copia della logica, le prove qui sopra
        misurerebbero una funzione che la produzione non esegue."""
        import re
        with io.open(self.s.__file__, encoding="utf-8") as f:
            sorgente = f.read()
        m = re.search(r"def _tick_promemoria\(\):(.+?)\n        _th", sorgente, re.S)
        self.assertIsNotNone(m, "il giro _tick_promemoria non si trova piu'")
        corpo = "\n".join(r for r in m.group(1).splitlines()
                          if r.strip() and not r.strip().startswith("#"))
        self.assertIn("promemoria_una_passata(sistema, router)", corpo,
                      "il giro del server non chiama la passata provata qui")
        self.assertNotIn("segna_promemoria", corpo,
                         "il giro del server ha ancora una SUA copia della logica")
        for metodo in ("_fuso_alloggio", "_lang_da_voucher"):
            self.assertTrue(callable(getattr(self.s.RouterHTTP, metodo, None)),
                            "RouterHTTP non ha piu' %s: il router finto di questa guardia non "
                            "somiglia piu' a quello vero" % metodo)


if __name__ == "__main__":
    unittest.main()
