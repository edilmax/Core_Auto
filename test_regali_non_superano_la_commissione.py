"""GUARDIA — la somma dei regali su UNA prenotazione non supera la commissione (B11).

⛔ IL DIFETTO, misurato il 2026-08-23. Su una prenotazione la piattaforma puo' regalare
DUE volte dalla stessa commissione, e i due tetti non si parlano:

  · lo sconto all'OSPITE (Credito Viaggio / Credito Fondatore) e' tagliato al margine
    `comm - costo` in `fase59_concierge._sconto_credito` (riga 503);
  · il credito dell'HOST (referral / benvenuto viral) e' tagliato dal parametro passato
    a `_applica_credito_host`, che in `fase83_server.py:8170` e' la commissione **LORDA**
    (`dj["commissione_cents"]`) -- cioe' la stessa da cui abbiamo GIA' finanziato lo
    sconto dell'ospite.

Risultato: su 300,00 con host a regime la somma regalata e' 18,00 + 30,00 = 48,00 contro
una commissione di 30,00, e il saldo della piattaforma va **negativo** (misurato: -8,13
su carta europea, -13,06 su carta internazionale; il fondo di tutta la banda e' -23,31
su una prenotazione da 500,00).

⛔ LA GUARDIA STA SU CHI CHIAMA, NON SU `_applica_credito_host` (regola ferrea 11: «il
difetto e' spesso in chi chiama, non nel pezzo che mostra il sintomo»). Il metodo fa
esattamente quello che gli si chiede: e' il numero che riceve a essere sbagliato. Per
questo il collaudo entra da `_conferma_pagamento`, che e' il punto in cui il webhook
Stripe fa scattare i passi derivati del pagamento.

⛔ E ASSERISCE UN EFFETTO, NON L'ASSENZA DI ECCEZIONI. `_conferma_pagamento` isola i
guasti in un `except` che degrada a warning: un collaudo che si accontentasse di «non ha
sollevato» sarebbe verde anche se il flusso morisse alla prima riga (sbaglio S7, «un
controllo che da' OK quando la premessa manca»). Qui si misura quanto credito e' stato
CONSUMATO davvero dal registro viral, che e' un numero che esiste solo se il flusso e'
arrivato in fondo.

Vista ROSSA sul codice di produzione prima della riparazione (D20 passo 2).
"""
import json
import shutil
import tempfile
import unittest

from fase76_viral_loop import crea_viral_loop

# La prenotazione del caso peggiore, in centesimi interi.
NETTO_CENTS = 30000          # 300,00 di soggiorno
COMMISSIONE_CENTS = 3000     # 10% a regime, quello che l'host paga a noi
SCONTO_OSPITE_CENTS = 1800   # gia' regalato all'ospite dal Credito Viaggio (fase59:503)
CREDITO_HOST_CENTS = 5000    # 10,00 di benvenuto + 40,00 di premio referral (fase81:56-57)

# Quel che resta da poter regalare all'host DOPO lo sconto gia' dato all'ospite.
MARGINE_RESIDUO_CENTS = COMMISSIONE_CENTS - SCONTO_OSPITE_CENTS      # 1200


class _PayoutFinto:
    """Il minimo che `_conferma_pagamento` usa davvero, piu' la memoria di cosa e' stato
    aumentato: `aumenta_payout` DEVE tornare True, perche' se torna False il codice di
    produzione considera il credito perso e ritorna 0 (ramo di compensazione)."""

    def __init__(self):
        self.aumenti = []

    def aggiorna_stato(self, prenotazione_id, nuovo):
        return True

    def aumenta_payout(self, prenotazione_id, delta_cents):
        self.aumenti.append(int(delta_cents))
        return True

    def conta_pagati(self, host_id):
        return 0        # sotto la soglia: il premio referral non deve scattare qui


class _PendentiFinti:
    """`conferma` e' un CAS che scrive 'pagato' e torna lo stato PRECEDENTE."""

    def __init__(self, rec):
        self._rec = rec

    def conferma(self, riferimento):
        return dict(self._rec)

    def info(self, riferimento):
        return dict(self._rec)


class _SysFinto:
    def __init__(self, viral, payout, pendenti):
        self.viral = viral
        self.payout = payout
        self.pagamenti_pendenti = pendenti
        # tutto il resto e' assente di proposito: il codice di produzione lo legge con
        # getattr(..., None) e degrada, e cosi' il collaudo misura SOLO l'incrocio dei due
        # crediti invece di trascinarsi dietro mezzo sistema.
        self.config = None


class TestIRegaliNonSuperanoLaCommissione(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.viral = crea_viral_loop(self.dir + "/viral.db", b"S" * 32)
        # l'host si e' guadagnato onestamente 50,00 di credito: benvenuto + premio referral
        codice = self.viral.genera_codice("referente1")
        self.assertTrue(codice, "premessa non valida: nessun codice referral generato")
        self.assertTrue(self.viral.registra_referee(codice, "host1").ok,
                        "premessa non valida: referee non registrato")
        # porto il credito dell'host esattamente a CREDITO_HOST_CENTS, qualunque sia il
        # benvenuto di configurazione: il collaudo non deve dipendere da quel default.
        avuto = self.viral.credito_disponibile("host1")
        if avuto < CREDITO_HOST_CENTS:
            cod2 = self.viral.genera_codice("host1")
            self.viral.registra_referee(cod2, "invitato_di_host1")
            self.viral.qualifica_referee("invitato_di_host1",
                                         premio_cents=CREDITO_HOST_CENTS - avuto)
        self.credito_iniziale = self.viral.credito_disponibile("host1")
        self.assertGreaterEqual(
            self.credito_iniziale, CREDITO_HOST_CENTS,
            "premessa non valida: l'host non ha il credito che il collaudo vuole provare")

        corpo = {"host_id": "host1", "valuta": "EUR",
                 "prezzo_netto_cents": NETTO_CENTS,
                 "totale_cents": NETTO_CENTS - SCONTO_OSPITE_CENTS,
                 "commissione_cents": COMMISSIONE_CENTS,
                 "sconto_credito_cents": SCONTO_OSPITE_CENTS,
                 "costo_pagamento_cents": 1435}
        self.rec = {"riferimento": "REF1", "stato": "in_attesa", "host_id": "host1",
                    "alloggio_id": "casa1", "check_in": "2030-01-10",
                    "check_out": "2030-01-12", "tassa_cents": 0, "comune": "",
                    "corpo_json": json.dumps(corpo)}
        self.payout = _PayoutFinto()
        self.sys = _SysFinto(self.viral, self.payout, _PendentiFinti(self.rec))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _conferma(self):
        from fase83_server import RouterHTTP
        r = RouterHTTP.__new__(RouterHTTP)      # solo il metodo sotto collaudo
        r._sys = self.sys
        r._conferma_pagamento("REF1")
        return self.credito_iniziale - self.viral.credito_disponibile("host1")

    def test_il_credito_host_non_puo_regalare_cio_che_e_gia_andato_all_ospite(self):
        """⛔ IL CUORE. Dalla commissione di 30,00 ne sono gia' usciti 18,00 verso
        l'ospite: all'host ne possono restare al massimo 12,00, non 30,00."""
        consumato = self._conferma()
        # PREMESSA, non tesi: se il flusso non e' arrivato in fondo non ha consumato
        # niente, e un collaudo che tacesse qui sarebbe un verde finto (S7).
        self.assertGreater(consumato, 0,
                           "MISURA NON VALIDA: nessun credito consumato, il flusso non e' "
                           "arrivato a _applica_credito_host -- questo collaudo non ha "
                           "misurato niente")
        self.assertLessEqual(
            consumato, MARGINE_RESIDUO_CENTS,
            "REGALO OLTRE LA COMMISSIONE: all'host sono stati scalati %d cent di credito "
            "mentre della commissione (%d) ne restavano solo %d, perche' %d erano gia' "
            "andati all'ospite. Somma regalata: %d su una commissione di %d."
            % (consumato, COMMISSIONE_CENTS, MARGINE_RESIDUO_CENTS, SCONTO_OSPITE_CENTS,
               consumato + SCONTO_OSPITE_CENTS, COMMISSIONE_CENTS))

    def test_la_somma_dei_due_regali_non_supera_la_commissione(self):
        """La stessa cosa detta come invariante, che e' la forma in cui va letta:
        sconto_ospite + credito_host <= commissione. Sotto questa riga il saldo della
        piattaforma resta almeno pari alla tariffa tecnica meno il costo Stripe."""
        consumato = self._conferma()
        self.assertGreater(consumato, 0, "MISURA NON VALIDA: nessun credito consumato")
        self.assertLessEqual(
            SCONTO_OSPITE_CENTS + consumato, COMMISSIONE_CENTS,
            "la somma dei regali (%d) supera la commissione (%d): su questa prenotazione "
            "la piattaforma paga di tasca propria %d cent"
            % (SCONTO_OSPITE_CENTS + consumato, COMMISSIONE_CENTS,
               SCONTO_OSPITE_CENTS + consumato - COMMISSIONE_CENTS))

    def test_il_payout_dell_host_cresce_di_quanto_gli_e_stato_scalato(self):
        """Cablaggio (collaudo 2): il credito consumato deve ARRIVARE al payout, non
        sparire. Senza questa, un tetto messo male potrebbe bruciare il credito dell'host
        senza dargli niente in cambio -- il ramo che il codice di produzione chiama
        «CREDITO REFERRAL PERSO»."""
        consumato = self._conferma()
        self.assertGreater(consumato, 0, "MISURA NON VALIDA: nessun credito consumato")
        self.assertEqual([consumato], self.payout.aumenti,
                         "il credito scalato all'host non e' finito nel suo payout")

    def test_ANCHE_la_conferma_immediata_rispetta_il_tetto(self):
        """⛔ IL PUNTO DI CHIAMATA E' DOPPIO, e questo e' l'altro.

        `_registra_payout` (conferma immediata / su-richiesta approvata, senza pagamento
        online) scala il credito dell'host per conto suo. Ripararne uno solo avrebbe
        lasciato il difetto vivo su questa strada, e nessun collaudo se ne sarebbe
        accorto: e' la regola #23 letta al contrario -- due cablaggi per la stessa regola,
        e uno che nessuno guarda."""
        corpo = json.loads(self.rec["corpo_json"])
        corpo["netto_host_cents"] = 25565
        corpo["tassa_soggiorno_cents"] = 0
        corpo.pop("payment_url", None)          # niente pagamento online -> ramo 'maturato'

        class _Catalogo:
            @staticmethod
            def host_di_alloggio(allog):
                return "host1"

        class _PayoutImmediato(_PayoutFinto):
            def registra_maturato(self, ref, host, minori, valuta):
                return True

        self.sys.payout = _PayoutImmediato()
        self.sys.catalogo = _Catalogo()
        from fase83_server import RouterHTTP
        r = RouterHTTP.__new__(RouterHTTP)
        r._sys = self.sys
        r._registra_payout("REF2", "casa1", corpo)
        consumato = self.credito_iniziale - self.viral.credito_disponibile("host1")
        self.assertGreater(consumato, 0,
                           "MISURA NON VALIDA: nessun credito consumato, _registra_payout "
                           "non e' arrivato a _applica_credito_host")
        self.assertLessEqual(
            consumato, MARGINE_RESIDUO_CENTS,
            "REGALO OLTRE LA COMMISSIONE sulla CONFERMA IMMEDIATA: scalati %d cent "
            "mentre ne restavano %d (%d gia' andati all'ospite)"
            % (consumato, MARGINE_RESIDUO_CENTS, SCONTO_OSPITE_CENTS))

    def test_senza_sconto_all_ospite_il_tetto_resta_la_commissione_piena(self):
        """L'altra direzione (regola ferrea 10 / D18 punto 2): la guardia non deve
        stringere dove non serve. Se all'ospite non e' andato niente, all'host spetta
        tutta la commissione."""
        corpo = json.loads(self.rec["corpo_json"])
        corpo["sconto_credito_cents"] = 0
        corpo["totale_cents"] = NETTO_CENTS
        self.rec["corpo_json"] = json.dumps(corpo)
        self.sys.pagamenti_pendenti = _PendentiFinti(self.rec)
        consumato = self._conferma()
        self.assertEqual(consumato, COMMISSIONE_CENTS,
                         "senza sconto all'ospite l'host deve poter usare tutta la "
                         "commissione: attesi %d, scalati %d"
                         % (COMMISSIONE_CENTS, consumato))


if __name__ == "__main__":
    unittest.main()
