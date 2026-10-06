"""IDOR su /api/host/foto_elimina (Compiti 46-49 di GML, verificati da Claude sul codice).

Il buco: `_foto_elimina` (fase83) controlla che il chiamante sia un host, ma NON che la foto
sia SUA. Le URL delle foto sono pubbliche sugli annunci: un host A puo' copiare l'URL di una
foto pubblicata nell'annuncio di un host B e cancellargliela (vandalismo).

La riparazione non deve rompere il gesto LEGITTIMO: cancellare una foto appena caricata e non
ancora pubblicata (host.html chiama foto_elimina come pulizia best-effort).

E i tre modi che il primo controllo (quello che legge gli annunci) lasciava aperti, misurati il
2026-10-05 sulle rotte vere:
  · la BOZZA-TRUCCO (Compito 48 di GML): A salva una bozza sul proprio annuncio con l'URL della
    foto di B; un controllo che chiede «e' citata dai tuoi annunci?» risponde si' e la cancella;
  · la PROVA FOTO dell'ospite (Compito 49): l'ospite la carica dal voucher in una controversia,
    finisce nella STESSA cartella, e l'host della prenotazione ne legge l'URL nella chat: poteva
    cancellare la prova mentre l'arbitro decide il rimborso;
  · i NOMI-ALIAS: sul laboratorio Windows (NTFS) `ABC.PNG`, `abc.png.`, `abc.png ` e
    `abc.png::$DATA` aprono LO STESSO file di `abc.png`; in produzione (Linux) sono file che non
    esistono. In tutti e due i casi la richiesta va rifiutata e il file resta.

D20: queste guardie sono viste ROSSE sul codice di produzione prima della riparazione.
"""
import base64
import datetime
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

SEG = b"h" * 32
HK = {"X-Host-Key": "hk"}
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200).decode()


class TestIdorFotoElimina(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.updir = os.path.join(d, "uploads")
        os.makedirs(self.updir)
        self._old_updir = os.environ.get("UPLOAD_DIR")
        os.environ["UPLOAD_DIR"] = self.updir
        self.db_catalogo = f"{d}/c.db"
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, con_registrazione_host=True,
            db_catalogo=self.db_catalogo, db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db", db_domanda=f"{d}/dom.db",
            db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_tassa_comunale=f"{d}/tc.db", db_finanza=f"{d}/fin.db",
            file_referral=f"{d}/ref.json", commissione_bps=1000))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        esA = self.sis.registro_host.registra("a@collaudo.invalid", "password12",
                                              accetta_termini=True)
        esB = self.sis.registro_host.registra("b@collaudo.invalid", "password12",
                                              accetta_termini=True)
        self.hidA, self.tokA = esA.host_id, esA.token
        self.hidB, self.tokB = esB.host_id, esB.token
        self.assertTrue(self.hidA and self.tokA and self.hidB and self.tokB)
        for nome in ("vittimaB.jpg", "miaA.jpg", "orfana.jpg"):
            with open(os.path.join(self.updir, nome), "wb") as f:
                f.write(b"\xff\xd8\xff\x00jpeg")
        self._pubblica(self.hidA, "casa-a", "/uploads/miaA.jpg")
        self._pubblica(self.hidB, "casa-b", "/uploads/vittimaB.jpg")

    def tearDown(self):
        if self._old_updir is None:
            os.environ.pop("UPLOAD_DIR", None)
        else:
            os.environ["UPLOAD_DIR"] = self._old_updir
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _pubblica(self, hid, slug, url):
        s, c = self.g("POST", "/api/host/pubblica",
                      {"host_id": hid, "slug": slug, "titolo": "T", "citta": "Roma",
                       "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
                       "servizi": [], "immagini": [url]}, HK)
        self.assertIn(s, (200, 201), "pubblica %s: %s" % (slug, c))

    def _carica(self, token):
        """Una foto caricata DAL PANNELLO, come fa host.html: la rotta vera, col token."""
        s, c = self.g("POST", "/api/host/upload_foto", {"image_base64": PNG},
                      {"X-Host-Token": token})
        self.assertEqual(s, 201, c)
        return c["url"]

    def _esiste(self, nome):
        return os.path.isfile(os.path.join(self.updir, nome))

    def _urls_dell_annuncio(self, slug):
        """Oracolo indipendente: le immagini dell'annuncio lette dall'archivio, non dal codice."""
        con = sqlite3.connect(self.db_catalogo)
        try:
            return [r[0] for r in con.execute(
                "SELECT i.url FROM alloggio_immagini i JOIN alloggi a ON a.id = i.alloggio_id "
                "WHERE a.slug = ?", (slug,))]
        finally:
            con.close()

    def test_host_NON_cancella_la_foto_pubblicata_di_un_altro(self):
        s, c = self.g("POST", "/api/host/foto_elimina", {"url": "/uploads/vittimaB.jpg"},
                      {"X-Host-Token": self.tokA})
        self.assertEqual(s, 403, "un host ha potuto cancellare la foto di un altro: %s" % (c,))
        self.assertTrue(self._esiste("vittimaB.jpg"),
                        "la foto pubblicata di B e' stata cancellata da A")

    def test_host_cancella_la_PROPRIA_foto_pubblicata(self):
        s, c = self.g("POST", "/api/host/foto_elimina", {"url": "/uploads/miaA.jpg"},
                      {"X-Host-Token": self.tokA})
        self.assertEqual(s, 200, c)
        self.assertFalse(self._esiste("miaA.jpg"))

    def test_un_file_SENZA_padrone_e_non_citato_un_host_non_lo_cancella(self):
        """Si nega per difetto (OWASP, «Deny by Default»; concordato con GML, Compito 49 D-a).
        Fino al 2026-10-05 qui c'era la prova opposta («orfana scritta a mano -> 200»): un file
        che nessun host ha caricato dal pannello, cancellabile da chiunque. Il gesto legittimo
        (la foto appena caricata e tolta prima di salvare) lo copre il proprietario registrato,
        e lo prova la guardia qui sotto; l'orfano senza padrone lo toglie la pulizia dei 7 giorni.
        E' questa regola a chiudere i nomi-alias (`abc.png.`) sul laboratorio Windows."""
        s, c = self.g("POST", "/api/host/foto_elimina", {"url": "/uploads/orfana.jpg"},
                      {"X-Host-Token": self.tokA})
        self.assertEqual((s, c), (403, {"errore": "non_tua"}))
        self.assertTrue(self._esiste("orfana.jpg"))

    def test_la_foto_appena_caricata_DAL_PANNELLO_si_cancella(self):
        """Il gesto legittimo, con la rotta vera: caricata col token e tolta prima di salvare."""
        url = self._carica(self.tokA)
        nome = url.rsplit("/", 1)[1]
        self.assertTrue(self._esiste(nome), "premessa: il caricamento non ha scritto il file")
        s, c = self.g("POST", "/api/host/foto_elimina", {"url": url},
                      {"X-Host-Token": self.tokA})
        self.assertEqual((s, c), (200, {"eliminata": True}))
        self.assertFalse(self._esiste(nome))

    def test_una_BOZZA_con_l_URL_di_B_non_rende_la_foto_di_A(self):
        """La bozza-trucco (Compito 48): rossa il 2026-10-05 sul primo controllo, 200 e file
        sparito."""
        url = self._carica(self.tokB)
        nome = url.rsplit("/", 1)[1]
        s, c = self.g("POST", "/api/host/pubblica",
                      {"slug": "casa-b2", "titolo": "T", "citta": "Roma", "descrizione": "x",
                       "prezzo_notte_cents": 10000, "capacita": 2, "servizi": [],
                       "immagini": [url]}, {"X-Host-Token": self.tokB})
        self.assertIn(s, (200, 201), c)
        s, c = self.g("POST", "/api/host/pubblica",
                      {"slug": "bozza-a", "titolo": "T", "citta": "Roma", "descrizione": "x",
                       "prezzo_notte_cents": 10000, "capacita": 2, "servizi": [],
                       "stato": "bozza", "immagini": [url]}, {"X-Host-Token": self.tokA})
        self.assertIn(s, (200, 201), c)
        # PREMESSA (S7): la bozza di A cita DAVVERO la foto di B, letto dall'archivio.
        self.assertEqual(self._urls_dell_annuncio("bozza-a"), [url])
        s, c = self.g("POST", "/api/host/foto_elimina", {"url": url},
                      {"X-Host-Token": self.tokA})
        self.assertEqual(s, 403, "la bozza-trucco ha aperto la cancellazione: %s" % (c,))
        self.assertTrue(self._esiste(nome), "la foto di B e' stata cancellata da A")

    def test_il_proprietario_vero_cancella_anche_se_un_altro_la_cita(self):
        """L'altra faccia della bozza-trucco: chi ha caricato la foto resta libero di toglierla,
        anche se un altro l'ha copiata in un suo annuncio."""
        url = self._carica(self.tokB)
        nome = url.rsplit("/", 1)[1]
        s, c = self.g("POST", "/api/host/pubblica",
                      {"slug": "bozza-a", "titolo": "T", "citta": "Roma", "descrizione": "x",
                       "prezzo_notte_cents": 10000, "capacita": 2, "servizi": [],
                       "stato": "bozza", "immagini": [url]}, {"X-Host-Token": self.tokA})
        self.assertIn(s, (200, 201), c)
        self.assertEqual(self._urls_dell_annuncio("bozza-a"), [url])
        s, c = self.g("POST", "/api/host/foto_elimina", {"url": url},
                      {"X-Host-Token": self.tokB})
        self.assertEqual((s, c), (200, {"eliminata": True}))
        self.assertFalse(self._esiste(nome))

    def _prova_dell_ospite(self):
        """Una prenotazione sull'alloggio di A e la foto-prova che l'ospite carica dal voucher.
        Ritorna (url, nome) dopo aver verificato che l'host la VEDE nelle sue conversazioni."""
        oggi = datetime.date.today()
        ci = (oggi + datetime.timedelta(days=30)).isoformat()
        co = (oggi + datetime.timedelta(days=31)).isoformat()
        self.sis.inventario.imposta_disponibilita("casa-a", ci, unita_totali=1,
                                                  prezzo_netto_cents=10000)
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-a", "check_in": ci, "check_out": co})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "ospite@collaudo.invalid"})
        self.assertEqual(s, 201, b)
        s, c = self.g("POST", "/api/voucher/prova",
                      {"voucher_token": b["voucher_token"], "image_base64": PNG})
        self.assertEqual(s, 201, c)
        url = c["url"]
        nome = url.rsplit("/", 1)[1]
        # PREMESSA (S7): l'host della prenotazione LEGGE quell'URL nelle sue conversazioni.
        s, conv = self.g("GET", "/api/host/conversazioni", h={"X-Host-Token": self.tokA})
        self.assertEqual(s, 200, conv)
        self.assertIn(url, json.dumps(conv), "premessa: l'host non vede la prova")
        self.assertTrue(self._esiste(nome), "premessa: la prova non e' su disco")
        return url, nome

    def test_l_host_NON_cancella_la_PROVA_FOTO_dell_ospite(self):
        """La prova di una controversia (Compito 49): rossa il 2026-10-05, 200 e file sparito."""
        url, nome = self._prova_dell_ospite()
        s, c = self.g("POST", "/api/host/foto_elimina", {"url": url},
                      {"X-Host-Token": self.tokA})
        self.assertEqual(s, 403, "l'host ha cancellato la prova dell'ospite: %s" % (c,))
        self.assertTrue(self._esiste(nome), "la prova dell'ospite e' sparita")

    def test_la_PROVA_non_si_cancella_nemmeno_citandola_in_una_bozza(self):
        """Le due strade insieme: l'host cita la prova in una SUA bozza, e cosi' per il catalogo
        e' una foto «citata solo dai suoi annunci». Qui la ferma solo la regola della chat: si
        vede rossa togliendo quella regola (un file senza padrone e non citato lo nega gia' il
        catalogo, quindi la guardia qui sopra non basta a provarla)."""
        url, nome = self._prova_dell_ospite()
        s, c = self.g("POST", "/api/host/pubblica",
                      {"slug": "bozza-prova", "titolo": "T", "citta": "Roma", "descrizione": "x",
                       "prezzo_notte_cents": 10000, "capacita": 2, "servizi": [],
                       "stato": "bozza", "immagini": [url]}, {"X-Host-Token": self.tokA})
        self.assertIn(s, (200, 201), c)
        self.assertEqual(self._urls_dell_annuncio("bozza-prova"), [url])
        s, c = self.g("POST", "/api/host/foto_elimina", {"url": url},
                      {"X-Host-Token": self.tokA})
        self.assertEqual(s, 403, "la bozza ha aperto la cancellazione della prova: %s" % (c,))
        self.assertTrue(self._esiste(nome), "la prova dell'ospite e' sparita")

    def test_il_padrone_cancella_la_SUA_foto_anche_se_l_ha_incollata_in_chat(self):
        """L'emendamento di GML (Compito 49): prima il padrone, poi la chat. La chat e' testo
        libero, e un host che spiega all'ospite una foto del suo annuncio ne incolla l'URL: con la
        chat controllata per prima, la SUA foto diventava non cancellabile per sempre."""
        url = self._carica(self.tokA)
        nome = url.rsplit("/", 1)[1]
        # la chat e' di una prenotazione VERA di A (V1 della busta 6, 2026-10-05)
        self.assertTrue(self.sis.pagamenti_pendenti.registra(
            "pren-della-chat", alloggio_id="casa-a", check_in="2027-03-01",
            check_out="2027-03-03", host_id=self.hidA))
        s, c = self.g("POST", "/api/messaggi",
                      {"prenotazione_id": "pren-della-chat", "guest_id": "ospite",
                       "testo": "ecco la foto del balcone: " + url},
                      {"X-Host-Token": self.tokA})
        self.assertEqual(s, 201, c)
        # PREMESSA (S7): la chat CITA davvero quel file.
        self.assertIn(nome, self.sis.messaggistica.nomi_uploads())
        s, c = self.g("POST", "/api/host/foto_elimina", {"url": url},
                      {"X-Host-Token": self.tokA})
        self.assertEqual((s, c), (200, {"eliminata": True}))
        self.assertFalse(self._esiste(nome))

    def test_un_nome_ALIAS_della_foto_di_B_non_la_cancella(self):
        """Rossa il 2026-10-05: 200 su Linux (file inesistente) e, sul laboratorio, file di B
        sparito. Rifiuto (403 o 422) e file intatto, sui due sistemi."""
        for alias in ("/uploads/VITTIMAB.JPG", "/uploads/vittimaB.jpg.",
                      "/uploads/vittimaB.jpg ", "/uploads/vittimaB.jpg::$DATA"):
            s, c = self.g("POST", "/api/host/foto_elimina", {"url": alias},
                          {"X-Host-Token": self.tokA})
            self.assertIn(s, (403, 422), "%r: %s %s" % (alias, s, c))
            self.assertTrue(self._esiste("vittimaB.jpg"),
                            "%r ha cancellato la foto di B" % (alias,))

    def test_la_foto_NON_pubblicata_di_B_non_la_cancella_A(self):
        """La 1d di GML (Compito 49): un URL che trapela (un registro, un referer) non basta."""
        url = self._carica(self.tokB)
        nome = url.rsplit("/", 1)[1]
        s, c = self.g("POST", "/api/host/foto_elimina", {"url": url},
                      {"X-Host-Token": self.tokA})
        self.assertEqual(s, 403, "A ha cancellato la foto appena caricata da B: %s" % (c,))
        self.assertTrue(self._esiste(nome))

    def test_l_operatore_cancella_ancora(self):
        """Il back-office (X-Host-Key, nessun token) resta libero, come `_verifica_proprieta`."""
        s, c = self.g("POST", "/api/host/foto_elimina", {"url": "/uploads/vittimaB.jpg"}, HK)
        self.assertEqual((s, c), (200, {"eliminata": True}))
        self.assertFalse(self._esiste("vittimaB.jpg"))

    def _righe_proprietario(self, host_id):
        con = sqlite3.connect(self.db_catalogo)
        try:
            return con.execute("SELECT COUNT(*) FROM upload_proprietario WHERE host_id = ?",
                               (host_id,)).fetchone()[0]
        finally:
            con.close()

    def test_il_padrone_si_scrive_quando_il_file_nasce(self):
        url = self._carica(self.tokA)
        con = sqlite3.connect(self.db_catalogo)
        try:
            righe = con.execute("SELECT nome, host_id FROM upload_proprietario").fetchall()
        finally:
            con.close()
        self.assertEqual(righe, [(url.rsplit("/", 1)[1], self.hidA)])

    def test_l_OBLIO_porta_via_anche_le_righe_del_padrone(self):
        """Le righe portano l'host_id: l'oblio (fase156) che lo ritrova in catalogo.db risponde
        errore alla persona. Si vede rossa togliendo il DELETE in `cancella_alloggi_host`."""
        from fase156_erasure import cancella_attivita_host
        self._carica(self.tokA)
        self.assertEqual(self._righe_proprietario(self.hidA), 1, "premessa: nessuna riga di A")
        rep = cancella_attivita_host(self.sis, self.hidA)
        self.assertEqual(self._righe_proprietario(self.hidA), 0, rep)
        sporche = [t for tabelle in (rep.get("archivi_sporchi") or {}).values() for t in tabelle]
        self.assertNotIn("upload_proprietario", sporche, rep)

    def test_se_la_proprieta_non_si_legge_si_NEGA(self):
        """D19: le due letture che decidono, guaste a mano. La foto e' di A, eppure no."""
        from unittest import mock
        url = self._carica(self.tokA)
        nome = url.rsplit("/", 1)[1]
        guasto = sqlite3.OperationalError("archivio guasto (finto, nel collaudo)")
        for oggetto, metodo in ((self.sis.catalogo, "upload_cancellabile_da"),
                                (self.sis.messaggistica, "nomi_uploads")):
            with mock.patch.object(oggetto, metodo, side_effect=guasto):
                with self.assertLogs("core_auto.server", level="WARNING") as registro:
                    s, c = self.g("POST", "/api/host/foto_elimina", {"url": url},
                                  {"X-Host-Token": self.tokA})
            self.assertEqual((s, c), (403, {"errore": "non_tua"}), metodo)
            self.assertTrue(self._esiste(nome), metodo)
            self.assertTrue(any("fail-closed" in r for r in registro.output), registro.output)

    def test_se_il_padrone_non_si_scrive_l_upload_resta_valido(self):
        from unittest import mock
        with mock.patch.object(self.sis.catalogo, "registra_upload",
                               side_effect=sqlite3.OperationalError("finto")):
            with self.assertLogs("core_auto.server", level="ERROR") as registro:
                s, c = self.g("POST", "/api/host/upload_foto", {"image_base64": PNG},
                              {"X-Host-Token": self.tokA})
        self.assertEqual(s, 201, c)
        self.assertTrue(self._esiste(c["url"].rsplit("/", 1)[1]))
        self.assertTrue(any("proprietario NON registrato" in r for r in registro.output),
                        registro.output)

    def test_la_foto_IMPORTATA_e_di_chi_importa(self):
        """La G10 di GML: le foto ri-ospitate dall'import hanno il padrone come quelle del
        pannello, cosi' chi importa resta libero di toglierle anche se un altro le cita."""
        import http.server
        import threading
        from unittest import mock
        import fase83_server
        png = base64.b64decode(PNG)

        class Servitore(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(png)

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), Servitore)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with mock.patch.object(fase83_server, "_ip_host_pubblico", lambda h: True):
                s, r = self.g("POST", "/api/host/importa", {
                    "sorgente": "canonico",
                    "dati": {"titolo": "Importata", "citta": "Roma", "prezzo_notte": "80.00",
                             "capacita": 2, "immagini": ["http://127.0.0.1:%d/x.png"
                                                         % srv.server_address[1]]}},
                    {"X-Host-Token": self.tokA})
        finally:
            srv.shutdown()
        self.assertEqual(s, 200, r)
        self.assertEqual(r["importati"], 1, r)
        urls = self._urls_dell_annuncio(r["risultati"][0]["slug"])
        self.assertEqual(len(urls), 1, "premessa: la foto non e' stata ri-ospitata: %s" % urls)
        con = sqlite3.connect(self.db_catalogo)
        try:
            padrone = con.execute("SELECT host_id FROM upload_proprietario WHERE nome = ?",
                                  (urls[0].rsplit("/", 1)[1],)).fetchall()
        finally:
            con.close()
        self.assertEqual(padrone, [(self.hidA,)])


class TestRiempimentoDelPadrone(unittest.TestCase):
    """La tabella nasce una volta sola, e quel giorno si riempie coi nomi gia' citati da UN SOLO
    host. Citati da due (una bozza-trucco fatta prima del deploy): nessuna riga, il padrone non
    si sceglie a caso. Un riavvio non cambia i dati."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.p = os.path.join(self.dir, "catalogo.db")

    def _righe(self):
        con = sqlite3.connect(self.p)
        try:
            return con.execute(
                "SELECT nome, host_id FROM upload_proprietario ORDER BY nome").fetchall()
        finally:
            con.close()

    def test_una_volta_sola_e_senza_scegliere_a_caso(self):
        from fase57_vetrina import Immagine, SchedaAlloggio, crea_catalogo

        def scheda(host, slug, stato="pubblicato"):
            return SchedaAlloggio(host_id=host, slug=slug, titolo="T", citta="Roma",
                                  prezzo_notte_cents=10000, capacita=2, stato=stato)

        cat = crea_catalogo(self.p)
        cat.pubblica(scheda("hB", "casa-b"), [Immagine("/uploads/b1.png", 0),
                                              Immagine("/uploads/amb.png", 1)])
        cat.pubblica(scheda("hA", "bozza-a", "bozza"), [Immagine("/uploads/AMB.png", 0)])
        # l'archivio com'e' in produzione PRIMA del deploy: senza la tabella
        con = sqlite3.connect(self.p)
        try:
            con.execute("DROP TABLE upload_proprietario")
            con.commit()
        finally:
            con.close()
        cat = crea_catalogo(self.p)
        self.assertEqual(self._righe(), [("b1.png", "hB")])
        # dopo la nascita una citazione nuova NON diventa proprieta' al riavvio
        cat.pubblica(scheda("hA", "bozza-a2", "bozza"), [Immagine("/uploads/b2.png", 0)])
        cat = crea_catalogo(self.p)
        self.assertEqual(self._righe(), [("b1.png", "hB")])
        self.assertTrue(cat.upload_cancellabile_da("b1.png", "hB", in_chat=False))
        self.assertFalse(cat.upload_cancellabile_da("b1.png", "hA", in_chat=False))
        # il conteso non ha padrone: non lo cancella nessuno dei due pretendenti
        self.assertFalse(cat.upload_cancellabile_da("amb.png", "hA", in_chat=False))
        self.assertFalse(cat.upload_cancellabile_da("AMB.PNG", "hB", in_chat=False))
        # senza padrone e citato da un solo host: suo, finche' la chat non lo cita
        self.assertTrue(cat.upload_cancellabile_da("b2.png", "hA", in_chat=False))
        self.assertFalse(cat.upload_cancellabile_da("b2.png", "hA", in_chat=True))
        # chi dimentica di dire se la chat lo cita, nega
        self.assertFalse(cat.upload_cancellabile_da("b2.png", "hA"))


if __name__ == "__main__":
    unittest.main()
