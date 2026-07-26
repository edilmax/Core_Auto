"""GUARDIA — motore campagna persuasiva a rotazione (fase200): genera SEMPRE un contenuto (mai vuoto),
ruota le 7 leve di Cialdini senza ripetere, usa l'AI quando c'e' e ripiega quando tace, e produce
un'immagine flux (nitida, keyless). Osservabili ESATTI (esito + effetto).
"""
import os
import shutil
import tempfile
import unittest

import fase200_campagna_persuasiva as C


class TestAngoli(unittest.TestCase):
    def test_sette_leve_chiavi_uniche(self):
        self.assertEqual(len(C.ANGOLI), 7)
        chiavi = [a["chiave"] for a in C.ANGOLI]
        self.assertEqual(len(set(chiavi)), 7, "chiavi leve duplicate")
        for a in C.ANGOLI:
            for campo in ("chiave", "nome", "istruzione", "soggetto", "ripiego"):
                self.assertTrue(a.get(campo), "leva %s: campo %s vuoto" % (a.get("chiave"), campo))


class TestGenerazione(unittest.TestCase):
    def test_ripiego_mai_vuoto_senza_ai(self):
        g = C.crea_generatore_campagna(None, citta="Roma")   # nessuna AI
        r = g.genera()
        self.assertFalse(r["da_ai"])
        self.assertTrue(r["didascalia"].strip(), "didascalia vuota col ripiego")
        self.assertIn("Roma", r["didascalia"] + r["immagine"])

    def test_usa_l_ai_quando_c_e(self):
        g = C.crea_generatore_campagna(lambda prompt: "  Vieni a pubblicare a Roma, host.  ", citta="Roma")
        r = g.genera()
        self.assertTrue(r["da_ai"])
        self.assertEqual(r["didascalia"], "Vieni a pubblicare a Roma, host.")   # strip applicato

    def test_niente_emoji_ne_premesse_ne_virgolette(self):
        # il fondatore NON vuole emoji; il modello a volte sbroda -> il pulitore GARANTISCE il risultato
        sporco = 'Ecco una didascalia: "Pubblica gratis a Roma 🏠👑✨, zero commissioni! 🎉" #bookinvip #casa'
        g = C.crea_generatore_campagna(lambda p: sporco)
        d = g.genera()["didascalia"]
        self.assertEqual(C._EMOJI.findall(d), [], "emoji non rimosse: %r" % d)
        self.assertFalse(d.lower().startswith("ecco"), "premessa non rimossa: %r" % d)
        self.assertFalse(d.startswith('"') or d.endswith('"'), "virgolette non rimosse: %r" % d)
        self.assertNotIn("#bookinvip", d, "hashtag finale non rimosso: %r" % d)
        self.assertIn("Pubblica gratis a Roma", d)   # il contenuto vero resta

    def test_nessuna_emoji_in_nessun_ripiego(self):
        for a in C.ANGOLI:
            self.assertEqual(C._EMOJI.findall(a["ripiego"]), [],
                             "la leva %s ha un'emoji nel ripiego" % a["chiave"])

    def test_prompt_vieta_emoji_e_premesse(self):
        # il prompt deve istruire l'AI a non usare emoji ne' premesse (difesa a monte)
        p = C.GeneratoreCampagna._prompt_ai(C.ANGOLI[0], "Roma")
        self.assertIn("NIENTE emoji", p)
        self.assertIn("SOLTANTO il testo", p)

    def test_ai_che_esplode_ripiega_senza_sollevare(self):
        def boom(_p):
            raise RuntimeError("Groq giu'")
        g = C.crea_generatore_campagna(boom)
        r = g.genera()                       # non deve sollevare
        self.assertFalse(r["da_ai"])
        self.assertTrue(r["didascalia"].strip())

    def test_ai_stringa_vuota_ripiega(self):
        g = C.crea_generatore_campagna(lambda p: "   ")
        r = g.genera()
        self.assertFalse(r["da_ai"])
        self.assertTrue(r["didascalia"].strip())

    def test_immagine_e_flux_pollinations(self):
        g = C.crea_generatore_campagna(None)
        img = g.genera()["immagine"]
        self.assertIn("image.pollinations.ai/prompt/", img)
        self.assertIn("model=flux", img)          # alta qualita', non il default sfocato
        self.assertIn("nologo=true", img)

    def test_niente_segnaposto_citta_residuo(self):
        g = C.crea_generatore_campagna(None, citta="Milano")
        r = g.genera()
        self.assertNotIn("{citta}", r["didascalia"])
        self.assertNotIn("{citta}", r["immagine"])
        self.assertIn("Milano", r["didascalia"] + r["immagine"])

    def test_angolo_specifico_non_avanza_la_rotazione(self):
        g = C.crea_generatore_campagna(None)
        r = g.genera(angolo_chiave="unita")
        self.assertEqual(r["chiave"], "unita")
        # la rotazione NON è avanzata: la prossima generica riparte da capo (indice 0)
        self.assertEqual(g.genera()["chiave"], C.ANGOLI[0]["chiave"])


class TestRotazioneDurevole(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = self.d + "/stato.json"

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_gira_tutte_le_leve_senza_ripetere_poi_ricomincia(self):
        g = C.crea_generatore_campagna(None, stato_path=self.path)
        viste = [g.genera()["chiave"] for _ in range(len(C.ANGOLI))]
        self.assertEqual(viste, [a["chiave"] for a in C.ANGOLI], "non gira tutte le leve in ordine")
        self.assertEqual(len(set(viste)), 7, "una leva ripetuta nel giro")
        # dopo un giro completo, ricomincia dalla prima
        self.assertEqual(g.genera()["chiave"], C.ANGOLI[0]["chiave"])

    def test_stato_sopravvive_a_una_nuova_istanza(self):
        g1 = C.crea_generatore_campagna(None, stato_path=self.path)
        self.assertEqual(g1.genera()["chiave"], C.ANGOLI[0]["chiave"])   # avanza a 1
        g2 = C.crea_generatore_campagna(None, stato_path=self.path)      # nuova istanza, stesso file
        self.assertEqual(g2.genera()["chiave"], C.ANGOLI[1]["chiave"], "la rotazione non è durevole")

    def test_giro_completo_uno_per_leva(self):
        g = C.crea_generatore_campagna(lambda p: "esempio", stato_path=self.path)
        giro = g.genera_giro_completo()
        self.assertEqual([r["chiave"] for r in giro], [a["chiave"] for a in C.ANGOLI])
        self.assertTrue(all(r["didascalia"] and r["immagine"] for r in giro))
        # genera_giro_completo NON deve toccare lo stato di rotazione
        self.assertEqual(g.genera()["chiave"], C.ANGOLI[0]["chiave"])


class TestGlobale(unittest.TestCase):
    """Siamo GLOBALI: le città top del mondo, nella lingua del posto, ripiego inglese fuori Italia."""

    def test_citta_top_e_lingue_coerenti(self):
        self.assertGreaterEqual(len(C.CITTA_TOP), 10, "poche città top")
        self.assertEqual(len(set(C.CITTA_TOP)), len(C.CITTA_TOP), "città top duplicate")
        # ogni città top ha una lingua mappata e la lingua ha un nome
        for citta in C.CITTA_TOP:
            self.assertIn(citta, C.LINGUA_CITTA, "città top senza lingua: %s" % citta)
            self.assertIn(C.LINGUA_CITTA[citta], C.NOME_LINGUA, "lingua senza nome: %s" % citta)

    def test_ripiego_en_copre_tutte_le_leve_senza_emoji(self):
        for a in C.ANGOLI:
            self.assertIn(a["chiave"], C.RIPIEGO_EN, "leva %s senza ripiego EN" % a["chiave"])
            r = C.RIPIEGO_EN[a["chiave"]]
            self.assertEqual(C._EMOJI.findall(r), [], "ripiego EN %s ha un'emoji" % a["chiave"])

    def test_lingua_en_usa_ripiego_inglese_niente_italiano(self):
        # con AI spenta e lingua non-italiana, il ripiego è quello INGLESE (mai italiano fuori Italia)
        g = C.crea_generatore_campagna(None, citta="London")
        r = g.genera(citta="London", lingua="en")
        self.assertEqual(r["lingua"], "en")
        d = r["didascalia"]
        self.assertIn("London", d)
        self.assertIn("bookinvip.com", d)
        # niente parole-spia italiane del ripiego IT (che direbbe "Pubblica"/"tuo alloggio")
        for spia in ("alloggio", "commissione", "Pubblica il tuo"):
            self.assertNotIn(spia, d, "residuo italiano nel ripiego EN: %r" % d)

    def test_lingua_it_resta_default_e_ripiego_italiano(self):
        g = C.crea_generatore_campagna(None, citta="Roma")
        r = g.genera()                       # nessuna lingua -> default italiano
        self.assertEqual(r["lingua"], "it")

    def test_prompt_istruisce_la_lingua(self):
        # l'ordine di lingua è NELLA LINGUA STESSA e compare in CIMA e in FONDO (posizioni forti):
        # senza questo il modello, annegato in un prompt italiano, sbrodava italiano ovunque (bug reale
        # visto su Parigi/Londra scritte in italiano nel primo giro di preview).
        p_en = C.GeneratoreCampagna._prompt_ai(C.ANGOLI[0], "London", "en")
        self.assertIn("Write the caption exclusively in English", p_en)
        self.assertTrue(p_en.strip().startswith(C._ORDINE_LINGUA["en"]), "ordine lingua non in cima")
        self.assertIn("interamente in inglese", p_en)                    # promemoria in fondo
        p_fr = C.GeneratoreCampagna._prompt_ai(C.ANGOLI[0], "Paris", "fr")
        self.assertIn("exclusivement en français", p_fr)
        self.assertNotIn("Write the caption", p_fr)                      # niente ordine di un'altra lingua
        p_ja = C.GeneratoreCampagna._prompt_ai(C.ANGOLI[0], "Tokyo", "ja")
        self.assertIn("日本語", p_ja)

    def test_genera_globale_gira_le_citta_e_da_la_lingua_locale(self):
        d = tempfile.mkdtemp()
        try:
            g = C.crea_generatore_campagna(None, stato_path=d + "/s.json")
            viste = [g.genera_globale() for _ in range(len(C.CITTA_TOP))]
            citta_viste = [r["citta"] for r in viste]
            # gira TUTTE le città top in ordine, una per giro
            self.assertEqual(citta_viste, list(C.CITTA_TOP), "genera_globale non gira le città top")
            # ogni contenuto è nella lingua locale della sua città
            for r in viste:
                self.assertEqual(r["lingua"], C.LINGUA_CITTA[r["citta"]],
                                 "lingua sbagliata per %s" % r["citta"])
                self.assertTrue(r["didascalia"].strip() and r["immagine"], "contenuto vuoto")
                self.assertIn(r["citta"], r["didascalia"] + r["immagine"])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_genera_globale_copre_tutte_le_combinazioni_prima_di_ripetere(self):
        # 13 città e 7 leve sono coprimi -> 91 combinazioni uniche prima di ripetere una coppia
        d = tempfile.mkdtemp()
        try:
            g = C.crea_generatore_campagna(None, stato_path=d + "/s.json")
            n = len(C.CITTA_TOP) * len(C.ANGOLI)
            coppie = set()
            for _ in range(n):
                r = g.genera_globale()
                coppie.add((r["citta"], r["chiave"]))
            self.assertEqual(len(coppie), n, "le combinazioni città×leva si ripetono prima di %d" % n)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestGuardiaLingua(unittest.TestCase):
    """Regola d'oro: MAI italiano fuori Italia. Il guardiano scarta le didascalie italiane contaminate
    (portoghese e italiano sono quasi gemelli: il modello a volte parte con «Pubblica…»)."""

    def test_riconosce_italiano_e_discrimina_dalle_sorelle(self):
        # italiano inequivocabile → contaminato quando la lingua target non è italiano
        self.assertTrue(C._contaminato_italiano("Pubblica il tuo alloggio a Lisbona", "pt"))
        self.assertTrue(C._contaminato_italiano("Bastano 10 giorni, scrivimi", "fr"))
        # lingue-sorelle NON devono scattare (publica/alojamento/dias, senza doppia-b)
        self.assertFalse(C._contaminato_italiano("Publica o teu alojamento em Lisboa por 90 dias", "pt"))
        self.assertFalse(C._contaminato_italiano("List your London property, 0% commission", "en"))
        self.assertFalse(C._contaminato_italiano("Publica tu alojamiento gratis", "es"))
        # se la lingua target È italiano, non è contaminazione
        self.assertFalse(C._contaminato_italiano("Pubblica il tuo alloggio a Roma", "it"))

    def test_scarta_didascalia_italiana_e_ripiega_pulito(self):
        # l'AI sbroda italiano per una città portoghese → deve essere SCARTATA e usato il ripiego (EN pulito)
        g = C.crea_generatore_campagna(lambda p: "Pubblica il tuo alloggio a Lisbona gratis per 90 giorni", citta="Lisbon")
        r = g.genera(citta="Lisbon", lingua="pt")
        self.assertFalse(r["da_ai"], "ha accettato una didascalia italiana fuori Italia")
        self.assertFalse(C._contaminato_italiano(r["didascalia"], "pt"),
                         "la didascalia finale contiene ancora italiano: %r" % r["didascalia"])
        self.assertTrue(r["didascalia"].strip())          # mai vuota

    def test_accetta_didascalia_nella_lingua_giusta(self):
        # testo pulito nella lingua target → accettato (il guardiano non è un falso-positivo)
        g = C.crea_generatore_campagna(lambda p: "Publica o teu alojamento em Lisboa, 0% de comissao", citta="Lisbon")
        r = g.genera(citta="Lisbon", lingua="pt")
        self.assertTrue(r["da_ai"], "ha scartato una didascalia portoghese valida")
        self.assertIn("alojamento", r["didascalia"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
