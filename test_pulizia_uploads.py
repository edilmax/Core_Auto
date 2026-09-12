# -*- coding: utf-8 -*-
"""PULIZIA UPLOADS ORFANI (audit "10 moduli" 2026-07-19) — la scopa e' UTILE ma
soprattutto non deve MAI fare danni: qui si prova (a) la selettivita' (cancella SOLO
orfani vecchi; i file citati da annunci o chat e i file freschi NON si toccano),
(b) il fail-closed (censimento in errore -> zero cancellazioni), (c) il paracadute
(troppi 'orfani' = censimento sospetto -> annulla), (d) il kill-switch, (e) il
gancio 24h del tick."""
import datetime
import os
import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
import json


class TestPuliziaUploads(unittest.TestCase):
    def setUp(self):
        self.dir = d = tempfile.mkdtemp()
        self.updir = os.path.join(d, "uploads")
        os.makedirs(self.updir)
        os.environ["UPLOAD_DIR"] = self.updir
        os.environ.pop("PULIZIA_UPLOADS", None)
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=":memory:", db_inventario=":memory:", db_registro_host=":memory:",
            db_accettazioni=":memory:", db_messaggi=":memory:",
            commissione_bps=1500, psp_bps=300))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://b.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@pu.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]

    def tearDown(self):
        os.environ.pop("PULIZIA_UPLOADS", None)
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _file(self, nome, *, giorni_fa=0):
        p = os.path.join(self.updir, nome)
        with open(p, "wb") as f:
            f.write(b"\x89PNGx")
        if giorni_fa:
            vecchio = time.time() - giorni_fa * 86400
            os.utime(p, (vecchio, vecchio))
        return p

    def test_selettiva_cancella_solo_orfani_vecchi(self):
        self._file("orfano_vecchio.png", giorni_fa=8)
        self._file("orfano_fresco.png")
        self._file("ref_cat.png", giorni_fa=8)
        self._file("ref_chat.png", giorni_fa=8)
        s, c = self.g("POST", "/api/host/pubblica",
                      {"slug": "casa-pulizia", "titolo": "Casa", "citta": "Roma",
                       "prezzo_notte_cents": 10000, "capacita": 2,
                       "immagini": ["/uploads/ref_cat.png"]},
                      {"X-Host-Token": self.tok})
        self.assertIn(s, (200, 201), c)
        self.assertTrue(self.sis.messaggistica.invia(
            "rif-pulizia", "h1", "ospite", "ospite",
            "PROVA FOTO: /uploads/ref_chat.png"))
        rep = self.r.pulizia_uploads_orfani()
        self.assertEqual(rep.get("rimossi"), 1, rep)
        restanti = sorted(os.listdir(self.updir))
        self.assertEqual(restanti, ["orfano_fresco.png", "ref_cat.png", "ref_chat.png"],
                         "cancellato un file SBAGLIATO: %r" % restanti)

    def test_censimento_rotto_zero_cancellazioni(self):
        self._file("orfano_vecchio.png", giorni_fa=8)
        vero = self.sis.catalogo.nomi_uploads
        self.sis.catalogo.nomi_uploads = lambda: (_ for _ in ()).throw(RuntimeError("db giu"))
        try:
            rep = self.r.pulizia_uploads_orfani()
        finally:
            self.sis.catalogo.nomi_uploads = vero
        self.assertEqual(rep.get("saltata"), "censimento_in_errore", rep)
        self.assertEqual(os.listdir(self.updir), ["orfano_vecchio.png"],
                         "fail-closed violato: ha cancellato con censimento rotto")

    def test_paracadute_troppi_orfani(self):
        for i in range(12):
            self._file("orf%02d.png" % i, giorni_fa=8)
        rep = self.r.pulizia_uploads_orfani()
        self.assertEqual(rep.get("saltata"), "paracadute", rep)
        self.assertEqual(len(os.listdir(self.updir)), 12,
                         "paracadute violato: ha cancellato in massa")

    def test_kill_switch(self):
        self._file("orfano_vecchio.png", giorni_fa=8)
        os.environ["PULIZIA_UPLOADS"] = "0"
        rep = self.r.pulizia_uploads_orfani()
        self.assertEqual(rep.get("saltata"), "kill_switch", rep)
        self.assertEqual(os.listdir(self.updir), ["orfano_vecchio.png"])

    def test_gancio_24h(self):
        primo = self.r._pulizia_uploads_se_ora()
        self.assertIsInstance(primo, dict, "la prima corsa deve eseguire")
        self.assertIsNone(self.r._pulizia_uploads_se_ora(),
                          "entro 24h NON deve rieseguire")


class TestLeChatNonRestanoInEternoENonSPARISCONOTroppoPRESTO(unittest.TestCase):
    """La conservazione delle comunicazioni: una regola sola, e vale nelle DUE direzioni.

    PERCHE' (coda dei lavori 1c, «autorizzato» dal fondatore l'11 settembre 2026): le chat
    e le prove foto di una prenotazione non venivano cancellate MAI. `fase113` cancella
    solo su richiesta di oblio di un host (`cancella_messaggi_host`) e la scopa dei file
    porta via soltanto gli upload che nessun messaggio cita: una conversazione di cinque
    anni fa restava intera, e l'informativa non prometteva niente in un senso ne'
    nell'altro.

    ⛔ LE DUE DIREZIONI SONO ENTRAMBE DIFETTI, e questo e' il punto della classe (regola
    ferrea 10). Tenere per sempre viola la minimizzazione; cancellare un giorno troppo
    presto distrugge la prova di una controversia — e il secondo non si ripara.

    ⛔ IL FRENO DELLE CONTROVERSIE VA PROVATO COSTRUENDO LO STATO, non aspettando che
    capiti (D19): una difesa che nessuno ha mai eseguito e' indistinguibile da codice
    morto, e il giorno che serve e' il giorno in cui e' troppo tardi per scoprirlo.
    """

    # Un istante FISSO, cosi' i confini si scrivono a mano e non con la stessa aritmetica
    # che si sta collaudando (collaudo 5, oracolo indipendente: se il conto del motore
    # sbaglia di un giorno, una data calcolata allo stesso modo sbaglierebbe con lui).
    ORA = datetime.datetime(2030, 6, 15, 12, 0, tzinfo=datetime.timezone.utc).timestamp()
    LIMITE = "2028-06-15"          # due anni prima del giorno di ORA, scritto a mano
    VECCHIA = "2028-06-14"         # un giorno OLTRE il termine -> si cancella
    ESATTA = "2028-06-15"          # il termine esatto -> si cancella
    RECENTE = "2028-06-16"         # un giorno PRIMA del termine -> NON si tocca

    def setUp(self):
        self.dir = d = tempfile.mkdtemp()
        self.updir = os.path.join(d, "uploads")
        os.makedirs(self.updir)
        os.environ["UPLOAD_DIR"] = self.updir
        os.environ.pop("PULIZIA_UPLOADS", None)
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=":memory:", db_inventario=":memory:", db_registro_host=":memory:",
            db_accettazioni=":memory:", db_messaggi=":memory:",
            commissione_bps=1500, psp_bps=300))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://b.com")

    def tearDown(self):
        os.environ.pop("PULIZIA_UPLOADS", None)
        shutil.rmtree(self.dir, ignore_errors=True)

    def _passata(self, **kw):
        from fase83_server import conservazione_una_passata
        kw.setdefault("ora_ts", self.ORA)
        return conservazione_una_passata(self.sis, **kw)

    def _prenotazione(self, rif, check_out, *, stato="pagato", messaggi=1, ts_messaggi=None):
        """Una prenotazione col suo thread.

        ⛔ `ts_messaggi` DATA I MESSAGGI, e serve a isolare UNA ancora per volta. Senza,
        una guardia sull'ancora del giornale passerebbe perche' la trattiene il messaggio
        recente: verde per il motivo sbagliato, cioe' il primo dei tre sbagli scritti nel
        diario del 12 settembre. L'orologio di `fase113` e' iniettabile: si sposta per
        scrivere e si rimette, cosi' il banco non lascia dietro uno stato alterato."""
        ci = (datetime.date.fromisoformat(check_out)
              - datetime.timedelta(days=2)).isoformat()
        self.assertTrue(self.sis.pagamenti_pendenti.registra(
            rif, alloggio_id="casa-x", check_in=ci, check_out=check_out,
            email="o@x.it", stato=stato), "banco: prenotazione non registrata")
        orologio = self.sis.messaggistica._now
        if ts_messaggi is not None:
            self.sis.messaggistica._now = lambda: int(ts_messaggi)
        try:
            for i in range(messaggi):
                self.assertTrue(self.sis.messaggistica.invia(
                    rif, "h1", "ospite", "ospite", "messaggio %d" % i),
                    "banco: messaggio non scritto")
        finally:
            self.sis.messaggistica._now = orologio
        return rif

    def _controversia(self, rif, *, aperta):
        self.assertTrue(self.sis.garanzia.apri(rif, 10000, alloggio_id="casa-x"),
                        "banco: garanzia non aperta")
        esito = self.sis.garanzia.contesta(rif)
        self.assertTrue(esito.get("ok"), "banco: controversia non aperta: %s" % esito)
        if not aperta:
            esito = self.sis.garanzia.risolvi(rif, rimborso_ospite_cents=0)
            self.assertTrue(esito.get("ok"), "banco: controversia non chiusa: %s" % esito)

    # ── la direzione «non restano in eterno» ────────────────────────────────────────
    def test_una_chat_oltre_il_termine_viene_cancellata_DAVVERO(self):
        rif = self._prenotazione("rif-vecchia", self.VECCHIA, messaggi=3)
        esito = self._passata()
        self.assertIn(rif, esito.get("cancellate", []), esito)
        self.assertEqual(self.sis.messaggistica.thread(rif, "ospite"), [],
                         "la passata dice cancellata ma i messaggi sono ancora li'")

    def test_il_termine_ESATTO_e_dentro_la_promessa(self):
        rif = self._prenotazione("rif-esatta", self.ESATTA)
        self.assertIn(rif, self._passata().get("cancellate", []))

    # ── la direzione «non sparisce troppo presto» ───────────────────────────────────
    def test_una_chat_DENTRO_il_termine_non_si_tocca(self):
        rif = self._prenotazione("rif-recente", self.RECENTE, messaggi=2)
        esito = self._passata()
        self.assertNotIn(rif, esito.get("cancellate", []), esito)
        self.assertEqual(len(self.sis.messaggistica.thread(rif, "ospite")), 2,
                         "cancellata una chat ancora dentro il termine promesso")

    def test_una_CONTROVERSIA_APERTA_trattiene_per_sempre(self):
        """Il caso che non si puo' sbagliare: finche' si litiga, la prova resta. Il
        fondamento e' l'art. 17.3.e del GDPR (difesa in giudizio), ed e' la ragione per
        cui la cancellazione programmata si SOSPENDE invece di proseguire."""
        rif = self._prenotazione("rif-contesa", "2020-01-01", messaggi=2)
        self._controversia(rif, aperta=True)
        esito = self._passata()
        self.assertNotIn(rif, esito.get("cancellate", []), esito)
        self.assertIn(rif, esito.get("trattenute", []), esito)
        self.assertEqual(len(self.sis.messaggistica.thread(rif, "ospite")), 2,
                         "cancellata la prova di una controversia APERTA")

    def test_una_controversia_CHIUSA_DI_RECENTE_fa_ripartire_il_termine(self):
        """«2 anni dal check-out, o dalla chiusura della controversia se e' piu' tardi»:
        senza questo, una controversia chiusa oggi su un soggiorno di tre anni fa
        perderebbe le sue prove il giorno stesso in cui si e' chiusa."""
        rif = self._prenotazione("rif-chiusa-ieri", "2020-01-01", messaggi=2,
                                 ts_messaggi=time.time() - 3 * 365 * 86400)
        self._controversia(rif, aperta=False)
        self.r._giornale(tipo="rimborso", riferimento=rif, soggetto="ospite:" + rif,
                         importo_cents=1000, valuta="EUR",
                         causale="rimborso deciso dall'arbitro (banco)",
                         evento_id="rimborso_controversia:" + rif)
        esito = self._passata(ora_ts=time.time() + 10 * 86400)
        self.assertNotIn(rif, esito.get("cancellate", []), esito)
        self.assertEqual(len(self.sis.messaggistica.thread(rif, "ospite")), 2,
                         "cancellate le prove di una controversia appena chiusa")

    def test_un_messaggio_RECENTE_trattiene_una_prenotazione_vecchia(self):
        """Si conta dalla data piu' RECENTE fra quelle osservabili. Una conversazione
        ancora viva non e' materiale scaduto, qualunque cosa dica il check-out."""
        rif = self._prenotazione("rif-viva", "2020-01-01", messaggi=1)
        esito = self._passata(ora_ts=time.time() + 10 * 86400)
        self.assertNotIn(rif, esito.get("cancellate", []), esito)
        self.assertEqual(len(self.sis.messaggistica.thread(rif, "ospite")), 1)

    # ── fail-closed: nel dubbio non si cancella ─────────────────────────────────────
    def test_senza_archivio_delle_controversie_NON_si_cancella_niente(self):
        rif = self._prenotazione("rif-senza-garanzia", self.VECCHIA)
        self.sis.garanzia = None
        esito = self._passata()
        self.assertEqual(esito.get("cancellate", []), [], esito)
        self.assertTrue(esito.get("saltata"), "non dichiara PERCHE' non ha cancellato")
        self.assertEqual(len(self.sis.messaggistica.thread(rif, "ospite")), 1,
                         "ha cancellato senza poter sapere se c'era una controversia")

    def test_se_l_archivio_delle_controversie_SBAGLIA_non_si_cancella_niente(self):
        """Un archivio che solleva non e' un archivio che dice «nessuna controversia»:
        e' una misura mancante, e una misura mancante non autorizza a distruggere."""
        rif = self._prenotazione("rif-garanzia-rotta", self.VECCHIA)
        self.sis.garanzia.stato = lambda _p: (_ for _ in ()).throw(RuntimeError("db giu"))
        esito = self._passata()
        self.assertEqual(esito.get("cancellate", []), [], esito)
        self.assertEqual(len(self.sis.messaggistica.thread(rif, "ospite")), 1,
                         "fail-closed violato: ha cancellato con l'archivio rotto")

    # ── il resto della catena, e cio' che NON deve toccare ──────────────────────────
    def test_la_cancellazione_lascia_la_sua_riga_nel_registro(self):
        """Senza riga, il giorno che qualcuno chiede «dov'e' finita quella chat?» la
        risposta e' «non si sa»: e' l'osservabile debole della regola ferrea 9."""
        rif = self._prenotazione("rif-registro", self.VECCHIA)
        with self.assertLogs("core_auto", level="INFO") as reg:
            self._passata()
        righe = [x for x in reg.output if "CONSERVAZIONE" in x]
        self.assertTrue(righe, "nessuna riga CONSERVAZIONE nel registro: %s" % reg.output)
        self.assertTrue(any(rif[-4:] in x for x in righe),
                        "la riga non dice DI QUALE prenotazione: %s" % righe)

    def test_le_foto_diventano_orfane_e_la_scopa_ESISTENTE_le_porta_via(self):
        """L'anello finale: la chat sparisce e le prove foto restano su disco finche'
        qualcuno le raccoglie. Provato fino in fondo, non fino al penultimo anello."""
        rif = self._prenotazione("rif-foto", self.VECCHIA, messaggi=0)
        nome = "a" * 32 + ".png"
        p = os.path.join(self.updir, nome)
        with open(p, "wb") as f:
            f.write(b"\x89PNGx")
        vecchio = time.time() - 30 * 86400
        os.utime(p, (vecchio, vecchio))
        self.assertTrue(self.sis.messaggistica.invia(
            rif, "h1", "ospite", "ospite", "PROVA FOTO: /uploads/" + nome))
        self.assertEqual(self.r.pulizia_uploads_orfani().get("rimossi"), 0,
                         "la foto era citata in chat: non doveva essere toccata")
        self.assertIn(rif, self._passata().get("cancellate", []))
        self.assertEqual(self.r.pulizia_uploads_orfani().get("rimossi"), 1,
                         "la foto e' rimasta orfana su disco dopo la cancellazione")
        self.assertEqual(os.listdir(self.updir), [])

    def test_i_SOLDI_non_si_toccano(self):
        """I soldi hanno un termine diverso e piu' lungo (scritture contabili, art. 2220
        c.c.): questa passata guarda le comunicazioni e NON deve sfiorare ne' la riga
        della prenotazione ne' il giornale."""
        rif = self._prenotazione("rif-soldi", self.VECCHIA)
        self.r._giornale(tipo="incasso", riferimento=rif, soggetto="ospite:" + rif,
                         importo_cents=5000, valuta="EUR", causale="incasso (banco)",
                         evento_id="incasso:" + rif)
        prima = len(self.sis.finanza.movimenti(rif))
        self._passata()
        self.assertIsNotNone(self.sis.pagamenti_pendenti.info(rif),
                             "ha cancellato la riga della PRENOTAZIONE")
        self.assertEqual(len(self.sis.finanza.movimenti(rif)), prima,
                         "ha toccato il GIORNALE dei soldi")

    def test_ripassare_non_cancella_due_volte_e_non_esplode(self):
        rif = self._prenotazione("rif-due-volte", self.VECCHIA)
        self.assertIn(rif, self._passata().get("cancellate", []))
        secondo = self._passata()
        self.assertEqual(secondo.get("cancellate", []), [], secondo)

    def test_il_gancio_gira_una_volta_al_giorno(self):
        self._prenotazione("rif-gancio", self.VECCHIA)
        primo = self.r._conservazione_se_ora()
        self.assertIsInstance(primo, dict, "la prima corsa deve eseguire")
        self.assertIsNone(self.r._conservazione_se_ora(),
                          "entro 24h NON deve rieseguire")

    def test_cancellato_vuol_dire_che_NON_SI_RILEGGE_DAL_FILE(self):
        """«Cancellata» deve essere vero anche aprendo il database con un editor
        esadecimale, non solo interrogandolo con SQL.

        ⛔ MISURATO NELLE DUE DIREZIONI prima di scrivere questa guardia, il 12 settembre
        2026: un `DELETE` normale su una tabella identica lascia il testo dentro il file
        (spia trovata nei byte), mentre `cancella_thread` lo azzera (spia assente). Se
        qualcuno togliesse il pragma, l'informativa continuerebbe a promettere una
        cancellazione che il disco non fa — e nessuna query lo direbbe.
        """
        import glob
        from fase113_messaggistica import crea_messaggistica
        percorso = os.path.join(self.dir, "conservazione.db")
        msg = crea_messaggistica(percorso)
        msg.inizializza_schema()
        # ⛔ NIENTE CIFRE DI FILA: `maschera_pii` prende una sequenza lunga di numeri per un
        # telefono e la sostituisce, la spia non arriva nel file e il test passerebbe A
        # VUOTO (spia assente prima e dopo). L'ha trovato il controllo della premessa qui
        # sotto, che senza questa riga avrebbe detto «cancellato» senza aver visto niente.
        spia = "SPIA-CONSERVAZIONE-" + "Q" * 12
        self.assertTrue(msg.invia("rif-bytes", "h1", "ospite", "ospite", spia))

        def nei_byte():
            dentro = []
            for f in sorted(glob.glob(percorso + "*")):
                with open(f, "rb") as fh:
                    if spia.encode("utf-8") in fh.read():
                        dentro.append(os.path.basename(f))
            return dentro

        self.assertTrue(nei_byte(), "il banco non ha scritto niente: misura non valida")
        self.assertEqual(msg.cancella_thread("rif-bytes"), 1)
        self.assertEqual(nei_byte(), [],
                         "il testo cancellato si rilegge ancora dai byte del database")

    def test_anche_l_OBLIO_di_un_host_azzera_i_byte(self):
        """L'oblio del GDPR (art. 17) e' la cancellazione con l'obbligo piu' forte di tutti:
        la chiede la persona, e la legge dice che deve avvenire. Se resta leggibile nei byte
        del file, quella cancellazione non e' avvenuta.

        ⛔ Oggi `cancella_messaggi_host` non sovrascrive: il pragma sta soltanto nel giro
        della conservazione. Cioe' la cancellazione con l'obbligo piu' debole (un termine che
        ci siamo dati noi) e' fatta meglio di quella con l'obbligo piu' forte."""
        import glob
        from fase113_messaggistica import crea_messaggistica
        percorso = os.path.join(self.dir, "oblio.db")
        msg = crea_messaggistica(percorso)
        msg.inizializza_schema()
        spia = "SPIA-OBLIO-" + "Z" * 12      # niente cifre di fila: le maschera `maschera_pii`
        self.assertTrue(msg.invia("rif-oblio", "host-da-dimenticare", "ospite", "ospite", spia))

        def nei_byte():
            dentro = []
            for f in sorted(glob.glob(percorso + "*")):
                with open(f, "rb") as fh:
                    if spia.encode("utf-8") in fh.read():
                        dentro.append(os.path.basename(f))
            return dentro

        self.assertTrue(nei_byte(), "il banco non ha scritto niente: misura non valida")
        self.assertEqual(msg.cancella_messaggi_host("host-da-dimenticare"), 1)
        self.assertEqual(nei_byte(), [],
                         "i messaggi cancellati per OBLIO si rileggono ancora dai byte del "
                         "database")

    def test_il_giro_ORARIO_lo_chiama_DAVVERO(self):
        """Costruito non vuol dire collegato: e' il modo di rompersi n.2, e su questo
        progetto e' il piu' frequente di tutti. Un giro perfetto che nessuno chiama non
        cancella niente, e la pagina continua a promettere che cancella.

        ⛔ Si legge l'ALBERO SINTATTICO, non il testo del sorgente: una guardia che
        cercasse il nome fra le righe la soddisferebbe un commento (sbaglio S6)."""
        import ast
        import io as _io
        sorgente = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "fase83_server.py")
        with _io.open(sorgente, encoding="utf-8") as f:
            albero = ast.parse(f.read())
        avvio = [n for n in ast.walk(albero)
                 if isinstance(n, ast.FunctionDef) and n.name == "servi"]
        self.assertEqual(len(avvio), 1,
                         "la funzione che avvia il server non si trova: questa guardia "
                         "non ha guardato niente")
        chiamate = [n for n in ast.walk(avvio[0])
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "_conservazione_se_ora"]
        self.assertTrue(chiamate,
                        "nessun giro periodico chiama la conservazione: il pezzo esiste e "
                        "non e' collegato a niente")


class TestIlGiroDellOblioEPercorsoDAVVERO(unittest.TestCase):
    """⛔ D18 PUNTO 4 — l'esame dell'oblio e' a sua volta sotto guardia.

    `collaudi/esame_oblio.py` percorre il giro intero del «cancellami»: il dato c'era, la
    cancellazione lo toglie, quello che resta e' dichiarato per legge col suo perche', e
    non si rilegge dai byte. Senza questa classe quell'esame vivrebbe fuori dalla suite:
    fra sei mesi lo toglierebbe una «semplificazione» e nessuno se ne accorgerebbe.

    ⛔ E si ESEGUE, nelle due direzioni. Un test che controllasse solo che il file esiste
    sarebbe soddisfatto da un file vuoto — e sarebbe la guardia ornamentale che questo
    progetto ha gia' pagato tre volte in un giorno.
    """

    def _giro(self, argomenti):
        import contextlib
        import io as _io
        from collaudi.esame_oblio import principale
        muto = _io.StringIO()
        with contextlib.redirect_stdout(muto):
            codice = principale(argomenti)
        return codice, muto.getvalue()

    def test_il_giro_intero_e_verde(self):
        codice, uscita = self._giro([])
        self.assertEqual(codice, 0,
                         "il giro intero dell'oblio non e' verde:\n%s" % uscita[-1500:])
        self.assertIn("anelli", uscita, "l'esame non dichiara il denominatore")

    def test_e_sa_diventare_ROSSO(self):
        codice, uscita = self._giro(["--guasto", "salta-oblio"])
        self.assertEqual(codice, 1,
                         "col guasto iniettato (l'oblio NON viene eseguito) l'esame resta "
                         "verde: allora non sta guardando niente")


if __name__ == "__main__":
    unittest.main(verbosity=2)
