"""CASELLA 2 del Blocco 1 (SOLDI) — LA CATENA INTERA, UNA STRADA PER VOLTA.

`test_rimborso_ogni_strada.py` conta le strade (SETTE, lette dall'albero sintattico).
`test_rimborso_in_lista_col_dovuto.py` prova che arrivano in lista con la cifra giusta.
`test_rimborso_arriva_al_gateway.py` prova che dal pannello i soldi partono davvero.
Tre file, tre pezzi: nessuno percorreva una strada **da capo a fondo**. Qui ogni strada e'
percorsa intera, dentro UN solo collaudo, e si pretendono tutti gli anelli in ordine:

    la strada scrive il dovuto -> la lista lo mostra CON il pulsante -> il pulsante manda al
    gateway QUELLA cifra su QUEL pagamento -> la riga esce perche' STRIPE conferma (non perche'
    l'abbiamo tolta noi) -> premere di nuovo non restituisce due volte.

⛔ IL GATEWAY E' FINTO MA IL PROVIDER E' VERO. Non si sostituisce `sis.stripe` con una spia:
   si sostituisce SOLO la rete (`ProviderStripe._fetch_reale`) con uno Stripe che RICORDA i
   rimborsi che ha creato. Cosi' girano davvero `fase85.rimborsa()` e `fase85.rimborsi_di()`,
   e «la riga esce perche' lo dice Stripe» e' misurato sul codice di produzione, non su un
   finto che risponde quello che ci serve.

⛔ L'ATTESO E' MISURATO PRIMA, non ipotizzato: dove la cifra la calcola una regola (scaglione,
   100%, totale, anticipo) l'asserzione e' `==` con la cifra che la regola dichiara alla
   fonte (la risposta della cancellazione, il preventivo, l'anticipo del `book`), mai `> 0`.
   Un `> 0` passa anche con l'importo sbagliato, cioe' col difetto che qui si deve prendere.

⛔ LA SETTIMA STRADA (la controversia) AVEVA UN'USCITA MANUALE, E ORA HA IL PULSANTE. Fino al
   4 settembre 2026 la riga compariva SENZA pulsante (`manca: date_liberate`: il soggiorno c'e'
   stato) e la cifra decisa nel pannello andava riscritta a mano su Stripe. Ordine del fondatore
   («le cifre le metto io … avere il pulsante da cliccare», «autorizzato»): `_rimborso_dovuto_
   scheda` riconosce la controversia risolta (garanzia «risolto» con ESATTAMENTE la cifra in
   lista) e al posto delle date pretende l'aritmetica «quota host + rimborso <= pagato». Qui la
   catena e' intera come per le altre sei, e il freno nuovo e' provato nelle DUE direzioni:
   cifra diversa in garanzia -> niente pulsante; host + ospite oltre il pagato -> niente pulsante.

⚠️ COSA QUESTO FILE NON DIMOSTRA (D18 punto 3): che Stripe esegua davvero (per quello c'e'
   `collaudi/e2e_rimborso_stripe.py`, con la chiave di prova, che dal 4 settembre preme anche
   il pulsante della controversia); che la cifra sia giusta in valuta diversa dall'euro
   (`test_admin_rimborso_money` ne copre una parte).
"""
import datetime
import json
import os
import secrets
import shutil
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlparse

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_ogni_strada"
CHIAVE_FINTA = "sk"          # come negli altri banchi: la rete e' finta, la chiave non conta


class _StripeCheRicorda:
    """La RETE di Stripe, finta: risponde alle due domande del provider vero.

    · POST /v1/refunds  -> crea un rimborso e lo RICORDA (deduplicato sull'`Idempotency-Key`,
      come fa Stripe: docs.stripe.com/api/idempotent_requests);
    · GET  /v1/refunds?payment_intent=... -> restituisce quelli ricordati.
    Tutto il resto (la sessione di checkout) e' una risposta di comodo.
    `creazioni` e' cio' che il gateway HA RICEVUTO: l'ultimo anello prima dei soldi veri."""

    def __init__(self):
        self.per_pi = {}
        self.per_chiave = {}
        self.creazioni = []

    def __call__(self, url, body, headers):
        if "/refunds" in url and not body:
            pi = (parse_qs(urlparse(url).query).get("payment_intent") or [""])[0]
            return {"object": "list", "data": list(self.per_pi.get(pi, []))}
        if "/refunds" in url:
            campi = parse_qs(body.decode("utf-8"))
            pi = (campi.get("payment_intent") or [""])[0]
            importo = int((campi.get("amount") or ["0"])[0] or 0)
            chiave = {k.lower(): v for k, v in (headers or {}).items()}.get("idempotency-key", "")
            self.creazioni.append({"payment_intent": pi, "importo_cents": importo,
                                   "chiave": chiave})
            if chiave and chiave in self.per_chiave:
                return dict(self.per_chiave[chiave])
            rid = "re_%s" % secrets.token_hex(4)
            risposta = {"id": rid, "status": "succeeded", "object": "refund"}
            if chiave:
                self.per_chiave[chiave] = risposta
            self.per_pi.setdefault(pi, []).append(
                {"id": rid, "status": "succeeded", "amount": importo})
            return dict(risposta)
        return {"url": "https://x/cs", "id": "cs_" + secrets.token_hex(4)}

    def rimborso_fatto_a_mano(self, pi, importo_cents):
        """Una persona ha rimborsato dal pannello di Stripe: il nostro codice non l'ha
        chiamato, ma alla prossima domanda Stripe lo dira'."""
        self.per_pi.setdefault(pi, []).append(
            {"id": "re_mano_%s" % secrets.token_hex(2), "status": "succeeded",
             "amount": int(importo_cents)})


class _BancoDelleStrade(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._orig_fetch = _stripe.ProviderStripe._fetch_reale

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig_fetch

    def setUp(self):
        self.stripe = _StripeCheRicorda()
        _stripe.ProviderStripe._fetch_reale = staticmethod(self.stripe)
        d = self.dir = tempfile.mkdtemp()
        # ⛔ `db_finanza` non e' un dettaglio del banco: la lista dei rimborsi dovuti nasce dal
        #    giornale immutabile (fase177), e senza giornale la lista risponde «non lo so».
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db", db_finanza=f"{d}/fin.db",
            commissione_bps=1000, psp_bps=0, stripe_secret_key=CHIAVE_FINTA,
            stripe_webhook_secret=WH, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@os.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        self.oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "Casa", "citta": "Roma", "prezzo_notte_cents": 50000,
                "capacita": 4, "politica_cancellazione": "flessibile"}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": self.oggi.isoformat(),
                "a": (self.oggi + datetime.timedelta(days=60)).isoformat(),
                "unita_totali": 1, "prezzo_netto_cents": 50000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    # ── attrezzi ──────────────────────────────────────────────────────────────
    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def date(self, da, notti=2):
        ci = self.oggi + datetime.timedelta(days=da)
        return ci.isoformat(), (ci + datetime.timedelta(days=notti)).isoformat()

    def prenota(self, ci, co, email, extra=None):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        self.assertEqual(s, 200, "PREMESSA NON VALIDA: niente preventivo: %r" % (q,))
        corpo = {"quote_token": q["quote_token"], "email": email}
        corpo.update(extra or {})
        s, b = self.g("POST", "/api/concierge/book", corpo)
        self.assertEqual(s, 201, "PREMESSA NON VALIDA: la prenotazione non riesce: %r" % (b,))
        totale = int(q.get("totale_cents") or q.get("prezzo_guest_cents") or 0)
        self.assertGreater(totale, 0, "PREMESSA NON VALIDA: preventivo a zero: %r" % (q,))
        return b, totale

    def paga(self, rif, pi):
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": "cs_" + pi, "payment_intent": pi,
                                             "metadata": {"riferimento": rif}}}})
        s, o = self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                               {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        self.assertEqual(s, 200, "PREMESSA NON VALIDA: il webhook non e' accettato: %r" % (o,))

    def lista(self):
        s, corpo = self.g("GET", "/api/admin/rimborsi_dovuti", None, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, "la lista dei rimborsi dovuti non risponde: %r" % (corpo,))
        self.assertTrue(corpo.get("controllabile"),
                        "la lista non e' CONTROLLABILE (Stripe finto non risponde?): %r"
                        % (corpo.get("motivo_non_controllabile"),))
        return corpo

    def riga(self, rif):
        for r in self.lista().get("rimborsi") or []:
            if r.get("riferimento") == rif:
                return r
        return None

    def premi(self, rif):
        return self.g("POST", "/api/admin/rimborsa_dovuto", {"riferimento": rif},
                      {"X-Admin-Key": "ak"})

    def idem_key_vera(self, rif):
        _, adm = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Key": "ak"})
        for p in (adm or {}).get("prenotazioni", []):
            if str(p.get("idem_key", ""))[:24] == rif:
                return p.get("idem_key")
        return None

    def stanza_rubata(self, rif, ci, co, chi):
        """L'attesa scade, un altro si prende la stanza (e ne ha diritto): il pagamento del
        primo arrivera' dopo, tardivo, su una stanza gia' presa."""
        pp = self.sis.pagamenti_pendenti
        rec = pp.info(rif)
        self.assertIsNotNone(rec, "PREMESSA NON VALIDA: il pendente deve esistere")
        pp.scadi(rif)
        self.sis.inventario.rilascia("casa", ci, co,
                                     idem_key=(rec.get("idem_key") or ("hold_" + rif)))
        ladro = self.sis.inventario.blocca("casa", ci, co, idem_key=chi + rif)
        self.assertTrue(getattr(ladro, "ok", False),
                        "PREMESSA NON VALIDA: dopo il rilascio la stanza doveva essere libera")

    # ── LA CATENA, uguale per ogni strada che passa dal pulsante ──────────────
    def catena_dal_pulsante(self, strada, rif, pi, atteso):
        riga = self.riga(rif)
        self.assertIsNotNone(
            riga, "[%s] LA STRADA NON ARRIVA IN LISTA: il dovuto e' stato scritto (o doveva "
                  "esserlo) e nel pannello di chi aspetta i suoi soldi non c'e' niente. Nessuno "
                  "restituira' quei soldi, perche' nessuno sa che sono dovuti." % strada)
        self.assertEqual(
            riga.get("dovuto_cents"), atteso,
            "[%s] IN LISTA C'E' L'IMPORTO SBAGLIATO: %s invece di %s. Una riga col numero "
            "sbagliato e' peggio di una riga mancante: la mancante si nota, questa viene "
            "eseguita." % (strada, riga.get("dovuto_cents"), atteso))
        self.assertTrue(
            riga.get("bottone"),
            "[%s] LA RIGA C'E' MA NON SI PUO' PREMERE (manca: %r): la promessa e' scritta e "
            "i soldi non possono partire dal pannello." % (strada, riga.get("manca")))
        self.assertEqual(self.stripe.creazioni, [],
                         "[%s] PREMESSA NON VALIDA: il gateway ha gia' ricevuto qualcosa "
                         "prima che il pulsante fosse premuto: %r" % (strada, self.stripe.creazioni))

        s, o = self.premi(rif)
        self.assertEqual(s, 200, "[%s] il pulsante non ha eseguito: %r" % (strada, o))
        self.assertEqual(o.get("stato"), "rimborsato", "[%s] risposta: %r" % (strada, o))
        self.assertEqual(o.get("importo_cents"), atteso,
                         "[%s] la rotta dichiara di aver restituito %s, la lista diceva %s"
                         % (strada, o.get("importo_cents"), atteso))
        self.assertEqual(
            len(self.stripe.creazioni), 1,
            "[%s] I SOLDI NON SONO PARTITI (o sono partiti piu' volte): il gateway ha "
            "ricevuto %r. Il 200 della rotta e la riga nel giornale non sono soldi."
            % (strada, self.stripe.creazioni))
        c = self.stripe.creazioni[0]
        self.assertEqual(c["importo_cents"], atteso,
                         "[%s] IL GATEWAY HA RICEVUTO %s MENTRE ERANO DOVUTI %s: all'ospite "
                         "tornerebbe una cifra diversa." % (strada, c["importo_cents"], atteso))
        self.assertEqual(c["payment_intent"], pi,
                         "[%s] IL GATEWAY HA RICEVUTO IL PAGAMENTO SBAGLIATO (%r): i soldi "
                         "partirebbero da un'altra transazione." % (strada, c["payment_intent"]))
        self.assertTrue(c["chiave"],
                        "[%s] nessuna Idempotency-Key: un ritentativo di rete restituirebbe "
                        "due volte." % strada)

        self.assertIsNone(
            self.riga(rif),
            "[%s] STRIPE HA IL RIMBORSO E LA RIGA E' ANCORA IN LISTA: il pannello non legge la "
            "verita' dalla fonte, e chi la vede premerebbe di nuovo." % strada)
        s2, o2 = self.premi(rif)
        self.assertEqual((s2, o2.get("stato")), (200, "gia_rimborsato"),
                         "[%s] premuto due volte: %r" % (strada, o2))
        self.assertEqual(len(self.stripe.creazioni), 1,
                         "[%s] PREMUTO DUE VOLTE, PARTITO DUE VOLTE: %r"
                         % (strada, self.stripe.creazioni))


class TestISoldiTornanoDaOgniStrada(_BancoDelleStrade):

    def test_STRADA_cancellazione_OSPITE_da_capo_a_fondo(self):
        """«rimborso dovuto per cancellazione ospite»: lo SCAGLIONE della politica."""
        ci, co = self.date(10)
        b, _totale = self.prenota(ci, co, "osp@os.it")
        rif, pi = b["riferimento"], "pi_osp"
        self.paga(rif, pi)
        s, canc = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, "PREMESSA NON VALIDA: la cancellazione non riesce: %r" % (canc,))
        atteso = int(canc.get("rimborso_cents") or 0)
        self.assertGreater(atteso, 0, "PREMESSA NON VALIDA: la politica flessibile a 10 giorni "
                                      "deve rendere qualcosa: %r" % (canc,))
        self.catena_dal_pulsante("cancellazione ospite", rif, pi, atteso)

    def test_STRADA_cancellazione_HOST_da_capo_a_fondo(self):
        """«rimborso 100% per cancellazione host»: la colpa e' dell'host, torna il TOTALE."""
        ci, co = self.date(12)
        b, totale = self.prenota(ci, co, "hst@os.it")
        rif, pi = b["riferimento"], "pi_hst"
        self.paga(rif, pi)
        s, o = self.g("POST", "/api/host/cancella", {"riferimento": rif}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 200, "PREMESSA NON VALIDA: la cancellazione host non riesce: %r" % (o,))
        self.assertEqual(int(o.get("rimborso_cliente_cents") or 0), totale,
                         "PREMESSA NON VALIDA: la rotta stessa non dichiara il 100%%: %r" % (o,))
        self.catena_dal_pulsante("cancellazione host", rif, pi, totale)

    def test_STRADA_pagamento_NON_CONFERMABILE_da_capo_a_fondo(self):
        """«pagamento su prenotazione non confermabile»: cancella PRIMA di pagare, poi il
        pagamento arriva lo stesso dal link ancora vivo. Non compra niente: torna il TOTALE."""
        ci, co = self.date(14)
        b, totale = self.prenota(ci, co, "ncf@os.it")
        rif, pi = b["riferimento"], "pi_ncf"
        s, canc = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, "PREMESSA NON VALIDA: la cancellazione non riesce: %r" % (canc,))
        self.assertIsNone(self.riga(rif), "PREMESSA NON VALIDA: senza aver pagato non deve "
                                          "esserci nessun rimborso dovuto")
        self.paga(rif, pi)
        self.catena_dal_pulsante("pagamento non confermabile", rif, pi, totale)

    def test_STRADA_pagamento_TARDIVO_su_stanza_presa_da_capo_a_fondo(self):
        """«pagamento tardivo su stanza presa»: non ha avuto niente, torna il TOTALE."""
        ci, co = self.date(16)
        b, totale = self.prenota(ci, co, "trd@os.it")
        rif, pi = b["riferimento"], "pi_trd"
        self.stanza_rubata(rif, ci, co, "veloce_")
        self.paga(rif, pi)
        self.assertEqual(self.sis.pagamenti_pendenti.info(rif)["stato"], "rimborsato",
                         "PREMESSA NON VALIDA: stanza presa da altri -> il pagatore tardivo va "
                         "rimborsato")
        self.catena_dal_pulsante("pagamento tardivo", rif, pi, totale)

    def test_STRADA_anticipo_TARDIVO_paga_in_struttura_da_capo_a_fondo(self):
        """«anticipo su stanza gia' presa»: online e' arrivato SOLO l'anticipo, e torna quello.
        Restituire il totale renderebbe denaro mai incassato."""
        prec = os.environ.get("PAGA_STRUTTURA_ATTIVO")
        os.environ["PAGA_STRUTTURA_ATTIVO"] = "1"
        try:
            ci, co = self.date(18)
            b, totale = self.prenota(ci, co, "ant@os.it", {"modo_pagamento": "in_struttura"})
            self.assertEqual(b.get("modo_pagamento"), "in_struttura",
                             "PREMESSA NON VALIDA: non e' in struttura: %r" % (b,))
            anticipo = int(b.get("anticipo_online_cents") or 0)
            self.assertTrue(0 < anticipo < totale,
                            "PREMESSA NON VALIDA: l'anticipo (%s) deve essere fra 0 e il "
                            "totale (%s), altrimenti la prova non distingue le due cifre"
                            % (anticipo, totale))
            rif, pi = b["riferimento"], "pi_ant"
            self.stanza_rubata(rif, ci, co, "veloce_ps_")
            self.paga(rif, pi)
            self.catena_dal_pulsante("anticipo tardivo", rif, pi, anticipo)
        finally:
            if prec is None:
                os.environ.pop("PAGA_STRUTTURA_ATTIVO", None)
            else:
                os.environ["PAGA_STRUTTURA_ATTIVO"] = prec

    def test_STRADA_rimborso_ADMIN_da_capo_a_fondo(self):
        """«rimborso disposto da admin»: l'unica strada che fa partire i soldi DA SE', col
        TOTALE; poi la lista NON la mostra, perche' Stripe conferma che sono gia' tornati."""
        ci, co = self.date(20)
        b, totale = self.prenota(ci, co, "adm@os.it")
        rif, pi = b["riferimento"], "pi_adm"
        self.paga(rif, pi)
        idem = self.idem_key_vera(rif)
        self.assertIsNotNone(idem, "PREMESSA NON VALIDA: idem_key non trovata nel pannello")
        self.assertEqual(self.stripe.creazioni, [], "PREMESSA NON VALIDA: gateway gia' toccato")

        s, o = self.g("POST", "/api/admin/rimborso",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "idem_key": idem},
                      {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, "la strada non e' stata percorsa: %r" % (o,))
        self.assertEqual(o.get("passi_falliti"), [],
                         "un passo di sicurezza e' fallito, quindi i soldi NON dovevano "
                         "partire da soli: %r" % (o,))
        self.assertEqual(len(self.stripe.creazioni), 1,
                         "I SOLDI NON SONO PARTITI dal rimborso admin: %r" % (self.stripe.creazioni,))
        c = self.stripe.creazioni[0]
        self.assertEqual((c["payment_intent"], c["importo_cents"]), (pi, totale),
                         "IL GATEWAY HA RICEVUTO %r: doveva essere (%s, %s)" % (c, pi, totale))
        self.assertIsNone(
            self.riga(rif),
            "STRIPE HA GIA' IL RIMBORSO E LA RIGA E' IN LISTA: chi la vede premerebbe, e il "
            "freno «gia' rimborsato» sarebbe l'unica cosa fra l'ospite e un doppio rimborso.")

    def test_STRADA_CONTROVERSIA_da_capo_a_fondo_con_la_cifra_dell_ARBITRO(self):
        """«rimborso deciso dall'arbitro»: la cifra la mette una persona, e il pulsante la
        esegue ESATTA. Il resto va all'host da solo; all'ospite torna quanto deciso, ne'
        un centesimo in piu' ne' uno in meno, e la riga esce perche' Stripe lo conferma.

        Fino al 4 settembre 2026 questa riga compariva SENZA pulsante (`manca: date_liberate`:
        il soggiorno c'e' stato) e la cifra andava riscritta a mano su Stripe. Ordine del
        fondatore, «autorizzato» quel giorno: *le cifre le metto io … avere il pulsante da
        cliccare*. Questa guardia e' stata vista ROSSA sul prodotto di prima
        (`corsia_B_2026-09-04\\guardia_rossa_controversia_pulsante_ROSSO_1.log`) e VERDE dopo
        la riga in `_rimborso_dovuto_scheda` che riconosce la controversia risolta."""
        ci, co = self.date(22)
        b, totale = self.prenota(ci, co, "ctr@os.it")
        rif, pi = b["riferimento"], "pi_ctr"
        self.paga(rif, pi)
        s, c = self.g("POST", "/api/garanzia/contesta", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, "PREMESSA NON VALIDA: la contestazione non riesce: %r" % (c,))
        in_garanzia = int((self.sis.garanzia.stato(rif) or {}).get("importo_host_cents") or 0)
        self.assertGreater(in_garanzia, 0, "PREMESSA NON VALIDA: niente in garanzia")
        deciso = in_garanzia // 3 + 7                 # una cifra che nessuna regola produce
        self.assertNotEqual(deciso, totale, "PREMESSA NON VALIDA: coincide col totale")
        s, out = self.g("POST", "/api/admin/controversia/risolvi",
                        {"riferimento": rif, "rimborso_ospite_cents": deciso},
                        {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, "PREMESSA NON VALIDA: l'arbitrato non riesce: %r" % (out,))
        self.assertEqual(int(out.get("rimborso_cliente_cents") or -1), deciso,
                         "la rotta ha registrato una cifra diversa da quella scritta: %r" % (out,))
        self.assertEqual(int(out.get("va_all_host_cents") or -1), in_garanzia - deciso,
                         "all'host non resta il resto al centesimo: %r" % (out,))
        riga = self.riga(rif)
        self.assertIsNotNone(riga, "LA DECISIONE DELL'ARBITRO NON ARRIVA IN LISTA")
        self.assertTrue(riga.get("arbitrato"),
                        "la riga non dice di nascere da un arbitrato: chi guarda il pannello "
                        "non sa che le date occupate sono legittime. Riga: %r" % (riga,))
        self.catena_dal_pulsante("controversia (cifra dell'arbitro)", rif, pi, deciso)

    def test_STRADA_CONTROVERSIA_il_pulsante_NON_c_e_se_la_cifra_in_lista_non_e_quella_decisa(self):
        """⛔ Il freno nuovo si prova nelle DUE direzioni (D20). Il pulsante della controversia
        esiste SOLO perche' la garanzia dice «risolto» con ESATTAMENTE la cifra in lista: se la
        garanzia dice un'altra cifra (qualcuno ha toccato il giornale, o la garanzia), il
        pulsante non deve comparire, e la riga deve dire che mancano le date — come prima."""
        ci, co = self.date(24)
        b, _totale = self.prenota(ci, co, "ctr2@os.it")
        rif, pi = b["riferimento"], "pi_ctr2"
        self.paga(rif, pi)
        s, _c = self.g("POST", "/api/garanzia/contesta", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200)
        in_garanzia = int((self.sis.garanzia.stato(rif) or {}).get("importo_host_cents") or 0)
        deciso = in_garanzia // 4 + 3
        s, out = self.g("POST", "/api/admin/controversia/risolvi",
                        {"riferimento": rif, "rimborso_ospite_cents": deciso},
                        {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, out)
        self.assertTrue(self.riga(rif).get("bottone"), "PREMESSA NON VALIDA: prima il pulsante c'e'")
        # la garanzia non dice piu' quella cifra: e' il caso «qualcosa non torna»
        vero_stato = self.sis.garanzia.stato

        def stato_diverso(prenotazione_id):
            st = vero_stato(prenotazione_id)
            if st and prenotazione_id == rif:
                st = dict(st, ospite_rimborso_cents=int(st["ospite_rimborso_cents"]) + 1)
            return st
        self.sis.garanzia.stato = stato_diverso
        try:
            riga = self.riga(rif)
            self.assertFalse(riga.get("bottone"),
                             "IL PULSANTE C'E' ANCHE SE LA GARANZIA DICE UN'ALTRA CIFRA: il freno "
                             "nuovo non guarda la cifra. Riga: %r" % (riga,))
            self.assertFalse(riga.get("arbitrato"))
            self.assertIn("date_liberate", riga.get("manca") or [])
            s, o = self.premi(rif)
            self.assertEqual(s, 409, "la rotta esegue anche quando il pannello lo vieta: %r" % (o,))
            self.assertEqual(self.stripe.creazioni, [], "I SOLDI SONO PARTITI LO STESSO")
        finally:
            self.sis.garanzia.stato = vero_stato

    def test_STRADA_CONTROVERSIA_il_pulsante_NON_c_e_se_quota_host_piu_rimborso_superano_il_pagato(self):
        """⛔ D16, mai in perdita: se quota dell'host + rimborso all'ospite superassero quanto
        l'ospite ha pagato, la differenza la metteremmo noi. Il freno aritmetico deve fermare
        il pulsante e dirlo (`arbitrato_supera_il_pagato`)."""
        ci, co = self.date(26)
        b, _totale = self.prenota(ci, co, "ctr3@os.it")
        rif, pi = b["riferimento"], "pi_ctr3"
        self.paga(rif, pi)
        s, _c = self.g("POST", "/api/garanzia/contesta", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200)
        in_garanzia = int((self.sis.garanzia.stato(rif) or {}).get("importo_host_cents") or 0)
        deciso = in_garanzia // 2
        s, out = self.g("POST", "/api/admin/controversia/risolvi",
                        {"riferimento": rif, "rimborso_ospite_cents": deciso},
                        {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, out)
        self.assertTrue(self.riga(rif).get("bottone"), "PREMESSA NON VALIDA: prima il pulsante c'e'")
        vero_stato = self.sis.garanzia.stato

        def host_gonfiato(prenotazione_id):
            st = vero_stato(prenotazione_id)
            if st and prenotazione_id == rif:
                st = dict(st, host_riceve_cents=10 ** 9)     # una quota host impossibile
            return st
        self.sis.garanzia.stato = host_gonfiato
        try:
            riga = self.riga(rif)
            self.assertFalse(riga.get("bottone"),
                             "IL PULSANTE C'E' ANCHE SE HOST + OSPITE SUPERANO IL PAGATO: la "
                             "differenza la metteremmo noi. Riga: %r" % (riga,))
            self.assertIn("arbitrato_supera_il_pagato", riga.get("manca") or [])
            s, o = self.premi(rif)
            self.assertEqual(s, 409, "%r" % (o,))
            self.assertEqual(self.stripe.creazioni, [], "I SOLDI SONO PARTITI LO STESSO")
        finally:
            self.sis.garanzia.stato = vero_stato


if __name__ == "__main__":
    unittest.main(verbosity=2)
