"""Collaudo RICERCA OPERATIVA unificata (Field, Incremento 7): /api/admin/search.

UNA barra per annunci (slug/titolo/città/ID, OGNI stato), host (id/email/nome) e
prenotazioni (riferimento a prefisso / email ospite). Paginata. FILTRO DI SICUREZZA
a whitelist: SOLO dati operativi — MAI dati fiscali (CF/P.IVA/IBAN), MAI log/hash/Bunker.
Invarianti:
  1. senza chiave admin -> 401; termine < 2 char -> 422;
  2. annunci trovati per titolo/città/ID anche se SOSPESI (il Field deve vederli);
  3. host trovati per email E per ragione sociale;
  4. prenotazioni per PREFISSO riferimento e per email ospite;
  5. nessun risultato -> totale 0 (la UI mostra "Nessun risultato trovato");
  6. wildcard dell'utente NEUTRALIZZATE ('%' non diventa "tutto");
  7. paginazione: 25 match -> 10+10+5, totale giusto su ogni pagina;
  8. SICUREZZA: nella risposta NON compaiono mai iban/codice_fiscale/partita_iva/hash.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

HK = {"X-Host-Key": "hk"}
AK = {"X-Admin-Key": "ak"}


class TestAdminSearch(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"s" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_pendenti=f"{d}/p.db"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        # host con nome parlante + dati FISCALI (che NON devono mai uscire dalla search)
        e = self.sis.registro_host.registra("mario@sole.it", "password12",
                                            accetta_termini=True,
                                            ragione_sociale="Villa Sole SRL")
        self.hid = e.host_id
        self.sis.registro_host.imposta_dati_fiscali(self.hid, {
            "codice_fiscale": "RSSMRA80A01H501U", "iban": "IT60X0542811101000000123456",
            "indirizzo_fiscale": "Via Segreta 1", "paese": "IT"})
        # annunci: uno pubblicato, uno SOSPESO
        for slug, tit in (("villa-mare", "Villa sul Mare"), ("baita-neve", "Baita Neve")):
            self.g("POST", "/api/host/pubblica", {"host_id": self.hid, "slug": slug,
                   "titolo": tit, "citta": "Rimini", "descrizione": "x",
                   "prezzo_notte_cents": 9000, "capacita": 2, "servizi": [],
                   "immagini": []}, HK)
        self.sis.catalogo.imposta_stato("baita-neve", "sospeso")
        # prenotazioni nel registro pendenti (una pagata, una in attesa)
        pp = self.sis.pagamenti_pendenti
        pp.registra("abc123def456", alloggio_id="villa-mare", check_in="2026-09-01",
                    check_out="2026-09-03", idem_key="k1", host_id=self.hid,
                    email="ospite@mare.it")
        pp.conferma("abc123def456")
        pp.registra("zzz999yyy888", alloggio_id="villa-mare", check_in="2026-10-01",
                    check_out="2026-10-02", idem_key="k2", host_id=self.hid,
                    email="altro@cliente.it")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None,
                               h or {})

    def cerca(self, q, page=None):
        qq = {"q": q}
        if page:
            qq["page"] = str(page)
        return self.g("GET", "/api/admin/search", None, AK, qq)

    def test_auth_e_termine_corto(self):
        s, _ = self.g("GET", "/api/admin/search", None, {}, {"q": "villa"})
        self.assertEqual(s, 401)
        s, c = self.cerca("v")
        self.assertEqual(s, 422)

    def test_annunci_per_titolo_citta_id_anche_sospesi(self):
        s, d = self.cerca("villa")
        self.assertEqual(s, 200, d)
        slugs = [a["slug"] for a in d["annunci"]]
        self.assertIn("villa-mare", slugs)
        s, d = self.cerca("baita")                       # SOSPESO: il Field lo vede
        self.assertIn("baita-neve", [a["slug"] for a in d["annunci"]])
        self.assertEqual(d["annunci"][0]["stato"], "sospeso")
        s, d = self.cerca("Rimini")                      # per città
        self.assertEqual(d["totali"]["annunci"], 2)
        aid = d["annunci"][0]["id"]
        s, d = self.cerca(str(aid))                      # per ID esatto
        self.assertIn(aid, [a["id"] for a in d["annunci"]])

    def test_host_per_email_e_nome(self):
        s, d = self.cerca("mario@sole.it")
        self.assertEqual([h["host_id"] for h in d["host"]], [self.hid])
        s, d = self.cerca("Villa Sole")
        self.assertEqual([h["host_id"] for h in d["host"]], [self.hid])

    def test_prenotazioni_per_riferimento_e_email(self):
        s, d = self.cerca("abc123")                      # prefisso riferimento
        self.assertEqual([p["riferimento"] for p in d["prenotazioni"]], ["abc123def456"])
        self.assertEqual(d["prenotazioni"][0]["stato"], "pagato")
        s, d = self.cerca("altro@cliente.it")            # email ospite
        self.assertEqual([p["riferimento"] for p in d["prenotazioni"]], ["zzz999yyy888"])

    def test_nessun_risultato(self):
        s, d = self.cerca("nonesiste-xyz")
        self.assertEqual(s, 200)
        self.assertEqual(d["totale"], 0)

    def test_wildcard_neutralizzate(self):
        s, d = self.cerca("%%")                          # NON deve diventare "tutto"
        self.assertEqual(d["totale"], 0)
        s, d = self.cerca("__")
        self.assertEqual(d["totale"], 0)

    def test_paginazione(self):
        for i in range(25):
            self.g("POST", "/api/host/pubblica", {"host_id": self.hid,
                   "slug": "casa-pag-%02d" % i, "titolo": "CasaPag %d" % i,
                   "citta": "Paginopoli", "descrizione": "x", "prezzo_notte_cents": 5000,
                   "capacita": 2, "servizi": [], "immagini": []}, HK)
        s, d = self.cerca("CasaPag", page=1)
        self.assertEqual(len(d["annunci"]), 10)
        self.assertEqual(d["totali"]["annunci"], 25)
        s, d2 = self.cerca("CasaPag", page=3)
        self.assertEqual(len(d2["annunci"]), 5)
        self.assertEqual(d2["totali"]["annunci"], 25)
        # pagine diverse = risultati diversi
        self.assertNotEqual({a["id"] for a in d["annunci"]},
                            {a["id"] for a in d2["annunci"]})

    def test_sicurezza_mai_dati_fiscali_o_bunker(self):
        # cerco proprio l'host che HA i dati fiscali: nella risposta non devono esserci
        s, d = self.cerca("Villa Sole")
        blob = json.dumps(d)
        for vietato in ("iban", "IT60X05428", "codice_fiscale", "RSSMRA80A01H501U",
                        "partita_iva", "indirizzo_fiscale", "Via Segreta",
                        "hash", "app.log", "bunker"):
            self.assertNotIn(vietato, blob, "campo VIETATO nella search: " + vietato)


if __name__ == "__main__":
    unittest.main()
