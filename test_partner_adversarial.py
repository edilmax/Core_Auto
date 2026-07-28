# -*- coding: utf-8 -*-
"""ADVERSARIAL sul form PARTNER B2B (fase201 + rotta /api/partner).

Non ripete la guardia base (test_fase201_partner.py): qui si ATTACCA.
Cinque fronti, un difetto per test, sempre con l'osservabile FORTE (stato HTTP **e** contenuto
dell'archivio, mai «non e' esploso»):

  1) BOT ad alta frequenza      -> il tetto orario regge, 429 pulito, archivio mai gonfiato
  2) BYPASS della dedup          -> cosa si normalizza davvero e cosa NO (documentato, non finto)
  3) CONSENSO GDPR               -> solo il booleano True vale; ogni forma perversa non scrive
  4) PAYLOAD OSTILI              -> 1MB, NUL, surrogati isolati, SQLi, XSS, JSON annidato: MAI 500
  5) PII a riposo + elenco admin -> in archivio solo i campi previsti; elenco chiuso a chiave

DIFETTI VERI TROVATI QUI E CORRETTI ALLA RADICE (visti ROSSI prima della correzione):
  A. `{"nome": "Mario\\ud800"}` -> surrogato isolato -> UnicodeEncodeError dentro l'INSERT ->
     la rotta pubblica rispondeva **500**. Radice: `_testo`/`_email_ok` accettavano caratteri
     non codificabili in UTF-8. Corretto in fase201 (`_velenoso`, `_email_norm`).
  B. `"n\\u0000ul@example.com"` -> NUL accettato e SCRITTO in archivio (stringa che tronca ogni
     consumatore a valle: CSV, log, librerie C); e `"@x.it"` (nessun destinatario) entrava lo
     stesso. Corretto: spazi interni, caratteri di controllo, surrogati, parte locale vuota,
     doppia chiocciola e dominio senza punto = email_non_valida.
  C. corpo JSON con annidamento profondissimo (`[[[[...`) -> `json.loads` alza RecursionError,
     che NON e' ValueError/TypeError -> risaliva fino al router -> **500**. Radice: `_json` in
     fase83_server ora la cattura -> 400 json_non_valido (vale per TUTTE le rotte POST).

BYPASS DOCUMENTATI E NON «CORRETTI» (scelta consapevole, vedi test_bypass_equivalenti_*):
  i punti di Gmail (p.m@ = pm@), gli alias +tag e i domini sosia unicode restano righe DISTINTE.
  Normalizzarli fonderebbe caselle legittime diverse su provider dove il punto CONTA (RFC 5321:
  la parte locale appartiene al destinatario). Il danno resta comunque limitato dal tetto orario:
  la guardia lo dimostra con i numeri, invece di far finta che il bypass non esista.
"""
import json
import shutil
import sqlite3
import tempfile
import unicodedata
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase201_partner import MAX_CANDIDATURE_ORA, crea_gestore_partner

# --- munizioni ---------------------------------------------------------------------------
SURROGATO = "\ud800"          # meta' di una coppia UTF-16: non codificabile in UTF-8
NUL = "\x00"
ESC = "\x1b"
NBSP = "\u00a0"       # spazio unificatore: sembra spazio, non lo e'
XSS = "<script>alert('x')</script>"
SQLI = "'; DROP TABLE partner; --"
CONSENSI_FINTI = ("true", "True", "on", "si", "1", 1, 1.0, [], {}, [True], {"ok": True},
                  None, 0, False, -1, "", b"true")


class _Bugiardo:
    """Oggetto che MENTE: e' vero in `if`, e' uguale a True con ==, ma non E' True.
    Se il gate del consenso usasse `if not consenso` o `== True`, questo passerebbe."""

    def __bool__(self):
        return True

    def __eq__(self, altro):
        return True

    def __hash__(self):
        return hash(True)


def _righe(percorso):
    con = sqlite3.connect(percorso)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(partner)").fetchall()]
        return cols, con.execute("SELECT * FROM partner").fetchall()
    finally:
        con.close()


class _BaseRotta(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.db = self.d + "/partner.db"
        self.sis = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"h" * 32,
                                              db_partner=self.db))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def post(self, corpo=None, grezzo=None, headers=None):
        body = grezzo if grezzo is not None else (json.dumps(corpo) if corpo is not None else None)
        return self.r.gestisci("POST", "/api/partner", {}, body, headers or {})

    def get_admin(self, headers=None, query=None):
        return self.r.gestisci("GET", "/api/admin/partner", query or {}, None, headers or {})

    def conta_db(self):
        return len(_righe(self.db)[1])


# ============================================================ 1) BOT AD ALTA FREQUENZA
class TestBotAltaFrequenza(_BaseRotta):
    def test_flood_220_post_il_tetto_regge_e_archivio_non_gonfia(self):
        """220 candidature da 220 email diverse in rapida successione: le prime
        MAX_CANDIDATURE_ORA passano, TUTTE le altre sono 429 pulite (mai 500, mai eccezione)
        e l'archivio non supera il tetto neppure di una riga."""
        stati = []
        for i in range(220):
            st, corpo = self.post({"nome": "Bot %d" % i, "email": "bot%d@example.com" % i,
                                   "tipo": "altro", "consenso": True})
            stati.append(st)
            if st == 429:
                self.assertEqual(corpo, {"errore": "riprova_piu_tardi"})
        self.assertEqual(stati.count(500), 0, "la raffica ha prodotto errori interni")
        self.assertEqual(set(stati), {201, 429})
        self.assertEqual(stati.count(201), MAX_CANDIDATURE_ORA)
        self.assertEqual(stati[:MAX_CANDIDATURE_ORA], [201] * MAX_CANDIDATURE_ORA)
        self.assertEqual(stati[MAX_CANDIDATURE_ORA:], [429] * (220 - MAX_CANDIDATURE_ORA))
        self.assertEqual(self.conta_db(), MAX_CANDIDATURE_ORA)   # archivio: esattamente il tetto

    def test_flood_stessa_email_non_moltiplica_le_righe(self):
        """L'altra faccia del bot: 200 invii con la STESSA email. La dedup (PRIMARY KEY) tiene:
        una sola riga, l'ultima versione vince, nessun 500."""
        for i in range(200):
            st, _ = self.post({"nome": "Ripetuto %d" % i, "email": "unico@example.com",
                               "tipo": "creator", "consenso": True})
            self.assertIn(st, (201, 429), "stato non controllato al giro %d" % i)
        cols, righe = _righe(self.db)
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0][cols.index("nome")], "Ripetuto 199")


# ============================================================ 2) BYPASS DELLA DEDUP
class TestBypassDedup(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.o = [1000000]
        self.g = crea_gestore_partner(self.d + "/p.db", orologio=lambda: self.o[0])
        self.g.inizializza_schema()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_varianti_di_forma_della_stessa_email_restano_una_riga(self):
        """Maiuscole e spazi ai BORDI (spazio, tab, a-capo, spazio-unificatore): e' la STESSA
        casella, deve restare UNA riga sola (altrimenti il bot moltiplica la stessa persona)."""
        for variante in ("pm@example.com", "PM@Example.COM", "  pm@example.com  ",
                         "\tPM@EXAMPLE.COM\n", "pm@example.com\n",
                         NBSP + "pm@example.com" + NBSP):
            esito = self.g.registra("Mario Rossi", variante, "agenzia", consenso=True)
            self.assertEqual(esito, {"ok": True}, "rifiutata la variante %r" % variante)
        self.assertEqual(self.g.conta(), 1)
        self.assertEqual(self.g.candidati()[0]["email"], "pm@example.com")

    def test_email_non_spedibili_sono_rifiutate(self):
        """DIFETTO VERO (corretto): un'email con spazio interno, NUL, surrogato o senza
        destinatario passava. Non sono indirizzi spedibili: sono grimaldelli per duplicare la
        stessa casella e, col surrogato, per far esplodere l'INSERT. Nessuna deve entrare."""
        for cattiva in ("p m@example.com", "p\tm@example.com", "pm@exa mple.com",
                        "pm" + NUL + "@example.com", "pm@example.com" + NUL,
                        SURROGATO + "@example.com", "pm@exa" + SURROGATO + "mple.com",
                        "pm" + ESC + "@example.com", "pm" + NBSP + "@example.com",
                        "@example.com", "@.", "pm@example", "pm@example.", "pm@.com",
                        "pm@@example.com", "pm@a@example.com", "pm@example..com"):
            esito = self.g.registra("Mario", cattiva, "altro", consenso=True)
            self.assertEqual(esito, {"errore": "email_non_valida"},
                             "accettata email velenosa %r" % cattiva)
        self.assertEqual(self.g.conta(), 0)

    def test_bypass_equivalenti_documentati_restano_sotto_il_tetto(self):
        """ONESTA': punti Gmail, alias +tag, sottodominio e sosia unicode NON vengono fusi
        (sono righe distinte) - e' una scelta, non una svista: normalizzarli fonderebbe caselle
        legittime diverse. Cio' che DEVE reggere e' il limite del danno: per quante varianti
        inventi, il tetto orario ferma tutto a MAX_CANDIDATURE_ORA righe."""
        varianti = ["p.m@gmail.com", "pm@gmail.com", "p.m.x@gmail.com", "pm+spam@gmail.com",
                    "pm+2@gmail.com", "pm@googlemail.com", "pm@gmail.com.example.com",
                    "рm@gmail.com", "pм@gmail.com"]      # r/m cirillici (sosia)
        varianti += ["v%d.p.m@gmail.com" % i for i in range(50)]
        ok = sum(1 for v in varianti
                 if self.g.registra("Tizio Caio", v, "altro", consenso=True).get("ok"))
        self.assertGreater(len(varianti), MAX_CANDIDATURE_ORA)
        self.assertEqual(ok, MAX_CANDIDATURE_ORA)                # il tetto ha fermato il resto
        self.assertEqual(self.g.conta(), MAX_CANDIDATURE_ORA)
        # e la fusione che DEVE esserci (sola forma) continua a funzionare anche dopo:
        self.o[0] += 3601
        self.g.registra("Tizio Caio", "  P.M@GMAIL.COM ", "altro", consenso=True)
        self.assertEqual(self.g.conta(), MAX_CANDIDATURE_ORA)    # nessuna riga in piu'


# ============================================================ 3) CONSENSO GDPR
class TestConsensoGDPR(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.g = crea_gestore_partner(self.d + "/p.db")
        self.g.inizializza_schema()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_solo_il_booleano_vero_apre_la_porta(self):
        """Ogni forma perversa di «consenso» (stringhe, numeri, contenitori, byte) e perfino un
        oggetto che si finge True (`__bool__`+`__eq__`) NON scrive NULLA."""
        for finto in CONSENSI_FINTI + (_Bugiardo(),):
            esito = self.g.registra("Mario Rossi", "pm@example.com", "creator", consenso=finto)
            self.assertEqual(esito, {"errore": "consenso_richiesto"},
                             "consenso finto accettato: %r" % (finto,))
        self.assertEqual(self.g.conta(), 0)
        self.assertEqual(self.g.registra("Mario Rossi", "pm@example.com", "creator",
                                         consenso=True), {"ok": True})   # il vero True passa
        self.assertEqual(self.g.conta(), 1)

    def test_il_gate_consenso_viene_prima_di_tutto(self):
        """Senza consenso non si scrive nulla NEPPURE quando il resto e' perfetto, e l'errore
        non rivela altro: il consenso e' la PRIMA porta (GDPR: niente base giuridica, niente
        trattamento, nemmeno la validazione dell'email)."""
        esito = self.g.registra("Mario Rossi", "email-senza-chiocciola", "tipo_inesistente",
                                consenso="true")
        self.assertEqual(esito, {"errore": "consenso_richiesto"})
        self.assertEqual(self.g.conta(), 0)


class TestConsensoSullaRotta(_BaseRotta):
    def test_rotta_ogni_consenso_finto_e_422_e_archivio_vuoto(self):
        for finto in CONSENSI_FINTI[:-1]:            # b"true" non e' serializzabile in JSON
            st, corpo = self.post({"nome": "Anna Creator", "email": "anna@example.com",
                                   "tipo": "creator", "consenso": finto})
            self.assertEqual((st, corpo), (422, {"errore": "consenso_richiesto"}),
                             "consenso %r accettato dalla rotta" % (finto,))
        st, corpo = self.post({"nome": "Anna Creator", "email": "anna@example.com",
                               "tipo": "creator"})              # campo del tutto assente
        self.assertEqual((st, corpo), (422, {"errore": "consenso_richiesto"}))
        self.assertEqual(self.conta_db(), 0)


# ============================================================ 4) PAYLOAD OSTILI
class TestPayloadOstili(_BaseRotta):
    STATI_LECITI = (201, 400, 422, 429)

    def test_campi_giganti_1mb_troncati_senza_esplodere(self):
        st, _ = self.post({"nome": "N" * 1000000, "email": "g@example.com", "tipo": "altro",
                           "citta": "C" * 1000000, "messaggio": "M" * 1000000, "consenso": True})
        self.assertEqual(st, 201)
        cols, righe = _righe(self.db)
        r = righe[0]
        self.assertEqual(len(r[cols.index("nome")]), 80)
        self.assertEqual(len(r[cols.index("citta")]), 80)
        self.assertEqual(len(r[cols.index("messaggio")]), 2000)
        st2, _ = self.post({"nome": "Mario Rossi", "email": "e" * 1000000 + "@x.it",
                            "tipo": "altro", "consenso": True})
        self.assertEqual(st2, 422)                                # email fuori misura: respinta
        self.assertEqual(self.conta_db(), 1)

    def test_json_malformato_o_annidato_o_non_oggetto_e_400_mai_500(self):
        """Compreso il DIFETTO VERO corretto: l'annidamento profondo alzava RecursionError
        (non ValueError) e usciva come 500."""
        corpi = ["{non-json", "", "   ", "[1,2,3]", '"stringa"', "123", "null", "true",
                 "{\"a\":", "[" * 30000 + "]" * 30000, "{" * 20000,
                 json.dumps([{"nome": "x"}]), "\x00{}"]
        for grezzo in corpi:
            st, corpo = self.post(grezzo=grezzo)
            self.assertEqual(st, 400, "corpo %r -> %s" % (grezzo[:40], st))
            self.assertEqual(corpo, {"errore": "json_non_valido"})
        self.assertEqual(self.conta_db(), 0)

    def test_surrogati_e_caratteri_di_controllo_mai_in_archivio_mai_500(self):
        """DIFETTO VERO (corretto): il surrogato isolato faceva 500 sull'INSERT. Ora il testo
        arriva ripulito, l'archivio resta leggibile e la risposta admin resta serializzabile."""
        st, _ = self.post(grezzo=json.dumps(
            {"nome": "Mario\ud800 Rossi\x00", "email": "clean@example.com", "tipo": "creator",
             "citta": "Roma\x1b\udfff", "messaggio": "riga1\nriga2\x07\ud83d",
             "consenso": True}))
        self.assertEqual(st, 201)
        cols, righe = _righe(self.db)
        testo = "".join(str(v) for v in righe[0])
        self.assertEqual([c for c in testo if unicodedata.category(c) == "Cs"], [])
        self.assertEqual([c for c in testo if unicodedata.category(c) == "Cc"
                          and c not in "\t\n"], [])
        self.assertEqual(righe[0][cols.index("nome")], "Mario Rossi")
        self.assertIn("\n", righe[0][cols.index("messaggio")])       # l'a-capo lecito resta
        st2, corpo2 = self.get_admin({"X-Admin-Key": "ak"})
        self.assertEqual(st2, 200)
        json.dumps(corpo2, ensure_ascii=False).encode("utf-8")       # nessun surrogato residuo
        # solo veleno nel nome -> nome vuoto -> rifiuto controllato, non riga sporca
        st3, corpo3 = self.post(grezzo=json.dumps(
            {"nome": "\ud800\x00", "email": "solo@veleno.it", "tipo": "creator",
             "consenso": True}))
        self.assertEqual((st3, corpo3), (422, {"errore": "nome_non_valido"}))
        self.assertEqual(self.conta_db(), 1)

    def test_sqli_e_xss_restano_dati_inerti(self):
        st, _ = self.post({"nome": SQLI, "email": "inerte@example.com", "tipo": "altro",
                           "citta": XSS, "messaggio": "1' OR '1'='1", "consenso": True})
        self.assertEqual(st, 201)
        cols, righe = _righe(self.db)
        self.assertEqual(len(righe), 1)                              # tabella VIVA, non «DROP»
        self.assertEqual(righe[0][cols.index("nome")], SQLI[:80])    # salvato alla lettera
        self.assertEqual(righe[0][cols.index("citta")], XSS)
        st2, corpo2 = self.get_admin({"X-Admin-Key": "ak"})
        self.assertEqual(corpo2["candidati"][0]["citta"], XSS)       # dato, non codice
        self.assertIsInstance(corpo2["candidati"], list)
        # e l'email con apice non apre nulla: e' un dato qualunque, la tabella resta viva
        st3, _ = self.post({"nome": "Mario Rossi", "email": "a'--@x.it", "tipo": "altro",
                            "consenso": True})
        self.assertIn(st3, self.STATI_LECITI)
        self.assertEqual(len(_righe(self.db)[1]), 2 if st3 == 201 else 1)

    def test_tipi_json_assurdi_al_posto_dei_campi_mai_500(self):
        veleni = [
            {"nome": {"a": 1}, "email": ["x@y.it"], "tipo": ["creator"], "consenso": True},
            {"nome": 42, "email": 42, "tipo": 42, "consenso": True},
            {"nome": None, "email": None, "tipo": None, "consenso": True},
            {"nome": "Mario Rossi", "email": "t@y.it", "tipo": "creator",
             "citta": {"n": [1, {"z": 2}]}, "messaggio": [1, 2, 3], "consenso": True},
            {"nome": ["Mario"], "email": "l@y.it", "tipo": "creator", "consenso": True},
            {"nome": "Mario Rossi", "email": "u@y.it", "tipo": "CREATOR", "consenso": True},
            {"nome": "Mario Rossi", "email": "v@y.it", "tipo": " creator ", "consenso": True},
            {"nome": "Mario Rossi", "email": "@.", "tipo": "creator", "consenso": True},
            {"nome": "Mario Rossi", "email": "@x.it", "tipo": "creator", "consenso": True},
            {"nome": "Mario Rossi", "email": "a@b", "tipo": "creator", "consenso": True},
        ]
        for v in veleni:
            st, corpo = self.post(v)
            self.assertIn(st, self.STATI_LECITI, "payload %r -> %s" % (v, st))
            self.assertIsInstance(corpo, dict)
            if st != 201:
                self.assertIn("errore", corpo)
        # una sola candidatura era davvero valida: le altre 9 non hanno lasciato traccia
        cols, righe = _righe(self.db)
        self.assertEqual(sorted(r[cols.index("email")] for r in righe), ["t@y.it"])


# ============================================================ 5) PII A RIPOSO + ELENCO ADMIN
class TestPIIaRiposoEAccesso(_BaseRotta):
    SPIE = {"ip": "203.0.113.77", "user_agent": "Mozilla/5.0 SpiaBot",
            "telefono": "+39 333 1234567", "iban": "IT60X0542811101000000123456",
            "password": "segretissima", "codice_fiscale": "RSSMRA80A01H501U",
            "carta": "4242424242424242", "note_interne": "profilo psicologico"}

    def test_in_archivio_finiscono_solo_i_campi_previsti(self):
        st, _ = self.post(dict({"nome": "Mario Rossi", "email": "pii@example.com",
                                "tipo": "property_manager", "citta": "Roma",
                                "messaggio": "ciao", "consenso": True}, **self.SPIE),
                          headers={"X-Forwarded-For": self.SPIE["ip"],
                                   "User-Agent": self.SPIE["user_agent"]})
        self.assertEqual(st, 201)
        con = sqlite3.connect(self.db)
        try:
            tabelle = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            cols = [r[1] for r in con.execute("PRAGMA table_info(partner)").fetchall()]
            righe = con.execute("SELECT * FROM partner").fetchall()
        finally:
            con.close()
        self.assertEqual(tabelle, ["partner"])
        self.assertEqual(cols, ["email", "nome", "tipo", "citta", "messaggio", "consenso", "ts"])
        contenuto = "".join(str(v) for v in righe[0])
        for etichetta, valore in self.SPIE.items():
            self.assertNotIn(valore, contenuto, "PII non prevista in archivio: %s" % etichetta)

    def test_nessuna_riga_puo_esistere_senza_consenso_registrato(self):
        for i in range(5):
            self.post({"nome": "Mario %d" % i, "email": "c%d@example.com" % i,
                       "tipo": "altro", "consenso": True})
        self.post({"nome": "Furbo", "email": "furbo@example.com", "tipo": "altro",
                   "consenso": "true"})
        con = sqlite3.connect(self.db)
        try:
            senza = con.execute("SELECT COUNT(*) FROM partner WHERE consenso != 1").fetchone()[0]
            tot = con.execute("SELECT COUNT(*) FROM partner").fetchone()[0]
        finally:
            con.close()
        self.assertEqual((tot, senza), (5, 0))

    def test_elenco_admin_chiuso_a_chiave_anche_quasi_giusta(self):
        self.post({"nome": "Mario Rossi", "email": "seg@example.com", "tipo": "altro",
                   "citta": "Roma", "consenso": True})
        chiavi = [{}, {"X-Admin-Key": ""}, {"X-Admin-Key": "ak "}, {"X-Admin-Key": " ak"},
                  {"X-Admin-Key": "AK"}, {"X-Admin-Key": "a"}, {"X-Admin-Key": "ak" + NUL},
                  {"X-Admin-Key": "ak" + SURROGATO}, {"X-Admin-Key": SURROGATO},
                  {"X-Admin-Key": "ak\n"}, {"X-Admin-Key": "ak" * 5000},
                  {"X-Admin-Op": "op|x@y.it|admin|99999999999|n|deadbeef"},
                  {"X-Host-Token": "hk"}, {"X-Admin-Key": "hk"}]
        for h in chiavi:
            st, corpo = self.get_admin(h)
            self.assertEqual(st, 401, "chiave %r ha aperto l'elenco" % h)
            self.assertEqual(corpo, {"errore": "non_autorizzato"})
            self.assertNotIn("seg@example.com", json.dumps(corpo))   # nessuna fuga di PII
        st, corpo = self.get_admin({"X-Admin-Key": "ak"})            # la chiave vera apre
        self.assertEqual(st, 200)
        self.assertEqual(corpo["candidati"][0]["email"], "seg@example.com")

    def test_bruteforce_da_un_ip_non_chiude_fuori_admin_onesto(self):
        """Il buttafuori per IP e' un'arma a doppio taglio: deve fermare chi indovina la
        chiave a raffica SENZA diventare un DoS sull'admin vero che lavora da un altro IP."""
        for _ in range(12):
            st, _ = self.get_admin({"X-Admin-Key": "sbagliata", "X-Forwarded-For": "198.51.100.9"})
            self.assertEqual(st, 401)
        st_bloccato, _ = self.get_admin({"X-Admin-Key": "ak", "X-Forwarded-For": "198.51.100.9"})
        self.assertEqual(st_bloccato, 401)                       # l'IP che martella resta fuori
        st_onesto, corpo = self.get_admin({"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.5"})
        self.assertEqual(st_onesto, 200)                         # l'admin vero lavora
        self.assertIn("candidati", corpo)

    def test_parametro_limite_ostile_non_rompe_e_resta_limitato(self):
        for i in range(3):
            self.post({"nome": "Mario %d" % i, "email": "l%d@example.com" % i,
                       "tipo": "altro", "consenso": True})
        for limite in ("abc", "-5", "0", "1e9", "999999999", "9" * 400, "", "2.5",
                       "1;DROP TABLE partner", SURROGATO, "0x10", "-0"):
            st, corpo = self.get_admin({"X-Admin-Key": "ak"}, {"limite": limite})
            self.assertEqual(st, 200, "limite %r -> %s" % (limite, st))
            self.assertEqual(corpo["totale"], 3)
            self.assertLessEqual(len(corpo["candidati"]), 1000)
            self.assertGreaterEqual(len(corpo["candidati"]), 1)


if __name__ == "__main__":
    unittest.main()
