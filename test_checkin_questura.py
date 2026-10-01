"""Collaudo -- la Questura dal check-in (blocco 3, 1 ottobre).

Tre difetti, ognuno con la guardia vista ROSSA prima della riparazione (D20):
1. in Italia il check-in raccoglieva solo nome e numero di documento: con quei dati la
   schedina di Alloggiati Web non si puo' scrivere (`fase151` vuole sesso, nascita,
   cittadinanza, e il documento di chi guida la famiglia o il gruppo);
2. i dati degli ospiti restavano PER SEMPRE: il Garante (comunicato del 29/4/2026) vuole che,
   trasmessi alla Questura, si cancellino subito; e il portale accetta solo arrivi di oggi o
   di ieri, quindi dopo non servono a niente;
3. l'informativa non nominava i dati del check-in e diceva di non conservare documenti.
L'altra direzione: fuori dall'Italia il check-in resta com'era.
"""
import ast
import datetime
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

import fase83_server
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

# codici veri delle tabelle ufficiali (deploy/alloggiati/)
ROMA, ITALIA, FRANCIA = "412058091", "100000100", "100000215"


def _capo(**k):
    o = {"cognome": "Rossi", "nome": "Mario", "sesso": "m", "data_nascita": "1980-05-17",
         "stato_nascita": ITALIA, "comune_nascita": ROMA, "prov_nascita": "RM",
         "cittadinanza": ITALIA, "tipo_doc": "IDENT", "num_doc": "CA12345AB",
         "luogo_doc": ROMA}
    o.update(k)
    return o


def _familiare(**k):
    o = {"cognome": "Dupont", "nome": "Claire", "sesso": "f", "data_nascita": "1982-01-02",
         "stato_nascita": FRANCIA, "cittadinanza": FRANCIA}
    o.update(k)
    return o


IP = "203.0.113.9"
# una costante, non un letterale nel banco (bandit B106), come in test_ritenuta
_CHIAVE_BUNKER_DI_PROVA = "SuperPw@1"


class _Banco(unittest.TestCase):
    PAESE, CIN = "IT", ""
    ACCESO = True          # il check-in online e' SPENTO di serie: queste prove lo accendono

    def setUp(self):
        prima = os.environ.get("CHECKIN_ONLINE_ATTIVO")
        self.addCleanup(lambda: os.environ.pop("CHECKIN_ONLINE_ATTIVO", None) if prima is None
                        else os.environ.__setitem__("CHECKIN_ONLINE_ATTIVO", prima))
        if self.ACCESO:
            os.environ["CHECKIN_ONLINE_ATTIVO"] = "1"
        else:
            os.environ.pop("CHECKIN_ONLINE_ATTIVO", None)
        self.d = tempfile.mkdtemp()
        self.db_ck = os.path.join(self.d, "ck.db")
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"Q" * 32,
            db_catalogo=f"{self.d}/c.db", db_inventario=f"{self.d}/i.db",
            db_checkin=self.db_ck, bunker_password=_CHIAVE_BUNKER_DI_PROVA))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        from fase57_vetrina import SchedaAlloggio
        self.sis.catalogo.pubblica(SchedaAlloggio(
            host_id="h1", slug="casa", titolo="Casa", citta="Roma", paese=self.PAESE,
            cin=self.CIN, prezzo_notte_cents=10000, capacita=4))
        oggi = datetime.date.today()
        self.arrivo = oggi + datetime.timedelta(days=10)
        self.ci = self.arrivo.isoformat()
        self.co = (oggi + datetime.timedelta(days=13)).isoformat()
        for i in range(3):
            self.sis.inventario.imposta_disponibilita(
                "casa", (self.arrivo + datetime.timedelta(days=i)).isoformat(),
                unita_totali=1, prezzo_netto_cents=10000)
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": self.ci, "check_out": self.co,
                       "party": 3})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "g@x.it"})
        self.assertEqual(s, 201, b)
        self.voucher = b["voucher_token"]
        self.rif = self.sis.firma.decodifica(self.voucher)["riferimento"]

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, q=None, h=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def bunker(self):
        s, out = self.g("POST", "/api/bunker/login", {"codice": _CHIAVE_BUNKER_DI_PROVA},
                        h={"X-Admin-Key": "ak", "X-Forwarded-For": IP})
        self.assertEqual(s, 200, out)
        return {"X-Admin-Key": "ak", "X-Forwarded-For": IP, "X-Bunker-Session": out["sessione"]}

    def paga(self):
        """Quello che fa il webhook di un pagamento riuscito: il voucher mostra il check-in
        solo a pagamento avvenuto."""
        pp = self.sis.pagamenti_pendenti
        self.assertIsNotNone(pp, "serve l'archivio dei pagamenti")
        self.assertTrue(pp.registra(self.rif, alloggio_id="casa", check_in=self.ci,
                                    check_out=self.co))
        pp.conferma(self.rif)
        self.assertEqual(pp.info(self.rif)["stato"], "pagato")

    def registra(self, ospiti, **extra):
        corpo = {"voucher_token": self.voucher, "ospiti": ospiti}
        corpo.update(extra)
        return self.g("POST", "/api/checkin/pre_registra", corpo)

    def salvati(self, rif=None):
        con = sqlite3.connect(self.db_ck)
        try:
            r = con.execute("SELECT ospiti_json FROM checkin WHERE prenotazione_id=?",
                            (rif or self.rif,)).fetchone()
        finally:
            con.close()
        return json.loads(r[0]) if r else None


class TestInItaliaIlCheckinRaccoglieLaSchedina(_Banco):

    def test_SOLO_NOME_E_DOCUMENTO_NON_BASTANO_IN_ITALIA(self):
        s, out = self.registra([{"nome": "Mario Rossi", "documento": "AB1234567"}])
        self.assertEqual(s, 422, out)
        self.assertEqual(out.get("errore"), "dati_questura", out)
        self.assertIs(out.get("ok"), False, out)
        self.assertIsNone(self.salvati(), "con dati che non bastano non si scrive niente")

    def test_OSPITI_VUOTI_O_NON_OSPITI_DANNO_DATI_QUESTURA(self):
        for ospiti in ([], "Mario Rossi", [_capo(), "Claire"]):
            with self.subTest(ospiti=ospiti):
                s, out = self.registra(ospiti)
                self.assertEqual(s, 422, out)
                self.assertEqual(out.get("errore"), "dati_questura", out)
        self.assertIsNone(self.salvati())

    def test_FAMIGLIA_DA_DUE_SCHEDINE_CHE_IL_PORTALE_ACCETTA(self):
        s, out = self.registra([_capo(), _familiare()])
        self.assertEqual(s, 200, out)
        righe = self.salvati()
        self.assertEqual([o["ruolo"] for o in righe], ["capofamiglia", "familiare"])
        from fase151_alloggiati_web import LUNGHEZZA_RECORD, carica_tabelle, genera_schedina
        tabelle = carica_tabelle()
        for o in righe:
            riga = genera_schedina(dict(o, data_arrivo=self.ci, giorni=3), tabelle)
            self.assertEqual(len(riga), LUNGHEZZA_RECORD, o)
        s, st = self.g("GET", "/api/checkin/stato", q={"voucher_token": self.voucher})
        self.assertTrue(st["completato"], st)

    def test_GRUPPO_E_OSPITE_SINGOLO(self):
        s, out = self.registra([_capo(), _familiare()], gruppo=True)
        self.assertEqual(s, 200, out)
        self.assertEqual([o["ruolo"] for o in self.salvati()], ["capogruppo", "membro_gruppo"])
        s, out = self.registra([_capo()])
        self.assertEqual(s, 200, out)
        self.assertEqual([o["ruolo"] for o in self.salvati()], ["singolo"])

    def test_UN_CODICE_CHE_NON_ESISTE_DICE_CHI_E_PERCHE(self):
        s, out = self.registra([_capo(), _familiare(stato_nascita="999999999")])
        self.assertEqual(s, 422, out)
        self.assertEqual([d["ospite"] for d in out["dettagli"]], [2], out)
        self.assertTrue(any("stato_nascita" in e for e in out["dettagli"][0]["errori"]), out)
        self.assertIsNone(self.salvati())

    def test_CHI_GUIDA_LA_FAMIGLIA_SENZA_DOCUMENTO_NON_PASSA(self):
        s, out = self.registra([_capo(num_doc=""), _familiare()])
        self.assertEqual(s, 422, out)
        self.assertEqual([d["ospite"] for d in out["dettagli"]], [1], out)
        self.assertTrue(any("num_doc" in e for e in out["dettagli"][0]["errori"]), out)

    def test_PIU_OSPITI_DI_QUELLI_PAGATI_NON_PASSANO(self):
        s, out = self.registra([_capo(), _familiare(), _familiare(nome="Anne"),
                                _familiare(nome="Paul")])        # 4 > 3 pagati
        self.assertEqual(s, 422, out)
        self.assertIsNone(self.salvati())


class TestIlCheckinOnlineESpentoDiSerie(_Banco):
    """Decisione del fondatore (1/10): il check-in lo fa l'host all'arrivo, come fanno tutti;
    il check-in online resta nel codice, SPENTO di serie, con un pulsante nel bunker per
    accenderlo un domani. Spento: non si mostra e non si raccoglie niente."""
    ACCESO = False

    def test_SPENTO_LA_ROTTA_NON_PRENDE_NIENTE(self):
        s, out = self.registra([_capo(), _familiare()])
        self.assertEqual((s, out.get("errore")), (409, "checkin_online_spento"), out)
        self.assertIsNone(self.salvati(), "spento, non si scrive niente")

    def test_SPENTO_LA_PAGINA_NON_HA_IL_MODULO(self):
        self.paga()
        html = fase83_server.pagina_voucher_html(self.sis, self.voucher, "it")
        self.assertNotIn("id='qBox'", html)
        self.assertNotIn("id='ckBox'", html)

    def test_IL_PULSANTE_DEL_BUNKER_LO_ACCENDE_E_LO_SPEGNE(self):
        s, d = self.g("GET", "/api/bunker/checkin_online")
        self.assertEqual(s, 403, "senza bunker non si legge")
        s, d = self.g("POST", "/api/bunker/checkin_online", {"attivo": True})
        self.assertEqual(s, 403, "senza bunker non si accende")
        hb = self.bunker()
        s, d = self.g("GET", "/api/bunker/checkin_online", h=hb)
        self.assertEqual((s, d.get("attivo")), (200, False), d)
        s, d = self.g("POST", "/api/bunker/checkin_online",
                      {"attivo": True, "motivo": "collaudo"}, h=hb)
        self.assertEqual((s, d.get("attivo")), (200, True), d)
        self.assertEqual(self.registra([_capo(), _familiare()])[0], 200, "acceso, si registra")
        self.paga()
        self.assertIn("id='qBox'", fase83_server.pagina_voucher_html(self.sis, self.voucher, "it"))
        s, d = self.g("POST", "/api/bunker/checkin_online", {"attivo": False}, h=hb)
        self.assertEqual((s, d.get("attivo")), (200, False), d)
        self.assertEqual(self.registra([_capo()])[0], 409, "rispento, non si registra piu'")

    def test_SE_L_INTERRUTTORE_NON_SI_SCRIVE_LO_DICE_E_IL_REGISTRO_NON_MENTE(self):
        # trovato dal browser il 1/10: col check-in in memoria l'interruttore non ha un file in
        # cui scriversi, la risposta era 500 ma il registro scriveva «CHECK-IN ONLINE ACCESO»
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"Q" * 32, db_catalogo=f"{self.d}/c2.db",
            db_inventario=f"{self.d}/i2.db", bunker_password=_CHIAVE_BUNKER_DI_PROVA))
        self.r = crea_router(sis, host_key="hk", admin_key="ak")
        hb = self.bunker()
        with self.assertLogs("core_auto.server", level="WARNING") as visti:
            s, d = self.g("POST", "/api/bunker/checkin_online", {"attivo": True}, h=hb)
        self.assertEqual((s, d.get("attivo"), d.get("impostato")), (500, False, False), d)
        self.assertFalse([r for r in visti.output if "CHECK-IN ONLINE ACCESO" in r],
                         "il registro dice acceso e non lo e': %s" % visti.output)
        self.assertTrue([r for r in visti.output if "NON" in r and "CHECK-IN ONLINE" in r],
                        visti.output)

    def test_ACCESO_DAL_BUNKER_RESTA_ACCESO_DOPO_UN_RIAVVIO(self):
        hb = self.bunker()
        self.assertEqual(self.g("POST", "/api/bunker/checkin_online", {"attivo": True},
                                h=hb)[0], 200)
        dopo = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"Q" * 32, db_catalogo=f"{self.d}/c.db",
            db_inventario=f"{self.d}/i.db", db_checkin=self.db_ck))
        self.assertTrue(dopo.checkin_online.attivo(),
                        "l'interruttore vive in un file accanto ai dati, non nella memoria")


class TestLaPaginaDelVoucherChiedeLaSchedina(_Banco):
    """Senza il modulo nella pagina, la rotta rifiuterebbe ogni ospite in Italia: e' la
    meta' che l'ospite vede."""

    def pagina(self):
        self.paga()
        return fase83_server.pagina_voucher_html(self.sis, self.voucher, "it")

    def test_IN_ITALIA_IL_MODULO_HA_I_CAMPI_DELLA_SCHEDINA(self):
        html = self.pagina()
        for campo in ("qCog", "qNom", "qSex", "qNas", "qStato", "qComune", "qCitt", "qTdoc",
                      "qNdoc", "qLstato", "qLcomune", "qGruppo", "qSend"):
            self.assertIn("id='%s'" % campo, html, campo)
        self.assertIn("/api/alloggiati/tabelle", html)
        self.assertNotIn("id='ckNome'", html, "in Italia il modulo di nome e documento non serve")

    def test_LA_RIGA_DELLA_PRIVACY_DICE_IL_TERMINE_DELL_INFORMATIVA(self):
        import fase185_testi_legali as legale
        prima = legale.GIORNI_CONSERVAZIONE_CHECKIN
        legale.GIORNI_CONSERVAZIONE_CHECKIN = 97
        try:
            html = self.pagina()
        finally:
            legale.GIORNI_CONSERVAZIONE_CHECKIN = prima
        self.assertIn("si cancellano da soli 97 giorni dopo l&#x27;arrivo", html)
        self.assertIn("/privacy.html?lang=it", html)

    def test_LA_RIGA_DELLA_PRIVACY_SI_COMPONE_IN_OGNI_LINGUA(self):
        for lang, testo in fase83_server.ETICHETTE_UI["v_q_privacy"].items():
            self.assertEqual(testo.count("%d"), 1, lang)
            self.assertIn("109", testo, lang)
        self.assertEqual(len(fase83_server.ETICHETTE_UI["v_q_privacy"]), 8)


class TestLeTabelleDelModulo(_Banco):

    def test_STATI_E_DOCUMENTI(self):
        s, t = self.g("GET", "/api/alloggiati/tabelle")
        self.assertEqual(s, 200, t)
        self.assertIn([ITALIA, "ITALIA", True], t["stati"])
        self.assertTrue(any(not attivo for _c, _n, attivo in t["stati"]),
                        "servono anche gli stati che non esistono piu': si nasce anche li'")
        self.assertIn("IDENT", [c for c, _n in t["documenti"]])

    def test_I_COMUNI_SI_CERCANO_DALLE_PRIME_LETTERE(self):
        s, out = self.g("GET", "/api/alloggiati/comuni", q={"q": "rom"})
        self.assertEqual(s, 200, out)
        self.assertIn([ROMA, "ROMA", "RM", ""], out["comuni"])
        self.assertTrue(all(c[1].startswith("ROM") for c in out["comuni"]), out)
        self.assertLessEqual(len(out["comuni"]), 20)
        fine = [c[3] for c in out["comuni"]]
        self.assertEqual(fine, sorted(fine, key=lambda f: f != ""),
                         "prima i comuni di oggi, poi quelli che non esistono piu'")

    def test_UNA_LETTERA_SOLA_NON_CERCA(self):
        for q in ({"q": "r"}, {}):
            s, out = self.g("GET", "/api/alloggiati/comuni", q=q)
            self.assertEqual((s, out), (200, {"comuni": []}), q)


class TestDatiMessiACaso(_Banco):
    """Il fondatore (1/10): «fai le prove se funziona, mettili a caso i dati». Famiglie e
    gruppi inventati a caso, coi codici pescati dalle tabelle ufficiali e semi fissi (il seme
    sta nel messaggio d'errore, per rifare il caso): un ospite valido per costruzione passa e
    la sua schedina si scrive; un dato rotto a caso fa rifiutare, nominando l'ospite giusto."""

    GIRI = 60
    # ⚠️ «Søren» NON e' qui: la Ø non ha una forma latina e la schedina la rifiuta (regola del
    # 30/9). L'hanno trovato i dati a caso, il 1/10: e' scritto fra i difetti aperti.
    NOMI = ("Mario", "Niccolò", "José", "Zoë", "Anne-Marie", "Li", "Sören", "Ana Sofía")
    COGNOMI = ("Rossi", "D'Angelo", "De Luca", "Müller", "García López", "Ng", "O'Brien")
    GUASTI = ("manca_cognome", "sesso_x", "data_inesistente", "stato_inventato",
              "lettere_non_latine", "cittadinanza_finita")

    @classmethod
    def setUpClass(cls):
        from fase151_alloggiati_web import carica_tabelle
        t = carica_tabelle()
        cls.stati_oggi = sorted(c for c, v in t["STATI"].items() if v["fine"] is None)
        cls.stati_finiti = sorted(c for c, v in t["STATI"].items() if v["fine"] is not None)
        cls.comuni_oggi = sorted((c, v["provincia"]) for c, v in t["COMUNI"].items()
                                 if v["fine"] is None)
        cls.documenti = sorted(t["DOCUMENTI"])

    def _ospite(self, rnd, primo):
        nascita = datetime.date(1930, 1, 1) + datetime.timedelta(days=rnd.randrange(30000))
        o = {"cognome": rnd.choice(self.COGNOMI), "nome": rnd.choice(self.NOMI),
             "sesso": rnd.choice("mf"), "data_nascita": nascita.isoformat(),
             "cittadinanza": rnd.choice(self.stati_oggi)}
        if rnd.random() < 0.5:
            comune, prov = rnd.choice(self.comuni_oggi)
            o.update(stato_nascita=ITALIA, comune_nascita=comune, prov_nascita=prov)
        else:
            o["stato_nascita"] = rnd.choice([s for s in self.stati_oggi if s != ITALIA])
        if primo:
            o.update(tipo_doc=rnd.choice(self.documenti),
                     num_doc="".join(rnd.choice("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789")
                                     for _ in range(rnd.randint(5, 20))))
            o["luogo_doc"] = (rnd.choice(self.comuni_oggi)[0] if rnd.random() < 0.5
                              else rnd.choice([s for s in self.stati_oggi if s != ITALIA]))
        return o

    def _famiglia(self, seme):
        import random
        rnd = random.Random(seme)  # nosec B311 - inventa dati di prova, non protegge niente
        n = rnd.randint(1, 3)                                  # al massimo i 3 pagati
        return rnd, [self._ospite(rnd, i == 0) for i in range(n)], rnd.random() < 0.3

    def test_UN_OSPITE_VALIDO_A_CASO_PASSA_E_LA_SCHEDINA_SI_SCRIVE(self):
        from fase151_alloggiati_web import LUNGHEZZA_RECORD, carica_tabelle, genera_schedina
        tabelle = carica_tabelle()
        for seme in range(self.GIRI):
            _rnd, ospiti, gruppo = self._famiglia(seme)
            s, out = self.registra(ospiti, gruppo=gruppo)
            self.assertEqual(s, 200, "seme %d: %s -> %s" % (seme, ospiti, out))
            righe = self.salvati()
            self.assertEqual(len(righe), len(ospiti), "seme %d" % seme)
            for o in righe:
                riga = genera_schedina(dict(o, data_arrivo=self.ci, giorni=3), tabelle)
                self.assertEqual(len(riga), LUNGHEZZA_RECORD, "seme %d: %s" % (seme, o))

    def test_UN_DATO_ROTTO_A_CASO_FA_RIFIUTARE_E_NOMINA_L_OSPITE(self):
        for seme in range(self.GIRI):
            rnd, ospiti, gruppo = self._famiglia(seme)
            chi = rnd.randrange(len(ospiti))
            guasto = rnd.choice(self.GUASTI)
            o = ospiti[chi]
            if guasto == "manca_cognome":
                o["cognome"] = ""
            elif guasto == "sesso_x":
                o["sesso"] = "x"
            elif guasto == "data_inesistente":
                o["data_nascita"] = "1990-02-30"
            elif guasto == "stato_inventato":
                o["stato_nascita"], o["comune_nascita"], o["prov_nascita"] = "999999999", "", ""
            elif guasto == "lettere_non_latine":
                o["nome"] = "Łukasz"
            else:
                o["cittadinanza"] = rnd.choice(self.stati_finiti)
            s, out = self.registra(ospiti, gruppo=gruppo)
            dove = "seme %d, guasto %s sull'ospite %d" % (seme, guasto, chi + 1)
            self.assertEqual((s, out.get("errore")), (422, "dati_questura"), dove)
            self.assertEqual([d["ospite"] for d in out["dettagli"]], [chi + 1], dove)


class TestColCinEItaliaAncheSenzaPaese(_Banco):
    PAESE, CIN = "", "IT058091C2X5V0ABCD"

    def test_IL_CIN_BASTA_A_DIRE_ITALIA(self):
        s, out = self.registra([{"nome": "Mario Rossi", "documento": "AB1234567"}])
        self.assertEqual(s, 422, out)
        self.assertEqual(out.get("errore"), "dati_questura", out)


class TestFuoriDallItaliaNonCambiaNiente(_Banco):
    PAESE = "FR"

    def test_NOME_E_DOCUMENTO_BASTANO_ANCORA(self):
        s, out = self.registra([{"nome": "Jean Dupont", "documento": "AB1234567"}])
        self.assertEqual(s, 200, out)
        self.assertEqual(self.salvati(), [{"nome": "Jean Dupont", "documento": "AB1234567"}])

    def test_LA_PAGINA_HA_IL_MODULO_DI_SEMPRE(self):
        self.paga()
        html = fase83_server.pagina_voucher_html(self.sis, self.voucher, "it")
        self.assertIn("id='ckNome'", html)
        self.assertNotIn("id='qCog'", html)


class TestIDatiDegliOspitiNonRestano(_Banco):

    def _passata(self, giorno):
        ts = datetime.datetime.combine(giorno, datetime.time(1, 0),
                                       tzinfo=datetime.timezone.utc).timestamp()
        return fase83_server.checkin_conservazione_una_passata(self.sis, ora_ts=ts)

    def test_IL_GIORNO_DOPO_L_ARRIVO_CI_SONO_ANCORA(self):
        # il portale accetta l'arrivo di ieri: l'host puo' ancora trasmetterli
        self.assertEqual(self.registra([_capo(), _familiare()])[0], 200)
        self._passata(self.arrivo + datetime.timedelta(days=1))
        self.assertEqual(len(self.salvati()), 2)

    def test_DOPO_IL_TERMINE_SPARISCONO_E_LA_PORTA_SI_APRE_ANCORA(self):
        import fase185_testi_legali as legale
        self.assertEqual(self.registra([_capo(), _familiare()])[0], 200)
        esito = self._passata(
            self.arrivo + datetime.timedelta(days=legale.GIORNI_CONSERVAZIONE_CHECKIN))
        self.assertEqual(self.salvati(), [])
        self.assertEqual(esito.get("cancellate"), 1, esito)
        self.assertTrue(self.sis.checkin.completato(self.rif),
                        "cancellare i dati non deve chiudere la porta all'ospite")

    def test_IL_TERMINE_SI_LEGGE_DALL_INFORMATIVA(self):
        import fase185_testi_legali as legale
        prima = legale.GIORNI_CONSERVAZIONE_CHECKIN
        self.assertEqual(self.registra([_capo(), _familiare()])[0], 200)
        legale.GIORNI_CONSERVAZIONE_CHECKIN = prima + 3
        try:
            self._passata(self.arrivo + datetime.timedelta(days=prima))
        finally:
            legale.GIORNI_CONSERVAZIONE_CHECKIN = prima
        self.assertEqual(len(self.salvati()), 2,
                         "il giro ha cancellato prima del termine che l'informativa promette")

    def test_UNA_RIGA_SENZA_DATA_DI_ARRIVO_NON_SI_TIENE(self):
        # le righe scritte prima di questa versione non hanno la data: non si sa fino a
        # quando servono, quindi non si tengono
        self.sis.checkin.pre_registra("vecchia", "casa",
                                      [{"nome": "Mario Rossi", "documento": "AB1234567"}], 2)
        self.assertEqual(self.salvati("vecchia"),
                         [{"nome": "Mario Rossi", "documento": "AB1234567"}])
        self._passata(datetime.date.today())
        self.assertEqual(self.salvati("vecchia"), [])

    def test_QUANDO_CANCELLA_LO_SCRIVE_E_QUANDO_NON_CE_NIENTE_TACE(self):
        self.assertEqual(self.registra([_capo(), _familiare()])[0], 200)
        with self.assertLogs("core_auto.server", level="INFO") as visti:
            self._passata(self.arrivo)                    # niente da cancellare
            fase83_server.logger.info("segnaposto")       # assertLogs vuole almeno una riga
        self.assertFalse([r for r in visti.output if "dati degli ospiti cancellati" in r],
                         visti.output)
        with self.assertLogs("core_auto.server", level="INFO") as visti:
            self._passata(self.arrivo + datetime.timedelta(days=30))
        self.assertTrue([r for r in visti.output if "cancellati | righe=1" in r], visti.output)

    def test_SE_IL_TERMINE_NON_SI_LEGGE_NON_SI_CANCELLA_E_LO_DICE(self):
        import sys
        from unittest import mock
        self.assertEqual(self.registra([_capo(), _familiare()])[0], 200)
        with mock.patch.dict(sys.modules, {"fase185_testi_legali": None}):
            with self.assertLogs("core_auto.server", level="ERROR") as visti:
                esito = self._passata(self.arrivo + datetime.timedelta(days=30))
        self.assertEqual(esito, {"saltata": "senza_termine_promesso"})
        self.assertEqual(len(self.salvati()), 2)
        self.assertIsInstance(visti.records[0].exc_info, tuple, "manca il perche' nel registro")

    def test_SE_L_ARCHIVIO_NON_RISPONDE_DICE_MENO_UNO_E_IL_PERCHE(self):
        from fase127_checkin_digitale import CheckinDigitale
        vuoto = os.path.join(self.d, "senza_tabella.db")       # l'archivio senza lo schema
        ck = CheckinDigitale(lambda: sqlite3.connect(vuoto), None)
        with self.assertLogs("core_auto.checkin_digitale", level="ERROR") as visti:
            self.assertEqual(ck.cancella_dati_scaduti(datetime.date.today(), 2), -1)
        self.assertIsInstance(visti.records[0].exc_info, tuple, "manca il perche' nel registro")

    def test_IL_GIRO_ORARIO_LO_CHIAMA_DAVVERO(self):
        # si legge l'ALBERO SINTATTICO: un commento col nome non deve bastare (S6)
        sorgente = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fase83_server.py")
        with io.open(sorgente, encoding="utf-8") as f:
            albero = ast.parse(f.read())
        avvio = [n for n in ast.walk(albero)
                 if isinstance(n, ast.FunctionDef) and n.name == "servi"]
        self.assertEqual(len(avvio), 1, "la funzione che avvia il server non si trova")
        chiamate = [n for n in ast.walk(avvio[0])
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "checkin_conservazione_una_passata"]
        self.assertTrue(chiamate, "nessun giro periodico cancella i dati del check-in")


class TestIlGiroPartePerDavveroColServer(unittest.TestCase):
    """Il giro orario sta dentro `servi()`, che nessuna prova unitaria esegue: un `is None` al
    posto di `is not None` lo terrebbe spento per sempre, e i dati resterebbero senza che
    nessuno se ne accorga. Qui il server si accende davvero, e il giro deve partire, chiamare
    la cancellazione e restare vivo quando la cancellazione solleva."""

    def test_ACCESO_IL_SERVER_IL_GIRO_PARTE_E_SOPRAVVIVE_A_UN_ERRORE(self):
        import socket
        import threading
        import time
        from unittest import mock
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        nomi = ("MARCA_TEMPORALE", "UPLOAD_DIR", "OUTREACH_OPTOUT_FILE")
        prec = {k: os.environ.get(k) for k in nomi}

        def _ripristina():
            for k, v in prec.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.addCleanup(_ripristina)
        # niente marca temporale in rete, niente pulizia degli upload veri del computer
        os.environ.update(MARCA_TEMPORALE="0", UPLOAD_DIR=d + "/uploads",
                          OUTREACH_OPTOUT_FILE=d + "/optout.json")
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"T" * 32, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_checkin=f"{d}/ck.db"))
        presa = socket.socket()
        presa.bind(("127.0.0.1", 0))
        porta = presa.getsockname()[1]
        presa.close()
        prima = [t for t in threading.enumerate() if t.name == "checkin-conservazione"]

        def _fallito(visti):
            return [r for r in visti.records if "giro di cancellazione fallito" in r.getMessage()]
        with mock.patch.object(fase83_server, "checkin_conservazione_una_passata",
                               side_effect=RuntimeError("giro rotto apposta")):
            with self.assertLogs("core_auto.server", level="ERROR") as visti:
                threading.Thread(target=fase83_server.servi, daemon=True, kwargs=dict(
                    sistema=sis, host="127.0.0.1", porta=porta, cartella_statica=d,
                    host_key="hk", admin_key="ak")).start()
                fine = time.time() + 15
                while time.time() < fine and not _fallito(visti):
                    time.sleep(0.05)
        nuovi = [t for t in threading.enumerate()
                 if t.name == "checkin-conservazione" and t not in prima]
        self.assertEqual(len(nuovi), 1, "il giro di cancellazione non e' partito col server")
        self.assertTrue(_fallito(visti), "il giro non ha chiamato la cancellazione")
        self.assertIsInstance(_fallito(visti)[0].exc_info, tuple, "manca il perche' nel registro")


class TestLInformativaDiceDeiDatiDelCheckin(unittest.TestCase):

    def test_OGNI_LINGUA_NOMINA_LA_LEGGE_E_IL_TERMINE(self):
        import fase185_testi_legali as legale
        lingue = legale.lingue_disponibili("privacy")
        self.assertEqual(len(lingue), 8, lingue)
        for lang in lingue:
            modello = legale._PRIVACY[lang]
            self.assertIn("{GIORNI_CHECKIN}", modello, lang)
            self.assertIn("109", modello, lang)                      # art. 109 TULPS

    def test_IL_TERMINE_SCRITTO_E_QUELLO_DEL_GIRO(self):
        import fase185_testi_legali as legale
        prima = legale.GIORNI_CONSERVAZIONE_CHECKIN
        legale.GIORNI_CONSERVAZIONE_CHECKIN = 97
        try:
            for lang in legale.lingue_disponibili("privacy"):
                self.assertIn("97", legale.testo_privacy(lang), lang)
        finally:
            legale.GIORNI_CONSERVAZIONE_CHECKIN = prima

    def test_L_ITALIANO_NON_DICE_PIU_CHE_NON_TENIAMO_DOCUMENTI(self):
        import fase185_testi_legali as legale
        self.assertNotIn("NON conserviamo documenti d'identita'", legale.testo_privacy("it"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
