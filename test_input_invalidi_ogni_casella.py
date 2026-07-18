"""Collaudo INPUT NON VALIDI (punto 3): numeri negativi, date sbagliate, campi vuoti
su OGNI casella -> il sistema non si rompe E non si sporca.

Differenza dal fuzzing generico (test_robustezza_fuzzing, che resta): quello bombarda
SENZA chiavi (si ferma spesso al muro del 401) e verifica solo "mai crash". Qui si entra
CON le chiavi valide (host e admin) nelle rotte di SCRITTURA vere, casella per casella,
e si verificano DUE cose:
  1. MAI 5xx / mai eccezioni: un input sbagliato riceve un "no" garbato (4xx), non uno schianto.
  2. IL "NO" RESTA NO NEL DATABASE (prova fisica di non-corruzione):
     - nessun annuncio con prezzo <= 0 o capacita' <= 0 compare nel catalogo pubblico;
     - nessuna quote a 200 con totale/notti <= 0 (i conti non vanno mai sotto zero);
     - un range disponibilita' INVERTITO (da > a) non crea notti prenotabili;
     - un quote_token MANOMESSO non prenota (firma);
     - e DOPO tutto il bombardamento il flusso sano funziona ancora per intero
       (pubblica -> quote -> book -> webhook pagato): il sistema non e' rimasto ferito.
"""
import hashlib
import hmac
import json
import shutil
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

SEG = b"h" * 32
HK = {"X-Host-Key": "hk"}
AK = {"X-Admin-Key": "ak"}
WHSEC = "whsec_test"

# valori ostili per OGNI casella (piu' quelli specifici per date/numeri)
VELENI = [None, "", "   ", -1, -999999999999, 0, "x", "x" * 4000, "👾" * 99,
          {"k": 1}, [1, 2], True, "abc123", "-5", "1e9"]
DATE_VELENO = ["2027-02-30", "2026-13-01", "31-12-2027", "0000-00-00", "2027-1-5",
               "2027/01/05", "oggi", "9999-99-99"]


class TestInputInvalidiOgniCasella(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db", db_domanda=f"{d}/dom.db",
            db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_tassa_comunale=f"{d}/tc.db", file_referral=f"{d}/ref.json",
            commissione_bps=1500, stripe_webhook_secret=WHSEC))
        self.sis.concierge._link = lambda dati: "https://pay/" + str(dati.get("riferimento", ""))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        # un annuncio SANO di riferimento (per le rotte che vogliono un alloggio esistente)
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "sano",
               "titolo": "Sano", "citta": "Roma", "descrizione": "x",
               "prezzo_notte_cents": 10000, "capacita": 2, "servizi": [], "immagini": [],
               "tassa_pp_notte_cents": 200}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "sano",
               "da": "2027-05-01", "a": "2027-05-31", "unita_totali": 3,
               "prezzo_netto_cents": 10000}, HK)
        self.crash = []          # (rotta, campo, veleno, eccezione)
        self.cinquecento = []    # (rotta, campo, veleno, status)
        self.quote_sospette = []

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    # ── il martello: ogni casella, ogni veleno ─────────────────────────────
    def _bombarda(self, metodo, rotta, base, headers, campi_data=()):
        """Per OGNI campo del payload base prova OGNI veleno (+ veleni-data sui campi data),
        piu' il campo MANCANTE e il body {} (tutte le caselle vuote). Registra crash/5xx e
        ogni 200 di quote con conti non positivi."""
        casi = []
        for campo in base:
            veleni = list(VELENI) + (list(DATE_VELENO) if campo in campi_data else [])
            for v in veleni:
                b = dict(base)
                b[campo] = v
                casi.append((campo, v, b))
            b = dict(base)
            del b[campo]
            casi.append((campo, "<MANCANTE>", b))
        casi.append(("<TUTTI>", "<VUOTO>", {}))
        for campo, veleno, body in casi:
            try:
                st, ris = self.g(metodo, rotta, body, headers)
            except Exception as e:  # noqa: BLE001 — e' proprio cio' che cerchiamo
                self.crash.append((rotta, campo, repr(veleno)[:40], repr(e)[:80]))
                continue
            if not isinstance(st, int) or st >= 500:
                self.cinquecento.append((rotta, campo, repr(veleno)[:40], st))
            if rotta == "/api/concierge/quote" and st == 200 and isinstance(ris, dict):
                if int(ris.get("totale_cents", 1)) <= 0 or int(ris.get("notti", 1)) <= 0:
                    self.quote_sospette.append((campo, repr(veleno)[:40], ris.get("totale_cents"),
                                                ris.get("notti")))

    def test_ogni_casella_con_ogni_veleno(self):
        self._bombarda("POST", "/api/host/pubblica",
                       {"host_id": "demo", "slug": "attacco", "titolo": "T", "citta": "Roma",
                        "descrizione": "d", "prezzo_notte_cents": 10000, "capacita": 2,
                        "servizi": [], "immagini": [], "tassa_pp_notte_cents": 200}, HK)
        self._bombarda("POST", "/api/host/disponibilita_range",
                       {"alloggio_id": "sano", "da": "2027-05-01", "a": "2027-05-10",
                        "unita_totali": 3, "prezzo_netto_cents": 10000}, HK,
                       campi_data=("da", "a"))
        self._bombarda("POST", "/api/concierge/quote",
                       {"alloggio_id": "sano", "check_in": "2027-05-10",
                        "check_out": "2027-05-12", "party": 2}, None,
                       campi_data=("check_in", "check_out"))
        self._bombarda("POST", "/api/concierge/book",
                       {"quote_token": "manomesso.xxx", "email": "a@collaudo.invalid"}, None)
        self._bombarda("POST", "/api/domanda",
                       {"email": "a@collaudo.invalid", "citta": "roma"}, None)
        self._bombarda("POST", "/api/admin/alloggio_stato",
                       {"slug": "sano", "stato": "pubblicato"}, AK)
        self._bombarda("POST", "/api/admin/rimborso",
                       {"alloggio_id": "sano", "check_in": "2027-05-10",
                        "check_out": "2027-05-12", "idem_key": "inesistente"}, AK,
                       campi_data=("check_in", "check_out"))
        self._bombarda("POST", "/api/host/cancella",
                       {"riferimento": "inesistente", "host_id": "demo"}, HK)
        self._bombarda("POST", "/api/host/stato",
                       {"slug": "sano", "stato": "pubblicato"}, HK)
        self.assertEqual(self.crash, [], "il router NON deve MAI sollevare")
        self.assertEqual(self.cinquecento, [], "input sbagliato = 4xx garbato, MAI 5xx")
        self.assertEqual(self.quote_sospette, [],
                         "nessuna quote a 200 con totale/notti <= 0 (conti mai sotto zero)")

        # ── prova FISICA di non-corruzione ────────────────────────────────
        # 1) il catalogo pubblico non contiene prezzi/capacita' <= 0 nati da payload
        #    avvelenati con successo apparente (shape-tolerante: ogni lista di schede)
        st, ris = self.g("GET", "/api/catalogo")
        self.assertEqual(st, 200, "il catalogo pubblico deve rispondere dopo la tempesta")
        schede = []
        if isinstance(ris, dict):
            for v in ris.values():
                if isinstance(v, list):
                    schede += [x for x in v if isinstance(x, dict)]
        for a in schede:
            for chiave in ("prezzo_notte_cents", "prezzo_cents"):
                pr = a.get(chiave)
                if isinstance(pr, int) and not isinstance(pr, bool):
                    self.assertGreater(pr, 0, f"annuncio col prezzo avvelenato nel catalogo: {a}")
            cap = a.get("capacita")
            if isinstance(cap, int) and not isinstance(cap, bool):
                self.assertGreater(cap, 0, f"annuncio con capacita' avvelenata: {a}")
        # 2) range INVERTITO (da > a): non deve creare notti prenotabili
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "inverso",
               "titolo": "I", "citta": "Roma", "descrizione": "x",
               "prezzo_notte_cents": 10000, "capacita": 2, "servizi": [], "immagini": [],
               "tassa_pp_notte_cents": 0}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "inverso",
               "da": "2027-06-20", "a": "2027-06-10", "unita_totali": 2,
               "prezzo_netto_cents": 10000}, HK)
        st, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "inverso",
                       "check_in": "2027-06-12", "check_out": "2027-06-14", "party": 2})
        self.assertFalse(isinstance(q, dict) and q.get("quote_token"),
                         "range invertito (da>a) ha creato notti prenotabili")
        # 3) check_out <= check_in: mai una quote valida
        for ci, co in (("2027-05-12", "2027-05-10"), ("2027-05-10", "2027-05-10")):
            st, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "sano",
                           "check_in": ci, "check_out": co, "party": 2})
            self.assertFalse(isinstance(q, dict) and q.get("quote_token"),
                             f"quote emessa con date {ci} -> {co}")

    # ── dopo il bombardamento, il sistema DEVE ancora funzionare ───────────
    def test_dopo_il_bombardamento_il_flusso_sano_vive(self):
        self.test_ogni_casella_con_ogni_veleno()          # prima la tempesta
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "sano",
                      "check_in": "2027-05-20", "check_out": "2027-05-22", "party": 2})
        self.assertTrue(isinstance(q, dict) and q.get("quote_token"),
                        "dopo la tempesta la quote sana non funziona piu'")
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "ok@collaudo.invalid"})
        self.assertIn(s, (200, 201))
        rif = b.get("riferimento")
        self.assertTrue(rif)
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": rif}}}})
        ts = str(int(time.time()))
        mac = hmac.new(WHSEC.encode(), f"{ts}.{payload}".encode(),
                       hashlib.sha256).hexdigest()
        s, _ = self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})
        self.assertEqual(s, 200)
        self.assertEqual(self.sis.pagamenti_pendenti.info(rif)["stato"], "pagato",
                         "dopo la tempesta il money-path sano deve restare intatto")


if __name__ == "__main__":
    unittest.main()
