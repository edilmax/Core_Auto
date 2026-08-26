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
  · non c'e' nessuna coda durevole ne' un secondo tentativo piu' tardi: e' la
    scelta 1 del fondatore (solo `logger.error` + contatore). Un'email persa resta
    persa -- ma da adesso **qualcuno lo sa entro 24 ore**;
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
