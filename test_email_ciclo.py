"""EMAIL DI CICLO + RICEVUTA (C3, 2026-07-20): prima il cliente pagava/cancellava/
contestava nel SILENZIO, l'host non sapeva di essere stato pagato e chi pagava soldi
veri non riceveva alcun documento.

Guardie di questo compartimento:
  - CONFERMA PAGAMENTO: dopo il webhook 'pagato' parte UNA email al cliente con
    importo e link voucher; il webhook DUPLICATO (retry Stripe) NON la rimanda.
  - CANCELLAZIONE: email onesta con l'esito del rimborso (solo se aveva pagato).
  - ESITO CONTROVERSIA: l'ospite riceve l'esito dell'arbitrato.
  - INVITO RECENSIONE (store fase162): solo PAGATE con soggiorno CONCLUSO, finestra
    14gg (mai spam sugli antichi al primo avvio), una sola volta per riferimento.
  - RICEVUTA: pagina stampabile dal token voucher firmato, SOLO pagate; link nel
    voucher solo se pagata; rotta /ricevuta/ cablata nel server (guardia sorgente).
  - CORPI EMAIL: XSS-safe (titolo ostile escapato), importi da centesimi interi.
Le email di ciclo sono BEST-EFFORT in background: mai bloccare i soldi.
"""
import datetime
import io
import json
import os
import shutil
import tempfile
import threading
import time
import types
import unittest

import fase85_pagamenti_stripe as _stripe
from fase59_concierge import codice_prenotazione
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, pagina_ricevuta_html, pagina_voucher_html
from fase86_email import (corpo_cancellazione_html, corpo_esito_controversia_html,
                          corpo_invito_recensione_html,
                          corpo_pagamento_confermato_html, corpo_payout_host_html)
from fase87_stripe_webhook import firma_di_test
from fase162_pagamenti_pendenti import crea_pagamenti_pendenti
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://x/" + secrets.token_hex(5), "id": "cs_" + secrets.token_hex(5)}


class Finta:
    """Provider email finto: raccoglie gli invii (le email C3 partono in thread)."""

    def __init__(self):
        self.inviate = []
        self._cv = threading.Condition()

    def invia(self, dest, oggetto, html):
        with self._cv:
            self.inviate.append((dest, oggetto, html))
            self._cv.notify_all()
        return True

    def attendi(self, filtro, n=1, timeout=8):
        """True quando almeno n email il cui oggetto contiene `filtro` sono arrivate."""
        fine = time.time() + timeout
        with self._cv:
            while len([1 for _, o, _h in self.inviate if filtro in o]) < n:
                resto = fine - time.time()
                if resto <= 0:
                    return False
                self._cv.wait(resto)
        return True

    def per_oggetto(self, filtro):
        return [(d, o, h) for d, o, h in self.inviate if filtro in o]


class TestEmailCiclo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        self.dir = d = tempfile.mkdtemp()
        os.environ["UPLOAD_DIR"] = f"{d}/uploads"
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_messaggi=f"{d}/m.db",
            db_garanzia=f"{d}/g.db", db_recensioni=f"{d}/rec.db",
            commissione_bps=1500, psp_bps=300,
            stripe_secret_key="sk", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@ec.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        tk = {"X-Host-Token": c["token"]}
        oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "Casa", "citta": "Roma",
                "prezzo_notte_cents": 20000, "capacita": 4}, tk)
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": oggi.isoformat(),
                "a": (oggi + datetime.timedelta(days=20)).isoformat(),
                "unita_totali": 2, "prezzo_netto_cents": 20000}, tk)
        self.ci = (oggi + datetime.timedelta(days=3)).isoformat()
        self.co = (oggi + datetime.timedelta(days=5)).isoformat()
        self.rif, self.vt = self._prenota(self.ci, self.co)
        # il provider si aggancia DOPO il book: qui si contano SOLO le email C3
        self.posta = Finta()
        self.sis.email_provider = self.posta

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _prenota(self, ci, co):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@ec.it", "lang": "it"})
        self.assertEqual(s, 201, b)
        return b["riferimento"], b["voucher_token"]

    def _webhook(self, rif):
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        return self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                               {"Stripe-Signature": firma_di_test(pl, "whsec_x",
                                                                  int(time.time()))})

    # ── 1. conferma pagamento: una email, mai due sul retry ─────────────────────
    def test_conferma_pagamento_una_sola_email(self):
        self._webhook(self.rif)
        self.assertTrue(self.posta.attendi("Pagamento ricevuto"),
                        "email di conferma pagamento mai partita")
        dest, ogg, corpo = self.posta.per_oggetto("Pagamento ricevuto")[0]
        self.assertEqual(dest, "cli@ec.it")
        self.assertIn("/voucher/", corpo)                 # link al voucher
        self.assertIn("400.00 EUR", corpo)                # 2 notti x 20000 = 40000 cents
        # RETRY Stripe (webhook duplicato): nessuna seconda email al cliente
        self._webhook(self.rif)
        time.sleep(0.6)                                   # margine ai thread background
        self.assertEqual(len(self.posta.per_oggetto("Pagamento ricevuto")), 1,
                         "il webhook duplicato ha rimandato l'email di conferma")

    # ── 2. cancellazione: esito rimborso nero su bianco ─────────────────────────
    def test_email_cancellazione_dopo_pagata(self):
        self._webhook(self.rif)
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": self.vt})
        self.assertEqual(s, 200, c)
        self.assertEqual(c["stato"], "cancellata")
        self.assertTrue(self.posta.attendi("Cancellazione confermata"),
                        "email di cancellazione mai partita")
        dest, _o, corpo = self.posta.per_oggetto("Cancellazione confermata")[0]
        self.assertEqual(dest, "cli@ec.it")
        self.assertIn("Prenotazione cancellata", corpo)
        # l'esito economico c'è SEMPRE: o l'importo del rimborso o "non è previsto"
        self.assertTrue(("Rimborso:" in corpo) or ("non è previsto" in corpo), corpo)

    def test_cancellazione_non_pagata_nessuna_email(self):
        rif2, vt2 = self._prenota(
            (datetime.date.today() + datetime.timedelta(days=8)).isoformat(),
            (datetime.date.today() + datetime.timedelta(days=10)).isoformat())
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": vt2})
        self.assertEqual(s, 200, c)
        time.sleep(0.5)
        self.assertEqual(self.posta.per_oggetto("Cancellazione confermata"), [],
                         "email di cancellazione partita per una NON pagata")

    # ── 3. esito controversia all'ospite ─────────────────────────────────────────
    def test_email_esito_controversia(self):
        self._webhook(self.rif)
        s, c = self.g("POST", "/api/garanzia/contesta", {"voucher_token": self.vt})
        self.assertEqual(s, 200, c)
        s, c = self.g("POST", "/api/admin/controversia/risolvi",
                      {"riferimento": self.rif, "percentuale_ospite": 100},
                      {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, c)
        self.assertTrue(self.posta.attendi("Esito della tua segnalazione"),
                        "email esito controversia mai partita")
        dest, _o, corpo = self.posta.per_oggetto("Esito della tua segnalazione")[0]
        self.assertEqual(dest, "cli@ec.it")
        self.assertIn("rimborsato", corpo)                # 100% all'ospite -> importo

    # ── 4. invito recensione: store fase162 (finestra, una-volta, solo pagate) ──
    def test_invito_recensione_selezione_e_finestra(self):
        pp = self.sis.pagamenti_pendenti
        self._webhook(self.rif)
        dopo = (datetime.date.fromisoformat(self.co)
                + datetime.timedelta(days=1)).isoformat()
        righe = pp.da_invitare_recensione(oggi=dopo)
        self.assertIn(self.rif, [r["riferimento"] for r in righe])
        # fuori finestra 14gg (primo avvio: niente spam sugli antichi)
        tardi = (datetime.date.fromisoformat(self.co)
                 + datetime.timedelta(days=20)).isoformat()
        self.assertNotIn(self.rif,
                         [r["riferimento"] for r in pp.da_invitare_recensione(oggi=tardi)])
        # segnato -> mai due inviti per lo stesso soggiorno
        self.assertTrue(pp.segna_invito_recensione(self.rif))
        self.assertNotIn(self.rif,
                         [r["riferimento"] for r in pp.da_invitare_recensione(oggi=dopo)])
        # una NON pagata non si invita mai (anche a soggiorno "concluso")
        rif2, _vt2 = self._prenota(
            (datetime.date.today() + datetime.timedelta(days=8)).isoformat(),
            (datetime.date.today() + datetime.timedelta(days=10)).isoformat())
        lontano = (datetime.date.today() + datetime.timedelta(days=11)).isoformat()
        self.assertNotIn(rif2,
                         [r["riferimento"] for r in pp.da_invitare_recensione(oggi=lontano)])
        # input non validi: mai un crash, lista vuota
        self.assertEqual(pp.da_invitare_recensione(oggi=""), [])
        self.assertEqual(pp.da_invitare_recensione(oggi="non-una-data"), [])
        self.assertFalse(pp.segna_invito_recensione(""))

    # ── 5. ricevuta: pagina firmata, solo pagate, link nel voucher ───────────────
    def test_ricevuta_solo_pagate(self):
        # NON ancora pagata: niente ricevuta, niente link nel voucher
        self.assertIsNone(pagina_ricevuta_html(self.sis, self.vt))
        # GATE STATO-PAGAMENTO: PRIMA del pagamento il voucher NON espone PIN reale né controversia
        _pin = self.sis.firma.pin_checkin(self.rif)
        _v_pre = pagina_voucher_html(self.sis, self.vt, "it")
        self.assertNotIn("/ricevuta/", _v_pre)
        self.assertNotIn(_pin, _v_pre)                     # PIN reale bloccato pre-pagamento
        self.assertNotIn("/api/garanzia/", _v_pre)         # nessun tasto controversia pre-pagamento
        self.assertIn("Completa il pagamento", _v_pre)
        self._webhook(self.rif)
        pagina = pagina_ricevuta_html(self.sis, self.vt)
        self.assertIsNotNone(pagina, "ricevuta assente su prenotazione PAGATA")
        self.assertIn("Ricevuta di pagamento", pagina)
        self.assertIn(codice_prenotazione(self.rif), pagina)
        self.assertIn("400.00 EUR", pagina)               # totale pagato
        self.assertIn("P.IVA 11795700969", pagina)        # identità gestore reale
        self.assertIn("non costituisce fattura fiscale", pagina)  # onestà
        # ora il voucher offre la ricevuta E sblocca PIN reale + tasti controversia (post-pagamento)
        _v_post = pagina_voucher_html(self.sis, self.vt, "it")
        self.assertIn("/ricevuta/", _v_post)
        self.assertIn(_pin, _v_post)                       # PIN reale ora presente
        self.assertIn("/api/garanzia/", _v_post)           # controversia/segnalazione sbloccata
        # token manomesso/estraneo -> nessuna pagina (mai dati altrui)
        self.assertIsNone(pagina_ricevuta_html(self.sis, "token-farlocco"))
        self.assertIsNone(pagina_ricevuta_html(self.sis, self.vt[:-4] + "AAAA"))

    def test_ricevuta_sparisce_dopo_rimborso(self):
        self._webhook(self.rif)
        self.assertIsNotNone(pagina_ricevuta_html(self.sis, self.vt))
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": self.vt})
        self.assertEqual(s, 200, c)
        # cancellata/rimborsata: la ricevuta non attesta più un pagamento valido
        self.assertIsNone(pagina_ricevuta_html(self.sis, self.vt))

    # ── 6. corpi email: XSS-safe e importi al centesimo ─────────────────────────
    def test_corpi_email_xss_e_importi(self):
        ostile = "<script>alert(1)</script>"
        for corpo in (
                corpo_pagamento_confermato_html(ostile, "https://x/v", 12345, "EUR"),
                corpo_cancellazione_html(ostile, 12345, "EUR", 500),
                corpo_invito_recensione_html(ostile, "https://x/v"),
                corpo_payout_host_html(12345, "EUR", ostile)):
            self.assertNotIn("<script>", corpo)
            self.assertIn("&lt;script&gt;", corpo)
        self.assertIn("123.45 EUR", corpo_pagamento_confermato_html("Casa", "", 12345, "EUR"))
        # cancellazione: rimborso positivo vs zero (frasi diverse, sempre oneste)
        con_r = corpo_cancellazione_html("Casa", 7000, "EUR")
        self.assertIn("70.00 EUR", con_r)
        senza_r = corpo_cancellazione_html("Casa", 0, "EUR", lingua="it")
        self.assertIn("non è previsto", senza_r)
        # credito anti-rimpianto mostrato solo se c'è
        self.assertIn("Credito Viaggio", corpo_cancellazione_html("Casa", 0, "EUR", 900, lingua="it"))
        self.assertNotIn("Credito Viaggio", corpo_cancellazione_html("Casa", 0, "EUR", 0))
        # esito controversia: rimborso vs nessun rimborso
        self.assertIn("50.00 EUR", corpo_esito_controversia_html(5000, "EUR", lingua="it"))
        self.assertIn("non è stato riconosciuto", corpo_esito_controversia_html(0, "EUR", lingua="it"))
        # importi rotti non fanno mai crashare (0 onesto)
        self.assertIn("0.00 EUR", corpo_pagamento_confermato_html("Casa", "", "boh", "EUR"))

    # ── 7. cablaggi nel server: rotta ricevuta + sweep invito recensione ────────
    def test_rotta_ricevuta_e_tick_cablati(self):
        import inspect
        import fase83_server as srv
        src = inspect.getsource(srv)
        self.assertIn('u.path.startswith("/ricevuta/")', src,
                      "rotta /ricevuta/ non cablata nel server")
        self.assertIn("target=_tick_invito_recensione", src,
                      "sweep invito recensione non avviato in servi()")
        # e il gancio email conferma sta nel punto giusto: DOPO la riasserzione
        # idempotente, MAI nel ramo retry (stato gia' 'pagato' esce prima)
        self.assertIn("self._email_pagamento_confermato(rec)", src)


class TestLInvitoARecensireNonRisultaFattoSeNonParte(unittest.TestCase):
    """⛔ D20, difetto vivo sul giro che invita a recensire dopo il check-out (lo STESSO
    difetto n. 2 del promemoria al check-in, riparato l'11 settembre; qui era rimasto).
    Parole del fondatore: «autorizzato» e poi «correggi tutto … non si torna piu' indietro».

    **Cosa era rotto.** `invia()` restituisce un booleano (False pulito dal provider, senza
    eccezione) e il giro chiamava `segna_invito_recensione` comunque, anche dopo un'eccezione:
    il cliente non riceveva l'invito, nessuno ritentava, e senza inviti il motore delle
    recensioni resta a secco. In piu' un invito mai partito **spariva in silenzio** quando la
    finestra di 14 giorni lo faceva uscire dalla coda: nessuno poteva sapere che era successo.

    ⛔ L'ORA QUI NON E' UN DIFETTO, e lo si MISURA invece di affermarlo
    (`test_PREMESSA_L_INVITO_NON_PRECEDE_MAI_IL_DIRITTO`): il giro sceglie `check_out < oggi`
    (data UTC) e il diritto di recensire parte dalla mezzanotte del check-out nel fuso
    dell'alloggio -- il primo giro utile cade sempre dopo, anche a UTC+14.
    ⛔ Queste guardie ESEGUONO la passata vera con un orologio iniettato, un archivio vero
    (`fase162`) e un provider finto che dice si', no o solleva: non cercano parole nel
    sorgente, che un commento soddisferebbe (sbaglio S6).
    """

    CO = "2026-09-20"          # check-out
    OGGI = "2026-09-21"        # il primo giorno in cui il giro vede la riga
    ULTIMO = "2026-10-04"      # CO + 14: l'ULTIMO giorno in cui la riga e' ancora in coda

    class _Posta(object):
        """Il provider finto: ricorda cosa gli si chiede, e risponde si', no o solleva."""

        def __init__(self, esito=True):
            self.esito = esito
            self.inviate = []

        def invia(self, destinatario, oggetto, corpo_html):
            self.inviate.append((destinatario, oggetto))
            if isinstance(self.esito, Exception):
                raise self.esito
            return self.esito

    class _Router(object):
        """Il router finto: SOLO il metodo che la passata usa."""

        def _lang_da_voucher(self, vt):
            return "it"

    def setUp(self):
        import fase83_server
        self.s = fase83_server
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _banco(self, nome, esito=True):
        pp = crea_pagamenti_pendenti(os.path.join(self.dir, nome + ".db"))
        pp.inizializza_schema()
        pp.registra("R-" + nome, alloggio_id="casa", check_in="2026-09-18",
                    check_out=self.CO, email="cliente@x.it",
                    corpo_json='{"voucher_token":"vt.sig","titolo":"Casa Bella"}')
        pp.conferma("R-" + nome)
        posta = self._Posta(esito)
        sistema = types.SimpleNamespace(pagamenti_pendenti=pp, email_provider=posta,
                                        config=types.SimpleNamespace(base_url="https://x"))
        return pp, posta, sistema, self._Router()

    def _in_coda(self, pp):
        """Le righe non ancora segnate. Si sonda col PRIMO giorno utile: la finestra di 14
        giorni le farebbe sparire da sola piu' avanti, e allora «segnata» e «scaduta»
        sarebbero indistinguibili."""
        return [r["riferimento"] for r in pp.da_invitare_recensione(oggi=self.OGGI)]

    @staticmethod
    def _ora_di(giorno):
        return datetime.datetime.fromisoformat(giorno + "T12:00:00+00:00").timestamp()

    def _errori_durante(self, fare):
        """Esegue `fare()` e rende le righe di livello ERROR scritte dal server nel frattempo."""
        import logging
        righe = []

        class _Presa(logging.Handler):
            def emit(self, record):
                righe.append(record.getMessage())

        presa = _Presa(level=logging.ERROR)
        log = logging.getLogger("core_auto.server")
        log.addHandler(presa)
        try:
            fare()
        finally:
            log.removeHandler(presa)
        return righe

    def test_UN_INVIO_FALLITO_NON_RISULTA_FATTO_E_SI_RITENTA(self):
        pp, posta, sistema, router = self._banco("fallito", esito=False)
        self.s.invito_recensione_una_passata(sistema, router, ora_ts=self._ora_di(self.OGGI))
        self.assertEqual(len(posta.inviate), 1, "non ha nemmeno provato a spedire")
        self.assertIn("R-fallito", self._in_coda(pp),
                      "il provider ha detto NO e l'invito risulta mandato: il cliente non "
                      "riceve niente e nessuno ritenta")
        posta.esito = True
        self.s.invito_recensione_una_passata(sistema, router, ora_ts=self._ora_di(self.OGGI))
        self.assertEqual(len(posta.inviate), 2, "al giro dopo non ha ritentato")
        self.assertNotIn("R-fallito", self._in_coda(pp))

    def test_UN_ECCEZIONE_DEL_PROVIDER_NON_RISULTA_FATTA(self):
        pp, posta, sistema, router = self._banco("eccezione", esito=OSError("smtp giu'"))
        self.s.invito_recensione_una_passata(sistema, router, ora_ts=self._ora_di(self.OGGI))
        self.assertEqual(len(posta.inviate), 1, "non ha nemmeno provato a spedire")
        self.assertIn("R-eccezione", self._in_coda(pp),
                      "un'eccezione del provider e' stata segnata come invito riuscito")

    def test_ALL_ULTIMO_GIORNO_UTILE_SI_SMETTE_E_RESTA_SCRITTO(self):
        """La finestra di 14 giorni fa uscire la riga dalla coda da sola: senza una riga
        d'ERRORE, un invito mai partito sparisce e nessuno lo sa. Qui si pretende che
        l'ultimo tentativo fallito lasci una traccia col riferimento."""
        pp, posta, sistema, router = self._banco("perso", esito=False)
        errori = self._errori_durante(
            lambda: self.s.invito_recensione_una_passata(
                sistema, router, ora_ts=self._ora_di(self.ULTIMO)))
        self.assertEqual(len(posta.inviate), 1,
                         "all'ultimo giorno utile non ha nemmeno provato a spedire")
        self.assertNotIn("R-perso", self._in_coda(pp),
                         "all'ultimo giorno utile la riga resta non segnata: domani esce "
                         "dalla finestra e il caso sparisce senza che nessuno lo sappia")
        self.assertTrue(any("R-perso" in r for r in errori),
                        "l'invito e' andato perso senza una riga d'ERRORE che lo dica: %r"
                        % errori)
        # ⛔ E la riga deve dire QUALE condizione ha chiuso il caso. Senza questo la guardia
        # passa anche quando scatta un ramo d'emergenza qualunque: e' successo davvero il
        # 2026-09-12, con la costante dei 14 giorni non ancora definita -- il NameError
        # finiva nel ramo «data illeggibile» e questa prova diventava VERDE PER IL MOTIVO
        # SBAGLIATO, mentre il prodotto smetteva di ritentare.
        self.assertTrue(any("ultimo giorno utile" in r for r in errori),
                        "la riga d'ERRORE non dice che a chiudere il caso e' stato l'ultimo "
                        "giorno della finestra: %r" % errori)

    def test_PREMESSA_I_QUATTORDICI_GIORNI_SONO_QUELLI_VERI_DELLA_CODA(self):
        """`GIORNI_INVITO_RECENSIONE` in `fase83_server` e' una COPIA: il numero vero e'
        scritto a mano dentro la query di `fase162`. Qui si MISURA la finestra vera --
        l'ultimo giorno in cui la coda restituisce ancora la riga -- e si pretende che le due
        coincidano. Se qualcuno cambia la finestra di la', questa diventa rossa oggi."""
        pp, _posta, _sistema, _router = self._banco("finestra", esito=True)
        co = datetime.date.fromisoformat(self.CO)
        ultimo_vero = None
        for giorni in range(1, 40):
            oggi = (co + datetime.timedelta(days=giorni)).isoformat()
            if [r for r in pp.da_invitare_recensione(oggi=oggi) if r["riferimento"] == "R-finestra"]:
                ultimo_vero = giorni
        self.assertIsNotNone(ultimo_vero, "la coda non restituisce mai la riga: banco rotto")
        self.assertEqual(
            self.s.GIORNI_INVITO_RECENSIONE, ultimo_vero,
            "la costante dice %r giorni, ma la coda smette di restituire la riga dopo %r: "
            "il numero copiato non descrive piu' la finestra vera"
            % (self.s.GIORNI_INVITO_RECENSIONE, ultimo_vero))

    def test_PARTE_UNA_VOLTA_SOLA(self):
        pp, posta, sistema, router = self._banco("una", esito=True)
        for _ in range(3):
            self.s.invito_recensione_una_passata(sistema, router,
                                                 ora_ts=self._ora_di(self.OGGI))
        self.assertEqual(len(posta.inviate), 1, "l'invito e' partito piu' di una volta")

    def test_PREMESSA_L_INVITO_NON_PRECEDE_MAI_IL_DIRITTO(self):
        """L'ora NON e' il difetto, e qui si misura: il primo istante in cui il giro puo'
        vedere la riga e' la mezzanotte UTC del giorno dopo il check-out; il diritto di
        recensire parte dalla mezzanotte del check-out NEL FUSO dell'alloggio. Il fuso piu'
        a est (UTC+14) e' il caso peggiore."""
        primo_giro = datetime.datetime.fromisoformat(
            self.OGGI + "T00:00:00+00:00").timestamp()
        for fuso in ("Europe/Rome", "Asia/Manila", "America/Los_Angeles",
                     "Pacific/Kiritimati", ""):
            with self.subTest(fuso=fuso or "(fuso ignoto)"):
                diritto = self.s._mezzanotte_checkout(self.CO, fuso)
                self.assertIsNotNone(diritto, "fuso %r: nessun istante calcolato" % fuso)
                self.assertGreaterEqual(
                    primo_giro, diritto,
                    "l'invito puo' partire PRIMA che si possa recensire (fuso %s)"
                    % (fuso or "ignoto"))

    def test_PREMESSA_IL_GIRO_DEL_SERVER_CHIAMA_QUESTA_PASSATA(self):
        """Se il thread del server tenesse una SUA copia della logica, le prove qui sopra
        misurerebbero una funzione che la produzione non esegue."""
        import re
        with io.open(self.s.__file__, encoding="utf-8") as f:
            sorgente = f.read()
        m = re.search(r"def _tick_invito_recensione\(\):(.+?)\n        _th", sorgente, re.S)
        self.assertIsNotNone(m, "il giro _tick_invito_recensione non si trova piu'")
        corpo = "\n".join(r for r in m.group(1).splitlines()
                          if r.strip() and not r.strip().startswith("#"))
        self.assertIn("invito_recensione_una_passata(sistema, router)", corpo,
                      "il giro del server non chiama la passata provata qui")
        self.assertNotIn("segna_invito_recensione", corpo,
                         "il giro del server ha ancora una SUA copia della logica")


if __name__ == "__main__":
    unittest.main()
