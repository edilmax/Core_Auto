"""
RBAC ISOLAMENTO IN SCRITTURA cross-host (gap del micro-stepping Flow 5).

L'isolamento host era provato SOLO in LETTURA (metriche/export/calendario, vedi
test_host_metriche_isolamento). Qui si prova che host A NON puo' MODIFICARE i dati di
host B: cambiare disponibilita'/prezzi (sabotaggio: prezzo a 1 cent) o — la piu' grave —
ELIMINARE l'annuncio altrui. La guardia `_verifica_proprieta` esiste su ogni scrittura:
questi test la difendono (rossi se qualcuno la togliesse). Controllo positivo incluso:
A scrive il PROPRIO annuncio -> 200 (la guardia non blocca tutto = non compiacente).
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256


class TestRBACScritturaCrossHost(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        self.tokA = self._host("a@rbac.it", "casa-a")
        self.tokB = self._host("b@rbac.it", "casa-b")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _host(self, email, slug):
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": email, "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        tok = c["token"]
        self.g("POST", "/api/host/pubblica",
               {"slug": slug, "titolo": slug, "citta": "Roma", "prezzo_notte_cents": 50000,
                "capacita": 4, "politica_cancellazione": "flessibile"}, {"X-Host-Token": tok})
        return tok

    def _range(self, slug, prezzo):
        return {"alloggio_id": slug, "da": "2026-09-01", "a": "2026-09-10",
                "unita_totali": 1, "prezzo_netto_cents": prezzo}

    # --- SCRITTURA calendario/prezzi altrui: VIETATA ---
    def test_A_non_cambia_disponibilita_di_B(self):
        # A prova a sabotare il prezzo di B mettendolo a 1 cent
        s, m = self.g("POST", "/api/host/disponibilita_range", self._range("casa-b", 1),
                      {"X-Host-Token": self.tokA})
        self.assertEqual(s, 403, "IDOR SCRITTURA: A ha cambiato calendario/prezzo di B! %s" % m)

    # --- ELIMINAZIONE annuncio altrui: VIETATA (la piu' grave) ---
    def test_A_non_elimina_annuncio_di_B(self):
        s, m = self.g("POST", "/api/host/alloggio_elimina",
                      {"alloggio_id": "casa-b", "slug": "casa-b"}, {"X-Host-Token": self.tokA})
        self.assertEqual(s, 403, "IDOR: A ha ELIMINATO l'annuncio di B! %s" % m)
        # ...e l'annuncio di B deve esistere ancora
        self.assertIsNotNone(self.sys.catalogo.host_di_alloggio("casa-b"),
                             "l'annuncio di B e' sparito nonostante il 403")

    # --- CONTROLLO POSITIVO (non-compiacenza): A scrive il PROPRIO -> ok ---
    def test_A_cambia_il_PROPRIO_ok(self):
        s, m = self.g("POST", "/api/host/disponibilita_range", self._range("casa-a", 60000),
                      {"X-Host-Token": self.tokA})
        self.assertEqual(s, 200, m)


ICAL_MINIMO = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261201\r\n"
               "DTEND;VALUE=DATE:20261203\r\nEND:VEVENT\r\nEND:VCALENDAR")

# Le scritture dell'host che prendono il nome dell'annuncio DAL CORPO e passano dal
# controllo di proprieta'. Il corpo e' quello minimo che il prodotto accetta.
SCRITTURE_COL_NOME_NEL_CORPO = (
    ("/api/host/disponibilita", lambda s: {"alloggio_id": s, "giorno": "2026-12-01",
                                           "unita_totali": 1, "prezzo_netto_cents": 5000}),
    ("/api/host/disponibilita_range", lambda s: {"alloggio_id": s, "da": "2026-12-01",
                                                 "a": "2026-12-05", "unita_totali": 1,
                                                 "prezzo_netto_cents": 5000}),
    ("/api/host/ical", lambda s: {"alloggio_id": s, "ical": ICAL_MINIMO}),
    ("/api/host/alloggio_elimina", lambda s: {"slug": s}),
)


class TestUnaScritturaSuUnAnnuncioCHENONESISTE(unittest.TestCase):
    """⛔ D20 — scritta PRIMA della riparazione e vista ROSSA sul codice di produzione.

    LA FAMIGLIA, non l'esemplare: `_verifica_proprieta` risponde `owner is None or
    owner == hid`, quindi un nome che NON ESISTE passa il controllo e la scrittura riesce
    sotto un nome che nessuno possiede.

    Il caso vero (2026-09-15, misurato su nginx): il fondatore ha caricato due periodi alle
    18:41:48 e alle 18:42:03 per un annuncio che ha creato alle 18:42:13. Il pannello ha
    risposto «✅», i giorni non sono andati sull'annuncio nuovo — che e' rimasto «Non
    disponibile», con ogni preventivo a 409 — e nessuno gli ha detto perche'.
    ⛔ E il danno non e' solo la confusione di una sera: un host puo' riservarsi il
    calendario di un nome che un ALTRO host usera' domani, e quello se lo troverebbe addosso.

    ⛔ COSA NON ESAMINA (D18 punto 3): le rotte di LETTURA che passano dallo stesso controllo
    (prezzi, link iCal), e le scritture che prendono l'annuncio da una query invece che dal
    corpo. Il conteggio del secondo test grida se nascono chiamanti nuovi.
    """

    FANTASMA = "annuncio-che-non-esiste-mai-stato-creato"

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "solo@rbac.it", "password": "password1",
                       "accetta_termini": True, "accetta_clausole": True,
                       "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa-vera", "titolo": "Casa vera", "citta": "Roma",
                "prezzo_notte_cents": 50000, "capacita": 2}, {"X-Host-Token": self.tok})
        # PREMESSA (sbaglio S1): il nome fantasma non deve esistere davvero, se no la
        # guardia proverebbe un'altra cosa e passerebbe per il motivo sbagliato.
        self.assertIsNone(self.sys.catalogo.host_di_alloggio(self.FANTASMA))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def test_nessuna_scrittura_riesce_su_un_nome_che_non_esiste(self):
        riuscite = []
        for path, corpo in SCRITTURE_COL_NOME_NEL_CORPO:
            s, d = self.g("POST", path, corpo(self.FANTASMA), {"X-Host-Token": self.tok})
            if 200 <= s < 300:
                riuscite.append("%s -> %d %s" % (path, s, d))
        self.assertEqual(
            riuscite, [],
            "queste scritture sono RIUSCITE su un annuncio che non esiste: %s. Il pannello "
            "dice «fatto» e il lavoro non e' andato dove l'host crede; e il nome resta "
            "prenotato per chi lo usera' domani" % " · ".join(riuscite))

    def test_la_stessa_scrittura_sul_PROPRIO_annuncio_riesce(self):
        """Controllo positivo (non-compiacenza): la guardia sopra non deve poter passare
        perche' il prodotto rifiuta tutto."""
        s, d = self.g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": "casa-vera", "da": "2026-12-01", "a": "2026-12-05",
                       "unita_totali": 1, "prezzo_netto_cents": 5000},
                      {"X-Host-Token": self.tok})
        self.assertEqual(s, 200, d)

    def test_il_PERIMETRO_di_questa_guardia_non_si_restringe_in_SILENZIO(self):
        """Le rotte sopra sono quattro, ma i punti che chiamano il controllo di proprieta'
        sono di piu': se ne nasce uno nuovo, qualcuno deve guardarlo. Questo conto lo dice
        lo stesso giorno, invece di lasciarlo scoperto per mesi (METODO v4, 20.3)."""
        import fase83_server
        with open(fase83_server.__file__, encoding="utf-8") as f:
            sorgente = f.read()
        quanti = sorgente.count("self._verifica_proprieta(")
        self.assertEqual(
            quanti, 13,
            "i punti che chiamano `_verifica_proprieta` sono %d, non 13: e' nata (o sparita) "
            "una rotta. Guardala: se SCRIVE e prende il nome dal corpo, va aggiunta a "
            "SCRITTURE_COL_NOME_NEL_CORPO, se no aggiorna questo numero con il motivo" % quanti)


if __name__ == "__main__":
    unittest.main()
