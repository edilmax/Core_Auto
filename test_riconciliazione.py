"""Collaudo RICONCILIAZIONE STRIPE (fase182): il periodo intero contro la banca.

Invarianti:
  1. mondo PERFETTO (Stripe==giornale al centesimo) -> ok True, delta 0;
  2. 👻 SOLO STRIPE: sessione pagata senza incasso a giornale (webhook perso) -> segnalata;
  3. 👻 SOLO GIORNALE: incasso senza sessione Stripe -> segnalato;
  4. ⚖️ IMPORTO DIVERSO sulla stessa prenotazione -> segnalato al centesimo;
  5. le sessioni NON pagate (link abbandonati) sono FILTRATE (non sono incassi);
  6. PAGINAZIONE Stripe (has_more) percorsa fino in fondo;
  7. valute mai mischiate (EUR e USD confrontati separatamente);
  8. endpoint: 403 senza Bunker; 503 senza chiave Stripe; READ-ONLY (giornale intatto);
  9. TETTO PAGINE: un giro TRONCATO si dichiara parziale a chi legge, e tace se completo;
 10. elenchi tagliati: il TOTALE dei fantasmi resta leggibile (chi conta le righe rimaste
     sottostima il disastro, ed e' quello che fanno il server e il Guardiano).
"""
import json
import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase177_financial_controller import crea_financial_controller
from fase182_riconciliazione import _MAX_PAGINE, riconcilia, stripe_sessioni_pagate

ORA = 1_800_000_000            # orologio finto e fermo: test deterministici


def _sessione(rif, cents, valuta="eur", pagata=True, sid=None, pi=None):
    s = {"id": sid or ("cs_" + rif), "payment_status": "paid" if pagata else "unpaid",
         "amount_total": cents, "currency": valuta,
         "metadata": {"riferimento": rif}}
    if pi:                         # g2: il pagamento, espanso come lo chiede fase182
        s["payment_intent"] = {"id": pi, "status": "succeeded"}
    return s


class _StripeFinto:
    """fetch iniettabile: risponde con pagine costruite dal test."""

    def __init__(self, sessioni=None, balance=None):
        self.sessioni = sessioni or []
        self.balance = balance or []
        self.chiamate = []

    def __call__(self, percorso, params, chiave):
        self.chiamate.append((percorso, dict(params)))
        fonte = self.sessioni if percorso.startswith("checkout") else self.balance
        dopo = params.get("starting_after")
        inizio = 0
        if dopo:
            for i, x in enumerate(fonte):
                if x["id"] == dopo:
                    inizio = i + 1
                    break
        blocco = fonte[inizio:inizio + int(params.get("limit", 100))]
        return {"data": blocco, "has_more": inizio + len(blocco) < len(fonte)}


class TestRiconciliazione(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.fc = crea_financial_controller(f"{self.dir}/fin.db",
                                            orologio=lambda: ORA)
        self.fc.inizializza_schema()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _incasso(self, rif, cents, valuta="EUR"):
        self.fc.movimento(tipo="incasso", riferimento=rif, soggetto="host:h",
                          importo_cents=cents, valuta=valuta, causale="pagamento")

    def _ric(self, stripe, giorni=30):
        return riconcilia(self.fc, "sk_test", giorni=giorni, fetch=stripe,
                          ora=lambda: ORA)

    # DA5 (campagna soldi 8/11): Stripe scrive il saldo in euro anche per un pagamento in yen,
    # il giornale in yen: il confronto dei totali gridava per sempre su prenotazioni sane.
    def _convertita(self, sid, euro):
        return {"id": sid, "reporting_category": "charge", "currency": "eur", "amount": euro,
                "exchange_rate": 0.0059}

    def test_DA5_una_prenotazione_in_yen_non_fa_gridare_i_totali(self):
        self._incasso("RJ", 170000, "JPY")
        rep = self._ric(_StripeFinto(sessioni=[_sessione("RJ", 170000, "jpy")],
                                     balance=[self._convertita("t1", 100000)]))
        self.assertIs(rep["ok"], True, rep)
        self.assertEqual(rep["conversioni"], {"charge": 1}, "cio' che non confronta va dichiarato")

    def test_DA5_gli_euro_si_confrontano_lo_stesso(self):
        self._incasso("RJ", 170000, "JPY")
        self._incasso("RE", 500)
        rep = self._ric(_StripeFinto(
            sessioni=[_sessione("RJ", 170000, "jpy"), _sessione("RE", 500)],
            balance=[self._convertita("t1", 100000),
                     {"id": "t2", "reporting_category": "charge", "currency": "eur", "amount": 400}]))
        self.assertIs(rep["ok"], False, "100 cent di euro mancano: deve gridare")

    def test_DA5_yen_a_giornale_senza_nessuna_conversione_grida_ancora(self):
        self._incasso("RJ", 170000, "JPY")
        rep = self._ric(_StripeFinto(sessioni=[_sessione("RJ", 170000, "jpy")], balance=[]))
        self.assertIs(rep["ok"], False, "su Stripe non c'e' niente: non e' una conversione")

    def test_mondo_perfetto(self):
        self._incasso("R1", 25000)
        self._incasso("R2", 18000)
        st = _StripeFinto(
            sessioni=[_sessione("R1", 25000), _sessione("R2", 18000)],
            balance=[{"id": "txn_1", "reporting_category": "charge",
                      "currency": "eur", "amount": 43000}])
        rep = self._ric(st)
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(rep["confronti"]["incassi"]["delta"], {"EUR": 0})
        self.assertEqual(rep["solo_stripe"], [])
        self.assertEqual(rep["solo_giornale"], [])

    def test_fantasma_solo_stripe(self):
        st = _StripeFinto(sessioni=[_sessione("PERSO", 9900)])
        rep = self._ric(st)
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["solo_stripe"][0]["riferimento"], "PERSO")

    def test_fantasma_solo_giornale(self):
        self._incasso("NOSTRO", 7700)
        rep = self._ric(_StripeFinto())
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["solo_giornale"][0]["riferimento"], "NOSTRO")

    def test_importo_diverso_al_centesimo(self):
        self._incasso("RX", 25000)
        st = _StripeFinto(sessioni=[_sessione("RX", 24999)])   # UN centesimo
        rep = self._ric(st)
        self.assertFalse(rep["ok"])
        d = rep["importo_diverso"][0]
        self.assertEqual((d["stripe_cents"], d["giornale_cents"]), (24999, 25000))

    def test_una_CONTESTAZIONE_di_carta_non_passa_per_un_mondo_perfetto(self):
        """C53-B1-4 (busta 8): il confronto guardava solo charge, refund e transfer. Una
        contestazione (chargeback) toglie dal saldo l'importo E la commissione («Addebita
        l'importo contestato, oltre a una commissione di contestazione, sul tuo account
        Stripe», docs.stripe.com, «Come funzionano le contestazioni», letta l'8/10/2026), e
        nel giornale non c'e' nessuna riga che la racconti: il confronto diceva «tutto
        quadra» mentre i soldi uscivano. Ora la categoria `dispute` entra nel confronto, e
        siccome il giornale non ne ha, una contestazione nel periodo e' sempre un delta."""
        self._incasso("R1", 25000)
        st = _StripeFinto(
            sessioni=[_sessione("R1", 25000)],
            balance=[{"id": "txn_1", "reporting_category": "charge",
                      "currency": "eur", "amount": 25000},
                     {"id": "txn_2", "reporting_category": "dispute",
                      "currency": "eur", "amount": -25000},
                     {"id": "txn_3", "reporting_category": "dispute",
                      "currency": "eur", "amount": -1500}])
        rep = self._ric(st)
        self.assertFalse(rep["ok"], "una contestazione da 265 EUR e il confronto dice che "
                                    "tutto quadra: %r" % (rep.get("confronti"),))
        self.assertEqual({"EUR": 26500},
                         rep["confronti"].get("contestazioni", {}).get("delta"),
                         "la contestazione non si legge nel report: %r" % (rep["confronti"],))

    def test_senza_contestazioni_il_confronto_resta_muto(self):
        self._incasso("R1", 25000)
        st = _StripeFinto(sessioni=[_sessione("R1", 25000)],
                          balance=[{"id": "txn_1", "reporting_category": "charge",
                                    "currency": "eur", "amount": 25000}])
        rep = self._ric(st)
        self.assertTrue(rep["ok"], rep)
        self.assertEqual({}, rep["confronti"].get("contestazioni", {}).get("delta", {}),
                         "un mondo senza contestazioni ne mostra una")

    def test_non_pagate_filtrate(self):
        st = _StripeFinto(sessioni=[_sessione("ABBAND", 5000, pagata=False)])
        self.assertEqual(stripe_sessioni_pagate("sk", 0, fetch=st), [])
        rep = self._ric(st)
        self.assertTrue(rep["ok"])                # un link abbandonato NON e' un fantasma

    def test_paginazione_fino_in_fondo(self):
        sessioni = [_sessione("R%03d" % i, 1000, sid="cs_%03d" % i)
                    for i in range(250)]          # 3 pagine da 100
        for i in range(250):
            self._incasso("R%03d" % i, 1000)
        st = _StripeFinto(sessioni=sessioni,
                          balance=[{"id": "t1", "reporting_category": "charge",
                                    "currency": "eur", "amount": 250 * 1000}])
        rep = self._ric(st)
        self.assertEqual(rep["sessioni_pagate"], 250)
        self.assertTrue(rep["ok"], rep["confronti"])
        pagine = [p for p in st.chiamate if p[0].startswith("checkout")]
        self.assertEqual(len(pagine), 3)          # paginazione percorsa davvero

    def test_valute_separate(self):
        self._incasso("EU1", 10000, "EUR")
        self._incasso("US1", 10000, "USD")
        st = _StripeFinto(sessioni=[_sessione("EU1", 10000, "eur"),
                                    _sessione("US1", 10000, "usd")],
                          balance=[{"id": "t1", "reporting_category": "charge",
                                    "currency": "eur", "amount": 10000},
                                   {"id": "t2", "reporting_category": "charge",
                                    "currency": "usd", "amount": 10000}])
        rep = self._ric(st)
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(rep["confronti"]["incassi"]["delta"],
                         {"EUR": 0, "USD": 0})

    def test_tetto_pagine_il_report_dichiara_di_essere_parziale(self):
        """Quando il tetto anti-runaway scatta, il giro NON ha visto tutto Stripe: chi
        legge il report deve poterlo sapere SENZA andare a cercare nei log. Il lato
        giornale non ha nessun tetto, quindi le sessioni mai lette diventano fantasmi
        'solo_giornale': un giro incompleto scambiato per completo produce un ALLARME
        FALSO sui soldi -- e un allarme falso si impara a ignorare (regola ferrea 10)."""
        sessioni = [_sessione("R%04d" % i, 1000, sid="cs_%04d" % i)
                    for i in range((_MAX_PAGINE + 1) * 100)]   # una pagina oltre il tetto
        st = _StripeFinto(sessioni=sessioni)
        rep = self._ric(st)
        pagine = [p for p in st.chiamate if p[0].startswith("checkout")]
        # PRECONDIZIONE: senza questa, la guardia sarebbe verde per il motivo sbagliato,
        # cioe' perche' il tetto non e' scattato affatto (D18 punto 1).
        self.assertEqual(len(pagine), _MAX_PAGINE,
                         "il tetto NON e' scattato: questa guardia non sta misurando "
                         "il difetto che dice di misurare")
        self.assertTrue(rep.get("parziale"),
                        "giro TRONCATO consegnato come se fosse completo: nel report non "
                        "c'e' nessun segno di parzialita' -> chiavi=%r" % (sorted(rep),))

    def test_giro_completo_il_report_non_si_dichiara_parziale(self):
        """L'ALTRA direzione (regola ferrea 10, D18 punto 2): a giro finito il segno di
        parzialita' deve TACERE. Un segnale sempre acceso e' un segnale gia' spento."""
        self._incasso("R1", 25000)
        st = _StripeFinto(sessioni=[_sessione("R1", 25000)],
                          balance=[{"id": "t1", "reporting_category": "charge",
                                    "currency": "eur", "amount": 25000}])
        rep = self._ric(st)
        self.assertTrue(rep["ok"], rep)
        self.assertFalse(rep.get("parziale"),
                         "giro COMPLETO dichiarato parziale: e' un falso allarme")

    def test_elenchi_tagliati_il_totale_dei_fantasmi_resta_leggibile(self):
        """Gli elenchi dei fantasmi escono TAGLIATI, e chi li riceve conta le righe: il
        server scrive nel registro `len(rep["solo_stripe"])` (fase83) e il Guardiano ci
        costruisce l'email d'allarme (fase186). Con l'elenco tagliato quel conto
        SOTTOSTIMA il disastro, e il report non porta nessun totale con cui accorgersene
        (regola ferrea 9: osservabile debole).
        ⚠️ Difetto DIVERSO dal tetto delle pagine: qui il verdetto `ok` resta giusto --
        e' misurato prima del taglio -- e a perdersi e' la GRANDEZZA, non il giudizio."""
        attesi = 60                       # piu' del taglio applicato agli elenchi
        for i in range(attesi):
            self._incasso("G%03d" % i, 1000)
        rep = self._ric(_StripeFinto())
        self.assertFalse(rep["ok"])
        # PRECONDIZIONE: se un giorno il taglio sparisse, questa guardia non avrebbe piu'
        # niente da sorvegliare e deve dirlo, invece di restare verde (D18 punto 1).
        self.assertLess(len(rep["solo_giornale"]), attesi,
                        "gli elenchi non sono piu' tagliati: guardia da rivedere")
        self.assertEqual(rep.get("fantasmi"), attesi,
                         "elenco TAGLIATO e nessun totale nel report: chi legge conta le "
                         "righe rimaste e sottostima -> chiavi=%r" % (sorted(rep),))

    # g2 (RIPRENDI, voce 24/11 sera tardi; «autorizzato» 25/11): due sessioni PAGATE con lo stesso
    # riferimento. Il confronto per riferimento guardava la prima e la seconda passava in
    # silenzio: restava solo lo scarto dei totali, senza il nome di nessuno.
    def _doppio(self, *, reso):
        self._incasso("R1", 25000)
        balance = [{"id": "txn_1", "reporting_category": "charge", "currency": "eur",
                    "amount": 50000}]
        if reso:
            balance.append({"id": "txn_2", "reporting_category": "refund", "currency": "eur",
                            "amount": -25000})
        return _StripeFinto(sessioni=[_sessione("R1", 25000, sid="cs_a", pi="pi_a"),
                                      _sessione("R1", 25000, sid="cs_b", pi="pi_b")],
                            balance=balance)

    def _secondo_registrato(self):           # la riga che scrive il webhook di fase83 (g1)
        self.fc.movimento(tipo="secondo_pagamento", riferimento="R1", soggetto="ospite",
                          importo_cents=25000, valuta="EUR", causale="restituire",
                          evento_id="secondo_pagamento:pi_b")

    def test_g2_due_pagamenti_sullo_stesso_riferimento_sono_un_fantasma(self):
        rep = self._ric(self._doppio(reso=False))
        self.assertIs(rep["ok"], False, rep)
        self.assertEqual([("R1", ["cs_a", "cs_b"])],
                         [(d["riferimento"], sorted(d["sessioni"]))
                          for d in rep.get("doppio_pagamento") or []],
                         "DUE PAGAMENTI SULLA STESSA PRENOTAZIONE E LA RICONCILIAZIONE NON LI "
                         "NOMINA: %r" % (rep,))
        self.assertEqual(1, rep["fantasmi"], rep)

    def test_g2_il_secondo_pagamento_registrato_e_reso_fa_quadrare_i_totali(self):
        self._secondo_registrato()
        rep = self._ric(self._doppio(reso=True))
        self.assertEqual(([], 0), (rep.get("doppio_pagamento"), rep["fantasmi"]), rep)
        self.assertEqual(({"EUR": 0}, {"EUR": 0}),
                         (rep["confronti"]["incassi"]["delta"],
                          rep["confronti"]["rimborsi"]["delta"]), rep)
        self.assertEqual(["cs_b"], [s["id"] for s in rep.get("secondi_pagamenti_noti") or []], rep)
        self.assertIs(rep["ok"], True, rep)

    def test_g2_il_secondo_pagamento_registrato_ma_non_reso_resta_da_guardare(self):
        self._secondo_registrato()
        rep = self._ric(self._doppio(reso=False))
        self.assertEqual([], rep.get("doppio_pagamento"), rep)
        self.assertEqual({"EUR": -25000}, rep["confronti"]["rimborsi"]["delta"],
                         "il secondo pagamento e' dovuto all'ospite e non e' ancora tornato: %r"
                         % (rep,))
        self.assertIs(rep["ok"], False, rep)

    def test_g2_il_secondo_pagamento_registrato_col_primo_fuori_periodo_non_e_un_fantasma(self):
        # silent-failure-hunter (25/11): la notte guarda 2 giorni. Se il primo pagamento e' piu'
        # vecchio, nel periodo resta solo il secondo, gia' in lista: non e' un fantasma
        self._secondo_registrato()
        rep = self._ric(_StripeFinto(
            sessioni=[_sessione("R1", 25000, sid="cs_b", pi="pi_b")],
            balance=[{"id": "txn_1", "reporting_category": "charge", "currency": "eur",
                      "amount": 25000}]))
        self.assertEqual(([], 0), (rep["solo_stripe"], rep["fantasmi"]),
                         "UN SECONDO PAGAMENTO GIA' IN LISTA GRIDATO COME FANTASMA: %r" % (rep,))
        self.assertEqual({"EUR": 0}, rep["confronti"]["incassi"]["delta"], rep)

    def test_g2_DA5_un_secondo_pagamento_in_moneta_convertita_non_fa_gridare_gli_incassi(self):
        # code-review (25/11): la regola DA5 valeva per le somme del giornale, non per i secondi
        self._incasso("RU", 50000, "USD")
        self.fc.movimento(tipo="secondo_pagamento", riferimento="RU", soggetto="ospite",
                          importo_cents=50000, valuta="USD", causale="restituire",
                          evento_id="secondo_pagamento:pi_u2")
        rep = self._ric(_StripeFinto(
            sessioni=[_sessione("RU", 50000, "usd", sid="cs_u1", pi="pi_u1"),
                      _sessione("RU", 50000, "usd", sid="cs_u2", pi="pi_u2")],
            balance=[self._convertita("t1", 46000), self._convertita("t2", 46000)]))
        self.assertEqual({}, rep["confronti"]["incassi"]["delta"],
                         "DOLLARI CONVERTITI DA STRIPE CONFRONTATI COI DOLLARI DEL GIORNALE: %r"
                         % (rep["confronti"],))

    def test_g2_col_giornale_illeggibile_il_doppione_resta_un_fantasma_e_si_dice_perche(self):
        # D19 (25/11, guasti del giudice della CI): la lettura dei secondi pagamenti e' isolata;
        # nel dubbio nessuno e' noto, e anche il secondo GIA' registrato si grida
        import sqlite3
        from unittest import mock
        self._secondo_registrato()
        with mock.patch.object(self.fc, "movimenti",
                               side_effect=sqlite3.OperationalError("database is locked")), \
                self.assertLogs("core_auto.riconciliazione", level="WARNING") as reg:
            rep = self._ric(self._doppio(reso=True))
        self.assertEqual(["R1"], [d["riferimento"] for d in rep.get("doppio_pagamento") or []],
                         "UN GIORNALE ILLEGGIBILE HA FATTO TACERE IL DOPPIO PAGAMENTO: %r" % (rep,))
        letti = [x for x in reg.records if "secondi pagamenti illeggibili" in x.getMessage()]
        self.assertEqual(1, len(letti), "%r" % ([x.getMessage() for x in reg.records],))
        self.assertIs(sqlite3.OperationalError, (letti[0].exc_info or (None,))[0],
                      "il registro dice che il giornale non si legge ma non dice perche'")


class TestDoppiPagamentiSuOgniSequenza(unittest.TestCase):
    """g2 (25/11), skill property-based-testing di Trail of Bits: prenotazioni casuali con 1-3
    sessioni pagate, le ultime m registrate dal webhook come secondo pagamento, incasso del primo
    presente o no. Vista ROSSA sul codice di master (KeyError 'doppio_pagamento'), verde dopo."""

    def test_doppio_se_e_solo_se_piu_di_una_sessione_non_registrata_e_totali_giusti(self):
        from hypothesis import given, settings, strategies as st

        @settings(max_examples=150, deadline=None)
        @given(st.lists(st.tuples(st.integers(1, 3), st.integers(0, 2), st.booleans(),
                                  st.integers(100, 90000)), min_size=1, max_size=6))
        def proprieta(prenotazioni):
            d = tempfile.mkdtemp()
            try:
                fc = crea_financial_controller(f"{d}/f.db", orologio=lambda: ORA)
                fc.inizializza_schema()
                sessioni, charge, giornale, attesi = [], 0, 0, set()
                for i, (k, m, con_incasso, cents) in enumerate(prenotazioni):
                    rif, m = "R%d" % i, min(m, k - 1)
                    if con_incasso:
                        fc.movimento(tipo="incasso", riferimento=rif, soggetto="host:h",
                                     importo_cents=cents, valuta="EUR", causale="p")
                        giornale += cents
                    for j in range(k):
                        pi = "pi_%d_%d" % (i, j)
                        sessioni.append(_sessione(rif, cents, sid="cs_%d_%d" % (i, j), pi=pi))
                        charge += cents
                        if j >= k - m:             # le ultime m: secondi pagamenti registrati
                            fc.movimento(tipo="secondo_pagamento", riferimento=rif,
                                         soggetto="ospite", importo_cents=cents, valuta="EUR",
                                         causale="restituire",
                                         evento_id="secondo_pagamento:" + pi)
                            giornale += cents
                    if k - m > 1:
                        attesi.add(rif)
                rep = riconcilia(fc, "sk_test", giorni=30, ora=lambda: ORA, fetch=_StripeFinto(
                    sessioni=sessioni, balance=[{"id": "t", "reporting_category": "charge",
                                                 "currency": "eur", "amount": charge}]))
                self.assertEqual(attesi, {x["riferimento"] for x in rep["doppio_pagamento"]}, rep)
                self.assertEqual(charge - giornale,
                                 rep["confronti"]["incassi"]["delta"].get("EUR", 0), rep)
                fantasmi = {s["id"] for s in rep["solo_stripe"]}
                self.assertFalse([s for s in rep["secondi_pagamenti_noti"] if s["id"] in fantasmi])
            finally:
                shutil.rmtree(d, ignore_errors=True)
        proprieta()


class TestEndpointRiconciliazione(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"r" * 32, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_finanza=f"{d}/fin.db", bunker_password="SuperPw@1",
            stripe_secret_key="sk_test_x", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_bunker_gated_e_read_only(self):
        s, _ = self.r.gestisci("GET", "/api/bunker/riconciliazione", {}, None,
                               {"X-Admin-Key": "ak"})
        self.assertEqual(s, 403)                  # senza sessione Bunker
        # con sessione: la fetch REALE fallira' (sk_test_x non valida) -> l'endpoint
        # NON esplode e il giornale resta INTATTO (read-only provato)
        s, out = self.r.gestisci("POST", "/api/bunker/login", {},
                                 json.dumps({"codice": "SuperPw@1"}),
                                 {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(s, 200, out)
        hb = {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9",
              "X-Bunker-Session": out["sessione"]}
        prima = self.sis.finanza.conta_movimenti()
        s, d = self.r.gestisci("GET", "/api/bunker/riconciliazione",
                               {"giorni": "7"}, None, hb)
        self.assertIn(s, (200, 503))              # 503 = Stripe irraggiungibile: ONESTO
        self.assertEqual(self.sis.finanza.conta_movimenti(), prima)


if __name__ == "__main__":
    unittest.main()
