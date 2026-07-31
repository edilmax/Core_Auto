"""Test collaudo — l'avvio DEVE fallire CHIUSO se mancano le chiavi d'accesso.

MINA TROVATA in collaudo 2026-07-15 (non era una falla attiva: in prod le chiavi ci sono e
l'ho verificato live — tutti gli endpoint host/admin rispondono 401 — ma era un default
PERICOLOSO):
  `RouterHTTP._auth_host` ha un ramo comodo per lo sviluppo:
      if self._host_key is None: return True      # passa CHIUNQUE
  e gli endpoint host ripiegano su `query['host_id']` quando non c'e' un token:
      host_id = self._host_id_da_token(headers) or query.get("host_id")
  Combinati: se HOST_KEY sparisce dall'ambiente (server nuovo, typo, .env resettato) l'API
  host diventa APERTA A TUTTI -> `/api/host/payout?host_id=<tizio>` restituirebbe payout,
  prenotazioni e dati personali di QUALSIASI host. Un fail-OPEN silenzioso: peggio del sito giu'.

FIX al confine del deploy (`main_casavip.py`), non nel router: cosi' i test che usano
`crea_router()` in modalita' sviluppo restano invariati, ma un DEPLOY senza chiavi non parte.
"""
from __future__ import annotations

import os
import unittest


class TestAvvioFailClosed(unittest.TestCase):

    def setUp(self):
        self._orig = dict(os.environ)
        os.environ["CASAVIP_SEGRETO"] = "00112233445566778899aabbccddeeff"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig)

    def _avvia(self):
        import importlib
        import main_casavip
        importlib.reload(main_casavip)
        return main_casavip.main()

    def test_senza_host_key_non_parte(self):
        """Meglio non partire che partire spalancati."""
        os.environ.pop("HOST_KEY", None)
        os.environ["ADMIN_KEY"] = "x"
        with self.assertRaises(SystemExit) as ctx:
            self._avvia()
        self.assertEqual(ctx.exception.code, 2)

    def test_senza_admin_key_non_parte(self):
        os.environ["HOST_KEY"] = "x"
        os.environ.pop("ADMIN_KEY", None)
        with self.assertRaises(SystemExit) as ctx:
            self._avvia()
        self.assertEqual(ctx.exception.code, 2)

    def test_chiave_vuota_vale_come_mancante(self):
        """HOST_KEY='' non deve valere: `or None` la trasformerebbe in dev-open."""
        os.environ["HOST_KEY"] = ""
        os.environ["ADMIN_KEY"] = "x"
        with self.assertRaises(SystemExit):
            self._avvia()

    def test_il_ramo_dev_open_esiste_ancora_nel_router(self):
        """Se un domani il router diventasse fail-closed da solo, questa guardia va rivista.

        Documenta PERCHE' la guardia sta in main e non nel router: i test usano crea_router()
        senza chiavi e si appoggiano al ramo dev-open.
        """
        import io
        with io.open("fase83_server.py", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("if self._host_key is None:", src,
                      "il router non ha piu' il ramo dev-open: la guardia in main va rivalutata")


class _BaseAvvio(unittest.TestCase):
    """Ambiente SANO di partenza: ogni prova rompe UNA cosa sola (un bug per test)."""

    SANO = {
        "HOST_KEY": "chiave-host-vera-di-prova",
        "ADMIN_KEY": "chiave-admin-vera-di-prova",
        "CASAVIP_SEGRETO": "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff",
    }

    def setUp(self):
        self._orig = dict(os.environ)
        for k in list(os.environ):
            if k.startswith("DB_"):
                del os.environ[k]
        os.environ.update(self.SANO)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig)

    def _main(self):
        import importlib
        import main_casavip
        importlib.reload(main_casavip)
        return main_casavip

    def _rifiuta(self, atteso_nel_messaggio):
        """Pretende SystemExit(2) E che il messaggio nomini il colpevole.

        Il codice d'uscita da solo non basta: `raise SystemExit(2)` senza dire QUALE
        variabile e' malata costringe chi rimette in piedi il server a indovinare.

        ⚠️ RETE DI SICUREZZA (imparata sul campo il 2026-07-31, provando queste guardie
        rosse): se un domani il cancello sparisce, `main()` NON solleva piu' nulla — arriva
        a `servi()` e il test resta APPESO PER SEMPRE dentro un server in ascolto. Un test
        inchiodato e' peggio di un test rosso: non dice niente e blocca la suite. Qui
        `crea_sistema` viene sostituito da una sentinella, cosi' il caso «il cancello non
        c'e' piu'» diventa un rosso immediato e leggibile.
        """
        m = self._main()
        sentinella = RuntimeError("IL CANCELLO NON HA FERMATO NIENTE: l'avvio e' arrivato "
                                  "a costruire il sistema invece di rifiutare")

        def _mai(_cfg):
            raise sentinella

        m.crea_sistema = _mai
        with self.assertLogs(level="CRITICAL") as reg:
            with self.assertRaises(SystemExit) as ctx:
                m.main()
        self.assertEqual(ctx.exception.code, 2)
        testo = "\n".join(reg.output)
        self.assertIn("RIFIUTO DI PARTIRE", testo)
        self.assertIn(atteso_nel_messaggio, testo,
                      "l'avvio rifiuta ma NON nomina il colpevole (%r): chi ripara alle 3 di "
                      "notte non sa cosa toccare. Messaggio: %s" % (atteso_nel_messaggio, testo))


class TestSegretoDiFirmaDebole(_BaseAvvio):
    """La chiave HMAC firma voucher, gettoni host, cookie di sessione e crediti.

    DIFETTO PROVATO VIVO il 2026-07-31 sul codice di allora (`main_casavip._segreto`):
      · `CASAVIP_SEGRETO=cambiami_64_caratteri_hex` (il segnaposto di `.env.casavip.example`,
        che sta PUBBLICO su GitHub) -> chiave = b'cambiami_64_caratteri_hex'. La piattaforma
        firmata con una password stampata sul giornale.
      · `CASAVIP_SEGRETO=x` (refuso, variabile troncata) -> il ramo `except ValueError`
        faceva `.ljust(16, b"0")` -> chiave = b'x000000000000000'. Indovinabile in un secondo.
    In tutti e due i casi NON compariva un solo errore nei log: il sito partiva spalancato.
    """

    def test_il_segnaposto_pubblico_non_puo_diventare_la_chiave(self):
        os.environ["CASAVIP_SEGRETO"] = "cambiami_64_caratteri_hex"
        self._rifiuta("segnaposto")

    def test_una_chiave_corta_non_viene_riempita_di_zeri(self):
        os.environ["CASAVIP_SEGRETO"] = "x"
        self._rifiuta("troppo corto")

    def test_il_CONFINE_dei_16_byte_e_accettato(self):
        """IL BUCO TROVATO DAL GENERATORE DI MUTANTI il 2026-07-31.

        La soglia e' `len(b) >= 16`. Il mutante che la stringe a `> 16` e' SOPRAVVISSUTO:
        nessun test asserisce che una chiave di ESATTAMENTE 16 byte sia accettata. Il caso
        conta perche' 16 byte e' proprio il valore di serie che usano i test e le guide --
        cioe' il piu' probabile in un `.env` scritto a mano. Con la soglia stretta il
        prodotto si rifiuterebbe di partire su una chiave legittima: un falso allarme che
        blocca il deploy.

        Perche' nessuno se ne accorgeva: i test piu' vecchi asseriscono solo il CODICE
        d'uscita 2, e col mutante l'uscita restava 2 -- ma per il cancello sbagliato.
        Codice giusto, ragione sbagliata: e' la firma di una guardia che non guarda.
        """
        os.environ["CASAVIP_SEGRETO"] = "00112233445566778899aabbccddeeff"   # 16 byte esatti
        chiave = self._main()._segreto()
        self.assertEqual(16, len(chiave),
                         "una chiave di 16 byte esatti deve essere ACCETTATA cosi' com'e'")

    def test_un_byte_SOTTO_il_confine_viene_rifiutato(self):
        """L'altra direzione del confine: 15 byte non bastano."""
        os.environ["CASAVIP_SEGRETO"] = "0011223344556677889900112233"      # 14 byte
        self._rifiuta("troppo corto")

    def test_una_frase_segreta_LUNGA_resta_lecita(self):
        """Non e' un test di comodo: dimostra che il rifiuto guarda la FORZA, non il formato.
        Una passphrase non esadecimale di 16+ byte e' legittima e deve passare."""
        os.environ["CASAVIP_SEGRETO"] = "questa-e-una-frase-segreta-lunga-e-non-esadecimale"
        chiave = self._main()._segreto()
        self.assertGreaterEqual(len(chiave), 16)

    def test_senza_segreto_il_ripiego_e_CASUALE_mai_una_costante(self):
        """Assente resta lecito (comodita' di sviluppo) ma due avvii non devono MAI
        produrre la stessa chiave: un ripiego costante sarebbe la stessa falla."""
        os.environ.pop("CASAVIP_SEGRETO", None)
        m = self._main()
        self.assertNotEqual(m._segreto(), m._segreto(),
                            "il ripiego senza CASAVIP_SEGRETO e' una COSTANTE: sarebbe una "
                            "chiave nota a chiunque legga il codice")


class TestArchiviEffimeri(_BaseAvvio):
    """DIFETTO PROVATO VIVO il 2026-07-31: con `DB_FINANZA=:memory:` o `DB_FINANZA=` il
    prodotto PARTIVA E SERVIVA (misurato: processo ancora vivo dopo 25 secondi).

    `:memory:` vive dentro il processo; il percorso vuoto apre un database TEMPORANEO che
    sqlite cancella alla chiusura della connessione — e siccome ogni chiamata apre la sua
    connessione, l'archivio sparisce fra una riga e l'altra. In tutti e due i casi la sonda
    `/api/health/db` salta quei percorsi e continua a rispondere "ok": il modo di rompersi
    n.1 (dati effimeri), gia' pagato due volte con recensioni e crediti in RAM.
    """

    def test_archivio_in_memoria_non_parte_e_nomina_la_variabile(self):
        os.environ["DB_FINANZA"] = ":memory:"
        self._rifiuta("DB_FINANZA")

    def test_percorso_vuoto_non_parte_e_nomina_la_variabile(self):
        os.environ["DB_FINANZA"] = ""
        self._rifiuta("DB_FINANZA")

    def test_spazi_intorno_non_sono_un_travestimento(self):
        os.environ["DB_FINANZA"] = "  :memory:  "
        self._rifiuta("DB_FINANZA")

    def test_il_controllo_non_puo_scattare_DA_SOLO(self):
        """REGOLA FERREA 10: un falso allarme e' un difetto quanto un allarme mancato.

        Il controllo scorre TUTTI i campi `db_*` della configurazione, e il valore di serie
        di parecchi di essi e' proprio `:memory:`. Se `main` ne dimenticasse anche uno solo,
        il sito NON PARTIREBBE PIU'. Qui si pretende che ogni campo sia impostato da main.
        """
        import io as _io
        import re as _re

        from fase81_bootstrap_casavip import ConfigCasaVIP
        campi = [c for c in sorted(vars(ConfigCasaVIP())) if c.startswith("db_")]
        self.assertGreater(len(campi), 10, "denominatore sospetto: %d campi db_*" % len(campi))
        with _io.open("main_casavip.py", encoding="utf-8") as f:
            src = f.read()
        mai = [c for c in campi if _re.search(r"^\s*" + c + r"=", src, _re.M) is None]
        self.assertEqual([], mai,
                         "questi campi di configurazione non vengono impostati da "
                         "main_casavip: se il loro valore di serie e' ':memory:' il prodotto "
                         "si rifiuterebbe di partire in produzione. %r" % (mai,))


class TestChiaviSegnaposto(_BaseAvvio):
    """DIFETTO PROVATO VIVO: con `ADMIN_KEY=cambiami_chiave_admin` (il valore che sta
    PUBBLICO su GitHub in `.env.casavip.example`) il prodotto partiva e serviva. Una porta
    chiusa con una password stampata sul giornale e' una porta aperta."""

    def test_host_key_segnaposto_non_parte(self):
        os.environ["HOST_KEY"] = "cambiami_chiave_host"
        self._rifiuta("HOST_KEY")

    def test_admin_key_segnaposto_non_parte(self):
        os.environ["ADMIN_KEY"] = "cambiami_chiave_admin"
        self._rifiuta("ADMIN_KEY")

    def test_chiave_fatta_di_soli_spazi_vale_come_mancante(self):
        os.environ["HOST_KEY"] = "   "
        self._rifiuta("HOST_KEY")

    def test_i_segnaposto_sorvegliati_sono_QUELLI_VERI_dellesempio(self):
        """Se qualcuno cambia i valori in `.env.casavip.example` senza aggiornare l'elenco,
        la guardia diventa cieca in silenzio. Qui i due elenchi si confrontano."""
        import io as _io
        import re as _re
        with _io.open(".env.casavip.example", encoding="utf-8") as f:
            esempio = f.read()
        nell_esempio = set(_re.findall(r"^(?:CASAVIP_SEGRETO|HOST_KEY|ADMIN_KEY)=(\S+)",
                                       esempio, _re.M))
        sorvegliati = set(self._main().SEGNAPOSTO_PUBBLICI)
        self.assertEqual(nell_esempio, sorvegliati,
                         "i segnaposto di .env.casavip.example e quelli sorvegliati da "
                         "main_casavip non coincidono. esempio=%r sorvegliati=%r"
                         % (sorted(nell_esempio), sorted(sorvegliati)))


class TestConTuttoAPostoIlCancelloTACE(_BaseAvvio):
    """L'altra direzione, obbligatoria (REGOLA FERREA 10): con un ambiente sano l'avvio
    deve arrivare OLTRE tutti i cancelli. Un cancello che chiude sempre non e' un cancello,
    e' un muro — e nessuno se ne accorgerebbe finche' non tocca il deploy."""

    def test_ambiente_sano_supera_TUTTI_i_cancelli(self):
        m = self._main()
        sentinella = RuntimeError("arrivato oltre i cancelli")

        def _basta(_cfg):
            raise sentinella

        m.crea_sistema = _basta                       # si ferma appena PRIMA di servire
        with self.assertRaises(RuntimeError) as ctx:
            m.main()
        self.assertIs(ctx.exception, sentinella,
                      "con un ambiente valido l'avvio si e' fermato PRIMA di costruire il "
                      "sistema: un cancello sta rifiutando a torto")


if __name__ == "__main__":
    unittest.main()
