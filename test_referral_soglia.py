"""Collaudo ramo REFERRAL (2026-07-16, metodo libro) — soglia '==' fragile.

BUG: `_forse_qualifica_referral` premiava il referente SOLO se `conta_pagati == soglia`
ESATTO. Due webhook CONCORRENTI (3a e 4a prenotazione pagate nello stesso istante)
aggiornano entrambi il payout a 'maturato' PRIMA che uno dei due conti -> entrambi
contano 4 -> la finestra '==3' e' persa PER SEMPRE e il premio (€40) non scatta mai.
Il "una volta sola" e' gia' garantito dallo store (fase76.qualifica_referee: BEGIN
IMMEDIATE + dedup 'gia_qualificato') -> il fix e' `>=`: si recupera al pagamento
successivo e il dedup impedisce il doppio premio.
"""
import shutil
import tempfile
import unittest

from fase76_viral_loop import crea_viral_loop


class _PayoutFinto:
    def __init__(self, n):
        self.n = n

    def conta_pagati(self, host_id):
        return self.n


class _Cfg:
    referral_soglia_prenotazioni = 3
    referral_premio_cents = 4000


class _SysFinto:
    def __init__(self, viral):
        self.viral = viral
        self.config = _Cfg()


class TestReferralSoglia(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.viral = crea_viral_loop(self.dir + r"\v.db", b"S" * 32)
        cod = self.viral.genera_codice("referente1")
        self.assertTrue(cod)
        self.assertTrue(self.viral.registra_referee(cod, "invitato1").ok)
        # la registrazione stessa accredita un benvenuto al referente: misuro i DELTA
        self.base = self.viral.credito_disponibile("referente1")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _qualifica(self, n_pagate):
        from fase83_server import RouterHTTP
        r = RouterHTTP.__new__(RouterHTTP)          # solo il metodo sotto test
        r._sys = _SysFinto(self.viral)
        r._forse_qualifica_referral("invitato1", _PayoutFinto(n_pagate))

    def test_finestra_saltata_recupera(self):
        # scenario della GARA: il conteggio ha gia' superato la soglia (==3 mai visto)
        self._qualifica(4)
        self.assertEqual(self.viral.credito_disponibile("referente1") - self.base, 4000,
                         "soglia SUPERATA (non ==): il premio deve scattare lo stesso")

    def test_mai_doppio_premio(self):
        self._qualifica(3)
        self.assertEqual(self.viral.credito_disponibile("referente1") - self.base, 4000)
        self._qualifica(4)                          # pagamento successivo: dedup
        self._qualifica(5)
        self.assertEqual(self.viral.credito_disponibile("referente1") - self.base, 4000,
                         "il dedup dello store deve impedire il doppio premio")

    def test_sotto_soglia_niente_premio(self):
        self._qualifica(2)
        self.assertEqual(self.viral.credito_disponibile("referente1") - self.base, 0)


class TestCreditoReferralPersoInSilenzio(unittest.TestCase):
    """IL CREDITO DELL'HOST NON PUO' SPARIRE SENZA CHE NESSUNO LO SAPPIA.

    `_applica_credito_host` fa DUE passi che non sono atomici:
      1. `viral.usa_credito()` -> il credito e' scalato e **COMMITTATO** nel database;
      2. `payout.aumenta_payout()` -> l'host incassa di piu'.
    Se il passo 2 esplode, il passo 1 e' gia' scritto: il credito e' BRUCIATO e l'host non
    ha ricevuto NULLA. Paga la commissione piena E ha perso i 40 euro che si era guadagnato
    portando un altro host. Con un semplice `logger.warning`.

    E' il difetto piu' grave della giornata perche' e' l'unico in cui a perderci non siamo
    noi ma L'HOST -- ed e' la promessa su cui si regge il passaparola.

    Perche' NON si inverte l'ordine: se prima si aumenta il payout e poi fallisce il
    consumo, l'host tiene sia lo sconto sia il credito -> ci perdiamo noi. Nessun ordine e'
    sicuro senza un'azione di compensazione che RESTITUISCA il credito -- codice nuovo in un
    modulo che muove denaro, registrato come candidato. Il rimedio proporzionato e' rendere
    il guasto UDIBILE e RIPARABILE A MANO: serve sapere QUALE host e QUANTI centesimi.

    VISTO ROSSO: col vecchio warning non esce nessun ERROR.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.viral = crea_viral_loop(self.dir + r"\v.db", b"S" * 32)
        cod = self.viral.genera_codice("referente1")
        self.viral.registra_referee(cod, "invitato1")     # accredita il benvenuto

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _router(self, payout):
        from fase83_server import RouterHTTP
        r = RouterHTTP.__new__(RouterHTTP)
        sis = _SysFinto(self.viral)
        sis.payout = payout
        r._sys = sis
        return r

    def test_credito_bruciato_e_sconto_non_applicato_e_un_ERRORE(self):
        class _PayoutRotto:
            def aumenta_payout(self, *a, **k):
                raise RuntimeError("payout non scrivibile")
        prima = self.viral.credito_disponibile("referente1")
        self.assertGreater(prima, 0, "setup: il referente deve avere credito")
        r = self._router(_PayoutRotto())
        with self.assertLogs("core_auto", level="ERROR") as reg:
            r._applica_credito_host("rif-1", "referente1", 100000)
        dopo = self.viral.credito_disponibile("referente1")
        self.assertLess(dopo, prima, "setup: il credito DEVE essere stato bruciato")
        unito = " ".join(reg.output)
        self.assertIn("referente1", unito,
                      "l'errore non dice QUALE host ha perso il credito: %r" % (reg.output,))
        self.assertIn(str(prima - dopo), unito,
                      "l'errore non dice QUANTI centesimi sono spariti (%d): %r"
                      % (prima - dopo, reg.output))

    def test_applicazione_RIUSCITA_non_scrive_errori(self):
        """Prova di rimozione: percorso sano -> nessun ERROR, o diventa rumore quotidiano."""
        import logging
        visti = []

        class _Spia(logging.Handler):
            def emit(self, rec):
                if rec.levelno >= logging.ERROR:
                    visti.append(rec.getMessage())

        class _PayoutOk:
            def aumenta_payout(self, *a, **k):
                return True
        lg = logging.getLogger("core_auto")
        h = _Spia(); lg.addHandler(h); self.addCleanup(lambda: lg.removeHandler(h))
        usato = self._router(_PayoutOk())._applica_credito_host("rif-2", "referente1", 100000)
        self.assertGreater(usato, 0, "setup: il credito doveva essere applicato")
        self.assertEqual(visti, [], "grida su un'applicazione riuscita: %r" % (visti,))

    def test_premio_al_referente_fallito_e_un_ERRORE(self):
        """Il premio ha un recupero (riprova a ogni pagamento successivo), ma un guasto
        PERSISTENTE resterebbe invisibile: va comunque detto."""
        class _PayoutRotto:
            def conta_pagati(self, host_id):
                raise RuntimeError("conteggio non leggibile")
        r = self._router(_PayoutRotto())
        with self.assertLogs("core_auto", level="ERROR") as reg:
            r._forse_qualifica_referral("invitato1", _PayoutRotto())
        self.assertTrue(any("referral" in x.lower() or "premio" in x.lower() for x in reg.output),
                        "il premio mancato non e' udibile: %r" % (reg.output,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
