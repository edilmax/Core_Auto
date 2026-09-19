"""IL CALENDARIO NON HA PAURA DEL 29 FEBBRAIO (Tappa 6 della mappa di blindatura).

Il 29 febbraio e' il giorno che i software sbagliano piu' volentieri: esiste UN anno sì
e UN anno no, le notti che lo attraversano si contano male se qualcuno «costruisce» le
date con aritmetica a 365 giorni, e i feed OTA (iCal) lo scrivono come una data a se
stessa. Qui si prova che il motore lo tratta come quello che e' -- un giorno qualunque --
in TUTTI i posti dove passa:

  1. il 29/2/2028 ESISTE: 27/02->01/03 sono TRE notti e il totale e' tre volte il prezzo;
  2. il 2027 NON lo ha: la stessa finestra sono DUE notti, e 28/02->01/03 e' UNA;
  3. il blocco atomico delle notti attraversa il 29 (prenotato 28/02->01/03 = anche il 29
     occupato: il secondo preventivo sulla stessa finestra e' 409, il 27/02->28/02 resta libero);
  4. l'iCal esporta una prenotazione DI SOLA NOTTE 29/02 (DTSTART 20280229) e l'import di
     un feed che copre il 29 chiude davvero quel giorno (quote -> 409), senza toccare il 27;
  5. il weekend del CAMBIO D'ORA (24->26 ottobre 2026, notte da 25 ore) si quota due notti
     esatte: il calendario conta GIORNI, non ore.

Le date qui dentro sono FISSE e futuri-protette per costruzione (2027/2028 sono oltre ogni
orizzonte di scadenza del banco): e' la stessa scelta di test_ical_export (data fissa non
adiacente, difetto del 2026-07-16).
"""
import datetime
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

PREZZO = 15000       # centesimi/notte, senza tasse ne' sconti: totale = notti x PREZZO
CIN = "IT058091C2X5V0ABCD"


class TestIlCalendarioNonHaPauraDel29(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp(prefix="bisestile_")
        cfg = ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"B" * 32, con_registrazione_host=True,
            db_catalogo=cls.d + "/c.db", db_inventario=cls.d + "/i.db",
            db_registro_host=cls.d + "/r.db", db_accettazioni=cls.d + "/a.db",
            db_pendenti=cls.d + "/p.db", db_payout=cls.d + "/po.db",
            db_finanza=cls.d + "/f.db", db_garanzia=cls.d + "/g.db",
            db_tassa_comunale=cls.d + "/t.db", valuta="EUR")
        cls.r = crea_router(crea_sistema(cfg), host_key="hk", admin_key="ak")

        def g(m, p, b=None, h=None, q=None):
            return cls.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

        # ⛔ staticmethod: senza, self.g("POST", ...) inietta self come PRIMO argomento
        #   e la rotta diventa "POST" -> rotta_non_trovata su ogni chiamata dei test.
        cls.g = staticmethod(g)
        s, c = g("POST", "/api/host/registrazione",
                 {"email": "host@bisestile.it", "password": "password1",
                  "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
                  "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        if s != 201:
            raise AssertionError("registrazione host: %s %r" % (s, c))
        cls.tok = c["token"]
        # TRE annunci, stesso prezzo: "casa" per quote+notte-29, "seconda" per l'import,
        # "terza" a UNA unita' per la prova del blocco (una prenotazione esaurisce tutto)
        for slug, titolo in (("casa", "Casa Bisestile"), ("seconda", "Casa Import"),
                             ("terza", "Casa Sola")):
            s, c = g("POST", "/api/host/pubblica",
                     {"slug": slug, "titolo": titolo, "citta": "Roma", "paese": "IT",
                      "cin": CIN, "prezzo_notte_cents": PREZZO, "capacita": 4},
                     {"X-Host-Token": cls.tok})
            if s != 201:
                raise AssertionError("pubblica %s: %s %r" % (slug, s, c))
        # tre finestre aperte su "casa": cambio d'ora 2026, anno intero 2027, primo semestre 2028
        for da, a in (("2026-10-01", "2026-12-31"), ("2027-01-01", "2027-12-31"),
                      ("2028-01-01", "2028-06-30")):
            s, c = g("POST", "/api/host/disponibilita_range",
                     {"alloggio_id": "casa", "da": da, "a": a,
                      "unita_totali": 2, "prezzo_netto_cents": PREZZO},
                     {"X-Host-Token": cls.tok})
            if s != 200:
                raise AssertionError("disponibilita %s-%s: %s %r" % (da, a, s, c))
        for alloggio in ("seconda", "terza"):
            s, c = g("POST", "/api/host/disponibilita_range",
                     {"alloggio_id": alloggio, "da": "2028-01-01", "a": "2028-06-30",
                      "unita_totali": 1, "prezzo_netto_cents": PREZZO},
                     {"X-Host-Token": cls.tok})
            if s != 200:
                raise AssertionError("disponibilita %s: %s %r" % (alloggio, s, c))
        # la "terza" ha unita' UNA anche nel 2026: l'export mostra i giorni PIENI, e con
        # una sola unita' una prenotazione riempie (misurato: con 2 unita' il giorno resta
        # non-pieno e il feed lo omette, giustamente)
        s, c = g("POST", "/api/host/disponibilita_range",
                 {"alloggio_id": "terza", "da": "2026-10-01", "a": "2026-12-31",
                  "unita_totali": 1, "prezzo_netto_cents": PREZZO},
                 {"X-Host-Token": cls.tok})
        if s != 200:
            raise AssertionError("disponibilita terza 2026: %s %r" % (s, c))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def _quote(self, alloggio, ci, co):
        s, c = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": alloggio, "check_in": ci, "check_out": co, "party": 2})
        return s, c

    def test_il_29_febbraio_2028_esiste_e_si_quota(self):
        """TRE notti per 27/02->01/03/2028, e le due ultime notti per 28/02->01/03: il
        totale e' notti x prezzo ESATTO (nessun cent di sconto o tassa in questo annuncio)."""
        s, c = self._quote("casa", "2028-02-27", "2028-03-01")
        self.assertEqual(200, s, c)
        self.assertEqual(3, c["notti"], "il 29/2/2028 non e' stato contato")
        self.assertEqual(3 * PREZZO, c["totale_cents"])
        s, c = self._quote("casa", "2028-02-28", "2028-03-01")
        self.assertEqual(200, s, c)
        self.assertEqual(2, c["notti"], "dal 28/02 al 01/03 le notti sono 28 e 29")
        self.assertEqual(2 * PREZZO, c["totale_cents"])

    def test_il_2027_non_ha_il_29(self):
        """L'anno NON bisestile non deve avere un 29 fantasma: 27/02->01/03/2027 sono DUE
        notti (27 e 28) e 28/02->01/03 e' UNA. Un contatore a 365/366 fisso le sbaglia."""
        s, c = self._quote("casa", "2027-02-27", "2027-03-01")
        self.assertEqual(200, s, c)
        self.assertEqual(2, c["notti"], "il 29/2/2027 non esiste: le notti sono 27 e 28")
        self.assertEqual(2 * PREZZO, c["totale_cents"])
        s, c = self._quote("casa", "2027-02-28", "2027-03-01")
        self.assertEqual(200, s, c)
        self.assertEqual(1, c["notti"])
        self.assertEqual(PREZZO, c["totale_cents"])

    def test_il_blocco_notti_attraversa_il_29(self):
        """Su un annuncio a UNA unita', una prenotazione 28/02->01/03 occupa ANCHE il 29:
        la stessa finestra riprenotabile e' 409, mentre 27/02->28/02 resta quotabile."""
        s, c = self._quote("terza", "2028-02-28", "2028-03-01")
        self.assertEqual(200, s, c)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": c["quote_token"], "email": "g29@bisestile.it"})
        self.assertEqual(201, s, b)
        s, c2 = self._quote("terza", "2028-02-28", "2028-03-01")
        self.assertEqual(409, s,
                         "il 29/2 prenotato non ha bloccato la finestra: si può ribookare (overbooking)")
        s, c3 = self._quote("terza", "2028-02-27", "2028-02-28")
        self.assertEqual(200, s, c3)

    def test_l_ical_importa_il_29_e_lo_chiude(self):
        """Un feed OTA che copre il 29/2/2028 lo chiude davvero (quote -> 409), senza
        toccare il 27. L'IMPORT non ha finestra: e' la strada con cui una OTA esterna
        scrive un giorno bisestile nel nostro calendario. Il 29 scritto male (o letto
        come 'primo del mese seguente') apre o chiude il giorno sbagliato: qui si vede."""
        feed = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:bisestile-esterno\r\n"
                "DTSTART;VALUE=DATE:20280229\r\nDTEND;VALUE=DATE:20280301\r\n"
                "SUMMARY:OTA esterno\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        s, d = self.g("POST", "/api/host/ical",
                      {"alloggio_id": "seconda", "ical": feed}, {"X-Host-Token": self.tok})
        self.assertEqual(200, s, d)
        s, c2 = self._quote("seconda", "2028-02-29", "2028-03-01")
        self.assertEqual(409, s,
                         "il 29/2 bloccato dal feed esterno resta quotabile (l'import non ha chiuso)")
        s, c3 = self._quote("seconda", "2028-02-27", "2028-02-28")
        self.assertEqual(200, s, "l'import ha chiuso un giorno che non doveva (il 27): %r" % (c3,))

    def test_l_export_mostra_le_notti_entro_la_sua_finestra_di_un_anno(self):
        """L'export dichiara una finestra [oggi, +365] (le OTA guardano un anno: vedi
        `_export_occupati`): una notte prenotata DENTRO la finestra compare nel feed con
        il suo DTSTART. Il 29/2/2028 e' fuori finestra e NON va esportato (misurato:
        feed vuoto, comportamento dichiarato, non difetto) -- per questo l'export del
        bisestile si prova via IMPORT (test sopra), che non ha finestra."""
        tra = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
        fra = (datetime.date.today() + datetime.timedelta(days=32)).isoformat()
        s, c = self._quote("terza", tra, fra)
        self.assertEqual(200, s, c)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": c["quote_token"], "email": "finestra@bisestile.it"})
        self.assertEqual(201, s, b)
        s, d = self.g("GET", "/api/host/ical_link", q={"alloggio": "terza"},
                      h={"X-Host-Token": self.tok})
        self.assertEqual(200, s, d)
        self.assertIn("/ical/", d["url"])
        from urllib.parse import unquote
        token = unquote(d["url"].split("/ical/")[1][:-4])
        ics = self.r._ical_export(token)
        self.assertIn("DTSTART;VALUE=DATE:" + tra.replace("-", ""), ics,
                      "la prenotazione dentro la finestra non compare nel feed: " + ics[:400])
        self.assertIn("DTEND;VALUE=DATE:" + fra.replace("-", ""), ics)

    def test_il_weekend_del_cambio_ora_si_quota_due_notti(self):
        """Nobel tra il 24 e il 25 ottobre 2026 durano 25 ore (si torna a solare): il
        calendario conta GIORNI, non ore -- 24->26 ottobre sono DUE notti, due volte il
        prezzo, e la singola 25->26 e' UNA."""
        s, c = self._quote("casa", "2026-10-24", "2026-10-26")
        self.assertEqual(200, s, c)
        self.assertEqual(2, c["notti"])
        self.assertEqual(2 * PREZZO, c["totale_cents"])
        s, c = self._quote("casa", "2026-10-25", "2026-10-26")
        self.assertEqual(200, s, c)
        self.assertEqual(1, c["notti"])
        self.assertEqual(PREZZO, c["totale_cents"])


if __name__ == "__main__":
    unittest.main()
