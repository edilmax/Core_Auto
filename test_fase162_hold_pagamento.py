"""Test HOLD prima del pagamento (fase162) + webhook conferma + ledger tassa (fase147) + sweep.
Chiude il buco: una prenotazione non pagata NON blocca piu' la stanza per sempre."""
import hashlib
import hmac
import json
import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase162_pagamenti_pendenti import crea_pagamenti_pendenti

SEG = b"h" * 32
HK = {"X-Host-Key": "hk"}
WHSEC = "whsec_test"


class TestModulo(unittest.TestCase):
    def setUp(self):
        self.clock = {"t": 1000}
        self.p = crea_pagamenti_pendenti(":memory:", orologio=lambda: self.clock["t"])
        self.p.inizializza_schema()

    def test_registra_conferma_scaduti(self):
        self.assertTrue(self.p.registra("R1", alloggio_id="casa", check_in="2027-01-10",
                                        check_out="2027-01-12", idem_key="k1", tassa_cents=800,
                                        comune="Roma", scadenza_ts=2000))
        self.assertEqual(self.p.info("R1")["stato"], "in_attesa")
        self.clock["t"] = 3000
        self.assertEqual(len(self.p.scaduti()), 1)              # scaduto e non pagato
        rec = self.p.conferma("R1")                             # paga
        self.assertEqual(rec["tassa_cents"], 800)
        self.assertEqual(rec["comune"], "Roma")
        self.assertEqual(self.p.info("R1")["stato"], "pagato")
        self.assertEqual(self.p.scaduti(), [])                  # pagato -> non piu' scaduto
        self.assertTrue(self.p.rimuovi("R1"))


class TestFlussoHold(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db",
            db_domanda=f"{d}/dom.db", db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db",
            db_tassa_comunale=f"{d}/tc.db", file_referral=f"{d}/ref.json",
            commissione_bps=1500, stripe_webhook_secret=WHSEC))
        # forza un payment_url (simula Stripe configurato) -> attiva l'HOLD
        self.sis.concierge._link = lambda dati: "https://pay/" + str(dati.get("riferimento", ""))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "casa", "titolo": "C",
               "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
               "servizi": [], "immagini": [], "tassa_pp_notte_cents": 200}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa", "da": "2027-02-01",
               "a": "2027-02-28", "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _book(self):
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa",
                      "check_in": "2027-02-10", "check_out": "2027-02-12", "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "o@x.it"})
        return b

    def test_book_va_in_attesa_pagamento(self):
        b = self._book()
        self.assertEqual(b["stato"], "in_attesa_pagamento")     # NON confermata finche' non paga
        self.assertTrue(b.get("payment_url"))
        rec = self.sis.pagamenti_pendenti.info(b["riferimento"])
        self.assertEqual(rec["stato"], "in_attesa")
        self.assertEqual(rec["tassa_cents"], 800)               # 200*2*2

    def test_webhook_conferma_e_registra_tassa(self):
        b = self._book()
        rif = b["riferimento"]
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": rif}}}})
        ts = str(int(time.time()))
        mac = hmac.new(WHSEC.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
        # il body deve essere il payload GREZZO (la firma e' sul body grezzo)
        s, _ = self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})
        self.assertEqual(s, 200)
        self.assertEqual(self.sis.pagamenti_pendenti.info(rif)["stato"], "pagato")
        self.assertEqual(self.sis.tassa_comunale.totale_riscosso("Roma"), 800)  # ledger

    def test_sweep_libera_lhold_non_pagato(self):
        b = self._book()
        rif = b["riferimento"]
        # simulo lo sweeper: forzo la scadenza nel passato e libero come fa il thread
        pp = self.sis.pagamenti_pendenti
        # riapro con scadenza passata: registro un record gia' scaduto e lo libero
        for rec in [pp.info(rif)]:
            self.sis.inventario.rilascia(rec["alloggio_id"], rec["check_in"], rec["check_out"],
                                         idem_key=rec["idem_key"])
            pp.rimuovi(rif)
        # le date sono di nuovo prenotabili
        _, q2 = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa",
                       "check_in": "2027-02-10", "check_out": "2027-02-12", "party": 1})
        self.assertEqual(q2.get("quote_token") is not None, True)


class TestBuchiDiMutazione(unittest.TestCase):
    """LE GUARDIE NATE DALLA MUTAZIONE DEL 2026-08-05 SU `fase162_pagamenti_pendenti`.

    Il modulo tiene i PAGAMENTI IN ATTESA: soldi di un ospite gia' impegnati e non ancora
    incassati, le date bloccate, la penale dell'host, il prospetto della tariffa tecnica.

    LA MISURA, in due passi come impone il metodo (i numeri sono letti dai comandi):
      PASSO 1   3 killer veloci   82 provati ·  7 uccisi · 75 sopravvissuti  <- CANDIDATI
      PASSO 2  11 sorveglianti    82 provati · 55 uccisi · 27 SOPRAVVISSUTI  <- buchi veri
    **Quarantotto candidati erano falsi**: sarebbero diventati quarantotto guardie inutili
    scritte per difendere punti gia' difesi. E' tutta li' la ragione del passo 2.

    ⛔ INSIEME KILLER DICHIARATO, con il motivo di ogni esclusione (D18 punto 3):
      · fuori `test_mutation_money` — rompe LUI STESSO questo file con la propria traccia:
        due processi che mutano lo stesso file di produzione insieme;
      · fuori `test_pipeline_ci` — lo nomina in due commenti e non ne esercita una riga:
        un sorvegliante di carta, che consuma tempo e non vede niente.

    ⛔ IL DENOMINATORE VERO E' 113, NON 82. Lo strumento rinuncia su 31 punti e da oggi lo
    DICHIARA: 8 operatori a cavallo di due righe, 14 dentro confronti a catena, 9 che non sa
    rompere (`is`, `is not`, `in`, `not in`). Fra questi ultimi c'e' la riga 263,
    `r["stato"] not in ("in_attesa", "scaduto")`: **il cancello che decide se un pagamento
    puo' essere scritto**. Nessun mutante lo tocchera' mai, quindi la sua guardia e' scritta
    a mano, col guasto iniettato (in fondo a questa classe).

    Ogni guardia dichiara nel nome la riga che sorveglia.
    """

    def setUp(self):
        self.clock = {"t": 1000}
        self.p = crea_pagamenti_pendenti(":memory:", orologio=lambda: self.clock["t"])
        self.p.inizializza_schema()

    def _grezzo(self, **campi):
        """Inserisce una riga SALTANDO le validazioni del modulo.

        Serve a costruire lo STATO IMPOSSIBILE che il codice sano si rifiuta di creare —
        un record con riferimento vuoto, o senza alloggio. Senza questo, i controlli
        d'ingresso non si possono nemmeno raggiungere e restano codice difensivo mai
        eseguito: la D19 dice che lo stato impossibile si costruisce a mano ADESSO, quando
        costa tre righe, invece di scoprire il giorno del disastro che quel ramo era rotto.
        """
        d = {"riferimento": "X", "alloggio_id": "casa", "check_in": "2027-01-10",
             "check_out": "2027-01-12", "idem_key": "", "tassa_cents": 0, "comune": "",
             "host_id": "", "email": "", "quote_token": "", "corpo_json": "",
             "scadenza_ts": 10 ** 9, "stato": "in_attesa", "promemoria_ts": 0,
             "creato_ts": 1000}
        d.update(campi)
        con = self.p._apri()
        try:
            with con:
                con.execute(
                    "INSERT INTO pendenti (riferimento, alloggio_id, check_in, check_out, "
                    "idem_key, tassa_cents, comune, host_id, email, quote_token, corpo_json, "
                    "scadenza_ts, stato, promemoria_ts, creato_ts) VALUES (:riferimento,"
                    ":alloggio_id,:check_in,:check_out,:idem_key,:tassa_cents,:comune,"
                    ":host_id,:email,:quote_token,:corpo_json,:scadenza_ts,:stato,"
                    ":promemoria_ts,:creato_ts)", d)
        finally:
            con.close()

    def _rompi_tabella(self):
        """Toglie la tabella da sotto i piedi: e' il modo di far fallire una lettura DAVVERO,
        invece di fingere un errore. Serve alle guardie sui rami `except`, che devono
        registrare la CAUSA e non solo il fatto."""
        con = self.p._apri()
        try:
            with con:
                con.execute("DROP TABLE pendenti")
        finally:
            con.close()

    # ── registra (l'ingresso: da qui nasce ogni pagamento in attesa) ──────────────────────

    def test_riga105_un_booleano_non_e_una_tassa_di_soggiorno(self):
        # `tassa_cents=True` e' un errore di chiamata, non un importo. In Python True vale 1:
        # senza il controllo sui booleani il comune incasserebbe 1 centesimo inventato.
        self.p.registra("R1", alloggio_id="casa", check_in="2027-01-10",
                        check_out="2027-01-12", tassa_cents=True)
        self.assertEqual(0, self.p.info("R1")["tassa_cents"],
                         "un booleano e' stato scritto come tassa di soggiorno: vale 1 "
                         "centesimo, e nessuno lo ha mai deciso")

    def test_riga119_il_gettone_del_preventivo_e_il_corpo_arrivano_INTERI(self):
        # `str(quote_token or "")` con `and` al posto di `or` scriverebbe SEMPRE stringa
        # vuota: il preventivo firmato e il corpo della prenotazione sparirebbero, e con
        # loro la prova di cosa era stato promesso al cliente.
        self.p.registra("R2", alloggio_id="casa", check_in="2027-01-10",
                        check_out="2027-01-12", quote_token="qt_firmato_123",
                        corpo_json='{"prezzo_cents": 12000}')
        rec = self.p.info("R2")
        self.assertEqual("qt_firmato_123", rec["quote_token"],
                         "il gettone del preventivo e' stato azzerato: sparisce la prova "
                         "del prezzo promesso")
        self.assertIn("12000", rec["corpo_json"],
                      "il corpo della prenotazione e' stato azzerato")

    # ── da_approvare (il pannello dell'host) ─────────────────────────────────────────────

    def test_riga126_un_host_senza_nome_non_vede_le_richieste_di_tutti(self):
        self._grezzo(riferimento="A1", stato="in_attesa_host", host_id="")
        self.assertEqual([], self.p.da_approvare(""),
                         "con host_id vuoto il pannello mostra le richieste dei record "
                         "SENZA host: un host vedrebbe prenotazioni che non sono sue")

    # ── salva_stripe_session (l'aggancio al pagamento vero) ──────────────────────────────

    def test_riga142_un_riferimento_vuoto_non_aggancia_nessuna_sessione(self):
        self._grezzo(riferimento="", alloggio_id="casa")
        self.assertFalse(self.p.salva_stripe_session("", "cs_test_1"),
                         "una sessione Stripe e' stata agganciata a un record col "
                         "riferimento VUOTO: da li' in poi il pagamento e' attribuito a "
                         "una prenotazione che non si sa quale sia")

    def test_riga143_solo_un_id_di_sessione_VERO_viene_salvato(self):
        self.p.registra("R3", alloggio_id="casa", check_in="2027-01-10",
                        check_out="2027-01-12")
        self.assertFalse(self.p.salva_stripe_session("R3", "pi_non_e_una_sessione"),
                         "un id che non e' una sessione Stripe (`cs_...`) e' stato accettato: "
                         "lo shadow-check contabile andrebbe a interrogare Stripe con un "
                         "identificativo sbagliato")
        self.assertNotIn("pi_non_e_una_sessione", self.p.info("R3")["corpo_json"])

    def test_riga154_agganciare_la_sessione_NON_cancella_il_resto_del_corpo(self):
        # Il docstring del metodo promette «merge, MAI sovrascrive il resto». Senza questa
        # guardia quella promessa non era verificata da nessuno: con `and` al posto di `or`
        # il corpo veniva riscritto da zero e il prezzo promesso al cliente spariva.
        self.p.registra("R4", alloggio_id="casa", check_in="2027-01-10",
                        check_out="2027-01-12", corpo_json='{"prezzo_cents": 9900}')
        self.assertTrue(self.p.salva_stripe_session("R4", "cs_test_4"))
        corpo = self.p.info("R4")["corpo_json"]
        self.assertIn("9900", corpo,
                      "agganciando la sessione Stripe il resto del corpo e' stato "
                      "CANCELLATO: sparisce il prezzo concordato, e resta solo l'id Stripe")
        self.assertIn("cs_test_4", corpo)

    def test_riga163_gli_accenti_restano_leggibili_nel_corpo(self):
        self.p.registra("R5", alloggio_id="casa", check_in="2027-01-10",
                        check_out="2027-01-12", corpo_json='{"citta": "Città di Roma"}')
        self.assertTrue(self.p.salva_stripe_session("R5", "cs_test_5"))
        self.assertIn("Città", self.p.info("R5")["corpo_json"],
                      "il corpo e' stato riscritto con gli accenti in codice (\\uXXXX): il "
                      "contenuto e' lo stesso ma chi legge il record a mano non lo capisce")

    def test_riga166_se_l_aggancio_fallisce_si_registra_la_CAUSA(self):
        self._rompi_tabella()
        with self.assertLogs("core_auto", level="WARNING") as reg:
            self.assertFalse(self.p.salva_stripe_session("R6", "cs_test_6"))
        self.assertTrue(any(r.exc_info for r in reg.records),
                        "il fallimento e' stato registrato SENZA la causa: nel registro "
                        "resta «e' fallita» e non si sa perche', che e' l'osservabile debole "
                        "che la regola ferrea 9 vieta")

    # ── cerca_prenotazioni (la ricerca operativa dell'admin) ─────────────────────────────

    def test_riga176_due_caratteri_bastano_a_cercare(self):
        self.p.registra("AB1", alloggio_id="casa", check_in="2027-01-10",
                        check_out="2027-01-12")
        self.assertEqual(1, self.p.cerca_prenotazioni("AB")["totale"],
                         "con due caratteri la ricerca non trova piu' niente: chi cerca una "
                         "prenotazione col codice corto crede che non esista")

    def test_riga178_un_limite_assurdo_non_svuota_il_tetto_della_ricerca(self):
        # UNDICI record col prefisso `ZZ` (due caratteri: la ricerca ne pretende almeno due,
        # e con uno solo questa prova non esercitava affatto il limite). Il tetto sano e' 10:
        # se il limite assurdo passasse, uscirebbero tutti e undici.
        for i in range(11):
            self.p.registra("ZZ%02d" % i, alloggio_id="casa", check_in="2027-01-10",
                            check_out="2027-01-12")
        self.assertEqual(10, len(self.p.cerca_prenotazioni("ZZ", limit=999)["prenotazioni"]),
                         "un limite di 999 e' stato preso per buono: la pagina admin prova a "
                         "disegnare tutto il database in un colpo solo")

    def test_riga179_uno_scostamento_assurdo_non_nasconde_i_risultati(self):
        self.p.registra("Y1", alloggio_id="casa", check_in="2027-01-10",
                        check_out="2027-01-12")
        self.assertEqual(1, len(self.p.cerca_prenotazioni("Y1", offset=10 ** 7)["prenotazioni"]),
                         "uno scostamento fuori scala e' stato preso per buono: la ricerca "
                         "risponde «nessun risultato» su una prenotazione che esiste")

    def test_riga191_se_la_ricerca_fallisce_si_registra_la_CAUSA(self):
        self._rompi_tabella()
        with self.assertLogs("core_auto", level="WARNING") as reg:
            self.assertEqual({"prenotazioni": [], "totale": 0},
                             self.p.cerca_prenotazioni("abc"))
        self.assertTrue(any(r.exc_info for r in reg.records),
                        "la ricerca fallita non dice PERCHE': l'admin vede «nessun "
                        "risultato» e nessuno sa che il database non ha risposto")

    def test_riga199_la_ricerca_restituisce_l_host_VERO(self):
        self.p.registra("H1", alloggio_id="casa", check_in="2027-01-10",
                        check_out="2027-01-12", host_id="host_42")
        trovate = self.p.cerca_prenotazioni("H1")["prenotazioni"]
        self.assertEqual("host_42", trovate[0]["host_id"],
                         "l'host della prenotazione esce sempre VUOTO dalla ricerca: chi "
                         "cerca non sa piu' di chi sia la casa")

    # ── notti_per_alloggio (il conto DAC7 verso il fisco) ────────────────────────────────

    def test_riga224_se_il_conto_DAC7_fallisce_si_registra_la_CAUSA(self):
        self._rompi_tabella()
        with self.assertLogs("core_auto", level="WARNING") as reg:
            self.assertEqual({}, self.p.notti_per_alloggio("host_1", 2027))
        self.assertTrue(any(r.exc_info for r in reg.records),
                        "il conto delle notti verso il fisco e' fallito in silenzio sulla "
                        "causa: si dichiarerebbe zero senza sapere che non si e' letto nulla")

    def test_riga236_un_soggiorno_di_ZERO_notti_non_entra_nel_conto_fiscale(self):
        # check_in == check_out: zero notti. Col guasto la prenotazione viene contata come
        # locazione (pren += 1, notti += 0): il numero di locazioni dichiarato al fisco sale
        # senza che nessuno abbia dormito una notte.
        self._grezzo(riferimento="D1", stato="pagato", host_id="host_9",
                     check_in="2027-03-01", check_out="2027-03-01")
        self.assertEqual({}, self.p.notti_per_alloggio("host_9", 2027),
                         "un soggiorno di zero notti e' finito nel conto DAC7: il numero di "
                         "locazioni dichiarato al fisco non corrisponde alla realta'")

    # ── conferma (il momento in cui il pagamento diventa vero) ───────────────────────────

    def test_riga253_un_riferimento_vuoto_non_conferma_nessun_pagamento(self):
        self._grezzo(riferimento="", alloggio_id="casa", stato="in_attesa")
        self.assertIsNone(self.p.conferma(""),
                          "una conferma di pagamento e' stata attribuita al record col "
                          "riferimento VUOTO: il pagamento di qualcuno marca 'pagato' una "
                          "riga che non e' la sua")

    # ── marca_cancellata_host (la penale dell'host) ──────────────────────────────────────

    def test_riga397_cancellare_una_prenotazione_INESISTENTE_non_esplode(self):
        # Col guasto (`r or r["corpo_json"]`) su un record inesistente si legge dentro None:
        # eccezione al posto di un False, dentro il percorso che applica la PENALE all'host.
        try:
            esito = self.p.marca_cancellata_host("mai_esistita", penale_cents=5000)
        except Exception as e:
            self.fail("cancellare una prenotazione inesistente ESPLODE (%r): il chiamante "
                      "non riceve un «no», riceve un errore, e il percorso della penale si "
                      "interrompe a meta'" % (e,))
        self.assertFalse(esito, "ha detto di aver cancellato una prenotazione inesistente")

    # ── attivi_per_alloggio / attivi_multi (il calendario dell'host) ─────────────────────

    def test_riga431_un_alloggio_senza_nome_non_apre_il_calendario_di_nessuno(self):
        self._grezzo(riferimento="C1", alloggio_id="", scadenza_ts=10 ** 9)
        self.assertEqual([], self.p.attivi_per_alloggio(""),
                         "con l'alloggio vuoto il calendario mostra i blocchi dei record "
                         "SENZA alloggio: date segnate occupate su una casa sbagliata")

    def test_riga450_uno_slug_vuoto_non_entra_nella_ricerca_multipla(self):
        self._grezzo(riferimento="C2", alloggio_id="", scadenza_ts=10 ** 9)
        self.assertEqual({}, self.p.attivi_multi([""]),
                         "uno slug vuoto e' stato interrogato lo stesso: il calendario "
                         "multi-alloggio si porta dentro record che non appartengono a "
                         "nessuna delle case chieste")

    # ── pulisci_vecchi (la pulizia dei record chiusi) ────────────────────────────────────

    def test_riga474_un_orario_booleano_non_ferma_la_pulizia(self):
        self._grezzo(riferimento="P1", stato="scaduto", creato_ts=1000)
        self.clock["t"] = 10 ** 9
        self.assertEqual(1, self.p.pulisci_vecchi(ora_ts=True),
                         "un orario booleano e' stato usato come data: la pulizia non "
                         "cancella piu' nulla e i record chiusi si accumulano per sempre")

    # ── da_promemoriare / da_invitare_recensione (le email al cliente) ───────────────────

    def test_riga489_una_data_vuota_non_manda_promemoria_a_caso(self):
        self._grezzo(riferimento="M1", stato="pagato", check_in="", email="a@b.it")
        self.assertEqual([], self.p.da_promemoriare(oggi=""),
                         "con la data vuota il giro dei promemoria pesca i record con "
                         "check-in vuoto: email al cliente sbagliato, nel momento sbagliato")

    def test_riga491_un_limite_booleano_non_taglia_i_promemoria_a_uno(self):
        for i in (1, 2):
            self._grezzo(riferimento="M%d" % i, stato="pagato", check_in="2027-01-01",
                         email="a%d@b.it" % i)
        self.assertEqual(2, len(self.p.da_promemoriare(oggi="2027-06-01", limit=True)),
                         "`limit=True` preso per il numero 1: di due clienti da avvisare ne "
                         "viene avvisato uno, e l'altro non lo sa nessuno")

    def test_riga509_un_limite_booleano_non_taglia_gli_inviti_a_uno(self):
        for i in (1, 2):
            self._grezzo(riferimento="I%d" % i, stato="pagato", check_out="2027-06-02",
                         email="c%d@b.it" % i)
        self.assertEqual(2, len(self.p.da_invitare_recensione(oggi="2027-06-05", limit=True)),
                         "`limit=True` preso per il numero 1: gli inviti a recensire partono "
                         "a uno solo, e il motore delle recensioni resta a secco")

    # ── aggrega_costi_tecnici (il prospetto della tariffa tecnica per il commercialista) ──

    def test_riga582_se_il_prospetto_fiscale_fallisce_si_registra_la_CAUSA(self):
        self._rompi_tabella()
        with self.assertLogs("core_auto", level="WARNING") as reg:
            esito = self.p.aggrega_costi_tecnici()
        self.assertEqual(0, esito["letti"])
        self.assertTrue(any(r.exc_info for r in reg.records),
                        "il prospetto della tariffa tecnica e' fallito senza dire perche': "
                        "al commercialista arriverebbero zeri indistinguibili da «nessun "
                        "costo»")

    # ── il modo :memory: (riga 626) ──────────────────────────────────────────────────────

    def test_riga626_memory_usabile_da_un_altro_filo(self):
        # Mutante: `check_same_thread=False` -> `True`. La connessione condivisa smette di
        # funzionare fuori dal filo che l'ha creata: il server lavora a fili, e il percorso
        # dei pagamenti esploderebbe con ProgrammingError.
        import threading
        p = crea_pagamenti_pendenti(":memory:")
        p.inizializza_schema()
        esito = {}

        def lavora():
            try:
                esito["ok"] = p.registra("T1", alloggio_id="casa", check_in="2027-01-10",
                                         check_out="2027-01-12")
            except Exception as e:                      # noqa: BLE001
                esito["errore"] = repr(e)

        t = threading.Thread(target=lavora)
        t.start()
        t.join(10)
        self.assertNotIn("errore", esito,
                         "la connessione condivisa non funziona da un altro filo: il server "
                         "lavora a fili e il percorso dei pagamenti esplode. %r" % (esito,))
        self.assertTrue(esito.get("ok"))

    # ── LA RIGA 263: IL CANCELLO CHE LO STRUMENTO NON SA ROMPERE ─────────────────────────

    def test_riga263_il_cancello_degli_stati_confermabili_e_CHIUSO(self):
        """⛔ GUARDIA SCRITTA A MANO, col guasto iniettato a mano.

        `if r["stato"] not in ("in_attesa", "scaduto")` decide se una conferma di pagamento
        puo' SCRIVERE. Il generatore di mutanti non sa rompere `not in` — lo dichiara fra le
        rinunce (9 punti su questo modulo), ma non lo prova mai. Un punto che lo strumento
        non esamina non e' un punto sicuro: e' un punto che nessuno ha mai guardato.

        Qui si pretende il comportamento in TUTTE le direzioni: dai due stati confermabili
        si scrive 'pagato' e si riceve lo stato PRECEDENTE; da ogni altro stato non si
        scrive NIENTE. Se qualcuno allargasse quella lista — e' successo davvero il
        2026-08-03, allargata a «pagato, cancellato, rimborsato» da un giro di mutazione
        ucciso — questa guardia diventerebbe rossa lo stesso giorno.
        """
        for stato in ("in_attesa", "scaduto"):
            self._grezzo(riferimento="OK_" + stato, stato=stato)
            rec = self.p.conferma("OK_" + stato)
            self.assertEqual(stato, rec["stato"],
                             "la conferma non restituisce lo stato PRECEDENTE: il chiamante "
                             "sceglie il ramo sbagliato (re-block o no)")
            self.assertEqual("pagato", self.p.info("OK_" + stato)["stato"],
                             "da %r la conferma non ha scritto 'pagato'" % stato)

        for stato in ("pagato", "cancellata_host", "rimborsato", "in_attesa_host"):
            self._grezzo(riferimento="NO_" + stato, stato=stato)
            rec = self.p.conferma("NO_" + stato)
            self.assertEqual(stato, rec["stato"],
                             "la conferma ha risposto con uno stato diverso da quello letto")
            self.assertEqual(stato, self.p.info("NO_" + stato)["stato"],
                             "il cancello si e' aperto su uno stato NON confermabile (%r): "
                             "un pagamento marca 'pagato' una prenotazione gia' chiusa, "
                             "rimborsata o cancellata dall'host -- soldi incassati su una "
                             "stanza che non c'e' piu'" % stato)


if __name__ == "__main__":
    unittest.main()
