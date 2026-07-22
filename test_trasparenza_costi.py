"""TRASPARENZA COSTI HOST (2026-07-20, direttiva fondatore "Strada A").

Prima di questo lavoro la dashboard e il contratto dicevano "ricevi il prezzo meno la
commissione" e NON nominavano mai il costo carta: a commissione 0% (promo lancio) l'host
credeva di tenere TUTTO, ma il 3% di tariffa tecnica gli veniva comunque dedotto. Il codice
era corretto, erano i TESTI a essere incompleti.

Guardie di questo compartimento (anti-deriva testi<->codice):
  - ANCORAGGIO AL CODICE: le percentuali scritte nei testi (3% tecnico, 0%/8%/10% rampa,
    5% diretto) DEVONO combaciare con le costanti vere del motore (main_casavip default
    PAGAMENTO_BPS, fase98 LANCIO_*/BPS_DIRETTO). Se domani si cambia una tariffa nel codice
    senza aggiornare i testi, questi test diventano ROSSI.
  - DASHBOARD: esiste la card costi (it+en) e nessun testo host promette il netto senza
    nominare la tariffa tecnica.
  - CONTRATTO: art. 6-bis presente in IT e EN, dice 3% + "sempre dovuta" + i tre scaglioni;
    versione aggiornata e impronta coerente.
  - TERMINI PUBBLICI: la tariffa tecnica e' dichiarata anche fuori dal pannello host.
"""
import os
import re
import unittest

import fase185_testi_legali as TL
from fase98_policy_commissione import (BPS_DIRETTO, LANCIO_BPS_FASE1, LANCIO_BPS_REGIME,
                                       LANCIO_GIORNI_GRATIS)
from fase163_accettazioni import (CONTRATTO_HOST, CONTRATTO_HOST_VERSIONE, doc_sha256,
                                  documento_corrente)

BASE = os.path.dirname(os.path.abspath(__file__))


def _leggi(rel):
    with open(os.path.join(BASE, rel), encoding="utf-8") as f:
        return f.read()


def _psp_bps_default():
    """Il costo carta VERO che parte in produzione = default di PAGAMENTO_BPS in main."""
    src = _leggi("main_casavip.py")
    m = re.search(r'PAGAMENTO_BPS["\']\s*,\s*["\'](\d+)["\']', src)
    assert m, "default PAGAMENTO_BPS non trovato in main_casavip.py"
    return int(m.group(1))


class TestAncoraggioAlCodice(unittest.TestCase):
    """Il numero scritto nei testi DEVE essere quello che il motore applica davvero."""

    def test_tariffa_tecnica_dichiarata_uguale_al_codice(self):
        bps = _psp_bps_default()
        self.assertEqual(bps % 100, 0, "tariffa non intera: i testi '3%%' andrebbero rivisti")
        atteso = "%d%%" % (bps // 100)                    # 300 bps -> "3%"
        self.assertIn(atteso, _leggi("deploy/host.html"),
                      "deploy/host.html non dichiara la tariffa tecnica %s del codice"
                      % atteso)
        # i TERMINI non stanno piu' nell'HTML: sono un documento servito dal motore in 8
        # lingue. Si verifica dove il testo vive davvero, e in OGNI lingua.
        for lang in TL.LINGUE:
            self.assertIn(atteso, TL.testo_termini(lang),
                          "i termini in '%s' non dichiarano la tariffa tecnica %s"
                          % (lang, atteso))
        for lang in ("it", "en"):
            self.assertIn(atteso, CONTRATTO_HOST[lang],
                          "il contratto (%s) non dichiara la tariffa %s" % (lang, atteso))

    def test_scaglioni_dichiarati_uguali_al_codice(self):
        """0%/8%/10% + 5% diretto + 90 giorni: come le costanti di fase98."""
        self.assertEqual(LANCIO_GIORNI_GRATIS, 90)
        self.assertEqual(LANCIO_BPS_FASE1 // 100, 8)
        self.assertEqual(LANCIO_BPS_REGIME // 100, 10)
        self.assertEqual(BPS_DIRETTO // 100, 5)
        host = _leggi("deploy/host.html")
        for atteso in ("90 giorni", "8%", "10%", "5%", "3%"):
            self.assertIn(atteso, host, "dashboard host: manca '%s'" % atteso)
        for lang in ("it", "en"):
            t = CONTRATTO_HOST[lang]
            for atteso in ("90", "8%", "10%", "5%", "3%"):
                self.assertIn(atteso, t, "contratto %s: manca '%s'" % (lang, atteso))


class TestDashboardHost(unittest.TestCase):
    def setUp(self):
        self.host = _leggi("deploy/host.html")

    def test_card_costi_presente_e_agganciata(self):
        self.assertIn('id="cardCosti"', self.host, "card costi assente dalla dashboard")
        # deve comparire dopo il login (lista di visibilita') e nell'ordine degli essenziali
        self.assertIn("'cardGuida','cardCosti','cardPrenotazioni'", self.host,
                      "cardCosti non viene mostrata dopo il login")
        self.assertIn("'cardGuida','cardCosti','cardAllog'", self.host,
                      "cardCosti non e' nell'ordine delle card essenziali")

    def test_testi_card_in_italiano_e_inglese(self):
        for chiave in ("co_h", "co_p", "co_r1", "co_r2", "co_r3", "co_r4", "co_n"):
            self.assertEqual(self.host.count(chiave + ':"'), 2,
                             "la chiave %s deve esistere in it E en (fallback EN per le altre)"
                             % chiave)
        self.assertIn("tariffa tecnica fissa del 3%", self.host)
        self.assertIn("fixed 3% technical fee", self.host)
        self.assertIn("sempre attiva", self.host)          # vale in OGNI periodo
        self.assertIn("always active", self.host)

    def test_nessun_testo_promette_il_netto_senza_la_tariffa(self):
        """Il campo prezzo diceva 'ricevi questo meno la commissione' e basta: bugia per
        omissione a 0% di commissione. Ogni traduzione deve nominare la tariffa tecnica."""
        for frase in re.findall(r'h_prezzo_osp:"([^"]*)"', self.host):
            self.assertIn("3%", frase, "h_prezzo_osp senza tariffa tecnica: %r" % frase)
        self.assertGreaterEqual(len(re.findall(r'h_prezzo_osp:"', self.host)), 8,
                                "attese 8 lingue per h_prezzo_osp")
        # anche il link diretto ("solo 5%") deve dire che il 3% si aggiunge
        for frase in re.findall(r'dir_p:"([^"]*)"', self.host):
            self.assertIn("3%", frase, "dir_p senza tariffa tecnica: %r" % frase)

    def test_traduzioni_non_rotte(self):
        """Il testo i18n sostituisce textContent: niente tag dentro gli span tradotti."""
        for m in re.finditer(r'<span data-i18n="(co_[a-z0-9_]+)">([^<]*)</span>', self.host):
            self.assertNotIn("<", m.group(2), "tag dentro uno span tradotto: %s" % m.group(1))


class TestContratto(unittest.TestCase):
    def test_articolo_6bis_it(self):
        t = CONTRATTO_HOST["it"]
        self.assertIn("ART. 6-BIS", t)
        self.assertIn("TARIFFA TECNICA", t)
        self.assertIn("3% (tre per cento)", t)
        self.assertIn("SEMPRE dovuta", t)
        self.assertIn("anche nei", t)            # "...anche nei periodi in cui la Commissione e' 0%"
        self.assertIn("Stripe", t)
        self.assertIn("non consegue alcun margine", t)

    def test_articolo_6bis_en(self):
        t = CONTRATTO_HOST["en"]
        self.assertIn("ART. 6-BIS", t)
        self.assertIn("TECHNICAL FEE", t)
        self.assertIn("3% (three per cent)", t)
        self.assertIn("ALWAYS due", t)
        self.assertIn("Stripe", t)
        self.assertIn("makes no margin", t)

    def test_versione_aggiornata_e_impronta_coerente(self):
        self.assertNotEqual(CONTRATTO_HOST_VERSIONE, "2026-07-11",
                            "il testo e' cambiato: la versione DEVE essere alzata "
                            "(altrimenti chi ha firmato il vecchio risulta legato al nuovo)")
        d = documento_corrente("it")
        self.assertEqual(d["versione"], CONTRATTO_HOST_VERSIONE)
        self.assertEqual(d["doc_sha256"], doc_sha256())
        self.assertIn(CONTRATTO_HOST_VERSIONE, CONTRATTO_HOST["it"])   # versione stampata nel testo
        self.assertIn("ART. 6-BIS", d["testo"])


class TestNessunaCifraOrfana(unittest.TestCase):
    """AUDIT A TAPPETO (2026-07-20): nessuna percentuale 'orfana' o superata nelle pagine che
    il CLIENTE vede. Ogni riga di `deploy/*.html` che parla di commissione o tariffa tecnica
    deve usare SOLO cifre allineate al motore; le righe che confrontano i concorrenti possono
    citare qualunque cifra (sono loro, non noi)."""

    KW_COSTO = re.compile(r"commission|commissione|comisi|Provision|tariffa tecnica|costo carta|"
                          r"technical fee|frais techniques|technische Geb|taxa t|tarifa t", re.I)
    KW_ALTRUI = re.compile(r"booking|airbnb|vrbo|expedia|agoda|tripadvisor|hostelworld|OTA|"
                           r"coloss|concorren|mercato|portale|competitor", re.I)
    # percentuali nostre legittime NON commissionali (penali, sconti, politiche di cancellazione)
    KW_ALTRO = re.compile(r"penale|penalit|cancellazion|rimbors|sconto|non rimborsabile|"
                          r"soggiorno lungo|IVA|VAT|tassa|refund|discount|width|height", re.I)
    PERC = re.compile(r"(\d{1,3})(?:[.,]\d+)?\s?%")

    def test_pagine_utente_solo_cifre_del_motore(self):
        bps = _psp_bps_default()
        ammesse = {0, BPS_DIRETTO // 100, LANCIO_BPS_FASE1 // 100,
                   LANCIO_BPS_REGIME // 100, bps // 100, 100}
        anomalie = []
        for nome in sorted(os.listdir(os.path.join(BASE, "deploy"))):
            if not nome.endswith(".html"):
                continue
            for n, riga in enumerate(_leggi("deploy/" + nome).splitlines(), 1):
                if not (self.PERC.search(riga) and self.KW_COSTO.search(riga)):
                    continue
                if self.KW_ALTRUI.search(riga) or self.KW_ALTRO.search(riga):
                    continue
                fuori = {int(x) for x in self.PERC.findall(riga)} - ammesse
                if fuori:
                    anomalie.append("deploy/%s:%d cifre=%s | %s"
                                    % (nome, n, sorted(fuori), riga.strip()[:110]))
        self.assertEqual(anomalie, [], "cifre non allineate al motore nelle pagine utente:\n"
                                       + "\n".join(anomalie))

    def test_radice_solo_cinque_documenti_ufficiali(self):
        """RIASSETTO 2026-07-20: in radice restano SOLO i 5 file ufficiali. Le strategie e i
        report storici stanno in `_archivio/` (cifre superate, non vanno seguite)."""
        ufficiali = {"README.md", "REGISTRO_INGEGNERIA.md", "RIPRENDI_QUI.md",
                     "DEPLOY.md", "CLAUDE.md"}
        presenti = {f for f in os.listdir(BASE) if f.endswith(".md")}
        self.assertEqual(presenti, ufficiali,
                         "in radice devono esserci SOLO i 5 documenti ufficiali; "
                         "trovati in più: %s | mancanti: %s"
                         % (sorted(presenti - ufficiali), sorted(ufficiali - presenti)))
        self.assertTrue(os.path.isfile(os.path.join(BASE, "_archivio",
                                                    "LEGGIMI-ARCHIVIO.md")),
                        "l'archivio deve avvisare che le sue cifre sono superate")

    def test_readme_unica_sorgente_testuale_del_tariffario(self):
        """Il README è l'UNICA fonte testuale di verità sulle tariffe: deve dichiarare tutti
        gli scaglioni del motore, il 3% SEMPRE dovuto e l'identità matematica."""
        r = _leggi("README.md")
        bps = _psp_bps_default()
        for atteso in ("%d%%" % (bps // 100), "%d%%" % (LANCIO_BPS_FASE1 // 100),
                       "%d%%" % (LANCIO_BPS_REGIME // 100), "%d%%" % (BPS_DIRETTO // 100),
                       str(LANCIO_GIORNI_GRATIS)):
            self.assertIn(atteso, r, "README: manca la cifra %s del motore" % atteso)
        self.assertIn("SEMPRE dovuta", r)            # la tariffa tecnica non si spegne mai
        self.assertIn("anche quando la commissione è 0%", r)
        self.assertIn("prezzo_ospite = netto_host + commissione + tariffa_tecnica", r)
        # niente affermazioni del vecchio README (stack Flask, server Aruba): NB "niente Flask"
        # e' una frase CORRETTA, quindi si cerca l'affermazione sbagliata, non la parola.
        self.assertNotIn("API REST Flask", r)
        self.assertNotIn("Aruba", r)
        self.assertIn("stdlib puro", r)

    def test_readme_dichiara_i_tre_consensi(self):
        """Il README deve descrivere la tutela legale come è implementata davvero."""
        r = _leggi("README.md")
        for atteso in ("1341-1342", "GDPR", "consensi_mancanti", "HMAC-SHA256",
                       "grigio e non cliccabile", "422"):
            self.assertIn(atteso, r, "README: manca '%s' nella sezione consensi" % atteso)


class TestTerminiPubblici(unittest.TestCase):
    def test_termini_dichiarano_la_tariffa(self):
        """Il testo italiano che fa fede deve dire le quattro cose che contano.

        Si legge dal MOTORE, non dal file: `deploy/termini.html` e' un guscio che chiede
        il documento a /api/legale/documento nella lingua dell'utente. Che il guscio sia
        davvero collegato lo pretende `test_testi_legali`.
        """
        t = TL.testo_termini("it")
        self.assertRegex(t, r"tariffa\s+tecnica",
                         "i termini non nominano la tariffa tecnica")
        self.assertRegex(t, r"SEMPRE DOVUTA|sempre dovuta",
                         "non dicono che e' SEMPRE dovuta")
        self.assertRegex(t, r"0%\s+per i primi 90 giorni",
                         "non dichiarano i 90 giorni a commissione zero")
        self.assertIn("Stripe", t, "non nominano il gestore di pagamento")

    def test_i_termini_dicono_il_3_in_tutte_le_lingue(self):
        """Una sola lingua che tace la tariffa basta a rendere disonesta la promessa."""
        mute = [lg for lg in TL.LINGUE
                if not re.search(r"3\s?%", TL.testo_termini(lg))]
        self.assertEqual(mute, [], "lingue che non dichiarano il 3%%: %s" % mute)

    def test_pagina_commissioni_resta_coerente(self):
        """La pagina Commissioni era gia' onesta: non deve perdere il 3%."""
        c = _leggi("deploy/commissioni.html")
        self.assertIn("3%", c)
        self.assertIn("costo carta", c)


class TestPagineCheReclutanoHost(unittest.TestCase):
    """GUARDIA — chi promette una percentuale all'host DEVE dire anche il 3%.

    TROVATO IL 2026-07-21, dopo la "Strada A". Tre pagine PUBBLICHE parlavano di
    commissione senza nominare mai la tariffa tecnica sempre dovuta:
      · `kit-marketing.html`  diceva "10% la nostra commissione" e "gratis";
      · `diventa-host.html`   prometteva "zero commissioni nascoste" in 8 lingue;
    cioe' esattamente la bugia involontaria che la Strada A doveva eliminare — un host
    reclutato con quei testi avrebbe scoperto il 3% solo dopo aver firmato.
    Erano sfuggite perche' l'audit automatico saltava ogni riga contenente
    "prenotazione": cercava la sigla "OTA" senza confini di parola e la trovava dentro
    "prenOTAzione". Qui la copertura non dipende piu' da nessuna euristica.
    """

    #  file -> deve dichiarare il 3% (True) oppure e' rivolto SOLO all'ospite (False)
    # `termini.html` non e' piu' in questa lista: e' diventato un guscio e il suo testo
    # vive nel motore. La stessa pretesa (chi parla di percentuali dichiara il 3%) e'
    # applicata al documento vero, in TUTTE le lingue, da
    # TestTerminiPubblici.test_i_termini_dicono_il_3_in_tutte_le_lingue.
    PAGINE_HOST = ("kit-marketing.html", "diventa-host.html", "commissioni.html",
                   "host.html")

    def _leggi(self, nome):
        import io
        import os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy", nome)
        # ASSENZA NON E' CONFORMITA': una pagina che sparisce non assolve la regola,
        # la rende impossibile da verificare — ed e' un fatto, non un'esenzione.
        self.assertTrue(os.path.exists(p), "pagina per host sparita: %s" % nome)
        return io.open(p, encoding="utf-8", errors="replace").read()

    def test_ogni_pagina_per_host_dichiara_la_tariffa_tecnica(self):
        for nome in self.PAGINE_HOST:
            testo = self._leggi(nome)
            self.assertRegex(
                testo, r"3\s?%",
                "%s parla agli host di percentuali ma NON nomina la tariffa tecnica "
                "del 3%%: e' la stessa mancanza di trasparenza chiusa il 2026-07-20."
                % nome)

    def test_nessuna_promessa_di_zero_costi_nascosti_senza_il_3(self):
        """"Zero commissioni nascoste" e' una promessa: vale solo se il 3% e' scritto."""
        import re
        # Sulle pagine di RECLUTAMENTO la promessa e il 3% devono stare VICINI: chi le
        # legge scorre pochi secondi. Sulle pagine tariffarie/legali (commissioni,
        # termini) basta che il 3% sia dichiarato: la pagina intera parla di quello,
        # ed e' gia' preteso dal test qui sopra.
        for nome in ("kit-marketing.html", "diventa-host.html"):
            testo = self._leggi(nome)
            # solo le promesse sui COSTI: "zero intermediari nascosti" parla d'altro
            promessa = (r"[^\"><]{0,70}"
                        r"(?:commission\w*|costi|spese|tariff\w*|fee|charges|"
                        r"comisi\w*|frais|Geb\w*|taxas)"
                        r"[^\"><]{0,25}(?:nascost\w*|hidden|ocult\w*|cach\w*|"
                        r"versteckt\w*|隠れ|隐藏)[^\"><]{0,70}")
            for frase in re.findall(promessa, testo, re.I):
                self.assertIn("3%", frase,
                              "%s promette '%s' senza nominare il 3%% nella stessa frase"
                              % (nome, frase.strip()))

    def test_il_kit_marketing_dice_la_verita_sulla_rampa(self):
        """Il kit non deve piu' vendere un "10% secco": la verita' (0%->8%->10%) e'
        anche l'argomento piu' forte che abbiamo."""
        testo = self._leggi("kit-marketing.html")
        self.assertIn("90 giorni", testo, "il kit non nomina la promo 0% dei 90 giorni")
        self.assertIn("3%", testo)
        # "iscriversi e pubblicare e' gratis" e' VERO (si paga solo sulla prenotazione):
        # cio' che non deve piu' esserci e' un "10%" secco venduto come LA commissione,
        # perche' nasconde sia la rampa sia il 3%.
        self.assertNotIn("10% la nostra commissione", testo)
        self.assertNotIn("Commissione al 10% per il tuo alloggio", testo)

    def test_le_percentuali_delle_pagine_sono_quelle_del_motore(self):
        """Ancoraggio al codice: se domani cambiano le costanti, questi testi devono
        cambiare con loro (o la suite diventa rossa)."""
        from fase98_policy_commissione import (BPS_DIRETTO, LANCIO_BPS_FASE1,
                                               LANCIO_BPS_REGIME, LANCIO_GIORNI_GRATIS)
        testo = self._leggi("kit-marketing.html") + self._leggi("diventa-host.html")
        self.assertIn("%d giorni" % LANCIO_GIORNI_GRATIS, testo)
        for bps in (LANCIO_BPS_FASE1, LANCIO_BPS_REGIME, BPS_DIRETTO):
            self.assertRegex(testo, r"\b%d\s?%%" % (bps // 100),
                             "manca la percentuale %d%% dichiarata dal motore"
                             % (bps // 100))


class TestEmailAgliHost(unittest.TestCase):
    """GUARDIA — anche le EMAIL agli host devono dire il 3%.

    TROVATO IL 2026-07-21: l'email di BENVENUTO (la prima cosa che un host legge)
    diceva "10% dal marketplace" — mentre nei primi 90 giorni paga 0% — e "nessun
    costo fisso", senza nominare mai la tariffa tecnica del 3%, sempre dovuta.
    Le pagine erano state sistemate, le email no.
    """

    def _benvenuto(self, lang="it"):
        from fase86_email import corpo_benvenuto_host_html
        return corpo_benvenuto_host_html("https://bookinvip.com/host.html", lingua=lang)

    def test_dichiara_la_tariffa_tecnica_IN_OGNI_LINGUA(self):
        """La trasparenza sul 3% e' la prima cosa che un host legge: non puo' mancare in
        nessuna delle 8 lingue (o in una si prometterebbe qualcosa di diverso)."""
        from fase86_email import LINGUE
        mute = [lg for lg in LINGUE if not __import__("re").search(r"3\s?%",
                                                                   self._benvenuto(lg))]
        self.assertEqual(mute, [], "il 3%% manca nelle lingue: %s" % mute)

    def test_dichiara_la_promozione_di_lancio_in_ogni_lingua(self):
        from fase98_policy_commissione import LANCIO_GIORNI_GRATIS
        from fase86_email import LINGUE
        for lg in LINGUE:
            corpo = self._benvenuto(lg)
            self.assertIn(str(LANCIO_GIORNI_GRATIS), corpo,
                          "i %d giorni mancano in '%s'" % (LANCIO_GIORNI_GRATIS, lg))
            self.assertRegex(corpo, r"0\s?%", "lo 0%% manca in '%s'" % lg)

    def test_non_promette_zero_costi_senza_qualificarlo(self):
        """"Nessun costo fisso" (frase ITALIANA) e' vero solo se subito accanto si dice
        qual e' il costo variabile sempre dovuto."""
        import re
        corpo = re.sub(r"<[^>]+>", " ", self._benvenuto("it"))
        for m in re.finditer(r"[Nn]essun[^.]{0,80}costo[^.]{0,80}\.", corpo):
            frase = m.group(0)
            self.assertRegex(frase, r"3\s?%",
                             "promessa '%s' senza il 3%% nella stessa frase" % frase.strip())

    def test_le_percentuali_vengono_dal_motore(self):
        from fase98_policy_commissione import (BPS_DIRETTO, LANCIO_BPS_FASE1,
                                               LANCIO_BPS_REGIME)
        corpo = self._benvenuto()
        for bps in (LANCIO_BPS_FASE1, LANCIO_BPS_REGIME, BPS_DIRETTO):
            self.assertRegex(corpo, r"(?<![0-9])%d\s?%%" % (bps // 100),
                             "manca %d%% dichiarato dal motore" % (bps // 100))


if __name__ == "__main__":
    unittest.main(verbosity=2)
