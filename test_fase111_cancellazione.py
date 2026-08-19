"""Test Fase 111 - Cancellazione flessibile + rimborso. Puro, cents interi.
Soglie allineate agli standard mondiali (Airbnb/Booking/Vrbo) + finestra di ripensamento 48h."""
import unittest

from fase111_cancellazione import (POLITICHE, PoliticaCancellazione, calcola_rimborso,
                                   crea_politica_cancellazione)


class TestRimborso(unittest.TestCase):
    def test_flessibile_pieno(self):
        r = calcola_rimborso(10000, 5, politica="flessibile")
        self.assertEqual(r["rimborso_cents"], 10000)        # >=1 giorno -> 100%
        self.assertEqual(r["trattenuto_cents"], 0)

    def test_flessibile_stesso_giorno_meta(self):
        r = calcola_rimborso(10000, 0, politica="flessibile")
        self.assertEqual(r["rimborso_cents"], 5000)         # 0 giorni -> 50%

    def test_moderata_scaglioni(self):
        self.assertEqual(calcola_rimborso(10000, 5, politica="moderata")["rimborso_cents"], 10000)
        self.assertEqual(calcola_rimborso(10000, 3, politica="moderata")["rimborso_cents"], 5000)
        self.assertEqual(calcola_rimborso(10000, 0, politica="moderata")["rimborso_cents"], 0)

    def test_rigida_soglie_stile_airbnb_firm(self):
        # rigida = Airbnb "Firm": 100% >=30gg, 50% 7-30gg, 0% <7gg
        self.assertEqual(calcola_rimborso(10000, 30, politica="rigida")["rimborso_cents"], 10000)
        self.assertEqual(calcola_rimborso(10000, 29, politica="rigida")["rimborso_cents"], 5000)
        self.assertEqual(calcola_rimborso(10000, 7, politica="rigida")["rimborso_cents"], 5000)
        self.assertEqual(calcola_rimborso(10000, 6, politica="rigida")["rimborso_cents"], 0)
        self.assertEqual(calcola_rimborso(10000, 0, politica="rigida")["rimborso_cents"], 0)

    def test_non_rimborsabile(self):
        # 0% sempre (ma vedi ripensamento: la finestra 48h vince comunque)
        self.assertEqual(calcola_rimborso(10000, 90, politica="non_rimborsabile")["rimborso_cents"], 0)
        self.assertEqual(calcola_rimborso(10000, 1, politica="non_rimborsabile")["trattenuto_cents"], 10000)

    def test_ripensamento_vince_su_ogni_politica(self):
        # finestra di ripensamento 48h -> 100% anche su rigida e non_rimborsabile
        for pol in ("flessibile", "moderata", "rigida", "non_rimborsabile"):
            r = calcola_rimborso(10000, 3, politica=pol, entro_ripensamento=True)
            self.assertEqual(r["rimborso_cents"], 10000, pol)
            self.assertEqual(r["trattenuto_cents"], 0, pol)
            self.assertTrue(r.get("ripensamento"))

    def test_ripensamento_non_crea_soldi_dal_nulla(self):
        # fail-closed: input invalido resta 0 anche con ripensamento
        self.assertEqual(calcola_rimborso(0, 3, entro_ripensamento=True)["rimborso_cents"], 0)
        self.assertEqual(calcola_rimborso(-5, 3, entro_ripensamento=True)["rimborso_cents"], 0)

    def test_fee_pulizia_sempre_resa(self):
        # rigida, 2 giorni -> soggiorno 0%, ma pulizia 2000 sempre rimborsata
        r = calcola_rimborso(12000, 2, politica="rigida", fee_pulizia_cents=2000)
        self.assertEqual(r["rimborso_cents"], 2000)
        self.assertEqual(r["trattenuto_cents"], 10000)

    def test_input_invalido_failclosed(self):
        self.assertEqual(calcola_rimborso(0, 5)["rimborso_cents"], 0)
        self.assertEqual(calcola_rimborso(-5, 5)["rimborso_cents"], 0)
        self.assertEqual(calcola_rimborso(10000, -3, politica="moderata")["rimborso_cents"], 0)

    def test_mai_piu_del_pagato(self):
        # invariante "noi mai in perdita": rimborso <= pagato, sempre
        for g in (-5, 0, 1, 7, 30, 100):
            for pol in POLITICHE:
                r = calcola_rimborso(10000, g, politica=pol)
                self.assertLessEqual(r["rimborso_cents"], 10000)
                self.assertEqual(r["rimborso_cents"] + r["trattenuto_cents"], 10000)

    def test_cents_interi_e_conservazione(self):
        r = calcola_rimborso(9999, 3, politica="moderata")
        self.assertIsInstance(r["rimborso_cents"], int)
        self.assertEqual(r["rimborso_cents"] + r["trattenuto_cents"], 9999)

    def test_politica_custom(self):
        pol = crea_politica_cancellazione("x", [(2, 10000), (0, 2000)])
        self.assertIsInstance(pol, PoliticaCancellazione)
        self.assertEqual(calcola_rimborso(10000, 0, politica=pol)["rimborso_cents"], 2000)

    def test_politica_sconosciuta_usa_flessibile(self):
        self.assertEqual(calcola_rimborso(10000, 5, politica="boh")["politica"], "flessibile")

    # --- FLOOR del rimborso parziale (Flow 4 micro-stepping): mai over-refund di 1 cent ---
    def test_rimborso_parziale_FLOOR_non_arrotonda_su(self):
        # 9999 * 50% = 4999.5 -> DEVE fare FLOOR (4999), non round (5000). Con round() si
        # rimborserebbe 1 cent di troppo (noi in perdita). Nessun test lo bloccava: la
        # conservazione (rimborso+trattenuto=pagato) resta vera anche arrotondando su.
        r = calcola_rimborso(9999, 3, politica="moderata")          # moderata@3gg -> bps 5000
        self.assertEqual(r["bps"], 5000)
        self.assertEqual(r["rimborso_cents"], 4999, "rimborso non FLOORato (over-refund di 1 cent)")
        self.assertEqual(r["trattenuto_cents"], 5000)
        self.assertEqual(round(9999 * 5000 / 10000), 5000)          # prova: round() darebbe 5000

    def test_rimborso_non_supera_mai_la_quota_esatta(self):
        # invariante FLOOR non-circolare: rimborso <= quota proporzionale ESATTA, sempre.
        # (rimborso*10000 <= soggiorno*bps) <=> il rimborso non eccede mai la frazione esatta.
        # Rosso se qualcuno passa a round()/ceil (over-refund su importi dispari).
        for pagato in (9999, 10001, 12345, 7777, 33333, 1, 3, 101):
            for pol_nome in POLITICHE:
                for g in (0, 1, 5, 7, 30):
                    r = calcola_rimborso(pagato, g, politica=pol_nome)   # fee=0 -> soggiorno=pagato
                    self.assertLessEqual(
                        r["rimborso_cents"] * 10000, pagato * r["bps"],
                        "OVER-REFUND: pagato=%d pol=%s g=%d -> rimborso %d supera la quota esatta"
                        % (pagato, pol_nome, g, r["rimborso_cents"]))


class TestIDueBUCHITrovatiDalGiudice(unittest.TestCase):
    """I due punti che il Giudice ha trovato SCOPERTI il 2026-08-19 (11 punti, 7 uccisi,
    4 sopravvissuti). Gli altri due sopravvissuti sono **provati equivalenti**, con la
    dimostrazione scritta in `EQUIVALENTI_DICHIARATI`: qui ci sono solo i buchi VERI.

    ⛔ Nessuno dei due sta nell'aritmetica del rimborso, che era gia' sorvegliata bene.
    Stanno tutt'e due **al confine**, dove un valore entra da fuori e viene interpretato --
    ed e' esattamente la lezione che il primo modulo dei soldi aveva gia' insegnato il
    2026-08-12: *i difetti veri non stanno nel calcolo, stanno nel passaggio dove un modulo
    traduce un valore per un altro*.
    """

    def test_un_BOOLEANO_come_giorni_NON_vale_un_giorno(self):
        """⛔ IL BUCO CHE COSTA SOLDI VERI.

        In Python `True` **e'** un intero, e vale 1. Il modulo lo sa e lo esclude apposta
        (`not isinstance(giorni_all_arrivo, bool)`), ma nessun test lo verificava: il Giudice
        ha rotto quella condizione (`and` -> `or`) e **tutti i test sono rimasti verdi**.

        Col guasto dentro, `True` verrebbe letto come **1 giorno all'arrivo** invece che 0, e
        sulla politica flessibile (1 giorno = 100%, 0 giorni = 50%) il rimborso RADDOPPIA:
        su 200,00 EUR si restituirebbero 200,00 invece di 100,00. **Cento euro regalati per
        un booleano**, su ogni cancellazione che arrivi con quel valore.

        ⚠️ E non e' un caso di laboratorio: `True`/`False` arrivano da JSON, da un campo di
        modulo, da un confronto scritto male a monte. La regola del progetto e' la stessa da
        sempre -- **il difetto e' spesso in chi chiama** -- e questo modulo si difende bene:
        mancava solo chi lo dimostrasse.
        """
        for booleano in (True, False):
            r = calcola_rimborso(20000, booleano, politica="flessibile")
            self.assertEqual(
                r["bps"], 5000,
                "giorni=%r e' stato letto come un numero di giorni: un booleano NON e' un "
                "giorno, e leggerlo cosi' cambia quanto si restituisce (bps=%d)"
                % (booleano, r["bps"]))
            self.assertEqual(
                r["rimborso_cents"], 10000,
                "giorni=%r ha prodotto un rimborso di %d cents invece di 10000: su questa "
                "politica un giorno in piu' vale il DOPPIO del rimborso"
                % (booleano, r["rimborso_cents"]))
        # e l'altra direzione, che rende il confronto leggibile: 1 giorno VERO vale il doppio
        self.assertEqual(calcola_rimborso(20000, 1, politica="flessibile")["rimborso_cents"],
                         20000, "un giorno vero vale il 100%: se cambia, cambia il senso "
                                "del controllo qui sopra")

    def test_un_intero_che_MENTE_sul_confronto_non_ottiene_un_rimborso(self):
        """⛔ IL DIFETTO PIU' CARO DEI TRE, e non l'ha trovato un mutante: l'ha trovato la
        GUARDIA DELLO SCHEDARIO, bocciando una mia dichiarazione di equivalenza.

        Avevo dichiarato equivalenti due mutanti dimostrandolo con z3 «su tutti gli interi».
        La guardia e' andata rossa con la ragione scritta dentro di se': *«il risolutore
        ragiona sugli INTERI, la funzione accetta `Any` -- non ha sbagliato lui, gli era
        stata fatta la domanda sbagliata»*. Andando a vedere cosa ci fosse in quel pezzo di
        dominio che la mia prova NON copriva, e' saltato fuori un buco vero.

        `isinstance(v, int)` accetta anche le SOTTOCLASSI di `int`, e una sottoclasse puo'
        **riscrivere il confronto**. Misurato sul codice di produzione, politica «rigida»
        (30+ giorni = 100%, 7+ = 50%, altrimenti ZERO):
            giorni = 0 (intero vero) -> rimborso      0 cents
            giorni = una sottoclasse che dice sempre «sono >= di tutto»
                                     -> rimborso 20.000 cents
        **Duecento euro regalati** su una prenotazione che secondo la politica non ne
        prevedeva nemmeno uno.

        ⚠️ Il modulo dichiara di essere «BLINDATO: input invalido -> rimborso 0
        (fail-closed)». Lo era per i tipi sbagliati, non per i tipi **camuffati**. La cura e'
        pretendere l'intero VERO (`type(x) is int`), che chiude anche i booleani senza
        bisogno di nominarli: `type(True) is bool`, non `int`.
        """
        class Bugiarda(int):
            """Un intero che mente: a ogni confronto risponde «sono maggiore o uguale»."""
            def __ge__(self, altro):
                return True

        class Falsa(int):
            """Un intero che mente sull'uguaglianza: non e' mai uguale a niente."""
            def __eq__(self, altro):
                return False

            def __hash__(self):
                return 0

        for politica in ("rigida", "moderata", "flessibile", "non_rimborsabile"):
            atteso = calcola_rimborso(20000, 0, politica=politica)
            camuffato = calcola_rimborso(20000, Bugiarda(0), politica=politica)
            self.assertEqual(
                camuffato["rimborso_cents"], atteso["rimborso_cents"],
                "politica %r: un valore che MENTE sul confronto ha ottenuto %d cents invece "
                "di %d. Un tipo camuffato non deve poter scegliere lo scaglione: il modulo "
                "dichiara fail-closed, e fail-closed vuol dire che l'ignoto vale ZERO"
                % (politica, camuffato["rimborso_cents"], atteso["rimborso_cents"]))

        # e lo stesso vale per il PREZZO: un importo che mente non deve attraversare la
        # porta d'ingresso e finire nell'aritmetica del rimborso
        finto = calcola_rimborso(Falsa(0), 5, politica="moderata")
        self.assertEqual(
            (finto["rimborso_cents"], finto["bps"]), (0, 0),
            "un prezzo che mente sull'uguaglianza e' passato dalla porta: rimborso=%d "
            "bps=%d. Su un importo zero camuffato il modulo deve restituire zero e "
            "dichiarare zero" % (finto["rimborso_cents"], finto["bps"]))

    def test_la_politica_di_cancellazione_NON_si_puo_riscrivere_a_caldo(self):
        """⛔ IL SECONDO BUCO: le politiche erano CONGELATE e nessuno lo pretendeva.

        `PoliticaCancellazione` e' `frozen=True` apposta: sono le regole con cui si decide
        quanto denaro torna all'ospite, e devono essere **costanti**, non oggetti che
        chiunque puo' riscrivere mentre il programma gira. Il Giudice ha tolto quel congelo
        (`frozen=True` -> `False`) e nessun test se n'e' accorto.

        Col guasto dentro, una riga qualsiasi del programma -- o un modulo importato -- puo'
        fare `POLITICHE["rigida"].scaglioni = ((0, 10000),)` e da quel momento **ogni**
        cancellazione rimborsa il 100%, senza che nulla risulti rotto e senza lasciare
        traccia. E' il modo di rompersi n. 4 applicato ai soldi: non un calcolo sbagliato,
        ma una regola che si puo' cambiare sotto i piedi di chi la usa.
        """
        for nome, politica in POLITICHE.items():
            with self.assertRaises(Exception, msg="la politica %r si lascia riscrivere: "
                                                  "le regole del rimborso devono essere "
                                                  "costanti" % nome):
                politica.scaglioni = ((0, 10000),)
            with self.assertRaises(Exception, msg="il NOME della politica %r si lascia "
                                                  "riscrivere" % nome):
                politica.nome = "inventata"
        # ...e dopo i tentativi le politiche sono ancora quelle di prima (nessun danno)
        self.assertEqual(POLITICHE["rigida"].scaglioni, ((30, 10000), (7, 5000), (0, 0)),
                         "la politica rigida e' cambiata dopo i tentativi di scrittura")


if __name__ == "__main__":
    unittest.main()
