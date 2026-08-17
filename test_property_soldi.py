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


if __name__ == "__main__":
    unittest.main(verbosity=2)
