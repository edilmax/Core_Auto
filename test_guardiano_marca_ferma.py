# -*- coding: utf-8 -*-
"""Guardia ALLARME «MARCA TEMPORALE FERMA» (fase186).

IL BUCO (trovato il 2026-07-30 verificando la produzione): il giro giornaliero riduce contratti
e libro giornale a un'impronta e la fa datare da un'Autorita' esterna (RFC 3161). Se la TSA
tace, il giro archivia il tentativo e riprova **in silenzio**: si potrebbero passare settimane
senza prove datate da un terzo e scoprirlo soltanto in causa. Il guardiano sorvegliava escrow,
bonifici, payout e cambio valuta — ma NON l'asset legale.
E' il modo-di-rompersi n.6 del progetto ("il terzo che cambia") applicato alle prove.

LA CORREZIONE: `_marca_temporale_ferma` — read-only sull'ultima marca RIUSCITA; oltre
ORE_MARCA_FERMA (48h = due giri giornalieri saltati) il guardiano GRIDA.

VISTO ROSSO: togliendo la chiamata `_marca_temporale_ferma` da `scansiona` questi test
falliscono (il guardiano resta 'pulito' mentre le prove non sono piu' datate).
"""
import unittest

from fase186_guardiano import ORE_MARCA_FERMA, _TITOLI, riassunto_html, scansiona

ORA = 1_800_000_000          # istante di riferimento del test
OROLOGIO = lambda: ORA       # `scansiona(ora=...)` vuole un OROLOGIO, non un numero


class _ArchivioMarcheFinto:
    """Solo cio' che il guardiano legge: l'ultima marca riuscita."""

    def __init__(self, righe):
        self._righe = righe

    def elenco(self, limit=100, solo_ok=False):
        righe = [r for r in self._righe if r.get("stato") == "ok"] if solo_ok else self._righe
        return righe[:limit]


class _Sistema:
    def __init__(self, marche=None):
        self.marche = marche


def _marca(ore_fa, giorno="2026-07-28"):
    return {"id": 1, "giorno": giorno, "ambito": "registri", "stato": "ok",
            "richiesto_ts": ORA - int(ore_fa * 3600), "gen_time": ORA - int(ore_fa * 3600)}


class TestAllarmeMarcaFerma(unittest.TestCase):

    def _anomalia(self, sistema):
        return scansiona(sistema, ora=OROLOGIO).get("anomalie", {}).get("marca_temporale_ferma")

    # ── DEVE GRIDARE ────────────────────────────────────────────────────────
    def test_grida_se_l_ultima_marca_e_troppo_vecchia(self):
        a = self._anomalia(_Sistema(_ArchivioMarcheFinto([_marca(ore_fa=ORE_MARCA_FERMA + 5)])))
        self.assertIsNotNone(a, "prove non piu' datate da un terzo e il guardiano tace")
        self.assertGreater(a["eta_ore"], ORE_MARCA_FERMA)
        self.assertFalse(a["mai_riuscita"])
        self.assertEqual(a["soglia_ore"], ORE_MARCA_FERMA)

    def test_grida_se_non_c_e_MAI_riuscita_una_marca(self):
        """Archivio con soli tentativi falliti: e' il caso peggiore, mai una prova datata."""
        a = self._anomalia(_Sistema(_ArchivioMarcheFinto(
            [{"id": 1, "giorno": "2026-07-01", "stato": "errore", "richiesto_ts": ORA - 3600}])))
        self.assertIsNotNone(a, "nessuna marca riuscita e il guardiano tace")
        self.assertTrue(a["mai_riuscita"])

    def test_il_messaggio_al_fondatore_dice_cosa_e_successo(self):
        rep = scansiona(_Sistema(_ArchivioMarcheFinto([_marca(ore_fa=100)])), ora=OROLOGIO)
        self.assertFalse(rep["pulito"])
        html = riassunto_html(rep)
        # il titolo nell'email e' XSS-safe (l'apostrofo diventa &#x27;): si confrontano i
        # pezzi che sopravvivono all'escape, non la stringa letterale
        self.assertIn("Marca temporale ferma", html)
        self.assertIn("datati da un terzo", html)
        self.assertIn("eta_ore", html)          # il fondatore vede DA QUANTO e' ferma
        self.assertIn("100.0", html)
        self.assertTrue(_TITOLI["marca_temporale_ferma"].startswith("Marca temporale ferma"))

    # ── NON DEVE GRIDARE ────────────────────────────────────────────────────
    def test_tace_se_la_marca_di_oggi_c_e(self):
        rep = scansiona(_Sistema(_ArchivioMarcheFinto([_marca(ore_fa=2)])), ora=OROLOGIO)
        self.assertIsNone(rep["anomalie"].get("marca_temporale_ferma"))

    def test_tace_al_limite_esatto_della_soglia(self):
        """Alla soglia esatta non si grida: si grida OLTRE (niente allarmi al minuto zero)."""
        rep = scansiona(_Sistema(_ArchivioMarcheFinto([_marca(ore_fa=ORE_MARCA_FERMA)])),
                        ora=OROLOGIO)
        self.assertIsNone(rep["anomalie"].get("marca_temporale_ferma"))

    def test_tace_su_un_impianto_APPENA_NATO(self):
        """Archivio VUOTO = installazione nuova, non un guasto. Gridare qui sarebbe un falso
        allarme — e un falso allarme insegna a ignorare i rossi. (Difetto della mia prima
        stesura, colto dal test del sistema sano: `test_su_tutto_pulito_il_guardiano_TACE`.)"""
        rep = scansiona(_Sistema(_ArchivioMarcheFinto([])), ora=OROLOGIO)
        self.assertIsNone(rep["anomalie"].get("marca_temporale_ferma"))

    def test_tace_se_la_funzione_e_spenta(self):
        """Nessun archivio marche (installazione senza prove legali) -> niente allarme."""
        rep = scansiona(_Sistema(marche=None), ora=OROLOGIO)
        self.assertIsNone(rep["anomalie"].get("marca_temporale_ferma"))

    def test_un_archivio_rotto_non_ferma_il_guardiano(self):
        """Il guardiano deve continuare a controllare tutto il resto anche se qui esplode."""
        class _Rotto:
            def elenco(self, limit=100, solo_ok=False):
                raise RuntimeError("archivio illeggibile")
        rep = scansiona(_Sistema(_Rotto()), ora=OROLOGIO)
        self.assertIsInstance(rep.get("anomalie"), dict)
        self.assertIsNone(rep["anomalie"].get("marca_temporale_ferma"))


if __name__ == "__main__":
    unittest.main()
