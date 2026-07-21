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

import fase185_testi_legali as L

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
    """`privacy.html` e `termini.html`: da oggi sono GUSCI, non testi.

    Prima erano HTML statico in italiano — il fondatore se n'e' accorto da solo
    («clicco termini e lo leggo solo italiano»). Ora prendono il documento da
    /api/legale/documento nella lingua dell'utente, quindi cio' che va sorvegliato
    cambia natura: non piu' "la pagina contiene la frase giusta", ma **la pagina e'
    collegata al motore ed espone tutte le lingue**.

    NOTA SU UN FINTO VERDE GIA' PAGATO. La verifica del 3% viveva qui e si SALTAVA DA
    SOLA quando la pagina non nominava le commissioni: appena il testo e' uscito
    dall'HTML, il controllo e' evaporato senza che nulla diventasse rosso. Ora quella
    verifica sta dove sta il testo — sul documento vero, in TUTTE le lingue.
    """

    def _pagina(self, nome):
        p = os.path.join(QUI, "deploy", nome)
        self.assertTrue(os.path.exists(p), "pagina legale sparita: %s" % nome)
        return _leggi(p)

    def test_le_pagine_legali_chiamano_il_motore(self):
        """La chiamata dev'essere VIVA, non raccontata.

        La prima stesura cercava la stringa "/api/legale/documento" in tutta la pagina.
        Provata col guasto vero — chiamata spenta, commento lasciato intatto — restava
        VERDE: si accontentava del commento che DESCRIVE la chiamata. Sarebbe stata
        cieca proprio al difetto per cui e' nata (il pezzo scollegato). Ora i commenti
        si tolgono prima di guardare, e si pretende la chiamata dentro un fetch().
        """
        for nome, doc in (("termini.html", "termini"), ("privacy.html", "privacy")):
            vivo = re.sub(r"/\*.*?\*/", " ", self._pagina(nome), flags=re.S)
            vivo = re.sub(r"(?m)^\s*//.*$", " ", vivo)
            self.assertRegex(
                vivo, r"fetch\(\s*['\"`]/api/legale/documento",
                "%s non CHIAMA il motore (un commento non basta): tornerebbe statica"
                % nome)
            self.assertRegex(vivo, r"const DOC\s*=\s*'%s'" % doc,
                             "%s chiede il documento sbagliato" % nome)

    def test_le_pagine_legali_offrono_tutte_le_lingue(self):
        for nome in ("termini.html", "privacy.html"):
            testo = self._pagina(nome)
            for lang in L.LINGUE:
                self.assertRegex(testo, r"\b%s\s*:\s*\{\s*torna:" % lang,
                                 "%s non ha la cornice in '%s'" % (nome, lang))

    def test_le_pagine_legali_non_contengono_piu_testo_legale_fisso(self):
        """Se il testo tornasse dentro l'HTML, tornerebbe anche in una lingua sola."""
        for nome in ("termini.html", "privacy.html"):
            testo = self._pagina(nome)
            for frase in ("BookinVIP e' una piattaforma", "Commissione di piattaforma",
                          "BOZZA NON VINCOLANTE", "Ultimo aggiornamento:"):
                self.assertNotIn(frase, testo,
                                 "%s e' tornata statica: contiene '%s'" % (nome, frase))

    def test_nessun_segreto_nelle_pagine_legali(self):
        for nome in ("privacy.html", "termini.html"):
            testo = self._pagina(nome)
            for spia in ("sk_live", "sk_test", "whsec_", "ADMIN_KEY"):
                self.assertNotIn(spia, testo, "%s contiene '%s'" % (nome, spia))

    def test_il_documento_esce_dal_marcatore_senza_marcatura_viva(self):
        """La pagina inserisce il testo con innerHTML: deve passare da esc()."""
        for nome in ("termini.html", "privacy.html"):
            testo = self._pagina(nome)
            self.assertIn("function esc(", testo)
            self.assertIn("comeHtml(", testo)
            self.assertNotIn("innerHTML = d.testo", testo,
                             "%s inserisce il testo senza ripulirlo" % nome)


class TestTariffaTecnicaInOgniLingua(unittest.TestCase):
    """La regola vale sul TESTO, non sulla pagina: chi nomina la commissione deve
    nominare anche la tariffa tecnica sempre dovuta. In tutte e otto le lingue, o in
    una si prometterebbe qualcosa di diverso."""

    def test_ogni_lingua_dichiara_la_tariffa_tecnica(self):
        tecnica = L._percentuali()["tecnica"]
        mute = []
        for lang in L.LINGUE:
            testo = L.testo_termini(lang)
            if not re.search(r"%d\s?%%" % tecnica, testo):
                mute.append(lang)
        self.assertEqual(mute, [],
                         "queste lingue non dichiarano la tariffa tecnica del %d%%: %s"
                         % (tecnica, mute))

    def test_ogni_lingua_porta_le_stesse_percentuali(self):
        """Nessuna lingua puo' promettere una percentuale diversa da un'altra."""
        insiemi = {}
        for lang in L.LINGUE:
            insiemi[lang] = sorted(set(re.findall(r"(\d+)\s?%", L.testo_termini(lang))))
        riferimento = insiemi[L.LINGUA_CHE_FA_FEDE]
        diverse = [lg for lg, v in insiemi.items() if v != riferimento]
        self.assertEqual(diverse, [],
                         "percentuali diverse fra le lingue (%s fa fede con %s): %s"
                         % (L.LINGUA_CHE_FA_FEDE, riferimento,
                            {lg: insiemi[lg] for lg in diverse}))

    def test_nessun_segnaposto_dimenticato_in_nessuna_lingua(self):
        for nome in ("termini", "privacy"):
            for lang in L.LINGUE:
                testo = L.documento(nome, lang)["testo"]
                resti = re.findall(r"\{[A-Z0-9_]+\}", testo)
                self.assertEqual(resti, [],
                                 "%s/%s ha segnaposto non riempiti: %s"
                                 % (nome, lang, resti))


if __name__ == "__main__":
    unittest.main(verbosity=2)
