"""
Collaudo del FIX single-use del Credito Fondatore/Viaggio (fase167).

BUG PROVATO (2026-07-16): il token `credito_fondatore` era un BEARER riusabile all'infinito
-> lo stesso credito da €50 scontava OGNI prenotazione (erosione sistematica del ricavo).
FIX: registro durevole dei crediti consumati; consumo alla FINALIZZAZIONE della prenotazione,
check al preventivo. Qui si prova: (1) lo store atomico nuovo/stesso/diverso; (2) end-to-end
un credito sconta la 1a prenotazione e NON le successive; (3) un credito mai usato funziona
(niente regressione); (4) fail-open (store rotto -> la prenotazione NON viene bloccata).
"""
import json
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE
from fase167_credito_single_use import crea_registro_crediti_usati

WHSEC = "whsec_cu"


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://checkout.test/" + secrets.token_hex(6),
            "id": "cs_test_" + secrets.token_hex(6)}


class TestRegistroCreditiUsati(unittest.TestCase):
    """Lo store puro: consumo atomico e stati nuovo/stesso/diverso."""
    def test_consuma_atomico(self):
        s = crea_registro_crediti_usati(":memory:")
        s.inizializza_schema()
        self.assertFalse(s.usato("cid1"))
        self.assertEqual(s.consuma("cid1", "REF1"), "nuovo")
        self.assertTrue(s.usato("cid1"))
        # stessa prenotazione -> idempotente (replay del book non allarma)
        self.assertEqual(s.consuma("cid1", "REF1"), "stesso")
        # prenotazione DIVERSA -> riuso rilevato
        self.assertEqual(s.consuma("cid1", "REF2"), "diverso")
        # credito vuoto -> 'nuovo' (niente da tracciare, non blocca nulla)
        self.assertEqual(s.consuma("", "REF3"), "nuovo")
        self.assertFalse(s.usato(""))

    def test_durevole_su_file(self):
        d = tempfile.mkdtemp()
        try:
            s1 = crea_registro_crediti_usati(f"{d}/cu.db")
            s1.inizializza_schema()
            s1.consuma("cidX", "REFX")
            s2 = crea_registro_crediti_usati(f"{d}/cu.db")   # nuovo handle, stesso file
            self.assertTrue(s2.usato("cidX"), "il consumo deve sopravvivere cross-worker")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestContrattoRegistroCrediti(unittest.TestCase):
    """(1) UNITARI — il CONTRATTO dello store, sui confini che i test esistenti non toccano.

    CONTRATTO: un credito, identificato dalla firma del suo token, vale UNA prenotazione
    sola. `consuma(credito_id, riferimento)` risponde 'nuovo' la prima volta, 'stesso' se e'
    un replay della STESSA prenotazione, 'diverso' se qualcuno prova a spenderlo su un'ALTRA.
    Il chiamante (fase83:4862) ONORA lo sconto su 'nuovo' e 'stesso', RIFIUTA su
    'diverso'/errore. Da cui:

      INVARIANTE DEL DENARO: per uno stesso credito, le chiamate ONORATE ('nuovo' o
      'stesso') devono corrispondere a UNA SOLA prenotazione.

    Cosa era scoperto e perche' conta: l'orologio (`ts`, l'unica traccia di QUANDO un credito
    e' stato bruciato) · gli ingressi non-stringa (modo di rompersi n.10, dato assurdo) · il
    RIFERIMENTO VUOTO (fase83:4824 ha il ripiego "") · lo schema mancante, che e' anche
    l'unico modo di far girare il ramo except/ROLLBACK (D19: un ramo difensivo si prova
    adesso, non il giorno del disastro) · la concorrenza sullo store NUDO, perche'
    `test_bombardamento_credito` prova la stessa cosa attraverso TUTTO il server: se cedesse
    qui, quel test direbbe "rotto" senza dire DOVE.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = f"{self.dir}/cu.db"

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _righe(self):
        """L'EFFETTO scritto su disco, non solo l'esito restituito (osservabile forte)."""
        con = sqlite3.connect(self.db)
        try:
            return con.execute(
                "SELECT credito_id, riferimento, ts FROM crediti_usati").fetchall()
        finally:
            con.close()

    def test_ts_registra_QUANDO_il_credito_e_stato_speso(self):
        """`ts` e' l'unica traccia di quando un credito e' stato bruciato: davanti a una
        contestazione e' cio' che si mostra. Nessun test guardava quella colonna, quindi
        scriverci 0 (o togliere l'orologio) sarebbe passato inosservato."""
        s = crea_registro_crediti_usati(self.db, orologio=lambda: 1750000000)
        s.inizializza_schema()
        self.assertEqual(s.consuma("cidT", "REF-T"), "nuovo")
        righe = self._righe()
        self.assertEqual(len(righe), 1, "una sola riga attesa: %r" % (righe,))
        self.assertEqual(righe[0], ("cidT", "REF-T", 1750000000),
                         "credito, prenotazione e ISTANTE devono essere scritti esatti")

    def test_ingressi_assurdi_non_esplodono_e_non_sporcano_il_registro(self):
        """Modo di rompersi n.10 (dato assurdo). Un ingresso non-stringa significa "nessun
        credito da tracciare": `usato` -> False, `consuma` -> 'nuovo', senza sollevare e
        soprattutto SENZA scrivere righe. Una riga spuria qui e' un credito bruciato a un
        ospite che non ne aveva."""
        s = crea_registro_crediti_usati(self.db)
        s.inizializza_schema()
        for brutto in (None, 123, 0, b"cid", {"c": 1}, [], "", "   "):
            self.assertFalse(s.usato(brutto), "usato(%r) deve essere False" % (brutto,))
            self.assertEqual(s.consuma(brutto, "REF-X"), "nuovo",
                             "consuma(%r): niente da tracciare, non deve bloccare" % (brutto,))
        self.assertEqual(self._righe(), [],
                         "nessun ingresso assurdo deve lasciare righe nel registro")

    def test_riferimento_VUOTO_non_puo_onorare_due_prenotazioni(self):
        """IL BUCO DEL DENARO. `fase83:4824` legge `ref = corpo.get("riferimento", "")`: il
        ripiego e' la STRINGA VUOTA. Se due prenotazioni diverse arrivassero entrambe senza
        riferimento, lo store non ha modo di distinguerle: la seconda ottiene 'stesso' (=
        replay innocuo) e il chiamante la CONFERMA con lo sconto applicato. Lo stesso credito
        pagherebbe due soggiorni.

        L'invariante e' indipendente dal rimedio: lo soddisfa sia sollevare (un riferimento
        vuoto non identifica una prenotazione) sia rispondere 'diverso'. Quel che non puo'
        succedere e' che passino tutte e due."""
        s = crea_registro_crediti_usati(self.db)
        s.inizializza_schema()
        esiti = []
        for _ in range(2):
            try:
                esiti.append(s.consuma("cidVuoto", ""))
            except Exception as e:
                esiti.append("rifiutato(%s)" % type(e).__name__)
        onorati = [e for e in esiti if e in ("nuovo", "stesso")]
        self.assertEqual(len(onorati), 1,
                         "un credito si onora UNA volta sola: esiti=%r" % (esiti,))

    def test_schema_mancante_SOLLEVA_invece_di_dire_credito_fresco(self):
        """D19: il ramo difensivo si prova adesso. Se il registro non e' inizializzato,
        `usato` e `consuma` DEVONO sollevare: se rispondessero False/'nuovo' ogni credito
        risulterebbe fresco per sempre = riuso infinito, in silenzio. Il rifiuto del
        chiamante (409 service_unavailable, fase83:4871) dipende esattamente da questa
        eccezione. E' anche l'unico modo di far girare il ramo except/ROLLBACK di
        `consuma`, che nessun test aveva mai eseguito."""
        s = crea_registro_crediti_usati(self.db)          # niente inizializza_schema()
        with self.assertRaises(sqlite3.OperationalError):
            s.usato("cidS")
        with self.assertRaises(sqlite3.OperationalError):
            s.consuma("cidS", "REF-S")

    def test_un_solo_nuovo_anche_con_dieci_prenotazioni_simultanee(self):
        """Il double-spend sullo store NUDO: dieci prenotazioni DIVERSE, stesso credito,
        tutte nello stesso istante. Esattamente UNA deve essere onorata, e nel registro deve
        restare UNA riga."""
        s = crea_registro_crediti_usati(self.db)
        s.inizializza_schema()
        esiti, lucchetto = [], threading.Lock()

        def tenta(n):
            try:
                e = s.consuma("cidRace", "REF-%d" % n)
            except Exception as ex:
                e = "rifiutato(%s)" % type(ex).__name__
            with lucchetto:
                esiti.append(e)

        fili = [threading.Thread(target=tenta, args=(n,)) for n in range(10)]
        for f in fili:
            f.start()
        for f in fili:
            f.join(timeout=30)
        self.assertEqual(len(esiti), 10, "tutti i fili devono aver risposto: %r" % (esiti,))
        onorati = [e for e in esiti if e in ("nuovo", "stesso")]
        self.assertEqual(len(onorati), 1,
                         "UNA sola prenotazione puo' spendere il credito: esiti=%r" % (esiti,))
        self.assertEqual(len(self._righe()), 1, "una sola riga nel registro")

    def test_registro_in_memoria_risponde_anche_da_un_ALTRO_filo(self):
        """TROVATO DAL GIUDICE (mutazione, riga 129 `check_same_thread` False->True:
        SOPRAVVISSUTO). Il registro `:memory:` non e' roba da test: e' il RIPIEGO
        PREDEFINITO della produzione (fase81:97, `db_credito_usati: str = ":memory:"`), e il
        server risponde a piu' ospiti in parallelo, su fili diversi. Se la connessione
        condivisa accettasse solo il filo che l'ha creata, il consumo del credito
        esploderebbe appena due ospiti prenotano insieme -- e nessun test lo guardava,
        perche' tutti quelli sulla concorrenza usano un file su disco.

        Deliberatamente SEQUENZIALE, non in gara: qui si prova UNA cosa sola (si puo' usare
        da un altro filo?), non la contesa. Un test che prova due cose insieme, quando
        diventa rosso, non dice quale delle due si e' rotta."""
        s = crea_registro_crediti_usati(":memory:")
        s.inizializza_schema()
        self.assertEqual(s.consuma("cidMem", "REF-1"), "nuovo")   # filo principale
        esito = {}

        def da_un_altro_filo():
            try:
                esito["r"] = s.consuma("cidMem", "REF-2")
            except Exception as ex:
                esito["r"] = "rifiutato(%s)" % type(ex).__name__

        t = threading.Thread(target=da_un_altro_filo)
        t.start()
        t.join(timeout=30)
        self.assertEqual(esito.get("r"), "diverso",
                         "il registro in memoria deve rispondere anche da un altro filo, e "
                         "riconoscere il riuso: ottenuto %r" % (esito.get("r"),))


class TestSingleUseE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db", db_credito_usati=f"{d}/cu.db",
            commissione_bps=1000, psp_bps=0,
            stripe_secret_key="sk_test_cu", stripe_webhook_secret=WHSEC,
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@cu.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "Casa", "citta": "Roma",
                "prezzo_notte_cents": 50000, "capacita": 4,
                "politica_cancellazione": "flessibile"}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": "2026-09-01", "a": "2026-12-31",
                "unita_totali": 3, "prezzo_netto_cents": 50000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, metodo, path, body=None, headers=None):
        return self.r.gestisci(metodo, path, {},
                               json.dumps(body) if body is not None else None, headers or {})

    def _credito(self, cents=5000, nonce="n1"):
        return self.sys.firma.codifica({"tipo": "credito_fondatore", "email": "x@x.it",
                                        "citta": "roma", "credito_cents": cents,
                                        "exp": int(time.time()) + 30 * 86400, "nonce": nonce})

    def _quote(self, ci, co, credito=None):
        body = {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2}
        if credito:
            body["credito_token"] = credito
        s, q = self.g("POST", "/api/concierge/quote", body)
        self.assertEqual(s, 200, q)
        return q

    def _book(self, q):
        return self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@x.it"})

    def test_credito_si_spende_una_volta_sola(self):
        cr = self._credito()
        q1 = self._quote("2026-09-05", "2026-09-08", cr)
        self.assertGreater(q1["sconto_credito_cents"], 0, "il credito deve scontare la 1a")
        s1, _ = self._book(q1)
        self.assertEqual(s1, 201)                       # finalizzata -> credito consumato
        # STESSO credito su prenotazioni successive -> NIENTE sconto
        q2 = self._quote("2026-10-05", "2026-10-08", cr)
        self.assertEqual(q2["sconto_credito_cents"], 0, "REGRESSIONE: credito riusabile")
        q3 = self._quote("2026-11-05", "2026-11-08", cr)
        self.assertEqual(q3["sconto_credito_cents"], 0, "REGRESSIONE: credito riusabile")

    def test_book_idempotente_non_rompe(self):
        cr = self._credito(nonce="n2")
        q = self._quote("2026-09-15", "2026-09-18", cr)
        s1, _ = self._book(q)
        s2, _ = self._book(q)                            # replay dello stesso book
        self.assertEqual((s1, s2), (201, 201), "il replay idempotente non deve fallire")

    def test_credito_mai_usato_funziona(self):
        # niente regressione: un credito fresco applica lo sconto normalmente
        q = self._quote("2026-09-25", "2026-09-28", self._credito(nonce="n3"))
        self.assertGreater(q["sconto_credito_cents"], 0)

    def test_race_n_preventivi_secondo_book_rifiutato(self):
        """RESIDUO CHIUSO: due preventivi con lo STESSO credito generati PRIMA di prenotare
        (entrambi scontati) -> il 1o book applica lo sconto e consuma; il 2o book viene RIFIUTATO
        (409, pre-pagamento) e la stanza LIBERATA (ri-prenotabile). Cosi' un credito vale UNA
        prenotazione anche sotto race, senza mai toccare una prenotazione legittima."""
        cr = self._credito(nonce="race")
        qa = self._quote("2026-09-05", "2026-09-08", cr)
        qb = self._quote("2026-09-15", "2026-09-18", cr)   # generato PRIMA di prenotare qa
        self.assertGreater(qa["sconto_credito_cents"], 0)
        self.assertGreater(qb["sconto_credito_cents"], 0)   # ancora scontato (credito non consumato)
        sa, _ = self._book(qa)
        self.assertEqual(sa, 201)                            # 1o book: ok, consuma il credito
        sb, bb = self._book(qb)
        self.assertEqual(sb, 409, "il 2o book con credito gia' speso deve essere RIFIUTATO")
        self.assertEqual(bb.get("errore"), "credito_gia_usato")
        # la stanza di qb e' stata LIBERATA -> prenotabile di nuovo (senza credito)
        s2, q2 = self.g("POST", "/api/concierge/quote",
                        {"alloggio_id": "casa", "check_in": "2026-09-15",
                         "check_out": "2026-09-18", "party": 2})
        s3, _ = self.g("POST", "/api/concierge/book",
                       {"quote_token": q2["quote_token"], "email": "cli2@x.it"})
        self.assertEqual(s3, 201, "la stanza del book rifiutato deve restare prenotabile")

    def test_store_rotto_RIFIUTA_la_prenotazione_invece_di_regalare_il_credito(self):
        """CONTRATTO CORRETTO (2026-07-30). Questo test prima si chiamava
        `test_fail_open_store_rotto_non_blocca_prenotazione` e pretendeva `201`: cioe'
        IMPONEVA il difetto invece di sorvegliarlo.

        Il difetto: se l'archivio dei crediti e' guasto, `consuma()` solleva; il fail-open
        confermava la prenotazione con lo SCONTO GIA' APPLICATO mentre il credito restava
        NON marcato come speso -> lo stesso credito tornava spendibile, all'infinito. Il
        guasto non e' teorico: "database is locked" sotto concorrenza e' gia' successo qui.

        Perche' il contratto giusto e' RIFIUTARE: due righe piu' sotto il codice ragiona
        gia' cosi' per il caso gemello ('diverso') -- siamo PRE-PAGAMENTO, nessun soldo
        mosso, quindi si rifiuta e si libera la stanza. Rifiutare e' recuperabile (l'ospite
        rifa' il preventivo); regalare un credito riusabile no.

        All'ospite si dice la VERITA': `service_unavailable` (problema momentaneo), non
        `credito_gia_usato` che sarebbe falso -- lui non ha usato niente.

        VISTO ROSSO sul codice vecchio: rispondeva 201.
        """
        class _Rotto:
            def usato(self, cid):
                raise RuntimeError("store giu'")

            def consuma(self, cid, rif):
                raise RuntimeError("store giu'")
        self.sys.credito_usati = _Rotto()
        # ricablo il concierge allo store rotto (il router usa self.sys.credito_usati al book)
        self.sys.concierge._credito_store = _Rotto()
        q = self._quote("2026-10-15", "2026-10-18", self._credito(nonce="n4"))
        self.assertGreater(q["sconto_credito_cents"], 0,
                           "il preventivo deve avere lo sconto: e' quello che rende grave "
                           "confermare senza bruciare il credito")
        s, b = self._book(q)
        self.assertEqual(s, 409, "archivio crediti guasto -> prenotazione RIFIUTATA: %r" % (b,))
        self.assertEqual(b.get("errore"), "service_unavailable",
                         "il motivo detto all'ospite dev'essere vero: %r" % (b,))
        self.assertNotIn("voucher_token", b, "nessuna prenotazione confermata: %r" % (b,))


class TestIntegrazioneConsumoLatoServer(unittest.TestCase):
    """(2) INTEGRAZIONE — `RouterHTTP._consuma_credito` (fase83:6343) sopra il registro VERO.

    Perche' serve un livello in mezzo. Il (1) prova il registro da solo; il (3) prova tutto
    il sito. In mezzo c'e' il pezzo che TRADUCE la risposta del registro in "confermo" o
    "rifiuto": fase83:4862 onora lo sconto su 'nuovo' e 'stesso', RIFIUTA su
    'diverso'/'errore'. Il ripiego che rende ambiguo il riferimento sta li' accanto
    (fase83:4824, `corpo.get("riferimento", "")`), quindi e' li' che va provato — non nel
    registro, che non sa chi lo chiama, e non nel sito, dove si perde fra mille altre cose.

    D19 punto 3: lo stato "impossibile" si costruisce a mano ADESSO, quando costa tre righe,
    non il giorno in cui capita davvero.
    """
    ONORATI = ("nuovo", "stesso")      # esattamente cio' su cui fase83:4862 NON rifiuta

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db",
            db_credito_usati=f"{d}/cu.db"))
        self.r = crea_router(self.sys, host_key="hk")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _consuma(self, riferimento, credito="cidINT", sconto=5000):
        """Chiama il VERO pezzo del server, col VERO registro sotto."""
        return self.r._consuma_credito(
            {"credito_id": credito, "sconto_credito_cents": sconto}, riferimento)

    def test_due_prenotazioni_senza_riferimento_non_sono_entrambe_onorate(self):
        """Il caso del ripiego vuoto, visto da chi decide. Due finalizzazioni DIVERSE che
        arrivano entrambe senza riferimento: il server non deve onorarle tutte e due, o lo
        stesso credito paga due soggiorni."""
        esiti = [self._consuma(""), self._consuma("")]
        onorati = [e for e in esiti if e in self.ONORATI]
        self.assertEqual(len(onorati), 1,
                         "un credito si onora UNA volta sola: esiti=%r" % (esiti,))

    def test_replay_della_stessa_prenotazione_resta_onorato(self):
        """L'ALTRA direzione, obbligatoria (regola ferrea 10: un falso allarme e' un difetto
        quanto un allarme mancato). Se l'ospite ricarica la pagina, il SUO book deve
        continuare a passare: 'stesso' e' un replay legittimo, non un riuso."""
        self.assertEqual(self._consuma("BVIP-1"), "nuovo")
        self.assertEqual(self._consuma("BVIP-1"), "stesso",
                         "il replay della STESSA prenotazione non va mai rifiutato")

    def test_un_altro_book_con_lo_stesso_credito_viene_rifiutato(self):
        """Il caso normale del riuso: prenotazioni diverse, credito gia' speso -> 'diverso',
        che fase83:4871 traduce in 409 credito_gia_usato + stanza liberata."""
        self.assertEqual(self._consuma("BVIP-1"), "nuovo")
        self.assertEqual(self._consuma("BVIP-2"), "diverso")

    def test_un_preventivo_senza_sconto_non_brucia_il_credito(self):
        """Se lo sconto non e' stato applicato non c'e' niente da consumare: bruciarlo
        comunque significherebbe togliere il credito a un ospite che non l'ha ancora usato.
        Dopo il giro a vuoto il credito deve risultare ANCORA spendibile."""
        self.assertIsNone(self._consuma("BVIP-9", sconto=0))
        self.assertEqual(self._consuma("BVIP-9", sconto=5000), "nuovo",
                         "il credito doveva restare spendibile")


if __name__ == "__main__":
    unittest.main(verbosity=2)
