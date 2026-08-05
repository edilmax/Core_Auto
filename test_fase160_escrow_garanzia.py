"""Test ESCROW DI GARANZIA (fase160): i soldi all'host solo se l'ospite conferma o passa la
finestra; contestazione blocca; risoluzione a conservazione esatta. + E2E book->garanzia->conferma."""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase160_escrow_garanzia import crea_escrow_garanzia

SEG = b"g" * 32
HK = {"X-Host-Key": "hk"}
AK = {"X-Admin-Key": "ak"}


class TestModulo(unittest.TestCase):
    def setUp(self):
        self.clock = {"t": 1000}
        self.g = crea_escrow_garanzia(":memory:", orologio=lambda: self.clock["t"])
        self.g.inizializza_schema()

    def test_conferma_rilascia_tutto_allhost(self):
        self.assertTrue(self.g.apri("P1", 8500, ora_checkin_ts=1000))
        out = self.g.conferma_ospite("P1")
        self.assertTrue(out["ok"]); self.assertEqual(out["stato"], "rilasciato")
        self.assertEqual(out["host_riceve_cents"], 8500)
        self.assertEqual(self.g.stato("P1")["host_riceve_cents"], 8500)

    def test_apri_idempotente_e_importo_zero(self):
        self.assertTrue(self.g.apri("P2", 5000, ora_checkin_ts=1000))
        self.assertTrue(self.g.apri("P2", 9999, ora_checkin_ts=1000))   # idempotente
        self.assertEqual(self.g.stato("P2")["importo_host_cents"], 5000)
        self.assertFalse(self.g.apri("P3", 0))                          # importo nullo -> no

    def test_contesta_blocca_e_risolvi_conserva(self):
        self.g.apri("P4", 10000, ora_checkin_ts=1000)
        self.assertEqual(self.g.contesta("P4", "manca il wifi dichiarato")["stato"], "contestato")
        # auto-rilascio NON tocca una contestata anche se la finestra e' passata
        self.clock["t"] = 10**9
        self.assertEqual(self.g.auto_rilascia(), 0)
        r = self.g.risolvi("P4", rimborso_ospite_cents=4000)
        self.assertTrue(r["ok"])
        st = self.g.stato("P4")
        self.assertEqual(st["ospite_rimborso_cents"], 4000)
        self.assertEqual(st["host_riceve_cents"], 6000)
        self.assertEqual(st["host_riceve_cents"] + st["ospite_rimborso_cents"], 10000)  # conservazione

    def test_risolvi_clampa_rimborso_oltre_importo(self):
        # GUARDIA (dal mutation testing ⑨): un rimborso richiesto SUPERIORE all'escrow
        # (chiamata diretta a risolvi, bypassando il clamp 0-100% della UI admin) NON
        # deve mai far andare l'host in NEGATIVO. Il min() interno lo blocca a 'imp'.
        self.g.apri("P9", 10000, ora_checkin_ts=1000)
        self.g.contesta("P9", "problema grave")
        r = self.g.risolvi("P9", rimborso_ospite_cents=999999)   # >> importo
        self.assertTrue(r["ok"])
        st = self.g.stato("P9")
        self.assertEqual(st["ospite_rimborso_cents"], 10000)     # clampato all'escrow
        self.assertEqual(st["host_riceve_cents"], 0)             # MAI negativo
        self.assertEqual(st["host_riceve_cents"] + st["ospite_rimborso_cents"], 10000)

    def test_auto_rilascio_dopo_finestra(self):
        self.g.apri("P5", 7000, ora_checkin_ts=1000, finestra_ore=24)
        self.clock["t"] = 1000 + 25 * 3600
        self.assertEqual(self.g.auto_rilascia(), 1)
        self.assertEqual(self.g.stato("P5")["stato"], "rilasciato")

    def test_conferma_solo_da_in_garanzia(self):
        self.g.apri("P6", 5000, ora_checkin_ts=1000)
        self.g.conferma_ospite("P6")
        self.assertFalse(self.g.conferma_ospite("P6")["ok"])           # gia' rilasciata

    def test_annulla_blocca_auto_rilascio(self):
        # prenotazione cancellata SENZA penale -> garanzia annullata -> MAI payout (no auto-rilascio)
        self.g.apri("P7", 5000, ora_checkin_ts=1000)
        self.assertEqual(self.g.annulla("P7")["stato"], "annullato")
        self.clock["t"] = 10 ** 9
        self.assertEqual(self.g.auto_rilascia(), 0)

    def test_chiudi_proporzionale_host_tiene_penale(self):
        # cancellazione CON penale: l'host tiene la sua quota, il resto torna all'ospite (conservazione)
        self.g.apri("P8", 10000, ora_checkin_ts=1000)
        self.assertTrue(self.g.chiudi_proporzionale("P8", 8500)["ok"])
        st = self.g.stato("P8")
        self.assertEqual(st["stato"], "risolto")
        self.assertEqual(st["host_riceve_cents"], 8500)
        self.assertEqual(st["ospite_rimborso_cents"], 1500)
        self.assertEqual(st["host_riceve_cents"] + st["ospite_rimborso_cents"], 10000)
        self.clock["t"] = 10 ** 9
        self.assertEqual(self.g.auto_rilascia(), 0)               # risolta -> mai auto-rilascio


class TestE2E(unittest.TestCase):
    def test_book_apre_garanzia_e_ospite_conferma(self):
        d = tempfile.mkdtemp(); self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db",
            db_domanda=f"{d}/dom.db", db_garanzia=f"{d}/g.db", file_referral=f"{d}/ref.json",
            commissione_bps=1500))
        r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")
        def g(m, p, b=None, h=None, q=None):
            return r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})
        g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "casa", "titolo": "Casa",
          "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
          "servizi": [], "immagini": []}, HK)
        g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa", "da": "2026-11-01",
          "a": "2026-11-30", "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)
        _, q = g("POST", "/api/concierge/quote", {"alloggio_id": "casa", "check_in": "2026-11-10",
                 "check_out": "2026-11-12", "party": 1})
        _, b = g("POST", "/api/concierge/book", {"quote_token": q["quote_token"], "email": "o@x.it"})
        ref = b["riferimento"]
        # garanzia aperta col netto host (20000 - 15% = 17000)
        s, st = g("GET", "/api/garanzia/stato", q={"ref": ref}, h=AK)
        self.assertEqual(s, 200)
        self.assertEqual(st["stato"], "in_garanzia")
        self.assertEqual(st["importo_host_cents"], 17000)
        # l'ospite conferma "tutto ok" col voucher -> rilasciato all'host
        s, c = g("POST", "/api/garanzia/conferma", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200); self.assertEqual(c["stato"], "rilasciato")
        # contestazione su una gia' rilasciata -> rifiutata
        s2, _ = g("POST", "/api/garanzia/contesta", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s2, 409)


class TestCassaforteNonApertaDeveGRIDARE(unittest.TestCase):
    """SE LA CASSAFORTE NON SI APRE, NON PUO' RESTARE UN SUSSURRO.

    `_apri_garanzia` protegge i soldi dell'ospite: trattiene l'importo dell'host finche' non
    passa la finestra di contestazione. Se `garanzia.apri()` fallisce (archivio bloccato,
    disco pieno) l'errore era ingoiato con un semplice `logger.warning` e la prenotazione
    proseguiva CONFERMATA: l'ospite crede di essere protetto e non lo e'.

    E nessuno se ne accorgeva. Il Guardiano cerca escrow BLOCCATI o SU RIMBORSATA, non
    prenotazioni SENZA escrow -- quel controllo non esiste (registrato come candidato: va
    costruito quando ci saranno prenotazioni vere su cui validarlo, altrimenti rischia falsi
    allarmi sulle 'paga in struttura', che la cassaforte la saltano di proposito).

    Il livello ERROR non e' cosmetico: dal 2026-07-30 il Guardiano LEGGE il registro ogni
    giorno e manda un'email sugli ERROR delle ultime 24h (mai sui warning, che sono 131 e
    includono cose innocue). Alzare il livello e' cio' che trasforma questo guasto da
    invisibile-per-sempre a visibile-entro-un-giorno.

    VISTO ROSSO: col vecchio `logger.warning` questa guardia fallisce.
    """

    def test_il_fallimento_dell_apertura_e_registrato_come_ERRORE(self):
        d = tempfile.mkdtemp(); self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_garanzia=f"{d}/g.db", commissione_bps=1500))
        r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")

        class _CassaforteRotta:
            def apri(self, *a, **k):
                raise RuntimeError("archivio garanzia guasto")
        sis.garanzia = _CassaforteRotta()

        with self.assertLogs("core_auto", level="ERROR") as reg:
            r._apri_garanzia("rif-x", 17000, "casa", "2026-11-10")
        unito = " ".join(reg.output).lower()
        self.assertIn("garanzia", unito,
                      "il messaggio non dice che e' la CASSAFORTE a non essersi aperta: %r"
                      % (reg.output,))

    def test_quando_si_apre_NON_scrive_errori(self):
        """Prova di rimozione: sul percorso sano nessun ERROR, o l'email del Guardiano
        diventerebbe rumore quotidiano (regola 10: un falso allarme e' un difetto)."""
        import logging
        d = tempfile.mkdtemp(); self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_garanzia=f"{d}/g.db", commissione_bps=1500))
        r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")
        reg = logging.getLogger("core_auto")
        catturati = []

        class _Spia(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.ERROR:
                    catturati.append(record.getMessage())
        h = _Spia(); reg.addHandler(h); self.addCleanup(lambda: reg.removeHandler(h))
        r._apri_garanzia("rif-ok", 17000, "casa", "2026-11-10")
        self.assertEqual(catturati, [], "grida su un'apertura riuscita: %r" % (catturati,))
        self.assertEqual((sis.garanzia.stato("rif-ok") or {}).get("stato"), "in_garanzia",
                         "setup: la cassaforte doveva aprirsi davvero")


class TestBuchiDiMutazione(unittest.TestCase):
    """LE 20 GUARDIE NATE DALLA MUTAZIONE DEL 2026-08-04.

    Misura di partenza su `fase160_escrow_garanzia.py`: 35 punti esaminati, **15 uccisi e
    20 SOPRAVVISSUTI** con tutti e 13 i sorveglianti — copertura reale 43%. Non voleva dire
    che il modulo fosse rotto: i test erano verdi e il codice fa il suo lavoro. Voleva dire
    che se una di quelle 20 righe cambiasse — per errore, per una riscrittura o per un
    mutante lasciato dentro — **la suite resterebbe verde e nessuno se ne accorgerebbe**. In
    un modulo che decide CHI PRENDE QUANTO fra piattaforma, host e ospite, un interruttore
    invertito e' denaro che finisce alla persona sbagliata.

    LA CONTABILITA' ESATTA, perche' 20 guardie per 20 sopravvissuti non torna da sola:
      · 19 sopravvissuti hanno avuto ognuno la SUA guardia, vista rossa sul suo mutante;
      ·  1 sopravvissuto (riga 43, `_cent`, `>=` -> `>`) resta APERTO e dichiarato: la
         dimostrazione di equivalenza che avevo scritto e' stata REFUTATA da una revisione
         a contesto fresco (basta una sottoclasse di `int` che valga 0 per distinguerli), e
         un sopravvissuto aperto vale piu' di una cecita' dichiarata;
      ·  1 guardia in piu' (`test_riga247`) non nasce da un mutante: copre un punto che il
         generatore NON SA rompere (confronto a catena), e il guasto e' stato iniettato a
         mano per vederla rossa.
      Fa 19 + 1 = 20 prove nuove, con 34 uccisi su 35 e 1 sopravvissuto dichiarato.

    ⚠️ IL DENOMINATORE VERO E' 43, NON 35. Oltre ai 35 punti mutati, lo strumento rinuncia
    su 4 punti e lo DICHIARA (3 confronti a catena, 1 operatore a cavallo di due righe) e
    ne salta altri 4 IN SILENZIO — `is`, `is not`, `not in` non sono nel suo elenco di
    confronti (`collaudi/mutazione_prodotto.py:445`) e non incrementano nessun contatore di
    rinuncia. Fra quei 4 muti c'e' la riga 126, `r["stato"] not in attesi`: **il cancello che
    decide se una transizione che muove denaro e' permessa**. Non e' scoperto (invertirlo fa
    fallire `test_conferma_rilascia_tutto_allhost`), ma nessuno l'ha mai messo alla prova.

    ⚠️ Il numero si legge SOLO con tutti e 13 i sorveglianti (compreso `test_happy_soldi`,
    che esercita l'escrow senza nominare il modulo, quindi lo strumento non lo vede da
    solo). Con 5 killer i sopravvissuti risultavano 23: tre erano FALSI, morti appena
    entrati gli altri occhi.

    Ogni guardia qui sotto e' stata VISTA ROSSA sul suo mutante prima di essere contata
    buona, e dichiara nel nome la riga che sorveglia.
    """

    def setUp(self):
        self.clock = {"t": 1000}
        self.g = crea_escrow_garanzia(":memory:", orologio=lambda: self.clock["t"])
        self.g.inizializza_schema()

    def _sentinella(self):
        """Una garanzia VERA, aperta accanto, che l'operazione rifiutata non deve toccare.

        Senza di lei una guardia sul rifiuto controlla solo l'ESITO: «non ha cambiato
        niente» sarebbe vero per costruzione, perche' l'archivio e' vuoto. Con lei si
        controlla anche l'EFFETTO, che e' la meta' che conta davvero.
        """
        self.g.apri("SENT", 7777, alloggio_id="ALL-SENT", ora_checkin_ts=1000)
        return "SENT"

    def _sentinella_intatta(self, dove):
        st = self.g.stato("SENT")
        self.assertEqual(st["stato"], "in_garanzia", "%s ha toccato un'ALTRA garanzia" % dove)
        self.assertEqual(st["host_riceve_cents"], 0, "%s ha mosso denaro altrui" % dove)
        self.assertEqual(st["ospite_rimborso_cents"], 0, "%s ha mosso denaro altrui" % dove)

    def _su_file(self, stato, importo):
        """Costruisce a mano uno STATO IMPOSSIBILE: una garanzia con importo ZERO.

        `apri()` lo vieta (riga 85), quindi oggi non si raggiunge — ma la D19 vieta di
        dichiarare irraggiungibile un ramo difensivo per merito di un'ALTRA funzione: e' una
        conclusione con una premessa, e il giorno che la premessa cade la cecita' resta. Lo
        stato si costruisce adesso, che costa tre righe.
        """
        import os
        import sqlite3
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        p = os.path.join(d, "g.db")
        g = crea_escrow_garanzia(p, orologio=lambda: self.clock["t"])
        g.inizializza_schema()
        con = sqlite3.connect(p)
        with con:
            con.execute("INSERT INTO garanzia (prenotazione_id, alloggio_id, "
                        "importo_host_cents, stato, sblocco_auto_ts, aperto_ts, "
                        "aggiornato_ts) VALUES ('Z0','',?,?,?,1000,1000)",
                        (importo, stato, 10 ** 12))
        con.close()
        return g

    # ── I CINQUE RIFIUTI DI UN ID NON VALIDO (righe 140 · 147 · 153 · 160 · 172) ──────────
    # Mutante: `False` -> `True` nel dizionario di rifiuto. La chiamata verrebbe dichiarata
    # RIUSCITA pur non avendo fatto niente: chi la usa crede che i soldi si siano mossi.

    def test_riga140_conferma_ospite_rifiuta_id_non_stringa(self):
        self._sentinella()
        out = self.g.conferma_ospite(12345)
        self.assertIs(out["ok"], False, "una conferma con id non valido si dichiara RIUSCITA")
        self.assertEqual(out["motivo"], "id_non_valido")
        self._sentinella_intatta("conferma_ospite con id non valido")

    def test_riga147_contesta_rifiuta_id_non_stringa(self):
        self._sentinella()
        out = self.g.contesta(None, "motivo qualsiasi")
        self.assertIs(out["ok"], False, "una contestazione con id non valido risulta riuscita")
        self.assertEqual(out["motivo"], "id_non_valido")
        self._sentinella_intatta("contesta con id non valido")

    def test_riga153_annulla_rifiuta_id_non_stringa(self):
        self._sentinella()
        out = self.g.annulla(3.14)
        self.assertIs(out["ok"], False, "un annullamento con id non valido risulta riuscito")
        self.assertEqual(out["motivo"], "id_non_valido")
        self._sentinella_intatta("annulla con id non valido")

    def test_riga160_chiudi_proporzionale_rifiuta_id_non_stringa(self):
        self._sentinella()
        out = self.g.chiudi_proporzionale(["P1"], 500)
        self.assertIs(out["ok"], False, "una divisione con id non valido risulta riuscita")
        self.assertEqual(out["motivo"], "id_non_valido")
        self._sentinella_intatta("chiudi_proporzionale con id non valido")

    def test_riga172_risolvi_rifiuta_id_non_stringa(self):
        self._sentinella()
        out = self.g.risolvi(b"P1", rimborso_ospite_cents=500)
        self.assertIs(out["ok"], False, "una risoluzione con id non valido risulta riuscita")
        self.assertEqual(out["motivo"], "id_non_valido")
        self._sentinella_intatta("risolvi con id non valido")

    # ── I DUE CONFINI SU IMPORTO ZERO (righe 162 · 174) ───────────────────────────────────
    # Mutante: `imp <= 0` -> `imp < 0`. Con importo ZERO la funzione non si ferma piu' e
    # CHIUDE la garanzia dichiarandola risolta: una pratica si chiude senza che un centesimo
    # sia stato assegnato a nessuno, e lo stato 'in_garanzia' sparisce per sempre.

    # ⚠️ Queste due NON inchiodano il testo del motivo, di proposito. Oggi il modulo risponde
    # `non_trovata` anche per una riga che ESISTE e vale zero: e' un osservabile debole (due
    # situazioni con rimedi opposti fuse in una stringa sola, regola 9). Se un giorno qualcuno
    # la separasse in `importo_nullo`, sarebbe un MIGLIORAMENTO — e una guardia che diventa
    # rossa su un miglioramento e' una guardia che frena il progetto invece di proteggerlo.
    # Cio' che conta, e che qui e' preteso, e' che l'operazione sia RIFIUTATA e che lo stato
    # non si muova: e' quello che uccide il mutante.

    def test_riga162_chiudi_proporzionale_non_chiude_una_garanzia_da_zero(self):
        g = self._su_file("in_garanzia", 0)
        out = g.chiudi_proporzionale("Z0", 0)
        self.assertIs(out["ok"], False, "ha CHIUSO una garanzia da zero euro")
        self.assertEqual(g.stato("Z0")["stato"], "in_garanzia",
                         "lo stato e' stato cambiato lo stesso: la pratica e' andata persa")
        self.assertEqual(g.stato("Z0")["host_riceve_cents"], 0)

    def test_riga174_risolvi_non_chiude_una_garanzia_da_zero(self):
        g = self._su_file("contestato", 0)
        out = g.risolvi("Z0", rimborso_ospite_cents=0)
        self.assertIs(out["ok"], False, "ha RISOLTO una contestazione da zero euro")
        self.assertEqual(g.stato("Z0")["stato"], "contestato",
                         "la contestazione e' stata chiusa senza assegnare nulla a nessuno")
        self.assertEqual(g.stato("Z0")["ospite_rimborso_cents"], 0)

    # ── I TRE «NON TROVATA» (righe 125 · 163 · 175) ───────────────────────────────────────
    # Mutante: `False` -> `True`. Un'operazione su una garanzia INESISTENTE torna «riuscita»:
    # il chiamante prosegue convinto che i soldi siano stati sistemati.

    def test_riga125_conferma_su_garanzia_inesistente_non_e_riuscita(self):
        self._sentinella()
        out = self.g.conferma_ospite("mai-esistita")
        self.assertIs(out["ok"], False, "conferma su una garanzia che non esiste: riuscita")
        self.assertEqual(out["motivo"], "non_trovata")
        self._sentinella_intatta("conferma su garanzia inesistente")

    def test_riga163_chiudi_proporzionale_su_inesistente_non_e_riuscita(self):
        self._sentinella()
        out = self.g.chiudi_proporzionale("mai-esistita", 100)
        self.assertIs(out["ok"], False, "divisione su una garanzia che non esiste: riuscita")
        self.assertEqual(out["motivo"], "non_trovata")
        self._sentinella_intatta("divisione su garanzia inesistente")

    def test_riga175_risolvi_su_inesistente_non_e_riuscita(self):
        self._sentinella()
        out = self.g.risolvi("mai-esistita", rimborso_ospite_cents=100)
        self.assertIs(out["ok"], False, "risoluzione su una garanzia che non esiste: riuscita")
        self.assertEqual(out["motivo"], "non_trovata")
        self._sentinella_intatta("risoluzione su garanzia inesistente")

    # ── L'APERTURA DELLA GARANZIA (righe 82 · 83 · 99) ────────────────────────────────────

    def test_riga82_83_apri_rifiuta_id_vuoto_e_non_crea_nulla(self):
        # Mutante: `and` -> `or` nel controllo dell'id, e il `return False` che ne segue.
        # Con `or` un id VUOTO passa: nasce una garanzia che nessuno potra' piu' nominare,
        # e i soldi dell'host restano appesi a una riga irraggiungibile.
        self.assertIs(self.g.apri("", 5000, ora_checkin_ts=1000), False)
        self.assertEqual(self.g.aperte(), [], "ha creato una garanzia con id VUOTO")
        self.assertIsNone(self.g.stato(""))

    def test_riga82_apri_rifiuta_id_di_tipo_sbagliato(self):
        # Stesso punto, input DIVERSO (appendice, regola 9: una correzione non si accetta
        # sul solo caso che l'ha fatta nascere).
        self.assertIs(self.g.apri(12345, 5000, ora_checkin_ts=1000), False)
        self.assertEqual(self.g.aperte(), [], "ha creato una garanzia con id numerico")

    def test_riga99_apri_conserva_l_alloggio(self):
        # Mutante: `alloggio_id or ""` -> `alloggio_id and ""`, che azzera SEMPRE l'alloggio.
        # Senza alloggio, `aperte_per_alloggio` non vede piu' niente: si potrebbe cancellare
        # un alloggio che custodisce ancora i soldi di un ospite (riga orfana).
        self.assertTrue(self.g.apri("PA", 5000, alloggio_id="A1", ora_checkin_ts=1000))
        self.assertEqual(self.g.aperte_per_alloggio("A1"), 1,
                         "l'alloggio e' sparito dalla riga: la garanzia diventa orfana")
        self.assertEqual(self.g.aperte()[0]["alloggio_id"], "A1")

    # ── I TETTI E LE VALIDAZIONI DELLE LISTE (righe 246 · 270 · 288 · 291 · 311) ──────────
    # Mutante: `and` -> `or` nelle catene di validazione. Un valore assurdo smette di essere
    # scartato e diventa il tetto vero: la lista si accorcia in silenzio, e chi la legge
    # (pannello admin, Guardiano) crede di vedere tutto.

    def test_riga246_contestate_scarta_un_limite_assurdo(self):
        for rif in ("C1", "C2"):
            self.g.apri(rif, 5000, ora_checkin_ts=1000)
            self.g.contesta(rif, "non conforme")
        self.assertEqual(len(self.g.contestate(limit=True)), 2,
                         "un limite booleano e' stato preso per buono: controversie NASCOSTE "
                         "al pannello admin")

    def test_riga247_contestate_scarta_un_limite_zero(self):
        # ⚠️ PUNTO CHE IL GENERATORE NON SA ROMPERE — rinuncia «catena»
        # (`mutazione_prodotto.py:441`: salta gli `ast.Compare` con piu' di un operatore).
        # `0 < limit <= 500` e' un confronto A CATENA: nessun mutante l'ha mai toccato, ne'
        # oggi ne' mai. Un punto che lo strumento non esamina non e' un punto sicuro: e' un
        # punto di cui NON SAPPIAMO NIENTE, e la guardia la scrive un essere umano o non la
        # scrive nessuno.
        # Se `0 <` diventasse `0 <=`, lo zero passerebbe come tetto valido: il pannello admin
        # mostrerebbe una lista VUOTA con le controversie aperte, i soldi fermi in garanzia e
        # nessun operatore che le vede. Provata a mano iniettando la modifica il 2026-08-04.
        for rif in ("D1", "D2"):
            self.g.apri(rif, 5000, ora_checkin_ts=1000)
            self.g.contesta(rif, "non conforme")
        self.assertEqual(len(self.g.contestate(limit=0)), 2,
                         "limite zero preso per buono: le controversie spariscono dal "
                         "pannello admin e nessuno decide piu' su quei soldi")

    def test_riga270_aperte_per_alloggio_scarta_un_id_vuoto(self):
        self.g.apri("PB", 5000, ora_checkin_ts=1000)          # alloggio_id vuoto per difetto
        self.assertEqual(self.g.aperte_per_alloggio(""), 0,
                         "un id vuoto conta le garanzie di TUTTI gli alloggi senza nome")

    def test_riga288_aperte_scadute_scarta_un_orario_booleano(self):
        self.g.apri("PC", 5000, ora_checkin_ts=1000, finestra_ore=24)
        self.clock["t"] = 10 ** 9
        self.assertEqual(len(self.g.aperte_scadute(ora_ts=True)), 1,
                         "un orario booleano e' stato usato come data: il Guardiano non vede "
                         "piu' le garanzie in ritardo e nessuno grida")

    def test_riga291_aperte_scadute_scarta_un_limite_zero(self):
        self.g.apri("PD", 5000, ora_checkin_ts=1000, finestra_ore=24)
        self.clock["t"] = 10 ** 9
        self.assertEqual(len(self.g.aperte_scadute(limit=0)), 1,
                         "limite zero preso per buono: elenco VUOTO e allarme spento")

    def test_riga311_aperte_scarta_un_limite_zero(self):
        self.g.apri("PE", 5000, ora_checkin_ts=1000)
        self.assertEqual(len(self.g.aperte(limit=0)), 1,
                         "limite zero preso per buono: il Guardiano non vede piu' nulla")

    # ── IL MODO :memory: (riga 348) ───────────────────────────────────────────────────────

    def test_riga348_memory_usabile_da_un_altro_filo(self):
        # Mutante: `check_same_thread=False` -> `True`. La connessione condivisa smette di
        # funzionare fuori dal filo che l'ha creata: il server, che lavora a fili, esplode
        # con ProgrammingError sul percorso dei soldi.
        import threading
        g = crea_escrow_garanzia(":memory:")
        g.inizializza_schema()
        esito = {}

        def _lavora():
            try:
                esito["ok"] = g.apri("T1", 5000, ora_checkin_ts=1000)
            except Exception as e:                      # noqa: BLE001 - serve il tipo esatto
                esito["errore"] = "%s: %s" % (type(e).__name__, e)

        t = threading.Thread(target=_lavora)
        t.start()
        t.join(30)
        self.assertNotIn("errore", esito,
                         "la garanzia in memoria non si usa da un altro filo: %s"
                         % esito.get("errore"))
        self.assertIs(esito.get("ok"), True)
        self.assertEqual(g.stato("T1")["stato"], "in_garanzia")


if __name__ == "__main__":
    unittest.main()
