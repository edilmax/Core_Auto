"""Collaudo — chat cliente<->host dal VOUCHER (zero password) + PROVE FOTO nella conversazione
+ vista ARBITRO (admin). Strategia: un solo posto (thread fase113) per messaggi e prove."""
import json, shutil, tempfile, unittest
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase57_vetrina import SchedaAlloggio

PNG1 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

class TestChatControversia(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        import os
        os.environ["UPLOAD_DIR"] = self.d + "/up"
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S"*32,
            db_catalogo=f"{self.d}/c.db", db_inventario=f"{self.d}/i.db",
            db_messaggi=f"{self.d}/m.db"))
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak")
        self.sys.catalogo.pubblica(SchedaAlloggio(host_id="h1", slug="casa", titolo="Casa",
            citta="Roma", prezzo_notte_cents=10000, capacita=2))
        for g in ("2026-09-01","2026-09-02"):
            self.sys.inventario.imposta_disponibilita("casa", g, unita_totali=1, prezzo_netto_cents=10000)
        s,q=self.g("POST","/api/concierge/quote",{"alloggio_id":"casa","check_in":"2026-09-01","check_out":"2026-09-02","party":2})
        s,b=self.g("POST","/api/concierge/book",{"quote_token":q["quote_token"],"email":"c@x.it"})
        self.v=b["voucher_token"]; self.rif=b["riferimento"]
    def tearDown(self):
        import os; os.environ.pop("UPLOAD_DIR",None); shutil.rmtree(self.d, ignore_errors=True)
    def g(self,m,p,b=None,h=None,q=None):
        return self.r.gestisci(m,p,q or {}, json.dumps(b) if b is not None else None, h or {})
    def test_chat_e_prova_e_arbitro(self):
        # cliente scrive dal voucher
        s,_=self.g("POST","/api/voucher/messaggio",{"voucher_token":self.v,"testo":"La terrazza era chiusa"})
        self.assertEqual(s,201)
        # cliente carica una PROVA foto
        s,d=self.g("POST","/api/voucher/prova",{"voucher_token":self.v,"image_base64":PNG1})
        self.assertEqual(s,201,d); self.assertTrue(d["url"].startswith("/uploads/"))
        # cliente vede il thread
        s,t=self.g("GET","/api/voucher/messaggi",q={"voucher_token":self.v})
        self.assertEqual(s,200); testi=[m["testo"] for m in t["messaggi"]]
        self.assertEqual(len(testi),2); self.assertIn("terrazza",testi[0])
        self.assertIn("PROVA FOTO",testi[1])
        # ARBITRO (admin) vede la stessa conversazione con le prove
        s,a=self.g("GET","/api/admin/messaggi",h={"X-Admin-Key":"ak"},q={"riferimento":self.rif})
        self.assertEqual(s,200); self.assertEqual(len(a["messaggi"]),2)
        # senza chiave admin: 401; voucher finto: 400
        s,_=self.g("GET","/api/admin/messaggi",q={"riferimento":self.rif}); self.assertEqual(s,401)
        s,_=self.g("POST","/api/voucher/messaggio",{"voucher_token":"falso","testo":"x"}); self.assertEqual(s,400)
    def test_prova_invalida(self):
        s,_=self.g("POST","/api/voucher/prova",{"voucher_token":self.v,"image_base64":"non-base64!!"})
        self.assertEqual(s,422)

if __name__=="__main__": unittest.main()
