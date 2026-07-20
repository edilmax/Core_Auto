"""
COLLAUDO ISOLAMENTO MULTI-HOST (richiesta fondatore: "nessuna interferenza tra host e host
con pannelli diversi e registrazioni diverse", simulato piu' volte).

Molti host si registrano DA SOLI (token self-service distinti), pubblicano i propri annunci,
aprono date. Poi OGNI host, col PROPRIO token, ATTACCA tutti gli endpoint del pannello puntando
alla roba di un ALTRO host (leggere, sovrascrivere, sospendere, cancellare, incassi, calendario,
metriche, chat, SEO, export CSV) — anche col trucco di passare l'host_id altrui in query.

INVARIANTI FERREI (devono reggere OGNI giro):
  - un host NON legge MAI dati di un altro (annunci, prenotazioni, payout, metriche, chat, SEO);
  - un host NON modifica MAI la roba di un altro (pubblica/sovrascrivi/stato/cancella/date);
  - col token presente vince SEMPRE il token: passare host_id altrui in query NON scavalca;
  - le liste "i miei ..." contengono SOLO roba propria;
  - dopo la tempesta, ogni annuncio ha ancora il SUO proprietario e i SUOI dati (niente furti).
"""
import json
import random
import shutil
import tempfile
import threading
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE


class TestIsolamentoMultiHost(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{self.d}/c.db", db_inventario=f"{self.d}/i.db",
            db_registro_host=f"{self.d}/r.db", db_accettazioni=f"{self.d}/a.db",
            db_pendenti=f"{self.d}/p.db"))
        self.r = crea_router(self.sys, host_key="operatore")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    # -- registra un host self-service, ritorna (host_id, token, headers, slug pubblicato) --
    def _crea_host(self, n, tag=""):
        email = "host%s-%d@test.it" % (tag, n)
        body = {"email": email, "password": "password%d!" % n, "accetta_termini": True,
                "accetta_clausole": True, "accetta_privacy": True, "ragione_sociale": "Casa %d" % n,
                "doc_sha256": doc_sha256(), "lang": "it"}
        s, out = self.g("POST", "/api/host/registrazione", body)
        self.assertEqual(s, 201, "registrazione host %d fallita: %r" % (n, out))
        hid, token = out["host_id"], out["token"]
        H = {"X-Host-Token": token}
        slug = "casa-host-%s-%d" % (tag, n)
        s, _ = self.g("POST", "/api/host/pubblica", {
            "titolo": "Villa di %d" % n, "citta": "Roma", "prezzo_notte_cents": 10000 + n,
            "capacita": 2, "slug": slug}, H)
        self.assertEqual(s, 201)
        # date proprie (il campo del motore e' 'alloggio_id')
        for giorno in ("2026-09-01", "2026-09-02"):
            s, _ = self.g("POST", "/api/host/disponibilita",
                          {"alloggio_id": slug, "giorno": giorno, "unita_totali": 1,
                           "prezzo_netto_cents": 10000}, H)
            self.assertEqual(s, 200, "setup date host %d fallito: %d" % (n, s))
        return {"n": n, "hid": hid, "token": token, "H": H, "slug": slug, "email": email}

    def _attacca(self, ladro, vittima):
        """ladro (col SUO token) prova a leggere/toccare la roba di vittima. Ritorna la lista
        delle VIOLAZIONI trovate (vuota = isolamento OK)."""
        v = []
        Hl = ladro["H"]
        vs = vittima["slug"]
        vh = vittima["hid"]

        # 1) LETTURE mirate all'annuncio altrui -> 403/404, MAI 200 coi dati
        for path in ("/api/host/alloggio", "/api/host/calendario_prezzi",
                     "/api/host/metriche", "/api/host/export", "/api/host/seo_report"):
            q = {"slug": vs, "alloggio": vs, "alloggio_id": vs, "da": "2026-09-01",
                 "a": "2026-09-02"}
            s, out = self.g("GET", path, None, Hl, q)
            if s == 200 and isinstance(out, dict) and (
                    "Villa di %d" % vittima["n"] in json.dumps(out, ensure_ascii=False)):
                v.append("%s: ladro legge annuncio di vittima (200 coi dati)" % path)

        # 1b) calendario altrui
        s, out = self.g("GET", "/api/host/calendario", None, Hl,
                        {"alloggio": vs, "da": "2026-09-01", "a": "2026-09-02"})
        if s == 200 and out.get("giorni") and any(
                x.get("stato") != "non_caricato" for x in out["giorni"]):
            v.append("calendario: ladro vede le date REALI di vittima")

        # 2) trucco host_id ALTRUI in query (col proprio token): il token deve vincere
        for path in ("/api/host/alloggi", "/api/host/prenotazioni", "/api/host/payout",
                     "/api/host/metriche_avanzate"):
            s, out = self.g("GET", path, None, Hl, {"host_id": vh})
            blob = json.dumps(out, ensure_ascii=False) if isinstance(out, (dict, list)) else ""
            if vs in blob or ("Villa di %d" % vittima["n"]) in blob:
                v.append("%s: host_id altrui in query -> dati di vittima trapelati" % path)

        # 3) SCRITTURE sulla roba altrui -> devono fallire (403 non_tuo)
        s, _ = self.g("POST", "/api/host/pubblica",
                      {"titolo": "RUBATO", "citta": "Rubata", "prezzo_notte_cents": 1,
                       "capacita": 9, "slug": vs}, Hl)
        if s == 201:
            v.append("pubblica: ladro ha SOVRASCRITTO l'annuncio di vittima")
        s, _ = self.g("POST", "/api/host/disponibilita",
                      {"alloggio_id": vs, "giorno": "2026-09-01", "unita_totali": 0,
                       "prezzo_netto_cents": 1}, Hl)
        if s not in (401, 403):
            v.append("disponibilita: ladro scrive sulle date di vittima (status %d)" % s)
        s, _ = self.g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": vs, "da": "2026-09-01", "a": "2026-09-30",
                       "unita_totali": 0, "prezzo_netto_cents": 1}, Hl)
        if s not in (401, 403):
            v.append("disponibilita_range: ladro chiude le date di vittima (status %d)" % s)

        # PROVA POSITIVA: dopo tutti gli attacchi le notti della vittima sono INTATTE
        # (il ladro tentava di CHIUDERLE a unita_totali=0 e sfondarle a 30 giorni).
        cal = self.sys.inventario.calendario(vs, "2026-09-01", "2026-09-03")
        caricati = [x for x in cal if x.get("stato") != "non_caricato"]
        if len(caricati) < 2:
            v.append("notti di vittima SPARITE dopo gli attacchi: %r" % cal)
        if any(x.get("unita_totali") != 1 for x in caricati):
            v.append("notti di vittima ALTERATE (unita != 1): %r" % caricati)

        return v

    def _verifica_integrita(self, hosts):
        """Dopo la tempesta: ogni annuncio ha ancora il SUO proprietario e il SUO titolo."""
        v = []
        for x in hosts:
            owner = self.sys.catalogo.host_di_alloggio(x["slug"])
            if owner != x["hid"]:
                v.append("furto proprieta': %s ora e' di %r (era %s)" % (x["slug"], owner, x["hid"]))
            det = self.sys.catalogo.dettaglio_owner(x["slug"]) or {}
            if det.get("titolo") != "Villa di %d" % x["n"]:
                v.append("dato alterato: %s titolo=%r" % (x["slug"], det.get("titolo")))
            # ognuno vede SOLO i propri alloggi
            s, out = self.g("GET", "/api/host/alloggi", None, x["H"])
            slugs = [a.get("slug") for a in (out.get("alloggi") or [])]
            estranei = [sl for sl in slugs if sl != x["slug"]]
            if estranei:
                v.append("host %d vede alloggi altrui nella sua lista: %r" % (x["n"], estranei))
        return v

    def _un_giro(self, n_host, seed):
        rnd = random.Random(seed)
        hosts = [self._crea_host(i, tag="s%d" % seed) for i in range(n_host)]
        violazioni = []
        # ogni host attacca alcuni altri, in ordine casuale
        for ladro in hosts:
            for vittima in rnd.sample(hosts, k=len(hosts)):
                if vittima["hid"] == ladro["hid"]:
                    continue
                violazioni += self._attacca(ladro, vittima)
        violazioni += self._verifica_integrita(hosts)
        return violazioni

    def test_isolamento_ripetuto(self):
        """10 giri (seed diversi) x 6 host che si attaccano a vicenda: 0 violazioni."""
        for seed in range(1, 11):
            with self.subTest(seed=seed):
                viol = self._un_giro(6, seed)
                self.assertEqual(viol, [], "seed %d: %d violazioni: %r"
                                 % (seed, len(viol), viol[:6]))

    def test_isolamento_concorrente(self):
        """Gli host attaccano IN PARALLELO (thread): l'isolamento regge sotto carico."""
        hosts = [self._crea_host(i, tag="par") for i in range(6)]
        risultati, errori = [], []
        lock = threading.Lock()

        def worker(ladro):
            try:
                for vittima in hosts:
                    if vittima["hid"] == ladro["hid"]:
                        continue
                    v = self._attacca(ladro, vittima)
                    if v:
                        with lock:
                            risultati.extend(v)
            except Exception as e:                       # un crash sotto carico = bocciato
                with lock:
                    errori.append(repr(e))

        th = [threading.Thread(target=worker, args=(h,)) for h in hosts]
        for t in th:
            t.start()
        for t in th:
            t.join(timeout=60)
        self.assertEqual(errori, [], "eccezioni sotto carico: %r" % errori[:5])
        self.assertEqual(risultati, [], "violazioni concorrenti: %r" % risultati[:6])
        self.assertEqual(self._verifica_integrita(hosts), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
