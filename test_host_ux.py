"""
Test UX pannello host (semplificazione richiesta dal fondatore):
  - AUTO-ID: pubblicare SENZA slug -> il server genera uno slug pulito, numerato e UNIVOCO;
    due annunci con lo stesso titolo -> due slug diversi. L'host non digita mai un codice.
  - /api/host/alloggi ricavato dal TOKEN (niente host_id a mano) + espone l'id NUMERICO;
    il parametro host_id è ignorato (non puoi vedere gli alloggi altrui).
  - CANCELLA FOTO: caricata per sbaglio -> /api/host/foto_elimina la rimuove dal disco;
    path-safe (niente traversal), idempotente.
"""
import base64
import json
import os
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

SEG = b"S" * 32
PNG1x1 = base64.b64encode(
    bytes.fromhex("89504e470d0a1a0a0000000d494844520000000100000001010300000025db56"
                  "ca00000003504c5445000000a77a3dda0000000149444154789c6360000002"
                  "00010005000601a5f645000000004945" + "4e44ae426082")).decode()


class TestHostUX(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ["UPLOAD_DIR"] = os.path.join(self.dir, "uploads")
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, con_registrazione_host=True,
            db_catalogo=f"{self.dir}/c.db", db_inventario=f"{self.dir}/i.db",
            db_registro_host=f"{self.dir}/r.db", db_accettazioni=f"{self.dir}/acc.db"))
        self.r = crea_router(self.sys, host_key="operatore")
        self.h = {"X-Host-Token": self._registra("mario@bnb.it")}

    def tearDown(self):
        os.environ.pop("UPLOAD_DIR", None)
        shutil.rmtree(self.dir, ignore_errors=True)

    def _registra(self, email):
        s, c = self.r.gestisci("POST", "/api/host/registrazione", body=json.dumps(
            {"email": email, "password": "passwordlunga", "ragione_sociale": "B&B",
             "accetta_termini": True, "accetta_clausole": True,
             "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE}))
        self.assertEqual(s, 201, c)
        return c["token"]

    def _pubblica(self, **extra):
        corpo = {"titolo": "Casa a Roma", "citta": "Roma", "prezzo_notte_cents": 9500,
                 "capacita": 4}
        corpo.update(extra)
        return self.r.gestisci("POST", "/api/host/pubblica", headers=self.h,
                               body=json.dumps(corpo))

    # ── AUTO-ID ───────────────────────────────────────────────────────────────
    def test_pubblica_senza_slug_genera_slug(self):
        s, c = self._pubblica()                       # NESSUNO slug fornito
        self.assertEqual(s, 201, c)
        self.assertTrue(c["slug"], "slug non generato")
        self.assertRegex(c["slug"], r"^[a-z0-9-]+$")  # pulito (url-safe)
        self.assertIn("casa", c["slug"])              # derivato dal titolo
        self.assertIsInstance(c.get("id"), int)       # id numerico per l'admin

    def test_due_titoli_uguali_slug_diversi(self):
        s1, c1 = self._pubblica()
        s2, c2 = self._pubblica()                     # stesso titolo -> slug DIVERSO (numerato)
        self.assertEqual((s1, s2), (201, 201))
        self.assertNotEqual(c1["slug"], c2["slug"], "collisione di slug!")
        # due alloggi distinti sotto lo stesso host
        _, miei = self.r.gestisci("GET", "/api/host/alloggi", {}, headers=self.h)
        self.assertEqual(len(miei["alloggi"]), 2)
        self.assertEqual(len({a["id"] for a in miei["alloggi"]}), 2)   # id numerici distinti

    def test_slug_esplicito_rispettato(self):
        s, c = self._pubblica(slug="villa-mare")
        self.assertEqual(c["slug"], "villa-mare")     # se lo fornisce, si rispetta

    def test_alloggi_dal_token_espone_id(self):
        self._pubblica()
        _, miei = self.r.gestisci("GET", "/api/host/alloggi", {}, headers=self.h)
        self.assertEqual(len(miei["alloggi"]), 1)
        a = miei["alloggi"][0]
        self.assertIsInstance(a["id"], int)
        self.assertIn("slug", a); self.assertIn("titolo", a)
        self.assertEqual(a["valuta"], "EUR")          # default

    def test_valuta_locale_round_trip(self):
        # host prezza in THB -> l'elenco e il preventivo restano in THB (like-for-like)
        s, c = self._pubblica(valuta="THB", prezzo_notte_cents=350000)   # ฿3500
        self.assertEqual(s, 201, c)
        slug = c["slug"]
        _, miei = self.r.gestisci("GET", "/api/host/alloggi", {}, headers=self.h)
        a = next(x for x in miei["alloggi"] if x["slug"] == slug)
        self.assertEqual(a["valuta"], "THB")
        self.assertEqual(a["prezzo_notte_cents"], 350000)
        # apro disponibilità e chiedo un preventivo: la valuta dell'addebito è THB, non EUR
        for g in ("2026-09-01", "2026-09-02"):
            self.r.gestisci("POST", "/api/host/disponibilita", headers=self.h, body=json.dumps(
                {"alloggio_id": slug, "giorno": g, "unita_totali": 1,
                 "prezzo_netto_cents": 350000}))
        s, q = self.r.gestisci("POST", "/api/concierge/quote", body=json.dumps(
            {"alloggio_id": slug, "check_in": "2026-09-01", "check_out": "2026-09-02", "party": 2}))
        self.assertEqual(s, 200, q)
        self.assertEqual(q["valuta"], "THB")          # l'ospite paga in THB, non convertito a EUR

    # ── MODIFICA annuncio esistente (upsert, no duplicati) ────────────────────
    def test_dettaglio_owner_per_modifica(self):
        s, c = self._pubblica(valuta="EUR", prezzo_notte_cents=9500)
        slug = c["slug"]
        s, d = self.r.gestisci("GET", "/api/host/alloggio", {"slug": slug}, headers=self.h)
        self.assertEqual(s, 200, d)
        self.assertEqual(d["slug"], slug)
        self.assertEqual(d["prezzo_notte_cents"], 9500)
        self.assertIn("modalita_prenotazione", d)     # campi per pre-riempire il form
        # un altro host non può leggerne il dettaglio
        hL = {"X-Host-Token": self._registra("luigi@bnb.it")}
        s2, _ = self.r.gestisci("GET", "/api/host/alloggio", {"slug": slug}, headers=hL)
        self.assertEqual(s2, 403)
        # slug inesistente -> 404
        s3, _ = self.r.gestisci("GET", "/api/host/alloggio", {"slug": "non-esiste"}, headers=self.h)
        self.assertEqual(s3, 404)

    def test_modifica_aggiorna_stesso_id_no_duplicato(self):
        s, c = self._pubblica(titolo="Casa Uno", prezzo_notte_cents=9000)
        slug, id0 = c["slug"], c["id"]
        # ri-pubblico con LO STESSO slug (modifica) -> stesso id, dati aggiornati, 1 solo annuncio
        s, c2 = self._pubblica(slug=slug, titolo="Casa Uno Rinnovata", prezzo_notte_cents=12000)
        self.assertEqual(s, 201, c2)
        self.assertEqual(c2["id"], id0)               # stesso id, non un duplicato
        _, miei = self.r.gestisci("GET", "/api/host/alloggi", {}, headers=self.h)
        self.assertEqual(len(miei["alloggi"]), 1)
        a = miei["alloggi"][0]
        self.assertEqual(a["prezzo_notte_cents"], 12000)

    def test_pubblica_su_slug_altrui_bloccata_no_furto(self):
        s, c = self._pubblica(prezzo_notte_cents=9000)   # mario
        slug = c["slug"]
        # luigi prova a pubblicare SULLO STESSO slug -> 403 (niente furto/riassegnazione host)
        hL = {"X-Host-Token": self._registra("luigi@bnb.it")}
        s2, r = self.r.gestisci("POST", "/api/host/pubblica", headers=hL, body=json.dumps(
            {"slug": slug, "titolo": "RUBATO", "citta": "X", "prezzo_notte_cents": 1, "capacita": 1}))
        self.assertEqual(s2, 403, r)
        # l'annuncio è ancora di mario, invariato
        _, d = self.r.gestisci("GET", "/api/host/alloggio", {"slug": slug}, headers=self.h)
        self.assertEqual(d["prezzo_notte_cents"], 9000)

    # ── PROPRIETÀ: non puoi modificare l'alloggio di un ALTRO host ────────────
    def test_ownership_scrittura_altrui_bloccata(self):
        s, c = self._pubblica()
        slug = c["slug"]
        hL = {"X-Host-Token": self._registra("luigi@bnb.it")}     # secondo host
        casi = [
            ("/api/host/stato", {"slug": slug, "stato": "sospeso"}),
            ("/api/host/disponibilita", {"alloggio_id": slug, "giorno": "2026-09-01",
                                         "unita_totali": 1, "prezzo_netto_cents": 100}),
            ("/api/host/disponibilita_range", {"alloggio_id": slug, "da": "2026-09-01",
                                               "a": "2026-09-05", "unita_totali": 1,
                                               "prezzo_netto_cents": 100}),
            ("/api/host/ical", {"alloggio_id": slug,
                                "ical": "BEGIN:VCALENDAR\nEND:VCALENDAR"}),
        ]
        for path, corpo in casi:
            s, r = self.r.gestisci("POST", path, headers=hL, body=json.dumps(corpo))
            self.assertEqual(s, 403, f"{path} doveva essere 403 (non tuo), invece {s} {r}")
        # il proprietario invece SÌ
        s, r = self.r.gestisci("POST", "/api/host/stato", headers=self.h,
                               body=json.dumps({"slug": slug, "stato": "sospeso"}))
        self.assertEqual(s, 200, r)

    # ── IMPORT DAI COLOSSI (portability) ──────────────────────────────────────
    def test_import_booking_end_to_end(self):
        export = {"property_name": "Villa Sole", "city": "Roma", "base_rate": "120.00",
                  "currency": "EUR", "max_occupancy": 4, "property_id": "BK-999",
                  "photos": ["https://img/1.jpg"],
                  "availability": [{"date": "2026-09-01", "units": 1, "price": "120.00"}]}
        s, r = self.r.gestisci("POST", "/api/host/importa", headers=self.h,
                               body=json.dumps({"sorgente": "booking", "dati": export}))
        self.assertEqual(s, 200, r)
        self.assertEqual(r["importati"], 1)
        res = r["risultati"][0]
        self.assertTrue(res["ok"], res)
        # l'annuncio è sotto l'host del TOKEN (non l'host dell'export), con slug generato da noi
        _, miei = self.r.gestisci("GET", "/api/host/alloggi", {}, headers=self.h)
        a = next(x for x in miei["alloggi"] if x["slug"] == res["slug"])
        self.assertEqual(a["titolo"], "Villa Sole")
        self.assertEqual(a["prezzo_notte_cents"], 12000)
        self.assertNotEqual(a["slug"], "BK-999")           # slug nostro, non quello dell'export

    def test_import_valuta_locale_preservata(self):
        export = {"listing_title": "Bangkok Loft", "city": "Bangkok",
                  "nightly_price": "3500.00", "currency": "THB", "accommodates": 2}
        s, r = self.r.gestisci("POST", "/api/host/importa", headers=self.h,
                               body=json.dumps({"sorgente": "airbnb", "dati": export}))
        self.assertEqual(s, 200, r)
        slug = r["risultati"][0]["slug"]
        _, miei = self.r.gestisci("GET", "/api/host/alloggi", {}, headers=self.h)
        a = next(x for x in miei["alloggi"] if x["slug"] == slug)
        self.assertEqual(a["valuta"], "THB")               # valuta preservata
        self.assertEqual(a["prezzo_notte_cents"], 350000)

    def test_import_lista_multipla_e_auth(self):
        # senza auth -> 401
        s, _ = self.r.gestisci("POST", "/api/host/importa",
                               body=json.dumps({"dati": {}}))
        self.assertEqual(s, 401)
        # lista di 2 annunci canonici -> 2 importati
        lista = [
            {"titolo": "Uno", "citta": "Roma", "prezzo_notte": "80.00", "capacita": 2},
            {"titolo": "Due", "citta": "Milano", "prezzo_notte": "90.00", "capacita": 3},
        ]
        s, r = self.r.gestisci("POST", "/api/host/importa", headers=self.h,
                               body=json.dumps({"sorgente": "canonico", "dati": lista}))
        self.assertEqual(s, 200, r)
        self.assertEqual(r["importati"], 2)

    # ── CANCELLA FOTO ─────────────────────────────────────────────────────────
    def _carica_foto(self):
        s, c = self.r.gestisci("POST", "/api/host/upload_foto", headers=self.h,
                               body=json.dumps({"image_base64": PNG1x1}))
        self.assertEqual(s, 201, c)
        return c["url"]

    def test_foto_elimina_rimuove_file(self):
        url = self._carica_foto()
        nome = url.rsplit("/", 1)[-1]
        percorso = os.path.join(os.environ["UPLOAD_DIR"], nome)
        self.assertTrue(os.path.isfile(percorso))     # c'è
        s, c = self.r.gestisci("POST", "/api/host/foto_elimina", headers=self.h,
                               body=json.dumps({"url": url}))
        self.assertEqual(s, 200, c)
        self.assertTrue(c["eliminata"])
        self.assertFalse(os.path.isfile(percorso))    # sparito dal disco

    def test_foto_elimina_idempotente(self):
        url = self._carica_foto()
        self.r.gestisci("POST", "/api/host/foto_elimina", headers=self.h,
                        body=json.dumps({"url": url}))
        s, c = self.r.gestisci("POST", "/api/host/foto_elimina", headers=self.h,
                               body=json.dumps({"url": url}))
        self.assertEqual(s, 200)                       # ri-cancellare non è un errore

    def test_foto_elimina_path_traversal_bloccato(self):
        # crea un file "segreto" fuori dalla cartella upload
        segreto = os.path.join(self.dir, "segreto.txt")
        with open(segreto, "w") as f:
            f.write("dati")
        for cattivo in ("/uploads/../segreto.txt", "/uploads/../../etc/passwd",
                        "/etc/passwd", "../segreto.txt"):
            s, c = self.r.gestisci("POST", "/api/host/foto_elimina", headers=self.h,
                                   body=json.dumps({"url": cattivo}))
            self.assertIn(s, (200, 422))
        self.assertTrue(os.path.isfile(segreto), "traversal ha cancellato un file esterno!")

    def test_foto_elimina_richiede_auth(self):
        s, _ = self.r.gestisci("POST", "/api/host/foto_elimina",
                               body=json.dumps({"url": "/uploads/x.png"}))
        self.assertEqual(s, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
