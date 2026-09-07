# -*- coding: utf-8 -*-
"""LA GUARDIA DELL'ESAME DEGLI ACCESSI (D18 punto 4): se qualcuno toglie all'attrezzo il
controllo che gli impedisce di barare, qui diventa rosso lo stesso giorno.

Niente rete: i giudizi sono puri (letture -> passi) e si provano con letture costruite; il
router locale si costruisce UNA volta (pochi secondi) per l'enumerazione e per la prova
«senza credenziali» sulle rotte vere.

VISTA ROSSA (2026-09-06, con l'editor, ripristino byte-identico): in `giudica_scrive`, la riga
che mette una rotta 2xx non dichiarata fra le `aperte` e' stata spostata fra le `dichiarate_2xx`
-> `test_una_porta_aperta_non_dichiarata_e_ROSSA` rosso; in `rotte_dal_codice` la riga che
aggiunge le rotte servite fuori dal router e' stata tolta -> `test_le_rotte_vengono_dal_codice`
rosso (manca `/api/bunker/marca.tsr`).
"""
import contextlib
import io
import os
import shutil
import sys
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(QUI, "collaudi"))

import esame_accessi as ea  # noqa: E402


class TestLEsameDegliAccessiNonPuoBARARE(unittest.TestCase):

    # ── D18 punto 2: le due direzioni, su letture costruite ─────────────────────────
    def test_l_autoprova_passa(self):
        riuscita, righe = ea.autoprova()
        self.assertTrue(riuscita, "\n".join(righe))

    def test_letture_sane_sono_VERDI_in_tutte_e_tre_le_caselle(self):
        for casella, giudica in ea.GIUDIZI.items():
            verde, _p, motivi, den = giudica(ea.letture_finte())
            self.assertTrue(verde, "%s: %s" % (casella, motivi))
            self.assertGreater(den, 0, casella)

    def test_una_porta_aperta_non_dichiarata_e_ROSSA(self):
        verde, _p, motivi, _d = ea.giudica_scrive(ea.letture_finte(aperta="/api/host/porta"))
        self.assertFalse(verde)
        self.assertTrue(any("/api/host/porta" in m for m in motivi), motivi)

    def test_un_200_a_vuoto_DICHIARATO_resta_verde_e_uno_non_dichiarato_no(self):
        verde, _p, _m, _d = ea.giudica_scrive(ea.letture_finte(aperta_dichiarata=True))
        self.assertTrue(verde)
        storte = ea.letture_finte()
        storte["rotte"].append({"metodo": "POST", "path": "/api/host/nuova_rotta", "gestore": "g",
                                "senza": 200, "altro_host": None})
        verde, _p, motivi, _d = ea.giudica_scrive(storte)
        self.assertFalse(verde, motivi)

    def test_l_altro_host_che_VEDE_i_dati_di_A_e_ROSSO_e_la_lista_propria_no(self):
        verde, _p, motivi, _d = ea.giudica_matrice(ea.letture_finte(altro_200="/api/host/x"))
        self.assertFalse(verde, motivi)
        verde, _p, motivi, _d = ea.giudica_matrice(ea.letture_finte(altro_200_proprio="/api/host/miei"))
        self.assertTrue(verde, motivi)

    def test_una_sonda_che_riceve_404_e_ROSSA_e_un_controllo_che_non_da_404_pure(self):
        verde, _p, motivi, _d = ea.giudica_sonde(ea.letture_finte(vivo_404="/api/admin/x"))
        self.assertFalse(verde, motivi)
        verde, _p, motivi, _d = ea.giudica_sonde(ea.letture_finte(controllo=200))
        self.assertFalse(verde, motivi)

    def test_senza_letture_dal_vivo_le_caselle_2_e_3_NON_sono_verdi(self):
        for casella in ("matrice", "sonde"):
            verde, _p, motivi, _d = ea.GIUDIZI[casella](ea.letture_finte(senza_vivo=True))
            self.assertFalse(verde, "%s deve restare rossa senza il sito vero: %s" % (casella, motivi))

    def test_il_guasto_iniettato_fa_gridare_tutte_e_tre(self):
        storte = ea.inietta_il_guasto(ea.letture_finte())
        for casella, giudica in ea.GIUDIZI.items():
            verde, _p, motivi, _d = giudica(storte)
            self.assertFalse(verde, casella)

    # ── D18 punto 1: l'enumerazione viene dal codice, non da una lista ─────────────
    def test_le_rotte_vengono_dal_codice(self):
        esatte, prefissi = ea.rotte_dal_codice()
        percorsi = set(p for _m, p, _g in esatte)
        self.assertGreater(len(esatte), 100)
        self.assertIn("/api/split/crea", percorsi)
        self.assertIn("/api/split/paga", percorsi)
        self.assertIn("/api/bunker/marca.tsr", percorsi, "le rotte servite fuori da _instrada vanno enumerate")
        self.assertTrue(any(p.startswith("/api/catalogo/") for p in prefissi), prefissi)

    def test_le_liste_dichiarate_nominano_solo_rotte_che_esistono(self):
        """Una dichiarazione su una rotta che non c'e' piu' e' una bugia che invecchia."""
        percorsi = set(p for _m, p, _g in ea.rotte_dal_codice()[0])
        for path in list(ea.PUBBLICHE_PER_PROGETTO) + list(ea.RISPONDONO_200_A_VUOTO):
            self.assertIn(path, percorsi, "dichiarata ma il router non la ha: %s" % path)
        for path in ea.RISPONDONO_200_A_VUOTO:
            self.assertIn(path, ea.PUBBLICHE_PER_PROGETTO,
                          "un 200 a vuoto si dichiara solo su una rotta pubblica per progetto: %s" % path)

    def test_le_tre_caselle_esistono_nel_piano_una_sola_ciascuna(self):
        for casella in ea.MARCHE:
            testo = ea.condizione(casella)
            self.assertIn(ea.MARCHE[casella], testo)

    def test_la_lista_a_mano_di_verifica_produzione_sta_dentro_le_rotte_del_codice(self):
        p3 = ea.lista_p3_di_verifica_produzione()
        percorsi = set(p for _m, p, _g in ea.rotte_dal_codice()[0])
        self.assertGreater(len(p3), 10)
        fuori = [p for p in p3 if p not in percorsi]
        self.assertEqual(fuori, [], "verifica_produzione.p3 nomina rotte che il router non ha")

    # ── il router VERO, senza credenziali (pochi secondi, nessuna rete) ─────────────
    def test_sul_router_vero_nessuna_rotta_riservata_si_apre_senza_credenziali(self):
        letture = ea.letture_locali()
        verde, passi, motivi, den = ea.giudica_scrive(letture)
        self.assertTrue(verde, motivi)
        self.assertGreaterEqual(den, 50)
        ris = [r for r in letture["rotte"] if ea.riservata(r["path"]) and r["gestore"] != "do_GET"]
        aperte = [r for r in ris if r["senza"] not in ea.CHIUSA]
        self.assertEqual(aperte, [], "rotte riservate aperte senza credenziali: %s"
                         % [(r["metodo"], r["path"], r["senza"]) for r in aperte])
        vede_a = [r for r in ris if r.get("altro_host_vede_A")]
        self.assertEqual(vede_a, [], "un altro host vede i dati di A: %s"
                         % [(r["metodo"], r["path"]) for r in vede_a])

    # ── --con-guasto non scrive MAI ──────────────────────────────────────────────────
    def test_con_guasto_e_scrivi_insieme_si_fermano_con_uscita_2(self):
        # In-processo, come le altre guardie sugli attrezzi (test_pipeline_ci): un
        # sottoprocesso non comprerebbe niente e conterebbe come segnalazione nuova
        # per gli strumenti statici (S603/B603).
        uscita = io.StringIO()
        with contextlib.redirect_stdout(uscita):
            codice = ea.main(["--con-guasto", "--scrivi"])
        self.assertEqual(codice, 2, uscita.getvalue()[-400:])
        self.assertIn("FERMO", uscita.getvalue())

    # ── il sistema locale NON lascia l'ambiente sporco ────────────────────────────────
    def test_il_sistema_locale_rimette_MARCA_TEMPORALE_com_era(self):
        """Nella suite intera tutto gira in UN processo: un attrezzo che spegne la marca
        temporale nell'ambiente e non la riaccende spegne anche i test che vengono dopo
        (23 rossi in CI su 2c60533, tutti `503 marca_temporale_non_attiva`)."""
        prima = os.environ.get("MARCA_TEMPORALE")
        os.environ["MARCA_TEMPORALE"] = "1"
        try:
            _r, d, _dati = ea.sistema_locale()
            shutil.rmtree(d, ignore_errors=True)
            self.assertEqual(os.environ.get("MARCA_TEMPORALE"), "1",
                             "sistema_locale() ha lasciato MARCA_TEMPORALE cambiata")
        finally:
            if prima is None:
                os.environ.pop("MARCA_TEMPORALE", None)
            else:
                os.environ["MARCA_TEMPORALE"] = prima


if __name__ == "__main__":
    unittest.main()
