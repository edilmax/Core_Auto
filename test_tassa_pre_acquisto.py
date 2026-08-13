"""Test tassa di soggiorno PRECISA e PRE-ACQUISTO: l'host la dichiara sull'annuncio (tutela),
il preventivo la calcola e la mostra separata + totale. Citta' senza regola -> 0 (mai inventare)."""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

SEG = b"t" * 32
HK = {"X-Host-Key": "hk"}


def _fra(giorni):
    """Una data scritta come INTENZIONE, non come cifra sul calendario.

    ⛔ `test_cancellazione_rimborsa_anche_la_tassa` pretende il rimborso PIENO, che la
    politica flessibile concede solo se all'arrivo manca abbastanza tempo. Con le date
    cablate (2027-01-10/12) sarebbe diventato rosso da solo il **2027-01-10**, misurato il
    2026-08-13: il rimborso sarebbe sceso da 20800 a 10800 e nessuno avrebbe toccato una
    riga di codice. ⚠️ E questo test guarda i SOLDI dell'ospite: un rosso qui, il giorno
    che arriva, sembra un difetto sulla tassa e manda a cercare dove non c'e' niente."""
    import datetime
    return (datetime.date.today() + datetime.timedelta(days=giorni)).isoformat()


class TestTassaPreAcquisto(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db",
            db_domanda=f"{d}/dom.db", db_garanzia=f"{d}/g.db", file_referral=f"{d}/ref.json",
            commissione_bps=1500))
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _pubblica(self, **tax):
        body = {"host_id": "demo", "slug": "casa", "titolo": "Casa", "citta": "Roma",
                "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 4,
                "servizi": [], "immagini": []}
        body.update(tax)
        self.g("POST", "/api/host/pubblica", body, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa",
                "da": _fra(1), "a": _fra(60), "unita_totali": 1,
                "prezzo_netto_cents": 10000}, HK)

    def _quote(self, party=2):
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa",
                      "check_in": _fra(20), "check_out": _fra(22), "party": party})
        return q

    def test_tassa_calcolata_e_mostrata_pre_acquisto(self):
        self._pubblica(tassa_pp_notte_cents=200)            # €2,00 per persona/notte
        q = self._quote(party=2)                            # 2 persone x 2 notti
        self.assertEqual(q["tassa_soggiorno_cents"], 800)   # 200*2*2
        self.assertEqual(q["prezzo_guest_cents"], 20000)    # soggiorno pulito
        self.assertEqual(q["totale_cents"], 20800)          # quello che paga DAVVERO l'ospite
        self.assertEqual(self.sis.catalogo.dettaglio("casa")["tassa_pp_notte_cents"], 200)

    def test_citta_senza_regola_tassa_zero(self):
        self._pubblica()                                    # nessuna tassa dichiarata
        q = self._quote()
        self.assertEqual(q["tassa_soggiorno_cents"], 0)     # mai inventare
        self.assertEqual(q["totale_cents"], q["prezzo_guest_cents"])

    def test_pagamento_addebita_il_totale_con_tassa(self):
        # il book riporta totale_cents (= soggiorno + tassa): e' quello che Stripe addebita
        self._pubblica(tassa_pp_notte_cents=200)
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa",
                      "check_in": _fra(20), "check_out": _fra(22), "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "o@x.it"})
        self.assertEqual(b["totale_cents"], 20800)            # 20000 soggiorno + 800 tassa
        self.assertEqual(b["tassa_soggiorno_cents"], 800)

    def test_cancellazione_rimborsa_anche_la_tassa(self):
        self._pubblica(tassa_pp_notte_cents=200)              # flessibile (default) + tassa
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa",
                      "check_in": _fra(20), "check_out": _fra(22), "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "o@x.it"})
        _, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": b["voucher_token"]})
        self.assertEqual(c["tassa_rimborsata_cents"], 800)    # tassa SEMPRE resa per intero
        self.assertEqual(c["rimborso_cents"], 20800)          # soggiorno pieno (flessibile) + tassa

    def test_cap_notti_tassabili(self):
        self._pubblica(tassa_pp_notte_cents=200, tassa_max_notti=1)   # max 1 notte
        q = self._quote(party=2)
        self.assertEqual(q["tassa_soggiorno_cents"], 400)   # 200*2persone*1notte (cap)

    def test_regola_tassa_di_default_zero(self):
        from fase66_tassa_soggiorno import REGOLA_ZERO
        self.assertIs(self.sis.catalogo.regola_tassa_di("inesistente"), REGOLA_ZERO)

    # ── UN VALORE DI TASSA NON VALIDO NON PUO' COSTARE SOLDI IN SILENZIO ──────────
    # Criterio scritto in REGISTRO_INGEGNERIA §2-bis: *«nessun difetto puo' costare soldi
    # in silenzio -- o viene impedito, o GRIDA»*. Qui era l'esatto contrario.
    #
    # MISURATO SULLA CATENA VERA il 2026-08-12 (pubblica -> disponibilita' -> preventivo,
    # 30 notti, 2 ospiti, tassa 350 cents a persona/notte):
    #     host scrive 7 (corretto)  -> pubblica 201 -> nel db 7    -> tassa  4900
    #     host scrive -1 (refuso)   -> pubblica 201 -> nel db 0    -> tassa 21000
    #     host scrive 7.5           -> pubblica 201 -> nel db 0    -> tassa 21000
    # Cioe' +16100 cents (161,00 EUR) addebitati all'ospite per un refuso, e `pubblica` che
    # risponde 201: l'host non riceve NESSUN avviso.
    #
    # ⛔ LA CATENA DEL DIFETTO, ed e' il motivo per cui la riparazione in `fase66` NON basta:
    #   `_tax()` schiaccia qualunque valore invalido su **0** -> ma nella tabella `alloggi`
    #   `0` e' anche il DEFAULT e significa **«nessun tetto»** (`fase57.regola_tassa_di`:
    #   `mx if mx > 0 else None`, e l'oracolo indipendente di `test_happy_conti` dice lo
    #   stesso). Quindi `fase66` riceve un `None` **legittimo** e non puo' piu' accorgersi
    #   di niente: il passaggio ha CANCELLATO LA PROVA. Un invalido diventa
    #   indistinguibile da un «non l'ho impostato», e «non l'ho impostato» e' la lettura
    #   piu' cara per l'ospite.
    #
    # ⚠️ E QUESTE GUARDIE NASCONO DA UN MIO ERRORE, scritto qui perche' non si ripeta: il
    # 2026-08-12 avevo concluso che questa porta fosse «gia' chiusa a monte» perche' `_tax`
    # azzera i negativi, e avevo scritto quella conclusione in due documenti. Era falsa:
    # azzerare NON e' chiudere, quando lo zero significa «nessun limite». L'ha smentita
    # l'E2E sulla catena vera, non un ragionamento -- ed e' esattamente il livello di
    # collaudo che stavo per saltare.

    def _pubblica_stato(self, **tax):
        body = {"host_id": "demo", "slug": "casa-v", "titolo": "Casa V", "citta": "Roma",
                "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 4,
                "servizi": [], "immagini": []}
        body.update(tax)
        return self.g("POST", "/api/host/pubblica", body, HK)

    def test_un_cap_notti_NEGATIVO_viene_RIFIUTATO_al_momento_di_pubblicare(self):
        stato, corpo = self._pubblica_stato(tassa_pp_notte_cents=350, tassa_max_notti=-1)
        self.assertEqual(422, stato,
                         "pubblicare con un tetto notti negativo risponde %s: il valore "
                         "viene azzerato in silenzio, diventa «nessun tetto» e l'ospite "
                         "paga la tassa su TUTTE le notti" % stato)
        self.assertEqual("tassa_max_notti_non_valido", corpo.get("dettaglio"),
                         "il rifiuto deve dire QUALE campo, se no l'host non sa cosa "
                         "correggere e il messaggio non e' un aiuto")

    def test_un_cap_notti_NON_INTERO_viene_RIFIUTATO(self):
        stato, _ = self._pubblica_stato(tassa_pp_notte_cents=350, tassa_max_notti=7.5)
        self.assertEqual(422, stato)

    def test_una_tassa_per_persona_NEGATIVA_viene_RIFIUTATA(self):
        stato, corpo = self._pubblica_stato(tassa_pp_notte_cents=-350)
        self.assertEqual(422, stato)
        self.assertEqual("tassa_pp_notte_cents_non_valido", corpo.get("dettaglio"))

    def test_uno_SCONTO_fuori_scala_viene_RIFIUTATO(self):
        """Stessa forma, stessa direzione: uno sconto invalido diventava 0, cioe' NESSUNO
        sconto, e l'ospite pagava piu' di quanto l'host voleva offrire."""
        stato, corpo = self._pubblica_stato(sconto_settimana_bps=9500)   # 95%, oltre il tetto
        self.assertEqual(422, stato)
        self.assertEqual("sconto_settimana_bps_non_valido", corpo.get("dettaglio"))

    def test_I_VALORI_BUONI_PASSANO_e_il_conto_e_quello_giusto(self):
        """⛔ IL RAMO CHE DEVE TACERE (regola ferrea 10), e con l'osservabile sui SOLDI.

        Una riparazione che rifiuta tutto sarebbe peggio del difetto: qui si pretende che
        la strada buona resti aperta E che il numero addebitato sia ancora quello esatto.
        """
        stato, _ = self._pubblica_stato(tassa_pp_notte_cents=350, tassa_max_notti=7)
        self.assertEqual(201, stato)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa-v",
                "da": "2027-01-01", "a": "2027-03-01", "unita_totali": 1,
                "prezzo_netto_cents": 10000}, HK)
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa-v",
                      "check_in": "2027-01-10", "check_out": "2027-02-09", "party": 2})
        self.assertEqual(350 * 7 * 2, q["tassa_soggiorno_cents"])   # 30 notti, cap 7

    def test_ASSENTE_resta_legittimo_e_significa_nessuna_tassa(self):
        """`0`, il campo omesso e `null` sono «non impostato»: restano validi.
        Se la riparazione li rifiutasse, nessun host potrebbe piu' pubblicare senza tassa."""
        for tax in ({}, {"tassa_max_notti": 0}, {"tassa_max_notti": None}):
            stato, _ = self._pubblica_stato(**tax)
            self.assertEqual(201, stato, "rifiutato un annuncio SENZA tassa (%r)" % tax)

    def test_like_for_like_valuta_dellannuncio(self):
        # l'host prezza in USD -> il preventivo (e l'addebito) e' in USD -> zero rischio cambio
        self._pubblica(valuta="USD")
        q = self._quote()
        self.assertEqual(q["valuta"], "USD")
        # annuncio EUR (default) -> preventivo EUR
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "casa2",
                "titolo": "C2", "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 9000,
                "capacita": 2, "servizi": [], "immagini": [], "valuta": "EUR"}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa2",
                "da": _fra(1), "a": _fra(60), "unita_totali": 1,
                "prezzo_netto_cents": 9000}, HK)
        _, q2 = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa2",
                       "check_in": _fra(20), "check_out": _fra(22), "party": 1})
        self.assertEqual(q2["valuta"], "EUR")


if __name__ == "__main__":
    unittest.main()
