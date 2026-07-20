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
        for gg in ("2027-01-01","2027-01-02"):
            self.sys.inventario.imposta_disponibilita("sbagliato",gg,unita_totali=1,prezzo_netto_cents=9000)
        self.sys.inventario.blocca("sbagliato","2027-01-01","2027-01-03",idem_key="b",origine="t")
        s,d=self.g("POST","/api/host/alloggio_elimina",{"slug":"sbagliato"},{"X-Host-Token":self.tok})
        self.assertEqual(s,409,d)                     # mai clienti senza stanza
        self.assertIsNotNone(self.sys.catalogo.dettaglio_owner("sbagliato"))

if __name__=="__main__": unittest.main()
