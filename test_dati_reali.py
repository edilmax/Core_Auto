"""IL CODICE NUOVO LEGGE I DATI VECCHI — regressione sui DATI, non sullo schema.

IL BUCO CHE QUESTO FILE CHIUDE
------------------------------
`test_migrazioni_schema.py` prova che un database col formato di ieri viene MIGRATO senza
perdere nulla. Ma anche a schema perfetto resta un buco piu' sottile, e piu' frequente:

    tutti gli altri test partono da archivi VUOTI e li riempiono chiamando le funzioni di
    scrittura del prodotto. Il prodotto legge quindi sempre e solo cio' che il prodotto
    stesso ha appena scritto, oggi, con le validazioni di oggi.

In produzione vivono 24 archivi con righe nate mesi fa: coordinate mancanti, `origine`
NULL, `corpo_json` in tre formati diversi (moderno, legacy, arcaico), date invertite da
una riparazione manuale, prenotazioni che puntano a un annuncio cancellato, doppioni,
descrizioni da 8.000 caratteri, titoli con emoji e apostrofi tipografici, valute miste,
bit di servizi RITIRATI ancora accesi nelle bitmask. Nessuna di quelle forme nasce mai
dentro la suite — e infatti e' li' che il prodotto si e' rotto davvero (vedi sotto).

COSA VERIFICA
-------------
Il corpus vive in `collaudi/dati_realistici.py` ed e' scritto con `sqlite3` NUDO: **nessun
import da `fase*.py`**. E' la condizione che rende il collaudo utile — se il corpus lo
generassero le stesse funzioni che poi lo leggono, un difetto nel modello dei dati sarebbe
invisibile per costruzione. Anche la catena hash del libro giornale e le firme HMAC delle
accettazioni sono RICALCOLATE li' in modo indipendente, secondo il formato documentato.

Su quel corpus passano TUTTE le letture principali del prodotto — catalogo, ricerca,
dettaglio, mappa, calendario, disponibilita', pannello host (prenotazioni/payout/metriche/
export/accettazioni), pannello admin (prenotazioni/annunci/ricerca/controversie/verifiche),
libro giornale, DAC7, tassa di soggiorno, escrow, recensioni — e per ognuna si pretendono
i VALORI ESATTI calcolabili a mano, non un generico "non e' 500".

DIFETTI VERI TROVATI QUI (2026-07-29)
-------------------------------------
1) `RouterHTTP._arricchisci_metrica` (fase83) leggeva il pendente con
`rif = idem_key[:24]`, senza togliere il prefisso `reblock:` che il blocco assume dopo un
PAGAMENTO TARDIVO — prefisso che `_host_prenotazioni` invece toglie da sempre. Risultato:
una prenotazione REGOLARMENTE PAGATA valeva ZERO nei KPI del pannello host. Con questo
corpus il pannello dichiarava `revenue_cents=44750` invece di `69650`, e di conseguenza
ADR 2486 invece di 3869 e RevPAR 1491 invece di 2321. Non un dato mancante: un dato
SBAGLIATO, mostrato all'host come suo incasso. Corretto in fase83 (una riga, stesso
identico idioma gia' presente in `_host_prenotazioni`) e sorvegliato da
`TestSitoInteroSuDatiVeri.test_i_kpi_del_pannello_contano_anche_la_prenotazione_ri_bloccata`.

2) `RegistroDAC7` (fase100) leggeva il record dell'host COSI' COM'E' (`d.get(h) or {...}`)
e poi ne pretendeva le chiavi: un record scritto da una versione precedente (solo `pren`)
faceva uscire un **KeyError** da `stato()`, `visibile()` e `payout_consentito()`; un file
JSON valido ma che non e' un oggetto faceva uscire un **AttributeError**. Non un numero
mancante: un errore in faccia, su una lettura che decide se un annuncio resta visibile e
se un bonifico parte. Corretto in fase100 (record normalizzato campo per campo + `_leggi`
che accetta solo un oggetto) e sorvegliato da due controlli in `TestGiornaleEDac7`.

VISTO ROSSO (regola aurea: nessun verde vale finche' non e' stato visto rosso)
------------------------------------------------------------------------------
Il 2026-07-29 ogni famiglia di controlli e' stata provata rimettendo il guasto nel codice
di PRODUZIONE, una alla volta; dopo ogni prova il file e' stato ripristinato e lo sha256
confrontato prima/dopo (identico in tutti i tredici casi, `ripristino byte per byte`):

  - `fase57_vetrina.cerca`, sottoquery della miniatura: `ORDER BY i.ordine, i.id` ->
    `ORDER BY i.id`  =>  ROSSO su `test_la_miniatura_e_la_foto_con_ordine_piu_basso`
    (la copertina dell'annuncio cambia da sola su ogni archivio in cui l'ordine di
    inserimento non e' l'ordine scelto dall'host);
  - `fase57_vetrina.cerca`, `stato = 'pubblicato'` -> `stato != ''`  =>  ROSSO su 4
    controlli (sospesi e bozze in vetrina, annuncio a prezzo 0 in vendita);
  - `fase58_channel_manager.calendario`, tolto il ramo "VENDUTA vince su CHIUSA"  =>
    ROSSO su `test_il_calendario_dice_la_verita_su_ogni_giorno` (il giorno venduto E
    chiuso diventa 'chiuso': la prenotazione viva sparisce dalla vista dell'host);
  - `fase58_channel_manager._dove_lista`, tolto il `NOT` della vista 'attive'  =>
    ROSSO su 2 controlli (le rilasciate tornano fra le attive);
  - `fase131_payout_dashboard.riepilogo`, filtro per host neutralizzato  =>  ROSSO su 2
    controlli (un host vedeva gli incassi di TUTTA la piattaforma);
  - `fase147_tassa_comunale.totale_riscosso`, tolto `AND stornato=0`  =>  ROSSO su
    `test_la_tassa_di_soggiorno_esclude_gli_storni` (2250 -> 3450: si verserebbe al
    Comune una tassa gia' restituita all'ospite);
  - `fase160_escrow_garanzia.aperte_per_alloggio`, tolto lo stato 'contestato'  =>
    ROSSO (si potrebbe cancellare un annuncio che custodisce ancora i soldi di un ospite);
  - `fase162_pagamenti_pendenti.notti_per_alloggio`, tolto il salto delle righe con date
    impossibili  =>  ROSSO (notti negative nel report DAC7);
  - `fase163_accettazioni._firma`, il riferimento esterno esce dalla stringa firmata  =>
    ROSSO su `test_le_firme_archiviate_restano_verificabili` (la prova legale legata alla
    verifica d'identita' risulterebbe manomessa);
  - `fase177_financial_controller.aggrega_dac7`, `lordo = incasso - tassa` ->
    `lordo = incasso`  =>  ROSSO su `test_il_report_dac7_ricostruisce_l_anno_fiscale`
    (la tassa di soggiorno, pass-through al Comune, dichiarata al Fisco come
    corrispettivo dell'host: 44750 invece di 42500);
  - `fase83_server._arricchisci_metrica`, rimesso `rif = idem_key[:24]`  =>  ROSSO su
    `test_i_kpi_del_pannello_contano_anche_la_prenotazione_ri_bloccata` (difetto vero
    n.1 descritto sopra);
  - `fase100_dac7._rec`, rimesso il record letto grezzo, e `_leggi` senza il controllo
    che sia un oggetto  =>  ERRORE (KeyError / AttributeError) sui due controlli DAC7
    dei formati vecchi (difetto vero n.2 descritto sopra).

Due mutanti erano SOPRAVVISSUTI al primo giro — e questo e' il vero guadagno del
metodo: il corpus non conteneva ancora (a) un giorno VENDUTO **e** CHIUSO insieme, ne'
(b) uno storno di tassa vecchio, segnato col solo flag e con l'importo rimasto scritto.
Sono stati aggiunti al corpus; adesso i due guasti si vedono.

La prova e' anche automatizzata e PERMANENTE in `TestIlControlloSaFallire`, che sporca il
corpus (un centesimo cambiato, una riga sparita, un anello di catena rotto, una firma
manomessa) e pretende che i controlli la boccino, con la controprova sul caso sano.
"""
import datetime
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
if QUI not in sys.path:
    sys.path.insert(0, QUI)

from collaudi import dati_realistici as C     # noqa: E402


# ---------------------------------------------------------------------------
# Il corpus si costruisce UNA volta (l'hash della password host e' PBKDF2 a
# 200.000 giri: rifarlo per ogni classe sarebbe tempo buttato) e ogni classe ne
# riceve una COPIA fresca, cosi' nessuna prova puo' sporcare le altre.
# ---------------------------------------------------------------------------
_MASTER = {"dir": None}


def _corpus(test):
    if _MASTER["dir"] is None:
        base = tempfile.mkdtemp(prefix="dati_reali_master_")
        C.costruisci_corpus(base)
        _MASTER["dir"] = base
    dest = tempfile.mkdtemp(prefix="dati_reali_")
    test.addCleanup(shutil.rmtree, dest, True)
    for nome in os.listdir(_MASTER["dir"]):
        shutil.copy2(os.path.join(_MASTER["dir"], nome), os.path.join(dest, nome))
    p = lambda n: os.path.join(dest, n)      # noqa: E731
    return {"dir": dest, "catalogo": p("catalogo.db"), "inventario": p("inventario.db"),
            "registro_host": p("registro_host.db"), "pendenti": p("pendenti.db"),
            "payout": p("payout.db"), "tassa": p("tassa.db"),
            "garanzia": p("garanzia.db"), "accettazioni": p("accettazioni.db"),
            "finanza": p("finanza.db"), "recensioni": p("recensioni.db"),
            "dac7": p("dac7.json")}


def _etichetta_attesa(check_in, check_out):
    """La regola documentata in `_host_prenotazioni` per una prenotazione VIVA, riscritta
    qui: cosi' l'attesa non invecchia col calendario (fra un anno 'futura' sara' 'confermata'
    e il controllo deve continuare a valere, senza diventare vago)."""
    oggi = datetime.date.today().isoformat()
    if check_in > oggi:
        return "futura"
    if check_in <= oggi < check_out:
        return "attiva"
    return "confermata"


# ═══════════════════════════════════════════════════════════════════════════
# 1. CATALOGO / RICERCA / DETTAGLIO
# ═══════════════════════════════════════════════════════════════════════════
class TestCatalogoLeggeDatiVecchi(unittest.TestCase):

    def setUp(self):
        from fase57_vetrina import crea_catalogo
        from fase58_channel_manager import crea_channel_manager
        self.f = _corpus(self)
        self.inv = crea_channel_manager(self.f["inventario"])
        self.cat = crea_catalogo(self.f["catalogo"], disponibilita=self.inv.disponibile)

    def test_la_ricerca_pubblica_mostra_solo_i_pubblicati(self):
        from fase57_vetrina import CriteriRicerca
        res = self.cat.cerca(CriteriRicerca(citta="roma"))
        self.assertEqual(res["totale"], 3,
                         "sospeso e bozza non devono comparire nella vetrina pubblica")
        self.assertEqual([r["slug"] for r in res["risultati"]],
                         [C.SLUG_ORFANO, C.SLUG_SENZA_GEO, C.SLUG_ROMA])
        tutti = self.cat.cerca(CriteriRicerca(limit=100))
        self.assertEqual(tutti["totale"], 6)
        self.assertNotIn(C.SLUG_SOSPESO, [r["slug"] for r in tutti["risultati"]])
        self.assertNotIn(C.SLUG_BOZZA, [r["slug"] for r in tutti["risultati"]])

    def test_la_scheda_con_accenti_emoji_e_apostrofi_esce_intatta(self):
        d = self.cat.dettaglio(C.SLUG_ROMA)
        self.assertEqual(d["titolo"], C.TITOLO_ROMA)
        self.assertIn("’", d["titolo"], "l'apostrofo tipografico e' andato perso")
        self.assertIn("\U0001f3db", d["titolo"], "l'emoji e' andata persa")
        self.assertEqual(d["descrizione"],
                         "Terrazza vista cupole, due camere, l’ascensore c’è. "
                         "☕ \U0001f6cb️")
        jp = self.cat.dettaglio(C.SLUG_TOKYO)
        self.assertEqual(jp["titolo"], "新宿のワンルーム")

    def test_un_bit_di_servizio_ritirato_viene_ignorato_non_esplode(self):
        """La bitmask porta un bit (1<<20) di un servizio tolto dal registro: e' cio' che
        resta negli archivi veri quando si dismette un servizio."""
        d = self.cat.dettaglio(C.SLUG_ROMA)
        self.assertEqual(d["servizi"], ["wifi", "piscina"])
        self.assertEqual(C.MASK_ATTICO & (1 << 20), 1 << 20,
                         "il caso di prova non contiene piu' il bit sconosciuto")

    def test_l_annuncio_senza_coordinate_non_rompe_ricerca_ne_dettaglio(self):
        from fase57_vetrina import CriteriRicerca
        d = self.cat.dettaglio(C.SLUG_SENZA_GEO)
        self.assertIsNone(d["lat_micro"])
        self.assertIsNone(d["lon_micro"])
        self.assertEqual(d["prezzo_notte_cents"], 7900)
        card = [r for r in self.cat.cerca(CriteriRicerca(citta="roma"))["risultati"]
                if r["slug"] == C.SLUG_SENZA_GEO][0]
        self.assertIsNone(card["lat_micro"])
        self.assertIsNone(card["thumbnail"], "nessuna foto -> miniatura assente, non errore")
        # il filtro geografico deve semplicemente NON pescarlo
        con_bbox = self.cat.cerca(CriteriRicerca(
            bbox=(41000000, 42000000, 12000000, 13000000)))
        self.assertNotIn(C.SLUG_SENZA_GEO, [r["slug"] for r in con_bbox["risultati"]])
        self.assertIn(C.SLUG_ROMA, [r["slug"] for r in con_bbox["risultati"]])

    def test_la_miniatura_e_la_foto_con_ordine_piu_basso(self):
        """Le due foto sono state inserite in ordine INVERSO rispetto all'ordine scelto
        dall'host: la copertina deve seguire `ordine`, non l'id di inserimento."""
        from fase57_vetrina import CriteriRicerca
        card = [r for r in self.cat.cerca(CriteriRicerca(citta="roma"))["risultati"]
                if r["slug"] == C.SLUG_ROMA][0]
        self.assertEqual(card["thumbnail"], "/uploads/attico_salotto.jpg")
        d = self.cat.dettaglio(C.SLUG_ROMA)
        self.assertEqual([i["url"] for i in d["immagini"]],
                         ["/uploads/attico_salotto.jpg", "/uploads/attico_terrazza.jpg"])
        self.assertEqual(d["immagini"][0]["alt"], "", "alt vuoto e' legittimo, non None")

    def test_la_foto_orfana_non_finisce_su_nessun_annuncio(self):
        """Una riga immagine che punta a un annuncio cancellato resta nell'archivio: non
        deve comparire da nessuna parte ne' far saltare la lettura."""
        from fase57_vetrina import CriteriRicerca
        viste = []
        for r in self.cat.cerca(CriteriRicerca(limit=100))["risultati"]:
            viste.append(r["thumbnail"])
            d = self.cat.dettaglio(r["slug"])
            viste.extend(i["url"] for i in d["immagini"])
        self.assertNotIn("/uploads/fantasma.jpg", viste)
        con = sqlite3.connect(self.f["catalogo"])
        try:
            resta = con.execute("SELECT COUNT(*) FROM alloggio_immagini "
                                "WHERE alloggio_id=999").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(resta, 1, "la riga orfana dev'essere ancora li': non si cancella nulla")

    def test_la_descrizione_lunghissima_arriva_tutta(self):
        d = self.cat.dettaglio(C.SLUG_LONDRA)
        self.assertEqual(len(d["descrizione"]), 8000)
        self.assertEqual(d["descrizione"], C.DESCRIZIONE_LUNGA)
        self.assertEqual(d["valuta"], "GBP")
        self.assertEqual(d["lon_micro"], -83000, "longitudine NEGATIVA (a ovest di Greenwich)")

    def test_l_annuncio_dell_host_cancellato_si_legge_ancora(self):
        """Riga ORFANA: l'annuncio esiste, il suo host non e' piu' attivo. Il prodotto
        deve degradare con garbo (scheda leggibile, prezzo giusto), mai esplodere."""
        d = self.cat.dettaglio(C.SLUG_ORFANO)
        self.assertEqual(d["prezzo_notte_cents"], 12000)
        self.assertEqual(self.cat.host_di_alloggio(C.SLUG_ORFANO), C.HOST_CANCELLATO)
        self.assertEqual(self.cat.alloggi_host(C.HOST_CANCELLATO)[0]["slug"], C.SLUG_ORFANO)

    def test_prezzo_zero_e_bozza_restano_fuori_dalla_vetrina_ma_visibili_all_host(self):
        from fase57_vetrina import CriteriRicerca
        self.assertIsNone(self.cat.dettaglio(C.SLUG_BOZZA))
        self.assertEqual(
            [a["slug"] for a in self.cat.alloggi_host(C.HOST_ROMA)],
            [C.SLUG_ROMA, C.SLUG_SOSPESO, C.SLUG_BOZZA, C.SLUG_SENZA_GEO])
        bozza = [a for a in self.cat.alloggi_host(C.HOST_ROMA)
                 if a["slug"] == C.SLUG_BOZZA][0]
        self.assertEqual(bozza["prezzo_notte_cents"], 0)
        self.assertEqual(bozza["stato"], "bozza")
        prezzi = [r["prezzo_notte_cents"]
                  for r in self.cat.cerca(CriteriRicerca(limit=100))["risultati"]]
        self.assertNotIn(0, prezzi, "un annuncio a prezzo 0 non deve finire in vetrina")

    def test_ordinamento_e_filtri_sui_dati_veri(self):
        from fase57_vetrina import CriteriRicerca
        asc = self.cat.cerca(CriteriRicerca(citta="roma", ordine="prezzo_asc"))
        self.assertEqual([r["prezzo_notte_cents"] for r in asc["risultati"]],
                         [7900, 12000, 18500])
        desc = self.cat.cerca(CriteriRicerca(citta="roma", ordine="prezzo_desc"))
        self.assertEqual([r["prezzo_notte_cents"] for r in desc["risultati"]],
                         [18500, 12000, 7900])
        cap = self.cat.cerca(CriteriRicerca(capacita_min=4))
        self.assertEqual([r["slug"] for r in cap["risultati"]], [C.SLUG_ROMA])
        wifi = self.cat.cerca(CriteriRicerca(servizi=("wifi", "piscina")))
        self.assertEqual([r["slug"] for r in wifi["risultati"]], [C.SLUG_ROMA])

    def test_il_fuso_mancante_viene_dedotto_all_apertura(self):
        """Tre annunci sono nati prima che la colonna `fuso` esistesse e l'hanno vuota.
        All'apertura il prodotto deve dedurla da citta'+paese: senza, check-in, pass
        della serratura, recensioni e cancellazione userebbero il fuso del SERVER."""
        from fase57_vetrina import crea_catalogo
        fresco = _corpus(self)                     # copia MAI aperta dal prodotto
        con = sqlite3.connect(fresco["catalogo"])
        try:
            prima = dict(con.execute("SELECT slug, fuso FROM alloggi").fetchall())
        finally:
            con.close()
        self.assertEqual(sorted(s for s, f in prima.items() if f == ""),
                         sorted([C.SLUG_BOZZA, C.SLUG_SENZA_GEO, C.SLUG_ORFANO]))
        crea_catalogo(fresco["catalogo"])          # e' l'apertura a ripararli
        con = sqlite3.connect(fresco["catalogo"])
        try:
            dopo = dict(con.execute("SELECT slug, fuso FROM alloggi").fetchall())
        finally:
            con.close()
        self.assertEqual(dopo[C.SLUG_SENZA_GEO], "Europe/Rome")
        self.assertEqual(dopo[C.SLUG_BOZZA], "Europe/Rome")
        self.assertEqual(dopo[C.SLUG_ORFANO], "Europe/Rome")
        self.assertEqual(dopo[C.SLUG_TOKYO], "Asia/Tokyo",
                         "un fuso gia' scritto non si tocca")
        self.assertEqual(dopo[C.SLUG_LONDRA], "Europe/London")
        self.assertEqual([s for s, f in dopo.items() if f == ""], [])

    def test_la_vista_admin_pagina_e_filtra_tutti_gli_stati(self):
        rep = self.cat.tutti_alloggi_pagina(limit=100)
        self.assertEqual(rep["totale"], 8, "l'admin vede TUTTI gli annunci, ogni stato")
        sosp = self.cat.tutti_alloggi_pagina(stato="sospeso", limit=100)
        self.assertEqual([a["slug"] for a in sosp["alloggi"]], [C.SLUG_SOSPESO])
        # la citta' e' salvata come l'ha scritta l'host ("Milano"): il filtro admin e'
        # senza distinzione di maiuscole, altrimenti non troverebbe mai nulla
        mil = self.cat.tutti_alloggi_pagina(citta="milano", limit=100)
        self.assertEqual([a["slug"] for a in mil["alloggi"]], [C.SLUG_MILANO])
        self.assertEqual(mil["totale"], 1)


# ═══════════════════════════════════════════════════════════════════════════
# 2. CALENDARIO E DISPONIBILITA'
# ═══════════════════════════════════════════════════════════════════════════
class TestCalendarioEDisponibilita(unittest.TestCase):

    def setUp(self):
        from fase58_channel_manager import crea_channel_manager
        self.f = _corpus(self)
        self.inv = crea_channel_manager(self.f["inventario"])

    def test_il_calendario_dice_la_verita_su_ogni_giorno(self):
        giorni = self.inv.calendario(C.SLUG_ROMA, "2026-09-01", "2026-09-12")
        self.assertEqual([g["giorno"] for g in giorni],
                         ["2026-09-%02d" % d for d in range(1, 12)])
        self.assertEqual(
            [g["stato"] for g in giorni],
            ["pieno", "pieno", "pieno", "chiuso", "libero", "libero", "libero",
             "pieno", "non_caricato", "libero", "pieno"])
        # VENDUTO **E** CHIUSO: vince 'pieno'. Dire 'chiuso' nasconderebbe all'host la
        # prenotazione viva di un ospite che quel giorno e' dentro casa sua.
        venduto_e_chiuso = [g for g in giorni if g["giorno"] == "2026-09-11"][0]
        self.assertEqual(venduto_e_chiuso["stato"], "pieno")
        self.assertEqual((venduto_e_chiuso["unita_totali"],
                          venduto_e_chiuso["unita_occupate"]), (1, 1))
        # il giorno mai caricato non porta numeri inventati
        buco = [g for g in giorni if g["giorno"] == "2026-09-09"][0]
        self.assertEqual(buco, {"giorno": "2026-09-09", "stato": "non_caricato"})
        # prezzo ZERO e' un dato, non un errore
        zero = [g for g in giorni if g["giorno"] == "2026-09-06"][0]
        self.assertEqual(zero["prezzo_netto_cents"], 0)
        # zero unita' totali = niente da vendere, quindi 'pieno'
        senza = [g for g in giorni if g["giorno"] == "2026-09-08"][0]
        self.assertEqual((senza["unita_totali"], senza["stato"]), (0, "pieno"))

    def test_la_disponibilita_rispetta_minimo_notti_buchi_e_chiusure(self):
        self.assertIs(self.inv.disponibile(C.SLUG_ROMA, "2026-09-01", "2026-09-02"), False)
        self.assertIs(self.inv.disponibile(C.SLUG_ROMA, "2026-09-04", "2026-09-05"), False)
        # 09-05 ha min_notti=3: una notte sola non e' prenotabile
        self.assertIs(self.inv.disponibile(C.SLUG_ROMA, "2026-09-05", "2026-09-06"), False)
        self.assertIs(self.inv.disponibile(C.SLUG_ROMA, "2026-09-05", "2026-09-08"), True)
        # il giorno MAI caricato non e' disponibile (assenza != libero)
        self.assertIs(self.inv.disponibile(C.SLUG_ROMA, "2026-09-09", "2026-09-10"), False)
        # alloggio che non esiste piu' in catalogo: risposta netta, nessuna eccezione
        self.assertIs(self.inv.disponibile(C.SLUG_SPARITO, "2026-07-01", "2026-07-02"), False)
        self.assertIsNone(self.inv.disponibile(C.SLUG_ROMA, "non-una-data", "2026-09-10"))

    def test_le_metriche_di_periodo_sono_esatte_al_centesimo(self):
        m = self.inv.metriche(alloggio_id=C.SLUG_ROMA, da="2026-09-01", a="2026-09-11")
        self.assertEqual(m, {"giorni": 9, "notti_totali": 9, "notti_occupate": 4,
                             "occupazione_bps": 4444, "revenue_cents": 75500})
        # 3 notti a 18500 + 1 notte a 20000; i giorni a prezzo zero non aggiungono nulla
        self.assertEqual(3 * 18500 + 1 * 20000, m["revenue_cents"])
        vuoto = self.inv.metriche(alloggio_id=C.SLUG_LONDRA, da="2026-09-01", a="2026-09-11")
        self.assertEqual(vuoto, {"giorni": 0, "notti_totali": 0, "notti_occupate": 0,
                                 "occupazione_bps": 0, "revenue_cents": 0})

    def test_la_prima_finestra_libera_salta_i_giorni_occupati(self):
        self.assertEqual(self.inv.prima_finestra(C.SLUG_ROMA, "2026-09-01", "2026-09-11", 3),
                         ("2026-09-05", "2026-09-08"))
        self.assertIsNone(self.inv.prima_finestra(C.SLUG_ROMA, "2026-09-01", "2026-09-11", 8))


# ═══════════════════════════════════════════════════════════════════════════
# 3. PRENOTAZIONI (pannello host e pannello admin)
# ═══════════════════════════════════════════════════════════════════════════
class TestPrenotazioniLetteDaArchiviVeri(unittest.TestCase):

    def setUp(self):
        from fase57_vetrina import crea_catalogo
        from fase58_channel_manager import crea_channel_manager
        self.f = _corpus(self)
        self.inv = crea_channel_manager(self.f["inventario"])
        self.cat = crea_catalogo(self.f["catalogo"])
        self.slug_roma = [a["slug"] for a in self.cat.alloggi_host(C.HOST_ROMA)]

    def test_conteggi_attive_e_archivio_separano_le_rilasciate(self):
        self.assertEqual(self.inv.conta_prenotazioni(alloggi=self.slug_roma,
                                                     vista="attive"), 5)
        self.assertEqual(self.inv.conta_prenotazioni(alloggi=self.slug_roma,
                                                     vista="archivio"), 1)
        # il tentativo RIFIUTATO non e' una prenotazione, in nessuna delle due viste
        pagina = self.inv.elenco_prenotazioni_pagina(alloggi=self.slug_roma, limit=50)
        arch = self.inv.elenco_prenotazioni_pagina(alloggi=self.slug_roma,
                                                   vista="archivio", limit=50)
        chiavi = [r["idem_key"] for r in pagina] + [r["idem_key"] for r in arch]
        self.assertNotIn("IDEM-2026-0005", chiavi)
        self.assertEqual(sorted(chiavi), sorted([
            C.REF_PAGATA, C.REF_ATTESA, C.REF_DOPPIONE, C.REF_SENZA_GEO,
            "reblock:" + C.REF_REBLOCK, C.REF_CANCELLATA]))

    def test_l_ordine_della_pagina_e_stabile_e_il_doppione_non_si_fonde(self):
        pagina = self.inv.elenco_prenotazioni_pagina(alloggi=self.slug_roma, limit=50)
        self.assertEqual([r["idem_key"] for r in pagina],
                         ["reblock:" + C.REF_REBLOCK, C.REF_ATTESA, C.REF_DOPPIONE,
                          C.REF_PAGATA, C.REF_SENZA_GEO])
        doppi = [r for r in pagina if r["check_in"] == "2026-09-01"]
        self.assertEqual(len(doppi), 2,
                         "due prenotazioni sulle STESSE date restano due righe distinte")
        self.assertEqual(len({r["idem_key"] for r in doppi}), 2)

    def test_date_nulle_e_origine_nulla_non_rompono_la_lettura(self):
        tokyo = self.inv.elenco_prenotazioni(alloggio_id=C.SLUG_TOKYO, limit=50)
        self.assertEqual(len(tokyo), 1)
        self.assertIsNone(tokyo[0]["check_in"])
        self.assertIsNone(tokyo[0]["check_out"])
        self.assertTrue(tokyo[0]["rimborsato"])
        senza_origine = [r for r in self.inv.elenco_prenotazioni(limit=100)
                         if r["idem_key"] == C.REF_ATTESA][0]
        self.assertIsNone(senza_origine["origine"])

    def test_la_vista_admin_vede_tutto_anche_le_righe_orfane(self):
        tutte = self.inv.elenco_prenotazioni(limit=100)
        self.assertEqual([r["idem_key"] for r in tutte],
                         ["reblock:" + C.REF_REBLOCK, C.REF_SCADUTA, C.REF_ATTESA,
                          C.REF_DOPPIONE, C.REF_PAGATA, C.REF_ORFANO,
                          C.REF_CANCELLATA, C.REF_SENZA_GEO])
        orfana = [r for r in tutte if r["idem_key"] == C.REF_ORFANO][0]
        self.assertEqual(orfana["alloggio_id"], C.SLUG_SPARITO)
        self.assertIsNone(self.cat.dettaglio(C.SLUG_SPARITO),
                          "il caso di prova non e' piu' quello di una riga orfana")
        self.assertEqual([r["rimborsato"] for r in tutte],
                         [False, True, False, False, False, False, True, False])

    def test_notti_per_alloggio_dac7_sopravvive_a_date_rotte_e_a_cavallo_d_anno(self):
        from fase162_pagamenti_pendenti import crea_pagamenti_pendenti
        pp = crea_pagamenti_pendenti(self.f["pendenti"])
        pp.inizializza_schema()
        self.assertEqual(pp.notti_per_alloggio(C.HOST_ROMA, 2026),
                         {C.SLUG_ROMA: {"notti": 12, "pren": 4},
                          C.SLUG_SENZA_GEO: {"notti": 7, "pren": 1}})
        # il soggiorno 2025-12-30 -> 2026-01-03 si SPACCA fra i due anni
        self.assertEqual(pp.notti_per_alloggio(C.HOST_ROMA, 2025),
                         {C.SLUG_ROMA: {"notti": 2, "pren": 1}})
        # le due righe rotte (date invertite, data vuota) sono state saltate, non contate
        con = sqlite3.connect(self.f["pendenti"])
        try:
            pagate = con.execute("SELECT COUNT(*) FROM pendenti WHERE host_id=? "
                                 "AND stato='pagato'", (C.HOST_ROMA,)).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(pagate, 7)
        self.assertEqual(sum(v["pren"] for v in
                             pp.notti_per_alloggio(C.HOST_ROMA, 2026).values()), 5)

    def test_ogni_stato_del_pendente_si_rilegge_come_e_stato_scritto(self):
        from fase162_pagamenti_pendenti import crea_pagamenti_pendenti
        pp = crea_pagamenti_pendenti(self.f["pendenti"])
        pp.inizializza_schema()
        attesi = {C.REF_PAGATA: "pagato", C.REF_ATTESA: "in_attesa",
                  C.REF_SCADUTA: "scaduto", C.REF_REBLOCK: "pagato",
                  C.REF_CANCELLATA: "cancellata_host", C.REF_DOPPIONE: "pagato",
                  C.REF_SENZA_GEO: "pagato", C.REF_CAVALLO_ANNO: "pagato",
                  C.REF_DA_RIMBORSARE: "da_rimborsare"}
        for rif, stato in attesi.items():
            rec = pp.info(rif)
            self.assertIsNotNone(rec, "%s non si rilegge" % rif)
            self.assertEqual(rec["stato"], stato, rif)
        self.assertEqual(pp.info(C.REF_ATTESA)["corpo_json"], "",
                         "corpo_json vuoto: dato legittimo di una riga vecchia")
        self.assertEqual([r["riferimento"] for r in pp.cancellate_host()],
                         [C.REF_CANCELLATA])
        self.assertIsNone(pp.info("MAI-ESISTITO"))


# ═══════════════════════════════════════════════════════════════════════════
# 4. SOLDI: payout, tassa, escrow
# ═══════════════════════════════════════════════════════════════════════════
class TestSoldiLettiDaArchiviVeri(unittest.TestCase):

    def setUp(self):
        self.f = _corpus(self)

    def _payout(self):
        from fase131_payout_dashboard import crea_payout_dashboard
        pd = crea_payout_dashboard(self.f["payout"])
        pd.inizializza_schema()
        return pd

    def test_il_riepilogo_payout_somma_per_valuta_e_per_stato(self):
        pd = self._payout()
        self.assertEqual(pd.riepilogo(C.HOST_ROMA),
                         {"EUR": {"maturato": 18300, "pagato": 24000,
                                  "in_transito": 0, "trattenuto": 5000}})
        self.assertEqual(pd.riepilogo(C.HOST_TOKYO), {"JPY": {"maturato": 47000}},
                         "le valute NON si sommano fra loro")
        self.assertEqual(pd.riepilogo("host-che-non-esiste"), {})
        # 'maturato' e' la somma di DUE righe: 15300 + 3000
        self.assertEqual(pd.info(C.REF_PAGATA)["minori"], 15300)
        self.assertEqual(pd.info(C.REF_CANCELLATA)["minori"], 3000)

    def test_un_payout_a_zero_e_un_numero_non_un_buco(self):
        pd = self._payout()
        rec = pd.info(C.REF_SENZA_GEO)
        self.assertEqual(rec["minori"], 0)
        self.assertEqual(rec["stato"], "in_transito")
        self.assertIn("in_transito", pd.riepilogo(C.HOST_ROMA)["EUR"])
        self.assertEqual(pd.riepilogo(C.HOST_ROMA)["EUR"]["in_transito"], 0)
        self.assertEqual(pd.conta_pagati(C.HOST_ROMA), 4,
                         "maturato+in_transito+pagato, anche quello a zero")
        self.assertEqual(pd.da_pagare(C.HOST_ROMA, "EUR"), 18300)

    def test_la_riga_payout_dell_host_cancellato_resta_leggibile(self):
        pd = self._payout()
        rec = pd.info(C.REF_ORFANO)
        self.assertEqual((rec["host_id"], rec["minori"], rec["stato"]),
                         (C.HOST_CANCELLATO, 9000, "maturato"))
        self.assertEqual(len(pd.tutti()), 7)

    def test_la_tassa_di_soggiorno_esclude_gli_storni(self):
        from fase147_tassa_comunale import crea_tassa_comunale
        tc = crea_tassa_comunale(self.f["tassa"])
        tc.inizializza_schema()
        self.assertEqual(tc.totale_riscosso("roma"), 2250,
                         "1350 + 900; i due storni (uno azzerato, uno che si e' tenuto "
                         "l'importo) NON si versano al Comune")
        self.assertEqual(tc.totale_riscosso("Roma"), 2250, "il comune si normalizza")
        # il tombstone VECCHIO ha ancora il suo importo scritto: vale il FLAG, non la cifra
        con = sqlite3.connect(self.f["tassa"])
        try:
            righe = con.execute("SELECT importo, stornato FROM tassa_riscossione "
                                "WHERE prenotazione_id=?",
                                (C.REF_DA_RIMBORSARE,)).fetchall()
        finally:
            con.close()
        self.assertEqual(righe, [(1200, 1)])
        self.assertEqual(tc.totale_riscosso("firenze"), 700)
        self.assertEqual(tc.totale_riscosso("comune-mai-visto"), 0)

    def test_una_regola_di_tassa_scritta_male_degrada_a_zero_senza_esplodere(self):
        from fase147_tassa_comunale import crea_tassa_comunale
        tc = crea_tassa_comunale(self.f["tassa"])
        tc.inizializza_schema()
        self.assertEqual(tc.regola("roma"), {"ppn_cents": 450, "max_notti": 10,
                                             "perc_bps": 0, "cap_persona_cents": 0})
        self.assertEqual(tc.applica("roma", 2, 3), 2700)      # 2 x 3 x 450
        self.assertEqual(tc.applica("roma", 2, 30), 9000,     # cap a 10 notti
                         "il tetto di notti tassabili deve reggere")
        # regola non-JSON e regola che non e' un oggetto: zero, mai un'eccezione
        self.assertEqual(tc.regola("comune-rotto"),
                         {"ppn_cents": 0, "max_notti": 0, "perc_bps": 0,
                          "cap_persona_cents": 0})
        self.assertEqual(tc.applica("comune-rotto", 2, 3), 0)
        self.assertEqual(tc.regola("comune-lista"), [450, 10])
        self.assertEqual(tc.applica("comune-lista", 2, 3), 0)

    def test_ogni_stato_dell_escrow_si_rilegge_con_gli_importi_giusti(self):
        from fase160_escrow_garanzia import crea_escrow_garanzia
        g = crea_escrow_garanzia(self.f["garanzia"])
        g.inizializza_schema()
        attesi = {
            C.REF_PAGATA: ("in_garanzia", 15300, 0, 0),
            C.REF_CAVALLO_ANNO: ("rilasciato", 24000, 24000, 0),
            C.REF_CANCELLATA: ("contestato", 8000, 0, 0),
            C.REF_DA_RIMBORSARE: ("annullato", 6000, 0, 0),
            C.REF_SENZA_GEO: ("risolto", 7900, 4900, 3000),
            C.REF_ORFANO: ("in_garanzia", 0, 0, 0)}
        for rif, (stato, imp, host, osp) in attesi.items():
            s = g.stato(rif)
            self.assertIsNotNone(s, rif)
            self.assertEqual((s["stato"], s["importo_host_cents"],
                              s["host_riceve_cents"], s["ospite_rimborso_cents"]),
                             (stato, imp, host, osp), rif)
        # conservazione: su una risoluzione, host + ospite == importo custodito
        r = g.stato(C.REF_SENZA_GEO)
        self.assertEqual(r["host_riceve_cents"] + r["ospite_rimborso_cents"],
                         r["importo_host_cents"])

    def test_i_soldi_ancora_in_custodia_bloccano_la_cancellazione_dell_annuncio(self):
        from fase160_escrow_garanzia import crea_escrow_garanzia
        g = crea_escrow_garanzia(self.f["garanzia"])
        g.inizializza_schema()
        # in_garanzia + contestato sull'attico = 2 (rilasciato/annullato/risolto NON contano)
        self.assertEqual(g.aperte_per_alloggio(C.SLUG_ROMA), 2)
        self.assertEqual(g.aperte_per_alloggio(C.SLUG_SENZA_GEO), 0)
        self.assertEqual(g.aperte_per_alloggio(C.SLUG_SPARITO), 1)
        self.assertEqual([c["prenotazione_id"] for c in g.contestate()],
                         [C.REF_CANCELLATA])
        self.assertEqual([a["prenotazione_id"] for a in g.aperte()],
                         [C.REF_ORFANO, C.REF_PAGATA])
        scadute = g.aperte_scadute(ora_ts=C.ts_utc(2025, 8, 1))
        self.assertEqual([s["prenotazione_id"] for s in scadute], [C.REF_ORFANO],
                         "l'escrow orfano da mesi e' uno STATO IMPOSSIBILE: va visto")


# ═══════════════════════════════════════════════════════════════════════════
# 5. GIORNALE E DAC7
# ═══════════════════════════════════════════════════════════════════════════
class TestGiornaleEDac7(unittest.TestCase):

    def setUp(self):
        from fase177_financial_controller import crea_financial_controller
        self.f = _corpus(self)
        self.fc = crea_financial_controller(self.f["finanza"])
        self.fc.inizializza_schema()

    def test_la_catena_del_giornale_scritta_fuori_dal_prodotto_e_valida(self):
        """La catena hash e' stata ricalcolata nel corpus in modo INDIPENDENTE, secondo il
        formato documentato: se il prodotto cambiasse formula senza accorgersene, un
        archivio vero diventerebbe 'manomesso' e qui si vedrebbe."""
        esito = self.fc.verifica_catena()
        self.assertTrue(esito["ok"], "catena rotta a seq %s" % esito.get("seq_rotta"))
        self.assertIsNone(esito["seq_rotta"])
        self.assertEqual(esito["righe"], 14)
        self.assertEqual(self.fc.conta_movimenti(), 14)

    def test_il_giornale_di_una_prenotazione_si_rilegge_riga_per_riga(self):
        mov = self.fc.movimenti(C.REF_PAGATA)
        self.assertEqual([m["tipo"] for m in mov],
                         ["incasso", "tassa_incassata", "commissione", "payout_host"])
        self.assertEqual([m["importo_cents"] for m in mov],
                         [19850, 1350, 1850, 16650])
        self.assertEqual({m["valuta"] for m in mov}, {"EUR"})
        # partita doppia: quanto e' entrato meno quanto e' uscito
        entrate = sum(m["importo_cents"] for m in mov
                      if m["conto_dare"] == "cassa_piattaforma")
        uscite = sum(m["importo_cents"] for m in mov
                     if m["conto_avere"] == "cassa_piattaforma")
        self.assertEqual(entrate - uscite, 19850 + 1350 - 16650)
        self.assertEqual(self.fc.movimenti("MAI-ESISTITO"), [])

    def test_il_report_dac7_ricostruisce_l_anno_fiscale(self):
        agg = self.fc.aggrega_dac7(2026)
        self.assertEqual(sorted(agg), [C.HOST_ROMA, C.HOST_TOKYO])
        roma = agg[C.HOST_ROMA]
        # lordo = incasso - tassa (la tassa e' pass-through al Comune, non e' ricavo host)
        self.assertEqual(roma["lordo"], 42500)          # (19850-1350) + (24900-900)
        self.assertEqual(roma["tasse"], 2250)
        self.assertEqual(roma["netto"], 38650)          # 16650 + 22000
        self.assertEqual(roma["commissioni"], 3850)     # 1850 registrata + 2000 dedotta
        self.assertEqual(roma["n"], 2)
        self.assertEqual(roma["lordo"], roma["netto"] + roma["commissioni"])
        self.assertEqual(roma["trim"], {1: 18500, 2: 24000, 3: 0, 4: 0})
        self.assertEqual(roma["trim_n"], {1: 1, 2: 1, 3: 0, 4: 0})
        tokyo = agg[C.HOST_TOKYO]
        self.assertEqual((tokyo["lordo"], tokyo["netto"], tokyo["commissioni"],
                          tokyo["tasse"], tokyo["n"]), (50000, 45000, 5000, 0, 1))
        self.assertEqual(tokyo["trim"], {1: 0, 2: 0, 3: 50000, 4: 0})

    def test_l_anno_precedente_resta_fuori_e_si_legge_da_solo(self):
        self.assertEqual(self.fc.aggrega_dac7(2025),
                         {C.HOST_ROMA: {"n": 1, "lordo": 10000, "netto": 9000,
                                        "commissioni": 1000, "tasse": 0, "rimborsi": 0,
                                        "trim": {1: 0, 2: 0, 3: 10000, 4: 0},
                                        "trim_n": {1: 0, 2: 0, 3: 1, 4: 0}}})
        self.assertEqual(self.fc.aggrega_dac7(2024), {})

    def test_un_rimborso_senza_incasso_non_inventa_un_host(self):
        """Riga ORFANA nel giornale: un rimborso di una prenotazione nata prima del
        giornale. Non dev'essere attribuito a nessuno, ne' far saltare il report."""
        agg = self.fc.aggrega_dac7(2026)
        self.assertNotIn("", agg)
        self.assertEqual(sum(h["rimborsi"] for h in agg.values()), 0)
        mov = self.fc.movimenti(C.REF_DA_RIMBORSARE)
        self.assertEqual([(m["tipo"], m["importo_cents"]) for m in mov],
                         [("rimborso", 12000)])

    def test_note_e_debiti_si_rileggono_con_il_ts_nullo(self):
        note = self.fc.note_per_riferimento(C.REF_CANCELLATA)
        self.assertEqual(len(note), 1)
        self.assertEqual((note[0]["nota_id"], note[0]["tipo"], note[0]["importo_cents"],
                          note[0]["valuta"], note[0]["stato"]),
                         ("NC-2026-000001", "credito", 3000, "EUR", "emessa"))
        self.assertIsNone(note[0]["storno_di"])
        aperti = self.fc.debiti_host(C.HOST_ROMA, stato="aperto")
        self.assertEqual(len(aperti), 1)
        self.assertEqual(aperti[0]["residuo_cents"], 3000)
        self.assertIsNone(aperti[0]["prossimo_ts"], "colonna nullable: deve restare None")
        self.assertEqual(len(self.fc.debiti_host(C.HOST_ROMA)), 2)
        # il debito gia' saldato ha residuo ZERO: numero, non assenza
        saldato = [d for d in self.fc.debiti_host(C.HOST_ROMA)
                   if d["stato"] == "saldato"][0]
        self.assertEqual(saldato["residuo_cents"], 0)

    def test_il_contatore_dac7_su_file_json_si_rilegge(self):
        from fase100_dac7 import crea_registro_dac7
        rd = crea_registro_dac7(self.f["dac7"])
        roma = rd.stato(C.HOST_ROMA)
        self.assertEqual((roma.prenotazioni, roma.ricavi_cents, roma.dati_forniti),
                         (42, 250000, True))
        self.assertTrue(roma.deve_segnalare, "42 prenotazioni: sopra la soglia UE")
        tokyo = rd.stato(C.HOST_TOKYO)
        self.assertEqual((tokyo.prenotazioni, tokyo.ricavi_cents, tokyo.dati_forniti),
                         (3, 50000, False))
        self.assertFalse(tokyo.deve_segnalare)
        # host mai visto: conteggio a zero, nessuna eccezione
        zero = rd.stato("host-che-non-esiste")
        self.assertEqual((zero.prenotazioni, zero.ricavi_cents), (0, 0))

    def test_un_record_dac7_di_forma_vecchia_degrada_invece_di_esplodere(self):
        """DIFETTO TROVATO QUI (2026-07-29). `_rec` restituiva il record COSI' COM'E' e
        `stato()` faceva `rec['ricavi']`: un record scritto da una versione precedente
        (solo 'pren') alzava KeyError, e un record che non era un oggetto alzava
        AttributeError — non un numero sbagliato, proprio un errore in faccia. Ora ogni
        campo assente o di tipo sbagliato ripiega sul valore neutro."""
        from fase100_dac7 import crea_registro_dac7
        rd = crea_registro_dac7(self.f["dac7"])
        parziale = rd.stato(C.HOST_DAC7_PARZIALE)
        self.assertEqual((parziale.prenotazioni, parziale.ricavi_cents,
                          parziale.dati_forniti), (5, 0, False))
        self.assertFalse(parziale.deve_segnalare)
        self.assertTrue(rd.visibile(C.HOST_DAC7_PARZIALE))
        self.assertTrue(rd.payout_consentito(C.HOST_DAC7_PARZIALE))
        rotto = rd.stato(C.HOST_DAC7_ROTTO)
        self.assertEqual((rotto.prenotazioni, rotto.ricavi_cents,
                          rotto.dati_forniti), (0, 0, False))
        # e gli host sani, nello STESSO file, restano letti bene
        self.assertEqual(rd.stato(C.HOST_ROMA).prenotazioni, 42)

    def test_un_file_dac7_che_non_e_un_oggetto_non_fa_esplodere_la_lettura(self):
        from fase100_dac7 import crea_registro_dac7
        percorso = os.path.join(self.f["dir"], "dac7_lista.json")
        with open(percorso, "w", encoding="utf-8") as fh:
            json.dump(["questa", "non", "e'", "una", "mappa"], fh)
        rd = crea_registro_dac7(percorso)
        stato = rd.stato(C.HOST_ROMA)
        self.assertEqual((stato.prenotazioni, stato.ricavi_cents), (0, 0))
        self.assertTrue(rd.payout_consentito(C.HOST_ROMA))


# ═══════════════════════════════════════════════════════════════════════════
# 6. PROVE LEGALI E REGISTRO HOST
# ═══════════════════════════════════════════════════════════════════════════
class TestProveLegaliEHostVeri(unittest.TestCase):

    def setUp(self):
        self.f = _corpus(self)

    def _acc(self):
        from fase163_accettazioni import crea_registro_accettazioni
        return crea_registro_accettazioni(self.f["accettazioni"], C.SEGRETO)

    def _host(self):
        from fase88_registro_host import crea_registro_host
        return crea_registro_host(self.f["registro_host"], C.SEGRETO)

    def test_le_firme_archiviate_restano_verificabili(self):
        ac = self._acc()
        righe = ac.elenco(C.HOST_ROMA)
        self.assertEqual([r["documento"] for r in righe],
                         ["contratto_host", "privacy_gdpr", "identita_stripe"])
        self.assertEqual([r["integra"] for r in righe], [True, True, True])
        # la prova col RIFERIMENTO esterno entra nella firma e resta valida
        ident = [r for r in righe if r["documento"] == "identita_stripe"][0]
        self.assertEqual(ident["riferimento"], "vs_1AbCdEfGhIjK")
        self.assertTrue(ident["integra"])
        # e quelle SENZA riferimento (scritte prima che la colonna esistesse) pure
        contratto = righe[0]
        self.assertEqual(contratto["riferimento"], "")
        self.assertTrue(contratto["integra"])

    def test_una_prova_manomessa_viene_segnalata_non_nascosta(self):
        ac = self._acc()
        righe = ac.elenco(C.HOST_SOSPESO)
        self.assertEqual(len(righe), 1)
        self.assertFalse(righe[0]["integra"],
                         "una firma che non torna dev'essere DICHIARATA falsa")
        self.assertEqual(righe[0]["firma"], "0" * 64,
                         "la riga non va riscritta: si legge e si segnala")
        # e non deve valere come consenso
        self.assertFalse(ac.ha_accettato_corrente(C.HOST_SOSPESO))
        self.assertTrue(ac.stato_consensi(C.HOST_SOSPESO)["deve_riaccettare"])

    def test_una_versione_vecchia_del_contratto_obbliga_a_riaccettare(self):
        ac = self._acc()
        roma = ac.stato_consensi(C.HOST_ROMA)
        self.assertEqual(roma["versione_accettata"], C.CONTRATTO_VERSIONE_CORRENTE)
        self.assertEqual([roma["contratto_corrente"], roma["clausole_vessatorie"],
                          roma["privacy_corrente"], roma["deve_riaccettare"]],
                         [True, True, True, False])
        tokyo = ac.stato_consensi(C.HOST_TOKYO)
        self.assertEqual(tokyo["versione_accettata"], C.CONTRATTO_VERSIONE_VECCHIA)
        self.assertEqual([tokyo["contratto_corrente"], tokyo["privacy_corrente"],
                          tokyo["deve_riaccettare"]], [False, False, True])

    def test_il_sigillo_del_registro_copre_tutte_le_prove(self):
        ac = self._acc()
        s1 = ac.sigillo()
        self.assertEqual(s1["righe"], 5)
        self.assertEqual(len(s1["sigillo"]), 64)
        self.assertEqual(ac.conta(), 5)
        self.assertEqual(ac.sigillo(), s1, "il sigillo dev'essere deterministico")

    def test_l_host_di_mesi_fa_entra_ancora_con_la_sua_password(self):
        rh = self._host()
        esito = rh.login(C.EMAIL_ROMA, C.PASSWORD_ROMA)
        self.assertTrue(esito.ok, esito.errore)
        self.assertEqual(esito.host_id, C.HOST_ROMA)
        self.assertEqual(rh.verifica_token(esito.token), C.HOST_ROMA)
        self.assertFalse(rh.login(C.EMAIL_ROMA, "password-sbagliata").ok)
        # sospeso e cancellato NON entrano, e il messaggio non svela l'esistenza
        sosp = rh.login("mario.sospeso@example.com", "qualunque")
        self.assertFalse(sosp.ok)
        self.assertEqual(sosp.errore, "account_sospeso")

    def test_i_dati_fiscali_incompleti_si_leggono_come_incompleti(self):
        rh = self._host()
        elenco = rh.elenco_host()
        self.assertEqual([h["host_id"] for h in elenco],
                         [C.HOST_CANCELLATO, C.HOST_ROMA, C.HOST_TOKYO, C.HOST_SOSPESO])
        roma = [h for h in elenco if h["host_id"] == C.HOST_ROMA][0]
        self.assertEqual(roma["codice_fiscale"], "RSSCHR85M41H501Z")
        self.assertEqual(roma["iban"], "IT60X0542811101000000123456")
        self.assertEqual(roma["verifica_stato"], "verificato")
        tokyo = [h for h in elenco if h["host_id"] == C.HOST_TOKYO][0]
        self.assertEqual(tokyo["ragione_sociale"],
                         "田中ゲストハウス")
        self.assertEqual([tokyo["codice_fiscale"], tokyo["partita_iva"], tokyo["iban"],
                          tokyo["paese"]], ["", "", "", ""])
        self.assertEqual(rh.conta_host(), 4)
        self.assertIsNone(rh.info_host("host-che-non-esiste"))

    def test_le_recensioni_con_categorie_mancanti_danno_medie_giuste(self):
        from fase63_recensioni import crea_registro_recensioni
        rr = crea_registro_recensioni(self.f["recensioni"], C.SEGRETO)
        rr.inizializza_schema()
        rie = rr.riepilogo(C.SLUG_ROMA)
        self.assertEqual(rie["conteggio"], 3, "la non verificata resta fuori")
        self.assertEqual(rie["media_centesimi"], 466)      # (5+4+5)*100//3
        self.assertEqual(rie["distribuzione"], {1: 0, 2: 0, 3: 0, 4: 1, 5: 2})
        # le categorie si mediano SOLO su chi le ha compilate
        self.assertEqual(rie["categorie"],
                         {"pulizia": {"conteggio": 2, "media_centesimi": 450},
                          "comfort": {"conteggio": 1, "media_centesimi": 500}})
        elenco = rr.elenco(C.SLUG_ROMA)
        self.assertEqual([r["prenotazione_id"] for r in elenco],
                         [C.REF_PAGATA, C.REF_DOPPIONE, C.REF_CAVALLO_ANNO])
        self.assertEqual(elenco[0]["testo"]["lang"], "it")
        self.assertIn("\U0001f60d", elenco[0]["testo"]["text"])
        self.assertEqual(elenco[1]["testo"]["text"], "", "testo vuoto e' un dato valido")
        self.assertNotIn("categorie", elenco[1])
        # recensione ORFANA (annuncio sparito): si legge, non contamina gli altri
        self.assertEqual(rr.riepilogo(C.SLUG_SPARITO)["conteggio"], 1)
        self.assertEqual(rr.riepilogo(C.SLUG_LONDRA),
                         {"conteggio": 0, "media_centesimi": 0,
                          "distribuzione": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
                          "categorie": {}})


# ═══════════════════════════════════════════════════════════════════════════
# 7. IL SITO INTERO, ACCESO SUL CORPUS
# ═══════════════════════════════════════════════════════════════════════════
class TestSitoInteroSuDatiVeri(unittest.TestCase):
    """Le classi qui sopra aprono un archivio alla volta. Un deploy no: accende TUTTO
    insieme sulla /data vera. Qui si accende il sistema (bootstrap + router) sul corpus e
    si chiede al sito quello che chiederebbero un ospite, un host e un operatore."""

    def setUp(self):
        self.f = _corpus(self)
        # ISOLAMENTO: nessuna chiamata a marcatori temporali esterni, nessuna pulizia di
        # cartelle dello sviluppatore, upload in una cartella usa-e-getta.
        upload = os.path.join(self.f["dir"], "uploads")
        os.makedirs(upload, exist_ok=True)
        for chiave, valore in (("MARCA_TEMPORALE", "0"), ("PULIZIA_UPLOADS", "0"),
                               ("UPLOAD_DIR", upload),
                               ("OUTREACH_OPTOUT_FILE",
                                os.path.join(self.f["dir"], "optout.txt"))):
            self._env(chiave, valore)
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase83_server import crea_router
        self.sistema = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=C.SEGRETO, con_registrazione_host=True,
            db_catalogo=self.f["catalogo"], db_inventario=self.f["inventario"],
            db_registro_host=self.f["registro_host"], db_pendenti=self.f["pendenti"],
            db_payout=self.f["payout"], db_tassa_comunale=self.f["tassa"],
            db_garanzia=self.f["garanzia"], db_accettazioni=self.f["accettazioni"],
            db_finanza=self.f["finanza"], db_recensioni=self.f["recensioni"],
            commissione_bps=1000, psp_bps=300))
        self.router = crea_router(self.sistema, host_key="hk", admin_key="ak",
                                  base_url="https://bookinvip.com")
        stato, corpo = self.chiama("POST", "/api/host/login",
                                   {"email": C.EMAIL_ROMA, "password": C.PASSWORD_ROMA})
        self.assertEqual(stato, 200, corpo)
        self.H = {"X-Host-Token": corpo["token"]}
        self.A = {"X-Admin-Key": "ak"}

    def _env(self, chiave, valore):
        vecchio = os.environ.get(chiave)
        os.environ[chiave] = valore
        self.addCleanup(lambda: os.environ.__setitem__(chiave, vecchio)
                        if vecchio is not None else os.environ.pop(chiave, None))

    def chiama(self, metodo, percorso, corpo=None, headers=None, query=None):
        return self.router.gestisci(
            metodo, percorso, query or {},
            json.dumps(corpo) if corpo is not None else None, headers or {})

    def test_nessuna_lettura_del_prodotto_esplode_sui_dati_veri(self):
        """Il giro completo delle letture: ogni rotta risponde con lo stato ATTESO
        (200, mai 500 ne' 503) leggendo archivi pieni di casi storti."""
        rotte = [
            ("/api/health/live", None, None), ("/api/health/ready", None, None),
            ("/api/health/db", None, None),
            ("/api/catalogo", {"citta": "roma"}, None),
            ("/api/catalogo", {"ordine": "prezzo_asc", "limit": "100"}, None),
            ("/api/catalogo/" + C.SLUG_ROMA, None, None),
            ("/api/catalogo/" + C.SLUG_LONDRA, None, None),
            ("/api/catalogo/" + C.SLUG_ORFANO, None, None),
            ("/api/mappa", {"citta": "roma"}, None),
            ("/api/recensioni/" + C.SLUG_ROMA, None, None),
            ("/api/recensioni/" + C.SLUG_SPARITO, None, None),
            ("/api/trasparenza", None, None),
            ("/api/host/alloggi", None, self.H),
            ("/api/host/alloggio", {"slug": C.SLUG_ROMA}, self.H),
            ("/api/host/prenotazioni", None, self.H),
            ("/api/host/prenotazioni", {"vista": "archivio"}, self.H),
            ("/api/host/payout", None, self.H),
            ("/api/host/richieste", None, self.H),
            ("/api/host/metriche", {"alloggio": C.SLUG_ROMA}, self.H),
            ("/api/host/metriche_avanzate", None, self.H),
            ("/api/host/calendario",
             {"alloggio": C.SLUG_ROMA, "da": "2026-09-01", "a": "2026-09-11"}, self.H),
            ("/api/host/calendario_tutti", {"da": "2026-09-01", "a": "2026-09-11"}, self.H),
            ("/api/host/export", None, self.H),
            ("/api/host/accettazioni", None, self.H),
            ("/api/host/contratto_stato", None, self.H),
            ("/api/host/dac7_stato", None, self.H),
            ("/api/admin/prenotazioni", None, self.A),
            ("/api/admin/alloggi", None, self.A),
            ("/api/admin/alloggi", {"stato": "sospeso"}, self.A),
            ("/api/admin/search", {"q": "trastevere"}, self.A),
            ("/api/admin/search", {"q": "rossi"}, self.A),
            ("/api/admin/controversie", None, self.A),
            ("/api/admin/verifiche", None, self.A),
            ("/api/admin/diagnosi", None, self.A),
        ]
        esiti = {}
        for percorso, query, headers in rotte:
            stato, corpo = self.chiama("GET", percorso, None, headers, query)
            esiti["%s?%s" % (percorso, sorted((query or {}).items()))] = stato
            self.assertIsInstance(corpo, dict, percorso)
        rotti = {k: v for k, v in esiti.items() if v != 200}
        self.assertEqual(rotti, {},
                         "queste letture NON reggono i dati veri: %r" % rotti)
        self.assertEqual(len(esiti), len(rotte), "due rotte si sono sovrapposte")

    def test_la_scheda_pubblica_porta_titolo_prezzo_e_recensioni_giusti(self):
        stato, d = self.chiama("GET", "/api/catalogo/" + C.SLUG_ROMA)
        self.assertEqual(stato, 200)
        self.assertEqual(d["titolo"], C.TITOLO_ROMA)
        self.assertEqual(d["prezzo_notte_cents"], 18500)
        self.assertEqual(d["valuta"], "EUR")
        self.assertEqual(d["cin"], "IT058091C2X3Y4Z5W6")
        self.assertEqual(d["fuso"], "Europe/Rome")
        self.assertEqual(d["politica_cancellazione"], "moderata")
        self.assertEqual(d["recensioni"], {"conteggio": 3, "media_centesimi": 466})
        self.assertNotIn("indirizzo", d, "l'indirizzo esatto NON e' pubblico")
        # l'annuncio senza CIN non deve mostrare 'None' ma una stringa vuota; il fuso,
        # che nell'archivio era vuoto, e' stato dedotto all'accensione (vedi
        # test_il_fuso_mancante_viene_dedotto_all_apertura)
        _s, jp = self.chiama("GET", "/api/catalogo/" + C.SLUG_SENZA_GEO)
        self.assertEqual(jp["cin"], "")
        self.assertEqual(jp["fuso"], "Europe/Rome")
        self.assertIsNone(jp["lat_micro"])

    def test_il_pannello_host_elenca_le_sue_prenotazioni_con_lo_stato_giusto(self):
        stato, corpo = self.chiama("GET", "/api/host/prenotazioni", None, self.H)
        self.assertEqual(stato, 200, corpo)
        self.assertEqual((corpo["totale"], corpo["totale_attive"],
                          corpo["totale_archivio"]), (5, 5, 1))
        self.assertEqual(len(corpo["prenotazioni"]), 5)
        self.assertEqual([p["slug"] for p in corpo["prenotazioni"]],
                         [C.SLUG_ROMA, C.SLUG_ROMA, C.SLUG_ROMA, C.SLUG_ROMA,
                          C.SLUG_SENZA_GEO])
        for p in corpo["prenotazioni"]:
            self.assertFalse(p["archiviata"])
            self.assertEqual(p["stato"],
                             _etichetta_attesa(p["check_in"], p["check_out"]),
                             "etichetta sbagliata per %s" % p["codice"])
        # ARCHIVIO: la cancellata dall'host si chiama 'cancellata', non 'rimborsata'
        stato, arch = self.chiama("GET", "/api/host/prenotazioni",
                                  None, self.H, {"vista": "archivio"})
        self.assertEqual(stato, 200)
        self.assertEqual(len(arch["prenotazioni"]), 1)
        self.assertEqual(arch["prenotazioni"][0]["stato"], "cancellata")
        self.assertTrue(arch["prenotazioni"][0]["archiviata"])
        self.assertEqual(arch["prenotazioni"][0]["slug"], C.SLUG_ROMA)

    def test_il_pannello_payout_mostra_incassi_e_debito_aperto(self):
        stato, corpo = self.chiama("GET", "/api/host/payout", None, self.H)
        self.assertEqual(stato, 200, corpo)
        self.assertEqual(corpo["payout"],
                         {"EUR": {"maturato": 18300, "pagato": 24000,
                                  "in_transito": 0, "trattenuto": 5000}})
        self.assertEqual(corpo["debiti_aperti_cents"], {"EUR": 3000},
                         "il debito SALDATO non deve comparire")

    def test_i_kpi_del_pannello_contano_anche_la_prenotazione_ri_bloccata(self):
        """DIFETTO VERO (2026-07-29). Dopo un pagamento tardivo la chiave del blocco
        diventa `reblock:<rif>`: `_arricchisci_metrica` non toglieva quel prefisso e la
        prenotazione, REGOLARMENTE PAGATA, valeva zero. Numeri prima della correzione:
        revenue 44750, ADR 2486, RevPAR 1491 — sbagliati, non mancanti."""
        stato, corpo = self.chiama("GET", "/api/host/metriche_avanzate", None, self.H)
        self.assertEqual(stato, 200, corpo)
        m = corpo["metriche"]
        self.assertEqual(m["revenue_cents"], 69650,      # 19850 + 24900 + 24900
                         "manca l'incasso di una prenotazione pagata")
        self.assertEqual(m["notti_vendute"], 18)
        self.assertEqual(m["adr_cents"], 69650 // 18)
        self.assertEqual(m["revpar_cents"], 69650 // 30)
        self.assertEqual((m["prenotazioni_totali"], m["prenotazioni_attive"],
                          m["cancellate"]), (6, 5, 1))
        self.assertEqual(corpo["valuta"], "EUR")

    def test_metriche_e_calendario_dell_host_sui_dati_veri(self):
        stato, m = self.chiama("GET", "/api/host/metriche", None, self.H,
                               {"alloggio": C.SLUG_ROMA, "da": "2026-09-01",
                                "a": "2026-09-11"})
        self.assertEqual(stato, 200, m)
        self.assertEqual(m["revenue_cents"], 75500)
        self.assertEqual(m["occupazione_bps"], 4444)
        self.assertEqual((m["prenotazioni_attive"], m["prenotazioni_rimborsate"]), (4, 1))
        self.assertEqual(m["money_unit"], "cents_integer")
        stato, cal = self.chiama("GET", "/api/host/calendario", None, self.H,
                                 {"alloggio": C.SLUG_ROMA, "da": "2026-09-01",
                                  "a": "2026-09-11"})
        self.assertEqual(stato, 200, cal)
        self.assertEqual([g["stato"] for g in cal["giorni"]],
                         ["pieno", "pieno", "pieno", "chiuso", "libero", "libero",
                          "libero", "pieno", "non_caricato", "libero"])

    def test_l_export_csv_dell_host_non_si_rompe_sui_campi_nulli(self):
        stato, corpo = self.chiama("GET", "/api/host/export", None, self.H)
        self.assertEqual(stato, 200, corpo)
        righe = corpo["csv"].replace("\r\n", "\n").strip().split("\n")
        self.assertEqual(righe[0], "alloggio,check_in,check_out,notti,origine,stato,"
                                   "revenue,valuta,riferimento")
        self.assertEqual(len(righe), 7, "intestazione + 6 prenotazioni")
        # `origine` NULL diventa colonna VUOTA, non la stringa "None"
        con_origine_nulla = [r for r in righe if C.REF_ATTESA in r]
        self.assertEqual(len(con_origine_nulla), 1)
        self.assertIn(",,attiva,", con_origine_nulla[0])
        self.assertNotIn("None", corpo["csv"])
        self.assertIn("2026-09-01,2026-09-04,3,web,attiva,555.00,EUR", corpo["csv"])

    def test_il_pannello_admin_vede_tutto_senza_inciampare_sugli_orfani(self):
        stato, corpo = self.chiama("GET", "/api/admin/prenotazioni", None, self.A)
        self.assertEqual(stato, 200, corpo)
        self.assertEqual(len(corpo["prenotazioni"]), 8)
        self.assertIn(C.SLUG_SPARITO,
                      [p["alloggio_id"] for p in corpo["prenotazioni"]])
        stato, al = self.chiama("GET", "/api/admin/alloggi", None, self.A, {"limit": "20"})
        self.assertEqual(stato, 200, al)
        self.assertEqual(al["totale"], 8)
        self.assertEqual(al["pagine"], 1)
        stato, ctrl = self.chiama("GET", "/api/admin/controversie", None, self.A)
        self.assertEqual(stato, 200, ctrl)
        self.assertEqual([c["prenotazione_id"] for c in ctrl["controversie"]],
                         [C.REF_CANCELLATA])
        self.assertEqual(ctrl["controversie"][0]["importo_host_cents"], 8000)
        self.assertEqual(ctrl["controversie"][0]["titolo"], C.TITOLO_ROMA)

    def test_la_ricerca_operativa_trova_annunci_host_e_prenotazioni(self):
        stato, r = self.chiama("GET", "/api/admin/search", None, self.A,
                               {"q": "trastevere"})
        self.assertEqual(stato, 200, r)
        self.assertEqual([a["slug"] for a in r["annunci"]], [C.SLUG_ROMA])
        self.assertEqual(r["totali"]["annunci"], 1)
        stato, h = self.chiama("GET", "/api/admin/search", None, self.A, {"q": "rossi"})
        self.assertEqual(stato, 200, h)
        self.assertEqual([x["host_id"] for x in h["host"]], [C.HOST_ROMA])
        # i dati fiscali NON escono mai dalla ricerca operativa
        self.assertNotIn("iban", json.dumps(h))
        self.assertNotIn("RSSCHR85M41H501Z", json.dumps(h))


# ═══════════════════════════════════════════════════════════════════════════
# 8. IL CONTROLLO SA FALLIRE (visto rosso permanente)
# ═══════════════════════════════════════════════════════════════════════════
class TestIlControlloSaFallire(unittest.TestCase):
    """Regola aurea: un controllo che non puo' fallire e' un ornamento. Qui si sporca il
    corpus nei quattro modi che contano — un centesimo cambiato, una riga sparita, un
    anello di catena rotto, una firma manomessa — e si pretende che i controlli lo
    vedano; con la controprova che sul corpus SANO non gridano."""

    def setUp(self):
        self.f = _corpus(self)

    def _esegui(self, percorso, sql, parametri=()):
        con = sqlite3.connect(percorso)
        try:
            with con:
                con.execute(sql, parametri)
        finally:
            con.close()

    def test_un_centesimo_cambiato_nel_payout_viene_visto(self):
        from fase131_payout_dashboard import crea_payout_dashboard
        pd = crea_payout_dashboard(self.f["payout"])
        pd.inizializza_schema()
        sano = pd.riepilogo(C.HOST_ROMA)
        self.assertEqual(sano["EUR"]["maturato"], 18300)
        self._esegui(self.f["payout"],
                     "UPDATE payout SET minori=minori-1 WHERE prenotazione_id=?",
                     (C.REF_PAGATA,))
        pd2 = crea_payout_dashboard(self.f["payout"])
        self.assertEqual(pd2.riepilogo(C.HOST_ROMA)["EUR"]["maturato"], 18299)
        self.assertNotEqual(pd2.riepilogo(C.HOST_ROMA), sano,
                            "il confronto non vede un centesimo cambiato")

    def test_una_prenotazione_sparita_viene_vista(self):
        from fase57_vetrina import crea_catalogo
        from fase58_channel_manager import crea_channel_manager
        inv = crea_channel_manager(self.f["inventario"])
        cat = crea_catalogo(self.f["catalogo"])
        slug = [a["slug"] for a in cat.alloggi_host(C.HOST_ROMA)]
        self.assertEqual(inv.conta_prenotazioni(alloggi=slug, vista="attive"), 5)
        self._esegui(self.f["inventario"], "DELETE FROM movimenti WHERE idem_key=?",
                     (C.REF_PAGATA,))
        inv2 = crea_channel_manager(self.f["inventario"])
        self.assertEqual(inv2.conta_prenotazioni(alloggi=slug, vista="attive"), 4,
                         "il conteggio non vede una prenotazione sparita")

    def test_un_anello_rotto_della_catena_viene_puntato_per_seq(self):
        from fase177_financial_controller import crea_financial_controller
        fc = crea_financial_controller(self.f["finanza"])
        fc.inizializza_schema()
        self.assertTrue(fc.verifica_catena()["ok"])
        # i trigger vietano UPDATE: si riscrive il file come farebbe un manomettitore
        con = sqlite3.connect(self.f["finanza"])
        try:
            with con:
                con.execute("DROP TRIGGER IF EXISTS lg_no_update")
                con.execute("UPDATE libro_giornale SET importo_cents=1 WHERE seq=3")
        finally:
            con.close()
        esito = crea_financial_controller(self.f["finanza"]).verifica_catena()
        self.assertFalse(esito["ok"], "la catena non vede un importo riscritto a mano")
        self.assertEqual(esito["seq_rotta"], 3)

    def test_una_firma_valida_e_una_manomessa_si_distinguono(self):
        from fase163_accettazioni import crea_registro_accettazioni
        ac = crea_registro_accettazioni(self.f["accettazioni"], C.SEGRETO)
        self.assertEqual([r["integra"] for r in ac.elenco(C.HOST_ROMA)],
                         [True, True, True])
        self._esegui(self.f["accettazioni"],
                     "UPDATE accettazioni SET accettato_ts=accettato_ts+1 WHERE id=1")
        ac2 = crea_registro_accettazioni(self.f["accettazioni"], C.SEGRETO)
        righe = ac2.elenco(C.HOST_ROMA)
        self.assertEqual([r["integra"] for r in righe], [False, True, True],
                         "spostare l'ora di una prova non deve passare inosservato")
        self.assertFalse(ac2.ha_accettato_corrente(C.HOST_ROMA))

    def test_il_corpus_e_scritto_senza_il_prodotto(self):
        """Se un domani qualcuno costruisse il corpus con le funzioni del prodotto, questo
        collaudo smetterebbe di provare qualcosa: proverebbe solo che il prodotto sa
        rileggere se stesso."""
        percorso = os.path.join(QUI, "collaudi", "dati_realistici.py")
        with open(percorso, encoding="utf-8") as fh:
            testo = fh.read()
        import ast
        albero = ast.parse(testo)
        moduli = set()
        for nodo in ast.walk(albero):
            if isinstance(nodo, ast.Import):
                moduli.update(a.name for a in nodo.names)
            elif isinstance(nodo, ast.ImportFrom):
                moduli.add(nodo.module or "")
        colpevoli = sorted(m for m in moduli if m.startswith("fase"))
        self.assertEqual(colpevoli, [],
                         "il corpus importa il prodotto: %r" % colpevoli)
        self.assertIn("import sqlite3", testo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
