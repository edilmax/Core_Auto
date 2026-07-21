"""GUARDIA — la marca temporale DENTRO la macchina (fase184 ↔ fase81/83).

Il modulo puo' essere perfetto e restare scollegato: e' gia' successo su questo progetto
(la promo 0% funzionava e non veniva applicata). Qui si verifica il CABLAGGIO:
  · il sistema composto espone l'archivio delle marche;
  · le rotte del Bunker esistono, sono PROTETTE e rispondono;
  · il token grezzo si scarica e ha la giusta intestazione;
  · la marca finisce nel DOSSIER LEGALE, in CSV e in JSON;
  · niente di tutto questo trapela fuori dal Bunker.
"""

import json
import os
import shutil
import tempfile
import unittest

import fase184_marca_temporale as mt
from test_fase184_marca_temporale import _risposta, IMPRONTA


def _rete_finta(url, richiesta, timeout):
    """Risponde come una TSA vera, rileggendo impronta e nonce dalla richiesta."""
    t = mt._leggi_tlv(richiesta, 0)
    campi = mt._figli(richiesta, t[1], t[2])
    imp = mt._figli(richiesta, campi[1][1], campi[1][2])[1]
    return _risposta(richiesta[imp[1]:imp[2]],
                     nonce=mt._intero_da(richiesta, campi[2][1], campi[2][2]))


PW = "SuperPw@1"
AK = {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9", "User-Agent": "Firefox"}


class BaseServer(unittest.TestCase):
    """Monta un sistema vero, con il Bunker acceso."""

    def setUp(self):
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase83_server import crea_router
        self.d = d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/a.db",
            db_marche=f"{d}/marche.db", db_pendenti=f"{d}/p.db",
            db_finanza=f"{d}/f.db", bunker_password=PW))
        self.router = crea_router(self.sys, host_key="hk", admin_key="ak",
                                  base_url="https://bookinvip.com")

    def g(self, m, p, b=None, h=None, q=None):
        return self.router.gestisci(m, p, q or {},
                                    json.dumps(b) if b is not None else None, h or AK)

    def _hdr(self):
        st, o = self.g("POST", "/api/bunker/login", {"codice": PW})
        self.assertEqual(st, 200, o)
        h = dict(AK)
        h["X-Bunker-Session"] = o["sessione"]
        return h


class TestCablaggio(BaseServer):

    def test_il_sistema_espone_larchivio(self):
        self.assertIsNotNone(getattr(self.sys, "marche", None),
                             "fase184 non e' cablata nel sistema composto")

    def test_compare_nel_report_di_composizione(self):
        self.assertIn("marca_temporale(184)", self.sys.report.get("componenti", []))

    def test_il_database_e_su_file_non_in_ram(self):
        """Una prova che vive in RAM sparisce al riavvio: sarebbe inutile."""
        self.assertTrue(os.path.exists(os.path.join(self.d, "marche.db")))

    def test_i_registri_veri_sono_collegati(self):
        """La marca deve sigillare accettazioni E giornale, non oggetti vuoti."""
        esito = mt.marca_i_registri(self.sys.marche,
                                    accettazioni=self.sys.accettazioni,
                                    finanza=self.sys.finanza,
                                    giorno="2026-07-21", url="http://t.finto",
                                    trasporto=_rete_finta)
        self.assertTrue(esito["ok"], esito.get("motivo"))
        riga = self.sys.marche.elenco()[0]
        self.assertIn("accettazioni=", riga["canonico"])
        self.assertIn("giornale=", riga["canonico"])
        self.assertNotIn("assente", riga["canonico"],
                         "i registri non risultano collegati")

    def test_la_marca_segue_le_prove_vere(self):
        """Aggiungere una prova d'accettazione DEVE cambiare l'impronta marcata."""
        a = mt.marca_i_registri(self.sys.marche, accettazioni=self.sys.accettazioni,
                                finanza=self.sys.finanza, giorno="2026-07-21",
                                url="http://t.finto", trasporto=_rete_finta)
        self.sys.accettazioni.registra("host-nuovo", ip="1.2.3.4", vessatorie=True)
        b = mt.marca_i_registri(self.sys.marche, accettazioni=self.sys.accettazioni,
                                finanza=self.sys.finanza, giorno="2026-07-22",
                                url="http://t.finto", trasporto=_rete_finta)
        self.assertNotEqual(a["impronta"], b["impronta"])


class TestRotteBunker(BaseServer):

    def test_senza_sessione_e_403(self):
        for metodo, rotta in [("GET", "/api/bunker/marche_temporali"),
                              ("POST", "/api/bunker/marca_ora")]:
            st, _ = self.g(metodo, rotta, {} if metodo == "POST" else None, {})
            self.assertEqual(st, 403, "%s %s non e' protetta!" % (metodo, rotta))

    def test_con_sessione_risponde(self):
        st, corpo = self.g("GET", "/api/bunker/marche_temporali", None, self._hdr())
        self.assertEqual(st, 200, corpo)
        self.assertIn("marche", corpo)
        self.assertIn("come_verificare", corpo)
        self.assertIn("openssl ts -verify", corpo["come_verificare"])

    def test_elenca_le_marche_ottenute(self):
        mt.marca_i_registri(self.sys.marche, accettazioni=self.sys.accettazioni,
                            finanza=self.sys.finanza, giorno="2026-07-21",
                            url="http://t.finto", trasporto=_rete_finta)
        st, corpo = self.g("GET", "/api/bunker/marche_temporali", None, self._hdr())
        self.assertEqual(st, 200)
        self.assertEqual(corpo["riuscite"], 1)
        m = corpo["marche"][0]
        self.assertTrue(m["token_riverificato"], "il token archiviato non si riverifica")
        self.assertTrue(m["ora_coerente"])
        self.assertTrue(m["ora_certificata_utc"].endswith("UTC"))
        self.assertIn("marca.tsr", m["scarica"])

    def test_il_token_si_scarica_grezzo(self):
        mt.marca_i_registri(self.sys.marche, accettazioni=self.sys.accettazioni,
                            finanza=self.sys.finanza, giorno="2026-07-21",
                            url="http://t.finto", trasporto=_rete_finta)
        idm = self.sys.marche.elenco()[0]["id"]
        st, token = self.router.scarica_marca(idm, self._hdr())
        self.assertEqual(st, 200)
        self.assertIsInstance(token, bytes)
        self.assertEqual(token[0], 0x30, "non e' un oggetto ASN.1")

    def test_scarico_del_token_protetto(self):
        st, token = self.router.scarica_marca(1, {})
        self.assertEqual(st, 403)
        self.assertIsNone(token)

    def test_scarico_di_un_id_inesistente_o_assurdo(self):
        for cattivo in [999999, "abc", "", None, -1]:
            st, token = self.router.scarica_marca(cattivo, self._hdr())
            self.assertIn(st, (400, 404))
            self.assertIsNone(token)

    def test_congela_adesso_e_idempotente_con_marca_qualificata(self):
        """Una seconda richiesta non deve disturbare di nuovo l'Autorita' — a patto che
        la marca gia' presa sia QUALIFICATA. (Se fosse solo un ripiego si riproverebbe
        apposta, per non restare tutto il giorno con una prova di rango inferiore:
        regola cambiata il 2026-07-21 dopo averlo visto accadere in produzione.)"""
        import fase184_marca_temporale as m2
        from test_marca_qualificata import _token_qualificato

        def qualificata(imp, **kw):
            risposta = _token_qualificato(imp, nonce=7)
            e = m2.interpreta_risposta(risposta, imp, 7)
            e["qualificata"] = m2.e_qualificata(e.get("token") or b"")
            e["tsa"] = "http://tsa.finta.eu"
            return e

        vero = m2.chiedi_marca
        m2.chiedi_marca = qualificata
        try:
            st1, c1 = self.g("POST", "/api/bunker/marca_ora", {}, self._hdr())
            st2, c2 = self.g("POST", "/api/bunker/marca_ora", {}, self._hdr())
        finally:
            m2.chiedi_marca = vero
        self.assertEqual(st1, 200, c1)
        self.assertTrue(c1.get("ok"), c1)
        self.assertTrue(c1.get("qualificata"), "la marca finta deve risultare qualificata")
        self.assertEqual(st2, 200)
        self.assertEqual(c2.get("saltato"), "gia_marcato_oggi")

    def test_col_solo_ripiego_congela_adesso_RIPROVA(self):
        """Con in archivio una marca ordinaria, premere «Congela adesso» deve tentare
        di nuovo: e' l'occasione per rimpiazzarla con una qualificata."""
        import fase184_marca_temporale as m2
        vero = m2.chiedi_marca
        m2.chiedi_marca = lambda imp, **kw: m2.interpreta_risposta(
            _rete_finta("x", m2.costruisci_richiesta(imp, 7), 1), imp, 7)
        try:
            st1, c1 = self.g("POST", "/api/bunker/marca_ora", {}, self._hdr())
            st2, c2 = self.g("POST", "/api/bunker/marca_ora", {}, self._hdr())
        finally:
            m2.chiedi_marca = vero
        self.assertTrue(c1.get("ok"))
        self.assertFalse(c1.get("qualificata"))
        self.assertEqual(c2.get("saltato"), "ripiego_gia_presente",
                         "si e' riprovato, ma senza archiviare un doppione")


class TestDossier(BaseServer):

    def setUp(self):
        super().setUp()
        self.sys.accettazioni.registra("host-1", ip="1.2.3.4", vessatorie=True)
        mt.marca_i_registri(self.sys.marche, accettazioni=self.sys.accettazioni,
                            finanza=self.sys.finanza, giorno="2026-07-21",
                            url="http://t.finto", trasporto=_rete_finta)

    def test_nel_dossier_csv(self):
        st, corpo = self.g("GET", "/api/bunker/export_legale", None, self._hdr(), {"formato": "csv"})
        self.assertEqual(st, 200)
        testo = corpo["contenuto"]
        self.assertIn("MARCHE TEMPORALI", testo)
        self.assertIn("ora_certificata_utc", testo)
        self.assertIn("openssl ts -verify", testo)
        self.assertIn("# marche_temporali,1", testo)
        self.assertTrue(corpo["certificato"], "il dossier deve restare sigillato")

    def test_nel_dossier_json(self):
        st, corpo = self.g("GET", "/api/bunker/export_legale", None, self._hdr(), {"formato": "json"})
        self.assertEqual(st, 200)
        testo = corpo["contenuto"]
        dati = json.loads(testo.split("\n# FINE DOSSIER")[0])
        mtj = dati["marche_temporali"]
        self.assertEqual(mtj["totale"], 1)
        self.assertEqual(mtj["elenco"][0]["token_riverificato"], "SI")
        self.assertIn("non e' dichiarata da BookinVIP", mtj["cosa_provano"])

    def test_dossier_valido_anche_senza_marche(self):
        """Se la marca fosse spenta, il fascicolo deve restare valido lo stesso."""
        self.sys.marche = None
        st, corpo = self.g("GET", "/api/bunker/export_legale", None, self._hdr(), {"formato": "csv"})
        self.assertEqual(st, 200)
        self.assertIn("nessuna marca temporale presente", corpo["contenuto"])
        self.assertTrue(corpo["certificato"])


class TestNienteTrapela(BaseServer):

    def test_le_marche_non_escono_dal_pannello_operativo(self):
        """Il Field (chiave admin) NON deve vedere le prove: solo il Bunker."""
        st, corpo = self.g("GET", "/api/bunker/marche_temporali", None, {"X-Admin-Key": "ak"})
        self.assertEqual(st, 403)

    def test_nessuna_marca_nelle_rotte_pubbliche(self):
        for rotta in ["/api/trasparenza", "/api/salute", "/api/ricerca"]:
            st, corpo = self.g("GET", rotta, None, {})
            if isinstance(corpo, dict):
                self.assertNotIn("marche", corpo)
                self.assertNotIn("marche_temporali", corpo)


class TestSpenta(unittest.TestCase):

    def test_sistema_si_compone_anche_con_la_marca_spenta(self):
        """Kill-switch: MARCA_TEMPORALE=0 e la macchina parte identica."""
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        vecchio = os.environ.get("MARCA_TEMPORALE")
        os.environ["MARCA_TEMPORALE"] = "0"
        try:
            d = tempfile.mkdtemp()
            s = crea_sistema(ConfigCasaVIP(
                abilitato=True, segreto_hmac=b"s" * 32,
                db_catalogo=os.path.join(d, "c.db"),
                db_inventario=os.path.join(d, "i.db"),
                db_marche=os.path.join(d, "m.db")))
            self.assertIsNone(s.marche)
            self.assertNotIn("marca_temporale(184)", s.report.get("componenti", []))
            self.assertFalse(os.path.exists(os.path.join(d, "m.db")),
                             "spenta non deve nemmeno creare il file")
        finally:
            if vecchio is None:
                os.environ.pop("MARCA_TEMPORALE", None)
            else:
                os.environ["MARCA_TEMPORALE"] = vecchio


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestIlGiroGiornalieroEIndipendente(unittest.TestCase):
    """GUARDIA STRUTTURALE — il giro della marca non deve dipendere da altro.

    TROVATO IL 2026-07-21 avviando `main_casavip.py` PER DAVVERO (la suite non lo
    esegue mai): il ciclo giornaliero era stato messo dentro il blocco
    `if pp is not None and email_prov is not None:` — cioe' partiva **solo con SMTP
    configurato**. In produzione SMTP c'e', quindi "funzionava"; ma il giorno in cui
    l'email si guasta, le prove legali smetterebbero di essere datate da un terzo
    **in silenzio**, e ce ne accorgeremmo in causa. Datare i registri non ha nulla a
    che vedere con l'invio delle email.
    """

    def _sorgente(self):
        import io
        import os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fase83_server.py")
        return io.open(p, encoding="utf-8").read()

    def test_il_ciclo_esiste(self):
        self.assertIn("def _tick_marca_temporale", self._sorgente())

    def test_non_dipende_dalla_configurazione_email(self):
        s = self._sorgente()
        inizio = s.index("def _tick_marca_temporale")
        # si risale al blocco che lo contiene: deve essere quello della marca, non
        # quello delle email (l'ultimo `if ... email_prov ...` prima del ciclo)
        prima = s[:inizio]
        gate_marche = prima.rfind("if _marche is not None:")
        gate_email = prima.rfind("email_prov is not None")
        self.assertGreater(gate_marche, gate_email,
                           "il ciclo della marca e' finito DENTRO il blocco delle email: "
                           "senza SMTP le prove non verrebbero piu' datate, in silenzio")

    def test_e_condizionato_solo_al_proprio_archivio(self):
        s = self._sorgente()
        inizio = s.rindex("if _marche is not None:")
        fine = s.index("srv.serve_forever()", inizio)
        blocco = s[inizio:fine]
        for estraneo in ("email_prov", "smtp", "pagamenti_pendenti", "inventario"):
            self.assertNotIn(estraneo, blocco,
                             "il blocco della marca nomina '%s': non deve dipendere da "
                             "nulla che non sia il proprio archivio" % estraneo)

    def test_parte_prima_che_il_server_serva(self):
        """Deve essere avviato, non solo definito."""
        s = self._sorgente()
        avvio = s.index("_th4.Thread(target=_tick_marca_temporale, daemon=True).start()")
        self.assertLess(avvio, s.index("srv.serve_forever()", avvio - 1000))

    def test_e_un_thread_demone(self):
        """Un thread non-demone impedirebbe al processo di chiudersi al riavvio."""
        s = self._sorgente()
        i = s.index("_tick_marca_temporale, daemon=True")
        self.assertGreater(i, 0, "il ciclo deve girare come demone")
