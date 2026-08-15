"""GUARDIA — il Guardiano degli stati impossibili (fase186) VEDE davvero le anomalie.

Nato dall'audit del 2026-07-22: tre indagini convergevano su una lacuna — nessuno
controlla in automatico gli stati che non dovrebbero poter esistere, e nessuno grida.
Il Guardiano colma quel buco. Ma un guardiano che non ha mai visto un'anomalia non e' un
guardiano: e' un ornamento. Qui gli si mette davanti, uno per uno, ogni stato impossibile
e si pretende che se ne accorga; e su un sistema sano deve tacere.

Stati messi alla prova:
  · ESCROW BLOCCATO: una garanzia il cui rilascio automatico e' passato da giorni;
  · BONIFICO FERMO: un payout 'maturato' vecchio di settimane;
  · PAYOUT ORFANO: un payout dovuto a un host che non esiste;
  · e su tutto pulito -> nessun allarme (mai gridare al lupo per un ritardo normale).
"""

import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
import fase186_guardiano as G


class _Base(unittest.TestCase):

    def setUp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"G" * 32, con_registrazione_host=True,
            db_catalogo="%s/c.db" % d, db_inventario="%s/i.db" % d,
            db_registro_host="%s/r.db" % d, db_garanzia="%s/g.db" % d,
            db_payout="%s/y.db" % d, db_pendenti="%s/p.db" % d,
            db_accettazioni="%s/a.db" % d, db_tassa_comunale="%s/t.db" % d))
        self.now = int(time.time())


class TestSistemaSanoNessunAllarme(_Base):

    def test_su_tutto_pulito_il_guardiano_TACE(self):
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        self.assertTrue(rep["pulito"], "grida su un sistema sano: %s" % rep["anomalie"])
        self.assertEqual(rep["conta"], 0)


class TestControlloCieco(_Base):
    """«PULITO» e «NON HO POTUTO GUARDARE» non sono la stessa cosa.

    Il Guardiano avvolge tutti i suoi controlli in `_prova`, che cattura qualunque errore e
    ritorna None; il chiamante fa `if ric:` e la categoria SPARISCE dall'elenco. Poi
    `conta = 0` -> `pulito = True` -> nessuna email. Tradotto: se un controllo va in errore,
    il Guardiano dichiara che va tutto bene mentre e' CIECO su quel fronte -- e i fronti sono
    otto, fra cui la riconciliazione con Stripe e gli escrow che pagano l'host.

    E' lo stesso difetto di forma trovato altrove il 2026-07-30 (il test che pretendeva il
    comando che spegne il sito, il log che diceva «blocco temporaneo» su un'app murata, il
    credito «non consumato» confuso con «niente da consumare»): uno strumento che rassicura
    invece di controllare.

    VISTO ROSSO sul codice vecchio: con un archivio guasto rispondeva pulito=True, conta=0.
    """

    class _ArchivioRotto:
        """Qualunque cosa gli si chieda, esplode. Simula un DB corrotto o irraggiungibile."""
        def __getattr__(self, nome):
            def _boom(*a, **k):
                raise RuntimeError("archivio guasto: %s" % nome)
            return _boom

    def test_un_controllo_che_esplode_NON_puo_diventare_tutto_pulito(self):
        self.sys.garanzia = self._ArchivioRotto()          # rompe il controllo escrow
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        self.assertFalse(rep["pulito"],
                         "un controllo esploso e' stato scambiato per «tutto a posto»: %r" % rep)
        self.assertGreater(rep["conta"], 0, "il conteggio ignora i controlli ciechi: %r" % rep)
        self.assertIn("controllo_cieco", rep["anomalie"],
                      "il Guardiano deve DICHIARARE cosa non ha potuto guardare: %r" % rep)

    def test_l_allarme_dice_QUALE_controllo_e_cieco(self):
        """Non basta gridare: serve sapere su cosa siamo ciechi, o l'email e' inutile."""
        self.sys.payout = self._ArchivioRotto()            # rompe bonifici fermi/orfani
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        ciechi = rep["anomalie"].get("controllo_cieco") or []
        self.assertTrue(any("payout" in str(c) for c in ciechi),
                        "l'elenco dei ciechi non nomina il controllo rotto: %r" % (ciechi,))

    def test_e_l_email_di_allarme_lo_scrive(self):
        self.sys.garanzia = self._ArchivioRotto()
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        html = G.riassunto_html(rep)
        self.assertIn("non ha potuto", html.lower(),
                      "l'email non spiega che un controllo non ha potuto girare: %s" % html[:400])


class TestControlloCiecoSILENZIOSO(_Base):
    """LA STESSA MALATTIA DELLA CLASSE QUI SOPRA, MA SENZA RUMORE -- e per questo peggiore.

    `TestControlloCieco` copre la forma RUMOROSA: un archivio esplode, `_prova` cattura
    l'eccezione e mette il controllo fra i ciechi. Funziona.

    Ma `_riconciliazione` (fase186_guardiano.py) esce con `None` in DUE situazioni diverse:
      · riga 76 -> Stripe non e' configurato: NON HO GUARDATO;
      · riga 84 -> `rep["ok"]`: HO GUARDATO E TUTTO QUADRA.
    Chi chiama riceve lo stesso identico valore, e `_prova` mette fra i ciechi **solo chi
    solleva un'eccezione**. Quindi la prima situazione non lascia traccia da nessuna parte:
    niente anomalia, niente cieco, `conta` resta 0, `pulito` diventa True. Non c'e' nemmeno
    una riga di log, mentre la forma rumorosa almeno ne scrive una.

    E' esattamente il buco che il commento a `scansiona` (riga 316) dichiara di aver chiuso:
    *«un controllo fallito NON e' un controllo pulito»*. Chiuso per una forma su due.

    MISURATO il 2026-08-15 sul banco di prova di questo file, che non passa nessuna chiave
    Stripe (`ConfigCasaVIP.stripe_secret_key` vale "" di serie, fase81:59):
        pulito = True | conta = 0 | anomalie = []
    Cioe' il Guardiano dichiara tutto a posto AVENDO SALTATO il confronto dei conti con la
    banca, che e' il controllo piu' importante che ha. Il test «su tutto pulito il Guardiano
    TACE», in cima a questo file, oggi passa APPOGGIANDOSI a questo difetto.

    ⛔ E la riparazione non puo' essere «alzare un allarme»: senza Stripe non c'e' nessuna
    anomalia da segnalare, e gridare sarebbe un FALSO ALLARME (regola ferrea 10, che li
    considera gravi quanto un allarme mancato -- insegnano a ignorare i segnali). La forma
    giusta e' quella che il progetto usa gia' ovunque, dal pre-volo al pre-fatto: i
    NON ESEGUITI si dichiarano A PARTE, e un non eseguito non e' un successo (sbaglio S7).
    """

    def _pretendi_niente_stripe(self):
        """La premessa di questi tre test: il banco NON ha una chiave Stripe.

        Non la si IMPOSTA (`ConfigCasaVIP` e' un dataclass frozen: assegnare solleva
        `FrozenInstanceError`), la si VERIFICA. E la si verifica invece di darla per buona,
        perche' il giorno che qualcuno mettesse una chiave nel banco questi tre test
        smetterebbero di provare cio' che dicono e resterebbero verdi: e' lo sbaglio S7,
        un controllo che da' OK quando la premessa manca.
        """
        self.assertFalse(
            getattr(self.sys.config, "stripe_secret_key", "") or "",
            "premessa non valida: il banco di prova ha una chiave Stripe, quindi la "
            "riconciliazione VIENE eseguita e questi test non provano piu' niente")

    def test_SENZA_STRIPE_il_rapporto_DICHIARA_di_non_aver_guardato(self):
        """Il Guardiano deve dire cosa NON ha potuto controllare, non solo cosa ha trovato."""
        self._pretendi_niente_stripe()
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        non_eseguiti = rep.get("non_eseguiti") or []
        self.assertTrue(
            any("riconcili" in str(c) for c in non_eseguiti),
            "il confronto dei conti con Stripe NON e' stato eseguito (manca la chiave) e il "
            "rapporto non lo dichiara da nessuna parte: dice «tutto quadra» su un fronte che "
            "non ha nemmeno guardato. Rapporto: %r" % (rep,))

    def test_ma_NON_diventa_un_FALSO_ALLARME(self):
        """L'altra direzione (D18 punto 2): dichiararlo non vuol dire gridare.

        Senza Stripe non c'e' NIENTE che non va: c'e' una cosa che non si e' potuta
        guardare. Se questa distinzione si perde, il Guardiano manda un'email ogni giorno
        su una macchina sana -- e un allarme sempre acceso viene spento da chi lo riceve.
        """
        self._pretendi_niente_stripe()
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        self.assertTrue(rep["pulito"],
                        "senza Stripe non c'e' nessuna ANOMALIA: c'e' un controllo non "
                        "eseguito. Trasformarlo in allarme e' un falso allarme: %r" % (rep,))
        self.assertEqual(rep["conta"], 0, "un non eseguito non si conta fra le anomalie")
        self.assertNotIn("riconciliazione_stripe", rep["anomalie"])

    def test_e_CHI_LEGGE_L_EMAIL_lo_vede(self):
        """COSTRUITO non basta: dev'essere COLLEGATO a chi decide (regola #23).

        Un rapporto che dichiara i non eseguiti in un campo che nessuno stampa non protegge
        nessuno. Il gemello rumoroso ha gia' la sua prova (`test_e_l_email_di_allarme_lo
        _scrive`): qui si pretende la stessa cosa per la forma silenziosa.
        """
        self._pretendi_niente_stripe()
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        html = G.riassunto_html(rep).lower()
        self.assertIn("non eseguit", html,
                      "l'email non dice che un controllo non ha potuto girare, quindi chi la "
                      "legge crede che sia stato guardato tutto: %s" % html[:400])


class TestGuastiIsolatiNelRegistro(_Base):
    """I GUASTI ISOLATI NON POSSONO FINIRE DOVE NESSUNO GUARDA.

    Nel solo `fase83_server.py` ci sono 165 punti in cui un errore viene ingoiato di
    proposito (isolamento: un pezzo rotto non deve far cadere tutto) e finisce SOLO nel
    registro `app.log`. In tutto il progetto quel file ha UN solo lettore: un pannello
    manuale, dietro doppia chiave, che mostra al massimo le ultime 300 righe di un file
    rotante da 5MB. Tradotto: un guasto isolato su denaro o serrature poteva restare
    invisibile per sempre.

    Qui il Guardiano -- che gira gia' ogni giorno e manda gia' l'email -- impara a leggerlo.
    Guarda SOLO gli ERROR (non i warning): sono i casi gravi, e sul server vero oggi sono
    ZERO, quindi non produce affaticamento da allarmi (regola 10: un falso allarme e' un
    difetto).

    VISTO ROSSO: prima di questa correzione il Guardiano non leggeva il registro e restava
    'pulito' anche con errori freschi dentro.
    """

    def _sistema_con_registro(self, righe=None):
        """Sistema il cui `db_finanza` sta in una cartella temporanea: e' da li' che il
        Guardiano ricava dove leggere `app.log` -- dalla CONFIGURAZIONE, non dall'ambiente.
        Legarlo a una variabile d'ambiente faceva leggere l'app.log dello SVILUPPATORE."""
        import os
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        if righe is not None:
            with open(os.path.join(d, "app.log"), "w", encoding="utf-8") as f:
                f.write("\n".join(righe) + "\n")
        return crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"G" * 32, con_registrazione_host=True,
            db_catalogo="%s/c.db" % d, db_inventario="%s/i.db" % d,
            db_registro_host="%s/r.db" % d, db_garanzia="%s/g.db" % d,
            db_payout="%s/y.db" % d, db_pendenti="%s/p.db" % d,
            db_accettazioni="%s/a.db" % d, db_tassa_comunale="%s/t.db" % d,
            db_finanza="%s/finanza.db" % d))

    def _riga(self, quando_ts, livello, testo):
        import datetime
        t = datetime.datetime.utcfromtimestamp(quando_ts).strftime("%Y-%m-%d %H:%M:%S,000")
        return "%s %s core_auto.server %s" % (t, livello, testo)

    def test_errori_freschi_nel_registro_sono_un_ALLARME(self):
        sis = self._sistema_con_registro([
            self._riga(self.now - 600, "INFO", "avvio ok"),
            self._riga(self.now - 500, "ERROR", "consumo credito single-use FALLITO"),
            self._riga(self.now - 400, "ERROR", "RIMBORSO ADMIN INCOMPLETO rif=abc"),
        ])
        rep = G.scansiona(sis, ora=lambda: self.now)
        self.assertFalse(rep["pulito"], "errori freschi nel registro e il Guardiano tace: %r" % rep)
        self.assertIn("guasti_isolati", rep["anomalie"], rep["anomalie"])

    def test_solo_avvisi_e_informazioni_NON_fanno_gridare(self):
        """Prova di rimozione: 131 warning nel codice sono normali, non sono allarmi."""
        sis = self._sistema_con_registro([
            self._riga(self.now - 300, "INFO", "tutto regolare"),
            self._riga(self.now - 200, "WARNING", "prova foto: bolla non scritta (ISOLATO)"),
        ])
        rep = G.scansiona(sis, ora=lambda: self.now)
        self.assertTrue(rep["pulito"], "grida su semplici avvisi: %r" % rep["anomalie"])

    def test_errori_VECCHI_non_gridano_per_sempre(self):
        """Un errore di un mese fa non deve tenere l'allarme acceso in eterno."""
        sis = self._sistema_con_registro(
            [self._riga(self.now - 40 * 86400, "ERROR", "roba vecchissima")])
        rep = G.scansiona(sis, ora=lambda: self.now)
        self.assertTrue(rep["pulito"], "un errore vecchio grida ancora: %r" % rep["anomalie"])

    def test_registro_ASSENTE_non_e_un_allarme(self):
        """Impianto appena nato: nessun log -> silenzio (lezione del falso allarme marche)."""
        sis = self._sistema_con_registro(None)      # cartella vera, nessun app.log dentro
        rep = G.scansiona(sis, ora=lambda: self.now)
        self.assertTrue(rep["pulito"], "grida su un impianto senza registro: %r" % rep["anomalie"])


class TestEscrowBloccato(_Base):

    def test_una_garanzia_scaduta_da_giorni_e_un_allarme(self):
        gar = self.sys.garanzia
        # apro una garanzia con check-in vecchissimo -> il rilascio e' gia' passato
        vecchio = self.now - 10 * 86400
        gar.apri("pren-vecchia", 30000, alloggio_id="casa", ora_checkin_ts=vecchio)
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        self.assertFalse(rep["pulito"])
        self.assertIn("escrow_bloccato", rep["anomalie"])
        self.assertEqual(rep["anomalie"]["escrow_bloccato"][0]["prenotazione_id"],
                         "pren-vecchia")

    def test_una_garanzia_appena_aperta_NON_allarma(self):
        self.sys.garanzia.apri("pren-fresca", 30000, alloggio_id="casa",
                               ora_checkin_ts=self.now)
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        self.assertNotIn("escrow_bloccato", rep["anomalie"],
                         "grida su un escrow appena aperto (ritardo normale)")


class TestBonificoFermoEOrfano(_Base):

    def _registra_host(self, hid="h_reale"):
        # un host che esiste davvero, cosi' il suo payout non risulta orfano
        self.sys.registro_host.registra("h@g.it", "password1", host_id_forzato=hid) \
            if hasattr(self.sys.registro_host, "registra") else None
        return hid

    def test_payout_maturato_vecchio_e_un_bonifico_fermo(self):
        pay = self.sys.payout
        # host ESISTENTE (altrimenti il payout risulterebbe 'orfano', non 'fermo')
        e = self.sys.registro_host.registra("e@g.it", "password1", accetta_termini=True)
        self.assertTrue(getattr(e, "ok", False), "registrazione host fallita: %r" % e)
        hid = e.host_id
        # riga maturato vecchia di 20 giorni
        pay.registra_maturato("pren-ferma", hid, 25000, "EUR")
        # invecchio la riga a mano (il ts di registrazione e' 'ora')
        con = pay._apri()
        with con:
            con.execute("UPDATE payout SET ts=? WHERE prenotazione_id=?",
                        (self.now - 20 * 86400, "pren-ferma"))
        con.close()
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        self.assertFalse(rep["pulito"])
        self.assertIn("bonifico_fermo", rep["anomalie"])

    def test_payout_a_host_inesistente_e_ORFANO(self):
        # payout dovuto a un host che NON e' nel registro -> residuo di cancellazione
        self.sys.payout.registra_maturato("pren-orfana", "host_fantasma", 40000, "EUR")
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        self.assertFalse(rep["pulito"])
        self.assertIn("payout_orfano", rep["anomalie"])
        self.assertEqual(rep["anomalie"]["payout_orfano"][0]["host_id"], "host_fantasma")


class TestRiassuntoEmail(_Base):

    def test_l_email_di_allarme_e_costruita_e_XSS_safe(self):
        rep = {"conta": 1, "pulito": False,
               "anomalie": {"payout_orfano": [{"host_id": "<script>x</script>",
                                               "minori": 100}]}}
        html = G.riassunto_html(rep)
        self.assertIn("Guardiano", html)
        self.assertNotIn("<script>x", html, "il riassunto non e' XSS-safe")
        self.assertIn("&lt;script&gt;", html)


class TestEndpointManuale(_Base):
    """La rotta a richiesta `/api/bunker/guardiano`: stesso controllo del giro giornaliero,
    ma eseguito subito. Deve essere protetta (bunker) e READ-ONLY."""

    def test_endpoint_richiede_il_bunker_e_e_read_only(self):
        import json as _j
        from fase83_server import crea_router
        r = crea_router(self.sys, host_key="hk", admin_key="ak",
                        base_url="https://bookinvip.com")
        # senza sessione bunker -> se il bunker e' configurato, 403; se non lo e' (come qui,
        # nei test), l'operazione read-only puo' passare. In entrambi i casi NON deve
        # sollevare ne' 500, e su un sistema pulito il referto e' 'pulito'.
        st, corpo = r.gestisci("GET", "/api/bunker/guardiano", {}, None,
                               {"X-Admin-Key": "ak"})
        self.assertIn(st, (200, 403), corpo)
        if st == 200:
            self.assertIn("pulito", corpo)


class TestNonSollevaMai(_Base):

    def test_scansiona_non_solleva_su_sistema_rotto(self):
        class Rotto:
            def __getattr__(self, n):
                raise RuntimeError("giu")
        try:
            rep = G.scansiona(Rotto())
        except Exception as e:
            self.fail("il guardiano solleva su sistema rotto: %s" % e)
        self.assertIsInstance(rep, dict)


if __name__ == "__main__":
    unittest.main(verbosity=2)
