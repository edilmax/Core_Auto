"""
Collaudo OSTILE — DENARO: "rimborso su escrow GIA' LIQUIDATO all'host" (perdita a nostro carico).

Tesi sotto attacco: «nessun percorso puo' produrre soldi-senza-stanza, doppio esborso o
perdita a nostro carico».

CAMMINO DI STATI CHE LA VIOLA (trovato 2026-07-28):
  1. l'ospite prenota e PAGA online  -> pendente 'pagato', escrow 'in_garanzia', payout 'maturato';
  2. l'ospite preme "tutto ok" sul voucher (POST /api/garanzia/conferma)
     -> escrow 'rilasciato' con host_riceve = netto host, e `_trasferisci_all_host` manda
        SUBITO il bonifico Connect: i soldi dell'host ESCONO dalla nostra cassa;
  3. lo stesso ospite chiama POST /api/concierge/cancella con lo STESSO voucher.
     `_cancella_prenotazione` non guardava lo stato dell'escrow: ricalcolava il rimborso dalla
     sola politica (flessibile / ripensamento 48h -> 100%) e prometteva all'ospite l'INTERO
     prezzo pagato, mentre la quota host era gia' uscita.
     `gz.annulla()` falliva in silenzio (l'escrow non e' piu' 'in_garanzia') e nessuno se ne
     accorgeva. Risultato: rimborso_ospite + gia_pagato_all_host > incassato = PERDITA SECCA
     della piattaforma, farmabile da una coppia host+ospite complice, a ogni prenotazione.

INVARIANTE DI CASSA (quella che la guardia difende):
    rimborso_soggiorno_cents + host_riceve_cents_gia_liquidato  <=  prezzo pagato dall'ospite

FIX ALLA RADICE (fase83_server._cancella_prenotazione): se l'escrow e' gia' DECISO a favore
dell'host ('rilasciato'/'risolto' con host_riceve>0), il rimborso viene TAGLIATO al residuo
che abbiamo ancora in cassa (pagato - gia_liquidato). Il Credito Viaggio resta calcolato sul
trattenuto ORIGINALE (il taglio non conia credito nuovo).

VISTO ROSSO: rimuovendo il taglio, `test_cancella_dopo_conferma_escrow_non_supera_incasso`
fallisce con rimborso 30000 su 30000 incassati e 27000 gia' dell'host.
"""
import json
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

WHSEC = "whsec_escrow_liq"


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://checkout.stripe.test/" + secrets.token_hex(6),
            "id": "cs_test_" + secrets.token_hex(6)}


class TestEscrowGiaLiquidato(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db",
            db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db", db_garanzia=f"{d}/g.db",
            db_tassa_comunale=f"{d}/t.db",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_liq", stripe_webhook_secret=WHSEC,
            stripe_success_url="https://bookinvip.com/grazie.html",
            stripe_cancel_url="https://bookinvip.com/annullato.html"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@liq.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.hid, self.tok = c["host_id"], c["token"]
        s, _ = self.g("POST", "/api/host/pubblica",
                      {"slug": "casa-liq", "titolo": "Casa Liq", "citta": "Roma",
                       "prezzo_notte_cents": 15000, "capacita": 2,
                       "politica_cancellazione": "flessibile"}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 201)
        # ⛔ RELATIVA: due test di questa classe pretendono un soggiorno che deve ANCORA
        # arrivare (il rimborso «pieno» dipende dalla politica flessibile, che guarda
        # quanto manca all'arrivo). Con le date cablate sarebbero diventati rossi da soli
        # il 2026-09-20 e il 2026-10-10 -- misurato il 2026-08-13.
        s, _ = self.g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": "casa-liq", "da": self._fra(1), "a": self._fra(150),
                       "unita_totali": 1, "prezzo_netto_cents": 15000},
                      {"X-Host-Token": self.tok})
        self.assertEqual(s, 200)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, metodo, path, body=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None, headers or {})

    @staticmethod
    def _fra(giorni):
        """Una data scritta come INTENZIONE, non come cifra sul calendario."""
        import datetime
        return (datetime.date.today() + datetime.timedelta(days=giorni)).isoformat()

    def _prenota_e_paga(self, ci, co):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-liq", "check_in": ci, "check_out": co, "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cli@liq.it"})
        self.assertEqual(s, 201, b)
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata":
                                                  {"riferimento": b["riferimento"]}}}})
        sig = firma_di_test(payload, WHSEC, int(time.time()))
        s2, _ = self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                                {"Stripe-Signature": sig})
        self.assertEqual(s2, 200)
        self.assertEqual(self.sys.pagamenti_pendenti.info(b["riferimento"])["stato"], "pagato")
        return b

    # ── IL CAMMINO CHE REFUTAVA LA TESI ───────────────────────────────────────
    def test_cancella_dopo_conferma_escrow_non_supera_incasso(self):
        """Escrow gia' RILASCIATO all'host (l'ospite ha confermato 'tutto ok') e poi
        cancellazione: il rimborso promesso non puo' MAI superare cio' che resta in cassa."""
        b = self._prenota_e_paga(self._fra(20), self._fra(22))
        rif, pagato = b["riferimento"], int(b["prezzo_guest_cents"])

        s, ok = self.g("POST", "/api/garanzia/conferma", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, ok)
        st = self.sys.garanzia.stato(rif)
        self.assertEqual(st["stato"], "rilasciato")
        gia_host = int(st["host_riceve_cents"])
        self.assertGreater(gia_host, 0, "l'escrow deve avere liquidato l'host")

        s, canc = self.g("POST", "/api/concierge/cancella",
                         {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, canc)
        rimborso = int(canc["rimborso_soggiorno_cents"])

        # INVARIANTE DI CASSA: quello che promettiamo all'ospite + quello che l'host ha gia'
        # incassato non puo' superare quello che l'ospite ci ha versato.
        self.assertLessEqual(
            rimborso + gia_host, pagato,
            "PERDITA A NOSTRO CARICO: rimborso %d + gia' all'host %d > incassato %d"
            % (rimborso, gia_host, pagato))
        # e il taglio non deve coniare Credito Viaggio dal nulla
        self.assertEqual(int(canc["credito_viaggio_cents"]), 0,
                         "credito coniato dal taglio anti-perdita")

    def test_cancella_escrow_ancora_in_garanzia_rimborso_pieno_invariato(self):
        """NON-REGRESSIONE: se i soldi sono ANCORA in garanzia (nessuna liquidazione),
        la cancellazione deve continuare a rimborsare per intero secondo la politica."""
        b = self._prenota_e_paga(self._fra(40), self._fra(42))
        rif, pagato = b["riferimento"], int(b["prezzo_guest_cents"])
        self.assertEqual(self.sys.garanzia.stato(rif)["stato"], "in_garanzia")

        s, canc = self.g("POST", "/api/concierge/cancella",
                         {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, canc)
        self.assertEqual(int(canc["rimborso_soggiorno_cents"]), pagato,
                         "il taglio non deve toccare i rimborsi legittimi")
        self.assertEqual(self.sys.garanzia.stato(rif)["stato"], "annullato")

    def test_cancella_dopo_risoluzione_controversia_non_supera_incasso(self):
        """Stessa falla per la via 'risolto': disputa arbitrata (parte all'host, parte
        rimborsata) e poi cancellazione self-service -> il secondo rimborso non puo'
        sommarsi alla quota gia' liquidata all'host."""
        b = self._prenota_e_paga(self._fra(60), self._fra(62))
        rif, pagato = b["riferimento"], int(b["prezzo_guest_cents"])
        s, _ = self.g("POST", "/api/garanzia/contesta",
                      {"voucher_token": b["voucher_token"], "motivo": "wifi assente"})
        self.assertEqual(s, 200)
        # l'arbitro rimborsa 0 all'ospite: tutto all'host
        out = self.sys.garanzia.risolvi(rif, rimborso_ospite_cents=0)
        self.assertTrue(out.get("ok"), out)
        gia_host = int(self.sys.garanzia.stato(rif)["host_riceve_cents"])
        self.assertGreater(gia_host, 0)

        s, canc = self.g("POST", "/api/concierge/cancella",
                         {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200, canc)
        self.assertLessEqual(
            int(canc["rimborso_soggiorno_cents"]) + gia_host, pagato,
            "PERDITA A NOSTRO CARICO dopo controversia risolta a favore dell'host")


    # ── SECONDO CAMMINO: la stessa falla dal lato HOST ────────────────────────
    def test_host_non_puo_cancellare_con_escrow_gia_liquidato(self):
        """L'host che ha GIA' incassato l'escrow non puo' auto-cancellare: rimborserebbe
        il cliente al 100% con i soldi gia' usciti (perdita = netto - penale 15%),
        farmabile da una coppia host+ospite complice."""
        b = self._prenota_e_paga(self._fra(80), self._fra(82))
        rif = b["riferimento"]
        s, _ = self.g("POST", "/api/garanzia/conferma", {"voucher_token": b["voucher_token"]})
        self.assertEqual(s, 200)
        gia_host = int(self.sys.garanzia.stato(rif)["host_riceve_cents"])
        self.assertGreater(gia_host, 0)

        s, out = self.g("POST", "/api/host/cancella", {"riferimento": rif},
                        {"X-Host-Token": self.tok})
        self.assertEqual(s, 409, out)
        self.assertEqual(out.get("errore"), "escrow_gia_liquidato")
        # e NIENTE effetti: niente penale, record ancora 'pagato', date ancora bloccate
        self.assertEqual(self.sys.pagamenti_pendenti.info(rif)["stato"], "pagato")

    def test_host_cancella_normale_invariata(self):
        """NON-REGRESSIONE: con l'escrow ancora in garanzia la cancellazione host
        continua a funzionare (cliente rimborsato 100%, penale all'host)."""
        b = self._prenota_e_paga(self._fra(100), self._fra(102))
        rif = b["riferimento"]
        self.assertEqual(self.sys.garanzia.stato(rif)["stato"], "in_garanzia")
        s, out = self.g("POST", "/api/host/cancella", {"riferimento": rif},
                        {"X-Host-Token": self.tok})
        self.assertEqual(s, 200, out)
        self.assertEqual(out["stato"], "cancellata_host")
        self.assertGreater(int(out["penale_host_cents"]), 0)
        self.assertEqual(self.sys.garanzia.stato(rif)["stato"], "annullato")


if __name__ == "__main__":
    unittest.main()
