"""
PAGA IN STRUTTURA — test AVANZATI (angoli DIVERSI, high-signal, carta bianca del fondatore).

Non ripetono l'happy-path gia' coperto (e2e/p0/cablaggio): colpiscono angoli nuovi dove
si nascondono i bug veri:
  1. MULTI-VALUTA: l'intero flusso in yen (JPY, 0 decimali) -> gli importi restano coerenti,
     non si perde mai, la penale = prima notte in yen.
  2. ANTI-FRODE: un voucher MANOMESSO (anticipo/saldo gonfiati) viene RIFIUTATO (la firma
     protegge gli importi) -> niente rimborso/penale su numeri falsi.
  3. IDEMPOTENZA: doppia cancellazione della stessa prenotazione -> penale UNA volta sola.
  4. CONFINE PENALE MULTI-NOTTE: penale = PRIMA NOTTE esatta (non il totale, non la media
     arrotondata male) su 3 e 7 notti.
  5. CONSERVAZIONE END-TO-END (oracolo): book -> paga -> cancella -> penale; ogni centesimo e'
     contabilizzato (l'ospite paga X, noi teniamo Y, l'host prende Z, niente sparisce o nasce).
"""
import json
import os
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
import fase183_carta_offsession as _carta_mod
import fase188_paga_struttura as PS
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_adv"
_BODIES = []
_DECLINE = [False]
_CARTA_MODE = ["ok"]          # 'ok'|'declined'|'sca'|'timeout'|'scaduta'
_CHARGE_COUNT = [0]
import threading as _thr
_CHARGE_LOCK = _thr.Lock()


def _fake_stripe(url, body, headers):
    import secrets
    _BODIES.append(body.decode() if isinstance(body, (bytes, bytearray)) else str(body))
    return {"url": "https://checkout.stripe.com/c/" + secrets.token_hex(4),
            "id": "cs_" + secrets.token_hex(4)}


def _fake_carta(metodo, url, body, headers):
    if metodo == "GET" and "/checkout/sessions/" in url:
        return {"customer": "cus_x", "payment_intent": "pi_x"}
    if metodo == "GET" and "/payment_intents/" in url:
        return {"payment_method": "pm_x"}
    if metodo == "POST" and url.endswith("/payment_intents"):
        with _CHARGE_LOCK:
            _CHARGE_COUNT[0] += 1
        m = _CARTA_MODE[0]
        if m == "timeout":
            raise RuntimeError("stripe timeout")                      # rete giu' a meta'
        if m == "declined" or _DECLINE[0]:
            return {"error": {"code": "card_declined"}}
        if m == "scaduta":
            return {"error": {"code": "expired_card"}}
        if m == "sca":
            return {"error": {"code": "authentication_required",
                              "payment_intent": {"id": "pi_sca"}}}
        return {"status": "succeeded", "id": "pi_c"}
    return {}


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._o1 = _stripe.ProviderStripe._fetch_reale
        cls._o2 = _carta_mod.ProviderCarta._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_stripe)
        _carta_mod.ProviderCarta._fetch_reale = staticmethod(_fake_carta)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._o1
        _carta_mod.ProviderCarta._fetch_reale = cls._o2

    def setUp(self):
        self._flag = os.environ.get("PAGA_STRUTTURA_ATTIVO")
        os.environ["PAGA_STRUTTURA_ATTIVO"] = "1"
        del _BODIES[:]
        _DECLINE[0] = False
        _CARTA_MODE[0] = "ok"
        _CHARGE_COUNT[0] = 0
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db",
            commissione_bps=1000, psp_bps=0, stripe_secret_key="sk",
            stripe_webhook_secret=WH, stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")
        _, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@a.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.tok = c["token"]

    def tearDown(self):
        if self._flag is None:
            os.environ.pop("PAGA_STRUTTURA_ATTIVO", None)
        else:
            os.environ["PAGA_STRUTTURA_ATTIVO"] = self._flag
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def pubblica(self, slug, valuta="EUR", prezzo=30000, giorni_da_oggi=0, giorni_range=40, fuso=""):
        import datetime
        oggi = datetime.date.today()
        corpo = {"slug": slug, "titolo": slug, "citta": "Roma", "prezzo_notte_cents": prezzo,
                 "capacita": 4, "valuta": valuta, "politica_cancellazione": "flessibile"}
        if fuso:
            corpo["fuso"] = fuso
        self.g("POST", "/api/host/pubblica", corpo, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": slug, "da": (oggi + datetime.timedelta(days=giorni_da_oggi)).isoformat(),
                "a": (oggi + datetime.timedelta(days=giorni_range)).isoformat(),
                "unita_totali": 5, "prezzo_netto_cents": prezzo}, {"X-Host-Token": self.tok})

    def prenota(self, slug, ci, co):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": slug, "check_in": ci, "check_out": co, "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@a.it", "modo_pagamento": "in_struttura"})
        self.assertEqual(s, 201, b)
        return q, b

    def webhook(self, rif, cs="cs_adv"):
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": cs, "metadata": {"riferimento": rif}}}})
        return self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                               {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})

    def dd(self, giorni, notti=1):
        import datetime
        ci = datetime.date.today() + datetime.timedelta(days=giorni)
        return ci.isoformat(), (ci + datetime.timedelta(days=notti)).isoformat()


class TestMultiValuta(_Base):
    def test_flusso_in_yen_coerente_e_non_si_perde(self):
        # JPY: 0 decimali, importi grandi. prezzo 30000 = ¥30.000/notte.
        self.pubblica("casa-jpy", valuta="JPY", prezzo=30000, giorni_da_oggi=5)
        ci, co = self.dd(5, notti=3)
        q, b = self.prenota("casa-jpy", ci, co)
        self.assertEqual(b.get("modo_pagamento"), "in_struttura", b)
        self.assertEqual((q.get("valuta") or "").upper(), "JPY")
        # gli importi tornano con fase188 sugli stessi numeri (yen interi)
        atteso = PS.calcola(q["totale_cents"], q["notti"], q["commissione_cents"])
        self.assertEqual(b["anticipo_online_cents"], atteso["anticipo_online_cents"])
        self.assertEqual(b["saldo_in_loco_cents"], atteso["saldo_in_loco_cents"])
        # INVARIANTE soldi anche in yen: anticipo + saldo == totale + fee
        self.assertEqual(b["anticipo_online_cents"] + b["saldo_in_loco_cents"],
                         q["totale_cents"] + atteso["fee_cents"])
        # il link addebita l'anticipo in valuta jpy
        ant = [x for x in _BODIES if "in_struttura" in x][-1]
        self.assertIn("currency%5D=jpy", ant)
        # non si perde: l'anticipo copre Stripe peggiore anche in yen
        self.assertGreater(b["anticipo_online_cents"] - (25 + b["anticipo_online_cents"] * 325 // 10000), 0)

    def test_penale_in_yen_e_la_prima_notte(self):
        self.pubblica("casa-jpy2", valuta="JPY", prezzo=30000, giorni_da_oggi=0)
        ci, co = self.dd(0, notti=3)                # < 24h
        q, b = self.prenota("casa-jpy2", ci, co)
        self.webhook(b["riferimento"])
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, c)
        pen = c.get("penale_struttura") or {}
        self.assertTrue(pen.get("applicata"), pen)
        self.assertEqual(pen.get("importo_cents"), q["prezzo_guest_cents"] // 3, "penale != prima notte (yen)")


class TestAntiFrode(_Base):
    def test_voucher_manomesso_rifiutato(self):
        # gonfiare l'anticipo nel voucher per farsi rimborsare di piu' -> la FIRMA lo rifiuta
        self.pubblica("casa-fr", giorni_da_oggi=5)
        ci, co = self.dd(5, notti=2)
        q, b = self.prenota("casa-fr", ci, co)
        vt = b["voucher_token"]
        # manomissione: cambio un carattere nel token firmato
        rotto = vt[:-3] + ("aaa" if vt[-3:] != "aaa" else "bbb")
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": rotto})
        self.assertNotEqual(s, 200, "un voucher manomesso NON deve cancellare/rimborsare: %s" % (c,))

    def test_doppia_cancellazione_penale_una_volta_sola(self):
        # idempotenza: due cancellazioni della stessa prenotazione -> UN solo addebito penale
        self.pubblica("casa-idem", giorni_da_oggi=0)
        ci, co = self.dd(0, notti=1)               # < 24h -> penale
        q, b = self.prenota("casa-idem", ci, co)
        self.webhook(b["riferimento"])
        s1, c1 = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        s2, c2 = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s1, 200); self.assertEqual(s2, 200)
        # la 2a cancellazione e' un replay ('gia_cancellata'): NON riaddebita la penale
        applicate = [x for x in (c1, c2) if (x.get("penale_struttura") or {}).get("applicata")]
        self.assertLessEqual(len(applicate), 1, "penale addebitata due volte su doppia cancellazione")
        self.assertIn(c2.get("stato"), ("gia_cancellata", "cancellata"))


class TestPenaleMultiNotte(_Base):
    def _prima_notte(self, notti):
        slug = "casa-mn%d" % notti
        self.pubblica(slug, giorni_da_oggi=0)
        ci, co = self.dd(0, notti=notti)           # < 24h
        q, b = self.prenota(slug, ci, co)
        self.webhook(b["riferimento"])
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, c)
        pen = c.get("penale_struttura") or {}
        self.assertTrue(pen.get("applicata"), pen)
        # CONFINE: la penale e' la PRIMA NOTTE, non il totale, non altro
        self.assertEqual(pen["importo_cents"], q["prezzo_guest_cents"] // notti,
                         "penale != prima notte su %d notti" % notti)
        self.assertLess(pen["importo_cents"], q["prezzo_guest_cents"],
                        "penale >= totale su %d notti: sbagliato" % notti)

    def test_prima_notte_su_3_notti(self):
        self._prima_notte(3)

    def test_prima_notte_su_7_notti(self):
        self._prima_notte(7)


class TestConservazioneE2E(_Base):
    def test_ogni_centesimo_contabilizzato(self):
        # ORACOLO: dopo book->paga (in struttura), i conti tornano al centesimo.
        self.pubblica("casa-cons", giorni_da_oggi=5)
        ci, co = self.dd(5, notti=4)
        q, b = self.prenota("casa-cons", ci, co)
        r = PS.calcola(q["totale_cents"], q["notti"], q["commissione_cents"])
        # 1) quello che l'ospite paga in tutto = totale soggiorno + fee
        self.assertEqual(r["ospite_paga_totale_cents"], q["totale_cents"] + r["fee_cents"])
        # 2) anticipo (online, nostro) + saldo (in loco, host) = tutto quello che paga l'ospite
        self.assertEqual(b["anticipo_online_cents"] + b["saldo_in_loco_cents"],
                         r["ospite_paga_totale_cents"])
        # 3) l'host prende ESATTAMENTE il saldo (niente giro storto)
        self.assertEqual(r["host_incassa_cents"], b["saldo_in_loco_cents"])
        # 4) noi teniamo commissione + fee; il gateway copre (e supera) il costo Stripe -> mai in perdita
        self.assertEqual(r["noi_incassiamo_cents"], r["commissione_cents"] + r["fee_cents"])
        stripe_peggiore = 25 + b["anticipo_online_cents"] * 325 // 10000
        self.assertGreater(b["anticipo_online_cents"] - stripe_peggiore, 0, "in perdita end-to-end")
        # 5) niente e' negativo, niente sparisce
        self.assertGreaterEqual(r["host_incassa_cents"], 0)
        self.assertGreaterEqual(b["saldo_in_loco_cents"], 0)


class TestFusoOrario(_Base):
    """Fusi opposti a cavallo della soglia 24h: la penale conta l'ora VERA del check-in nel
    fuso dell'alloggio, non del server. Atteso calcolato indipendentemente con zoneinfo."""

    def _ore_reali(self, fuso, ci):
        # 15:00 locali del giorno di check-in, in ore da ORA (indipendente dal codice sotto test)
        import datetime
        try:
            from zoneinfo import ZoneInfo
            dt = datetime.datetime.fromisoformat(ci + "T15:00:00").replace(tzinfo=ZoneInfo(fuso))
            return (dt.timestamp() - time.time()) / 3600.0
        except Exception:
            return None

    def _prova_fuso(self, fuso, giorni):
        slug = "casa-tz-" + fuso.split("/")[-1].lower()
        self.pubblica(slug, giorni_da_oggi=0, fuso=fuso)
        ci, co = self.dd(giorni, notti=1)
        ore = self._ore_reali(fuso, ci)
        # zoneinfo e' stdlib (3.9+): deve esserci. Niente skip (sarebbe una zona cieca): se
        # manca e' un difetto d'ambiente vero, e vogliamo vederlo, non nasconderlo.
        self.assertIsNotNone(ore, "zoneinfo/ora locale non calcolabile: ambiente rotto")
        atteso_penale = ore < 24
        # ROBUSTEZZA anti-flaky (bonifica 2026-07-24): fra il calcolo di `ore` QUI e quello INTERNO
        # del motore (fatto alla cancellazione, alcuni secondi dopo: pubblica+prenota+webhook+cancel)
        # passa tempo reale -> a ridosso ESATTO delle 24h i due istanti possono cadere ai lati opposti
        # del confine per pura deriva d'orologio (non un bug: entrambe le risposte sono "giuste" per
        # l'istante in cui sono state prese). Questo rendeva il job MUTAZIONE rosso a certe ore UTC.
        # Il verso ESATTO al confine e' gia' coperto in modo DETERMINISTICO da TestConfine24hEsatto
        # (clock mockato, uccide entrambi i mutanti >=24): qui, nella fascia ambigua, si salta invece
        # di asserire a caso. Fuori dalla fascia (il caso normale) l'asserzione resta PIENA.
        q, b = self.prenota(slug, ci, co)
        if b.get("modo_pagamento") != "in_struttura":
            self.fail("prenotazione non in_struttura: setup rotto")
        self.webhook(b["riferimento"])
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, c)
        applicata = bool((c.get("penale_struttura") or {}).get("applicata"))
        if abs(ore - 24.0) < 0.05:        # ~3 minuti: copre ampiamente la durata del flusso
            self.skipTest("ore=%.4f a ridosso del confine 24h: verso ambiguo per deriva "
                          "d'orologio (coperto deterministicamente da TestConfine24hEsatto)" % ore)
        self.assertEqual(applicata, atteso_penale,
                         "fuso %s ci=%s: penale=%s ma per l'ora vera (%.1fh) doveva essere %s"
                         % (fuso, ci, applicata, ore, atteso_penale))

    def test_estremo_est_domani(self):
        self._prova_fuso("Pacific/Kiritimati", 1)     # UTC+14

    def test_estremo_ovest_domani(self):
        self._prova_fuso("Pacific/Honolulu", 1)       # UTC-10

    def test_istante_checkin_e_fuso_aware(self):
        # unit: la stessa data in due fusi opposti da istanti diversi (~24h di scarto)
        from fase83_server import _istante_checkin
        a = _istante_checkin("2026-09-10", "Pacific/Kiritimati")
        b = _istante_checkin("2026-09-10", "Pacific/Honolulu")
        self.assertIsNotNone(a); self.assertIsNotNone(b)
        self.assertGreater(abs(a - b) / 3600.0, 20, "i due fusi opposti dovrebbero distare ~24h")


class TestArrotondamenti(_Base):
    def test_penale_prima_notte_arrotonda_per_difetto(self):
        # prezzo NON divisibile per le notti: la penale (prezzo//notti) arrotonda per DIFETTO
        # e non supera mai una notte piena; penale*notti <= prezzo (mai addebito gonfiato).
        for prezzo, notti in ((10000, 3), (99999, 7), (10001, 2), (12345, 5)):
            slug = "casa-rnd-%d-%d" % (prezzo, notti)
            self.pubblica(slug, prezzo=prezzo, giorni_da_oggi=0)
            ci, co = self.dd(0, notti=notti)
            q, b = self.prenota(slug, ci, co)
            self.webhook(b["riferimento"])
            s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
            self.assertEqual(s, 200, c)
            pen = c.get("penale_struttura") or {}
            if pen.get("applicata"):
                atteso = q["prezzo_guest_cents"] // notti
                self.assertEqual(pen["importo_cents"], atteso, "arrotondamento penale sbagliato")
                self.assertLessEqual(pen["importo_cents"] * notti, q["prezzo_guest_cents"],
                                     "penale*notti > prezzo: addebito gonfiato dall'arrotondamento")

    def test_valuta_zero_decimali_penale_intera(self):
        # JPY: la penale e' un intero di yen, mai frazione
        self.pubblica("casa-jpy-rnd", valuta="JPY", prezzo=10000, giorni_da_oggi=0)
        ci, co = self.dd(0, notti=3)
        q, b = self.prenota("casa-jpy-rnd", ci, co)
        self.webhook(b["riferimento"])
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        pen = c.get("penale_struttura") or {}
        if pen.get("applicata"):
            self.assertEqual(pen["importo_cents"], q["prezzo_guest_cents"] // 3)
            self.assertIsInstance(pen["importo_cents"], int)


class TestRaceConcorrente(_Base):
    def test_cancellazioni_concorrenti_penale_una_sola(self):
        # 8 thread cancellano LA STESSA prenotazione insieme: 1 sola cancellazione vera,
        # 1 sola penale addebitata, zero crash, zero doppio addebito.
        self.pubblica("casa-race", giorni_da_oggi=0)
        ci, co = self.dd(0, notti=1)
        q, b = self.prenota("casa-race", ci, co)
        self.webhook(b["riferimento"])
        vt = b["voucher_token"]
        esiti = []
        lock = _thr.Lock()

        def worker():
            try:
                s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
                with lock:
                    esiti.append((s, c.get("stato"), bool((c.get("penale_struttura") or {}).get("applicata"))))
            except Exception as e:
                with lock:
                    esiti.append(("EXC", str(e), False))

        ths = [_thr.Thread(target=worker) for _ in range(8)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual(len(esiti), 8)
        self.assertFalse(any(s == "EXC" for s, _, _ in esiti), "crash in concorrenza: %s" % esiti)
        penali = sum(1 for _, _, p in esiti if p)
        self.assertLessEqual(penali, 1, "penale applicata piu' di una volta in concorrenza")
        self.assertLessEqual(_CHARGE_COUNT[0], 1, "carta addebitata piu' di una volta in concorrenza")


class TestResilienzaCarta(_Base):
    def _cancella_tardiva(self):
        self.pubblica("casa-res", giorni_da_oggi=0)
        ci, co = self.dd(0, notti=1)
        q, b = self.prenota("casa-res", ci, co)
        self.webhook(b["riferimento"])
        return self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})

    def test_carta_scaduta(self):
        _CARTA_MODE[0] = "scaduta"
        s, c = self._cancella_tardiva()
        self.assertEqual(s, 200, "carta scaduta non deve rompere la cancellazione")
        self.assertFalse((c.get("penale_struttura") or {}).get("applicata"))
        self.assertEqual(c.get("date_liberate"), True)

    def test_carta_richiede_autenticazione_sca(self):
        _CARTA_MODE[0] = "sca"
        s, c = self._cancella_tardiva()
        self.assertEqual(s, 200)
        self.assertFalse((c.get("penale_struttura") or {}).get("applicata"),
                         "SCA (richiede_azione) NON e' un incasso riuscito")

    def test_timeout_stripe_durante_addebito(self):
        _CARTA_MODE[0] = "timeout"                 # il fetch SOLLEVA a meta'
        s, c = self._cancella_tardiva()
        self.assertEqual(s, 200, "un timeout Stripe NON deve rompere la cancellazione")
        pen = c.get("penale_struttura") or {}
        self.assertFalse(pen.get("applicata"))


class TestManipolazione(_Base):
    def test_data_passata_non_prenota(self):
        self.pubblica("casa-past", giorni_da_oggi=0)
        ci, co = self.dd(-5, notti=2)              # check-in nel PASSATO
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-past", "check_in": ci, "check_out": co, "party": 2})
        if s == 200 and q.get("quote_token"):
            s2, b2 = self.g("POST", "/api/concierge/book",
                            {"quote_token": q["quote_token"], "email": "x@x.it",
                             "modo_pagamento": "in_struttura"})
            self.assertNotEqual(s2, 201, "una data passata NON deve confermare")
        else:
            self.assertNotEqual(s, 200)

    def test_payload_corrotti_su_cancella_non_crashano(self):
        for bad in (None, {}, {"voucher_token": ""}, {"voucher_token": "xxx.yyy"},
                    {"voucher_token": 12345}, {"voucher_token": "a" * 5000}):
            s, c = self.g("POST", "/api/concierge/cancella", bad)
            self.assertIn(s, (400, 422), "payload corrotto deve dare errore pulito, non 500/crash: %s" % (bad,))

    def test_json_non_valido_su_book(self):
        s, c = self.r.gestisci("POST", "/api/concierge/book", {}, "{non-json!!", {})
        self.assertIn(s, (400, 422))


class TestConfine24hEsatto(unittest.TestCase):
    """MICRO-STEPPING Flow 4 — l'OFF-BY-ONE al confine ESATTO delle 24h.

    I test integrati (TestFusoOrario) calcolano `ore` dall'orologio reale e non colpiscono
    MAI le 24.0 esatte. Cosi' il mutante `if ore >= 24` -> `if ore > 24` SOPRAVVIVEVA: a chi
    disdice con ESATTAMENTE 24h di preavviso addebiterebbe la prima notte sulla carta salvata
    (addebito indebito). Regola del fondatore: la penale scatta solo a MENO di 24h; a 24h
    esatte la carta NON si tocca. Qui si forza `ore` a valori esatti a livello di funzione:
      · ore = 24.0        -> nessuna penale (motivo 'non_tardiva'), la carta non si tocca;
      · ore = 24h - 1 sec -> tardiva: entra nel ramo penale (si ferma solo perche' qui la
                             carta e' assente -> motivo diverso da 'non_tardiva').
    VISTO ROSSO col mutante `> 24` (il caso 24.0 cade nel ramo penale -> motivo != 'non_tardiva').
    """

    def _decisione(self, ore_esatte):
        from unittest import mock
        import fase83_server as srv
        NOW = 1_000_000
        ts_ci = NOW + int(round(ore_esatte * 3600))          # istante check-in a `ore` da ora
        router = srv.RouterHTTP.__new__(srv.RouterHTTP)       # istanza minima, senza __init__
        router._sys = object()                               # niente carta/pagamenti_pendenti
        router._fuso_alloggio = lambda a: "UTC"
        v = {"alloggio_id": "x", "check_in": "2026-09-10", "check_out": "2026-09-11",
             "prezzo_guest_cents": 12000, "valuta": "EUR"}
        with mock.patch.object(srv, "_istante_checkin", lambda ci, fuso="": ts_ci), \
             mock.patch("time.time", lambda: float(NOW)):
            return srv.RouterHTTP._forse_penale_struttura(router, "REF-24H", v, 1)

    def setUp(self):
        self._flag = os.environ.get("PAGA_STRUTTURA_ATTIVO")
        os.environ["PAGA_STRUTTURA_ATTIVO"] = "1"             # feature accesa (dark altrimenti)

    def tearDown(self):
        if self._flag is None:
            os.environ.pop("PAGA_STRUTTURA_ATTIVO", None)
        else:
            os.environ["PAGA_STRUTTURA_ATTIVO"] = self._flag

    def test_esattamente_24h_nessuna_penale(self):
        d = self._decisione(24.0)
        self.assertEqual(d.get("motivo"), "non_tardiva",
                         "a ESATTAMENTE 24h la carta NON si tocca: 24h esatte = preavviso valido")
        self.assertFalse(d.get("applicata"))

    def test_appena_sotto_24h_e_tardiva(self):
        d = self._decisione(24.0 - 1.0 / 3600.0)             # 1 secondo sotto le 24h
        self.assertNotEqual(d.get("motivo"), "non_tardiva",
                            "sotto le 24h la disdetta E' tardiva: deve entrare nel ramo penale")
        self.assertEqual(d.get("motivo"), "carta_non_attiva",
                         "superato il confine, si ferma qui solo perche' la carta e' assente")


if __name__ == "__main__":
    unittest.main(verbosity=2)
