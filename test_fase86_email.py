"""
Test Fase 86 - Provider Email.

Copre: invio (con send STUB, niente SMTP reale), destinatario invalido -> False, send che
solleva -> False (isolato), factory gated (no host -> None), corpo voucher HTML (link +
XSS-safe).
"""
import unittest

from fase86_email import ProviderEmail, corpo_voucher_html, crea_provider_email


class SendSpy:
    def __init__(self, ritorna=True, solleva=False, solleva_prime=0):
        """`solleva_prime=N`: le prime N chiamate sollevano (singhiozzo transitorio),
        poi funziona. `solleva=True`: solleva SEMPRE (SMTP giu' del tutto)."""
        self.chiamate = []
        self.tentativi = 0
        self._r = ritorna
        self._solleva = solleva
        self._solleva_prime = solleva_prime

    def __call__(self, dest, oggetto, html):
        self.tentativi += 1
        if self._solleva or self.tentativi <= self._solleva_prime:
            raise RuntimeError("smtp giu'")
        self.chiamate.append((dest, oggetto, html))
        return self._r


class SleepSpy:
    def __init__(self):
        self.pause = []

    def __call__(self, secondi):
        self.pause.append(secondi)


class TestInvio(unittest.TestCase):
    def test_invio_ok(self):
        spy = SendSpy()
        p = ProviderEmail("smtp.x", 587, "u", "pw", "no-reply@bookinvip.com", send=spy)
        self.assertTrue(p.invia("g@x.it", "Conferma", "<p>ciao</p>"))
        self.assertEqual(spy.chiamate[0][0], "g@x.it")
        self.assertEqual(spy.chiamate[0][1], "Conferma")

    def test_destinatario_invalido(self):
        p = ProviderEmail("smtp.x", 587, "u", "pw", "m@x.it", send=SendSpy())
        self.assertFalse(p.invia("non-email", "x", "y"))
        self.assertFalse(p.invia(None, "x", "y"))

    def test_send_solleva_isolato(self):
        spy, dormi = SendSpy(solleva=True), SleepSpy()
        p = ProviderEmail("smtp.x", 587, "u", "pw", "m@x.it", send=spy, sleep=dormi)
        self.assertFalse(p.invia("g@x.it", "x", "y"))      # False, non crash
        self.assertEqual(spy.tentativi, 2)                 # ha ritentato una volta
        self.assertEqual(len(dormi.pause), 1)              # una sola pausa tra i due

    def test_retry_su_singhiozzo_transitorio(self):
        # Il caso VERO visto in prod (2026-07-15): SMTP chiude la connessione una volta,
        # al secondo tentativo (connessione fresca) va -> l'email NON e' persa.
        spy, dormi = SendSpy(solleva_prime=1), SleepSpy()
        p = ProviderEmail("smtp.x", 587, "u", "pw", "m@x.it", send=spy, sleep=dormi)
        self.assertTrue(p.invia("g@x.it", "Conferma", "<p>ok</p>"))
        self.assertEqual(spy.tentativi, 2)
        self.assertEqual(dormi.pause, [1.5])
        self.assertEqual(spy.chiamate[0][0], "g@x.it")     # consegnata al 2o giro

    def test_no_retry_su_false_pulito(self):
        # Il provider risponde 'no' senza eccezione -> NIENTE retry (ha gia' deciso).
        spy, dormi = SendSpy(ritorna=False), SleepSpy()
        p = ProviderEmail("smtp.x", 587, "u", "pw", "m@x.it", send=spy, sleep=dormi)
        self.assertFalse(p.invia("g@x.it", "x", "y"))
        self.assertEqual(spy.tentativi, 1)
        self.assertEqual(dormi.pause, [])

    def test_invia_non_solleva_mai_neanche_con_sleep_rotto(self):
        # Perfino uno sleep che solleva non deve far uscire eccezioni da `invia`.
        def sleep_rotto(_s):
            raise RuntimeError("clock rotto")
        p = ProviderEmail("smtp.x", 587, "u", "pw", "m@x.it",
                          send=SendSpy(solleva=True), sleep=sleep_rotto)
        try:
            esito = p.invia("g@x.it", "x", "y")
        except Exception as exc:  # pragma: no cover
            self.fail("invia ha sollevato: %r" % exc)
        self.assertFalse(esito)


class TestFactory(unittest.TestCase):
    def test_gated(self):
        self.assertIsNone(crea_provider_email(None))
        self.assertIsNone(crea_provider_email(""))
        self.assertIsNotNone(crea_provider_email("smtp.x", 587, "u", "pw", "m@x.it",
                                                 send=SendSpy()))


class TestCorpo(unittest.TestCase):
    def test_html_con_link(self):
        h = corpo_voucher_html("Casa Roma", "ABC123", "2026-09-01", "2026-09-02",
                               "https://bookinvip.com/voucher/tok", lingua="it")
        self.assertIn("Prenotazione confermata", h)
        self.assertIn("ABC123", h)
        self.assertIn("https://bookinvip.com/voucher/tok", h)

    def test_xss_safe(self):
        h = corpo_voucher_html("<script>x</script>", "r", "a", "b", "")
        self.assertNotIn("<script>x</script>", h)
        self.assertIn("&lt;script&gt;", h)


class TestLaMailDelBonificoDiceITempiVeri(unittest.TestCase):
    """5/11: la mail all'host diceva «in banca di norma 1-3 giorni», ma sul conto host vero
    Stripe tiene i soldi 7 giorni (delay_days letto il 4/11, minimo chiesto e rifiutato). Ogni
    lingua deve dire che i soldi sono GIA' sul conto Stripe e che la banca arriva dopo, senza
    promettere i giorni lavorativi di una banca."""

    def test_ogni_lingua_nomina_stripe_e_non_promette_1_3_giorni(self):
        from fase86_email import _TR
        tempi = _TR["p_tempi"]
        self.assertEqual(sorted(tempi), sorted(_TR["p_ogg"]))
        for lingua, testo in tempi.items():
            self.assertIn("Stripe", testo, lingua)
            self.assertIn("7", testo, lingua)
            for falso in ("1-3", "1 à 3", "1〜3", "1-3 "):
                self.assertNotIn(falso, testo, lingua)


class TestIlPannelloHostDiceGliStessiTempiDellaMail(unittest.TestCase):
    """5/11: il riquadro «Collega il tuo conto Stripe» del pannello host diceva che dopo il
    check-in «i tuoi soldi partono da soli verso il tuo conto», e l'host capiva «in banca il
    giorno dopo». Ora dice che partono verso il conto STRIPE e ripete, parola per parola, la
    frase dei tempi della banca della mail del bonifico (`p_tempi`): se una delle due cambia da
    sola, questa prova diventa rossa. Il testo di riserva del paragrafo (quello che si legge
    prima che giri lo script) e' la versione italiana."""

    def test_it_ed_en_dicono_conto_stripe_e_la_stessa_frase_della_mail(self):
        import re
        from pathlib import Path
        from fase86_email import _TR
        pagina = (Path(__file__).resolve().parent / "deploy" / "host.html").read_text("utf-8")
        pannello = dict(re.findall(r'\b([a-z]{2}):\{[^\n]*?\bsc_p:"([^"]*)"', pagina))
        riserva = re.findall(r'data-i18n="sc_p">([^<]*)<', pagina)
        self.assertEqual(riserva, [pannello.get("it")])
        verso = {"it": "verso il tuo conto Stripe.", "en": "to your Stripe account"}
        for lingua, destinazione in verso.items():
            frase_mail = _TR["p_tempi"][lingua].split(". ")[1] + "."
            self.assertIn(destinazione, pannello.get(lingua, ""), lingua)
            self.assertIn(frase_mail, pannello[lingua], lingua)


class TestLaCodaNonScriveRigheFinteNelRegistro(unittest.TestCase):
    """PROTON, compiti 24 e 29 (14/11): «EMAIL NON CONSEGNABILE» scriveva il riferimento letto
    dalla coda cosi' com'era, e `accoda` lo salva senza filtro (in fase83 template e
    riferimento «arrivano da dati di richiesta»). Un a-capo dentro fabbrica una riga nuova nel
    registro, dove il Guardiano cerca i guasti: qui lo si mette a mano, nelle tre forme."""

    def test_il_riferimento_non_spezza_la_riga_e_si_legge_ancora(self):
        import os
        import shutil
        import tempfile
        from fase86_email import CodaEmail
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        for i, rif in enumerate(("R-1\nRIGA FINTA", "R-2\r\nRIGA FINTA", "R-3\rRIGA FINTA")):
            with self.subTest(rif=repr(rif)):
                coda = CodaEmail(os.path.join(d, "coda%d.db" % i), lambda a, o, h: False,
                                 tentativi=1, ora=lambda: 1_000_000.0)
                self.assertTrue(coda.accoda("a@b.it", "o", "<p>x</p>", riferimento=rif))
                with self.assertLogs("core_auto.email", level="CRITICAL") as reg:
                    coda.un_giro()
                gridi = [x.getMessage() for x in reg.records
                         if "EMAIL NON CONSEGNABILE" in x.getMessage()]
                self.assertEqual(len(gridi), 1, reg.output)
                self.assertNotIn("\n", gridi[0], "un a-capo da fuori e' arrivato nel registro")
                self.assertNotIn("\r", gridi[0], "un ritorno a capo da fuori nel registro")
                self.assertIn("RIGA FINTA", gridi[0], "il riferimento si deve ancora leggere")
                self.assertIn("R-%d" % (i + 1), gridi[0])


class TestPR316IlGiroDellaCodaNonTieneVivoIlProcesso(unittest.TestCase):
    """Pezzo 4 (PR #316): `daemon=True` di `CodaEmail.avvia` (:259) era «non determinabile» per
    il giudice: col guasto la prova di test_email_tracciata cadeva prima di fermare il giro, il
    processo non finiva e il giro andava oltre il tempo. Qui la fermata e' registrata PRIMA
    delle asserzioni, e la prova sta nel dedicato."""

    def test_il_giro_e_un_filo_demone_e_si_ferma_davvero(self):
        import os
        import shutil
        import tempfile
        from fase86_email import CodaEmail
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        coda = CodaEmail(os.path.join(d, "coda.db"), lambda a, o, h: True)
        coda.inizializza_schema()
        coda.avvia(ogni_s=3600)
        self.addCleanup(coda.ferma)
        giro = coda._giro
        self.assertIsNotNone(giro, "avvia non ha acceso il giro")
        self.assertEqual("coda-email", giro.name)
        self.assertTrue(giro.daemon, "un giro non demone tiene vivo il processo all'uscita")
        coda.ferma()
        giro.join(5)
        self.assertFalse(giro.is_alive(), "ferma() non ha fermato il giro")
        self.assertIsNone(coda._giro)


class TestUnEmailInVoloStaGiaSuDisco(unittest.TestCase):
    """21/11, code-review della PR #335: le email nella fila IN MEMORIA di fase83 (`_FILA_EMAIL`)
    si perdevano a ogni riavvio (python e' il processo 1 del contenitore, senza gestore di
    SIGTERM: Docker lo uccide e nessun gancio di spegnimento gira). Ora la riga nasce su disco
    PRIMA dell'invio (`accoda_in_volo`), il postino la prende (`prendi`), la manda e la chiude
    (`chiudi`); se il processo muore, il giro dei ritentativi la manda dopo PRESA_SCADE_S."""

    def setUp(self):
        import os
        import shutil
        import tempfile
        from fase86_email import CodaEmail
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.t, self.esito, self.mandate = 1_900_000_000.0, True, []

        def invia(a, _o, _h):
            if self.esito:              # conta solo le consegne riuscite
                self.mandate.append(a)
            return self.esito
        self.coda = CodaEmail(os.path.join(d, "coda.db"), invia, ora=lambda: self.t)
        self.coda.inizializza_schema()

    def _righe(self):
        con = self.coda._apri()
        try:
            return con.execute("SELECT a, stato, prossimo_ts FROM coda_email ORDER BY id").fetchall()
        finally:
            con.close()

    def test_la_riga_nasce_prima_dell_invio_e_il_giro_la_tocca_solo_dopo_la_presa(self):
        from fase86_email import PRESA_SCADE_S
        id_riga = self.coda.accoda_in_volo("ospite@x.it", "o", "<p>x</p>", "voucher", "R1")
        self.assertIsInstance(id_riga, int)
        self.assertEqual([("ospite@x.it", "attesa", int(self.t) + PRESA_SCADE_S)], self._righe())
        # la riga porta tutto cio' che serve al giro e al registro (il riferimento lo scrive
        # l'allarme «EMAIL NON CONSEGNABILE»), e i vuoti restano vuoti, non «None»
        self.coda.accoda_in_volo("altro@x.it", "o2", "h2", None, None)
        con = self.coda._apri()
        try:
            dati = con.execute("SELECT oggetto, html, template, riferimento FROM coda_email "
                               "ORDER BY id").fetchall()
        finally:
            con.close()
        self.assertEqual([("o", "<p>x</p>", "voucher", "R1"), ("o2", "h2", "", "")], dati)
        con = self.coda._apri()
        try:
            with con:
                con.execute("DELETE FROM coda_email WHERE a='altro@x.it'")
        finally:
            con.close()
        self.t += PRESA_SCADE_S - 1
        self.assertEqual(0, self.coda.un_giro(), "il giro l'ha presa mentre il postino la manda")
        self.t += 1
        self.assertEqual(1, self.coda.un_giro(), "processo morto: il giro non l'ha mandata")
        self.assertEqual(["ospite@x.it"], self.mandate)
        self.assertEqual([], self._righe())

    def test_un_destinatario_non_valido_non_scrive_niente(self):
        for dest in (None, 123, "senza-chiocciola"):
            with self.subTest(dest=dest):
                self.assertIsNone(self.coda.accoda_in_volo(dest, "o", "h"))
        self.assertEqual([], self._righe())

    def test_il_postino_prende_manda_e_chiude(self):
        id_riga = self.coda.accoda_in_volo("ospite@x.it", "o", "h")
        presa = self.coda.prendi(id_riga)
        self.assertIsInstance(presa, int, "la presa e' un biglietto: chi chiude deve averlo")
        self.assertIsNone(self.coda.prendi(id_riga), "presa due volte: due invii")
        self.coda.chiudi(id_riga, True, presa)
        self.assertEqual([], self._righe(), "consegnata = cancellata")

    def test_un_invio_fallito_torna_al_giro_coi_suoi_tentativi(self):
        # code-review 21/11: il fallimento del postino conta come un tentativo e aspetta come
        # quelli del giro (prima tentativi restava 0 e il giro rimandava subito)
        from fase86_email import ATTESA_PRIMA_S
        id_riga = self.coda.accoda_in_volo("ospite@x.it", "o", "h")
        self.coda.chiudi(id_riga, False, self.coda.prendi(id_riga))
        self.assertEqual([("ospite@x.it", "attesa", int(self.t) + ATTESA_PRIMA_S)], self._righe())
        con = self.coda._apri()
        try:
            self.assertEqual([(1,)], con.execute("SELECT tentativi FROM coda_email").fetchall())
        finally:
            con.close()
        self.t += ATTESA_PRIMA_S - 1
        self.assertEqual(0, self.coda.un_giro())
        self.t += 1
        self.assertEqual(1, self.coda.un_giro())
        self.assertEqual([], self._righe())

    def test_chiudere_una_riga_non_presa_non_tocca_niente(self):
        # una riga che il postino non ha preso non si cancella ne' si rimette in attesa da fuori
        from fase86_email import PRESA_SCADE_S
        id_riga = self.coda.accoda_in_volo("ospite@x.it", "o", "h")
        self.coda.chiudi(id_riga, True, None)
        self.coda.chiudi(id_riga, False, None)
        self.assertEqual([("ospite@x.it", "attesa", int(self.t) + PRESA_SCADE_S)], self._righe())

    def test_un_postino_in_ritardo_non_tocca_la_riga_ripresa_dal_giro(self):
        # code-review 21/11: la presa del postino e' scaduta e il giro ha ripreso la riga; il
        # postino in ritardo non la deve cancellare (se il giro poi fallisce: email persa) ne'
        # rimettere in attesa (doppione)
        from fase86_email import PRESA_SCADE_S
        id_riga = self.coda.accoda_in_volo("ospite@x.it", "o", "h")
        nato = int(self.t)
        vecchia = self.coda.prendi(id_riga)
        self.t += PRESA_SCADE_S
        self.assertIsNotNone(self.coda.prendi(id_riga), "presa scaduta non ripresa")
        self.coda.chiudi(id_riga, True, vecchia)
        self.coda.chiudi(id_riga, False, vecchia)
        self.assertEqual([("ospite@x.it", "presa", nato + PRESA_SCADE_S)], self._righe())

    def test_una_email_consegnata_non_lascia_il_testo_su_disco(self):
        # code-review 21/11, sicurezza: ora OGNI email passa dal disco (reset della password,
        # PIN del voucher). Consegnata = cancellata anche dal file di appoggio (-wal), dove
        # `secure_delete` non arriva
        # ⛔ con UNA sola connessione SQLite svuota il -wal da se' chiudendo l'ultima: la prova
        # passava anche senza il rimedio. In produzione un'altra connessione (il giro, un altro
        # processo) resta aperta: qui la si tiene aperta anche noi
        import os
        import sqlite3
        segreto = "reset=SEGRETO-7f3a9c"
        id_riga = self.coda.accoda_in_volo("ospite@x.it", "o", "<a href='/entra#%s'>x</a>"
                                           % segreto)
        altra = sqlite3.connect(self.coda.percorso)
        self.addCleanup(altra.close)
        altra.execute("SELECT count(*) FROM coda_email").fetchall()
        self.coda.chiudi(id_riga, True, self.coda.prendi(id_riga))
        for suffisso in ("", "-wal"):
            percorso = self.coda.percorso + suffisso
            if os.path.exists(percorso):
                with open(percorso, "rb") as f:
                    self.assertNotIn(segreto.encode(), f.read(), "testo rimasto in" + suffisso)

    def test_un_archivio_bloccato_non_ferma_la_richiesta(self):
        # code-review 21/11: `accoda_in_volo` gira nel filo della richiesta dell'ospite; con
        # l'archivio occupato da un altro processo non si aspettano 30 s: si rinuncia presto
        # (e fase83 manda l'email dalla memoria, ERROR coda_non_scritta)
        import sqlite3
        import time
        self.coda.accoda_in_volo("prima@x.it", "o", "h")       # archivio gia' in WAL
        blocco = sqlite3.connect(self.coda.percorso, timeout=1)
        self.addCleanup(blocco.close)
        blocco.execute("BEGIN IMMEDIATE")
        inizio = time.monotonic()
        with self.assertRaises(sqlite3.OperationalError):
            self.coda.accoda_in_volo("ospite@x.it", "o", "h")
        attesa = time.monotonic() - inizio
        blocco.rollback()
        self.assertLess(attesa, 10, "la richiesta ha aspettato %.1f s l'archivio" % attesa)

    def test_anticipa_fa_partire_la_riga_al_prossimo_giro(self):
        # code-review 21/11: a fila piena la riga su disco non aspetta la presa (10 minuti)
        id_riga = self.coda.accoda_in_volo("ospite@x.it", "o", "h")
        self.coda.anticipa(id_riga)
        self.assertEqual([("ospite@x.it", "attesa", int(self.t))], self._righe())
        self.assertEqual(1, self.coda.un_giro())

    def test_nessuna_sequenza_perde_un_email(self):
        # property-based-testing (Trail of Bits) 21/11: sequenze a caso di email accodate,
        # postini che prendono, mandano (riuscito o no), chiudono o MUOIONO con la riga in mano,
        # tempo che passa e giri della coda. Invarianti: una riga sparisce solo dopo una
        # consegna; e alla fine, col tempo, ogni email accodata e' consegnata almeno una volta.
        from hypothesis import settings, strategies as st
        from hypothesis.stateful import RuleBasedStateMachine, invariant, rule
        caso = self

        class Coda(RuleBasedStateMachine):
            def __init__(self):
                super().__init__()
                caso.setUp()
                self.n, self.ids, self.in_mano = 0, {}, {}

            def _presenti(self):
                return {a for a, _s, _p in caso._righe()}

            @rule()
            def accoda(self):
                self.n += 1
                a = "e%d@x.it" % self.n
                self.ids[a] = caso.coda.accoda_in_volo(a, "o", "h", "t", "r%d" % self.n)

            @rule(dato=st.data())
            def postino_prende(self, dato):
                if self.ids:
                    a = dato.draw(st.sampled_from(sorted(self.ids)))
                    presa = caso.coda.prendi(self.ids[a])
                    if presa is not None:
                        self.in_mano[a] = presa

            @rule(dato=st.data(), riuscito=st.booleans())
            def postino_manda_e_chiude(self, dato, riuscito):
                # anche un postino in ritardo (presa scaduta, riga ripresa dal giro) chiude
                if self.in_mano:
                    a = dato.draw(st.sampled_from(sorted(self.in_mano)))
                    presa = self.in_mano.pop(a)
                    if riuscito:
                        caso.mandate.append(a)
                    caso.coda.chiudi(self.ids[a], riuscito, presa)

            @rule(dato=st.data())
            def postino_muore(self, dato):
                if self.in_mano:
                    self.in_mano.pop(dato.draw(st.sampled_from(sorted(self.in_mano))))

            @rule(secondi=st.integers(0, 900))
            def passa_il_tempo(self, secondi):
                caso.t += secondi

            @rule(riuscito=st.booleans())
            def giro(self, riuscito):
                caso.esito = riuscito
                caso.coda.un_giro(limite=1000)
                caso.esito = True

            @invariant()
            def nessuna_riga_sparisce_senza_consegna(self):
                presenti = self._presenti()
                persi = [a for a in self.ids if a not in presenti and a not in caso.mandate]
                caso.assertEqual([], persi, "righe sparite senza consegna")

            def teardown(self):
                self.in_mano.clear()            # il processo muore: i postini spariscono
                for _ in range(6):
                    caso.t += 10_000
                    caso.coda.un_giro(limite=1000)
                mancanti = [a for a in self.ids if a not in caso.mandate]
                caso.assertEqual([], mancanti, "email mai consegnate")

        Coda.TestCase.settings = settings(max_examples=120, stateful_step_count=30,
                                          deadline=None, derandomize=True, database=None)
        Coda.TestCase("runTest").runTest()


if __name__ == "__main__":
    unittest.main()
