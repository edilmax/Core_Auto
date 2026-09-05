"""
Test Fase 203 - l'orologio dell'iCal: la difesa dal RITARDO dei calendari esterni.

Copre: URL (solo https, niente spazi, tetto di lunghezza), archivio dei feed (salva
idempotente, rimuovi, elenco, esiti ed errori di fila), rilettura con orologio e rete
INIETTATI (recente / ok / errore), la riga di registro con l'ora esatta e SENZA l'URL intero,
un feed rotto per un'ora che diventa anomalia, il giro periodico, la rilettura prima della
conferma (fail-open sulla rete), l'archivio accanto all'inventario, e «mai solleva».
"""
import os
import shutil
import tempfile
import unittest

from fase58_channel_manager import crea_channel_manager
from fase203_ical_orologio import (
    ERRORI_PER_ALLARME, MARCA, MARCA_ROTTO, MAX_BYTES, RILETTURA_CONFERMA_SEC, RILETTURA_SEC,
    ArchivioFeed, anomalie, archivio_di, crea_archivio_feed, giro_periodico,
    prima_di_confermare, rileggi, scarica, url_breve, url_valido,
)

URL = "https://www.airbnb.com/calendar/ical/123456.ics?s=segreto0123abcd"
ICS_1 = ("BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nDTSTART;VALUE=DATE:20260701\n"
         "DTEND;VALUE=DATE:20260703\nSUMMARY:Reserved\nEND:VEVENT\nEND:VCALENDAR\n")
ICS_2 = ICS_1.replace("END:VCALENDAR", "BEGIN:VEVENT\nDTSTART;VALUE=DATE:20260710\n"
                      "DTEND;VALUE=DATE:20260712\nEND:VEVENT\nEND:VCALENDAR")
T0 = 1_700_000_000


class _Config:
    def __init__(self, db_inventario=":memory:"):
        self.db_inventario = db_inventario


class _Sistema:
    def __init__(self, inventario=None, db_inventario=":memory:"):
        self.inventario = inventario
        self.config = _Config(db_inventario)


def _rete(testi):
    """Una rete finta: `testi` e' una lista di risposte in ordine (str o eccezione)."""
    chiamate = []

    def fetch(url, timeout):
        chiamate.append((url, timeout))
        r = testi[min(len(chiamate) - 1, len(testi) - 1)]
        if isinstance(r, Exception):
            raise r
        return r
    return chiamate, fetch


class TestUrl(unittest.TestCase):
    def test_solo_https_senza_spazi_e_con_un_tetto(self):
        self.assertTrue(url_valido(URL))
        self.assertFalse(url_valido("http://www.airbnb.com/calendar/ical/1.ics"))
        self.assertFalse(url_valido("https://www.airbnb.com/cal endar.ics"))
        self.assertFalse(url_valido("https://www.airbnb.com/a\nb.ics"))
        self.assertFalse(url_valido("https://" + "a" * 3000))
        self.assertFalse(url_valido(None))
        self.assertFalse(url_valido(123))
        self.assertFalse(url_valido("https://"))

    def test_l_url_breve_dice_l_host_e_non_il_segreto(self):
        breve = url_breve(URL)
        self.assertIn("www.airbnb.com", breve)
        self.assertNotIn("segreto0123abcd", breve)
        self.assertNotEqual(url_breve(URL), url_breve(URL + "x"))

    def test_scarica_rifiuta_un_url_non_https_prima_di_toccare_la_rete(self):
        chiamate, fetch = _rete([ICS_1])
        with self.assertRaises(ValueError):
            scarica("http://www.airbnb.com/1.ics", timeout=1, fetch=fetch)
        self.assertEqual(chiamate, [])

    def test_scarica_rifiuta_un_feed_troppo_grande(self):
        _c, fetch = _rete(["x" * (MAX_BYTES + 1)])
        with self.assertRaises(ValueError):
            scarica(URL, timeout=1, fetch=fetch)


class TestArchivio(unittest.TestCase):
    def setUp(self):
        self.a = crea_archivio_feed()

    def test_salva_idempotente_ed_elenco(self):
        self.assertTrue(self.a.salva("casa", URL, ora_ts=T0))
        self.assertTrue(self.a.salva("casa", URL, ora_ts=T0 + 5))
        self.assertEqual(len(self.a.elenco("casa")), 1)
        self.assertEqual(self.a.elenco("casa")[0]["creato_ts"], T0)
        self.assertTrue(self.a.salva("casa", URL + "&b=2", ora_ts=T0))
        self.assertEqual(len(self.a.elenco("casa")), 2)
        self.assertEqual(self.a.elenco("altra"), [])
        self.assertEqual(len(self.a.elenco()), 2)

    def test_input_invalidi_rifiutati(self):
        self.assertFalse(self.a.salva("", URL))
        self.assertFalse(self.a.salva("casa", "http://x.y/1.ics"))
        self.assertFalse(self.a.salva(None, URL))
        self.assertEqual(self.a.elenco(), [])

    def test_rimuovi(self):
        self.a.salva("casa", URL)
        self.assertTrue(self.a.rimuovi("casa", URL))
        self.assertFalse(self.a.rimuovi("casa", URL))
        self.assertFalse(self.a.rimuovi(None, URL))
        self.assertEqual(self.a.elenco("casa"), [])

    def test_gli_errori_di_fila_salgono_e_tornano_a_zero_con_una_lettura_buona(self):
        self.a.salva("casa", URL)
        self.assertEqual(self.a.registra_esito("casa", URL, ora_ts=T0, ok=False, dettaglio="e"), 1)
        self.assertEqual(self.a.registra_esito("casa", URL, ora_ts=T0, ok=False, dettaglio="e"), 2)
        f = self.a.elenco("casa")[0]
        self.assertEqual((f["letture"], f["errori_di_fila"], f["ultima_lettura_ts"]), (2, 2, 0))
        self.assertEqual(self.a.registra_esito("casa", URL, ora_ts=T0 + 9, ok=True,
                                               dettaglio="ok"), 0)
        f = self.a.elenco("casa")[0]
        self.assertEqual((f["letture"], f["errori_di_fila"], f["ultima_lettura_ts"],
                          f["ultimo_tentativo_ts"]), (3, 0, T0 + 9, T0 + 9))


class TestRilettura(unittest.TestCase):
    def setUp(self):
        self.inv = crea_channel_manager()
        for g in ("2026-07-01", "2026-07-02", "2026-07-10", "2026-07-11"):
            self.inv.imposta_disponibilita("casa", g, unita_totali=1, prezzo_netto_cents=10000)
        self.a = crea_archivio_feed()
        self.a.salva("casa", URL, ora_ts=T0)

    def test_la_prima_lettura_blocca_le_notti_dell_ota(self):
        chiamate, fetch = _rete([ICS_1])
        esiti = rileggi(self.a, self.inv, "casa", ora_ts=T0, eta_massima_sec=0, fetch=fetch)
        self.assertEqual(esiti[0]["esito"], "ok")
        self.assertEqual(esiti[0]["giorni_bloccati"], 2)
        self.assertEqual(self.inv.stato_giorno("casa", "2026-07-01")["unita_totali"], 0)
        self.assertEqual(self.inv.stato_giorno("casa", "2026-07-10")["unita_totali"], 1)
        self.assertEqual(chiamate[0][0], URL)

    def test_una_lettura_recente_non_tocca_la_rete(self):
        chiamate, fetch = _rete([ICS_1])
        rileggi(self.a, self.inv, "casa", ora_ts=T0, eta_massima_sec=0, fetch=fetch)
        esiti = rileggi(self.a, self.inv, "casa", ora_ts=T0 + RILETTURA_SEC - 1,
                        eta_massima_sec=RILETTURA_SEC, fetch=fetch)
        self.assertEqual(esiti[0]["esito"], "recente")
        self.assertEqual(len(chiamate), 1)

    def test_dopo_l_intervallo_rilegge_e_prende_le_notti_nuove(self):
        chiamate, fetch = _rete([ICS_1, ICS_2])
        rileggi(self.a, self.inv, "casa", ora_ts=T0, eta_massima_sec=0, fetch=fetch)
        esiti = rileggi(self.a, self.inv, "casa", ora_ts=T0 + RILETTURA_SEC,
                        eta_massima_sec=RILETTURA_SEC, fetch=fetch)
        self.assertEqual(esiti[0]["esito"], "ok")
        self.assertEqual(esiti[0]["eventi"], 2)
        self.assertEqual(self.inv.stato_giorno("casa", "2026-07-10")["unita_totali"], 0)
        self.assertEqual(len(chiamate), 2)

    def test_la_riga_di_registro_porta_l_ora_esatta_e_non_l_url_intero(self):
        _c, fetch = _rete([ICS_1])
        with self.assertLogs("core_auto.ical_orologio", level="INFO") as registro:
            rileggi(self.a, self.inv, "casa", ora_ts=T0, eta_massima_sec=0, fetch=fetch,
                    motivo="prova")
        riga = registro.output[0]
        self.assertIn(MARCA, riga)
        self.assertIn("alloggio=casa", riga)
        self.assertIn("giorni_bloccati=2", riga)
        self.assertIn("motivo=prova", riga)
        self.assertIn(url_breve(URL), riga)
        self.assertNotIn("segreto0123abcd", riga)
        import datetime
        self.assertIn(datetime.datetime.fromtimestamp(T0).isoformat(timespec="seconds"), riga)

    def test_un_errore_di_rete_e_un_esito_scritto_e_dopo_un_ora_diventa_anomalia(self):
        sis = _Sistema(self.inv)
        sis.ical_feed = self.a
        _c, fetch = _rete([RuntimeError("timeout: " + URL)])
        ora = T0
        for i in range(1, ERRORI_PER_ALLARME + 1):
            with self.assertLogs("core_auto.ical_orologio", level="WARNING") as registro:
                esiti = rileggi(self.a, self.inv, "casa", ora_ts=ora, eta_massima_sec=0,
                                fetch=fetch)
            self.assertEqual(esiti[0]["esito"], "errore")
            self.assertEqual(esiti[0]["errori_di_fila"], i)
            self.assertNotIn("segreto0123abcd", "\n".join(registro.output))
            self.assertIn("RuntimeError", registro.output[0])
            if i < ERRORI_PER_ALLARME:
                self.assertEqual(anomalie(sis), [])
                self.assertFalse(any(MARCA_ROTTO in r for r in registro.output))
            ora += RILETTURA_SEC
        self.assertTrue(any(MARCA_ROTTO in r for r in registro.output))
        self.assertEqual(len(anomalie(sis)), 1)
        self.assertIn("casa", anomalie(sis)[0])
        # una lettura buona azzera il conto e spegne l'anomalia
        _c2, fetch_ok = _rete([ICS_1])
        rileggi(self.a, self.inv, "casa", ora_ts=ora, eta_massima_sec=0, fetch=fetch_ok)
        self.assertEqual(anomalie(sis), [])

    def test_l_inventario_che_rifiuta_non_e_un_errore_del_feed(self):
        # una notte gia' occupata da noi non scende sotto l'occupato (fase58 fail-safe): il
        # feed e' letto, il giorno non viene contato fra i bloccati, niente errore.
        self.inv.blocca("casa", "2026-07-01", "2026-07-02", idem_key="nostra")
        _c, fetch = _rete([ICS_1])
        esiti = rileggi(self.a, self.inv, "casa", ora_ts=T0, eta_massima_sec=0, fetch=fetch)
        self.assertEqual(esiti[0]["esito"], "ok")
        self.assertEqual(esiti[0]["giorni_bloccati"], 1)


class TestGiroEConferma(unittest.TestCase):
    def setUp(self):
        self.inv = crea_channel_manager()
        for g in ("2026-07-01", "2026-07-02", "2026-07-10", "2026-07-11"):
            for allog in ("casa", "villa"):
                self.inv.imposta_disponibilita(allog, g, unita_totali=1,
                                               prezzo_netto_cents=10000)
        self.sis = _Sistema(self.inv)
        self.a = archivio_di(self.sis)
        self.a.salva("casa", URL, ora_ts=T0)
        self.a.salva("villa", URL.replace("123456", "654321"), ora_ts=T0)

    def test_l_archivio_resta_agganciato_al_sistema(self):
        self.assertIs(archivio_di(self.sis), self.a)
        self.assertIsInstance(self.sis.ical_feed, ArchivioFeed)

    def test_il_giro_periodico_conta_letti_ed_errori_e_non_solleva(self):
        def fetch(url, timeout):
            if "654321" in url:
                raise TimeoutError("giu'")
            return ICS_1
        c = giro_periodico(self.sis, ora_ts=T0 + RILETTURA_SEC, fetch=fetch)
        self.assertEqual(c, {"feed": 2, "letti": 1, "errori": 1, "recenti": 0})
        c2 = giro_periodico(self.sis, ora_ts=T0 + RILETTURA_SEC + 1, fetch=fetch)
        self.assertEqual(c2["recenti"], 2)

    def test_prima_di_confermare_rilegge_solo_se_l_ultimo_tentativo_ha_un_minuto(self):
        chiamate, fetch = _rete([ICS_1, ICS_2])
        prima_di_confermare(self.sis, "casa", ora_ts=T0, fetch=fetch)
        self.assertEqual(len(chiamate), 1)
        esiti = prima_di_confermare(self.sis, "casa", ora_ts=T0 + RILETTURA_CONFERMA_SEC - 1,
                                    fetch=fetch)
        self.assertEqual(esiti[0]["esito"], "recente")
        self.assertEqual(len(chiamate), 1)
        esiti = prima_di_confermare(self.sis, "casa", ora_ts=T0 + RILETTURA_CONFERMA_SEC,
                                    fetch=fetch)
        self.assertEqual(esiti[0]["esito"], "ok")
        self.assertEqual(self.inv.stato_giorno("casa", "2026-07-10")["unita_totali"], 0)

    def test_prima_di_confermare_e_fail_open_sulla_rete(self):
        _c, fetch = _rete([ICS_1, TimeoutError("giu'")])
        prima_di_confermare(self.sis, "casa", ora_ts=T0, fetch=fetch)
        esiti = prima_di_confermare(self.sis, "casa", ora_ts=T0 + 3600, fetch=fetch)
        self.assertEqual(esiti[0]["esito"], "errore")
        # le notti bloccate dalla lettura buona restano bloccate
        self.assertEqual(self.inv.stato_giorno("casa", "2026-07-01")["unita_totali"], 0)

    def test_prima_di_confermare_senza_feed_non_fa_niente(self):
        chiamate, fetch = _rete([ICS_1])
        self.assertEqual(prima_di_confermare(self.sis, "senza_feed", ora_ts=T0, fetch=fetch), [])
        self.assertEqual(prima_di_confermare(self.sis, "", ora_ts=T0, fetch=fetch), [])
        self.assertEqual(chiamate, [])

    def test_l_archivio_su_file_nasce_accanto_all_inventario(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        inv_path = os.path.join(d, "inventario.db")
        sis = _Sistema(crea_channel_manager(inv_path), db_inventario=inv_path)
        a = archivio_di(sis)
        a.salva("casa", URL, ora_ts=T0)
        self.assertTrue(os.path.exists(os.path.join(d, "ical_feed.db")))
        # un secondo sistema sulla stessa cartella rilegge lo stesso archivio (durevole)
        sis2 = _Sistema(crea_channel_manager(inv_path), db_inventario=inv_path)
        self.assertEqual(len(archivio_di(sis2).elenco("casa")), 1)

    def test_i_feed_rotti_entrano_nel_rapporto_del_guardiano(self):
        from fase203_ical_orologio import CHIAVE_ANOMALIA, con_feed_rotti
        rapporto = {"pulito": True, "conta": 0, "anomalie": {}}
        self.assertTrue(con_feed_rotti(dict(rapporto), self.sis)["pulito"])
        _c, fetch = _rete([TimeoutError("giu'")])
        ora = T0
        for _ in range(ERRORI_PER_ALLARME):
            rileggi(self.a, self.inv, "casa", ora_ts=ora, eta_massima_sec=0, fetch=fetch)
            ora += RILETTURA_SEC
        arricchito = con_feed_rotti(dict(rapporto), self.sis)
        self.assertFalse(arricchito["pulito"])
        self.assertEqual(arricchito["conta"], 1)
        self.assertEqual(len(arricchito["anomalie"][CHIAVE_ANOMALIA]), 1)

    def test_i_ganci_orologio_e_rete_del_modulo_valgono_quando_nessuno_passa_i_suoi(self):
        import fase203_ical_orologio as m
        chiamate, fetch = _rete([ICS_1])
        vecchi = (m.OROLOGIO, m.RETE)
        m.OROLOGIO, m.RETE = (lambda: T0 + 5), fetch
        try:
            esiti = prima_di_confermare(self.sis, "casa")
        finally:
            m.OROLOGIO, m.RETE = vecchi
        self.assertEqual(esiti[0]["esito"], "ok")
        self.assertEqual(self.a.elenco("casa")[0]["ultima_lettura_ts"], T0 + 5)
        self.assertEqual(len(chiamate), 1)

    def test_mai_solleva_su_un_sistema_monco(self):
        class Monco:
            pass
        for sis in (Monco(), _Sistema(None), _Sistema(self.inv, db_inventario="")):
            try:
                giro_periodico(sis, ora_ts=T0)
                prima_di_confermare(sis, "casa", ora_ts=T0)
                anomalie(sis)
            except Exception as e:  # pragma: no cover
                self.fail("sollevato su %r: %s" % (type(sis).__name__, e))


class TestLeGuardieDeiPuntiScoperti(unittest.TestCase):
    """Una guardia per ogni punto che il Giudice della mutazione ha trovato SCOPERTO col
    solo occhio dedicato (2026-09-05, primo giro su fase203: 16 punti su 48). Ogni test
    dice quale riga difende."""

    def test_i_confini_della_lunghezza_dell_url_sono_inclusi(self):
        # riga 85: `len < 12` e `len > MAX_URL` -- 12 e MAX_URL caratteri sono validi.
        from fase203_ical_orologio import MAX_URL
        self.assertTrue(url_valido("https://a.io"))                      # 12 caratteri esatti
        self.assertFalse(url_valido("https://a.i"))
        giusto = "https://x.io/" + "a" * (MAX_URL - 13)
        self.assertEqual(len(giusto), MAX_URL)
        self.assertTrue(url_valido(giusto))
        self.assertFalse(url_valido(giusto + "a"))

    def test_un_url_che_urlsplit_rifiuta_non_e_valido(self):
        # riga 92: il ramo `except ValueError` risponde False (un IPv6 malformato).
        self.assertFalse(url_valido("https://[::1"))

    def test_un_feed_grande_esattamente_quanto_il_tetto_passa(self):
        # riga 134: `len(testo) > MAX_BYTES` -- il tetto e' incluso.
        _c, fetch = _rete(["x" * MAX_BYTES])
        self.assertEqual(len(scarica(URL, timeout=1, fetch=fetch)), MAX_BYTES)

    def test_rimuovi_con_un_identificativo_non_testuale_dice_no_senza_sollevare(self):
        # riga 191: `not isinstance(a, str) OR not isinstance(url, str)` -- con `and` una lista
        # arriverebbe al database e solleverebbe.
        a = crea_archivio_feed()
        a.salva("casa", URL)
        self.assertFalse(a.rimuovi(["casa"], URL))
        self.assertFalse(a.rimuovi("casa", ["x"]))
        self.assertEqual(len(a.elenco("casa")), 1)

    def test_un_sistema_che_rifiuta_l_aggancio_lascia_la_traccia(self):
        # riga 308: `exc_info=True` quando il sistema non accetta l'attributo.
        class Rigido:
            __slots__ = ("inventario", "config")

            def __init__(self, inv):
                self.inventario = inv
                self.config = _Config()
        sis = Rigido(crea_channel_manager())
        with self.assertLogs("core_auto.ical_orologio", level="WARNING") as registro:
            a = archivio_di(sis)
        self.assertIsInstance(a, ArchivioFeed)
        traccia = registro.records[0].exc_info
        self.assertIsInstance(traccia, tuple)
        self.assertIs(traccia[0], AttributeError)

    def _sistema_con_archivio_impossibile(self):
        # `db_inventario` in una cartella che non esiste: l'archivio non si puo' creare.
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return _Sistema(crea_channel_manager(),
                        db_inventario=os.path.join(d, "non_esiste", "inventario.db"))

    def test_il_giro_periodico_che_esplode_lascia_la_traccia(self):
        # riga 332: `exc_info=True`.
        sis = self._sistema_con_archivio_impossibile()
        with self.assertLogs("core_auto.ical_orologio", level="ERROR") as registro:
            c = giro_periodico(sis, ora_ts=T0)
        self.assertEqual(c, {"feed": 0, "letti": 0, "errori": 0, "recenti": 0})
        self.assertIsInstance(registro.records[0].exc_info, tuple)

    def test_prima_di_confermare_rifiuta_un_alloggio_non_testuale_o_un_sistema_senza_inventario(self):
        # riga 344: `inv is None OR not isinstance(alloggio, str) OR not alloggio` -> [].
        inv = crea_channel_manager()
        for g in ("2026-07-01", "2026-07-02"):
            inv.imposta_disponibilita("123", g, unita_totali=1, prezzo_netto_cents=100)
        sis = _Sistema(inv)
        a = archivio_di(sis)
        a.salva("123", URL, ora_ts=T0)
        chiamate, fetch = _rete([ICS_1])
        self.assertEqual(prima_di_confermare(sis, 123, ora_ts=T0 + 3600, fetch=fetch), [])
        senza_inventario = _Sistema(None)
        senza_inventario.ical_feed = a
        self.assertEqual(prima_di_confermare(senza_inventario, "123", ora_ts=T0 + 3600,
                                             fetch=fetch), [])
        self.assertEqual(chiamate, [])

    def test_prima_di_confermare_che_esplode_lascia_la_traccia(self):
        # riga 352: `exc_info=True`.
        sis = self._sistema_con_archivio_impossibile()
        with self.assertLogs("core_auto.ical_orologio", level="ERROR") as registro:
            self.assertEqual(prima_di_confermare(sis, "casa", ora_ts=T0), [])
        self.assertIsInstance(registro.records[0].exc_info, tuple)

    def test_i_feed_rotti_si_sommano_al_conto_del_rapporto_e_ne_dicono_il_numero_e_l_esito(self):
        # righe 365, 380, 381: `conta` si somma (non si azzera); l'anomalia dice QUANTE letture
        # sono fallite e l'ULTIMO esito.
        from fase203_ical_orologio import CHIAVE_ANOMALIA, con_feed_rotti
        inv = crea_channel_manager()
        sis = _Sistema(inv)
        a = archivio_di(sis)
        a.salva("casa", URL, ora_ts=T0)
        _c, fetch = _rete([TimeoutError("giu'")])
        ora = T0
        for _ in range(ERRORI_PER_ALLARME):
            rileggi(a, inv, "casa", ora_ts=ora, eta_massima_sec=0, fetch=fetch)
            ora += RILETTURA_SEC
        rap = con_feed_rotti({"pulito": True, "conta": 5, "anomalie": {}}, sis)
        self.assertEqual(rap["conta"], 6)
        testo = rap["anomalie"][CHIAVE_ANOMALIA][0]
        self.assertIn("%d letture fallite" % ERRORI_PER_ALLARME, testo)
        self.assertIn("TimeoutError", testo)

    def test_un_rapporto_che_non_si_lascia_scrivere_lascia_la_traccia_e_lo_dice(self):
        # riga 368: `exc_info=True`, e il rapporto dice che il controllo non e' stato eseguito.
        from fase203_ical_orologio import con_feed_rotti

        class RapportoRigido(dict):
            def __setitem__(self, k, v):
                raise RuntimeError("sola lettura")
        inv = crea_channel_manager()
        sis = _Sistema(inv)
        a = archivio_di(sis)
        a.salva("casa", URL, ora_ts=T0)
        _c, fetch = _rete([TimeoutError("giu'")])
        ora = T0
        for _ in range(ERRORI_PER_ALLARME):
            rileggi(a, inv, "casa", ora_ts=ora, eta_massima_sec=0, fetch=fetch)
            ora += RILETTURA_SEC
        rap = RapportoRigido()
        with self.assertLogs("core_auto.ical_orologio", level="ERROR") as registro:
            con_feed_rotti(rap, sis)
        self.assertIsInstance(registro.records[0].exc_info, tuple)
        self.assertTrue(any("feed rotti" in r for r in rap.get("non_eseguiti", [])))

    def test_un_archivio_illeggibile_e_un_anomalia_dichiarata_con_la_traccia(self):
        # riga 385: `exc_info=True`.
        sis = self._sistema_con_archivio_impossibile()
        with self.assertLogs("core_auto.ical_orologio", level="ERROR") as registro:
            rotti = anomalie(sis)
        self.assertEqual(len(rotti), 1)
        self.assertIn("illeggibile", rotti[0])
        self.assertIsInstance(registro.records[0].exc_info, tuple)

    def test_l_archivio_in_memoria_si_usa_da_un_altro_thread(self):
        # riga 414: `check_same_thread=False` -- il server e' a thread.
        import threading
        a = crea_archivio_feed()
        esiti = []

        def lavoro():
            try:
                esiti.append(a.salva("casa", URL, ora_ts=T0))
                esiti.append(len(a.elenco("casa")))
            except Exception as e:  # pragma: no cover
                esiti.append(repr(e))

        t = threading.Thread(target=lavoro)
        t.start()
        t.join()
        self.assertEqual(esiti, [True, 1])


if __name__ == "__main__":
    unittest.main()
