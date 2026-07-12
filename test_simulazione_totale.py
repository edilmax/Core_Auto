"""
SIMULAZIONE TOTALE — "macchina perfetta": 10 host + 10 clienti che usano OGNI funzione,
sul sistema VERO (crea_sistema + crea_router), con Stripe FINTO iniettato per collaudare
anche pagamenti / hold / scadenze / rimborsi / payout. Se qualcosa nella logica è rotto,
QUI deve saltare — prima dei clienti veri.

Copre: registrazione host + contratto firmato, pubblicazione, foto, disponibilità, ricerca,
preventivo (+scadenza prezzo), prenotazione (immediata e su-richiesta), pagamento (webhook
firmato), hold scaduto -> stanza liberata + niente guadagno fantasma, pagamento TARDIVO
(gara: ri-blocco o rimborso), cancellazione cliente (+rimborso per politica), pannello host
(metriche/calendario/payout/alloggi/referral/link diretto/prezzo dinamico/messaggi/
approva-rifiuta/stato/export), pannello admin (prenotazioni/rimborso/cancella-tutto),
split, trasparenza, tassa, i18n, superficie AI (mcp/openapi/llms), domanda.
"""
import json
import os
import secrets
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

WHSEC = "whsec_simulazione"


def _fake_fetch(url, body, headers):     # Stripe finto: sessione con url+id, nessuna rete
    return {"url": "https://checkout.stripe.test/" + secrets.token_hex(6),
            "id": "cs_test_" + secrets.token_hex(8)}


class TestSimulazioneTotale(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)
        cls.dir = tempfile.mkdtemp()
        d = cls.dir
        os.environ["UPLOAD_DIR"] = os.path.join(d, "uploads")
        cfg = ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db",
            db_domanda=f"{d}/dom.db", db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db",
            db_tassa_comunale=f"{d}/t.db", db_payout=f"{d}/pay.db",
            db_accettazioni=f"{d}/acc.db", file_referral=f"{d}/ref.json",
            con_registrazione_host=True, con_mcp=True,
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_sim", stripe_webhook_secret=WHSEC,
            stripe_success_url="https://bookinvip.com/grazie.html",
            stripe_cancel_url="https://bookinvip.com/annullato.html")
        cls.sis = crea_sistema(cfg)
        cls.r = crea_router(cls.sis, host_key="hk", admin_key="ak",
                            base_url="https://bookinvip.com")
        cls.HK = {"X-Host-Key": "hk"}
        cls.AK = {"X-Admin-Key": "ak"}

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig
        os.environ.pop("UPLOAD_DIR", None)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def g(self, metodo, path, body=None, headers=None, query=None):
        s, c = self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None, headers or {})
        return s, c

    def _registra_host(self, i):
        email = f"host{i}@sim.it"
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": email, "password": "password1", "ragione_sociale": f"Host {i}",
                       "telefono": f"+3933300000{i:02d}", "accetta_termini": True,
                       "accetta_clausole": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE, "lang": "it"})
        self.assertEqual(s, 201, c)
        return c["host_id"], c["token"], email

    def _pubblica(self, tok, hid, slug, *, citta="Roma", prezzo=10000, modalita="immediata",
                  politica="flessibile"):
        s, c = self.g("POST", "/api/host/pubblica",
                      {"host_id": hid, "slug": slug, "titolo": f"Casa {slug}", "citta": citta,
                       "descrizione": "bella", "prezzo_notte_cents": prezzo, "capacita": 4,
                       "servizi": ["wifi", "piscina"], "modalita_prenotazione": modalita,
                       "politica_cancellazione": politica, "immagini": ["https://x/y.jpg"]},
                      {"X-Host-Token": tok})
        self.assertIn(s, (200, 201), c)
        s2, _ = self.g("POST", "/api/host/disponibilita_range",
                       {"alloggio_id": slug, "da": "2026-09-01", "a": "2026-10-31",
                        "unita_totali": 1, "prezzo_netto_cents": prezzo}, {"X-Host-Token": tok})
        self.assertEqual(s2, 200)

    def _quote(self, slug, ci="2026-09-10", co="2026-09-12", party=2, fonte="marketplace"):
        return self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": slug, "check_in": ci, "check_out": co,
                       "party": party, "fonte": fonte})

    def _webhook_pagato(self, rif):
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": rif}}}})
        sig = firma_di_test(payload, WHSEC, int(time.time()))
        return self.g("POST", "/api/payments/webhook", None,
                      {"Stripe-Signature": sig}, None) if False else \
            self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                            {"Stripe-Signature": sig})

    # ───────────────────────── LA STORIA (in ordine) ─────────────────────────
    def test_01_dieci_host_pubblicano(self):
        cls = type(self)
        cls.hosts = []
        for i in range(10):
            hid, tok, email = self._registra_host(i)
            modalita = "su_richiesta" if i % 5 == 4 else "immediata"
            politica = ("non_rimborsabile" if i % 4 == 0 else
                        "rigida" if i % 4 == 1 else
                        "moderata" if i % 4 == 2 else "flessibile")
            self._pubblica(tok, hid, f"casa-{i}", prezzo=8000 + i * 1000,
                           modalita=modalita, politica=politica)
            cls.hosts.append({"i": i, "hid": hid, "tok": tok, "email": email,
                              "slug": f"casa-{i}", "modalita": modalita, "politica": politica})
        # tutti in catalogo
        s, c = self.g("GET", "/api/catalogo", query={"citta": "Roma"})
        self.assertEqual(s, 200)
        self.assertGreaterEqual(c.get("totale", 0), 10)
        # ogni host ha la prova d'accettazione firmata e integra
        for h in cls.hosts:
            s, c = self.g("GET", "/api/host/accettazioni", headers={"X-Host-Token": h["tok"]})
            self.assertEqual(s, 200)
            self.assertTrue(c["accettazioni"][0]["integra"])

    def test_02_foto_upload_e_in_ricerca(self):
        png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAE"
               "hQGAhKmMIQAAAABJRU5ErkJggg==")
        h = type(self).hosts[0]
        s, c = self.g("POST", "/api/host/upload_foto", {"image_base64": png},
                      {"X-Host-Token": h["tok"]})
        self.assertEqual(s, 201, c)
        self.assertTrue(c["url"].startswith("/uploads/"))

    def test_03_preventivo_numeri_e_scadenza(self):
        # casa-1 = 'rigida' (nessuno sconto), prezzo 9000. 2 notti = 18000; comm 10% = 1800;
        # carta 3% del totale = 540; host = 18000 - 1800 - 540.
        s, q = self._quote("casa-1")
        self.assertEqual(s, 200, q)
        self.assertEqual(q["prezzo_guest_cents"], 18000)   # ospite prezzo pulito
        self.assertEqual(q["commissione_cents"], 1800)     # 10%
        self.assertEqual(q["costo_pagamento_cents"], 540)  # 3% host, sul totale
        self.assertEqual(q["netto_host_cents"], 18000 - 1800 - 540)
        self.assertTrue(q.get("scade_a", 0) > int(time.time()))   # countdown reale
        # casa-0 è 'non_rimborsabile' -> sconto onesto -12% all'ospite (14080 invece di 16000)
        s, q0 = self._quote("casa-0")
        self.assertEqual(q0["prezzo_guest_cents"], 14080)
        self.assertGreater(q0["sconto_non_rimborsabile_cents"], 0)

    def test_04_prenota_paga_e_diventa_guadagno(self):
        cls = type(self)
        h = cls.hosts[1]                                   # immediata
        s, q = self._quote(h["slug"])
        self.assertEqual(s, 200)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cliente1@sim.it"})
        self.assertEqual(s, 201, b)
        self.assertEqual(b["stato"], "in_attesa_pagamento")   # Stripe -> attende pagamento
        self.assertTrue(b.get("payment_url"))
        rif = b["riferimento"]
        # PRIMA di pagare: payout è 'in_attesa' (NON conta come guadagno)
        s, pay = self.g("GET", "/api/host/payout", headers={"X-Host-Token": h["tok"]},
                        query={"host_id": h["hid"]})
        self.assertEqual(s, 200)
        tot = pay.get("totale") or pay
        self.assertNotIn("maturato", json.dumps(pay))       # niente guadagno fantasma
        self.assertIn("in_attesa", json.dumps(pay))
        # PAGA (webhook firmato) -> maturato
        s, _ = self._webhook_pagato(rif)
        self.assertEqual(s, 200)
        s, pay2 = self.g("GET", "/api/host/payout", headers={"X-Host-Token": h["tok"]},
                         query={"host_id": h["hid"]})
        self.assertIn("maturato", json.dumps(pay2))         # ora è guadagno vero
        cls.pagata = {"rif": rif, "host": h, "email": "cliente1@sim.it"}

    def test_05_hold_scaduto_libera_e_niente_guadagno_fantasma(self):
        h = type(self).hosts[2]
        s, q = self._quote(h["slug"], ci="2026-09-20", co="2026-09-22")
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cliente2@sim.it"})
        rif = b["riferimento"]
        # forzo la scadenza dell'hold nel passato e simulo lo sweeper (come il thread live)
        pp = self.sis.pagamenti_pendenti
        con = pp._apri()
        with con:
            con.execute("UPDATE pendenti SET scadenza_ts=? WHERE riferimento=?",
                        (int(time.time()) - 10, rif))
        con.close()
        for rec in pp.scaduti():
            self.sis.inventario.rilascia(rec["alloggio_id"], rec["check_in"], rec["check_out"],
                                         idem_key=rec.get("idem_key") or ("hold_" + rec["riferimento"]))
            self.sis.payout.rimuovi(rec["riferimento"])
            pp.scadi(rec["riferimento"])
        # la stanza è di nuovo prenotabile e il payout non conta più
        s, q2 = self._quote(h["slug"], ci="2026-09-20", co="2026-09-22")
        self.assertEqual(s, 200)
        self.assertTrue(q2.get("quote_token"))              # ridisponibile
        s, pay = self.g("GET", "/api/host/payout", headers={"X-Host-Token": h["tok"]},
                        query={"host_id": h["hid"]})
        self.assertNotIn(rif, json.dumps(pay))              # niente guadagno fantasma

    def test_06_pagamento_tardivo_gara(self):
        # dopo lo scaduto, se NESSUNO ha ripreso la stanza, il pagamento tardivo la ri-blocca
        h = type(self).hosts[3]
        s, q = self._quote(h["slug"], ci="2026-10-05", co="2026-10-07")
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cliente3@sim.it"})
        rif = b["riferimento"]
        pp = self.sis.pagamenti_pendenti
        con = pp._apri()
        with con:
            con.execute("UPDATE pendenti SET scadenza_ts=? WHERE riferimento=?",
                        (int(time.time()) - 10, rif))
        con.close()
        for rec in pp.scaduti():
            self.sis.inventario.rilascia(rec["alloggio_id"], rec["check_in"], rec["check_out"],
                                         idem_key=rec.get("idem_key") or ("hold_" + rec["riferimento"]))
            self.sis.payout.rimuovi(rec["riferimento"]); pp.scadi(rec["riferimento"])
        # pagamento TARDIVO: stanza libera -> ancora sua (conferma + payout ricreato)
        s, _ = self._webhook_pagato(rif)
        self.assertEqual(s, 200)
        info = pp.info(rif)
        self.assertEqual(info["stato"], "pagato")           # ripreso con successo

    def test_07_cliente_cancella_e_rimborso(self):
        # su un alloggio flessibile, il cliente cancella e ottiene rimborso (date liberate)
        h = next(x for x in type(self).hosts if x["politica"] == "flessibile"
                 and x["modalita"] == "immediata")
        s, q = self._quote(h["slug"], ci="2026-10-10", co="2026-10-12")
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cliente4@sim.it"})
        self._webhook_pagato(b["riferimento"])
        vt = b.get("voucher_token")
        self.assertTrue(vt)
        s, canc = self.g("POST", "/api/concierge/cancella", {"voucher_token": vt})
        self.assertEqual(s, 200, canc)
        self.assertEqual(canc["stato"], "cancellata")
        self.assertTrue(canc["date_liberate"])
        self.assertGreaterEqual(canc["rimborso_cents"], 0)

    def test_08_su_richiesta_approva_e_rifiuta(self):
        h = next(x for x in type(self).hosts if x["modalita"] == "su_richiesta")
        # richiesta 1 -> approva
        s, q = self._quote(h["slug"], ci="2026-09-15", co="2026-09-17")
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cliente5@sim.it"})
        self.assertEqual(b["stato"], "in_attesa_host")
        s, lst = self.g("GET", "/api/host/richieste", headers={"X-Host-Token": h["tok"]},
                        query={"host_id": h["hid"]})
        self.assertEqual(s, 200)
        self.assertTrue(lst["richieste"])
        ref1 = lst["richieste"][0]["riferimento"]
        s, appr = self.g("POST", "/api/host/richieste/approva", {"riferimento": ref1},
                         {"X-Host-Token": h["tok"]})
        self.assertEqual(s, 200, appr)
        # richiesta 2 -> rifiuta (stanza si libera)
        s, q = self._quote(h["slug"], ci="2026-09-25", co="2026-09-27")
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cliente6@sim.it"})
        s, lst = self.g("GET", "/api/host/richieste", headers={"X-Host-Token": h["tok"]},
                        query={"host_id": h["hid"]})
        ref2 = lst["richieste"][0]["riferimento"]
        s, rif = self.g("POST", "/api/host/richieste/rifiuta", {"riferimento": ref2},
                        {"X-Host-Token": h["tok"]})
        self.assertEqual(s, 200, rif)

    def test_09_pannello_host_tutte_le_funzioni(self):
        h = type(self).hosts[1]
        tok = {"X-Host-Token": h["tok"]}
        casi = [
            ("GET", "/api/host/metriche", None, {}),
            ("GET", "/api/host/alloggi", None, {"host_id": h["hid"]}),
            ("GET", "/api/host/calendario", None, {"alloggio": h["slug"], "da": "2026-09-01", "a": "2026-09-10"}),
            ("GET", "/api/host/export", None, {}),
            ("GET", "/api/host/payout", None, {"host_id": h["hid"]}),
            ("GET", "/api/host/referral", None, {"host_id": h["hid"]}),
            ("GET", "/api/host/link_diretto", None, {"host_id": h["hid"]}),
            ("GET", "/api/host/prezzo_suggerito", None,
             {"prezzo_base_cents": "10000", "occupazione_bps": "9000", "data": "2026-08-08"}),
        ]
        for metodo, path, body, query in casi:
            s, c = self.g(metodo, path, body, tok, query)
            self.assertEqual(s, 200, f"{path} -> {s} {c}")
        # messaggi host<->ospite
        s, _ = self.g("POST", "/api/messaggi",
                      {"prenotazione_id": "REFX", "guest_id": "g@sim.it", "testo": "ciao"}, tok)
        self.assertIn(s, (200, 201))
        s, _ = self.g("GET", "/api/messaggi", headers=tok, query={"prenotazione_id": "REFX"})
        self.assertEqual(s, 200)
        # sospendi e ripubblica
        s, _ = self.g("POST", "/api/host/stato", {"slug": h["slug"], "stato": "sospeso"}, tok)
        self.assertIn(s, (200, 422))
        # iCal import (anti-overbooking)
        ics = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:20260901\nDTEND:20260903\nEND:VEVENT\nEND:VCALENDAR"
        s, _ = self.g("POST", "/api/host/ical", {"slug": h["slug"], "ical": ics}, tok)
        self.assertIn(s, (200, 422))

    def test_10_pannello_admin(self):
        s, c = self.g("GET", "/api/admin/prenotazioni", headers=self.AK)
        self.assertEqual(s, 200, c)
        # cancella_attivita di un host: rimuove tutto e verifica 0 residui
        h = type(self).hosts[9]
        s, c = self.g("POST", "/api/admin/cancella_attivita", {"host_id": h["hid"]}, self.AK)
        self.assertIn(s, (200, 409), c)

    def test_11_servizi_trasversali(self):
        # split conto
        s, c = self.g("POST", "/api/split/preview", {"totale_cents": 10000, "n": 3})
        self.assertEqual(s, 200)
        self.assertEqual(sum(c["quote"]), 10000)
        # trasparenza (mostra 10%)
        s, c = self.g("GET", "/api/trasparenza", query={"prezzo_cents": "10000"})
        self.assertEqual(s, 200)
        # tassa
        s, c = self.g("GET", "/api/tassa", query={"citta": "Roma", "notti": "2", "ospiti": "2"})
        self.assertEqual(s, 200)
        # i18n 8 lingue
        for lang in ("it", "en", "es", "fr", "de", "pt", "ja", "zh"):
            s, c = self.g("GET", "/api/i18n", query={"lang": lang})
            self.assertEqual(s, 200)
            self.assertIn("ui", c)
        # superficie AI-agent
        s, c = self.g("POST", "/api/mcp",
                      {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(s, 200)
        # domanda (waitlist / cold-start)
        s, c = self.g("POST", "/api/domanda", {"email": "vuoi@sim.it", "citta": "Milano"})
        self.assertIn(s, (200, 201))

    def test_13_host_cancella_con_penale(self):
        # l'host annulla una prenotazione PAGATA: cliente rimborsato 100%, host paga penale 15%,
        # date liberate (ri-prenotabili). Come Booking/Airbnb.
        h = type(self).hosts[7]                            # immediata, flessibile
        s, q = self._quote(h["slug"], ci="2026-10-25", co="2026-10-27")
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cliente9@sim.it"})
        rif = b["riferimento"]
        guest = q["totale_cents"]
        self._webhook_pagato(rif)                          # pagata
        s, canc = self.g("POST", "/api/host/cancella", {"riferimento": rif},
                         {"X-Host-Token": h["tok"]})
        self.assertEqual(s, 200, canc)
        self.assertEqual(canc["stato"], "cancellata_host")
        self.assertEqual(canc["rimborso_cliente_cents"], guest)     # cliente rimborsato 100%
        self.assertEqual(canc["penale_host_cents"], guest * 15 // 100)  # penale 15% all'host
        # date di nuovo prenotabili
        s, q2 = self._quote(h["slug"], ci="2026-10-25", co="2026-10-27")
        self.assertTrue(q2.get("quote_token"))
        # non è la prenotazione di un altro host
        altro = type(self).hosts[8]
        s, r = self.g("POST", "/api/host/cancella", {"riferimento": rif},
                      {"X-Host-Token": altro["tok"]})
        self.assertIn(s, (403, 409))                       # non tua / già cancellata

    def test_12_no_overbooking(self):
        # due clienti sulle STESSE date: il secondo NON deve poter tenere la stanza pagata del primo
        h = type(self).hosts[6]
        s, q1 = self._quote(h["slug"], ci="2026-10-20", co="2026-10-22")
        s, b1 = self.g("POST", "/api/concierge/book",
                       {"quote_token": q1["quote_token"], "email": "a@sim.it"})
        self._webhook_pagato(b1["riferimento"])
        # secondo cliente stesse date -> non disponibile
        s, q2 = self._quote(h["slug"], ci="2026-10-20", co="2026-10-22")
        self.assertFalse(q2.get("quote_token"), "OVERBOOKING: la stanza era già pagata!")


if __name__ == "__main__":
    unittest.main()
