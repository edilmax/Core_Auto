# -*- coding: utf-8 -*-
"""HAPPY PATH — fetta ADMIN: le 41 rotte `/api/admin/*` + `/api/bunker/*` e il flusso OPERATORE.

Che cosa dimostra (livello 1 del mandato del fondatore): per OGNI rotta di questa fetta una
richiesta VALIDA e ben formata, con la chiave/token GIUSTI e i dati corretti, risponde con lo
stato ATTESO e con un corpo JSON di STRUTTURA COERENTE. Non basta "non e' 500": ogni prova
verifica (a) lo stato esatto, (b) chiavi e tipi del corpo, (c) dove ha senso un VALORE vero
(un id, un totale, un conteggio, un importo al centesimo).

Lo stato del mondo e' vero, non finto: un host registrato (con contratto firmato), un annuncio
pubblicato con calendario aperto, una prenotazione PAGATA (webhook Stripe firmato), i dati
fiscali DAC7 completi, una chat ospite-host, un operatore admin creato dal super-admin.
Delle dipendenze esterne e' finto SOLO il confine di rete (Stripe HTTP, l'Autorita' di marca
temporale RFC 3161, Open Exchange Rates): tutto il resto e' il codice di produzione.

Ruoli (fase192): l'operatore 'admin' pieno passa; 'supporto' NON tocca i soldi (403
permesso_negato_ruolo) — e' comportamento ATTESO, quindi qui e' un'asserzione positiva.

La copertura non e' una dichiarazione: ogni chiamata a una rotta della fetta viene REGISTRATA
e a fine modulo si confronta l'insieme visitato con l'elenco delle 41 rotte (`tearDownModule`).
Se una rotta smettesse di essere esercitata, il modulo fallisce.
"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
import fase181_audit_console as _audit
import fase182_riconciliazione as _ricon
import fase184_marca_temporale as _marca
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase99_multicurrency import crea_provider_tassi
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_happy_admin"
BUNKER_PW = "SuperPw@1"
# 2.500,00 EUR a notte x 2 notti = 5.000 EUR di corrispettivo: sopra la soglia DAC7 (2.000 EUR)
# -> l'host diventa REPORTABILE e il report fiscale ha una riga vera da produrre.
PREZZO_NOTTE = 250000
_BASE = datetime.date.today() + datetime.timedelta(days=30)


def _giorno(i):
    return (_BASE + datetime.timedelta(days=i)).isoformat()


# ── le 41 rotte della fetta (metodo, percorso), dall'elenco del router ──────────────────
ROTTE_FETTA = frozenset([
    ("GET", "/api/admin/alloggi"),
    ("POST", "/api/admin/alloggio_stato"),
    ("GET", "/api/admin/audit"),
    ("POST", "/api/admin/cancella_attivita"),
    ("POST", "/api/admin/controversia/risolvi"),
    ("GET", "/api/admin/controversie"),
    ("GET", "/api/admin/diagnosi"),
    ("POST", "/api/admin/login"),
    ("GET", "/api/admin/messaggi"),
    ("GET", "/api/admin/partner"),
    ("GET", "/api/admin/prenotazioni"),
    ("POST", "/api/admin/rimborso"),
    ("GET", "/api/admin/search"),
    ("POST", "/api/admin/storno_penale"),
    ("POST", "/api/admin/verifica_stato"),
    ("GET", "/api/admin/verifiche"),
    ("GET", "/api/admin/verifiche/dettaglio"),
    ("GET", "/api/admin/verifiche/fascicolo"),
    ("GET", "/api/bunker/admin_accounts"),
    ("POST", "/api/bunker/admin_accounts"),
    ("GET", "/api/bunker/blocco_globale"),
    ("POST", "/api/bunker/blocco_globale"),
    ("GET", "/api/bunker/cambio_valuta"),
    ("POST", "/api/bunker/cambio_valuta/aggiorna"),
    ("GET", "/api/bunker/costi_tecnici"),
    ("GET", "/api/bunker/dac7_conformita"),
    ("GET", "/api/bunker/dac7_report"),
    ("GET", "/api/bunker/export_contabile"),
    ("GET", "/api/bunker/export_legale"),
    ("GET", "/api/bunker/guardiano"),
    ("GET", "/api/bunker/integrita"),
    ("GET", "/api/bunker/invarianti"),
    ("GET", "/api/bunker/log"),
    ("POST", "/api/bunker/login"),
    ("POST", "/api/bunker/logout"),
    ("POST", "/api/bunker/marca_ora"),
    ("GET", "/api/bunker/marche_temporali"),
    ("GET", "/api/bunker/prove_legali"),
    ("GET", "/api/bunker/riconciliazione"),
    ("GET", "/api/bunker/scaglioni_host"),
    ("GET", "/api/bunker/stato"),
])
VISITATE = set()          # (metodo, path) davvero esercitati con esito ATTESO
TEST_ESEGUITI = [0]       # quante prove di questo modulo sono partite


class _EmailStub:
    def __init__(self):
        self.inviate = []

    def invia(self, dest, oggetto, html):
        self.inviate.append((dest, oggetto, html))
        return True


def _fake_stripe_checkout(url, body, headers):
    """Confine di rete Stripe: crea sessione. Ritorna un id 'cs_' come quello vero."""
    import secrets
    return {"url": "https://stripe.finto/" + secrets.token_hex(4),
            "id": "cs_" + secrets.token_hex(8)}


# Cio' che Stripe DAVVERO conosce del periodo (lo specchio onesto della prenotazione vera):
# lo riempie il setUp dopo il pagamento, cosi' la riconciliazione confronta due verita'.
_STRIPE_FINTO = {"sessioni": [], "balance": []}


def _fake_stripe_lista(percorso, params, chiave):
    """Confine di rete Stripe per la RICONCILIAZIONE (liste paginate)."""
    if percorso == "checkout/sessions":
        return {"data": list(_STRIPE_FINTO["sessioni"]), "has_more": False}
    if percorso == "balance_transactions":
        return {"data": list(_STRIPE_FINTO["balance"]), "has_more": False}
    return {"data": [], "has_more": False}


def _fake_session_fetch(secret_key, cs_id, timeout=2.0):
    """Shadow-check dell'Audit Console: Stripe conferma il pagamento."""
    return {"ok": True, "payment_status": "paid", "status": "complete"}


def _fake_chiedi_marca(impronta_sha256, *, url=None, timeout=12.0, trasporto=None):
    """Confine di rete della TSA RFC 3161: l'Autorita' risponde e certifica l'ora."""
    return {"ok": True, "token": b"", "tsa": "https://tsa.finta/tsr",
            "policy": "1.2.3.4.5", "seriale": "00AB", "gen_time": int(time.time()),
            "qualificata": True}


def _fake_oxr(url):
    """Confine di rete Open Exchange Rates: pacchetto tassi (base USD, piano free)."""
    return {"base": "USD", "rates": {"USD": 1, "EUR": 0.92, "GBP": 0.79, "JPY": 157.0}}


class HappyAdmin(unittest.TestCase):
    """Uno stato del mondo VERO per ogni prova (setUp isolato: nessuna prova eredita
    i movimenti di soldi dell'altra)."""

    maxDiff = None

    # ══════════════════════ preparazione dello stato ══════════════════════
    def setUp(self):
        TEST_ESEGUITI[0] += 1
        d = self.d = tempfile.mkdtemp(prefix="happy_admin_")
        os.makedirs(os.path.join(d, "backup"), exist_ok=True)
        with open(os.path.join(d, "backup", "finanza.db.gz"), "wb") as f:
            f.write(b"backup-finto")     # il watchdog misura la freschezza dei *.db.gz
        with open(os.path.join(d, "app.log"), "w", encoding="utf-8") as f:
            f.write("2026-07-28 09:00:00 INFO core_auto.server avvio\n")
            f.write("2026-07-28 09:01:00 CRITICAL core_auto.server BUNKER: accesso NEGATO\n")

        # --- confini di rete: gli UNICI pezzi finti ---
        self._env0 = {k: os.environ.get(k) for k in
                      ("DATA_DIR", "BACKUP_DIR", "MARCA_TEMPORALE", "BLOCCO_GLOBALE")}
        os.environ["DATA_DIR"] = d
        os.environ["BACKUP_DIR"] = os.path.join(d, "backup")
        os.environ["MARCA_TEMPORALE"] = "1"
        os.environ.pop("BLOCCO_GLOBALE", None)
        # NB: `_fetch_reale` di fase85 e' uno @staticmethod -> si salva e si rimette
        # l'OGGETTO staticmethod (dal __dict__), non la funzione nuda: rimettendo la
        # funzione nuda diventerebbe un metodo d'istanza e il ripristino sarebbe finto.
        self._orig = (_stripe.ProviderStripe.__dict__["_fetch_reale"], _ricon._fetch_reale,
                      _audit.stripe_session_fetch, _marca.chiedi_marca)
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_stripe_checkout)
        _ricon._fetch_reale = _fake_stripe_lista
        _audit.stripe_session_fetch = _fake_session_fetch
        _marca.chiedi_marca = _fake_chiedi_marca

        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"H" * 32, con_registrazione_host=True,
            db_catalogo=d + "/catalogo.db", db_inventario=d + "/inventario.db",
            db_registro_host=d + "/registro_host.db", db_accettazioni=d + "/accettazioni.db",
            db_pendenti=d + "/pendenti.db", db_payout=d + "/payout.db",
            db_garanzia=d + "/garanzia.db", db_finanza=d + "/finanza.db",
            db_partner=d + "/partner.db", db_messaggi=d + "/messaggi.db",
            db_tassa_comunale=d + "/tassa.db", db_marche=d + "/marche.db",
            db_kyc=d + "/kyc.db", db_admin_accounts=d + "/admin_accounts.db",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_finta", stripe_webhook_secret=WH,
            stripe_success_url="https://bookinvip.com/grazie",
            stripe_cancel_url="https://bookinvip.com/annullato",
            bunker_password=BUNKER_PW))
        self.sis.email_provider = _EmailStub()
        self.sis.connect.trasferisci = lambda *a, **k: "tr_finto"
        # cambio valuta ACCESO col provider vero, sola rete finta (fase99)
        self.sis.tassi = crea_provider_tassi("app_id_finto", fetch=_fake_oxr)
        self.assertTrue(self.sis.tassi.aggiorna(), "setup: cache tassi non scaldata")

        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        self.AK = {"X-Admin-Key": "ak"}

        # --- super-admin dentro al Bunker (2° muro) ---
        st, out = self.g("POST", "/api/bunker/login", {"codice": BUNKER_PW}, self.AK)
        self.assertEqual(st, 200, out)
        self.sess = out["sessione"]
        self.AKB = {"X-Admin-Key": "ak", "X-Bunker-Session": self.sess}

        # --- host VERO: registrazione col contratto firmato ---
        st, out = self.g("POST", "/api/host/registrazione",
                         {"email": "host@happyadmin.it", "password": "password1",
                          "accetta_termini": True, "accetta_clausole": True,
                          "accetta_privacy": True, "doc_sha256": doc_sha256(),
                          "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(st, 201, out)
        self.host_id = out["host_id"]
        self.HT = {"X-Host-Token": out["token"]}

        # --- annuncio pubblicato + calendario aperto ---
        self.slug = "villa-happy-admin"
        st, out = self.g("POST", "/api/host/pubblica",
                         {"slug": self.slug, "titolo": "Villa Happy Admin",
                          "citta": "Roma", "prezzo_notte_cents": PREZZO_NOTTE,
                          "capacita": 4, "politica_cancellazione": "flessibile"}, self.HT)
        self.assertEqual(st, 201, out)
        st, out = self.g("POST", "/api/host/disponibilita_range",
                         {"alloggio_id": self.slug, "da": _giorno(0), "a": _giorno(10),
                          "unita_totali": 1, "prezzo_netto_cents": PREZZO_NOTTE}, self.HT)
        self.assertEqual(st, 200, out)

        # --- dati fiscali DAC7 completi (l'host e' in regola) ---
        st, out = self.g("POST", "/api/host/dati_fiscali",
                         {"codice_fiscale": "RSSMRA80A01H501U", "partita_iva": "12345678901",
                          "indirizzo_fiscale": "Via Roma 1, 00184 Roma", "paese": "IT",
                          "iban": "IT60X0542811101000000123456", "tipo_soggetto": "privato",
                          "data_nascita": "1980-01-01"}, self.HT)
        self.assertEqual((st, out["mancanti"]), (200, []), out)

        # --- prenotazione VERA, pagata (webhook Stripe firmato) ---
        self.ci, self.co = _giorno(2), _giorno(4)
        st, q = self.g("POST", "/api/concierge/quote",
                       {"alloggio_id": self.slug, "check_in": self.ci,
                        "check_out": self.co, "party": 2})
        self.assertEqual(st, 200, q)
        self.totale = int(q["totale_cents"])
        st, b = self.g("POST", "/api/concierge/book",
                       {"quote_token": q["quote_token"], "email": "ospite@happyadmin.it",
                        "lang": "it"})
        self.assertEqual(st, 201, b)
        self.rif, self.vt = b["riferimento"], b["voucher_token"]
        self._paga(self.rif)
        self.assertEqual(self._stato_pren(), "pagato", "setup: pagamento non confermato")
        self.idem = (self.sis.pagamenti_pendenti.info(self.rif) or {}).get("idem_key")
        self.assertTrue(self.idem, "setup: idem_key assente")
        # cio' che Stripe conosce del periodo: la STESSA sessione pagata e lo stesso addebito
        _STRIPE_FINTO["sessioni"] = [{"id": "cs_" + self.rif[:10], "payment_status": "paid",
                                      "amount_total": self.totale, "currency": "eur",
                                      "metadata": {"riferimento": self.rif}}]
        _STRIPE_FINTO["balance"] = [{"reporting_category": "charge", "currency": "eur",
                                     "amount": self.totale}]

        # --- una chat ospite->host sulla prenotazione (l'arbitro deve poterla leggere) ---
        st, out = self.g("POST", "/api/voucher/messaggio",
                         {"voucher_token": self.vt, "testo": "Il condizionatore non parte"})
        self.assertEqual(st, 201, out)

    def tearDown(self):
        _STRIPE_FINTO["sessioni"], _STRIPE_FINTO["balance"] = [], []
        (_stripe.ProviderStripe._fetch_reale, _ricon._fetch_reale,
         _audit.stripe_session_fetch, _marca.chiedi_marca) = self._orig
        for k, v in self._env0.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.d, ignore_errors=True)

    # ══════════════════════ attrezzi ══════════════════════
    def g(self, metodo, path, corpo=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(corpo) if corpo is not None else None,
                               headers or {})

    def rotta(self, metodo, path, atteso, corpo=None, headers=None, query=None):
        """Esercita una rotta della fetta e PRETENDE lo stato atteso. Registra la copertura
        solo quando lo stato e' quello giusto: una rotta 'coperta' male non conta."""
        st, out = self.g(metodo, path, corpo, headers, query)
        self.assertEqual(st, atteso, "%s %s -> %d %r" % (metodo, path, st, out))
        self.assertIsInstance(out, dict, "%s %s: corpo non JSON-oggetto" % (metodo, path))
        VISITATE.add((metodo, path))
        return out

    def _paga(self, rif):
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": "cs_" + rif[:10],
                                             "metadata": {"riferimento": rif}}}})
        st, out = self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                                  {"Stripe-Signature": firma_di_test(pl, WH,
                                                                     int(time.time()))})
        self.assertEqual(st, 200, out)

    def _stato_pren(self):
        return (self.sis.pagamenti_pendenti.info(self.rif) or {}).get("stato")

    def _chiavi(self, corpo, *chiavi):
        for k in chiavi:
            self.assertIn(k, corpo, "manca la chiave '%s' in %r" % (k, corpo))

    def _crea_operatore(self, email, ruolo):
        """Il super-admin crea un operatore (fase192) e lo fa entrare: -> token X-Admin-Op."""
        out = self.rotta("POST", "/api/bunker/admin_accounts", 200,
                         {"azione": "crea", "email": email, "password": "OperPw2026",
                          "ruolo": ruolo}, self.AKB)
        self.assertEqual(out, {"ok": True, "email": email, "ruolo": ruolo})
        login = self.rotta("POST", "/api/admin/login", 200,
                           {"email": email, "password": "OperPw2026"})
        self.assertEqual((login["ok"], login["ruolo"], login["operatore"]),
                         (True, ruolo, email), login)
        self.assertTrue(login["op_token"].startswith("op|" + email + "|" + ruolo + "|"),
                        login["op_token"])
        return {"X-Admin-Op": login["op_token"]}

    # ══════════════════════ ADMIN — elenchi e ricerca ══════════════════════
    def test_admin_elenchi_e_ricerca(self):
        """alloggi (paginato) · prenotazioni · search unificata · partner: dati VERI."""
        out = self.rotta("GET", "/api/admin/alloggi", 200, headers=self.AK)
        self._chiavi(out, "alloggi", "page", "limit", "totale", "pagine")
        self.assertEqual((out["page"], out["limit"], out["totale"], out["pagine"]),
                         (1, 20, 1, 1), out)
        self.assertEqual(out["alloggi"][0]["slug"], self.slug)

        out = self.rotta("GET", "/api/admin/prenotazioni", 200, headers=self.AK,
                         query={"alloggio": self.slug})
        self.assertIsInstance(out["prenotazioni"], list)
        self.assertEqual(len(out["prenotazioni"]), 1, out)

        out = self.rotta("GET", "/api/admin/search", 200, headers=self.AK,
                         query={"q": "happy"})
        self._chiavi(out, "q", "page", "limit", "annunci", "host", "prenotazioni",
                     "totali", "totale")
        self.assertEqual(out["q"], "happy")
        self.assertEqual(out["totali"]["annunci"], 1, out)
        self.assertEqual(out["totali"]["host"], 1, out)
        self.assertEqual(out["annunci"][0]["slug"], self.slug)
        self.assertEqual(out["host"][0]["host_id"], self.host_id)
        # FILTRO DI SICUREZZA: la ricerca operativa non fa uscire i dati fiscali
        for h in out["host"]:
            for vietato in ("iban", "codice_fiscale", "partita_iva"):
                self.assertNotIn(vietato, h, "la ricerca admin espone %s" % vietato)

        st, _ = self.g("POST", "/api/partner",
                       {"nome": "Anna Creator", "email": "anna@happyadmin.it",
                        "tipo": "creator", "citta": "Roma", "consenso": True})
        self.assertEqual(st, 201)
        out = self.rotta("GET", "/api/admin/partner", 200, headers=self.AK)
        self.assertEqual(out["totale"], 1, out)
        self.assertEqual(out["candidati"][0]["email"], "anna@happyadmin.it")

    def test_admin_alloggi_filtro_citta(self):
        """GUARDIA del difetto PROVATO 2026-07-28: il filtro `citta` del Field operativo non
        trovava MAI nulla. La colonna conserva la citta' come l'ha scritta l'host ("Roma") e
        `fase57.tutti_alloggi_pagina` cercava il parametro abbassato a minuscolo ("roma"),
        confrontato con `=` (case-SENSITIVE in SQLite) -> 0 risultati su un annuncio che
        c'era eccome. Rosso sul codice vecchio: la prima riga qui sotto tornava totale=0."""
        out = self.rotta("GET", "/api/admin/alloggi", 200, headers=self.AK,
                         query={"citta": "Roma"})
        self.assertEqual(out["totale"], 1, out)
        self.assertEqual([a["slug"] for a in out["alloggi"]], [self.slug])
        # insensibile alle maiuscole su ENTRAMBI i lati: l'operatore scrive come vuole
        for scritta in ("roma", "ROMA", "  Roma "):
            o = self.g("GET", "/api/admin/alloggi", None, self.AK, {"citta": scritta})[1]
            self.assertEqual(o["totale"], 1, "citta=%r -> %r" % (scritta, o))
        # e combinato con gli altri filtri continua a stringere, non ad annullare
        o = self.g("GET", "/api/admin/alloggi", None, self.AK,
                   {"citta": "Roma", "stato": "pubblicato", "host_id": self.host_id})[1]
        self.assertEqual(o["totale"], 1, o)
        # una citta' che non esiste resta a zero (il filtro filtra davvero)
        o = self.g("GET", "/api/admin/alloggi", None, self.AK, {"citta": "Milano"})[1]
        self.assertEqual((o["totale"], o["alloggi"]), (0, []), o)

    def test_admin_messaggi_e_diagnosi(self):
        """L'arbitro legge la chat della prenotazione; l'auto-diagnosi risponde read-only."""
        out = self.rotta("GET", "/api/admin/messaggi", 200, headers=self.AK,
                         query={"riferimento": self.rif})
        self.assertEqual(len(out["messaggi"]), 1, out)
        self.assertEqual(out["messaggi"][0]["mittente"], "ospite")
        self.assertEqual(out["messaggi"][0]["testo"], "Il condizionatore non parte")
        self.assertIsInstance(out["messaggi"][0]["ts"], int)

        out = self.rotta("GET", "/api/admin/diagnosi", 200, headers=self.AK)
        self._chiavi(out, "ok", "allarmi", "misure")
        self.assertIsInstance(out["allarmi"], list)
        self.assertTrue(out["misure"]["catena"]["ok"], out["misure"]["catena"])
        for atteso in ("finanza", "catalogo", "registro_host", "pendenti"):
            self.assertIn(atteso, out["misure"]["db_presenti"], out["misure"])
        self.assertIsNotNone(out["misure"]["eta_backup_sec"], "backup non visto")

    def test_admin_audit_console_scheda_prenotazione(self):
        """Scheda contabile unica da un riferimento vero: semaforo VERDE (Stripe conferma)."""
        out = self.rotta("GET", "/api/admin/audit", 200, headers=self.AK,
                         query={"id": self.rif})
        self.assertEqual(out["tipo"], "riferimento")
        self.assertEqual(out["riferimento"], self.rif)
        self.assertEqual(out["prenotazione"]["stato"], "pagato")
        self.assertEqual(out["prenotazione"]["alloggio_id"], self.slug)
        self.assertEqual(out["semaforo"]["complessivo"], "verde", out["semaforo"])
        self.assertEqual(out["semaforo"]["stripe"]["payment_status"], "paid")
        incassi = [m for m in out["movimenti"] if m["tipo"] == "incasso"]
        self.assertEqual(len(incassi), 1, out["movimenti"])
        self.assertEqual(incassi[0]["importo_cents"], self.totale)
        # whitelist: la scheda non porta fuori il corpo grezzo ne' la chiave d'idempotenza
        self.assertNotIn("corpo_json", out["prenotazione"])
        self.assertNotIn("idem_key", out["prenotazione"])

    def test_admin_audit_console_scheda_host(self):
        """Lo stesso ingresso risolve anche un host_id: paga-per-host e debiti."""
        out = self.rotta("GET", "/api/admin/audit", 200, headers=self.AK,
                         query={"id": self.host_id})
        self.assertEqual(out["tipo"], "host")
        self.assertEqual(out["host_id"], self.host_id)
        self.assertEqual(out["identita"]["email"], "host@happyadmin.it")
        self.assertEqual(out["debiti_aperti"], [])
        self.assertGreater(out["payout"]["EUR"]["maturato"], 0, out["payout"])

    # ══════════════════════ ADMIN — verifiche & legale (KYC) ══════════════════════
    def test_admin_verifiche_lista_dettaglio_fascicolo_e_stato(self):
        """Il giro completo dell'istruttoria: lista -> dettaglio (mascherato) -> fascicolo
        (Bunker) -> approvazione della verifica."""
        out = self.rotta("GET", "/api/admin/verifiche", 200, headers=self.AK)
        self._chiavi(out, "host", "totale", "contatori")
        self.assertEqual(out["totale"], 1, out)
        voce = out["host"][0]
        self.assertEqual(voce["host_id"], self.host_id)
        self.assertTrue(voce["documenti"]["contratto"], voce)   # ha firmato in registrazione
        self.assertTrue(voce["documenti"]["fiscale"], voce)     # DAC7 completo
        self.assertFalse(voce["documenti"]["in_regola"], voce)  # manca la verifica manuale
        self.assertEqual(out["contatori"]["incompleti"], 1, out["contatori"])

        det = self.rotta("GET", "/api/admin/verifiche/dettaglio", 200, headers=self.AK,
                         query={"host_id": self.host_id})
        self.assertEqual(det["email"], "host@happyadmin.it")
        self.assertEqual(det["fiscale"]["mancanti"], [])
        self.assertEqual(det["fiscale"]["paese"], "IT")
        self.assertTrue(det["fiscale"]["iban_maschera"].endswith("3456"))
        self.assertNotIn("IT60X", det["fiscale"]["iban_maschera"])   # IBAN mai in chiaro
        self.assertTrue(det["contratto_prove"], det)
        self.assertTrue(det["contratto_prove"][0]["integra"])
        # il Field NON vede IP / impronta / firma: quelli stanno nel Bunker
        self.assertEqual(set(det["contratto_prove"][0]),
                         {"documento", "versione", "integra"})

        fas = self.rotta("GET", "/api/admin/verifiche/fascicolo", 200, headers=self.AKB,
                         query={"host_id": self.host_id})["fascicolo"]
        self.assertEqual(fas["host_id"], self.host_id)
        self.assertEqual(fas["fiscale"]["iban"], "IT60X0542811101000000123456")
        self.assertEqual(fas["identita"]["email"], "host@happyadmin.it")
        self.assertTrue(fas["contratto_prove"][0]["firma"])
        self.assertIn("DSA art.30", fas["nota_legale"])

        ver = self.rotta("POST", "/api/admin/verifica_stato", 200,
                         {"host_id": self.host_id, "stato": "verificato",
                          "motivo": "documenti controllati"}, self.AKB)
        self.assertEqual((ver["ok"], ver["host_id"], ver["stato"]),
                         (True, self.host_id, "verificato"))
        self.assertIsInstance(ver["payout_riprovati"], int)
        dopo = self.rotta("GET", "/api/admin/verifiche", 200, headers=self.AK,
                          query={"stato": "verificati"})
        self.assertEqual(dopo["totale"], 1, dopo)
        doc = dopo["host"][0]["documenti"]
        self.assertEqual(doc["verifica"], "verificato")
        self.assertEqual(dopo["contatori"]["verificati"], 1, dopo["contatori"])
        # onesta' del semaforo: 'in_regola' vuole ANCHE il conto Stripe Connect, che questo
        # host non ha ancora collegato -> resta fra gli incompleti, e la lista lo dice.
        self.assertFalse(doc["stripe"], doc)
        self.assertFalse(doc["in_regola"], doc)

    # ══════════════════════ ADMIN — moderazione ══════════════════════
    def test_admin_alloggio_stato_sospende_e_ripubblica(self):
        """La moderazione ha effetto VERO: sospeso -> sparisce dalla vetrina; ripubblicato
        -> ricompare."""
        self.assertEqual(len(self.g("GET", "/api/catalogo")[1]["risultati"]), 1)
        out = self.rotta("POST", "/api/admin/alloggio_stato", 200,
                         {"slug": self.slug, "stato": "sospeso"}, self.AKB)
        self.assertEqual(out, {"stato": "sospeso"})
        self.assertEqual(self.g("GET", "/api/catalogo")[1]["risultati"], [])
        out = self.rotta("POST", "/api/admin/alloggio_stato", 200,
                         {"slug": self.slug, "stato": "pubblicato"}, self.AKB)
        self.assertEqual(out, {"stato": "pubblicato"})
        self.assertEqual(len(self.g("GET", "/api/catalogo")[1]["risultati"]), 1)

    def test_admin_cancella_attivita_host_senza_obblighi(self):
        """'Cancella tutto' su un host SENZA soldi ne' persone in ballo: 0 residui, verificati."""
        st, out = self.g("POST", "/api/host/registrazione",
                         {"email": "host2@happyadmin.it", "password": "password2",
                          "accetta_termini": True, "accetta_clausole": True,
                          "accetta_privacy": True, "doc_sha256": doc_sha256(),
                          "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(st, 201, out)
        h2 = out["host_id"]
        rep = self.rotta("POST", "/api/admin/cancella_attivita", 200,
                         {"host_id": h2}, self.AKB)
        self.assertEqual((rep["ok"], rep["host_id"]), (True, h2), rep)
        self.assertEqual([v for v in rep["residui"].values() if v], [], rep["residui"])
        self.assertIsNone(self.sis.registro_host.info_host(h2), "host ancora presente")
        # l'host VERO (con la prenotazione pagata) non e' stato toccato
        self.assertIsNotNone(self.sis.registro_host.info_host(self.host_id))

    # ══════════════════════ ADMIN — soldi ══════════════════════
    def test_admin_rimborso_libera_date_e_mette_i_soldi_in_sicurezza(self):
        """Rimborso admin: date libere, payout NON pagabile, escrow chiuso, ledger coerente."""
        out = self.rotta("POST", "/api/admin/rimborso", 200,
                         {"alloggio_id": self.slug, "check_in": self.ci,
                          "check_out": self.co, "idem_key": self.idem}, self.AKB)
        self.assertEqual(out["stato"], "rimborsato")
        self.assertTrue(out["date_liberate"])
        self.assertIs(out["idempotente"], False)
        self.assertEqual(self._stato_pren(), "rimborsato")
        self.assertEqual((self.sis.payout.riepilogo(self.host_id) or {})
                         .get("EUR", {}).get("maturato", 0), 0,
                         "payout ancora pagabile su prenotazione rimborsata")
        self.assertEqual((self.sis.garanzia.stato(self.rif) or {}).get("stato"),
                         "annullato")
        rimborsi = [m for m in self.sis.finanza.movimenti(self.rif)
                    if m["tipo"] == "rimborso"]
        self.assertEqual(len(rimborsi), 1, rimborsi)
        self.assertEqual(rimborsi[0]["importo_cents"], self.totale)

    def test_admin_controversia_elenco_e_risoluzione_split(self):
        """L'ospite contesta; l'arbitro decide il 40% e i due ledger si riallineano."""
        st, out = self.g("POST", "/api/garanzia/contesta",
                         {"voucher_token": self.vt, "motivo": "casa non conforme"})
        self.assertEqual(st, 200, out)

        el = self.rotta("GET", "/api/admin/controversie", 200, headers=self.AK)
        self.assertEqual(len(el["controversie"]), 1, el)
        c = el["controversie"][0]
        self.assertEqual(c["prenotazione_id"], self.rif)
        self.assertEqual(c["alloggio_id"], self.slug)
        self.assertEqual(c["titolo"], "Villa Happy Admin")
        self.assertEqual(c["motivo"], "casa non conforme")
        importo = int(c["importo_host_cents"])
        self.assertGreater(importo, 0)

        ris = self.rotta("POST", "/api/admin/controversia/risolvi", 200,
                         {"riferimento": self.rif, "percentuale_ospite": 40}, self.AKB)
        atteso_ospite = int(importo * 40 / 100)
        self.assertEqual(ris["stato"], "risolta")
        self.assertEqual(ris["riferimento"], self.rif)
        self.assertEqual(ris["rimborso_cliente_cents"], atteso_ospite)
        self.assertEqual(ris["va_all_host_cents"], importo - atteso_ospite)
        # conservazione al centesimo + ledger payout riallineato alla quota host
        self.assertEqual(ris["rimborso_cliente_cents"] + ris["va_all_host_cents"], importo)
        self.assertEqual((self.sis.payout.info(self.rif) or {}).get("minori"),
                         importo - atteso_ospite)
        self.assertEqual((self.sis.garanzia.stato(self.rif) or {}).get("stato"), "risolto")
        self.assertEqual(self.g("GET", "/api/admin/controversie", headers=self.AK)[1]
                         ["controversie"], [])

    def test_admin_storno_penale_emette_la_nota_di_credito(self):
        """Penale sbagliata -> NC contraria: il giornale non si tocca mai, la ND va 'stornata'."""
        esito = self.sis.finanza.processa_penale(
            riferimento=self.rif, host_id=self.host_id, penale_cents=45000,
            valuta="EUR", payout=self.sis.payout, emittente="sistema")
        self.assertIsNotNone(esito, "setup: penale non emessa")
        nota_id = esito["nota_id"]

        out = self.rotta("POST", "/api/admin/storno_penale", 200,
                         {"nota_id": nota_id, "motivo": "cancellazione non imputabile"},
                         self.AKB)
        self.assertEqual(out["nota_id"], nota_id)
        self.assertTrue(str(out["nc_id"]).startswith("NC-"), out)
        self.assertIs(out["gia_stornata"], False)
        self.assertEqual(self.sis.finanza.nota(nota_id)["stato"], "stornata")
        nc = self.sis.finanza.nota(out["nc_id"])
        self.assertEqual((nc["tipo"], nc["importo_cents"], nc["valuta"]),
                         ("credito", 45000, "EUR"))
        self.assertTrue(self.sis.finanza.verifica_catena()["ok"], "catena rotta")

    # ══════════════════════ ADMIN — login (root + operatore) ══════════════════════
    def test_admin_login_root_emette_il_cookie_di_pagina(self):
        out = self.rotta("POST", "/api/admin/login", 200, {}, self.AK)
        self.assertEqual((out["ok"], out["ruolo"]), (True, "admin"))
        nomi = [c[0] for c in out["_cookie"]]
        self.assertEqual(nomi, ["bv_admin"])
        self.assertEqual(out["_cookie"][0][2], 12 * 3600)

    def test_operatore_admin_pieno_puo_tutto(self):
        """Operatore 'admin' (fase192): entra con email+password e opera come la root."""
        op = self._crea_operatore("capo@happyadmin.it", "admin")
        out = self.rotta("GET", "/api/admin/prenotazioni", 200, headers=op)
        self.assertEqual(len(out["prenotazioni"]), 1, out)
        # con il token operatore 'admin' anche le azioni-soldi passano (con il Bunker)
        opb = dict(op)
        opb["X-Bunker-Session"] = self.sess
        out = self.rotta("POST", "/api/admin/rimborso", 200,
                         {"alloggio_id": self.slug, "check_in": self.ci,
                          "check_out": self.co, "idem_key": self.idem}, opb)
        self.assertEqual(out["stato"], "rimborsato")

    def test_operatore_supporto_non_tocca_i_soldi(self):
        """Comportamento ATTESO: 'supporto' legge e assiste, ma le azioni-soldi/distruttive
        rispondono 403 permesso_negato_ruolo (e NON cambiano nulla)."""
        op = self._crea_operatore("aiuto@happyadmin.it", "supporto")
        # letture: passa
        out = self.rotta("GET", "/api/admin/prenotazioni", 200, headers=op)
        self.assertEqual(len(out["prenotazioni"]), 1, out)
        opb = dict(op)
        opb["X-Bunker-Session"] = self.sess
        for metodo, path, corpo in (
                ("POST", "/api/admin/rimborso",
                 {"alloggio_id": self.slug, "check_in": self.ci, "check_out": self.co,
                  "idem_key": self.idem}),
                ("POST", "/api/admin/alloggio_stato",
                 {"slug": self.slug, "stato": "sospeso"}),
                ("POST", "/api/admin/cancella_attivita", {"host_id": self.host_id}),
                ("POST", "/api/admin/controversia/risolvi",
                 {"riferimento": self.rif, "percentuale_ospite": 100}),
                ("POST", "/api/admin/storno_penale",
                 {"nota_id": "ND-2026-000001", "motivo": "no"})):
            st, out = self.g(metodo, path, corpo, opb)
            self.assertEqual((st, out.get("errore")), (403, "permesso_negato_ruolo"),
                             "%s %s -> %d %r" % (metodo, path, st, out))
        # NULLA e' cambiato: prenotazione ancora pagata, annuncio ancora in vetrina,
        # host ancora vivo, escrow intatto
        self.assertEqual(self._stato_pren(), "pagato")
        self.assertEqual(len(self.g("GET", "/api/catalogo")[1]["risultati"]), 1)
        self.assertIsNotNone(self.sis.registro_host.info_host(self.host_id))
        self.assertEqual((self.sis.garanzia.stato(self.rif) or {}).get("stato"),
                         "in_garanzia")

    # ══════════════════════ BUNKER — ingresso e uscita ══════════════════════
    def test_bunker_login_e_logout_revoca_la_sessione(self):
        out = self.rotta("POST", "/api/bunker/login", 200, {"codice": BUNKER_PW}, self.AK)
        self._chiavi(out, "ok", "sessione", "scade_tra_sec", "modo", "_cookie")
        self.assertIs(out["ok"], True)
        self.assertEqual((out["scade_tra_sec"], out["modo"]), (900, "password"))
        sess = out["sessione"]
        h = {"X-Admin-Key": "ak", "X-Bunker-Session": sess}
        self.assertEqual(self.g("GET", "/api/bunker/stato", headers=h)[0], 200)

        out = self.rotta("POST", "/api/bunker/logout", 200, {}, h)
        self.assertIs(out["ok"], True)
        self.assertEqual(len(out["_cookie"]), 1, out["_cookie"])
        self.assertEqual(tuple(out["_cookie"][0]), ("bv_bunker", "", 0))
        # LOGOUT SERVER-SIDE: quel token e' morto SUBITO
        self.assertEqual(self.g("GET", "/api/bunker/stato", headers=h)[0], 403,
                         "la sessione revocata funziona ancora")

    def test_bunker_stato_sala_controllo(self):
        out = self.rotta("GET", "/api/bunker/stato", 200, headers=self.AKB)
        self.assertIs(out["bunker"], True)
        self._chiavi(out["diagnosi"], "ok", "allarmi", "misure")
        self.assertTrue(out["diagnosi"]["misure"]["catena"]["ok"])

    # ══════════════════════ BUNKER — contabilita' e prove ══════════════════════
    def test_bunker_integrita_e_log(self):
        out = self.rotta("GET", "/api/bunker/integrita", 200, headers=self.AKB)
        self._chiavi(out, "catena", "diagnosi", "debiti")
        self.assertTrue(out["catena"]["ok"], out["catena"])
        self.assertGreater(out["catena"]["righe"], 0)
        self.assertEqual(out["debiti"]["aperti"], 0)
        self.assertEqual(out["debiti"]["totale_cents"], 0)

        log = self.rotta("GET", "/api/bunker/log", 200, headers=self.AKB, query={"n": "50"})
        self.assertEqual(log["file"], "app.log")
        self.assertEqual(log["n"], len(log["righe"]))
        self.assertIn("BUNKER: accesso NEGATO", "\n".join(log["righe"]))

    def test_bunker_export_contabile_certificato(self):
        out = self.rotta("GET", "/api/bunker/export_contabile", 200, headers=self.AKB)
        self.assertIs(out["catena_integra"], True)
        self.assertIs(out["corrotto"], False)
        self.assertIn("# FINE ESTRATTO - INTEGRITÀ VERIFICATA:", out["csv"])
        self.assertIn(self.rif, out["csv"])          # la prenotazione vera c'e'

    def test_bunker_export_legale_dossier(self):
        out = self.rotta("GET", "/api/bunker/export_legale", 200, headers=self.AKB)
        self.assertEqual(out["formato"], "csv")
        self.assertIs(out["certificato"], True)
        self.assertIn("# FINE DOSSIER - INTEGRITÀ:", out["contenuto"])
        self.assertIn(self.host_id, out["contenuto"])
        js = self.rotta("GET", "/api/bunker/export_legale", 200, headers=self.AKB,
                        query={"formato": "json"})
        self.assertEqual(js["formato"], "json")
        self.assertIs(js["certificato"], True)

    def test_bunker_prove_legali_complete(self):
        out = self.rotta("GET", "/api/bunker/prove_legali", 200, headers=self.AKB)
        self.assertEqual(out["manomesse"], 0)
        self.assertIs(out["integrita_ok"], True)
        self.assertEqual(out["totale"], len(out["prove"]))
        self.assertGreaterEqual(out["totale"], 1, out)
        p = [x for x in out["prove"] if x["host_id"] == self.host_id][0]
        self._chiavi(p, "documento", "versione", "doc_sha256", "ip", "dispositivo",
                     "accettato_ts", "accettato_utc", "clausole_vessatorie",
                     "firma_hmac_sha256", "integra")
        self.assertIs(p["integra"], True)
        self.assertIs(p["clausole_vessatorie"], True)
        self.assertEqual(p["versione"], CONTRATTO_HOST_VERSIONE)
        self.assertEqual(len(p["firma_hmac_sha256"]), 64)
        self.assertTrue(p["accettato_utc"].endswith("UTC"))

    def test_bunker_costi_tecnici(self):
        out = self.rotta("GET", "/api/bunker/costi_tecnici", 200, headers=self.AKB)
        self._chiavi(out, "incassate", "perdite", "coperto_cents", "per_valuta", "letti",
                     "tariffa_tecnica_bps", "nota", "classificazione_fiscale")
        self.assertEqual(out["tariffa_tecnica_bps"], 300)      # 3% come da README
        self.assertEqual(out["letti"], 1)
        self.assertEqual(out["incassate"]["conteggio"], 1, out["incassate"])
        self.assertEqual(out["perdite"]["conteggio"], 0, out["perdite"])
        # valore VERO al centesimo: 3% di 5.000,00 EUR di corrispettivo = 150,00 EUR
        self.assertEqual(out["incassate"]["cents"], PREZZO_NOTTE * 2 * 300 // 10000)
        self.assertEqual(out["perdite"]["cents"], 0)
        self.assertEqual(out["coperto_cents"], out["incassate"]["cents"])

    def test_bunker_scaglioni_host(self):
        out = self.rotta("GET", "/api/bunker/scaglioni_host", 200, headers=self.AKB)
        self._chiavi(out, "host", "totale", "conteggi", "promo_attiva",
                     "commissione_regime_bps", "tariffa_tecnica_bps",
                     "versione_contratto_corrente", "da_riaccettare")
        self.assertEqual(out["totale"], 1, out)
        self.assertEqual(out["commissione_regime_bps"], 1000)
        self.assertEqual(out["tariffa_tecnica_bps"], 300)
        self.assertEqual(out["versione_contratto_corrente"], CONTRATTO_HOST_VERSIONE)
        h = out["host"][0]
        self.assertEqual(h["host_id"], self.host_id)
        self.assertEqual(h["bps"], 1000)                # promo spenta -> regime 10%
        self.assertEqual(h["percentuale"], 10.0)
        self.assertEqual(h["bps_diretto"], 500)         # 5% sempre sul link diretto
        self.assertIs(h["deve_riaccettare"], False)
        self.assertEqual(out["da_riaccettare"], 0)

    # ══════════════════════ BUNKER — DAC7 ══════════════════════
    def test_bunker_dac7_conformita_e_report(self):
        anno = datetime.datetime.utcnow().year
        out = self.rotta("GET", "/api/bunker/dac7_conformita", 200, headers=self.AKB,
                         query={"anno": str(anno)})
        self.assertEqual(out["anno"], anno)
        self.assertEqual(out["totale"], 1, out)
        self.assertEqual((out["incompleti"], out["reportabili"], out["urgenti"]),
                         (0, 1, 0), out)
        h = out["host"][0]
        self.assertEqual(h["host_id"], self.host_id)
        self.assertIs(h["completo"], True)
        self.assertIs(h["reportabile"], True)          # 5.000 EUR > soglia UE 2.000
        self.assertEqual(h["prenotazioni"], 1)
        self.assertEqual(h["ricavi_cents"], self.totale)
        self.assertEqual(h["mancanti"], [])

        rep = self.rotta("GET", "/api/bunker/dac7_report", 200, headers=self.AKB,
                         query={"anno": str(anno)})
        self.assertEqual(rep["anno"], anno)
        self.assertIs(rep["integro"], True)
        self.assertIn("# host_reportabili,1", rep["csv"])
        self.assertIn(self.host_id, rep["csv"])
        self.assertIn("IT60X0542811101000000123456", rep["csv"])
        # il corrispettivo dichiarato e' quello VERO del giornale, in euro con 2 decimali
        self.assertIn("%.2f" % (self.totale / 100.0), rep["csv"])
        self.assertIn("# FINE REPORT DAC7 - INTEGRITÀ:", rep["csv"])

    # ══════════════════════ BUNKER — guardiani ══════════════════════
    def test_bunker_guardiano_stati_impossibili(self):
        out = self.rotta("GET", "/api/bunker/guardiano", 200, headers=self.AKB)
        self._chiavi(out, "pulito", "conta", "anomalie", "ts", "soglie")
        self.assertIs(out["pulito"], True, out["anomalie"])
        self.assertEqual(out["conta"], 0)
        self.assertEqual(out["anomalie"], {})

    def test_bunker_invarianti_auditor(self):
        out = self.rotta("GET", "/api/bunker/invarianti", 200, headers=self.AKB)
        self._chiavi(out, "ok", "violazioni", "prenotazioni_lette")
        self.assertIs(out["ok"], True, out["violazioni"])
        self.assertEqual(out["violazioni"], {})
        self.assertGreaterEqual(out["prenotazioni_lette"], 1, out)

    def test_bunker_riconciliazione_stripe(self):
        """Stripe e giornale raccontano la stessa storia: nessun fantasma, delta zero."""
        out = self.rotta("GET", "/api/bunker/riconciliazione", 200, headers=self.AKB,
                         query={"giorni": "30"})
        self._chiavi(out, "ok", "giorni", "sessioni_pagate", "incassi_giornale",
                     "solo_stripe", "solo_giornale", "importo_diverso", "confronti")
        self.assertEqual(out["giorni"], 30)
        self.assertEqual((out["sessioni_pagate"], out["incassi_giornale"]), (1, 1), out)
        self.assertEqual((out["solo_stripe"], out["solo_giornale"],
                          out["importo_diverso"]), ([], [], []), out)
        self.assertEqual(out["confronti"]["incassi"]["stripe"], {"EUR": self.totale})
        self.assertEqual(out["confronti"]["incassi"]["giornale"], {"EUR": self.totale})
        self.assertEqual(out["confronti"]["incassi"]["delta"], {"EUR": 0})
        self.assertIs(out["ok"], True, out)

    # ══════════════════════ BUNKER — marche temporali ══════════════════════
    def test_bunker_marca_ora_e_elenco(self):
        out = self.rotta("POST", "/api/bunker/marca_ora", 200, {}, self.AKB)
        self.assertIs(out["ok"], True, out)
        self.assertEqual(out["tsa"], "https://tsa.finta/tsr")
        self.assertEqual(len(out["impronta"]), 64)
        self.assertIsInstance(out["id"], int)
        self.assertEqual(out["giorno"], datetime.datetime.utcnow().strftime("%Y-%m-%d"))

        el = self.rotta("GET", "/api/bunker/marche_temporali", 200, headers=self.AKB)
        self.assertEqual((el["totale"], el["riuscite"]), (1, 1), el)
        m = el["marche"][0]
        self.assertEqual((m["stato"], m["autorita"], m["seriale"]),
                         ("ok", "https://tsa.finta/tsr", "00AB"))
        self.assertEqual(m["impronta"], out["impronta"])
        self.assertEqual(m["scarica"], "/api/bunker/marca.tsr?id=%d" % m["id"])
        self.assertTrue(m["ora_certificata_utc"].endswith("UTC"))
        self.assertIn("eIDAS art. 41", el["cosa_significa_qualificata"])
        # idempotente sul giorno: la seconda richiesta non disturba l'Autorita'
        di_nuovo = self.rotta("POST", "/api/bunker/marca_ora", 200, {}, self.AKB)
        self.assertEqual(di_nuovo.get("saltato"), "gia_marcato_oggi", di_nuovo)

    # ══════════════════════ BUNKER — kill-switch, valuta, operatori ══════════════════════
    def test_bunker_blocco_globale_congela_e_sblocca_i_soldi(self):
        out = self.rotta("GET", "/api/bunker/blocco_globale", 200, headers=self.AKB)
        self.assertEqual((out["attivo"], out["env"], out["runtime"], out["dettaglio"]),
                         (False, False, False, None))

        acceso = self.rotta("POST", "/api/bunker/blocco_globale", 200,
                            {"attivo": True, "motivo": "incidente di sicurezza"}, self.AKB)
        self.assertEqual((acceso["attivo"], acceso["impostato"], acceso["runtime"]),
                         (True, True, True), acceso)
        self.assertEqual(acceso["dettaglio"]["motivo"], "incidente di sicurezza")
        self.assertEqual(acceso["dettaglio"]["chi"], "super-admin")
        # FREEZE VERO: il rimborso admin viene rifiutato finche' dura
        st, out = self.g("POST", "/api/admin/rimborso",
                         {"alloggio_id": self.slug, "check_in": self.ci,
                          "check_out": self.co, "idem_key": self.idem}, self.AKB)
        self.assertEqual((st, out.get("errore")), (503, "transazioni_sospese"), out)

        spento = self.rotta("POST", "/api/bunker/blocco_globale", 200,
                            {"attivo": False, "motivo": "rientrato"}, self.AKB)
        self.assertEqual((spento["attivo"], spento["impostato"]), (False, True), spento)
        self.assertEqual(self.g("POST", "/api/admin/rimborso",
                                {"alloggio_id": self.slug, "check_in": self.ci,
                                 "check_out": self.co, "idem_key": self.idem},
                                self.AKB)[0], 200)

    def test_bunker_cambio_valuta_stato_e_refresh(self):
        out = self.rotta("GET", "/api/bunker/cambio_valuta", 200, headers=self.AKB)
        self.assertIs(out["configurato"], True)
        self.assertIs(out["mai_riuscito"], False)
        self.assertEqual(out["markup_bps"], 100)               # 1% dichiarato
        self.assertEqual(out["campioni"]["EUR->USD"], "1.086956521739130434782608696")
        self.assertIn("EUR->GBP", out["campioni"])
        self.assertIn("USD->JPY", out["campioni"])
        # la chiave OXR resta un segreto: non esce MAI dall'API
        self.assertNotIn("app_id_finto", json.dumps(out))

        agg = self.rotta("POST", "/api/bunker/cambio_valuta/aggiorna", 200, {}, self.AKB)
        self.assertIs(agg["aggiornato"], True)
        self.assertIs(agg["configurato"], True)
        self.assertGreater(agg["ultimo_ok_ts"], 0)

    def test_bunker_admin_accounts_ciclo_completo(self):
        """Elenco -> crea -> cambia ruolo -> revoca (token morto all'istante) -> riattiva."""
        out = self.rotta("GET", "/api/bunker/admin_accounts", 200, headers=self.AKB)
        self.assertEqual(out["account"], [])
        self.assertEqual(out["ruoli"], ["admin", "supporto"])

        op = self._crea_operatore("mario@happyadmin.it", "supporto")
        el = self.rotta("GET", "/api/bunker/admin_accounts", 200, headers=self.AKB)
        self.assertEqual(len(el["account"]), 1, el)
        a = el["account"][0]
        self.assertEqual((a["email"], a["ruolo"], a["attivo"], a["creato_da"]),
                         ("mario@happyadmin.it", "supporto", True, "super-admin"))
        self.assertNotIn("pw_hash", a)          # mai hash/salt fuori dall'API
        self.assertNotIn("salt", a)

        # promozione: il ruolo cambia SUBITO per il token gia' emesso
        out = self.rotta("POST", "/api/bunker/admin_accounts", 200,
                         {"azione": "ruolo", "email": "mario@happyadmin.it",
                          "ruolo": "admin"}, self.AKB)
        self.assertEqual(out, {"ok": True, "email": "mario@happyadmin.it",
                               "ruolo": "admin"})
        opb = dict(op)
        opb["X-Bunker-Session"] = self.sess
        self.assertEqual(self.g("POST", "/api/admin/alloggio_stato",
                                {"slug": self.slug, "stato": "sospeso"}, opb)[0], 200)

        # revoca: lo stesso token NON entra piu' (401), all'istante
        out = self.rotta("POST", "/api/bunker/admin_accounts", 200,
                         {"azione": "revoca", "email": "mario@happyadmin.it"}, self.AKB)
        self.assertEqual(out, {"ok": True, "email": "mario@happyadmin.it"})
        self.assertEqual(self.g("GET", "/api/admin/prenotazioni", headers=op)[0], 401)

        out = self.rotta("POST", "/api/bunker/admin_accounts", 200,
                         {"azione": "riattiva", "email": "mario@happyadmin.it"}, self.AKB)
        self.assertEqual(out, {"ok": True, "email": "mario@happyadmin.it"})
        self.assertEqual(self.g("GET", "/api/admin/prenotazioni", headers=op)[0], 200)


def tearDownModule():
    """TABELLA DI COPERTURA: quando il modulo gira INTERO, ogni rotta della fetta deve
    essere stata esercitata con lo stato atteso. Una rotta dimenticata fa fallire qui."""
    metodi = [m for m in dir(HappyAdmin) if m.startswith("test_")]
    print("\n[happy_admin] rotte coperte: %d/%d" % (len(VISITATE), len(ROTTE_FETTA)),
          file=sys.stderr)
    if TEST_ESEGUITI[0] < len(metodi):
        print("[happy_admin] modulo parziale (%d/%d prove): copertura non giudicata"
              % (TEST_ESEGUITI[0], len(metodi)), file=sys.stderr)
        return
    mancanti = sorted("%s %s" % r for r in (ROTTE_FETTA - VISITATE))
    extra = sorted("%s %s" % r for r in (VISITATE - ROTTE_FETTA))
    assert not mancanti, "rotte della fetta MAI esercitate: %s" % ", ".join(mancanti)
    assert not extra, "rotte fuori dalla fetta registrate: %s" % ", ".join(extra)


if __name__ == "__main__":
    unittest.main(verbosity=2)
