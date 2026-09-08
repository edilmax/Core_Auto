"""GUARDIA — CASELLA 7 DEL BLOCCO SOLDI: si SALVA l'evento, si risponde, si elabora DOPO.

Testo della casella, letto da `collaudi/piano.py` e NON ricopiato a mano (la chiave della
scheda e' il testo: una copia che coincide quasi non spuntera' mai quella casella):
il gestore dei webhook verifica la firma sul corpo grezzo, SALVA l'evento col suo
identificativo, risponde 200 subito -- e non 200 finche' non e' salvato -- e lo elabora DOPO.

⛔ COS'E' CHE MANCA OGGI, misurato e non supposto. `_webhook_stripe` (`fase83_server.py`)
verifica la firma (quello c'e' gia' ed e' giusto) e poi fa TUTTO dentro la risposta:
conferma, scrive, manda email. E un archivio degli eventi non esiste: cercato su tutto il
progetto (`grep -rniE "eventi_stripe|stripe_event|evt_|webhook_event"` sui `fase*.py`), non
c'e' ne' un modulo ne' una tabella. Quindi oggi alla domanda «questo evento l'abbiamo gia'
ricevuto?» non risponde nessuno.

⛔ PERCHE' NON E' UN CAPRICCIO DI FORMA. Salvare PRIMA e lavorare DOPO separa due domande
che oggi sono una sola: «l'ho ricevuto?» e «l'ho gestito?». La prima deve poter essere vera
in un colpo solo, e non poter fallire a meta'. Finche' il lavoro riesce non si vede niente;
il giorno che una di quelle cose e' lenta o esplode a meta', la risposta che Stripe riceve
non descrive piu' cio' che e' successo davvero.

⛔ E LA RISPOSTA 2xx E' IL PUNTO DI NON RITORNO. Stripe legge 2xx come «gestito» e non
riprova MAI piu': un 200 su un evento che non e' stato nemmeno salvato rende la perdita
DEFINITIVA. E' la stessa ragione gia' pagata quattro volte in `test_webhook_stripe_esiti_persi.py`.

⚠️ QUESTE GUARDIE SONO NATE ROSSE, ed era voluto (D20: prima la guardia, vista rossa, poi la
riparazione). Non asseriscono l'esistenza di un nome -- un nome non e' un comportamento:
chiedono fatti osservabili. Viste rosse il 2026-09-08 sul codice di allora («non esiste
NESSUN archivio degli eventi Stripe»), poi verdi dopo `fase204_eventi_stripe`.

⛔⛔ E LA CASELLA 7 RESTA VUOTA APPOSTA, perche' qui ne e' chiusa META'.
La casella chiede anche «lo elabora DOPO, in un passo separato»: NON e' fatto, l'elaborazione
resta dentro la risposta. Misurato prima di decidere, e la misura e' il motivo: 81 file di
collaudo e 19 banchi passano dal webhook, 120 chiamate in tutto, quasi tutte aspettandosi la
conferma dentro la risposta -- spostarla e' un lavoro a se', sul percorso del denaro, da fare
quando non c'e' altro in volo. Quello che QUI e' chiuso e' il buco vero: un evento non viene
piu' accettato senza essere prima scritto, e uno ricevuto-e-non-gestito si VEDE.
⛔ Nessuno spunti la casella 7 con queste guardie: misurano un'altra cosa, e una casella
spuntata da un attrezzo che guarda altrove e' peggio di una casella vuota.

🔑 PERCHE' UN BANCO PROPRIO E NON UNA SOTTOCLASSE di `TestWebhookStripeEsitiPersi`, che
avrebbe dato setUp e attrezzi gratis: ereditando, i suoi quattro test sarebbero girati una
seconda volta: quattro esecuzioni in piu' e quattro unita' in piu' nel conto della suite,
senza un filo di copertura in piu'. E' la forma che l'appendice #14 denuncia («duplicare 200
test soddisferebbe il conteggio»): il numero direbbe di piu' e la macchina non saprebbe
niente di piu'. Qui il banco e' PIU' PICCOLO del loro, non uguale: nessun host, nessun
alloggio, nessuna prenotazione, perche' queste guardie non guardano l'elaborazione -- solo
la RICEZIONE. E un evento di un tipo che il gestore non tratta risponde
`200 {"ricevuto": true}` senza effetti, il che isola «l'ho archiviato?» da «l'ho gestito?».
"""
import json
import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test

WH = "whsec_evento_archiviato"
# ⛔ VALORE FINTO IN UNA COSTANTE, non scritto sul posto: `bandit` (B106) segnala un
# argomento il cui NOME contiene «secret»/«key» quando riceve un valore letterale. Passandolo
# per variabile il rilievo non nasce -- e un rilievo NUOVO va chiuso nel codice, perche' la
# fotografia del cricchetto si rifa' solo per DIMINUIRE il debito.
CHIAVE_FINTA = "sk"

# Un tipo che questo prodotto non tratta: il gestore risponde `200 {"ricevuto": true}` e non
# tocca niente. Serve a separare la RICEZIONE dall'ELABORAZIONE.
TIPO_NON_TRATTATO = "customer.subscription.updated"


class GuastoIniettato(Exception):
    """Sollevata dal COLLABORATORE sostituito, mai dal codice sotto esame."""


class TestLEventoSiArchiviaPrimaDiRispondere(unittest.TestCase):

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db", db_kyc=f"{d}/k.db",
            commissione_bps=1500, psp_bps=300, stripe_secret_key=CHIAVE_FINTA,
            stripe_webhook_secret=WH, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://b.com")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    # ── attrezzi ────────────────────────────────────────────────────────────────
    def _posta(self, evento):
        pl = json.dumps(evento)
        return self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                               {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})

    def _evento(self, eid):
        """Un evento vero di Stripe porta un `id` in cima (evt_...): e' LA chiave."""
        return {"id": eid, "type": TIPO_NON_TRATTATO,
                "data": {"object": {"id": "sub_x"}}}

    def _archivio(self):
        """L'archivio degli eventi ricevuti, o None se non esiste ancora."""
        return getattr(self.sis, "eventi_stripe", None)

    # ── la premessa si verifica PRIMA del verdetto (sbaglio S7) ─────────────────
    def test_la_PREMESSA_regge_l_evento_finto_viene_accettato(self):
        """Se il banco non riuscisse nemmeno a far accettare un evento firmato, le tre
        guardie qui sotto accuserebbero il prodotto per un guasto del banco (sbaglio S3)."""
        s, corpo = self._posta(self._evento("evt_premessa"))
        self.assertEqual(s, 200,
                         "un evento firmato e di tipo non trattato deve essere accettato "
                         "con 200: se non lo e', a essere rotto e' questo banco. Corpo: %s"
                         % (corpo,))

    def test_l_evento_viene_SALVATO_col_suo_identificativo(self):
        s, _ = self._posta(self._evento("evt_archiviato_1"))
        self.assertEqual(s, 200)
        archivio = self._archivio()
        self.assertIsNotNone(
            archivio,
            "non esiste NESSUN archivio degli eventi Stripe: il gestore ha risposto 200 e "
            "dell'evento non resta traccia col suo identificativo. Senza, la casella 8 (uno "
            "stesso evento consegnato due volte si elabora una volta sola) non ha su cosa "
            "poggiare, e la 9 (un'elaborazione fallita non sparisce) nemmeno.")
        self.assertTrue(
            archivio.esiste("evt_archiviato_1"),
            "l'evento e' stato accettato con 200 ma non risulta salvato col suo id")

    def test_se_l_evento_NON_si_salva_la_risposta_non_e_2xx(self):
        """L'altra direzione, ed e' quella che rende utile la prima.

        Un archivio che salva quando tutto va bene non serve a niente se, quando NON riesce
        a salvare, la risposta e' 200 lo stesso: Stripe legge 2xx e non ritenta mai piu'.
        ⛔ Il guasto sta nel COLLABORATORE sostituito su questa istanza, mai nel codice sotto
        esame: nessun `fase*.py` viene toccato, quindi non c'e' nessuna finestra in cui un
        file di produzione resti rotto e non serve nessun ripristino byte-identico.
        """
        archivio = self._archivio()
        if archivio is None:
            self.fail("non c'e' nessun archivio degli eventi da far esplodere: la casella 7 "
                      "non e' costruita, e questa guardia descrive cio' che deve esistere")

        def _esplode(*_a, **_k):
            raise GuastoIniettato("archivio degli eventi bloccato")

        originale = archivio.salva
        archivio.salva = _esplode
        try:
            s, corpo = self._posta(self._evento("evt_non_salvabile"))
        finally:
            archivio.salva = originale
        self.assertFalse(
            200 <= int(s) < 300,
            "il salvataggio dell'evento e' fallito e la risposta e' %s: Stripe legge 2xx "
            "come «gestito» e NON riprova mai piu'. Un 2xx su un evento mai salvato rende la "
            "perdita definitiva. Corpo: %s" % (s, corpo))

    def _evento_identita(self, eid, hid="host_che_non_esiste"):
        """Un evento che il gestore TRATTA e che qui non puo' andare a buon fine.

        Serve a ottenere il caso «salvato ma NON gestito» senza rompere niente a mano: la
        macchina a stati del KYC rifiuta una conferma su un host mai avviato, il gestore se
        ne accorge e risponde non-2xx perche' Stripe lo riporti. E' il comportamento che
        `test_webhook_stripe_esiti_persi.py` ha gia' guadagnato: qui lo si USA, non lo si
        riscrive.
        """
        return {"id": eid, "type": "identity.verification_session.verified",
                "data": {"object": {"status": "verified", "metadata": {"host_id": hid}}}}

    def test_un_evento_GESTITO_risulta_elaborato_e_non_resta_fra_i_pendenti(self):
        """Le due domande vanno tenute separate: «l'ho ricevuto?» e «l'ho gestito?»."""
        s, _ = self._posta(self._evento("evt_gestito"))
        self.assertEqual(s, 200)
        archivio = self._archivio()
        self.assertTrue(archivio.esiste("evt_gestito"))
        self.assertTrue(archivio.elaborato("evt_gestito"),
                        "l'evento e' stato gestito con 200 ma risulta ancora da elaborare")
        self.assertNotIn("evt_gestito", [p["evt_id"] for p in archivio.pendenti()],
                         "un evento gia' gestito continua a risultare in sospeso: chi guarda "
                         "l'elenco dei buchi vedrebbe un buco che non c'e' (ferrea 10)")

    def test_un_evento_SALVATO_ma_NON_gestito_resta_VISIBILE(self):
        """Il caso che conta: ricevuto sì, gestito no. Deve restare VISIBILE.

        ⛔ «non c'e'» e «c'e' e non e' stato gestito» hanno rimedi OPPOSTI -- il primo e' un
        evento perso per sempre, il secondo un lavoro rimasto indietro che si puo' ancora
        recuperare. Un archivio che li confondesse manderebbe a cercare nel posto sbagliato
        (e' l'osservabile debole della regola ferrea 9).
        """
        s, corpo = self._posta(self._evento_identita("evt_non_gestito"))
        self.assertFalse(
            200 <= int(s) < 300,
            "PREMESSA CADUTA: questo evento doveva NON essere applicabile e invece ha avuto "
            "%s. Senza il fallimento, questa guardia non starebbe misurando niente (S7). "
            "Corpo: %s" % (s, corpo))
        archivio = self._archivio()
        self.assertTrue(
            archivio.esiste("evt_non_gestito"),
            "l'evento e' stato SCARTATO senza lasciare traccia: il salvataggio deve avvenire "
            "PRIMA del tentativo di gestirlo, non dopo che e' andato bene")
        self.assertFalse(archivio.elaborato("evt_non_gestito"),
                         "la gestione e' fallita e l'evento risulta elaborato lo stesso")
        self.assertIn(
            "evt_non_gestito", [p["evt_id"] for p in archivio.pendenti()],
            "l'evento e' stato ricevuto e non gestito, e non compare fra i pendenti: cosi' "
            "quel buco non lo vede nessuno")


if __name__ == "__main__":
    unittest.main(verbosity=2)
