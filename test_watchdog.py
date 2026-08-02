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


class TestWatchdogTrediciBuchiTrovatiDallaMutazione(unittest.TestCase):
    """⛔ TREDICI BUCHI VERI NEL GUARDIANO (mutazione, 2026-08-02).

    Campagna su tutti e 27 i punti di `fase178_watchdog`: 14 uccisi, 13 sopravvissuti --
    quasi meta' del modulo scoperto. Un solo file di prove (questo), usato tutto dalla
    campagna: nessuna scorciatoia, sono buchi reali.

    E' il modulo piu' delicato di tutti in un senso preciso: **se sbaglia lui, tutto il
    resto diventa cieco**. Non gestisce dati, dice se qualcosa e' rotto -- e un guardiano
    che si sbaglia o tace e' peggio di nessun guardiano, perche' ci si fida.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    # ── IL DIFETTO CAPITALE DI UN GUARDIANO ─────────────────────────────────────────
    def test_un_giornale_ILLEGGIBILE_non_e_un_giornale_integro(self):
        """⛔ IL PEGGIORE DEI TREDICI.

            except sqlite3.Error:
                return {"ok": False, "errore": "apertura_fallita"}

        Con `ok: True` il guardiano risponde **«catena integra»** quando non e' nemmeno
        riuscito ad APRIRE il libro dei soldi. Dichiara sano cio' che non ha potuto
        guardare -- ed e' lo strumento su cui contano tutti gli altri per accorgersene.

        Le tre situazioni vanno tenute DISTINTE, e sono tre risposte diverse:
          · file che non c'e'          -> ok, «assente» (installazione nuova: nessun allarme)
          · tabella non ancora creata  -> ok, «assente» (idem)
          · file che NON SI APRE       -> **NON ok**, «apertura_fallita» (qualcosa non va)
        Confonderle significa o gridare al lupo a ogni avvio, o tacere mentre il libro
        e' irraggiungibile.
        """
        # 1) file assente -> ok, e lo dice
        r = wd.verifica_catena_file(os.path.join(self.dir, "non-esiste.db"))
        self.assertTrue(r["ok"], "un file che non c'e' viene scambiato per una manomissione: "
                                 "falso allarme a ogni installazione nuova")
        self.assertTrue(r.get("assente"))

        # 2) file che esiste ma NON e' un database -> NON ok
        rotto = os.path.join(self.dir, "rotto.db")
        with open(rotto, "wb") as f:
            f.write(b"questo non e' un database sqlite" * 50)
        r2 = wd.verifica_catena_file(rotto)
        self.assertFalse(r2.get("assente"), "un file illeggibile marcato come «assente»")
        self.assertFalse(r2["ok"],
                         "il guardiano dichiara la catena INTEGRA su un libro che non "
                         "riesce nemmeno ad aprire: %r" % (r2,))

        # 3) database vero ma senza la tabella -> ok, «assente»
        vuoto = os.path.join(self.dir, "vuoto.db")
        con = sqlite3.connect(vuoto)
        con.execute("CREATE TABLE altro (x INTEGER)")
        con.commit()
        con.close()
        r3 = wd.verifica_catena_file(vuoto)
        self.assertTrue(r3["ok"], "un database senza ancora il giornale fa gridare il "
                                  "guardiano: falso allarme al primo avvio")
        self.assertTrue(r3.get("assente"))

    def test_un_libro_che_non_si_APRE_e_uno_che_non_si_LEGGE_sono_guasti(self):
        """Gli altri due rami di guasto, quelli che quasi non si raggiungono mai -- e
        proprio per questo non erano provati da nessuno.

          · `connect` che fallisce: succede davvero se al posto del file c'e' una CARTELLA
            (o mancano i permessi). Deve dire NON ok, non «assente»;
          · la tabella C'E' in elenco ma la lettura fallisce: non e' un'installazione
            nuova, e' un guasto -- e va detto.

        Sono i due rami che, se rispondessero «ok», renderebbero il guardiano cieco proprio
        nei casi in cui serve.
        """
        # (a) al posto del file c'e' una cartella -> connect fallisce
        cartella = os.path.join(self.dir, "sono_una_cartella.db")
        os.makedirs(cartella)
        r = wd.verifica_catena_file(cartella)
        self.assertFalse(r["ok"], "un libro che non si apre viene dichiarato integro: %r" % (r,))
        self.assertFalse(r.get("assente"), "scambiato per «assente»: %r" % (r,))

        # (b) la tabella c'e', ma leggerla fallisce -> guasto, non installazione nuova
        vero = os.path.join(self.dir, "finanza.db")
        con = sqlite3.connect(vero)
        con.execute("CREATE TABLE libro_giornale (seq INTEGER)")
        con.commit()
        con.close()
        import fase178_watchdog as modulo
        vero_connect = modulo.sqlite3.connect

        class _ConnCheRompeLaLettura:
            def __init__(self, c):
                self._c = c
                self.row_factory = None

            def execute(self, sql, *a):
                if "libro_giornale" in sql:
                    raise sqlite3.DatabaseError("database disk image is malformed")
                return self._c.execute(sql, *a)

            def close(self):
                self._c.close()

        modulo.sqlite3.connect = lambda p, **k: _ConnCheRompeLaLettura(vero_connect(p, **k))
        try:
            r2 = wd.verifica_catena_file(vero)
        finally:
            modulo.sqlite3.connect = vero_connect
        self.assertFalse(r2["ok"],
                         "la tabella c'e' ma non si legge, e il guardiano dice che va "
                         "tutto bene: %r" % (r2,))
        self.assertFalse(r2.get("assente"),
                         "un guasto di lettura scambiato per installazione nuova: %r" % (r2,))

    # ── LE SOGLIE, ALL'ISTANTE ESATTO ───────────────────────────────────────────────
    def test_le_soglie_scattano_al_punto_GIUSTO(self):
        """Tre confini, e ognuno cambia il verdetto solo NEL PUNTO ESATTO:

          · backup vecchio ESATTAMENTE quanto la soglia -> ancora buono (`>` stretto);
          · disco ESATTAMENTE alla soglia               -> allarme (`>=`);
          · disco ESATTAMENTE al 95%                    -> **critico**, non «avviso».

        Il terzo non e' un dettaglio: «avviso» e «critico» finiscono in due posti diversi
        (il critico sveglia la gente). Un disco pieno significa che SQLite smette di
        scrivere, cioe' il sito fermo: e' il caso in cui la differenza fra i due livelli
        vale davvero qualcosa.
        """
        SOGLIA_ETA, SOGLIA_DISCO = 8 * 3600, 85

        def codici(misure):
            r = wd.valuta(misure, max_eta_backup_sec=SOGLIA_ETA, max_disco_pct=SOGLIA_DISCO)
            return {a["cod"]: a["grav"] for a in r["allarmi"]}

        # backup: esattamente alla soglia = ancora buono; un secondo oltre = avviso
        self.assertNotIn("backup", codici({"eta_backup_sec": SOGLIA_ETA}),
                         "un backup vecchio esattamente quanto la soglia fa gia' scattare "
                         "l'allarme: si grida un secondo troppo presto, ogni volta")
        self.assertIn("backup", codici({"eta_backup_sec": SOGLIA_ETA + 1}))

        # disco: esattamente alla soglia = allarme (un punto sotto, no)
        self.assertNotIn("disco", codici({"disco_pct": SOGLIA_DISCO - 1}))
        self.assertIn("disco", codici({"disco_pct": SOGLIA_DISCO}),
                      "il disco ha raggiunto la soglia e il guardiano tace")

        # gravita': esattamente 95 = critico
        self.assertEqual("avviso", codici({"disco_pct": 94})["disco"])
        self.assertEqual("critico", codici({"disco_pct": 95})["disco"],
                         "al 95% esatto l'allarme e' declassato ad «avviso»: quello e' il "
                         "livello che sveglia qualcuno, e non scatta")
        self.assertEqual("critico", codici({"disco_pct": 99})["disco"])

    # ── LA RIGA DI COMANDO: e' cosi' che il guardiano parla al mondo ────────────────
    def _cli(self, *argomenti):
        """Esegue il modulo come lo esegue il bash del server, e legge il suo JSON."""
        import io
        import json as _json
        import runpy
        import sys
        vecchio_argv, vecchio_out = sys.argv, sys.stdout
        cattura = io.StringIO()
        sys.argv = ["fase178_watchdog.py", "--dati", self.dir, "--backup", self.dir] + \
                   list(argomenti)
        sys.stdout = cattura
        codice = 0
        try:
            runpy.run_path("fase178_watchdog.py", run_name="__main__")
        except SystemExit as e:
            codice = e.code
        finally:
            sys.argv, sys.stdout = vecchio_argv, vecchio_out
        testo = cattura.getvalue().strip()
        try:
            return codice, _json.loads(testo)
        except Exception:
            self.fail("il guardiano non ha stampato un JSON leggibile: %r" % (testo[:300],))

    def test_la_riga_di_comando_riporta_l_uptime_come_gli_e_stato_detto(self):
        """`up = True if a.uptime == "ok" else False if a.uptime == "ko" else None`

        Quattro guasti diversi su una riga sola, e tutti e quattro rovesciano il verdetto
        sull'UPTIME -- che e' l'unica cosa che il guardiano non puo' misurare da solo (un
        processo non puo' dire «sono morto»: glielo dice il controllo esterno). Se questa
        riga sbaglia, un sito GIU' viene riportato come su, o viceversa.

        Si prova attraverso la riga di comando vera, che e' come il bash del server lo
        interroga: provarlo sulla funzione interna non proverebbe questa riga.
        """
        _, ko = self._cli("--uptime", "ko")
        self.assertIn("uptime", [a["cod"] for a in ko["allarmi"]],
                      "detto «sito GIU'», il guardiano non se ne lamenta: %r" % (ko,))
        self.assertFalse(ko["ok"])

        _, ok = self._cli("--uptime", "ok")
        self.assertNotIn("uptime", [a["cod"] for a in ok["allarmi"]],
                         "detto «sito su», il guardiano grida lo stesso: falso allarme "
                         "a ogni giro (%r)" % (ok,))

        _, salta = self._cli("--uptime", "skip")
        self.assertNotIn("uptime", [a["cod"] for a in salta["allarmi"]],
                         "senza informazione sull'uptime il guardiano se la inventa")

    def test_il_codice_di_uscita_dice_la_verita_al_bash(self):
        """Il bash del server guarda il codice d'uscita, non il testo: 0 = tutto bene,
        1 = qualcosa non va. Se quello mente, l'allarme non parte mai -- o parte sempre."""
        codice_ko, _ = self._cli("--uptime", "ko")
        self.assertEqual(1, codice_ko, "sito dichiarato GIU' e il guardiano esce 0: "
                                       "nessun allarme partira' mai")
        codice_ok, r = self._cli("--uptime", "ok")
        self.assertEqual(0 if r["ok"] else 1, codice_ok,
                         "il codice d'uscita non corrisponde al verdetto: %r" % (r,))


if __name__ == "__main__":
    unittest.main()
