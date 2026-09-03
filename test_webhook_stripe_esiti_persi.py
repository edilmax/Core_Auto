"""GUARDIA — il webhook di Stripe risponde 200 anche quando l'esito e' andato perso.

RILIEVO: `collaudi/METODO_v4.md` PARTE 12, casella «L'elaborazione fallita **non** risponde
200» (misurata NO il 2026-08-28). Qui la guardia che la rende rossa invece che scritta.

PERCHE' UN 200 SBAGLIATO COSTA PIU' DI UN 500. Stripe legge 200 come «ricevuto e gestito»
e **non riprova mai piu'**. Un 500, invece, lo fa ritentare per giorni. Quindi rispondere
200 su un esito perso non e' un errore di forma: e' l'unico modo di rendere quella perdita
DEFINITIVA. Un 500 su un esito che si e' comunque salvato costa un retry inutile; un 200 su
un esito perso costa l'esito.

TRE PUNTI, tutti dentro `_webhook_stripe` (`fase83_server.py`), in ordine di gravita':

  [1] SOLDI — `salva_stripe_session` esplode. L'`except` la inghiotte («ISOLATO»), si
      prosegue e si risponde 200. Non viene salvato `payment_intent` (pi_...), che e'
      l'UNICO modo di dire a Stripe quale pagamento restituire: senza, la scheda del
      rimborso dichiara `manca: payment_intent` e il pulsante non compare
      (`fase83_server.py` `manca.append("payment_intent")`, e il rimborso vero passa da
      `sp.rimborsa(riga["payment_intent"], ...)`). Il rimborso all'ospite torna una cosa
      da fare a mano dal pannello Stripe, per sempre e senza che nessuno lo sappia.

  [2] SOLDI — `salva_stripe_session` NON esplode: restituisce `False`. Il chiamante
      **ignora il valore di ritorno**, quindi il caso «non salvato» e' indistinguibile da
      «salvato». Stesso danno di [1], e qui non serve nemmeno un guasto: basta che il
      record non ci sia ancora quando l'evento arriva.

  [3] IDENTITA' — `kyc.conferma` esplode. L'`except` la inghiotte, si risponde 200 e
      l'esito della verifica d'identita' dell'host e' perso: l'host resta «non verificato»
      per sempre, e Stripe non riprovera'.

  [4] IDENTITA', SENZA NESSUN GUASTO — ed e' il piu' brutto dei quattro, perche' non ha
      bisogno che si rompa niente. `KYCHost.conferma` e' una macchina a stati: da
      «non_avviata» l'unica transizione ammessa e' verso «in_corso»
      (`fase143_kyc_host.py` `_TRANS`), quindi una conferma che arriva su uno stato non
      avviato **restituisce False e non scrive niente**. Il chiamante ignora quel False,
      scrive nel registro «KYC IDENTITY VERIFICATO» — una riga che dichiara il falso — e
      risponde 200. Succede ogni volta che il webhook arriva prima che l'avvio della
      sessione sia stato registrato: Stripe consegna in millisecondi, e quella gara e'
      normale. L'esito e' perso, il registro dice il contrario, e nessuno riprovera'.
      MISURATO il 2026-09-02 con `collaudi`-fuori (script di misura, non nel repository):
      tre consegne dello stesso evento, tre righe «KYC IDENTITY VERIFICATO» nel registro,
      stato prima «non_avviata» e stato dopo «non_avviata».

FILO COMUNE DEI QUATTRO. Tre volte su quattro il difetto e' lo stesso gesto: un metodo
dichiarato `-> bool` viene chiamato e il suo valore di ritorno **non viene guardato**. Un
booleano che nessuno legge non e' un esito: e' un commento.

COME E' INIETTATO IL GUASTO, e perche' cosi'. Il guasto sta nel COLLABORATORE (l'oggetto
`pagamenti_pendenti` / `kyc` del sistema), sostituito su questa istanza di prova — mai nel
codice sotto esame. Nessun `fase*.py` viene toccato, quindi non serve nessun ripristino
byte-identico e non c'e' nessuna finestra in cui un file di produzione resti rotto.

LA PREMESSA SI VERIFICA PRIMA DEL VERDETTO (sbaglio S7). Ogni prova controlla ANCHE che
l'esito sia davvero andato perso. Se un giorno il codice smettesse di perderlo, la prova
non deve accusare a vuoto: deve dire che la premessa non regge piu'.
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

WH = "whsec_esiti_persi"
# ⛔ VALORE FINTO, IN UNA COSTANTE E NON SCRITTO SUL POSTO. Il banco non chiama mai Stripe
# (`_fetch_reale` e' sostituito in `setUpClass`), quindi qui non serve nessuna chiave vera.
# Sta in una costante perche' `bandit` (B106) segnala un argomento il cui NOME contiene
# «secret» quando riceve un valore scritto sul posto; passandolo per variabile il rilievo non
# nasce, ed e' la stessa forma gia' usata qui sopra per `WH` -- che infatti non e' mai stato
# segnalato. ⚠️ E un rilievo NUOVO si chiude nel CODICE: la fotografia del cricchetto si rifa'
# solo per DIMINUIRE il debito, mai per assorbire una segnalazione appena creata. Le stesse
# righe negli altri collaudi non gridano perche' sono debito gia' congelato, non perche'
# siano piu' sane.
CHIAVE_FINTA = "sk"


class GuastoIniettato(Exception):
    """Sollevata dal COLLABORATORE sostituito, mai dal codice sotto esame."""


def _e_ritentabile(stato):
    """Stripe ritenta solo se la risposta NON e' 2xx. Questa e' la regola vera, e non
    coincide con «diverso da 200»: un 204 sarebbe altrettanto definitivo."""
    return not (200 <= int(stato) < 300)


class TestWebhookStripeEsitiPersi(unittest.TestCase):

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
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db", db_kyc=f"{d}/k.db",
            commissione_bps=1500, psp_bps=300, stripe_secret_key=CHIAVE_FINTA,
            stripe_webhook_secret=WH, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://b.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@ep.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.hid, self.tok = c["host_id"], c["token"]
        oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "C", "citta": "Roma", "prezzo_notte_cents": 20000,
                "capacita": 4, "tassa_pp_notte_cents": 200}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": oggi.isoformat(),
                "a": (oggi + datetime.timedelta(days=30)).isoformat(),
                "unita_totali": 1, "prezzo_netto_cents": 20000}, {"X-Host-Token": self.tok})
        self.rif = self._prenota(5, 7, "cli@ep.it")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    # ── attrezzi ────────────────────────────────────────────────────────────────
    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _prenota(self, da, a, email):
        oggi = datetime.date.today()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa",
                       "check_in": (oggi + datetime.timedelta(days=da)).isoformat(),
                       "check_out": (oggi + datetime.timedelta(days=a)).isoformat(),
                       "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": email})
        return b["riferimento"]

    def _posta(self, payload_dict):
        pl = json.dumps(payload_dict)
        return self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                               {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})

    def _evento_pagamento(self, rif, cs="cs_prova1", pi="pi_prova1"):
        return {"type": "checkout.session.completed",
                "data": {"object": {"id": cs, "payment_intent": pi,
                                    "metadata": {"riferimento": rif}}}}

    def _evento_identita(self, hid, stato="verified", eid="evt_id1"):
        return {"id": eid, "type": "identity.verification_session.verified",
                "data": {"object": {"status": stato, "metadata": {"host_id": hid}}}}

    def _pi_salvato(self, rif):
        """Il payment_intent come risulta ADESSO nel pendente. '' = non salvato."""
        info = self.sis.pagamenti_pendenti.info(rif) or {}
        try:
            return json.loads(info.get("corpo_json") or "{}").get("stripe_pi", "")
        except Exception:
            return ""

    # ── [1] SOLDI: il salvataggio del payment_intent ESPLODE ─────────────────────
    def test_se_il_payment_intent_non_si_salva_perche_esplode_stripe_deve_ritentare(self):
        def _esplode(*_a, **_k):
            raise GuastoIniettato("archivio dei pendenti bloccato")
        self.sis.pagamenti_pendenti.salva_stripe_session = _esplode

        stato, corpo = self._posta(self._evento_pagamento(self.rif))

        # PREMESSA prima del verdetto (S7): l'esito dev'essere davvero andato perso.
        self.assertEqual(
            self._pi_salvato(self.rif), "",
            "PREMESSA NON VALIDA: il payment_intent risulta salvato nonostante il guasto. "
            "Questa prova non sta piu' misurando il caso che dice di misurare.")

        self.assertTrue(
            _e_ritentabile(stato),
            "IL RIMBORSO E' PERSO E STRIPE NON RIPROVERA'. Il salvataggio di "
            "payment_intent e' fallito, quindi la scheda del rimborso dichiarera' "
            "'manca: payment_intent' e il pulsante non ci sara': restituire i soldi a "
            "questo ospite tornera' un lavoro a mano sul pannello Stripe. Rispondendo "
            "%s (corpo: %s) diciamo a Stripe che l'evento e' stato gestito, e la perdita "
            "diventa definitiva. Serve una risposta NON 2xx, perche' il retry di Stripe "
            "e' l'unica cosa che puo' ancora salvare quel dato." % (stato, corpo))

    # ── [2] SOLDI: il salvataggio NON esplode, ma NON salva ──────────────────────
    def test_se_il_salvataggio_dice_di_non_aver_salvato_non_si_risponde_2xx(self):
        chiamate = []

        def _non_salva(*a, **_k):
            chiamate.append(a)
            return False                      # il contratto del metodo: non ho salvato
        self.sis.pagamenti_pendenti.salva_stripe_session = _non_salva

        stato, corpo = self._posta(self._evento_pagamento(self.rif))

        # PREMESSA: il metodo dev'essere stato interrogato davvero.
        self.assertTrue(
            chiamate,
            "PREMESSA NON VALIDA: salva_stripe_session non e' stata nemmeno chiamata, "
            "quindi questa prova non attraversa il punto che dovrebbe sorvegliare.")
        self.assertEqual(self._pi_salvato(self.rif), "",
                         "PREMESSA NON VALIDA: risulta salvato qualcosa.")

        self.assertTrue(
            _e_ritentabile(stato),
            "ESITO IGNORATO. salva_stripe_session ha dichiarato di NON aver salvato "
            "(ritorno False) e il chiamante non guarda il valore di ritorno: il caso "
            "'non salvato' e' indistinguibile da 'salvato'. Qui non serve nemmeno un "
            "guasto — basta che il record non ci sia ancora quando l'evento arriva. "
            "Risposta ottenuta: %s (corpo: %s); serve NON 2xx." % (stato, corpo))

    # ── [3] IDENTITA': l'esito della verifica va perso ───────────────────────────
    def test_se_l_esito_kyc_va_perso_stripe_deve_ritentare(self):
        # ⛔ QUI NON SI METTE DA PARTE NIENTE. Un test che si toglie di mezzo da solo esce
        # dal rapporto come «messo da parte» e non lo rilegge piu' nessuno: e' il modo in
        # cui un controllo smette di controllare senza che niente diventi rosso (S7). E nel
        # merito sarebbe pure sbagliato: il collaboratore lo costruisce il `setUp` qui sopra
        # (`db_kyc`), quindi se manca e' il BANCO a essere rotto, non il prodotto -- e un
        # banco rotto si vede.
        # 📌 E questo commento evita DI PROPOSITO di nominare il costrutto che mette da parte
        # un test: `collaudi/caccia_finti_verdi.py` lo cerca come TESTO nel sorgente, commenti
        # compresi, quindi una riga che dichiara di NON usarlo verrebbe contata come se lo
        # usasse (sbaglio S6, misurato qui il 2026-09-02). Un commento non nomina il token
        # che gli attrezzi cercano, come non nomina la cifra (S17).
        self.assertIsNotNone(
            getattr(self.sis, "kyc", None),
            "BANCO ROTTO: il setUp costruisce il KYC passando `db_kyc`, quindi qui non "
            "puo' mancare. Se manca, questa prova non attraversa il ramo identity e non "
            "sta misurando niente: si ripara il banco, non si salta la prova.")
        prima = self.sis.kyc.stato(self.hid)

        def _esplode(*_a, **_k):
            raise GuastoIniettato("archivio KYC bloccato")
        self.sis.kyc.conferma = _esplode

        stato, corpo = self._posta(self._evento_identita(self.hid))

        # PREMESSA: l'esito dev'essere davvero rimasto quello di prima.
        self.assertEqual(
            self.sis.kyc.stato(self.hid), prima,
            "PREMESSA NON VALIDA: lo stato KYC e' cambiato nonostante il guasto.")

        self.assertTrue(
            _e_ritentabile(stato),
            "L'ESITO DELLA VERIFICA D'IDENTITA' E' PERSO PER SEMPRE. La conferma e' "
            "fallita, l'host resta '%s', e rispondendo %s (corpo: %s) diciamo a Stripe "
            "che l'evento e' stato gestito: non lo rimandera' mai piu'. Nessuno si "
            "accorgera' che quell'host aveva superato la verifica. Serve NON 2xx."
            % (prima, stato, corpo))

    # ── [4] IDENTITA': l'esito si perde SENZA NESSUN GUASTO ──────────────────────
    def test_una_conferma_rifiutata_dalla_macchina_a_stati_non_puo_rispondere_2xx(self):
        """Nessun guasto iniettato: e' il codice sano che perde l'esito.

        Da «non_avviata» la macchina a stati del KYC ammette solo «in_corso», quindi la
        conferma torna False senza scrivere. Il chiamante non guarda quel False, scrive a
        registro «KYC IDENTITY VERIFICATO» e risponde 200. La riga di registro dichiara il
        falso e l'esito e' perso per sempre."""
        # ⛔ QUI NON SI METTE DA PARTE NIENTE. Un test che si toglie di mezzo da solo esce
        # dal rapporto come «messo da parte» e non lo rilegge piu' nessuno: e' il modo in
        # cui un controllo smette di controllare senza che niente diventi rosso (S7). E nel
        # merito sarebbe pure sbagliato: il collaboratore lo costruisce il `setUp` qui sopra
        # (`db_kyc`), quindi se manca e' il BANCO a essere rotto, non il prodotto -- e un
        # banco rotto si vede.
        # 📌 E questo commento evita DI PROPOSITO di nominare il costrutto che mette da parte
        # un test: `collaudi/caccia_finti_verdi.py` lo cerca come TESTO nel sorgente, commenti
        # compresi, quindi una riga che dichiara di NON usarlo verrebbe contata come se lo
        # usasse (sbaglio S6, misurato qui il 2026-09-02). Un commento non nomina il token
        # che gli attrezzi cercano, come non nomina la cifra (S17).
        self.assertIsNotNone(
            getattr(self.sis, "kyc", None),
            "BANCO ROTTO: il setUp costruisce il KYC passando `db_kyc`, quindi qui non "
            "puo' mancare. Se manca, questa prova non attraversa il ramo identity e non "
            "sta misurando niente: si ripara il banco, non si salta la prova.")
        # PREMESSA: si parte da uno stato da cui la conferma NON e' ammessa, e la
        # macchina a stati dev'essere davvero d'accordo (se cambiasse, va rivista la prova).
        prima = self.sis.kyc.stato(self.hid)
        self.assertEqual(prima, "non_avviata",
                         "PREMESSA NON VALIDA: mi aspettavo uno stato non avviato.")
        self.assertFalse(
            self.sis.kyc.conferma(self.hid, "verificato"),
            "PREMESSA NON VALIDA: la conferma da questo stato ora riesce. La macchina a "
            "stati e' cambiata: questa prova va riscritta, non ignorata.")

        stato, corpo = self._posta(self._evento_identita(self.hid))

        self.assertEqual(
            self.sis.kyc.stato(self.hid), prima,
            "PREMESSA NON VALIDA: l'esito risulta applicato, quindi non e' andato perso.")

        self.assertTrue(
            _e_ritentabile(stato),
            "ESITO PERSO SENZA NESSUN GUASTO, E IL REGISTRO DICE IL CONTRARIO. La "
            "conferma e' stata rifiutata dalla macchina a stati (l'host e' rimasto '%s'), "
            "ma il chiamante non guarda il valore di ritorno: scrive «KYC IDENTITY "
            "VERIFICATO» e risponde %s (corpo: %s). Succede ogni volta che il webhook "
            "arriva prima che l'avvio della sessione sia registrato, ed e' una gara "
            "normale. Serve NON 2xx, perche' il retry di Stripe e' l'unica cosa che puo' "
            "ancora applicare quell'esito." % (prima, stato, corpo))


if __name__ == "__main__":
    unittest.main(verbosity=2)
