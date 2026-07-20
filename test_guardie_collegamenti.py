"""GUARDIE AUTO-APPLICANTI sui COLLEGAMENTI (ispezione "libro" 2026-07-20).

Nate dall'audit pannelli+collegamenti: l'unico 404 vero del sito era una PROMESSA non
mantenuta (/llms.txt pubblicizzava /api/concierge/manifest, mai registrato). Queste guardie
rendono IMPOSSIBILE ricascarci:
  1. ogni url /api/... promesso da llms.txt risponde (mai 404 rotta_non_trovata);
  2. il manifest concierge esiste e OGNI passo che dichiara e' una rotta reale col metodo
     dichiarato;
  3. ogni chiave i18n usata da index.html (data-t / data-tph / data-ttitle / t('...'))
     esiste in ETICHETTE_UI;
  4. ETICHETTE_UI e' SIMMETRICO: ogni chiave ha ESATTAMENTE le stesse 8 lingue;
  5. ogni chiave mt('...') della mappa esiste in TUTTE le 8 righe-lingua di MAP_T
     (dizionario client dentro index.html).
"""
import datetime
import json
import os
import re
import shutil
import tempfile
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import ETICHETTE_UI, crea_router
from fase97_inbound_seo import llms_txt

_QUI = os.path.dirname(os.path.abspath(__file__))
_LINGUE = ("it", "en", "es", "fr", "de", "pt", "ja", "zh")


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://x/" + secrets.token_hex(5), "id": "cs_" + secrets.token_hex(5)}


class TestGuardieCollegamenti(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)
        cls.dir = d = tempfile.mkdtemp()
        os.environ["UPLOAD_DIR"] = f"{d}/uploads"
        cls.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_messaggi=f"{d}/m.db",
            db_garanzia=f"{d}/g.db", commissione_bps=1500, psp_bps=300,
            stripe_secret_key="sk", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        cls.r = crea_router(cls.sis, host_key="hk", admin_key="ak",
                            base_url="https://bookinvip.com")
        with open(os.path.join(_QUI, "deploy", "index.html"), encoding="utf-8") as f:
            cls.index = f.read()

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _non_404(self, metodo, path):
        st, out = self.r.gestisci(metodo, path, {}, "{}" if metodo == "POST" else None, {})
        self.assertFalse(st == 404 and isinstance(out, dict)
                         and out.get("errore") == "rotta_non_trovata",
                         "%s %s: ROTTA INESISTENTE (promessa non mantenuta)" % (metodo, path))

    def test_llms_txt_non_promette_rotte_inesistenti(self):
        testo = llms_txt("https://bookinvip.com")
        api = sorted(set(re.findall(r"https://bookinvip\.com(/api/[A-Za-z0-9_/\-]+)", testo)))
        self.assertTrue(api, "llms.txt senza url api: guardia vuota (cambiata la firma?)")
        for path in api:
            for metodo in ("GET", "POST"):
                st, out = self.r.gestisci(metodo, path, {},
                                          "{}" if metodo == "POST" else None, {})
                if not (st == 404 and isinstance(out, dict)
                        and out.get("errore") == "rotta_non_trovata"):
                    break
            else:
                self.fail("llms.txt promette %s ma NESSUN metodo la serve (404)" % path)

    def test_manifest_concierge_esiste_e_dice_la_verita(self):
        st, m = self.r.gestisci("GET", "/api/concierge/manifest", {}, None, {})
        self.assertEqual(st, 200, m)
        self.assertEqual(m.get("mcp"), "https://bookinvip.com/api/mcp")
        self.assertEqual(len(m.get("flusso", [])), 3)
        json.dumps(m)                                   # serializzabile senza sorprese
        for passo in m["flusso"]:
            self._non_404(passo["metodo"], passo["path"])
        self._non_404(m["catalogo"]["metodo"], m["catalogo"]["path"])
        self._non_404("POST", "/api/mcp")
        # il flusso dichiarato FUNZIONA davvero (quote->book con dati veri, non parole)
        tok = self._prepara_alloggio()
        st, q = self.r.gestisci("POST", "/api/concierge/quote", {}, json.dumps({
            "alloggio_id": "casa-guardia", "check_in": self._ci, "check_out": self._co,
            "party": 2}), {})
        self.assertEqual(st, 200, q)
        self.assertIn("quote_token", q)
        st, b = self.r.gestisci("POST", "/api/concierge/book", {}, json.dumps({
            "quote_token": q["quote_token"], "email": "agente@ai.it"}), {})
        self.assertEqual(st, 201, b)
        for campo in ("riferimento", "voucher_token"):
            self.assertIn(campo, b, "il manifest promette '%s' che book non ritorna" % campo)

    def _prepara_alloggio(self):
        from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
        st, c = self.r.gestisci("POST", "/api/host/registrazione", {}, json.dumps({
            "email": "g@cp.it", "password": "password1", "accetta_termini": True,
            "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
            "versione": CONTRATTO_HOST_VERSIONE}), {})
        self.assertEqual(st, 201, c)
        tk = {"X-Host-Token": c["token"]}
        oggi = datetime.date.today()
        self.r.gestisci("POST", "/api/host/pubblica", {}, json.dumps({
            "slug": "casa-guardia", "titolo": "Casa", "citta": "Roma",
            "prezzo_notte_cents": 20000, "capacita": 4}), tk)
        self.r.gestisci("POST", "/api/host/disponibilita_range", {}, json.dumps({
            "alloggio_id": "casa-guardia", "da": oggi.isoformat(),
            "a": (oggi + datetime.timedelta(days=20)).isoformat(),
            "unita_totali": 1, "prezzo_netto_cents": 20000}), tk)
        self._ci = (oggi + datetime.timedelta(days=3)).isoformat()
        self._co = (oggi + datetime.timedelta(days=5)).isoformat()
        return tk

    def test_chiavi_i18n_di_index_esistono_nel_dizionario(self):
        usate = set(re.findall(r'data-t(?:ph|title)?="([A-Za-z0-9_]+)"', self.index))
        usate |= set(re.findall(r"\bt\('([A-Za-z0-9_]+)'\)", self.index))
        usate.discard("")
        self.assertGreater(len(usate), 50, "guardia vuota: estrazione chiavi rotta?")
        mancanti = {k for k in usate if k not in ETICHETTE_UI}
        self.assertEqual(mancanti, set(),
                         "index.html usa chiavi i18n NON nel dizionario (il client "
                         "mostrerebbe il token grezzo): %r" % sorted(mancanti))

    def test_dizionario_simmetrico_8_lingue(self):
        for chiave, tab in ETICHETTE_UI.items():
            self.assertEqual(tuple(sorted(tab.keys())), tuple(sorted(_LINGUE)),
                             "chiave '%s': lingue %r invece delle 8 canoniche"
                             % (chiave, sorted(tab.keys())))
            for lingua in _LINGUE:
                v = tab[lingua]
                self.assertTrue(isinstance(v, str) and v.strip(),
                                "chiave '%s' lingua '%s': testo vuoto" % (chiave, lingua))

    def test_map_t_client_completo_8_lingue(self):
        m = re.search(r"const MAP_T=\{(.*?)\n\};", self.index, re.S)
        self.assertIsNotNone(m, "MAP_T non trovato in index.html (cambiato nome?)")
        righe = dict(re.findall(r"(?m)^\s*(\w+):\{(.*)\}", m.group(1)))
        self.assertEqual(tuple(sorted(righe.keys())), tuple(sorted(_LINGUE)),
                         "MAP_T: lingue %r invece delle 8 canoniche" % sorted(righe.keys()))
        usate = set(re.findall(r"\bmt\('([A-Za-z0-9_]+)'\)", self.index))
        self.assertGreater(len(usate), 5, "guardia vuota: nessuna chiamata mt()?")
        for k in usate:
            for lingua, corpo in righe.items():
                self.assertRegex(corpo, r"\b%s:" % re.escape(k),
                                 "MAP_T.%s senza la chiave '%s' usata da mt()" % (lingua, k))


if __name__ == "__main__":
    unittest.main()
