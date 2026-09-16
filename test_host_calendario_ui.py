"""
Guardia UI pannelli (statica, zero browser): ogni helper JS USATO in una pagina
deve essere DEFINITO nella stessa pagina (le pagine deploy/*.html sono
self-contained: un solo <script> inline, nessun include condiviso).

Bug #34 (provato staticamente): host.html chiamava money() — definita SOLO in
admin.html/index.html (copia-incolla cross-pagina) — dentro il handler del
bottone "💶 Prezzi": ReferenceError alla prima cella con prezzo, calendario
prezzi MORTO nel browser mentre la suite era verde (gap #1: niente E2E).
"""
import os
import re
import unittest

BASE = os.path.dirname(os.path.abspath(__file__))
PAGINE = ("host.html", "index.html", "admin.html")
HELPERS = ("money", "fmt", "valExp", "valSym", "toCents")


def _testo(pagina):
    with open(os.path.join(BASE, "deploy", pagina), encoding="utf-8") as f:
        return f.read()


class TestHelperDefinitiPerPagina(unittest.TestCase):
    def test_helper_usati_sono_definiti_nella_stessa_pagina(self):
        for pagina in PAGINE:
            t = _testo(pagina)
            for nome in HELPERS:
                tutti = len(re.findall(r"(?<![\w.$])%s\(" % nome, t))
                defs = len(re.findall(r"function\s+%s\(" % nome, t)) + \
                    len(re.findall(r"(?:const|let|var)\s+%s\s*=" % nome, t))
                chiamate = tutti - len(re.findall(r"function\s+%s\(" % nome, t))
                if chiamate > 0:
                    self.assertGreater(
                        defs, 0,
                        "%s: %s() usato %d volte ma MAI definito in pagina "
                        "(classe bug #34)" % (pagina, nome, chiamate))

    def test_host_niente_money(self):
        """host.html usa fmt() (sua, per-valuta): money() non deve riapparire."""
        self.assertNotIn("money(", _testo("host.html"))

    def test_host_calendario_prezzi_gestisce_chiuso(self):
        """La vista prezzi colora anche lo stato 'chiuso' (emesso da fase119).

        2026-07-18 (semaforo universale): il controllo per-stringa `c.stato==='chiuso'`
        e' stato sostituito dalla mappa UNICA `SEMAFORO`, che DEVE coprire il dialetto
        di fase119 (prenotato/venduto/chiuso) e la vista prezzi DEVE usarla."""
        t = _testo("host.html")
        i = t.index("const SEMAFORO")
        mappa = t[i:i + 220]
        for stato in ("chiuso:", "prenotato:", "venduto:"):
            self.assertIn(stato, mappa, "SEMAFORO non copre lo stato %s" % stato)
        # la vista prezzi consulta la mappa (non piu' if per-stringa)
        self.assertIn("SEMAFORO[c.stato]", t)


class TestNessunaCasellaDiPrezzoPARTEGIASCRITTA(unittest.TestCase):
    """⛔ D20 — scritta PRIMA della riparazione e vista ROSSA sul codice di produzione.

    LA FAMIGLIA, non l'esemplare (METODO v4, PARTE 10 direzione 7 «valori scritti a mano»):
    una casella del pannello che SCRIVE un prezzo non parte mai con un numero dentro.
    Il 2026-09-15 il fondatore ha caricato un annuncio a 1 EUR e il pannello ha aperto il
    periodo a 90: `r_prezzo` partiva con `value="90"`, `d_prezzo` e `p_prezzo` con
    `value="95"` — presenti dal commit ae36668 del 13/7 e mai tolti. Chi non le cambia
    vende alla cifra di qualcun altro, e l'ospite paga quella.

    ⛔ Gli id NON sono scritti a mano: si LEGGONO dal pannello (chi manda
    `prezzo_notte_cents` o `prezzo_netto_cents` al server). Una casella nuova entra da sola
    nel perimetro, ed e' il motivo per cui questa guardia chiude la famiglia invece di
    inseguire i tre esemplari di oggi.
    ⛔ COSA NON ESAMINA (D18 punto 3): le caselle che non fissano un prezzo per notte
    (tassa di soggiorno, sconti, unita') e i due calcolatori che non mandano niente al
    server (`tr_prezzo` della trasparenza, `dp_base` del prezzo suggerito).
    """

    RE_CASELLE = re.compile(
        r"(?:prezzo_notte_cents|prezzo_netto_cents)\s*:\s*toCents\(\s*"
        r"document\.getElementById\('([^']+)'\)")

    def test_le_caselle_che_scrivono_un_prezzo_partono_VUOTE(self):
        t = _testo("host.html")
        ids = sorted(set(self.RE_CASELLE.findall(t)))
        # PREMESSA (sbaglio S1: il vuoto non e' una misura). Se la lettura non trovasse piu'
        # nessuna casella, «nessuna e' precompilata» sarebbe un verde che non ha guardato.
        self.assertGreaterEqual(
            len(ids), 3,
            "misura non valida: nel pannello ho letto %d caselle che scrivono un prezzo "
            "(attese almeno 3: annuncio, giorno, periodo). La lettura non parla piu' del "
            "codice di oggi." % len(ids))
        precompilate = []
        for nome in ids:
            tag = re.search(r"<input[^>]*\bid=\"%s\"[^>]*>" % re.escape(nome), t)
            self.assertIsNotNone(
                tag, "la casella %s e' usata dal pannello ma non ha un <input> in pagina" % nome)
            val = re.search(r"\bvalue=\"([^\"]*)\"", tag.group(0))
            if val and val.group(1).strip():
                precompilate.append("%s=%s" % (nome, val.group(1)))
        self.assertEqual(
            precompilate, [],
            "queste caselle di PREZZO partono gia' scritte, e l'host che non le cambia vende "
            "a quella cifra: %s (lette %d caselle dal pannello)"
            % (", ".join(precompilate), len(ids)))

    def test_ogni_casella_di_prezzo_RIFIUTA_il_vuoto(self):
        """⛔ IL VUOTO NON E' ZERO, ma il pannello lo trasformava in zero.

        `BV.toCents` fa `parseFloat(maj)||0` (deploy/app.js:91): svuotare la casella e
        premere il pulsante aprirebbe le notti IN REGALO, con un «✅» in faccia. E' il
        difetto che nasce dalla riparazione di sopra, quindi la riparazione porta con se'
        il suo rifiuto — e questa guardia pretende che ci sia per OGNI casella di prezzo
        letta dal pannello, non per le tre di oggi (D19: una difesa si mette alla prova).
        ⛔ COSA NON ESAMINA (D18 punto 3): che il rifiuto stia PRIMA della chiamata al
        server — quello lo vede il giro col browser, non una lettura del sorgente.
        """
        t = _testo("host.html")
        ids = sorted(set(self.RE_CASELLE.findall(t)))
        self.assertGreaterEqual(
            len(ids), 3,
            "misura non valida: ho letto %d caselle di prezzo nel pannello" % len(ids))
        senza_rifiuto = [
            nome for nome in ids
            if not re.search(
                r"if\(!document\.getElementById\('%s'\)\.value\.trim\(\)\)" % re.escape(nome), t)]
        self.assertEqual(
            senza_rifiuto, [],
            "queste caselle di prezzo non rifiutano il vuoto, e un vuoto vale ZERO: %s "
            "(lette %d caselle dal pannello)" % (", ".join(senza_rifiuto), len(ids)))


class TestUnEtichettaDiStatoNonNominaUnaCAUSASOLA(unittest.TestCase):
    """⛔ D20 — scritta PRIMA della riparazione e vista ROSSA sul codice di produzione.

    FAMIGLIA «testi che mentono» (modo di rompersi n. 3): lo stato `trattenuto` del payout lo
    scrivono TRE punti del prodotto — prenotazione cancellata, controversia aperta, subentro
    (`fase83_server.py`) — ma il pannello lo chiama «Trattenuto (cancellata)», in tutte e 8
    le lingue. Il 2026-09-15 il fondatore ha letto quella riga su un rimborso pieno e ha
    chiesto perche' gli «trattenessero» dei soldi che nessuno stava tenendo.

    La guardia lega il TESTO al CODICE: conta i punti che scrivono lo stato e, se sono piu'
    di uno, pretende che l'etichetta non nomini una causa sola — in ogni lingua.
    ⛔ COSA NON ESAMINA (D18 punto 3): la CIFRA mostrata (e' giusta: e' la quota dell'host,
    prezzo meno tariffa tecnica) e le altre tre etichette di stato.
    """

    # lingua -> (parola che nomina la CANCELLAZIONE, parola che nomina la CONTROVERSIA)
    PAROLE = {
        "it": ("cancella", "controversia"), "en": ("cancel", "dispute"),
        "es": ("cancela", "disputa"), "fr": ("annul", "litige"),
        "de": ("storn", "streit"), "pt": ("cancela", "disputa"),
        "ja": ("キャンセル", "異議"), "zh": ("取消", "争议"),
    }

    def test_l_etichetta_del_trattenuto_non_dice_solo_cancellata(self):
        import fase83_server
        with open(fase83_server.__file__, encoding="utf-8") as f:
            sorgente = f.read()
        cause = len(re.findall(r"aggiorna_stato\([^)]*\"trattenuto\"\)", sorgente))
        # PREMESSA (sbaglio S1): se un solo punto scrivesse quello stato, nominarlo NON
        # sarebbe una bugia e questa guardia non starebbe misurando niente.
        self.assertGreater(
            cause, 1,
            "misura non valida: i punti che scrivono lo stato «trattenuto» sono %d. Se e' "
            "tornato a uno solo, questa guardia va riscritta con il motivo" % cause)
        t = _testo("host.html")
        bugiarde = []
        for riga in t.splitlines():
            testa = riga.strip()[:4]
            for lingua, (cancellazione, controversia) in self.PAROLE.items():
                if not testa.startswith(lingua + ":{"):
                    continue
                m = re.search(r"st_trat:\"([^\"]*)\"", riga)
                if not m:
                    continue
                etichetta = m.group(1)
                if (cancellazione in etichetta.lower()
                        and controversia not in etichetta.lower()):
                    bugiarde.append("%s=%s" % (lingua, etichetta))
        self.assertEqual(
            len(bugiarde), 0,
            "lo stato «trattenuto» lo scrivono %d cause diverse, e queste etichette ne "
            "nominano UNA sola: %s" % (cause, " · ".join(bugiarde)))

    def test_la_legenda_degli_incassi_SPIEGA_anche_lo_stato_fermo(self):
        """La legenda elenca gli altri tre stati e salta proprio quello che ha fatto
        chiedere «perche'?» al fondatore. Chi legge deve trovarci la riga che spiega."""
        t = _testo("host.html")
        senza = []
        for riga in t.splitlines():
            for lingua in ("it", "en"):
                if not riga.strip()[:4].startswith(lingua + ":{"):
                    continue
                mp = re.search(r"pay_p:\"([^\"]*)\"", riga)
                ms = re.search(r"st_trat:\"([^\"]*)\"", riga)
                if not (mp and ms):
                    continue
                # la legenda deve nominare lo stato con la SUA etichetta, non a parole mie
                primo = ms.group(1).split("(")[0].strip()
                if primo and primo.lower() not in mp.group(1).lower():
                    senza.append("%s (manca «%s»)" % (lingua, primo))
        self.assertEqual(
            senza, [],
            "la legenda degli incassi non spiega lo stato dei soldi fermi: %s"
            % " · ".join(senza))


if __name__ == "__main__":
    unittest.main(verbosity=2)
