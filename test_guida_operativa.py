"""GUARDIA — `guida-operativa.html`, l'ultima pagina pubblica che nessuno sorvegliava.

TROVATA IL 2026-07-21 dalla PIRAMIDE (`collaudi/piramide.py`), che confronta l'inventario
ricavato dal codice con tutto cio' che i test nominano. Era l'unica pagina di `deploy/`
mai citata da un test: pubblica (HTTP 200) e piena di percentuali — rimborsi, penali —
che nessuno confrontava col motore.

Non conteneva errori. Ma una pagina pubblica che promette numeri e che nessun test
guarda e' esattamente il modo in cui, il 2026-07-20, la promessa "10%" e' rimasta per
mesi in contraddizione col 13% realmente addebitato.

Qui le sue cifre vengono ancorate alle costanti del codice: se domani la penale cambia
e la guida no, la suite diventa rossa.
"""

import io
import os
import re
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
PAGINA = os.path.join(QUI, "deploy", "guida-operativa.html")


def _leggi(p):
    with io.open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


class TestGuidaOperativa(unittest.TestCase):

    def setUp(self):
        if not os.path.exists(PAGINA):
            # ASSENZA NON E' CONFORMITA': una pagina che sparisce non assolve la
            # regola, rende impossibile verificarla — ed e' un fatto, non un'esenzione.
            self.fail("guida-operativa.html non c'e' piu': la guida per gli operatori "
                      "e' sparita dal deploy")
        self.testo = _leggi(PAGINA)

    def test_la_pagina_e_viva(self):
        self.assertGreater(len(self.testo), 1500, "pagina troppo corta: e' un guscio?")
        self.assertIn("<title>", self.testo)

    def test_la_penale_dichiarata_e_quella_del_MOTORE(self):
        """Il cuore della guardia: la percentuale scritta nella guida deve venire dalla
        costante che il motore applica davvero, non da un ricordo di chi l'ha scritta."""
        from fase83_server import PENALE_HOST_BPS
        attesa = "%d%%" % (PENALE_HOST_BPS // 100)
        self.assertIn(attesa, self.testo,
                      "la guida non dichiara la penale vera del motore (%s): "
                      "se e' cambiata nel codice, va cambiata anche qui" % attesa)

    def test_nessuna_percentuale_inventata(self):
        """Ogni percentuale della pagina deve corrispondere a un valore che il motore
        usa davvero, oppure essere uno di quelli ovvi (0 e 100)."""
        from fase83_server import PENALE_HOST_BPS
        from fase98_policy_commissione import (BPS_DIRETTO, LANCIO_BPS_FASE1,
                                               LANCIO_BPS_REGIME)
        ammesse = {0, 100,
                   PENALE_HOST_BPS // 100,
                   BPS_DIRETTO // 100,
                   LANCIO_BPS_FASE1 // 100,
                   LANCIO_BPS_REGIME // 100,
                   3}                       # tariffa tecnica
        senza_marcatori = re.sub(r"<[^>]+>", " ", self.testo)
        trovate = {int(x) for x in re.findall(r"(\d{1,3})\s?%", senza_marcatori)}
        inventate = sorted(trovate - ammesse)
        self.assertEqual(inventate, [],
                         "la guida cita percentuali che il motore non applica: %s "
                         "(ammesse: %s)" % (inventate, sorted(ammesse)))

    def test_se_parla_di_commissione_deve_dire_il_3(self):
        """Chi promette una percentuale di commissione deve dichiarare anche la tariffa
        tecnica sempre dovuta.

        PRIMA QUESTO TEST SI SALTAVA DA SOLO quando la pagina non nominava le
        commissioni. Nel merito aveva ragione — la guida parla di rimborsi e di penale,
        non di commissioni — ma un test che si assolve da solo **sparisce dal rapporto**:
        resta scritto "skipped" e nessuno lo legge piu'. Il giorno in cui qualcuno
        aggiunge una promessa di commissione alla guida, il salto smette di essere
        legittimo e nulla lo segnala.

        Ora si asserisce in tutti e due i rami: o la tariffa tecnica c'e', oppure si
        **dimostra** che di commissioni non si parla, con tutte le parole che varrebbero
        come promessa.
        """
        parla = re.search(r"commission|provvigion|trattenut[ao]\s+d[ai]\s+noi",
                          self.testo, re.I)
        if parla:
            self.assertRegex(
                self.testo, r"3\s?%",
                "parla di commissioni (%r) senza dichiarare la tariffa tecnica"
                % parla.group(0))
            return
        # ramo di esenzione: va DIMOSTRATO, non dato per buono
        for parola in ("commission", "provvigion", "percentuale che tratteniamo"):
            self.assertNotRegex(
                self.testo, parola,
                "l'esenzione non vale piu': la guida ha cominciato a parlare di "
                "commissioni (%r) e ora deve dichiarare il 3%%" % parola)

    def test_nessun_segreto_nella_pagina(self):
        for spia in ("sk_live", "sk_test", "whsec_", "BUNKER_PASSWORD", "ADMIN_KEY"):
            self.assertNotIn(spia, self.testo, "segreto nella pagina: %s" % spia)


class TestOgniPaginaPubblicaEsorvegliata(unittest.TestCase):
    """Che non ricapiti: ogni `deploy/*.html` dev'essere nominata da almeno un test."""

    def test_nessuna_pagina_resta_senza_guardiani(self):
        pagine = sorted(f for f in os.listdir(os.path.join(QUI, "deploy"))
                        if f.endswith(".html"))
        testi = []
        for f in os.listdir(QUI):
            if f.startswith("test_") and f.endswith(".py"):
                testi.append(_leggi(os.path.join(QUI, f)))
        tutto = chr(10).join(testi)
        scoperte = [p for p in pagine if p not in tutto]
        self.assertEqual(scoperte, [],
                         "queste pagine pubbliche non sono nominate da NESSUN test: "
                         "potrebbero mentire o rompersi senza che nessuno se ne "
                         "accorga: %s" % scoperte)


if __name__ == "__main__":
    unittest.main(verbosity=2)
