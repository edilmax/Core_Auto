"""OGNI MESSAGGIO IN OGNI LINGUA — la guardia che chiude le 77 coppie mai generate.

PERCHE' ESISTE. Il 2026-08-19 `collaudi/denominatore.py` ha misurato una cosa che nessuno
sapeva: la macchina sa spedire **10 messaggi** e dichiara **8 lingue**, cioe' 80 combinazioni,
e i collaudi ne generavano **3**. Le altre 77 non erano rotte: erano **mai state guardate**,
che e' una cosa diversa e va detta cosi'.

⛔ E' IL MODO DI ROMPERSI n. 11 (lingua congelata), l'unico che non trovo' nessun test: lo
   trovo' il fondatore aprendo il sito. Una pagina -- o un'email -- puo' avere otto lingue
   dichiarate e restare in italiano, e tutta la suite resta verde perche' non guarda li'.

COSA PRETENDE, per tutte e 80 le combinazioni:
  1. il messaggio si genera senza esplodere;
  2. il testo e' DIVERSO da quello inglese (se fosse identico, quella lingua non e' tradotta:
     e' il ripiego che passa per traduzione);
  3. non resta dentro un segnaposto vuoto.

⛔ E DICHIARA IL PROPRIO DENOMINATORE. L'elenco qui sotto non e' scritto a mano e basta: un
   controllo lo confronta con le funzioni `corpo_*_html` che esistono davvero nel modulo. Se
   qualcuno aggiunge l'undicesimo messaggio e non lo prova in otto lingue, questa guardia
   diventa ROSSA lo stesso giorno -- altrimenti fra sei mesi saremmo di nuovo a 77.
"""
import re
import unittest

import fase86_email as E
from fase61_localizzazione import LINGUE_SUPPORTATE

# ogni voce: come si chiama il messaggio -> come si costruisce, data una lingua.
# Gli argomenti sono finti ma PLAUSIBILI: un importo, una data, un titolo, un link.
MESSAGGI = {
    "corpo_voucher_html": lambda l: E.corpo_voucher_html(
        "Villa Roma", "ABC123", "2099-03-05", "2099-03-08",
        "https://bookinvip.com/v/ABC123", lingua=l),
    "corpo_preventivo_html": lambda l: E.corpo_preventivo_html(
        "Villa Roma", "2099-03-05", "2099-03-08",
        [("3 notti", "600,00 EUR")], "https://bookinvip.com/p/1", lingua=l),
    "corpo_pagamento_confermato_html": lambda l: E.corpo_pagamento_confermato_html(
        "Villa Roma", "https://bookinvip.com/v/ABC123", 60000, "EUR", lingua=l),
    "corpo_cancellazione_html": lambda l: E.corpo_cancellazione_html(
        "Villa Roma", 30000, "EUR", lingua=l),
    "corpo_invito_recensione_html": lambda l: E.corpo_invito_recensione_html(
        "Villa Roma", "https://bookinvip.com/v/ABC123", lingua=l),
    "corpo_esito_controversia_html": lambda l: E.corpo_esito_controversia_html(
        30000, "EUR", lingua=l),
    "corpo_payout_host_html": lambda l: E.corpo_payout_host_html(
        50000, "EUR", "REF-1", lingua=l),
    "corpo_reset_password_html": lambda l: E.corpo_reset_password_html(
        "https://bookinvip.com/reset/xyz", lingua=l),
    "corpo_benvenuto_host_html": lambda l: E.corpo_benvenuto_host_html(
        "https://bookinvip.com/host", lingua=l),
    "corpo_promemoria_checkin_html": lambda l: E.corpo_promemoria_checkin_html(
        "Villa Roma", "https://bookinvip.com/v/ABC123", lingua=l),
}


class TestOgniMessaggioInOgniLingua(unittest.TestCase):

    def test_IL_DENOMINATORE_DI_QUESTA_GUARDIA_E_QUELLO_VERO(self):
        """⛔ La guardia dichiara quante cose sta guardando, e lo confronta con quante ne
        esistono. Senza questo, aggiungere l'undicesimo messaggio lascerebbe la guardia verde
        e la copertura muta: e' la regola «ogni guardia dichiara il denominatore» applicata a
        se stessa. Il conto delle funzioni si legge dal modulo, non da un numero scritto qui."""
        import io
        import os
        percorso = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fase86_email.py")
        with io.open(percorso, encoding="utf-8") as f:
            sorgente = f.read()
        esistenti = set(re.findall(r"^def (corpo_\w+_html)\(", sorgente, re.M))
        self.assertEqual(
            esistenti, set(MESSAGGI),
            "i messaggi che la macchina sa spedire e quelli che questa guardia prova non "
            "coincidono. Mancano qui: %s. Non esistono piu': %s. Un messaggio nuovo va "
            "provato in TUTTE le lingue, se no torniamo alle 77 coppie mai guardate."
            % (sorted(esistenti - set(MESSAGGI)), sorted(set(MESSAGGI) - esistenti)))

    def test_ogni_messaggio_si_genera_in_ogni_lingua(self):
        """80 combinazioni, una per una. Un messaggio che esplode in giapponese non lo
        scoprirebbe nessuno: quella riga la esegue un ospite, non noi."""
        rotti = []
        for nome, fabbrica in sorted(MESSAGGI.items()):
            for lingua in LINGUE_SUPPORTATE:
                try:
                    testo = fabbrica(lingua)
                except Exception as e:
                    rotti.append("%s/%s -> %s: %s" % (nome, lingua, type(e).__name__, e))
                    continue
                if not testo or len(testo) < 80:
                    rotti.append("%s/%s -> testo vuoto o troppo corto (%d caratteri)"
                                 % (nome, lingua, len(testo or "")))
        self.assertEqual([], rotti,
                         "queste combinazioni messaggio/lingua non si generano: %r" % (rotti,))

    def test_nessuna_lingua_e_CONGELATA_sull_inglese(self):
        """⛔ IL CUORE. Se il testo in giapponese e' IDENTICO a quello inglese, quella lingua
        non e' tradotta: e' il ripiego che passa per traduzione, e nessuno se ne accorge
        perche' l'email parte lo stesso ed e' pure leggibile. Misurato il 2026-08-19: zero
        congelate su 70 -- ma senza questa guardia la prima che si congela non lo dice."""
        congelate = []
        for nome, fabbrica in sorted(MESSAGGI.items()):
            inglese = fabbrica("en")
            for lingua in LINGUE_SUPPORTATE:
                if lingua == "en":
                    continue
                if fabbrica(lingua) == inglese:
                    congelate.append("%s/%s" % (nome, lingua))
        self.assertEqual([], congelate,
                         "questi messaggi escono in INGLESE anche quando la lingua e' un'altra "
                         "(modo di rompersi n. 11, lingua congelata): %r" % (congelate,))

    def test_nessun_segnaposto_resta_nel_testo_spedito(self):
        """D8: niente segnaposto nei percorsi che l'utente attraversa. Un `%s` o un `{cosa}`
        rimasto dentro e' un pezzo di codice che finisce sotto gli occhi di un cliente."""
        sospetti = []
        for nome, fabbrica in sorted(MESSAGGI.items()):
            for lingua in LINGUE_SUPPORTATE:
                testo = fabbrica(lingua)
                for segnaposto in ("%s", "%d", "{}", "None", "TODO"):
                    if segnaposto in testo:
                        sospetti.append("%s/%s contiene %r" % (nome, lingua, segnaposto))
        self.assertEqual([], sospetti,
                         "segnaposto rimasti nel testo che legge una persona: %r" % (sospetti,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
