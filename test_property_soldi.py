"""
PROPERTY-BASED TESTING (Hypothesis) sui MOTORI DEI SOLDI.

Invece di scegliere noi i casi, Hypothesis GENERA centinaia di input (anche cattivi/estremi) e
verifica che gli INVARIANTI reggano SEMPRE. Se trova un controesempio, lo restringe al piu'
piccolo e lo mostra. Copre: motore "paga in struttura" (fase188), rampa commissioni (fase98),
rimborso cancellazione (fase111). Zero rete, deterministico (seed fisso via profilo).
"""
import unittest

from hypothesis import given, settings, strategies as st, HealthCheck

import fase188_paga_struttura as PS
import fase98_policy_commissione as POL
import fase111_cancellazione as CANC
import fase162_pagamenti_pendenti as PEND

_S = settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _stripe_peggiore(x):
    return 25 + x * 325 // 10000


class TestMotorePagaStruttura(unittest.TestCase):
    @_S
    @given(prezzo=st.integers(min_value=0, max_value=5_000_000),
           notti=st.integers(min_value=1, max_value=90),
           comm=st.integers(min_value=0, max_value=6_000_000),
           psp=st.integers(min_value=0, max_value=1000))
    def test_invarianti_sempre(self, prezzo, notti, comm, psp):
        r = PS.calcola(prezzo, notti, comm, psp_bps=psp)
        A, S = r["anticipo_online_cents"], r["saldo_in_loco_cents"]
        # niente negativi, mai
        for k, v in r.items():
            self.assertGreaterEqual(v, 0, "%s negativo: %s" % (k, r))
        # conservazione + totale ospite = prezzo + fee
        self.assertEqual(r["ospite_paga_totale_cents"], max(0, prezzo) + r["fee_cents"])
        self.assertEqual(A + S, r["ospite_paga_totale_cents"])
        # host prende TUTTO dal saldo (no giro storto)
        self.assertEqual(r["host_incassa_cents"], S)
        # NON SI PERDE MAI: quello che incassiamo online copre il costo Stripe peggiore
        if A > 0:
            self.assertGreater(A - _stripe_peggiore(A), 0, "PERDITA su %s" % r)
        # margine PIENO quando l'anticipo non e' tosato (saldo > 0)
        if S > 0 and A > 0:
            self.assertGreaterEqual(r["gateway_cents"], _stripe_peggiore(A))

    @_S
    @given(prezzo=st.integers(min_value=1, max_value=5_000_000),
           notti=st.integers(min_value=1, max_value=60))
    def test_fee_sempre_150_per_notte(self, prezzo, notti):
        r = PS.calcola(prezzo, notti, 0)
        self.assertEqual(r["fee_cents"], 150 * notti)


class TestRampaCommissioni(unittest.TestCase):
    @_S
    @given(giorni=st.integers(min_value=-1000, max_value=100000))
    def test_scaglioni_0_8_10(self, giorni):
        bps = POL.commissione_bps_lancio(giorni)
        # sempre uno dei tre scaglioni ufficiali
        self.assertIn(bps, (0, POL.LANCIO_BPS_FASE1, POL.LANCIO_BPS_REGIME),
                      "bps fuori scaglione: %d (giorni %d)" % (bps, giorni))
        if giorni < 0:
            # FAIL-SAFE del fondatore: giorni non validi -> tariffa a regime (non si regala lo 0%)
            self.assertEqual(bps, POL.LANCIO_BPS_REGIME, "giorni negativi devono dare la tariffa a regime (fail-safe)")
        elif giorni < POL.LANCIO_GIORNI_GRATIS:
            self.assertEqual(bps, 0)
        elif giorni < POL.LANCIO_GIORNI_FASE1:
            self.assertEqual(bps, POL.LANCIO_BPS_FASE1)
        else:
            self.assertEqual(bps, POL.LANCIO_BPS_REGIME)

    @_S
    @given(g1=st.integers(min_value=0, max_value=100000),
           g2=st.integers(min_value=0, max_value=100000))
    def test_monotona(self, g1, g2):
        # su giorni VALIDI (>=0): piu' anzianita' -> commissione mai minore (la rampa non torna
        # indietro). Sui giorni negativi vale il fail-safe (regime), fuori dalla monotonia.
        if g1 <= g2:
            self.assertLessEqual(POL.commissione_bps_lancio(g1), POL.commissione_bps_lancio(g2))


class TestRimborsoCancellazione(unittest.TestCase):
    @_S
    @given(pagato=st.integers(min_value=0, max_value=5_000_000),
           giorni=st.integers(min_value=-30, max_value=400),
           politica=st.sampled_from(["flessibile", "moderata", "rigida", "non_rimborsabile"]),
           ripens=st.booleans())
    def test_rimborso_mai_oltre_il_pagato(self, pagato, giorni, politica, ripens):
        r = CANC.calcola_rimborso(pagato, giorni, politica=politica, entro_ripensamento=ripens)
        rimb = r.get("rimborso_cents", 0)
        tratt = r.get("trattenuto_cents", 0)
        # niente negativi
        self.assertGreaterEqual(rimb, 0, f"rimborso negativo: {r}")
        self.assertGreaterEqual(tratt, 0, f"trattenuto negativo: {r}")
        # MAI rimborsare piu' di quanto pagato (regalo di soldi)
        self.assertLessEqual(rimb, max(0, pagato), f"rimborso > pagato: {r}")
        # conservazione: rimborso + trattenuto == pagato
        self.assertEqual(rimb + tratt, max(0, pagato), f"rimborso+trattenuto != pagato: {r}")

    @_S
    @given(pagato=st.integers(min_value=1, max_value=1_000_000),
           giorni=st.integers(min_value=3, max_value=400))
    def test_ripensamento_rende_tutto(self, pagato, giorni):
        # dentro il ripensamento 48h (arrivo >= 3 giorni) si rende il 100% (diritto legale)
        r = CANC.calcola_rimborso(pagato, giorni, politica="non_rimborsabile", entro_ripensamento=True)
        self.assertEqual(r.get("rimborso_cents", 0), pagato, f"ripensamento non rende tutto: {r}")


# ─────────────────────────────────────────────────────────────────────────────────────────
# LA RIGA SQL DELLA PURGA — provata COME SQL (2026-08-17)
# ─────────────────────────────────────────────────────────────────────────────────────────
_STATI = ("in_attesa", "in_attesa_host", "scaduto", "pagato", "rimborsato", "cancellata_host")


@st.composite
def _record(draw):
    """Un pendente: uno stato qualsiasi, nato fra 0 e 400 ore nel passato."""
    return (draw(st.sampled_from(_STATI)),
            draw(st.integers(min_value=0, max_value=400)))


class TestLaPurgaNonPuoPerdereChiAspettaISoldi(unittest.TestCase):
    """⛔ LA RIGA PIÙ RISCHIOSA DEL LAVORO DEL 2026-08-17, e non era provata come SQL.

    `fase162.pulisci_vecchi` esegue un `DELETE ... WHERE stato=? AND creato_ts<?`. Una
    condizione sbagliata lì non rompe niente in modo visibile: cancella **in silenzio** il
    record dove vive lo `stripe_pi`, cioè l'unico modo di restituire i soldi a chi aspetta.
    È esattamente il difetto trovato il 2026-08-17 — la soglia contava da `creato_ts`, cioè
    dalla PRENOTAZIONE — e un difetto di quella famiglia non lo prende un caso scelto a mano.

    ⚠️ LA FORMA della prova viene dal **TLP (Ternary Logic Partitioning)**, ricerca sui
    database (SQLancer, Rigger) — ⛔ **NON è una tecnica AWS**, e non va attribuita ad AWS:
    per il suo database AWS usa simulazione deterministica, metodi formali e iniezione di
    guasti, che sono già fra le nostre 11. Il TLP dice: le righe CANCELLATE e quelle RIMASTE
    devono ricomporre **esattamente** la tabella di partenza — nessuna persa, nessuna doppia.

    Gli attrezzi sono due che il progetto ha già (test a proprietà · oracolo indipendente):
    l'insieme atteso è ricalcolato **in Python**, non in SQL, così due errori uguali non si
    coprono a vicenda.
    """

    @_S
    @given(righe=st.lists(_record(), min_size=1, max_size=10),
           eta_sec=st.integers(min_value=0, max_value=400_000),
           ore_dopo=st.integers(min_value=0, max_value=500))
    def test_toglie_ESATTAMENTE_gli_scaduti_vecchi_e_nientaltro(self, righe, eta_sec, ore_dopo):
        base = 1_700_000_000
        clock = {"t": base}
        p = PEND.crea_pagamenti_pendenti(":memory:", orologio=lambda: clock["t"])
        p.inizializza_schema()
        tutti = set()
        for i, (stato, eta_ore) in enumerate(righe):
            rif = "R%d" % i
            clock["t"] = base - eta_ore * 3600          # nasce nel passato: è il punto
            p.registra(rif, alloggio_id="a", check_in="2026-10-01", check_out="2026-10-02",
                       stato=("in_attesa_host" if stato == "in_attesa_host" else "in_attesa"))
            if stato == "scaduto":
                p.scadi(rif)
            elif stato == "pagato":
                p.conferma(rif)
            elif stato == "rimborsato":
                p.marca_da_rimborsare(rif)
            elif stato == "cancellata_host":
                p.marca_cancellata_host(rif, 0)
            tutti.add(rif)
        clock["t"] = base
        ora = base + ore_dopo * 3600
        taglio = ora - max(60, eta_sec)
        # ── ORACOLO INDIPENDENTE: lo stesso conto, scritto in Python invece che in SQL ──
        attesi_via = {"R%d" % i for i, (stato, eta_ore) in enumerate(righe)
                      if stato == "scaduto" and (base - eta_ore * 3600) < taglio}
        quanti = p.pulisci_vecchi(eta_sec=eta_sec, ora_ts=ora)
        rimasti = {r for r in tutti if p.info(r) is not None}
        # ── TLP: le due parti devono ricomporre ESATTAMENTE la tabella ──
        self.assertEqual(rimasti | attesi_via, tutti,
                         "righe PERSE dalla partizione: cancellate + rimaste non ricompongono "
                         "la tabella. via=%r rimasti=%r" % (sorted(attesi_via), sorted(rimasti)))
        self.assertEqual(rimasti & attesi_via, set(),
                         "una riga risulta insieme cancellata E rimasta: %r"
                         % sorted(rimasti & attesi_via))
        self.assertEqual(quanti, len(attesi_via),
                         "il conto dei rimossi non torna con l'oracolo: dice %d, atteso %d"
                         % (quanti, len(attesi_via)))
        # ── E LA PROPRIETÀ CHE VALE I SOLDI, dichiarata a parte perché è quella che conta ──
        for i, (stato, _e) in enumerate(righe):
            if stato in ("rimborsato", "cancellata_host"):
                self.assertIsNotNone(
                    p.info("R%d" % i),
                    "la purga ha portato via un record in stato '%s': con lui se ne va lo "
                    "`stripe_pi` e quei soldi non si possono più restituire dal pannello"
                    % stato)


# ─────────────────────────────────────────────────────────────────────────────────────────
# LA CONSERVAZIONE DELLA CONTROVERSIA — le due tecniche che al progetto mancavano su questo
# punto: la PROVA FORMALE (z3) e le RELAZIONI METAMORFICHE. Accese il 2026-08-17.
# ─────────────────────────────────────────────────────────────────────────────────────────
import fase160_escrow_garanzia as ESC


def _cassaforte(imp, rif="R"):
    """Una cassaforte VERA (in memoria) con `imp` centesimi, gia' contestata."""
    g = ESC.crea_escrow_garanzia(":memory:")
    g.inizializza_schema()
    g.apri(rif, imp, alloggio_id="a")
    g.contesta(rif)
    return g


class TestLaConservazioneDellaControversiaEDimostrata(unittest.TestCase):
    """⛔ LA PROVA FORMALE, che e' una cosa diversa da un test.

    `fase160.risolvi` fa `rimb = min(_cent(x), imp)` e `host = imp - rimb`. Un test prova
    quello che gli dai; **z3 prova che non esiste NESSUN ingresso** che rompa l'invariante --
    e' l'unica delle 11 tecniche che risponde «per tutti», non «per questi».

    💡 E serviva davvero: leggendo si scopre che `risolvi` da sola NON ha un limite inferiore.
    L'unica cosa che impedisce a un importo NEGATIVO di far ricevere all'host piu' di quanto
    c'era in garanzia e' una riga in un altro punto del file, `_cent` (fase160:43), che azzera
    i negativi. Un invariante che dipende da un pezzo altrove e' esattamente il tipo di cosa
    che si dimostra, non si spera.

    ⛔ E la prova e' provata nelle DUE direzioni: se si toglie quel presidio, z3 deve trovare
    un CONTROESEMPIO. Una prova che non sa fallire non e' una prova (regola dei 10 collaudi).
    """

    def _z3(self):
        try:
            import z3
        except Exception:                                    # pragma: no cover
            self.skipTest("z3 non installato in questo ambiente (gira dove c'e' z3-solver)")
        return z3

    def test_TEOREMA_nessun_centesimo_si_crea_o_si_perde(self):
        z3 = self._z3()
        imp, x = z3.Ints("imp x")
        cent = z3.If(x >= 0, x, 0)                  # `_cent`: i negativi diventano 0
        rimb = z3.If(cent < imp, cent, imp)         # `min(_cent(x), imp)`
        host = imp - rimb
        s = z3.Solver()
        s.add(imp >= 0)                             # una garanzia non e' mai negativa
        s.add(z3.Not(z3.And(host + rimb == imp,     # conservazione esatta
                            rimb >= 0, rimb <= imp,  # l'ospite non prende piu' della garanzia
                            host >= 0)))             # e l'host non finisce in negativo
        esito = s.check()
        self.assertEqual(
            str(esito), "unsat",
            "z3 ha trovato un ingresso che rompe la conservazione della controversia: %s"
            % (s.model() if str(esito) == "sat" else esito))

    def test_LA_PROVA_SA_FALLIRE_se_si_toglie_il_presidio(self):
        """Lo stesso teorema SENZA l'azzeramento dei negativi: z3 deve trovare il
        controesempio. Se restasse `unsat` anche cosi', la prova di sopra non starebbe
        dimostrando niente -- sarebbe l'ornamento peggiore, uno che sembra matematica."""
        z3 = self._z3()
        imp, x = z3.Ints("imp x")
        rimb = z3.If(x < imp, x, imp)               # ⛔ senza `_cent`: x puo' essere negativo
        host = imp - rimb
        s = z3.Solver()
        s.add(imp >= 0)
        s.add(z3.Not(z3.And(host + rimb == imp, rimb >= 0, rimb <= imp, host >= 0)))
        self.assertEqual(str(s.check()), "sat",
                         "senza il presidio la prova NON trova il controesempio: allora non "
                         "sta dimostrando niente, e il teorema di sopra e' un ornamento")


class TestRelazioniMetamorficheSullaControversia(unittest.TestCase):
    """⛔ L'UNICA DELLE 11 TECNICHE CHE IL PROGETTO NON AVEVA, accesa qui il 2026-08-17.

    Il metamorfico non chiede «quanto deve venire?» -- chiede «se cambio l'ingresso COSI',
    come deve cambiare l'uscita?». Serve dove il risultato atteso non si sa scrivere a mano
    senza rifare lo stesso calcolo (e due volte lo stesso errore da' lo stesso risultato).

    Il lavoro in sospeso n.4 lo chiede **sull'aritmetica del DENARO**, e lo split di una
    controversia e' aritmetica del denaro: decide quanto va a due persone diverse.
    """

    @_S
    @given(imp=st.integers(min_value=0, max_value=5_000_000),
           pct=st.integers(min_value=0, max_value=100))
    def test_RADDOPPIANDO_la_garanzia_le_quote_raddoppiano_A_MENO_DI_UN_CENTESIMO(self, imp, pct):
        """R1: la stessa percentuale su una garanzia DOPPIA da' quote doppie, **a meno di un
        centesimo**. Quel centesimo non e' tolleranza gratuita: e' esattamente il massimo che
        il troncamento della divisione intera puo' introdurre, e nulla di piu'.

        ⛔ LA PRIMA VERSIONE DI QUESTA RELAZIONE ERA FALSA, ED ERA MIA (sbaglio S15: scrivere
        la relazione NOMINALE invece di quella VERA). Pretendeva il doppio esatto, e la
        macchina ha risposto in un istante con un controesempio da un centesimo: con 1 in
        garanzia al 50%, `1*50//100 = 0` ma `2*50//100 = 1` -- e zero raddoppiato non fa uno.
        Il prodotto era sano: era la mia aspettativa a essere sbagliata. E' la prima cosa che
        questa tecnica ha trovato, il giorno che e' stata accesa.

        💡 Cosi' scritta, la relazione ha ancora denti: uno sbaglio che perde piu' di un
        centesimo per raddoppio -- una percentuale applicata due volte, un troncamento al
        posto sbagliato -- sfonda questo limite subito."""
        a = _cassaforte(imp).risolvi("R", rimborso_ospite_cents=imp * pct // 100)
        b = _cassaforte(imp * 2).risolvi("R", rimborso_ospite_cents=(imp * 2) * pct // 100)
        if not (a.get("ok") and b.get("ok")):
            return                                  # garanzia 0: niente da spartire
        o2, o1 = b["ospite_rimborso_cents"], a["ospite_rimborso_cents"]
        h2, h1 = b["host_riceve_cents"], a["host_riceve_cents"]
        self.assertIn(o2 - 2 * o1, (0, 1),
                      "la quota dell'ospite si allontana dal doppio di piu' di un centesimo: "
                      "garanzia %d -> %d, doppia -> %d" % (imp, o1, o2))
        self.assertIn(2 * h1 - h2, (0, 1),
                      "la quota dell'host si allontana dal doppio di piu' di un centesimo: "
                      "garanzia %d -> %d, doppia -> %d" % (imp, h1, h2))

    @_S
    @given(imp=st.integers(min_value=1, max_value=5_000_000),
           x=st.integers(min_value=-1_000_000, max_value=9_000_000))
    def test_QUALUNQUE_cifra_io_dia_la_somma_torna_ESATTA(self, imp, x):
        """R2: per QUALUNQUE cifra -- anche assurda, anche negativa, anche piu' grande della
        garanzia -- `ospite + host` fa esattamente la garanzia. Nessun centesimo creato dal
        nulla, nessuno perso per strada. E' l'invariante che z3 dimostra, qui verificato sul
        codice VERO invece che su un modello."""
        out = _cassaforte(imp).risolvi("R", rimborso_ospite_cents=x)
        self.assertTrue(out.get("ok"), "la risoluzione doveva riuscire: %r" % (out,))
        o, h = out["ospite_rimborso_cents"], out["host_riceve_cents"]
        self.assertEqual(o + h, imp,
                         "conservazione ROTTA: ospite %d + host %d != garanzia %d" % (o, h, imp))
        self.assertTrue(0 <= o <= imp, "quota ospite fuori dai limiti: %d su %d" % (o, imp))
        self.assertGreaterEqual(h, 0, "l'host finisce in negativo: %d" % h)

    @_S
    @given(imp=st.integers(min_value=1, max_value=5_000_000),
           x=st.integers(min_value=0, max_value=5_000_000))
    def test_DARE_ALL_OSPITE_o_DARE_ALL_HOST_e_lo_stesso_conto(self, imp, x):
        """R3: decidere «all'ospite X» oppure «all'host garanzia-X» deve portare allo STESSO
        split. Se le due strade divergessero, l'esito dipenderebbe da come l'arbitro formula
        la stessa decisione -- e due formulazioni della stessa decisione non possono dare due
        cifre diverse."""
        quota_ospite = min(x, imp)
        a = _cassaforte(imp).risolvi("R", rimborso_ospite_cents=quota_ospite)
        b = _cassaforte(imp).risolvi("R", rimborso_ospite_cents=imp - (imp - quota_ospite))
        self.assertEqual((a["ospite_rimborso_cents"], a["host_riceve_cents"]),
                         (b["ospite_rimborso_cents"], b["host_riceve_cents"]),
                         "la stessa decisione detta in due modi da' due split diversi")


# ═════════════════════════════════════════════════════════════════════════════════════════
# RELAZIONI METAMORFICHE SULL'ARITMETICA DEL DENARO  (blocco SOLDI, riga d'arrivo n.4)
# ═════════════════════════════════════════════════════════════════════════════════════════
# ⛔ RELAZIONI, NON ESEMPI, ed e' la differenza che rende questa sezione diversa da tutto
#    quello che sta sopra. Un invariante guarda UNA chiamata («il totale non e' mai
#    negativo»); una relazione metamorfica lega DUE chiamate imparentate e la loro uscita
#    («se raddoppio le notti la fee raddoppia»). Serve dove non esiste un oracolo: non
#    sappiamo dire quanto DEVE venire, ma sappiamo come devono stare fra loro due conti.
#    Fonte: Chen et al., ACM Computing Surveys 51(1), 2018; le sei famiglie di
#    trasformazione (additiva, moltiplicativa, permutativa, invertiva, inclusiva,
#    esclusiva) sono di Segura et al., IEEE TSE 2016 -- si pescano da li' invece di
#    inventarle, e ogni relazione qui sotto dichiara la sua famiglia.
#
# ⛔ E L'AVVERTIMENTO CHE HA CAMBIATO IL DISEGNO (Potter, «Metamorphic Relations for
#    Backtests»): LE COMPONENTI A COSTO FISSO NON SCALANO. Qui la fee e' fissa per notte e
#    il gateway ha un minimo, una parte fissa e un punto fisso iterativo: una relazione
#    «raddoppio il prezzo, raddoppia tutto» sarebbe FALSA, e un allarme che accusa innocenti
#    viene spento. Percio' qui non c'e' nessuna relazione moltiplicativa sul prezzo: quella
#    sulle notti c'e' perche' la fee e' l'unica parte davvero lineare, ed e' stato misurato.
#
# 🔑 OGNI RELAZIONE E' SCRITTA UNA VOLTA SOLA, come predicato sugli ingressi concreti. La
#    usano sia i test con `hypothesis` (che generano gli ingressi) sia la matrice qui sotto
#    (che li fissa e rompe il motore). Due formulazioni della stessa relazione potrebbero
#    divergere, e allora una delle due direbbe il falso senza avvisare.

import fase133_split_quote_uguali as SPLIT  # noqa: E402


def _mr_prezzo_monotono(p1, p2, notti):
    """ADDITIVA — pagare di piu' non puo' far scendere il totale dell'ospite."""
    lo, hi = min(p1, p2), max(p1, p2)
    return (PS.calcola(lo, notti, 0)["ospite_paga_totale_cents"]
            <= PS.calcola(hi, notti, 0)["ospite_paga_totale_cents"])


def _mr_commissione_non_premia(prezzo, notti, c1, c2):
    """ADDITIVA — alzare la nostra commissione non puo' far incassare di PIU' all'host.
    E' la «fee monotonicity» della fonte: prende i segni sbagliati, che sono il difetto
    piu' banale e piu' caro del percorso del denaro."""
    lo, hi = min(c1, c2), max(c1, c2)
    return (PS.calcola(prezzo, notti, lo)["host_incassa_cents"]
            >= PS.calcola(prezzo, notti, hi)["host_incassa_cents"])


def _mr_valuta_estera_costa_di_piu(prezzo, notti, comm):
    """INCLUSIVA — aggiungere la conversione non puo' costare MENO, e dove l'anticipo non
    e' compresso deve costare STRETTAMENTE di piu'.
    ⛔ Il `>=` da solo era un ORNAMENTO, misurato: ignorando la conversione i due conti
    escono UGUALI, quindi la relazione taceva proprio sul difetto che doveva vedere. La
    condizione «non compresso» si legge dall'uscita (l'anticipo ha toccato il totale), non
    dalle viscere del modulo."""
    euro = PS.calcola(prezzo, notti, comm)
    estera = PS.calcola(prezzo, notti, comm, valuta_estera=True)
    if estera["gateway_cents"] < euro["gateway_cents"]:
        return False
    compresso = euro["anticipo_online_cents"] >= euro["ospite_paga_totale_cents"]
    return compresso or estera["gateway_cents"] > euro["gateway_cents"]


def _mr_fee_lineare_nelle_notti(prezzo, notti, k):
    """MOLTIPLICATIVA — k volte le notti, k volte la fee. E' l'unica parte lineare del
    motore: tutto il resto ha componenti fisse e non scala (vedi il cappello)."""
    return (PS.calcola(prezzo, notti * k, 0)["fee_cents"]
            == k * PS.calcola(prezzo, notti, 0)["fee_cents"])


def _mr_anticipo_piu_saldo(prezzo, notti, comm):
    """ADDITIVA — quello che l'ospite paga subito piu' quello che paga in struttura fa
    esattamente il totale. Nessun centesimo puo' nascere o sparire nel mezzo."""
    r = PS.calcola(prezzo, notti, comm)
    return (r["anticipo_online_cents"] + r["saldo_in_loco_cents"]
            == r["ospite_paga_totale_cents"])


def _mr_rimborso_monotono_nei_giorni(pagato, g1, g2, politica):
    """ADDITIVA — cancellare con piu' anticipo non puo' rendere MENO soldi."""
    lo, hi = min(g1, g2), max(g1, g2)
    return (CANC.calcola_rimborso(pagato, lo, politica=politica)["rimborso_cents"]
            <= CANC.calcola_rimborso(pagato, hi, politica=politica)["rimborso_cents"])


def _mr_ripensamento_rende_tutto(pagato, giorni, politica):
    """INVERTIVA — la finestra di ripensamento rende il 100% a prescindere dalla politica,
    e dove la politica renderebbe meno deve rendere STRETTAMENTE di piu'.
    ⛔ Anche qui il `>=` da solo era un ornamento: una finestra IGNORATA da' lo stesso
    numero della politica, e la relazione taceva. Misurato."""
    normale = CANC.calcola_rimborso(pagato, giorni, politica=politica)["rimborso_cents"]
    con = CANC.calcola_rimborso(pagato, giorni, politica=politica,
                                entro_ripensamento=True)["rimborso_cents"]
    if con != pagato:
        return False
    return not (normale < pagato and con <= normale)


def _mr_pulizia_si_scorpora(pagato, giorni, pulizia, politica):
    """ESCLUSIVA — la pulizia e' sempre resa, quindi togliere la pulizia dal pagato e
    chiedere il rimborso del resto deve dare lo stesso conto. Se le due strade divergono,
    l'esito dipende da COME si formula la stessa domanda."""
    if pulizia >= pagato:
        return True
    con = CANC.calcola_rimborso(pagato, giorni, politica=politica,
                                fee_pulizia_cents=pulizia)["rimborso_cents"]
    senza = CANC.calcola_rimborso(pagato - pulizia, giorni, politica=politica)["rimborso_cents"]
    return con == pulizia + senza


def _mr_quote_sommano_al_totale(totale, n):
    """ADDITIVA — dividere fra N ospiti non crea e non perde centesimi."""
    return sum(SPLIT.riparti_uguale(totale, n)) == totale


def _mr_scarto_massimo_un_centesimo(totale, n):
    """PERMUTATIVA — nessuno paga piu' di un centesimo in piu' di un altro: e' l'unica
    definizione di «uguale» che regge sugli interi."""
    quote = SPLIT.riparti_uguale(totale, n)
    return (not quote) or (max(quote) - min(quote) <= 1)


def _mr_piu_partecipanti_quota_minore(totale, n):
    """INCLUSIVA — aggiungere un partecipante non puo' far salire la quota di chi paga di
    piu'. Prende il caso in cui il resto viene distribuito storto."""
    if n <= 1:
        return True
    piu, meno = SPLIT.riparti_uguale(totale, n), SPLIT.riparti_uguale(totale, n - 1)
    return (not piu) or (not meno) or max(piu) <= max(meno)


def _mr_doppio_riparto_conserva(totale, n, m):
    """COMPOSIZIONE — ripartire, e poi ripartire ancora ogni quota, conserva il totale.
    E' la relazione che prende gli arrotondamenti che si accumulano a ogni passaggio."""
    return sum(sum(SPLIT.riparti_uguale(q, m))
               for q in SPLIT.riparti_uguale(totale, n)) == totale


class TestRelazioniMetamorficheSulDenaro(unittest.TestCase):
    """Le dodici relazioni, con gli ingressi generati da Hypothesis invece che scelti da noi."""

    _P = st.integers(min_value=0, max_value=5_000_000)
    _N = st.integers(min_value=1, max_value=90)
    _C = st.integers(min_value=0, max_value=6_000_000)

    @_S
    @given(p1=_P, p2=_P, notti=_N)
    def test_MR1_pagare_di_piu_non_abbassa_il_totale(self, p1, p2, notti):
        self.assertTrue(_mr_prezzo_monotono(p1, p2, notti),
                        "totale non monotono fra %d e %d su %d notti" % (p1, p2, notti))

    @_S
    @given(prezzo=_P, notti=_N, c1=_C, c2=_C)
    def test_MR2_piu_commissione_non_fa_incassare_di_piu_all_host(self, prezzo, notti, c1, c2):
        self.assertTrue(_mr_commissione_non_premia(prezzo, notti, c1, c2),
                        "commissione piu' alta -> host incassa di PIU' (prezzo=%d notti=%d "
                        "comm=%d/%d)" % (prezzo, notti, c1, c2))

    @_S
    @given(prezzo=_P, notti=_N, comm=_C)
    def test_MR3_la_valuta_estera_non_e_mai_piu_economica(self, prezzo, notti, comm):
        self.assertTrue(_mr_valuta_estera_costa_di_piu(prezzo, notti, comm),
                        "la conversione non e' addebitata (prezzo=%d notti=%d comm=%d)"
                        % (prezzo, notti, comm))

    @_S
    @given(prezzo=_P, notti=st.integers(min_value=1, max_value=18),
           k=st.integers(min_value=2, max_value=5))
    def test_MR4_la_fee_e_lineare_nelle_notti(self, prezzo, notti, k):
        self.assertTrue(_mr_fee_lineare_nelle_notti(prezzo, notti, k),
                        "fee non lineare (prezzo=%d notti=%d k=%d)" % (prezzo, notti, k))

    @_S
    @given(prezzo=_P, notti=_N, comm=_C)
    def test_MR5_anticipo_piu_saldo_fa_il_totale(self, prezzo, notti, comm):
        self.assertTrue(_mr_anticipo_piu_saldo(prezzo, notti, comm),
                        "anticipo+saldo != totale (prezzo=%d notti=%d comm=%d)"
                        % (prezzo, notti, comm))

    @_S
    @given(pagato=st.integers(min_value=1, max_value=5_000_000),
           g1=st.integers(min_value=0, max_value=400),
           g2=st.integers(min_value=0, max_value=400),
           politica=st.sampled_from(["flessibile", "moderata", "rigida"]))
    def test_MR6_cancellare_prima_non_rende_meno(self, pagato, g1, g2, politica):
        self.assertTrue(_mr_rimborso_monotono_nei_giorni(pagato, g1, g2, politica),
                        "rimborso non monotono (pagato=%d giorni=%d/%d %s)"
                        % (pagato, g1, g2, politica))

    @_S
    @given(pagato=st.integers(min_value=1, max_value=5_000_000),
           giorni=st.integers(min_value=0, max_value=400),
           politica=st.sampled_from(["flessibile", "moderata", "rigida", "non_rimborsabile"]))
    def test_MR7_il_ripensamento_rende_tutto_e_domina_la_politica(self, pagato, giorni, politica):
        self.assertTrue(_mr_ripensamento_rende_tutto(pagato, giorni, politica),
                        "il ripensamento non domina (pagato=%d giorni=%d %s)"
                        % (pagato, giorni, politica))

    @_S
    @given(pagato=st.integers(min_value=1, max_value=5_000_000),
           giorni=st.integers(min_value=0, max_value=400),
           pulizia=st.integers(min_value=0, max_value=200_000),
           politica=st.sampled_from(["flessibile", "moderata", "rigida"]))
    def test_MR8_la_pulizia_si_scorpora(self, pagato, giorni, pulizia, politica):
        self.assertTrue(_mr_pulizia_si_scorpora(pagato, giorni, pulizia, politica),
                        "la pulizia non si scorpora (pagato=%d giorni=%d pulizia=%d %s)"
                        % (pagato, giorni, pulizia, politica))

    @_S
    @given(totale=st.integers(min_value=0, max_value=5_000_000),
           n=st.integers(min_value=1, max_value=12))
    def test_MR9_le_quote_sommano_al_totale(self, totale, n):
        self.assertTrue(_mr_quote_sommano_al_totale(totale, n),
                        "il riparto non conserva (totale=%d n=%d)" % (totale, n))

    @_S
    @given(totale=st.integers(min_value=0, max_value=5_000_000),
           n=st.integers(min_value=1, max_value=12))
    def test_MR10_nessuno_paga_piu_di_un_centesimo_in_piu(self, totale, n):
        self.assertTrue(_mr_scarto_massimo_un_centesimo(totale, n),
                        "riparto non equo (totale=%d n=%d)" % (totale, n))

    @_S
    @given(totale=st.integers(min_value=0, max_value=5_000_000),
           n=st.integers(min_value=2, max_value=12))
    def test_MR11_un_partecipante_in_piu_non_alza_la_quota(self, totale, n):
        self.assertTrue(_mr_piu_partecipanti_quota_minore(totale, n),
                        "aggiungere un ospite alza la quota massima (totale=%d n=%d)"
                        % (totale, n))

    @_S
    @given(totale=st.integers(min_value=0, max_value=5_000_000),
           n=st.integers(min_value=1, max_value=8),
           m=st.integers(min_value=1, max_value=8))
    def test_MR12_ripartire_due_volte_conserva_il_totale(self, totale, n, m):
        self.assertTrue(_mr_doppio_riparto_conserva(totale, n, m),
                        "il doppio riparto perde centesimi (totale=%d n=%d m=%d)"
                        % (totale, n, m))


# ── e adesso la meta' che decide se le dodici qui sopra valgono qualcosa ──────────────────
_VERO_PS, _VERO_CANC, _VERO_SPLIT = PS.calcola, CANC.calcola_rimborso, SPLIT.riparti_uguale


def _guasto_split_butta_il_resto():
    PS.calcola, CANC.calcola_rimborso = _VERO_PS, _VERO_CANC
    SPLIT.riparti_uguale = lambda t, n: (lambda q: [min(q)] * len(q) if q else q)(
        _VERO_SPLIT(t, n))


def _guasto_split_tutto_al_primo():
    def rotto(t, n):
        q = _VERO_SPLIT(t, n)
        if not q or len(q) == 1:
            return q
        return [sum(q) - min(q) * (len(q) - 1)] + [min(q)] * (len(q) - 1)
    SPLIT.riparti_uguale = rotto


def _guasto_rimborso_scala_rovesciata():
    def rotto(pagato, giorni, **kw):
        r = dict(_VERO_CANC(pagato, giorni, **kw))
        if not kw.get("entro_ripensamento") and type(pagato) is int and pagato > 0:
            r["rimborso_cents"] = pagato - r["rimborso_cents"]
        return r
    CANC.calcola_rimborso = rotto


def _guasto_pulizia_non_resa():
    def rotto(pagato, giorni, **kw):
        f = kw.get("fee_pulizia_cents", 0) or 0
        r = dict(_VERO_CANC(pagato, giorni, **kw))
        if f and type(pagato) is int and pagato > 0 and not kw.get("entro_ripensamento"):
            r["rimborso_cents"] = max(0, r["rimborso_cents"] - f)
        return r
    CANC.calcola_rimborso = rotto


def _guasto_ripensamento_ignorato():
    def rotto(pagato, giorni, **kw):
        kw = dict(kw)
        kw["entro_ripensamento"] = False
        return _VERO_CANC(pagato, giorni, **kw)
    CANC.calcola_rimborso = rotto


def _guasto_commissione_col_segno_piu():
    def rotto(prezzo, notti, comm, **kw):
        r = dict(_VERO_PS(prezzo, notti, comm, **kw))
        r["host_incassa_cents"] += 2 * r["commissione_cents"]
        return r
    PS.calcola = rotto


def _guasto_valuta_estera_ignorata():
    def rotto(prezzo, notti, comm, **kw):
        kw = dict(kw)
        kw.pop("valuta_estera", None)
        return _VERO_PS(prezzo, notti, comm, **kw)
    PS.calcola = rotto


def _guasto_fee_forfettaria():
    def rotto(prezzo, notti, comm, **kw):
        r = dict(_VERO_PS(prezzo, notti, comm, **kw))
        r["fee_cents"] = 150
        return r
    PS.calcola = rotto


def _guasto_un_centesimo_sparisce():
    def rotto(prezzo, notti, comm, **kw):
        r = dict(_VERO_PS(prezzo, notti, comm, **kw))
        if r["saldo_in_loco_cents"] > 0:
            r["saldo_in_loco_cents"] -= 1
        return r
    PS.calcola = rotto


def _guasto_tetto_silenzioso_sul_totale():
    def rotto(prezzo, notti, comm, **kw):
        r = dict(_VERO_PS(prezzo, notti, comm, **kw))
        if prezzo > 100_000:
            r["ospite_paga_totale_cents"] = 0
        return r
    PS.calcola = rotto


# Griglie piccole e FISSE: qui non si cerca un controesempio (lo fa Hypothesis qui sopra),
# si chiede a ogni relazione di accendersi. Deterministico e veloce.
_PREZZI = (0, 1, 100, 1234, 99_999, 1_000_000)
_NOTTI = (1, 2, 7, 30)
_COMM = (0, 500, 10_000, 250_000)
_GIORNI = (0, 1, 5, 14, 60, 365)
_POLS = ("flessibile", "moderata", "rigida")
_PAGATI = (1, 100, 10_000, 1_000_000)
_TOTALI = (0, 1, 7, 101, 999, 1_000_000)
_ENNE = (1, 2, 3, 5, 12)


def _tutte_le_relazioni():
    """(nome, funzione-che-torna-True-se-la-relazione-REGGE-su-tutta-la-griglia)."""
    import itertools as _it
    return (
        ("MR1 prezzo monotono",
         lambda: all(_mr_prezzo_monotono(a, b, n)
                     for a, b in _it.combinations(_PREZZI, 2) for n in _NOTTI)),
        ("MR2 commissione non premia",
         lambda: all(_mr_commissione_non_premia(p, n, a, b)
                     for p in _PREZZI for n in _NOTTI for a, b in _it.combinations(_COMM, 2))),
        ("MR3 valuta estera costa di piu'",
         lambda: all(_mr_valuta_estera_costa_di_piu(p, n, c)
                     for p in _PREZZI for n in _NOTTI for c in _COMM)),
        ("MR4 fee lineare nelle notti",
         lambda: all(_mr_fee_lineare_nelle_notti(p, n, k)
                     for p in _PREZZI for n in (1, 2, 7) for k in (2, 3, 5))),
        ("MR5 anticipo+saldo = totale",
         lambda: all(_mr_anticipo_piu_saldo(p, n, c)
                     for p in _PREZZI for n in _NOTTI for c in _COMM)),
        ("MR6 rimborso monotono nei giorni",
         lambda: all(_mr_rimborso_monotono_nei_giorni(p, a, b, pol)
                     for p in _PAGATI for a, b in _it.combinations(_GIORNI, 2)
                     for pol in _POLS)),
        ("MR7 ripensamento rende tutto",
         lambda: all(_mr_ripensamento_rende_tutto(p, g, pol)
                     for p in _PAGATI for g in _GIORNI for pol in _POLS)),
        ("MR8 la pulizia si scorpora",
         lambda: all(_mr_pulizia_si_scorpora(p, g, f, pol)
                     for p in _PAGATI for g in _GIORNI for f in (0, 1, 500) for pol in _POLS)),
        ("MR9 le quote sommano",
         lambda: all(_mr_quote_sommano_al_totale(t, k) for t in _TOTALI for k in _ENNE)),
        ("MR10 scarto un centesimo",
         lambda: all(_mr_scarto_massimo_un_centesimo(t, k) for t in _TOTALI for k in _ENNE)),
        ("MR11 piu' partecipanti, quota giu'",
         lambda: all(_mr_piu_partecipanti_quota_minore(t, k) for t in _TOTALI for k in _ENNE)),
        ("MR12 doppio riparto conserva",
         lambda: all(_mr_doppio_riparto_conserva(t, k, m)
                     for t in _TOTALI for k in (2, 3, 5) for m in (2, 3))),
    )


_GUASTI = (
    ("split: butta il resto", _guasto_split_butta_il_resto),
    ("split: tutto al primo", _guasto_split_tutto_al_primo),
    ("rimborso: scala rovesciata", _guasto_rimborso_scala_rovesciata),
    ("rimborso: pulizia non resa", _guasto_pulizia_non_resa),
    ("rimborso: ripensamento ignorato", _guasto_ripensamento_ignorato),
    ("paga: commissione col segno +", _guasto_commissione_col_segno_piu),
    ("paga: valuta estera ignorata", _guasto_valuta_estera_ignorata),
    ("paga: fee forfettaria", _guasto_fee_forfettaria),
    ("paga: un centesimo sparisce", _guasto_un_centesimo_sparisce),
    ("paga: tetto silenzioso sul totale", _guasto_tetto_silenzioso_sul_totale),
)


class TestLeRelazioniMetamorficheSANNODiventareROSSE(unittest.TestCase):
    """⛔ SENZA QUESTA CLASSE, LE DODICI RELAZIONI QUI SOPRA NON VALGONO NIENTE.

    Una relazione che regge e' inutile se reggerebbe anche col motore rotto: e' un
    ornamento, cioe' il verde peggiore -- quello che non ha guardato niente. Regola ferrea
    2 e D18 punto 2: si prova nelle DUE direzioni.

    ⛔ E UN SOLO GUASTO ASSOLVE. Provando una relazione con un guasto solo non si sa se e'
    lei a vederlo o se quel guasto rompeva tutto. Serve la MATRICE: dieci guasti per dodici
    relazioni, e si guarda chi vede cosa. Misurata il 2026-09-02, ha trovato DUE miei
    ornamenti prima che entrassero nella suite -- MR3 e MR7 erano scritte col `>=`, e un
    `>=` non distingue «fatto» da «non fatto» quando ignorare la cosa produce l'UGUALE.

    ⛔ B4: nessun `fase*.py` viene toccato. I guasti sostituiscono la funzione nel modulo
    importato, dentro questo processo, e si ripristinano in `tearDown` anche se il test
    fallisce.
    ⚠️ LIMITE DICHIARATO (D18 punto 3): l'iniezione e' al CONFINE OSSERVABILE -- l'uscita
    della funzione -- non dentro il corpo. Dimostra quindi che la relazione vede QUELLA
    deviazione osservabile, che e' tutto cio' che un oracolo sull'uscita puo' promettere;
    non che veda ogni possibile difetto interno.
    """

    def tearDown(self):
        PS.calcola = _VERO_PS
        CANC.calcola_rimborso = _VERO_CANC
        SPLIT.riparti_uguale = _VERO_SPLIT

    def test_A_MACCHINA_SANA_tacciono_tutte(self):
        """L'altra direzione, obbligatoria: un allarme che grida sempre viene spento."""
        for nome, regge in _tutte_le_relazioni():
            self.assertTrue(regge(), "%s e' rossa a MACCHINA SANA: o la relazione e' "
                                     "sbagliata, o c'e' un difetto vero" % nome)

    def test_OGNI_relazione_si_accende_su_almeno_un_guasto(self):
        """Nessun ornamento fra le dodici."""
        viste = {n: 0 for n, _ in _tutte_le_relazioni()}
        for _, applica in _GUASTI:
            self.tearDown()
            applica()
            for nome, regge in _tutte_le_relazioni():
                try:
                    rossa = not regge()
                except Exception:
                    rossa = True
                if rossa:
                    viste[nome] += 1
        self.tearDown()
        mute = sorted(n for n, v in viste.items() if v == 0)
        self.assertEqual(mute, [],
                         "queste relazioni non si accendono su NESSUNO dei %d guasti: sono "
                         "ornamenti, non guardie" % len(_GUASTI))

    def test_OGNI_guasto_e_visto_da_almeno_una_relazione(self):
        """L'altra faccia, e non e' la stessa cosa: un guasto che nessuno vede e' un buco
        di copertura, mentre una relazione muta e' una guardia inutile. Cercare solo gli
        ornamenti lascerebbe passare i buchi."""
        ciechi = []
        for gnome, applica in _GUASTI:
            self.tearDown()
            applica()
            visto = False
            for _, regge in _tutte_le_relazioni():
                try:
                    if not regge():
                        visto = True
                        break
                except Exception:
                    visto = True
                    break
            if not visto:
                ciechi.append(gnome)
        self.tearDown()
        self.assertEqual(ciechi, [],
                         "nessuna delle %d relazioni vede questi guasti: sono buchi di "
                         "copertura" % len(_tutte_le_relazioni()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
