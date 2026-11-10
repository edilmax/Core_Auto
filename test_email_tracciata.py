# -*- coding: utf-8 -*-
"""LE EMAIL PERSE IN SILENZIO — le guardie, scritte PRIMA della riparazione (D20).

⛔ QUESTO FILE E' NATO ROSSO, ED E' IL PUNTO.
Il difetto e' vivo in produzione e sta scritto in due referti d'audit:
`collaudi/audit/15_dipendenze_esterne.md` (§ «LE TRE CHE PERDONO IL MESSAGGIO IN
SILENZIO») e `collaudi/audit/20_sorveglianza.md` (§3.1 e §3.3). In una riga:

    `ProviderEmail.invia()` ritorna un bool onesto -- e NESSUNO lo legge.
    Ogni invio parte in un `threading.Thread(target=prov.invia, ...)`: thread
    demone, valore di ritorno **scartato**, nessuna coda, nessun secondo giro.
    Quando l'SMTP e' giu' spariscono il voucher e il PIN di check-in dell'ospite,
    la conferma di pagamento, il link di reimpostazione password, la ricevuta --
    e perfino l'allarme del Guardiano dei soldi, che esce per email.

E il pezzo che rende il difetto invisibile invece che solo grave:
`fase186_guardiano.py:275` guarda **SOLO gli `ERROR`** del registro, e tutti questi
fallimenti finivano in `logger.warning`. Quindi non solo si perdevano: **non li
contava nessuno**. Per questo la riparazione scrive `logger.error` e non `warning`:
non e' una preferenza di stile, e' l'unico livello che il sorvegliante legge.

⛔ COSA QUESTE GUARDIE NON ESAMINANO (D18 punto 3), dichiarato:
  · non provano che una email ARRIVI: provano che un fallimento **si veda**. La
    consegna dipende da SMTP, dominio, DKIM e dalla casella di chi riceve;
  · fino al 10/11 non c'era una coda durevole (scelta 1 di allora: solo `logger.error`
    + contatore). Dal 10/11, ordine del fondatore, l'email fallita si salva su SQLite e
    si ritenta (classe TestLEmailFallitaSiSalvaESiRitenta): l'allarme e il contatore
    restano, perche' la coda dice che si ritenta, non che e' arrivata;
  · il contatore vive nel processo: un riavvio lo azzera. Dice «da quando sono in
    piedi», non «da sempre»;
  · il terzo dei tre cancelli (il voucher all'ospite) e' verificato **sul sorgente**
    e non chiamando la rotta: costruire una prenotazione pagata dentro questo file
    duplicherebbe meta' di `test_fase83_server.py`. Gli altri due sono
    comportamentali, e sono quelli che il difetto lo attraversano davvero.
"""
import io
import logging
import os
import re
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

QUI = os.path.dirname(os.path.abspath(__file__))
SORGENTE = os.path.join(QUI, "fase83_server.py")
SEG = b"0123456789abcdef0123456789abcdef"
LOGGER = "core_auto.server"


def _sistema_senza_email():
    """Un sistema vero, col provider email SPENTO: e' lo stato che il difetto nasconde."""
    s = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG))
    s.email_provider = None
    return s


def _sorgente():
    with io.open(SORGENTE, encoding="utf-8") as f:
        return f.read()


class _ProviderFinto(object):
    """Un provider che risponde quello che gli dico. Non e' un sostituto pigro:
    e' l'unico modo di provare il ramo «il server ha risposto False» senza un SMTP."""

    def __init__(self, esito=True, solleva=False):
        self.esito = esito
        self.solleva = solleva
        self.chiamate = []

    def invia(self, destinatario, oggetto, corpo_html):
        self.chiamate.append((destinatario, oggetto))
        if self.solleva:
            raise RuntimeError("SMTP esploso")
        return self.esito


# ---------------------------------------------------------------------------
#  1. IL WRAPPER — legge il bool, e su False grida a un livello che si vede
# ---------------------------------------------------------------------------
class TestIlWrapperLeggeIlBool(unittest.TestCase):

    def test_IL_WRAPPER_ESISTE(self):
        """Se questo e' rosso, tutto il resto del file lo e' di conseguenza."""
        import fase83_server
        self.assertTrue(
            hasattr(fase83_server, "_invia_tracciato"),
            "manca `_invia_tracciato`: senza un punto obbligato che LEGGE il bool di "
            "ProviderEmail.invia(), ogni invio resta un thread che butta via la propria "
            "risposta")

    def test_SU_FALSE_SCRIVE_ERROR_E_NON_WARNING(self):
        """⛔ Il livello e' la riparazione. `fase186_guardiano.py:275` legge solo gli
        ERROR: un `warning` qui vale esattamente quanto il silenzio di prima."""
        from fase83_server import _invia_tracciato
        prov = _ProviderFinto(esito=False)
        with self.assertLogs(LOGGER, level="ERROR") as reg:
            esito = _invia_tracciato(prov, "ospite@example.com", "oggetto", "<p>x</p>",
                                     "voucher", "REF-1")
        self.assertFalse(esito, "il wrapper deve restituire il bool del provider")
        testo = "\n".join(reg.output)
        self.assertIn("voucher", testo,
                      "la riga deve dire QUALE email si e' persa: senza il template, "
                      "chi legge il registro sa che qualcosa e' sparito e non cosa")
        self.assertIn("REF-1", testo, "e a quale pratica si riferisce")

    def test_SU_TRUE_NON_GRIDA_E_NON_CONTA(self):
        """L'altra direzione (regola ferrea 10): un allarme provato in un verso solo
        potrebbe gridare sempre, e un allarme sempre acceso viene spento."""
        from fase83_server import _invia_tracciato, email_ko_totale
        prima = email_ko_totale()
        prov = _ProviderFinto(esito=True)
        logging.getLogger(LOGGER).error("ancora vivo")   # assertLogs vuole >=1 riga
        with self.assertLogs(LOGGER, level="ERROR") as reg:
            logging.getLogger(LOGGER).error("segnaposto")
            esito = _invia_tracciato(prov, "ospite@example.com", "o", "<p>x</p>", "voucher")
        self.assertTrue(esito)
        self.assertEqual([r for r in reg.output if "EMAIL" in r.upper()], [],
                         "invio riuscito: nessuna riga di allarme")
        self.assertEqual(email_ko_totale(), prima,
                         "invio riuscito: il contatore non si muove")

    def test_UNA_ECCEZIONE_DEL_PROVIDER_NON_SFUGGE(self):
        """Gira dentro un thread demone: se sollevasse, l'eccezione morirebbe li' e
        saremmo tornati al silenzio -- con in piu' un thread che esplode."""
        from fase83_server import _invia_tracciato
        prov = _ProviderFinto(solleva=True)
        with self.assertLogs(LOGGER, level="ERROR"):
            esito = _invia_tracciato(prov, "ospite@example.com", "o", "<p>x</p>", "voucher")
        self.assertFalse(esito)

    def test_IL_CONTATORE_SALE_DI_UNO(self):
        from fase83_server import _invia_tracciato, email_ko_totale
        prima = email_ko_totale()
        with self.assertLogs(LOGGER, level="ERROR"):
            _invia_tracciato(_ProviderFinto(esito=False), "a@b.com", "o", "<p>x</p>", "t")
        self.assertEqual(email_ko_totale(), prima + 1)

    def test_UN_A_CAPO_NON_FABBRICA_UNA_RIGA_DI_REGISTRO(self):
        """Log-injection: `template` e `riferimento` arrivano da dati di richiesta. Un
        a-capo dentro uno di loro scriverebbe una riga FINTA nel registro che il
        Guardiano legge -- cioe' si potrebbe fabbricare un allarme, o nasconderne uno."""
        from fase83_server import _invia_tracciato
        with self.assertLogs(LOGGER, level="ERROR") as reg:
            _invia_tracciato(_ProviderFinto(esito=False), "a@b.com", "o", "<p>x</p>",
                             "voucher", "REF\nERROR: soldi spariti")
        for riga in reg.output:
            self.assertNotIn("\n", riga.split(":", 2)[-1].strip().replace("\\n", ""),
                             "un a-capo e' passato dentro la riga di registro")


# ---------------------------------------------------------------------------
#  2. NESSUN THREAD DEVE PIU' BUTTARE VIA LA RISPOSTA
# ---------------------------------------------------------------------------
class TestNessunThreadButtaViaLaRisposta(unittest.TestCase):
    """⛔ Guardia STRUTTURALE, e dichiara il proprio denominatore.

    Non basta che il wrapper esista (regola #23: COSTRUITO != COLLEGATO). Il difetto
    torna il giorno che qualcuno aggiunge un invio nuovo copiando la riga di sopra."""

    #  Le forme con cui questo file lancia un invio in background. Si cercano tutte:
    #  cercarne una sola lascerebbe aperte le altre due.
    FORME = (r"target\s*=\s*prov\.invia",
             r"target\s*=\s*ep\.invia",
             r"target\s*=\s*self\._sys\.email_provider\.invia")

    def test_nessun_target_punta_dritto_a_invia(self):
        testo = _sorgente()
        colpevoli = []
        for forma in self.FORME:
            for m in re.finditer(forma, testo):
                riga = testo[:m.start()].count("\n") + 1
                colpevoli.append("fase83_server.py:%d  %s" % (riga, m.group(0)))
        self.assertEqual(
            colpevoli, [],
            "questi thread chiamano `invia` DIRETTAMENTE: il bool che restituisce "
            "muore col thread, e l'email persa non la conta nessuno. Devono passare "
            "da `_invia_tracciato`.\n    %s" % "\n    ".join(colpevoli))

    def test_il_wrapper_e_davvero_usato(self):
        """L'altra meta': se togliessi i `target=` senza mettere niente, la guardia
        di sopra sarebbe verde su un file che non manda piu' nessuna email."""
        quanti = len(re.findall(r"target\s*=\s*_invia_tracciato", _sorgente()))
        self.assertGreaterEqual(
            quanti, 7,
            "mi aspetto almeno 7 punti di invio agganciati al wrapper (voucher, ciclo, "
            "reset password, benvenuto host, esito richiesta, recupero hold, allarme "
            "del Guardiano); trovati %d" % quanti)


# ---------------------------------------------------------------------------
#  3. I TRE CANCELLI: se il provider e' spento, si dice
# ---------------------------------------------------------------------------
class TestSeIlProviderEspentoSiDice(unittest.TestCase):
    """Le tre guardie `if ... email_provider is not None` non avevano `else`: col
    provider spento il ramo veniva saltato e **non restava traccia di niente**.
    ⛔ E l'`else` non deve gridare per il motivo sbagliato: se manca il gettone di
    reset, o la registrazione e' fallita, non c'e' nessuna email da mandare e
    lamentarsi sarebbe un falso allarme (regola ferrea 10)."""

    def setUp(self):
        self.sys = _sistema_senza_email()
        self.r = crea_router(self.sys)

    def _registra(self, email="host@example.com"):
        import json as _j
        return self.r.gestisci("POST", "/api/host/registrazione", body=_j.dumps({
            "email": email, "password": "password123",
            "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
            "lang": "it"}))

    def test_BENVENUTO_HOST_provider_spento_conta_e_registra(self):
        from fase83_server import email_ko_totale
        prima = email_ko_totale()
        with self.assertLogs(LOGGER, level="WARNING") as reg:
            stato, _corpo = self._registra()
        self.assertIn(stato, (200, 201),
                      "la registrazione deve riuscire lo stesso: l'email e' "
                      "best-effort, l'account no")
        self.assertTrue([r for r in reg.output if "EMAIL NON INVIATA" in r],
                        "provider spento e nessuna riga: l'email di benvenuto e' "
                        "sparita in silenzio")
        self.assertEqual(email_ko_totale(), prima + 1,
                         "registrata ma non contata: /api/health non se ne accorge")

    def test_RESET_PASSWORD_provider_spento_conta_e_registra(self):
        import json as _j
        from fase83_server import email_ko_totale
        self._registra("reset@example.com")
        prima = email_ko_totale()
        with self.assertLogs(LOGGER, level="WARNING") as reg:
            stato, _corpo = self.r.gestisci(
                "POST", "/api/host/password_dimenticata",
                body=_j.dumps({"email": "reset@example.com"}))
        self.assertEqual(stato, 200)
        self.assertTrue([r for r in reg.output if "EMAIL NON INVIATA" in r],
                        "provider spento e nessuna riga: chi ha chiesto il reset "
                        "aspettera' per sempre un'email che non e' mai partita")
        self.assertEqual(email_ko_totale(), prima + 1)

    def test_RESET_PASSWORD_su_email_sconosciuta_NON_dice_niente(self):
        """L'altra direzione. Nessun gettone = nessuna email dovuta = nessuna riga."""
        import json as _j
        from fase83_server import email_ko_totale
        prima = email_ko_totale()
        logging.getLogger(LOGGER).warning("segnaposto")
        with self.assertLogs(LOGGER, level="WARNING") as reg:
            logging.getLogger(LOGGER).warning("segnaposto")
            self.r.gestisci("POST", "/api/host/password_dimenticata",
                            body=_j.dumps({"email": "mai-vista@example.com"}))
        self.assertEqual([r for r in reg.output if "EMAIL NON INVIATA" in r], [],
                         "si e' lamentato di un'email che non doveva partire: e' un "
                         "falso allarme, e i falsi allarmi insegnano a ignorare il rosso")
        self.assertEqual(email_ko_totale(), prima,
                         "ha contato un'email che non doveva partire")

    def test_IL_PERCORSO_SANO_NON_SCRIVE_NEANCHE_UN_ERROR(self):
        """⛔ LA GUARDIA CHE MI HA BOCCIATO, e per cui il livello e' `warning`.

        Il primo tentativo di riparazione scriveva `logger.error` anche per «provider
        spento». La suite l'ha respinto: `test_cancellazione_money` pretende ZERO
        `ERROR` sul percorso SANO e ne trovava uno per OGNI prenotazione. Aveva
        ragione -- «provider spento» e' uno STATO di configurazione, non un evento, e
        un rosso a ogni prenotazione diventa rumore e poi viene spento (ferrea 10).
        L'evento vero (`invia` che risponde NO) resta `error`: quello lo deve vedere
        il Guardiano."""
        registratore = logging.getLogger(LOGGER)
        catturati = []

        class _Cattura(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.ERROR:
                    catturati.append(record.getMessage())

        h = _Cattura()
        registratore.addHandler(h)
        try:
            self._registra("sano@example.com")
        finally:
            registratore.removeHandler(h)
        self.assertEqual([m for m in catturati if "EMAIL" in m], [],
                         "un ERROR sul percorso sano: %r" % (catturati,))

    def test_VOUCHER_OSPITE_ha_il_ramo_che_dichiara_il_provider_spento(self):
        """⛔ Verificata SUL SORGENTE, non chiamando la rotta: vedi il limite
        dichiarato in cima al file. Cerca il ramo, non una frase."""
        testo = _sorgente()
        inizio = testo.find("corpo_voucher_html")
        self.assertGreater(inizio, 0, "non trovo il punto dell'email voucher")
        pezzo = testo[inizio:inizio + 4000]
        #  ⛔ Non si cerca una FRASE: si cerca il RAMO e la chiamata che fa il lavoro.
        #  Un commento che dice «qui gestiamo il provider spento» non gestisce niente.
        i_elif = pezzo.find("\n        elif ")
        self.assertGreater(i_elif, 0,
                           "il cancello del voucher non ha un ramo che dichiara il "
                           "provider spento: col provider giu' l'ospite resta senza "
                           "voucher e senza PIN, e nel registro non c'e' niente")
        self.assertIn("_email_provider_spento(", pezzo[i_elif:],
                      "il ramo c'e' ma non registra e non conta niente")


# ---------------------------------------------------------------------------
#  4. LA SALUTE LO DICE A CHI GUARDA DA FUORI
# ---------------------------------------------------------------------------
class TestUnaControversiaApertaAvvisaQualcuno(unittest.TestCase):
    """⛔ D20 — scritta PRIMA della riparazione e vista ROSSA sul codice di produzione.

    L'ospite preme «segnala un problema» dal voucher -> `POST /api/garanzia/contesta` ->
    la garanzia passa a `contestato` e il bonifico all'host viene trattenuto. E poi NIENTE:
    nessuna email, nessuna riga ERROR, e il Guardiano cerca le garanzie ferme in
    `in_garanzia`, non in `contestato` -- per lui «tutto quadra». Soldi dell'host fermi,
    ospite in attesa, e lo sa solo chi apre a mano il riquadro Controversie.
    Censimento «porta per un uomo solo» del 2026-09-14, fronte notifiche.

    Qui si stubba la decodifica del voucher e l'archivio garanzia: cio' che si prova e' il
    CABLAGGIO -- che aprire una controversia produca un ERROR (letto dal Guardiano entro
    24 h) e un'email a chi decide -- non la logica della garanzia, che ha i suoi test.
    """

    def _sistema(self, provider):
        s = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG,
                                       email_alert="allarmi@esempio.test"))
        s.email_provider = provider
        self.assertIsNotNone(getattr(s, "garanzia", None),
                             "misura non valida: senza l'archivio garanzia la rotta risponde 503")
        r = crea_router(s)
        r._garanzia_da_voucher = lambda body: (("BVIP-TEST-0001", {"motivo": "acqua fredda"}),
                                               None)
        s.garanzia.contesta = lambda rif, motivo: {"ok": True, "stato": "contestato",
                                                   "riferimento": rif}
        return s, r

    def test_con_il_provider_ACCESO_parte_un_ERROR_e_una_email_a_chi_decide(self):
        import json as _j
        import time as _t
        prov = _ProviderFinto()
        s, r = self._sistema(prov)
        with self.assertLogs(LOGGER, level="ERROR") as reg:
            stato, corpo = r.gestisci("POST", "/api/garanzia/contesta",
                                      body=_j.dumps({"voucher_token": "x", "motivo": "acqua fredda"}))
        self.assertEqual(stato, 200, corpo)
        self.assertTrue([x for x in reg.output if "CONTROVERSIA" in x],
                        "controversia aperta e nessuna riga ERROR: il Guardiano non la "
                        "vedra' mai. Righe: %r" % (reg.output,))
        for _ in range(100):
            if prov.chiamate:
                break
            _t.sleep(0.02)
        self.assertTrue([o for _d, o in prov.chiamate if "ontroversia" in o],
                        "controversia aperta e nessuna email a chi decide: %r" % (prov.chiamate,))

    def test_con_il_provider_SPENTO_conta_e_registra(self):
        import json as _j
        from fase83_server import email_ko_totale
        s, r = self._sistema(None)
        prima = email_ko_totale()
        with self.assertLogs(LOGGER, level="WARNING") as reg:
            stato, _ = r.gestisci("POST", "/api/garanzia/contesta",
                                  body=_j.dumps({"voucher_token": "x", "motivo": "acqua fredda"}))
        self.assertEqual(stato, 200)
        self.assertEqual(email_ko_totale(), prima + 1,
                         "provider spento: l'avviso della controversia e' sparito senza contare")
        self.assertTrue([x for x in reg.output if "EMAIL NON INVIATA" in x
                         and "controversia" in x.lower()], reg.output)


class TestLaSaluteEspone(unittest.TestCase):
    """Come `guardiano`: una sola richiesta HTTP deve poter dire a una sentinella
    ESTERNA che le email si stanno perdendo. Il volume Docker, da fuori, non si vede."""

    def setUp(self):
        self.r = crea_router(_sistema_senza_email())

    def test_api_health_espone_email_ko(self):
        stato, corpo = self.r.gestisci("GET", "/api/health")
        self.assertEqual(stato, 200)
        self.assertIn("email_ko", corpo,
                      "/api/health non dice quante email si sono perse: da fuori "
                      "nessuno puo' accorgersene")
        self.assertIsInstance(corpo["email_ko"], int)

    def test_il_numero_e_QUELLO_vero_non_una_costante(self):
        """«non e' nullo» non e' una guardia: un `0` scritto a mano passerebbe il
        controllo di sopra e mentirebbe per sempre."""
        from fase83_server import _invia_tracciato
        prima = self.r.gestisci("GET", "/api/health")[1]["email_ko"]
        with self.assertLogs(LOGGER, level="ERROR"):
            _invia_tracciato(_ProviderFinto(esito=False), "a@b.com", "o", "<p>x</p>", "t")
        dopo = self.r.gestisci("GET", "/api/health")[1]["email_ko"]
        self.assertEqual(dopo, prima + 1,
                         "il numero esposto non segue i fallimenti veri")

    def test_la_salute_NON_diventa_degraded_per_una_email(self):
        """⛔ Stessa regola del battito del Guardiano: un'email persa non e' un sito
        giu'. Toccare `status` spegnerebbe un sito SANO dentro nginx e watchdog.sh."""
        from fase83_server import _invia_tracciato
        with self.assertLogs(LOGGER, level="ERROR"):
            _invia_tracciato(_ProviderFinto(esito=False), "a@b.com", "o", "<p>x</p>", "t")
        stato, corpo = self.r.gestisci("GET", "/api/health")
        self.assertEqual(stato, 200)
        self.assertEqual(corpo["status"], "ok")


# ---------------------------------------------------------------------------
#  5. ORDINE DEL FONDATORE 10/11: l'email fallita si salva e si ritenta
# ---------------------------------------------------------------------------
class TestLEmailFallitaSiSalvaESiRitenta(unittest.TestCase):
    """Fino al 10/11 un'email fallita era contata e gridata, ma PERSA (scelta 1 di allora).
    Il fondatore il 10/11: salvata su SQLite e ritentata, senza toccare soldi e sito.
    ⛔ Prima si era riusata la vecchia coda fase16_outbox: portava in produzione fase13 (che
    importa flask, psutil e requests) e altri tre moduli fuori da ogni misura -- le guardie
    di test_parita_ambiente e test_copertura_onesta sono diventate ROSSE. La coda e' ora
    `fase86_email.CodaEmail`, sola libreria standard, con un archivio suo."""

    def setUp(self):
        import shutil
        import tempfile
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.db = os.path.join(self.dir, "coda_email.db")

    def _righe(self):
        import sqlite3
        if not os.path.exists(self.db):
            return []
        con = sqlite3.connect(self.db)
        try:
            return con.execute("SELECT a, oggetto, html, template, riferimento, stato, "
                               "tentativi FROM coda_email ORDER BY id").fetchall()
        finally:
            con.close()

    def _collega(self, prov):
        """Il cablaggio di fase81, rifatto su un provider di prova."""
        from fase81_bootstrap_casavip import collega_coda_email
        coda = collega_coda_email(prov, self.db, avvia=False)
        self.assertIsNotNone(coda, "coda email non collegata")
        return coda

    def test_un_invio_FALLITO_finisce_in_coda(self):
        from fase83_server import _invia_tracciato
        prov = _ProviderFinto(esito=False)
        self._collega(prov)
        with self.assertLogs(LOGGER, level="ERROR"):
            _invia_tracciato(prov, "ospite@example.com", "Il tuo voucher", "<p>v</p>",
                             "voucher", "REF-9")
        righe = self._righe()
        self.assertEqual(len(righe), 1, "email fallita e non salvata: persa")
        self.assertEqual(righe[0], ("ospite@example.com", "Il tuo voucher", "<p>v</p>",
                                    "voucher", "REF-9", "attesa", 0))

    def test_anche_un_ECCEZIONE_finisce_in_coda(self):
        from fase83_server import _invia_tracciato
        prov = _ProviderFinto(solleva=True)
        self._collega(prov)
        with self.assertLogs(LOGGER, level="ERROR"):
            _invia_tracciato(prov, "ospite@example.com", "o", "<p>x</p>", "voucher", "R")
        self.assertEqual(len(self._righe()), 1)

    def test_un_invio_RIUSCITO_non_lascia_niente_in_coda(self):
        from fase83_server import _invia_tracciato
        prov = _ProviderFinto(esito=True)
        self._collega(prov)
        _invia_tracciato(prov, "ospite@example.com", "o", "<p>x</p>", "voucher", "R")
        self.assertEqual(self._righe(), [])

    def test_il_giro_della_coda_la_RIMANDA_e_la_CANCELLA(self):
        """Consegnata = riga cancellata subito: e' un'email con dati personali."""
        from fase83_server import _invia_tracciato
        prov = _ProviderFinto(esito=False)
        coda = self._collega(prov)
        with self.assertLogs(LOGGER, level="ERROR"):
            _invia_tracciato(prov, "ospite@example.com", "Voucher", "<p>v</p>", "voucher", "R")
        prov.esito = True                                    # l'SMTP torna su
        self.assertEqual(coda.un_giro(), 1)
        self.assertEqual(prov.chiamate[-1], ("ospite@example.com", "Voucher"))
        self.assertEqual(self._righe(), [])

    def test_un_nuovo_fallimento_nel_giro_NON_raddoppia_la_coda(self):
        from fase83_server import _invia_tracciato
        prov = _ProviderFinto(esito=False)
        coda = self._collega(prov)
        with self.assertLogs(LOGGER, level="ERROR"):
            _invia_tracciato(prov, "ospite@example.com", "V", "<p>v</p>", "voucher", "R")
        self.assertEqual(coda.un_giro(), 0)
        righe = self._righe()
        self.assertEqual(len(righe), 1, "il ritentativo fallito ha creato una riga nuova")
        self.assertEqual(righe[0][5:], ("attesa", 1), "deve restare in coda per il giro dopo")

    def test_senza_coda_si_comporta_come_prima(self):
        """Provider senza coda (test, o processo senza archivio): nessun guasto."""
        from fase83_server import _invia_tracciato
        with self.assertLogs(LOGGER, level="ERROR"):
            self.assertFalse(_invia_tracciato(_ProviderFinto(esito=False), "a@b.com", "o",
                                              "<p>x</p>", "t"))

    def test_crea_sistema_collega_la_coda_quando_c_e_l_SMTP(self):
        s = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=SEG,
                                       smtp_host="smtp.invalid", db_coda_email=self.db))
        coda = getattr(s.email_provider, "coda_email", None)
        try:
            self.assertIsNotNone(coda,
                                 "SMTP acceso e coda non collegata: le email fallite si perdono")
            self.assertEqual(os.path.abspath(coda.percorso), os.path.abspath(self.db))
        finally:
            if coda is not None:
                coda.ferma()

    def test_la_produzione_salva_la_coda_su_FILE(self):
        """Modo di rompersi 1 (dati effimeri): in RAM la coda morirebbe a ogni riavvio."""
        import main_casavip
        os.environ.pop("DB_CODA_EMAIL", None)
        self.assertEqual(main_casavip.config_da_ambiente().db_coda_email,
                         "data/coda_email.db")


class TestLaCodaEmailDaSola(unittest.TestCase):
    """Il meccanismo della coda (fase86.CodaEmail), con l'orologio in mano alla prova."""

    def setUp(self):
        import shutil
        import tempfile
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.db = os.path.join(self.dir, "coda.db")
        self.t = 1_000_000.0
        self.prov = _ProviderFinto(esito=False)

    def _coda(self, **kw):
        from fase86_email import CodaEmail
        return CodaEmail(self.db, self.prov.invia, ora=lambda: self.t, **kw)

    def _riga(self):
        import sqlite3
        con = sqlite3.connect(self.db)
        try:
            return con.execute("SELECT stato, tentativi, prossimo_ts FROM coda_email").fetchall()
        finally:
            con.close()

    def test_si_ritenta_SUBITO_la_prima_volta(self):
        c = self._coda()
        self.assertTrue(c.accoda("a@b.it", "o", "<p>x</p>"))
        c.un_giro()
        self.assertEqual(len(self.prov.chiamate), 1, "appena accodata va gia' tentata")

    def test_l_attesa_RADDOPPIA_e_si_ferma_a_5_minuti(self):
        from fase86_email import ATTESA_MASSIMA_S, ATTESA_PRIMA_S
        self.assertEqual((ATTESA_PRIMA_S, ATTESA_MASSIMA_S), (30, 300))
        c = self._coda()
        c.accoda("a@b.it", "o", "<p>x</p>")
        visti = []
        for _ in range(6):
            c.un_giro()
            stato, tent, prossimo = self._riga()[0]
            visti.append(int(prossimo - self.t))
            self.t = prossimo
        self.assertEqual(visti, [30, 60, 120, 240, 300, 300])
        self.assertEqual(len(self.prov.chiamate), 6)

    def test_PRIMA_del_tempo_non_si_ritenta(self):
        c = self._coda()
        c.accoda("a@b.it", "o", "<p>x</p>")
        c.un_giro()
        self.t += 29
        c.un_giro()
        self.assertEqual(len(self.prov.chiamate), 1, "ritentata prima dell'attesa")
        self.t += 1
        c.un_giro()
        self.assertEqual(len(self.prov.chiamate), 2, "allo scadere dell'attesa si ritenta")

    def test_all_ultimo_tentativo_NON_CONSEGNABILE_e_grida(self):
        c = self._coda(tentativi=2)
        c.accoda("a@b.it", "o", "<p>x</p>", "voucher", "R-1")
        c.un_giro()
        self.assertEqual(self._riga()[0][:2], ("attesa", 1))
        self.t += 30
        with self.assertLogs("core_auto.email", level="CRITICAL") as log:
            c.un_giro()
        self.assertIn("R-1", "\n".join(log.output))
        self.assertEqual(self._riga()[0][:2], ("non_consegnabile", 2))
        self.t += 10_000
        c.un_giro()
        self.assertEqual(len(self.prov.chiamate), 2, "una non consegnabile non si rimanda")

    def test_un_ECCEZIONE_del_provider_e_un_fallimento(self):
        self.prov.solleva = True
        c = self._coda()
        c.accoda("a@b.it", "o", "<p>x</p>")
        self.assertEqual(c.un_giro(), 0)
        self.assertEqual(self._riga()[0][:2], ("attesa", 1))

    def test_DUE_processi_non_mandano_due_volte_la_stessa_email(self):
        """Il sito e il giro di recupero (cron_sweep_eventi) aprono lo stesso archivio."""
        from fase86_email import PRESA_SCADE_S
        a, b = self._coda(), self._coda()
        a.accoda("a@b.it", "o", "<p>x</p>")
        self.assertTrue(a._prendi(1), "il primo processo prende la riga")
        self.assertEqual(b.un_giro(), 0)
        self.assertEqual(self.prov.chiamate, [], "riga presa da un altro processo e rimandata")
        self.t += PRESA_SCADE_S                 # il primo processo e' morto con la riga in mano
        self.prov.esito = True
        self.assertEqual(b.un_giro(), 1, "riga orfana mai ripresa: email persa")
        self.assertEqual(self._riga(), [])

    def test_si_rifiuta_un_destinatario_che_non_e_un_indirizzo(self):
        c = self._coda()
        for cattivo in (None, "", "senza-chiocciola", 5):
            with self.subTest(cattivo=cattivo):
                self.assertFalse(c.accoda(cattivo, "o", "<p>x</p>"))
        self.assertFalse(os.path.exists(self.db) and self._riga())


class TestLaCodaEmailIConfini(unittest.TestCase):
    """I sopravvissuti di Cosmic Ray sulla coda (10/11, 52 su 197 nella classe CodaEmail):
    numeri, confini e il giro in sottofondo che nessuna prova fermava."""

    def setUp(self):
        import shutil
        import tempfile
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.db = os.path.join(self.dir, "coda.db")
        self.t = 1_000_000.0
        self.prov = _ProviderFinto(esito=False)

    def _coda(self, **kw):
        from fase86_email import CodaEmail
        return CodaEmail(self.db, self.prov.invia, ora=lambda: self.t, **kw)

    def _righe(self):
        import sqlite3
        con = sqlite3.connect(self.db)
        try:
            return con.execute("SELECT id, stato, tentativi FROM coda_email ORDER BY id").fetchall()
        finally:
            con.close()

    def test_i_numeri_della_coda_sono_quelli_dichiarati(self):
        import inspect
        from fase86_email import CodaEmail, PRESA_SCADE_S, TENTATIVI_EMAIL
        self.assertEqual((TENTATIVI_EMAIL, PRESA_SCADE_S), (288, 600))
        self.assertEqual(inspect.signature(CodaEmail.avvia).parameters["ogni_s"].default, 30.0)
        self.assertEqual(inspect.signature(CodaEmail.un_giro).parameters["limite"].default, 20)

    def test_di_serie_si_ritenta_288_volte_poi_si_grida(self):
        c = self._coda()
        c.accoda("a@b.it", "o", "<p>x</p>")
        with self.assertLogs("core_auto.email", level="WARNING") as log:
            for _ in range(400):
                c.un_giro()
                riga = self._righe()[0]
                if riga[1] != "attesa":
                    break
                self.t += 300
        self.assertEqual(self._righe()[0][1:], ("non_consegnabile", 288))
        self.assertEqual(len(self.prov.chiamate), 288)
        critici = [r for r in log.records if r.levelname == "CRITICAL"]
        self.assertEqual(len(critici), 1, "un CRITICAL solo, all'ultimo tentativo")
        self.assertIn("tentativi: 288", critici[0].getMessage())

    def test_con_un_solo_tentativo_ammesso_il_primo_fallimento_e_l_ultimo(self):
        c = self._coda(tentativi=1)
        c.accoda("a@b.it", "o", "<p>x</p>", "voucher", "R-9")
        with self.assertLogs("core_auto.email", level="CRITICAL") as log:
            c.un_giro()
        self.assertEqual(self._righe()[0][1:], ("non_consegnabile", 1))
        self.assertIn("tentativi: 1", log.records[0].getMessage())

    def test_un_fallimento_normale_non_grida_CRITICAL(self):
        c = self._coda(tentativi=5)
        c.accoda("a@b.it", "o", "<p>x</p>")
        with self.assertLogs("core_auto.email", level="DEBUG") as log:
            logging.getLogger("core_auto.email").warning("segnaposto per assertLogs")
            c.un_giro()
        self.assertEqual([r for r in log.records if r.levelname == "CRITICAL"], [])
        self.assertEqual(self._righe()[0][1:], ("attesa", 1))

    def test_una_riga_che_ha_gia_superato_il_tetto_si_chiude_subito(self):
        """Archivio scritto con un tetto piu' alto (es. riavvio con meno tentativi): la riga con
        piu' tentativi del tetto nuovo non si ritenta all'infinito."""
        c10 = self._coda(tentativi=10)
        c10.accoda("a@b.it", "o", "<p>x</p>")
        for _ in range(3):
            c10.un_giro()
            self.t += 300
        self.assertEqual(self._righe()[0][1:], ("attesa", 3))
        with self.assertLogs("core_auto.email", level="CRITICAL"):
            self._coda(tentativi=2).un_giro()
        self.assertEqual(self._righe()[0][1:], ("non_consegnabile", 4))

    def test_la_presa_scade_ESATTAMENTE_a_600_secondi(self):
        a, b = self._coda(), self._coda()
        a.accoda("a@b.it", "o", "<p>x</p>")
        self.assertTrue(a._prendi(1))
        self.assertFalse(b._prendi(1), "riga gia' presa da un processo vivo: non si ruba")
        self.prov.esito = True
        self.t += 599
        self.assertEqual(b.un_giro(), 0, "presa di 599 secondi: il processo e' ancora vivo")
        self.assertFalse(b._prendi(1))
        self.t += 1
        self.assertEqual(b.un_giro(), 1, "presa di 600 secondi: processo morto, si riprende")

    def test_un_giro_manda_al_massimo_20_email(self):
        self.prov.esito = True
        c = self._coda()
        for i in range(21):
            c.accoda("a%d@b.it" % i, "o", "<p>x</p>")
        self.assertEqual(c.un_giro(), 20)
        self.assertEqual(len(self._righe()), 1)
        self.assertEqual(c.un_giro(), 1)

    def test_una_riga_che_non_si_prende_non_ferma_le_altre(self):
        from fase86_email import CodaEmail

        class _UnaPresaDaAltri(CodaEmail):
            def _prendi(self, id_riga):
                return id_riga != 1 and CodaEmail._prendi(self, id_riga)

        self.prov.esito = True
        c = _UnaPresaDaAltri(self.db, self.prov.invia, ora=lambda: self.t)
        c.accoda("primo@b.it", "o", "<p>x</p>")
        c.accoda("secondo@b.it", "o", "<p>x</p>")
        self.assertEqual(c.un_giro(), 1)
        self.assertEqual(self.prov.chiamate, [("secondo@b.it", "o")])

    def test_l_eccezione_del_provider_si_registra_con_la_traccia(self):
        self.prov.solleva = True
        c = self._coda()
        c.accoda("a@b.it", "o", "<p>x</p>")
        with self.assertLogs("core_auto.email", level="WARNING") as log:
            c.un_giro()
        self.assertTrue(any(r.exc_info for r in log.records), "eccezione senza traccia")

    def test_il_giro_in_sottofondo_consegna_regge_un_errore_e_si_ferma(self):
        import time as _t
        self.prov.esito = True
        from fase86_email import CodaEmail
        scoppi = []

        class _ScoppiaUnaVolta(CodaEmail):
            def un_giro(self, limite=20):
                if not scoppi:
                    scoppi.append(1)
                    raise RuntimeError("giro esploso")
                return CodaEmail.un_giro(self, limite)

        c = _ScoppiaUnaVolta(self.db, self.prov.invia)
        c.ferma()                                  # prima dell'avvio: non deve esplodere
        c.accoda("a@b.it", "o", "<p>x</p>")
        with self.assertLogs("core_auto.email", level="ERROR") as log:
            c.avvia(ogni_s=0.01)
            giro = c._giro
            self.assertTrue(giro.daemon, "il giro deve essere un thread demone")
            c.avvia(ogni_s=0.01)
            self.assertIs(c._giro, giro, "avviato due volte: due giri sulla stessa coda")
            fine = _t.time() + 5
            while self._righe() and _t.time() < fine:
                _t.sleep(0.02)
        self.assertEqual(self._righe(), [], "il giro in sottofondo non ha consegnato")
        self.assertTrue(any("giro_fallito" in r.getMessage() and r.exc_info
                            for r in log.records), "errore del giro senza traccia")
        c.ferma()
        giro.join(2)
        self.assertFalse(giro.is_alive(), "ferma() non ferma il giro")


if __name__ == "__main__":
    unittest.main(verbosity=2)
