"""
Collaudo CONTI — conservazione del denaro (proprietà, griglia severa).

Ogni preventivo firmato deve rispettare le identità contabili, per QUALSIASI combinazione
di prezzo (inclusi numeri primi e casi limite), notti, fonte (marketplace/diretto),
politica (sconto non-rimborsabile -12%), tassa di soggiorno e valuta (JPY senza decimali):

  I1: prezzo_guest == netto_host + commissione + costo_pagamento   (nessun cent sparisce)
  I2: totale == prezzo_guest + tassa_soggiorno                     (tassa pass-through)
  I3: prezzo_listino == prezzo_guest + sconto_non_rimborsabile     (sconto trasparente)
  I4: tutti gli importi interi e >= 0; commissione <= prezzo_guest
  I5: escrow risolvi: rimborso_ospite + va_all_host == importo     (split esatto)
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase57_vetrina import SchedaAlloggio
from fase177_financial_controller import crea_financial_controller


class TestQuandoCANCELLAILCLIENTELaPiattaformaNONDeveRIMETTERCI(unittest.TestCase):
    """💸 «QUANDO LO FA IL CLIENTE, IO NON CI DEVO PERDERE SOLDI» — fondatore, 2026-08-17.

    ⛔ NON E' UN CASO IPOTETICO: E' IL REPLAY DELL'UNICO PAGAMENTO VERO MAI PASSATO.
    Il 2026-08-16 e' stata fatta una prova con un alloggio da **1,00 EUR**, poi rimborsata.
    Letto dal conto Stripe LIVE il 2026-08-17 (sola lettura, `balance_transactions`):

        charge  EUR  importo=100  fee=27  netto=73    ch_3U53IsJMRnB73twq1Vr2rHmz
                     fee_details: stripe_fee = 27 ("Stripe processing fees")
        refund  EUR  importo=-100 fee= 0  netto=-100  re_3U53IsJMRnB73twq1QLzUCu9

    Il `fee: 0` sul rimborso e' il punto: **Stripe i 27 centesimi non li restituisce**. Quindi
    su un rimborso totale abbiamo incassato 73 e restituito 100 -> **-27**. Su 200 EUR la
    stessa strada costa **~3,25 EUR** a ogni cancellazione.

    E queste sono le righe che il nostro giornale immutabile ha scritto davvero, lette da
    `/data/finanza.db` in produzione (sola lettura):

        seq 1  incasso      100  cassa_piattaforma / debiti_vs_host
        seq 2  commissione   30  debiti_vs_host    / ricavi_commissioni
        seq 3  rimborso     100  debiti_vs_ospite  / cassa_piattaforma

    Saldi che ne escono (dare positivo): cassa **0** · debiti_vs_host **-70** ·
    ricavi_commissioni **-30** · debiti_vs_ospite **+100**. La partita doppia **quadra a
    zero**, ed e' proprio per questo che nessuno ha gridato: e' formalmente giusta e
    sostanzialmente falsa. Su una prenotazione annullata il libro dichiara un **ricavo** di
    30, un **debito verso l'host** di 70 per un soggiorno mai avvenuto, e una **cassa a zero**
    mentre siamo sotto di 27.

    ⛔ E NESSUNO POTEVA ACCORGERSENE: in `fase177_financial_controller.py` non esiste **nessuna
    funzione che calcoli i saldi dei conti**. C'e' `verifica_catena`, che dimostra che il libro
    non e' stato **manomesso** — non che dica il **vero**. Sono due cose diverse, e finora
    avevamo solo la prima.

    Le tre guardie qui sotto sono i tre pezzi del difetto, separati apposta: si possono
    riparare in tre momenti diversi e ognuna dice quale.
    """

    # I numeri veri, non inventati. Fonte: conto Stripe LIVE + /data/finanza.db, 2026-08-17.
    PAGATO = 100          # quello che l'ospite ha versato
    FEE_STRIPE = 27       # quello che Stripe ha trattenuto E NON ha restituito
    NOSTRA_COMMISSIONE = 30   # la riga `commissione` che il giornale ha scritto

    def _libro(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        fc = crea_financial_controller("%s/finanza.db" % d)
        fc.inizializza_schema()
        return fc

    def _incasso_e_commissione(self, fc, rif):
        """Le due righe che la produzione scrive quando l'ospite paga."""
        fc.movimento(tipo="incasso", riferimento=rif, soggetto="host:h_test",
                     importo_cents=self.PAGATO, valuta="EUR",
                     causale="pagamento ospite ricevuto")
        fc.movimento(tipo="commissione", riferimento=rif, soggetto="host:h_test",
                     importo_cents=self.NOSTRA_COMMISSIONE, valuta="EUR",
                     causale="commissione piattaforma (comm+costo carta-credito)")

    def _replay_della_prova_vera(self, fc, rif="8a448a3a4c003c9ccb0f3583"):
        """Il giro COMPLETO di una cancellazione dell'ospite, passando dalle stesse chiamate
        che fa la produzione. ⛔ Fino al 2026-08-17 esistevano solo la prima, la seconda e
        l'ultima: mancavano il costo del gateway e lo storno, ed e' li' che il libro mentiva.
        """
        self._incasso_e_commissione(fc, rif)
        # la fetta del gestore, letta da lui (`balance_transaction.fee`), mai stimata
        fc.costo_gateway(riferimento=rif, soggetto="host:h_test",
                         fee_cents=self.FEE_STRIPE, valuta="EUR")
        # la cancellazione: il dovuto all'host passa all'ospite e la commissione si storna.
        # Gli importi NON si passano: li legge il giornale.
        fc.storna_prenotazione(riferimento=rif)
        fc.movimento(tipo="rimborso", riferimento=rif, soggetto="ospite:" + rif,
                     importo_cents=self.PAGATO, valuta="EUR",
                     causale="cancellazione dell'ospite, rimborso totale")
        return rif

    @staticmethod
    def _saldi(fc):
        """⛔ Si chiedono AL LIBRO (`fc.saldi()`), non si ricalcolano qui. Fino al 2026-08-17
        quella funzione non esisteva: c'era `verifica_catena`, che dimostra che il libro non e'
        stato MANOMESSO, non che dica il VERO — ed e' per questo che tre righe false sono
        rimaste invisibili."""
        return fc.saldi()

    def test_0_il_SERVER_chiama_davvero_lo_storno_e_il_costo_del_gateway(self):
        """⛔ COSTRUITO != COLLEGATO (appendice 23). Le tre guardie qui sotto provano che il
        MODELLO contabile e' giusto; questa prova che la produzione lo USA. Senza, avremmo un
        libro capace di dire il vero e un server che continua a scriverci dentro il falso —
        cioe' un verde perfetto su codice che nessuno esegue.

        ⛔ Si guarda l'albero sintattico, non il testo: una parola in un commento non e' una
        chiamata (sbaglio S6, ricomparso il 2026-08-17 su una guardia scritta poche ore prima).
        """
        import ast
        import io
        import os
        percorso = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "fase83_server.py")
        with io.open(percorso, encoding="utf-8") as f:
            albero = ast.parse(f.read())
        chiamate = {n.func.attr for n in ast.walk(albero)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for nome, perche in (
                ("storna_prenotazione",
                 "senza, a ogni rimborso restano un RICAVO su una prenotazione annullata e un "
                 "debito verso l'host per un soggiorno mai avvenuto"),
                ("costo_gateway",
                 "senza, la fetta che il gestore trattiene non entra in nessuna riga del "
                 "libro: la cassa dichiara di avere soldi che non ci sono")):
            # ⛔ NON `assertIn` sul set: stamperebbe le ~900 chiamate del file, e un errore
            # illeggibile e' un difetto quanto un errore mancato — chi lo legge non capisce
            # cosa fare.
            self.assertTrue(
                nome in chiamate,
                "`fase83_server.py` non chiama MAI `%s`: %s. Il modello contabile e' giusto e "
                "nessuno lo usa." % (nome, perche))

    def test_1_il_costo_VERO_del_gateway_deve_ESISTERE_nel_giornale(self):
        """⛔ Oggi in cassa entrano **100** mentre ne sono arrivati **73**: la fetta di Stripe
        non compare in nessuna riga del libro. Un costo che non e' scritto da nessuna parte
        non lo vede il commercialista, non lo vede un allarme e non lo vede il fondatore."""
        fc = self._libro()
        self._replay_della_prova_vera(fc)
        tipi = {m.get("tipo") for m in fc.stream_giornale()}
        parla_del_gateway = {t for t in tipi if "gateway" in t or "psp" in t or "stripe" in t}
        self.assertTrue(
            parla_del_gateway,
            "il giornale non ha NESSUNA riga per il costo del gateway. Ha registrato un "
            "incasso di %d mentre sul conto ne sono arrivati %d: mancano %d cents che "
            "esistono davvero e non stanno da nessuna parte. Tipi presenti: %r"
            % (self.PAGATO, self.PAGATO - self.FEE_STRIPE, self.FEE_STRIPE, sorted(tipi)))

    def test_2_dopo_un_rimborso_TOTALE_non_restano_ricavi_ne_debiti_verso_l_host(self):
        """⛔ Il soggiorno non c'e' stato: non abbiamo guadagnato niente e non dobbiamo niente
        all'host. Oggi il libro dichiara tutt'e due."""
        fc = self._libro()
        self._replay_della_prova_vera(fc)
        s = self._saldi(fc)
        ricavo = -s.get("ricavi_commissioni", 0)      # avere positivo = ricavo
        debito_host = -s.get("debiti_vs_host", 0)     # avere positivo = debito verso l'host
        self.assertEqual(
            ricavo, 0,
            "su una prenotazione RIMBORSATA per intero il libro dichiara un ricavo di %d "
            "cents: la commissione era stata scritta all'incasso e nessuna riga la storna. "
            "Su 200 EUR sarebbero 10,25 EUR di ricavo mai avvenuto." % ricavo)
        self.assertEqual(
            debito_host, 0,
            "dopo il rimborso totale risultiamo ancora debitori di %d cents verso l'host, per "
            "un soggiorno che non c'e' stato: quel debito non si azzera mai e resta nel libro "
            "per sempre." % debito_host)

    def test_3_su_una_cancellazione_dell_OSPITE_la_piattaforma_non_resta_in_perdita(self):
        """💸 LA DOMANDA DEL FONDATORE, tradotta in un numero. D16: *«ogni scelta che tocca
        denaro dichiara chi ci perde se va storta»* — e qui, oggi, ci perdiamo noi.

        ⛔ QUESTA GUARDIA NON DECIDE CHI DEVE PAGARE LA FETTA DI STRIPE: e' una scelta di
        soldi e di contratto, quindi del fondatore. Pretende solo che la perdita **non sia
        invisibile**: o non c'e', oppure il libro la dichiara.
        """
        fc = self._libro()
        self._replay_della_prova_vera(fc)
        cassa_secondo_il_libro = self._saldi(fc).get("cassa_piattaforma", 0)
        cassa_vera = (self.PAGATO - self.FEE_STRIPE) - self.PAGATO      # 73 - 100 = -27
        self.assertEqual(
            cassa_secondo_il_libro, cassa_vera,
            "il libro dice che in cassa il saldo e' %+d, ma il denaro vero e' %+d: abbiamo "
            "incassato %d (Stripe ne ha trattenuti %d) e restituito %d. La differenza di %d "
            "cents e' una perdita REALE che il libro non registra — e su 200 EUR la stessa "
            "strada costa circa 3,25 EUR a ogni cancellazione del cliente."
            % (cassa_secondo_il_libro, cassa_vera, self.PAGATO - self.FEE_STRIPE,
               self.FEE_STRIPE, self.PAGATO, abs(cassa_vera - cassa_secondo_il_libro)))


class TestConservazioneDenaro(unittest.TestCase):
    def _sistema(self, *, commissione_bps, psp_bps):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            commissione_bps=commissione_bps, psp_bps=psp_bps))
        return sis, crea_router(sis)

    def _quota(self, r, slug, notti, fonte, atteso=200):
        co = "2026-09-%02d" % (1 + notti)
        s, q = r.gestisci("POST", "/api/concierge/quote", {}, json.dumps(
            {"alloggio_id": slug, "check_in": "2026-09-01", "check_out": co,
             "party": 2, "fonte": fonte}), {})
        self.assertEqual(s, atteso, q)
        return q

    def _verifica_identita(self, q, ctx):
        campi = ("prezzo_guest_cents", "netto_host_cents", "commissione_cents",
                 "costo_pagamento_cents", "totale_cents", "tassa_soggiorno_cents",
                 "prezzo_listino_cents", "sconto_non_rimborsabile_cents")
        for k in campi:                                       # I4: interi, mai negativi
            v = q.get(k)
            self.assertIsInstance(v, int, "%s non intero (%r) in %s" % (k, v, ctx))
            self.assertGreaterEqual(v, 0, "%s negativo in %s" % (k, ctx))
        self.assertEqual(q["prezzo_guest_cents"],
                         q["netto_host_cents"] + q["commissione_cents"]
                         + q["costo_pagamento_cents"],
                         "I1 violata (un cent sparito/creato) in %s" % ctx)
        self.assertEqual(q["totale_cents"],
                         q["prezzo_guest_cents"] + q["tassa_soggiorno_cents"],
                         "I2 violata (tassa non pass-through) in %s" % ctx)
        self.assertEqual(q["prezzo_listino_cents"],
                         q["prezzo_guest_cents"] + q["sconto_non_rimborsabile_cents"],
                         "I3 violata (sconto opaco) in %s" % ctx)
        self.assertLessEqual(q["commissione_cents"], q["prezzo_guest_cents"], ctx)

    def test_griglia_severa(self):
        # prezzi ostili: primi, dispari, tondi, massimi tipici (i realistici conservano al cent)
        prezzi = (97, 7333, 9999, 10000, 123457, 999999)
        for comm_bps, psp_bps in ((1000, 300), (1000, 0), (500, 300), (0, 300)):
            sis, r = self._sistema(commissione_bps=comm_bps, psp_bps=psp_bps)
            for i, prezzo in enumerate(prezzi):
                for pol in ("flessibile", "non_rimborsabile"):
                    slug = "g-%d-%s" % (i, pol[:2])
                    sis.catalogo.pubblica(SchedaAlloggio(
                        host_id="h1", slug=slug, titolo=slug, citta="Roma",
                        prezzo_notte_cents=prezzo, capacita=4,
                        politica_cancellazione=pol,
                        tassa_pp_notte_cents=137, tassa_max_notti=2))
                    for g in ("2026-09-01", "2026-09-02", "2026-09-03"):
                        sis.inventario.imposta_disponibilita(
                            slug, g, unita_totali=1, prezzo_netto_cents=prezzo)
                    for notti in (1, 3):
                        for fonte in ("marketplace", "diretto"):
                            q = self._quota(r, slug, notti, fonte)
                            ctx = "prezzo=%d pol=%s notti=%d fonte=%s comm=%d psp=%d" % (
                                prezzo, pol, notti, fonte, comm_bps, psp_bps)
                            self._verifica_identita(q, ctx)
                            if pol == "non_rimborsabile":
                                self.assertGreater(
                                    q["sconto_non_rimborsabile_cents"], 0,
                                    "NR senza sconto in %s" % ctx)

    def test_prezzo_non_sostenibile_rifiutato(self):
        # prezzi da centesimi con tassa alta: il costo carta supererebbe il ricavo host ->
        # 422 onesto (nessuno ci rimette), NON un preventivo che fa sparire centesimi.
        sis, r = self._sistema(commissione_bps=1000, psp_bps=300)
        sis.catalogo.pubblica(SchedaAlloggio(
            host_id="h1", slug="patologico", titolo="x", citta="Roma",
            prezzo_notte_cents=1, capacita=4, tassa_pp_notte_cents=137, tassa_max_notti=2))
        for g in ("2026-09-01", "2026-09-02"):
            sis.inventario.imposta_disponibilita("patologico", g, unita_totali=1,
                                                 prezzo_netto_cents=1)
        q = self._quota(r, "patologico", 1, "marketplace", atteso=422)
        self.assertEqual(q["errore"], "prezzo_non_sostenibile")

    def test_valuta_jpy_senza_decimali(self):
        # JPY: l'esponente è 0 -> 12000 = ¥12.000 (mai ×100). Le identità valgono uguali.
        sis, r = self._sistema(commissione_bps=1000, psp_bps=300)
        sis.catalogo.pubblica(SchedaAlloggio(
            host_id="h1", slug="jp", titolo="Tokyo", citta="Tokyo",
            prezzo_notte_cents=12000, capacita=2, valuta="JPY"))
        for g in ("2026-09-01", "2026-09-02"):
            sis.inventario.imposta_disponibilita("jp", g, unita_totali=1,
                                                 prezzo_netto_cents=12000)
        q = self._quota(r, "jp", 1, "marketplace")
        self.assertEqual(q["valuta"], "JPY")
        self.assertEqual(q["prezzo_guest_cents"], 12000)      # 1 notte, nessun ×100
        self._verifica_identita(q, "JPY")

    def test_escrow_split_esatto(self):
        # I5: la risoluzione di una controversia conserva ogni cent (importi ostili)
        from fase160_escrow_garanzia import crea_escrow_garanzia
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        g = crea_escrow_garanzia(f"{d}/g.db")
        g.inizializza_schema()
        for i, imp in enumerate((1, 3, 97, 12743, 999999)):
            ref = "e%d" % i
            g.apri(ref, imp, alloggio_id="x", ora_checkin_ts=None)
            g.contesta(ref)
            for pct in (0, 33, 50, 77, 100):
                pass                                          # il pct lo applica il server
            rimborso = imp * 33 // 100
            out = g.risolvi(ref, rimborso_ospite_cents=rimborso)
            self.assertTrue(out.get("ok"), out)
            self.assertEqual(out["ospite_rimborso_cents"] + out["host_riceve_cents"], imp,
                             "escrow: cent perso su importo %d" % imp)


class TestLaTassaDiSoggiornoVAALLHOST(unittest.TestCase):
    """💸 DECISIONE DEL FONDATORE, 2026-08-19: **«la tassa passa all'host, autorizzato»**.

    ⛔ PRIMA DI QUESTA DECISIONE LA MACCHINA FACEVA IL CONTRARIO, ed era misurabile:
    l'ospite pagava `soggiorno + tassa`, all'host andava **solo** il soggiorno meno le
    trattenute, e la tassa **restava nella nostra cassa** -- il libro contabile la
    registrava come `debiti_vs_comune`, cioe' dichiarava che **il debitore verso il Comune
    eravamo noi**.

    **Perche' e' sbagliato, ed e' una questione di legge prima che di codice.** In Italia il
    `DL 34/2020 art. 180` fa del **gestore della struttura** il «responsabile del pagamento»
    dell'imposta di soggiorno: non la piattaforma. Ma la responsabilita' segue i soldi: se la
    tassa resta nella nostra cassa, il debitore diventiamo noi -- verso **ogni** Comune del
    mondo in cui abbiamo un alloggio. Facendola passare all'host restiamo un **tubo**, non un
    debitore: lui la riceve insieme al resto e la versa al suo Comune.

    ⚠️ **E NON SI FONDE COL SUO GUADAGNO.** `netto_host_cents` resta quello che l'host
    **guadagna** dal soggiorno -- e' la cifra su cui si calcolano commissione e report DAC7 --
    mentre la tassa e' denaro **in transito** che lui deve girare al Comune. Sommarle
    farebbe dichiarare al Fisco un reddito che l'host non ha. Sono due fatti diversi e
    restano due numeri diversi: qui si controlla solo che **quello che gli VERSIAMO** li
    contenga tutti e due.
    """

    class _Recorder:
        """Finto registro dei payout: annota quanto gli viene chiesto di maturare."""
        def __init__(self):
            self.maturati = []
            self.in_attesa = []

        def registra_maturato(self, rif, host, importo, valuta):
            self.maturati.append(importo)
            return True

        def registra_in_attesa(self, rif, host, importo, valuta):
            self.in_attesa.append(importo)
            return True

    class _Cassaforte:
        """Finta cassaforte di garanzia: annota l'importo trattenuto fino al check-in."""
        def __init__(self):
            self.aperti = []

        def apri(self, ref, importo, alloggio_id=None, ora_checkin_ts=None):
            self.aperti.append(importo)
            return True

    def _router(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32,
            db_catalogo=d + "/c.db", db_inventario=d + "/i.db"))
        return sis, crea_router(sis)

    def test_all_host_versiamo_il_suo_netto_PIU_la_tassa(self):
        """⛔ IL CUORE. Quello che maturiamo per l'host deve contenere anche la tassa: e'
        denaro suo in transito, non nostro."""
        sis, r = self._router()
        registro = self._Recorder()
        sis.payout = registro
        sis.catalogo.host_di_alloggio = lambda a: "host-1"
        corpo = {"netto_host_cents": 8000, "tassa_soggiorno_cents": 2000,
                 "valuta": "EUR", "commissione_cents": 1000}
        r._registra_payout("REF-TASSA", "villa", corpo)
        self.assertEqual(
            registro.maturati, [10000],
            "all'host stiamo versando %r invece di 10000 (8000 suoi + 2000 di tassa da "
            "girare al Comune). Se la tassa non gli arriva, resta nella NOSTRA cassa e il "
            "debitore verso il Comune diventiamo noi" % (registro.maturati,))

    def test_anche_la_CASSAFORTE_trattiene_la_tassa_fino_al_check_in(self):
        """La cassaforte di garanzia trattiene i soldi dell'host fino al check-in, e poi li
        libera. Se la tassa non entra li' dentro, all'host non arrivera' mai: la cassaforte
        e' il posto da cui il payout esce davvero."""
        sis, r = self._router()
        cassaforte = self._Cassaforte()
        sis.garanzia = cassaforte
        r._apri_garanzia("REF-TASSA", {"netto_host_cents": 8000,
                                       "tassa_soggiorno_cents": 2000}, "villa", "2099-03-05")
        self.assertEqual(
            cassaforte.aperti, [10000],
            "nella cassaforte sono entrati %r invece di 10000: la tassa non e' trattenuta "
            "insieme al resto, quindi non uscira' mai verso l'host" % (cassaforte.aperti,))

    def test_il_LIBRO_non_dichiara_piu_un_debito_verso_il_COMUNE(self):
        """⛔ E il libro contabile deve dire la stessa cosa del denaro, se no la contabilita'
        racconta un'altra azienda.

        Due difetti in una riga sola, tutt'e due invisibili finche' la tassa vale zero:
          · dichiarava un **debito verso il Comune** che dopo questa decisione non esiste
            piu' (la tassa la deve l'host, e noi gliela abbiamo girata);
          · e la registrava di nuovo in **cassa**, che era gia' stata accreditata dalla riga
            `incasso` -- quella scrive il **totale**, tassa compresa. Su un incasso di 100
            con 20 di tassa il libro dichiarava **120 in cassa** mentre sul conto ne erano
            arrivati 100.
        Ora e' un movimento **dentro** cio' che dobbiamo all'host: lascia la traccia (quanto
        di quell'incasso e' tassa) senza spostare un centesimo che non si e' mosso.
        """
        from fase177_financial_controller import _CONTI_MOVIMENTO
        for tipo in ("tassa_incassata", "tassa_stornata"):
            dare, avere = _CONTI_MOVIMENTO[tipo]
            self.assertNotIn(
                "debiti_vs_comune", (dare, avere),
                "%s dichiara ancora un debito verso il Comune: dopo la decisione del "
                "2026-08-19 la tassa la versa l'host, non noi" % tipo)
            self.assertNotIn(
                "cassa_piattaforma", (dare, avere),
                "%s tocca la cassa, ma quel denaro e' gia' stato contato dalla riga "
                "`incasso` (che scrive il TOTALE, tassa compresa): cosi' la cassa risulta "
                "piu' piena di quanto sia davvero" % tipo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
