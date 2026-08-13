"""
Collaudo — attivazione fase119 (calendario prezzi host): per ogni giorno stato + prezzo base
+ prezzo dinamico suggerito (fase106). Endpoint host-auth con verifica proprietà.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE


class TestCalendarioPrezzi(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{self.d}/c.db", db_inventario=f"{self.d}/i.db",
            db_registro_host=f"{self.d}/r.db", db_accettazioni=f"{self.d}/a.db"))
        self.r = crea_router(self.sys, host_key="hk")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@cp.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "Casa", "citta": "Roma",
                "prezzo_notte_cents": 10000, "capacita": 2}, {"X-Host-Token": self.tok})
        for g in ("2026-09-01", "2026-09-02"):
            self.sys.inventario.imposta_disponibilita("casa", g, unita_totali=1,
                                                      prezzo_netto_cents=10000)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def test_calendario_prezzi(self):
        s, d = self.g("GET", "/api/host/calendario_prezzi", h={"X-Host-Token": self.tok},
                      q={"alloggio": "casa", "da": "2026-09-01", "a": "2026-09-04"})
        self.assertEqual(s, 200, d)
        celle = {c["giorno"]: c for c in d["celle"]}
        self.assertEqual(celle["2026-09-01"]["prezzo_cents"], 10000)
        self.assertIn("prezzo_dinamico_cents", celle["2026-09-01"])
        self.assertEqual(celle["2026-09-01"]["stato"], "libero")
        self.assertEqual(celle["2026-09-03"]["stato"], "non_aperto")   # non caricato

    def test_prenotato_e_chiuso_visibili(self):
        """Bug #33 (provato live): giorno PIENO appariva 'libero' (chiavi
        venduto/occupati inesistenti nella riga fase58) e CHIUSO era ignorato."""
        e = self.sys.inventario.blocca("casa", "2026-09-01", "2026-09-02",
                                       idem_key="t33")
        self.assertTrue(e.ok, e)
        self.sys.inventario.imposta_disponibilita(
            "casa", "2026-09-02", unita_totali=1, prezzo_netto_cents=10000,
            chiuso=True)
        s, d = self.g("GET", "/api/host/calendario_prezzi", h={"X-Host-Token": self.tok},
                      q={"alloggio": "casa", "da": "2026-09-01", "a": "2026-09-04"})
        self.assertEqual(s, 200, d)
        celle = {c["giorno"]: c for c in d["celle"]}
        self.assertEqual(celle["2026-09-01"]["stato"], "prenotato")
        self.assertEqual(celle["2026-09-02"]["stato"], "chiuso")

    def test_occupazione_reale_muove_il_dinamico(self):
        """Il fattore occupazione (fase106) ora usa l'occupazione REALE del range
        (prima era fisso a 5000 bps: non scattava mai)."""
        import fase106_dynamic_pricing as dyn
        e = self.sys.inventario.blocca("casa", "2026-09-01", "2026-09-03",
                                       idem_key="t-occ")           # 2/2 notti: 100%
        self.assertTrue(e.ok, e)
        s, d = self.g("GET", "/api/host/calendario_prezzi", h={"X-Host-Token": self.tok},
                      q={"alloggio": "casa", "da": "2026-09-01", "a": "2026-09-04"})
        self.assertEqual(s, 200, d)
        celle = {c["giorno"]: c for c in d["celle"]}
        atteso = dyn.calcola_prezzo(10000, occupazione_bps=10000,
                                    data="2026-09-01")["prezzo_cents"]
        self.assertEqual(celle["2026-09-01"]["prezzo_dinamico_cents"], atteso)

    def test_stato_range_equivale_a_stato_giorno(self):
        """La vincitrice del benchmark (query unica) deve restituire ESATTAMENTE
        le stesse righe del percorso per-giorno."""
        inv = self.sys.inventario
        per_range = inv.stato_range("casa", "2026-09-01", "2026-09-04")
        for g in ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"):
            self.assertEqual(per_range.get(g), inv.stato_giorno("casa", g))
        self.assertEqual(inv.stato_range("casa", "js;drop", "2026-09-04"), {})

    def test_auth_proprieta_date(self):
        s, _ = self.g("GET", "/api/host/calendario_prezzi",
                      q={"alloggio": "casa", "da": "2026-09-01", "a": "2026-09-04"})
        self.assertEqual(s, 401)                                        # senza auth
        s, _ = self.g("GET", "/api/host/calendario_prezzi", h={"X-Host-Token": self.tok},
                      q={"alloggio": "casa"})
        self.assertEqual(s, 422)                                        # date mancanti
        altro = self.g("POST", "/api/host/registrazione",
                       {"email": "h2@cp.it", "password": "password1", "accetta_termini": True,
                        "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                        "versione": CONTRATTO_HOST_VERSIONE})[1]["token"]
        s, _ = self.g("GET", "/api/host/calendario_prezzi", h={"X-Host-Token": altro},
                      q={"alloggio": "casa", "da": "2026-09-01", "a": "2026-09-04"})
        self.assertEqual(s, 403)                                        # non è tuo


class _Apparecchio:
    """Solo l'apparecchio, senza test dentro: NON eredita da `TestCase`, quindi
    il caricatore non lo raccoglie e i test della classe sopra non vengono
    rieseguiti in ogni sottoclasse. Misurato: ereditando da `TestCalendarioPrezzi`
    la suite passava da 11 a 20 test, cioe' 9 esecuzioni duplicate — ed e'
    esattamente il conteggio gonfiato che l'appendice #14 vieta di esibire."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{self.d}/c.db", db_inventario=f"{self.d}/i.db",
            db_registro_host=f"{self.d}/r.db", db_accettazioni=f"{self.d}/a.db"))
        self.r = crea_router(self.sys, host_key="hk")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@cp.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "Casa", "citta": "Roma",
                "prezzo_notte_cents": 10000, "capacita": 2}, {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})


class TestChiudereNonSvuotaLOccupazione(_Apparecchio, unittest.TestCase):
    """⛔ DIFETTO VIVO, misurato sul router vero il 2026-08-13.

    L'occupazione che alimenta il prezzo dinamico si calcola in
    `fase83_server._host_calendario_prezzi` SALTANDO i giorni `chiuso`, sia al
    numeratore sia al denominatore. Ma «chiuso» e «invenduto» sono due cose
    diverse: chiudere una data GIA' VENDUTA e' pratica normale (l'host smette di
    prendere richieste su una notte che ha gia' dato via), e il prodotto lo
    riconosce gia' — bug #35, «VENDUTA vince su CHIUSA».

    Effetto misurato: 4 notti tutte vendute, prezzo suggerito 14300. Le stesse
    4 notti, sempre vendute, chiuse dall'host: suggerito 11000, cioe' **-23,1%**.
    Se l'host le chiude TUTTE il denominatore va a zero e l'occupazione ripiega
    sul default 5000 bps — «mezzo pieno» — mentre l'alloggio e' pieno al 100%.
    Il danno e' esattamente quello che questa schermata puo' fare: un host che
    ABBASSA il prezzo proprio quando e' pieno.

    DENOMINATORE (appendice #15): i 4 giorni del range, confrontati uno per uno
    prima e dopo la chiusura. Nessun `assertIn` su un totale."""

    GIORNI = ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04")

    def _suggeriti(self):
        s, d = self.g("GET", "/api/host/calendario_prezzi",
                      h={"X-Host-Token": self.tok},
                      q={"alloggio": "casa", "da": self.GIORNI[0], "a": self.GIORNI[-1]})
        self.assertEqual(s, 200, d)
        return {c["giorno"]: c for c in d["celle"]}

    def _carica_le_quattro_notti(self, chiuso=False):
        for g in self.GIORNI:
            self.sys.inventario.imposta_disponibilita(
                "casa", g, unita_totali=1, prezzo_netto_cents=10000, chiuso=chiuso)

    def test_chiudere_date_vendute_non_abbassa_il_suggerito(self):
        self._carica_le_quattro_notti()
        e = self.sys.inventario.blocca("casa", self.GIORNI[0], "2026-09-05",
                                       idem_key="pieno")
        self.assertTrue(e.ok, e)
        prima = self._suggeriti()
        self._carica_le_quattro_notti(chiuso=True)          # l'host chiude il venduto
        dopo = self._suggeriti()
        for g in self.GIORNI:
            self.assertEqual(prima[g]["stato"], "prenotato", g)
            self.assertEqual(dopo[g]["stato"], "prenotato", g)   # bug #35 regge
            self.assertGreaterEqual(
                dopo[g]["prezzo_dinamico_cents"], prima[g]["prezzo_dinamico_cents"],
                "%s: chiudere una notte GIA' VENDUTA ha fatto scendere il "
                "suggerito da %s a %s — l'occupazione non vede il venduto"
                % (g, prima[g]["prezzo_dinamico_cents"],
                   dopo[g]["prezzo_dinamico_cents"]))

    def test_tutto_venduto_e_chiuso_non_ripiega_sul_mezzo_pieno(self):
        """Appendice #9: stesso difetto, input diverso — qui NON esiste nemmeno
        un giorno aperto, quindi il denominatore va a zero e il ripiego a 5000
        bps si vede in chiaro. Confronto contro l'oracolo indipendente
        (collaudo 5): fase106 interrogata a mano con occupazione 10000."""
        import fase106_dynamic_pricing as dyn
        self._carica_le_quattro_notti()
        self.assertTrue(self.sys.inventario.blocca(
            "casa", self.GIORNI[0], "2026-09-05", idem_key="tutto").ok)
        self._carica_le_quattro_notti(chiuso=True)
        celle = self._suggeriti()
        for g in self.GIORNI:
            atteso = dyn.calcola_prezzo(10000, occupazione_bps=10000,
                                        data=g)["prezzo_cents"]
            self.assertEqual(
                celle[g]["prezzo_dinamico_cents"], atteso,
                "%s: alloggio pieno al 100%% e tutte le notti chiuse -> "
                "il server ha suggerito %s invece di %s (ha ripiegato sul "
                "default 'mezzo pieno')"
                % (g, celle[g]["prezzo_dinamico_cents"], atteso))


class TestNienteDuecentoMuto(_Apparecchio, unittest.TestCase):
    """⛔ DIFETTO VIVO, misurato sul router vero il 2026-08-13.

    Un range piu' lungo del tetto (366 giorni), due date invertite o una data
    che non e' una data ricevono tutti **HTTP 200 con `celle: []`** — cioe' la
    stessa identica risposta di «non hai caricato nessuna disponibilita'».
    L'host non puo' distinguere «ho sbagliato a chiedere» da «non ho dati», e
    il pannello disegna un calendario vuoto senza una parola
    (`deploy/host.html:1339`).

    E' il modo di rompersi n.4 («controllo che non controlla») e l'appendice #17
    («il guardiano deve dire cosa ha guardato»): un tetto che scatta in silenzio
    fa sembrare vuoto cio' che non e' stato nemmeno guardato. La rotta sa gia'
    rispondere 422 con un codice parlante — lo fa per le date mancanti — e il
    pannello sa gia' tradurlo (`fraseErrore`).

    DENOMINATORE: le 4 forme di richiesta invalida che oggi tacciono, piu' la
    richiesta valida che deve continuare a rispondere 200."""

    def _chiedi(self, da, a):
        return self.g("GET", "/api/host/calendario_prezzi",
                      h={"X-Host-Token": self.tok},
                      q={"alloggio": "casa", "da": da, "a": a})

    def test_le_quattro_richieste_invalide_non_rispondono_200(self):
        casi = {
            "range oltre il tetto di 366 giorni": ("2026-01-01", "2027-01-03"),
            "range assurdo di dieci anni": ("2026-01-01", "2036-01-01"),
            "date invertite": ("2026-09-04", "2026-09-01"),
            "data che non e' una data": ("pippo", "2026-09-04"),
        }
        muti = []
        for perche, (da, a) in casi.items():
            s, d = self._chiedi(da, a)
            if s == 200:
                muti.append("%s -> 200 %s" % (perche, d))
            else:
                self.assertEqual(s, 422, "%s: atteso 422, ricevuto %s" % (perche, s))
                self.assertTrue(d.get("errore"),
                                "%s: 422 senza codice d'errore" % perche)
        self.assertEqual(muti, [], "richieste invalide accolte in silenzio: %s" % muti)

    def test_la_richiesta_valida_resta_200(self):
        """Regola ferrea 10: l'allarme si prova nelle DUE direzioni. Un tetto che
        rifiuta anche il caso buono e' peggio del tetto assente."""
        s, d = self._chiedi("2026-09-01", "2026-09-04")
        self.assertEqual(s, 200, d)
        self.assertEqual(len(d["celle"]), 4)

    def test_il_confine_del_tetto_passa_dalla_rotta_vera(self):
        """Il confine si prova SUL confine (D4). ⚠️ La prima versione di questo
        collaudo diceva «366 dentro, 367 fuori» ed era FALSA: il tetto guarda la
        differenza fra le date, che e' una notte in meno delle celle. Il range
        piu' lungo accettato ha `.days == 366`, cioe' **367 celle** — misurato,
        ed e' il mutante di riga 26 che l'ha fatto venire fuori."""
        s, d = self._chiedi("2026-01-01", "2027-01-01")
        self.assertEqual((s, len(d["celle"])), (200, 366))
        s, d = self._chiedi("2026-01-01", "2027-01-02")          # ultimo accettato
        self.assertEqual((s, len(d["celle"])), (200, 367))
        s, d = self._chiedi("2026-01-01", "2027-01-03")          # primo rifiutato
        self.assertEqual(s, 422, d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
