"""GUARDIA — una chiave/token di autenticazione con caratteri NON-ASCII (emoji/unicode) deve dare
un rifiuto PULITO (401/403), MAI un 500 da `TypeError` di hmac.compare_digest.

Scovato dalla batteria estrema (collaudi/estremo.py, fuzzing endpoint): `hmac.compare_digest` su
str non-ASCII solleva 'comparing strings with non-ASCII characters is not supported' → l'errore era
isolato (500) ma un login sbagliato NON deve mai essere un 500. Fix: confronto sui byte UTF-8.
Vista ROSSA: sul codice pre-fix questi asserti trovano 500.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router


class TestAuthNonAscii(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        sis = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"k" * 32,
                                         db_payout=self.d + "/p.db"))
        self.r = crea_router(sis, host_key="hk", admin_key="ak", base_url="http://t")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _post(self, path, headers):
        return self.r.gestisci("POST", path, {}, json.dumps({"slug": "x", "titolo": "t",
                               "citta": "Roma", "prezzo_notte_cents": 10000, "capacita": 2}),
                               headers)

    def test_host_key_non_ascii_rifiuto_pulito(self):
        for chiave in ("😀🔥", "clé-héllo", "Ключ", "鍵", "\x00\x01"):
            st, _ = self._post("/api/host/pubblica", {"X-Host-Key": chiave})
            self.assertNotEqual(st, 500, "chiave host non-ASCII %r -> 500 (crash auth)" % chiave)
            self.assertIn(st, (401, 403, 429), "atteso rifiuto auth pulito, non %r" % st)

    def test_host_token_non_ascii_rifiuto_pulito(self):
        for tok in ("émoji😀", "токен", "￿￿"):
            st, _ = self._post("/api/host/pubblica", {"X-Host-Token": tok})
            self.assertNotEqual(st, 500, "token host non-ASCII %r -> 500" % tok)

    def test_admin_key_non_ascii_rifiuto_pulito(self):
        st, _ = self.r.gestisci("POST", "/api/admin/rimborso", {},
                                json.dumps({"riferimento": "x"}), {"X-Admin-Key": "🔑€ñ"})
        self.assertNotEqual(st, 500, "chiave admin non-ASCII -> 500")
        self.assertIn(st, (401, 403, 429, 400), "atteso rifiuto pulito, non %r" % st)

    def test_surrogato_isolato_non_crasha_auth(self):
        # SCOVATO da collaudi/gare_estreme.py (fuzzing): un SURROGATO Unicode isolato (\ud800, non
        # ASCII e nemmeno UTF-8 valido) faceva UnicodeEncodeError su .encode("utf-8") -> 500.
        # Copre TUTTE le verifiche firma con input utente: admin-key, host-token, cookie gate.
        # Fix: .encode("utf-8", "surrogatepass"). Vista ROSSA: pre-fix questi danno 500/eccezione.
        surrogati = ("\ud800", "ab\ud800cd", "\udfff\ud800", "x𝄞")  # anche coppia rotta
        for s in surrogati:
            st, _ = self.r.gestisci("POST", "/api/admin/rimborso", {},
                                    json.dumps({"riferimento": "x"}), {"X-Admin-Key": s})
            self.assertIn(st, (401, 403, 429, 400), "admin surrogato %r -> %r (atteso rifiuto)" % (s, st))
            st2, _ = self._post("/api/host/pubblica", {"X-Host-Token": s})
            self.assertNotEqual(st2, 500, "host-token surrogato %r -> 500" % s)
            # cookie gate: un surrogato nel cookie di sessione non deve schiantare il gatekeeper
            st3, _ = self.r.gestisci("GET", "/host.html", {}, None,
                                     {"Cookie": "bv_host=host|9999999999|" + s + "|deadbeef"})
            self.assertNotEqual(st3, 500, "cookie gate surrogato %r -> 500" % s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
