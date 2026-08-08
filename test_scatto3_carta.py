# -*- coding: utf-8 -*-
"""SCATTO ③ — carta host off-session (fase183). Il provider e' fetch-iniettabile: qui si
provano gli esiti con uno Stripe FINTO, senza toccare la rete ne' muovere denaro vero.

Invarianti:
  - salvataggio carta (webhook mode=setup) -> customer+pm salvati sull'host;
  - addebito RIUSCITO -> debito saldato + UNA riga 'penale_incassata' a giornale;
  - IDEMPOTENZA: ritentare lo stesso addebito NON raddoppia (giornale + Stripe idem-key);
  - carta RIFIUTATA -> debito resta 'aperto' + backoff (tentativi++/prossimo_ts), MAI saldato;
  - SCA (requires_action) -> debito aperto, nessun incasso segnato;
  - GATE: senza SCATTO3_ATTIVO lo sweep NON addebita (dormiente);
  - catena hash del giornale integra.
"""
import json
import os
import unittest

from fase177_financial_controller import crea_financial_controller
from fase183_carta_offsession import ProviderCarta


class _StripeFinto:
    """Fetch finto: registra le chiamate e risponde a piacere (succeeded/declined/SCA)."""
    def __init__(self, esito="succeeded"):
        self.esito = esito
        self.chiamate = []
        self.idem_visti = {}

    def __call__(self, metodo, url, body, headers):
        self.chiamate.append((metodo, url))
        if url.endswith("/payment_intents"):
            idem = headers.get("Idempotency-Key", "")
            # Stripe: stessa idem-key -> stessa risposta (dedup), un solo "addebito"
            if idem and idem in self.idem_visti:
                return self.idem_visti[idem]
            if self.esito == "succeeded":
                r = {"id": "pi_" + os.urandom(3).hex(), "status": "succeeded"}
            elif self.esito == "declined":
                r = {"error": {"code": "card_declined", "type": "card_error"}}
            elif self.esito == "sca":
                r = {"error": {"code": "authentication_required",
                               "payment_intent": {"id": "pi_sca"}}}
            else:
                r = {"status": "processing", "id": "pi_x"}
            if idem:
                self.idem_visti[idem] = r
            return r
        return {}


class TestScatto3Carta(unittest.TestCase):
    def setUp(self):
        self.fc = crea_financial_controller(":memory:")
        self.fc.inizializza_schema()
        # crea un debito 'aperto' scoperto: emette ND penale, nessun payout da cui offset
        class _NoPayout:
            def elenca(self, *a, **k):
                return []
        self.fc.processa_penale(riferimento="RIF1", host_id="h1", penale_cents=5000,
                                valuta="EUR", payout=_NoPayout())
        aperti = self.fc.debiti_host("h1", stato="aperto")
        self.assertEqual(len(aperti), 1)
        self.assertEqual(aperti[0]["residuo_cents"], 5000)

    def _prov(self, esito):
        return ProviderCarta("sk", fetch=_StripeFinto(esito))

    def test_addebito_riuscito_salda_e_giornale(self):
        r = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=self._prov("succeeded"),
                                      customer="cus_1", payment_method="pm_1")
        self.assertEqual(r["debiti_saldati"], 1)
        self.assertEqual(r["incassati_cents"], 5000)
        self.assertEqual(self.fc.debiti_host("h1", stato="aperto"), [])
        movs = self.fc.movimenti("RIF1")
        inc = [m for m in movs if m["tipo"] == "penale_incassata"]
        self.assertEqual(len(inc), 1)
        self.assertEqual(int(inc[0]["importo_cents"]), 5000)
        self.assertTrue(self.fc.verifica_catena().get("ok"))

    def test_idempotente_non_raddoppia(self):
        prov = self._prov("succeeded")
        self.fc.riscuoti_da_carta(host_id="h1", provider_carta=prov,
                                  customer="cus_1", payment_method="pm_1")
        # ritento (es. sweep ripetuto): il debito e' gia' saldato -> nessun nuovo addebito
        r2 = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=prov,
                                       customer="cus_1", payment_method="pm_1")
        self.assertEqual(r2["debiti_saldati"], 0)
        inc = [m for m in self.fc.movimenti("RIF1") if m["tipo"] == "penale_incassata"]
        self.assertEqual(len(inc), 1, "penale_incassata raddoppiata")

    def test_carta_rifiutata_resta_aperto_e_backoff(self):
        r = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=self._prov("declined"),
                                      customer="cus_1", payment_method="pm_1")
        self.assertEqual(r["falliti"], 1)
        self.assertEqual(r["debiti_saldati"], 0)
        aperti = self.fc.debiti_host("h1", stato="aperto")
        self.assertEqual(len(aperti), 1, "il debito NON deve sparire su carta rifiutata")
        self.assertEqual(aperti[0]["residuo_cents"], 5000)
        self.assertEqual(int(aperti[0]["tentativi"]), 1)
        self.assertTrue(int(aperti[0]["prossimo_ts"]) > 0)
        self.assertEqual([m for m in self.fc.movimenti("RIF1")
                          if m["tipo"] == "penale_incassata"], [],
                         "nessun incasso a giornale se la carta e' rifiutata")

    def test_sca_richiede_azione_niente_incasso(self):
        r = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=self._prov("sca"),
                                      customer="cus_1", payment_method="pm_1")
        self.assertEqual(r["richiede_azione"], 1)
        self.assertEqual(r["debiti_saldati"], 0)
        self.assertEqual(len(self.fc.debiti_host("h1", stato="aperto")), 1)

    def test_senza_carta_non_addebita(self):
        r = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=self._prov("succeeded"),
                                      customer="", payment_method="")
        self.assertEqual(r["incassati_cents"], 0)
        self.assertEqual(len(self.fc.debiti_host("h1", stato="aperto")), 1)

    def test_backoff_blocca_ritentativo_immediato(self):
        prov = self._prov("declined")
        self.fc.riscuoti_da_carta(host_id="h1", provider_carta=prov,
                                  customer="cus_1", payment_method="pm_1")
        # subito dopo (stesso istante) il backoff impedisce un nuovo tentativo
        prov2 = _StripeFinto("succeeded")
        r2 = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=ProviderCarta("sk", fetch=prov2),
                                       customer="cus_1", payment_method="pm_1")
        self.assertEqual(r2["debiti_saldati"], 0, "il backoff deve saltare il ritentativo")
        self.assertEqual([c for c in prov2.chiamate if c[1].endswith("/payment_intents")], [],
                         "non deve nemmeno chiamare Stripe durante il backoff")

    def test_addebito_provider_shape(self):
        """Il provider costruisce la richiesta giusta e mappa gli esiti."""
        prov = ProviderCarta("sk", fetch=_StripeFinto("succeeded"))
        out = prov.addebita(customer="cus_1", payment_method="pm_1", importo_cents=5000,
                            valuta="EUR", riferimento="RIF1", idem="carta:x:5000")
        self.assertEqual(out["stato"], "riuscito")
        out2 = prov.addebita(customer="", payment_method="pm_1", importo_cents=5000,
                             valuta="EUR", riferimento="RIF1")
        self.assertEqual(out2["stato"], "config")


class TestScatto3Router(unittest.TestCase):
    """Integrazione via router: webhook salva-carta + endpoint host + sweep GATED."""
    def _build(self):
        import datetime
        import tempfile
        import fase85_pagamenti_stripe as _stripe
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase83_server import crea_router
        from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
        _stripe.ProviderStripe._fetch_reale = staticmethod(
            lambda u, b, h: {"url": "x", "id": "cs_x"})
        d = tempfile.mkdtemp()
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_finanza=f"{d}/f.db",
            commissione_bps=1000, psp_bps=300, stripe_secret_key="sk",
            stripe_webhook_secret="whx", stripe_success_url="x", stripe_cancel_url="x"))
        r = crea_router(sis, host_key="hk", base_url="https://b.com")
        # carta provider FINTO (niente rete): salva-carta e addebito deterministici
        finto = _StripeFinto("succeeded")

        class _CartaFinta(ProviderCarta):
            def crea_link_carta(self, *, host_id, email=""):
                return "https://checkout.stripe/setup/" + host_id

            def dettagli_da_sessione(self, sid):
                return {"customer": "cus_" + sid[-4:], "payment_method": "pm_" + sid[-4:]}
        sis.carta = _CartaFinta("sk", fetch=finto)
        _, c = r.gestisci("POST", "/api/host/registrazione", {}, json.dumps(
            {"email": "h@c.it", "password": "password1", "accetta_termini": True,
             "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
             "versione": CONTRATTO_HOST_VERSIONE}), {})
        return sis, r, c["token"], c["host_id"]

    def test_webhook_setup_salva_carta(self):
        import time
        from fase87_stripe_webhook import firma_di_test
        sis, r, tok, hid = self._build()
        obj = {"id": "cs_setup_9999", "mode": "setup",
               "metadata": {"host_id": hid, "scopo": "mandato_penale_offsession"}}
        pl = json.dumps({"type": "checkout.session.completed", "data": {"object": obj}})
        st, out = r.gestisci("POST", "/api/payments/webhook", {}, pl,
                             {"Stripe-Signature": firma_di_test(pl, "whx", int(time.time()))})
        self.assertEqual(st, 200)
        info = sis.registro_host.info_host(hid)
        self.assertTrue(info["stripe_customer_id"].startswith("cus_"))
        self.assertTrue(info["stripe_payment_method"].startswith("pm_"))

    def test_host_carta_link_da_mandato(self):
        sis, r, tok, hid = self._build()
        st, out = r.gestisci("POST", "/api/host/carta_link", {}, None,
                             {"X-Host-Token": tok})
        self.assertEqual(st, 200, out)
        self.assertIn("checkout.stripe", out["url"])
        self.assertIn("Autorizzo BookinVIP", out["mandato"])

    def test_sweep_gated_dormiente(self):
        import os
        sis, r, tok, hid = self._build()
        os.environ.pop("SCATTO3_ATTIVO", None)
        self.assertEqual(r.riscuoti_debiti_carta().get("saltato"), "non_attivo")

    def test_sweep_attivo_incassa(self):
        import os
        sis, r, tok, hid = self._build()
        # carta salvata + debito scoperto
        sis.registro_host.imposta_carta(hid, "cus_1", "pm_1")
        class _NoPayout:
            def elenca(self, *a, **k):
                return []
        sis.finanza.processa_penale(riferimento="R1", host_id=hid, penale_cents=3000,
                                    valuta="EUR", payout=_NoPayout())
        os.environ["SCATTO3_ATTIVO"] = "1"
        try:
            esito = r.riscuoti_debiti_carta()
        finally:
            os.environ.pop("SCATTO3_ATTIVO", None)
        self.assertEqual(esito.get("saldati"), 1, esito)
        self.assertEqual(sis.finanza.debiti_host(hid, stato="aperto"), [])


class _Carta:
    """Provider di carta finto: registra COME e' stato chiamato, e risponde a piacere.

    Serve a guardare i PARAMETRI dell'addebito (valuta, importo, identificativi), non solo
    il risultato: quasi tutti i difetti trovati qui stanno in cio' che viene passato, non in
    cio' che torna indietro.
    """

    def __init__(self, stato="riuscito"):
        self.stato = stato
        self.chiamate = []

    def addebita(self, **kw):
        self.chiamate.append(kw)
        return {"stato": self.stato, "pi": "pi_test", "motivo": "prova"}


class _Payout:
    """Ledger dei payout finto: `elenca` registra con che valuta gli si chiede."""

    def __init__(self, righe=None):
        self.righe = righe or []
        self.chiamate = []
        self.tolti, self.impostati = [], []

    def elenca(self, host_id, stato=None, valuta=None):
        self.chiamate.append({"host_id": host_id, "stato": stato, "valuta": valuta})
        return list(self.righe)

    def imposta_importo(self, pid, n):
        self.impostati.append((pid, n))
        return True

    def rimuovi(self, pid):
        self.tolti.append(pid)
        return True


class TestRiscossioneNonPuoSbagliareIDENTIFICATIVI(unittest.TestCase):
    """⛔ 18 BUCHI VERI nella riscossione, trovati dalla mutazione il 2026-08-01.

    Campagna su tutti e 143 i punti di `fase177_financial_controller`: 97 uccisi, 45
    sopravvissuti, e **18 di quei 45 stanno nelle due funzioni che spostano denaro davvero**
    (`riscuoti_debiti`, che trattiene dai bonifici, e `riscuoti_da_carta`, che addebita
    off-session su una carta salvata via Stripe). Ognuno dei 18 e' stato ri-provato contro
    TUTTI gli 11 sorveglianti: 18 su 18 sopravvivono anche li', zero falsi allarmi.

    Le prove qui sotto sono raggruppate per PROPRIETA', non una per mutante: diciotto prove
    che dicono la stessa cosa in diciotto modi sarebbero rumore che nasconde il segnale.
    """

    def setUp(self):
        self.fc = crea_financial_controller(":memory:")
        self.fc.inizializza_schema()

    def _debito(self, valuta="EUR", cents=5000, rif="RIF1", host="h1"):
        class _NoPayout:
            def elenca(self, *a, **k):
                return []
        self.fc.processa_penale(riferimento=rif, host_id=host, penale_cents=cents,
                                valuta=valuta, payout=_NoPayout())
        return self.fc.debiti_host(host, stato="aperto")

    def test_un_identificativo_VUOTO_ferma_tutto_prima_di_toccare_i_soldi(self):
        """`not (isinstance(x, str) and x)` con un `or` accetta la stringa vuota: e' pur
        sempre una stringa. Da li' parte una riscossione con un identificativo vuoto --
        contro i bonifici di chissa' chi, o con un `customer` Stripe vuoto.

        Si pretende il rifiuto **e** che gli archivi non siano stati nemmeno interrogati:
        un rifiuto che ha gia' chiamato il provider di pagamento non e' un rifiuto.
        """
        self._debito()
        # ⛔ L'OSSERVABILE DEVE STARE AL GRADINO GIUSTO. Prima pretendevo «i payout non
        # vengono interrogati»: ma col guasto dentro la funzione PROSEGUE, chiede i debiti di
        # "", non ne trova, e finisce senza toccare i payout -- stesso osservabile, guasto
        # invisibile (provato: il mutante sopravviveva). Cio' che distingue davvero e' se
        # l'ARCHIVIO DEI DEBITI viene interrogato: un rifiuto vero non guarda niente.
        visti = []
        vero_debiti_host = self.fc.debiti_host
        self.fc.debiti_host = lambda *a, **k: visti.append((a, k)) or []
        try:
            for storto in ("", None, 0, [], 123):
                p = _Payout([{"prenotazione_id": "P9", "minori": 9999}])
                e = self.fc.riscuoti_debiti(host_id=storto, payout=p)
                self.assertEqual(0, e["riscossi_cents"], "host_id %r accettato" % (storto,))
                self.assertEqual([], visti,
                                 "con host_id %r ha comunque interrogato l'archivio dei "
                                 "debiti: il rifiuto non e' avvenuto prima" % (storto,))
                self.assertEqual([], p.chiamate)
                c = _Carta()
                e = self.fc.riscuoti_da_carta(host_id=storto, provider_carta=c,
                                              customer="cus_1", payment_method="pm_1")
                self.assertEqual(0, e["incassati_cents"])
                self.assertEqual([], visti,
                                 "con host_id %r la riscossione su carta ha comunque "
                                 "interrogato i debiti" % (storto,))
                self.assertEqual([], c.chiamate,
                                 "ha chiamato la carta con host_id %r" % (storto,))
        finally:
            self.fc.debiti_host = vero_debiti_host
        # e gli identificativi Stripe: vuoti o storti -> nessun addebito
        for cus, pm in (("", "pm_1"), ("cus_1", ""), (None, "pm_1"), ("cus_1", None),
                        (7, "pm_1"), ("cus_1", [])):
            c = _Carta()
            e = self.fc.riscuoti_da_carta(host_id="h1", provider_carta=c,
                                          customer=cus, payment_method=pm)
            self.assertEqual([], c.chiamate,
                             "addebito tentato con customer=%r payment_method=%r" % (cus, pm))
            self.assertEqual(0, e["incassati_cents"])

    def test_la_VALUTA_del_debito_non_diventa_mai_euro_per_conto_suo(self):
        """`str(deb.get("valuta") or "EUR")` con un `and` restituisce **sempre "EUR"**.

        Due punti diversi, due danni diversi e tutti e due veri:
          · nella riscossione sui bonifici si cercherebbero payout in euro per un debito in
            un'altra valuta -- e il modulo dichiara «STESSA valuta» come sua garanzia;
          · sulla carta si addebiterebbe **denaro vero nella valuta sbagliata**, con la
            conversione fatta dalla banca dell'host e a carico suo.
        """
        self._debito(valuta="USD", cents=4200, rif="RIFUSD")
        p = _Payout([])
        self.fc.riscuoti_debiti(host_id="h1", payout=p)
        self.assertTrue(p.chiamate, "i payout non sono stati nemmeno interrogati")
        self.assertEqual(["USD"], sorted({c["valuta"] for c in p.chiamate}),
                         "il debito e' in USD ma i payout sono stati cercati in: %r"
                         % ([c["valuta"] for c in p.chiamate],))
        c = _Carta()
        self.fc.riscuoti_da_carta(host_id="h1", provider_carta=c,
                                  customer="cus_1", payment_method="pm_1")
        self.assertTrue(c.chiamate, "nessun addebito tentato")
        self.assertEqual(["USD"], sorted({x["valuta"] for x in c.chiamate}),
                         "addebito su carta nella valuta sbagliata: %r"
                         % ([x["valuta"] for x in c.chiamate],))

    def test_non_si_riscuote_dal_bonifico_della_prenotazione_del_debito_STESSO(self):
        """E' una garanzia scritta nel modulo: *«mai il payout della prenotazione del debito
        stesso»*. Serve perche' quel bonifico e' gia' legato alla prenotazione contestata:
        prenderlo significherebbe pagarsi due volte con lo stesso denaro, e lasciare
        scoperta la prenotazione da cui il debito nasce.
        """
        self._debito(cents=5000, rif="RIF1")
        p = _Payout([{"prenotazione_id": "RIF1", "minori": 9999}])   # proprio quella del debito
        e = self.fc.riscuoti_debiti(host_id="h1", payout=p)
        self.assertEqual(0, e["riscossi_cents"],
                         "ha riscosso dal bonifico della prenotazione del debito stesso")
        self.assertEqual([], p.impostati + [(x, None) for x in p.tolti],
                         "il payout della prenotazione contestata e' stato toccato: %r"
                         % (p.impostati + p.tolti,))
        # ...e il verso opposto: da un ALTRO bonifico si riscuote eccome, se no basterebbe
        # non riscuotere mai per far passare la meta' di sopra.
        p2 = _Payout([{"prenotazione_id": "P_ALTRA", "minori": 9999}])
        e2 = self.fc.riscuoti_debiti(host_id="h1", payout=p2)
        self.assertEqual(5000, e2["riscossi_cents"], "non riscuote nemmeno dove dovrebbe")

    def test_una_carta_RIFIUTATA_non_si_martella(self):
        """`prossimo > ora` diventa `>=`: un debito ancora in attesa (backoff) verrebbe
        ritentato **subito**.

        Il modulo lo dichiara: *«una carta rifiutata non si martella»*. Non e' cortesia: una
        raffica di tentativi su una carta rifiutata viene letta dalle banche come tentativo
        di frode, e mette a rischio il conto commerciante -- cioe' la possibilita' stessa di
        incassare. Il danno non e' il singolo addebito: e' restare senza pagamenti.
        """
        self._debito(cents=5000)
        c1 = _Carta("fallito")
        self.fc.riscuoti_da_carta(host_id="h1", provider_carta=c1,
                                  customer="cus_1", payment_method="pm_1", ora_ts=1_000_000)
        self.assertEqual(1, len(c1.chiamate), "il primo tentativo deve avvenire")
        aperti = self.fc.debiti_host("h1", stato="aperto")
        self.assertEqual(1, len(aperti), "dopo un rifiuto il debito resta aperto")
        self.assertGreater(int(aperti[0]["prossimo_ts"]), 1_000_000,
                           "nessuna attesa impostata dopo il rifiuto")
        # ...e adesso, PRIMA che l'attesa sia scaduta, non si ritenta
        c2 = _Carta("riuscito")
        self.fc.riscuoti_da_carta(host_id="h1", provider_carta=c2,
                                  customer="cus_1", payment_method="pm_1", ora_ts=1_000_001)
        self.assertEqual([], c2.chiamate,
                         "carta martellata: ritentata mentre era ancora in attesa")
        # ⛔ IL CONFINE ESATTO, che e' l'unico punto dove `>` e `>=` differiscono: all'istante
        # PRECISO della scadenza l'attesa e' finita, quindi si ritenta. Provare solo «prima» e
        # «dopo» lascia vivo il guasto -- misurato: il mutante sopravviveva a entrambe.
        scadenza = int(aperti[0]["prossimo_ts"])
        c3 = _Carta("riuscito")
        self.fc.riscuoti_da_carta(host_id="h1", provider_carta=c3, customer="cus_1",
                                  payment_method="pm_1", ora_ts=scadenza)
        self.assertEqual(1, len(c3.chiamate),
                         "all'istante esatto della scadenza l'attesa e' finita e il "
                         "ritentativo deve avvenire: un giorno di ritardo a ogni giro")

    def test_un_residuo_a_ZERO_non_muove_niente(self):
        """`if not nota_id or residuo <= 0: continue` e `if residuo <= 0: break` con `and` o
        con `<`: un debito gia' saldato (residuo 0) rientrerebbe nel giro. Nel migliore dei
        casi gira a vuoto; nel peggiore registra movimenti da zero centesimi nel libro che
        alimenta il DAC7."""
        self._debito(cents=5000)
        p = _Payout([{"prenotazione_id": "P1", "minori": 9999}])
        self.fc.riscuoti_debiti(host_id="h1", payout=p)      # salda tutto
        self.assertEqual([], self.fc.debiti_host("h1", stato="aperto"))
        prima = len(self.fc.movimenti("RIF1"))
        p2 = _Payout([{"prenotazione_id": "P2", "minori": 9999}])
        e = self.fc.riscuoti_debiti(host_id="h1", payout=p2)
        self.assertEqual(0, e["riscossi_cents"], "ha riscosso su un debito gia' saldato")
        self.assertEqual([], p2.impostati + p2.tolti, "ha toccato i payout a debito zero")
        self.assertEqual(prima, len(self.fc.movimenti("RIF1")),
                         "ha scritto movimenti nuovi su un debito gia' chiuso")

    def test_un_debito_DEGENERE_non_fa_partire_nessuna_riscossione(self):
        """⛔ I DUE CONTROLLI CHE PROTEGGONO DA UNO STATO IMPOSSIBILE.

            if not nota_id or residuo <= 0: continue

        Difendono da righe che l'uso normale non produce ma un'interruzione si': un debito
        rimasto 'aperto' con residuo gia' a zero (scrittura interrotta fra il consumo e
        l'aggiornamento dello stato), o senza identificativo. Con `and` al posto di `or`, o
        con `<` al posto di `<=`, quelle righe entrano nel giro:
          · quella a residuo zero fa interrogare i bonifici per niente;
          · quella senza identificativo fa scrivere nel giornale un movimento con evento
            `offset::<pagamento>` -- una riga contabile agganciata a un debito che non ha
            nome, quindi impossibile da riconciliare e da stornare.

        Le righe si costruiscono con `_debito_scrivi` (metodo interno) perche' l'ingresso
        pubblico non permette di crearle: e' esattamente il motivo per cui quei due controlli
        esistono, e l'unico modo di provare che servono davvero.
        """
        # (a) debito 'aperto' con residuo gia' a zero
        self.fc._debito_scrivi("ND-ZERO", "h1", "RIF-ZERO", 0, "EUR", "aperto")
        p = _Payout([{"prenotazione_id": "P1", "minori": 9999}])
        e = self.fc.riscuoti_debiti(host_id="h1", payout=p)
        self.assertEqual(0, e["riscossi_cents"])
        self.assertEqual([], p.chiamate,
                         "un debito a residuo zero ha fatto interrogare i bonifici: %r"
                         % (p.chiamate,))
        # (b) debito senza identificativo, con residuo VERO
        self.fc._debito_scrivi("", "h1", "RIF-SENZA-NOME", 5000, "EUR", "aperto")
        p2 = _Payout([{"prenotazione_id": "P2", "minori": 9999}])
        e2 = self.fc.riscuoti_debiti(host_id="h1", payout=p2)
        self.assertEqual(0, e2["riscossi_cents"],
                         "ha riscosso su un debito senza identificativo")
        self.assertEqual([], self.fc.movimenti("RIF-SENZA-NOME"),
                         "ha scritto nel giornale un movimento agganciato a un debito senza "
                         "nome: impossibile da riconciliare e da stornare")

    def _con_debiti_rotti(self, azione):
        """Esegue `azione` con l'archivio dei debiti che solleva. Ripristina sempre."""
        vero = self.fc.debiti_host

        def _rompi(*a, **k):
            raise RuntimeError("archivio debiti guasto")

        self.fc.debiti_host = _rompi
        try:
            return azione()
        finally:
            self.fc.debiti_host = vero

    def test_ogni_guasto_ISOLATO_della_riscossione_lascia_la_TRACCIA(self):
        """Cinque punti di queste due funzioni ingoiano i guasti di proposito: un archivio
        rotto non deve fermare la riscossione degli altri debiti. Proprio per questo la
        traccia dell'eccezione e' l'unica cosa che resta -- e qui si parla di denaro che non
        e' entrato: senza il PERCHE', nessuno sapra' mai se e' un problema di rete, di carta
        o di archivio.

        ⚠️ Osservabile FORTE: con `exc_info=False` il campo del record vale `False`, che NON
        e' `None` -- un `assertIsNotNone` passerebbe col guasto dentro.
        """
        import logging

        def _esplode(*a, **k):
            raise RuntimeError("archivio guasto")

        self._debito(cents=5000)
        casi = []
        # l'archivio dei debiti stesso illeggibile: e' il PRIMO passo di tutte e due le
        # funzioni, e se salta non si riscuote niente da nessuno. Senza la traccia, il
        # registro direbbe solo «non si e' potuto leggere», mai perche'.
        rotto = _Payout([{"prenotazione_id": "P1", "minori": 9999}])
        casi.append(("lettura dei debiti (riscossione sui payout)",
                     lambda: self._con_debiti_rotti(
                         lambda: self.fc.riscuoti_debiti(host_id="h1", payout=rotto))))
        casi.append(("lettura dei debiti (riscossione su carta)",
                     lambda: self._con_debiti_rotti(
                         lambda: self.fc.riscuoti_da_carta(
                             host_id="h1", provider_carta=_Carta(),
                             customer="cus_1", payment_method="pm_1"))))
        p_rotto = _Payout()
        p_rotto.elenca = _esplode
        casi.append(("lettura dei payout",
                     lambda: self.fc.riscuoti_debiti(host_id="h1", payout=p_rotto)))
        p_ledger = _Payout([{"prenotazione_id": "P1", "minori": 9999}])
        p_ledger.imposta_importo = _esplode
        p_ledger.rimuovi = _esplode
        casi.append(("aggiornamento del ledger payout",
                     lambda: self.fc.riscuoti_debiti(host_id="h1", payout=p_ledger)))
        c = _Carta()
        c.addebita = _esplode
        casi.append(("addebito sulla carta",
                     lambda: self.fc.riscuoti_da_carta(host_id="h1", provider_carta=c,
                                                       customer="cus_1", payment_method="pm_1")))
        for nome, azione in casi:
            with self.assertLogs("core_auto.financial_controller", level="WARNING") as reg:
                azione()
            tracce = [r.exc_info for r in reg.records
                      if r.levelno == logging.WARNING and r.exc_info is not None]
            self.assertTrue(tracce, "nessun allarme con traccia per il guasto su %s: %r"
                            % (nome, reg.output))
            for t in tracce:
                self.assertIsInstance(t, tuple,
                                      "l'allarme su %s non porta la traccia (exc_info=%r)"
                                      % (nome, t))
                self.assertIsInstance(t[1], BaseException,
                                      "la traccia su %s non contiene l'eccezione" % nome)


class TestNonSiChiedeUnaCartaCheNonSiPUOAddebitare(unittest.TestCase):
    """⛔ NON SI CHIEDE UNA GARANZIA CHE NON SI PUO' USARE.

    Trovato dal FONDATORE il 2026-08-08, guardando il pannello host -- non da un
    test. La sua obiezione, con parole sue: «se sono dentro il pannello host e dice
    di collegare una carta, li' va messo l'IBAN, non il numero della carta col CVC».

    Aveva ragione, e la misura lo conferma: la scheda della carta compariva perche'
    ESISTE LA CHIAVE STRIPE (`self._sys.carta is not None`), mentre l'addebito vero
    e' spento da un interruttore DIVERSO, `SCATTO3_ATTIVO`, che vale "0" per difetto
    ed e' assente in produzione (misurato nel contenitore vivo: NON IMPOSTATA).

    Cioe' chiedevamo all'host il numero della sua carta per una garanzia che non
    avremmo potuto incassare. Tutto il costo di fiducia, zero beneficio -- e nel
    momento peggiore, mentre si recluta il primo host vero.

    ⚠️ Non e' un difetto di sicurezza: il numero non passa da noi (si digita su
    Stripe, a noi torna solo `cus_...`/`pm_...`; cercato nel codice: zero occorrenze
    di numero carta, CVC, scadenza). E' un difetto di COERENZA: due interruttori che
    governano la stessa funzione e dicono cose diverse.

    La riparazione e' una riga: la scheda compare solo se l'addebito e' acceso.
    Il giorno che il fondatore mette SCATTO3_ATTIVO=1, torna da sola.

    ⚠️ Questa e' la famiglia di difetti che la piramide dei test NON prende: nessuno
    aveva scritto la regola «non chiederla se non puoi usarla», quindi non c'era
    niente da far fallire. Lo dicono i documenti del progetto: «i test provano che il
    codice fa quello che dice; nessuno chiedeva cosa vede una persona».
    """

    def _monta(self):
        # si riusa il montaggio di TestScatto3Router senza ereditarne i test (che
        # verrebbero rieseguiti). `_build` non usa `self` per altro.
        return TestScatto3Router._build(self)

    def _stato(self, r, tok):
        return r.gestisci("GET", "/api/host/carta_stato", {}, None, {"X-Host-Token": tok})

    def test_la_scheda_NON_si_offre_se_l_addebito_e_spento(self):
        sis, r, tok, hid = self._monta()
        os.environ.pop("SCATTO3_ATTIVO", None)
        st, out = self._stato(r, tok)
        self.assertEqual(200, st, out)
        self.assertFalse(
            out.get("attivo"),
            "il pannello host OFFRE la carta di garanzia (attivo=True) mentre "
            "l'addebito e' spento (SCATTO3_ATTIVO assente): stiamo chiedendo il "
            "numero di una carta che non potremmo mai incassare. Due interruttori "
            "sulla stessa funzione devono dire la stessa cosa")

    def test_la_scheda_SI_offre_quando_l_addebito_e_acceso(self):
        """L'altra direzione, obbligatoria: un allarme provato in un verso solo
        potrebbe gridare sempre, e un allarme sempre acceso viene spento."""
        sis, r, tok, hid = self._monta()
        os.environ["SCATTO3_ATTIVO"] = "1"
        try:
            st, out = self._stato(r, tok)
        finally:
            os.environ.pop("SCATTO3_ATTIVO", None)
        self.assertEqual(200, st, out)
        self.assertTrue(
            out.get("attivo"),
            "con l'addebito ACCESO la scheda deve tornare disponibile: se restasse "
            "spenta, la riparazione avrebbe ucciso la funzione invece di allinearla")

    def test_e_senza_il_provider_resta_spenta_comunque(self):
        """Terzo caso, che la riparazione non deve perdere: se manca la chiave
        Stripe non c'e' provider, e allora la scheda non si offre nemmeno con
        l'interruttore acceso -- altrimenti si offrirebbe un bottone che non apre
        niente."""
        sis, r, tok, hid = self._monta()
        sis.carta = None
        os.environ["SCATTO3_ATTIVO"] = "1"
        try:
            st, out = self._stato(r, tok)
        finally:
            os.environ.pop("SCATTO3_ATTIVO", None)
        self.assertEqual(200, st, out)
        self.assertFalse(
            out.get("attivo"),
            "senza provider carta la scheda si offre lo stesso: il bottone "
            "«Aggiungi carta» non aprirebbe niente")


if __name__ == "__main__":
    unittest.main(verbosity=2)
