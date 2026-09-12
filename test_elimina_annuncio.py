"""Collaudo — l'host ELIMINA un annuncio sbagliato (doppia conferma in UI). Sicuro: solo il
proprietario; bloccato se ci sono prenotazioni future (mai clienti senza stanza)."""
import json, shutil, tempfile, unittest
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

class TestElimina(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S"*32, con_registrazione_host=True,
            db_catalogo=f"{self.d}/c.db", db_inventario=f"{self.d}/i.db",
            db_registro_host=f"{self.d}/r.db", db_accettazioni=f"{self.d}/a.db"))
        self.r = crea_router(self.sys, host_key="hk")
        self.tok = self._reg("h@del.it")
        self.g("POST","/api/host/pubblica",{"slug":"sbagliato","titolo":"Oops","citta":"Roma",
               "prezzo_notte_cents":9000,"capacita":2},{"X-Host-Token":self.tok})
    def tearDown(self): shutil.rmtree(self.d, ignore_errors=True)
    def g(self,m,p,b=None,h=None,q=None):
        return self.r.gestisci(m,p,q or {}, json.dumps(b) if b is not None else None, h or {})
    def _reg(self,email):
        s,c=self.g("POST","/api/host/registrazione",{"email":email,"password":"password1",
                   "accetta_termini":True,"accetta_clausole":True,"accetta_privacy":True,"doc_sha256":doc_sha256(),
                   "versione":CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s,201,c); return c["token"]
    def test_elimina_ok(self):
        s,d=self.g("POST","/api/host/alloggio_elimina",{"slug":"sbagliato"},{"X-Host-Token":self.tok})
        self.assertEqual(s,200,d)
        self.assertIsNone(self.sys.catalogo.dettaglio_owner("sbagliato"))
        s,_=self.g("POST","/api/host/alloggio_elimina",{"slug":"sbagliato"},{"X-Host-Token":self.tok})
        self.assertEqual(s,404)                       # idempotente onesto
    def test_non_tuo_e_auth(self):
        altro=self._reg("h2@del.it")
        s,_=self.g("POST","/api/host/alloggio_elimina",{"slug":"sbagliato"},{"X-Host-Token":altro})
        self.assertEqual(s,403)
        s,_=self.g("POST","/api/host/alloggio_elimina",{"slug":"sbagliato"})
        self.assertEqual(s,401)
    def test_bloccato_con_prenotazioni_future(self):
        # ⛔ «FUTURE» sta nel NOME del test, quindi si scrive «fra N giorni». Con le date
        # cablate (2027-01-01/03) sarebbe diventato rosso da solo il **2027-01-04**:
        # quelle prenotazioni avrebbero smesso di essere future e l'annuncio si sarebbe
        # potuto cancellare, cioe' il test avrebbe smesso di sorvegliare «mai clienti
        # senza stanza» senza che nessuno se ne accorgesse. Misurato il 2026-08-13.
        import datetime
        fra = lambda n: (datetime.date.today() + datetime.timedelta(days=n)).isoformat()
        for gg in (fra(30), fra(31)):
            self.sys.inventario.imposta_disponibilita("sbagliato",gg,unita_totali=1,prezzo_netto_cents=9000)
        self.sys.inventario.blocca("sbagliato",fra(30),fra(32),idem_key="b",origine="t")
        s,d=self.g("POST","/api/host/alloggio_elimina",{"slug":"sbagliato"},{"X-Host-Token":self.tok})
        self.assertEqual(s,409,d)                     # mai clienti senza stanza
        self.assertIsNotNone(self.sys.catalogo.dettaglio_owner("sbagliato"))


class TestUnAnnuncioCANCELLATOSPARISCEDAVVERO(unittest.TestCase):
    """⛔ D20 — scritta PRIMA della riparazione e vista ROSSA sul codice di produzione.

    Misura l'EFFETTO, non la forma. Non cerca la parola `secure_delete` nel sorgente — che
    una riga di registro basta a soddisfare (misurato: 3 moduli su 7 sono «scudati» da un
    `logger.warning` che nomina il pragma) — ma apre l'archivio e guarda se il dato c'e'
    ancora. E' la famiglia «cancellazione incompleta» del METODO v4 PARTE 13, gia'
    dichiarata chiusa e tornata: allora il controllo era debole, e si rinforza quello.

    I due difetti VIVI che ha scoperto, misurati il 2026-09-12 su efc5b2c:
      · `elimina_alloggio` (fase57:791) toglie la riga ma NON azzera i byte: l'indirizzo di
        casa dell'host — «PRIVATO: solo per geocodifica precisa, mai pubblico» (fase57:126)
        — resta leggibile nel file. La sorella `cancella_alloggi_host` ha il pragma alla
        riga 821 e sullo stesso banco non lascia niente: la differenza e' quella riga;
      · `cancella_alloggi_host` (fase57:825), cioe' proprio il «cancellami» che
        `fase156_erasure` chiama, confronta `alloggio_id` (un NUMERO, come dichiara
        fase57:942 con `i.alloggio_id = a.id`) con `slug` (un TESTO): la condizione non e'
        mai vera e le FOTO restano in archivio, vive e interrogabili — non nascoste nei
        byte. E l'esame dell'oblio resta VERDE, perche' quella riga non porta l'host_id.
    """

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S"*32, con_registrazione_host=True,
            db_catalogo=f"{self.d}/c.db", db_inventario=f"{self.d}/i.db",
            db_registro_host=f"{self.d}/r.db", db_accettazioni=f"{self.d}/a.db"))
        self.r = crea_router(self.sys, host_key="hk")
        s, c = self.g("POST", "/api/host/registrazione", {
            "email": "h@byte.it", "password": "password1", "accetta_termini": True,
            "accetta_clausole": True, "accetta_privacy": True,
            "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]

    def tearDown(self): shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _nei_byte(self, ago):
        """Quante volte l'ago si rilegge nei BYTE dell'archivio, WAL compreso. Un `DELETE`
        di SQLite marca lo spazio come riutilizzabile e lascia il contenuto nelle pagine
        libere: la riga non si interroga piu' e il testo si legge con un editor esadecimale."""
        import glob
        n = 0
        for f in sorted(glob.glob(f"{self.d}/c.db*")):
            with open(f, "rb") as fh:
                n += fh.read().count(ago.encode("utf-8"))
        return n

    def _righe_immagine(self, url):
        import sqlite3
        con = sqlite3.connect(f"{self.d}/c.db")
        try:
            return con.execute(
                "SELECT COUNT(*) FROM alloggio_immagini WHERE url=?", (url,)).fetchone()[0]
        finally:
            con.close()

    def test_l_INDIRIZZO_di_casa_non_si_rilegge_dai_byte_dopo_l_eliminazione(self):
        spia = "via-SPIA-DELLE-PROVE-ZZZZ"        # niente cifre di fila: verrebbero mascherate
        s, d = self.g("POST", "/api/host/pubblica",
                      {"slug": "casa-byte", "titolo": "Oops", "citta": "Roma",
                       "prezzo_notte_cents": 9000, "capacita": 2, "indirizzo": spia},
                      {"X-Host-Token": self.tok})
        self.assertIn(s, (200, 201), d)
        # PREMESSA (sbaglio S1: il vuoto non e' un valore). Se l'indirizzo non fosse nei byte
        # nemmeno PRIMA, «non c'e' dopo» non dimostrerebbe niente: sarebbe assente in tutti
        # e due i tempi, cioe' un verde che non ha guardato.
        self.assertGreater(self._nei_byte(spia), 0,
                           "misura non valida: l'indirizzo non e' mai arrivato nell'archivio")
        s, d = self.g("POST", "/api/host/alloggio_elimina", {"slug": "casa-byte"},
                      {"X-Host-Token": self.tok})
        self.assertEqual(s, 200, d)
        self.assertIsNone(self.sys.catalogo.dettaglio_owner("casa-byte"))
        self.assertEqual(
            self._nei_byte(spia), 0,
            "l'host ha cancellato il suo annuncio e l'indirizzo di casa sua si rilegge "
            "ancora nei byte di c.db: la riga non si interroga piu', il dato c'e'")

    def test_il_CANCELLAMI_toglie_anche_le_FOTO_dell_annuncio(self):
        from fase57_vetrina import Immagine, SchedaAlloggio
        foto = "https://esempio.test/foto-SPIA-OBLIO.jpg"
        hid = self.sys.registro_host.host_id_da_email("h@byte.it") \
            if hasattr(self.sys.registro_host, "host_id_da_email") else "host-oblio"
        self.sys.catalogo.pubblica(
            SchedaAlloggio(host_id=hid, slug="casa-foto", titolo="Con foto", citta="Roma",
                           prezzo_notte_cents=9000, capacita=2),
            (Immagine(url=foto, ordine=0, alt="a"),))
        self.assertEqual(self._righe_immagine(foto), 1,
                         "misura non valida: la foto non e' mai entrata in archivio")
        self.sys.catalogo.cancella_alloggi_host(hid)
        self.assertEqual(self.sys.catalogo.conta_alloggi_host(hid), 0,
                         "premessa: l'alloggio doveva sparire")
        self.assertEqual(
            self._righe_immagine(foto), 0,
            "il «cancellami» dichiara «CANCELLAZIONE TOTALE annunci+immagini» e la riga "
            "della foto e' ancora in archivio, viva e interrogabile")


if __name__=="__main__": unittest.main()
