"""
Test "approva/rifiuta prenotazione da un messaggio" (link firmato, canale-agnostico).
L'host riceve una richiesta su-richiesta e la APPROVA/RIFIUTA con UN link (email/Telegram/
WhatsApp), senza login: il link è firmato HMAC, scade, verifica la proprietà. Approvando,
le date si bloccano (calendario/pannello aggiornati). Copre anche link scaduto/non valido/altrui.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlparse

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, pagina_azione_html
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

SEG = b"S" * 32


class TestAzioneRichiesta(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db",
            db_pendenti=f"{d}/p.db"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@sim.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.hid, self.tok = c["host_id"], c["token"]
        s, p = self.g("POST", "/api/host/pubblica",
                      {"slug": "casa-sr", "titolo": "Casa SR", "citta": "Roma",
                       "prezzo_notte_cents": 10000, "capacita": 2,
                       "modalita_prenotazione": "su_richiesta"}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 201, p)
        s, _ = self.g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": "casa-sr", "da": "2026-09-01", "a": "2026-10-31",
                       "unita_totali": 1, "prezzo_netto_cents": 10000}, {"X-Host-Token": self.tok})
        self.assertEqual(s, 200)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, metodo, path, body=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None, headers or {})

    def _richiedi(self, ci="2026-09-10", co="2026-09-12"):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa-sr", "check_in": ci, "check_out": co, "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "cliente@sim.it"})
        self.assertEqual(s, 201, b)
        self.assertEqual(b["stato"], "in_attesa_host")
        return b["riferimento"]

    def _token_da_link(self, link):
        return parse_qs(urlparse(link).query)["t"][0]

    def test_approva_da_link_aggiorna_calendario(self):
        ref = self._richiedi()
        link = self.r._link_azione(ref, self.hid, "approva")
        self.assertIn("/host/azione?t=", link)
        esito = self.r._azione_richiesta(self._token_da_link(link))
        self.assertTrue(esito["ok"], esito)
        self.assertEqual(esito["stato"], "approvata")
        # date ora bloccate: una nuova richiesta sulle STESSE date non è disponibile
        s, q2 = self.g("POST", "/api/concierge/quote",
                       {"alloggio_id": "casa-sr", "check_in": "2026-09-10",
                        "check_out": "2026-09-12", "party": 2})
        self.assertFalse(q2.get("quote_token"), "le date dovevano essere bloccate dopo l'approvazione")
        # la richiesta non è più tra quelle da approvare
        s, lst = self.g("GET", "/api/host/richieste", headers={"X-Host-Token": self.tok},
                        query={"host_id": self.hid})
        self.assertNotIn(ref, [x["riferimento"] for x in lst["richieste"]])

    def test_rifiuta_da_link_libera_le_date(self):
        ref = self._richiedi(ci="2026-09-15", co="2026-09-17")
        link = self.r._link_azione(ref, self.hid, "rifiuta")
        esito = self.r._azione_richiesta(self._token_da_link(link))
        self.assertTrue(esito["ok"], esito)
        self.assertEqual(esito["stato"], "rifiutata")
        # date di nuovo libere -> nuova quota possibile
        s, q2 = self.g("POST", "/api/concierge/quote",
                       {"alloggio_id": "casa-sr", "check_in": "2026-09-15",
                        "check_out": "2026-09-17", "party": 2})
        self.assertTrue(q2.get("quote_token"))

    def test_link_non_valido(self):
        self.assertFalse(self.r._azione_richiesta("spazzatura.non.firmata")["ok"])
        self.assertEqual(self.r._azione_richiesta("")["motivo"], "link_non_valido")

    def test_link_scaduto(self):
        ref = self._richiedi(ci="2026-09-20", co="2026-09-22")
        tok = self.sys.firma.codifica({"k": "az_richiesta", "rif": ref, "hid": self.hid,
                                       "az": "approva", "exp": int(time.time()) - 10})
        esito = self.r._azione_richiesta(tok)
        self.assertFalse(esito["ok"])
        self.assertEqual(esito["motivo"], "link_scaduto")

    def test_link_di_altro_host_bloccato(self):
        ref = self._richiedi(ci="2026-09-25", co="2026-09-27")
        tok = self.sys.firma.codifica({"k": "az_richiesta", "rif": ref, "hid": "ALTRO_HOST",
                                       "az": "approva", "exp": int(time.time()) + 3600})
        esito = self.r._azione_richiesta(tok)
        self.assertFalse(esito["ok"])
        self.assertEqual(esito["motivo"], "non_tua")

    def test_pagina_html_esiti(self):
        ok = pagina_azione_html({"ok": True, "azione": "approva", "stato": "approvata"})
        self.assertIn("Prenotazione approvata", ok)
        self.assertIn("calendario", ok.lower())
        scaduto = pagina_azione_html({"ok": False, "motivo": "link_scaduto"})
        self.assertIn("scaduto", scaduto.lower())


if __name__ == "__main__":
    unittest.main()
