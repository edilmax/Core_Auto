"""CASELLA 2, l'ultima riga: **ogni strada arriva in lista con il DOVUTO GIUSTO.**

`test_rimborso_arriva_al_gateway.py` ha chiuso l'altra meta': **dal pannello i soldi partono
davvero** (2 punti su 2, entrambi provati). Restava questa, ed e' quella che decide **quanto**
torna all'ospite: le sette strade **mettono in lista**, e se una ci mette l'importo sbagliato
il pulsante restituisce la cifra sbagliata — con tutta la catena a valle che funziona
benissimo.

⛔ **NON BASTA CHE LA RIGA ESISTA.** Una riga presente col numero sbagliato e' peggio di una
riga mancante: la mancante si nota, quella sbagliata viene **eseguita**. Qui si pretende
l'importo, non la presenza.

📊 **DENOMINATORE: da 1 su 7 a 3 su 7.** Provate finora:
    1. cancellazione ospite ........ (in `test_rimborso_arriva_al_gateway`) -> lo SCAGLIONE
    2. cancellazione host .......... qui -> il TOTALE (colpa dell'host, ospite rimborsato 100%)
    3. pagamento non confermabile .. qui -> il TOTALE (soldi arrivati su una prenotazione morta)
Restano **4 su 7** non provate: controversia, pagamento tardivo, anticipo tardivo, rimborso
admin. ⚠️ E il denominatore resta **7** e non 6, per la ragione dichiarata nell'altro file:
non e' misurato quali strade *debbano* comparire in lista, e assumerlo sarebbe una precisione
finta.
"""
import datetime
import json
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_dovuto"
CHIAVE_FINTA = "sk"


class _GatewayCheConferma:
    """Provider finto che **conferma** su Stripe, cosi' la riga in lista non resta senza
    pulsante per `manca: verifica_stripe`. Non esegue nessun rimborso: qui si misura la
    LISTA, non la partenza — quella e' provata altrove."""

    def __init__(self, vero):
        self._vero = vero

    def __getattr__(self, nome):
        return getattr(self._vero, nome)

    def rimborsi_di(self, payment_intent):
        return {"ok": True, "rimborsato_cents": 0}


class _Banco(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(
            lambda u, b, h: {"url": "https://x/cs", "id": "cs_" + str(time.time_ns())})

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db",
            commissione_bps=1500, psp_bps=300, stripe_secret_key=CHIAVE_FINTA,
            stripe_webhook_secret=WH, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/no"))
        self.sis.stripe = _GatewayCheConferma(getattr(self.sis, "stripe", None))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://b.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@dv.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        self.oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "C", "citta": "Roma", "prezzo_notte_cents": 20000,
                "capacita": 4, "tassa_pp_notte_cents": 200}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": self.oggi.isoformat(),
                "a": (self.oggi + datetime.timedelta(days=60)).isoformat(),
                "unita_totali": 2, "prezzo_netto_cents": 20000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def prenota(self, email):
        ci = self.oggi.isoformat()
        co = (self.oggi + datetime.timedelta(days=2)).isoformat()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": email})
        return (b["riferimento"], b["voucher_token"],
                q.get("totale_cents") or q.get("prezzo_guest_cents"))

    def paga(self, rif, pi="pi_dv"):
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": "cs_dv", "payment_intent": pi,
                                             "metadata": {"riferimento": rif}}}})
        return self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                               {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})

    def riga_in_lista(self, rif):
        """La riga del pannello «rimborsi dovuti» per questo riferimento, o None."""
        s, lista = self.g("GET", "/api/admin/rimborsi_dovuti", None, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, "la lista dei rimborsi dovuti non risponde: %r" % (lista,))
        for r in (lista or {}).get("rimborsi", []):
            if r.get("riferimento") == rif:
                return r
        return None


class TestOgniStradaArrivaInListaColDovutoGiusto(_Banco):

    def test_STRADA_cancellazione_HOST_mette_in_lista_il_TOTALE(self):
        """Quando cancella l'host la colpa e' sua: l'ospite va rimborsato **al 100%**.

        Se in lista finisse lo scaglione (come per la cancellazione dell'ospite), chi preme
        il pulsante restituirebbe **meno del dovuto** — e la differenza resterebbe a noi
        senza che nessuno l'abbia decisa."""
        rif, _vou, totale = self.prenota("host@dv.it")
        st, _ = self.paga(rif)
        self.assertEqual(st, 200, "PREMESSA NON VALIDA: il pagamento non e' stato accettato.")

        s, o = self.g("POST", "/api/host/cancella", {"riferimento": rif},
                      {"X-Host-Token": self.tok})
        self.assertEqual(s, 200, "PREMESSA NON VALIDA: la cancellazione host non riesce: %r"
                                 % (o,))

        riga = self.riga_in_lista(rif)
        self.assertIsNotNone(
            riga,
            "LA STRADA NON ARRIVA IN LISTA. L'host ha cancellato, l'ospite ha pagato, e nel "
            "pannello dei rimborsi dovuti non c'e' niente: nessuno sa che quei soldi sono "
            "dovuti, e il pulsante per restituirli non esiste.")
        self.assertEqual(
            riga.get("dovuto_cents"), totale,
            "IN LISTA C'E' L'IMPORTO SBAGLIATO: %s invece di %s. Quando cancella l'HOST "
            "l'ospite ha diritto al 100%%, non allo scaglione: chi preme il pulsante "
            "restituirebbe meno del dovuto, e la differenza resterebbe a noi senza che "
            "nessuno l'abbia decisa." % (riga.get("dovuto_cents"), totale))

    def test_STRADA_pagamento_NON_CONFERMABILE_mette_in_lista_il_TOTALE(self):
        """I soldi sono arrivati per una prenotazione che non si puo' onorare.

        L'ospite cancella, e **dopo** arriva il pagamento (Stripe consegna in ritardo, o
        l'ospite paga il link vecchio). Quei soldi non comprano niente: vanno restituiti
        **per intero**, non secondo lo scaglione di una cancellazione che al momento del
        pagamento era gia' avvenuta."""
        rif, voucher, totale = self.prenota("ncf@dv.it")
        s1, _ = self.g("POST", "/api/concierge/cancella", {"voucher_token": voucher})
        self.assertEqual(s1, 200, "PREMESSA NON VALIDA: la cancellazione non riesce.")

        st, _ = self.paga(rif, pi="pi_tardivo")
        self.assertEqual(st, 200, "PREMESSA NON VALIDA: il webhook non e' stato accettato.")

        riga = self.riga_in_lista(rif)
        self.assertIsNotNone(
            riga,
            "LA STRADA NON ARRIVA IN LISTA. Sono arrivati soldi per una prenotazione "
            "cancellata e il pannello non lo sa: l'ospite ha pagato per niente e nessuno "
            "gli deve niente, secondo il sistema.")
        # ⛔ L'ASSERZIONE E' SUL TOTALE, non su «maggiore di zero». La prima stesura diceva
        # `>= 1` perche' non avevo misurato il valore vero: sarebbe passata anche con
        # l'importo sbagliato, cioe' proprio col difetto che questa guardia deve prendere.
        # Misurato: totale 40800 -> in lista 40800, e nel giornale una sola riga
        # (`rimborso_non_confermabile`, 40800). ⚠️ Nota misurata: la cancellazione avvenuta
        # PRIMA del pagamento dichiara rimborso **0** (non c'era ancora niente da
        # restituire) e non scrive nessuna riga — quindi qui non c'e' collisione di chiavi,
        # e il totale entra pulito.
        self.assertEqual(
            riga.get("dovuto_cents"), totale,
            "IN LISTA C'E' L'IMPORTO SBAGLIATO: %s invece di %s. Quei soldi sono arrivati "
            "per una prenotazione che non si puo' onorare: non comprano niente, quindi "
            "vanno restituiti per INTERO. Una riga presente col numero sbagliato e' peggio "
            "di una riga mancante — la mancante si nota, questa viene **eseguita**."
            % (riga.get("dovuto_cents"), totale))


class TestLeDueStradeDoveLimportoLoDecideUnaPERSONA(_Banco):
    """⛔ Le due strade in cui il dovuto **non lo calcola la politica**: lo decide qualcuno.

    Nelle altre cinque l'importo esce da una regola (lo scaglione, il 100%, il totale): se la
    regola è giusta, il numero è giusto. Qui no — **lo digita una persona** (il rimborso admin)
    o **lo decide un arbitro** (la controversia). Sono quindi le due dove «il dovuto giusto» ha
    più modi di essere diverso da quello che finisce in lista, e le uniche in cui un numero
    arbitrario deve attraversare tutta la catena **senza essere riscritto da nessuno**.
    ⚠️ Gli attesi sono **misurati prima** di scrivere le asserzioni, non ipotizzati: è la
    correzione che questo stesso file ha già dovuto fare una volta."""

    def test_STRADA_rimborso_ADMIN_mette_in_lista_il_TOTALE(self):
        """E se il gateway non risponde, la riga **resta in lista col pulsante**.

        Misurato: il provider finto fa fallire `rimborsa` e il sistema **grida**
        (`passi FALLITI=['soldi_restituiti'] -> rischio PERDITA PIENA`) invece di dichiarare
        chiuso il rimborso. La riga rimane, con il totale e il pulsante: una persona può
        ritentare. È il comportamento giusto — un rimborso che fallisce in silenzio sarebbe
        un ospite che aspetta per sempre."""
        rif, _vou, totale = self.prenota("adm@dv.it")
        st, _ = self.paga(rif, pi="pi_adm")
        self.assertEqual(st, 200, "PREMESSA NON VALIDA: il pagamento non è stato accettato.")

        _, adm = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Key": "ak"})
        idem = None
        for p in (adm or {}).get("prenotazioni", []):
            if str(p.get("idem_key", ""))[:24] == rif:
                idem = p.get("idem_key")
                break
        self.assertIsNotNone(idem, "PREMESSA NON VALIDA: idem_key non trovata nel pannello.")
        ci = self.oggi.isoformat()
        co = (self.oggi + datetime.timedelta(days=2)).isoformat()
        s, o = self.g("POST", "/api/admin/rimborso",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co,
                       "idem_key": idem}, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, "PREMESSA NON VALIDA: il rimborso admin non riesce: %r" % (o,))

        riga = self.riga_in_lista(rif)
        self.assertIsNotNone(
            riga,
            "LA STRADA NON ARRIVA IN LISTA. L'admin ha disposto il rimborso, i soldi non sono "
            "partiti (il gateway ha rifiutato), e nel pannello non resta niente: la richiesta "
            "sparisce e l'ospite aspetta un rimborso che nessuno sa più di dovergli.")
        self.assertEqual(
            riga.get("dovuto_cents"), totale,
            "IN LISTA C'È L'IMPORTO SBAGLIATO: %s invece di %s. Il rimborso admin muove il "
            "TOTALE, quindi è quello che deve risultare dovuto: se in lista finisse un "
            "importo minore, un ritentativo restituirebbe meno di quanto era stato deciso."
            % (riga.get("dovuto_cents"), totale))

    def test_STRADA_CONTROVERSIA_mette_in_lista_l_importo_deciso_dall_ARBITRO(self):
        """Il numero lo decide una persona, e deve arrivare **intatto** fino alla lista.

        È l'unico caso in cui l'importo non è derivabile da nessuna regola: se qualcosa lo
        ricalcolasse (con lo scaglione, col totale, con la politica), l'arbitrato verrebbe
        **scavalcato in silenzio** — la decisione resterebbe scritta nel verbale e i soldi
        seguirebbero un'altra cifra.
        ⚠️ Misurato: la riga compare **senza pulsante** (`manca: date_liberate`), ed è
        **voluto** — il soggiorno c'è stato, quindi le date sono legittimamente occupate e il
        freno non passa. Il rimborso resta manuale, come dichiara la rotta stessa. Qui si
        pretende **l'importo**, non il pulsante."""
        rif, _vou, totale = self.prenota("ctr@dv.it")
        st, _ = self.paga(rif, pi="pi_ctr")
        self.assertEqual(st, 200, "PREMESSA NON VALIDA: il pagamento non è stato accettato.")

        gz = getattr(self.sis, "garanzia", None)
        self.assertIsNotNone(gz, "BANCO ROTTO: il modulo garanzia non c'è, e senza non si può "
                                 "aprire una controversia: si ripara il banco, non si salta.")
        esito = gz.contesta(rif, "danni")
        self.assertTrue(esito.get("ok"),
                        "PREMESSA NON VALIDA: la controversia non si apre: %r" % (esito,))

        deciso = 12345          # una cifra arbitraria, che NESSUNA regola produrrebbe
        self.assertNotEqual(deciso, totale,
                            "PREMESSA NON VALIDA: l'importo dell'arbitro coincide col totale, "
                            "quindi la prova non distinguerebbe «intatto» da «ricalcolato».")
        s, o = self.g("POST", "/api/admin/controversia/risolvi",
                      {"riferimento": rif, "rimborso_ospite_cents": deciso},
                      {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, "PREMESSA NON VALIDA: la controversia non si risolve: %r" % (o,))

        riga = self.riga_in_lista(rif)
        self.assertIsNotNone(
            riga,
            "LA DECISIONE DELL'ARBITRO NON ARRIVA IN LISTA. È stata presa, l'ospite è stato "
            "avvisato per email, e nel pannello non risulta dovuto niente: la promessa esiste "
            "solo nella memoria di chi ha arbitrato.")
        self.assertEqual(
            riga.get("dovuto_cents"), deciso,
            "L'ARBITRATO È STATO SCAVALCATO: in lista c'è %s invece dei %s decisi. Qualcosa "
            "ha ricalcolato un importo che nessuna regola doveva toccare — la decisione resta "
            "nel verbale e i soldi seguono un'altra cifra."
            % (riga.get("dovuto_cents"), deciso))


if __name__ == "__main__":
    unittest.main(verbosity=2)
