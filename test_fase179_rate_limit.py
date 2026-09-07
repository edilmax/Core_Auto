# -*- coding: utf-8 -*-
"""IL DEDICATO DI fase179_rate_limit — il buttafuori dei tentativi di accesso.

Fino al 2026-09-06 questo modulo non aveva un test dedicato: il Giudice lo dichiarava NON
GIUDICABILE (17 punti mai esaminati). Qui ogni guardia misura un COMPORTAMENTO con l'orologio
iniettato, non una riga: la soglia esatta, la finestra che dimentica, il blocco che raddoppia
fino al tetto, lo sblocco al secondo giusto, il successo che azzera, lo sfratto delle chiavi
vecchie, gli ingressi non validi che non lasciano traccia.

VISTA ROSSA (2026-09-06, con l'editor, ripristino byte-identico sha256): fase179:87 `>=` -> `>`
(la soglia esclude il confine) -> `test_l_ottavo_fallimento_blocca_il_settimo_no` ROSSO;
fase179:89 `min` tolto (nessun tetto) -> `test_il_blocco_raddoppia_fino_al_tetto_e_non_oltre`
ROSSO.
"""
import unittest

from fase179_rate_limit import RateLimiter, crea_rate_limiter


class _Orologio:
    def __init__(self, t=1_000_000.0):
        self.t = float(t)

    def __call__(self):
        return self.t

    def avanza(self, sec):
        self.t += sec


def _limiter(**kw):
    oro = _Orologio()
    base = dict(soglia=8, finestra_sec=60, base_blocco_sec=30, max_blocco_sec=120,
                max_chiavi=100, orologio=oro)
    base.update(kw)
    return crea_rate_limiter(**base), oro


class TestIlButtafuoriDeiTentativi(unittest.TestCase):

    def test_l_ottavo_fallimento_blocca_il_settimo_no(self):
        rl, _ = _limiter(soglia=8)
        for i in range(7):
            self.assertEqual(rl.fallito("k"), (False, 0), "fallimento %d non deve bloccare" % (i + 1))
            self.assertEqual(rl.consenti("k"), (True, 0))
        self.assertEqual(rl.fallito("k"), (True, 30), "l'ottavo blocca per la durata base")
        ok, attesa = rl.consenti("k")
        self.assertFalse(ok)
        self.assertEqual(attesa, 31, "attesa = secondi che restano + 1")

    def test_il_blocco_finisce_al_secondo_giusto_e_non_prima(self):
        rl, oro = _limiter(soglia=2, base_blocco_sec=30)
        rl.fallito("k")
        self.assertEqual(rl.fallito("k"), (True, 30))
        oro.avanza(29.5)
        self.assertEqual(rl.consenti("k")[0], False, "a 29,5 s e' ancora bloccato")
        oro.avanza(0.5)
        self.assertEqual(rl.consenti("k"), (True, 0), "a 30 s esatti il blocco e' finito (blocco_fino > ora e' falso)")

    def test_il_blocco_raddoppia_fino_al_tetto_e_non_oltre(self):
        rl, oro = _limiter(soglia=2, base_blocco_sec=30, max_blocco_sec=100)
        durate = []
        for _ in range(5):
            rl.fallito("k")
            bloccato, dur = rl.fallito("k")
            self.assertTrue(bloccato)
            durate.append(dur)
            oro.avanza(dur)                      # aspetta la fine del blocco
        self.assertEqual(durate, [30, 60, 100, 100, 100],
                         "30 -> 60 -> (120 tagliato a) 100 -> 100 -> 100")

    def test_dopo_il_blocco_il_conteggio_riparte_da_zero(self):
        rl, oro = _limiter(soglia=3, base_blocco_sec=10)
        for _ in range(2):
            rl.fallito("k")
        self.assertEqual(rl.fallito("k")[0], True)
        oro.avanza(10)
        self.assertEqual(rl.consenti("k"), (True, 0))
        self.assertEqual(rl.fallito("k"), (False, 0), "un fallimento dopo il blocco NON riblocca subito")
        self.assertEqual(rl.fallito("k"), (False, 0))
        self.assertEqual(rl.fallito("k")[0], True, "servono di nuovo TRE fallimenti")

    def test_la_finestra_dimentica_i_fallimenti_vecchi_ma_non_quello_sul_confine(self):
        rl, oro = _limiter(soglia=3, finestra_sec=60)
        rl.fallito("k")                          # t=0
        oro.avanza(60)
        rl.fallito("k")                          # t=60: quello di t=0 sta ESATTAMENTE sul confine e conta
        self.assertEqual(rl.fallito("k")[0], True, "a 60 s il primo fallimento conta ancora (>= taglio)")
        rl2, oro2 = _limiter(soglia=3, finestra_sec=60)
        rl2.fallito("k")                         # t=0
        oro2.avanza(60.5)
        rl2.fallito("k")                         # t=60,5: quello di t=0 e' fuori finestra
        self.assertEqual(rl2.fallito("k"), (False, 0), "a 60,5 s il primo e' dimenticato: due soli nella finestra")

    def test_il_successo_azzera_tutto_per_quella_chiave(self):
        rl, _ = _limiter(soglia=3)
        rl.fallito("k")
        rl.fallito("k")
        rl.riuscito("k")
        self.assertEqual(rl.stato("k"), {"fail": [], "blocco_fino": 0.0, "lockout": 0})
        rl.fallito("k")
        rl.fallito("k")
        self.assertEqual(rl.fallito("k")[0], True, "dopo l'azzeramento servono di nuovo tre fallimenti")
        # e il lockout esponenziale riparte: la durata torna quella base
        rl2, oro2 = _limiter(soglia=2, base_blocco_sec=30)
        rl2.fallito("k")
        rl2.fallito("k")                          # blocco 1: 30 s
        oro2.avanza(30)
        rl2.riuscito("k")
        rl2.fallito("k")
        self.assertEqual(rl2.fallito("k"), (True, 30), "dopo un successo il raddoppio riparte da capo")

    def test_le_chiavi_sono_separate(self):
        rl, _ = _limiter(soglia=2)
        rl.fallito("email:a")
        self.assertEqual(rl.fallito("email:a")[0], True)
        self.assertEqual(rl.consenti("email:b"), (True, 0))
        self.assertEqual(rl.consenti("ip:1.2.3.4"), (True, 0))
        self.assertEqual(rl.fallito("email:b"), (False, 0))

    def test_una_chiave_non_valida_non_blocca_e_non_lascia_traccia(self):
        rl, _ = _limiter(soglia=1)
        for chiave in ("", None, 0, b"x", ["k"]):
            self.assertEqual(rl.consenti(chiave), (True, 0))
            self.assertEqual(rl.fallito(chiave), (False, 0))
            rl.riuscito(chiave)
        self.assertEqual(rl._m, {}, "nessuna riga creata per chiavi non valide")

    def test_lo_sfratto_butta_la_chiave_MENO_recente_e_tiene_le_altre(self):
        rl, oro = _limiter(max_chiavi=100)
        for i in range(100):
            rl.fallito("k%03d" % i)
            oro.avanza(1)
        rl.consenti("k000")                      # la piu' vecchia viene rivista: ora e' la piu' recente
        oro.avanza(1)
        rl.fallito("k100")                       # la 101esima: qualcuno deve uscire
        self.assertEqual(len(rl._m), 100)
        self.assertIn("k000", rl._m, "rivista di recente: resta")
        self.assertNotIn("k001", rl._m, "la meno recente e' k001: sfrattata")
        self.assertIn("k100", rl._m)

    def test_i_parametri_assurdi_vengono_riportati_a_valori_sensati(self):
        rl = RateLimiter(soglia=0, finestra_sec=0, base_blocco_sec=0, max_blocco_sec=0, max_chiavi=5)
        self.assertEqual(rl._soglia, 1)
        self.assertEqual(rl._finestra, 1)
        self.assertEqual(rl._base, 1)
        self.assertEqual(rl._max, 1, "il tetto non scende sotto la base")
        self.assertEqual(rl._max_chiavi, 100)
        rl2 = RateLimiter(base_blocco_sec=50, max_blocco_sec=10)
        self.assertEqual(rl2._max, 50, "tetto sotto la base -> tetto = base")

    def test_stato_dice_il_vero_e_consenti_aggiorna_visto(self):
        # `stato()` e' una copia SUPERFICIALE (dict(r)): la lista `fail` resta condivisa. Il
        # modulo non promette di piu' e nessun chiamante la modifica; qui si guarda cio' che
        # promette: i campi giusti, e `visto` che si muove a ogni `consenti`.
        rl, oro = _limiter()
        rl.fallito("k")
        s = rl.stato("k")
        self.assertEqual(sorted(s), ["blocco_fino", "fail", "lockout", "visto"])
        self.assertEqual(len(s["fail"]), 1)
        s["lockout"] = 99
        self.assertEqual(rl.stato("k")["lockout"], 0, "il dict restituito non e' quello interno")
        oro.avanza(5)
        rl.consenti("k")
        self.assertEqual(rl.stato("k")["visto"], oro())
        self.assertEqual(rl.stato("mai-vista"), {"fail": [], "blocco_fino": 0.0, "lockout": 0})


if __name__ == "__main__":
    unittest.main()
