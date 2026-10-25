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

VISTO ROSSO (2026-07-28): rimuovendo il taglio, `test_cancella_dopo_conferma_escrow_non_supera_incasso`
falliva con rimborso 30000 su 30000 incassati e 27000 gia' dell'host.

DAL 2026-10-11 ((m) in RIPRENDI_QUI, «autorizzato»): il taglio non bastava. La cancellazione
andava avanti e TOGLIEVA la riga del bonifico dell'host, che senza Stripe collegato non veniva
pagato mai. Ora una prenotazione PAGATA con l'escrow gia' deciso non si cancella dal voucher
(409 escrow_gia_liquidato, lo stesso freno dell'host e dell'admin) e niente cambia; il taglio
resta come seconda difesa per quando l'archivio dei pagamenti non risponde. Guardie viste
rosse: `test_fase83_server.TestUnSoggiornoGiaIniziatoNonSiCancellaDalVoucher`.
"""
import json
import shutil
import tempfile
import time
import unittest
from unittest import mock

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import _istante_checkin, crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE
from test_fase160_escrow_garanzia import nella_finestra

WHSEC = "whsec_escrow_liq"


def _fake_fetch(url, body, headers):
    if not body and "/checkout/sessions/" in url:     # rilettura dello stato (casella 10)
        return {"id": url.rsplit("/", 1)[-1], "payment_status": "paid"}
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
        self.r = crea_router(self.sys, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
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
                              "data": {"object": {"id": "cs_" + b["riferimento"], "metadata":
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
        cancellazione: dal 2026-10-11 ((m), «autorizzato») non passa piu', con lo stesso freno
        dell'host e dell'admin, e non tocca niente. Prima passava col rimborso tagliato al
        tetto di cassa, ma la riga del bonifico dell'host SPARIVA: un host senza Stripe
        collegato (bonifico a mano, come qui) non veniva pagato mai."""
        b = self._prenota_e_paga(self._fra(20), self._fra(22))
        rif = b["riferimento"]

        # dal 14/10 ((ad)) «tutto ok» vale solo dall'arrivo: l'ospite lo preme durante il
        # soggiorno e subito dopo prova a cancellare, tutto dentro le sue 24 ore
        with nella_finestra(self.sys, b["voucher_token"]):
            s, ok = self.g("POST", "/api/garanzia/conferma", {"voucher_token": b["voucher_token"]})
            self.assertEqual(s, 200, ok)
            st = self.sys.garanzia.stato(rif)
            self.assertEqual(st["stato"], "rilasciato")
            gia_host = int(st["host_riceve_cents"])
            self.assertGreater(gia_host, 0, "l'escrow deve avere liquidato l'host")
            bonifico_prima = self.sys.payout.info(rif)

            s, canc = self.g("POST", "/api/concierge/cancella",
                             {"voucher_token": b["voucher_token"]})
        self.assertEqual((s, canc.get("errore")), (409, "escrow_gia_liquidato"), canc)
        # NIENTE effetti: nessun rimborso promesso, pagamento vivo, bonifico dell'host intatto
        self.assertNotIn("rimborso_soggiorno_cents", canc)
        self.assertEqual(self.sys.pagamenti_pendenti.info(rif)["stato"], "pagato")
        self.assertEqual(self.sys.payout.info(rif), bonifico_prima,
                         "il bonifico dell'host e' cambiato con la garanzia gia' sua")

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
        # dal 14/10 ((ad)) la segnalazione vale solo dall'arrivo: tutto dentro le 24 ore
        with nella_finestra(self.sys, b["voucher_token"]):
            s, c = self.g("POST", "/api/garanzia/contesta",
                          {"voucher_token": b["voucher_token"], "motivo": "wifi assente"})
            self.assertEqual(s, 200, c)
            # l'arbitro rimborsa 0 all'ospite: tutto all'host
            out = self.sys.garanzia.risolvi(rif, rimborso_ospite_cents=0)
            self.assertTrue(out.get("ok"), out)
            gia_host = int(self.sys.garanzia.stato(rif)["host_riceve_cents"])
            self.assertGreater(gia_host, 0)
            self.assertLessEqual(gia_host, pagato)
            bonifico_prima = self.sys.payout.info(rif)

            # dal 2026-10-11 ((m)) la cancellazione dopo l'arbitro non passa: l'ha gia' decisa lui
            s, canc = self.g("POST", "/api/concierge/cancella",
                             {"voucher_token": b["voucher_token"]})
        self.assertEqual((s, canc.get("errore")), (409, "escrow_gia_liquidato"), canc)
        self.assertNotIn("rimborso_soggiorno_cents", canc)
        self.assertEqual(self.sys.pagamenti_pendenti.info(rif)["stato"], "pagato")
        self.assertEqual(self.sys.payout.info(rif), bonifico_prima)


    # ── SECONDO CAMMINO: la stessa falla dal lato HOST ────────────────────────
    def test_host_non_puo_cancellare_con_escrow_gia_liquidato(self):
        """L'host che ha GIA' incassato l'escrow non puo' auto-cancellare: rimborserebbe
        il cliente al 100% con i soldi gia' usciti (perdita = netto - penale 15%),
        farmabile da una coppia host+ospite complice."""
        b = self._prenota_e_paga(self._fra(80), self._fra(82))
        rif = b["riferimento"]
        # dal 14/10 ((ad)) «tutto ok» vale solo dall'arrivo: tutto dentro le 24 ore dell'ospite
        with nella_finestra(self.sys, b["voucher_token"]):
            s, c = self.g("POST", "/api/garanzia/conferma", {"voucher_token": b["voucher_token"]})
            self.assertEqual(s, 200, c)
            gia_host = int(self.sys.garanzia.stato(rif)["host_riceve_cents"])
            self.assertGreater(gia_host, 0)

            # a quasi tre mesi dalla registrazione la sessione dell'host e' scaduta: rientra
            s, acc = self.g("POST", "/api/host/login",
                            {"email": "h@liq.it", "password": "password1"})
            self.assertEqual(s, 200, acc)
            s, out = self.g("POST", "/api/host/cancella", {"riferimento": rif},
                            {"X-Host-Token": acc["token"]})
        self.assertEqual(s, 409, out)
        self.assertEqual(out.get("errore"), "escrow_gia_liquidato")
        # e NIENTE effetti: niente penale, record ancora 'pagato', date ancora bloccate
        self.assertEqual(self.sys.pagamenti_pendenti.info(rif)["stato"], "pagato")

    def _rimborso_all_ospite(self, rif):
        """Il rimborso promesso all'ospite, letto dove vive: le righe «rimborso» del giornale (in
        ordine) e la cifra della lista «Rimborsi da eseguire», quella che il pulsante paga."""
        giornale = [int(m["importo_cents"]) for m in self.sys.finanza.movimenti(rif)
                    if (m.get("tipo") or "") == "rimborso"]
        s, lista = self.g("GET", "/api/admin/rimborsi_dovuti", None, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, lista)
        riga = [int(r["dovuto_cents"]) for r in (lista.get("rimborsi") or [])
                if r.get("riferimento") == rif]
        return {"giornale": giornale, "lista": riga}

    def test_al_dopo_la_partenza_l_host_non_cambia_il_rimborso_deciso_dall_arbitro(self):
        """(al), trovato dalla macchina delle combinazioni il 14/10 (`test_macchina_dei_soldi.py
        --una vicino,flessibile,si,piccolo giorno_arrivo:segnala,sblocco_garanzia:tutto_ok,
        sblocco_garanzia:arbitro_100,dopo_partenza:dati_fiscali,dopo_partenza:host_cancella`).
        L'ospite segnala un problema, l'arbitro gli da' il 100% della somma in garanzia (all'host
        zero) e DOPO LA PARTENZA l'host cancella. Il freno di `_host_cancella` guarda solo
        `host_riceve_cents > 0`: con zero all'host non scatta, la cancellazione passa e riscrive
        la decisione dell'arbitro col «100% per cancellazione host». La regola: la cifra decisa
        dall'arbitro resta quella, scritta UNA volta nel giornale, nella lista del pulsante e in
        ogni risposta."""
        ci, co = self._fra(120), self._fra(122)
        b = self._prenota_e_paga(ci, co)
        rif, pagato = b["riferimento"], int(b["prezzo_guest_cents"])
        sblocco = int(self.sys.garanzia.stato(rif)["sblocco_auto_ts"])
        # l'ospite segnala dentro le sue 24 ore; l'arbitro decide appena dopo, come nella macchina
        with nella_finestra(self.sys, b["voucher_token"]):
            s, c = self.g("POST", "/api/garanzia/contesta",
                          {"voucher_token": b["voucher_token"], "motivo": "non corrisponde"})
        self.assertEqual(s, 200, c)
        with mock.patch("time.time", return_value=float(sblocco + 1)):
            s, arb = self.g("POST", "/api/admin/controversia/risolvi",
                            {"riferimento": rif, "percentuale_ospite": 100},
                            {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, arb)
        deciso = int(arb["rimborso_cliente_cents"])
        st = self.sys.garanzia.stato(rif)
        # PREMESSE: la strada e' quella di (al) e non un'altra
        self.assertEqual((st["stato"], int(st["host_riceve_cents"])), ("risolto", 0), st)
        self.assertEqual(deciso, int(st["importo_host_cents"]), arb)
        self.assertLess(deciso, pagato, "PREMESSA NON VALIDA: se l'arbitro desse il prezzo "
                                        "pieno, la cancellazione dell'host non cambierebbe cifra")
        self.assertEqual(self._rimborso_all_ospite(rif),
                         {"giornale": [deciso], "lista": [deciso]},
                         "PREMESSA NON VALIDA: la decisione dell'arbitro non e' scritta dove si "
                         "legge")

        # dopo la partenza: l'host rientra (la sessione del primo accesso e' scaduta) e cancella
        dopo_partenza = _istante_checkin(co, "Europe/Rome") + 86400
        with mock.patch("time.time", return_value=float(dopo_partenza)):
            s, acc = self.g("POST", "/api/host/login",
                            {"email": "h@liq.it", "password": "password1"})
            self.assertEqual(s, 200, acc)
            s, out = self.g("POST", "/api/host/cancella", {"riferimento": rif},
                            {"X-Host-Token": acc["token"]})
        dopo = self._rimborso_all_ospite(rif)
        # una risposta che non promette una cifra non contraddice l'arbitro
        dopo["risposta"] = int(out.get("rimborso_cliente_cents", deciso))
        self.assertEqual(dopo, {"giornale": [deciso], "lista": [deciso], "risposta": deciso},
                         "(al) LA CANCELLAZIONE DELL'HOST DOPO LA PARTENZA HA RISCRITTO LA "
                         "DECISIONE DELL'ARBITRO: l'ospite ha pagato %d, l'arbitro gli ha dato "
                         "%d; la cancellazione ha risposto %d %r" % (pagato, deciso, s, out))

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
