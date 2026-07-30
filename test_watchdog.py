"""Collaudo WATCHDOG / AUTO-DIAGNOSI (fase178) — il sistema nervoso.

Kimi-NTU: Testare (ogni guasto simulato fa scattare l'allarme giusto), Isolare (read-only,
nessun dato toccato), Verificare (verdetto deterministico), Scalare (soglie da config).
Invarianti:
  1. sistema SANO -> ok=True, zero allarmi;
  2. catena hash MANOMESSA -> allarme 'catena' critico (riga puntata);
  3. backup VECCHIO oltre soglia -> allarme 'backup'; ASSENTE -> critico;
  4. disco oltre soglia -> allarme 'disco' (critico >=95%);
  5. un DB atteso SPARITO -> allarme 'db_mancanti' critico;
  6. uptime ko -> allarme 'uptime' critico;
  7. l'endpoint admin /api/admin/diagnosi e' READ-ONLY (nessuna riga nuova da nessuna
     parte) e richiede auth.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest

import fase178_watchdog as wd
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase177_financial_controller import crea_financial_controller


class TestValutaPura(unittest.TestCase):
    def test_sano(self):
        r = wd.valuta({"uptime_ok": True, "catena": {"ok": True, "righe": 3},
                       "eta_backup_sec": 3600, "disco_pct": 40,
                       "db_presenti": ["finanza", "catalogo"]},
                      db_attesi=["finanza", "catalogo"])
        self.assertTrue(r["ok"])
        self.assertEqual(r["allarmi"], [])

    def test_uptime_ko(self):
        r = wd.valuta({"uptime_ok": False})
        self.assertFalse(r["ok"])
        self.assertEqual(r["allarmi"][0]["cod"], "uptime")
        self.assertEqual(r["allarmi"][0]["grav"], "critico")

    def test_catena_manomessa(self):
        r = wd.valuta({"catena": {"ok": False, "seq_rotta": 7}})
        cod = [a["cod"] for a in r["allarmi"]]
        self.assertIn("catena", cod)
        self.assertIn("7", [a["msg"] for a in r["allarmi"]][cod.index("catena")])

    def test_backup_vecchio_e_assente(self):
        r = wd.valuta({"eta_backup_sec": 20 * 3600}, max_eta_backup_sec=8 * 3600)
        self.assertEqual([a["cod"] for a in r["allarmi"]], ["backup"])
        self.assertEqual(r["allarmi"][0]["grav"], "avviso")
        r2 = wd.valuta({"eta_backup_sec": None})
        self.assertEqual(r2["allarmi"][0]["grav"], "critico")

    def test_disco(self):
        self.assertTrue(wd.valuta({"disco_pct": 84}, max_disco_pct=85)["ok"])
        self.assertEqual(wd.valuta({"disco_pct": 88}, max_disco_pct=85)["allarmi"][0]["grav"],
                         "avviso")
        self.assertEqual(wd.valuta({"disco_pct": 96}, max_disco_pct=85)["allarmi"][0]["grav"],
                         "critico")

    def test_db_mancanti(self):
        r = wd.valuta({"db_presenti": ["catalogo"]}, db_attesi=["catalogo", "finanza"])
        self.assertEqual(r["allarmi"][0]["cod"], "db_mancanti")
        self.assertIn("finanza", r["allarmi"][0]["msg"])


class TestVerificheReali(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_catena_file_ok_e_manomessa(self):
        db = os.path.join(self.dir, "finanza.db")
        fc = crea_financial_controller(db)
        fc.inizializza_schema()
        for i in range(3):
            fc.emetti_nota(tipo="debito", riferimento="R%d" % i, soggetto="host:h",
                           importo_cents=1000 + i, valuta="EUR", causale="t", emittente="a")
        self.assertTrue(wd.verifica_catena_file(db)["ok"])
        # manomissione (drop trigger + update)
        con = sqlite3.connect(db)
        con.execute("DROP TRIGGER lg_no_update")
        with con:
            con.execute("UPDATE libro_giornale SET importo_cents=9 WHERE seq=2")
        con.close()
        r = wd.verifica_catena_file(db)
        self.assertFalse(r["ok"])
        self.assertEqual(r["seq_rotta"], 2)

    def test_catena_file_assente_o_vuoto(self):
        self.assertTrue(wd.verifica_catena_file(os.path.join(self.dir, "non_c_e.db"))["ok"])

    def test_eta_backup(self):
        bkp = os.path.join(self.dir, "backup")
        os.makedirs(bkp)
        self.assertIsNone(wd.eta_backup_sec(bkp))
        f = os.path.join(bkp, "catalogo-x.db.gz")
        open(f, "w").close()
        vecchio = int(time.time()) - 20 * 3600
        os.utime(f, (vecchio, vecchio))
        self.assertGreaterEqual(wd.eta_backup_sec(bkp), 19 * 3600)

    def test_diagnosi_read_only_su_disco(self):
        # una diagnosi non deve creare nulla nella cartella dati
        prima = set(os.listdir(self.dir))
        wd.diagnosi(dir_dati=self.dir, dir_backup=os.path.join(self.dir, "b"),
                    uptime_ok=True)
        self.assertEqual(set(os.listdir(self.dir)), prima)


class TestEndpointDiagnosi(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"h" * 32, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_finanza=f"{d}/finanza.db"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, h=None):
        return self.r.gestisci("GET", "/api/admin/diagnosi", {}, None, h or {})

    def test_auth_e_read_only(self):
        s, _ = self.g()
        self.assertEqual(s, 401)                          # senza chiave admin
        s, _ = self.g({"X-Admin-Key": "sbagliata"})
        self.assertEqual(s, 401)
        # con chiave: risponde e NON scrive nel giornale
        mv_prima = self.sis.finanza.movimenti("qualsiasi")
        s, rep = self.g({"X-Admin-Key": "ak"})
        self.assertEqual(s, 200)
        self.assertIn("ok", rep)
        self.assertIn("allarmi", rep)
        self.assertEqual(self.sis.finanza.verifica_catena()["ok"], True)
        self.assertEqual(len(self.sis.finanza.movimenti("qualsiasi")), len(mv_prima))

    def test_data_dir_vuota_usa_fallback(self):
        """BUG scovato al collaudo live Incr.10/11: nel container DATA_DIR esiste ma
        VUOTA -> environ.get(..., default) ritorna '' (il default scatta solo se la
        chiave MANCA) -> diagnosi su cartelle inesistenti ('0 db' con /data pieno).
        Col fix l'endpoint usa il fallback di _data_dir() (dirname di DB_FINANZA)."""
        import os
        prima_dd = os.environ.get("DATA_DIR")
        prima_fin = os.environ.get("DB_FINANZA")
        os.environ["DATA_DIR"] = ""                      # esattamente il caso prod
        os.environ["DB_FINANZA"] = f"{self.dir}/finanza.db"
        try:
            s, rep = self.g({"X-Admin-Key": "ak"})
            self.assertEqual(s, 200)
            # la cartella del DB finanza contiene i .db del setUp: DEVE vederli
            self.assertGreaterEqual(len(rep["misure"]["db_presenti"]), 1)
        finally:
            for k, v in (("DATA_DIR", prima_dd), ("DB_FINANZA", prima_fin)):
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class TestCanaleDiAllarmeNonPuoEssereMUTO(unittest.TestCase):
    """IL WATCHDOG DEVE ACCORGERSI SE L'ALLARME NON PARTE.

    Il modulo puro (fase178) e' collaudato sopra, ma NESSUNO leggeva lo script che
    CONSEGNA l'allarme -- e li' c'era il buco: `curl` senza `-f` esce con codice 0 anche
    quando il server risponde 401/404. PROVATO SUL CAMPO il 2026-07-30:
        curl -sS  ...token_inventato...  -> uscita 0   (la shell crede sia andata bene)
        curl -sSf ...token_inventato...  -> uscita 22  (fallimento visto)
    Con la forma senza `-f`, il ramo `|| log "invio Telegram fallito"` NON scattava MAI:
    se il token veniva revocato o ruotato, gli allarmi smettevano di partire e non lo
    scopriva nessuno. Un guardiano che grida in un telefono staccato non serve a niente --
    e da oggi il Guardiano (fase186) sa anche dire quando e' cieco, quindi la sua voce
    deve arrivare.

    Nota di metodo: qui NON si controlla che la stringa "-f" esista "da qualche parte"
    nel file (errore gia' commesso in questo progetto con `server_tokens`, dove il
    controllo passava mentre uno dei due blocchi nginx era scoperto). Si isola la
    funzione `telegram()` e si guarda IL SUO curl.
    """

    SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy", "watchdog.sh")

    def _corpo_funzione(self, nome):
        """Estrae il corpo di `nome(){ ... }` dallo script (fino alla graffa in colonna 0)."""
        with open(self.SCRIPT, encoding="utf-8", errors="replace") as f:
            righe = f.read().split("\n")
        dentro, corpo = False, []
        for r in righe:
            if not dentro and r.startswith(nome + "(){"):
                dentro = True
                continue
            if dentro:
                if r.startswith("}"):
                    break
                corpo.append(r)
        self.assertTrue(corpo, "funzione %s() non trovata in %s" % (nome, self.SCRIPT))
        return "\n".join(corpo)

    def test_il_curl_che_manda_l_allarme_FALLISCE_sugli_errori_HTTP(self):
        corpo = self._corpo_funzione("telegram")
        self.assertIn("curl", corpo, "telegram() non usa curl?! %r" % corpo)
        # -f (o --fail) e' l'unica cosa che rende il codice d'uscita affidabile
        self.assertTrue(("-f " in corpo) or ("--fail" in corpo) or ("-sSf" in corpo)
                        or ("-fsS" in corpo),
                        "il curl che consegna l'allarme non ha -f: con un token revocato "
                        "esce 0, il ramo di errore non scatta e restiamo senza allarmi "
                        "SENZA SAPERLO.\n%s" % corpo)

    def test_e_il_fallimento_dell_invio_viene_registrato(self):
        """Accorgersene non basta: dev'esserci il ramo che lo scrive."""
        corpo = self._corpo_funzione("telegram")
        self.assertIn("||", corpo, "manca il ramo di errore sull'invio: %s" % corpo)
        self.assertIn("log ", corpo, "il fallimento dell'invio non viene registrato: %s" % corpo)


if __name__ == "__main__":
    unittest.main()
