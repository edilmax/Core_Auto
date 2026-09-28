"""IL BLOCCO SULLA CARTA (autorizzazione senza incasso), 7 giorni -- le guardie, scritte PRIMA.

PERCHE' (consegne 19, RIPRENDI_QUI.md). Stripe NON restituisce la sua commissione sui rimborsi
(docs.stripe.com/refunds), e per l'art. 6-ter del contratto la paga la PIATTAFORMA su ogni
rimborso pieno: le 48 ore di ripensamento, la cancellazione gratuita. Un pagamento ANNULLATO
prima dell'incasso invece non costa niente: misurato il 28/9 su Stripe di prova -- blocco
`requires_capture`, nessun movimento di saldo; annullo `canceled`, zero movimenti; incasso
`succeeded` con la sua commissione (collaudi: vedi REGISTRO_INGEGNERIA.md, voce del blocco).

LE REGOLE CHE QUESTE GUARDIE PRETENDONO:
  1. un pagamento BLOCCATO (sessione `unpaid`, PaymentIntent `requires_capture`, riletti
     dall'API) CONFERMA la prenotazione -- il pagamento e' garantito -- ma NON scrive incassi:
     il giornale racconta i soldi che Stripe ha davvero, e bloccati non li ha ancora;
  2. la cancellazione nelle 48 ore ANNULLA il blocco: nessun rimborso, nessuna riga «rimborso»;
  3. a fine finestra il giro orario INCASSA, e solo allora nascono incasso, commissione,
     tassa e payout maturato; dentro la finestra non incassa;
  4. un incasso fallito GRIDA (ERROR, che il Guardiano legge) e non inventa niente;
  5. un bonifico all'host NON parte su un pagamento non incassato;
  6. un blocco rimasto su una prenotazione chiusa lo annulla il giro orario;
  7. se la rilettura del pagamento non riesce, non si conferma e si fa ritentare Stripe;
  8. il pagamento normale (incassato subito) resta com'era.

⛔ D20: queste guardie vanno VISTE ROSSE sul codice di prima, poi si ripara.
Stripe finto al bordo (`sis.stripe`), rotte vere, webhook firmato.
"""
import hashlib
import hmac
import json
import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import SECONDI_RIPENSAMENTO, crea_router

SEG = b"b" * 32
HK = {"X-Host-Key": "hk"}
AK = {"X-Admin-Key": "ak"}
WHSEC = "whsec_blocco"
# ⛔ VALORE FINTO IN UNA COSTANTE, non scritto sul posto: `bandit` (B106) segnala un argomento
# il cui NOME contiene «secret»/«key» quando riceve un valore letterale (stesso rimedio di
# test_webhook_evento_archiviato: un rilievo NUOVO si chiude nel codice).
CHIAVE_FINTA = "sk_test_blocco"


class StripeColBlocco:
    """Stripe finto al bordo, con il blocco sulla carta.
    `sessioni` : cs -> (payment_status, pi)   cio' che l'API dice della sessione
    `pagamenti`: pi -> stato del PaymentIntent (requires_capture, succeeded, canceled)
    Una sessione o un pagamento assenti = «rilettura non riuscita»."""

    def __init__(self):
        self.sessioni = {}
        self.pagamenti = {}
        self.importi = {}
        self.incassi = []
        self.annulli = []
        self.rimborsi = []
        self.esito_incasso = None
        self.esito_annullo = None

    def stato_sessione(self, cs):
        return self.sessioni.get(cs, ("", ""))[0]

    def pagamento_della_sessione(self, cs):
        if cs not in self.sessioni:
            return {"ok": False, "pi": "", "stato": "", "incassabile_cents": 0,
                    "motivo": "rete"}
        pi = self.sessioni[cs][1]
        if pi not in self.pagamenti:
            return {"ok": False, "pi": "", "stato": "", "incassabile_cents": 0,
                    "motivo": "rete"}
        return {"ok": True, "pi": pi, "stato": self.pagamenti[pi],
                "incassabile_cents": self.importi.get(pi, 0), "motivo": ""}

    def stato_pagamento(self, pi):
        if pi not in self.pagamenti:
            return {"ok": False, "stato": "", "motivo": "rete"}
        return {"ok": True, "stato": self.pagamenti[pi], "motivo": ""}

    def incassa(self, pi, chiave):
        self.incassi.append((pi, chiave))
        if self.esito_incasso is not None:
            return self.esito_incasso
        if self.pagamenti.get(pi) == "requires_capture":
            self.pagamenti[pi] = "succeeded"
            return {"ok": True, "id": pi, "motivo": "succeeded"}
        return {"ok": False, "id": "", "motivo": "payment_intent_unexpected_state"}

    def annulla(self, pi, chiave):
        self.annulli.append((pi, chiave))
        if self.esito_annullo is not None:
            return self.esito_annullo
        if self.pagamenti.get(pi) == "requires_capture":
            self.pagamenti[pi] = "canceled"
            return {"ok": True, "id": pi, "motivo": "canceled"}
        return {"ok": False, "id": "", "motivo": "payment_intent_unexpected_state"}

    def impronta_carta(self, pi):
        return ""

    def rimborsa(self, pi, importo, chiave):
        self.rimborsi.append((pi, importo, chiave))
        return {"ok": True, "id": "re_finto", "motivo": "succeeded"}

    def rimborsi_di(self, pi):
        return {"ok": True, "rimborsi": [], "rimborsato_cents": 0, "motivo": ""}


class ConnectFinto:
    def __init__(self):
        self.bonifici = []

    def trasferisci(self, acct, importo, valuta, rif):
        self.bonifici.append((acct, importo, valuta, rif))
        return "tr_finto_%d" % len(self.bonifici)


class _Base(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db",
            db_domanda=f"{d}/dom.db", db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db",
            db_payout=f"{d}/pay.db", db_tassa_comunale=f"{d}/tc.db",
            db_eventi_stripe=f"{d}/evt.db", db_finanza=f"{d}/fin.db",
            file_referral=f"{d}/ref.json", commissione_bps=1500, psp_bps=500,
            stripe_webhook_secret=WHSEC))
        self.sis.concierge._link = lambda dati: "https://pay/" + str(dati.get("riferimento", ""))
        self.stripe = StripeColBlocco()
        self.sis.stripe = self.stripe
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "casa", "titolo": "C",
               "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
               "servizi": [], "immagini": [], "tassa_pp_notte_cents": 200,
               "politica_cancellazione": "non_rimborsabile"}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa", "da": "2027-04-01",
               "a": "2027-05-31", "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def prenota(self, ci, co):
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book", {"quote_token": q["quote_token"],
                                                      "email": "o@x.it"})
        return b["riferimento"], b.get("voucher_token", ""), int(q["totale_cents"])

    def evento(self, evt_id, tipo, rif, cs, pi):
        payload = json.dumps({"id": evt_id, "type": tipo,
                              "data": {"object": {"id": cs, "payment_intent": pi,
                                                  "payment_status": "paid",
                                                  "metadata": {"riferimento": rif}}}})
        ts = str(int(time.time()))
        mac = hmac.new(WHSEC.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
        return self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})

    def paga_bloccato(self, rif, totale, n=1):
        cs, pi = "cs_blocco%d" % n, "pi_blocco%d" % n
        self.stripe.sessioni[cs] = ("unpaid", pi)
        self.stripe.pagamenti[pi] = "requires_capture"
        self.stripe.importi[pi] = totale
        s, c = self.evento("evt_blocco%d" % n, "checkout.session.completed", rif, cs, pi)
        return s, c, pi

    def stato(self, rif):
        return self.sis.pagamenti_pendenti.info(rif)["stato"]

    def movimenti(self, rif, tipo):
        return [m for m in self.sis.finanza.movimenti(rif) if m.get("tipo") == tipo]

    def corpo(self, rif):
        return json.loads(self.sis.pagamenti_pendenti.info(rif).get("corpo_json") or "{}")

    def payout(self, rif):
        return self.sis.payout.stato_di(rif)


class TestIlPagamentoBloccatoConferma(_Base):

    def test_IL_BLOCCO_CONFERMA_LA_PRENOTAZIONE_MA_NON_SCRIVE_INCASSI(self):
        rif, _vt, tot = self.prenota("2027-04-10", "2027-04-12")
        s, c, pi = self.paga_bloccato(rif, tot)
        self.assertEqual(s, 200, "%r" % (c,))
        self.assertEqual(self.stato(rif), "pagato",
                         "UN PAGAMENTO BLOCCATO NON CONFERMA LA PRENOTAZIONE: Stripe dice che i "
                         "soldi sono garantiti (requires_capture) e noi lasciamo scadere la stanza")
        self.assertEqual(self.movimenti(rif, "incasso"), [],
                         "il giornale scrive un INCASSO che Stripe non ha ancora fatto: %r"
                         % (self.movimenti(rif, "incasso"),))
        self.assertEqual(self.movimenti(rif, "commissione"), [])
        self.assertNotEqual(self.payout(rif), "maturato",
                            "payout MATURATO su soldi non incassati")
        self.assertEqual(self.corpo(rif).get("blocco_pi"), pi,
                         "il blocco non e' scritto sulla prenotazione: nessuno sapra' di incassarlo")
        self.assertGreater(int(self.corpo(rif).get("blocco_incassa_dal_ts") or 0), int(time.time()),
                           "la fine della finestra dev'essere nel futuro (48 ore)")

    def test_IL_WEBHOOK_RIPETUTO_NON_INCASSA_NEL_GIORNALE(self):
        """Lo stesso pagamento annunciato di nuovo (un secondo evento dello stesso pagamento):
        la prenotazione e' gia' 'pagato', e la riasserzione dei passi derivati NON deve
        scrivere un incasso che Stripe non ha fatto."""
        rif, _vt, tot = self.prenota("2027-04-10", "2027-04-12")
        self.paga_bloccato(rif, tot)
        self.assertEqual(self.stato(rif), "pagato", "PREMESSA: il blocco ha confermato")
        s, c = self.evento("evt_ripetuto", "checkout.session.async_payment_succeeded", rif,
                           "cs_blocco1", "pi_blocco1")
        self.assertTrue(200 <= s < 300, "%r %r" % (s, c))
        self.assertEqual(self.movimenti(rif, "incasso"), [],
                         "la ripetizione del webhook ha scritto l'incasso di un pagamento bloccato")

    def test_RILETTURA_DEL_PAGAMENTO_FALLITA_NON_CONFERMA_E_FA_RITENTARE(self):
        rif, _vt, _tot = self.prenota("2027-04-14", "2027-04-16")
        self.stripe.sessioni["cs_giu"] = ("unpaid", "pi_giu")      # pi_giu NON risponde
        s, c = self.evento("evt_giu", "checkout.session.completed", rif, "cs_giu", "pi_giu")
        self.assertFalse(200 <= s < 300,
                         "rilettura del pagamento fallita e risposta 2xx: Stripe non ritentera' "
                         "mai piu', e un pagamento forse bloccato resta senza prenotazione (%r %r)"
                         % (s, c))
        self.assertNotEqual(self.stato(rif), "pagato")

    def test_SESSIONE_UNPAID_SENZA_BLOCCO_RESTA_IN_ATTESA(self):
        """Pix: sessione chiusa, soldi non ancora arrivati, pagamento NON bloccato: resta in
        attesa come prima (tace a macchina sana, ferrea 10)."""
        rif, _vt, _tot = self.prenota("2027-04-18", "2027-04-20")
        self.stripe.sessioni["cs_pix"] = ("unpaid", "pi_pix")
        self.stripe.pagamenti["pi_pix"] = "processing"
        s, c = self.evento("evt_pix", "checkout.session.completed", rif, "cs_pix", "pi_pix")
        self.assertEqual(s, 200, "%r" % (c,))
        self.assertNotEqual(self.stato(rif), "pagato")
        self.assertEqual(self.stripe.incassi, [])

    def test_IL_PAGAMENTO_NORMALE_RESTA_COM_ERA(self):
        rif, _vt, tot = self.prenota("2027-04-22", "2027-04-24")
        self.stripe.sessioni["cs_carta"] = ("paid", "pi_carta")
        self.stripe.pagamenti["pi_carta"] = "succeeded"
        s, c = self.evento("evt_carta", "checkout.session.completed", rif, "cs_carta", "pi_carta")
        self.assertEqual(s, 200, "%r" % (c,))
        self.assertEqual(self.stato(rif), "pagato")
        self.assertEqual([m["importo_cents"] for m in self.movimenti(rif, "incasso")], [tot])
        self.assertEqual(self.payout(rif), "maturato")
        self.assertNotIn("blocco_pi", self.corpo(rif))
        self.assertEqual((self.stripe.incassi, self.stripe.annulli), ([], []))


class TestLaCancellazioneNelleQuarantottoOreAnnulla(_Base):

    def test_L_OSPITE_CHE_CANCELLA_NELLE_48_ORE_VIENE_ANNULLATO_NON_RIMBORSATO(self):
        rif, vt, tot = self.prenota("2027-04-10", "2027-04-12")
        _s, _c, pi = self.paga_bloccato(rif, tot)
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
        self.assertEqual(s, 200, "%r" % (c,))
        self.assertEqual([p for p, _k in self.stripe.annulli], [pi],
                         "LA CANCELLAZIONE NELLE 48 ORE NON ANNULLA IL BLOCCO: i soldi restano "
                         "fermi sulla carta dell'ospite, e prima o poi qualcuno li incassa")
        self.assertEqual(self.stripe.rimborsi, [], "un rimborso su un pagamento mai incassato")
        self.assertEqual(self.movimenti(rif, "rimborso"), [],
                         "RIGA DI RIMBORSO per soldi mai incassati: la lista dei rimborsi dovuti "
                         "mostrerebbe un pulsante che Stripe rifiuta")
        _s, lista = self.g("GET", "/api/admin/rimborsi_dovuti", None, AK)
        self.assertNotIn(rif, [x.get("riferimento") for x in lista.get("rimborsi", [])])
        self.assertEqual(self.corpo(rif).get("blocco_pi"), pi)
        self.assertTrue(self.corpo(rif).get("blocco_annullato_ts"),
                        "l'annullo non e' scritto: il giro orario lo rifarebbe per sempre")
        # il prospetto per il commercialista: il costo di Stripe su un annullo e' NOTO, ed e' zero
        prospetto = self.sis.pagamenti_pendenti.aggrega_costi_tecnici()
        self.assertEqual(prospetto["costo_stripe_sconosciuto"]["conteggio"], 0,
                         "un annullo sulla carta finisce fra i costi Stripe «NON DETERMINATI»: il "
                         "commercialista cercherebbe un dato che c'e' gia' (zero)")
        self.assertEqual((prospetto["costo_stripe_irrecuperabile"]["conteggio"],
                          prospetto["costo_stripe_irrecuperabile"]["cents"]), (1, 0))

    def test_L_HOST_CHE_CANCELLA_UN_BLOCCO_LO_ANNULLA(self):
        rif, _vt, tot = self.prenota("2027-04-10", "2027-04-12")
        _s, _c, pi = self.paga_bloccato(rif, tot)
        s, c = self.g("POST", "/api/host/cancella", {"riferimento": rif, "host_id": "demo"}, HK)
        self.assertEqual(s, 200, "%r" % (c,))
        self.assertEqual([p for p, _k in self.stripe.annulli], [pi])
        self.assertEqual(self.movimenti(rif, "rimborso"), [])
        self.assertEqual(self.stripe.rimborsi, [])

    def test_UN_ANNULLO_FALLITO_LO_RIFA_IL_GIRO_ORARIO(self):
        rif, vt, tot = self.prenota("2027-04-10", "2027-04-12")
        _s, _c, pi = self.paga_bloccato(rif, tot)
        self.stripe.esito_annullo = {"ok": False, "id": "", "motivo": "URLError: rete"}
        self.stripe.pagamenti.pop(pi)                   # e nemmeno la rilettura risponde
        self.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
        self.assertEqual(self.movimenti(rif, "rimborso"), [],
                         "annullo fallito NON vuol dire incassato: nessuna riga di rimborso")
        self.assertFalse(self.corpo(rif).get("blocco_annullato_ts"))
        # torna la rete: il giro orario annulla il blocco rimasto sulla prenotazione chiusa
        self.stripe.esito_annullo = None
        self.stripe.pagamenti[pi] = "requires_capture"
        self.r._incassa_blocchi(ora_ts=int(time.time()) + 3600)
        self.assertEqual([p for p, _k in self.stripe.annulli], [pi, pi])
        self.assertEqual(self.stripe.incassi, [],
                         "IL GIRO HA INCASSATO UNA PRENOTAZIONE CANCELLATA")
        self.assertTrue(self.corpo(rif).get("blocco_annullato_ts"))

    def test_PAGAMENTO_BLOCCATO_SU_PRENOTAZIONE_GIA_CANCELLATA_SI_ANNULLA(self):
        """L'ospite cancella PRIMA di pagare, poi paga sul link ancora aperto: la prenotazione
        non e' confermabile. Col blocco i soldi non sono mai entrati: si annulla, e nessuna
        riga di rimborso."""
        rif, vt, tot = self.prenota("2027-04-10", "2027-04-12")
        self.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
        _s, _c, pi = self.paga_bloccato(rif, tot)
        self.assertNotEqual(self.stato(rif), "pagato")
        self.assertEqual([p for p, _k in self.stripe.annulli], [pi])
        self.assertEqual(self.movimenti(rif, "rimborso"), [])


class TestAFineFinestraSiIncassa(_Base):

    def _bloccata(self):
        rif, vt, tot = self.prenota("2027-04-10", "2027-04-12")
        _s, _c, pi = self.paga_bloccato(rif, tot)
        return rif, vt, tot, pi

    def test_DENTRO_LA_FINESTRA_NON_SI_INCASSA(self):
        rif, _vt, _tot, _pi = self._bloccata()
        self.r._incassa_blocchi(ora_ts=int(time.time()) + SECONDI_RIPENSAMENTO - 3600)
        self.assertEqual(self.stripe.incassi, [],
                         "INCASSATO DENTRO LE 48 ORE: l'ospite che cancella dopo paga la "
                         "commissione di Stripe")
        self.assertEqual(self.movimenti(rif, "incasso"), [])

    def test_A_FINE_FINESTRA_SI_INCASSA_E_NASCONO_I_CONTI(self):
        rif, _vt, tot, pi = self._bloccata()
        self.r._incassa_blocchi(ora_ts=int(time.time()) + SECONDI_RIPENSAMENTO + 60)
        self.assertEqual(self.stripe.incassi, [(pi, "incasso:" + rif)],
                         "A FINE FINESTRA NON SI INCASSA: dopo 7 giorni l'autorizzazione scade e "
                         "la prenotazione resta senza soldi")
        self.assertEqual([m["importo_cents"] for m in self.movimenti(rif, "incasso")], [tot])
        self.assertEqual(len(self.movimenti(rif, "commissione")), 1)
        self.assertEqual(self.payout(rif), "maturato")
        self.assertTrue(self.corpo(rif).get("blocco_incassato_ts"))
        # il giro dopo non incassa due volte
        self.r._incassa_blocchi(ora_ts=int(time.time()) + SECONDI_RIPENSAMENTO + 7200)
        self.assertEqual(len(self.stripe.incassi), 1)
        self.assertEqual(len(self.movimenti(rif, "incasso")), 1)

    def test_UN_INCASSO_FALLITO_GRIDA_E_NON_INVENTA_NIENTE(self):
        rif, _vt, _tot, _pi = self._bloccata()
        self.stripe.esito_incasso = {"ok": False, "id": "", "motivo": "card_declined"}
        with self.assertLogs("core_auto.server", level="ERROR") as reg:
            self.r._incassa_blocchi(ora_ts=int(time.time()) + SECONDI_RIPENSAMENTO + 60)
        self.assertTrue(any("INCASSO" in r.getMessage() and rif[:8] in r.getMessage()
                            for r in reg.records),
                        "l'incasso fallito non ha gridato col riferimento: %r"
                        % [r.getMessage() for r in reg.records])
        self.assertEqual(self.movimenti(rif, "incasso"), [])
        self.assertFalse(self.corpo(rif).get("blocco_incassato_ts"))

    def test_UN_INCASSO_GIA_FATTO_SU_STRIPE_SI_RICONOSCE(self):
        """Il primo giro ha incassato e poi e' morto prima di scriverlo: Stripe risponde «gia'
        incassato». Si rilegge il pagamento: `succeeded` vuol dire incassato davvero."""
        rif, _vt, tot, pi = self._bloccata()
        self.stripe.pagamenti[pi] = "succeeded"
        self.r._incassa_blocchi(ora_ts=int(time.time()) + SECONDI_RIPENSAMENTO + 60)
        self.assertEqual([m["importo_cents"] for m in self.movimenti(rif, "incasso")], [tot])
        self.assertTrue(self.corpo(rif).get("blocco_incassato_ts"))


class TestIlBonificoAspettaLIncasso(_Base):

    def setUp(self):
        super().setUp()
        self.connect = ConnectFinto()
        self.sis.connect = self.connect
        self.sis.registro_host.info_host = lambda h: {"stripe_account_id": "acct_finto"}

    def test_NESSUN_BONIFICO_SU_UN_PAGAMENTO_NON_INCASSATO(self):
        rif, _vt, tot = self.prenota("2027-04-10", "2027-04-12")
        self.paga_bloccato(rif, tot)
        self.assertEqual(self.stato(rif), "pagato", "PREMESSA: il blocco ha confermato")
        self.r._trasferisci_all_host(rif, 5000)
        self.assertEqual(self.connect.bonifici, [],
                         "BONIFICO ALL'HOST SU SOLDI MAI INCASSATI: se l'autorizzazione scade li "
                         "paghiamo noi")

    def test_DOPO_L_INCASSO_IL_BONIFICO_PARTE(self):
        """L'altra direzione (ferrea 10): la guardia non ferma i bonifici veri."""
        rif, _vt, tot = self.prenota("2027-04-10", "2027-04-12")
        self.paga_bloccato(rif, tot)
        self.r._incassa_blocchi(ora_ts=int(time.time()) + SECONDI_RIPENSAMENTO + 60)
        self.r._trasferisci_all_host(rif, 5000)
        self.assertEqual(len(self.connect.bonifici), 1, "%r" % (self.connect.bonifici,))


class TestLaRevisioneDiGML(_Base):
    """I tre rilievi VERI della revisione indipendente di GML 5.5 Flash sulla #231 (28/9 sera,
    file di coordinamento sul Desktop), controllati sul codice prima di scrivere queste guardie."""

    def test_UN_BLOCCO_GIA_ANNULLATO_NON_GRIDA_PAGATA_SU_UNA_PRENOTAZIONE_CANCELLATA(self):
        """Il giro orario legge l'elenco dei blocchi, e un istante dopo l'ospite cancella e
        annulla: il giro, con la fotografia vecchia, prova a incassare, Stripe dice «annullato».
        Gridare «la prenotazione risulta PAGATA» su una prenotazione CANCELLATA e' un falso
        allarme (ferrea 10): si rilegge lo stato, e si grida solo se e' davvero 'pagato'."""
        rif, vt, tot = self.prenota("2027-04-10", "2027-04-12")
        _s, _c, pi = self.paga_bloccato(rif, tot)
        self.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
        self.assertEqual(self.stripe.pagamenti[pi], "canceled", "PREMESSA: annullato")
        with self.assertLogs("core_auto.server", level="INFO") as reg:
            self.r._incassa_blocco(rif, pi)           # il giro con la fotografia vecchia
        errori = [r.getMessage() for r in reg.records if r.levelname == "ERROR"]
        self.assertEqual(errori, [], "FALSO ALLARME su una prenotazione cancellata: %r" % errori)

    def test_LA_PENALE_NON_INCASSATA_GRIDA_COME_TALE(self):
        """L'ospite cancella dopo le 48 ore (politica non rimborsabile: c'e' una penale da
        trattenere) mentre il blocco e' ancora aperto, e l'incasso non riesce. Il giro orario, su
        una prenotazione chiusa, ANNULLA: la penale non entra mai. Il registro non puo' promettere
        «si ritenta»: deve dire che la penale e' persa, col riferimento."""
        from unittest import mock
        rif, vt, tot = self.prenota("2027-04-10", "2027-04-12")
        self.paga_bloccato(rif, tot)
        self.stripe.esito_incasso = {"ok": False, "id": "", "motivo": "URLError: rete"}
        dopo = time.time() + SECONDI_RIPENSAMENTO + 3600
        with mock.patch("time.time", return_value=dopo), \
                self.assertLogs("core_auto.server", level="ERROR") as reg:
            self.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
        testi = [r.getMessage() for r in reg.records]
        self.assertTrue(any("penale_non_incassata" in t and rif[:8] in t for t in testi),
                        "LA PENALE EVAPORA IN SILENZIO: nessun ERROR 'penale_non_incassata' "
                        "col riferimento: %r" % testi)

    def test_SE_IL_BLOCCO_NON_SI_SCRIVE_SI_RISPONDE_503_E_NON_SI_CONFERMA(self):
        """Il ramo difensivo che nessuno eseguiva (D19): la scrittura del blocco fallisce. Senza
        il blocco scritto, la conferma scriverebbe un incasso che Stripe non ha fatto: quindi 503
        (Stripe ritenta, lo sweeper degli eventi pure), prenotazione non confermata, evento non
        segnato come elaborato."""
        rif, _vt, tot = self.prenota("2027-04-10", "2027-04-12")
        self.sis.pagamenti_pendenti.segna_blocco = lambda *a, **k: False
        s, c, _pi = self.paga_bloccato(rif, tot)
        self.assertEqual((s, c.get("sottocodice")), (503, "blocco_non_segnato"), "%r %r" % (s, c))
        self.assertNotEqual(self.stato(rif), "pagato")
        self.assertEqual(self.movimenti(rif, "incasso"), [])
        self.assertFalse(self.sis.eventi_stripe.elaborato("evt_blocco1"))


class TestIlLinkVeroChiedeIlBlocco(unittest.TestCase):
    """CABLAGGIO, anello per anello (collaudo 2): dal preventivo al CORPO della sessione di
    Checkout, col fornitore VERO (fase85, montato dal bootstrap come in produzione) e solo la
    rete finta. Il blocco deve arrivare a Stripe sia dalla prenotazione immediata (il link lo
    crea fase59) sia dall'approvazione di una richiesta (il link lo rigenera fase83). Date
    RELATIVE a oggi: una data scritta a mano diventa una bomba a tempo."""

    def setUp(self):
        import datetime
        import fase85_pagamenti_stripe as f85
        self._f85 = f85
        self._orig = f85.ProviderStripe._fetch_reale
        self.corpi = []

        def finta(url, body, headers):
            if not body and "/checkout/sessions/" in url:
                return {"id": url.rsplit("/", 1)[-1], "payment_status": "paid"}
            self.corpi.append(body.decode("utf-8") if body else "")
            return {"url": "https://checkout.stripe.test/%d" % len(self.corpi),
                    "id": "cs_test_%d" % len(self.corpi)}
        f85.ProviderStripe._fetch_reale = staticmethod(finta)
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db", db_pendenti=f"{d}/p.db",
            db_payout=f"{d}/pay.db", db_garanzia=f"{d}/g.db", commissione_bps=1000,
            psp_bps=500, stripe_secret_key=CHIAVE_FINTA, stripe_webhook_secret=WHSEC,
            stripe_success_url="https://bookinvip.com/grazie.html",
            stripe_cancel_url="https://bookinvip.com/annullato.html"))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")
        oggi = datetime.datetime.now(datetime.timezone.utc).date()
        self.giorno = lambda n: (oggi + datetime.timedelta(days=n)).isoformat()
        for slug, modo in (("subito", "immediata"), ("richiesta", "su_richiesta")):
            s, c = self.g("POST", "/api/host/pubblica", {
                "host_id": "demo", "slug": slug, "titolo": slug, "citta": "Roma",
                "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
                "servizi": [], "immagini": [], "modalita_prenotazione": modo}, HK)
            self.assertIn(s, (200, 201), c)
            s, c = self.g("POST", "/api/host/disponibilita_range", {
                "alloggio_id": slug, "da": self.giorno(0), "a": self.giorno(40),
                "unita_totali": 3, "prezzo_netto_cents": 10000}, HK)
            self.assertEqual(s, 200, c)

    def tearDown(self):
        self._f85.ProviderStripe._fetch_reale = self._orig
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def prenota(self, slug, arrivo):
        s, q = self.g("POST", "/api/concierge/quote", {
            "alloggio_id": slug, "check_in": self.giorno(arrivo),
            "check_out": self.giorno(arrivo + 2), "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book", {"quote_token": q["quote_token"],
                                                      "email": "o@x.it"})
        self.assertEqual(s, 201, b)
        return b

    MANUALE = "payment_method_options%5Bcard%5D%5Bcapture_method%5D=manual"

    def test_la_prenotazione_immediata_lontana_chiede_il_blocco_e_la_vicina_no(self):
        self.prenota("subito", 20)
        self.assertIn(self.MANUALE, self.corpi[-1],
                      "il link della prenotazione immediata NON chiede il blocco: fase59 non "
                      "passa l'arrivo a fase85, o fase85 non lo usa")
        self.prenota("subito", 2)
        self.assertNotIn("capture_method", self.corpi[-1],
                         "blocco su un arrivo vicino: dentro la finestra il diritto alle 48 ore "
                         "non c'e', e il blocco si chiuderebbe con un incasso parziale")

    def test_l_approvazione_di_una_richiesta_lontana_chiede_il_blocco(self):
        b = self.prenota("richiesta", 20)
        self.assertEqual(b.get("stato"), "in_attesa_host", b)
        n = len(self.corpi)
        s, c = self.g("POST", "/api/host/richieste/approva",
                      {"riferimento": b["riferimento"], "host_id": "demo"}, HK)
        self.assertEqual(s, 200, c)
        self.assertEqual(len(self.corpi), n + 1, "l'approvazione non ha creato il link nuovo")
        self.assertIn(self.MANUALE, self.corpi[-1],
                      "IL LINK DELL'APPROVAZIONE NON CHIEDE IL BLOCCO: rigenerato senza la data "
                      "d'arrivo, le richieste approvate si incassano subito e l'annullo nelle 48 "
                      "ore diventa un rimborso con la commissione persa")


class TestISorveglientiConosconoIlBlocco(unittest.TestCase):
    """Chi sorveglia i conti non deve gridare su un pagamento BLOCCATO dentro la sua finestra
    (un falso allarme insegna a ignorare, ferrea 10) -- e deve gridare quando il blocco NON e'
    stato incassato in tempo, o e' scaduto su una prenotazione che risulta pagata."""

    def test_I2_non_grida_dentro_la_finestra_e_grida_oltre(self):
        from fase202_invarianti_archivi import GRAZIA_INCASSO_BLOCCO_SEC, _giudica_i2
        ora = 1_900_000_000
        oltre = ora - GRAZIA_INCASSO_BLOCCO_SEC - 60

        def p(rif, **corpo):
            return {"rif": rif, "stato": "pagato",
                    "corpo_json": json.dumps(dict({"totale_cents": 5000}, **corpo))}
        prenotazioni = [
            p("DENTRO", blocco_pi="pi_a", blocco_incassa_dal_ts=ora + 100),
            p("APPENA_FINITA", blocco_pi="pi_e", blocco_incassa_dal_ts=ora - 60),
            p("OLTRE", blocco_pi="pi_b", blocco_incassa_dal_ts=oltre),
            p("SCADUTO", blocco_pi="pi_c", blocco_incassa_dal_ts=ora + 100,
              blocco_annullato_ts=ora - 10),
            p("INCASSATO", blocco_pi="pi_d", blocco_incassa_dal_ts=oltre,
              blocco_incassato_ts=ora - 3600),
            p("NORMALE"),
        ]
        giornale = [{"tipo": "incasso", "riferimento": "INCASSATO", "importo_cents": 5000},
                    {"tipo": "incasso", "riferimento": "NORMALE", "importo_cents": 5000}]
        viol, _note = _giudica_i2(prenotazioni, giornale, ora_ts=ora)
        self.assertEqual(sorted(v[0] for v in viol), ["OLTRE", "SCADUTO"],
                         "I2 deve tacere sul blocco dentro la finestra (e nella grazia) e gridare "
                         "su quello non incassato in tempo o scaduto: %r" % (viol,))
        self.assertGreaterEqual(GRAZIA_INCASSO_BLOCCO_SEC, 3 * 3600,
                                "il giro gira ogni ora: una grazia piu' corta di qualche giro "
                                "griderebbe su un ritardo normale")

    def test_la_riconciliazione_conta_le_sessioni_incassate_dopo_il_blocco(self):
        from fase182_riconciliazione import stripe_sessioni_pagate
        chiamate = []

        def fetch(percorso, params, chiave):
            chiamate.append((percorso, dict(params)))
            return {"has_more": False, "data": [
                {"id": "cs_a", "payment_status": "paid", "amount_total": 1000,
                 "currency": "eur", "metadata": {"riferimento": "A"}},
                {"id": "cs_b", "payment_status": "unpaid", "amount_total": 2000,
                 "currency": "eur", "metadata": {"riferimento": "B"},
                 "payment_intent": {"id": "pi_b", "status": "succeeded"}},
                {"id": "cs_c", "payment_status": "unpaid", "amount_total": 3000,
                 "currency": "eur", "metadata": {"riferimento": "C"},
                 "payment_intent": {"id": "pi_c", "status": "requires_capture"}},
                {"id": "cs_d", "payment_status": "unpaid", "amount_total": 4000,
                 "currency": "eur", "metadata": {"riferimento": "D"},
                 "payment_intent": "pi_d"}]}
        out = stripe_sessioni_pagate("sk_test_x", 0, fetch=fetch)
        self.assertEqual([(s["riferimento"], s["cents"]) for s in out], [("A", 1000), ("B", 2000)],
                         "una sessione chiusa col blocco e poi INCASSATA e' un incasso vero; "
                         "una ancora bloccata no")
        self.assertEqual(chiamate[0][1].get("expand[]"), "data.payment_intent",
                         "senza espandere il pagamento la sessione incassata dopo non si vede")

    def test_la_scheda_contabile_non_segna_rosso_un_blocco_in_corso(self):
        from fase181_audit_console import _semaforo_coerenza, _semaforo_stripe
        unpaid = lambda cs: {"ok": True, "payment_status": "unpaid"}      # noqa: E731
        bloccata = {"stato": "pagato", "corpo_json": json.dumps(
            {"stripe_cs": "cs_x", "blocco_pi": "pi_x", "blocco_incassa_dal_ts": 1})}
        self.assertEqual(_semaforo_coerenza(bloccata, None, [])["colore"], "verde")
        self.assertEqual(_semaforo_stripe(bloccata, unpaid)["colore"], "verde")
        # l'altra direzione: senza blocco, «pagato» senza incasso resta un rosso vero
        senza = {"stato": "pagato", "corpo_json": json.dumps({"stripe_cs": "cs_x"})}
        self.assertEqual(_semaforo_coerenza(senza, None, [])["colore"], "rosso")
        self.assertEqual(_semaforo_stripe(senza, unpaid)["colore"], "rosso")
        # e un blocco SCADUTO su una prenotazione che risulta pagata e' un rosso
        scaduto = {"stato": "pagato", "corpo_json": json.dumps(
            {"stripe_cs": "cs_x", "blocco_pi": "pi_x", "blocco_annullato_ts": 5})}
        self.assertEqual(_semaforo_coerenza(scaduto, None, [])["colore"], "rosso")
        self.assertEqual(_semaforo_stripe(scaduto, unpaid)["colore"], "rosso")
        # una cancellazione col blocco ANNULLATO non ha riga di rimborso, ed e' giusto
        annullata = {"stato": "rimborsato", "corpo_json": json.dumps(
            {"stripe_cs": "cs_x", "blocco_pi": "pi_x", "blocco_annullato_ts": 5})}
        self.assertEqual(_semaforo_coerenza(annullata, None, [])["colore"], "verde")
        rimborsata = {"stato": "rimborsato", "corpo_json": json.dumps({"stripe_cs": "cs_x"})}
        self.assertEqual(_semaforo_coerenza(rimborsata, None, [])["colore"], "rosso",
                         "senza blocco, «rimborsato» senza riga di rimborso resta un rosso vero")


if __name__ == "__main__":
    unittest.main()
