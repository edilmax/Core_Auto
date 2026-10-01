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

import dataclasses
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


class TestGiroTroncatoNonEUnVerdetto(_Base):
    """UN GIRO CHE NON HA FINITO DI GUARDARE NON DEVE DIRE NE' «ok» NE' «allarme».

    La classe qui sopra copre la premessa MANCANTE: non ho guardato perche' non potevo
    (niente chiave Stripe). Questa copre il caso opposto e piu' insidioso -- la premessa
    C'E', il giro PARTE, e si ferma a meta'.

    Perche' non e' un dettaglio. `fase182` legge Stripe a pagine e si ferma a un tetto
    anti-runaway (`_MAX_PAGINE`); il giornale invece lo legge INTERO. Quindi un giro
    troncato non perde fantasmi: ne INVENTA. Le sessioni che non ha fatto in tempo a
    leggere diventano «solo_giornale», cioe' prenotazioni sanissime che risultano
    incassate da noi e sconosciute a Stripe. `fase182` lo sa, lo dichiara (`parziale`,
    `troncati`) e lo dichiara proprio perche' chi legge non scambi quel referto per un
    verdetto -- il suo commento lo scrive per esteso.

    MISURATO il 2026-08-28 su 8354e10: quei due campi non li legge NESSUNO.
        grep -rn "parziale\\|troncati" --include=*.py .    (fuori da fase182 e collaudi/)
        -> zero righe
    `_riconciliazione` guarda solo `rep["ok"]` e ricostruisce le anomalie dagli elenchi.
    Quindi oggi un giro troncato manda un'email di ALLARME CRITICO che elenca
    prenotazioni sane. E' un falso allarme sui soldi, e la regola ferrea 10 lo considera
    grave quanto un allarme mancato: insegna a ignorare i segnali.
    E capita proprio quando i movimenti sono tanti -- cioe' quando i soldi sono tanti.

    Lo strumento giusto il progetto ce l'ha gia' e lo usa un ramo piu' in la':
    `NON_ESEGUITO` e il canale `non_eseguiti`. Un giro troncato appartiene li': non e'
    «qualcosa non va», e' «non ho finito di guardare» (sbaglio S7).

    ⛔ COSA QUESTA GUARDIA NON COPRE (D18 punto 3), perche' non sembri chiuso di piu':
    la GIUNTURA fra `fase83_server._tick_guardiano` e questo referto resta scoperta.
    L'email parte solo `if not rep.get("pulito")`, quindi un non eseguito su una macchina
    per il resto sana non raggiunge nessuno. Quello dipende da una decisione del fondatore
    (la mail anche quando tutto quadra) e qui NON si asserisce: una guardia che pretende
    una decisione non ancora presa nasce rossa per finta, e verrebbe spenta invece che
    ascoltata. E il pezzo a monte non e' comunque raggiungibile da un test: e' una
    funzione annidata, avviata come thread demone con un ciclo infinito.
    """

    # Non e' una chiave e non deve somigliarne a una: `_riconciliazione` guarda solo se
    # la stringa e' vuota o piena (`if not sk`), quindi qui basta che sia piena.
    _NON_UNA_CHIAVE = "banco-di-prova-nessuna-chiave-vera"

    def _banco_col_giro_troncato(self):
        """Stripe CONFIGURATO (se no si ricade nella classe sopra) e `riconcilia`
        sostituita da un referto TRONCATO: nessuna rete, nessuno Stripe vero."""
        import fase182_riconciliazione as R
        # Il banco SENZA chiave si tiene da parte: serve al confronto del secondo test.
        self.sys_senza_chiave = self.sys
        self.sys = crea_sistema(dataclasses.replace(
            self.sys.config, stripe_secret_key=self._NON_UNA_CHIAVE))
        self.addCleanup(setattr, R, "riconcilia", R.riconcilia)
        R.riconcilia = lambda *a, **k: {
            "ok": False, "giorni": 30, "da_ts": self.now - 30 * 86400,
            "parziale": True, "troncati": ["checkout/sessions"],
            "fantasmi": 2, "sessioni_pagate": 2, "incassi_giornale": 4,
            "solo_stripe": [],
            # I DUE FANTASMI INVENTATI DAL TRONCAMENTO: prenotazioni sane, incassate
            # davvero, che Stripe conosce benissimo -- solo, non siamo arrivati a leggerle.
            "solo_giornale": [{"riferimento": "prova-una", "cents": 12000, "valuta": "EUR"},
                              {"riferimento": "prova-due", "cents": 9500, "valuta": "EUR"}],
            "importo_diverso": [],
            "confronti": {"incassi": {"stripe": {}, "giornale": {}, "delta": {}},
                          "rimborsi": {"stripe": {}, "giornale": {}, "delta": {}},
                          "transfer": {"stripe": {}, "giornale": {}, "delta": {}}}}

    def _pretendi_che_il_confronto_SIA_PARTITO(self):
        """La premessa, verificata e non supposta.

        Senza questo controllo i due test qui sotto passerebbero per il motivo sbagliato:
        `_riconciliazione` uscirebbe con `NON_ESEGUITO` gia' alla prima riga (manca la
        chiave), e la guardia direbbe verde senza aver mai toccato il codice del
        troncamento -- proverebbe la classe sopra, non questa. E' lo sbaglio S7 applicato
        alla guardia stessa: un controllo che da' OK quando la premessa manca."""
        self.assertTrue(
            getattr(self.sys.config, "stripe_secret_key", "") or "",
            "premessa non valida: senza chiave il confronto non parte nemmeno, e questi "
            "test proverebbero la premessa mancante invece del giro troncato")
        self.assertIsNotNone(
            getattr(self.sys, "finanza", None),
            "premessa non valida: senza giornale il confronto non parte nemmeno")

    def test_un_giro_TRONCATO_non_grida_su_prenotazioni_sane(self):
        """Prima meta': niente falso allarme. I fantasmi li ha inventati il tetto."""
        self._banco_col_giro_troncato()
        self._pretendi_che_il_confronto_SIA_PARTITO()
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        self.assertNotIn(
            "riconciliazione_stripe", rep["anomalie"],
            "il giro si e' fermato al tetto (`parziale` vero, `troncati` non vuoto) e il "
            "Guardiano lo tratta come un verdetto: grida su prenotazioni SANE, che "
            "risultano fantasmi solo perche' Stripe non e' stato letto fino in fondo. "
            "Un falso allarme sui soldi si impara a ignorare (ferrea 10). Rapporto: %r"
            % (rep["anomalie"],))
        self.assertTrue(rep["pulito"],
                        "un giro non finito non e' un'anomalia: e' un controllo a meta'")
        self.assertEqual(rep["conta"], 0, "un giro troncato non si conta fra le anomalie")

    def test_e_DICHIARA_di_non_aver_finito_di_guardare(self):
        """Seconda meta', ed e' quella che impedisce di 'riparare' col silenzio.

        Se un giro troncato smettesse di gridare e basta, avremmo scambiato un allarme
        falso con un punto cieco muto -- e sul percorso dei soldi il secondo e' peggio,
        perche' un allarme fastidioso lo noti e un silenzio no. Deve finire fra i non
        eseguiti. Come si chiami la riga lo decide la riparazione: qui si pretende che
        ci sia."""
        self._banco_col_giro_troncato()
        self._pretendi_che_il_confronto_SIA_PARTITO()
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        self.assertTrue(
            any("riconcili" in str(c) for c in (rep.get("non_eseguiti") or [])),
            "il confronto con Stripe si e' fermato a meta' e il rapporto non lo dichiara "
            "da nessuna parte: chi legge non ha modo di sapere che il controllo piu' "
            "importante ha guardato solo un pezzo. non_eseguiti: %r"
            % (rep.get("non_eseguiti"),))
        # ⛔ E NON DEVE DIRLO CON LA BUGIA COMODA. La riparazione piu' economica che
        # soddisfa l'asserzione qui sopra e' un `return NON_ESEGUITO` secco sul giro
        # troncato: verde qui, e nel referto ci finirebbe «manca la chiave Stripe o il
        # giornale» MENTRE LA CHIAVE C'E' e il giro e' partito. Sarebbe una riga falsa in
        # un rapporto operativo, cioe' il difetto che questa guardia nasce per impedire,
        # travestito da riparazione. Le due situazioni devono restare DISTINGUIBILI da chi
        # legge -- lo stesso principio per cui `NON_ESEGUITO` e `None` restano
        # distinguibili da chi chiama (il commento a `_riconciliazione` lo dice).
        # Il testo non lo detta questa guardia: pretende solo che i due non coincidano.
        mio = [c for c in (rep.get("non_eseguiti") or []) if "riconcili" in str(c)]
        rep_senza_chiave = G.scansiona(self.sys_senza_chiave, ora=lambda: self.now)
        suo = [c for c in (rep_senza_chiave.get("non_eseguiti") or [])
               if "riconcili" in str(c)]
        self.assertNotEqual(
            mio, suo,
            "un giro TRONCATO e una chiave MANCANTE dichiarano la stessa identica riga, "
            "quindi il rapporto dice «manca la chiave» a chiave presente: chi legge "
            "cerchera' una chiave che c'e' invece di guardare il tetto delle pagine. "
            "troncato=%r · senza chiave=%r" % (mio, suo))


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

    def test_il_livello_CRITICO_conta_come_un_guasto_e_non_di_meno(self):
        """⛔ D20 — scritta PRIMA della riparazione e vista ROSSA sul codice di produzione.

        Il lettore del registro filtrava la parola ` ERROR `. Ma il livello piu' grave che
        il codice sa scrivere e' `logger.critical`, che `main_casavip` scrive come
        ` CRITICAL `: un tentativo d'intrusione nel Bunker (`fase83_server.py`, BUNKER),
        il kill-switch globale, la cancellazione FORZATA di un host con obblighi
        (`fase156_erasure.py`) finivano nel registro e l'unico lettore automatico li
        saltava apposta. Il peggio era invisibile e il meno grave no.
        Censimento «porta per un uomo solo» del 2026-09-14, fronte allarmi, rilievo 1."""
        sis = self._sistema_con_registro([
            self._riga(self.now - 300, "CRITICAL",
                       "BUNKER: accesso negato, chiave admin errata (ip mascherato)"),
        ])
        rep = G.scansiona(sis, ora=lambda: self.now)
        self.assertFalse(rep["pulito"],
                         "una riga CRITICAL fresca nel registro e il Guardiano tace: il livello "
                         "piu' grave e' l'unico che nessuno legge. %r" % (rep,))
        self.assertIn("guasti_isolati", rep["anomalie"], rep["anomalie"])
        self.assertTrue(any("BUNKER" in e for e in rep["anomalie"]["guasti_isolati"]["esempi"]),
                        "l'esempio riportato non e' la riga CRITICAL: %r"
                        % (rep["anomalie"]["guasti_isolati"],))

    def test_il_Guardiano_non_conta_la_sua_riga_ne_le_sonde_DICHIARATE_del_giudice(self):
        """⛔ D20 — vista ROSSA prima della riparazione (`conta 4 != 3`: leggeva la propria
        riga-riassunto). Il 14/9, appena ha imparato a leggere i CRITICAL, il Guardiano ha
        gridato «7 stati anomali» per 33 sonde del NOSTRO giudice
        (`collaudi/verifica_produzione.py`, a ogni deploy) — e il giorno dopo avrebbe riletto
        la SUA riga `GUARDIANO: 7 stato/i anomalo/i`, che e' CRITICAL, tenendo l'allarme
        acceso da solo. Rimedio: il giudice DICHIARA la finestra delle sue sonde
        (`fase178.dichiara_sonde_giudice`) e il lettore salta quelle righe e la propria. Una
        negazione NON dichiarata e un ERROR vero contano ancora: le due direzioni in una
        sola guardia («meno guardie», il fondatore, 15/9)."""
        import os
        sis = self._sistema_con_registro([
            self._riga(self.now - 7200, "CRITICAL",
                       "GUARDIANO: 7 stato/i anomalo/i -> {'guasti_isolati': {}}"),
            self._riga(self.now - 3600, "CRITICAL", "BUNKER: accesso NEGATO azione=prove_legali "
                       "motivo=sessione_assente_o_manomessa ip=203.0.113.9"),
            self._riga(self.now - 1800, "CRITICAL", "BUNKER: accesso NEGATO azione=prove_legali "
                       "motivo=sessione_assente_o_manomessa ip=198.51.100.7"),
            # un ERROR vero (fino al 29/9 qui c'era la riga di una CONTROVERSIA APERTA: da D22
            # non e' piu' un guasto, la segnala `_controversie_aperte` col suo nome)
            self._riga(self.now - 300, "ERROR", "RIMBORSO ADMIN INCOMPLETO rif=BVI***01"),
        ])
        gi = G.scansiona(sis, ora=lambda: self.now)["anomalie"].get("guasti_isolati") or {}
        self.assertEqual(gi.get("conta"), 3,
                         "il Guardiano conta la propria riga-riassunto, oppure perde una "
                         "negazione NON dichiarata: %r" % (gi,))
        # il giudice dichiara la finestra della sonda di un'ora fa: quella sparisce, l'altra resta
        from fase178_watchdog import dichiara_sonde_giudice
        dati = os.path.dirname(sis.config.db_finanza)
        self.assertTrue(dichiara_sonde_giudice(dati, inizio=self.now - 3605, fine=self.now - 3595),
                        "misura non valida: la dichiarazione non e' stata scritta")
        gi = G.scansiona(sis, ora=lambda: self.now)["anomalie"].get("guasti_isolati") or {}
        self.assertEqual(gi.get("conta"), 2,
                         "una negazione DENTRO la finestra dichiarata conta ancora come "
                         "intrusione, oppure una FUORI e' sparita: %r" % (gi,))

    def test_il_Guardiano_onora_TUTTE_le_finestre_delle_sue_24_ore_non_solo_l_ultima(self):
        """⛔ D20 — scritta PRIMA della riparazione e vista ROSSA sul codice di produzione.

        Misurato sul server il 2026-09-27: il giro intero delle 18:06:25Z ha scritto
        «GUARDIANO: 6 stato/i anomalo/i» contando le negazioni CRITICAL del 26/9 (20:38 e
        23:41), tutte dall'IP di questo computer (101.57.50.246, riconfermato con
        api.ipify.org il 28/9): le NOSTRE sonde. Erano state dichiarate, ma
        `dichiara_sonde_giudice` riscriveva il file a ogni verifica e ne restava UNA finestra,
        l'ultima: le sonde dei giri precedenti tornavano intrusioni per 24 ore. Bastano due
        verifiche nello stesso giorno (un deploy e la batteria). Come i silenzi di Alertmanager
        (ognuno col suo startsAt/endsAt, molti attivi insieme): qui due giri del giudice a otto
        ore di distanza, due righe CRITICAL ciascuno dentro la propria finestra, e
        un'intrusione vera FUORI da tutte e due. Il Guardiano conta quella, e solo quella."""
        import os
        sonda = ("BUNKER: accesso NEGATO azione=prove_legali "
                 "motivo=sessione_assente_o_manomessa ip=203.0.113.9")
        sis = self._sistema_con_registro([
            self._riga(self.now - 36000, "CRITICAL", sonda),
            self._riga(self.now - 35999, "CRITICAL", sonda),
            self._riga(self.now - 7200, "CRITICAL", sonda),
            self._riga(self.now - 7199, "CRITICAL", sonda),
            self._riga(self.now - 3600, "CRITICAL", "BUNKER: accesso NEGATO azione=prove_legali "
                       "motivo=sessione_assente_o_manomessa ip=198.51.100.7"),
        ])
        from fase178_watchdog import dichiara_sonde_giudice
        dati = os.path.dirname(sis.config.db_finanza)
        for inizio, fine in ((self.now - 36005, self.now - 35995),
                             (self.now - 7205, self.now - 7195)):
            self.assertTrue(dichiara_sonde_giudice(dati, inizio=inizio, fine=fine),
                            "misura non valida: la dichiarazione non e' stata scritta")
        gi = G.scansiona(sis, ora=lambda: self.now)["anomalie"].get("guasti_isolati") or {}
        self.assertEqual(gi.get("conta"), 1,
                         "le sonde di un giro PRECEDENTE del giudice contano come intrusioni "
                         "(resta solo l'ultima finestra), oppure l'intrusione vera e' sparita: %r"
                         % (gi,))
        self.assertTrue(gi["esempi"] and all("198.51.100.7" in e for e in gi["esempi"]),
                        "l'esempio non e' l'intrusione vera: %r" % (gi,))

    def test_le_finestre_scadute_si_buttano_ma_non_prima_che_il_Guardiano_le_rilegga(self):
        """Le finestre non si accumulano per sempre (Alertmanager butta i silenzi scaduti dopo
        `--data.retention`), ma una finestra non puo' sparire finche' il lettore piu' lungo
        (`_guasti_isolati`, ORE_GUASTI_ISOLATI) puo' ancora incontrare le sue righe: sarebbe
        lo stesso falso allarme, rimandato. Il limite lo tiene questa prova, non la memoria."""
        import os
        import fase178_watchdog as wd
        self.assertGreaterEqual(wd.MAX_ETA_SONDE_GIUDICE_SEC, G.ORE_GUASTI_ISOLATI * 3600,
                                "le finestre si buttano prima che il Guardiano smetta di "
                                "rileggerne le righe: le nostre sonde tornano intrusioni")
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        t, m = self.now, wd.MAX_ETA_SONDE_GIUDICE_SEC
        self.assertTrue(wd.dichiara_sonde_giudice(d, inizio=t - 5, fine=t))
        self.assertTrue(wd.dichiara_sonde_giudice(d, inizio=t + m - 5, fine=t + m))
        self.assertEqual(wd.finestra_sonde_giudice(d), [(t - 5, t), (t + m - 5, t + m)],
                         "una finestra ancora dentro la conservazione e' stata buttata")
        self.assertTrue(wd.dichiara_sonde_giudice(d, inizio=t + m + 1, fine=t + m + 1))
        self.assertEqual(wd.finestra_sonde_giudice(d), [(t + m - 5, t + m), (t + m + 1, t + m + 1)],
                         "una finestra scaduta resta nel file: si accumulano per sempre")
        with open(os.path.join(d, wd.NOME_SONDE_GIUDICE)) as f:
            self.assertEqual(len(f.read().splitlines()), 2)


class TestContaGiustaEControversieColLoroNome(_Base):
    """D21 e D22, trovati il 29/9 sera dall'allarme vero della prova con la carta.

    D21: «3 stato/i anomalo/i» per UN errore nel registro -- il conteggio sommava ogni campo
    del riquadro (il numero, le 24 ore, l'esempio). Il «7» del 15/9 erano 34 righe.
    D22: la controversia aperta di a2c63fd8 (una riga ERROR voluta) arrivava come «guasto
    ingoiato che nessuno leggerebbe»: un fatto giusto da segnalare, col nome sbagliato.
    Scritte PRIMA della riparazione e viste ROSSE.
    """
    RIGA_CONTROVERSIA = ("CONTROVERSIA APERTA | riferimento: %s | messaggio: l'ospite contesta "
                         "il servizio, il bonifico all'host e' trattenuto e serve una "
                         "decisione dell'arbitro")
    # gli attrezzi del banco del registro, presi in prestito senza ereditarne le prove
    _sistema_con_registro = TestGuastiIsolatiNelRegistro._sistema_con_registro
    _riga = TestGuastiIsolatiNelRegistro._riga

    def test_UN_errore_nel_registro_e_UN_guasto_non_tre(self):
        sis = self._sistema_con_registro([
            self._riga(self.now - 500, "ERROR", "consumo credito single-use FALLITO")])
        rep = G.scansiona(sis, ora=lambda: self.now)
        self.assertEqual(rep["conta"], 1, rep["anomalie"])
        self.assertIn("trovato 1 stato/i anomalo/i", G.riassunto_html(rep))

    def test_DUE_errori_sono_due(self):
        sis = self._sistema_con_registro([
            self._riga(self.now - 500, "ERROR", "consumo credito single-use FALLITO"),
            self._riga(self.now - 400, "ERROR", "RIMBORSO ADMIN INCOMPLETO rif=abc")])
        self.assertEqual(G.scansiona(sis, ora=lambda: self.now)["conta"], 2)

    def test_una_controversia_aperta_ha_il_SUO_nome_e_non_e_un_guasto(self):
        sis = self._sistema_con_registro([
            self._riga(self.now - 500, "ERROR", self.RIGA_CONTROVERSIA % "a2c63fd8")])
        sis.garanzia.apri("a2c63fd8", 30000, alloggio_id="casa", ora_checkin_ts=self.now)
        self.assertTrue(sis.garanzia.contesta("a2c63fd8", "servizio")["ok"])
        rep = G.scansiona(sis, ora=lambda: self.now)
        self.assertNotIn("guasti_isolati", rep["anomalie"], rep["anomalie"])
        self.assertEqual([c["prenotazione_id"] for c in rep["anomalie"]["controversia_aperta"]],
                         ["a2c63fd8"])
        self.assertEqual(rep["conta"], 1)
        self.assertIn("Controversie aperte", G.riassunto_html(rep))

    def test_decisa_la_controversia_il_Guardiano_TACE(self):
        sis = self._sistema_con_registro([
            self._riga(self.now - 500, "ERROR", self.RIGA_CONTROVERSIA % "a2c63fd8")])
        sis.garanzia.apri("a2c63fd8", 30000, alloggio_id="casa", ora_checkin_ts=self.now)
        sis.garanzia.contesta("a2c63fd8", "servizio")
        self.assertTrue(sis.garanzia.risolvi("a2c63fd8", rimborso_ospite_cents=0)["ok"])
        rep = G.scansiona(sis, ora=lambda: self.now)
        self.assertTrue(rep["pulito"], rep["anomalie"])

    def test_un_riquadro_senza_numero_e_UNA_anomalia(self):
        """Sopravvissuto del giro sul diff (fase186:445): il cambio valuta fermo e' un
        riquadro di quattro campi e resta UNA anomalia (col vecchio conto erano due)."""
        class _Tassi:
            def stato(self, ora):
                return {"configurato": True, "mai_riuscito": True, "eta_ore": None,
                        "ultimo_ok_ts": None}
        self.sys.tassi = _Tassi()
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        self.assertIn("cambio_valuta_fermo", rep["anomalie"], rep["anomalie"])
        self.assertEqual(rep["conta"], 1, rep["anomalie"])

    def test_un_archivio_che_non_sa_elencare_le_controversie_NON_grida(self):
        """Sopravvissuto del giro sul diff (fase186:350): come gli altri controlli del
        Guardiano, un archivio senza quel metodo non e' un'anomalia."""
        class _GaranziaSenzaElenco:
            def aperte_scadute(self, **kw):
                return []
        self.sys.garanzia = _GaranziaSenzaElenco()
        rep = G.scansiona(self.sys, ora=lambda: self.now)
        self.assertTrue(rep["pulito"], rep["anomalie"])

    def test_un_elenco_delle_controversie_ROTTO_e_un_controllo_CIECO(self):
        class _GaranziaRotta:
            def aperte_scadute(self, **kw):
                return []

            def contestate(self, **kw):
                raise RuntimeError("archivio guasto")
        self.sys.garanzia = _GaranziaRotta()
        with self.assertLogs("core_auto.guardiano", level="ERROR"):
            rep = G.scansiona(self.sys, ora=lambda: self.now)
        self.assertIn("_controversie_aperte", rep["anomalie"].get("controllo_cieco", []))

    def test_un_guasto_vero_accanto_alla_controversia_resta_un_guasto(self):
        sis = self._sistema_con_registro([
            self._riga(self.now - 500, "ERROR", self.RIGA_CONTROVERSIA % "a2c63fd8"),
            self._riga(self.now - 400, "ERROR", "RIMBORSO ADMIN INCOMPLETO rif=abc")])
        sis.garanzia.apri("a2c63fd8", 30000, alloggio_id="casa", ora_checkin_ts=self.now)
        sis.garanzia.contesta("a2c63fd8", "servizio")
        rep = G.scansiona(sis, ora=lambda: self.now)
        self.assertEqual(rep["anomalie"]["guasti_isolati"]["conta"], 1, rep["anomalie"])
        self.assertEqual(rep["conta"], 2)


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
