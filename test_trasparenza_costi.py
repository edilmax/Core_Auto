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


def _psp_bps_estera_default():
    """Idem, sugli annunci prezzati fuori euro: li' il gateway deve CONVERTIRE e la
    tariffa e' piu' alta. Serve perche' una pagina che la nomina dichiara una cifra
    diversa da quella in euro, ed e' corretta: senza questa, una guardia sulla cifra
    accuserebbe come falsa una riga vera a ogni giro (regola ferrea 10)."""
    src = _leggi("main_casavip.py")
    m = re.search(r'PAGAMENTO_BPS_ESTERA["\']\s*,\s*["\'](\d+)["\']', src)
    if not m:
        raise AssertionError("default PAGAMENTO_BPS_ESTERA non trovato in main_casavip.py")
    return int(m.group(1))


# La cifra della tariffa tecnica si scrive UNA VOLTA SOLA e si prende DAL MOTORE.
# Il 2026-08-09, quando e' passata dal 3% al 4% + 0,25 EUR, questo file aveva TECNICA
# scritto a mano in una quindicina di punti ed e' diventato lui il documento che
# dichiarava il falso -- proprio il difetto che esiste per impedire. Ora non puo' piu'
# succedere: cambia il motore, cambia la pretesa.
TECNICA = "%d%%" % (_psp_bps_default() // 100)          # la cifra viene dal motore
RX_TECNICA = r"%d\s?%%" % (_psp_bps_default() // 100)   # idem, con lo spazio facoltativo
# ⛔ Qui c'era un commento «es. "4%"», scritto a mano il 2026-08-10 e diventato falso lo
# stesso giorno. Su una riga che esiste APPOSTA per impedire i numeri scritti a mano.
# Un commento che nomina la cifra puo' diventare falso; uno che non la nomina, no.


class TestAncoraggioAlCodice(unittest.TestCase):
    """Il numero scritto nei testi DEVE essere quello che il motore applica davvero."""

    def test_i_ripieghi_di_fase185_combaciano_con_main(self):
        """`fase185._percentuali()` ha una SUA copia dei ripieghi della tariffa tecnica.
        Se diverge da `main_casavip.py`, i TERMINI DI SERVIZIO in 8 lingue dichiarano una
        cifra diversa da quella che il motore addebita davvero — un documento legale che
        dice il falso.

        ⛔ SUCCESSO DAVVERO il 2026-08-10: la tariffa e' passata da 4 a 5, `main` e' stato
        aggiornato e questa copia no. Per un po' i termini in otto lingue hanno dichiarato
        il 4% mentre si addebitava il 5%. Nessuno se ne sarebbe accorto: nessun test
        confrontava le due copie. Adesso una macchina le confronta."""
        import os as _os
        import fase185_testi_legali as _tl
        vecchi = {k: _os.environ.pop(k, None)
                  for k in ("PAGAMENTO_BPS", "PAGAMENTO_BPS_ESTERA", "PAGAMENTO_FISSO_CENTS")}
        try:
            p = _tl._percentuali()          # senza variabili d'ambiente -> parlano i ripieghi
        finally:
            for k, v in vecchi.items():
                if v is not None:
                    _os.environ[k] = v
        self.assertEqual(p["tecnica"], _psp_bps_default() // 100,
                         "fase185 ripiega su %d%% ma main dichiara %d%%: i termini in 8 "
                         "lingue direbbero una cifra diversa da quella addebitata"
                         % (p["tecnica"], _psp_bps_default() // 100))
        m = re.search(r'PAGAMENTO_BPS_ESTERA["\']\s*,\s*["\'](\d+)["\']', _leggi("main_casavip.py"))
        self.assertIsNotNone(m, "main_casavip.py non dichiara piu' PAGAMENTO_BPS_ESTERA: "
                                "questa prova non e' in condizione di misurare, e si ferma")
        estera = int(m.group(1))
        self.assertEqual(p["tecnica_estera"], estera // 100,
                         "fase185 ripiega su %d%% per la valuta estera, main dichiara %d%%"
                         % (p["tecnica_estera"], estera // 100))

    def test_tariffa_tecnica_dichiarata_uguale_al_codice(self):
        bps = _psp_bps_default()
        self.assertEqual(bps % 100, 0, "tariffa non intera: i testi '3%%' andrebbero rivisti")
        atteso = "%d%%" % (bps // 100)                    # 300 bps -> TECNICA
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
        for atteso in ("90 giorni", "8%", "10%", "5%", TECNICA):
            self.assertIn(atteso, host, "dashboard host: manca '%s'" % atteso)
        for lang in ("it", "en"):
            t = CONTRATTO_HOST[lang]
            for atteso in ("90", "8%", "10%", "5%", TECNICA):
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
        self.assertIn("tariffa tecnica del " + TECNICA, self.host)
        self.assertIn("technical fee of " + TECNICA, self.host)
        self.assertIn("sempre attiva", self.host)          # vale in OGNI periodo
        self.assertIn("always active", self.host)

    def test_nessun_testo_promette_il_netto_senza_la_tariffa(self):
        """Il campo prezzo diceva 'ricevi questo meno la commissione' e basta: bugia per
        omissione a 0% di commissione. Ogni traduzione deve nominare la tariffa tecnica."""
        for frase in re.findall(r'h_prezzo_osp:"([^"]*)"', self.host):
            self.assertIn(TECNICA, frase, "h_prezzo_osp senza tariffa tecnica: %r" % frase)
        self.assertGreaterEqual(len(re.findall(r'h_prezzo_osp:"', self.host)), 8,
                                "attese 8 lingue per h_prezzo_osp")
        # anche il link diretto ("solo 5%") deve dire che il 3% si aggiunge
        for frase in re.findall(r'dir_p:"([^"]*)"', self.host):
            self.assertIn(TECNICA, frase, "dir_p senza tariffa tecnica: %r" % frase)

    def test_traduzioni_non_rotte(self):
        """Il testo i18n sostituisce textContent: niente tag dentro gli span tradotti."""
        for m in re.finditer(r'<span data-i18n="(co_[a-z0-9_]+)">([^<]*)</span>', self.host):
            self.assertNotIn("<", m.group(2), "tag dentro uno span tradotto: %s" % m.group(1))


class TestContratto(unittest.TestCase):
    def test_articolo_6bis_it(self):
        t = CONTRATTO_HOST["it"]
        self.assertIn("ART. 6-BIS", t)
        self.assertIn("TARIFFA TECNICA", t)
        # La cifra si RICAVA DAL MOTORE, non si riscrive qui: riscriverla a mano e'
        # esattamente il difetto che questo file esiste per impedire.
        self.assertIn("%d%% (" % (_psp_bps_default() // 100), t)
        self.assertIn("SEMPRE dovuta", t)
        self.assertIn("anche nei", t)            # "...anche nei periodi in cui la Commissione e' 0%"
        self.assertIn("Stripe", t)
        # La QUOTA FISSA e la maggiorazione sulla VALUTA ESTERA devono essere dichiarate:
        # senza, il contratto direbbe meno di quanto addebitiamo davvero.
        self.assertIn("per ogni transazione", t)
        self.assertIn("valuta diversa dall'euro", t)
        # La vecchia riga pretendeva "non consegue alcun margine". Con una tariffa che deve
        # coprire la carta PEGGIORE quella frase e' FALSA, e sarebbe falsa dentro un
        # contratto. Ora si pretende il contrario: che il contratto dica il vero.
        self.assertNotIn("non consegue alcun margine", t)
        self.assertIn("inferiore o superiore alla tariffa", t)

    def test_articolo_6bis_en(self):
        t = CONTRATTO_HOST["en"]
        self.assertIn("ART. 6-BIS", t)
        self.assertIn("TECHNICAL FEE", t)
        self.assertIn("%d%% (" % (_psp_bps_default() // 100), t)
        self.assertIn("ALWAYS due", t)
        self.assertIn("Stripe", t)
        self.assertIn("per transaction", t)
        self.assertIn("other than the euro", t)
        self.assertNotIn("makes no margin", t)
        self.assertIn("higher than the fee", t)

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
                if not re.search(RX_TECNICA, TL.testo_termini(lg))]
        self.assertEqual(mute, [], "lingue che non dichiarano il 3%%: %s" % mute)

    def test_pagina_commissioni_resta_coerente(self):
        """La pagina Commissioni era gia' onesta: non deve perdere la tariffa tecnica.

        ⛔ QUI C'ERA `assertIn("costo carta")`, e il 2026-08-29 e' stato cambiato in
        «tariffa tecnica». NON e' uno sconto fatto per far passare una modifica, ed e'
        importante che chi legge fra sei mesi lo sappia distinguere: «costo carta» era
        la formula di UN'ETICHETTA che diceva anche «0 nostro margine» — cioe' la
        stringa cercata viveva dentro la bugia che quel giorno e' stata tolta. Tenerla
        avrebbe voluto dire conservare la formulazione sbagliata per compiacere una
        guardia. «Tariffa tecnica» e' il termine che usano il CONTRATTO (fase185) e
        tutti gli altri strumenti del progetto, e sulla pagina compare piu' volte, non
        una: la pretesa e' piu' forte di prima, non piu' debole.
        """
        c = _leggi("deploy/commissioni.html")
        self.assertIn(TECNICA, c)
        self.assertIn("tariffa tecnica", c)


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
                testo, RX_TECNICA,
                "%s parla agli host di percentuali ma NON nomina la tariffa tecnica "
                "del 3%%: e' la stessa mancanza di trasparenza chiusa il 2026-07-20."
                % nome)

    def test_nessuna_promessa_di_zero_costi_nascosti_senza_il_3(self):
        """"Zero commissioni nascoste" e' una promessa: vale solo se la tariffa tecnica
        e' scritta nella stessa frase."""
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
                self.assertIn(TECNICA, frase,
                              "%s promette '%s' senza nominare il 3%% nella stessa frase"
                              % (nome, frase.strip()))

    def test_il_kit_marketing_dice_la_verita_sulla_rampa(self):
        """Il kit non deve piu' vendere un "10% secco": la verita' (0%->8%->10%) e'
        anche l'argomento piu' forte che abbiamo."""
        testo = self._leggi("kit-marketing.html")
        self.assertIn("90 giorni", testo, "il kit non nomina la promo 0% dei 90 giorni")
        self.assertIn(TECNICA, testo)
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
    """GUARDIA — anche le EMAIL agli host devono dire la tariffa tecnica.

    TROVATO IL 2026-07-21: l'email di BENVENUTO (la prima cosa che un host legge)
    diceva "10% dal marketplace" — mentre nei primi 90 giorni paga 0% — e "nessun
    costo fisso", senza nominare mai la tariffa tecnica, sempre dovuta.
    Le pagine erano state sistemate, le email no.
    """

    def _benvenuto(self, lang="it"):
        from fase86_email import corpo_benvenuto_host_html
        return corpo_benvenuto_host_html("https://bookinvip.com/host.html", lingua=lang)

    def test_dichiara_la_tariffa_tecnica_IN_OGNI_LINGUA(self):
        """La trasparenza sul 3% e' la prima cosa che un host legge: non puo' mancare in
        nessuna delle 8 lingue (o in una si prometterebbe qualcosa di diverso)."""
        from fase86_email import LINGUE
        mute = [lg for lg in LINGUE if not __import__("re").search(RX_TECNICA,
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
            self.assertRegex(frase, RX_TECNICA,
                             "promessa '%s' senza il 3%% nella stessa frase" % frase.strip())

    def test_le_percentuali_vengono_dal_motore(self):
        from fase98_policy_commissione import (BPS_DIRETTO, LANCIO_BPS_FASE1,
                                               LANCIO_BPS_REGIME)
        corpo = self._benvenuto()
        for bps in (LANCIO_BPS_FASE1, LANCIO_BPS_REGIME, BPS_DIRETTO):
            self.assertRegex(corpo, r"(?<![0-9])%d\s?%%" % (bps // 100),
                             "manca %d%% dichiarato dal motore" % (bps // 100))


class TestNessunaPromessaDiMargineZero(unittest.TestCase):
    """GUARDIA — nessun testo che l'host legge PRIMA di firmare puo' affermare che la
    tariffa tecnica non ci lascia margine, ne' dichiararne una diversa da quella del
    motore: il contratto che poi firma dice il contrario.

    NATA IL 2026-08-29. Le pagine pubbliche dicevano, in OTTO lingue, «una tariffa
    tecnica del 3% che copre il costo della carta: su quella riga non guadagniamo
    nulla». Due affermazioni false in una frase sola:
      · la CIFRA — il motore ne addebita un'altra dal 2026-08-10, quando la vecchia fu
        misurata SOTTO COSTO (`collaudi/conti_stripe.py`);
      · il MARGINE — lo stesso strumento misura «copre a QUALUNQUE importo» su tutte e
        cinque le carte e «Nessun caso in perdita piena». Nei primi giorni di promo,
        quando la commissione e' zero, quella tariffa e' l'UNICO ricavo e non e' nullo.
    Il contratto, `fase185_testi_legali.py` righe 137-139, dichiarava gia' il vero:
    «il costo effettivamente sostenuto dalla Piattaforma puo' risultare INFERIORE O
    SUPERIORE alla tariffa». Il parlato smentiva il firmato — e lo faceva dentro la
    frase che rivendicava trasparenza («preferiamo dirtelo adesso, non dopo la firma»).

    PERCHE' NON BASTAVANO LE GUARDIE GIA' PRESENTI. Le altre di questo file erano tutte
    VERDI mentre le pagine dicevano quelle cose, e non per un difetto: pretendono che la
    cifra giusta SIA PRESENTE, e lo era (nel pie' di pagina). Una pagina puo' dichiarare
    due tariffe diverse e soddisfarle tutte. Qui si pretende l'ASSENZA di quella
    sbagliata — che e' una domanda diversa, non una piu' severa.

    ⛔ LIMITE DICHIARATO (sbaglio S6), e va letto PRIMA di fidarsi di questo verde:
    il primo test cerca delle FORME, cioe' un elenco di frasi nelle lingue in cui
    esistono oggi. Una riscrittura con parole diverse lo evade. E' una guardia contro la
    REGRESSIONE di quell'affermazione, NON contro ogni bugia possibile: il suo verde dice
    «quella frase non e' tornata», mai «le pagine dicono il vero».

    ⛔ E OGNI VOLTA CHE SI STRINGE UNA DI QUESTE REGEX, VA RIFATTA LA PROVA CHE VEDE
    ANCORA — riapplicandola ai file presi da `git show HEAD:` e pretendendo che li
    segnali. Il motivo non e' pignoleria: le regex qui sotto sono state strette piu'
    volte per togliere falsi allarmi, e ogni stretta puo' rendere cieca la guardia
    invece che precisa. Le due cose si assomigliano moltissimo — un verde. La prima
    volta che e' stata fatta, quella prova ha rivelato che un verde precedente era
    **vero per fortuna, non per costruzione**: le forme che mancavano all'elenco
    (francese al singolare, tedesco con una parola in mezzo, inglese con la cifra dopo)
    su quelle pagine non c'erano, ma nessuno l'aveva misurato. Fra «giusto per fortuna»
    e «giusto per costruzione» non c'e' differenza mentre li guardi, e c'e' tutta la
    differenza la volta dopo.

    ⛔ E PERCHE' NON PUO' FARLO L'AUDIT AL POSTO SUO: `collaudi/audit_coerenza_tariffe.py`
    confronta CIFRE, non AFFERMAZIONI, e per giunta non gira in CI (solo dentro
    `collaudi/batteria.py`, che si lancia a mano). Misurato il 2026-08-29:
    `commissioni.html` non compare in nessuno dei suoi giri e l'affermazione ce l'ha.
    Sono due difetti diversi e vogliono due guardie diverse.
    """

    @staticmethod
    def _pagine():
        """TUTTE le pagine di `deploy/`, LETTE DALLA CARTELLA — non un elenco scritto a mano.

        ⛔ QUI C'ERA UN ELENCO DI QUATTRO NOMI, e il 2026-08-29 ha nascosto un difetto vero:
        `deploy/bunker.html` dichiarava la tariffa superata in SETTE lingue su otto e questa
        guardia non poteva vederlo, perche' quel nome non era nell'elenco. Non era una svista:
        era **cecita' di progetto**. Una guardia con una lista chiusa non dice «non ho trovato
        niente», dice «non ho guardato altrove» — e le due cose arrivano identiche a chi legge
        il verde. Un elenco scritto a mano e' un obbligo affidato alla buona volonta' di chi,
        fra sei mesi, dovra' RICORDARSI di aggiungerci la pagina nuova.
        ⇒ Cosi' una pagina creata domani entra sotto guardia da sola. Costo misurato in
        rumore: ZERO — allargando, l'unica pagina che si accendeva era quella col difetto.
        """
        cartella = os.path.join(BASE, "deploy")
        nomi = sorted(n for n in os.listdir(cartella) if n.endswith(".html"))
        #  ASSENZA NON E' CONFORMITA': se la cartella sparisse o si svuotasse, i due test
        #  qui sotto passerebbero senza aver guardato NIENTE -- il verde peggiore di tutti.
        if len(nomi) < 4:
            raise AssertionError("deploy/ ha %d pagine: la guardia non sta guardando" % len(nomi))
        return nomi

    #  L'affermazione, nelle lingue in cui le pagine esistono. Le forme sono state
    #  RACCOLTE DAI FILE, non immaginate: una guardia scritta a memoria cerca frasi
    #  che nessuno ha mai scritto e tace su quelle che ci sono (sbaglio S2).
    #  ⛔ E LE FORME SONO DUE FAMIGLIE, non una. La prima e' la frase distesa («non
    #  guadagniamo nulla»); la seconda e' la stessa cosa detta in due parole dentro
    #  un'etichetta («0 nostro margine»). Cercando solo la prima famiglia questa guardia
    #  ha visto UNA occorrenza su commissioni.html e ne mancava SETTE — le traduzioni
    #  della seconda. Misurato il 2026-08-29, e trovato solo perche' si e' aperto il file
    #  invece di fidarsi del verde: e' il motivo per cui il limite qui sotto va letto.
    MARGINE_ZERO = re.compile(
        r"non guadagniamo nulla|we (?:make|earn) nothing|no ganamos nada|"
        r"ne gagnons rien|verdienen wir nichts|n[aã]o ganhamos nada|"
        r"不赚取[^，。]*利润|利益はありません|"
        r"0\s*nostro margine|nessun (?:nostro )?margine|"
        r"0\s*margin for us|0\s*margen para nosotros|0\s*marge pour nous|"
        r"0\s*Marge für uns|0\s*margem para n[oó]s|当社利益0|我们0\s?利润", re.I)

    #  ⛔ LA DIVISIONE NON E' PER ALFABETO, E' PER LINGUA — misurata sui file, non deduttta:
    #    · il numero VIENE DOPO in it/es/fr/de/pt  («tariffa tecnica del ...%»)
    #    · il numero VIENE PRIMA in en/ja/zh       («...% technical fee»)
    #  Mescolarle produce tutt'e due gli errori insieme: cercando «prima» anche nelle
    #  lingue latine, il francese «meme a 0%, des frais techniques» faceva scattare un
    #  falso allarme sulla commissione promozionale; cercando solo «dopo» si PERDEVA
    #  l'inglese — che e' la lingua di ripiego per ogni visitatore con lingua non
    #  prevista, cioe' il caso piu' comune di tutti.
    #  ⛔ E IL CINESE E IL GIAPPONESE VOGLIONO LE DUE DIREZIONI, non una.
    #  In quelle lingue la cifra puo' stare prima della parola o dopo, e la scelta
    #  dipende da come e' girata la frase (⛔ e qui NON si scrive un esempio con la
    #  cifra dentro: un commento che nomina un numero puo' diventare falso, e questo
    #  file esiste apposta per impedire i numeri scritti a mano — S17). Cercarne una
    #  sola vuol dire che riscrivendo il testo la guardia SMETTE DI GUARDARE senza dirlo
    #  — e nessuno se ne accorge, perche' sono le due lingue che nessuno di noi rilegge.
    #  La finestra resta STRETTA: con 25 caratteri, in ideogrammi, prendeva lo 0% della
    #  promozione che sta nella stessa frase (misurato: 4 falsi allarmi su kit-marketing).
    #  ⛔ E LE FORME VANNO PRESE DAI FILE, NON DALLA GRAMMATICA CHE UNO SI RICORDA.
    #  Scritte a memoria, tre varianti vere sfuggivano — trovate il 2026-08-29
    #  scandendo TUTTO `deploy/` invece delle sole pagine di questo elenco:
    #    · francese al SINGOLARE («frais technique»), non solo plurale;
    #    · tedesco con una parola IN MEZZO («Technische Stripe-Gebühr»);
    #    · inglese con la cifra DOPO («technical fee (…%)»), non solo prima.
    #  Nessuna delle tre era immaginabile: si vedono solo aprendo i file.
    _KW_DOPO = (r"tariffa tecnica|tarifa t[eé]cnica|frais techniques?|"
                r"technische[\w\s-]{0,12}Geb[uü]hr|taxa t[eé]cnica|technical fee")
    _KW_PRIMA = r"technical fee"
    _KW_CJK = r"技術手数料|技术费"
    #  Niente formattazione con `%` in queste: il carattere cercato E' `%`, e
    #  `"...%[^%%]..." % KW` esplode con «unsupported format character». Si concatena.
    #  ⛔ IL BUCO FRA LA CIFRA E LA PAROLA NON PUO' SCAVALCARE UN A CAPO NE' UN PUNTO
    #  ELENCO. Senza questo, in cinese «...delle OTA 18-25%\n• tariffa tecnica...» faceva
    #  scattare l'allarme sul 25% del CONCORRENTE, che sta nel punto elenco PRECEDENTE:
    #  in ideogrammi quattro caratteri bastano ad attraversare il divisorio. Il `\\`
    #  serve perche' negli attributi JavaScript l'a capo e' scritto come DUE caratteri.
    _BUCO = r"[^%\\\n•]"
    RX_CIFRA_DOPO = re.compile(r"(?:" + _KW_DOPO + r")" + _BUCO + r"{0,25}?(\d{1,3})\s?%",
                               re.I)
    RX_CIFRA_PRIMA = re.compile(r"(\d{1,3})\s?%" + _BUCO + r"{0,4}?(?:" + _KW_PRIMA + r")",
                                re.I)
    RX_CIFRA_CJK = re.compile(r"(\d{1,3})\s?%" + _BUCO + r"{0,4}?(?:" + _KW_CJK + r")"
                              r"|(?:" + _KW_CJK + r")" + _BUCO + r"{0,4}?(\d{1,3})\s?%")

    def _leggi(self, nome):
        p = os.path.join(BASE, "deploy", nome)
        # ASSENZA NON E' CONFORMITA': una pagina che sparisce non assolve la regola,
        # la rende impossibile da verificare.
        self.assertTrue(os.path.exists(p), "pagina per host sparita: %s" % nome)
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()

    def test_nessuna_pagina_afferma_di_non_guadagnare_sulla_tariffa_tecnica(self):
        colpevoli = []
        for nome in self._pagine():
            trovate = self.MARGINE_ZERO.findall(self._leggi(nome))
            if trovate:
                colpevoli.append("%s: %d occorrenze" % (nome, len(trovate)))
        self.assertEqual(
            [], colpevoli,
            "queste pagine affermano che non guadagniamo sulla tariffa tecnica, ma il "
            "CONTRATTO che l'host firma dice il contrario (fase185_testi_legali.py "
            "righe 137-139: «il costo effettivamente sostenuto dalla Piattaforma puo' "
            "risultare INFERIORE O SUPERIORE alla tariffa»). Non e' una regola di stile: "
            "e' una contraddizione con un documento firmato. Occorrenze (non righe): %s"
            % "; ".join(colpevoli))

    def test_la_tariffa_tecnica_scritta_nelle_pagine_e_quella_del_motore(self):
        """La cifra attaccata alle parole «tariffa tecnica» dev'essere quella che il
        motore addebita davvero — quella in euro o quella in valuta estera, non altre.
        ⛔ Si guarda solo la percentuale ATTACCATA a quelle parole, non tutte quelle
        della riga: le pagine nominano legittimamente le percentuali dei CONCORRENTI,
        e pretenderle uguali alle nostre sarebbe un falso allarme a ogni giro."""
        ammesse = {_psp_bps_default() // 100, _psp_bps_estera_default() // 100}
        sbagliate = []
        for nome in self._pagine():
            testo = self._leggi(nome)
            for rx in (self.RX_CIFRA_DOPO, self.RX_CIFRA_PRIMA, self.RX_CIFRA_CJK):
                for m in rx.finditer(testo):
                    #  la regex CJK ha DUE gruppi (cifra prima / cifra dopo): quello
                    #  che non ha corrisposto e' None, e si prende l'altro.
                    cifra = next(g for g in m.groups() if g is not None)
                    if int(cifra) not in ammesse:
                        sbagliate.append("%s: «%s»"
                                         % (nome, " ".join(m.group(0).split())[:60]))
        self.assertEqual(
            [], sbagliate,
            "queste pagine dichiarano una tariffa tecnica che il motore NON addebita "
            "(ammesse dal codice: %s). Un host reclutato con una cifra e addebitato con "
            "un'altra la scopre dopo aver firmato. Casi: %s"
            % (sorted(ammesse), "; ".join(sbagliate)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
