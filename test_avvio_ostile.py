"""REVISIONE OSTILE dell'avvio — tesi da refutare: "il prodotto non parte mai aperto".

La tesi e' quasi vera: HOST_KEY/ADMIN_KEY assenti, vuote o col segnaposto pubblico, il
segreto HMAC corto, il percorso di archivio VUOTO — tutto gia' sorvegliato da
`test_avvio_failclosed.py` e da `test_avvio_e_ripristino.TestFailClosed`.

QUESTO file esiste per la combinazione che quelle guardie NON vedevano, trovata provando
l'avvio VERO una variabile per volta (2026-07-29):

    DB_FINANZA=:memory:      ->  il prodotto PARTIVA.

Perche' era grave, e perche' nessuno se ne accorgeva:
  · `:memory:` non e' vuoto, quindi la guardia sui percorsi vuoti lo lasciava passare;
  · il ciclo che crea le cartelle lo salta di proposito, quindi nessun file nasceva;
  · `/api/health/db` (fase83_server.py, `_salute_db`) SALTA i percorsi ":memory:" ->
    l'archivio scomparso non veniva nemmeno NOMINATO nella risposta, che restava
    `{"status": "ok"}`. MISURATO sul prodotto vivo: avviato con DB_FINANZA=:memory:,
    nella cartella dati non c'era `finanza.db` e la sonda rispondeva 200/"ok" senza la
    chiave `db_finanza`.
  · `:memory:` e' il valore che i test usano ovunque: e' il primo candidato a finire in
    un `.env` per copia-incolla.
Risultato: libro giornale immutabile, prove d'accettazione e crediti gia' spesi vivi
soltanto dentro il processo — spariti al riavvio, in perfetto silenzio. E' il modo di
rompersi n.1 (dati effimeri), gia' pagato due volte (recensioni e crediti in RAM: un
credito rispendibile dopo ogni deploy).

VISTO ROSSO: con `main_casavip.py` senza il blocco `_in_ram` queste prove falliscono
tutte (il processo parte e `servi` viene chiamato); ripristinato il blocco, sono verdi.
"""
from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

# Ambiente del processo figlio: LISTA BIANCA (niente chiavi vere dello sviluppatore,
# niente DB_* ereditati -> nessuna scrittura fuori dal temporaneo, nessuna rete).
VARIABILI_DI_SISTEMA = (
    "PATH", "SYSTEMROOT", "COMSPEC", "TEMP", "TMP", "WINDIR", "PATHEXT", "APPDATA",
    "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMDATA", "SYSTEMDRIVE", "USERPROFILE", "HOME",
    "LANG", "LC_ALL", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "OS", "LD_LIBRARY_PATH",
)


def _campi_db():
    from fase81_bootstrap_casavip import ConfigCasaVIP
    return sorted(c for c in vars(ConfigCasaVIP()) if c.startswith("db_"))


def _porta_libera():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    return porta


def _ambiente(cartella, porta, extra=None):
    env = {k: v for k, v in os.environ.items() if k.upper() in VARIABILI_DI_SISTEMA}
    env.update({
        "CASAVIP_SEGRETO": "ab" * 32,
        "HOST_KEY": "chiave-host-collaudo-ostile",
        "ADMIN_KEY": "chiave-admin-collaudo-ostile",
        "DATA_DIR": cartella,
        "HOST": "127.0.0.1",
        "PORTA": str(porta),
        "STATIC_DIR": "deploy",
        "MARCA_TEMPORALE": "0",          # niente marca RFC 3161 verso una TSA vera
        "GEOCODING": "false",            # niente rete
        "POI_OSM": "false",              # niente rete
        "PULIZIA_UPLOADS": "0",          # nessuna cancellazione di file
        "UPLOAD_DIR": os.path.join(cartella, "uploads"),
        "OUTREACH_OPTOUT_FILE": os.path.join(cartella, "outreach_optout.json"),
        "FILE_REFERRAL": os.path.join(cartella, "referral.json"),
        "CAMPAGNA_STATO_FILE": os.path.join(cartella, "campagna_stato.json"),
        "DOMANDA_ALLARME_FILE": os.path.join(cartella, "domanda_allarme.json"),
        "DOMANDA_SOGLIA": "1000000",
        "PYTHONIOENCODING": "utf-8",
    })
    for campo in _campi_db():
        env["DB_" + campo[3:].upper()] = os.path.join(cartella, campo[3:] + ".db")
    for chiave, valore in (extra or {}).items():
        if valore is None:
            env.pop(chiave, None)
        else:
            env[chiave] = valore
    return env


class _Esito(object):
    PARTITO = "PARTITO"
    BLOCCATO = "BLOCCATO"


def _avvia_e_osserva(cartella, extra, attesa=90.0):
    """Lancia il prodotto VERO (processo separato, come nel container) e dice com'e'
    finita: codice d'uscita, oppure PARTITO se ha aperto la porta e risponde."""
    porta = _porta_libera()
    log = os.path.join(cartella, "_avvio.log")
    with open(log, "wb") as flusso:
        proc = subprocess.Popen([PY, "main_casavip.py"], cwd=QUI,
                                env=_ambiente(cartella, porta, extra),
                                stdout=flusso, stderr=subprocess.STDOUT)
        try:
            scadenza = time.time() + attesa
            while time.time() < scadenza:
                uscita = proc.poll()
                if uscita is not None:
                    break
                try:
                    conn = http.client.HTTPConnection("127.0.0.1", porta, timeout=2)
                    try:
                        conn.request("GET", "/api/health/live")
                        if conn.getresponse().status == 200:
                            uscita = _Esito.PARTITO
                            break
                    finally:
                        conn.close()
                except (OSError, http.client.HTTPException):
                    pass
                time.sleep(0.05)
            else:                                          # pragma: no cover
                uscita = _Esito.BLOCCATO
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=25)
                except subprocess.TimeoutExpired:          # pragma: no cover
                    proc.kill()
                    proc.wait(timeout=25)
    with open(log, "rb") as f:
        return uscita, f.read().decode("utf-8", "replace")


# ═════════ 1. AVVIO VERO: un archivio in RAM non deve far partire niente ═════════
class TestArchivioInRamNonParte(unittest.TestCase):
    """Processo vero, ambiente vero, una sola variabile cambiata."""

    def _prova(self, variabile):
        cartella = tempfile.mkdtemp(prefix="ostile_ram_")
        self.addCleanup(shutil.rmtree, cartella, True)
        uscita, log = _avvia_e_osserva(cartella, {variabile: ":memory:"})
        self.assertEqual(
            uscita, 2,
            "con %s=:memory: il prodotto NON si e' rifiutato di partire (esito %r): "
            "l'archivio vivrebbe solo in RAM e sparirebbe al riavvio, senza un errore.\n%s"
            % (variabile, uscita, log[-1200:]))
        self.assertIn("RIFIUTO DI PARTIRE", log,
                      "si e' fermato senza dire perche':\n%s" % log[-1200:])
        self.assertIn(variabile, log,
                      "il motivo non nomina la variabile colpevole:\n%s" % log[-1200:])
        self.assertIn("IN MEMORIA", log,
                      "il motivo non dice che il guasto e' l'archivio in RAM:\n%s"
                      % log[-1200:])
        self.assertFalse(
            os.path.isfile(os.path.join(cartella, variabile[3:].lower() + ".db")),
            "l'archivio in RAM non crea nessun file: e' proprio questo il danno")

    def test_il_giornale_contabile_in_ram_non_parte(self):
        """DB_FINANZA=:memory: = libro giornale immutabile che si azzera a ogni riavvio."""
        self._prova("DB_FINANZA")

    def test_le_prove_daccettazione_in_ram_non_partono(self):
        """DB_ACCETTAZIONI=:memory: = prove firmate del contratto host (valore LEGALE)."""
        self._prova("DB_ACCETTAZIONI")

    def test_i_crediti_gia_spesi_in_ram_non_partono(self):
        """DB_CREDITO_USATI=:memory: = un credito rispendibile dopo ogni deploy (denaro)."""
        self._prova("DB_CREDITO_USATI")


# ═════════ 2. LA STESSA REGOLA, SU OGNI ARCHIVIO, SENZA APRIRE PORTE ═════════
class TestNessunArchivioPuoVivereInRam(unittest.TestCase):
    """In-processo e veloce: `main()` con i due collaboratori finali spiati.

    Osservabile FORTE: `servi` (il server HTTP) e `crea_sistema` NON devono essere mai
    chiamati. Non "non e' 200": proprio "il server non e' stato acceso".
    """

    def setUp(self):
        import logging
        import main_casavip
        self.main = main_casavip
        self.cartella = tempfile.mkdtemp(prefix="ostile_cfg_")
        self.addCleanup(shutil.rmtree, self.cartella, True)
        self._env = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._env)))
        os.environ.clear()
        os.environ.update({k: v for k, v in self._env.items()
                           if k.upper() in VARIABILI_DI_SISTEMA})
        os.environ.update(_ambiente(self.cartella, _porta_libera()))
        radice = logging.getLogger()
        vecchi = list(radice.handlers)

        def _ripulisci_log():
            # `main()` aggiunge un handler su FILE dentro la cartella temporanea: va
            # CHIUSO, altrimenti su Windows il file resta aperto e la cartella non si
            # cancella (e la suite si riempie di ResourceWarning).
            for h in list(radice.handlers):
                if h not in vecchi:
                    try:
                        h.close()
                    except Exception:               # pragma: no cover
                        pass
            radice.handlers[:] = vecchi

        self.ripulisci_log = _ripulisci_log     # va chiamata dopo OGNI main(): altrimenti
        self.addCleanup(_ripulisci_log)         # gli handler si accumulano e il log duplica
        self.chiamate = []
        self._veri = (main_casavip.crea_sistema, main_casavip.servi)
        self.addCleanup(setattr, main_casavip, "crea_sistema", self._veri[0])
        self.addCleanup(setattr, main_casavip, "servi", self._veri[1])
        class _SistemaFinto(object):
            report = "collaudo ostile: nessun sistema costruito"

        def _crea(cfg):
            self.chiamate.append("crea_sistema")
            return _SistemaFinto()

        main_casavip.crea_sistema = _crea
        main_casavip.servi = lambda *a, **k: self.chiamate.append("servi")

    def test_controllo_positivo_con_percorsi_veri_si_arriva_ad_accendere_il_server(self):
        """Senza questo, i rifiuti qui sotto potrebbero essere colpa dell'attrezzatura."""
        self.main.main()
        self.assertEqual(self.chiamate, ["crea_sistema", "servi"],
                         "l'ambiente completo non arriva ad accendere il server: le prove "
                         "qui sotto non proverebbero nulla")

    def test_ogni_singolo_archivio_in_ram_ferma_lavvio(self):
        """La lista viene dalla configurazione, non dalla memoria: un archivio nuovo
        aggiunto domani e' sorvegliato da subito, senza toccare questo file."""
        for campo in _campi_db():
            variabile = "DB_" + campo[3:].upper()
            with self.subTest(archivio=variabile):
                del self.chiamate[:]
                vecchio = os.environ[variabile]
                os.environ[variabile] = ":memory:"
                try:
                    with self.assertRaises(SystemExit) as ctx:
                        self.main.main()
                finally:
                    os.environ[variabile] = vecchio
                    self.ripulisci_log()
                self.assertEqual(ctx.exception.code, 2,
                                 "%s=:memory: -> uscita %r invece di 2"
                                 % (variabile, ctx.exception.code))
                self.assertEqual(self.chiamate, [],
                                 "%s=:memory: e il server e' stato acceso lo stesso (%s)"
                                 % (variabile, self.chiamate))

    def test_la_maiuscola_e_lo_spazio_non_sono_una_scappatoia(self):
        """`DB_FINANZA=' :memory: '` e' lo stesso guasto con un altro vestito."""
        for valore in (" :memory: ", "\t:memory:\n"):
            with self.subTest(valore=repr(valore)):
                del self.chiamate[:]
                vecchio = os.environ["DB_FINANZA"]
                os.environ["DB_FINANZA"] = valore
                try:
                    with self.assertRaises(SystemExit) as ctx:
                        self.main.main()
                finally:
                    os.environ["DB_FINANZA"] = vecchio
                    self.ripulisci_log()
                self.assertEqual(ctx.exception.code, 2)
                self.assertEqual(self.chiamate, [])

    def test_un_percorso_vero_che_contiene_la_parola_memory_resta_lecito(self):
        """Il rovescio della guardia: non deve diventare un divieto di scrivere
        'memory' in un percorso. `/data/memoria/finanza.db` e' un percorso vero."""
        del self.chiamate[:]
        vero = os.path.join(self.cartella, "in_memory_dir", "finanza.db")
        os.environ["DB_FINANZA"] = vero
        self.main.main()
        self.assertEqual(self.chiamate, ["crea_sistema", "servi"],
                         "un percorso VERO che contiene 'memory' e' stato rifiutato")
        self.assertTrue(os.path.isdir(os.path.dirname(vero)),
                        "la cartella del percorso vero non e' stata creata")


# ═════════ 3. LA SONDA CHE TACEVA (perche' la guardia sopra e' indispensabile) ═════════
class TestLaSondaDiSaluteSaltaGliArchiviInRam(unittest.TestCase):
    """Non un'ipotesi: il codice della sonda salta ':memory:' — quindi un archivio in RAM
    non comparirebbe NEMMENO come nome nella risposta, e lo stato resterebbe "ok".

    Finche' questa riga esiste, il fail-closed all'avvio e' l'unica cosa che separa la
    piattaforma da una perdita di dati silenziosa: se un giorno la sonda imparasse a
    DENUNCIARE gli archivi in RAM invece di saltarli, questa guardia va rivista (e questo
    test va aggiornato di proposito, non per caso).
    """

    def test_la_sonda_salta_i_percorsi_in_memoria(self):
        with open(os.path.join(QUI, "fase83_server.py"), encoding="utf-8") as f:
            sorgente = f.read()
        self.assertIn('perc == ":memory:"', sorgente,
                      "la sonda /api/health/db non salta piu' ':memory:': rivedi la "
                      "motivazione della guardia in main_casavip.py")

    def test_la_sonda_dichiara_ok_su_un_archivio_in_ram(self):
        """La prova del DANNO che la guardia evita, sul motore vero della sonda."""
        from fase81_bootstrap_casavip import ConfigCasaVIP
        from fase83_server import RouterHTTP
        cartella = tempfile.mkdtemp(prefix="ostile_sonda_")
        self.addCleanup(shutil.rmtree, cartella, True)
        valori = {campo: os.path.join(cartella, campo[3:] + ".db")
                  for campo in _campi_db()}
        valori["db_finanza"] = ":memory:"
        cfg = ConfigCasaVIP(**valori)      # la configurazione e' congelata: si costruisce

        class _Sistema(object):
            config = cfg
            attivo = True

        router = RouterHTTP.__new__(RouterHTTP)
        router._sys = _Sistema()
        ok, dettaglio = router._salute_db()
        self.assertTrue(ok, "la sonda si accorge dell'archivio in RAM? allora la "
                            "motivazione della guardia e' cambiata")
        self.assertNotIn("db_finanza", dettaglio,
                         "la sonda ora NOMINA l'archivio in RAM: aggiorna la guardia")
        self.assertIn("db_catalogo", dettaglio, "la sonda non guarda piu' niente")


if __name__ == "__main__":
    unittest.main(verbosity=2)
