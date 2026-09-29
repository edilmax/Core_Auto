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

    def test_I2_all_ultimo_secondo_della_grazia_tace_e_a_quello_dopo_grida(self):
        """Il confine della grazia e' COMPRESO: sopravviveva il `<=` diventato `<` (Giudice sul
        diff del blocco, 2026-09-29, fase202:293)."""
        from fase202_invarianti_archivi import GRAZIA_INCASSO_BLOCCO_SEC, _giudica_i2
        fine = 1_900_000_000
        pren = [{"rif": "CONFINE", "stato": "pagato", "corpo_json": json.dumps(
            {"totale_cents": 5000, "blocco_pi": "pi_c", "blocco_incassa_dal_ts": fine})}]
        viol, _ = _giudica_i2(pren, [], ora_ts=fine + GRAZIA_INCASSO_BLOCCO_SEC)
        self.assertEqual(viol, [], "all'ultimo secondo della grazia il blocco e' ancora in regola")
        viol, _ = _giudica_i2(pren, [], ora_ts=fine + GRAZIA_INCASSO_BLOCCO_SEC + 1)
        self.assertEqual([v[0] for v in viol], ["CONFINE"],
                         "un secondo dopo la grazia il blocco non incassato e' un incasso mancato")

    def test_I2_senza_un_istante_valido_usa_l_orologio_vero(self):
        """`ora_ts` assente o booleano non e' un istante: vale l'orologio vero. Sopravviveva
        l'`and` diventato `or` (fase202:269): con None il confronto esplodeva, con True l'istante
        diventava 1 e un blocco scaduto da anni restava «autorizzato» per sempre."""
        from fase202_invarianti_archivi import _giudica_i2
        adesso = int(time.time())

        def p(rif, fine):
            return {"rif": rif, "stato": "pagato", "corpo_json": json.dumps(
                {"totale_cents": 5000, "blocco_pi": "pi_" + rif, "blocco_incassa_dal_ts": fine})}
        dentro, scaduto = p("DENTRO", adesso + 86400), p("SCADUTO", 1_000_000_000)
        for senza_istante in (None, True, False):
            viol, _ = _giudica_i2([dentro, scaduto], [], ora_ts=senza_istante)
            self.assertEqual([v[0] for v in viol], ["SCADUTO"],
                             "ora_ts=%r: deve valere l'orologio vero (DENTRO tace, SCADUTO grida)"
                             % (senza_istante,))

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


class TestSegnaBloccoEBlocchiApertiAiConfini(unittest.TestCase):
    """`segna_blocco` e `blocchi_aperti` di fase162 sugli ingressi che il flusso normale non
    manda mai. Nate dal Giudice sul diff del blocco (2026-09-29): 10 sopravvissuti su 25, perche'
    nessun test chiamava queste due funzioni fuori dal cammino felice. Il False di `segna_blocco`
    non e' un dettaglio: e' cio' che fa rispondere 503 `blocco_non_segnato` a fase83."""

    CORPO = {"ospite": "Nicolò Città", "totale_cents": 5000}

    def setUp(self):
        import os
        from fase162_pagamenti_pendenti import crea_pagamenti_pendenti
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "pendenti.db")
        self.pp = crea_pagamenti_pendenti(self.db)
        self.pp.inizializza_schema()
        for rif in ("RIF", "123"):
            self.assertTrue(self.pp.registra(rif, alloggio_id="a", check_in="2030-01-01",
                                             check_out="2030-01-03",
                                             corpo_json=json.dumps(self.CORPO, ensure_ascii=False)))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def grezzo(self, rif):
        import sqlite3
        con = sqlite3.connect(self.db)
        try:
            return con.execute("SELECT corpo_json FROM pendenti WHERE riferimento=?",
                               (rif,)).fetchone()[0]
        finally:
            con.close()

    def test_un_riferimento_che_non_e_una_stringa_piena_non_scrive(self):
        prima = self.grezzo("123")
        for rif in (None, "", 123):
            self.assertIs(self.pp.segna_blocco(rif, blocco_pi="pi_x"), False, "rif=%r" % (rif,))
        self.assertEqual(self.grezzo("123"), prima,
                         "il numero 123 non e' il riferimento '123': SQLite li confronterebbe uguali")

    def test_si_scrivono_solo_i_campi_del_blocco_e_tutti_o_nessuno(self):
        prima = self.grezzo("RIF")
        for campi in ({}, {"nome_sbagliato": "x"}, {"blocco_pi": None}, {"blocco_pi": ""},
                      {"blocco_pi": "pi_x", "nome_sbagliato": "y"}):
            self.assertIs(self.pp.segna_blocco("RIF", **campi), False, "campi=%r" % (campi,))
        self.assertEqual(self.grezzo("RIF"), prima, "una richiesta rifiutata non scrive niente")

    def test_un_riferimento_che_non_esiste_risponde_False(self):
        self.assertIs(self.pp.segna_blocco("NON_ESISTE", blocco_pi="pi_x"), False)

    def test_la_scrittura_che_fallisce_risponde_False_e_lascia_la_traccia(self):
        import sqlite3
        con = sqlite3.connect(self.db)
        with con:
            con.execute("CREATE TRIGGER no_update BEFORE UPDATE ON pendenti "
                        "BEGIN SELECT RAISE(ABORT, 'disco pieno'); END")
        con.close()
        with self.assertLogs("core_auto.pagamenti_pendenti", level="WARNING") as registro:
            esito = self.pp.segna_blocco("RIF", blocco_pi="pi_x")
        self.assertIs(esito, False, "una scrittura non riuscita non puo' dire «segnato»")
        rec = [r for r in registro.records if "segna_blocco" in r.getMessage()]
        self.assertEqual(len(rec), 1)
        self.assertIsInstance(rec[0].exc_info, tuple, "la riga deve portare l'eccezione intera")
        self.assertTrue(issubclass(rec[0].exc_info[0], sqlite3.Error))

    def test_la_riga_riscritta_resta_leggibile_come_le_altre(self):
        self.assertIs(self.pp.segna_blocco("RIF", blocco_pi="pi_x"), True)
        grezzo = self.grezzo("RIF")
        self.assertIn("Nicolò Città", grezzo,
                      "il modulo scrive il corpo in UTF-8 leggibile (come alle righe gemelle): "
                      "chi cerca un nome nel file deve trovarlo anche dopo il blocco")
        self.assertEqual(json.loads(grezzo), dict(self.CORPO, blocco_pi="pi_x"))

    def test_un_tetto_non_valido_torna_quello_di_serie(self):
        for rif in ("RIF", "123"):
            self.assertIs(self.pp.segna_blocco(rif, blocco_pi="pi_" + rif), True)
        self.assertEqual(len(self.pp.blocchi_aperti(limit=1)), 1, "un tetto valido vale")
        for tetto in (True, False, 0, -1, 5001, "3", None):
            self.assertEqual(len(self.pp.blocchi_aperti(limit=tetto)), 2, "limit=%r" % (tetto,))

    def test_il_tetto_massimo_dichiarato_vale_davvero(self):
        import sqlite3
        con = sqlite3.connect(self.db)
        with con:
            con.executemany(
                "INSERT INTO pendenti (riferimento, alloggio_id, check_in, check_out, corpo_json,"
                " scadenza_ts, creato_ts) VALUES (?, 'a', '2030-01-01', '2030-01-03', ?, 1, 1)",
                [("B%03d" % i, json.dumps({"blocco_pi": "pi_%d" % i})) for i in range(501)])
        con.close()
        self.assertEqual(len(self.pp.blocchi_aperti()), 500, "di serie il tetto e' 500")
        self.assertEqual(len(self.pp.blocchi_aperti(limit=5000)), 501,
                         "5000 e' ammesso: il confine e' compreso")


class _Registro:
    """Raccoglie TUTTO cio' che scrive il server, anche niente (su Python 3.9 `assertNoLogs`
    non c'e', e la direzione «tace» di un allarme va provata quanto l'altra, ferrea 10)."""

    def __init__(self):
        import logging
        self.records = []
        self._log = logging.getLogger("core_auto.server")
        self._h = logging.Handler(level=logging.DEBUG)
        self._h.emit = self.records.append

    def __enter__(self):
        import logging
        self._livello = self._log.level
        self._log.addHandler(self._h)
        self._log.setLevel(logging.DEBUG)
        return self

    def __exit__(self, *a):
        self._log.removeHandler(self._h)
        self._log.setLevel(self._livello)

    def testi(self, livello=None):
        return [r.getMessage() for r in self.records if livello in (None, r.levelname)]


class TestIRamiDelBloccoCheNessunoEseguiva(_Base):
    """fase83, le funzioni del blocco sulla carta fuori dal cammino felice. Nate dal Giudice sul
    diff del blocco (2026-09-29): 28 sopravvissuti su 87 in queste funzioni, rami difensivi che
    nessun test eseguiva (D19) -- Stripe che non risponde o risponde storto, un fornitore senza
    incasso o annullo, un istante non valido, il confine esatto della finestra, il motivo che
    deve arrivare nel registro (ferrea 9)."""

    def _bloccata(self):
        rif, vt, tot = self.prenota("2027-04-10", "2027-04-12")
        _s, _c, pi = self.paga_bloccato(rif, tot)
        self.assertEqual(self.stato(rif), "pagato", "PREMESSA: il blocco ha confermato")
        return rif, vt, tot, pi

    # ── il webhook ───────────────────────────────────────────────────────────────
    def test_la_sessione_unpaid_senza_blocco_risponde_il_corpo_intero(self):
        rif, _vt, _tot = self.prenota("2027-04-18", "2027-04-20")
        self.stripe.sessioni["cs_pix"] = ("unpaid", "pi_pix")
        self.stripe.pagamenti["pi_pix"] = "processing"
        s, c = self.evento("evt_pix", "checkout.session.completed", rif, "cs_pix", "pi_pix")
        self.assertEqual((s, c), (200, {"ricevuto": True, "tipo": "checkout.session.completed",
                                        "pagamento": "in_attesa"}))
        self.assertNotIn("blocco_pi", self.corpo(rif),
                         "un pagamento che NON e' requires_capture non e' un blocco")

    def test_una_rilettura_che_esplode_o_risponde_storto_fa_ritentare(self):
        import logging
        rif, _vt, tot = self.prenota("2027-04-14", "2027-04-16")
        self.stripe.pagamenti["pi_x"] = "requires_capture"

        def esplode(cs):
            raise ConnectionError("rete")
        for n, risposta in enumerate((esplode, lambda cs: None, lambda cs: "requires_capture")):
            # una sessione per tentativo: la deduplica riconosce la sessione, non solo l'evento
            cs = "cs_x%d" % n
            self.stripe.sessioni[cs] = ("unpaid", "pi_x")
            self.stripe.pagamento_della_sessione = risposta
            with _Registro() as reg:
                s, c = self.evento("evt_x%d" % n, "checkout.session.completed", rif, cs, "pi_x")
            self.assertEqual((s, c.get("sottocodice")), (503, "rilettura_pagamento_fallita"),
                             "risposta %d: %r %r" % (n, s, c))
            self.assertNotEqual(self.stato(rif), "pagato")
            if risposta is esplode:
                rec = [r for r in reg.records if "rilettura del pagamento" in r.getMessage()]
                self.assertEqual([r.levelno for r in rec], [logging.WARNING])
                self.assertIsInstance(rec[0].exc_info, tuple, "la traccia dell'esplosione manca")
                self.assertIs(rec[0].exc_info[0], ConnectionError)

    def test_se_la_scrittura_del_blocco_esplode_non_si_conferma(self):
        rif, _vt, tot = self.prenota("2027-04-10", "2027-04-12")

        def esplode(*a):
            raise RuntimeError("archivio bloccato")
        self.r._segna_blocco_aperto = esplode
        with _Registro() as reg:
            s, c, _pi = self.paga_bloccato(rif, tot)
        self.assertEqual((s, c.get("sottocodice")), (503, "blocco_non_segnato"),
                         "BLOCCO NON SCRITTO E PRENOTAZIONE CONFERMATA: la conferma scrive un "
                         "incasso che Stripe non ha fatto (%r %r)" % (s, c))
        self.assertNotEqual(self.stato(rif), "pagato")
        self.assertEqual(self.movimenti(rif, "incasso"), [])
        rec = [r for r in reg.records if "scrittura esplosa" in r.getMessage()]
        self.assertEqual(len(rec), 1)
        self.assertIsInstance(rec[0].exc_info, tuple)
        self.assertIs(rec[0].exc_info[0], RuntimeError)

    # ── la fine della finestra ───────────────────────────────────────────────────
    def test_segnare_il_blocco_senza_archivio_dei_pendenti_non_esplode(self):
        self.sis.pagamenti_pendenti = None
        self.assertIsNone(self.r._segna_blocco_aperto("RIF", "pi_x"))

    def test_un_istante_del_voucher_non_valido_vuol_dire_adesso(self):
        from unittest import mock
        rif, _vt, _tot = self.prenota("2027-04-10", "2027-04-12")
        for ts in (True, 0, -5):
            prima = int(time.time())
            with mock.patch.object(self.sis.firma, "decodifica", return_value={"prenotato_ts": ts}):
                self.assertIs(self.r._segna_blocco_aperto(rif, "pi_x"), True)
            fine = self.corpo(rif)["blocco_incassa_dal_ts"]
            self.assertTrue(prima <= fine <= int(time.time()),
                            "prenotato_ts=%r non e' un istante: la finestra finisce adesso, non a "
                            "%r" % (ts, fine))
        # l'altra direzione: un istante valido sposta la fine di 48 ore esatte
        with mock.patch.object(self.sis.firma, "decodifica",
                               return_value={"prenotato_ts": 1_900_000_000}):
            self.r._segna_blocco_aperto(rif, "pi_x")
        self.assertEqual(self.corpo(rif)["blocco_incassa_dal_ts"],
                         1_900_000_000 + SECONDI_RIPENSAMENTO)

    def test_un_voucher_illeggibile_lascia_la_traccia_e_si_incassa_subito(self):
        from unittest import mock
        rif, _vt, _tot = self.prenota("2027-04-10", "2027-04-12")
        prima = int(time.time())
        with mock.patch.object(self.sis.firma, "decodifica", side_effect=ValueError("rotto")), \
                self.assertLogs("core_auto.server", level="WARNING") as reg:
            self.assertIs(self.r._segna_blocco_aperto(rif, "pi_x"), True)
        rec = [r for r in reg.records if "voucher illeggibile" in r.getMessage()]
        self.assertEqual(len(rec), 1)
        self.assertIsInstance(rec[0].exc_info, tuple)
        self.assertIs(rec[0].exc_info[0], ValueError)
        self.assertTrue(prima <= self.corpo(rif)["blocco_incassa_dal_ts"] <= int(time.time()))

    # ── incasso e annullo ────────────────────────────────────────────────────────
    def test_lo_stato_del_pagamento_non_prende_per_buono_un_no(self):
        for risposta, atteso in (({"ok": False, "stato": "succeeded"}, ""), (None, ""),
                                 ({"ok": True, "stato": "requires_capture"}, "requires_capture")):
            self.stripe.stato_pagamento = lambda pi, r=risposta: r
            self.assertEqual(self.r._stato_pi("pi_x"), atteso, "risposta %r" % (risposta,))

    def test_un_fornitore_senza_incasso_non_incassa_niente(self):
        rif, _vt, _tot, pi = self._bloccata()
        self.stripe.incassa = None
        with self.assertLogs("core_auto.server", level="ERROR") as reg:
            self.assertEqual(self.r._incassa_blocco(rif, pi), "fallito")
        self.assertTrue(any("incasso_fallito" in t and "fornitore senza incasso" in t
                            for t in reg.output), reg.output)
        self.assertEqual(self.movimenti(rif, "incasso"), [],
                         "INCASSO SCRITTO SENZA CHE NESSUNO L'ABBIA CHIESTO A STRIPE")
        self.assertFalse(self.corpo(rif).get("blocco_incassato_ts"))

    def test_un_fornitore_senza_annullo_non_annulla_niente(self):
        rif, _vt, _tot, pi = self._bloccata()
        self.stripe.annulla = None
        with self.assertLogs("core_auto.server", level="ERROR") as reg:
            self.assertEqual(self.r._annulla_blocco(rif, pi), "fallito")
        self.assertTrue(any("annullo_fallito" in t and "fornitore senza annullo" in t
                            for t in reg.output), reg.output)
        self.assertFalse(self.corpo(rif).get("blocco_annullato_ts"),
                         "ANNULLO SCRITTO SENZA CHE STRIPE L'ABBIA FATTO: i soldi restano fermi")

    def test_l_incasso_e_l_annullo_falliti_scrivono_il_motivo_di_stripe(self):
        rif, _vt, _tot, pi = self._bloccata()
        self.stripe.esito_incasso = {"ok": False, "id": "", "motivo": "card_declined"}
        with self.assertLogs("core_auto.server", level="ERROR") as reg:
            self.assertEqual(self.r._incassa_blocco(rif, pi), "fallito")
        self.assertTrue(any("incasso_fallito" in t and "card_declined" in t for t in reg.output),
                        "il motivo di Stripe non arriva nel registro: %r" % reg.output)
        self.stripe.esito_annullo = {"ok": False, "id": "", "motivo": "URLError: rete"}
        with self.assertLogs("core_auto.server", level="ERROR") as reg:
            self.assertEqual(self.r._annulla_blocco(rif, pi), "fallito")
        self.assertTrue(any("annullo_fallito" in t and "URLError: rete" in t for t in reg.output),
                        "il motivo di Stripe non arriva nel registro: %r" % reg.output)

    def test_l_autorizzazione_scaduta_su_una_prenotazione_pagata_grida(self):
        """L'altra direzione del falso allarme riparato il 28/9: se la prenotazione e' DAVVERO
        ancora pagata, l'autorizzazione finita senza incasso e' un grido."""
        rif, _vt, _tot, pi = self._bloccata()
        self.stripe.pagamenti[pi] = "canceled"          # Stripe l'ha lasciata scadere
        with self.assertLogs("core_auto.server", level="ERROR") as reg:
            self.assertEqual(self.r._incassa_blocco(rif, pi), "annullato")
        self.assertTrue(any("autorizzazione_scaduta" in t and rif[:8] in t for t in reg.output),
                        "SOLDI MAI ENTRATI SU UNA PRENOTAZIONE PAGATA, E NESSUNO GRIDA: %r"
                        % reg.output)
        self.assertTrue(self.corpo(rif).get("blocco_annullato_ts"))

    def test_chiudere_il_blocco_per_ogni_suo_stato(self):
        def rec(**corpo):
            return {"corpo_json": json.dumps(corpo)}
        self.assertIs(self.r._chiudi_blocco("R", rec()), False, "nessun blocco: i soldi ci sono")
        self.assertIs(self.r._chiudi_blocco("R", rec(blocco_pi="pi_x", blocco_incassato_ts=5)),
                      False, "blocco incassato: i soldi ci sono, si restituiscono come sempre")
        self.assertIs(self.r._chiudi_blocco("R", rec(blocco_pi="pi_x", blocco_annullato_ts=5)),
                      True, "blocco annullato: i soldi non sono mai entrati")
        self.assertEqual((self.stripe.incassi, self.stripe.annulli), ([], []),
                         "un blocco gia' chiuso non si tocca su Stripe")
        # aperto con una penale: si INCASSA tutto, e i soldi ci sono
        rif, _vt, _tot, pi = self._bloccata()
        self.assertIs(self.r._chiudi_blocco(rif, self.sis.pagamenti_pendenti.info(rif), 500),
                      False, "incassato per la penale: la parte dovuta si rimborsa come sempre")
        self.assertEqual(self.stripe.incassi, [(pi, "incasso:" + rif)])

    # ── il giro orario ───────────────────────────────────────────────────────────
    def test_il_giro_senza_elenco_dei_blocchi_non_esplode(self):
        import types
        self.sis.pagamenti_pendenti = types.SimpleNamespace()
        self.assertEqual(self.r._incassa_blocchi(),
                         {"incassati": 0, "annullati": 0, "falliti": 0, "in_finestra": 0})

    def test_il_giro_senza_istante_usa_l_orologio_vero(self):
        self._bloccata()
        self.assertEqual(self.r._incassa_blocchi()["in_finestra"], 1)
        self.assertEqual(self.stripe.incassi, [])

    def test_il_giro_incassa_all_istante_esatto_della_fine(self):
        rif, _vt, _tot, pi = self._bloccata()
        fine = self.corpo(rif)["blocco_incassa_dal_ts"]
        self.assertEqual(self.r._incassa_blocchi(ora_ts=fine - 1)["in_finestra"], 1)
        self.assertEqual(self.r._incassa_blocchi(ora_ts=fine)["incassati"], 1,
                         "alla fine esatta della finestra si incassa")
        self.assertEqual(self.stripe.incassi, [(pi, "incasso:" + rif)])

    def test_il_giro_dice_cosa_ha_fatto_e_tace_se_non_ha_fatto_niente(self):
        rif, vt, _tot, pi = self._bloccata()
        with _Registro() as reg:
            self.r._incassa_blocchi()                    # dentro la finestra: niente da dire
        self.assertEqual([t for t in reg.testi() if "BLOCCHI SULLA CARTA" in t], [])
        with _Registro() as reg:
            self.r._incassa_blocchi(ora_ts=int(time.time()) + SECONDI_RIPENSAMENTO + 60)
        self.assertIn("BLOCCHI SULLA CARTA | incassati=1 annullati=0 falliti=0 in_finestra=0",
                      reg.testi("INFO"))
        # solo un annullo (l'annullo alla cancellazione e' fallito, lo rifa' il giro)
        rif2, vt2, tot2 = self.prenota("2027-05-10", "2027-05-12")
        _s, _c, pi2 = self.paga_bloccato(rif2, tot2, n=2)
        self.stripe.esito_annullo = {"ok": False, "id": "", "motivo": "URLError: rete"}
        self.stripe.pagamenti.pop(pi2)
        self.g("POST", "/api/concierge/cancella", {"voucher_token": vt2})
        self.stripe.esito_annullo = None
        self.stripe.pagamenti[pi2] = "requires_capture"
        with _Registro() as reg:
            self.r._incassa_blocchi()
        self.assertIn("BLOCCHI SULLA CARTA | incassati=0 annullati=1 falliti=0 in_finestra=0",
                      reg.testi("INFO"))

    # ── il pagamento tardivo su una stanza gia' presa ────────────────────────────
    def _stanza_rubata(self, rif, ci, co):
        pp = self.sis.pagamenti_pendenti
        rec = pp.info(rif)
        pp.scadi(rif)
        self.sis.inventario.rilascia("casa", ci, co,
                                     idem_key=(rec.get("idem_key") or ("hold_" + rif)))
        self.assertTrue(getattr(self.sis.inventario.blocca("casa", ci, co, idem_key="altro_" + rif),
                                "ok", False), "PREMESSA: dopo il rilascio la stanza era libera")

    def test_il_blocco_tardivo_su_una_stanza_presa_si_annulla(self):
        rif, _vt, tot = self.prenota("2027-04-10", "2027-04-12")
        self._stanza_rubata(rif, "2027-04-10", "2027-04-12")
        with _Registro() as reg:
            _s, _c, pi = self.paga_bloccato(rif, tot)
        self.assertEqual([p for p, _k in self.stripe.annulli], [pi])
        self.assertEqual(self.movimenti(rif, "rimborso"), [])
        self.assertEqual([t for t in reg.testi("ERROR") if "RIMBORSARE" in t], [],
                         "«RIMBORSARE» su soldi mai entrati: un allarme su niente da fare")

    def test_il_blocco_tardivo_si_annulla_anche_se_la_rilettura_non_trova_il_record(self):
        """`pp.info(rif) or rec`: se la rilettura dopo la marcatura non risponde, vale il record
        della conferma, che il blocco ce l'ha gia' (D19: il ripiego si prova iniettandolo)."""
        rif, _vt, tot = self.prenota("2027-04-10", "2027-04-12")
        self._stanza_rubata(rif, "2027-04-10", "2027-04-12")
        pp = self.sis.pagamenti_pendenti
        marcata, vera_info, vera_marca = [], pp.info, pp.marca_da_rimborsare
        pp.marca_da_rimborsare = lambda r: (marcata.append(r), vera_marca(r))[1]
        pp.info = lambda r: None if marcata else vera_info(r)
        _s, _c, pi = self.paga_bloccato(rif, tot)
        self.assertEqual(marcata, [rif], "PREMESSA: la strada del pagamento tardivo e' percorsa")
        self.assertEqual([p for p, _k in self.stripe.annulli], [pi])
        self.assertEqual(self.movimenti(rif, "rimborso"), [])


class _ConLeSpie(_Base):
    """Attrezzi comuni alle guardie sui rimborsi (nessun test qui: chi eredita non li ripete)."""

    def _pagata(self, ci, co, cs, pi):
        rif, _vt, tot = self.prenota(ci, co)
        self.stripe.sessioni[cs] = ("paid", pi)
        self.stripe.pagamenti[pi] = "succeeded"
        self.evento("evt_" + cs, "checkout.session.completed", rif, cs, pi)
        self.assertEqual(self.stato(rif), "pagato", "PREMESSA: pagata")
        return rif, tot

    def _azzera_il_totale(self, rif):
        import sqlite3
        corpo = dict(self.corpo(rif), totale_cents=0, prezzo_guest_cents=0)
        con = sqlite3.connect(self.dir + "/p.db")
        with con:
            con.execute("UPDATE pendenti SET corpo_json=? WHERE riferimento=?",
                        (json.dumps(corpo), rif))
        con.close()

    def _spia_del_giornale(self):
        chieste, vero = [], self.r._giornale
        self.r._giornale = lambda *a, **k: (chieste.append(k), vero(*a, **k))[1]
        return chieste

    def rimborsa(self, rif, ci, co):
        idem = self.sis.pagamenti_pendenti.info(rif)["idem_key"]
        return self.g("POST", "/api/admin/rimborso", {"alloggio_id": "casa", "check_in": ci,
                                                      "check_out": co, "idem_key": idem}, AK)


class TestIlRimborsoDellAdminColBlocco(_ConLeSpie):
    """Il pulsante «Rimborsa» del pannello admin (e la cancellazione dell'host) sul blocco sulla
    carta. Nate dal Giudice sul diff del blocco (2026-09-29): quattro sopravvissuti su fase83
    anche con gli occhi di quelle strade accesi (test_admin_rimborso_money,
    test_rimborso_torna_da_ogni_strada, test_rimborso_arriva_al_gateway, test_cancellazione_money,
    test_storno_penale): nessun test premeva il pulsante su un pagamento bloccato, ne' guardava
    una riga di rimborso chiesta per zero euro."""

    def test_il_rimborso_dell_admin_su_un_blocco_annulla_senza_riga(self):
        rif, _vt, tot = self.prenota("2027-04-10", "2027-04-12")
        _s, _c, pi = self.paga_bloccato(rif, tot)
        s, c = self.rimborsa(rif, "2027-04-10", "2027-04-12")
        self.assertEqual(s, 200, "%r" % (c,))
        self.assertEqual([p for p, _k in self.stripe.annulli], [pi],
                         "il rimborso dell'admin non annulla il blocco sulla carta")
        self.assertEqual((self.stripe.rimborsi, self.movimenti(rif, "rimborso")), ([], []),
                         "RIGA DI RIMBORSO PER SOLDI MAI ENTRATI: la lista dei rimborsi dovuti "
                         "mostrerebbe un pulsante che Stripe rifiuta")
        self.assertIn("AUTORIZZATO", c.get("rimborso_stripe", ""))

    def test_un_totale_a_zero_non_chiede_una_riga_di_rimborso(self):
        """Il chiamante non chiede una riga da zero euro: che `_giornale` la scarti da se' e' la
        seconda difesa, non la prima (D19)."""
        rif, _tot = self._pagata("2027-04-22", "2027-04-24", "cs_zero", "pi_zero")
        self._azzera_il_totale(rif)
        chieste = self._spia_del_giornale()
        s, c = self.rimborsa(rif, "2027-04-22", "2027-04-24")
        self.assertEqual(s, 200, "%r" % (c,))
        self.assertEqual([k for k in chieste if k.get("tipo") == "rimborso"], [],
                         "chiesta una riga di rimborso da zero euro")
        self.assertIn("non determinabile", c.get("rimborso_stripe", ""))

    def test_la_cancellazione_dell_host_con_totale_a_zero_non_chiede_una_riga(self):
        """fase83 `_host_cancella`, stessa regola (sopravviveva `guest > 0` diventato `>= 0`)."""
        rif, _tot = self._pagata("2027-05-02", "2027-05-04", "cs_host0", "pi_host0")
        self._azzera_il_totale(rif)
        chieste = self._spia_del_giornale()
        s, c = self.g("POST", "/api/host/cancella", {"riferimento": rif, "host_id": "demo"}, HK)
        self.assertEqual(s, 200, "%r" % (c,))
        self.assertEqual([k for k in chieste if k.get("tipo") == "rimborso"], [],
                         "chiesta una riga di rimborso da zero euro")

    def test_se_un_passo_di_sicurezza_esplode_non_si_dice_annullato(self):
        """Se il pendente non si marca, i soldi (incassati) NON partono e va detto: dire
        «pagamento solo autorizzato, annullato» farebbe credere all'admin che non ci sia niente
        da restituire."""
        rif, _tot = self._pagata("2027-04-26", "2027-04-28", "cs_esplode", "pi_esplode")

        def esplode(r):
            raise RuntimeError("archivio bloccato")
        self.sis.pagamenti_pendenti.marca_da_rimborsare = esplode
        s, c = self.rimborsa(rif, "2027-04-26", "2027-04-28")
        self.assertEqual(s, 200, "%r" % (c,))
        self.assertIn("pendente_invalidato", c.get("passi_falliti", []))
        testo = c.get("rimborso_stripe", "")
        self.assertIn("A MANO", testo, "all'admin va detto che i soldi vanno restituiti a mano")
        self.assertNotIn("AUTORIZZATO", testo,
                         "«solo autorizzato, niente da restituire» su soldi INCASSATI: %r" % testo)
        self.assertEqual(self.stripe.rimborsi, [])


class TestLaCancellazioneDellOspiteAiMargini(_ConLeSpie):
    """fase83, la cancellazione dell'ospite col blocco sulla carta fuori dal cammino felice. Nate
    dal Giudice sul diff del blocco (2026-09-29): cinque sopravvissuti anche con gli occhi della
    cancellazione accesi (test_cancellazione_money, test_rimborso_torna_da_ogni_strada,
    test_escrow_gia_liquidato, test_fase111_endpoint, test_happy_soldi)."""

    def cancella(self, vt):
        s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
        self.assertEqual(s, 200, "%r" % (c,))
        return c

    def _pagata_col_voucher(self, ci, co, cs, pi):
        rif, vt, tot = self.prenota(ci, co)
        self.stripe.sessioni[cs] = ("paid", pi)
        self.stripe.pagamenti[pi] = "succeeded"
        self.evento("evt_" + cs, "checkout.session.completed", rif, cs, pi)
        self.assertEqual(self.stato(rif), "pagato", "PREMESSA: pagata")
        return rif, vt, tot

    def test_se_l_archivio_non_risponde_il_rimborso_dovuto_si_scrive_lo_stesso(self):
        """«In dubbio vale il voucher» (pagato_davvero resta vero): il rimborso dovuto nasce."""
        rif, vt, tot = self._pagata_col_voucher("2027-04-10", "2027-04-12", "cs_arch", "pi_arch")
        pp, vera, prima = self.sis.pagamenti_pendenti, self.sis.pagamenti_pendenti.info, []

        def info(r):
            if not prima:
                prima.append(r)
                raise RuntimeError("archivio non risponde")
            return vera(r)
        pp.info = info
        self.cancella(vt)
        self.assertEqual(prima, [rif], "PREMESSA: la prima lettura e' fallita")
        self.assertEqual([m["importo_cents"] for m in self.movimenti(rif, "rimborso")], [tot],
                         "RIMBORSO DOVUTO SPARITO: soldi incassati, cancellazione nelle 48 ore, e "
                         "nessuna riga che dica che vanno restituiti")

    def test_una_prenotazione_non_pagata_col_blocco_non_tocca_stripe_alla_cancellazione(self):
        rif, vt, _tot = self.prenota("2027-04-14", "2027-04-16")
        self.stripe.pagamenti["pi_np"] = "requires_capture"
        self.assertIs(self.sis.pagamenti_pendenti.segna_blocco(
            rif, blocco_pi="pi_np", blocco_incassa_dal_ts=int(time.time()) + 999), True)
        self.cancella(vt)
        self.assertEqual((self.stripe.annulli, self.stripe.incassi), ([], []),
                         "una prenotazione NON pagata non si chiude su Stripe alla cancellazione")
        self.assertEqual(self.movimenti(rif, "rimborso"), [])

    def test_se_la_chiusura_del_blocco_esplode_lo_si_scrive_e_si_decide_giusto(self):
        def esplode(*a):
            raise RuntimeError("stripe irraggiungibile")
        # blocco APERTO: soldi mai entrati, nessuna riga di rimborso
        rif, vt, tot = self.prenota("2027-04-10", "2027-04-12")
        self.paga_bloccato(rif, tot)
        self.r._chiudi_blocco = esplode
        with _Registro() as reg:
            self.cancella(vt)
        rec = [r for r in reg.records if "chiusura del blocco sulla carta esplosa" in r.getMessage()]
        self.assertEqual([r.levelname for r in rec], ["ERROR"])
        self.assertIsInstance(rec[0].exc_info, tuple)
        self.assertIs(rec[0].exc_info[0], RuntimeError)
        self.assertEqual(self.movimenti(rif, "rimborso"), [],
                         "RIGA DI RIMBORSO PER UN BLOCCO APERTO: soldi mai entrati")
        # nessun blocco: i soldi ci sono, e la riga del rimborso dovuto nasce
        rif2, vt2, tot2 = self._pagata_col_voucher("2027-05-10", "2027-05-12", "cs_nb", "pi_nb")
        self.cancella(vt2)
        self.assertEqual([m["importo_cents"] for m in self.movimenti(rif2, "rimborso")], [tot2])

    def test_una_cancellazione_senza_rimborso_non_grida_e_non_chiede_righe(self):
        """Non rimborsabile, dopo le 48 ore: rimborso zero. Chiedere una riga da zero euro fa
        gridare «RIMBORSO DOVUTO NON REGISTRATO» su niente (ferrea 10)."""
        from unittest import mock
        # un annuncio SENZA tassa di soggiorno: la tassa si restituisce sempre, e qui serve
        # un rimborso che sia davvero zero
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "casa0", "titolo": "C0",
               "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
               "servizi": [], "immagini": [], "politica_cancellazione": "non_rimborsabile"}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa0", "da": "2027-04-01",
               "a": "2027-05-31", "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa0", "check_in":
                      "2027-04-22", "check_out": "2027-04-24", "party": 2})
        self.assertEqual(q.get("tassa_soggiorno_cents"), 0, "PREMESSA: annuncio senza tassa")
        _, b = self.g("POST", "/api/concierge/book", {"quote_token": q["quote_token"],
                                                      "email": "o@x.it"})
        rif, vt = b["riferimento"], b.get("voucher_token", "")
        self.stripe.sessioni["cs_nr"] = ("paid", "pi_nr")
        self.stripe.pagamenti["pi_nr"] = "succeeded"
        self.evento("evt_cs_nr", "checkout.session.completed", rif, "cs_nr", "pi_nr")
        self.assertEqual(self.stato(rif), "pagato", "PREMESSA: pagata")
        chieste = self._spia_del_giornale()
        with mock.patch("time.time", return_value=time.time() + SECONDI_RIPENSAMENTO + 3600), \
                _Registro() as reg:
            c = self.cancella(vt)
        self.assertEqual(c.get("rimborso_cents"), 0, "PREMESSA: non rimborsabile, niente rimborso")
        self.assertEqual([k for k in chieste if k.get("tipo") == "rimborso"], [])
        self.assertEqual([t for t in reg.testi("ERROR") if "RIMBORSO DOVUTO" in t], [],
                         "FALSO ALLARME: rimborso zero e grido «non registrato»")


class TestIlGiroOrarioLasciaLaTraccia(unittest.TestCase):
    """Il tick orario e' una chiusura dentro `servi()`: si legge l'albero sintattico (come
    `test_fase202.TestIlTickDiFase83ChiamaIlGiro`). Se il giro dei blocchi esplode, il thread
    resta vivo e la riga ERROR deve portare l'eccezione intera: sopravviveva `exc_info=False`."""

    def test_il_giro_dei_blocchi_fallito_scrive_l_eccezione(self):
        import ast
        import os
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fase83_server.py"),
                  encoding="utf-8") as f:
            albero = ast.parse(f.read())
        tick = [n for n in ast.walk(albero)
                if isinstance(n, ast.FunctionDef) and n.name == "_tick_garanzia"]
        self.assertEqual(len(tick), 1, "il tick della garanzia non si trova piu'")
        prove = [t for t in ast.walk(tick[0]) if isinstance(t, ast.Try)
                 and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                         and c.func.attr == "_incassa_blocchi"
                         for s in t.body for c in ast.walk(s))]
        self.assertEqual(len(prove), 1, "il giro dei blocchi non e' dentro il suo try")
        chiamate = [c for h in prove[0].handlers for c in ast.walk(h)
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                    and c.func.attr == "error"]
        self.assertEqual(len(chiamate), 1)
        exc = [k.value for k in chiamate[0].keywords if k.arg == "exc_info"]
        self.assertTrue(len(exc) == 1 and isinstance(exc[0], ast.Constant) and exc[0].value is True,
                        "la riga ERROR del giro fallito non porta l'eccezione (exc_info=True)")


if __name__ == "__main__":
    unittest.main()
