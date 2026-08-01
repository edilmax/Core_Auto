"""Test 'tasto cancella tutto + verifica ovunque' (fase156): registra host -> pubblica ->
disponibilita -> prenota -> messaggio, poi cancella_attivita_host -> tutto rimosso da OGNI
archivio + verifica residui 0. Endpoint admin + idempotenza."""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase156_erasure import cancella_attivita_host

SEG = b"e" * 32
HK = {"X-Host-Key": "hk"}
AK = {"X-Admin-Key": "ak"}


class TestErasure(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db",
            db_messaggi=f"{d}/m.db", file_referral=f"{d}/ref.json", commissione_bps=1500))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@x.it", "password": "passw0rd!", "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True})
        self.hid = c["host_id"]
        self.g("POST", "/api/host/pubblica", {
            "host_id": self.hid, "slug": "casa", "titolo": "Casa", "citta": "Roma",
            "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
            "servizi": [], "immagini": ["https://x/y.jpg"]}, HK)
        self.g("POST", "/api/host/disponibilita_range", {
            "alloggio_id": "casa", "da": "2026-08-01", "a": "2026-08-31",
            "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)
        _, q = self.g("POST", "/api/concierge/quote", {
            "alloggio_id": "casa", "check_in": "2026-08-10", "check_out": "2026-08-12",
            "party": 1})
        self.g("POST", "/api/concierge/book",
                {"quote_token": q["quote_token"], "email": "o@x.it"})
        self.sis.messaggistica.invia("P1", self.hid, "o@x.it", self.hid, "ciao")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, body=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {},
                               json.dumps(body) if body is not None else None, h or {})

    def test_dati_presenti_prima(self):
        self.assertEqual(self.sis.catalogo.conta_alloggi_host(self.hid), 1)
        self.assertTrue(self.sis.registro_host.esiste_host(self.hid))
        self.assertGreaterEqual(self.sis.inventario.conta_alloggio("casa"), 1)
        self.assertEqual(self.sis.messaggistica.conta_messaggi_host(self.hid), 1)

    def test_host_con_prenotazione_e_RIFIUTATO_senza_forza(self):
        """Dal 2026-07-22: questo host ha una prenotazione FUTURA (un ospite che ha
        pagato). Cancellarlo lo lascerebbe senza stanza -> la cancellazione DEVE
        rifiutare, a meno di forzarla. E' la riparazione (a) dell'audit integrita'."""
        rep = cancella_attivita_host(self.sis, self.hid)
        self.assertFalse(rep.get("ok"))
        self.assertEqual(rep.get("errore"), "obblighi_pendenti")
        self.assertIn("prenotazioni_attive", rep.get("obblighi", {}))
        # e NON ha cancellato nulla: l'host e i dati ci sono ancora
        self.assertTrue(self.sis.registro_host.esiste_host(self.hid))

    def test_cancella_ovunque_e_verifica(self):
        # il meccanismo di WIPE: con forza=True (obbligo legale inderogabile) deve
        # comunque togliere tutto da ogni archivio e verificare 0 residui.
        rep = cancella_attivita_host(self.sis, self.hid, forza=True)
        self.assertTrue(rep["ok"])                         # 0 residui ovunque
        self.assertIn("forzato_nonostante", rep)           # tracciato cosa c'era
        self.assertGreaterEqual(rep["cancellati"]["alloggi"], 1)
        self.assertEqual(rep["cancellati"]["host"], 1)
        self.assertTrue(all(v == 0 for v in rep["residui"].values()))
        # davvero sparito da ogni archivio:
        self.assertIsNone(self.sis.catalogo.dettaglio("casa"))
        self.assertFalse(self.sis.registro_host.esiste_host(self.hid))
        self.assertEqual(self.sis.inventario.conta_alloggio("casa"), 0)
        self.assertEqual(self.sis.messaggistica.conta_messaggi_host(self.hid), 0)

    def test_endpoint_admin(self):
        # senza forza: rifiutato (obblighi) -> 409
        s, c = self.g("POST", "/api/admin/cancella_attivita", {"host_id": self.hid}, AK)
        self.assertEqual(s, 409)
        self.assertEqual(c.get("errore"), "obblighi_pendenti")
        # con forza: eseguito -> 200
        s, c = self.g("POST", "/api/admin/cancella_attivita",
                      {"host_id": self.hid, "forza": True}, AK)
        self.assertEqual(s, 200)
        self.assertTrue(c["ok"])
        # senza chiave admin -> 401
        self.assertEqual(self.g("POST", "/api/admin/cancella_attivita",
                                {"host_id": self.hid}, {})[0], 401)

    def test_idempotente(self):
        # il WIPE e' idempotente: eseguito due volte (forzato, perche' restano obblighi
        # finanziari che di proposito NON si cancellano) lascia 0 residui negli archivi
        # che gestisce. NB: il payout/escrow di una prenotazione forzata resta — va
        # saldato a mano, ed e' giusto che `obblighi_pendenti` continui a segnalarlo.
        cancella_attivita_host(self.sis, self.hid, forza=True)
        rep2 = cancella_attivita_host(self.sis, self.hid, forza=True)
        self.assertTrue(rep2["ok"])
        self.assertTrue(all(v == 0 for v in rep2["residui"].values()))


class _Archivio:
    """Un archivio finto che espone SOLO i metodi che gli si danno.

    Serve a costruire un sistema PARZIALE: e' l'unico modo di provare la resilienza che
    `fase156` dichiara di avere («opera solo sugli store presenti che espongono i metodi»),
    perche' col sistema vero sono sempre tutti presenti.
    """

    def __init__(self, **metodi):
        for nome, f in metodi.items():
            setattr(self, nome, f)


class _Sistema:
    """Un sistema con SOLO gli archivi che gli si passano: gli altri non esistono proprio."""

    def __init__(self, **archivi):
        for nome, a in archivi.items():
            setattr(self, nome, a)


class TestErasureConArchiviMANCANTI(unittest.TestCase):
    """⛔ LO SCENARIO CHE NON ERA MAI STATO PROVATO — e valeva 33 mutanti su 42.

    La mutazione (2026-08-01, tutti e 42 i punti del modulo) ha ucciso **9** guasti su 42:
    il 79% del modulo del **diritto all'oblio** non era protetto. Ma non erano 33 difetti
    diversi: era **UNO scenario mancante**.

    Tutto `fase156` e' costruito su `if archivio is not None **and** hasattr(archivio, "m")`.
    Le prove esistenti usano solo il sistema VERO, dove entrambe le condizioni sono sempre
    vere: cambiare quell'`and` in `or` non si vede da nessuna parte. La resilienza agli
    archivi mancanti -- la proprieta' scritta nel commento in cima al file -- non era mai
    stata messa alla prova.

    Non e' un'ipotesi di laboratorio: gli archivi mancano davvero quando un modulo nuovo non
    e' ancora cablato, quando un archivio non si apre, o su un'istanza ridotta (i motori
    verticali). E il modulo esiste proprio per NON dichiarare un successo che non c'e'
    stato: se sbaglia, una persona crede di essere sparita e noi teniamo i suoi dati.
    """

    def test_se_NESSUN_archivio_si_puo_verificare_la_cancellazione_NON_e_riuscita(self):
        """⛔ LA PROMESSA CENTRALE DEL MODULO, ROVESCIABILE CON UNA PAROLA.

            rep["ok"] = all(v == 0 for v in residui.values()) if residui else False

        Con `False` -> `True`, un sistema in cui **non si e' potuto controllare niente**
        dichiara la cancellazione **riuscita**. E' esattamente il «falso cancellato» che il
        modulo e' stato scritto per impedire: nessun archivio interrogato, zero prove, e
        una persona convinta di essere stata dimenticata mentre i suoi dati sono ancora li'.
        Con `forza=True` perche' senza archivi gli obblighi sono tutti incerti (giustamente)
        e la cancellazione verrebbe rifiutata prima di arrivare alla verifica.
        """
        from fase156_erasure import cancella_attivita_host
        rep = cancella_attivita_host(_Sistema(), "h1", forza=True)
        self.assertEqual({}, rep["residui"], "senza archivi non si verifica nulla")
        self.assertEqual([], rep["verificato_archivi"])
        self.assertFalse(rep["ok"],
                         "ha dichiarato RIUSCITA una cancellazione in cui non ha verificato "
                         "un solo archivio: e' il falso 'cancellato' che questo modulo esiste "
                         "per impedire. rep=%r" % (rep,))

    def test_un_controllo_IMPOSSIBILE_diventa_dubbio_e_BLOCCA_la_cancellazione(self):
        """Un archivio che non c'e' non e' «tutto pulito»: e' «non lo so». Il modulo lo
        scrive in `_incerti`, e la presenza di dubbi basta a RIFIUTARE la cancellazione --
        altrimenti si cancellerebbe sopra dei soldi solo perche' l'archivio che li custodisce
        non rispondeva.

        Si pretende l'elenco ESATTO dei dubbi: con `or` al posto di `and` alcuni rami entrano
        lo stesso e il dubbio **non viene registrato**, cioe' sparisce senza che nessuno lo
        veda. E si pretende **nessun allarme nel registro**: un archivio assente e' una
        condizione nota, non un guasto; segnalarlo come errore riempirebbe i log di falsi
        allarmi, che e' il modo migliore per farli ignorare.
        """
        import logging
        from fase156_erasure import cancella_attivita_host, obblighi_pendenti
        with self.assertRaises(AssertionError):        # nessun allarme a sistema vuoto
            with self.assertLogs("fase156_erasure", level="WARNING"):
                motivi = obblighi_pendenti(_Sistema(), "h1")
        self.assertEqual(["escrow", "in_sospeso", "payout", "prenotazioni"],
                         motivi.get("_incerti"),
                         "l'elenco dei controlli NON eseguiti e' incompleto: un dubbio "
                         "sparito e' un rischio che nessuno vedra' piu'. motivi=%r" % (motivi,))
        rep = cancella_attivita_host(_Sistema(), "h1")
        self.assertEqual("obblighi_pendenti", rep.get("errore"),
                         "ha cancellato pur non avendo potuto controllare NIENTE: rep=%r"
                         % (rep,))
        self.assertFalse(rep["ok"])

    def test_ogni_obbligo_VERO_viene_visto_uno_per_uno(self):
        """I quattro pericoli, ognuno acceso da solo: se anche uno solo smettesse di essere
        visto, si cancellerebbe un host con dei soldi o una persona in ballo. Provati uno
        alla volta, cosi' un rosso dice QUALE si e' rotto (un test che li accende tutti
        insieme direbbe solo «qualcosa non va»)."""
        from fase156_erasure import obblighi_pendenti
        cat = _Archivio(alloggi_host=lambda h, limit=None: [{"slug": "casa"}])
        casi = (
            ("prenotazioni_attive", dict(inventario=_Archivio(
                elenco_prenotazioni=lambda alloggio_id=None, limit=None: [
                    {"rimborsato": False, "check_out": "2099-01-01"}]))),
            ("payout_dovuto", dict(payout=_Archivio(
                riepilogo=lambda h: {"EUR": {"maturato": 5000}}))),
            ("escrow_aperto", dict(garanzia=_Archivio(aperte_per_alloggio=lambda s: 2))),
            ("in_sospeso", dict(pagamenti_pendenti=_Archivio(
                da_approvare=lambda h, limit=None: [{"x": 1}, {"y": 2}]))),
        )
        for atteso, archivi in casi:
            motivi = obblighi_pendenti(_Sistema(catalogo=cat, **archivi), "h1")
            self.assertIn(atteso, motivi,
                          "obbligo non visto: %s (motivi=%r). Un host con questo in ballo "
                          "verrebbe cancellato." % (atteso, motivi))

    def test_su_un_sistema_PARZIALE_non_esplode_e_dichiara_SOLO_cio_che_ha_verificato(self):
        """Regola 15 della ricerca: *ogni controllo dichiari quanti posti ispeziona*. Qui il
        rapporto deve elencare **solo** gli archivi davvero interrogati -- ne' meno (si
        perderebbe la traccia di cosa e' stato pulito) ne' di piu' (dichiarerebbe verifiche
        mai fatte). E con un archivio che ha ancora dati, `ok` deve essere **falso**.
        """
        from fase156_erasure import cancella_attivita_host
        rimasti = {"n": 3}
        cat = _Archivio(alloggi_host=lambda h, limit=None: [],
                        cancella_alloggi_host=lambda h: 0,
                        conta_alloggi_host=lambda h: 0)
        msg = _Archivio(cancella_messaggi_host=lambda h: 1,
                        conta_messaggi_host=lambda h: rimasti["n"])
        sis = _Sistema(catalogo=cat, messaggistica=msg)     # inventario/registro/viral ASSENTI
        rep = cancella_attivita_host(sis, "h1", forza=True)
        self.assertEqual(["alloggi", "messaggi"], sorted(rep["verificato_archivi"]),
                         "il rapporto dichiara archivi diversi da quelli davvero "
                         "interrogati: %r" % (rep,))
        self.assertEqual(3, rep["residui"]["messaggi"])
        self.assertFalse(rep["ok"],
                         "sono rimasti 3 messaggi e la cancellazione si dichiara riuscita: "
                         "%r" % (rep,))
        # ...e il verso opposto: quando i residui sono davvero zero, `ok` deve essere vero.
        # Senza questa meta', un `ok` sempre falso passerebbe per prudente.
        rimasti["n"] = 0
        self.assertTrue(cancella_attivita_host(sis, "h1", forza=True)["ok"])


class TestErasureConArchiviINCOMPLETI(unittest.TestCase):
    """⛔ L'ARCHIVIO C'E' MA NON SA FARE QUELLA COSA — lo scenario che mancava davvero.

    Prima diagnosi mia, SBAGLIATA e corretta qui: pensavo bastasse un sistema con archivi
    ASSENTI. Non basta, e la mutazione lo ha dimostrato: su `X is not None and hasattr(X, "m")`
    le due versioni (`and` / `or`) danno lo stesso risultato quando X manca del tutto, perche'
    `hasattr(None, "m")` e' comunque falso. Differiscono in UN caso solo: **l'archivio esiste
    ma non espone quel metodo**.

    Ed e' proprio la situazione che il modulo dichiara di reggere: *«opera solo sugli store
    presenti che espongono i metodi -> aggiungere un nuovo store in futuro non richiede
    toccare questo file»*. Succede davvero quando un archivio e' di una versione precedente,
    o quando un modulo nuovo e' cablato a meta'.
    """

    def _vuoti(self, *nomi):
        return _Sistema(**{n: _Archivio() for n in nomi})

    def test_archivi_SENZA_METODI_non_fanno_esplodere_e_restano_DICHIARATI_come_dubbi(self):
        """Con `or` al posto di `and`, il codice chiama un metodo che non c'e': o esplode e
        porta giu' la cancellazione, o -- peggio -- l'errore viene ingoiato e il controllo
        risulta **fatto** senza essere avvenuto. Qui si pretende la terza via, quella scritta
        nel modulo: saltarlo e **segnarlo come dubbio**."""
        from fase156_erasure import cancella_attivita_host, obblighi_pendenti
        sis = self._vuoti("inventario", "payout", "pagamenti_pendenti",
                          "garanzia", "registro_host", "messaggistica", "viral")
        # il catalogo risponde (elenco vuoto): serve a isolare la proprieta' qui sotto.
        # NB misurato: `_slug_host` NON controlla `hasattr` come fanno tutti gli altri punti,
        # quindi un catalogo privo di `alloggi_host` finisce fra i GUASTI invece che fra gli
        # ASSENTI, e grida. E' un'incoerenza del modulo, segnalata al fondatore: si ripara in
        # produzione (una riga), non piegando la prova.
        sis.catalogo = _Archivio(alloggi_host=lambda h, limit=None: [])
        # ⛔ E NEMMENO UN ALLARME: un archivio che non espone quel metodo e' una condizione
        # NOTA (il modulo e' scritto apposta per reggerla), non un guasto. Segnalarla come
        # errore riempirebbe il registro di falsi allarmi -- e un registro che grida sempre
        # e' un registro che nessuno legge. Senza questa meta', il codice puo' arrivare allo
        # stesso elenco di dubbi passando per un'eccezione ingoiata, e non si vedrebbe.
        with self.assertRaises(AssertionError):
            with self.assertLogs("fase156_erasure", level="WARNING"):
                obblighi_pendenti(sis, "h1")
        motivi = obblighi_pendenti(sis, "h1")
        self.assertEqual(["escrow", "in_sospeso", "payout", "prenotazioni"],
                         motivi.get("_incerti"),
                         "un archivio che non sa rispondere e' sparito dall'elenco dei "
                         "dubbi: motivi=%r" % (motivi,))
        rep = cancella_attivita_host(sis, "h1", forza=True)
        self.assertEqual({}, rep["cancellati"],
                         "ha dichiarato cancellazioni su archivi che non sanno cancellare: "
                         "%r" % (rep["cancellati"],))
        self.assertEqual({}, rep["residui"], "residui inventati: %r" % (rep["residui"],))
        self.assertEqual([], rep["verificato_archivi"],
                         "ha dichiarato verifiche mai avvenute: %r" % (rep,))
        self.assertNotIn("impronte_depositate", rep,
                         "ha dichiarato di aver depositato le impronte anti-riciclo su un "
                         "archivio che non sa farlo: %r" % (rep,))
        self.assertFalse(rep["ok"])

    def test_un_ospite_che_parte_OGGI_e_ancora_dentro_casa(self):
        """`check_out >= oggi` diventa `> oggi`: un ospite che lascia la casa **oggi** smette
        di contare come prenotazione attiva, e l'host puo' essere cancellato mentre quella
        persona e' ancora dentro, con la prenotazione che sparisce da sotto. Un giorno di
        differenza, una persona in mezzo a una strada."""
        import datetime
        from fase156_erasure import obblighi_pendenti
        oggi = datetime.date.today().isoformat()
        sis = _Sistema(
            catalogo=_Archivio(alloggi_host=lambda h, limit=None: [{"slug": "casa"}]),
            inventario=_Archivio(elenco_prenotazioni=lambda alloggio_id=None, limit=None: [
                {"rimborsato": False, "check_out": oggi}]))
        self.assertEqual(1, obblighi_pendenti(sis, "h1").get("prenotazioni_attive"),
                         "chi parte OGGI non e' stato contato fra le prenotazioni attive")

    def test_una_prenotazione_RIMBORSATA_e_VECCHIA_non_blocca_per_sempre(self):
        """Il verso opposto: `not rimborsato and check_out >= oggi` con un `or` conta come
        attiva anche una prenotazione **rimborsata** o **finita da un pezzo**. L'host non
        riuscirebbe MAI a farsi cancellare -- un diritto GDPR negato da un errore di logica,
        senza che nessuno capisca perche'."""
        from fase156_erasure import obblighi_pendenti
        sis = _Sistema(
            catalogo=_Archivio(alloggi_host=lambda h, limit=None: [{"slug": "casa"}]),
            inventario=_Archivio(elenco_prenotazioni=lambda alloggio_id=None, limit=None: [
                {"rimborsato": True, "check_out": "2099-01-01"},      # rimborsata (futura)
                {"rimborsato": False, "check_out": "2000-01-01"}]))   # finita nel 2000
        motivi = obblighi_pendenti(sis, "h1")
        self.assertNotIn("prenotazioni_attive", motivi,
                         "una prenotazione rimborsata o vecchia blocca la cancellazione per "
                         "sempre: %r" % (motivi,))

    def test_un_payout_a_ZERO_non_e_un_payout_dovuto(self):
        """`if tot > 0` diventa `>= 0`: una valuta con **zero** da bonificare finisce fra i
        motivi, e l'host resta bloccato per un debito che non esiste."""
        from fase156_erasure import obblighi_pendenti
        sis = _Sistema(payout=_Archivio(
            riepilogo=lambda h: {"EUR": {"maturato": 0, "in_transito": 0}}))
        motivi = obblighi_pendenti(sis, "h1")
        self.assertNotIn("payout_dovuto", motivi,
                         "zero euro da bonificare vengono contati come debito: %r" % (motivi,))
        # e il verso opposto, senno' basterebbe non guardare mai
        sis2 = _Sistema(payout=_Archivio(riepilogo=lambda h: {"EUR": {"maturato": 1}}))
        self.assertEqual({"EUR": 1}, obblighi_pendenti(sis2, "h1").get("payout_dovuto"))

    def test_un_host_id_VUOTO_viene_rifiutato_prima_di_toccare_qualunque_cosa(self):
        """`not (isinstance(host_id, str) and host_id)` con un `or`: la stringa vuota passa
        il controllo (e' pur sempre una stringa) e la cancellazione **parte** con un
        identificativo vuoto -- cioe' va a colpire chissa' cosa, in ogni archivio."""
        from fase156_erasure import cancella_attivita_host
        toccato = {"n": 0}

        def _conta(*a, **k):
            toccato["n"] += 1
            return 0

        sis = _Sistema(catalogo=_Archivio(alloggi_host=_conta, cancella_alloggi_host=_conta,
                                          conta_alloggi_host=_conta))
        for storto in ("", None, 0, [], {}):
            rep = cancella_attivita_host(sis, storto, forza=True)
            self.assertEqual("host_id_non_valido", rep.get("errore"),
                             "identificativo storto accettato: %r -> %r" % (storto, rep))
        self.assertEqual(0, toccato["n"],
                         "con un identificativo storto ha comunque toccato gli archivi "
                         "%d volte" % toccato["n"])

    def test_un_archivio_che_risponde_VERO_invece_di_un_numero_vale_ZERO(self):
        """`_safe` deve accettare solo interi veri: `isinstance(n, int) and not isinstance(n,
        bool)`. Con un `or`, un archivio che risponde `True` -- e in Python `True` e' 1 --
        farebbe scrivere nel rapporto «1 elemento cancellato» dal nulla. Il rapporto della
        cancellazione e' una prova legale: non puo' contare cose che non esistono."""
        from fase156_erasure import cancella_attivita_host
        sis = _Sistema(
            catalogo=_Archivio(alloggi_host=lambda h, limit=None: [],
                               cancella_alloggi_host=lambda h: True,   # non e' un numero
                               conta_alloggi_host=lambda h: 0))
        rep = cancella_attivita_host(sis, "h1", forza=True)
        self.assertEqual(0, rep["cancellati"]["alloggi"],
                         "un 'True' e' stato contato come un elemento cancellato: %r"
                         % (rep["cancellati"],))

    def test_gli_slug_si_leggono_solo_da_voci_VERE(self):
        """`isinstance(a, dict) and a.get("slug")` con un `or`: una voce che non e' un
        dizionario fa esplodere la lettura, e l'eccezione viene ingoiata dal `try` esterno ->
        **l'elenco degli alloggi torna vuoto**. Da li' in poi la cancellazione crede che
        l'host non abbia case: inventario, escrow e prenotazioni non vengono nemmeno
        guardati. Un dato sporco in un archivio spegne mezza cancellazione, in silenzio."""
        from fase156_erasure import obblighi_pendenti
        sis = _Sistema(
            catalogo=_Archivio(alloggi_host=lambda h, limit=None: [
                "non-un-dizionario", {"slug": "casa"}, {"altro": 1}, None]),
            garanzia=_Archivio(aperte_per_alloggio=lambda s: 1 if s == "casa" else 0))
        self.assertEqual(1, obblighi_pendenti(sis, "h1").get("escrow_aperto"),
                         "una voce sporca nel catalogo ha fatto perdere gli alloggi dell'host, "
                         "e con essi l'escrow ancora aperto")

    def test_una_forzatura_su_host_PULITO_non_grida_al_lupo(self):
        """`if obblighi and forza:` con un `or`: basta `forza=True` perche' il modulo scriva
        un **CRITICAL** «ERASURE FORZATA su host con obblighi» anche quando di obblighi non
        ce n'e' nessuno, e infili nel rapporto un `forzato_nonostante` vuoto.

        Il livello CRITICAL e' quello che sveglia la gente di notte e finisce nelle email del
        guardiano: se grida a vuoto, si smette di guardarlo -- e il giorno che grida per una
        forzatura VERA (un host con soldi in ballo cancellato per obbligo legale) nessuno
        alzera' la testa. Un falso allarme e' un difetto, non un fastidio.
        """
        import logging
        from fase156_erasure import cancella_attivita_host
        sis = _Sistema(
            catalogo=_Archivio(alloggi_host=lambda h, limit=None: [],
                               cancella_alloggi_host=lambda h: 0,
                               conta_alloggi_host=lambda h: 0),
            inventario=_Archivio(elenco_prenotazioni=lambda alloggio_id=None, limit=None: []),
            payout=_Archivio(riepilogo=lambda h: {}),
            garanzia=_Archivio(aperte_per_alloggio=lambda s: 0),
            pagamenti_pendenti=_Archivio(da_approvare=lambda h, limit=None: []))
        with self.assertRaises(AssertionError):        # nessun CRITICAL su un host pulito
            with self.assertLogs("fase156_erasure", level="CRITICAL"):
                rep = cancella_attivita_host(sis, "h1", forza=True)
        rep = cancella_attivita_host(sis, "h1", forza=True)
        self.assertNotIn("forzato_nonostante", rep,
                         "ha registrato una forzatura «nonostante gli obblighi» su un host "
                         "che non ne aveva: %r" % (rep,))
        self.assertTrue(rep["ok"])

    def test_un_CIN_vuoto_non_finisce_fra_le_impronte(self):
        """`if isinstance(d, dict) and d.get("cin")` con un `or`: un annuncio con il CIN
        **vuoto** («e' pur sempre un dizionario») passa il controllo e deposita una impronta
        di stringa vuota.

        Le impronte anti-riciclo servono a impedire che un host si cancelli e si ri-registri
        per riprendersi i 90 giorni a commissione zero. Un'impronta vuota e' **la stessa per
        tutti**: da quel momento chiunque risulterebbe «gia' visto», e a host onesti verrebbe
        negata la promozione che gli spetta. E' il difetto gemello di quello trovato il
        2026-07-31 sull'anti-riciclo, dalla parte opposta.
        """
        from fase156_erasure import cancella_attivita_host
        visto = {}
        sis = _Sistema(
            catalogo=_Archivio(alloggi_host=lambda h, limit=None: [{"slug": "casa"}],
                               dettaglio=lambda s: {"cin": ""},      # CIN vuoto
                               cancella_alloggi_host=lambda h: 1,
                               conta_alloggi_host=lambda h: 0),
            registro_host=_Archivio(
                deposita_impronte=lambda h, extra=None: visto.setdefault("extra", extra) and 1,
                cancella_host=lambda h: 1, esiste_host=lambda h: False))
        cancella_attivita_host(sis, "h1", forza=True)
        self.assertEqual([], visto.get("extra"),
                         "un CIN vuoto e' stato depositato come impronta: %r -- da quel "
                         "momento vale per chiunque" % (visto.get("extra"),))

    def test_un_CIN_NON_LETTO_viene_DETTO_invece_di_sparire(self):
        """⛔ CORREZIONE DI PRODUZIONE (2026-08-01, autorizzata dal fondatore).

        Qui c'era un `except Exception: pass` **nudo**. Ingoiava tutto, quindi:
          · un CIN non letto spariva senza che nessuno lo sapesse -- e il CIN e' l'impronta
            che impedisce a un host di cancellarsi e ri-registrarsi per riprendersi i 90
            giorni a commissione zero. Il buco restava aperto per sempre, in silenzio;
          · e nessun mutante di quelle righe era uccidibile dall'esterno, perche' qualunque
            cosa andasse storta finiva nello stesso silenzio. Lo strato che nasconde gli
            errori impedisce di provare cio' che ci sta sotto (lezione del 2026-07-31).

        L'isolamento resta -- gli altri alloggi si leggono lo stesso -- cambia solo che il
        fallimento adesso si vede: nel registro **e** nel rapporto.
        """
        import logging
        from fase156_erasure import cancella_attivita_host
        visto = {}

        def _esplode(s):
            raise RuntimeError("catalogo guasto su %s" % s)

        sis = _Sistema(
            catalogo=_Archivio(alloggi_host=lambda h, limit=None: [{"slug": "casa"},
                                                                   {"slug": "villa"}],
                               dettaglio=_esplode,
                               cancella_alloggi_host=lambda h: 2,
                               conta_alloggi_host=lambda h: 0),
            registro_host=_Archivio(
                # `update`, non `setdefault`: si guarda l'ULTIMA chiamata, senno' la seconda
                # meta' della prova leggerebbe il risultato della prima e non proverebbe niente
                deposita_impronte=lambda h, extra=None: visto.update({"extra": extra}) or 1,
                cancella_host=lambda h: 1, esiste_host=lambda h: False))
        with self.assertLogs("fase156_erasure", level="WARNING") as reg:
            rep = cancella_attivita_host(sis, "h1", forza=True)
        self.assertEqual(["casa", "villa"], rep.get("cin_non_letti"),
                         "un CIN non letto e' sparito dal rapporto: %r" % (rep,))
        self.assertTrue(any(r.exc_info for r in reg.records),
                        "nessuna traccia dell'errore nel registro: %r" % (reg.output,))
        # l'isolamento NON e' stato sacrificato: le impronte si depositano lo stesso
        self.assertEqual([], visto.get("extra"))
        # ...e a catalogo sano il rapporto NON contiene quella chiave (senno' basterebbe
        # scriverla sempre per far passare la meta' di sopra)
        sis.catalogo.dettaglio = lambda s: {"cin": "IT-%s" % s}
        rep2 = cancella_attivita_host(sis, "h1", forza=True)
        self.assertNotIn("cin_non_letti", rep2)
        self.assertEqual(["IT-casa", "IT-villa"], visto["extra"])

        # ⛔ E IL TERZO CASO, quello che distingue davvero: un catalogo che NON ESPONE
        # `dettaglio`. Non e' un guasto -- e' un archivio che quella cosa non la sa fare, e
        # il modulo e' scritto apposta per reggerlo. Deve saltarlo in silenzio, senza
        # inventarsi un fallimento. (Senza questo caso il mutante `and`->`or` di quella riga
        # sopravvive: con un catalogo che ESPLODE le due strade portano allo stesso errore.)
        senza = _Sistema(
            catalogo=_Archivio(alloggi_host=lambda h, limit=None: [{"slug": "casa"}],
                               cancella_alloggi_host=lambda h: 1,
                               conta_alloggi_host=lambda h: 0),
            registro_host=_Archivio(
                deposita_impronte=lambda h, extra=None: visto.update({"extra": extra}) or 1,
                cancella_host=lambda h: 1, esiste_host=lambda h: False))
        # NB: qui NON si puo' pretendere «nessun record», perche' la forzatura emette il suo
        # `critical` (che e' giusto). Si pretende «nessun WARNING»: cioe' nessun GUASTO.
        with self.assertLogs("fase156_erasure", level="WARNING") as reg3log:
            rep3 = cancella_attivita_host(senza, "h1", forza=True)
        self.assertEqual([], [r.getMessage() for r in reg3log.records
                              if r.levelno == logging.WARNING],
                         "un catalogo che non espone `dettaglio` ha prodotto un allarme di "
                         "guasto: non e' rotto, semplicemente quella cosa non la sa fare")
        self.assertNotIn("cin_non_letti", rep3,
                         "un catalogo che non espone `dettaglio` e' stato scambiato per un "
                         "archivio guasto: %r" % (rep3,))
        self.assertEqual([], visto["extra"])

    def test_ogni_guasto_ISOLATO_lascia_la_traccia_dell_errore(self):
        """Le quattro braccia di questo modulo ingoiano i guasti di proposito (un archivio
        rotto non deve fermare gli altri). Proprio per questo la traccia dell'eccezione e'
        l'unica cosa che resta: senza, il registro dice «un passo e' fallito» e nessuno sapra'
        mai quale archivio, ne' perche'. E' la stessa falsa equivalenza corretta lo stesso
        giorno su `fase199`: `exc_info` **e'** osservabile.

        ⚠️ Osservabile FORTE: con `exc_info=False` il campo del record vale `False`, che NON
        e' `None` -- un `assertIsNotNone` passerebbe col guasto dentro.
        """
        from fase156_erasure import cancella_attivita_host, obblighi_pendenti

        def _esplode(*a, **k):
            raise RuntimeError("archivio guasto")

        casi = (
            ("lettura degli alloggi", lambda: obblighi_pendenti(
                _Sistema(catalogo=_Archivio(alloggi_host=_esplode)), "h1")),
            ("payout", lambda: obblighi_pendenti(
                _Sistema(payout=_Archivio(riepilogo=_esplode)), "h1")),
            ("prenotazioni", lambda: obblighi_pendenti(_Sistema(
                catalogo=_Archivio(alloggi_host=lambda h, limit=None: [{"slug": "casa"}]),
                inventario=_Archivio(elenco_prenotazioni=_esplode)), "h1")),
            ("escrow", lambda: obblighi_pendenti(_Sistema(
                catalogo=_Archivio(alloggi_host=lambda h, limit=None: [{"slug": "casa"}]),
                garanzia=_Archivio(aperte_per_alloggio=_esplode)), "h1")),
            ("sospesi", lambda: obblighi_pendenti(
                _Sistema(pagamenti_pendenti=_Archivio(da_approvare=_esplode)), "h1")),
            ("un passo della cancellazione", lambda: cancella_attivita_host(
                _Sistema(catalogo=_Archivio(alloggi_host=lambda h, limit=None: [],
                                            cancella_alloggi_host=_esplode,
                                            conta_alloggi_host=lambda h: 0)),
                "h1", forza=True)),
        )
        import logging
        for nome, azione in casi:
            with self.assertLogs("fase156_erasure", level="WARNING") as reg:
                azione()
            # SOLO i WARNING: il `critical` di «erasure forzata» non e' il resoconto di un
            # guasto ma la registrazione di una decisione presa, e giustamente non porta
            # nessuna traccia da allegare.
            tracce = [r.exc_info for r in reg.records if r.levelno == logging.WARNING]
            self.assertTrue(tracce, "nessun allarme per il guasto su %s" % nome)
            for t in tracce:
                self.assertIsInstance(t, tuple,
                                      "l'allarme su %s non porta la traccia dell'errore "
                                      "(exc_info=%r): resta «qualcosa e' fallito» e basta"
                                      % (nome, t))
                self.assertIsInstance(t[1], BaseException,
                                      "la traccia su %s non contiene l'eccezione: %r"
                                      % (nome, t))


if __name__ == "__main__":
    unittest.main()
