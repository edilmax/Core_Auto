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
        for rel in ("deploy/host.html", "deploy/termini.html"):
            self.assertIn(atteso, _leggi(rel),
                          "%s non dichiara la tariffa tecnica %s del codice" % (rel, atteso))
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


class TestTerminiPubblici(unittest.TestCase):
    def test_termini_dichiarano_la_tariffa(self):
        t = _leggi("deploy/termini.html")
        self.assertIn("tariffa tecnica fissa del 3%", t)
        self.assertIn("sempre dovuta", t)
        self.assertIn("0% per i primi 90 giorni", t)
        self.assertIn("Stripe", t)

    def test_pagina_commissioni_resta_coerente(self):
        """La pagina Commissioni era gia' onesta: non deve perdere il 3%."""
        c = _leggi("deploy/commissioni.html")
        self.assertIn("3%", c)
        self.assertIn("costo carta", c)


if __name__ == "__main__":
    unittest.main()
