# -*- coding: utf-8 -*-
"""COPERTURA SUI MODULI CRITICI (denaro + sicurezza) — i RAMI D'ERRORE mai eseguiti.

Perche' esiste. La copertura totale (82,5%) e' una MEDIA: nasconde i buchi. Sui dieci
moduli che toccano DENARO e SICUREZZA restavano centinaia di righe che nessun test
attraversava, e sono quasi tutte la stessa famiglia: **i percorsi di errore**. E' li'
che si annidano i difetti, perche' sono gli unici che nessuno prova a mano.

Cosa NON e' questo file: un attraversamento. Ogni ramo qui e' verificato per il
COMPORTAMENTO promesso dal modulo in quel ramo — valore esatto di ritorno, chiavi e
tipi, e soprattutto **l'effetto sullo stato** (nessuna scrittura parziale, nessun
denaro fantasma, nessun conteggio gonfiato). Un `assertFalse` senza il controllo dello
stato sarebbe un finto verde.

Attrezzo comune: `_Fabbrica` + `_ConnRotta` — una connessione SQLite VERA che rompe
(sqlite3.OperationalError) solo le istruzioni scelte. E' iniezione di guasto reale sul
database, non un mock del modulo: il codice sotto test e' quello di produzione, intero.
"""
import ast
import base64
import hashlib
import hmac
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

import fase185_testi_legali as legali
from fase131_payout_dashboard import PayoutDashboard, crea_payout_dashboard
from fase147_tassa_comunale import TassaComunale, crea_tassa_comunale
from fase162_pagamenti_pendenti import PagamentiPendenti
from fase177_financial_controller import (FinancialController,
                                          crea_financial_controller)
from fase183_carta_offsession import ProviderCarta, crea_provider_carta
from fase185_testi_legali import documento
from fase191_blocco_globale import crea_blocco_globale
from fase192_admin_accounts import AdminAccounts, crea_admin_accounts

QUI = os.path.dirname(os.path.abspath(__file__))


# ═══════════════════════════════════════════════════════════════════════════════
#  ATTREZZO: connessione SQLite vera che ROMPE le istruzioni scelte
# ═══════════════════════════════════════════════════════════════════════════════
class _ConnRotta:
    """Avvolge una connessione VERA. Solleva sqlite3.OperationalError su ogni
    istruzione il cui testo contiene uno dei frammenti (dalla `salta`+1-esima in poi).
    `riscrivi` permette di alterare l'SQL (per forzare rowcount=0 e simulare una CAS
    persa senza toccare il codice di produzione)."""

    def __init__(self, con, frammenti=(), salta=0, riscrivi=None, contatore=None):
        object.__setattr__(self, "_con", con)
        object.__setattr__(self, "_fr", tuple(frammenti))
        object.__setattr__(self, "_salta", salta)
        object.__setattr__(self, "_riscrivi", riscrivi)
        object.__setattr__(self, "_cnt", contatore if contatore is not None else {"n": 0})

    def execute(self, sql, *a, **k):
        for f in self._fr:
            if f in sql:
                self._cnt["n"] += 1
                if self._cnt["n"] > self._salta:
                    raise sqlite3.OperationalError("guasto simulato su: %s" % f)
        if self._riscrivi is not None:
            sql = self._riscrivi(sql)
        return self._con.execute(sql, *a, **k)

    def close(self):
        pass

    def __enter__(self):
        return self._con.__enter__()

    def __exit__(self, *a):
        return self._con.__exit__(*a)

    def __getattr__(self, n):
        return getattr(self._con, n)

    def __setattr__(self, n, v):
        setattr(self._con, n, v)


class _Fabbrica:
    """conn_factory riconfigurabile a caldo: si crea l'oggetto sano, si popola, e solo
    DOPO si accende il guasto sulla singola istruzione che interessa."""

    def __init__(self, con):
        self.con = con
        self.frammenti = ()
        self.salta = 0
        self.riscrivi = None
        self.contatore = {"n": 0}

    def rompi(self, *frammenti, **kw):
        self.frammenti = frammenti
        self.salta = kw.get("salta", 0)
        self.contatore = {"n": 0}

    def sana(self):
        self.frammenti = ()
        self.salta = 0
        self.riscrivi = None

    def __call__(self):
        return _ConnRotta(self.con, self.frammenti, self.salta, self.riscrivi,
                          self.contatore)


def _memoria(row=False):
    con = sqlite3.connect(":memory:", check_same_thread=False)
    if row:
        con.row_factory = sqlite3.Row
    return con


# ═══════════════════════════════════════════════════════════════════════════════
#  fase191 — KILL-SWITCH GLOBALE: i rami di guasto NON devono congelare i soldi
# ═══════════════════════════════════════════════════════════════════════════════
class TestBloccoGlobaleRamiDErrore(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.flag = os.path.join(self.d, "blocco.flag")
        self.ENV = "TEST_BLOCCO_COPERTURA"
        os.environ.pop(self.ENV, None)
        self.b = crea_blocco_globale(self.flag, env_var=self.ENV)

    def tearDown(self):
        os.environ.pop(self.ENV, None)
        shutil.rmtree(self.d, ignore_errors=True)

    def test_glitch_filesystem_e_FAIL_OPEN_ma_lenv_resta_autorevole(self):
        """Il flag non e' leggibile (disco in avaria): NON si congela l'attivita' per un
        errore passeggero. L'ENV pero' e' autorevole e non dipende dal file."""
        self.b.imposta(True, motivo="prova", chi="test")
        with mock.patch("fase191_blocco_globale.os.path.exists",
                        side_effect=OSError("EIO: disco non leggibile")):
            self.assertIs(self.b.attivo(), False)          # FAIL-OPEN
            st = self.b.stato()
            self.assertEqual(st, {"attivo": False, "env": False,
                                  "runtime": False, "dettaglio": None})
            os.environ[self.ENV] = "1"
            self.assertIs(self.b.attivo(), True)           # env: autorevole comunque
            self.assertIs(self.b.stato()["env"], True)
        # tolto il guasto, il flag su disco torna a valere
        os.environ.pop(self.ENV, None)
        self.assertIs(self.b.attivo(), True)

    def test_spegnere_un_interruttore_gia_spento_e_idempotente(self):
        """`imposta(False)` senza file: non c'e' niente da togliere -> True, nessun file
        creato, e nessun errore."""
        self.assertFalse(os.path.exists(self.flag))
        self.assertIs(self.b.imposta(False), True)
        self.assertFalse(os.path.exists(self.flag))
        self.assertIs(self.b.attivo(), False)

    def test_flag_non_scrivibile_ritorna_False_e_NON_congela(self):
        """Cartella inesistente: la scrittura fallisce. Deve dirlo (False) e lasciare lo
        stato invariato — mai fingere di aver congelato."""
        b = crea_blocco_globale(os.path.join(self.d, "mai", "esistita", "b.flag"),
                                env_var=self.ENV)
        self.assertIs(b.imposta(True, motivo="x", chi="y"), False)
        self.assertIs(b.attivo(), False)
        self.assertEqual(b.stato()["dettaglio"], None)

    def test_flag_corrotto_congela_lo_stesso_ma_senza_dettaglio(self):
        """Il file c'e' ma il contenuto e' illeggibile: il freeze RESTA in vigore
        (l'esistenza del flag e' il segnale), il dettaglio per l'audit e' None."""
        with io.open(self.flag, "w", encoding="utf-8") as f:
            f.write("{questo non e' json")
        st = self.b.stato()
        self.assertEqual(st["attivo"], True)
        self.assertEqual(st["runtime"], False)
        self.assertIsNone(st["dettaglio"])
        self.assertIs(self.b.attivo(), True)

    def test_modalita_solo_env_nessuna_leva_a_caldo(self):
        b = crea_blocco_globale("", env_var=self.ENV)
        self.assertIs(b.imposta(True, motivo="x"), False)
        self.assertIs(b.attivo(), False)
        os.environ[self.ENV] = "1"
        self.assertIs(b.attivo(), True)


# ═══════════════════════════════════════════════════════════════════════════════
#  fase192 — ACCOUNT OPERATORE: validazioni, DB in avaria, email sconosciuta
# ═══════════════════════════════════════════════════════════════════════════════
class TestAdminAccountsRamiDErrore(unittest.TestCase):
    def setUp(self):
        self.fab = _Fabbrica(_memoria())
        self.a = AdminAccounts(self.fab)

    def test_pragma_wal_non_supportato_non_impedisce_di_lavorare(self):
        fab = _Fabbrica(_memoria())
        fab.rompi("PRAGMA journal_mode")
        a = AdminAccounts(fab)                     # lo schema nasce lo stesso
        self.assertEqual(a.crea("op@x.it", "passwordlunga", "supporto"),
                         {"ok": True, "email": "op@x.it", "ruolo": "supporto"})
        self.assertEqual(a.verifica("op@x.it", "passwordlunga")["ruolo"], "supporto")

    def test_crea_rifiuta_e_NON_scrive_nulla(self):
        casi = [(("senza-chiocciola", "passwordlunga", "admin"), "email_non_valida"),
                (("", "passwordlunga", "admin"), "email_non_valida"),
                (("op@x.it", "corta", "admin"), "password_troppo_corta"),
                (("op@x.it", 12345678, "admin"), "password_troppo_corta"),
                (("op@x.it", "passwordlunga", "superadmin"), "ruolo_non_valido")]
        for args, errore in casi:
            self.assertEqual(self.a.crea(*args), {"ok": False, "errore": errore},
                             "input %r" % (args,))
        self.assertEqual(self.a.lista(), [])       # ZERO righe scritte

    def test_crea_con_db_in_avaria_dice_db_e_non_lascia_account(self):
        self.fab.rompi("INSERT OR REPLACE INTO admin_account")
        self.assertEqual(self.a.crea("op@x.it", "passwordlunga", "admin"),
                         {"ok": False, "errore": "db"})
        self.fab.sana()
        self.assertEqual(self.a.lista(), [])
        # e nessuna porta si e' aperta per sbaglio
        self.assertEqual(self.a.verifica("op@x.it", "passwordlunga"),
                         {"ok": False, "errore": "credenziali_non_valide"})

    def test_login_di_email_mai_registrata(self):
        """Nessun account: stesso messaggio del password sbagliata (niente enumerazione)."""
        self.a.crea("vero@x.it", "passwordlunga", "admin")
        self.assertEqual(self.a.verifica("mai@x.it", "passwordlunga"),
                         {"ok": False, "errore": "credenziali_non_valide"})
        self.assertEqual(self.a.verifica("vero@x.it", "sbagliatissima"),
                         {"ok": False, "errore": "credenziali_non_valide"})

    def test_login_con_db_in_avaria_NEGA(self):
        """Fail-closed: se non si puo' leggere l'account, non si entra."""
        self.a.crea("op@x.it", "passwordlunga", "admin")
        self.fab.rompi("SELECT salt, pw_hash, ruolo, attivo FROM admin_account")
        self.assertEqual(self.a.verifica("op@x.it", "passwordlunga"),
                         {"ok": False, "errore": "credenziali_non_valide"})

    def test_ruolo_attivo_con_db_in_avaria_e_None(self):
        self.a.crea("op@x.it", "passwordlunga", "admin")
        self.assertEqual(self.a.ruolo_attivo("op@x.it"), "admin")
        self.fab.rompi("SELECT ruolo, attivo FROM admin_account")
        self.assertIsNone(self.a.ruolo_attivo("op@x.it"))   # fail-closed

    def test_imposta_ruolo_rifiuta_ruolo_ignoto_e_db_rotto(self):
        self.a.crea("op@x.it", "passwordlunga", "supporto")
        self.assertIs(self.a.imposta_ruolo("op@x.it", "dio"), False)
        self.assertEqual(self.a.ruolo_attivo("op@x.it"), "supporto")   # invariato
        self.assertIs(self.a.imposta_ruolo("mai@x.it", "admin"), False)  # nessuna riga
        self.fab.rompi("UPDATE admin_account SET ruolo=")
        self.assertIs(self.a.imposta_ruolo("op@x.it", "admin"), False)
        self.fab.sana()
        self.assertEqual(self.a.ruolo_attivo("op@x.it"), "supporto")   # ancora invariato

    def test_revoca_e_riattiva_su_account_inesistente_e_su_db_rotto(self):
        self.assertIs(self.a.revoca("mai@x.it"), False)
        self.assertIs(self.a.riattiva("mai@x.it"), False)
        self.a.crea("op@x.it", "passwordlunga", "admin")
        self.fab.rompi("UPDATE admin_account SET attivo=0")
        self.assertIs(self.a.revoca("op@x.it"), False)
        self.fab.sana()
        self.assertEqual(self.a.verifica("op@x.it", "passwordlunga")["ok"], True)
        self.assertIs(self.a.revoca("op@x.it"), True)
        self.assertEqual(self.a.verifica("op@x.it", "passwordlunga"),
                         {"ok": False, "errore": "account_revocato"})
        self.fab.rompi("UPDATE admin_account SET attivo=1")
        self.assertIs(self.a.riattiva("op@x.it"), False)
        self.fab.sana()
        self.assertEqual(self.a.verifica("op@x.it", "passwordlunga"),
                         {"ok": False, "errore": "account_revocato"})   # ancora revocato

    def test_lista_con_db_in_avaria_e_vuota_mai_esplode(self):
        self.a.crea("op@x.it", "passwordlunga", "admin")
        self.assertEqual(len(self.a.lista()), 1)
        self.fab.rompi("SELECT email, ruolo, attivo, creato_ts, creato_da")
        self.assertEqual(self.a.lista(), [])

    def test_factory_su_memoria_e_su_file_vero(self):
        a = crea_admin_accounts(":memory:", orologio=lambda: 42)
        self.assertEqual(a.crea("op@x.it", "passwordlunga", "admin")["ok"], True)
        self.assertEqual(a.lista()[0]["creato_ts"], 42)
        d = tempfile.mkdtemp()
        try:
            b = crea_admin_accounts(os.path.join(d, "admin.db"))
            b.crea("op@x.it", "passwordlunga", "supporto")
            self.assertEqual(b.verifica("OP@X.IT", "passwordlunga")["ruolo"], "supporto")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_lista_non_espone_mai_salt_ne_hash(self):
        self.a.crea("op@x.it", "passwordlunga", "admin", creato_da="super")
        riga = self.a.lista()[0]
        self.assertEqual(sorted(riga.keys()),
                         ["attivo", "creato_da", "creato_ts", "email", "ruolo"])
        self.assertEqual(riga["creato_da"], "super")


# ═══════════════════════════════════════════════════════════════════════════════
#  fase147 — TASSA COMUNALE: DB in avaria = mai una tassa inventata, mai persa muta
# ═══════════════════════════════════════════════════════════════════════════════
class TestTassaComunaleRamiDErrore(unittest.TestCase):
    def setUp(self):
        self.fab = _Fabbrica(_memoria())
        self.t = TassaComunale(self.fab, orologio=lambda: 1000)
        self.t.inizializza_schema()
        self.t.imposta_regola("roma", {"ppn_cents": 500, "max_notti": 10})

    def test_pragma_wal_non_supportato_non_ferma_il_registro(self):
        fab = _Fabbrica(_memoria())
        fab.rompi("PRAGMA journal_mode")
        t = TassaComunale(fab, orologio=lambda: 7)
        t.inizializza_schema()
        self.assertIs(t.imposta_regola("roma", {"ppn_cents": 300}), True)
        self.assertEqual(t.applica("roma", 2, 3), 1800)

    def test_imposta_regola_rifiuta_input_e_db_rotto_senza_toccare_la_regola(self):
        self.assertIs(self.t.imposta_regola("", {"ppn_cents": 1}), False)
        self.assertIs(self.t.imposta_regola("roma", "non-un-dizionario"), False)
        self.fab.rompi("INSERT OR REPLACE INTO tassa_regola")
        self.assertIs(self.t.imposta_regola("roma", {"ppn_cents": 99999}), False)
        self.fab.sana()
        self.assertEqual(self.t.regola("roma"), {"ppn_cents": 500, "max_notti": 10})

    def test_regola_illeggibile_vale_ZERO_mai_una_tassa_inventata(self):
        self.fab.rompi("SELECT regola_json FROM tassa_regola")
        self.assertEqual(self.t.regola("roma"),
                         {"ppn_cents": 0, "max_notti": 0, "perc_bps": 0,
                          "cap_persona_cents": 0})
        self.assertEqual(self.t.applica("roma", 4, 5), 0)   # comune ignoto -> ZERO

    def test_riscossione_con_db_rotto_dice_False_e_non_conta_nulla(self):
        self.fab.rompi("VALUES (?,?,?,?,0)")
        self.assertIs(self.t.registra_riscossione("P1", "roma", 1500), False)
        self.fab.sana()
        self.assertEqual(self.t.totale_riscosso("roma"), 0)
        # il retry del webhook riasserisce: nessuna perdita definitiva
        self.assertIs(self.t.registra_riscossione("P1", "roma", 1500), True)
        self.assertEqual(self.t.totale_riscosso("roma"), 1500)

    def test_storna_rifiuta_id_non_stringa(self):
        for cattivo in (None, 123, b"P1", "", ["P1"]):
            self.assertIs(self.t.storna(cattivo), False, repr(cattivo))

    def test_storna_con_db_rotto_dice_False_e_la_tassa_resta_dovuta(self):
        self.t.registra_riscossione("P1", "roma", 1500)
        self.fab.rompi("ON CONFLICT(prenotazione_id) DO UPDATE")
        self.assertIs(self.t.storna("P1"), False)
        self.fab.sana()
        self.assertEqual(self.t.totale_riscosso("roma"), 1500)   # NON stornata a meta'
        self.assertIs(self.t.storna("P1"), True)
        self.assertEqual(self.t.totale_riscosso("roma"), 0)

    def test_tombstone_respinge_la_riscossione_tardiva(self):
        self.assertIs(self.t.storna("P9"), True)                 # storno prima dell'incasso
        self.assertIs(self.t.registra_riscossione("P9", "roma", 900), True)
        self.assertEqual(self.t.totale_riscosso("roma"), 0)      # NON risorge

    def test_factory_su_file_vero(self):
        d = tempfile.mkdtemp()
        try:
            t = crea_tassa_comunale(os.path.join(d, "tassa.db"), orologio=lambda: 5)
            t.inizializza_schema()
            t.imposta_regola("Milano", {"ppn_cents": 200})
            self.assertEqual(t.applica("MILANO", 3, 2), 1200)
            self.assertIs(t.registra_riscossione("P1", "Milano", 1200), True)
            self.assertEqual(t.totale_riscosso("milano"), 1200)
        finally:
            shutil.rmtree(d, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  fase183 — CARTA OFF-SESSION: ogni esito Stripe ha un significato preciso
# ═══════════════════════════════════════════════════════════════════════════════
class _Fetch:
    """fetch iniettabile: registra le chiamate e risponde secondo una tabella."""

    def __init__(self, risposte=None, esplode=False):
        self.risposte = risposte or {}
        self.esplode = esplode
        self.chiamate = []

    def __call__(self, metodo, url, body, headers):
        self.chiamate.append({"metodo": metodo, "url": url, "body": body,
                              "headers": headers})
        if self.esplode:
            raise OSError("rete giu'")
        for chiave, valore in self.risposte.items():
            if chiave in url:
                if isinstance(valore, Exception):
                    raise valore
                return valore
        return {}


class TestCartaOffSessionRamiDErrore(unittest.TestCase):
    def test_factory_gated_senza_chiave_e_dormiente(self):
        for vuota in (None, "", "   ", 123):
            self.assertIsNone(crea_provider_carta(vuota))
        self.assertIsInstance(crea_provider_carta("sk_test_x"), ProviderCarta)

    def test_link_carta_senza_email_non_manda_customer_email(self):
        f = _Fetch({"/checkout/sessions": {"url": "https://pay/setup"}})
        p = ProviderCarta("sk_x", fetch=f)
        self.assertEqual(p.crea_link_carta(host_id="h1"), "https://pay/setup")
        corpo = f.chiamate[0]["body"].decode("utf-8")
        self.assertNotIn("customer_email", corpo)
        self.assertIn("metadata%5Bhost_id%5D=h1", corpo)
        self.assertIn("mode=setup", corpo)
        # con email valida invece c'e'
        f2 = _Fetch({"/checkout/sessions": {"url": "https://pay/setup"}})
        ProviderCarta("sk_x", fetch=f2).crea_link_carta(host_id="h1", email="a@b.it")
        self.assertIn("customer_email=a%40b.it", f2.chiamate[0]["body"].decode("utf-8"))
        # email senza chiocciola: NON viene mandata
        f3 = _Fetch({"/checkout/sessions": {"url": "https://pay/setup"}})
        ProviderCarta("sk_x", fetch=f3).crea_link_carta(host_id="h1", email="pippo")
        self.assertNotIn("customer_email", f3.chiamate[0]["body"].decode("utf-8"))

    def test_link_carta_con_stripe_giu_e_None(self):
        p = ProviderCarta("sk_x", fetch=_Fetch(esplode=True))
        self.assertIsNone(p.crea_link_carta(host_id="h1"))
        # risposta senza url -> None (mai un link finto)
        p2 = ProviderCarta("sk_x", fetch=_Fetch({"/checkout/sessions": {"id": "cs_1"}}))
        self.assertIsNone(p2.crea_link_carta(host_id="h1"))

    def test_dettagli_da_sessione_tutti_i_modi_di_non_avere_la_carta(self):
        # 1) risposta non-oggetto
        p = ProviderCarta("sk_x", fetch=_Fetch({"/checkout/sessions/": ["non", "dict"]}))
        self.assertIsNone(p.dettagli_da_sessione("cs_1"))
        # 2) sessione senza setup_intent -> niente payment_method -> None
        p = ProviderCarta("sk_x", fetch=_Fetch({"/checkout/sessions/":
                                                {"customer": "cus_1"}}))
        self.assertIsNone(p.dettagli_da_sessione("cs_1"))
        # 3) setup_intent presente ma senza pm -> None
        p = ProviderCarta("sk_x", fetch=_Fetch({
            "/checkout/sessions/": {"customer": "cus_1", "setup_intent": "seti_1"},
            "/setup_intents/": {"id": "seti_1"}}))
        self.assertIsNone(p.dettagli_da_sessione("cs_1"))
        # 4) rete giu' -> None
        self.assertIsNone(ProviderCarta("sk_x", fetch=_Fetch(esplode=True))
                          .dettagli_da_sessione("cs_1"))
        # 5) completo -> gli id opachi, e SOLO quelli
        p = ProviderCarta("sk_x", fetch=_Fetch({
            "/checkout/sessions/": {"customer": "cus_1", "setup_intent": "seti_1"},
            "/setup_intents/": {"payment_method": "pm_1"}}))
        self.assertEqual(p.dettagli_da_sessione("cs_1"),
                         {"customer": "cus_1", "payment_method": "pm_1"})

    def test_dettagli_pagamento_da_sessione_tutti_i_rami(self):
        p = ProviderCarta("sk_x", fetch=_Fetch({"/checkout/sessions/": "non-dict"}))
        self.assertIsNone(p.dettagli_pagamento_da_sessione("cs_1"))
        p = ProviderCarta("sk_x", fetch=_Fetch({"/checkout/sessions/":
                                                {"customer": "cus_1"}}))
        self.assertIsNone(p.dettagli_pagamento_da_sessione("cs_1"))   # niente payment_intent
        p = ProviderCarta("sk_x", fetch=_Fetch({
            "/checkout/sessions/": {"customer": "cus_1", "payment_intent": "pi_1"},
            "/payment_intents/": {"id": "pi_1"}}))
        self.assertIsNone(p.dettagli_pagamento_da_sessione("cs_1"))   # pm assente
        self.assertIsNone(ProviderCarta("sk_x", fetch=_Fetch(esplode=True))
                          .dettagli_pagamento_da_sessione("cs_1"))
        p = ProviderCarta("sk_x", fetch=_Fetch({
            "/checkout/sessions/": {"customer": "cus_9", "payment_intent": "pi_9"},
            "/payment_intents/": {"payment_method": "pm_9"}}))
        self.assertEqual(p.dettagli_pagamento_da_sessione("cs_9"),
                         {"customer": "cus_9", "payment_method": "pm_9"})

    def test_addebito_senza_idem_non_manda_la_chiave_di_idempotenza(self):
        f = _Fetch({"/payment_intents": {"id": "pi_1", "status": "succeeded"}})
        p = ProviderCarta("sk_x", fetch=f)
        r = p.addebita(customer="cus_1", payment_method="pm_1", importo_cents=500,
                       valuta="EUR", riferimento="R1")
        self.assertEqual(r, {"stato": "riuscito", "pi": "pi_1"})
        self.assertNotIn("Idempotency-Key", f.chiamate[0]["headers"])
        f2 = _Fetch({"/payment_intents": {"id": "pi_1", "status": "succeeded"}})
        ProviderCarta("sk_x", fetch=f2).addebita(
            customer="cus_1", payment_method="pm_1", importo_cents=500,
            valuta="EUR", riferimento="R1", idem="carta:ND-1:500")
        self.assertEqual(f2.chiamate[0]["headers"]["Idempotency-Key"], "carta:ND-1:500")

    def test_addebito_risposta_non_valida_e_stato_sconosciuto(self):
        p = ProviderCarta("sk_x", fetch=_Fetch({"/payment_intents": ["lista"]}))
        self.assertEqual(p.addebita(customer="c", payment_method="p", importo_cents=1,
                                    valuta="eur", riferimento="R"),
                         {"stato": "fallito", "motivo": "risposta_non_valida"})
        p = ProviderCarta("sk_x", fetch=_Fetch({"/payment_intents":
                                                {"id": "pi_2", "status": "canceled"}}))
        self.assertEqual(p.addebita(customer="c", payment_method="p", importo_cents=1,
                                    valuta="eur", riferimento="R"),
                         {"stato": "fallito", "pi": "pi_2", "motivo": "canceled"})
        p = ProviderCarta("sk_x", fetch=_Fetch({"/payment_intents": {"id": "pi_3"}}))
        self.assertEqual(p.addebita(customer="c", payment_method="p", importo_cents=1,
                                    valuta="eur", riferimento="R"),
                         {"stato": "fallito", "pi": "pi_3", "motivo": "sconosciuto"})

    def test_addebito_configurazione_e_valuta_di_ripiego(self):
        p = ProviderCarta("sk_x", fetch=_Fetch({"/payment_intents":
                                                {"id": "pi_1", "status": "succeeded"}}))
        self.assertEqual(p.addebita(customer="", payment_method="pm", importo_cents=1,
                                    valuta="eur", riferimento="R"),
                         {"stato": "config", "motivo": "carta_non_collegata"})
        for importo in (0, -1, True, 1.5, "500", None):
            self.assertEqual(p.addebita(customer="c", payment_method="p",
                                        importo_cents=importo, valuta="eur",
                                        riferimento="R"),
                             {"stato": "config", "motivo": "importo_non_valido"},
                             repr(importo))
        f = _Fetch({"/payment_intents": {"id": "pi_1", "status": "succeeded"}})
        ProviderCarta("sk_x", fetch=f).addebita(
            customer="c", payment_method="p", importo_cents=100, valuta="   ",
            riferimento="R")
        self.assertIn("currency=eur", f.chiamate[0]["body"].decode("utf-8"))

    def test_addebito_rete_giu_non_solleva(self):
        p = ProviderCarta("sk_x", fetch=_Fetch(esplode=True))
        self.assertEqual(p.addebita(customer="c", payment_method="p", importo_cents=1,
                                    valuta="eur", riferimento="R"),
                         {"stato": "fallito", "motivo": "eccezione"})


# ═══════════════════════════════════════════════════════════════════════════════
#  fase185 — TESTI LEGALI: se il motore non risponde, il documento NON mente
# ═══════════════════════════════════════════════════════════════════════════════
class TestTestiLegaliRamiDErrore(unittest.TestCase):
    def test_percentuali_di_ripiego_quando_il_motore_non_e_leggibile(self):
        vecchio = os.environ.get("PAGAMENTO_BPS")
        os.environ["PAGAMENTO_BPS"] = "non-un-numero"
        try:
            self.assertEqual(legali._percentuali(),
                             {"promo": 0, "giorni_promo": 90, "fase1": 8,
                              "regime": 10, "diretto": 5, "tecnica": 3})
        finally:
            if vecchio is None:
                os.environ.pop("PAGAMENTO_BPS", None)
            else:
                os.environ["PAGAMENTO_BPS"] = vecchio
        # tolto il guasto, torna a leggere dal motore
        from fase98_policy_commissione import LANCIO_BPS_REGIME
        self.assertEqual(legali._percentuali()["regime"], LANCIO_BPS_REGIME // 100)

    def test_penale_di_ripiego_quando_il_server_non_e_importabile(self):
        import fase83_server
        vecchio = fase83_server.PENALE_HOST_BPS
        fase83_server.PENALE_HOST_BPS = "non-un-numero"
        try:
            self.assertEqual(legali._penale(), 15)
        finally:
            fase83_server.PENALE_HOST_BPS = vecchio
        self.assertEqual(legali._penale(), vecchio // 100)

    def test_documento_non_componibile_dichiara_lerrore_e_non_solleva(self):
        vero = legali.testo_termini

        def rotto(lang="it"):
            raise RuntimeError("modello legale illeggibile")

        legali.testo_termini = rotto
        try:
            d = documento("termini", "it")
        finally:
            legali.testo_termini = vero
        self.assertEqual(d, {"documento": "termini", "errore": "non_disponibile"})
        self.assertNotIn("testo", d)          # mai un documento a meta'
        # subito dopo il documento vero torna completo
        buono = documento("termini", "it")
        self.assertEqual(buono["lang"], "it")
        self.assertEqual(len(buono["doc_sha256"]), 64)


# ═══════════════════════════════════════════════════════════════════════════════
#  fase131 — LEDGER DEI PAYOUT: il denaro dell'host non deve mai diventare invisibile
# ═══════════════════════════════════════════════════════════════════════════════
class TestPayoutDashboardRamiDErrore(unittest.TestCase):
    def setUp(self):
        self.fab = _Fabbrica(_memoria())
        self.p = PayoutDashboard(self.fab, orologio=lambda: 1000)
        self.p.inizializza_schema()

    def test_pragma_wal_non_supportato_non_ferma_il_ledger(self):
        fab = _Fabbrica(_memoria())
        fab.rompi("PRAGMA journal_mode")
        p = PayoutDashboard(fab, orologio=lambda: 1)
        p.inizializza_schema()
        self.assertIs(p.registra_maturato("P1", "h1", 5000, "EUR"), True)
        self.assertEqual(p.da_pagare("h1", "EUR"), 5000)

    def test_registra_rifiuta_input_e_NON_scrive(self):
        casi = [("", "h1", 100, "EUR"), ("P1", "", 100, "EUR"),
                ("P1", "h1", -1, "EUR"), ("P1", "h1", True, "EUR"),
                ("P1", "h1", 100, "EU"), ("P1", "h1", 100, "EU1"),
                ("P1", "h1", 100, None)]
        for args in casi:
            self.assertIs(self.p.registra_maturato(*args), False, repr(args))
            self.assertIs(self.p.registra_in_attesa(*args), False, repr(args))
        self.assertEqual(self.p.tutti(), [])

    def test_registra_con_db_rotto_dice_False_e_non_lascia_righe(self):
        self.fab.rompi("'maturato', ?)")
        self.assertIs(self.p.registra_maturato("P1", "h1", 100, "EUR"), False)
        self.fab.rompi("'in_attesa', ?)")
        self.assertIs(self.p.registra_in_attesa("P2", "h1", 100, "EUR"), False)
        self.fab.sana()
        self.assertEqual(self.p.tutti(), [])
        self.assertEqual(self.p.da_pagare("h1", "EUR"), 0)

    def test_rimuovi_con_db_rotto_dice_False_e_la_riga_resta(self):
        self.p.registra_in_attesa("P1", "h1", 700, "EUR")
        self.fab.rompi("DELETE FROM payout")
        self.assertIs(self.p.rimuovi("P1"), False)
        self.fab.sana()
        self.assertEqual(self.p.stato_di("P1"), "in_attesa")   # NON persa a meta'
        self.assertIs(self.p.rimuovi("P1"), True)
        self.assertEqual(self.p.stato_di("P1"), "")

    def test_aggiorna_stato_con_db_rotto_non_avanza_lo_stato(self):
        self.p.registra_maturato("P1", "h1", 700, "EUR")
        self.fab.rompi("SELECT stato FROM payout WHERE prenotazione_id=?")
        self.assertIs(self.p.aggiorna_stato("P1", "in_transito"), False)
        self.fab.sana()
        self.assertEqual(self.p.stato_di("P1"), "maturato")

    def test_riepilogo_e_conta_pagati_con_db_rotto_sono_vuoti_mai_esplodono(self):
        self.p.registra_maturato("P1", "h1", 700, "EUR")
        self.fab.rompi("SELECT valuta, stato, SUM(minori) FROM payout")
        self.assertEqual(self.p.riepilogo("h1"), {})
        self.assertEqual(self.p.da_pagare("h1", "EUR"), 0)
        self.fab.rompi("SELECT COUNT(*) FROM payout")
        self.assertEqual(self.p.conta_pagati("h1"), 0)
        self.fab.sana()
        self.assertEqual(self.p.conta_pagati("h1"), 1)

    def test_stato_di_input_non_valido_e_db_rotto(self):
        for cattivo in (None, 0, b"P1", "", ["P1"]):
            self.assertEqual(self.p.stato_di(cattivo), "", repr(cattivo))
        self.p.registra_maturato("P1", "h1", 700, "EUR")
        self.fab.rompi("SELECT stato FROM payout WHERE prenotazione_id=?")
        self.assertEqual(self.p.stato_di("P1"), "")
        self.fab.sana()
        self.assertEqual(self.p.stato_di("P1"), "maturato")

    def test_aumenta_payout_somma_al_centesimo_rifiuta_delta_non_positivi(self):
        self.p.registra_maturato("P1", "h1", 7000, "EUR")
        self.assertIs(self.p.aumenta_payout("P1", 250), True)
        self.assertEqual(self.p.info("P1")["minori"], 7250)
        for cattivo in (0, -5, True, 1.5, "250", None):
            self.assertIs(self.p.aumenta_payout("P1", cattivo), False, repr(cattivo))
        self.assertEqual(self.p.info("P1")["minori"], 7250)          # invariato
        self.assertIs(self.p.aumenta_payout("MAI", 250), False)      # nessuna riga
        self.fab.rompi("UPDATE payout SET minori=minori+?")
        self.assertIs(self.p.aumenta_payout("P1", 100), False)
        self.fab.sana()
        self.assertEqual(self.p.info("P1")["minori"], 7250)          # ancora invariato

    def test_info_input_non_valido_e_db_rotto(self):
        for cattivo in (None, 0, b"P1", ""):
            self.assertIsNone(self.p.info(cattivo), repr(cattivo))
        self.assertIsNone(self.p.info("MAI"))
        self.p.registra_maturato("P1", "h1", 7000, "EUR")
        self.fab.rompi("minori, valuta, stato FROM payout WHERE prenotazione_id")
        self.assertIsNone(self.p.info("P1"))
        self.fab.sana()
        self.assertEqual(self.p.info("P1"), {"prenotazione_id": "P1", "host_id": "h1",
                                             "minori": 7000, "valuta": "EUR",
                                             "stato": "maturato"})

    def test_elenca_senza_filtri_e_con_host_non_valido_e_db_rotto(self):
        self.p.registra_maturato("P1", "h1", 100, "EUR")
        self.p.registra_in_attesa("P2", "h1", 200, "USD")
        for cattivo in (None, 0, b"h1", ""):
            self.assertEqual(self.p.elenca(cattivo), [], repr(cattivo))
        tutti_h1 = self.p.elenca("h1")                       # nessun filtro stato/valuta
        self.assertEqual([r["prenotazione_id"] for r in tutti_h1], ["P1", "P2"])
        self.assertEqual(self.p.elenca("h1", limit=0)[0]["prenotazione_id"], "P1")
        self.assertEqual([r["prenotazione_id"]
                          for r in self.p.elenca("h1", valuta="usd")], ["P2"])
        self.fab.rompi("FROM payout WHERE host_id=?")
        self.assertEqual(self.p.elenca("h1"), [])
        self.fab.sana()
        self.assertEqual(len(self.p.elenca("h1")), 2)

    def test_tutti_con_db_rotto_e_vuoto(self):
        self.p.registra_maturato("P1", "h1", 100, "EUR")
        self.assertEqual(len(self.p.tutti(stato="maturato")), 1)
        self.assertEqual(len(self.p.tutti(limit=99999)), 1)   # limit fuori banda -> default
        self.fab.rompi("stato, ts FROM payout ORDER BY")
        self.assertEqual(self.p.tutti(), [])

    def test_imposta_importo_rifiuta_valori_impossibili_e_db_rotto(self):
        self.p.registra_maturato("P1", "h1", 7000, "EUR")
        for cattivo in (0, -1, True, 1.5, "10", None):
            self.assertIs(self.p.imposta_importo("P1", cattivo), False, repr(cattivo))
        self.assertIs(self.p.imposta_importo(None, 10), False)
        self.assertIs(self.p.imposta_importo("", 10), False)
        self.assertEqual(self.p.info("P1")["minori"], 7000)
        self.assertIs(self.p.imposta_importo("MAI", 10), False)
        self.fab.rompi("UPDATE payout SET minori=?, ts=?")
        self.assertIs(self.p.imposta_importo("P1", 10), False)
        self.fab.sana()
        self.assertEqual(self.p.info("P1")["minori"], 7000)   # invariato
        self.assertIs(self.p.imposta_importo("P1", 4200), True)
        self.assertEqual(self.p.info("P1")["minori"], 4200)

    def test_valuta_con_spazi_NON_rende_invisibile_il_denaro_dellhost(self):
        """DIFETTO TROVATO QUI. `_valuta()` valida DOPO lo strip (' eur ' -> ok) ma la
        riga veniva scritta SENZA strip (' EUR '): il riepilogo raggruppava su una
        chiave con gli spazi, cosi' `da_pagare(host,'EUR')` diceva ZERO e `elenca(...,
        valuta='EUR')` non trovava nulla. Il payout esisteva ma era INVISIBILE: nessun
        bonifico all'host e nessuna compensazione penale possibile su quella riga."""
        self.assertIs(self.p.registra_maturato("P1", "h1", 5000, " eur "), True)
        self.assertEqual(self.p.info("P1")["valuta"], "EUR")
        self.assertEqual(self.p.da_pagare("h1", "EUR"), 5000)
        self.assertEqual([r["prenotazione_id"]
                          for r in self.p.elenca("h1", stato="maturato",
                                                 valuta="EUR")], ["P1"])
        self.assertEqual(self.p.riepilogo("h1"), {"EUR": {"maturato": 5000}})
        # e la lettura tollera a sua volta la richiesta sporca
        self.assertEqual(self.p.da_pagare("h1", " eur "), 5000)
        self.assertIs(self.p.registra_in_attesa("P2", "h1", 300, "usd "), True)
        self.assertEqual(self.p.info("P2")["valuta"], "USD")

    def test_factory_su_file_vero(self):
        d = tempfile.mkdtemp()
        try:
            p = crea_payout_dashboard(os.path.join(d, "payout.db"), orologio=lambda: 3)
            p.inizializza_schema()
            p.registra_maturato("P1", "h1", 100, "EUR")
            self.assertEqual(p.stato_di("P1"), "maturato")
        finally:
            shutil.rmtree(d, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  fase162 — PAGAMENTI PENDENTI: hold, gare, e il prospetto della tariffa tecnica
# ═══════════════════════════════════════════════════════════════════════════════
class TestPagamentiPendentiRamiDErrore(unittest.TestCase):
    def setUp(self):
        self.fab = _Fabbrica(_memoria(row=True))
        self.orologio = [1000]
        self.pp = PagamentiPendenti(self.fab, orologio=lambda: self.orologio[0])
        self.pp.inizializza_schema()

    def _reg(self, rif, **kw):
        base = {"alloggio_id": "casa", "check_in": "2027-05-01",
                "check_out": "2027-05-03"}
        base.update(kw)
        return self.pp.registra(rif, **base)

    def test_pragma_wal_non_supportato_non_ferma_gli_hold(self):
        fab = _Fabbrica(_memoria(row=True))
        fab.rompi("PRAGMA journal_mode")
        pp = PagamentiPendenti(fab, orologio=lambda: 10)
        pp.inizializza_schema()
        self.assertIs(pp.registra("R1", alloggio_id="casa", check_in="2027-05-01",
                                  check_out="2027-05-03"), True)
        self.assertEqual(pp.info("R1")["stato"], "in_attesa")

    def test_registra_rifiuta_riferimenti_e_alloggi_vuoti(self):
        for rif, allo in ((None, "casa"), ("", "casa"), (123, "casa"), ("R1", "")):
            self.assertIs(self.pp.registra(rif, alloggio_id=allo, check_in="a",
                                           check_out="b"), False, repr((rif, allo)))
        self.assertEqual(self.pp.idem_keys(), set())

    def test_da_approvare_con_host_non_valido_e_vuoto(self):
        for cattivo in (None, "", 0, b"h1"):
            self.assertEqual(self.pp.da_approvare(cattivo), [], repr(cattivo))
        self._reg("R1", host_id="h1", stato="in_attesa_host")
        self.assertEqual([r["riferimento"] for r in self.pp.da_approvare("h1")], ["R1"])
        self.assertEqual(self.pp.da_approvare("h1", limit=0)[0]["riferimento"], "R1")

    def test_salva_stripe_session_rifiuta_input_e_record_inesistente(self):
        self.assertIs(self.pp.salva_stripe_session("R1", "non_cs"), False)
        self.assertIs(self.pp.salva_stripe_session(None, "cs_1"), False)
        self.assertIs(self.pp.salva_stripe_session("MAI", "cs_1"), False)  # record assente

    def test_salva_stripe_session_ripara_un_corpo_json_non_utilizzabile(self):
        """corpo_json che non e' un oggetto (lista) o non e' nemmeno JSON: si riparte da
        un dizionario vuoto e l'id sessione viene salvato lo stesso — mai perdere il
        riferimento Stripe per colpa di un campo sporco."""
        self._reg("R1", corpo_json="[1, 2, 3]")
        self.assertIs(self.pp.salva_stripe_session("R1", "cs_A"), True)
        self.assertEqual(json.loads(self.pp.info("R1")["corpo_json"]),
                         {"stripe_cs": "cs_A"})
        self._reg("R2", corpo_json="{non json")
        self.assertIs(self.pp.salva_stripe_session("R2", "cs_B"), True)
        self.assertEqual(json.loads(self.pp.info("R2")["corpo_json"]),
                         {"stripe_cs": "cs_B"})
        self.assertIs(self.pp.salva_stripe_session("R2", "cs_B"), True)   # replay: no-op

    def test_salva_stripe_session_con_db_rotto_e_ISOLATO(self):
        self._reg("R1", corpo_json=json.dumps({"valuta": "EUR"}))
        self.fab.rompi("UPDATE pendenti SET corpo_json=?")
        self.assertIs(self.pp.salva_stripe_session("R1", "cs_A"), False)
        self.fab.sana()
        self.assertEqual(json.loads(self.pp.info("R1")["corpo_json"]), {"valuta": "EUR"})

    def test_cerca_prenotazioni_termine_corto_e_db_rotto(self):
        for corto in (None, "", "a", "  ", 12):
            self.assertEqual(self.pp.cerca_prenotazioni(corto),
                             {"prenotazioni": [], "totale": 0}, repr(corto))
        self._reg("R1ABC", email="ospite@x.it", host_id="h1")
        r = self.pp.cerca_prenotazioni("R1A")
        self.assertEqual(r["totale"], 1)
        self.assertEqual(r["prenotazioni"][0]["email"], "ospite@x.it")
        self.assertEqual(self.pp.cerca_prenotazioni("%")["totale"], 0)   # wildcard neutra
        self.fab.rompi("SELECT COUNT(*) FROM pendenti")
        self.assertEqual(self.pp.cerca_prenotazioni("R1A"),
                         {"prenotazioni": [], "totale": 0})

    def test_notti_per_alloggio_con_db_rotto_e_input_impossibili(self):
        self.assertEqual(self.pp.notti_per_alloggio(None, 2027), {})
        self.assertEqual(self.pp.notti_per_alloggio("h1", True), {})
        self.assertEqual(self.pp.notti_per_alloggio("h1", 999999), {})   # anno fuori banda
        self._reg("R1", host_id="h1")
        self.pp.conferma("R1")
        self.assertEqual(self.pp.notti_per_alloggio("h1", 2027),
                         {"casa": {"notti": 2, "pren": 1}})
        self.fab.rompi("SELECT alloggio_id, check_in, check_out FROM pendenti")
        self.assertEqual(self.pp.notti_per_alloggio("h1", 2027), {})

    def test_conferma_riferimento_non_valido(self):
        for cattivo in (None, "", 0, b"R1"):
            self.assertIsNone(self.pp.conferma(cattivo), repr(cattivo))
        self.assertIsNone(self.pp.conferma("MAI"))

    def test_conferma_con_CAS_sempre_persa_non_scrive_mai_pagato(self):
        """Gara patologica: la CAS perde a ogni giro (lo stato cambia sotto le mani).
        Il ciclo e' LIMITATO (8 tentativi) e non deve mai lasciare una scrittura a
        meta': il record resta esattamente com'era."""
        self._reg("R1")
        self.fab.riscrivi = lambda sql: (
            sql + " AND 0" if sql.startswith("UPDATE pendenti SET stato='pagato'") else sql)
        rec = self.pp.conferma("R1")
        self.fab.riscrivi = None
        self.assertEqual(rec["riferimento"], "R1")
        self.assertEqual(self.pp.info("R1")["stato"], "in_attesa")   # NESSUNA scrittura

    def test_metodi_di_stato_rifiutano_riferimenti_non_stringa(self):
        cattivi = (None, "", 0, b"R1", ["R1"])
        for c in cattivi:
            self.assertIs(self.pp.aggiorna_idem(c, "k"), False, repr(c))
            self.assertIs(self.pp.rimuovi(c), False, repr(c))
            self.assertIs(self.pp.rimuovi_se_stato(c, "in_attesa"), False, repr(c))
            self.assertIs(self.pp.scadi(c), False, repr(c))
            self.assertIs(self.pp.marca_da_rimborsare(c), False, repr(c))
            self.assertIs(self.pp.marca_cancellata_host(c), False, repr(c))
            self.assertIs(self.pp.segna_promemoria(c), False, repr(c))
            self.assertIs(self.pp.segna_invito_recensione(c), False, repr(c))
            self.assertIsNone(self.pp.info(c), repr(c))
        self._reg("R1")
        self.assertIs(self.pp.aggiorna_idem("R1", ""), False)
        self.assertIs(self.pp.rimuovi_se_stato("R1", ""), False)
        self.assertIs(self.pp.rimuovi_se_stato("R1", "pagato"), False)   # stato sbagliato
        self.assertEqual(self.pp.info("R1")["stato"], "in_attesa")       # intatto

    def test_idem_keys_con_db_rotto_e_insieme_vuoto(self):
        self._reg("R1", idem_key="k1")
        self.assertEqual(self.pp.idem_keys(), {"k1"})
        self.fab.rompi("SELECT idem_key FROM pendenti")
        self.assertEqual(self.pp.idem_keys(), set())

    def test_cancellata_host_ripara_un_corpo_json_illeggibile(self):
        """corpo_json corrotto: la penale va registrata lo stesso (e' un debito vero),
        ripartendo da un dizionario vuoto."""
        self._reg("R1", corpo_json="{rotto")
        self.assertIs(self.pp.marca_cancellata_host("R1", 1500), True)
        self.assertEqual(json.loads(self.pp.info("R1")["corpo_json"]),
                         {"penale_host_cents": 1500})
        self.assertEqual(self.pp.info("R1")["stato"], "cancellata_host")
        self.assertIs(self.pp.marca_cancellata_host("R1", 9999), False)   # CAS: una sola
        self.assertEqual(json.loads(self.pp.info("R1")["corpo_json"])["penale_host_cents"],
                         1500)
        self.assertEqual([r["riferimento"] for r in self.pp.cancellate_host()], ["R1"])
        self.assertEqual(self.pp.cancellate_host(limit=0)[0]["riferimento"], "R1")

    def test_calendario_hold_vivi_singolo_e_batch(self):
        for cattivo in (None, "", 0, b"casa"):
            self.assertEqual(self.pp.attivi_per_alloggio(cattivo), [], repr(cattivo))
        for vuoto in (None, [], [1, None, ""], "casa"[:0]):
            self.assertEqual(self.pp.attivi_multi(vuoto), {}, repr(vuoto))
        self._reg("R1", scadenza_ts=5000)
        self._reg("R2", alloggio_id="villa", scadenza_ts=5000)
        self._reg("R3", scadenza_ts=10)                       # gia' scaduto
        multi = self.pp.attivi_multi(["casa", "villa", 7, None])
        self.assertEqual(sorted(multi.keys()), ["casa", "villa"])
        self.assertEqual([r["riferimento"] for r in multi["casa"]], ["R1"])
        self.assertEqual([r["riferimento"] for r in multi["villa"]], ["R2"])
        self.assertEqual([r["riferimento"]
                          for r in self.pp.attivi_per_alloggio("casa")], ["R1"])

    def test_promemoria_e_invito_recensione_con_data_non_valida(self):
        for cattivo in (None, "", 0):
            self.assertEqual(self.pp.da_promemoriare(oggi=cattivo), [], repr(cattivo))
            self.assertEqual(self.pp.da_invitare_recensione(oggi=cattivo), [],
                             repr(cattivo))
        self.assertEqual(self.pp.da_invitare_recensione(oggi="non-una-data"), [])
        self._reg("R1", email="o@x.it")
        self.pp.conferma("R1")
        self.assertEqual([r["riferimento"]
                          for r in self.pp.da_promemoriare(oggi="2027-05-02")], ["R1"])
        self.assertIs(self.pp.segna_promemoria("R1"), True)
        self.assertEqual(self.pp.da_promemoriare(oggi="2027-05-02"), [])
        self.assertEqual([r["riferimento"] for r in
                          self.pp.da_invitare_recensione(oggi="2027-05-05")], ["R1"])
        self.assertIs(self.pp.segna_invito_recensione("R1"), True)
        self.assertEqual(self.pp.da_invitare_recensione(oggi="2027-05-05"), [])

    def test_pulisci_vecchi_toglie_solo_scaduti_e_rimborsati(self):
        self._reg("R1")
        self._reg("R2")
        self.pp.scadi("R1")
        self.pp.marca_da_rimborsare("R2")
        self._reg("R3")
        self.assertEqual(self.pp.pulisci_vecchi(ora_ts=1000), 0)      # troppo recenti
        self.assertEqual(self.pp.pulisci_vecchi(ora_ts=1000 + 93600 + 1), 2)
        self.assertIsNone(self.pp.info("R1"))
        self.assertEqual(self.pp.info("R3")["stato"], "in_attesa")    # il vivo resta

    def test_prospetto_tariffa_tecnica_separa_incassato_e_PERDITA(self):
        """La quota Stripe su una prenotazione rimborsata NON torna indietro: e' una
        perdita tecnica reale, e il prospetto deve dirlo con la voce fiscale giusta."""
        self._reg("P1", corpo_json=json.dumps({"costo_pagamento_cents": 300,
                                               "valuta": "eur"}))
        self.pp.conferma("P1")
        self._reg("P2", corpo_json=json.dumps({"costo_pagamento_cents": 120,
                                               "valuta": "EUR"}))
        self.pp.conferma("P2")
        self.pp.marca_da_rimborsare("P2")
        self._reg("P3", corpo_json=json.dumps({"costo_pagamento_cents": 80,
                                               "valuta": "USD"}))
        self.pp.marca_cancellata_host("P3", 500)
        self._reg("P4", corpo_json="{corrotto")                     # saltata
        self.pp.conferma("P4")
        self._reg("P5", corpo_json=json.dumps({"costo_pagamento_cents": 0}))  # saltata
        self.pp.conferma("P5")
        self._reg("P6", corpo_json=json.dumps({"costo_pagamento_cents": True}))  # saltata
        self.pp.conferma("P6")
        self._reg("P7")                                             # niente corpo: saltata
        self.pp.conferma("P7")
        out = self.pp.aggrega_costi_tecnici()
        self.assertEqual(out["letti"], 7)
        self.assertEqual(out["incassate"]["conteggio"], 1)
        self.assertEqual(out["incassate"]["cents"], 300)
        self.assertEqual(out["perdite"]["conteggio"], 2)
        self.assertEqual(out["perdite"]["cents"], 200)
        self.assertEqual(out["coperto_cents"], 100)
        self.assertEqual(out["per_valuta"], {
            "EUR": {"incassate_cents": 300, "perdite_cents": 120, "conteggio": 2},
            "USD": {"incassate_cents": 0, "perdite_cents": 80, "conteggio": 1}})
        self.assertIn("IRRECUPERABILE", out["perdite"]["voce_fiscale"])
        self.assertIn("Ricavo tecnico", out["incassate"]["voce_fiscale"])
        self.assertEqual(self.pp.aggrega_costi_tecnici(limit=0)["letti"], 7)  # limit clampato

    def test_prospetto_tariffa_tecnica_con_db_rotto_e_vuoto_mai_esplode(self):
        self._reg("P1", corpo_json=json.dumps({"costo_pagamento_cents": 300}))
        self.pp.conferma("P1")
        self.fab.rompi("SELECT stato, corpo_json FROM pendenti")
        out = self.pp.aggrega_costi_tecnici()
        self.assertEqual(out, {"incassate": {"conteggio": 0, "cents": 0},
                               "perdite": {"conteggio": 0, "cents": 0},
                               "coperto_cents": 0, "per_valuta": {}, "letti": 0})


# ═══════════════════════════════════════════════════════════════════════════════
#  fase88 — REGISTRO HOST: credenziali, magic-link, e DB in avaria
# ═══════════════════════════════════════════════════════════════════════════════
SEG_HOST = b"0123456789abcdef0123456789abcdef"


class TestRegistroHostRamiDErrore(unittest.TestCase):
    def setUp(self):
        from fase59_concierge import FirmaQuote
        from fase88_registro_host import RegistroHost
        self.orologio = [1_700_000_000]
        self.fab = _Fabbrica(_memoria())
        self.reg = RegistroHost(self.fab, FirmaQuote(SEG_HOST),
                                orologio=lambda: self.orologio[0])
        self.e = self.reg.registra("host@x.it", "passwordlunga", accetta_termini=True,
                                   ragione_sociale="B&B Sole")
        self.assertTrue(self.e.ok)

    def test_email_non_stringa_e_rifiutata_ovunque(self):
        from fase88_registro_host import _email_valida
        for cattiva in (None, 123, b"a@b.it", ["a@b.it"], {"a": 1}):
            self.assertIs(_email_valida(cattiva), False, repr(cattiva))
            self.assertEqual(self.reg.login(cattiva, "passwordlunga").errore,
                             "credenziali_non_valide")
            self.assertIsNone(self.reg.token_reset_password(cattiva))

    def test_pragma_wal_non_supportato_non_ferma_il_registro(self):
        from fase59_concierge import FirmaQuote
        from fase88_registro_host import RegistroHost
        fab = _Fabbrica(_memoria())
        fab.rompi("PRAGMA journal_mode")
        reg = RegistroHost(fab, FirmaQuote(SEG_HOST), orologio=lambda: 100)
        e = reg.registra("a@b.it", "passwordlunga", accetta_termini=True)
        self.assertTrue(e.ok)
        self.assertEqual(reg.verifica_token(e.token), e.host_id)

    def test_registra_con_db_rotto_non_lascia_account_a_meta(self):
        self.fab.rompi("INSERT INTO host")
        e = self.reg.registra("nuovo@x.it", "passwordlunga", accetta_termini=True)
        self.assertIs(e.ok, False)
        self.assertEqual(e.errore, "errore_interno")
        self.assertEqual(e.as_dict(), {"ok": False, "errore": "errore_interno"})
        self.fab.sana()
        self.assertEqual(self.reg.conta_host(), 1)                # solo quello di setUp
        self.assertEqual(self.reg.login("nuovo@x.it", "passwordlunga").errore,
                         "credenziali_non_valide")

    def test_magic_link_email_ignota_o_account_sospeso_non_esiste(self):
        self.assertIsNone(self.reg.token_reset_password("mai@x.it"))   # anti-enumerazione
        self.reg.imposta_stato(self.e.host_id, "sospeso")
        self.assertIsNone(self.reg.token_reset_password("host@x.it"))
        self.reg.imposta_stato(self.e.host_id, "attivo")
        self.assertTrue(self.reg.token_reset_password("host@x.it"))

    def test_reset_password_rifiuta_link_falsi_scaduti_e_password_corte(self):
        self.assertEqual(self.reg.reset_password("non-un-token", "passwordlunga").errore,
                         "link_non_valido")
        tok_host = self.e.token                       # token di accesso, non di reset
        self.assertEqual(self.reg.reset_password(tok_host, "passwordlunga").errore,
                         "link_non_valido")
        buono = self.reg.token_reset_password("host@x.it")
        self.orologio[0] += 1801                      # 30 minuti + 1s
        self.assertEqual(self.reg.reset_password(buono, "passwordlunga").errore,
                         "link_scaduto")
        self.orologio[0] -= 1801
        self.assertEqual(self.reg.reset_password(buono, "corta").errore,
                         "password_troppo_corta")
        # la password vecchia funziona ancora: nessun effetto collaterale
        self.assertTrue(self.reg.login("host@x.it", "passwordlunga").ok)

    def test_magic_link_e_SINGLE_USE_il_secondo_uso_e_carta_straccia(self):
        t1 = self.reg.token_reset_password("host@x.it")
        self.assertTrue(self.reg.reset_password(t1, "nuovapassword").ok)
        self.assertEqual(self.reg.reset_password(t1, "altrapassword").errore,
                         "link_non_valido")
        self.assertTrue(self.reg.login("host@x.it", "nuovapassword").ok)
        self.assertEqual(self.reg.login("host@x.it", "altrapassword").errore,
                         "credenziali_non_valide")

    def test_reset_password_con_db_rotto_non_cambia_la_password(self):
        t = self.reg.token_reset_password("host@x.it")
        self.fab.rompi("UPDATE host SET salt=")
        self.assertEqual(self.reg.reset_password(t, "nuovapassword").errore,
                         "errore_interno")
        self.fab.sana()
        self.assertTrue(self.reg.login("host@x.it", "passwordlunga").ok)   # vecchia valida

    def test_cambia_password_tutti_i_rifiuti(self):
        h = self.e.host_id
        self.assertEqual(self.reg.cambia_password(None, "passwordlunga", "nuovapassword")
                         .errore, "credenziali_non_valide")
        self.assertEqual(self.reg.cambia_password(h, 123, "nuovapassword").errore,
                         "credenziali_non_valide")
        self.assertEqual(self.reg.cambia_password(h, "passwordlunga", "corta").errore,
                         "password_troppo_corta")
        self.assertEqual(self.reg.cambia_password("h_inesistente", "passwordlunga",
                                                  "nuovapassword").errore,
                         "credenziali_non_valide")
        self.assertEqual(self.reg.cambia_password(h, "sbagliatissima", "nuovapassword")
                         .errore, "credenziali_non_valide")
        self.reg.imposta_stato(h, "sospeso")
        self.assertEqual(self.reg.cambia_password(h, "passwordlunga", "nuovapassword")
                         .errore, "credenziali_non_valide")
        self.reg.imposta_stato(h, "attivo")
        self.assertTrue(self.reg.login("host@x.it", "passwordlunga").ok)   # mai cambiata

    def test_cambia_password_riuscita_invalida_i_magic_link_in_giro(self):
        vecchio_link = self.reg.token_reset_password("host@x.it")
        ok = self.reg.cambia_password(self.e.host_id, "passwordlunga", "nuovapassword")
        self.assertTrue(ok.ok)
        self.assertEqual(self.reg.verifica_token(ok.token), self.e.host_id)
        self.assertEqual(self.reg.reset_password(vecchio_link, "terzapassword").errore,
                         "link_non_valido")

    def test_cambia_password_con_db_rotto_lascia_la_vecchia(self):
        self.fab.rompi("UPDATE host SET salt=")
        self.assertEqual(self.reg.cambia_password(self.e.host_id, "passwordlunga",
                                                  "nuovapassword").errore,
                         "errore_interno")
        self.fab.sana()
        self.assertTrue(self.reg.login("host@x.it", "passwordlunga").ok)

    def test_verifica_token_con_host_id_mancante_o_non_stringa(self):
        from fase59_concierge import FirmaQuote
        f = FirmaQuote(SEG_HOST)
        for hid in (None, 123, "", ["h_1"]):
            t = f.codifica({"tipo": "host_token", "host_id": hid,
                            "exp": self.orologio[0] + 10})
            self.assertIsNone(self.reg.verifica_token(t), repr(hid))

    def test_info_host_e_esiste_host_con_id_non_valido(self):
        for cattivo in (None, "", 0, b"h_1"):
            self.assertIsNone(self.reg.info_host(cattivo), repr(cattivo))
            self.assertIs(self.reg.esiste_host(cattivo), False, repr(cattivo))
        self.assertIsNone(self.reg.info_host("h_mai"))
        self.assertEqual(self.reg.info_host(self.e.host_id)["email"], "host@x.it")

    def test_dati_fiscali_rifiuti_e_db_rotto(self):
        h = self.e.host_id
        self.assertIs(self.reg.imposta_dati_fiscali(None, {"paese": "IT"}), False)
        self.assertIs(self.reg.imposta_dati_fiscali(h, "non-dizionario"), False)
        self.assertIs(self.reg.imposta_dati_fiscali(h, {}), False)          # nessun campo
        self.assertIs(self.reg.imposta_dati_fiscali(h, {"paese": "   "}), False)
        self.assertIs(self.reg.imposta_dati_fiscali(h, {"non_esiste": "x"}), False)
        self.assertIs(self.reg.imposta_dati_fiscali("h_mai", {"paese": "IT"}), False)
        self.assertIs(self.reg.imposta_dati_fiscali(h, {"paese": "IT"}), True)
        self.assertEqual(self.reg.info_host(h)["paese"], "IT")
        self.fab.rompi("UPDATE host SET codice_fiscale")
        self.assertIs(self.reg.imposta_dati_fiscali(h, {"codice_fiscale": "ABC"}), False)
        self.fab.sana()
        self.assertEqual(self.reg.info_host(h)["codice_fiscale"], "")

    def test_verifica_host_stati_ammessi_e_db_rotto(self):
        h = self.e.host_id
        self.assertIs(self.reg.imposta_verifica(None, "verificato"), False)
        self.assertIs(self.reg.imposta_verifica(h, "chissa"), False)
        self.assertIs(self.reg.imposta_verifica(h, None), False)
        self.assertIs(self.reg.imposta_verifica("h_mai", "verificato"), False)
        self.assertEqual(self.reg.info_host(h)["verifica_stato"], "")
        self.assertIs(self.reg.imposta_verifica(h, "verificato", note="documenti ok",
                                                da="super-admin"), True)
        info = self.reg.info_host(h)
        self.assertEqual(info["verifica_stato"], "verificato")
        self.assertEqual(info["verifica_note"], "documenti ok")
        self.assertEqual(info["verifica_da"], "super-admin")
        self.assertIs(self.reg.imposta_verifica(h, "revocato"), True)
        self.assertEqual(self.reg.info_host(h)["verifica_stato"], "revocato")
        self.assertEqual(self.reg.elenco_host()[0]["verifica_stato"], "revocato")
        self.fab.rompi("UPDATE host SET verifica_stato")
        self.assertIs(self.reg.imposta_verifica(h, ""), False)
        self.fab.sana()
        self.assertEqual(self.reg.info_host(h)["verifica_stato"], "revocato")  # invariato

    def test_cerca_host_termine_corto_e_db_rotto(self):
        for corto in (None, "", "a", "  ", 12):
            self.assertEqual(self.reg.cerca_host(corto), {"host": [], "totale": 0},
                             repr(corto))
        r = self.reg.cerca_host("host@")
        self.assertEqual(r["totale"], 1)
        self.assertEqual(r["host"][0]["ragione_sociale"], "B&B Sole")
        self.assertNotIn("iban", r["host"][0])            # mai dati fiscali qui
        self.assertEqual(self.reg.cerca_host("%")["totale"], 0)   # wildcard neutralizzata
        self.assertEqual(self.reg.cerca_host("host@", limit=0, offset=-1)["totale"], 1)
        self.fab.rompi("COUNT(*) FROM host WHERE")
        self.assertEqual(self.reg.cerca_host("host@"), {"host": [], "totale": 0})

    def test_collegamenti_esterni_rifiutano_host_id_non_valido_e_db_rotto(self):
        h = self.e.host_id
        for cattivo in (None, "", 0, b"h_1"):
            self.assertIs(self.reg.imposta_stripe_account(cattivo, "acct_1"), False)
            self.assertIs(self.reg.imposta_carta(cattivo, "cus_1", "pm_1"), False)
            self.assertIs(self.reg.imposta_telegram_chat(cattivo, "123"), False)
        self.assertIs(self.reg.imposta_stripe_account("h_mai", "acct_1"), False)
        self.assertIs(self.reg.imposta_stripe_account(h, "acct_1"), True)
        self.assertIs(self.reg.imposta_carta(h, "cus_1", "pm_1"), True)
        self.assertIs(self.reg.imposta_telegram_chat(h, "123"), True)
        info = self.reg.info_host(h)
        self.assertEqual((info["stripe_account_id"], info["stripe_customer_id"],
                          info["stripe_payment_method"], info["telegram_chat_id"]),
                         ("acct_1", "cus_1", "pm_1", "123"))
        for frammento, chiamata in (
                ("UPDATE host SET stripe_account_id",
                 lambda: self.reg.imposta_stripe_account(h, "acct_2")),
                ("UPDATE host SET stripe_customer_id",
                 lambda: self.reg.imposta_carta(h, "cus_2", "pm_2")),
                ("UPDATE host SET telegram_chat_id",
                 lambda: self.reg.imposta_telegram_chat(h, "999"))):
            self.fab.rompi(frammento)
            self.assertIs(chiamata(), False, frammento)
            self.fab.sana()
        info2 = self.reg.info_host(h)
        self.assertEqual((info2["stripe_account_id"], info2["stripe_customer_id"],
                          info2["telegram_chat_id"]), ("acct_1", "cus_1", "123"))

    def test_cancella_host_e_imposta_stato_con_input_non_validi(self):
        for cattivo in (None, "", 0, b"h_1"):
            self.assertEqual(self.reg.cancella_host(cattivo), 0, repr(cattivo))
        self.assertEqual(self.reg.cancella_host("h_mai"), 0)
        self.assertIs(self.reg.imposta_stato(self.e.host_id, "cancellato"), False)
        self.assertIs(self.reg.imposta_stato("h_mai", "sospeso"), False)
        self.assertEqual(self.reg.cancella_host(self.e.host_id), 1)
        self.assertIs(self.reg.esiste_host(self.e.host_id), False)

    def test_conta_host_con_db_rotto_ritorna_zero(self):
        self.fab.rompi("SELECT COUNT(*) FROM host")
        self.assertEqual(self.reg.conta_host(), 0)
        self.fab.sana()
        self.assertEqual(self.reg.conta_host(), 1)

    def test_numero_host_con_db_rotto_e_host_ignoto(self):
        self.assertEqual(self.reg.numero_host(self.e.host_id), 1)
        self.assertEqual(self.reg.numero_host("h_mai"), 0)
        self.fab.rompi("SELECT creato_ts FROM host WHERE host_id=?")
        self.assertEqual(self.reg.numero_host(self.e.host_id), 0)

    def test_giorni_da_registrazione_ignoto_o_illeggibile_e_ENORME(self):
        """Fail-closed sui soldi: se non si sa quando l'host si e' iscritto, NON si
        regala lo sconto di lancio — si risponde con un'anzianita' enorme."""
        self.assertEqual(self.reg.giorni_da_registrazione(self.e.host_id,
                                                          ora_ts=self.orologio[0]), 0)
        self.assertEqual(self.reg.giorni_da_registrazione("h_mai"), 10 ** 9)
        self.fab.rompi("SELECT creato_ts FROM host WHERE host_id=?")
        self.assertEqual(self.reg.giorni_da_registrazione(self.e.host_id), 10 ** 9)
        self.fab.sana()
        self.assertEqual(self.reg.giorni_da_registrazione(
            self.e.host_id, ora_ts=self.orologio[0] + 100 * 86400), 100)

    def test_db_che_non_sa_nemmeno_annullare_la_transazione(self):
        """Caso peggiore: la scrittura fallisce E il ROLLBACK fallisce a sua volta.
        Il modulo deve comunque rispondere 'errore_interno' senza sollevare e senza
        aver cambiato nulla di visibile."""
        self.fab.rompi("INSERT INTO host", "ROLLBACK")
        self.assertEqual(self.reg.registra("nuovo@x.it", "passwordlunga",
                                           accetta_termini=True).errore, "errore_interno")
        self.fab.sana()
        self.fab.con.rollback()
        self.assertEqual(self.reg.conta_host(), 1)
        t = self.reg.token_reset_password("host@x.it")
        self.fab.rompi("UPDATE host SET salt=", "ROLLBACK")
        self.assertEqual(self.reg.reset_password(t, "nuovapassword").errore,
                         "errore_interno")
        self.fab.sana()
        self.fab.con.rollback()
        self.fab.rompi("UPDATE host SET salt=", "ROLLBACK")
        self.assertEqual(self.reg.cambia_password(self.e.host_id, "passwordlunga",
                                                  "nuovapassword").errore,
                         "errore_interno")
        self.fab.sana()
        self.fab.con.rollback()          # igiene: la transazione era rimasta aperta
        self.assertTrue(self.reg.login("host@x.it", "passwordlunga").ok)

    def test_anzianita_host_regge_una_data_di_iscrizione_ASSURDA(self):
        """Riga con `creato_ts` testuale (dato sporco arrivato da una migrazione): il
        report non deve rompersi ne' inventare un'anzianita' — dichiara None."""
        self.fab.con.execute(
            "INSERT INTO host (host_id, email, salt, pw_hash, termini_versione, "
            "termini_ts, stato, creato_ts) VALUES "
            "('h_sporco','sporco@x.it','00','00','1.0',0,'attivo','non-un-numero')")
        self.fab.con.commit()
        righe = {r["host_id"]: r for r in self.reg.anzianita_host(
            ora_ts=self.orologio[0] + 10 * 86400)}
        self.assertEqual(righe["h_sporco"]["giorni"], None)
        self.assertEqual(righe["h_sporco"]["creato_ts"], None)
        self.assertEqual(righe[self.e.host_id]["giorni"], 10)
        self.assertEqual(righe[self.e.host_id]["ragione_sociale"], "B&B Sole")
        self.assertEqual(self.reg.giorni_da_registrazione("h_sporco"), 10 ** 9)
        self.assertEqual(len(self.reg.anzianita_host(limit=0)), 2)   # limit clampato
        self.fab.rompi("SELECT host_id, email, ragione_sociale, stato, creato_ts ")
        self.assertEqual(self.reg.anzianita_host(), [])


# ═══════════════════════════════════════════════════════════════════════════════
#  fase59 — CONCIERGE: i guasti dei pezzi collegati non devono fermare la vendita
#           (ne' far uscire un prezzo che il CORE non ha firmato)
# ═══════════════════════════════════════════════════════════════════════════════
SEG_CONC = b"0123456789abcdef0123456789abcdef"


class _EsitoBlocco:
    def __init__(self, ok=True, motivo="", idempotente=False):
        self.ok = ok
        self.motivo = motivo
        self.idempotente = idempotente


class _InvFinto:
    def __init__(self, prezzo=10000, disp=True, esito=None, esplode=None):
        self.prezzo = prezzo
        self.disp = disp
        self.esito = esito or _EsitoBlocco(True)
        self.esplode = esplode or ()

    def disponibile(self, slug, ci, co):
        if "disponibile" in self.esplode:
            raise RuntimeError("inventario giu'")
        return self.disp

    def stato_giorno(self, slug, g):
        return {"prezzo_netto_cents": self.prezzo}

    def blocca(self, slug, ci, co, idem_key="", origine=""):
        if "blocca" in self.esplode:
            raise RuntimeError("inventario giu'")
        return self.esito


_MANCA = object()


class _CatFinto:
    def __init__(self, dett=_MANCA, esplode=(), risultati=None, sconto=(0, 0),
                 politica="flessibile"):
        self._dett = {"slug": "casa", "valuta": "EUR"} if dett is _MANCA else dett
        self.esplode = esplode
        self.risultati = risultati if risultati is not None else {"alloggi": []}
        self._sconto = sconto
        self._politica = politica

    def dettaglio(self, slug):
        if "dettaglio" in self.esplode:
            raise RuntimeError("catalogo giu'")
        return self._dett

    def cerca(self, criteri):
        if "cerca" in self.esplode:
            raise RuntimeError("catalogo giu'")
        return self.risultati

    def sconto_lungo_di(self, slug):
        if "sconto" in self.esplode:
            raise RuntimeError("sconti illeggibili")
        return self._sconto

    def politica_cancellazione_di(self, slug):
        if "politica" in self.esplode:
            raise RuntimeError("politica illeggibile")
        return self._politica


def _proto(**kw):
    from fase59_concierge import FirmaQuote, ProtocolloConcierge
    inv = kw.pop("inventario", None) or _InvFinto()
    firma = kw.pop("firma", None) or FirmaQuote(SEG_CONC)
    return ProtocolloConcierge(inv, firma, **kw)


DATE = {"check_in": "2027-09-01", "check_out": "2027-09-03"}


class TestConciergeRamiDErrore(unittest.TestCase):
    def test_quota_input_non_validi(self):
        p = _proto()
        self.assertEqual(p.quota("non-un-oggetto").status, 400)
        self.assertEqual(p.quota({"alloggio_id": "   "}).corpo["errore"],
                         "alloggio_id_non_valido")
        self.assertEqual(p.quota({"alloggio_id": "a|b"}).corpo["errore"],
                         "alloggio_id_non_valido")
        self.assertEqual(p.quota({"alloggio_id": "x" * 300}).corpo["errore"],
                         "alloggio_id_non_valido")
        self.assertEqual(p.quota({"alloggio_id": "casa"}).corpo["errore"],
                         "date_mancanti")
        self.assertEqual(p.quota({"alloggio_id": "casa", "check_in": "2027-09-01"})
                         .corpo["errore"], "date_mancanti")
        for party in (0, 51, True, 1.5, "2", None):
            r = p.quota(dict(alloggio_id="casa", party=party, **DATE))
            self.assertEqual(r.corpo["errore"], "party_non_valido", repr(party))

    def test_annuncio_sospeso_non_e_quotabile_ne_prenotabile(self):
        p = _proto(catalogo=_CatFinto(dett=None))       # dettaglio None = non pubblicato
        r = p.quota(dict(alloggio_id="casa", **DATE))
        self.assertEqual((r.status, r.corpo["errore"]), (404, "alloggio_non_disponibile"))

    def test_annuncio_sospeso_TRA_preventivo_e_prenotazione(self):
        cat = _CatFinto()
        p = _proto(catalogo=cat)
        tok = p.quota(dict(alloggio_id="casa", **DATE)).corpo["quote_token"]
        cat._dett = None                                 # sospeso nel frattempo
        r = p.prenota({"quote_token": tok, "email": "g@x.it"})
        self.assertEqual((r.status, r.corpo["errore"]), (404, "alloggio_non_disponibile"))

    def test_catalogo_in_avaria_NON_blocca_le_vendite_e_usa_la_valuta_di_sistema(self):
        """Fail-open dichiarato: un errore transitorio del catalogo non deve fermare
        TUTTE le prenotazioni (l'inventario resta la guardia vera)."""
        p = _proto(catalogo=_CatFinto(esplode=("dettaglio",)), valuta="CHF")
        r = p.quota(dict(alloggio_id="casa", **DATE))
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["valuta"], "CHF")

    def test_annuncio_senza_valuta_dichiarata_usa_quella_di_sistema(self):
        p = _proto(catalogo=_CatFinto(dett={"slug": "casa"}), valuta="GBP")
        self.assertEqual(p.quota(dict(alloggio_id="casa", **DATE)).corpo["valuta"], "GBP")
        p2 = _proto(catalogo=_CatFinto(dett={"slug": "casa", "valuta": 123}),
                    valuta="GBP")
        self.assertEqual(p2.quota(dict(alloggio_id="casa", **DATE)).corpo["valuta"], "GBP")

    def test_sconti_e_tassa_illeggibili_valgono_ZERO_non_rompono_il_preventivo(self):
        p = _proto(catalogo=_CatFinto(esplode=("sconto", "politica")),
                   tassa_alloggio=lambda *a, **k: (_ for _ in ()).throw(
                       RuntimeError("tassa giu'")))
        r = p.quota(dict(alloggio_id="casa", **DATE))
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["sconto_soggiorno_lungo_cents"], 0)
        self.assertEqual(r.corpo["sconto_non_rimborsabile_cents"], 0)
        self.assertEqual(r.corpo["tassa_soggiorno_cents"], 0)
        self.assertEqual(r.corpo["totale_cents"], r.corpo["prezzo_guest_cents"])

    def test_commissione_in_avaria_ripiega_e_mai_negativa(self):
        p = _proto(commissione=lambda netto: 1500,
                   commissione_alloggio=lambda *a: (_ for _ in ()).throw(
                       RuntimeError("policy giu'")))
        r = p.quota(dict(alloggio_id="casa", **DATE))
        self.assertEqual(r.corpo["commissione_cents"], 1500)          # ripiego semplice
        for storta in (-100, 1.5, True, "1500", None):
            p2 = _proto(commissione=lambda netto, v=storta: v)
            r2 = p2.quota(dict(alloggio_id="casa", **DATE))
            self.assertEqual(r2.corpo["commissione_cents"], 0, repr(storta))
            self.assertEqual(r2.corpo["netto_host_cents"], r2.corpo["prezzo_netto_cents"])

    def test_commissione_non_puo_superare_il_netto_dellhost(self):
        """Tetto duro: qualunque cosa dica la policy, non si tratterra' all'host piu' di
        quanto l'host incassa (netto host mai negativo)."""
        p = _proto(commissione=lambda netto: netto * 3)
        r = p.quota(dict(alloggio_id="casa", **DATE))
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["commissione_cents"], r.corpo["prezzo_netto_cents"])
        self.assertEqual(r.corpo["netto_host_cents"], 0)

    def test_prezzo_fuori_banda_e_rifiutato(self):
        p = _proto(inventario=_InvFinto(prezzo=100_000_000))
        r = p.quota(dict(alloggio_id="casa", **DATE))
        self.assertEqual((r.status, r.corpo["errore"]), (422, "prezzo_fuori_banda"))

    def test_inventario_in_avaria_e_un_503_onesto_mai_un_prezzo_inventato(self):
        p = _proto(inventario=_InvFinto(esplode=("disponibile",)))
        r = p.quota(dict(alloggio_id="casa", **DATE))
        self.assertEqual((r.status, r.corpo), (503, {"errore": "service_unavailable"}))
        p2 = _proto(inventario=_InvFinto(esplode=("blocca",)))
        tok = _proto().quota(dict(alloggio_id="casa", **DATE)).corpo["quote_token"]
        r2 = p2.prenota({"quote_token": tok, "email": "g@x.it"})
        self.assertEqual((r2.status, r2.corpo), (503, {"errore": "service_unavailable"}))

    def test_cambio_indicativo_con_tasso_in_avaria_vale_ZERO(self):
        p = _proto(tasso_cambio=lambda da, a: (_ for _ in ()).throw(
            RuntimeError("cambio giu'")))
        r = p.quota(dict(alloggio_id="casa", valuta_ospite="USD", **DATE))
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["totale_indicativo_cents"], 0)
        self.assertEqual(r.corpo["valuta_indicativa"], "")
        p2 = _proto(tasso_cambio=lambda da, a: None)
        self.assertEqual(p2.quota(dict(alloggio_id="casa", valuta_ospite="USD", **DATE))
                         .corpo["totale_indicativo_cents"], 0)

    def test_credito_fondatore_tutti_i_modi_di_NON_scontare(self):
        from fase59_concierge import FirmaQuote
        f = FirmaQuote(SEG_CONC)
        ora = [2_000_000_000]
        p = _proto(firma=f, commissione=lambda n: 10000, orologio=lambda: ora[0])
        buono = f.codifica({"tipo": "credito_fondatore", "credito_cents": 500,
                            "valuta": "EUR", "exp": ora[0] + 1000})
        r = p.quota(dict(alloggio_id="casa", credito_token=buono, **DATE))
        self.assertEqual(r.corpo["sconto_credito_cents"], 500)        # riferimento
        casi = {
            "token non firmato": "roba.a-caso",
            "tipo sbagliato": f.codifica({"tipo": "altro", "credito_cents": 500,
                                          "valuta": "EUR", "exp": ora[0] + 10}),
            "senza scadenza": f.codifica({"tipo": "credito_fondatore",
                                          "credito_cents": 500, "valuta": "EUR"}),
            "scaduto": f.codifica({"tipo": "credito_fondatore", "credito_cents": 500,
                                   "valuta": "EUR", "exp": ora[0] - 1}),
            "altra valuta": f.codifica({"tipo": "credito_fondatore",
                                        "credito_cents": 500, "valuta": "JPY",
                                        "exp": ora[0] + 10}),
            "credito non intero": f.codifica({"tipo": "credito_fondatore",
                                              "credito_cents": "500", "valuta": "EUR",
                                              "exp": ora[0] + 10}),
        }
        for nome, tok in casi.items():
            rr = p.quota(dict(alloggio_id="casa", credito_token=tok, **DATE))
            self.assertEqual(rr.corpo["sconto_credito_cents"], 0, nome)
            # anche dentro il token FIRMATO (quello che il book onorera') lo sconto e'
            # zero e l'ospite paga il prezzo pieno. NB: `credito_id` puo' restare
            # valorizzato, ma con sconto 0 il credito NON viene mai consumato
            # (`_consuma_credito` esige sconto > 0): nessun credito bruciato a vuoto.
            firmato = f.decodifica(rr.corpo["quote_token"])
            self.assertEqual(firmato["sconto_credito_cents"], 0, nome)
            self.assertEqual(firmato["prezzo_guest_cents"],
                             firmato["prezzo_netto_cents"], nome)

    def test_credito_gia_speso_non_sconta_piu_e_lo_store_rotto_non_toglie_il_diritto(self):
        from fase59_concierge import FirmaQuote
        f = FirmaQuote(SEG_CONC)
        ora = [2_000_000_000]
        tok = f.codifica({"tipo": "credito_fondatore", "credito_cents": 500,
                          "valuta": "EUR", "exp": ora[0] + 1000})

        class _StoreUsato:
            def usato(self, cid):
                return True

        class _StoreRotto:
            def usato(self, cid):
                raise RuntimeError("store crediti giu'")

        p_usato = _proto(firma=f, commissione=lambda n: 10000,
                         orologio=lambda: ora[0], credito_store=_StoreUsato())
        self.assertEqual(p_usato.quota(dict(alloggio_id="casa", credito_token=tok,
                                            **DATE)).corpo["sconto_credito_cents"], 0)
        p_rotto = _proto(firma=f, commissione=lambda n: 10000,
                         orologio=lambda: ora[0], credito_store=_StoreRotto())
        self.assertEqual(p_rotto.quota(dict(alloggio_id="casa", credito_token=tok,
                                            **DATE)).corpo["sconto_credito_cents"], 500)

    def test_credito_con_firma_illeggibile_vale_ZERO_e_il_preventivo_esce_lo_stesso(self):
        from fase59_concierge import FirmaQuote

        class _FirmaCheEsplodeInLettura(FirmaQuote):
            def decodifica(self, token):
                raise RuntimeError("firma illeggibile")

        p = _proto(firma=_FirmaCheEsplodeInLettura(SEG_CONC),
                   commissione=lambda n: 10000)
        r = p.quota(dict(alloggio_id="casa", credito_token="qualsiasi.cosa", **DATE))
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["sconto_credito_cents"], 0)
        self.assertEqual(r.corpo["credito_id"] if "credito_id" in r.corpo else "", "")

    def test_firma_valida_ma_contenuto_non_JSON_e_rifiutata(self):
        from fase59_concierge import FirmaQuote
        b64 = base64.urlsafe_b64encode(b"questo non e' json").decode("ascii")
        # oracolo indipendente: l'HMAC lo ricalcolo qui con la stdlib, non col modulo
        mac = hmac.new(SEG_CONC, b64.encode("ascii"), hashlib.sha256).hexdigest()
        self.assertIsNone(FirmaQuote(SEG_CONC).decodifica(b64 + "." + mac))

    def test_prenota_payload_e_quote_corrotte(self):
        from fase59_concierge import FirmaQuote
        f = FirmaQuote(SEG_CONC)
        ora = [2_000_000_000]
        p = _proto(firma=f, orologio=lambda: ora[0])
        self.assertEqual(p.prenota("non-un-oggetto").status, 400)
        corrotta = f.codifica({"exp": ora[0] + 100})          # firmata ma senza campi
        r = p.prenota({"quote_token": corrotta, "email": "g@x.it"})
        self.assertEqual((r.status, r.corpo["errore"]), (400, "quote_corrotta"))
        mezza = f.codifica({"alloggio_id": "casa", "check_in": "2027-09-01",
                            "check_out": "2027-09-03", "prezzo_guest_cents": "20000",
                            "exp": ora[0] + 100})
        self.assertEqual(p.prenota({"quote_token": mezza, "email": "g@x.it"})
                         .corpo["errore"], "quote_corrotta")

    def test_scopri_payload_non_oggetto_e_catalogo_in_avaria(self):
        p = _proto(catalogo=_CatFinto())
        self.assertEqual(p.scopri("non-un-oggetto").status, 400)
        self.assertEqual(p.scopri(None).corpo["errore"], "payload_non_oggetto")
        p2 = _proto(catalogo=_CatFinto(esplode=("cerca",)))
        r = p2.scopri({"citta": "Roma"})
        self.assertEqual((r.status, r.corpo), (503, {"errore": "service_unavailable"}))

    def test_dettaglio_e_confronto_input_non_validi(self):
        p = _proto(catalogo=_CatFinto())
        self.assertEqual(p.dettaglio("non-un-oggetto").status, 400)
        self.assertEqual(p.dettaglio({"alloggio_id": "   "}).corpo["errore"],
                         "alloggio_id_non_valido")
        p2 = _proto(catalogo=_CatFinto(esplode=("dettaglio",)))
        r = p2.dettaglio({"alloggio_id": "casa"})
        self.assertEqual((r.status, r.corpo), (503, {"errore": "service_unavailable"}))
        self.assertEqual(_proto().confronto("non-un-oggetto").status, 400)

    def test_rotte_agent_discoverable_su_un_server_vero(self):
        try:
            from flask import Flask
        except ImportError:                       # pragma: no cover
            self.skipTest("flask non installato in questo ambiente")
        from fase59_concierge import registra_concierge
        p = _proto(catalogo=_CatFinto(risultati={"alloggi": [{"slug": "casa"}]}))
        app = Flask(__name__ + "_concierge")
        registra_concierge(app, p)
        c = app.test_client()
        m = c.get("/concierge/manifest")
        self.assertEqual(m.status_code, 200)
        self.assertEqual(m.get_json()["money_unit"], "cents_integer")
        s = c.post("/concierge/search", json={"citta": "Roma"})
        self.assertEqual(s.status_code, 200)
        self.assertEqual(s.get_json()["alloggi"], [{"slug": "casa"}])
        q = c.post("/concierge/quote", json=dict(alloggio_id="casa", **DATE))
        self.assertEqual(q.status_code, 200)
        token = q.get_json()["quote_token"]
        b = c.post("/concierge/book", json={"quote_token": token, "email": "g@x.it"})
        self.assertEqual(b.status_code, 201)
        self.assertEqual(b.get_json()["stato"], "confermata")
        ko = c.post("/concierge/quote", json={"alloggio_id": "casa"})
        self.assertEqual(ko.status_code, 400)


# ═══════════════════════════════════════════════════════════════════════════════
#  fase177 — FINANCIAL CONTROLLER: il giornale e' la verita', anche quando crolla
# ═══════════════════════════════════════════════════════════════════════════════
class _LedgerCheEsplode:
    """Ledger payout che SOLLEVA (il vero fase131 non solleva mai): serve a provare
    che il Financial Controller isola un ledger davvero rotto."""

    def __init__(self, righe=(), su=("elenca",)):
        self.righe = [dict(r) for r in righe]
        self.su = su

    def elenca(self, host_id, stato=None, valuta=None):
        if "elenca" in self.su:
            raise RuntimeError("ledger payout giu'")
        return [dict(r) for r in self.righe]

    def imposta_importo(self, pid, minori):
        if "imposta_importo" in self.su:
            raise RuntimeError("ledger payout giu'")
        return True

    def rimuovi(self, pid):
        if "rimuovi" in self.su:
            raise RuntimeError("ledger payout giu'")
        return True

    def registra_maturato(self, pid, host_id, minori, valuta):
        if "registra_maturato" in self.su:
            raise RuntimeError("ledger payout giu'")
        return True


class _CartaFinta:
    def __init__(self, esiti):
        self.esiti = list(esiti)
        self.chiamate = []

    def addebita(self, **kw):
        self.chiamate.append(kw)
        e = self.esiti.pop(0) if self.esiti else {"stato": "fallito", "motivo": "vuoto"}
        if isinstance(e, Exception):
            raise e
        return e


class _BaseFC(unittest.TestCase):
    TS = 1_800_000_000               # 2027-01-15, primo trimestre

    def setUp(self):
        self.ts = [self.TS]
        self.fabf = _Fabbrica(_memoria())
        self.fc = FinancialController(self.fabf, orologio=lambda: self.ts[0])
        self.fc.inizializza_schema()
        self.fabp = _Fabbrica(_memoria())
        self.pd = PayoutDashboard(self.fabp, orologio=lambda: self.ts[0])
        self.pd.inizializza_schema()


class TestGiornaleRamiDErrore(_BaseFC):
    def test_pragma_non_supportato_non_ferma_il_giornale(self):
        fab = _Fabbrica(_memoria())
        fab.rompi("PRAGMA ")
        fc = FinancialController(fab, orologio=lambda: self.TS)
        fc.inizializza_schema()
        self.assertIsNotNone(fc.movimento(tipo="incasso", riferimento="R1",
                                          soggetto="host:h1", importo_cents=100,
                                          valuta="EUR", causale="x"))
        self.assertEqual(fc.conta_movimenti(), 1)

    def test_registra_rifiuta_righe_impossibili_e_NON_scrive(self):
        base = dict(evento_id="E1", tipo="incasso", riferimento="R1", soggetto="host:h1",
                    conto_dare="a", conto_avere="b", importo_cents=100, valuta="EUR",
                    causale="c", emittente="sistema")
        cattivi = [{"evento_id": ""}, {"tipo": "inventato"}, {"riferimento": ""},
                   {"soggetto": ""}, {"importo_cents": 0}, {"importo_cents": -5},
                   {"importo_cents": True}, {"valuta": "EURO"}, {"valuta": "EU"},
                   {"valuta": 978}]
        for patch_ in cattivi:
            arg = dict(base)
            arg.update(patch_)
            self.assertIsNone(self.fc.registra(**arg), repr(patch_))
        self.assertEqual(self.fc.conta_movimenti(), 0)
        self.assertIsNone(self.fc.movimento(tipo="inventato", riferimento="R1",
                                            soggetto="s", importo_cents=1,
                                            valuta="EUR", causale="c"))

    def test_giornale_non_scrivibile_ritorna_None_e_lascia_la_catena_intatta(self):
        self.fc.movimento(tipo="incasso", riferimento="R1", soggetto="host:h1",
                          importo_cents=100, valuta="EUR", causale="c")
        testa = self.fc.verifica_catena()["testa"]
        self.fabf.rompi("INSERT INTO libro_giornale")
        self.assertIsNone(self.fc.movimento(tipo="rimborso", riferimento="R1",
                                            soggetto="host:h1", importo_cents=50,
                                            valuta="EUR", causale="c"))
        self.fabf.sana()
        self.assertEqual(self.fc.conta_movimenti(), 1)
        self.assertEqual(self.fc.verifica_catena(),
                         {"ok": True, "seq_rotta": None, "testa": testa, "righe": 1})

    def test_db_che_non_sa_nemmeno_annullare_la_transazione(self):
        """La INSERT fallisce E il ROLLBACK fallisce: si risponde None senza sollevare e
        il giornale resta quello di prima."""
        self.fabf.rompi("INSERT INTO libro_giornale", "ROLLBACK")
        self.assertIsNone(self.fc.movimento(tipo="incasso", riferimento="R1",
                                            soggetto="host:h1", importo_cents=100,
                                            valuta="EUR", causale="c"))
        self.fabf.sana()
        self.fabf.con.rollback()
        self.assertEqual(self.fc.conta_movimenti(), 0)
        self.fabf.rompi("INSERT INTO note", "ROLLBACK")
        self.assertIsNone(self.fc.emetti_nota(tipo="debito", riferimento="R1",
                                              soggetto="host:h1", importo_cents=100,
                                              valuta="EUR", causale="c", emittente="e"))
        self.fabf.sana()
        self.fabf.con.rollback()
        self.assertEqual(self.fc.conta_movimenti(), 1)   # la riga di giornale resta
        self.assertEqual(self.fc.note_per_riferimento("R1"), [])

    def test_esporta_tutti_ordine_limiti_e_paginazione(self):
        for i in range(3):
            self.fc.movimento(tipo="incasso", riferimento="R%d" % i,
                              soggetto="host:h1", importo_cents=100 + i, valuta="EUR",
                              causale="c")
        tutte = self.fc.esporta_tutti()
        self.assertEqual([r["seq"] for r in tutte], [1, 2, 3])
        self.assertEqual([r["importo_cents"] for r in tutte], [100, 101, 102])
        self.assertNotIn("prev_hash", tutte[0])          # l'estratto porta l'hash finale
        self.assertEqual(len(self.fc.esporta_tutti(limit=2)), 2)
        self.assertEqual([r["seq"] for r in self.fc.esporta_tutti(offset=2)], [3])
        for storto in (0, -1, 10 ** 9, True, "10"):
            self.assertEqual(len(self.fc.esporta_tutti(limit=storto)), 3, repr(storto))
        for storto in (-1, True, "0", None):
            self.assertEqual(len(self.fc.esporta_tutti(offset=storto)), 3, repr(storto))

    def test_somme_e_incassi_periodo_input_storti_finestre_e_db_rotto(self):
        self.fc.movimento(tipo="incasso", riferimento="R1", soggetto="host:h1",
                          importo_cents=1000, valuta="EUR", causale="c")
        self.ts[0] += 100
        self.fc.movimento(tipo="incasso", riferimento="R2", soggetto="host:h1",
                          importo_cents=500, valuta="EUR", causale="c")
        self.assertEqual(self.fc.somme_periodo("non-un-numero"), {})
        self.assertEqual(self.fc.somme_periodo(None), {})
        self.assertEqual(self.fc.incassi_periodo("non-un-numero"), {})
        self.assertEqual(self.fc.incassi_periodo(None), {})
        self.assertEqual(self.fc.somme_periodo(self.TS), {"incasso": {"EUR": 1500}})
        self.assertEqual(self.fc.somme_periodo(self.TS, a_ts=self.TS),
                         {"incasso": {"EUR": 1000}})       # finestra chiusa
        self.assertEqual(self.fc.incassi_periodo(self.TS, a_ts=self.TS),
                         {"R1": {"cents": 1000, "valuta": "EUR"}})
        self.fabf.rompi("SUM(importo_cents) FROM libro_giornale")
        self.assertEqual(self.fc.somme_periodo(self.TS), {})
        self.assertEqual(self.fc.incassi_periodo(self.TS), {})

    def test_dac7_attribuisce_lanno_dellincasso_e_salta_le_righe_impossibili(self):
        # prenotazione completa: incasso + tassa + commissione (host dedotto da 'commissione')
        self.fc.movimento(tipo="incasso", riferimento="R1", soggetto="ospite",
                          importo_cents=12000, valuta="EUR", causale="c")
        self.fc.movimento(tipo="tassa_incassata", riferimento="R1", soggetto="comune",
                          importo_cents=2000, valuta="EUR", causale="c")
        self.fc.movimento(tipo="commissione", riferimento="R1", soggetto="host:h1",
                          importo_cents=1000, valuta="EUR", causale="c")
        self.fc.movimento(tipo="rimborso", riferimento="R1", soggetto="ospite",
                          importo_cents=300, valuta="EUR", causale="c")
        # prenotazione storica (senza riga 'commissione'): host dedotto dal bonifico
        self.fc.movimento(tipo="incasso", riferimento="R2", soggetto="ospite",
                          importo_cents=5000, valuta="EUR", causale="c")
        self.fc.movimento(tipo="payout_host", riferimento="R2", soggetto="host:h2",
                          importo_cents=4500, valuta="EUR", causale="c")
        # anno diverso: fuori dal report
        self.ts[0] = 1_500_000_000                       # 2017
        self.fc.movimento(tipo="incasso", riferimento="R3", soggetto="host:h1",
                          importo_cents=9999, valuta="EUR", causale="c")
        # data impossibile: la riga si salta, il report NON si rompe
        self.ts[0] = 10 ** 12
        self.fc.movimento(tipo="incasso", riferimento="R4", soggetto="host:h1",
                          importo_cents=7777, valuta="EUR", causale="c")
        self.ts[0] = self.TS
        agg = self.fc.aggrega_dac7(2027)
        self.assertEqual(sorted(agg.keys()), ["h1", "h2"])
        self.assertEqual(agg["h1"]["lordo"], 10000)      # 12000 - 2000 di tassa
        self.assertEqual(agg["h1"]["commissioni"], 1000)
        self.assertEqual(agg["h1"]["netto"], 9000)
        self.assertEqual(agg["h1"]["tasse"], 2000)
        self.assertEqual(agg["h1"]["rimborsi"], 300)
        self.assertEqual(agg["h1"]["trim"], {1: 10000, 2: 0, 3: 0, 4: 0})
        self.assertEqual(agg["h1"]["trim_n"], {1: 1, 2: 0, 3: 0, 4: 0})
        self.assertEqual(agg["h2"]["netto"], 4500)
        self.assertEqual(agg["h2"]["commissioni"], 500)  # ricostruita: lordo - netto
        self.assertEqual(self.fc.aggrega_dac7(2017)["h1"]["lordo"], 9999)
        for storto in ("non-un-anno", None, [2027]):
            self.assertEqual(self.fc.aggrega_dac7(storto), {}, repr(storto))

    def test_movimenti_senza_host_o_senza_incasso_non_entrano_nel_DAC7(self):
        self.fc.movimento(tipo="payout_host", riferimento="R1", soggetto="host:h1",
                          importo_cents=100, valuta="EUR", causale="c")  # niente incasso
        self.fc.movimento(tipo="incasso", riferimento="R2", soggetto="ospite",
                          importo_cents=100, valuta="EUR", causale="c")  # niente host
        self.assertEqual(self.fc.aggrega_dac7(2027), {})


class TestNoteRamiDErrore(_BaseFC):
    def test_emetti_nota_rifiuta_documenti_impossibili(self):
        base = dict(tipo="debito", riferimento="R1", soggetto="host:h1",
                    importo_cents=100, valuta="EUR", causale="c", emittente="e")
        for patch_ in [{"tipo": "boh"}, {"importo_cents": 0}, {"importo_cents": -1},
                       {"riferimento": ""}, {"soggetto": ""}, {"causale": ""},
                       {"emittente": ""}]:
            arg = dict(base)
            arg.update(patch_)
            self.assertIsNone(self.fc.emetti_nota(**arg), repr(patch_))
        arg = dict(base)
        arg["valuta"] = "EURO"                       # il giornale la rifiuta -> niente nota
        self.assertIsNone(self.fc.emetti_nota(**arg))
        self.assertEqual(self.fc.conta_movimenti(), 0)
        self.assertEqual(self.fc.note_per_riferimento("R1"), [])

    def test_nota_RIASSERITA_se_il_giornale_ha_la_riga_ma_la_nota_manca(self):
        """Crash a meta': la riga di giornale c'e', la nota no. Il replay non deve
        ne' duplicare la riga ne' lasciare il documento mancante."""
        self.fc.registra(evento_id="penale:R1", tipo="nota_debito", riferimento="R1",
                         soggetto="host:h1", conto_dare="crediti_vs_host",
                         conto_avere="ricavi_penali", importo_cents=1500, valuta="EUR",
                         causale="penale", emittente="sistema")
        self.assertEqual(self.fc.conta_movimenti(), 1)
        n = self.fc.emetti_nota(tipo="debito", riferimento="R1", soggetto="host:h1",
                                importo_cents=1500, valuta="EUR", causale="penale",
                                emittente="sistema", evento_id="penale:R1")
        self.assertEqual(n["nota_id"], "ND-2027-000001")
        self.assertEqual(self.fc.conta_movimenti(), 1)          # nessun doppione
        # e un secondo replay ora ritorna la nota gia' scritta
        n2 = self.fc.emetti_nota(tipo="debito", riferimento="R1", soggetto="host:h1",
                                 importo_cents=1500, valuta="EUR", causale="penale",
                                 emittente="sistema", evento_id="penale:R1")
        self.assertEqual(n2["nota_id"], "ND-2027-000001")
        self.assertEqual(len(self.fc.note_per_riferimento("R1")), 1)

    def test_nota_non_scrivibile_lascia_la_riga_di_giornale_e_ritorna_None(self):
        self.fabf.rompi("INSERT INTO note")
        self.assertIsNone(self.fc.emetti_nota(tipo="debito", riferimento="R1",
                                              soggetto="host:h1", importo_cents=100,
                                              valuta="EUR", causale="c", emittente="e"))
        self.fabf.sana()
        self.assertEqual(self.fc.conta_movimenti(), 1)          # il giornale e' la verita'
        self.assertEqual(self.fc.note_per_riferimento("R1"), [])

    def test_storna_nota_senza_giornale_non_storna_nulla(self):
        n = self.fc.emetti_nota(tipo="debito", riferimento="R1", soggetto="host:h1",
                                importo_cents=100, valuta="EUR", causale="c",
                                emittente="e")
        self.fabf.rompi("INSERT INTO libro_giornale")
        self.assertIsNone(self.fc.storna_nota(n["nota_id"], emittente="e", causale="x"))
        self.fabf.sana()
        self.assertEqual(self.fc.nota(n["nota_id"])["stato"], "emessa")   # NON stornata

    def test_lookup_note_input_storti_e_db_rotto(self):
        n = self.fc.emetti_nota(tipo="debito", riferimento="R1", soggetto="host:h1",
                                importo_cents=100, valuta="EUR", causale="c",
                                emittente="e")
        for cattivo in (None, "", 0, b"ND-1", ["ND-1"]):
            self.assertIsNone(self.fc.nota(cattivo), repr(cattivo))
            self.assertEqual(self.fc.note_per_riferimento(cattivo), [], repr(cattivo))
        self.assertEqual(self.fc.nota("nd-2027-000001")["nota_id"], n["nota_id"])
        self.assertIsNone(self.fc.nota("ND-2027-999999"))
        self.assertEqual(len(self.fc.note_per_riferimento("R1")), 1)
        self.fabf.rompi("SELECT * FROM note WHERE nota_id=?")
        self.assertIsNone(self.fc.nota(n["nota_id"]))
        self.fabf.rompi("SELECT * FROM note WHERE riferimento=?")
        self.assertEqual(self.fc.note_per_riferimento("R1"), [])
        self.fabf.rompi("FROM debiti WHERE stato='aperto'")
        self.assertEqual(self.fc.debiti_aperti(), [])

    def test_nessun_metodo_duplicato_nel_financial_controller(self):
        """DIFETTO TROVATO QUI: `nota()` era definito DUE volte nella stessa classe. La
        prima definizione era codice MORTO (Python tiene l'ultima) e per questo non
        compariva in nessuna copertura: una versione senza normalizzazione dell'id che
        nessuno avrebbe mai eseguito, ma che chiunque legge il file crede attiva."""
        with io.open(os.path.join(QUI, "fase177_financial_controller.py"),
                     encoding="utf-8") as f:
            albero = ast.parse(f.read())
        classi = [n for n in ast.walk(albero)
                  if isinstance(n, ast.ClassDef) and n.name == "FinancialController"]
        self.assertEqual(len(classi), 1)
        nomi = [m.name for m in classi[0].body if isinstance(m, ast.FunctionDef)]
        doppi = sorted({n for n in nomi if nomi.count(n) > 1})
        self.assertEqual(doppi, [], "metodi definiti piu' volte: %s" % doppi)


class TestPenaliOffsetRamiDErrore(_BaseFC):
    def _penale(self, rif="R1", host="h1", cents=1000, payout=None, valuta="EUR"):
        return self.fc.processa_penale(riferimento=rif, host_id=host,
                                       penale_cents=cents, valuta=valuta,
                                       payout=payout if payout is not None else self.pd)

    def test_processa_penale_rifiuta_input_impossibili(self):
        for cents in (0, -1, True, 1.5, "100", None):
            self.assertIsNone(self._penale(cents=cents), repr(cents))
        self.assertIsNone(self._penale(rif=""))
        self.assertIsNone(self._penale(host=""))
        self.assertEqual(self.fc.conta_movimenti(), 0)

    def test_processa_penale_senza_giornale_non_conferma_nulla(self):
        self.fabf.rompi("INSERT INTO libro_giornale")
        self.assertIsNone(self._penale())
        self.fabf.sana()
        self.assertEqual(self.fc.debiti_host("h1"), [])

    def test_offset_FIFO_si_ferma_appena_la_penale_e_coperta(self):
        for i, importo in enumerate((60, 30, 20, 50)):
            self.ts[0] += 1
            self.pd.registra_maturato("P%d" % i, "h1", importo, "EUR")
        r = self._penale(cents=100)
        self.assertEqual((r["offset_cents"], r["residuo_cents"]), (100, 0))
        self.assertEqual(self.pd.stato_di("P0"), "")           # 60 consumati per intero
        self.assertEqual(self.pd.stato_di("P1"), "")           # 30 consumati per intero
        self.assertEqual(self.pd.info("P2")["minori"], 10)     # 20 -> 10 (parziale)
        self.assertEqual(self.pd.info("P3")["minori"], 50)     # MAI toccato: gia' coperta
        self.assertEqual(self.fc.nota(r["nota_id"])["stato"], "saldata")
        self.assertEqual(self.fc.debiti_host("h1", stato="saldato")[0]["residuo_cents"], 0)

    def test_replay_di_una_penale_gia_compensata_non_riconsuma_nulla(self):
        self.pd.registra_maturato("P0", "h1", 500, "EUR")
        r1 = self._penale(cents=200)
        self.assertEqual(r1["offset_cents"], 200)
        self.assertEqual(self.pd.info("P0")["minori"], 300)
        r2 = self._penale(cents=200)                      # replay identico
        self.assertEqual((r2["offset_cents"], r2["residuo_cents"]), (200, 0))
        self.assertEqual(self.pd.info("P0")["minori"], 300)    # NON riconsumato
        self.assertEqual(self.fc.conta_movimenti(), 2)         # ND + un solo offset

    def test_offset_salta_le_righe_inutilizzabili(self):
        self.pd.registra_maturato("R1", "h1", 900, "EUR")       # la prenotazione stessa
        self.ts[0] += 1
        self.pd.registra_maturato("P0", "h1", 0, "EUR")         # importo zero
        self.ts[0] += 1
        self.pd.registra_maturato("P1", "h1", 400, "USD")       # altra valuta
        r = self._penale(cents=300)
        self.assertEqual((r["offset_cents"], r["residuo_cents"]), (0, 300))
        self.assertEqual(self.pd.info("R1")["minori"], 900)     # intatta
        self.assertEqual(self.pd.info("P1")["minori"], 400)     # valuta diversa: intatta
        self.assertEqual(self.fc.debiti_host("h1", stato="aperto")[0]["residuo_cents"],
                         300)

    def test_ledger_payout_che_SOLLEVA_in_lettura_lascia_il_debito_intero(self):
        r = self._penale(cents=700, payout=_LedgerCheEsplode(su=("elenca",)))
        self.assertEqual((r["offset_cents"], r["residuo_cents"]), (0, 700))
        self.assertEqual(self.fc.debiti_host("h1", stato="aperto")[0]["residuo_cents"],
                         700)

    def test_ledger_payout_che_SOLLEVA_in_scrittura_fa_STORNARE_loffset(self):
        led = _LedgerCheEsplode(righe=[{"prenotazione_id": "P0", "minori": 900,
                                        "valuta": "EUR", "stato": "maturato"}],
                                su=("imposta_importo",))
        r = self._penale(cents=700, payout=led)
        self.assertEqual((r["offset_cents"], r["residuo_cents"]), (0, 700))
        tipi = [m["tipo"] for m in self.fc.movimenti("R1")]
        self.assertEqual(tipi, ["nota_debito", "penale_offset", "storno"])
        self.assertEqual(self.fc.debiti_host("h1", stato="aperto")[0]["residuo_cents"],
                         700)

    def test_offset_stornato_e_poi_replay_non_ricompensa_lo_stesso_payout(self):
        """Il ledger non si aggiorna: offset + STORNO (saldo contabile zero). Al replay
        lo storico dal giornale torna a zero, ma l'evento di offset e' gia' bruciato:
        quel payout non viene consumato una seconda volta di nascosto."""
        self.pd.registra_maturato("P0", "h1", 900, "EUR")
        self.fabp.rompi("UPDATE payout SET minori=?, ts=?")
        r1 = self._penale(cents=700)
        self.fabp.sana()
        self.assertEqual((r1["offset_cents"], r1["residuo_cents"]), (0, 700))
        self.assertEqual(self.pd.info("P0")["minori"], 900)       # intatto
        r2 = self._penale(cents=700)                              # replay
        self.assertEqual((r2["offset_cents"], r2["residuo_cents"]), (0, 700))
        self.assertEqual(self.pd.info("P0")["minori"], 900)       # ancora intatto
        eventi = sorted(m["evento_id"] for m in self.fc.movimenti("R1"))
        self.assertEqual(eventi, ["offset:ND-2027-000001:P0", "penale:R1",
                                  "storno-offset:ND-2027-000001:P0"])

    def test_offset_senza_riga_di_giornale_non_tocca_il_ledger(self):
        """La riga di offset non e' scrivibile: il ledger payout NON si tocca (giornale
        prima, sempre). Il denaro dell'host resta dov'e'."""
        self.pd.registra_maturato("P0", "h1", 900, "EUR")
        self.fabf.rompi("INSERT INTO libro_giornale", salta=1)    # passa solo la ND
        r = self._penale(cents=700)
        self.fabf.sana()
        self.assertEqual((r["offset_cents"], r["residuo_cents"]), (0, 700))
        self.assertEqual(self.pd.info("P0")["minori"], 900)


class TestRiscossioneDebitiRamiDErrore(_BaseFC):
    def _debito(self, rif="R1", cents=1000):
        r = self.fc.processa_penale(riferimento=rif, host_id="h1", penale_cents=cents,
                                    valuta="EUR", payout=self.pd)
        self.assertEqual(r["residuo_cents"], cents)
        return r

    def test_riscuoti_input_non_validi(self):
        zero = {"riscossi_cents": 0, "debiti_saldati": 0, "debiti_aperti": 0}
        self.assertEqual(self.fc.riscuoti_debiti(host_id="", payout=self.pd), zero)
        self.assertEqual(self.fc.riscuoti_debiti(host_id=None, payout=self.pd), zero)
        self.assertEqual(self.fc.riscuoti_debiti(host_id="h1", payout=None), zero)

    def test_riscuoti_con_debiti_illeggibili_non_inventa_incassi(self):
        self.fabf.rompi("FROM debiti WHERE host_id=?")
        self.assertEqual(self.fc.riscuoti_debiti(host_id="h1", payout=self.pd),
                         {"riscossi_cents": 0, "debiti_saldati": 0, "debiti_aperti": 0})

    def test_riscossione_alla_fonte_parziale_poi_totale(self):
        self._debito(cents=1000)
        self.pd.registra_maturato("P0", "h1", 400, "EUR")
        e1 = self.fc.riscuoti_debiti(host_id="h1", payout=self.pd)
        self.assertEqual(e1, {"riscossi_cents": 400, "debiti_saldati": 0,
                              "debiti_aperti": 1})
        self.assertEqual(self.pd.stato_di("P0"), "")          # consumato per intero
        self.assertEqual(self.fc.debiti_host("h1", stato="aperto")[0]["residuo_cents"],
                         600)
        self.ts[0] += 10
        self.pd.registra_maturato("P1", "h1", 1000, "EUR")
        e2 = self.fc.riscuoti_debiti(host_id="h1", payout=self.pd)
        self.assertEqual(e2, {"riscossi_cents": 600, "debiti_saldati": 1,
                              "debiti_aperti": 0})
        self.assertEqual(self.pd.info("P1")["minori"], 400)   # 1000 - 600
        self.assertEqual(self.fc.nota("ND-2027-000001")["stato"], "saldata")
        self.assertEqual(self.fc.debiti_aperti(), [])
        # replay: nulla da riscuotere, nessun doppio consumo
        self.assertEqual(self.fc.riscuoti_debiti(host_id="h1", payout=self.pd),
                         {"riscossi_cents": 0, "debiti_saldati": 0, "debiti_aperti": 0})
        self.assertEqual(self.pd.info("P1")["minori"], 400)

    def test_riscuoti_salta_debiti_vuoti_e_il_payout_della_prenotazione_stessa(self):
        self.fabf.con.execute(
            "INSERT INTO debiti (debito_id, host_id, riferimento, residuo_cents, "
            "valuta, stato, tentativi, aggiornato_ts) "
            "VALUES ('ND-VUOTO','h1','R9',0,'EUR','aperto',0,1)")
        self.fabf.con.commit()
        self._debito(rif="R1", cents=500)
        self.pd.registra_maturato("R1", "h1", 800, "EUR")     # e' la prenotazione stessa
        e = self.fc.riscuoti_debiti(host_id="h1", payout=self.pd)
        self.assertEqual(e["riscossi_cents"], 0)
        self.assertEqual(e["debiti_aperti"], 1)              # solo quello vero
        self.assertEqual(self.pd.info("R1")["minori"], 800)  # intatta

    def test_riscuoti_si_ferma_appena_il_debito_e_coperto(self):
        self._debito(cents=400)
        self.pd.registra_maturato("P0", "h1", 400, "EUR")
        self.ts[0] += 1
        self.pd.registra_maturato("P1", "h1", 900, "EUR")
        e = self.fc.riscuoti_debiti(host_id="h1", payout=self.pd)
        self.assertEqual(e, {"riscossi_cents": 400, "debiti_saldati": 1,
                             "debiti_aperti": 0})
        self.assertEqual(self.pd.stato_di("P0"), "")          # consumato per intero
        self.assertEqual(self.pd.info("P1")["minori"], 900)   # MAI toccato

    def test_riscuoti_con_ledger_che_SOLLEVA_in_scrittura_storna_subito(self):
        self._debito(cents=500)
        led = _LedgerCheEsplode(righe=[{"prenotazione_id": "P0", "minori": 900,
                                        "valuta": "EUR", "stato": "maturato"}],
                                su=("imposta_importo",))
        e = self.fc.riscuoti_debiti(host_id="h1", payout=led)
        self.assertEqual(e, {"riscossi_cents": 0, "debiti_saldati": 0,
                             "debiti_aperti": 1})
        tipi = sorted(m["tipo"] for m in self.fc.movimenti("R1"))
        self.assertEqual(tipi, ["nota_debito", "penale_offset", "storno"])
        self.assertEqual(self.fc.debiti_host("h1", stato="aperto")[0]["residuo_cents"],
                         500)

    def test_riscuoti_con_ledger_che_solleva_o_non_si_aggiorna(self):
        self._debito(cents=500)
        e = self.fc.riscuoti_debiti(host_id="h1", payout=_LedgerCheEsplode(su=("elenca",)))
        self.assertEqual(e, {"riscossi_cents": 0, "debiti_saldati": 0,
                             "debiti_aperti": 1})
        self.pd.registra_maturato("P0", "h1", 800, "EUR")
        self.fabp.rompi("UPDATE payout SET minori=?, ts=?")
        e2 = self.fc.riscuoti_debiti(host_id="h1", payout=self.pd)
        self.fabp.sana()
        self.assertEqual(e2, {"riscossi_cents": 0, "debiti_saldati": 0,
                              "debiti_aperti": 1})
        self.assertEqual(self.pd.info("P0")["minori"], 800)  # intatta
        tipi = sorted(m["tipo"] for m in self.fc.movimenti("R1"))
        self.assertEqual(tipi, ["nota_debito", "penale_offset", "storno"])

    def test_riscuoti_senza_giornale_non_tocca_il_ledger(self):
        self._debito(cents=500)
        self.pd.registra_maturato("P0", "h1", 800, "EUR")
        self.fabf.rompi("INSERT INTO libro_giornale")
        e = self.fc.riscuoti_debiti(host_id="h1", payout=self.pd)
        self.fabf.sana()
        self.assertEqual(e["riscossi_cents"], 0)
        self.assertEqual(self.pd.info("P0")["minori"], 800)


class TestCartaEStornoRamiDErrore(_BaseFC):
    def _debito(self, rif="R1", cents=1000):
        return self.fc.processa_penale(riferimento=rif, host_id="h1",
                                       penale_cents=cents, valuta="EUR",
                                       payout=self.pd)

    def test_riscuoti_da_carta_input_non_validi(self):
        zero = {"incassati_cents": 0, "debiti_saldati": 0, "richiede_azione": 0,
                "falliti": 0}
        carta = _CartaFinta([])
        self.assertEqual(self.fc.riscuoti_da_carta(host_id="", provider_carta=carta,
                                                   customer="cus", payment_method="pm"),
                         zero)
        self.assertEqual(self.fc.riscuoti_da_carta(host_id="h1", provider_carta=None,
                                                   customer="cus", payment_method="pm"),
                         zero)
        self.assertEqual(self.fc.riscuoti_da_carta(host_id="h1", provider_carta=carta,
                                                   customer="", payment_method="pm"),
                         zero)
        self.assertEqual(self.fc.riscuoti_da_carta(host_id="h1", provider_carta=carta,
                                                   customer="cus", payment_method=""),
                         zero)
        self.assertEqual(carta.chiamate, [])          # nessun addebito tentato

    def test_riscuoti_da_carta_con_debiti_illeggibili(self):
        carta = _CartaFinta([{"stato": "riuscito", "pi": "pi_1"}])
        self.fabf.rompi("FROM debiti WHERE host_id=?")
        self.assertEqual(self.fc.riscuoti_da_carta(host_id="h1", provider_carta=carta,
                                                   customer="cus", payment_method="pm"),
                         {"incassati_cents": 0, "debiti_saldati": 0,
                          "richiede_azione": 0, "falliti": 0})
        self.assertEqual(carta.chiamate, [])

    def test_carta_non_si_martella_backoff_e_tetto_dei_tentativi(self):
        self._debito(cents=900)
        carta = _CartaFinta([{"stato": "fallito", "motivo": "card_declined"}])
        e = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=carta,
                                      customer="cus", payment_method="pm",
                                      ora_ts=1000)
        self.assertEqual(e["falliti"], 1)
        self.assertEqual(e["incassati_cents"], 0)
        deb = self.fc.debiti_host("h1", stato="aperto")[0]
        self.assertEqual(deb["residuo_cents"], 900)          # MAI saldato senza incasso
        self.assertEqual(deb["tentativi"], 1)
        self.assertEqual(deb["prossimo_ts"], 1000 + 86400)   # 1 giorno
        # ancora in backoff: non si ritenta
        carta2 = _CartaFinta([{"stato": "riuscito", "pi": "pi_X"}])
        self.fc.riscuoti_da_carta(host_id="h1", provider_carta=carta2, customer="cus",
                                  payment_method="pm", ora_ts=1000)
        self.assertEqual(carta2.chiamate, [])
        # tetto raggiunto: serve un umano
        self.fabf.con.execute("UPDATE debiti SET tentativi=4, prossimo_ts=0")
        self.fabf.con.commit()
        carta3 = _CartaFinta([{"stato": "riuscito", "pi": "pi_Y"}])
        self.fc.riscuoti_da_carta(host_id="h1", provider_carta=carta3, customer="cus",
                                  payment_method="pm", ora_ts=10 ** 9)
        self.assertEqual(carta3.chiamate, [])

    def test_carta_che_solleva_e_trattata_come_fallita(self):
        self._debito(cents=900)
        carta = _CartaFinta([RuntimeError("stripe irraggiungibile")])
        e = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=carta,
                                      customer="cus", payment_method="pm", ora_ts=500)
        self.assertEqual(e["falliti"], 1)
        self.assertEqual(self.fc.debiti_host("h1", stato="aperto")[0]["residuo_cents"],
                         900)

    def test_carta_salta_i_debiti_a_residuo_zero(self):
        self.fabf.con.execute(
            "INSERT INTO debiti (debito_id, host_id, riferimento, residuo_cents, "
            "valuta, stato, tentativi, aggiornato_ts) "
            "VALUES ('ND-VUOTO','h1','R9',0,'EUR','aperto',0,1)")
        self.fabf.con.commit()
        carta = _CartaFinta([{"stato": "riuscito", "pi": "pi_1"}])
        e = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=carta,
                                      customer="cus", payment_method="pm")
        self.assertEqual(e["incassati_cents"], 0)
        self.assertEqual(carta.chiamate, [])

    def test_carta_riuscita_salda_anche_se_lo_stato_della_nota_non_si_scrive(self):
        self._debito(cents=900)
        self.fabf.rompi("UPDATE note SET stato='saldata'")
        carta = _CartaFinta([{"stato": "riuscito", "pi": "pi_1"}])
        e = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=carta,
                                      customer="cus", payment_method="pm")
        self.fabf.sana()
        self.assertEqual(e, {"incassati_cents": 900, "debiti_saldati": 1,
                             "richiede_azione": 0, "falliti": 0})
        self.assertEqual(self.fc.debiti_host("h1", stato="saldato")[0]["residuo_cents"],
                         0)
        self.assertEqual(carta.chiamate[0]["idem"], "carta:ND-2027-000001:900")
        incassi = [m for m in self.fc.movimenti("R1") if m["tipo"] == "penale_incassata"]
        self.assertEqual(len(incassi), 1)
        self.assertEqual(incassi[0]["importo_cents"], 900)

    def test_carta_SCA_richiede_azione_e_il_backoff_non_si_scrive(self):
        self._debito(cents=900)
        self.fabf.rompi("UPDATE debiti SET tentativi=?")
        carta = _CartaFinta([{"stato": "richiede_azione", "motivo":
                              "authentication_required"}])
        e = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=carta,
                                      customer="cus", payment_method="pm", ora_ts=1000)
        self.fabf.sana()
        self.assertEqual(e["richiede_azione"], 1)
        self.assertEqual(e["incassati_cents"], 0)
        deb = self.fc.debiti_host("h1", stato="aperto")[0]
        self.assertEqual(deb["residuo_cents"], 900)
        self.assertEqual(deb["tentativi"], 0)                # il backoff non e' passato

    def test_storno_penale_restituisce_il_gia_riscosso_e_chiude_il_debito(self):
        self.pd.registra_maturato("P0", "h1", 5000, "EUR")
        r = self._debito(cents=1000)
        self.assertEqual(r["offset_cents"], 1000)
        st = self.fc.storna_penale(nota_id="nd-2027-000001", motivo="errore operatore",
                                   payout=self.pd, emittente="super-admin")
        self.assertEqual(st["nota_id"], "ND-2027-000001")
        self.assertEqual(st["nc_id"], "NC-2027-000001")
        self.assertEqual(st["riscosso_cents"], 1000)
        self.assertEqual(st["restituito_in_da_pagare"], 1000)
        self.assertIs(st["gia_stornata"], False)
        self.assertEqual(self.fc.nota("ND-2027-000001")["stato"], "stornata")
        self.assertEqual(self.fc.nota("NC-2027-000001")["storno_di"], "ND-2027-000001")
        self.assertEqual(self.fc.debiti_host("h1")[0]["stato"], "stornato")
        self.assertEqual(self.pd.stato_di("stornoND-ND-2027-000001"), "maturato")
        self.assertEqual(self.pd.da_pagare("h1", "EUR"), 4000 + 1000)
        # la riscossione automatica non lo riprende MAI piu'
        self.assertEqual(self.fc.riscuoti_debiti(host_id="h1", payout=self.pd),
                         {"riscossi_cents": 0, "debiti_saldati": 0, "debiti_aperti": 0})
        # replay dello storno: idempotente, nessun secondo accredito
        st2 = self.fc.storna_penale(nota_id="ND-2027-000001", payout=self.pd)
        self.assertEqual(st2, {"nota_id": "ND-2027-000001", "nc_id": None,
                               "riscosso_cents": 0, "restituito_in_da_pagare": 0,
                               "gia_stornata": True})
        self.assertEqual(self.pd.da_pagare("h1", "EUR"), 5000)

    def test_storno_penale_dopo_un_offset_gia_stornato_non_restituisce_nulla(self):
        """Il gia'-riscosso si legge DAL GIORNALE: offset 1000 meno storno-offset 1000
        fa ZERO. Restituire quei soldi sarebbe un regalo che non e' mai stato incassato."""
        self.pd.registra_maturato("P0", "h1", 5000, "EUR")
        self.fabp.rompi("UPDATE payout SET minori=?, ts=?")
        self._debito(cents=1000)                      # offset scritto e subito stornato
        self.fabp.sana()
        tipi = sorted(m["tipo"] for m in self.fc.movimenti("R1"))
        self.assertEqual(tipi, ["nota_debito", "penale_offset", "storno"])
        st = self.fc.storna_penale(nota_id="ND-2027-000001", payout=self.pd)
        self.assertEqual(st["riscosso_cents"], 0)
        self.assertEqual(st["restituito_in_da_pagare"], 0)
        self.assertEqual(self.pd.stato_di("stornoND-ND-2027-000001"), "")
        self.assertEqual(self.pd.da_pagare("h1", "EUR"), 5000)   # nessun accredito nuovo

    def test_storno_penale_se_il_ledger_RIFIUTA_laccredito_non_lo_dichiara(self):
        class _LedgerCheDiceNo:
            def elenca(self, *a, **k):
                return []

            def imposta_importo(self, *a):
                return False

            def rimuovi(self, *a):
                return False

            def registra_maturato(self, *a):
                return False

        self.pd.registra_maturato("P0", "h1", 5000, "EUR")
        self._debito(cents=1000)
        st = self.fc.storna_penale(nota_id="ND-2027-000001", payout=_LedgerCheDiceNo())
        self.assertEqual(st["riscosso_cents"], 1000)
        self.assertEqual(st["restituito_in_da_pagare"], 0)       # onesto: non e' passato
        self.assertEqual(self.fc.nota("ND-2027-000001")["stato"], "stornata")

    def test_storno_penale_rifiuta_note_inesistenti_o_di_credito(self):
        self.assertIsNone(self.fc.storna_penale(nota_id="ND-2027-999999"))
        self.assertIsNone(self.fc.storna_penale(nota_id=None))
        nc = self.fc.emetti_nota(tipo="credito", riferimento="R1", soggetto="host:h1",
                                 importo_cents=100, valuta="EUR", causale="c",
                                 emittente="e")
        self.assertIsNone(self.fc.storna_penale(nota_id=nc["nota_id"]))

    def test_storno_penale_con_giornale_giu_non_storna(self):
        self._debito(cents=1000)
        self.fabf.rompi("INSERT INTO libro_giornale")
        self.assertIsNone(self.fc.storna_penale(nota_id="ND-2027-000001",
                                                payout=self.pd))
        self.fabf.sana()
        self.assertEqual(self.fc.nota("ND-2027-000001")["stato"], "emessa")

    def test_storno_penale_con_ledger_giu_documenta_comunque_il_riscosso(self):
        self.pd.registra_maturato("P0", "h1", 5000, "EUR")
        self._debito(cents=1000)
        st = self.fc.storna_penale(nota_id="ND-2027-000001",
                                   payout=_LedgerCheEsplode(su=("registra_maturato",)))
        self.assertEqual(st["riscosso_cents"], 1000)
        self.assertEqual(st["restituito_in_da_pagare"], 0)   # da rifare a mano
        self.assertEqual(self.fc.nota("ND-2027-000001")["stato"], "stornata")

    def test_storno_penale_senza_payout_non_accredita_nulla(self):
        self.pd.registra_maturato("P0", "h1", 5000, "EUR")
        self._debito(cents=1000)
        st = self.fc.storna_penale(nota_id="ND-2027-000001", payout=None)
        self.assertEqual(st["riscosso_cents"], 1000)
        self.assertEqual(st["restituito_in_da_pagare"], 0)


class TestFactoryFinancialController(unittest.TestCase):
    def test_su_memoria_la_connessione_e_serializzata_e_richiudibile(self):
        fc = crea_financial_controller(":memory:", orologio=lambda: 1_800_000_000)
        fc.inizializza_schema()
        self.assertIsNotNone(fc.movimento(tipo="incasso", riferimento="R1",
                                          soggetto="host:h1", importo_cents=100,
                                          valuta="EUR", causale="c"))
        c = fc._apri()
        c.close()
        c.close()                       # doppia chiusura: tollerata, niente eccezione
        self.assertEqual(fc.conta_movimenti(), 1)

    def test_su_file_crea_la_cartella_genitore(self):
        d = tempfile.mkdtemp()
        try:
            percorso = os.path.join(d, "mai", "esistita", "conti.db")
            fc = crea_financial_controller(percorso, orologio=lambda: 1_800_000_000)
            fc.inizializza_schema()
            self.assertTrue(os.path.exists(percorso))
            fc.movimento(tipo="incasso", riferimento="R1", soggetto="host:h1",
                         importo_cents=100, valuta="EUR", causale="c")
            self.assertEqual(fc.verifica_catena()["righe"], 1)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
