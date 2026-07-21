"""GUARDIA — i testi legali multilingua (fase185): termini e privacy.

PERCHE' (fondatore, 2026-07-21): «privacy e termini e altre cose del genere tutte le
lingue per coerenza» — e prima ancora: «sul sito clicco termini e lo leggo solo italiano
e anche privacy».

Aveva ragione: otto pagine pubbliche erano solo in italiano, fra cui l'informativa GDPR e
i termini contrattuali. Il capitolato non le vedeva perche' SALTAVA le pagine senza
dizionario — il caso peggiore trattato come "non applicabile".

Qui si presidia il modulo che porta quei testi in tutte le lingue. Due principi:

  1. **Assenza non e' conformita'**: una lingua dichiarata ma non fornita e' una
     violazione, non un'esenzione. Una bandiera che apre una pagina vuota e' peggio di
     una bandiera che non c'e'.
  2. **Una sola lingua fa fede**: le traduzioni servono a far capire; il testo che
     vincola resta l'italiano, e ogni versione deve dirlo. Su un'informativa GDPR una
     traduzione approssimativa senza questa clausola sarebbe un rischio, non un servizio.

Le pagine `privacy.html` e `termini.html` sono nominate qui apposta: prima di oggi
nessun test le citava, e una pagina che nessuno guarda puo' mentire per mesi.
"""

import io
import os
import re
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))


def _leggi(p):
    with io.open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


class TestModuloTestiLegali(unittest.TestCase):

    def setUp(self):
        import fase185_testi_legali as tl
        self.tl = tl

    def test_dichiara_le_lingue_del_prodotto(self):
        self.assertGreaterEqual(len(self.tl.LINGUE), 8,
                                "il prodotto dichiara 8 lingue: qui ne mancano")
        self.assertEqual(self.tl.LINGUA_CHE_FA_FEDE, "it")

    def test_ogni_lingua_FORNITA_produce_un_testo_completo(self):
        """Non si controlla che la lingua sia dichiarata: si controlla che il testo
        esista davvero e sia lungo abbastanza da non essere un abbozzo."""
        for documento in ("termini", "privacy"):
            fornite = self.tl.lingue_disponibili(documento)
            self.assertIn("it", fornite, "%s senza italiano" % documento)
            for lang in fornite:
                d = self.tl.documento(documento, lang)
                self.assertNotIn("errore", d, "%s[%s]: %s" % (documento, lang, d))
                # La soglia dipende dalla SCRITTURA: 1500 caratteri giapponesi o
                # cinesi contengono quanto ~3500 latini. Misurare tutte le lingue con
                # lo stesso metro segnalerebbe come "monche" traduzioni complete —
                # ed e' quello che e' successo il 2026-07-21 (giapponese 1500,
                # cinese 1200 caratteri: verificati COMPLETI, finiscono con la
                # clausola sulla lingua).
                minimo = 900 if lang in ("ja", "zh", "ko") else 2500
                self.assertGreater(
                    len(d["testo"]), minimo,
                    "%s[%s] e' solo %d caratteri (minimo %d per questa scrittura): "
                    "traduzione monca" % (documento, lang, len(d["testo"]), minimo))
                self.assertTrue(d["tradotto"])

    def test_ogni_versione_dichiara_QUALE_LINGUA_FA_FEDE(self):
        """La clausola che rende sicure le traduzioni di un testo legale."""
        for documento in ("termini", "privacy"):
            for lang in self.tl.lingue_disponibili(documento):
                testo = self.tl.documento(documento, lang)["testo"]
                self.assertRegex(
                    testo, # "ITALIEN" copre il tedesco ITALIENISCHE e il francese ITALIENNE: cercare
                    # solo "ITALIAN" li mancava entrambi (difetto del test, 2026-07-21)
                    r"(?i)(ITALIAN|ITALIEN|ITALIANA|ITALIANO|イタリア|意大利)",
                    "%s[%s] non dichiara che fa fede l'italiano: una traduzione "
                    "senza questa clausola crea ambiguita' legale" % (documento, lang))

    def test_le_percentuali_vengono_dal_motore(self):
        """Era la causa della bugia «10%» rimasta per mesi in contraddizione col 13%
        realmente addebitato: le cifre non si scrivono a mano nei testi."""
        from fase98_policy_commissione import (BPS_DIRETTO, LANCIO_BPS_FASE1,
                                               LANCIO_BPS_REGIME, LANCIO_GIORNI_GRATIS)
        testo = self.tl.testo_termini("it")
        for bps in (LANCIO_BPS_FASE1, LANCIO_BPS_REGIME, BPS_DIRETTO):
            self.assertIn("%d%%" % (bps // 100), testo,
                          "manca la percentuale %d%% del motore" % (bps // 100))
        self.assertIn("%d giorni" % LANCIO_GIORNI_GRATIS, testo)
        self.assertRegex(testo, r"3%", "i termini non dichiarano la tariffa tecnica")

    def test_la_penale_e_quella_del_motore(self):
        from fase83_server import PENALE_HOST_BPS
        self.assertIn("%d%%" % (PENALE_HOST_BPS // 100), self.tl.testo_termini("it"))

    def test_ogni_lingua_ha_una_IMPRONTA_diversa(self):
        """Se due lingue avessero la stessa impronta, una sarebbe copia dell'altra:
        cioe' NON tradotta."""
        for documento in ("termini", "privacy"):
            impronte = {}
            for lang in self.tl.lingue_disponibili(documento):
                d = self.tl.documento(documento, lang)
                self.assertEqual(len(d["doc_sha256"]), 64)
                self.assertNotIn(d["doc_sha256"], impronte,
                                 "%s[%s] e' identico a [%s]: non e' tradotto"
                                 % (documento, lang, impronte.get(d["doc_sha256"])))
                impronte[d["doc_sha256"]] = lang

    def test_una_lingua_non_fornita_ripiega_sullitaliano_DICENDOLO(self):
        """Ripiegare va bene; ripiegare in silenzio no: chi legge deve sapere che sta
        vedendo l'italiano perche' la sua lingua non c'e' (ancora)."""
        d = self.tl.documento("privacy", "xx")
        self.assertFalse(d["tradotto"], "dichiara tradotta una lingua che non esiste")
        self.assertEqual(d["lang"], "it")
        self.assertIn("it", d["lingue"])

    def test_i_dati_del_titolare_sono_UNA_VOLTA_SOLA(self):
        """Se l'indirizzo cambia, deve cambiare in tutte le lingue insieme: altrimenti
        una traduzione resta con la sede vecchia e nessuno se ne accorge."""
        for documento in ("termini", "privacy"):
            for lang in self.tl.lingue_disponibili(documento):
                testo = self.tl.documento(documento, lang)["testo"]
                self.assertIn(self.tl.GESTORE["piva"], testo,
                              "%s[%s] non riporta la partita IVA" % (documento, lang))
                self.assertIn(self.tl.GESTORE["email"], testo)

    def test_nessun_segnaposto_lasciato_a_meta(self):
        for documento in ("termini", "privacy"):
            for lang in self.tl.lingue_disponibili(documento):
                testo = self.tl.documento(documento, lang)["testo"]
                for spia in ("TODO", "XXX", "lorem ipsum", "TRANSLATE", "{", "}"):
                    self.assertNotIn(spia, testo,
                                     "%s[%s] contiene '%s': testo non finito"
                                     % (documento, lang, spia))

    def test_la_privacy_copre_i_punti_obbligatori_del_GDPR(self):
        """Artt. 13-14: un'informativa che non dice questi punti non e' un'informativa."""
        obbligatori = {
            "it": ["Titolare", "base giuridica", "diritti", "reclamo", "conserv"],
            "en": ["controller", "legal basis", "rights", "complaint", "keep"],
        }
        for lang, parole in obbligatori.items():
            if lang not in self.tl.lingue_disponibili("privacy"):
                continue
            testo = self.tl.testo_privacy(lang).lower()
            for parola in parole:
                self.assertIn(parola.lower(), testo,
                              "privacy[%s] non tratta '%s'" % (lang, parola))

    def test_il_modulo_non_solleva_mai(self):
        for documento in ("termini", "privacy", "", None, "inventato", 123):
            for lang in ("it", "", None, "ZZ", "it-IT", 42, "a" * 200):
                try:
                    d = self.tl.documento(documento, lang)
                except Exception as e:
                    self.fail("documento(%r, %r) ha sollevato %s"
                              % (documento, lang, type(e).__name__))
                self.assertIsInstance(d, dict)


class TestPagineLegaliPubbliche(unittest.TestCase):
    """`privacy.html` e `termini.html`: prima di oggi NESSUN test le nominava."""

    def _pagina(self, nome):
        p = os.path.join(QUI, "deploy", nome)
        if not os.path.exists(p):
            self.skipTest("pagina assente: %s" % nome)
        return _leggi(p)

    def test_privacy_html_esiste_ed_e_piena(self):
        testo = self._pagina("privacy.html")
        self.assertGreater(len(testo), 1500)
        self.assertIn("<title>", testo)

    def test_termini_html_esiste_ed_e_pieno(self):
        testo = self._pagina("termini.html")
        self.assertGreater(len(testo), 1500)
        self.assertIn("<title>", testo)

    def test_nessun_segreto_nelle_pagine_legali(self):
        for nome in ("privacy.html", "termini.html"):
            testo = self._pagina(nome)
            for spia in ("sk_live", "sk_test", "whsec_", "ADMIN_KEY"):
                self.assertNotIn(spia, testo, "%s contiene '%s'" % (nome, spia))

    def test_i_termini_dichiarano_la_tariffa_tecnica(self):
        """Stessa regola di tutte le pagine per host: chi nomina percentuali deve
        nominare anche il 3% sempre dovuto."""
        testo = self._pagina("termini.html")
        if not re.search(r"commission", testo, re.I):
            self.skipTest("la pagina non parla di commissioni")
        self.assertRegex(testo, r"3\s?%",
                         "i termini parlano di commissioni senza il 3% tecnico")


if __name__ == "__main__":
    unittest.main(verbosity=2)
